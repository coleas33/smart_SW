"""Every recorded call gets a class from pass A (008 T020, `contracts/replay.md` §3, R2.4).

The class keeps what the offline replay cannot know apart from what the change being priced
did: `reproduced` (same status, same summary), `changed` (same status, a different summary, no
estimated call before it in the turn: sized at the current code's result and listed), and
`estimated` (a tool the current code does not offer offline or does not know, a status
mismatch, or a divergence after an estimated call). The recordings are made with the scripted
builder and then edited the way older code would have written them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.replay import ReplayReport, TurnPlan, replay
from swreview.ir.loader import save_package
from tests.support.prerun import prerun_package, standards_prerun_package
from tests.support.replay import record_scripted_review, rewrite_events
from tests.support.review_bridge import (
    RECORDED_INTERFERENCE_SETTINGS,
    VOLUME_UNIT_GAP,
    ScriptedReviewBridge,
    interference_row,
)

pytestmark = pytest.mark.usefixtures("vocabulary")

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"

SUMMARY = ScriptedToolCall("get_package_summary")
COMPONENTS = ScriptedToolCall("list_components", {"parent_id": None, "include_suppressed": True})
COMPONENT = ScriptedToolCall("get_component", {"component_id": "cmp:0002"})
INTERFERENCES = ScriptedToolCall(
    "list_interferences", {"configuration": None, "component_id": None}
)
STANDARDS = ScriptedToolCall("check_standards")
LIVE = ScriptedToolCall(
    "bridge_interference",
    {
        "component_ids": [],
        "configuration": "Default",
        "settings": dict(RECORDED_INTERFERENCE_SETTINGS),
    },
)
ROW = interference_row("int:0101", ("cmp:0002", "cmp:0003"), "cmp:0002|cmp:0003", 12.0)


def package(tmp_path: Path, standards: bool = False) -> Path:
    directory = tmp_path / "package"
    save_package(standards_prerun_package() if standards else prerun_package(), directory)
    return directory


def bridged() -> dict[str, Any]:
    answer = {"interferences": [ROW], "gaps": [VOLUME_UNIT_GAP]}
    return {
        "bridge": True,
        "bridge_factory": lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [answer]}
        ),
    }


def calls_of(report: ReplayReport) -> dict[str, tuple[str, str | None]]:
    return {c.tool: (c.class_, c.reason) for r in report.rounds for c in r.calls}


def rename(old: str, new: str):  # noqa: ANN201 - a small event rewriter
    def change(event: dict[str, Any]) -> dict[str, Any]:
        if event["type"] == "tool.started" and event["body"]["tool"] == old:
            event["body"]["tool"] = new
        return event

    return change


# --- estimated -------------------------------------------------------------------------------


def test_an_unknown_tool_name_is_estimated_as_not_known(tmp_path: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run", package(tmp_path), [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))]
    )
    rewrite_events(run, rename("list_components", "list_retired_components"))

    klass, reason = calls_of(replay(run, requested=EfficiencySettings()))["list_retired_components"]

    assert klass == "estimated"
    assert reason is not None and "not known to the current code" in reason


def test_a_bridge_tool_with_no_bridge_is_estimated(tmp_path: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run", package(tmp_path), [TurnPlan(rounds=((LIVE,), (SUMMARY,)))], **bridged()
    )

    klass, reason = calls_of(replay(run, requested=EfficiencySettings()))["bridge_interference"]

    assert klass == "estimated"
    assert reason is not None and "bridge" in reason


def test_check_standards_without_a_profile_is_estimated_and_with_one_reproduced(
    tmp_path: Path,
) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package(tmp_path, standards=True),
        [TurnPlan(rounds=((STANDARDS,), (SUMMARY,)))],
        standards_profile=EXAMPLE_PROFILE,
    )

    without = calls_of(replay(run, requested=EfficiencySettings()))["check_standards"]
    with_profile = calls_of(
        replay(run, requested=EfficiencySettings(), standards_profile=EXAMPLE_PROFILE)
    )["check_standards"]

    assert without[0] == "estimated"
    assert without[1] is not None and "standards profile" in without[1]
    assert with_profile == ("reproduced", None)


def test_a_divergence_after_an_estimated_call_is_estimated(tmp_path: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run",
        package(tmp_path),
        [TurnPlan(rounds=((LIVE,), (INTERFERENCES,)))],
        **bridged(),
    )

    klass, reason = calls_of(replay(run, requested=EfficiencySettings()))["list_interferences"]

    assert klass == "estimated"
    assert reason is not None and "after" in reason


def test_a_status_mismatch_is_estimated(tmp_path: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run", package(tmp_path), [TurnPlan(rounds=((COMPONENT,), (SUMMARY,)))]
    )

    def missing(event: dict[str, Any]) -> dict[str, Any]:
        if event["type"] == "tool.started" and event["body"]["tool"] == "get_component":
            event["body"]["arguments"] = {"component_id": "cmp:9999"}
        return event

    rewrite_events(run, missing)

    klass, reason = calls_of(replay(run, requested=EfficiencySettings()))["get_component"]

    assert klass == "estimated"
    assert reason is not None and "error" in reason


def test_findings_renumbered_behind_an_estimated_call_still_reproduce(tmp_path: Path) -> None:
    """A replay that cannot run a check skips its findings, so every later id moves down."""
    judge = ScriptedToolCall("check_interference_group", {"group_key": "cmp:0001|cmp:0002"})
    rms = ScriptedToolCall("check_rms_part", {"document_id": None})
    row = interference_row("int:0102", ("cmp:0001", "cmp:0002"), "cmp:0001|cmp:0002", 3.0)
    answer = {"interferences": [row], "gaps": [VOLUME_UNIT_GAP]}
    run = record_scripted_review(
        tmp_path / "run",
        package(tmp_path),
        [TurnPlan(rounds=((LIVE,), (judge,), (rms,)))],
        bridge=True,
        bridge_factory=lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [answer]}
        ),
    )

    report = replay(run, requested=EfficiencySettings())

    klass, reason = calls_of(report)["check_rms_part"]
    assert (klass, reason) == ("reproduced", None)
    assert report.findings.lost == []
    assert [item.check for item in report.findings.not_replayable] == ["interference.static"]


# --- changed and reproduced ---------------------------------------------------------------


def test_a_divergence_with_no_estimated_call_before_it_is_changed(tmp_path: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run", package(tmp_path), [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))]
    )

    def older(event: dict[str, Any]) -> dict[str, Any]:
        if event["type"] == "tool.finished" and event["body"]["step_index"] == 1:
            event["body"]["result_summary"] = '{"result":[{"id":"cmp:0001","name":"older"}]}'
        return event

    rewrite_events(run, older)

    report = replay(run, requested=EfficiencySettings())

    klass, reason = calls_of(report)["list_components"]
    assert klass == "changed"
    assert reason is not None and reason
    assert report.rounds[2].as_recorded_input == report.rounds[2].recorded_input, (
        "a changed call is sized at the current code's result, which here is the recorded one"
    )


def test_an_untouched_recording_is_reproduced_throughout(tmp_path: Path) -> None:
    run = record_scripted_review(
        tmp_path / "run", package(tmp_path), [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)))]
    )

    report = replay(run, requested=EfficiencySettings())

    assert {klass for klass, _ in calls_of(report).values()} == {"reproduced"}
    assert all(reason is None for _, reason in calls_of(report).values())
