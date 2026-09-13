"""Worst-case axial stack (T080, `stack.worst_case`).

Signed nominal sum, and a tolerance band made by adding every contributor's tolerance
magnitude on the side that moves the result away from nominal. Worst case is the
arithmetic an engineer can check by hand and the only one that cannot understate the
band, which is what a review needs; a statistical (RSS) stack would be narrower and is
not what this check computes.
"""

from __future__ import annotations

from swreview.checks.result import (
    ROUNDING_ASSUMPTION,
    CheckResult,
    Limits,
    MissingToleranceError,
    cite,
    dimension_inputs,
    limits_mm,
    require_length,
    round_length,
    unresolved,
)
from swreview.findings import Calculation
from swreview.ir.models import Angle, Dimension, Quantity

__all__ = ["CHECK", "EXCLUDED_EFFECTS", "check_axial_stack"]

CHECK = "stack.worst_case"
FUNCTION = "swreview.checks.stack.check_axial_stack"
FUNCTION_VERSION = "1"

EXCLUDED_EFFECTS = [
    "geometric position and orientation tolerance (perpendicularity, flatness datums)",
    "form error of the mating faces",
    "temperature",
    "deformation under load, clamping or fastener preload",
    "statistical distribution: this is worst case, not an RSS stack",
]

COVERAGE_LIMIT = (
    f"{CHECK} summed sizes along one axis; {', '.join(EXCLUDED_EFFECTS)} were not evaluated"
)


def check_axial_stack(
    dims: list[Dimension], signs: list[int], target: Dimension | None
) -> CheckResult:
    """Worst-case sum of `dims` along one axis, each taken with its sign in `signs`.

    `+1` adds a dimension to the stack, `-1` subtracts it, so a gap is written as the
    enclosing dimension `+1` and everything inside it `-1`. The result is the nominal
    sum with a band around it: `tolerance_plus_mm` is the sum of each contributor's
    deviation towards a larger result, `tolerance_minus_mm` the sum towards a smaller
    one, so `min_mm` and `max_mm` are the extremes reachable when every part is at a
    limit at the same time.

    With a `target`, the stack is compared against the target's own limits and the
    result is `demonstrated` when the stack can fall outside them - the numbers show a
    requirement that can be missed, which is the one case this check can prove. Inside
    the target, or with no target at all, the result is `checked_within_scope` and the
    band is reported for the engineer.

    A dimension whose tolerance carries no limits (kind `none` or `basic`, or a missing
    value) makes the whole stack `unresolved`, naming the index and the text as read: a
    stack with an unknown contributor has no worst case (Principle I). A tolerance that
    came from a general note is used as it stands and cited in `assumptions`, since
    `Tolerance.source` records where it was read.

    Raises `ValueError` for an empty stack, a sign per dimension missing, or a sign that
    is not `+1` or `-1`, and `TypeError` for an angular dimension.
    """
    if not dims:
        raise ValueError("an axial stack needs at least one dimension")
    if len(signs) != len(dims):
        raise ValueError(f"got {len(signs)} signs for {len(dims)} dimensions; one sign each")
    unexpected = [sign for sign in signs if sign not in (1, -1)]
    if unexpected:
        raise ValueError(f"signs must be +1 or -1; got {unexpected}")

    for index, dimension in enumerate(dims):
        require_length(dimension, f"dimension {index} ({dimension.text_as_read!r})")
    if target is not None:
        require_length(target, f"target gap ({target.text_as_read!r})")

    inputs = [*dims, target] if target is not None else list(dims)
    requirement = _requirement(target)

    limits: list[Limits] = []
    for index, dimension in enumerate(dims):
        try:
            limits.append(limits_mm(dimension))
        except MissingToleranceError as error:
            return unresolved(
                CHECK,
                f"the tolerance for dimension {index} {dimension.text_as_read!r} "
                f"({cite(dimension.source)}; {error})",
                inputs,
                requirement=requirement,
                recommended_action=(
                    f"Add limits to {dimension.text_as_read!r}, or supply the general "
                    "note that governs it, then re-run the stack."
                ),
            )

    target_limits: Limits | None = None
    if target is not None:
        try:
            target_limits = limits_mm(target)
        except MissingToleranceError as error:
            return unresolved(
                CHECK,
                f"the limits of the target gap {target.text_as_read!r} "
                f"({cite(target.source)}; {error})",
                inputs,
                requirement=requirement,
                recommended_action=(
                    "Tolerance the target gap on the drawing, then re-run the stack."
                ),
            )

    if target is not None and target_limits is not None:
        requirement = (
            f"Target gap {target.text_as_read!r} ({cite(target.source)}): "
            f"{target_limits.min_mm} mm to {target_limits.max_mm} mm"
        )

    nominal_mm = round_length(
        sum(sign * limit.nominal_mm for sign, limit in zip(signs, limits, strict=True))
    )
    plus_mm = round_length(
        sum(_towards_larger(sign, limit) for sign, limit in zip(signs, limits, strict=True))
    )
    minus_mm = round_length(
        sum(_towards_smaller(sign, limit) for sign, limit in zip(signs, limits, strict=True))
    )
    min_mm = round_length(nominal_mm - minus_mm)
    max_mm = round_length(nominal_mm + plus_mm)

    result: dict[str, Quantity | bool | str | float] = {
        "nominal_mm": nominal_mm,
        "min_mm": min_mm,
        "max_mm": max_mm,
        "tolerance_plus_mm": plus_mm,
        "tolerance_minus_mm": minus_mm,
    }
    observed = (
        f"Worst-case stack of {len(dims)} dimensions: {nominal_mm} mm nominal, "
        f"{min_mm} mm to {max_mm} mm"
    )
    status = "checked_within_scope"
    severity = "info"
    action = (
        "None from the stack itself; supply the target gap if one is specified so the "
        "band can be compared against it."
        if target_limits is None
        else "None; the stack stays inside the target gap at both limits."
    )

    if target_limits is not None:
        violates = min_mm < target_limits.min_mm or max_mm > target_limits.max_mm
        result["target_min_mm"] = target_limits.min_mm
        result["target_max_mm"] = target_limits.max_mm
        result["violates_target"] = violates
        if violates:
            status = "demonstrated"
            severity = "high"
            observed += (
                f", outside the target gap {target_limits.min_mm} mm to "
                f"{target_limits.max_mm} mm"
            )
            action = (
                f"The stack reaches {min_mm} mm to {max_mm} mm against a target of "
                f"{target_limits.min_mm} mm to {target_limits.max_mm} mm: tighten the "
                "contributing tolerances, change a nominal, or widen the target."
            )
        else:
            observed += (
                f", inside the target gap {target_limits.min_mm} mm to "
                f"{target_limits.max_mm} mm"
            )

    calculation_inputs: dict[str, Quantity | Angle | str] = {}
    for index, (sign, dimension, limit) in enumerate(zip(signs, dims, limits, strict=True)):
        prefix = f"dim_{index}"
        calculation_inputs[f"{prefix}_sign"] = "+1" if sign > 0 else "-1"
        calculation_inputs.update(dimension_inputs(prefix, dimension, limit))
    if target is not None and target_limits is not None:
        calculation_inputs.update(dimension_inputs("target", target, target_limits))

    return CheckResult(
        check=CHECK,
        status=status,
        severity=severity,
        observed=observed,
        requirement=requirement,
        inputs=inputs,
        calculation=Calculation(
            model=CHECK,
            inputs=calculation_inputs,
            assumptions=[
                "worst case: every dimension is at the limit that moves the result "
                "furthest from nominal, all at the same time",
                "all dimensions act along one axis and add directly, as signed",
                ROUNDING_ASSUMPTION,
                *_tolerance_source_notes(dims),
            ],
            excluded_effects=list(EXCLUDED_EFFECTS),
            result=result,
            units_out="mm",
            function=FUNCTION,
            function_version=FUNCTION_VERSION,
        ),
        coverage_limits=[COVERAGE_LIMIT],
        recommended_action=action,
    )


def _towards_larger(sign: int, limit: Limits) -> float:
    """How far this contributor can push the stack above its nominal contribution."""
    return limit.upper_deviation_mm if sign > 0 else -limit.lower_deviation_mm


def _towards_smaller(sign: int, limit: Limits) -> float:
    """How far this contributor can push the stack below its nominal contribution."""
    return -limit.lower_deviation_mm if sign > 0 else limit.upper_deviation_mm


def _requirement(target: Dimension | None) -> str:
    if target is None:
        return (
            "No target gap was supplied; the stack is reported for the engineer to "
            "compare against the requirement"
        )
    return (
        f"Target gap {target.text_as_read!r} ({cite(target.source)}) as drawn, "
        "compared against the worst-case stack"
    )


def _tolerance_source_notes(dims: list[Dimension]) -> list[str]:
    """Cite every tolerance that was not read from the dimension itself.

    A general note tolerance is usable evidence, but only if the report says where it
    came from, so the engineer can confirm the note governs that dimension.
    """
    notes: list[str] = []
    for index, dimension in enumerate(dims):
        if dimension.tolerance.source != dimension.source:
            notes.append(
                f"dimension {index} {dimension.text_as_read!r} takes its tolerance from "
                f"{cite(dimension.tolerance.source)}, not from the dimension itself"
            )
    return notes
