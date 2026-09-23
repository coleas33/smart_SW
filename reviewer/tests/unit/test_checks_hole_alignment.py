"""Unit tests for the hole coaxiality check (T085).

Two holes that should share an axis: the check reports the measured offset and the angle
between the axes, and compares the offset with a tolerance that came from the package.
With no tolerance the measurement is still reported, but the verdict is withheld
(constitution Principle I).
"""

from __future__ import annotations

import math

import pytest

from swreview.checks.hole_alignment import check_hole_alignment
from swreview.ir.models import (
    Angle,
    Axis,
    Dimension,
    Hole,
    Quantity,
    SourceRef,
    Tolerance,
    Vec3,
)
from tests.support.packages import persist_ref


def hole(
    hole_id: str,
    origin: tuple[float, float, float],
    direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
    component_id: str = "cmp:0001",
) -> Hole:
    return Hole(
        id=hole_id,
        persist_ref=persist_ref(hole_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        feature_name=f"{hole_id} Hole1",
        hole_type="clearance",
        standard=None,
        size=None,
        thread_designation=None,
        thread_depth=None,
        hole_depth=Quantity(value=10.0, unit="mm"),
        end_condition="through",
        diameter=Quantity(value=6.6, unit="mm"),
        axis=Axis(
            origin=Vec3(x=origin[0], y=origin[1], z=origin[2]),
            direction=Vec3(x=direction[0], y=direction[1], z=direction[2]),
        ),
        face_ids=[],
    )


def tolerance(nominal: Quantity | Angle) -> Dimension:
    source = SourceRef(document_id="doc:1", sheet="Sheet1", annotation="DIM-7")
    return Dimension(
        nominal=nominal,
        tolerance=Tolerance(kind="symmetric", upper=None, lower=None, source=source),
        source=source,
        text_as_read="0.2",
    )


def test_offset_within_tolerance_is_checked_within_scope() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0001, 0.0, 0.020)),
        tolerance(Quantity(value=0.2, unit="mm")),
    )

    assert result.check == "hole.coaxiality"
    assert result.status == "checked_within_scope"
    assert result.calculation is not None
    assert result.calculation.model == "hole.coaxiality"
    assert result.calculation.result["offset_mm"] == pytest.approx(0.1, abs=1e-9)
    assert result.calculation.result["relation"] == "parallel"


def test_offset_beyond_tolerance_is_demonstrated() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0005, 0.0, 0.020)),
        tolerance(Quantity(value=0.2, unit="mm")),
    )

    assert result.status == "demonstrated"
    assert result.calculation.result["offset_mm"] == pytest.approx(0.5, abs=1e-9)
    assert result.calculation.result["tolerance_mm"] == pytest.approx(0.2, abs=1e-9)
    assert "0.5" in result.observed


def test_coaxial_holes_are_checked_within_scope() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0, 0.0, 0.020)),
        tolerance(Quantity(value=0.05, unit="mm")),
    )

    assert result.status == "checked_within_scope"
    assert result.calculation.result["offset_mm"] == pytest.approx(0.0, abs=1e-12)
    assert result.calculation.result["relation"] == "coincident"


def test_a_missing_tolerance_is_unresolved_but_still_reports_the_offset() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0005, 0.0, 0.020)),
        None,
    )

    assert result.status == "unresolved"
    assert any("tolerance" in limit for limit in result.coverage_limits)
    assert result.calculation.result["offset_mm"] == pytest.approx(0.5, abs=1e-9)


def test_the_angle_between_the_axes_is_reported() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0, 0.0, 0.020), direction=(1.0, 0.0, 1.0)),
        tolerance(Quantity(value=0.2, unit="mm")),
    )

    # The angle is rounded like every other reported number (`result.PLACES`).
    assert result.calculation.result["axis_angle_rad"] == pytest.approx(math.pi / 4, abs=1e-6)
    assert result.calculation.result["relation"] == "intersecting"


def test_an_angular_misalignment_is_named_as_an_excluded_effect() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0, 0.0, 0.020), direction=(1.0, 0.0, 1.0)),
        tolerance(Quantity(value=0.2, unit="mm")),
    )

    assert any("angle" in limit for limit in result.coverage_limits)


def test_an_angular_tolerance_where_a_length_belongs_raises() -> None:
    """Same refusal as `check_fit`: a TypeError at the call site, never a CheckResult."""
    with pytest.raises(TypeError, match="coaxiality tolerance"):
        check_hole_alignment(
            hole("hole:1", (0.0, 0.0, 0.0)),
            hole("hole:2", (0.0, 0.0, 0.020)),
            tolerance(Angle(value=0.5, unit="deg")),
        )


def test_an_offset_between_half_the_zone_and_the_zone_is_demonstrated() -> None:
    """Feature 010 FR-009: a 0.2 mm zone lets the axis move 0.1 mm, so 0.15 mm - within the
    zone value the check used to compare with - is now demonstrated (research R2.8)."""
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.00015, 0.0, 0.020)),
        tolerance(Quantity(value=0.2, unit="mm")),
    )

    assert result.status == "demonstrated"
    assert result.calculation is not None
    assert result.calculation.result["zone_mm"] == pytest.approx(0.2)
    assert result.calculation.result["permitted_offset_mm"] == pytest.approx(0.1)
    assert result.calculation.result["within_tolerance"] is False
    assert (
        "the tolerance value is a position or coaxiality zone; the axis may move half of it "
        "from true position"
    ) in result.calculation.assumptions


def test_the_zone_and_the_permitted_offset_are_recorded_on_a_pass() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0001, 0.0, 0.020)),
        tolerance(Quantity(value=0.2, unit="mm")),
    )

    assert result.status == "checked_within_scope"
    assert result.calculation.result["zone_mm"] == pytest.approx(0.2)
    assert result.calculation.result["permitted_offset_mm"] == pytest.approx(0.1)
    assert result.calculation.result["within_tolerance"] is True


def test_both_hole_ids_are_recorded_in_the_calculation_inputs() -> None:
    result = check_hole_alignment(
        hole("hole:1", (0.0, 0.0, 0.0)),
        hole("hole:2", (0.0, 0.0, 0.020)),
        tolerance(Quantity(value=0.2, unit="mm")),
    )

    assert result.calculation.inputs["hole_a"] == "hole:1"
    assert result.calculation.inputs["hole_b"] == "hole:2"
