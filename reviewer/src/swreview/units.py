"""The only place in the reviewer that converts units (research R6).

One shared `pint.UnitRegistry` backs every conversion so lengths and angles cannot be
mixed: passing an `Angle` to a length function raises `pint.DimensionalityError`
(FR-022, constitution Principle II). Conversions keep both the source and the converted
quantity so a finding can cite the number as drawn and the number as calculated.
"""

from __future__ import annotations

import pint
from pydantic import BaseModel, ConfigDict

from swreview.ir.models import Angle, LengthUnit, Quantity

__all__ = ["Converted", "as_mm", "convert", "to_angle", "to_length"]

_REGISTRY = pint.UnitRegistry()

_LENGTH_UNITS: tuple[str, ...] = ("mm", "in", "m")


class Converted(BaseModel):
    """A conversion result: the quantity as stored and the same quantity as asked for."""

    model_config = ConfigDict(strict=True, extra="forbid")

    source: Quantity
    converted: Quantity


def _pint_unit(name: str) -> pint.Unit:
    try:
        return _REGISTRY.Unit(name)
    except pint.UndefinedUnitError as exc:
        raise ValueError(f"unknown unit {name!r}") from exc


def to_length(q: Quantity | Angle) -> pint.Quantity:
    """Return `q` as a pint quantity in its own unit, rejecting anything but a length.

    Raises `pint.DimensionalityError` when given an `Angle`.
    """
    quantity = _REGISTRY.Quantity(q.value, _pint_unit(q.unit))
    if not quantity.check("[length]"):
        raise pint.DimensionalityError(
            quantity.units, _REGISTRY.millimeter, extra_msg=" (a length was required)"
        )
    return quantity


def to_angle(a: Angle | Quantity) -> pint.Quantity:
    """Return `a` as a pint quantity in its own unit, rejecting anything but an angle.

    Raises `pint.DimensionalityError` when given a `Quantity` (a length).
    """
    quantity = _REGISTRY.Quantity(a.value, _pint_unit(a.unit))
    if quantity.dimensionality != _REGISTRY.radian.dimensionality:
        raise pint.DimensionalityError(
            quantity.units, _REGISTRY.degree, extra_msg=" (an angle was required)"
        )
    return quantity


def convert(q: Quantity | Angle, unit: LengthUnit) -> Converted:
    """Convert a length to `unit`, keeping the source quantity alongside the result."""
    if unit not in _LENGTH_UNITS:
        raise ValueError(f"unknown length unit {unit!r}; expected one of {_LENGTH_UNITS}")
    converted = to_length(q).to(_pint_unit(unit))
    return Converted(
        source=Quantity(value=q.value, unit=q.unit),
        converted=Quantity(value=float(converted.magnitude), unit=unit),
    )


def as_mm(q: Quantity | Angle) -> float:
    """Return the magnitude of a length in millimetres."""
    return float(to_length(q).to(_REGISTRY.millimeter).magnitude)
