"""The recorded-review builder (008 T013).

`tests/support/replay.record_scripted_review` writes a real review run folder - a copy of
`package.json`, `session.json`, `events.jsonl` - by playing a script of recorded-style rounds
through the current code with the scripted provider. Every replay test (T015, T019 to T021)
and the fixture generator (T018) build their recordings with it, so the usage it writes has to
follow the accounting the replay prices with: by default each round costs
`11_006 + the outputs so far + the engineer's words so far + Σ(count_tokens(tool_result_text(
result)) + FRAMING_TOKENS)` over the results the round is sent with. It writes in two passes:
the first, in a scratch folder, learns each round's results; the second writes the folder with
each round's usage computed from them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers import (
    FRAMING_TOKENS,
    TokenUsage,
    model_payload,
    tool_result_text,
)
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.runner import ANSWER_MESSAGE
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.replay import PlayedRound, TurnPlan
from swreview.ir.loader import load_package, save_package
from swreview.tokens import count_tokens
from swreview.tools.context import context_for
from swreview.tools.registry import ToolRegistry
from tests.support.prerun import prerun_package
from tests.support.replay import (
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_PREFIX_TOKENS,
    record_scripted_review,
    usage,
)

pytestmark = pytest.mark.usefixtures("vocabulary")

SUMMARY = ScriptedToolCall("get_package_summary")
COMPONENTS = ScriptedToolCall("list_components", {"parent_id": None, "include_suppressed": True})
HOLES = ScriptedToolCall("list_holes", {"component_id": None, "hole_type": None})
RMS_PART = ScriptedToolCall("check_rms_part", {"document_id": None})


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "package"
    save_package(prerun_package(), directory)
    return directory


def events_of(run_dir: Path) -> list[dict[str, Any]]:
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def usage_inputs(run_dir: Path) -> list[int]:
    return [e["body"]["input_tokens"] for e in events_of(run_dir) if e["type"] == "usage"]


def query_text(call: ScriptedToolCall, package_dir: Path) -> str:
    """A pure query's payload through the product's dispatch, computed without the builder."""
    context = context_for(load_package(package_dir).package)
    result = ToolRegistry().dispatch(context).call(call.name, dict(call.arguments))
    return tool_result_text(result.payload)


def cost(text: str) -> int:
    return count_tokens(text) + FRAMING_TOKENS


# --- the folder --------------------------------------------------------------------------


def test_it_writes_a_real_run_folder(tmp_path: Path, package_dir: Path) -> None:
    out = record_scripted_review(
        tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),), text="Done.")]
    )

    assert {"package.json", "session.json", "events.jsonl"} <= {p.name for p in out.iterdir()}
    assert (out / "package.json").read_bytes() == (package_dir / "package.json").read_bytes()
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert [step["tool"] for step in session["steps"]] == ["get_package_summary"]


def test_the_scratch_pass_leaves_nothing_behind_but_the_folder(
    tmp_path: Path, package_dir: Path
) -> None:
    record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])

    assert sorted(p.name for p in tmp_path.iterdir()) == ["package", "run"]


# --- the default accounting ----------------------------------------------------------------


def test_serial_rounds_cost_what_the_accounting_says(tmp_path: Path, package_dir: Path) -> None:
    out = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)), text="Done.")],
    )

    summary = query_text(SUMMARY, package_dir)
    components = query_text(COMPONENTS, package_dir)
    base = DEFAULT_PREFIX_TOKENS
    assert usage_inputs(out) == [
        base,
        base + DEFAULT_OUTPUT_TOKENS + cost(summary),
        base + 2 * DEFAULT_OUTPUT_TOKENS + cost(summary) + cost(components),
    ]


def test_each_rounds_usage_precedes_its_calls(tmp_path: Path, package_dir: Path) -> None:
    out = record_scripted_review(
        tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))]
    )

    kinds = [e["type"] for e in events_of(out) if e["type"] in ("usage", "tool.started")]
    assert kinds == ["usage", "tool.started", "usage", "tool.started", "usage"]


def test_a_round_of_several_calls_is_one_round(tmp_path: Path, package_dir: Path) -> None:
    out = record_scripted_review(
        tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY, COMPONENTS), (HOLES,)))]
    )

    summary = query_text(SUMMARY, package_dir)
    components = query_text(COMPONENTS, package_dir)
    holes = query_text(HOLES, package_dir)
    base = DEFAULT_PREFIX_TOKENS
    assert usage_inputs(out) == [
        base,
        base + DEFAULT_OUTPUT_TOKENS + cost(summary) + cost(components),
        base + 2 * DEFAULT_OUTPUT_TOKENS + cost(summary) + cost(components) + cost(holes),
    ]


def test_a_follow_up_adds_the_engineers_words(tmp_path: Path, package_dir: Path) -> None:
    question = "Which holes did you look at?"
    out = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,),), text="Done."),
            TurnPlan(kind="follow_up", user_text=question, rounds=((HOLES,),), text="These."),
        ],
    )

    summary = query_text(SUMMARY, package_dir)
    inputs = usage_inputs(out)
    assert inputs[2] == inputs[1] + DEFAULT_OUTPUT_TOKENS + count_tokens(question)
    assert inputs[1] == DEFAULT_PREFIX_TOKENS + DEFAULT_OUTPUT_TOKENS + cost(summary)


def test_an_answered_evidence_request_resumes_on_the_answer(
    tmp_path: Path, package_dir: Path
) -> None:
    ask = ScriptedToolCall(
        "request_evidence",
        {"what": "the drawing", "why": "fit check", "entity_ids": ["cmp:0002"]},
    )
    answer = "The drawing is attached."
    out = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [
            TurnPlan(rounds=((ask,),), text="Asked."),
            TurnPlan(kind="answer", answers=(("ER-001", answer),), text="Thanks."),
        ],
    )

    events = events_of(out)
    answered = [e["body"] for e in events if e["type"] == "evidence.answered"]
    assert answered == [{"request_id": "ER-001", "answer": answer}]
    inputs = usage_inputs(out)
    message = ANSWER_MESSAGE.format(request_id="ER-001", answer=answer)
    assert inputs[2] == inputs[1] + DEFAULT_OUTPUT_TOKENS + count_tokens(message)
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert session["evidence_requests"][0]["status"] == "answered"


def test_a_stopped_turn_leaves_its_last_call_dangling(tmp_path: Path, package_dir: Path) -> None:
    out = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [
            TurnPlan(
                rounds=((SUMMARY,), (COMPONENTS,)), end_reason="stopped", stop_at_last_call=True
            )
        ],
    )

    events = events_of(out)
    started = [e["body"]["step_index"] for e in events if e["type"] == "tool.started"]
    finished = [e["body"]["step_index"] for e in events if e["type"] == "tool.finished"]
    assert started == [0, 1]
    assert finished == [0]
    ends = [e["body"]["reason"] for e in events if e["type"] == "turn.ended"]
    assert ends == ["stopped"]
    assert events[-1]["type"] == "session.ended"
    assert len(usage_inputs(out)) == 2


def test_a_presentation_request_is_recorded_after_the_text(
    tmp_path: Path, package_dir: Path
) -> None:
    presentation = TokenUsage(
        input_tokens=1_874,
        cached_input_tokens=0,
        cache_write_tokens=None,
        output_tokens=519,
        reasoning_tokens=0,
        tool_result_input_tokens=None,
        total_tokens=2_393,
        latency_s=0.5,
    )
    out = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((RMS_PART,),), text="Found some.")],
        presentation=presentation,
    )

    order = [e["type"] for e in events_of(out) if e["type"] in ("usage", "text.done", "turn.ended")]
    assert order == ["usage", "usage", "text.done", "usage", "turn.ended"]
    assert usage_inputs(out)[-1] == 1_874


def test_a_lever_5_pre_run_writes_its_steps_before_the_first_usage(
    tmp_path: Path, package_dir: Path
) -> None:
    out = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((SUMMARY,),))],
        efficiency=EfficiencySettings(prerun_checks=True),
    )

    events = events_of(out)
    first_usage = next(i for i, e in enumerate(events) if e["type"] == "usage")
    early = [e for e in events[:first_usage] if e["type"] == "tool.started"]
    assert early, "the pre-run's calls come before the model's first round"
    model_steps = [
        e["body"]["step_index"] for e in events[first_usage:] if e["type"] == "tool.started"
    ]
    assert model_steps == [len(early)]
    assert usage_inputs(out)[0] == DEFAULT_PREFIX_TOKENS


# --- a custom usage ------------------------------------------------------------------------


def test_usage_for_decides_every_rounds_usage(tmp_path: Path, package_dir: Path) -> None:
    seen: list[PlayedRound] = []

    def usage_for(played: PlayedRound) -> TokenUsage:
        seen.append(played)
        return TokenUsage(
            input_tokens=1_000 * (played.turn + 1) + played.index,
            cached_input_tokens=None,
            cache_write_tokens=None,
            output_tokens=7,
            reasoning_tokens=None,
            tool_result_input_tokens=None,
            total_tokens=None,
            latency_s=0.0,
        )

    out = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))],
        usage_for=usage_for,
    )

    assert usage_inputs(out) == [1_000, 1_001, 1_002]
    assert [len(played.visible) for played in seen] == [0, 1, 2]
    assert [played.prior_rounds for played in seen] == [0, 1, 2]


# --- the neutral history each round carries (008 T078, T079) --------------------------------


def played_rounds(tmp_path: Path, package_dir: Path, turns: list[TurnPlan]) -> list[PlayedRound]:
    """Every round of `turns` as the builder's first pass played it."""
    seen: list[PlayedRound] = []

    def usage_for(played: PlayedRound) -> TokenUsage:
        seen.append(played)
        return usage(1_000)

    record_scripted_review(tmp_path / "run", package_dir, turns, usage_for=usage_for)
    return seen


def roles(played: PlayedRound) -> list[str]:
    return [str(message["role"]) for message in played.history]


def test_a_round_carries_the_adapters_neutral_history(tmp_path: Path, package_dir: Path) -> None:
    """One assistant message per round asking for its calls, each result as the model reads
    it, a committed turn's closing answer and the engineer's messages: the shape every
    adapter's history has, which the replay prunes with the adapters' own function."""
    seen = played_rounds(
        tmp_path,
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,), (COMPONENTS, HOLES)), text="Done."),
            TurnPlan(kind="follow_up", user_text="And the holes?", rounds=((HOLES,),), text="Ok."),
        ],
    )

    [follow_up] = [played for played in seen if (played.turn, played.index) == (1, 0)]
    assert roles(follow_up) == [
        "user", "assistant", "tool", "assistant", "tool", "tool", "assistant", "user"
    ]
    assert follow_up.history[-2] == {"role": "assistant", "content": "Done."}
    assert follow_up.history[-1] == {"role": "user", "content": "And the holes?"}
    tools = [message for message in follow_up.history if message["role"] == "tool"]
    assert [message["name"] for message in tools] == [call.tool for call in follow_up.visible]
    assert [message["content"] for message in tools] == [
        model_payload(call.result) for call in follow_up.visible
    ]
    asked = [
        [call["name"] for call in message["tool_calls"]]
        for message in follow_up.history
        if message["role"] == "assistant" and "tool_calls" in message
    ]
    assert asked == [["get_package_summary"], ["list_components", "list_holes"]]


def test_the_rounds_of_one_turn_grow_the_history_round_by_round(
    tmp_path: Path, package_dir: Path
) -> None:
    seen = played_rounds(
        tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)), text="Done.")]
    )

    assert [roles(played) for played in seen] == [
        ["user"],
        ["user", "assistant", "tool"],
        ["user", "assistant", "tool", "assistant", "tool"],
    ]
    assert seen[0].history[0]["role"] == "user" and seen[0].history[0]["content"]


def test_a_stopped_turn_leaves_only_its_engineer_message_behind(
    tmp_path: Path, package_dir: Path
) -> None:
    """The runner keeps the message it appended before the turn, and none of a turn that did
    not return; so the next request carries two engineer messages and no stopped result."""
    seen = played_rounds(
        tmp_path,
        package_dir,
        [
            TurnPlan(
                rounds=((SUMMARY,), (COMPONENTS,)), end_reason="stopped", stop_at_last_call=True
            ),
            TurnPlan(kind="follow_up", user_text="Go on.", rounds=((HOLES,),), text="Ok."),
        ],
    )

    [follow_up] = [played for played in seen if (played.turn, played.index) == (1, 0)]
    assert roles(follow_up) == ["user", "user"]
    assert follow_up.visible == ()


def test_a_turn_cut_at_its_budget_has_no_closing_answer(tmp_path: Path, package_dir: Path) -> None:
    seen = played_rounds(
        tmp_path,
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,),), end_reason="max_steps"),
            TurnPlan(kind="follow_up", user_text="Go on.", rounds=((HOLES,),), text="Ok."),
        ],
    )

    [follow_up] = [played for played in seen if (played.turn, played.index) == (1, 0)]
    assert roles(follow_up) == ["user", "assistant", "tool", "user"]


def test_an_answer_turn_opens_on_the_runners_answer_message(
    tmp_path: Path, package_dir: Path
) -> None:
    ask = ScriptedToolCall(
        "request_evidence",
        {"what": "the drawing", "why": "fit check", "entity_ids": ["cmp:0002"]},
    )
    seen = played_rounds(
        tmp_path,
        package_dir,
        [
            TurnPlan(rounds=((ask,),), text="Need a drawing."),
            TurnPlan(kind="answer", answers=(("ER-001", "It is rev B."),), text="Thanks."),
        ],
    )

    [answer] = [played for played in seen if played.turn == 1]
    assert answer.history[-1] == {
        "role": "user",
        "content": ANSWER_MESSAGE.format(request_id="ER-001", answer="It is rev B."),
    }


# --- determinism ---------------------------------------------------------------------------

VOLATILE = re.compile(
    r'"(session_id|at|started_at|ended_at|elapsed_s|answered_at|finding_explanation_fingerprint)"'
    r':\s*("[^"]*"|[0-9.e+-]+|null)'
)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def normalized(path: Path) -> str:
    text = VOLATILE.sub(lambda m: f'"{m.group(1)}": "*"', path.read_text(encoding="utf-8"))
    text = re.sub(r'"timing":\s*\{[^}]*\}', '"timing": "*"', text)
    return UUID.sub("<uuid>", text)


def test_two_builds_of_one_script_are_identical_but_for_ids_and_times(
    tmp_path: Path, package_dir: Path
) -> None:
    turns = [
        TurnPlan(rounds=((SUMMARY, COMPONENTS), (RMS_PART,)), text="Done."),
        TurnPlan(kind="follow_up", user_text="And the holes?", rounds=((HOLES,),), text="Yes."),
    ]
    first = record_scripted_review(tmp_path / "one", package_dir, turns)
    second = record_scripted_review(tmp_path / "two", package_dir, turns)

    for name in ("package.json", "session.json", "events.jsonl"):
        assert normalized(first / name) == normalized(second / name), name


def test_an_existing_folder_is_refused(tmp_path: Path, package_dir: Path) -> None:
    out = tmp_path / "run"
    out.mkdir()
    (out / "session.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        record_scripted_review(out, package_dir, [TurnPlan(rounds=((SUMMARY,),))])
