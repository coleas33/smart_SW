"""An item still open after its question was answered says so, quoting the answer (013 T063).

`contracts/re-ask-guard.md` section 3, "At finalization": a checklist item still open whose
blocking request (`blocks == item.id`) is answered is written unresolved with the reason
"{title}: still open after {ER id} was answered: '{answer}'" instead of the generic "ended without
a finding or a coverage entry". The answer stands; the model recorded no check with it, and the
report says which answer it had.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swreview.agent.runner import finalize_session
from swreview.report.session import EvidenceRequest
from swreview.tools.context import ToolContext, context_for
from tests.support.packages import build_package

STARTED = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)


def a_context(*requests: EvidenceRequest) -> ToolContext:
    context = context_for(build_package())
    context.require_session().evidence_requests.extend(requests)
    return context


def request(
    request_id: str,
    blocks: str | None,
    *,
    answer: str | None = None,
    minute: int = 0,
    source: str = "model",
) -> EvidenceRequest:
    return EvidenceRequest(
        id=request_id,
        what="What fit class is the pin in the plate?",
        why="interfaces.fit",
        entity_ids=["cmp:0001"],
        status="answered" if answer is not None else "open",
        answer=answer,
        answered_at=datetime(2026, 9, 26, 10, minute, tzinfo=UTC) if answer is not None else None,
        blocks=blocks,
        source=source,  # type: ignore[arg-type]
    )


def reason_for(context: ToolContext, check: str) -> str:
    [item] = [row for row in context.require_session().coverage.unresolved if row.check == check]
    return item.reason


def test_an_item_open_after_its_answer_quotes_the_answer() -> None:
    context = a_context(request("ER-001", "interfaces.fit", answer="press fit"))

    finalize_session(context, STARTED)

    assert reason_for(context, "interfaces.fit") == (
        "Fits and clearances at mating interfaces: still open after ER-001 was answered: "
        "'press fit'"
    )


def test_the_most_recent_answer_is_the_one_quoted() -> None:
    context = a_context(
        request("ER-001", "interfaces.fit", answer="press fit", minute=9),
        request("ER-002", "interfaces.fit", answer="slip fit", minute=3),
    )

    finalize_session(context, STARTED)

    assert reason_for(context, "interfaces.fit").endswith("after ER-001 was answered: 'press fit'")


def test_an_item_whose_question_is_still_open_keeps_the_generic_reason() -> None:
    context = a_context(request("ER-001", "interfaces.fit"))

    finalize_session(context, STARTED)

    assert reason_for(context, "interfaces.fit") == (
        "Fits and clearances at mating interfaces: the review ended without a finding or a "
        "coverage entry for it"
    )


def test_an_answer_that_blocks_another_item_changes_nothing_here() -> None:
    context = a_context(request("ER-001", "fasteners", answer="12 mm"))

    finalize_session(context, STARTED)

    assert "ended without" in reason_for(context, "interfaces.fit")
    assert "after ER-001 was answered: '12 mm'" in reason_for(context, "fasteners")


def test_a_code_question_answered_is_quoted_too() -> None:
    """The item's blocking request, whoever wrote it: the drawing check's candidate question
    blocks the drawing item, and its answer is what the item was left with."""
    context = a_context(
        request("ER-001", "drawing.manufacturing_inputs", answer="Review without it", source="code")
    )

    finalize_session(context, STARTED)

    assert reason_for(context, "drawing.manufacturing_inputs").endswith(
        "still open after ER-001 was answered: 'Review without it'"
    )


def test_finalizing_twice_rewrites_the_same_reason_once() -> None:
    context = a_context(request("ER-001", "interfaces.fit", answer="press fit"))
    written: list = []

    finalize_session(context, STARTED, written=written)
    finalize_session(context, STARTED, written=written)

    rows = [row for row in context.require_session().coverage.unresolved
            if row.check == "interfaces.fit"]
    assert len(rows) == 1
    assert "after ER-001 was answered" in rows[0].reason
