"""Score a finished benchmark run against its withheld answer keys.

`score_run` is the only place in the benchmark harness that combines a run's
`session.json` files with `swreview.benchmark.answer_key` - the run itself never sees an
answer key (constitution Principle VI, FR-025). Output shapes follow data-model.md
section 3 and must validate against `contracts/scorecard.schema.json`.

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

import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from swreview.benchmark.answer_key import AnswerKey, CorrectCondition, load_answer_key
from swreview.benchmark.sets import BenchmarkSet
from swreview.findings import Finding, ReviewModel
from swreview.report.session import ReviewSession, load_session

MatchRule = Literal["exact", "prefix"]


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


def _score_package(
    package_id: str, held_out: bool, session: ReviewSession, answer_key: AnswerKey
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
        matched_defect_ids=matched_defect_ids,
        missed_defect_ids=missed_defect_ids,
        false_alarm_finding_ids=false_alarm_ids,
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
        session = load_session(run_dir / ref.package_id / "session.json")
        answer_key = load_answer_key(answer_keys_dir, ref.package_id)
        per_package.append(_score_package(ref.package_id, ref.held_out, session, answer_key))

    return Scorecard(
        run_id=Path(run_dir).resolve().name,
        benchmark_set=benchmark_set.name,
        scored_at=datetime.now(UTC),
        per_package=per_package,
        aggregate=_aggregate(per_package),
        distribution=[score.net_saved_minutes for score in per_package],
    )


def render_scorecard_md(scorecard: Scorecard) -> str:
    """Render a per-package table plus the aggregate, for `scorecard.md`."""
    lines = [
        f"# Scorecard: {scorecard.benchmark_set} ({scorecard.run_id})",
        "",
        f"Scored at {scorecard.scored_at.isoformat()}.",
        "",
        "| package | held out | valid | missed | false alarms | unresolved | net saved (min) |",
        "|---|---|---|---|---|---|---|",
    ]
    for score in scorecard.per_package:
        net_saved = "-" if score.net_saved_minutes is None else f"{score.net_saved_minutes:.1f}"
        lines.append(
            f"| {score.package_id} | {score.held_out} | {score.valid_findings} | "
            f"{score.missed_known_defects} | {score.false_alarms} | {score.unresolved_count} | "
            f"{net_saved} |"
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
    ]
    return "\n".join(lines) + "\n"
