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
from swreview.agent.settings import (
    DEFAULT_PROVIDER,
    ExtractionSettings,
    default_model,
)
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
    Contact,
    ContactIdAllocator,
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


RMS_NOT_GRADABLE = (
    "RMS tools were not offered for this review: the package carries no feature rows "
    "(extractor profile {profile!r}, features[] empty), so no part rule and no equation "
    "rule could be graded. The four assembly rules read the mates and the component "
    "instances rather than the tree and would grade; they are withheld with them because "
    "a report that closed out modeling resilience on the assembly rules alone would read "
    "as a graded model rather than as an extract that never happened. Extract the model "
    "again with its feature tree to grade them"
)


def rms_not_gradable(package: EvidencePackage) -> str | None:
    """Why this package cannot be graded for Resilient Modeling, or `None` when it can.

    The condition is the one `POST /checks/rms` already refuses with `EmptyFeatureTree`
    (`_refuse_empty_feature_tree`, `checks/rms/run.py`): a package with no feature rows
    carries no tree for the part or the equation rules to read, and the route's three
    scopes - `part`, `equations`, `all` - are all document-scoped, so for the route that
    condition is exactly `features[]` being empty.

    **The four assembly rules are the exception, and the sentence says so.** They read the
    mates and the component instances and never `features[]`, which is why
    `_refuse_empty_feature_tree` lets an assembly-scoped run through, and a package of
    assembly evidence with no part trees in it really does grade: `rms.assembly.*` finds
    mates to faces and edges, an unfixed first component and a deep mate chain in it. This
    tier withholds `check_rms_assembly` with the five tree readers anyway (T060), because a
    report that closed out modeling resilience on the assembly rules alone would read as a
    graded model rather than as an extract that never happened (constitution Principle I).
    That is a **trade**, not an impossibility, and the reason states it as one: an engineer
    who reads it can extract the tree, or ask for the assembly rules back. A sentence that
    said instead that no assembly rule could be graded would be false, and a reason an
    engineer cannot trust is worth less than silence.

    **One writer for one sentence.** The error result a withheld tool hands the model, the
    `unresolved` coverage item the same call writes, and the "NOT evaluated, and why" line
    of a pre-run digest all render this string, so "not covered" and "not covered because"
    cannot drift into two different explanations of one fact. The sentence names the rule,
    the evidence for it and what to do about it, because a reason an engineer cannot act
    on is worth no more than silence.
    """
    if package.features:
        return None
    return RMS_NOT_GRADABLE.format(profile=package.extractor.profile)


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

    `remodel` is feature 004's hook: the re-modeler's plan object
    (`tools/remodel_plan.RemodelToolContext`), set only for a remodel run's judgement
    phase. It is typed loosely for the same reason `bridge` is - the tool layer must not
    import the feature that fills it - and when it is `None` the four proposal tools and
    the plan read-back are not registered at all, so a review, a general-chat session and
    the Model check tab cannot see them.

    `extraction` says where this run's evidence comes from, and `eager` - the default -
    is what every run before lever 10a did: the meshes are in the package. `lazy` has a
    check fetch a body's mesh over the bridge when it needs one, and `lazy_bodies_fetched`
    counts how many this review has pulled back, because `lazy_fetch_body_limit` bounds one
    review rather than one call (contracts/levers.md, lever 10a).
    """

    package: LoadedPackage
    session: ReviewSession | None
    checklist: Checklist
    exceptions: ExceptionStore | list[Any] | None = None
    bridge: Any | None = None
    remodel: Any | None = None
    emit: EventCallback | None = None
    extraction: ExtractionSettings = field(default_factory=ExtractionSettings)
    lazy_bodies_fetched: int = 0
    tool_results_dir: Path | None = None
    """Where every recorded step's full result is written, as `step-<index>.json` (feature
    008, FR-021). Set only by `start_review`, to `<out>/tool-results`, so a check run, the
    Model check tab and MCP general chat write none."""
    finding_ids: FindingIdAllocator = field(default_factory=FindingIdAllocator)
    evidence_request_ids: EvidenceRequestIdAllocator = field(
        default_factory=EvidenceRequestIdAllocator
    )
    contact_ids: ContactIdAllocator = field(default_factory=ContactIdAllocator)
    joint_analysis: Any | None = None
    """Feature 010: the recognised fasteners and the joint map they are placed in, built once
    per context by `tools/checks_mechanical.joint_analysis` and read by `check_joints` and
    the interference tool's thread-model rule. Typed loosely, like `bridge`, so the tool
    context does not import the checks that fill it."""

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

    @property
    def current_step_id(self) -> int:
        """The index the next recorded `InvestigationStep` will take.

        Read inside a tool call, that is the step of the call in flight: `SessionSink`
        records the step *after* the tool function returns, with `index=len(steps)`
        (`tools/registry.py`), so a tool that writes a finding while it runs cites the
        step it is itself being recorded as. That is what `Finding.tool_result_ids` is
        for, and it is the only evidence a check has when its verdict rests on what the
        model was shown rather than on arithmetic.

        Raises `ValueError` through `require_session` for a context with no session: a
        step id is an index into a session's steps, and there are none to index.
        """
        return len(self.require_session().steps)

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

    def replace_coverage(self, check: str, bucket: CoverageBucket, item: CoverageItem) -> None:
        """Rewrite `check`'s item in `bucket`: drop what is there, then record `item`.

        An aggregated coverage item - one RMS rule over every document it was evaluated on
        (data-model.md section 2) - is rebuilt from the whole run each time the check tool
        runs, so calling the tool twice must leave one item, not two. Appending is what
        `record_coverage` does and is right for an item that stands for one occurrence;
        this is for the item that stands for the current state of a rule.

        The append and the event still go through `record_coverage`, so the pane sees the
        replacement exactly like any other coverage item and there is one path that writes
        coverage rather than two that could drift.
        """
        items = getattr(self.require_session().coverage, bucket)
        items[:] = [existing for existing in items if existing.check != check]
        self.record_coverage(bucket, item)

    def record_contact(self, contact: Contact) -> None:
        """Append a contact to the session's contact list (feature 010).

        No event of its own: a contact rides the judging tool's `tool.finished`, whose
        payload carries it, so the event schema does not grow a type (`contracts/
        contacts.md` section 3). Raises `ValueError` outside a review session, like every
        writer here.
        """
        self.require_session().contacts.append(contact)

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
        # Mirrored, not recomputed: the extractor decided the reuse and wrote it onto the
        # package, and a session that said anything else would be a second opinion about a
        # fact (data-model.md 9.5).
        reused_from=package.reused_from,
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
    extraction: ExtractionSettings | None = None,
) -> ToolContext:
    """A context over `package` with a fresh session and the versioned checklist.

    `model` reaches `new_session` untouched, so the per-provider default is resolved in
    exactly one place rather than restated here. `emit` is the run's event stream; a
    caller with no stream to write to - a fixture, a golden case - leaves it unset.
    `extraction` of `None` is the eager default, which is every caller that predates lever
    10a.
    """
    return ToolContext(
        package=package,
        session=new_session(package.package, model=model),
        checklist=checklist if checklist is not None else load_checklist(),
        exceptions=exceptions,
        bridge=bridge,
        emit=emit,
        extraction=extraction if extraction is not None else ExtractionSettings(),
    )


def context_for(
    package: EvidencePackage,
    *,
    base_dir: Path | str = ".",
    model: str | None = None,
) -> ToolContext:
    """A context over an in-memory package, for tests and the golden fixtures."""
    return build_context(LoadedPackage(package=package, base_dir=Path(base_dir)), model=model)
