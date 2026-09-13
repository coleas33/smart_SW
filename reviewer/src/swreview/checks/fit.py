"""Size-only fit of a shaft in a bore (T079, `fit.size_only`).

The whole model is two subtractions on the two worst conditions of the two toleranced
diameters. Everything else that decides whether a shaft goes into a bore - where the
features sit, how round they are, what they are plated with, how hot they get, how much
they deflect - is outside it and is named in `excluded_effects` on every result.
"""

from __future__ import annotations

from swreview.checks.result import (
    ROUNDING_ASSUMPTION,
    CheckResult,
    MissingToleranceError,
    cite,
    dimension_inputs,
    limits_mm,
    require_length,
    round_length,
    unresolved,
)
from swreview.findings import Calculation, Severity
from swreview.ir.models import Dimension

__all__ = ["CHECK", "EXCLUDED_EFFECTS", "check_fit"]

CHECK = "fit.size_only"
FUNCTION = "swreview.checks.fit.check_fit"
FUNCTION_VERSION = "1"

EXCLUDED_EFFECTS = [
    "geometric position tolerance (coaxiality, runout)",
    "form error (roundness, straightness, cylindricity)",
    "coatings and platings",
    "temperature",
    "deformation under load or press",
]

_SEVERITY_BY_FIT: dict[str, Severity] = {
    "clearance": "info",
    "transition": "medium",
    "interference": "high",
}

COVERAGE_LIMIT = (
    f"{CHECK} considered size only; {', '.join(EXCLUDED_EFFECTS)} were not evaluated"
)

_ACTION_BY_FIT = {
    "clearance": (
        "None from the size data; confirm position, form and coating separately if the "
        "joint is tight."
    ),
    "transition": (
        "Decide whether a transition fit is intended here: the parts as drawn may "
        "assemble with clearance or need pressing, depending on where each part falls "
        "in its tolerance band."
    ),
    "interference": (
        "Confirm the interference is intended and that the assembly method (press, "
        "shrink) is specified; otherwise revise the bore or shaft tolerance."
    ),
}


def check_fit(bore: Dimension, shaft: Dimension) -> CheckResult:
    """Clearance or interference between a bore and a shaft, from size alone.

    The two worst conditions are `min_clearance_mm = bore_min - shaft_max` and
    `max_clearance_mm = bore_max - shaft_min`; a negative clearance is interference.
    `fit_class` is `clearance` when the minimum clearance is not negative,
    `interference` when the maximum clearance is not positive, and `transition` when the
    two straddle zero.

    Status. A fit that clears at both limits is `checked_within_scope`: the numbers are
    shown and nothing in the size data contradicts assembly. A transition or
    interference fit is `suspected`, never `demonstrated`. `demonstrated` would mean the
    check showed a requirement to be violated, and the requirement - a fit class such as
    `H7/g6`, or a press-fit note - is not machine-readable in this phase: an
    interference may be exactly what the designer intended. The check therefore reports
    both clearances, quotes the drawing text for each side, and leaves the verdict to
    the engineer. `demonstrated` becomes available to this check only once a fit
    requirement is parsed alongside the dimensions.

    A tolerance that carries no size limits (`basic`, `none`, or a missing value) is
    `unresolved` naming the side it was missing on; an angular dimension on either side
    raises `TypeError` before any arithmetic.
    """
    require_length(bore, "bore")
    require_length(shaft, "shaft")
    requirement = (
        f"Fit as drawn: bore {bore.text_as_read!r} ({cite(bore.source)}) over shaft "
        f"{shaft.text_as_read!r} ({cite(shaft.source)}); no machine-readable fit class "
        "requirement in this phase"
    )

    try:
        bore_limits = limits_mm(bore)
    except MissingToleranceError as error:
        return _unresolved_side("bore", bore, error, bore, shaft, requirement)
    try:
        shaft_limits = limits_mm(shaft)
    except MissingToleranceError as error:
        return _unresolved_side("shaft", shaft, error, bore, shaft, requirement)

    min_clearance = round_length(bore_limits.min_mm - shaft_limits.max_mm)
    max_clearance = round_length(bore_limits.max_mm - shaft_limits.min_mm)
    fit_class = _classify(min_clearance, max_clearance)

    return CheckResult(
        check=CHECK,
        status="checked_within_scope" if fit_class == "clearance" else "suspected",
        severity=_SEVERITY_BY_FIT[fit_class],
        observed=(
            f"{fit_class.capitalize()} fit on size: {min_clearance} mm to "
            f"{max_clearance} mm diametral clearance between bore "
            f"{bore.text_as_read!r} ({bore_limits.min_mm}/{bore_limits.max_mm} mm) and "
            f"shaft {shaft.text_as_read!r} ({shaft_limits.min_mm}/{shaft_limits.max_mm} mm)"
        ),
        requirement=requirement,
        inputs=[bore, shaft],
        calculation=Calculation(
            model=CHECK,
            inputs={
                **dimension_inputs("bore", bore, bore_limits),
                **dimension_inputs("shaft", shaft, shaft_limits),
            },
            assumptions=[
                "diametral clearance: bore and shaft are coaxial cylinders of the "
                "stated sizes",
                "worst case: each part is at the limit of its own tolerance band, "
                "independently of the other",
                ROUNDING_ASSUMPTION,
            ],
            excluded_effects=list(EXCLUDED_EFFECTS),
            result={
                "min_clearance_mm": min_clearance,
                "max_clearance_mm": max_clearance,
                "fit_class": fit_class,
            },
            units_out="mm",
            function=FUNCTION,
            function_version=FUNCTION_VERSION,
        ),
        coverage_limits=[COVERAGE_LIMIT],
        recommended_action=_ACTION_BY_FIT[fit_class],
    )


def _classify(min_clearance: float, max_clearance: float) -> str:
    if min_clearance >= 0.0:
        return "clearance"
    if max_clearance <= 0.0:
        return "interference"
    return "transition"


def _unresolved_side(
    role: str,
    dimension: Dimension,
    error: MissingToleranceError,
    bore: Dimension,
    shaft: Dimension,
    requirement: str,
) -> CheckResult:
    return unresolved(
        CHECK,
        f"the {role} tolerance for {dimension.text_as_read!r} "
        f"({cite(dimension.source)}; {error})",
        [bore, shaft],
        requirement=requirement,
        recommended_action=(
            f"Add the limits for the {role} to the drawing, or supply the general note "
            f"that governs {dimension.text_as_read!r}, then re-run the fit check."
        ),
    )
