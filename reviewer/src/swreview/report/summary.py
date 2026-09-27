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
`standards.drawing.*` speaks for drawings and never also for standards.

**A goal's state is a fixed precedence** (contracts/review-summary.md section 3): issues,
then not reached, then checked, then not applicable. One case the contract's four rows left
open - only rule rows that are unresolved, skipped or failed - reads not reached, its
reason from the first of them, so every goal has a state.

The goals, `goal_of` and the goal lines live in `report/finding_groups.py` since feature 013,
where each goal names the group its findings are listed under (013 research R2.14); they are
imported here and exported from here as before.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import model_validator

from swreview.drawings.evidence import file_key, file_name, id_order
from swreview.findings import Finding, FindingStatus, ReviewModel, Severity
from swreview.ir.models import EvidencePackage
from swreview.report.attention import (
    SUPPRESSED_STATUS,
    Policy,
    Ranking,
    is_decided,
    load_policy,
    rank,
)
from swreview.report.finding_groups import (
    COVERAGE_BUCKETS,
    CheckedFoldWords,
    CoverageBucket,
    FindingGroupText,
    FindingGroupWords,
    FindingsByType,
    Goal,
    GoalLine,
    GoalReason,
    GoalState,
    findings_by_type,
    goal_lines,
    goal_of,
)
from swreview.report.names import and_list
from swreview.report.names import component_names as all_component_names
from swreview.report.titles import with_display_titles
from swreview.report.unexamined import not_examined

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only, never at run time
    from swreview.agent.events import UsageLedger
    from swreview.report.session import EvidenceRequest, ReviewSession

__all__ = [
    "COVERAGE_BUCKETS",
    "DRAWINGS_NAMED",
    "WORDS_FILE",
    "ContactList",
    "ContactView",
    "DrawingsLine",
    "EntityName",
    "Goal",
    "GoalLine",
    "Labels",
    "NotLoaded",
    "NotReached",
    "QuestionList",
    "QuestionView",
    "ReviewRanking",
    "ReviewSummary",
    "SummaryGroup",
    "Tally",
    "Words",
    "contacts_of",
    "drawings_of",
    "goal_lines",
    "goal_of",
    "load_words",
    "review_ranking",
    "review_summary",
]

WORDS_FILE = Path(__file__).parent / "review_words_v1.yaml"
"""Every word the summary, the labels route and the read-only restore print."""

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

EvidenceStatus = Literal["open", "answered"]
ContactKind = Literal["zero_volume", "possible_only", "thread_model"]


# --- the words file ---------------------------------------------------------------------------


class HeadlineWords(ReviewModel):
    none: str
    findings_one: str
    findings_many: str
    issues_one: str
    issues_many: str
    checked: str

    def of(self, findings: int, issues: int, checked: int, separator: str) -> str:
        """"{n} findings in {m} issues · {k} checked, no issue" (feature 013): `findings` the
        ones in issues, `checked` the passes; each part only when it counts something, and
        the `none` sentence when neither does."""
        parts: list[str] = []
        if findings:
            head = self.findings_one if findings == 1 else self.findings_many.format(n=findings)
            tail = self.issues_one if issues == 1 else self.issues_many.format(n=issues)
            parts.append(f"{head} {tail}")
        if checked:
            parts.append(self.checked.format(n=checked))
        return separator.join(parts) if parts else self.none


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


class TallyWords(ReviewModel):
    """The tally's one line (feature 013): each owner group's label and count, then Decided."""

    item: str


class ResumeWords(ReviewModel):
    with_tokens: str
    without: str

    def of(self, tokens: int | None) -> str:
        return self.without if tokens is None else self.with_tokens.format(tokens=f"{tokens:,}")


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
    does not name, so a misspelt word is an error and never a silently missing line.

    The groups (feature 013) are checked against the goals when the file loads: a goal naming
    a group the file does not list, a group listed twice, or "Other checks" sharing a type
    group's id would each file findings under a heading nobody renders, so each is refused by
    name rather than discovered on the page.
    """

    version: str
    headline: HeadlineWords
    separator: str
    groups: dict[GroupKind, GroupWords]
    tally: TallyWords
    not_reached: str
    questions: CountWords
    not_loaded: NotLoadedWords
    drawings: DrawingsWords
    contacts: CountWords
    resume: ResumeWords
    read_only: str
    goal_states: dict[GoalState, str]
    goal_reasons: dict[GoalReason, str]
    goals: list[Goal]
    finding_groups: list[FindingGroupWords]
    finding_group_other: FindingGroupWords
    finding_group_checked: CheckedFoldWords
    finding_group_text: FindingGroupText
    labels: Labels

    @model_validator(mode="after")
    def _every_goal_names_a_listed_group(self) -> Words:
        ids = [group.id for group in self.finding_groups]
        repeated = sorted({one for one in ids if ids.count(one) > 1})
        if repeated:
            raise ValueError(f"finding_groups lists {', '.join(repeated)} more than once")
        if self.finding_group_other.id in ids:
            raise ValueError(
                f"finding_group_other's id {self.finding_group_other.id} is a type group's id"
            )
        unknown = [goal.id for goal in self.goals if goal.group not in ids]
        if unknown:
            raise ValueError(
                f"goals {', '.join(unknown)} name a group finding_groups does not list"
            )
        return self


@cache
def load_words() -> Words:
    """The words file, parsed once per process, like `attention.load_policy`."""
    return Words.model_validate(yaml.safe_load(WORDS_FILE.read_text(encoding="utf-8")))


# --- the summary's shapes (data-model section 2) ----------------------------------------------


class SummaryGroup(ReviewModel):
    kind: GroupKind
    label: str
    count: int
    text: str


class Tally(ReviewModel):
    """"Decide {a} · Fix {b} · Verify {c}", then " · Decided {d}" when any (feature 013)."""

    text: str


class NotReached(ReviewModel):
    """The goals not reached, by title in goal order, and the one line that names them."""

    titles: list[str]
    text: str


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
    tally: Tally
    questions: QuestionList
    not_loaded: NotLoaded | None
    drawings: DrawingsLine | None
    not_reached: NotReached | None
    contacts: ContactList | None
    component_names: dict[str, str]
    resume_input_tokens: int | None
    resume_text: str


class ReviewRanking(Ranking):
    """The Review tab's ranking body: `Ranking` unchanged, plus its summary and its findings
    by type (feature 013).

    A subclass rather than fields on `Ranking`, so `attention.json` and both check bodies
    - which serialize `Ranking` - never carry them, and the ranking module never imports this
    one (research R2.2). Every route that answers one (attention, snapshot, disk) builds it
    with `review_ranking` from the session, so there is no ranking without `groups` for the
    page to fall back from (013 `contracts/grouped-list.md` section 3).
    """

    summary: ReviewSummary
    groups: FindingsByType

    @classmethod
    def of(cls, ranking: Ranking, summary: ReviewSummary, groups: FindingsByType) -> ReviewRanking:
        """`ranking` with `summary` and `groups` beside it, every ranking field as it is."""
        return cls(**dict(ranking), summary=summary, groups=groups)


# --- the summary ------------------------------------------------------------------------------


def review_ranking(
    session: ReviewSession,
    package: EvidencePackage | None,
    *,
    usage: UsageLedger | None = None,
) -> ReviewRanking:
    """`rank(session)` with its summary and its findings by type: what the attention,
    snapshot and disk routes answer.

    The rows carry the titles a person reads (`report/titles.with_display_titles`, feature 009
    decision 2A): the Review tab prints them. Order, keys and reasons are `rank`'s own, and
    `attention.json` keeps the recorded titles. `groups` is `findings_by_type` over the same
    session, policy and package (feature 013).
    """
    names = all_component_names(package) if package is not None else {}
    policy = load_policy()
    ranking = with_display_titles(rank(session, policy), session.findings, names)
    groups = findings_by_type(session, package, load_words(), policy)
    return ReviewRanking.of(ranking, review_summary(groups, session, package, usage=usage), groups)


def review_summary(
    groups: FindingsByType,
    session: ReviewSession,
    package: EvidencePackage | None,
    *,
    usage: UsageLedger | None = None,
) -> ReviewSummary:
    """The summary of one review (contracts/review-summary.md sections 2 to 4, as feature 013
    amended them).

    `groups` is the session's findings by type (`report/finding_groups.findings_by_type`), whose
    rows are the issues the headline counts and whose fold holds the passes it counts as
    checked. `package` is `None` when there is none to read; the names, the parts not loaded,
    the drawings line and the "about" names are then empty. `usage` is the live run's ledger,
    and the resume cost is unknown without one (the disk route passes none).
    """
    words = load_words()
    names = _non_blank(all_component_names(package)) if package is not None else {}
    tokens = usage.last_conversation_input() if usage is not None else None
    checked = groups.checked.findings if groups.checked is not None else 0
    issues = sum(len(group.rows) for group in groups.groups)
    summary_groups = _groups(session.findings, words, load_policy())
    return ReviewSummary(
        version=words.version,
        headline=words.headline.of(
            len(session.findings) - checked, issues, checked, words.separator
        ),
        findings=len(session.findings),
        issues=issues,
        groups=summary_groups,
        tally=_tally(summary_groups, words),
        questions=_questions(session.evidence_requests, words, names, package),
        not_loaded=_not_loaded(package, words),
        drawings=drawings_of(package),
        not_reached=_not_reached(goal_lines(session, words), words),
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


# --- the groups, the tally and the goals not reached --------------------------------------------


def _group_of(finding: Finding, policy: Policy) -> GroupKind:
    """Research R2.3, first match winning: the order `attention._not_amplified` counts in."""
    if finding.status == SUPPRESSED_STATUS:
        return "within_scope"
    if is_decided(finding):
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
        )
        for kind in kinds
    ]


TALLIED: tuple[GroupKind, ...] = (*OWNER_GROUPS, "decided")
"""The groups the tally names: the owner's three always, Decided only when it holds a finding.
The passes are the headline's "checked, no issue", not a tally entry."""


def _tally(groups: Sequence[SummaryGroup], words: Words) -> Tally:
    """"Decide {a} · Fix {b} · Verify {c}", then " · Decided {d}" (feature 013)."""
    return Tally(
        text=words.separator.join(
            words.tally.item.format(label=group.label, n=group.count)
            for group in groups
            if group.kind in TALLIED
        )
    )


def _not_reached(lines: Sequence[GoalLine], words: Words) -> NotReached | None:
    """The goals whose line reads not reached, in goal order, or `None` when every goal was
    reached: the first screen still names the coverage gaps once the goal lines live under
    their groups (feature 013)."""
    titles = [line.title for line in lines if line.state == "not_reached"]
    if not titles:
        return None
    return NotReached(titles=titles, text=words.not_reached.format(titles=and_list(titles)))


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
        file_key(documents[document_id].path)
        for document_id in read_ids
        if document_id in documents
    }
    candidates: list[str] = []
    for candidate in sorted(
        package.drawing_candidates, key=lambda item: id_order(item.document_id)
    ):
        key = file_key(candidate.path)
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
