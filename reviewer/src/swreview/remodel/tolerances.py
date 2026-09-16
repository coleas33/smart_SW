"""The two named tolerance profiles the geometry gate compares against (T097).

`data-model.md` section 3.2 and `research.md` R4.4: two profiles, one pure function, and
the profiles are **frozen constants, never assembled at a call site**, so a run cannot
quietly widen a bound and then report a pass against it.

| Profile | volume | area | centre of mass | moments | face count | body count | Ships in |
|---|---|---|---|---|---|---|---|
| `IDENTITY` | 1e-9 | 1e-9 | 1e-9 | 1e-9 | exact | exact | v1, stage 1 |
| `EQUIVALENCE` | 1e-6 | 1e-5 | 1e-6 | 1e-5 | warn | exact | stage 2, selected by no v1 path |

In stage 1 the same B-rep is re-evaluated after a reorder, so any measured difference is a
defect, which is what `IDENTITY` says. `EQUIVALENCE` is declared here because stage 2
recreates a feature and a NURBS re-evaluation legitimately moves the last few digits; no
v1 code path selects it.

**Units (SC-010).** Every profile bound is a dimensionless ratio: a relative bound cannot
be mixed with an absolute one because the profiles contain no absolute bound at all. The
only absolute constants in this module are the three tier-2 residual thresholds of
`research.md` R4.6, and each carries its unit in its name (`_M3`, `_M`). Every length in
this feature is metres and every angle is radians; the gate compares no angle.

**Calibration (FR-036).** A tolerance that has never been compared against a known answer
does not ship. Both profiles carry `calibrated=False` until PROBE-8 measures the attained
relative error against a box and a cylinder of exactly known analytic volume and the
numbers are checked in at `benchmarks/native/remodel/tolerance-calibration.md`; until
then `require_calibrated` refuses, at `load_profile` on the way in and at the
`geometry.json` writer on the way out. T138 freezes the profiles against that ledger,
and the numbers live in the ledger, not in a comment here.

`Tolerances` carries one field the `geometry.json` example in `contracts/run-artifacts.md`
does not show, `name`, so a profile says which profile it is wherever it travels and
`GateResult.profile` is read off the profile rather than passed beside it.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CALIBRATION_LEDGER",
    "EQUIVALENCE",
    "IDENTITY",
    "PROFILES",
    "RESIDUAL_MIN_DIMENSION_M",
    "RESIDUAL_VOLUME_FLOOR_M3",
    "RESIDUAL_VOLUME_REL",
    "CountRule",
    "ProfileName",
    "Tolerances",
    "UncalibratedProfileError",
    "load_profile",
    "require_calibrated",
]

ProfileName = Literal["IDENTITY", "EQUIVALENCE"]
CountRule = Literal["exact", "warn"]

CALIBRATION_LEDGER = "benchmarks/native/remodel/tolerance-calibration.md"
"""Where PROBE-8's attained relative errors are recorded (quickstart.md Scenario 4)."""

RESIDUAL_VOLUME_FLOOR_M3 = 1e-12
"""Tier 2: the absolute floor of the residual-volume threshold, in cubic metres."""

RESIDUAL_VOLUME_REL = 1e-6
"""Tier 2: the relative half of the residual-volume threshold, `max(floor, rel x V)`."""

RESIDUAL_MIN_DIMENSION_M = 1e-5
"""Tier 2: a residual counts as real when its bounding box's **minimum** dimension reaches
this many metres; below it the residual is a sliver to inspect, not a difference."""


class Tolerances(BaseModel):
    """One named profile. Frozen: a call site reads it, it never builds one."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    name: ProfileName
    volume_rel: float
    area_rel: float
    com_rel: float
    moment_rel: float
    face_count: CountRule
    body_count: Literal["exact"]
    calibrated: bool
    calibration_ref: str | None


IDENTITY = Tolerances(
    name="IDENTITY",
    volume_rel=1e-9,
    area_rel=1e-9,
    com_rel=1e-9,
    moment_rel=1e-9,
    face_count="exact",
    body_count="exact",
    calibrated=False,
    calibration_ref=None,
)
"""Stage 1, where nothing geometric is supposed to change: any measured difference fails."""

EQUIVALENCE = Tolerances(
    name="EQUIVALENCE",
    volume_rel=1e-6,
    area_rel=1e-5,
    com_rel=1e-6,
    moment_rel=1e-5,
    face_count="warn",
    body_count="exact",
    calibrated=False,
    calibration_ref=None,
)
"""Stage 2, where a recreated feature may legitimately move the last digits. Declared
here so stage 2 adds a tier rather than a type; no v1 code path selects it."""

PROFILES: dict[ProfileName, Tolerances] | MappingProxyType[ProfileName, Tolerances] = (
    MappingProxyType({"IDENTITY": IDENTITY, "EQUIVALENCE": EQUIVALENCE})
)
"""Every profile there is, by name. Read-only: the ledger, not a caller, calibrates one."""


class UncalibratedProfileError(RuntimeError):
    """Raised for a profile PROBE-8 has not measured yet (FR-036)."""


def require_calibrated(profile: Tolerances) -> Tolerances:
    """Return the profile, refusing one that has never been compared against a known answer.

    The one place FR-036 is enforced, so the refusal reads the same wherever a profile
    enters a run: `load_profile` calls it on the way in and the `geometry.json` writer
    calls it on the way out, which is the boundary a profile read straight off this module
    would otherwise slip past.
    """
    if not profile.calibrated:
        raise UncalibratedProfileError(
            f"tolerance profile {profile.name!r} has not been calibrated: PROBE-8 must "
            f"measure the attained relative error against a part of exactly known analytic "
            f"volume and record it in {CALIBRATION_LEDGER} before this profile may decide a "
            f"run (FR-036). A tolerance that has never been compared against a known answer "
            f"does not ship."
        )
    return profile


def load_profile(name: ProfileName) -> Tolerances:
    """Return the named profile, refusing one that has never been calibrated.

    Raises `KeyError` when no profile has that name and `UncalibratedProfileError` while
    `calibrated` is `False`, which it is for both profiles until PROBE-8's ledger is
    checked in. Reading `IDENTITY` directly is deliberately still possible, because the
    case-table tests compare against the constants; it is *deciding a run with a profile*
    that a missing calibration refuses, here and at the artifact.
    """
    try:
        profile = PROFILES[name]
    except KeyError:
        raise KeyError(f"unknown tolerance profile {name!r}") from None
    return require_calibrated(profile)
