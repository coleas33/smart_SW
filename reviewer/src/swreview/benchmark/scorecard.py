"""Score a finished benchmark run against its withheld answer keys.

`score_run` is the only place in the benchmark harness that combines a run's
`session.json` files with `swreview.benchmark.answer_key` - the run itself never sees an
answer key (constitution Principle VI, FR-025). Output shapes follow data-model.md
section 3 and must validate against `contracts/scorecard.schema.json`. `read_scorecard` is the
one reader of the `scorecard.json` it writes.

## What a run cost

Feature 005 adds the usage columns beside the quality ones, because every adoption
decision reads both: a lever that halves the token bill and loses a known defect is not
adopted. The counts are **copied** from `session.usage`, never re-summed, and the one
derivation, `cached_input_share`, is `TokenUsage`'s own property. `seconds_to_first_finding`
is read from the package's event stream beside the `session.json`, plain or packed, found by
`agent/events.event_stream` and read in the one pass that also reads the withdrawn findings
(`read_stream`, through the product's one event-line reader, `replay_events`; plan decisions
RF-29, RF-83). A session that carries no usage scores to nulls; a null in any package makes that
aggregate total null rather than a partial sum.

## What a finding credits (feature 014 `contracts/scoring.md` 3)

Whether a finding matches a key entry is `benchmark/matching.py`'s, the one matcher: its check
under the entry's exact check or family, its parts or documents meeting the entry's, and on a
reference-keyed check its references equal to one covered item's. The prefix rule this module
once applied, which credited a sibling rule, is gone (owner decision 4A). The scorer asks the
matcher once per finding and entry, and reads every outcome from that one pass, the final state's
findings only (FR-026):

- **A known defect** (owner decision 13A): any demonstrated or suspected match credits it, with a
  status mismatch when it was expected unresolved; failing that, an unresolved match flags it when
  it was expected unresolved and leaves it flagged below expected otherwise, which is no
  detection and no false alarm; failing that, it is missed when nothing matched at all. Any
  `checked_within_scope` match clears it, whatever the row, so a defect only a pass matched is
  cleared and neither detected nor missed. Detected is credited or flagged, the
  `matched_defect_ids` adoption reads.
- **A correct condition**: contradicted by a demonstrated or suspected match, confirmed by a
  `checked_within_scope` one; an unresolved match counts in neither. A key with no condition
  assesses neither column: each is `null`, its reason in `not_assessed`, never 0 (FR-021).
- **A false alarm**: a demonstrated or suspected finding that credits no known defect, one at most
  per finding. The key's overlap refusal means a finding contradicting a condition credits no
  defect, so it is a false alarm too. A false alarm matching a forbidden entry is also a
  **forbidden hit**, still one false alarm; one matching a tuned-on forbidden entry or tuned-on
  correct condition is **tuned-on**, which the verdict leaves out of its deciding figure (D15).
- **A withdrawn forbidden hit** (`scoring.md` 3.3): a finding that left the session before the
  end and, as last announced in the event stream, was demonstrated or suspected and matched a
  forbidden entry. It is no false alarm; unknown, never 0, when the stream is missing or cannot be
  read to its end.
- **Expected coverage** (`scoring.md` 4): each entry's goal, read through the report's own state
  decision (`finding_groups.goal_readings`), by section 4's table; a reading outside the entry's
  statuses is a mismatch.
- **The question columns** (`questions.md` 6): `benchmark/questions.py`'s, from the session, its
  stored request results and its answer log, checked against the session first.

A column a key gives nothing to grade, or one that cannot be read, is `null`, its reason in the
one `not_assessed` map (FR-021).

Recall is read from the key's item tags, by producer and tag (FR-006, FR-031), never from the
set's package flag, which must equal what the key derives. Every finding's origin is
`benchmark/origins.py`'s, and the scorer never refuses on it.

## The scoring-rules version

`SCORING_RULES_VERSION` names the rules above. Any change to matching or counting, and any new
required field, bumps it, so a scorecard scored under other rules meets the re-score line in
`read_scorecard` rather than being compared silently with this build's (FR-008).
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as Date
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar, get_args

from pydantic import ConfigDict, Field, ValidationError

from swreview.agent import events
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import CACHED_SHARE_PUBLISHABLE, TokenUsage
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.benchmark import answers, matching, questions, runner, sets
from swreview.benchmark import prices as pricing
from swreview.benchmark.answer_key import load_answer_key
from swreview.benchmark.answer_key_model import (
    AnswerKey,
    ExpectedCoverage,
    ExpectedReading,
    ExpectedStatus,
    Producer,
    Tag,
)
from swreview.benchmark.answers import UnscriptedRequest
from swreview.benchmark.attempt import AttemptClass
from swreview.benchmark.digest import sha256_of
from swreview.benchmark.origins import MODEL_ORIGINS, Origin, finding_origin
from swreview.benchmark.questions import CallRow, CountRow, QuestionIds, RepeatRow, UnanswerableRow
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet
from swreview.findings import Finding, ReviewModel, carried_count, first_refusal
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package
from swreview.ir.models import EvidencePackage
from swreview.report.finding_groups import (
    GoalReading,
    GoalReason,
    GoalState,
    goal_of,
    goal_readings,
)
from swreview.report.session import Coverage, ReviewSession, load_session
from swreview.report.summary import Words, load_words

SCORING_RULES_VERSION = 4
"""The rules this build scores by (`scoring.md` 8): 2 was feature 014's scorer slice, exact and
family matching, references, 13A's statuses, conditions, origins and recall by tag; 3 is its
key-extensions slice, adding forbidden, withdrawn and tuned-on hits, expected coverage and the
question columns; 4 adds the run outcomes, attempt costs, served models and price sources.
A scorecard without the field was scored under version 1. The golden version record pins the
current version and its scoring view (INT-11, SC-013)."""

SCORECARD_FILE = "scorecard.json"
"""What `benchmark score` writes into a run folder, and `read_scorecard` reads."""

Number = TypeVar("Number", int, float)
"""What `sum_or_none` adds: token counts, or a wall clock's seconds (feature 014
`contracts/report.md` 4)."""

NOT_ASSESSED = "not assessed"
"""What a column the key gives nothing to grade renders as: a key with no entry of the list the
column reads is no measurement of it, never 0 (FR-021)."""

NO_CORRECT_CONDITION = "the key holds no correct condition"
"""`not_assessed`'s reason for the two condition columns of a key without one."""

NO_FORBIDDEN_ENTRY = "the key holds no forbidden entry"
"""`not_assessed`'s reason for the two forbidden columns of a key without one."""

NO_EXPECTED_COVERAGE = "the key holds no expected coverage"
"""`not_assessed`'s reason for `coverage_mismatches` of a key without an entry."""

NO_EVENT_STREAM = (
    f"the package has no event stream ({events.EVENTS_FILE_NAME} or "
    f"{events.PACKED_EVENTS_FILE_NAME}), so no withdrawal can be read"
)
"""`not_assessed`'s reason for the withdrawn column of a package whose stream is missing."""

WITHDRAWN_COLUMN = "withdrawn_forbidden_hit_finding_ids"
"""The one column that reads `unknown`, not `not assessed`, when its stream cannot be read."""

CREDITING_STATUSES: tuple[str, ...] = ("demonstrated", "suspected")
"""The statuses that credit a known defect, contradict a correct condition, and, crediting
nothing, are a false alarm (`scoring.md` 3)."""

UNKNOWN = "unknown"
"""What a number no run reported renders as in the markdown. Never `0`, which is a
measurement, and never the `-` the timing columns have always used for a missing minute
count: a token column that reads `-` invites "no tokens" (Principle I)."""


def tool_histogram(session: ReviewSession) -> dict[str, int]:
    """How many times this session called each tool, most-called first, then by name.

    **The token count is arithmetic; which tool the model picked is the thing that needs
    watching** (T057). A trim, a withheld tier or a pre-run digest that changed the answer
    shows first as a call-pattern change - a check tool dropping out of the repertoire, or
    one that used to be called once per package being called once per document - and none
    of that moves the token totals or the finding counts enough for the general gate to
    fire.

    Every step counts, a failed call included: the question is which tool was chosen, not
    which call came back clean. The order is deterministic so two runs of one arm produce
    comparable JSON.
    """
    counts = Counter(step.tool for step in session.steps)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def coverage_bucket_mix(session: ReviewSession) -> dict[str, int]:
    """How many coverage items this session closed out in each of the five buckets.

    **Lever 7 cannot be gated without this column** (FR-074). The coverage-driven stop
    turns `mark_coverage` into a turn-ending call, so a model that wants to finish can
    close the checklist with nine `mark_coverage(bucket="skipped")` calls: today that
    makes a bad report, and with the lever on it also makes a short, cheap run that reads
    as a win in every other column of the table. `unresolved_count` does not catch it -
    that counts *findings* whose status is unresolved, not coverage items - and neither do
    the token totals, which is exactly the point.

    Every bucket is named, zeros included, so two arms' rows line up column for column. A
    `0` here is a measurement: this run recorded no item in that bucket.
    """
    return {
        bucket: len(getattr(session.coverage, bucket)) for bucket in Coverage.model_fields
    }


def unresolved_split(session: ReviewSession) -> tuple[int, int]:
    """The unresolved coverage items as two numbers: withheld, and everything else (FR-054).

    **Lever 4's gate needs both halves separately.** Withholding a tool is *supposed* to
    raise the first - that is what "not covered, and here is why" looks like in the
    coverage - and must not raise the second, which is the review quietly covering less.
    One number cannot tell those apart, and neither can `unresolved_count`, which counts
    *findings* whose status is unresolved rather than coverage items. The two returned here
    sum to `coverage_bucket_mix(session)["unresolved"]` and never to `unresolved_count`.

    The first half is set membership over `session.withheld_checks`, which the withheld
    tool wrote when it wrote the item. Reading it out of the reason sentence instead would
    make a rewording of that sentence a silent change to a measured number.
    """
    withheld = set(session.withheld_checks)
    items = session.coverage.unresolved
    because = sum(1 for item in items if item.check in withheld)
    return because, len(items) - because


GradedKind = Literal[
    "known_defect",
    "correct_condition",
    "forbidden_entry",
    "expected_coverage",
    "unanswerable_request",
    "question_count",
]
"""Which list of the key a graded item came from (`scoring.md` 6): one kind per list."""

CoverageRead = ExpectedReading | Literal["not_reported"]
"""How the scorer reads a goal (`scoring.md` 4): the four readings a key may expect, and not
reported, which no key may list."""


class CoverageMismatch(ReviewModel):
    """An expected-coverage entry whose goal reads outside its statuses (`scoring.md` 4)."""

    entry: str
    item: str
    read: CoverageRead


class GradedItem(ReviewModel):
    """One key entry as the scorecard copies it (`scoring.md` 6): compare reads no key, so the
    verdict splits recall and false alarms from these."""

    id: str
    kind: GradedKind
    tag: Tag
    producer: Producer | None
    """A known defect's, `null` for any other entry."""

    expected_status: ExpectedStatus | None
    """A known defect's, `null` for any other entry."""


class RecallByTag(ReviewModel):
    """Detected over all, for the known defects of one tag; `null` when there is none."""

    held_out: Annotated[float, Field(ge=0, le=1)] | None
    tuned_on: Annotated[float, Field(ge=0, le=1)] | None


class RecallByProducer(ReviewModel):
    """Recall per producer and tag (FR-006): the model's and code's defects apart."""

    model: RecallByTag
    code: RecallByTag


class _ClassRecord(ReviewModel):
    """Records keep the contract's `class` key in every serialized form."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    class_: AttemptClass | None = Field(alias="class")


class PackageRunStatus(_ClassRecord):
    kind: Literal["completed", "behavioural", "not_recorded"]
    stop_reason: str | None


class UnscoredPackage(_ClassRecord):
    package_id: str
    kind: Literal["infrastructure"]
    error_class: str | None
    attempts: int = Field(ge=1)
    folder: str


class FailedAttempt(_ClassRecord):
    package_id: str
    attempt: int = Field(ge=1)
    retries: int = Field(ge=0)
    cost: pricing.Cost
    folder: str


class PriceSource(ReviewModel):
    source: str
    date: Date


class PricedModel(ReviewModel):
    provider: str
    model: str
    input: PriceSource
    cached_input: PriceSource
    output: PriceSource


class PriceTableRecord(ReviewModel):
    prices_version: int
    models: list[PricedModel]


class PackageScore(ReviewModel):
    package_id: str
    held_out: bool
    session_id: str
    run_status: PackageRunStatus
    cost: pricing.Cost
    served_models: list[str]
    valid_findings: int = Field(ge=0)
    missed_known_defects: int = Field(ge=0)
    false_alarms: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    baseline_minutes: float | None
    assisted_minutes: float | None
    unattended_runtime_minutes: float = Field(ge=0)
    net_saved_minutes: float | None

    usage: TokenUsage | None = None
    """`session.usage.totals`, copied and never re-summed: two writers of one number is
    how a ledger and the session it was built from come to disagree."""

    round_trips: Annotated[int, Field(ge=0)] | None = None
    """`session.usage.rounds`. Model round trips, **not** `len(session.steps)`, which
    counts tool calls; the two diverge by exactly the amount lever 6 is trying to save."""

    cached_input_share: Annotated[float, Field(ge=0, le=1)] | None = None
    """`TokenUsage.cached_input_share`, the one formula. Computed from the first commit
    of this feature and published only once probe L1 has recorded that cached input is
    contained in input (FR-047); until then `render_scorecard_md` prints `unknown`."""

    wall_clock_s: Annotated[float, Field(ge=0)] | None = None
    """`started_at` to `ended_at`, in seconds, and the wall clock FR-028's threshold
    reads. Deliberately **not** `unattended_runtime_minutes * 60`: that field has two
    writers and the benchmark runner's `perf_counter` span wins, which also covers package
    load and adapter construction. `None` on a session that never ended."""

    seconds_to_first_finding: Annotated[float, Field(ge=0)] | None = None
    """The first **computed** finding event's `at` minus `session.started`'s, from
    `events.jsonl`. A carried finding (lever 11a) is skipped, because it is written during
    setup and would time the carry rather than the review (FR-104). `None` when the run
    computed nothing, or when it kept no event stream."""

    carried_findings: int = Field(default=0, ge=0)
    """Findings this run carried from an earlier one rather than computing (lever 11a).
    Zero unless `carry_over_rms` was on. The row records it beside the quality numbers
    because a lever that "improves" recall by remembering is not an improvement (FR-104)."""

    unresolved_because_withheld: int = Field(default=0, ge=0)
    """Unresolved coverage items a tool this run declined to offer wrote (lever 4, FR-054).
    Zero unless `tool_tiers` was on, and a zero here is a measurement."""

    unresolved_other: int = Field(default=0, ge=0)
    """Every other unresolved coverage item. **T064's gate is that this one must not
    rise**: the lever may trade coverage it names for bytes, never coverage it does not.
    With `unresolved_because_withheld` it sums to `coverage_bucket_mix["unresolved"]`, and
    never to `unresolved_count`, which counts findings rather than coverage items."""

    coverage_bucket_mix: dict[str, int] = Field(default_factory=dict)
    """`coverage_bucket_mix(session)`: the five closing buckets and how many items each
    holds. Lever 7's second guard, shipped with the lever because the run it has to catch
    looks efficient in every other column (FR-074)."""

    tool_calls_by_name: dict[str, int] = Field(default_factory=dict)
    """`tool_histogram(session)`: every tool this package's run called and how often, most
    called first. Empty for a run that called nothing, which is a measurement and not an
    absence. The ledger's lever-specific counter reads these per arm (T057, FR-034)."""

    matched_defect_ids: list[str] = Field(default_factory=list)
    """Detected: credited or flagged, in key order (`scoring.md` 3.1). The name is kept so
    adoption's rules read detection unchanged."""

    flagged_defect_ids: list[str]
    """Detected through an unresolved finding only, the defect expected unresolved; within
    matched."""

    status_mismatch_defect_ids: list[str]
    """Credited by a demonstrated or suspected finding while expected unresolved; within matched
    and outside flagged."""

    flagged_below_expected_defect_ids: list[str]
    """Met by an unresolved finding only while expected demonstrated or suspected: not detected,
    in no recall figure and never a false alarm (13A)."""

    cleared_defect_ids: list[str]
    """Matched by a `checked_within_scope` finding, whatever else matched it."""

    missed_defect_ids: list[str] = Field(default_factory=list)
    """No finding matched at all."""

    contradicted_condition_ids: list[str] | None
    """Correct conditions a demonstrated or suspected finding matched, in key order; `null` when
    the key holds none (`scoring.md` 3.2)."""

    confirmed_condition_ids: list[str] | None
    """Correct conditions a `checked_within_scope` finding matched; `null` likewise."""

    false_alarm_finding_ids: list[str] = Field(default_factory=list)
    """Demonstrated or suspected findings that credit no known defect, in session order."""

    forbidden_hit_finding_ids: list[str] | None
    """The false alarms that match a forbidden entry, in session order; `null` when the key holds
    none (`scoring.md` 3.3)."""

    withdrawn_forbidden_hit_finding_ids: list[str] | None
    """Findings withdrawn before the end that, as last announced, were demonstrated or suspected
    and matched a forbidden entry, in the order they were withdrawn; never false alarms. `null`
    when the key holds no forbidden entry, the stream is missing, or it cannot be read to its
    end."""

    tuned_on_false_alarm_finding_ids: list[str]
    """The false alarms that match a tuned-on forbidden entry or tuned-on correct condition, a
    hit on a tuned-on and a held-out item included (D15, SR-10)."""

    coverage_mismatches: list[CoverageMismatch] | None
    """Expected-coverage entries whose goal reads outside their statuses, in key order; `null`
    when the key holds none (`scoring.md` 4)."""

    finding_origins: dict[str, Origin]
    """Every final-state finding's origin, by finding id, in session order, then every withdrawn
    forbidden hit's, read off its last announced body (`scoring.md` 5.5)."""

    graded_items: list[GradedItem]
    """Every key entry, in key order: known defects, correct conditions, then the four extension
    lists."""

    re_asks: list[RepeatRow] | None
    open_repeats: list[RepeatRow] | None
    unanswerable_requests: list[UnanswerableRow] | None
    unmatched_requests: list[CallRow] | None
    question_counts: list[CountRow] | None
    unscripted_questions: list[UnscriptedRequest] | None
    bound_reached: bool | None
    """The question columns (`questions.md` 6), each `null` where it cannot be assessed."""

    not_assessed: dict[str, str]
    """The reason for every `null` column above, and for none other."""


class Aggregate(ReviewModel):
    packages: int = Field(ge=0)
    cost: pricing.Cost
    failed_attempts_cost: pricing.Cost
    held_out_packages: int = Field(ge=0)
    valid_findings: int = Field(ge=0)
    missed_known_defects: int = Field(ge=0)
    false_alarms: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    recall: Annotated[float, Field(ge=0, le=1)] | None
    false_alarm_rate: Annotated[float, Field(ge=0, le=1)] | None
    median_net_saved_minutes: float | None
    packages_with_timing: int = Field(ge=0)

    input_tokens: Annotated[int, Field(ge=0)] | None = None
    cached_input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    reasoning_tokens: Annotated[int, Field(ge=0)] | None = None
    total_tokens: Annotated[int, Field(ge=0)] | None = None
    round_trips: Annotated[int, Field(ge=0)] | None = None
    """Summed over packages under the same rule `SessionUsage.summed` applies over rounds:
    one package that reported nothing makes that total `None`, not a partial sum. Only the
    five counts the ledger compares are aggregated; `scorecard.json` keeps all seven per
    package."""

    median_seconds_to_first_finding: float | None = None
    packages_with_usage: int = Field(default=0, ge=0)
    """How many packages contributed usage, mirroring `packages_with_timing`. Without it a
    `None` total cannot be told from a run where nothing was measured at all."""

    detected: int = Field(ge=0)
    flagged: int = Field(ge=0)
    status_mismatches: int = Field(ge=0)
    flagged_below_expected: int = Field(ge=0)
    cleared: int = Field(ge=0)
    """The per-package defect lists' lengths, summed (`scoring.md` 7)."""

    contradictions: Annotated[int, Field(ge=0)] | None
    confirmations: Annotated[int, Field(ge=0)] | None
    """Summed over the packages whose key holds a correct condition; `null` when none does."""

    forbidden_hits: Annotated[int, Field(ge=0)] | None
    withdrawn_forbidden_hits: Annotated[int, Field(ge=0)] | None
    tuned_on_false_alarms: int = Field(ge=0)
    coverage_mismatches: Annotated[int, Field(ge=0)] | None
    """Each per-package list's length, summed over the packages that assess it; `null` when none
    does (`scoring.md` 7)."""

    findings_by_origin: dict[Origin, int]
    false_alarms_by_origin: dict[Origin, int]
    """Every origin, zeros included, so two arms line up origin for origin; the final state's
    findings only, never a withdrawn one."""

    recall_by_producer: RecallByProducer
    held_out_model_defects: int = Field(ge=0)
    """The held-out model-produced defects every package's key names
    (`AnswerKey.held_out_model_defect_ids()`)."""

    re_asks: Annotated[int, Field(ge=0)] | None
    open_repeats: Annotated[int, Field(ge=0)] | None
    unanswerable_requests: Annotated[int, Field(ge=0)] | None
    unmatched_requests: Annotated[int, Field(ge=0)] | None
    unscripted_questions: Annotated[int, Field(ge=0)] | None
    question_count_misses: Annotated[int, Field(ge=0)] | None
    bound_reached: Annotated[int, Field(ge=0)] | None
    """The question columns (`questions.md` 6), each summed over the packages that assess it,
    `null` when none does: `question_count_misses` the rules whose count falls outside their
    bounds, `bound_reached` the packages whose answer log says the answer-turn bound was
    reached."""


class Scorecard(ReviewModel):
    scoring_rules_version: int = Field(ge=1)
    """`SCORING_RULES_VERSION` when it was scored; `read_scorecard` reads it before anything
    else."""

    run_id: str
    benchmark_set: str
    scored_at: datetime = Field(strict=False)
    per_package: list[PackageScore]
    unscored_packages: list[UnscoredPackage]
    failed_attempts: list[FailedAttempt]
    price_table: PriceTableRecord | None
    aggregate: Aggregate
    distribution: list[float | None]
    key_sha256: dict[str, str]
    """Each package's key file, by its raw bytes' `sha256_of`: compare refuses a study whose runs
    were scored against two versions of one key (plan decision INT-16)."""


def _graded_items(answer_key: AnswerKey) -> list[GradedItem]:
    """Every entry of the key as the scorecard copies it, in section 2.1's order of the lists:
    a known defect with its producer and expected status, any other entry with neither."""
    others: list[tuple[GradedKind, Sequence[Any]]] = [
        ("correct_condition", answer_key.correct_conditions),
        ("forbidden_entry", answer_key.forbidden),
        ("expected_coverage", answer_key.expected_coverage),
        ("unanswerable_request", answer_key.unanswerable_requests),
        ("question_count", answer_key.question_counts),
    ]
    return [
        *(
            GradedItem(
                id=defect.id,
                kind="known_defect",
                tag=defect.tag,
                producer=defect.producer,
                expected_status=defect.expected_status,
            )
            for defect in answer_key.known_defects
        ),
        *(
            GradedItem(id=entry.id, kind=kind, tag=entry.tag, producer=None, expected_status=None)
            for kind, entries in others
            for entry in entries
        ),
    ]


def _matches_by_entry(
    findings: Sequence[Finding], answer_key: AnswerKey
) -> dict[str, list[Finding]]:
    """Each entry's matching findings, in session order: the one pass through the matcher every
    outcome below is read from, forbidden entries included."""
    return {
        entry.id: [finding for finding in findings if matching.matches(finding, entry)]
        for entry in [
            *answer_key.known_defects,
            *answer_key.correct_conditions,
            *answer_key.forbidden,
        ]
    }


def _statuses(findings: Sequence[Finding]) -> set[str]:
    """The statuses among an entry's matching findings: all 13A's table reads of them."""
    return {finding.status for finding in findings}


def _defect_outcomes(
    answer_key: AnswerKey, matches: Mapping[str, Sequence[Finding]]
) -> dict[str, list[str]]:
    """13A's table (`scoring.md` 3.1), each list in key order: detected (`matched`), `flagged`,
    `status_mismatch`, `flagged_below_expected`, `cleared` and `missed`."""
    lists: dict[str, list[str]] = {
        name: []
        for name in (
            "matched",
            "flagged",
            "status_mismatch",
            "flagged_below_expected",
            "cleared",
            "missed",
        )
    }
    for defect in answer_key.known_defects:
        hits = matches[defect.id]
        statuses = _statuses(hits)
        expected_unresolved = defect.expected_status == "unresolved"
        if statuses & set(CREDITING_STATUSES):
            lists["matched"].append(defect.id)
            if expected_unresolved:
                lists["status_mismatch"].append(defect.id)
        elif "unresolved" in statuses:
            if expected_unresolved:
                lists["matched"].append(defect.id)
                lists["flagged"].append(defect.id)
            else:
                lists["flagged_below_expected"].append(defect.id)
        elif not hits:
            lists["missed"].append(defect.id)
        if "checked_within_scope" in statuses:
            lists["cleared"].append(defect.id)
    return lists


def _condition_outcomes(
    answer_key: AnswerKey, matches: Mapping[str, Sequence[Finding]]
) -> tuple[list[str] | None, list[str] | None]:
    """`scoring.md` 3.2: the contradicted and the confirmed conditions, in key order, or two
    `None`s for a key with no condition."""
    if not answer_key.correct_conditions:
        return None, None
    contradicted = [
        condition.id
        for condition in answer_key.correct_conditions
        if _statuses(matches[condition.id]) & set(CREDITING_STATUSES)
    ]
    confirmed = [
        condition.id
        for condition in answer_key.correct_conditions
        if "checked_within_scope" in _statuses(matches[condition.id])
    ]
    return contradicted, confirmed


def _crediting_finding_ids(
    answer_key: AnswerKey, matches: Mapping[str, Sequence[Finding]]
) -> set[str]:
    """The demonstrated or suspected findings that credit some known defect."""
    return {
        finding.id
        for defect in answer_key.known_defects
        for finding in matches[defect.id]
        if finding.status in CREDITING_STATUSES
    }


@dataclass(frozen=True)
class StreamRead:
    """What the scorer reads of one package's event stream, in its one pass (`scoring.md` 1 and
    3.3; plan decision RF-29)."""

    present: bool
    """Whether the stream exists, plain or packed."""
    seconds_to_first_finding: float | None
    """The first computed finding's `at` less `session.started`'s, before any unreadable line."""
    withdrawn: dict[str, dict[str, Any]]
    """Each id a `finding.withdrawn` event names, in the order of its first withdrawal, with the
    last `finding` body announced for it before its latest withdrawal."""
    unreadable_line: int | None
    """The 1-based line `replay_events` stopped at, or `None` when it read to the end."""


def read_stream(events_path: Path) -> StreamRead:
    """One pass over a package's event stream through the product's one event-line reader,
    `agent/events.replay_events`, whose `on_unreadable` hook names the line where it stops.

    **Time to first finding.** Both stamps are already there: `session.started` and every
    `finding` event carry an `at` (`EventSink.emit`), so this needs no new recording and no
    answer key. **A carried finding does not start the clock.** Lever 11a writes its carried
    findings during `start_review` setup, before the first turn (`carry_over.carry_over_findings`),
    so a stream that counted them would time the carry rather than the review (FR-104): the
    first finding whose `carried_over_from` is absent or null starts it. `None` whenever the
    number cannot be had: no stream (a run made before the convention is still a real run), no
    finding, no `session.started`, or a line that cannot be read before the first finding.

    **Withdrawn findings.** The session holds none (`tools/context.py:316-335`), so each
    `finding.withdrawn` is read here with the last `finding` body announced before it; whether
    it is still withdrawn at the end, and what it hit, is `_score_package`'s.
    """
    if not events_path.is_file():
        return StreamRead(
            present=False, seconds_to_first_finding=None, withdrawn={}, unreadable_line=None
        )
    unreadable: list[int] = []
    started_at: datetime | None = None
    first: float | None = None
    announced: dict[str, dict[str, Any]] = {}
    withdrawn: dict[str, dict[str, Any]] = {}
    for event in events.replay_events(events_path, on_unreadable=unreadable.append):
        if event.type == "session.started" and started_at is None:
            started_at = event.at
        elif event.type == "finding":
            body = event.body
            if first is None and started_at is not None and body.get("carried_over_from") is None:
                first = (event.at - started_at).total_seconds()
            if isinstance(body.get("id"), str):
                announced[body["id"]] = body
        elif event.type == "finding.withdrawn":
            finding_id = event.body.get("finding_id")
            if isinstance(finding_id, str) and finding_id in announced:
                withdrawn[finding_id] = announced[finding_id]
    return StreamRead(
        present=True,
        seconds_to_first_finding=first,
        withdrawn=withdrawn,
        unreadable_line=unreadable[0] if unreadable else None,
    )


def seconds_to_first_finding(events_path: Path) -> float | None:
    """How long the run took to find something itself: `read_stream`'s, the one pass."""
    return read_stream(events_path).seconds_to_first_finding


def _withdrawn_forbidden_hits(
    stream: StreamRead, answer_key: AnswerKey, session: ReviewSession
) -> tuple[dict[str, Finding] | None, str | None]:
    """`scoring.md` 3.3's withdrawn forbidden hits, by id, in the order they were withdrawn, or
    `None` and the reason they cannot be assessed: no forbidden entry, no stream, or a line the
    stream cannot be read past, after which a withdrawal could lie (unknown is never 0)."""
    if not answer_key.forbidden:
        return None, NO_FORBIDDEN_ENTRY
    if not stream.present:
        return None, NO_EVENT_STREAM
    if stream.unreadable_line is not None:
        return None, (
            f"the event stream cannot be read from line {stream.unreadable_line}, and a "
            "withdrawal could lie after it"
        )
    final = {finding.id for finding in session.findings}
    hits: dict[str, Finding] = {}
    for finding_id, body in stream.withdrawn.items():
        if finding_id in final:
            continue
        try:
            finding = Finding.model_validate(body)
        except ValidationError:
            continue
        if finding.status in CREDITING_STATUSES and any(
            matching.matches(finding, entry) for entry in answer_key.forbidden
        ):
            hits[finding_id] = finding
    return hits, None


_READ_AS: dict[tuple[GoalState, GoalReason | None], CoverageRead] = {
    ("issues", None): "checked",
    ("checked", None): "checked",
    ("not_reached", "unresolved"): "unresolved",
    ("not_reached", "failed"): "unresolved",
    ("not_reached", "skipped"): "skipped",
    ("not_reached", "no_check"): "not_reported",
    ("not_applicable", "out_of_scope"): "out_of_scope",
}
"""`scoring.md` 4's table: a goal reading's state and `GoalReason` key to how a key reads it.
`issues` reads `checked`, the item having been examined (SR-11)."""


def coverage_read(reading: GoalReading) -> CoverageRead:
    """How a key reads one goal (`scoring.md` 4), from the report's own state decision."""
    return _READ_AS[(reading.state, reading.reason)]


def coverage_mismatches(
    session: ReviewSession, entries: Sequence[ExpectedCoverage], words: Words
) -> list[CoverageMismatch]:
    """Each entry whose goal (`goal_of` its item) reads outside its statuses, in key order,
    through `finding_groups.goal_readings`, the decision the report's goal lines are built from
    (plan decision RF-23): no second reader, and no change to which rows a goal reads."""
    readings = {reading.goal.id: reading for reading in goal_readings(session, words)}
    mismatches: list[CoverageMismatch] = []
    for entry in entries:
        goal = goal_of(entry.item, words.goals)
        assert goal is not None  # the key loader's row 9: a goal reads every entry's item
        read = coverage_read(readings[goal.id])
        if read not in entry.statuses:
            mismatches.append(CoverageMismatch(entry=entry.id, item=entry.item, read=read))
    return mismatches


def _wall_clock_s(session: ReviewSession) -> float | None:
    """`started_at` to `ended_at`, or `None` for a session that never ended."""
    if session.ended_at is None:
        return None
    return (session.ended_at - session.started_at).total_seconds()


def _score_package(
    package_dir: Path,
    *,
    package_id: str,
    held_out: bool,
    answer_key: AnswerKey,
    package: EvidencePackage,
    words: Words,
    run_status: PackageRunStatus | Mapping[str, str | None],
    cost: pricing.Cost,
    served_models: list[str],
) -> PackageScore:
    """Score one package folder as a run leaves it, `session.json`, its event stream, its stored
    request results and its answer log, against its loaded key and its package: what `score_run`
    does per package, and what the oracle and null reviews of the validation are scored through,
    since `score_run` refuses a key-only key. `words` are the ones the caller loaded once, which
    the coverage reading takes. The answer log is checked against the session before any column
    is scored (`questions.md` 6)."""
    session = load_session(package_dir / SESSION_FILE_NAME)
    asked = questions.question_columns(
        session,
        run_dir=package_dir,
        ids=QuestionIds(package),
        answer_log=answers.read_answer_log(package_dir),
        unanswerable=answer_key.unanswerable_requests,
        count_rules=answer_key.question_counts,
    )
    findings = session.findings
    matches = _matches_by_entry(findings, answer_key)
    defects = _defect_outcomes(answer_key, matches)
    contradicted, confirmed = _condition_outcomes(answer_key, matches)
    crediting = _crediting_finding_ids(answer_key, matches)
    false_alarm_ids = [
        finding.id
        for finding in findings
        if finding.status in CREDITING_STATUSES and finding.id not in crediting
    ]
    forbidden = {finding.id for entry in answer_key.forbidden for finding in matches[entry.id]}
    tuned_on = {
        finding.id
        for entry in [*answer_key.forbidden, *answer_key.correct_conditions]
        if entry.tag == "tuned_on"
        for finding in matches[entry.id]
    }
    stream = read_stream(events.event_stream(package_dir))
    withdrawn, withdrawn_reason = _withdrawn_forbidden_hits(stream, answer_key, session)
    not_assessed: dict[str, str] = {}
    if contradicted is None:
        not_assessed["contradicted_condition_ids"] = NO_CORRECT_CONDITION
        not_assessed["confirmed_condition_ids"] = NO_CORRECT_CONDITION
    if not answer_key.forbidden:
        not_assessed["forbidden_hit_finding_ids"] = NO_FORBIDDEN_ENTRY
    if withdrawn_reason is not None:
        not_assessed[WITHDRAWN_COLUMN] = withdrawn_reason
    if not answer_key.expected_coverage:
        not_assessed["coverage_mismatches"] = NO_EXPECTED_COVERAGE
    not_assessed.update(asked.not_assessed)
    timing = session.timing
    assisted_minutes = (
        timing.assisted_supervision_minutes
        + timing.assisted_verification_minutes
        + timing.false_alarm_handling_minutes
    )
    usage = session.usage
    because_withheld, unresolved_other = unresolved_split(session)
    return PackageScore(
        package_id=package_id,
        held_out=held_out,
        session_id=str(session.session_id),
        run_status=run_status,
        cost=cost,
        served_models=served_models,
        valid_findings=len(crediting),
        missed_known_defects=len(defects["missed"]),
        false_alarms=len(false_alarm_ids),
        unresolved_count=sum(1 for finding in findings if finding.status == "unresolved"),
        baseline_minutes=timing.baseline_minutes,
        assisted_minutes=assisted_minutes,
        unattended_runtime_minutes=timing.unattended_runtime_minutes,
        net_saved_minutes=timing.net_saved_minutes,
        usage=usage.totals if usage is not None else None,
        round_trips=usage.rounds if usage is not None else None,
        cached_input_share=usage.totals.cached_input_share if usage is not None else None,
        wall_clock_s=_wall_clock_s(session),
        seconds_to_first_finding=stream.seconds_to_first_finding,
        carried_findings=carried_count(findings),
        unresolved_because_withheld=because_withheld,
        unresolved_other=unresolved_other,
        coverage_bucket_mix=coverage_bucket_mix(session),
        tool_calls_by_name=tool_histogram(session),
        matched_defect_ids=defects["matched"],
        flagged_defect_ids=defects["flagged"],
        status_mismatch_defect_ids=defects["status_mismatch"],
        flagged_below_expected_defect_ids=defects["flagged_below_expected"],
        cleared_defect_ids=defects["cleared"],
        missed_defect_ids=defects["missed"],
        contradicted_condition_ids=contradicted,
        confirmed_condition_ids=confirmed,
        false_alarm_finding_ids=false_alarm_ids,
        forbidden_hit_finding_ids=(
            [finding_id for finding_id in false_alarm_ids if finding_id in forbidden]
            if answer_key.forbidden
            else None
        ),
        withdrawn_forbidden_hit_finding_ids=None if withdrawn is None else list(withdrawn),
        tuned_on_false_alarm_finding_ids=[
            finding_id for finding_id in false_alarm_ids if finding_id in tuned_on
        ],
        coverage_mismatches=(
            coverage_mismatches(session, answer_key.expected_coverage, words)
            if answer_key.expected_coverage
            else None
        ),
        finding_origins={
            **{finding.id: finding_origin(finding, session) for finding in findings},
            **{
                finding_id: finding_origin(finding, session)
                for finding_id, finding in (withdrawn or {}).items()
            },
        },
        graded_items=_graded_items(answer_key),
        re_asks=asked.re_asks,
        open_repeats=asked.open_repeats,
        unanswerable_requests=asked.unanswerable_requests,
        unmatched_requests=asked.unmatched_requests,
        question_counts=asked.question_counts,
        unscripted_questions=asked.unscripted_questions,
        bound_reached=asked.bound_reached,
        not_assessed=not_assessed,
    )


def sum_or_none(values: Iterable[Number | None]) -> Number | None:
    """Add the counts, unless any one of them is unknown, in which case so is the sum.

    The same rule `SessionUsage.summed` applies one level down, over the rounds of one
    session, applied here over the packages of one run. A partial sum silently understates
    and no reader of the number can tell that it happened.
    """
    collected = list(values)
    if not collected or any(value is None for value in collected):
        return None
    return sum(value for value in collected if value is not None)


def _token_totals(per_package: Sequence[PackageScore], field: str) -> int | None:
    """One `TokenUsage` count summed over packages; a package with no usage is unknown."""
    return sum_or_none(
        getattr(score.usage, field) if score.usage is not None else None for score in per_package
    )


def _sum_assessed(values: Iterable[int | None]) -> int | None:
    """Add the counts of the packages that assess a column; `None` when none does.

    Not `sum_or_none`'s rule, and deliberately: a `None` here is a package whose key gives the
    column nothing to grade, not a number that went unreported, so it is left out of the sum
    rather than making it unknown (`scoring.md` 7)."""
    assessed = [value for value in values if value is not None]
    return sum(assessed) if assessed else None


def length_or_none(values: Sequence[object] | None) -> int | None:
    """How many entries a list some key may give nothing to grade holds, `None` for no list: the
    scorecard's sums and the ledger's per-package cells read it alike."""
    return None if values is None else len(values)


def question_count_misses(score: PackageScore) -> int | None:
    """How many of the package's question-count rules count outside their bounds, `None` when
    its key holds none (`questions.md` 5.2)."""
    if score.question_counts is None:
        return None
    return sum(1 for row in score.question_counts if row.missed)


def final_state_origins(score: PackageScore) -> list[Origin]:
    """The origin of each of the final state's findings: `finding_origins` less the withdrawn
    forbidden hits it also names (`scoring.md` 5.5)."""
    withdrawn = set(score.withdrawn_forbidden_hit_finding_ids or ())
    return [
        origin
        for finding_id, origin in score.finding_origins.items()
        if finding_id not in withdrawn
    ]


def _graded_defects(per_package: Sequence[PackageScore]) -> list[tuple[GradedItem, bool]]:
    """Every known defect of every package, with whether it was detected."""
    return [
        (item, item.id in score.matched_defect_ids)
        for score in per_package
        for item in score.graded_items
        if item.kind == "known_defect"
    ]


def _recall(defects: Sequence[tuple[GradedItem, bool]]) -> float | None:
    """Detected over all; `None` with no defect, which is not computable rather than 0."""
    if not defects:
        return None
    return sum(1 for _, detected in defects if detected) / len(defects)


def _recall_by_tag(defects: Sequence[tuple[GradedItem, bool]], producer: Producer) -> RecallByTag:
    """One producer's recall over its held-out and its tuned-on defects."""

    def of(tag: Tag) -> float | None:
        return _recall(
            [
                (item, found)
                for item, found in defects
                if item.producer == producer and item.tag == tag
            ]
        )

    return RecallByTag(held_out=of("held_out"), tuned_on=of("tuned_on"))


def by_origin(origins: Iterable[Origin]) -> dict[Origin, int]:
    """A count per origin, every origin named in `Origin`'s order, zeros included: the
    aggregate's and the ledger's per-package counts alike."""
    counts = Counter(origins)
    return {origin: counts[origin] for origin in get_args(Origin)}


def false_alarm_origins(score: PackageScore) -> list[Origin]:
    """The origin of each of this package's false alarms, in session order."""
    return [score.finding_origins[finding_id] for finding_id in score.false_alarm_finding_ids]


def of_model_origin(counts: Mapping[Origin, int]) -> int:
    """How many of a count by origin are of model origin (`origins.MODEL_ORIGINS`): what the
    summary and the page print beside the false alarms."""
    return sum(counts.get(origin, 0) for origin in MODEL_ORIGINS)


def known_defect_count(scorecard: Scorecard) -> int:
    """How many known defects the keys of the scored packages name: detected's denominator."""
    return len(_graded_defects(scorecard.per_package))


def _sum_costs(costs: Sequence[pricing.Cost]) -> pricing.Cost:
    """An empty or partly unpriced group cannot claim a measured zero spend (86A)."""
    if not costs:
        return pricing.Cost(amount=None, missing=["no costs recorded"], basis=[], synthetic=False)
    if all(cost.synthetic for cost in costs):
        return pricing.SYNTHETIC_COST
    unknown = sum(cost.amount is None for cost in costs)
    return pricing.Cost(
        amount=sum_or_none(cost.amount for cost in costs),
        missing=list(dict.fromkeys([
            *([f"{unknown} of {len(costs)} costs unknown"] if unknown else []),
            *(reason for cost in costs for reason in cost.missing),
        ])),
        basis=list(dict.fromkeys(note for cost in costs for note in cost.basis)),
        synthetic=False,
    )


def _aggregate(
    per_package: Sequence[PackageScore], answer_keys: Sequence[AnswerKey],
    *, failed_attempts: Sequence[FailedAttempt] = (),
) -> Aggregate:
    """The run's totals. Recall is held-out items of both producers, read from the tags: the
    set's package flag, checked against its key in `score_run`, filters nothing (`scoring.md`
    6)."""
    held_out_scores = [score for score in per_package if score.held_out]
    defects = _graded_defects(per_package)

    total_valid = sum(score.valid_findings for score in per_package)
    total_false_alarms = sum(score.false_alarms for score in per_package)
    total_findings = total_valid + total_false_alarms
    false_alarm_rate = total_false_alarms / total_findings if total_findings else None

    timed_savings = [
        score.net_saved_minutes for score in per_package if score.net_saved_minutes is not None
    ]
    median_net_saved_minutes = statistics.median(timed_savings) if timed_savings else None

    first_finding_times = [
        score.seconds_to_first_finding
        for score in per_package
        if score.seconds_to_first_finding is not None
    ]

    return Aggregate(
        packages=len(per_package),
        cost=_sum_costs([score.cost for score in per_package]),
        failed_attempts_cost=_sum_costs([attempt.cost for attempt in failed_attempts]),
        held_out_packages=len(held_out_scores),
        valid_findings=total_valid,
        missed_known_defects=sum(score.missed_known_defects for score in per_package),
        false_alarms=total_false_alarms,
        unresolved_count=sum(score.unresolved_count for score in per_package),
        recall=_recall([(item, found) for item, found in defects if item.tag == "held_out"]),
        false_alarm_rate=false_alarm_rate,
        median_net_saved_minutes=median_net_saved_minutes,
        packages_with_timing=len(timed_savings),
        input_tokens=_token_totals(per_package, "input_tokens"),
        cached_input_tokens=_token_totals(per_package, "cached_input_tokens"),
        output_tokens=_token_totals(per_package, "output_tokens"),
        reasoning_tokens=_token_totals(per_package, "reasoning_tokens"),
        total_tokens=_token_totals(per_package, "total_tokens"),
        round_trips=sum_or_none(score.round_trips for score in per_package),
        median_seconds_to_first_finding=(
            statistics.median(first_finding_times) if first_finding_times else None
        ),
        packages_with_usage=sum(1 for score in per_package if score.usage is not None),
        detected=sum(len(score.matched_defect_ids) for score in per_package),
        flagged=sum(len(score.flagged_defect_ids) for score in per_package),
        status_mismatches=sum(len(score.status_mismatch_defect_ids) for score in per_package),
        flagged_below_expected=sum(
            len(score.flagged_below_expected_defect_ids) for score in per_package
        ),
        cleared=sum(len(score.cleared_defect_ids) for score in per_package),
        contradictions=_sum_assessed(
            length_or_none(score.contradicted_condition_ids) for score in per_package
        ),
        confirmations=_sum_assessed(
            length_or_none(score.confirmed_condition_ids) for score in per_package
        ),
        forbidden_hits=_sum_assessed(
            length_or_none(score.forbidden_hit_finding_ids) for score in per_package
        ),
        withdrawn_forbidden_hits=_sum_assessed(
            length_or_none(score.withdrawn_forbidden_hit_finding_ids) for score in per_package
        ),
        tuned_on_false_alarms=sum(
            len(score.tuned_on_false_alarm_finding_ids) for score in per_package
        ),
        coverage_mismatches=_sum_assessed(
            length_or_none(score.coverage_mismatches) for score in per_package
        ),
        findings_by_origin=by_origin(
            origin for score in per_package for origin in final_state_origins(score)
        ),
        false_alarms_by_origin=by_origin(
            origin for score in per_package for origin in false_alarm_origins(score)
        ),
        recall_by_producer=RecallByProducer(
            model=_recall_by_tag(defects, "model"), code=_recall_by_tag(defects, "code")
        ),
        held_out_model_defects=sum(len(key.held_out_model_defect_ids()) for key in answer_keys),
        re_asks=_sum_assessed(length_or_none(score.re_asks) for score in per_package),
        open_repeats=_sum_assessed(length_or_none(score.open_repeats) for score in per_package),
        unanswerable_requests=_sum_assessed(
            length_or_none(score.unanswerable_requests) for score in per_package
        ),
        unmatched_requests=_sum_assessed(
            length_or_none(score.unmatched_requests) for score in per_package
        ),
        unscripted_questions=_sum_assessed(
            length_or_none(score.unscripted_questions) for score in per_package
        ),
        question_count_misses=_sum_assessed(question_count_misses(score) for score in per_package),
        bound_reached=_sum_assessed(
            None if score.bound_reached is None else int(score.bound_reached)
            for score in per_package
        ),
    )


def _package_on_disk(directory: Path) -> EvidencePackage | None:
    """The package a set entry names, or `None` when its folder holds no `package.json`: a
    key-only key's unbuilt package, which the key loader then reads the key against."""
    if not (directory / PACKAGE_FILE_NAME).is_file():
        return None
    return load_package(directory).package


def held_out_flag_error(package_id: str, flag: bool, answer_key: AnswerKey) -> str | None:
    """The refusal of a set flag that disagrees with its key, or `None` when it agrees: the
    flag is `AnswerKey.holds_held_out()` (`scoring.md` 6; US5-12). The one writer of the line,
    which the set summary calls too."""
    if flag == answer_key.holds_held_out():
        return None
    held = sum(1 for item in _graded_items(answer_key) if item.tag == "held_out")
    return (
        f"{package_id}: the set marks it held_out={json.dumps(flag)}, but its key holds {held} "
        "held-out items; the flag is derived from the key"
    )


def key_package_error(entry: BenchmarkPackageRef, answer_key: AnswerKey) -> str | None:
    """The refusal of a key that names another package than its set entry, or `None` when it
    names the entry's: `answer-key.md` 4 row 2's set half (FR-009), whose stem half the key
    loader holds. Both ids and the key file's name, never its folder. The one writer of the
    line, which the set summary calls for every entry once its key loads, and `score_run` too.

    Only a keyed entry can be refused: a keyless one's key is `<package_id>.json`
    (`sets.key_path`), whose stem the loader already holds its `package_id` to.
    """
    if answer_key.package_id == entry.package_id:
        return None
    assert entry.key is not None  # a keyless entry's key is named by its package id
    return (
        f"{entry.package_id}: its key {entry.key.name} names package {answer_key.package_id}, "
        f"not the set entry's {entry.package_id}"
    )


def score_run(
    run_dir: Path | str, answer_keys_dir: Path | None, benchmark_set: BenchmarkSet,
    *, prices: pricing.PriceTable | None = None,
) -> Scorecard:
    """Score every package in `benchmark_set` from `<run_dir>/<package_id>/session.json`
    against its answer key, found by `sets.key_path`: the entry's own `key` in a keyed set,
    `<answer_keys_dir>/<package_id>.json` in a keyless one.

    Each key is read through `load_answer_key` against the package its set entry names (`None`
    when that folder holds no `package.json`); a key naming another package than its entry is
    refused, then a key-only key, since it has no package to have been reviewed, and so is a
    set flag its key does not back. Package order follows `benchmark_set.packages`;
    `distribution` mirrors `per_package`.
    """
    run_dir = Path(run_dir)
    checklist = load_checklist()
    words = load_words()
    per_package: list[PackageScore] = []
    answer_keys: list[AnswerKey] = []
    key_sha256: dict[str, str] = {}
    table = pricing.load_prices() if prices is None else prices
    unscored_packages: list[UnscoredPackage] = []
    failed_attempts: list[FailedAttempt] = []
    used_models: dict[tuple[str, str], PricedModel] = {}

    def attempt_cost(facts: runner.AttemptFacts) -> pricing.Cost:
        cost = pricing.price_rounds(facts.rounds, table=table)
        for round_ in facts.rounds:
            if pricing.price_rounds([round_], table=table).amount is None:
                continue
            entry = pricing.price_entry(table, round_.provider, round_.served_model)
            assert entry is not None  # a priced round necessarily resolved an entry
            used_models.setdefault((entry.provider, entry.model), PricedModel(
                provider=entry.provider,
                model=entry.model,
                **{
                    name: PriceSource(source=price.source, date=price.date)
                    for name in ("input", "cached_input", "output")
                    for price in [getattr(entry, name)]
                },
            ))
        return cost
    for ref in benchmark_set.packages:
        key_path = sets.key_path(ref, answer_keys_dir)
        package = _package_on_disk(ref.path)
        answer_key = load_answer_key(
            key_path, package=package, checklist=checklist, words=words
        )
        package_error = key_package_error(ref, answer_key)
        if package_error is not None:
            raise ValueError(package_error)
        if answer_key.key_only:
            raise ValueError(
                f"{ref.package_id}: its key is key-only (package not built); it cannot be scored"
            )
        assert package is not None  # the loader refuses a missing package not marked key-only
        flag_error = held_out_flag_error(ref.package_id, ref.held_out, answer_key)
        if flag_error is not None:
            raise ValueError(flag_error)
        key_sha256[ref.package_id] = sha256_of(key_path)
        answer_keys.append(answer_key)
        outcome = runner.package_outcome(run_dir, ref.package_id)
        for attempt in outcome.attempts:
            if attempt.kind == "infrastructure":
                facts = runner.attempt_facts(run_dir / attempt.folder)
                failed_attempts.append(FailedAttempt(
                    package_id=ref.package_id,
                    attempt=attempt.attempt,
                    class_=attempt.class_,
                    retries=facts.retries,
                    cost=attempt_cost(facts),
                    folder=attempt.folder,
                ))
        if outcome.kind == "infrastructure":
            unscored_packages.append(UnscoredPackage(
                package_id=ref.package_id,
                kind=outcome.kind,
                class_=outcome.class_,
                error_class=outcome.error_class,
                attempts=len(outcome.attempts),
                folder=outcome.folder,
            ))
            continue
        facts = runner.attempt_facts(run_dir / ref.package_id)
        per_package.append(
            _score_package(
                run_dir / ref.package_id,
                package_id=ref.package_id,
                held_out=ref.held_out,
                answer_key=answer_key,
                package=package,
                words=words,
                run_status=PackageRunStatus(
                    kind=outcome.kind, class_=outcome.class_, stop_reason=outcome.stop_reason,
                ),
                cost=attempt_cost(facts),
                served_models=facts.served_models,
            )
        )

    return Scorecard(
        scoring_rules_version=SCORING_RULES_VERSION,
        run_id=run_dir.resolve().name,
        benchmark_set=benchmark_set.name,
        scored_at=datetime.now(UTC),
        per_package=per_package,
        aggregate=_aggregate(per_package, answer_keys, failed_attempts=failed_attempts),
        distribution=[score.net_saved_minutes for score in per_package],
        key_sha256=key_sha256,
        unscored_packages=unscored_packages,
        failed_attempts=failed_attempts,
        price_table=(
            PriceTableRecord(prices_version=table.prices_version, models=list(used_models.values()))
            if used_models else None
        ),
    )


def read_scorecard(run_dir: Path | str) -> Scorecard:
    """The one reader of `<run_dir>/scorecard.json` (`scoring.md` 8).

    The version is read **before** the model is validated, so a scorecard scored under other
    rules is refused with what to do about it, never with a validation error naming a field it
    could not have had. Each refusal is one `ValueError` line naming the folder. The re-score
    line is fixed text, so the refusal reads no second file.
    """
    run_dir = Path(run_dir)
    raw = (run_dir / SCORECARD_FILE).read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{run_dir}: {SCORECARD_FILE} is not JSON ({error})") from None
    version = payload.get("scoring_rules_version", 1) if isinstance(payload, dict) else None
    if type(version) is int and version < SCORING_RULES_VERSION:
        raise ValueError(
            f"{run_dir}: {SCORECARD_FILE} was scored under scoring rules version {version}; "
            f"this build scores under {SCORING_RULES_VERSION}. Re-score it: swreview benchmark "
            f"score {run_dir} (add --answer-keys <dir> when its set names no keys; it reads the "
            "saved session; nothing is re-run)"
        )
    if type(version) is int and version > SCORING_RULES_VERSION:
        raise ValueError(
            f"{run_dir}: {SCORECARD_FILE} was scored by a newer build (version {version}); "
            "compare it with that build, or re-score it with this one"
        )
    try:
        return Scorecard.model_validate_json(raw)
    except ValidationError as error:
        raise ValueError(
            f"{run_dir}: {SCORECARD_FILE} does not validate: {first_refusal(error)}"
        ) from None


def _fmt_count(value: int | None) -> str:
    return str(value) if value is not None else UNKNOWN


def _fmt_cached_share(share: float | None) -> str:
    """The cached share, or `unknown` while it is not publishable.

    Two reasons for the same word, both honest: probe L1 has not recorded that cached
    input is contained in input, so the ratio is not yet a share (FR-047); or the provider
    reported no counts to divide. `scorecard.json` carries the number either way, so
    flipping `CACHED_SHARE_PUBLISHABLE` publishes the column without rescoring a run.
    """
    if not CACHED_SHARE_PUBLISHABLE or share is None:
        return UNKNOWN
    return f"{share:.0%}"


def _fmt_recall(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def fmt_assessed(value: int | None) -> str:
    """A count some key may give nothing to grade: `not assessed` then, never 0. The scorecard's
    and the ledger's cells alike."""
    return NOT_ASSESSED if value is None else str(value)


def _fmt_assessed_total(value: int | None, assessed: int, packages: int) -> str:
    """An aggregate summed over the packages that assess it, saying how many of how many."""
    if value is None:
        return NOT_ASSESSED
    return f"{value} ({assessed} of {packages} packages)"


def _assessing(per_package: Sequence[PackageScore], column: str) -> int:
    """How many packages assess `column`: those whose value of it is not `null`."""
    return sum(1 for score in per_package if getattr(score, column) is not None)


def _fmt_withdrawn(scorecard: Scorecard) -> str:
    """The withdrawn forbidden hits' total: `unknown`, never 0 and never `not assessed`, when no
    package assesses it and some package's key forbids while its stream cannot be read
    (`scoring.md` 7); otherwise as every other column some key may give nothing to grade."""
    per_package = scorecard.per_package
    total = scorecard.aggregate.withdrawn_forbidden_hits
    unread = any(
        score.not_assessed.get(WITHDRAWN_COLUMN) not in (None, NO_FORBIDDEN_ENTRY)
        for score in per_package
    )
    if total is None and unread:
        return UNKNOWN
    return _fmt_assessed_total(total, _assessing(per_package, WITHDRAWN_COLUMN), len(per_package))


def fmt_origins(counts: Mapping[Origin, int], *, separator: str) -> str:
    """Each origin with a count, in `Origin`'s order, joined by `separator`, or `none` when every
    one is zero, so a cell is never blank. The scorecard's line (`, `) and the ledger's cells
    (` / `, feature 014 `contracts/provenance.md` 5) alike."""
    named = [f"{origin} {count}" for origin, count in counts.items() if count]
    return separator.join(named) if named else "none"


def render_scorecard_md(scorecard: Scorecard) -> str:
    """Render a per-package table plus the aggregate, for `scorecard.md`.

    The table gains **three** usage columns and not seven: the markdown is a scan, and
    `scorecard.json` holds every count the ledger renders. Feature 014 adds the outcome columns
    before them (`scoring.md` 7): detected, flagged, below expected, cleared, the false alarms of
    model origin, contradictions, forbidden hits and coverage mismatches, a column the key does
    not grade reading `not assessed`; and to the aggregate the forbidden, withdrawn and tuned-on
    hits, the coverage mismatches and each question column, re-asks split into seen (recorded)
    and refused, each saying how many packages assess it.
    """
    lines = [
        f"# Scorecard: {scorecard.benchmark_set} ({scorecard.run_id})",
        "",
        f"Scored at {scorecard.scored_at.isoformat()} under scoring rules version "
        f"{scorecard.scoring_rules_version}.",
        "",
        "| package | held out | valid | detected | flagged | below expected | cleared | missed "
        "| false alarms | of model origin | contradictions | forbidden hits | coverage mismatches "
        "| unresolved | net saved (min) | total tokens | cached share | round trips |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for score in scorecard.per_package:
        net_saved = "-" if score.net_saved_minutes is None else f"{score.net_saved_minutes:.1f}"
        total_tokens = _fmt_count(score.usage.total_tokens if score.usage is not None else None)
        model_false_alarms = of_model_origin(Counter(false_alarm_origins(score)))
        contradictions = fmt_assessed(length_or_none(score.contradicted_condition_ids))
        forbidden_hits = fmt_assessed(length_or_none(score.forbidden_hit_finding_ids))
        mismatches = fmt_assessed(length_or_none(score.coverage_mismatches))
        lines.append(
            f"| {score.package_id} | {score.held_out} | {score.valid_findings} | "
            f"{len(score.matched_defect_ids)} | {len(score.flagged_defect_ids)} | "
            f"{len(score.flagged_below_expected_defect_ids)} | {len(score.cleared_defect_ids)} | "
            f"{score.missed_known_defects} | {score.false_alarms} | {model_false_alarms} | "
            f"{contradictions} | {forbidden_hits} | {mismatches} | {score.unresolved_count} | "
            f"{net_saved} | {total_tokens} | {_fmt_cached_share(score.cached_input_share)} "
            f"| {_fmt_count(score.round_trips)} |"
        )

    aggregate = scorecard.aggregate
    per_package = scorecard.per_package
    packages = len(per_package)

    def total(value: int | None, column: str) -> str:
        return _fmt_assessed_total(value, _assessing(per_package, column), packages)

    re_asked = [row for score in per_package for row in score.re_asks or []]
    seen = sum(1 for row in re_asked if row.outcome == "recorded")
    re_asks = total(aggregate.re_asks, "re_asks")
    if aggregate.re_asks is not None:
        re_asks += f", seen {seen}, refused {len(re_asked) - seen}"
    by_producer = aggregate.recall_by_producer
    false_alarm_rate = (
        "-" if aggregate.false_alarm_rate is None else f"{aggregate.false_alarm_rate:.0%}"
    )
    median_net_saved = (
        "-"
        if aggregate.median_net_saved_minutes is None
        else f"{aggregate.median_net_saved_minutes:.1f}"
    )
    median_first_finding = (
        UNKNOWN
        if aggregate.median_seconds_to_first_finding is None
        else f"{aggregate.median_seconds_to_first_finding:.1f} s"
    )
    false_alarms_by_origin = fmt_origins(aggregate.false_alarms_by_origin, separator=", ")
    lines += [
        "",
        "## Aggregate",
        "",
        f"- packages: {aggregate.packages} ({aggregate.held_out_packages} held out)",
        f"- valid findings: {aggregate.valid_findings}",
        f"- detected: {aggregate.detected} of {known_defect_count(scorecard)} "
        f"(flagged {aggregate.flagged}; status mismatches {aggregate.status_mismatches})",
        f"- flagged below expected: {aggregate.flagged_below_expected}",
        f"- cleared: {aggregate.cleared}",
        f"- missed known defects: {aggregate.missed_known_defects}",
        f"- false alarms: {aggregate.false_alarms}",
        f"- false alarms by origin: {false_alarms_by_origin}",
        f"- contradictions: {total(aggregate.contradictions, 'contradicted_condition_ids')}",
        f"- confirmations: {total(aggregate.confirmations, 'confirmed_condition_ids')}",
        f"- forbidden hits: {total(aggregate.forbidden_hits, 'forbidden_hit_finding_ids')}",
        f"- withdrawn forbidden hits: {_fmt_withdrawn(scorecard)}",
        f"- tuned-on false alarms: {aggregate.tuned_on_false_alarms}",
        f"- coverage mismatches: {total(aggregate.coverage_mismatches, 'coverage_mismatches')}",
        f"- unresolved: {aggregate.unresolved_count}",
        f"- recall (held-out): {_fmt_recall(aggregate.recall)}",
        f"- recall by producer and tag: model held out {_fmt_recall(by_producer.model.held_out)}, "
        f"model tuned on {_fmt_recall(by_producer.model.tuned_on)}, "
        f"code held out {_fmt_recall(by_producer.code.held_out)}, "
        f"code tuned on {_fmt_recall(by_producer.code.tuned_on)}",
        f"- held-out model-produced defects: {aggregate.held_out_model_defects}",
        f"- re-asks: {re_asks}",
        f"- repeats of open questions: {total(aggregate.open_repeats, 'open_repeats')}",
        "- unanswerable requests: "
        f"{total(aggregate.unanswerable_requests, 'unanswerable_requests')}",
        f"- unmatched requests: {total(aggregate.unmatched_requests, 'unmatched_requests')}",
        "- question-count misses: "
        f"{total(aggregate.question_count_misses, 'question_counts')}",
        "- unscripted questions: "
        f"{total(aggregate.unscripted_questions, 'unscripted_questions')}",
        f"- answer-turn bound reached: {total(aggregate.bound_reached, 'bound_reached')}",
        f"- false-alarm rate: {false_alarm_rate}",
        f"- median net saved minutes ({aggregate.packages_with_timing} packages with timing): "
        f"{median_net_saved}",
        f"- total tokens ({aggregate.packages_with_usage} packages with usage): "
        f"{_fmt_count(aggregate.total_tokens)}",
        f"- round trips: {_fmt_count(aggregate.round_trips)}",
        f"- median seconds to first finding: {median_first_finding}",
    ]
    return "\n".join(lines) + "\n"
