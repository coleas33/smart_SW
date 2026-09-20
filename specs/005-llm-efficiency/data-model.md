# Data Model: LLM efficiency, speed, and token usage

**Feature**: `005-llm-efficiency` | **Date**: 2026-09-16 | **Spec**: [spec.md](spec.md) |
**Research**: [research.md](research.md)

**This feature adds no new top-level artifact and no new IR phase.** Every type below is either a
new pydantic model in the reviewer, a new **optional** field on an existing feature 001 or 002
model, a new `ManifestEntry` field in the IR (lever 9 only, schema 1.3.0), or a row shape rendered
by `swreview benchmark compare`. Nothing existing is removed and nothing existing changes type.

## Conventions this document holds to

- **Unknown stays unknown.** Every token count is `int | None`. `None` means "the provider did not
  report it"; `0` means "the provider reported zero". The two are never collapsed, and no reader
  coerces one to the other. This is Principle I and it is the single rule the measurement layer is
  built around (research R4).
- **Any null makes the sum null.** A sum over rounds where **any** contributing round reported
  `None` for that field is `None`, not a partial sum. A partial sum silently understates and no
  reader can tell it happened. Same discipline as `Timing.baseline_minutes`.
- **Raw provider fields are recorded; comparisons are derived and named.** The two providers'
  sub-counts nest differently (research R2, R3), so a cross-provider comparison is made only on
  `total_tokens` and every derived quantity states its formula here, once.
- **Derived values are properties, not fields.** `uncached_input_tokens` and `cached_input_share`
  are computed from the fields they derive from, so they cannot go stale. Same rule
  `Timing.replace` (`report/session.py:124-140`) already follows.
- **Additive means additive.** Every new field on a feature 001 or 002 model is optional with a
  default, added to the schema's `properties` and left out of `required`, so every session, event
  stream and report written before this feature still loads and still validates. The one schema
  whose house style is the opposite (`scorecard.schema.json`, where every property is also in
  `required` and nullability carries "may be absent") gets additions in **its** style. Section 12
  is the full register.
- **This document is normative for every field name.** Where a JSON example in `contracts/`
  differs from a table here, this file is right and the example is a defect.
- **No lever changes what the reviewer may do.** Nothing in this model grants a write.

---

## 1. What is new, at a glance

| # | Thing | Where it lives | Phase | Flagged? |
|---|---|---|---|---|
| 2 | `TokenUsage` | `agent/providers/__init__.py` | 1 | no |
| 3 | `SessionUsage` | `report/session.py` | 1 | no |
| 4 | `usage` event and its body | `agent/providers/__init__.py`, `chat-events.schema.json` | 1 | no |
| 5 | `CacheDiagnostic` | `agent/providers/__init__.py` | 2 (lever 3) | on the body from phase 1, always `null` until then |
| 6 | `ReviewSession.usage`, `ReviewSession.efficiency` | `report/session.py` | 1 | no |
| 7 | `EfficiencySettings` | `agent/settings.py` | 1 | it **is** the flags |
| 8 | `PackageScore` and `Aggregate` additions; the ledger rows | `benchmark/scorecard.py`, `benchmark/compare.py` | 1 | no |
| 9 | `reuse_key`, `ManifestEntry.file_modified_utc`, `file_size_bytes`, `PackageIndexRow` | `ir/models.py`, `Dump/ManifestBuilder.cs`, `Review/RunFolders.cs` | 4 (lever 9) | `package_reuse` |
| 10 | `Finding.carried_over_from`, `carried_over_at`, `carry_over_key` | `findings.py` | 4 (lever 11a) | `carry_over_rms` |
| 11 | `ToolTier`, `WithheldTool` | `tools/registry.py` | 2 (lever 4) | `tool_tiers` |

---

## 2. `TokenUsage`: the usage record for one model round trip

`reviewer/src/swreview/agent/providers/__init__.py`, beside `EffortMapping`, because it is
provider-neutral, it is produced by adapters, and `report/session.py:22` already imports across
that boundary (VERIFIED). Any other home means two definitions.

**One `TokenUsage` is one model round trip, not one turn.** VERIFIED that `OpenAIProvider.run()` is
a `while True` loop whose body makes exactly one HTTP request, so a turn with six serial tool calls
is seven requests and seven `TokenUsage` records.

```python
class TokenUsage(ProviderModel):
    """What one model round trip cost, in the fields the provider actually reported.

    Every count is `int | None`. None means the provider did not report the field; 0 means it
    reported zero. Never coerce one to the other.
    """

    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_tokens: int | None        # OpenAI only; always None on Gemini
    output_tokens: int | None
    reasoning_tokens: int | None
    tool_result_input_tokens: int | None  # Gemini only; inside input_tokens on OpenAI
    total_tokens: int | None
    latency_s: float
```

| Field | Type | Rules |
|---|---|---|
| `input_tokens` | `int \| None`, `ge=0` | Prompt tokens as the provider reports them. On Gemini this **excludes** tool-result tokens (see `tool_result_input_tokens`). |
| `cached_input_tokens` | `int \| None`, `ge=0` | Tokens served from cache. **Contained inside `input_tokens` on both providers**: VERIFIED for Gemini from the `prompt_token_count` description; UNVERIFIED for OpenAI and asserted by probe L1. |
| `cache_write_tokens` | `int \| None`, `ge=0` | OpenAI only. `None` on Gemini, and `None` on an OpenAI endpoint that does not report it, which VERIFIED happens (research R4.1). |
| `output_tokens` | `int \| None`, `ge=0` | Completion tokens. |
| `reasoning_tokens` | `int \| None`, `ge=0` | **Nests differently per provider and is never summed across them**: a subset of `output_tokens` on OpenAI, a separate addend of the total on Gemini. |
| `tool_result_input_tokens` | `int \| None`, `ge=0` | Gemini only. **Outside** `prompt_token_count` and a separate addend of `total_token_count` (VERIFIED). `None` on OpenAI, where the same tokens are already inside `input_tokens`. |
| `total_tokens` | `int \| None`, `ge=0` | The whole bill for the round trip. **The only field compared across providers.** |
| `latency_s` | `float`, `ge=0` | Wall clock for the round trip, measured by the adapter around its own request. Not a provider field, never `None`: if we made the call we timed it. |

### 2.1 Derived properties, not fields

| Property | Formula | Result when an input is `None` |
|---|---|---|
| `uncached_input_tokens` | `input_tokens - cached_input_tokens` | `None` |
| `cached_input_share` | `cached_input_tokens / input_tokens` | `None`; also `None` when `input_tokens == 0`, because a share of nothing is not zero |

Both are defined **once, here and in code**, and nowhere else. `cached_input_share` being well
defined at all depends on cached being contained in input, which is why probe L1 exists: if that
assertion ever fails for OpenAI, this metric is wrong for OpenAI and the assertion is what tells
us.

### 2.2 The provider mapping, every cell VERIFIED

Read today in `openai/types/responses/response_usage.py` and `google/genai/types.py:8445-8496`.

| `TokenUsage` | OpenAI `Response.usage` | Gemini `GenerateContentResponse.usage_metadata` |
|---|---|---|
| `input_tokens` | `input_tokens` | `prompt_token_count` |
| `cached_input_tokens` | `input_tokens_details.cached_tokens` | `cached_content_token_count` |
| `cache_write_tokens` | `input_tokens_details.cache_write_tokens` | not reported, always `None` |
| `output_tokens` | `output_tokens` | `candidates_token_count` |
| `reasoning_tokens` | `output_tokens_details.reasoning_tokens` | `thoughts_token_count` |
| `tool_result_input_tokens` | not reported (those tokens are inside `input_tokens`), always `None` | `tool_use_prompt_token_count` |
| `total_tokens` | `total_tokens` | `total_token_count` |

**Reading rule for both adapters**: every sub-field is read with `getattr(obj, name, None)` and
never by attribute access, because `Response.usage` may be `None`, `input_tokens_details` may
itself be `None` on a constructed response, and every Gemini field is `Optional[...] = None` by
declaration (all VERIFIED).

**Two nesting facts that must not be summed away** (VERIFIED from the packages' own field
descriptions, research R3.1):

- Gemini: `cached_content_token_count` is **inside** `prompt_token_count`; adding them double
  counts.
- Gemini: `tool_use_prompt_token_count` is **outside** `prompt_token_count` and is a separate
  addend of `total_token_count`; dropping it understates our input cost by whatever 60-odd tool
  results weigh.

### 2.3 The synthetic record the fake provider emits

`ScriptedTurn` gains `usage: TokenUsage | None = None`, defaulting to one fixed synthetic constant
so that runner, ledger, report and scorecard paths are exercised with no network and a test can
assert exact totals. The fake's contract is "nothing is random" (VERIFIED, `providers/fake.py`
docstring) and a constant keeps that. The constant is defined once in `fake.py`, is deliberately
not round-numbered so an accidental zero is visible, and **includes at least one `None` field**, so
the any-null-makes-the-sum-null rule is exercised by the default fixture and not only by a special
test.

---

## 3. `SessionUsage`: the usage record for one run

`reviewer/src/swreview/report/session.py`, beside `Timing`.

```python
class SessionUsage(ReviewModel):
    """What this whole run cost. Summed by UsageLedger from the usage events on the stream."""

    rounds: int          # model round trips across the whole session
    turns: int           # turns that produced at least one round
    totals: TokenUsage   # summed under the any-null-makes-the-sum-null rule
    by_turn: list[TokenUsage]
```

| Field | Type | Rules |
|---|---|---|
| `rounds` | `int`, `ge=0` | Count of `usage` events seen. **This is the round-trip counter every lever in tiers 1 and 2 is measured with.** It is not `len(session.steps)`: steps count tool calls and the two diverge by exactly the amount lever 6 saves. |
| `turns` | `int`, `ge=0` | Count of turns that produced at least one round. Delimited by the existing `turn.ended` events. |
| `totals` | `TokenUsage` | Field-by-field sum over every round. `latency_s` sums to total model wall clock, which is **not** session wall clock (local tool time is outside it). |
| `by_turn` | `list[TokenUsage]` | One summed entry per turn, same summing rule, in turn order. Length equals `turns`. |

### 3.1 The summing rule, stated once

For each field independently: if **any** contributing round reported `None`, the total for that
field is `None`. Otherwise it is the arithmetic sum. `latency_s` is never `None` so it always sums.

The invariant a test pins: `totals` computed over every round equals `totals` computed by summing
`by_turn`, for every field including the `None`s.

### 3.2 Who writes it, and why it survives a crash

Produced by a **`UsageLedger` listener on the `EventSink`** (`EventSink` already takes `listeners`,
VERIFIED), held by `ReviewRun`, written to `session.usage` in `finalize()` **before**
`save_session`. One accumulator, one write point.

This works on the failure path because `_run_turn`'s `except Exception` branch calls `finalize()`
before re-raising. **A turn that raised on its sixth round still records the five rounds it paid
for** (RK-2), which is the whole reason usage is a stream event rather than a field on
`TurnResult`.

---

## 4. The `usage` event

A new value in the `EventType` literal (`agent/providers/__init__.py:87-103`) and in the closed
`type` enum of `specs/002-task-pane-assistant/contracts/chat-events.schema.json`. Emitted **by the
adapter**, once per model round trip, immediately after the response for that round is in hand and
before any tool in that round runs.

```json
{"round_index": 0, "provider": "openai", "model": "gpt-5.6",
 "input_tokens": 12043, "cached_input_tokens": 10240, "cache_write_tokens": 1803,
 "output_tokens": 512, "reasoning_tokens": 448, "tool_result_input_tokens": null,
 "total_tokens": 12555, "latency_s": 4.31, "cache_diagnostic": null}
```

| Body field | Type | Rules |
|---|---|---|
| `round_index` | `integer`, `ge=0` | The adapter's own per-turn counter, resetting at each turn. Exactly the convention `tool.started.step_index` already uses, and for the reason the module docstring gives: an adapter sees one turn and cannot know a session-level number. **No turn number is carried**: turns are delimited by the existing `turn.ended` events, so the runner never has to enrich an adapter's event. |
| `provider` | `string` | `"openai"`, `"gemini"` or `"fake"`. On the event because a session can in principle be resumed under a different adapter and the round is the thing that was paid for. |
| `model` | `string` | The model id as sent. Never a literal anywhere but `settings.py`. |
| the seven counts | `integer \| null` | Exactly the `TokenUsage` fields of section 2, same names, same nullability. `null` in JSON is `None` in the model and means "not reported". |
| `latency_s` | `number`, `ge=0` | Never null. |
| `cache_diagnostic` | `object \| null` | Section 5. `null` until lever 3 lands, and `null` on Gemini always. |

The body is `additionalProperties: false` like every other body in that schema, and `required` is
every field above: this event is new, so there is no older producer to keep valid, and stating
every field is the honest shape.

### 4.1 What the new event does not break

- `events.jsonl` replay (`GET /sessions/{id}/events`, `Last-Event-ID`): `seq` is still monotonic;
  the new events simply occupy sequence numbers.
- The pane: an unknown event type is ignored by a `switch` on `type`, so the page renders as before
  until it is taught the new one.
- Goldens: unchanged for a session with no usage; new goldens carry it.

### 4.2 `session.ended` gains an optional `usage`

Added to `properties` of the `session.ended` body, with `required` left as
`["ended_at", "timing"]`. The value is the `SessionUsage` of section 3. It exists so the pane does
not have to own a summing rule `SessionUsage` already defines. **Severable** if the smallest
possible Phase 1 contract surface matters more (OQ-10).

### 4.3 Where usage is deliberately *not* added

`GET /sessions/{chat_id}` (`ChatSession.public()`) gains nothing. The pane gets usage from the
stream and `session.json` is the record; putting it on `public()` would be a third copy of the same
numbers.

---

## 5. `CacheDiagnostic`: the OpenAI prompt-cache outcome for one round

`agent/providers/__init__.py`. Mirrors `Response.prompt_cache_diagnostics` (VERIFIED,
`openai/types/responses/response.py:194-241`, field at `:418`), flattened to one nullable record
because a discriminated union on our side would buy nothing: every reader wants the `type` and,
when it is a miss, the reason and the count.

| Field | Type | Rules |
|---|---|---|
| `type` | `"cache_hit" \| "cache_miss" \| "comparison_response_not_found" \| "unavailable"` | The four variants the SDK declares. VERIFIED. |
| `reason` | `string \| null` | Present only when `type == "cache_miss"`. One of the nine values below, recorded **verbatim as the SDK spells it**, because it is the SDK's vocabulary and not ours. |
| `cache_missed_tokens` | `int \| None`, `ge=0` | Present only on `cache_miss`. "The estimated number of input tokens affected after the first detected divergence" (VERIFIED, the field's own description). |
| `comparison_reusable_tokens` | `int \| None`, `ge=0` | Optional even on a miss (`Optional[int] = None` in the SDK, VERIFIED). "The raw token count of the reusable prefix in the compared response." |

The nine miss reasons, VERIFIED verbatim at `response.py:204-213`:

```
model_changed | prompt_cache_key_changed | tools_changed | text_format_changed |
reasoning_effort_changed | verbosity_changed | context_compacted | input_changed |
service_tier_changed
```

**That enum is the authoritative list of what breaks our prefix**, and it is why lever 3 is
sequenced before levers 2 and 4: a tier change shows up as `tools_changed` with a
`cache_missed_tokens` number, which **prices lever 4 before lever 4 is written**.

Diagnostics are returned only when `prompt_cache_options.comparison_response_id` is set to the
previous response's id (VERIFIED that the field exists; **UNVERIFIED** that our seat accepts
`prompt_cache_options` on `gpt-5.6`, which is probe L3b). `cache_diagnostic` is `None` on Gemini
always, and `None` on OpenAI whenever we did not ask.

### 5.1 The cache key itself

Not a model field: `prompt_cache_key` is a request parameter set to `str(session.session_id)`, a
value already persisted in `session.json`. It must be stable across a process restart, because the
pane restarts the backend on a settings save and resumes the same run folder; a process-local
random value would look identical and silently drop every hit, showing up as
`prompt_cache_key_changed`.

---

## 6. Additive fields on `ReviewSession`

`report/session.py:153-166`. Both added to `properties` of
`specs/001-agentic-design-review/contracts/review-session.schema.json` and **left out of
`required`**, which is exactly the pattern `provider_info` and `retry_of` already set (VERIFIED).

| Field | Type | Default | Why optional |
|---|---|---|---|
| `usage` | `SessionUsage \| None` | `None` | A session written before this feature has none, and a session whose adapter reported nothing keeps `None` rather than an all-zero record. |
| `efficiency` | `EfficiencySettings \| None` | `None` | Same reason. **Without this field no results row can be attributed to a configuration and the A/B table cannot be rebuilt from the run folder.** |

`ReviewSession.model` and `provider_info` stay exactly as they are. Nothing in this feature makes a
session carry two models (research R15).

### 6.1 The report surface

`report/markdown.py` gains a `## Tokens` section beside `_render_timing`, rendered **only when
`session.usage is not None`**, so every feature 001 and 002 golden report for a session without
usage stays byte-identical. It renders `rounds`, `turns`, the seven totals with `not reported` for
a `None`, `cached_input_share` as a percentage or `not reported`, and total model latency. It never
prints `0` for a `None`.

When lever 11a is on, the coverage section also states how many findings were carried over and how
many were re-run (section 10.4).

---

## 7. `EfficiencySettings`: the lever flags, and the one carrier for all of them

`reviewer/src/swreview/agent/settings.py`, beside `ProviderSettings` (VERIFIED, `:176-192`), which
is already the single place per-provider defaults live.

```python
class EfficiencySettings(BaseModel):
    """Which efficiency levers this run has on. Every field defaults to off."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trim_tool_descriptions: bool = False   # lever 2
    tool_tiers: bool = False               # lever 4
    prompt_cache_key: bool = False         # lever 3, OpenAI
    gemini_explicit_cache: bool = False    # lever 3, Gemini; gated on probe G4
    prerun_checks: bool = False            # lever 5
    parallel_tool_calls: bool = False      # lever 6
    coverage_stop: bool = False            # lever 7
    package_reuse: bool = False            # lever 9
    lazy_meshes: bool = False              # lever 10a
    carry_over_rms: bool = False           # lever 11a
    procedural_gate: bool = False          # lever 11
    compact_queries: bool = False          # experimental bounded discovery pages
```

| Flag | Lever | What it switches | Read when | Provider |
|---|---|---|---|---|
| `trim_tool_descriptions` | 2 | Tool descriptions are the first paragraph only; the rest is rendered into the system prompt's `## Tool notes` block | once, at `start_review`; applied **after** `spec_for`, never inside it, because `_SPECS` is a process-global cache (VERIFIED, `registry.py:257-261`) | both |
| `tool_tiers` | 4 | Package-decidable tiers are applied; withheld tools become `WithheldTool` entries (section 11) | once, at `start_review`; the subset is fixed for the whole session | both |
| `prompt_cache_key` | 3 | `prompt_cache_key = str(session_id)` is sent, and `prompt_cache_diagnostics` is recorded onto the `usage` body | per request | OpenAI |
| `gemini_explicit_cache` | 3 | An explicit `CachedContent` is created at `start_review`, referenced per request, deleted on `close()` | once, at `start_review` | Gemini |
| `prerun_checks` | 5 | The four self-enumerating deterministic checks run before the first turn; the digest is prepended to `OPENING_MESSAGE` | once, at `start_review` | both |
| `parallel_tool_calls` | 6 | The OpenAI request stops pinning `parallel_tool_calls: False`; local execution stays serial in request order | at adapter construction | OpenAI only; Gemini is already parallel and has no off switch (VERIFIED by absence) |
| `coverage_stop` | 7 | When the strict stop predicate holds, the next round is issued with `tool_choice: "none"` / `FunctionCallingConfig(mode=NONE)` | per round | both |
| `package_reuse` | 9 | An unchanged package is copied from a prior run folder instead of dumped | at dump time | neither, this is extractor-side |
| `lazy_meshes` | 10a | Meshes are fetched on demand over the bridge instead of dumped eagerly | at dump and at `check_tool_envelope` | neither |
| `carry_over_rms` | 11a | `rms.*` findings whose fingerprint is unchanged are carried over instead of re-run | once, at `start_review` | both |
| `procedural_gate` | 11 | Deterministic opening gate and brief are run before the model's first turn | once, at `start_review` | both |
| `compact_queries` | 12 | The opt-in compact discovery page is added to the provider tool surface | once, at registry build | both |

### 7.1 Threading, and why it is one argument

Threaded as **one keyword argument** through `start_review` (`runner.py:595-651`), held on
`ReviewRun` (`:394-424`) exactly as `effort` and `max_steps` already are, and as one argument
through `run_benchmark` (`benchmark/runner.py:69-76`) and `cli._review_fn` (`cli.py:1341-1364`).
One plumbed parameter per lever would be ten signature changes across three call sites and ten
separate contract edits (OQ-1).

### 7.2 Where these flags do not appear

The pane's `settings.schema.json` does **not** grow lever checkboxes while the levers are being
measured: an engineer toggling experiment flags mid-pilot makes the pilot's own numbers unreadable.
The CLI flag (`swreview benchmark run --lever <name>`, repeatable) is enough for the benchmark.
**An adopted lever becomes a default in code, not a checkbox**, and its flag then either disappears
or flips its default in a separate change with its own ledger row.

### 7.3 Serialization

Serialized onto `session.efficiency` as a plain object of twelve booleans. `extra="forbid"` means an
old session carrying a flag a later build removed fails loudly rather than being silently ignored,
which is correct: a results row attributed to a configuration nobody can reconstruct is worse than
an error.

### 7.4 Combinations the protocol forbids rather than the model

`EfficiencySettings` permits any combination; the **evaluation protocol** (research R8, R20)
forbids some arms. The two that matter: levers 5 and 7 are never on in the same A/B arm until each
is gated alone, and lever 2 is measured with lever 3 off. These are protocol rules recorded in the
ledger's "other levers on" column, not validator rules, because a validator would also block a
legitimate post-adoption run with several adopted levers on.

---

## 8. The A/B run record and the results ledger

The ledger is a **rendering of N `scorecard.json` files**, produced by
`swreview benchmark compare`, never a hand-kept table. Typed numbers go stale and cannot be
audited.

### 8.1 `PackageScore` additions

`benchmark/scorecard.py:65-78`. `contracts/scorecard.schema.json` is
`additionalProperties: false` with **every** property also in `required` and nullability carrying
"may be absent" (VERIFIED), so these additions are in `properties` **and** in `required`, nullable
where a session may not carry usage.

| Field | Type | Source, and the one place it is computed |
|---|---|---|
| `usage` | `TokenUsage \| null` | `session.usage.totals`, copied, not recomputed |
| `round_trips` | `int \| null`, `ge=0` | `session.usage.rounds` |
| `cached_input_share` | `float \| null`, `0..1` | `usage.cached_input_share` (section 2.1). `null` when either input is `null` or `input_tokens == 0` |
| `wall_clock_s` | `float`, `ge=0` | `started_at` to `ended_at` on the session, in seconds. **This is the one wall clock the ledger quotes and the one FR-028's 20 percent threshold reads.** Deliberately **not** `unattended_runtime_minutes * 60`: that field has two writers, and the second one wins. `finalize_session` computes it from `started_at`/`ended_at`, then `_record_unattended_runtime` **overwrites** it with `run_benchmark`'s own `time.perf_counter()` span, which also covers package load and adapter construction (VERIFIED, `benchmark/runner.py:99-103,55-65`). The two are different numbers; `unattended_runtime_minutes` stays as the benchmark harness's separate number and the baseline row names which one it quotes (FR-010, SC-005) |
| `seconds_to_first_finding` | `float \| null`, `ge=0` | `at` of the first `finding` event minus `at` of `session.started`, read from `<run_dir>/<package_id>/events.jsonl`. `null` when the run produced no finding |
| `coverage_bucket_mix` | `object` of five `int` | `len()` of each of `checked`, `skipped`, `unresolved`, `failed`, `out_of_scope`. **Required by lever 7's gate** and useful on its own |
| `unresolved_because_withheld` | `int`, `ge=0` | Count of `unresolved` coverage items written by a `WithheldTool`. Zero unless lever 4 is on |
| `unresolved_other` | `int`, `ge=0` | Every other `unresolved` coverage item. **These two are the two numbers FR-054 requires**, they sum to `unresolved_count`, and lever 4's gate is that the first may rise and the second must not. One number would hide exactly the failure lever 4 can cause |
| `carried_findings` | `int`, `ge=0` | Count of findings with `carried_over_from` set. Zero unless lever 11a is on |
| `tool_call_histogram` | `object` of `str -> int` | Tool name to call count, from `session.steps`. **Lever 2's real quality signal** (a trim that changed the answer usually shows first as a call-pattern change) and lever 5's `check_fit` / `check_axial_stack` gate reads two of its entries |

`seconds_to_first_finding` needs **no new recording**: both events already carry `at` timestamps
(VERIFIED). `score_run` gains one file read per package and **no answer-key contact**, so
Principle VI and FR-025 are untouched.

### 8.2 `Aggregate` additions

Same house style, same "any null makes the sum null" rule.

| Field | Type | Rules |
|---|---|---|
| `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens`, `total_tokens`, `round_trips` | `int \| null` | Summed over packages; `null` if any package contributed `null` |
| `median_seconds_to_first_finding` | `float \| null` | Median over packages that produced a finding; `null` when none did |
| `packages_with_usage` | `int`, `ge=0` | Mirrors the existing `packages_with_timing`, which is the precedent for "how many packages contributed to this aggregate" |

`render_scorecard_md` gains **three** columns and not seven: total tokens, cached share, round
trips. The markdown is a scan; `scorecard.json` holds the detail.

### 8.3 `RunRow`: one row per run folder, the raw ledger

`benchmark/compare.py`. Every column has **exactly one source** and no column is computed twice.

`lever`, `arm`, `rep` and `commit` come from the run's **provenance record** (section 2 of
contracts/ab-harness.md, which is where the record is defined; section 7 is the harness
preconditions), which `cli.py` writes from `--study`, `--arm`, `--rep` and the commit sha, and are
**cross-checked against `session.efficiency`**, which the runner writes from the resolved
`EfficiencySettings`. Two independent writers is the whole point: a run whose two records disagree
is refused rather than rendered (RK-20). A run directory with no provenance record renders with
those four columns null, because a run made before the convention existed is still a real run.

| Column | Type | Source |
|---|---|---|
| `run` | str | The run folder name |
| `commit` | str | The run's **provenance record**, which records the tree's commit sha at run time. Load-bearing rather than decoration because `compare` refuses to place two runs of differing commits in one comparison, with no exception |
| `lever` | str | The run's **provenance record**, from `--study`. Which lever this arm is measuring, e.g. `parallel_tool_calls`, or `"none"` for a baseline study |
| `arm` | `"off" \| "on" \| "baseline"` | The run's **provenance record**, from `--arm`, cross-checked against `session.efficiency` for this lever's flag (ab-harness section 3). `"baseline"` is the study with no lever under test (ab-harness section 8) |
| `rep` | int, `ge=1` | The run's **provenance record**, from `--rep`. Which of the three repetitions; **not** inferred from the run folder name |
| `provider`, `model`, `effort` | str | `session.provider_info` |
| `package` | str | `PackageScore.package_id` |
| `other_levers_on` | list[str] | Every other flag true in `session.efficiency`. **Exists because of the interaction matrix**; a number without it is unattributable |
| `input`, `cached_in`, `output`, `reasoning`, `tool_result_in`, `total` | `int \| null` | `session.usage.totals`, the raw provider fields |
| `uncached_in`, `cached_share` | `int \| null`, `float \| null` | **Derived in the scorecard only**, never stored twice |
| `rounds` | `int \| null` | `session.usage.rounds` |
| `tool_calls` | int | `len(session.steps)`. **Kept beside `rounds` because lever 6 makes them diverge and lever 6's own gate reads both** |
| `wall_clock_s` | float | `PackageScore.wall_clock_s` |
| `s_to_first_finding` | `float \| null` | `PackageScore.seconds_to_first_finding` |
| `valid`, `missed`, `false_alarms`, `unresolved` | int | The existing `PackageScore` fields, unchanged |
| `coverage_bucket_mix` | object | `PackageScore.coverage_bucket_mix` |
| `unresolved_because_withheld`, `unresolved_other` | int | `PackageScore`, the two numbers FR-054 requires |

`reasoning` is rendered under a **provider-specific heading** ("reasoning" for OpenAI, "thoughts"
for Gemini) because the two are different quantities (research R3.1), and the two are never added
together.

### 8.4 `LeverDecision`: one row per lever per provider and model, the summary the owner reads

| Column | Type | Rules |
|---|---|---|
| `lever` | str | |
| `provider`, `model` | str | One row per pair. Lever 6 carries the literal note "Gemini: on by default, not measurable as A/B" instead of a fabricated comparison |
| `commit_off`, `commit_on` | str | **Equal for every lever in this feature**, lever 2 included, whose off arm is its flag off rather than an earlier commit. The pair exists for FR-032, which currently has no instance |
| `reps` | int | 3 unless the control arm was unstable and the count was raised |
| `other_levers_on` | list[str] | |
| `input_tokens`, `cached_input`, `output`, `reasoning_or_thoughts`, `round_trips`, `tool_calls`, `wall_clock`, `dump_wall_clock` | `OffOn` | Each is `{off_median, off_min, off_max, on_median, on_min, on_max, delta_pct}`. `dump_wall_clock` is populated for levers 9 and 10 only, from the workstation harness |
| `valid`, `missed`, `false_alarms`, `unresolved` | `OffOn` | Quality, same shape |
| `recall_held_out` | `OffOn` | `null` throughout until at least one package is held out (research R20.1 precondition 4) |
| `worst_case_defects_lost` | int, `ge=0` | Defects any off-run found that any on-run missed. **Worst case, not median**, per the adoption rule |
| `lever_counter` | `{name, off, on}` | The number **this** lever's gate needs and no other's: stop fire rate (7), carried-finding count (11a), unresolved-because-withheld (4), the `check_fit` and `check_axial_stack` call counts (5), step count against round trips (6), miss reasons and `cache_missed_tokens` (3), tool-name histogram diff (2), byte-identity pass/fail (9), `bodies_swept` equality (10a) |
| `decision` | `"adopt" \| "keep off" \| "re-measure"` | **Computed** by the FR-028 rule from the scorecards, never typed (FR-027, SC-009). A closed enum of exactly three: an unstable control arm yields `re-measure`, not a fourth value |
| `decision_reason` | str | The printed reason beside the computed decision, for example `CONTROL UNSTABLE` naming the disagreeing defect ids, or the threshold that was missed. This is where an unstable control arm is named; it is prose beside the enum, not a member of it |
| `owner_signed_off` | bool, default `False` | **The owner's act, kept separate from the computed column.** `compare` never writes it; it is written by hand into the committed `ledger.md` once the owner has read the row. A row may be computed `adopt` and unsigned, and **no flag default changes until it is signed** |
| `owner_signed_off_at` | `date \| None` | When. `None` while `owner_signed_off` is false |
| `run_dirs` | list[str] | Every run folder behind the row, so any number is chaseable to its `scorecard.json` |

`OffOn.delta_pct` is `(on_median - off_median) / off_median` and is `None` when `off_median` is
`None` or zero. **The adoption threshold reads `delta_pct` on `total` tokens or on `wall_clock`
and nothing else** (research R20.3).

**A failed lever keeps its row.** `decision` is `keep off` and every number stays, which is why the
column is called Decision rather than Winners.

---

## 9. The package-reuse key (lever 9)

### 9.1 New `ManifestEntry` fields

`ir/models.py:187-194` and `Dump/ManifestBuilder.cs:28-65`. **IR schema goes to 1.3.0** and
`tests/unit/test_schema_sync.py` is regenerated.

| Field | Type | Rules |
|---|---|---|
| `file_modified_utc` | `datetime \| None` | `FileInfo.LastWriteTimeUtc` of the document's path, ISO 8601 UTC. `None` plus a gap when the path cannot be stat'ed. Never `0` and never "now" |
| `file_size_bytes` | `int \| None`, `ge=0` | Same source, same null-with-a-gap rule |

**Why these two are non-negotiable.** VERIFIED that the manifest today holds no modification time,
no file size and no content hash, that `local_modified` is **hardcoded null** with an `unsupported`
gap on every document of every dump (`ManifestBuilder.cs:57,92-98`), and that `vault_version` and
`revision` are null unless a vault writes them. So a key without these two reduces to **path and
configuration**, which says nothing about whether anything changed, and reuse on it makes the
stale-package failure certain rather than possible (RK-10, OQ-6).

### 9.2 `EvidencePackage.reuse_key`

A new top-level `reuse_key: str | None` on `EvidencePackage`, written near the top of
`package.json` so a bounded head read can find it (the `RunFolders.ProfileOf` technique reads the
first 8 KiB, VERIFIED). It is a SHA-256 hex digest over this ordered tuple:

```
extractor.name
extractor.version
schema_version
extractor.profile
dump options that change content:
    meshes    (glb | stl | none)
    faces     (needed | all)
    features  (tree | none)
    equations (on | off)
design.root_assembly_document_id
design.active_configuration
for each manifest entry sorted by document_id:
    document_id
    configuration
    sorted(referenced configurations of that document)
    file_modified_utc
    file_size_bytes
for each component sorted by component_id:
    suppression state
```

Every part earns its place, and each is a failure the key would otherwise miss:

| Part | The failure it catches |
|---|---|
| extractor name and version, schema version | A package written by an older build is missing a phase a newer reviewer expects |
| profile and the four dump options | A `model_check` package has empty `holes[]`, `fasteners[]`, `faces[]` and `bodies[]` **by design** (VERIFIED, `Dump/PackageWriter.cs:200-235`); handing one to a `full` Review silently narrows it (RK-11) |
| root document and active configuration | A configuration switch changes geometry without touching a file |
| **every** manifest entry, not just the root | A referenced part edited outside the assembly. VERIFIED that `PackageWriter.DocumentPaths` (`:381-401`) collects every document the traversal reached |
| per-document referenced configurations | `ManifestEntry.configuration` is the *document's* active configuration while `ComponentInstance.referenced_configuration` is per instance (VERIFIED, `ir/models.py:245`), so a per-instance switch is otherwise invisible |
| per-component suppression state | A suppressed or lightweight component later resolved changes what a review can see with no file change (VERIFIED, `Dump/MeshExporter.cs:57-69`) |

### 9.3 The invalidation table, one unit test per row

| Change | Caught by the key? | Note |
|---|---|---|
| A part or assembly file saved | **Yes**, `file_modified_utc` and `file_size_bytes` | The ordinary case |
| A referenced part edited outside the assembly | **Yes**, it has its own manifest entry | The input document's named risk, closed |
| The active configuration switched | **Yes** | |
| A component's referenced configuration switched | **Yes**, via the per-document sorted set | Would have been missed by `ManifestEntry.configuration` alone |
| A component resolved from suppressed or lightweight | **Yes**, via suppression state in the key | |
| Dump options or profile changed | **Yes** | |
| Extractor or schema version changed | **Yes** | |
| A virtual component stored inside the assembly | **Yes**, indirectly | Its bytes live in the parent, so the parent's mtime moves |
| A toolbox part regenerated in place | **Yes** if its file mtime moved | |
| **Unsaved in-memory edits** | **No** | mtime does not move until save. **Refusal**, not a key part: refuse reuse whenever the active document reports unsaved changes (`GetSaveFlag`, already consulted by `suppress-test`) and say so in the status line |
| **A partial dump (a phase aborted)** | **No** | VERIFIED that `PackageWriter.Build` continues past a failed phase and writes the package with gaps (`:38-41,142-235`). **Refusal**: add `extractor.completed`, or refuse reuse of any package carrying a phase-level `tool_error` gap |
| Clock skew or a restored-from-backup file | **No** | mtime can move backwards. The key is equality, not ordering, so this is a false **miss**, which is the safe direction |

### 9.4 `PackageIndexRow` (`run_root/package-index.json`)

One line appended per successful dump. A missing or unparseable index means **"no reuse"**, never
an error.

| Field | Type | Rules |
|---|---|---|
| `reuse_key` | str | The section 9.2 digest |
| `folder` | str | Run folder name, relative to `run_root` |
| `written_at` | datetime | Used for the "(age)" in the pane status line |
| `profile` | str | So a mismatch is rejected before any file is opened |
| `package_bytes` | int, `ge=0` | So the copy cost is predictable before it is paid |

The lookup **verifies the folder and its `package.json` still exist** before reusing, because the
index can drift from disk if a folder is deleted by hand. Fallback when the index is absent: a
bounded head scan of the N most recent folders using the `ProfileOf` technique, which is why
`reuse_key` sits near the top of `package.json`.

### 9.5 The reuse-provenance fields

VERIFIED that `chat/server.py` claims a run folder per chat and refuses a second (`RunDirInUse`,
`:233-238,1341-1381`), so **a reused package still gets its own new run folder**; reuse means copy
`package.json` and `meshes/` into it instead of dumping.

| Field | On | Type | Rules |
|---|---|---|---|
| `reused_from` | `EvidencePackage`, and mirrored onto `ReviewSession` | `str \| None` | The run folder the package was copied from. `None` means freshly dumped |
| `reused_at` | `EvidencePackage` | `datetime \| None` | When the reuse decision was made, not when the original was dumped |

**Reuse is stated in three places**: the pane status line says "Reusing the extraction from
`<folder>` (<age>)" instead of "Extracting evidence from ...", the report header states it, and
`session.json` carries it. And **the key is recomputed at reuse time** from the live document's
references now, never trusted from the file: a stored key that matches a file that has moved is the
one thing this mechanism must not do.

### 9.6 The gate this model has to support

The reused package must be **byte-identical to a fresh dump modulo `package_id`, `created_at`,
`reuse_key`, `reused_from` and `reused_at`**. Probe P3 (dump the same unchanged document twice and
diff field by field) defines the exact modulo set before the gate is run; anything P3 finds
legitimately non-deterministic joins that list **in this document**, not in the test only.

---

## 10. The carry-over finding marker (lever 11a)

### 10.1 Additive fields on `Finding`

`findings.py:66-86`, all three optional, all three added to `properties` of
`review-session.schema.json` and left out of `required`.

| Field | Type | Default | Rules |
|---|---|---|---|
| `carried_over_from` | `UUID \| None` | `None` | The session id of the run that produced the verdict. **This is the machine-readable signal**; everything else is for humans |
| `carried_over_at` | `datetime \| None` | `None` | When the carry-over decision was made, not when the verdict was first produced |
| `carry_over_key` | `str \| None` | `None` | The section 10.2 digest, stored so the decision is reproducible by hand against the package |

**`Finding.status` is not touched.** A carried `demonstrated` finding is still demonstrated; what
changed is who demonstrated it and when, which is provenance and not status. Overloading `status`
would break the scorecard's matching rules (`scorecard.py:106-142`).

### 10.2 The carry-over key, per finding

```
finding.check
Calculation.function_version (when the finding carries a calculation)
sorted(finding.component_ids)
fingerprint(package, finding.component_ids, fingerprint_kind_for(finding.check))
```

`fingerprint` and `fingerprint_kind_for` are the **existing** functions
(`exceptions.py:249-295`, `:89-91`, VERIFIED). **No second hashing scheme is written**, and that is
the DRY line to hold in code review.

### 10.3 Scope, and why it is this narrow

v1 carries over **only `rms.*`**, and within it **not
`rms.detail.individually_suppressible`** (it reads `rms_suppress_test`, `ir/models.py:508-560`, and
that array is not in the feature-tree fingerprint).

That is the only family where "the fingerprint covers every input the check reads" is defensible
from the code rather than hoped for. Every other family reads state outside both fingerprints:
`fastener.*` reads hole depths, fastener lengths and the `Thickness` custom property; `fit.*` and
the drawing checks read `DrawingSheet.dimensions` and `parse_status`; `interference.*` reads
`package.interferences` and `InterferenceSettings`; and every family reads
`EvidencePackage.gaps`, `extractor.profile`, the checklist version and `exceptions.json` (all
VERIFIED, research R18.2).

### 10.4 The two other places a carry-over is stated

- **Coverage**: a carried-over finding also writes a `CoverageItem` in the existing **`checked`**
  bucket whose `reason` starts with `"carried over from "`. Not a sixth bucket: a new bucket would
  touch the schema, the report renderer and the scorecard aggregate to carry information
  `carried_over_from` already carries.
- **The report**: the finding's heading line names the originating run, and the coverage section
  states how many findings were carried and how many were re-run, so an engineer can see at a
  glance which part of the report was not computed today (Principle VI).

### 10.5 The six guards, as data rules

| # | Rule | Where it is enforced |
|---|---|---|
| 1 | Carry only from a session with `ended_at` non-null and no `failed` coverage naming this check | The carry-over selector, before the key is even computed |
| 2 | Carry only `demonstrated` and `checked_within_scope`; re-run every `suspected` and `unresolved` | The selector. Those two statuses are where the model's judgement sits, and an `unresolved` finding with an open evidence request is exactly what a new run might resolve |
| 3 | Never carry a finding with a `disposition` | The selector. A human decision is attached; carrying it without the decision is worse than re-running, carrying it with the decision re-asserts a human's judgement |
| 4 | Never carry if `ExceptionStore.refresh` moved any exception touching these components to `needs_review` | The selector, after the refresh that already runs |
| 5 | Never carry across a profile, gap-set, checklist-version or check-version change | **The key** (`function_version` and the fingerprint) |
| 6 | Cap the carry in age or in consecutive runs | The selector, from one configured bound, stated in the report |

The invariant a test pins: `carried + re_run == len(findings)`, and every carried finding's
`carry_over_key` recomputes to the same value against the current package. The minimum bar test
mutates **one feature row** and asserts the finding is re-run rather than carried.

---

## 11. The tool tier table (lever 4)

### 11.1 The tiers

The registry is **already grouped by tier** (VERIFIED, `tools/registry.py:71` query, `:92`
measurement, `:102` check, `:116` session, `:127` bridge), named after the tables in
`contracts/agent-tools.md`. No new taxonomy is introduced; lever 4 adds a **rule per tier** and
nothing else. Byte figures measured today against this tree.

| Tier | Tools | Bytes as-is | Rule | Decidable when? |
|---|---|---|---|---|
| Package query | 15 | 10,410 | Always offered. It is how the model orients | n/a |
| Measurement | 4 | 3,706 | Always offered. It is how evidence is gathered | n/a |
| Check | 8 | **14,182** | Always offered **except** the RMS subset below. "Check tools once evidence exists" is **dropped** (see 11.2) | n/a |
| Session | 5 | 5,770 | **Never** withheld. `mark_coverage` is how coverage stays honest, and the group trims only 10 percent because it is `CoverageScope` and `SourceRef` structure | n/a |
| Bridge | 3 | 3,648 | Offered only when `context.bridge is not None`. **Already implemented today** (`ToolRegistry.functions_for`, `:485-489`), and the 32-tool baseline is the no-bridge number | at context construction |
| **RMS subset** | 6: `check_rms_part`, `check_rms_assembly`, `check_rms_equations`, `list_features`, `get_feature`, `list_equations` | **8,093 withheld, 23.8 percent of the payload**; the array goes 32 tools to 26 | Withheld when `package.features` is empty or `extractor.profile` says feature rows were not dumped. This is exactly the condition `POST /checks/rms` already refuses with `EmptyFeatureTree`; the rule is reused, not restated | **before the first turn, from the package alone** |

**The asymmetry is stated, never averaged away**: 23.8 percent off a `model_check` or part-only
package, **0 percent off a full assembly package**. Lever 4 does nothing for the main case and a
lot for the Model check tab's case.

### 11.2 What is deliberately not a tier

"Check tools once evidence exists" is a claim about the conversation, not the package. It would
change the tool array mid-session, which invalidates the OpenAI cacheable prefix for the rest of
the session (`tools_changed`, section 5), make two turns structurally different in a way the step
log does not record, and buy tokens only on multi-turn sessions that VERIFIED mostly do not happen
(`start()` plays **one** opening turn that does the whole review, `runner.py:443-460`). Dropped
(OQ-3).

**Per-turn subsets only, never per-round.** VERIFIED that both adapters build their tool encoding
once per turn before the loop (`openai_provider.py:235`, `gemini_provider.py:310`), so a per-turn
subset needs **no adapter change at all**: the wrapper's `__iter__` simply yields fewer tools.

### 11.3 `WithheldTool`

`tools/registry.py`. A withheld tool is **registered, not absent**.

```python
@dataclass(frozen=True)
class WithheldTool:
    """A tool this run did not expose. Not on the wire; still in the dispatch, so a model
    that asks for it is told why, and the report says the same thing."""

    name: str
    reason: str                 # "this package carries no feature rows, so RMS tools were not offered"
    checklist_item: str | None  # "modeling.resilience"
```

| Field | Type | Rules |
|---|---|---|
| `name` | str | The tool name exactly as it would have appeared on the wire |
| `reason` | str | A sentence an engineer reads in the report, naming the **tier rule** and the package fact that triggered it. Never "unavailable" and never a tool-name list |
| `checklist_item` | `str \| None` | The checklist item this tool would have closed. When `None`, the coverage item's `check` is `"tool." + name` |

**Behaviour**, which is the whole point of the type:

- It is **not** in `ToolDispatch.__iter__`, so no schema reaches the request. That is where the
  bytes are saved.
- It **is** in `ToolDispatch.by_name`, so a model that asks for it gets an answer rather than the
  generic unknown-name path.
- Its `call` returns an error result **and** writes an **`unresolved`** coverage item through the
  existing `ToolContext.record_coverage` (`tools/context.py:165-171`) with
  `check=<checklist_item or "tool."+name>` and `reason=<reason>`, so it lands in the bucket
  `Checklist.bucket_of` searches and closes the item **as unresolved with a sentence attached**.

**Why this is a new type rather than the existing path**: VERIFIED that today an unregistered name
goes to `ToolDispatch.call` (`registry.py:450-478`), returns `{"error": "no tool named ..."}` with
a 32-name list in the tool result, and `SessionSink.record` (`:226-253`) writes a **`failed`**
coverage item. `failed` says the tool broke (it did not; we declined to offer it) and `failed` is
deliberately excluded from the checklist's closing buckets (`agent/checklist.py:21-27`), so the
item ends `unresolved` at finalization with the generic reason and the engineer never learns we
withheld the tool (RK-5).

`ToolDispatch.tools` therefore holds two kinds of entry, `__iter__` filters and `by_name` does not:
one small explicit split in one dataclass, not a new layer. **A hallucinated name still goes to
`failed`**, and a regression test pins that.

### 11.4 The rejected alternative, recorded so the choice stays deliberate

VERIFIED that OpenAI has `tool_choice: {"type": "allowed_tools", ...}`
(`openai/types/responses/tool_choice_allowed.py`) and Gemini has
`FunctionCallingConfig(mode=ANY, allowed_function_names=[...])` (`google/genai/types.py:6224-6237,
6258-6273`). Both narrow what the model may call **without removing the schemas from the request**:
ideal for the prompt cache, **zero tokens saved**. Right mechanism for a future "focus the model"
lever; wrong one for lever 4, whose entire purpose is bytes.

---

## 12. Contract edit register

Every schema touched, with the house style it must follow. `tests/unit/test_session.py` writes a
`session.json` with `save_session` and validates it through `session_validator()` (`:42-49`) at
`:244`, `:267` and `:277`, and `tests/unit/test_runner_provider.py:773` does the same for a
runner-produced session; `review-session.schema.json` is `additionalProperties: false` at the top
level (VERIFIED), so adding `usage` or `efficiency` to `ReviewSession` without the matching schema
edit turns those tests red. That is the desired behaviour.
`tests/unit/test_schema_sync.py` compares only the **IR** pydantic models to `ir.schema.json`
(`test_export_schema_matches_the_committed_contract`, `:103-112`) - it is the test the lever 9 and
phase-timing IR bump regenerates, and it touches the session schema only at `:156-159`, where
`test_contract_files_are_valid_json_schema` checks that both contract files are themselves valid
JSON Schema.

| Contract | Style | Edit | Phase |
|---|---|---|---|
| `002/contracts/chat-events.schema.json` | `additionalProperties: false` on every body; `type` is a closed enum (VERIFIED) | Add `"usage"` to the `type` enum; add the `usage` body (section 4) with every field in `required`; add optional `usage` to the `session.ended` body's `properties`, leaving `required` as `["ended_at", "timing"]` | 1 |
| `001/contracts/review-session.schema.json` | `additionalProperties: false` at the top level; new optional fields go in `properties` and **not** in `required`, the pattern `provider_info` and `retry_of` already set (VERIFIED) | Add `usage` and `efficiency` (section 6); add `Finding.carried_over_from`, `carried_over_at`, `carry_over_key` (section 10.1); add `reused_from` | 1, then 4 |
| `001/contracts/scorecard.schema.json` | `additionalProperties: false` with **every** property also in `required`; nullable types carry "may be absent" (VERIFIED) | Add the section 8.1 `PackageScore` fields and the section 8.2 `Aggregate` fields, in `properties` **and** `required` | 1 |
| `001/contracts/ir.schema.json` | Versioned; readers reject an unsupported major (Principle IV) | `ManifestEntry.file_modified_utc` and `file_size_bytes`; `EvidencePackage.reuse_key`, `reused_from`, `reused_at`; `extractor.completed`; `extractor.phases` (dump timing). **Bump to 1.3.0** | 1b (phases), 4 (the rest) |
| `002/contracts/settings.schema.json` | | **No edit.** Lever flags do not reach the pane while the levers are being measured (section 7.2) | n/a |
| `002/contracts/chat-api.md` | | **No edit.** `GET /sessions/{chat_id}` gains nothing (section 4.3) | n/a |
| `Serve/PROTOCOL.md` | Versioned; `ping` reports the version | Add the `tessellate` command; **bump to 1.1**. The read-only guard is **not** edited: VERIFIED that `GetTessellation`, `Tessellate`, `CurveChordTolerance` and `GetBodies2` are not on the denylist and not covered by its prefixes | 4 |

### 12.1 What stays byte-identical

- A feature 001 or 002 `session.json` with no `usage` and no `efficiency` loads and validates
  against the amended session schema.
- `report.md` for a session with no usage is byte-identical to the current golden, because the
  `## Tokens` section renders only when `session.usage is not None`.
- A scorecard over a session with no usage produces nulls and does not raise.
- Every existing event type still validates unchanged against the amended events schema.

These four are the Phase 1 acceptance tests for "additive", and they are written before the fields
are added (Principle III).
