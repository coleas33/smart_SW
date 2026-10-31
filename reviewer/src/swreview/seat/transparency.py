"""`swreview seat transparency`: PROBE-2's polarity from the probe's own lines (006 R11, 172A).

006 T102 asks which recorded transparency value means transparent, and whether slot 7 of
`GetMaterialPropertyValues2` is the transparency slot on this build (research R2.8, R4). The seat
answers on a made-up assembly (`benchmarks/native/probe2-polarity/RECIPE.md`): one block three
times, the first two given one component-level colour, the first of them made transparent, the
third left alone. `swreview-extract probe standards` prints each one's nine slots, and this reads
only its PROBE-2 lines:

- the transparent and opaque overrides must differ at slot 7 and nowhere else; the opaque one's
  slot 7 then names the polarity, 0 for `zero_is_opaque` and 1 for `one_is_opaque`;
- slot 7 equal while the colour is equal and another slot differs, or no slot 7 at all, refutes
  slot 7: the dump reads that slot (`ComponentTreeDumper.ReadTransparency`), so the constant
  cannot settle it;
- anything else is inconclusive and says what did not hold, because a guess either way silently
  mislabels every override (research R2.8). Overrides that differ nowhere, or in colour, are
  inconclusive rather than a refutation: a missed recipe step explains them, and a refutation
  sends the owner to change the extractor. So is a slot that is no finite number, or a slot 7
  outside 0 to 1, which no transparency is: the read went wrong (R11.2).
"""

from __future__ import annotations

import codecs
import math
import re
from dataclasses import dataclass
from pathlib import Path

from swreview.checks.standards.assembly import ONE_IS_OPAQUE, ZERO_IS_OPAQUE
from swreview.seat import INCONCLUSIVE

SECTION = "probe-2 appearance_overrides:"
SLOT = 7
COLOUR = (0, 1, 2)
"""The slots of the colour, red, green and blue; the lighting slots follow them."""

DEFAULT_NAMES = {
    "transparent": "PROBE2-BLOCK-1",
    "opaque": "PROBE2-BLOCK-2",
    "plain": "PROBE2-BLOCK-3",
}
"""The recipe's three instances, by role."""

GOLDENS = "reviewer/tests/golden/test_transparency_polarity"
REFUTED = (
    "the dump reads slot 7 (ComponentTreeDumper.ReadTransparency), so this needs an extractor "
    "change, not the flip: tell the owner"
)

_LINE = re.compile(
    r"\s+\S+ (?P<key>.+?) HasMaterialPropertyValues=(?P<has>.*?) "
    r"GetMaterialPropertyValues2\(1, null\)=(?P<slots>.*)"
)
_SLOTS = re.compile(r"(?P<count>\d+) slots(?P<values>( \[\d+\]=\S+)*)")
_SLOT = re.compile(r"\[(\d+)\]=(\S+)")


@dataclass(frozen=True)
class Reading:
    role: str
    name: str
    has_override: bool | None
    slots: list[float] | None


@dataclass(frozen=True)
class Decision:
    verdict: str
    slot_7_refuted: bool
    reason: str
    readings: list[Reading]
    next: str | None


def read_text(path: Path) -> str:
    """The probe's output as the seat saved it: Windows PowerShell 5.1's `>` writes UTF-16."""
    raw = path.read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def _section(text: str) -> list[str] | str:
    """The PROBE-2 section's lines, or why there is no one section to read."""
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == SECTION]
    if len(starts) != 1:
        return (
            f"the file holds {len(starts)} probe-2 sections, not one: give it the output of one "
            "`swreview-extract probe standards` run"
        )
    body = []
    for line in lines[starts[0] + 1 :]:
        if not line[:1].isspace():
            break
        body.append(line)
    return body


def _slots(printed: str) -> list[float] | None:
    """`9 slots [0]=0 ... [8]=0` as numbers in slot order; None for `null`, a failure, a gap, a
    count that disagrees with the slots listed, no slots at all, or a slot that is no finite
    number (the probe prints `NaN` and `Infinity` as such)."""
    match = _SLOTS.fullmatch(printed.strip())
    if not match:
        return None
    values = []
    for position, (index, value) in enumerate(_SLOT.findall(match["values"])):
        try:
            number = float(value)
        except ValueError:
            return None
        if int(index) != position or not math.isfinite(number):
            return None
        values.append(number)
    return values if values and len(values) == int(match["count"]) else None


def _read(body: list[str], role: str, name: str) -> Reading | str:
    found = []
    for line in body:
        match = _LINE.fullmatch(line)
        if match and match["key"].rsplit("/", 1)[-1].lower() == name.lower():
            found.append(match)
    if len(found) != 1:
        where = "is not among" if not found else f"is listed {len(found)} times in"
        return f"{name} (the {role} block) {where} the probe-2 components"
    has = {"True": True, "False": False}.get(found[0]["has"].strip())
    return Reading(role, name, has, _slots(found[0]["slots"]))


def _listed(slots: list[int]) -> str:
    if len(slots) == 1:
        return f"slot {slots[0]}"
    return "slots " + ", ".join(str(slot) for slot in slots[:-1]) + f" and {slots[-1]}"


def decide(text: str, names: dict[str, str]) -> Decision:
    readings: list[Reading] = []

    def inconclusive(reason: str, *, refuted: bool = False) -> Decision:
        return Decision(INCONCLUSIVE, refuted, reason, readings, None)

    body = _section(text)
    if isinstance(body, str):
        return inconclusive(body)
    for role in ("transparent", "opaque", "plain"):
        reading = _read(body, role, names[role])
        if isinstance(reading, str):
            return inconclusive(reading)
        readings.append(reading)
    transparent, opaque, plain = readings

    for reading, expected in ((transparent, True), (opaque, True), (plain, False)):
        if reading.has_override is None:
            return inconclusive(f"the override read failed for {reading.name}")
        if reading.has_override is not expected:
            has = "reports an" if reading.has_override else "reports no"
            return inconclusive(
                f"{reading.name}, the {reading.role} block, {has} component-level appearance "
                "override, so the recipe's control did not hold"
            )
    clear, solid = transparent.slots, opaque.slots
    if clear is None or solid is None:
        unread = transparent if clear is None else opaque
        return inconclusive(f"the appearance slots of {unread.name} could not be read")

    if len(clear) != len(solid):
        return inconclusive(
            f"the two overrides answer with {len(clear)} and {len(solid)} slots, which one build "
            "cannot do: probe again"
        )
    if len(solid) <= SLOT:
        return inconclusive(
            f"slot 7 refuted: the overrides answer with {len(solid)} slots, so there is no slot 7; "
            f"{REFUTED}",
            refuted=True,
        )
    for reading, read in ((transparent, clear), (opaque, solid)):
        if not 0 <= read[SLOT] <= 1:
            return inconclusive(
                f"{reading.name} reads {read[SLOT]:g} at slot 7, outside 0 to 1, which no "
                "transparency is, so the read went wrong: probe again, and if it reads so again, "
                "tell the owner"
            )
    differ = [
        slot
        for slot, (left, right) in enumerate(zip(clear, solid, strict=True))
        if not math.isclose(left, right, abs_tol=1e-6)
    ]
    shared = f"{solid[SLOT]:g}"
    if SLOT not in differ:
        both = f"the transparent and opaque overrides both read {shared} at slot 7"
        if not differ:
            return inconclusive(
                f"{both} and differ at no slot, so the transparency never reached "
                f"{transparent.name}: set it on the component row, not the part, a body or a "
                "face, until the block looks see-through (recipe step 4), and probe again"
            )
        if any(slot in COLOUR for slot in differ):
            return inconclusive(
                f"{both} and differ at {_listed(differ)}, the colour among them, so the recipe's "
                "control did not hold: give both the same colour by number, the transparency on "
                "the component row (recipe steps 3 and 4), and probe again"
            )
        return inconclusive(
            f"slot 7 refuted: {both}, the same colour, and differ only at {_listed(differ)}; "
            f"{REFUTED}",
            refuted=True,
        )
    if differ != [SLOT]:
        return inconclusive(
            f"the two overrides differ at {_listed(differ)}, not at slot 7 alone: give both the "
            "same appearance but the transparent amount (recipe steps 3 and 4) and probe again"
        )
    seen = (
        f"the opaque override reads {shared} at slot 7 and the transparent one {clear[SLOT]:g}, "
        "and they differ nowhere else"
    )
    for value, polarity in ((0.0, ZERO_IS_OPAQUE), (1.0, ONE_IS_OPAQUE)):
        if math.isclose(solid[SLOT], value, abs_tol=1e-9):
            return Decision(
                polarity,
                False,
                f"{seen}: {value:g} means opaque",
                readings,
                f'set TRANSPARENCY_POLARITY = "{polarity}" in '
                "reviewer/src/swreview/checks/standards/assembly.py, copy "
                f"{GOLDENS}/{polarity}/*.yml over reviewer/tests/golden/test_golden/, and make "
                "the edits 006 research R11 lists",
            )
    return inconclusive(f"{seen}, but {shared} is neither 0 nor 1")
