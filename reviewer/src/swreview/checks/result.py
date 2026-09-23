"""What every deterministic check returns, and the pieces they all need.

A check is a pure function: IR entities in, one `CheckResult` out (plan.md Phase 1,
design point 2). The tool layer turns a `CheckResult` into a `Finding` with
`swreview.findings.build_finding`, which is where provenance and the finding id come
from; nothing here knows about packages or sessions.

Three rules from the constitution live here so no check can restate them differently:

- a missing input is never defaulted. `unresolved()` is the only way a check reports a
  value it could not obtain and it always names the field (Principle I);
- `swreview.units` is the only converter, and both the number as drawn and the number
  the arithmetic used are recorded (Principle II);
- `limits_mm()` is the single reading of a `Tolerance`, so `fit` and `stack` cannot
  disagree about what `bilateral` means (Principle V, DRY).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from swreview import units
from swreview.findings import Calculation, FindingStatus, Severity
from swreview.ir.models import Angle, Dimension, LengthUnit, Quantity, SourceRef

__all__ = [
    "PLACES",
    "ROUNDING_ASSUMPTION",
    "CheckResult",
    "DocumentResult",
    "Limits",
    "MissingToleranceError",
    "cite",
    "dimension_inputs",
    "limits_mm",
    "permitted_radial_offset_mm",
    "require_length",
    "round_length",
    "unresolved",
]

PLACES = 6
"""Lengths are reported to 1e-6 of their unit: below any manufacturing meaning, and
above the float noise that would otherwise make 40.000 - 39.991 read 0.00899999..."""

ROUNDING_ASSUMPTION = f"lengths rounded to 1e-{PLACES} of the unit they are reported in"
"""Stated by every check that rounds, so a reader knows the last digit is not measured."""


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict on one set of inputs.

    The fields are the subset of `Finding` a check can fill on its own: the tool layer
    adds the id, title, components, drawing locations and provenance.
    """

    check: str
    status: FindingStatus
    severity: Severity
    observed: str
    requirement: str
    inputs: list[Dimension | Quantity | str]
    calculation: Calculation | None
    coverage_limits: list[str]
    recommended_action: str


@dataclass(frozen=True)
class DocumentResult:
    """A document-scope verdict and what its finding binds to (feature 010's mass and
    hygiene checks): the documents it judged and every instance of them. The documents are
    bound as well, so a finding on the root assembly - which no component instantiates - still
    names where it was read."""

    result: CheckResult
    documents: tuple[str, ...]
    component_ids: tuple[str, ...]

    @property
    def document_id(self) -> str:
        """The first document judged: the only one, for a check of one document."""
        return self.documents[0]

    @property
    def document_ids(self) -> tuple[str, ...]:
        return self.documents


def unresolved(
    check: str,
    missing: str,
    inputs: Sequence[Dimension | Quantity | str],
    *,
    requirement: str,
    recommended_action: str,
    severity: Severity = "medium",
) -> CheckResult:
    """The one shape every check uses to report an input it could not obtain.

    `missing` names the field - which side, which index, which value - and appears in
    both the observed condition and the coverage limit, so the report says what is
    unknown and the coverage says the check did not run (Principle I; `build_finding`
    requires a coverage limit on every unresolved finding).
    """
    return CheckResult(
        check=check,
        status="unresolved",
        severity=severity,
        observed=f"{missing} is unknown; the check did not run",
        requirement=requirement,
        inputs=list(inputs),
        calculation=None,
        coverage_limits=[f"{check} not evaluated: {missing} is unknown"],
        recommended_action=recommended_action,
    )


class MissingToleranceError(ValueError):
    """A dimension carries no usable size limits, so a check cannot use it.

    Expected input, not a bug: the caller turns it into `unresolved()` with wording that
    names which dimension it was.
    """


def round_length(value: float) -> float:
    """Round a length to `PLACES` decimals of whatever unit it is expressed in."""
    return round(value, PLACES)


def permitted_radial_offset_mm(zone_mm: float) -> float:
    """How far an axis may sit from true position inside a zone of `zone_mm` (FR-009).

    A position or coaxiality zone of `t` - a cylinder of diameter `t` or a band of width `t`
    centred on true position - lets the axis move `t / 2`, whether or not a diameter symbol
    was read (feature 010 research R2.8). The one reading of a zone: `hole.coaxiality` and
    the joint stack both call it. Raises `ValueError` for a negative zone.
    """
    if zone_mm < 0.0:
        raise ValueError(f"a tolerance zone cannot be negative, got {zone_mm} mm")
    return round_length(zone_mm / 2.0)


def cite(source: SourceRef) -> str:
    """A short, human-checkable reference to where a value was read."""
    parts = [source.document_id]
    if source.sheet is not None:
        parts.append(f"sheet {source.sheet}")
    if source.view is not None:
        parts.append(f"view {source.view}")
    if source.annotation is not None:
        parts.append(f"annotation {source.annotation}")
    if source.page is not None:
        parts.append(f"page {source.page}")
    return " ".join(parts)


def require_length(dimension: Dimension, role: str) -> None:
    """Raise `TypeError` when `role` is angular, before any arithmetic runs.

    pint would raise `DimensionalityError` a few lines later, but an angle where a
    length belongs is a mistake at the call site - the wrong dimension was selected -
    not an unknown input, so it is an exception and never a `CheckResult` (FR-022).
    """
    candidates = (
        ("nominal", dimension.nominal),
        ("upper tolerance", dimension.tolerance.upper),
        ("lower tolerance", dimension.tolerance.lower),
    )
    for label, value in candidates:
        if isinstance(value, Angle):
            raise TypeError(
                f"{role} {label} is an angle ({value.value} {value.unit}, "
                f"{dimension.text_as_read!r}); this check needs a length"
            )


@dataclass(frozen=True)
class Limits:
    """The two size limits of one toleranced dimension, in mm and in its own unit."""

    nominal_mm: float
    min_mm: float
    max_mm: float
    min_source: Quantity
    max_source: Quantity

    @property
    def upper_deviation_mm(self) -> float:
        """How far the maximum limit sits above nominal; never negative."""
        return round_length(self.max_mm - self.nominal_mm)

    @property
    def lower_deviation_mm(self) -> float:
        """How far the minimum limit sits below nominal; never positive."""
        return round_length(self.min_mm - self.nominal_mm)


def _in_unit(value_mm: float, unit: LengthUnit) -> Quantity:
    converted = units.convert(Quantity(value=value_mm, unit="mm"), unit)
    return Quantity(value=round_length(converted.converted.value), unit=unit)


def limits_mm(dimension: Dimension) -> Limits:
    """The minimum and maximum size of `dimension`, read by tolerance kind.

    Conventions (data-model.md, `Tolerance`):

    - `symmetric`: `upper` is the half width; the limits are nominal +/- |upper|, and
      `lower` is ignored.
    - `bilateral`: `upper` and `lower` are signed deviations from nominal, so
      `12 +0.05/-0.15` carries `lower = -0.15`. A positive `lower` is taken as written,
      which is how `40 +0.05/+0.02` is stored.
    - `limits`: `upper` and `lower` are the two limits themselves, not deviations.
    - `basic` and `none` carry no size limits at all.

    Raises `MissingToleranceError` when the kind carries no limits or a needed value is
    `None`, and `ValueError` when the two limits are the wrong way round.
    """
    tolerance = dimension.tolerance
    nominal_mm = units.as_mm(dimension.nominal)

    if tolerance.kind in ("basic", "none"):
        raise MissingToleranceError(
            f"tolerance kind {tolerance.kind!r} carries no size limits"
        )
    if tolerance.kind == "symmetric":
        if tolerance.upper is None:
            raise MissingToleranceError("symmetric tolerance with no upper value")
        half_width = abs(units.as_mm(tolerance.upper))
        min_mm, max_mm = nominal_mm - half_width, nominal_mm + half_width
    else:
        if tolerance.upper is None or tolerance.lower is None:
            side = "upper" if tolerance.upper is None else "lower"
            raise MissingToleranceError(f"{tolerance.kind} tolerance with no {side} value")
        if tolerance.kind == "bilateral":
            min_mm = nominal_mm + units.as_mm(tolerance.lower)
            max_mm = nominal_mm + units.as_mm(tolerance.upper)
        else:
            min_mm = units.as_mm(tolerance.lower)
            max_mm = units.as_mm(tolerance.upper)

    min_mm, max_mm = round_length(min_mm), round_length(max_mm)
    if min_mm > max_mm:
        raise ValueError(
            f"lower limit {min_mm} mm is above upper limit {max_mm} mm "
            f"for {dimension.text_as_read!r} ({cite(dimension.source)})"
        )

    unit: LengthUnit = dimension.nominal.unit  # type: ignore[assignment]
    return Limits(
        nominal_mm=round_length(nominal_mm),
        min_mm=min_mm,
        max_mm=max_mm,
        min_source=_in_unit(min_mm, unit),
        max_source=_in_unit(max_mm, unit),
    )


def dimension_inputs(
    prefix: str, dimension: Dimension, limits: Limits
) -> dict[str, Quantity | Angle | str]:
    """The evidence one toleranced dimension contributes to a `Calculation.inputs` block.

    Both the value as drawn and the value the arithmetic used are recorded, so a reader
    can re-do the conversion (Principle II), along with where the tolerance came from -
    which is not always the dimension itself (a general note).
    """
    return {
        f"{prefix}_text_as_read": dimension.text_as_read,
        f"{prefix}_tolerance_kind": dimension.tolerance.kind,
        f"{prefix}_tolerance_source": cite(dimension.tolerance.source),
        f"{prefix}_min_source": limits.min_source,
        f"{prefix}_min_mm": Quantity(value=limits.min_mm, unit="mm"),
        f"{prefix}_max_source": limits.max_source,
        f"{prefix}_max_mm": Quantity(value=limits.max_mm, unit="mm"),
    }
