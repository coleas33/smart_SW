"""Unit tests for the re-modeler's judgement tools (T108, T110, T112, T114).

`specs/004-resilient-remodeler/contracts/tools.md` is normative for every sentence
asserted here. The five tools let the model **propose intent into the plan** and nothing
else: no order, no move, no folder, no rollback, no verdict, and no call that could reach
SOLIDWORKS. That is what lets stage 1's apply loop run with no model in it, so the tests
are organised around the three properties that carry the contract rather than around the
functions:

- **every rejection is a result, never an exception.** A refused proposal returns
  `{"error": ...}`, which `RecordedTool.call` already turns into `is_error=True`; this
  feature adds no error path. One rejection is asserted through the registry as well as
  through the bare function, so "the model can act on it" is proven and not assumed;
- **a rejection is also written down.** `plan.rejected_proposals[]` gains one row per
  refusal, carrying the tool, the arguments as sent, the sentence, the rule id and the
  provider and model, because FR-016 and US4 scenario 7 make the report list them and a
  tool result is persisted nowhere the report reads;
- **the tools exist only for a remodel run.** They are registered through a `Registration`
  added when `ToolContext.remodel` is set, exactly the way `bridge_tools()` is added when
  the context carries a bridge, and with `remodel` unset the offered list is byte-identical
  to today's. None of them is in the MCP function list or in the terminal profile's
  `enabled_tools`, so one can never leak into general chat or into the CLI.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from swreview.agent.providers.schema import canonical_schema
from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage
from swreview.mcp.server import MCP_BRIDGE_TOOL_FUNCTIONS, MCP_TOOL_FUNCTIONS
from swreview.remodel.plan import RemodelPlan, plan_reorganize
from swreview.tools import remodel_plan
from swreview.tools.context import context_for, use_context
from swreview.tools.registry import (
    TOOL_FUNCTIONS,
    RecordedTool,
    ToolRegistry,
    remodel_tools,
)
from tests.support.features import equation, feature, fillet_feature, sketch_feature
from tests.support.remodel import UNKNOWN_TYPE_NAME, linked, remodel_package
from tests.unit.test_mcp_server import contract_enabled_tools

TABLE = load_table()
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups
AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
PROVIDER = "fake"
MODEL = "fake-judge-1"
UNIT = "mm"

REMODEL_TOOL_NAMES: tuple[str, ...] = (
    "propose_description",
    "propose_global",
    "decide_fillet",
    "classify_unknown",
    "get_remodel_plan",
)
"""The five rows of the tool table in `contracts/tools.md`, in its order."""

SECTIONS: tuple[str, ...] = (
    "summary",
    "targets",
    "order",
    "pins",
    "rebuild",
    "folders",
    "descriptions",
    "globals",
    "deviations",
    "rejected_proposals",
)
"""Every `section` `get_remodel_plan` accepts, in the contract's order."""


# --- the part under judgement -----------------------------------------------------


def part() -> EvidencePackage:
    """One part carrying every case the four validators have to answer.

    `Fillet1` has a dependent (`Shell1`), `Fillet2` has none and `Fillet3`'s `GetChildren`
    call failed, which is the difference between "no dependents" and "nobody knows".
    `Deform1` carries a type name the table does not classify, `Shell1`'s description was
    read and is blank, `Cut-Extrude1`'s could not be read at all, and `Right Plane` is an
    excluded default name and therefore not content.
    """
    specs = linked(
        [
            feature("Right Plane", "RefPlane"),
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            fillet_feature("Fillet1", radius_m=0.005),
            fillet_feature("Fillet2", radius_m=0.003),
            fillet_feature("Fillet3", radius_m=None, child_names=None),
            feature("Deform1", UNKNOWN_TYPE_NAME),
            feature("Shell1", "Shell", description=""),
            feature("Cut-Extrude1", "Cut", description=None),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Fillet1"),
        ("Fillet1", "Shell1"),
        ("Boss-Extrude1", "Deform1"),
    )
    return remodel_package(
        specs, equations=[equation('"width" = 100', is_global=True, value=0.1)]
    )


PACKAGE = part()
IDS: dict[str, str] = {row.name: row.id for row in PACKAGE.features}


def plan_of(package: EvidencePackage) -> RemodelPlan:
    return plan_reorganize(package, now=AT)


def judgement_context() -> remodel_plan.RemodelToolContext:
    return remodel_plan.RemodelToolContext(
        plan=plan_of(PACKAGE),
        provider=PROVIDER,
        model=MODEL,
        document_length_unit=UNIT,
    )


@pytest.fixture
def judgement() -> Iterator[remodel_plan.RemodelToolContext]:
    """The remodel context behind the contextvar the five tools read."""
    context = context_for(PACKAGE)
    context.remodel = judgement_context()
    with use_context(context):
        yield context.remodel


def recorded(name: str) -> RecordedTool:
    """The registry-built tool called `name`, over a fresh remodel context."""
    context = context_for(PACKAGE)
    context.remodel = judgement_context()
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


def only_rejection(judgement: remodel_plan.RemodelToolContext) -> Any:
    """The single `RejectedProposal` this call wrote, asserted to be the only one."""
    assert len(judgement.rejected_proposals) == 1, judgement.rejected_proposals
    return judgement.rejected_proposals[0]


def nothing_accepted(judgement: remodel_plan.RemodelToolContext) -> None:
    """No accepted proposal of any kind: a rejection writes into one list only."""
    assert judgement.descriptions == []
    assert judgement.globals == []
    assert judgement.targets == []
    assert judgement.deviations == []


# --- 1. propose_description (T108) ------------------------------------------------


def test_an_accepted_description_lands_in_descriptions_and_nowhere_else(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    result = remodel_plan.propose_description(
        IDS["Shell1"], "Wall thickness for the casting"
    )

    assert result == {
        "feature_id": IDS["Shell1"],
        "text": "Wall thickness for the casting",
    }
    assert [item.feature_id for item in judgement.descriptions] == [IDS["Shell1"]]
    proposal = judgement.descriptions[0]
    assert proposal.before == ""
    assert proposal.text == "Wall thickness for the casting"
    assert proposal.source == "model"
    assert proposal.validation == "accepted"
    assert (proposal.provider, proposal.model) == (PROVIDER, MODEL)
    assert judgement.rejected_proposals == []
    assert judgement.targets == []
    assert judgement.globals == []
    assert judgement.deviations == []


@pytest.mark.parametrize(
    ("feature_name", "text", "reason", "rule"),
    [
        pytest.param(
            None,
            "Wall thickness",
            "unknown feature id",
            "propose_description.unknown_feature",
            id="unknown-id",
        ),
        pytest.param(
            "Right Plane",
            "A datum plane",
            "not a content feature",
            "propose_description.not_content",
            id="not-content",
        ),
        pytest.param(
            "Shell1",
            "",
            "description must be 1 to 200 characters",
            "propose_description.length",
            id="empty",
        ),
        pytest.param(
            "Shell1",
            "x" * 201,
            "description must be 1 to 200 characters",
            "propose_description.length",
            id="too-long",
        ),
        pytest.param(
            "Shell1",
            "two\nlines",
            "description must be a single line",
            "propose_description.single_line",
            id="newline",
        ),
        pytest.param(
            "Shell1",
            "two\rlines",
            "description must be a single line",
            "propose_description.single_line",
            id="carriage-return",
        ),
        pytest.param(
            "Shell1",
            "  shell1  ",
            "description repeats the feature name",
            "propose_description.repeats_name",
            id="repeats-name",
        ),
        pytest.param(
            "Shell1",
            "Shell",
            "description repeats the feature name",
            "propose_description.repeats_name",
            id="repeats-type-name",
        ),
        pytest.param(
            "Cut-Extrude1",
            "The pocket",
            "current description is unreadable; this feature is on the rebuild list",
            "propose_description.unreadable",
            id="unreadable-description",
        ),
    ],
)
def test_propose_description_rejections(
    judgement: remodel_plan.RemodelToolContext,
    feature_name: str | None,
    text: str,
    reason: str,
    rule: str,
) -> None:
    feature_id = "feat:9999" if feature_name is None else IDS[feature_name]

    result = remodel_plan.propose_description(feature_id, text)

    assert result == {"error": reason}
    rejection = only_rejection(judgement)
    assert rejection.tool == "propose_description"
    assert rejection.reason == reason
    assert rejection.rule == rule
    assert rejection.arguments == {"feature_id": feature_id, "text": text}
    assert (rejection.provider, rejection.model) == (PROVIDER, MODEL)
    assert rejection.at.tzinfo is not None
    nothing_accepted(judgement)


def test_a_second_description_for_one_feature_is_refused(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    remodel_plan.propose_description(IDS["Shell1"], "Wall thickness for the casting")

    result = remodel_plan.propose_description(IDS["Shell1"], "Something else entirely")

    assert result == {"error": "already proposed for this feature"}
    assert len(judgement.descriptions) == 1
    assert only_rejection(judgement).rule == "propose_description.duplicate"


def test_a_rejected_description_is_an_error_result_and_not_an_exception() -> None:
    """`RecordedTool.call` turns `{"error": ...}` into `is_error=True` with no raise."""
    tool = recorded("propose_description")

    result = tool.call({"feature_id": "feat:9999", "text": "anything"})

    assert result.is_error is True
    assert result.payload == {"error": "unknown feature id"}


# --- 2. propose_global (T110) -----------------------------------------------------


def test_an_accepted_global_lands_in_globals_with_its_evidence(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    result = remodel_plan.propose_global(
        "corner_radius",
        "5",
        "the two structural fillets share one radius",
        [IDS["Fillet1"]],
    )

    assert result == {
        "name": "corner_radius",
        "expression": "5",
        "evidence": [IDS["Fillet1"]],
    }
    proposal = judgement.globals[0]
    assert proposal.name == "corner_radius"
    assert proposal.validation == "accepted"
    assert (proposal.provider, proposal.model) == (PROVIDER, MODEL)
    assert proposal.order_index == 0
    evidence = proposal.evidence[0]
    assert evidence.feature_id == IDS["Fillet1"]
    assert evidence.parameter == "default_radius"
    assert evidence.value_m == pytest.approx(0.005)
    assert evidence.document_length_unit == UNIT
    assert evidence.value_document_units == pytest.approx(5.0)
    assert evidence.equation_text == '"corner_radius" = 5'
    assert judgement.rejected_proposals == []


def test_a_millimetre_part_never_writes_the_metre_number(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    """R3.6: a 5 mm radius is `= 5`, never `= 0.005`."""
    remodel_plan.propose_global(
        "corner_radius", "5", "the structural fillet", [IDS["Fillet1"]]
    )

    assert "0.005" not in judgement.globals[0].evidence[0].equation_text


def test_a_global_over_an_earlier_proposal_needs_no_evidence(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    remodel_plan.propose_global(
        "corner_radius", "5", "the structural fillet", [IDS["Fillet1"]]
    )

    result = remodel_plan.propose_global(
        "corner_clearance", '"corner_radius" * 2', "twice the corner radius", []
    )

    assert result["name"] == "corner_clearance"
    assert judgement.globals[1].evidence == ()
    assert judgement.globals[1].order_index == 1


@pytest.mark.parametrize(
    ("name", "expression", "rationale", "evidence", "reason", "rule"),
    [
        pytest.param(
            "CornerRadius",
            "5",
            "a radius",
            ["Fillet1"],
            "global name must be lower_snake_case, 2 to 32 characters",
            "propose_global.name_pattern",
            id="upper-case",
        ),
        pytest.param(
            "r",
            "5",
            "a radius",
            ["Fillet1"],
            "global name must be lower_snake_case, 2 to 32 characters",
            "propose_global.name_pattern",
            id="one-character",
        ),
        pytest.param(
            "w" * 33,
            "5",
            "a radius",
            ["Fillet1"],
            "global name must be lower_snake_case, 2 to 32 characters",
            "propose_global.name_pattern",
            id="thirty-three-characters",
        ),
        pytest.param(
            "width",
            "5",
            "a radius",
            ["Fillet1"],
            "a global with this name already exists",
            "propose_global.existing_global",
            id="collides-with-the-package",
        ),
        pytest.param(
            "corner_radius",
            "plate_width * 2",
            "a radius",
            ["Fillet1"],
            "expression does not parse",
            "propose_global.expression_parse",
            id="unquoted-reference",
        ),
        pytest.param(
            "corner_radius",
            '"D1@Sketch1" * 2',
            "a radius",
            ["Fillet1"],
            "expression does not parse",
            "propose_global.expression_parse",
            id="names-a-dimension",
        ),
        pytest.param(
            "corner_radius",
            '"corner_radius" * 2',
            "a radius",
            ["Fillet1"],
            "expression is circular",
            "propose_global.circular",
            id="self-reference",
        ),
        pytest.param(
            "corner_radius",
            '"plate_width" * 2',
            "a radius",
            ["Fillet1"],
            "expression references an undeclared name",
            "propose_global.undeclared_reference",
            id="undeclared",
        ),
        pytest.param(
            "corner_radius",
            "5",
            "a radius",
            ["Right Plane"],
            "evidence names an unknown feature",
            "propose_global.unknown_evidence",
            id="evidence-not-content",
        ),
        pytest.param(
            "corner_radius",
            "5",
            "a radius",
            ["Shell1"],
            "no parameter data for this feature in the package",
            "propose_global.no_parameter_data",
            id="no-feature-data",
        ),
        pytest.param(
            "corner_radius",
            "5",
            "a radius",
            ["Fillet3"],
            "no parameter data for this feature in the package",
            "propose_global.no_parameter_data",
            id="unreadable-radius",
        ),
        pytest.param(
            "corner_radius",
            "5",
            "a radius",
            [],
            "a literal global needs feature data behind it",
            "propose_global.evidence_required",
            id="literal-with-no-evidence",
        ),
        pytest.param(
            "corner_radius",
            "5",
            "",
            ["Fillet1"],
            "rationale required",
            "propose_global.rationale",
            id="empty-rationale",
        ),
        pytest.param(
            "corner_radius",
            "5",
            "x" * 301,
            ["Fillet1"],
            "rationale required",
            "propose_global.rationale",
            id="rationale-too-long",
        ),
    ],
)
def test_propose_global_rejections(
    judgement: remodel_plan.RemodelToolContext,
    name: str,
    expression: str,
    rationale: str,
    evidence: list[str],
    reason: str,
    rule: str,
) -> None:
    ids = [IDS.get(item, item) for item in evidence]

    result = remodel_plan.propose_global(name, expression, rationale, ids)

    assert result == {"error": reason}
    rejection = only_rejection(judgement)
    assert rejection.tool == "propose_global"
    assert rejection.reason == reason
    assert rejection.rule == rule
    assert rejection.arguments == {
        "name": name,
        "expression": expression,
        "rationale": rationale,
        "evidence": ids,
    }
    assert (rejection.provider, rejection.model) == (PROVIDER, MODEL)
    nothing_accepted(judgement)


def test_an_unknown_evidence_id_is_refused(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    result = remodel_plan.propose_global("corner_radius", "5", "a radius", ["feat:9999"])

    assert result == {"error": "evidence names an unknown feature"}
    assert only_rejection(judgement).rule == "propose_global.unknown_evidence"


def test_a_second_proposal_of_one_name_is_refused(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    remodel_plan.propose_global(
        "corner_radius", "5", "the structural fillet", [IDS["Fillet1"]]
    )

    result = remodel_plan.propose_global(
        "corner_radius", "3", "the other fillet", [IDS["Fillet2"]]
    )

    assert result == {"error": "already proposed"}
    assert len(judgement.globals) == 1
    assert only_rejection(judgement).rule == "propose_global.already_proposed"


def test_an_unreadable_document_unit_refuses_rather_than_assuming_metres() -> None:
    """FR-027: an unread unit is not metres, and a literal seeded from that assumption is
    a part a thousand times off. The refusal is a result, so the run continues."""
    context = context_for(PACKAGE)
    context.remodel = remodel_plan.RemodelToolContext(
        plan=plan_of(PACKAGE),
        provider=PROVIDER,
        model=MODEL,
        document_length_unit=None,
    )
    with use_context(context):
        result = remodel_plan.propose_global(
            "corner_radius", "5", "the structural fillet", [IDS["Fillet1"]]
        )

    assert "error" in result
    assert context.remodel.globals == []
    assert only_rejection(context.remodel).rule == "propose_global.document_unit"


# --- 3. decide_fillet and classify_unknown (T112) ---------------------------------


@pytest.mark.parametrize("group", [CORE, QUARANTINE])
def test_an_accepted_fillet_decision_lands_in_targets(
    judgement: remodel_plan.RemodelToolContext, group: str
) -> None:
    subject = IDS["Fillet2"]

    result = remodel_plan.decide_fillet(subject, group, "no face depends on it")

    assert result == {"feature_id": subject, "group": group}
    target = judgement.targets[0]
    assert target.feature_id == subject
    assert target.target_group == group
    assert target.decided_by == "model"
    assert target.basis == "model_judgement"
    assert target.state == "resolved"
    assert target.candidates == ()
    assert target.rationale == "no face depends on it"
    assert (target.provider, target.model) == (PROVIDER, MODEL)
    assert judgement.deviations == []
    assert judgement.rejected_proposals == []


@pytest.mark.parametrize(
    ("feature_name", "group", "rationale", "reason", "rule"),
    [
        pytest.param(
            None,
            CORE,
            "structural",
            "unknown feature id",
            "decide_fillet.unknown_feature",
            id="unknown-id",
        ),
        pytest.param(
            "Boss-Extrude1",
            CORE,
            "structural",
            "not a fillet",
            "decide_fillet.not_a_fillet",
            id="not-a-fillet",
        ),
        pytest.param(
            "Fillet2",
            DETAIL,
            "cosmetic",
            "a fillet belongs in 3-Core or 6-Quarantine",
            "decide_fillet.group",
            id="wrong-group",
        ),
        pytest.param(
            "Fillet2",
            "7-Nowhere",
            "cosmetic",
            "a fillet belongs in 3-Core or 6-Quarantine",
            "decide_fillet.group",
            id="no-such-group",
        ),
        pytest.param(
            "Fillet1",
            QUARANTINE,
            "cosmetic",
            "this fillet has dependents; Quarantine requires none",
            "decide_fillet.quarantine_has_dependents",
            id="has-dependents",
        ),
        pytest.param(
            "Fillet3",
            QUARANTINE,
            "cosmetic",
            "this fillet's dependents could not be read; Quarantine requires none",
            "decide_fillet.dependents_unreadable",
            id="dependents-unreadable",
        ),
        pytest.param(
            "Fillet2",
            CORE,
            "",
            "rationale required",
            "decide_fillet.rationale",
            id="empty-rationale",
        ),
        pytest.param(
            "Fillet2",
            CORE,
            "x" * 301,
            "rationale required",
            "decide_fillet.rationale",
            id="rationale-too-long",
        ),
    ],
)
def test_decide_fillet_rejections(
    judgement: remodel_plan.RemodelToolContext,
    feature_name: str | None,
    group: str,
    rationale: str,
    reason: str,
    rule: str,
) -> None:
    feature_id = "feat:9999" if feature_name is None else IDS[feature_name]

    result = remodel_plan.decide_fillet(feature_id, group, rationale)

    assert result == {"error": reason}
    rejection = only_rejection(judgement)
    assert rejection.tool == "decide_fillet"
    assert rejection.reason == reason
    assert rejection.rule == rule
    assert rejection.arguments == {
        "feature_id": feature_id,
        "group": group,
        "rationale": rationale,
    }
    nothing_accepted(judgement)


def test_a_fillet_nobody_decided_keeps_the_planners_core_target(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    """The default is `3-Core`, which never violates `rms.quarantine.has_no_children`, and
    it is the planner's target rather than anything this tool writes."""
    planned = {item.feature_id: item for item in judgement.plan.targets}

    assert planned[IDS["Fillet1"]].target_group == CORE
    assert planned[IDS["Fillet1"]].decided_by == "planner"
    assert judgement.targets == []


def test_an_accepted_unknown_classification_writes_a_target_and_a_deviation(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    subject = IDS["Deform1"]

    result = remodel_plan.classify_unknown(subject, MODIFY, "it deforms the body in place")

    assert result == {"feature_id": subject, "group": MODIFY}
    target = judgement.targets[0]
    assert (target.feature_id, target.target_group) == (subject, MODIFY)
    assert target.decided_by == "model"
    assert target.basis == "model_judgement"
    assert target.state == "resolved"
    deviation = judgement.deviations[0]
    assert deviation.kind == "unknown_classified_by_model"
    assert deviation.feature_id == subject
    assert deviation.chosen == MODIFY
    assert deviation.rationale == "it deforms the body in place"
    assert deviation.report_line
    assert judgement.rejected_proposals == []


@pytest.mark.parametrize(
    ("feature_name", "group", "rationale", "reason", "rule"),
    [
        pytest.param(
            None,
            MODIFY,
            "it deforms",
            "unknown feature id",
            "classify_unknown.unknown_feature",
            id="unknown-id",
        ),
        pytest.param(
            "Boss-Extrude1",
            MODIFY,
            "it deforms",
            "this feature already has a class",
            "classify_unknown.already_classified",
            id="already-classified",
        ),
        pytest.param(
            "Right Plane",
            MODIFY,
            "it deforms",
            "not a content feature",
            "classify_unknown.not_content",
            id="not-content",
        ),
        pytest.param(
            "Deform1",
            "7-Nowhere",
            "it deforms",
            "group must be one of the six",
            "classify_unknown.group",
            id="no-such-group",
        ),
        pytest.param(
            "Deform1",
            MODIFY,
            "",
            "rationale required",
            "classify_unknown.rationale",
            id="empty-rationale",
        ),
        pytest.param(
            "Deform1",
            MODIFY,
            "x" * 301,
            "rationale required",
            "classify_unknown.rationale",
            id="rationale-too-long",
        ),
    ],
)
def test_classify_unknown_rejections(
    judgement: remodel_plan.RemodelToolContext,
    feature_name: str | None,
    group: str,
    rationale: str,
    reason: str,
    rule: str,
) -> None:
    feature_id = "feat:9999" if feature_name is None else IDS[feature_name]

    result = remodel_plan.classify_unknown(feature_id, group, rationale)

    assert result == {"error": reason}
    rejection = only_rejection(judgement)
    assert rejection.tool == "classify_unknown"
    assert rejection.reason == reason
    assert rejection.rule == rule
    nothing_accepted(judgement)


@pytest.mark.parametrize("tool", ["decide_fillet", "classify_unknown"])
def test_a_second_decision_for_one_feature_is_refused(
    judgement: remodel_plan.RemodelToolContext, tool: str
) -> None:
    """Two targets for one feature is not a partition; the second call is a rejection."""
    subject, group = (
        (IDS["Fillet2"], QUARANTINE)
        if tool == "decide_fillet"
        else (IDS["Deform1"], MODIFY)
    )
    call = getattr(remodel_plan, tool)
    call(subject, group, "the first decision")

    result = call(subject, group, "the second decision")

    assert result == {"error": "already decided for this feature"}
    assert len(judgement.targets) == 1
    assert only_rejection(judgement).rule == f"{tool}.already_decided"


# --- 4. get_remodel_plan and the registration (T114) ------------------------------


@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_reads_back_and_writes_nothing(
    judgement: remodel_plan.RemodelToolContext, section: str
) -> None:
    before = (
        list(judgement.descriptions),
        list(judgement.globals),
        list(judgement.targets),
        list(judgement.deviations),
        list(judgement.rejected_proposals),
    )

    result = remodel_plan.get_remodel_plan(section)

    assert result is not None
    assert not (isinstance(result, dict) and "error" in result)
    assert before == (
        judgement.descriptions,
        judgement.globals,
        judgement.targets,
        judgement.deviations,
        judgement.rejected_proposals,
    )


def test_an_unknown_section_is_an_error_result(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    assert remodel_plan.get_remodel_plan("changes") == {"error": "unknown section"}
    assert judgement.rejected_proposals == []


def test_the_read_back_shows_a_proposal_after_validation(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    remodel_plan.propose_description(IDS["Shell1"], "Wall thickness for the casting")
    remodel_plan.propose_description(IDS["Shell1"], "again")
    remodel_plan.classify_unknown(IDS["Deform1"], MODIFY, "it deforms the body in place")

    descriptions = remodel_plan.get_remodel_plan("descriptions")
    rejections = remodel_plan.get_remodel_plan("rejected_proposals")
    targets = remodel_plan.get_remodel_plan("targets")
    deviations = remodel_plan.get_remodel_plan("deviations")

    assert [row["feature_id"] for row in descriptions] == [IDS["Shell1"]]
    assert [row["rule"] for row in rejections] == ["propose_description.duplicate"]
    decided = [row for row in targets if row["feature_id"] == IDS["Deform1"]]
    assert len(decided) == 1, "the model's target replaces the planner's, never joins it"
    assert decided[0]["decided_by"] == "model"
    assert decided[0]["target_group"] == MODIFY
    assert len(targets) == len(judgement.plan.targets)
    assert any(row["kind"] == "unknown_classified_by_model" for row in deviations)


def test_the_summary_section_counts_what_the_plan_holds(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    summary = remodel_plan.get_remodel_plan("summary")

    assert summary["document_id"] == judgement.plan.document_id
    assert summary["targets"] == len(judgement.plan.targets)
    assert summary["descriptions"] == 0


def test_the_read_back_never_returns_a_path_or_the_package(
    judgement: remodel_plan.RemodelToolContext,
) -> None:
    """The tool reads the plan and nothing else in the run folder."""
    text = "".join(str(remodel_plan.get_remodel_plan(section)) for section in SECTIONS)

    assert "copy_path" not in text
    assert "source_attestation" not in text
    assert ".SLDPRT" not in text


# --- the registration -------------------------------------------------------------


def test_the_registration_returns_the_five_tools_in_contract_order() -> None:
    assert [function.__name__ for function in remodel_tools()] == list(REMODEL_TOOL_NAMES)


def test_a_context_with_no_remodel_plan_is_offered_the_list_it_is_offered_today() -> None:
    """With `remodel` unset the offered list is byte-identical to today's."""
    context = context_for(PACKAGE)

    offered = ToolRegistry().functions_for(context)

    assert offered == TOOL_FUNCTIONS
    assert set(REMODEL_TOOL_NAMES).isdisjoint(
        function.__name__ for function in offered
    )


def test_a_remodel_context_is_offered_them_the_way_a_bridge_context_is() -> None:
    context = context_for(PACKAGE)
    context.remodel = judgement_context()

    offered = ToolRegistry().functions_for(context)

    assert offered == (*TOOL_FUNCTIONS, *remodel_tools())


def test_the_remodel_tools_are_in_no_curated_list() -> None:
    curated = {function.__name__ for function in TOOL_FUNCTIONS}

    assert curated.isdisjoint(REMODEL_TOOL_NAMES)


def test_no_remodel_tool_is_in_the_mcp_list_or_the_terminal_profile() -> None:
    """One tool on this page in either list is one the engineer could call from the
    terminal or from general chat, neither of which has a plan to write into."""
    mcp = {
        function.__name__ for function in MCP_TOOL_FUNCTIONS + MCP_BRIDGE_TOOL_FUNCTIONS
    }

    assert mcp.isdisjoint(REMODEL_TOOL_NAMES)
    assert set(contract_enabled_tools()).isdisjoint(REMODEL_TOOL_NAMES)


def test_no_remodel_tool_names_a_document_a_path_or_a_run_folder() -> None:
    """`contracts/tools.md`, "What is deliberately absent": no tool here can name where
    anything is, so none of them can cause a write outside the plan object."""
    forbidden = {"path", "document", "document_id", "run_dir", "persist_ref"}
    arguments = {
        name
        for function in remodel_tools()
        for name in canonical_schema(function)["properties"]
    }

    assert arguments.isdisjoint(forbidden)
