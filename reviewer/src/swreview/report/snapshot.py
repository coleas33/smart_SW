"""One review as the Review tab restores it, without a token (feature 009 research R2.15).

The engineer keeps a chip per review; choosing one renders that review's Results again
from one object - the findings and the questions in session order, the coverage as the
stream delivered it, the ranking with its summary, and the parts not loaded - through the
same functions the end of a live turn uses. The object is built here, once, and served by
three callers:

- `GET /sessions/{chat_id}/snapshot`, from the run the backend holds (with its ledger, the
  chat's state and the stream's last seq, so a page reloaded mid-turn can reopen the
  stream where the snapshot ends);
- `GET /reviews/{run_id}`, from a run folder after a backend restart, read-only with the
  words file's reason (`restored_snapshot`; a record that waits for Send is dated and
  carries its `restored` Send block, feature 015);
- the page fixture `tests/fixtures/pane/generate_pane_fixture.py` writes.

Pure: it reads its arguments (and, through the summary, the words file) and writes
nothing. The run's events, which the two routes replay from its stream, are one of them: owner
decision 193A works a cleared decision's line out from them (`cleared`). `report.md` prints the
same lines, and names the findings withdrawn with a decision (`withdrawn_lines`; roadmap hole
H-g-010).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from pydantic_core import to_jsonable_python

from swreview.ir.models import EvidencePackage
from swreview.report.names import component_names
from swreview.report.summary import COVERAGE_BUCKETS, load_words, review_ranking
from swreview.report.titles import pane_finding
from swreview.report.unexamined import not_examined

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from swreview.agent.events import UsageLedger
    from swreview.agent.providers import AgentEvent
    from swreview.report.session import ReviewSession
    from swreview.report.summary import SendInput

__all__ = [
    "WAITING_STATES",
    "cleared_lines",
    "restored_snapshot",
    "review_snapshot",
    "root_document",
    "withdrawn_lines",
]

WAITING_STATES = frozenset({"not_sent", "send_failed"})
"""The `model_status` states of a record that waits for Send (feature 015)."""

WHEN_FORMAT = "%Y-%m-%d %H:%M"
"""`{when}` of `send.restored_line`: the stored wall clock, never converted (015 records.md 1)."""


def review_snapshot(
    session: ReviewSession,
    package: EvidencePackage,
    *,
    run_id: str,
    usage: UsageLedger | None = None,
    send: SendInput | None = None,
    send_in_flight: bool = False,
    chat_state: str | None = None,
    last_seq: int | None = None,
    read_only_reason: str | None = None,
    events: Iterable[AgentEvent] = (),
) -> dict[str, Any]:
    """The body both restore routes answer (data-model section 8), as JSON-ready data.

    Every finding, request and coverage entry is exactly the body its stream event carries
    (`finding`, `evidence.requested`, `coverage`), so the page renders a restored review
    with the functions that rendered it live - a finding's with its display title
    (`report/titles.pane_finding`, feature 009 decision 2A), as the ranking's rows are. A
    finding and a request state their source always, a coverage entry only when the model
    wrote it (feature 013, `contracts/sources.md` section 1). `cleared` is added only when
    `events`, the run's stream, leaves a line to show (`cleared_lines`), as `send_in_flight`
    is only when true, so every other snapshot keeps its bytes.
    """
    block = not_examined(package)
    names = component_names(package)
    snapshot = {
        "run_id": run_id,
        "read_only": read_only_reason is not None,
        "read_only_reason": read_only_reason,
        "chat_state": chat_state,
        "last_seq": last_seq,
        "document": root_document(package),
        "findings": [pane_finding(finding, names) for finding in session.findings],
        "evidence_requests": [request.pane_body() for request in session.evidence_requests],
        "coverage": [
            {"bucket": bucket, "item": item.model_dump(mode="json")}
            for bucket in COVERAGE_BUCKETS
            for item in getattr(session.coverage, bucket)
        ],
        "ranking": to_jsonable_python(review_ranking(session, package, usage=usage, send=send)),
        "not_examined": None if block is None else block.model_dump(mode="json"),
    }
    cleared = cleared_lines(session, events)
    if cleared:
        snapshot["cleared"] = cleared
    if send_in_flight:
        snapshot["send_in_flight"] = True
    return snapshot


def cleared_lines(session: ReviewSession, events: Iterable[AgentEvent]) -> list[dict[str, Any]]:
    """For each finding still undecided, in session order, the body of the last
    `disposition.cleared` the run's stream names it in: the line its card shows again after a
    reload, a review switch, a backend restart or a read-only restore (owner decision 193A). The
    body leaves out the `triage_tally` its clear was written with, which a later decision may have
    outdated: a snapshot's one tally is its summary's (002 cycle 7's Tier 2 review).

    Worked out from the stream, so `Finding` gains no field and an older build still loads the
    session; a decision recorded since ends the line, as it does on the live card. A stream whose
    first event does not start this session lends none (`_own_events`).
    """
    latest: dict[str, dict[str, Any]] = {}
    for event in _own_events(session, events):
        if event.type == "disposition.cleared":
            latest[str(event.body.get("finding_id"))] = {
                key: value for key, value in event.body.items() if key != "triage_tally"
            }
    return [
        latest[finding.id]
        for finding in session.findings
        if finding.disposition is None and finding.id in latest
    ]


def withdrawn_lines(session: ReviewSession, events: Iterable[AgentEvent]) -> list[dict[str, Any]]:
    """Each `finding.withdrawn` body of the run's stream that names the decision it took
    (`taken`), in the order the findings went: what `report.md` names under "Withdrawn with a
    decision" (002 FR-031, roadmap hole H-g-010). An undecided finding's withdrawal and a fold's
    name none. Worked out from the stream as `cleared_lines` is, the session holding no withdrawn
    finding; a stream whose first event does not start this session lends none.

    A body whose finding the session still holds is skipped: the stream can run ahead of the
    record, since a sent review's `answer_evidence_batch` writes the withdrawal during `_restate`
    and `session.json` is saved only by `finalize`, after the resumed turn (cycle 10's Tier 2
    review)."""
    held = {finding.id for finding in session.findings}
    return [
        dict(event.body)
        for event in _own_events(session, events)
        if event.type == "finding.withdrawn"
        and "taken" in event.body
        and event.body.get("finding_id") not in held
    ]


def _own_events(session: ReviewSession, events: Iterable[AgentEvent]) -> list[AgentEvent]:
    """`events` read to their end - so a file a caller replays is closed when this returns - or
    none when the first does not start `session`: a re-run that failed after its rotation leaves
    its own stream beside the earlier record (owner decision 193A)."""
    read = list(events)
    if (
        not read
        or read[0].type != "session.started"
        or read[0].body.get("session_id") != str(session.session_id)
    ):
        return []
    return read


def restored_snapshot(
    session: ReviewSession,
    package: EvidencePackage,
    *,
    run_id: str,
    events: Iterable[AgentEvent] = (),
) -> dict[str, Any]:
    """`GET /reviews/{run_id}`'s body: the record read-only, as restored from its run folder.

    Every record is read-only with feature 009's sentence (`Words.read_only`), except one
    that waits for Send (`not_sent` or `send_failed`; feature 015 `contracts/recheck.md`
    section 8, owner decisions 68A and 73A). Its reason is the words file's
    `read_only_lead`, a space, and `send.restored_line` dated with `checked_at`'s stored wall
    clock - 009's second sentence is not in it - and its summary carries the `restored` Send
    block, with no count, from the persisted provider alone. `events`, the folder's stream,
    gives `cleared` as `review_snapshot`'s do.
    """
    words = load_words()
    status = session.model_status
    if status is None or status.state not in WAITING_STATES:
        return review_snapshot(
            session, package, run_id=run_id, read_only_reason=words.read_only, events=events
        )
    send: SendInput = {
        "state": "restored",
        "input_tokens": None,
        "provider": session.provider_info.provider if session.provider_info else "",
        "send_error": None,
    }
    when = status.checked_at.strftime(WHEN_FORMAT)
    reason = f"{words.read_only_lead} {words.send.restored_line.format(when=when)}"
    return review_snapshot(
        session, package, run_id=run_id, send=send, read_only_reason=reason, events=events
    )


def root_document(package: EvidencePackage) -> dict[str, str] | None:
    """The reviewed document's `{path, configuration}`, the shape `review.started` names."""
    root = next(
        (
            document
            for document in package.documents
            if document.document_id == package.design.root_assembly_document_id
        ),
        None,
    )
    if root is None:
        return None
    return {"path": root.path, "configuration": root.active_configuration}
