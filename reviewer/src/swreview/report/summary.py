"""The review summary: what matters in ten seconds, computed once (feature 009 US3).

The Review tab prints a summary above everything else - how many findings in how many
issues, which of them are the engineer's to decide, to fix and to verify, the questions
waiting, the parts not loaded, the drawings read and found, and one line per check goal -
and **computes none of it**
(FR-009). This module is where it is computed, from the ranking, the session and the
package, in words read from `review_words_v1.yaml` (research R2.5).

It is pure: it reads its arguments and the words file, imports no provider and no
settings, and writes nothing. `report/attention.py` does not import it, so the ranking,
`attention.json` and both check bodies carry no summary (research R2.2); the rows of the
ranking the Review tab prints carry display titles (`review_ranking`, decision 2A). Because
it imports no provider, the session, the ledger and the coverage bucket names are not
imported at run time: `report/session.py` pulls the provider port in, so the bucket
names are copied below and asserted against the session's own in the tests, the way
`attention.CHECKLIST_ITEM_IDS` is.

Three decisions worth stating, each settled with a reason:

**Findings are counted, not rows** (research R2.3). A folded row stands for several
findings, and the headline and the groups say "findings". Every finding is in exactly one
group, first match winning, by the ranking's own keys; severity is never read.

**One goal per check** (research R2.4). A finding or a coverage row belongs to the goal
whose `items` name its check, else to the goal with the longest prefix it starts with, so
`standards.drawing.*` speaks for drawings and never also for hygiene.

**A goal's state is a fixed precedence** (contracts/review-summary.md section 3): issues,
then not reached, then checked, then not applicable. One case the contract's four rows left
open - only rule rows that are unresolved, skipped or failed - reads not reached, its
reason from the first of them, so every goal has a state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

from swreview.drawings.evidence import file_name, id_order
from swreview.findings import Finding, FindingStatus, ReviewModel, Severity
from swreview.ir.models import EvidencePackage
from swreview.report.attention import (
    DECIDED_DECISIONS,
    SUPPRESSED_STATUS,
    Policy,
    Ranking,
    load_policy,
    rank,
)
from swreview.report.names import and_list
from swreview.report.names import component_names as all_component_names
from swreview.report.titles import with_display_titles
from swreview.report.unexamined import not_examined

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only, never at run time
    from swreview.agent.events import UsageLedger
    from swreview.report.session import CoverageItem, EvidenceRequest, ReviewSession

__all__ = [
    "COVERAGE_BUCKETS",
    "DRAWINGS_NAMED",
    "WORDS_FILE",
    "ContactList",
    "ContactView",
    "DrawingsLine",
    "EntityName",
    "Goal",
    "GoalCount",
    "GoalLine",
    "Labels",
    "ModellingPractice",
    "NotLoaded",
    "QuestionList",
    "QuestionView",
    "ReviewRanking",
    "ReviewSummary",
    "SummaryGroup",
    "Words",
    "contacts_of",
    "drawings_of",
    "goal_of",
    "load_words",
    "review_ranking",
    "review_summary",
]

WORDS_FILE = Path(__file__).parent / "review_words_v1.yaml"
"""Every word the summary, the labels route and the read-only restore print."""

CoverageBucket = Literal["checked", "skipped", "unresolved", "failed", "out_of_scope"]
COVERAGE_BUCKETS: tuple[CoverageBucket, ...] = (
    "checked",
    "skipped",
    "unresolved",
    "failed",
    "out_of_scope",
)
"""`report/session.CoverageBucket`, copied (see the module docstring), in `Coverage`'s
order; `tests/unit/test_review_summary.py` asserts the two are one list."""

NOT_REACHED_BUCKETS: tuple[CoverageBucket, ...] = ("unresolved", "skipped", "failed")
"""The buckets that say a goal was not reached, in the order its reason is taken from."""

GroupKind = Literal["decide", "fix", "verify", "decided", "within_scope"]
OWNER_GROUPS: tuple[GroupKind, ...] = ("decide", "fix", "verify")
"""Always listed, in this order, at zero too (the owner's decision of 2026-09-23)."""
SHOWN_WHEN_HELD: tuple[GroupKind, ...] = ("decided", "within_scope")
"""Listed after the owner's three, and only when they hold a finding."""

DRAWINGS_NAMED = 10
"""How many file names each part of the drawings line names; the rest are counted. The
candidate question's bound (`checks/drawing_context.CANDIDATES_NAMED`), copied because that
module reaches the session module (see the module docstring); `tests/unit/test_review_summary.py`
asserts the two are one number."""

DRAWINGS_SEPARATOR = ". "
"""What joins the drawings line's two parts, each a sentence of its own."""

GoalState = Literal["issues", "checked", "not_reached", "not_applicable"]
GoalReason = Literal["unresolved", "skipped", "failed", "out_of_scope", "no_check"]
EvidenceStatus = Literal["open", "answered"]
ContactKind = Literal["zero_volume", "possible_only", "thread_model"]


# --- the words file ---------------------------------------------------------------------------


class HeadlineWords(ReviewModel):
    none: str
    findings_one: str
    findings_many: str
    issues_one: str
    issues_many: str

    def of(self, findings: int, issues: int) -> str:
        if findings == 0:
            return self.none
        head = self.findings_one if findings == 1 else self.findings_many.format(n=findings)
        tail = self.issues_one if issues == 1 else self.issues_many.format(n=issues)
        return f"{head} {tail}"


class CountWords(ReviewModel):
    """A sentence for exactly one, and one for every other count, zero included."""

    one: str
    many: str

    def of(self, count: int) -> str:
        return (self.one if count == 1 else self.many).format(n=count)


class GroupWords(CountWords):
    label: str


class NotLoadedWords(ReviewModel):
    text: str


class DrawingsWords(ReviewModel):
    """The drawings line's words (decision 10A): a sentence for one name and for several, per
    part, and the tail that counts the names past the bound."""

    read_one: str
    read_many: str
    candidates_one: str
    candidates_many: str
    more: str

    def named(self, names: Sequence[str]) -> str:
        """`names` as a sentence lists them; past `DRAWINGS_NAMED`, the first that many and how
        many more."""
        if len(names) <= DRAWINGS_NAMED:
            return and_list(names)
        return self.more.format(
            names=", ".join(names[:DRAWINGS_NAMED]), n=len(names) - DRAWINGS_NAMED
        )

    def of(self, read: Sequence[str], candidates: Sequence[str]) -> str:
        """The line: the drawings read, then the candidates, each part only when it names one."""
        parts = [
            (one if len(names) == 1 else many).format(names=self.named(names))
            for names, one, many in (
                (read, self.read_one, self.read_many),
                (candidates, self.candidates_one, self.candidates_many),
            )
            if names
        ]
        return DRAWINGS_SEPARATOR.join(parts)


class ResumeWords(ReviewModel):
    with_tokens: str
    without: str

    def of(self, tokens: int | None) -> str:
        return self.without if tokens is None else self.with_tokens.format(tokens=f"{tokens:,}")


class Goal(ReviewModel):
    """One check goal: the coverage rows that close it and the check ids it owns."""

    id: str
    title: str
    items: list[str]
    prefixes: list[str]


class Labels(ReviewModel):
    """The card vocabulary `GET /labels` serves, verbatim (data-model section 7)."""

    version: str
    status: dict[FindingStatus, str]
    severity: dict[Severity, str]
    bucket: dict[CoverageBucket, str]
    evidence_status: dict[EvidenceStatus, str]
    contact_kind: dict[ContactKind, str]
    errors: dict[str, str]


class Words(ReviewModel):
    """`review_words_v1.yaml`, loaded (data-model section 1). Every model refuses a key it
    does not name, so a misspelt word is an error and never a silently missing line."""

    version: str
    headline: HeadlineWords
    groups: dict[GroupKind, GroupWords]
    questions: CountWords
    not_loaded: NotLoadedWords
    drawings: DrawingsWords
    contacts: CountWords
    resume: ResumeWords
    read_only: str
    goal_states: dict[GoalState, str]
    goal_reasons: dict[GoalReason, str]
    goals: list[Goal]
    labels: Labels


@cache
def load_words() -> Words:
    """The words file, parsed once per process, like `attention.load_policy`."""
    return Words.model_validate(yaml.safe_load(WORDS_FILE.read_text(encoding="utf-8")))


# --- the summary's shapes (data-model section 2) ----------------------------------------------


class GoalCount(ReviewModel):
    goal: str
    title: str
    count: int


class SummaryGroup(ReviewModel):
    kind: GroupKind
    label: str
    count: int
    text: str
    by_goal: list[GoalCount]


class GoalLine(ReviewModel):
    goal: str
    title: str
    state: GoalState
    state_label: str
    findings: int
    reason: str | None
    detail: str | None


class EntityName(ReviewModel):
    """An id a question is about, with the component's name or the document's file name."""

    id: str
    name: str | None


class QuestionView(ReviewModel):
    id: str
    question: str
    options: list[str]
    blocks: str | None
    blocks_title: str | None
    what: str
    why: str
    about: list[EntityName]


class QuestionList(ReviewModel):
    count: int
    text: str | None
    items: list[QuestionView]


class NotLoaded(ReviewModel):
    count: int
    total: int
    text: str


class DrawingsLine(ReviewModel):
    """The drawings the review read and the same-name drawings it found but did not open, by
    file name (decision 10A), and the one line the page prints."""

    read: list[str]
    candidates: list[str]
    text: str


class ModellingPractice(ReviewModel):
    title: str
    findings: int
    rules: int
    finding_ids: list[str]


class ContactView(ReviewModel):
    id: str
    component_ids: list[str]
    names: list[str | None]
    configuration: str
    kind: str
    kind_label: str
    volume_mm3: float | None
    text: str


class ContactList(ReviewModel):
    count: int
    text: str
    items: list[ContactView]


class ReviewSummary(ReviewModel):
    version: str
    headline: str
    findings: int
    issues: int
    groups: list[SummaryGroup]
    modelling_practice: ModellingPractice | None
    questions: QuestionList
    not_loaded: NotLoaded | None
    drawings: DrawingsLine | None
    goals: list[GoalLine]
    contacts: ContactList | None
    component_names: dict[str, str]
    resume_input_tokens: int | None
    resume_text: str


class ReviewRanking(Ranking):
    """The Review tab's ranking body: `Ranking` unchanged, plus its summary.

    A subclass rather than a field on `Ranking`, so `attention.json` and both check bodies
    - which serialize `Ranking` - never carry it, and the ranking module never imports this
    one (research R2.2).
    """

    summary: ReviewSummary

    @classmethod
    def of(cls, ranking: Ranking, summary: ReviewSummary) -> ReviewRanking:
        """`ranking` with `summary` beside it, every ranking field carried as it is."""
        return cls(**dict(ranking), summary=summary)


# --- which goal a check belongs to ------------------------------------------------------------


def goal_of(check: str, goals: Sequence[Goal]) -> Goal | None:
    """The goal whose `items` name `check`, else the goal of its longest prefix, else none."""
    for goal in goals:
        if check in goal.items:
            return goal
    matches = [
        (len(prefix), goal)
        for goal in goals
        for prefix in goal.prefixes
        if check.startswith(prefix)
    ]
    if not matches:
        return None
    return max(matches, key=lambda match: match[0])[1]


# --- the summary ------------------------------------------------------------------------------


def review_ranking(
    session: ReviewSession,
    package: EvidencePackage | None,
    *,
    usage: UsageLedger | None = None,
) -> ReviewRanking:
    """`rank(session)` with its summary: what the attention, snapshot and disk routes answer.

    The rows carry the titles a person reads (`report/titles.with_display_titles`, feature 009
    decision 2A): the Review tab prints them. Order, keys and reasons are `rank`'s own, and
    `attention.json` keeps the recorded titles.
    """
    names = all_component_names(package) if package is not None else {}
    ranking = with_display_titles(rank(session), session.findings, names)
    return ReviewRanking.of(ranking, review_summary(ranking, session, package, usage=usage))


def review_summary(
    ranking: Ranking,
    session: ReviewSession,
    package: EvidencePackage | None,
    *,
    usage: UsageLedger | None = None,
) -> ReviewSummary:
    """The summary of one review (contracts/review-summary.md sections 2 to 4).

    `package` is `None` when there is none to read; the names, the parts not loaded, the
    drawings line and the "about" names are then empty. `usage` is the live run's ledger, and
    the resume cost is unknown without one (the disk route passes none).
    """
    words = load_words()
    names = _non_blank(all_component_names(package)) if package is not None else {}
    tokens = usage.last_conversation_input() if usage is not None else None
    practice = _modelling_practice(ranking)
    folded = set() if practice is None else set(practice.finding_ids)
    return ReviewSummary(
        version=words.version,
        headline=words.headline.of(len(session.findings), len(ranking.rows)),
        findings=len(session.findings),
        issues=len(ranking.rows),
        groups=_groups(
            (finding for finding in session.findings if finding.id not in folded),
            words,
            load_policy(),
        ),
        modelling_practice=practice,
        questions=_questions(session.evidence_requests, words, names, package),
        not_loaded=_not_loaded(package, words),
        drawings=drawings_of(package),
        goals=[_goal_line(goal, session, words) for goal in words.goals],
        contacts=contacts_of(session, names),
        component_names=names,
        resume_input_tokens=tokens,
        resume_text=words.resume.of(tokens),
    )


def contacts_of(session: ReviewSession, names: Mapping[str, str]) -> ContactList | None:
    """Feature 010's size-for-size contacts as the summary's list, or `None` when there are none.

    The one reader of `ReviewSession.contacts` (research R2.7), in the order feature 010
    recorded them. `names` is the summary's non-blank component names; a part without one
    is named by its id in the sentence and `None` in `names`. A contact is never a finding:
    no group, goal or headline counts it.
    """
    contacts = session.contacts
    if not contacts:
        return None
    words = load_words()
    items = [
        ContactView(
            id=contact.id,
            component_ids=list(contact.component_ids),
            names=[names.get(component) for component in contact.component_ids],
            configuration=contact.configuration,
            kind=contact.kind,
            kind_label=words.labels.contact_kind[contact.kind],
            volume_mm3=contact.volume_mm3,
            text=and_list([names.get(component, component) for component in contact.component_ids]),
        )
        for contact in contacts
    ]
    return ContactList(count=len(items), text=words.contacts.of(len(items)), items=items)


def _non_blank(names: Mapping[str, str]) -> dict[str, str]:
    return {component: name for component, name in names.items() if name.strip()}


# --- the folded family and the groups ---------------------------------------------------------


def _modelling_practice(ranking: Ranking) -> ModellingPractice | None:
    """The folded family's one line, from its ranking row (feature 008), or `None`.

    The row is the first whose `family` is set, in rank order. The contract names one such
    row - the review folds `rms` alone - and a second family, which no build writes, is
    left to the groups rather than refused: its findings are counted there as if unfolded,
    so the partition holds and no finding leaves the summary.
    """
    row = next((row for row in ranking.rows if row.family is not None), None)
    if row is None:
        return None
    return ModellingPractice(
        title=row.title,
        findings=len(row.member_finding_ids),
        # `attention._family_row` sets it on every family row; `rules` is an `int`, so a row
        # without one is refused by the model rather than given a guessed count.
        rules=row.rule_count,  # type: ignore[arg-type]
        finding_ids=list(row.member_finding_ids),
    )


def _group_of(finding: Finding, policy: Policy) -> GroupKind:
    """Research R2.3, first match winning: the order `attention._not_amplified` counts in."""
    if finding.status == SUPPRESSED_STATUS:
        return "within_scope"
    if finding.disposition is not None and finding.disposition.decision in DECIDED_DECISIONS:
        return "decided"
    if policy.needs_judgement_of(finding.check):
        return "decide"
    if finding.status == "demonstrated":
        return "fix"
    return "verify"


def _groups(findings: Iterable[Finding], words: Words, policy: Policy) -> list[SummaryGroup]:
    members: dict[GroupKind, list[Finding]] = {
        kind: [] for kind in (*OWNER_GROUPS, *SHOWN_WHEN_HELD)
    }
    for finding in findings:
        members[_group_of(finding, policy)].append(finding)
    kinds = [*OWNER_GROUPS, *(kind for kind in SHOWN_WHEN_HELD if members[kind])]
    return [
        SummaryGroup(
            kind=kind,
            label=words.groups[kind].label,
            count=len(members[kind]),
            text=words.groups[kind].of(len(members[kind])),
            by_goal=_by_goal(members[kind], words.goals),
        )
        for kind in kinds
    ]


def _by_goal(findings: Sequence[Finding], goals: Sequence[Goal]) -> list[GoalCount]:
    """The goals with a non-zero count among `findings`, in goal-table order."""
    counts = {goal.id: 0 for goal in goals}
    for finding in findings:
        goal = goal_of(finding.check, goals)
        if goal is not None:
            counts[goal.id] += 1
    return [
        GoalCount(goal=goal.id, title=goal.title, count=counts[goal.id])
        for goal in goals
        if counts[goal.id]
    ]


# --- the goal lines ---------------------------------------------------------------------------


def _goal_line(goal: Goal, session: ReviewSession, words: Words) -> GoalLine:
    """One goal's state, first match winning (contracts/review-summary.md section 3)."""
    goals = words.goals
    mapped = [finding for finding in session.findings if goal_of(finding.check, goals) is goal]
    issues = [finding for finding in mapped if finding.status != SUPPRESSED_STATUS]
    rows = {
        bucket: [
            item for item in getattr(session.coverage, bucket) if goal_of(item.check, goals) is goal
        ]
        for bucket in COVERAGE_BUCKETS
    }

    def line(
        state: GoalState, reason: GoalReason | None = None, detail: str | None = None
    ) -> GoalLine:
        return GoalLine(
            goal=goal.id,
            title=goal.title,
            state=state,
            state_label=words.goal_states[state],
            findings=len(issues),
            reason=None if reason is None else words.goal_reasons[reason],
            detail=detail,
        )

    if issues:
        return line("issues")
    closeout = _first(rows, lambda item: item.check in goal.items)
    if closeout is not None:
        return line("not_reached", *closeout)
    if not mapped and not any(rows.values()):
        return line("not_reached", "no_check")
    if rows["checked"] or mapped:
        # `mapped` holds within-scope findings only here: `issues` was empty.
        return line("checked")
    rule_row = _first(rows, lambda item: True)
    if rule_row is not None:
        # The case the contract's four rows leave open: only rule rows, none checked, and
        # at least one of them unresolved, skipped or failed.
        return line("not_reached", *rule_row)
    # Every row left is out of scope, and there is at least one: `no_check` took the rest.
    return line("not_applicable", "out_of_scope", rows["out_of_scope"][0].reason)


def _first(
    rows: Mapping[CoverageBucket, Sequence[CoverageItem]],
    wanted: Callable[[CoverageItem], bool],
) -> tuple[GoalReason, str] | None:
    """The bucket and reason of the first `wanted` row in unresolved, skipped, failed order."""
    for bucket in NOT_REACHED_BUCKETS:
        for item in rows[bucket]:
            if wanted(item):
                return bucket, item.reason
    return None


# --- questions and parts not loaded -----------------------------------------------------------


def _questions(
    requests: Iterable[EvidenceRequest],
    words: Words,
    names: Mapping[str, str],
    package: EvidencePackage | None,
) -> QuestionList:
    """The open evidence requests, in session order (contracts/questions.md section 3)."""
    documents = (
        {document.document_id: document.file_name for document in package.documents}
        if package
        else {}
    )
    items = [
        QuestionView(
            id=request.id,
            question=request.question if request.question is not None else request.what,
            options=list(request.options),
            blocks=request.blocks,
            blocks_title=_blocks_title(request.blocks, words.goals),
            what=request.what,
            why=request.why,
            about=[
                EntityName(id=entity, name=names.get(entity, documents.get(entity)))
                for entity in request.entity_ids
            ],
        )
        for request in requests
        if request.status == "open"
    ]
    return QuestionList(
        count=len(items),
        text=words.questions.of(len(items)) if items else None,
        items=items,
    )


def _blocks_title(blocks: str | None, goals: Sequence[Goal]) -> str | None:
    """The title of the goal whose `items` hold the checklist item a request blocks."""
    if blocks is None:
        return None
    goal = next((goal for goal in goals if blocks in goal.items), None)
    return None if goal is None else goal.title


def drawings_of(package: EvidencePackage | None) -> DrawingsLine | None:
    """The drawings line (contracts/review-summary.md section 4, decision 10A), or `None` when
    there is no package, or it holds no drawing read and no candidate.

    A drawing is **read** when the package holds its native record or a PDF-ingested sheet of
    it: named by its document's file name, its id where the package has no row for it, once, in
    document-id order. A **candidate** is a same-name drawing file beside a reviewed document
    that nothing opened: named by its path's file name, in its document's id order, once per
    file - a part and an assembly of one stem share one - and never a file the review read. A
    candidate the engineer confirmed, which the product then opened and read (feature 011
    `contracts/confirmed-open.md`), is read, whether or not the package still holds its row.
    """
    if package is None:
        return None
    documents = {document.document_id: document for document in package.documents}
    read_ids = sorted(
        {record.document_id for record in package.drawing_records}
        | {sheet.document_id for sheet in package.drawings},
        key=lambda document_id: (id_order(document_id), document_id),
    )
    files_named = {
        _file_key(documents[document_id].path)
        for document_id in read_ids
        if document_id in documents
    }
    candidates: list[str] = []
    for candidate in sorted(
        package.drawing_candidates, key=lambda item: id_order(item.document_id)
    ):
        key = _file_key(candidate.path)
        if key not in files_named:
            files_named.add(key)
            candidates.append(file_name(candidate.path))
    read = [
        documents[document_id].file_name if document_id in documents else document_id
        for document_id in read_ids
    ]
    if not read and not candidates:
        return None
    return DrawingsLine(
        read=read, candidates=candidates, text=load_words().drawings.of(read, candidates)
    )


def _file_key(path: str) -> str:
    """One file however its path is spelled: case and the separator ignored, as the extractor's
    discovery compares two paths."""
    return path.replace("/", "\\").casefold()


def _not_loaded(package: EvidencePackage | None, words: Words) -> NotLoaded | None:
    """`{count, total, text}` from `not_examined`, or `None` when every instance was read."""
    if package is None:
        return None
    block = not_examined(package)
    if block is None:
        return None
    count, total = len(block.instances), len(package.components)
    return NotLoaded(
        count=count, total=total, text=words.not_loaded.text.format(count=count, total=total)
    )
