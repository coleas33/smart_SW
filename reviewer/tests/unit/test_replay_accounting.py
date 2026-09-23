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
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers import FRAMING_TOKENS
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import ReplayReport, TurnPlan, estimated_sizes, replay
from swreview.ir.loader import save_package
from swreview.tokens import count_tokens
from tests.support.prerun import prerun_package
from tests.support.replay import folder_hashes, record_scripted_review, rewrite_session, usage
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

    report = replay(run, requested=EfficiencySettings())

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

    report = replay(run, requested=EfficiencySettings())

    assert all(r.requested_input == r.as_recorded_input for r in report.rounds)
    assert report.totals.requested == report.totals.as_recorded


def test_the_report_names_its_tokenizer_and_its_framing(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])

    report = replay(run, requested=EfficiencySettings())

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

    assert replay(run, requested=EfficiencySettings()).comparison == "shape"


def test_the_requested_settings_are_reported(tmp_path: Path, package_dir: Path) -> None:
    run = record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])
    requested = EfficiencySettings(trim_tool_descriptions=True)

    report = replay(run, requested=requested)

    assert report.settings.requested.efficiency == requested
    assert report.settings.as_recorded.efficiency == EfficiencySettings()


# --- estimation ------------------------------------------------------------------------------


def test_one_estimated_call_is_sized_as_the_growth_minus_the_others_and_framing(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((SUMMARY, LIVE), (COMPONENTS,)))],
        **with_bridge(),
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
    report = replay(run, requested=EfficiencySettings())
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
    report = replay(run, requested=EfficiencySettings())
    assert report.rounds[1].as_recorded_input == report.rounds[1].recorded_input


def test_an_unobservable_growth_gives_the_summary_size_as_a_lower_bound(
    tmp_path: Path, package_dir: Path
) -> None:
    run = record_scripted_review(
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
    recording = read_recording(run)
    last = recording.turns[0].rounds[-1]
    [live] = last.calls

    sizes = estimated_sizes(recording, last, {})

    assert sizes == {live.step: (count_tokens(live.summary), True)}
    report = replay(run, requested=EfficiencySettings())
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

    report = replay(run, requested=EfficiencySettings())

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

    replay(run, requested=EfficiencySettings(prerun_checks=True))

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

    report = replay(run, requested=EfficiencySettings())

    assert rounds_of(report)[-1][0] == rounds_of(report)[-1][1]


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
