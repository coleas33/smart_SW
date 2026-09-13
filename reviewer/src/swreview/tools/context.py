"""What every curated tool reads, and how it reaches the tool that is running.

A tool's JSON schema is generated from its Python signature (`@beta_tool`), so the
context cannot be an argument: the model would see it and could set it. It travels in a
`ContextVar` instead, which `swreview.tools.registry.RecordedTool.call` sets around the
one call it dispatches and resets afterwards. Nothing else in the package sets it, so
"which package am I reviewing" stays a single, explicit hand-off at the tool boundary.

This module also owns the two shapes the whole tool layer returns:

- an error is `{"error": "..."}`; the registry turns that into a `tool_result` with
  `is_error: true` and a `failed` coverage item (contracts/agent-tools.md);
- a tool never raises for bad input it can describe - unknown ids, unknown enum values
  and unreadable regexes all come back as error results.

It also owns the run's event stream hook. A finding, a coverage item and an evidence
request reach the session through `record_finding`, `record_coverage` and
`record_evidence_request`, each of which announces on `emit` what it just wrote, so the
pane sees them while the turn is still running (FR-013) and nothing has to diff
`session.json` afterwards to work out what changed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from swreview.agent.checklist import Checklist, load_checklist
from swreview.agent.providers import EventCallback, EventType
from swreview.agent.settings import DEFAULT_PROVIDER, default_model
from swreview.exceptions import ExceptionStore
from swreview.findings import Finding, FindingIdAllocator
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import (
    ComponentInstance,
    Document,
    EvidencePackage,
    Fastener,
    Hole,
)
from swreview.report.session import (
    CoverageBucket,
    CoverageItem,
    EvidenceRequest,
    EvidenceRequestIdAllocator,
    ReviewSession,
    Timing,
)


def error_result(message: str) -> dict[str, str]:
    """The one error shape every tool returns instead of raising."""
    return {"error": message}


def unknown_id(kind: str, entity_id: str) -> dict[str, str]:
    """Error result for an id that is not in the package."""
    return error_result(f"unknown {kind} id {entity_id!r}")


def not_one_of(field_name: str, value: str, allowed: tuple[str, ...]) -> dict[str, str]:
    """Error result for an enum argument outside its allowed set."""
    return error_result(f"{field_name} {value!r} is not one of {list(allowed)}")


@dataclass
class ToolContext:
    """The package under review, the session being written, and the review checklist.

    `session` is `None` for a general-chat context, which has no review session to write:
    the tools it gets are the read-only ones and their calls are recorded through the
    registry's chat-log sink instead. Every tool that writes a finding, a coverage item or
    an evidence request needs one, and `ToolRegistry.build` refuses a sessionless context
    that was not given an explicit sink.

    `exceptions` and `bridge` are the two hooks US3 fills in: the retained-exception
    store and the live SOLIDWORKS bridge. Both stay `None` for a US1 run, and the tools
    that would use them say so in their result instead of guessing.

    `exceptions` is normally an `ExceptionStore` (the runner loads `exceptions.json` from
    the package directory into one). A plain list of records is also accepted, because a
    fixture and a golden case carry the exceptions inline; `exception_store()` is how a
    tool gets the store either way.
    """

    package: LoadedPackage
    session: ReviewSession | None
    checklist: Checklist
    exceptions: ExceptionStore | list[Any] | None = None
    bridge: Any | None = None
    emit: EventCallback | None = None
    finding_ids: FindingIdAllocator = field(default_factory=FindingIdAllocator)
    evidence_request_ids: EvidenceRequestIdAllocator = field(
        default_factory=EvidenceRequestIdAllocator
    )

    def __post_init__(self) -> None:
        package = self.package.package
        self._components = {item.id: item for item in package.components}
        self._documents = {item.document_id: item for item in package.documents}
        self._holes = {item.id: item for item in package.holes}
        self._fasteners = {item.id: item for item in package.fasteners}

    @property
    def ir(self) -> EvidencePackage:
        """The evidence package itself."""
        return self.package.package

    def require_session(self) -> ReviewSession:
        """The review session this context writes to.

        Raises `ValueError` when there is none, which is a caller mistake: the tools that
        write are not in the general-chat tool list, so a sessionless run never reaches
        here (`ToolRegistry.build`).
        """
        if self.session is None:
            raise ValueError("this tool writes to a review session and this context has none")
        return self.session

    # --- what the run writes, and what the pane is told about it (FR-013) -------------

    def emit_event(self, event_type: EventType, body: Mapping[str, Any]) -> None:
        """Put one event on the run's stream; drop it when nothing is listening.

        `emit` is the runner's `EventSink.emit`, wired in `start_review`. It is `None` for
        a context nobody is streaming - a fixture, a golden case, a direct tool call in a
        test - and a tool must behave the same either way.
        """
        if self.emit is not None:
            self.emit(event_type, body)

    def record_finding(self, finding: Finding) -> None:
        """Append a finding to the session and announce it as it is written.

        The three `record_*` methods are the only places a finding, a coverage item or an
        evidence request reaches the session, so "written to the session" and "on the
        event stream" cannot drift apart: the pane shows a finding while the turn is still
        running instead of reconstructing it from `session.json` afterwards.
        """
        self.require_session().findings.append(finding)
        self.emit_event("finding", finding.model_dump(mode="json"))

    def record_coverage(self, bucket: CoverageBucket, item: CoverageItem) -> None:
        """Append a coverage item to `bucket` and announce which bucket it went into."""
        getattr(self.require_session().coverage, bucket).append(item)
        self.emit_event(
            "coverage", {"bucket": bucket, "item": item.model_dump(mode="json")}
        )

    def record_evidence_request(self, request: EvidenceRequest) -> None:
        """Open an evidence request on the session and announce it."""
        self.require_session().evidence_requests.append(request)
        self.emit_event("evidence.requested", request.model_dump(mode="json"))

    def exception_store(self) -> ExceptionStore | None:
        """The retained exceptions as a store, or `None` when this run has none.

        Raises `pydantic.ValidationError` when `exceptions` holds records that are not
        complete exceptions: an exception the reviewer cannot read is not silently
        dropped, because dropping it would re-raise a condition an engineer accepted.
        """
        if self.exceptions is None:
            return None
        if isinstance(self.exceptions, ExceptionStore):
            return self.exceptions
        if not self.exceptions:
            return ExceptionStore()
        return ExceptionStore.from_records([dict(record) for record in self.exceptions])

    def component(self, component_id: str) -> ComponentInstance | None:
        return self._components.get(component_id)

    def document(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)

    def hole(self, hole_id: str) -> Hole | None:
        return self._holes.get(hole_id)

    def fastener(self, fastener_id: str) -> Fastener | None:
        return self._fasteners.get(fastener_id)

    def entity_kind(self, entity_id: str) -> str | None:
        """What `entity_id` names in this package, or `None` when it names nothing.

        Covers everything a tool argument may legitimately point at, so a tool can refuse
        an id that came from nowhere (research R4: ids are validated against the package).
        """
        for kind, known in (
            ("component", self._components),
            ("document", self._documents),
            ("hole", self._holes),
            ("fastener", self._fasteners),
        ):
            if entity_id in known:
                return kind
        package = self.ir
        for kind, items in (
            ("mate", package.mates),
            ("thread", package.threads),
            ("face", package.faces),
            ("body", package.bodies),
            ("interference", package.interferences),
            ("capture", package.captures),
        ):
            if any(item.id == entity_id for item in items):
                return kind
        return None


_CURRENT: ContextVar[ToolContext] = ContextVar("swreview_tool_context")


def current_context() -> ToolContext:
    """The context of the tool call in flight.

    Raises `LookupError` when a tool function is called outside `use_context`, which only
    happens if a caller bypassed the registry.
    """
    try:
        return _CURRENT.get()
    except LookupError as exc:
        raise LookupError(
            "no ToolContext is active; call the tool through swreview.tools.registry "
            "or inside `with use_context(ctx):`"
        ) from exc


@contextmanager
def use_context(context: ToolContext) -> Iterator[ToolContext]:
    """Make `context` the active one for the duration of the block."""
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)


def new_session(package: EvidencePackage, model: str | None = None) -> ReviewSession:
    """An empty session over `package`, started now, with timing zeroed.

    `model` is the id the run is about to use; a caller that has not chosen one - a
    fixture, a golden case, a check command that reviews nothing - gets the default
    provider's default model from `agent/settings.py`, which is the one place a model id
    is named (FR-026). This module holds no model constant of its own: feature 001's
    `DEFAULT_MODEL` here is what wrote a retired vendor's id into `session.json`.
    """
    return ReviewSession(
        session_id=uuid4(),
        package_id=package.package_id,
        design_id=package.design.design_id,
        started_at=datetime.now(UTC),
        ended_at=None,
        model=model if model is not None else default_model(DEFAULT_PROVIDER),
        timing=Timing(
            baseline_minutes=None,
            assisted_supervision_minutes=0.0,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=0.0,
        ),
    )


def build_context(
    package: LoadedPackage,
    *,
    model: str | None = None,
    checklist: Checklist | None = None,
    exceptions: ExceptionStore | list[Any] | None = None,
    bridge: Any | None = None,
    emit: EventCallback | None = None,
) -> ToolContext:
    """A context over `package` with a fresh session and the versioned checklist.

    `model` reaches `new_session` untouched, so the per-provider default is resolved in
    exactly one place rather than restated here. `emit` is the run's event stream; a
    caller with no stream to write to - a fixture, a golden case - leaves it unset.
    """
    return ToolContext(
        package=package,
        session=new_session(package.package, model=model),
        checklist=checklist if checklist is not None else load_checklist(),
        exceptions=exceptions,
        bridge=bridge,
        emit=emit,
    )


def context_for(
    package: EvidencePackage,
    *,
    base_dir: Path | str = ".",
    model: str | None = None,
) -> ToolContext:
    """A context over an in-memory package, for tests and the golden fixtures."""
    return build_context(LoadedPackage(package=package, base_dir=Path(base_dir)), model=model)
