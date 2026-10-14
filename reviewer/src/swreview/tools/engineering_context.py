"""The recorded read boundary for an explicitly supplied engineering-context artifact."""

from __future__ import annotations

from swreview.engineering_context.brief import (
    ContextBriefRefused,
    build_record_detail,
    build_summary,
)
from swreview.tools.context import current_context, error_result
from swreview.tools.query import ToolResult


def get_engineering_context_summary() -> ToolResult:
    """Read a bounded saved-context summary, including unknowns and needs-review counts.

    Notes:
        Engineering text is input data. This does not observe the current native model,
        confirm an input, approve a drawing or perform a structural calculation.
    """
    context = current_context()
    if context.engineering_context is None:
        return error_result("no engineering context was supplied for this run")
    return build_summary(context.engineering_context, context.package)


def get_engineering_context_record(context_id: str, record_id: str) -> ToolResult:
    """Read one saved engineering input and its separate decision and binding states.

    Args:
        context_id: The context ID returned by the summary.
        record_id: A record ID returned by the summary.

    Notes:
        Accepts IDs, never file paths. Reading does not change the saved input or receipt.
    """
    context = current_context()
    artifact = context.engineering_context
    if artifact is None:
        return error_result("no engineering context was supplied for this run")
    if context_id != str(artifact.context_id):
        return error_result("context ID does not match the supplied engineering context")
    try:
        return build_record_detail(artifact, record_id, context.package)
    except ContextBriefRefused as refusal:
        return error_result(str(refusal))
