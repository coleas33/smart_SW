"""The pane study's rule, shared by compare, the simulator and the pilot (T227).

Counts keep a leading study axis. Rates, drops and guards are computed across that
axis together; intervals use the single package-level implementation in stats.
No provider, key, session or event stream is read here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from swreview.benchmark import origins
from swreview.benchmark import stats as statistics
from swreview.findings import ReviewModel

if TYPE_CHECKING:
    from swreview.benchmark.scorecard import Scorecard

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


class NoiseFloor(ReviewModel):
    state: Literal["computed", "not_computed", "stale"]
    points: float | Literal["above 50 points", "not attainable"] | None
    seed: int | None
    numpy: str | None


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
    floor: int = 34

    def __post_init__(self) -> None:
        if not math.isfinite(self.alpha) or not 0 < self.alpha <= 0.5:
            raise ValueError("alpha must be inside (0, 0.5]")
        if isinstance(self.floor, bool) or not isinstance(self.floor, int) or self.floor < 1:
            raise ValueError("floor must be a positive integer")


@dataclass(frozen=True)
class StudyStats:
    """Sufficient statistics, with shared layouts and optional compare-path names.

    Detection/count arrays have shape (studies, arms, figures, defects), and
    false-alarm/package counts (studies, arms, figures, packages). Arm order is
    off, on; figure order main, sensitivity. Code counts use only main, with
    shape (studies, arms, code defects); clears use completed and stopped runs,
    with shape (studies, arms, all known defects). Metadata has no study axis.
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


def study_stats(runs: Sequence[StudyRun]) -> StudyStats:
    """Read one study's scorecards; a pilot containing only off runs is valid.

    Defect identities include the package: ids are only unique within a key.
    The package universe includes unscored packages, clean twins and anchors.
    """
    package_names: set[str] = set()
    items: dict[tuple[str, str], tuple[str | None, str]] = {}
    for run in runs:
        package_names.update(row.package_id for row in run.scorecard.unscored_packages)
        for score in run.scorecard.per_package:
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

    for run in runs:
        arm = ARMS.index(run.arm)
        unscored = {row.package_id for row in run.scorecard.unscored_packages}
        for score in run.scorecard.per_package:
            if score.package_id in unscored:
                continue
            completed = score.run_status.kind == "completed"
            if not completed and score.run_status.kind != "behavioural":
                continue
            package = package_index[score.package_id]
            detected = set(score.matched_defect_ids) | set(score.flagged_defect_ids)
            false_alarm_count = len(origins.deciding_false_alarm_ids(score))
            for figure in (0, 1) if completed else (1,):
                package_runs[0, arm, figure, package] += 1
                false_alarms[0, arm, figure, package] += false_alarm_count
                for key, index in held_index.items():
                    if key[0] == score.package_id:
                        counted[0, arm, figure, index] += 1
                        detections[0, arm, figure, index] += int(completed and key[1] in detected)
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
    )


def _paired(sums: NDArray, weights: NDArray, alpha: float, *, recall: bool) -> PairedInterval:
    interval = statistics.package_interval(sums, weights, alpha, sides=1)
    bound = interval.upper if recall else interval.lower
    loss = interval.computable and bound is not None and (bound < 0 if recall else bound > 0)
    return PairedInterval(**vars(interval), alpha=alpha, loss=bool(loss))


def _reference(ids: tuple[DefectRef, ...], index: int) -> DefectRef:
    # Simulated studies need no report names. Their labels never enter a ledger.
    return ids[index] if ids else DefectRef(package_id="simulated", defect_id=str(index))


def _label(reference: DefectRef) -> str:
    return f"{reference.package_id}/{reference.defect_id}"


def judge(stats: StudyStats, rules: VerdictRules) -> list[StudyVerdict]:
    """Apply every loss before floor, computability and the strict -10-point bound.

    All studies use the same array path and package interval; there is no separate
    simulation rule. Only interval calls and named output construction iterate rows.
    """
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
    grouping = (stats.defect_packages[:, None] == np.arange(package_count)).astype(float)
    recall_sums = np.einsum("sfd,dk->sfk", (rates[:, 1] - rates[:, 0]) * retained, grouping)
    recall_weights = np.einsum("sfd,dk->sfk", retained.astype(float), grouping)
    alarm_sums = (alarm_rates[:, 1] - alarm_rates[:, 0]) * retained_packages
    code_retained = np.all(stats.code_runs > 0, axis=1)
    off_complete = stats.code_detections[:, 0] == stats.code_runs[:, 0]
    code_lost = code_retained & off_complete & (stats.code_detections[:, 1] < stats.code_runs[:, 1])
    sometimes = code_retained & (stats.code_detections[:, 0] > 0) & ~off_complete
    cleared = (stats.clears[:, 1] > 0) & (stats.clears[:, 0] == 0)
    results: list[StudyVerdict] = []

    for study in range(stats.detections.shape[0]):
        reasons: list[str] = []
        figures: list[FigureStats] = []
        for figure, name in enumerate(FIGURES):
            recall = _paired(
                recall_sums[study, figure], recall_weights[study, figure], rules.alpha, recall=True
            )
            alarms = _paired(
                alarm_sums[study, figure],
                retained_packages[study, figure].astype(float),
                rules.alpha,
                recall=False,
            )
            figures.append(
                FigureStats(
                    retained_defects=int(np.count_nonzero(retained[study, figure])),
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
        named = [
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

        if reasons:
            outcome: Verdict = "quality loss"
        elif any(figure.retained_defects < rules.floor for figure in figures):
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
        elif any(not figure.recall.computable for figure in figures):
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
                if lower is not None and lower <= -0.10:
                    reasons.append(
                        f"{LOWER_END_AT_OR_BELOW_MINUS_TEN_POINTS}: {name} {lower * 100:.1f}"
                    )
            outcome = "inconclusive" if reasons else "no 10-point loss"
        results.append(
            StudyVerdict(
                verdict=outcome,
                reasons=reasons,
                figures=Figures(main=figures[0], sensitivity=figures[1]),
                code_guard=code_guard,
                cleared_guard=ClearedGuard(decides=rules.cleared_guard_decides, named=named),
            )
        )
    return results
