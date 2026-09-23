"""The replay's finding comparison (008 T021, `contracts/replay.md` §5, research R2.8).

Findings are compared as multisets of `finding_subject_key`. A recorded finding whose step the
replay reproduced and whose key the requested pass no longer produces is **lost**, and the
command exits 1 after printing everything; a new key is **added** and changes no exit code; the
findings of a step the replay could only estimate are **not replayable offline**, listed with
the step and the reason and never counted lost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.replay import TurnPlan, replay
from swreview.ir.loader import save_package
from tests.support.prerun import prerun_package
from tests.support.replay import record_scripted_review, rewrite_session
from tests.support.review_bridge import (
    RECORDED_INTERFERENCE_SETTINGS,
    VOLUME_UNIT_GAP,
    ScriptedReviewBridge,
    interference_row,
)

pytestmark = pytest.mark.usefixtures("vocabulary")

runner = CliRunner()

SUMMARY = ScriptedToolCall("get_package_summary")
RMS_PART = ScriptedToolCall("check_rms_part", {"document_id": None})
LIVE = ScriptedToolCall(
    "bridge_interference",
    {
        "component_ids": [],
        "configuration": "Default",
        "settings": dict(RECORDED_INTERFERENCE_SETTINGS),
    },
)
NEW_GROUP = "cmp:0001|cmp:0002"
JUDGE_NEW = ScriptedToolCall("check_interference_group", {"group_key": NEW_GROUP})


@pytest.fixture
def run(tmp_path: Path) -> Path:
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    return record_scripted_review(
        tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,), (RMS_PART,)), text="Done.")]
    )


def replay_cli(run: Path) -> Any:
    return runner.invoke(cli.app, ["benchmark", "replay", str(run)])


def test_a_finding_the_replay_no_longer_produces_is_lost_and_exits_1(run: Path) -> None:
    def moved(session: dict[str, Any]) -> None:
        session["findings"][0]["component_ids"] = ["cmp:0003"]

    original = json.loads((run / "session.json").read_text(encoding="utf-8"))["findings"][0]
    rewrite_session(run, moved)

    report = replay(run, requested=EfficiencySettings())

    assert [(item.check, item.subject) for item in report.findings.lost] == [
        (original["check"], report.findings.lost[0].subject)
    ]
    assert "cmp:0003" in report.findings.lost[0].subject
    assert [item.check for item in report.findings.added] == [original["check"]]
    result = replay_cli(run)
    assert result.exit_code == 1
    assert "lost" in result.stdout
    assert original["check"] in result.stdout
    assert "tokens counted with o200k_base" in result.stdout, "everything is printed first"


def test_an_added_finding_is_reported_and_the_exit_stays_0(run: Path) -> None:
    removed: dict[str, Any] = {}

    def fewer(session: dict[str, Any]) -> None:
        removed.update(session["findings"].pop())

    rewrite_session(run, fewer)

    report = replay(run, requested=EfficiencySettings())

    assert report.findings.lost == []
    assert [item.check for item in report.findings.added] == [removed["check"]]
    result = replay_cli(run)
    assert result.exit_code == 0, result.output
    assert "added" in result.stdout


def test_findings_of_an_estimated_step_are_not_replayable_and_not_lost(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    row = interference_row("int:0101", ("cmp:0001", "cmp:0002"), NEW_GROUP, 7.0)
    answer = {"interferences": [row], "gaps": [VOLUME_UNIT_GAP]}
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((LIVE,), (JUDGE_NEW,)), text="Done.")],
        bridge=True,
        bridge_factory=lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [answer]}
        ),
    )

    report = replay(run, requested=EfficiencySettings())

    [item] = report.findings.not_replayable
    assert item.check.startswith("interference.")
    assert item.step == 1
    assert item.reason
    assert report.findings.lost == []
    assert replay_cli(run).exit_code == 0


def test_duplicate_subject_keys_are_compared_as_a_multiset(run: Path) -> None:
    def doubled(session: dict[str, Any]) -> None:
        extra = dict(session["findings"][0])
        extra["id"] = "F-900"
        session["findings"].append(extra)

    rewrite_session(run, doubled)

    report = replay(run, requested=EfficiencySettings())

    assert len(report.findings.lost) == 1
    assert report.findings.recorded == report.findings.replayed + 1


def test_an_untouched_recording_loses_and_adds_nothing(run: Path) -> None:
    report = replay(run, requested=EfficiencySettings())

    assert report.findings.lost == []
    assert report.findings.added == []
    assert report.findings.not_replayable == []
    assert report.findings.recorded == report.findings.replayed > 0
