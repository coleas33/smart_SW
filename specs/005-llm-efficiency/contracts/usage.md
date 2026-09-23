# Contract: token usage

What a model round trip cost, as both SDKs actually report it, carried from the adapter to the
event stream, the session, the report and the scorecard. **Additive everywhere.** A session
written before this feature has no usage, loads unchanged, and renders a byte-identical
`report.md`.

This layer carries **no flag**. Recording what a run cost is not an experiment.

## 1. The rule that decides every type here

**Unknown stays unknown** (Principle I).

VERIFIED against the installed package:

```
python -c "from openai.types.responses.response_usage import ResponseUsage; \
u = ResponseUsage.construct(input_tokens=100, input_tokens_details={'cached_tokens':64}, \
  output_tokens=10, output_tokens_details={'reasoning_tokens':4}, total_tokens=110); \
print(u.input_tokens_details.cache_write_tokens)"
-> None
```

`InputTokensDetails.cache_write_tokens` is annotated `int` with no default (VERIFIED,
`openai/types/responses/response_usage.py`), and the SDK builds response models with
`BaseModel.construct` (VERIFIED, `openai/_models.py:231-259`), which sets any field the server
omitted to the field default; a required field's default is `None`. `cache_write_tokens` is new,
and an endpoint or model that does not report it yields `None`.

Gemini is the same by declaration rather than by construction: every field of
`GenerateContentResponseUsageMetadata` is `Optional[int] = None` (VERIFIED,
`google/genai/types.py:8445-8496`).

Three consequences, each of which is a test:

1. **Every token field is `int | None`.** A reader typed `int` raises `TypeError` on the first
   sum. A reader that coerces `None` to `0` reports "zero cached tokens" for "the endpoint did not
   say", which is the Principle I violation this whole contract exists to prevent.
2. **Every sub-field is read with `getattr(..., None)`**, never attribute access, because
   `input_tokens_details` itself can be `None` on a constructed response.
3. **A sum over rounds where any round reported `None` for that field is `None`, not a partial
   sum.** A partial sum silently understates and no reader can tell it happened. This is the
   discipline `Timing.baseline_minutes` already follows.

## 2. `TokenUsage`

Lives in `agent/providers/__init__.py`, beside `EffortMapping`, for the reason that module already
states about `EffortMapping`: it is provider-neutral, it is produced by adapters, and
`report/session.py:22` already imports across that boundary (VERIFIED). Any other home means two
definitions.

```python
class TokenUsage(ProviderModel):
    """What one model round trip cost, in the fields the provider actually reported.

    Every count is `int | None` because a field the endpoint omitted is `None`, not zero.
    No field is derived; `uncached_input_tokens` is a property so it cannot go stale.
    """

    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_tokens: int | None        # OpenAI only; None on Gemini
    output_tokens: int | None
    reasoning_tokens: int | None
    tool_result_input_tokens: int | None  # Gemini only; inside input_tokens on OpenAI
    total_tokens: int | None
    latency_s: float

    @property
    def uncached_input_tokens(self) -> int | None:
        """`input - cached` when both are ints; None otherwise."""
```

`uncached_input_tokens` is a **property, not a field**, derived so it cannot go stale, the rule
`Timing.replace` (`report/session.py:124-140`) already follows.

## 3. The mapping, and the two arithmetic facts that are opposites

Every cell VERIFIED at the line cited.

| `TokenUsage` | OpenAI `Response.usage` (`response_usage.py`; field at `response.py:532`) | Gemini `usage_metadata` (`types.py:8445-8496`; field at `types.py:8612`) |
|---|---|---|
| `input_tokens` | `input_tokens` | `prompt_token_count` |
| `cached_input_tokens` | `input_tokens_details.cached_tokens` | `cached_content_token_count` |
| `cache_write_tokens` | `input_tokens_details.cache_write_tokens` | not reported |
| `output_tokens` | `output_tokens` | `candidates_token_count` |
| `reasoning_tokens` | `output_tokens_details.reasoning_tokens` | `thoughts_token_count` |
| `tool_result_input_tokens` | not reported (inside `input_tokens`) | `tool_use_prompt_token_count` |
| `total_tokens` | `total_tokens` | `total_token_count` |

**Fact 1 (VERIFIED, `types.py:8468-8471`).** `cached_content_token_count` is **inside**
`prompt_token_count`: "When `cached_content` is set, this also includes the number of tokens in
the cached content." Adding the two double counts.

**Fact 2 (VERIFIED, `types.py:8488-8491`).** `tool_use_prompt_token_count` is **outside**
`prompt_token_count`; `total_token_count` is documented as "the sum of `prompt_token_count`,
`candidates_token_count`, `tool_use_prompt_token_count`, and `thoughts_token_count`". Our reviewer
feeds every tool result back as input, so on Gemini this is a first-class number and dropping it
understates our input cost by whatever sixty-odd tool results weigh.

The same asymmetry runs the other way on output: OpenAI's `reasoning_tokens` is a **subset of**
`output_tokens`, while Gemini's `thoughts_token_count` is a **separate addend** of the total.

**Therefore: record the raw provider fields, and derive any cross-provider comparison explicitly
and only on `total_tokens`**, which both providers define as the whole bill. A single
cross-provider "output tokens" column compares two different quantities (RK-3). Every derived
column in the ledger names its derivation.

`cached_input_share` is `cached_input_tokens / input_tokens`, which is well defined on both
providers **only because on both, cached is contained in input**. The Gemini containment is
VERIFIED above; the OpenAI containment is **UNVERIFIED and is probe L1**, which asserts
`total == input + output`, `cached <= input` and `reasoning <= output` on one tiny request.

## 4. Where each adapter reads it

### OpenAI

**Insertion point**: immediately after `response = self._respond(...)` at the top of the `run()`
loop body, before `raw_output = [...]`. VERIFIED: `run()` is a `while True` loop
(`openai_provider.py:240`) and `_respond` is one HTTP request per iteration (`:292`), so a turn
with six serial tool calls is seven requests and **usage is per round, not per turn**.

Streaming carries the same object and **no `stream_options` or `include` flag is needed**:
`ResponseCompletedEvent.response` and `ResponseIncompleteEvent.response` are both `Response`
(VERIFIED, `response_completed_event.py`, `response_incomplete_event.py`), and those two events
are exactly what the adapter already captures as `final` (VERIFIED, `openai_provider.py`,
`_respond`). There is no separate usage-only stream event in this SDK version (VERIFIED by
absence under `openai/types/responses/`).

### Gemini

**Insertion point**: inside `_stream`. `_Round` gains
`usage: types.GenerateContentResponseUsageMetadata | None`, and the chunk loop reads usage
**outside** the candidates loop:

```python
for chunk in stream:
    if chunk.usage_metadata is not None:
        usage_metadata = chunk.usage_metadata   # last one wins
    for candidate in chunk.candidates or []:
        ...
```

This matters because the current loop body only runs for chunks that have candidates (VERIFIED,
`gemini_provider.py:393-394`, `for candidate in chunk.candidates or []`), so **a final chunk
carrying usage and no candidate is silently dropped today**.

**The SDK does not aggregate chunk usage** (VERIFIED: `google/genai/models.py:1718` and `:1757`
copy `usageMetadata` straight through per chunk; nothing under `google/genai/` merges it), so the
adapter must choose. "Last chunk that carries usage wins" is correct under both "cumulative" and
"only the final chunk carries it", and wrong only under "each chunk is a delta". That case is
**UNVERIFIED and is probe G3**.

### fake

`ScriptedTurn` gains `usage: TokenUsage | None` with a **fixed synthetic default**, so the runner,
ledger, report and scorecard paths are exercised with no network and a test can assert exact
totals. The fake's contract is that nothing is random, and a synthetic constant keeps it.

## 5. The `usage` event

**One event per model round trip, emitted by the adapter**, not a field on `TurnResult`. The
failure path is the reason: both adapters raise out of the round loop on a provider error
(`openai_provider._respond` raises `OpenAIProviderError`; `gemini_provider._stream` raises through
`self._report`), and `ReviewRun._run_turn`'s `except Exception` branch finalizes and re-raises
with no `TurnResult` to read. Usage carried on `TurnResult` would therefore **report zero cost for
the turn that cost the most**: five successful rounds then a rate limit on the sixth (RK-2).
`EventSink.emit` opens, appends and closes per event precisely so the stream survives the process
dying mid-review, so those five paid rounds are already on disk.

New `type` enum member: `usage`. Body, `additionalProperties: false`, every token field
`["integer", "null"]`:

```json
{"round_index": 0, "provider": "openai", "model": "gpt-5.6",
 "input_tokens": 12043, "cached_input_tokens": 10240, "cache_write_tokens": 1803,
 "output_tokens": 512, "reasoning_tokens": 448, "tool_result_input_tokens": null,
 "total_tokens": 12555, "latency_s": 4.31, "cache_diagnostic": null}
```

| Field | Type | Meaning |
|---|---|---|
| `round_index` | integer, >= 0 | The adapter's own per-turn counter, zero-based. Same convention `tool.started.step_index` already uses, and for the reason that module's docstring gives: an adapter sees one turn and cannot know a session-level number. Turns are delimited by the existing `turn.ended` events, so no turn number is carried and the runner never has to enrich an adapter's event |
| `provider` | `"openai" \| "gemini" \| "fake"` | Same closed enum `session.started.provider` uses |
| `model` | string | The model id this round was billed against |
| the seven counts | integer or null | Section 3, unmapped fields null |
| `latency_s` | number, >= 0 | Wall clock of the one request, measured by the adapter |
| `cache_diagnostic` | object or null | OpenAI lever 3 only; section 7. Null on Gemini, null on `fake`, and null on OpenAI whenever `prompt_cache_options.comparison_response_id` was not sent |

`round_index` also delivers the **round-trip counter** that levers 5, 6 and 7 are unmeasurable
without. `TurnResult.steps` counts tool calls, which is a different number, and with lever 6 on
the two diverge by exactly the amount lever 6 is trying to save.

**The pane's usage line** (`render.js` `usageLine`, feature 005 T016a) sums these bodies as they
arrive, by section 6's rule - any null in a field makes that total null - and reads only
`input_tokens`, `cached_input_tokens`, `total_tokens` and `latency_s`. Since feature 008 (T095,
`specs/008-checks-first-review/contracts/cost.md` section 4) it states the input as the report's
two numbers and **no cached share**: `<U> uncached + <C> cached input - <T> tokens in all - <K>
round trips - last round <S>`, `U` being summed input minus summed cached, when every round
reported both counts and the cached sum does not exceed the input sum; otherwise `<I> input
(cache split not reported)`, or `input unknown (cache split not reported)` when an input count is
missing. A total not reported by every round is `tokens unknown`. The share was dropped because
the report prints it as unknown until probe L1 is recorded (FR-047), and a percentage in the pane
beside that would be a second, contradicting number.

## 6. `SessionUsage` and the one summing rule

```python
class SessionUsage(ReviewModel):
    """What this session cost. `totals` is null in any field any round left null."""

    rounds: int          # >= 0
    turns: int           # >= 0
    totals: TokenUsage
    by_turn: list[TokenUsage]

    @classmethod
    def summed(cls, rounds: Sequence[TokenUsage], turn_boundaries: Sequence[int]) -> SessionUsage:
        """The ONLY place token counts are added. Any null in a field makes that total null."""
```

`ReviewSession.usage: SessionUsage | None = None`. Produced by a `UsageLedger` listener on the
`EventSink` (which already takes `listeners`), written in `finalize()` **before** `save_session`,
which means it works on the failure path because `_run_turn`'s `except` branch calls `finalize()`
before re-raising. **One accumulator, one write point, one summing rule** that the ledger listener
and the scorecard both call rather than re-implement.

`session.ended` body gains an optional `usage` carrying `SessionUsage`, so the pane does not have
to own a summing rule `SessionUsage` already defines. This is severable if the smallest possible
Phase 1 contract surface matters more (brief Q10).

## 7. `cache_diagnostic` (OpenAI, lever 3)

VERIFIED, `openai/types/responses/response.py:195-241`, field `prompt_cache_diagnostics` at
`:418`. A discriminated union on `type`:

| `type` | Extra fields | Meaning |
|---|---|---|
| `cache_hit` | none | The prefix was reused |
| `cache_miss` | `cache_missed_tokens` (int), `comparison_reusable_tokens` (int or null), `reason` | The estimated tokens affected after the first detected divergence, and why |
| `comparison_response_not_found` | none | The `comparison_response_id` we sent is gone |
| `unavailable` | none | No diagnostic for this request |

The `reason` enum, copied exactly from the installed SDK (VERIFIED, `response.py:202-213`):

```
model_changed | prompt_cache_key_changed | tools_changed | text_format_changed |
reasoning_effort_changed | verbosity_changed | context_compacted | input_changed |
service_tier_changed
```

**That enum is the authoritative list of what breaks our prefix**, and it turns "why did we miss"
from a guess into a recorded field. It is requested by setting
`prompt_cache_options.comparison_response_id` to the previous response's id (VERIFIED,
`response_create_params.py:165-175`; `PromptCacheOptions` carries `mode` (`implicit` default or
`explicit`), `ttl` (`"30m"`, currently the only value) and `comparison_response_id`, and its
docstring says "Supported for `gpt-5.6` and later models", which is our default.
`prompt_cache_retention` is deprecated in favour of the ttl, VERIFIED `response.py:434-452`).

It is recorded verbatim as a nested object. **It is not flattened and not summarised**, because
`tools_changed` with a `cache_missed_tokens` number is exactly how lever 4 is priced before lever
4 is written.

Whether `prompt_cache_options` is accepted on our seat is **UNVERIFIED and is probe L3b**; a 400
means the diagnostics half of lever 3 is off the table and `cache_diagnostic` stays null
everywhere.

## 8. Report

`report/markdown.py`'s `_render_timing` (`:450-461`) gains a `## Tokens` sibling, rendered **only
when `session.usage is not None`**, so every feature 001 and 002 golden report for a session
without usage stays byte-identical. Same discipline `record_partial_evidence` already follows.

The section states, per session: rounds, turns, input, cached input, uncached input, output,
reasoning or thoughts (named per provider, never merged), tool-result input where the provider
reports it, and total. A `None` renders as `unknown`, never as `0` and never as a dash that could
be read as zero.

Since feature 008 (T092, `specs/008-checks-first-review/contracts/cost.md` sections 2 and 3):
the `Cached input tokens` and `Uncached input tokens` lines are the two numbers the pane's line
also states, byte for byte unchanged; when the summed cached total is null the section ends with
`- Cache split not reported: the provider sent no cached-input count`. A `## Largest tool results`
table follows the section when the session has usage and at least one step carries its sizes
(`result_bytes`, `result_tokens`): at most five steps, by tokens, then bytes, then step index, an
unknown token count last as `unknown`, estimated with o200k_base from each step's full result. A
session without usage (a check folder) and every existing golden (no sizes) render no table.

## 9. Scorecard

`PackageScore` gains:

| Field | Source | Note |
|---|---|---|
| `usage` | `session.json` `usage.totals` | Verbatim, no re-summing |
| `round_trips` | `session.json` `usage.rounds` | The number levers 5, 6 and 7 are gated on |
| `cached_input_share` | derived here and nowhere else | `cached / input`, null if either is null or input is 0. **Computed from the start, published only once probe L1 is recorded** (FR-047): the share is well defined only if cached input is contained in input, and until L1 answers that, both the scorecard's markdown column and the ledger column render as unknown rather than as a number |
| `wall_clock_s` | `started_at` to `ended_at` | Distinct from `unattended_runtime_minutes`, which the benchmark runner overwrites (see below). **This is the number the ledger quotes and the number FR-028's 20 percent wall-clock threshold reads** |
| `seconds_to_first_finding` | `events.jsonl` | **Needs no new recording**: `session.started` and the first `finding` event already carry `at` timestamps. The scorecard reads `events.jsonl` beside the `session.json` it already reads, so `score_run` gains one file read per package and no answer-key contact. Principle VI and FR-025 are untouched |
| `coverage_bucket_mix` | `session.coverage` | Counts per bucket. **Lever 7 cannot be gated without it** (RK-7), so it ships with that lever |
| `unresolved_because_withheld`, `unresolved_other` | `session.coverage` | The two numbers FR-054 requires. They sum to `unresolved_count`. The first counts `unresolved` items written by a `WithheldTool` and is zero unless lever 4 is on; the second is everything else, and lever 4's gate is that it must not rise. One number would hide exactly the failure lever 4 can cause |

`Aggregate` gains the summed counts under the same any-null-makes-the-sum-null rule, plus
`median_seconds_to_first_finding` and `packages_with_usage`, mirroring the existing
`packages_with_timing`, which is the precedent for "how many packages contributed".

`render_scorecard_md` gains **three** columns: total tokens, cached share, round trips. Not seven.
The markdown is a scan; `scorecard.json` holds the detail and the ledger renders the rest.

**A labelling requirement, not a bug**: `run_benchmark` times each package with
`time.perf_counter()` and writes it into `Timing.unattended_runtime_minutes` via
`_record_unattended_runtime`, **overwriting** the number `finalize_session` computed from
`started_at` to `ended_at` (VERIFIED). Two writers of one field; the benchmark's wins because it
runs last and it includes package load and adapter construction. Any table quoting that number
says which one it is.

## 10. Tests, written first (Principle III), none needing a key

1. `usage_of(Response)` maps all five OpenAI fields; a response built with
   `ResponseUsage.construct` omitting `cache_write_tokens` yields `None`, **not 0** (the exact
   reproduction in section 1).
2. `usage_of(usage_metadata)` maps all six Gemini fields; an all-`None` `usage_metadata` yields an
   all-`None` `TokenUsage` and never a zero.
3. A Gemini stream whose final chunk carries `usage_metadata` and **no candidates** records that
   usage.
4. A turn that raises on its third round still records rounds 1 and 2 in `session.usage`.
5. `SessionUsage.summed`: one `None` in one round makes that total `None`, and the other fields
   still sum.
6. A `usage` event validates against the amended `chat-events.schema.json`, and **every existing
   event type still validates unchanged**.
7. A feature 001 `session.json` with no `usage` and no `efficiency` loads and validates against
   the amended session schema.
8. A scorecard over a session with no usage produces nulls and does not raise.
9. `report.md` for a session with no usage is **byte-identical** to the current golden.
10. `tests/unit/test_tool_payload.py`: the curated array is under a stated byte ceiling and no
    single tool object exceeds a per-tool ceiling. Worth writing whether or not lever 2 is ever
    adopted, because it stops a new tool quietly adding 2 KB to every request.

## 11. Live probes for this layer

| # | UNVERIFIED claim | Probe |
|---|---|---|
| L1 | OpenAI sub-count containment | One tiny request; assert `total == input + output`, `cached <= input`, `reasoning <= output`. This is what keeps `cached_input_share` honest |
| L3b | `prompt_cache_options` is accepted on our model | Falls out of L3; a 400 means `cache_diagnostic` stays null |
| G3 | Gemini streaming populates `usage_metadata`, and the last chunk carries the totals | One streamed call; collect every chunk's usage; assert at least one is non-null and the last `total_token_count` is >= the first. Settles cumulative versus delta |
| P6 | Both adapters actually receive a usage object on a streamed turn | `swreview review` on `cover-blind-tap` on both providers, recording the fields. **This is also the baseline row that does not exist today** |

Each lives in `reviewer/tests/live/` with `pytestmark = pytest.mark.live`, is skipped without a
key, and reports 401, 429 and 5xx as a skip rather than a failure, following
`tests/live/test_openai_live_schemas.py`.
