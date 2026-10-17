"""Offline pilot estimation, study sizing and the strict measurement record.

Approval is the owner's act. Reading a record neither approves it nor checks its
stored digest, whose mismatch compare names in its own refusal.
"""

from __future__ import annotations

import heapq
import math
import os
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

import numpy as np
from pydantic import AfterValidator, Field, field_validator, model_serializer

from swreview.agent import settings
from swreview.agent.checklist import load_checklist
from swreview.atomic import write_atomic
from swreview.benchmark import answer_key, digest, matching, sets, simulate, verdict
from swreview.benchmark import stats as statistics
from swreview.benchmark.runner import RunProvenance
from swreview.benchmark.sets import BenchmarkSet
from swreview.findings import FindingStatus, ReviewModel
from swreview.report.session import ReviewSession
from swreview.report.summary import load_words

PILOT_SCHEMA = 1


@dataclass(frozen=True)
class RunRecord:
    """A validated run's shared view for the pilot and the noise floor."""

    study_run: verdict.StudyRun
    folder: Path
    provenance: RunProvenance
    sessions: Mapping[str, ReviewSession]
    saved_set: BenchmarkSet
    study_key: tuple[str, str | None, str | None]


def _relative_folder(value: str) -> str:
    """Keep relative spelling, including siblings; reject foreign absolute paths too."""
    windows = PureWindowsPath(value)
    if windows.drive or windows.root or PurePosixPath(value).is_absolute():
        raise ValueError(f"run folder {value!r} must be relative to the measurement's folder")
    return value


RunFolder = Annotated[str, Field(min_length=1), AfterValidator(_relative_folder)]


class PilotIdentity(ReviewModel):
    pilot_schema: int
    study: str
    provider: str
    model: str
    commit: str
    set_digest: str
    scoring_rules_version: int = Field(ge=1)

    @field_validator("pilot_schema")
    @classmethod
    def _supported_schema(cls, value: int) -> int:
        if value != PILOT_SCHEMA:
            raise ValueError(f"pilot_schema {value} is not supported; expected {PILOT_SCHEMA}")
        return value


class PilotRun(ReviewModel):
    folder: RunFolder
    arm: Literal["off", "on"]
    repetition: int = Field(ge=1)
    started_at: str
    commit: str


class Count(ReviewModel):
    x: int = Field(ge=0)
    n: int = Field(ge=0)


class DefectRef(ReviewModel):
    package_id: str
    defect_id: str


class DefectCount(DefectRef, Count):
    """A named defect's detections or clearances over counted runs."""


class BetaFit(ReviewModel):
    """The corrected variance may be negative or unknown; limits have no finite a/b."""

    mu: float | None
    variance: float | None
    variance_computable: bool
    distribution: Literal["beta", "constant", "polarised"]
    a: float | None
    b: float | None
    reason: str | None


class ShockPoint(ReviewModel):
    sd: float = Field(ge=0)
    log_likelihood: float


class CoMovement(ReviewModel):
    grid: list[ShockPoint]
    estimate: float | None
    used: float | None


class FalseAlarmFit(ReviewModel):
    mean: float | None
    variance: float | None
    distribution: Literal["negative_binomial", "poisson"]
    k: float | None


class PackageRun(ReviewModel):
    run: RunFolder
    package_id: str


class CostTime(ReviewModel):
    mean_cost: float | None
    mean_wall_clock_s: float | None
    unknown_cost_runs: list[PackageRun]
    unknown_cost_count: int = Field(ge=0)


class NeverDetectedFinding(ReviewModel):
    """One final finding in one run, without the finding's local provenance paths."""

    run: RunFolder
    finding_id: str
    check: str
    status: FindingStatus
    title: str
    observed: str
    component_ids: list[str]
    document_ids: list[str]


class NeverDetected(DefectRef):
    findings: list[NeverDetectedFinding]


class Measured(ReviewModel):
    defect_counts: list[DefectCount]
    dropped_defects: list[DefectRef]
    dropped_defect_count: int = Field(ge=0)
    variance_excluded_defects: list[DefectRef]
    variance_excluded_count: int = Field(ge=0)
    beta_fit: BetaFit
    comovement: CoMovement
    code_defects: list[DefectCount]
    stops: Count
    clearances: list[DefectCount]
    false_alarm_fit: FalseAlarmFit
    cost_time: CostTime
    never_detected: list[NeverDetected]


class SimulatedRates(ReviewModel):
    """Unattainable shapes have unknown power, never a fabricated zero."""

    power_proportional: float | None
    power_room: float | None
    identical_loss: float | None
    identical_loss_upper: float | None
    no_loss_at_drop: float | None
    no_loss_at_drop_upper: float | None


class SizeTried(ReviewModel):
    reps: int = Field(ge=1)
    packages: int = Field(ge=0)
    held_out_model_defects: int = Field(ge=0)
    growth_units: int = Field(ge=0)
    alpha: float | None = Field(gt=0, le=0.5)
    cleared_guard_decides: bool
    simulated: SimulatedRates


class SizingResult(ReviewModel):
    reps: int = Field(ge=1)
    packages: int = Field(ge=0)
    held_out_model_defects: int = Field(ge=0)
    alpha: float | None = Field(gt=0, le=0.5)
    deciding_rules: list[str]
    cleared_guard_decides: bool
    simulated: SimulatedRates
    stress_case: float | None
    estimated_study_cost: float | None
    state: Literal["reached", "not reached", "not attainable"] | None = None
    cleared_guard_reason: str | None = None

    @model_serializer(mode="wrap")
    def _optional_search_fields(self, handler):
        """Older schema-1 files retain their exact computed blocks and digest."""
        result = handler(self)
        for name in ("state", "cleared_guard_reason"):
            if name not in self.model_fields_set:
                result.pop(name, None)
        return result


class ProjectedWallClock(ReviewModel):
    """Measured inputs and projected seconds at sizing.jobs, unknowns kept null."""

    off_run_s: float | None
    on_run_s: float | None
    study_s: float | None
    smoke_ratio: float | None
    smoke_off_s: float | None
    smoke_on_s: float | None
    mean_tokens_per_minute: float | None
    unknown_packages: list[str]


class Sizing(ReviewModel):
    cap: int = Field(ge=3)
    floor: int = Field(ge=1)
    seed: int
    sims: int = Field(ge=1)
    ladder: list[float]
    tried: list[SizeTried]
    pilot_packages: list[str]
    growth_units: int = Field(ge=0)
    jobs: int = Field(ge=1)
    projected_wall_clock: ProjectedWallClock
    result: SizingResult


class Approval(ReviewModel):
    approved: bool = False
    approved_at: str | None = None


class PilotMeasurement(ReviewModel):
    identity: PilotIdentity
    pilot_runs: list[PilotRun]
    smoke_runs: list[PilotRun]
    measured: Measured
    sizing: Sizing
    sizing_digest: str
    approval: Approval = Field(default_factory=Approval)


def sizing_digest(measurement: PilotMeasurement) -> str:
    """Hash parsed computed values; approval and the stored digest do not enter it."""
    computed = measurement.model_dump(
        mode="json", include={"identity", "pilot_runs", "smoke_runs", "measured", "sizing"},
    )
    return digest.canonical_sha256(computed)


def read_measurement(path: Path | str) -> PilotMeasurement:
    """Read just the strict JSON record, without opening any of its run folders."""
    return PilotMeasurement.model_validate_json(Path(path).read_bytes())


def _count_groups(counts):
    """RF-9 partitions: n=0 dropped, n=1 outside V, n>=2 eligible for V."""
    eligible, excluded, dropped = [], [], []
    for name, (x, n) in counts.items():
        if n == 0:
            dropped.append(name)
        elif n == 1:
            excluded.append(name)
        else:
            eligible.append((x / n, n))
    return eligible, excluded, dropped


def beta_fit(counts: Mapping[str | tuple[str, str], tuple[int, int]]) -> BetaFit:
    """Fit moments after removing binomial sampling variance (sample variance)."""
    for name, (x, n) in counts.items():
        if (isinstance(x, bool) or isinstance(n, bool)
                or not isinstance(x, int) or not isinstance(n, int) or not 0 <= x <= n):
            raise ValueError(f"counts for {name} must be integers with 0 <= x <= n")
    total = sum(n for x, n in counts.values())
    mu = sum(x for x, n in counts.values()) / total if total else None
    eligible, _, _ = _count_groups(counts)
    computable = len(eligible) >= 2
    variance = None
    if computable:
        rates = np.array([r for r, n in eligible])
        variance = float(np.var(rates, ddof=1) - np.mean([
            r * (1 - r) / (n - 1) for r, n in eligible
        ]))
    distribution, a, b = "constant", None, None
    reason = None
    if not computable:
        reason = "fewer than two defects with at least two counted runs"
    elif variance <= 0:
        reason = "corrected variance <= 0; every rate is mu"
    elif mu is not None and variance >= mu * (1 - mu):
        distribution = "polarised"
        reason = "corrected variance >= mu(1 - mu); rates are 0 or 1 with P(1) = mu"
    elif mu is not None:
        distribution = "beta"
        concentration = mu * (1 - mu) / variance - 1
        a, b = mu * concentration, (1 - mu) * concentration
    return BetaFit(mu=mu, variance=variance, variance_computable=computable,
                   distribution=distribution, a=a, b=b, reason=reason)


def shrunk_rates(counts, fit: BetaFit):
    """Posterior means, with the continuous constant/polarised limits explicit."""
    if fit.mu is None:
        return {}
    if fit.distribution == "beta":
        return {name: (fit.a + x) / (fit.a + fit.b + n)
                for name, (x, n) in counts.items()}
    if fit.distribution == "constant":
        return {name: fit.mu for name in counts}
    return {name: x / n if n else fit.mu for name, (x, n) in counts.items()}


def _arm_index(arm: Literal["off", "on"]) -> int:
    if arm not in verdict.ARMS:
        raise ValueError("arm must be off or on")
    return verdict.ARMS.index(arm)


def _defect_key(ref: verdict.DefectRef) -> tuple[str, str]:
    """Identity stays unambiguous when either component contains a slash."""
    return ref.package_id, ref.defect_id


def defect_counts(
    stats: verdict.StudyStats, arm: Literal["off", "on"],
) -> dict[tuple[str, str], tuple[int, int]]:
    """One observed study's main-figure counts, keyed by package/defect identity."""
    index = _arm_index(arm)
    if stats.detections.shape[0] != 1:
        raise ValueError("defect_counts needs one study")
    return {
        _defect_key(ref): (
            int(stats.detections[0, index, 0, i]), int(stats.counted_runs[0, index, 0, i]),
        ) for i, ref in enumerate(stats.defect_ids)
    }


def comovement(
    stats: verdict.StudyStats, fit: BetaFit, arm: Literal["off", "on"] = "off",
) -> CoMovement:
    """Profile the counted package-run vectors using the shared 40-node GH rule."""
    index = _arm_index(arm)
    vectors = stats.package_run_detections
    if vectors is None:
        raise ValueError("StudyStats.package_run_detections is required for comovement")
    rates = shrunk_rates(defect_counts(stats, arm), fit)
    if not rates:
        return CoMovement(grid=[], estimate=None, used=None)
    references = [_defect_key(ref) for ref in stats.defect_ids]
    grid = []
    for sd in np.arange(0, 2.51, 0.25):
        intercepts = statistics.intercept(
            statistics.intercept_table(float(sd)), [rates[name] for name in references],
        )
        logits = intercepts[:, None] + float(sd) * statistics._GH_POINTS
        log_yes = -np.logaddexp(0, -logits)
        log_no = -np.logaddexp(0, logits)
        likelihood = 0.0
        for package in range(len(stats.package_ids)):
            selected = stats.defect_packages == package
            if not np.any(selected):
                continue
            for run in np.flatnonzero(vectors.counted[0, index, :, package]):
                detected = vectors.detected[0, index, run, selected]
                conditional = np.sum(np.where(
                    detected[:, None], log_yes[selected], log_no[selected],
                ), axis=0)
                terms = conditional + np.log(statistics._GH_WEIGHTS)
                maximum = float(np.max(terms))
                if not math.isfinite(maximum):
                    raise ValueError(
                        f"fit's limit rates contradict the observed vectors for arm {arm!r}"
                    )
                likelihood += maximum + math.log(float(np.sum(np.exp(terms - maximum))))
        grid.append(ShockPoint(sd=float(sd), log_likelihood=likelihood))
    maximum = max(point.log_likelihood for point in grid)
    estimate = max(grid, key=lambda point: point.log_likelihood).sd
    used = max(point.sd for point in grid if 2 * (maximum - point.log_likelihood) <= 1.6424)
    return CoMovement(grid=grid, estimate=estimate, used=used)


def false_alarm_fit(counts: Sequence[int]) -> FalseAlarmFit:
    """Negative binomial by moments when overdispersed, otherwise Poisson."""
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in counts):
        raise ValueError("false alarm counts must be nonnegative integers")
    mean = float(np.mean(counts)) if counts else None
    variance = float(np.var(counts, ddof=1)) if len(counts) >= 2 else None
    overdispersed = mean is not None and variance is not None and variance > mean
    return FalseAlarmFit(mean=mean, variance=variance,
                         distribution="negative_binomial" if overdispersed else "poisson",
                         k=mean**2 / (variance - mean) if overdispersed else None)


def _relative_run(record: RunRecord, relative_to: Path) -> str:
    return Path(os.path.relpath(record.folder, relative_to)).as_posix()


def never_detected(records: Sequence[RunRecord], stats: verdict.StudyStats) -> list[NeverDetected]:
    """Find every target-overlapping final finding, without check/status filtering."""
    result = []
    checklist, words = load_checklist(), load_words()
    keys = {}
    for record in records:
        for entry in record.saved_set.packages:
            path = sets.key_path(entry, None)
            if path not in keys:
                keys[path] = answer_key.load_answer_key(
                    path, package=None, checklist=checklist, words=words,
                )
    held_out = {(ref.package_id, ref.defect_id) for i, ref in enumerate(stats.clear_ids)
                if stats.clear_held_out[i]}
    candidates = [
        (ref, bool(np.any(stats.detections[..., 0, index])))
        for index, ref in enumerate(stats.defect_ids)
    ]
    candidates.extend(
        (ref, bool(np.any(stats.code_detections[..., index])))
        for index, ref in enumerate(stats.code_ids)
        if (ref.package_id, ref.defect_id) in held_out
    )
    for ref, detected in candidates:
        if detected:
            continue
        findings = []
        for record in records:
            for entry in record.saved_set.packages:
                if entry.package_id != ref.package_id:
                    continue
                defect = next((item for item in keys[sets.key_path(entry, None)].known_defects
                               if item.id == ref.defect_id), None)
                session = record.sessions.get(ref.package_id)
                if defect is None or session is None:
                    continue
                for finding in session.findings:
                    if matching.targets_overlap(finding, defect):
                        findings.append(NeverDetectedFinding(
                            run=record.study_run.run, finding_id=finding.id, check=finding.check,
                            status=finding.status, title=finding.title, observed=finding.observed,
                            component_ids=list(finding.component_ids),
                            document_ids=sorted(matching.finding_documents(finding)),
                        ))
        result.append(NeverDetected(**ref.model_dump(), findings=findings))
    return result


def study_layout(
    records: Sequence[RunRecord], *, stats: verdict.StudyStats | None = None,
) -> simulate.Layout:
    """Saved-set order, scored held-out model identities, and each core's twins."""
    if not records:
        raise ValueError("study_layout needs pilot runs")
    if stats is None:
        stats = verdict.study_stats([record.study_run for record in records])
    entries = records[0].saved_set.packages
    counts = {entry.package_id: 0 for entry in entries}
    for ref in stats.defect_ids:
        counts[ref.package_id] += 1
    package_counts = tuple(counts[entry.package_id] for entry in entries)
    units = [
        (counts[entry.package_id], *(
            counts[twin.package_id] for twin in entries if twin.twin_of == entry.package_id
        )) for entry in entries if counts[entry.package_id] and entry.twin_of is None
    ]
    if not units or any(unit != units[0] for unit in units):
        raise ValueError("saved set growth_unit must have one consistent core case and its twins")
    return simulate.Layout(package_counts, units[0])


def layout_inputs(
    records: Sequence[RunRecord], stats: verdict.StudyStats,
    rates: Mapping[tuple[str, str], float],
) -> tuple[simulate.Layout, list[float], list[list[int]]]:
    """Align rates and counted repetitions with the saved set's package order."""
    if not records:
        raise ValueError("layout_inputs needs study runs")
    package_index = {name: index for index, name in enumerate(stats.package_ids)}
    entries = records[0].saved_set.packages
    ordered_rates = []
    repetitions = [[], []]
    for entry in entries:
        if entry.package_id not in package_index:
            raise ValueError(f"saved set package {entry.package_id!r} is absent from scorecards")
        index = package_index[entry.package_id]
        ordered_rates.extend(
            rates[_defect_key(ref)] for ref in stats.defect_ids
            if ref.package_id == entry.package_id
        )
        for arm in range(2):
            repetitions[arm].append(int(stats.package_runs[0, arm, 0, index]))
    return study_layout(records, stats=stats), ordered_rates, repetitions


def project_wall_clock(
    off_times: Mapping[str, float | None], *, on_ratio: float, jobs: int,
    repetitions: int, growth: int, growth_packages: Sequence[str] = (),
) -> ProjectedWallClock:
    """List-schedule in set order; added packages use committed cores/twins' mean."""
    for name, value, minimum in (("jobs", jobs, 1), ("repetitions", repetitions, 1),
                                  ("growth", growth, 0)):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer at least {minimum}")
    if not math.isfinite(on_ratio) or on_ratio < 0:
        raise ValueError("on_ratio must be finite and nonnegative")
    unknown = [name for name, value in off_times.items() if value is None]
    if any(value is not None and (not math.isfinite(value) or value < 0)
           for value in off_times.values()):
        raise ValueError("off_times must be finite and nonnegative or None")
    if growth and not growth_packages:
        raise ValueError("growth_packages must name the committed core cases and twins")
    for name in growth_packages:
        if name not in off_times:
            raise ValueError(f"growth package {name!r} has no pilot time")
    off = on = study = None
    if off_times and not unknown:
        times = list(off_times.values())
        if growth:
            growth_mean = _mean([off_times[name] for name in growth_packages])
            times.extend([growth_mean] * growth)
        slots = [0.0] * min(jobs, len(times))
        for seconds in times:
            heapq.heapreplace(slots, slots[0] + seconds)
        off = max(slots)
        on = off * on_ratio
        study = repetitions * (off + on)
    return ProjectedWallClock(
        off_run_s=off, on_run_s=on, study_s=study, smoke_ratio=on_ratio,
        smoke_off_s=None, smoke_on_s=None, mean_tokens_per_minute=None,
        unknown_packages=unknown,
    )


def check_smoke_count(smoke: Sequence[object] | None) -> None:
    """One count refusal for the command's paths and measure's loaded views."""
    if smoke is None or len(smoke) != 2:
        raise ValueError("--smoke must be given exactly twice, once for each arm")


def _validate_records(records: Sequence[RunRecord], smoke: Sequence[RunRecord]) -> None:
    if not records:
        raise ValueError(f"pilot needs {settings.PANE_STUDY} off-arm runs")
    first = records[0].provenance
    for record in records:
        provenance = record.provenance
        if record.study_key[0] != settings.PANE_STUDY:
            raise ValueError(f"{record.folder}: study must be {settings.PANE_STUDY}")
        if provenance.arm != "off":
            raise ValueError(f"{record.folder}: arm must be off")
        # compare checks must-match fields within each study key. Only these
        # key fields can differ across its validated groups.
        for index, name in ((1, "provider"), (2, "model")):
            if record.study_key[index] != records[0].study_key[index]:
                raise ValueError(f"{record.folder}: {name} differs from the pilot")
        if not record.study_run.scorecard.per_package:
            raise ValueError(f"{record.folder}: unscored run")
        for entry in record.saved_set.packages:
            sets.key_path(entry, None)
    if len({record.provenance.rep for record in records}) < 2:
        raise ValueError("co-movement needs at least two runs of a package")
    check_smoke_count(smoke)
    if {record.provenance.arm for record in smoke} != {"off", "on"}:
        names = ", ".join(str(record.folder) for record in smoke)
        raise ValueError(f"{names}: smoke arm must include one off and one on")
    for record in smoke:
        for index, name in enumerate(("study (lever)", "provider", "model")):
            if record.study_key[index] != records[0].study_key[index]:
                raise ValueError(f"{record.folder}: smoke {name} differs from the pilot")
        # The smoke set is deliberately distinct, so compare cannot check these
        # two must-match fields against the pilot in either loader call.
        for name in ("effort", "commit"):
            if getattr(record.provenance, name) != getattr(first, name):
                raise ValueError(f"{record.folder}: smoke {name} differs from the pilot")
        for pilot_record in records:
            available = {entry.package_id: entry for entry in pilot_record.saved_set.packages}
            for entry in record.saved_set.packages:
                if entry.package_id not in available or entry != available[entry.package_id]:
                    raise ValueError(f"{record.folder}: saved set package {entry.package_id} "
                                     "is not held by every pilot saved set")
        card = record.study_run.scorecard
        scores = {score.package_id: score for score in card.per_package}
        for entry in record.saved_set.packages:
            if entry.package_id not in scores:
                raise ValueError(f"{record.folder}: smoke package {entry.package_id} "
                                 "has no kept attempt")
            if scores[entry.package_id].run_status.kind not in ("completed", "behavioural"):
                raise ValueError(f"{record.folder}: smoke package {entry.package_id} run_status "
                                 "has no kept attempt")


def _mean(values):
    return sum(values) / len(values) if values else None


def _pilot_run(record: RunRecord, relative_to: Path) -> PilotRun:
    provenance = record.provenance
    return PilotRun(folder=_relative_run(record, relative_to), arm=provenance.arm,
                    repetition=provenance.rep, started_at=provenance.started_at.isoformat(),
                    commit=provenance.commit)


def _simulated_rates(row: simulate.SizeResult) -> SimulatedRates:
    return SimulatedRates(**{name: getattr(row, name) for name in SimulatedRates.model_fields})


def measure(
    records: Sequence[RunRecord], smoke: Sequence[RunRecord], *, relative_to: Path,
    cap: int = 10, seed: int | None = None, jobs: int = 1,
) -> PilotMeasurement:
    """Measure only the pilot, size its layout, and use smoke solely for timing."""
    _validate_records(records, smoke)
    relative_to = Path(relative_to)
    data = verdict.study_stats([record.study_run for record in records])
    counts = defect_counts(data, "off")
    fit = beta_fit(counts)
    movement = comovement(data, fit)
    if fit.mu is None or movement.used is None:
        raise ValueError("pilot held-out model defects have no counted runs")
    # The individual summaries retain package-run false alarms; all their counting
    # and detection rules still live in verdict.study_stats.
    per_run = [verdict.study_stats([record.study_run]) for record in records]
    alarms = []
    for summary in per_run:
        selected = summary.package_runs[0, 0, 0] > 0
        alarms.extend(int(value) for value in summary.false_alarms[0, 0, 0, selected])
    alarm_fit = false_alarm_fit(alarms)
    main_runs = int(np.sum(data.package_runs[0, 0, 0]))
    all_runs = int(np.sum(data.package_runs[0, 0, 1]))
    stops = Count(x=all_runs - main_runs, n=all_runs)
    code = [DefectCount(**ref.model_dump(), x=int(data.code_detections[0, 0, i]),
                        n=int(data.code_runs[0, 0, i])) for i, ref in enumerate(data.code_ids)]
    package_index = {name: i for i, name in enumerate(data.package_ids)}
    clearances = [DefectCount(
        **ref.model_dump(), x=int(data.clears[0, 0, i]),
        n=int(data.package_runs[0, 0, 1, package_index[ref.package_id]]),
    ) for i, ref in enumerate(data.clear_ids) if data.clear_held_out[i]]
    costs, times, tokens_per_minute, unknown_cost = [], [], [], []
    package_times = {entry.package_id: [] for entry in records[0].saved_set.packages}
    for record, summary in zip(records, per_run, strict=True):
        selected = {name for i, name in enumerate(summary.package_ids)
                    if summary.package_runs[0, 0, 0, i]}
        for score in record.study_run.scorecard.per_package:
            if score.package_id not in selected:
                continue
            if score.cost.amount is None:
                unknown_cost.append(PackageRun(run=_relative_run(record, relative_to),
                                               package_id=score.package_id))
            else:
                costs.append(score.cost.amount)
            if score.wall_clock_s is not None:
                times.append(score.wall_clock_s)
                package_times[score.package_id].append(score.wall_clock_s)
                if (score.wall_clock_s > 0 and score.usage is not None
                        and score.usage.input_tokens is not None
                        and score.usage.output_tokens is not None):
                    tokens_per_minute.append(
                        60 * (score.usage.input_tokens + score.usage.output_tokens)
                        / score.wall_clock_s,
                    )
    layout = study_layout(records, stats=data)
    def rate_draw(rng, shape):
        if fit.distribution == "beta":
            return rng.beta(fit.a, fit.b, size=shape)
        if fit.distribution == "polarised":
            return rng.binomial(1, fit.mu, size=shape)
        return np.full(shape, fit.mu)

    code_rates = tuple(item.x / item.n for item in code if item.n)
    clear_rates = tuple(item.x / item.n for item in clearances if item.n)
    scenario = simulate.Scenario(
        "pilot", rate_draw, movement.used, alarm_fit.mean or 0, alarm_fit.k,
        stop_rate=stops.x / stops.n if stops.n else 0,
        clearance_count=len(clear_rates), clearance_rate=clear_rates or 0,
        code_count=len(code_rates), code_rate=code_rates or 0,
        growth_clearance_rate=(sum(item.x for item in clearances)
                               / sum(item.n for item in clearances)
                               if any(item.n for item in clearances) else 0),
    )
    if seed is None:
        seed = secrets.randbits(63)
    sims = simulate.DEFAULT_SIMS
    searched = simulate.search(scenario, seed=seed, sims=sims, cap=cap, layout=layout)
    if not searched.tried:
        raise ValueError("size search tried no size")
    chosen = searched.result or searched.tried[-1]
    mean_cost = _mean(costs)
    deciding = ["recall", "false_alarms", "code_guard"]
    if searched.cleared_guard_decides:
        deciding.append("cleared_guard")
    result = SizingResult(
        reps=chosen.reps, packages=chosen.packages, held_out_model_defects=chosen.defects,
        alpha=chosen.alpha, deciding_rules=deciding,
        cleared_guard_decides=searched.cleared_guard_decides,
        simulated=_simulated_rates(chosen), stress_case=searched.stress_case,
        estimated_study_cost=(2 * chosen.reps * chosen.packages * mean_cost
                              if mean_cost is not None else None),
        state=searched.state, cleared_guard_reason=searched.cleared_guard_reason,
    )
    off_times = {name: _mean(values) for name, values in package_times.items()}
    entries = records[0].saved_set.packages
    cores = {data.package_ids[int(p)] for p in data.defect_packages}
    growth_ids = cores | {entry.package_id for entry in entries if entry.twin_of in cores}
    smoke_totals = {}
    for record in smoke:
        values = [score.wall_clock_s for score in record.study_run.scorecard.per_package]
        smoke_totals[record.provenance.arm] = (
            sum(values) if values and all(value is not None for value in values) else None
        )
    smoke_off, smoke_on = smoke_totals["off"], smoke_totals["on"]
    ratio = smoke_on / smoke_off if smoke_off and smoke_on is not None else None
    if ratio is None:
        projection = ProjectedWallClock(
            off_run_s=None, on_run_s=None, study_s=None, smoke_ratio=None,
            smoke_off_s=smoke_off, smoke_on_s=smoke_on, mean_tokens_per_minute=None,
            unknown_packages=[name for name, value in off_times.items() if value is None],
        )
    else:
        projection = project_wall_clock(
            off_times, on_ratio=ratio, jobs=jobs, repetitions=chosen.reps,
            growth=chosen.growth_units * len(layout.growth_unit),
            growth_packages=[entry.package_id for entry in entries
                             if entry.package_id in growth_ids],
        )
        projection.smoke_off_s, projection.smoke_on_s = smoke_off, smoke_on
    projection.mean_tokens_per_minute = _mean(tokens_per_minute)
    _, excluded_keys, dropped_keys = _count_groups(counts)
    dropped = [ref for ref in data.defect_ids if _defect_key(ref) in dropped_keys]
    excluded = [ref for ref in data.defect_ids if _defect_key(ref) in excluded_keys]
    relative_records = [replace(
        record, study_run=replace(record.study_run, run=_relative_run(record, relative_to)),
    ) for record in records]
    named_never = never_detected(relative_records, data)
    first = records[0].provenance
    measurement = PilotMeasurement(
        identity=PilotIdentity(
            pilot_schema=PILOT_SCHEMA, study=first.lever, provider=first.provider,
            model=first.model, commit=first.commit, set_digest=first.set_digest,
            scoring_rules_version=records[0].study_run.scorecard.scoring_rules_version,
        ),
        pilot_runs=[_pilot_run(record, relative_to) for record in records],
        smoke_runs=[_pilot_run(record, relative_to) for record in smoke],
        measured=Measured(
            defect_counts=[DefectCount(**ref.model_dump(), x=counts[name][0], n=counts[name][1])
                           for ref in data.defect_ids
                           for name in [_defect_key(ref)]],
            dropped_defects=[DefectRef(**ref.model_dump()) for ref in dropped],
            dropped_defect_count=len(dropped),
            variance_excluded_defects=[DefectRef(**ref.model_dump()) for ref in excluded],
            variance_excluded_count=len(excluded), beta_fit=fit, comovement=movement,
            code_defects=code, stops=stops, clearances=clearances, false_alarm_fit=alarm_fit,
            cost_time=CostTime(mean_cost=mean_cost, mean_wall_clock_s=_mean(times),
                               unknown_cost_runs=unknown_cost,
                               unknown_cost_count=len(unknown_cost)),
            never_detected=named_never,
        ),
        sizing=Sizing(
            cap=cap, floor=verdict.FLOOR, seed=seed, sims=sims, ladder=list(simulate.ALPHA_LADDER),
            tried=[SizeTried(reps=row.reps, packages=row.packages,
                             held_out_model_defects=row.defects, growth_units=row.growth_units,
                             alpha=row.alpha, cleared_guard_decides=False,
                             simulated=_simulated_rates(row)) for row in searched.tried],
            pilot_packages=sorted(off_times), growth_units=chosen.growth_units, jobs=jobs,
            projected_wall_clock=projection, result=result,
        ), sizing_digest="",
    )
    measurement.sizing_digest = sizing_digest(measurement)
    return measurement


def refuse_existing(path: Path | str) -> None:
    """Refuse overwriting the one measurement before loading or before writing."""
    path = Path(path)
    if path.exists():
        raise ValueError(f"{path} exists: one study has one measurement; "
                         "delete the unapproved file to size again")


def write_measurement(path: Path | str, measurement: PilotMeasurement) -> None:
    """Write a fresh unapproved measurement with the digest of its computed blocks."""
    path = Path(path)
    refuse_existing(path)
    measurement = measurement.model_copy(update={"approval": Approval()})
    measurement.sizing_digest = sizing_digest(measurement)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, (measurement.model_dump_json(indent=2) + "\n").encode("utf-8"))
