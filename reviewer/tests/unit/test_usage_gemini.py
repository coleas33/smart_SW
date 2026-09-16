"""The Gemini adapter's usage mapping, and where in the stream it reads it (T008).

Two arithmetic facts run in opposite directions and a mapping that gets either wrong looks
perfectly plausible. Both are VERIFIED from the installed package's own field descriptions:

- `cached_content_token_count` is **inside** `prompt_token_count` (`types.py:8468-8471`,
  "When `cached_content` is set, this also includes the number of tokens in the cached
  content"), so adding the two double counts the cached prefix.
- `tool_use_prompt_token_count` is **outside** `prompt_token_count` and is a separate
  addend of `total_token_count` (`types.py:8488-8491`), so dropping it understates our
  input cost by whatever sixty-odd tool results weigh - and our reviewer feeds every tool
  result back as input, which makes it a first-class number rather than a rounding error.

The mapping therefore copies the provider's fields across and derives nothing. The tests
below assert exactly that: `input_tokens` equals `prompt_token_count` on the nose, and
`total_tokens` is the provider's own total rather than a sum this code computed.

The other half is **where** the usage is read. The stream's usage can arrive on a chunk
that carries no candidate at all, and the adapter's loop body runs per candidate, so a
read inside that loop silently drops the whole round's cost. It is read outside, last
chunk that carries usage wins - correct under both "cumulative" and "only the final chunk
carries it", and settled against "each chunk is a delta" by probe G3.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from google.genai import types

from swreview.agent.providers import TokenUsage
from swreview.agent.providers.gemini_provider import GeminiProvider, usage_of
from tests.support import usage as synthetic
from tests.unit.test_gemini_provider import (
    LEVEL_MODEL,
    SECRET,
    FakeTool,
    Sink,
    StubClient,
    StubModels,
    call_part,
    chunk,
    run,
    text_part,
)

TICK = 0.75
"""Seconds every reading of the injected clock advances. One round is exactly one tick."""


def stepping_clock(step: float = TICK) -> Callable[[], float]:
    """A monotonic clock advancing `step` per reading, so a round's latency is one step.

    `call_tool` also reads the clock, twice per tool call, so a counter shared with the
    rounds would make a round's latency depend on how many calls the round before it made.
    """
    counter = iter(range(0, 10_000))

    def clock() -> float:
        return next(counter) * step

    return clock


def build(*rounds: Any, clock: Callable[[], float] | None = None) -> tuple[GeminiProvider, Any]:
    """The adapter over a scripted stream, with a clock a latency assertion can read."""
    models = StubModels(rounds=list(rounds))
    adapter = GeminiProvider(
        client=StubClient(models=models),
        model=LEVEL_MODEL,
        secrets=[SECRET],
        clock=clock if clock is not None else stepping_clock(),
    )
    return adapter, models


def stop_chunk(
    usage_metadata: types.GenerateContentResponseUsageMetadata | None = None,
) -> types.GenerateContentResponse:
    """A last chunk: a finish reason, no content, and optionally the round's usage."""
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=None, finish_reason=types.FinishReason.STOP)],
        usage_metadata=usage_metadata,
    )


# --- the mapping --------------------------------------------------------------------------


def test_every_reported_field_maps_to_its_token_usage_field() -> None:
    """The seven-column mapping of contracts/usage.md section 3, Gemini column."""
    mapped = usage_of(synthetic.gemini_usage_metadata(), latency_s=2.5)

    assert mapped == TokenUsage(
        input_tokens=synthetic.GEMINI_PROMPT_TOKENS,
        cached_input_tokens=synthetic.GEMINI_CACHED_CONTENT_TOKENS,
        cache_write_tokens=None,
        output_tokens=synthetic.GEMINI_CANDIDATES_TOKENS,
        reasoning_tokens=synthetic.GEMINI_THOUGHTS_TOKENS,
        tool_result_input_tokens=synthetic.GEMINI_TOOL_USE_PROMPT_TOKENS,
        total_tokens=synthetic.GEMINI_TOTAL_TOKENS,
        latency_s=2.5,
    )


def test_cache_write_tokens_is_none_because_gemini_does_not_report_it() -> None:
    """Gemini has no cache-write count. `0` would claim it wrote nothing to the cache."""
    assert usage_of(synthetic.gemini_usage_metadata(), latency_s=1.0).cache_write_tokens is None


def test_cached_input_is_not_added_to_input_because_it_is_already_inside_it() -> None:
    """Fact 1: `cached_content_token_count` is contained in `prompt_token_count`.

    `input_tokens` is therefore the prompt count on the nose. A mapping that summed the
    two would report an input of 17,551 for a prompt of 9,871 and every derived figure -
    cached share, uncached input, cost - would be wrong in the same direction.
    """
    metadata = synthetic.gemini_usage_metadata()

    mapped = usage_of(metadata, latency_s=1.0)

    assert mapped.input_tokens == metadata.prompt_token_count
    assert mapped.cached_input_tokens is not None
    assert mapped.cached_input_tokens < mapped.input_tokens
    assert mapped.uncached_input_tokens == (
        synthetic.GEMINI_PROMPT_TOKENS - synthetic.GEMINI_CACHED_CONTENT_TOKENS
    )


def test_tool_result_input_is_kept_separate_because_it_is_outside_the_prompt_count() -> None:
    """Fact 2: `tool_use_prompt_token_count` is a separate addend of the total.

    It is not folded into `input_tokens`, because `total_token_count` already counts it
    once; folding it in and keeping the provider's total would make the parts stop adding
    up to the whole, and dropping it would understate what our tool results cost.
    """
    metadata = synthetic.gemini_usage_metadata()

    mapped = usage_of(metadata, latency_s=1.0)

    assert mapped.tool_result_input_tokens == metadata.tool_use_prompt_token_count
    assert mapped.input_tokens == metadata.prompt_token_count
    assert mapped.total_tokens == (
        mapped.input_tokens
        + mapped.output_tokens
        + mapped.tool_result_input_tokens
        + mapped.reasoning_tokens
    )


def test_the_total_is_the_providers_own_number_and_is_not_recomputed() -> None:
    """A total this code derived would hide a provider whose parts stopped adding up."""
    metadata = synthetic.gemini_usage_metadata()
    metadata.total_token_count = 1
    assert usage_of(metadata, latency_s=1.0).total_tokens == 1


def test_an_all_none_usage_metadata_maps_to_every_count_none_and_never_to_zero() -> None:
    """Every field is `Optional[int] = None` by declaration, so this shape is reachable."""
    mapped = usage_of(synthetic.gemini_usage_metadata_all_none(), latency_s=3.0)

    assert mapped == TokenUsage(
        input_tokens=None,
        cached_input_tokens=None,
        cache_write_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        tool_result_input_tokens=None,
        total_tokens=None,
        latency_s=3.0,
    )


def test_no_usage_metadata_at_all_maps_to_every_count_none() -> None:
    """A stream where no chunk carried usage: unknown, which is not zero."""
    mapped = usage_of(None, latency_s=0.5)

    assert mapped.total_tokens is None
    assert mapped.input_tokens is None
    assert mapped.latency_s == 0.5


@pytest.mark.parametrize(
    "field", ["input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"]
)
def test_a_reported_zero_is_kept_as_zero(field: str) -> None:
    """Zero and unknown are different answers, in both directions."""
    metadata = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=0,
        cached_content_token_count=0,
        candidates_token_count=0,
        thoughts_token_count=0,
        tool_use_prompt_token_count=0,
        total_token_count=0,
    )

    assert getattr(usage_of(metadata, latency_s=0.1), field) == 0


# --- where the stream is read -------------------------------------------------------------


def test_usage_on_a_final_chunk_with_no_candidates_is_recorded() -> None:
    """The case a read inside the candidates loop drops in full.

    `_stream`'s loop body is `for candidate in chunk.candidates or []`, which never runs
    for a chunk that carries only usage, so reading usage there would record nothing at
    all for a round we paid for. This is the sequence the service actually sends.
    """
    adapter, _ = build(synthetic.gemini_chunks_usage_on_a_candidateless_final_chunk())

    run(adapter, [])

    assert [one.total_tokens for one in adapter.round_usage] == [synthetic.GEMINI_TOTAL_TOKENS]
    assert adapter.round_usage[0].input_tokens == synthetic.GEMINI_PROMPT_TOKENS


@pytest.mark.parametrize(
    "sequence",
    [
        synthetic.gemini_chunks_usage_on_a_candidateless_final_chunk,
        synthetic.gemini_chunks_usage_on_the_last_chunk_only,
        synthetic.gemini_chunks_usage_on_every_chunk,
    ],
    ids=["candidateless-final", "last-chunk-only", "every-chunk"],
)
def test_the_last_chunk_that_carries_usage_wins(
    sequence: Callable[[], list[types.GenerateContentResponse]],
) -> None:
    """All three arrival patterns end on the same round, so all three record the same cost.

    A first-chunk-wins rule would record 144 output tokens for the growing sequence and a
    per-chunk sum would record 877 for a round that produced 431.
    """
    adapter, _ = build(sequence())

    run(adapter, [])

    assert adapter.round_usage[0].output_tokens == synthetic.GEMINI_CANDIDATES_TOKENS
    assert adapter.round_usage[0].reasoning_tokens == synthetic.GEMINI_THOUGHTS_TOKENS
    assert adapter.round_usage[0].total_tokens == synthetic.GEMINI_TOTAL_TOKENS


def test_a_later_chunk_with_no_usage_does_not_erase_the_usage_already_seen() -> None:
    """"Last one wins" is last chunk that *carries* usage, not last chunk."""
    adapter, _ = build(
        [
            chunk(text_part("the bracket ")),
            types.GenerateContentResponse(usage_metadata=synthetic.gemini_usage_metadata()),
            stop_chunk(),
        ]
    )

    run(adapter, [])

    assert adapter.round_usage[0].total_tokens == synthetic.GEMINI_TOTAL_TOKENS


def test_the_round_carries_the_raw_usage_metadata_the_sdk_sent() -> None:
    """`_Round.usage` is the provider's own object; the mapping happens once, above it."""
    from swreview.agent.providers.gemini_provider import _Round

    adapter, _ = build(synthetic.gemini_chunks_usage_on_the_last_chunk_only())
    round_ = adapter._stream(  # the seam T009 adds is exactly what is under test here
        [types.Content(role="user", parts=[types.Part(text="review it")])],
        types.GenerateContentConfig(),
        Sink(),
    )

    assert isinstance(round_, _Round)
    assert isinstance(round_.usage, types.GenerateContentResponseUsageMetadata)
    assert round_.usage.prompt_token_count == synthetic.GEMINI_PROMPT_TOKENS


def test_a_round_no_chunk_reported_usage_for_is_still_recorded() -> None:
    """The round happened and cost something; what it cost is unknown, which is not zero."""
    adapter, _ = build([chunk(text_part("done"), finish_reason=types.FinishReason.STOP)])

    run(adapter, [])

    assert len(adapter.round_usage) == 1
    assert adapter.round_usage[0].total_tokens is None
    assert adapter.round_usage[0].latency_s == TICK


def test_one_record_per_round_trip_not_per_turn() -> None:
    """A turn with one tool call is two streams, so it is two usage records."""
    second = synthetic.gemini_usage_metadata(candidates_token_count=96, thoughts_token_count=12)
    adapter, models = build(
        [
            chunk(call_part("call_1", "get_component", {"component_id": "C1"})),
            stop_chunk(synthetic.gemini_usage_metadata()),
        ],
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP), stop_chunk(second)],
    )

    run(adapter, [FakeTool(name="get_component")])

    assert len(models.calls) == 2
    assert [one.output_tokens for one in adapter.round_usage] == [
        synthetic.GEMINI_CANDIDATES_TOKENS,
        96,
    ]
    assert [one.latency_s for one in adapter.round_usage] == [TICK, TICK]


def test_the_record_is_this_turns_rounds_only() -> None:
    """An adapter sees one turn, which is the convention `step_index` already follows."""
    adapter, _ = build(
        [stop_chunk(synthetic.gemini_usage_metadata())],
        [stop_chunk(synthetic.gemini_usage_metadata())],
    )

    run(adapter, [])
    run(adapter, [])

    assert len(adapter.round_usage) == 1


def test_a_fresh_adapter_has_recorded_nothing() -> None:
    adapter, _ = build()
    assert adapter.round_usage == []
