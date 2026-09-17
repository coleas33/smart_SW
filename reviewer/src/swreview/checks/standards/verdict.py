"""The release verdict: a state, the counts in every bucket, and what they hide.

FR-032. The headline of a standards run is three things and never a fourth:

- **a state**, computed from the error count and the unresolved coverage **alone**:
  `not_ready` above zero errors, `ready` at zero errors with no unresolved row on any
  check, `ready_coverage_incomplete` at zero errors with one or more. A warning never moves
  it - the two warning checks are advisory by contract - and a **waived** error is not an
  error, which is what lets a run reach `ready` with waivers;
- **the counts in every bucket, in every state**, beside the unresolved check ids, so no
  page can render a clean headline without what it does not cover;
- **`notes`**, which is what stops a clean headline hiding a waiver, an empty profile
  setting or a run that graded no drawing.

**No letter grade, and no single number.** Feature 003's `RmsGrade` carries a fraction as a
secondary number and states why; a release verdict carries none. "Ready" is not a score, and
a release gate that could be read as 83% would be read as 83%.

**The unit of each count is stated, because the six do not share one** (`COUNT_UNITS`):
`error`, `warning` and `waived` count **findings** - one per failing check per document
(FR-003), whatever subjects it carries - and the four coverage counts count **(check,
document) pairs**, so a check landing in two buckets over three documents contributes to
both and the four do not sum to sixteen. The page and the report label them from here
rather than from a sentence each of them writes.

This module counts what it is handed and decides nothing else: which findings exist and
which pairs landed in which bucket is `checks/standards/report.py`'s answer, and the
verdict is a function of it.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, get_args

__all__ = [
    "COUNT_UNITS",
    "COVERAGE_BUCKETS",
    "EMPTY_SETTING_NOTE",
    "NO_DRAWING_NOTE",
    "WAIVED_NOTE",
    "BucketCounts",
    "CoverageBucketName",
    "CoveragePair",
    "FindingOutcome",
    "ReleaseVerdict",
    "VerdictState",
    "release_verdict",
]

VerdictState = Literal["not_ready", "ready", "ready_coverage_incomplete"]
"""The three states, and the only three. There is no fourth for "ready with waivers": a
waiver is an accepted condition, not a different kind of readiness, and it is said in
`notes` instead."""

CoverageBucketName = Literal["checked", "skipped", "unresolved", "out_of_scope"]
"""The four session coverage buckets a (check, document) pair can land in. `failed` and
`warned` are **rendered** buckets derived from findings by `checks/standards/report.py`,
never session buckets, so they are counted here as findings and not as pairs."""

COVERAGE_BUCKETS: tuple[CoverageBucketName, ...] = get_args(CoverageBucketName)
"""The same four, as a tuple to walk.

Derived from the type rather than typed out a second time: every walk over "the session
buckets a (check, document) pair can land in" - here, and the three in
`checks/standards/report.py` - reads this, so a fifth bucket is added in one place and no
walk can quietly be one short of the vocabulary (constitution Principle V, T099).
"""

FindingSeverity = Literal["error", "warning"]

COUNT_UNITS: dict[str, str] = {
    "error": "findings",
    "warning": "findings",
    "waived": "findings",
    "checked": "(check, document) pairs",
    "skipped": "(check, document) pairs",
    "unresolved": "(check, document) pairs",
    "out_of_scope": "(check, document) pairs",
}
"""What each count counts, for the page and the report to label it with.

Seven keys for six counts plus `waived`, which is rendered beside them and shares their
unit. A reader who sees `checked 9` beside `error 0` would otherwise reasonably add them
up; they are two different things counted two different ways.
"""

WAIVED_NOTE = "{count} finding{s} waived by {an}accepted exception{s}"
EMPTY_SETTING_NOTE = "{count} check{s} skipped because a profile list is empty"
NO_DRAWING_NOTE = "no drawing graded"
"""The three notes, verbatim as `contracts/standards-check.md` renders them."""


@dataclass(frozen=True)
class FindingOutcome:
    """One finding as the verdict counts it: which check, how hard, and whether waived.

    One per failing check per document (FR-003). The subjects it names and the instances
    that reach its document change nothing here, which is the point of counting findings
    rather than subjects.
    """

    check: str
    severity: FindingSeverity
    waived: bool = False


@dataclass(frozen=True)
class CoveragePair:
    """One (check, document) pair that reached one bucket."""

    check: str
    document_id: str
    bucket: CoverageBucketName


@dataclass(frozen=True)
class BucketCounts:
    """The six counts, rendered beside the verdict in every state.

    Two units, named by `COUNT_UNITS`: the first two count findings, the last four count
    (check, document) pairs. They do not sum to sixteen and are not meant to.
    """

    error: int = 0
    warning: int = 0
    checked: int = 0
    skipped: int = 0
    unresolved: int = 0
    out_of_scope: int = 0


@dataclass(frozen=True)
class ReleaseVerdict:
    """What a standards run says about a design, in full."""

    state: VerdictState
    counts: BucketCounts
    waived: int
    """Findings a matching active exception waived. They are not errors - that is what
    makes a `ready` verdict reachable with them - and `notes` always says so."""

    unresolved_check_ids: tuple[str, ...]
    """Every check with at least one `unresolved` pair, in the order they were reached.
    They travel with the counts in every state so a page cannot show one without them."""

    notes: tuple[str, ...]


def release_verdict(
    *,
    findings: Sequence[FindingOutcome],
    coverage: Iterable[CoveragePair],
    empty_setting_checks: Collection[str] = (),
    graded_kinds: Collection[str | None] = (),
) -> ReleaseVerdict:
    """The verdict over one run's findings and coverage.

    `empty_setting_checks` are the checks that were skipped because the profile setting
    they read is empty - the count that keeps an unconfigured profile from reading as a
    clean run (`contracts/rules.md`, "Profile values"). `graded_kinds` are the kinds of the
    documents that were graded, which is how the run knows whether it saw a drawing; an
    unresolved document has no kind and is not one.
    """
    waived = sum(1 for finding in findings if finding.waived)
    counts, unresolved_ids = _counted(findings, coverage)
    return ReleaseVerdict(
        state=_state(counts.error, unresolved_ids),
        counts=counts,
        waived=waived,
        unresolved_check_ids=unresolved_ids,
        notes=_notes(waived, empty_setting_checks, graded_kinds),
    )


def _counted(
    findings: Sequence[FindingOutcome], coverage: Iterable[CoveragePair]
) -> tuple[BucketCounts, tuple[str, ...]]:
    """The six counts and the unresolved ids, in one walk over each input.

    A pair is counted once however many times it is offered: the same check on the same
    document in the same bucket is one fact, and the report layer aggregates coverage per
    check per bucket, so a caller that passed a pair per document *and* a pair per
    aggregated item must not double it.
    """
    buckets: dict[str, set[tuple[str, str]]] = {name: set() for name in COVERAGE_BUCKETS}
    unresolved_ids: dict[str, None] = {}
    for pair in coverage:
        buckets[pair.bucket].add((pair.check, pair.document_id))
        if pair.bucket == "unresolved":
            unresolved_ids.setdefault(pair.check, None)

    return (
        BucketCounts(
            error=sum(
                1 for finding in findings if finding.severity == "error" and not finding.waived
            ),
            warning=sum(
                1 for finding in findings if finding.severity == "warning" and not finding.waived
            ),
            checked=len(buckets["checked"]),
            skipped=len(buckets["skipped"]),
            unresolved=len(buckets["unresolved"]),
            out_of_scope=len(buckets["out_of_scope"]),
        ),
        tuple(unresolved_ids),
    )


def _state(errors: int, unresolved_ids: tuple[str, ...]) -> VerdictState:
    """FR-032's rule, and nothing else reaches it: errors first, then coverage."""
    if errors > 0:
        return "not_ready"
    return "ready_coverage_incomplete" if unresolved_ids else "ready"


def _notes(
    waived: int, empty_setting_checks: Collection[str], graded_kinds: Collection[str | None]
) -> tuple[str, ...]:
    """The notes that apply, in one order: waivers, empty settings, no drawing."""
    notes: list[str] = []
    if waived:
        notes.append(
            WAIVED_NOTE.format(
                count=waived, s="" if waived == 1 else "s", an="an " if waived == 1 else ""
            )
        )
    skipped = len(set(empty_setting_checks))
    if skipped:
        notes.append(EMPTY_SETTING_NOTE.format(count=skipped, s="" if skipped == 1 else "s"))
    if graded_kinds and "drawing" not in set(graded_kinds):
        notes.append(NO_DRAWING_NOTE)
    return tuple(notes)
