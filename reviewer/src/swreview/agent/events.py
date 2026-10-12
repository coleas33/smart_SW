"""The event stream two runs share: stamping, the append-only file, and the fan-out.

`agent/runner.py` owns a **review**: a checklist, findings, evidence requests, coverage
buckets and a finalization that rebuilds them. `remodel/runner.py` owns a **re-model**: a
plan, a change log, a geometry gate and a grade delta. Neither shape fits the other, so
they stay two loops (plan.md Phase 1 point 9) - but everything *underneath* a loop is the
same in both, and this module is that everything:

- **`EventSink`**, the one place an event gets its `seq` and its `at`, the only writer of
  `events.jsonl`, and the fan-out to live listeners. Copied rather than shared, the two
  runs would have two stamping rules and, the first time one changed, two dialects of a
  file the pane replays from either (`002/contracts/chat-events.schema.json` is
  authoritative for both).
- **`replay_events`**, the one reader of that file, beside its writer: the pane's reconnect
  and remodel replay through it, and the benchmark's readers move onto it in US3, US6 and
  US7 (feature 014 plan decision RF-29); **`event_stream`** finds a benchmark run's stream,
  plain or packed (owner decision 28A, plan decision RF-83).
- **`UsageLedger`**, which rides on that stream as a listener and is therefore shared by
  construction: it reads `usage` and `turn.ended` events and knows nothing about what run
  produced them.
- **`DEFAULT_MAX_STEPS`**, the per-turn step budget, and **`no_redaction`**, the redactor
  hand-off a run applies to provider error text before it reaches the run folder. Both are
  one-line pieces of policy, which is exactly why they would otherwise be retyped.
- **`emit_error`** and **`emit_turn_failed`**, how a run reports something that raised: the
  redaction, the `error_body` shape and the `turn.ended` that closes the turn it happened
  in. What each run does *after* that differs - a review finalizes and re-raises, a
  re-model records the absence and carries on - but what reaches the stream must not.

The other half of the `TurnEndReason` reading, the sentence a turn cut short is written
down as, lives in `report/session.py` as `cut_short_reason`, beside the two constants it
composes and the `was_cut_short` predicate that reads them back.

Nothing here knows what a review is. The dependency runs one way - a run imports the
stream, never the reverse - and the only thing this module imports from outside the
provider layer is `SessionUsage`, which is the single summing rule for token counts and is
not review-shaped despite the module it lives in (`report/session.py`).
"""

from __future__ import annotations

import gzip
import re
import zlib
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from swreview.agent.providers import (
    AgentEvent,
    EventType,
    TokenUsage,
    error_body,
    usage_from_body,
)
from swreview.report.session import SessionUsage

EVENTS_FILE_NAME = "events.jsonl"

PACKED_EVENTS_FILE_NAME = "events.jsonl.gz"
"""A benchmark run's stream once `swreview benchmark pack`, which US7 adds, has packed it
(owner decision 28A). Recordings and live sessions are never packed, so the pane only reads
the plain name."""

DEFAULT_MAX_STEPS = 200
"""Tool calls one turn may make. A session of many turns may make many times this."""


def no_redaction(text: str) -> str:
    """What a run with no secret to hide masks with: nothing.

    A run is given a redactor rather than a list of secrets, so the runner never holds a
    key at all, and a keyless run takes the same code path as a real one instead of a
    branch nobody exercises.
    """
    return text


def utc_now() -> datetime:
    """The default clock. Injected rather than called directly so `at` is assertable."""
    return datetime.now(UTC)


EventListener = Callable[[AgentEvent], None]
"""A live consumer of the stream: the chat server's SSE fan-out, a CLI trace, a test."""


class EventSink:
    """The one place an event gets its `seq` and its timestamp, and the only writer.

    Adapters call `emit(type, body)` without a sequence number, because an adapter sees
    one turn and `seq` is monotonic per *session* (`agent/providers` docstring). The sink
    stamps it, appends the event to `events.jsonl` as one JSON line, and hands it to every
    listener. The file is opened per event and appended to: the stream is append-only and
    has to survive the process dying mid-review, which is exactly when the pane needs to
    replay it.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        listeners: Iterable[EventListener] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._listeners = list(listeners)
        self._clock = clock if clock is not None else utc_now
        self._seq = 0

    @property
    def seq(self) -> int:
        """The sequence number of the last event emitted; 0 before the first."""
        return self._seq

    def emit(self, event_type: EventType, body: Mapping[str, Any]) -> AgentEvent:
        """Stamp, write and fan out one event. Its shape is the contract's, not ours."""
        self._seq += 1
        event = AgentEvent(
            seq=self._seq,
            at=self._clock(),
            type=event_type,
            body=dict(body),
        )
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
        for listener in self._listeners:
            listener(event)
        return event

    def add_listener(self, listener: EventListener) -> None:
        """Attach a consumer after the sink was built.

        `ReviewRun` is handed a sink it did not construct - `start_review` builds it with
        the caller's callbacks - and it has to put its usage ledger on that same stream.
        Registering here rather than threading the ledger through `start_review` means a
        `ReviewRun` built any other way (a test, a future caller) still accumulates, and
        there is no second construction site to keep in step.
        """
        self._listeners.append(listener)


_NOT_UTF8 = re.compile("[\udc80-\udcff]")
"""What `_open_stream` decodes each byte that is not UTF-8 to: a lone surrogate
(`errors="surrogateescape"`), which no UTF-8 text decodes to. Pydantic would refuse such a line
too (`model_validate_json` raises a `ValidationError` on a lone surrogate), so the check is there
for clarity: it names the cut character as the reason a line is unreadable."""


def replay_events(
    path: Path | str,
    after: int = 0,
    *,
    on_unreadable: Callable[[int], None] | None = None,
) -> Iterator[AgentEvent]:
    """Every event in `events.jsonl` whose `seq` is greater than `after`.

    `after` is the `Last-Event-ID` the pane reconnected with, so a reconnect is never told
    the same thing twice, and 0 (no header) replays the session from the beginning.

    A file that is not there yet is an empty stream, not an error: the pane may open the
    stream before the first event is written. A line that does not parse ends the replay
    rather than raising - the one way a line is malformed is a backend killed mid-write,
    and what the pane needs then is everything that survived, followed by the live stream.
    A write cut inside a multibyte character (a tolerance sign, say) leaves a line that is
    not UTF-8, and that line ends the replay the same way: each byte that is not UTF-8
    decodes to a lone surrogate in the line that holds it, so the damage is its own line's
    and no earlier line's. Lines end where text mode ends them, at a newline, a carriage
    return and newline, or a lone carriage return, as at `be01974` (owner decision 38A).

    A path whose name ends `.gz` is a packed stream (`PACKED_EVENTS_FILE_NAME`) and reads
    as its plain form. A truncated or corrupt archive ends the replay as a malformed line
    does, at the line being read when decompression failed.

    `on_unreadable` is told where a replay stopped short: the 1-based number of that line
    in the file, blank lines counted. It is not called for a missing or empty file, nor
    for a log read to its end - a reader that must not mistake a damaged log for a
    complete one passes it, as the benchmark's scorer, report and attempt reader will when
    they move onto it in US3, US6 and US7.
    """
    file = Path(path)
    if not file.is_file():
        return
    read = 0
    unreadable: int | None = None
    try:
        with _open_stream(file) as handle:
            for read, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                if _NOT_UTF8.search(text):
                    unreadable = read
                    break
                try:
                    event = AgentEvent.model_validate_json(text)
                except ValidationError:
                    unreadable = read
                    break
                if event.seq > after:
                    yield event
    except (EOFError, gzip.BadGzipFile, zlib.error):
        unreadable = read + 1
    if unreadable is not None and on_unreadable is not None:
        on_unreadable(unreadable)


def _open_stream(file: Path) -> TextIO:
    """The stream's lines as text, decompressed when it is packed.

    Text mode with universal newlines, as at `be01974` (owner decision 38A). A byte that is
    not UTF-8 reads as a lone surrogate (`_NOT_UTF8`) instead of raising out of a read that
    holds earlier lines too.
    """
    if file.name.endswith(".gz"):
        return gzip.open(file, "rt", encoding="utf-8", errors="surrogateescape")
    return file.open(encoding="utf-8", errors="surrogateescape")


def event_stream(folder: Path | str) -> Path:
    """Where a benchmark run folder's stream is: plain, else packed, else the plain path.

    The plain path when neither exists, which `replay_events` reads as an empty stream, as
    it does today. A folder holding both is a pack that did not finish (the pack, which US7
    adds, will write and verify the packed stream before it deletes the plain one) and is
    refused rather than read as either.
    """
    folder = Path(folder)
    plain = folder / EVENTS_FILE_NAME
    packed = folder / PACKED_EVENTS_FILE_NAME
    if plain.is_file() and packed.is_file():
        raise ValueError(
            f"{folder} holds {EVENTS_FILE_NAME} and {PACKED_EVENTS_FILE_NAME}: a pack did "
            "not finish; run swreview benchmark pack on its run again"
        )
    if plain.is_file():
        return plain
    if packed.is_file():
        return packed
    return plain


class UsageLedger:
    """The one accumulator of what a session cost: an `EventSink` listener.

    It reads the stream rather than the adapters, and that is the whole point. Both
    adapters raise out of their round loop on a provider error and `ReviewRun._run_turn`'s
    `except Exception` branch finalizes and re-raises with **no `TurnResult` to read**, so
    usage carried home on the turn's result would report zero cost for the turn that cost
    the most - five paid rounds and a rate limit on the sixth. `EventSink.emit` appends and
    closes per event, so by the time the exception arrives those five rounds are on disk
    and this ledger has already counted them.

    It owns no arithmetic: `SessionUsage.summed` is the one summing rule and this calls it.
    `turn.ended` delimits a turn, which is why no adapter has to carry a turn number.
    """

    def __init__(self) -> None:
        self._rounds: list[TokenUsage] = []
        self._turn_boundaries: list[int] = []
        """How many rounds had been recorded when each turn ended, one entry per
        `turn.ended`. Rounds after the last entry are a turn that never ended."""
        self._rounds_at_text_done: int | None = None
        """How many rounds had been recorded at the most recent `text.done`, or `None`
        before the first (feature 009 data-model section 6)."""

    def __call__(self, event: AgentEvent) -> None:
        if event.type == "usage":
            self._rounds.append(usage_from_body(event.body))
        elif event.type == "turn.ended":
            self._turn_boundaries.append(len(self._rounds))
        elif event.type == "text.done":
            self._rounds_at_text_done = len(self._rounds)

    @property
    def current_round_count(self) -> int:
        """Reported rounds since the most recent turn boundary."""
        return len(self._rounds) - (self._turn_boundaries[-1] if self._turn_boundaries else 0)

    def usage(self) -> SessionUsage | None:
        """What the session has cost so far, or `None` if no round reported anything.

        `None` and not an all-zero record: a run whose provider reported nothing cost
        something we did not measure, which is not zero (Principle I).
        """
        if not self._rounds:
            return None
        return SessionUsage.summed(self._rounds, self._turn_boundaries)

    def last_conversation_input(self) -> int | None:
        """The input tokens of the last round before the most recent `text.done`.

        What resuming the review once last cost, for the sentence beside the questions
        panel's Send (feature 009 FR-016). The round *before* `text.done` because the
        explanation pass's presentation request is emitted after it and is small; the most
        recent `text.done` because a turn stopped before its answer wrote none. `None` before
        any `text.done`, with no round before it, or when that round reported no input.
        """
        if not self._rounds_at_text_done:
            return None
        return self._rounds[self._rounds_at_text_done - 1].input_tokens


def emit_error(
    sink: EventSink,
    exc: BaseException,
    redact: Callable[[str], str] = no_redaction,
) -> str:
    """Report one failure on the stream and hand back the text that was written.

    Whatever raised - an adapter's own mapped error, an SDK class it does not map, a
    transport failure - the run folder must not receive the key the request carried
    (FR-015). The adapters redact what they wrap; this is the one place that covers what
    none of them did.

    `retryable` is always true here: a caller that has caught an exception cannot tell a
    dropped connection from a bug, and the engineer, not this module, decides whether to
    spend another run (FR-028). An adapter that does know emits its own `error` first.
    """
    message = redact(str(exc))
    sink.emit(
        "error",
        error_body(error_class=type(exc).__name__, message=message, retryable=True),
    )
    return message


def emit_turn_failed(
    sink: EventSink,
    exc: BaseException,
    redact: Callable[[str], str] = no_redaction,
) -> str:
    """`emit_error`, then the `turn.ended` that closes the turn it happened in.

    Both runs report a turn that raised this way and in this order, and the order matters
    to more than a reader: `UsageLedger` delimits a turn on `turn.ended`, so the rounds
    that were paid for before the failure are counted into the turn they belong to.

    A failure with no turn behind it - a provider that could not be constructed - calls
    `emit_error` instead, because a turn that never started never ended.
    """
    message = emit_error(sink, exc, redact)
    sink.emit("turn.ended", {"reason": "error"})
    return message
