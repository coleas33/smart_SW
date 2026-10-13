"""T027: one renderer preserves the ticked report and logs secondary failures."""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from swreview import atomic, tokens
from swreview.agent import runner
from swreview.agent.events import replay_events
from swreview.agent.providers.deferred import DeferredProvider
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import pane_defaults
from swreview.bridge.client import PROTOCOL_VERSION, BridgeClient
from swreview.chat import server
from swreview.chat.sessions import ChatSession, ChatState
from swreview.report.session import CoverageItem, CoverageScope, SendFailure, load_session
from tests.support.questions_package import build_questions_package
from tests.support.recording_provider import RecordingProvider
from tests.support.review_bridge import VOLUME_UNIT_GAP
from tests.support.roles_review import PLATE_ID
from tests.unit import test_chat_review_routes as routes
from tests.unit import test_chat_server as chat
from tests.unit.test_chat_timing_route import files_in

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir
finished_chat = routes.finished_chat


def test_the_shared_renderer_writes_the_same_report_and_attention_as_a_ticked_chat(
    app: Any, client: TestClient, run_dir: Path, finished_chat: str
) -> None:
    held = routes.held_chat(app, finished_chat)
    expected = {name: (run_dir / name).read_bytes() for name in ("report.md", "attention.json")}
    for name in expected:
        (run_dir / name).unlink()
    app.state.server._render_run(held.run, held.report_path, run_dir)
    assert {name: (run_dir / name).read_bytes() for name in expected} == expected


@pytest.mark.parametrize("point", ["rank", "report", "attention"])
def test_a_ranking_or_write_failure_is_logged_and_never_raises(
    app: Any,
    client: TestClient,
    run_dir: Path,
    finished_chat: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    point: str,
) -> None:
    held = routes.held_chat(app, finished_chat)

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise OSError("FICT-secondary-render-failure")

    if point == "rank":
        monkeypatch.setattr(server, "rank", refused)
    elif point == "report":
        monkeypatch.setattr(Path, "write_text", refused)
    else:
        monkeypatch.setattr(server, "write_attention_record", refused)
    app.state.server._render_run(held.run, held.report_path, run_dir)
    assert "FICT-secondary-render-failure" in caplog.text


def test_render_report_retains_its_no_run_guard_and_delegates_once(
    app: Any,
    client: TestClient,
    finished_chat: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = routes.held_chat(app, finished_chat)
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(app.state.server, "_render_run", lambda *args: calls.append(args))
    app.state.server._render_report(ChatSession())
    assert calls == []
    app.state.server._render_report(held)
    assert calls == [(held.run, held.report_path, held.run_dir)]


# T040: checks-only setup is finalized before publication and owns its pending folder.


def waiting_body(run_dir: Path, **overrides: Any) -> dict[str, Any]:
    return chat.session_body(run_dir, send_when_checked=False, **overrides)


def waiting_chat(client: TestClient, run_dir: Path, **overrides: Any) -> str:
    response = client.post("/sessions", json=waiting_body(run_dir, **overrides))
    assert response.status_code == 201, response.text
    assert set(response.json()) == {"chat_id", "review_session_id", "not_examined"}
    chat_id = response.json()["chat_id"]
    assert chat.state_of(client, chat_id) == "awaiting_send"
    return str(chat_id)


def test_no_key_start_finalizes_and_renders_before_registering_the_chat(
    app: Any,
    client: TestClient,
    run_dir: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (*server.KEY_VARIABLES, "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        monkeypatch.delenv(name, raising=False)
    owner = app.state.server
    calls: list[tuple[str, int]] = []
    loop_threads: list[int] = []
    close_waiting = ReviewRun.close_waiting
    build_cache = ReviewRun.build_send_cache
    render_run = owner._render_run
    settings = owner._settings

    def on_loop(body: Any) -> Any:
        loop_threads.append(threading.get_ident())
        return settings(body)

    def counted_cache(run: ReviewRun) -> None:
        assert owner.chats == {}
        calls.append(("cache", threading.get_ident()))
        build_cache(run)

    def closed_waiting(run: ReviewRun) -> Any:
        assert isinstance(run.provider, DeferredProvider)
        assert owner.chats == {}
        calls.append(("close", threading.get_ident()))
        return close_waiting(run)

    def rendered(run: ReviewRun, report_path: Path, directory: Path) -> None:
        assert owner.chats == {}
        assert run.session.ended_at is not None
        calls.append(("render", threading.get_ident()))
        render_run(run, report_path, directory)

    monkeypatch.setattr(ReviewRun, "build_send_cache", counted_cache)
    monkeypatch.setattr(ReviewRun, "close_waiting", closed_waiting)
    monkeypatch.setattr(owner, "_render_run", rendered)
    monkeypatch.setattr(owner, "_settings", on_loop)
    chat_id = waiting_chat(client, run_dir, provider="openai", model="gpt-4.1")
    held = owner.chats[UUID(chat_id)]
    assert [name for name, _ in calls] == ["close", "cache", "render"]
    assert len({thread for _, thread in calls}) == 1
    assert len(loop_threads) == 1
    assert calls[0][1] != loop_threads[0]
    assert held.run.awaiting_send
    assert owner._workers == {}
    assert owner._pending_run_dirs == set()
    assert held.run._send_cache is not None
    events = list(replay_events(run_dir / "events.jsonl"))
    assert events[0].type == "session.started"
    assert events[0].body["send_when_checked"] is False
    assert events[-1].type == "session.ended"
    assert not {event.type for event in events} & {"turn.started", "turn.ended"}
    saved = load_session(run_dir / "session.json")
    assert saved.model_status.state == "not_sent"
    assert saved.model_status.checked_at == saved.ended_at
    assert held.review_session_id == saved.session_id
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "- Model: not sent to the model (checked by code only)" in report
    assert json.loads((run_dir / "attention.json").read_bytes())["session_id"] == str(
        saved.session_id
    )
    assert provider_control.built == []


def test_waiting_coverage_equals_the_ticked_first_request_plus_exact_closeout_rows(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    ticked = build_questions_package(run_root / "FICT-ticked-reference")
    waiting = build_questions_package(run_root / "FICT-waiting-coverage")
    recorder = RecordingProvider([chat.turn("FICT-first-request")])
    defaults = pane_defaults(recorder.name)
    reference = start_review(
        ticked.folder,
        ticked.folder,
        provider=recorder,
        standards_profile=ticked.profile,
        bridge=True,
        bridge_factory=lambda pipe, secret: ticked.bridge,
        efficiency=defaults.efficiency,
        model_view=defaults.model_view,
        explain_findings=defaults.explain_findings,
    )
    before: dict[str, Any] = {}
    first_request = recorder.run

    def captured(**kwargs: Any) -> Any:
        if not before:
            before["coverage"] = reference.session.coverage.model_dump(mode="json")
            before["findings"] = [row.model_dump(mode="json") for row in reference.session.findings]
            before["questions"] = [
                row.model_dump(mode="json", exclude={"requested_at"})
                for row in reference.session.evidence_requests
            ]
            before["model_items"] = reference.context.checklist.open_items(
                reference.session, owner="model"
            )
            before["open_questions"] = runner.open_evidence_requests(reference.session)
            before["closeout"] = runner.closeout_item(reference.session, reference.context.ir)
        return first_request(**kwargs)

    recorder.run = captured
    try:
        reference.start()
    finally:
        reference.close()
    assert before, "the ticked reference must reach its actual first provider request"
    app.state.server.bridge_factory = lambda pipe, secret: waiting.bridge
    chat_id = waiting_chat(
        client,
        waiting.folder,
        standards_profile=str(waiting.profile),
        bridge={"pipe": "FICT-pipe", "secret": "FICT-secret"},
    )
    run = app.state.server.chats[UUID(chat_id)].run
    expected = before["coverage"]
    expected["checked"].append(before["closeout"].model_dump(mode="json"))
    extra = [
        CoverageItem(
            check=runner.EVIDENCE_CHECK,
            scope=CoverageScope(
                component_ids=[
                    entity for entity in request.entity_ids if run.context.component(entity)
                ]
            ),
            reason=f"{request.id} is still open: {request.what}",
            error=None,
        )
        for request in before["open_questions"]
    ]
    extra.extend(
        CoverageItem(
            check=item.id,
            scope=CoverageScope(),
            reason=f"{item.title}: not reviewed, because the review was not sent to the model",
            error=None,
        )
        for item in before["model_items"]
        if not any(row["check"] == item.id for row in expected["failed"])
    )
    expected["unresolved"].extend(row.model_dump(mode="json") for row in extra)
    assert run.session.coverage.model_dump(mode="json") == expected
    assert [row.model_dump(mode="json") for row in run.session.findings] == before["findings"]
    assert [
        row.model_dump(mode="json", exclude={"requested_at"})
        for row in run.session.evidence_requests
    ] == before["questions"]
    assert len(before["open_questions"]) == 2
    assert provider_control.built == []


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_a_non_boolean_send_setting_is_refused_before_setup(
    app: Any,
    client: TestClient,
    run_dir: Path,
    provider_control: chat.ProviderControl,
    value: Any,
) -> None:
    response = client.post("/sessions", json=chat.session_body(run_dir, send_when_checked=value))
    assert response.status_code == 400, response.text
    assert response.json()["error_class"] == "InvalidRequest"
    assert "send_when_checked" in response.json()["message"]
    assert app.state.server.chats == {}
    assert app.state.server._pending_run_dirs == set()
    assert not (run_dir / "events.jsonl").exists()
    assert provider_control.built == []


def test_an_unreadable_unticked_package_registers_nothing_and_releases_its_reservation(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    unreadable = run_root / "FICT-unreadable"
    unreadable.mkdir()
    response = client.post("/sessions", json=waiting_body(unreadable))
    assert response.status_code == 400, response.text
    assert response.json()["error_class"] == "InvalidPackage"
    assert app.state.server.chats == {}
    assert app.state.server._pending_run_dirs == set()
    app.state.server._claim_run_dir(unreadable.resolve(), None)
    assert provider_control.built == []


@pytest.mark.parametrize(
    "point,send_when_checked",
    [("setup", True), ("setup", False), ("cache", False), ("finalization", False)],
)
def test_a_failed_start_is_unregistered_and_releases_its_pending_folder(
    app: Any,
    client: TestClient,
    run_dir: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
    send_when_checked: bool,
) -> None:
    owner = app.state.server
    pending: list[ChatSession] = []
    starting = owner._start_review

    def captured(held: ChatSession, *args: Any, **kwargs: Any) -> ReviewRun:
        pending.append(held)
        if point == "setup":
            raise OSError("FICT-start-failure")
        return starting(held, *args, **kwargs)

    def refused(*args: Any, **kwargs: Any) -> None:
        raise OSError("FICT-start-failure")

    monkeypatch.setattr(owner, "_start_review", captured)
    if point == "cache":
        monkeypatch.setattr(ReviewRun, "build_send_cache", refused)
    elif point == "finalization":
        monkeypatch.setattr("swreview.atomic.write_atomic", refused)
    with TestClient(
        app,
        headers={"Authorization": f"Bearer {chat.TOKEN}", "Origin": chat.ORIGIN},
        raise_server_exceptions=False,
    ) as failed_client:
        response = failed_client.post(
            "/sessions", json=chat.session_body(run_dir, send_when_checked=send_when_checked)
        )
    assert response.status_code == 500, response.text
    assert response.text == "Internal Server Error"
    assert owner.chats == {}
    assert pending[0].state is ChatState.FAILED
    assert pending[0].run is None
    assert owner._pending_run_dirs == set()
    owner._claim_run_dir(run_dir.resolve(), pending[0].chat_id)
    # Stream debris retains today's disk rule; Retry permits a fresh claim.
    monkeypatch.undo()
    waiting_chat(client, run_dir, retry_of=str(pending[0].chat_id))
    assert provider_control.built == []


@pytest.mark.parametrize("send_when_checked", [True, False])
def test_overlapping_starts_reserve_only_the_same_folder_until_registration(
    app: Any,
    client: TestClient,
    run_dir: Path,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
    send_when_checked: bool,
) -> None:
    owner = app.state.server
    other = run_root / "FICT-independent"
    shutil.copytree(run_dir, other)
    entered, release = threading.Event(), threading.Event()
    setups: list[Path] = []
    starting = owner._start_review

    def held_setup(held: ChatSession, *args: Any, **kwargs: Any) -> ReviewRun:
        setups.append(held.run_dir)
        if held.run_dir == run_dir.resolve() and setups.count(held.run_dir) == 1:
            entered.set()
            assert release.wait(chat.TIMEOUT_S), "FICT-setup barrier was never released"
        return starting(held, *args, **kwargs)

    monkeypatch.setattr(owner, "_start_review", held_setup)
    body = chat.session_body(run_dir, send_when_checked=send_when_checked)
    with ThreadPoolExecutor(max_workers=1) as worker:
        first = worker.submit(client.post, "/sessions", json=body)
        try:
            assert entered.wait(chat.TIMEOUT_S)
            duplicate = client.post("/sessions", json=body)
            if duplicate.status_code == 201:
                # Let an incorrectly accepted duplicate finish before releasing the first
                # setup, so a red race assertion is not hidden by Windows rename sharing.
                chat.settle(client, duplicate.json()["chat_id"])
            assert duplicate.status_code == 409, duplicate.text
            assert duplicate.json()["error_class"] == "RunDirInUse"
            assert setups == [run_dir.resolve()]
            independent = client.post(
                "/sessions", json=chat.session_body(other, send_when_checked=send_when_checked)
            )
            assert independent.status_code == 201, independent.text
            assert setups == [run_dir.resolve(), other.resolve()]
            assert len(provider_control.built) == (1 if send_when_checked else 0)
        finally:
            release.set()
            accepted = first.result(timeout=chat.TIMEOUT_S)
    assert accepted.status_code == 201, accepted.text
    assert owner._pending_run_dirs == set()
    assert len(provider_control.built) == (2 if send_when_checked else 0)
    if not send_when_checked:
        still_claimed = client.post("/sessions", json=body)
        assert still_claimed.status_code == 409
        assert still_claimed.json()["error_class"] == "RunDirInUse"
        assert provider_control.built == []


@pytest.mark.parametrize("point", ["cache", "finalization", "render"])
def test_the_waiting_tail_is_not_visible_to_shutdown_until_it_is_finished(
    app: Any,
    client: TestClient,
    run_dir: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    owner = app.state.server
    entered, release = threading.Event(), threading.Event()
    if point == "cache":
        target, name = ReviewRun, "build_send_cache"
    elif point == "finalization":
        target, name = ReviewRun, "finalize"
    else:
        target, name = owner, "_render_run"
    original = getattr(target, name)

    def held_tail(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(chat.TIMEOUT_S), "FICT-waiting barrier was never released"
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, held_tail)
    with ThreadPoolExecutor(max_workers=1) as worker:
        first = worker.submit(client.post, "/sessions", json=waiting_body(run_dir))
        try:
            assert entered.wait(chat.TIMEOUT_S), "the unticked start did not enter its waiting tail"
            assert owner.chats == {}
            before = files_in(run_dir)
            owner.shutdown()
            assert files_in(run_dir) == before
            duplicate = client.post("/sessions", json=waiting_body(run_dir))
            assert duplicate.status_code == 409, duplicate.text
            assert duplicate.json()["error_class"] == "RunDirInUse"
        finally:
            release.set()
            accepted = first.result(timeout=chat.TIMEOUT_S)
    assert accepted.status_code == 201, accepted.text
    held = owner.chats[UUID(accepted.json()["chat_id"])]
    assert held.state is ChatState.AWAITING_SEND
    assert held.run.session.ended_at is not None
    assert owner._pending_run_dirs == set()
    assert provider_control.built == []


def test_follow_up_before_send_is_not_sent_and_changes_nothing(
    app: Any,
    client: TestClient,
    run_dir: Path,
    provider_control: chat.ProviderControl,
) -> None:
    chat_id = waiting_chat(client, run_dir)
    before = files_in(run_dir)
    response = client.post(f"/sessions/{chat_id}/messages", json={"text": "FICT-follow-up"})
    assert response.status_code == 409, response.text
    assert response.json()["error_class"] == "NotSent"
    assert response.json()["retryable"] is False
    assert files_in(run_dir) == before
    assert chat.state_of(client, chat_id) == "awaiting_send"
    assert not app.state.server.chats[UUID(chat_id)].stop_requested.is_set()
    assert provider_control.built == []


def test_stop_and_graceful_shutdown_do_not_rewrite_a_waiting_review(
    app: Any,
    client: TestClient,
    run_dir: Path,
    provider_control: chat.ProviderControl,
) -> None:
    chat_id = waiting_chat(client, run_dir)
    before = {
        path.relative_to(run_dir).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    for _ in range(2):
        response = client.post(f"/sessions/{chat_id}/stop")
        assert response.status_code == 202
        assert response.json()["state"] == "awaiting_send"
    owner = app.state.server
    assert not owner.chats[UUID(chat_id)].stop_requested.is_set()
    owner.shutdown()
    assert {
        path.relative_to(run_dir).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    } == before
    assert owner.chats[UUID(chat_id)].state is ChatState.AWAITING_SEND
    assert provider_control.built == []


def test_two_waiting_reviews_keep_their_own_record_and_claimed_folder(
    app: Any,
    client: TestClient,
    run_dir: Path,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    other = run_root / "FICT-second-waiting"
    shutil.copytree(run_dir, other)
    first_id = waiting_chat(client, run_dir)
    first_bytes = files_in(run_dir)
    second_id = waiting_chat(client, other)
    assert first_id != second_id
    assert files_in(run_dir) == first_bytes
    assert set(app.state.server.chats) == {UUID(first_id), UUID(second_id)}
    for chat_id, folder in ((first_id, run_dir), (second_id, other)):
        held = app.state.server.chats[UUID(chat_id)]
        saved = load_session(folder / "session.json")
        assert held.state is ChatState.AWAITING_SEND
        assert held.review_session_id == saved.session_id
        assert saved.model_status.state == "not_sent"
        duplicate = client.post("/sessions", json=waiting_body(folder))
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error_class"] == "RunDirInUse"
    assert provider_control.built == []


class ReopeningTransport:
    """Wire answers and the same lazy-open/close behavior as NamedPipeTransport."""

    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0
        self.is_open = False
        self.requests: list[dict[str, Any]] = []

    @property
    def open_pipes(self) -> int:
        return self.opened - self.closed

    def request(self, line: str) -> str:
        if not self.is_open:
            self.opened += 1
            self.is_open = True
        request = json.loads(line)
        self.requests.append(request)
        result = {
            "ping": {
                "pong": True, "protocol": PROTOCOL_VERSION, "drawing_read": "opens_closed"
            },
            "interference": {"interferences": [], "gaps": [dict(VOLUME_UNIT_GAP)]},
            "drawing.read": {
                "document_id": PLATE_ID, "drawing_document_id": "doc:0004",
                "opened": True, "closed": True, "sheets": 1, "gaps": 0,
            },
        }[request["command"]]
        return json.dumps({"id": request["id"], "status": "ok", "result": result})

    def close(self) -> None:
        if self.is_open:
            self.closed += 1
            self.is_open = False


@pytest.fixture
def pipe_app(run_root: Path, provider_control: chat.ProviderControl, models: chat.Models) -> Any:
    app = server.create_app(
        token=chat.TOKEN,
        allow_origin=chat.ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
    )
    app.state.pipe_transports = []
    app.state.pipe_clients = []

    def factory(pipe: str, secret: str | None) -> BridgeClient:
        transport = ReopeningTransport()
        client = BridgeClient(pipe, secret, transport=transport)
        app.state.pipe_transports.append(transport)
        app.state.pipe_clients.append(client)
        return client

    app.state.server.bridge_factory = factory
    return app


@pytest.fixture
def pipe_client(pipe_app: Any) -> Iterator[TestClient]:
    with TestClient(
        pipe_app,
        headers={"Authorization": f"Bearer {chat.TOKEN}", "Origin": chat.ORIGIN},
        raise_server_exceptions=False,
    ) as client:
        yield client


def pipe_review(client: TestClient, folder: Path, *, sends: bool = False) -> Any:
    fixture = build_questions_package(folder)
    return client.post(
        "/sessions",
        json=chat.session_body(
            folder,
            standards_profile=str(fixture.profile),
            bridge={"pipe": "FICT-counted-pipe", "secret": "FICT-secret"},
            send_when_checked=sends,
        ),
    )


def test_five_checks_only_reviews_release_every_opened_pipe_at_the_201(
    pipe_app: Any, pipe_client: TestClient, run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    for index in range(5):
        response = pipe_review(pipe_client, run_root / f"FICT-pipe-{index}")
        assert response.status_code == 201, response.text
        assert chat.state_of(pipe_client, response.json()["chat_id"]) == "awaiting_send"
        assert sum(transport.open_pipes for transport in pipe_app.state.pipe_transports) == 0
        transport = pipe_app.state.pipe_transports[-1]
        assert transport.opened == transport.closed == 1
        assert "interference" in [request["command"] for request in transport.requests]
    assert provider_control.built == []


def test_release_keeps_the_real_client_and_a_later_request_reopens_the_pipe(
    pipe_app: Any, pipe_client: TestClient, run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    response = pipe_review(pipe_client, run_root / "FICT-reopen")
    assert response.status_code == 201, response.text
    held = pipe_app.state.server.chats[UUID(response.json()["chat_id"])]
    client = pipe_app.state.pipe_clients[0]
    transport = pipe_app.state.pipe_transports[0]
    assert held.run.context.bridge is client
    assert held.run._bridge is client
    held.run.release_bridge()
    assert held.run.context.bridge is client
    assert held.run._bridge is client
    assert transport.open_pipes == 0
    before = len(transport.requests)
    assert client.drawing_read_mode() == "opens_closed"
    assert len(transport.requests) == before
    assert transport.open_pipes == 0
    assert client.ping()["pong"] is True
    assert transport.opened == 2
    assert transport.open_pipes == 1
    held.run.release_bridge()
    assert transport.open_pipes == 0
    assert provider_control.built == []


def test_release_without_a_bridge_does_nothing(
    app: Any, client: TestClient, run_dir: Path, provider_control: chat.ProviderControl,
) -> None:
    response = client.post("/sessions", json=chat.session_body(run_dir, send_when_checked=False))
    assert response.status_code == 201, response.text
    held = app.state.server.chats[UUID(response.json()["chat_id"])]
    assert held.run.context.bridge is None
    held.run.release_bridge()
    assert held.run.context.bridge is None
    assert provider_control.built == []


def test_a_ticked_start_keeps_its_transport_open(
    pipe_app: Any, pipe_client: TestClient, run_root: Path,
) -> None:
    response = pipe_review(pipe_client, run_root / "FICT-ticked-pipe", sends=True)
    assert response.status_code == 201, response.text
    chat.settle(pipe_client, response.json()["chat_id"])
    transport = pipe_app.state.pipe_transports[0]
    assert transport.opened == 1
    assert transport.closed == 0
    assert transport.open_pipes == 1


def test_an_unticked_start_that_cannot_finalize_closes_its_opened_pipe(
    pipe_app: Any, pipe_client: TestClient, run_root: Path,
    provider_control: chat.ProviderControl, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise OSError("FICT-atomic-finalization-refused")

    monkeypatch.setattr(atomic, "write_atomic", refused)
    response = pipe_review(pipe_client, run_root / "FICT-failed-pipe")
    assert response.status_code == 500, response.text
    assert pipe_app.state.server.chats == {}
    assert len(pipe_app.state.pipe_transports) == 1
    transport = pipe_app.state.pipe_transports[0]
    assert transport.opened == transport.closed == 1
    assert transport.open_pipes == 0
    assert provider_control.built == []


@pytest.mark.parametrize("endpoint", ["attention", "snapshot"])
def test_waiting_routes_show_the_cached_estimate_without_preparing_or_counting(
    app: Any, client: TestClient, run_dir: Path, provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    monkeypatch.setattr(tokens, "count_tokens", lambda text: 13_151)
    started = client.post("/sessions", json=chat.session_body(run_dir, send_when_checked=False))
    assert started.status_code == 201, started.text
    chat_id = started.json()["chat_id"]
    held = app.state.server.chats[UUID(chat_id)]
    expected = held.run._send_cache.estimate.input_tokens
    assert expected == 13_151

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("FICT-route-recomputed-preparation")

    monkeypatch.setattr(held.run, "opening_at_send", refused)
    monkeypatch.setattr(held.run, "build_send_cache", refused)
    monkeypatch.setattr(held.run, "first_request_estimate", refused)
    monkeypatch.setattr(runner, "_opening_message", refused)
    monkeypatch.setattr(tokens, "count_tokens", refused)
    response = client.get(f"/sessions/{chat_id}/{endpoint}")
    assert response.status_code == 200, response.text
    payload = response.json()
    summary = payload["summary"] if endpoint == "attention" else payload["ranking"]["summary"]
    assert summary["send"]["state"] == "waiting"
    assert summary["send"]["input_tokens"] == expected
    if endpoint == "snapshot":
        assert payload["chat_state"] == "awaiting_send"
    assert provider_control.built == []


@pytest.mark.parametrize("endpoint", ["attention", "snapshot"])
def test_ticked_routes_omit_the_send_block(
    client: TestClient, finished_chat: str, endpoint: str,
) -> None:
    response = client.get(f"/sessions/{finished_chat}/{endpoint}")
    assert response.status_code == 200, response.text
    payload = response.json()
    summary = payload["summary"] if endpoint == "attention" else payload["ranking"]["summary"]
    assert "send" not in summary


def test_send_input_reads_the_held_cache_and_error_without_computing(
    app: Any, client: TestClient, run_dir: Path, monkeypatch: pytest.MonkeyPatch,
    provider_control: chat.ProviderControl,
) -> None:
    started = client.post("/sessions", json=chat.session_body(run_dir, send_when_checked=False))
    assert started.status_code == 201, started.text
    held = app.state.server.chats[UUID(started.json()["chat_id"])]
    run = held.run
    estimate = run._send_cache.estimate
    failure = SendFailure(
        at=datetime.fromisoformat("2026-10-12T10:15:00+05:30"),
        error_class="FICT-preparation-failure", reason="FICT-reason",
    )
    run._send_error = failure

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("FICT-send-input-computed")

    monkeypatch.setattr(run, "build_send_cache", refused)
    monkeypatch.setattr(run, "opening_at_send", refused)
    monkeypatch.setattr(run, "first_request_estimate", refused)
    monkeypatch.setattr(tokens, "count_tokens", refused)
    values = run.send_input()
    assert values == {
        "state": "waiting", "input_tokens": estimate.input_tokens,
        "provider": run.provider.name, "send_error": failure,
    }
    assert values["send_error"] is failure
    assert provider_control.built == []
