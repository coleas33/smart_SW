"""The review snapshot (feature 009 T020), against data-model section 8.

A chip restores a review without a token: the page asks for one object holding everything
Results shows - the findings and questions in session order, the coverage flattened the way
the stream delivered it, the ranking with its summary and the parts not loaded - and renders
it through the same functions the end of a live turn uses (research R2.15). One builder
serves the live route, the run-folder route and the page fixture, so what this pins holds
for all three:

- every key is present, whichever route asks;
- each finding and request is exactly its stream body, in session order;
- each coverage entry is exactly the `coverage` event body, bucket by bucket in the order
  `checked, skipped, unresolved, failed, out_of_scope`;
- the ranking is `review_ranking` - the same object the attention route answers;
- it is pure: the same call gives the same bytes and mutates nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic_core import to_jsonable_python

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.names import component_names
from swreview.report.session import ModelStatus, ReviewSession, SendFailure, load_session
from swreview.report.snapshot import restored_snapshot, review_snapshot
from swreview.report.summary import load_words, review_ranking
from swreview.report.titles import pane_finding
from swreview.report.unexamined import not_examined
from tests.support.attention import REVIEW_FOLDER
from tests.support.contracts import contract_validator

KEYS = {
    "run_id",
    "read_only",
    "read_only_reason",
    "chat_state",
    "last_seq",
    "document",
    "findings",
    "evidence_requests",
    "coverage",
    "ranking",
    "not_examined",
}

RUN_ID = "20260918-215755-cover-assy"


@pytest.fixture
def session() -> ReviewSession:
    return load_session(REVIEW_FOLDER / "session.json")


@pytest.fixture
def package() -> EvidencePackage:
    return load_package(REVIEW_FOLDER).package


def as_bytes(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, sort_keys=False, ensure_ascii=False)


def test_every_key_is_present_live_and_from_disk(
    session: ReviewSession, package: EvidencePackage
) -> None:
    live = review_snapshot(session, package, run_id=RUN_ID, chat_state="ended", last_seq=41)
    disk = review_snapshot(session, package, run_id=RUN_ID, read_only_reason="restarted")

    assert set(live) == KEYS
    assert set(disk) == KEYS
    assert (live["run_id"], live["chat_state"], live["last_seq"]) == (RUN_ID, "ended", 41)
    assert (disk["chat_state"], disk["last_seq"]) == (None, None)


def test_read_only_is_whether_a_reason_was_given(
    session: ReviewSession, package: EvidencePackage
) -> None:
    live = review_snapshot(session, package, run_id=RUN_ID)
    disk = review_snapshot(session, package, run_id=RUN_ID, read_only_reason=load_words().read_only)

    assert (live["read_only"], live["read_only_reason"]) == (False, None)
    assert (disk["read_only"], disk["read_only_reason"]) == (True, load_words().read_only)


def test_the_findings_and_requests_are_their_stream_bodies_in_session_order(
    session: ReviewSession, package: EvidencePackage
) -> None:
    snapshot = review_snapshot(session, package, run_id=RUN_ID)

    # Feature 013 T101, edited deliberately: the stream's bodies state who wrote each record
    # (`contracts/sources.md` section 1) - `pane_finding` and `EvidenceRequest.pane_body` - so the
    # snapshot's do too, where before they were the records' plain dumps.
    names = component_names(package)
    assert snapshot["findings"] == [pane_finding(finding, names) for finding in session.findings]
    assert snapshot["evidence_requests"] == [
        request.pane_body() for request in session.evidence_requests
    ]
    assert all("source" in body for body in [*snapshot["findings"], *snapshot["evidence_requests"]])
    assert [one["id"] for one in snapshot["findings"]] == [f.id for f in session.findings]


def test_the_coverage_is_flattened_bucket_by_bucket_as_the_stream_carries_it(
    session: ReviewSession, package: EvidencePackage
) -> None:
    snapshot = review_snapshot(session, package, run_id=RUN_ID)
    expected = [
        {"bucket": bucket, "item": item.model_dump(mode="json")}
        for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        for item in getattr(session.coverage, bucket)
    ]

    assert snapshot["coverage"] == expected
    assert len(expected) == 5 + 11 + 39 + 0 + 7, "the fixture's five buckets"


def test_every_coverage_entry_validates_as_the_coverage_event_body(
    session: ReviewSession, package: EvidencePackage
) -> None:
    validator = contract_validator("chat-events.schema.json")
    snapshot = review_snapshot(session, package, run_id=RUN_ID)

    for seq, entry in enumerate(snapshot["coverage"], start=1):
        event = {"seq": seq, "at": "2026-09-23T10:00:00+00:00", "type": "coverage", "body": entry}
        errors = [error.message for error in validator.iter_errors(event)]
        assert errors == [], (entry, errors)


def test_the_ranking_is_the_review_ranking_with_its_summary(
    session: ReviewSession, package: EvidencePackage
) -> None:
    snapshot = review_snapshot(session, package, run_id=RUN_ID)

    assert snapshot["ranking"] == to_jsonable_python(review_ranking(session, package))
    assert "summary" in snapshot["ranking"]
    assert snapshot["ranking"]["summary"]["resume_input_tokens"] is None
    assert snapshot["ranking"]["groups"]["version"] == 1, "feature 013: the grouped view"


def test_the_document_is_the_package_roots_path_and_active_configuration(
    session: ReviewSession, package: EvidencePackage
) -> None:
    root = next(
        document
        for document in package.documents
        if document.document_id == package.design.root_assembly_document_id
    )

    snapshot = review_snapshot(session, package, run_id=RUN_ID)

    assert snapshot["document"] == {"path": root.path, "configuration": root.active_configuration}


def test_a_package_that_does_not_carry_its_root_document_has_no_document(
    session: ReviewSession, package: EvidencePackage
) -> None:
    rootless = package.model_copy(
        update={
            "documents": [
                document
                for document in package.documents
                if document.document_id != package.design.root_assembly_document_id
            ]
        }
    )

    assert review_snapshot(session, rootless, run_id=RUN_ID)["document"] is None


def test_the_parts_not_loaded_are_the_shared_block(
    session: ReviewSession, package: EvidencePackage
) -> None:
    first, second, *rest = package.components
    lightweight = package.model_copy(
        update={
            "components": [first, second.model_copy(update={"suppression": "lightweight"}), *rest]
        }
    )

    assert review_snapshot(session, package, run_id=RUN_ID)["not_examined"] is None
    block = not_examined(lightweight)
    assert block is not None
    assert review_snapshot(session, lightweight, run_id=RUN_ID)["not_examined"] == (
        block.model_dump(mode="json")
    )


def test_two_calls_give_the_same_bytes_and_mutate_nothing(
    session: ReviewSession, package: EvidencePackage
) -> None:
    session_before = session.model_dump_json()
    package_before = package.model_dump_json()

    first = review_snapshot(session, package, run_id=RUN_ID, chat_state="ended", last_seq=3)
    second = review_snapshot(session, package, run_id=RUN_ID, chat_state="ended", last_seq=3)

    assert as_bytes(first) == as_bytes(second)
    assert session.model_dump_json() == session_before
    assert package.model_dump_json() == package_before


@pytest.mark.parametrize("in_flight", [False, True])
def test_send_in_flight_is_additive_only_when_true_and_default_keeps_old_bytes(
    session: ReviewSession, package: EvidencePackage, in_flight: bool
) -> None:
    before = session.model_dump(mode="json")
    default = review_snapshot(session, package, run_id=RUN_ID)
    explicit = review_snapshot(session, package, run_id=RUN_ID, send_in_flight=in_flight)

    assert "send_in_flight" not in default
    if in_flight:
        assert explicit.pop("send_in_flight") is True
    else:
        assert "send_in_flight" not in explicit
    assert as_bytes(explicit) == as_bytes(default)
    assert session.model_dump(mode="json") == before


# --- feature 015 T099: a record restored from its run folder (`contracts/recheck.md` section 8)

CHECKED = datetime(2026, 10, 9, 14, 30, 59, tzinfo=timezone(timedelta(hours=2)))
"""A fictional `checked_at` two hours east of UTC: its line reads 14:30, never 12:30."""


def with_status(session: ReviewSession, state: str, **fields: Any) -> ReviewSession:
    status = ModelStatus(
        state=state,
        document={"path": r"C:\Fictional\FICT-cover.SLDASM", "configuration": "Default"},
        checked_at=CHECKED,
        **fields,
    )
    return session.model_copy(update={"model_status": status})


@pytest.mark.parametrize("state", ["not_sent", "send_failed"])
def test_a_waiting_record_restores_with_the_composed_line_and_the_restored_block(
    session: ReviewSession, package: EvidencePackage, state: str
) -> None:
    """Owner decisions 68A and 73A: 009's first sentence, then the dated Send sentence."""
    words = load_words()
    failures = [
        SendFailure(
            at=CHECKED + timedelta(minutes=5), error_class="FICTError", reason="FICT refused"
        )
    ]
    record = with_status(session, state, failures=failures if state == "send_failed" else [])

    restored = restored_snapshot(record, package, run_id=RUN_ID)

    assert set(restored) == KEYS
    assert restored["read_only"] is True
    assert restored["read_only_reason"] == (
        "The backend restarted, so this review is shown from its run folder. "
        "Its checks ran 2026-10-09 14:30; Send checks the saved evidence again first."
    )
    assert restored["read_only_reason"] == (
        f"{words.read_only_lead} {words.send.restored_line.format(when='2026-10-09 14:30')}"
    )
    assert words.read_only_off not in restored["read_only_reason"]
    send = restored["ranking"]["summary"]["send"]
    assert send == {
        "state": "restored",
        "input_tokens": None,
        "approximate": False,
        "text": words.send.restored,
        "failure": (
            words.send.failed.format(reason="FICT refused", time="14:35")
            if state == "send_failed"
            else None
        ),
        "rerun_failed_text": words.send.rerun_failed,
    }
    assert "session_id" not in send
    assert restored == review_snapshot(
        record,
        package,
        run_id=RUN_ID,
        send={"state": "restored", "input_tokens": None, "provider": "", "send_error": None},
        read_only_reason=restored["read_only_reason"],
    )


@pytest.mark.parametrize("state", ["sent", None])
def test_a_sent_or_unmarked_record_restores_with_todays_sentence_and_no_block(
    session: ReviewSession, package: EvidencePackage, state: str | None
) -> None:
    record = session if state is None else with_status(session, state)

    restored = restored_snapshot(record, package, run_id=RUN_ID)

    assert restored == review_snapshot(
        record, package, run_id=RUN_ID, read_only_reason=load_words().read_only
    )
    assert restored["read_only_reason"] == (
        "The backend restarted, so this review is shown from its run folder. "
        "Follow-ups, decisions and answers are off."
    )
    assert "send" not in restored["ranking"]["summary"]


def test_restoring_a_waiting_record_mutates_nothing(
    session: ReviewSession, package: EvidencePackage
) -> None:
    record = with_status(session, "not_sent")
    before = record.model_dump_json()

    first = restored_snapshot(record, package, run_id=RUN_ID)

    assert as_bytes(first) == as_bytes(restored_snapshot(record, package, run_id=RUN_ID))
    assert record.model_dump_json() == before
