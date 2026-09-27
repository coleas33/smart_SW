"""The coverage close-out is closed by code when the review ends (feature 013 T116).

`contracts/tokens.md` section 1: `coverage.closeout` is code-owned, and `finalize_session` writes
exactly one row for it - check `coverage.closeout`, bucket `checked` - counting the open evidence
requests it lists as unresolved and the package's gaps by kind, and rewrites it, never adds a
second, on a second finalization. The model marked it every turn; now `mark_coverage` answers it
`closed_by_code`. A turn cut short still reads as cut short, and the attention coverage block
still leaves the item out of its not-closed list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from swreview.agent.runner import finalize_session
from swreview.ir.models import Gap
from swreview.report.attention import CLOSEOUT_ITEM_ID, rank
from swreview.report.session import (
    CLOSEOUT_CHECK,
    MAX_STEPS_CLOSEOUT,
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    was_cut_short,
)
from swreview.tools import session as session_tools
from swreview.tools.context import ToolContext, context_for, use_context
from tests.support.packages import build_package

STARTED = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)


def gap(kind: str, entity_id: str) -> Gap:
    return Gap(kind=kind, entity_kind="hole", entity_id=entity_id, reason="fictional", error=None)


def a_context(*gaps: Gap, requests: int = 0) -> ToolContext:
    package = build_package(gaps=list(gaps)) if gaps else build_package(gaps=[])
    context = context_for(package)
    for number in range(1, requests + 1):
        context.require_session().evidence_requests.append(
            EvidenceRequest(
                id=f"ER-{number:03d}", what=f"value {number}", why="a check",
                entity_ids=[], status="open", answer=None, answered_at=None,
            )
        )
    return context


def closeout_rows(context: ToolContext) -> list[tuple[str, CoverageItem]]:
    coverage = context.require_session().coverage
    return [
        (bucket, item)
        for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        for item in getattr(coverage, bucket)
        if item.check == CLOSEOUT_CHECK
    ]


def test_finalization_writes_one_checked_row_counting_requests_and_gaps_by_kind() -> None:
    context = a_context(
        gap("not_extracted", "hol:0001"),
        gap("tool_error", "hol:0002"),
        gap("not_extracted", "hol:0003"),
        requests=2,
    )

    finalize_session(context, STARTED)

    [(bucket, row)] = closeout_rows(context)
    assert bucket == "checked"
    assert row.reason == (
        "Closed by code when the review ended: 2 open evidence requests are listed as "
        "unresolved coverage (coverage.evidence_request); the package records 3 gaps: "
        "2 not extracted, 1 tool error"
    )
    assert row.source == "code"


def test_no_gap_and_one_request_read_as_such() -> None:
    context = a_context(requests=1)

    finalize_session(context, STARTED)

    [(_, row)] = closeout_rows(context)
    assert row.reason == (
        "Closed by code when the review ended: 1 open evidence request is listed as "
        "unresolved coverage (coverage.evidence_request); the package records no gaps"
    )


def test_one_gap_is_counted_in_the_singular() -> None:
    context = a_context(gap("unsupported", "hol:0001"))

    finalize_session(context, STARTED)

    [(_, row)] = closeout_rows(context)
    assert row.reason.endswith("the package records 1 gap: 1 unsupported")


def test_a_second_finalization_rewrites_the_row_and_never_adds_one() -> None:
    context = a_context(requests=1)
    written: list[Any] = []

    finalize_session(context, STARTED, written=written)
    context.require_session().evidence_requests[0].status = "answered"
    context.require_session().evidence_requests[0].answer = "a value"
    finalize_session(context, STARTED, written=written)

    [(_, row)] = closeout_rows(context)
    assert row.reason.startswith("Closed by code when the review ended: 0 open evidence requests")


def test_the_item_is_never_left_open_or_written_unresolved_by_finalization() -> None:
    context = a_context()

    finalize_session(context, STARTED)

    assert [bucket for bucket, _ in closeout_rows(context)] == ["checked"]
    open_ids = [item.id for item in context.checklist.open_items(context.require_session())]
    assert CLOSEOUT_ITEM_ID not in open_ids


def test_mark_coverage_on_the_close_out_is_closed_by_code() -> None:
    context = a_context()

    with use_context(context):
        result = session_tools.mark_coverage(
            CLOSEOUT_CHECK, "checked", CoverageScope(), "every gap reflected"
        )

    assert result["status"] == "closed_by_code"
    assert closeout_rows(context) == []


def test_after_finalization_the_close_out_answer_quotes_the_row() -> None:
    context = a_context()
    finalize_session(context, STARTED)
    [(_, row)] = closeout_rows(context)

    with use_context(context):
        result = session_tools.mark_coverage(CLOSEOUT_CHECK, "checked", CoverageScope(), "r")

    assert {key: result[key] for key in ("status", "check", "reason")} == {
        "status": "closed_by_code", "check": CLOSEOUT_CHECK, "reason": row.reason,
    }
    assert result["open_items"] == []  # finalization wrote every open item's row too


def test_a_turn_cut_short_still_reads_as_cut_short() -> None:
    context = a_context()
    context.require_session().coverage.unresolved.append(
        CoverageItem(
            check=CLOSEOUT_CHECK,
            scope=CoverageScope(),
            reason=MAX_STEPS_CLOSEOUT.format(max_steps=3),
            error=None,
        )
    )

    finalize_session(context, STARTED)

    assert was_cut_short(context.require_session())
    assert sorted(bucket for bucket, _ in closeout_rows(context)) == ["checked", "unresolved"]


def test_a_finished_review_does_not_read_as_cut_short() -> None:
    context = a_context()

    finalize_session(context, STARTED)

    assert not was_cut_short(context.require_session())


def test_the_attention_coverage_block_still_leaves_the_item_out() -> None:
    context = a_context(requests=1)

    finalize_session(context, STARTED)

    block = rank(context.require_session()).coverage
    assert all(row.item != CLOSEOUT_ITEM_ID for row in block.not_closed)
    assert block.open_evidence_requests == 1


def test_lever_7_does_not_wait_for_an_item_code_closes_when_the_review_ends() -> None:
    """`coverage_complete` asks whether the model has finished: every model-owned item closed
    by a finding or a checked row, and no request open. The close-out is written only by
    finalization, so an item code owns never holds the stop back (feature 013 T117)."""
    from swreview.agent.runner import coverage_complete

    context = a_context()
    session = context.require_session()
    for item in context.checklist.items:
        if item.owner == "model":
            session.coverage.checked.append(
                CoverageItem(check=item.id, scope=CoverageScope(), reason="r", error=None)
            )

    assert CLOSEOUT_CHECK not in [row.check for row in session.coverage.checked]
    assert coverage_complete(context.checklist, session)


def test_lever_7_still_waits_for_every_model_owned_item() -> None:
    from swreview.agent.runner import coverage_complete

    context = a_context()
    session = context.require_session()
    model_items = [item for item in context.checklist.items if item.owner == "model"]
    for item in model_items[:-1]:
        session.coverage.checked.append(
            CoverageItem(check=item.id, scope=CoverageScope(), reason="r", error=None)
        )

    assert not coverage_complete(context.checklist, session)


def test_the_checklist_owns_the_close_out_in_code() -> None:
    from swreview.agent.checklist import load_checklist

    item = next(entry for entry in load_checklist().items if entry.id == CLOSEOUT_CHECK)

    assert item.owner == "code"
