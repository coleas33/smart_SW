"""The attention policy: which findings the engineer reads first, as one pure rule.

A review of a four-component assembly on 2026-09-18 produced eight findings and printed the
six mediums in the order the tools happened to run. This module is the answer to that: a
**total order** over a finished session's findings, nine named lookups deep, with no
weights and no scores (`contracts/attention.md` section 1). Two findings compare by the
first key on which they differ, so a placement is arguable by pointing at a line rather
than by re-doing arithmetic:

    1 suppressed   2 needs judgement   3 consequence class   4 status   5 severity
    6 reach        7 carried over      8 check id            9 finding id

Four decisions are worth stating here, because each one is a way the rule could be read
wrongly and each was settled with a reason (research R2):

**Suppressed is a status or a decision, never the exception reference.** A finding is
suppressed when `status == "checked_within_scope"` - what a live waiver rewrites a finding
to, and what a clean numeric pass carries - or when its disposition is `accepted` or
`rejected`. `exception_id` is set for a waiver whose fingerprint moved as well as for a
live one, so reading it would suppress exactly the finding FR-008 protects (R2.1).

**The fold is a row, never a mutation.** Repeated conditions collapse into one
`AttentionRow` carrying the member ids and the union of the subjects. `Finding.group` is
not written and `session.findings` is byte-identical before and after, which is what makes
a ranking reproducible from `session.json` alone (R2.2, FR-014).

**Severity is read, never recomputed.** The rule families already promote their
high-severity ids; key 5 reads what they wrote (R2.4).

**Nothing here talks to a provider.** FR-015: this module imports no provider adapter, no
settings module and no network client, and does no I/O beyond loading its own table once.
`ReviewSession` is therefore a type-checking import only - `report/session.py` pulls the
provider port in for two type aliases - and the nine checklist item ids the coverage block
needs are a constant below rather than a call into `agent/checklist.py`, which imports the
session module. `tests/unit/test_attention.py` asserts both: the ids against the
checklist's own file, and the import purity in a subprocess.

One typographic rule applies to every string this module renders: **no percent sign.** The
Standards tab's body scan forbids one anywhere it displays, and the ranking reaches that
tab (research R2.14). Write "30 percent".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import Field

from swreview.findings import Finding, FindingStatus, ReviewModel, Severity

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only, never at run time
    from swreview.report.session import Coverage, CoverageItem, ReviewSession

__all__ = [
    "AttentionKey",
    "AttentionRow",
    "ConsequenceClass",
    "CoverageBlock",
    "NotAmplified",
    "NotClosed",
    "Policy",
    "Ranking",
    "RuleCounts",
    "coverage_line",
    "fold",
    "load_policy",
    "rank",
    "start_here_lines",
]

POLICY_FILE = Path(__file__).parent / "attention_policy_v1.yaml"
"""The consequence table as data, versioned and checked in beside this module."""

ConsequenceClass = Literal[
    "rebuild_breaker",
    "interface",
    "manufacturing",
    "unclassified",
    "discipline",
    "hygiene",
]

CONSEQUENCE_ORDER: tuple[ConsequenceClass, ...] = (
    "rebuild_breaker",
    "interface",
    "manufacturing",
    "unclassified",
    "discipline",
    "hygiene",
)
"""Key 3, best first. `unclassified` sits in the middle deliberately: an id the table does
not name is neither promoted nor buried, and the row prints the id so the gap is visible."""

UNCLASSIFIED: ConsequenceClass = "unclassified"

CONSEQUENCE_PHRASES: dict[ConsequenceClass, str] = {
    "rebuild_breaker": "rebuild breaker",
    "interface": "interface",
    "manufacturing": "manufacturing",
    "unclassified": "unclassified",
    "discipline": "discipline",
    "hygiene": "hygiene",
}
"""What a reason line calls each class. `unclassified` is never used from here: that row
names its check id instead (`_reason`)."""

STATUS_ORDER: tuple[FindingStatus, ...] = (
    "demonstrated",
    "suspected",
    "unresolved",
    "checked_within_scope",
)
"""Key 4, best first."""

SEVERITY_ORDER: tuple[Severity, ...] = ("high", "medium", "low", "info")
"""Key 5, best first, read verbatim off the finding (research R2.4)."""

SUPPRESSED_STATUS: FindingStatus = "checked_within_scope"
DECIDED_DECISIONS: frozenset[str] = frozenset({"accepted", "rejected"})
"""FR-008. `deferred` is absent on purpose: nothing has been decided, so it keeps competing."""

MAX_REACH = 3
"""Key 6 counts distinct components and caps at three: four subjects and forty are both
"this is everywhere", and letting the count run would make key 6 outrank every key below
it on one wide finding."""

TOP_N = 5
TOP_N_WORD = "five"
"""How many rows the section amplifies, as a number and as the word the line prints.
The two move together; `tests/unit/test_attention.py` pins the rendered sentence."""

MAX_NOT_CLOSED = 5
"""How many close-out sentences the coverage block prints (FR-013)."""

CHECKLIST_ITEM_IDS: tuple[str, ...] = (
    "provenance",
    "drawing.manufacturing_inputs",
    "interfaces.fit",
    "interfaces.stack",
    "fasteners",
    "holes.alignment",
    "interference",
    "modeling.resilience",
    "coverage.closeout",
)
"""The ids of `agent/checklist_v1.yaml`, in its order.

A coverage item whose `check` equals one of these is a **close-out row**: the row
`ReviewRun.finalize` writes for a checklist item the run did not close, carrying the
sentence an engineer can act on (research R2.5). They are copied here rather than loaded,
because `agent/checklist.py` imports `report/session.py` and would drag the provider port
into a module FR-015 requires to stay pure; the copy is asserted against the checklist's
own file in `tests/unit/test_attention.py`.
"""

CLOSEOUT_ITEM_ID = "coverage.closeout"
"""The one checklist id the close-out list excludes.

Its unresolved row is the run's **own** close-out summary - "the package carries no hole,
fastener or drawing evidence, so four checklist items closed out unresolved" - and not a
family the run could not reach. Decided on 2026-09-19, after the Phase 1 builder read the
handover folders and found the row; the fixtures carry it last, so a rule that took the
first five rows and never looked at the id would pass by luck.
"""

EVIDENCE_REQUEST_CHECK = "coverage.evidence_request"
"""The check an open evidence request is recorded under; counted, never listed."""

EMPTY_NO_FINDINGS = "no findings were recorded"
EMPTY_ALL_DECIDED = "every finding is informational or already decided"
"""The two things the section says when it has nothing to amplify (contract section 3)."""


# --- the policy file -------------------------------------------------------------------------


class Policy(ReviewModel):
    """`attention_policy_v1.yaml`, loaded (data-model.md section 1)."""

    version: str
    needs_judgement: list[str]
    classes: dict[str, ConsequenceClass]
    blind_spots: dict[str, str]
    triage_pass_preconditions: list[str]

    def needs_judgement_of(self, check: str) -> bool:
        """Key 2: no tool can close this family, because only the engineer knows the intent."""
        return any(check.startswith(prefix) for prefix in self.needs_judgement)

    def consequence_of(self, check: str) -> ConsequenceClass:
        """Key 3. An id the table does not name is `unclassified` and is printed by name."""
        return self.classes.get(check, UNCLASSIFIED)


@cache
def load_policy() -> Policy:
    """The policy file, parsed once per process (FR-015: no I/O beyond this).

    Cached rather than read per call because the ranking is recomputed on every report
    render, every check re-read and every `GET`, and because a table that could change
    under two calls in one run would break FR-014's reproducibility in the least visible
    way possible.
    """
    return Policy.model_validate(yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8")))


# --- the ranking's shapes ----------------------------------------------------------------------


class AttentionKey(ReviewModel):
    """The nine values that placed a row, so the placement is arguable by hand.

    Every value is an integer or a string, and smaller is better on all seven numbers, so
    `order()` is a plain tuple comparison and two rankings of the same session compare
    byte-identically.
    """

    suppressed: int
    judgement: int
    consequence: int
    status: int
    severity: int
    reach: int
    carried: int
    check: str
    finding_id: str

    def order(self) -> tuple[int, int, int, int, int, int, int, str, str]:
        return (
            self.suppressed,
            self.judgement,
            self.consequence,
            self.status,
            self.severity,
            self.reach,
            self.carried,
            self.check,
            self.finding_id,
        )


class AttentionRow(ReviewModel):
    """One line of "Start here": one finding, or one repeated condition folded into one."""

    finding_id: str
    member_finding_ids: list[str]
    check: str
    title: str
    status: FindingStatus
    severity: Severity
    component_ids: list[str]
    consequence_class: ConsequenceClass
    key: AttentionKey
    reason: str


class NotAmplified(ReviewModel):
    """What the section did not put in front of the engineer, and why, in findings.

    The four counts partition `total`, first match winning, so no finding is counted twice
    and none escapes: a waived finding is "checked within scope" rather than
    "informational", although it carries both.
    """

    total: int
    checked_within_scope: int
    dispositioned: int
    info: int
    beyond_top_n: int


class NotClosed(ReviewModel):
    """One checklist item the run did not close, with the sentence the run recorded."""

    item: str
    reason: str


class RuleCounts(ReviewModel):
    """Everything in the unresolved and skipped buckets that is not a close-out row."""

    unresolved: int
    skipped: int


class CoverageBlock(ReviewModel):
    """What the run could not reach: the five buckets, then the run's own close-out."""

    checked: int
    skipped: int
    unresolved: int
    failed: int
    out_of_scope: int
    not_closed: list[NotClosed]
    open_evidence_requests: int
    rules: RuleCounts


class Ranking(ReviewModel):
    """A finished session's findings in attention order, with what the order left out.

    Serializes to `contracts/attention.md` section 4 minus `session_id`, which is what the
    two check bodies and `GET /sessions/{chat_id}/attention` carry; `attention.json` adds
    the session id back, because a record beside a session it was not computed from is
    stale.
    """

    policy_version: str
    rows: list[AttentionRow]
    top_n: int = Field(default=TOP_N)
    not_amplified: NotAmplified
    coverage: CoverageBlock
    empty_reason: str | None


# --- the fold ------------------------------------------------------------------------------------


def fold(findings: Sequence[Finding], policy: Policy | None = None) -> list[list[Finding]]:
    """Group `findings` into the rows the ranking will carry (FR-012, contract section 2).

    Findings fold when they share `check`, `status` and `severity` and their
    `component_ids` are pairwise disjoint. A needs-judgement check never folds - two press
    fits may be two different intents, and collapsing them would be a judgement the policy
    made silently. A single finding is a group of one.

    The walk is in finding-id order, not arrival order, so the survivor of a group and the
    order of its members are the same however the tools happened to record them (FR-014).
    Groups are returned in the order their survivors were first seen; `rank` sorts them, so
    that order is an implementation detail rather than a rank.

    The findings themselves are returned, never copies: a row is a *view* of the session,
    and this function writes nothing to it.
    """
    policy = policy if policy is not None else load_policy()
    groups: list[list[Finding]] = []
    subjects: list[set[str]] = []
    open_groups: dict[tuple[str, str, str], list[int]] = {}

    for finding in sorted(findings, key=lambda one: one.id):
        components = set(finding.component_ids)
        if policy.needs_judgement_of(finding.check):
            # The one guard: this check joins no group and opens none for the next
            # finding to join, however disjoint the two subjects are.
            groups.append([finding])
            subjects.append(components)
            continue
        fold_key = (finding.check, finding.status, finding.severity)
        candidates = open_groups.setdefault(fold_key, [])
        index = next((one for one in candidates if not subjects[one] & components), None)
        if index is None:
            candidates.append(len(groups))
            groups.append([finding])
            subjects.append(components)
        else:
            groups[index].append(finding)
            subjects[index] |= components
    return groups


# --- the rank --------------------------------------------------------------------------------


def rank(session: ReviewSession, policy: Policy | None = None) -> Ranking:
    """Rank a finished session's findings. Total: it raises on no `ReviewSession`.

    Reads `session.findings` and `session.coverage` and writes nothing anywhere - the
    report, the record beside the session and the two check bodies are all rendered from
    what comes back.
    """
    policy = policy if policy is not None else load_policy()
    rows = [_row(group, policy) for group in fold(session.findings, policy)]
    rows.sort(key=lambda row: row.key.order())

    empty_reason = _empty_reason(rows)
    amplified = (
        set()
        if empty_reason is not None
        else {member for row in rows[:TOP_N] for member in row.member_finding_ids}
    )
    return Ranking(
        policy_version=policy.version,
        rows=rows,
        top_n=TOP_N,
        not_amplified=_not_amplified(session.findings, amplified),
        coverage=_coverage_block(session.coverage),
        empty_reason=empty_reason,
    )


def _row(group: Sequence[Finding], policy: Policy) -> AttentionRow:
    """One row from one folded group; the survivor is the lowest finding id."""
    survivor = group[0]
    components = sorted({component for one in group for component in one.component_ids})
    consequence = policy.consequence_of(survivor.check)
    key = AttentionKey(
        suppressed=int(_is_suppressed(survivor)),
        judgement=int(not policy.needs_judgement_of(survivor.check)),
        consequence=CONSEQUENCE_ORDER.index(consequence),
        status=STATUS_ORDER.index(survivor.status),
        severity=SEVERITY_ORDER.index(survivor.severity),
        reach=MAX_REACH - min(MAX_REACH, len(components)),
        carried=int(survivor.carried_over_from is not None),
        check=survivor.check,
        finding_id=survivor.id,
    )
    return AttentionRow(
        finding_id=survivor.id,
        member_finding_ids=[one.id for one in group],
        check=survivor.check,
        title=survivor.title,
        status=survivor.status,
        severity=survivor.severity,
        component_ids=components,
        consequence_class=consequence,
        key=key,
        reason=_reason(survivor, consequence, key, len(components)),
    )


def _is_suppressed(finding: Finding) -> bool:
    """FR-008: a status of checked within scope, or a decision, and nothing else."""
    return finding.status == SUPPRESSED_STATUS or (
        finding.disposition is not None and finding.disposition.decision in DECIDED_DECISIONS
    )


def _reason(finding: Finding, consequence: ConsequenceClass, key: AttentionKey, reach: int) -> str:
    """One sentence naming the key that placed the row (data-model.md section 2).

    The suppressed and needs-judgement keys are names on their own; below them the reason
    states the consequence class, the status, and the two keys that are only sometimes the
    difference - the reach when the row names more than one component, and the carry when
    the verdict came from a previous session.
    """
    if key.suppressed:
        # The status first, because it is the bucket the not-amplified line counts a
        # finding in when it carries both; and never an `assert`, because `rank` is total
        # and a future reading of key 1 must not be able to make a reason line raise.
        if finding.status != SUPPRESSED_STATUS and finding.disposition is not None:
            return f"already {finding.disposition.decision}"
        return "checked within scope"
    if not key.judgement:
        return "needs your judgement"

    if consequence == UNCLASSIFIED:
        parts = [f"unclassified check `{finding.check}`"]
    else:
        parts = [CONSEQUENCE_PHRASES[consequence]]
    parts.append(finding.status.replace("_", " "))
    if reach > 1:
        parts.append(f"{reach} components")
    if key.carried:
        parts.append("carried over")
    return ", ".join(parts)


def _empty_reason(rows: Sequence[AttentionRow]) -> str | None:
    """Why there is nothing to start with, or `None` when there is (contract section 3)."""
    if not rows:
        return EMPTY_NO_FINDINGS
    if all(row.key.suppressed or row.severity == "info" for row in rows):
        return EMPTY_ALL_DECIDED
    return None


def _not_amplified(findings: Iterable[Finding], amplified: set[str]) -> NotAmplified:
    """Every finding the section did not print, by the reason it did not print it.

    Counted over the session's findings rather than over the rows, because a folded row
    stands for several findings and the line says "findings".
    """
    counts = {"checked_within_scope": 0, "dispositioned": 0, "info": 0, "beyond_top_n": 0}
    for finding in findings:
        if finding.id in amplified:
            continue
        if finding.status == SUPPRESSED_STATUS:
            counts["checked_within_scope"] += 1
        elif finding.disposition is not None and finding.disposition.decision in DECIDED_DECISIONS:
            counts["dispositioned"] += 1
        elif finding.severity == "info":
            counts["info"] += 1
        else:
            counts["beyond_top_n"] += 1
    return NotAmplified(total=sum(counts.values()), **counts)


def _coverage_block(coverage: Coverage) -> CoverageBlock:
    """The five bucket counts and the run's own close-out (research R2.5, FR-013).

    Nothing here is recomputed or reworded: a close-out row's reason is the sentence the
    run recorded, printed verbatim.
    """
    items = set(CHECKLIST_ITEM_IDS)
    not_closed = [
        NotClosed(item=item.check, reason=item.reason)
        for item in coverage.unresolved
        if item.check in items and item.check != CLOSEOUT_ITEM_ID
    ]
    return CoverageBlock(
        checked=len(coverage.checked),
        skipped=len(coverage.skipped),
        unresolved=len(coverage.unresolved),
        failed=len(coverage.failed),
        out_of_scope=len(coverage.out_of_scope),
        not_closed=not_closed[:MAX_NOT_CLOSED],
        open_evidence_requests=sum(
            1 for item in coverage.unresolved if item.check == EVIDENCE_REQUEST_CHECK
        ),
        rules=RuleCounts(
            unresolved=_rule_count(coverage.unresolved),
            skipped=_rule_count(coverage.skipped),
        ),
    )


def _rule_count(items: Iterable[CoverageItem]) -> int:
    """Everything in a bucket that is neither a close-out row nor an evidence request."""
    named = set(CHECKLIST_ITEM_IDS) | {EVIDENCE_REQUEST_CHECK}
    return sum(1 for item in items if item.check not in named)


# --- the two renderers ----------------------------------------------------------------------


def start_here_lines(ranking: Ranking) -> list[str]:
    """The rows of "Start here", then the line accounting for what they left out.

    The heading and the policy footer belong to whoever is rendering - the report writes a
    Markdown section (T026), the gate's brief writes a plain block (T046) - so this returns
    the body both of them share and neither of them re-derives.
    """
    if ranking.empty_reason is not None:
        lines = [f"Nothing to start with: {ranking.empty_reason}."]
    else:
        lines = [
            f"{number}. **{row.finding_id}** `{row.check}` - {_row_reason(row)}"
            for number, row in enumerate(ranking.rows[: ranking.top_n], start=1)
        ]
    if ranking.not_amplified.total:
        lines.extend(["", _not_amplified_line(ranking.not_amplified)])
    return lines


def _row_reason(row: AttentionRow) -> str:
    """A row's reason, and for a needs-judgement row what the judgement is about.

    "needs your judgement" is the one reason that describes no property of the finding -
    the check id already said the family - so that row, and only that row, carries the
    title. Every other reason states the class, the status and the reach.
    """
    if not row.key.judgement:
        return f"{row.reason} ({row.title})"
    return row.reason


def _not_amplified_line(not_amplified: NotAmplified) -> str:
    findings = "finding" if not_amplified.total == 1 else "findings"
    return (
        f"Not amplified: {not_amplified.total} {findings} "
        f"({not_amplified.checked_within_scope} checked within scope, "
        f"{not_amplified.dispositioned} already decided, "
        f"{not_amplified.info} informational, "
        f"{not_amplified.beyond_top_n} beyond the top {TOP_N_WORD})."
    )


def coverage_line(ranking: Ranking) -> list[str]:
    """What the run could not reach: the bucket counts, then the run's own close-out.

    Named for the one line it always produces; the close-out sentences and the tail below
    it are bullets under that line. A check folder writes no close-out row, so there it is
    the bucket counts and the rule counts only (contract section 3).
    """
    coverage = ranking.coverage
    lines = [
        f"What this run could not reach: {coverage.unresolved} unresolved, "
        f"{coverage.skipped} skipped, {coverage.failed} failed, "
        f"{coverage.out_of_scope} out of scope."
    ]
    lines.extend(f"- {entry.item}: {entry.reason}" for entry in coverage.not_closed)
    tail = _rules_clauses(coverage)
    if tail:
        lines.append(f"- {'; '.join(tail)}.")
    return lines


def _rules_clauses(coverage: CoverageBlock) -> list[str]:
    """The open evidence requests and the rule counts, each clause only when it says something."""
    clauses: list[str] = []
    open_requests = coverage.open_evidence_requests
    if open_requests:
        requests = "request is" if open_requests == 1 else "requests are"
        clauses.append(f"{open_requests} evidence {requests} still open")
    if coverage.rules.unresolved or coverage.rules.skipped:
        rules = "rule" if coverage.rules.unresolved == 1 else "rules"
        clauses.append(
            f"{coverage.rules.unresolved} {rules} unresolved and {coverage.rules.skipped} skipped"
        )
    return clauses
