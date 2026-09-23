"""The tool list handed to a provider, and the recording wrapper around every call.

`ToolRegistry.dispatch(context)` is the only way a tool reaches a provider: the runner
hands the adapter that `ToolDispatch`, and every call the model asks for - a registered
name or an invented one - comes back through it. (`build` is the same tools as a plain
list, for a caller that only wants to read their schemas.)
Each entry is a `RecordedTool` over a `ToolSpec` (`agent/providers/schema.py`), and its
`call` is the single choke point where five things happen for every tool call, in order
(FR-004, contracts/agent-tools.md):

1. the active `ToolContext` is bound, so the tool function itself takes only the
   arguments the model chose;
2. arguments are validated by `pydantic.validate_call` against the same signature the
   schema was generated from, on top of the id and enum checks the tool functions run;
3. the call is recorded through the sink - an `InvestigationStep` on the review session,
   or the general-chat chat log - with the arguments, a short result summary, the status
   and the elapsed time, whether the call succeeded or not;
4. a failure becomes a `ToolCallResult` with `is_error=True` and, on a review session, a
   `failed` coverage item, so it stays visible in the report instead of vanishing;
5. nothing raises. Ever. A validation error, an exception inside the tool, and a tool
   name that is not registered at all are all results the model can read.

An error result the tool function returned itself (`{"error": ...}` for an unknown id,
say) is treated exactly like a raised exception: same `is_error`, same `failed` coverage.
The model never has to guess whether a result was a result.

A `ToolDispatch` holds one further kind of entry, and only when lever 4 is on: a
`WithheldTool`, a tool this package's tier rule declined to offer. It is not in
`__iter__`, so no schema reaches the wire, and it *is* in `by_name`, so a model that asks
for it is told why rather than told it does not exist - as `unresolved` coverage with a
sentence an engineer can read, never as `failed` and never silently.

Two things are deliberately pluggable, because the MCP server for general chat (T059)
drives the *same* wrapper rather than a second copy of it:

- the **recording sink**, so a call can be recorded to `chat-log.jsonl` instead of to a
  review session;
- `ToolContext.session`, which is `None` for a general-chat context. `build` then needs
  an explicit sink: silently discarding the record is never the right default.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import validate_call
from pydantic_core import to_jsonable_python

from swreview.agent.providers import ToolCallResult, summarize_result
from swreview.agent.providers.schema import ToolSpec, tool_spec
from swreview.agent.settings import EfficiencySettings, ModelViewSettings
from swreview.report.session import (
    CoverageItem,
    CoverageScope,
    InvestigationStep,
    ReviewSession,
)
from swreview.tools import (
    bridge,
    checks_fastener,
    checks_fit,
    checks_interference,
    checks_mechanical,
    measure,
    query,
    remodel_plan,
    rms_checks,
    rms_query,
    session,
)
from swreview.tools.context import ToolContext, rms_not_gradable, use_context

Registration = Callable[[], tuple[Callable[..., Any], ...]]
"""One group of tools, named by the table it comes from in contracts/agent-tools.md."""


def query_tools() -> tuple[Callable[..., Any], ...]:
    """Package query tools: everything the model can read out of the package."""
    return (
        query.get_package_summary,
        query.list_components,
        query.get_component,
        query.find_components,
        query.list_mates,
        query.list_holes,
        query.list_fasteners,
        query.list_interferences,
        query.get_drawing_sheet,
        query.find_dimensions,
        query.list_gaps,
        query.get_exceptions,
        rms_query.list_features,
        rms_query.get_feature,
        rms_query.list_equations,
    )


def compact_query_tools() -> tuple[Callable[..., Any], ...]:
    """The opt-in bounded discovery experiment, absent from default tool surfaces."""
    return (query.compact_query,)


def measurement_tools() -> tuple[Callable[..., Any], ...]:
    """Measurement tools: deterministic geometry, no verdict and no finding."""
    return (
        measure.measure_axis_distance,
        measure.measure_face_gap,
        measure.check_tool_envelope,
        measure.bounding_box,
    )


def check_tools() -> tuple[Callable[..., Any], ...]:
    """Check tools: deterministic checks that write a finding to the session."""
    return (
        checks_fit.check_fit,
        checks_fit.check_axial_stack,
        checks_fastener.check_fastener_joint,
        checks_fastener.check_hole_alignment,
        checks_interference.check_interference_group,
        rms_checks.check_rms_part,
        rms_checks.check_rms_assembly,
        rms_checks.check_rms_equations,
        checks_mechanical.check_joints,
        checks_mechanical.check_mass_material,
        checks_mechanical.check_hygiene,
    )


def session_tools() -> tuple[Callable[..., Any], ...]:
    """Session tools: the only tools that write, and they only write to the session."""
    return (
        session.request_evidence,
        session.mark_coverage,
        session.record_drawing_finding,
        session.get_review_checklist,
        session.request_capture,
    )


def bridge_tools() -> tuple[Callable[..., Any], ...]:
    """Live SOLIDWORKS bridge tools: workstation only, and only with `--bridge`.

    Deliberately outside `REGISTRATIONS`: these three are added by `ToolRegistry.build`
    when the context carries a bridge, which only `--bridge` arranges. A package reviewed
    from exported files cannot see them at all (contracts/agent-tools.md).
    """
    return (
        bridge.bridge_capture,
        bridge.bridge_measure,
        bridge.bridge_interference,
    )


def remodel_tools() -> tuple[Callable[..., Any], ...]:
    """The re-modeler's judgement tools: a remodel run only, and only its judgement phase.

    Deliberately outside `REGISTRATIONS`, exactly as `bridge_tools` is: these five are added
    by `ToolRegistry._offered` when the context carries a remodel plan, which only
    `remodel/runner.py` arranges. A review, a general-chat session and the Model check tab
    carry no plan to propose into, so none of them can see these at all
    (`specs/004-resilient-remodeler/contracts/tools.md`).

    They are not query tools and not check tools, so they are in neither `MCP_TOOL_FUNCTIONS`
    nor the terminal profile's `enabled_tools`, and a test asserts both.
    """
    return (
        remodel_plan.propose_description,
        remodel_plan.propose_global,
        remodel_plan.decide_fillet,
        remodel_plan.classify_unknown,
        remodel_plan.get_remodel_plan,
    )


STANDARDS_RUN_ATTRIBUTE = "standards"
"""The attribute a standards run is carried on, and the one thing `_offered` asks about.

Named here rather than in `tools/standards_checks.py` so that the predicate below needs no
import at all: `checks/rules/run.py` imports this module, so this module cannot import the
standards family at the top of the file without a cycle. `attach_standards_run` reads the
name from here, so the setter and the reader cannot disagree about it.
"""


def standards_tools() -> tuple[Callable[..., Any], ...]:
    """The standards family's one review-only check tool: a standards run only (FR-035).

    Deliberately outside `REGISTRATIONS`, exactly as `remodel_tools` is: it is added by
    `ToolRegistry._offered` when the context carries a standards run, which only
    `checks/standards/run.py` arranges. A review, a general-chat session and every other
    tab carry none, so none of them can see it - which is what keeps `TOOL_FUNCTIONS`,
    `MCP_TOOL_FUNCTIONS` and the terminal profile's `enabled_tools` genuinely unmoved, and
    a test asserts all three.

    The import is local because `checks/rules/run.py` imports this module: the standards
    family reaches it through `checks/standards/traversal.py`, so importing the tool at the
    top of this file would close the cycle. It is called only when a standards run is in
    flight, by which time every module is loaded.
    """
    from swreview.tools import standards_checks

    return (standards_checks.check_standards,)


REGISTRATIONS: tuple[Registration, ...] = (
    query_tools,
    measurement_tools,
    check_tools,
    session_tools,
)
"""The extension point for a new group of tools: write a registration function that
returns them and add it here, in the order of contracts/agent-tools.md. The bridge tools
are the one group that is not here: they depend on the run, not on the build, so
`ToolRegistry.build` adds them when the context carries a bridge."""

TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = tuple(
    function for registration in REGISTRATIONS for function in registration()
)
"""Every tool the model gets, in the order of contracts/agent-tools.md.

There is no code-execution tool, no file tool and no SOLIDWORKS call outside this list
(FR-006).
"""

BRIDGE_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = bridge_tools()
"""The tools a `--bridge` run adds on top of `TOOL_FUNCTIONS`."""

REMODEL_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = remodel_tools()
"""The tools a remodel run's judgement phase adds on top of `TOOL_FUNCTIONS`."""

RESULT_KEY = "result"
"""Where a non-object tool result goes, so a tool result is always a JSON object.

Several query tools return a list (`list_components`, `list_gaps`, ...). Both provider
wire formats carry a tool result as an object, and `ToolCallResult.payload` is an object
for the same reason, so a list becomes `{"result": [...]}` here - at the one place that
knows it happened - rather than at each of the three adapters.
"""

COMPACT_QUERY_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = compact_query_tools()
"""Tools exposed only when `EfficiencySettings.compact_queries` is explicitly on."""

FINDING_DETAIL_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = (session.get_finding,)
"""Offered only with payload slimming on (feature 008, research R2.26): a slimmed check result
lists its findings as a digest, and this is how the model reads one in full. With slimming
off every check result already carries its findings whole, so the tool array stays
`TOOL_FUNCTIONS` byte for byte. Never in MCP or the terminal profile - general chat has no
session to read a finding from."""


def error_payload(message: str) -> dict[str, Any]:
    """The one error shape a failed call reports, whatever the failure was."""
    return {"error": message}


# --- recording -----------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool call as the sink sees it: the trace line, not a second copy of the result.

    The fields are exactly the ones an `InvestigationStep` (feature 001's session) and a
    `chat-log.jsonl` line (data-model section 6) both carry, which is why one record
    shape serves both sinks.
    """

    tool: str
    arguments: dict[str, Any]
    result_summary: str
    status: Literal["ok", "error"]
    elapsed_s: float
    error: str | None
    withheld: bool = False
    """This call was refused because the tool was not offered this run (lever 4).

    The refusal has already written its own `unresolved` coverage item naming the tier
    rule, so `SessionSink` must not add the `failed` item it writes for a tool that ran
    and broke: `failed` says the tool broke, and this one did not. Defaulted, so the chat
    log and every existing caller are unchanged.
    """


@runtime_checkable
class RecordingSink(Protocol):
    """Where a `RecordedTool` writes what it just did.

    `SessionSink` is the review-session implementation; the general-chat MCP server
    passes its own, so the never-raise rule and the error conversion above it are shared
    rather than reimplemented.
    """

    def record(self, record: ToolCallRecord) -> None: ...


@dataclass(frozen=True)
class SessionSink:
    """Records into a feature 001 `ReviewSession`: a step, and `failed` coverage on error.

    With one exception, and it is the whole point of `WithheldTool`: a call refused because
    the tool was not offered this run is recorded as a step and nothing more, because it
    has already written the `unresolved` item that says why.

    It writes the `failed` item through `ToolContext.record_coverage` rather than onto the
    session directly, so the one bucket the model may not write itself still reaches the
    event stream the way every other coverage item does (FR-013).
    """

    context: ToolContext

    @property
    def session(self) -> ReviewSession:
        return self.context.require_session()

    def record(self, record: ToolCallRecord) -> None:
        session = self.session
        session.steps.append(
            InvestigationStep(
                index=len(session.steps),
                tool=record.tool,
                arguments=record.arguments,
                result_summary=record.result_summary,
                status=record.status,
                elapsed_s=record.elapsed_s,
                error=record.error,
            )
        )
        if record.error is None or record.withheld:
            return
        self.context.record_coverage(
            "failed",
            CoverageItem(
                check=f"tool.{record.tool}",
                scope=CoverageScope(),
                reason=(
                    f"tool {record.tool} failed; whatever it was called for is not covered"
                ),
                error=record.error,
            ),
        )


# --- one recorded tool ----------------------------------------------------------------

_SPECS: dict[Callable[..., Any], ToolSpec] = {}
_VALIDATORS: dict[Callable[..., Any], Callable[..., Any]] = {}
"""Both derivations are pure functions of the tool function and neither is cheap, so they
are computed once per process rather than once per `build` (a review builds the registry
once; the test suite builds it hundreds of times)."""


def spec_for(function: Callable[..., Any]) -> ToolSpec:
    """The `ToolSpec` for one tool function, built once."""
    cached = _SPECS.get(function)
    if cached is None:
        cached = tool_spec(function)
        _SPECS[function] = cached
    return cached


def _validator_for(function: Callable[..., Any]) -> Callable[..., Any]:
    cached = _VALIDATORS.get(function)
    if cached is None:
        cached = validate_call(function)
        _VALIDATORS[function] = cached
    return cached


def _admits_null(property_schema: Any) -> bool:
    """Whether this property's canonical schema allows `null`."""
    if not isinstance(property_schema, dict):
        return False
    declared = property_schema.get("type")
    if declared == "null" or (isinstance(declared, list) and "null" in declared):
        return True
    for keyword in ("anyOf", "oneOf"):
        branches = property_schema.get(keyword)
        if isinstance(branches, list) and any(_admits_null(branch) for branch in branches):
            return True
    return False


class RecordedTool:
    """One curated tool: schema-bound, validated, context-bound, and recorded.

    Implements `agent.providers.ProviderTool`, which is all an adapter ever sees: a name,
    a description, the canonical schema it converts for its own wire format, and a `call`
    that never raises.
    """

    def __init__(
        self,
        spec: ToolSpec,
        *,
        context: ToolContext,
        sink: RecordingSink,
        forced_failure: bool = False,
        trim_description: bool = False,
    ) -> None:
        self.spec = spec
        self.context = context
        self.sink = sink
        self.forced_failure = forced_failure
        self.trim_description = trim_description
        """Lever 2, applied here rather than in `spec_for`: see `description`."""

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        """What this run puts on the wire: the first paragraph, or both halves rejoined.

        **This is lever 2's application point, and it is here on purpose.** `_SPECS` is
        process-global and keyed by function, so a flag read while building the spec would
        let the first run in a process decide for every later one - the benchmark runner
        plays six runs in one process - while both runs still recorded the settings they
        asked for. A `RecordedTool` is built per run, with that run's settings in scope.

        Flag off hands over `full_description`, which FR-039 pins byte-equal to the
        pre-split docstring body, so one commit runs both arms of the A/B.
        """
        return self.spec.wire_description(trim=self.trim_description)

    @property
    def schema(self) -> dict[str, Any]:
        return self.spec.schema

    def call(self, arguments: Mapping[str, Any], call_id: str = "") -> ToolCallResult:
        """Run the tool, record the call, and hand back a result - never an exception.

        `call_id` is the provider's correlation id, carried straight through onto the
        result so an adapter can pair the two up. It defaults to empty because the caller
        is not always a provider: a test, and the MCP server, call a tool directly.
        """
        if not isinstance(arguments, Mapping):
            refused = error_payload(
                f"tool arguments must be an object, got {type(arguments).__name__}"
            )
            return self._finish({}, refused, call_id, 0.0)
        given = dict(arguments)
        started = perf_counter()
        try:
            if self.forced_failure:
                raise RuntimeError(f"tool {self.name!r} was told to fail (--fail-tool)")
            with use_context(self.context):
                returned = _validator_for(self.spec.fn)(**self._prepared(given))
            payload = self._as_object(to_jsonable_python(returned))
        except Exception as exc:  # noqa: BLE001 - every failure becomes a tool result
            payload = error_payload(f"{type(exc).__name__}: {exc}")
        return self._finish(given, payload, call_id, perf_counter() - started)

    def _prepared(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """`arguments` with the nulls that mean "use the default" dropped.

        OpenAI strict mode has no way to leave a property out: every property is required
        and an optional one is rewritten as `["T", "null"]` (`providers/schema.py`). A
        null for a parameter whose own annotation does not admit one therefore means the
        model did not care, not that it wants `None` - so it is dropped here and the
        function's default applies. A parameter that really is `T | None` keeps its null.
        """
        properties = self.schema.get("properties", {})
        return {
            name: value
            for name, value in arguments.items()
            if value is not None or name not in properties or _admits_null(properties[name])
        }

    @staticmethod
    def _as_object(payload: Any) -> dict[str, Any]:
        return payload if isinstance(payload, dict) else {RESULT_KEY: payload}

    def _finish(
        self,
        arguments: dict[str, Any],
        payload: dict[str, Any],
        call_id: str,
        elapsed_s: float,
    ) -> ToolCallResult:
        error = str(payload["error"]) if "error" in payload else None
        record_call(
            self.sink,
            tool=self.name,
            arguments=arguments,
            payload=payload,
            elapsed_s=elapsed_s,
            error=error,
        )
        return ToolCallResult(call_id=call_id, payload=payload, is_error=error is not None)


def record_call(
    sink: RecordingSink,
    *,
    tool: str,
    arguments: Mapping[str, Any],
    payload: Mapping[str, Any],
    elapsed_s: float,
    error: str | None,
    withheld: bool = False,
) -> None:
    """Write one call to `sink`, summarized the way every consumer of a trace expects.

    `summarize_result` is the adapters' own summarizer, so the `tool.finished` event in
    the pane and the `InvestigationStep` in `session.json` read alike rather than being
    two renderings of the same call.

    `withheld` says this call was refused because the tool was not offered this run, which
    is the one error a session sink must not turn into `failed` coverage.
    """
    sink.record(
        ToolCallRecord(
            tool=tool,
            arguments=to_jsonable_python(dict(arguments)),
            result_summary=summarize_result(payload),
            status="error" if error is not None else "ok",
            elapsed_s=max(elapsed_s, 0.0),
            error=error,
            withheld=withheld,
        )
    )


# --- the package-decidable tool tiers (lever 4) ----------------------------------------

RMS_TIER_TOOLS: tuple[str, ...] = (
    "list_features",
    "get_feature",
    "list_equations",
    "check_rms_part",
    "check_rms_assembly",
    "check_rms_equations",
)
"""Tier R: the six tools a package with no feature rows cannot use.

Three package-query tools and three check tools, withheld together because they read one
thing - the feature tree - and it is not there. Named here once;
`tests/unit/test_tool_payload.py` weighs what they cost and regenerates the figure rather
than restating it.
"""

RMS_TIER_CHECKLIST_ITEM = "modeling.resilience"
"""The checklist item Tier R closes out when it withholds (`agent/checklist_v1.yaml`)."""


@dataclass(frozen=True)
class ToolTier:
    """One tier this run withholds: which tools, why, and the checklist item it closes.

    **A tier rule is decidable from the package before the first turn and does not change
    for the life of the session** (contracts/tool-tiers.md section 3). That scope is not a
    simplification, it is the guarantee: a tool array that changed between turn 1 and
    turn 2 would be a `tools_changed` cache miss for the rest of the session on OpenAI,
    and would make two turns structurally different in a way the step log does not record.
    The dynamic "check tools once evidence exists" tier was therefore **dropped from this
    lever rather than deferred**: it is a claim about the conversation, not the package,
    and `start()` plays one opening turn that does the whole review, so there is usually no
    turn 2 to add tools back in. The waste it bet against is attacked by lever 5 instead.

    Tier B, "bridge tools only when a bridge is wired", predates this lever and lives in
    `ToolRegistry.functions_for`; it is not expressed here because nothing is withheld from
    the model's point of view - a package reviewed from exported files never had them.

    Deliberately **not** the mechanism here: OpenAI's
    `tool_choice: {"type": "allowed_tools", ...}` and Gemini's
    `FunctionCallingConfig(mode=ANY, allowed_function_names=[...])`. Both narrow what the
    model may call without removing the schemas from the request - perfect for the prompt
    cache and zero tokens saved. That makes them the right mechanism for a future "focus
    the model" lever and the wrong one for lever 4, whose whole purpose is bytes.
    """

    tools: tuple[str, ...]
    reason: str
    checklist_item: str | None


def withheld_tier(
    context: ToolContext, efficiency: EfficiencySettings | None
) -> ToolTier | None:
    """The tier this run withholds, or `None` when it withholds nothing.

    Asked once, when the dispatch is built, which `start_review` does once per session.
    `efficiency` of `None` - every caller that predates feature 005 - is every lever off.
    """
    if efficiency is None or not efficiency.tool_tiers:
        return None
    reason = rms_not_gradable(context.ir)
    if reason is None:
        return None
    return ToolTier(
        tools=RMS_TIER_TOOLS,
        reason=reason,
        checklist_item=RMS_TIER_CHECKLIST_ITEM,
    )


@dataclass(frozen=True)
class WithheldTool:
    """A tool this run did not expose: not on the wire, still in the dispatch.

    **It is not in `ToolDispatch.__iter__`**, which is the entire point - no schema reaches
    the wire, and that is where the bytes are saved. **`ToolDispatch.by_name` resolves it**,
    so a model that asks for it anyway is told *why* it was not offered instead of being
    handed "no tool named ..." and the list of the other thirty-one.

    That difference is the difference between "not covered" and "not covered because":
    a call here writes an `unresolved` coverage item, which is a bucket
    `Checklist.bucket_of` searches, so the item is closed out **with a sentence an engineer
    can read** rather than left open for finalization to restate generically. It is not
    `failed`, which would say the tool broke when in fact we declined to offer it, and
    which closes nothing.

    A name that is neither registered nor withheld is unchanged: `ToolDispatch.call` gives
    it the error it always gave and the `failed` item it always wrote. A hallucinated name
    is routine, not exceptional, and that path is load-bearing.
    """

    name: str
    reason: str
    checklist_item: str | None
    context: ToolContext
    sink: RecordingSink

    @property
    def check(self) -> str:
        """The coverage `check` this refusal writes against."""
        return self.checklist_item or f"tool.{self.name}"

    def call(self, arguments: Mapping[str, Any], call_id: str = "") -> ToolCallResult:
        """Say why the tool was not offered, and write the coverage item that says it too.

        `replace_coverage` rather than `record_coverage`: the item stands for the state of
        the rule, not for one occurrence of the call, so asking twice leaves one item.

        A context with no review session - general chat - has no coverage to write, and the
        model still gets the sentence. It never raises, which is the rule every path
        through this module obeys.
        """
        payload = error_payload(self.reason)
        session = self.context.session
        if session is not None:
            self.context.replace_coverage(
                self.check,
                "unresolved",
                CoverageItem(
                    check=self.check,
                    scope=CoverageScope(),
                    reason=self.reason,
                    error=None,
                ),
            )
            if self.check not in session.withheld_checks:
                # The one recorded fact behind `unresolved_because_withheld` (FR-054).
                # Deduped for the same reason the item is replaced rather than appended:
                # it stands for the state of the rule, not for one occurrence of the call.
                session.withheld_checks.append(self.check)
        record_call(
            self.sink,
            tool=self.name,
            arguments=arguments,
            payload=payload,
            elapsed_s=0.0,
            error=self.reason,
            withheld=True,
        )
        return ToolCallResult(call_id=call_id, payload=payload, is_error=True)


# --- the registry ---------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDispatch:
    """The built tools plus the name lookup a provider dispatches through.

    This is the `agent.providers.ToolSet` the runner hands an adapter: iterating it yields
    the tools to encode, and `call` is the only way a call is made. A provider that names
    a tool nobody registered gets an error result naming what it asked for, recorded like
    any other failed call. Feature 001 never needed this: the vendor SDK matched names
    before the registry saw them. A manual tool loop does not, and a hallucinated name is
    routine, not exceptional - which is why the adapters dispatch through here rather than
    resolving names themselves and synthesizing a result nobody records.
    """

    tools: tuple[RecordedTool, ...]
    sink: RecordingSink
    withheld: tuple[WithheldTool, ...] = ()
    """The tools a tier declined to offer this run (lever 4). Empty with the flag off.

    `tools` then holds two kinds of entry and **`__iter__` filters while `by_name` does
    not**: a small explicit split inside one dataclass, not a new layer.
    """

    def __iter__(self) -> Iterator[RecordedTool]:
        """Only the tools that go on the wire; a withheld tool has no schema to encode."""
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    @property
    def by_name(self) -> dict[str, RecordedTool | WithheldTool]:
        """Every name this dispatch answers to, offered or withheld."""
        return {tool.name: tool for tool in (*self.tools, *self.withheld)}

    def get(self, name: str) -> RecordedTool | WithheldTool | None:
        """The tool called `name`, or `None` when nothing is registered under it."""
        return self.by_name.get(name)

    def call(
        self,
        name: str,
        arguments: Mapping[str, Any],
        call_id: str = "",
    ) -> ToolCallResult:
        """Dispatch one call by name. An unknown name is a result, not a raise."""
        tool = self.get(name)
        if tool is not None:
            return tool.call(arguments, call_id)
        payload = error_payload(
            # The offered names only. A withheld tool is not available, so advertising it
            # here would invite the call whose whole point was to save its bytes.
            f"no tool named {name!r}; the tools available are "
            f"{sorted(tool.name for tool in self.tools)}"
        )
        record_call(
            self.sink,
            tool=name,
            arguments=arguments,
            payload=payload,
            elapsed_s=0.0,
            error=str(payload["error"]),
        )
        return ToolCallResult(call_id=call_id, payload=payload, is_error=True)


@dataclass(frozen=True)
class ToolRegistry:
    """The curated tool surface. `build` and `dispatch` are the only entry points."""

    functions: tuple[Callable[..., Any], ...] = TOOL_FUNCTIONS
    bridge_functions: tuple[Callable[..., Any], ...] = BRIDGE_TOOL_FUNCTIONS
    remodel_functions: tuple[Callable[..., Any], ...] = REMODEL_TOOL_FUNCTIONS

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(function.__name__ for function in self.functions)

    def functions_for(
        self,
        context: ToolContext,
        *,
        efficiency: EfficiencySettings | None = None,
        model_view: ModelViewSettings | None = None,
    ) -> tuple[Callable[..., Any], ...]:
        """The tools this run gets: the curated list, less any tier it withholds, plus the
        bridge when one is wired and the remodel tools when a plan is being judged."""
        return self._offered(
            context,
            withheld_tier(context, efficiency),
            compact_queries=efficiency is not None and efficiency.compact_queries,
            finding_detail=model_view is not None and model_view.payload_slimming,
        )

    def _offered(
        self,
        context: ToolContext,
        tier: ToolTier | None,
        *,
        compact_queries: bool = False,
        finding_detail: bool = False,
    ) -> tuple[Callable[..., Any], ...]:
        """`functions_for` with the tier already decided, so `dispatch` decides it once.

        The conditional groups are appended in the order they were added to the product and
        none is subject to a tier: a tier withholds a *review* tool on the evidence the
        package carries, and a bridge call, a proposal into a plan and a standards check
        over an already-decided graded set are none of them. `get_finding` comes with
        payload slimming (feature 008), beside `compact_query`.
        """
        functions = self.functions
        if tier is not None:
            functions = tuple(fn for fn in functions if fn.__name__ not in tier.tools)
        if compact_queries:
            functions = (*functions, *COMPACT_QUERY_TOOL_FUNCTIONS)
        if finding_detail:
            functions = (*functions, *FINDING_DETAIL_TOOL_FUNCTIONS)
        if context.bridge is not None:
            functions = (*functions, *self.bridge_functions)
        if context.remodel is not None:
            functions = (*functions, *self.remodel_functions)
        if getattr(context, STANDARDS_RUN_ATTRIBUTE, None) is not None:
            functions = (*functions, *standards_tools())
        return functions

    def dispatch(
        self,
        context: ToolContext,
        fail_tool: Iterable[str] = (),
        *,
        sink: RecordingSink | None = None,
        efficiency: EfficiencySettings | None = None,
        model_view: ModelViewSettings | None = None,
    ) -> ToolDispatch:
        """The built tools plus the name lookup, bound to `context` and `sink`.

        `sink` defaults to recording into `context.session`; a context without a session
        (general chat) has to pass one, because a call that is recorded nowhere is
        invisible in both the report and the chat log.

        `fail_tool` names tools that must raise instead of running - the `--fail-tool`
        test hook that proves a failed tool ends up in `failed` coverage rather than
        stopping the review. An unknown name is a caller mistake and raises.

        `efficiency` is this run's lever flags, read **after** `spec_for` and applied to
        the per-run `RecordedTool` rather than to the process-global spec cache
        (`RecordedTool.description`). `None` means every lever off, which is what every
        caller that predates feature 005 - the MCP bind, the tests - gets.

        Lever 4 is read here too, and **this is the only place it is read**: the tier is
        decided once, from the package, and the dispatch that results is the one `ReviewRun`
        hands every turn of the session. Nothing downstream can change the tool array
        mid-session, which is what makes "no `tools_changed` cache miss" true by
        construction rather than by discipline.

        `model_view` is what the model reads of each result (feature 008). `None` - every
        caller that predates it - and `MODEL_VIEW_OFF` give today's tools and today's
        results; payload slimming adds `get_finding`.
        """
        recorder = self._sink_for(context, sink)
        tier = withheld_tier(context, efficiency)
        functions = self._offered(
            context,
            tier,
            compact_queries=efficiency is not None and efficiency.compact_queries,
            finding_detail=model_view is not None and model_view.payload_slimming,
        )
        names = [function.__name__ for function in functions]
        forced = set(fail_tool)
        unknown = sorted(forced - set(names))
        if unknown:
            raise ValueError(f"fail_tool names no such tool: {unknown}; known: {names}")
        trim = efficiency is not None and efficiency.trim_tool_descriptions
        tools = tuple(
            RecordedTool(
                spec_for(function),
                context=context,
                sink=recorder,
                forced_failure=function.__name__ in forced,
                trim_description=trim,
            )
            for function in functions
        )
        withheld = (
            ()
            if tier is None
            else tuple(
                WithheldTool(
                    name=name,
                    reason=tier.reason,
                    checklist_item=tier.checklist_item,
                    context=context,
                    sink=recorder,
                )
                for name in tier.tools
            )
        )
        return ToolDispatch(tools=tools, sink=recorder, withheld=withheld)

    def build(
        self,
        context: ToolContext,
        fail_tool: Iterable[str] = (),
        *,
        sink: RecordingSink | None = None,
        efficiency: EfficiencySettings | None = None,
        model_view: ModelViewSettings | None = None,
    ) -> list[RecordedTool]:
        """The provider-ready tools bound to `context`, in registration order."""
        return list(
            self.dispatch(
                context, fail_tool, sink=sink, efficiency=efficiency, model_view=model_view
            ).tools
        )

    @staticmethod
    def _sink_for(context: ToolContext, sink: RecordingSink | None) -> RecordingSink:
        if sink is not None:
            return sink
        if context.session is None:
            raise ValueError(
                "this ToolContext has no review session, so building its tools needs an "
                "explicit recording sink: a tool call recorded nowhere is invisible"
            )
        return SessionSink(context)


def build_tools(
    context: ToolContext,
    fail_tool: Iterable[str] = (),
    *,
    sink: RecordingSink | None = None,
) -> list[RecordedTool]:
    """The default curated tool list, bound to `context`."""
    return ToolRegistry().build(context, fail_tool=fail_tool, sink=sink)
