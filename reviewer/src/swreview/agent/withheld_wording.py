"""What the model is told once checks first has taken tools off the array (lever 13).

Feature 008 FR-030, `contracts/checks-first.md` section 7, research R2.53. When the pre-run
has run a check tool to completion the tool leaves the array, and every sentence the model
is sent that asks it to call that tool has to go with it. A search of everything a review
sends found three, and they are this module's table: step 3 of `prompts/system_v1.md` lists
`check_interference_group` among the check tools to run; step 4 is a paragraph on calling
the three RMS tools; and the `modeling.resilience` checklist item, which the model reads in
the system prompt and from `get_review_checklist`, ends "Run check_rms_part, ...".

**Exact text, replaced only when every tool an entry names is withheld.** An entry is the
sentence as the source holds it and the sentence that replaces it; a test proves each old
sentence occurs exactly once where it is expected, so a later edit to the prompt or the
checklist that stops an entry matching fails there rather than quietly leaving a withheld
tool's name in front of the model. At run time a sentence that no longer matches is left as
it is: a review is never lost over wording. The RMS entries name all three tools because
lever 13 withholds them together (`prerun.withheld_tools`).

With nothing withheld - the lever off, checks first off, or a pre-run that completed nothing
- every text is returned unchanged, byte for byte.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace

from swreview.agent.checklist import Checklist
from swreview.prerun import INTERFERENCE_TOOL, RMS_PRERUN_TOOLS

__all__ = [
    "CHECKLIST_REWORDINGS",
    "SYSTEM_PROMPT_REWORDINGS",
    "Rewording",
    "reworded",
    "reworded_checklist",
]


@dataclass(frozen=True)
class Rewording:
    """One sentence that asks for a tool, and what it says once the tool is withheld."""

    withheld: tuple[str, ...]
    """The tools this sentence asks for; it is replaced only when every one is withheld."""

    old: str
    """The sentence exactly as its source holds it."""

    new: str
    """What replaces it. Names no withheld tool."""


SYSTEM_PROMPT_REWORDINGS: tuple[Rewording, ...] = (
    Rewording(
        withheld=(INTERFERENCE_TOOL,),
        old="`check_hole_alignment`, `check_interference_group`)",
        new="`check_hole_alignment`)",
    ),
    Rewording(
        withheld=RMS_PRERUN_TOOLS,
        old=(
            "4. Grade the modelling method with the three RMS check tools: `check_rms_part` for "
            "the\n"
            "   part feature trees (no argument grades every part document in one call, which "
            "is what\n"
            "   you normally want), `check_rms_assembly` for the root assembly's mates and "
            "first\n"
            "   component, and `check_rms_equations` for the global variables. They are "
            "deterministic\n"
            "   and read only the extracted tree, so run them before you reason about the "
            "model's\n"
            "   structure rather than judging a tree by eye. Call each one once: a second call "
            "replaces\n"
            "   its earlier coverage but *appends* its findings, so re-grading a document you "
            "already\n"
            "   graded records every one of its problems twice. Together they close out\n"
            "   `modeling.resilience`; do not mark that item covered by hand while a check tool "
            "could\n"
            "   answer it."
        ),
        new=(
            "4. The modelling method was graded before your first turn: checks first ran the "
            "three RMS\n"
            "   checks over every document, and the opening message gives their counts. "
            "Together they\n"
            "   close out `modeling.resilience`; do not mark that item covered by hand."
        ),
    ),
)
"""Steps 3 and 4 of `prompts/system_v1.md`, wrapped as the file wraps them."""

CHECKLIST_REWORDINGS: tuple[Rewording, ...] = (
    Rewording(
        withheld=RMS_PRERUN_TOOLS,
        old="Run check_rms_part, check_rms_assembly and check_rms_equations.",
        new="Checks first ran the three RMS checks before the first turn.",
    ),
)
"""The `modeling.resilience` item's last instruction, as `load_checklist` normalizes it."""


def reworded(text: str, withheld: Collection[str], rewordings: Sequence[Rewording]) -> str:
    """`text` with every entry whose tools are all withheld replaced; unchanged otherwise."""
    for entry in rewordings:
        if set(entry.withheld) <= set(withheld):
            text = text.replace(entry.old, entry.new)
    return text


def reworded_checklist(checklist: Checklist, withheld: Collection[str]) -> Checklist:
    """`checklist` with each item's description reworded for `withheld`.

    Ids, titles, prefixes and the version never change - finalization and the coverage stop
    read those - and with nothing to reword the same object comes back.
    """
    items = tuple(
        replace(item, description=reworded(item.description, withheld, CHECKLIST_REWORDINGS))
        for item in checklist.items
    )
    if items == checklist.items:
        return checklist
    return replace(checklist, items=items)
