"""The `usage` event, one per model round trip, emitted by the adapter (T012).

What a round cost reaches the stream as an event and **not** as a field on `TurnResult`,
and the reason is the failure path rather than taste. Both adapters raise out of their
round loop on a provider error - `openai_provider._respond` raises `OpenAIProviderError`
and `gemini_provider._stream` raises through `self._report` - and `ReviewRun._run_turn`'s
`except Exception` branch finalizes and re-raises with no `TurnResult` to read. Usage
carried home on `TurnResult` would therefore report **zero cost for the turn that cost the
most**: five successful rounds and a rate limit on the sixth. `EventSink.emit` opens,
appends and closes per event precisely so the stream survives the process dying mid-review,
which means those five paid rounds are already on disk. That is the single claim the two
mid-turn-failure tests below pin, once per adapter.

Three more things this module fixes, because each of them is a decision a later reader
would otherwise have to re-derive:

- **`round_index` is the adapter's own per-turn counter, zero-based, reset each turn.**
  Exactly the convention `tool.started.step_index` already uses, and for the reason the
  providers module docstring gives: an adapter sees one turn and cannot know a
  session-level number. It is the round-trip counter levers 5, 6 and 7 are unmeasurable
  without, and it is not `TurnResult.steps`, which counts tool calls.
- **No turn number is carried.** Turns are delimited by the existing `turn.ended` events,
  so the runner never has to enrich an adapter's event on its way past.
- **All three producers build the body through one builder.** The bodies of an OpenAI, a
  Gemini and a fake round are asserted to have the same keys in the same order, which is
  what stops the three drifting into three shapes of the same event.

The schema this body validates against is `test_usage_contracts.py`'s subject (T019); here
the shape is pinned against `TokenUsage.model_fields` rather than a retyped list, so a
count added to the model without being added to the event fails here.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from google.genai import types

from swreview.agent.providers import TokenUsage, usage_body
from swreview.agent.providers.fake import SYNTHETIC_USAGE, ScriptedToolCall, ScriptedTurn
from swreview.agent.providers.gemini_provider import GeminiServerError
from swreview.agent.providers.openai_provider import OpenAIProviderError
from tests.support import usage as synthetic
from tests.unit import test_fake_provider as fake_support
from tests.unit.test_gemini_provider import LEVEL_MODEL, call_part, chunk, server_error, text_part
from tests.unit.test_gemini_provider import FakeTool as GeminiTool
from tests.unit.test_gemini_provider import Sink as GeminiSink
from tests.unit.test_gemini_provider import run as gemini_run
from tests.unit.test_openai_provider import (
    MODEL,
    RESPONSES_URL,
    completed,
    function_call_item,
    message_item,
    stream_response,
)
from tests.unit.test_openai_provider import FakeTool as OpenAITool
from tests.unit.test_openai_provider import Sink as OpenAISink
from tests.unit.test_openai_provider import run as openai_run
from tests.unit.test_usage_gemini import build as gemini_build
from tests.unit.test_usage_gemini import stop_chunk
from tests.unit.test_usage_openai import provider_with, responses, small_block, with_usage
from tests.unit.test_usage_openai import stepping_clock as openai_clock

COUNT_FIELDS: tuple[str, ...] = tuple(
    name for name in TokenUsage.model_fields if name != "latency_s"
)
"""The seven nullable counts, taken from the model so the event cannot fall behind it."""

BODY_FIELDS: tuple[str, ...] = (
    "round_index",
    "provider",
    "model",
    *COUNT_FIELDS,
    "latency_s",
    "cache_diagnostic",
)
"""Every field of the body, in the order contracts/usage.md section 5 prints them."""


def usage_bodies(sink: Any) -> list[dict[str, Any]]:
    return sink.bodies("usage")


def one_usage(sink: Any) -> dict[str, Any]:
    """The single `usage` body on a sink, asserted to be single.

    The two adapters' test modules ship slightly different `Sink` helpers and only one of
    them has a `one()`; this keeps the assertion identical on both.
    """
    bodies = usage_bodies(sink)
    assert len(bodies) == 1, f"expected one usage event, got {len(bodies)}"
    return bodies[0]


# --- the fake ---------------------------------------------------------------------------


def fake_run(*turns: ScriptedTurn, tools: list[Any] | None = None) -> Any:
    """Play one scripted turn and hand back the sink it wrote to."""
    provider = fake_support.provider(*turns)
    _, sink = fake_support.run(provider, tools if tools is not None else [])
    return sink


def test_the_fake_emits_one_usage_event_for_its_scripted_round() -> None:
    """Every runner, ledger, report and scorecard test drives the fake, so it pays too."""
    sink = fake_run(ScriptedTurn(text="done"))

    assert [body["round_index"] for body in usage_bodies(sink)] == [0]
    assert usage_bodies(sink)[0]["total_tokens"] == SYNTHETIC_USAGE.total_tokens


def test_the_fakes_usage_event_names_the_fake_and_its_model() -> None:
    sink = fake_run(ScriptedTurn(text="done"))

    body = usage_bodies(sink)[0]
    assert body["provider"] == "fake"
    assert body["model"] == "fake-scripted"


def test_a_turn_scripted_with_no_usage_emits_no_usage_event() -> None:
    """A round whose cost was not reported records nothing rather than a zero one."""
    sink = fake_run(ScriptedTurn(text="done", usage=None))

    assert usage_bodies(sink) == []
    assert "usage" not in sink.types


def test_the_fake_emits_usage_before_the_tools_of_that_round_run() -> None:
    """The response is in hand before any tool in the round is called, so the cost is
    on the stream before the local work that follows it can fail."""
    sink = fake_run(
        ScriptedTurn(text="done", tool_calls=(ScriptedToolCall(name="get_component"),)),
        tools=[fake_support.FakeTool(name="get_component")],
    )

    assert sink.types.index("usage") < sink.types.index("tool.started")


def test_the_fakes_round_index_restarts_at_zero_on_the_next_turn() -> None:
    """An adapter sees one turn; a session-level number is not one it could know."""
    provider = fake_support.provider(ScriptedTurn(text="one"), ScriptedTurn(text="two"))

    first = fake_support.Sink()
    second = fake_support.Sink()
    fake_support.run(provider, [], sink=first)
    fake_support.run(provider, [], sink=second)

    assert [body["round_index"] for body in usage_bodies(first)] == [0]
    assert [body["round_index"] for body in usage_bodies(second)] == [0]


# --- OpenAI -----------------------------------------------------------------------------


@respx.mock
def test_openai_emits_one_usage_event_per_round_trip_not_per_turn() -> None:
    """A turn with one tool call is two requests, so it is two usage events."""
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(function_call_item()), small_block())),
            stream_response(with_usage(completed(message_item("done")), small_block())),
        )
    )
    sink = OpenAISink()

    openai_run(
        provider_with(openai_clock()),
        tools=[OpenAITool(name="get_component")],
        sink=sink,
    )

    assert [body["round_index"] for body in usage_bodies(sink)] == [0, 1]
    assert sink.types.count("usage") == 2


@respx.mock
def test_openais_usage_event_carries_the_mapped_counts_unchanged() -> None:
    """The event is the mapping's own numbers; nothing is recomputed on the way out."""
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(message_item("done")), small_block())),
        )
    )
    provider = provider_with(openai_clock())
    sink = OpenAISink()

    openai_run(provider, sink=sink)

    body = one_usage(sink)
    recorded = provider.round_usage[0]
    assert {name: body[name] for name in COUNT_FIELDS} == {
        name: getattr(recorded, name) for name in COUNT_FIELDS
    }
    assert body["latency_s"] == recorded.latency_s
    assert body["provider"] == "openai"
    assert body["model"] == MODEL


@respx.mock
def test_openai_emits_usage_before_the_tool_calls_of_that_round() -> None:
    """Round one's cost is on the stream before the tool it asked for is even started."""
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(function_call_item()), small_block())),
            stream_response(with_usage(completed(message_item("done")), small_block())),
        )
    )
    sink = OpenAISink()

    openai_run(
        provider_with(openai_clock()), tools=[OpenAITool(name="get_component")], sink=sink
    )

    assert sink.types == [
        "usage",
        "tool.started",
        "tool.finished",
        "usage",
        "text.done",
    ]


@respx.mock
def test_an_openai_round_the_service_reported_nothing_for_still_emits_its_event() -> None:
    """The round happened and cost something; every count is null, which is not zero."""
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(message_item("done")), None)),
        )
    )
    sink = OpenAISink()

    openai_run(provider_with(openai_clock()), sink=sink)

    body = one_usage(sink)
    assert all(body[name] is None for name in COUNT_FIELDS)
    assert body["latency_s"] is not None


@respx.mock
def test_a_turn_that_fails_on_its_second_round_has_already_emitted_the_first() -> None:
    """The whole reason usage is an event: a `TurnResult` that never exists reports zero.

    The first round succeeded and was paid for. The second is a 503 the adapter raises
    out of the round loop on, so `run()` returns nothing at all - and the first round's
    cost is on the stream regardless.
    """
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(function_call_item()), small_block())),
            httpx.Response(503, json={"error": {"message": "overloaded"}}),
        )
    )
    sink = OpenAISink()

    with pytest.raises(OpenAIProviderError):
        openai_run(
            provider_with(openai_clock()), tools=[OpenAITool(name="get_component")], sink=sink
        )

    assert [body["round_index"] for body in usage_bodies(sink)] == [0]
    assert usage_bodies(sink)[0]["total_tokens"] == small_block()["total_tokens"]


@respx.mock
def test_openais_round_index_restarts_at_zero_on_the_next_turn() -> None:
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(message_item("one")), small_block())),
            stream_response(with_usage(completed(message_item("two")), small_block())),
        )
    )
    provider = provider_with(openai_clock())

    first = OpenAISink()
    second = OpenAISink()
    openai_run(provider, sink=first)
    openai_run(provider, sink=second)

    assert [body["round_index"] for body in usage_bodies(first)] == [0]
    assert [body["round_index"] for body in usage_bodies(second)] == [0]


# --- Gemini -----------------------------------------------------------------------------


def test_gemini_emits_one_usage_event_per_round_trip_not_per_turn() -> None:
    """A turn with one tool call is two streams, so it is two usage events."""
    adapter, _ = gemini_build(
        [
            chunk(call_part("call_1", "get_component", {"component_id": "C1"})),
            stop_chunk(synthetic.gemini_usage_metadata()),
        ],
        [
            chunk(text_part("done"), finish_reason=types.FinishReason.STOP),
            stop_chunk(synthetic.gemini_usage_metadata(candidates_token_count=96)),
        ],
    )
    sink = GeminiSink()

    gemini_run(adapter, [GeminiTool(name="get_component")], sink=sink)

    assert [body["round_index"] for body in usage_bodies(sink)] == [0, 1]
    assert [body["output_tokens"] for body in usage_bodies(sink)] == [
        synthetic.GEMINI_CANDIDATES_TOKENS,
        96,
    ]


def test_geminis_usage_event_carries_the_mapped_counts_unchanged() -> None:
    adapter, _ = gemini_build(
        [
            chunk(text_part("done"), finish_reason=types.FinishReason.STOP),
            stop_chunk(synthetic.gemini_usage_metadata()),
        ]
    )
    sink = GeminiSink()

    gemini_run(adapter, [], sink=sink)

    body = one_usage(sink)
    recorded = adapter.round_usage[0]
    assert {name: body[name] for name in COUNT_FIELDS} == {
        name: getattr(recorded, name) for name in COUNT_FIELDS
    }
    assert body["provider"] == "gemini"
    assert body["model"] == LEVEL_MODEL
    assert body["tool_result_input_tokens"] == synthetic.GEMINI_TOOL_USE_PROMPT_TOKENS


def test_a_gemini_turn_that_fails_on_its_second_round_has_already_emitted_the_first() -> None:
    """The same claim as OpenAI's, on the adapter that raises through `_report`."""
    adapter, _ = gemini_build(
        [
            chunk(call_part("call_1", "get_component", {"component_id": "C1"})),
            stop_chunk(synthetic.gemini_usage_metadata()),
        ],
        server_error(503, "model overloaded"),
    )
    sink = GeminiSink()

    with pytest.raises(GeminiServerError):
        gemini_run(adapter, [GeminiTool(name="get_component")], sink=sink)

    assert [body["round_index"] for body in usage_bodies(sink)] == [0]
    assert usage_bodies(sink)[0]["total_tokens"] == synthetic.GEMINI_TOTAL_TOKENS


def test_a_gemini_round_no_chunk_reported_usage_for_still_emits_its_event() -> None:
    adapter, _ = gemini_build([chunk(text_part("done"), finish_reason=types.FinishReason.STOP)])
    sink = GeminiSink()

    gemini_run(adapter, [], sink=sink)

    body = one_usage(sink)
    assert all(body[name] is None for name in COUNT_FIELDS)


def test_geminis_round_index_restarts_at_zero_on_the_next_turn() -> None:
    adapter, _ = gemini_build(
        [stop_chunk(synthetic.gemini_usage_metadata())],
        [stop_chunk(synthetic.gemini_usage_metadata())],
    )

    first = GeminiSink()
    second = GeminiSink()
    gemini_run(adapter, [], sink=first)
    gemini_run(adapter, [], sink=second)

    assert [body["round_index"] for body in usage_bodies(first)] == [0]
    assert [body["round_index"] for body in usage_bodies(second)] == [0]


# --- one body, three producers ------------------------------------------------------------


@respx.mock
def test_all_three_producers_build_the_same_body_shape() -> None:
    """One builder, so the event cannot become three shapes of itself (constitution V)."""
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(message_item("done")), small_block()))
        )
    )
    openai_sink = OpenAISink()
    openai_run(provider_with(openai_clock()), sink=openai_sink)

    adapter, _ = gemini_build(
        [
            chunk(text_part("done"), finish_reason=types.FinishReason.STOP),
            stop_chunk(synthetic.gemini_usage_metadata()),
        ]
    )
    gemini_sink = GeminiSink()
    gemini_run(adapter, [], sink=gemini_sink)

    shapes = [
        list(one_usage(openai_sink)),
        list(one_usage(gemini_sink)),
        list(usage_bodies(fake_run(ScriptedTurn(text="done")))[0]),
    ]
    assert shapes[0] == shapes[1] == shapes[2] == list(BODY_FIELDS)


def test_the_body_carries_every_token_usage_field_and_no_turn_number() -> None:
    """Turns are delimited by `turn.ended`, so the runner never enriches this event."""
    body = usage_body(SYNTHETIC_USAGE, round_index=0, provider="fake", model="fake-1")

    assert set(TokenUsage.model_fields) <= set(body)
    assert "turn" not in body
    assert "turn_index" not in body
    assert "step_index" not in body


def test_the_builder_copies_the_counts_across_without_deriving_anything() -> None:
    body = usage_body(SYNTHETIC_USAGE, round_index=3, provider="openai", model=MODEL)

    assert body["round_index"] == 3
    assert body["provider"] == "openai"
    assert body["model"] == MODEL
    assert {name: body[name] for name in COUNT_FIELDS} == {
        name: getattr(SYNTHETIC_USAGE, name) for name in COUNT_FIELDS
    }
    assert body["latency_s"] == SYNTHETIC_USAGE.latency_s


def test_cache_diagnostic_is_null_until_lever_three_lands() -> None:
    """It is requested only by setting `prompt_cache_options.comparison_response_id`,
    which nothing does yet, and it is null on Gemini and on the fake for ever."""
    assert (
        usage_body(SYNTHETIC_USAGE, round_index=0, provider="gemini", model="x")[
            "cache_diagnostic"
        ]
        is None
    )
