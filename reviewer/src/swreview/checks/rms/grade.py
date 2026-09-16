"""How much of the method a model follows, as counts - never as a letter (T069).

`plan.md` key point 10 is the whole design, and it is one paragraph long: the headline is
counts per bucket, the fraction `checked / (checked + failed + warned)` is secondary and
is absent rather than zero when nothing was graded, and the unresolved rule ids are always
named beside the counts. **No letter.** A letter compresses six honest numbers and a list
of rules nobody could evaluate into one confident character, which is exactly the
unsupported artefact constitution Principle I exists to prevent; nothing here produces one
and no consumer can ask for one.

The grade is taken over either of the two shapes a check has at hand, because they are the
same run at two moments:

- a **`ReviewSession`**, which is what `run_rms_check` and `POST /checks/rms` grade. This
  is the authoritative one: the rule layer says `fail` for a condition an engineer has
  already accepted, and it is `report.py` that turns it into a `checked_within_scope`
  finding when the exception store matches, so only the recorded session knows an
  acceptance happened. It also holds the ten never-dispatched rules - four data gaps,
  six out of scope - which belong in the counts rather than in a footnote;
- a sequence of **`RuleResult`s**, before anything is recorded. Feature 004 evaluates a
  tree it has just re-modelled and wants a number for it without writing a session first.

Both funnel into `RmsGrade.of`, so "what a bucket means" and "what the fraction is" are
written once and the two sources differ only in how they name their buckets.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from swreview.checks.rms.registry import RULES
from swreview.checks.rms.results import RuleResult
from swreview.findings import FindingStatus
from swreview.report.session import CoverageBucket, ReviewSession

__all__ = ["BUCKETS", "GradeBucket", "RmsGrade", "RmsGradeDelta", "delta", "grade"]

GradeBucket = Literal["failed", "warned", "checked", "skipped", "unresolved", "out_of_scope"]

BUCKETS: tuple[GradeBucket, ...] = (
    "failed",
    "warned",
    "checked",
    "skipped",
    "unresolved",
    "out_of_scope",
)
"""The six buckets, in the order they are read: what went wrong first, what could not be
evaluated last."""

_GRADED: tuple[GradeBucket, ...] = ("checked", "failed", "warned")
"""The buckets the fraction is over: the rules that reached a verdict. A skipped rule had
nothing to grade and an unresolved one could not be graded; counting either would turn a
missing input into a score."""

_BUCKET_BY_OUTCOME: dict[str, GradeBucket] = {
    "fail": "failed",
    "warn": "warned",
    "pass": "checked",
    "waived": "checked",
    "skip": "skipped",
    "unresolved": "unresolved",
}
"""A rule layer outcome to its bucket. `waived` is `checked`: an accepted condition is
reported as checked within scope, and SC-010 is precisely that the rule stops reading as a
failure once the engineer has accepted it."""

_BUCKET_BY_FINDING_STATUS: dict[FindingStatus, GradeBucket] = {
    "demonstrated": "failed",
    "suspected": "warned",
    "checked_within_scope": "checked",
    "unresolved": "unresolved",
}
"""A recorded finding's status to its bucket - the same mapping seen from the other side
of `results.py`'s `_STATUS_BY_OUTCOME`, plus the `unresolved` status no RMS rule writes as
a finding but which is in the `Finding` contract."""

_COVERAGE_BUCKETS: tuple[CoverageBucket, ...] = (
    "checked",
    "skipped",
    "unresolved",
    "out_of_scope",
)
"""The coverage buckets a rule's aggregated item can be in. `failed` holds tool failures
(`tools/registry.py`), which are not rule results and are never graded as one."""


@dataclass(frozen=True)
class RmsGrade:
    """What a check concluded, counted. Six numbers, a fraction, and the rules it could
    not evaluate, named."""

    failed: int = 0
    warned: int = 0
    checked: int = 0
    skipped: int = 0
    unresolved: int = 0
    out_of_scope: int = 0
    unresolved_rule_ids: tuple[str, ...] = ()
    """Every rule that landed in `unresolved`, sorted and named once however many
    documents it was unresolved on. Counts alone would say how much is missing without
    saying what, which is the one thing a reader has to act on."""

    @classmethod
    def of(cls, counted: Sequence[GradeBucket], unresolved_rule_ids: Iterable[str]) -> RmsGrade:
        """One grade over `counted`, one entry per rule result, however it was reached."""
        return cls(
            failed=counted.count("failed"),
            warned=counted.count("warned"),
            checked=counted.count("checked"),
            skipped=counted.count("skipped"),
            unresolved=counted.count("unresolved"),
            out_of_scope=counted.count("out_of_scope"),
            unresolved_rule_ids=tuple(sorted(set(unresolved_rule_ids))),
        )

    @property
    def counts(self) -> dict[GradeBucket, int]:
        """The six counts in `BUCKETS` order."""
        return {bucket: getattr(self, bucket) for bucket in BUCKETS}

    @property
    def total(self) -> int:
        """Every rule result counted, in every bucket."""
        return sum(self.counts.values())

    @property
    def graded(self) -> int:
        """The rule results that reached a verdict: the fraction's denominator."""
        return sum(getattr(self, bucket) for bucket in _GRADED)

    @property
    def fraction(self) -> float | None:
        """`checked / (checked + failed + warned)`, or `None` when nothing was graded.

        `None`, not `0.0`: a run where every rule was skipped or unresolved has no
        fraction to state, and zero would read as "everything failed".
        """
        if self.graded == 0:
            return None
        return self.checked / self.graded

    @property
    def nothing_evaluated(self) -> bool:
        """Whether no rule reached any bucket at all - not a perfect score."""
        return self.total == 0

    def as_dict(self) -> dict[str, object]:
        """The grade as the route renders it (`contracts/model-check.md`, `CheckResult`).

        The unresolved ids are in the same object as the counts on purpose: a page cannot
        render a score from this without having been handed the rules behind it.
        """
        return {
            **self.counts,
            "fraction": self.fraction,
            "unresolved_rule_ids": list(self.unresolved_rule_ids),
        }

    def summary(self) -> str:
        """One line for a log or a command line; never a letter and never a bare number."""
        if self.nothing_evaluated:
            return "nothing evaluated"
        counts = ", ".join(
            f"{count} {bucket.replace('_', ' ')}" for bucket, count in self.counts.items()
        )
        fraction = "" if self.fraction is None else f"; {self.fraction:.2f} of the graded rules"
        unresolved = (
            ""
            if not self.unresolved_rule_ids
            else f"; unresolved: {', '.join(self.unresolved_rule_ids)}"
        )
        return f"{counts}{fraction}{unresolved}"


@dataclass(frozen=True)
class RmsGradeDelta:
    """Two grades of the same part, and what moved between them.

    Feature 004 re-models a tree and has to say what its change did; a pair of counts with
    the rules that stopped or started being unresolved is that statement, and it is here
    rather than there so both features report a change the same way (plan key point 12).
    """

    before: RmsGrade
    after: RmsGrade
    counts: Mapping[GradeBucket, int]
    """`after` minus `before`, per bucket; negative means the bucket shrank."""

    resolved_rule_ids: tuple[str, ...]
    """Rules that were unresolved before and are not now - evaluated, not necessarily
    passing."""

    newly_unresolved_rule_ids: tuple[str, ...]
    """Rules that are unresolved now and were not before: evidence the change took away."""

    def summary(self) -> str:
        moved = ", ".join(
            f"{bucket.replace('_', ' ')} {count:+d}"
            for bucket, count in self.counts.items()
            if count
        )
        return f"before: {self.before.summary()}; after: {self.after.summary()}" + (
            f"; moved: {moved}" if moved else "; no bucket moved"
        )


def grade(source: ReviewSession | Sequence[RuleResult]) -> RmsGrade:
    """Grade a recorded session, or a rule layer's results before anything is recorded.

    Prefer the session wherever there is one: it is the only shape that knows an exception
    was applied, and it carries the ten rules that are never dispatched.
    """
    if isinstance(source, ReviewSession):
        return _grade_session(source)
    return _grade_results(source)


def delta(before: RmsGrade, after: RmsGrade) -> RmsGradeDelta:
    """What changed between two grades of the same part."""
    was = set(before.unresolved_rule_ids)
    now = set(after.unresolved_rule_ids)
    return RmsGradeDelta(
        before=before,
        after=after,
        counts={
            bucket: after.counts[bucket] - before.counts[bucket] for bucket in BUCKETS
        },
        resolved_rule_ids=tuple(sorted(was - now)),
        newly_unresolved_rule_ids=tuple(sorted(now - was)),
    )


def _grade_results(results: Sequence[RuleResult]) -> RmsGrade:
    """One entry per result: the rule layer returns one per outcome it reached."""
    counted = [_BUCKET_BY_OUTCOME[result.outcome] for result in results]
    return RmsGrade.of(
        counted,
        (result.rule_id for result in results if result.outcome == "unresolved"),
    )


def _grade_session(session: ReviewSession) -> RmsGrade:
    """One entry per (rule, document) coverage entry, plus one per recorded finding.

    An aggregated coverage item stands for one rule over the documents it names, so it
    counts once per document - and once when it names none, which is how the ten
    never-dispatched rules and any rule about the package as a whole are counted. A
    finding stands for one rule on one document, so it counts once. That is the same unit
    the rule layer counts, because the report layer writes exactly one coverage entry per
    (rule, bucket, document) and exactly one finding per finding-shaped result.

    Anything whose check is not a rule id - the `modeling.resilience` summary, the
    `rms.types.unknown` census, a `tool.*` failure - is not a rule and is not graded.
    """
    counted: list[GradeBucket] = []
    unresolved_rule_ids: list[str] = []
    for bucket in _COVERAGE_BUCKETS:
        for item in getattr(session.coverage, bucket):
            if item.check not in RULES:
                continue
            entries = max(len(item.scope.document_ids), 1)
            counted.extend([bucket] * entries)
            if bucket == "unresolved":
                unresolved_rule_ids.append(item.check)
    for recorded in session.findings:
        if recorded.check not in RULES:
            continue
        found = _BUCKET_BY_FINDING_STATUS[recorded.status]
        counted.append(found)
        if found == "unresolved":
            unresolved_rule_ids.append(recorded.check)
    return RmsGrade.of(counted, unresolved_rule_ids)
