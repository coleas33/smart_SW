"""Synthetic provider usage payloads, built the way the two SDKs build them.

One place, because three suites read the same shapes: the OpenAI adapter's mapping test,
the Gemini adapter's mapping test, and the ledger and report tests downstream of them. A
payload invented separately in each would let a mapping that misreads the SDK pass
everywhere.

Two things every builder here holds to, both of them Principle I:

- **The numbers are not round.** An accidental zero, a silently dropped field or a total
  computed by adding the wrong two sub-counts is visible against 9,871 and invisible
  against 10,000.
- **The omitted field stays omitted.** `openai_usage_without_cache_write` goes through
  `ResponseUsage.construct` exactly as the SDK does, so the field it leaves out is `None`
  and not zero. That is the case the mapping must not coerce.

The arithmetic each provider documents is preserved, because a builder whose numbers do
not add up lets a mapping that double counts look correct:

- OpenAI: `cached_tokens` is inside `input_tokens`, `reasoning_tokens` is inside
  `output_tokens`, and `total_tokens` is `input + output`.
- Gemini: `cached_content_token_count` is **inside** `prompt_token_count`, while
  `tool_use_prompt_token_count` is **outside** it and `total_token_count` is the sum of
  prompt, candidates, tool-use prompt and thoughts (VERIFIED, `google/genai/types.py`).
"""

from __future__ import annotations

from google.genai import types
from openai.types.responses.response_usage import ResponseUsage

# --- OpenAI ---------------------------------------------------------------------------

OPENAI_INPUT_TOKENS = 12_043
OPENAI_CACHED_TOKENS = 10_240
OPENAI_CACHE_WRITE_TOKENS = 1_803
OPENAI_OUTPUT_TOKENS = 512
OPENAI_REASONING_TOKENS = 448
OPENAI_TOTAL_TOKENS = OPENAI_INPUT_TOKENS + OPENAI_OUTPUT_TOKENS
"""The round trip contracts/usage.md section 5 uses as its worked example."""


def openai_usage(
    *,
    input_tokens: int = OPENAI_INPUT_TOKENS,
    cached_tokens: int = OPENAI_CACHED_TOKENS,
    cache_write_tokens: int = OPENAI_CACHE_WRITE_TOKENS,
    output_tokens: int = OPENAI_OUTPUT_TOKENS,
    reasoning_tokens: int = OPENAI_REASONING_TOKENS,
) -> ResponseUsage:
    """A fully reported `Response.usage`, built through `construct` as the SDK does."""
    return ResponseUsage.construct(
        input_tokens=input_tokens,
        input_tokens_details={
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
        },
        output_tokens=output_tokens,
        output_tokens_details={"reasoning_tokens": reasoning_tokens},
        total_tokens=input_tokens + output_tokens,
    )


def openai_usage_without_cache_write() -> ResponseUsage:
    """The endpoint that does not report `cache_write_tokens`, which VERIFIED happens.

    The exact reproduction from contracts/usage.md section 1: `cache_write_tokens` is
    annotated `int` with no default, `construct` fills an omitted field with the field
    default, and a required field's default is `None`. The mapping must read `None`.
    """
    return ResponseUsage.construct(
        input_tokens=100,
        input_tokens_details={"cached_tokens": 64},
        output_tokens=10,
        output_tokens_details={"reasoning_tokens": 4},
        total_tokens=110,
    )


# --- Gemini ---------------------------------------------------------------------------

GEMINI_PROMPT_TOKENS = 9_871
GEMINI_CACHED_CONTENT_TOKENS = 7_680
GEMINI_CANDIDATES_TOKENS = 431
GEMINI_THOUGHTS_TOKENS = 288
GEMINI_TOOL_USE_PROMPT_TOKENS = 1_204
GEMINI_TOTAL_TOKENS = (
    GEMINI_PROMPT_TOKENS
    + GEMINI_CANDIDATES_TOKENS
    + GEMINI_TOOL_USE_PROMPT_TOKENS
    + GEMINI_THOUGHTS_TOKENS
)
"""The total as Gemini documents it: cached is not added, tool-use prompt is."""


def gemini_usage_metadata(
    *,
    candidates_token_count: int = GEMINI_CANDIDATES_TOKENS,
    thoughts_token_count: int = GEMINI_THOUGHTS_TOKENS,
) -> types.GenerateContentResponseUsageMetadata:
    """A fully reported `usage_metadata`, with the total recomputed from its addends.

    Only the two growing counts are arguments: the prompt, its cached part and the
    tool-result input are fixed for a round, which is what makes a growing stream's
    intermediate chunks differ from its last one in exactly the way a real one does.
    """
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=GEMINI_PROMPT_TOKENS,
        cached_content_token_count=GEMINI_CACHED_CONTENT_TOKENS,
        candidates_token_count=candidates_token_count,
        thoughts_token_count=thoughts_token_count,
        tool_use_prompt_token_count=GEMINI_TOOL_USE_PROMPT_TOKENS,
        total_token_count=(
            GEMINI_PROMPT_TOKENS
            + candidates_token_count
            + GEMINI_TOOL_USE_PROMPT_TOKENS
            + thoughts_token_count
        ),
    )


def gemini_usage_metadata_all_none() -> types.GenerateContentResponseUsageMetadata:
    """Every field left unset. Must map to an all-`None` `TokenUsage`, never to zeroes."""
    return types.GenerateContentResponseUsageMetadata()


def _text_chunk(
    text: str,
    *,
    finish_reason: types.FinishReason | None = None,
    usage_metadata: types.GenerateContentResponseUsageMetadata | None = None,
) -> types.GenerateContentResponse:
    """One streamed chunk with a candidate, shaped like `test_gemini_provider.chunk`."""
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=finish_reason,
            )
        ],
        usage_metadata=usage_metadata,
    )


def gemini_chunks_usage_on_a_candidateless_final_chunk() -> list[types.GenerateContentResponse]:
    """Usage arrives alone, after the last candidate.

    This is the sequence `_stream` drops today: its loop body is
    `for candidate in chunk.candidates or []`, which never runs for this final chunk, so
    an adapter that reads `usage_metadata` inside that loop records nothing at all.
    """
    return [
        _text_chunk("The lower bracket "),
        _text_chunk("interferes.", finish_reason=types.FinishReason.STOP),
        types.GenerateContentResponse(usage_metadata=gemini_usage_metadata()),
    ]


def gemini_chunks_usage_on_the_last_chunk_only() -> list[types.GenerateContentResponse]:
    """Usage arrives once, on the same chunk that carries the finish reason."""
    return [
        _text_chunk("The lower bracket "),
        _text_chunk(
            "interferes.",
            finish_reason=types.FinishReason.STOP,
            usage_metadata=gemini_usage_metadata(),
        ),
    ]


_GROWING_COUNTS: tuple[tuple[int, int], ...] = (
    (144, 96),
    (302, 288),
    (GEMINI_CANDIDATES_TOKENS, GEMINI_THOUGHTS_TOKENS),
)
"""(candidates, thoughts) per chunk. The last pair is the full round, so all three
sequences end on the same `usage_metadata` and "last chunk wins" is one expectation."""


def gemini_chunks_usage_on_every_chunk() -> list[types.GenerateContentResponse]:
    """Cumulative usage on every chunk, growing to the same final total.

    Whether the service actually streams cumulative totals or per-chunk deltas is
    UNVERIFIED (probe G3). This sequence is the cumulative reading, which is the one
    "last chunk that carries usage wins" is correct under.
    """
    texts = ("The lower bracket ", "interferes with ", "the motor mount.")
    reasons = (None, None, types.FinishReason.STOP)
    return [
        _text_chunk(
            text,
            finish_reason=reason,
            usage_metadata=gemini_usage_metadata(
                candidates_token_count=candidates, thoughts_token_count=thoughts
            ),
        )
        for text, reason, (candidates, thoughts) in zip(
            texts, reasons, _GROWING_COUNTS, strict=True
        )
    ]
