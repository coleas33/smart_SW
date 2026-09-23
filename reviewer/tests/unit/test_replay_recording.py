"""Reading a recorded review back into turns and rounds (008 T015, `contracts/replay.md` §2).

`swreview.benchmark.recording.read_recording` is the replay's only view of a run folder. Every
fact it rebuilds comes from the event log's own markers - a round is a `usage` event and the
`tool.started` events after it, a presentation request is a `usage` after the turn's
`text.done`, an answer turn follows `evidence.answered`, a finding belongs to the call whose
`tool.started`/`tool.finished` bracket its event falls in - so these tests build recordings
with the scripted builder and check each rebuilt fact against the script. A folder that is
not a review is refused in one sentence naming what is missing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from swreview.agent.providers import TokenUsage
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.recording import RecordingRefused, read_recording
from swreview.benchmark.replay import TurnPlan
from swreview.ir.loader import save_package
from swreview.tokens import count_tokens
from tests.support.prerun import prerun_package
from tests.support.replay import record_scripted_review

pytestmark = pytest.mark.usefixtures("vocabulary")

SUMMARY = ScriptedToolCall("get_package_summary")
COMPONENTS = ScriptedToolCall("list_components", {"parent_id": None, "include_suppressed": True})
HOLES = ScriptedToolCall("list_holes", {"component_id": None, "hole_type": None})
RMS_PART = ScriptedToolCall("check_rms_part", {"document_id": None})
RMS_ASSEMBLY = ScriptedToolCall("check_rms_assembly")
ASK = ScriptedToolCall(
    "request_evidence", {"what": "the drawing", "why": "fit check", "entity_ids": ["cmp:0002"]}
)
PRESENTATION = TokenUsage(
    input_tokens=1_874,
    cached_input_tokens=0,
    cache_write_tokens=None,
    output_tokens=519,
    reasoning_tokens=0,
    tool_result_input_tokens=None,
    total_tokens=2_393,
    latency_s=0.5,
)


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "package"
    save_package(prerun_package(), directory)
    return directory


def recorded(tmp_path: Path, package_dir: Path, turns: list[TurnPlan], **options: object) -> Path:
    return record_scripted_review(tmp_path / "run", package_dir, turns, **options)


# --- rounds ------------------------------------------------------------------------------


def test_serial_rounds_rebuild_one_call_per_round(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))])

    recording = read_recording(run)

    [turn] = recording.turns
    assert (turn.index, turn.kind, turn.end_reason) == (0, "opening", "end")
    assert [[call.tool for call in r.calls] for r in turn.rounds] == [
        ["get_package_summary"],
        ["list_components"],
        [],
    ]
    assert [r.index for r in turn.rounds] == [0, 1, 2]
    assert [r.kind for r in turn.rounds] == ["main", "main", "main"]
    assert [call.step for r in turn.rounds for call in r.calls] == [0, 1]
    assert turn.rounds[1].calls[0].arguments == {"parent_id": None, "include_suppressed": True}
    assert all(call.status == "ok" for r in turn.rounds for call in r.calls)


def test_the_recorded_summary_is_the_trace_line(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))])
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))

    [call] = read_recording(run).turns[0].rounds[0].calls

    assert call.summary == session["steps"][0]["result_summary"]


def test_a_round_of_three_calls_is_one_round(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY, COMPONENTS, HOLES),))])

    [turn] = read_recording(run).turns

    assert [len(r.calls) for r in turn.rounds] == [3, 0]


def test_each_round_keeps_its_recorded_usage(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))])
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    inputs = [e["body"]["input_tokens"] for e in events if e["type"] == "usage"]

    [turn] = read_recording(run).turns

    assert [r.usage.input_tokens for r in turn.rounds] == inputs


def test_the_presentation_usage_after_the_text_is_a_presentation_round(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(
        tmp_path,
        package_dir,
        [TurnPlan(rounds=((RMS_PART,),), text="Found some.")],
        presentation=PRESENTATION,
    )

    [turn] = read_recording(run).turns

    assert [r.kind for r in turn.rounds] == ["main", "main", "presentation"]
    assert turn.rounds[-1].usage.input_tokens == 1_874
    assert turn.rounds[-1].calls == ()


def test_a_follow_up_turn_carries_its_users_words_as_the_recorded_growth(
    tmp_path: Path, package_dir: Path
) -> None:
    question = "Which holes did you look at?"
    run = recorded(
        tmp_path,
        package_dir,
        [
            TurnPlan(rounds=((SUMMARY,),), text="Done."),
            TurnPlan(kind="follow_up", user_text=question, rounds=((HOLES,),), text="These."),
        ],
    )

    recording = read_recording(run)

    assert [turn.kind for turn in recording.turns] == ["opening", "follow_up"]
    assert recording.turns[0].user_tokens is None
    assert recording.turns[1].user_tokens == count_tokens(question)
    assert [r.index for r in recording.turns[1].rounds] == [0, 1]


def test_an_answered_request_makes_an_answer_turn(tmp_path: Path, package_dir: Path) -> None:
    answer = "The drawing is attached."
    run = recorded(
        tmp_path,
        package_dir,
        [
            TurnPlan(rounds=((ASK,),), text="Asked."),
            TurnPlan(kind="answer", answers=(("ER-001", answer),), text="Thanks."),
        ],
    )

    recording = read_recording(run)

    assert [turn.kind for turn in recording.turns] == ["opening", "answer"]
    assert recording.turns[1].answers == (("ER-001", answer),)
    assert recording.turns[0].answers == ()


def test_a_stopped_turn_drops_its_dangling_call(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(
        tmp_path,
        package_dir,
        [
            TurnPlan(
                rounds=((SUMMARY,), (COMPONENTS,)), end_reason="stopped", stop_at_last_call=True
            )
        ],
    )

    [turn] = read_recording(run).turns

    assert turn.end_reason == "stopped"
    assert [[call.tool for call in r.calls] for r in turn.rounds] == [["get_package_summary"], []]


def test_pre_run_steps_are_setup_and_in_no_round(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(
        tmp_path,
        package_dir,
        [TurnPlan(rounds=((SUMMARY,),))],
        efficiency=EfficiencySettings(prerun_checks=True),
    )

    recording = read_recording(run)

    assert recording.setup_steps, "lever 5 ran its checks before the first round"
    assert recording.setup_steps == tuple(range(len(recording.setup_steps)))
    in_rounds = {call.step for t in recording.turns for r in t.rounds for call in r.calls}
    assert in_rounds == {len(recording.setup_steps)}


def test_every_finding_is_tied_to_the_step_that_recorded_it(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(
        tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,), (RMS_PART,), (RMS_ASSEMBLY,)))]
    )

    recording = read_recording(run)

    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    expected: dict[str, int | None] = {}
    open_step: int | None = None
    for event in events:
        if event["type"] == "tool.started":
            open_step = event["body"]["step_index"]
        elif event["type"] == "tool.finished":
            open_step = None
        elif event["type"] == "finding":
            expected.setdefault(event["body"]["id"], open_step)
    assert recording.findings, "the part check finds something in this package"
    assert {item.finding.id: item.step for item in recording.findings} == expected
    assert set(expected.values()) == {1}, "every finding here comes from check_rms_part"
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    assert [item.finding.id for item in recording.findings] == [
        f["id"] for f in session["findings"]
    ]


def test_setup_findings_are_tied_to_their_pre_run_step(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(
        tmp_path,
        package_dir,
        [TurnPlan(rounds=((SUMMARY,),))],
        efficiency=EfficiencySettings(prerun_checks=True),
    )

    recording = read_recording(run)

    assert recording.findings
    assert {item.step for item in recording.findings} <= set(recording.setup_steps)


def test_the_provider_and_the_package_are_named(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))])

    recording = read_recording(run)

    assert recording.provider == "fake"
    assert recording.package_path == run / "package.json"
    assert recording.run_dir == run


def test_growth_after_a_round_is_the_next_rounds_input_minus_this_ones(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))])
    [turn] = read_recording(run).turns
    recording = read_recording(run)

    first, second, closing = turn.rounds
    assert recording.growth_after(first) == (
        second.usage.input_tokens - first.usage.input_tokens - first.usage.output_tokens
    )
    assert recording.growth_after(closing) is None


def test_the_last_round_of_a_stopped_turn_has_no_observable_growth(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(
        tmp_path,
        package_dir,
        [
            TurnPlan(
                rounds=((SUMMARY,), (COMPONENTS,)), end_reason="stopped", stop_at_last_call=True
            )
        ],
    )
    recording = read_recording(run)

    assert recording.growth_after(recording.turns[0].rounds[-1]) is None


def test_reading_writes_nothing(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))])
    before = {p.name: p.read_bytes() for p in run.iterdir()}

    read_recording(run)

    assert {p.name: p.read_bytes() for p in run.iterdir()} == before


# --- refusals ----------------------------------------------------------------------------


def refusal(folder: Path) -> str:
    with pytest.raises(RecordingRefused) as raised:
        read_recording(folder)
    message = str(raised.value)
    assert "\n" not in message
    return message


def test_a_folder_with_no_session_is_refused_with_run_folder_sessions_sentence(
    tmp_path: Path,
) -> None:
    from swreview.report.rerender import run_folder_session

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError) as expected:
        run_folder_session(empty)

    assert refusal(empty) == str(expected.value)


def test_a_benchmark_run_root_is_refused_with_its_sentence(
    tmp_path: Path, package_dir: Path
) -> None:
    root = tmp_path / "root"
    recorded_run = recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))])
    shutil.copytree(recorded_run, root / "some-package")

    message = refusal(root)

    assert "benchmark" in message
    assert "some-package" in message


def test_a_check_folder_with_no_event_log_is_refused(tmp_path: Path, package_dir: Path) -> None:
    folder = tmp_path / "check"
    shutil.copytree(recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))]), folder)
    (folder / "events.jsonl").unlink()

    message = refusal(folder)

    assert "events.jsonl" in message
    assert "check folder" in message


def test_an_event_log_with_no_usage_is_refused(tmp_path: Path, package_dir: Path) -> None:
    folder = tmp_path / "quiet"
    shutil.copytree(recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))]), folder)
    events = (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    kept = [line for line in events if json.loads(line)["type"] != "usage"]
    (folder / "events.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")

    message = refusal(folder)

    assert "usage" in message
    assert "nothing to price" in message


def test_a_folder_with_no_package_is_refused(tmp_path: Path, package_dir: Path) -> None:
    folder = tmp_path / "nopackage"
    shutil.copytree(recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))]), folder)
    (folder / "package.json").unlink()

    message = refusal(folder)

    assert "package.json" in message


def test_an_event_log_with_a_broken_line_is_refused(tmp_path: Path, package_dir: Path) -> None:
    folder = tmp_path / "broken"
    shutil.copytree(recorded(tmp_path, package_dir, [TurnPlan(rounds=((SUMMARY,),))]), folder)
    with (folder / "events.jsonl").open("a", encoding="utf-8") as log:
        log.write("{not json\n")

    message = refusal(folder)

    assert "events.jsonl" in message
    assert "line" in message


def test_the_committed_attention_check_folder_is_refused(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "fixtures" / "attention" / "check-folder"
    if not source.is_dir():
        pytest.skip("the attention check-folder fixture is not in this checkout")
    folder = tmp_path / "check"
    shutil.copytree(source, folder)

    assert "events.jsonl" in refusal(folder)
