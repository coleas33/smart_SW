"""What the standards family adds to `checks/rules/report.py`, and nothing else (T048).

The one check tool of this family dispatches all sixteen checks over every graded document;
what happens to their results afterwards - findings, exceptions, aggregated coverage - is
the same for every family and `checks/rules/report.py` is that once, so no check author
writes a `Finding` and no tool author writes a `CoverageItem`.

Five things are this family's own, and they are what is left here:

1. **the profile stamp and this family's evidence format.** Every finding carries
   `profile:<path> sha256:<hash>` in `coverage_limits` - the identity and never a value
   (FR-001, FR-034) - plus the configuration the document was read in and the instances
   that did not resolve, where they apply; and every subject is one `inputs` entry as
   `<kind> <id> <name> persist_ref=<ref|none> scope=<document_id>` (data-model section 3).
   Both are stamped onto the results **before** they reach the neutral layer, which is the
   one place a `CheckResult` can be completed without the neutral layer learning a second
   family's shape;
2. **the subject kind, and whether the page can show it.** `Subject.kind` says what a
   subject *is* - a component, a mate, a cut-list item, a data-card property - and
   `showable` says whether there is anything in SOLIDWORKS to select: false whenever the
   persistent reference is null **or** the scope document is not a model the shared
   resolver reads, which is every drawing entity. The page renders **no** Show control for
   those rather than one that reports `ok: false` every time (FR-031);
3. **the out-of-scope loop.** Out of scope is not an outcome and this feature adds no
   seventh `RuleOutcome` (data-model section 3): after the results are aggregated this
   module walks (every check) x (every graded document) and writes one `out_of_scope`
   coverage item per check naming the documents whose kind its scope does not match. A
   document the package records **no kind** for is not one of them: it is unknown, not
   inapplicable, and the checks report it as unresolved;
4. **the verdict.** `checks/standards/verdict.py` decides it; this module is what hands it
   the findings and the (check, document) pairs, read back off the whole session so that
   two calls accumulate rather than overwrite. It then replaces the neutral summary item
   with the family's own, which carries the verdict state and the counts;
5. **the rendered check rows.** All sixteen on every run with the buckets each landed in
   and the worst of them, in the order unresolved, failed, warned, skipped, checked, out of
   scope. `failed` and `warned` are **derived from the findings**: the review session has
   five coverage buckets and no `warned`, and this feature does not change that schema.

**`standards.release` is the family's summary coverage item and is never a check**: it is
absent from `RULES`, from `check_rows` and from every waiver.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from pydantic_core import to_jsonable_python

from swreview.checks.rules.report import SUMMARY_BUCKETS, scope_over
from swreview.checks.rules.report import report_results as _report_results
from swreview.checks.standards.profile import ProfileIdentity
from swreview.checks.standards.registry import RULES, STANDARDS_FAMILY, StandardsRule
from swreview.checks.standards.results import RuleResult
from swreview.checks.standards.traversal import CheckedDocument
from swreview.checks.standards.verdict import (
    COVERAGE_BUCKETS,
    CoveragePair,
    FindingOutcome,
    ReleaseVerdict,
    release_verdict,
)
from swreview.report.session import CoverageBucket, CoverageItem, ReviewSession
from swreview.tools.context import ToolContext
from swreview.tools.query import ToolResult

__all__ = [
    "BUCKET_ORDER",
    "EMPTY_SETTING",
    "MODEL_KINDS",
    "NO_REF",
    "PROFILE_LIMIT",
    "SESSION_BUCKETS",
    "SUMMARY_CHECK",
    "SUMMARY_REASON",
    "applies",
    "check_rows",
    "document_of",
    "report_results",
    "subject_input",
    "subject_kind",
    "verdict_from",
    "verdict_json",
]

SUMMARY_CHECK = STANDARDS_FAMILY.summary_check
"""`standards.release`: the one aggregated coverage item that carries the run's verdict. It
is not one of the sixteen and no document is ever graded against it."""

PROFILE_LIMIT = "profile:{path} sha256:{sha256}"
"""The profile identity on every finding - the path and the content hash, and **no profile
value** (FR-001, FR-034). A reader of a finding has to be able to tell which standard it
was graded against without the standard being copied into the report."""

CONFIGURATION_LIMIT = "configuration {name}"
UNRESOLVED_INSTANCES_LIMIT = "unresolved instances: {ids}"

NO_REF = "none"
"""What an input says instead of a persistent reference it does not have. Said out loud, so
a reader can tell a subject that cannot be selected from one whose reference was simply not
rendered."""

MODEL_KINDS: frozenset[str] = frozenset({"part", "assembly"})
"""The document kinds the shared entity resolver can select inside. A subject scoped to a
drawing is not showable, whatever reference it carries (FR-031)."""

KIND_BY_TYPE_NAME: dict[str, str] = {
    "component": "component",
    "mate": "mate",
    "cut list item": "cut_list_item",
    "document": "document",
    "data card property": "property",
    "sheet": "sheet",
    "view": "view",
    "dimension": "dimension",
    "annotation": "annotation",
    "note": "note",
    "revision row": "revision_row",
}
"""The `Subject.kind` behind each label `checks/standards/results.py` gives a subject.

The labels are the family's own, written once in the constructors there and read once here;
anything this map does not hold is a feature row, whose `type_name` is whatever SOLIDWORKS
called the feature, and a feature row that carries a sketch is a `sketch`.
"""

BUCKET_ORDER: tuple[str, ...] = (
    "unresolved",
    "failed",
    "warned",
    "skipped",
    "checked",
    "out_of_scope",
)
"""Worst first (FR-033). A single line standing for a check shows `buckets[0]`, so no
summary line claims coverage that is partly unknown."""

SESSION_BUCKETS: frozenset[str] = frozenset(COVERAGE_BUCKETS)
"""The rendered buckets that are read off `session.coverage`. `failed` and `warned` are not:
the session has no `warned` bucket, and its `failed` one is for a tool that raised.

The four are `checks/standards/verdict.py`'s vocabulary and not a second list: this module
walks them three times - here, over the pairs the verdict counts, and over the documents the
summary names - and three typed-out copies of one vocabulary are three chances for a walk to
be one bucket short of it (T099)."""

EMPTY_SETTING = re.compile(r"the profile's (?P<setting>[A-Za-z0-9_.]+) is empty")
"""How a check says it was skipped because the profile setting it reads is empty.

One phrasing, written by the evaluator that skipped and read here, so the headline can say
"n checks skipped because a profile list is empty" (FR-032) without this module holding a
second copy of which check reads which setting - which would be a fact in two places, free
to disagree with the check that actually skipped.
"""

SUMMARY_REASON = (
    "{state}; {error} error, {warning} warning and {waived} waived finding(s); "
    "{checked} checked, {skipped} skipped, {unresolved} unresolved and {out_of_scope} "
    "out-of-scope (check, document) pair(s)"
)

OUT_OF_SCOPE_REASON = "{document_id} is a {kind} document and this check grades a {scope} one"


def report_results(
    context: ToolContext,
    results: Sequence[RuleResult],
    documents: Sequence[CheckedDocument],
    identity: ProfileIdentity,
) -> ToolResult:
    """Write `results` to the session as findings, coverage and a verdict; report them.

    Returns the recording envelope every check tool returns - `{"status": "recorded",
    "findings": [...]}` - with the structured subjects beside the findings, the coverage
    items this call wrote, the documents graded and the release verdict; or the first error
    result a finding could not be built from, handed straight back.
    """
    by_id = {document.document_id: document for document in documents}
    stamped = [_stamped(result, by_id, identity) for result in results]

    reported = _report_results(
        STANDARDS_FAMILY,
        RULES,
        context,
        stamped,
        decorate_subjects=_kind_stamp(stamped),
        extra_coverage=(_out_of_scope_step(documents),),
    )
    if "error" in reported:
        return reported

    session = context.require_session()
    kinds = {document.document_id: document.kind for document in documents}
    verdict = release_verdict(
        findings=_finding_outcomes(session),
        coverage=_coverage_pairs(session),
        empty_setting_checks=_empty_setting_checks(stamped),
        graded_kinds=[document.kind for document in documents],
    )
    coverage = [row for row in reported["coverage"] if row["check"] != SUMMARY_CHECK]
    coverage.append(_write_summary(context, session, verdict))
    return {
        "status": "recorded",
        "findings": reported["findings"],
        "subjects": {
            finding_id: [_subject_entry(entry, kinds) for entry in entries]
            for finding_id, entries in reported["subjects"].items()  # type: ignore[union-attr]
        },
        "coverage": coverage,
        "documents": [document.document_id for document in documents],
        "verdict": verdict_json(verdict),
    }


# --- 1. the profile stamp and this family's evidence format -------------------------------


def subject_kind(row: Any) -> str:
    """What one subject *is*, as `Subject.kind` (data-model section 3)."""
    mapped = KIND_BY_TYPE_NAME.get(row.type_name)
    if mapped is not None:
        return mapped
    return "sketch" if getattr(row, "sketch", None) is not None else "feature"


def subject_input(row: Any) -> str:
    """One subject as a finding input: `<kind> <id> <name> persist_ref=<ref|none> scope=<id>`.

    This family's format, and not the feature-tree one `checks/rules/results.py` writes:
    a standards finding names components, mates, cut-list items, drawing entities and
    data-card property names, so what the subject *is* has to be said before its id, and a
    subject with nothing to select says `none` rather than leaving a reader to guess.
    """
    return (
        f"{subject_kind(row)} {row.id} {row.name} "
        f"persist_ref={row.persist_ref or NO_REF} scope={row.persist_ref_scope}"
    )


def _stamped(
    result: RuleResult,
    documents: Mapping[str, CheckedDocument],
    identity: ProfileIdentity,
) -> RuleResult:
    """One result with this family's inputs and coverage limits on its finding body.

    Stamped here rather than in each check, because the profile identity, the configuration
    and the unresolved instances are facts about the *run* and the *document* that every one
    of the sixteen would otherwise repeat (constitution Principle V). A result that is not
    finding-shaped carries no body and passes through untouched.
    """
    if result.result is None:
        return result
    document = documents.get(result.document_id)
    limits = [
        PROFILE_LIMIT.format(path=identity.path, sha256=identity.sha256),
        *_document_limits(document),
        *result.result.coverage_limits,
    ]
    return replace(
        result,
        result=replace(
            result.result,
            inputs=[subject_input(row) for row in result.subject_rows],
            coverage_limits=limits,
        ),
    )


def _document_limits(document: CheckedDocument | None) -> list[str]:
    """The configuration the document was read in, and the instances that did not resolve."""
    if document is None:
        return []
    limits: list[str] = []
    if document.configuration:
        limits.append(CONFIGURATION_LIMIT.format(name=document.configuration))
    if document.unresolved_instances:
        limits.append(
            UNRESOLVED_INSTANCES_LIMIT.format(
                ids=", ".join(
                    f"{instance_id} is {state}"
                    for instance_id, state in document.unresolved_instances
                )
            )
        )
    return limits


# --- 2. the subject kind, and whether the page can show it --------------------------------


def _kind_stamp(
    results: Sequence[RuleResult],
) -> Callable[[Any, Sequence[str]], Callable[[str, str], Mapping[str, object]]]:
    """The neutral layer's per-subject decorator, carrying this family's `kind`.

    Prepared from the results rather than from the package, because a subject may be a
    data-card property name, which is not an IR row at all.
    """
    rows = {
        (result.document_id, row.id): row for result in results for row in result.subject_rows
    }

    def decorator(
        package: Any, document_ids: Sequence[str]
    ) -> Callable[[str, str], Mapping[str, object]]:
        def stamp(document_id: str, subject_id: str) -> Mapping[str, object]:
            row = rows.get((document_id, subject_id))
            return {"kind": None if row is None else subject_kind(row)}

        return stamp

    return decorator


def _subject_entry(
    entry: Mapping[str, Any], kinds: Mapping[str, str | None]
) -> dict[str, Any]:
    """One neutral subject entry as this family's `Subject` (data-model section 3)."""
    scope = entry.get("persist_ref_scope")
    return {
        "kind": entry.get("kind"),
        "id": entry["feature_id"],
        "name": entry["name"],
        "persist_ref": entry.get("persist_ref"),
        "persist_ref_scope": scope,
        "parent_chain": [],
        "component_ids": entry.get("component_ids", []),
        "showable": bool(entry.get("persist_ref")) and kinds.get(str(scope)) in MODEL_KINDS,
        "reason": entry.get("reason"),
    }


# --- 3. the out-of-scope loop -------------------------------------------------------------


def _out_of_scope_step(
    documents: Sequence[CheckedDocument],
) -> Callable[[ToolContext, ReviewSession, Sequence[RuleResult]], list[dict[str, str]]]:
    """(every check) x (every graded document), as one aggregated item per mismatched check.

    A document whose kind the package does not record is skipped here: it is carried as
    unresolved by every check that would have applied to it, and calling it out of scope
    would claim a fact about a document nobody could read (FR-029).
    """

    def step(
        context: ToolContext, session: ReviewSession, results: Sequence[RuleResult]
    ) -> list[dict[str, str]]:
        written: list[dict[str, str]] = []
        for rule in RULES.values():
            mismatched = [
                document
                for document in documents
                if document.kind is not None and not applies(rule, document.kind)
            ]
            if not mismatched:
                continue
            document_ids = [document.document_id for document in mismatched]
            reasons = "; ".join(
                OUT_OF_SCOPE_REASON.format(
                    document_id=document.document_id, kind=document.kind, scope=rule.scope
                )
                for document in mismatched
            )
            context.replace_coverage(
                rule.id,
                "out_of_scope",
                CoverageItem(
                    check=rule.id,
                    scope=scope_over(context, document_ids),
                    reason=f"{len(document_ids)} document(s): {reasons}",
                    error=None,
                ),
            )
            written.append({"bucket": "out_of_scope", "check": rule.id})
        return written

    return step


def applies(rule: StandardsRule, kind: str) -> bool:
    """Whether `rule` grades a document of `kind`; the document scope grades all three."""
    return rule.scope == "document" or rule.scope == kind


# --- 4. the verdict and the summary item --------------------------------------------------


def document_of(finding: Any) -> str:
    """The document a standards finding is about.

    Its provenance names exactly one document for every one of these checks: a finding's
    `component_ids` are all the instances of one graded document, and a drawing finding's
    references all resolve against the drawing itself. Read off the finding rather than
    carried beside it, so the same answer is available when a run folder is read back and
    the results are the session's rather than this call's.
    """
    provenance = finding.provenance if hasattr(finding, "provenance") else finding["provenance"]
    first = provenance[0]
    return str(first.document_id if hasattr(first, "document_id") else first["document_id"])


def _finding_outcomes(session: ReviewSession) -> list[FindingOutcome]:
    """Every standards finding the session holds, as the verdict counts them."""
    outcomes: list[FindingOutcome] = []
    for finding in session.findings:
        rule = RULES.get(finding.check)
        if rule is None or rule.severity is None:
            continue
        outcomes.append(
            FindingOutcome(
                check=finding.check,
                severity=rule.severity,  # type: ignore[arg-type]
                waived=finding.status == "checked_within_scope",
            )
        )
    return outcomes


def _coverage_pairs(session: ReviewSession) -> list[CoveragePair]:
    """Every (check, document) pair the session's coverage holds for one of the sixteen."""
    pairs: list[CoveragePair] = []
    for bucket in COVERAGE_BUCKETS:
        for item in getattr(session.coverage, bucket):
            if item.check not in RULES:
                continue
            pairs.extend(
                CoveragePair(check=item.check, document_id=document_id, bucket=bucket)
                for document_id in item.scope.document_ids
            )
    return pairs


def _empty_setting_checks(results: Sequence[RuleResult]) -> list[str]:
    """The checks this call skipped because the profile setting they read is empty."""
    return [
        result.rule_id
        for result in results
        if result.outcome == "skip" and EMPTY_SETTING.search(result.reason or "")
    ]


def _write_summary(
    context: ToolContext, session: ReviewSession, verdict: ReleaseVerdict
) -> dict[str, str]:
    """The family's summary item, carrying the verdict, over the neutral layer's own.

    The neutral layer writes its own summary **last**, after every extra coverage step, so
    the family's verdict-bearing one is written here once it has returned. One item that
    moves between two buckets, which `replace_coverage` alone cannot express, so the other
    bucket is cleared first - exactly as the neutral layer does it.
    """
    counts = verdict.counts
    target: CoverageBucket = "unresolved" if verdict.unresolved_check_ids else "checked"
    reason = SUMMARY_REASON.format(
        state=verdict.state,
        error=counts.error,
        warning=counts.warning,
        waived=verdict.waived,
        checked=counts.checked,
        skipped=counts.skipped,
        unresolved=counts.unresolved,
        out_of_scope=counts.out_of_scope,
    )
    if verdict.unresolved_check_ids:
        reason += f"; unresolved: {', '.join(verdict.unresolved_check_ids)}"
    for note in verdict.notes:
        reason += f"; {note}"

    documents = sorted(
        {
            document_id
            for bucket in COVERAGE_BUCKETS
            for item in getattr(session.coverage, bucket)
            if item.check in RULES
            for document_id in item.scope.document_ids
        }
    )
    for bucket in SUMMARY_BUCKETS:
        if bucket != target:
            items = getattr(session.coverage, bucket)
            items[:] = [item for item in items if item.check != SUMMARY_CHECK]
    context.replace_coverage(
        SUMMARY_CHECK,
        target,
        CoverageItem(
            check=SUMMARY_CHECK, scope=scope_over(context, documents), reason=reason, error=None
        ),
    )
    return {"bucket": target, "check": SUMMARY_CHECK}


def verdict_json(verdict: ReleaseVerdict) -> dict[str, Any]:
    """`verdict` as the JSON the route, the record and the page read."""
    return dict(to_jsonable_python(verdict))


def verdict_from(body: Mapping[str, Any]) -> ReleaseVerdict:
    """The verdict a check record holds, rebuilt. Nothing is recomputed."""
    from swreview.checks.standards.verdict import BucketCounts

    return ReleaseVerdict(
        state=body["state"],
        counts=BucketCounts(**body["counts"]),
        waived=int(body["waived"]),
        unresolved_check_ids=tuple(body["unresolved_check_ids"]),
        notes=tuple(body["notes"]),
    )


# --- 5. the rendered check rows -----------------------------------------------------------


def check_rows(session: ReviewSession) -> list[dict[str, Any]]:
    """All sixteen checks, each with the buckets it landed in and the worst of them.

    Required on every run (FR-033): a release gate must be able to say that all sixteen
    were accounted for from one array, so a check that did not apply is **present** with an
    `out_of_scope` bucket rather than absent. `standards.release` is not in it.
    """
    derived = _derived_buckets(session)
    rows: list[dict[str, Any]] = []
    for rule in RULES.values():
        buckets = [
            bucket
            for bucket in (
                _bucket_row(session, derived, rule.id, name) for name in BUCKET_ORDER
            )
            if bucket is not None
        ]
        rows.append(
            {
                "check": rule.id,
                "severity": rule.severity,
                "statement": rule.statement,
                "worst_bucket": buckets[0]["bucket"] if buckets else None,
                "buckets": buckets,
            }
        )
    return rows


def _derived_buckets(session: ReviewSession) -> dict[tuple[str, str], dict[str, str]]:
    """The buckets a finding renders in, keyed by (check, bucket) then by document.

    An `error`-severity finding renders `failed` and a `warning`-severity one `warned`; a
    waived finding renders `checked`, because an accepted condition is checked within scope
    and carries its exception (`contracts/standards-check.md` section 5). None of the three
    is read from `session.coverage`, which has no `warned` bucket at all.
    """
    derived: dict[tuple[str, str], dict[str, str]] = {}
    for finding in session.findings:
        rule = RULES.get(finding.check)
        if rule is None:
            continue
        if finding.status == "checked_within_scope":
            bucket, reason = "checked", f"waived by {finding.exception_id or 'an exception'}"
        elif rule.severity == "warning":
            bucket, reason = "warned", finding.id
        else:
            bucket, reason = "failed", finding.id
        derived.setdefault((finding.check, bucket), {})[document_of(finding)] = reason
    return derived


def _bucket_row(
    session: ReviewSession,
    derived: Mapping[tuple[str, str], Mapping[str, str]],
    check: str,
    bucket: str,
) -> dict[str, Any] | None:
    """One rendered bucket of one check, or `None` when the check did not land in it."""
    document_ids: list[str] = []
    reasons: list[str] = []
    if bucket in SESSION_BUCKETS:
        for item in getattr(session.coverage, bucket):
            if item.check != check:
                continue
            reasons.append(item.reason)
            document_ids.extend(
                document_id
                for document_id in item.scope.document_ids
                if document_id not in document_ids
            )
    for document_id, reason in derived.get((check, bucket), {}).items():
        reasons.append(f"{document_id}: {reason}")
        if document_id not in document_ids:
            document_ids.append(document_id)
    if not document_ids:
        return None
    return {"bucket": bucket, "document_ids": document_ids, "reason": "; ".join(reasons)}
