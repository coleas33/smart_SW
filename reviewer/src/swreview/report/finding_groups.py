"""Findings by type: the goals, their groups, and the grouped view (feature 013 US2).

The Review tab used to show one review's findings three ways - the Decide, Fix and Verify
counts per goal, a five-row Start here with "Show all", and the cards in arrival order - and
the five rows took passes (013 research R2.12). `findings_by_type` is the one grouped view
that replaces them, on the Review tab and in `report.md` (013 `contracts/grouped-list.md`):

- **one taxonomy** (section 2, research R2.14). A check's group is its goal's group: the goals
  of `review_words_v1.yaml` name the check ids they own, as feature 009 decided, and each goal
  names its group; a second prefix table would drift from the first. So the goal table,
  `goal_of` and the goal lines live here, beside the view that reads them, and
  `report/summary.py` imports them (and still exports them, so every earlier import works);
- **one order** (section 3, research R2.15). Rows are `attention.ranked_rows` with every family
  unfolded - the group is the fold now - and the same-check fold of disjoint subjects kept. One
  pass puts each row in its group, so every group keeps the policy's order; a group's decided
  rows then move to its end, keeping theirs. Nothing here sorts by a second rule;
- **no pass in a type group** (research R2.16): a row whose status is `checked_within_scope`
  goes to the one "Checked, no issue" fold;
- **every word is the backend's** (FR-022): a row's fold count, reach and card-title flag and
  a group's count line are worded here, so the page counts, pluralises and compares nothing.

**The partition** holds by construction: `ranked_rows` folds every finding into exactly one
row, and each row goes to exactly one group or to the fold (`test_finding_groups.py`).

Pure: it reads its arguments, imports no provider and no settings, and writes nothing.
`report/summary.py` imports this module and never the reverse, so the words model it reads is a
type-checking import only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Literal

from swreview.findings import Finding, ReviewModel
from swreview.ir.models import EvidencePackage
from swreview.report.attention import (
    SUPPRESSED_STATUS,
    AttentionRow,
    Policy,
    is_decided,
    persisted_explanation,
    ranked_rows,
)
from swreview.report.names import component_names
from swreview.report.titles import titled_rows

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only, never at run time
    from swreview.report.session import CoverageItem, ReviewSession
    from swreview.report.summary import Words

__all__ = [
    "COVERAGE_BUCKETS",
    "CheckedFold",
    "CheckedFoldWords",
    "CoverageBucket",
    "FindingGroupText",
    "FindingGroupWords",
    "FindingsByType",
    "Goal",
    "GoalLine",
    "GoalReason",
    "GoalState",
    "GroupRow",
    "TypeGroup",
    "findings_by_type",
    "goal_lines",
    "goal_of",
]

CoverageBucket = Literal["checked", "skipped", "unresolved", "failed", "out_of_scope"]
COVERAGE_BUCKETS: tuple[CoverageBucket, ...] = (
    "checked",
    "skipped",
    "unresolved",
    "failed",
    "out_of_scope",
)
"""`report/session.CoverageBucket`, copied because that module pulls the provider port in, in
`Coverage`'s order; `tests/unit/test_review_summary.py` asserts the two are one list."""

NOT_REACHED_BUCKETS: tuple[CoverageBucket, ...] = ("unresolved", "skipped", "failed")
"""The buckets that say a goal was not reached, in the order its reason is taken from."""

GoalState = Literal["issues", "checked", "not_reached", "not_applicable"]
GoalReason = Literal["unresolved", "skipped", "failed", "out_of_scope", "no_check"]

GOAL_STATE_PRECEDENCE: tuple[GoalState, ...] = (
    "issues",
    "not_reached",
    "checked",
    "not_applicable",
)
"""Feature 009's order of the goal states (its `contracts/review-summary.md` section 3): which
goal line speaks for a type group that holds no row. It names every `GoalState`."""


# --- the words this module reads ---------------------------------------------------------------


class FindingGroupWords(ReviewModel):
    """One group of findings: its id, its heading, and whether it arrives open."""

    id: str
    title: str
    open: bool


class CheckedFoldWords(ReviewModel):
    """The one fold every pass sits in, and the tail a waived pass carries."""

    title: str
    open: bool
    exception_tail: str


class FindingGroupText(ReviewModel):
    """A group's count line and a row's fold count and reach, worded here and nowhere else."""

    one: str
    many: str
    decided: str
    fold_tail: str
    reach_one: str
    reach_many: str


class Goal(ReviewModel):
    """One check goal: the coverage rows that close it, the check ids it owns, its group."""

    id: str
    title: str
    items: list[str]
    prefixes: list[str]
    group: str


class GoalLine(ReviewModel):
    goal: str
    title: str
    state: GoalState
    state_label: str
    findings: int
    reason: str | None
    detail: str | None


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


# --- the goal lines ---------------------------------------------------------------------------


def goal_lines(session: ReviewSession, words: Words) -> list[GoalLine]:
    """One line per goal, in the words file's order (feature 009 `contracts/review-summary.md`
    section 3): each finding and each coverage row counted for its one goal (`goal_of`), in
    one pass over each, then each goal's state first match winning."""
    goals = words.goals
    mapped: dict[str, list[Finding]] = {goal.id: [] for goal in goals}
    rows: dict[str, dict[CoverageBucket, list[CoverageItem]]] = {
        goal.id: {bucket: [] for bucket in COVERAGE_BUCKETS} for goal in goals
    }
    for finding in session.findings:
        goal = goal_of(finding.check, goals)
        if goal is not None:
            mapped[goal.id].append(finding)
    for bucket in COVERAGE_BUCKETS:
        for item in getattr(session.coverage, bucket):
            goal = goal_of(item.check, goals)
            if goal is not None:
                rows[goal.id][bucket].append(item)
    return [_goal_line(goal, mapped[goal.id], rows[goal.id], words) for goal in goals]


def _goal_line(
    goal: Goal,
    mapped: Sequence[Finding],
    rows: Mapping[CoverageBucket, Sequence[CoverageItem]],
    words: Words,
) -> GoalLine:
    """One goal's state, first match winning (feature 009 `contracts/review-summary.md` 3)."""
    issues = [finding for finding in mapped if finding.status != SUPPRESSED_STATUS]

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


# --- the grouped view (013 contracts/grouped-list.md section 3) ------------------------------


class GroupRow(AttentionRow):
    """One row of a type group or of the checked fold: an attention row and its words.

    Every word the page prints about the row is here, so the page counts, pluralises and
    compares nothing (FR-022): the fold count and a waived pass's tail (`tail_text`), the reach
    of a folded row (`reach_text`), and whether a single member's card would repeat the row's
    title (`hide_card_title`). The three are always serialized, `null` included, so the page
    honours what it is given rather than inferring it from a missing key.
    """

    tail_text: str | None
    reach_text: str | None
    hide_card_title: bool


class TypeGroup(ReviewModel):
    """One group of findings: its rows in the policy's order, decided last, and its goals."""

    id: str
    title: str
    open: bool
    findings: int
    decided: int
    text: str
    rows: list[GroupRow]
    goals: list[GoalLine]


class CheckedFold(ReviewModel):
    """Every pass, in one fold after the groups."""

    title: str
    open: bool
    findings: int
    text: str
    rows: list[GroupRow]


class FindingsByType(ReviewModel):
    """`groups` in the words file's order - every group with a row or a goal, "Other checks"
    last and only when it holds a row - then `checked`, `None` when nothing passed."""

    version: Literal[1]
    groups: list[TypeGroup]
    checked: CheckedFold | None


def findings_by_type(
    session: ReviewSession,
    package: EvidencePackage | None,
    words: Words,
    policy: Policy,
) -> FindingsByType:
    """Every finding of `session` in one row of one group, or in the checked fold.

    Rows are `ranked_rows(session.findings, policy, families=())`: the modelling-practice
    family is unfolded, because the group is the fold now, and the same-check fold of disjoint
    subjects is kept. Rows carry the display titles a person reads (`report/titles`, parts
    named from `package` when there is one) and the persisted explanation of their own finding
    id. One pass puts each row in its group - a pass in the fold - so every group keeps the
    policy's order; within a group the decided rows then move to its end, keeping theirs.
    """
    names = component_names(package) if package is not None else {}
    by_id = {finding.id: finding for finding in session.findings}
    other = words.finding_group_other
    placed: dict[str, list[GroupRow]] = {one.id: [] for one in (*words.finding_groups, other)}
    checked: list[GroupRow] = []
    for row in titled_rows(ranked_rows(session.findings, policy, ()), session.findings, names):
        members = [by_id[member] for member in row.member_finding_ids]
        passed = row.status == SUPPRESSED_STATUS
        grouped = _group_row(
            row, members, passed, persisted_explanation(session, row.finding_id), words
        )
        if passed:
            checked.append(grouped)
            continue
        goal = goal_of(row.check, words.goals)
        placed[other.id if goal is None else goal.group].append(grouped)

    lines = goal_lines(session, words)
    groups: list[TypeGroup] = []
    for one in words.finding_groups:
        goals = [
            line for goal, line in zip(words.goals, lines, strict=True) if goal.group == one.id
        ]
        if placed[one.id] or goals:
            groups.append(_type_group(one, placed[one.id], goals, by_id, words))
    if placed[other.id]:
        groups.append(_type_group(other, placed[other.id], [], by_id, words))
    return FindingsByType(
        version=1,
        groups=groups,
        checked=_checked_fold(checked, words) if checked else None,
    )


def _group_row(
    row: AttentionRow,
    members: Sequence[Finding],
    passed: bool,
    explanation: str | None,
    words: Words,
) -> GroupRow:
    """`row` with its words: the fold count and a waived pass's tail, the reach, the flag.

    A pass's tail claims the accepted exception only when every member carries one: a fold
    does not read `exception_id`, so a clean pass can share a row with a waived one, and the
    row must not say the clean one was waived.
    """
    text = words.finding_group_text
    folded = len(members) > 1
    tails = [text.fold_tail.format(n=len(members))] if folded else []
    if passed and all(member.exception_id is not None for member in members):
        tails.append(words.finding_group_checked.exception_tail)
    return GroupRow(
        **{**dict(row), "explanation": explanation},
        tail_text=words.separator.join(tails) if tails else None,
        reach_text=_reach_text(len(row.component_ids), words) if folded else None,
        hide_card_title=not folded,
    )


def _reach_text(components: int, words: Words) -> str | None:
    """How many parts a folded row reaches, or `None` when it names none."""
    text = words.finding_group_text
    if components == 0:
        return None
    return text.reach_one if components == 1 else text.reach_many.format(n=components)


def _type_group(
    group: FindingGroupWords,
    rows: Sequence[GroupRow],
    goals: Sequence[GoalLine],
    by_id: Mapping[str, Finding],
    words: Words,
) -> TypeGroup:
    """One group: its rows, decided last in their order, its counts and its goal lines.

    In a type group a suppressed row is a decided one - every pass went to the fold - and it
    already sorts after every undecided row by key 1; moving it is stated here all the same, so
    the rule is this module's and not a property of the key it happens to follow. The decided
    count is of findings, as the group's count is: a fold does not read the disposition, so a
    decided row can hold an undecided member.
    """
    ordered = [row for row in rows if not row.key.suppressed]
    ordered += [row for row in rows if row.key.suppressed]
    findings = sum(len(row.member_finding_ids) for row in ordered)
    decided = sum(
        1 for row in ordered for member in row.member_finding_ids if is_decided(by_id[member])
    )
    return TypeGroup(
        id=group.id,
        title=group.title,
        open=group.open,
        findings=findings,
        decided=decided,
        text=_count_text(findings, decided, words) if ordered else _goal_text(goals),
        rows=ordered,
        goals=list(goals),
    )


def _checked_fold(rows: Sequence[GroupRow], words: Words) -> CheckedFold:
    fold = words.finding_group_checked
    findings = sum(len(row.member_finding_ids) for row in rows)
    return CheckedFold(
        title=fold.title,
        open=fold.open,
        findings=findings,
        text=_count_text(findings, 0, words),
        rows=list(rows),
    )


def _count_text(findings: int, decided: int, words: Words) -> str:
    """The count line, "3 findings", then " · 1 decided" when any of them is decided."""
    text = words.finding_group_text
    count = text.one if findings == 1 else text.many.format(n=findings)
    if not decided:
        return count
    return words.separator.join((count, text.decided.format(d=decided)))


def _goal_text(goals: Sequence[GoalLine]) -> str:
    """What a group with no row says: its first goal line's state in feature 009's precedence
    (issues, not reached, checked, not applicable), with that line's reason. A group with no row
    has a goal, or it is not rendered, and the precedence names every state."""
    line = next(line for state in GOAL_STATE_PRECEDENCE for line in goals if line.state == state)
    return line.state_label if line.reason is None else f"{line.state_label} ({line.reason})"
