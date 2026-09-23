"""The loopback chat backend against `contracts/chat-api.md` (T036).

Driven through Starlette's in-process client, so every assertion here is about the real
application - the same routes, the same middleware, the same worker threads - without a
socket, a port or a provider key. `test_chat_main.py` (T037a) covers the half this cannot
reach: the program the pane actually launches.

What the contract makes this module responsible for:

- **the door.** Every request carries `Authorization: Bearer <token>`; a missing or wrong
  token is 401, and a token in the *query string* is still 401, because a token in a URL
  lands in access logs, WebView2 history and crash dumps and so must never be a way in.
- **the other origin.** The pages are served from `https://swreview.invalid`, so every
  call is cross-origin: `OPTIONS` is answered without a token (a preflight carries no
  author headers), the exact configured origin is echoed - never `*`, because the loopback
  port is reachable from any browser on the workstation - and any other `Origin` is
  refused with 403 before authentication.
- **the path rule.** `run_dir` is caller-supplied, so it is canonicalized and required to
  be a descendant of the run root; UNC paths, device paths and `..` are refused.
- **one turn per chat.** Messages, evidence answers and dispositions are refused with 409
  while a turn is running rather than queued silently, and accepted on a session whose
  previous turn already ended (FR-006).
- **a session always ends.** `/stop` ends the turn at the next tool boundary and writes
  `session.ended`; so does a shutdown signal that arrives mid-turn (FR-008).
- **no key in an error.** Provider failures surface as 502 carrying the provider's error
  class, with the key masked out of the message (FR-015).

The provider is injected: `provider_control` builds a scripted adapter whose turn can be
held open at a gate, which is how a test observes a *running* turn at all.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import anyio
import pytest
from starlette.testclient import TestClient

from swreview.agent.providers import AgentEvent, AgentProvider, ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import PROFILE_CHECK
from swreview.agent.settings import MASK, ProviderSettings
from swreview.chat.server import SESSION_FILES, _sse, create_app
from swreview.chat.sessions import ChatState
from swreview.ir.loader import save_package
from swreview.report.attention import rank
from swreview.report.attention_record import (
    ATTENTION_FILE_NAME,
    read_attention_record,
    write_attention_record,
)
from swreview.report.session import Timing, load_session
from tests.support.attention import CHECK_FOLDER as ATTENTION_CHECK_FOLDER
from tests.support.contracts import contract_path, contract_validator
from tests.support.packages import build_package

ORIGIN = "https://swreview.invalid"
OTHER_ORIGIN = "https://evil.example"
TOKEN = "the-per-launch-token"
MODEL = "fake-1"
TIMEOUT_S = 10.0

EVIDENCE_ARGUMENTS: dict[str, Any] = {
    "what": "The usable thread depth of hole:1",
    "why": "fastener.engagement needs it; re-run that check once it is answered",
    "entity_ids": ["hole:1"],
}
DRAWING_FINDING_ARGUMENTS: dict[str, Any] = {
    "document_id": "doc:2",
    "sheet": "Sheet1",
    "observed": "The tapped hole is called out without a thread depth",
    "requirement": "A tapped hole callout states the usable thread depth",
    "source_refs": [{"document_id": "doc:2", "sheet": "Sheet1"}],
    "status": "suspected",
    "recommended_action": "Add the tapped depth to the hole callout",
}


def call(name: str, **arguments: Any) -> ScriptedToolCall:
    return ScriptedToolCall(name=name, arguments=arguments)


def turn(text: str, *calls: ScriptedToolCall) -> ScriptedTurn:
    return ScriptedTurn(text=text, tool_calls=calls)


def text_turns(count: int) -> list[ScriptedTurn]:
    """`count` turns that say something and call nothing: enough for follow-ups."""
    return [turn(f"turn {index + 1}") for index in range(count)]


def wait_until(predicate: Callable[[], bool], what: str, timeout: float = TIMEOUT_S) -> None:
    """Poll until `predicate` holds. A worker thread is doing the work this waits on."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


class GateProvider(FakeProvider):
    """A scripted adapter whose turn can be held open, so a test can see one running.

    `started` is set the moment the turn begins and `gate` is what it waits on before
    playing the script, so the test can act (send a second message, stop the turn, shut
    the server down) at a point where the chat really is `running`.
    """

    def __init__(self, *, gate: threading.Event, started: threading.Event, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._gate = gate
        self._started = started

    def run(self, **kwargs: Any) -> Any:
        self._started.set()
        if not self._gate.wait(TIMEOUT_S):  # pragma: no cover - a hung test, not a path
            raise AssertionError("the gate was never opened")
        return super().run(**kwargs)


@dataclass
class ProviderControl:
    """The adapter the app builds for every session, and the handle the test holds on it."""

    script: list[ScriptedTurn] = field(default_factory=lambda: text_turns(4))
    gate: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)
    built: list[ProviderSettings] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.gate.set()

    def hold(self) -> None:
        """Make the next turn wait at the gate instead of running."""
        self.gate.clear()
        self.started.clear()

    def release(self) -> None:
        self.gate.set()

    def factory(self, settings: ProviderSettings) -> AgentProvider:
        self.built.append(settings)
        return GateProvider(
            gate=self.gate, started=self.started, script=self.script, model=settings.model
        )


@pytest.fixture
def provider_control() -> ProviderControl:
    return ProviderControl()


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def run_dir(run_root: Path, tmp_package_dir: Path) -> Path:
    """A run folder inside the run root holding `package.json`, as the pane dumps it."""
    target = run_root / "20260913-120000-bracket"
    shutil.copytree(tmp_package_dir, target)
    return target


@dataclass
class Models:
    """The `/models` proxy, scripted: what it returns, or what it raises."""

    result: list[dict[str, str]] = field(default_factory=lambda: [{"id": MODEL, "label": MODEL}])
    error: Exception | None = None
    asked: list[str] = field(default_factory=list)

    def __call__(self, provider: ProviderName) -> list[dict[str, str]]:
        self.asked.append(str(provider))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def models() -> Models:
    return Models()


@pytest.fixture
def app(run_root: Path, provider_control: ProviderControl, models: Models) -> Any:
    return create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
    )


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    """The pane's client: the launch token and the virtual-host origin on every call."""
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as test_client:
        yield test_client


# --- talking to the server -----------------------------------------------------------


def session_body(run_dir: Path, **overrides: Any) -> dict[str, Any]:
    """The body the pane posts to `/sessions`, with whatever this test wants changed."""
    body: dict[str, Any] = {
        "run_dir": str(run_dir),
        "provider": "fake",
        "model": MODEL,
        "effort": "high",
        "bridge": None,
        "engineer": "a.engineer",
        "retry_of": None,
    }
    body.update(overrides)
    return body


def start_session(client: TestClient, run_dir: Path, **overrides: Any) -> dict[str, Any]:
    """`POST /sessions` with the pane's body; returns the parsed 201."""
    response = client.post("/sessions", json=session_body(run_dir, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def state_of(client: TestClient, chat_id: str) -> str:
    response = client.get(f"/sessions/{chat_id}")
    assert response.status_code == 200, response.text
    return str(response.json()["state"])


def settle(client: TestClient, chat_id: str) -> str:
    """Wait until no turn is running, and hand back the state it settled in."""
    wait_until(
        lambda: state_of(client, chat_id) != ChatState.RUNNING.value,
        f"chat {chat_id} to stop running",
    )
    return state_of(client, chat_id)


def events_of(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def types_of(run_dir: Path) -> list[str]:
    return [event["type"] for event in events_of(run_dir)]


def seqs_of(run_dir: Path) -> list[int]:
    return [int(event["seq"]) for event in events_of(run_dir)]


ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/health"),
    ("GET", "/models"),
    ("POST", "/sessions"),
    ("GET", "/sessions/{chat}"),
    ("GET", "/sessions/{chat}/events"),
    ("POST", "/sessions/{chat}/messages"),
    ("POST", "/sessions/{chat}/evidence/ER-001"),
    ("POST", "/sessions/{chat}/findings/F-001/disposition"),
    ("POST", "/sessions/{chat}/timing"),
    ("POST", "/sessions/{chat}/stop"),
    ("GET", "/sessions/{chat}/report"),
    ("GET", "/sessions/{chat}/attention"),
    ("GET", "/sessions/{chat}/snapshot"),
    ("GET", "/reviews/20260913-120000-bracket"),
)
"""Every route of the contract, with a placeholder for a chat id."""


def paths() -> list[str]:
    chat = str(uuid4())
    return [path.format(chat=chat) for _, path in ROUTES]


# --- the door ------------------------------------------------------------------------


@pytest.mark.parametrize("path", paths())
def test_every_route_refuses_a_request_with_no_token(app: Any, path: str) -> None:
    with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
        response = anonymous.request("GET", path)

    assert response.status_code == 401
    body = response.json()
    assert body["error_class"] == "Unauthorized"
    assert body["retryable"] is False


def test_a_wrong_token_is_refused(app: Any) -> None:
    with TestClient(app, headers={"Authorization": "Bearer not-the-token"}) as wrong:
        response = wrong.get("/health")

    assert response.status_code == 401


@pytest.mark.parametrize("header", ["", "the-per-launch-token", "Token the-per-launch-token"])
def test_only_a_bearer_scheme_is_accepted(app: Any, header: str) -> None:
    with TestClient(app, headers={"Authorization": header} if header else None) as odd:
        response = odd.get("/health")

    assert response.status_code == 401


def test_a_token_in_the_query_string_is_still_refused(app: Any) -> None:
    """FR: the token never appears in a URL, so a URL is never a way to present it."""
    with TestClient(app) as anonymous:
        response = anonymous.get(f"/health?token={TOKEN}")

    assert response.status_code == 401
    assert TOKEN not in response.text


def test_an_error_body_never_carries_the_token(app: Any) -> None:
    with TestClient(app) as anonymous:
        response = anonymous.get("/health")

    assert TOKEN not in response.text


# --- the other origin ----------------------------------------------------------------


@pytest.mark.parametrize("path", paths())
def test_a_preflight_is_answered_on_every_route_without_a_token(app: Any, path: str) -> None:
    with TestClient(app) as anonymous:
        response = anonymous.options(
            path,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type",
            },
        )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["vary"] == "Origin"
    assert response.headers["access-control-allow-private-network"] == "true"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "content-type" in allowed
    assert "last-event-id" in allowed
    methods = response.headers["access-control-allow-methods"].upper()
    assert {"GET", "POST", "OPTIONS"} <= set(part.strip() for part in methods.split(","))
    assert response.headers["access-control-max-age"] == "600"


def test_the_allowed_origin_is_the_exact_one_and_never_a_wildcard(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["vary"] == "Origin"


@pytest.mark.parametrize("path", paths())
def test_any_other_origin_is_refused_before_authentication(app: Any, path: str) -> None:
    with TestClient(app, headers={"Origin": OTHER_ORIGIN}) as stranger:
        response = stranger.request("GET", path)
        preflight = stranger.options(path, headers={"Origin": OTHER_ORIGIN})

    assert response.status_code == 403
    assert response.json()["error_class"] == "ForbiddenOrigin"
    assert "access-control-allow-origin" not in response.headers
    assert preflight.status_code == 403


def test_a_request_with_no_origin_at_all_is_served(app: Any) -> None:
    """`curl` and the health poll send none; only a *wrong* origin is a refusal."""
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as bare:
        response = bare.get("/health")

    assert response.status_code == 200


# --- health and models ---------------------------------------------------------------


def test_health_names_the_providers_this_build_runs(client: TestClient) -> None:
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["version"]
    assert body["providers"][:2] == ["openai", "gemini"]
    assert "fake" not in body["providers"]


def test_a_development_build_also_lists_the_scripted_provider(
    run_root: Path, provider_control: ProviderControl, models: Models
) -> None:
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
        development=True,
    )
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as dev:
        assert dev.get("/health").json()["providers"] == ["openai", "gemini", "fake"]


def test_models_proxies_the_provider(client: TestClient, models: Models) -> None:
    response = client.get("/models", params={"provider": "fake"})

    assert response.status_code == 200
    assert response.json() == {"models": [{"id": MODEL, "label": MODEL}]}
    assert models.asked == ["fake"]


def test_models_reports_a_provider_failure_as_502_with_its_error_class(
    client: TestClient, models: Models
) -> None:
    class AuthenticationError(RuntimeError):
        """Stands in for the SDK class an unusable key raises."""

    models.error = AuthenticationError("401 Unauthorized")

    response = client.get("/models", params={"provider": "openai"})

    assert response.status_code == 502
    body = response.json()
    assert body["error_class"] == "AuthenticationError"
    assert "401 Unauthorized" in body["message"]
    assert body["retryable"] is True


def test_a_provider_error_that_echoes_the_key_is_redacted(
    run_root: Path,
    provider_control: ProviderControl,
    models: Models,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-015: the key reaches the backend in its environment and must not come back out."""
    key = "sk-live-should-never-be-echoed"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    models.error = RuntimeError(f"401 Unauthorized: api_key={key} was rejected")
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
    )

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as keyed:
        response = keyed.get("/models", params={"provider": "openai"})

    assert response.status_code == 502
    assert key not in response.text
    assert MASK in response.json()["message"]


def test_an_unknown_provider_is_a_client_error(client: TestClient) -> None:
    """Every name that is not one of the three, including the retired vendor's."""
    response = client.get("/models", params={"provider": "acme-llm"})

    assert response.status_code == 400
    assert response.json()["error_class"] == "UnknownProvider"


# --- starting a session --------------------------------------------------------------


def test_posting_a_session_starts_the_review_and_returns_both_ids(
    client: TestClient, run_dir: Path
) -> None:
    body = start_session(client, run_dir)

    assert body["chat_id"]
    assert body["review_session_id"]
    settle(client, body["chat_id"])
    session = load_session(run_dir / "session.json")
    assert str(session.session_id) == body["review_session_id"]
    assert types_of(run_dir)[0] == "session.started"


def test_configured_standards_profile_reaches_review_setup_and_blank_is_absent(
    run_root: Path,
    provider_control: ProviderControl,
    models: Models,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The host's configured path is forwarded, while a blank setting means no profile."""
    import swreview.chat.server as chat_server

    original = chat_server.start_review
    received: list[str | None] = []

    def recording_start_review(*args: Any, **kwargs: Any) -> Any:
        received.append(kwargs.get("standards_profile"))
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_server, "start_review", recording_start_review)
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
    )
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    with TestClient(app, headers=headers) as test_client:
        profile = run_root / "configured-standards.yaml"
        started = start_session(test_client, run_dir, standards_profile=f"  {profile}  ")
        settle(test_client, started["chat_id"])

        blank_run = run_root / "20260920-000000-second"
        blank_run.mkdir()
        save_package(build_package(), blank_run)
        blank = start_session(test_client, blank_run, standards_profile="  ")
        settle(test_client, blank["chat_id"])

    assert received == [str(profile), None]


def test_the_session_view_carries_no_token_and_no_bridge(
    client: TestClient, run_dir: Path
) -> None:
    started = start_session(
        client, run_dir, bridge={"pipe": "swreview-1", "secret": "the-bridge-secret"}
    )

    response = client.get(f"/sessions/{started['chat_id']}")

    assert response.status_code == 200
    assert TOKEN not in response.text
    assert "the-bridge-secret" not in response.text
    assert "token" not in response.json()
    assert "bridge" not in response.json()


def test_the_bridge_pipe_and_secret_reach_the_run(
    run_root: Path, provider_control: ProviderControl, models: Models, run_dir: Path
) -> None:
    """`POST /sessions` carries `{pipe, secret}`; both reach the bridge client the review
    runs with, and neither is read from anywhere but the request (T049)."""
    built: list[tuple[str, str | None]] = []

    class RecordingBridge:
        def close(self) -> None:
            return None

    def factory(pipe_name: str, secret: str | None) -> RecordingBridge:
        built.append((pipe_name, secret))
        return RecordingBridge()

    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
        bridge_factory=factory,
    )
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as bridged:
        started = start_session(
            bridged, run_dir, bridge={"pipe": "swreview-abc", "secret": "the-bridge-secret"}
        )
        settle(bridged, started["chat_id"])

    assert built == [("swreview-abc", "the-bridge-secret")]


def test_a_session_without_a_bridge_builds_no_bridge_client(
    run_root: Path, provider_control: ProviderControl, models: Models, run_dir: Path
) -> None:
    built: list[tuple[str, str | None]] = []
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
        bridge_factory=lambda pipe_name, secret: built.append((pipe_name, secret)),
    )
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as plain:
        started = start_session(plain, run_dir)
        settle(plain, started["chat_id"])

    assert built == []


def test_an_unknown_chat_is_a_404(client: TestClient) -> None:
    response = client.get(f"/sessions/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_class"] == "UnknownChat"


def test_a_retry_records_the_session_it_replaces(client: TestClient, run_dir: Path) -> None:
    """The pane's Retry action links the new session to the failed one (FR-028)."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])

    second = start_session(client, run_dir, retry_of=first["chat_id"])
    settle(client, second["chat_id"])

    assert client.get(f"/sessions/{second['chat_id']}").json()["retry_of"] == first["chat_id"]
    session = load_session(run_dir / "session.json")
    assert str(session.retry_of) == first["review_session_id"]


def test_a_second_chat_on_a_run_dir_a_live_chat_holds_is_refused(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """One chat per run folder: two would interleave one `events.jsonl` and one `seq`."""
    provider_control.hold()
    first = start_session(client, run_dir)
    assert provider_control.started.wait(TIMEOUT_S)

    response = client.post("/sessions", json=session_body(run_dir))

    assert response.status_code == 409
    assert response.json()["error_class"] == "RunDirInUse"
    assert first["chat_id"] in response.json()["message"]
    provider_control.release()
    settle(client, first["chat_id"])


def test_a_run_dir_that_already_holds_a_session_is_refused_without_a_retry(
    client: TestClient, run_dir: Path
) -> None:
    """A second session in the folder would restart `seq` mid-file and lose the first."""
    settle(client, start_session(client, run_dir)["chat_id"])

    response = client.post("/sessions", json=session_body(run_dir))

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidRunDir"


def test_a_retry_into_the_same_run_dir_starts_a_clean_stream_and_keeps_the_old_one(
    app: Any, client: TestClient, run_dir: Path
) -> None:
    """`ChatSession 1 events.jsonl` (data-model section 7), across a retry as well.

    The retry writes the folder its predecessor wrote, so the pair the predecessor wrote
    is moved aside: the retry's stream starts at `seq` 1 with its own `session.started`,
    and the session `retry_of` points at is still on disk to be read.
    """
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    before = events_of(run_dir)

    second = start_session(client, run_dir, retry_of=first["chat_id"])
    settle(client, second["chat_id"])

    events = events_of(run_dir)
    assert seqs_of(run_dir) == list(range(1, len(events) + 1))
    assert events[0]["type"] == "session.started"
    assert events[0]["body"]["session_id"] == second["review_session_id"]
    rotated = run_dir / "events.1.jsonl"
    assert [json.loads(line) for line in rotated.read_text(encoding="utf-8").splitlines()] == before
    assert str(load_session(run_dir / "session.1.json").session_id) == first["review_session_id"]
    assert str(load_session(run_dir / "session.json").session_id) == second["review_session_id"]
    superseded = app.state.server.chats[UUID(first["chat_id"])]
    assert superseded.events_path == rotated


def test_a_retry_moves_the_attention_record_to_the_same_index_as_the_session(
    client: TestClient, run_dir: Path
) -> None:
    """`attention.json` is the ranking of the session beside it, so it travels with it.

    Left where it was, the record would name `session.1.json` while sitting beside the
    retry's `session.json`, which is exactly the staleness `read_attention_record` refuses
    - and the predecessor's ranking, which is what an engineer comparing two attempts
    wants, would have been written over (FR-021).
    """
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    assert (run_dir / ATTENTION_FILE_NAME).is_file(), "the run wrote its own record"
    before = (run_dir / ATTENTION_FILE_NAME).read_bytes()

    second = start_session(client, run_dir, retry_of=first["chat_id"])
    settle(client, second["chat_id"])

    assert (run_dir / "attention.1.json").read_bytes() == before
    assert str(read_attention_record(run_dir).session_id) == second["review_session_id"]


def test_a_retry_cannot_claim_a_folder_until_the_previous_render_finishes(
    app: Any,
    client: TestClient,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A finished turn keeps its run claimed while the final report render is writing.

    The worker publishes ``ended`` only after that render. Holding the render at a known
    point makes the old race deterministic: Retry must see the live predecessor and wait
    for the caller to release it, rather than rotate files underneath its writer.
    """
    rendering = threading.Event()
    release = threading.Event()
    original = app.state.server._render_report

    def held_render(chat: Any) -> None:
        if not rendering.is_set():
            rendering.set()
            assert release.wait(TIMEOUT_S), "the test did not release the final render"
        original(chat)

    monkeypatch.setattr(app.state.server, "_render_report", held_render)
    first = start_session(client, run_dir)
    assert rendering.wait(TIMEOUT_S), "the first session did not reach its final render"

    retry = client.post(
        "/sessions",
        json=session_body(run_dir, retry_of=first["chat_id"]),
    )
    assert retry.status_code == 409
    assert retry.json()["error_class"] == "RunDirInUse"

    release.set()
    assert settle(client, first["chat_id"]) == ChatState.ENDED.value

    second = start_session(client, run_dir, retry_of=first["chat_id"])
    assert settle(client, second["chat_id"]) == ChatState.ENDED.value
    assert (run_dir / "attention.1.json").is_file()
    assert str(read_attention_record(run_dir).session_id) == second["review_session_id"]


@pytest.fixture
def check_run_dir(run_root: Path) -> Path:
    """An RMS check folder inside the run root, holding its own `attention.json`.

    The committed fixture rather than a live `run_rms_check`: this module's package has no
    feature rows to grade, and what is under test is the rotation, not the rules.
    """
    target = run_root / "20260918-220310-check"
    shutil.copytree(ATTENTION_CHECK_FOLDER, target)
    session = load_session(target / "session.json")
    write_attention_record(target, rank(session), session.session_id)
    return target


def test_a_review_claiming_a_check_folder_rotates_its_record_beside_its_session(
    client: TestClient, check_run_dir: Path
) -> None:
    """User Story 6 scenario 11, with the fourth file: the check's record survives as
    `attention.1.json` beside `session.1.json` rather than being written over."""
    check_session_id = load_session(check_run_dir / "session.json").session_id
    check_record = (check_run_dir / ATTENTION_FILE_NAME).read_bytes()

    settle(client, start_session(client, check_run_dir)["chat_id"])

    assert (check_run_dir / "attention.1.json").read_bytes() == check_record
    assert load_session(check_run_dir / "session.1.json").session_id == check_session_id
    assert read_attention_record(check_run_dir).session_id != check_session_id


def test_a_folder_holding_only_a_record_is_not_a_folder_that_already_holds_a_review(
    client: TestClient, check_run_dir: Path
) -> None:
    """`SESSION_FILES` is also the claim rule's truthiness test, and the record is
    deliberately not in it: a folder with a record and no session is claimable."""
    (check_run_dir / "session.json").unlink()
    (check_run_dir / "check.json").unlink()
    assert [path.name for path in sorted(check_run_dir.iterdir())] == [
        ATTENTION_FILE_NAME,
        "package.json",
    ]

    response = client.post("/sessions", json=session_body(check_run_dir))

    assert response.status_code == 201, response.text
    assert not (check_run_dir / "attention.1.json").exists(), (
        "nothing was rotated: the folder held no session for the record to travel with"
    )
    settle(client, response.json()["chat_id"])


def test_the_record_is_not_in_session_files(run_dir: Path) -> None:
    """Pinned by name, because adding it there would look like tidiness and would turn
    every check folder into "a folder that already holds a review"."""
    assert ATTENTION_FILE_NAME not in SESSION_FILES


def test_the_provider_settings_come_from_the_request_and_the_environment(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    start_session(client, run_dir, model="fake-2", effort="low")

    settings = provider_control.built[-1]
    assert settings.provider is ProviderName.FAKE
    assert settings.model == "fake-2"
    assert settings.effort == "low"
    assert settings.key_source == "none"


@pytest.mark.parametrize(
    "bad",
    [
        "relative/run",
        "\\\\server\\share\\run",
        "\\\\.\\pipe\\swreview",
        "//server/share/run",
    ],
)
def test_a_run_dir_that_breaks_the_path_rule_is_refused(
    client: TestClient, run_root: Path, bad: str
) -> None:
    response = client.post(
        "/sessions",
        json={
            "run_dir": bad if bad.startswith(("\\", "/")) else str(run_root.parent / bad),
            "provider": "fake",
            "model": MODEL,
            "effort": "high",
            "bridge": None,
            "engineer": "a.engineer",
            "retry_of": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidRunDir"


def test_a_run_dir_outside_the_run_root_is_refused(
    client: TestClient, tmp_path: Path, tmp_package_dir: Path
) -> None:
    outside = tmp_path / "elsewhere"
    shutil.copytree(tmp_package_dir, outside)

    response = client.post(
        "/sessions",
        json={
            "run_dir": str(outside),
            "provider": "fake",
            "model": MODEL,
            "effort": "high",
            "bridge": None,
            "engineer": "a.engineer",
            "retry_of": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidRunDir"


def test_a_run_dir_with_a_parent_segment_is_refused_even_when_it_lands_inside(
    client: TestClient, run_root: Path, run_dir: Path
) -> None:
    """It would resolve inside the root; `..` is refused on sight rather than normalized."""
    sneaky = run_root / "somewhere" / ".." / run_dir.name

    response = client.post(
        "/sessions",
        json={
            "run_dir": str(sneaky),
            "provider": "fake",
            "model": MODEL,
            "effort": "high",
            "bridge": None,
            "engineer": "a.engineer",
            "retry_of": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidRunDir"


def test_a_run_dir_without_a_package_is_refused(client: TestClient, run_root: Path) -> None:
    empty = run_root / "20260913-130000-empty"
    empty.mkdir()

    response = client.post(
        "/sessions",
        json={
            "run_dir": str(empty),
            "provider": "fake",
            "model": MODEL,
            "effort": "high",
            "bridge": None,
            "engineer": "a.engineer",
            "retry_of": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidPackage"


def test_a_package_that_does_not_parse_is_refused(client: TestClient, run_root: Path) -> None:
    broken = run_root / "20260913-140000-broken"
    broken.mkdir()
    (broken / "package.json").write_text('{"schema_version": "9.9.9"}', encoding="utf-8")

    response = client.post(
        "/sessions",
        json={
            "run_dir": str(broken),
            "provider": "fake",
            "model": MODEL,
            "effort": "high",
            "bridge": None,
            "engineer": "a.engineer",
            "retry_of": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidPackage"


def model_check_run_dir(run_root: Path, name: str = "20260913-150000-bracket-check") -> Path:
    """A run folder holding the package the `ModelCheck` dump profile writes (IR 1.2.0)."""
    package = build_package()
    directory = run_root / name
    save_package(
        package.model_copy(
            update={"extractor": package.extractor.model_copy(update={"profile": "model_check"})}
        ),
        directory,
    )
    return directory


def test_a_model_check_package_is_reviewed_with_its_missing_phases_as_coverage(
    client: TestClient, run_root: Path
) -> None:
    """A check package handed to a review says it is partial; it does not read as clean.

    The Model check tab dumps documents, mates, features and equations and skips the
    hole, fastener, face and body or mesh phases (FR-022), so `holes`, `fasteners`,
    `faces` and `bodies` come back empty. A review of that package would otherwise
    report "no holes" and "no fasteners" as facts about the design, which is the one
    reading of a partial extract that is worse than no reading at all - so the run
    records what was never extracted before the first turn.
    """
    partial = model_check_run_dir(run_root)

    started = start_session(client, partial)
    settle(client, started["chat_id"])

    session = load_session(partial / "session.json")
    items = [item for item in session.coverage.skipped if item.check == PROFILE_CHECK]
    assert len(items) == 1, f"one partial-evidence coverage item expected, got {items}"
    item = items[0]

    assert "model_check" in item.reason
    for phase in ("hole", "fastener", "face", "body or mesh"):
        assert phase in item.reason, f"the coverage item does not name {phase}: {item.reason}"
    assert item.error is None


def test_a_full_package_records_nothing_about_the_dump_profile(
    client: TestClient, run_dir: Path
) -> None:
    """The unchanged half of FR-022: a full dump is not annotated as a partial one."""
    started = start_session(client, run_dir)
    settle(client, started["chat_id"])

    session = load_session(run_dir / "session.json")
    coverage = session.coverage
    written = [
        item
        for bucket in (
            coverage.checked,
            coverage.skipped,
            coverage.unresolved,
            coverage.failed,
            coverage.out_of_scope,
        )
        for item in bucket
        if item.check == PROFILE_CHECK
    ]

    assert written == []


# --- the event stream ----------------------------------------------------------------


BLOCK_SEPARATOR = "\r\n\r\n"
"""What separates two server-sent events; sse-starlette writes CRLF by default."""


def read_stream(
    app: Any,
    path: str,
    *,
    count: int,
    last_event_id: str | None = None,
    on_open: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    """`count` server-sent events off `path`, by driving the ASGI application directly.

    Every in-process HTTP client here - Starlette's `TestClient` and `httpx`'s
    `ASGITransport` alike - buffers the whole response body before handing back a
    response, and an event stream never finishes, so neither of them can read one. Talking
    ASGI is the only in-process way to watch a stream arrive, and it is also the honest
    one: `http.disconnect` is exactly what the pane's `fetch` reader sends when it lets go,
    and the response ends because the endpoint noticed, not because a test told it to.

    `on_open` runs once the response has started, which is how a test arranges for
    something to happen *while* it is listening.
    """
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"authorization", f"Bearer {TOKEN}".encode()),
            (b"origin", ORIGIN.encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    if last_event_id is not None:
        scope["headers"].append((b"last-event-id", last_event_id.encode()))

    async def scenario() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        start: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        buffer = ""
        done = anyio.Event()

        async def receive() -> dict[str, Any]:
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal buffer
            if message["type"] == "http.response.start":
                start.update(message)
                if on_open is not None:
                    on_open()
                return
            buffer += message.get("body", b"").decode("utf-8")
            while BLOCK_SEPARATOR in buffer:
                block, _, buffer = buffer.partition(BLOCK_SEPARATOR)
                event = parse_sse(block)
                if event:
                    events.append(event)
            if len(events) >= count:
                done.set()

        with anyio.move_on_after(TIMEOUT_S):
            await app(scope, receive, send)
        return start, events

    started, events = anyio.run(scenario)
    assert len(events) >= count, (
        f"only {len(events)} of {count} events arrived on {path} within {TIMEOUT_S}s"
    )
    headers = {key.decode(): value.decode() for key, value in started.get("headers", [])}
    assert started["status"] == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["access-control-allow-origin"] == ORIGIN
    # One drain hands over everything that arrived together, so the stream can overshoot
    # the count the caller asked for; it is given exactly the count it asked for.
    return events[:count]


def parse_sse(block: str) -> dict[str, Any]:
    """One `id:`/`event:`/`data:` block as a dict; a keep-alive comment is not an event."""
    event: dict[str, Any] = {}
    for line in block.splitlines():
        if not line or line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.lstrip()
        if name == "data":
            event["data"] = json.loads(value)
        elif name in ("id", "event"):
            event[name] = value
    return event


def test_the_stream_replays_the_file_and_then_the_live_events(
    client: TestClient, app: Any, run_dir: Path, provider_control: ProviderControl
) -> None:
    """The pane reconnects into a running turn: what it missed, then what happens next."""
    provider_control.script = [turn("streamed answer")]
    provider_control.hold()
    chat_id = start_session(client, run_dir)["chat_id"]
    wait_until(provider_control.started.is_set, "the turn to reach the gate")

    events = read_stream(
        app,
        f"/sessions/{chat_id}/events",
        count=5,
        on_open=provider_control.release,
    )

    assert events[0]["event"] == "session.started"
    assert [event["id"] for event in events] == [str(index) for index in range(1, 6)]
    assert "text.delta" in [event["event"] for event in events]
    assert events[0]["data"]["provider"] == "fake"
    assert events[0]["data"]["model"] == MODEL

    # The body alone travels in `data`. The page builds its `{seq, type, body}` envelope from
    # the three SSE fields (app.js `onFrame`), so a `data` that carried the envelope would be
    # read as a body with a `type` key and rendered as an event about nothing - the shape the
    # add-in tests fabricated until 2026-09-18 (docs/pane-findings-2026-09-18.md).
    for event in events:
        assert "type" not in event["data"]
        assert "seq" not in event["data"]


def test_the_contract_sample_is_what_the_producer_writes_byte_for_byte() -> None:
    """The recorded closing pair, `turn.ended` then `session.ended`, exactly as `_sse` writes it.

    The add-in's page tests feed this same file to the real page (SseFrames.cs), so the
    producer here and the consumer there are pinned to one artifact, and a change to either
    side's idea of a frame goes red in one suite or the other. Until 2026-09-18 nothing pinned
    them to each other: the C# tests fabricated an envelope-in-`data` frame this server never
    writes, and every real frame fell through the page's parser
    (docs/pane-findings-2026-09-18.md).
    """
    at = datetime(2026, 9, 16, 10, 20, tzinfo=UTC)
    timing = Timing(
        baseline_minutes=None,
        assisted_supervision_minutes=0.0,
        assisted_verification_minutes=0.0,
        false_alarm_handling_minutes=0.0,
        unattended_runtime_minutes=1.6,
    )
    events = [
        AgentEvent(seq=19, at=at, type="turn.ended", body={"reason": "end"}),
        AgentEvent(
            seq=20,
            at=at,
            type="session.ended",
            body={"ended_at": at.isoformat(), "timing": timing.model_dump(mode="json")},
        ),
    ]
    for event in events:
        contract_validator("chat-events.schema.json").validate(event.model_dump(mode="json"))

    sample = contract_path("event-stream.sample.sse").read_bytes()

    assert b"".join(_sse(event).encode() for event in events) == sample
    # And in words a reader can check against chat-api.md: `id` is the seq, `event` is the
    # type, and `data` is the body and nothing else.
    frames = [block for block in sample.decode("utf-8").split("\r\n\r\n") if block]
    assert [parse_sse(frame) for frame in frames] == [
        {"id": "19", "event": "turn.ended", "data": {"reason": "end"}},
        {"id": "20", "event": "session.ended", "data": events[1].body},
    ]


def test_the_stream_resumes_after_the_last_event_id_it_was_given(
    client: TestClient, app: Any, run_dir: Path
) -> None:
    """The pane reconnects with what it already has; it must not be told it twice."""
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    written = [event for event in events_of(run_dir) if event["seq"] > 2]

    events = read_stream(
        app, f"/sessions/{chat_id}/events", count=len(written), last_event_id="2"
    )

    assert [int(event["id"]) for event in events] == [item["seq"] for item in written]
    assert [event["event"] for event in events] == [item["type"] for item in written]
    assert events[-1]["event"] == "session.ended"
    assert events[-1]["data"]["ended_at"]


def test_the_stream_of_an_unknown_chat_is_a_404(client: TestClient) -> None:
    response = client.get(f"/sessions/{uuid4()}/events")

    assert response.status_code == 404


# --- follow-ups ----------------------------------------------------------------------


def test_a_message_is_refused_while_a_turn_is_running_and_accepted_after_it(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """The contract refuses rather than queueing silently, so the pane can say so."""
    provider_control.hold()
    chat_id = start_session(client, run_dir)["chat_id"]
    wait_until(provider_control.started.is_set, "the turn to reach the gate")

    refused = client.post(f"/sessions/{chat_id}/messages", json={"text": "and also"})

    assert refused.status_code == 409
    assert refused.json()["error_class"] == "TurnRunning"

    provider_control.release()
    assert settle(client, chat_id) == ChatState.ENDED.value
    accepted = client.post(f"/sessions/{chat_id}/messages", json={"text": "and also"})

    assert accepted.status_code == 202
    assert settle(client, chat_id) == ChatState.ENDED.value


def test_a_follow_up_on_an_ended_session_runs_another_turn(
    client: TestClient, run_dir: Path
) -> None:
    """FR-006: `ended -> running`; the second turn's events continue the same file."""
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    first = len(events_of(run_dir))

    response = client.post(f"/sessions/{chat_id}/messages", json={"text": "anything else?"})
    settle(client, chat_id)

    assert response.status_code == 202
    events = events_of(run_dir)
    assert len(events) > first
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert types_of(run_dir).count("session.ended") == 2


def test_a_message_to_an_unknown_chat_is_a_404(client: TestClient) -> None:
    response = client.post(f"/sessions/{uuid4()}/messages", json={"text": "hello"})

    assert response.status_code == 404


def test_a_message_without_text_is_a_400(client: TestClient, run_dir: Path) -> None:
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)

    response = client.post(f"/sessions/{chat_id}/messages", json={})

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidRequest"


# --- evidence answers ----------------------------------------------------------------


@pytest.fixture
def waiting_chat(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> str:
    """A session that opened an evidence request and is waiting for the engineer."""
    provider_control.script = [
        turn("I need the thread depth.", call("request_evidence", **EVIDENCE_ARGUMENTS)),
        turn("Thanks; the joint is fine."),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    assert settle(client, chat_id) == ChatState.WAITING_ENGINEER.value
    return chat_id


def test_an_answer_resumes_the_review(
    client: TestClient, run_dir: Path, waiting_chat: str
) -> None:
    response = client.post(
        f"/sessions/{waiting_chat}/evidence/ER-001", json={"answer": "Tapped 12 mm deep."}
    )

    assert response.status_code == 202
    assert settle(client, waiting_chat) == ChatState.ENDED.value
    assert "evidence.answered" in types_of(run_dir)
    session = load_session(run_dir / "session.json")
    assert session.evidence_requests[0].status == "answered"
    assert session.evidence_requests[0].answer == "Tapped 12 mm deep."


def test_an_unknown_evidence_request_is_a_404(client: TestClient, waiting_chat: str) -> None:
    response = client.post(
        f"/sessions/{waiting_chat}/evidence/ER-404", json={"answer": "anything"}
    )

    assert response.status_code == 404
    assert response.json()["error_class"] == "UnknownEvidenceRequest"


def test_answering_twice_is_refused(client: TestClient, waiting_chat: str) -> None:
    client.post(f"/sessions/{waiting_chat}/evidence/ER-001", json={"answer": "12 mm"})
    settle(client, waiting_chat)

    response = client.post(
        f"/sessions/{waiting_chat}/evidence/ER-001", json={"answer": "12 mm again"}
    )

    assert response.status_code == 409
    assert response.json()["error_class"] == "AlreadyAnswered"


# The two refusals name the request they refused (feature 009 T041's single-route half,
# data-model section 9), so the page can say which question without parsing English. The
# batch route's half waits for feature 008 T084-T085.


def test_an_unknown_evidence_request_names_its_request_id(
    client: TestClient, waiting_chat: str
) -> None:
    body = client.post(
        f"/sessions/{waiting_chat}/evidence/ER-404", json={"answer": "anything"}
    ).json()

    assert body["request_id"] == "ER-404"
    assert set(body) == {"error_class", "message", "retryable", "request_id"}


def test_answering_twice_names_the_request_id(client: TestClient, waiting_chat: str) -> None:
    client.post(f"/sessions/{waiting_chat}/evidence/ER-001", json={"answer": "12 mm"})
    settle(client, waiting_chat)

    body = client.post(
        f"/sessions/{waiting_chat}/evidence/ER-001", json={"answer": "12 mm again"}
    ).json()

    assert (body["error_class"], body["request_id"]) == ("AlreadyAnswered", "ER-001")
    assert set(body) == {"error_class", "message", "retryable", "request_id"}


def test_every_other_refusal_carries_no_request_id(client: TestClient, waiting_chat: str) -> None:
    empty_answer = client.post(f"/sessions/{waiting_chat}/evidence/ER-001", json={}).json()
    unknown_chat = client.post(
        f"/sessions/{uuid4()}/evidence/ER-001", json={"answer": "12 mm"}
    ).json()

    assert (empty_answer["error_class"], unknown_chat["error_class"]) == (
        "InvalidRequest",
        "UnknownChat",
    )
    assert "request_id" not in empty_answer
    assert "request_id" not in unknown_chat


def test_a_chat_error_body_adds_the_request_id_only_when_set() -> None:
    from swreview.chat.server import AlreadyAnswered, TurnRunning, UnknownEvidenceRequest

    assert UnknownEvidenceRequest("no ER-9", request_id="ER-009").body()["request_id"] == "ER-009"
    assert AlreadyAnswered("done", request_id="ER-001").body()["request_id"] == "ER-001"
    assert "request_id" not in TurnRunning("busy").body()


def test_an_answer_is_refused_while_a_turn_is_running(
    client: TestClient, run_dir: Path, provider_control: ProviderControl, waiting_chat: str
) -> None:
    provider_control.hold()
    client.post(f"/sessions/{waiting_chat}/messages", json={"text": "keep going"})
    wait_until(provider_control.started.is_set, "the follow-up turn to reach the gate")

    response = client.post(
        f"/sessions/{waiting_chat}/evidence/ER-001", json={"answer": "12 mm"}
    )

    assert response.status_code == 409
    assert response.json()["error_class"] == "TurnRunning"
    provider_control.release()


# --- dispositions --------------------------------------------------------------------


@pytest.fixture
def chat_with_a_finding(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> str:
    provider_control.script = [
        turn("One finding.", call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS)),
        *text_turns(2),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    return chat_id


def test_a_disposition_is_recorded_and_the_report_re_rendered(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    finding_id = load_session(run_dir / "session.json").findings[0].id

    response = client.post(
        f"/sessions/{chat_with_a_finding}/findings/{finding_id}/disposition",
        json={"decision": "accepted", "note": "known and accepted", "by": "a.engineer"},
    )

    assert response.status_code == 200
    finding = response.json()
    assert finding["id"] == finding_id
    assert finding["disposition"]["decision"] == "accepted"
    assert load_session(run_dir / "session.json").findings[0].disposition is not None
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "accepted" in report
    assert "disposition" in types_of(run_dir)


def test_a_disposition_survives_the_next_turn(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """The live session is written again at the end of every turn; the decision must be in it."""
    finding_id = load_session(run_dir / "session.json").findings[0].id
    client.post(
        f"/sessions/{chat_with_a_finding}/findings/{finding_id}/disposition",
        json={"decision": "accepted", "note": "", "by": "a.engineer"},
    )

    client.post(f"/sessions/{chat_with_a_finding}/messages", json={"text": "carry on"})
    settle(client, chat_with_a_finding)

    assert load_session(run_dir / "session.json").findings[0].disposition is not None


def test_an_illegal_disposition_transition_is_refused(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    finding_id = load_session(run_dir / "session.json").findings[0].id
    url = f"/sessions/{chat_with_a_finding}/findings/{finding_id}/disposition"
    client.post(url, json={"decision": "accepted", "note": "", "by": "a.engineer"})

    response = client.post(url, json={"decision": "rejected", "note": "", "by": "a.engineer"})

    assert response.status_code == 409
    assert response.json()["error_class"] == "IllegalTransition"


def test_an_unknown_finding_is_a_404(client: TestClient, chat_with_a_finding: str) -> None:
    response = client.post(
        f"/sessions/{chat_with_a_finding}/findings/F-404/disposition",
        json={"decision": "accepted", "note": "", "by": "a.engineer"},
    )

    assert response.status_code == 404
    assert response.json()["error_class"] == "UnknownFinding"


def test_a_decision_the_state_machine_does_not_know_is_a_400(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    finding_id = load_session(run_dir / "session.json").findings[0].id

    response = client.post(
        f"/sessions/{chat_with_a_finding}/findings/{finding_id}/disposition",
        json={"decision": "maybe", "note": "", "by": "a.engineer"},
    )

    assert response.status_code == 400
    assert response.json()["error_class"] == "InvalidDecision"


def test_the_report_is_served_as_markdown(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    response = client.get(f"/sessions/{chat_with_a_finding}/report")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == (run_dir / "report.md").read_text(encoding="utf-8")


# --- stopping ------------------------------------------------------------------------


def test_stop_ends_the_turn_at_the_next_tool_boundary_and_the_session_with_it(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """FR-030: a running turn is interruptible from the pane, and it still ends properly."""
    provider_control.script = [
        turn("never finished", call("get_package_summary"), call("list_gaps")),
        *text_turns(1),
    ]
    provider_control.hold()
    chat_id = start_session(client, run_dir)["chat_id"]
    wait_until(provider_control.started.is_set, "the turn to reach the gate")

    response = client.post(f"/sessions/{chat_id}/stop")
    provider_control.release()

    assert response.status_code == 202
    assert settle(client, chat_id) == ChatState.ENDED.value
    types = types_of(run_dir)
    assert types[-2:] == ["turn.ended", "session.ended"]
    ended = [event for event in events_of(run_dir) if event["type"] == "turn.ended"]
    assert ended[-1]["body"]["reason"] == "stopped"
    session = load_session(run_dir / "session.json")
    assert session.ended_at is not None


def test_a_stopped_session_still_takes_a_follow_up(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    provider_control.script = [turn("never finished", call("get_package_summary")), *text_turns(2)]
    provider_control.hold()
    chat_id = start_session(client, run_dir)["chat_id"]
    wait_until(provider_control.started.is_set, "the turn to reach the gate")
    client.post(f"/sessions/{chat_id}/stop")
    provider_control.release()
    settle(client, chat_id)

    response = client.post(f"/sessions/{chat_id}/messages", json={"text": "try again"})

    assert response.status_code == 202
    assert settle(client, chat_id) == ChatState.ENDED.value


def test_stopping_a_chat_that_is_not_running_still_ends_it(
    client: TestClient, run_dir: Path
) -> None:
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)

    response = client.post(f"/sessions/{chat_id}/stop")

    assert response.status_code == 202
    assert state_of(client, chat_id) == ChatState.ENDED.value
    assert load_session(run_dir / "session.json").ended_at is not None


def test_stopping_an_already_ended_chat_does_not_end_the_session_twice(
    client: TestClient, run_dir: Path
) -> None:
    """Stop is idempotent: an ended session is not re-closed (quickstart T067).

    `shutdown` already refuses to finalize a session that has an `ended_at` because a
    second `session.ended` says nothing new; pressing Stop on a turn that finished on its
    own has to obey the same rule, or `events.jsonl` carries two terminal events and
    `session.json` carries an `ended_at` that moved after the session ended.
    """
    chat_id = start_session(client, run_dir)["chat_id"]
    assert settle(client, chat_id) == ChatState.ENDED.value
    before_events = events_of(run_dir)
    before_ended_at = load_session(run_dir / "session.json").ended_at

    response = client.post(f"/sessions/{chat_id}/stop")

    assert response.status_code == 202
    assert state_of(client, chat_id) == ChatState.ENDED.value
    assert events_of(run_dir) == before_events
    assert load_session(run_dir / "session.json").ended_at == before_ended_at


# --- shutdown ------------------------------------------------------------------------


def test_a_shutdown_during_a_running_turn_still_finalizes_the_session(
    app: Any, run_dir: Path, provider_control: ProviderControl
) -> None:
    """FR-008: no session is ever left without an ended time, whatever killed the backend."""
    provider_control.hold()
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as client:
        chat_id = start_session(client, run_dir)["chat_id"]
        wait_until(provider_control.started.is_set, "the turn to reach the gate")
        assert state_of(client, chat_id) == ChatState.RUNNING.value

    session = load_session(run_dir / "session.json")
    assert session.ended_at is not None
    types = types_of(run_dir)
    assert "turn.ended" in types
    assert types[-1] == "session.ended"
    ended = [event for event in events_of(run_dir) if event["type"] == "turn.ended"]
    assert ended[-1]["body"]["reason"] == "error"
    # Only now: the stranded worker still holds the turn the shutdown finalized around it,
    # and letting it run any earlier would rewrite the files just asserted on.
    provider_control.release()


def test_a_shutdown_with_nothing_running_leaves_the_ended_session_alone(
    app: Any, run_dir: Path
) -> None:
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as client:
        chat_id = start_session(client, run_dir)["chat_id"]
        settle(client, chat_id)
        before = types_of(run_dir)

    assert types_of(run_dir) == before
    assert load_session(run_dir / "session.json").ended_at is not None


# --- a failed session ----------------------------------------------------------------


def test_a_provider_failure_fails_the_chat_and_still_writes_an_ended_time(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """The script runs out, which is a provider failure: the runner reports and finalizes."""
    provider_control.script = [turn("the only turn")]
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)

    client.post(f"/sessions/{chat_id}/messages", json={"text": "one more"})
    wait_until(
        lambda: state_of(client, chat_id) == ChatState.FAILED.value, "the chat to fail"
    )

    assert "error" in types_of(run_dir)
    assert load_session(run_dir / "session.json").ended_at is not None
    refused = client.post(f"/sessions/{chat_id}/messages", json={"text": "again"})
    assert refused.status_code == 409
    assert refused.json()["error_class"] == "SessionFailed"


def test_a_failed_chat_can_only_be_replaced_by_a_retry(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    provider_control.script = [turn("the only turn")]
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    client.post(f"/sessions/{chat_id}/messages", json={"text": "one more"})
    wait_until(
        lambda: state_of(client, chat_id) == ChatState.FAILED.value, "the chat to fail"
    )

    provider_control.script = text_turns(2)
    retry = start_session(client, run_dir, retry_of=chat_id)

    assert settle(client, retry["chat_id"]) == ChatState.ENDED.value
    assert retry["chat_id"] != chat_id
    seqs = seqs_of(run_dir)
    assert seqs == list(range(1, len(seqs) + 1)), "the retry restarted `seq` inside one file"


def test_a_failure_that_is_not_the_providers_still_ends_the_session(
    app: Any, client: TestClient, run_dir: Path
) -> None:
    """FR-008 and data-model section 3: `failed` still writes `session.ended`.

    The runner closes a *provider* failure out itself. Everything else that can raise out
    of a turn - here a `finalize()` that could not write the run folder - leaves the
    session open, and `failed` is terminal, so nothing else would ever close it. The
    worker writes the closing events instead of assuming the runner did.
    """
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    run = app.state.server.chats[UUID(chat_id)].run
    finalize = run.finalize
    attempts: list[int] = []

    def failing_finalize() -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("the run folder went away mid-turn")
        return finalize()

    run.finalize = failing_finalize

    client.post(f"/sessions/{chat_id}/messages", json={"text": "one more"})
    wait_until(
        lambda: state_of(client, chat_id) == ChatState.FAILED.value, "the chat to fail"
    )

    events = events_of(run_dir)
    assert [event["type"] for event in events[-3:]] == ["error", "turn.ended", "session.ended"]
    assert events[-2]["body"]["reason"] == "error"
    assert events[-1]["body"]["ended_at"] is not None
    assert load_session(run_dir / "session.json").ended_at is not None


def test_a_chat_that_could_not_be_closed_out_is_still_finalized_at_shutdown(
    app: Any, run_dir: Path
) -> None:
    """The shutdown pass asks whether the session ended, not whether the chat did.

    A chat whose close-out also failed is `failed` with no `ended_at`; a pass that skipped
    every finished chat would leave it open forever.
    """
    attempts: list[int] = []
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as client:
        chat_id = start_session(client, run_dir)["chat_id"]
        settle(client, chat_id)
        run = app.state.server.chats[UUID(chat_id)].run
        finalize = run.finalize

        def failing_finalize() -> Any:
            attempts.append(1)
            if len(attempts) <= 2:  # the turn's own, then the worker's close-out
                raise OSError("the run folder went away mid-turn")
            return finalize()

        run.finalize = failing_finalize
        client.post(f"/sessions/{chat_id}/messages", json={"text": "one more"})
        wait_until(
            lambda: state_of(client, chat_id) == ChatState.FAILED.value, "the chat to fail"
        )
        assert types_of(run_dir)[-1] != "session.ended"

    assert types_of(run_dir)[-1] == "session.ended"
    assert load_session(run_dir / "session.json").ended_at is not None


# --- the tool boundary ----------------------------------------------------------------


def test_a_turn_with_no_tool_call_left_to_make_finishes_normally(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """The stop flag is read at a tool boundary, so a turn that reaches none just ends."""
    provider_control.script = [turn("no tools at all")]
    chat_id = start_session(client, run_dir)["chat_id"]

    assert settle(client, chat_id) == ChatState.ENDED.value
    reasons = [
        event["body"]["reason"] for event in events_of(run_dir) if event["type"] == "turn.ended"
    ]
    assert reasons == ["end"]
