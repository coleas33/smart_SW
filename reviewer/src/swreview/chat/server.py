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
from swreview.benchmark.timing import TIMING_INPUTS
from swreview.bridge.client import DEFAULT_PIPE_NAME, BridgeClient, BridgeError, NamedPipeTransport
from swreview.chat import DEFAULT_ALLOW_ORIGIN, DEFAULT_RUN_ROOT
from swreview.chat.sessions import (
    ChatSession,
    ChatState,
    InvalidTransitionError,
    record_disposition,
    record_timing_live,
    replay_events,
)
from swreview.checks.rms.registry import RMS_FAMILY, RULES
from swreview.checks.rms.run import (
    RMS_SCOPE_RUNS,
    NotACheckError,
    RmsCheckRun,
    RmsRunError,
    RmsScope,
    is_check_folder,
    read_rms_check,
    run_rms_check,
)
from swreview.checks.rules.family import waiver_invalidity
from swreview.checks.rules.run import check_record
from swreview.checks.standards.profile import SETTING_NAME, ProfileError, ProfileUnreadable
from swreview.checks.standards.registry import RULES as STANDARDS_RULES
from swreview.checks.standards.registry import STANDARDS_FAMILY
from swreview.checks.standards.report import document_of, verdict_json
from swreview.checks.standards.run import (
    StandardsCheckRun,
    read_standards_check,
    run_standards_check,
)
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore, ReviewException
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage, UnsupportedSchemaVersionError
from swreview.report.dispositions import DECISIONS, REPORT_FILE_NAME, find_finding
from swreview.report.markdown import render_report
from swreview.report.session import load_session

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


class InvalidTiming(ChatError):
    """A timing body that is not the four human inputs as numbers.

    Named rather than ignored for every key that is not one of the four, because
    `Timing.model_validate` would silently accept a supplied `net_saved_minutes` and
    overwrite the derived figure with it (`contracts/timing.md` section 3, FR-004).
    """

    error_class = "InvalidTiming"


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


# --- what the Model check routes refuse (`contracts/model-check.md`) ---------------------


class UnknownCheck(ChatError):
    """No check run folder of that name under the run root, or none that ran a check.

    The folder name *is* the check id, so a check is addressable after a restart without
    any server-side registry; the price is that an id is a path, and every id-addressed
    route puts it through the same rule a `run_dir` body field goes through. A refused
    path is reported as an unknown check and not as an invalid one, so the route cannot be
    used to find out what else is on the workstation.
    """

    status = 404
    error_class = "UnknownCheck"


class ScopeNotAvailable(ChatError):
    """A rule family this build does not offer the tab (`contracts/model-check.md`)."""

    error_class = "ScopeNotAvailable"


class EmptyNote(ChatError):
    """An exception with no reason is the blanket exclusion Principle VI does not allow."""

    error_class = "EmptyNote"


class RuleNotAcceptable(ChatError):
    """FR-016: only a `fail` rule is waivable, so a `warn` one is refused here as well.

    409 and not 400: the request is well formed and names a real finding; it is the
    finding's rule that cannot take an exception. The page draws no Accept button for one,
    and the route refuses it anyway - a rule that is not waivable must not become waivable
    by going round the page.
    """

    status = 409
    error_class = "RuleNotAcceptable"


class AlreadyAccepted(ChatError):
    """An active exception already covers this condition; a second record would be dead.

    `ExceptionStore.match` returns the first non-retired match, so everything written
    after it is unreachable as well as untrue.
    """

    status = 409
    error_class = "AlreadyAccepted"


class CheckRefused(ChatError):
    """An `RmsRunError` as the contract's error body, keeping the run's own class.

    `EmptyFeatureTree` and `UnreadableExceptions` are named by `contracts/model-check.md`
    and are decided by `checks/rms/run.py`, which is where the reason for each one lives.
    Re-deciding them here would be a second rule about the same condition, so the class
    travels with the exception instead.
    """

    def __init__(self, exc: RmsRunError) -> None:
        super().__init__(str(exc))
        self.error_class = exc.error_class


class ProfileRefused(ChatError):
    """A `ProfileError` as the contract's error body, keeping the profile module's class.

    `ProfileUnreadable` and `ProfileInvalid` are named by `contracts/standards-check.md`
    and are decided by `checks/standards/profile.py`, the one module that owns the schema
    (FR-002). Re-deciding either here would be a second opinion about a file this route
    only passes along, so the class travels with the exception instead.
    """

    def __init__(self, exc: ProfileError) -> None:
        super().__init__(str(exc))
        self.error_class = exc.error_class


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


# --- the timing body (`007-attention-policy-gate/contracts/timing.md` section 3) ---------


def _timing_inputs(body: Mapping[str, Any]) -> dict[str, float]:
    """The four human inputs `body` supplies, or `InvalidTiming` naming what was wrong.

    Every key is optional and `null` means "keep what is recorded", so an engineer corrects
    one number without restating the other three. Anything else is refused **by name**: a
    key that is not one of the four (`net_saved_minutes` first among them, because the net
    is derived and never accepted), a value that is not a number, and a negative one. The
    negative is caught here rather than left to the model so the pane reads one error class
    for every bad body, and nothing is written on any of the four paths.
    """
    unknown = sorted(key for key in body if key not in TIMING_INPUTS)
    if unknown:
        raise InvalidTiming(
            f"a timing body carries only {', '.join(TIMING_INPUTS)}; "
            f"{', '.join(unknown)} is not one of them"
        )
    inputs: dict[str, float] = {}
    for name, value in body.items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidTiming(f"{name} must be a number or null, got {value!r}")
        if value < 0:
            raise InvalidTiming(f"{name} must not be negative, got {value}")
        inputs[name] = float(value)
    return inputs


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


# --- the Model check result (`contracts/model-check.md`) ---------------------------------


OFFERED_SCOPES: tuple[RmsScope, ...] = (RmsScope.part, RmsScope.equations, RmsScope.all)
"""The rule families `POST /checks/rms` runs.

`assembly` is deliberately absent: its rules are in the catalogue and this build can
dispatch them, but they have not been calibrated, so the tab does not offer the scope and
a request naming it is refused rather than answered. Refusing is the point - a check that
returned an uncalibrated assembly verdict would be read as a clean one.
"""


def _offered_scopes(scope: RmsScope) -> tuple[RmsScope, ...]:
    """The rule scopes this route runs for `scope`: the scope's own, minus the uncalibrated.

    `RMS_SCOPE_RUNS` says what a scope means, here as everywhere else, and this subtracts
    the one scope the tab does not offer - so `all` cannot run by alias the rules
    `assembly` is refused by name for. Derived rather than listed again: a second table
    would be a second answer to "what does `all` mean".
    """
    offered = tuple(
        run_scope for run_scope in RMS_SCOPE_RUNS[scope] if run_scope is not RmsScope.assembly
    )
    if not offered:
        raise ScopeNotAvailable(
            f"the {scope.value} rules are not offered by the Model check until they have "
            "been calibrated"
        )
    return offered


def _check_scope(raw: Any) -> RmsScope:
    """The body's `scope` as a rule family, or the refusal that names what is offered.

    Required rather than defaulted: which rule families ran is the first thing a reader of
    a check has to know, and a route that guessed it would answer a question nobody asked.
    """
    offered = ", ".join(scope.value for scope in OFFERED_SCOPES)
    if not isinstance(raw, str) or not raw.strip():
        raise ChatError(f"scope is required and names a rule family: one of {offered}")
    text = raw.strip()
    for scope in OFFERED_SCOPES:
        if scope.value == text:
            return scope
    if text == RmsScope.assembly.value:
        raise ScopeNotAvailable(
            "the assembly rules are not offered by the Model check until they have been "
            f"calibrated; this check runs {offered}"
        )
    raise ChatError(f"scope {text!r} is not a rule family; this backend runs {offered}")


def check_result(check_dir: Path, run: RmsCheckRun) -> dict[str, Any]:
    """One `RmsCheckRun` as the `CheckResult` of `contracts/model-check.md`.

    The package is read again here rather than carried on `RmsCheckRun`: that dataclass is
    what a *check produced*, and the four fields this needs from the package - the graded
    document, when it was extracted and which dump profile wrote it - are the package's
    own evidence and not the run's conclusion. One extra read of a model-check dump is the
    cheaper half of that trade.
    """
    package = load_package(check_dir).package
    exceptions = _exceptions_by_id(check_dir, run.findings)
    carried = run.exceptions_carried_forward
    return {
        "check_id": check_dir.name,
        "run_dir": str(check_dir),
        "document": _checked_document(package, run.documents),
        "extracted_at": package.created_at.isoformat(),
        "profile": package.extractor.profile,
        "grade": run.grade.as_dict(),
        "findings": [_finding_row(finding, exceptions) for finding in run.findings],
        "coverage": run.coverage,
        "subjects": run.subjects,
        "exceptions_carried_forward": {
            "from_run": carried.from_run,
            "count": carried.count,
            "reason": carried.reason,
        },
    }


def _checked_document(package: EvidencePackage, documents: Sequence[str]) -> dict[str, Any] | None:
    """The one part document this check graded, or `None` when it graded several.

    A model-check dump carries the open part, so the tab's check names one document and
    the page can title itself with it. A run that graded two has no single document to
    name, and naming the first would be a claim about which one the page is showing.
    """
    if len(documents) != 1:
        return None
    return _document_row(package, documents[0])


def _document_row(package: EvidencePackage, document_id: str | None) -> dict[str, Any] | None:
    """One document of `package` as the `{id, path, configuration, kind}` a page titles
    itself with, or `None` when the package records no such document."""
    found = next(
        (item for item in package.documents if item.document_id == document_id), None
    )
    if found is None:  # pragma: no cover - the run graded it, so the package carries it
        return None
    return {
        "id": found.document_id,
        "path": found.path,
        "configuration": found.active_configuration,
        "kind": found.kind,
    }


def _exceptions_by_id(
    check_dir: Path, findings: Sequence[Mapping[str, Any]]
) -> dict[str, ReviewException]:
    """The exceptions the findings cite, by id; empty when none of them cites one.

    The finding already names the exception that matched (`report.py`), so this looks the
    records up rather than matching the bindings a second time: a second match would be a
    second opinion about which exception covers a condition.
    """
    wanted = {str(finding["exception_id"]) for finding in findings if finding.get("exception_id")}
    if not wanted:
        return {}
    store = ExceptionStore(check_dir / EXCEPTIONS_FILE_NAME).load()
    return {
        exception.id: exception for exception in store.exceptions if exception.id in wanted
    }


def _with_exception(
    row: dict[str, Any],
    finding: Mapping[str, Any],
    exceptions: Mapping[str, ReviewException],
) -> dict[str, Any]:
    """`row` with the exception the finding cites beside it, when it cites one.

    The same three fields in both families' rows, so it is written once: which exception
    matched, whether it is still `active` and what was accepted are facts about the record
    and not about whose check raised the finding (T099). A finding that cites none gets no
    `exception` key at all, which is what it has always got.
    """
    exception = exceptions.get(str(finding.get("exception_id") or ""))
    if exception is not None:
        row["exception"] = {
            "id": exception.id,
            "state": exception.status,
            "note": exception.note,
        }
    return row


def _finding_row(
    finding: Mapping[str, Any], exceptions: Mapping[str, ReviewException]
) -> dict[str, Any]:
    """One finding as the tab reads it: the `Finding`, its rule, and what it can do.

    `finding` is the feature 001 `Finding` untouched (FR-026). Everything the tab needs
    beyond it - the rule's statement, whether the rule is waivable at all, and the
    exception that matched - sits beside it, so a consumer that only knows feature 001
    sees exactly what it always saw.

    `acceptable` is asked of `checks/rules/family.py`'s one reader, exactly as the
    standards row asks it: which rules may be waived is `RMS_FAMILY.status_by_severity`
    read for `WAIVABLE_STATUS`, and the `"fail"` this line used to spell out was a second
    answer to the question the accept route and `exceptions accept-rms` already decide
    from the descriptor (`checks/rules/family.py`, T099).
    """
    check = str(finding["check"])
    rule = RULES.get(check)
    row: dict[str, Any] = {
        "finding": finding,
        "rule_id": finding["check"],
        "severity": None if rule is None else rule.severity,
        "statement": None if rule is None else rule.statement,
        "observed": finding["observed"],
        "acceptable": waiver_invalidity(RMS_FAMILY, RULES, check) is None,
    }
    return _with_exception(row, finding, exceptions)


# --- the Standards result (`contracts/standards-check.md`) -------------------------------


def standards_result(check_dir: Path, run: StandardsCheckRun) -> dict[str, Any]:
    """One `StandardsCheckRun` as the `StandardsResult` of `contracts/standards-check.md`.

    Four things the shape states rather than leaves to the page, and each of them is a
    release gate's question:

    - the **verdict** replaces feature 003's grade. It carries the counts in every bucket
      and the unresolved check ids in every state, and no letter grade and no single
      number, so a clean headline cannot be rendered without what the run does not cover
      (FR-032).
    - **all sixteen checks** come back whether they applied or not, each with the buckets
      it landed in, so "all sixteen were accounted for" is readable from one array (FR-033).
    - the **profile is `{path, sha256}`**. No profile value travels on any reply (FR-001):
      the reasoning side owns the schema and the page shows which file is in force.
    - **`rebuilt` is always false**, said out loud rather than left implicit, because the
      two rebuild-error checks report counts the macro this feature replaces would have
      refreshed by force-rebuilding.

    The package is read again here for the same reason `check_result` reads it: the root
    document, when it was extracted and which dump profile wrote it are the package's own
    evidence and not the run's conclusion.
    """
    package = load_package(check_dir).package
    exceptions = _exceptions_by_id(check_dir, run.findings)
    carried = run.exceptions_carried_forward
    return {
        "check_id": check_dir.name,
        "run_dir": str(check_dir),
        "family": STANDARDS_FAMILY.check_file_family,
        "document": _document_row(package, package.design.root_assembly_document_id),
        "extracted_at": package.created_at.isoformat(),
        "profile": {"path": run.profile.path, "sha256": run.profile.sha256},
        "extractor_profile": package.extractor.profile,
        "documents_graded": [
            {
                "id": document_id,
                "kind": run.document_kinds.get(document_id),
                "reached_by": run.document_reached_by.get(document_id),
            }
            for document_id in run.documents
        ],
        "verdict": verdict_json(run.verdict),
        "checks": run.checks,
        "findings": [
            _standards_finding_row(finding, exceptions) for finding in run.findings
        ],
        "coverage": run.coverage,
        "subjects": run.subjects,
        "exceptions_carried_forward": {
            "from_run": carried.from_run,
            "count": carried.count,
            "reason": carried.reason,
        },
        "rebuilt": False,
    }


def _standards_finding_row(
    finding: Mapping[str, Any], exceptions: Mapping[str, ReviewException]
) -> dict[str, Any]:
    """One standards finding as the tab reads it: the `Finding`, its check, and what it can do.

    `finding` is the feature 001 `Finding` untouched (FR-026), exactly as `_finding_row`
    leaves an rms one. The two rows differ in the one field whose name is the family's -
    `check` here, `rule_id` there - and in where `acceptable` is decided from, which is why
    they are two functions and not one with a flag.
    """
    check = str(finding["check"])
    rule = STANDARDS_RULES.get(check)
    row: dict[str, Any] = {
        "finding": finding,
        "check": finding["check"],
        "severity": None if rule is None else rule.severity,
        "statement": None if rule is None else rule.statement,
        "observed": finding["observed"],
        "acceptable": _standards_waiver_invalidity(check) is None,
    }
    return _with_exception(row, finding, exceptions)


def _standards_waiver_invalidity(check_id: str) -> str | None:
    """Why `check_id` cannot be waived, or `None` when it is a waivable `error` check.

    The standards family's binding of `checks/rules/family.py`'s one reader, and not a
    second table: `status_by_severity` read for `WAIVABLE_STATUS` is what makes `error`
    waivable and `warning` not, and the line the refusal prints is
    `STANDARDS_FAMILY.waiver_labels`, so the tab and `swreview exceptions accept-standards`
    cannot disagree about one waiver (FR-041, FR-042).
    """
    return waiver_invalidity(STANDARDS_FAMILY, STANDARDS_RULES, check_id)


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

    async def timing(self, request: Request) -> Response:
        """Record the engineer's minutes against this review (`contracts/timing.md` 3).

        `disposition`'s shape, for the same reason: the run holds the session in memory, so
        the write has to reach the live one. The body is validated before `_require_idle`
        so a malformed body is 400 whatever the chat is doing, and the write itself goes to
        the thread pool because it renders a report.
        """
        chat = self._chat(request)
        inputs = _timing_inputs(await self._json(request))
        self._require_idle(chat)
        run = self._run_of(chat)
        recorded = await run_in_threadpool(partial(record_timing_live, run, **inputs))
        return JSONResponse(recorded.model_dump(mode="json"))

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

    # --- the Model check (`contracts/model-check.md`) --------------------------------

    async def run_check(self, request: Request) -> Response:
        """`POST /checks/rms`: grade the dump in `run_dir` and answer the `CheckResult`.

        Synchronous, and no chat: there is no provider, no network call and no turn, so
        the folder is not claimed, nothing is registered and nothing has to be finalized.
        The work is the rule layer over one feature tree - tens of milliseconds - and it
        runs off the event loop because it is file I/O and CPU, not because it is slow.
        """
        body = await self._json(request)
        run_dir = resolve_run_dir(body.get("run_dir"), self.run_root)
        scope = _check_scope(body.get("scope"))
        document_id = body.get("document_id")
        if document_id is not None and not isinstance(document_id, str):
            raise ChatError(
                "document_id is one part document id, or null for every part document"
            )
        result = await run_in_threadpool(
            partial(self._check, run_dir, scope=scope, document_id=document_id or None)
        )
        return JSONResponse(result, status_code=201)

    async def run_standards(self, request: Request) -> Response:
        """`POST /checks/standards`: grade the dump in `run_dir` against `profile_path`.

        The Standards counterpart of `run_check`, and synchronous for the same reasons: no
        provider, no network call and no turn, so the folder is not claimed, nothing is
        registered and nothing has to be finalized (FR-045).

        Two fields and no third. **There is no `scope`**: every standards check runs on
        every run, the document kinds decide which apply, and a check that applies to no
        graded document is an out-of-scope coverage row. A body that names one is refused
        rather than quietly answered, because a verdict whose coverage depended on a
        control nobody recorded is what a release gate must never produce.
        """
        body = await self._json(request)
        run_dir = resolve_run_dir(body.get("run_dir"), self.run_root)
        if "scope" in body:
            raise ChatError(
                "a standards check takes no scope: every check runs on every run, and one "
                "that does not apply to a graded document is an out-of-scope coverage row "
                "rather than a check nobody ran"
            )
        result = await run_in_threadpool(
            partial(self._standards_check, run_dir, body.get("profile_path"))
        )
        return JSONResponse(result, status_code=201)

    async def read_check(self, request: Request) -> Response:
        """`GET /checks/{check_id}`: the check that run folder holds, read back.

        A read, and not a re-evaluation (`contracts/model-check.md` section 1): answering
        it by running the rules again would write a new `session.json` and `report.md`
        every time the page was refreshed, over the evidence `swreview exceptions accept`
        reads by name and an engineer's recorded disposition lives in.

        One route, two families. The answer is **the record's own family shape**
        (`contracts/standards-check.md` section 1): neither family ever answers for the
        other, so a page handed the wrong id reports that it is not its kind of check
        rather than rendering somebody else's result.
        """
        check_dir = self._check_dir(request.path_params["check_id"])
        return JSONResponse(await run_in_threadpool(partial(self._read_any_check, check_dir)))

    async def accept_check_exception(self, request: Request) -> Response:
        """`POST /checks/{check_id}/exceptions/{finding_id}`: accept a rule for this part.

        The exception binds to the part's component instances, its configuration and a
        feature-tree fingerprint, which means it waives the rule **on the part** and not on
        one feature (`contracts/model-check.md`, section 5). It is written through the same
        helpers `swreview exceptions accept-rms` uses, so a waiver written from the tab and
        one written from the command line are one kind of record and not two.

        The finding comes back re-rendered rather than edited in place: only the rule layer
        turns an accepted condition into a `checked_within_scope` finding, so the check is
        run again over the store that was just written and the row for this finding is what
        is returned. That re-run is also what re-renders `report.md`.

        One route serves both families: the record says whose check this is, and that is
        what decides which catalogue answers "may this be waived" and which entry point
        re-renders the folder (`contracts/standards-check.md` section 1).
        """
        check_dir = self._check_dir(request.path_params["check_id"])
        finding_id = str(request.path_params["finding_id"])
        body = await self._json(request)
        note = str(body.get("note") or "").strip()
        if not note:
            raise EmptyNote(
                "an exception states why the condition is accepted; an unexplained one is "
                "a blanket exclusion and is refused"
            )
        family = await run_in_threadpool(partial(self._family_of, check_dir))
        exception_id = await run_in_threadpool(
            partial(
                self._accept_exception,
                check_dir,
                finding_id,
                note=note,
                by=str(body.get("by") or "").strip(),
                family=family,
            )
        )
        result = await run_in_threadpool(partial(self._recheck, check_dir, family))
        # A waived finding keeps its row (Principle VI: never hidden), so this is the same
        # finding rendered as checked within scope rather than a finding that went away.
        row = next(
            (item for item in result["findings"] if item["finding"]["id"] == finding_id), None
        )
        return JSONResponse({"finding": row, "exception_id": exception_id})

    def _check_dir(self, check_id: Any) -> Path:
        """The check run folder `check_id` names, under the run root.

        The folder name is the whole registry, so a check id is a path segment, and it goes
        through the same rule a caller-supplied `run_dir` goes through. Anything the rule
        refuses is reported as an unknown check: the id is caller-supplied, and a route that
        told a caller *why* a path was refused would be a way to probe the workstation.
        """
        raw = str(check_id)
        try:
            directory = resolve_run_dir(str(self.run_root / raw), self.run_root)
        except InvalidRunDir as exc:
            raise UnknownCheck(f"no check {raw!r} under the run root") from exc
        if not directory.is_dir():
            raise UnknownCheck(f"no check {raw!r} under the run root")
        return directory

    def _family_of(self, check_dir: Path) -> str:
        """The family whose check `check_dir` holds, from the record's own stamp.

        A record written before the field existed is a feature 003 model check, which is
        the whole reason the fall-back is named rather than refused: every check folder on
        a workstation that ran this build's predecessor carries no `family` at all.
        """
        try:
            record = check_record(check_dir)
        except NotACheckError as exc:
            raise UnknownCheck(self.redact(str(exc))) from exc
        return str(record.get("family", RMS_FAMILY.check_file_family))

    def _check(
        self, package_dir: Path, *, scope: RmsScope, document_id: list[str] | str | None
    ) -> dict[str, Any]:
        """One evaluation of the package in `package_dir`, as the contract's `CheckResult`.

        `run_rms_check` is the one no-language-model entry point (FR-024): what the tab
        shows and what `swreview check rms` prints cannot be two different evaluations of
        the same part, so this route adds no rule and no finding of its own. Blocking, so
        every caller runs it off the event loop.

        Two things this route states rather than inherits: the rule scopes it runs (the
        uncalibrated assembly rules are refused by name, so they are not run under the
        `all` alias either), and the run root the carry-forward may copy an earlier
        `exceptions.json` from, which is this server's own `--run-root`.
        """
        offered = _offered_scopes(scope)
        try:
            run = run_rms_check(
                package_dir,
                scope=scope,
                document_id=document_id,
                scopes=offered,
                run_root=self.run_root,
            )
        except RmsRunError as exc:
            raise CheckRefused(exc) from exc
        except PACKAGE_ERRORS as exc:
            raise InvalidPackage(
                f"{package_dir} is not a readable evidence package: "
                f"{type(exc).__name__}: {self.redact(str(exc))}"
            ) from exc
        return check_result(package_dir, run)

    def _standards_check(self, package_dir: Path, profile_path: Any) -> dict[str, Any]:
        """One evaluation of the package in `package_dir`, as the `StandardsResult`.

        `run_standards_check` is the one no-language-model entry point (FR-043): what the
        tab shows and what `swreview check standards` prints cannot be two different
        gradings of the same design, so this route adds no check and no finding of its own.
        Blocking, so every caller runs it off the event loop.

        The profile is read and validated **there** and not here (FR-002): the reasoning
        side owns the schema, the page relays the path the host gave it, and expressing the
        schema a second time is the drift this design exists to avoid. What this route
        states is the run root the carry-forward may copy an earlier `exceptions.json`
        from, which is this server's own `--run-root`.
        """
        path = self._profile_path(profile_path)
        try:
            run = run_standards_check(
                package_dir, path, package_dir, run_root=self.run_root
            )
        except ProfileError as exc:
            raise ProfileRefused(exc) from exc
        except RmsRunError as exc:
            raise CheckRefused(exc) from exc
        except PACKAGE_ERRORS as exc:
            raise InvalidPackage(
                f"{package_dir} is not a readable evidence package: "
                f"{type(exc).__name__}: {self.redact(str(exc))}"
            ) from exc
        return standards_result(package_dir, run)

    @staticmethod
    def _profile_path(raw: Any) -> str:
        """The body's `profile_path`, or the profile module's own refusal for an absent one.

        Reported as `ProfileUnreadable` rather than as a malformed request because that is
        what it is to the engineer: the host sends the configured path and sends null when
        there is none, and "no profile is configured" is one condition with one name
        (`contracts/standards-check.md` section 1).
        """
        if not isinstance(raw, str) or not raw.strip():
            raise ProfileRefused(
                ProfileUnreadable(
                    "profile_path is required and names the standards profile this design "
                    f"is graded against; the {SETTING_NAME} setting configures it, and "
                    "there is no default"
                )
            )
        return raw.strip()

    def _read_check(self, check_dir: Path) -> dict[str, Any]:
        """The check `check_dir` holds, as the contract's `CheckResult`. Nothing is run.

        The folder is the whole registry, so this is the whole read: `session.json` holds
        the findings, the coverage and therefore the grade, and `check.json` holds what it
        does not - the scope, the documents graded, the subjects beside each finding, and
        what the carry-forward did.
        """
        run = self._recorded_check(check_dir)
        try:
            return check_result(check_dir, run)
        except PACKAGE_ERRORS as exc:
            raise InvalidPackage(
                f"{check_dir} is not a readable evidence package: "
                f"{type(exc).__name__}: {self.redact(str(exc))}"
            ) from exc

    def _recorded_check(self, check_dir: Path) -> RmsCheckRun:
        """The check recorded in `check_dir`, or `UnknownCheck` naming what it holds.

        A folder that was never checked, one holding a record this build cannot read, and
        one whose session is no longer the one its record describes are all the same
        answer to the caller: there is no such check here.
        """
        try:
            return read_rms_check(check_dir)
        except NotACheckError as exc:
            raise UnknownCheck(self.redact(str(exc))) from exc

    def _read_any_check(self, check_dir: Path) -> dict[str, Any]:
        """The check `check_dir` holds, in **its own** family's shape. Nothing is run."""
        if self._family_of(check_dir) == STANDARDS_FAMILY.check_file_family:
            return self._read_standards_check(check_dir)
        return self._read_check(check_dir)

    def _read_standards_check(self, check_dir: Path) -> dict[str, Any]:
        """The standards check `check_dir` holds, as the `StandardsResult`. Nothing is run.

        The read half of the same bargain `_read_check` makes: `session.json` holds the
        findings and the coverage, and `check.json` holds what it does not - the documents
        and their kinds, the profile identity, the verdict, the subjects and what the
        carry-forward did - so answering a `GET` writes nothing over the file an engineer's
        recorded disposition lives in.
        """
        run = self._recorded_standards_check(check_dir)
        try:
            return standards_result(check_dir, run)
        except PACKAGE_ERRORS as exc:
            raise InvalidPackage(
                f"{check_dir} is not a readable evidence package: "
                f"{type(exc).__name__}: {self.redact(str(exc))}"
            ) from exc

    def _recorded_standards_check(self, check_dir: Path) -> StandardsCheckRun:
        """The standards check recorded in `check_dir`, or `UnknownCheck`.

        A folder that was never checked, one holding a record this build cannot read, one
        whose session is no longer the one its record describes and one holding the *other*
        family's check are all the same answer to the caller: there is no such standards
        check here.
        """
        try:
            return read_standards_check(check_dir)
        except NotACheckError as exc:
            raise UnknownCheck(self.redact(str(exc))) from exc

    def _recheck(self, check_dir: Path, family: str) -> dict[str, Any]:
        """Evaluate a check folder again, exactly as the check that wrote it was run.

        What Accept needs and a read does not: an exception accepted a moment ago has to
        read as checked within scope, and only `report.py` renders that, so the rules run
        again over the store that was just written - which is also what re-renders
        `report.md`. The scope and the document selection come off the folder's own check
        record, so what a scope means still has one answer.

        One field does differ from the first answer, and honestly:
        `exceptions_carried_forward` then reports that the folder already holds its own
        store, because it does - that is a different statement from "there was none".

        A standards folder is re-run against the profile **its own record names**, which is
        the only profile this grading was ever against: re-reading it is what makes the
        re-render the same evaluation, and a profile that has since moved or changed
        refuses by name rather than silently grading against another standard (FR-002).
        """
        if family == STANDARDS_FAMILY.check_file_family:
            return self._standards_check(
                check_dir, self._recorded_standards_check(check_dir).profile.path
            )
        record = self._recorded_check(check_dir)
        return self._check(
            check_dir, scope=record.scope, document_id=record.documents or None
        )

    def _accept_exception(
        self, check_dir: Path, finding_id: str, *, note: str, by: str, family: str
    ) -> str:
        """Write the exception for `finding_id` and return its id. Blocking.

        The helpers are imported from the command line rather than copied: they are what
        `exceptions accept-rms` decides an acceptance with, and a second copy of "which
        rule may be waived", "is this condition already covered" and "accept or re-bind"
        is exactly the drift that would let the tab and the command line disagree about
        one waiver. The import is inside the function so `chat.server` stays importable
        without pulling in typer, as `build_provider` already does.

        Only one of the five is a family's own: which checks may be waived at all. The
        folder's record says whose check this is, and that is what picks the catalogue -
        everything after it (is this condition already covered, accept or re-bind, who
        accepted it) is the same question in both families and is asked once.
        """
        from swreview.cli import (
            _accept_or_reaccept,
            _default_user,
            _rms_waiver_invalidity,
            _store_for,
            _uncovered,
        )

        invalidity_of = (
            _standards_waiver_invalidity
            if family == STANDARDS_FAMILY.check_file_family
            else _rms_waiver_invalidity
        )
        session_file = check_dir / SESSION_FILE_NAME
        if not session_file.is_file():
            raise UnknownCheck(
                f"{check_dir.name} holds no {SESSION_FILE_NAME}: no check has run in it"
            )
        session = load_session(session_file)
        try:
            finding = find_finding(session, finding_id)
        except KeyError as exc:
            raise UnknownFinding(
                f"no finding {finding_id!r} in check {check_dir.name}"
            ) from exc
        invalidity = invalidity_of(finding.check)
        if invalidity is not None:
            raise RuleNotAcceptable(
                f"{finding.check} cannot be accepted: it is {invalidity}. Only a rule the "
                "method grades as a failure is waivable"
            )
        try:
            store, evidence = _store_for(check_dir)
        except PACKAGE_ERRORS as exc:
            raise InvalidPackage(
                f"{check_dir} is not a readable evidence package: "
                f"{type(exc).__name__}: {self.redact(str(exc))}"
            ) from exc
        # A standards waiver is bound to the document it was accepted on as well as to the
        # instances, because a drawing finding has no instances at all and two drawings'
        # waivers would otherwise be indistinguishable (FR-041, RK-11).
        document_id = (
            document_of(finding) if family == STANDARDS_FAMILY.check_file_family else None
        )
        store.refresh(evidence)
        pending = _uncovered(store, evidence, [finding], document_id=document_id)
        if not pending:
            raise AlreadyAccepted(
                f"an active exception already covers {finding.check} on these components "
                f"in configuration {finding.configuration}; one condition keeps one record"
            )
        [(target, retained)] = pending
        exception = _accept_or_reaccept(
            store,
            evidence,
            target,
            retained,
            by=by or _default_user(),
            note=note,
            document_id=document_id,
        )
        store.save()
        return exception.id

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

        A Model check's folder is the one other exception, and for the same reason read
        the other way: a check writes `session.json` and **no** `events.jsonl`, so there
        is no stream for a review to restart the `seq` of. Handing the check package to a
        review is the last step of User Story 6, and refusing it would mean no folder a
        check ran in could ever be reviewed. `_rotate_previous` still moves the check's
        session aside, so the check's record survives as `session.1.json` rather than
        being written over, and the folder stops answering `GET /checks/{check_id}`
        because its `check.json` no longer names the session that is in it.
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
        if retry_of is None and _session_files(run_dir) and not is_check_folder(run_dir):
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
    remodel_bridge_factory: Callable[[str, str | None], Any] | None = None,
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
        remodel_bridge_factory: The same, for the Remodel tab's `remodel.*` client
            (`contracts/backend-remodel.md`). A separate factory because it is a separate
            client over a separate secret: `RemodelSecret` authorizes the twelve `remodel.*`
            commands and nothing else, and a review's bridge authorizes none of them.
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

    # Imported here rather than at module scope so `chat/remodel.py` may import this
    # module's door - `ChatError`, `resolve_run_dir`, `PACKAGE_ERRORS` - without the two
    # importing each other. The Remodel routes are a separate module because a re-model is
    # not a chat: no turn, no evidence request, no disposition (`backend-remodel.md`).
    from swreview.chat.remodel import RemodelServer, remodel_routes

    remodel = RemodelServer(
        run_root=Path(run_root),
        redact=server.redact,
        settings=server._settings,
        bridge_factory=remodel_bridge_factory,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        yield
        await run_in_threadpool(remodel.shutdown)
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
        Route("/sessions/{chat_id}/timing", server.timing, methods=["POST"]),
        Route("/sessions/{chat_id}/stop", server.stop, methods=["POST"]),
        Route("/sessions/{chat_id}/report", server.report, methods=["GET"]),
        # The Model check tab (`contracts/model-check.md`) and the Standards tab
        # (`contracts/standards-check.md`). The two literal paths are listed first so they
        # are matched before the `{check_id}` pattern that follows them; the read and the
        # accept routes serve both families and answer in the record's own shape.
        Route("/checks/rms", server.run_check, methods=["POST"]),
        Route("/checks/standards", server.run_standards, methods=["POST"]),
        Route("/checks/{check_id}", server.read_check, methods=["GET"]),
        Route(
            "/checks/{check_id}/exceptions/{finding_id}",
            server.accept_check_exception,
            methods=["POST"],
        ),
        # The Remodel tab (`contracts/backend-remodel.md`), whose nine routes are the
        # pipeline's whole surface.
        *remodel_routes(remodel),
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
    app.state.remodel = remodel
    return app
