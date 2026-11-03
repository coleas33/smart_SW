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

import functools
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

from swreview.agent import runner
from swreview.agent.providers import AgentEvent, AgentProvider, ProviderError, ProviderName
from swreview.agent.providers.fake import (
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.agent.runner import PROFILE_CHECK
from swreview.agent.settings import (
    MASK,
    MODEL_VIEW_PANE,
    ProviderSettings,
    pane_defaults,
    pane_efficiency,
)
from swreview.chat import server as chat_server
from swreview.chat.server import SESSION_FILES, _sse, build_provider, create_app
from swreview.chat.sessions import ChatSession, ChatState
from swreview.checks.rms.run import is_check_folder
from swreview.checks.rules.run import session_replaced
from swreview.checks.standards.run import run_standards_check
from swreview.findings import MODEL_FINDING_CHECK, TRIAGES, Disposition
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import DIGEST_HEADER, RMS_PRERUN_TOOLS
from swreview.remodel.artifacts import GradedRun, grade_remodel_run, write_package
from swreview.report.attention import rank
from swreview.report.attention_record import (
    ATTENTION_FILE_NAME,
    read_attention_record,
    write_attention_record,
)
from swreview.report.session import ReviewSession, Timing, load_session, save_session
from swreview.tools.registry import ToolRegistry, session_tools
from tests.support import roles_review
from tests.support.attention import CHECK_FOLDER as ATTENTION_CHECK_FOLDER
from tests.support.contracts import contract_path, contract_validator
from tests.support.features import feature, folder
from tests.support.packages import build_package
from tests.support.remodel import remodel_package
from tests.support.replay import folder_hashes
from tests.support.triage import tally_body
from tests.unit import test_answer_batch_roles as batch_roles
from tests.unit import test_chat_standards_routes as standards
from tests.unit.test_runner_provider import standing

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
    `labels` block, verbatim, with its version, so every word on a card is the backend's.

    *Changed 2026-11-01 on purpose (002 T310; owner decision 185A, FR-031):* the block gains
    the `triage` group, the words of a finding's four triage outcomes.

    *Changed 2026-11-01 on purpose (002 T332; owner decision 187A, FR-031):* and the
    `pass_triage` group, the word of the one outcome a pass takes, the miss.

    *Changed 2026-11-02 on purpose (002 T352; roadmap hole H-c-008, FR-031):* and the
    `no_triage` group, what a flagged finding's card head says until its triage is recorded.

    *Changed 2026-11-02 on purpose (002 T356; cycle 9's Tier 2 review):* and that group's keys,
    with `read_only`, the words such a card says while its review is read-only.

    *Changed 2026-11-02 on purpose (002 T368; cycle 11's Tier 2 review):* and the `note` group,
    what a card says when a late triage keeps the note recorded first in place of the one sent.

    *Changed 2026-11-03 on purpose (002 T388; cycle 17, roadmap hole H-a-009):* and the
    `first_shown` group, the line a card says when an earlier review first showed its finding.

    *Changed 2026-11-03 on purpose (007 T087; cycle 18, minutes typed on the Review page):* and the
    `timing` and `timing_form` groups, the minutes form's words, `timing` keyed by the timing
    route's six body keys in their order.

    *Changed 2026-11-03 on purpose (007 T097; cycle 20, roadmap hole H-a-015):* and `timing_form`'s
    `all_six`, the line under the form's heading that says to type all six, zero for none."""
    from swreview.benchmark.timing import TIMING_INPUTS
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
        "triage",
        "pass_triage",
        "no_triage",
        "note",
        "first_shown",
        "timing",
        "timing_form",
        "errors",
    }
    assert set(body["no_triage"]) == {"undecided", "accepted", "rejected", "deferred", "read_only"}
    assert set(body["note"]) == {"not_kept"}
    assert set(body["first_shown"]) == {"earlier"}
    assert tuple(body["timing"]) == TIMING_INPUTS
    assert set(body["timing_form"]) == {"heading", "all_six", "save", "saved"}
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
    """A second session in the folder would restart `seq` mid-file and lose the first.

    `RunDirTaken`, not `InvalidRunDir` (owner decision 146A): the folder is inside the run root,
    and the path rule's sentence sent the engineer to Settings for a folder that only holds
    another run's files."""
    settle(client, start_session(client, run_dir)["chat_id"])

    response = client.post("/sessions", json=session_body(run_dir))

    assert response.status_code == 400
    assert response.json() == held_session_refusal(run_dir)


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


REMODEL_RUN = "20261019-101500-bracket-remodel"
"""A remodel run's folder in the run root, as `RunFolders.CreateForRemodel` names one."""


def remodel_copy_package() -> EvidencePackage:
    """The `ModelCheck` dump of a remodel run's copy: one core feature and one detail."""
    tree = [
        folder("3-Core", feature("Boss-Extrude1", "Extrusion", description="")),
        folder("4-Detail", feature("Hole1", "HoleWzd")),
    ]
    return remodel_package(tree, document_id="doc:copy", name="bracket-RMS")


def graded_remodel_run(run_root: Path) -> GradedRun:
    """A remodel run that graded its copy before and after: `rms-before/` and `rms-after/`."""
    remodel_run = run_root / REMODEL_RUN
    remodel_run.mkdir()
    package = remodel_copy_package()
    return grade_remodel_run(
        remodel_run, before=package, after=package, source_design_id="dsn:FICT-source"
    )


def grade_check_folder(run_root: Path) -> Path:
    """The re-modeler's grade of the copy at open: `rms-before/` under its remodel run."""
    return graded_remodel_run(run_root).before.check_file.parent


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
    """The one body a check's folder is refused with, by a Retry and by a start alike.

    `RunDirTaken` since owner decision 146A, where 142A answered `InvalidRunDir`: the page shows
    a class's sentence first, and `InvalidRunDir`'s is the path rule's."""
    return {
        "error_class": "RunDirTaken",
        "message": (
            f"{check_dir.resolve()} holds the {family} check that ran in it and no review "
            "session: a Retry replaces only a review's session, and only a Model check's "
            "folder is handed to a new review; review into a new run folder"
        ),
        "retryable": False,
    }


def grade_refusal(grade_dir: Path, side: str) -> dict[str, Any]:
    """The body a start or a Retry meets on a re-modeler grade's folder (owner decision 146A)."""
    folder = grade_dir.resolve()
    return {
        "error_class": "RunDirTaken",
        "message": (
            f"{folder} is the folder of the {side} grade of the remodel run in {folder.parent}: "
            "a review never claims a grade's folder, which only the remodel run writes; review "
            "into a new run folder"
        ),
        "retryable": False,
    }


def held_session_refusal(run_dir: Path) -> dict[str, Any]:
    """A start into a folder that already holds a session and is no check's to hand over.

    "a session", not "a review session" (owner decision 146A): the folder's session is a
    review's as a rule, but it may be a remodel run's, or a check's whose record cannot be read."""
    return {
        "error_class": "RunDirTaken",
        "message": (
            f"{run_dir.resolve()} already holds a session that a start does not write over: "
            "review into a new run folder, or retry the chat that wrote it with 'retry_of'"
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


@pytest.mark.parametrize("kind", list(CHECK_FOLDERS))
def test_session_replaced_tells_a_check_s_own_session_from_one_in_its_place(
    run_root: Path, kind: str
) -> None:
    """What `GET /reviews` asks of a folder holding `check.json` (owner decision 146A): the
    check's own session is not replaced, and another session in its place - a review's, which
    moved the check's aside - is, whatever the family. It answers `is_check_folder`'s question
    the other way round only where both records can be read."""
    _, build = CHECK_FOLDERS[kind]
    check_dir = build(run_root)
    assert (session_replaced(check_dir), is_check_folder(check_dir)) == (False, True)

    session = load_session(check_dir / "session.json")
    save_session(session.model_copy(update={"session_id": uuid4()}), check_dir / "session.json")

    assert (session_replaced(check_dir), is_check_folder(check_dir)) == (True, False)


@pytest.mark.parametrize(
    "broken",
    [
        "no record",
        "an unreadable record",
        "a record that is no object",
        "a record naming no session",
        "no session",
        "an unreadable session",
    ],
)
def test_session_replaced_guesses_nothing_where_a_record_cannot_be_read(
    check_run_dir: Path, broken: str
) -> None:
    """A session in the check's place, then each way the folder can fail to show whose it is:
    every one answers no, so `GET /reviews` restores nothing it cannot show is a review's. A
    record that names no session read as one naming another before 146A ("the record describes
    session None"); it is a record that cannot be read now, to every caller alike."""
    session = load_session(check_run_dir / "session.json")
    save_session(session.model_copy(update={"session_id": uuid4()}), check_run_dir / "session.json")
    assert session_replaced(check_run_dir)
    record = check_run_dir / "check.json"
    if broken == "no record":
        record.unlink()
    elif broken == "an unreadable record":
        record.write_text("{ not json", encoding="utf-8")
    elif broken == "a record that is no object":
        record.write_text("[]", encoding="utf-8")
    elif broken == "a record naming no session":
        body = json.loads(record.read_text(encoding="utf-8"))
        del body["session_id"]
        record.write_text(json.dumps(body), encoding="utf-8")
    elif broken == "no session":
        (check_run_dir / "session.json").unlink()
    else:
        (check_run_dir / "session.json").write_text("{ not json", encoding="utf-8")

    assert not session_replaced(check_run_dir)
    assert not is_check_folder(check_run_dir)


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
    this backend holds and an id it never issued meet the same 400.

    A grade's folder is refused with the grade's words since owner decision 146A, which a
    start meets too, where 142A refused it as any check's."""
    family, build = CHECK_FOLDERS[kind]
    reviewed = start_session(client, run_dir)
    settle(client, reviewed["chat_id"])
    check_dir = build(run_root)
    before = folder_hashes(check_dir)
    built = len(provider_control.built)
    retry_of = reviewed["chat_id"] if named == "a chat this backend holds" else str(uuid4())

    response = client.post("/sessions", json=session_body(check_dir, retry_of=retry_of))

    assert response.status_code == 400
    assert response.json() == (
        grade_refusal(check_dir, "before")
        if kind == "re-modeler grade"
        else check_folder_refusal(check_dir, family)
    )
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


def test_a_start_still_claims_a_model_check_s_folder(client: TestClient, run_root: Path) -> None:
    """Unchanged by 142A and 146A. Feature 003's User Story 6 scenario 11 hands a Model check's
    folder to a review, which rotates the check's session aside (feature 007 FR-021). Its case
    for the re-modeler's grade, which a start claimed as the same rms record, is gone: owner
    decision 146A refuses a grade's folder to every start (below)."""
    check_dir = model_check_folder(run_root)
    check_session = load_session(check_dir / "session.json").session_id

    settle(client, start_session(client, check_dir)["chat_id"])

    assert load_session(check_dir / "session.1.json").session_id == check_session
    assert load_session(check_dir / "session.json").session_id != check_session


# --- a review never claims a re-modeler grade's folder (owner decision 146A) ---------------


@pytest.mark.parametrize("side", ["before", "after"])
def test_a_start_on_a_re_modeler_grade_s_folder_is_refused_and_moves_nothing(
    app: Any, client: TestClient, run_root: Path, provider_control: ProviderControl, side: str
) -> None:
    """A grade's `check.json` is `run_rms_check`'s own rms record, so 142A's rule took the folder
    for a Model check's and a start claimed it: the grade's session went aside, the review
    wrote over the grade's `report.md`, and the run's `rms-<side>.json` then named the review's
    files. A grade is its remodel run's, and nothing in the run's folder moves."""
    graded = graded_remodel_run(run_root)
    grade_dir = getattr(graded, side).check_file.parent
    before = folder_hashes(graded.run_dir)

    response = client.post("/sessions", json=session_body(grade_dir))

    assert response.status_code == 400
    assert response.json() == grade_refusal(grade_dir, side)
    assert folder_hashes(graded.run_dir) == before
    named = json.loads((graded.run_dir / f"rms-{side}.json").read_text(encoding="utf-8"))
    assert load_session(graded.run_dir / named["session"]).session_id == (
        getattr(graded, side).session.session_id
    )
    assert app.state.server.chats == {}
    assert provider_control.built == []


def test_a_grade_s_folder_is_refused_before_its_grade_is_written(
    app: Any, client: TestClient, run_root: Path, provider_control: ProviderControl
) -> None:
    """`grade_remodel_run` files a side's dump in the grade's folder, and beside it, before it
    grades anything. Until the grade's session was written the folder held none, so a start
    claimed it - and the grade would then have written its own session and report over the
    review's. A grade's folder is refused whatever it holds."""
    remodel_run = run_root / REMODEL_RUN
    remodel_run.mkdir()
    write_package(remodel_run, remodel_copy_package(), side="before")
    grade_dir = remodel_run / "rms-before"
    before = folder_hashes(remodel_run)

    response = client.post("/sessions", json=session_body(grade_dir))

    assert response.status_code == 400
    assert response.json() == grade_refusal(grade_dir, "before")
    assert folder_hashes(remodel_run) == before
    assert app.state.server.chats == {}
    assert provider_control.built == []


def test_a_model_check_s_folder_named_like_a_grade_s_is_still_claimed(
    client: TestClient, run_root: Path
) -> None:
    """A grade's folder is told by its remodel run's layout - its side's dump filed beside it -
    and neither by its record, which is a Model check's too, nor by its name alone: a Model
    check's folder called `rms-before` in the run root is handed to a review as any is."""
    check_dir = run_root / "rms-before"
    shutil.copytree(ATTENTION_CHECK_FOLDER, check_dir)
    check_session = load_session(check_dir / "session.json").session_id

    settle(client, start_session(client, check_dir)["chat_id"])

    assert load_session(check_dir / "session.1.json").session_id == check_session


def test_a_re_run_naming_a_grade_s_folder_is_refused_as_no_waiting_review(
    client: TestClient, run_root: Path
) -> None:
    """A re-run (`recheck`, feature 015) re-runs a waiting review in its own folder, so the
    grade's refusal is not asked of it: the grade's session waits for nothing, and the re-run
    is refused `NotWaiting` with nothing moved, as before 146A."""
    graded = graded_remodel_run(run_root)
    grade_dir = graded.before.check_file.parent
    before = folder_hashes(graded.run_dir)

    response = client.post(
        "/sessions", json=session_body(grade_dir, send_when_checked=False, recheck=True)
    )

    assert response.status_code == 409
    assert response.json()["error_class"] == "NotWaiting"
    assert folder_hashes(graded.run_dir) == before


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
    """The start's refusal is `RunDirTaken` with words true of any session (owner decision
    146A), where 142A pinned `InvalidRunDir` and "already holds a review session"."""
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])

    response = client.post("/sessions", json=session_body(run_dir, retry_of=""))

    assert response.status_code == 400
    assert response.json() == held_session_refusal(run_dir)


@pytest.mark.parametrize("record", ["not json", "names no session"])
def test_a_start_on_a_check_s_folder_whose_record_cannot_be_read_is_told_it_holds_a_session(
    client: TestClient, check_run_dir: Path, provider_control: ProviderControl, record: str
) -> None:
    """A check's folder whose `check.json` cannot show whose its session is, is no check's folder
    (`is_check_folder`), so a start meets the refusal for any folder that holds a session. The
    session there is the check's, not a review's, so the words name a session and no review
    (owner decision 146A); and nothing is guessed through, so nothing moves."""
    check_file = check_run_dir / "check.json"
    if record == "not json":
        check_file.write_text("{ not json", encoding="utf-8")
    else:
        body = json.loads(check_file.read_text(encoding="utf-8"))
        del body["session_id"]
        check_file.write_text(json.dumps(body), encoding="utf-8")
    before = folder_hashes(check_run_dir)

    response = client.post("/sessions", json=session_body(check_run_dir))

    assert response.status_code == 400
    assert response.json() == held_session_refusal(check_run_dir)
    assert folder_hashes(check_run_dir) == before
    assert provider_control.built == []


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


# --- a finding's triage beside its decision (002 T310, owner decision 185A) --------------------


def disposition_url(chat_id: str, run_dir: Path) -> str:
    """The disposition route of the chat's one finding."""
    finding_id = load_session(run_dir / "session.json").findings[0].id
    return f"/sessions/{chat_id}/findings/{finding_id}/disposition"


def recorded_dispositions(run_dir: Path) -> list[dict[str, Any]]:
    """Each `disposition` event's disposition, in the order the stream carried them."""
    return [
        event["body"]["disposition"]
        for event in events_of(run_dir)
        if event["type"] == "disposition"
    ]


def folder_files(run_dir: Path) -> dict[str, bytes]:
    """The three files a disposition writes, by name: what a refusal must leave as it was."""
    return {
        name: (run_dir / name).read_bytes()
        for name in ("session.json", "report.md", "events.jsonl")
    }


def test_a_disposition_records_its_triage_and_answers_it(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """*Changed 2026-11-01 on purpose (002 T314):* `report.md` shows the triage's words under
    the decision, once T315 renders them."""
    response = client.post(
        disposition_url(chat_with_a_finding, run_dir),
        json={
            "decision": "rejected",
            "note": "FICT note",
            "by": "FICT-ENG",
            "triage": "already_known",
        },
    )

    assert response.status_code == 200, response.text
    answered = response.json()["disposition"]
    assert (answered["decision"], answered["note"], answered["by"], answered["triage"]) == (
        "rejected",
        "FICT note",
        "FICT-ENG",
        "already_known",
    )
    saved = load_session(run_dir / "session.json").findings[0].disposition
    assert saved is not None and saved.model_dump(mode="json") == answered
    assert recorded_dispositions(run_dir) == [answered]
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "  - decision: rejected\n  - triage: real but already known\n" in report


def test_a_triage_outside_the_four_is_a_400_and_writes_nothing(
    client: TestClient,
    run_dir: Path,
    chat_with_a_finding: str,
    provider_control: ProviderControl,
) -> None:
    """Refused before the chat's state is read, so never `409 IllegalTransition` or
    `TurnRunning`: idle, and again while a turn runs. Null, or no key, records none."""
    url = disposition_url(chat_with_a_finding, run_dir)
    outside: tuple[Any, ...] = ("maybe", "", 3, True, [])
    before = folder_files(run_dir)

    def post(value: Any) -> Any:
        body = {"decision": "accepted", "note": "", "by": "FICT-ENG", "triage": value}
        return client.post(url, json=body)

    idle = [post(value) for value in outside]
    written = folder_files(run_dir)
    provider_control.hold()
    client.post(f"/sessions/{chat_with_a_finding}/messages", json={"text": "keep going"})
    wait_until(provider_control.started.is_set, "the follow-up turn to reach the gate")
    running = [post(value) for value in outside]
    provider_control.release()
    settle(client, chat_with_a_finding)

    refusals = [(response.status_code, response.json()["error_class"]) for response in idle]
    assert refusals == [(400, "InvalidTriage")] * len(outside)
    assert [(response.status_code, response.json()["error_class"]) for response in running] == (
        refusals
    )
    assert written == before
    assert load_session(run_dir / "session.json").findings[0].disposition is None
    assert recorded_dispositions(run_dir) == []

    deferred = client.post(
        url, json={"decision": "deferred", "note": "", "by": "FICT-ENG", "triage": None}
    )
    accepted = client.post(url, json={"decision": "accepted", "note": "", "by": "FICT-ENG"})

    assert [response.status_code for response in (deferred, accepted)] == [200, 200]
    assert ["triage" in response.json()["disposition"] for response in (deferred, accepted)] == [
        False,
        False,
    ]


def test_a_late_triage_records_the_triage_and_nothing_else(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """185A: an Accept recorded without a triage takes one once, sent with the same decision;
    the note, `by` and `at` stay as first recorded. A different decision, or a second triage,
    is refused as any change to a settled finding is.

    *Changed 2026-11-01 on purpose (002 T314):* `report.md` shows the late triage's words too.

    *Changed 2026-11-01 on purpose (002 T320; roadmap hole H-g-012):* a second triage, the same
    or another, is `409 TriageAlreadyRecorded`, a class of its own whose sentence says the triage
    recorded stands, where it was `IllegalTransition`, whose sentence reads as a refused decision;
    a different decision stays `IllegalTransition`."""
    url = disposition_url(chat_with_a_finding, run_dir)
    first = client.post(
        url, json={"decision": "accepted", "note": "FICT first note", "by": "FICT-ENG"}
    ).json()["disposition"]

    late = client.post(
        url,
        json={
            "decision": "accepted",
            "note": "FICT later note",
            "by": "FICT-ENG-2",
            "triage": "already_known",
        },
    )

    assert late.status_code == 200, late.text
    recorded = {**first, "triage": "already_known"}
    assert late.json()["disposition"] == recorded
    saved = load_session(run_dir / "session.json").findings[0].disposition
    assert saved is not None and saved.model_dump(mode="json") == recorded
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "FICT first note" in report and "FICT later note" not in report
    assert "  - decision: accepted\n  - triage: real but already known\n" in report
    assert recorded_dispositions(run_dir) == [first, recorded]

    before = folder_files(run_dir)
    refused = [
        client.post(
            url, json={"decision": decision, "note": "", "by": "FICT-ENG", "triage": triage}
        )
        for decision, triage in (
            ("rejected", "wrong"),
            ("accepted", "wrong"),
            ("accepted", "already_known"),
        )
    ]

    assert [(response.status_code, response.json()["error_class"]) for response in refused] == [
        (409, "IllegalTransition"),
        (409, "TriageAlreadyRecorded"),
        (409, "TriageAlreadyRecorded"),
    ]
    assert folder_files(run_dir) == before


def test_a_deferred_finding_takes_a_late_triage_and_a_note_on_the_live_route(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """Owner decision 198A (002 T364), through the route the pane presses: a Defer recorded with
    no triage and no note, sent again with an outcome and a note - such as 188A's date - records
    both and stays deferred, its `by` and `at` as first recorded, and the reply, `session.json`,
    `report.md` and the `disposition` event all say so. A Defer again with no triage is still
    `409 IllegalTransition`, and writes nothing.

    *Changed 2026-11-03 on purpose (002 T376; roadmap hole H-c-010):* that Defer again with no
    triage is still refused and writes nothing, but as `409 OutcomeNeeded`, whose sentence says to
    pick an outcome first, where `IllegalTransition`'s says to reload the review
    (`test_the_same_decision_again_without_an_outcome_is_a_409_of_its_own`)."""
    url = disposition_url(chat_with_a_finding, run_dir)
    first = client.post(url, json={"decision": "deferred", "note": "", "by": "FICT-ENG"}).json()[
        "disposition"
    ]
    before = folder_files(run_dir)

    again = client.post(url, json={"decision": "deferred", "note": "", "by": "FICT-ENG"})

    assert (again.status_code, again.json()["error_class"]) == (409, "OutcomeNeeded")
    assert folder_files(run_dir) == before

    late = client.post(
        url,
        json={
            "decision": "deferred",
            "note": "FICT first shown at an earlier sitting",
            "by": "FICT-ENG-2",
            "triage": "new_and_real",
        },
    )

    assert late.status_code == 200, late.text
    recorded = {**first, "note": "FICT first shown at an earlier sitting", "triage": "new_and_real"}
    assert late.json()["disposition"] == recorded
    saved = load_session(run_dir / "session.json").findings[0].disposition
    assert saved is not None and saved.model_dump(mode="json") == recorded
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "  - decision: deferred\n  - triage: new and real\n" in report
    assert "  - note: FICT first shown at an earlier sitting\n" in report
    assert recorded_dispositions(run_dir) == [first, recorded]


def test_a_second_triage_is_a_409_of_its_own_and_writes_nothing(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """Roadmap hole H-g-012 (185A unchanged): a finding rejected with a triage is refused a
    second one - another, or the same again - as `409 TriageAlreadyRecorded`, not retryable, its
    message naming the triage recorded, so the page can say the recorded one stands. Every other
    refusal stays `409 IllegalTransition`: an Accept, with a triage or without, a Reject with none
    and a Defer. None of them writes anything.

    *Changed 2026-11-03 on purpose (002 T402; cycle 23):* the Reject sent again with none, its
    triage let go, is `409 DecisionAlreadyRecorded`, a class of its own whose sentence says the
    decision is already recorded, where `IllegalTransition`'s said to reload the review; a
    different decision, an Accept or a Defer, stays `IllegalTransition`."""
    url = disposition_url(chat_with_a_finding, run_dir)
    first = client.post(
        url,
        json={"decision": "rejected", "note": "FICT note", "by": "FICT-ENG", "triage": "wrong"},
    )
    assert first.status_code == 200, first.text
    before = folder_files(run_dir)

    refused = [
        client.post(
            url, json={"decision": decision, "note": "", "by": "FICT-ENG", "triage": triage}
        )
        for decision, triage in (
            ("rejected", "already_known"),
            ("rejected", "wrong"),
            ("accepted", "wrong"),
            ("accepted", None),
            ("rejected", None),
            ("deferred", "wrong"),
        )
    ]

    assert [(response.status_code, response.json()["error_class"]) for response in refused] == [
        (409, "TriageAlreadyRecorded"),
        (409, "TriageAlreadyRecorded"),
        (409, "IllegalTransition"),
        (409, "IllegalTransition"),
        (409, "DecisionAlreadyRecorded"),
        (409, "IllegalTransition"),
    ]
    assert [response.json()["retryable"] for response in refused] == [False] * len(refused)
    assert "with its triage ('wrong')" in refused[0].json()["message"]
    assert folder_files(run_dir) == before


def test_the_same_decision_again_without_an_outcome_is_a_409_of_its_own(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """Roadmap hole H-c-010 (002 T376), through the route the pane presses: the decision recorded
    without a triage, sent again with none - a Defer, then the Accept that follows it - is
    `409 OutcomeNeeded`, a class of its own (the record's `OutcomeNeededError`), not retryable,
    its message naming the repair, so the page can say to pick an outcome first, where
    `IllegalTransition`'s sentence says to reload the review and a reload loses the note typed for
    the retry; neither writes anything. Once the Accept takes its late triage, an Accept again
    with none is `409 IllegalTransition`, as before.

    *Changed 2026-11-03 on purpose (002 T402; cycle 23):* that Accept again with none, its triage
    recorded, is `409 DecisionAlreadyRecorded`, whose sentence says the decision is already
    recorded, where `IllegalTransition`'s said to reload the review; it still writes nothing."""
    url = disposition_url(chat_with_a_finding, run_dir)
    pressed = {"note": "FICT first shown at an earlier sitting", "by": "FICT-ENG"}
    deferred = client.post(url, json={"decision": "deferred", "note": "", "by": "FICT-ENG"})
    assert deferred.status_code == 200, deferred.text
    before_defer = folder_files(run_dir)
    defer_again = client.post(url, json={"decision": "deferred", **pressed})
    after_defer = folder_files(run_dir)
    accepted = client.post(url, json={"decision": "accepted", "note": "", "by": "FICT-ENG"})
    assert accepted.status_code == 200, accepted.text
    before_accept = folder_files(run_dir)

    accept_again = client.post(url, json={"decision": "accepted", **pressed})

    refused = [defer_again, accept_again]
    assert [(response.status_code, response.json()["error_class"]) for response in refused] == [
        (409, "OutcomeNeeded"),
        (409, "OutcomeNeeded"),
    ]
    assert [response.json()["retryable"] for response in refused] == [False, False]
    assert [response.json()["message"] for response in refused] == [
        "finding F-001 is deferred with no triage recorded; send 'deferred' again with a triage "
        "to record one",
        "finding F-001 is accepted with no triage recorded; send 'accepted' again with a triage "
        "to record one",
    ]
    assert after_defer == before_defer
    assert folder_files(run_dir) == before_accept

    late = client.post(url, json={"decision": "accepted", "triage": "new_and_real", **pressed})
    assert late.status_code == 200, late.text
    triaged = folder_files(run_dir)
    again = client.post(url, json={"decision": "accepted", **pressed})

    assert (again.status_code, again.json()["error_class"]) == (409, "DecisionAlreadyRecorded")
    assert folder_files(run_dir) == triaged


def test_a_defer_again_on_one_that_holds_a_triage_says_what_its_later_decision_does(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """Cycle 15's Tier 2 review, through the route the pane presses: a deferred card that holds a
    triage shows it pressed, so Defer pressed again sends it - with a note typed, such as 188A's
    date. That is `409 IllegalTransition`, as 198A kept it (002 research, H-c-009), and so is
    another triage or none: `TriageAlreadyRecorded`'s sentence says a triage is recorded only
    once, which is untrue of a Defer, whose triage a later Accept or Reject replaces. Each message
    names the triage recorded, and nothing is written.

    *Changed 2026-11-03 on purpose (a read-only check of the review's fixes):* renamed from
    `test_a_defer_again_with_a_triage_on_one_that_holds_one_is_a_second_triage`, whose two posts
    with a triage were `409 TriageAlreadyRecorded`, the review's change, which reversed that
    default unsaid; `IllegalTransition`'s sentence, which says to reload, is H-c-010's *Left
    open*.

    *Changed 2026-11-03 on purpose (002 T402; cycle 23):* renamed from
    `test_a_defer_again_on_one_that_holds_a_triage_is_still_an_illegal_transition`. Each is
    `409 AlreadyDeferred`, a class of its own (the record's `AlreadyDeferredError`), not
    retryable, whose sentence says what the later Accept or Reject does, where
    `IllegalTransition`'s said to reload the review; each message says it too."""
    url = disposition_url(chat_with_a_finding, run_dir)
    deferred = client.post(
        url, json={"decision": "deferred", "note": "", "by": "FICT-ENG", "triage": "wrong"}
    )
    assert deferred.status_code == 200, deferred.text
    before = folder_files(run_dir)
    pressed = {"decision": "deferred", "note": "FICT first shown at an earlier sitting"}

    refused = [
        client.post(url, json={**pressed, "by": "FICT-ENG", "triage": triage})
        for triage in ("wrong", "already_known", None)
    ]

    assert [(response.status_code, response.json()["error_class"]) for response in refused] == [
        (409, "AlreadyDeferred")
    ] * 3
    assert [response.json()["retryable"] for response in refused] == [False] * 3
    assert [response.json()["message"] for response in refused] == [
        "finding F-001 is deferred with its triage ('wrong'); it can only move to accepted or "
        "rejected, not 'deferred' again, and either keeps that triage unless it names another"
    ] * 3
    assert folder_files(run_dir) == before


def test_a_pass_takes_no_triage_but_wrong_on_the_live_route(
    app: Any,
    client: TestClient,
    run_dir: Path,
    chat_with_a_finding: str,
    provider_control: ProviderControl,
) -> None:
    """Owner decision 187A (002 T332, FR-031): on a pass - 'Checked, no issue' - any triage but
    `wrong` is `400 InvalidTriage`, its message naming the pass, refused before the chat's state is
    read, as a triage outside the four is: idle, and again while a turn runs, so never
    `409 TurnRunning`; nothing is written. `wrong`, the miss, passes that check - while a turn runs
    it meets the turn, as any decision does - and is recorded. The chat's one finding is made a
    pass in the session the run holds, which is the session the route reads."""
    run = app.state.server.chats[UUID(chat_with_a_finding)].run
    run.session.findings[0] = run.session.findings[0].model_copy(
        update={"status": "checked_within_scope", "severity": "info"}
    )
    url = disposition_url(chat_with_a_finding, run_dir)
    others = [triage for triage in TRIAGES if triage != "wrong"]
    before = folder_files(run_dir)

    def post(triage: str) -> Any:
        body = {"decision": "rejected", "note": "", "by": "FICT-ENG", "triage": triage}
        return client.post(url, json=body)

    idle = [post(triage) for triage in others]
    written = folder_files(run_dir)
    provider_control.hold()
    client.post(f"/sessions/{chat_with_a_finding}/messages", json={"text": "keep going"})
    wait_until(provider_control.started.is_set, "the follow-up turn to reach the gate")
    running = [post(triage) for triage in others]
    miss_while_running = post("wrong")
    provider_control.release()
    settle(client, chat_with_a_finding)

    refusals = [(response.status_code, response.json().get("error_class")) for response in idle]
    assert refusals == [(400, "InvalidTriage")] * len(others)
    assert [(response.status_code, response.json()["error_class"]) for response in running] == (
        refusals
    )
    assert all("is a pass" in response.json()["message"] for response in idle)
    assert (miss_while_running.status_code, miss_while_running.json()["error_class"]) == (
        409,
        "TurnRunning",
    )
    assert written == before
    assert recorded_dispositions(run_dir) == []

    miss = post("wrong")

    assert miss.status_code == 200, miss.text
    assert miss.json()["disposition"]["triage"] == "wrong"
    saved = load_session(run_dir / "session.json").findings[0]
    assert saved.status == "checked_within_scope"
    assert saved.disposition is not None and saved.disposition.triage == "wrong"


def test_a_pass_accepted_again_without_an_outcome_says_it_is_already_recorded(
    app: Any, client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """Cycle 15's Tier 2 review, through the route the pane presses: a pass accepted with no
    triage, Accept pressed again with none - a note typed meanwhile, or a double click - is
    `409 IllegalTransition`, as before H-c-010, not `409 OutcomeNeeded`, whose sentence asks for
    an outcome where the pass's card offers only the miss; nothing is written. The chat's one
    finding is made a pass in the session the run holds, which is the session the route reads.

    *Changed 2026-11-03 on purpose (002 T402; cycle 23):* renamed from
    `test_a_pass_accepted_again_without_an_outcome_is_still_an_illegal_transition`. The press is
    `409 DecisionAlreadyRecorded`, a class of its own (the record's
    `DecisionAlreadyRecordedError`), not retryable, whose sentence says the decision is already
    recorded, where `IllegalTransition`'s said to reload the review; its message says so, and the
    body names the disposition recorded, which the page draws the card's record from."""
    run = app.state.server.chats[UUID(chat_with_a_finding)].run
    run.session.findings[0] = run.session.findings[0].model_copy(
        update={"status": "checked_within_scope", "severity": "info"}
    )
    url = disposition_url(chat_with_a_finding, run_dir)
    accepted = client.post(url, json={"decision": "accepted", "note": "", "by": "FICT-ENG"})
    assert accepted.status_code == 200, accepted.text
    before = folder_files(run_dir)

    again = client.post(
        url, json={"decision": "accepted", "note": "FICT typed note", "by": "FICT-ENG"}
    )

    assert (again.status_code, again.json()["error_class"]) == (409, "DecisionAlreadyRecorded")
    assert again.json()["retryable"] is False
    assert again.json()["message"] == (
        "finding F-001 is already accepted; 'accepted' again with no triage changes nothing"
    )
    assert again.json()["disposition"] == accepted.json()["disposition"]
    assert folder_files(run_dir) == before


def test_each_refusal_of_the_record_names_the_disposition_as_it_stands(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """002 T402 (cycle 23), through the route the pane presses: every refusal the record makes
    names the finding's disposition as the record holds it, `disposition` beside `error_class`,
    `message` and `retryable`, so the page draws the card's record from the backend's and not from
    a memory that another client's decision may have overtaken once its stream closed. A Defer
    with no triage, then with one, then an Accept, each recorded by one client, and each press of
    another refused in turn: Defer again with none (`OutcomeNeeded`), Defer again on the Defer
    that holds a triage (`AlreadyDeferred`), a Reject on the Accept (`IllegalTransition`, its
    message as before), another triage on it (`TriageAlreadyRecorded`) and the Accept again with
    none (`DecisionAlreadyRecorded`). None is retryable or writes anything. A refusal that is not
    the record's - an unknown finding, a decision or a triage the route does not know - names no
    disposition."""
    url = disposition_url(chat_with_a_finding, run_dir)
    elsewhere = {"note": "FICT decided elsewhere", "by": "FICT-ENG-2"}
    typed = {"note": "FICT typed note", "by": "FICT-ENG"}
    refusals: list[tuple[Any, dict[str, Any]]] = []

    def record(**press: Any) -> dict[str, Any]:
        reply = client.post(url, json={**elsewhere, **press})
        assert reply.status_code == 200, reply.text
        disposition: dict[str, Any] = reply.json()["disposition"]
        return disposition

    def refuse(recorded: dict[str, Any], **press: Any) -> None:
        before = folder_files(run_dir)
        refusals.append((client.post(url, json={**typed, **press}), recorded))
        assert folder_files(run_dir) == before

    deferred = record(decision="deferred")
    refuse(deferred, decision="deferred")
    triaged = record(decision="deferred", triage="wrong")
    refuse(triaged, decision="deferred", triage="wrong")
    accepted = record(decision="accepted")
    refuse(accepted, decision="rejected", triage="new_and_real")
    refuse(accepted, decision="accepted", triage="already_known")
    refuse(accepted, decision="accepted")

    assert [(response.status_code, response.json()["error_class"]) for response, _ in refusals] == [
        (409, "OutcomeNeeded"),
        (409, "AlreadyDeferred"),
        (409, "IllegalTransition"),
        (409, "TriageAlreadyRecorded"),
        (409, "DecisionAlreadyRecorded"),
    ]
    assert [response.json()["retryable"] for response, _ in refusals] == [False] * 5
    assert [response.json()["disposition"] for response, _ in refusals] == [
        recorded for _, recorded in refusals
    ]
    assert accepted == {**triaged, "decision": "accepted", "at": accepted["at"]}
    assert refusals[2][0].json()["message"] == (
        "finding F-001 already has a terminal disposition ('accepted'); it cannot be changed"
    )

    finding_id = load_session(run_dir / "session.json").findings[0].id
    others = [
        client.post(url.replace(finding_id, "F-404"), json={"decision": "rejected", **typed}),
        client.post(url, json={"decision": "approved", **typed}),
        client.post(url, json={"decision": "rejected", "triage": "maybe", **typed}),
    ]

    assert [(response.status_code, response.json()["error_class"]) for response in others] == [
        (404, "UnknownFinding"),
        (400, "InvalidDecision"),
        (400, "InvalidTriage"),
    ]
    assert all("disposition" not in response.json() for response in others)


def test_a_refusal_of_the_record_carries_the_tally_as_the_reply_does(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    """Cycle 23's Tier 2 review (002 T404), through the route the pane presses: a refusal of the
    record carries the review's triage tally beside the disposition, as the 200 reply does
    (`with_triage_tally`) - none while no finding records a triage, the review's one count once one
    does - so the card a refusal draws comes with the tally the record leaves, which nothing else
    tells the page once the session's end has closed its stream. An Accept with no triage, pressed
    again with none (`OutcomeNeeded`), carries none. An Accept as `new_and_real`, recorded though
    its reply was lost - the proxy's `502 BackendUnavailable` - then pressed again as the engineer
    would (`TriageAlreadyRecorded`), and a Reject on it (`IllegalTransition`), carry the tally that
    Accept left, its reply's. A refusal that is not the record's carries none."""
    findings = load_session(run_dir / "session.json").findings
    flagged = [finding.id for finding in findings if finding.status != "checked_within_scope"]
    url = f"/sessions/{chat_with_a_finding}/findings/{flagged[0]}/disposition"
    typed = {"note": "FICT typed note", "by": "FICT-ENG"}

    plain = client.post(url, json={"decision": "accepted", **typed})
    untriaged = client.post(url, json={"decision": "accepted", **typed})
    lost = client.post(url, json={"decision": "accepted", "triage": "new_and_real", **typed})
    again = client.post(url, json={"decision": "accepted", "triage": "new_and_real", **typed})
    other = client.post(url, json={"decision": "rejected", **typed})
    unknown = client.post(url.replace(flagged[0], "F-404"), json={"decision": "rejected", **typed})

    assert [response.status_code for response in (plain, lost)] == [200, 200]
    assert [
        (response.status_code, response.json()["error_class"])
        for response in (untriaged, again, other, unknown)
    ] == [
        (409, "OutcomeNeeded"),
        (409, "TriageAlreadyRecorded"),
        (409, "IllegalTransition"),
        (404, "UnknownFinding"),
    ]
    tally = tally_body(new=1, not_recorded=len(flagged) - 1)
    assert lost.json()["triage_tally"] == tally
    assert [again.json()["triage_tally"], other.json()["triage_tally"]] == [tally, tally]
    assert again.json()["disposition"] == other.json()["disposition"] == lost.json()["disposition"]
    assert "triage_tally" not in untriaged.json()
    assert "triage_tally" not in unknown.json()


# --- a check run again after an answer (002 T326; owner decisions 189A and 191A) ------------------


@pytest.mark.parametrize(
    ("rerun_status", "kept", "recorded", "by_triage"),
    [
        (
            "suspected",
            True,
            ["- Disposition:", "  - decision: accepted", "  - triage: real but already known"],
            [
                "- By triage: new and real: 0, real but already known: 1, wrong: 0, "
                "true but not worth flagging: 0, not recorded: {others}"
            ],
        ),
        ("unresolved", False, ["- Disposition: not yet dispositioned"], []),
    ],
    ids=["kept", "cleared"],
)
def test_the_saved_session_and_report_agree_with_the_fold(
    client: TestClient,
    run_dir: Path,
    provider_control: ProviderControl,
    rerun_status: str,
    kept: bool,
    recorded: list[str],
    by_triage: list[str],
) -> None:
    """Owner decisions 189A and 191A, through the live routes: the review's drawing finding is
    accepted as `already_known` while its question is open, the question is answered, and the
    resumed turn records the finding again - with the status and severity decided (`suspected`,
    medium) or with others (`unresolved`, low). What the server writes once that turn ends is the
    fold: `session.json` holds the folded finding with the decision kept whole or cleared, the
    `report.md` it renders shows the decision and its triage and counts it by triage when kept,
    and neither when cleared, and the stream says `disposition.cleared` only when it was cleared.
    The checks run first and record findings of their own, which nobody decides."""
    provider_control.script = [
        turn(
            "I need the thread depth.",
            call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS),
            call("request_evidence", **EVIDENCE_ARGUMENTS),
        ),
        turn(
            "Ran it again.",
            call("record_drawing_finding", **{**DRAWING_FINDING_ARGUMENTS, "status": rerun_status}),
        ),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    assert settle(client, chat_id) == ChatState.WAITING_ENGINEER.value
    [drawing] = [
        finding.id
        for finding in load_session(run_dir / "session.json").findings
        if finding.check == MODEL_FINDING_CHECK
    ]
    decided = client.post(
        f"/sessions/{chat_id}/findings/{drawing}/disposition",
        json={
            "decision": "accepted",
            "note": "FICT intended",
            "by": "FICT-ENG",
            "triage": "already_known",
        },
    )
    assert decided.status_code == 200, decided.text

    answered = client.post(f"/sessions/{chat_id}/evidence/ER-001", json={"answer": "12 mm."})

    assert answered.status_code == 202, answered.text
    assert settle(client, chat_id) == ChatState.ENDED.value
    saved = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))["findings"]
    assert [
        (finding["id"], finding["status"], finding["disposition"])
        for finding in saved
        if finding["check"] == MODEL_FINDING_CHECK
    ] == [(drawing, rerun_status, decided.json()["disposition"] if kept else None)]
    lines = (run_dir / "report.md").read_text(encoding="utf-8").splitlines()
    heading = lines.index(next(line for line in lines if line.startswith(f"#### {drawing}:")))
    disposition = next(
        index for index in range(heading, len(lines)) if lines[index].startswith("- Disposition:")
    )
    assert lines[disposition : disposition + len(recorded)] == recorded
    assert [line for line in lines if line.startswith("- By triage:")] == [
        line.format(others=len(saved) - 1) for line in by_triage
    ]
    assert types_of(run_dir).count("disposition.cleared") == (0 if kept else 1)


def test_the_live_and_the_restored_snapshot_carry_a_cleared_line_until_a_decision(
    client: TestClient,
    run_root: Path,
    run_dir: Path,
    provider_control: ProviderControl,
    models: Models,
) -> None:
    """Owner decision 193A (002 T340), through the routes: a re-run after an answer cleared the
    drawing finding's Accept. The live snapshot - what a reload or a review switch reads - and the
    run folder's, read by a backend started again on the same run root - what a restart and a
    read-only restore read - both name its line, the `disposition.cleared` body the stream holds.
    Once the engineer decides again, neither does.

    *Changed 2026-11-02 on purpose (002 T370; cycle 13):* the read-only restore's buttons are off,
    so the run folder's snapshot names the line without the call to decide again, where it named
    the stream's words; the live snapshot names them as written."""
    provider_control.script = [
        turn(
            "I need the thread depth.",
            call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS),
            call("request_evidence", **EVIDENCE_ARGUMENTS),
        ),
        turn(
            "Ran it again.",
            call("record_drawing_finding", **{**DRAWING_FINDING_ARGUMENTS, "status": "unresolved"}),
        ),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    assert settle(client, chat_id) == ChatState.WAITING_ENGINEER.value
    [drawing] = [
        finding.id
        for finding in load_session(run_dir / "session.json").findings
        if finding.check == MODEL_FINDING_CHECK
    ]
    decided = client.post(
        f"/sessions/{chat_id}/findings/{drawing}/disposition",
        json={"decision": "accepted", "note": "FICT intended", "triage": "already_known"},
    )
    assert decided.status_code == 200, decided.text
    answered = client.post(f"/sessions/{chat_id}/evidence/ER-001", json={"answer": "12 mm."})
    assert answered.status_code == 202, answered.text
    assert settle(client, chat_id) == ChatState.ENDED.value
    line = [
        {
            "finding_id": drawing,
            "disposition": decided.json()["disposition"],
            "reason": (
                "The check ran again after your answer and its verdict changed, so your Accept "
                "(real but already known) was cleared. Decide again."
            ),
        }
    ]

    def restored() -> dict[str, Any]:
        """The run folder's snapshot, read by a backend started again on the same run root."""
        again = create_app(
            token=TOKEN,
            allow_origin=ORIGIN,
            run_root=run_root,
            provider_factory=provider_control.factory,
            list_models=models,
        )
        with TestClient(
            again, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        ) as fresh:
            assert fresh.get(f"/sessions/{chat_id}/snapshot").status_code == 404
            response = fresh.get(f"/reviews/{run_dir.name}")
        assert response.status_code == 200, response.text
        return response.json()

    read_only = [
        {
            **line[0],
            "reason": (
                "The check ran again after your answer and its verdict changed, so your Accept "
                "(real but already known) was cleared."
            ),
        }
    ]
    assert client.get(f"/sessions/{chat_id}/snapshot").json().get("cleared") == line
    assert restored().get("cleared") == read_only

    again = client.post(
        f"/sessions/{chat_id}/findings/{drawing}/disposition",
        json={"decision": "rejected", "note": "FICT decided again"},
    )

    assert again.status_code == 200, again.text
    assert "cleared" not in client.get(f"/sessions/{chat_id}/snapshot").json()
    assert "cleared" not in restored()


# --- a resumed turn that fails or is stopped still folds (cycle 6's Tier 1 review) ----------------

RERUN_VERDICTS = pytest.mark.parametrize(
    ("rerun_status", "kept", "beside"),
    [("suspected", True, False), ("unresolved", False, False), ("unresolved", False, True)],
    ids=["kept", "cleared", "cleared-beside-a-triage"],
)
"""The re-run's status: the one decided (`suspected`, medium), which keeps the decision, or
another (`unresolved`, low), which clears it (owner decisions 189A and 191A). *Changed
2026-11-02 on purpose (cycle 7's adversarial verification):* and whether another finding keeps a
triage beside the cleared one (`beside`), so the notice of the clear carries a tally."""


class PausedAfterACall(FakeProvider):
    """A scripted adapter that pauses its `turn`-th turn right after the turn's first tool call:
    it sets `paused` and waits for `resumed`, so a test can press Stop between two calls."""

    def __init__(
        self, *, turn: int, paused: threading.Event, resumed: threading.Event, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._pause_in = turn
        self._paused = paused
        self._resumed = resumed

    def _call(self, request: Any, tools: Any, on_event: Any) -> Any:
        result = super()._call(request, tools, on_event)
        if self._turn_index == self._pause_in and not self._paused.is_set():
            self._paused.set()
            if not self._resumed.wait(TIMEOUT_S):  # pragma: no cover - a hung test, not a path
                raise AssertionError("the paused turn was never resumed")
        return result


def accepted_then_answered(
    client: TestClient, run_dir: Path, *, beside: bool = False
) -> tuple[str, str, dict[str, Any]]:
    """Cycle 3's review through the routes: the drawing finding accepted as `already_known` while
    its question is open, then the question answered, resuming the turn. Returns the chat, the
    drawing finding's id and the disposition recorded. With `beside`, the first flagged finding
    the checks recorded is accepted as `new_and_real` first, a triage the resumed turn leaves
    alone (cycle 7)."""
    chat_id = start_session(client, run_dir)["chat_id"]
    assert settle(client, chat_id) == ChatState.WAITING_ENGINEER.value
    [drawing] = [
        finding.id
        for finding in load_session(run_dir / "session.json").findings
        if finding.check == MODEL_FINDING_CHECK
    ]
    if beside:
        other = next(
            finding.id
            for finding in load_session(run_dir / "session.json").findings
            if finding.check != MODEL_FINDING_CHECK and finding.status != "checked_within_scope"
        )
        triaged = client.post(
            f"/sessions/{chat_id}/findings/{other}/disposition",
            json={"decision": "accepted", "note": "FICT a real one", "triage": "new_and_real"},
        )
        assert triaged.status_code == 200, triaged.text
    decided = client.post(
        f"/sessions/{chat_id}/findings/{drawing}/disposition",
        json={"decision": "accepted", "note": "FICT intended", "triage": "already_known"},
    )
    assert decided.status_code == 200, decided.text
    answered = client.post(f"/sessions/{chat_id}/evidence/ER-001", json={"answer": "12 mm."})
    assert answered.status_code == 202, answered.text
    return chat_id, drawing, decided.json()["disposition"]


def assert_the_fold_is_what_was_saved(
    run_dir: Path,
    drawing: str,
    rerun_status: str,
    decided: dict[str, Any],
    *,
    kept: bool,
    turn_ended: str,
    beside: bool = False,
) -> None:
    """The turn ended for `turn_ended`, as before, and `session.json`, the `report.md` the server
    rendered and the stream agree with the fold: one finding of the check, under the decided id,
    its decision kept whole or cleared; the re-run's own id withdrawn with `folded_into`, the
    finding announced again under the decided id, and a `disposition.cleared` only when it was
    cleared - each written after the turn's end, so no reader of the stream files it under a call
    the Stop cut short, and before the finalization's `session.ended`. With `beside` - another
    finding keeps its `new_and_real` (`accepted_then_answered`) - the notice carries the tally the
    fold leaves, `report.md`'s By triage and misses lines for the session as finalized (cycle 7)."""
    events = events_of(run_dir)
    assert [event["body"]["reason"] for event in events if event["type"] == "turn.ended"][-1] == (
        turn_ended
    )
    saved = load_session(run_dir / "session.json")
    assert [
        (finding.id, finding.status, finding.disposition)
        for finding in saved.findings
        if finding.check == MODEL_FINDING_CHECK
    ] == [(drawing, rerun_status, Disposition.model_validate(decided) if kept else None)]
    flagged = [finding for finding in saved.findings if finding.status != "checked_within_scope"]
    tally = tally_body(new=1, not_recorded=len(flagged) - 1) if beside else None
    folded = [
        index
        for index, event in enumerate(events)
        if event["type"] == "finding.withdrawn" and event["body"].get("folded_into") == drawing
    ]
    cleared = [
        (index, event["body"])
        for index, event in enumerate(events)
        if event["type"] == "disposition.cleared"
    ]
    assert len(folded) == 1
    assert [body for _, body in cleared] == (
        []
        if kept
        else [
            {
                "finding_id": drawing,
                "disposition": decided,
                "reason": (
                    "The check ran again after your answer and its verdict changed, so your "
                    "Accept (real but already known) was cleared. Decide again."
                ),
                **({} if tally is None else {"triage_tally": tally}),
            }
        ]
    )
    announced = folded[0] + 1
    assert (events[announced]["type"], events[announced]["body"]["id"]) == ("finding", drawing)
    kinds = [event["type"] for event in events]
    turn_end = max(index for index, kind in enumerate(kinds) if kind == "turn.ended")
    session_end = max(index for index, kind in enumerate(kinds) if kind == "session.ended")
    folding = [*folded, announced, *(index for index, _ in cleared)]
    assert all(turn_end < index < session_end for index in folding)
    assert standing(events) == {finding.id for finding in saved.findings}
    spent = events[folded[0]]["body"]["finding_id"]
    lines = (run_dir / "report.md").read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith(f"#### {spent}:") for line in lines)
    expected = ACCEPTED_LINES if kept else UNDECIDED_LINES
    assert reported_disposition(lines, drawing, len(expected)) == expected
    if tally is not None:
        [at] = [index for index, line in enumerate(lines) if line.startswith("- By triage:")]
        assert lines[at : at + 2] == [f"- {tally['text']}", f"- {tally['misses_text']}"]


ACCEPTED_LINES = ["- Disposition:", "  - decision: accepted", "  - triage: real but already known"]
"""`report.md`'s first lines for an Accept recorded as `already_known`."""

UNDECIDED_LINES = ["- Disposition: not yet dispositioned"]
"""`report.md`'s line for a finding with no decision."""


def reported_disposition(lines: list[str], finding_id: str, count: int) -> list[str]:
    """The first `count` lines of the disposition `report.md` prints under `finding_id`'s
    heading, from its "- Disposition:" line."""
    heading = lines.index(next(line for line in lines if line.startswith(f"#### {finding_id}:")))
    start = next(
        index for index in range(heading, len(lines)) if lines[index].startswith("- Disposition:")
    )
    return lines[start : start + count]


@RERUN_VERDICTS
def test_a_resumed_turn_the_provider_fails_still_folds_its_rerun(
    client: TestClient,
    run_dir: Path,
    provider_control: ProviderControl,
    rerun_status: str,
    kept: bool,
    beside: bool,
) -> None:
    """Cycle 6's Tier 1 review: the model runs the check again in the resumed turn, and then the
    provider fails. The turn is reported failed and the session finalized, as any failed turn's
    (FR-008), and the re-run still folds onto the decided finding before that finalization, so
    `session.json`, `report.md` and the stream hold one verdict for the check: no second card
    beside the decided one, and a decision kept or cleared as an ended turn's fold would.

    *Changed 2026-11-02 on purpose (cycle 7's adversarial verification):* a third case clears the
    Accept beside another finding's triage, so the notice carries the tally the fold leaves,
    pinned with `report.md`'s two lines; the `cleared` case, whose Accept was the review's one
    triage, still pins a notice with none."""
    provider_control.script = [
        turn(
            "I need the thread depth.",
            call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS),
            call("request_evidence", **EVIDENCE_ARGUMENTS),
        ),
        ScriptedTurn(
            text="",
            rounds=(
                ScriptedRound(
                    calls=(
                        call(
                            "record_drawing_finding",
                            **{**DRAWING_FINDING_ARGUMENTS, "status": rerun_status},
                        ),
                    )
                ),
            ),
            fails=ProviderError("FICT the provider connection dropped"),
        ),
    ]
    chat_id, drawing, decided = accepted_then_answered(client, run_dir, beside=beside)

    assert settle(client, chat_id) == ChatState.FAILED.value
    assert_the_fold_is_what_was_saved(
        run_dir, drawing, rerun_status, decided, kept=kept, turn_ended="error", beside=beside
    )


@RERUN_VERDICTS
def test_a_resumed_turn_stopped_after_its_rerun_still_folds_it(
    run_root: Path, run_dir: Path, models: Models, rerun_status: str, kept: bool, beside: bool
) -> None:
    """Cycle 6's Tier 1 review: the model runs the check again in the resumed turn, and the
    engineer presses Stop before its next call. The turn ends `stopped` and the session with it
    (FR-030), and the re-run still folds onto the decided finding before that finalization.

    *Changed 2026-11-02 on purpose (cycle 7's adversarial verification):* a third case clears the
    Accept beside another finding's triage, as the failed turn's does."""
    paused, resumed = threading.Event(), threading.Event()
    script = [
        turn(
            "I need the thread depth.",
            call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS),
            call("request_evidence", **EVIDENCE_ARGUMENTS),
        ),
        turn(
            "Never reached.",
            call("record_drawing_finding", **{**DRAWING_FINDING_ARGUMENTS, "status": rerun_status}),
            call("get_package_summary"),
        ),
    ]
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=lambda settings: PausedAfterACall(
            turn=2, paused=paused, resumed=resumed, script=script, model=settings.model
        ),
        list_models=models,
    )
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as client:
        chat_id, drawing, decided = accepted_then_answered(client, run_dir, beside=beside)
        wait_until(paused.is_set, "the resumed turn to run its check again")
        try:
            stopped = client.post(f"/sessions/{chat_id}/stop")
        finally:
            resumed.set()

        assert stopped.status_code == 202, stopped.text
        assert settle(client, chat_id) == ChatState.ENDED.value
    assert_the_fold_is_what_was_saved(
        run_dir, drawing, rerun_status, decided, kept=kept, turn_ended="stopped", beside=beside
    )


# --- a real regrade that clears a decision, end to end (cycle 6's Tier 1 review) ------------------

RESTATED_LINE = (
    "Your answer graded the checks again and this verdict changed, so your Accept (real but "
    "already known) was cleared. Decide again."
)
"""The words file's line for an Accept recorded as `already_known` that a restate cleared."""

RESTATED_READ_ONLY_LINE = (
    "Your answer graded the checks again and this verdict changed, so your Accept (real but "
    "already known) was cleared."
)
"""`RESTATED_LINE` as a read-only restore names it, without the call to decide again (002 cycle
13): its decision buttons are off."""


@pytest.fixture
def regrading_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The review's checks are `test_answer_batch_roles`' scripted stand-ins, which read the roles
    the runner attached: each finds one thing on every graded part, low while the part may be
    bought and medium once it is custom. So the part-roles answer "None bought", a real regrade,
    restates the unclear pin's findings with another severity, and the custom plate's with
    theirs."""
    functions = (
        *(batch_roles.scripted_check(name, custom="medium") for name in batch_roles.SCRIPTED_TOOLS),
        *session_tools(),
    )
    monkeypatch.setattr(runner, "ToolRegistry", functools.partial(ToolRegistry, functions))


@dataclass(frozen=True)
class Regraded:
    """A review whose part-roles answer cleared the pin's Accept - or withdrew it, "All bought" -
    its chat and folder, the pin's and the plate's hygiene findings, and the disposition recorded
    on each before the answer."""

    chat_id: str
    folder: Path
    pin: str
    plate: str
    decided: dict[str, dict[str, Any]]

    @property
    def line(self) -> dict[str, Any]:
        """The `disposition.cleared` body the restate leaves on the pin's card."""
        disposition = self.decided[self.pin]
        return {"finding_id": self.pin, "disposition": disposition, "reason": RESTATED_LINE}

    @property
    def read_only_line(self) -> dict[str, Any]:
        """`line` as a read-only restore names it, its words without the call to decide again
        (002 cycle 13)."""
        return {**self.line, "reason": RESTATED_READ_ONLY_LINE}


def regraded_review(
    client: TestClient,
    review_dir: Path,
    *,
    ticked: bool,
    answer: str = "None bought",
    settled: ChatState | None = None,
) -> Regraded:
    """`tests/support/roles_review.py`'s package reviewed live (`ticked`: its opening turn played)
    or checks only, waiting for Send; the pin's and the plate's hygiene findings accepted as
    `already_known`; then the part-roles question answered `answer`, "None bought" unless named,
    which restates both. *Changed 2026-11-02 on purpose (002 T358):* `answer` added, so "All
    bought" withdraws the pin's findings instead; every earlier caller answers as before.
    *Changed 2026-11-02 on purpose (002 T362; a read-only check of cycle 10's review fixes):*
    `settled` added, the state the answer leaves the chat in - ended when `ticked`, waiting for
    Send otherwise, unless named - so a waiting answer that cannot close settles `failed`; every
    earlier caller settles as before."""
    roles_review.write_package(review_dir)
    profile = roles_review.write_profile(review_dir)
    chat_id = start_session(
        client, review_dir, standards_profile=str(profile), send_when_checked=ticked
    )["chat_id"]
    asked = ChatState.WAITING_ENGINEER if ticked else ChatState.AWAITING_SEND
    assert settle(client, chat_id) == asked.value
    components = load_package(review_dir).package.components
    document_of = {item.id: item.document_id for item in components}
    session = load_session(review_dir / "session.json")
    hygiene = {
        document_of[finding.component_ids[0]]: finding.id
        for finding in session.findings
        if finding.check == "check_hygiene.scripted"
    }
    pin, plate = hygiene[roles_review.PIN_ID], hygiene[roles_review.PLATE_ID]
    decided: dict[str, dict[str, Any]] = {}
    for finding_id in (pin, plate):
        response = client.post(
            f"/sessions/{chat_id}/findings/{finding_id}/disposition",
            json={"decision": "accepted", "note": "FICT as modelled", "triage": "already_known"},
        )
        assert response.status_code == 200, response.text
        decided[finding_id] = response.json()["disposition"]
    [question] = [
        request.id
        for request in session.evidence_requests
        if roles_review.PIN_ID in request.entity_ids
    ]
    answered = client.post(
        f"/sessions/{chat_id}/evidence",
        json={"answers": [{"request_id": question, "answer": answer}]},
    )
    assert answered.status_code == 202, answered.text
    if settled is None:
        settled = ChatState.ENDED if ticked else ChatState.AWAITING_SEND
    assert settle(client, chat_id) == settled.value
    return Regraded(chat_id, review_dir, pin, plate, decided)


def restored_snapshot_of(
    run_root: Path, provider_control: ProviderControl, models: Models, run_id: str
) -> dict[str, Any]:
    """`GET /reviews/{run_id}` from a backend started again on the same run root: what a restart
    and a read-only restore show."""
    again = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
    )
    with TestClient(again, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as fresh:
        response = fresh.get(f"/reviews/{run_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.mark.parametrize("ticked", [True, False], ids=["live", "waiting"])
def test_a_regrade_that_clears_a_decision_says_so_in_every_view(
    client: TestClient,
    run_root: Path,
    provider_control: ProviderControl,
    models: Models,
    regrading_checks: None,
    ticked: bool,
) -> None:
    """Owner decision 194A, through the routes and a real regrade, on a live review and on a
    waiting one: the part-roles answer "None bought" restates the pin's hygiene finding medium
    where it was accepted low, so its Accept and triage are cleared, and the plate's, restated as
    decided, keeps them. `session.json`, the `report.md` the server rendered, the stream, the live
    snapshot and a restarted backend's read-only restore all agree: the pin undecided with the
    restate's line, the plate's Accept standing, and no card left under a restated finding's own
    id. Cycle 3's `test_the_saved_session_and_report_agree_with_the_fold` is its model.

    *Changed 2026-11-01 on purpose (cycle 7's Tier 2 review):* written before cycle 7 put the
    review's triage tally on a cleared notice, so the stream's body now carries the one the
    restate leaves - the plate's `already_known` beside the findings not recorded - while both
    snapshots' lines leave it out, a snapshot's one tally being its summary's.

    *Changed 2026-11-02 on purpose (002 T358; roadmap hole H-g-010):* written before `report.md`
    printed a cleared line, so it read the pin's first line alone; it now reads the restate's line
    printed under the pin's undecided disposition too.

    *Changed 2026-11-02 on purpose (002 T370; cycle 13):* the read-only restore's buttons are off,
    so it names the pin's line without the call to decide again (`read_only_line`), where it named
    the live snapshot's words; the stream and the live snapshot keep the line as written."""
    review = regraded_review(client, run_root / "FICT-regrade", ticked=ticked)

    findings = load_session(review.folder / "session.json").findings
    flagged = [finding for finding in findings if finding.status != "checked_within_scope"]
    saved = {finding.id: finding for finding in findings}
    pin, plate = saved[review.pin], saved[review.plate]
    assert (pin.severity, pin.disposition) == ("medium", None)
    assert (plate.severity, plate.disposition) == (
        "medium",
        Disposition.model_validate(review.decided[review.plate]),
    )
    lines = (review.folder / "report.md").read_text(encoding="utf-8").splitlines()
    assert reported_disposition(lines, review.pin, 2) == [
        *UNDECIDED_LINES,
        f"  - cleared: {RESTATED_LINE}",
    ]
    assert reported_disposition(lines, review.plate, 3) == ACCEPTED_LINES
    events = events_of(review.folder)
    cleared = [event["body"] for event in events if event["type"] == "disposition.cleared"]
    tally = tally_body(known=1, not_recorded=len(flagged) - 1)
    assert cleared == [{**review.line, "triage_tally": tally}]
    assert standing(events) == set(saved)
    assert client.get(f"/sessions/{review.chat_id}/snapshot").json().get("cleared") == [review.line]
    restored = restored_snapshot_of(run_root, provider_control, models, review.folder.name)
    assert restored.get("cleared") == [review.read_only_line]


@pytest.mark.parametrize("ticked", [True, False], ids=["live", "waiting"])
def test_a_regrade_that_withdraws_a_decided_finding_says_so_in_report_md(
    client: TestClient, run_root: Path, regrading_checks: None, ticked: bool
) -> None:
    """002 T358 (roadmap hole H-g-010), through the routes and a real regrade, live and waiting:
    the part-roles answer "All bought" withdraws the pin's findings, its hygiene finding with the
    Accept and triage recorded on it, and that withdrawal says so - the disposition and the clause
    naming them - while the plate's findings, restated as decided, fold, and their withdrawals name
    nothing. The `report.md` the server rendered at the turn's end names the pin's finding among
    those withdrawn with a decision, and so does the one a later decision renders.

    *Changed 2026-11-03 on purpose (002 T382; cycle 16):* each withdrawal also names its finding's
    title, as the stream announced the id it withdraws - the pin's, and each fold's own - and the
    pin's line in `report.md` names it right after the id."""
    review = regraded_review(
        client, run_root / "FICT-withdraw", ticked=ticked, answer="All bought"
    )

    session = load_session(review.folder / "session.json")
    [question] = [
        request.id
        for request in session.evidence_requests
        if roles_review.PIN_ID in request.entity_ids
    ]
    reason = f"bought part (your answer to {question})"
    took = "your Accept (real but already known) went with it"
    events = events_of(review.folder)
    title = announced_title(events, review.pin)
    withdrawals = [event["body"] for event in events if event["type"] == "finding.withdrawn"]
    assert [body for body in withdrawals if "taken" in body] == [
        {
            "finding_id": review.pin,
            "title": title,
            "reason": reason,
            "disposition": review.decided[review.pin],
            "taken": took,
        }
    ]
    folds = [body for body in withdrawals if "folded_into" in body]
    assert folds
    assert all(set(body) == {"finding_id", "title", "reason", "folded_into"} for body in folds)
    assert all(body["title"] == announced_title(events, body["finding_id"]) for body in folds)
    named = [f"- {review.pin} ({title}) withdrawn: {reason}; {took}"]
    assert withdrawn_part(review.folder) == named

    later = next(finding.id for finding in session.findings if finding.disposition is None)
    decided = client.post(
        f"/sessions/{review.chat_id}/findings/{later}/disposition",
        json={"decision": "rejected", "note": "FICT not here"},
    )

    assert decided.status_code == 200, decided.text
    assert withdrawn_part(review.folder) == named


def withdrawn_part(folder: Path) -> list[str]:
    """The lines `report.md` prints under "Withdrawn with a decision", none without the part.

    *Changed 2026-11-02 (015 T123; cycle 12's read-only check):* read by `withdrawn_of`, which
    `test_recheck.py` shares for a report it renders; the lines are as before."""
    return withdrawn_of((folder / "report.md").read_text(encoding="utf-8").splitlines())


def announced_title(events: list[dict[str, Any]], finding_id: str) -> str:
    """The title the stream's last `finding` event announced `finding_id` with - what the live
    Transcript's "F-007 recorded: <title>" line names - which a withdrawal of it names (002 cycle
    16).

    *Changed 2026-11-03 (002 T386; cycle 16's read-only check):* a withdrawal names that title
    with the finding's parts' names after it when it names none of them
    (`report/titles.withdrawal_title`); the titles its callers read name the part's file - the
    scripted checks' "<file name> is scripted" (`regrading_checks`), and the mass check's, whose
    finding `test_recheck.py`'s re-runs withdraw - so there a withdrawal names just this title."""
    return [
        event["body"]["title"]
        for event in events
        if event["type"] == "finding" and event["body"]["id"] == finding_id
    ][-1]


def withdrawn_of(lines: list[str]) -> list[str]:
    """The lines a `report.md`, split into `lines`, prints under "Withdrawn with a decision", none
    without the part (015 T123, cycle 12's read-only check: one helper for this module and
    `test_recheck.py`)."""
    if "## Withdrawn with a decision" not in lines:
        return []
    start = lines.index("## Withdrawn with a decision") + 2
    return lines[start : lines.index("", start)]


@pytest.mark.parametrize("ticked", [True, False], ids=["live", "waiting"])
def test_a_read_only_restore_names_each_withdrawal_with_a_decision(
    client: TestClient,
    run_root: Path,
    provider_control: ProviderControl,
    models: Models,
    regrading_checks: None,
    ticked: bool,
) -> None:
    """002 cycle 13 (FR-031; H-g-010's *Left open*), through the routes and a real regrade, live and
    waiting: the part-roles answer "All bought" withdraws the pin's hygiene finding with the Accept
    and triage recorded on it. A restarted backend's read-only restore replays no Transcript, so its
    snapshot names that withdrawal, the body the record's own stream holds, for the page to print
    as the live line does - and not the plate's folds, which took no decision. The live snapshot,
    whose Transcript is replayed from the stream, names none.

    *Changed 2026-11-03 on purpose (002 T382; cycle 16):* the restored withdrawal names the pin's
    title, as the stream announced the pin, so the page's line says which finding went though no
    "recorded" line comes before it."""
    review = regraded_review(
        client, run_root / "FICT-withdraw-restore", ticked=ticked, answer="All bought"
    )

    events = events_of(review.folder)
    taken = [
        event["body"]
        for event in events
        if event["type"] == "finding.withdrawn" and "taken" in event["body"]
    ]
    assert [body["finding_id"] for body in taken] == [review.pin]
    assert "withdrawn" not in client.get(f"/sessions/{review.chat_id}/snapshot").json()
    restored = restored_snapshot_of(run_root, provider_control, models, review.folder.name)
    assert restored["withdrawn"] == taken
    assert [body.get("title") for body in restored["withdrawn"]] == [
        announced_title(events, review.pin)
    ]


def test_a_waiting_answer_that_cannot_close_names_no_withdrawal_its_record_still_holds(
    client: TestClient,
    run_root: Path,
    regrading_checks: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-only check of cycle 10's Tier 2 review fixes (002 T362), a guard: a waiting
    review's rollback reaches the state the review's killed backend left. The part-roles answer
    "All bought" withdraws the pin's hygiene finding, its `finding.withdrawn` naming the Accept it
    took, and then `close_waiting` raises - a Send cache or a save that cannot be written - so
    `answer_evidence_batch` reloads the record from disk, which still holds the pin accepted, and
    `_play` renders `report.md` from it beside a stream that withdrew it. That report names no
    withdrawal, and the pin still shows its Accept."""
    close_waiting = runner.ReviewRun.close_waiting

    def refused_once_answered(run: runner.ReviewRun) -> ReviewSession:
        """The opening's close as before; the answer's raises."""
        if any(request.status == "answered" for request in run.session.evidence_requests):
            raise OSError("FICT the run folder cannot be written")
        return close_waiting(run)

    monkeypatch.setattr(runner.ReviewRun, "close_waiting", refused_once_answered)
    review = regraded_review(
        client,
        run_root / "FICT-withdraw-rollback",
        ticked=False,
        answer="All bought",
        settled=ChatState.FAILED,
    )

    withdrawals = [
        event["body"] for event in events_of(review.folder) if event["type"] == "finding.withdrawn"
    ]
    assert [body["finding_id"] for body in withdrawals if "taken" in body] == [review.pin]
    findings = load_session(review.folder / "session.json").findings
    saved = {finding.id: finding for finding in findings}
    assert saved[review.pin].disposition == Disposition.model_validate(review.decided[review.pin])
    assert withdrawn_part(review.folder) == []
    lines = (review.folder / "report.md").read_text(encoding="utf-8").splitlines()
    assert reported_disposition(lines, review.pin, 3) == ACCEPTED_LINES


# --- the triage tally (002 T346; the owner's request, cycle 7) ------------------------------------


def test_the_reply_and_every_summary_carry_the_tally_report_md_prints(
    client: TestClient,
    run_root: Path,
    run_dir: Path,
    chat_with_a_finding: str,
    provider_control: ProviderControl,
    models: Models,
) -> None:
    """The one tally, through the routes: a decision's reply, the attention route's summary - what
    a session's end reads - the live snapshot's - a reload or a review switch - and the run folder's
    - a backend restart and a read-only restore - carry none while no finding records a triage, and
    after a triaged decision all carry the same one, whose two lines are `report.md`'s."""
    chat_id = chat_with_a_finding
    findings = load_session(run_dir / "session.json").findings
    flagged = [finding.id for finding in findings if finding.status != "checked_within_scope"]

    def summaries() -> list[dict[str, Any]]:
        """The attention route's, the live snapshot's and the run folder's summary, in order."""
        again = create_app(
            token=TOKEN,
            allow_origin=ORIGIN,
            run_root=run_root,
            provider_factory=provider_control.factory,
            list_models=models,
        )
        with TestClient(
            again, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        ) as fresh:
            restored = fresh.get(f"/reviews/{run_dir.name}")
        assert restored.status_code == 200, restored.text
        return [
            client.get(f"/sessions/{chat_id}/attention").json()["summary"],
            client.get(f"/sessions/{chat_id}/snapshot").json()["ranking"]["summary"],
            restored.json()["ranking"]["summary"],
        ]

    plain = client.post(
        f"/sessions/{chat_id}/findings/{flagged[0]}/disposition",
        json={"decision": "accepted", "note": "FICT note"},
    )

    assert plain.status_code == 200, plain.text
    assert "triage_tally" not in plain.json()
    assert ["triage_tally" in shown for shown in summaries()] == [False, False, False]

    late = client.post(
        f"/sessions/{chat_id}/findings/{flagged[0]}/disposition",
        json={"decision": "accepted", "note": "FICT note", "triage": "already_known"},
    )

    assert late.status_code == 200, late.text
    tally = tally_body(known=1, not_recorded=len(flagged) - 1)
    assert late.json()["triage_tally"] == tally
    assert late.json()["disposition"]["triage"] == "already_known"
    assert [shown["triage_tally"] for shown in summaries()] == [tally, tally, tally]
    lines = (run_dir / "report.md").read_text(encoding="utf-8").splitlines()
    [at] = [index for index, line in enumerate(lines) if line.startswith("- By triage:")]
    assert lines[at : at + 2] == [f"- {tally['text']}", f"- {tally['misses_text']}"]


def test_the_report_is_served_as_markdown(
    client: TestClient, run_dir: Path, chat_with_a_finding: str
) -> None:
    response = client.get(f"/sessions/{chat_with_a_finding}/report")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == (run_dir / "report.md").read_text(encoding="utf-8")


# --- a write as the review ends (002 T406; cycle 24) ----------------------------------------------
#
# The runner sends `session.ended` from `finalize`, and the worker then writes `report.md` and the
# attention record before it moves the chat out of `running`. A write the page makes in that moment,
# on a review it shows finished, waits for the settle and is answered as it would be a moment later.

SETTLE_BOUND_S = 2.0
"""`SETTLE_WAIT_S` as the bound's two cases set it: long beside a refusal given at once, and short
beside the 5 s the contract names, so the case that waits it out stays quick. *Changed 2026-11-03
(cycle 24's Tier 2 review):* both set it without `raising=False`, so a renamed constant fails them
rather than leaving the real 5 s in force, which both would still pass."""

DECISION = {"decision": "accepted", "note": "", "by": "FICT-ENG"}


@dataclass
class FinalRender:
    """A turn's final render, held: `session.ended` is on the stream and the chat is `running`."""

    reached: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def final_render(app: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[FinalRender]:
    """The next final render held until the test lets it go, as
    `test_a_retry_cannot_claim_a_folder_until_the_previous_render_finishes` holds it, and let go
    at the end whatever the test did."""
    held = FinalRender()
    original = app.state.server._render_report

    def held_render(chat: Any) -> None:
        if not held.reached.is_set():
            held.reached.set()
            assert held.release.wait(TIMEOUT_S), "the test did not release the final render"
        original(chat)

    monkeypatch.setattr(app.state.server, "_render_report", held_render)
    yield held
    held.release.set()


def ended_and_still_running(
    client: TestClient, run_dir: Path, chat_id: str, held: FinalRender
) -> None:
    """Wait for the held render, and check it is the moment cycle 24 is about."""
    assert held.reached.wait(TIMEOUT_S), "the turn did not reach its final render"
    assert types_of(run_dir)[-1] == "session.ended"
    assert state_of(client, chat_id) == ChatState.RUNNING.value


@pytest.fixture
def review_ending(
    client: TestClient, run_dir: Path, provider_control: ProviderControl, final_render: FinalRender
) -> tuple[str, FinalRender]:
    """A review that recorded one finding, held at its final render."""
    provider_control.script = [
        turn("One finding.", call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS)),
        *text_turns(2),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    ended_and_still_running(client, run_dir, chat_id, final_render)
    return chat_id, final_render


def sent_in_one_settle(held: FinalRender, *requests: Callable[[], Any]) -> list[Any]:
    """Each of `requests` sent in its own thread while the final render is held, in order and half
    a second apart, and their answers once the render is let go. A refusal comes back at once; a
    request that waits for the settle is still waiting, which is checked before the render is let
    go."""
    responses: list[Any] = [None] * len(requests)

    def send(index: int) -> None:
        try:
            responses[index] = requests[index]()
        except Exception as exc:  # the test client raises the server's own error; raised below
            responses[index] = exc

    senders = [threading.Thread(target=send, args=(index,)) for index in range(len(requests))]
    for sender in senders:
        sender.start()
        sender.join(0.5)
    waited = [sender.is_alive() for sender in senders]
    held.release.set()
    for sender in senders:
        sender.join(TIMEOUT_S)
    for still_waiting, response in zip(waited, responses, strict=True):
        if isinstance(response, Exception):
            raise response
        assert still_waiting, (
            f"answered before the chat settled: {response.status_code} {response.text}"
        )
    return responses


def sent_as_the_review_ends(held: FinalRender, write: Callable[[], Any]) -> Any:
    """`write` sent while the final render is held, and its answer once the render is let go. A
    refusal comes back at once; a write that waits for the settle is still waiting half a second
    later, which is checked before the render is let go. *Changed 2026-11-03 (cycle 24's Tier 2
    review):* one request of `sent_in_one_settle`, which sends several the same way."""
    return sent_in_one_settle(held, write)[0]


@pytest.mark.parametrize(
    ("body", "lines"),
    [
        pytest.param(DECISION, "  - decision: accepted\n  - by: FICT-ENG\n", id="a decision"),
        pytest.param(
            {
                "decision": "rejected",
                "note": "FICT note pressed as the review ended",
                "by": "FICT-ENG",
                "triage": "already_known",
            },
            "  - decision: rejected\n  - triage: real but already known\n  - by: FICT-ENG\n",
            id="a decision with its triage and note",
        ),
    ],
)
def test_a_decision_sent_as_the_review_ends_waits_for_the_settle_and_is_recorded(
    client: TestClient,
    run_dir: Path,
    review_ending: tuple[str, FinalRender],
    body: dict[str, Any],
    lines: str,
) -> None:
    """002 cycle 24: a decision pressed between the runner's `session.ended` and the chat leaving
    `running` met `409 TurnRunning` while the page said the review had finished. It waits for the
    settle and is recorded as a decision a moment later is: in the reply, the session file, the
    stream and `report.md`, which the route writes after the turn's own render."""
    chat_id, held = review_ending
    url = disposition_url(chat_id, run_dir)

    response = sent_as_the_review_ends(held, lambda: client.post(url, json=body))

    assert response.status_code == 200, response.text
    recorded = response.json()["disposition"]
    assert (recorded["decision"], recorded["note"], recorded.get("triage")) == (
        body["decision"],
        body["note"],
        body.get("triage"),
    )
    assert state_of(client, chat_id) == ChatState.ENDED.value
    saved = load_session(run_dir / "session.json").findings[0].disposition
    assert saved is not None and saved.model_dump(mode="json") == recorded
    assert recorded_dispositions(run_dir) == [recorded]
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert f"- Disposition:\n{lines}" in report
    assert f"  - note: {body['note']}\n" in report


def test_a_follow_up_sent_as_the_review_ends_runs_its_turn_once_the_chat_has_settled(
    client: TestClient, run_dir: Path, review_ending: tuple[str, FinalRender]
) -> None:
    """A follow-up waits too (002 cycle 24), and its turn starts only once the worker has written
    the turn's report and attention record and settled the chat, so no turn starts under them."""
    chat_id, held = review_ending

    response = sent_as_the_review_ends(
        held, lambda: client.post(f"/sessions/{chat_id}/messages", json={"text": "and also"})
    )

    assert response.status_code == 202, response.text
    assert settle(client, chat_id) == ChatState.ENDED.value
    assert types_of(run_dir).count("session.ended") == 2


def test_a_decision_sent_as_a_failing_turn_ends_meets_the_failure_not_a_running_turn(
    client: TestClient,
    run_dir: Path,
    provider_control: ProviderControl,
    final_render: FinalRender,
) -> None:
    """A write that waited is answered as it would be a moment later (002 cycle 24): a turn the
    provider failed is still finalized, so its `session.ended` comes first, and the chat settles
    `failed`, where a decision is `409 SessionFailed`. Nothing is written."""
    provider_control.script = [
        ScriptedTurn(
            text="",
            rounds=(
                ScriptedRound(calls=(call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS),)),
            ),
            fails=ProviderError("FICT the provider connection dropped"),
        )
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    ended_and_still_running(client, run_dir, chat_id, final_render)
    url = disposition_url(chat_id, run_dir)

    response = sent_as_the_review_ends(final_render, lambda: client.post(url, json=DECISION))

    assert (response.status_code, response.json()["error_class"]) == (409, "SessionFailed")
    assert state_of(client, chat_id) == ChatState.FAILED.value
    assert load_session(run_dir / "session.json").findings[0].disposition is None
    assert recorded_dispositions(run_dir) == []


def test_past_the_bound_a_decision_sent_as_the_review_ends_is_turn_running_and_writes_nothing(
    client: TestClient,
    run_dir: Path,
    review_ending: tuple[str, FinalRender],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wait is bounded (002 cycle 24): a chat that has not settled once `SETTLE_WAIT_S` has
    passed answers the decision as before, `409 TurnRunning` with today's message, and nothing is
    written. The bound is set short here; the contract names 5 s."""
    monkeypatch.setattr(chat_server, "SETTLE_WAIT_S", SETTLE_BOUND_S)
    chat_id, held = review_ending
    url = disposition_url(chat_id, run_dir)

    started = time.monotonic()
    refused = client.post(url, json=DECISION)
    waited = time.monotonic() - started
    held.release.set()

    assert settle(client, chat_id) == ChatState.ENDED.value
    assert refused.status_code == 409
    assert refused.json() == {
        "error_class": "TurnRunning",
        "message": f"chat {chat_id} is running a turn; wait for it to end",
        "retryable": False,
    }
    # Half the bound: the loop's timer may fire a clock tick early, and a refusal at once takes
    # a few milliseconds.
    assert waited >= SETTLE_BOUND_S / 2, f"refused after {waited:.3f} s, before the bound"
    assert load_session(run_dir / "session.json").findings[0].disposition is None
    assert recorded_dispositions(run_dir) == []
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "- Disposition: not yet dispositioned" in report


def test_a_decision_while_a_turn_still_runs_is_turn_running_at_once(
    client: TestClient,
    run_dir: Path,
    chat_with_a_finding: str,
    provider_control: ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a turn that has ended is waited for (002 cycle 24): while one still runs, a decision is
    `409 TurnRunning` at once, as before, and not once the bound has passed."""
    monkeypatch.setattr(chat_server, "SETTLE_WAIT_S", SETTLE_BOUND_S)
    url = disposition_url(chat_with_a_finding, run_dir)
    provider_control.hold()
    client.post(f"/sessions/{chat_with_a_finding}/messages", json={"text": "keep going"})
    wait_until(provider_control.started.is_set, "the follow-up turn to reach the gate")

    started = time.monotonic()
    refused = client.post(url, json=DECISION)
    took = time.monotonic() - started
    provider_control.release()

    assert settle(client, chat_with_a_finding) == ChatState.ENDED.value
    assert (refused.status_code, refused.json()["error_class"]) == (409, "TurnRunning")
    assert took < SETTLE_BOUND_S / 2, f"refused after {took:.3f} s: it waited"
    assert load_session(run_dir / "session.json").findings[0].disposition is None


# --- cycle 24's Tier 2 review (002 T408) -------------------------------------------------------
#
# A snapshot asked for in that moment waits for the settle as a write does. The requests that waited
# go on one at a time, in the order they came, and a decision or minutes among them is written on
# the chat's worker, so the writes one settle releases and the turn a follow-up starts run in line.

SLOW_LOOK_S = 2.0
"""`POLL_S` as a case sets it to put a request's next look at the chat after the settle and after a
later request's: long beside the half second between two requests, short beside the 5 s bound."""

MINUTES = {
    "baseline": 45,
    "supervision": 6,
    "verification": 9,
    "false_alarms": 2,
    "setup": 0,
    "by_hand": 0,
}
"""`test_chat_timing_route.FOUR`, which this module cannot import: its net is 28.0."""


def traced_writes(monkeypatch: pytest.MonkeyPatch, chat_id: str) -> list[tuple[str, bool]]:
    """Each decision's finding id, or `minutes`, in the order they are written, and whether each
    was written on the chat's worker, the one thread its turns run on (`ChatServer._worker`)."""
    worker = f"chat-{UUID(chat_id).hex[:8]}_"
    written: list[tuple[str, bool]] = []
    decide, save_minutes = chat_server.record_disposition, chat_server.record_timing_live

    def on_the_worker() -> bool:
        return threading.current_thread().name.startswith(worker)

    def decision(run: Any, finding_id: str, **kwargs: Any) -> Any:
        written.append((finding_id, on_the_worker()))
        return decide(run, finding_id, **kwargs)

    def minutes(run: Any, **kwargs: Any) -> Any:
        written.append(("minutes", on_the_worker()))
        return save_minutes(run, **kwargs)

    monkeypatch.setattr(chat_server, "record_disposition", decision)
    monkeypatch.setattr(chat_server, "record_timing_live", minutes)
    return written


def test_a_snapshot_asked_for_as_the_review_ends_waits_for_the_settle_and_says_how_it_settled(
    client: TestClient, run_dir: Path, review_ending: tuple[str, FinalRender]
) -> None:
    """A review switched to, or the pane reloaded, in that moment was restored `running` while the
    snapshot's `last_seq` already counted `session.ended`, so the page held its turn running on a
    stream opened past the one event that ends it (cycle 24's Tier 2 review, should-fix 1). The
    snapshot waits for the settle as a write does, and names the state the chat settled in."""
    chat_id, held = review_ending

    response = sent_as_the_review_ends(held, lambda: client.get(f"/sessions/{chat_id}/snapshot"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["chat_state"], body["last_seq"]) == (ChatState.ENDED.value, seqs_of(run_dir)[-1])
    assert types_of(run_dir)[-1] == "session.ended"


def test_writes_sent_in_one_settle_are_written_one_at_a_time_on_the_chats_worker_in_order(
    client: TestClient,
    run_dir: Path,
    review_ending: tuple[str, FinalRender],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The writes that waited were released together and each ran in the thread pool, beside the
    others, each saving `session.json` and writing `report.md` (cycle 24's Tier 2 review,
    should-fix 2). A write that waited goes to the chat's worker, in the order it came: two
    decisions and the minutes are written one after another, and each is kept."""
    chat_id, held = review_ending
    first, second = (finding.id for finding in load_session(run_dir / "session.json").findings[:2])
    written = traced_writes(monkeypatch, chat_id)

    responses = sent_in_one_settle(
        held,
        lambda: client.post(f"/sessions/{chat_id}/findings/{first}/disposition", json=DECISION),
        lambda: client.post(f"/sessions/{chat_id}/findings/{second}/disposition", json=DECISION),
        lambda: client.post(f"/sessions/{chat_id}/timing", json=MINUTES),
    )

    assert [response.status_code for response in responses] == [200, 200, 200], [
        response.text for response in responses
    ]
    assert written == [(first, True), (second, True), ("minutes", True)]
    assert state_of(client, chat_id) == ChatState.ENDED.value
    decisions = [response.json()["disposition"] for response in responses[:2]]
    saved = load_session(run_dir / "session.json")
    assert [
        finding.disposition.model_dump(mode="json") if finding.disposition else None
        for finding in saved.findings[:2]
    ] == decisions
    assert saved.timing.net_saved_minutes == 28.0
    assert recorded_dispositions(run_dir) == decisions


def test_a_decision_sent_before_a_follow_up_in_one_settle_is_written_before_its_turn(
    client: TestClient,
    run_dir: Path,
    review_ending: tuple[str, FinalRender],
    provider_control: ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Released together, a follow-up that looked at the chat first started its turn, and a
    decision pressed before it then met that turn, `409 TurnRunning` (cycle 24's Tier 2 review,
    should-fix 2). The requests that waited go on in the order they came: the decision is written,
    on the chat's worker, and the follow-up's turn starts after it. The decision's next look at the
    chat is set after the follow-up's, as the two can fall on a slow seat."""
    chat_id, held = review_ending
    url = disposition_url(chat_id, run_dir)
    finding_id = load_session(run_dir / "session.json").findings[0].id
    written = traced_writes(monkeypatch, chat_id)
    provider_control.hold()
    poll = chat_server.POLL_S

    def follow_up() -> Any:
        monkeypatch.setattr(chat_server, "POLL_S", poll)  # every later look at the usual rate
        return client.post(f"/sessions/{chat_id}/messages", json={"text": "and also"})

    monkeypatch.setattr(chat_server, "POLL_S", SLOW_LOOK_S)
    decided, followed = sent_in_one_settle(held, lambda: client.post(url, json=DECISION), follow_up)
    provider_control.release()

    assert decided.status_code == 200, decided.text
    assert followed.status_code == 202, followed.text
    assert settle(client, chat_id) == ChatState.ENDED.value
    assert written == [(finding_id, True)]
    types = types_of(run_dir)
    assert types.count("session.ended") == 2
    assert types[types.index("session.ended") + 1] == "disposition"


def test_a_decision_sent_once_the_chat_has_settled_goes_behind_a_follow_up_still_waiting(
    client: TestClient,
    run_dir: Path,
    review_ending: tuple[str, FinalRender],
    provider_control: ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request that arrives once the chat has settled, while one sent before it has still to see
    the settle, goes behind it (cycle 24's Tier 2 review, should-fix 2): a decision sent after a
    follow-up meets the turn the follow-up starts, `409 TurnRunning`, as it would a moment later,
    and is never written beside that turn. Each look at the chat is set a second apart, so the
    follow-up sees the settle well after the decision arrives."""
    chat_id, held = review_ending
    url = disposition_url(chat_id, run_dir)
    provider_control.hold()
    monkeypatch.setattr(chat_server, "POLL_S", SLOW_LOOK_S / 2)
    answered: dict[str, Any] = {}
    follower = threading.Thread(
        target=lambda: answered.update(
            response=client.post(f"/sessions/{chat_id}/messages", json={"text": "and also"})
        )
    )
    follower.start()
    follower.join(0.5)
    assert follower.is_alive(), "the follow-up was answered before the chat settled"
    held.release.set()
    assert settle(client, chat_id) == ChatState.ENDED.value

    refused = client.post(url, json=DECISION)
    follower.join(TIMEOUT_S)
    provider_control.release()

    assert answered["response"].status_code == 202, answered["response"].text
    assert (refused.status_code, refused.json().get("error_class")) == (409, "TurnRunning")
    assert settle(client, chat_id) == ChatState.ENDED.value
    assert types_of(run_dir).count("session.ended") == 2
    assert load_session(run_dir / "session.json").findings[0].disposition is None
    assert recorded_dispositions(run_dir) == []


@pytest.mark.parametrize(
    ("route", "body"),
    [
        pytest.param("/evidence/ER-001", {"answer": "Tapped 12 mm deep."}, id="evidence/{id}"),
        pytest.param(
            "/evidence",
            {"answers": [{"request_id": "ER-001", "answer": "Tapped 12 mm deep."}]},
            id="evidence",
        ),
    ],
)
def test_answers_sent_as_the_turn_that_asked_ends_wait_and_resume_the_review(
    client: TestClient,
    run_dir: Path,
    provider_control: ProviderControl,
    final_render: FinalRender,
    route: str,
    body: dict[str, Any],
) -> None:
    """Both `evidence` routes wait for the settle (002 cycle 24; its Tier 2 review, should-fix 4):
    answers sent as the turn that asked ends are taken once the chat settles `waiting_engineer`, and
    resume the review."""
    provider_control.script = [
        turn("I need the thread depth.", call("request_evidence", **EVIDENCE_ARGUMENTS)),
        turn("Thanks; the joint is fine."),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    ended_and_still_running(client, run_dir, chat_id, final_render)

    response = sent_as_the_review_ends(
        final_render, lambda: client.post(f"/sessions/{chat_id}{route}", json=body)
    )

    assert response.status_code == 202, response.text
    assert settle(client, chat_id) == ChatState.ENDED.value
    request = load_session(run_dir / "session.json").evidence_requests[0]
    assert (request.status, request.answer) == ("answered", "Tapped 12 mm deep.")
    assert types_of(run_dir).count("session.ended") == 2


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
