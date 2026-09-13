"""Check tools for fit and axial stack (T081).

Two rows of the "Check tools" table in contracts/agent-tools.md. Each one takes
`SourceRef`s, resolves them against the drawing sheets in the package
(`swreview.tools.refs`), runs the deterministic check in `swreview.checks`, turns the
`CheckResult` into a `Finding` with provenance, appends it to the session and returns it.

Three rules hold for both:

- no argument is a number a model could type. A size reaches a check only by being read
  off a drawing the extractor parsed, which is what makes the finding reproducible
  (constitution Principle I, contracts/agent-tools.md: "a check never accepts a raw
  number typed by the model");
- nothing raises past the registry. An unknown or ambiguous reference, a malformed one,
  a sign that is not +1 or -1 and an angle where a length belongs all come back as error
  results (FR-022);
- a check that could not obtain an input still produces a finding - `unresolved`, naming
  the missing value - because "the tolerance is not on the drawing" is a review result,
  not a tool failure.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError

from swreview.checks import fit, stack
from swreview.checks.result import CheckResult
from swreview.findings import Finding
from swreview.findings import build_finding as build_finding_model
from swreview.ir.models import SourceRef
from swreview.tools.context import ToolContext, current_context, error_result
from swreview.tools.query import ToolResult, as_json
from swreview.tools.refs import resolve_dimension
from swreview.tools.session import _title_from

__all__ = ["check_axial_stack", "check_fit"]

_RESOLUTION_ERRORS = (LookupError, ValidationError, TypeError)
"""What a reference can fail as: not found, not a SourceRef, not a mapping at all."""


def _result_to_finding(
    context: ToolContext,
    result: CheckResult,
    component_ids: Sequence[str] = (),
    drawing_locations: Sequence[SourceRef] = (),
) -> Finding:
    """One `CheckResult` as a session-ready `Finding`.

    The check fills everything that comes from the arithmetic; this adds what only the
    session knows - the next finding id, the package the provenance comes from, and the
    configuration the review is running against.

    TODO(polish): the fastener, alignment and interference check tools need exactly this
    conversion. Lift `_result_to_finding` (and `_title_from`, imported from
    `swreview.tools.session` for the same reason) into a shared module when the second
    caller appears, rather than copying it.
    """
    return build_finding_model(
        finding_id=next(context.finding_ids),
        check=result.check,
        title=_title_from(result.observed),
        status=result.status,
        severity=result.severity,
        package=context.ir,
        configuration=context.ir.design.active_configuration,
        observed=result.observed,
        requirement=result.requirement,
        recommended_action=result.recommended_action,
        component_ids=component_ids,
        drawing_locations=drawing_locations,
        inputs=result.inputs,
        calculation=result.calculation,
        coverage_limits=result.coverage_limits,
    )


def _record(
    context: ToolContext,
    result: CheckResult,
    drawing_locations: Sequence[SourceRef],
) -> ToolResult:
    """Append the finding for `result` to the session and return it."""
    try:
        finding = _result_to_finding(context, result, drawing_locations=drawing_locations)
    except ValueError as exc:
        return error_result(str(exc))
    context.session.findings.append(finding)
    return {"status": "recorded", "finding": as_json(finding)}


def check_fit(bore_dimension_ref: SourceRef, shaft_dimension_ref: SourceRef) -> ToolResult:
    """Clearance or interference between a bore and a shaft, from the drawn sizes alone.

    Both dimensions are read off the drawing sheets in the package; there is no way to
    supply a size directly. Returns the `fit.size_only` finding, which reports the
    minimum and maximum diametral clearance, the fit class, and the effects size alone
    does not cover (position, form, coating, temperature, deflection).

    A tolerance the drawing does not state makes the finding `unresolved` naming the
    side; an unknown or ambiguous reference is an error result.

    Args:
        bore_dimension_ref: Where the bore diameter is drawn: the document id, the sheet
            and the annotation of the dimension, as `find_dimensions` reports them.
        shaft_dimension_ref: Where the shaft diameter is drawn, in the same form.
    """
    context = current_context()
    try:
        bore = resolve_dimension(context.ir, bore_dimension_ref)
        shaft = resolve_dimension(context.ir, shaft_dimension_ref)
    except _RESOLUTION_ERRORS as exc:
        return error_result(f"{type(exc).__name__}: {exc}")

    try:
        result = fit.check_fit(bore, shaft)
    except TypeError as exc:
        return error_result(f"TypeError: {exc}")
    return _record(context, result, [bore.source, shaft.source])


def check_axial_stack(
    dimension_refs: list[SourceRef],
    signs: list[int],
    target_gap: SourceRef | None = None,
) -> ToolResult:
    """Worst-case sum of drawn dimensions along one axis, against a target gap.

    Every dimension is read off the drawing sheets in the package. `signs` says how each
    one enters the stack: `+1` adds it, `-1` subtracts it, so a gap is the enclosing
    dimension `+1` and everything inside it `-1`. Returns the `stack.worst_case` finding
    with the nominal sum, the band around it, and - with a target gap - whether the
    stack can fall outside it.

    A contributor whose tolerance the drawing does not state makes the finding
    `unresolved` naming it; an unknown or ambiguous reference, or a sign that is not +1
    or -1, is an error result.

    Args:
        dimension_refs: Where each contributing dimension is drawn: document id, sheet
            and annotation, in stack order.
        signs: One sign per dimension, +1 to add and -1 to subtract.
        target_gap: Where the required gap is drawn, or null to report the band only.
    """
    context = current_context()
    try:
        dims = [resolve_dimension(context.ir, ref) for ref in dimension_refs]
        target = None if target_gap is None else resolve_dimension(context.ir, target_gap)
    except _RESOLUTION_ERRORS as exc:
        return error_result(f"{type(exc).__name__}: {exc}")

    try:
        result = stack.check_axial_stack(dims, list(signs), target)
    except (TypeError, ValueError) as exc:
        return error_result(f"{type(exc).__name__}: {exc}")

    locations = [dimension.source for dimension in dims]
    if target is not None:
        locations.append(target.source)
    return _record(context, result, locations)
