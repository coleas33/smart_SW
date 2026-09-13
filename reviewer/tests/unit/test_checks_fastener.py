"""Unit tests for the fastener joint checks (T083).

These pin FR-023 and FR-024 and the acceptance scenarios of US5: a bottoming margin and
an engagement ratio computed from the screw length, the clamped stack, the washers and
the usable thread depth; an unknown input that stays unknown; a thread mismatch reported
as demonstrated; and a joint kind the pilot does not support reported as out of scope,
never as passed.
"""

from __future__ import annotations

import pytest
from pint import DimensionalityError

from swreview.checks.engagement_rules import load_rules
from swreview.checks.fastener import (
    FUNCTION_VERSION,
    ClampedLayer,
    check_fastener_joint,
    nominal_diameter,
    parse_thread,
)
from swreview.checks.result import CheckResult
from swreview.ir.models import Angle, Axis, Fastener, Hole, Quantity, Vec3
from tests.support.packages import persist_ref

AXIS = Axis(origin=Vec3(x=0.0, y=0.0, z=0.01), direction=Vec3(x=0.0, y=0.0, z=1.0))


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


M6X20 = mm(20.0)
THREAD_DEPTH_12 = mm(12.0)


def screw(
    *,
    kind: str = "screw",
    thread: str | None = "M6x1.0",
    length: Quantity | None = M6X20,
) -> Fastener:
    return Fastener(
        id="fst:1",
        persist_ref=persist_ref("fst:1"),
        persist_ref_scope="doc:1",
        component_id="cmp:0002",
        kind=kind,  # type: ignore[arg-type]
        identity_source="toolbox",
        thread_designation=thread,
        length=length,
        head_type="socket head cap",
        head_diameter=mm(10.0),
        head_height=mm(6.0),
        drive="hex",
        axis=AXIS,
        material="Alloy Steel",
    )


def tapped_hole(
    *,
    thread: str | None = "M6x1.0",
    thread_depth: Quantity | None = THREAD_DEPTH_12,
    end_condition: str = "blind",
) -> Hole:
    return Hole(
        id="hole:1",
        persist_ref=persist_ref("hole:1"),
        persist_ref_scope="doc:2",
        component_id="cmp:0001",
        feature_name="M6 Tapped Hole1",
        hole_type="tapped",
        standard="ISO",
        size="M6",
        thread_designation=thread,
        thread_depth=thread_depth,
        hole_depth=mm(15.0),
        end_condition=end_condition,  # type: ignore[arg-type]
        diameter=mm(5.0),
        axis=AXIS,
        face_ids=[],
    )


def layer(thickness: Quantity | None, component_id: str = "cmp:0003") -> ClampedLayer:
    return ClampedLayer(component_id=component_id, thickness=thickness, material="6061-T6")


def by_check(results: list[CheckResult]) -> dict[str, CheckResult]:
    assert len({result.check for result in results}) == len(results), "duplicate check name"
    return {result.check: result for result in results}


# --- thread designation parsing ---------------------------------------------------


@pytest.mark.parametrize(
    ("designation", "expected_mm"),
    [
        ("M6x1.0", 6.0),
        ("M6 x 1", 6.0),
        ("M6", 6.0),
        ("M3.5x0.6", 3.5),
        ("M10X1.5", 10.0),
        ("1/4-20", 6.35),
        ("1/4-20 UNC", 6.35),
        ("#10-32", 4.826),
        ("0.190-32", 4.826),
    ],
)
def test_nominal_diameter_is_parsed_from_the_designation(
    designation: str, expected_mm: float
) -> None:
    diameter = nominal_diameter(designation)

    assert diameter is not None
    assert diameter.unit == "mm"
    assert diameter.value == pytest.approx(expected_mm, abs=1e-3)


def test_an_unrecognised_designation_has_no_nominal_diameter() -> None:
    assert nominal_diameter("NPT 1/8") is None
    assert nominal_diameter("") is None


def test_the_same_thread_written_two_ways_parses_to_one_canonical_form() -> None:
    assert parse_thread("M6x1.0").normalized == parse_thread("m6 X 1").normalized


def test_a_thread_without_a_pitch_is_not_the_same_text_as_one_with_a_pitch() -> None:
    assert parse_thread("M6").normalized != parse_thread("M6x1.0").normalized


# --- bottoming and engagement -----------------------------------------------------


def test_bottoming_margin_comes_from_length_stack_washer_and_thread_depth() -> None:
    # 20 - 1.5 - 1.6 = 16.9 mm into the hole; 12 - 16.9 = -4.9 mm of margin.
    results = by_check(
        check_fastener_joint(
            screw(length=mm(20.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(1.5))],
            washers=[mm(1.6)],
            hole_material="6061-T6",
        )
    )
    bottoming = results["fastener.bottoming"]

    assert bottoming.status == "demonstrated"
    assert bottoming.severity == "high"
    assert bottoming.calculation is not None
    assert bottoming.calculation.model == "fastener.bottoming"
    assert bottoming.calculation.result["protrusion_mm"] == pytest.approx(16.9, abs=1e-9)
    assert bottoming.calculation.result["margin_mm"] == pytest.approx(-4.9, abs=1e-9)
    assert bottoming.calculation.units_out == "mm"
    assert bottoming.calculation.function_version == FUNCTION_VERSION


def test_a_screw_that_clamps_before_it_bottoms_is_checked_within_scope() -> None:
    results = by_check(
        check_fastener_joint(
            screw(length=mm(12.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="6061-T6",
        )
    )
    bottoming = results["fastener.bottoming"]

    assert bottoming.status == "checked_within_scope"
    assert bottoming.calculation.result["margin_mm"] == pytest.approx(3.0, abs=1e-9)


def test_engagement_ratio_is_engagement_over_nominal_diameter() -> None:
    # protrusion 9 mm, thread depth 12 mm -> engagement 9 mm; 9 / 6 = 1.5 x d.
    results = by_check(
        check_fastener_joint(
            screw(length=mm(12.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="6061-T6",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.status == "checked_within_scope"
    assert engagement.calculation.result["engagement_mm"] == pytest.approx(9.0, abs=1e-9)
    assert engagement.calculation.result["ratio"] == pytest.approx(1.5, abs=1e-9)
    assert engagement.calculation.result["required_ratio"] == pytest.approx(1.5, abs=1e-9)


def test_engagement_is_capped_by_the_usable_thread_depth() -> None:
    """A screw that protrudes past the threads gains no engagement from the extra length."""
    results = by_check(
        check_fastener_joint(
            screw(length=mm(20.0)),
            tapped_hole(thread_depth=mm(8.0)),
            [layer(mm(1.5))],
            hole_material="AISI 1018 Steel",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.calculation.result["engagement_mm"] == pytest.approx(8.0, abs=1e-9)
    # The ratio is rounded like every other reported number (`result.PLACES`).
    assert engagement.calculation.result["ratio"] == pytest.approx(8.0 / 6.0, abs=1e-6)


def test_engagement_below_the_material_rule_is_demonstrated() -> None:
    # protrusion 6 mm in aluminium: 6 / 6 = 1.0 x d against a 1.5 x d rule.
    results = by_check(
        check_fastener_joint(
            screw(length=mm(9.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="6061-T6",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.status == "demonstrated"
    assert engagement.severity == "high"
    assert engagement.calculation.result["ratio"] == pytest.approx(1.0, abs=1e-9)


def test_the_engagement_rule_is_chosen_by_the_hole_material_and_cited() -> None:
    aluminium = by_check(
        check_fastener_joint(
            screw(length=mm(9.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="6061-T6",
        )
    )["fastener.engagement"]
    steel = by_check(
        check_fastener_joint(
            screw(length=mm(9.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="AISI 1018 Steel",
        )
    )["fastener.engagement"]

    assert aluminium.status == "demonstrated"
    assert steel.status == "checked_within_scope"

    rules = load_rules()
    assert rules.for_material("6061-T6").source in " ".join(aluminium.calculation.assumptions)
    assert aluminium.calculation.inputs["material_class"] == "aluminum"
    assert steel.calculation.inputs["material_class"] == "steel"
    assert rules.for_material("AISI 1018 Steel").source in " ".join(steel.calculation.assumptions)


def test_an_unknown_hole_material_leaves_engagement_unresolved() -> None:
    results = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="unobtainium",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.status == "unresolved"
    assert any("material" in limit for limit in engagement.coverage_limits)
    # The measured engagement is still reported; only the verdict is withheld.
    assert engagement.calculation.result["engagement_mm"] == pytest.approx(12.0, abs=1e-9)


def test_a_missing_hole_material_leaves_engagement_unresolved() -> None:
    engagement = by_check(
        check_fastener_joint(screw(), tapped_hole(), [layer(mm(1.5))], hole_material=None)
    )["fastener.engagement"]

    assert engagement.status == "unresolved"


# --- unknown inputs stay unknown --------------------------------------------------


def test_an_unknown_thread_depth_leaves_bottoming_and_engagement_unresolved() -> None:
    results = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(thread_depth=None),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )

    for name in ("fastener.bottoming", "fastener.engagement"):
        result = results[name]
        assert result.status == "unresolved", name
        assert any("usable thread depth" in limit for limit in result.coverage_limits), name


def test_a_missing_clamped_thickness_is_unresolved_and_names_the_component() -> None:
    results = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5), "cmp:0003"), layer(None, "cmp:0004")],
            hole_material="6061-T6",
        )
    )
    bottoming = results["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("cmp:0004" in limit for limit in bottoming.coverage_limits)
    assert not any("cmp:0003" in limit for limit in bottoming.coverage_limits)


def test_an_empty_clamped_stack_is_unresolved() -> None:
    """Zero clamped layers is not the same as a zero-thickness stack."""
    bottoming = by_check(
        check_fastener_joint(screw(), tapped_hole(), [], hole_material="6061-T6")
    )["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("clamped" in limit for limit in bottoming.coverage_limits)


def test_an_unknown_screw_length_is_unresolved() -> None:
    bottoming = by_check(
        check_fastener_joint(
            screw(length=None), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6"
        )
    )["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("length" in limit for limit in bottoming.coverage_limits)


def test_an_unknown_nominal_diameter_leaves_engagement_unresolved() -> None:
    engagement = by_check(
        check_fastener_joint(
            screw(thread="NPT 1/8"),
            tapped_hole(thread="NPT 1/8"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.engagement"]

    assert engagement.status == "unresolved"
    assert any("nominal" in limit for limit in engagement.coverage_limits)


# --- through holes ----------------------------------------------------------------


def test_a_through_hole_cannot_bottom_and_is_checked_within_scope_with_a_note() -> None:
    bottoming = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(end_condition="through"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.bottoming"]

    assert bottoming.status == "checked_within_scope"
    assert any("through" in limit for limit in bottoming.coverage_limits)


def test_an_unknown_end_condition_leaves_bottoming_unresolved() -> None:
    bottoming = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(end_condition="unknown"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("end condition" in limit for limit in bottoming.coverage_limits)


# --- thread match -----------------------------------------------------------------


def test_a_thread_mismatch_is_demonstrated_with_both_specifications() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="M5x0.8"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "demonstrated"
    assert match.severity == "high"
    assert "M6x1.0" in match.observed
    assert "M5x0.8" in match.observed


def test_a_pitch_mismatch_at_the_same_diameter_is_demonstrated() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="M6x0.75"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "demonstrated"


def test_a_matching_thread_is_checked_within_scope() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="m6 X 1"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "checked_within_scope"


def test_a_pitch_known_on_only_one_side_does_not_manufacture_a_mismatch() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="M6"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "checked_within_scope"


def test_a_missing_thread_designation_is_unresolved() -> None:
    for fastener_thread, hole_thread, expected in (
        (None, "M6x1.0", "fastener"),
        ("M6x1.0", None, "hole"),
    ):
        match = by_check(
            check_fastener_joint(
                screw(thread=fastener_thread),
                tapped_hole(thread=hole_thread),
                [layer(mm(1.5))],
                hole_material="6061-T6",
            )
        )["fastener.thread_match"]

        assert match.status == "unresolved"
        assert any(expected in limit for limit in match.coverage_limits)


def test_two_unrecognised_designations_are_unresolved_not_a_mismatch() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="NPT 1/8"),
            tapped_hole(thread="BSPT 1/8"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "unresolved"


# --- head clearance ---------------------------------------------------------------


def test_head_clearance_is_unresolved_without_an_envelope_raycast() -> None:
    clearance = by_check(
        check_fastener_joint(screw(), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6")
    )["fastener.head_clearance"]

    assert clearance.status == "unresolved"
    assert any("envelope" in limit for limit in clearance.coverage_limits)


def test_head_clearance_is_demonstrated_when_the_envelope_raycast_hits() -> None:
    from swreview.geometry.envelope import EnvelopeHit, EnvelopeResult

    envelope = EnvelopeResult(
        hits=[EnvelopeHit(component_id="cmp:0009", first_hit_distance_m=0.010)],
        unresolved=[],
    )

    clearance = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="6061-T6",
            envelope=envelope,
        )
    )["fastener.head_clearance"]

    assert clearance.status == "demonstrated"
    assert "cmp:0009" in clearance.observed


def test_head_clearance_is_checked_within_scope_when_the_envelope_is_clear() -> None:
    from swreview.geometry.envelope import EnvelopeResult

    clearance = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="6061-T6",
            envelope=EnvelopeResult(hits=[], unresolved=[]),
        )
    )["fastener.head_clearance"]

    assert clearance.status == "checked_within_scope"


def test_head_clearance_stays_unresolved_when_a_mesh_was_missing() -> None:
    from swreview.geometry.envelope import EnvelopeResult

    clearance = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="6061-T6",
            envelope=EnvelopeResult(hits=[], unresolved=["missing mesh for component cmp:0009"]),
        )
    )["fastener.head_clearance"]

    assert clearance.status == "unresolved"
    assert any("cmp:0009" in limit for limit in clearance.coverage_limits)


# --- unsupported joint kinds ------------------------------------------------------


@pytest.mark.parametrize("kind", ["pin", "other", "nut", "washer"])
def test_an_unsupported_joint_kind_is_one_out_of_scope_result(kind: str) -> None:
    results = check_fastener_joint(
        screw(kind=kind), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6"
    )

    assert len(results) == 1
    assert results[0].check == "fastener.unsupported"
    assert results[0].status == "unresolved"
    assert results[0].coverage_limits == [f"out_of_scope: {kind}"]


def test_a_bolt_is_a_supported_joint_kind() -> None:
    results = check_fastener_joint(
        screw(kind="bolt"), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6"
    )

    assert "fastener.unsupported" not in by_check(results)


# --- units ------------------------------------------------------------------------


def test_inch_inputs_are_converted_and_both_values_are_recorded() -> None:
    results = by_check(
        check_fastener_joint(
            screw(thread="1/4-20", length=Quantity(value=0.75, unit="in")),
            tapped_hole(thread="1/4-20", thread_depth=Quantity(value=0.5, unit="in")),
            [layer(Quantity(value=0.125, unit="in"))],
            hole_material="AISI 1018 Steel",
        )
    )
    bottoming = results["fastener.bottoming"]

    # 0.75 in = 19.05 mm, 0.125 in = 3.175 mm -> protrusion 15.875 mm;
    # thread depth 0.5 in = 12.7 mm -> margin -3.175 mm.
    assert bottoming.status == "demonstrated"
    assert bottoming.calculation.result["margin_mm"] == pytest.approx(-3.175, abs=1e-9)
    assert bottoming.calculation.inputs["fastener_length"] == Quantity(value=0.75, unit="in")
    assert bottoming.calculation.inputs["fastener_length_mm"].value == pytest.approx(19.05)


def test_an_angle_where_a_length_belongs_raises_a_dimensionality_error() -> None:
    with pytest.raises(DimensionalityError):
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [ClampedLayer(component_id="cmp:0003", thickness=Angle(value=5.0, unit="deg"))],
            hole_material="6061-T6",
        )
