"""The one request recorder used by 015's baseline and Send assertions (T003)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from swreview.agent.providers import AgentProvider
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.providers.openai_provider import _encode_history, tool_param
from tests.support.recording_provider import RecordingProvider
from tests.support.toolsets import toolset
from tests.unit.test_fake_provider import FakeTool, Sink, frozen_clock


def play(
    provider: RecordingProvider,
    *,
    messages: list[dict[str, Any]] | None = None,
    tools: list[FakeTool] | None = None,
    system: str = "Review the fictional café bracket.",
) -> tuple[Any, Sink]:
    sink = Sink()
    result = provider.run(
        system=system,
        messages=messages if messages is not None else [{"role": "user", "content": "Review it."}],
        tools=toolset(tools if tools is not None else []),
        effort="high",
        max_steps=10,
        on_event=sink,
    )
    return result, sink


def test_records_the_openai_encoded_input_before_a_tool_can_change_it() -> None:
    provider = RecordingProvider((ScriptedTurn(text="Done."),))
    tool = FakeTool(
        name="inspect_fictional_part",
        description="Inspect a fictional café bracket.",
        schema={"type": "object", "properties": {"part": {"type": "string"}}},
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Review FICT-7000."},
        {"role": "assistant", "content": "Checking the bracket."},
        {"role": "tool", "call_id": "call_1", "content": {"part": "FICT-7001"}},
    ]
    play(provider, messages=messages, tools=[tool])

    assert isinstance(provider, AgentProvider)
    assert len(provider.log) == 1
    request = provider.log[0]
    assert request.system == "Review the fictional café bracket."
    expected_tools = json.dumps([tool_param(tool)], ensure_ascii=False).encode("utf-8")
    assert request.encoded_tools == expected_tools
    assert request.encoded_history == tuple(
        json.dumps(item, ensure_ascii=False).encode("utf-8") for item in _encode_history(messages)
    )
    assert request.presentation is False
    assert request.tool_specs == (
        {"name": tool.name, "description": tool.description, "parameters": tool.schema},
    )
    assert request.first_message == messages[0]
    assert provider.systems == [request.system]
    assert provider.tool_arrays == [request.encoded_tools]
    assert provider.inputs == [[item.decode("utf-8") for item in request.encoded_history]]

    # The stored request is a snapshot, even if a later check rewrites a shared input.
    tool.schema["properties"]["part"]["type"] = "number"
    messages[0]["content"] = "Changed after the request."
    assert request.tool_specs[0]["parameters"]["properties"]["part"]["type"] == "string"
    assert request.first_message == {"role": "user", "content": "Review FICT-7000."}


def test_a_raising_turn_still_has_one_ordered_input_record() -> None:
    provider = RecordingProvider(())
    with pytest.raises(ValueError, match="the script has 0 turn"):
        play(provider, system="This request will fail.")
    assert len(provider.log) == 1
    assert provider.log[0].system == "This request will fail."


def test_review_and_independent_presentation_requests_share_one_ordered_log() -> None:
    provider = RecordingProvider(
        (ScriptedTurn(text="Review one."), ScriptedTurn(text="Review two.")),
        explanation_script=(ScriptedTurn(text="Explain the finding."),),
    )
    first, _ = play(provider, system="Review one.")
    presentation = provider.for_presentation(2048)
    explanation, _ = play(presentation, system="Presentation one.")
    second, _ = play(provider, system="Review two.")

    assert presentation is not provider
    assert presentation.model == provider.model
    assert presentation.log is provider.log
    assert [entry.system for entry in provider.log] == [
        "Review one.", "Presentation one.", "Review two."
    ]
    assert [entry.presentation for entry in provider.log] == [False, True, False]
    assert [first.text, explanation.text, second.text] == [
        "Review one.", "Explain the finding.", "Review two."
    ]


def test_two_plays_of_the_same_script_have_equal_logs() -> None:
    def recorded() -> RecordingProvider:
        provider = RecordingProvider(
            (ScriptedTurn(text="Review one."), ScriptedTurn(text="Review two.")),
            explanation_script=(ScriptedTurn(text="Explain the finding."),),
        )
        play(provider, system="Review one.")
        play(provider.for_presentation(2048), system="Presentation one.")
        play(provider, system="Review two.")
        return provider

    assert recorded().log == recorded().log


def test_pre_run_step_numbers_continue_through_the_delegated_provider() -> None:
    provider = RecordingProvider(
        (ScriptedTurn(text="Done.", tool_calls=(ScriptedToolCall(name="inspect_part"),)),),
        clock=frozen_clock,
    )
    provider.start_steps_at(7)
    _, sink = play(provider, tools=[FakeTool(name="inspect_part")])
    assert sink.bodies("tool.started")[0]["step_index"] == 7
