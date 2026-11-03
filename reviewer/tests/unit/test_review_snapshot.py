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
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from pydantic_core import to_jsonable_python

from swreview.agent.providers import AgentEvent
from swreview.findings import Disposition
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
from tests.support.triage import tally_body

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
    """*Changed 2026-11-03 on purpose (002 T398; cycle 22, roadmap hole H-c-011):* the fixture's
    flagged findings record no outcome, so 009's sentence is now followed by the console's, which
    records the rest (`read_only_console`), where it ended the line; the cases that tell the two
    lines apart are cycle 22's below."""
    words = load_words()
    record = session if state is None else with_status(session, state)

    restored = restored_snapshot(record, package, run_id=RUN_ID)

    assert restored == review_snapshot(
        record,
        package,
        run_id=RUN_ID,
        read_only_reason=f"{words.read_only} {words.read_only_console}",
    )
    assert restored["read_only_reason"] == (
        "The backend restarted, so this review is shown from its run folder. "
        "Follow-ups, decisions and answers are off. "
        "Record the rest of the triage at the console: swreview disposition."
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


# --- owner decision 193A (002 T340): a cleared decision's line, from the run's stream -------------

AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
"""When the fictional events below were written."""

DECIDED = Disposition(decision="accepted", note="FICT intended", by="FICT-ENG", at=AT)
"""A decision recorded on one of the fixture's findings, which a re-run cleared."""


def event(seq: int, kind: str, body: dict[str, Any]) -> AgentEvent:
    return AgentEvent(seq=seq, at=AT, type=kind, body=body)  # type: ignore[arg-type]


def started(session_id: Any, seq: int = 1) -> AgentEvent:
    """The `session.started` every review stream opens with, naming its session."""
    return event(
        seq,
        "session.started",
        {
            "session_id": str(session_id),
            "package_id": "FICT-package",
            "provider": "fake",
            "model": "fake-1",
            "effort_mapping": {
                "requested": "high", "provider_param": "fake.effort", "provider_value": "high"
            },
        },
    )


def cleared(seq: int, finding_id: str, line: str) -> AgentEvent:
    return event(
        seq,
        "disposition.cleared",
        {"finding_id": finding_id, "disposition": DECIDED.model_dump(mode="json"), "reason": line},
    )


def test_the_snapshot_names_each_undecided_findings_latest_cleared_line(
    session: ReviewSession, package: EvidencePackage
) -> None:
    """Owner decision 193A: both snapshots name, for each finding still undecided, the last
    `disposition.cleared` body its run's stream holds - F-002's later line, not its first - in
    session order. F-003, decided again since its line, and an id the session no longer holds
    lend none; the findings themselves are as the session holds them, with no field added."""
    session.findings[2] = session.findings[2].model_copy(update={"disposition": DECIDED})
    stream = [
        started(session.session_id),
        cleared(2, "F-004", "FICT F-004's line"),
        cleared(3, "F-002", "FICT F-002's first line"),
        cleared(4, "F-003", "FICT F-003's line"),
        cleared(5, "F-099", "FICT a withdrawn finding's line"),
        cleared(6, "F-002", "FICT F-002's latest line"),
    ]

    live = review_snapshot(session, package, run_id=RUN_ID, events=stream)
    restored = restored_snapshot(session, package, run_id=RUN_ID, events=stream)

    for snapshot in (live, restored):
        assert snapshot["cleared"] == [stream[5].body, stream[1].body]
        assert snapshot["findings"] == review_snapshot(session, package, run_id=RUN_ID)["findings"]


def test_a_cleared_line_leaves_the_tally_to_the_summary(
    session: ReviewSession, package: EvidencePackage
) -> None:
    """The triage tally (cycle 7's Tier 2 review): a `disposition.cleared` body carries the
    review's tally as its clear left it, and a later decision outdates it - F-002's decision was
    cleared while F-005 held `already_known`, and F-001 has since been rejected as `wrong`. Both
    snapshots name F-002's line without that tally, so the one a snapshot holds is its summary's,
    the count `report.md` prints."""
    known = DECIDED.model_copy(update={"triage": "already_known"})
    wrong = DECIDED.model_copy(update={"decision": "rejected", "triage": "wrong"})
    session.findings[4] = session.findings[4].model_copy(update={"disposition": known})
    session.findings[0] = session.findings[0].model_copy(update={"disposition": wrong})
    line = cleared(2, "F-002", "FICT F-002's line").body
    written = {**line, "triage_tally": tally_body(known=1, not_recorded=7)}
    stream = [started(session.session_id), event(2, "disposition.cleared", written)]

    live = review_snapshot(session, package, run_id=RUN_ID, events=stream)
    restored = restored_snapshot(session, package, run_id=RUN_ID, events=stream)

    for snapshot in (live, restored):
        assert snapshot["cleared"] == [line]
        assert snapshot["ranking"]["summary"]["triage_tally"] == tally_body(
            known=1, wrong=1, not_recorded=6
        )


@pytest.mark.parametrize("opening", ["another session", "no session.started"])
def test_a_stream_of_another_session_lends_the_snapshot_no_line(
    session: ReviewSession, package: EvidencePackage, opening: str
) -> None:
    """A stream whose first event does not start this session - a re-run that failed after its
    rotation left its own stream beside the earlier record - lends no line, so no card shows
    another session's."""
    first = (
        started(UUID("00000000-0000-4000-8000-000000000193"))
        if opening == "another session"
        else event(1, "text.delta", {"text": "FICT"})
    )

    snapshot = review_snapshot(
        session, package, run_id=RUN_ID, events=[first, cleared(2, "F-002", "FICT line")]
    )

    assert "cleared" not in snapshot


def test_a_snapshot_with_no_cleared_line_keeps_its_keys(
    session: ReviewSession, package: EvidencePackage
) -> None:
    """Owner decision 193A: `cleared` is added only when there is a line, as `send_in_flight` is,
    so a stream with none leaves every key and byte of the snapshot as it was."""
    stream = [started(session.session_id), event(2, "text.delta", {"text": "FICT"})]

    with_stream = review_snapshot(session, package, run_id=RUN_ID, events=stream)

    assert set(with_stream) == KEYS
    assert as_bytes(with_stream) == as_bytes(review_snapshot(session, package, run_id=RUN_ID))


# --- 002 cycle 13: what a read-only restore names -----------------------------------------------


def withdrawn(seq: int, finding_id: str, **named: Any) -> AgentEvent:
    """A `finding.withdrawn` event of `finding_id`, naming whatever else `named` gives its body."""
    return event(
        seq, "finding.withdrawn", {"finding_id": finding_id, "reason": "FICT bought part", **named}
    )


@pytest.mark.parametrize("waiting", [False, True], ids=["sent", "waiting"])
def test_a_read_only_snapshot_names_each_cleared_line_in_its_read_only_form(
    session: ReviewSession, package: EvidencePackage, waiting: bool
) -> None:
    """002 cycle 13 (FR-031): a read-only restore's decision buttons are off, so it names each
    cleared line without the call to decide again (`RerunWords.read_only`) - its finding,
    disposition and the rest of its words as the stream holds them, and a line written with other
    words as written - whether the record was sent or waits for Send. The live snapshot, whose
    buttons are on, names each line as written."""
    record = with_status(session, "not_sent") if waiting else session
    line = load_words().rerun.of("Accept", "real but already known", cause="restate")
    stream = [
        started(session.session_id),
        cleared(2, "F-002", line),
        cleared(3, "F-004", "FICT a cleared line written with other words."),
    ]

    live = review_snapshot(record, package, run_id=RUN_ID, events=stream)
    restored = restored_snapshot(record, package, run_id=RUN_ID, events=stream)

    assert live["cleared"] == [stream[1].body, stream[2].body]
    assert restored["cleared"] == [
        {
            **stream[1].body,
            "reason": (
                "Your answer graded the checks again and this verdict changed, so your Accept "
                "(real but already known) was cleared."
            ),
        },
        stream[2].body,
    ]


def test_a_read_only_snapshot_names_each_withdrawal_that_took_a_decision(
    session: ReviewSession, package: EvidencePackage
) -> None:
    """002 cycle 13 (FR-031; H-g-010's *Left open*): a read-only restore replays no Transcript, so
    its snapshot names, under `withdrawn`, each withdrawal the record's own stream holds that took a
    decision, in the order they went - the bodies `report.md` names under "Withdrawn with a
    decision" - for the page to print as the live Transcript does, whether the record was sent or
    waits for Send. A fold's withdrawal and an undecided finding's took none, and one of a finding
    the record still holds is a stream run ahead of its record (cycle 10's Tier 2 review): none of
    the three is named. The live snapshot, whose Transcript is replayed from the stream, names none;
    and with none to name the key is left out, so every other snapshot keeps its bytes."""
    taken = {"disposition": DECIDED.model_dump(mode="json"), "taken": "your Accept went with it"}
    stream = [
        started(session.session_id),
        withdrawn(2, "F-090", **taken),
        withdrawn(3, "F-091"),
        withdrawn(4, "F-092", folded_into="F-001"),
        withdrawn(5, "F-002", **taken),
        withdrawn(6, "F-093", **{**taken, "taken": "your Reject (wrong) went with it"}),
    ]

    live = review_snapshot(session, package, run_id=RUN_ID, events=stream)
    restored = restored_snapshot(session, package, run_id=RUN_ID, events=stream)
    waiting = restored_snapshot(
        with_status(session, "not_sent"), package, run_id=RUN_ID, events=stream
    )
    none_taken = restored_snapshot(session, package, run_id=RUN_ID, events=stream[:1] + stream[2:5])

    assert restored["withdrawn"] == [stream[1].body, stream[5].body]
    assert waiting["withdrawn"] == restored["withdrawn"]
    assert "withdrawn" not in live
    assert as_bytes(none_taken) == as_bytes(restored_snapshot(session, package, run_id=RUN_ID))


# --- 002 cycle 22 (roadmap hole H-c-011): a finished record's line names the console ----------

JUDGED_AT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
"""When the fictional outcomes below were recorded."""


def judged(triage: str | None, decision: str = "accepted") -> dict[str, Any]:
    """A finding's update: `decision` recorded, with `triage` as its outcome, or none."""
    return {
        "disposition": Disposition(
            decision=decision, note="FICT judged", by="FICT-ENG", at=JUDGED_AT, triage=triage
        )
    }


PASS = {"status": "checked_within_scope", "severity": "info"}
"""A finding's update into a pass, 'Checked, no issue', which takes no outcome but the miss."""


def each(update: Callable[[int], dict[str, Any]]) -> Callable[[ReviewSession], ReviewSession]:
    """The record with each finding updated by `update` of its index."""

    def changed(session: ReviewSession) -> ReviewSession:
        findings = [
            finding.model_copy(update=update(index))
            for index, finding in enumerate(session.findings)
        ]
        return session.model_copy(update={"findings": findings})

    return changed


CONSOLE_CASES: dict[str, tuple[Callable[[ReviewSession], ReviewSession], bool]] = {
    "no outcome recorded": (each(lambda index: {}), True),
    "an accept recorded with none": (
        each(lambda index: judged(None) if index == 0 else judged("new_and_real")),
        True,
    ),
    "a defer recorded with none": (
        each(lambda index: judged(None, "deferred") if index == 1 else judged("wrong")),
        True,
    ),
    "every outcome recorded": (each(lambda index: judged("already_known")), False),
    "a pass with none beside them": (
        each(lambda index: PASS if index == 0 else judged("not_worth_flagging")),
        False,
    ),
    "only passes, none judged": (each(lambda index: PASS), False),
    "no finding": (lambda session: session.model_copy(update={"findings": []}), False),
}
"""Each record the fixture's eight flagged findings make, and whether its line names the console."""


@pytest.mark.parametrize(
    ("record_of", "named"), list(CONSOLE_CASES.values()), ids=list(CONSOLE_CASES)
)
def test_a_finished_records_line_names_the_console_while_a_flagged_finding_records_no_outcome(
    session: ReviewSession,
    package: EvidencePackage,
    record_of: Callable[[ReviewSession], ReviewSession],
    named: bool,
) -> None:
    """002 FR-031, cycle 22 (roadmap hole H-c-011): a record restored from its run folder takes no
    decision in the pane (009 FR-021), so while a flagged finding - every status but a pass, which
    takes no outcome but the miss (187A) - records no outcome, decided or not, its line ends with
    the console's sentence (`read_only_console`), after 009's and a space; once every flagged
    finding records one, or none is flagged, the line is 009's alone. The rest of the snapshot is
    the one `review_snapshot` gives that line."""
    words = load_words()
    record = record_of(session)

    restored = restored_snapshot(record, package, run_id=RUN_ID)

    reason = f"{words.read_only} {words.read_only_console}" if named else words.read_only
    assert restored["read_only_reason"] == reason
    assert restored == review_snapshot(record, package, run_id=RUN_ID, read_only_reason=reason)


@pytest.mark.parametrize("state", ["not_sent", "send_failed"])
def test_a_waiting_records_line_never_names_the_console(
    session: ReviewSession, package: EvidencePackage, state: str
) -> None:
    """002 cycle 22: a record that waits for Send is read-only too, but its Send leads back to a
    live review that takes decisions, so its line stays 015's (68A, 73A), though the fixture's
    flagged findings record no outcome."""
    failures = [SendFailure(at=CHECKED, error_class="FICTError", reason="FICT refused")]
    record = with_status(session, state, failures=failures if state == "send_failed" else [])

    restored = restored_snapshot(record, package, run_id=RUN_ID)

    assert load_words().read_only_console not in restored["read_only_reason"]
    assert restored["read_only_reason"].startswith(load_words().read_only_lead + " ")
