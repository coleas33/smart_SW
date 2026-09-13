"""A scripted `AgentProvider`: no network, no key, one turn per scripted entry.

Every runner, chat-server and pane test drives this adapter, and `--provider fake` is the
pane's development mode, so it behaves like a real adapter in the ways that matter: it
dispatches every call through the `ToolSet` the runner hands it (so validation, recording,
the `failed` coverage and the never-raise rule in `tools/registry.py` are exercised for
real, a name nothing is registered under included), it emits the contract's
events, and it treats `max_steps` as a budget for *this* turn.

It differs from a real adapter in exactly one way, deliberately: nothing is random. Call
ids are `call_1`, `call_2`, ... across the provider's life, text is split into the same
deltas every time, and `clock` is injectable so a test can compare two event streams
field by field.

Shape of a script: one `ScriptedTurn` per `run()`. Within a turn the tool calls run first,
in order, and then the closing text streams. Calling `run()` more often than the script
has turns is a scripting mistake and raises - a silent extra turn would make a runner test
pass for the wrong reason.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from swreview.agent.providers import (
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    ToolCallRequest,
    ToolCallResult,
    ToolSet,
    TurnEndReason,
    TurnResult,
    register,
    summarize_result,
)

EFFORT_PARAM = "fake.effort"
"""The fake has no thinking control; it records the requested level unchanged."""

_DELTA = re.compile(r"\S+\s*")
"""Text streams one word (with its trailing space) per `text.delta`."""


@dataclass(frozen=True)
class ScriptedToolCall:
    """One tool call the scripted model makes, by name and arguments."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScriptedTurn:
    """One `run()`: tool calls in order, then the turn's closing text.

    `end_reason` is how a script reproduces the ends that are not a normal stop -
    `truncated` for a provider that hit its output ceiling, `stopped` for a cancelled
    turn. `max_steps` is not scripted: it is decided by the budget the runner passes in.
    """

    text: str
    tool_calls: tuple[ScriptedToolCall, ...] = ()
    end_reason: TurnEndReason = "end"


class FakeProvider:
    """The scripted provider. `providers.get("fake")` returns this class."""

    name = ProviderName.FAKE

    def __init__(
        self,
        *,
        script: Sequence[ScriptedTurn],
        model: str,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.model = model
        self._script = tuple(script)
        self._clock = clock
        self._turn_index = 0
        self._step_index = 0
        self._call_index = 0

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        """Every level is available: the fake does no thinking to budget."""
        return EffortMapping(requested=effort, provider_param=EFFORT_PARAM, provider_value=effort)

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
        """Play the next scripted turn: tool calls up to `max_steps`, then the text."""
        turn = self._next_turn()
        history = [dict(message) for message in messages]
        steps = 0

        for scripted in turn.tool_calls:
            if steps >= max_steps:
                return TurnResult(reason="max_steps", text="", steps=steps, messages=history)
            request = self._request(scripted)
            result = self._call(request, tools, on_event)
            history.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "call_id": request.call_id,
                            "name": request.name,
                            "arguments": dict(request.arguments),
                        }
                    ],
                }
            )
            history.append(
                {
                    "role": "tool",
                    "call_id": result.call_id,
                    "name": request.name,
                    "content": result.payload,
                    "is_error": result.is_error,
                }
            )
            steps += 1

        if turn.text:
            for delta in _DELTA.findall(turn.text):
                on_event("text.delta", {"text": delta})
            on_event("text.done", {"text": turn.text})
            history.append({"role": "assistant", "content": turn.text})

        return TurnResult(reason=turn.end_reason, text=turn.text, steps=steps, messages=history)

    def _next_turn(self) -> ScriptedTurn:
        if self._turn_index >= len(self._script):
            raise ValueError(
                f"the script has {len(self._script)} turn(s); "
                f"run() was called {self._turn_index + 1} time(s)"
            )
        turn = self._script[self._turn_index]
        self._turn_index += 1
        return turn

    def _request(self, scripted: ScriptedToolCall) -> ToolCallRequest:
        self._call_index += 1
        return ToolCallRequest(
            call_id=f"call_{self._call_index}",
            name=scripted.name,
            arguments=dict(scripted.arguments),
        )

    def _call(
        self,
        request: ToolCallRequest,
        tools: ToolSet,
        on_event: EventCallback,
    ) -> ToolCallResult:
        """Run one call and emit its two events. A missing tool is a result, not a raise."""
        step_index = self._step_index
        self._step_index += 1
        on_event(
            "tool.started",
            {"step_index": step_index, "tool": request.name, "arguments": request.arguments},
        )
        started = self._clock()
        result = tools.call(request.name, request.arguments, request.call_id)
        error = str(result.payload.get("error")) if result.is_error else None
        on_event(
            "tool.finished",
            {
                "step_index": step_index,
                "status": "error" if result.is_error else "ok",
                "result_summary": summarize_result(result.payload),
                "elapsed_s": max(self._clock() - started, 0.0),
                "error": error,
            },
        )
        return result


register(ProviderName.FAKE, FakeProvider)
