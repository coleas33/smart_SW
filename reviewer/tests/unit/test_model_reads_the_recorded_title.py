"""What the model reads of a check tool's result does not move with the display title (feature
009 T061, the owner's decision 2A of 2026-09-23, research R2.28).

A finding has two titles. `Finding.title` is the recorded one - the first sentence of `observed`,
cut at 80 characters with an ellipsis, component ids as written - and it is in every check tool's
result, so the model reads it on every round and feature 008's replay prices it. The whole, named
title a person reads is built by `report/titles.display_title` only where a person reads it: the
pane's bodies and `report.md`. This module proves the first did not move when the second arrived.

Four representative tools are called, in one session, through the real dispatch on
`tests/support/prerun.prerun_package` - an assembly whose parts are named (`housing-1`,
`housing-2`): the part check (a title cut at 80), the equations check, the interference check (a
title that is cut *and* names both parts by id) and a drawing finding (the other title funnel,
`tools/session.py`). The text the model reads of each result is pinned by its SHA-256, twice:
every setting off (`tool_result_text(payload)`) and the pane's slim view
(`tool_result_text(view, compact=True)`). The pins were taken at `d47a91f`, before
`report/titles.py` existed.

**Regenerated, never transcribed.** `python -m tests.unit.test_model_reads_the_recorded_title
--write` (from `reviewer/`) prints `PINS` from this same computation. A deliberate change to one of
these tools' results regenerates them in a commit of its own; a change that comes with a title a
person reads is exactly what decision 2A rules out, and the second test says which title moved.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping
from functools import cache
from typing import Any

import pytest

from swreview.agent.providers import tool_result_text
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE, ModelViewSettings
from swreview.report.names import COMPONENT_ID, component_names
from swreview.tools.context import context_for
from swreview.tools.recording import TITLE_LENGTH, title_from
from swreview.tools.registry import ToolRegistry
from tests.support.prerun import GROUP_KEY, PART_DOCUMENT, prerun_package

WRITE_COMMAND = "python -m tests.unit.test_model_reads_the_recorded_title --write"

DRAWING_FINDING: dict[str, Any] = {
    "document_id": PART_DOCUMENT,
    "sheet": "Sheet1",
    "observed": (
        "The drawing of cmp:0002 calls out the tapped hole without the usable thread depth, so "
        "the engagement of the screw cannot be judged from the sheet. Nothing else is missing."
    ),
    "requirement": "A tapped hole callout states the usable thread depth",
    "source_refs": [{"document_id": PART_DOCUMENT, "sheet": "Sheet1"}],
    "status": "suspected",
    "recommended_action": "Add the usable thread depth to the hole callout",
}
"""A drawing finding whose first sentence is longer than 80 characters and names `housing-1` by
its id, so the second title funnel is pinned on both counts."""

CALLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("check_rms_part", {}),
    ("check_rms_equations", {}),
    ("check_interference_group", {"group_key": GROUP_KEY}),
    ("record_drawing_finding", DRAWING_FINDING),
)
"""In the order they are called: the finding ids run on across the four, so the order is part of
what is pinned."""

VIEWS: dict[str, ModelViewSettings] = {"full": MODEL_VIEW_OFF, "slim": MODEL_VIEW_PANE}
"""Every setting off - the command line's and `benchmark run`'s default - and the pane's view."""

ELLIPSIS = "…"
"""What `title_from` ends a cut title with."""

PINS: dict[tuple[str, str], str] = {
    ("full", "check_rms_part"): (
        "180d126290a8d1571af25fd936add2ffce4513b2cdc06d73eecae63bb09d02cd"
    ),
    ("full", "check_rms_equations"): (
        "3bc7a6cd67c6261087f75a581b49da01909bf7e4d94c4ee28f7a2a1685e03dfd"
    ),
    ("full", "check_interference_group"): (
        "155517df6fc42ea9a55db986f6f937d63260d358d3602b73018ca4cbf9f9c0c6"
    ),
    ("full", "record_drawing_finding"): (
        "8190dbc601f12186e38de748182d42e8d733d8a0099106cd61dedcf108cbf9ee"
    ),
    ("slim", "check_rms_part"): (
        "15acabea014b3e434cbfd613064ed88ac0d168488ccc012a5833a26bb0be7b85"
    ),
    ("slim", "check_rms_equations"): (
        "8657495cde02fd3cb1d831744a7279a21486f8711a51f750b48dfa8fae936d89"
    ),
    ("slim", "check_interference_group"): (
        "69131f01a82ed9a3541c989e2ba47fec15ec24f73245e42330b26d9c710f5cd5"
    ),
    ("slim", "record_drawing_finding"): (
        "c14b9135c12a23bacda20a5c93d1a59d40d1dde5a59afe09081336a347efb1f7"
    ),
}
"""SHA-256 of the UTF-8 text the model reads of each call, taken at `d47a91f`."""


@cache
def payloads(view: str) -> dict[str, tuple[dict[str, Any], dict[str, Any] | None]]:
    """`{tool: (payload, view)}` of the four calls in one session, under one model view."""
    tools = ToolRegistry().dispatch(context_for(prerun_package()), model_view=VIEWS[view])
    results = {}
    for name, arguments in CALLS:
        result = tools.call(name, arguments)
        assert not result.is_error, f"{name} failed: {result.payload}"
        results[name] = (result.payload, result.view)
    return results


def read_by_the_model(view: str, name: str) -> str:
    """The one serialization the adapters send and the replay prices (`tool_result_text`)."""
    payload, slim = payloads(view)[name]
    if VIEWS[view].payload_slimming:
        assert slim is not None, f"{name} has no slim view"
        return tool_result_text(slim, compact=True)
    return tool_result_text(payload)


def computed_pins() -> dict[tuple[str, str], str]:
    return {
        (view, name): hashlib.sha256(read_by_the_model(view, name).encode("utf-8")).hexdigest()
        for view in VIEWS
        for name, _ in CALLS
    }


def findings_of(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The findings a result names: a check's `findings`, or a drawing finding's `finding`."""
    if isinstance(payload.get("findings"), list):
        return list(payload["findings"])
    return [payload["finding"]] if isinstance(payload.get("finding"), dict) else []


def titled_rows(view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The finding rows a slim view names: a check digest's `rows`, or the one finding."""
    rows = view.get("rows")
    return list(rows) if isinstance(rows, list) else findings_of(view)


def test_the_bytes_the_model_reads_are_the_ones_it_read_before_the_display_title() -> None:
    assert computed_pins() == PINS, f"regenerate only for a deliberate change: {WRITE_COMMAND}"


@pytest.mark.parametrize("view", VIEWS)
def test_every_title_the_model_reads_is_the_recorded_one(view: str) -> None:
    """The readable half of the pin: a title that moved is named here, not only a digest."""
    for name, _ in CALLS:
        payload, slim = payloads(view)[name]
        recorded = {finding["id"]: finding for finding in findings_of(payload)}
        for finding in recorded.values():
            assert finding["title"] == title_from(finding["observed"]), (name, finding["id"])
        for row in titled_rows(slim or {}):
            assert row["title"] == recorded[row["id"]]["title"], (name, row["id"])


def test_the_pinned_results_hold_a_cut_title_and_a_named_part_by_its_id() -> None:
    """Otherwise the pin would prove nothing about the two things the display title changes."""
    names = component_names(prerun_package())
    titles = [
        finding["title"] for name, _ in CALLS for finding in findings_of(payloads("full")[name][0])
    ]

    cut = [title for title in titles if title.endswith(ELLIPSIS)]
    named = [
        title
        for title in titles
        if any(names.get(component, "").strip() for component in COMPONENT_ID.findall(title))
    ]
    assert all(len(title) <= TITLE_LENGTH for title in cut)
    assert len(cut) >= 3, "the part check, the interference check and the drawing finding"
    assert len(named) >= 2, "the interference check and the drawing finding"


def main(argv: list[str]) -> int:
    if argv != ["--write"]:
        print(f"usage: {WRITE_COMMAND}", file=sys.stderr)
        return 2
    print("PINS: dict[tuple[str, str], str] = {")
    for (view, name), value in computed_pins().items():
        print(f'    ("{view}", "{name}"): (\n        "{value}"\n    ),')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
