"""The real recordings' rule, pinned on recordings that always run (008 T117, decision 3A).

`contracts/replay.md` section 10, research R2.55. The recordings of 2026-09-20 can never be
regenerated, so they are not held to 1% of their bill; each round's drift - pass A's input
minus the recorded input - must instead equal the size change of the results that round's
recorded request carried, with a residual of exactly zero. `tests/support/drift.round_drifts`
computes the rule; this module proves it on scripted recordings built by the accounting:

- a recording replayed by the code that made it drifts nowhere;
- a recording made by "older code" - its usage rewritten as if one result had been smaller -
  drifts by exactly that difference on every round that carried the result and on no other,
  a two-call round, a stopped turn and the turns after it included;
- a package edited after recording, so several results change size and summary, drifts by
  exactly their changes;
- a presentation round drifts by nothing;
- a replay defect - a framing constant the rule does not share - leaves a residual, and the
  rule names each round it sits on;
- a round the replay flags lower bound is outside the rule, listed apart;
- a replay whose settings are not the recording's, a model view on, and a stored result are
  refused, each in one sentence naming what.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers import FRAMING_TOKENS
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE, EfficiencySettings
from swreview.benchmark import replay as replay_module
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import (
    ReplayPasses,
    ReplayReport,
    Requested,
    TurnPlan,
    replay_passes,
    report_of,
)
from swreview.ir.loader import save_package
from swreview.tokens import count_tokens
from tests.support.drift import DriftRuleRefused, RoundDrift, round_drifts
from tests.support.prerun import prerun_package
from tests.support.replay import (
    ALL_OFF,
    record_scripted_review,
    rewrite_events,
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
ANSWER: dict[str, Any] = {
    "interferences": [
        interference_row("int:0101", ("cmp:0002", "cmp:0003"), "cmp:0002|cmp:0003", 12.0)
    ],
    "gaps": [VOLUME_UNIT_GAP],
}

SCRIPT = (
    TurnPlan(rounds=((SUMMARY,), (COMPONENTS, HOLES), (RMS_PART,)), text="Done."),
    TurnPlan(
        kind="follow_up",
        user_text="Look at the summary again, then the holes.",
        rounds=((SUMMARY,), (HOLES,)),
        end_reason="stopped",
        stop_at_last_call=True,
    ),
    TurnPlan(
        kind="follow_up", user_text="And the components?", rounds=((COMPONENTS,),), text="Ok."
    ),
)
"""Three turns: a committed opening with a two-call round, a stopped follow-up, and a
follow-up after it. As recorded, the rounds are (turn, round):

    (0, 0) SUMMARY   (0, 1) COMPONENTS + HOLES   (0, 2) RMS_PART   (0, 3) closing
    (1, 0) SUMMARY   (1, 1) its HOLES call started and stopped, so dropped by the reader
    (2, 0) COMPONENTS   (2, 1) closing
"""

ROUNDS = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (2, 0), (2, 1)]

CARRIERS_OF_THE_OPENING_TWO_CALL_ROUND = [(0, 2), (0, 3), (1, 0), (1, 1), (2, 0), (2, 1)]
"""Every round whose recorded request carried (0, 1)'s results: the rest of the opening
turn, the stopped turn (the opening committed before it), and the turn after it."""

CARRIERS_OF_THE_STOPPED_TURNS_SUMMARY = [(1, 1)]
"""(1, 0)'s results: carried by the stopped turn's next round only. The stopped turn was
never committed, so the turn after it does not carry them."""


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "package"
    save_package(prerun_package(), directory)
    return directory


def recorded(tmp_path: Path, package_dir: Path, **options: Any) -> Path:
    return record_scripted_review(tmp_path / "run", package_dir, list(SCRIPT), **options)


def played(run: Path, scratch: Path, requested: Requested = ALL_OFF) -> ReplayPasses:
    return replay_passes(read_recording(run), scratch, requested=requested)


def drifts_of(run: Path, scratch: Path) -> tuple[list[RoundDrift], ReplayReport]:
    passes = played(run, scratch)
    report = report_of(passes)
    return round_drifts(passes, report), report


def main_drifts(drifts: Sequence[RoundDrift]) -> dict[tuple[int, int], RoundDrift]:
    return {(d.turn, d.round): d for d in drifts if d.kind == "main"}


def as_if_older_code_returned_less(run: Path, tokens_by_round: dict[tuple[int, int], int]) -> None:
    """Rewrite the recorded usage as if older code's results had been smaller.

    `tokens_by_round` maps each recorded round to how many fewer input tokens its request
    carried: exactly what a recording made by code whose result was that much smaller bills.
    Output and cached counts are left alone; the total follows the input.
    """
    recording = read_recording(run)
    order = [(r.turn, r.index, r.kind) for t in recording.turns for r in t.rounds]
    ordinal = iter(order)

    def change(event: dict[str, Any]) -> dict[str, Any]:
        if event.get("type") != "usage":
            return event
        turn, index, kind = next(ordinal)
        less = tokens_by_round.get((turn, index), 0) if kind == "main" else 0
        body = dict(event["body"])
        body["input_tokens"] -= less
        if body.get("total_tokens") is not None:
            body["total_tokens"] -= less
        return {**event, "body": body}

    rewrite_events(run, change)


def less_on(rounds: Collection[tuple[int, int]], tokens: int) -> dict[tuple[int, int], int]:
    return dict.fromkeys(rounds, tokens)


# --- the rule holds, and says what it says ----------------------------------------------------


def test_a_recording_replayed_by_the_code_that_made_it_drifts_nowhere(
    tmp_path: Path, package_dir: Path
) -> None:
    drifts, report = drifts_of(recorded(tmp_path, package_dir), tmp_path / "scratch")

    assert [(d.turn, d.round) for d in drifts] == ROUNDS
    assert [d.kind for d in drifts] == ["main"] * len(ROUNDS)
    assert all((d.drift, d.change, d.residual) == (0, 0, 0) for d in drifts)
    assert len(drifts) == len(report.rounds)


def test_one_result_older_code_returned_smaller_drifts_every_round_that_carried_it(
    tmp_path: Path, package_dir: Path
) -> None:
    """The recorded summary is unchanged, so the call is `reproduced`: a result can change
    size without changing its 200-character trace line, and the rule still accounts for
    every token."""
    run = recorded(tmp_path, package_dir)
    as_if_older_code_returned_less(run, less_on(CARRIERS_OF_THE_OPENING_TWO_CALL_ROUND, 25))

    drifts, report = drifts_of(run, tmp_path / "scratch")

    by_round = main_drifts(drifts)
    assert {key: d.drift for key, d in by_round.items()} == {
        key: 25 if key in CARRIERS_OF_THE_OPENING_TWO_CALL_ROUND else 0 for key in ROUNDS
    }
    assert all(d.residual == 0 for d in drifts)
    assert {c.class_ for r in report.rounds for c in r.calls} == {"reproduced"}


def test_a_stopped_turns_results_are_carried_by_no_later_turn(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(tmp_path, package_dir)
    older = less_on(CARRIERS_OF_THE_OPENING_TWO_CALL_ROUND, 25)
    for key in CARRIERS_OF_THE_STOPPED_TURNS_SUMMARY:
        older[key] += 7
    as_if_older_code_returned_less(run, older)

    drifts, _ = drifts_of(run, tmp_path / "scratch")

    by_round = main_drifts(drifts)
    assert by_round[(1, 1)].drift == 32
    assert by_round[(2, 0)].drift == by_round[(2, 1)].drift == 25
    assert all(d.residual == 0 for d in drifts)


def test_a_package_edited_after_recording_drifts_by_exactly_its_results_growth(
    tmp_path: Path, package_dir: Path
) -> None:
    """A deliberate change the replay sees as `changed` calls: the part renamed, so every
    result that names it grows. Each round's drift is the growth of the results it carried,
    counted here from the two replays' own calls, never from the rule."""
    run = recorded(tmp_path, package_dir)
    before = played(run, tmp_path / "before")
    save_package(prerun_package(part_name="A-much-longer-name-for-the-graded-part"), run)

    after = played(run, tmp_path / "after")
    drifts = round_drifts(after, report_of(after))

    growth = {
        (r.turn, r.index): sum(
            count_tokens(new.text) - count_tokens(old.text)
            for old, new in zip(r.calls, s.calls, strict=True)
        )
        for r, s in zip(before.first.rounds, after.first.rounds, strict=True)
    }
    assert any(growth.values()), "the edit changed no result; the test would pin nothing"
    carried = {
        (0, 0): [],
        (0, 1): [(0, 0)],
        (0, 2): [(0, 0), (0, 1)],
        (0, 3): [(0, 0), (0, 1), (0, 2)],
        (1, 0): [(0, 0), (0, 1), (0, 2)],
        (1, 1): [(0, 0), (0, 1), (0, 2), (1, 0)],
        (2, 0): [(0, 0), (0, 1), (0, 2)],
        (2, 1): [(0, 0), (0, 1), (0, 2), (2, 0)],
    }
    by_round = main_drifts(drifts)
    assert {key: by_round[key].drift for key in ROUNDS} == {
        key: sum(growth[k] for k in carried[key]) for key in ROUNDS
    }
    assert all(d.residual == 0 for d in drifts)


def test_a_presentation_round_drifts_by_nothing(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((RMS_PART,),), text="Found some.")],
        presentation=usage(1_874, 519),
    )
    as_if_older_code_returned_less(run, {(0, 1): 40})

    drifts, _ = drifts_of(run, tmp_path / "scratch")

    [presentation] = [d for d in drifts if d.kind == "presentation"]
    assert (presentation.drift, presentation.change, presentation.residual) == (0, 0, 0)
    assert main_drifts(drifts)[(0, 1)].drift == 40


# --- a replay defect is a residual --------------------------------------------------------------


def test_a_framing_constant_the_rule_does_not_share_leaves_a_residual_on_every_carrying_round(
    tmp_path: Path, package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The replay adding 13 tokens a result where the bill and the rule add 12: every round
    is off by one token per result it carries, which is a defect of the replay, never a
    size change."""
    run = recorded(tmp_path, package_dir)
    monkeypatch.setattr(replay_module, "FRAMING_TOKENS", FRAMING_TOKENS + 1)

    drifts, _ = drifts_of(run, tmp_path / "scratch")

    results_carried = {
        (0, 0): 0, (0, 1): 1, (0, 2): 3, (0, 3): 4,
        (1, 0): 4, (1, 1): 5, (2, 0): 4, (2, 1): 5,
    }  # fmt: skip
    assert {(d.turn, d.round): d.residual for d in drifts} == results_carried
    assert all(d.change == 0 for d in drifts)


# --- outside the rule, and refused --------------------------------------------------------------


def with_bridge() -> dict[str, Any]:
    return {
        "bridge": True,
        "bridge_factory": lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [ANSWER]}
        ),
    }


def test_a_round_flagged_lower_bound_is_outside_the_rule(tmp_path: Path, package_dir: Path) -> None:
    """The live call stopped as the last of its turn: its growth is never observed, the
    replay sizes it from its summary and flags the round, and the rule has no recorded size
    to hold that round to."""
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

    drifts, report = drifts_of(run, tmp_path / "scratch")

    flagged = {(r.turn, r.round) for r in report.rounds if r.lower_bound}
    assert flagged == {(0, 1)}
    outside = [(d.turn, d.round) for d in drifts if d.change is None]
    assert outside == [(0, 1)]
    assert [d.residual for d in drifts if d.change is None] == [None]
    assert all(d.residual == 0 for d in drifts if d.change is not None)


def test_an_estimated_call_changes_nothing_while_its_growth_is_observed(
    tmp_path: Path, package_dir: Path
) -> None:
    """The live call sized from the recorded growth: its round's results are the recorded
    ones by construction, so the round after it drifts by the other call's change only."""
    run = without_stored_results(
        record_scripted_review(
            tmp_path / "run",
            package_dir,
            [TurnPlan(rounds=((LIVE, SUMMARY), (HOLES,)), text="Done.")],
            **with_bridge(),
        )
    )

    drifts, report = drifts_of(run, tmp_path / "scratch")

    assert {c.class_ for r in report.rounds for c in r.calls} >= {"estimated"}
    assert all(d.change is not None and d.residual == 0 for d in drifts)


def test_a_replay_with_other_settings_than_the_recordings_is_refused(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(tmp_path, package_dir)
    passes = played(
        run, tmp_path / "scratch", (EfficiencySettings(prerun_checks=True), MODEL_VIEW_OFF)
    )

    with pytest.raises(DriftRuleRefused, match="recording's own settings"):
        round_drifts(passes, report_of(passes))


def test_a_recording_made_with_the_model_view_on_is_refused(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(tmp_path, package_dir)
    rewrite_session(
        run, lambda session: session.update(model_view=MODEL_VIEW_PANE.model_dump(mode="json"))
    )
    passes = played(run, tmp_path / "scratch", (EfficiencySettings(), MODEL_VIEW_PANE))

    with pytest.raises(DriftRuleRefused, match="model view"):
        round_drifts(passes, report_of(passes))


def test_a_call_sized_from_its_stored_result_is_refused(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((LIVE,), (SUMMARY,)), text="Done.")],
        **with_bridge(),
    )
    passes = played(run, tmp_path / "scratch")
    report = report_of(passes)
    assert {c.class_ for r in report.rounds for c in r.calls} >= {"stored"}

    with pytest.raises(DriftRuleRefused, match="stored result"):
        round_drifts(passes, report)


def test_a_report_of_other_passes_is_refused(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir)
    passes = played(run, tmp_path / "scratch")
    report = report_of(passes)

    with pytest.raises(DriftRuleRefused, match="not the report of these passes"):
        round_drifts(passes, report.model_copy(update={"rounds": report.rounds[:-1]}))
