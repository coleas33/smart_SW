"""The Remodel tab's nine loopback routes (`contracts/backend-remodel.md`, T134b).

Tab 5 asks the backend for nine things, and this module is all nine. It exists as its own
module beside `chat/server.py` rather than inside it because a re-model is not a chat: it
has no turn, no evidence request and no disposition, and the only pieces the two share are
the door, the path rule and the event stream - which are imported here and not copied.

**Why the bridge is called from Python at all.** The division of labour is the wiring
brief's and is not re-decided here: every `remodel.*` command goes out through the one
`bridge/remodel_client.py::RemodelClient` there is, so there is one composer of those
requests, one mapping from `error_code` to a class, and one holder of the `RemodelSecret`.
What the add-in does in process - the two `SwReviewDump` ModelCheck dumps and activating
the copy in the seat - it does because the extractor needs the STA thread and the
`ISldWorks` that live in SOLIDWORKS, not because the seat is anybody's second opinion.

**The folder is the state, and the job is only what is running.** `POST /remodel/open`
writes `source-attestation.json` and `open.json` before it answers, so `POST /remodel/plan`
and `POST /remodel/runs` rebuild the runner's inputs from the run folder alone. Nothing a
route needs is held between two requests except the live job itself: the pane can be
restarted, the pipeline is stateless, and a run that was interrupted is read off disk
rather than remembered.

**One worker thread per run, one run per folder.** A run is a blocking sequence of bridge
calls, so it runs on its own single-threaded executor exactly the way a chat turn does
(`ChatServer._submit`), and the event loop stays free to answer the poll. The one place
this is more than a chat is the **package-after rendezvous**: `run_remodel` takes
`dump_after` as a callable because the after-dump is a reading of the document as the apply
phase leaves it, the dumper is the add-in, and so the worker blocks on a `threading.Event`
with a timeout. On expiry it raises `PackageAfterTimeout`, which `run_remodel` reports on
the stream, records on the plan and finalizes as `failed` **with the change log intact**.

**No route constructs a provider.** `remodel/runner.py::build_provider` is the remodel run's
one entry point to an adapter (FR-045); it builds none itself but delegates to
`cli.provider_factory`, the one construction body (owner decision 4A, 2026-09-23). It is reached
only from `POST /remodel/runs`, and a run whose adapter cannot be built records the absence and
applies the deterministic plan anyway.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from swreview.agent.events import EVENTS_FILE_NAME
from swreview.agent.providers import AgentEvent
from swreview.agent.settings import ProviderSettings
from swreview.bridge.client import (
    DEFAULT_PIPE_NAME,
    BridgeDocumentClosedError,
    BridgeError,
)
from swreview.bridge.remodel_client import CircuitOpen, RemodelClient, RemodelError
from swreview.chat.server import PACKAGE_ERRORS, ChatError, resolve_run_dir
from swreview.chat.sessions import EventStream, replay_events
from swreview.checks.rms.run import RmsRunError
from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage
from swreview.remodel.apply_log import ChangeRecord, changes_path
from swreview.remodel.artifacts import NOT_MODEL_CHECK, carry_forward_exceptions
from swreview.remodel.attestation import (
    attestation_from_open,
    read_attestation,
    write_attestation,
)
from swreview.remodel.geometry import reading_from_reply
from swreview.remodel.plan import (
    PACKAGE_BEFORE,
    RemodelPlan,
    part_document_ids,
    plan_path,
)
from swreview.remodel.runner import plan_run, run_remodel
from swreview.remodel.scope import ScopeGate, ScopeSignals
from swreview.remodel.summary import plan_summary_row
from swreview.remodel.tolerances import IDENTITY

__all__ = [
    "OPEN_FILE_NAME",
    "PACKAGE_AFTER",
    "BridgeUnavailable",
    "DocumentDirty",
    "ExternalReferences",
    "NotAPart",
    "NotModelCheck",
    "PackageAfterRefused",
    "PackageAfterTimeout",
    "PackageMissing",
    "RemodelJob",
    "RemodelServer",
    "ResumeRefused",
    "RunFolderFailed",
    "RunInProgress",
    "RunNotPlanned",
    "ScopeRefused",
    "UnknownJob",
    "copy_path_for",
    "remodel_routes",
]

logger = logging.getLogger("swreview.chat.remodel")

OPEN_FILE_NAME = "open.json"
"""What `remodel.open` recorded, so the two routes after it need no memory of the call."""

PACKAGE_AFTER = "package-after.json"
"""The after-dump's name in the run folder (`contracts/run-artifacts.md`)."""

MODEL_CHECK_PROFILE = "model_check"
"""The dump profile both of this run's packages carry. Spelled as `artifacts.py` and
`agent/runner.py` spell it, because it is a value in the IR and not a name to import."""

COPY_FOLDER_NAME = "copy"
COPY_SUFFIX = "-RMS"
PART_EXTENSION = ".SLDPRT"

DEFAULT_PACKAGE_AFTER_TIMEOUT_S = 600.0
"""How long a run waits for the add-in's after-dump before it gives up.

Ten minutes, because the dump is another process's thread doing real work on a large part,
and a run that waited forever would hold a worker thread and a document open with nobody
left to answer it. Injectable so a test can drive the expiry without waiting."""

JOB_RUNNING = "running"
JOB_AWAITING = "awaiting_package_after"
JOB_FINISHED = "finished"
JOB_FAILED = "failed"


# --- what the page is allowed to see -----------------------------------------------------


class NotAPart(ChatError):
    """`not_a_part`. v1 reorganizes a part's feature tree and nothing else."""

    error_class = "NotAPart"


class DocumentDirty(ChatError):
    """`source_dirty`. The source is never saved by this feature, so the engineer saves it."""

    error_class = "DocumentDirty"


class ExternalReferences(ChatError):
    """`external_refs`: `ListExternalFileReferencesCount2() != 0`."""

    error_class = "ExternalReferences"


class ScopeRefused(ChatError):
    """The scope gate refused, or the bridge says the scope was not probed or has changed.

    The message names **every** failing signal and never only the first: a message that
    named one of two reasons would send the engineer back twice (`research.md` R4.1).
    """

    error_class = "ScopeRefused"


class RunFolderFailed(ChatError):
    """The copy could not be made, tagged, or read back - and every unknown `error_code`.

    An unknown token stays unknown: it is reported with the host's own sentence rather than
    guessed into the nearest class, the same rule `bridge/remodel_client.py` applies one
    layer down.
    """

    error_class = "RunFolderFailed"


class BridgeUnavailable(ChatError):
    """The circuit is open or the transport failed, so the call was never sent."""

    status = 502
    error_class = "BridgeUnavailable"
    retryable = True


class PackageMissing(ChatError):
    """`package-before.json` is not in the run folder: the add-in's dump has not landed."""

    error_class = "PackageMissing"


class NotModelCheck(ChatError):
    """The dump in the run folder is not a ModelCheck dump of exactly one part."""

    error_class = "NotModelCheck"


class RunNotPlanned(ChatError):
    """There is no `plan.json`, or the plan is past `planned`. Plan first, then start."""

    status = 409
    error_class = "RunNotPlanned"


class ResumeRefused(ChatError):
    """The folder already holds a change log. **A run never auto-resumes** (FR-031).

    After a lost session the copy and the log survive on disk and recovery is manual: a
    resumed run over a tree nobody re-verified is exactly the wrong risk, and the tree after
    a crash is whatever the change in flight left behind.
    """

    status = 409
    error_class = "ResumeRefused"


class RunInProgress(ChatError):
    """One run per folder, refused rather than queued, so the pane can say so."""

    status = 409
    error_class = "RunInProgress"


class UnknownJob(ChatError):
    """No job of that id on this backend."""

    status = 404
    error_class = "UnknownJob"


class PackageAfterRefused(ChatError):
    """The posted path is not this run's after-dump, or does not load as one."""

    error_class = "PackageAfterRefused"


class PackageAfterTimeout(RuntimeError):
    """The add-in's after-dump never arrived.

    Not a `ChatError`: nobody is waiting on an HTTP reply for it. It is raised inside the
    run, on the worker thread, and `run_remodel` turns it into a reported error, a
    `PlanCoverage` row and a `failed` run whose change log is untouched.
    """


BRIDGE_REFUSALS: Mapping[str, type[ChatError]] = {
    "not_a_part": NotAPart,
    "source_dirty": DocumentDirty,
    "external_refs": ExternalReferences,
    "scope_not_probed": ScopeRefused,
    "scope_changed": ScopeRefused,
    "copy_failed": RunFolderFailed,
    "copy_exists": RunFolderFailed,
    "tag_failed": RunFolderFailed,
}
"""The `error_code` table of `contracts/bridge-remodel.md` as the page's refusal classes.

Every token with no row here is `RunFolderFailed` carrying the host's sentence. The table
is short on purpose: the codes it does not list are the ones a run meets *after* the copy
is open, and those are the executor's to record against the change it was making rather
than an HTTP refusal for a route to answer."""

PREEXISTING_REBUILD_ERRORS = "preexisting_rebuild_errors"
"""The one refusal that is not an error body; see `RemodelServer._open`."""


def _refusal(exc: RemodelError) -> ChatError:
    """The host's `error_code` as the class the page switches on, with its own sentence."""
    return BRIDGE_REFUSALS.get(exc.error_code, RunFolderFailed)(str(exc))


def _unavailable(what: str, detail: str | None = None) -> BridgeUnavailable:
    return BridgeUnavailable(
        f"the SOLIDWORKS bridge did not answer {what}"
        + (f": {detail}" if detail else "; nothing was sent")
    )


def _answered(reply: Any, what: str) -> Any:
    """One bridge reply, or the refusal that says it never came.

    An open circuit is a value and not an exception on the client
    (`bridge/remodel_client.py`), because the executor records it against the change it was
    making; a route has no change to record it against, so here it becomes the refusal the
    page draws a Retry on.
    """
    if isinstance(reply, CircuitOpen):
        raise _unavailable(what, reply.last_error)
    return reply


def _call(what: str, action: Callable[..., Any], *args: Any) -> Any:
    """Send one command and name its failure: a refusal, or a bridge that is not there."""
    try:
        return _answered(action(*args), what)
    except RemodelError as exc:
        raise _refusal(exc) from exc
    except BridgeError as exc:
        raise _unavailable(what, str(exc)) from exc


def copy_path_for(run_dir: Path, source_path: str) -> Path:
    """`<run>/copy/<name>-RMS.SLDPRT`, the convention `Rms/RemodelCopy.cs::CopyPathFor` writes.

    The copy lives **only** in the run folder: it never sits beside the source, because one
    bad path join beside a source inside an EPDM vault writes into the vault. The name is
    derived here rather than posted by the pipeline so that the caller cannot name the file
    the bridge is about to create - the host still refuses anything outside the run folder
    (`AssertSaveTarget`), and this is the other half of that agreement.
    """
    name = Path(source_path.strip()).stem
    if not name:
        raise RunFolderFailed(f"{source_path!r} has no file name to build a copy name from")
    return run_dir / COPY_FOLDER_NAME / f"{name}{COPY_SUFFIX}{PART_EXTENSION}"


# --- one run, and the thread it happens on ------------------------------------------------


@dataclass
class RemodelJob:
    """One running re-model: its stream, its stop flag and its package-after rendezvous.

    The job holds what is *running*. Everything a reader needs about the run itself - the
    plan, its state, the change log - is in the run folder and is read from there, so a job
    that has gone away does not take the run's answers with it.
    """

    job_id: str
    run_dir: Path
    timeout_s: float = DEFAULT_PACKAGE_AFTER_TIMEOUT_S
    stream: EventStream = field(default_factory=EventStream)
    """The live fan-out, fed as an `EventSink` listener; the file is the run's own."""

    stop: threading.Event = field(default_factory=threading.Event)
    """Set by `POST .../stop`; read by `apply_changes` **between** changes."""

    arrived: threading.Event = field(default_factory=threading.Event)
    """Set when the add-in's after-dump has been handed over, or abandoned at shutdown."""

    package: EvidencePackage | None = None
    state: str = JOB_RUNNING
    error: str | None = None

    # --- the stream ---------------------------------------------------------------

    def publish(self, event: AgentEvent) -> None:
        """Hand one event to every live listener. Registered as `callbacks=[job.publish]`."""
        self.stream.publish(event)

    # --- the rendezvous -----------------------------------------------------------

    def wait_for_package_after(self) -> EvidencePackage:
        """Block until the add-in posts the after-dump, or refuse to wait any longer.

        This is `run_remodel`'s `dump_after`. The run is between phase C and the grade, the
        copy is open and every change is recorded, so the only two honest outcomes are the
        package or an exception: returning a stale or empty one would grade the wrong tree.
        """
        self.state = JOB_AWAITING
        try:
            arrived = self.arrived.wait(self.timeout_s)
            package = self.package
            if not arrived or package is None:
                raise PackageAfterTimeout(
                    f"{PACKAGE_AFTER} never arrived: the add-in had "
                    f"{self.timeout_s:g}s to dump the copy after the last change and the "
                    "run cannot be graded without it"
                )
            return package
        finally:
            if self.state == JOB_AWAITING:
                self.state = JOB_RUNNING

    def deliver(self, package: EvidencePackage) -> None:
        self.package = package
        self.arrived.set()

    def abandon(self) -> None:
        """Release a waiting run at shutdown: the wait ends and the run fails honestly."""
        self.arrived.set()

    # --- what the poll reads ------------------------------------------------------

    @property
    def awaiting(self) -> str | None:
        return "package_after" if self.state == JOB_AWAITING else None

    @property
    def live(self) -> bool:
        return self.state in (JOB_RUNNING, JOB_AWAITING)

    def finish(self) -> None:
        self.state = JOB_FINISHED

    def fail(self, message: str) -> None:
        self.state = JOB_FAILED
        self.error = message


# --- reading the run folder ----------------------------------------------------------------


def _changes(run_dir: Path) -> tuple[ChangeRecord, ...]:
    """Every readable line of `changes.jsonl`, in the order it was written.

    Tolerant of an unreadable line, for the reason `replay_events` is: the file is being
    appended to by another thread while this reads it, and a torn final line is a poll that
    arrived mid-write, not a corrupt log. `read_changes` reads the whole file and refuses
    one - which is the right answer for a reader of a finished run and the wrong one for a
    progress poll.
    """
    path = changes_path(run_dir)
    if not path.is_file():
        return ()
    records: list[ChangeRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            records.append(ChangeRecord.model_validate_json(text))
        except ValidationError:
            continue
    return tuple(records)


def _plan_facts(run_dir: Path) -> tuple[str | None, int]:
    """`plan.json`'s state and how many changes it plans, without validating the whole plan.

    `record_state` rewrites the file in place at every transition, so a poll can land on a
    half-written one; that reads as an unknown state for one poll rather than as an error,
    because unknown stays unknown and the next poll answers.
    """
    path = plan_path(run_dir)
    if not path.is_file():
        return None, 0
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 0
    if not isinstance(body, Mapping):
        return None, 0
    state = body.get("state")
    changes = body.get("changes")
    return (
        state if isinstance(state, str) else None,
        len(changes) if isinstance(changes, list) else 0,
    )


def _package(path: Path, missing: type[ChatError], wrong: type[ChatError]) -> EvidencePackage:
    """One of the run's two dumps, or the refusal naming what is wrong with it.

    A dump at another profile and a dump of two parts are both `wrong`: the re-modeler's
    packages are the ModelCheck dumps of **one** copy, and grading anything else would say
    something untrue about what was graded.
    """
    if not path.is_file():
        raise missing(f"{path.name} is not in {path.parent}; the dump has not been written")
    try:
        package = EvidencePackage.model_validate_json(path.read_bytes())
    except PACKAGE_ERRORS as exc:
        raise wrong(f"{path.name} is not a readable evidence package: {exc}") from exc
    if package.extractor.profile != MODEL_CHECK_PROFILE:
        raise wrong(
            NOT_MODEL_CHECK.format(
                side="before" if path.name == PACKAGE_BEFORE else "after",
                profile=package.extractor.profile,
                name=path.name,
            )
        )
    try:
        parts = part_document_ids(package)
    except ValueError as exc:
        raise wrong(f"{path.name}: {exc}") from exc
    if len(parts) != 1:
        raise wrong(
            f"{path.name} carries {len(parts)} part documents ({', '.join(parts)}); the "
            "re-modeler's subject is one part opened alone"
        )
    return package


def _open_record(run_dir: Path) -> Mapping[str, Any]:
    """What `POST /remodel/open` wrote down, or the refusal that the run never opened one."""
    path = run_dir / OPEN_FILE_NAME
    if not path.is_file():
        raise RunFolderFailed(
            f"{OPEN_FILE_NAME} is not in {run_dir}: no copy of this run has been opened, so "
            "there is no baseline, no geometry reading and no scope to plan from"
        )
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunFolderFailed(f"{OPEN_FILE_NAME} could not be read: {exc}") from exc
    if not isinstance(body, Mapping):
        raise RunFolderFailed(f"{OPEN_FILE_NAME} does not hold an object")
    return body


# --- the request ---------------------------------------------------------------------------


async def _json(request: Request) -> Mapping[str, Any]:
    """The body as an object, or the contract's `InvalidRequest`.

    The same three lines `ChatServer._json` is; not shared, because sharing them would mean
    either a second class holding a method that uses no state or an import of a private one.
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise ChatError("the request body is not JSON") from exc
    if not isinstance(body, dict):
        raise ChatError("the request body must be a JSON object")
    return body


def _text(raw: Any, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ChatError(f"{field_name} is required and must be a non-empty string")
    return raw.strip()


def _signals(raw: Any) -> ScopeSignals:
    """The bridge's `scope_signals` block as the typed rows the gate decides from."""
    if not isinstance(raw, Mapping):
        raise RunFolderFailed(
            "the bridge answered without a scope_signals block, so there is nothing to "
            "decide this part's scope from"
        )
    try:
        return ScopeSignals(**dict(raw))
    except ValidationError as exc:
        raise RunFolderFailed(f"the bridge's scope_signals could not be read: {exc}") from exc


def _rebuild_error_count(detail: Any) -> int | None:
    """The count a `preexisting_rebuild_errors` refusal carried, or `None`.

    Unknown is not zero. A part whose rebuild-error count could not be read has no baseline
    to attribute changes against, and the host's own handler says exactly that rather than
    reporting a clean part.
    """
    if not isinstance(detail, Mapping):
        return None
    for name in ("rebuild_error_count", "count"):
        value = detail.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


# --- the server -------------------------------------------------------------------------------


class RemodelServer:
    """The nine routes, the live jobs behind them, and the worker thread each run owns."""

    def __init__(
        self,
        *,
        run_root: Path | str,
        redact: Callable[[str], str],
        settings: Callable[[Mapping[str, Any]], ProviderSettings],
        bridge_factory: Callable[[str, str | None], Any] | None = None,
        package_after_timeout: float = DEFAULT_PACKAGE_AFTER_TIMEOUT_S,
    ) -> None:
        self.run_root = Path(run_root)
        self.redact = redact
        self.settings = settings
        self.bridge_factory = bridge_factory
        self.package_after_timeout = package_after_timeout
        self.jobs: dict[str, RemodelJob] = {}
        self._workers: dict[str, ThreadPoolExecutor] = {}

    # --- endpoints ------------------------------------------------------------------

    async def probe(self, request: Request) -> Response:
        """`POST /remodel/probe`: read the scope signals and let the pure gate decide.

        The bridge reads and this decides, which is what makes the refusal table
        table-testable with no seat and what keeps every scope refusal ahead of the copy
        (FR-001). An empty `refusals` is the only ok: an unread signal is never a pass.
        """
        body = await _json(request)
        source_path = _text(body.get("source_path"), "source_path")
        client = self._client(body)
        return JSONResponse(
            await run_in_threadpool(partial(self._probe, client, source_path))
        )

    async def open_copy(self, request: Request) -> Response:
        """`POST /remodel/open`: copy the source, open the copy, and write the run's baseline."""
        body = await _json(request)
        run_dir = resolve_run_dir(body.get("run_dir"), self.run_root)
        source_path = _text(body.get("source_path"), "source_path")
        probe_id = _text(body.get("probe_id"), "probe_id")
        configuration = body.get("configuration")
        client = self._client(body)
        return JSONResponse(
            await run_in_threadpool(
                partial(
                    self._open,
                    client,
                    run_dir,
                    source_path,
                    probe_id,
                    configuration if isinstance(configuration, str) else None,
                )
            )
        )

    async def plan(self, request: Request) -> Response:
        """`POST /remodel/plan`: phase A over the copy's dump, filed as `plan.json` rev 1."""
        body = await _json(request)
        run_dir = resolve_run_dir(body.get("run_dir"), self.run_root)
        return JSONResponse(await run_in_threadpool(partial(self._plan, run_dir)))

    async def start_run(self, request: Request) -> Response:
        """`POST /remodel/runs`: phases B, C and D on a worker thread, to completion.

        There is no approve-each-change mode and no parameter for one (FR-045): the run
        goes to completion and reports, and the engineer's only lever is Stop.
        """
        body = await _json(request)
        run_dir = resolve_run_dir(body.get("run_dir"), self.run_root)
        settings = self.settings(body)
        client = self._client(body)
        job = await run_in_threadpool(partial(self._start, run_dir, client, settings))
        return JSONResponse({"job_id": job.job_id, "chat_id": job.job_id}, status_code=201)

    async def run_state(self, request: Request) -> Response:
        """`GET /remodel/runs/{job_id}`: what the pipeline's poll loop reads."""
        job = self._job(request)
        return JSONResponse(await run_in_threadpool(partial(self._state, job)))

    async def run_events(self, request: Request) -> Response:
        """`GET /remodel/runs/{job_id}/events`: the run's stream, replayed after `after`.

        A poll and not an SSE stream, because the consumer is the add-in's poll loop and it
        is already asking for the status on the same beat. The file is the same
        `events.jsonl` the pane's review stream replays, read with the same function.
        """
        job = self._job(request)
        after = self._after(request)
        events = await run_in_threadpool(
            lambda: list(replay_events(job.run_dir / EVENTS_FILE_NAME, after=after))
        )
        return JSONResponse(
            {
                "events": [event.model_dump(mode="json") for event in events],
                "next": events[-1].seq if events else after,
            }
        )

    async def package_after(self, request: Request) -> Response:
        """`POST /remodel/runs/{job_id}/package-after`: hand the run the add-in's after-dump."""
        job = self._job(request)
        body = await _json(request)
        path = _text(body.get("path"), "path")
        await run_in_threadpool(partial(self._deliver, job, path))
        return JSONResponse({"ok": True})

    async def stop_run(self, request: Request) -> Response:
        """`POST /remodel/runs/{job_id}/stop`: set the flag the apply loop reads.

        Idempotent, like `POST /sessions/{chat_id}/stop`: a second press says nothing new,
        and a run that has already finished is not turned into a failure by one.
        """
        job = self._job(request)
        job.stop.set()
        return JSONResponse({"stopping": True})

    async def close_copy(self, request: Request) -> Response:
        """`POST /remodel/close`: close the copy's document; discard it only if asked."""
        body = await _json(request)
        resolve_run_dir(body.get("run_dir"), self.run_root)
        discard = bool(body.get("discard_copy"))
        client = self._client(body)
        return JSONResponse(await run_in_threadpool(partial(self._close, client, discard)))

    # --- the work ---------------------------------------------------------------------

    def _probe(self, client: Any, source_path: str) -> dict[str, Any]:
        reply = _call("remodel.probe_scope", client.probe_scope, source_path)
        signals = _signals(_field(reply, "scope_signals"))
        gate = ScopeGate.evaluate(signals)
        return {
            "probe_id": str(_field(reply, "probe_id") or ""),
            "signals": signals.model_dump(mode="json"),
            "refusals": [refusal.message for refusal in gate.refusals],
        }

    def _open(
        self,
        client: Any,
        run_dir: Path,
        source_path: str,
        probe_id: str,
        configuration: str | None,
    ) -> dict[str, Any]:
        copy_path = copy_path_for(run_dir, source_path)
        try:
            reply = _answered(
                client.open(source_path, str(copy_path), run_dir.name, probe_id),
                "remodel.open",
            )
        except RemodelError as exc:
            if exc.error_code == PREEXISTING_REBUILD_ERRORS:
                # The one refusal raised after a copy exists, and the one whose handler has
                # already deleted it. The host has its own path for it and needs the count,
                # so this is an answer and not an error body.
                return {
                    "copy_path": str(copy_path),
                    "rebuild_error_count": _rebuild_error_count(exc.detail),
                    "copy_present": False,
                }
            raise _refusal(exc) from exc
        except BridgeError as exc:
            raise _unavailable("remodel.open", str(exc)) from exc

        signals = _signals(_field(reply, "scope_signals"))
        try:
            attestation = attestation_from_open(_field(reply, "source_attestation") or {})
        except (ValueError, TypeError, KeyError) as exc:
            raise RunFolderFailed(
                f"remodel.open answered ok and its source attestation could not be read, so "
                f"this run could never be attested: {exc}"
            ) from exc
        write_attestation(run_dir, attestation)

        geometry = _call("remodel.geometry", client.geometry)
        try:
            reading_from_reply(geometry)
        except (ValidationError, ValueError, TypeError) as exc:
            raise RunFolderFailed(
                f"remodel.geometry answered a reading this build cannot read, so the run "
                f"has no baseline to compare against: {exc}"
            ) from exc

        record = {
            "copy_path": str(copy_path),
            # Zero by construction: step 11 of `remodel.open` refuses any other count.
            "rebuild_error_count": 0,
            "document_length_unit": _optional_text(_field(reply, "document_length_unit")),
            "which_configs": ScopeGate.evaluate(signals).which_configs,
            "scope_signals": signals.model_dump(mode="json"),
            "probe_id": probe_id,
            "geometry_before": dict(geometry),
            "configuration": configuration,
        }
        (run_dir / OPEN_FILE_NAME).write_text(
            json.dumps(record, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        return {
            "copy_path": str(copy_path),
            "rebuild_error_count": 0,
            "copy_present": True,
        }

    def _plan(self, run_dir: Path) -> dict[str, Any]:
        package = _package(run_dir / PACKAGE_BEFORE, PackageMissing, NotModelCheck)
        record = _open_record(run_dir)
        attestation = read_attestation(run_dir)
        document_id = part_document_ids(package)[0]
        try:
            carry_forward_exceptions(
                run_dir,
                source_design_id=attestation.source_design_id,
                run_root=self.run_root,
            )
        except RmsRunError as exc:
            # A candidate store that exists and will not parse refuses the run rather than
            # being skipped (FR-029): both grades of this run are measured against those
            # waivers, and measuring them against a store nobody could read would be two
            # different measurements reported as one.
            raise RunFolderFailed(
                f"the waivers an earlier run left could not be carried into {run_dir}: {exc}"
            ) from exc
        plan = plan_run(
            run_dir,
            package,
            document_id=document_id,
            signals=_signals(record.get("scope_signals")),
            probe_id=_optional_text(record.get("probe_id")),
        )
        # The copy's identity is the host's and is carried onto the plan here, because a
        # plan that knew the copy's path but not what it was copied from is one nobody
        # could attest - which is why `RemodelPlan` refuses the three apart.
        plan = plan.model_copy(
            update={
                "run_id": run_dir.name,
                "copy_path": _optional_text(record.get("copy_path")),
                "source": attestation,
            }
        )
        plan_path(run_dir).write_text(
            plan.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        document = next(
            row for row in package.documents if row.document_id == document_id
        )
        return {"plan_summary": plan_summary_row(plan, document, load_table())}

    def _start(
        self, run_dir: Path, client: Any, settings: ProviderSettings
    ) -> RemodelJob:
        # The live job is read first, because it is the most specific fact and it explains
        # the other two: a run past its first few milliseconds has moved its own plan off
        # `planned` (`judge` records `judging`) and opened its own change log, so both of
        # the refusals below are true of a folder a run is writing to and neither says why.
        # "One run per folder" outranks them (`backend-remodel.md`, `RunInProgress`).
        live = next(
            (job for job in self.jobs.values() if job.run_dir == run_dir and job.live), None
        )
        if live is not None:
            raise RunInProgress(
                f"run {live.job_id} is already re-modeling {run_dir}; one run per folder"
            )
        state, _ = _plan_facts(run_dir)
        if state is None:
            raise RunNotPlanned(
                f"{run_dir} holds no plan; press Remodel to plan this part before starting "
                "a run"
            )
        if state != "planned":
            raise RunNotPlanned(
                f"the plan in {run_dir} is {state!r} and a run starts from 'planned'; a run "
                "that already began is never restarted over its own change log"
            )
        if changes_path(run_dir).exists():
            raise ResumeRefused(
                f"{run_dir} already holds a change log, so this run was interrupted rather "
                "than finished; recovery is manual and a run never auto-resumes (FR-031)"
            )

        package = _package(run_dir / PACKAGE_BEFORE, PackageMissing, NotModelCheck)
        record = _open_record(run_dir)
        attestation = read_attestation(run_dir)
        plan = RemodelPlan.model_validate_json(
            plan_path(run_dir).read_text(encoding="utf-8")
        )
        job = RemodelJob(
            job_id=uuid4().hex,
            run_dir=run_dir,
            timeout_s=self.package_after_timeout,
        )
        self.jobs[job.job_id] = job
        self._submit(
            job,
            partial(
                run_remodel,
                run_dir=run_dir,
                client=client,
                plan=plan,
                package=package,
                dump_after=job.wait_for_package_after,
                baseline=int(record.get("rebuild_error_count") or 0),
                before=reading_from_reply(record.get("geometry_before") or {}),
                attestation=attestation,
                settings=settings,
                document_length_unit=_optional_text(record.get("document_length_unit")),
                which_configs=record.get("which_configs"),
                # The stage-1 profile, named rather than defaulted: this route states which
                # profile the run is decided under, and `require_calibrated` still refuses
                # one PROBE-8 has not measured (FR-036).
                tolerances=IDENTITY,
                effort=settings.effort,
                run_root=self.run_root,
                callbacks=[job.publish],
                stop_requested=job.stop.is_set,
                redact=self.redact,
            ),
        )
        return job

    def _state(self, job: RemodelJob) -> dict[str, Any]:
        plan_state, total = _plan_facts(job.run_dir)
        records = _changes(job.run_dir)
        # What landed, counted from the records themselves. The `save` is not a planned
        # change - its `seq` is the next free one in the log rather than a plan index - so
        # it is neither counted nor reported as the change in hand: a run the engineer
        # stopped after one change writes that line too, and reading it as "all of them"
        # would report a truncated run as a completed one (data-model.md section 11).
        applied = len(
            [row for row in records if row.status == "applied" and row.kind != "save"]
        )
        last = records[-1] if records else None
        current = (
            None
            if last is None or last.kind == "save"
            else {
                "seq": last.seq,
                "kind": last.kind,
                "subject_name": None if last.subject is None else last.subject.name,
            }
        )
        return {
            "state": job.state,
            "plan_state": plan_state,
            "changes_total": total,
            "changes_applied": applied,
            "current": current,
            "awaiting": job.awaiting,
            "error": job.error,
        }

    def _deliver(self, job: RemodelJob, path: str) -> None:
        expected = job.run_dir / PACKAGE_AFTER
        if Path(path).resolve() != expected.resolve():
            raise PackageAfterRefused(
                f"this run's after-dump is {expected} and the request named {path}; the "
                "dump the run grades is the one in its own folder and no other file"
            )
        job.deliver(_package(expected, PackageAfterRefused, PackageAfterRefused))

    def _close(self, client: Any, discard_copy: bool) -> dict[str, Any]:
        try:
            _answered(client.close_document(discard_copy), "remodel.close")
        except BridgeDocumentClosedError:
            # A copy that is not open is a no-op: Discard after a refusal that already
            # closed the document is the same request, and it has already been honoured.
            return {"closed": True}
        except RemodelError as exc:
            raise _refusal(exc) from exc
        except BridgeError as exc:
            raise _unavailable("remodel.close", str(exc)) from exc
        return {"closed": True}

    # --- the bridge, the job and the worker ------------------------------------------

    def _client(self, body: Mapping[str, Any]) -> Any:
        """The `remodel.*` client this request's bridge config names.

        The secret travels from the pane to the client and stops there: it is never written
        to the run folder, never echoed in a reply and never in an error body.
        """
        bridge = body.get("bridge")
        if not isinstance(bridge, Mapping):
            raise ChatError(
                "bridge is required and is the {pipe, secret} of this run's SOLIDWORKS "
                "bridge, exactly as POST /sessions takes it"
            )
        pipe = str(bridge.get("pipe") or DEFAULT_PIPE_NAME)
        secret = str(bridge.get("secret") or "") or None
        if self.bridge_factory is not None:
            return self.bridge_factory(pipe, secret)
        return RemodelClient(pipe, secret)

    def _job(self, request: Request) -> RemodelJob:
        job_id = str(request.path_params["job_id"])
        job = self.jobs.get(job_id)
        if job is None:
            raise UnknownJob(f"no run {job_id!r} on this backend")
        return job

    @staticmethod
    def _after(request: Request) -> int:
        """`?after=N` as a `seq`. Anything unreadable replays from the beginning."""
        try:
            return max(int(request.query_params.get("after", "0")), 0)
        except (TypeError, ValueError):
            return 0

    def _submit(self, job: RemodelJob, action: Callable[[], Any]) -> None:
        """Run one re-model on its own thread. One thread per run, one run per folder."""
        worker = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"remodel-{job.job_id[:8]}"
        )
        self._workers[job.job_id] = worker
        worker.submit(self._play, job, action)

    def _play(self, job: RemodelJob, action: Callable[[], Any]) -> None:
        """One run, and the state it leaves the job in. This never raises.

        A run that raised has already written down why: `run_remodel` reports the failure on
        the event stream and records it on the plan before it travels, so what is left for
        the job is the sentence the pane shows beside a run it can no longer poll.
        """
        try:
            action()
        except Exception as exc:
            message = self.redact(str(exc)) or type(exc).__name__
            logger.warning("remodel run %s failed: %s", job.job_id, message)
            job.fail(f"{type(exc).__name__}: {message}")
        else:
            job.finish()

    def shutdown(self) -> None:
        """Release every live run before the process goes away.

        A run blocked on the package-after rendezvous would otherwise outlive the backend
        that owns it, holding a worker thread and a document nobody is going to dump. Both
        flags are set: the apply loop stops between changes and the wait ends, and the run
        finalizes itself the way any other failure does.
        """
        for job in self.jobs.values():
            job.stop.set()
            job.abandon()
        for worker in self._workers.values():
            worker.shutdown(wait=False)
        self._workers.clear()


def _field(reply: Any, name: str) -> Any:
    """One member of a bridge reply, or `None` when the host sent no such member."""
    return reply.get(name) if isinstance(reply, Mapping) else None


def _optional_text(value: Any) -> str | None:
    """A string the caller may legitimately not have. Unknown stays `None`, never `""`."""
    return value.strip() or None if isinstance(value, str) else None


def remodel_routes(server: RemodelServer) -> list[Route]:
    """The nine routes of `contracts/backend-remodel.md`, in the contract's order.

    `/remodel/runs` is listed before `/remodel/runs/{job_id}` so the literal path is matched
    before the pattern that would otherwise swallow it, exactly as `/checks/rms` is.
    """
    return [
        Route("/remodel/probe", server.probe, methods=["POST"]),
        Route("/remodel/open", server.open_copy, methods=["POST"]),
        Route("/remodel/plan", server.plan, methods=["POST"]),
        Route("/remodel/runs", server.start_run, methods=["POST"]),
        Route("/remodel/runs/{job_id}", server.run_state, methods=["GET"]),
        Route("/remodel/runs/{job_id}/events", server.run_events, methods=["GET"]),
        Route(
            "/remodel/runs/{job_id}/package-after",
            server.package_after,
            methods=["POST"],
        ),
        Route("/remodel/runs/{job_id}/stop", server.stop_run, methods=["POST"]),
        Route("/remodel/close", server.close_copy, methods=["POST"]),
    ]
