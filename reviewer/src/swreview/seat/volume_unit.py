"""`swreview seat volume-unit`: which unit `IInterference.Volume` answers in (001 R15, 172A).

The unit is undocumented (001 research R12, open question 5), so `InterferenceRunner` labels the
number m3 and adds a gap until a seat measures it (`VolumeUnitVerified`, 001 T069). The seat
measures it on two made-up cubes that overlap by a known volume
(`benchmarks/native/interference-volume/RECIPE.md`, 1000 mm3): the one computed volume the package
records is compared, whatever its label, with that overlap in m3 and in mm3, within 1 per cent.
The two candidates are a factor of 10^9 apart, so at most one matches; neither is inconclusive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from swreview.ir.loader import load_package
from swreview.ir.models import Interference

TOLERANCE = 0.01
INCONCLUSIVE = "inconclusive"
MM3_IN = {"m3": 1e9, "mm3": 1.0}
"""Cubic millimetres in one of each unit the judge can answer."""

MM3_IN_IN3 = 16387.064
"""Named in an inconclusive reason only: a document's own unit, from an inch template."""


@dataclass(frozen=True)
class Judgement:
    unit: str
    reason: str
    recorded: dict[str, float | str] | None
    expected_mm3: float
    next: str | None


def interferences(path: Path) -> list[Interference]:
    """The rows of a package (its folder or its `package.json`), or one record on its own."""
    if path.is_dir() or path.name == "package.json":
        return list(load_package(path if path.is_dir() else path.parent).package.interferences)
    return [Interference.model_validate_json(path.read_bytes())]


def judge(rows: list[Interference], expected_mm3: float) -> Judgement:
    computed = [
        volume for row in rows if row.status == "computed" and (volume := row.volume) is not None
    ]
    if len(computed) != 1:
        return Judgement(
            INCONCLUSIVE,
            f"{len(computed)} computed interference volumes, not one: the recipe's two cubes give "
            "exactly one (its step 4 shows it)",
            None,
            expected_mm3,
            None,
        )
    volume = computed[0]
    recorded: dict[str, float | str] = {"value": volume.value, "unit": volume.unit}
    for unit, per in MM3_IN.items():
        if math.isclose(volume.value * per, expected_mm3, rel_tol=TOLERANCE):
            if unit == volume.unit:
                change = (
                    "the package's label holds: set InterferenceRunner.VolumeUnitVerified = true"
                )
            else:
                change = (
                    f"the package labels it {volume.unit}, which is wrong: set "
                    f"InterferenceRunner.AssumedVolumeUnit = VolumeUnit.{unit.capitalize()} and "
                    "VolumeUnitVerified = true"
                )
            return Judgement(
                unit,
                f"the recorded {volume.value:g} is the known {expected_mm3:g} mm3 in {unit}, "
                "within 1 per cent",
                recorded,
                expected_mm3,
                f"{change} (001 T069; an extractor change, the owner's)",
            )
    reason = (
        f"the recorded {volume.value:g} is the known {expected_mm3:g} mm3 neither in m3 "
        f"({expected_mm3 / MM3_IN['m3']:g}) nor in mm3, within 1 per cent"
    )
    if math.isclose(volume.value * MM3_IN_IN3, expected_mm3, rel_tol=TOLERANCE):
        reason += "; it is the overlap in in3, so the assembly was built from an inch template"
    return Judgement(INCONCLUSIVE, reason, recorded, expected_mm3, None)
