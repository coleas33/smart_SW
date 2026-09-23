"""One evidence-request writer for the model's requests and the drawing check's (T043).

`contracts/questions.md` section 4: `tools/session.record_evidence_request` is the writer
`request_evidence` delegates to after its refusals, and the one feature 011's drawing check
writes its questions through, so the pane's "Questions for you" panel and feature 008's batch
route serve both unchanged (FR-034). It allocates the next `ER-` id, validates through
`EvidenceRequest`, appends to the session and emits `evidence.requested` exactly as
`request_evidence` always has; `request_evidence`'s refusals still come first and take no id.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from swreview.report.session import EvidenceRequest
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.session import record_evidence_request, request_evidence
from tests.support.mechanical import PackageBuilder


def fresh() -> tuple[ToolContext, list[tuple[str, dict[str, Any]]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    context = context_for(PackageBuilder(design_stem="FICT-KALO-0000").build().package)
    context.emit = lambda event, body: events.append((event, dict(body)))
    return context, events


def test_the_writer_allocates_validates_appends_and_announces() -> None:
    context, events = fresh()

    first = record_evidence_request(
        context,
        what="the drawing of FICT-KALO-0000",
        why="fits stay unresolved without it",
        entity_ids=["doc:0001"],
        question="Should the review read it?",
        options=["Yes", "No"],
        blocks="drawing.manufacturing_inputs",
    )
    second = record_evidence_request(context, "a second thing", "for a reason", ["doc:0001"])

    assert isinstance(first, EvidenceRequest)
    assert (first.id, second.id) == ("ER-001", "ER-002")
    assert first.status == "open" and first.answer is None and first.answered_at is None
    assert (first.question, first.options, first.blocks) == (
        "Should the review read it?", ["Yes", "No"], "drawing.manufacturing_inputs"
    )
    assert (second.question, second.options, second.blocks) == (None, [], None)
    assert context.require_session().evidence_requests == [first, second]
    assert events == [
        ("evidence.requested", first.model_dump(mode="json")),
        ("evidence.requested", second.model_dump(mode="json")),
    ]


@pytest.mark.parametrize(
    "fields",
    [
        {"question": "x" * 141},
        {"question": "   "},
        {"options": ["same", "same"]},
        {"options": ["o"] * 6},
        {"options": ["x" * 61]},
    ],
    ids=["long question", "blank question", "repeated option", "six options", "long option"],
)
def test_the_writer_refuses_what_evidence_request_refuses_and_takes_no_id(
    fields: dict[str, Any],
) -> None:
    context, events = fresh()

    with pytest.raises(ValidationError):
        record_evidence_request(context, "what", "why", ["doc:0001"], **fields)
    written = record_evidence_request(context, "what", "why", ["doc:0001"])

    assert written.id == "ER-001"
    assert context.require_session().evidence_requests == [written]
    assert [event for event, _ in events] == ["evidence.requested"]


def test_request_evidence_writes_through_the_writer_exactly_as_before() -> None:
    context, events = fresh()

    with use_context(context):
        result = request_evidence(
            "what", "why", ["doc:0001"], question="One decision?", options=["A", "B"],
            blocks="fasteners",
        )

    [request] = context.require_session().evidence_requests
    assert result == {"status": "open", "evidence_request": request.model_dump(mode="json")}
    assert request.id == "ER-001"
    assert events == [("evidence.requested", request.model_dump(mode="json"))]


@pytest.mark.parametrize(
    ("arguments", "refusal"),
    [
        ({"entity_ids": ["cmp:9999"]}, "entity_ids not in this package"),
        ({"question": "x" * 141}, "question must be one short question"),
        ({"options": ["A", "A"]}, "twice"),
        ({"blocks": "nothing.like.this"}, "is not a checklist item id"),
    ],
)
def test_request_evidences_refusals_come_first_and_take_no_id(
    arguments: dict[str, Any], refusal: str
) -> None:
    context, events = fresh()
    call = {"what": "what", "why": "why", "entity_ids": ["doc:0001"], **arguments}

    with use_context(context):
        refused = request_evidence(**call)
    written = record_evidence_request(context, "what", "why", ["doc:0001"])

    assert refusal in refused["error"]
    assert written.id == "ER-001", "a refused request allocates no id"
    assert [event for event, _ in events] == ["evidence.requested"]


def test_the_writer_needs_a_review_session() -> None:
    context, _ = fresh()
    context.session = None

    with pytest.raises(ValueError, match="review session"):
        record_evidence_request(context, "what", "why", ["doc:0001"])
