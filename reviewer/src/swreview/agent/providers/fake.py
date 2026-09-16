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

    one_round: bool = False
    """Whether `tool_calls` were asked for together, which is feature 005's lever 6.

    It changes the **history shape** and nothing else: the calls still run one after
    another, in the order they are scripted, because that is what the real adapters do and
    what keeps the step log deterministic. Off (the default), the turn records one
    assistant message per call, the serial shape every earlier test was written against.
    On, it records one assistant message carrying every call it dispatched, followed by one
    `tool` message each - the shape a response with several `function_call` items really
    takes.

    A turn the step budget cuts short records the calls it dispatched and no others, on
    both settings. The real adapter's `BUDGET_EXHAUSTED` output exists because a wire
    history with an unanswered call is rejected on the next request; the fake has no wire,
    and inventing an output here would model the adapter's rule rather than exercise it.
    """


def _assistant_message(requests: Sequence[ToolCallRequest]) -> dict[str, Any]:
    """One assistant turn asking for these calls, in the order it asked for them."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "call_id": request.call_id,
                "name": request.name,
                "arguments": dict(request.arguments),
            }
            for request in requests
        ],
    }


def _tool_message(request: ToolCallRequest, result: ToolCallResult) -> dict[str, Any]:
    return {
        "role": "tool",
        "call_id": result.call_id,
        "name": request.name,
        "content": result.payload,
        "is_error": result.is_error,
    }


def _append_round(
    history: list[dict[str, Any]],
    dispatched: Sequence[tuple[ToolCallRequest, ToolCallResult]],
    *,
    one_round: bool,
) -> None:
    """Record what this turn dispatched, grouped the way the script said it was asked for.

    `one_round` is the only difference between the two shapes, and it is a shape only: the
    calls have already run, serially and in order, by the time this is called.
    """
    if not dispatched:
        return
    if one_round:
        history.append(_assistant_message([request for request, _ in dispatched]))
        history.extend(_tool_message(request, result) for request, result in dispatched)
        return
    for request, result in dispatched:
        history.append(_assistant_message([request]))
        history.append(_tool_message(request, result))


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

        dispatched: list[tuple[ToolCallRequest, ToolCallResult]] = []
        for scripted in turn.tool_calls:
            if steps >= max_steps:
                _append_round(history, dispatched, one_round=turn.one_round)
                return TurnResult(reason="max_steps", text="", steps=steps, messages=history)
            request = self._request(scripted)
            result = self._call(request, tools, on_event)
            dispatched.append((request, result))
            steps += 1
        _append_round(history, dispatched, one_round=turn.one_round)

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

    def start_steps_at(self, index: int) -> None:
        """`AgentProvider`: the session already holds `index` steps, so number from there.

        Called by `start_review` only when setup wrote steps, which today means lever 5's
        pre-run; the port's docstring says why the number is the session's and the counter
        the adapter's.
        """
        self._step_index = index

    def _call(
        self,
        request: ToolCallRequest,
        tools: ToolSet,
        on_event: EventCallback,
    ) -> ToolCallResult:
        """Run one call and emit its two events, through the port's own shaper.

        The counter runs for the whole session and is never reset per turn, because
        `step_index` names an `InvestigationStep` and the session keeps accumulating them;
        everything after it is identical for every adapter and lives in
        `providers.call_tool`.
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
