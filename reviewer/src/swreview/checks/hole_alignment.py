"""Coaxiality of two holes that are meant to share an axis (T089, `hole.coaxiality`).

The model is one measurement - the closest distance between the two hole axes, with the
angle between them alongside - compared with a position tolerance read from the package.
It is a size-and-position comparison of the axes as modelled, not a GD&T evaluation: no
datum reference frame, no material condition, no form error.

With no tolerance the offset is still measured and reported; only the verdict is withheld
(constitution Principle I).
"""

from __future__ import annotations

from swreview import units
from swreview.checks.result import (
    ROUNDING_ASSUMPTION,
    CheckResult,
    cite,
    require_length,
    round_length,
)
from swreview.findings import Calculation, Severity
from swreview.geometry.axis import ANGLE_TOL_RAD, axis_distance
from swreview.ir.models import Angle, Dimension, Hole, Quantity

__all__ = ["CHECK", "EXCLUDED_EFFECTS", "check_hole_alignment"]

CHECK = "hole.coaxiality"
FUNCTION = "swreview.checks.hole_alignment.check_hole_alignment"
FUNCTION_VERSION = "1"

EXCLUDED_EFFECTS = [
    "datum reference frame and material condition modifiers (MMC, LMC)",
    "form error of the hole walls (roundness, straightness)",
    "component position tolerance and mate play in the assembly",
    "the angle between the axes, which is reported but has no tolerance to compare with",
]

CalcInputs = dict[str, Quantity | Angle | str]
CalcResult = dict[str, Quantity | bool | str | float]

_SEVERITY_BY_STATUS: dict[str, Severity] = {
    "unresolved": "medium",
    "checked_within_scope": "info",
}


def check_hole_alignment(a: Hole, b: Hole, tolerance: Dimension | None) -> CheckResult:
    """Compare the offset between two hole axes with a position tolerance.

    `tolerance` is the drawing dimension that governs the pair; its nominal is read as the
    permitted offset. `None` leaves the check `unresolved` with the measured offset still
    reported. An offset above the tolerance is `demonstrated`; at or below it, the check is
    `checked_within_scope`.

    Raises `TypeError` when `tolerance` is an angular dimension: an angle where a length
    belongs is a mistake at the call site, not an unknown input (FR-022).
    """
    if tolerance is not None:
        require_length(tolerance, "coaxiality tolerance")

    relation = axis_distance(a.axis, b.axis)
    offset_mm = round_length(relation.distance_m * 1000.0)
    angle_rad = round_length(relation.angle_rad)

    requirement = (
        f"holes {a.id} and {b.id} share an axis to within {tolerance.text_as_read!r} "
        f"({cite(tolerance.source)})"
        if tolerance is not None
        else f"holes {a.id} and {b.id} share an axis to within a tolerance the package does "
        "not carry"
    )
    result: CalcResult = {
        "offset_mm": offset_mm,
        "axis_angle_rad": angle_rad,
        "relation": relation.relation,
    }
    inputs: CalcInputs = {
        "hole_a": a.id,
        "hole_b": b.id,
        "hole_a_component": a.component_id,
        "hole_b_component": b.component_id,
    }
    coverage_limits = [
        f"{CHECK} compared the modelled axes only; {', '.join(EXCLUDED_EFFECTS)} were not "
        "evaluated"
    ]
    if angle_rad > ANGLE_TOL_RAD:
        coverage_limits.append(
            f"the axes of {a.id} and {b.id} are not parallel ({angle_rad} rad apart); the "
            "reported offset is the closest distance between them and the angle has no "
            "tolerance to compare with"
        )

    if tolerance is None:
        return CheckResult(
            check=CHECK,
            status="unresolved",
            severity="medium",
            observed=(
                f"The axes of {a.id} and {b.id} are {offset_mm} mm apart ({relation.relation}), "
                "but no coaxiality tolerance is available; the check did not run."
            ),
            requirement=requirement,
            inputs=[a.id, b.id],
            calculation=_calculation(inputs, result, tolerance),
            coverage_limits=[
                f"{CHECK} not evaluated: the coaxiality tolerance for {a.id} and {b.id} is "
                "unknown",
                *coverage_limits,
            ],
            recommended_action=(
                f"Add the position tolerance that governs {a.id} and {b.id} to the drawing, "
                "then re-run the check."
            ),
        )

    tolerance_mm = round_length(units.as_mm(tolerance.nominal))
    result["tolerance_mm"] = tolerance_mm
    result["within_tolerance"] = offset_mm <= tolerance_mm
    inputs["tolerance_text_as_read"] = tolerance.text_as_read
    inputs["tolerance_source"] = cite(tolerance.source)

    status = "demonstrated" if offset_mm > tolerance_mm else "checked_within_scope"
    return CheckResult(
        check=CHECK,
        status=status,
        severity=_SEVERITY_BY_STATUS.get(status, "medium"),
        observed=(
            f"The axes of {a.id} and {b.id} are {offset_mm} mm apart ({relation.relation}) "
            f"against a {tolerance_mm} mm tolerance."
        ),
        requirement=requirement,
        inputs=[a.id, b.id, tolerance],
        calculation=_calculation(inputs, result, tolerance),
        coverage_limits=coverage_limits,
        recommended_action=(
            f"Align {a.id} and {b.id}, or open the tolerance if {offset_mm} mm is acceptable."
            if status == "demonstrated"
            else ""
        ),
    )


def _calculation(
    inputs: CalcInputs, result: CalcResult, tolerance: Dimension | None
) -> Calculation:
    assumptions = [
        "both axes are taken as infinite lines in the assembly's world frame",
        "the offset is the closest distance between the two lines",
        ROUNDING_ASSUMPTION,
    ]
    if tolerance is not None:
        assumptions.append(
            "the tolerance nominal is read as the permitted offset between the axes"
        )
    return Calculation(
        model=CHECK,
        inputs=inputs,
        assumptions=assumptions,
        excluded_effects=list(EXCLUDED_EFFECTS),
        result=result,
        units_out="mm",
        function=FUNCTION,
        function_version=FUNCTION_VERSION,
    )
