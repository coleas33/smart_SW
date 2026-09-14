"""The agent loop: one review of one evidence package, start to saved session.

The loop belongs to this module. A provider adapter (`agent/providers`) runs exactly one
turn - streaming text, dispatching tool calls, mapping its own errors - and hands back a
`TurnResult`; everything around that turn is here, because none of it is provider
business:

- the system prompt: the versioned commitments in `prompts/system_v1.md`, the mandatory
  checklist rendered as text, and the package census, so the model starts oriented;
- a **per-turn** step budget. `max_steps` bounds the tool calls of one turn, not of the
  session (data-model section 3, rule 4): a resumed turn never no-ops because an earlier
  turn spent the budget. The cumulative count is kept separately, on the run;
- the event stream: one `EventSink` stamps `seq` and `at`, appends every event to
  `events.jsonl` and fans it out to listeners, so the pane, the CLI and the file all see
  the same ordered stream (`contracts/chat-events.schema.json`);
- multi-turn. `ReviewRun.continue_session` appends an engineer turn and runs it, even on a
  session that already ended, and `ReviewRun.answer_evidence` answers an open request and
  resumes. A check re-run after its request is answered replaces the earlier verdict
  rather than adding a second one (rule 3);
- finalization: every evidence request still open and every checklist item still open
  becomes `unresolved` coverage before the session is written (FR-010, FR-019).
  `finalize_session` **rebuilds** what it wrote last time instead of appending to it, so
  finalizing twice is finalizing once (rule 1), and it runs on the failure path too, so
  `ended_at` is never left null (rule 5, FR-008);
- the two US3 hooks on the context: the `exceptions.json` beside the package, loaded when
  it is there, and the live SOLIDWORKS bridge when the run asked for one. Both are wired
  here and nowhere else, so the tools only ever see them through `ToolContext`.

`provider` is injected rather than built, so the whole loop is testable without a network
call or an API key: `providers.fake.FakeProvider` plays a script. `bridge_factory` is
injectable for the same reason: `--bridge` needs a workstation, a unit test does not.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from swreview.agent.checklist import Checklist, load_checklist
from swreview.agent.providers import (
    AgentEvent,
    AgentProvider,
    EffortLevel,
    EventType,
    TurnResult,
    error_body,
)
from swreview.bridge.client import DEFAULT_PIPE_NAME, BridgeClient
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.findings import Finding
from swreview.ir.loader import LoadedPackage, load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import (
    CoverageItem,
    CoverageScope,
    KeySource,
    ProviderInfo,
    ReviewSession,
    save_session,
)
from swreview.tools.context import ToolContext, build_context
from swreview.tools.query import package_summary
from swreview.tools.registry import ToolDispatch, ToolRegistry

SYSTEM_PROMPT_FILE = Path(__file__).parent / "prompts" / "system_v1.md"
SESSION_FILE_NAME = "session.json"
EVENTS_FILE_NAME = "events.jsonl"

DEFAULT_MAX_STEPS = 200
"""Tool calls one turn may make. A session of many turns may make many times this."""

CLOSEOUT_CHECK = "coverage.closeout"
EVIDENCE_CHECK = "coverage.evidence_request"

OPENING_MESSAGE = (
    "Review the evidence package described in the system prompt. Work through the "
    "checklist, gather evidence with the query tools before you judge anything, and "
    "close out every checklist item with a finding or a coverage entry. When you are "
    "done, summarize what you found and what is still unresolved."
)

ANSWER_MESSAGE = (
    "Evidence request {request_id} is answered: {answer}\n\n"
    "Re-run the check you named in that request's `why` using this answer and record one "
    "verdict for it. Your earlier entry for that check is replaced, not duplicated. Then "
    "close out anything the answer unblocks."
)

TRUNCATED_REASON = (
    "the provider ended the turn on its output ceiling; the answer was cut short and "
    "whatever it was still working on was not investigated"
)


def no_redaction(text: str) -> str:
    """What a run with no secret to hide masks with: nothing.

    A run is given a redactor rather than a list of secrets, so the runner never holds a
    key at all, and a keyless run takes the same code path as a real one instead of a
    branch nobody exercises.
    """
    return text


def build_system_prompt(checklist: Checklist, package: EvidencePackage) -> str:
    """The versioned prompt, the checklist, and the package census as one system prompt."""
    return "\n\n".join(
        [
            SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip(),
            "## Review checklist\n\n" + checklist.render(),
            "## This package\n\n```json\n"
            + json.dumps(package_summary(package), indent=2)
            + "\n```",
        ]
    )


def _unresolved(
    session: ReviewSession,
    check: str,
    reason: str,
    *,
    component_ids: Iterable[str] = (),
    document_ids: Iterable[str] = (),
) -> CoverageItem:
    """Append one `unresolved` coverage item and hand it back to whoever wrote it.

    The item is returned so a caller that may have to withdraw it later - finalization,
    which rebuilds its own items on every call - can identify exactly the ones it wrote.
    """
    item = CoverageItem(
        check=check,
        scope=CoverageScope(
            component_ids=list(component_ids),
            document_ids=list(document_ids),
        ),
        reason=reason,
        error=None,
    )
    session.coverage.unresolved.append(item)
    return item


def load_exceptions(loaded: LoadedPackage) -> ExceptionStore | None:
    """The `exceptions.json` beside `package.json`, or `None` when there is none.

    Absent is the normal case and means "no condition has been accepted for this design";
    the check tools then report every condition they find. A file that is there but
    unreadable raises rather than being skipped: an exception the reviewer silently
    dropped would re-raise something an engineer already accepted (FR-013).
    """
    path = loaded.base_dir / EXCEPTIONS_FILE_NAME
    if not path.is_file():
        return None
    return ExceptionStore(path).load()


def finalize_session(
    context: ToolContext,
    started: datetime,
    *,
    written: list[CoverageItem] | None = None,
) -> ReviewSession:
    """Close out the session: open requests, open checklist items, timing, end time.

    Called whether the turn ended normally, ran out of steps, was truncated, or blew up:
    a session is never written with an item that quietly went nowhere, and `ended_at` is
    never left null (data-model section 3, rule 5).

    Args:
        context: The run's tool context; its `session` is the one being closed out.
        started: When the session started, for the unattended-runtime timing.
        written: The items a previous finalization of this same session appended. They
            are withdrawn by identity before the new ones are computed, and the list is
            updated in place, which is what makes a second finalization produce the same
            coverage rather than a duplicate of it (rule 1). Items *anything else* wrote -
            a `mark_coverage` call, a truncated or cut-short turn - are never touched.
            Pass the same list on every call; omitting it finalizes as a one-shot.
    """
    review = context.session
    previous = written if written is not None else []
    review.coverage.unresolved[:] = [
        item
        for item in review.coverage.unresolved
        if all(item is not stale for stale in previous)
    ]
    previous.clear()

    for request in review.evidence_requests:
        if request.status != "open":
            continue
        previous.append(
            _unresolved(
                review,
                EVIDENCE_CHECK,
                f"{request.id} is still open: {request.what}",
                component_ids=[
                    entity_id
                    for entity_id in request.entity_ids
                    if context.component(entity_id) is not None
                ],
            )
        )
    for item in context.checklist.open_items(review):
        previous.append(
            _unresolved(
                review,
                item.id,
                f"{item.title}: the review ended without a finding or a coverage entry for it",
            )
        )

    ended = datetime.now(UTC)
    review.ended_at = ended
    review.timing = review.timing.replace(
        unattended_runtime_minutes=(ended - started).total_seconds() / 60.0
    )
    return review


# --- the event stream -------------------------------------------------------------------


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
        self._clock = clock if clock is not None else _now
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


def _now() -> datetime:
    return datetime.now(UTC)


# --- one verdict per check --------------------------------------------------------------


def _verdict_key(finding: Finding) -> tuple[Any, ...]:
    """What makes two findings two verdicts on the *same* thing rather than two findings.

    A check, the component instances it judged, the drawing places it read, and the
    configuration it judged them in. Two drawing findings on different sheets, or the same
    check on different components, have different keys and both stand.
    """
    return (
        finding.check,
        tuple(finding.component_ids),
        tuple(
            (
                location.document_id,
                location.sheet,
                location.view,
                location.annotation,
                location.page,
            )
            for location in finding.drawing_locations
        ),
        finding.configuration,
    )


def _reconcile_reruns(session: ReviewSession, before: int) -> list[Finding]:
    """Fold a re-run check's new finding onto the one it re-judges (rule 3).

    `before` is how many findings the session held when the answer went in; everything
    after it came out of the resumed turn. A new finding whose verdict key matches an
    earlier one takes that finding's id and replaces it in place, so the report shows one
    verdict per check in its original position instead of two contradictory ones. A new
    finding that matches nothing is simply a new finding.

    Only findings from a turn that an answered evidence request started are reconciled:
    inside one ordinary turn, two calls to the same check are the model's own doing and
    are left exactly as it recorded them.

    Returns the folded findings in their final form. The tool layer already announced each
    of them under the id it was allocated, so the caller re-announces it under the id it
    was folded onto: the stream's last word on a finding id is then the verdict
    `session.json` holds.
    """
    previous = list(session.findings[:before])
    added = list(session.findings[before:])
    by_key = {_verdict_key(finding): index for index, finding in enumerate(previous)}
    kept: list[Finding] = []
    folded: list[Finding] = []
    for finding in added:
        index = by_key.get(_verdict_key(finding))
        if index is None:
            kept.append(finding)
            continue
        previous[index] = finding.model_copy(update={"id": previous[index].id})
        folded.append(previous[index])
    session.findings[:] = [*previous, *kept]
    return folded


# --- one review in flight ----------------------------------------------------------------


class ReviewRun:
    """One review: the session, the provider, the message history and the event stream.

    Built by `start_review`, played by `start`, and kept alive afterwards so the engineer
    can send a follow-up (`continue_session`) or answer an evidence request
    (`answer_evidence`). Every one of those runs a turn and finalizes, so `session.json`
    on disk is current after each of them.
    """

    def __init__(
        self,
        *,
        context: ToolContext,
        provider: AgentProvider,
        tools: ToolDispatch,
        system: str,
        sink: EventSink,
        out_dir: Path,
        effort: EffortLevel,
        max_steps: int,
        bridge: Any | None = None,
        redact: Callable[[str], str] = no_redaction,
    ) -> None:
        self.context = context
        self.provider = provider
        self.tools = tools
        self.system = system
        self.sink = sink
        self.out_dir = Path(out_dir)
        self.effort = effort
        self.max_steps = max_steps
        self.redact = redact
        """Applied to provider error text before it is written to `events.jsonl`."""
        self.messages: list[dict[str, Any]] = []
        self.total_steps = 0
        """Tool calls across every turn of this session. `max_steps` bounds one turn."""
        self.turns = 0
        self.started = context.session.started_at
        self._bridge = bridge
        self._finalized: list[CoverageItem] = []

    @property
    def session(self) -> ReviewSession:
        session = self.context.session
        if session is None:  # pragma: no cover - build_context always makes one
            raise ValueError("a review run needs a tool context with a review session")
        return session

    @property
    def session_path(self) -> Path:
        return self.out_dir / SESSION_FILE_NAME

    @property
    def events_path(self) -> Path:
        return self.out_dir / EVENTS_FILE_NAME

    # --- turns --------------------------------------------------------------------

    def start(self) -> ReviewSession:
        """Announce the session and play the opening turn."""
        mapping = self.session.provider_info
        self.sink.emit(
            "session.started",
            {
                "session_id": str(self.session.session_id),
                "package_id": str(self.session.package_id),
                "provider": mapping.provider if mapping is not None else "",
                "model": self.session.model,
                "effort_mapping": (
                    mapping.effort_mapping.model_dump(mode="json")
                    if mapping is not None
                    else {}
                ),
            },
        )
        return self._say(OPENING_MESSAGE)

    def continue_session(self, text: str) -> ReviewSession:
        """Append an engineer turn and run it.

        Accepted on a session whose previous turn already ended: the review goes back to
        running and is finalized again afterwards (FR-006, US1 scenarios 4 and 5).
        """
        return self._say(text)

    def answer_evidence(self, request_id: str, answer: str) -> ReviewSession:
        """Answer an open evidence request and resume the review on the answer.

        The request stops being open, so finalization no longer reports it as unresolved
        (rule 2), and a check the resumed turn re-runs replaces its earlier verdict rather
        than adding a second one (rule 3).
        """
        request = next(
            (item for item in self.session.evidence_requests if item.id == request_id), None
        )
        if request is None:
            known = [item.id for item in self.session.evidence_requests]
            raise ValueError(f"no evidence request {request_id!r} in this session; open: {known}")
        if request.status != "open":
            raise ValueError(f"evidence request {request_id} is already answered")

        request.status = "answered"
        request.answer = answer
        request.answered_at = _now()
        self.sink.emit("evidence.answered", {"request_id": request_id, "answer": answer})

        before = len(self.session.findings)
        self._ask(ANSWER_MESSAGE.format(request_id=request_id, answer=answer))
        for finding in _reconcile_reruns(self.session, before):
            self.sink.emit("finding", finding.model_dump(mode="json"))
        return self.finalize()

    def finalize(self) -> ReviewSession:
        """Close the session out, write `session.json`, and say so on the stream."""
        session = finalize_session(self.context, self.started, written=self._finalized)
        save_session(session, self.session_path)
        ended_at = session.ended_at
        self.sink.emit(
            "session.ended",
            {
                "ended_at": ended_at.isoformat() if ended_at is not None else None,
                "timing": session.timing.model_dump(mode="json"),
            },
        )
        return session

    def close(self) -> None:
        """Release what the run holds open. Only the live bridge needs it today."""
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None

    # --- internals ----------------------------------------------------------------

    def _ask(self, text: str) -> TurnResult:
        """Append an engineer turn and run it. The caller decides when to finalize."""
        self.messages.append({"role": "user", "content": text})
        return self._run_turn()

    def _say(self, text: str) -> ReviewSession:
        self._ask(text)
        return self.finalize()

    def _run_turn(self) -> TurnResult:
        """One provider turn, its budget, and how it ended.

        A turn that fails is still an ended session: the error is reported, the turn is
        closed out, the session is finalized and written, and only then does the exception
        travel on to the caller, who decides whether to retry (FR-008, FR-028).
        """
        self.turns += 1
        self.session.ended_at = None
        try:
            result = self.provider.run(
                system=self.system,
                messages=self.messages,
                tools=self.tools,
                effort=self.effort,
                max_steps=self.max_steps,
                on_event=self.sink.emit,
            )
        except Exception as exc:
            self.sink.emit(
                "error",
                error_body(
                    error_class=type(exc).__name__,
                    # Whatever raised - an adapter's own mapped error, an SDK class it
                    # does not map, a transport failure - the run folder must not receive
                    # the key the request carried (FR-015). The adapters redact what they
                    # wrap; this is the one place that covers what none of them did.
                    message=self.redact(str(exc)),
                    # The runner cannot tell a dropped connection from a bug, and the
                    # engineer, not this module, decides whether to spend another run
                    # (FR-028). An adapter that does know emits its own `error` first.
                    retryable=True,
                ),
            )
            self.sink.emit("turn.ended", {"reason": "error"})
            self.finalize()
            raise

        self.messages = [dict(message) for message in result.messages]
        self.total_steps += result.steps
        if result.reason == "max_steps":
            self._closeout(
                f"max_steps reached ({self.max_steps} tool calls); the turn was cut short "
                "and what it was still investigating was not finished"
            )
        elif result.reason == "truncated":
            self._closeout(TRUNCATED_REASON)
        self.sink.emit("turn.ended", {"reason": result.reason})
        return result

    def _closeout(self, reason: str) -> None:
        """Record why this turn stopped short, and say so on the stream.

        The items *finalization* writes are not announced this way: it rebuilds them on
        every call (rule 1), so announcing each rebuild would put the same item on the
        stream once per turn. `session.ended` and `session.json` carry the closing
        coverage; a `coverage` event means something was just decided.
        """
        item = _unresolved(self.session, CLOSEOUT_CHECK, reason)
        self.sink.emit(
            "coverage", {"bucket": "unresolved", "item": item.model_dump(mode="json")}
        )


# --- entry points ---------------------------------------------------------------------


def start_review(
    package_dir: Path | str,
    out_dir: Path | str,
    *,
    provider: AgentProvider,
    model: str | None = None,
    effort: EffortLevel = "high",
    key_source: KeySource = "none",
    retry_of: str | UUID | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    fail_tool: Iterable[str] = (),
    bridge: bool = False,
    pipe_name: str = DEFAULT_PIPE_NAME,
    bridge_secret: str | None = None,
    bridge_factory: Callable[[str, str | None], Any] | None = None,
    callbacks: Iterable[EventListener] = (),
    redact: Callable[[str], str] = no_redaction,
) -> ReviewRun:
    """Prepare a review of `package_dir` writing into `out_dir`; play it with `start()`.

    Nothing is sent to the provider here. The package is loaded, the tools are bound, the
    session records who is about to run it, and the event file is prepared - so a caller
    that wants the turns one at a time (the pane) and a caller that wants the whole review
    (`run_review`) share every line of setup.

    Args:
        package_dir: Directory holding `package.json`.
        out_dir: Directory `session.json` and `events.jsonl` are written to.
        provider: The adapter that runs each turn. Constructed by the caller, so no
            provider SDK is imported by a run that does not use one.
        model: Model id; the provider's own model when omitted. Never defaulted to a
            literal here - `agent/settings.py` owns the per-provider default (FR-026).
        effort: What the engineer asked for. The adapter maps it or fails fast; the
            mapping it chose is recorded on the session and in `session.started`.
        key_source: Where the provider's key came from, for the session record. `none`
            means the run needed no key, which is the truth for the scripted provider.
        retry_of: The failed session this run replaces (FR-028), or None.
        max_steps: Tool-call budget for **one turn**. Hitting it is unresolved coverage,
            not a finish.
        fail_tool: Tool names forced to fail; the `--fail-tool` test hook. An unknown
            name raises.
        bridge: Open the live SOLIDWORKS bridge and add the three bridge tools (US3).
            Needs `SwReview.Extractor.Console.exe serve` running on this workstation.
        pipe_name: Named pipe the bridge listens on.
        bridge_secret: The per-launch secret the in-process tool service requires on every
            request (contracts/README.md). `None` for the console host, which asks for
            none; the pane passes the review-session secret from `POST /sessions`.
        bridge_factory: Builds the bridge client from the pipe name and the secret - the
            session's whole `bridge` config - and defaults to
            `swreview.bridge.client.BridgeClient`, which takes them in that order. It is
            injectable for tests and for the `--fail-bridge` hook.
        callbacks: Live listeners on the event stream, called after each event is
            written. The pane's SSE fan-out is one; a test collecting events is another.
        redact: Masks the run's API key out of provider error text before it is written
            to `events.jsonl` (FR-015). The caller that resolved the key builds it;
            `no_redaction` is the default because a run may legitimately have no key.
    """
    loaded = load_package(package_dir)
    checklist = load_checklist()
    chosen_model = model if model is not None else provider.model
    effort_mapping = provider.effort_mapping(effort)

    bridge_client = None
    if bridge:
        factory = bridge_factory if bridge_factory is not None else BridgeClient
        bridge_client = factory(pipe_name, bridge_secret)
    out = Path(out_dir)
    try:
        # Before the context, which needs `emit`: what a tool writes is on the stream from
        # the first tool call, not from the end of the turn (FR-013).
        sink = EventSink(out / EVENTS_FILE_NAME, listeners=callbacks)
        context = build_context(
            loaded,
            model=chosen_model,
            checklist=checklist,
            exceptions=load_exceptions(loaded),
            bridge=bridge_client,
            emit=sink.emit,
        )
        session = context.session
        if session is None:  # pragma: no cover - build_context always makes one
            raise ValueError("build_context returned a context without a review session")
        session.provider_info = ProviderInfo(
            provider=str(provider.name),
            model=chosen_model,
            effort_mapping=effort_mapping,
            key_source=key_source,
        )
        session.retry_of = UUID(str(retry_of)) if retry_of is not None else None
        tools = ToolRegistry().dispatch(context, fail_tool=fail_tool)
    except Exception:
        if bridge_client is not None:
            bridge_client.close()
        raise

    return ReviewRun(
        context=context,
        provider=provider,
        tools=tools,
        system=build_system_prompt(checklist, loaded.package),
        sink=sink,
        out_dir=out,
        effort=effort,
        max_steps=max_steps,
        bridge=bridge_client,
        redact=redact,
    )


def run_review(
    package_dir: Path | str,
    out_dir: Path | str,
    *,
    provider: AgentProvider,
    model: str | None = None,
    effort: EffortLevel = "high",
    **options: Any,
) -> ReviewSession:
    """Review the package in `package_dir` and write `session.json` into `out_dir`.

    The one-shot form: one opening turn, then finalize, then release the bridge. A caller
    that wants to keep talking to the session - the pane, which sends follow-ups and
    answers evidence requests - calls `start_review` and holds on to the `ReviewRun`.

    Args:
        package_dir: Directory holding `package.json`.
        out_dir: Directory `session.json` and `events.jsonl` are written to.
        provider: The adapter that runs the turn.
        model: Model id; the provider's own model when omitted.
        effort: What the engineer asked for; the adapter maps it or fails fast.
        options: The rest of `start_review`'s keyword arguments - `key_source`,
            `retry_of`, `max_steps`, `fail_tool`, `bridge`, `pipe_name`,
            `bridge_secret`, `bridge_factory`, `callbacks`, `redact` - documented there
            rather than restated here.
    """
    run = start_review(
        package_dir, out_dir, provider=provider, model=model, effort=effort, **options
    )
    try:
        return run.start()
    finally:
        run.close()
