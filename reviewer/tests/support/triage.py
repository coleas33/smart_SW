"""The triage tally a payload carries (feature 002 FR-031, cycle 7), written out by hand.

The backend counts the flagged findings by outcome, those with none and the passes judged wrong
once (`report/summary.triage_tally`), and sends the result beside the review summary, in the
disposition route's reply and in the `disposition` and `disposition.cleared` events, and beside
each `finding` event's finding (cycle 13), null there while none is recorded. A test pins
what it sends with `tally_body`, which states the counts and `report.md`'s two lines in the words
file's words without calling the function under test.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def tally_body(
    *,
    new: int = 0,
    known: int = 0,
    wrong: int = 0,
    not_worth: int = 0,
    not_recorded: int = 0,
    misses: int = 0,
) -> dict[str, Any]:
    """`triage_tally` as JSON: the flagged findings by outcome, those with none, the passes judged
    wrong, and the two lines `report.md` prints for them."""
    return {
        "counts": {
            "new_and_real": new,
            "already_known": known,
            "wrong": wrong,
            "not_worth_flagging": not_worth,
        },
        "not_recorded": not_recorded,
        "misses": misses,
        "text": (
            f"By triage: new and real: {new}, real but already known: {known}, wrong: {wrong}, "
            f"true but not worth flagging: {not_worth}, not recorded: {not_recorded}"
        ),
        "misses_text": f"Passes judged wrong (misses): {misses}",
    }


def finding_alone(body: Mapping[str, Any]) -> dict[str, Any]:
    """A `finding` event's body without the `triage_tally` it names beside the finding (002 cycle
    13; null while no finding records a triage): the finding, as a session and a snapshot hold it
    and as the scorer reads it."""
    return {key: value for key, value in body.items() if key != "triage_tally"}
