"""The pilot measurement's data contract (T229, verdict.md sections 10.3–10.4).

Compare reads these records without importing the pilot's future estimators or
search. Approval is the owner's act: reading neither approves a measurement nor
checks its stored digest, whose mismatch compare must name in its own refusal.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator

from swreview.benchmark import digest
from swreview.findings import FindingStatus, ReviewModel

PILOT_SCHEMA = 1


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
    cap: int = Field(ge=1)
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
