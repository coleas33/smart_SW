"""Unit tests for the OpenAI Responses adapter (T017).

Every exchange here is replayed through `respx`, so the adapter is exercised against the
real `openai` client - its request serialization, its SSE decoder, its exception classes -
without a key or a network call. What the tests pin is exactly the surface the adapter
owns: the request it builds, the history it keeps, the events it emits, how it ends a
turn, and what it does with a failure.

Two mechanical notes, both deliberate:

`openai` 3.x ships on `httpx2` while `respx` patches the legacy `httpx`. The client the
SDK builds for itself is therefore *not* interceptable; the client these tests inject is
built on legacy `httpx`, which `openai` explicitly supports (`openai/_httpx2.py`). That is
the one difference between a recorded turn and a live one, and T018a's key-gated test is
what covers the rest.

`max_retries=0` on the injected client keeps the call count on each `respx` route equal to
the number of turns the adapter actually took: the SDK would otherwise retry a 429 or a
connection error twice on its own and the assertions would be about the SDK, not us.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from openai import OpenAI

from swreview.agent.providers import (
    AgentEvent,
    AgentProvider,
    EventType,
    ProviderName,
    ToolCallResult,
)
from swreview.agent.providers.openai_provider import (
    EFFORT_PARAM,
    EffortNotSupportedError,
    OpenAIProvider,
    OpenAIProviderError,
)
from swreview.agent.settings import MASK, output_ceiling
from tests.support.contracts import contract_validator
from tests.support.toolsets import toolset

RESPONSES_URL = "https://api.openai.com/v1/responses"
KEY = "sk-test-0123456789abcdef"
MODEL = "gpt-5.6"
CEILING = 24000
"""A ceiling deliberately unlike the settings default, so a passed value proves itself."""

AT = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


# --- the stand-ins the adapter talks to -----------------------------------------------


@dataclass
class FakeTool:
    """A `ProviderTool`: `tools/registry.py`'s `RecordedTool` is the real implementation."""

    name: str
    description: str = "a tool"
    schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"component_id": {"type": "string", "description": "the component"}},
            "required": ["component_id"],
        }
    )
    payload: dict[str, Any] = field(default_factory=lambda: {"mass_kg": 1.25})
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

    def one(self, event_type: str) -> dict[str, Any]:
        bodies = self.bodies(event_type)
        assert len(bodies) == 1, f"expected one {event_type}, got {len(bodies)}"
        return bodies[0]


# --- the recorded wire format ---------------------------------------------------------


def sse(*events: dict[str, Any]) -> str:
    """The SSE body the Responses API streams, in the shape `openai`'s decoder reads."""
    lines = []
    for event in events:
        lines.append("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n")
    return "".join(lines)


def stream_response(*events: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse(*events))


def text_delta(text: str, *, seq: int = 1) -> dict[str, Any]:
    return {
        "type": "response.output_text.delta",
        "delta": text,
        "item_id": "msg_1",
        "output_index": 0,
        "content_index": 0,
        "logprobs": [],
        "sequence_number": seq,
    }


def message_item(text: str, *, item_id: str = "msg_1") -> dict[str, Any]:
    return {
        "type": "message",
        "id": item_id,
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def reasoning_item(*, item_id: str = "rs_1") -> dict[str, Any]:
    return {"type": "reasoning", "id": item_id, "summary": [], "status": "completed"}


def function_call_item(
    *,
    call_id: str = "call_1",
    name: str = "get_component",
    arguments: str = '{"component_id":"C1"}',
) -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": "fc_1",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
        "status": "completed",
    }


def item_done(item: dict[str, Any], *, index: int = 0, seq: int = 2) -> dict[str, Any]:
    return {
        "type": "response.output_item.done",
        "item": item,
        "output_index": index,
        "sequence_number": seq,
    }


def response_payload(
    output: list[dict[str, Any]],
    *,
    status: str = "completed",
    incomplete_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": MODEL,
        "status": status,
        "output": output,
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "incomplete_details": incomplete_details,
    }


def completed(*output: dict[str, Any], seq: int = 9) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "sequence_number": seq,
        "response": response_payload(list(output)),
    }


def incomplete(
    *output: dict[str, Any], reason: str = "max_output_tokens", seq: int = 9
) -> dict[str, Any]:
    return {
        "type": "response.incomplete",
        "sequence_number": seq,
        "response": response_payload(
            list(output), status="incomplete", incomplete_details={"reason": reason}
        ),
    }


# --- construction helpers -------------------------------------------------------------


def make_client() -> OpenAI:
    """An `OpenAI` client `respx` can intercept, with the SDK's own retries turned off."""
    return OpenAI(api_key=KEY, http_client=httpx.Client(), max_retries=0)


def make_provider(*, model: str = MODEL, client: OpenAI | None = None) -> OpenAIProvider:
    return OpenAIProvider(
        model=model,
        max_output_tokens=CEILING,
        client=client if client is not None else make_client(),
    )


def run(
    provider: OpenAIProvider,
    *,
    tools: list[FakeTool] | None = None,
    messages: list[dict[str, Any]] | None = None,
    effort: Any = "high",
    max_steps: int = 10,
    sink: Sink | None = None,
) -> tuple[Any, Sink]:
    sink = sink or Sink()
    result = provider.run(
        system="you are a design reviewer",
        messages=messages if messages is not None else [{"role": "user", "content": "review it"}],
        tools=toolset(tools or []),
        effort=effort,
        max_steps=max_steps,
        on_event=sink,
    )
    return result, sink


def request_bodies(route: respx.Route) -> list[dict[str, Any]]:
    return [json.loads(call.request.content) for call in route.calls]


# --- registration and effort ----------------------------------------------------------


def test_the_adapter_is_registered_under_its_provider_name() -> None:
    from swreview.agent import providers

    assert providers.get("openai") is OpenAIProvider
    assert OpenAIProvider.name is ProviderName.OPENAI


def test_the_adapter_satisfies_the_provider_protocol() -> None:
    assert isinstance(make_provider(), AgentProvider)


def test_every_registered_tool_builds_a_flat_strict_function_param() -> None:
    """The shape T018a then posts for real; here it is proved for every tool we ship."""
    from swreview.agent.providers.openai_provider import tool_param
    from swreview.agent.providers.schema import tool_spec
    from swreview.tools.registry import BRIDGE_TOOL_FUNCTIONS, TOOL_FUNCTIONS

    params = [tool_param(tool_spec(fn)) for fn in (*TOOL_FUNCTIONS, *BRIDGE_TOOL_FUNCTIONS)]

    assert params
    for param in params:
        assert set(param) == {"type", "name", "description", "strict", "parameters"}
        assert param["type"] == "function"
        assert param["strict"] is True
        assert param["description"]
        assert param["parameters"]["type"] == "object"
        assert param["parameters"]["additionalProperties"] is False
        assert sorted(param["parameters"]["required"]) == sorted(param["parameters"]["properties"])


def test_effort_mapping_is_recorded_with_the_parameter_it_maps_to() -> None:
    mapping = make_provider().effort_mapping("high")

    assert mapping.requested == "high"
    assert mapping.provider_param == EFFORT_PARAM == "reasoning.effort"
    assert mapping.provider_value == "high"


def test_an_effort_the_model_does_not_offer_fails_fast_with_a_named_error() -> None:
    provider = make_provider(model="gpt-5-mini")

    with pytest.raises(EffortNotSupportedError) as caught:
        provider.effort_mapping("xhigh")

    message = str(caught.value)
    assert "xhigh" in message
    assert "gpt-5-mini" in message


@respx.mock
def test_an_unsupported_effort_is_refused_before_any_request_is_sent() -> None:
    """Fail fast, never a silent downgrade: the run must not reach the API at all."""
    route = respx.post(RESPONSES_URL).mock(return_value=stream_response(completed()))

    with pytest.raises(EffortNotSupportedError):
        run(make_provider(model="gpt-5-mini"), effort="xhigh")

    assert route.call_count == 0


def test_a_model_outside_the_table_passes_the_requested_effort_through() -> None:
    """An unknown model id is not a reason to downgrade; the API is the backstop."""
    mapping = make_provider(model="gpt-6-experimental").effort_mapping("xhigh")

    assert mapping.provider_value == "xhigh"


@respx.mock
def test_presentation_clone_isolated_state_reuses_client_and_bounds_output() -> None:
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(text_delta("{}"), completed(message_item("{}")))
    )
    primary = make_provider()
    primary.use_prompt_cache("review-session")
    primary._step_index = 7
    primary._last_response_id = "resp_review"

    presentation = primary.for_presentation(2048)

    assert presentation is not primary
    assert presentation._client is primary._client
    assert presentation.max_output_tokens == 2048
    assert presentation.parallel_tool_calls is False
    assert presentation.prompt_cache_key is None
    assert primary._step_index == 7
    assert primary._last_response_id == "resp_review"
    assert primary.prompt_cache_key == "review-session"

    result, _ = run(presentation, max_steps=0)
    assert result.reason == "end"
    body = request_bodies(route)[0]
    assert body["max_output_tokens"] == 2048
    assert "tools" not in body


# --- request shape --------------------------------------------------------------------


@respx.mock
def test_the_request_carries_the_prompt_effort_ceiling_and_flat_strict_tools() -> None:
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(text_delta("done"), completed(message_item("done")))
    )
    tool = FakeTool(name="get_component", description="Read one component.")

    run(make_provider(), tools=[tool])

    body = request_bodies(route)[0]
    assert body["model"] == MODEL
    assert body["instructions"] == "you are a design reviewer"
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == CEILING
    assert body["parallel_tool_calls"] is False
    assert body["stream"] is True
    assert body["tools"] == [
        {
            "type": "function",
            "name": "get_component",
            "description": "Read one component.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"component_id": {"type": "string", "description": "the component"}},
                "required": ["component_id"],
                "additionalProperties": False,
            },
        }
    ]


@respx.mock
def test_the_ceiling_is_the_one_the_caller_passed_not_the_inherited_sixteen_thousand() -> None:
    route = respx.post(RESPONSES_URL).mock(return_value=stream_response(completed()))

    run(OpenAIProvider(model=MODEL, max_output_tokens=64000, client=make_client()))

    assert request_bodies(route)[0]["max_output_tokens"] == 64000


@respx.mock
def test_the_ceiling_defaults_to_the_one_settings_owns_for_this_provider_and_model() -> None:
    """No ceiling of its own: `agent/settings.py` is the single authority (T018)."""
    route = respx.post(RESPONSES_URL).mock(return_value=stream_response(completed()))
    expected = output_ceiling("openai", MODEL)

    run(OpenAIProvider(model=MODEL, client=make_client()))

    assert expected != 16000  # the retired non-streaming number must not creep back in
    assert request_bodies(route)[0]["max_output_tokens"] == expected


@respx.mock
def test_the_history_the_runner_owns_is_encoded_as_the_full_input_list() -> None:
    route = respx.post(RESPONSES_URL).mock(return_value=stream_response(completed()))
    messages = [
        {"role": "user", "content": "review it"},
        {"role": "assistant", "content": "looking"},
        {"role": "user", "content": "and the fasteners"},
    ]

    run(make_provider(), messages=messages)

    assert request_bodies(route)[0]["input"] == [
        {"role": "user", "content": "review it"},
        {"role": "assistant", "content": "looking"},
        {"role": "user", "content": "and the fasteners"},
    ]


# --- the tool-call round trip ---------------------------------------------------------


@respx.mock
def test_a_function_call_is_validated_called_and_answered_with_function_call_output() -> None:
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(reasoning_item(), index=0),
                item_done(function_call_item(), index=1),
                completed(reasoning_item(), function_call_item()),
            ),
            stream_response(text_delta("C1 is 1.25 kg"), completed(message_item("C1 is 1.25 kg"))),
        ]
    )
    tool = FakeTool(name="get_component")

    result, _ = run(make_provider(), tools=[tool])

    assert tool.calls == [({"component_id": "C1"}, "call_1")]
    assert result.reason == "end"
    assert result.steps == 1
    assert result.text == "C1 is 1.25 kg"

    second = request_bodies(route)[1]["input"]
    assert second[0] == {"role": "user", "content": "review it"}
    assert second[1]["type"] == "reasoning"
    assert second[2]["type"] == "function_call"
    assert second[2]["call_id"] == "call_1"
    assert second[3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": json.dumps({"mass_kg": 1.25}),
    }


@respx.mock
def test_the_echoed_output_survives_a_second_turn_through_the_neutral_history() -> None:
    """Reasoning items must come back verbatim, so they ride the history under our key."""
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(reasoning_item(), index=0),
                item_done(function_call_item(), index=1),
                completed(reasoning_item(), function_call_item()),
            ),
            stream_response(completed(message_item("ok"))),
            stream_response(completed(message_item("again ok"))),
        ]
    )
    provider = make_provider()
    result, _ = run(provider, tools=[FakeTool(name="get_component")])

    echoed = [message for message in result.messages if message.get("role") == "assistant"]
    raw = [item for message in echoed for item in message.get("openai", {}).get("output", [])]
    assert [item["type"] for item in raw] == ["reasoning", "function_call", "message"]

    run(
        provider,
        tools=[FakeTool(name="get_component")],
        messages=[*result.messages, {"role": "user", "content": "again"}],
    )

    replayed = request_bodies(route)[-1]["input"]
    assert [item.get("type") for item in replayed[1:4]] == [
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert replayed[-1] == {"role": "user", "content": "again"}


@respx.mock
def test_a_tool_error_is_reported_as_a_result_not_raised() -> None:
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(function_call_item(), index=0),
                completed(function_call_item()),
            ),
            stream_response(completed(message_item("noted"))),
        ]
    )
    tool = FakeTool(name="get_component", payload={"error": "no such component"}, is_error=True)

    result, sink = run(make_provider(), tools=[tool])

    assert result.reason == "end"
    assert sink.one("tool.finished")["status"] == "error"
    assert sink.one("tool.finished")["error"] == "no such component"
    assert json.loads(request_bodies(route)[1]["input"][2]["output"]) == {
        "error": "no such component"
    }


@respx.mock
def test_a_call_naming_an_unregistered_tool_is_an_error_result_not_an_exception() -> None:
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(function_call_item(name="no_such_tool"), index=0),
                completed(function_call_item(name="no_such_tool")),
            ),
            stream_response(completed(message_item("sorry"))),
        ]
    )

    result, sink = run(make_provider(), tools=[FakeTool(name="get_component")])

    assert result.reason == "end"
    assert sink.one("tool.finished")["status"] == "error"
    assert "no_such_tool" in sink.one("tool.finished")["error"]
    assert "error" in json.loads(request_bodies(route)[1]["input"][2]["output"])


@respx.mock
def test_max_steps_is_a_per_turn_budget() -> None:
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(function_call_item(call_id="call_1"), index=0),
                completed(function_call_item(call_id="call_1")),
            ),
            stream_response(
                item_done(function_call_item(call_id="call_2"), index=0),
                completed(function_call_item(call_id="call_2")),
            ),
        ]
    )
    tool = FakeTool(name="get_component")

    result, _ = run(make_provider(), tools=[tool], max_steps=1)

    assert result.reason == "max_steps"
    assert result.steps == 1
    assert len(tool.calls) == 1
    assert route.call_count == 1


@respx.mock
def test_a_call_the_budget_would_not_pay_for_still_gets_an_output_in_the_history() -> None:
    """Every `function_call` needs a `function_call_output` or the next request is a 400."""
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(
            completed(
                function_call_item(call_id="call_1"),
                function_call_item(call_id="call_2"),
            )
        )
    )
    tool = FakeTool(name="get_component")

    result, sink = run(make_provider(), tools=[tool], max_steps=1)

    assert result.reason == "max_steps"
    assert result.steps == 1
    assert len(tool.calls) == 1
    answered = [message for message in result.messages if message.get("role") == "tool"]
    assert [message["call_id"] for message in answered] == ["call_1", "call_2"]
    assert answered[1]["is_error"] is True
    assert len(sink.bodies("tool.started")) == 1


# --- streaming to events --------------------------------------------------------------


@respx.mock
def test_text_streams_as_deltas_then_one_done_with_the_whole_turn() -> None:
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(
            text_delta("The bracket "),
            text_delta("interferes."),
            completed(message_item("The bracket interferes.")),
        )
    )

    result, sink = run(make_provider())

    assert [body["text"] for body in sink.bodies("text.delta")] == [
        "The bracket ",
        "interferes.",
    ]
    assert sink.one("text.done")["text"] == "The bracket interferes."
    assert result.text == "The bracket interferes."


@respx.mock
def test_a_turn_with_no_text_emits_no_text_events() -> None:
    respx.post(RESPONSES_URL).mock(return_value=stream_response(completed()))

    _, sink = run(make_provider())

    # The round trip itself is always reported: it happened, and what it cost is a
    # separate question from whether the model said anything.
    assert sink.types == ["usage"]


@respx.mock
def test_a_tool_call_emits_started_then_finished_with_a_bounded_summary() -> None:
    respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(function_call_item(), index=0), completed(function_call_item())
            ),
            stream_response(completed(message_item("ok"))),
        ]
    )

    _, sink = run(make_provider(), tools=[FakeTool(name="get_component")])

    assert sink.types[:3] == ["usage", "tool.started", "tool.finished"]
    started = sink.one("tool.started")
    assert started == {
        "step_index": 0,
        "tool": "get_component",
        "arguments": {"component_id": "C1"},
    }
    finished = sink.one("tool.finished")
    assert finished["step_index"] == 0
    assert finished["status"] == "ok"
    assert finished["result_summary"] == '{"mass_kg":1.25}'
    assert finished["error"] is None
    assert finished["elapsed_s"] >= 0.0


@respx.mock
def test_step_index_keeps_counting_across_turns() -> None:
    respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(function_call_item(call_id="call_1"), index=0),
                completed(function_call_item(call_id="call_1")),
            ),
            stream_response(completed(message_item("one"))),
            stream_response(
                item_done(function_call_item(call_id="call_2"), index=0),
                completed(function_call_item(call_id="call_2")),
            ),
            stream_response(completed(message_item("two"))),
        ]
    )
    provider = make_provider()
    tool = FakeTool(name="get_component")

    _, first = run(provider, tools=[tool])
    _, second = run(provider, tools=[tool])

    assert first.one("tool.started")["step_index"] == 0
    assert second.one("tool.started")["step_index"] == 1


@respx.mock
def test_every_emitted_event_validates_against_the_contract() -> None:
    respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                item_done(function_call_item(), index=0), completed(function_call_item())
            ),
            stream_response(text_delta("ok"), completed(message_item("ok"))),
        ]
    )
    validator = contract_validator("chat-events.schema.json")

    _, sink = run(make_provider(), tools=[FakeTool(name="get_component")])

    assert sink.types  # a test that validates nothing proves nothing
    for event in sink.events:
        validator.validate(event.model_dump(mode="json"))


# --- truncation -----------------------------------------------------------------------


@respx.mock
def test_an_incomplete_response_on_the_output_ceiling_ends_the_turn_truncated() -> None:
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(
            text_delta("The bracket "),
            incomplete(message_item("The bracket ")),
        )
    )

    result, sink = run(make_provider())

    assert result.reason == "truncated"
    assert result.text == "The bracket "
    assert sink.bodies("error") == []


@respx.mock
def test_a_ceiling_reached_mid_tool_call_ends_the_turn_without_dispatching_it() -> None:
    """The response is already known to be cut short; running its calls would spend more."""
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(incomplete(function_call_item()))
    )
    tool = FakeTool(name="get_component")

    result, sink = run(make_provider(), tools=[tool])

    assert result.reason == "truncated"
    assert result.steps == 0
    assert tool.calls == []
    assert route.call_count == 1
    answered = [message for message in result.messages if message.get("role") == "tool"]
    assert [message["call_id"] for message in answered] == ["call_1"]
    assert answered[0]["is_error"] is True
    assert sink.bodies("error") == []


@respx.mock
def test_an_incomplete_response_for_another_reason_is_not_reported_as_truncated() -> None:
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(incomplete(reason="content_filter"))
    )

    sink = Sink()
    with pytest.raises(OpenAIProviderError) as caught:
        run(make_provider(), sink=sink)

    assert "content_filter" in str(caught.value)
    assert caught.value.error_class == "IncompleteResponseError"
    assert caught.value.retryable is False
    assert sink.one("error")["error_class"] == "IncompleteResponseError"


@respx.mock
def test_function_call_arguments_that_will_not_parse_end_the_turn_truncated() -> None:
    """A cut-off argument stream is a ceiling, not a tool error and not a normal end."""
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(
            item_done(function_call_item(arguments='{"component_id":"C'), index=0),
            completed(function_call_item(arguments='{"component_id":"C')),
        )
    )
    tool = FakeTool(name="get_component")

    result, sink = run(make_provider(), tools=[tool])

    assert result.reason == "truncated"
    assert result.steps == 0
    assert tool.calls == []
    assert sink.bodies("tool.started") == []
    answered = [message for message in result.messages if message.get("role") == "tool"]
    assert [message["call_id"] for message in answered] == ["call_1"]
    assert answered[0]["is_error"] is True


@respx.mock
def test_function_call_arguments_that_are_not_an_object_end_the_turn_truncated() -> None:
    """Strict mode cannot produce this from a complete response, so treat it as a cut-off."""
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed(function_call_item(arguments='["C1"]')))
    )
    tool = FakeTool(name="get_component")

    result, _ = run(make_provider(), tools=[tool])

    assert result.reason == "truncated"
    assert tool.calls == []


# --- error mapping and redaction ------------------------------------------------------


@respx.mock
def test_an_authentication_failure_maps_to_a_named_non_retryable_error() -> None:
    respx.post(RESPONSES_URL).mock(
        return_value=httpx.Response(
            401,
            json={"error": {"message": "Incorrect API key provided.", "code": "invalid_api_key"}},
        )
    )

    sink = Sink()
    with pytest.raises(OpenAIProviderError) as caught:
        run(make_provider(), sink=sink)

    assert caught.value.error_class == "AuthenticationError"
    assert caught.value.retryable is False
    assert sink.one("error") == {
        "error_class": "AuthenticationError",
        "message": caught.value.message,
        "retryable": False,
    }


@respx.mock
def test_a_rate_limit_maps_to_a_retryable_error() -> None:
    respx.post(RESPONSES_URL).mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )

    with pytest.raises(OpenAIProviderError) as caught:
        run(make_provider())

    assert caught.value.error_class == "RateLimitError"
    assert caught.value.retryable is True


@respx.mock
def test_a_connection_failure_maps_to_a_retryable_error() -> None:
    respx.post(RESPONSES_URL).mock(side_effect=httpx.ConnectError("name resolution failed"))

    with pytest.raises(OpenAIProviderError) as caught:
        run(make_provider())

    assert caught.value.error_class == "APIConnectionError"
    assert caught.value.retryable is True


@respx.mock
def test_a_server_error_is_retryable_and_a_bad_request_is_not() -> None:
    respx.post(RESPONSES_URL).mock(
        return_value=httpx.Response(503, json={"error": {"message": "overloaded"}})
    )
    with pytest.raises(OpenAIProviderError) as server:
        run(make_provider())

    respx.post(RESPONSES_URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "invalid schema for function 'get_component'"}}
        )
    )
    with pytest.raises(OpenAIProviderError) as client:
        run(make_provider())

    assert server.value.error_class == "InternalServerError"
    assert server.value.retryable is True
    assert client.value.error_class == "BadRequestError"
    assert client.value.retryable is False
    assert "get_component" in client.value.message


@respx.mock
def test_the_api_key_never_reaches_the_error_message_or_the_error_event() -> None:
    """OpenAI echoes the offending key in its auth errors; it must not leave the adapter."""
    respx.post(RESPONSES_URL).mock(
        return_value=httpx.Response(
            401,
            json={"error": {"message": f"Incorrect API key provided: {KEY}. Check your key."}},
        )
    )

    sink = Sink()
    with pytest.raises(OpenAIProviderError) as caught:
        run(make_provider(), sink=sink)

    assert KEY not in caught.value.message
    assert KEY not in str(caught.value)
    assert MASK in caught.value.message
    assert KEY not in json.dumps(sink.one("error"))
