"""The replay's accounting (008 T019, `contracts/replay.md` §4, research R2.5 and R2.6).

Every round is priced as the recorded first-round input, plus the difference the requested
settings make to the prefix, plus the recorded output of every earlier round in the history,
plus the engineer's words, plus every visible result counted with the one tokenizer over the one
serialization and twelve framing tokens. The recordings here are built by the scripted builder,
whose usage follows exactly that formula, so pass A must reproduce every round to the token;
the estimation rules (a call the current code cannot reproduce is sized from the recorded
growth, shared equally, or a lower bound when the growth cannot be seen) are pinned against
recordings with a live bridge the replay does not have. The replay writes nothing into the
folder it reads.

User Story 3 (T078): with a model view requested, each round counts the tool messages of its
own neutral history as the adapters send them - through `prune_history`, compact - and pass A
reads the recording's own view; a call the replay cannot run is sized from its stored result
when the run folder keeps one for this session, and an estimated one becomes a stub on the
adapters' schedule, priced at the part of the stub the replay can know.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from swreview.agent.providers import FRAMING_TOKENS, TokenUsage, tool_result_text
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.providers.pruning import PRUNED_NOTE, prune_history, result_stub
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE, EfficiencySettings
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import (
    PlayedRound,
    ReplayReport,
    TurnPlan,
    estimated_sizes,
    replay,
    replay_passes,
    report_of,
)
from swreview.ir.loader import save_package
from swreview.tokens import count_tokens
from swreview.tools.model_view import model_view
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME
from tests.support.prerun import prerun_package
from tests.support.replay import (
    ALL_OFF,
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_PREFIX_TOKENS,
    folder_hashes,
    record_scripted_review,
    rewrite_session,
    usage,
    without_stored_results,
)
from tests.support.review_bridge import (
    RECORDED_INTERFERENCE_SETTINGS,
    VOLUME_UNIT_GAP,
    ScriptedReviewBridge,
    interference_row,
)

pytestmark = pytest.mark.usefixtures("vocabulary")

SUMMARY = ScriptedToolCall("get_package_summary")
COMPONENTS = ScriptedToolCall("list_components", {"parent_id": None, "include_suppressed": True})
HOLES = ScriptedToolCall("list_holes", {"component_id": None, "hole_type": None})
RMS_PART = ScriptedToolCall("check_rms_part", {"document_id": None})
LIVE = ScriptedToolCall(
    "bridge_interference",
    {
        "component_ids": [],
        "configuration": "Default",
        "settings": dict(RECORDED_INTERFERENCE_SETTINGS),
    },
)
ROW = interference_row("int:0101", ("cmp:0002", "cmp:0003"), "cmp:0002|cmp:0003", 12.0)
ANSWER: dict[str, Any] = {"interferences": [ROW], "gaps": [VOLUME_UNIT_GAP]}


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "package"
    save_package(prerun_package(), directory)
    return directory


def with_bridge(answers: int = 1) -> dict[str, Any]:
    return {
        "bridge": True,
        "bridge_factory": lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [ANSWER] * answers}
        ),
    }


def rounds_of(report: ReplayReport) -> list[tuple[int, int, int]]:
    return [(r.recorded_input, r.as_recorded_input, r.requested_input) for r in report.rounds]


# --- pass A reproduces a recording made by the accounting ------------------------------------


def test_pass_a_reproduces_every_round_and_both_totals(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,), (COMPONENTS, HOLES), (RMS_PART,)), text="Done."),
            TurnPlan(kind="follow_up", user_text="And the holes?", rounds=((HOLES,),), text="Ok."),
        ],
    )

    report = replay(run, requested=ALL_OFF)

    assert len(report.rounds) == 6
    assert all(r.as_recorded_input == r.recorded_input for r in report.rounds)
    assert report.totals.as_recorded == report.totals.recorded
    assert report.totals.recorded == sum(r.recorded_input for r in report.rounds)
    assert report.totals.difference == report.totals.requested - report.totals.recorded


def test_the_prefix_difference_is_zero_when_the_settings_are_the_recorded_ones(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(
        tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))]
    )

    report = replay(run, requested=ALL_OFF)

    assert all(r.requested_input == r.as_recorded_input for r in report.rounds)
    assert report.totals.requested == report.totals.as_recorded


def test_the_report_names_its_tokenizer_and_its_framing(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])

    report = replay(run, requested=ALL_OFF)

    assert report.tokenizer == "o200k_base"
    assert report.framing_tokens == FRAMING_TOKENS == 12
    assert report.comparison == "exact"
    assert report.provider == "fake"
    assert report.settings.as_recorded.efficiency == EfficiencySettings()


def test_a_gemini_recording_is_a_shape_comparison(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])

    def gemini(session: dict[str, Any]) -> None:
        session["provider_info"]["provider"] = "gemini"

    rewrite_session(run, gemini)

    assert replay(run, requested=ALL_OFF).comparison == "shape"


def test_the_requested_settings_are_reported(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])
    requested = EfficiencySettings(trim_tool_descriptions=True)

    report = replay(run, requested=(requested, MODEL_VIEW_OFF))

    assert report.settings.requested.efficiency == requested
    assert report.settings.as_recorded.efficiency == EfficiencySettings()


# --- estimation ------------------------------------------------------------------------------


def test_one_estimated_call_is_sized_as_the_growth_minus_the_others_and_framing(
    tmp_path: Path, package_dir: Path
) -> None:
    run = without_stored_results(
        record_scripted_review(
            tmp_path / "run",
            package_dir,
            [TurnPlan(rounds=((SUMMARY, LIVE), (COMPONENTS,)))],
            **with_bridge(),
        )
    )
    recording = read_recording(run)
    first = recording.turns[0].rounds[0]
    summary_step, live_step = (call.step for call in first.calls)
    summary_size = count_tokens(
        _text_of(run, summary_step)  # the current code reproduces the summary exactly
    )

    sizes = estimated_sizes(recording, first, {summary_step: summary_size})

    growth = recording.growth_after(first)
    assert growth is not None
    assert sizes == {live_step: (growth - (summary_size + FRAMING_TOKENS) - FRAMING_TOKENS, False)}
    report = replay(run, requested=ALL_OFF)
    assert [c.class_ for c in report.rounds[0].calls] == ["reproduced", "estimated"]
    assert report.rounds[0].estimated is True
    assert report.rounds[1].as_recorded_input == report.rounds[1].recorded_input
    assert report.totals.estimated_rounds == 1


def test_two_estimated_calls_in_one_round_share_the_rest_equally(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((LIVE, LIVE), (COMPONENTS,)))],
        **with_bridge(answers=2),
    )
    recording = read_recording(run)
    first = recording.turns[0].rounds[0]

    sizes = estimated_sizes(recording, first, {})

    growth = recording.growth_after(first)
    assert growth is not None
    rest = growth - 2 * FRAMING_TOKENS
    values = sorted((size for size, _ in sizes.values()), reverse=True)
    assert sum(values) == rest
    assert values[0] - values[1] in (0, 1)
    assert not any(lower for _, lower in sizes.values())
    report = replay(run, requested=ALL_OFF)
    assert report.rounds[1].as_recorded_input == report.rounds[1].recorded_input


def test_an_unobservable_growth_gives_the_summary_size_as_a_lower_bound(
    tmp_path: Path, package_dir: Path
) -> None:
    run = without_stored_results(
        record_scripted_review(
            tmp_path / "run",
            package_dir,
            [
                TurnPlan(
                    rounds=((SUMMARY,), (LIVE, COMPONENTS)),
                    end_reason="stopped",
                    stop_at_last_call=True,
                )
            ],
            **with_bridge(),
        )
    )
    recording = read_recording(run)
    last = recording.turns[0].rounds[-1]
    [live] = last.calls

    sizes = estimated_sizes(recording, last, {})

    assert sizes == {live.step: (count_tokens(live.summary), True)}
    report = replay(run, requested=ALL_OFF)
    assert report.rounds[-1].lower_bound is True
    assert report.totals.lower_bound_rounds == 1


def test_a_round_whose_calls_are_all_known_needs_no_estimate(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])
    recording = read_recording(run)
    first = recording.turns[0].rounds[0]

    assert estimated_sizes(recording, first, {first.calls[0].step: 5}) == {}


# --- carried rounds and the folder ---------------------------------------------------------


def test_carried_presentation_rounds_are_in_all_three_totals(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((RMS_PART,),), text="Found some.")],
        presentation=usage(1_874, 519),
    )

    report = replay(run, requested=ALL_OFF)

    carried = [r for r in report.rounds if r.kind == "presentation"]
    assert [(r.recorded_input, r.as_recorded_input, r.requested_input) for r in carried] == [
        (1_874, 1_874, 1_874)
    ]
    assert report.totals.carried_rounds == 1
    assert report.totals.recorded == sum(r.recorded_input for r in report.rounds)
    assert report.totals.as_recorded == sum(r.as_recorded_input for r in report.rounds)
    assert report.totals.requested == sum(r.requested_input for r in report.rounds)


def test_the_run_folder_is_byte_identical_before_and_after(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((SUMMARY,), (RMS_PART,)))],
    )
    before = folder_hashes(run)

    replay(run, requested=(EfficiencySettings(prerun_checks=True), MODEL_VIEW_OFF))

    assert folder_hashes(run) == before


def test_the_follow_up_words_come_from_the_recorded_growth(
    tmp_path: Path, package_dir: Path
) -> None:
    question = "Which holes did you look at, and why those?"
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,),), text="Done."),
            TurnPlan(kind="follow_up", user_text=question, text="These."),
        ],
    )

    report = replay(run, requested=ALL_OFF)

    assert rounds_of(report)[-1][0] == rounds_of(report)[-1][1]


# --- the model's view (User Story 3, T078) ------------------------------------------------

PANE_VIEW = (EfficiencySettings(), MODEL_VIEW_PANE)
"""Every lever off and the pane's model view: slimming, and stubs after two rounds."""


def results_by_hand(messages: Sequence[Mapping[str, Any]], *, compact: bool) -> int:
    """Σ over the tool messages of `T(tool_result_text(content)) + FRAMING_TOKENS`."""
    return sum(
        count_tokens(tool_result_text(message["content"], compact=compact)) + FRAMING_TOKENS
        for message in messages
        if message["role"] == "tool"
    )


def pane_sent(played: PlayedRound) -> list[dict[str, Any]]:
    """What an adapter with the pane's view sends for the round: its history, pruned."""
    return prune_history(list(played.history), 2, finding_detail=True)


def is_stub(message: Mapping[str, Any]) -> bool:
    content = message["content"]
    return isinstance(content, Mapping) and content.get("pruned") == PRUNED_NOTE


def test_with_the_view_on_each_round_counts_its_pruned_history_compactly(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,), (COMPONENTS,), (HOLES,), (RMS_PART,)), text="Done."),
            TurnPlan(kind="follow_up", user_text="And the holes?", rounds=((HOLES,),), text="Ok."),
        ],
    )

    passes = replay_passes(read_recording(run), tmp_path / "scratch", requested=PANE_VIEW)
    report = report_of(passes)

    # No result is visible in the first round, so its difference is the prefix's alone.
    prefix = report.rounds[0].requested_input - report.rounds[0].as_recorded_input
    first = {(r.turn, r.index): r for r in passes.first.rounds}
    second = {(r.turn, r.index): r for r in passes.second.rounds}
    stubs = 0
    for priced in report.rounds:
        a, b = first[(priced.turn, priced.round)], second[(priced.turn, priced.round)]
        sent = pane_sent(b)
        stubs += sum(1 for message in sent if message["role"] == "tool" and is_stub(message))
        fixed = priced.as_recorded_input - results_by_hand(a.history, compact=False)
        assert priced.requested_input == fixed + prefix + results_by_hand(sent, compact=True), (
            priced.turn,
            priced.round,
        )
    assert stubs > 0
    assert report.settings.requested.model_view == MODEL_VIEW_PANE
    assert report.settings.as_recorded.model_view == MODEL_VIEW_OFF


def test_a_stub_crosses_into_the_next_turn(tmp_path: Path, package_dir: Path) -> None:
    """The closing answer is an assistant message, so it ages every result by one: the
    opening's one result is in full in its closing round (age 0) and in the follow-up's first
    request (age 1), and a stub in the follow-up's second (age 2) - without the closing
    answer it would still be one round short."""
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,),), text="Done."),
            TurnPlan(kind="follow_up", user_text="And the holes?", rounds=((HOLES,),), text="Ok."),
        ],
    )

    passes = replay_passes(read_recording(run), tmp_path / "scratch", requested=PANE_VIEW)

    rounds = {(r.turn, r.index): r for r in passes.second.rounds}
    def stubs(key: tuple[int, int]) -> list[bool]:
        return [is_stub(m) for m in pane_sent(rounds[key]) if m["role"] == "tool"]

    assert stubs((0, 1)) == [False]
    assert stubs((1, 0)) == [False]
    assert stubs((1, 1)) == [True, False]


def test_pass_a_replays_with_the_recordings_own_model_view(
    tmp_path: Path, package_dir: Path
) -> None:
    def viewed(played: PlayedRound) -> TokenUsage:
        """What a review recorded with the pane's view was billed for each round."""
        return usage(
            DEFAULT_PREFIX_TOKENS
            + DEFAULT_OUTPUT_TOKENS * played.prior_rounds
            + results_by_hand(pane_sent(played), compact=True)
        )

    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,), (HOLES,), (RMS_PART,)), text="Done.")],
        usage_for=viewed,
        model_view=MODEL_VIEW_PANE,
    )

    report = replay(run, requested=ALL_OFF)

    assert report.settings.as_recorded.model_view == MODEL_VIEW_PANE
    assert report.settings.requested.model_view == MODEL_VIEW_OFF
    assert [r.as_recorded_input for r in report.rounds] == [r.recorded_input for r in report.rounds]
    assert report.totals.requested > report.totals.as_recorded


# --- stored results (User Story 3, T078) ---------------------------------------------------


def live_run(tmp_path: Path, package_dir: Path, *rounds: tuple[ScriptedToolCall, ...]) -> Path:
    return record_scripted_review(
        tmp_path / "run", package_dir, [TurnPlan(rounds=rounds)], **with_bridge()
    )


def stored_file(run: Path, step: int) -> Path:
    return run / TOOL_RESULTS_DIR_NAME / f"step-{step}.json"


def test_a_call_the_replay_cannot_run_is_sized_from_its_stored_result(
    tmp_path: Path, package_dir: Path
) -> None:
    run = live_run(tmp_path, package_dir, (LIVE,), (COMPONENTS,))

    report = replay(run, requested=ALL_OFF)

    [live] = report.rounds[0].calls
    assert live.class_ == "stored"
    assert live.reason is not None and "bridge" in live.reason
    assert f"{TOOL_RESULTS_DIR_NAME}/step-{live.step}.json" in live.reason
    assert report.rounds[0].estimated is False
    assert report.totals.estimated_rounds == 0
    assert [r.as_recorded_input for r in report.rounds] == [r.recorded_input for r in report.rounds]

    path = stored_file(run, live.step)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    before = count_tokens(tool_result_text(envelope["payload"]))
    envelope["payload"]["padding"] = "stored " * 100
    path.write_text(json.dumps(envelope), encoding="utf-8")
    after = count_tokens(tool_result_text(envelope["payload"]))

    padded = replay(run, requested=ALL_OFF)

    assert padded.rounds[1].as_recorded_input - report.rounds[1].as_recorded_input == after - before


@pytest.mark.parametrize(
    "spoil", ["another session", "another tool", "other arguments", "no payload", "not json"]
)
def test_a_stored_file_that_is_not_this_calls_result_is_ignored(
    tmp_path: Path, package_dir: Path, spoil: str
) -> None:
    run = live_run(tmp_path, package_dir, (LIVE,), (COMPONENTS,))
    [live] = read_recording(run).turns[0].rounds[0].calls
    path = stored_file(run, live.step)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if spoil == "another session":
        envelope["session_id"] = str(uuid4())
    elif spoil == "another tool":
        envelope["tool"] = "list_components"
    elif spoil == "other arguments":
        envelope["arguments"] = {**envelope["arguments"], "configuration": "Other"}
    elif spoil == "no payload":
        del envelope["payload"]
    path.write_text("{not json" if spoil == "not json" else json.dumps(envelope), encoding="utf-8")

    [call] = replay(run, requested=ALL_OFF).rounds[0].calls

    assert call.class_ == "estimated"


def test_a_stored_result_is_shown_and_pruned_like_any_other(
    tmp_path: Path, package_dir: Path
) -> None:
    run = live_run(tmp_path, package_dir, (LIVE,), (SUMMARY,), (COMPONENTS,), (HOLES,))
    [live] = read_recording(run).turns[0].rounds[0].calls
    payload = json.loads(stored_file(run, live.step).read_text(encoding="utf-8"))["payload"]

    passes = replay_passes(read_recording(run), tmp_path / "scratch", requested=PANE_VIEW)
    report = report_of(passes)

    base = report.rounds[0].requested_input
    for k in (1, 2, 3):
        played = passes.second.rounds[k]
        history = [
            {**m, "content": model_view(live.tool, payload), "is_error": False}
            if m["role"] == "tool" and m["name"] == live.tool
            else m
            for m in played.history
        ]
        sent = prune_history(history, 2, finding_detail=True)
        assert report.rounds[k].requested_input == (
            base + DEFAULT_OUTPUT_TOKENS * k + results_by_hand(sent, compact=True)
        )
        assert is_stub(sent[2]) is (k == 3)


def test_an_estimated_result_past_the_prune_age_is_priced_as_the_stub_the_replay_can_know(
    tmp_path: Path, package_dir: Path
) -> None:
    """Its payload is unknown, so its view is priced at the recorded size and its stub at
    what the replay knows of it - its tool and arguments - once the adapters' rule applies."""
    run = without_stored_results(
        live_run(tmp_path, package_dir, (LIVE,), (SUMMARY,), (COMPONENTS,), (HOLES,))
    )

    passes = replay_passes(read_recording(run), tmp_path / "scratch", requested=PANE_VIEW)
    report = report_of(passes)

    rounds = report.rounds
    estimate = (
        rounds[1].as_recorded_input
        - rounds[0].as_recorded_input
        - DEFAULT_OUTPUT_TOKENS
        - FRAMING_TOKENS
    )
    stub = count_tokens(
        tool_result_text(
            result_stub(LIVE.name, LIVE.arguments, {}, finding_detail=True), compact=True
        )
    )
    assert 0 < stub < estimate

    def others(k: int) -> int:
        sent = pane_sent(passes.second.rounds[k])
        return results_by_hand([m for m in sent if m.get("name") != LIVE.name], compact=True)

    base = rounds[0].requested_input
    assert rounds[2].requested_input == (
        base + 2 * DEFAULT_OUTPUT_TOKENS + estimate + FRAMING_TOKENS + others(2)
    )
    assert rounds[3].requested_input == (
        base + 3 * DEFAULT_OUTPUT_TOKENS + stub + FRAMING_TOKENS + others(3)
    )
    assert [c.class_ for c in rounds[0].calls] == ["estimated"]


def _text_of(run: Path, step: int) -> str:
    """The current code's result of a pure query step, replayed in isolation."""
    from swreview.agent.providers import tool_result_text
    from swreview.ir.loader import load_package
    from swreview.tools.context import context_for
    from swreview.tools.registry import ToolRegistry

    recording = read_recording(run)
    call = next(c for t in recording.turns for r in t.rounds for c in r.calls if c.step == step)
    dispatch = ToolRegistry().dispatch(context_for(load_package(run).package))
    return tool_result_text(dispatch.call(call.tool, call.arguments).payload)
