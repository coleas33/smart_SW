"""Unit tests for the Gemini adapter (T019).

Every exchange here is a stubbed `genai.Client`: the adapter is exercised against the real
`google.genai.types` models (so a field that moved or a constructor that changed fails the
test) but never against the network. What the adapter owes the rest of the system:

- tools declared with `parameters_json_schema=gemini_adapt(...)`, never the OpenAPI
  `parameters` field, and `automatic_function_calling.disable=True` so *our* loop runs each
  call through `RecordedTool` (validation, recording, the never-raise rule);
- effort mapped to `thinking_config` - `thinking_level` on 3.x models, the integer
  `thinking_budget` on 2.5 models - or a named failure. Never a silent downgrade;
- the contract's events synthesized out of a stream that has none;
- provider errors mapped to named, redacted failures before they reach the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from google.genai import errors, types

from swreview.agent import providers
from swreview.agent.providers import (
    AgentEvent,
    AgentProvider,
    EventType,
    ProviderName,
    ToolCallResult,
)
from swreview.agent.providers.gemini_provider import (
    AUTOMATIC_FUNCTION_CALLING_DISABLED,
    BUDGET_PARAM,
    LEVEL_PARAM,
    NATIVE_CONTENT_KEY,
    GeminiAuthError,
    GeminiProvider,
    GeminiRateLimitError,
    GeminiRequestError,
    GeminiServerError,
    UnsupportedEffortError,
)
from swreview.agent.providers.schema import gemini_adapt, tool_spec
from swreview.agent.settings import MASK
from tests.support.contracts import contract_validator
from tests.support.toolsets import toolset

AT = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)
LEVEL_MODEL = "gemini-3.5-flash"
"""A model whose thinking control is `thinking_level` (the product default)."""
BUDGET_MODEL = "gemini-2.5-flash"
"""A 2.5 model, whose control is the integer `thinking_budget`."""
SECRET = "AIza-not-a-real-key"


def frozen_clock() -> float:
    return 3.5


# --- a tool, a stub client, and a sink -------------------------------------------------


def list_components(configuration: str) -> dict[str, Any]:
    """List the components of the assembly.

    Args:
        configuration: The configuration to read.
    """
    return {"components": []}


@dataclass
class FakeTool:
    """A `ProviderTool` that records its calls; stands in for `RecordedTool`."""

    name: str
    description: str = "a tool"
    schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    payload: dict[str, Any] = field(default_factory=lambda: {"ok": True})
    is_error: bool = False
    calls: list[tuple[dict[str, Any], str]] = field(default_factory=list)

    def call(self, arguments: Any, call_id: str) -> ToolCallResult:
        self.calls.append((dict(arguments), call_id))
        return ToolCallResult(call_id=call_id, payload=self.payload, is_error=self.is_error)


def spec_tool() -> FakeTool:
    """A tool carrying a real canonical schema, so the declaration assertions are real."""
    spec = tool_spec(list_components)
    return FakeTool(name=spec.name, description=spec.description, schema=spec.schema)


@dataclass
class StubModels:
    """`client.models`: one scripted stream per round, or an exception to raise."""

    rounds: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate_content_stream(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if not self.rounds:
            raise AssertionError("the adapter asked for more rounds than the script has")
        scripted = self.rounds.pop(0)
        if isinstance(scripted, Exception):
            raise scripted
        return iter(scripted)


@dataclass
class StubClient:
    models: StubModels


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


# --- chunk builders --------------------------------------------------------------------


def chunk(
    *parts: types.Part, finish_reason: types.FinishReason | None = None
) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=list(parts)),
                finish_reason=finish_reason,
            )
        ]
    )


def text_part(text: str, *, thought: bool = False, signature: bytes | None = None) -> types.Part:
    return types.Part(text=text, thought=thought or None, thought_signature=signature)


def call_part(call_id: str, name: str, args: dict[str, Any]) -> types.Part:
    return types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=args))


def stop() -> types.GenerateContentResponse:
    """The last chunk of a stream: a finish reason and no content."""
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=None, finish_reason=types.FinishReason.STOP)]
    )


# --- building and running the adapter ---------------------------------------------------


def build(
    *rounds: Any,
    model: str = LEVEL_MODEL,
    max_output_tokens: int | None = None,
) -> tuple[GeminiProvider, StubModels]:
    models = StubModels(rounds=list(rounds))
    adapter = GeminiProvider(
        client=StubClient(models=models),
        model=model,
        secrets=[SECRET],
        max_output_tokens=max_output_tokens,
        clock=frozen_clock,
    )
    return adapter, models


def run(
    adapter: GeminiProvider,
    tools: list[FakeTool],
    *,
    sink: Sink | None = None,
    messages: list[dict[str, Any]] | None = None,
    effort: str = "high",
    max_steps: int = 10,
) -> tuple[Any, Sink]:
    sink = sink or Sink()
    result = adapter.run(
        system="you are a reviewer",
        messages=messages if messages is not None else [{"role": "user", "content": "review it"}],
        tools=toolset(tools),
        effort=effort,  # type: ignore[arg-type]
        max_steps=max_steps,
        on_event=sink,
    )
    return result, sink


# --- registration and the protocol ------------------------------------------------------


def test_gemini_is_registered_under_its_provider_name() -> None:
    assert providers.get("gemini") is GeminiProvider
    assert ProviderName.GEMINI in providers.available()


def test_gemini_satisfies_the_provider_protocol() -> None:
    adapter, _ = build()
    assert isinstance(adapter, AgentProvider)
    assert adapter.name is ProviderName.GEMINI
    assert adapter.model == LEVEL_MODEL


# --- the request -------------------------------------------------------------------------


def test_tools_are_declared_with_parameters_json_schema() -> None:
    tool = spec_tool()
    adapter, models = build([chunk(text_part("done"), finish_reason=types.FinishReason.STOP)])
    run(adapter, [tool])

    config = models.calls[0]["config"]
    assert len(config.tools) == 1
    declarations = config.tools[0].function_declarations
    assert len(declarations) == 1
    declaration = declarations[0]
    assert declaration.name == "list_components"
    assert declaration.description == tool.description
    assert declaration.parameters_json_schema == gemini_adapt(tool.schema)
    assert declaration.parameters is None, "the OpenAPI Schema field is mutually exclusive"


def test_the_declared_schema_carries_no_additional_properties_or_defs() -> None:
    tool = spec_tool()
    adapter, models = build([chunk(text_part("done"), finish_reason=types.FinishReason.STOP)])
    run(adapter, [tool])

    declared = models.calls[0]["config"].tools[0].function_declarations[0].parameters_json_schema
    assert "additionalProperties" not in declared
    assert "$defs" not in declared


def test_automatic_function_calling_is_disabled() -> None:
    """Our loop owns every call: validation, recording and the never-raise rule."""
    adapter, models = build([chunk(text_part("done"), finish_reason=types.FinishReason.STOP)])
    run(adapter, [spec_tool()])

    config = models.calls[0]["config"]
    assert config.automatic_function_calling == AUTOMATIC_FUNCTION_CALLING_DISABLED
    assert config.automatic_function_calling.disable is True


def test_the_system_prompt_goes_in_system_instruction_not_the_history() -> None:
    adapter, models = build([chunk(text_part("done"), finish_reason=types.FinishReason.STOP)])
    run(adapter, [])

    call = models.calls[0]
    assert call["config"].system_instruction == "you are a reviewer"
    assert call["model"] == LEVEL_MODEL
    assert [content.role for content in call["contents"]] == ["user"]


def test_the_output_ceiling_is_sent_only_when_configured() -> None:
    adapter, models = build(
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)],
        max_output_tokens=4096,
    )
    run(adapter, [])
    assert models.calls[0]["config"].max_output_tokens == 4096

    unset, unset_models = build([chunk(text_part("x"), finish_reason=types.FinishReason.STOP)])
    run(unset, [])
    assert unset_models.calls[0]["config"].max_output_tokens is None


# --- effort ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("effort", "expected"),
    [("low", "LOW"), ("medium", "MEDIUM"), ("high", "HIGH")],
)
def test_effort_maps_to_thinking_level_on_a_3x_model(effort: str, expected: str) -> None:
    adapter, models = build(
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)], model=LEVEL_MODEL
    )
    mapping = adapter.effort_mapping(effort)  # type: ignore[arg-type]
    assert mapping.requested == effort
    assert mapping.provider_param == LEVEL_PARAM
    assert mapping.provider_value == expected

    run(adapter, [], effort=effort)
    thinking = models.calls[0]["config"].thinking_config
    assert thinking.thinking_level == types.ThinkingLevel(expected)
    assert thinking.thinking_budget is None


def test_effort_maps_to_an_integer_thinking_budget_on_a_25_model() -> None:
    adapter, models = build(
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)], model=BUDGET_MODEL
    )
    mapping = adapter.effort_mapping("high")
    assert mapping.provider_param == BUDGET_PARAM
    assert isinstance(mapping.provider_value, int)
    assert not isinstance(mapping.provider_value, bool)

    run(adapter, [])
    thinking = models.calls[0]["config"].thinking_config
    assert thinking.thinking_budget == mapping.provider_value
    assert thinking.thinking_level is None


def test_a_level_the_model_does_not_offer_fails_fast_and_sends_nothing() -> None:
    """Gemini's thinking levels stop at HIGH; `xhigh` is an error, never a downgrade."""
    adapter, models = build(model=LEVEL_MODEL)
    with pytest.raises(UnsupportedEffortError) as caught:
        adapter.effort_mapping("xhigh")
    assert "xhigh" in str(caught.value)
    assert LEVEL_MODEL in str(caught.value)

    with pytest.raises(UnsupportedEffortError):
        run(adapter, [], effort="xhigh")
    assert models.calls == [], "the turn must fail before any request is sent"


def test_a_budget_the_25_model_does_not_offer_fails_fast() -> None:
    adapter, _ = build(model=BUDGET_MODEL)
    with pytest.raises(UnsupportedEffortError) as caught:
        adapter.effort_mapping("xhigh")
    assert BUDGET_MODEL in str(caught.value)


def test_a_model_with_no_thinking_table_fails_fast_rather_than_guessing() -> None:
    adapter, _ = build(model="gemini-2.5-unknown-preview")
    with pytest.raises(UnsupportedEffortError) as caught:
        adapter.effort_mapping("high")
    assert "gemini-2.5-unknown-preview" in str(caught.value)


# --- streaming ---------------------------------------------------------------------------


def test_streamed_text_becomes_deltas_then_one_done_per_turn() -> None:
    adapter, _ = build(
        [
            chunk(text_part("Checking ")),
            chunk(text_part("the joints")),
            stop(),
        ]
    )
    result, sink = run(adapter, [])

    assert sink.types == ["text.delta", "text.delta", "text.done"]
    assert [body["text"] for body in sink.bodies("text.delta")] == ["Checking ", "the joints"]
    assert sink.bodies("text.done") == [{"text": "Checking the joints"}]
    assert result.text == "Checking the joints"
    assert result.reason == "end"
    assert result.steps == 0
    last = result.messages[-1]
    assert last["role"] == "assistant"
    assert last["content"] == "Checking the joints"
    assert "tool_calls" not in last
    assert last[NATIVE_CONTENT_KEY]["role"] == "model", "the model's own parts are kept"


def test_one_text_done_carries_every_round_of_a_multi_round_turn() -> None:
    """`data-model.md` defines `text.done` as the *turn* text, not one round of it.

    A turn that says something, calls a tool and then says the rest must not publish two
    `text.done` events, and `TurnResult.text` must not be only the second half - the pane
    and `events.jsonl` would both lose the first sentence of the answer.
    """
    tool = spec_tool()
    adapter, _ = build(
        [
            chunk(
                text_part("Checking the bracket. "),
                call_part("fc_1", "list_components", {"configuration": "Default"}),
            )
        ],
        [chunk(text_part("It interferes."), finish_reason=types.FinishReason.STOP)],
    )
    result, sink = run(adapter, [tool])

    assert sink.bodies("text.done") == [{"text": "Checking the bracket. It interferes."}]
    assert result.text == "Checking the bracket. It interferes."
    assert sink.types == [
        "text.delta",
        "tool.started",
        "tool.finished",
        "text.delta",
        "text.done",
    ]


def test_the_turn_text_is_kept_when_the_step_budget_ends_the_turn() -> None:
    """`max_steps` is still an ending: the text streamed so far is the turn's text."""
    tool = spec_tool()
    adapter, _ = build(
        [
            chunk(
                text_part("Looking at two of them. "),
                call_part("fc_1", "list_components", {"configuration": "Default"}),
                call_part("fc_2", "list_components", {"configuration": "Other"}),
            )
        ]
    )
    result, sink = run(adapter, [tool], max_steps=1)

    assert result.reason == "max_steps"
    assert result.text == "Looking at two of them. "
    assert sink.bodies("text.done") == [{"text": "Looking at two of them. "}]


def test_thought_parts_are_not_streamed_as_answer_text() -> None:
    adapter, _ = build(
        [
            chunk(text_part("the user wants clearances", thought=True)),
            chunk(text_part("All clear"), finish_reason=types.FinishReason.STOP),
        ]
    )
    result, sink = run(adapter, [])
    assert [body["text"] for body in sink.bodies("text.delta")] == ["All clear"]
    assert result.text == "All clear"


def test_a_turn_that_hits_the_output_ceiling_ends_truncated() -> None:
    adapter, _ = build(
        [chunk(text_part("half a sen"), finish_reason=types.FinishReason.MAX_TOKENS)]
    )
    result, sink = run(adapter, [])
    assert result.reason == "truncated"
    assert sink.bodies("text.done") == [{"text": "half a sen"}]


# --- finish reasons -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [None, types.FinishReason.STOP, types.FinishReason.FINISH_REASON_UNSPECIFIED],
)
def test_a_completed_turn_ends_end(reason: types.FinishReason | None) -> None:
    adapter, _ = build([chunk(text_part("all clear"), finish_reason=reason)])
    result, sink = run(adapter, [])
    assert result.reason == "end"
    assert "error" not in sink.types


@pytest.mark.parametrize(
    "reason",
    [
        types.FinishReason.MAX_TOKENS,
        types.FinishReason.MALFORMED_FUNCTION_CALL,
        types.FinishReason.UNEXPECTED_TOOL_CALL,
    ],
)
def test_a_cut_short_turn_ends_truncated(reason: types.FinishReason) -> None:
    """The ceiling and the two malformed-call reasons are all "cut short", never "done".

    `MALFORMED_FUNCTION_CALL` and `UNEXPECTED_TOOL_CALL` are Gemini's side of OpenAI's
    unparseable-arguments path: the model meant to call a tool and the call did not
    survive, so the turn is incomplete rather than finished.
    """
    adapter, _ = build([chunk(text_part("half a sen"), finish_reason=reason)])
    result, sink = run(adapter, [])
    assert result.reason == "truncated"
    assert result.text == "half a sen"
    assert "error" not in sink.types


@pytest.mark.parametrize(
    "reason",
    [
        types.FinishReason.SAFETY,
        types.FinishReason.RECITATION,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.SPII,
        types.FinishReason.LANGUAGE,
        types.FinishReason.TOO_MANY_TOOL_CALLS,
        types.FinishReason.OTHER,
    ],
)
def test_a_refused_or_blocked_turn_is_reported_as_an_error_not_an_end(
    reason: types.FinishReason,
) -> None:
    """Constitution Principle I: a turn the service cut off must not read as a normal end.

    Reported rather than raised: the text already streamed and the history built so far
    are still worth keeping, and the runner turns `error` into unresolved coverage.
    """
    adapter, _ = build([chunk(text_part("I cannot"), finish_reason=reason)])
    result, sink = run(adapter, [])

    assert result.reason == "error"
    assert sink.types.count("error") == 1
    body = sink.bodies("error")[0]
    assert reason.value in body["message"]
    assert body["error_class"] == "GeminiBlockedTurnError"
    assert body["retryable"] is False


def test_an_unknown_finish_reason_is_an_error_rather_than_a_silent_end() -> None:
    """A reason this adapter has never heard of is the one case that must not default to
    "end": the enum grows, and a new stop reason read as a completed answer is exactly the
    silent failure the constitution forbids."""
    adapter, _ = build([chunk(text_part("x"), finish_reason=types.FinishReason.NO_IMAGE)])
    result, sink = run(adapter, [])
    assert result.reason == "error"
    assert sink.bodies("error")[0]["error_class"] == "GeminiBlockedTurnError"


def test_a_terminal_finish_reason_on_a_round_that_also_asked_for_a_tool_runs_nothing() -> None:
    """The ceiling is checked *before* the calls are dispatched, as on the OpenAI side.

    A `function_call` whose arguments were cut off mid-stream must not be run and must not
    be sent back for another round: the turn is already known to be incomplete.
    """
    tool = spec_tool()
    adapter, models = build(
        [
            chunk(
                text_part("half a th"),
                call_part("fc_1", "list_components", {"configuration": "Default"}),
                finish_reason=types.FinishReason.MAX_TOKENS,
            )
        ]
    )
    result, sink = run(adapter, [tool])

    assert result.reason == "truncated"
    assert tool.calls == [], "a cut-short call is never run"
    assert len(models.calls) == 1, "the cut-short round is not sent back for another answer"
    assert "tool.started" not in sink.types
    assert result.text == "half a th"
    calls_in_history = [
        message for message in result.messages if message.get("tool_calls") is not None
    ]
    assert calls_in_history == [], "an unanswered function call must not be left in the history"


def test_a_blocked_round_that_also_asked_for_a_tool_runs_nothing() -> None:
    tool = spec_tool()
    adapter, models = build(
        [
            chunk(
                call_part("fc_1", "list_components", {"configuration": "Default"}),
                finish_reason=types.FinishReason.SAFETY,
            )
        ]
    )
    result, _ = run(adapter, [tool])
    assert result.reason == "error"
    assert tool.calls == []
    assert len(models.calls) == 1


# --- tool calls ---------------------------------------------------------------------------


def test_a_function_call_runs_through_the_tool_and_is_answered_with_its_id() -> None:
    tool = spec_tool()
    tool.payload = {"components": ["cmp:0001"]}
    adapter, models = build(
        [
            chunk(
                call_part("fc_1", "list_components", {"configuration": "Default"}),
                finish_reason=types.FinishReason.STOP,
            )
        ],
        [chunk(text_part("one component"), finish_reason=types.FinishReason.STOP)],
    )
    result, sink = run(adapter, [tool])

    assert tool.calls == [({"configuration": "Default"}, "fc_1")]
    assert sink.types == ["tool.started", "tool.finished", "text.delta", "text.done"]
    assert sink.bodies("tool.started") == [
        {"step_index": 0, "tool": "list_components", "arguments": {"configuration": "Default"}}
    ]
    finished = sink.bodies("tool.finished")[0]
    assert finished["status"] == "ok"
    assert finished["error"] is None
    assert finished["elapsed_s"] == 0.0
    assert finished["result_summary"] == '{"components":["cmp:0001"]}'

    contents = models.calls[1]["contents"]
    assert [content.role for content in contents] == ["user", "model", "tool"]
    response = contents[-1].parts[0].function_response
    assert response.id == "fc_1"
    assert response.name == "list_components"
    assert response.response == {"output": {"components": ["cmp:0001"]}}
    assert result.steps == 1
    assert result.text == "one component"


def test_a_failed_tool_result_is_reported_to_the_model_as_an_error_response() -> None:
    tool = FakeTool(name="check_fit", payload={"error": "unknown component id"}, is_error=True)
    adapter, models = build(
        [chunk(call_part("fc_1", "check_fit", {"a": "cmp:9999"}))],
        [chunk(text_part("noted"), finish_reason=types.FinishReason.STOP)],
    )
    result, sink = run(adapter, [tool])

    finished = sink.bodies("tool.finished")[0]
    assert finished["status"] == "error"
    assert finished["error"] == "unknown component id"
    response = models.calls[1]["contents"][-1].parts[0].function_response
    assert response.response == {"error": {"error": "unknown component id"}}
    assert result.reason == "end"


def test_a_call_naming_an_unknown_tool_is_an_error_result_not_an_exception() -> None:
    """A hallucinated tool name is routine model behaviour, not a crash."""
    adapter, models = build(
        [chunk(call_part("fc_1", "measure_everything", {}))],
        [chunk(text_part("sorry"), finish_reason=types.FinishReason.STOP)],
    )
    result, sink = run(adapter, [spec_tool()])

    finished = sink.bodies("tool.finished")[0]
    assert finished["status"] == "error"
    assert "measure_everything" in finished["error"]
    assert result.steps == 1
    assert models.calls[1]["contents"][-1].parts[0].function_response.id == "fc_1"
    assert result.messages[-2]["role"] == "tool"
    assert result.messages[-2]["is_error"] is True


def test_parallel_calls_in_one_round_are_answered_in_one_tool_content() -> None:
    first = FakeTool(name="list_components", payload={"components": []})
    second = FakeTool(name="check_fit", payload={"verdict": "pass"})
    adapter, models = build(
        [
            chunk(
                call_part("fc_1", "list_components", {}),
                call_part("fc_2", "check_fit", {"a": "cmp:0001"}),
            )
        ],
        [chunk(text_part("all clear"), finish_reason=types.FinishReason.STOP)],
    )
    result, _ = run(adapter, [first, second])

    contents = models.calls[1]["contents"]
    assert [content.role for content in contents] == ["user", "model", "tool"]
    assert [part.function_response.id for part in contents[-1].parts] == ["fc_1", "fc_2"]
    assert result.steps == 2


def test_step_index_keeps_counting_across_turns() -> None:
    tool = spec_tool()
    adapter, _ = build(
        [chunk(call_part("fc_1", "list_components", {"configuration": "Default"}))],
        [chunk(text_part("a"), finish_reason=types.FinishReason.STOP)],
        [chunk(call_part("fc_2", "list_components", {"configuration": "Default"}))],
        [chunk(text_part("b"), finish_reason=types.FinishReason.STOP)],
    )
    _, first = run(adapter, [tool])
    _, second = run(adapter, [tool])
    assert first.bodies("tool.started")[0]["step_index"] == 0
    assert second.bodies("tool.started")[0]["step_index"] == 1


def test_max_steps_is_a_per_turn_budget() -> None:
    tool = spec_tool()
    adapter, models = build(
        [
            chunk(
                call_part("fc_1", "list_components", {"configuration": "Default"}),
                call_part("fc_2", "list_components", {"configuration": "Other"}),
            )
        ],
    )
    result, sink = run(adapter, [tool], max_steps=1)

    assert result.reason == "max_steps"
    assert result.steps == 1
    assert len(tool.calls) == 1
    assert len(models.calls) == 1, "the cut-short round is not sent back for another answer"
    assert sink.types.count("tool.started") == 1
    calls_in_history = [
        message for message in result.messages if message.get("tool_calls") is not None
    ]
    assert [call["call_id"] for call in calls_in_history[-1]["tool_calls"]] == ["fc_1"], (
        "an unanswered function call must not be left in the history"
    )


def test_max_steps_of_zero_runs_no_tool() -> None:
    tool = spec_tool()
    adapter, models = build(
        [chunk(call_part("fc_1", "list_components", {"configuration": "Default"}))]
    )
    result, sink = run(adapter, [tool], max_steps=0)

    assert result.reason == "max_steps"
    assert result.steps == 0
    assert tool.calls == []
    assert len(models.calls) == 1
    assert sink.types == []


# --- history ---------------------------------------------------------------------------


def test_the_neutral_history_is_translated_into_contents() -> None:
    adapter, models = build([chunk(text_part("ok"), finish_reason=types.FinishReason.STOP)])
    history = [
        {"role": "user", "content": "review it"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [
                {"call_id": "fc_1", "name": "list_components", "arguments": {"configuration": "D"}}
            ],
        },
        {
            "role": "tool",
            "call_id": "fc_1",
            "name": "list_components",
            "content": {"components": []},
            "is_error": False,
        },
        {"role": "user", "content": "and the fasteners?"},
    ]
    result, _ = run(adapter, [], messages=history)

    contents = models.calls[0]["contents"]
    assert [content.role for content in contents] == ["user", "model", "tool", "user"]
    model_parts = contents[1].parts
    assert model_parts[0].text == "checking"
    assert model_parts[1].function_call.id == "fc_1"
    assert model_parts[1].function_call.args == {"configuration": "D"}
    assert contents[2].parts[0].function_response.id == "fc_1"
    assert history[0] == {"role": "user", "content": "review it"}, "input history is not mutated"
    assert result.messages[: len(history)] == history


def test_a_replayed_assistant_turn_keeps_its_thought_signature() -> None:
    """Gemini 3 rejects a function-calling history whose thought signatures were dropped."""
    signature = b"\x01\x02sig"
    adapter, models = build(
        [
            chunk(
                text_part("checking", signature=signature),
                call_part("fc_1", "list_components", {"configuration": "Default"}),
            )
        ],
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)],
    )
    result, _ = run(adapter, [spec_tool()])

    replayed = models.calls[1]["contents"][1]
    assert replayed.role == "model"
    assert replayed.parts[0].thought_signature == signature

    followup, followup_models = build(
        [chunk(text_part("more"), finish_reason=types.FinishReason.STOP)]
    )
    run(followup, [spec_tool()], messages=result.messages)
    carried = followup_models.calls[0]["contents"][1]
    assert carried.parts[0].thought_signature == signature


# --- errors --------------------------------------------------------------------------------


def client_error(code: int, status: str, message: str) -> errors.ClientError:
    return errors.ClientError(code, {"error": {"code": code, "status": status, "message": message}})


def server_error(code: int, message: str) -> errors.ServerError:
    return errors.ServerError(
        code, {"error": {"code": code, "status": "UNAVAILABLE", "message": message}}
    )


@pytest.mark.parametrize(
    ("raised", "expected", "retryable"),
    [
        (client_error(401, "UNAUTHENTICATED", "API key not valid"), GeminiAuthError, False),
        (client_error(429, "RESOURCE_EXHAUSTED", "quota exceeded"), GeminiRateLimitError, True),
        (client_error(400, "INVALID_ARGUMENT", "bad schema"), GeminiRequestError, False),
        (server_error(503, "model overloaded"), GeminiServerError, True),
    ],
)
def test_provider_errors_are_mapped_named_and_reported(
    raised: Exception, expected: type[Exception], retryable: bool
) -> None:
    adapter, _ = build(raised)
    sink = Sink()
    with pytest.raises(expected):
        run(adapter, [], sink=sink)

    assert sink.types == ["error"]
    body = sink.bodies("error")[0]
    assert body["error_class"] == expected.__name__
    assert body["retryable"] is retryable
    assert body["message"]


def test_the_key_is_redacted_out_of_the_error_it_is_reported_in() -> None:
    adapter, _ = build(client_error(401, "UNAUTHENTICATED", f"API key {SECRET} not valid"))
    sink = Sink()
    with pytest.raises(GeminiAuthError) as caught:
        run(adapter, [], sink=sink)

    assert SECRET not in str(caught.value)
    assert SECRET not in sink.bodies("error")[0]["message"]
    assert MASK in sink.bodies("error")[0]["message"]


def test_a_gemini_provider_cannot_be_built_without_its_secrets() -> None:
    """FR-015 is structural here: there is no constructor that reports raw provider text.

    An enterprise run authenticating through ADC passes `secrets=[]` - an explicit
    statement that there is no key to mask, not a default that quietly masks nothing.
    """
    with pytest.raises(TypeError) as caught:
        GeminiProvider(client=StubClient(models=StubModels(rounds=[])), model=LEVEL_MODEL)  # type: ignore[call-arg]
    assert "secrets" in str(caught.value)


def test_the_key_is_redacted_with_the_settings_redactor_not_an_injected_one() -> None:
    """The adapter reaches for `settings.redact` itself, so no caller can skip it."""
    models = StubModels(rounds=[client_error(401, "UNAUTHENTICATED", f"key {SECRET} invalid")])
    adapter = GeminiProvider(
        client=StubClient(models=models), model=LEVEL_MODEL, secrets=[SECRET]
    )
    sink = Sink()
    with pytest.raises(GeminiAuthError) as caught:
        adapter.run(
            system="s",
            messages=[{"role": "user", "content": "review it"}],
            tools=toolset([]),
            effort="high",
            max_steps=1,
            on_event=sink,
        )
    assert SECRET not in str(caught.value)
    assert SECRET not in sink.bodies("error")[0]["message"]
    assert MASK in sink.bodies("error")[0]["message"]


def test_an_error_raised_mid_stream_is_mapped_the_same_way() -> None:
    """The first chunks arrive, then the connection fails: still one mapped failure."""

    def failing_stream() -> Any:
        yield chunk(text_part("Checking "))
        raise server_error(500, "internal")

    adapter, _ = build(failing_stream())
    sink = Sink()
    with pytest.raises(GeminiServerError):
        run(adapter, [], sink=sink)
    assert sink.types == ["text.delta", "error"]


# --- the contract ----------------------------------------------------------------------------


def test_every_emitted_event_validates_against_the_contract() -> None:
    validator = contract_validator("chat-events.schema.json")
    tools = [
        spec_tool(),
        FakeTool(name="check_fit", payload={"error": "no such id"}, is_error=True),
    ]
    adapter, _ = build(
        [
            chunk(
                call_part("fc_1", "list_components", {"configuration": "Default"}),
                call_part("fc_2", "check_fit", {"a": "cmp:9999"}),
                call_part("fc_3", "gone_missing", {}),
            )
        ],
        [chunk(text_part("one finding"), finish_reason=types.FinishReason.STOP)],
    )
    _, sink = run(adapter, tools)
    assert set(sink.types) == {"tool.started", "tool.finished", "text.delta", "text.done"}
    for event in sink.serialized():
        validator.validate(event)


def test_the_error_event_validates_against_the_contract() -> None:
    validator = contract_validator("chat-events.schema.json")
    adapter, _ = build(client_error(429, "RESOURCE_EXHAUSTED", "quota exceeded"))
    sink = Sink()
    with pytest.raises(GeminiRateLimitError):
        run(adapter, [], sink=sink)
    for event in sink.serialized():
        validator.validate(event)
