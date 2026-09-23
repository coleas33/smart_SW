"""Unit tests for the session tools (T028).

These are the only tools that write, so each test pins down a rule the model must not be
able to talk its way around: `mark_coverage` cannot claim the `failed` bucket,
`record_drawing_finding` cannot claim a status a calculation would have to support, and
`request_capture` says `unresolved` rather than describing a picture it does not have.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from swreview.agent.providers.schema import (
    MAX_DESCRIPTION_LENGTH,
    MAX_PARAMETER_DESCRIPTION_LENGTH,
    tool_spec,
)
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE
from swreview.ir.models import Capture, EvidencePackage, SourceRef
from swreview.report.session import CoverageScope
from swreview.tools import session
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.model_view import model_view
from swreview.tools.query import as_json
from swreview.tools.registry import ToolRegistry
from tests.support.packages import persist_ref
from tests.support.prerun import prerun_package

MakePackage = Callable[..., EvidencePackage]

SHEET_REF = {"document_id": "doc:2", "sheet": "Sheet1"}


@pytest.fixture
def context(make_package: MakePackage) -> Iterator[ToolContext]:
    tool_context = context_for(make_package())
    with use_context(tool_context):
        yield tool_context


def record_thread_depth_finding(status: str = "suspected") -> dict:
    return session.record_drawing_finding(
        document_id="doc:2",
        sheet="Sheet1",
        observed="The tapped hole is called out without a thread depth",
        requirement="A tapped hole callout states the usable thread depth",
        source_refs=[SourceRef(**SHEET_REF)],
        status=status,  # type: ignore[arg-type]
        recommended_action="Add the tapped depth to the hole callout",
    )


# --- request_evidence ------------------------------------------------------------


def test_request_evidence_opens_a_numbered_request(context: ToolContext) -> None:
    first = session.request_evidence(
        what="The usable thread depth of hole:1",
        why="fastener.engagement cannot be evaluated without it",
        entity_ids=["hole:1", "cmp:0001"],
    )
    assert first["status"] == "open"
    assert first["evidence_request"]["id"] == "ER-001"
    assert first["evidence_request"]["answer"] is None
    assert first["evidence_request"]["answered_at"] is None

    second = session.request_evidence(what="The bolt torque spec", why="preload", entity_ids=[])
    assert second["evidence_request"]["id"] == "ER-002"
    assert [item.id for item in context.session.evidence_requests] == ["ER-001", "ER-002"]
    assert all(item.status == "open" for item in context.session.evidence_requests)


def test_request_evidence_rejects_ids_that_are_not_in_the_package(
    context: ToolContext,
) -> None:
    result = session.request_evidence(what="anything", why="anything", entity_ids=["cmp:9999"])
    assert result == {"error": "entity_ids not in this package: ['cmp:9999']"}
    assert context.session.evidence_requests == []


# --- request_evidence's short form (feature 009 T035, contracts/questions.md 1) ------------

THREAD_DEPTH = {
    "what": "The usable thread depth of hole:1",
    "why": "fastener.engagement cannot be evaluated without it",
    "entity_ids": ["hole:1"],
}


@pytest.fixture
def emitted(context: ToolContext) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    context.emit = lambda event_type, body: events.append((event_type, dict(body)))
    return events


def test_the_short_form_is_recorded_on_the_request(
    context: ToolContext, emitted: list[tuple[str, dict]]
) -> None:
    result = session.request_evidence(
        **THREAD_DEPTH,
        question="What is the usable thread depth of the tapped hole?",
        options=["6 mm", "8 mm", "Through"],
        blocks="fasteners",
    )

    request = context.session.evidence_requests[0]
    assert (request.question, request.options, request.blocks) == (
        "What is the usable thread depth of the tapped hole?",
        ["6 mm", "8 mm", "Through"],
        "fasteners",
    )
    assert result["evidence_request"]["options"] == ["6 mm", "8 mm", "Through"]
    assert [event for event, _ in emitted] == ["evidence.requested"]
    assert emitted[0][1]["blocks"] == "fasteners"


def test_a_request_without_the_short_form_is_recorded_as_before(context: ToolContext) -> None:
    result = session.request_evidence(**THREAD_DEPTH)

    assert result == {
        "status": "open",
        "evidence_request": {
            "id": "ER-001",
            "what": "The usable thread depth of hole:1",
            "why": "fastener.engagement cannot be evaluated without it",
            "entity_ids": ["hole:1"],
            "status": "open",
            "answer": None,
            "answered_at": None,
        },
    }


@pytest.mark.parametrize(
    ("short_form", "names"),
    [
        ({"question": "x" * 141}, ["question", "140", "141"]),
        ({"question": "   "}, ["question", "140"]),
        ({"options": ["a", "b", "c", "d", "e", "f"]}, ["options", "5", "6"]),
        ({"options": ["Press fit", " "]}, ["options[1]", "blank"]),
        ({"options": ["y" * 61]}, ["options[0]", "60", "61"]),
        ({"options": ["Press fit", "Slip fit", "Press fit"]}, ["options", "'Press fit'"]),
        ({"blocks": "nonsense"}, ["blocks", "'nonsense'", "fasteners", "interfaces.fit"]),
    ],
    ids=[
        "question-141",
        "question-blank",
        "six-options",
        "option-blank",
        "option-61",
        "option-repeated",
        "blocks-unknown",
    ],
)
def test_a_short_form_past_its_limits_is_refused_by_name_and_records_nothing(
    context: ToolContext,
    emitted: list[tuple[str, dict]],
    short_form: dict,
    names: list[str],
) -> None:
    result = session.request_evidence(**THREAD_DEPTH, **short_form)

    assert set(result) == {"error"}
    for name in names:
        assert name in result["error"], (name, result["error"])
    assert context.session.evidence_requests == []
    assert emitted == []


def test_the_refusals_come_in_the_contracts_order(context: ToolContext) -> None:
    """Unknown ids first, then the question, then the options, then `blocks`."""
    everything_wrong = {
        "what": "anything",
        "why": "anything",
        "question": "x" * 141,
        "options": ["same", "same"],
        "blocks": "nonsense",
    }

    steps = [
        session.request_evidence(**everything_wrong, entity_ids=["cmp:9999"]),
        session.request_evidence(**everything_wrong, entity_ids=[]),
        session.request_evidence(**{**everything_wrong, "question": None}, entity_ids=[]),
        session.request_evidence(
            **{**everything_wrong, "question": None, "options": None}, entity_ids=[]
        ),
    ]

    assert [result["error"].split(" ", 1)[0] for result in steps] == [
        "entity_ids",
        "question",
        "options",
        "blocks",
    ]
    assert context.session.evidence_requests == []


def test_every_checklist_item_is_a_valid_blocks(context: ToolContext) -> None:
    from swreview.report.attention import CHECKLIST_ITEM_IDS

    for item in CHECKLIST_ITEM_IDS:
        assert "error" not in session.request_evidence(**THREAD_DEPTH, blocks=item)


def test_the_description_and_arguments_stay_under_the_lever_caps() -> None:
    from swreview.agent.providers.schema import (
        MAX_DESCRIPTION_LENGTH,
        MAX_PARAMETER_DESCRIPTION_LENGTH,
        parse_docstring,
    )

    description, arguments, notes = parse_docstring(session.request_evidence.__doc__)

    assert len(description) <= MAX_DESCRIPTION_LENGTH
    assert set(arguments) == {"what", "why", "entity_ids", "question", "options", "blocks"}
    assert all(len(text) <= MAX_PARAMETER_DESCRIPTION_LENGTH for text in arguments.values())
    # The guidance rides on the arguments: the Notes are pinned byte-equal to the pre-split
    # text (`test_docstring_split.py`), and an argument description is on the wire always.
    assert arguments["question"].startswith("One decision")
    assert "never guess a fit class, tolerance or thread depth" in arguments["question"]
    assert "only when the answers are a closed set" in arguments["options"]
    assert "never guess" not in notes.lower()


# --- mark_coverage ---------------------------------------------------------------


def test_mark_coverage_declares_the_scope_it_accepts() -> None:
    """`scope` is a `CoverageScope`, so its keys are in the schema the model is given.

    A `dict[str, Any]` generates `{"type": "object", "additionalProperties": true}` with
    no properties. Strict mode cannot express that, and `CoverageScope.model_validate({})`
    succeeds, so a scope the model got wrong would be recorded as an empty scope with no
    error anywhere.
    """
    schema = TypeAdapter(session.mark_coverage).json_schema()
    scope = schema["properties"]["scope"]
    definition = schema["$defs"][scope["$ref"].rsplit("/", 1)[-1]]

    assert definition["additionalProperties"] is False
    assert set(definition["properties"]) == set(CoverageScope.model_fields)


def test_mark_coverage_writes_the_requested_bucket(context: ToolContext) -> None:
    result = session.mark_coverage(
        check="interference",
        bucket="out_of_scope",
        scope=CoverageScope(component_ids=["cmp:0001"], configuration="Default"),
        reason="no interference results were extracted for this package",
    )
    assert result["status"] == "recorded"
    item = context.session.coverage.out_of_scope[0]
    assert item.check == "interference"
    assert item.scope.component_ids == ["cmp:0001"]
    assert item.scope.configuration == "Default"
    assert item.error is None


def test_mark_coverage_refuses_the_failed_bucket(context: ToolContext) -> None:
    result = session.mark_coverage(
        check="fasteners",
        bucket="failed",  # type: ignore[arg-type]
        scope=CoverageScope(),
        reason="the tool blew up",
    )
    assert "bucket 'failed' is written by the tool layer" in result["error"]
    assert context.session.coverage.failed == []


def test_mark_coverage_refuses_an_unknown_bucket(context: ToolContext) -> None:
    result = session.mark_coverage(
        check="fasteners",
        bucket="passed",  # type: ignore[arg-type]
        scope=CoverageScope(),
        reason="looks fine",
    )
    assert result["error"].startswith("bucket 'passed' is not one of")


def test_mark_coverage_refuses_a_scope_it_cannot_read(context: ToolContext) -> None:
    """A key `CoverageScope` does not have is refused by the parameter type itself.

    `scope` is a `CoverageScope`, not a free-form map, so a field the model invented
    never reaches the tool: it fails argument validation in the registry, which records
    `failed` coverage. What the tool still owns is the ids inside a well-formed scope.
    """
    with pytest.raises(ValidationError):
        CoverageScope(widgets=[])  # type: ignore[call-arg]
    unknown_ids = session.mark_coverage(
        check="fasteners",
        bucket="checked",
        scope=CoverageScope(component_ids=["cmp:9999"]),
        reason="r",
    )
    assert unknown_ids == {"error": "scope names ids not in this package: ['cmp:9999']"}
    assert context.session.coverage.checked == []


# --- record_drawing_finding ------------------------------------------------------


def test_record_drawing_finding_writes_a_suspected_finding(context: ToolContext) -> None:
    result = record_thread_depth_finding()
    finding = result["finding"]
    assert finding["id"] == "F-001"
    assert finding["status"] == "suspected"
    assert finding["severity"] == "medium"
    assert finding["check"] == "drawing.manufacturing_inputs"
    assert finding["calculation"] is None
    assert finding["component_ids"] == []
    assert finding["drawing_locations"][0]["sheet"] == "Sheet1"
    assert finding["provenance"][0]["document_id"] == "doc:2"
    assert finding["title"] == "The tapped hole is called out without a thread depth"
    assert [item.id for item in context.session.findings] == ["F-001"]


def test_record_drawing_finding_gives_an_unresolved_finding_a_coverage_limit(
    context: ToolContext,
) -> None:
    finding = record_thread_depth_finding(status="unresolved")["finding"]
    assert finding["status"] == "unresolved"
    assert finding["severity"] == "low"
    assert finding["coverage_limits"] == [
        "doc:2 sheet Sheet1: the drawing does not state the required value"
    ]


@pytest.mark.parametrize("status", ["demonstrated", "checked_within_scope"])
def test_record_drawing_finding_refuses_a_status_no_calculation_backs(
    context: ToolContext, status: str
) -> None:
    result = record_thread_depth_finding(status=status)
    assert f"status {status!r} is not available to a drawing finding" in result["error"]
    assert context.session.findings == []


def test_record_drawing_finding_needs_a_place_on_the_drawing(context: ToolContext) -> None:
    result = session.record_drawing_finding(
        document_id="doc:2",
        sheet="Sheet1",
        observed="No material callout",
        requirement="Every part drawing states its material",
        source_refs=[],
        status="suspected",
        recommended_action="Add the material to the title block",
    )
    assert result == {"error": "source_refs must name at least one place on the drawing"}


def test_record_drawing_finding_rejects_unknown_documents(context: ToolContext) -> None:
    assert session.record_drawing_finding(
        document_id="doc:9",
        sheet="Sheet1",
        observed="o",
        requirement="r",
        source_refs=[SourceRef(**SHEET_REF)],
        status="suspected",
        recommended_action="a",
    ) == {"error": "unknown document id 'doc:9'"}

    assert session.record_drawing_finding(
        document_id="doc:2",
        sheet="Sheet1",
        observed="o",
        requirement="r",
        source_refs=[{"document_id": "doc:9", "sheet": "Sheet1"}],  # type: ignore[list-item]
        status="suspected",
        recommended_action="a",
    ) == {"error": "unknown document id 'doc:9'"}


def test_record_drawing_finding_accepts_source_refs_as_dicts(context: ToolContext) -> None:
    result = session.record_drawing_finding(
        document_id="doc:2",
        sheet="Sheet1",
        observed="No general tolerance note",
        requirement="Every part drawing states a general tolerance",
        source_refs=[SHEET_REF],  # type: ignore[list-item]
        status="suspected",
        recommended_action="Add the general tolerance note",
    )
    assert result["finding"]["drawing_locations"][0]["document_id"] == "doc:2"


def test_record_drawing_finding_rejects_a_source_ref_without_a_locator(
    context: ToolContext,
) -> None:
    result = session.record_drawing_finding(
        document_id="doc:2",
        sheet="Sheet1",
        observed="o",
        requirement="r",
        source_refs=[{"document_id": "doc:2"}],  # type: ignore[list-item]
        status="suspected",
        recommended_action="a",
    )
    assert result["error"].startswith("source_ref is not valid")


# --- get_review_checklist --------------------------------------------------------


def test_get_review_checklist_starts_every_item_open(context: ToolContext) -> None:
    items = session.get_review_checklist()
    assert [item["id"] for item in items] == [entry.id for entry in context.checklist.items]
    assert {item["bucket"] for item in items} == {"open"}


def test_the_checklist_carries_the_resilient_modeling_item_with_the_rms_prefix(
    context: ToolContext,
) -> None:
    """`modeling.resilience` is closed out by the `rms.*` findings the check tools write.

    The prefix is the whole coupling between the checklist and the RMS rule catalogue
    (`specs/003-resilient-modeling/contracts/tools.md`), so it is asserted against the
    registered rule ids rather than retyped.
    """
    from swreview.checks.rms import RULES

    item = next(entry for entry in context.checklist.items if entry.id == "modeling.resilience")
    assert item.check_prefix == "rms."
    assert all(rule_id.startswith(item.check_prefix) for rule_id in RULES)
    assert "check_rms_part" in item.description


def test_get_review_checklist_reflects_findings_and_coverage(context: ToolContext) -> None:
    record_thread_depth_finding()
    session.mark_coverage(
        check="interference",
        bucket="skipped",
        scope=CoverageScope(),
        reason="no interference results in this package",
    )
    buckets = {item["id"]: item["bucket"] for item in session.get_review_checklist()}
    assert buckets["drawing.manufacturing_inputs"] == "finding"
    assert buckets["interference"] == "skipped"
    assert buckets["fasteners"] == "open"


def test_get_review_checklist_ignores_a_failed_coverage_item(context: ToolContext) -> None:
    """`failed` is the tool layer's bucket; it never closes a checklist item out."""
    from swreview.report.session import CoverageItem

    context.session.coverage.failed.append(
        CoverageItem(
            check="fasteners",
            scope=CoverageScope(),
            reason="tool failed",
            error="RuntimeError: boom",
        )
    )
    buckets = {item["id"]: item["bucket"] for item in session.get_review_checklist()}
    assert buckets["fasteners"] == "open"


# --- request_capture -------------------------------------------------------------


def test_request_capture_is_unresolved_without_a_capture_or_a_bridge(
    context: ToolContext,
) -> None:
    assert session.request_capture(entity_id="cmp:0001", view="iso") == {
        "status": "unresolved",
        "reason": "no capture and no bridge",
    }


def test_request_capture_returns_an_existing_capture(make_package: MakePackage) -> None:
    package = make_package(
        captures=[
            Capture(
                id="cap:1",
                persist_ref=persist_ref("cmp:0001"),
                component_ids=["cmp:0001"],
                file="captures/housing-iso.png",
                view="iso",
                note="isometric of the housing",
            )
        ]
    )
    with use_context(context_for(package)):
        found = session.request_capture(entity_id="cmp:0001", view="iso")
        other_view = session.request_capture(entity_id="cmp:0001", view="front")
    assert found == {"status": "found", "capture": found["capture"]}
    assert found["capture"]["file"] == "captures/housing-iso.png"
    assert other_view["status"] == "found"
    assert "no 'front' capture exists" in other_view["note"]


def test_request_capture_rejects_an_unknown_entity_and_view(context: ToolContext) -> None:
    assert session.request_capture(entity_id="cmp:9999", view="iso") == {
        "error": "unknown entity id 'cmp:9999'"
    }
    result = session.request_capture(entity_id="cmp:0001", view="exploded")  # type: ignore[arg-type]
    assert result["error"].startswith("view 'exploded' is not one of")


# --- get_finding (feature 008 T062) ------------------------------------------------------


def slim_dispatch(tool_context: ToolContext) -> Any:
    return ToolRegistry().dispatch(tool_context, model_view=MODEL_VIEW_PANE)


def rms_finding_context() -> ToolContext:
    """A context whose session holds RMS findings, whose inputs carry inline references."""
    tool_context = context_for(prerun_package())
    ToolRegistry().dispatch(tool_context).call("check_rms_part", {})
    assert tool_context.session is not None and tool_context.session.findings
    return tool_context


def test_get_finding_returns_the_finding_exactly_as_the_session_records_it() -> None:
    tool_context = rms_finding_context()
    finding = tool_context.session.findings[0]  # type: ignore[union-attr]

    with use_context(tool_context):
        result = session.get_finding(finding.id)

    assert result == {"finding": as_json(finding)}


def test_through_a_slim_dispatch_the_view_has_no_reference_and_the_payload_does() -> None:
    tool_context = rms_finding_context()
    finding = next(
        f
        for f in tool_context.session.findings  # type: ignore[union-attr]
        if any("persist_ref=" in str(value) for value in f.inputs)
    )
    refs = {feature.persist_ref for feature in tool_context.ir.features}

    payload = slim_dispatch(tool_context).call("get_finding", {"finding_id": finding.id}).payload
    view = json.dumps(model_view("get_finding", payload))

    assert any(ref in json.dumps(payload) for ref in refs)
    assert not [ref for ref in refs if ref in view]


def test_an_unknown_finding_id_is_an_error_naming_it_and_failed_coverage() -> None:
    tool_context = rms_finding_context()

    result = slim_dispatch(tool_context).call("get_finding", {"finding_id": "F-999"})

    assert result.is_error is True
    assert "F-999" in result.payload["error"]
    assert [item.check for item in tool_context.session.coverage.failed] == [  # type: ignore[union-attr]
        "tool.get_finding"
    ]


def test_a_sessionless_context_gets_an_error_result_never_a_raise(
    make_package: MakePackage,
) -> None:
    general_chat = replace(context_for(make_package()), session=None)

    with use_context(general_chat):
        result = session.get_finding("F-001")

    assert "error" in result


def test_get_finding_describes_itself_within_the_caps() -> None:
    spec = tool_spec(session.get_finding)

    assert len(spec.description) <= MAX_DESCRIPTION_LENGTH
    for described in spec.schema["properties"].values():
        assert len(described.get("description", "")) <= MAX_PARAMETER_DESCRIPTION_LENGTH


def test_get_finding_is_offered_only_with_payload_slimming(make_package: MakePackage) -> None:
    tool_context = context_for(make_package())

    assert "get_finding" not in ToolRegistry().dispatch(tool_context).by_name
    assert "get_finding" not in ToolRegistry().dispatch(
        tool_context, model_view=MODEL_VIEW_OFF
    ).by_name
    assert "get_finding" in slim_dispatch(tool_context).by_name
