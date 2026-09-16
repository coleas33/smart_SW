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
    measure,
    query,
    rms_checks,
    rms_query,
    session,
)
from swreview.tools.context import ToolContext, use_context

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

RESULT_KEY = "result"
"""Where a non-object tool result goes, so a tool result is always a JSON object.

Several query tools return a list (`list_components`, `list_gaps`, ...). Both provider
wire formats carry a tool result as an object, and `ToolCallResult.payload` is an object
for the same reason, so a list becomes `{"result": [...]}` here - at the one place that
knows it happened - rather than at each of the three adapters.
"""


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
        if record.error is None:
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
    ) -> None:
        self.spec = spec
        self.context = context
        self.sink = sink
        self.forced_failure = forced_failure

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

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
) -> None:
    """Write one call to `sink`, summarized the way every consumer of a trace expects.

    `summarize_result` is the adapters' own summarizer, so the `tool.finished` event in
    the pane and the `InvestigationStep` in `session.json` read alike rather than being
    two renderings of the same call.
    """
    sink.record(
        ToolCallRecord(
            tool=tool,
            arguments=to_jsonable_python(dict(arguments)),
            result_summary=summarize_result(payload),
            status="error" if error is not None else "ok",
            elapsed_s=max(elapsed_s, 0.0),
            error=error,
        )
    )


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

    def __iter__(self) -> Iterator[RecordedTool]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    @property
    def by_name(self) -> dict[str, RecordedTool]:
        return {tool.name: tool for tool in self.tools}

    def get(self, name: str) -> RecordedTool | None:
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
            f"no tool named {name!r}; the tools available are {sorted(self.by_name)}"
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

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(function.__name__ for function in self.functions)

    def functions_for(self, context: ToolContext) -> tuple[Callable[..., Any], ...]:
        """The tools this run gets: the curated list, plus the bridge when one is wired."""
        if context.bridge is None:
            return self.functions
        return (*self.functions, *self.bridge_functions)

    def dispatch(
        self,
        context: ToolContext,
        fail_tool: Iterable[str] = (),
        *,
        sink: RecordingSink | None = None,
    ) -> ToolDispatch:
        """The built tools plus the name lookup, bound to `context` and `sink`.

        `sink` defaults to recording into `context.session`; a context without a session
        (general chat) has to pass one, because a call that is recorded nowhere is
        invisible in both the report and the chat log.

        `fail_tool` names tools that must raise instead of running - the `--fail-tool`
        test hook that proves a failed tool ends up in `failed` coverage rather than
        stopping the review. An unknown name is a caller mistake and raises.
        """
        recorder = self._sink_for(context, sink)
        functions = self.functions_for(context)
        names = [function.__name__ for function in functions]
        forced = set(fail_tool)
        unknown = sorted(forced - set(names))
        if unknown:
            raise ValueError(f"fail_tool names no such tool: {unknown}; known: {names}")
        tools = tuple(
            RecordedTool(
                spec_for(function),
                context=context,
                sink=recorder,
                forced_failure=function.__name__ in forced,
            )
            for function in functions
        )
        return ToolDispatch(tools=tools, sink=recorder)

    def build(
        self,
        context: ToolContext,
        fail_tool: Iterable[str] = (),
        *,
        sink: RecordingSink | None = None,
    ) -> list[RecordedTool]:
        """The provider-ready tools bound to `context`, in registration order."""
        return list(self.dispatch(context, fail_tool, sink=sink).tools)

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
