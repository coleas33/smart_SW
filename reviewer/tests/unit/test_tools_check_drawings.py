"""`check_drawings`, the drawing family and its place in the pre-run (feature 011 T047).

`contracts/questions.md` sections 1, 2, 5 and 6 are normative. The drawing family is offered
only when the package carries drawing evidence - a drawing record or a candidate - exactly as the
standards, bridge and remodel families are offered on their conditions, and it is in none of
`TOOL_FUNCTIONS`, the MCP list and the terminal profile. `check_drawings()` takes no argument,
records the coverage and the questions `checks/drawing_context.py` computes, and returns counts;
the pre-run plans it after every `CODE_FIRST_CHECKS` name and before `check_standards`, feature
008's re-call guard keys it `(tool,)`, and lever 13 withholds it once the pre-run ran it. With no
drawing evidence the plan, the digest and the tool array are what they were (FR-037).
"""

from __future__ import annotations

import inspect
import shutil
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.agent.settings import EfficiencySettings
from swreview.checks.drawing_context import CANDIDATE_CONFIRM
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import CHECK_TOOL
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.mcp.server import MCP_BRIDGE_TOOL_FUNCTIONS, MCP_TOOL_FUNCTIONS
from swreview.prerun import (
    ALREADY_RUN,
    PrerunCall,
    PrerunGuard,
    planned_calls,
    repeat_key,
)
from swreview.report.summary import review_ranking
from swreview.tools import checks_mechanical, registry
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.drawings import DRAWINGS_TOOL, check_drawings, drawing_evidence
from swreview.tools.registry import (
    TOOL_FUNCTIONS,
    ToolDispatch,
    ToolRegistry,
    WithheldTool,
    drawing_tools,
)
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
from tests.support.prerun import ON, STANDARDS_PROFILE, prerun_package
from tests.unit.test_mcp_server import contract_enabled_tools

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"


def fixture(name: str) -> EvidencePackage:
    return load_package(FIXTURES / name).package


def recorded(package: EvidencePackage) -> tuple[ToolContext, dict[str, Any]]:
    context = context_for(package)
    with use_context(context):
        return context, check_drawings()


def names(functions: Any) -> list[str]:
    return [function.__name__ for function in functions]


def played(tmp_path: Path, name: str, efficiency: EfficiencySettings = ON) -> Any:
    """A scripted review of a committed drawing fixture, its pre-run played."""
    folder = tmp_path / name
    shutil.copytree(FIXTURES / name, folder)
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=efficiency,
    )
    run.start()
    return run


# --- 1. the tool --------------------------------------------------------------------------------


def test_check_drawings_takes_no_argument() -> None:
    assert inspect.signature(check_drawings).parameters == {}
    assert DRAWINGS_TOOL == "check_drawings"


def test_check_drawings_returns_the_counts() -> None:
    _, result = recorded(fixture("plate-drawing"))

    assert result == {
        "status": "recorded",
        "drawings": 2,
        "candidates": 1,
        "questions": 1,
        "findings": 0,
        "finding_ids": [],
        "coverage": {"checked": 1, "skipped": 4, "unresolved": 0},
    }


def test_it_records_one_drawing_context_item_per_reviewed_document() -> None:
    context, _ = recorded(fixture("plate-drawing"))
    coverage = context.require_session().coverage

    checked = [item for item in coverage.checked if item.check == "drawing.context"]
    skipped = [item for item in coverage.skipped if item.check == "drawing.context"]
    assert [item.scope.document_ids for item in checked] == [["doc:0002"]]
    assert [item.scope.document_ids[0] for item in skipped] == [
        "doc:0001", "doc:0003", "doc:0004", "doc:0005"
    ]


def test_the_questions_are_evidence_requests_the_summary_shows() -> None:
    context, _ = recorded(fixture("plate-drawing"))
    session = context.require_session()

    [request] = session.evidence_requests
    assert (request.id, request.status) == ("ER-001", "open")
    assert request.options[0] == CANDIDATE_CONFIRM
    assert request.blocks == "drawing.manufacturing_inputs"
    assert request.entity_ids == ["doc:0003"]
    summary = review_ranking(session, context.ir).summary
    [shown] = summary.questions.items
    assert shown.id == "ER-001" and shown.question == request.question
    assert shown.options == request.options
    assert [about.name for about in shown.about] == ["FICT-TULMSORN-3002.SLDPRT"]


def test_the_governing_question_reaches_the_session_on_the_assembly_fixture() -> None:
    context, result = recorded(fixture("assembly-drawings"))

    [request] = context.require_session().evidence_requests
    assert result["questions"] == 1 and result["candidates"] == 0 and result["drawings"] == 4
    assert request.options[-1] == "They all apply" and request.blocks is None


def test_calling_it_again_asks_nothing_twice_and_restates_the_coverage() -> None:
    """Even with no re-call guard in front of it (checks first off)."""
    context, first = recorded(fixture("plate-drawing"))
    with use_context(context):
        second = check_drawings()
    session = context.require_session()

    assert second == first
    assert len(session.evidence_requests) == 1
    items = [
        item
        for bucket in ("checked", "skipped", "unresolved")
        for item in getattr(session.coverage, bucket)
        if item.check == "drawing.context"
    ]
    assert len(items) == 5


def test_a_package_with_no_drawing_evidence_records_skipped_coverage_only() -> None:
    context, result = recorded(prerun_package())

    assert result["drawings"] == 0 and result["candidates"] == 0 and result["questions"] == 0
    assert context.require_session().evidence_requests == []


# --- 2. the family: offered only with drawing evidence ------------------------------------------


def test_drawing_evidence_is_a_record_or_a_candidate() -> None:
    plate = fixture("plate-drawing")

    assert drawing_evidence(plate) is True
    assert drawing_evidence(plate.model_copy(update={"drawing_records": []})) is True
    assert drawing_evidence(plate.model_copy(update={"drawing_candidates": []})) is True
    assert drawing_evidence(
        plate.model_copy(update={"drawing_records": [], "drawing_candidates": []})
    ) is False
    assert drawing_evidence(prerun_package()) is False


def test_the_family_is_offered_only_with_drawing_evidence() -> None:
    offered = names(ToolRegistry().functions_for(context_for(fixture("plate-drawing"))))
    bare = names(ToolRegistry().functions_for(context_for(prerun_package())))

    assert DRAWINGS_TOOL in offered and offered[-len(drawing_tools()):] == names(drawing_tools())
    assert DRAWINGS_TOOL not in bare
    assert offered[: len(bare)] == bare


def test_the_family_is_in_none_of_the_three_standing_lists() -> None:
    family = set(names(drawing_tools()))

    assert family.isdisjoint(names(TOOL_FUNCTIONS))
    assert family.isdisjoint(names(MCP_TOOL_FUNCTIONS + MCP_BRIDGE_TOOL_FUNCTIONS))
    assert family.isdisjoint(contract_enabled_tools())


# --- 3. the plan (section 2) ----------------------------------------------------------------------


def test_it_is_planned_after_every_code_first_check_and_before_check_standards() -> None:
    context = context_for(fixture("drawing-root"))
    profile = load_profile(STANDARDS_PROFILE)
    attach_standards_run(
        context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
    )

    plan = [name for name, _ in planned_calls(context, ToolRegistry().dispatch(context))]

    code_first = [plan.index(name) for name in checks_mechanical.CODE_FIRST_CHECKS]
    assert plan.index(DRAWINGS_TOOL) > max(code_first)
    assert plan.index(DRAWINGS_TOOL) == plan.index(CHECK_TOOL) - 1
    assert ("check_drawings", {}) in planned_calls(context, ToolRegistry().dispatch(context))


def test_it_is_not_planned_without_drawing_evidence() -> None:
    context = context_for(prerun_package())

    plan = [name for name, _ in planned_calls(context, ToolRegistry().dispatch(context))]

    assert DRAWINGS_TOOL not in plan


def test_it_is_not_planned_when_withheld() -> None:
    context = context_for(fixture("plate-drawing"))
    dispatch = ToolRegistry().dispatch(context)
    withheld = ToolDispatch(
        tools=dispatch.tools,
        sink=dispatch.sink,
        withheld=(
            WithheldTool(name=DRAWINGS_TOOL, reason="withheld in a test", checklist_item=None,
                         context=context, sink=dispatch.sink),
        ),
    )

    plan = [name for name, _ in planned_calls(context, withheld)]

    assert DRAWINGS_TOOL not in plan


def test_the_re_call_guard_keys_it_by_the_tool_alone() -> None:
    assert repeat_key(DRAWINGS_TOOL, {}) == (DRAWINGS_TOOL,)
    assert repeat_key(DRAWINGS_TOOL, {"anything": 1}) == (DRAWINGS_TOOL,)


def test_its_digest_line_counts_drawings_candidates_and_questions() -> None:
    call = PrerunCall(
        tool=DRAWINGS_TOOL,
        arguments={},
        step_index=7,
        findings=(),
        error=None,
        payload={"status": "recorded", "drawings": 2, "candidates": 3, "questions": 2,
                 "findings": 0, "finding_ids": [], "coverage": {}},
    )
    single = PrerunCall(
        tool=DRAWINGS_TOOL, arguments={}, step_index=7, findings=(), error=None,
        payload={"drawings": 1, "candidates": 1, "questions": 1},
    )

    assert call.line() == "  check_drawings() -> ok, 2 drawings, 3 candidates, 2 questions"
    assert single.line() == "  check_drawings() -> ok, 1 drawing, 1 candidate, 1 question"


def test_the_pre_run_calls_it_and_the_digest_says_so(tmp_path: Path) -> None:
    run = played(tmp_path, "plate-drawing")

    opening = run.messages[0]["content"]
    assert "  check_drawings() -> ok, 2 drawings, 1 candidate, 1 question" in opening
    [step] = [step for step in run.session.steps if step.tool == DRAWINGS_TOOL]
    assert step.status == "ok"
    assert len(run.session.evidence_requests) == 1


def test_a_repeat_after_the_pre_run_records_one_step_and_adds_nothing(tmp_path: Path) -> None:
    run = played(tmp_path, "plate-drawing")
    guard = run.tools
    assert isinstance(guard, PrerunGuard)
    steps, requests = len(run.session.steps), len(run.session.evidence_requests)

    result = guard.call(DRAWINGS_TOOL, {})

    assert result.payload["status"] == ALREADY_RUN
    assert result.payload["outcome"]["drawings"] == 2
    assert len(run.session.steps) == steps + 1
    assert len(run.session.evidence_requests) == requests


def test_lever_13_withholds_it_once_the_pre_run_ran_it(tmp_path: Path) -> None:
    run = played(
        tmp_path, "plate-drawing",
        EfficiencySettings(prerun_checks=True, withhold_prerun_tools=True),
    )

    assert DRAWINGS_TOOL not in [tool.name for tool in run.tools]
    assert f"{DRAWINGS_TOOL}" in run.messages[0]["content"].split("Not offered to you", 1)[1]


# --- 4. with no drawing evidence nothing moves (FR-037) -------------------------------------------


def test_without_drawing_evidence_the_plan_array_and_digest_equal_a_tree_without_the_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_prerun_digest import started

    with_family, _ = started(tmp_path, "with", efficiency=ON)
    context = context_for(prerun_package())
    plan = planned_calls(context, ToolRegistry().dispatch(context))
    array = [tool.spec.schema for tool in ToolRegistry().dispatch(context)]

    monkeypatch.setattr(registry, "drawing_tools", lambda: ())
    without_family, _ = started(tmp_path, "without", efficiency=ON)
    context = context_for(prerun_package())

    assert planned_calls(context, ToolRegistry().dispatch(context)) == plan
    assert [tool.spec.schema for tool in ToolRegistry().dispatch(context)] == array
    assert with_family.messages[0]["content"] == without_family.messages[0]["content"]
