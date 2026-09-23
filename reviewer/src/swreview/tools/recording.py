"""One `CheckResult` becomes one session `Finding`, in one place.

Every check tool ends the same way: run a deterministic check, turn its `CheckResult`
into a `Finding` with the provenance only the session knows, append it, and hand it back.
That conversion lived in `swreview.tools.checks_fit` while fit and stack were the only
check tools; the fastener, alignment and interference tools need exactly the same thing,
so it lives here instead of being copied four times.

What the conversion adds to a `CheckResult` is what a check cannot know: the next finding
id in this session, the manifest provenance of the documents the finding touches, and the
configuration the review is running against. What it never adds is a number: everything
numeric comes from the check.
"""

from __future__ import annotations

from collections.abc import Sequence

from swreview.checks.result import CheckResult
from swreview.findings import Finding
from swreview.findings import build_finding as build_finding_model
from swreview.ir.models import SourceRef
from swreview.report.session import CoverageItem, CoverageScope

# The recorded title every check tool's result carries lives in `report/titles.py`, beside the
# display title that undoes its cut (feature 009 decision 2A); re-exported here unchanged.
from swreview.report.titles import TITLE_LENGTH, title_from
from swreview.tools.context import ToolContext, error_result
from swreview.tools.query import ToolResult, as_json

__all__ = [
    "TITLE_LENGTH",
    "out_of_scope",
    "record_result",
    "record_results",
    "result_to_finding",
    "title_from",
]


def result_to_finding(
    context: ToolContext,
    result: CheckResult,
    component_ids: Sequence[str] = (),
    drawing_locations: Sequence[SourceRef] = (),
    exception_id: str | None = None,
    tool_result_ids: Sequence[int] = (),
    document_ids: Sequence[str] = (),
) -> Finding:
    """One `CheckResult` as a session-ready `Finding`.

    The check fills everything that comes from the arithmetic; this adds what only the
    session knows - the next finding id, the package the provenance comes from, and the
    configuration the review is running against.

    `tool_result_ids` are the investigation steps whose results the finding rests on -
    `ToolContext.current_step_id` for a check that produces one. A check whose evidence is
    the model itself rather than arithmetic (an RMS rule reading a feature tree) carries no
    `Calculation`, and `build_finding` accepts a numeric status from it only when a step id
    says where the evidence came from.

    Raises `ValueError` when the evidence rules of data-model.md section 3 are not met
    (an unresolved result with no coverage limit, a finding naming nothing at all, a
    numeric result with neither a calculation nor a step id).
    """
    return build_finding_model(
        finding_id=next(context.finding_ids),
        check=result.check,
        title=title_from(result.observed),
        status=result.status,
        severity=result.severity,
        package=context.ir,
        configuration=context.ir.design.active_configuration,
        observed=result.observed,
        requirement=result.requirement,
        recommended_action=result.recommended_action,
        component_ids=component_ids,
        drawing_locations=drawing_locations,
        document_ids=document_ids,
        inputs=result.inputs,
        calculation=result.calculation,
        tool_result_ids=tool_result_ids,
        coverage_limits=result.coverage_limits,
        exception_id=exception_id,
    )


def record_result(
    context: ToolContext,
    result: CheckResult,
    component_ids: Sequence[str] = (),
    drawing_locations: Sequence[SourceRef] = (),
    exception_id: str | None = None,
    tool_result_ids: Sequence[int] = (),
    document_ids: Sequence[str] = (),
) -> ToolResult:
    """Append the finding for `result` to the session and return it.

    `document_ids` binds a document-scoped finding - one whose document has no
    `ComponentInstance` by nature - to the document it was read from; see `build_finding`.
    """
    try:
        finding = result_to_finding(
            context,
            result,
            component_ids,
            drawing_locations,
            exception_id=exception_id,
            tool_result_ids=tool_result_ids,
            document_ids=document_ids,
        )
    except ValueError as exc:
        return error_result(str(exc))
    context.record_finding(finding)
    return {"status": "recorded", "finding": as_json(finding)}


def record_results(
    context: ToolContext,
    results: Sequence[CheckResult],
    component_ids: Sequence[str] = (),
    drawing_locations: Sequence[SourceRef] = (),
    tool_result_ids: Sequence[int] = (),
) -> ToolResult:
    """Append one finding per `CheckResult` and return them all.

    A check that produces several results - a fastener joint is four - is one tool call
    and one result, so the model sees the whole joint at once rather than four calls it
    has to correlate. They came from one call, so they all cite the same
    `tool_result_ids`.
    """
    findings = []
    for result in results:
        try:
            findings.append(
                result_to_finding(
                    context,
                    result,
                    component_ids,
                    drawing_locations,
                    tool_result_ids=tool_result_ids,
                )
            )
        except ValueError as exc:
            return error_result(str(exc))
    for finding in findings:
        context.record_finding(finding)
    return {"status": "recorded", "findings": [as_json(finding) for finding in findings]}


def out_of_scope(
    context: ToolContext,
    result: CheckResult,
    component_ids: Sequence[str] = (),
) -> dict[str, object]:
    """File a result the check declared out of scope in the `out_of_scope` bucket.

    A joint kind the pilot does not model is not a finding and is certainly not a pass:
    it is coverage saying the condition was seen and not evaluated (FR-024).
    """
    item = CoverageItem(
        check=result.check,
        scope=CoverageScope(
            component_ids=[
                component_id
                for component_id in component_ids
                if context.component(component_id) is not None
            ],
            configuration=context.ir.design.active_configuration,
        ),
        reason=result.observed,
        error=None,
    )
    context.record_coverage("out_of_scope", item)
    return {"status": "out_of_scope", "coverage_item": as_json(item)}
