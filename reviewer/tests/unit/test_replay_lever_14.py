"""The replay prices lever 14 as an estimate (feature 013 T122, research R3 C13).

`contracts/tokens.md` section 4, "Pricing". The replay has no reasoning items, only the recorded
usage. The as-recorded pass carries every earlier turn's output in each later request - reasoning
included, because the OpenAI adapter echoes its reasoning items - so with lever 14 on, each round
of a turn after the first is priced lower by the sum of the recorded reasoning output tokens of
every earlier committed turn's rounds. The figure is an estimate and the round says so. Nothing
the review finds changes: no recorded finding is lost. Gemini sends no reasoning items, so on a
Gemini recording the lever prices nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.settings import MODEL_VIEW_OFF, EfficiencySettings
from swreview.benchmark.replay import ReplayReport, TurnPlan, replay
from swreview.ir.loader import save_package
from tests.support.prerun import prerun_package
from tests.support.replay import (
    ALL_OFF,
    default_usage,
    record_scripted_review,
    rewrite_session,
)

SUMMARY = ScriptedToolCall("get_package_summary")
HOLES = ScriptedToolCall("list_holes", {"component_id": None, "hole_type": None})
RMS_PART = ScriptedToolCall("check_rms_part", {"document_id": None})
LEVER_14 = (EfficiencySettings(drop_prior_reasoning=True), MODEL_VIEW_OFF)


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "package"
    save_package(prerun_package(), directory)
    return directory


def reasoning_by_turn(turns: Sequence[TurnPlan], tokens: Mapping[int, int | None]) -> Any:
    """The default usage, with each round of turn `t` reporting `tokens[t]` reasoning tokens."""
    base = default_usage(turns)

    def usage_for(played: Any) -> Any:
        return base(played).model_copy(update={"reasoning_tokens": tokens.get(played.turn, 0)})

    return usage_for


TWO_TURNS = [
    TurnPlan(rounds=((SUMMARY,), (HOLES,)), text="Done."),
    TurnPlan(kind="follow_up", user_text="And the part tree?", rounds=((RMS_PART,),), text="Ok."),
]


def recorded(
    tmp_path: Path,
    package_dir: Path,
    turns: Sequence[TurnPlan] = TWO_TURNS,
    tokens: Mapping[int, int | None] | None = None,
) -> Path:
    return record_scripted_review(
        tmp_path / "run",
        package_dir,
        turns,
        usage_for=reasoning_by_turn(turns, tokens if tokens is not None else {0: 25, 1: 30}),
    )


def by_turn(report: ReplayReport) -> dict[int, list[Any]]:
    rounds: dict[int, list[Any]] = {}
    for item in report.rounds:
        rounds.setdefault(item.turn, []).append(item)
    return rounds


def test_each_later_turn_round_is_priced_lower_by_the_earlier_turns_reasoning(
    tmp_path: Path, package_dir: Path
) -> None:
    run = recorded(tmp_path, package_dir)

    off, on = replay(run, requested=ALL_OFF), replay(run, requested=LEVER_14)

    first_turn_rounds = len(by_turn(off)[0])
    saving = 25 * first_turn_rounds
    for lever_off, lever_on in zip(off.rounds, on.rounds, strict=True):
        expected = lever_off.requested_input - (saving if lever_on.turn > 0 else 0)
        assert lever_on.requested_input == expected, (lever_on.turn, lever_on.round)


def test_the_first_turn_is_priced_as_recorded(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir)

    off, on = replay(run, requested=ALL_OFF), replay(run, requested=LEVER_14)

    assert [r.requested_input for r in by_turn(on)[0]] == [
        r.requested_input for r in by_turn(off)[0]
    ]


def test_the_lever_14_figure_is_reported_as_an_estimate(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir)

    on = replay(run, requested=LEVER_14)

    assert all(r.estimated for r in by_turn(on)[1])
    assert not any(r.estimated for r in by_turn(on)[0])
    assert on.totals.estimated_rounds == len(by_turn(on)[1])


def test_the_as_recorded_pass_is_untouched(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir)

    off, on = replay(run, requested=ALL_OFF), replay(run, requested=LEVER_14)

    assert [r.as_recorded_input for r in on.rounds] == [r.as_recorded_input for r in off.rounds]
    assert on.totals.as_recorded == off.totals.as_recorded


def test_no_finding_is_lost(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir)

    on = replay(run, requested=LEVER_14)

    assert on.findings.lost == []
    assert on.findings.not_replayable == []
    assert on.findings.replayed == on.findings.recorded


def test_a_third_turn_is_priced_lower_by_both_earlier_turns(
    tmp_path: Path, package_dir: Path
) -> None:
    turns = [
        *TWO_TURNS,
        TurnPlan(kind="follow_up", user_text="Anything else?", rounds=((SUMMARY,),), text="No."),
    ]
    run = recorded(tmp_path, package_dir, turns, {0: 25, 1: 30, 2: 7})

    off, on = replay(run, requested=ALL_OFF), replay(run, requested=LEVER_14)

    rounds_off, rounds_on = by_turn(off), by_turn(on)
    earlier = 25 * len(rounds_off[0]) + 30 * len(rounds_off[1])
    assert [r.requested_input for r in rounds_on[2]] == [
        r.requested_input - earlier for r in rounds_off[2]
    ]


def test_unreported_reasoning_prices_no_saving(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir, tokens={0: None, 1: None})

    off, on = replay(run, requested=ALL_OFF), replay(run, requested=LEVER_14)

    assert [r.requested_input for r in on.rounds] == [r.requested_input for r in off.rounds]
    assert not any(r.estimated for r in on.rounds)


def test_a_gemini_recording_prices_nothing(tmp_path: Path, package_dir: Path) -> None:
    run = recorded(tmp_path, package_dir)

    def gemini(session: dict[str, Any]) -> None:
        session["provider_info"]["provider"] = "gemini"

    rewrite_session(run, gemini)

    off, on = replay(run, requested=ALL_OFF), replay(run, requested=LEVER_14)

    assert [r.requested_input for r in on.rounds] == [r.requested_input for r in off.rounds]


def test_the_regrouped_estimate_prices_the_lever_as_the_strict_figure_does(
    tmp_path: Path, package_dir: Path
) -> None:
    """Parallel tool calls turn the regrouped estimate on (rule M); lever 14 lowers each of its
    later-turn rounds by the same earlier reasoning."""
    run = recorded(tmp_path, package_dir)
    parallel = EfficiencySettings(parallel_tool_calls=True)
    both = EfficiencySettings(parallel_tool_calls=True, drop_prior_reasoning=True)

    without = replay(run, requested=(parallel, MODEL_VIEW_OFF))
    with_lever = replay(run, requested=(both, MODEL_VIEW_OFF))

    assert without.regrouped is not None and with_lever.regrouped is not None
    later_rounds = len(by_turn(without)[1])
    first_turn_rounds = len(by_turn(without)[0])
    assert with_lever.regrouped.total == (
        without.regrouped.total - 25 * first_turn_rounds * later_rounds
    )


def test_the_command_line_accepts_the_lever(tmp_path: Path, package_dir: Path) -> None:
    from tests.unit.test_cli import invoke, payload

    run = recorded(tmp_path, package_dir)

    result = invoke("benchmark", "replay", str(run), "--lever", "drop_prior_reasoning", "--json")

    report = ReplayReport.model_validate(payload(result))
    assert report.settings.requested.efficiency.drop_prior_reasoning is True
    assert report.settings.as_recorded.efficiency.drop_prior_reasoning is False
    assert any(r.estimated for r in report.rounds)
