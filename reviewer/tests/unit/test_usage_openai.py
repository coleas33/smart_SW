"""The OpenAI adapter's usage mapping, and where it reads it (T006).

Two things are pinned here and they fail in different ways.

**The mapping** is asserted against payloads built through the installed SDK's own
`ResponseUsage.construct`, which is how the SDK itself builds a response, so a field that
moved or a sub-model that became optional fails here rather than on the wire. The case
worth the most is the one the contract calls the exact reproduction: a response whose
`cache_write_tokens` the endpoint omitted must map to `None` and never to `0`. `construct`
fills an omitted required field with its default and a required field's default is `None`
(VERIFIED, `openai/_models.py`), so the shape is real, and a mapping that reads it as zero
would report "the prefix was never written" for "the endpoint did not say".

**The capture point** is per round, not per turn. `run()` is a `while True` loop whose body
makes exactly one request, so a turn with one tool call is two requests and two records.
The clock these tests inject advances by a fixed step per reading, so each round's
`latency_s` is exactly one step whatever else in the turn also reads the clock.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import respx
from openai.types.responses import Response

from swreview.agent.providers import TokenUsage
from swreview.agent.providers.openai_provider import OpenAIProvider, usage_of
from tests.support import usage as synthetic
from tests.unit.test_openai_provider import (
    CEILING,
    MODEL,
    RESPONSES_URL,
    FakeTool,
    Sink,
    completed,
    function_call_item,
    incomplete,
    make_client,
    message_item,
    run,
    stream_response,
)

TICK = 1.5
"""Seconds every reading of the injected clock advances. One round is exactly one tick."""


def stepping_clock(step: float = TICK) -> Any:
    """A monotonic clock that advances `step` per reading, starting at zero.

    `call_tool` reads the clock twice per tool call, so a shared counter would make a
    round's latency depend on how many tools the round before it ran. A fixed step makes
    every round's measured latency exactly `step` regardless.
    """
    counter = iter(range(0, 10_000))

    def clock() -> float:
        return next(counter) * step

    return clock


def provider_with(clock: Any) -> OpenAIProvider:
    return OpenAIProvider(
        model=MODEL, max_output_tokens=CEILING, client=make_client(), clock=clock
    )


def usage_block(
    *,
    input_tokens: int,
    cached_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
) -> dict[str, Any]:
    """The `usage` object the Responses API puts on a terminal event's `response`."""
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
        },
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
        "total_tokens": input_tokens + output_tokens,
    }


def small_block() -> dict[str, Any]:
    """A reported round whose numbers are small enough to read at a glance."""
    return usage_block(
        input_tokens=100,
        cached_tokens=64,
        cache_write_tokens=8,
        output_tokens=10,
        reasoning_tokens=4,
    )


def with_usage(event: dict[str, Any], block: dict[str, Any] | None) -> dict[str, Any]:
    """The same terminal event, carrying a `usage` object (or carrying none)."""
    if block is not None:
        event["response"]["usage"] = block
    return event


def responses(*bodies: Any) -> Iterator[Any]:
    """One recorded reply per round, in order."""
    return iter(bodies)


# --- the mapping ------------------------------------------------------------------------


def test_every_reported_field_maps_to_its_token_usage_field() -> None:
    """The seven-column mapping of contracts/usage.md section 3, OpenAI column."""
    response = Response.construct(usage=synthetic.openai_usage())

    mapped = usage_of(response, latency_s=4.31)

    assert mapped == TokenUsage(
        input_tokens=synthetic.OPENAI_INPUT_TOKENS,
        cached_input_tokens=synthetic.OPENAI_CACHED_TOKENS,
        cache_write_tokens=synthetic.OPENAI_CACHE_WRITE_TOKENS,
        output_tokens=synthetic.OPENAI_OUTPUT_TOKENS,
        reasoning_tokens=synthetic.OPENAI_REASONING_TOKENS,
        tool_result_input_tokens=None,
        total_tokens=synthetic.OPENAI_TOTAL_TOKENS,
        latency_s=4.31,
    )


def test_tool_result_input_tokens_is_none_because_openai_does_not_report_it() -> None:
    """Those tokens are real and are already inside `input_tokens`; they are not a zero.

    Gemini reports them separately as `tool_use_prompt_token_count`. Writing `0` here
    would make the two providers look comparable on a column only one of them has.
    """
    mapped = usage_of(Response.construct(usage=synthetic.openai_usage()), latency_s=1.0)

    assert mapped.tool_result_input_tokens is None


def test_an_omitted_cache_write_count_stays_none_and_is_never_read_as_zero() -> None:
    """The exact reproduction: `construct` leaves an omitted required field at `None`."""
    response = Response.construct(usage=synthetic.openai_usage_without_cache_write())

    mapped = usage_of(response, latency_s=0.5)

    assert mapped.cache_write_tokens is None
    assert mapped.cached_input_tokens == 64
    assert mapped.input_tokens == 100
    assert mapped.output_tokens == 10
    assert mapped.reasoning_tokens == 4
    assert mapped.total_tokens == 110


def test_a_response_with_no_usage_at_all_maps_to_every_count_none() -> None:
    """`Response.usage` is `Optional[ResponseUsage]`, so this is a shape that arrives."""
    mapped = usage_of(Response.construct(), latency_s=2.0)

    assert mapped == TokenUsage(
        input_tokens=None,
        cached_input_tokens=None,
        cache_write_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        tool_result_input_tokens=None,
        total_tokens=None,
        latency_s=2.0,
    )


def test_absent_detail_sub_models_do_not_raise() -> None:
    """`input_tokens_details` can itself be `None`, so sub-fields are read with getattr.

    Attribute access would raise `AttributeError` here and lose a round we paid for on
    the way to reporting a sub-count we never had.
    """
    from openai.types.responses.response_usage import ResponseUsage

    bare = ResponseUsage.construct(input_tokens=90, output_tokens=8, total_tokens=98)
    assert bare.input_tokens_details is None
    assert bare.output_tokens_details is None

    mapped = usage_of(Response.construct(usage=bare), latency_s=0.25)

    assert mapped.input_tokens == 90
    assert mapped.output_tokens == 8
    assert mapped.total_tokens == 98
    assert mapped.cached_input_tokens is None
    assert mapped.cache_write_tokens is None
    assert mapped.reasoning_tokens is None


def test_latency_is_carried_through_unchanged_and_is_never_null() -> None:
    """We made the call, so we timed it: `latency_s` has no null case."""
    mapped = usage_of(Response.construct(), latency_s=0.0)

    assert mapped.latency_s == 0.0


# --- the capture point ------------------------------------------------------------------


@respx.mock
def test_one_record_per_round_trip_not_per_turn() -> None:
    """A turn with one tool call is two requests, so it is two usage records."""
    first = usage_block(
        input_tokens=12_043,
        cached_tokens=10_240,
        cache_write_tokens=1_803,
        output_tokens=512,
        reasoning_tokens=448,
    )
    second = usage_block(
        input_tokens=13_117,
        cached_tokens=12_043,
        cache_write_tokens=1_074,
        output_tokens=96,
        reasoning_tokens=32,
    )
    route = respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(function_call_item()), first)),
            stream_response(with_usage(completed(message_item("done")), second)),
        )
    )
    provider = provider_with(stepping_clock())

    run(provider, tools=[FakeTool(name="get_component")], sink=Sink())

    assert len(route.calls) == 2
    assert [one.input_tokens for one in provider.round_usage] == [12_043, 13_117]
    assert [one.cached_input_tokens for one in provider.round_usage] == [10_240, 12_043]
    assert [one.output_tokens for one in provider.round_usage] == [512, 96]
    assert [one.uncached_input_tokens for one in provider.round_usage] == [1_803, 1_074]


@respx.mock
def test_latency_is_measured_around_the_request_and_not_around_the_turn() -> None:
    """Each round's latency is one clock step; the tool call between them is outside it."""
    block = small_block()
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(function_call_item()), block)),
            stream_response(with_usage(completed(message_item("done")), block)),
        )
    )
    provider = provider_with(stepping_clock())

    run(provider, tools=[FakeTool(name="get_component")], sink=Sink())

    assert [one.latency_s for one in provider.round_usage] == [TICK, TICK]


@respx.mock
def test_a_round_the_provider_did_not_report_usage_for_is_still_recorded() -> None:
    """The round happened and cost something; what it cost is unknown, which is not zero."""
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(message_item("done")), None)),
        )
    )
    provider = provider_with(stepping_clock())

    run(provider, sink=Sink())

    assert len(provider.round_usage) == 1
    assert provider.round_usage[0].total_tokens is None
    assert provider.round_usage[0].latency_s == TICK


@respx.mock
def test_a_round_that_hit_the_output_ceiling_is_recorded_before_the_turn_is_cut_short() -> None:
    """The truncated round is the expensive one; dropping it hides the cost of the failure."""
    block = usage_block(
        input_tokens=12_043,
        cached_tokens=10_240,
        cache_write_tokens=1_803,
        output_tokens=CEILING,
        reasoning_tokens=CEILING - 12,
    )
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(incomplete(message_item("cut off")), block)),
        )
    )
    provider = provider_with(stepping_clock())

    result, _ = run(provider, sink=Sink())

    assert result.reason == "truncated"
    assert [one.output_tokens for one in provider.round_usage] == [CEILING]


@respx.mock
def test_the_record_is_this_turns_rounds_only() -> None:
    """An adapter sees one turn, which is the convention `step_index` already follows."""
    block = small_block()
    respx.post(RESPONSES_URL).mock(
        side_effect=responses(
            stream_response(with_usage(completed(message_item("one")), block)),
            stream_response(with_usage(completed(message_item("two")), block)),
        )
    )
    provider = provider_with(stepping_clock())

    run(provider, sink=Sink())
    run(provider, sink=Sink())

    assert len(provider.round_usage) == 1


def test_a_fresh_adapter_has_recorded_nothing() -> None:
    assert provider_with(stepping_clock()).round_usage == []


@pytest.mark.parametrize("field", ["input_tokens", "cached_input_tokens", "total_tokens"])
def test_a_reported_zero_is_kept_as_zero(field: str) -> None:
    """Zero and unknown are different answers, in both directions."""
    from openai.types.responses.response_usage import ResponseUsage

    zeroed = ResponseUsage.construct(
        input_tokens=0,
        input_tokens_details={"cached_tokens": 0, "cache_write_tokens": 0},
        output_tokens=0,
        output_tokens_details={"reasoning_tokens": 0},
        total_tokens=0,
    )

    mapped = usage_of(Response.construct(usage=zeroed), latency_s=0.1)

    assert getattr(mapped, field) == 0
