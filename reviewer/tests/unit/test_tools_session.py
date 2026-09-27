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
from pathlib import Path
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
from tests.support.packages import build_package, persist_ref
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


# --- request_evidence --------------------------------------------------------------------------


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


# --- request_evidence's short form (feature 009 T035, contracts/questions.md 1) ----------------

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
        # Edited deliberately by feature 013 T119: every answer lists the items still open.
        "open_items": [
            item.id for item in context.checklist.items if item.owner == "model"
        ],
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


# --- mark_coverage -----------------------------------------------------------------------------


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


# --- record_drawing_finding --------------------------------------------------------------------


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


# --- get_review_checklist ----------------------------------------------------------------------


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


# --- request_capture ---------------------------------------------------------------------------


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


# --- get_finding (feature 008 T062) ------------------------------------------------------------


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


# --- feature 013 T061: code-owned items answer `closed_by_code` (re-ask-guard.md section 1) --


def closed_scope() -> CoverageScope:
    return CoverageScope(document_ids=["doc:1"])


def held(tool_context: ToolContext) -> dict[str, int]:
    """How many of each record the session holds: nothing may move on `closed_by_code`."""
    held_session = tool_context.require_session()
    return {
        "requests": len(held_session.evidence_requests),
        "findings": len(held_session.findings),
        **{
            bucket: len(getattr(held_session.coverage, bucket))
            for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        },
    }


def test_mark_coverage_on_provenance_is_closed_by_code_with_the_recorded_reason(
    context: ToolContext, emitted: list[tuple[str, dict]]
) -> None:
    from swreview.agent.runner import record_provenance

    record_provenance(context)
    [row] = context.session.coverage.checked
    emitted.clear()
    before = held(context)

    result = session.mark_coverage("provenance", "checked", closed_scope(), "vault checked")

    assert result == {
        "status": "closed_by_code",
        "check": "provenance",
        "reason": row.reason,
        "open_items": model_items(context),
    }
    assert held(context) == before
    assert emitted == []


def test_without_a_recorded_row_the_reason_is_the_items_own_description(
    context: ToolContext,
) -> None:
    item = next(entry for entry in context.checklist.items if entry.id == "provenance")

    result = session.mark_coverage("provenance", "unresolved", closed_scope(), "why not")

    assert result == {
        "status": "closed_by_code",
        "check": "provenance",
        "reason": item.description,
        "open_items": model_items(context),
    }


def test_a_code_owned_item_is_closed_by_code_whatever_bucket_is_asked(
    context: ToolContext,
) -> None:
    result = session.mark_coverage("provenance", "failed", closed_scope(), "x")  # type: ignore[arg-type]

    assert result["status"] == "closed_by_code"
    assert "error" not in result


def test_request_evidence_blocking_provenance_is_closed_by_code_and_takes_no_id(
    context: ToolContext, emitted: list[tuple[str, dict]]
) -> None:
    before = held(context)

    result = session.request_evidence(
        what="The vault version of doc:1",
        why="provenance",
        entity_ids=["doc:1"],
        question="Is this the latest vault version?",
        blocks="provenance",
    )

    assert result["status"] == "closed_by_code"
    assert result["check"] == "provenance"
    assert held(context) == before
    assert emitted == []
    following = session.request_evidence(what="The bolt torque", why="preload", entity_ids=[])
    assert following["evidence_request"]["id"] == "ER-001"


def test_the_four_refusals_still_come_before_closed_by_code(context: ToolContext) -> None:
    unknown = session.request_evidence(
        what="w", why="y", entity_ids=["cmp:9999"], blocks="provenance"
    )
    too_long = session.request_evidence(
        what="w", why="y", entity_ids=[], question="q" * 141, blocks="provenance"
    )

    assert "error" in unknown and "error" in too_long


def test_through_the_registry_closed_by_code_writes_no_failed_row(
    make_package: MakePackage,
) -> None:
    tool_context = context_for(make_package())
    tools = ToolRegistry().dispatch(tool_context)

    tools.call("mark_coverage", {
        "check": "provenance", "bucket": "checked", "scope": {}, "reason": "r",
    })
    tools.call("request_evidence", {
        "what": "w", "why": "y", "entity_ids": [], "blocks": "provenance",
    })

    recorded = tool_context.require_session()
    assert recorded.coverage.failed == []
    assert [step.status for step in recorded.steps] == ["ok", "ok"]
    assert recorded.evidence_requests == []


def test_a_model_owned_item_is_still_recorded(context: ToolContext) -> None:
    result = session.mark_coverage("fasteners", "checked", closed_scope(), "all engage")

    assert result["status"] == "recorded"


# --- feature 013 T063: the re-ask guard (re-ask-guard.md section 3) ----------------------------

ANSWERED_NOTE = (
    "{id} answered this. Use that answer and record the check with it; if it is not enough, "
    "mark the check unresolved quoting it. To ask something different, name the specific hole, "
    "fastener or face."
)
ASKED_NOTE = "{id} already asks this; wait for the engineer's answer."


def ask(**fields: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {"what": "a value", "why": "a reason", "entity_ids": []}
    arguments.update(fields)
    return session.request_evidence(**arguments)


def answer(tool_context: ToolContext, request_id: str, text: str, minute: int = 0) -> None:
    from datetime import UTC, datetime

    request = next(
        item for item in tool_context.require_session().evidence_requests if item.id == request_id
    )
    request.status = "answered"
    request.answer = text
    request.answered_at = datetime(2026, 9, 26, 10, minute, tzinfo=UTC)


def test_a_question_an_answered_request_covers_is_answered_from_it(
    context: ToolContext, emitted: list[tuple[str, dict]]
) -> None:
    ask(question="What fit class is the pin in the plate?", blocks="interfaces.fit",
        entity_ids=["cmp:0001", "cmp:0002"])
    answer(context, "ER-001", "press fit")
    emitted.clear()
    before = held(context)

    result = ask(question="Give the numeric limits of the press fit", blocks="interfaces.fit",
                 entity_ids=["cmp:0002"])

    assert result == {
        "status": "already_answered",
        "evidence_request": {
            "id": "ER-001",
            "question": "What fit class is the pin in the plate?",
            "answer": "press fit",
            "answered_at": "2026-09-26T10:00:00Z",
            "blocks": "interfaces.fit",
            "entity_ids": ["cmp:0001", "cmp:0002"],
        },
        "note": ANSWERED_NOTE.format(id="ER-001"),
        "open_items": model_items(context),
    }
    assert held(context) == before
    assert emitted == []
    assert ask(what="another", entity_ids=["hole:1"])["evidence_request"]["id"] == "ER-002"


def test_a_request_with_no_question_is_cited_by_its_what(context: ToolContext) -> None:
    ask(what="The usable thread depth of hole:1", blocks="fasteners", entity_ids=["hole:1"])
    answer(context, "ER-001", "12 mm")

    result = ask(what="Thread depth again", blocks="fasteners", entity_ids=["hole:1"])

    assert result["evidence_request"]["what"] == "The usable thread depth of hole:1"
    assert "question" not in result["evidence_request"]


def test_a_question_an_open_request_covers_is_already_asked(context: ToolContext) -> None:
    ask(question="What fit class?", blocks="interfaces.fit", entity_ids=["cmp:0001"])

    result = ask(question="Which fit, please?", blocks="interfaces.fit", entity_ids=["cmp:0001"])

    assert result["status"] == "already_asked"
    assert result["evidence_request"]["id"] == "ER-001"
    assert result["evidence_request"]["answer"] is None
    assert result["note"] == ASKED_NOTE.format(id="ER-001")
    assert len(context.session.evidence_requests) == 1


def test_the_most_recent_answer_wins(context: ToolContext) -> None:
    ask(question="Fit?", blocks="interfaces.fit", entity_ids=["cmp:0001"])
    ask(question="Fit, both parts?", blocks="interfaces.fit", entity_ids=["cmp:0001", "cmp:0002"])
    answer(context, "ER-002", "slip fit", minute=1)
    answer(context, "ER-001", "press fit", minute=5)

    result = ask(question="Fit again?", blocks="interfaces.fit", entity_ids=["cmp:0001"])

    assert result["evidence_request"]["id"] == "ER-001"
    assert result["evidence_request"]["answer"] == "press fit"


def test_an_answered_request_is_cited_before_an_open_one(context: ToolContext) -> None:
    ask(question="Fit?", blocks="interfaces.fit", entity_ids=["cmp:0001"])
    answer(context, "ER-001", "press fit")
    ask(question="Fit of both?", blocks="interfaces.fit", entity_ids=["cmp:0001", "cmp:0002"])

    result = ask(question="Fit again?", blocks="interfaces.fit", entity_ids=["cmp:0001"])

    assert result["status"] == "already_answered"
    assert result["evidence_request"]["id"] == "ER-001"


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        ({"blocks": "interfaces.fit", "entity_ids": ["cmp:0001"]},
         {"blocks": "interfaces.fit", "entity_ids": ["cmp:0001", "cmp:0002"]}),
        ({"blocks": "interfaces.fit", "entity_ids": ["cmp:0001", "hole:1"]},
         {"blocks": "interfaces.fit", "entity_ids": ["cmp:0001", "cmp:0002"]}),
        ({"blocks": "interfaces.fit", "entity_ids": ["cmp:0001"]},
         {"blocks": "fasteners", "entity_ids": ["cmp:0001"]}),
        ({"blocks": None, "entity_ids": ["cmp:0001"]},
         {"blocks": "interfaces.fit", "entity_ids": ["cmp:0001"]}),
        ({"blocks": "interfaces.fit", "entity_ids": ["cmp:0001"]},
         {"blocks": "interfaces.fit", "entity_ids": []}),
        ({"blocks": None, "entity_ids": []},
         {"blocks": None, "entity_ids": []}),
    ],
    ids=["superset", "partial-overlap", "other-blocks", "null-versus-an-item",
         "empty-against-ids", "no-item-no-ids-twice"],
)
def test_a_question_the_answer_does_not_cover_is_recorded(
    context: ToolContext, earlier: dict[str, Any], later: dict[str, Any]
) -> None:
    ask(question="First?", **earlier)
    answer(context, "ER-001", "an answer")

    result = ask(question="Second?", **later)

    assert result["status"] == "open"
    assert result["evidence_request"]["id"] == "ER-002"


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        ({"blocks": None, "entity_ids": ["cmp:0001", "cmp:0002"]},
         {"blocks": None, "entity_ids": ["cmp:0002"]}),
        ({"blocks": "interfaces.stack", "entity_ids": []},
         {"blocks": "interfaces.stack", "entity_ids": []}),
        ({"blocks": "interfaces.fit", "entity_ids": ["cmp:0001", "cmp:0002"]},
         {"blocks": "interfaces.fit", "entity_ids": ["cmp:0002", "cmp:0001"]}),
    ],
    ids=["no-item-subset-pinned", "item-and-no-ids-twice", "same-ids-other-order"],
)
def test_a_question_the_answer_covers_is_not_recorded(
    context: ToolContext, earlier: dict[str, Any], later: dict[str, Any]
) -> None:
    """The first case is pinned on purpose (research R2.22): a model question with no checklist
    item naming a subset of an answered model question's parts, also with no item, is covered."""
    ask(question="First?", **earlier)
    answer(context, "ER-001", "an answer")

    result = ask(question="Second?", **later)

    assert result["status"] == "already_answered"


def test_a_code_written_request_covers_only_itself(context: ToolContext) -> None:
    """The part-roles question has no checklist item and names the unclear parts; answered, it
    never answers a later model question about one of them."""
    session.record_evidence_request(
        context,
        "Parts no rule tells apart: housing.SLDPRT",
        "Bought parts are not graded.",
        ["doc:2"],
        question="Are these bought parts?",
        options=["All bought", "None bought"],
        allow_text=True,
        source="code",
    )
    answer(context, "ER-001", "All bought")

    result = ask(question="What material is the housing?", entity_ids=["doc:2"])

    assert result["status"] == "open"
    assert result["evidence_request"]["id"] == "ER-002"


def test_an_unknown_id_is_still_refused_before_the_guard(context: ToolContext) -> None:
    ask(question="Fit?", blocks="interfaces.fit", entity_ids=["cmp:0001"])
    answer(context, "ER-001", "press fit")

    result = ask(question="Fit?", blocks="interfaces.fit", entity_ids=["cmp:0001", "cmp:9999"])

    assert "error" in result


def test_through_the_registry_a_covered_question_writes_no_failed_row(
    make_package: MakePackage,
) -> None:
    tool_context = context_for(make_package())
    tools = ToolRegistry().dispatch(tool_context)
    arguments = {"what": "w", "why": "y", "entity_ids": ["cmp:0001"], "blocks": "interfaces.fit"}
    tools.call("request_evidence", arguments)
    answer(tool_context, "ER-001", "press fit")

    covered = tools.call("request_evidence", {**arguments, "what": "again"})

    assert covered.payload["status"] == "already_answered"
    assert not covered.is_error
    assert tool_context.require_session().coverage.failed == []
    assert len(tool_context.require_session().evidence_requests) == 1


def sitting_package() -> EvidencePackage:
    """The sitting's shape, fictional: an assembly (doc:0001), a plate with a same-name drawing
    beside it (doc:0002, cmp:0001) and a pin (doc:0003, cmp:0002 and cmp:0003)."""
    from tests.support.drawings import DrawingBuilder
    from tests.support.mechanical import PackageBuilder

    builder = PackageBuilder(design_stem="FICT-7000", schema_version="1.6.0")
    plate = builder.document("FICT-7001", "part")
    builder.component(plate)
    pin = builder.document("FICT-KALO-PIN", "part")
    builder.component(pin)
    builder.component(pin)
    drawings = DrawingBuilder(builder.build().package)
    drawings.candidate(plate)
    return drawings.build()


def test_the_sittings_eight_question_calls_come_back_answered_from_the_record() -> None:
    """The 2026-09-26 sitting's shape, with fictional ids: questions asked and answered, then
    three re-asks - provenance in other words, the vendor pin's drawing, and the fit follow-up.

    Edited deliberately by T086: row 6 answers the model's drawing requests - the sitting's
    ER-003 and its re-ask ER-007 - `closed_by_code` before the guard is reached, so neither is
    recorded; the provenance and fit re-asks (the sitting's ER-006 and ER-008) still come back
    `already_answered`, citing the requests they repeat."""
    tool_context = context_for(sitting_package())
    with use_context(tool_context):
        asked = [
            ask(question="Is there a drawing for the plate?", entity_ids=["doc:0002"]),
            ask(question="Are these the latest released files?",
                entity_ids=["doc:0001", "doc:0002"]),
            ask(question="Can you provide the pin's drawing?", entity_ids=["doc:0003"],
                blocks="drawing.manufacturing_inputs"),
            ask(question="Is the interference intended?", entity_ids=["cmp:0001", "cmp:0002"],
                blocks="interference"),
            ask(question="What fit class is the pin in the plate?",
                entity_ids=["cmp:0001", "cmp:0002"], blocks="interfaces.fit"),
        ]
        assert [result["status"] for result in asked] == [
            "open", "open", "closed_by_code", "open", "open",
        ]
        for minute, request in enumerate(tool_context.require_session().evidence_requests):
            answer(tool_context, request.id, f"answer {request.id}", minute=minute)

        re_asked = [
            ask(question="Please confirm the vault versions of these files",
                entity_ids=["doc:0002", "doc:0001"]),
            ask(question="Please attach the pin drawing", entity_ids=["doc:0003"],
                blocks="drawing.manufacturing_inputs"),
            ask(question="Give the numeric limits of the press fit", entity_ids=["cmp:0002"],
                blocks="interfaces.fit"),
        ]

    assert [result["status"] for result in re_asked] == [
        "already_answered", "closed_by_code", "already_answered",
    ]
    assert re_asked[0]["evidence_request"]["id"] == "ER-002"
    assert re_asked[2]["evidence_request"]["id"] == "ER-004"
    assert len(tool_context.require_session().evidence_requests) == 4


# --- feature 013 T086: code answers drawing requests (drawing-capability.md section 5) ---------

DRAWING_ITEM = "drawing.manufacturing_inputs"


def drawings_context(*, attach_plate: bool = False, toolbox_pin: bool = True) -> ToolContext:
    """A review context: the plate (doc:0002) has a candidate, or an attached drawing; the pin
    (doc:0003) is a Toolbox part, so bought, unless told otherwise; roles attached from a
    version 3 profile whose convention the assembly and the plate follow."""
    from swreview.checks import part_roles
    from swreview.checks.standards.profile import load_profile
    from swreview.tools.registry import PART_ROLES_ATTRIBUTE
    from tests.support.drawings import DrawingBuilder
    from tests.support.mechanical import PackageBuilder
    from tests.support.roles_review import write_profile

    builder = PackageBuilder(design_stem="FICT-7000", schema_version="1.6.0")
    plate = builder.document("FICT-7001", "part")
    builder.component(plate)
    pin = builder.document("FICT-KALO-PIN", "part")
    builder.component(pin)
    drawings = DrawingBuilder(builder.build().package)
    if attach_plate:
        record = drawings.drawing(drawings.drawing_document("FICT-7001"))
        drawings.view(drawings.sheet(record, "Sheet1"), "Drawing View1", references=plate)
    else:
        drawings.candidate(plate)
    package = drawings.build()
    if toolbox_pin:
        package = package.model_copy(
            update={
                "components": [
                    item.model_copy(update={"is_toolbox": item.document_id == pin})
                    for item in package.components
                ]
            }
        )
    tool_context = context_for(package)
    import tempfile

    folder = Path(tempfile.mkdtemp())
    roles = part_roles.classify_parts(package, load_profile(write_profile(folder)))
    setattr(tool_context, PART_ROLES_ATTRIBUTE, roles)
    return tool_context


def expected_states(tool_context: ToolContext, document_ids: list[str]) -> list[dict[str, str]]:
    """What lane D's `drawing_states` says of each document: row 6 passes it through."""
    from swreview.checks.drawing_context import drawing_states
    from swreview.drawings.evidence import DrawingIndex
    from swreview.tools.registry import PART_ROLES_ATTRIBUTE

    states = drawing_states(
        DrawingIndex.for_package(tool_context.ir),
        getattr(tool_context, PART_ROLES_ATTRIBUTE),
        tool_context.drawing_read_mode(),
    )
    return [
        {"document_id": item, "state": states[item].state, "reason": states[item].reason}
        for item in document_ids
    ]


def test_a_drawing_request_on_documents_with_no_attached_drawing_is_closed_by_code() -> None:
    tool_context = drawings_context()
    with use_context(tool_context):
        before = held(tool_context)
        result = session.request_evidence(
            what="The drawings", why="drawing inputs", entity_ids=["doc:0002", "doc:0003"],
            blocks=DRAWING_ITEM,
        )

    assert result == {
        "status": "closed_by_code",
        "check": DRAWING_ITEM,
        "drawings": expected_states(tool_context, ["doc:0002", "doc:0003"]),
        "attached": [],
        "open_items": model_items(tool_context),
    }
    assert [item["state"] for item in result["drawings"]] == ["candidate", "bought"]
    assert held(tool_context) == before


def test_a_component_a_hole_or_a_fastener_names_its_document() -> None:
    tool_context = drawings_context()
    plate_instance = next(
        item.id for item in tool_context.ir.components if item.document_id == "doc:0002"
    )
    with use_context(tool_context):
        result = session.request_evidence(
            what="w", why="y", entity_ids=[plate_instance, "doc:0002"], blocks=DRAWING_ITEM
        )

    assert [item["document_id"] for item in result["drawings"]] == ["doc:0002"]


def test_a_hole_and_a_fastener_name_their_components_document() -> None:
    """The minimal package with a candidate beside its part: `hole:1` sits on `cmp:0001` and
    `fst:1` on `cmp:0002`, both instances of `doc:2`; with no review, the roles are the
    no-profile ones, so the part is graded and its candidate is named."""
    from swreview.ir.models import DrawingCandidate

    package = build_package(
        drawing_candidates=[
            DrawingCandidate(
                document_id="doc:2", path="C:\\Fictional\\housing.SLDDRW",
                reason="same_name_beside_model",
            )
        ]
    )
    tool_context = context_for(package)
    with use_context(tool_context):
        by_hole = session.request_evidence(what="w", why="y", entity_ids=["hole:1"],
                                           blocks=DRAWING_ITEM)
        by_fastener = session.request_evidence(what="w", why="y", entity_ids=["fst:1"],
                                               blocks=DRAWING_ITEM)

    for result in (by_hole, by_fastener):
        assert result["status"] == "closed_by_code"
        assert [item["document_id"] for item in result["drawings"]] == ["doc:2"]
        assert result["drawings"][0]["state"] == "candidate"


def test_an_id_that_names_no_document_is_recorded_as_before() -> None:
    tool_context = drawings_context()
    with use_context(tool_context):
        result = session.request_evidence(what="w", why="y", entity_ids=[], blocks=DRAWING_ITEM)

    assert result["status"] == "open"


def test_a_mix_names_both_groups() -> None:
    tool_context = drawings_context(attach_plate=True)
    with use_context(tool_context):
        result = session.request_evidence(
            what="w", why="y", entity_ids=["doc:0002", "doc:0003"], blocks=DRAWING_ITEM
        )

    assert result["status"] == "closed_by_code"
    assert [item["document_id"] for item in result["drawings"]] == ["doc:0003"]
    assert result["attached"] == ["doc:0002"]


def test_a_request_about_a_document_whose_drawing_is_attached_is_recorded() -> None:
    tool_context = drawings_context(attach_plate=True)
    with use_context(tool_context):
        result = session.request_evidence(
            what="The thread callout", why="y", entity_ids=["doc:0002"], blocks=DRAWING_ITEM
        )

    assert result["status"] == "open"


def test_without_drawing_evidence_a_drawing_request_is_recorded(context: ToolContext) -> None:
    """The family is offered only on drawing evidence, and so is the closure: without it no
    drawing phase said what sits beside a document, and nothing may be claimed of it."""
    result = session.request_evidence(
        what="The drawing", why="y", entity_ids=["doc:2"], blocks=DRAWING_ITEM
    )

    assert result["status"] == "open"


def test_mark_coverage_on_the_drawing_item_is_closed_by_code_only_in_the_predicates_state(
) -> None:
    closed = drawings_context()
    owned = drawings_context(attach_plate=True)

    plate = CoverageScope(document_ids=["doc:0002"])
    with use_context(closed):
        closed_result = session.mark_coverage(DRAWING_ITEM, "unresolved", plate, "r")
    with use_context(owned):
        owned_result = session.mark_coverage(DRAWING_ITEM, "checked", plate, "r")

    assert closed_result["status"] == "closed_by_code"
    assert closed_result["check"] == DRAWING_ITEM
    assert closed.require_session().coverage.checked == []
    assert closed.require_session().coverage.unresolved == []
    assert owned_result["status"] == "recorded"


def test_mark_coverage_on_the_drawing_item_without_drawing_evidence_is_recorded(
    context: ToolContext,
) -> None:
    result = session.mark_coverage(DRAWING_ITEM, "out_of_scope", closed_scope(), "no drawings")

    assert result["status"] == "recorded"


def test_the_mode_is_asked_only_when_a_custom_document_has_a_candidate() -> None:
    from tests.unit.test_context_drawing_read import PingingBridge

    with_candidate = drawings_context()
    attached = drawings_context(attach_plate=True)
    for tool_context in (with_candidate, attached):
        tool_context.bridge = PingingBridge("open_only")
        with use_context(tool_context):
            session.request_evidence(
                what="w", why="y", entity_ids=["doc:0003"], blocks=DRAWING_ITEM
            )

    assert with_candidate.bridge.pings == 1
    assert attached.bridge.pings == 0


DRAWING_DESCRIPTION = (
    "For each custom part or assembly: its drawing is the same-name .SLDDRW in its folder; bought "
    "parts have none. check_drawings decides which drawings exist and tells the engineer how to "
    "include one; never request a drawing or a drawing's version."
)


def test_the_drawing_items_description_is_the_contracts() -> None:
    from swreview.agent.checklist import load_checklist

    item = next(entry for entry in load_checklist().items if entry.id == DRAWING_ITEM)

    assert item.description == DRAWING_DESCRIPTION
    assert item.owner == "model"


def test_system_prompt_step_6_says_never_to_request_a_drawing() -> None:
    from tests.unit.test_system_prompt_013 import steps

    assert steps()["6"].endswith(
        "check_drawings decides which drawings exist and tells the engineer how to include "
        "one; never request a drawing or a drawing's version."
    )


# --- feature 013 T065: the ids the tools hand out are accepted (re-ask-guard.md section 4) -----

DRAWINGS = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"


def drawing_ids(package: EvidencePackage) -> dict[str, str]:
    """`{id: kind}` for every sheet, view, dimension, annotation and note the package holds."""
    found: dict[str, str] = {}
    for record in package.drawing_records:
        for sheet in record.sheets:
            found[sheet.id] = "drawing_sheet"
            for view in sheet.views:
                found[view.id] = "drawing_view"
                found.update({item.id: "drawing_dimension" for item in view.display_dimensions})
                found.update({item.id: "drawing_annotation" for item in view.annotations})
                found.update({item.id: "drawing_note" for item in view.notes})
    return found


def test_a_joint_id_is_accepted_after_check_joints_hands_it_out() -> None:
    from tests.unit.test_joint_map import pattern_package

    tool_context = context_for(pattern_package())
    tools = ToolRegistry().dispatch(tool_context)
    tools.call("check_joints", {})
    joint_id = next(iter(tool_context.joint_analysis.joint_map.joints)).id
    handed_out = json.dumps(
        [finding.model_dump(mode="json") for finding in tool_context.require_session().findings]
    )
    assert joint_id.startswith("jnt:") and joint_id in handed_out

    with use_context(tool_context):
        result = session.request_evidence(what="the joint's torque", why="fasteners",
                                          entity_ids=[joint_id])

    assert result["status"] == "open"
    assert tool_context.entity_kind(joint_id) == "joint"


def test_a_joint_id_before_any_joint_map_or_an_unknown_one_is_refused() -> None:
    tool_context = context_for(prerun_package())

    with use_context(tool_context):
        before = session.request_evidence(what="w", why="y", entity_ids=["jnt:0001"])
        ToolRegistry().dispatch(tool_context).call("check_joints", {})
        unknown = session.request_evidence(what="w", why="y", entity_ids=["jnt:9999"])

    assert "error" in before and "jnt:0001" in before["error"]
    assert "error" in unknown and "jnt:9999" in unknown["error"]


def test_a_feature_id_is_accepted() -> None:
    package = prerun_package()
    feature_id = package.features[0].id
    tool_context = context_for(package)

    with use_context(tool_context):
        result = session.request_evidence(what="the sketch", why="modeling.resilience",
                                          entity_ids=[feature_id])
        unknown = session.request_evidence(what="w", why="y", entity_ids=["feat:99999"])

    assert result["status"] == "open"
    assert tool_context.entity_kind(feature_id) == "feature"
    assert "error" in unknown


def test_every_drawing_entity_id_of_the_fixture_is_accepted() -> None:
    from swreview.ir.loader import load_package

    loaded = load_package(DRAWINGS / "plate-drawing")
    tool_context = ToolContext(
        package=loaded, session=context_for(loaded.package).session,
        checklist=context_for(loaded.package).checklist,
    )
    kinds = drawing_ids(loaded.package)
    assert {"drawing_sheet", "drawing_view"} <= set(kinds.values())

    assert {entity_id: tool_context.entity_kind(entity_id) for entity_id in kinds} == kinds
    with use_context(tool_context):
        result = session.request_evidence(what="the note", why="drawing text",
                                          entity_ids=list(kinds))
        unknown = session.request_evidence(what="w", why="y", entity_ids=["dvw:9999"])
    assert result["status"] == "open"
    assert "error" in unknown


def test_a_reloaded_package_answers_for_its_own_drawing_ids() -> None:
    from swreview.ir.loader import load_package

    loaded = load_package(DRAWINGS / "plate-drawing")
    tool_context = context_for(prerun_package())
    some_view = next(entity for entity, kind in drawing_ids(loaded.package).items()
                     if kind == "drawing_view")
    assert tool_context.entity_kind(some_view) is None

    tool_context.reload_package(loaded)

    assert tool_context.entity_kind(some_view) == "drawing_view"


def test_mark_coverage_scope_still_reads_components_and_documents(context: ToolContext) -> None:
    result = session.mark_coverage(
        "fasteners", "checked", CoverageScope(component_ids=["cmp:9999"]), "why"
    )

    assert "error" in result


# --- feature 013 T118: every answer lists the items still open (tokens.md section 2) -----------


def model_items(tool_context: ToolContext) -> list[str]:
    return [item.id for item in tool_context.checklist.items if item.owner == "model"]


def test_a_recorded_coverage_row_lists_the_model_owned_items_still_open(
    context: ToolContext,
) -> None:
    result = session.mark_coverage("fasteners", "checked", closed_scope(), "all engage")

    assert result["open_items"] == [item for item in model_items(context) if item != "fasteners"]
    assert "provenance" not in result["open_items"]
    assert "coverage.closeout" not in result["open_items"]


def test_the_open_items_follow_the_checklists_order(context: ToolContext) -> None:
    for check in ("hygiene", "interference", "interfaces.fit"):
        result = session.mark_coverage(check, "skipped", closed_scope(), "r")

    expected = [
        item for item in model_items(context)
        if item not in {"hygiene", "interference", "interfaces.fit"}
    ]
    assert result["open_items"] == expected


def test_a_recorded_request_lists_them_too_and_its_request_stays_as_it_was(
    context: ToolContext,
) -> None:
    result = session.request_evidence(what="The torque", why="preload", entity_ids=["cmp:0001"])

    assert result["status"] == "open"
    assert set(result) == {"status", "evidence_request", "open_items"}
    assert result["open_items"] == model_items(context)


def test_every_non_error_answer_lists_them(context: ToolContext) -> None:
    ask(question="Fit?", blocks="interfaces.fit", entity_ids=["cmp:0001"])
    closed = session.mark_coverage("provenance", "checked", closed_scope(), "r")
    closed_request = ask(blocks="provenance")
    asked = ask(question="Fit again?", blocks="interfaces.fit", entity_ids=["cmp:0001"])
    answer(context, "ER-001", "press fit")
    answered = ask(question="Fit, once more?", blocks="interfaces.fit", entity_ids=["cmp:0001"])

    for result in (closed, closed_request, asked, answered):
        assert result["open_items"] == model_items(context), result["status"]


def test_the_drawing_answer_lists_them() -> None:
    tool_context = drawings_context()
    with use_context(tool_context):
        result = session.request_evidence(
            what="w", why="y", entity_ids=["doc:0002"], blocks=DRAWING_ITEM
        )

    assert result["status"] == "closed_by_code"
    assert result["open_items"] == model_items(tool_context)


def test_with_every_model_owned_item_closed_the_list_is_empty(context: ToolContext) -> None:
    for check in model_items(context)[:-1]:
        session.mark_coverage(check, "checked", closed_scope(), "r")

    result = session.mark_coverage(model_items(context)[-1], "checked", closed_scope(), "r")

    assert result["open_items"] == []


def test_an_error_carries_no_open_items(context: ToolContext) -> None:
    refused = session.mark_coverage("fasteners", "failed", closed_scope(), "r")  # type: ignore[arg-type]
    unknown = session.request_evidence(what="w", why="y", entity_ids=["cmp:9999"])

    assert set(refused) == {"error"} and set(unknown) == {"error"}


# --- sources: who wrote each record (feature 013 T096, `contracts/sources.md` section 1) --------


def saved(tool_context: ToolContext, tmp_path: Path) -> dict[str, Any]:
    """The session as `session.json` stores it."""
    from swreview.report.session import save_session

    path = save_session(tool_context.require_session(), tmp_path / "session.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_drawing_finding_is_the_models_and_session_json_stores_it(
    context: ToolContext, tmp_path: Path
) -> None:
    result = record_thread_depth_finding()

    finding = context.require_session().findings[-1]
    assert finding.source == "model"
    assert saved(context, tmp_path)["findings"][-1]["source"] == "model"
    assert result["status"] == "recorded"


def test_the_drawing_findings_tool_result_echoes_no_source(context: ToolContext) -> None:
    result = record_thread_depth_finding()

    finding = context.require_session().findings[-1]
    assert "source" not in result["finding"]
    assert result["finding"] == finding.model_dump(mode="json", exclude={"source"})
    assert result == {"status": "recorded", "finding": as_json(finding, exclude={"source"})}


def test_a_marked_coverage_row_is_the_models_and_session_json_stores_it(
    context: ToolContext, tmp_path: Path
) -> None:
    result = session.mark_coverage("fasteners", "unresolved", closed_scope(), "no torque given")

    item = context.require_session().coverage.unresolved[-1]
    assert item.source == "model"
    assert saved(context, tmp_path)["coverage"]["unresolved"][-1]["source"] == "model"
    assert result["status"] == "recorded"


def test_the_coverage_tool_result_echoes_the_row_without_its_source(context: ToolContext) -> None:
    result = session.mark_coverage("fasteners", "unresolved", closed_scope(), "no torque given")

    assert result["coverage_item"] == {
        "check": "fasteners",
        "scope": closed_scope().model_dump(mode="json"),
        "reason": "no torque given",
        "error": None,
    }


def test_a_model_question_is_the_models_and_omitted_from_the_dump(
    context: ToolContext, tmp_path: Path
) -> None:
    result = session.request_evidence(what="The torque", why="preload", entity_ids=[])

    request = context.require_session().evidence_requests[-1]
    assert request.source == "model"
    assert "source" not in result["evidence_request"]
    assert "source" not in saved(context, tmp_path)["evidence_requests"][-1]


def test_get_finding_echoes_a_drawing_finding_without_its_source(context: ToolContext) -> None:
    """`get_finding` returns a finding "exactly as the session records it"; a model-written one
    carries `source: model` there, so it is echoed without it, as its writer's result is, and no
    byte the model reads moves."""
    record_thread_depth_finding()
    finding = context.require_session().findings[-1]

    result = session.get_finding(finding.id)

    assert result == {"finding": as_json(finding, exclude={"source"})}
    assert "source" not in result["finding"]


def test_a_code_finding_keeps_every_byte_of_its_get_finding_result(context: ToolContext) -> None:
    from swreview.findings import build_finding

    finding = build_finding(
        finding_id=next(context.finding_ids),
        check="interference.static",
        title="A code finding",
        status="suspected",
        severity="low",
        package=context.ir,
        configuration="Default",
        observed="A code finding",
        requirement="r",
        recommended_action="a",
        component_ids=["cmp:0001"],
    )
    context.record_finding(finding)

    assert session.get_finding(finding.id) == {"finding": finding.model_dump(mode="json")}
    assert "source" not in session.get_finding(finding.id)["finding"]


def test_the_model_written_records_reach_the_surfaces_as_ai_guidance(
    context: ToolContext,
) -> None:
    """The review of 2026-09-27: with the writers stating `model`, lane R's readers label the
    records - the grouped row's chip, the goal line's detail source - where before they read
    `code` and labelled nothing."""
    from swreview.report.attention import coverage_source, finding_source, load_policy
    from swreview.report.finding_groups import findings_by_type
    from swreview.report.summary import load_words

    record_thread_depth_finding()
    session.mark_coverage("fasteners", "unresolved", closed_scope(), "no torque was given")
    review = context.require_session()
    words = load_words()

    assert finding_source(review.findings[-1]) == "model"
    assert coverage_source(review.coverage.unresolved[-1]) == "model"
    grouped = findings_by_type(review, context.ir, words, load_policy())
    [row] = [
        row
        for group in grouped.groups
        for row in group.rows
        if row.finding_id == review.findings[-1].id
    ]
    assert (row.source, row.chip) == ("model", words.labels.source["model"])
    [fasteners] = [
        line for group in grouped.groups for line in group.goals if line.goal == "fasteners"
    ]
    assert fasteners.detail_source == "model"
