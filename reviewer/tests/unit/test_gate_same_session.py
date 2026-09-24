"""The gate's pre-run is the same session lever 5's is, one call wider (T047, FR-027, FR-032).

`test_prerun_same_session.py` makes the statement lever 5 rests on: the pre-run calls the
same tool functions through the same `ToolDispatch`, so every check produces a real
`InvestigationStep`, real findings through `ToolContext.record_finding`, real coverage and
real `tool.started` / `tool.finished` events. Lever 11 adds a fifth call - `check_standards`,
when the context carries a standards run - and that statement has to survive it, so this
module makes it again with the gate on and with the widest plan the gate can produce.

Three things are asserted here that the lever 5 module has no reason to:

- **`planned_calls` reads the context, not a parameter.** `ToolRegistry._offered` adds
  `check_standards` only when the context carries a standards run, so the plan asks the same
  question the dispatch asks (`standards_run(context)`) rather than being told the answer.
  If the two ever disagree, the pre-run calls a tool that was never offered, or offers one it
  never plans.
- **Lever 4 still filters.** `planned_calls` drops a withheld tool, and it must keep doing
  so with the gate on: calling it would write the tier's refusal against a request the model
  never made, and the tier's own sentence goes into the digest instead.
- **No new event type.** FR-032. The gate adds a message, not a protocol; the types of
  `chat-events.schema.json` (fifteen since feature 011 T092) are what a gated run emits and
  nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swreview.agent.settings import EfficiencySettings
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import CHECK_TOOL
from swreview.checks.standards.traversal import graded_documents
from swreview.prerun import PRERUN_CHECK_PREFIX, PRERUN_TOOLS, planned_calls
from swreview.report.session import ReviewSession
from swreview.tools.context import context_for
from swreview.tools.registry import RMS_TIER_TOOLS, ToolRegistry
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
from tests.support.contracts import load_any_contract
from tests.support.prerun import (
    GATE_ON,
    MODEL_DRIVEN_CALLS,
    STANDARDS_PROFILE,
    prerun_package,
    review,
    standards_prerun_package,
)
from tests.support.tiers import full_assembly_without_tree

SCHEMA_EVENT_TYPES: frozenset[str] = frozenset(
    load_any_contract("chat-events.schema.json")["properties"]["type"]["enum"]
)
"""The event types the contract carries, read from the contract (FR-032)."""

GATE_AND_TIERS = EfficiencySettings(procedural_gate=True, tool_tiers=True)
"""Levers 11 and 4 together. `efficiency_from_levers` refuses 11 with 5 and 11 with 7, and
nothing else, so this pair is a configuration a benchmark arm can really hold."""


def events_of(tmp_path: Any, out: str) -> list[dict[str, Any]]:
    lines = (Path(tmp_path) / out / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def bodies_of(tmp_path: Any, out: str, event_type: str) -> list[dict[str, Any]]:
    return [event["body"] for event in events_of(tmp_path, out) if event["type"] == event_type]


def with_a_standards_run(package: Any = None) -> tuple[Any, Any]:
    """A context carrying a standards run, and the dispatch built over it."""
    context = context_for(package if package is not None else standards_prerun_package())
    profile = load_profile(STANDARDS_PROFILE)
    attach_standards_run(
        context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
    )
    return context, ToolRegistry().dispatch(context)


# --- 1. what the gate plans ------------------------------------------------------------------


def test_the_plan_is_lever_5s_list_when_the_context_carries_no_standards_run() -> None:
    context = context_for(prerun_package())
    dispatch = ToolRegistry().dispatch(context)

    assert planned_calls(context, dispatch) == tuple(
        (call.name, dict(call.arguments)) for call in MODEL_DRIVEN_CALLS
    )


def test_the_plan_gains_check_standards_when_the_context_carries_one() -> None:
    """The same attribute `_offered` reads, so the plan and the tool array cannot disagree."""
    context, dispatch = with_a_standards_run()

    plan = planned_calls(context, dispatch)

    assert plan == (
        *((call.name, dict(call.arguments)) for call in MODEL_DRIVEN_CALLS),
        (CHECK_TOOL, {}),
    )
    assert CHECK_TOOL in [tool.name for tool in dispatch.tools]


def test_check_standards_is_planned_last() -> None:
    """After the four that were there before it, so a run with the standards half switched
    off is a prefix of one with it on rather than a different ordering."""
    context, dispatch = with_a_standards_run()

    plan = planned_calls(context, dispatch)

    assert plan[-1] == (CHECK_TOOL, {})
    assert plan[:-1] == tuple((call.name, dict(call.arguments)) for call in MODEL_DRIVEN_CALLS)


def test_a_withheld_tool_is_still_dropped_from_the_plan(tmp_path: Any) -> None:
    """Lever 4, unchanged by lever 11: a tool the tier withheld is not called here."""
    package = full_assembly_without_tree()
    context = context_for(package)
    dispatch = ToolRegistry().dispatch(context, efficiency=GATE_AND_TIERS)

    planned = [name for name, _ in planned_calls(context, dispatch)]

    assert [tool.name for tool in dispatch.withheld] == list(RMS_TIER_TOOLS)
    assert not set(planned) & set(RMS_TIER_TOOLS)


def test_the_gate_run_with_a_tier_records_no_step_for_a_withheld_tool(tmp_path: Any) -> None:
    """And the tier's own sentence is what the brief carries for each one, written as the
    `coverage.prerun.<tool>` items `not_evaluated_families` makes of them."""
    session = review(
        tmp_path, "tiered", package=full_assembly_without_tree(), efficiency=GATE_AND_TIERS
    )

    withheld_prerun_tools = [name for name in RMS_TIER_TOOLS if name in PRERUN_TOOLS]

    assert not {step.tool for step in session.steps} & set(RMS_TIER_TOOLS)
    assert len(withheld_prerun_tools) == 3, "the tier withholds three of the four pre-run tools"
    written = {item.check for item in session.coverage.skipped}
    assert {f"{PRERUN_CHECK_PREFIX}{name}" for name in withheld_prerun_tools} <= written


# --- 2. real steps, real events, real provenance ---------------------------------------------


def gated(tmp_path: Any, out: str = "gated") -> ReviewSession:
    return review(tmp_path, out, efficiency=GATE_ON)


def test_every_gate_call_records_one_real_investigation_step(tmp_path: Any) -> None:
    session = gated(tmp_path)

    assert [step.tool for step in session.steps] == [call.name for call in MODEL_DRIVEN_CALLS]
    assert [step.index for step in session.steps] == list(range(len(session.steps)))
    assert all(step.status == "ok" for step in session.steps)


def test_every_gate_finding_cites_a_step_of_this_session(tmp_path: Any) -> None:
    session = gated(tmp_path)

    cited = [step_id for finding in session.findings for step_id in finding.tool_result_ids]
    assert cited
    assert all(0 <= step_id < len(session.steps) for step_id in cited)


def test_the_pane_sees_the_gates_pre_run_happening(tmp_path: Any) -> None:
    session = gated(tmp_path)

    started = bodies_of(tmp_path, "gated", "tool.started")
    finished = bodies_of(tmp_path, "gated", "tool.finished")
    assert [body["tool"] for body in started] == [step.tool for step in session.steps]
    assert [body["step_index"] for body in started] == [step.index for step in session.steps]
    assert [body["step_index"] for body in finished] == [step.index for step in session.steps]
    assert all(body["status"] == "ok" for body in finished)


def test_the_gate_writes_a_finding_event_and_a_coverage_event_of_its_own(
    tmp_path: Any,
) -> None:
    """The two the pre-run produces through the tool layer rather than through a turn."""
    session = gated(tmp_path)

    findings = bodies_of(tmp_path, "gated", "finding")
    coverage = bodies_of(tmp_path, "gated", "coverage")
    assert [body["id"] for body in findings] == [finding.id for finding in session.findings]
    skipped = [body["item"]["check"] for body in coverage if body["bucket"] == "skipped"]
    assert [check for check in skipped if check.startswith(PRERUN_CHECK_PREFIX)]


def test_the_stream_still_opens_with_session_started(tmp_path: Any) -> None:
    """The one implicit ordering rule `events.jsonl` has ever had; the gate runs during
    setup, after that event, exactly as lever 5's pre-run does."""
    gated(tmp_path)

    assert events_of(tmp_path, "gated")[0]["type"] == "session.started"


# --- 3. no new event type ---------------------------------------------------------------------


def test_a_gated_run_emits_no_event_type_outside_the_fifteen(tmp_path: Any) -> None:
    """FR-032. The gate is a message, not a protocol.

    Edited deliberately on 2026-09-23 (feature 011 T092): the contract's fifteenth type,
    `coverage.withdrawn`, is the coverage a restating check withdrew - not the gate's - and the
    gate still adds none."""
    gated(tmp_path)

    emitted = {event["type"] for event in events_of(tmp_path, "gated")}

    assert emitted
    assert emitted <= SCHEMA_EVENT_TYPES
    assert len(SCHEMA_EVENT_TYPES) == 15
