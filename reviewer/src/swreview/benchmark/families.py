"""The judgement families of a benchmark set, data only (feature 014 `contracts/cases.md` 8).

The one family rule: the case generator's spec check (`generator.md` 10, row 3), the
committed-set test and `swreview benchmark set-summary` all read `family_of`, and none restates
it. A family is a check family, never a producer (research D14.8, owner decision 16A).

The standard library only, so the generator imports it without loading the runner, the agent,
a check or the key's loader (`generator.md` 9; plan decision RF-48).
"""

from __future__ import annotations

from typing import Literal

Family = Literal["fastener", "fit_and_stack", "interference", "drawing", "part_role", "other"]
"""The summary's rows, in its order. `part_role` is reached by no check: the summary counts the
part-roles question's count rule there, a rule that names none (`cases.md` 8)."""

_FAMILY_OF_FIRST_SEGMENT: dict[str, Family] = {
    "fastener": "fastener",
    "hole": "fastener",
    "fit": "fit_and_stack",
    "stack": "fit_and_stack",
    "interference": "interference",
    "drawing": "drawing",
}
"""The judgement families' first segments; every other first segment is `other`."""


def family_of(check: str) -> Family:
    """The family of an exact check id or an `x.*` family, read from its first segment.

    The segment is compared whole, so `fasteners.x` is `other`, and only the first one counts,
    so `standards.drawing.revision_matches` is `other` too: modelling practice, hygiene,
    standards and every check not named above.
    """
    return _FAMILY_OF_FIRST_SEGMENT.get(check.split(".", 1)[0], "other")


ANCHOR_FAMILY: dict[str, Family] = {
    "R-1": "part_role",
    "R-2": "drawing",
    "R-3": "fit_and_stack",
    "R-4": "interference",
    "R-5": "interference",
    "R-6": "fastener",
    "R-7": "other",
    "R-8": "other",
    "AF-1": "fastener",
    "AF-2": "fastener",
    "AF-3": "interference",
}
"""The anchors R-1 to R-8 and the analyst-found AF-1 to AF-3, each to the family the summary
counts it in (`cases.md` 8's anchors column)."""

FAMILY_LABELS: dict[Family, str] = {
    "fastener": "fastener",
    "fit_and_stack": "fit and axial stack",
    "interference": "interference",
    "drawing": "drawing",
    "part_role": "part role",
    "other": "other",
}
"""Every family's printed label, once, in the summary's row order."""
