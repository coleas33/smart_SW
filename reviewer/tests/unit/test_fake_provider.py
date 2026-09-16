"""Unit tests for the scripted fake provider (T010).

The fake is what every runner, server and pane test drives, so its own guarantees have to
be exact: the events it emits are the contract's events, the tool calls go through the
`ProviderTool` interface (the same one `RecordedTool` implements, so a fake run exercises
validation, recording and the never-raise rule), `max_steps` is a per-turn budget, and two
runs of one script produce byte-identical event streams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from swreview.agent import providers
from swreview.agent.providers import (
    AgentEvent,
    AgentProvider,
    EventType,
    ProviderName,
    ToolCallResult,
)
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from tests.support.contracts import contract_validator
from tests.support.toolsets import toolset

AT = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)
FROZEN_CLOCK = 3.5
"""A clock that never advances: `elapsed_s` is then 0.0 and the stream is comparable."""


def frozen_clock() -> float:
    return FROZEN_CLOCK


@dataclass
class FakeTool:
    """A `ProviderTool` that records its calls; stands in for `RecordedTool`."""

    name: str
    description: str = "a tool"
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    payload: dict[str, Any] = field(default_factory=lambda: {"ok": True})
    is_error: bool = False
    calls: list[tuple[dict[str, Any], str]] = field(default_factory=list)

    def call(self, arguments: Any, call_id: str) -> ToolCallResult:
        self.calls.append((dict(arguments), call_id))
        return ToolCallResult(call_id=call_id, payload=self.payload, is_error=self.is_error)


@dataclass
class Sink:
    """The runner's side of `on_event`: stamps `seq` and `at` the way the sink will."""

    events: list[AgentEvent] = field(default_factory=list)

    def __call__(self, event_type: EventType, body: Any) -> None:
        self.events.append(
            AgentEvent(seq=len(self.events) + 1, at=AT, type=event_type, body=dict(body))
        )

    @property
    def types(self) -> list[str]:
        return [event.type for event in self.events]

    def bodies(self, event_type: str) -> list[dict[str, Any]]:
        return [event.body for event in self.events if event.type == event_type]

    def serialized(self) -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in self.events]


def provider(*turns: ScriptedTurn, model: str = "fake-scripted") -> FakeProvider:
    return FakeProvider(script=turns, model=model, clock=frozen_clock)


def run(
    fake: FakeProvider,
    tools: list[FakeTool],
    *,
    sink: Sink | None = None,
    messages: list[dict[str, Any]] | None = None,
    max_steps: int = 10,
) -> tuple[Any, Sink]:
    sink = sink or Sink()
    result = fake.run(
        system="you are a reviewer",
        messages=messages if messages is not None else [{"role": "user", "content": "review it"}],
        tools=toolset(tools),
        effort="high",
        max_steps=max_steps,
        on_event=sink,
    )
    return result, sink


def test_fake_is_registered_under_its_provider_name() -> None:
    assert providers.get("fake") is FakeProvider
    assert ProviderName.FAKE in providers.available()


def test_fake_satisfies_the_provider_protocol() -> None:
    fake = provider(ScriptedTurn(text="done"))
    assert isinstance(fake, AgentProvider)
    assert fake.name is ProviderName.FAKE
    assert fake.model == "fake-scripted"


def test_effort_mapping_is_recorded_for_every_level() -> None:
    fake = provider(ScriptedTurn(text="done"))
    mapping = fake.effort_mapping("xhigh")
    assert mapping.requested == "xhigh"
    assert mapping.provider_value == "xhigh"
    assert mapping.provider_param


def test_text_only_turn_streams_deltas_then_one_done() -> None:
    fake = provider(ScriptedTurn(text="Checking the joints now"))
    result, sink = run(fake, [])
    assert sink.types == ["usage"] + ["text.delta"] * 4 + ["text.done"]
    assert "".join(body["text"] for body in sink.bodies("text.delta")) == "Checking the joints now"
    assert sink.bodies("text.done") == [{"text": "Checking the joints now"}]
    assert result.text == "Checking the joints now"
    assert result.reason == "end"
    assert result.steps == 0


def test_a_turn_with_no_text_emits_no_text_events() -> None:
    tool = FakeTool(name="list_components")
    fake = provider(ScriptedTurn(text="", tool_calls=(ScriptedToolCall("list_components", {}),)))
    _, sink = run(fake, [tool])
    assert sink.types == ["usage", "tool.started", "tool.finished"]


def test_scripted_tool_calls_run_through_the_tool_interface() -> None:
    tool = FakeTool(name="list_components", payload={"components": ["cmp:0001"]})
    fake = provider(
        ScriptedTurn(
            text="two components",
            tool_calls=(ScriptedToolCall("list_components", {"configuration": "Default"}),),
        )
    )
    result, sink = run(fake, [tool])

    assert tool.calls[0][0] == {"configuration": "Default"}
    call_id = tool.calls[0][1]
    assert call_id
    assert sink.types[:3] == ["usage", "tool.started", "tool.finished"]
    assert sink.bodies("tool.started") == [
        {"step_index": 0, "tool": "list_components", "arguments": {"configuration": "Default"}}
    ]
    finished = sink.bodies("tool.finished")[0]
    assert finished["step_index"] == 0
    assert finished["status"] == "ok"
    assert finished["error"] is None
    assert finished["elapsed_s"] == 0.0
    assert finished["result_summary"] == '{"components":["cmp:0001"]}'
    assert result.steps == 1


def test_a_failed_tool_result_is_reported_not_raised() -> None:
    tool = FakeTool(name="check_fit", payload={"error": "unknown component id 'cmp:9999'"},
                    is_error=True)
    fake = provider(
        ScriptedTurn(text="", tool_calls=(ScriptedToolCall("check_fit", {"a": "cmp:9999"}),))
    )
    result, sink = run(fake, [tool])
    finished = sink.bodies("tool.finished")[0]
    assert finished["status"] == "error"
    assert finished["error"] == "unknown component id 'cmp:9999'"
    assert finished["result_summary"] == "unknown component id 'cmp:9999'"
    assert result.reason == "end"


def test_a_call_naming_an_unknown_tool_is_an_error_result_not_an_exception() -> None:
    """A hallucinated tool name is routine model behaviour, not a crash."""
    fake = provider(
        ScriptedTurn(text="", tool_calls=(ScriptedToolCall("measure_everything", {}),))
    )
    result, sink = run(fake, [FakeTool(name="list_components")])
    finished = sink.bodies("tool.finished")[0]
    assert finished["status"] == "error"
    assert "measure_everything" in finished["error"]
    assert result.steps == 1
    tool_messages = [message for message in result.messages if message["role"] == "tool"]
    assert tool_messages[-1]["is_error"] is True


def test_step_index_keeps_counting_across_turns() -> None:
    tool = FakeTool(name="list_components")
    fake = provider(
        ScriptedTurn(text="", tool_calls=(ScriptedToolCall("list_components", {}),)),
        ScriptedTurn(text="", tool_calls=(ScriptedToolCall("list_components", {}),)),
    )
    _, first = run(fake, [tool])
    _, second = run(fake, [tool])
    assert first.bodies("tool.started")[0]["step_index"] == 0
    assert second.bodies("tool.started")[0]["step_index"] == 1


def test_max_steps_is_a_per_turn_budget() -> None:
    tool = FakeTool(name="list_components")
    calls = tuple(ScriptedToolCall("list_components", {"n": index}) for index in range(3))
    fake = provider(
        ScriptedTurn(text="never reached", tool_calls=calls),
        ScriptedTurn(text="second turn runs anyway", tool_calls=calls[:1]),
    )

    result, sink = run(fake, [tool], max_steps=2)
    assert result.reason == "max_steps"
    assert result.steps == 2
    assert len(tool.calls) == 2
    assert sink.types.count("tool.started") == 2
    assert "text.done" not in sink.types

    resumed, _ = run(fake, [tool], max_steps=2)
    assert resumed.reason == "end"
    assert resumed.steps == 1
    assert resumed.text == "second turn runs anyway"


def test_max_steps_of_zero_runs_no_tool() -> None:
    tool = FakeTool(name="list_components")
    fake = provider(
        ScriptedTurn(text="x", tool_calls=(ScriptedToolCall("list_components", {}),))
    )
    result, sink = run(fake, [tool], max_steps=0)
    assert result.reason == "max_steps"
    assert result.steps == 0
    assert tool.calls == []
    # The round was still played and still "cost" its scripted usage; what the budget
    # stopped is the tool call, not the round trip that asked for it.
    assert sink.types == ["usage"]


def test_messages_extend_the_history_the_runner_passed_in() -> None:
    tool = FakeTool(name="list_components", payload={"components": []})
    history = [{"role": "user", "content": "review it"}]
    fake = provider(
        ScriptedTurn(text="all clear", tool_calls=(ScriptedToolCall("list_components", {}),))
    )
    result, _ = run(fake, [tool], messages=history)

    assert history == [{"role": "user", "content": "review it"}], "input history is not mutated"
    assert result.messages[0] == history[0]
    assert result.messages[1]["role"] == "assistant"
    assert result.messages[1]["tool_calls"] == [
        {"call_id": tool.calls[0][1], "name": "list_components", "arguments": {}}
    ]
    assert result.messages[2] == {
        "role": "tool",
        "call_id": tool.calls[0][1],
        "name": "list_components",
        "content": {"components": []},
        "is_error": False,
    }
    assert result.messages[3] == {"role": "assistant", "content": "all clear"}


def test_a_turn_can_be_scripted_to_end_truncated() -> None:
    """The provider's output ceiling: neither an exception nor a tool error (T014 case e)."""
    fake = provider(ScriptedTurn(text="half a sen", end_reason="truncated"))
    result, sink = run(fake, [])
    assert result.reason == "truncated"
    assert sink.bodies("text.done") == [{"text": "half a sen"}]


def test_running_past_the_end_of_the_script_is_a_scripting_error() -> None:
    fake = provider(ScriptedTurn(text="only turn"))
    run(fake, [])
    with pytest.raises(ValueError, match="script"):
        run(fake, [])


def test_two_runs_of_one_script_are_identical() -> None:
    def once() -> list[dict[str, Any]]:
        tool = FakeTool(name="list_components", payload={"components": ["cmp:0001"]})
        fake = provider(
            ScriptedTurn(
                text="one component",
                tool_calls=(ScriptedToolCall("list_components", {"configuration": "Default"}),),
            )
        )
        _, sink = run(fake, [tool])
        return sink.serialized()

    assert once() == once()


def test_every_emitted_event_validates_against_the_contract() -> None:
    validator = contract_validator("chat-events.schema.json")
    tools = [
        FakeTool(name="list_components", payload={"components": []}),
        FakeTool(name="check_fit", payload={"error": "no such id"}, is_error=True),
    ]
    fake = provider(
        ScriptedTurn(
            text="one finding",
            tool_calls=(
                ScriptedToolCall("list_components", {}),
                ScriptedToolCall("check_fit", {"a": "cmp:9999"}),
                ScriptedToolCall("gone_missing", {}),
            ),
        )
    )
    _, sink = run(fake, tools)
    assert set(sink.types) == {"usage", "tool.started", "tool.finished", "text.delta", "text.done"}
    for event in sink.serialized():
        validator.validate(event)
