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
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ADAPTER_MODULES",
    "SUMMARY_LENGTH",
    "AgentEvent",
    "AgentProvider",
    "EffortLevel",
    "EffortMapping",
    "EventCallback",
    "EventType",
    "ProviderName",
    "ProviderTool",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolSet",
    "TurnEndReason",
    "TurnResult",
    "UnknownProviderError",
    "available",
    "get",
    "register",
    "summarize_result",
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
