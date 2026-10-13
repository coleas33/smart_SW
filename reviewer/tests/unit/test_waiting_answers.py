"""US3: code applies waiting answers without a model turn, and preserves the work."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from swreview.agent import runner
from swreview.agent.events import replay_events
from swreview.agent.providers.deferred import DeferredProvider
from swreview.bridge.client import BridgeError
from swreview.checks.drawing_context import CANDIDATE_CONFIRM
from swreview.report.session import load_session
from swreview.report.summary import load_words
from tests.support.questions_package import QuestionsPackage, build_questions_package
from tests.support.recording_provider import RecordingProvider
from tests.support.roles_review import PIN_ID
from tests.unit import test_chat_server as chat
from tests.unit import test_send_gate_server as send_cases
from tests.unit.test_chat_timing_route import FOUR

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
pipe_app = send_cases.pipe_app
pipe_client = send_cases.pipe_client


@dataclass(frozen=True)
class Waiting:
    fixture: QuestionsPackage
    chat_id: str
    held: Any

    @property
    def run(self) -> runner.ReviewRun:
        return self.held.run


def waiting_review(app: Any, client: TestClient, folder: Path) -> Waiting:
    fixture = build_questions_package(folder)
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    response = client.post(
        "/sessions",
        json=chat.session_body(
            folder,
            standards_profile=str(fixture.profile),
            bridge={"pipe": "FICT-pipe", "secret": "FICT-secret"},
            send_when_checked=False,
        ),
    )
    assert response.status_code == 201, response.text
    chat_id = str(response.json()["chat_id"])
    assert chat.state_of(client, chat_id) == "awaiting_send"
    return Waiting(fixture, chat_id, app.state.server.chats[UUID(chat_id)])


def question(waiting: Waiting, *, drawing: bool = False) -> Any:
    return next(
        item
        for item in waiting.run.session.evidence_requests
        if (CANDIDATE_CONFIRM in item.options) == drawing
    )


def apply(client: TestClient, waiting: Waiting, *answers: tuple[str, str]) -> Any:
    return client.post(
        f"/sessions/{waiting.chat_id}/evidence",
        json={"answers": [{"request_id": rid, "answer": answer} for rid, answer in answers]},
    )


def new_events(waiting: Waiting, marker: int) -> list[Any]:
    return [event for event in replay_events(waiting.run.events_path) if event.seq > marker]


def test_all_bought_regrades_and_withdraws_without_building_a_provider_or_turn(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-all-bought")
    run = waiting.run
    pin_components = {item.id for item in run.context.ir.components if item.document_id == PIN_ID}
    role_steps = {step.index for step in run.session.steps if step.tool in runner.ROLES_RESTATED}
    withdrawn = [
        f.id
        for f in run.session.findings
        if set(f.component_ids) & pin_components and set(f.tool_result_ids) & role_steps
    ]
    assert withdrawn
    remaining = [f.id for f in run.session.findings if f.id not in withdrawn]
    marker = run.sink.seq
    answer = question(waiting)

    response = apply(client, waiting, (answer.id, "All bought"))
    assert response.status_code == 202, response.text
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    events = new_events(waiting, marker)
    assert [
        event.body["finding_id"] for event in events if event.type == "finding.withdrawn"
    ] == withdrawn
    assert [f.id for f in run.session.findings] == remaining
    assert provider_control.built == []
    assert isinstance(run.provider, DeferredProvider)
    assert run.messages == [] and run.turns == 0 and run.awaiting_send
    assert not any(event.type.startswith("turn.") for event in events)


def test_the_applied_record_report_attention_and_summary_replace_the_waiting_review(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-records")
    run = waiting.run
    before = {
        name: (run.out_dir / name).read_bytes()
        for name in ("session.json", "report.md", "attention.json")
    }
    marker = run.sink.seq
    response = apply(client, waiting, (question(waiting).id, "All bought"))
    assert response.status_code == 202, response.text
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    saved = load_session(run.session_path)
    assert saved == run.session
    assert saved.evidence_requests[0].status == "answered"
    assert saved.model_status.state == "not_sent"
    assert all((run.out_dir / name).read_bytes() != raw for name, raw in before.items())
    assert [event.type for event in new_events(waiting, marker)].count("session.ended") == 1
    report = (run.out_dir / "report.md").read_text(encoding="utf-8")
    assert "- Model: not sent to the model (checked by code only)" in report
    attention = json.loads((run.out_dir / "attention.json").read_bytes())
    assert attention["session_id"] == str(saved.session_id)
    snapshot = client.get(f"/sessions/{waiting.chat_id}/snapshot").json()
    summary = snapshot["ranking"]["summary"]
    assert summary["resume_text"] == load_words().send.apply_answers
    assert summary["send"]["state"] == "waiting"
    assert [f["id"] for f in snapshot["findings"]] == [f.id for f in saved.findings]
    assert provider_control.built == []


def test_the_apply_replaces_the_cache_once_on_its_worker_before_finalization(
    app: Any,
    client: TestClient,
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-cache")
    run = waiting.run
    old_cache = run._send_cache
    order: list[tuple[str, int]] = []
    close, build, finalize = run.close_waiting, run.build_send_cache, run.finalize
    loop: list[int] = []
    require_idle = app.state.server._require_idle

    def on_loop(held: Any) -> None:
        loop.append(threading.get_ident())
        return require_idle(held)

    def closed() -> Any:
        order.append(("close", threading.get_ident()))
        return close()

    def built() -> None:
        order.append(("build", threading.get_ident()))
        build()

    def finalized() -> Any:
        order.append(("finalize", threading.get_ident()))
        return finalize()

    monkeypatch.setattr(app.state.server, "_require_idle", on_loop)
    monkeypatch.setattr(run, "close_waiting", closed)
    monkeypatch.setattr(run, "build_send_cache", built)
    monkeypatch.setattr(run, "finalize", finalized)
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    assert [name for name, _ in order] == ["close", "build", "finalize"]
    assert len({identity for _, identity in order}) == 1
    assert loop and order[0][1] not in loop
    worker = app.state.server._workers[UUID(waiting.chat_id)]
    assert order[0][1] == next(iter(worker._threads)).ident
    assert run._send_cache is not old_cache and run._opening_changed
    assert provider_control.built == []


def test_an_answered_waiting_question_cannot_be_answered_again(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-repeat")
    answer = question(waiting)
    assert apply(client, waiting, (answer.id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    before = send_cases.files_in(waiting.fixture.folder)
    response = apply(client, waiting, (answer.id, "None bought"))
    assert response.status_code == 409 and response.json()["error_class"] == "AlreadyAnswered"
    assert send_cases.files_in(waiting.fixture.folder) == before
    assert chat.state_of(client, waiting.chat_id) == "awaiting_send"
    assert provider_control.built == []


def test_send_is_refused_while_code_is_applying_an_answer(
    app: Any,
    client: TestClient,
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-held-apply")
    entered, release = threading.Event(), threading.Event()
    original = runner.classify_part_roles

    def held(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(chat.TIMEOUT_S)
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "classify_part_roles", held)
    try:
        assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
        assert entered.wait(chat.TIMEOUT_S)
        response = client.post(f"/sessions/{waiting.chat_id}/send", json={})
        assert response.status_code == 409 and response.json()["error_class"] == "TurnRunning"
        assert provider_control.built == []
    finally:
        release.set()
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    assert provider_control.built == []


def test_an_answer_is_refused_while_a_send_is_in_flight(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-held-send")
    assert provider_control.built == []
    provider_control.hold()
    try:
        assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
        assert provider_control.started.wait(chat.TIMEOUT_S)
        response = apply(client, waiting, (question(waiting).id, "All bought"))
        assert response.status_code == 409 and response.json()["error_class"] == "TurnRunning"
        assert question(waiting).status == "open"
    finally:
        provider_control.release()
    chat.settle(client, waiting.chat_id)


@pytest.mark.parametrize("refused", [False, True])
def test_a_waiting_confirmed_drawing_records_its_outcome_without_a_turn(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    refused: bool,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-drawing")
    if refused:
        waiting.fixture.bridge._raises["drawing_read"] = BridgeError("FICT-read-refused")
    marker = waiting.run.sink.seq
    response = apply(client, waiting, (question(waiting, drawing=True).id, CANDIDATE_CONFIRM))
    assert response.status_code == 202, response.text
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    assert len(waiting.run.session.drawing_outcomes) == 1
    outcome = waiting.run.session.drawing_outcomes[0]
    assert outcome.file == "FICT-7001.SLDDRW"
    assert outcome.outcome == (
        "FICT-read-refused" if refused else "opened read-only, read and closed (1 sheet)"
    )
    assert load_session(waiting.run.session_path).drawing_outcomes == [outcome]
    assert [command for command, _ in waiting.fixture.bridge.calls].count("drawing_read") == 1
    assert not any(event.type.startswith("turn.") for event in new_events(waiting, marker))
    assert provider_control.built == []


def test_a_confirmed_read_reopens_the_real_pipe_and_the_apply_settle_closes_it(
    pipe_app: Any,
    pipe_client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    started = send_cases.pipe_review(pipe_client, run_root / "FICT-waiting-pipe")
    assert started.status_code == 201, started.text
    chat_id = str(started.json()["chat_id"])
    held = pipe_app.state.server.chats[UUID(chat_id)]
    transport = pipe_app.state.pipe_transports[0]
    request = next(
        item for item in held.run.session.evidence_requests if CANDIDATE_CONFIRM in item.options
    )
    assert transport.opened == transport.closed == 1
    response = pipe_client.post(
        f"/sessions/{chat_id}/evidence",
        json={"answers": [{"request_id": request.id, "answer": CANDIDATE_CONFIRM}]},
    )
    assert response.status_code == 202, response.text
    assert chat.settle(pipe_client, chat_id) == "awaiting_send"
    assert transport.opened == transport.closed == 2 and transport.open_pipes == 0
    assert [request["command"] for request in transport.requests].count("drawing.read") == 1
    assert held.run.session.drawing_outcomes
    assert provider_control.built == []


def test_a_reject_and_timing_written_while_waiting_are_kept_at_send(
    app: Any,
    client: TestClient,
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-work")
    finding = waiting.run.session.findings[0]
    decision = {"decision": "rejected", "note": "FICT engineer decision"}
    response = client.post(
        f"/sessions/{waiting.chat_id}/findings/{finding.id}/disposition",
        json=decision,
    )
    assert response.status_code == 200, response.text
    saved = load_session(waiting.run.session_path)
    assert next(f for f in saved.findings if f.id == finding.id).disposition.decision == "rejected"
    assert chat.state_of(client, waiting.chat_id) == "awaiting_send"
    timed = client.post(f"/sessions/{waiting.chat_id}/timing", json=FOUR)
    assert timed.status_code == 200, timed.text
    assert provider_control.built == []
    provider = RecordingProvider([chat.turn("FICT sent")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    sent = load_session(waiting.run.session_path)
    assert next(f for f in sent.findings if f.id == finding.id).disposition.decision == "rejected"
    assert sent.timing.baseline_minutes == 45 and sent.timing.net_saved_minutes is not None
    assert sent.timing.assisted_supervision_minutes == 6
    assert sent.timing.assisted_verification_minutes == 9
    assert sent.timing.false_alarm_handling_minutes == 2
    assert provider.log
