"""`check_joints`, the argument-free tool that records the joint map (feature 010 T027).

`contracts/code-first.md` section 3 and `contracts/joint-map.md` section 7 are normative:
the tool takes no argument, records one `checked` `joint.map` item per pattern group and one
`skipped` item per candidate and per gap, returns counts rather than a payload to page
through, and is the first name in `CODE_FIRST_CHECKS`, so the pre-run calls it before the
first turn at no model round.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from swreview.ir.loader import load_package
from swreview.report.session import CoverageItem
from swreview.tools import checks_mechanical
from swreview.tools.checks_mechanical import JOINT_MAP_CHECK, check_joints
from swreview.tools.context import ToolContext, build_context, context_for, use_context
from swreview.tools.registry import ToolRegistry, check_tools
from tests.support.mechanical import PackageBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"


def fixture_context(name: str) -> ToolContext:
    return build_context(load_package(FIXTURES / name))


def run(context: ToolContext) -> dict[str, Any]:
    with use_context(context):
        return check_joints()


def joint_items(context: ToolContext, bucket: str) -> list[CoverageItem]:
    return [
        item
        for item in getattr(context.require_session().coverage, bucket)
        if item.check == JOINT_MAP_CHECK
    ]


@pytest.fixture(scope="module")
def big() -> tuple[ToolContext, dict[str, Any]]:
    context = fixture_context("big-assembly")
    return context, run(context)


# --- the tool's shape ---------------------------------------------------------------------


def test_check_joints_takes_no_argument_and_is_a_check_tool() -> None:
    assert inspect.signature(check_joints).parameters == {}
    assert check_joints in check_tools()


def test_check_joints_is_the_first_code_first_check() -> None:
    assert checks_mechanical.CODE_FIRST_CHECKS == ("check_joints",)


def test_the_joint_map_check_is_not_a_checklist_item() -> None:
    """So none of these rows closes `holes.alignment` or `fasteners` (section 7)."""
    context = context_for(PackageBuilder(design_stem="FICT-KALO-0000").build().package)

    assert JOINT_MAP_CHECK == "joint.map"
    assert JOINT_MAP_CHECK not in {item.id for item in context.checklist.items}


# --- what it records on the big fixture -------------------------------------------------


def test_one_checked_item_per_pattern_group(big) -> None:
    context, _ = big

    checked = joint_items(context, "checked")

    assert len(checked) == 11
    reasons = [item.reason for item in checked]
    assert any(reason.startswith("15 screw joints: ") for reason in reasons)
    assert any(reason.startswith("16 screw joints: ") for reason in reasons)
    [dowel] = [reason for reason in reasons if "hol:0018#1" in reason]
    assert dowel.startswith("1 pin joint: jnt:")
    assert "hol:0018#1+hol:0027#2" in dowel


def test_a_pattern_group_item_names_its_member_components_and_their_pairs(big) -> None:
    """Every member counts, the screw whose face sits in one of the joints included."""
    context, _ = big

    [item] = [
        item for item in joint_items(context, "checked") if item.reason.startswith("16 screw")
    ]

    assert item.scope.component_ids == ["cmp:0001", "cmp:0002", "cmp:0017"]
    assert item.scope.pairs == [
        ["cmp:0001", "cmp:0002"],
        ["cmp:0001", "cmp:0017"],
        ["cmp:0002", "cmp:0017"],
    ]
    assert item.scope.configuration == "Default"
    assert "jnt:" in item.reason and "hol:0016#1+hol:0023#1+cmp:0017" in item.reason


def test_one_skipped_item_per_candidate(big) -> None:
    context, _ = big

    candidates = [item for item in joint_items(context, "skipped") if "not a joint" in item.reason]

    assert [item.reason for item in candidates] == [
        "hol:0018#2 and hol:0024#1 are not a joint: overlap_near (angle 0.0 deg, offset 7.006 "
        "mm, radius sum 6.05 mm, gap 0.0 mm); listed for the engineer",
        "hol:0018#2 and hol:0027#1 are not a joint: assigned_elsewhere (angle 0.0 deg, offset "
        "0.75 mm, radius sum 3.05 mm, gap 0.0 mm); listed for the engineer",
    ]
    assert candidates[0].scope.component_ids == ["cmp:0003", "cmp:0004"]


def test_one_skipped_item_per_gap(big) -> None:
    context, _ = big

    gaps = [item for item in joint_items(context, "skipped") if "not a joint" not in item.reason]

    assert len(gaps) == 6
    faceless = [item for item in gaps if "no cylinder face" in item.reason]
    assert [item.reason.split()[0] for item in faceless] == ["hol:0007", "hol:0009"]
    assert all(item.scope.component_ids == ["cmp:0001"] for item in faceless)
    free = {
        item.scope.component_ids[0]: int(item.reason.split()[0])
        for item in gaps
        if "cylinder faces on" in item.reason
    }
    assert free == {"cmp:0001": 3, "cmp:0003": 4, "cmp:0005": 3, "cmp:0011": 3}
    assert sum(free.values()) == 13, "one row per part with holes, each with its count"


def test_it_returns_counts_and_not_a_payload(big) -> None:
    context, result = big

    assert result["status"] == "recorded"
    assert result["joints"] == {"total": 50, "by_kind": {"screw": 47, "pin": 2, "unclassified": 1}}
    assert result["pattern_groups"] == 11
    assert result["candidates"] == 2
    assert result["unplaced_fasteners"] == 0
    session = context.require_session()
    assert result["findings"] == len(session.findings)
    assert result["finding_ids"] == [finding.id for finding in session.findings]
    assert result["coverage"] == {
        "checked": len(session.coverage.checked),
        "skipped": len(session.coverage.skipped),
        "unresolved": len(session.coverage.unresolved),
    }
    assert "joint_map" not in result and "instances" not in result


def test_the_small_fixture_records_one_pin_joint() -> None:
    context = fixture_context("small-assembly")

    result = run(context)

    assert result["joints"] == {"total": 1, "by_kind": {"pin": 1}}
    [item] = joint_items(context, "checked")
    assert item.reason == "1 pin joint: jnt:0001 hol:0004#1+cmp:0003"
    assert item.scope.component_ids == ["cmp:0001", "cmp:0003"]
    assert joint_items(context, "skipped") == []


# --- the two package-level rows -----------------------------------------------------------


def test_a_package_with_no_hole_row_is_one_skipped_row() -> None:
    context = context_for(PackageBuilder(design_stem="FICT-KALO-0000").build().package)

    result = run(context)

    assert [
        (item.reason, item.scope.component_ids) for item in joint_items(context, "skipped")
    ] == [("no hole was extracted", [])]
    assert joint_items(context, "checked") == []
    assert result["joints"] == {"total": 0, "by_kind": {}}


def test_a_model_check_package_is_one_skipped_row() -> None:
    package = PackageBuilder(design_stem="FICT-KALO-0000").build().package
    model_check = package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"profile": "model_check"})}
    )
    context = context_for(model_check)

    run(context)

    assert [item.reason for item in joint_items(context, "skipped")] == [
        "the hole phase did not run (profile model_check)"
    ]


# --- alignment on the big fixture (T036, contracts/alignment.md) ---------------------------


def alignment_findings(context: ToolContext) -> list:
    return [
        finding
        for finding in context.require_session().findings
        if finding.check == "hole.nominal_alignment"
    ]


def test_the_dowel_joint_is_demonstrated_misaligned_0_750_against_0_050(big) -> None:
    """SC-003: the 0.75 mm dowel offset is reported, by code, against its clearance."""
    context, _ = big

    [dowel] = [
        finding for finding in alignment_findings(context) if finding.status == "demonstrated"
    ]

    assert dowel.severity == "high"
    assert dowel.observed.startswith("1 joint (jnt:0048 hol:0018#1+hol:0027#2): ")
    result = dowel.calculation.result
    assert (result["offset_mm"], result["allowed_offset_mm"]) == (0.75, 0.05)
    assert result["fixture"] == "floating"
    assert result["callout"] == (
        "position ⌀0.1 at nominal size on hol:0018, ⌀0.0 on hol:0027 (floating-fastener rule)"
    )
    assert dowel.component_ids == ["cmp:0004", "cmp:0005"]


def test_every_other_pattern_group_passes_folded_into_one_finding_each(big) -> None:
    context, _ = big

    passes = [
        finding
        for finding in alignment_findings(context)
        if finding.status == "checked_within_scope"
    ]

    assert len(passes) == 8
    counts = sorted(int(finding.observed.split(" ", 1)[0]) for finding in passes)
    assert counts == [1, 1, 3, 3, 4, 4, 15, 16]
    [line_to_line] = [
        finding for finding in passes if finding.calculation.result["allowed_offset_mm"] == 0.0
    ]
    assert "hol:0017#1+hol:0027#1" in line_to_line.observed
    assert any("line to line" in limit for limit in line_to_line.coverage_limits)


def test_the_screw_joints_carry_their_fixed_fastener_budget(big) -> None:
    context, _ = big

    [m2] = [
        finding for finding in alignment_findings(context) if finding.observed.startswith("16 ")
    ]

    result = m2.calculation.result
    assert (result["fastener_mm"], result["allowed_offset_mm"]) == (2.0, 0.2)
    assert result["callout"] == (
        "position ⌀0.4 total at nominal size, to be shared between hol:0023 and the tapped "
        "hol:0016 (fixed-fastener rule)"
    )
    assert m2.inputs[:2] == ["hol:0016#1", "hol:0023#1"]


def test_the_stack_is_one_skipped_item_for_every_joint(big) -> None:
    context, _ = big
    session = context.require_session()

    stacks = [item for item in session.coverage.skipped if item.check == "hole.position_stack"]

    assert [item.reason for item in stacks] == [
        "no tolerance source is read for this package; searched: drawing callout, model "
        "annotation, model dimension, Hole Wizard class, general tolerance"
    ]
    assert not [finding for finding in session.findings if finding.check == "hole.position_stack"]


def test_the_joints_with_no_clearance_hole_are_named_once(big) -> None:
    context, _ = big

    [item] = [
        item
        for item in context.require_session().coverage.skipped
        if item.check == "hole.nominal_alignment"
    ]

    assert item.reason.startswith("no clearance hole to line up in jnt:0011, jnt:0049: ")


def test_the_result_counts_the_alignment_findings(big) -> None:
    _, result = big

    assert result["findings"] == 9
    assert result["by_status"] == {"checked_within_scope": 8, "demonstrated": 1}


def test_the_small_fixtures_pin_passes_with_a_zero_budget() -> None:
    context = fixture_context("small-assembly")

    run(context)

    [finding] = alignment_findings(context)
    assert finding.status == "checked_within_scope"
    assert finding.calculation.result["position_budget_mm"] == 0.0
    assert "measured diameter" in finding.calculation.inputs["F_source"]


# --- through the registry -------------------------------------------------------------------


def test_check_joints_through_the_registry_is_one_real_step() -> None:
    context = fixture_context("small-assembly")
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}

    payload = tools["check_joints"].call({}).payload

    assert payload["status"] == "recorded"
    assert [step.tool for step in context.require_session().steps] == ["check_joints"]


def test_check_joints_refuses_an_argument_through_the_registry() -> None:
    context = fixture_context("small-assembly")
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}

    result = tools["check_joints"].call({"hole_id": "hol:0001"})

    assert result.is_error is True
