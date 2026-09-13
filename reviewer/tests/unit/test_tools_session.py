"""Unit tests for the session tools (T028).

These are the only tools that write, so each test pins down a rule the model must not be
able to talk its way around: `mark_coverage` cannot claim the `failed` bucket,
`record_drawing_finding` cannot claim a status a calculation would have to support, and
`request_capture` says `unresolved` rather than describing a picture it does not have.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from pydantic import TypeAdapter, ValidationError

from swreview.ir.models import Capture, EvidencePackage, SourceRef
from swreview.report.session import CoverageScope
from swreview.tools import session
from swreview.tools.context import ToolContext, context_for, use_context
from tests.support.packages import persist_ref

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
