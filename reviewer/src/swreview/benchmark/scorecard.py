"""Score a finished benchmark run against its withheld answer keys.

`score_run` is the only place in the benchmark harness that combines a run's
`session.json` files with `swreview.benchmark.answer_key` - the run itself never sees an
answer key (constitution Principle VI, FR-025). Output shapes follow data-model.md
section 3 and must validate against `contracts/scorecard.schema.json`.

## What a run cost

Feature 005 adds the usage columns beside the quality ones, because every adoption
decision reads both: a lever that halves the token bill and loses a known defect is not
adopted. The counts are **copied** from `session.usage`, never re-summed, and the one
derivation, `cached_input_share`, is `TokenUsage`'s own property. `seconds_to_first_finding`
is read from the `events.jsonl` beside the `session.json` - one more file read per package
and still no answer-key contact. A session that carries no usage scores to nulls; a null
in any package makes that aggregate total null rather than a partial sum.

## Matching rule

A finding matches a known defect (or a correct condition) when both hold:

1. **check**: `finding.check` equals the target's `check` (an *exact* match), or the two
   share the same prefix - everything before the last dot - as a *prefix* match. This
   lets an answer key name a family with a trailing `*`, e.g. `fastener.*` against a
   finding checked as `fastener.bottoming`: both reduce to the prefix `fastener`.
2. **components**: `finding.component_ids` and the target's `component_ids` intersect.

Exact match is tried before prefix match; `classify_match` returns which one fired (or
`None`) so callers - including tests - can tell them apart.

Only `demonstrated` and `suspected` findings are classified as valid or a false alarm.
`unresolved` findings are counted separately and never as false alarms; `checked_within_scope`
findings are excluded from all three counts. A `demonstrated`/`suspected` finding that
matches no known defect but does match a correct condition is excluded too - it is not a
false alarm and it is not a valid finding.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from swreview.agent.providers import CACHED_SHARE_PUBLISHABLE, TokenUsage
from swreview.agent.runner import EVENTS_FILE_NAME
from swreview.benchmark.answer_key import AnswerKey, CorrectCondition, load_answer_key
from swreview.benchmark.sets import BenchmarkSet
from swreview.findings import Finding, ReviewModel
from swreview.report.session import ReviewSession, load_session

MatchRule = Literal["exact", "prefix"]

UNKNOWN = "unknown"
"""What a number no run reported renders as in the markdown. Never `0`, which is a
measurement, and never the `-` the timing columns have always used for a missing minute
count: a token column that reads `-` invites "no tokens" (Principle I)."""


def check_prefix(check: str) -> str:
    """Everything in `check` before its last dot, or `check` itself if there is none."""
    return check.rsplit(".", 1)[0] if "." in check else check


def classify_match(finding: Finding, check: str, component_ids: Sequence[str]) -> MatchRule | None:
    """Whether `finding` matches a known defect or correct condition named by `check` /
    `component_ids`: `"exact"`, `"prefix"`, or `None` if neither the check nor the
    components line up.
    """
    if finding.check == check:
        rule: MatchRule | None = "exact"
    elif check_prefix(finding.check) == check_prefix(check):
        rule = "prefix"
    else:
        return None
    if not set(finding.component_ids) & set(component_ids):
        return None
    return rule


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
    """The first `finding` event's `at` minus `session.started`'s, from `events.jsonl`.
    `None` when the run found nothing, or when the run kept no event stream."""

    matched_defect_ids: list[str] = Field(default_factory=list)
    missed_defect_ids: list[str] = Field(default_factory=list)
    false_alarm_finding_ids: list[str] = Field(default_factory=list)


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


class Scorecard(ReviewModel):
    run_id: str
    benchmark_set: str
    scored_at: datetime = Field(strict=False)
    per_package: Annotated[list[PackageScore], Field(min_length=1)]
    aggregate: Aggregate
    distribution: list[float | None]


def _score_package_findings(
    findings: Sequence[Finding], answer_key: AnswerKey
) -> tuple[list[str], list[str], list[str], int]:
    """Return `(matched_defect_ids, missed_defect_ids, false_alarm_finding_ids, unresolved_count)`.

    Both lists of defect ids preserve `answer_key.known_defects` order.
    """
    matched_defect_ids: set[str] = set()
    false_alarm_finding_ids: list[str] = []
    unresolved_count = 0

    for finding in findings:
        if finding.status == "unresolved":
            unresolved_count += 1
            continue
        if finding.status == "checked_within_scope":
            continue
        # status is "demonstrated" or "suspected"
        matched_any = False
        for defect in answer_key.known_defects:
            if classify_match(finding, defect.check, defect.component_ids) is not None:
                matched_any = True
                matched_defect_ids.add(defect.id)
        if matched_any:
            continue
        matched_correct_condition = _matches_any_condition(finding, answer_key.correct_conditions)
        if matched_correct_condition:
            continue
        false_alarm_finding_ids.append(finding.id)

    missed_defect_ids = [
        defect.id for defect in answer_key.known_defects if defect.id not in matched_defect_ids
    ]
    ordered_matched_ids = [
        defect.id for defect in answer_key.known_defects if defect.id in matched_defect_ids
    ]
    return ordered_matched_ids, missed_defect_ids, false_alarm_finding_ids, unresolved_count


def _matches_any_condition(finding: Finding, conditions: Sequence[CorrectCondition]) -> bool:
    return any(
        classify_match(finding, condition.check, condition.component_ids) is not None
        for condition in conditions
    )


def _count_valid_findings(findings: Sequence[Finding], answer_key: AnswerKey) -> int:
    """Findings with `demonstrated`/`suspected` status that matched at least one known
    defect - counted per finding, not per defect (a finding may match more than one).
    """
    count = 0
    for finding in findings:
        if finding.status not in ("demonstrated", "suspected"):
            continue
        if any(
            classify_match(finding, defect.check, defect.component_ids) is not None
            for defect in answer_key.known_defects
        ):
            count += 1
    return count


def seconds_to_first_finding(events_path: Path) -> float | None:
    """How long the run took to say something, from the stream it already writes.

    Both stamps are already there: `session.started` and every `finding` event carry an
    `at` (VERIFIED, `EventSink.emit`), so this needs no new recording and, crucially, no
    answer key - `score_run` reads one more file per package and Principle VI and FR-025
    are untouched.

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
        elif event.get("type") == "finding" and started_at is not None:
            return (datetime.fromisoformat(event["at"]) - started_at).total_seconds()
    return None


def _wall_clock_s(session: ReviewSession) -> float | None:
    """`started_at` to `ended_at`, or `None` for a session that never ended."""
    if session.ended_at is None:
        return None
    return (session.ended_at - session.started_at).total_seconds()


def _score_package(
    package_id: str,
    held_out: bool,
    session: ReviewSession,
    answer_key: AnswerKey,
    first_finding_s: float | None,
) -> PackageScore:
    matched_defect_ids, missed_defect_ids, false_alarm_ids, unresolved_count = (
        _score_package_findings(session.findings, answer_key)
    )
    valid_findings = _count_valid_findings(session.findings, answer_key)
    timing = session.timing
    assisted_minutes = (
        timing.assisted_supervision_minutes
        + timing.assisted_verification_minutes
        + timing.false_alarm_handling_minutes
    )
    usage = session.usage
    return PackageScore(
        package_id=package_id,
        held_out=held_out,
        session_id=str(session.session_id),
        valid_findings=valid_findings,
        missed_known_defects=len(missed_defect_ids),
        false_alarms=len(false_alarm_ids),
        unresolved_count=unresolved_count,
        baseline_minutes=timing.baseline_minutes,
        assisted_minutes=assisted_minutes,
        unattended_runtime_minutes=timing.unattended_runtime_minutes,
        net_saved_minutes=timing.net_saved_minutes,
        usage=usage.totals if usage is not None else None,
        round_trips=usage.rounds if usage is not None else None,
        cached_input_share=usage.totals.cached_input_share if usage is not None else None,
        wall_clock_s=_wall_clock_s(session),
        seconds_to_first_finding=first_finding_s,
        matched_defect_ids=matched_defect_ids,
        missed_defect_ids=missed_defect_ids,
        false_alarm_finding_ids=false_alarm_ids,
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


def _aggregate(per_package: Sequence[PackageScore]) -> Aggregate:
    held_out_scores = [score for score in per_package if score.held_out]
    matched_held_out = sum(len(score.matched_defect_ids) for score in held_out_scores)
    missed_held_out = sum(len(score.missed_defect_ids) for score in held_out_scores)
    held_out_known_defects = matched_held_out + missed_held_out
    recall = matched_held_out / held_out_known_defects if held_out_known_defects else None

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
        recall=recall,
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
    )


def score_run(
    run_dir: Path | str, answer_keys_dir: Path | str, benchmark_set: BenchmarkSet
) -> Scorecard:
    """Score every package in `benchmark_set` from `<run_dir>/<package_id>/session.json`
    against `<answer_keys_dir>/<package_id>.json`.

    Package order follows `benchmark_set.packages`; `distribution` mirrors `per_package`.
    """
    run_dir = Path(run_dir)
    per_package: list[PackageScore] = []
    for ref in benchmark_set.packages:
        package_dir = run_dir / ref.package_id
        session = load_session(package_dir / "session.json")
        answer_key = load_answer_key(answer_keys_dir, ref.package_id)
        per_package.append(
            _score_package(
                ref.package_id,
                ref.held_out,
                session,
                answer_key,
                seconds_to_first_finding(package_dir / EVENTS_FILE_NAME),
            )
        )

    return Scorecard(
        run_id=Path(run_dir).resolve().name,
        benchmark_set=benchmark_set.name,
        scored_at=datetime.now(UTC),
        per_package=per_package,
        aggregate=_aggregate(per_package),
        distribution=[score.net_saved_minutes for score in per_package],
    )


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


def render_scorecard_md(scorecard: Scorecard) -> str:
    """Render a per-package table plus the aggregate, for `scorecard.md`.

    The table gains **three** usage columns and not seven: the markdown is a scan, and
    `scorecard.json` holds every count the ledger renders.
    """
    lines = [
        f"# Scorecard: {scorecard.benchmark_set} ({scorecard.run_id})",
        "",
        f"Scored at {scorecard.scored_at.isoformat()}.",
        "",
        "| package | held out | valid | missed | false alarms | unresolved | net saved (min) "
        "| total tokens | cached share | round trips |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for score in scorecard.per_package:
        net_saved = "-" if score.net_saved_minutes is None else f"{score.net_saved_minutes:.1f}"
        total_tokens = _fmt_count(score.usage.total_tokens if score.usage is not None else None)
        lines.append(
            f"| {score.package_id} | {score.held_out} | {score.valid_findings} | "
            f"{score.missed_known_defects} | {score.false_alarms} | {score.unresolved_count} | "
            f"{net_saved} | {total_tokens} | {_fmt_cached_share(score.cached_input_share)} "
            f"| {_fmt_count(score.round_trips)} |"
        )

    aggregate = scorecard.aggregate
    recall = "-" if aggregate.recall is None else f"{aggregate.recall:.0%}"
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
        f"- missed known defects: {aggregate.missed_known_defects}",
        f"- false alarms: {aggregate.false_alarms}",
        f"- unresolved: {aggregate.unresolved_count}",
        f"- recall (held-out): {recall}",
        f"- false-alarm rate: {false_alarm_rate}",
        f"- median net saved minutes ({aggregate.packages_with_timing} packages with timing): "
        f"{median_net_saved}",
        f"- total tokens ({aggregate.packages_with_usage} packages with usage): "
        f"{_fmt_count(aggregate.total_tokens)}",
        f"- round trips: {_fmt_count(aggregate.round_trips)}",
        f"- median seconds to first finding: {median_first_finding}",
    ]
    return "\n".join(lines) + "\n"
