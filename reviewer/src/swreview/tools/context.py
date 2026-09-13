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
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from swreview.agent.checklist import Checklist, load_checklist
from swreview.exceptions import ExceptionStore
from swreview.findings import FindingIdAllocator
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import (
    ComponentInstance,
    Document,
    EvidencePackage,
    Fastener,
    Hole,
)
from swreview.report.session import (
    EvidenceRequestIdAllocator,
    ReviewSession,
    Timing,
)

DEFAULT_MODEL = "claude-opus-5"


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

    `exceptions` and `bridge` are the two hooks US3 fills in: the retained-exception
    store and the live SOLIDWORKS bridge. Both stay `None` for a US1 run, and the tools
    that would use them say so in their result instead of guessing.

    `exceptions` is normally an `ExceptionStore` (the runner loads `exceptions.json` from
    the package directory into one). A plain list of records is also accepted, because a
    fixture and a golden case carry the exceptions inline; `exception_store()` is how a
    tool gets the store either way.
    """

    package: LoadedPackage
    session: ReviewSession
    checklist: Checklist
    exceptions: ExceptionStore | list[Any] | None = None
    bridge: Any | None = None
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


def new_session(package: EvidencePackage, model: str = DEFAULT_MODEL) -> ReviewSession:
    """An empty session over `package`, started now, with timing zeroed."""
    return ReviewSession(
        session_id=uuid4(),
        package_id=package.package_id,
        design_id=package.design.design_id,
        started_at=datetime.now(UTC),
        ended_at=None,
        model=model,
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
    model: str = DEFAULT_MODEL,
    checklist: Checklist | None = None,
    exceptions: ExceptionStore | list[Any] | None = None,
    bridge: Any | None = None,
) -> ToolContext:
    """A context over `package` with a fresh session and the versioned checklist."""
    return ToolContext(
        package=package,
        session=new_session(package.package, model=model),
        checklist=checklist if checklist is not None else load_checklist(),
        exceptions=exceptions,
        bridge=bridge,
    )


def context_for(
    package: EvidencePackage,
    *,
    base_dir: Path | str = ".",
    model: str = DEFAULT_MODEL,
) -> ToolContext:
    """A context over an in-memory package, for tests and the golden fixtures."""
    return build_context(LoadedPackage(package=package, base_dir=Path(base_dir)), model=model)
