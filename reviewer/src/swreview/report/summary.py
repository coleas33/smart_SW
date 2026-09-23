"""The review summary: what matters in ten seconds, computed once (feature 009 US3).

The Review tab prints a summary above everything else - how many findings in how many
issues, which of them are the engineer's to decide, to fix and to verify, the questions
waiting, the parts not loaded, and one line per check goal - and **computes none of it**
(FR-009). This module is where it is computed, from the ranking, the session and the
package, in words read from `review_words_v1.yaml` (research R2.5).

It is pure: it reads its arguments and the words file, imports no provider and no
settings, and writes nothing. `report/attention.py` does not import it, so the ranking,
`attention.json` and both check bodies are exactly what they were before this feature
(research R2.2).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

import yaml

from swreview.findings import FindingStatus, ReviewModel, Severity
from swreview.report.session import CoverageBucket

__all__ = [
    "WORDS_FILE",
    "Goal",
    "Labels",
    "Words",
    "load_words",
]

WORDS_FILE = Path(__file__).parent / "review_words_v1.yaml"
"""Every word the summary, the labels route and the read-only restore print."""

GroupKind = Literal["decide", "fix", "verify", "decided", "within_scope"]
GoalState = Literal["issues", "checked", "not_reached", "not_applicable"]
GoalReason = Literal["unresolved", "skipped", "failed", "out_of_scope", "no_check"]
EvidenceStatus = Literal["open", "answered"]
ContactKind = Literal["zero_volume", "possible_only", "thread_model"]


# --- the words file ------------------------------------------------------------------------


class HeadlineWords(ReviewModel):
    none: str
    findings_one: str
    findings_many: str
    issues_one: str
    issues_many: str


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


class ResumeWords(ReviewModel):
    with_tokens: str
    without: str


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
