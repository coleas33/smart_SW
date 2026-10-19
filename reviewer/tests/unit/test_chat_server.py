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
from starlette.requests import Request
from starlette.testclient import TestClient

from swreview.agent.providers import AgentEvent, AgentProvider, ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import PROFILE_CHECK
from swreview.agent.settings import (
    MASK,
    MODEL_VIEW_PANE,
    ProviderSettings,
    pane_defaults,
    pane_efficiency,
)
from swreview.chat.server import SESSION_FILES, _sse, build_provider, create_app
from swreview.chat.sessions import ChatSession, ChatState
from swreview.checks.rms.run import is_check_folder
from swreview.checks.standards.run import run_standards_check
from swreview.ir.loader import save_package
from swreview.prerun import DIGEST_HEADER, RMS_PRERUN_TOOLS
from swreview.remodel.artifacts import grade_remodel_run
from swreview.report.attention import rank
from swreview.report.attention_record import (
    ATTENTION_FILE_NAME,
    read_attention_record,
    write_attention_record,
)
from swreview.report.session import Timing, load_session, save_session
from tests.support.attention import CHECK_FOLDER as ATTENTION_CHECK_FOLDER
from tests.support.contracts import contract_path, contract_validator
from tests.support.features import feature, folder
from tests.support.packages import build_package
from tests.support.remodel import remodel_package
from tests.support.replay import folder_hashes
from tests.unit import test_chat_standards_routes as standards

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
    ("POST", "/sessions/{chat}/send"),
    ("POST", "/sessions/{chat}/messages"),
    ("POST", "/sessions/{chat}/evidence/ER-001"),
    ("POST", "/sessions/{chat}/evidence"),
    ("POST", "/sessions/{chat}/findings/F-001/disposition"),
    ("POST", "/sessions/{chat}/timing"),
    ("POST", "/sessions/{chat}/stop"),
    ("GET", "/sessions/{chat}/report"),
    ("GET", "/sessions/{chat}/attention"),
    ("GET", "/sessions/{chat}/snapshot"),
    ("GET", "/reviews/20260913-120000-bracket"),
    ("GET", "/labels"),
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


def test_labels_answer_the_words_files_card_vocabulary(client: TestClient) -> None:
    """`GET /labels` (feature 009 T059, contracts/plain-words.md section 1): the words file's
    `labels` block, verbatim, with its version, so every word on a card is the backend's."""
    from swreview.report.summary import load_words

    response = client.get("/labels")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == load_words().labels.model_dump(mode="json")
    assert body["version"] == "review_words_v1"
    assert set(body) == {
        "version",
        "status",
        "severity",
        "bucket",
        "evidence_status",
        "contact_kind",
        "source",
        "errors",
    }
    assert body["source"] == {"code": "Checked by code", "model": "AI guidance"}, "feature 013"
    assert body["status"]["checked_within_scope"] == "checked within scope"
    assert body["errors"]["TurnRunning"].startswith("A review turn is still running.")


def test_labels_write_nothing_into_the_run_root(client: TestClient, run_root: Path) -> None:
    before = sorted(str(path) for path in run_root.rglob("*"))

    assert client.get("/labels").status_code == 200

    assert sorted(str(path) for path in run_root.rglob("*")) == before


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


def test_a_pane_review_runs_checks_first(client: TestClient, app: Any, run_dir: Path) -> None:
    """Feature 008 T047, FR-013: checks first is the pane default. The session records the
    pane's levers, the steps begin with the pre-run's own calls, the model opens on the
    digest, and the modelling-practice family is folded."""
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)

    session = load_session(run_dir / "session.json")
    assert session.efficiency == pane_efficiency(ProviderName.FAKE)
    assert [step.tool for step in session.steps[: len(RMS_PRERUN_TOOLS)]] == list(
        RMS_PRERUN_TOOLS
    )
    run = app.state.server.chats[UUID(chat_id)].run
    assert DIGEST_HEADER in str(run.messages[0]["content"])
    assert session.folded_families == ["rms"]


def test_a_pane_review_records_the_pane_defaults_model_view(
    client: TestClient, run_dir: Path
) -> None:
    """Feature 008 T076, FR-023: payload slimming and history pruning are pane defaults,
    decided with the levers by one function, and the session records both."""
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)

    written = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    pane = pane_defaults(ProviderName.FAKE)
    assert written["model_view"] == pane.model_view.model_dump() == MODEL_VIEW_PANE.model_dump()
    # Edited deliberately by feature 013 T121 and T125: lever 14, on in the pane since T125, is
    # written with the other levers.
    assert written["efficiency"] == pane.efficiency.model_dump()


@dataclass
class BuiltAdapters:
    """A provider factory that builds the product's own adapter and plays a scripted one.

    `build_provider` is the pane's construction site, so what it returns is what a real
    review would have talked to; the review itself runs on the scripted adapter, so no
    request leaves the machine.
    """

    control: ProviderControl
    built: list[AgentProvider] = field(default_factory=list)

    def factory(self, settings: ProviderSettings) -> AgentProvider:
        self.built.append(build_provider(settings))
        return self.control.factory(settings)


def test_an_openai_pane_review_asks_for_parallel_calls_and_records_it(
    run_root: Path,
    run_dir: Path,
    provider_control: ProviderControl,
    models: Models,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feature 008 T080, FR-024: the adapter the pane builds for OpenAI asks for parallel
    tool calls, and the session records the flag the adapter was built with."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-parallel")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    adapters = BuiltAdapters(provider_control)
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=adapters.factory,
        list_models=models,
    )

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as pane:
        chat_id = start_session(pane, run_dir, provider="openai", model=None)["chat_id"]
        settle(pane, chat_id)

    [adapter] = adapters.built
    session = load_session(run_dir / "session.json")
    assert getattr(adapter, "parallel_tool_calls", None) is True
    assert session.efficiency is not None
    assert session.efficiency.parallel_tool_calls is True
    assert session.efficiency == pane_efficiency(ProviderName.OPENAI)


def test_a_gemini_pane_review_records_parallel_calls_off(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """Gemini has no switch and already makes parallel calls, so the pane records the lever
    off rather than claiming an arm the provider cannot run (research R2.40)."""
    chat_id = start_session(client, run_dir, provider="gemini", model=None)["chat_id"]
    settle(client, chat_id)

    session = load_session(run_dir / "session.json")
    assert [settings.provider for settings in provider_control.built] == [ProviderName.GEMINI]
    assert session.efficiency is not None
    assert session.efficiency.parallel_tool_calls is False
    assert session.efficiency == pane_efficiency(ProviderName.GEMINI)


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


def model_check_folder(run_root: Path) -> Path:
    """An RMS check folder inside the run root, holding its own `attention.json`.

    The committed fixture rather than a live `run_rms_check`: this module's package has no
    feature rows to grade, and what is under test is the rotation, not the rules.
    """
    target = run_root / "20260918-220310-check"
    shutil.copytree(ATTENTION_CHECK_FOLDER, target)
    session = load_session(target / "session.json")
    write_attention_record(target, rank(session), session.session_id)
    return target


@pytest.fixture
def check_run_dir(run_root: Path) -> Path:
    """`model_check_folder`, for the tests that need only the Model check's."""
    return model_check_folder(run_root)


def standards_check_folder(run_root: Path) -> Path:
    """A Standards check's folder: the seeded golden graded against the fictional profile A."""
    target = run_root / "20261019-101600-assy-standards"
    target.mkdir()
    shutil.copy2(standards.SEEDED_PACKAGE, target / "package.json")
    run_standards_check(target, standards.PROFILE_A, target, run_root=run_root)
    return target


def grade_check_folder(run_root: Path) -> Path:
    """The re-modeler's grade of the copy at open: `rms-before/` under its remodel run."""
    tree = [
        folder("3-Core", feature("Boss-Extrude1", "Extrusion", description="")),
        folder("4-Detail", feature("Hole1", "HoleWzd")),
    ]
    package = remodel_package(tree, document_id="doc:copy", name="bracket-RMS")
    remodel_run = run_root / "20261019-101500-bracket-remodel"
    remodel_run.mkdir()
    graded = grade_remodel_run(
        remodel_run, before=package, after=package, source_design_id="dsn:FICT-source"
    )
    return graded.before.check_file.parent


CHECK_FOLDERS: dict[str, tuple[str, Callable[[Path], Path]]] = {
    "model check": ("rms", model_check_folder),
    "standards check": ("standards", standards_check_folder),
    "re-modeler grade": ("rms", grade_check_folder),
}
"""Every check's folder a run root holds, by kind: the family its `check.json` records, and
how it is built. The re-modeler's grade is `run_rms_check`'s own record, so it is `rms`."""


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


# --- a Retry replaces only the session it names, and never a check's (owner decision 142A)


def check_folder_refusal(check_dir: Path, family: str) -> dict[str, Any]:
    """The one body a check's folder is refused with, by a Retry and by a start alike."""
    return {
        "error_class": "InvalidRunDir",
        "message": (
            f"{check_dir.resolve()} holds the {family} check that ran in it and no review "
            "session: a Retry replaces only a review's session, and only a Model check's "
            "folder is handed to a new review; review into a new run folder"
        ),
        "retryable": False,
    }


def unknown_chat_refusal(run_dir: Path, chat_id: str) -> dict[str, Any]:
    """A Retry into a folder that holds a session, naming a chat this backend does not hold."""
    return {
        "error_class": "UnknownChat",
        "message": (
            f"no chat {chat_id} on this backend: {run_dir.resolve()} holds a session, and a "
            "Retry replaces it only for the chat that wrote it, which this backend no longer "
            "holds or never did; review into a new run folder"
        ),
        "retryable": False,
    }


def stray_session_refusal(run_dir: Path, chat_id: str, wrote: str, *held: str) -> dict[str, Any]:
    """A Retry naming a chat whose session `run_dir` does not hold; `held` names, file by
    file, what each session file there that is not `wrote`'s holds instead."""
    return {
        "error_class": "RunDirInUse",
        "message": (
            f"{run_dir.resolve()} does not hold the session chat {chat_id} wrote ({wrote}): "
            f"{'; '.join(held)}; a Retry replaces only the session its folder holds, so retry "
            "the chat that wrote it or review into a new run folder"
        ),
        "retryable": False,
    }


@pytest.mark.parametrize("kind", list(CHECK_FOLDERS))
def test_is_check_folder_recognises_every_family_s_folder(run_root: Path, kind: str) -> None:
    """The question both routes ask of a folder that holds a session. It read the folder
    through the rms record, so a standards check's folder was no check folder to it."""
    _, build = CHECK_FOLDERS[kind]

    assert is_check_folder(build(run_root))


def test_a_standards_folder_whose_session_its_record_does_not_name_is_no_check_folder(
    run_root: Path,
) -> None:
    """The other half, for the family that was missing: whatever the family, a folder is
    its check only while `check.json` names the `session.json` beside it."""
    check_dir = standards_check_folder(run_root)
    session = load_session(check_dir / "session.json")
    save_session(session.model_copy(update={"session_id": uuid4()}), check_dir / "session.json")

    assert not is_check_folder(check_dir)


@pytest.mark.parametrize("named", ["a chat this backend holds", "an id it never issued"])
@pytest.mark.parametrize("kind", list(CHECK_FOLDERS))
def test_a_retry_is_refused_on_every_family_s_check_folder_and_moves_nothing(
    app: Any,
    client: TestClient,
    run_dir: Path,
    run_root: Path,
    provider_control: ProviderControl,
    kind: str,
    named: str,
) -> None:
    """A check's folder holds no review session for a Retry to replace. Before 142A a Retry
    skipped the folder check, so any `retry_of` rotated the check's session aside and wrote
    a review into its folder. The folder is refused before the chat is looked up, so a chat
    this backend holds and an id it never issued meet the same 400."""
    family, build = CHECK_FOLDERS[kind]
    reviewed = start_session(client, run_dir)
    settle(client, reviewed["chat_id"])
    check_dir = build(run_root)
    before = folder_hashes(check_dir)
    built = len(provider_control.built)
    retry_of = reviewed["chat_id"] if named == "a chat this backend holds" else str(uuid4())

    response = client.post("/sessions", json=session_body(check_dir, retry_of=retry_of))

    assert response.status_code == 400
    assert response.json() == check_folder_refusal(check_dir, family)
    assert folder_hashes(check_dir) == before
    assert list(app.state.server.chats) == [UUID(reviewed["chat_id"])]
    assert len(provider_control.built) == built


def test_a_start_on_a_standards_folder_is_refused_with_the_body_a_retry_gets(
    client: TestClient, run_root: Path, provider_control: ProviderControl
) -> None:
    """One 400, one class and one wording for a check's folder, from both routes. A start
    was refused here already, but as "a review session" to "retry with 'retry_of'": the
    standards check was no check to `is_check_folder`, and the Retry it pointed to is now
    refused too."""
    check_dir = standards_check_folder(run_root)
    before = folder_hashes(check_dir)

    start = client.post("/sessions", json=session_body(check_dir))
    retry = client.post("/sessions", json=session_body(check_dir, retry_of=str(uuid4())))

    assert (start.status_code, retry.status_code) == (400, 400)
    assert start.json() == retry.json() == check_folder_refusal(check_dir, "standards")
    assert folder_hashes(check_dir) == before
    assert provider_control.built == []


@pytest.mark.parametrize("kind", ["model check", "re-modeler grade"])
def test_a_start_still_claims_an_rms_check_s_folder(
    client: TestClient, run_root: Path, kind: str
) -> None:
    """Unchanged by 142A. Feature 003's User Story 6 scenario 11 hands a Model check's folder
    to a review, which rotates the check's session aside (feature 007 FR-021). The
    re-modeler's grade is the same rms record, so a start claims it as well; only a Retry is
    refused on either."""
    _, build = CHECK_FOLDERS[kind]
    check_dir = build(run_root)
    check_session = load_session(check_dir / "session.json").session_id

    settle(client, start_session(client, check_dir)["chat_id"])

    assert load_session(check_dir / "session.1.json").session_id == check_session
    assert load_session(check_dir / "session.json").session_id != check_session


def test_a_retry_naming_no_chat_this_backend_holds_is_refused_and_moves_nothing(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """`retry_of` must name the chat whose session the folder holds; an id this backend
    never issued names none, so nothing is rotated and no provider is built."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    before = folder_hashes(run_dir)
    built = len(provider_control.built)
    stranger = str(uuid4())

    response = client.post("/sessions", json=session_body(run_dir, retry_of=stranger))

    assert response.status_code == 404
    assert response.json() == unknown_chat_refusal(run_dir, stranger)
    assert folder_hashes(run_dir) == before
    assert len(provider_control.built) == built


def test_a_retry_a_restarted_backend_cannot_tie_to_the_folder_is_refused(
    client: TestClient,
    run_dir: Path,
    run_root: Path,
    provider_control: ProviderControl,
    models: Models,
) -> None:
    """What 142A costs (research, 142A): a settings save restarts the backend, which then
    holds none of the chats before it and so cannot tell that the session in the folder is
    the one the Retry names. The pane's own Retry extracts into a new folder and is not
    affected; a context review's Retry in its own folder (108A) is refused after one."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    before = folder_hashes(run_dir)
    restarted = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
    )

    with TestClient(
        restarted, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as fresh:
        response = fresh.post("/sessions", json=session_body(run_dir, retry_of=first["chat_id"]))

    assert response.status_code == 404
    assert response.json() == unknown_chat_refusal(run_dir, first["chat_id"])
    assert folder_hashes(run_dir) == before


def test_a_retry_into_a_folder_holding_no_session_needs_no_chat_this_backend_holds(
    client: TestClient, run_dir: Path
) -> None:
    """Unchanged by 142A, and what the pane's own Retry does: it extracts into a new folder,
    which holds no session to replace, so the chat it names need not be one this backend
    still holds. The link is recorded only for a chat it holds (FR-028)."""
    response = client.post("/sessions", json=session_body(run_dir, retry_of=str(uuid4())))

    assert response.status_code == 201, response.text
    settle(client, response.json()["chat_id"])
    assert load_session(run_dir / "session.json").retry_of is None


def test_a_retry_naming_another_folder_s_chat_is_refused_and_moves_nothing(
    client: TestClient, run_dir: Path, run_root: Path, tmp_package_dir: Path
) -> None:
    other = run_root / "20260913-120500-bracket"
    shutil.copytree(tmp_package_dir, other)
    elsewhere = start_session(client, other)
    settle(client, elsewhere["chat_id"])
    settle(client, start_session(client, run_dir)["chat_id"])
    before = folder_hashes(run_dir)

    response = client.post(
        "/sessions", json=session_body(run_dir, retry_of=elsewhere["chat_id"])
    )

    assert response.status_code == 409
    assert response.json() == {
        "error_class": "RunDirInUse",
        "message": (
            f"chat {elsewhere['chat_id']} reviewed {other.resolve()}, not {run_dir.resolve()}: "
            "a Retry replaces only the session its own chat wrote; review into a new run folder"
        ),
        "retryable": False,
    }
    assert folder_hashes(run_dir) == before


def test_a_retry_of_a_retry_names_the_latest_attempt_not_the_one_it_replaced(
    client: TestClient, run_dir: Path
) -> None:
    """The folder already rotated: the first attempt's session is `session.1.json` now, so a
    Retry naming it would rotate its successor's aside. Naming the successor still works."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    second = start_session(client, run_dir, retry_of=first["chat_id"])
    settle(client, second["chat_id"])
    before = folder_hashes(run_dir)

    stale = client.post("/sessions", json=session_body(run_dir, retry_of=first["chat_id"]))

    assert stale.status_code == 409
    assert stale.json() == stray_session_refusal(
        run_dir,
        first["chat_id"],
        first["review_session_id"],
        f"its events.jsonl belongs to session {second['review_session_id']}",
        f"its session.json belongs to session {second['review_session_id']}",
    )
    assert folder_hashes(run_dir) == before

    third = start_session(client, run_dir, retry_of=second["chat_id"])
    settle(client, third["chat_id"])
    assert [
        str(load_session(run_dir / name).session_id)
        for name in ("session.1.json", "session.2.json", "session.json")
    ] == [first["review_session_id"], second["review_session_id"], third["review_session_id"]]
    assert str(load_session(run_dir / "session.json").retry_of) == second["review_session_id"]


def test_a_review_that_claimed_a_model_check_s_folder_is_retried_there_by_its_own_chat(
    client: TestClient, check_run_dir: Path
) -> None:
    """The folder keeps its `check.json`, but once the review's session is beside it, it is no
    check's folder (`is_check_folder`): the review's own chat retries it like any review's."""
    check_session = str(load_session(check_run_dir / "session.json").session_id)
    review = start_session(client, check_run_dir)
    settle(client, review["chat_id"])

    retry = start_session(client, check_run_dir, retry_of=review["chat_id"])
    settle(client, retry["chat_id"])

    assert [
        str(load_session(check_run_dir / name).session_id)
        for name in ("session.1.json", "session.2.json", "session.json")
    ] == [check_session, review["review_session_id"], retry["review_session_id"]]


@pytest.mark.parametrize("missing", ["session.json", "events.jsonl"])
def test_a_retry_tells_the_session_by_the_file_the_folder_still_holds(
    client: TestClient, run_dir: Path, missing: str
) -> None:
    """A folder holding one of the two session files is still that session's: the record
    alone (a stream deleted by hand) or the stream alone (no record written yet)."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    (run_dir / missing).unlink()

    second = start_session(client, run_dir, retry_of=first["chat_id"])
    settle(client, second["chat_id"])

    if missing == "session.json":
        stream = (run_dir / "events.1.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(stream[0])["body"]["session_id"] == first["review_session_id"]
        assert not (run_dir / "session.1.json").exists()
    else:
        record = load_session(run_dir / "session.1.json")
        assert str(record.session_id) == first["review_session_id"]
        assert not (run_dir / "events.1.jsonl").exists()


@pytest.mark.parametrize(
    "case", ["an unreadable record", "an unreadable stream", "another session's record"]
)
def test_a_retry_is_refused_where_a_session_file_is_not_its_chat_s(
    client: TestClient, run_dir: Path, case: str
) -> None:
    """Every session file the folder holds must name the chat's session. One that cannot be
    read cannot be shown to be its, so the Retry is refused rather than guessed through."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    if case == "an unreadable record":
        (run_dir / "session.json").write_text("not a session record", encoding="utf-8")
        held = "its session.json cannot be read as one session's"
    elif case == "an unreadable stream":
        (run_dir / "events.jsonl").write_text("not an event\n", encoding="utf-8")
        held = "its events.jsonl cannot be read as one session's"
    else:
        stranger = uuid4()
        session = load_session(run_dir / "session.json")
        save_session(session.model_copy(update={"session_id": stranger}), run_dir / "session.json")
        held = f"its session.json belongs to session {stranger}"
    before = folder_hashes(run_dir)

    response = client.post("/sessions", json=session_body(run_dir, retry_of=first["chat_id"]))

    assert response.status_code == 409
    assert response.json() == stray_session_refusal(
        run_dir, first["chat_id"], first["review_session_id"], held
    )
    assert folder_hashes(run_dir) == before


@pytest.mark.parametrize("spelling", ["upper case", "braces", "urn", "no hyphens"])
def test_a_retry_matches_its_chat_however_the_id_is_spelled(
    client: TestClient, run_dir: Path, spelling: str
) -> None:
    """`retry_of` is read as a uuid, not compared as text, so these name the same chat."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    chat_id = first["chat_id"]
    spelled = {
        "upper case": chat_id.upper(),
        "braces": "{" + chat_id + "}",
        "urn": f"urn:uuid:{chat_id}",
        "no hyphens": UUID(chat_id).hex,
    }[spelling]

    second = start_session(client, run_dir, retry_of=spelled)
    settle(client, second["chat_id"])

    assert client.get(f"/sessions/{second['chat_id']}").json()["retry_of"] == chat_id
    assert str(load_session(run_dir / "session.json").retry_of) == first["review_session_id"]


@pytest.mark.parametrize(
    "spell",
    [
        lambda chat_id: "not-a-uuid",
        lambda chat_id: "   ",
        lambda chat_id: f" {chat_id} ",
        lambda chat_id: 42,
        lambda chat_id: True,
    ],
    ids=["not-a-uuid", "blank", "padded", "a number", "a boolean"],
)
def test_a_retry_of_that_is_no_uuid_is_refused_before_the_folder_is_looked_at(
    client: TestClient, run_dir: Path, spell: Callable[[str], Any]
) -> None:
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    raw = spell(first["chat_id"])
    before = folder_hashes(run_dir)

    response = client.post("/sessions", json=session_body(run_dir, retry_of=raw))

    assert response.status_code == 400
    assert response.json() == {
        "error_class": "InvalidRequest",
        "message": f"retry_of must be a uuid, got {raw!r}",
        "retryable": False,
    }
    assert folder_hashes(run_dir) == before


def test_an_empty_retry_of_is_no_retry_and_meets_a_start_s_refusal(
    client: TestClient, run_dir: Path
) -> None:
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])

    response = client.post("/sessions", json=session_body(run_dir, retry_of=""))

    assert response.status_code == 400
    assert response.json() == {
        "error_class": "InvalidRunDir",
        "message": (
            f"{run_dir.resolve()} already holds a review session; retry it with 'retry_of' "
            "or review into a new run folder"
        ),
        "retryable": False,
    }


def test_two_retries_of_one_chat_rotate_its_folder_once(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    """Concurrent Retries of one chat: the first holds the folder while it runs, so the
    second meets the live chat; once that one ends, the folder holds its session and not
    the retried chat's, so the second is refused again and nothing rotates twice."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    provider_control.hold()
    winner = start_session(client, run_dir, retry_of=first["chat_id"])
    assert provider_control.started.wait(TIMEOUT_S)

    during = client.post("/sessions", json=session_body(run_dir, retry_of=first["chat_id"]))
    provider_control.release()
    settle(client, winner["chat_id"])
    after = client.post("/sessions", json=session_body(run_dir, retry_of=first["chat_id"]))

    assert during.status_code == 409
    assert during.json()["message"] == (
        f"chat {winner['chat_id']} is already reviewing {run_dir.resolve()}; "
        "one chat per run folder"
    )
    assert after.status_code == 409
    assert after.json() == stray_session_refusal(
        run_dir,
        first["chat_id"],
        first["review_session_id"],
        f"its events.jsonl belongs to session {winner['review_session_id']}",
        f"its session.json belongs to session {winner['review_session_id']}",
    )
    assert (run_dir / "session.1.json").is_file()
    assert not (run_dir / "session.2.json").exists()


def test_the_provider_settings_come_from_the_request_and_the_environment(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> None:
    start_session(client, run_dir, model="fake-2", effort="low")

    settings = provider_control.built[-1]
    assert settings.provider is ProviderName.FAKE
    assert settings.model == "fake-2"
    assert settings.effort == "low"
    assert settings.key_source == "none"


# --- where the key came from: the add-in's marker (owner decision 138A) ----------------

PANE_KEY = "fict" + "-pane-saved-" + "0138a"
"""The key saved in the pane, as the add-in copies it into the backend's environment. Built
from fragments and not provider-shaped."""

WORKSTATION_KEY = "fict" + "-workstation-" + "0138a"
"""A key the workstation exports for itself, which the backend inherits from SLDWORKS.exe."""

KEY_VARIABLES = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "GOOGLE_API_KEY", "GEMINI_API_KEY")


@pytest.fixture
def no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """The backend's environment holds no key until a test puts one there, whatever the
    workstation running the suite exports."""
    for name in KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def marked_app(
    run_root: Path,
    marker: ProviderName | None,
    provider_factory: Callable[[ProviderSettings], AgentProvider] | None,
    models: Models,
) -> Any:
    """The backend as the add-in starts it, saying (or not) whose key is the saved one."""
    return create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_factory,
        list_models=models,
        settings_key_provider=marker,
    )


@pytest.mark.parametrize(
    ("marker", "recorded"),
    [(ProviderName.OPENAI, "settings"), (None, "env")],
    ids=["marked", "unmarked"],
)
def test_a_pane_review_records_where_its_key_came_from(
    run_root: Path,
    run_dir: Path,
    provider_control: ProviderControl,
    models: Models,
    no_provider_keys: pytest.MonkeyPatch,
    marker: ProviderName | None,
    recorded: str,
) -> None:
    """Owner decision 138A. The add-in copies the key into the backend's environment either
    way; only its marker says the key is the one saved in the pane, and `session.json`
    records `settings` then, `env` without it - never the key itself."""
    no_provider_keys.setenv("OPENAI_API_KEY", PANE_KEY)
    app = marked_app(run_root, marker, provider_control.factory, models)

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as pane:
        chat_id = start_session(pane, run_dir, provider="openai", model=None)["chat_id"]
        settle(pane, chat_id)

    assert [settings.key_source for settings in provider_control.built] == [recorded]
    written = (run_dir / "session.json").read_text(encoding="utf-8")
    assert json.loads(written)["provider_info"]["key_source"] == recorded
    assert PANE_KEY not in written
    assert PANE_KEY not in (run_dir / "events.jsonl").read_text(encoding="utf-8")


def test_the_marker_names_one_provider_so_another_providers_key_records_env(
    run_root: Path,
    run_dir: Path,
    provider_control: ProviderControl,
    models: Models,
    no_provider_keys: pytest.MonkeyPatch,
) -> None:
    """The saved key was copied under OpenAI's variable; a Gemini session - posted after a
    provider change the backend has not restarted for yet - reads the workstation's own key,
    and that is `env`, not the credential saved in the pane."""
    no_provider_keys.setenv("OPENAI_API_KEY", PANE_KEY)
    no_provider_keys.setenv("GOOGLE_API_KEY", WORKSTATION_KEY)
    app = marked_app(run_root, ProviderName.OPENAI, provider_control.factory, models)

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as pane:
        chat_id = start_session(pane, run_dir, provider="gemini", model=None)["chat_id"]
        settle(pane, chat_id)

    [settings] = provider_control.built
    assert settings.provider is ProviderName.GEMINI
    assert settings.key_source == "env"
    session = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    assert session["provider_info"]["key_source"] == "env"


@pytest.mark.parametrize("marker", [None, ProviderName.OPENAI], ids=["unmarked", "marked"])
def test_a_marked_backend_with_no_key_refuses_a_review_as_it_always_has(
    run_root: Path,
    run_dir: Path,
    models: Models,
    no_provider_keys: pytest.MonkeyPatch,
    marker: ProviderName | None,
) -> None:
    """The marker is a statement about a key, never a key: with none in the environment a
    ticked review meets the product's own adapter refusing to start without one, marked or
    not (`build_provider`, the real factory; nothing reaches a network)."""
    app = marked_app(run_root, marker, None, models)

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as pane:
        response = pane.post("/sessions", json=session_body(run_dir, provider="openai", model=None))

    assert response.status_code == 502
    assert response.json() == {
        "error_class": "ValueError",
        "message": "an OpenAI adapter needs either an api_key or a ready-made client",
        "retryable": True,
    }


@pytest.mark.parametrize("marker", [None, ProviderName.OPENAI], ids=["unmarked", "marked"])
def test_a_marked_backend_with_no_key_refuses_send_as_it_always_has(
    run_root: Path,
    run_dir: Path,
    provider_control: ProviderControl,
    models: Models,
    no_provider_keys: pytest.MonkeyPatch,
    marker: ProviderName | None,
) -> None:
    """The waiting path of the same rule: the checks run and record `none`, and Send is the
    existing `409 NoCredential`, marked or not."""
    app = marked_app(run_root, marker, provider_control.factory, models)

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as pane:
        chat_id = start_session(
            pane, run_dir, provider="openai", model=None, send_when_checked=False
        )["chat_id"]
        response = pane.post(f"/sessions/{chat_id}/send", json={})

    assert response.status_code == 409
    assert response.json()["error_class"] == "NoCredential"
    session = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    assert session["provider_info"]["key_source"] == "none"
    assert provider_control.built == []


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
    """The pane reconnects into a running turn: what it missed, then what happens next.

    Feature 008 T047, edited deliberately: the pane runs checks first, so setup writes the
    pre-run's steps before the turn reaches the gate. The stream is read far enough to
    carry every one of them and the first live text, the id-equals-seq assertion covers
    the whole replay, and the text arrives after the last pre-run `tool.finished`."""
    provider_control.script = [turn("streamed answer")]
    provider_control.hold()
    chat_id = start_session(client, run_dir)["chat_id"]
    wait_until(provider_control.started.is_set, "the turn to reach the gate")
    written_before_the_turn = len(events_of(run_dir))
    count = written_before_the_turn + 2

    events = read_stream(
        app,
        f"/sessions/{chat_id}/events",
        count=count,
        on_open=provider_control.release,
    )

    assert events[0]["event"] == "session.started"
    assert [event["id"] for event in events] == [str(index) for index in range(1, count + 1)]
    kinds = [event["event"] for event in events]
    assert "text.delta" in kinds
    last_prerun_finished = max(i for i, kind in enumerate(kinds) if kind == "tool.finished")
    assert last_prerun_finished < written_before_the_turn
    assert kinds.index("text.delta") > last_prerun_finished
    assert events[0]["data"]["provider"] == "fake"
    assert events[0]["data"]["model"] == MODEL

    # The body alone travels in `data`. The page builds its `{seq, type, body}` envelope from
    # the three SSE fields (app.js `onFrame`), so a `data` that carried the envelope would be
    # read as a body with a `type` key and rendered as an event about nothing - the shape the
    # add-in tests fabricated until 2026-09-18 (docs/history/pane-findings-2026-09-18.md).
    for event in events:
        assert "type" not in event["data"]
        assert "seq" not in event["data"]


def test_the_pane_stream_carries_the_served_model(
    run_root: Path,
    run_dir: Path,
    models: Models,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import respx

    from swreview.agent.providers.openai_provider import OpenAIProvider
    from tests.unit.test_openai_provider import (
        KEY,
        RESPONSES_URL,
        completed,
        make_client,
        message_item,
        stream_response,
    )

    requested_model = "fict-model-a"
    served_model = "fict-model-a-2026-10-01"
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    final = completed(message_item("The review is complete."))
    final["response"]["model"] = served_model

    with make_client() as sdk_client, respx.mock() as router:
        route = router.post(RESPONSES_URL).mock(return_value=stream_response(final))

        def factory(settings: ProviderSettings) -> AgentProvider:
            return OpenAIProvider(model=settings.model, api_key=KEY, client=sdk_client)

        app = create_app(
            token=TOKEN,
            allow_origin=ORIGIN,
            run_root=run_root,
            provider_factory=factory,
            list_models=models,
            secrets=(),
        )
        with TestClient(
            app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        ) as pane:
            chat_id = start_session(pane, run_dir, provider="openai", model=requested_model)[
                "chat_id"
            ]
            assert settle(pane, chat_id) == ChatState.ENDED.value
            events = read_stream(app, f"/sessions/{chat_id}/events", count=len(events_of(run_dir)))

        assert route.called
        assert all(
            json.loads(call.request.content)["model"] == requested_model for call in route.calls
        )

    usages = [event["data"] for event in events if event["event"] == "usage"]
    assert usages
    assert all(body["model"] == requested_model for body in usages)
    assert all(body["served_model"] == served_model for body in usages)
    assert all("retries" not in event["data"] for event in events)


def test_the_contract_sample_is_what_the_producer_writes_byte_for_byte() -> None:
    """The recorded closing pair, `turn.ended` then `session.ended`, exactly as `_sse` writes it.

    The add-in's page tests feed this same file to the real page (SseFrames.cs), so the
    producer here and the consumer there are pinned to one artifact, and a change to either
    side's idea of a frame goes red in one suite or the other. Until 2026-09-18 nothing pinned
    them to each other: the C# tests fabricated an envelope-in-`data` frame this server never
    writes, and every real frame fell through the page's parser
    (docs/history/pane-findings-2026-09-18.md).
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
# batch route's half follows feature 008's batch-route tests below.


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


# --- several answers at once (feature 008 T084, contracts/answer-batch.md section 2) --------

THREE_REQUESTS = tuple(
    call("request_evidence", **{**EVIDENCE_ARGUMENTS, "what": what, "entity_ids": ids})
    for what, ids in (
        ("The usable thread depth of hole:1", EVIDENCE_ARGUMENTS["entity_ids"]),
        ("The washer grade", ["fst:1"]),
        ("The drawing revision", ["cmp:0002"]),
    )
)
"""Edited deliberately by feature 013 T064: each ask names its own entity, since the re-ask
guard answers a model question naming the same parts with no checklist item from the earlier one
(contracts/re-ask-guard.md section 3)."""

ANSWERS: list[dict[str, str]] = [
    {"request_id": "ER-002", "answer": "Grade 8.8, zinc flake."},
    {"request_id": "ER-003", "answer": "Revision C is released."},
    {"request_id": "ER-001", "answer": "Tapped 12 mm deep."},
]
"""All three answers, in an order that is not the ids', so submission order is visible."""


@pytest.fixture
def waiting_on_three(
    client: TestClient, run_dir: Path, provider_control: ProviderControl
) -> str:
    """A session that opened ER-001 to ER-003 and is waiting for the engineer."""
    provider_control.script = [
        turn("I need three things.", *THREE_REQUESTS),
        turn("Thanks; the joint is fine."),
        *text_turns(2),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    assert settle(client, chat_id) == ChatState.WAITING_ENGINEER.value
    return chat_id


def answer_all(client: TestClient, chat_id: str, answers: Any) -> Any:
    return client.post(f"/sessions/{chat_id}/evidence", json={"answers": answers})


def requests_of(run_dir: Path) -> list[tuple[str, str, str | None]]:
    return [
        (request.id, request.status, request.answer)
        for request in load_session(run_dir / "session.json").evidence_requests
    ]


def test_three_answers_together_resume_the_review_once(
    client: TestClient, run_dir: Path, waiting_on_three: str
) -> None:
    before = types_of(run_dir)

    response = answer_all(client, waiting_on_three, ANSWERS)

    assert response.status_code == 202
    assert response.json()["chat_id"] == waiting_on_three
    assert settle(client, waiting_on_three) == ChatState.ENDED.value
    after = events_of(run_dir)[len(before) :]
    kinds = [event["type"] for event in after]
    assert [event["body"] for event in after if event["type"] == "evidence.answered"] == ANSWERS
    assert kinds[:3] == ["evidence.answered"] * 3
    assert kinds.count("turn.ended") == 1
    assert kinds.count("session.ended") == 1
    by_id = {item["request_id"]: item["answer"] for item in ANSWERS}
    assert requests_of(run_dir) == [
        (request_id, "answered", by_id[request_id]) for request_id in ("ER-001", "ER-002", "ER-003")
    ]


def test_a_partial_batch_answers_only_what_it_names(
    client: TestClient, run_dir: Path, waiting_on_three: str
) -> None:
    """Some of the open questions may go back together; the rest stay open."""
    response = answer_all(client, waiting_on_three, ANSWERS[:2])

    assert response.status_code == 202
    assert settle(client, waiting_on_three) == ChatState.WAITING_ENGINEER.value
    assert [status for _, status, _ in requests_of(run_dir)] == ["open", "answered", "answered"]


def refused_without_change(
    client: TestClient, run_dir: Path, chat_id: str, answers: Any
) -> dict[str, Any]:
    """Post a submission that must be refused; assert it changed nothing; return the body."""
    lines = len(events_of(run_dir))
    requests = requests_of(run_dir)

    response = answer_all(client, chat_id, answers)

    assert response.status_code >= 400, response.text
    assert len(events_of(run_dir)) == lines
    assert requests_of(run_dir) == requests
    assert state_of(client, chat_id) == ChatState.WAITING_ENGINEER.value
    return {"status": response.status_code, **response.json()}


def test_an_unknown_id_refuses_the_whole_batch_naming_it(
    client: TestClient, run_dir: Path, waiting_on_three: str
) -> None:
    body = refused_without_change(
        client,
        run_dir,
        waiting_on_three,
        [ANSWERS[0], {"request_id": "ER-404", "answer": "anything"}, ANSWERS[1]],
    )

    assert (body["status"], body["error_class"]) == (404, "UnknownEvidenceRequest")
    assert "ER-404" in body["message"]


def test_an_answered_id_refuses_the_whole_batch(
    client: TestClient, run_dir: Path, waiting_on_three: str
) -> None:
    client.post(f"/sessions/{waiting_on_three}/evidence/ER-001", json={"answer": "12 mm"})
    assert settle(client, waiting_on_three) == ChatState.WAITING_ENGINEER.value

    body = refused_without_change(
        client,
        run_dir,
        waiting_on_three,
        [ANSWERS[0], {"request_id": "ER-001", "answer": "12 mm again"}],
    )

    assert (body["status"], body["error_class"]) == (409, "AlreadyAnswered")
    assert "ER-001" in body["message"]


@pytest.mark.parametrize(
    ("answers", "named"),
    [
        ([], "at least one"),
        ("ER-001: 12 mm", "list"),
        (None, "list"),
        ([ANSWERS[0], "ER-001: 12 mm"], "answers[1]"),
        ([ANSWERS[0], {"request_id": "ER-001"}], "answers[1]"),
        ([{"request_id": "ER-001", "answer": 12}], "answers[0]"),
        ([{"request_id": "ER-001", "answer": "   "}], "answers[0]"),
        ([{"request_id": 1, "answer": "12 mm"}], "answers[0]"),
        ([{"request_id": "", "answer": "12 mm"}], "answers[0]"),
        ([ANSWERS[0], ANSWERS[1], {**ANSWERS[0], "answer": "again"}], "ER-002"),
    ],
    ids=[
        "empty",
        "not-a-list",
        "null",
        "item-not-an-object",
        "item-without-answer",
        "answer-not-a-string",
        "blank-answer",
        "request-id-not-a-string",
        "blank-request-id",
        "repeated-id",
    ],
)
def test_a_malformed_submission_is_an_invalid_request_naming_the_problem(
    client: TestClient, run_dir: Path, waiting_on_three: str, answers: Any, named: str
) -> None:
    body = refused_without_change(client, run_dir, waiting_on_three, answers)

    assert (body["status"], body["error_class"]) == (400, "InvalidRequest")
    assert named in body["message"]


def test_a_body_without_answers_is_an_invalid_request(
    client: TestClient, run_dir: Path, waiting_on_three: str
) -> None:
    lines = len(events_of(run_dir))

    missing = client.post(f"/sessions/{waiting_on_three}/evidence", json={"answer": "12 mm"})
    not_json = client.post(
        f"/sessions/{waiting_on_three}/evidence",
        content=b"answers",
        headers={"Content-Type": "application/json"},
    )

    assert (missing.status_code, missing.json()["error_class"]) == (400, "InvalidRequest")
    assert (not_json.status_code, not_json.json()["error_class"]) == (400, "InvalidRequest")
    assert len(events_of(run_dir)) == lines


def test_a_batch_for_an_unknown_chat_is_a_404(client: TestClient) -> None:
    response = answer_all(client, str(uuid4()), ANSWERS)

    assert (response.status_code, response.json()["error_class"]) == (404, "UnknownChat")


def test_a_batch_is_refused_while_a_turn_is_running(
    client: TestClient, provider_control: ProviderControl, waiting_on_three: str
) -> None:
    """Checked in the contract's order: the shape first, then the running turn, then the ids."""
    provider_control.hold()
    client.post(f"/sessions/{waiting_on_three}/messages", json={"text": "keep going"})
    wait_until(provider_control.started.is_set, "the follow-up turn to reach the gate")

    running = answer_all(client, waiting_on_three, ANSWERS)
    unknown_while_running = answer_all(
        client, waiting_on_three, [{"request_id": "ER-404", "answer": "anything"}]
    )
    malformed_while_running = answer_all(client, waiting_on_three, [])

    assert (running.status_code, running.json()["error_class"]) == (409, "TurnRunning")
    assert unknown_while_running.json()["error_class"] == "TurnRunning"
    assert malformed_while_running.json()["error_class"] == "InvalidRequest"
    provider_control.release()


# The batch route's half of feature 009 T041 (data-model section 9): its two refusals about
# one request name that request, the first that failed, as `request_id`; no other refusal
# of the route carries the key, not even the 400 whose message names a repeated id.

REFUSAL_KEYS = {"error_class", "message", "retryable", "request_id"}


def test_the_batch_names_the_unknown_request_it_refused(
    client: TestClient, waiting_on_three: str
) -> None:
    body = answer_all(
        client,
        waiting_on_three,
        [
            ANSWERS[0],
            {"request_id": "ER-404", "answer": "anything"},
            {"request_id": "ER-405", "answer": "anything"},
        ],
    ).json()

    assert (body["error_class"], body["request_id"]) == ("UnknownEvidenceRequest", "ER-404")
    assert set(body) == REFUSAL_KEYS


def test_the_batch_names_the_answered_request_it_refused(
    client: TestClient, waiting_on_three: str
) -> None:
    client.post(f"/sessions/{waiting_on_three}/evidence/ER-003", json={"answer": "Rev C"})
    settle(client, waiting_on_three)

    body = answer_all(
        client, waiting_on_three, [ANSWERS[0], {"request_id": "ER-003", "answer": "again"}]
    ).json()

    assert (body["error_class"], body["request_id"]) == ("AlreadyAnswered", "ER-003")
    assert set(body) == REFUSAL_KEYS


def test_every_other_batch_refusal_carries_no_request_id(
    client: TestClient, provider_control: ProviderControl, waiting_on_three: str
) -> None:
    repeated = answer_all(client, waiting_on_three, [ANSWERS[0], ANSWERS[0]]).json()
    malformed = answer_all(client, waiting_on_three, [{"request_id": "ER-001"}]).json()
    unknown_chat = answer_all(client, str(uuid4()), ANSWERS).json()
    provider_control.hold()
    client.post(f"/sessions/{waiting_on_three}/messages", json={"text": "keep going"})
    wait_until(provider_control.started.is_set, "the follow-up turn to reach the gate")
    running = answer_all(client, waiting_on_three, ANSWERS).json()
    provider_control.release()

    refusals = (repeated, malformed, unknown_chat, running)
    assert [body["error_class"] for body in refusals] == [
        "InvalidRequest",
        "InvalidRequest",
        "UnknownChat",
        "TurnRunning",
    ]
    assert "ER-002" in repeated["message"]
    assert all("request_id" not in body for body in refusals)
    assert all(set(body) == REFUSAL_KEYS - {"request_id"} for body in refusals)


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


@pytest.mark.parametrize("state", [ChatState.RUNNING, ChatState.WAITING_ENGINEER])
def test_the_panes_stop_uses_the_review_runs_stopped_end(
    app: Any,
    run_dir: Path,
    provider_control: ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
    state: ChatState,
) -> None:
    """Both an interrupted turn and an idle Stop use the shared stopped finalizer."""
    provider_control.script = [turn("never finished", call("get_package_summary"))]
    server = app.state.server
    chat = ChatSession(run_dir=run_dir, state=state)
    run = server._start_review(chat, ProviderSettings(provider="fake", model=MODEL))
    chat.run = run
    server.chats[chat.chat_id] = chat
    stopped: list[Any] = []
    end_stopped = run.end_stopped

    def record_stopped() -> Any:
        stopped.append(run)
        return end_stopped()

    monkeypatch.setattr(run, "end_stopped", record_stopped)
    request = Request({"type": "http", "path_params": {"chat_id": str(chat.chat_id)}})
    try:
        response = anyio.run(server.stop, request)
        if state is ChatState.RUNNING:
            server._play(chat, run.start)

        assert response.status_code == 202
        assert stopped == [run]
        assert chat.state is ChatState.ENDED
        assert run.session.ended_at is not None
        ended = [event for event in events_of(run_dir) if event["type"] == "turn.ended"]
        assert ended[-1]["body"]["reason"] == "stopped"
    finally:
        run.close()


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
