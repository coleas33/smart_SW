"""The User Story 1 acceptance on the committed fixtures (008 T022, SC-001).

Each fixture is shaped like one recorded review - the big assembly and two runs of the small
one - and replaying it with the settings it was recorded with must reproduce every recorded
round within 1% and the finding set exactly: every recorded finding replayed, or - for a group
feature 010 judges touching - reclassified as a contact, counted per fixture. Every replay of a
committed fixture is graded with `config/standards.example.yaml`, the profile the pilot ran
(research R2.10). The payload shapes that make later savings measurable are pinned too: the
part check's 866 feature rows and the 110 mate entities with their persistent references.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import ReplayPasses, ReplayReport, replay, replay_passes
from swreview.findings import finding_subject_key
from swreview.ir.loader import load_package
from swreview.prerun import DIGEST_HEADER
from swreview.tools.checks_interference import groups_of
from swreview.tools.context import context_for
from swreview.tools.registry import ToolRegistry

pytestmark = pytest.mark.usefixtures("vocabulary")

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"
FIXTURES = REPO_ROOT / "reviewer" / "tests" / "fixtures" / "replay"
NAMES = ("big-assembly", "small-assembly-a", "small-assembly-b")
TOLERANCE = 0.01


@cache
def as_recorded(name: str) -> ReplayReport:
    """The fixture replayed with its recorded settings (all off), graded with the example."""
    return replay(
        FIXTURES / name, requested=EfficiencySettings(), standards_profile=EXAMPLE_PROFILE
    )


@pytest.mark.parametrize("name", NAMES)
def test_every_round_is_within_one_percent_of_the_recorded_input(name: str) -> None:
    report = as_recorded(name)

    worst = max(
        abs(r.as_recorded_input - r.recorded_input) / r.recorded_input for r in report.rounds
    )
    assert worst < TOLERANCE, f"{name}: worst round {worst:.4%}"
    assert abs(report.totals.as_recorded - report.totals.recorded) / report.totals.recorded < (
        TOLERANCE
    )


RECLASSIFIED = {"big-assembly": 3, "small-assembly-a": 2, "small-assembly-b": 0}
"""Recorded `interference.static` findings on touching groups (0.0 mm3), which feature 010
judges contacts: the replay names each one reclassified rather than lost (010 T094-T095)."""


@pytest.mark.parametrize("name", NAMES)
def test_the_finding_set_is_exact(name: str) -> None:
    findings = as_recorded(name).findings

    assert findings.lost == []
    assert findings.added == []
    assert findings.not_replayable == []
    assert len(findings.reclassified) == RECLASSIFIED[name]
    assert {item.check for item in findings.reclassified} <= {"interference.static"}
    assert findings.recorded == findings.replayed + RECLASSIFIED[name]


def test_the_big_assembly_has_the_live_call_and_three_touching_groups_estimated() -> None:
    """One estimated round was the live call alone until feature 010. The three touching
    groups judged after it are contacts now, so their results differ from the recording; a
    replay cannot tell that difference from anything the live call did, so each of their
    rounds is estimated too. Those are exactly the three reclassified findings' steps."""
    report = as_recorded("big-assembly")

    estimated = [r for r in report.rounds if r.estimated]
    assert len(estimated) == 4
    calls = [c for r in estimated for c in r.calls if c.class_ == "estimated"]
    assert [c.tool for c in calls] == ["bridge_interference", *["check_interference_group"] * 3]
    assert [c.step for c in calls[1:]] == [item.step for item in report.findings.reclassified]
    assert report.totals.estimated_rounds == 4
    assert report.totals.lower_bound_rounds == 0


def test_the_big_assembly_carries_one_presentation_round() -> None:
    report = as_recorded("big-assembly")

    assert report.totals.carried_rounds == 1
    assert [r.kind for r in report.rounds].count("presentation") == 1


def test_the_big_assembly_recorded_total_is_twelve_point_four_million() -> None:
    total = as_recorded("big-assembly").totals.recorded

    assert abs(total - 12_400_000) / 12_400_000 < TOLERANCE


# --- the User Story 2 acceptance: checks first alone (008 T049) ------------------------------

CHECKS_FIRST = EfficiencySettings(prerun_checks=True)


@cache
def checks_first(name: str) -> ReplayReport:
    """The fixture replayed with checks first alone requested (model view off)."""
    return replay(FIXTURES / name, requested=CHECKS_FIRST, standards_profile=EXAMPLE_PROFILE)


@pytest.fixture(scope="module")
def big_checks_first(tmp_path_factory: pytest.TempPathFactory) -> ReplayPasses:
    """Both passes of the big fixture with checks first requested, the folders kept."""
    return replay_passes(
        read_recording(FIXTURES / "big-assembly"),
        tmp_path_factory.mktemp("big-checks-first"),
        requested=CHECKS_FIRST,
        standards_profile=EXAMPLE_PROFILE,
    )


@pytest.mark.parametrize("name", NAMES)
def test_checks_first_alone_loses_no_recorded_finding(name: str) -> None:
    findings = checks_first(name).findings

    assert findings.lost == []
    assert findings.not_replayable == []


def test_checks_first_cuts_the_big_assembly() -> None:
    """The cut on every recorded run is asserted with the pane defaults (T078, T086):
    checks first alone adds its digest to every round's prefix, which a small run may not
    repay, but the big one resent a 205k-token check result about thirty times."""
    report = checks_first("big-assembly")

    assert report.totals.requested < report.totals.as_recorded


def test_the_recorded_rms_calls_are_answered_from_checks() -> None:
    report = checks_first("big-assembly")

    rms = [c for r in report.rounds for c in r.calls if c.tool.startswith("check_rms_")]
    assert rms
    assert {c.class_ for c in rms} == {"answered_from_checks"}
    assert all(c.reason and c.reason.startswith("the pre-run ran this call at step ") for c in rms)


def test_every_group_is_judged_once_offline(big_checks_first: ReplayPasses) -> None:
    """SC-006 offline: every group the package holds is judged - one finding or, since
    feature 010, one contact - against 6 of 113 on the recorded run."""
    session = big_checks_first.second.session
    groups = {g.group_key for g in groups_of(load_package(FIXTURES / "big-assembly").package)}
    judged = [
        f.calculation.inputs["group_key"]
        for f in session.findings
        if f.check == "interference.static" and f.calculation is not None
    ] + [c.group_key for c in session.contacts]

    assert len(groups) == 113
    assert sorted(judged) == sorted(groups)


def test_the_opening_is_the_digest_with_the_family_counted_and_no_rms_id(
    big_checks_first: ReplayPasses,
) -> None:
    opening = big_checks_first.second.opening
    session = big_checks_first.second.session

    assert DIGEST_HEADER in opening
    rms_ids = {f.id for f in session.findings if f.check.startswith("rms.")}
    assert rms_ids
    assert not rms_ids & set(re.findall(r"\bF-\d+\b", opening))
    [family_line] = [
        line for line in opening.splitlines() if line.startswith("  modelling practice:")
    ]
    assert f"{len(rms_ids)} findings across" in family_line


def test_the_rms_verdicts_equal_the_recordings(big_checks_first: ReplayPasses) -> None:
    recorded = Counter(
        finding_subject_key(item.finding)
        for item in big_checks_first.recording.findings
        if item.finding.check.startswith("rms.")
    )
    requested = Counter(
        finding_subject_key(finding)
        for finding in big_checks_first.second.session.findings
        if finding.check.startswith("rms.")
    )

    assert requested == recorded


def test_the_big_assembly_keeps_the_recorded_payload_shapes() -> None:
    package = load_package(FIXTURES / "big-assembly").package
    dispatch = ToolRegistry().dispatch(context_for(package))

    part = dispatch.call("check_rms_part", {"document_id": None}).payload
    mates = dispatch.call("list_mates", {"component_id": None}).payload

    assert sum(len(rows) for rows in part["subjects"].values()) == 866
    entities = [entity for mate in mates["result"] for entity in mate["entities"]]
    assert len(entities) == 110
    assert all(entity["persist_ref"] for entity in entities)
