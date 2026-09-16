"""`RuleResult` lists become session findings and coverage, in one place (T022).

The three `check_rms_*` tools differ only in which rules they dispatch; everything that
happens to the results afterwards is the same, and `specs/003-resilient-modeling/
data-model.md` section 2 ("Subjects to Finding fields", "Coverage aggregation") words it
once. `report_results` is that once, so a rule author never writes a `Finding` and a tool
author never writes a `CoverageItem`.

What it does, in the order it does it:

1. **findings.** A `fail`, `warn` or `waived` result becomes one finding through
   `tools/recording.py`. The subject document's every `ComponentInstance` is its
   `component_ids`, in package order - the root assembly's own instance is `cmp:0001` -
   and a document with no instance at all yields unresolved coverage instead, because a
   finding that names no component is not a finding and an invented id is worse
   (constitution Principle I). The finding carries `tool_result_ids=[current_step_id]`
   and no `Calculation`: an RMS rule's evidence is the tree the model was shown.
2. **exceptions.** Only a `fail` outcome asks the store, and it asks with
   `check=<rule id>` so one document's instances cannot hand an interference waiver to a
   sketch rule. `active` waives the finding, `needs_review` leaves it standing with the
   marker (`contracts/tools.md`, "Exceptions"). `warn` never asks.
3. **coverage.** One item per rule per bucket, written through
   `ToolContext.replace_coverage`, so a tool called twice leaves one item and not two;
   then the `rms.types.unknown` item when a type name was not in the calibrated table,
   the ten never-dispatched rules once per session, and last the `modeling.resilience`
   summary, which is read back off the session so the three tools accumulate into one
   answer rather than overwriting each other's.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from swreview.checks.result import CheckResult
from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.registry import RULES, coverage_only
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table, unknown_types
from swreview.exceptions import ReviewException
from swreview.ir.models import EvidencePackage, SourceRef
from swreview.report.session import CoverageBucket, CoverageItem, CoverageScope, ReviewSession
from swreview.tools.context import ToolContext
from swreview.tools.query import ToolResult
from swreview.tools.recording import record_result

__all__ = ["NO_PERSIST_REF", "SUMMARY_CHECK", "UNKNOWN_TYPES_CHECK", "report_results"]

SUMMARY_CHECK = "modeling.resilience"
"""The checklist item these rules answer; its coverage item is the one-line verdict on
the whole method for this review (`agent/checklist_v1.yaml`)."""

UNKNOWN_TYPES_CHECK = "rms.types.unknown"
"""Not a rule: the census of `GetTypeName2` names the shipped table does not know, which
is how a recalibration finds out what it is missing (`contracts/rules.md`, "Content
features")."""

CONFIGURATION_GAP = "feature_tree_configuration"

NO_PERSIST_REF = (
    "no persistent reference was read for this subject, so it cannot be selected in "
    "SOLIDWORKS"
)
"""Why a subject has no `SourceRef` and no reference in its entry. Said once, on the
subject it is about: a Show button that reported success while selecting nothing is the
failure D3 exists to remove, and a silently missing subject would be the same failure one
layer earlier."""

_BUCKET_BY_OUTCOME: dict[str, CoverageBucket] = {
    "pass": "checked",
    "skip": "skipped",
    "unresolved": "unresolved",
}
"""The three outcomes that are coverage rather than a finding (data-model section 2)."""

_SUMMARY_BUCKETS: tuple[CoverageBucket, ...] = ("checked", "unresolved")
"""The two buckets the summary can be in. It is one item that moves between them, which
`replace_coverage` - same check, same bucket - cannot express on its own."""


def report_results(context: ToolContext, results: Sequence[RuleResult]) -> ToolResult:
    """Write `results` to the session as findings and coverage; report what was written.

    Returns the recording envelope every check tool returns - `{"status": "recorded",
    "findings": [...]}` - with the coverage items this call wrote, or the first error
    result a finding could not be built from.
    """
    session = context.require_session()
    findings: list[dict[str, object]] = []
    subjects: dict[str, list[dict[str, object]]] = {}
    coverage: list[dict[str, str]] = []

    reportable, unreportable = _split_by_reportability(context, results)
    groups = _groups_by_document(context.ir, [result.document_id for result, _ in reportable])
    for result, check_result in reportable:
        recorded = _record(context, result, check_result, groups)
        if "error" in recorded:
            return recorded
        finding = recorded["finding"]
        findings.append(finding)  # type: ignore[arg-type]
        subjects[finding["id"]] = recorded["subjects"]  # type: ignore[index, assignment]

    configuration = context.ir.design.active_configuration
    for bucket, item in _aggregate([*results, *unreportable], configuration):
        context.replace_coverage(item.check, bucket, item)
        coverage.append({"bucket": bucket, "check": item.check})

    coverage.extend(_write_unknown_types(context, results))
    coverage.extend(_write_undispatched(context, session))
    coverage.append(_write_summary(context, session))
    return {
        "status": "recorded",
        "findings": findings,
        "subjects": subjects,
        "coverage": coverage,
    }


# --- 1. findings ------------------------------------------------------------------


def _component_ids(package: EvidencePackage, document_id: str) -> list[str]:
    """Every instance of `document_id`, in package order; empty when there is none."""
    return [
        component.id for component in package.components if component.document_id == document_id
    ]


def _split_by_reportability(
    context: ToolContext, results: Sequence[RuleResult]
) -> tuple[list[tuple[RuleResult, CheckResult]], list[RuleResult]]:
    """The finding-shaped results, split into those whose document has an instance and
    those whose does not: the latter are unresolved coverage, never an invented id."""
    reportable: list[tuple[RuleResult, CheckResult]] = []
    unreportable: list[RuleResult] = []
    for result in results:
        if result.result is None:
            continue
        if _component_ids(context.ir, result.document_id):
            reportable.append((result, result.result))
        else:
            unreportable.append(
                RuleResult(
                    rule_id=result.rule_id,
                    document_id=result.document_id,
                    outcome="unresolved",
                    subjects=list(result.subjects),
                    subject_rows=tuple(result.subject_rows),
                    reason=f"no component instance for {result.document_id}",
                )
            )
    return reportable, unreportable


def _record(
    context: ToolContext,
    result: RuleResult,
    body: CheckResult,
    groups: Mapping[tuple[str, str], str | None],
) -> ToolResult:
    """One finding-shaped result as a session finding, exceptions applied.

    The subjects the rule named are emitted twice here (D2): as one `SourceRef` each on
    the finding, which is what both pages build their Show payload from, and as the
    structured entries returned beside the finding for the route's response. One builder,
    two consumers, and neither of them parses the display string in `inputs`.
    """
    package = context.ir
    component_ids = _component_ids(package, result.document_id)
    check_result = _with_configuration_limit(package, result.document_id, body)

    exception = _exception_for(context, result, component_ids)
    if exception is not None and exception.status == "active":
        check_result = _waived(check_result, exception)
    elif exception is not None:
        check_result = _needs_review(check_result, exception)

    recorded = record_result(
        context,
        check_result,
        component_ids=component_ids,
        drawing_locations=_source_refs(result),
        exception_id=None if exception is None else exception.id,
        tool_result_ids=[context.current_step_id],
    )
    if "error" in recorded:
        return recorded
    return {**recorded, "subjects": _subjects(result, component_ids, groups)}


def _source_refs(result: RuleResult) -> list[SourceRef]:
    """One source reference per subject that has one, in the order the rule named them.

    `document_id` is the subject's persist-ref scope - the document the reference resolves
    against, which for a part feature reached through an assembly is the part - because
    that is what `SwEntityResolver` needs to open the right document before selecting. A
    reference the extractor could not read produces nothing: an invented locator would
    make Show report success and select the wrong thing (Principle I).
    """
    return [
        SourceRef(document_id=row.persist_ref_scope, persist_ref=row.persist_ref)
        for row in result.subject_rows
        if row.persist_ref and row.persist_ref_scope
    ]


def _subjects(
    result: RuleResult,
    component_ids: Sequence[str],
    groups: Mapping[tuple[str, str], str | None],
) -> list[dict[str, object]]:
    """The structured subjects of one finding (`contracts/model-check.md`, `CheckResult`).

    Deliberately *not* a field on `Finding`: the feature 001 finding contract does not
    move for User Story 6 (FR-026), so this travels beside the finding, keyed by its id,
    and a consumer that only knows feature 001 sees exactly what it always saw.

    `group` is null for a subject that is not a feature of a graded part document - a mate
    and a component instance are subjects too, and neither is in a group. `component_ids`
    is the finding's own: an exception binds to a part's instances, so a subject is shown
    through the same instances the rule was graded on.
    """
    entries: list[dict[str, object]] = []
    for row in result.subject_rows:
        readable = bool(row.persist_ref and row.persist_ref_scope)
        entries.append(
            {
                "feature_id": row.id,
                "name": row.name,
                "type_name": row.type_name,
                "group": groups.get((result.document_id, row.id)),
                "persist_ref": row.persist_ref if readable else None,
                "persist_ref_scope": row.persist_ref_scope if readable else None,
                "component_ids": list(component_ids),
                "reason": None if readable else NO_PERSIST_REF,
            }
        )
    return entries


def _groups_by_document(
    package: EvidencePackage, document_ids: Iterable[str]
) -> dict[tuple[str, str], str | None]:
    """Which group each feature of `document_ids` is in, keyed by (document, feature).

    `checks/rms/groups.py` is the one place group membership is decided, so this asks it
    rather than re-deriving anything; it is asked once per document per call rather than
    once per finding. Keyed by the pair because a feature id is unique within a document's
    tree, not across a package.
    """
    table = load_table()
    assigned: dict[tuple[str, str], str | None] = {}
    for document_id in dict.fromkeys(document_ids):
        rows = [row for row in package.features if row.document_id == document_id]
        if not rows:
            continue
        for feature_id, group in assign_groups(rows, table).by_feature_id.items():
            assigned[(document_id, feature_id)] = group
    return assigned


def _with_configuration_limit(
    package: EvidencePackage, document_id: str, result: CheckResult
) -> CheckResult:
    """Add `other configurations not read: <names>` when the document has that gap.

    The gap says the document is also used under configurations the dump did not read;
    which ones is the document's own `configurations` less the one the tree was read in,
    so the limit names them rather than repeating the extractor's prose.
    """
    if not any(
        gap.entity_kind == CONFIGURATION_GAP and gap.entity_id == document_id
        for gap in package.gaps
    ):
        return result
    document = next(
        (item for item in package.documents if item.document_id == document_id), None
    )
    if document is None:  # pragma: no cover - a gap names a document the package holds
        return result
    read = next(
        (row.configuration for row in package.features if row.document_id == document_id),
        document.active_configuration,
    )
    others = [name for name in document.configurations if name != read]
    if not others:  # pragma: no cover - the gap is written only when there are others
        return result
    return replace(
        result,
        coverage_limits=[
            *result.coverage_limits,
            f"other configurations not read: {', '.join(others)}",
        ],
    )


def _exception_for(
    context: ToolContext, result: RuleResult, component_ids: Sequence[str]
) -> ReviewException | None:
    """The retained exception for this `fail`, or `None`.

    A `warn` is advisory and is never waivable (`contracts/rules.md`, "Waivable rules"),
    so it is not even looked up: a store that happens to hold an exception with the same
    bindings must not quieten it.
    """
    if result.outcome != "fail":
        return None
    store = context.exception_store()
    if store is None:
        return None
    return store.match(
        context.ir,
        component_ids,
        context.ir.design.active_configuration,
        check=result.rule_id,
    )


def _waived(result: CheckResult, exception: ReviewException) -> CheckResult:
    """The same condition, accepted: `checked_within_scope` citing the exception."""
    return replace(
        result,
        status="checked_within_scope",
        severity="info",
        observed=(
            f"{result.observed}. Excepted by {exception.id}, accepted by "
            f"{exception.accepted_by} on {exception.accepted_at} for this feature tree "
            f"and configuration: {exception.note}"
        ),
        coverage_limits=[
            *result.coverage_limits,
            f"exception:{exception.id}: {exception.note}",
        ],
        recommended_action=(
            f"None while the feature tree is unchanged. Re-review {exception.id} if these "
            "features change."
        ),
    )


def _needs_review(result: CheckResult, exception: ReviewException) -> CheckResult:
    """The finding stands: the tree it was accepted for is not the tree that is here."""
    return replace(
        result,
        observed=(
            f"{result.observed}. Exception {exception.id} was accepted for this condition "
            f"but the feature tree it was bound to has changed, so it does not clear this "
            f"finding - needs re-review: {exception.id}"
        ),
        recommended_action=(
            f"Re-review exception {exception.id}: confirm the changed condition is still "
            f"intended and re-accept it, or retire it and fix the tree. "
            f"{result.recommended_action}"
        ),
    )


# --- 2. aggregated coverage -------------------------------------------------------


def _aggregate(
    results: Iterable[RuleResult], configuration: str
) -> list[tuple[CoverageBucket, CoverageItem]]:
    """One item per (rule, bucket), documents in the order the results named them."""
    documents: dict[tuple[str, CoverageBucket], list[str]] = {}
    reasons: dict[tuple[str, CoverageBucket], list[str]] = {}
    for result in results:
        bucket = _BUCKET_BY_OUTCOME.get(result.outcome)
        if bucket is None:
            continue
        key = (result.rule_id, bucket)
        seen = documents.setdefault(key, [])
        if result.document_id not in seen:
            seen.append(result.document_id)
        if result.reason is not None:
            reasons.setdefault(key, []).append(f"{result.document_id}: {result.reason}")

    items: list[tuple[CoverageBucket, CoverageItem]] = []
    for (check, bucket), document_ids in documents.items():
        detail = "; ".join(reasons.get((check, bucket), []))
        items.append(
            (
                bucket,
                CoverageItem(
                    check=check,
                    scope=CoverageScope(
                        document_ids=list(document_ids), configuration=configuration
                    ),
                    reason=f"{len(document_ids)} document(s)" + (f": {detail}" if detail else ""),
                    error=None,
                ),
            )
        )
    return items


# --- 3. the census, the undispatched rules, and the summary -----------------------


def _write_unknown_types(
    context: ToolContext, results: Sequence[RuleResult]
) -> list[dict[str, str]]:
    """The `rms.types.unknown` item over the documents this call evaluated, or nothing.

    What counts as unclassified is `checks/rms_types.unknown_types`, which `swreview rms
    types` asks for the whole package and this item asks for the documents one check
    evaluated: only content features, and only `unknown` rather than `ambiguous` (a
    folder and an end tag are structure, and the table classifies neither -
    `contracts/rules.md`, "Content features"). The census here is that answer rendered,
    and the scope is the documents it came back naming.
    """
    document_ids = []
    for result in results:
        if result.document_id not in document_ids:
            document_ids.append(result.document_id)

    rows = unknown_types(row for row in context.ir.features if row.document_id in document_ids)
    if not rows:
        return []

    documents: list[str] = []
    for row in rows:
        for document_id in row.document_ids:
            if document_id not in documents:
                documents.append(document_id)
    census = ", ".join(f"{row.type_name} x{row.count}" for row in rows)
    context.replace_coverage(
        UNKNOWN_TYPES_CHECK,
        "unresolved",
        CoverageItem(
            check=UNKNOWN_TYPES_CHECK,
            scope=_scope(context, documents),
            reason=f"feature type names not in the calibrated table: {census}",
            error=None,
        ),
    )
    return [{"bucket": "unresolved", "check": UNKNOWN_TYPES_CHECK}]


def _write_undispatched(context: ToolContext, session: ReviewSession) -> list[dict[str, str]]:
    """The ten rules that are never evaluated, once per session.

    `rms.assembly.subassemblies` names the subassembly documents it did not reach; the
    other nine are about the package as a whole and name no document.
    """
    written: list[dict[str, str]] = []
    subassemblies = _subassembly_document_ids(context.ir)
    for rule in coverage_only():
        if rule.coverage is None or _session_holds(session, rule.id):
            continue
        bucket, reason = rule.coverage
        documents = subassemblies if rule.id == "rms.assembly.subassemblies" else []
        context.record_coverage(
            bucket,
            CoverageItem(
                check=rule.id,
                scope=_scope(context, documents),
                reason=reason,
                error=None,
            ),
        )
        written.append({"bucket": bucket, "check": rule.id})
    return written


def _subassembly_document_ids(package: EvidencePackage) -> list[str]:
    """Every assembly document that is not the root, in package order."""
    root = package.design.root_assembly_document_id
    return [
        document.document_id
        for document in package.documents
        if document.kind == "assembly" and document.document_id != root
    ]


def _session_holds(session: ReviewSession, check: str) -> bool:
    """Whether any bucket of `session` already holds an item for `check`."""
    coverage = session.coverage
    return any(
        item.check == check
        for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        for item in getattr(coverage, bucket)
    )


def _write_summary(context: ToolContext, session: ReviewSession) -> dict[str, str]:
    """The one `modeling.resilience` item, read back off the whole session.

    Counting what is already written rather than what this call produced is what lets
    `check_rms_part`, `check_rms_assembly` and `check_rms_equations` add up: each of them
    rewrites the summary from everything the session holds so far. Only the rules that are
    actually dispatched count - the four data-gap rules are unresolved by construction and
    would otherwise make every review's summary unresolved.
    """
    counted: tuple[CoverageBucket, ...] = ("checked", "skipped", "unresolved")
    counts: dict[CoverageBucket, int] = {}
    documents: set[str] = set()
    for bucket in counted:
        total = 0
        for item in getattr(session.coverage, bucket):
            rule = RULES.get(item.check)
            if rule is None or rule.coverage is not None:
                continue
            total += len(item.scope.document_ids)
            documents.update(item.scope.document_ids)
        counts[bucket] = total

    findings = sum(1 for item in session.findings if item.check in RULES)
    target: CoverageBucket = "unresolved" if counts["unresolved"] else "checked"
    item = CoverageItem(
        check=SUMMARY_CHECK,
        scope=_scope(context, sorted(documents)),
        reason=(
            f"{counts['checked']} checked, {counts['skipped']} skipped, "
            f"{counts['unresolved']} unresolved rule result(s) over "
            f"{len(documents)} document(s); {findings} finding(s)"
        ),
        error=None,
    )
    for bucket in _SUMMARY_BUCKETS:
        if bucket != target:
            items = getattr(session.coverage, bucket)
            items[:] = [existing for existing in items if existing.check != SUMMARY_CHECK]
    context.replace_coverage(SUMMARY_CHECK, target, item)
    return {"bucket": target, "check": SUMMARY_CHECK}


def _scope(context: ToolContext, document_ids: Sequence[str]) -> CoverageScope:
    """A coverage scope over documents, in the configuration the review is running in."""
    return CoverageScope(
        document_ids=list(document_ids),
        configuration=context.ir.design.active_configuration,
    )
