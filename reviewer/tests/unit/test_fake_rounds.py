"""Recorded rounds in the scripted provider (008 T005, research R2.3).

The replay plays a recorded review back through `FakeProvider`, and a recorded turn is not
one round: the big assembly's recording opens with a turn of 39 main rounds, each with its own
usage and its own calls. `ScriptedTurn.rounds` scripts exactly that - one assistant message per
round holding that round's calls, its tool messages after it, one `usage` event per round
before its calls run - while a turn scripted the old way plays byte-identically to before,
which the first test pins against a stream captured from the code as it was.
"""

from __future__ import annotations

from typing import Any

import pytest

from swreview.agent.providers import TokenUsage
from swreview.agent.providers.fake import (
    SYNTHETIC_USAGE,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from tests.unit.test_fake_provider import FakeTool, provider, run

A = ScriptedToolCall("alpha", {"x": 1})
B = ScriptedToolCall("beta")
C = ScriptedToolCall("gamma", {"group_key": "cmp:0002|cmp:0003"})


def usage(input_tokens: int, output_tokens: int = 40) -> TokenUsage:
    return TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        cache_write_tokens=None,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        tool_result_input_tokens=None,
        total_tokens=input_tokens + output_tokens,
        latency_s=0.25,
    )


def tools() -> list[FakeTool]:
    return [FakeTool("alpha"), FakeTool("beta", payload={"n": 2}), FakeTool("gamma")]


# --- the old shape is untouched ------------------------------------------------------

CAPTURED_EVENTS: list[tuple[str, dict[str, Any]]] = [
    (
        "usage",
        {
            "cache_diagnostic": None,
            "cache_write_tokens": None,
            "cached_input_tokens": 419,
            "input_tokens": 1337,
            "latency_s": 0.37,
            "model": "fake-scripted",
            "output_tokens": 211,
            "provider": "fake",
            "reasoning_tokens": 67,
            "round_index": 0,
            "tool_result_input_tokens": None,
            "total_tokens": 1548,
        },
    ),
    ("tool.started", {"arguments": {"x": 1}, "step_index": 0, "tool": "alpha"}),
    (
        "tool.finished",
        {
            "elapsed_s": 0.0,
            "error": None,
            "result_summary": '{"ok":true}',
            "status": "ok",
            "step_index": 0,
        },
    ),
    ("tool.started", {"arguments": {}, "step_index": 1, "tool": "beta"}),
    (
        "tool.finished",
        {
            "elapsed_s": 0.0,
            "error": "no",
            "result_summary": "no",
            "status": "error",
            "step_index": 1,
        },
    ),
    ("text.delta", {"text": "Two "}),
    ("text.delta", {"text": "checks "}),
    ("text.delta", {"text": "ran."}),
    ("text.done", {"text": "Two checks ran."}),
]
"""A clock-pinned run of the default `ScriptedTurn`, captured before `rounds` existed."""


def test_a_turn_without_rounds_plays_exactly_as_before() -> None:
    fake = provider(ScriptedTurn(text="Two checks ran.", tool_calls=(A, B)))
    stubs = [FakeTool("alpha"), FakeTool("beta", payload={"error": "no"}, is_error=True)]

    result, sink = run(fake, stubs)

    assert [(event.type, event.body) for event in sink.events] == CAPTURED_EVENTS
    assert result.reason == "end"
    assert result.steps == 2
    assert [m["role"] for m in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


def test_a_turn_without_rounds_defaults_rounds_to_empty() -> None:
    assert ScriptedTurn(text="done").rounds == ()


# --- rounds ------------------------------------------------------------------------


def test_each_round_is_one_assistant_message_holding_its_calls() -> None:
    fake = provider(ScriptedTurn(text="done", rounds=(ScriptedRound((A, B)), ScriptedRound((C,)))))

    result, _ = run(fake, tools())

    added = result.messages[1:]
    assert [m["role"] for m in added] == [
        "assistant",
        "tool",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert [call["name"] for call in added[0]["tool_calls"]] == ["alpha", "beta"]
    assert [call["name"] for call in added[3]["tool_calls"]] == ["gamma"]
    assert [m["name"] for m in added if m["role"] == "tool"] == ["alpha", "beta", "gamma"]
    assert [m["call_id"] for m in added if m["role"] == "tool"] == ["call_1", "call_2", "call_3"]
    assert added[-1] == {"role": "assistant", "content": "done"}
    assert result.steps == 3


def test_one_usage_event_per_round_then_the_closing_texts() -> None:
    fake = provider(
        ScriptedTurn(
            text="done",
            rounds=(ScriptedRound((A, B), usage=usage(100)), ScriptedRound((C,), usage=usage(200))),
            usage=usage(300),
        )
    )

    _, sink = run(fake, tools())

    usages = sink.bodies("usage")
    assert [body["round_index"] for body in usages] == [0, 1, 2]
    assert [body["input_tokens"] for body in usages] == [100, 200, 300]
    assert sink.types == [
        "usage",
        "tool.started",
        "tool.finished",
        "tool.started",
        "tool.finished",
        "usage",
        "tool.started",
        "tool.finished",
        "usage",
        "text.delta",
        "text.done",
    ]
    assert [u.input_tokens for u in fake.round_usage] == [100, 200, 300]


def test_a_round_without_usage_emits_none_but_keeps_its_index() -> None:
    fake = provider(
        ScriptedTurn(
            text="done",
            rounds=(ScriptedRound((A,)), ScriptedRound((C,), usage=usage(200))),
            usage=None,
        )
    )

    _, sink = run(fake, tools())

    assert [body["round_index"] for body in sink.bodies("usage")] == [1]


def test_the_default_closing_usage_is_the_synthetic_constant() -> None:
    fake = provider(ScriptedTurn(text="done", rounds=(ScriptedRound((A,), usage=usage(10)),)))

    _, sink = run(fake, tools())

    assert sink.bodies("usage")[-1]["input_tokens"] == SYNTHETIC_USAGE.input_tokens
    assert sink.bodies("usage")[-1]["round_index"] == 1


def test_step_index_is_continuous_across_rounds_and_turns() -> None:
    fake = provider(
        ScriptedTurn(text="one", rounds=(ScriptedRound((A, B)), ScriptedRound((C,)))),
        ScriptedTurn(text="two", rounds=(ScriptedRound((C,)),)),
    )

    result, sink = run(fake, tools())
    _, second = run(fake, tools(), messages=result.messages)

    assert [b["step_index"] for b in sink.bodies("tool.started")] == [0, 1, 2]
    assert [b["step_index"] for b in second.bodies("tool.started")] == [3]


def test_step_index_honours_start_steps_at() -> None:
    fake = provider(ScriptedTurn(text="done", rounds=(ScriptedRound((A,)), ScriptedRound((B,)))))
    fake.start_steps_at(5)

    _, sink = run(fake, tools())

    assert [b["step_index"] for b in sink.bodies("tool.started")] == [5, 6]
    assert [b["step_index"] for b in sink.bodies("tool.finished")] == [5, 6]


def test_setting_both_tool_calls_and_rounds_is_refused() -> None:
    with pytest.raises(ValueError, match="rounds"):
        ScriptedTurn(text="done", tool_calls=(A,), rounds=(ScriptedRound((B,)),))


def test_a_budget_that_cuts_mid_round_records_only_what_it_dispatched() -> None:
    fake = provider(
        ScriptedTurn(
            text="never said",
            rounds=(ScriptedRound((A, B), usage=usage(100)), ScriptedRound((C,), usage=usage(200))),
        )
    )

    result, sink = run(fake, tools(), max_steps=1)

    assert result.reason == "max_steps"
    assert result.steps == 1
    added = result.messages[1:]
    assert [m["role"] for m in added] == ["assistant", "tool"]
    assert [call["name"] for call in added[0]["tool_calls"]] == ["alpha"]
    assert [b["tool"] for b in sink.bodies("tool.started")] == ["alpha"]
    assert [b["round_index"] for b in sink.bodies("usage")] == [0]
    assert "text.done" not in sink.types


def test_a_budget_that_cuts_between_rounds_stops_before_the_next_round() -> None:
    fake = provider(
        ScriptedTurn(
            text="never said",
            rounds=(ScriptedRound((A, B), usage=usage(100)), ScriptedRound((C,), usage=usage(200))),
        )
    )

    result, sink = run(fake, tools(), max_steps=2)

    assert result.reason == "max_steps"
    assert [m["role"] for m in result.messages[1:]] == ["assistant", "tool", "tool"]
    assert [b["tool"] for b in sink.bodies("tool.started")] == ["alpha", "beta"]
    assert [b["round_index"] for b in sink.bodies("usage")] == [0], (
        "a round the budget never reaches is a request never made, so it costs nothing"
    )


def test_a_round_with_no_calls_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one call"):
        ScriptedRound(())
