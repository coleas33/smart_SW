"""`RuleResult` lists become session findings and coverage, for any family, in one place.

A family's check tools differ only in which rules they dispatch; everything that happens to
the results afterwards is the same, and `report_results` is that once, so a rule author
never writes a `Finding` and a tool author never writes a `CoverageItem`.

What it does, in the order it does it:

1. **findings.** A `fail`, `warn` or `waived` result becomes one finding through
   `tools/recording.py`. The subject document's every `ComponentInstance` is its
   `component_ids`, in package order, and a document with no instance at all yields
   unresolved coverage instead - because a finding that names no component is not a finding
   and an invented id is worse (constitution Principle I). The one exception is a document
   **kind that never has an instance**: a drawing is reached by opening it, not by being
   placed in an assembly, so a result about one is a **document-scoped** finding bound by
   its `document_id` with empty `component_ids`, and reporting it as unresolved coverage
   would be a data gap that is not one. The finding carries
   `tool_result_ids=[current_step_id]` and no `Calculation`: these rules' evidence is the
   model the reader was shown.
2. **exceptions.** Only a `fail` outcome asks the store, and it asks with `check=<rule id>`
   so one document's instances cannot hand an interference waiver to a sketch rule - and
   with the **document** as well whenever the store binds that check's exceptions to one,
   which `fingerprint_kind_for` answers and this layer does not decide. `active` waives the
   finding, `needs_review` leaves it standing with the marker, and both say which evidence
   the exception was accepted for (`BOUND_TO`). A `warn` is advisory and never asks, in any
   family: what a family calls its warning severity differs, but a `warn` **outcome** is
   the same thing everywhere.
3. **coverage.** One item per rule per bucket, written through
   `ToolContext.replace_coverage`, so a tool called twice leaves one item and not two; then
   the family's own extra coverage steps, in the order the family supplies them; and last
   the family's summary item, which is read back off the session so several tools of one
   family accumulate into one answer rather than overwriting each other's.

**Two per-family hooks, and no more.** The subject decorator stamps whatever extra a family
knows about a subject (the RMS rules stamp the group the feature is in); the extra coverage
steps write whatever a family owes beyond one item per rule per bucket (the RMS rules write
a census of unknown type names and the ten rules that are never dispatched). Both are
supplied by the family **module** at the call rather than carried on `CheckFamily`, which
holds facts and no callables.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from swreview.checks.result import CheckResult
from swreview.checks.rules.family import CheckFamily
from swreview.checks.rules.registry import Rule
from swreview.checks.rules.results import RuleResult
from swreview.exceptions import FingerprintKind, ReviewException, fingerprint_kind_for
from swreview.ir.models import EvidencePackage, SourceRef
from swreview.report.session import CoverageBucket, CoverageItem, CoverageScope, ReviewSession
from swreview.tools.context import ToolContext
from swreview.tools.query import ToolResult
from swreview.tools.recording import record_result

__all__ = [
    "BOUND_TO",
    "DOCUMENT_SCOPED_KINDS",
    "NO_PERSIST_REF",
    "ExtraCoverage",
    "SubjectDecorator",
    "report_results",
    "scope_over",
    "session_holds",
]

CONFIGURATION_GAP = "feature_tree_configuration"

NO_PERSIST_REF = (
    "no persistent reference was read for this subject, so it cannot be selected in "
    "SOLIDWORKS"
)
"""Why a subject has no `SourceRef` and no reference in its entry. Said once, on the
subject it is about: a Show button that reported success while selecting nothing is the
failure this exists to remove, and a silently missing subject would be the same failure one
layer earlier."""

DOCUMENT_SCOPED_KINDS: frozenset[str] = frozenset({"drawing"})
"""The document kinds that never carry a `ComponentInstance`, and are therefore graded as
themselves.

A part or an assembly is reached through instances, so one with none is a package that does
not say how the document is used - a data gap, reported as unresolved coverage. A drawing
is not placed in anything; it has no instance by nature, and treating that as a gap would
turn every drawing finding into a coverage row (`specs/006-standards-check/data-model.md`
section 2). The distinction is the document's kind and not the family's name, so a family
that never grades a drawing is unaffected by it.
"""

STANDARDS_BINDING: FingerprintKind = "standards"
"""The one fingerprint kind whose exceptions are bound to a **document** as well as to the
instances that reach it.

The store's own vocabulary and not a family name: `fingerprint_kind_for` decides it from
the check id, and this layer asks rather than deciding, so "what is this exception bound
to" has one answer (`swreview.exceptions`, `data-model.md` section 5).
"""


@dataclass(frozen=True)
class BoundTo:
    """How a finding talks about the evidence an exception was accepted for.

    Three phrasings and not one, because the sentence has to be true: an exception bound to
    a feature tree is re-reviewed when the features change, and one bound to a drawing has
    no feature tree at all to point at.
    """

    subject: str
    """What the exception was accepted for: "for this <subject> and configuration"."""

    changes: str
    """What would make it need re-review: "Re-review EX-001 if <changes>"."""

    repair: str
    """What an engineer fixes instead of re-accepting: "fix the <repair>"."""


DEFAULT_BOUND_TO = BoundTo(
    subject="feature tree", changes="these features change", repair="tree"
)
"""What every exception written before this feature says, byte for byte: the geometry and
feature-tree kinds are re-reviewed when the tree moves, and feature 001's and 003's goldens
carry these words."""

BOUND_TO: dict[str, BoundTo] = {
    STANDARDS_BINDING: BoundTo(subject="document", changes="it changes", repair="document")
}
"""The kinds that say something else. Only the document-bound one does, so the map holds
one entry and `DEFAULT_BOUND_TO` answers for the rest - which is what keeps the existing
wording unchanged rather than nearly unchanged."""


SubjectDecorator = Callable[
    [EvidencePackage, Sequence[str]], Callable[[str, str], Mapping[str, object]]
]
"""A family's extra per-subject entries: prepared once per call over the documents being
reported, then asked for each `(document_id, subject_id)` pair.

Two levels because the preparation is the expensive half - the RMS decorator assigns groups
once per document - and the stamping happens once per subject."""

ExtraCoverage = Callable[
    [ToolContext, ReviewSession, Sequence[RuleResult]], list[dict[str, str]]
]
"""One family-owned coverage step: writes what it owes and returns the rows it wrote, in
the `{"bucket": ..., "check": ...}` shape `report_results` reports."""

_BUCKET_BY_OUTCOME: dict[str, CoverageBucket] = {
    "pass": "checked",
    "skip": "skipped",
    "unresolved": "unresolved",
}
"""The three outcomes that are coverage rather than a finding."""

_SUMMARY_BUCKETS: tuple[CoverageBucket, ...] = ("checked", "unresolved")
"""The two buckets the summary can be in. It is one item that moves between them, which
`replace_coverage` - same check, same bucket - cannot express on its own."""


def report_results(
    family: CheckFamily,
    rules: Mapping[str, Rule],
    context: ToolContext,
    results: Sequence[RuleResult],
    *,
    decorate_subjects: SubjectDecorator | None = None,
    extra_coverage: Sequence[ExtraCoverage] = (),
) -> ToolResult:
    """Write `results` to the session as findings and coverage; report what was written.

    Returns the recording envelope every check tool returns - `{"status": "recorded",
    "findings": [...]}` - with the coverage items this call wrote, or the first error
    result a finding could not be built from.

    `rules` is the family's catalogue: the summary counts only the rules that are actually
    dispatched, so it has to know which ids are the family's and which of those are
    coverage-only.
    """
    session = context.require_session()
    findings: list[dict[str, object]] = []
    subjects: dict[str, list[dict[str, object]]] = {}
    coverage: list[dict[str, str]] = []

    reportable, unreportable = _split_by_reportability(context, results)
    decorate = _decorations(
        context.ir, [result.document_id for result, _ in reportable], decorate_subjects
    )
    for result, check_result in reportable:
        recorded = _record(context, result, check_result, decorate)
        if "error" in recorded:
            return recorded
        finding = recorded["finding"]
        findings.append(finding)  # type: ignore[arg-type]
        subjects[finding["id"]] = recorded["subjects"]  # type: ignore[index, assignment]

    configuration = context.ir.design.active_configuration
    for bucket, item in _aggregate([*results, *unreportable], configuration):
        context.replace_coverage(item.check, bucket, item)
        coverage.append({"bucket": bucket, "check": item.check})

    for step in extra_coverage:
        coverage.extend(step(context, session, results))
    coverage.append(_write_summary(family, rules, context, session))
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


def _is_document_scoped(package: EvidencePackage, document_id: str) -> bool:
    """Whether `document_id` is a kind that is graded as itself, with no instance.

    A document the package does not carry at all is not one: its absence is a gap, and the
    unresolved row that reports it is what says so.
    """
    return any(
        document.document_id == document_id and document.kind in DOCUMENT_SCOPED_KINDS
        for document in package.documents
    )


def _split_by_reportability(
    context: ToolContext, results: Sequence[RuleResult]
) -> tuple[list[tuple[RuleResult, CheckResult]], list[RuleResult]]:
    """The finding-shaped results, split into those that can name what they are about and
    those that cannot: the latter are unresolved coverage, never an invented id.

    A result can name what it is about when its document has a `ComponentInstance`, or when
    its document is a kind that never has one (`DOCUMENT_SCOPED_KINDS`) and is therefore
    bound by its own id.
    """
    reportable: list[tuple[RuleResult, CheckResult]] = []
    unreportable: list[RuleResult] = []
    for result in results:
        if result.result is None:
            continue
        if _component_ids(context.ir, result.document_id) or _is_document_scoped(
            context.ir, result.document_id
        ):
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


def _decorations(
    package: EvidencePackage,
    document_ids: Sequence[str],
    decorator: SubjectDecorator | None,
) -> Callable[[str, str], Mapping[str, object]]:
    """The family's per-subject stamp, prepared once, or one that stamps nothing."""
    if decorator is None:
        return lambda document_id, subject_id: {}
    return decorator(package, list(dict.fromkeys(document_ids)))


def _record(
    context: ToolContext,
    result: RuleResult,
    body: CheckResult,
    decorate: Callable[[str, str], Mapping[str, object]],
) -> ToolResult:
    """One finding-shaped result as a session finding, exceptions applied.

    The subjects the rule named are emitted twice here: as one `SourceRef` each on the
    finding, which is what a page builds its Show payload from, and as the structured
    entries returned beside the finding for the route's response. One builder, two
    consumers, and neither of them parses the display string in `inputs`.

    `component_ids` is empty for a document-scoped result, and the finding is bound by the
    document instead - which is why the exception record carries a `document_id`. The
    emptiness is decided by the document's **kind**, not by the package happening to carry
    no row for it: a drawing-rooted dump writes one synthesized forest-root instance to
    hang the referenced models under, and that row does not *reach* the drawing, so naming
    it would bind a drawing's waiver to a pseudo-instance. `document_ids` carries that
    binding into the finding, so one whose subjects have no persistent reference - a
    data-card property name on a drawing - still names the document it was read from
    rather than being refused for naming nothing.
    """
    package = context.ir
    document_scoped = _is_document_scoped(package, result.document_id)
    component_ids = [] if document_scoped else _component_ids(package, result.document_id)
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
        document_ids=[result.document_id] if document_scoped else [],
    )
    if "error" in recorded:
        return recorded
    return {**recorded, "subjects": _subjects(result, component_ids, decorate)}


def _source_refs(result: RuleResult) -> list[SourceRef]:
    """One source reference per subject that has one, in the order the rule named them.

    `document_id` is the subject's persist-ref scope - the document the reference resolves
    against, which for a part feature reached through an assembly is the part - because
    that is what the entity resolver needs to open the right document before selecting. A
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
    decorate: Callable[[str, str], Mapping[str, object]],
) -> list[dict[str, object]]:
    """The structured subjects of one finding.

    Deliberately *not* a field on `Finding`: the feature 001 finding contract does not
    move, so this travels beside the finding, keyed by its id, and a consumer that only
    knows feature 001 sees exactly what it always saw.

    The family's decoration sits between the subject's identity and its reference, which is
    where a family-specific fact about a subject reads: `feature_id`, `name`, `type_name`,
    then whatever the family knows, then how to select it.
    """
    entries: list[dict[str, object]] = []
    for row in result.subject_rows:
        readable = bool(row.persist_ref and row.persist_ref_scope)
        entries.append(
            {
                "feature_id": row.id,
                "name": row.name,
                "type_name": row.type_name,
                **decorate(result.document_id, row.id),
                "persist_ref": row.persist_ref if readable else None,
                "persist_ref_scope": row.persist_ref_scope if readable else None,
                "component_ids": list(component_ids),
                "reason": None if readable else NO_PERSIST_REF,
            }
        )
    return entries


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

    A `warn` outcome is advisory and is never waivable, so it is not even looked up: a
    store that happens to hold an exception with the same bindings must not quieten it.
    The test is the outcome and not the family's severity word, because the outcome is what
    both vocabularies map onto.

    The lookup is asked with the **document** whenever the store binds this check's
    exceptions to one, which `fingerprint_kind_for` answers from the check id: a standards
    waiver names the document it was accepted on, and asking without it would find no
    record at all for a check that has one, silently un-waiving it (FR-041, RK-11).
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
        document_id=_bound_document(result),
    )


def _bound_document(result: RuleResult) -> str | None:
    """The document an exception for this rule binds to, or `None` for one that binds to
    components alone.

    The store's own rule, read by the check id rather than by the family's name: which
    evidence a kind of exception is bound to is `swreview.exceptions`' answer, and a second
    copy of it here would be free to disagree with the record the store writes.
    """
    return (
        result.document_id
        if fingerprint_kind_for(result.rule_id) == STANDARDS_BINDING
        else None
    )


def _waived(result: CheckResult, exception: ReviewException) -> CheckResult:
    """The same condition, accepted: `checked_within_scope` citing the exception."""
    bound_to = BOUND_TO.get(exception.fingerprint_kind, DEFAULT_BOUND_TO)
    return replace(
        result,
        status="checked_within_scope",
        severity="info",
        observed=(
            f"{result.observed}. Excepted by {exception.id}, accepted by "
            f"{exception.accepted_by} on {exception.accepted_at} for this "
            f"{bound_to.subject} and configuration: {exception.note}"
        ),
        coverage_limits=[
            *result.coverage_limits,
            f"exception:{exception.id}: {exception.note}",
        ],
        recommended_action=(
            f"None while the {bound_to.subject} is unchanged. Re-review {exception.id} if "
            f"{bound_to.changes}."
        ),
    )


def _needs_review(result: CheckResult, exception: ReviewException) -> CheckResult:
    """The finding stands: what it was accepted for is not what is here."""
    bound_to = BOUND_TO.get(exception.fingerprint_kind, DEFAULT_BOUND_TO)
    return replace(
        result,
        observed=(
            f"{result.observed}. Exception {exception.id} was accepted for this condition "
            f"but the {bound_to.subject} it was bound to has changed, so it does not clear "
            f"this finding - needs re-review: {exception.id}"
        ),
        recommended_action=(
            f"Re-review exception {exception.id}: confirm the changed condition is still "
            f"intended and re-accept it, or retire it and fix the {bound_to.repair}. "
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


# --- 3. the summary, and what a family's own coverage step needs -------------------


def scope_over(context: ToolContext, document_ids: Sequence[str]) -> CoverageScope:
    """A coverage scope over documents, in the configuration the review is running in."""
    return CoverageScope(
        document_ids=list(document_ids),
        configuration=context.ir.design.active_configuration,
    )


def session_holds(session: ReviewSession, check: str) -> bool:
    """Whether any bucket of `session` already holds an item for `check`."""
    coverage = session.coverage
    return any(
        item.check == check
        for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        for item in getattr(coverage, bucket)
    )


def _write_summary(
    family: CheckFamily,
    rules: Mapping[str, Rule],
    context: ToolContext,
    session: ReviewSession,
) -> dict[str, str]:
    """The family's one summary item, read back off the whole session.

    Counting what is already written rather than what this call produced is what lets a
    family's several check tools add up: each of them rewrites the summary from everything
    the session holds so far. Only the rules that are actually dispatched count - a
    coverage-only rule is unresolved by construction and would otherwise make every
    review's summary unresolved.
    """
    counted: tuple[CoverageBucket, ...] = ("checked", "skipped", "unresolved")
    counts: dict[CoverageBucket, int] = {}
    documents: set[str] = set()
    for bucket in counted:
        total = 0
        for item in getattr(session.coverage, bucket):
            rule = rules.get(item.check)
            if rule is None or rule.coverage is not None:
                continue
            total += len(item.scope.document_ids)
            documents.update(item.scope.document_ids)
        counts[bucket] = total

    findings = sum(1 for item in session.findings if item.check in rules)
    target: CoverageBucket = "unresolved" if counts["unresolved"] else "checked"
    item = CoverageItem(
        check=family.summary_check,
        scope=scope_over(context, sorted(documents)),
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
            items[:] = [
                existing for existing in items if existing.check != family.summary_check
            ]
    context.replace_coverage(family.summary_check, target, item)
    return {"bucket": target, "check": family.summary_check}
