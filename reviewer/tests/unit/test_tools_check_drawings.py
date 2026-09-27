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
from swreview.checks.drawing_context import (
    CANDIDATE_CONFIRM,
    CLOSED_BY_CODE,
    item_closed_by_code,
)
from swreview.checks.drawing_context import CONFORMANCE_CHECK as CONFORMANCE
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import CHECK_TOOL
from swreview.checks.standards.traversal import graded_documents
from swreview.drawings.evidence import DrawingIndex
from swreview.ir.loader import LoadedPackage, load_package
from swreview.ir.models import EvidencePackage
from swreview.mcp.server import MCP_BRIDGE_TOOL_FUNCTIONS, MCP_TOOL_FUNCTIONS
from swreview.prerun import (
    ALREADY_RUN,
    PrerunCall,
    PrerunGuard,
    planned_calls,
    repeat_key,
)
from swreview.report.session import CoverageItem, CoverageScope
from swreview.report.summary import review_ranking
from swreview.tools import checks_mechanical, registry
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.drawings import (
    DRAWINGS_TOOL,
    PART_ROLES_ATTRIBUTE,
    check_drawings,
    drawing_evidence,
)
from swreview.tools.registry import (
    TOOL_FUNCTIONS,
    ToolDispatch,
    ToolRegistry,
    WithheldTool,
    drawing_tools,
)
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
from tests.support.fake_part_roles import FakePartRoles
from tests.support.prerun import ON, STANDARDS_PROFILE, prerun_package
from tests.unit.test_drawing_context import (
    INSTRUCTION,
    LOOSE,
    SITTING,
    assembly,
    drawn,
    sitting,
    sitting_roles,
)
from tests.unit.test_mcp_server import contract_enabled_tools

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"


def fixture(name: str) -> EvidencePackage:
    return load_package(FIXTURES / name).package


class ModeHost:
    """A bridge as the drawing check asks it: what its `drawing.read` can do, as
    `BridgeClient.drawing_read_mode` answers (013 T074), counting each time it is asked."""

    def __init__(self, mode: str = "opens_closed") -> None:
        self.mode = mode
        self.asked = 0

    def drawing_read_mode(self) -> str:
        self.asked += 1
        return self.mode

    def close(self) -> None:
        pass


def recorded(
    package: EvidencePackage, *, host: ModeHost | None = None, roles: Any = None
) -> tuple[ToolContext, dict[str, Any]]:
    """`check_drawings` over `package`, with `host` as the bridge and `roles` attached where
    `start_review` attaches them (013 `contracts/part-roles.md` section 5)."""
    context = context_for(package)
    context.bridge = host
    if roles is not None:
        setattr(context, PART_ROLES_ATTRIBUTE, roles)
    with use_context(context):
        return context, check_drawings()


def names(functions: Any) -> list[str]:
    return [function.__name__ for function in functions]


def played(
    tmp_path: Path, name: str, efficiency: EfficiencySettings = ON, host: ModeHost | None = None
) -> Any:
    """A scripted review of a committed drawing fixture, its pre-run played, with `host` as its
    bridge when one is given."""
    folder = tmp_path / name
    shutil.copytree(FIXTURES / name, folder)
    bridged: dict[str, Any] = (
        {} if host is None else {"bridge": True, "bridge_factory": lambda pipe, secret: host}
    )
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=efficiency,
        **bridged,
    )
    run.start()
    return run


# --- 1. the tool --------------------------------------------------------------------------------


def test_check_drawings_takes_no_argument() -> None:
    assert inspect.signature(check_drawings).parameters == {}
    assert DRAWINGS_TOOL == "check_drawings"


def test_check_drawings_returns_the_counts() -> None:
    """*Edited deliberately by 013 T079:* with no bridge the candidate question is not asked (the
    host can open nothing), and the four documents no drawing shows are `unresolved`."""
    _, result = recorded(fixture("plate-drawing"))
    _, offered = recorded(fixture("plate-drawing"), host=ModeHost("opens_closed"))

    assert result == {
        "status": "recorded",
        "drawings": 2,
        "candidates": 1,
        "questions": 0,
        "findings": 0,
        "finding_ids": [],
        "states": {"attached": 1, "candidate": 1, "absent": 3, "bought": 0},
        "coverage": {"checked": 1, "skipped": 0, "unresolved": 4},
    }, "013 T085 adds the states; the plate's attached drawing keeps the item the model's"
    assert offered == {**result, "questions": 1}


def test_it_records_one_drawing_context_item_per_reviewed_document() -> None:
    context, _ = recorded(fixture("plate-drawing"))
    coverage = context.require_session().coverage

    checked = [item for item in coverage.checked if item.check == "drawing.context"]
    unresolved = [item for item in coverage.unresolved if item.check == "drawing.context"]
    assert [item.scope.document_ids for item in checked] == [["doc:0002"]]
    assert [item.scope.document_ids[0] for item in unresolved] == [
        "doc:0001", "doc:0003", "doc:0004", "doc:0005"
    ], "013 T079: no drawing shows them, which is unresolved, not skipped"
    assert [item for item in coverage.skipped if item.check == "drawing.context"] == []


def test_the_questions_are_evidence_requests_the_summary_shows() -> None:
    context, _ = recorded(fixture("plate-drawing"), host=ModeHost("opens_closed"))
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
    context, first = recorded(fixture("plate-drawing"), host=ModeHost("opens_closed"))
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


def test_a_valid_profile_is_compared_even_when_the_standards_phases_were_not_dumped() -> None:
    """Feature 013 T019 (lane P, one case in this file): the drawing check now reads the
    review's loaded profile (`checks_mechanical.review_profile`), not only the standards
    run's, so `drawing_profile.conformance` is compared on a review whose standards phases
    were not dumped - where it was skipped as "the standards profile is absent" before. The
    rows it moves are pinned deliberately: one skipped row becomes two checked ones."""
    from swreview.prerun import attach_standards

    package = fixture("plate-drawing")
    package = package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"phases": []})}
    )
    context = context_for(package)
    assert attach_standards(context, STANDARDS_PROFILE) is not None  # the run did not attach
    with use_context(context):
        check_drawings()

    coverage = context.require_session().coverage
    conformance = {
        bucket: [item.reason for item in getattr(coverage, bucket) if item.check == CONFORMANCE]
        for bucket in ("checked", "skipped", "unresolved")
    }
    assert conformance["skipped"] == [] and conformance["unresolved"] == []
    assert [reason.split(" agrees ")[0] for reason in conformance["checked"]] == [
        "drawing doc:0006",
        "drawing doc:0007",
    ]


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
    run = played(tmp_path, "plate-drawing", host=ModeHost("opens_closed"))

    opening = run.messages[0]["content"]
    assert "  check_drawings() -> ok, 2 drawings, 1 candidate, 1 question" in opening
    [step] = [step for step in run.session.steps if step.tool == DRAWINGS_TOOL]
    assert step.status == "ok"
    assert len(run.session.evidence_requests) == 1


def test_without_a_bridge_the_pre_run_asks_no_candidate_question(tmp_path: Path) -> None:
    """013 T079: the digest counts no question when the host can open nothing."""
    run = played(tmp_path / "bare", "plate-drawing")

    assert "  check_drawings() -> ok, 2 drawings, 1 candidate, 0 questions" in (
        run.messages[0]["content"]
    )
    assert run.session.evidence_requests == []


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


# --- 5. the offer follows the host, for custom documents only (013 T079) --------------------------
#
# 013 `contracts/drawing-capability.md` sections 2 to 4. The check reads the review's part roles
# where `start_review` attaches them and asks the host what its `drawing.read` can do - only when
# a custom or unclear document has a candidate, so a package without one never pings.


def test_the_host_is_asked_only_when_a_custom_or_unclear_document_has_a_candidate() -> None:
    plate = fixture("plate-drawing")  # one candidate, beside doc:0003
    hosts = {
        "no candidate": ModeHost(),
        "a bought document's only": ModeHost(),
        "a custom document's": ModeHost(),
        "an unclear document's": ModeHost(),
    }

    recorded(fixture("assembly-drawings"), host=hosts["no candidate"])
    recorded(plate, host=hosts["a bought document's only"],
             roles=FakePartRoles(roles={"doc:0003": "bought"}, root="doc:0001"))
    recorded(plate, host=hosts["a custom document's"])
    recorded(plate, host=hosts["an unclear document's"],
             roles=FakePartRoles(roles={"doc:0003": "unclear"}, root="doc:0001"))

    assert {case: host.asked for case, host in hosts.items()} == {
        "no candidate": 0,
        "a bought document's only": 0,
        "a custom document's": 1,
        "an unclear document's": 1,
    }


@pytest.mark.parametrize("mode", ["none", "open_only"])
def test_while_the_host_cannot_open_a_closed_drawing_the_candidate_gets_the_instruction(
    mode: str,
) -> None:
    context, result = recorded(fixture("plate-drawing"), host=ModeHost(mode))

    assert result["questions"] == 0
    assert context.require_session().evidence_requests == []
    [item] = [
        item for item in context.require_session().coverage.unresolved
        if item.check == "drawing.context" and item.scope.document_ids == ["doc:0003"]
    ]
    assert item.reason == (
        "Open FICT-TULMSORN-3002.SLDDRW in SOLIDWORKS, then press Review again with "
        "FICT-TULMVEN-0000.SLDASM active"
    )


def test_a_bought_document_is_no_drawing_subject_and_its_candidate_is_not_offered() -> None:
    roles = FakePartRoles(roles={"doc:0003": "bought", "doc:0004": "bought"}, root="doc:0001")

    context, result = recorded(fixture("plate-drawing"), host=ModeHost(), roles=roles)

    subjects = [
        item.scope.document_ids[0]
        for bucket in ("checked", "skipped", "unresolved")
        for item in getattr(context.require_session().coverage, bucket)
        if item.check == "drawing.context"
    ]
    assert sorted(subjects) == ["doc:0001", "doc:0002", "doc:0005"]
    assert result["questions"] == 0
    assert context.require_session().evidence_requests == []


def test_the_drawing_check_reads_the_roles_where_start_review_attaches_them() -> None:
    """The stand-in attribute name is the registry's once 013 T022 (lane S) defines it."""
    if not hasattr(registry, "PART_ROLES_ATTRIBUTE"):
        pytest.xfail(
            "013 T022 (lane S) adds tools/registry.PART_ROLES_ATTRIBUTE; "
            "tools/drawings.PART_ROLES_ATTRIBUTE stands in for it until then"
        )
    assert PART_ROLES_ATTRIBUTE == registry.PART_ROLES_ATTRIBUTE


def test_the_drawing_check_asks_the_context_for_the_mode_once_it_can_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """013 T077 (lane S) gives `ToolContext.drawing_read_mode()`, lazy, cached and recorded on
    the session; the check must then ask it rather than the bridge. Here the context says
    `opens_closed` with no bridge at all, so only a check that asks the context offers."""
    if not hasattr(ToolContext, "drawing_read_mode"):
        pytest.xfail(
            "013 T077 (lane S) adds ToolContext.drawing_read_mode(); tools/drawings._read_mode "
            "asks the bridge until then"
        )
    monkeypatch.setattr(ToolContext, "drawing_read_mode", lambda self: "opens_closed")

    _, result = recorded(fixture("plate-drawing"))

    assert result["questions"] == 1


# --- 6. the drawing item closed by code, and the payload (013 T084) -----------------------------
#
# 013 `contracts/drawing-capability.md` sections 5 and 7. While no attached drawing shows a custom
# or unclear document, `check_drawings` closes the checklist's `drawing.manufacturing_inputs` item
# with one row - unresolved naming each candidate or missing drawing, skipped when every subject is
# bought - and the model owns the item again once a drawing is attached. The payload counts
# candidate files and each drawing state.

MANUFACTURING_INPUTS = "drawing.manufacturing_inputs"


def item_rows(context: ToolContext) -> list[tuple[str, list[str], str]]:
    """`(bucket, document ids, reason)` of each `drawing.manufacturing_inputs` row, bucket order."""
    return [
        (bucket, list(item.scope.document_ids), item.reason)
        for bucket in ("checked", "skipped", "unresolved")
        for item in getattr(context.require_session().coverage, bucket)
        if item.check == MANUFACTURING_INPUTS
    ]


def test_the_payload_counts_candidate_files_and_carries_every_state() -> None:
    _, result = recorded(sitting(), host=ModeHost("open_only"), roles=sitting_roles())

    assert result == {
        "status": "recorded",
        "drawings": 0,
        "candidates": 1,
        "questions": 0,
        "findings": 0,
        "finding_ids": [],
        "states": {"attached": 0, "candidate": 2, "absent": 1, "bought": 1},
        "coverage": {"checked": 0, "skipped": 0, "unresolved": 4},
    }, "one file beside two documents; three drawing.context rows and the closing row"
    assert list(result) == [
        "status", "drawings", "candidates", "questions", "findings", "finding_ids", "states",
        "coverage",
    ]


def test_with_nothing_attached_the_item_is_closed_by_code_naming_each_missing_drawing() -> None:
    context, _ = recorded(sitting(), host=ModeHost("open_only"), roles=sitting_roles())

    assert item_rows(context) == [(
        "unresolved",
        ["doc:0001", "doc:0002", "doc:0004"],
        f"No attached drawing shows a custom part or assembly - {SITTING}.SLDASM and "
        f"{SITTING}.SLDPRT: {INSTRUCTION}; {LOOSE}.SLDPRT: no drawing named {LOOSE}.SLDDRW sits "
        "beside it (may be a bought part)",
    )]
    assert CLOSED_BY_CODE == "No attached drawing shows a custom part or assembly"


def test_when_every_subject_is_bought_the_item_is_skipped() -> None:
    """Only a drawing root leaves every subject bought: any other root is graded (the root rule),
    and bought comes before attached, so the root drawing's views do not make them attached."""
    root = fixture("drawing-root")
    roles = FakePartRoles(roles=dict.fromkeys(("doc:2", "doc:3", "doc:4"), "bought"), root="doc:1")

    context, result = recorded(root, roles=roles)

    assert item_rows(context) == [(
        "skipped",
        ["doc:2", "doc:3", "doc:4"],
        "No attached drawing shows a custom part or assembly - every reviewed part and assembly "
        "is bought, so no drawing is expected",
    )]
    assert result["states"] == {"attached": 0, "candidate": 0, "absent": 0, "bought": 3}
    assert result["coverage"] == {"checked": 0, "skipped": 1, "unresolved": 0}


def test_with_no_part_or_assembly_reviewed_the_item_is_skipped_saying_so() -> None:
    root = fixture("drawing-root")
    drawings_only = root.model_copy(
        update={"documents": [row for row in root.documents if row.kind == "drawing"]}
    )

    context, _ = recorded(drawings_only)

    assert item_rows(context) == [(
        "skipped", [],
        "No attached drawing shows a custom part or assembly - no part or assembly is reviewed, "
        "so no drawing is expected",
    )]


def test_with_a_drawing_attached_the_model_owns_the_item() -> None:
    plate = fixture("plate-drawing")

    context, result = recorded(plate)

    assert item_rows(context) == []
    assert result["states"] == {"attached": 1, "candidate": 1, "absent": 3, "bought": 0}
    assert item_closed_by_code(DrawingIndex.for_package(plate), None) is False


def test_the_one_predicate_decides_the_item() -> None:
    """`item_closed_by_code` is what `mark_coverage` asks (013 T087) and what the closing row
    follows: nothing attached; a drawing showing only bought documents shows no custom one."""
    plate = fixture("plate-drawing")  # the plate, doc:0002, is the one document shown
    index = DrawingIndex.for_package(plate)

    assert item_closed_by_code(DrawingIndex.for_package(sitting()), sitting_roles()) is True
    assert item_closed_by_code(index, FakePartRoles(roles={"doc:0002": "custom"})) is False
    assert item_closed_by_code(
        index, FakePartRoles(roles={"doc:0002": "bought"}, root="doc:0001")
    ) is True
    assert item_closed_by_code(index, FakePartRoles(roles={"doc:0002": "unclear"})) is False


def test_calling_it_again_adds_no_second_closing_row() -> None:
    context, first = recorded(sitting(), host=ModeHost("open_only"), roles=sitting_roles())
    rows = item_rows(context)
    with use_context(context):
        second = check_drawings()

    assert second == first
    assert item_rows(context) == rows and len(rows) == 1


def test_the_closing_row_goes_once_a_confirmed_read_attaches_a_drawing() -> None:
    """The state leaves "closed by code" only when a read attaches a drawing, before the model has
    had a turn to write a row of its own: the restated check withdraws its closing row."""
    base, (part,) = assembly(1)
    bare = base.build().package
    context, _ = recorded(bare)
    assert len(item_rows(context)) == 1

    context.reload_package(LoadedPackage(package=drawn(base, {"FICT-KALO-7001": [part]}),
                                         base_dir=Path(".")))
    with use_context(context):
        check_drawings()

    assert item_rows(context) == []


def test_the_models_own_rows_are_never_withdrawn_while_a_drawing_is_attached() -> None:
    context = context_for(fixture("plate-drawing"))
    own = CoverageItem(
        check=MANUFACTURING_INPUTS, scope=CoverageScope(document_ids=["doc:0002"]),
        reason="the plate's drawing gives its fits", error=None,
    )
    context.record_coverage("checked", own)

    with use_context(context):
        check_drawings()
        check_drawings()

    assert item_rows(context) == [("checked", ["doc:0002"], "the plate's drawing gives its fits")]


def test_while_closed_the_closing_row_supersedes_the_items_other_rows() -> None:
    """A row of the item that predates the change that closed it (a regrade made the only
    attached document bought) is withdrawn: in this state code owns the item, and the model is
    answered `closed_by_code` (013 T087)."""
    plate = fixture("plate-drawing")
    context = context_for(plate)
    context.record_coverage("checked", CoverageItem(
        check=MANUFACTURING_INPUTS, scope=CoverageScope(document_ids=["doc:0002"]),
        reason="the plate's drawing gives its fits", error=None,
    ))
    setattr(context, PART_ROLES_ATTRIBUTE, FakePartRoles(roles={"doc:0002": "bought"},
                                                         root="doc:0001"))

    with use_context(context):
        check_drawings()

    [(bucket, _, reason)] = item_rows(context)
    assert bucket == "unresolved"
    assert reason.startswith(CLOSED_BY_CODE)


# --- 7. the drawing check's questions are written by code (013 T098) ----------------------------


def test_the_drawing_checks_questions_carry_source_code() -> None:
    """013 `contracts/sources.md` section 1: a question code wrote says so, so the pane labels
    it and the re-ask guard never lets it cover a model question. 013 T099: `check_drawings`
    records its questions through `tools/session.record_question`, which writes
    `source="code"`, and this test holds it there."""
    candidate, _ = recorded(fixture("plate-drawing"), host=ModeHost("opens_closed"))
    governing, _ = recorded(fixture("assembly-drawings"))

    requests = [
        *candidate.require_session().evidence_requests,
        *governing.require_session().evidence_requests,
    ]
    assert len(requests) == 2
    assert [getattr(request, "source", None) for request in requests] == ["code", "code"]
