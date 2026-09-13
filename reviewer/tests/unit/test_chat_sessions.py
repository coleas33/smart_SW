"""The chat session state machine, its event file and its live fan-out (T035).

Three things `chat/sessions.py` owns, and this module pins each of them down:

1. **The state machine of data-model section 3.** `idle -> extracting -> running ->
   (waiting_engineer <-> running)* -> ended`, plus `ended -> running` when the engineer
   sends a follow-up on a session whose previous turn already ended (FR-006), plus any
   state `-> failed`, which is terminal: its only exit is a new session carrying
   `retry_of`. Every transition the table does not name raises, because a chat that
   silently slid from `ended` back to `extracting` would answer `GET /sessions/{id}` with
   a state the pane cannot draw.
2. **`events.jsonl`.** The runner's `EventSink` is the only writer, so what is asserted
   here is what a *chat* adds: that the file the session names is the file the run wrote,
   that `seq` is contiguous from 1 across every turn, and that `replay_events` hands the
   pane exactly the events after the `Last-Event-ID` it reconnected with.
3. **The live fan-out.** A subscriber registered before a turn sees everything that turn
   emits, in order; one registered after it sees only what comes next, which is why
   replay-then-live is the pane's reconnect and not just a convenience.

`record_disposition` is here too rather than in the server: it is the engineer's decision
applied to a *live* session, and the server endpoint is one caller of it. The disposition
event has no other producer (`chat-events.schema.json`), so its shape is asserted against
the contract in `test_events_schema.py` as well.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from swreview.agent import runner
from swreview.agent.providers import AgentEvent
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.chat.sessions import (
    ChatSession,
    ChatState,
    InvalidTransitionError,
    record_disposition,
    replay_events,
)
from swreview.report.session import load_session

MODEL = "fake-1"

DRAWING_FINDING_ARGUMENTS: dict[str, Any] = {
    "document_id": "doc:2",
    "sheet": "Sheet1",
    "observed": "The tapped hole is called out without a thread depth",
    "requirement": "A tapped hole callout states the usable thread depth",
    "source_refs": [{"document_id": "doc:2", "sheet": "Sheet1"}],
    "status": "suspected",
    "recommended_action": "Add the tapped depth to the hole callout",
}
EVIDENCE_ARGUMENTS: dict[str, Any] = {
    "what": "The usable thread depth of hole:1",
    "why": "fastener.engagement needs it; re-run that check once it is answered",
    "entity_ids": ["hole:1"],
}


def call(name: str, **arguments: Any) -> ScriptedToolCall:
    return ScriptedToolCall(name=name, arguments=arguments)


def turn(text: str, *calls: ScriptedToolCall) -> ScriptedTurn:
    return ScriptedTurn(text=text, tool_calls=calls)


@pytest.fixture
def chat(tmp_path: Path) -> ChatSession:
    """A chat session with no run behind it: enough to drive the state machine."""
    return ChatSession(
        chat_id=uuid4(),
        run_dir=tmp_path / "run",
        provider="fake",
        model=MODEL,
        effort="high",
        engineer="a.engineer",
        token="the-launch-token",
        bridge={"pipe": "swreview-1", "secret": "the-bridge-secret"},
    )


@pytest.fixture
def start_run(tmp_package_dir: Path, tmp_path: Path) -> Callable[..., runner.ReviewRun]:
    """`start_review` over the fixture package with a scripted provider, not yet played."""

    def begin(script: Sequence[ScriptedTurn], **kwargs: Any) -> runner.ReviewRun:
        return runner.start_review(
            tmp_package_dir,
            tmp_path / "out",
            provider=FakeProvider(script=script, model=MODEL),
            effort="high",
            **kwargs,
        )

    return begin


# --- the state machine --------------------------------------------------------------


def test_a_new_chat_is_idle_and_knows_nothing_about_a_review_yet(chat: ChatSession) -> None:
    assert chat.state is ChatState.IDLE
    assert chat.review_session_id is None
    assert chat.run is None
    assert chat.open_requests == []


def test_the_documented_path_runs_from_idle_to_ended(chat: ChatSession) -> None:
    """`idle -> extracting -> running -> (waiting_engineer <-> running)* -> ended`."""
    for state in (
        ChatState.EXTRACTING,
        ChatState.RUNNING,
        ChatState.WAITING_ENGINEER,
        ChatState.RUNNING,
        ChatState.WAITING_ENGINEER,
        ChatState.RUNNING,
        ChatState.ENDED,
    ):
        chat.to(state)
        assert chat.state is state


def test_a_follow_up_takes_an_ended_session_back_to_running(chat: ChatSession) -> None:
    """FR-006, US1 scenarios 4 and 5: an ended session still takes another turn."""
    chat.to(ChatState.EXTRACTING)
    chat.to(ChatState.RUNNING)
    chat.to(ChatState.ENDED)

    chat.to(ChatState.RUNNING)

    assert chat.state is ChatState.RUNNING


@pytest.mark.parametrize(
    "path",
    [
        (),
        (ChatState.EXTRACTING,),
        (ChatState.EXTRACTING, ChatState.RUNNING),
        (ChatState.EXTRACTING, ChatState.RUNNING, ChatState.WAITING_ENGINEER),
        (ChatState.EXTRACTING, ChatState.RUNNING, ChatState.ENDED),
    ],
)
def test_every_state_can_fail(chat: ChatSession, path: tuple[ChatState, ...]) -> None:
    """"any state -> failed on an unrecoverable error" is the whole of the rule."""
    for state in path:
        chat.to(state)

    chat.to(ChatState.FAILED)

    assert chat.state is ChatState.FAILED


@pytest.mark.parametrize("target", list(ChatState))
def test_failed_is_terminal(chat: ChatSession, target: ChatState) -> None:
    """Its only exit is a new `ChatSession` carrying `retry_of`, which is the server's job."""
    chat.to(ChatState.FAILED)

    with pytest.raises(InvalidTransitionError):
        chat.to(target)

    assert chat.state is ChatState.FAILED


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ((), ChatState.WAITING_ENGINEER),
        ((), ChatState.ENDED),
        ((), ChatState.RUNNING),
        ((ChatState.EXTRACTING,), ChatState.IDLE),
        ((ChatState.EXTRACTING,), ChatState.WAITING_ENGINEER),
        ((ChatState.EXTRACTING, ChatState.RUNNING), ChatState.RUNNING),
        ((ChatState.EXTRACTING, ChatState.RUNNING), ChatState.EXTRACTING),
        ((ChatState.EXTRACTING, ChatState.RUNNING, ChatState.ENDED), ChatState.EXTRACTING),
        ((ChatState.EXTRACTING, ChatState.RUNNING, ChatState.ENDED), ChatState.WAITING_ENGINEER),
    ],
)
def test_a_transition_the_table_does_not_name_raises(
    chat: ChatSession, path: tuple[ChatState, ...], target: ChatState
) -> None:
    for state in path:
        chat.to(state)
    current = chat.state

    with pytest.raises(InvalidTransitionError) as raised:
        chat.to(target)

    assert current.value in str(raised.value)
    assert target.value in str(raised.value)
    assert chat.state is current


def test_a_second_turn_cannot_start_while_one_is_running(chat: ChatSession) -> None:
    """One running turn per chat; the server turns this refusal into a 409."""
    chat.to(ChatState.EXTRACTING)
    chat.to(ChatState.RUNNING)

    with pytest.raises(InvalidTransitionError):
        chat.to(ChatState.RUNNING)


# --- what the pane is told ----------------------------------------------------------


def test_the_public_view_carries_the_state_and_never_a_secret(chat: ChatSession) -> None:
    """`GET /sessions/{chat_id}` echoes neither the HTTP token nor the bridge secret."""
    view = chat.public()

    assert view["chat_id"] == str(chat.chat_id)
    assert view["state"] == ChatState.IDLE.value
    assert view["run_dir"] == str(chat.run_dir)
    assert view["provider"] == "fake"
    assert view["model"] == MODEL
    assert view["engineer"] == "a.engineer"
    assert view["retry_of"] is None
    assert view["review_session_id"] is None
    assert view["open_requests"] == []
    assert "token" not in view
    assert "bridge" not in view

    serialized = json.dumps(view)
    assert chat.token not in serialized
    assert "the-bridge-secret" not in serialized


def test_retry_of_is_carried_as_the_chat_it_replaces(tmp_path: Path) -> None:
    failed = uuid4()
    chat = ChatSession(
        chat_id=uuid4(), run_dir=tmp_path / "run", provider="fake", model=MODEL, retry_of=failed
    )

    assert chat.retry_of == failed
    assert chat.public()["retry_of"] == str(failed)


def test_open_requests_are_read_from_the_live_session(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    """Derived, never stored: an answered request stops being open the moment it is answered."""
    script = [turn("Opened one.", call("request_evidence", **EVIDENCE_ARGUMENTS)), turn("ok")]
    run = start_run(script)
    chat.attach(run)
    run.start()

    assert chat.open_requests == ["ER-001"]

    run.answer_evidence("ER-001", "Tapped 12 mm deep.")

    assert chat.open_requests == []


def test_attaching_a_run_records_the_review_session_id_and_the_event_file(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    run = start_run([turn("done")])

    chat.attach(run)

    assert chat.review_session_id == run.session.session_id
    assert chat.events_path == run.events_path
    assert chat.public()["review_session_id"] == str(run.session.session_id)


# --- events.jsonl -------------------------------------------------------------------


def test_the_event_file_carries_a_contiguous_seq_across_every_turn(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    run = start_run([turn("first"), turn("second")])
    chat.attach(run)
    run.start()
    run.continue_session("keep going")

    events = list(replay_events(chat.events_path))

    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert events[0].type == "session.started"


def test_replay_yields_only_what_follows_the_last_event_id(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    """The pane reconnects with `Last-Event-ID` and must not be told the same thing twice."""
    run = start_run([turn("first"), turn("second")])
    chat.attach(run)
    run.start()
    run.continue_session("keep going")
    everything = list(replay_events(chat.events_path))

    after_third = list(replay_events(chat.events_path, after=3))

    assert [event.seq for event in after_third] == [event.seq for event in everything[3:]]
    assert list(replay_events(chat.events_path, after=everything[-1].seq)) == []


def test_replay_of_a_file_that_does_not_exist_yet_is_empty(tmp_path: Path) -> None:
    """A chat is asked for its stream before its first event is written; that is not an error."""
    assert list(replay_events(tmp_path / "nothing" / "events.jsonl")) == []


def test_replay_stops_at_a_line_the_crash_cut_in_half(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    """A half-written last line is what a killed backend leaves; replay what survived it."""
    run = start_run([turn("first")])
    chat.attach(run)
    run.start()
    whole = list(replay_events(chat.events_path))
    with chat.events_path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 99, "at": "2026-09-13T12:00:00Z", "type": "text.d')

    replayed = list(replay_events(chat.events_path))

    assert [event.seq for event in replayed] == [event.seq for event in whole]


# --- the live fan-out ----------------------------------------------------------------


def test_a_subscriber_receives_every_event_of_the_turn_in_order(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    run = start_run([turn("hello there")], callbacks=[chat.publish])
    chat.attach(run)

    with chat.subscribe() as subscriber:
        run.start()
        received = subscriber.drain()

    written = list(replay_events(chat.events_path))
    assert [event.seq for event in received] == [event.seq for event in written]
    assert [event.type for event in received] == [event.type for event in written]


def test_a_subscriber_that_arrives_late_is_told_only_what_comes_next(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    """Which is why the stream is replay *then* live: the file holds what it missed."""
    run = start_run([turn("first"), turn("second")], callbacks=[chat.publish])
    chat.attach(run)
    run.start()

    with chat.subscribe() as subscriber:
        run.continue_session("keep going")
        received = subscriber.drain()

    first_seq = received[0].seq
    assert first_seq > 1
    assert [event.seq for event in received] == list(
        range(first_seq, first_seq + len(received))
    )


def test_a_subscription_that_has_ended_is_no_longer_fed(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> None:
    """The pane closes the stream; a queue nobody reads must not grow for the rest of the run."""
    run = start_run([turn("first"), turn("second")], callbacks=[chat.publish])
    chat.attach(run)
    with chat.subscribe() as subscriber:
        run.start()
        subscriber.drain()

    run.continue_session("keep going")

    assert subscriber.drain() == []


def test_draining_an_empty_subscription_returns_nothing_rather_than_blocking(
    chat: ChatSession,
) -> None:
    with chat.subscribe() as subscriber:
        assert subscriber.drain() == []


# --- the engineer's disposition ------------------------------------------------------


@pytest.fixture
def run_with_a_finding(
    chat: ChatSession, start_run: Callable[..., runner.ReviewRun]
) -> runner.ReviewRun:
    """A played session holding one finding, ready to be dispositioned."""
    run = start_run(
        [turn("One finding.", call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS))],
        callbacks=[chat.publish],
    )
    chat.attach(run)
    run.start()
    return run


def test_a_disposition_is_written_to_the_session_the_report_and_the_stream(
    chat: ChatSession, run_with_a_finding: runner.ReviewRun
) -> None:
    """FR-012: `session.json` is the truth, `report.md` is rendered from it, the pane is told."""
    run = run_with_a_finding
    finding_id = run.session.findings[0].id
    before = list(replay_events(chat.events_path))

    finding = record_disposition(
        run, finding_id, decision="accepted", note="known and accepted", by="a.engineer"
    )

    assert finding.id == finding_id
    assert finding.disposition is not None
    assert finding.disposition.decision == "accepted"
    assert finding.disposition.by == "a.engineer"

    saved = load_session(run.session_path)
    assert saved.findings[0].disposition is not None
    assert saved.findings[0].disposition.note == "known and accepted"

    report = (run.out_dir / "report.md").read_text(encoding="utf-8")
    assert "accepted" in report

    emitted = list(replay_events(chat.events_path))[len(before) :]
    assert [event.type for event in emitted] == ["disposition"]
    assert emitted[0].body["finding_id"] == finding_id
    assert emitted[0].body["disposition"]["decision"] == "accepted"
    assert emitted[0].body["disposition"]["by"] == "a.engineer"


def test_the_in_memory_session_carries_the_disposition_so_the_next_turn_cannot_drop_it(
    run_with_a_finding: runner.ReviewRun,
) -> None:
    """The live run finalizes and saves after every turn; a disposition written only to
    disk would be overwritten by the next `save_session`."""
    run = run_with_a_finding
    finding_id = run.session.findings[0].id

    record_disposition(run, finding_id, decision="deferred", note="later", by="a.engineer")
    run.finalize()

    assert load_session(run.session_path).findings[0].disposition is not None


def test_an_illegal_transition_is_refused_and_nothing_is_written(
    chat: ChatSession, run_with_a_finding: runner.ReviewRun
) -> None:
    run = run_with_a_finding
    finding_id = run.session.findings[0].id
    record_disposition(run, finding_id, decision="accepted", note="", by="a.engineer")
    before = list(replay_events(chat.events_path))

    with pytest.raises(ValueError, match="terminal disposition"):
        record_disposition(run, finding_id, decision="rejected", note="", by="a.engineer")

    assert run.session.findings[0].disposition is not None
    assert run.session.findings[0].disposition.decision == "accepted"
    assert list(replay_events(chat.events_path)) == before


def test_an_unknown_finding_id_is_refused(run_with_a_finding: runner.ReviewRun) -> None:
    with pytest.raises(KeyError, match="F-404"):
        record_disposition(
            run_with_a_finding, "F-404", decision="accepted", note="", by="a.engineer"
        )


def test_a_decision_the_state_machine_does_not_know_is_refused(
    run_with_a_finding: runner.ReviewRun,
) -> None:
    run = run_with_a_finding
    with pytest.raises(ValueError, match="decision"):
        record_disposition(
            run, run.session.findings[0].id, decision="maybe", note="", by="a.engineer"
        )


def test_the_disposition_event_body_matches_the_agent_event_model(
    chat: ChatSession, run_with_a_finding: runner.ReviewRun
) -> None:
    """Every line of the file is an `AgentEvent`; the contract check lives in T024's module."""
    record_disposition(
        run_with_a_finding,
        run_with_a_finding.session.findings[0].id,
        decision="rejected",
        note="not a real condition",
        by="a.engineer",
    )

    lines = chat.events_path.read_text(encoding="utf-8").splitlines()
    event = AgentEvent.model_validate_json(lines[-1])
    assert event.type == "disposition"
    assert set(event.body) == {"finding_id", "disposition"}
    assert isinstance(UUID(str(run_with_a_finding.session.session_id)), UUID)
