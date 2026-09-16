"""The geometry gate's tier-1 case table (T098, T100).

`quickstart.md` Scenario 3 is the table and `research.md` R4.7 is the reasoning:
`remodel/geometry.py::evaluate(before, after, tolerances)` has no COM in its signature, so
every case here is two `GeometryReading` records and a named profile. The verdict is
tri-state (`pass`, `fail`, `unresolved`) from day one, **never a Boolean and never
inferred from a successful rebuild**, so stage 2 adds a tier rather than changing a type.

Tier 1 is mass properties and is the whole stage-1 gate under `IDENTITY`, where nothing
geometric is supposed to change. The tier-2 rows at the bottom of this file drive the
residual branch through its optional argument: the **decision** is testable now against
fixture readings, while the **measurement** (`IBody2.Operations2`) is stage 2.

Two rules this table exists to pin, because getting either wrong would make the product
untrustworthy rather than merely wrong:

- a measurement that did not happen is `unresolved`, never `pass` and never `fail`: a
  mass-properties status other than OK, a `Recalculate()` that returned false, a baseline
  volume of zero (which is guarded, not divided by), a baseline with two solid bodies, an
  unreadable count, and tier 1 failing while tier 2 passes (a bug in the tolerances, not a
  geometry verdict);
- mass is not geometry. `Mass = Volume x Density`, so a mass-only difference reports
  `material_changed` and never a geometry failure.
"""

from __future__ import annotations

from typing import Any

import pytest

from swreview.remodel.geometry import (
    BODY_OPERATION_BOOLEAN_FAIL,
    BODY_OPERATION_EMPTY_BODY,
    BODY_OPERATION_NO_ERROR,
    BODY_OPERATION_NO_INTERSECT,
    BODY_OPERATION_NON_API_BODY,
    BODY_OPERATION_PARTIAL_COINCIDENCE,
    BODY_OPERATION_UNKNOWN_ERROR,
    COVERAGE_LIMITS,
    MASS_PROPERTIES_STATUS_OK,
    Delta,
    GateResult,
    GeometryReading,
    ResidualReading,
    evaluate,
)
from swreview.remodel.tolerances import (
    EQUIVALENCE,
    IDENTITY,
    RESIDUAL_MIN_DIMENSION_M,
    RESIDUAL_VOLUME_FLOOR_M3,
    RESIDUAL_VOLUME_REL,
)

SOURCE_SHA = "9f" * 32

BASELINE: dict[str, Any] = {
    "at": "2026-09-16T14:22:01Z",
    "source_sha256": SOURCE_SHA,
    "subject": "copy_at_open",
    "status": MASS_PROPERTIES_STATUS_OK,
    "accuracy_level": 2,
    "recalculated": True,
    "volume_m3": 1.0e-3,
    "surface_area_m2": 6.0e-2,
    "center_of_mass_m": (0.05, 0.025, 0.01),
    "principal_moments": (1.1e-5, 2.2e-5, 3.3e-5),
    "mass_kg": 2.7,
    "density": 2700.0,
    "material_name": "1060 Alloy",
    "solid_body_count": 1,
    "sheet_body_count": 0,
    "face_count": 214,
    "edge_count": 642,
    "residual": None,
}


def before(**overrides: Any) -> GeometryReading:
    return GeometryReading(**{**BASELINE, **overrides})


def after(**overrides: Any) -> GeometryReading:
    return GeometryReading(**{**BASELINE, "subject": "copy_at_end", **overrides})


def delta_for(result: GateResult, quantity: str) -> Delta:
    matches = [d for d in result.deltas if d.quantity == quantity]
    assert len(matches) == 1, f"expected exactly one {quantity} delta, got {len(matches)}"
    return matches[0]


def assert_names_every_undetectable_difference(limits: tuple[str, ...]) -> None:
    """The coverage statement `data-model.md` section 3.4 requires on **every** run.

    One helper rather than a copy per case: the five differences tier 1 is blind to plus
    the difference the baseline rollback and rebuild themselves produce.
    """
    for limit in COVERAGE_LIMITS:
        assert limit in limits
    printed = " | ".join(limits)
    assert "reflection" in printed
    assert "rigid rotation about a symmetry axis" in printed
    assert "compensating add and remove" in printed
    assert "occupying no volume" in printed
    assert "wire-body" in printed
    assert "baseline" in printed and "rebuild" in printed


def scaled(reading: GeometryReading, s: float) -> dict[str, Any]:
    """The mass properties of the same shape scaled uniformly by `s` about the origin."""
    assert reading.volume_m3 is not None
    assert reading.surface_area_m2 is not None
    assert reading.center_of_mass_m is not None
    assert reading.principal_moments is not None
    return {
        "volume_m3": reading.volume_m3 * s**3,
        "surface_area_m2": reading.surface_area_m2 * s**2,
        "center_of_mass_m": tuple(c * s for c in reading.center_of_mass_m),
        "principal_moments": tuple(m * s**5 for m in reading.principal_moments),
    }


def mirrored(reading: GeometryReading, axis: int) -> dict[str, Any]:
    """The mass properties of the same part reflected in the plane through its centre of
    mass normal to `axis`.

    Computed from the transform rather than copied from the baseline, so the case below
    fails if any invariant it rests on stops holding. A reflection is an isometry: it
    preserves volume, surface area and the three principal moments, and a plane through
    the centre of mass sends that point to itself, so every quantity tier 1 reads comes
    back identical. The moments come back reversed because a reflection may relabel the
    principal axes, and sorting them is part of the comparison.
    """
    assert reading.center_of_mass_m is not None
    assert reading.principal_moments is not None
    plane = reading.center_of_mass_m[axis]
    return {
        "volume_m3": reading.volume_m3,
        "surface_area_m2": reading.surface_area_m2,
        "center_of_mass_m": tuple(
            2.0 * plane - c if i == axis else c for i, c in enumerate(reading.center_of_mass_m)
        ),
        "principal_moments": tuple(reversed(reading.principal_moments)),
        "solid_body_count": reading.solid_body_count,
        "face_count": reading.face_count,
        "edge_count": reading.edge_count,
    }


# --------------------------------------------------------------------------------------
# The type itself


def test_the_verdict_is_tri_state_and_never_a_boolean() -> None:
    result = evaluate(before(), after(), IDENTITY)
    assert result.verdict in {"pass", "fail", "unresolved"}
    assert not isinstance(result.verdict, bool)
    assert result.profile == "IDENTITY"
    assert result.tier_2 is None, "tier 2 does not run in v1 unless a residual is supplied"


def test_every_run_including_a_passing_one_states_what_the_gate_cannot_detect() -> None:
    result = evaluate(before(), after(), IDENTITY)
    assert result.verdict == "pass"
    assert_names_every_undetectable_difference(result.coverage_limits)


def test_surface_bodies_are_reported_uncovered_rather_than_passed() -> None:
    result = evaluate(before(sheet_body_count=2), after(sheet_body_count=2), IDENTITY)
    printed = " | ".join(result.coverage_limits)
    assert "surface bodies are present" in printed
    assert "uncovered" in printed


# --------------------------------------------------------------------------------------
# Tier 1


def test_identical() -> None:
    result = evaluate(before(), after(), IDENTITY)
    assert result.verdict == "pass"
    assert result.tier_1.ran is True
    assert result.tier_1.verdict == "pass"
    assert result.diagnosis is None
    assert result.material_changed is False
    assert delta_for(result, "volume_m3").within is True
    assert delta_for(result, "volume_m3").absolute == 0.0


def test_delta_volume_just_inside() -> None:
    inside = BASELINE["volume_m3"] * (1.0 + IDENTITY.volume_rel / 2.0)
    result = evaluate(before(), after(volume_m3=inside), IDENTITY)
    assert result.verdict == "pass"
    volume = delta_for(result, "volume_m3")
    assert volume.within is True
    assert volume.relative is not None and volume.relative < IDENTITY.volume_rel
    assert volume.bound == IDENTITY.volume_rel


def test_delta_volume_just_outside() -> None:
    outside = BASELINE["volume_m3"] * (1.0 + IDENTITY.volume_rel * 2.0)
    result = evaluate(before(), after(volume_m3=outside), IDENTITY)
    assert result.verdict == "fail"
    assert result.tier_1.verdict == "fail"
    volume = delta_for(result, "volume_m3")
    assert volume.within is False
    assert volume.relative is not None and volume.relative > IDENTITY.volume_rel
    assert result.diagnosis is not None
    assert "volume_m3" in result.diagnosis, "the report names which quantity moved"
    assert f"{volume.relative:.3g}" in result.diagnosis


def test_a_bound_is_relative_and_not_absolute_at_any_scale() -> None:
    """The same relative delta decides the same way on a 1 m3 part and a 1 mm3 one."""
    for volume in (1.0, 1.0e-9):
        inside = evaluate(
            before(volume_m3=volume),
            after(volume_m3=volume * (1.0 + IDENTITY.volume_rel / 2.0)),
            IDENTITY,
        )
        outside = evaluate(
            before(volume_m3=volume),
            after(volume_m3=volume * (1.0 + IDENTITY.volume_rel * 2.0)),
            IDENTITY,
        )
        assert inside.verdict == "pass", volume
        assert outside.verdict == "fail", volume


def test_translated_0_1_mm() -> None:
    origin = BASELINE["center_of_mass_m"]
    moved = tuple(c + d for c, d in zip(origin, (1e-4, 0.0, 0.0), strict=True))
    result = evaluate(before(), after(center_of_mass_m=moved), IDENTITY)
    assert result.verdict == "fail"
    com = delta_for(result, "center_of_mass_m")
    assert com.within is False
    assert com.absolute == pytest.approx(1e-4)
    assert result.diagnosis is not None and "center_of_mass_m" in result.diagnosis


def test_uniformly_scaled_1_0001() -> None:
    result = evaluate(before(), after(**scaled(before(), 1.0001)), IDENTITY)
    assert result.verdict == "fail"
    assert delta_for(result, "volume_m3").within is False
    assert delta_for(result, "surface_area_m2").within is False
    assert result.diagnosis is not None
    assert "1.0001" in result.diagnosis, "the report names the scale"


def test_principal_moments_permuted() -> None:
    """Sorting ascending is part of the comparison, not a fix-up."""
    permuted = (3.3e-5, 1.1e-5, 2.2e-5)
    result = evaluate(before(), after(principal_moments=permuted), IDENTITY)
    assert result.verdict == "pass"
    assert all(delta_for(result, f"principal_moment_{i}").within is True for i in range(3))


def test_principal_moments_that_really_moved_still_fail_after_sorting() -> None:
    result = evaluate(before(), after(principal_moments=(1.1e-5, 2.2e-5, 3.4e-5)), IDENTITY)
    assert result.verdict == "fail"
    assert delta_for(result, "principal_moment_2").within is False


def test_zero_volume_baseline() -> None:
    """Unresolved, and explicitly not a divide-by-zero."""
    result = evaluate(before(volume_m3=0.0), after(volume_m3=0.0), IDENTITY)
    assert result.verdict == "unresolved"
    assert result.tier_1.ran is False
    assert result.tier_1.reason is not None and "zero" in result.tier_1.reason
    assert delta_for(result, "volume_m3").relative is None
    assert delta_for(result, "volume_m3").within is None


def test_baseline_body_count_2() -> None:
    result = evaluate(before(solid_body_count=2), after(solid_body_count=2), IDENTITY)
    assert result.verdict == "unresolved"
    assert result.tier_1.reason is not None
    assert "solid bodies" in result.tier_1.reason
    assert "scope gate" in result.tier_1.reason


def test_a_solid_body_count_that_changed_is_a_failure_not_an_unresolved() -> None:
    result = evaluate(before(), after(solid_body_count=2), IDENTITY)
    assert result.verdict == "fail"
    assert delta_for(result, "solid_body_count").within is False


def test_mass_properties_status_not_ok() -> None:
    """Measurement failed; this is not 'geometry changed'."""
    result = evaluate(before(), after(status=3), IDENTITY)
    assert result.verdict == "unresolved"
    assert result.tier_1.ran is False
    assert result.tier_1.reason is not None and "status" in result.tier_1.reason
    assert "3" in result.tier_1.reason


def test_a_recalculate_that_returned_false_is_unresolved() -> None:
    result = evaluate(before(recalculated=False), after(), IDENTITY)
    assert result.verdict == "unresolved"
    assert result.tier_1.reason is not None and "Recalculate" in result.tier_1.reason


def test_mass_only_delta_reports_material_changed_and_never_geometry_changed() -> None:
    result = evaluate(before(), after(mass_kg=3.1, density=3100.0), IDENTITY)
    assert result.verdict == "pass"
    assert result.material_changed is True
    assert result.diagnosis is None
    assert delta_for(result, "volume_m3").within is True
    assert delta_for(result, "mass_kg").within is False
    assert delta_for(result, "mass_kg").gates is False


def test_a_changed_material_name_is_material_changed_on_its_own() -> None:
    result = evaluate(before(), after(material_name="6061 Alloy"), IDENTITY)
    assert result.verdict == "pass"
    assert result.material_changed is True


def test_an_unreadable_material_is_reported_uncompared_rather_than_unchanged() -> None:
    result = evaluate(before(material_name=None), after(material_name=None), IDENTITY)
    assert result.verdict == "pass"
    assert result.material_changed is False
    assert any("material name" in limit for limit in result.coverage_limits)


def test_face_count_differs_fails_under_identity() -> None:
    result = evaluate(before(), after(face_count=215), IDENTITY)
    assert result.verdict == "fail"
    assert delta_for(result, "face_count").within is False
    assert delta_for(result, "face_count").bound == "exact"


def test_face_count_differs_is_a_warning_under_equivalence() -> None:
    """`EQUIVALENCE` is stage 2's profile and is selected by no v1 code path."""
    result = evaluate(before(), after(face_count=215), EQUIVALENCE)
    assert result.verdict == "pass"
    face = delta_for(result, "face_count")
    assert face.within is False
    assert face.bound == "warn"
    assert face.gates is False


def test_an_unreadable_count_is_unresolved_rather_than_assumed_equal() -> None:
    result = evaluate(before(), after(face_count=None), IDENTITY)
    assert result.verdict == "unresolved"
    assert delta_for(result, "face_count").within is None


def test_edge_count_is_exact_under_every_profile() -> None:
    """`edge_count` has no row in the profile table of `data-model.md` section 3.2, so it
    is compared exactly and never borrows `face_count`'s warn rule."""
    for profile in (IDENTITY, EQUIVALENCE):
        result = evaluate(before(), after(edge_count=643), profile)
        assert result.verdict == "fail", profile.name
        edges = delta_for(result, "edge_count")
        assert edges.within is False
        assert edges.bound == "exact"
        assert edges.gates is True


def test_the_gate_follows_the_profiles_body_count_rule() -> None:
    """The bound published in the artifact is the bound that decided.

    `solid_body_count` is gated by `tolerances.body_count`, read off the profile rather
    than hardcoded beside it: a profile whose rule said something else would decide
    differently, and this is the case that would notice.
    """
    warned = IDENTITY.model_copy(update={"body_count": "warn"})
    result = evaluate(before(), after(solid_body_count=2), warned)
    assert result.verdict == "pass"
    bodies = delta_for(result, "solid_body_count")
    assert bodies.within is False
    assert bodies.bound == "warn"
    assert bodies.gates is False


def test_mirrored_tier1_only() -> None:
    """Tier 1 alone passes a reflection, and the result says so in its coverage.

    The after-reading is the reflection applied to the baseline, not a copy of it, so this
    case fails the moment one of the invariants it rests on stops holding.
    """
    baseline = before()
    assert baseline.center_of_mass_m is not None
    assert baseline.principal_moments is not None
    reflected = mirrored(baseline, axis=2)

    assert reflected["volume_m3"] == baseline.volume_m3, "an isometry preserves volume"
    assert reflected["surface_area_m2"] == baseline.surface_area_m2, "and surface area"
    assert reflected["center_of_mass_m"] == pytest.approx(
        baseline.center_of_mass_m
    ), "the mirror plane passes through the centre of mass, which it therefore fixes"
    assert sorted(reflected["principal_moments"]) == sorted(baseline.principal_moments)
    assert reflected["principal_moments"] != baseline.principal_moments, "relabelled axes"
    assert reflected["solid_body_count"] == baseline.solid_body_count
    assert reflected["face_count"] == baseline.face_count
    assert reflected["edge_count"] == baseline.edge_count

    result = evaluate(baseline, after(**reflected), IDENTITY)
    assert result.verdict == "pass"
    assert result.tier_1.ran is True
    assert result.tier_1.verdict == "pass"
    assert result.tier_2 is None, "tier 2 is the only tier that can see a reflection"
    assert_names_every_undetectable_difference(result.coverage_limits)


# --------------------------------------------------------------------------------------
# Tier 2: the residual branch, behind its optional argument (T100)


def residual(**overrides: Any) -> ResidualReading:
    base: dict[str, Any] = {
        "error_code": BODY_OPERATION_NO_ERROR,
        "body_count": 0,
        "total_volume_m3": 0.0,
        "per_body_bbox": (),
    }
    return ResidualReading(**{**base, **overrides})


def test_the_residual_branch_is_optional_and_absent_in_v1() -> None:
    assert evaluate(before(), after(), IDENTITY).tier_2 is None
    supplied = evaluate(before(), after(), IDENTITY, residual=residual())
    assert supplied.tier_2 is not None
    assert supplied.tier_2.ran is True
    assert supplied.verdict == "pass"


def test_mirrored_with_residual() -> None:
    """Tier 1 passes, the residual is the whole part, the verdict is a named reflection."""
    full = BASELINE["volume_m3"]
    result = evaluate(
        before(),
        after(**mirrored(before(), axis=2)),
        IDENTITY,
        residual=residual(body_count=1, total_volume_m3=full, per_body_bbox=((0.1, 0.05, 0.2),)),
    )
    assert result.tier_1.verdict == "pass"
    assert result.tier_2 is not None and result.tier_2.verdict == "fail"
    assert result.verdict == "fail"
    assert result.diagnosis is not None
    assert "reflection" in result.diagnosis
    assert "full baseline volume" in result.diagnosis


def test_one_sliver_residual() -> None:
    """10 mm by 10 mm by 0.2 um: inspected and recorded, not a failure."""
    sliver_volume = 0.01 * 0.01 * 2e-7
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(
            error_code=BODY_OPERATION_PARTIAL_COINCIDENCE,
            body_count=1,
            total_volume_m3=sliver_volume,
            per_body_bbox=((0.01, 0.01, 2e-7),),
        ),
    )
    assert result.verdict == "pass"
    assert result.tier_2 is not None and result.tier_2.verdict == "pass"
    assert result.tier_2.reason is not None
    assert f"{sliver_volume:.3g}" in result.tier_2.reason, "the residual is recorded, not ignored"
    assert "1" in result.tier_2.reason


def test_many_slivers_over_threshold() -> None:
    over = max(RESIDUAL_VOLUME_FLOOR_M3, RESIDUAL_VOLUME_REL * BASELINE["volume_m3"]) * 10.0
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(
            error_code=BODY_OPERATION_PARTIAL_COINCIDENCE,
            body_count=37,
            total_volume_m3=over,
            per_body_bbox=tuple((0.01, 0.01, 2e-7) for _ in range(37)),
        ),
    )
    assert result.verdict == "fail"
    assert result.tier_2 is not None and result.tier_2.reason is not None
    assert f"{over:.3g}" in result.tier_2.reason
    assert "37" in result.tier_2.reason, "residual body count is recorded beside the volume"


def test_the_three_residual_signals_are_read_separately() -> None:
    """A residual under the volume threshold still fails when it is a real solid."""
    under = RESIDUAL_VOLUME_FLOOR_M3 / 10.0
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(
            body_count=1,
            total_volume_m3=under,
            per_body_bbox=((RESIDUAL_MIN_DIMENSION_M * 10, 1.0, 1.0),),
        ),
    )
    assert result.verdict == "fail"
    assert result.tier_2 is not None and result.tier_2.reason is not None
    assert "minimum" in result.tier_2.reason


def test_residual_body_count_is_recorded_and_not_gated() -> None:
    """Many tiny lumps is the sliver signature; the count alone decides nothing."""
    tiny = tuple((0.001, 0.001, 1e-8) for _ in range(500))
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(body_count=500, total_volume_m3=1e-14, per_body_bbox=tiny),
    )
    assert result.verdict == "pass"
    assert result.tier_2 is not None and result.tier_2.reason is not None
    assert "500" in result.tier_2.reason


def test_residual_null_bounding_box() -> None:
    """`GetBodyBox` returned null: the gate did not run on that residual."""
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(body_count=1, total_volume_m3=1e-15, per_body_bbox=((None, None, None),)),
    )
    assert result.verdict == "unresolved"
    assert result.tier_2 is not None
    assert result.tier_2.ran is False
    assert result.tier_2.reason is not None and "bounding box" in result.tier_2.reason


def test_residual_bbox_count_mismatch() -> None:
    """Fewer boxes than bodies: the third signal is not a reading of every residual."""
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(
            body_count=9, total_volume_m3=1e-15, per_body_bbox=((0.001, 0.001, 1e-8),)
        ),
    )
    assert result.verdict == "unresolved"
    assert result.tier_2 is not None
    assert result.tier_2.ran is False
    assert result.tier_2.reason is not None
    assert "9" in result.tier_2.reason, "the reason names how many bodies were reported"
    assert "1 " in result.tier_2.reason, "and how many boxes were read"


def test_residual_bodies_with_no_bounding_box_reported_is_unresolved() -> None:
    """A measurement that did not happen is never a pass, however small the volume."""
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(body_count=3, total_volume_m3=1e-15, per_body_bbox=()),
    )
    assert result.verdict == "unresolved"
    assert result.tier_2 is not None
    assert result.tier_2.ran is False
    assert result.tier_2.reason is not None
    assert "3" in result.tier_2.reason
    assert "0 " in result.tier_2.reason


def test_a_null_residual_volume_is_unresolved() -> None:
    result = evaluate(
        before(), after(), IDENTITY, residual=residual(body_count=1, total_volume_m3=None)
    )
    assert result.verdict == "unresolved"
    assert result.tier_2 is not None and result.tier_2.ran is False


def test_error_code_1058_boolean_fail() -> None:
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(error_code=BODY_OPERATION_BOOLEAN_FAIL, total_volume_m3=None),
    )
    assert result.verdict == "unresolved"
    assert result.tier_2 is not None and result.tier_2.ran is False
    assert result.tier_2.reason is not None and "1058" in result.tier_2.reason


def test_error_code_minus_1_unknown() -> None:
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(error_code=BODY_OPERATION_UNKNOWN_ERROR, total_volume_m3=None),
    )
    assert result.verdict == "unresolved"
    assert result.tier_2 is not None and result.tier_2.ran is False


def test_error_code_1_non_api_body() -> None:
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(error_code=BODY_OPERATION_NON_API_BODY, total_volume_m3=None),
    )
    assert result.verdict == "unresolved"
    assert result.tier_2 is not None and result.tier_2.ran is False
    assert result.tier_2.reason is not None and "API body" in result.tier_2.reason


def test_error_code_6_empty_body_is_a_pass_signal() -> None:
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(error_code=BODY_OPERATION_EMPTY_BODY, body_count=0, total_volume_m3=0.0),
    )
    assert result.verdict == "pass"
    assert result.tier_2 is not None and result.tier_2.verdict == "pass"
    assert result.tier_2.reason is not None and "entirely inside" in result.tier_2.reason


def test_error_code_1067_no_intersect_is_read_with_the_residual_volume() -> None:
    """Never alone: the same code passes on an empty residual and fails on a real one."""
    empty = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(error_code=BODY_OPERATION_NO_INTERSECT, total_volume_m3=0.0),
    )
    assert empty.verdict == "pass"
    assert empty.tier_2 is not None and empty.tier_2.reason is not None
    assert "0" in empty.tier_2.reason

    real = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(
            error_code=BODY_OPERATION_NO_INTERSECT,
            body_count=1,
            total_volume_m3=BASELINE["volume_m3"] / 2.0,
            per_body_bbox=((0.05, 0.05, 0.05),),
        ),
    )
    assert real.verdict == "fail"


def test_error_code_1040_partial_coincidence_inspects_the_residual_rather_than_failing() -> None:
    result = evaluate(
        before(),
        after(),
        IDENTITY,
        residual=residual(
            error_code=BODY_OPERATION_PARTIAL_COINCIDENCE,
            body_count=1,
            total_volume_m3=1e-15,
            per_body_bbox=((0.01, 0.01, 1e-8),),
        ),
    )
    assert result.verdict == "pass"
    assert result.tier_2 is not None and result.tier_2.verdict == "pass"


def test_tier1_fail_tier2_pass_is_unresolved_and_never_silently_resolved() -> None:
    outside = BASELINE["volume_m3"] * (1.0 + IDENTITY.volume_rel * 2.0)
    result = evaluate(before(), after(volume_m3=outside), IDENTITY, residual=residual())
    assert result.tier_1.verdict == "fail"
    assert result.tier_2 is not None and result.tier_2.verdict == "pass"
    assert result.verdict == "unresolved"
    assert result.diagnosis is not None
    assert "tolerance" in result.diagnosis


def test_tier1_fail_tier2_fail_is_a_failure() -> None:
    outside = BASELINE["volume_m3"] * (1.0 + IDENTITY.volume_rel * 2.0)
    result = evaluate(
        before(),
        after(volume_m3=outside),
        IDENTITY,
        residual=residual(
            body_count=1,
            total_volume_m3=BASELINE["volume_m3"] / 2.0,
            per_body_bbox=((0.05, 0.05, 0.05),),
        ),
    )
    assert result.verdict == "fail"


def test_tier1_unresolved_stays_unresolved_whatever_tier2_says() -> None:
    result = evaluate(before(status=3), after(), IDENTITY, residual=residual())
    assert result.verdict == "unresolved"
    assert result.tier_1.verdict == "unresolved"
