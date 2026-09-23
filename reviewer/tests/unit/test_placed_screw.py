"""The placed screw: thread match, engagement and bottoming from the assembly (feature 010 T044).

`contracts/fasteners.md` section 4 is normative. `check_placed_screw` reads the protrusion
and the usable thread off the placed geometry rather than a clamped stack a model names, and
decides with the same four rule functions as `check_fastener_joint`:

- the protrusion is the tip's depth below the thread entry, along the tapped axis;
- a blind hole's usable thread is its `thread_depth`, a through-tapped hole's its tapped
  face's length, labelled derived - never `hole_depth`, never a blind face's extent;
- an oblique axis read from face boxes, a screw its shank contradicts, a blind hole with no
  thread depth and an unknown end condition are unresolved, naming why;
- a through-tapped part too thin for 1.5 x d is a finding at low severity carrying the sheet
  thickness (owner answer 2026-09-23).
"""

from __future__ import annotations

import math

import pytest
import trimesh

from swreview.checks.fastener import (
    CHECK_BOTTOMING,
    CHECK_ENGAGEMENT,
    CHECK_HEAD_CLEARANCE,
    CHECK_THREAD_MATCH,
    THROUGH_TAPPED_SOURCE,
    Placement,
    UsableThread,
    _Stack,
    _thread_match,
    check_placed_screw,
)
from swreview.checks.fastener_identity import measure_placement, recognise_fasteners
from swreview.checks.joints import Joint, build_joint_map
from swreview.checks.result import CheckResult
from swreview.ir.models import EvidencePackage, Fastener, Hole
from tests.support.mechanical import Face, Instance, PackageBuilder, cylinder_mesh

Z = (0.0, 0.0, 1.0)
TILT = (math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0)))


def by_check(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {result.check: result for result in results}


def screw_joint(
    *,
    thread: str = "M5-0.8",
    length: float = 16.0,
    tapped: str = "M5x0.8",
    end_condition: str = "blind",
    face: Face = Face(4.2, -12.0, 0.0),  # noqa: B008 - a frozen value, never mutated
    thread_depth_mm: float | None = 10.0,
    hole_depth_mm: float | None = 12.0,
    bearing_z: float = 10.0,
    shank_face_mm: float | None = 5.0,
    direction: tuple[float, float, float] = Z,
    material: str = "Alloy Steel",
) -> tuple[EvidencePackage, Joint]:
    """One screw over one tapped hole in a plate, the screw's bearing face `bearing_z` above
    the axis origin and the tapped face at `face` along the axis."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    plate = builder.document("FICT-KALOMIR-0001", "part", material=material)
    builder.component(plate, component_id="cmp:0001")
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size=tapped,
        thread=tapped,
        thread_depth_mm=thread_depth_mm,
        hole_depth_mm=hole_depth_mm,
        end_condition=end_condition,  # type: ignore[arg-type]
        instances=[Instance((0.0, 0.0, 0.0), direction, (face,))],
    )
    document = builder.screw_document("SHC", thread, length, serial=1)
    unit = [value / math.hypot(*direction) for value in direction]
    builder.screw(
        document,
        bearing_mm=tuple(value * bearing_z for value in unit),  # type: ignore[arg-type]
        direction=direction,
        component_id="cmp:0002",
        shank_face_mm=shank_face_mm,
    )
    package = builder.build().package
    [joint] = build_joint_map(package, fasteners=recognise_fasteners(package)).joints
    return package, joint


def checked(
    package: EvidencePackage, joint: Joint, mesh: trimesh.Trimesh | None = None
) -> dict[str, CheckResult]:
    placement = measure_placement(joint, package, mesh)
    assert placement is not None and joint.fastener is not None
    tapped = joint.tapped_instance
    assert tapped is not None
    material = next(
        document.material
        for document in package.documents
        if document.document_id == "doc:0002"
    )
    return by_check(
        check_placed_screw(joint.fastener.fastener, tapped.hole, placement, hole_material=material)
    )


# --- the protrusion ---------------------------------------------------------------------------


def test_the_protrusion_is_the_tip_below_the_entry() -> None:
    """A 16 mm screw bearing 10 mm above a blind tapped face that ends at 0: tip at -6."""
    package, joint = screw_joint()

    placement = measure_placement(joint, package, None)

    assert placement is not None
    assert placement.protrusion_mm == 6.0
    assert placement.missing == ()
    assert "shank face" in placement.protrusion_source


def test_engagement_is_min_of_protrusion_and_the_blind_thread_depth() -> None:
    results = checked(*screw_joint(length=16.0, thread_depth_mm=10.0))

    engagement = results[CHECK_ENGAGEMENT]
    assert engagement.calculation is not None
    assert engagement.calculation.result["engagement_mm"] == 6.0
    assert engagement.calculation.result["ratio"] == 1.2
    assert engagement.status == "demonstrated"
    assert engagement.severity == "high"


def test_a_long_enough_screw_passes_against_1_5_d() -> None:
    results = checked(*screw_joint(length=18.0, thread_depth_mm=10.0))

    engagement = results[CHECK_ENGAGEMENT]
    assert engagement.calculation is not None
    assert engagement.calculation.result["engagement_mm"] == 8.0
    assert engagement.status == "checked_within_scope"


def test_hole_depth_is_never_read_as_thread_depth() -> None:
    """A hole depth that would clear the joint changes nothing; the thread depth decides."""
    shallow = checked(*screw_joint(length=18.0, thread_depth_mm=6.0, hole_depth_mm=30.0))

    engagement = shallow[CHECK_ENGAGEMENT]
    assert engagement.calculation is not None
    assert engagement.calculation.result["engagement_mm"] == 6.0
    assert engagement.status == "demonstrated"
    assert "hole_depth" not in str(engagement.calculation.inputs)


def test_a_blind_hole_with_no_thread_depth_is_unresolved_naming_it() -> None:
    results = checked(*screw_joint(thread_depth_mm=None))

    for check in (CHECK_BOTTOMING, CHECK_ENGAGEMENT):
        assert results[check].status == "unresolved"
        assert "the usable thread depth of hole hol:0001" in results[check].observed
        assert "hole depth is never used" in results[check].observed


def test_an_unknown_end_condition_is_unresolved() -> None:
    package, joint = screw_joint()
    tapped = joint.reference_instance
    unknown = tapped.hole.model_copy(update={"end_condition": "unknown"})
    joint = _with_hole(joint, unknown)

    results = checked(package, joint)

    assert results[CHECK_ENGAGEMENT].status == "unresolved"
    assert "its end condition is unknown" in results[CHECK_ENGAGEMENT].observed
    assert results[CHECK_BOTTOMING].status == "unresolved"


def _with_hole(joint: Joint, hole: Hole) -> Joint:
    from dataclasses import replace

    instance = replace(joint.reference_instance, hole=hole)
    return replace(joint, instances=(instance,))


def test_the_through_tapped_length_is_the_face_labelled_derived() -> None:
    """An M3x4 bearing 4.331 above a 1.725 mm through-tapped sheet engages 1.394 mm."""
    package, joint = screw_joint(
        thread="M3-0.5",
        length=4.0,
        tapped="M3x0.5",
        end_condition="through",
        face=Face(2.5, 0.0, 1.725),
        thread_depth_mm=None,
        hole_depth_mm=None,
        bearing_z=4.331,
        shank_face_mm=3.0,
    )

    placement = measure_placement(joint, package, None)
    results = checked(package, joint)

    assert placement is not None
    assert placement.usable_thread == UsableThread(1.725, THROUGH_TAPPED_SOURCE)
    engagement = results[CHECK_ENGAGEMENT]
    assert engagement.calculation is not None
    assert engagement.calculation.result["engagement_mm"] == 1.394
    assert engagement.calculation.inputs["usable_thread_source"] == THROUGH_TAPPED_SOURCE
    assert results[CHECK_BOTTOMING].status == "checked_within_scope"
    assert "through hole" in results[CHECK_BOTTOMING].observed


def test_a_through_tapped_sheet_thinner_than_1_5_d_is_low_severity_with_its_thickness() -> None:
    package, joint = screw_joint(
        thread="M3-0.5",
        length=4.0,
        tapped="M3x0.5",
        end_condition="through",
        face=Face(2.5, 0.0, 1.725),
        thread_depth_mm=None,
        bearing_z=4.331,
        shank_face_mm=3.0,
    )

    engagement = checked(package, joint)[CHECK_ENGAGEMENT]

    assert (engagement.status, engagement.severity) == ("demonstrated", "low")
    assert engagement.calculation is not None
    assert engagement.calculation.result["sheet_thickness_mm"] == 1.725
    assert engagement.calculation.result["required_engagement_mm"] == 4.5
    assert "1.725 mm sheet" in engagement.observed


def test_a_thick_through_tapped_part_short_of_the_rule_keeps_the_normal_severity() -> None:
    """The part could take the rule; the screw is too short. Not the thin-sheet case."""
    package, joint = screw_joint(
        thread="M3-0.5",
        length=6.0,
        tapped="M3x0.5",
        end_condition="through",
        face=Face(2.5, 0.0, 10.0),
        thread_depth_mm=None,
        bearing_z=12.0,
        shank_face_mm=3.0,
    )

    engagement = checked(package, joint)[CHECK_ENGAGEMENT]

    assert engagement.calculation is not None
    assert engagement.calculation.result["engagement_mm"] == 4.0
    assert (engagement.status, engagement.severity) == ("demonstrated", "high")
    assert "sheet_thickness_mm" not in engagement.calculation.result


def test_a_blind_hole_short_of_the_rule_keeps_the_normal_severity() -> None:
    engagement = checked(*screw_joint(length=12.0, thread_depth_mm=10.0))[CHECK_ENGAGEMENT]

    assert (engagement.status, engagement.severity) == ("demonstrated", "high")


# --- bottoming at its boundary ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("length", "status"),
    [(20.0, "checked_within_scope"), (20.001, "demonstrated")],
)
def test_bottoming_at_its_boundary(length: float, status: str) -> None:
    """A 10 mm thread and a screw whose tip reaches exactly 10 mm below the entry clears."""
    results = checked(*screw_joint(length=length, thread_depth_mm=10.0))

    bottoming = results[CHECK_BOTTOMING]
    assert bottoming.status == status
    assert bottoming.calculation is not None
    assert bottoming.calculation.result["margin_mm"] == pytest.approx(20.0 - length, abs=1e-9)


# --- oblique axes, untrusted sizes, no extent -------------------------------------------------


def test_an_oblique_axis_is_unresolved_when_the_extent_comes_from_a_face() -> None:
    package, joint = screw_joint(direction=TILT)

    placement = measure_placement(joint, package, None)
    results = checked(package, joint)

    assert placement is not None and placement.protrusion_mm is None
    assert results[CHECK_ENGAGEMENT].status == "unresolved"
    assert "the axis is oblique; bounding-box extents are not used" in (
        results[CHECK_ENGAGEMENT].observed
    )


def test_an_oblique_mesh_extent_is_exact_and_the_entry_still_keeps_it_unresolved() -> None:
    """The screw's mesh extent is computed and exact on any axis; the thread entry is the
    tapped face's box, which overruns an oblique face (here by 1.8 mm, `r` times the sum of
    `|a_i| sqrt(1 - a_i^2)`), so the protrusion is not computed from it (`contracts/
    joint-map.md` section 2: engagement requires an aligned axis). Deviation from T044's
    wording, which expected a computed protrusion: that number would be 30 percent wrong."""
    from swreview.checks.fastener_identity import screw_extent

    package, joint = screw_joint(direction=TILT, shank_face_mm=None)
    bearing = tuple(value * 10.0 for value in TILT)
    mesh = cylinder_mesh(bearing, TILT, 5.0, -16.0, 0.0)

    extent = screw_extent(joint, package, mesh)
    placement = measure_placement(joint, package, mesh)

    assert extent is not None and extent.source == "mesh"
    assert (extent.low_mm, extent.high_mm) == (pytest.approx(-6.0), pytest.approx(10.0))
    assert placement is not None and placement.protrusion_mm is None
    assert "the screw's mesh extent is exact, but the thread entry" in placement.missing[0]


def test_a_screw_its_shank_contradicts_is_unresolved() -> None:
    """An M5 name over a 3.3 mm shank: the size is not leaned on (research R2.12)."""
    package, joint = screw_joint(shank_face_mm=3.3)

    results = checked(package, joint)

    engagement = results[CHECK_ENGAGEMENT]
    assert engagement.status == "unresolved"
    assert "the parsed size disagrees with the measured shank" in engagement.observed


def test_no_face_and_no_mesh_leaves_the_protrusion_unresolved() -> None:
    package, joint = screw_joint(shank_face_mm=None)

    results = checked(package, joint, mesh=None)

    assert results[CHECK_ENGAGEMENT].status == "unresolved"
    assert "no face and no exported mesh" in results[CHECK_ENGAGEMENT].observed


def test_a_screw_that_does_not_reach_the_thread_is_unresolved() -> None:
    package, joint = screw_joint(length=16.0, bearing_z=40.0, shank_face_mm=None)
    mesh = cylinder_mesh((0.0, 0.0, 40.0), Z, 5.0, -16.0, 0.0)

    placement = measure_placement(joint, package, mesh)

    assert placement is not None and placement.protrusion_mm is None
    assert "ends 24.0 mm short of the tapped face" in placement.missing[0]


# --- thread match and the derivation ---------------------------------------------------------


def test_thread_match_is_the_existing_rule_byte_for_byte() -> None:
    package, joint = screw_joint(thread="M4-0.7")
    placement = measure_placement(joint, package, None)
    assert placement is not None and joint.fastener is not None
    fastener: Fastener = joint.fastener.fastener
    hole = joint.reference_instance.hole

    placed = by_check(check_placed_screw(fastener, hole, placement))[CHECK_THREAD_MATCH]
    stack = _Stack(inputs={"fastener_id": fastener.id, "hole_id": hole.id})
    stack.sources = [item for item in placed.inputs]  # type: ignore[misc]
    direct = _thread_match(fastener, hole, stack)

    assert placed.status == "demonstrated"
    assert (placed.observed, placed.requirement, placed.recommended_action) == (
        direct.observed,
        direct.requirement,
        direct.recommended_action,
    )
    assert placed.calculation is not None and direct.calculation is not None
    assert placed.calculation.result == direct.calculation.result


def test_every_result_carries_the_placement_derivation() -> None:
    results = checked(*screw_joint(length=18.0))

    for check in (CHECK_BOTTOMING, CHECK_ENGAGEMENT):
        calculation = results[check].calculation
        assert calculation is not None
        assumptions = " ".join(calculation.assumptions)
        assert "protrusion = thread entry - screw tip, along the tapped axis" in assumptions
        assert "usable thread depth = Hole.thread_depth of hol:0001" in assumptions
        assert "screw length - clamped stack" not in assumptions
    assert results[CHECK_BOTTOMING].calculation is not None
    assert "the screw is where the assembly places it" in (
        results[CHECK_BOTTOMING].calculation.assumptions
    )


def test_head_clearance_without_an_envelope_is_unresolved() -> None:
    results = checked(*screw_joint())

    assert results[CHECK_HEAD_CLEARANCE].status == "unresolved"


def test_a_placement_must_say_why_a_value_is_missing() -> None:
    with pytest.raises(ValueError, match="protrusion"):
        Placement(protrusion_mm=None, protrusion_source="", usable_thread=None)
    with pytest.raises(ValueError, match="usable thread"):
        Placement(protrusion_mm=1.0, protrusion_source="x", usable_thread=None)
