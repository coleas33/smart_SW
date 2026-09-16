"""Unit tests for the units module (T007).

The unit module is the only place allowed to do unit arithmetic; these tests pin the
length/angle separation the spec calls out (FR-022, constitution Principle II).
"""

from __future__ import annotations

import math

import pytest
from pint import DimensionalityError

from swreview import units
from swreview.ir.models import Angle, Quantity


def test_convert_mm_to_inch_keeps_source_and_converted() -> None:
    result = units.convert(Quantity(value=25.4, unit="mm"), "in")

    assert result.source == Quantity(value=25.4, unit="mm")
    assert result.converted.unit == "in"
    assert result.converted.value == pytest.approx(1.0, abs=1e-9)


def test_convert_inch_to_mm() -> None:
    result = units.convert(Quantity(value=0.5, unit="in"), "mm")

    assert result.converted.unit == "mm"
    assert result.converted.value == pytest.approx(12.7, abs=1e-9)


def test_convert_round_trips_to_1e_9() -> None:
    start = Quantity(value=37.125, unit="mm")

    there = units.convert(start, "in")
    back = units.convert(there.converted, "mm")

    assert back.converted.value == pytest.approx(start.value, abs=1e-9)


def test_convert_to_same_unit_is_identity() -> None:
    result = units.convert(Quantity(value=3.0, unit="m"), "m")

    assert result.converted == Quantity(value=3.0, unit="m")


def test_as_mm_returns_a_float_in_millimetres() -> None:
    value = units.as_mm(Quantity(value=2.0, unit="in"))

    assert isinstance(value, float)
    assert value == pytest.approx(50.8, abs=1e-9)


def test_to_length_keeps_the_source_unit() -> None:
    pint_quantity = units.to_length(Quantity(value=12.0, unit="mm"))

    assert f"{pint_quantity.units}" == "millimeter"
    assert pint_quantity.magnitude == pytest.approx(12.0)


def test_to_angle_converts_degrees_and_radians() -> None:
    degrees = units.to_angle(Angle(value=180.0, unit="deg"))
    radians = units.to_angle(Angle(value=math.pi, unit="rad"))

    assert degrees.to("rad").magnitude == pytest.approx(math.pi, abs=1e-9)
    assert radians.magnitude == pytest.approx(math.pi, abs=1e-9)


def test_angle_passed_to_a_length_function_raises_dimensionality_error() -> None:
    angle = Angle(value=45.0, unit="deg")

    with pytest.raises(DimensionalityError):
        units.to_length(angle)
    with pytest.raises(DimensionalityError):
        units.as_mm(angle)
    with pytest.raises(DimensionalityError):
        units.convert(angle, "mm")


def test_length_passed_to_the_angle_function_raises_dimensionality_error() -> None:
    with pytest.raises(DimensionalityError):
        units.to_angle(Quantity(value=10.0, unit="mm"))
    with pytest.raises(DimensionalityError):
        units.as_degrees(Quantity(value=10.0, unit="mm"))


def test_as_degrees_reads_an_angle_in_degrees() -> None:
    """The angular sibling of `as_mm`: every angle an equation carries is in degrees
    (`swAngularEquationUnits_e`), and this is the one place the conversion happens."""
    assert units.as_degrees(Angle(value=45.0, unit="deg")) == pytest.approx(45.0, abs=1e-12)
    assert units.as_degrees(Angle(value=math.pi, unit="rad")) == pytest.approx(180.0, abs=1e-9)


def test_unknown_target_unit_raises_value_error() -> None:
    with pytest.raises(ValueError, match="furlong"):
        units.convert(Quantity(value=1.0, unit="mm"), "furlong")


def test_module_exports_only_the_agreed_surface() -> None:
    assert set(units.__all__) == {
        "Converted",
        "as_degrees",
        "as_mm",
        "convert",
        "to_angle",
        "to_length",
    }
