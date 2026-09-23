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
from typing import Any

import pytest
from pydantic_core import to_jsonable_python

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import ReviewSession, load_session
from swreview.report.snapshot import review_snapshot
from swreview.report.summary import load_words, review_ranking
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

    assert snapshot["findings"] == [finding.model_dump(mode="json") for finding in session.findings]
    assert snapshot["evidence_requests"] == [
        request.model_dump(mode="json") for request in session.evidence_requests
    ]
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
