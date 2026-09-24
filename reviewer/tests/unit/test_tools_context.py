"""Unit tests for the model a tool context's session records (T023).

`tools/context.py` no longer holds a model constant: feature 001's `DEFAULT_MODEL` there
is what wrote a retired vendor's id into `session.json`, and the id a session records when
nobody chose one now comes from `agent/settings.py` (FR-026). Every `check` subcommand,
every tool test and every golden fixture builds a context without passing a model, so that
fallback is what most session records in this product are stamped with - and no other test
exercises it, because the CLI review path always passes a model explicitly.

The expected value is imported rather than spelled out, so these assertions track the
single source of truth instead of restating `gpt-5.6` in a fourth place.

The second half of the module covers the two things the RMS report layer asks a context
for (T017): `current_step_id`, the step index a finding cites as its evidence, and
`replace_coverage`, which rewrites an aggregated coverage item instead of duplicating it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.checklist import load_checklist
from swreview.agent.settings import DEFAULT_PROVIDER, default_model
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, CoverageScope
from swreview.tools.context import (
    ToolContext,
    build_context,
    context_for,
    current_context,
    new_session,
)
from swreview.tools.query import ToolResult
from swreview.tools.registry import ToolRegistry

MakePackage = Callable[..., EvidencePackage]

CHOSEN_MODEL = "gemini-3.5-flash"
"""Any id that is not the default: these tests assert *which* id wins, not what it is."""


def test_new_session_without_a_model_records_the_default_providers_default(
    make_package: MakePackage,
) -> None:
    assert new_session(make_package()).model == default_model(DEFAULT_PROVIDER)


def test_new_session_with_a_model_records_that_model(make_package: MakePackage) -> None:
    assert new_session(make_package(), CHOSEN_MODEL).model == CHOSEN_MODEL


def test_build_context_without_a_model_records_the_default_providers_default(
    make_package: MakePackage, tmp_path: Path
) -> None:
    loaded = LoadedPackage(package=make_package(), base_dir=tmp_path)

    context = build_context(loaded)

    assert context.session is not None
    assert context.session.model == default_model(DEFAULT_PROVIDER)


def test_build_context_with_a_model_records_that_model(
    make_package: MakePackage, tmp_path: Path
) -> None:
    loaded = LoadedPackage(package=make_package(), base_dir=tmp_path)

    context = build_context(loaded, model=CHOSEN_MODEL)

    assert context.session is not None
    assert context.session.model == CHOSEN_MODEL


def test_context_for_without_a_model_records_the_default_providers_default(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())

    assert context.session is not None
    assert context.session.model == default_model(DEFAULT_PROVIDER)


def test_context_for_with_a_model_records_that_model(make_package: MakePackage) -> None:
    context = context_for(make_package(), model=CHOSEN_MODEL)

    assert context.session is not None
    assert context.session.model == CHOSEN_MODEL


# --- the step id a finding cites, and coverage that is rewritten (T017) ----------------


def peek_step_id() -> ToolResult:
    """Report the step id the tool call in flight will be recorded under.

    A curated tool with a schema, so the assertion below runs through the real recording
    path - `RecordedTool.call` binding the context, then `SessionSink` appending the step -
    rather than against a hand-appended step.
    """
    return {"step_id": current_context().current_step_id}


def coverage_item(check: str, reason: str) -> CoverageItem:
    return CoverageItem(check=check, scope=CoverageScope(), reason=reason, error=None)


def context_with_events(
    make_package: MakePackage, tmp_path: Path
) -> tuple[ToolContext, list[tuple[str, dict[str, Any]]]]:
    """A context whose emitted events are collected, so "announced once" is assertable."""
    events: list[tuple[str, dict[str, Any]]] = []
    context = build_context(
        LoadedPackage(package=make_package(), base_dir=tmp_path),
        emit=lambda event_type, body: events.append((event_type, dict(body))),
    )
    return context, events


def test_current_step_id_is_the_index_the_call_in_flight_is_recorded_under(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())
    session = context.session
    assert session is not None
    dispatch = ToolRegistry(functions=(peek_step_id,), bridge_functions=()).dispatch(context)

    assert context.current_step_id == 0
    first = dispatch.call("peek_step_id", {})
    second = dispatch.call("peek_step_id", {})

    assert [first.payload["step_id"], second.payload["step_id"]] == [0, 1]
    assert [step.index for step in session.steps] == [0, 1]
    assert context.current_step_id == len(session.steps) == 2


def test_current_step_id_without_a_session_is_a_caller_mistake(
    make_package: MakePackage, tmp_path: Path
) -> None:
    context = ToolContext(
        package=LoadedPackage(package=make_package(), base_dir=tmp_path),
        session=None,
        checklist=load_checklist(),
    )

    with pytest.raises(ValueError, match="review session"):
        context.current_step_id  # noqa: B018 - the property is what raises


def test_replace_coverage_replaces_that_check_in_that_bucket_only(
    make_package: MakePackage, tmp_path: Path
) -> None:
    context, _ = context_with_events(make_package, tmp_path)
    session = context.session
    assert session is not None
    context.record_coverage("checked", coverage_item("rms.part.grouping", "first pass"))
    context.record_coverage("checked", coverage_item("rms.part.holes_last", "untouched"))
    context.record_coverage("unresolved", coverage_item("rms.part.grouping", "other bucket"))

    context.replace_coverage(
        "rms.part.grouping", "checked", coverage_item("rms.part.grouping", "second pass")
    )

    assert [(item.check, item.reason) for item in session.coverage.checked] == [
        ("rms.part.holes_last", "untouched"),
        ("rms.part.grouping", "second pass"),
    ]
    assert [(item.check, item.reason) for item in session.coverage.unresolved] == [
        ("rms.part.grouping", "other bucket")
    ]


def test_replace_coverage_appends_when_that_check_is_not_in_the_bucket_yet(
    make_package: MakePackage, tmp_path: Path
) -> None:
    context, _ = context_with_events(make_package, tmp_path)
    session = context.session
    assert session is not None

    context.replace_coverage(
        "rms.part.grouping", "checked", coverage_item("rms.part.grouping", "first pass")
    )

    assert [(item.check, item.reason) for item in session.coverage.checked] == [
        ("rms.part.grouping", "first pass")
    ]


def test_replace_coverage_emits_the_withdrawal_then_one_coverage_event(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """Edited deliberately on 2026-09-23 (feature 011 T092): the dropped item is announced too,
    as `coverage.withdrawn` before the restated item's `coverage`, so the pane drops it."""
    context, events = context_with_events(make_package, tmp_path)
    context.record_coverage("checked", coverage_item("rms.part.grouping", "first pass"))
    events.clear()

    context.replace_coverage(
        "rms.part.grouping", "checked", coverage_item("rms.part.grouping", "second pass")
    )

    assert len(events) == 2
    assert events[0] == (
        "coverage.withdrawn", {"checks": ["rms.part.grouping"], "buckets": ["checked"]}
    )
    event_type, body = events[1]
    assert event_type == "coverage"
    assert body["bucket"] == "checked"
    assert body["item"]["check"] == "rms.part.grouping"
    assert body["item"]["reason"] == "second pass"
