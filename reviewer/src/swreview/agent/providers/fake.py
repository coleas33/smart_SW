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
    TokenUsage,
    ToolCallRequest,
    ToolCallResult,
    ToolSet,
    TurnEndReason,
    TurnResult,
    call_tool,
    register,
    usage_body,
)

EFFORT_PARAM = "fake.effort"
"""The fake has no thinking control; it records the requested level unchanged."""

_DELTA = re.compile(r"\S+\s*")
"""Text streams one word (with its trailing space) per `text.delta`."""

SYNTHETIC_USAGE = TokenUsage(
    input_tokens=1_337,
    cached_input_tokens=419,
    cache_write_tokens=None,
    output_tokens=211,
    reasoning_tokens=67,
    tool_result_input_tokens=None,
    total_tokens=1_548,
    latency_s=0.37,
)
"""What one scripted round "costs". One constant, defined here and nowhere else.

The fake pays for no tokens, but the runner, the usage ledger, the report and the
scorecard all need a round that reports some, and a network is not available to any of
them in CI. A constant keeps the fake's one guarantee - nothing is random - so two runs of
one script record identical usage and a downstream test can assert an exact total.

Three properties are deliberate:

- **Nothing is round.** An accidental zero, a dropped field or a total built from the
  wrong two addends shows up against 1,337 and hides against 1,000.
- **The numbers nest the way a real provider's do.** Cached input is inside input,
  reasoning is inside output, and the total is input plus output, so a reader that sums
  the wrong pair of fields is caught by the fixture rather than excused by it.
- **Two counts are `None`.** No provider reports every field - OpenAI has no
  tool-result count and Gemini no cache-write count - so the
  any-null-in-any-round-makes-the-total-null rule is exercised by the default script every
  ledger test already uses, and not only by a test written specially for it.
"""


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
    usage: TokenUsage | None = field(default_factory=lambda: SYNTHETIC_USAGE)
    """What this round "cost", defaulting to the one synthetic constant.

    `None` scripts the case a real provider also produces: a round we made and paid for
    whose cost the service did not report. It records no usage rather than a zero one.
    """


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
        self.round_usage: list[TokenUsage] = []
        """This turn's round trips, one record each. Reset by `run()`.

        A scripted turn is one round: the fake has no round loop, so its calls and its
        closing text are one exchange, and the list has one entry unless the turn was
        scripted with no usage at all.
        """

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
        self.round_usage = [turn.usage] if turn.usage is not None else []
        if turn.usage is not None:
            # Before the scripted calls run, which is where a real adapter emits it: the
            # response for the round is in hand and the tools it asked for have not been
            # dispatched yet.
            on_event(
                "usage",
                usage_body(
                    turn.usage, round_index=0, provider=self.name, model=self.model
                ),
            )

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
        """Run one call and emit its two events, through the port's own shaper.

        The counter is this turn's; everything after it is identical for every adapter and
        lives in `providers.call_tool`.
        """
        step_index = self._step_index
        self._step_index += 1
        return call_tool(
            request=request,
            tools=tools,
            on_event=on_event,
            step_index=step_index,
            clock=self._clock,
        )


register(ProviderName.FAKE, FakeProvider)
