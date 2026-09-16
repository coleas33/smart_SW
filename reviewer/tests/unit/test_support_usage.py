"""The synthetic usage payloads are the shape the adapters will actually be handed.

`tests/support/usage.py` is the one place a fake `Response.usage` or a fake Gemini chunk
sequence is built, so the two adapter test modules assert a mapping rather than each
inventing a payload. A builder that drifted from the SDK would make both adapter suites
pass against a shape no provider ever sends, which is exactly the failure this module is
here to catch: it checks the builders against the installed SDKs' own types.
"""

from __future__ import annotations

from google.genai import types
from openai.types.responses.response_usage import ResponseUsage

from tests.support import usage


def test_openai_usage_carries_every_field_the_mapping_reads() -> None:
    """The five OpenAI numbers, two of them nested, as `usage_of` will read them."""
    built = usage.openai_usage()
    assert isinstance(built, ResponseUsage)
    assert built.input_tokens == usage.OPENAI_INPUT_TOKENS
    assert built.input_tokens_details.cached_tokens == usage.OPENAI_CACHED_TOKENS
    assert built.input_tokens_details.cache_write_tokens == usage.OPENAI_CACHE_WRITE_TOKENS
    assert built.output_tokens == usage.OPENAI_OUTPUT_TOKENS
    assert built.output_tokens_details.reasoning_tokens == usage.OPENAI_REASONING_TOKENS
    assert built.total_tokens == usage.OPENAI_TOTAL_TOKENS


def test_openai_usage_nests_the_way_the_provider_does() -> None:
    """Cached is inside input and reasoning is inside output, so neither is ever added."""
    built = usage.openai_usage()
    assert built.input_tokens_details.cached_tokens <= built.input_tokens
    assert built.output_tokens_details.reasoning_tokens <= built.output_tokens
    assert built.total_tokens == built.input_tokens + built.output_tokens


def test_openai_usage_without_cache_write_leaves_it_none_not_zero() -> None:
    """The omitted-field case, verbatim from contracts/usage.md section 1.

    `InputTokensDetails.cache_write_tokens` is annotated `int` with no default, and the
    SDK builds response models with `construct`, which fills an omitted required field
    with its default - `None`. An endpoint that does not report the field therefore hands
    us `None`, and the mapping must carry that through instead of reading it as zero.
    """
    built = usage.openai_usage_without_cache_write()
    assert built.input_tokens_details.cache_write_tokens is None
    assert built.input_tokens_details.cached_tokens == 64
    assert built.input_tokens == 100
    assert built.output_tokens_details.reasoning_tokens == 4
    assert built.total_tokens == 110


def test_gemini_usage_metadata_carries_every_field_the_mapping_reads() -> None:
    """The six Gemini numbers, all flat, all `Optional[int]` by declaration."""
    built = usage.gemini_usage_metadata()
    assert isinstance(built, types.GenerateContentResponseUsageMetadata)
    assert built.prompt_token_count == usage.GEMINI_PROMPT_TOKENS
    assert built.cached_content_token_count == usage.GEMINI_CACHED_CONTENT_TOKENS
    assert built.candidates_token_count == usage.GEMINI_CANDIDATES_TOKENS
    assert built.thoughts_token_count == usage.GEMINI_THOUGHTS_TOKENS
    assert built.tool_use_prompt_token_count == usage.GEMINI_TOOL_USE_PROMPT_TOKENS
    assert built.total_token_count == usage.GEMINI_TOTAL_TOKENS


def test_gemini_usage_metadata_obeys_the_two_opposite_nesting_facts() -> None:
    """Cached is inside the prompt; tool-use input is outside it and a separate addend.

    Both VERIFIED from the package's own field descriptions (`types.py:8468-8471` and
    `:8488-8491`). A builder whose numbers did not add up this way would let a mapping
    that double counted the cache still look right.
    """
    built = usage.gemini_usage_metadata()
    assert built.cached_content_token_count < built.prompt_token_count
    assert built.total_token_count == (
        built.prompt_token_count
        + built.candidates_token_count
        + built.tool_use_prompt_token_count
        + built.thoughts_token_count
    )


def test_gemini_usage_metadata_all_none_reports_nothing_rather_than_zero() -> None:
    """Every field `None`: the case that must map to an all-`None` `TokenUsage`."""
    built = usage.gemini_usage_metadata_all_none()
    assert built.prompt_token_count is None
    assert built.cached_content_token_count is None
    assert built.candidates_token_count is None
    assert built.thoughts_token_count is None
    assert built.tool_use_prompt_token_count is None
    assert built.total_token_count is None


def test_the_candidateless_final_chunk_is_the_one_todays_loop_would_drop() -> None:
    """A last chunk with usage and no candidates: `for candidate in chunk.candidates or []`
    never runs for it, so an adapter that reads usage inside that loop records nothing."""
    chunks = usage.gemini_chunks_usage_on_a_candidateless_final_chunk()
    assert all(isinstance(chunk, types.GenerateContentResponse) for chunk in chunks)
    assert not chunks[-1].candidates
    assert chunks[-1].usage_metadata is not None
    assert [chunk.usage_metadata is not None for chunk in chunks[:-1]] == [False] * (
        len(chunks) - 1
    )


def test_the_last_chunk_only_sequence_carries_usage_once_beside_a_candidate() -> None:
    """Usage arrives on the final chunk, which also carries the finish reason."""
    chunks = usage.gemini_chunks_usage_on_the_last_chunk_only()
    carrying = [index for index, chunk in enumerate(chunks) if chunk.usage_metadata is not None]
    assert carrying == [len(chunks) - 1]
    assert chunks[-1].candidates


def test_the_every_chunk_sequence_grows_and_ends_on_the_same_total() -> None:
    """Cumulative usage on every chunk. Last one wins, and the last one is the full bill."""
    chunks = usage.gemini_chunks_usage_on_every_chunk()
    totals = [chunk.usage_metadata.total_token_count for chunk in chunks]
    assert all(usage_metadata is not None for usage_metadata in (c.usage_metadata for c in chunks))
    assert totals == sorted(totals)
    assert len(set(totals)) == len(totals)


def test_all_three_sequences_end_on_the_same_usage() -> None:
    """The point of having three: "last chunk that carries usage wins" is one expectation.

    Whatever the service does with intermediate chunks, the adapter must land on the same
    `TokenUsage` for all three, so one assertion covers all three in the adapter suite.
    """
    sequences = [
        usage.gemini_chunks_usage_on_a_candidateless_final_chunk(),
        usage.gemini_chunks_usage_on_the_last_chunk_only(),
        usage.gemini_chunks_usage_on_every_chunk(),
    ]
    finals = [chunk.usage_metadata for sequence in sequences for chunk in sequence[-1:]]
    assert all(final == usage.gemini_usage_metadata() for final in finals)


def test_each_sequence_is_rebuilt_per_call() -> None:
    """A stream is consumed once; a shared list would make the second test see an empty one."""
    first = usage.gemini_chunks_usage_on_every_chunk()
    second = usage.gemini_chunks_usage_on_every_chunk()
    assert first is not second
    assert first[0] is not second[0]
