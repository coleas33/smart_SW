"""The provider port: the only way the runner talks to a model (plan.md Phase 1, point 1).

An adapter owns everything provider-specific - history encoding, tool encoding, effort
mapping, streaming, error mapping - and hands back two provider-neutral things: uniform
`AgentEvent` bodies through `on_event`, and a `TurnResult`. The runner owns everything
else: the step budget, session recording, evidence requests, finalization, and multi-turn.

Two boundaries are worth stating explicitly, because getting either wrong leaks provider
detail past the adapter:

**Events carry no sequence number here.** `seq` is monotonic *per session* and an adapter
cannot know it: it sees one turn. Adapters therefore call `on_event(event_type, body)` and
the runner's sink stamps `seq` and `at` and builds the `AgentEvent`. `AgentEvent` is the
serialized form - one line of `events.jsonl`, one server-sent event -
and `specs/002-task-pane-assistant/contracts/chat-events.schema.json` is authoritative for
every body; the literals below are asserted against it in
`tests/unit/test_provider_protocol.py`.

**Tools reach the adapter as one `ToolSet`, never as a list it has to resolve names in.**
`tools/registry.py` builds a `RecordedTool` around each `ToolSpec` (name, description,
canonical schema, function) and a `ToolDispatch` around the lot. An adapter iterates the
set for `tool.name` and `tool.schema` - which it converts with `providers/schema.py`'s
`strictify()` or `gemini_adapt()` - and dispatches every call the model asks for through
`tools.call(name, arguments, call_id)`, which validates, records and never raises: it
returns a `ToolCallResult` with `is_error` set, for a name that is registered and for one
that is not.

The provider-neutral message history is a list of plain dicts owned by the runner
(data-model section 3). Adapters translate it both ways and must keep to this shape:

    {"role": "user",      "content": <str>}
    {"role": "assistant", "content": <str>, "tool_calls": [{"call_id", "name", "arguments"}]}
    {"role": "tool",      "call_id": <str>, "name": <str>, "content": <dict>, "is_error": <bool>}

`tool_calls` is present only when the turn made calls; an adapter that needs provider-only
state (OpenAI's reasoning items, say) keeps it under a key namespaced with its own name.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ADAPTER_MODULES",
    "CACHED_SHARE_PUBLISHABLE",
    "FRAMING_TOKENS",
    "SUMMARY_LENGTH",
    "AgentEvent",
    "AgentProvider",
    "EffortLevel",
    "EffortMapping",
    "EventCallback",
    "EventType",
    "PromptCacheAware",
    "ProviderName",
    "ProviderTool",
    "TokenUsage",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolSet",
    "TurnEndReason",
    "TurnResult",
    "UnknownProviderError",
    "WithdrawableTools",
    "available",
    "call_tool",
    "error_body",
    "get",
    "model_payload",
    "register",
    "summarize_result",
    "tool_result_text",
    "tools_withdrawn",
    "usage_body",
    "usage_from_body",
]


class ProviderName(StrEnum):
    """The providers this product supports. No other value is constructible (FR-026)."""

    OPENAI = "openai"
    GEMINI = "gemini"
    FAKE = "fake"


EffortLevel = Literal["low", "medium", "high", "xhigh"]
"""What the engineer asks for. Each adapter maps it to its own control, or fails fast."""

EventType = Literal[
    "session.started",
    "text.delta",
    "text.done",
    "tool.started",
    "tool.finished",
    "finding",
    "evidence.requested",
    "evidence.answered",
    "disposition",
    "coverage",
    "usage",
    "turn.ended",
    "session.ended",
    "error",
]
"""Mirrors the `type` enum of chat-events.schema.json, which is authoritative."""

TurnEndReason = Literal["end", "max_steps", "error", "stopped", "truncated"]
"""Mirrors the `turn.ended` body enum. `truncated` is the provider's output ceiling."""


class ProviderModel(BaseModel):
    """Strict by default: an unexpected field is a bug, not something to carry along."""

    model_config = ConfigDict(extra="forbid")


class EffortMapping(ProviderModel):
    """What the requested effort became for this provider and model.

    Recorded in the session and in `session.started` so a run can be read back without
    guessing: `provider_value` is a string on OpenAI (`reasoning.effort`) and an integer
    on Gemini 2.5 models, whose control is `thinking_budget`.
    """

    requested: EffortLevel
    provider_param: str
    provider_value: str | int


TokenCount = Annotated[int, Field(ge=0)] | None
"""One reported token count. `None` is "the provider did not report it", `0` is "it
reported zero", and nothing anywhere coerces one into the other (Principle I)."""


class TokenUsage(ProviderModel):
    """What one model round trip cost, in the fields the provider actually reported.

    Provider-neutral and produced by the adapters, so it lives here beside
    `EffortMapping` for the same reason that one does. **One record is one round trip,
    not one turn**: `OpenAIProvider.run` is a `while True` loop whose body makes exactly
    one request, so a turn with six serial tool calls is seven requests and seven of
    these.

    The two providers' sub-counts nest differently and are never summed across them: on
    OpenAI `reasoning_tokens` is a subset of `output_tokens` and tool-result tokens are
    already inside `input_tokens`, while on Gemini `thoughts_token_count` and
    `tool_use_prompt_token_count` are separate addends of the total. The raw fields are
    what is recorded; `total_tokens` is the only one a cross-provider comparison may use.
    """

    input_tokens: TokenCount
    cached_input_tokens: TokenCount
    cache_write_tokens: TokenCount  # OpenAI only; always None on Gemini
    output_tokens: TokenCount
    reasoning_tokens: TokenCount
    tool_result_input_tokens: TokenCount  # Gemini only; inside input_tokens on OpenAI
    total_tokens: TokenCount
    latency_s: float = Field(ge=0)
    """Wall clock for the one request, measured by the adapter. Never `None`: if we made
    the call, we timed it."""

    @property
    def _contained_counts(self) -> tuple[int, int] | None:
        """`(input_tokens, cached_input_tokens)` when both are known **and** cached is a
        part of input; `None` otherwise.

        The one containment check, read by both derived values below so neither decides
        for itself. The containment is VERIFIED for Gemini and UNVERIFIED for OpenAI
        until probe L1 (T025) runs, so a record that violates it is reachable and must
        not become arithmetic anybody trusts: both derived values go `None` - unknown -
        while the raw counts are still recorded verbatim, so the violation stays visible
        wherever the record is read.
        """
        input_tokens, cached = self.input_tokens, self.cached_input_tokens
        if input_tokens is None or cached is None or cached > input_tokens:
            return None
        return input_tokens, cached

    @property
    def uncached_input_tokens(self) -> int | None:
        """`input - cached` when both are known and cached is contained in input.

        A property and not a field, so it cannot go stale - the rule `Timing.replace`
        already follows. It is well defined only because cached input is contained in
        input on both providers (VERIFIED for Gemini, asserted by probe L1 for OpenAI),
        so a record where it is not returns `None` rather than a negative count.
        """
        counts = self._contained_counts
        if counts is None:
            return None
        input_tokens, cached = counts
        return input_tokens - cached

    @property
    def cached_input_share(self) -> float | None:
        """`cached / input` when both are known and input is not zero, `None` otherwise.

        Defined here, once, because the report and the scorecard both publish it and two
        formulas would be two numbers (data-model.md section 2.1). A share of nothing is
        `None` and not `0.0`: no input tokens were reported, so no share was reported.

        The number is meaningful only if cached input is contained in input, which is
        VERIFIED for Gemini and UNVERIFIED for OpenAI until probe L1 runs, which is why
        `CACHED_SHARE_PUBLISHABLE` gates what a reader is shown rather than what is
        computed. A record that reports `cached > input` therefore has **no** share:
        `None`, never a ratio above 1. That keeps the `0..1` bound the scorecard and
        `scorecard.schema.json` declare true, so an unverified fact about a provider's
        own counts cannot make a whole benchmark run unscoreable.
        """
        counts = self._contained_counts
        if counts is None:
            return None
        input_tokens, cached = counts
        if input_tokens == 0:
            return None
        return cached / input_tokens


CACHED_SHARE_PUBLISHABLE = False
"""Has probe L1 recorded that cached input is contained in input (FR-047)?

`TokenUsage.cached_input_share` is computed from the first commit of this feature, but a
share is only well defined if the cached count is a part of the input count rather than a
number beside it. That containment is VERIFIED for Gemini and UNVERIFIED for OpenAI until
probe L1 (T025) runs against a live key and its output is recorded in
`specs/005-llm-efficiency/probe-log.md`. Until then every published surface - the report's
`## Tokens` section, the scorecard's markdown column and the ledger's - renders the share
as `unknown`, which is what it is.

Flipping this to `True` is the act of publishing the column, and it belongs in the same
change that records L1's output. It lives beside `TokenUsage` because it is a claim about
what the providers' own counts mean.
"""


class ToolCallRequest(ProviderModel):
    """One tool call the model asked for, after the adapter parsed its arguments.

    OpenAI delivers arguments as a JSON string and Gemini as a dict; both become a dict
    here, before `RecordedTool` validates them against the tool's schema.
    """

    call_id: str
    name: str
    arguments: dict[str, Any]


class ToolCallResult(ProviderModel):
    """What one tool call produced. Never an exception: `is_error` carries the failure.

    The adapter encodes it for its own wire format (`function_call_output` text on
    OpenAI, a `function_response` part on Gemini) and pairs it back to the request by
    `call_id`.
    """

    call_id: str
    payload: dict[str, Any]
    is_error: bool
    view: dict[str, Any] | None = None
    """What the model reads of the result when payload slimming is on (feature 008), set
    once at `RecordedTool._finish`; `None` otherwise. `payload` is always the tool's full
    return - the step summary, the `tool.finished` event, MCP and the goldens read it - and
    `model_payload` is the only thing an adapter puts into its history."""


def model_payload(result: ToolCallResult) -> dict[str, Any]:
    """What the model is sent for one tool result: the view when there is one, else the payload.

    The one reading of `ToolCallResult` every adapter's history is built from (research
    R2.24), so no adapter can send the full payload where the view was meant, or the other
    way round.
    """
    return result.view if result.view is not None else result.payload


class AgentEvent(ProviderModel):
    """One line of `events.jsonl` and one server-sent event.

    `body` is deliberately untyped here: `chat-events.schema.json` is authoritative for
    every body and several of them are `$ref`s into the feature 001 review-session
    contract (`Finding`, `EvidenceRequest`, `CoverageItem`, `Timing`). Duplicating those
    as models would mean two definitions to keep in step; the contract test validates
    every event type against the schema instead.
    """

    seq: int = Field(ge=1)
    at: datetime
    type: EventType
    body: dict[str, Any]


EventCallback = Callable[[EventType, Mapping[str, Any]], None]
"""How an adapter emits: the runner's sink stamps `seq` and `at` and writes the event."""


def error_body(*, error_class: str, message: str, retryable: bool) -> dict[str, Any]:
    """The one shape a failure is reported in.

    These three fields are the `error` event body of `chat-events.schema.json` *and* the
    HTTP error body of `chat-api.md`, and five places produce one: each provider adapter,
    the runner when a turn raises, and the chat server's `ChatError` and close-out path.
    They are the same shape for the page on the other end, so they are built here rather
    than written out five times (constitution V).

    `message` arrives already redacted: masking is the caller's job because only the
    caller knows which secret was in reach (FR-015).
    """
    return {"error_class": error_class, "message": message, "retryable": retryable}


def usage_body(
    usage: TokenUsage,
    *,
    round_index: int,
    provider: ProviderName | str,
    model: str,
    cache_diagnostic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The one shape a model round trip's cost is reported in.

    Three producers emit this event - both adapters and the fake - and a body written out
    three times is three shapes of the same event, so it is built here instead
    (constitution V, the rule `error_body` above already follows). The seven counts and
    `latency_s` come straight off the model, so a count added to `TokenUsage` is carried
    by the event without anyone remembering to add it twice.

    Args:
        usage: What the round cost, already mapped by the adapter that made it.
        round_index: The adapter's **own per-turn counter**, zero-based and reset at each
            turn, exactly the convention `tool.started.step_index` follows and for the
            reason this module's docstring gives: an adapter sees one turn and cannot know
            a session-level number. No turn number is carried either, because turns are
            delimited by the existing `turn.ended` events and the runner therefore never
            has to enrich an adapter's event.
        provider: Which adapter paid for it. On the event and not inferred from the
            session, because the round is the thing that was billed.
        model: The model id this round was billed against.
        cache_diagnostic: OpenAI's prompt-cache outcome for this round, recorded verbatim.
            `None` on Gemini and on the fake always, and `None` on OpenAI whenever
            `prompt_cache_options.comparison_response_id` was not sent - which is every
            round of a lever-3-off run, and the first round of every turn.
    """
    return {
        "round_index": round_index,
        "provider": str(provider),
        "model": model,
        **usage.model_dump(mode="json"),
        "cache_diagnostic": dict(cache_diagnostic) if cache_diagnostic is not None else None,
    }


def usage_from_body(body: Mapping[str, Any]) -> TokenUsage:
    """Read one `usage` event body back into the `TokenUsage` it was built from.

    The inverse of `usage_body`, here rather than in the ledger that calls it so the field
    list lives in exactly one place. The body carries four fields `TokenUsage` does not
    (`round_index`, `provider`, `model`, `cache_diagnostic`) and the model forbids extras,
    so the counts are selected by name; a missing one raises rather than becoming a `None`
    that would read as "the provider did not report it".
    """
    return TokenUsage.model_validate({name: body[name] for name in TokenUsage.model_fields})


class TurnResult(ProviderModel):
    """What one `AgentProvider.run` produced.

    `messages` is the full provider-neutral history after the turn (the input list plus
    what this turn added), so the runner can hand it straight back for the next turn.
    `steps` counts the tool calls made *this* turn, which is what `max_steps` bounds;
    the cumulative count across a resumed session belongs to the runner.
    """

    reason: TurnEndReason
    text: str
    steps: int = Field(ge=0)
    messages: list[dict[str, Any]]


@runtime_checkable
class ProviderTool(Protocol):
    """What an adapter needs from a tool: a name, a schema, and one call that never raises.

    `tools/registry.py`'s `RecordedTool` is the implementation: it binds the tool context,
    validates the arguments, records the step through its sink, and turns every failure
    into a result with `is_error=True`. `call_id` comes from the model's request and is
    carried straight through onto the result so the adapter can pair them up.
    """

    name: str
    description: str
    schema: dict[str, Any]

    def call(self, arguments: Mapping[str, Any], call_id: str) -> ToolCallResult: ...


@runtime_checkable
class ToolSet(Protocol):
    """Every tool one turn may call, and the single dispatch that never raises.

    `tools/registry.py`'s `ToolDispatch` is the implementation. An adapter iterates it to
    encode the tool schemas for its own wire format, and calls `call(name, ...)` for every
    call the model asks for - **including a name nothing is registered under**. That is
    routine model behaviour, and the dispatch turns it into an error result that is
    recorded like any other failed call: an `InvestigationStep` and a `failed` coverage
    item. An adapter that resolved names itself would have to synthesize that result, and
    nothing would ever be written down.
    """

    def __iter__(self) -> Iterator[ProviderTool]: ...

    def __len__(self) -> int: ...

    def call(
        self, name: str, arguments: Mapping[str, Any], call_id: str = ""
    ) -> ToolCallResult: ...


@runtime_checkable
class AgentProvider(Protocol):
    """One model turn, driven by one provider. Adapters are constructed by the CLI/backend."""

    name: ProviderName
    model: str

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        """What `effort` becomes for this model, or a named error when it cannot."""
        ...

    def for_presentation(self, max_output_tokens: int) -> AgentProvider:
        """Return an independent no-cache adapter for a bounded presentation request.

        The returned adapter shares the already-created provider client, model and
        redaction configuration, but has fresh per-turn state. Constructing it must not
        make a network request or require credentials again.
        """
        ...

    def run(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: ToolSet,
        effort: EffortLevel,
        max_steps: int,
        on_event: EventCallback,
    ) -> TurnResult:
        """Run one turn: stream text, drive tool calls, stop on an end or on `max_steps`."""
        ...

    def start_steps_at(self, index: int) -> None:
        """Number this session's tool calls from `index`, the session's own step count.

        Called by `start_review` when setup already wrote steps, which today means feature
        005's lever 5: the pre-run calls tools through the same dispatch the adapter is
        about to be handed, so `session.steps` is already several deep before the model's
        first call. The counter stays the adapter's - it is the one thing an adapter can
        count without knowing a session-level number - but the number it starts from is the
        session's, because `tool.started.step_index` has to keep identifying the
        `InvestigationStep` the call produced: the pane keys its tool cards on it and
        `Finding.tool_result_ids` is joined to those cards. Not called at all on a run whose
        setup wrote nothing, which is every run with lever 5 off.

        Part of the port rather than an optional extension like `PromptCacheAware`: every
        adapter numbers steps, and an adapter that quietly did not would corrupt provenance
        rather than merely forgo a saving.
        """
        ...


@runtime_checkable
class PromptCacheAware(Protocol):
    """An adapter whose provider lets a session name its prompt cache (feature 005).

    An **optional** extension of the port, not part of `AgentProvider`: only OpenAI has a
    cache key to name, and making every adapter carry a no-op would be a method three
    classes implement so that one of them can mean it. `start_review` asks with
    `isinstance` - rather than `hasattr` - so the one thing it calls has a name, a
    signature and a docstring to read.

    The session id is passed in, never invented by the adapter, because **the key must
    survive a process restart**: the pane restarts the backend on a settings save and
    resumes the same run folder, and a process-local value would look identical while
    silently dropping every hit afterwards (contracts/levers.md, lever 3).
    """

    def use_prompt_cache(self, session_id: str) -> None:
        """Name this session's prompt cache. Called once, at `start_review`."""
        ...


@runtime_checkable
class WithdrawableTools(Protocol):
    """A `ToolSet` that can ask for the next round to go out with no tool call allowed.

    An **optional** extension of `ToolSet`, for the same reason `PromptCacheAware` is one
    of `AgentProvider`: only a run with feature 005's lever 7 on has anything to say here,
    and making every `ToolSet` carry a `return False` would be a method three classes
    implement so that one of them can mean it. `agent/runner.py`'s `CoverageStopTools` is
    the implementation.

    An adapter asks between rounds, never between the calls of one round: the answer is
    "the review is finished", and what it buys is the *next* round trip.
    """

    def tools_withdrawn(self) -> bool:
        """May the next round of this turn still call a tool?"""
        ...


def tools_withdrawn(tools: ToolSet) -> bool:
    """Whether `tools` has asked for the next round to carry no tools (lever 7).

    Both adapters ask this once per round and act on it in their own dialect -
    `tool_choice: "none"` on OpenAI, `FunctionCallingConfig(mode=NONE)` on Gemini - so the
    question itself is asked in one place rather than restated per adapter. `False` for
    every `ToolSet` that does not implement `WithdrawableTools`, which is every run with
    the lever off.
    """
    return isinstance(tools, WithdrawableTools) and tools.tools_withdrawn()


SUMMARY_LENGTH = 200
"""A tool result summary is a trace line, not a second copy of the result."""


def summarize_result(payload: Mapping[str, Any]) -> str:
    """The bounded one-line rendering of a tool result carried by `tool.finished`.

    Shared by every adapter (and by `tools/registry.py`, which puts the same string on the
    `InvestigationStep`) so the trace in the pane and the trace in `session.json` read
    alike.
    """
    if "error" in payload:
        text = str(payload["error"])
    else:
        text = json.dumps(payload, separators=(",", ":"), default=str)
    if len(text) <= SUMMARY_LENGTH:
        return text
    return text[: SUMMARY_LENGTH - 1] + "…"


def tool_result_text(payload: Mapping[str, Any]) -> str:
    """What the model reads of one tool result: the one serialization (008 research R2.9).

    The OpenAI adapter encodes every `function_call_output` with it, and feature 008's
    replay and step sizes count tokens over it (`swreview.tokens.count_tokens`), so the
    request and every number priced from it are made from the same bytes. Default
    separators, ASCII-escaped: exactly the `json.dumps` the adapter always sent. A Gemini
    request carries a `function_response` part the SDK serializes itself; its counts use
    this text and are labelled a shape comparison.
    """
    return json.dumps(payload)


FRAMING_TOKENS = 12
"""The tokens a provider bills around each tool result, beyond the result's own text.

Measured, not assumed: recorded round-over-round input growth minus the replayed
`count_tokens(tool_result_text(payload))` of the result that caused it was 11 to 14 tokens,
median 12, over 87 results of three recorded OpenAI runs (008 research R2.5). The replay adds
it once per visible result so its rounds reproduce what the provider billed.
"""


def call_tool(
    *,
    request: ToolCallRequest,
    tools: ToolSet,
    on_event: EventCallback,
    step_index: int,
    clock: Callable[[], float],
) -> ToolCallResult:
    """Run one tool call and emit the `tool.started`/`tool.finished` pair around it.

    Every adapter does exactly this and nothing provider-specific happens in between, so
    the two bodies of `chat-events.schema.json` are built here once instead of in each
    adapter: a field the contract grows is added in one place, and a new adapter gets the
    trace right by calling this rather than by copying the last one (constitution V).

    `tools.call` never raises - a tool that failed and a tool that does not exist both come
    back as a result with `is_error` set - so there is no failure path to write here; the
    `error` the trace carries is the one in the payload.

    `step_index` is the adapter's own per-turn counter and `clock` its own time source,
    because a test that pins `elapsed_s` has to be able to hand one over.
    """
    on_event(
        "tool.started",
        {"step_index": step_index, "tool": request.name, "arguments": request.arguments},
    )
    started = clock()
    result = tools.call(request.name, request.arguments, request.call_id)
    on_event(
        "tool.finished",
        {
            "step_index": step_index,
            "status": "error" if result.is_error else "ok",
            "result_summary": summarize_result(result.payload),
            "elapsed_s": max(clock() - started, 0.0),
            "error": str(result.payload.get("error")) if result.is_error else None,
        },
    )
    return result


class UnknownProviderError(ValueError):
    """Raised for a provider name this product does not have an adapter for."""


ADAPTER_MODULES: dict[ProviderName, str] = {
    ProviderName.OPENAI: "swreview.agent.providers.openai_provider",
    ProviderName.GEMINI: "swreview.agent.providers.gemini_provider",
    ProviderName.FAKE: "swreview.agent.providers.fake",
}
"""Where `get` looks for an adapter that has not registered itself yet.

Importing an adapter module imports its provider SDK, so the import is lazy: a `fake` run
never loads `openai`, and a `gemini` run never loads it either.
"""

_ADAPTERS: dict[ProviderName, type] = {}


def register(name: ProviderName, adapter: type) -> None:
    """Register an adapter class under a provider name (each adapter module calls this)."""
    _ADAPTERS[ProviderName(name)] = adapter


def available() -> tuple[ProviderName, ...]:
    """The provider names already registered, in declaration order."""
    return tuple(name for name in ProviderName if name in _ADAPTERS)


def get(name: str | ProviderName) -> type:
    """The adapter class for `name`, importing its module the first time.

    Raises `UnknownProviderError` for anything that is not `openai`, `gemini` or `fake`.
    The vendor whose SDK feature 002 removed is one such name among all the others and
    gets no branch of its own: naming it here to reject it would be the one string FR-026
    leaves behind under `reviewer/src/`, and the generic message already says which
    providers do work, which is what a caller migrating from it needs to read.
    """
    text = str(name)
    try:
        provider = ProviderName(text)
    except ValueError:
        supported = ", ".join(member.value for member in ProviderName)
        raise UnknownProviderError(
            f"unknown provider {text!r}; supported providers are {supported}"
        ) from None
    if provider not in _ADAPTERS:
        importlib.import_module(ADAPTER_MODULES[provider])
    if provider not in _ADAPTERS:
        raise UnknownProviderError(
            f"{ADAPTER_MODULES[provider]} did not register an adapter for {provider.value!r}"
        )
    return _ADAPTERS[provider]
