"""`hole.nominal_alignment`: every joint's offset against the clearance it allows (T032).

`contracts/alignment.md` sections 1 and 2 are normative. At nominal sizes a joint's allowed
axis offset is the sum over its clearance holes of `(H - F) / 2` - a tapped hole centres
the screw on its thread and contributes nothing - which is the fixed-fastener relation for a
screw into a tapped hole and the floating one for a pin or bolt through clearance holes
(research R2.6). The allowed offset doubled is the position budget, reported as the callout
the drawing should carry (FR-008). A fastener that cannot pass a hole at all is a negative
term, demonstrated with both numbers (R2.4).
"""

from __future__ import annotations

import math

import pytest

from swreview.checks.joint_alignment import CHECK_NOMINAL, check_nominal_alignment
from swreview.checks.joints import Joint, build_joint_map, fold_by_pattern, folded_result
from swreview.ir.models import EvidencePackage, Quantity
from tests.support.mechanical import Face, Instance, PackageBuilder

Z = (0.0, 0.0, 1.0)


def parts(count: int) -> PackageBuilder:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    for index in range(1, count + 1):
        document = builder.document(f"FICT-KALO-{index:04d}", "part", material="Alloy Steel")
        builder.component(document, component_id=f"cmp:{index:04d}")
    return builder


def at(point: tuple[float, float, float], *faces: Face, direction=Z) -> list[Instance]:
    return [Instance(origin_mm=point, direction=direction, faces=faces)]


def only_joint(builder: PackageBuilder) -> tuple[Joint, EvidencePackage]:
    package = builder.build().package
    [joint] = build_joint_map(package).joints
    return joint, package


def screw_joint(
    clearance_bore: float = 3.4,
    offset: float = 0.0,
    *,
    size: str = "M3",
    thread: str = "M3x0.5",
    tapped_bore: float = 2.5,
    direction=Z,
):
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size=thread,
        thread=thread,
        end_condition="blind",
        instances=at((0.0, 0.0, 0.0), Face(tapped_bore, -8.0, 0.0), direction=direction),
    )
    builder.hole(
        "cmp:0002",
        hole_type="countersink",
        size=size,
        end_condition="through",
        instances=at((offset, 0.0, 0.0), Face(clearance_bore, 0.0, 2.5), direction=direction),
    )
    return builder


def dowel_joint(first_bore: float, second_bore: float, offset: float, *, size: str = "Ø3.0"):
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size=size,
        end_condition="through",
        instances=at((0.0, 0.0, 0.0), Face(first_bore, -6.0, 0.0)),
    )
    builder.hole(
        "cmp:0002",
        hole_type="clearance",
        size=size,
        end_condition="through",
        instances=at((offset, 0.0, 0.0), Face(second_bore, 0.0, 6.0)),
    )
    return builder


# --- the fixed and floating sums ---------------------------------------------------------


def test_a_screw_into_a_tapped_hole_is_fixed_and_the_tapped_hole_adds_no_term() -> None:
    joint, package = only_joint(screw_joint(clearance_bore=3.4))

    result = check_nominal_alignment(joint, package)

    assert result is not None
    assert result.check == CHECK_NOMINAL
    assert result.status == "checked_within_scope"
    assert result.severity == "info"
    values = result.calculation.result
    assert values["fixture"] == "fixed"
    assert values["fastener_mm"] == 3.0
    assert values["allowed_offset_mm"] == 0.2
    assert values["position_budget_mm"] == 0.4
    assert values["term_hol:0002_mm"] == 0.2
    assert "term_hol:0001_mm" not in values
    assert values["offset_mm"] == 0.0


def test_the_fixed_callout_shares_the_budget_between_the_two_holes() -> None:
    joint, package = only_joint(screw_joint(clearance_bore=3.4))

    callout = check_nominal_alignment(joint, package).calculation.result["callout"]

    assert callout == (
        "position ⌀0.4 total at nominal size, to be shared between hol:0002 and the tapped "
        "hol:0001 (fixed-fastener rule)"
    )


def test_a_pin_through_two_clearance_holes_is_floating_and_sums_both_terms() -> None:
    joint, package = only_joint(dowel_joint(3.1, 3.2, 0.0))

    values = check_nominal_alignment(joint, package).calculation.result

    assert values["fixture"] == "floating"
    assert values["fastener_mm"] == 3.0
    assert (values["term_hol:0001_mm"], values["term_hol:0002_mm"]) == (0.05, 0.1)
    assert values["allowed_offset_mm"] == 0.15
    assert values["callout"] == (
        "position ⌀0.1 at nominal size on hol:0001, ⌀0.2 on hol:0002 (floating-fastener rule)"
    )


def test_the_dowel_offset_beyond_its_clearance_is_demonstrated_with_both_numbers() -> None:
    """The big fixture's case: a 3.1 and a 3.0 mm hole 0.750 mm apart allow 0.050 mm."""
    joint, package = only_joint(dowel_joint(3.1, 3.0, 0.75))

    result = check_nominal_alignment(joint, package)

    assert result.status == "demonstrated"
    assert result.severity == "high"
    assert result.calculation.result["offset_mm"] == 0.75
    assert result.calculation.result["allowed_offset_mm"] == 0.05
    assert "0.75 mm" in result.observed and "0.05 mm" in result.observed


def test_an_offset_equal_to_the_allowed_offset_passes() -> None:
    joint, package = only_joint(dowel_joint(3.1, 3.1, 0.1))

    result = check_nominal_alignment(joint, package)

    assert result.calculation.result["allowed_offset_mm"] == 0.1
    assert result.status == "checked_within_scope"


def test_an_offset_just_beyond_the_allowed_offset_is_demonstrated() -> None:
    joint, package = only_joint(dowel_joint(3.1, 3.1, 0.101))

    assert check_nominal_alignment(joint, package).status == "demonstrated"


def test_a_line_to_line_pass_says_the_fit_has_no_clearance() -> None:
    joint, package = only_joint(dowel_joint(3.0, 3.0, 0.0))

    result = check_nominal_alignment(joint, package)

    assert result.status == "checked_within_scope"
    assert result.calculation.result["position_budget_mm"] == 0.0
    assert (
        "the joint has no clearance: the fit is line to line and any position error prevents "
        "assembly"
    ) in result.coverage_limits


# --- where F comes from, in precedence (research R2.5) ------------------------------------


def test_a_pin_members_measured_diameter_is_the_fastener_size() -> None:
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="Ø3.0",
        end_condition="through",
        instances=at((0.0, 0.0, 0.0), Face(3.1, 0.0, 10.0)),
    )
    builder.cylinder_face(
        "cmp:0002", origin_mm=(0.0, 0.0, 0.0), direction=Z, diameter_mm=2.98, lo_mm=1.0, hi_mm=12.0
    )
    joint, package = only_joint(builder)

    result = check_nominal_alignment(joint, package)

    assert result.calculation.result["fastener_mm"] == 2.98
    assert "measured diameter" in result.calculation.inputs["F_source"]


def test_a_tapped_thread_beats_the_clearance_holes_size() -> None:
    """An M4 counterbore over an M5 tapped hole: the thread says 5 mm, and 5 mm cannot pass
    a 4.5 mm bore - the negative term R2.4 turns into a finding."""
    joint, package = only_joint(
        screw_joint(clearance_bore=4.5, size="M4", thread="M5x0.8", tapped_bore=4.2)
    )

    result = check_nominal_alignment(joint, package)

    assert result.calculation.result["fastener_mm"] == 5.0
    assert "M5x0.8" in result.calculation.inputs["F_source"]
    assert result.status == "demonstrated"
    assert result.observed.startswith("A 5.0 mm fastener cannot pass hol:0002 (4.5 mm)")


def test_a_clearance_hole_sized_as_a_thread_gives_its_nominal() -> None:
    joint, package = only_joint(dowel_joint(9.0, 9.0, 0.0, size="M8"))

    result = check_nominal_alignment(joint, package)

    assert result.calculation.result["fastener_mm"] == 8.0
    assert "made for" in result.calculation.inputs["F_source"]


def test_no_fastener_size_from_any_source_is_unresolved_naming_it() -> None:
    joint, package = only_joint(dowel_joint(3.0, 3.1, 0.0, size="FICT"))

    result = check_nominal_alignment(joint, package)

    assert result.status == "unresolved"
    assert "the fastener size" in result.observed
    assert result.coverage_limits


def test_a_hole_of_unknown_type_leaves_its_size_unresolved() -> None:
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",
        end_condition="blind",
        instances=at((0.0, 0.0, 0.0), Face(2.5, -8.0, 0.0)),
    )
    builder.hole(
        "cmp:0002",
        hole_type="unknown",
        size="M3",
        end_condition="through",  # type: ignore[arg-type]
        instances=at((0.0, 0.0, 0.0), Face(3.4, 0.0, 2.5)),
    )
    joint, package = only_joint(builder)

    result = check_nominal_alignment(joint, package)

    assert result.status == "unresolved"
    assert "hol:0002" in result.observed


def test_a_joint_with_no_clearance_hole_has_no_alignment_to_judge() -> None:
    """A screw face in a lone tapped hole: the thread centres it and nothing else locates it."""
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",
        end_condition="blind",
        instances=at((0.0, 0.0, 0.0), Face(2.5, -8.0, 0.0)),
    )
    builder.cylinder_face(
        "cmp:0002", origin_mm=(0.0, 0.0, 0.0), direction=Z, diameter_mm=3.0, lo_mm=-6.0, hi_mm=4.0
    )
    joint, package = only_joint(builder)

    assert check_nominal_alignment(joint, package) is None


# --- measurement and units ------------------------------------------------------------


def test_oblique_axes_are_measured_on_their_own_line() -> None:
    tilt = (math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0)))
    joint, package = only_joint(screw_joint(clearance_bore=3.4, offset=0.1, direction=tilt))

    result = check_nominal_alignment(joint, package)

    assert result.calculation.result["offset_mm"] == pytest.approx(
        0.1 * math.cos(math.radians(30.0)), abs=1e-6
    )
    assert result.status == "checked_within_scope"


def test_an_inch_clearance_hole_for_a_metric_screw_is_compared_in_mm() -> None:
    builder = screw_joint(clearance_bore=5.1, size="#10", thread="M4x0.7", tapped_bore=3.3)
    package = builder.build().package
    inch = package.holes[1].model_copy(update={"diameter": Quantity(value=0.2, unit="in")})
    package = package.model_copy(update={"holes": [package.holes[0], inch]})
    [joint] = build_joint_map(package).joints

    result = check_nominal_alignment(joint, package)

    assert result.calculation.result["term_hol:0002_mm"] == pytest.approx((5.08 - 4.0) / 2)
    assert result.calculation.inputs["H_hol:0002_as_read"] == Quantity(value=0.2, unit="in")
    assert result.calculation.inputs["H_hol:0002"] == Quantity(value=5.08, unit="mm")
    assert result.calculation.inputs["H_hol:0002_source"] == "the Hole Wizard diameter"


def test_every_size_is_cited_with_its_source() -> None:
    joint, package = only_joint(screw_joint(clearance_bore=3.4))

    inputs = check_nominal_alignment(joint, package).calculation.inputs

    assert inputs["F"] == Quantity(value=3.0, unit="mm")
    assert inputs["F_source"] == "the thread of the tapped hole hol:0001 (M3x0.5)"
    assert inputs["H_hol:0002"] == Quantity(value=3.4, unit="mm")
    assert inputs["H_hol:0002_source"] == "derived from the cylinder face"


# --- folding a pattern ---------------------------------------------------------------------


def pattern_of(
    count: int, shifted: dict[int, float] | None = None
) -> tuple[list[Joint], EvidencePackage]:
    """`count` screw joints of one pattern; `shifted` moves some countersinks sideways."""
    shifted = shifted or {}
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",
        end_condition="blind",
        instances=[
            Instance((10.0 * k, 0.0, 0.0), Z, (Face(2.5, -8.0, 0.0),)) for k in range(count)
        ],
    )
    builder.hole(
        "cmp:0002",
        hole_type="countersink",
        size="M3",
        end_condition="through",
        instances=[
            Instance((10.0 * k + shifted.get(k, 0.0), 0.0, 0.0), Z, (Face(3.4, 0.0, 2.5),))
            for k in range(count)
        ],
    )
    package = builder.build().package
    return list(build_joint_map(package).joints), package


def test_fifteen_identical_joints_of_one_pattern_fold_into_one_finding() -> None:
    joints, package = pattern_of(15)
    results = [(joint, check_nominal_alignment(joint, package)) for joint in joints]

    folded = fold_by_pattern(results)

    [(members, result)] = folded
    assert len(members) == 15
    finding = folded_result(members, result)
    assert finding.observed.startswith("15 joints (jnt:0001 hol:0001#1+hol:0002#1, ")
    assert "jnt:0015 hol:0001#15+hol:0002#15" in finding.observed
    assert finding.calculation == result.calculation


def test_a_joint_whose_numbers_differ_stays_its_own_finding() -> None:
    """Plan RK-4: the fold key holds the calculation result, so a differing joint of the
    same pattern is never hidden inside its siblings' finding."""
    joints, package = pattern_of(3, shifted={2: 0.1})
    results = [(joint, check_nominal_alignment(joint, package)) for joint in joints]

    folded = fold_by_pattern(results)

    assert len({joint.pattern_key for joint in joints}) == 1
    assert [[joint.id for joint in members] for members, _ in folded] == [
        ["jnt:0001", "jnt:0002"],
        ["jnt:0003"],
    ]
    assert folded[1][1].calculation.result["offset_mm"] == 0.1


def test_a_single_joint_is_named_in_its_finding_too() -> None:
    joint, package = only_joint(dowel_joint(3.1, 3.0, 0.75))
    result = check_nominal_alignment(joint, package)

    finding = folded_result((joint,), result)

    assert finding.observed.startswith("1 joint (jnt:0001 hol:0001#1+hol:0002#1): ")
