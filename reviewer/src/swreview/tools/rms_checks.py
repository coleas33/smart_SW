"""The Resilient Modeling check tools: the family's entry point for the model (T028).

One function per row of the check table in `specs/003-resilient-modeling/contracts/tools.md`.
A check tool here is deliberately thin, because everything it would otherwise do already
has one home:

- `checks/rms/part.py` decides what each rule concludes about one document;
- `checks/rms/report.py` turns those conclusions into findings, exceptions and aggregated
  coverage, identically for all three tools;
- `checks/rms/groups.py` and `checks/rms_types.py` supply the derived answers, which is
  what keeps `list_features` and `check_rms_part` from disagreeing about the same tree.

What is left - and what this module is - is the dispatch decision: *which* documents a
call evaluates. Two rules govern it (constitution Principle I):

- `document_id=null` is every part document of the package, in package order, **including
  the ones whose tree was never read**. A suppressed component's part is unresolved for
  every part- and equation-scope rule, which is a different statement from "not in the
  report" and is the one the report has to carry;
- an id that names no document, or names an assembly, is an error result. A part check
  dispatched over nothing would write an empty run that reads like a clean part.
"""

from __future__ import annotations

from collections.abc import Sequence

from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import evaluate_part
from swreview.checks.rms.report import report_results
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table
from swreview.tools.context import ToolContext, current_context, error_result, unknown_id
from swreview.tools.query import ToolResult

__all__ = ["check_rms_part", "part_documents", "run_part_checks"]

PART_KIND = "part"


def check_rms_part(document_id: str | None = None) -> ToolResult:
    """Grade one part's feature tree, or every part's, against the part-scope RMS rules.

    Each failing rule becomes one finding naming the features it is about, each passing,
    skipped or unresolved rule becomes one aggregated coverage item per bucket, and the
    `modeling.resilience` summary is rewritten from everything the session holds. Each
    call re-evaluates its scope in full and replaces its own earlier *coverage* items, so
    running it twice leaves one coverage item per rule; findings are appended, as they are
    by every check tool, so a second call over a document you already graded adds a second
    finding for each of its conditions. Grade every part in one call - no argument - and
    re-grade a single document only when you mean to add findings for it.

    A `fail` outcome consults the retained exceptions for exactly these component
    instances, this configuration and this rule id: an `active` exception waives the
    finding and is cited on it, one whose feature tree has changed leaves the finding
    standing and says so. A `warn` outcome is advisory and never consults them.

    A part whose tree was never read - every instance lightweight, suppressed or unloaded
    - is unresolved for every part- and equation-scope rule, with the component state as
    the reason. It is never silently left out of the report.

    Args:
        document_id: Part document to grade; null grades every part document in the
            package, including the ones whose tree was not read.
    """
    return run_part_checks(
        current_context(), None if document_id is None else [document_id]
    )


def run_part_checks(
    context: ToolContext, document_ids: Sequence[str] | None = None
) -> ToolResult:
    """Grade `document_ids` (null = every part document) and write them to `context`.

    The tool above grades one document because that is the argument the model gets;
    `swreview check rms --document a --document b` grades several. Both end in one pass
    of `report_results`, and that matters rather than being a convenience: aggregated
    coverage is written through `replace_coverage`, so grading two documents as two calls
    would leave the second one's coverage and drop the first one's.
    """
    documents = part_documents(context, document_ids)
    if isinstance(documents, dict):
        return documents

    table = load_table()
    results: list[RuleResult] = []
    for part in documents:
        # Both `assign_groups` and `part_tree` walk the rows in `index` order themselves,
        # so the rows are handed over as the package carries them.
        rows = [row for row in context.ir.features if row.document_id == part]
        results.extend(evaluate_part(part, rows, table, assign_groups(rows, table), context.ir))

    reported = report_results(context, results)
    if "error" in reported:
        return reported
    return {**reported, "documents": documents}


def part_documents(
    context: ToolContext, document_ids: Sequence[str] | None
) -> list[str] | ToolResult:
    """The part documents to grade, or the error result explaining why it cannot.

    Without ids, package order: a caller reading the result - and the `document_ids` of
    every coverage item written from it - sees the documents in the order the package
    lists them rather than in whatever order the feature rows happen to arrive in. With
    ids, the caller's own order, because the caller named them.
    """
    parts = [
        document.document_id
        for document in context.ir.documents
        if document.kind == PART_KIND
    ]
    if document_ids is None:
        return parts
    selected: list[str] = []
    for document_id in document_ids:
        document = context.document(document_id)
        if document is None:
            return unknown_id("document", document_id)
        if document.kind != PART_KIND:
            return error_result(
                f"document {document_id!r} is a {document.kind} document; the part rules "
                f"grade part documents, and the part documents here are {parts}"
            )
        if document_id not in selected:
            selected.append(document_id)
    return selected
