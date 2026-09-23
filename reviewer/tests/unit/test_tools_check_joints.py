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

from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.loader import load_package
from swreview.report.session import CoverageItem
from swreview.tools import checks_mechanical
from swreview.tools.checks_mechanical import JOINT_MAP_CHECK, check_joints
from swreview.tools.context import ToolContext, build_context, context_for, use_context
from swreview.tools.registry import ToolRegistry, check_tools
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
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
    """Edited deliberately by feature 010 T046: `check_joints` records the map with the
    recognised fasteners placed, which adds two pattern groups - the eight screws on
    `hol:0003`'s clearance instances and the second M4 on `hol:0022` - to the foundational
    eleven (the foundational map keeps its own golden, T029)."""
    context, _ = big

    checked = joint_items(context, "checked")

    assert len(checked) == 13
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

    gaps = [
        item
        for item in joint_items(context, "skipped")
        if "not a joint" not in item.reason and "was not placed" not in item.reason
    ]

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
    # Edited deliberately by feature 010 T046: the map is the one with the fasteners placed
    # (50 foundational joints, 47 screw, 2 pin, 1 unclassified, before US4).
    assert result["joints"] == {"total": 59, "by_kind": {"screw": 57, "pin": 2}}
    assert result["pattern_groups"] == 13
    assert result["candidates"] == 2
    assert result["recognised_fasteners"] == 68
    assert result["unplaced_fasteners"] == 11
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
    # jnt:0048 in the foundational map; the placed fasteners renumber it (T046).
    assert dowel.observed.startswith("1 joint (jnt:0056 hol:0018#1+hol:0027#2): ")
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
    """Edited deliberately by feature 010 T046: with the fasteners placed the ids move, the
    second M4 on `hol:0022` joins the list, and the eight screws placed by their origin on
    `hol:0003`'s clearance instances are named once, as having no second axis to line up."""
    context, _ = big

    tapped_only, single = [
        item
        for item in context.require_session().coverage.skipped
        if item.check == "hole.nominal_alignment"
    ]

    assert tapped_only.reason.startswith(
        "no clearance hole to line up in jnt:0019, jnt:0057, jnt:0058: "
    )
    assert single.reason.startswith(
        "one measured member only in jnt:0001, jnt:0002, jnt:0003, jnt:0004, jnt:0005, "
        "jnt:0006, jnt:0007, jnt:0008: "
    )


def test_the_result_counts_the_alignment_findings(big) -> None:
    """Edited deliberately by feature 010 T046 and T060: 9 alignment findings, the fastener
    family's 25, and US5's 7 head-clearance and 6 head-fit folds."""
    _, result = big

    assert result["findings"] == 47
    assert result["by_status"] == {
        "checked_within_scope": 34,
        "demonstrated": 8,
        "unresolved": 4,
        "suspected": 1,
    }
    assert len(alignment_findings(big[0])) == 9


def test_the_small_fixtures_pin_passes_with_a_zero_budget() -> None:
    context = fixture_context("small-assembly")

    run(context)

    [finding] = alignment_findings(context)
    assert finding.status == "checked_within_scope"
    assert finding.calculation.result["position_budget_mm"] == 0.0
    assert "measured diameter" in finding.calculation.inputs["F_source"]


# --- fasteners on the big fixture (T046, contracts/fasteners.md section 6) -------------------


def fastener_findings(context: ToolContext, check: str) -> list:
    return [finding for finding in context.require_session().findings if finding.check == check]


def engagement_of(context: ToolContext, hole_id: str):
    [finding] = [
        finding
        for finding in fastener_findings(context, "fastener.engagement")
        if f"into {hole_id}" in finding.observed or f"in {hole_id}:" in finding.observed
    ]
    return finding


def test_68_of_68_named_screws_are_recognised(big) -> None:
    """SC-004: every screw named in the vendor pattern, recognised by code."""
    _, result = big

    assert result["recognised_fasteners"] == 68


def test_the_two_m4_screws_in_m5_threads_are_one_thread_match_finding(big) -> None:
    """SC-002: one screw part mis-threaded into one part at two holes is one condition."""
    context, _ = big

    [mismatch] = [
        finding
        for finding in fastener_findings(context, "fastener.thread_match")
        if finding.status == "demonstrated"
    ]

    assert mismatch.severity == "high"
    assert mismatch.observed.startswith(
        "2 joints (jnt:0019 hol:0013#1+cmp:0007, jnt:0058 hol:0022#1): "
    )
    result = mismatch.calculation.result
    assert (result["fastener_thread"], result["hole_thread"]) == ("M4X0.7", "M5X0.8")


@pytest.mark.parametrize(
    ("hole_id", "count", "engaged", "required_ratio", "status"),
    [
        ("hol:0006", 3, 10.225, 1.5, "demonstrated"),  # M10: 15.0 required
        ("hol:0016", 16, 2.205, 1.5, "demonstrated"),  # M2: 3.0 required
        ("hol:0004", 3, 14.375, 1.5, "checked_within_scope"),  # M8
        ("hol:0012", 4, 14.6, 1.5, "checked_within_scope"),  # M8
        ("hol:0014", 15, 5.133, 1.5, "checked_within_scope"),  # M3
        ("hol:0015", 4, 5.883, 1.5, "checked_within_scope"),  # M3
    ],
)
def test_the_engagement_table_of_research_r2_13(
    big, hole_id: str, count: int, engaged: float, required_ratio: float, status: str
) -> None:
    context, _ = big

    finding = engagement_of(context, hole_id)

    assert finding.status == status
    assert finding.observed.startswith(f"{count} joint")
    assert finding.calculation.result["engagement_mm"] == engaged
    assert finding.calculation.result["required_ratio"] == required_ratio


def test_the_m3_in_a_thin_sheet_is_short_at_low_severity_with_the_derived_length(big) -> None:
    context, _ = big

    finding = engagement_of(context, "hol:0021")

    assert (finding.status, finding.severity) == ("demonstrated", "low")
    assert finding.calculation.result["engagement_mm"] == 1.394
    assert finding.calculation.result["sheet_thickness_mm"] == 1.725
    assert finding.calculation.inputs["usable_thread_source"] == (
        "derived: through-tapped length from the tapped face"
    )


def test_the_oblique_m4_engagement_is_unresolved_naming_the_oblique_axis(big) -> None:
    context, _ = big

    [unresolved] = [
        finding
        for finding in fastener_findings(context, "fastener.engagement")
        if finding.status == "unresolved"
    ]

    assert "hol:0013#1 (the axis is oblique; bounding-box extents are not used)" in (
        unresolved.observed
    )


def test_the_screw_named_m5_with_a_3_3_mm_shank_is_one_suspected_identity(big) -> None:
    context, _ = big

    [identity] = fastener_findings(context, "fastener.identity")

    assert (identity.status, identity.severity) == ("suspected", "medium")
    assert "is named M5x0.8 but its shank measures 3.3 mm" in identity.observed
    assert identity.component_ids == ["cmp:0078"]


def test_every_unplaced_screw_is_one_skipped_joint_map_row(big) -> None:
    context, _ = big

    unplaced = [item for item in joint_items(context, "skipped") if "was not placed" in item.reason]

    assert len(unplaced) == 11
    assert unplaced[0].reason == (
        "M5x0.8 was not placed: it has no face in a hole and its origin lies on no hole "
        "instance's axis"
    )


def test_screws_whose_tapped_part_has_no_hole_are_one_skipped_item(big) -> None:
    context, _ = big

    [item] = [
        item
        for item in context.require_session().coverage.skipped
        if item.check == "fastener.engagement"
    ]

    assert item.reason.startswith("9 placed screws (cmp:0071 in hol:0003#1, ")
    assert "cmp:0069 in hol:0025#2" in item.reason


# --- tool access and head fit on the big fixture (T060, contracts/tool-access.md s. 5) -------


def test_the_head_under_the_clevis_leg_is_demonstrated_naming_it(big) -> None:
    context, _ = big

    [blocked] = [
        finding
        for finding in fastener_findings(context, "fastener.head_clearance")
        if finding.status == "demonstrated"
    ]

    assert blocked.observed.startswith("1 joint (jnt:0015 hol:0012#1+hol:0024#1+cmp:0061): ")
    assert "runs into cmp:0004 at 0.6 mm" in blocked.observed
    assert blocked.calculation.inputs["tool"] == "hex_key"
    assert blocked.calculation.inputs["tool_source"].startswith("pilot default")


def test_every_other_placed_screw_head_is_clear(big) -> None:
    context, _ = big

    clearances = fastener_findings(context, "fastener.head_clearance")
    clear = [finding for finding in clearances if finding.status == "checked_within_scope"]

    assert len(clearances) == len(clear) + 1
    assert sum(int(finding.observed.split(" ", 1)[0]) for finding in clear) == 47
    assert not [
        item
        for item in context.require_session().coverage.skipped
        if item.check == "fastener.head_clearance"
    ]


def test_the_12_mm_counterbore_under_an_m8_socket_head_is_demonstrated(big) -> None:
    context, _ = big

    [tight] = [
        finding
        for finding in fastener_findings(context, "fastener.head_fit")
        if finding.status == "demonstrated"
    ]

    assert tight.observed == (
        "1 joint (jnt:0059 hol:0025#2+cmp:0069): The 12.0 mm counterbore of hol:0025#2 is "
        "smaller than the 13.0 mm head of an M8x1.25 socket head cap (ISO 4762): the head "
        "cannot seat"
    )


def test_the_14_mm_counterbores_under_the_same_head_pass(big) -> None:
    context, _ = big

    passes = sorted(
        (
            finding.calculation.result["recess_diameter_mm"],
            finding.calculation.result["recess_depth_mm"],
            int(finding.observed.split(" ", 1)[0]),
        )
        for finding in fastener_findings(context, "fastener.head_fit")
        if finding.status == "checked_within_scope"
    )

    # hol:0010 (3 joints, 8.375 deep) and hol:0024 (4 joints, 8.6 deep) under M8 heads of
    # 13.0 x 8.0; hol:0011 under M10 heads of 16.0 x 10.0.
    assert passes == [(14.0, 8.375, 3), (14.0, 8.6, 4), (17.5, 10.225, 3)]


def test_the_flat_head_torx_countersinks_are_unresolved_for_want_of_a_head_row(big) -> None:
    """FHT is flat head Torx (owner answer); the head table carries ISO 10642's hexagon socket
    countersunk heads and nothing for a flat head, so head fit waits rather than borrows."""
    context, _ = big

    unresolved = [
        finding
        for finding in fastener_findings(context, "fastener.head_fit")
        if finding.status == "unresolved"
    ]

    assert sorted(int(finding.observed.split(" ", 1)[0]) for finding in unresolved) == [16, 19]
    assert all("flat head" in finding.observed for finding in unresolved)


# --- the stack's tolerance sources (feature 010 US8, T084) ----------------------------------
#
# The tolerances fixture (IR 1.5.0): a dowel joint whose three sizes each bind to one model
# dimension - the plate hole's by a class-only H7 fit, which is where a hole's ISO class
# arrives (the Hole Wizard's own fit is a screw clearance fit, the C# lane found), the block
# hole's and the pin's by bilateral limits - and a screw joint whose counterbore bore meets
# two equal 4.5 mm dimensions, so its stack is unresolved and names every source searched.

PROFILE_A = Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "profile-a.yaml"

EVERY_SOURCE = (
    "drawing callout: ",
    "model annotation: ",
    "model dimension: ",
    "Hole Wizard class: ",
    "general tolerance: ",
)


def version_1(profile: StandardsProfile) -> StandardsProfile:
    return profile.model_copy(update={"version": 1, "hygiene": None, "general_tolerance": None})


def with_profile(name: str, profile: StandardsProfile | None) -> ToolContext:
    """The fixture's context, carrying a standards run over `profile` when one is given: the
    joint checks read the attached profile and never load one."""
    context = fixture_context(name)
    if profile is not None:
        attach_standards_run(
            context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
        )
    return context


def stacks_of(context: ToolContext) -> dict[str, Any]:
    """The `hole.position_stack` findings, by their first input instance."""
    return {
        finding.inputs[0]: finding
        for finding in context.require_session().findings
        if finding.check == "hole.position_stack"
    }


@pytest.fixture(scope="module")
def tolerances() -> tuple[ToolContext, dict[str, Any]]:
    context = with_profile("tolerances", load_profile(PROFILE_A))
    return context, run(context)


def test_the_tolerances_fixture_is_two_joints_and_nothing_skipped(tolerances) -> None:
    context, result = tolerances

    assert result["joints"] == {"total": 2, "by_kind": {"pin": 1, "screw": 1}}
    assert result["recognised_fasteners"] == 1
    assert context.require_session().coverage.skipped == []


def test_the_dowel_stack_is_size_only_with_h7_from_the_hole_dimension(tolerances) -> None:
    """H7 on 3 mm is 0/+0.010 (ISO 286-1, the band up to and including 3 mm); the block's hole
    is +0.002/+0.012 and the pin 0/-0.006, so the least clearance is (0 + 0.002)/2 = 0.001 mm
    and the most (0.016 + 0.018)/2 = 0.017 mm, over two floating-fastener half clearances."""
    context, _ = tolerances

    stack = stacks_of(context)["hol:0001#1"]
    inputs = stack.calculation.inputs

    assert stack.status == "checked_within_scope"
    assert stack.calculation.result == {
        "model": "size_only",
        "offset_mm": 0.0,
        "position_half_zones_mm": 0.0,
        "clearance_min_mm": 0.001,
        "clearance_max_mm": 0.017,
        "fastener_min_mm": 2.994,
        "fastener_max_mm": 3.0,
    }
    assert (inputs["hol:0001#1_min"].value, inputs["hol:0001#1_max"].value) == (3.0, 3.01)
    assert (inputs["hol:0003#1_min"].value, inputs["hol:0003#1_max"].value) == (3.002, 3.012)
    assert (inputs["fastener_min"].value, inputs["fastener_max"].value) == (2.994, 3.0)
    assert stack.observed.endswith(
        "The member axes are 0.0 mm apart, within the 0.001 mm the smallest permitted "
        "clearance allows (size only)"
    )


def test_each_dowel_size_cites_its_own_source(tolerances) -> None:
    context, _ = tolerances

    inputs = stacks_of(context)["hol:0001#1"].calculation.inputs

    assert inputs["hol:0001#1_source"] == (
        "model dimension: dimension KALOMIR1@FICT-HOLE-0001 (mdm:0001): fit class H7, per "
        "ISO 286-1 (iso286.yaml)"
    )
    assert inputs["hol:0003#1_source"] == (
        "model dimension: dimension KALOMIR4@FICT-HOLE-0001 (mdm:0004)"
    )
    assert inputs["fastener_source"] == (
        "model dimension: dimension KALOMIR5@FICT-HOLE-0001 (mdm:0005)"
    )


def test_a_position_zone_with_no_unit_binds_nothing_and_says_why(tolerances) -> None:
    """The GTol on the plate's dowel face states 0.02 with no unit, and the package carries
    no length unit for the part: the stack stays size-only and names the zone it could not
    size rather than guessing millimetres (SC-007)."""
    context, _ = tolerances

    excluded = stacks_of(context)["hol:0001#1"].calculation.excluded_effects

    [position] = [item for item in excluded if item.startswith("the position of hol:0001#1")]
    assert (
        "model annotation: man:0001 is attached to hol:0001#1 and states a position zone of "
        "0.02, but the part's length unit is not in the package, so the zone's size is unknown"
    ) in position


def test_the_screw_stack_is_unresolved_naming_every_source(tolerances) -> None:
    context, _ = tolerances

    stack = stacks_of(context)["hol:0002#1"]
    searched = stack.coverage_limits[1]

    assert stack.status == "unresolved"
    assert stack.observed.endswith(
        "a tolerance for the size of hol:0002#1 is unknown; the check did not run"
    )
    assert searched.startswith("the size of hol:0002#1: searched drawing callout: ")
    assert all(source in searched for source in EVERY_SOURCE)
    assert "2 dimensions of doc:0002 are 4.5 mm (mdm:0002, mdm:0003)" in searched
    assert "a Hole Wizard fit is a screw clearance fit" in searched
    assert (
        "general tolerance: the precision its dimension is written to is not recorded"
    ) in searched


def test_the_counterbore_is_sized_by_its_wizard_through_hole_diameter_as_read(tolerances) -> None:
    """IR 1.5.0 carries the Hole Wizard's own sizes; the alignment reads the counterbore's
    bore from `thru_hole_diameter` and keeps the metres it was written in."""
    context, _ = tolerances

    [alignment] = [
        finding
        for finding in context.require_session().findings
        if finding.check == "hole.nominal_alignment" and finding.inputs[0] == "hol:0002#1"
    ]
    inputs = alignment.calculation.inputs

    assert inputs["H_hol:0002"].value == 4.5
    assert inputs["H_hol:0002_source"] == "the Hole Wizard diameter"
    assert (inputs["H_hol:0002_as_read"].value, inputs["H_hol:0002_as_read"].unit) == (0.0045, "m")


@pytest.mark.parametrize(
    ("profile", "general"),
    [
        ("version 1", "general tolerance: the profile is version 1, which declares no general "),
        (None, "general tolerance: no standards profile is attached"),
    ],
)
def test_without_a_version_2_profile_the_general_source_is_still_searched(
    profile: str | None, general: str
) -> None:
    attached = None if profile is None else version_1(load_profile(PROFILE_A))
    context = with_profile("tolerances", attached)
    run(context)

    stacks = stacks_of(context)

    assert general in stacks["hol:0002#1"].coverage_limits[1]
    assert stacks["hol:0001#1"].calculation.result["model"] == "size_only"


def test_a_version_2_profile_alone_is_no_source_so_the_one_skipped_item_remains() -> None:
    """General tolerance binds nothing before feature 011 records a dimension's precision, so
    a version 2 profile on a package with no other source leaves the one skipped item."""
    context = with_profile("big-assembly", load_profile(PROFILE_A))
    run(context)
    session = context.require_session()

    stacks = [item for item in session.coverage.skipped if item.check == "hole.position_stack"]

    assert [item.reason for item in stacks] == [
        "no tolerance source is read for this package; searched: drawing callout, model "
        "annotation, model dimension, Hole Wizard class, general tolerance"
    ]
    assert not stacks_of(context)


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
