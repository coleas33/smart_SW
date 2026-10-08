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
is read from the `events.jsonl` beside the `session.json` - one more file read per package
and still no answer-key contact. A session that carries no usage scores to nulls; a null
in any package makes that aggregate total null rather than a partial sum.

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
  defect, so it is a false alarm too.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import Field, ValidationError

from swreview.agent.checklist import load_checklist
from swreview.agent.providers import CACHED_SHARE_PUBLISHABLE, TokenUsage
from swreview.agent.runner import EVENTS_FILE_NAME, SESSION_FILE_NAME
from swreview.benchmark import matching
from swreview.benchmark.answer_key import load_answer_key
from swreview.benchmark.answer_key_model import AnswerKey, ExpectedStatus, Producer, Tag
from swreview.benchmark.digest import sha256_of
from swreview.benchmark.origins import MODEL_ORIGINS, Origin, finding_origin
from swreview.benchmark.sets import BenchmarkSet
from swreview.findings import Finding, ReviewModel, carried_count
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import Coverage, ReviewSession, load_session
from swreview.report.summary import load_words

SCORING_RULES_VERSION = 2
"""The rules this build scores by (`scoring.md` 8): 2 is feature 014's scorer slice, exact and
family matching, references, 13A's statuses, conditions, origins and recall by tag. A scorecard
without the field was scored under version 1. Pinned by value in
`tests/unit/test_scoring_rules_version.py` until the validation slice's version record exists
(plan decision INT-11)."""

SCORECARD_FILE = "scorecard.json"
"""What `benchmark score` writes into a run folder, and `read_scorecard` reads."""

NOT_ASSESSED = "not assessed"
"""What a column the key gives nothing to grade renders as: a key with no entry of the list the
column reads is no measurement of it, never 0 (FR-021)."""

NO_CORRECT_CONDITION = "the key holds no correct condition"
"""`not_assessed`'s reason for the two condition columns of a key without one."""

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


GradedKind = Literal["known_defect", "correct_condition"]
"""Which list of the key a graded item came from."""


class GradedItem(ReviewModel):
    """One key entry as the scorecard copies it (`scoring.md` 6): compare reads no key, so the
    verdict splits recall and false alarms from these."""

    id: str
    kind: GradedKind
    tag: Tag
    producer: Producer | None
    """A known defect's, `null` for a correct condition."""

    expected_status: ExpectedStatus | None
    """A known defect's, `null` for a correct condition."""


class RecallByTag(ReviewModel):
    """Detected over all, for the known defects of one tag; `null` when there is none."""

    held_out: Annotated[float, Field(ge=0, le=1)] | None
    tuned_on: Annotated[float, Field(ge=0, le=1)] | None


class RecallByProducer(ReviewModel):
    """Recall per producer and tag (FR-006): the model's and code's defects apart."""

    model: RecallByTag
    code: RecallByTag


class PackageScore(ReviewModel):
    package_id: str
    held_out: bool
    session_id: str
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

    finding_origins: dict[str, Origin]
    """Every final-state finding's origin, by finding id, in session order (`scoring.md` 5.5)."""

    graded_items: list[GradedItem]
    """Every key entry, in key order: known defects, then correct conditions."""

    not_assessed: dict[str, str]
    """The reason for every `null` column above, and for none other."""


class Aggregate(ReviewModel):
    packages: int = Field(ge=1)
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

    findings_by_origin: dict[Origin, int]
    false_alarms_by_origin: dict[Origin, int]
    """Every origin, zeros included, so two arms line up origin for origin."""

    recall_by_producer: RecallByProducer
    held_out_model_defects: int = Field(ge=0)
    """The held-out model-produced defects every package's key names
    (`AnswerKey.held_out_model_defect_ids()`)."""


class Scorecard(ReviewModel):
    scoring_rules_version: int = Field(ge=1)
    """`SCORING_RULES_VERSION` when it was scored; `read_scorecard` reads it before anything
    else."""

    run_id: str
    benchmark_set: str
    scored_at: datetime = Field(strict=False)
    per_package: Annotated[list[PackageScore], Field(min_length=1)]
    aggregate: Aggregate
    distribution: list[float | None]
    key_sha256: dict[str, str]
    """Each package's key file, by its raw bytes' `sha256_of`: compare refuses a study whose runs
    were scored against two versions of one key (plan decision INT-16)."""


def _graded_items(answer_key: AnswerKey) -> list[GradedItem]:
    """Every entry of the key as the scorecard copies it, known defects then conditions."""
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
            GradedItem(
                id=condition.id,
                kind="correct_condition",
                tag=condition.tag,
                producer=None,
                expected_status=None,
            )
            for condition in answer_key.correct_conditions
        ),
    ]


def _matches_by_entry(
    findings: Sequence[Finding], answer_key: AnswerKey
) -> dict[str, list[Finding]]:
    """Each entry's matching findings, in session order: the one pass through the matcher every
    outcome below is read from."""
    return {
        entry.id: [finding for finding in findings if matching.matches(finding, entry)]
        for entry in [*answer_key.known_defects, *answer_key.correct_conditions]
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


def seconds_to_first_finding(events_path: Path) -> float | None:
    """How long the run took to find something itself, from the stream it already writes.

    Both stamps are already there: `session.started` and every `finding` event carry an
    `at` (VERIFIED, `EventSink.emit`), so this needs no new recording and, crucially, no
    answer key - `score_run` reads one more file per package and Principle VI and FR-025
    are untouched.

    **A carried finding does not start the clock.** Lever 11a writes its carried findings
    during `start_review` setup, before the first turn (`carry_over.carry_over_findings`),
    so a stream that counted them would report a second or two for the on-arm of the A/B and
    call it speed - timing the carry rather than the review. A lever that "improves" a
    number by remembering is not an improvement (FR-104), and the scorecard's job is to show
    that rather than bury it, so this reads the first finding whose `carried_over_from` is
    absent or null. `carried_findings` beside it is what counts the rest.

    `None` rather than an error whenever the number cannot be had: no stream (a run made
    before the convention is still a real run), no finding, no `session.started`, or a
    stream truncated by a process that died mid-write. The scorer's job is to score the
    session; an unreadable auxiliary file makes one column unknown, not the run unscored.
    """
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    started_at: datetime | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        if event.get("type") == "session.started" and started_at is None:
            started_at = datetime.fromisoformat(event["at"])
        elif (
            event.get("type") == "finding"
            and started_at is not None
            and event.get("body", {}).get("carried_over_from") is None
        ):
            return (datetime.fromisoformat(event["at"]) - started_at).total_seconds()
    return None


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
) -> PackageScore:
    """Score one package folder as a run leaves it, `session.json` and `events.jsonl`, against
    its loaded key: what `score_run` does per package, and what the oracle and null reviews of
    the validation are scored through, since `score_run` refuses a key-only key."""
    session = load_session(package_dir / SESSION_FILE_NAME)
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
    not_assessed = (
        {}
        if contradicted is not None
        else {
            "contradicted_condition_ids": NO_CORRECT_CONDITION,
            "confirmed_condition_ids": NO_CORRECT_CONDITION,
        }
    )
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
        seconds_to_first_finding=seconds_to_first_finding(package_dir / EVENTS_FILE_NAME),
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
        finding_origins={finding.id: finding_origin(finding, session) for finding in findings},
        graded_items=_graded_items(answer_key),
        not_assessed=not_assessed,
    )


def _sum_or_none(values: Iterable[int | None]) -> int | None:
    """Add the counts, unless any one of them is unknown, in which case so is the sum.

    The same rule `SessionUsage.summed` applies one level down, over the rounds of one
    session, applied here over the packages of one run. A partial sum silently understates
    and no reader of the number can tell that it happened.
    """
    collected = list(values)
    if any(value is None for value in collected):
        return None
    return sum(value for value in collected if value is not None)


def _token_totals(per_package: Sequence[PackageScore], field: str) -> int | None:
    """One `TokenUsage` count summed over packages; a package with no usage is unknown."""
    return _sum_or_none(
        getattr(score.usage, field) if score.usage is not None else None for score in per_package
    )


def _sum_assessed(values: Iterable[int | None]) -> int | None:
    """Add the counts of the packages that assess a column; `None` when none does.

    Not `_sum_or_none`'s rule, and deliberately: a `None` here is a package whose key gives the
    column nothing to grade, not a number that went unreported, so it is left out of the sum
    rather than making it unknown (`scoring.md` 7)."""
    assessed = [value for value in values if value is not None]
    return sum(assessed) if assessed else None


def length_or_none(values: Sequence[str] | None) -> int | None:
    """How many ids a list some key may give nothing to grade holds, `None` for no list: the
    scorecard's sums and the ledger's per-package cells read it alike."""
    return None if values is None else len(values)


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


def _aggregate(per_package: Sequence[PackageScore], answer_keys: Sequence[AnswerKey]) -> Aggregate:
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
        round_trips=_sum_or_none(score.round_trips for score in per_package),
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
        findings_by_origin=by_origin(
            origin for score in per_package for origin in score.finding_origins.values()
        ),
        false_alarms_by_origin=by_origin(
            origin for score in per_package for origin in false_alarm_origins(score)
        ),
        recall_by_producer=RecallByProducer(
            model=_recall_by_tag(defects, "model"), code=_recall_by_tag(defects, "code")
        ),
        held_out_model_defects=sum(len(key.held_out_model_defect_ids()) for key in answer_keys),
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


def score_run(
    run_dir: Path | str, answer_keys_dir: Path | str, benchmark_set: BenchmarkSet
) -> Scorecard:
    """Score every package in `benchmark_set` from `<run_dir>/<package_id>/session.json`
    against `<answer_keys_dir>/<package_id>.json`.

    Each key is read through `load_answer_key` against the package its set entry names (`None`
    when that folder holds no `package.json`); a key-only key is refused, since it has no
    package to have been reviewed, and so is a set flag its key does not back. Package order
    follows `benchmark_set.packages`; `distribution` mirrors `per_package`.
    """
    run_dir = Path(run_dir)
    checklist = load_checklist()
    words = load_words()
    per_package: list[PackageScore] = []
    answer_keys: list[AnswerKey] = []
    key_sha256: dict[str, str] = {}
    for ref in benchmark_set.packages:
        key_path = Path(answer_keys_dir) / f"{ref.package_id}.json"
        answer_key = load_answer_key(
            key_path, package=_package_on_disk(ref.path), checklist=checklist, words=words
        )
        if answer_key.key_only:
            raise ValueError(
                f"{ref.package_id}: its key is key-only (package not built); it cannot be scored"
            )
        flag_error = held_out_flag_error(ref.package_id, ref.held_out, answer_key)
        if flag_error is not None:
            raise ValueError(flag_error)
        key_sha256[ref.package_id] = sha256_of(key_path)
        answer_keys.append(answer_key)
        per_package.append(
            _score_package(
                run_dir / ref.package_id,
                package_id=ref.package_id,
                held_out=ref.held_out,
                answer_key=answer_key,
            )
        )

    return Scorecard(
        scoring_rules_version=SCORING_RULES_VERSION,
        run_id=run_dir.resolve().name,
        benchmark_set=benchmark_set.name,
        scored_at=datetime.now(UTC),
        per_package=per_package,
        aggregate=_aggregate(per_package, answer_keys),
        distribution=[score.net_saved_minutes for score in per_package],
        key_sha256=key_sha256,
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
        first = error.errors(include_url=False)[0]
        field = ".".join(str(part) for part in first["loc"])
        where = f"{field}: " if field else ""
        raise ValueError(
            f"{run_dir}: {SCORECARD_FILE} does not validate: {where}{first['msg']}"
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


def _fmt_origins(counts: Mapping[Origin, int]) -> str:
    """Each origin with a count, in `Origin`'s order, or `none`."""
    named = [f"{origin} {count}" for origin, count in counts.items() if count]
    return ", ".join(named) if named else "none"


def render_scorecard_md(scorecard: Scorecard) -> str:
    """Render a per-package table plus the aggregate, for `scorecard.md`.

    The table gains **three** usage columns and not seven: the markdown is a scan, and
    `scorecard.json` holds every count the ledger renders. Feature 014 adds the outcome columns
    before them (`scoring.md` 7): detected, flagged, below expected, cleared, the false alarms of
    model origin and contradictions, a column the key does not grade reading `not assessed`.
    """
    lines = [
        f"# Scorecard: {scorecard.benchmark_set} ({scorecard.run_id})",
        "",
        f"Scored at {scorecard.scored_at.isoformat()} under scoring rules version "
        f"{scorecard.scoring_rules_version}.",
        "",
        "| package | held out | valid | detected | flagged | below expected | cleared | missed "
        "| false alarms | of model origin | contradictions | unresolved | net saved (min) "
        "| total tokens | cached share | round trips |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for score in scorecard.per_package:
        net_saved = "-" if score.net_saved_minutes is None else f"{score.net_saved_minutes:.1f}"
        total_tokens = _fmt_count(score.usage.total_tokens if score.usage is not None else None)
        model_false_alarms = of_model_origin(Counter(false_alarm_origins(score)))
        contradictions = fmt_assessed(length_or_none(score.contradicted_condition_ids))
        lines.append(
            f"| {score.package_id} | {score.held_out} | {score.valid_findings} | "
            f"{len(score.matched_defect_ids)} | {len(score.flagged_defect_ids)} | "
            f"{len(score.flagged_below_expected_defect_ids)} | {len(score.cleared_defect_ids)} | "
            f"{score.missed_known_defects} | {score.false_alarms} | {model_false_alarms} | "
            f"{contradictions} | {score.unresolved_count} | "
            f"{net_saved} | {total_tokens} | {_fmt_cached_share(score.cached_input_share)} "
            f"| {_fmt_count(score.round_trips)} |"
        )

    aggregate = scorecard.aggregate
    packages = len(scorecard.per_package)
    assessed = sum(
        1 for score in scorecard.per_package if score.contradicted_condition_ids is not None
    )
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
        f"- false alarms by origin: {_fmt_origins(aggregate.false_alarms_by_origin)}",
        f"- contradictions: {_fmt_assessed_total(aggregate.contradictions, assessed, packages)}",
        f"- confirmations: {_fmt_assessed_total(aggregate.confirmations, assessed, packages)}",
        f"- unresolved: {aggregate.unresolved_count}",
        f"- recall (held-out): {_fmt_recall(aggregate.recall)}",
        f"- recall by producer and tag: model held out {_fmt_recall(by_producer.model.held_out)}, "
        f"model tuned on {_fmt_recall(by_producer.model.tuned_on)}, "
        f"code held out {_fmt_recall(by_producer.code.held_out)}, "
        f"code tuned on {_fmt_recall(by_producer.code.tuned_on)}",
        f"- held-out model-produced defects: {aggregate.held_out_model_defects}",
        f"- false-alarm rate: {false_alarm_rate}",
        f"- median net saved minutes ({aggregate.packages_with_timing} packages with timing): "
        f"{median_net_saved}",
        f"- total tokens ({aggregate.packages_with_usage} packages with usage): "
        f"{_fmt_count(aggregate.total_tokens)}",
        f"- round trips: {_fmt_count(aggregate.round_trips)}",
        f"- median seconds to first finding: {median_first_finding}",
    ]
    return "\n".join(lines) + "\n"
