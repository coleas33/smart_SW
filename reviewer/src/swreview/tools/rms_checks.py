"""The Resilient Modeling check tools: the family's entry point for the model (T028).

One function per row of the check table in `specs/003-resilient-modeling/contracts/tools.md`.
A check tool here is deliberately thin, because everything it would otherwise do already
has one home:

- `checks/rms/part.py`, `checks/rms/assembly.py` and `checks/rms/equations.py` decide what
  each rule concludes about one document;
- `checks/rms/report.py` turns those conclusions into findings, exceptions and aggregated
  coverage, identically for all three tools;
- `checks/rms/groups.py` and `checks/rms_types.py` supply the derived answers, which is
  what keeps `list_features` and `check_rms_part` from disagreeing about the same tree.

What is left - and what this module is - is the dispatch decision: *which* documents a
call evaluates. Three rules govern it (constitution Principle I):

- `document_id=null` is every part document of the package, in package order, **including
  the ones whose tree was never read**. A suppressed component's part is unresolved for
  every part- and equation-scope rule, which is a different statement from "not in the
  report" and is the one the report has to carry;
- an id that names no document, or names an assembly, is an error result. A part check
  dispatched over nothing would write an empty run that reads like a clean part;
- the assembly check takes no argument at all, because it has no choice to offer: the
  extractor reads the root assembly's mates and `Mate` carries no owning document, so
  `design.root_assembly_document_id` is the only document the assembly rules can grade.
  The subassembly documents are not graded and not dropped either - `report_results`
  writes them as the `rms.assembly.subassemblies` item that names them. That id is
  whatever document the dump was rooted at, so in a part-only package it names a *part*:
  the mirror of the guard above is that the assembly rules are then unresolved for it by
  name rather than graded over it, because "the root assembly has no mates" said of a part
  is a claim about an assembly this package does not carry. It is not an error result -
  there is no argument to have got wrong, and `--scope all` over a part-only dump is a
  legitimate run.
"""

from __future__ import annotations

from collections.abc import Sequence

from swreview.checks.rms.assembly import assembly_rules_unresolved, evaluate_assembly
from swreview.checks.rms.equations import evaluate_equations
from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import evaluate_part
from swreview.checks.rms.report import report_results
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table
from swreview.tools.context import ToolContext, current_context, error_result, unknown_id
from swreview.tools.query import ToolResult

__all__ = [
    "check_rms_assembly",
    "check_rms_equations",
    "check_rms_part",
    "part_documents",
    "run_assembly_checks",
    "run_equation_checks",
    "run_part_checks",
]

PART_KIND = "part"
ASSEMBLY_KIND = "assembly"

NO_ROOT_ASSEMBLY = (
    "{document_id} is a {kind} document; this package has no root assembly, so the "
    "assembly rules were not evaluated"
)
NO_ROOT_DOCUMENT = (
    "the package has no document {document_id}, which design.root_assembly_document_id "
    "names, so the assembly rules were not evaluated"
)


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

    return _reported(context, results, documents)


def check_rms_assembly() -> ToolResult:
    """Grade the root assembly's mates and components against the assembly-scope RMS rules.

    Four rules: the mates reference planes, axes, points or coordinate systems rather than
    faces, edges or vertices (`fail`); the first component is fixed or fully constrained
    (`fail`); no component is more than three mates from the fixed root (`warn`); and
    Toolbox hardware is inserted as parts rather than as configurations of one file
    (`warn`). Each failing rule becomes one finding naming the mates and components it is
    about, everything else becomes one aggregated coverage item per rule per bucket, and
    the `modeling.resilience` summary is rewritten from everything the session holds.

    There is no argument because there is no choice: only the root assembly document's
    mates are extracted, so that is the one document these rules can grade. The
    subassemblies are reported as unresolved by name rather than passed over.

    A package with no assembly document - a part-only dump, where the root document id
    names the part - grades nothing: `documents` comes back empty and all four rules are
    unresolved, naming that document and its kind. Nothing is claimed about an assembly
    this package does not carry.

    A `fail` outcome consults the retained exceptions for the root assembly instance, this
    configuration and this rule id; a `warn` outcome is advisory and never does. Calling
    this twice replaces its coverage and appends a second copy of every finding, so call
    it once.
    """
    return run_assembly_checks(current_context())


def run_assembly_checks(context: ToolContext) -> ToolResult:
    """Grade the root assembly document of `context` and write the results to it.

    The CLI's counterpart to the tool above, and the same shape as `run_part_checks`
    without the document selection: `swreview check rms --document` narrows the *part*
    documents, and there is nothing here for it to narrow.

    `design.root_assembly_document_id` is `DocumentIds.For(tree.RootDocumentPath)` -
    whatever document the dump was rooted at - so it names a part in a part-only package.
    There is no root assembly to grade then: every assembly rule is unresolved, naming that
    document and its kind, and no document is reported as graded.
    """
    document_id = context.ir.design.root_assembly_document_id
    document = context.document(document_id)
    if document is None or document.kind != ASSEMBLY_KIND:
        reason = (
            NO_ROOT_DOCUMENT.format(document_id=document_id)
            if document is None
            else NO_ROOT_ASSEMBLY.format(document_id=document_id, kind=document.kind)
        )
        results = assembly_rules_unresolved(document_id, reason)
        documents: list[str] = []
    else:
        results = evaluate_assembly(context.ir, load_table())
        documents = [document_id]

    return _reported(context, results, documents)


def check_rms_equations(document_id: str | None = None) -> ToolResult:
    """Grade one part's equation manager, or every part's, against the equation rules.

    The same two rules for every part document: at least one global variable exists
    (`fail`), and at least one dimension is driven by an equation (`warn`). A manager that
    was read and holds nothing is an answer and becomes those two outcomes; a manager
    nobody could read - the `equations` gap, or a row whose global flag threw - is
    unresolved instead, because "this part has no global variables" is a claim about data
    someone actually saw (constitution Principle I).

    Dispatch, exceptions, coverage and the effect of calling it twice are `check_rms_part`'s
    exactly: null grades every part document including the ones whose tree was never read,
    a `fail` outcome consults the retained exceptions for this rule id, coverage is
    replaced and findings are appended.

    Args:
        document_id: Part document whose equations to grade; null grades every part
            document in the package.
    """
    return run_equation_checks(
        current_context(), None if document_id is None else [document_id]
    )


def run_equation_checks(
    context: ToolContext, document_ids: Sequence[str] | None = None
) -> ToolResult:
    """Grade `document_ids` (null = every part document) and write them to `context`.

    The equation twin of `run_part_checks`, and deliberately its shape rather than a
    parameter on it: the two scopes are two rows of `contracts/tools.md` and two tools,
    so `swreview check rms --scope all` runs both and lands in two passes of
    `report_results` - which accumulate, because the aggregated items of one scope's rules
    are never the other's and the summary is read back off the session.
    """
    documents = part_documents(context, document_ids)
    if isinstance(documents, dict):
        return documents

    results: list[RuleResult] = []
    for part in documents:
        rows = [row for row in context.ir.equations if row.document_id == part]
        results.extend(evaluate_equations(part, rows, context.ir))

    return _reported(context, results, documents)


def _reported(
    context: ToolContext, results: Sequence[RuleResult], documents: Sequence[str]
) -> ToolResult:
    """`report_results` plus the documents the caller graded, for all three check tools.

    The three runners differ only in which rules they dispatch and over what; what they do
    with the results afterwards is one thing and is written once (constitution Principle
    V). An error result is handed straight back rather than having `documents` added to
    it: the caller has to be able to tell "this call reported nothing" from "this call
    graded nothing", and an error result carrying a document list reads as the second.
    """
    reported = report_results(context, results)
    if "error" in reported:
        return reported
    return {**reported, "documents": list(documents)}


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
