"""The loopback HTTP backend the Task Pane talks to (`contracts/chat-api.md`).

One Starlette application, one process, one workstation, one engineer. What it is
responsible for, and why each piece is where it is:

**The door is middleware, not a decorator on ten endpoints.** `Guard` runs before routing,
so the three rules that hold for *every* path - a wrong `Origin` is 403 before
authentication, an `OPTIONS` preflight is answered 204 without a token, everything else
needs `Authorization: Bearer <token>` - are written once and cannot be forgotten on the
eleventh route. The token is compared with `hmac.compare_digest` and is never read from a
query string: a token in a URL lands in access logs, WebView2 history and crash dumps, so
a URL must not be a way to present one.

**`run_dir` is caller-supplied, so it is not trusted.** `resolve_run_dir` refuses UNC and
Win32 device paths and any `..` segment on sight, then requires the canonical path to be a
strict descendant of the configured run root. The pane passes the run root from settings
and the page never sees it, so this is the one place a page-supplied path becomes a file
the backend will write to. A folder is also *one chat's*: `events.jsonl` has one `seq`
sequence and `session.json` one session, so a folder a live chat holds is refused and a
folder that already holds a session is refused unless this is the Retry replacing it,
which moves the old pair aside (`_claim_run_dir`, `_rotate_previous`).

**One worker thread per chat, and one running turn per chat.** A turn is a blocking call
into a provider SDK, so it runs on the chat's own single-threaded executor and the event
loop stays free to stream events and answer `GET /sessions/{id}`. The state machine in
`sessions.py` is what refuses a second turn: the endpoints ask it, and a refusal is a 409
rather than a silent queue, because the pane has to be able to say so.

**A session always ends (FR-008).** Four paths close one: the turn finishes and the runner
finalizes; the *provider* fails and the runner reports, closes the turn and finalizes
before the exception travels on; `POST /stop` raises `TurnStopped` at the next tool
boundary, which the worker turns into `turn.ended {reason: "stopped"}` and a finalization;
or the process gets a shutdown signal, and the lifespan finalizes every chat whose session
is still open - writing `turn.ended {reason: "error"}` first when a turn was mid-flight -
before the loop goes away. Anything else that raises out of a turn is closed out by the
worker itself (`_close_out`), which asks whether the session has an `ended_at` rather than
assuming the runner wrote one.

**No key ever leaves the process as text (FR-015).** Credentials arrive in the environment
and nowhere else (the server never reads the settings file), and every error body goes
through the redactor built from those values, so a provider exception that quotes the
request it failed on cannot carry the key back to the page.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import logging
import os
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import UUID

import anyio
from pydantic import ValidationError
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from swreview import __version__
from swreview.agent.providers import (
    AgentEvent,
    AgentProvider,
    ProviderName,
    ToolCallResult,
    error_body,
)
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import (
    EVENTS_FILE_NAME,
    SESSION_FILE_NAME,
    ReviewRun,
    start_review,
)
from swreview.agent.settings import DEFAULT_PROVIDER, ProviderSettings, default_model, redact
from swreview.bridge.client import DEFAULT_PIPE_NAME, BridgeClient, BridgeError, NamedPipeTransport
from swreview.chat import DEFAULT_ALLOW_ORIGIN, DEFAULT_RUN_ROOT
from swreview.chat.sessions import (
    ChatSession,
    ChatState,
    InvalidTransitionError,
    record_disposition,
    replay_events,
)
from swreview.ir.models import UnsupportedSchemaVersionError
from swreview.report.dispositions import DECISIONS, REPORT_FILE_NAME
from swreview.report.markdown import render_report

__all__ = [
    "DEFAULT_ALLOW_ORIGIN",
    "DEFAULT_RUN_ROOT",
    "ChatError",
    "ChatServer",
    "StoppableTools",
    "TurnStopped",
    "build_provider",
    "create_app",
    "environment_secrets",
    "fake_chat_script",
    "forced_failure_bridge_factory",
    "list_provider_models",
    "resolve_run_dir",
]

logger = logging.getLogger("swreview.chat")

RELEASE_PROVIDERS: tuple[str, ...] = (ProviderName.OPENAI.value, ProviderName.GEMINI.value)
"""What `GET /health` lists. A development build appends the scripted provider (FR-027)."""

KEY_VARIABLES: tuple[str, ...] = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
"""The environment the add-in passes the key in; the values redaction has to mask."""

ALLOWED_HEADERS = "authorization, content-type, last-event-id"
ALLOWED_METHODS = "GET, POST, OPTIONS"
PREFLIGHT_MAX_AGE = "600"

POLL_S = 0.02
"""How often the SSE endpoint drains its subscriber queue.

The queue is filled from the chat's worker thread and read on the event loop; polling it
keeps the fan-out free of any loop binding (`sessions.py`), which is what lets the state
machine and the stream be tested without an ASGI server at all. One desktop pane with one
open stream makes 50 wakeups a second the cheaper trade.
"""

PACKAGE_ERRORS = (
    FileNotFoundError,
    NotADirectoryError,
    UnsupportedSchemaVersionError,
    ValidationError,
    ValueError,
    KeyError,
    LookupError,
    OSError,
)
"""What an unreadable or unparseable `run_dir/package.json` raises. All of it is a 400."""


# --- failures the page is allowed to see ------------------------------------------------


class ChatError(Exception):
    """A refusal with an HTTP status and the contract's error body.

    `error_class` is the string the page switches on, so it is part of the contract and
    not a rendering of the exception name. `retryable` answers "is it worth pressing the
    button again": a client mistake is not, a provider failure is.
    """

    status = 400
    error_class = "InvalidRequest"
    retryable = False

    def body(self) -> dict[str, Any]:
        return error_body(
            error_class=self.error_class, message=str(self), retryable=self.retryable
        )


class InvalidRunDir(ChatError):
    """`run_dir` broke the path rule (`chat-api.md`, Path rule for `run_dir`)."""

    error_class = "InvalidRunDir"


class InvalidPackage(ChatError):
    """`run_dir/package.json` is missing or is not a package this build can read."""

    error_class = "InvalidPackage"


class UnknownProvider(ChatError):
    error_class = "UnknownProvider"


class InvalidDecision(ChatError):
    error_class = "InvalidDecision"


class UnknownChat(ChatError):
    status = 404
    error_class = "UnknownChat"


class UnknownEvidenceRequest(ChatError):
    status = 404
    error_class = "UnknownEvidenceRequest"


class UnknownFinding(ChatError):
    status = 404
    error_class = "UnknownFinding"


class ReportMissing(ChatError):
    status = 404
    error_class = "ReportMissing"


class TurnRunning(ChatError):
    """One running turn per chat: the server refuses rather than queueing silently."""

    status = 409
    error_class = "TurnRunning"


class RunDirInUse(ChatError):
    """A live chat already holds this run folder (`_claim_run_dir`)."""

    status = 409
    error_class = "RunDirInUse"


class AlreadyAnswered(ChatError):
    status = 409
    error_class = "AlreadyAnswered"


class SessionFailed(ChatError):
    """`failed` is terminal; its only exit is a new session carrying `retry_of`."""

    status = 409
    error_class = "SessionFailed"


class IllegalTransition(ChatError):
    """A disposition the finding's state machine forbids (`report/dispositions.py`)."""

    status = 409
    error_class = "IllegalTransition"


class ProviderFailed(ChatError):
    """The provider itself failed. 502 carrying *its* error class, not ours."""

    status = 502
    retryable = True

    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class

    @classmethod
    def wrapping(cls, exc: BaseException) -> ProviderFailed:
        return cls(type(exc).__name__, str(exc))


# --- stopping a turn ---------------------------------------------------------------------


class TurnStopped(BaseException):
    """`POST /stop` reached this chat; raised at the next tool boundary.

    A `BaseException` on purpose. The runner turns any `Exception` out of a turn into
    `error` plus `turn.ended {reason: "error"}` and a failed session, which is the right
    answer for a provider that blew up and the wrong one for an engineer who pressed Stop:
    the contract says the turn ends with `reason: "stopped"` and the session ends cleanly.
    Passing outside the `Exception` hierarchy is what lets the worker say so itself.
    """


class StoppableTools:
    """The run's `ToolSet` with one question asked between calls: has Stop been pressed?

    A turn is a blocking call inside a provider SDK, so it cannot be cancelled from
    outside; what it does do, repeatedly, is come back here to run a tool. That is the
    "next tool boundary" the contract promises, and it is the only place where stopping
    costs nothing: no half-written tool result, no partial finding.
    """

    def __init__(self, tools: Any, stop: Any) -> None:
        self.tools = tools
        self.stop = stop

    def __iter__(self) -> Iterator[Any]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def call(
        self, name: str, arguments: Mapping[str, Any], call_id: str = ""
    ) -> ToolCallResult:
        if self.stop.is_set():
            raise TurnStopped(f"the engineer stopped this turn before {name!r} ran")
        return self.tools.call(name, arguments, call_id)


# --- the path rule -----------------------------------------------------------------------


def resolve_run_dir(raw: Any, run_root: Path) -> Path:
    """`raw` as a canonical directory strictly inside `run_root`, or `InvalidRunDir`.

    The order matters. UNC and device paths (`\\\\server\\share`, `\\\\.\\pipe\\x`,
    `\\\\?\\C:\\x`) are refused before anything touches the filesystem, because resolving
    one can block on a network the workstation cannot reach. `..` is refused on sight
    rather than normalized away: a page that sends one is not asking for the directory it
    would land in, and a rule that quietly rewrote it would be a rule nobody can audit.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidRunDir("run_dir is required and must be a path")
    text = raw.strip()
    windows = PureWindowsPath(text)
    if text.startswith(("\\\\", "//")) or windows.anchor.startswith(("\\\\", "//")):
        raise InvalidRunDir(f"run_dir {text!r} is a UNC or device path; it must be a local path")
    if ".." in windows.parts or ".." in Path(text).parts:
        raise InvalidRunDir(f"run_dir {text!r} contains a '..' segment")
    resolved = Path(text).resolve()
    root = Path(run_root).resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise InvalidRunDir(f"run_dir {text!r} is not inside the run root {root}")
    return resolved


SESSION_FILES: tuple[str, ...] = (EVENTS_FILE_NAME, SESSION_FILE_NAME)
"""What one session owns in its run folder, and what a second one would write over."""


def _session_files(run_dir: Path) -> list[Path]:
    """The files of `SESSION_FILES` that `run_dir` already holds, in order."""
    return [path for name in SESSION_FILES if (path := run_dir / name).is_file()]


def _rotated(path: Path, index: int) -> Path:
    """`events.jsonl` at index 2 is `events.2.jsonl`, `session.json` is `session.2.json`."""
    return path.with_name(f"{path.stem}.{index}{path.suffix}")


def _next_free_index(run_dir: Path) -> int:
    """The lowest `n` for which *no* `SESSION_FILES` entry has been rotated to `.n`.

    One index for the whole pair: `events.2.jsonl` beside `session.2.json` says the two
    came from the same session, which is the only reading of the folder that is any use
    after two retries.
    """
    index = 1
    while any(_rotated(run_dir / name, index).exists() for name in SESSION_FILES):
        index += 1
    return index


# --- what the server builds when nobody injected anything --------------------------------


FAKE_TURNS = 32
"""How many turns `--provider fake` can play before the script runs out.

The CLI's dry run is one turn because `swreview review` takes one; a chat takes as many as
the engineer types, and a script that ran out mid-conversation would fail the session for a
reason that has nothing to do with what is being tested.
"""

DRY_RUN_TEXT = (
    "Dry run: the scripted provider sends nothing to a model. It reads the package census "
    "and stops, so nothing here is a review finding."
)

BRIDGE_PROBE_REF = "probe"


def fake_chat_script(*, bridge_calls: int = 0) -> tuple[ScriptedTurn, ...]:
    """What `--provider fake` plays in the pane: a read-only call, then talk.

    `bridge_calls` is the `--fail-bridge` diagnostic (quickstart scenario 4): the opening
    turn makes that many live-bridge calls so the forced failures and the circuit opening
    on the fourth are visible in the event stream, on a workstation and in the subprocess
    test alike. It is 0 for every ordinary run, and the bridge tools only exist at all
    when the session asked for a bridge.
    """
    probe = tuple(
        ScriptedToolCall(
            "bridge_measure",
            {"persist_ref_a": f"{BRIDGE_PROBE_REF}-{index}", "persist_ref_b": BRIDGE_PROBE_REF},
        )
        for index in range(bridge_calls)
    )
    opening = ScriptedTurn(
        text=DRY_RUN_TEXT,
        tool_calls=(ScriptedToolCall("get_package_summary"), *probe),
    )
    return (opening, *(ScriptedTurn(text=DRY_RUN_TEXT) for _ in range(FAKE_TURNS - 1)))


def build_provider(settings: ProviderSettings, *, fail_bridge: int = 0) -> AgentProvider:
    """The adapter one chat session talks to.

    Real providers are built by `cli.provider_factory`, which is the single place in the
    product that constructs a provider SDK client; it is imported here rather than at
    module scope so `chat.server` stays importable (and testable) without pulling in the
    command line. The scripted provider is built here instead of there because a chat
    needs a script that survives a conversation - see `fake_chat_script`.
    """
    if settings.provider is ProviderName.FAKE:
        calls = fail_bridge + 1 if fail_bridge else 0
        return FakeProvider(script=fake_chat_script(bridge_calls=calls), model=settings.model)
    from swreview.cli import provider_factory

    return provider_factory(settings)


def list_provider_models(
    provider: ProviderName, *, env: Mapping[str, str] | None = None
) -> list[dict[str, str]]:
    """`GET /models`: what the provider says it can run, as `{id, label}` rows.

    The key comes from the environment, like everything else the backend is given, and the
    SDK is imported only for the provider actually asked about.
    """
    settings = ProviderSettings.from_env(provider=provider, env=env)
    if provider is ProviderName.FAKE:
        model = default_model(provider)
        return [{"id": model, "label": f"{model} (scripted, sends nothing to a model)"}]
    if provider is ProviderName.OPENAI:
        from openai import OpenAI

        client = OpenAI(**settings.client_kwargs())
        return [{"id": item.id, "label": item.id} for item in client.models.list()]
    from google import genai

    client = genai.Client(**settings.client_kwargs())
    rows: list[dict[str, str]] = []
    for item in client.models.list():
        name = getattr(item, "name", None)
        if not name:
            continue
        rows.append({"id": str(name), "label": str(getattr(item, "display_name", "") or name)})
    return rows


class _ForcedFailureTransport:
    """A bridge transport whose first `failures` requests fail without reaching the pipe.

    The `--fail-bridge N` test hook. It fails the transport rather than the client so the
    breaker under test is the real one: three counted failures and `BridgeClient` opens its
    own circuit, and the fourth call never goes out (`bridge/client.py`, `CIRCUIT_LIMIT`).
    """

    def __init__(self, failures: int, inner: Any) -> None:
        self.remaining = failures
        self.inner = inner

    def request(self, line: str) -> str:
        if self.remaining > 0:
            self.remaining -= 1
            raise BridgeError(
                f"--fail-bridge forced this request to fail ({self.remaining} forced "
                "failure(s) left before the real pipe is used)"
            )
        return self.inner.request(line)

    def close(self) -> None:
        self.inner.close()


def forced_failure_bridge_factory(
    failures: int,
) -> Callable[[str, str | None], BridgeClient]:
    """A `bridge_factory` for `start_review` that forces the first `failures` calls to fail."""

    def build(pipe_name: str, secret: str | None) -> BridgeClient:
        return BridgeClient(
            pipe_name,
            secret,
            transport=_ForcedFailureTransport(failures, NamedPipeTransport(pipe_name)),
        )

    return build


def environment_secrets(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Every provider key in this process's environment: what redaction must mask.

    The backend is given its credentials in its environment and reads no settings file, so
    this is the whole set - and it is read once, at start, because the environment of a
    running process does not change (the pane restarts the backend when the key does).
    """
    source = os.environ if env is None else env
    return tuple(
        value for name in KEY_VARIABLES if (value := (source.get(name) or "").strip())
    )


# --- the door ------------------------------------------------------------------------------


class Guard:
    """Origin, preflight and token, for every route, before routing (`chat-api.md`)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        origin: str,
        redactor: Callable[[str], str],
    ) -> None:
        self.app = app
        self.token = token
        self.origin = origin
        self.redact = redactor

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - the app serves no websockets
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is not None and origin != self.origin:
            logger.warning("refused a request from origin %r", origin)
            await self._refuse(
                scope,
                receive,
                send,
                403,
                "ForbiddenOrigin",
                f"origin {origin!r} is not allowed; this backend serves {self.origin}",
                cors=False,
            )
            return
        if scope["method"] == "OPTIONS":
            await self._preflight(scope, receive, send)
            return
        if not self._authorized(headers):
            logger.warning("refused an unauthenticated %s %s", scope["method"], scope["path"])
            await self._refuse(
                scope,
                receive,
                send,
                401,
                "Unauthorized",
                "this request carried no valid bearer token",
            )
            return
        await self.app(scope, receive, self._with_cors(send))

    def _authorized(self, headers: Headers) -> bool:
        """`Authorization: Bearer <token>`, compared in constant time. Nothing else.

        The query string is deliberately not consulted: the contract forbids the token in
        a URL, and accepting one there would make the forbidden form work.
        """
        value = headers.get("authorization", "")
        scheme, _, presented = value.partition(" ")
        if scheme.lower() != "bearer" or not presented:
            return False
        return hmac.compare_digest(presented.strip(), self.token)

    def _cors_headers(self) -> list[tuple[bytes, bytes]]:
        return [
            (b"access-control-allow-origin", self.origin.encode()),
            (b"vary", b"Origin"),
        ]

    def _with_cors(self, send: Send) -> Send:
        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["access-control-allow-origin"] = self.origin
                if "vary" not in headers:
                    headers["vary"] = "Origin"
            await send(message)

        return wrapped

    async def _preflight(self, scope: Scope, receive: Receive, send: Send) -> None:
        """204, with no token asked for: a preflight never carries author headers."""
        response = Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": self.origin,
                "Vary": "Origin",
                "Access-Control-Allow-Headers": ALLOWED_HEADERS,
                "Access-Control-Allow-Methods": ALLOWED_METHODS,
                "Access-Control-Max-Age": PREFLIGHT_MAX_AGE,
                "Access-Control-Allow-Private-Network": "true",
            },
        )
        await response(scope, receive, send)

    async def _refuse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        error_class: str,
        message: str,
        cors: bool = True,
    ) -> None:
        headers = {"Access-Control-Allow-Origin": self.origin, "Vary": "Origin"} if cors else None
        response = JSONResponse(
            {
                "error_class": error_class,
                "message": self.redact(message),
                "retryable": False,
            },
            status_code=status,
            headers=headers,
        )
        await response(scope, receive, send)


# --- the server ------------------------------------------------------------------------------


class ChatServer:
    """Every live chat, the worker thread behind each one, and the endpoints over them."""

    def __init__(
        self,
        *,
        token: str,
        allow_origin: str,
        run_root: Path,
        provider_factory: Callable[[ProviderSettings], AgentProvider],
        list_models: Callable[[ProviderName], list[dict[str, str]]],
        bridge_factory: Callable[[str, str | None], Any] | None = None,
        development: bool = False,
        secrets: Sequence[str] | None = None,
    ) -> None:
        self.token = token
        self.allow_origin = allow_origin
        self.run_root = Path(run_root)
        self.provider_factory = provider_factory
        self.list_models = list_models
        self.bridge_factory = bridge_factory
        self.development = development
        self.secrets = tuple(secrets) if secrets is not None else environment_secrets()
        self.chats: dict[UUID, ChatSession] = {}
        self._workers: dict[UUID, ThreadPoolExecutor] = {}

    def redact(self, text: str) -> str:
        """Mask every configured key out of anything headed for the page or a log."""
        return redact(text, self.secrets)

    # --- endpoints ---------------------------------------------------------------

    async def health(self, request: Request) -> Response:
        providers = [*RELEASE_PROVIDERS]
        if self.development:
            providers.append(ProviderName.FAKE.value)
        return JSONResponse({"status": "ok", "version": __version__, "providers": providers})

    async def models(self, request: Request) -> Response:
        raw = request.query_params.get("provider", DEFAULT_PROVIDER.value)
        try:
            provider = ProviderName(raw)
        except ValueError:
            supported = ", ".join(member.value for member in ProviderName)
            raise UnknownProvider(
                f"unknown provider {raw!r}; this backend runs {supported}"
            ) from None
        try:
            found = await run_in_threadpool(self.list_models, provider)
        except Exception as exc:
            logger.warning("listing %s models failed: %s", provider.value, self.redact(str(exc)))
            raise ProviderFailed.wrapping(exc) from exc
        return JSONResponse({"models": found})

    async def create_session(self, request: Request) -> Response:
        body = await self._json(request)
        run_dir = resolve_run_dir(body.get("run_dir"), self.run_root)
        retry_of = self._uuid(body.get("retry_of"), "retry_of")
        self._claim_run_dir(run_dir, retry_of)
        settings = self._settings(body)
        bridge = body.get("bridge") or None
        chat = ChatSession(
            run_dir=run_dir,
            provider=settings.provider.value,
            model=settings.model,
            effort=settings.effort,
            engineer=str(body.get("engineer") or ""),
            retry_of=retry_of,
            token=self.token,
            bridge=bridge,
            created_at=datetime.now(UTC),
        )
        chat.to(ChatState.EXTRACTING)
        run = await run_in_threadpool(self._start_review, chat, settings)
        chat.attach(run)
        self.chats[chat.chat_id] = chat
        chat.to(ChatState.RUNNING)
        self._submit(chat, run.start)
        return JSONResponse(
            {
                "chat_id": str(chat.chat_id),
                "review_session_id": str(chat.review_session_id),
            },
            status_code=201,
        )

    async def get_session(self, request: Request) -> Response:
        return JSONResponse(self._chat(request).public())

    async def events(self, request: Request) -> Response:
        """Replay `events.jsonl` after `Last-Event-ID`, then stream what happens next.

        The subscription is opened *before* the file is read, so an event written while
        the replay is in flight is delivered by the live half instead of falling into the
        gap between the two; `seq` is what tells the two apart.
        """
        chat = self._chat(request)
        last = self._last_event_id(request)

        async def stream() -> AsyncIterator[ServerSentEvent]:
            with chat.subscribe() as subscriber:
                highest = last
                for event in replay_events(chat.events_path, after=last):
                    highest = event.seq
                    yield _sse(event)
                while True:
                    for event in subscriber.drain():
                        if event.seq <= highest:
                            continue
                        highest = event.seq
                        yield _sse(event)
                    await anyio.sleep(POLL_S)

        return EventSourceResponse(stream())

    async def post_message(self, request: Request) -> Response:
        chat = self._chat(request)
        body = await self._json(request)
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ChatError("a message needs a non-empty 'text'")
        self._require_idle(chat)
        run = self._run_of(chat)
        chat.to(ChatState.RUNNING)
        self._submit(chat, partial(run.continue_session, text))
        return JSONResponse(chat.public(), status_code=202)

    async def answer_evidence(self, request: Request) -> Response:
        chat = self._chat(request)
        body = await self._json(request)
        answer = body.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ChatError("an evidence answer needs a non-empty 'answer'")
        self._require_idle(chat)
        run = self._run_of(chat)
        request_id = request.path_params["request_id"]
        found = next(
            (item for item in run.session.evidence_requests if item.id == request_id), None
        )
        if found is None:
            raise UnknownEvidenceRequest(
                f"no evidence request {request_id!r} in this session; open: "
                f"{chat.open_requests}"
            )
        if found.status != "open":
            raise AlreadyAnswered(f"evidence request {request_id} is already answered")
        chat.to(ChatState.RUNNING)
        self._submit(chat, partial(run.answer_evidence, request_id, answer))
        return JSONResponse(chat.public(), status_code=202)

    async def disposition(self, request: Request) -> Response:
        chat = self._chat(request)
        body = await self._json(request)
        decision = str(body.get("decision", ""))
        if decision not in DECISIONS:
            raise InvalidDecision(
                f"decision must be one of {sorted(DECISIONS)}, got {decision!r}"
            )
        self._require_idle(chat)
        run = self._run_of(chat)
        finding_id = request.path_params["finding_id"]
        try:
            finding = await run_in_threadpool(
                partial(
                    record_disposition,
                    run,
                    finding_id,
                    decision=decision,
                    note=str(body.get("note") or ""),
                    by=str(body.get("by") or chat.engineer),
                )
            )
        except KeyError as exc:
            raise UnknownFinding(f"no finding {finding_id!r} in this session") from exc
        except ValueError as exc:
            raise IllegalTransition(str(exc)) from exc
        return JSONResponse(finding.model_dump(mode="json"))

    async def stop(self, request: Request) -> Response:
        """End the turn at the next tool boundary, then end the session (FR-030).

        Stop is idempotent, for the same reason `shutdown` skips a session that already
        has an `ended_at`: a second `session.ended` says nothing new, and rewriting
        `ended_at` moves a time that was already the truth. A pane that presses Stop just
        as the turn finishes on its own must not turn one ended session into two terminal
        events - it gets 202 and the state it already had.
        """
        chat = self._chat(request)
        if chat.state is ChatState.FAILED:
            raise SessionFailed(f"chat {chat.chat_id} failed; start a new session to retry")
        if chat.state is ChatState.RUNNING:
            chat.stop_requested.set()
        elif not _already_ended(chat):
            await run_in_threadpool(self._end_now, chat)
        return JSONResponse(chat.public(), status_code=202)

    async def report(self, request: Request) -> Response:
        chat = self._chat(request)
        path = chat.report_path
        if not path.is_file():
            raise ReportMissing(f"no {REPORT_FILE_NAME} has been rendered for this chat yet")
        return PlainTextResponse(
            path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
        )

    # --- the request ----------------------------------------------------------------

    async def _json(self, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ChatError("the request body is not JSON") from exc
        if not isinstance(body, dict):
            raise ChatError("the request body must be a JSON object")
        return body

    def _chat(self, request: Request) -> ChatSession:
        chat_id = self._uuid(request.path_params["chat_id"], "chat_id")
        chat = self.chats.get(chat_id) if chat_id is not None else None
        if chat is None:
            raise UnknownChat(f"no chat {request.path_params['chat_id']!r} on this backend")
        return chat

    @staticmethod
    def _uuid(raw: Any, field: str) -> UUID | None:
        if raw in (None, ""):
            return None
        try:
            return UUID(str(raw))
        except ValueError as exc:
            raise ChatError(f"{field} must be a uuid, got {raw!r}") from exc

    @staticmethod
    def _last_event_id(request: Request) -> int:
        """`Last-Event-ID` as a `seq`. Anything unreadable replays from the beginning."""
        raw = request.headers.get("last-event-id", "")
        try:
            return max(int(raw), 0)
        except (TypeError, ValueError):
            return 0

    def _settings(self, body: Mapping[str, Any]) -> ProviderSettings:
        """The provider settings for one session: the request, then the environment.

        The settings *file* is never read here - the add-in owns it and passes the key in
        the environment - so `from_env` sees no settings key and resolves `key_source`
        from the environment or reports `none`.
        """
        try:
            return ProviderSettings.from_env(
                provider=body.get("provider") or DEFAULT_PROVIDER,
                model=body.get("model") or None,
                effort=body.get("effort") or None,
            )
        except ValueError as exc:
            raise UnknownProvider(self.redact(str(exc))) from exc

    # --- one chat per run folder -----------------------------------------------------

    def _claim_run_dir(self, run_dir: Path, retry_of: UUID | None) -> None:
        """Refuse a run folder that is already somebody's, before a chat is built for it.

        `ChatSession 1 events.jsonl` (data-model section 7) is not decoration. Every run
        gets its own `EventSink`, whose `seq` starts at 1 and which *appends* to
        `run_dir/events.jsonl`; two runs in one folder therefore write one file whose `seq`
        restarts halfway through. Replay after a `Last-Event-ID` then yields nothing for
        the second session, the live stream drops every event whose `seq` the pane has
        already been shown, and `session.json` holds only the later of the two sessions.

        So: a folder a live chat is reviewing is a 409, and a folder that already holds a
        session is a 400 - unless this request is the Retry that replaces it, which
        `_rotate_previous` moves the old pair aside for rather than writing over.
        """
        live = next(
            (
                chat
                for chat in self.chats.values()
                if chat.run_dir == run_dir and not chat.finished
            ),
            None,
        )
        if live is not None:
            raise RunDirInUse(
                f"chat {live.chat_id} is already reviewing {run_dir}; one chat per run folder"
            )
        if retry_of is None and _session_files(run_dir):
            raise InvalidRunDir(
                f"{run_dir} already holds a review session; retry it with 'retry_of' or "
                f"review into a new run folder"
            )

    def _rotate_previous(self, chat: ChatSession) -> None:
        """Move a retried folder's `events.jsonl` and `session.json` aside, as a pair.

        A retry writes into the folder the session it replaces wrote, and the two cannot
        share one file (`_claim_run_dir`). Both files take the same free index, so the pair
        one session wrote stays a pair - the session `retry_of` names survives as
        `session.1.json` instead of being overwritten by the session replacing it - and a
        chat still pointing at the old stream is moved along with it, so a pane
        reconnecting to it is replayed what that chat wrote rather than what took its
        place.
        """
        existing = _session_files(chat.run_dir)
        if not existing:
            return
        index = _next_free_index(chat.run_dir)
        for path in existing:
            moved = _rotated(path, index)
            path.rename(moved)
            for other in self.chats.values():
                if other.events_path == path:
                    other.events_file = moved

    # --- the review ------------------------------------------------------------------

    def _start_review(self, chat: ChatSession, settings: ProviderSettings) -> ReviewRun:
        """Load the package and bind the tools. Blocking, so it runs off the event loop."""
        self._rotate_previous(chat)
        try:
            adapter = self.provider_factory(settings)
        except Exception as exc:
            raise ProviderFailed.wrapping(exc) from exc
        bridge = chat.bridge or {}
        try:
            run = start_review(
                chat.run_dir,
                chat.run_dir,
                provider=adapter,
                model=settings.model,
                effort=settings.effort,
                key_source=settings.key_source,
                retry_of=self._review_retry_of(chat),
                bridge=bool(bridge),
                pipe_name=str(bridge.get("pipe") or DEFAULT_PIPE_NAME),
                bridge_secret=str(bridge.get("secret") or "") or None,
                bridge_factory=self.bridge_factory,
                callbacks=[chat.publish],
                redact=self.redact,
            )
        except PACKAGE_ERRORS as exc:
            raise InvalidPackage(
                f"{chat.run_dir} is not a readable evidence package: "
                f"{type(exc).__name__}: {self.redact(str(exc))}"
            ) from exc
        run.tools = StoppableTools(run.tools, chat.stop_requested)
        return run

    def _review_retry_of(self, chat: ChatSession) -> UUID | None:
        """The *review session* the retried *chat* wrote, when this backend still holds it."""
        if chat.retry_of is None:
            return None
        previous = self.chats.get(chat.retry_of)
        return previous.review_session_id if previous is not None else None

    def _run_of(self, chat: ChatSession) -> ReviewRun:
        run = chat.run
        if run is None:  # pragma: no cover - a registered chat always has one
            raise SessionFailed(f"chat {chat.chat_id} has no review behind it")
        return run

    def _require_idle(self, chat: ChatSession) -> None:
        """Refuse the two states that cannot take an engineer's turn, with the right 409."""
        if chat.state is ChatState.FAILED:
            raise SessionFailed(
                f"chat {chat.chat_id} failed; retry it as a new session (retry_of)"
            )
        if chat.state is ChatState.RUNNING:
            raise TurnRunning(f"chat {chat.chat_id} is running a turn; wait for it to end")

    # --- the worker ------------------------------------------------------------------

    def _submit(self, chat: ChatSession, action: Callable[[], Any]) -> None:
        """Run one turn on this chat's own thread. One thread per chat, one turn at a time."""
        worker = self._workers.get(chat.chat_id)
        if worker is None:
            worker = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"chat-{chat.chat_id.hex[:8]}"
            )
            self._workers[chat.chat_id] = worker
        worker.submit(self._play, chat, action)

    def _play(self, chat: ChatSession, action: Callable[[], Any]) -> None:
        """One turn, and the state it leaves the chat in. This never raises."""
        try:
            action()
        except TurnStopped:
            self._end_stopped(chat)
        except Exception as exc:
            logger.warning("chat %s failed: %s", chat.chat_id, self.redact(str(exc)))
            self._close_out(chat, exc)
            self._settle(chat, ChatState.FAILED)
        else:
            self._settle(
                chat, ChatState.WAITING_ENGINEER if chat.open_requests else ChatState.ENDED
            )
        finally:
            chat.stop_requested.clear()
            self._render_report(chat)

    def _settle(self, chat: ChatSession, state: ChatState) -> None:
        """Move the chat, unless a shutdown already moved it somewhere terminal."""
        if chat.state is state:
            return
        try:
            chat.to(state)
        except InvalidTransitionError:
            logger.debug("chat %s was already %s", chat.chat_id, chat.state.value)

    def _close_out(self, chat: ChatSession, exc: Exception) -> None:
        """End a session the failure left open, because `failed` still ends (FR-008).

        `ReviewRun._run_turn` writes `error`, `turn.ended {reason: "error"}` and
        `session.ended` for whatever the *provider* raised, and writing a second set for
        that would be a session that ended twice. It is everything else that can raise out
        of a turn - a `finalize()` that could not write the run folder, a failure before
        the first event of the session was emitted - that leaves `ended_at` null with no
        `session.ended` on the stream; and `failed` is terminal, so nothing later comes
        back for it. `ended_at` is the question, not who raised: `_run_turn` clears it when
        the turn begins and only a finalization sets it again.

        Its own failure is swallowed: a run folder that cannot be written is not a reason
        to lose the chat as well, the shutdown pass tries once more, and the chat is about
        to be `failed` either way.
        """
        if chat.run is None or _already_ended(chat):
            return
        try:
            chat.emit(
                "error",
                error_body(
                    error_class=type(exc).__name__,
                    message=self.redact(str(exc)),
                    retryable=True,
                ),
            )
            chat.emit("turn.ended", {"reason": "error"})
            self._finalize_run(chat)
        except Exception as failure:  # noqa: BLE001 - see above
            logger.warning(
                "closing chat %s out failed: %s", chat.chat_id, self.redact(str(failure))
            )

    def _finalize_run(self, chat: ChatSession) -> None:
        run = chat.run
        if run is not None:
            run.finalize()

    def _render_report(self, chat: ChatSession) -> None:
        """Re-render `report.md` from the session the run holds (`GET /report` serves it)."""
        run = chat.run
        if run is None:
            return
        try:
            chat.report_path.write_text(
                render_report(run.session, run.context.ir), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 - see below
            # A report that would not render is not a reason to lose the session: the
            # session file is already written and `report` answers 404 until it is there.
            logger.warning("rendering %s failed: %s", chat.report_path, self.redact(str(exc)))

    def _end_stopped(self, chat: ChatSession) -> None:
        """How a stopped chat closes, wherever the stop was noticed.

        A turn that raised `TurnStopped` at a tool boundary and a chat that was not
        running when Stop arrived end the same way, so they end in the same three lines.
        """
        chat.emit("turn.ended", {"reason": "stopped"})
        self._finalize_run(chat)
        self._settle(chat, ChatState.ENDED)

    def _end_now(self, chat: ChatSession) -> None:
        """Stop a chat that has no turn running: close it, then re-render the report.

        `_play` renders in its own `finally`, so only this path has to ask for it.
        """
        self._end_stopped(chat)
        self._render_report(chat)

    # --- shutdown --------------------------------------------------------------------

    def shutdown(self) -> None:
        """Finalize every live chat before the process goes away (FR-008).

        A chat that is mid-turn gets `turn.ended {reason: "error"}` first: the turn did not
        finish and the session must not read as though it did. What is skipped is a session
        that already has an `ended_at` - finalizing it again would write a second
        `session.ended` saying nothing new - and not simply a chat that is no longer
        running: a chat whose `_close_out` could not write the run folder is `failed` with
        its session still open, and this is its last chance to be closed.
        """
        for chat in list(self.chats.values()):
            try:
                self._finalize_on_exit(chat)
            except Exception as exc:  # noqa: BLE001 - one chat must not block the others
                logger.warning(
                    "finalizing chat %s on shutdown failed: %s",
                    chat.chat_id,
                    self.redact(str(exc)),
                )
        for worker in self._workers.values():
            worker.shutdown(wait=False)
        self._workers.clear()

    def _finalize_on_exit(self, chat: ChatSession) -> None:
        if chat.run is None or _already_ended(chat):
            return
        if chat.state is ChatState.RUNNING:
            chat.emit("turn.ended", {"reason": "error"})
        self._finalize_run(chat)
        self._settle(chat, ChatState.ENDED)
        chat.run.close()


def _already_ended(chat: ChatSession) -> bool:
    """Has this chat's session already been closed out?

    The one question `stop` and `shutdown` both ask before finalizing, so that the answer
    is written once: a session with an `ended_at` is finished, and finalizing it again
    only appends a duplicate `turn.ended`/`session.ended` pair.
    """
    run = chat.run
    return run is not None and run.session.ended_at is not None


def _sse(event: AgentEvent) -> ServerSentEvent:
    """One event as the contract streams it: `id` = `seq`, `event` = `type`, `data` = body."""
    return ServerSentEvent(
        data=json.dumps(event.body, separators=(",", ":"), default=str),
        event=event.type,
        id=str(event.seq),
    )


# --- the application -------------------------------------------------------------------------


def create_app(
    *,
    token: str,
    allow_origin: str,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    provider_factory: Callable[[ProviderSettings], AgentProvider] | None = None,
    list_models: Callable[[ProviderName], list[dict[str, str]]] | None = None,
    bridge_factory: Callable[[str, str | None], Any] | None = None,
    development: bool = False,
    secrets: Sequence[str] | None = None,
) -> Starlette:
    """The chat backend as an ASGI application.

    Args:
        token: The per-launch secret every request must present as a bearer token.
        allow_origin: The pane's virtual-host origin, echoed exactly and never as `*`.
        run_root: The settings run root; every `run_dir` must be strictly inside it.
        provider_factory: Builds the adapter one session talks to. Injected by the tests
            so no unit test needs a key or a network; `build_provider` otherwise.
        list_models: Backs `GET /models`; `list_provider_models` otherwise.
        bridge_factory: Builds the live SOLIDWORKS bridge client for a session that asked
            for one, from the `{pipe, secret}` that session posted. `None` uses the real
            named pipe; `--fail-bridge` passes a forced-failure one.
        development: List the scripted provider in `GET /health` (FR-027).
        secrets: What error text is masked of; the process environment otherwise.
    """
    server = ChatServer(
        token=token,
        allow_origin=allow_origin,
        run_root=Path(run_root),
        provider_factory=provider_factory if provider_factory is not None else build_provider,
        list_models=list_models if list_models is not None else list_provider_models,
        bridge_factory=bridge_factory,
        development=development,
        secrets=secrets,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        yield
        await run_in_threadpool(server.shutdown)

    async def on_chat_error(request: Request, exc: Exception) -> Response:
        error = exc if isinstance(exc, ChatError) else ChatError(str(exc))
        body = error.body()
        body["message"] = server.redact(str(body["message"]))
        return JSONResponse(body, status_code=error.status)

    routes = [
        Route("/health", server.health, methods=["GET"]),
        Route("/models", server.models, methods=["GET"]),
        Route("/sessions", server.create_session, methods=["POST"]),
        Route("/sessions/{chat_id}", server.get_session, methods=["GET"]),
        Route("/sessions/{chat_id}/events", server.events, methods=["GET"]),
        Route("/sessions/{chat_id}/messages", server.post_message, methods=["POST"]),
        Route(
            "/sessions/{chat_id}/evidence/{request_id}",
            server.answer_evidence,
            methods=["POST"],
        ),
        Route(
            "/sessions/{chat_id}/findings/{finding_id}/disposition",
            server.disposition,
            methods=["POST"],
        ),
        Route("/sessions/{chat_id}/stop", server.stop, methods=["POST"]),
        Route("/sessions/{chat_id}/report", server.report, methods=["GET"]),
    ]
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={ChatError: on_chat_error},
        middleware=[
            Middleware(Guard, token=token, origin=allow_origin, redactor=server.redact)
        ],
    )
    app.state.server = server
    return app
