"""The User Story 1 acceptance on the committed fixtures (008 T022, SC-001).

Each fixture is shaped like one recorded review - the big assembly and two runs of the small
one - and replaying it with the settings it was recorded with must reproduce every recorded
round within 1% and the finding set exactly. Every replay of a committed fixture is graded with
`config/standards.example.yaml`, the profile the pilot ran (research R2.10). The payload shapes
that make later savings measurable are pinned too: the part check's 866 feature rows and the
110 mate entities with their persistent references.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import pytest

from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.replay import ReplayReport, replay
from swreview.ir.loader import load_package
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


@pytest.mark.parametrize("name", NAMES)
def test_the_finding_set_is_exact(name: str) -> None:
    findings = as_recorded(name).findings

    assert findings.lost == []
    assert findings.added == []
    assert findings.not_replayable == []
    assert findings.recorded == findings.replayed


def test_the_big_assembly_has_one_estimated_round_the_live_call() -> None:
    report = as_recorded("big-assembly")

    estimated = [r for r in report.rounds if r.estimated]
    assert len(estimated) == 1
    assert [c.tool for c in estimated[0].calls if c.class_ == "estimated"] == [
        "bridge_interference"
    ]
    assert report.totals.estimated_rounds == 1
    assert report.totals.lower_bound_rounds == 0


def test_the_big_assembly_carries_one_presentation_round() -> None:
    report = as_recorded("big-assembly")

    assert report.totals.carried_rounds == 1
    assert [r.kind for r in report.rounds].count("presentation") == 1


def test_the_big_assembly_recorded_total_is_twelve_point_four_million() -> None:
    total = as_recorded("big-assembly").totals.recorded

    assert abs(total - 12_400_000) / 12_400_000 < TOLERANCE


def test_the_big_assembly_keeps_the_recorded_payload_shapes() -> None:
    package = load_package(FIXTURES / "big-assembly").package
    dispatch = ToolRegistry().dispatch(context_for(package))

    part = dispatch.call("check_rms_part", {"document_id": None}).payload
    mates = dispatch.call("list_mates", {"component_id": None}).payload

    assert sum(len(rows) for rows in part["subjects"].values()) == 866
    entities = [entity for mate in mates["result"] for entity in mate["entities"]]
    assert len(entities) == 110
    assert all(entity["persist_ref"] for entity in entities)
