"""One chat: its state machine, its event file, its live listeners, its dispositions.

The HTTP layer is `server.py`; everything it keeps *about a chat* is here, so the state
machine can be read (and tested) without an ASGI client.

**The state machine is data-model section 3 and nothing else.** `idle -> extracting ->
running -> (waiting_engineer <-> running)* -> ended`, `ended -> running` when the engineer
sends a follow-up or answers an evidence request on a session whose previous turn already
ended (FR-006), any state `-> failed`, and `failed` terminal - its only exit is a new
`ChatSession` carrying `retry_of`. `TRANSITIONS` below is the whole rule, and `to()` is
the only way to move; a transition it does not name raises rather than being tolerated,
because the pane draws its buttons from this state and a state nobody can reach from the
last one means the pane is drawing something that did not happen.

**The event file has one writer, and it is not this module.** `agent/runner.py`'s
`EventSink` stamps `seq`, appends to `events.jsonl` and fans out to listeners; a chat
registers `publish` as one of those listeners and reads the file back with
`replay_events`. Replay-then-live is the pane's reconnect: `Last-Event-ID` says what it
already has, the file supplies the rest, and the subscription carries what arrives while
it is reading. A chat therefore never writes the stream itself except on the one path
where there is no run to write it - a session that failed before the runner existed.

**Why a queue and not an `asyncio.Queue`.** Events are published from the chat's worker
thread and consumed by the SSE endpoint on the event loop. A `queue.SimpleQueue` is safe
in both directions and needs no loop bound at subscribe time, so the fan-out is testable
without an event loop at all; the endpoint drains it on a short poll rather than awaiting
it. For one desktop pane with one open stream that is cheaper than it is clever.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from swreview.agent.providers import AgentEvent, EventType
from swreview.agent.runner import EVENTS_FILE_NAME, EventSink, ReviewRun
from swreview.benchmark.timing import timing_with
from swreview.findings import Finding
from swreview.report.attention import rank
from swreview.report.attention_record import write_attention_record
from swreview.report.dispositions import REPORT_FILE_NAME, set_disposition
from swreview.report.markdown import render_report
from swreview.report.session import Timing, save_session

__all__ = [
    "ChatSession",
    "ChatState",
    "EventStream",
    "InvalidTransitionError",
    "Subscriber",
    "TRANSITIONS",
    "record_disposition",
    "record_timing_live",
    "replay_events",
]


class ChatState(StrEnum):
    """Where one chat is (data-model section 3). The pane draws its controls from this."""

    IDLE = "idle"
    EXTRACTING = "extracting"
    RUNNING = "running"
    WAITING_ENGINEER = "waiting_engineer"
    ENDED = "ended"
    FAILED = "failed"


TRANSITIONS: Mapping[ChatState, frozenset[ChatState]] = {
    ChatState.IDLE: frozenset({ChatState.EXTRACTING, ChatState.FAILED}),
    ChatState.EXTRACTING: frozenset({ChatState.RUNNING, ChatState.FAILED}),
    ChatState.RUNNING: frozenset(
        {ChatState.WAITING_ENGINEER, ChatState.ENDED, ChatState.FAILED}
    ),
    ChatState.WAITING_ENGINEER: frozenset(
        {ChatState.RUNNING, ChatState.ENDED, ChatState.FAILED}
    ),
    ChatState.ENDED: frozenset({ChatState.RUNNING, ChatState.FAILED}),
    ChatState.FAILED: frozenset(),
}
"""Every move the machine allows. Read it as the table in data-model section 3.

`running -> running` is absent on purpose: one turn per chat is the concurrency rule the
server turns into a 409 (`chat-api.md`, Concurrency), and making it a transition would
push that rule into three endpoints instead of one table.
"""


class InvalidTransitionError(RuntimeError):
    """A move the state machine does not allow. The server answers 409 with it."""


# --- the event file ------------------------------------------------------------------


def replay_events(path: Path | str, after: int = 0) -> Iterator[AgentEvent]:
    """Every event in `events.jsonl` whose `seq` is greater than `after`.

    `after` is the `Last-Event-ID` the pane reconnected with, so a reconnect is never told
    the same thing twice, and 0 (no header) replays the session from the beginning.

    A file that is not there yet is an empty stream, not an error: the pane may open the
    stream before the first event is written. A line that does not parse ends the replay
    rather than raising - the one way a line is malformed is a backend killed mid-write,
    and what the pane needs then is everything that survived, followed by the live stream.
    """
    file = Path(path)
    if not file.is_file():
        return
    with file.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                event = AgentEvent.model_validate_json(text)
            except ValidationError:
                return
            if event.seq > after:
                yield event


class Subscriber:
    """One live listener on a chat's stream: a thread-safe queue with a non-blocking read.

    Fed from the chat's worker thread by `EventStream.publish` and drained by the SSE
    endpoint on the event loop. `closed` is set by `EventStream.subscribe` on the way out
    so a stream the pane has closed stops being fed for the rest of the run.
    """

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[AgentEvent] = queue.SimpleQueue()
        self.closed = False

    def offer(self, event: AgentEvent) -> None:
        """Hand one event to this listener. Called from the worker thread."""
        if not self.closed:
            self._queue.put(event)

    def drain(self) -> list[AgentEvent]:
        """Everything waiting, in order, without blocking. Empty when there is nothing."""
        events: list[AgentEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                return events


class EventStream:
    """The live fan-out of one chat. The file is written by the run's `EventSink`."""

    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._lock = threading.Lock()

    def publish(self, event: AgentEvent) -> None:
        """Hand one event to every current listener. Registered as an `EventSink` listener."""
        with self._lock:
            listeners = list(self._subscribers)
        for listener in listeners:
            listener.offer(event)

    @contextmanager
    def subscribe(self) -> Iterator[Subscriber]:
        """Listen for the duration of the block; the subscription is closed on the way out."""
        subscriber = Subscriber()
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            yield subscriber
        finally:
            subscriber.closed = True
            with self._lock:
                self._subscribers.discard(subscriber)


# --- one chat ------------------------------------------------------------------------


@dataclass
class ChatSession:
    """One chat between the pane and one review (data-model section 3).

    `chat_id` is distinct from `ReviewSession.session_id`: the chat is the conversation,
    the review session is what it wrote. `token` and `bridge` are held here because the
    server checks them, and are the two things `public()` never echoes.
    """

    chat_id: UUID = field(default_factory=uuid4)
    run_dir: Path = field(default_factory=Path)
    provider: str = ""
    model: str = ""
    effort: str = "high"
    engineer: str = ""
    retry_of: UUID | None = None
    token: str = ""
    """The per-launch HTTP secret. Never returned by `GET /sessions/{chat_id}`."""
    bridge: Mapping[str, Any] | None = None
    """The pipe and secret the live bridge uses. Never echoed either."""
    state: ChatState = ChatState.IDLE
    run: ReviewRun | None = None
    review_session_id: UUID | None = None
    created_at: datetime | None = None
    stop_requested: threading.Event = field(default_factory=threading.Event)
    """Set by `POST /stop`; read at the next tool boundary by the server's tool wrapper."""
    stream: EventStream = field(default_factory=EventStream)
    fallback_sink: EventSink | None = None
    """Where a chat that failed before its runner existed writes that one event; see `emit`."""
    events_file: Path | None = None
    """Where this chat's stream ended up once a retry rotated it aside; see `events_path`."""

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)

    # --- state ------------------------------------------------------------------

    def to(self, state: ChatState) -> None:
        """Move to `state`, or raise `InvalidTransitionError` naming both states."""
        if state not in TRANSITIONS[self.state]:
            allowed = ", ".join(sorted(item.value for item in TRANSITIONS[self.state])) or "nothing"
            raise InvalidTransitionError(
                f"chat {self.chat_id} is {self.state.value!r} and cannot become "
                f"{state.value!r}; from {self.state.value!r} it can become {allowed}"
            )
        self.state = state

    @property
    def finished(self) -> bool:
        """True once no further turn can be started without the engineer asking for one."""
        return self.state in (ChatState.ENDED, ChatState.FAILED)

    @property
    def open_requests(self) -> list[str]:
        """The ids of the evidence requests still open, read from the live session.

        Derived rather than stored: the runner marks a request answered on the session
        itself, and a second copy of that fact here could only ever be the stale one.
        """
        if self.run is None:
            return []
        return [item.id for item in self.run.session.evidence_requests if item.status == "open"]

    # --- the run ----------------------------------------------------------------

    def attach(self, run: ReviewRun) -> None:
        """Bind the review this chat drives. Called once, when extraction succeeded."""
        self.run = run
        self.review_session_id = run.session.session_id

    @property
    def events_path(self) -> Path:
        """`events.jsonl` for this chat: the run's file, or where the run would write it.

        `events_file` wins when it is set, which is what a retry into the same run folder
        does to the chat it replaces (`server._rotate_previous`): the superseded stream is
        moved to `events.1.jsonl`, and a pane reconnecting to that chat has to be replayed
        what *it* wrote rather than what is now in its place.
        """
        if self.events_file is not None:
            return self.events_file
        if self.run is not None:
            return self.run.events_path
        return self.run_dir / EVENTS_FILE_NAME

    @property
    def report_path(self) -> Path:
        return self.run_dir / REPORT_FILE_NAME

    # --- the stream -------------------------------------------------------------

    def publish(self, event: AgentEvent) -> None:
        """The `EventSink` listener: hand one written event to every live subscriber."""
        self.stream.publish(event)

    def subscribe(self) -> AbstractContextManager[Subscriber]:
        """Listen to this chat for the duration of the block (`EventStream.subscribe`)."""
        return self.stream.subscribe()

    def emit(self, event_type: EventType, body: Mapping[str, Any]) -> AgentEvent:
        """Write one event the server itself produces (a stop, a disposition, a shutdown).

        It goes through the run's sink, which is the only thing that knows what `seq` this
        session is up to. A chat with no run has written nothing, so the one event it can
        still owe - the error that failed it before the runner existed - is written
        through a sink of its own; that path is terminal, so the two can never interleave.
        """
        if self.run is not None:
            return self.run.sink.emit(event_type, body)
        if self.fallback_sink is None:
            self.fallback_sink = EventSink(self.events_path, listeners=[self.publish])
        return self.fallback_sink.emit(event_type, body)

    # --- what the pane is told ---------------------------------------------------

    def public(self) -> dict[str, Any]:
        """The `ChatSession` as `GET /sessions/{chat_id}` returns it: no token, no bridge."""
        return {
            "chat_id": str(self.chat_id),
            "state": self.state.value,
            "run_dir": str(self.run_dir),
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
            "engineer": self.engineer,
            "retry_of": str(self.retry_of) if self.retry_of is not None else None,
            "review_session_id": (
                str(self.review_session_id) if self.review_session_id is not None else None
            ),
            "open_requests": self.open_requests,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
        }


# --- the engineer's decision ----------------------------------------------------------


def record_disposition(
    run: ReviewRun,
    finding_id: str,
    *,
    decision: str,
    note: str,
    by: str,
) -> Finding:
    """Disposition one finding of a **live** review, and say so on the stream (FR-012).

    `report/dispositions.apply_disposition` is the offline form: it loads `session.json`,
    applies the decision and writes the file back. That is exactly wrong for a chat, whose
    session is held in memory by the run and saved again at the end of every turn - a
    decision written only to disk would be overwritten by the next finalization. So the
    same validated transition is applied to the session the run is holding, and the file
    and the report are rendered from that.

    The ranking is computed here and handed to both writes rather than the folder being
    re-rendered through `rerender_run_folder`, for the same reason: the run is holding the
    package (`run.context.ir`) and the session, and re-reading the folder to recover what
    is already in hand would be a second read that can only lose. One `rank` call serves
    the report and the record, so the section the engineer re-opens and `attention.json`
    beside it are the same order (research R2.7).

    Raises `KeyError` for an unknown finding id and `ValueError` for an unknown decision or
    a transition the state machine forbids; nothing is written on either path.
    """
    session = run.session
    finding = set_disposition(session, finding_id, decision, note, by)
    save_session(session, run.session_path)
    ranking = rank(session)
    (run.out_dir / REPORT_FILE_NAME).write_text(
        render_report(session, run.context.ir, ranking=ranking), encoding="utf-8"
    )
    write_attention_record(run.out_dir, ranking, session.session_id)
    disposition = finding.disposition
    run.sink.emit(
        "disposition",
        {
            "finding_id": finding.id,
            "disposition": disposition.model_dump(mode="json") if disposition else None,
        },
    )
    return finding


# --- the engineer's minutes -----------------------------------------------------------


def record_timing_live(
    run: ReviewRun,
    *,
    baseline: float | None = None,
    supervision: float | None = None,
    verification: float | None = None,
    false_alarms: float | None = None,
) -> Timing:
    """Record the four human inputs on a **live** review and re-render its report.

    `benchmark.timing.record_timing_at` is the offline form, and it is exactly wrong for a
    chat for the reason `record_disposition` above gives: the run holds the session in
    memory and writes it again at the end of every turn, so minutes written only to disk
    would be gone after the engineer's next message. The values are applied to the session
    the run is holding, and the file and the report are rendered from that.

    The report and `attention.json` are written from one `rank` call over that session,
    exactly as `record_disposition` writes them and for the reason given there.

    No event is emitted: timing is the engineer's own bookkeeping, not something the review
    did (`contracts/timing.md` section 3). Raises `pydantic.ValidationError` for a negative
    value, naming the field, having written nothing.
    """
    session = run.session
    session.timing = timing_with(
        session.timing,
        baseline=baseline,
        supervision=supervision,
        verification=verification,
        false_alarms=false_alarms,
    )
    save_session(session, run.session_path)
    ranking = rank(session)
    (run.out_dir / REPORT_FILE_NAME).write_text(
        render_report(session, run.context.ir, ranking=ranking), encoding="utf-8"
    )
    write_attention_record(run.out_dir, ranking, session.session_id)
    return session.timing
