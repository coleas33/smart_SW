"""The replay's finding comparison (008 T021, `contracts/replay.md` §5, research R2.8).

Findings are compared as multisets of `finding_subject_key`. A recorded finding whose step the
replay reproduced and whose key the requested pass no longer produces is **lost**, and the
command exits 1 after printing everything; a new key is **added** and changes no exit code; the
findings of a step the replay could only estimate are **not replayable offline**, listed with
the step and the reason and never counted lost.

Feature 010 (T094) adds one outcome ahead of those: a recorded `interference.static` finding
whose group key and configuration equal a contact the requested pass recorded is
**reclassified as contact** - the touching groups the recorded runs reported as findings are
contacts by design now - and is neither lost nor not replayable.
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
from swreview.checks import interference
from swreview.ir.loader import save_package
from swreview.ir.models import Volume
from tests.support.prerun import FIRST_INSTANCE, GROUP_KEY, SECOND_INSTANCE, prerun_package
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
JUDGE_TOUCHING = ScriptedToolCall("check_interference_group", {"group_key": GROUP_KEY})


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


# --- reclassified as contact (feature 010 T094, 010 `contracts/contacts.md` section 6) -------


def touching_package_dir(tmp_path: Path) -> Path:
    """`prerun_package` with its one interference group touching: 0.0 mm3, which feature 010
    judges a contact where the code before it recorded an `interference.static` finding."""
    package = prerun_package()
    [row] = package.interferences
    touching = row.model_copy(update={"volume": Volume(value=0.0, unit="mm3")})
    package_dir = tmp_path / "package"
    save_package(package.model_copy(update={"interferences": [touching]}), package_dir)
    return package_dir


def record_before_contacts(
    monkeypatch: pytest.MonkeyPatch, out: Path, package_dir: Path, **kwargs: Any
) -> Path:
    """A recording made by code with no contact rule: no volume is at or below a negative
    threshold, so the touching group is recorded as a finding, as the recorded runs were."""
    with monkeypatch.context() as patched:
        patched.setattr(interference, "CONTACT_VOLUME_MM3", -1.0)
        return record_scripted_review(out, package_dir, **kwargs)


def recorded_interference(run: Path) -> dict[str, Any]:
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    [finding] = [item for item in session["findings"] if item["check"] == "interference.static"]
    return finding


def test_a_recorded_finding_the_replay_judges_a_contact_is_reclassified_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = record_before_contacts(
        monkeypatch,
        tmp_path / "run",
        touching_package_dir(tmp_path),
        turns=[TurnPlan(rounds=((SUMMARY,), (JUDGE_TOUCHING,)), text="Done.")],
    )
    recorded = recorded_interference(run)
    assert recorded["calculation"]["inputs"]["group_key"] == GROUP_KEY

    report = replay(run, requested=EfficiencySettings())

    [item] = report.findings.reclassified
    assert (item.check, item.group_key, item.contact_id) == (
        "interference.static",
        GROUP_KEY,
        "C-001",
    )
    assert item.subject == f"components {FIRST_INSTANCE}, {SECOND_INSTANCE}; configuration Default"
    assert item.step == 1
    assert report.findings.lost == []
    assert report.findings.added == []
    assert report.findings.not_replayable == []
    assert report.findings.recorded == report.findings.replayed + 1
    result = replay_cli(run)
    assert result.exit_code == 0, result.output
    assert "1 reclassified as contacts" in result.stdout
    assert f"reclassified: interference.static - {item.subject} (contact C-001)" in result.stdout


def test_reclassification_is_checked_before_an_estimated_step_makes_it_not_replayable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded runs' shape: the group is judged after the live call, so its changed
    result is estimated - but the replayed contact names the same group and configuration,
    which says what became of the finding whatever the live call did."""
    row = interference_row("int:0101", ("cmp:0001", "cmp:0002"), NEW_GROUP, 7.0)
    answer = {"interferences": [row], "gaps": [VOLUME_UNIT_GAP]}
    run = record_before_contacts(
        monkeypatch,
        tmp_path / "run",
        touching_package_dir(tmp_path),
        turns=[TurnPlan(rounds=((LIVE,), (JUDGE_TOUCHING,)), text="Done.")],
        bridge=True,
        bridge_factory=lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [answer]}
        ),
    )

    report = replay(run, requested=EfficiencySettings())

    [item] = report.findings.reclassified
    assert (item.group_key, item.step) == (GROUP_KEY, 1)
    assert report.findings.not_replayable == []
    assert report.findings.lost == []
    assert replay_cli(run).exit_code == 0


def test_a_contact_in_another_configuration_reclassifies_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = record_before_contacts(
        monkeypatch,
        tmp_path / "run",
        touching_package_dir(tmp_path),
        turns=[TurnPlan(rounds=((SUMMARY,), (JUDGE_TOUCHING,)), text="Done.")],
    )

    def elsewhere(session: dict[str, Any]) -> None:
        for finding in session["findings"]:
            if finding["check"] == "interference.static":
                finding["configuration"] = "Other"
                finding["calculation"]["inputs"]["configuration"] = "Other"

    rewrite_session(run, elsewhere)

    report = replay(run, requested=EfficiencySettings())

    assert report.findings.reclassified == []
    [lost] = report.findings.lost
    assert (lost.check, lost.subject.endswith("configuration Other")) == (
        "interference.static",
        True,
    )


def test_one_contact_reclassifies_one_recorded_finding_of_its_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiset, like every other comparison here: a group recorded twice and judged once by
    the replay leaves the second recorded finding to be compared as usual - and lost."""
    run = record_before_contacts(
        monkeypatch,
        tmp_path / "run",
        touching_package_dir(tmp_path),
        turns=[TurnPlan(rounds=((SUMMARY,), (JUDGE_TOUCHING,)), text="Done.")],
    )

    def twice(session: dict[str, Any]) -> None:
        extra = dict(recorded_interference(run))
        extra["id"] = "F-900"
        session["findings"].append(extra)

    rewrite_session(run, twice)

    report = replay(run, requested=EfficiencySettings())

    assert len(report.findings.reclassified) == 1
    assert [item.check for item in report.findings.lost] == ["interference.static"]
    assert replay_cli(run).exit_code == 1


def test_a_recorded_finding_with_no_group_key_is_never_reclassified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The group key is read from the recorded calculation; a finding that does not carry
    one cannot be matched to a contact, so it is compared as any other finding is."""
    run = record_before_contacts(
        monkeypatch,
        tmp_path / "run",
        touching_package_dir(tmp_path),
        turns=[TurnPlan(rounds=((SUMMARY,), (JUDGE_TOUCHING,)), text="Done.")],
    )

    def keyless(session: dict[str, Any]) -> None:
        for finding in session["findings"]:
            if finding["check"] == "interference.static":
                del finding["calculation"]["inputs"]["group_key"]

    rewrite_session(run, keyless)

    report = replay(run, requested=EfficiencySettings())

    assert report.findings.reclassified == []
    assert [item.check for item in report.findings.lost] == ["interference.static"]


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
