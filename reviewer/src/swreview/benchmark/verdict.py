"""The pane study's rule, shared by compare, the simulator and the pilot (T227).

Counts keep a leading study axis. Rates, drops and guards are computed across that
axis together; intervals use the single package-level implementation in stats.
No provider, key, session or event stream is read here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, field_validator

from swreview.benchmark import origins
from swreview.benchmark import stats as statistics
from swreview.findings import ReviewModel

if TYPE_CHECKING:
    from swreview.benchmark.scorecard import PackageScore, Scorecard

FLOOR = 34
LOSS_BOUND = 0.10
NOISE_FLOOR_GRID = tuple(index / 2 for index in range(1, 101))

RECALL_LOSS = "RECALL LOSS"
FALSE_ALARM_RISE = "FALSE-ALARM RISE"
CODE_DEFECT_LOST = "CODE DEFECT LOST"
CLEARED = "CLEARED"
BELOW_FLOOR = "BELOW FLOOR"
RECALL_NOT_COMPUTABLE = "RECALL NOT COMPUTABLE"
LOWER_END_AT_OR_BELOW_MINUS_TEN_POINTS = "LOWER END AT OR BELOW -10 POINTS"

Verdict = Literal["quality loss", "no 10-point loss", "inconclusive"]
FIGURES = ("main", "sensitivity")
ARMS = ("off", "on")


class DefectRef(ReviewModel):
    package_id: str
    defect_id: str


class DefectRuns(DefectRef):
    runs: list[str]


class GuardNote(DefectRef):
    reason: str


class SometimesDefect(GuardNote):
    reason: str = "the off arm detected it only sometimes"


class PairedInterval(ReviewModel):
    estimate: float | None
    lower: float | None
    upper: float | None
    alpha: float = Field(gt=0, le=0.5)
    df: int
    packages: int = Field(ge=0)
    computable: bool
    loss: bool


class FigureStats(ReviewModel):
    retained_defects: int = Field(ge=0)
    retained_packages: int = Field(ge=0)
    dropped_defects: list[DefectRef]
    dropped_packages: list[str]
    recall: PairedInterval
    false_alarms: PairedInterval


class Figures(ReviewModel):
    main: FigureStats
    sensitivity: FigureStats


class CodeGuard(ReviewModel):
    lost: list[DefectRuns]
    off_only_sometimes: list[SometimesDefect]
    skipped: list[GuardNote]


class ClearedGuard(ReviewModel):
    decides: bool
    named: list[DefectRuns]


class StudyVerdict(ReviewModel):
    verdict: Verdict
    reasons: list[str]
    figures: Figures
    code_guard: CodeGuard
    cleared_guard: ClearedGuard


class Repetitions(ReviewModel):
    off: int = Field(ge=0)
    on: int = Field(ge=0)


class SimulatedRates(ReviewModel):
    power_proportional: float
    power_room: float
    identical_loss: float
    identical_loss_upper: float
    no_loss_at_drop: float
    no_loss_at_drop_upper: float


class StudyApproval(ReviewModel):
    file_sha256: str
    approved_at: str
    alpha: float = Field(gt=0, le=0.5)
    held_out_model_defects: int = Field(ge=0)
    reps: int = Field(ge=1)
    cleared_guard_decides: bool
    seed: int
    simulated: SimulatedRates


def above_noise_floor(points: float) -> str:
    """Spell a lower bound on the noise floor in points."""
    return f"above {points:g} points"


def validate_noise_floor_points(value: float | str | None) -> None:
    """Accept only results on the printed grid, its lower bounds, or no result."""
    if value is None:
        return
    if isinstance(value, str):
        if value == "not attainable" or value in {
            above_noise_floor(points) for points in NOISE_FLOOR_GRID
        }:
            return
    elif not isinstance(value, bool) and value in NOISE_FLOOR_GRID:
        return
    raise ValueError("must be a grid number, an above-grid value, not attainable, or None")


class NoiseFloor(ReviewModel):
    state: Literal["computed", "not_computed", "stale"]
    points: float | str | None
    seed: int | None
    numpy: str | None

    @field_validator("points")
    @classmethod
    def _grid_points(cls, value: float | str | None) -> float | str | None:
        validate_noise_floor_points(value)
        return value


class UntestedSetting(ReviewModel):
    setting: str
    reason: str


class ShownMeasure(ReviewModel):
    name: str
    off: float | None
    on: float | None
    estimate: float | None
    lower: float | None
    upper: float | None
    level: float = 0.95
    excludes_zero: bool


class PaneStudy(ReviewModel):
    """The strict, data-only ledger block from verdict.md section 8 (schema 1.1)."""

    study: str
    provider: str
    model: str
    commit: str
    slice: Literal["committed", "private"]
    run_dirs: list[str]
    reps: Repetitions
    verdict: Verdict | None
    reasons: list[str]
    refusal: str | None
    approval: StudyApproval | None
    figures: Figures | None
    code_guard: CodeGuard | None
    cleared_guard: ClearedGuard | None
    noise_floor: NoiseFloor
    arms_differed_in: list[str]
    inert: list[str]
    untested_between_turns: list[UntestedSetting]
    shown: list[ShownMeasure]


@dataclass(frozen=True)
class StudyRun:
    run: str
    arm: Literal["off", "on"]
    scorecard: Scorecard

    def __post_init__(self) -> None:
        if self.arm not in ARMS:
            raise ValueError("arm must be off or on")


@dataclass(frozen=True)
class VerdictRules:
    alpha: float
    cleared_guard_decides: bool
    floor: int = FLOOR

    def __post_init__(self) -> None:
        if not math.isfinite(self.alpha) or not 0 < self.alpha <= 0.5:
            raise ValueError("alpha must be inside (0, 0.5]")
        if isinstance(self.floor, bool) or not isinstance(self.floor, int) or self.floor < 1:
            raise ValueError("floor must be a positive integer")


@dataclass(frozen=True)
class PackageRunDetections:
    """Main-figure observations that aggregate detection counts cannot recover.

    ``detected`` is boolean with shape (studies, arms, runs, held-out model
    defects); ``counted`` is boolean with shape (studies, arms, runs, packages).
    Arm order is off, on; defects and packages follow the enclosing StudyStats'
    layouts. Runs follow each arm's input order in study_stats, including runs
    with no counted package. The run axis is padded to the larger arm's length.
    Padded, missing and uncounted package slots have false counted masks and
    false detections. Completed runs, including bound-reached, count here.
    """

    detected: NDArray[np.bool_]
    counted: NDArray[np.bool_]


@dataclass(frozen=True)
class StudyStats:
    """Sufficient statistics, with shared layouts and optional compare-path names.

    Detection/count arrays have shape (studies, arms, figures, defects), and
    false-alarm/package counts (studies, arms, figures, packages). Arm order is
    off, on; figure order main, sensitivity. Code counts use only main, with
    shape (studies, arms, code defects); clears use completed and stopped runs,
    with shape (studies, arms, all known defects). Metadata has no study axis.
    Optional package_run_detections retains the main figure's observations and
    counted masks; see PackageRunDetections for its shapes and ordering.
    """

    detections: NDArray[np.int64]
    counted_runs: NDArray[np.int64]
    defect_packages: NDArray[np.int64]
    false_alarms: NDArray[np.int64]
    package_runs: NDArray[np.int64]
    code_detections: NDArray[np.int64]
    code_runs: NDArray[np.int64]
    clears: NDArray[np.int64]
    clear_held_out: NDArray[np.bool_]
    defect_ids: tuple[DefectRef, ...] = ()
    package_ids: tuple[str, ...] = ()
    code_ids: tuple[DefectRef, ...] = ()
    clear_ids: tuple[DefectRef, ...] = ()
    code_missed_runs: dict[tuple[int, int], tuple[str, ...]] = field(default_factory=dict)
    clear_runs: dict[tuple[int, int], tuple[str, ...]] = field(default_factory=dict)
    package_run_detections: PackageRunDetections | None = None


def detected_ids(score: PackageScore) -> set[str]:
    """Credited and flagged defects, shared by deciding and shown measures."""
    return set(score.matched_defect_ids) | set(score.flagged_defect_ids)


def study_stats(runs: Sequence[StudyRun]) -> StudyStats:
    """Read one study's scorecards; a pilot containing only off runs is valid.

    Defect identities include the package: ids are only unique within a key.
    The package universe includes unscored packages, clean twins and anchors.
    """
    package_names: set[str] = set()
    items: dict[tuple[str, str], tuple[str | None, str]] = {}
    for run in runs:
        for score in (*run.scorecard.per_package, *run.scorecard.unscored_packages):
            package_names.add(score.package_id)
            for item in score.graded_items:
                if item.kind == "known_defect":
                    items[score.package_id, item.id] = (item.producer, item.tag)
    packages = tuple(sorted(package_names))
    package_index = {name: index for index, name in enumerate(packages)}
    known = sorted(items)
    held_out = [key for key in known if items[key] == ("model", "held_out")]
    code = [key for key in known if items[key][0] == "code"]
    held_index = {key: index for index, key in enumerate(held_out)}
    code_index = {key: index for index, key in enumerate(code)}
    known_index = {key: index for index, key in enumerate(known)}
    detections = np.zeros((1, 2, 2, len(held_out)), dtype=np.int64)
    counted = np.zeros_like(detections)
    false_alarms = np.zeros((1, 2, 2, len(packages)), dtype=np.int64)
    package_runs = np.zeros_like(false_alarms)
    code_detections = np.zeros((1, 2, len(code)), dtype=np.int64)
    code_runs = np.zeros_like(code_detections)
    clears = np.zeros((1, 2, len(known)), dtype=np.int64)
    code_missed: dict[tuple[int, int], tuple[str, ...]] = {}
    cleared_runs: dict[tuple[int, int], tuple[str, ...]] = {}
    arm_runs = [sum(run.arm == arm for run in runs) for arm in ARMS]
    run_detections = np.zeros((1, 2, max(arm_runs), len(held_out)), dtype=bool)
    run_counted = np.zeros((1, 2, max(arm_runs), len(packages)), dtype=bool)
    arm_positions = [0, 0]

    for run in runs:
        arm = ARMS.index(run.arm)
        run_index = arm_positions[arm]
        arm_positions[arm] += 1
        unscored = {row.package_id for row in run.scorecard.unscored_packages}
        for score in run.scorecard.per_package:
            if score.package_id in unscored:
                continue
            completed = score.run_status.kind == "completed"
            if not completed and score.run_status.kind != "behavioural":
                continue
            package = package_index[score.package_id]
            detected = detected_ids(score)
            false_alarm_count = len(origins.deciding_false_alarm_ids(score))
            for figure in (0, 1) if completed else (1,):
                package_runs[0, arm, figure, package] += 1
                false_alarms[0, arm, figure, package] += false_alarm_count
                if figure == 0:
                    run_counted[0, arm, run_index, package] = True
                for key, index in held_index.items():
                    if key[0] == score.package_id:
                        counted[0, arm, figure, index] += 1
                        detections[0, arm, figure, index] += int(completed and key[1] in detected)
                        if figure == 0:
                            run_detections[0, arm, run_index, index] = key[1] in detected
            for key, index in code_index.items():
                if completed and key[0] == score.package_id:
                    code_runs[0, arm, index] += 1
                    code_detections[0, arm, index] += int(key[1] in detected)
                    if arm == 1 and key[1] not in detected:
                        code_missed[0, index] = (*code_missed.get((0, index), ()), run.run)
            for defect in score.cleared_defect_ids:
                key = (score.package_id, defect)
                if key in known_index:
                    index = known_index[key]
                    clears[0, arm, index] += 1
                    if arm == 1:
                        cleared_runs[0, index] = (*cleared_runs.get((0, index), ()), run.run)

    def refs(keys: Sequence[tuple[str, str]]) -> tuple[DefectRef, ...]:
        return tuple(DefectRef(package_id=package, defect_id=defect) for package, defect in keys)

    return StudyStats(
        detections=detections,
        counted_runs=counted,
        defect_packages=np.array([package_index[key[0]] for key in held_out], dtype=np.int64),
        false_alarms=false_alarms,
        package_runs=package_runs,
        code_detections=code_detections,
        code_runs=code_runs,
        clears=clears,
        clear_held_out=np.array([items[key][1] == "held_out" for key in known], dtype=bool),
        defect_ids=refs(held_out),
        package_ids=packages,
        code_ids=refs(code),
        clear_ids=refs(known),
        code_missed_runs=code_missed,
        clear_runs=cleared_runs,
        package_run_detections=PackageRunDetections(run_detections, run_counted),
    )


def _paired(
    intervals: statistics.BatchInterval,
    loss: NDArray[np.bool_],
    study: int,
    figure: int,
    alpha: float,
) -> PairedInterval:
    def optional(values):
        value = float(values[study, figure])
        return None if math.isnan(value) else value

    return PairedInterval(
        estimate=optional(intervals.estimate),
        lower=optional(intervals.lower),
        upper=optional(intervals.upper),
        df=int(intervals.df[study, figure]),
        packages=int(intervals.packages[study, figure]),
        computable=bool(intervals.computable[study, figure]),
        alpha=alpha,
        loss=bool(loss[study, figure]),
    )


@dataclass(frozen=True)
class PreparedJudge:
    """Package moments and guards shared across every tested alpha level."""

    stats: StudyStats
    retained: NDArray[np.bool_]
    retained_packages: NDArray[np.bool_]
    retained_defects: NDArray[np.int64]
    recall: statistics.PackageMoments
    false_alarms: statistics.PackageMoments
    code_retained: NDArray[np.bool_]
    code_lost: NDArray[np.bool_]
    sometimes: NDArray[np.bool_]
    cleared: NDArray[np.bool_]


@dataclass(frozen=True)
class JudgeCounts:
    """The same rule's numerical outcomes without allocating named reports."""

    quality_loss: NDArray[np.bool_]
    no_loss: NDArray[np.bool_]
    below_floor: NDArray[np.bool_]
    recall_computable: NDArray[np.bool_]
    recall_loss: NDArray[np.bool_]
    false_alarm_loss: NDArray[np.bool_]
    recall: statistics.BatchInterval
    false_alarms: statistics.BatchInterval

    @property
    def main_recall_loss(self) -> NDArray[np.bool_]:
        return self.recall_loss[:, 0]


def _group_packages(values: NDArray, packages: NDArray, count: int) -> NDArray[np.float64]:
    """Sum each package's defects without constructing a dense one-hot matrix."""
    # Existing reports may contain more than the simulator's two defects per
    # package. Retain their historical addition order in cancellation cases.
    if packages.size and np.max(np.bincount(packages, minlength=count)) > 2:
        grouping = (packages[:, None] == np.arange(count)).astype(float)
        return np.einsum("sfd,dk->sfk", values, grouping)
    grouped = np.zeros((*values.shape[:-1], count), dtype=float)
    if packages.size:
        order = np.argsort(packages, kind="stable")
        unique, starts = np.unique(packages[order], return_index=True)
        grouped[..., unique] = np.add.reduceat(values[..., order], starts, axis=-1)
    return grouped


def _equal_counted_package_means(
    counts: NDArray[np.int64], runs: NDArray[np.int64], retained: NDArray[np.bool_],
    packages: NDArray[np.int64], weights: NDArray[np.float64],
) -> NDArray[np.bool_]:
    """Compare rational package means exactly, before floating rate subtraction.

    Scale counts by the common denominator of the counted runs, then compare
    integer package sums by cross multiplication. Python integers handle unusually
    large inputs; ordinary studies (at most ten runs) stay in vectorised int64.
    This changes only the exact zero-variance mask, preserving every other bit of
    the interval arithmetic used for the simulator's pinned outputs.
    """
    denominator = math.lcm(*(int(n) for n in np.unique(runs) if n > 0))
    # Bound the scaled sum and its subsequent cross product before choosing a
    # dtype. Using Python ints for the bound prevents overflow in the check itself.
    bound = denominator * int(np.max(np.abs(counts), initial=0)) * max(1, packages.size)
    bound *= max(1, int(np.max(weights, initial=0)))
    dtype = object if max(denominator, bound) > np.iinfo(np.int64).max else np.int64
    positive_runs = np.maximum(runs, 1).astype(dtype)
    scaled = counts.astype(dtype) * (denominator // positive_runs)
    differences = (scaled[:, 1] - scaled[:, 0]) * retained
    sums = np.zeros(weights.shape, dtype=dtype)
    if packages.size:
        order = np.argsort(packages, kind="stable")
        unique, starts = np.unique(packages[order], return_index=True)
        sums[..., unique] = np.add.reduceat(differences[..., order], starts, axis=-1)
    kept = weights > 0
    if not weights.shape[-1]:
        return np.ones(weights.shape[:-1], dtype=bool)
    integer_weights = weights.astype(dtype)
    first = np.argmax(kept, axis=-1)[..., None]
    first_sum = np.take_along_axis(sums, first, axis=-1)
    first_weight = np.take_along_axis(integer_weights, first, axis=-1)
    return np.all(~kept | (sums * first_weight == first_sum * integer_weights), axis=-1)


def prepare_judge(stats: StudyStats) -> PreparedJudge:
    """Compute alpha-independent package moments and guard masks together."""
    retained = np.all(stats.counted_runs > 0, axis=1)
    retained_packages = np.all(stats.package_runs > 0, axis=1)
    rates = np.divide(
        stats.detections,
        stats.counted_runs,
        out=np.zeros_like(stats.detections, dtype=float),
        where=stats.counted_runs > 0,
    )
    alarm_rates = np.divide(
        stats.false_alarms,
        stats.package_runs,
        out=np.zeros_like(stats.false_alarms, dtype=float),
        where=stats.package_runs > 0,
    )
    package_count = stats.package_runs.shape[-1]
    recall_sums = _group_packages(
        (rates[:, 1] - rates[:, 0]) * retained, stats.defect_packages, package_count,
    )
    recall_weights = _group_packages(retained.astype(float), stats.defect_packages, package_count)
    alarm_sums = (alarm_rates[:, 1] - alarm_rates[:, 0]) * retained_packages
    recall_moments = statistics.prepare_package_intervals(recall_sums, recall_weights)
    alarm_weights = retained_packages.astype(float)
    alarm_moments = statistics.prepare_package_intervals(alarm_sums, alarm_weights)
    recall_equal = _equal_counted_package_means(
        stats.detections, stats.counted_runs, retained, stats.defect_packages, recall_weights,
    )
    alarm_equal = _equal_counted_package_means(
        stats.false_alarms, stats.package_runs, retained_packages,
        np.arange(package_count), alarm_weights,
    )
    code_retained = np.all(stats.code_runs > 0, axis=1)
    off_complete = stats.code_detections[:, 0] == stats.code_runs[:, 0]
    code_lost = code_retained & off_complete & (stats.code_detections[:, 1] < stats.code_runs[:, 1])
    sometimes = code_retained & (stats.code_detections[:, 0] > 0) & ~off_complete
    cleared = (stats.clears[:, 1] > 0) & (stats.clears[:, 0] == 0)
    return PreparedJudge(
        stats=stats,
        retained=retained,
        retained_packages=retained_packages,
        retained_defects=np.count_nonzero(retained, axis=-1),
        recall=replace(recall_moments, computable=recall_moments.computable & ~recall_equal),
        false_alarms=replace(alarm_moments, computable=alarm_moments.computable & ~alarm_equal),
        code_retained=code_retained,
        code_lost=code_lost,
        sometimes=sometimes,
        cleared=cleared,
    )


def _judge_counts(prepared: PreparedJudge, rules: VerdictRules) -> JudgeCounts:
    recall = statistics.package_intervals_from_moments(prepared.recall, rules.alpha)
    alarms = statistics.package_intervals_from_moments(prepared.false_alarms, rules.alpha)
    recall_loss = recall.computable & (recall.upper < 0)
    alarm_loss = alarms.computable & (alarms.lower > 0)
    quality_loss = np.any(recall_loss | alarm_loss, axis=1) | np.any(prepared.code_lost, axis=1)
    if rules.cleared_guard_decides:
        quality_loss |= np.any(prepared.cleared & prepared.stats.clear_held_out, axis=1)
    below_floor = np.any(prepared.retained_defects < rules.floor, axis=1)
    recall_computable = np.all(recall.computable, axis=1)
    no_loss = (
        ~quality_loss & ~below_floor & recall_computable
        & np.all(recall.lower > -LOSS_BOUND, axis=1)
    )
    return JudgeCounts(
        quality_loss=quality_loss,
        no_loss=no_loss,
        below_floor=below_floor,
        recall_computable=recall_computable,
        recall_loss=recall_loss,
        false_alarm_loss=alarm_loss,
        recall=recall,
        false_alarms=alarms,
    )

def _reference(ids: tuple[DefectRef, ...], index: int) -> DefectRef:
    # Simulated studies need no report names. Their labels never enter a ledger.
    return ids[index] if ids else DefectRef(package_id="simulated", defect_id=str(index))


def _label(reference: DefectRef) -> str:
    return f"{reference.package_id}/{reference.defect_id}"


def judge(
    stats: StudyStats | PreparedJudge, rules: VerdictRules, *, named: bool = True,
) -> list[StudyVerdict] | JudgeCounts:
    """Apply every loss before floor, computability and the strict -10-point bound.

    Both modes use the same batched intervals and decision masks. Named reports
    allocate per-study models only when requested; a prepared study can be reused
    at another alpha without recomputing package moments or guards.
    """
    prepared = stats if isinstance(stats, PreparedJudge) else prepare_judge(stats)
    judged = _judge_counts(prepared, rules)
    if not named:
        return judged
    stats = prepared.stats
    retained, retained_packages = prepared.retained, prepared.retained_packages
    code_retained, code_lost = prepared.code_retained, prepared.code_lost
    sometimes, cleared = prepared.sometimes, prepared.cleared
    results: list[StudyVerdict] = []

    for study in range(stats.detections.shape[0]):
        reasons: list[str] = []
        figures: list[FigureStats] = []
        for figure, name in enumerate(FIGURES):
            recall = _paired(judged.recall, judged.recall_loss, study, figure, rules.alpha)
            alarms = _paired(
                judged.false_alarms, judged.false_alarm_loss, study, figure, rules.alpha,
            )
            figures.append(
                FigureStats(
                    retained_defects=int(prepared.retained_defects[study, figure]),
                    retained_packages=int(np.count_nonzero(retained_packages[study, figure])),
                    dropped_defects=[
                        _reference(stats.defect_ids, int(i))
                        for i in np.flatnonzero(~retained[study, figure])
                    ],
                    dropped_packages=[
                        stats.package_ids[i] if stats.package_ids else str(i)
                        for i in np.flatnonzero(~retained_packages[study, figure])
                    ],
                    recall=recall,
                    false_alarms=alarms,
                )
            )
            if recall.loss:
                reasons.append(f"{RECALL_LOSS}: {name}")
            if alarms.loss:
                reasons.append(f"{FALSE_ALARM_RISE}: {name}")

        lost = [
            DefectRuns(
                **_reference(stats.code_ids, int(i)).model_dump(),
                runs=list(stats.code_missed_runs.get((study, int(i)), ())),
            )
            for i in np.flatnonzero(code_lost[study])
        ]
        for defect in lost:
            reasons.append(
                f"{CODE_DEFECT_LOST}: main {_label(defect)}; runs {', '.join(defect.runs)}"
            )
        code_guard = CodeGuard(
            lost=lost,
            off_only_sometimes=[
                SometimesDefect(
                    **_reference(stats.code_ids, int(i)).model_dump(),
                )
                for i in np.flatnonzero(sometimes[study])
            ],
            skipped=[
                GuardNote(
                    **_reference(stats.code_ids, int(i)).model_dump(),
                    reason="no counted run in at least one arm",
                )
                for i in np.flatnonzero(~code_retained[study])
            ],
        )
        named_clears = [
            DefectRuns(
                **_reference(stats.clear_ids, int(i)).model_dump(),
                runs=list(stats.clear_runs.get((study, int(i)), ())),
            )
            for i in np.flatnonzero(cleared[study])
        ]
        if rules.cleared_guard_decides:
            for i in np.flatnonzero(cleared[study] & stats.clear_held_out):
                reference = _reference(stats.clear_ids, int(i))
                runs = stats.clear_runs.get((study, int(i)), ())
                reasons.append(f"{CLEARED}: {_label(reference)}; runs {', '.join(runs)}")

        if judged.quality_loss[study]:
            outcome: Verdict = "quality loss"
        elif judged.below_floor[study]:
            outcome = "inconclusive"
            counts = []
            for name, figure in zip(FIGURES, figures, strict=True):
                drops = ", ".join(_label(ref) for ref in figure.dropped_defects) or "none"
                packages = ", ".join(figure.dropped_packages) or "none"
                counts.append(
                    f"{name} {figure.retained_defects}; dropped defects {drops}; "
                    f"dropped packages {packages}"
                )
            reasons.append(f"{BELOW_FLOOR}: floor {rules.floor}; " + "; ".join(counts))
        elif not judged.recall_computable[study]:
            outcome = "inconclusive"
            for name, figure in zip(FIGURES, figures, strict=True):
                if not figure.recall.computable:
                    why = (
                        "fewer than two retained packages"
                        if figure.recall.packages < 2
                        else "zero standard error (zero-width interval)"
                    )
                    reasons.append(f"{RECALL_NOT_COMPUTABLE}: {name}; {why}")
        else:
            for name, figure in zip(FIGURES, figures, strict=True):
                lower = figure.recall.lower
                if lower is not None and lower <= -LOSS_BOUND:
                    reasons.append(
                        f"{LOWER_END_AT_OR_BELOW_MINUS_TEN_POINTS}: {name} {lower * 100:.1f}"
                    )
            outcome = "no 10-point loss" if judged.no_loss[study] else "inconclusive"
        results.append(
            StudyVerdict(
                verdict=outcome,
                reasons=reasons,
                figures=Figures(main=figures[0], sensitivity=figures[1]),
                code_guard=code_guard,
                cleared_guard=ClearedGuard(decides=rules.cleared_guard_decides, named=named_clears),
            )
        )
    return results
