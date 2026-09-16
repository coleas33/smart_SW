"""The geometry gate: two readings in, one tri-state verdict out (T099).

`research.md` R4.2 splits this feature in two. The **measurement** happens in C#, where
the mass-property calls take ByRef out-parameters the Python bridge cannot marshal; the
**decision** happens here, in a pure function with no COM in its signature, so the verdict
that decides whether a run may save is table-testable without a SOLIDWORKS seat.

`evaluate(before, after, tolerances)` returns a `GateResult` whose `verdict` is `pass`,
`fail` or `unresolved` from day one - **never a Boolean, and never inferred from a
successful rebuild**. The three states are not decoration:

- `pass`: every gated quantity was readable and stayed inside its bound;
- `fail`: a gated quantity moved outside its bound;
- `unresolved`: the comparison did not happen. A mass-properties status other than OK, a
  `Recalculate()` that returned false, a baseline volume of zero (guarded, never divided
  by), a baseline carrying two solid bodies (the scope gate should have refused the part),
  an unreadable count, or tier 1 failing while tier 2 passes, which is a bug in the
  tolerances and is resolved neither way.

Tier 1 is mass properties and is the whole stage-1 gate: the same B-rep is re-evaluated
after a reorder, so under `IDENTITY` any measured difference is a defect. Tier 2 is the
boolean symmetric difference (`research.md` R4.6), the only thing that can see a
reflection; its **measurement** is stage 2, but its **decision** lives here behind the
optional `residual` argument (T101), so stage 2 adds a tier rather than changing a type.

Three rules the shape of this module encodes:

- **mass is not geometry.** `Mass = Volume x Density` and density comes from the material,
  so the mass delta never gates; a mass-only difference reports `material_changed`.
- **principal moments are sorted ascending before comparison**, because two bodies
  differing by a symmetry-degenerate rotation return the same three numbers permuted.
  Sorting is part of the comparison, not a fix-up applied to a failure.
- **every bound is relative** (`tolerances.py`): the centre of mass is compared as a
  distance over the baseline's characteristic length `V**(1/3)` rather than against an
  absolute bound, because `|com|` itself is zero for a symmetric part and an absolute
  bound would have to be mixed with the relative ones (SC-010).

`coverage_limits` is written on every run, including a passing one, because Principle VI
requires the report to say what was **not** checked.

`write_geometry_json` refuses a profile PROBE-8 has not calibrated (FR-036): `evaluate`
still decides under the constants, and it is publishing a verdict as a run's answer under
bounds nobody has compared against a known answer that does not ship.

Two fields here are additions to `data-model.md` section 3.3, each earning its place:
`Delta.gates` says whether a delta decided the verdict, so a reader can see why a
`within: false` on mass or on a warned face count did not fail the run; and
`Tolerances.name` (in `tolerances.py`) carries the profile's own name.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from swreview.remodel.tolerances import (
    RESIDUAL_MIN_DIMENSION_M,
    RESIDUAL_VOLUME_FLOOR_M3,
    RESIDUAL_VOLUME_REL,
    CountRule,
    ProfileName,
    Tolerances,
    require_calibrated,
)

__all__ = [
    "BODY_OPERATION_BOOLEAN_FAIL",
    "BODY_OPERATION_EMPTY_BODY",
    "BODY_OPERATION_NON_API_BODY",
    "BODY_OPERATION_NO_ERROR",
    "BODY_OPERATION_NO_INTERSECT",
    "BODY_OPERATION_PARTIAL_COINCIDENCE",
    "BODY_OPERATION_UNKNOWN_ERROR",
    "COVERAGE_LIMITS",
    "GEOMETRY_FILE_NAME",
    "MASS_PROPERTIES_STATUS_OK",
    "Delta",
    "GateResult",
    "GeometryArtifact",
    "GeometryReading",
    "ResidualReading",
    "Subject",
    "TierResult",
    "Verdict",
    "evaluate",
    "write_geometry_json",
]

GEOMETRY_FILE_NAME = "geometry.json"

Verdict = Literal["pass", "fail", "unresolved"]
Subject = Literal["copy_at_open", "copy_at_end"]

MASS_PROPERTIES_STATUS_OK = 0
"""`swMassPropertiesStatus_e.swMassPropertiesStatus_OK` (VERIFIED). Anything else makes
the gate `unresolved`, never `fail`: the measurement failed, the geometry did not move."""

BODY_OPERATION_UNKNOWN_ERROR = -1
BODY_OPERATION_NO_ERROR = 0
BODY_OPERATION_NON_API_BODY = 1
BODY_OPERATION_EMPTY_BODY = 6
BODY_OPERATION_PARTIAL_COINCIDENCE = 1040
BODY_OPERATION_BOOLEAN_FAIL = 1058
BODY_OPERATION_NO_INTERSECT = 1067
"""`swBodyOperationError_e`, all VERIFIED values (`research.md` R4.6). The whole tier-2
vocabulary is these six codes read together with the residual, never alone."""

COVERAGE_LIMITS: tuple[str, ...] = (
    "a reflection",
    "a rigid rotation about a symmetry axis",
    "compensating add and remove pairs",
    "any difference occupying no volume (split faces, cosmetic threads, material, "
    "custom properties, configuration data)",
    "surface-body and wire-body differences",
    "a difference produced by the baseline rollback and rebuild themselves, which sits "
    "inside the baseline reading and cannot be seen from it",
)
"""What tier 1 cannot detect (`data-model.md` section 3.4), printed on every run."""

_SURFACE_BODIES_UNCOVERED = (
    "surface bodies are present on this part, so the gate's surface coverage is "
    "uncovered, never passed"
)
_MATERIAL_NOT_COMPARED = (
    "the material name was unreadable on at least one reading, so material was not "
    "compared and is not reported as unchanged"
)


class ResidualReading(BaseModel):
    """What the tier-2 symmetric difference left over. Stage 2 measures it; v1 never does."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    error_code: int
    body_count: int
    total_volume_m3: float | None
    per_body_bbox: tuple[tuple[float | None, float | None, float | None], ...] = ()


class GeometryReading(BaseModel):
    """One mass-properties reading of the run's own copy (`data-model.md` section 3.1).

    Both readings are of the copy: `copy_at_open` after the baseline rollback and rebuild
    and before the first change, `copy_at_end` after the last one. The source is never
    opened for the comparison in any mode (FR-037); `source_sha256` is the attested hash
    that makes the baseline stand for the source, so the artifact names the file it speaks
    for. There is no prototype reading and no reference body in any tree.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    at: str
    source_sha256: str
    subject: Subject
    status: int
    accuracy_level: int
    recalculated: bool
    volume_m3: float | None
    surface_area_m2: float | None
    center_of_mass_m: tuple[float, float, float] | None
    principal_moments: tuple[float, float, float] | None
    mass_kg: float | None
    density: float | None
    material_name: str | None
    solid_body_count: int
    sheet_body_count: int
    face_count: int | None
    edge_count: int | None
    residual: ResidualReading | None = None


class Delta(BaseModel):
    """One compared quantity. `within` is null when the comparison could not be made."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    quantity: str
    before: float | tuple[float, float, float] | None
    after: float | tuple[float, float, float] | None
    absolute: float | None
    relative: float | None
    bound: float | str
    within: bool | None
    gates: bool


class TierResult(BaseModel):
    """What one tier concluded. `ran` is true only when the tier reached pass or fail."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    ran: bool
    verdict: Verdict
    reason: str | None


class GateResult(BaseModel):
    """The verdict and everything it was reached from (`data-model.md` section 3.3)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    verdict: Verdict
    profile: ProfileName
    tier_1: TierResult
    tier_2: TierResult | None
    deltas: tuple[Delta, ...]
    material_changed: bool
    coverage_limits: tuple[str, ...]
    diagnosis: str | None


def _blocking_reasons(before: GeometryReading, after: GeometryReading) -> list[str]:
    """Reasons the measurement itself cannot be trusted, before any quantity is compared."""
    reasons: list[str] = []
    for label, reading in (("baseline", before), ("final", after)):
        if not reading.recalculated:
            reasons.append(
                f"the {label} reading's Recalculate() returned false, so nothing on it was read"
            )
        if reading.status != MASS_PROPERTIES_STATUS_OK:
            reasons.append(
                f"the {label} reading's mass-properties status is {reading.status}, "
                f"not OK ({MASS_PROPERTIES_STATUS_OK})"
            )
    if before.solid_body_count != 1:
        reasons.append(
            f"the baseline reading has {before.solid_body_count} solid bodies, so bodies "
            f"cannot be paired; the scope gate should have refused this part earlier"
        )
    return reasons


def _scalar_delta(
    quantity: str,
    before_value: float | None,
    after_value: float | None,
    bound: float,
    *,
    gates: bool = True,
) -> tuple[Delta, str | None]:
    """A relative comparison of one scalar, guarded against a null and a zero baseline."""
    if before_value is None or after_value is None:
        missing = "baseline" if before_value is None else "final"
        return (
            Delta(
                quantity=quantity,
                before=before_value,
                after=after_value,
                absolute=None,
                relative=None,
                bound=bound,
                within=None,
                gates=gates,
            ),
            f"{quantity} is unreadable on the {missing} reading",
        )
    absolute = abs(after_value - before_value)
    if before_value == 0.0:
        return (
            Delta(
                quantity=quantity,
                before=before_value,
                after=after_value,
                absolute=absolute,
                relative=None,
                bound=bound,
                within=None,
                gates=gates,
            ),
            f"the baseline {quantity} is zero, so no relative comparison is possible",
        )
    relative = absolute / abs(before_value)
    return (
        Delta(
            quantity=quantity,
            before=before_value,
            after=after_value,
            absolute=absolute,
            relative=relative,
            bound=bound,
            within=relative <= bound,
            gates=gates,
        ),
        None,
    )


def _com_delta(
    before: GeometryReading, after: GeometryReading, bound: float
) -> tuple[Delta, str | None]:
    """The centre of mass as a distance over the baseline's characteristic length.

    `V**(1/3)` is the only length the reading carries, and dividing by it keeps the bound
    relative like every other one. `|com|` is not usable as the scale: it is zero for a
    part whose centre of mass sits on the origin.
    """
    quantity = "center_of_mass_m"
    if before.center_of_mass_m is None or after.center_of_mass_m is None:
        missing = "baseline" if before.center_of_mass_m is None else "final"
        return (
            Delta(
                quantity=quantity,
                before=before.center_of_mass_m,
                after=after.center_of_mass_m,
                absolute=None,
                relative=None,
                bound=bound,
                within=None,
                gates=True,
            ),
            f"{quantity} is unreadable on the {missing} reading",
        )
    distance = math.dist(before.center_of_mass_m, after.center_of_mass_m)
    scale = (
        before.volume_m3 ** (1.0 / 3.0)
        if before.volume_m3 is not None and before.volume_m3 > 0.0
        else None
    )
    if scale is None:
        return (
            Delta(
                quantity=quantity,
                before=before.center_of_mass_m,
                after=after.center_of_mass_m,
                absolute=distance,
                relative=None,
                bound=bound,
                within=None,
                gates=True,
            ),
            f"{quantity} cannot be compared relatively: the baseline volume is zero or "
            f"unreadable, so it yields no characteristic length to scale the distance by",
        )
    relative = distance / scale
    return (
        Delta(
            quantity=quantity,
            before=before.center_of_mass_m,
            after=after.center_of_mass_m,
            absolute=distance,
            relative=relative,
            bound=bound,
            within=relative <= bound,
            gates=True,
        ),
        None,
    )


def _moment_deltas(
    before: GeometryReading, after: GeometryReading, bound: float
) -> list[tuple[Delta, str | None]]:
    """The three principal moments, **sorted ascending on both sides** before comparing."""
    if before.principal_moments is None or after.principal_moments is None:
        missing = "baseline" if before.principal_moments is None else "final"
        return [
            (
                Delta(
                    quantity=f"principal_moment_{i}",
                    before=None,
                    after=None,
                    absolute=None,
                    relative=None,
                    bound=bound,
                    within=None,
                    gates=True,
                ),
                f"principal_moment_{i} is unreadable on the {missing} reading",
            )
            for i in range(3)
        ]
    sorted_before = sorted(before.principal_moments)
    sorted_after = sorted(after.principal_moments)
    return [
        _scalar_delta(f"principal_moment_{i}", sorted_before[i], sorted_after[i], bound)
        for i in range(3)
    ]


def _count_delta(
    quantity: str, before_value: int | None, after_value: int | None, rule: CountRule
) -> tuple[Delta, str | None]:
    """An exact comparison of one topology or body count. `warn` records but never gates."""
    gates = rule == "exact"
    if before_value is None or after_value is None:
        missing = "baseline" if before_value is None else "final"
        return (
            Delta(
                quantity=quantity,
                before=before_value,
                after=after_value,
                absolute=None,
                relative=None,
                bound=rule,
                within=None,
                gates=gates,
            ),
            f"{quantity} is unreadable on the {missing} reading",
        )
    return (
        Delta(
            quantity=quantity,
            before=float(before_value),
            after=float(after_value),
            absolute=float(abs(after_value - before_value)),
            relative=None,
            bound=rule,
            within=before_value == after_value,
            gates=gates,
        ),
        None,
    )


def _tier_1_deltas(
    before: GeometryReading, after: GeometryReading, tolerances: Tolerances
) -> list[tuple[Delta, str | None]]:
    """Every compared quantity, in the order a report reads them."""
    return [
        _scalar_delta("volume_m3", before.volume_m3, after.volume_m3, tolerances.volume_rel),
        _scalar_delta(
            "surface_area_m2", before.surface_area_m2, after.surface_area_m2, tolerances.area_rel
        ),
        _com_delta(before, after, tolerances.com_rel),
        *_moment_deltas(before, after, tolerances.moment_rel),
        _count_delta(
            "solid_body_count",
            before.solid_body_count,
            after.solid_body_count,
            tolerances.body_count,
        ),
        _count_delta("face_count", before.face_count, after.face_count, tolerances.face_count),
        # `edge_count` has no row in the profile table of `data-model.md` section 3.2, so it
        # is exact under every profile rather than borrowing `face_count`'s rule: no profile
        # grants an edge-count change, and a bound that no profile publishes is not one the
        # gate may relax on its own.
        _count_delta("edge_count", before.edge_count, after.edge_count, "exact"),
        _scalar_delta(
            "mass_kg", before.mass_kg, after.mass_kg, tolerances.volume_rel, gates=False
        ),
    ]


def _failure_reason(delta: Delta) -> str:
    """Why one delta failed, in the words the report prints: what moved and by how much."""
    if delta.relative is not None and isinstance(delta.bound, float):
        return (
            f"{delta.quantity} moved by {delta.relative:.3g} relative, outside its bound "
            f"of {delta.bound:.3g}"
        )
    return f"{delta.quantity} changed from {delta.before} to {delta.after} (bound: {delta.bound})"


def _implied_uniform_scale(
    before: GeometryReading, after: GeometryReading, tolerances: Tolerances
) -> float | None:
    """The uniform scale the volume and area deltas agree on, or None when they do not."""
    volume_before, volume_after = before.volume_m3, after.volume_m3
    area_before, area_after = before.surface_area_m2, after.surface_area_m2
    if volume_before is None or volume_after is None or area_before is None or area_after is None:
        return None
    if volume_before <= 0.0 or volume_after <= 0.0 or area_before <= 0.0 or area_after <= 0.0:
        return None
    volume_scale = (volume_after / volume_before) ** (1.0 / 3.0)
    area_scale = math.sqrt(area_after / area_before)
    if abs(volume_scale - 1.0) <= tolerances.volume_rel:
        return None
    if abs(volume_scale - area_scale) > 1e-6 * volume_scale:
        return None
    return volume_scale


def _material_changed(
    before: GeometryReading, after: GeometryReading, deltas: dict[str, Delta]
) -> bool:
    """A mass-only difference is the material, never the geometry.

    A mass that moved while the volume stayed inside its bound can only be density, and
    density comes from the material. When the names are unreadable the mass still decides,
    and `coverage_limits` says the name was not compared rather than calling it unchanged.
    """
    names_known = before.material_name is not None and after.material_name is not None
    if names_known and before.material_name != after.material_name:
        return True
    mass = deltas["mass_kg"]
    volume = deltas["volume_m3"]
    return mass.within is False and volume.within is True


def _coverage_limits(before: GeometryReading, after: GeometryReading) -> tuple[str, ...]:
    limits = list(COVERAGE_LIMITS)
    if before.sheet_body_count > 0 or after.sheet_body_count > 0:
        limits.append(_SURFACE_BODIES_UNCOVERED)
    if before.material_name is None or after.material_name is None:
        limits.append(_MATERIAL_NOT_COMPARED)
    return tuple(limits)


def _tier_1(
    before: GeometryReading, after: GeometryReading, tolerances: Tolerances
) -> tuple[TierResult, tuple[Delta, ...], dict[str, Delta]]:
    measured = _tier_1_deltas(before, after, tolerances)
    deltas = tuple(delta for delta, _ in measured)
    by_quantity = {delta.quantity: delta for delta in deltas}
    unresolved = _blocking_reasons(before, after)
    unresolved += [reason for delta, reason in measured if delta.gates and reason is not None]
    if unresolved:
        return (
            TierResult(ran=False, verdict="unresolved", reason="; ".join(unresolved)),
            deltas,
            by_quantity,
        )
    failed = [delta for delta in deltas if delta.gates and delta.within is False]
    if failed:
        return (
            TierResult(
                ran=True,
                verdict="fail",
                reason="; ".join(_failure_reason(delta) for delta in failed),
            ),
            deltas,
            by_quantity,
        )
    return TierResult(ran=True, verdict="pass", reason=None), deltas, by_quantity


_GATE_DID_NOT_RUN: dict[int, str] = {
    BODY_OPERATION_BOOLEAN_FAIL: (
        f"swBodyOperationBooleanFail ({BODY_OPERATION_BOOLEAN_FAIL}): the boolean failed, "
        f"so the symmetric difference produced no verdict"
    ),
    BODY_OPERATION_UNKNOWN_ERROR: (
        f"swBodyOperationUnknownError ({BODY_OPERATION_UNKNOWN_ERROR}): the boolean "
        f"reported an unknown error, so the symmetric difference produced no verdict"
    ),
    BODY_OPERATION_NON_API_BODY: (
        f"swBodyOperationNonApiBody ({BODY_OPERATION_NON_API_BODY}): the input was not an "
        f"API body, so the symmetric difference did not run"
    ),
}
"""The three codes that mean the gate did not run. Each is `unresolved`, never `pass`."""


def _residual_threshold_m3(before: GeometryReading) -> float:
    """`max(1e-12 m3, 1e-6 x V)` (`research.md` R4.6), with a missing volume falling back
    to the absolute floor rather than to no threshold at all."""
    volume = before.volume_m3 if before.volume_m3 is not None and before.volume_m3 > 0.0 else 0.0
    return max(RESIDUAL_VOLUME_FLOOR_M3, RESIDUAL_VOLUME_REL * volume)


def _largest_residual_min_dimension_m(residual: ResidualReading) -> float | None:
    """The **minimum** dimension of the largest residual's bounding box, in metres.

    Largest by bounding-box volume, because the reading carries no per-body volume. The
    minimum dimension is the signal: a 10 mm by 10 mm by 0.2 um lump is a sliver whatever
    its footprint, and a residual only counts as real when its thinnest dimension does.
    """
    boxes = [
        (box[0], box[1], box[2])
        for box in residual.per_body_bbox
        if box[0] is not None and box[1] is not None and box[2] is not None
    ]
    if not boxes:
        return None
    largest = max(boxes, key=lambda box: box[0] * box[1] * box[2])
    return min(largest)


def _tier_2(before: GeometryReading, residual: ResidualReading) -> TierResult:
    """Decide the symmetric difference from the error code and the three residual signals.

    The signals are read separately and never collapsed into one scalar: the total
    residual volume against its threshold, the residual body count (recorded, **not**
    gated - many tiny lumps is the sliver signature, one big lump is a real difference),
    and the largest residual's bounding-box minimum dimension.

    All three have to have been read. A residual volume that is null, a bounding-box side
    that is null and a set of boxes that does not cover every reported body are the same
    thing - a measurement that did not happen - and each is `unresolved`, never a pass
    decided from the two signals that did arrive.
    """
    if residual.error_code in _GATE_DID_NOT_RUN:
        return TierResult(
            ran=False, verdict="unresolved", reason=_GATE_DID_NOT_RUN[residual.error_code]
        )
    if residual.total_volume_m3 is None:
        return TierResult(
            ran=False,
            verdict="unresolved",
            reason="the residual volume was not readable, so the symmetric difference "
            "produced no verdict",
        )
    if len(residual.per_body_bbox) != residual.body_count:
        return TierResult(
            ran=False,
            verdict="unresolved",
            reason=f"bounding boxes were read for {len(residual.per_body_bbox)} of "
            f"{residual.body_count} residual bodies, so the largest residual's minimum "
            f"dimension is not a reading of every residual and the gate did not run on "
            f"the residual",
        )
    if any(side is None for box in residual.per_body_bbox for side in box):
        return TierResult(
            ran=False,
            verdict="unresolved",
            reason="a residual body's bounding box was unreadable (GetBodyBox returned "
            "null), so the gate did not run on that residual",
        )
    threshold = _residual_threshold_m3(before)
    min_dimension = _largest_residual_min_dimension_m(residual)
    dimension_signal = (
        f"the largest residual's bounding-box minimum dimension is {min_dimension:.3g} m "
        f"against {RESIDUAL_MIN_DIMENSION_M:.3g} m"
        if min_dimension is not None
        else "no residual bounding box was reported"
    )
    signals = (
        f"residual volume {residual.total_volume_m3:.3g} m3 against a threshold of "
        f"{threshold:.3g} m3; {residual.body_count} residual bodies; {dimension_signal}"
    )
    if residual.error_code == BODY_OPERATION_EMPTY_BODY:
        return TierResult(
            ran=True,
            verdict="pass",
            reason=f"swBodyOperationEmptyBody ({BODY_OPERATION_EMPTY_BODY}): the cut left "
            f"nothing, so one body lies entirely inside the other, a pass signal read "
            f"together with the other direction ({signals})",
        )
    prefix = ""
    if residual.error_code == BODY_OPERATION_NO_INTERSECT:
        prefix = (
            f"swBodyOperationNoIntersect ({BODY_OPERATION_NO_INTERSECT}), read with the "
            f"residual volume and never alone: "
        )
    elif residual.error_code == BODY_OPERATION_PARTIAL_COINCIDENCE:
        prefix = (
            f"swBodyOperationPartialCoincidence ({BODY_OPERATION_PARTIAL_COINCIDENCE}), "
            f"the sliver signature, inspected rather than failed on: "
        )
    over_threshold = residual.total_volume_m3 > threshold
    real_by_dimension = min_dimension is not None and min_dimension >= RESIDUAL_MIN_DIMENSION_M
    verdict: Verdict = "fail" if over_threshold or real_by_dimension else "pass"
    return TierResult(ran=True, verdict=verdict, reason=prefix + signals)


def _residual_is_the_whole_part(
    before: GeometryReading, residual: ResidualReading, tolerances: Tolerances
) -> bool:
    if before.volume_m3 is None or residual.total_volume_m3 is None:
        return False
    return residual.total_volume_m3 >= before.volume_m3 * (1.0 - tolerances.volume_rel)


def _combined_verdict(tier_1: TierResult, tier_2: TierResult | None) -> Verdict:
    """The two tiers into one verdict (`research.md` R4.7).

    Tier 1 passing while tier 2 fails **is** the mirrored-part case and is a failure. Tier
    1 failing while tier 2 passes is a bug in the tolerances and is `unresolved`, resolved
    neither way.
    """
    if tier_1.verdict == "unresolved" or tier_2 is None:
        return tier_1.verdict
    if tier_2.verdict == "unresolved":
        return "unresolved"
    if tier_1.verdict == "fail" and tier_2.verdict == "pass":
        return "unresolved"
    if tier_1.verdict == "pass" and tier_2.verdict == "pass":
        return "pass"
    return "fail"


def _diagnosis(
    before: GeometryReading,
    after: GeometryReading,
    tolerances: Tolerances,
    verdict: Verdict,
    tier_1: TierResult,
    tier_2: TierResult | None,
    residual: ResidualReading | None,
) -> str | None:
    """Required whenever the verdict is not `pass`, and spelled out rather than coded."""
    if verdict == "pass":
        return None
    if tier_2 is not None and tier_1.verdict == "fail" and tier_2.verdict == "pass":
        return (
            f"tier 1 failed ({tier_1.reason}) while tier 2 found no residual ({tier_2.reason}). "
            f"That combination is a bug in the tolerances, not a geometry verdict, so the "
            f"gate reports unresolved and resolves it neither way"
        )
    if verdict == "unresolved":
        tiers = (tier_1, tier_2)
        reasons = [t.reason for t in tiers if t is not None and t.verdict == "unresolved"]
        return "the gate did not run: " + "; ".join(reason for reason in reasons if reason)
    if tier_2 is not None and tier_1.verdict == "pass" and tier_2.verdict == "fail":
        whole_part = residual is not None and _residual_is_the_whole_part(
            before, residual, tolerances
        )
        mirrored = (
            " The residual equals the full baseline volume, which is the signature of a "
            "reflection."
            if whole_part
            else ""
        )
        return (
            f"tier 1 (mass properties) found no difference and the symmetric difference "
            f"left a residual ({tier_2.reason}). Volume, surface area and all three "
            f"principal moments are invariant under any isometry including a mirror, so "
            f"this is exactly the class of difference tier 1 cannot see: a reflection."
            f"{mirrored}"
        )
    diagnosis = f"the geometry moved: {tier_1.reason}"
    scale = _implied_uniform_scale(before, after, tolerances)
    if scale is not None:
        diagnosis += f". The volume and area deltas agree on a uniform scale of {scale:.6g}"
    if tier_2 is not None and tier_2.verdict == "fail":
        diagnosis += f". The symmetric difference agrees: {tier_2.reason}"
    return diagnosis


def evaluate(
    before: GeometryReading,
    after: GeometryReading,
    tolerances: Tolerances,
    *,
    residual: ResidualReading | None = None,
) -> GateResult:
    """Decide whether the copy's geometry moved between the two readings.

    Pure: two readings and a named profile in, one tri-state `GateResult` out. Nothing
    here opens a document, and nothing here is a Boolean.

    `residual` is the stage-2 symmetric difference. It is an optional argument rather than
    a second function so stage 2 adds a tier rather than changing this type; v1 never
    measures one, so `tier_2` is null on every v1 run. It is passed explicitly rather than
    read off `after.residual` so the caller says which reading the gate is deciding from.
    """
    tier_1, deltas, by_quantity = _tier_1(before, after, tolerances)
    tier_2 = _tier_2(before, residual) if residual is not None else None
    verdict = _combined_verdict(tier_1, tier_2)
    return GateResult(
        verdict=verdict,
        profile=tolerances.name,
        tier_1=tier_1,
        tier_2=tier_2,
        deltas=deltas,
        material_changed=_material_changed(before, after, by_quantity),
        coverage_limits=_coverage_limits(before, after),
        diagnosis=_diagnosis(before, after, tolerances, verdict, tier_1, tier_2, residual),
    )


class GeometryArtifact(BaseModel):
    """`geometry.json`: both readings, the verdict, and the profile it was reached under.

    The shape is `contracts/run-artifacts.md`'s four blocks, and the model enforces the
    three things a reader of the file would otherwise have to take on trust:

    - the baseline is the copy at open and the final reading is the copy at end, so a
      reading of anything else cannot be filed as a baseline (FR-037);
    - both readings carry the **same** `source_sha256`, the attested hash recorded before
      any document handle existed, which is what makes the baseline stand for the source
      without the source ever being opened;
    - the gate's `profile` is the profile filed beside it, so the bounds in the artifact
      are the bounds the verdict was reached under.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    before: GeometryReading
    after: GeometryReading
    gate: GateResult
    tolerances: Tolerances

    @model_validator(mode="after")
    def _both_readings_are_of_the_copy(self) -> GeometryArtifact:
        if self.before.subject != "copy_at_open":
            raise ValueError(
                f"the baseline reading's subject is {self.before.subject!r}, not "
                f"'copy_at_open': the baseline is the copy read after the rollback and "
                f"rebuild and before the first change"
            )
        if self.after.subject != "copy_at_end":
            raise ValueError(
                f"the final reading's subject is {self.after.subject!r}, not "
                f"'copy_at_end': the final reading is the copy read after the last change"
            )
        if self.before.source_sha256 != self.after.source_sha256:
            raise ValueError(
                f"the two readings carry different source_sha256 values "
                f"({self.before.source_sha256} and {self.after.source_sha256}), so they do "
                f"not stand for the same source file"
            )
        if self.gate.profile != self.tolerances.name:
            raise ValueError(
                f"the gate was decided under profile {self.gate.profile!r} but "
                f"{self.tolerances.name!r} is filed beside it"
            )
        return self


def write_geometry_json(
    run_dir: Path,
    *,
    before: GeometryReading,
    after: GeometryReading,
    gate: GateResult,
    tolerances: Tolerances,
) -> Path:
    """Write `geometry.json` into `run_dir` and return the path it was written to.

    This is the only filesystem access in the gate: it reads nothing, and it writes one
    file inside the run folder. The source file is never opened for the comparison in any
    mode (FR-037) - there is nothing here that could open it.

    Raises `UncalibratedProfileError` for a profile PROBE-8 has not measured (FR-036), so
    an artifact cannot record a `pass` beside bounds nobody has compared against a known
    answer. `evaluate` still decides - the case table compares against the uncalibrated
    constants - and it is publishing the verdict as a run's answer that is refused.
    """
    artifact = GeometryArtifact(before=before, after=after, gate=gate, tolerances=tolerances)
    require_calibrated(artifact.tolerances)
    target = run_dir / GEOMETRY_FILE_NAME
    target.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target
