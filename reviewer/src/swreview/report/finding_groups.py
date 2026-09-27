"""Findings by type: the goals, their groups, and the grouped view (feature 013 US2).

The Review tab used to show one review's findings three ways - the Decide, Fix and Verify
counts per goal, a five-row Start here with "Show all", and the cards in arrival order - and
the five rows took passes (013 research R2.12). The grouped view that replaces them, on the
Review tab and in `report.md`, rests on **one taxonomy** (013 `contracts/grouped-list.md`
section 2, research R2.14): a check's group is its goal's group. The goals of
`review_words_v1.yaml` name the check ids they own, as feature 009 decided, and each goal names
its group; a second prefix table would drift from the first. So the goal table, `goal_of` and
the goal lines live here, beside the view that reads them, and `report/summary.py` imports them
(and still exports them, so every earlier import keeps working).

Pure: it reads its arguments, imports no provider and no settings, and writes nothing.
`report/summary.py` imports this module and never the reverse, so the words model it reads is a
type-checking import only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Literal

from swreview.findings import Finding, ReviewModel
from swreview.report.attention import SUPPRESSED_STATUS

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only, never at run time
    from swreview.report.session import CoverageItem, ReviewSession
    from swreview.report.summary import Words

__all__ = [
    "COVERAGE_BUCKETS",
    "CheckedFoldWords",
    "CoverageBucket",
    "FindingGroupText",
    "FindingGroupWords",
    "Goal",
    "GoalLine",
    "GoalReason",
    "GoalState",
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
