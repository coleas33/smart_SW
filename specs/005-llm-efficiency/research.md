# Research: LLM efficiency, speed, and token usage

**Feature**: `005-llm-efficiency` | **Date**: 2026-09-16 | **Plan**: [plan.md](plan.md)

Phase 0 output. Condensed from the design brief that synthesized three Opus research passes
(`instrumentation-caching.md`, `review-loop-levers.md`, `extraction-and-protocol.md`) over the
input document `docs/llm-efficiency-options.md`, plus a re-measurement pass over this tree and
over the packages installed under `reviewer/.venv/Lib/site-packages` (`openai` 3.13.0,
`google-genai` 2.23.0) done for this document rather than taken on trust from the brief.

**The owner's rule governs every section below**: instrument first, then one lever at a time
behind a flag, default off, adopted only on measured evidence with no quality regression.
Nothing here proposes turning anything on. Every lever is a design plus a flag plus a test plus
an A/B protocol plus an adoption rule, and the adoption decision is the owner's, taken against a
recorded number.

## What VERIFIED and UNVERIFIED mean in this document

- **VERIFIED**: read on 2026-09-16 in this tree at the file and line cited, or read in a package
  installed under `reviewer/.venv/Lib/site-packages` at the file and line cited, or produced by
  a script run against this tree on 2026-09-16 (every such number is marked "measured today").
  VERIFIED means *the field exists with that type, or the number came out of this tree*. It
  **never** means an API was observed behaving a certain way.
- **UNVERIFIED**: needs a live provider call, a SOLIDWORKS seat, or a timed run. Every
  UNVERIFIED claim that gates a decision appears again in R24 as a numbered probe and is not
  trusted until that probe runs.

**Providers.** OpenAI is the default and Gemini is the alternate
(`reviewer/src/swreview/agent/providers/`). Claude is not a provider of this product and no
section below assumes one.

**Scope.** The reviewer stays read-only. No lever touches what the reviewer may do; the bridge
`ReadOnlyGuard` denylist is not edited by any lever in this feature, including lever 10a
(R17.4).

---

## R0. What this feature is, and what it deliberately is not

### R0.1 The shape

Feature 005 is a measurement layer plus ten flags plus an evaluation protocol. The measurement
layer is not optional and carries no flag, because recording what a run cost is not an
experiment. Each lever is then written behind its own flag, defaulted off, measured against the
instrumented baseline, and either adopted (it becomes a default in code, not a checkbox) or kept
off with its numbers recorded.

### R0.2 Non-goals, each with the reason

1. **No lever is adopted by default in this feature without a recorded result.** Shipping a
   default is a separate per-lever decision, taken after that lever's A/B, recorded in the
   ledger (R21).
2. **No change to what the reviewer may do.** It stays read-only. VERIFIED that
   `extractor/SwReview.Extractor.Console/Guard/ReadOnlyGuard.cs:23-80` is a denylist, and no
   lever edits it.
3. **No provider beyond OpenAI and Gemini.**
4. **No quality trade accepted for tokens.** A lever that saves tokens and loses a known defect
   is kept off and its numbers are recorded.
5. **No lever flag reaches the pane settings while it is being measured.** An engineer toggling
   experiment flags mid-pilot makes the pilot's own numbers unreadable (R7.3).
6. **Out of feature 005 entirely**: lever 8 (model tiers per job, R15), lever 10b (lazy faces,
   R17.3), lever 11b (per-check input digests, R18.2), a deterministic fastener-joint enumerator
   (R12.1), and concurrent local tool execution (R13.3). Each is argued out at the lever that
   would have carried it, not dropped silently.

### R0.3 The one thing that must land first

There is no token number, no cost number and no round-trip count for any run in this tree today.
VERIFIED: `grep -rn "usage" reviewer/src/swreview/agent/providers/*.py` returns nothing, and
`TurnResult` (`agent/providers/__init__.py:187-199`) carries `reason`, `text`, `steps` and
`messages` and no usage. VERIFIED further that no agent review has been run against any
benchmark package, so **the first measurement of feature 005 is the baseline itself** (R23,
Phase 1 item 9).

---

## R1. Today's static payload, measured today rather than transcribed

### R1.1 The numbers

Measured today by a script run against this tree, building the OpenAI parameter object exactly
as `openai_provider.tool_param` does and the Gemini declaration exactly as `gemini_provider`
does:

| What | Measured today |
|---|---|
| Tools sent on every request, no bridge (`TOOL_FUNCTIONS`) | **32** |
| OpenAI `tools` array, compact JSON | **34,065 bytes** |
| Gemini function declarations (`{name, description, parameters}`), compact | **33,897 bytes** |
| With the three bridge tools (`--bridge`) | 35 tools, **37,712 bytes** |
| Tool descriptions alone (no parameter descriptions) | **14,685 bytes** |
| Same array with every description emptied (the structural floor) | **15,274 bytes** |
| Longest descriptions | `check_rms_assembly` 1,455, `check_rms_part` 1,296, `check_fastener_joint` 871, `check_interference_group` 870, `check_rms_equations` 836 |
| Largest whole tool objects | `check_axial_stack` 2,734, `check_fit` 2,413, `record_drawing_finding` 2,156, `check_hole_alignment` 1,824, `check_rms_part` 1,685 |

Per registry group (VERIFIED, `tools/registry.py:71` query, `:92` measurement, `:102` check,
`:116` session, `:127` bridge; bytes measured today):

| Group | Tools | Bytes as-is | Bytes at a 160/90 cap |
|---|---|---|---|
| Package query | 15 | 10,410 | 8,083 |
| Measurement | 4 | 3,706 | 2,367 |
| Check | 8 | **14,182** | 8,203 |
| Session | 5 | 5,770 | 5,184 |
| Bridge | 3 | 3,648 | 2,589 |

Two readings. The **check group alone is 42 percent of the payload** and is also the most
trimmable, so levers 2 and 4 point at the same eight tools. The **session group barely trims**
(10 percent), because it is `CoverageScope` and `SourceRef` structure, and it can never be
withheld, because `mark_coverage` is how coverage stays honest.

### R1.2 Two corrections to the input document, and one to the brief

`docs/llm-efficiency-options.md` records **29 tools and 32,435 bytes** and names a different set
of longest descriptions. The RMS tools have landed since it was written. **The baseline table
must be regenerated from the tree, not transcribed**, and `docs/llm-efficiency-options.md` gets
the corrected row in the same change so the input document and the tree agree (RK-19).

The design brief records 37,709 bytes with the bridge and 34,248 bytes for Gemini; measured
today those are **37,712** and **33,897**. The differences are serialization-wrapper artifacts of
a few hundred bytes and they make the same point the brief makes: **a transcribed number goes
stale, so the regenerating script is committed as a test** (`tests/unit/test_tool_payload.py`)
and the document quotes the test's output. That test is worth writing in Phase 1 whether or not
lever 2 is ever adopted, because it stops a new tool quietly adding 2 KB to every request.

### R1.3 Determinism of the payload

VERIFIED: the serialized tool array has an identical sha256 under `PYTHONHASHSEED` 0, 1 and
12345. `strictify` (`agent/providers/schema.py:216-259`) and `gemini_adapt` (`:353-382`) use no
set iteration. This is what makes the OpenAI cacheable prefix stable across processes (R10.2).

### R1.4 Bytes are not tokens

At the roughly 4 bytes per token the input document itself implies, 34,065 bytes is roughly
8,500 tokens per request (**UNVERIFIED** as a token count), and a review with 60 tool calls
spends roughly 510,000 input tokens on tool schemas alone. **The first instrumented run replaces
the estimate with a real number.** No decision in this feature rests on the estimate.

---

## R2. OpenAI: exactly which usage fields exist

VERIFIED, `openai/types/responses/response_usage.py`, whole file, 47 lines, read today:

| Field | Type as annotated |
|---|---|
| `input_tokens` | `int` |
| `input_tokens_details.cached_tokens` | `int` ("retrieved from the cache") |
| `input_tokens_details.cache_write_tokens` | `int` ("written to the cache") |
| `output_tokens` | `int` |
| `output_tokens_details.reasoning_tokens` | `int` |
| `total_tokens` | `int` |

VERIFIED that `Response.usage: Optional[ResponseUsage]` (`openai/types/responses/response.py`).

**Streaming carries the same object.** VERIFIED: `ResponseCompletedEvent.response` and
`ResponseIncompleteEvent.response` are both `Response`
(`openai/types/responses/response_completed_event.py`, `response_incomplete_event.py`), and
those two events are exactly what our adapter already captures as `final` (VERIFIED,
`agent/providers/openai_provider.py`, `_respond`). **No `stream_options` and no `include` flag is
needed on the Responses API**, and there is no separate usage-only stream event in this SDK
version (VERIFIED by absence under `openai/types/responses/`).

**`reasoning_tokens` is a subset of `output_tokens`** (VERIFIED from the field's own description:
"a detailed breakdown of the output tokens"). Containment of `cached_tokens` inside
`input_tokens`, and of the sub-counts inside `total_tokens`, is **UNVERIFIED** in the package and
is probe L1 (R24). That containment is what makes "cached share" meaningful, so it is asserted by
a live test rather than assumed.

---

## R3. Gemini: exactly which usage fields exist

VERIFIED, `google/genai/types.py:8445-8496`, `GenerateContentResponseUsageMetadata`, read today.
**Every field is `Optional[...] = None`.** VERIFIED that
`GenerateContentResponse.usage_metadata: Optional[GenerateContentResponseUsageMetadata]`
(`types.py:8612`).

| Field | Meaning, from the package's own description |
|---|---|
| `prompt_token_count` | total prompt tokens; "When `cached_content` is set, this **also includes** the number of tokens in the cached content" |
| `cached_content_token_count` | tokens in the cached content used for this request |
| `candidates_token_count` | tokens in the generated candidates |
| `thoughts_token_count` | tokens that were part of the model's generated "thoughts" output |
| `tool_use_prompt_token_count` | "tokens in the results from tool executions, which are provided back to the model as input" |
| `total_token_count` | "the sum of `prompt_token_count`, `candidates_token_count`, `tool_use_prompt_token_count`, and `thoughts_token_count`" |

### R3.1 Two arithmetic facts that are opposites of each other

Both VERIFIED from those field descriptions, and both of which a naive reader gets wrong:

- **`cached_content_token_count` is inside `prompt_token_count`.** Adding the two double counts.
- **`tool_use_prompt_token_count` is outside `prompt_token_count`**; `total_token_count`'s own
  description lists it as a separate addend. Our reviewer feeds every tool result back as input,
  so on Gemini this is a first-class number, and dropping it understates our input cost by
  whatever 60-odd tool results weigh.

Similarly asymmetric across providers: OpenAI's `reasoning_tokens` is a **subset of**
`output_tokens`, while Gemini's `thoughts_token_count` is a **separate addend** of the total. A
single "output tokens" column across providers compares two different quantities.

**The rule that follows**: record the raw provider fields; derive any cross-provider comparison
explicitly, and only on `total_tokens`, which both providers define as the whole bill (RK-3).

### R3.2 Streaming: the SDK does not aggregate

VERIFIED: `google/genai/models.py:1718` and `:1757` copy `usageMetadata` straight through per
chunk, and nothing anywhere under `google/genai/` merges it. So the adapter must choose an
aggregation. **"Last chunk that carries usage wins"** is correct under both "cumulative" and
"only the final chunk carries it", and wrong only under "each chunk is a delta". That last case
is **UNVERIFIED** and is probe G3.

---

## R4. The rule that decides the whole measurement layer: unknown stays unknown

### R4.1 The reproduction, run today

```
python -c "from openai.types.responses.response_usage import ResponseUsage; \
u = ResponseUsage.construct(input_tokens=100, input_tokens_details={'cached_tokens':64}, \
  output_tokens=10, output_tokens_details={'reasoning_tokens':4}, total_tokens=110); \
print(u.input_tokens_details.cache_write_tokens)"
```

VERIFIED, run today against the installed package: it prints **`None`**, while
`cached_tokens` prints `64`.

The SDK builds response models with `BaseModel.construct` (`openai/_models.py:231-259`), which
sets any field the server omitted to the field default, and a required field's default is `None`.
`cache_write_tokens` is new, and an endpoint or model that does not report it yields `None` even
though the annotation says `int`.

### R4.2 The three consequences

1. **Every token field is `int | None` on our side.** A reader typed `int` raises `TypeError` on
   the first sum.
2. **`None` is never coerced to `0`.** "Zero cached tokens" and "the endpoint did not say" are
   different facts, and collapsing them is a Principle I violation.
3. **A sum over rounds where any round reported `None` for that field is `None`, not a partial
   sum.** A partial sum silently understates and no reader can tell. This is the same discipline
   `Timing.baseline_minutes` already follows (VERIFIED, `report/session.py:118`).

This is RK-1 and it is the single rule the measurement-layer tests are built around (R6.7).

---

## R5. Where usage is read, and why it is an event per round

### R5.1 The record belongs beside `EffortMapping`

`TokenUsage` goes in `agent/providers/__init__.py`, beside `EffortMapping`, for the reason that
module already states about `EffortMapping`: it is provider-neutral, it is produced by adapters,
and `report/session.py:22` already imports across that boundary (VERIFIED). Any other home means
two definitions. The full field list and the provider mapping are in
[data-model.md](data-model.md) section 2.

### R5.2 OpenAI insertion point

Immediately after `response = self._respond(...)` at the top of the `run()` loop body, before
`raw_output = [...]`. VERIFIED: `run()` is a `while True` loop and `_respond` is one HTTP request
per iteration, so **a turn with 6 serial tool calls is 7 requests and usage is per round, not per
turn**.

Every sub-field is read with `getattr(..., None)` rather than attribute access, because
`input_tokens_details` itself can be `None` on a constructed response (R4.1).

### R5.3 Gemini insertion point

Inside `_stream`. `_Round` gains `usage: types.GenerateContentResponseUsageMetadata | None`, and
the chunk loop reads usage **outside** the candidates loop:

```python
for chunk in stream:
    if chunk.usage_metadata is not None:
        usage_metadata = chunk.usage_metadata   # last one wins
    for candidate in chunk.candidates or []:
        ...
```

This matters because the current loop body only runs for chunks that have candidates
(`for candidate in chunk.candidates or []`), so **a final chunk carrying usage and no candidate
would be silently dropped**. Probe G3 settles the aggregation (R3.2).

### R5.4 Why usage is a per-round event and not a field on `TurnResult`

This is the single design decision in the measurement layer, and it is decided by the failure
path. Both adapters raise out of the round loop on a provider error (`openai_provider.py`
`_respond` raises `OpenAIProviderError`; `gemini_provider.py` `_stream` raises through
`self._report`). A design that carries usage only on `TurnResult` therefore **reports zero cost
for the turn that cost the most**: five successful rounds followed by a rate limit on the sixth.
`ReviewRun._run_turn`'s `except Exception` branch finalizes and re-raises and has no `TurnResult`
to read.

So: **a new `usage` event per model round trip, emitted by the adapter**. `EventSink.emit` opens,
appends and closes per event precisely so the stream survives the process dying mid-review, which
means the five paid rounds are already on disk (RK-2).

### R5.5 `round_index`, which is also the round-trip counter

`round_index` is the adapter's own per-turn counter, exactly the convention
`tool.started.step_index` already uses, and for the reason the module docstring gives ("Events
carry no sequence number here"): an adapter sees one turn and cannot know a session-level number.
Turns are delimited by the existing `turn.ended` events, so no turn number is needed in the body
and the runner does not have to enrich an adapter's event, which would be the
clever-not-explicit option.

`round_index` also delivers the **round-trip counter that levers 5, 6 and 7 are unmeasurable
without**. `TurnResult.steps` counts tool calls, which is a different number, and with lever 6 on
the two diverge by exactly the amount lever 6 is trying to save.

---

## R6. Where usage lands: session, report, scorecard, and the contract edits

### R6.1 The session

`ReviewSession.usage: SessionUsage | None = None`, holding `rounds`, `turns`, `totals` and
`by_turn`. Produced by a `UsageLedger` listener on the `EventSink` (`EventSink` already takes
`listeners`, VERIFIED), written in `finalize()` before `save_session`. One accumulator, one write
point, and it works on the failure path because `_run_turn`'s `except` branch calls `finalize()`
before re-raising.

### R6.2 The report

`_render_timing` (`report/markdown.py:450-461`) gains a `## Tokens` sibling rendered **only when
`session.usage is not None`**, so every feature 001 and 002 golden report stays byte-identical
for a session without usage. Same discipline `record_partial_evidence` already follows.

### R6.3 What does not change

`GET /sessions/{chat_id}` (`ChatSession.public()`, `chat/sessions.py:302-318`) gains nothing. The
pane gets usage from the stream and `session.json` is the record; adding it to `public()` would
be a third copy of the same numbers.

### R6.4 The fake provider emits usage too

`ScriptedTurn` gains `usage: TokenUsage | None` with a fixed synthetic default, so runner,
ledger, report and scorecard paths are exercised with no network and a test can assert exact
totals. The fake's contract is "nothing is random" (VERIFIED, `providers/fake.py` docstring) and
a synthetic constant keeps that.

### R6.5 The scorecard

`PackageScore` gains `usage`, `round_trips`, `cached_input_share`, `wall_clock_s` and
`seconds_to_first_finding`. The last needs **no new recording**: both `session.started` and the
first `finding` event already carry `at` timestamps (VERIFIED, `AgentEvent`,
`providers/__init__.py:152`), and the scorecard reads `events.jsonl` beside the `session.json` it
already reads. That is the whole of the "wall clock to first finding" metric the protocol asks
for, and it is the number an engineer feels. `score_run` gains one file read per package and no
answer-key contact, so Principle VI and FR-025 are untouched.

`Aggregate` gains the summed counts under the same "any null makes the sum null" rule, plus
`median_seconds_to_first_finding` and `packages_with_usage` (mirroring the existing
`packages_with_timing`, which is the precedent for "how many packages contributed").

`render_scorecard_md` gains **three** columns: total tokens, cached share, round trips. Not seven;
the markdown is a scan and `scorecard.json` holds the detail.

### R6.6 The contract edits, which are not free

VERIFIED: `specs/002-task-pane-assistant/contracts/chat-events.schema.json` sets
`additionalProperties: false` on **every** event body and the top-level `type` is a closed enum,
so a new event type and a new body field are both contract edits.
`specs/001-agentic-design-review/contracts/review-session.schema.json` is
`additionalProperties: false` at the top level, with `provider_info` and `retry_of` already
established as the pattern for a new optional field: **added to `properties`, left out of
`required`**, which keeps every feature 001 session valid.
`contracts/scorecard.schema.json` uses the opposite house style (every property also in
`required`, nullable types saying "may be absent"), so its additions follow that.

VERIFIED that what holds the **session** schema and `ReviewSession` together is the written-session
validation in `reviewer/tests/unit/test_session.py` (`:244`, `:267`, `:277`, through the
`session_validator()` helper at `:42-49`) and `tests/unit/test_runner_provider.py:773`, against a
`review-session.schema.json` that is `additionalProperties: false` at the top level, so a field
added to the model without the schema edit turns those tests red. That is the desired behaviour.
`test_schema_sync.py` is **not** that test: it compares only the **IR** models to `ir.schema.json`
(`test_export_schema_matches_the_committed_contract`, `:103-112`), and touches the session schema
only at `:156-159`, where `test_contract_files_are_valid_json_schema` checks that both contract
files are valid JSON Schema. The full edit register is in [data-model.md](data-model.md)
section 12.

### R6.7 Measurement-layer tests, written first (Principle III), none needing a key

1. `usage_of(Response)` maps all five OpenAI fields; a response built with
   `ResponseUsage.construct` omitting `cache_write_tokens` yields `None`, not 0 (the exact
   reproduction in R4.1).
2. `usage_of(usage_metadata)` maps all six Gemini fields; an all-`None` `usage_metadata` yields
   an all-`None` `TokenUsage` and never a zero.
3. A Gemini stream whose final chunk carries `usage_metadata` and **no** candidates records that
   usage.
4. A turn that raises on its third round still records rounds 1 and 2 in `session.usage`.
5. `SessionUsage` summing: one `None` in one round makes that total `None`.
6. A `usage` event validates against the amended `chat-events.schema.json`, and every existing
   event type still validates unchanged.
7. A feature 001 `session.json` with no `usage` loads and validates against the amended session
   schema.
8. A scorecard over a session with no usage produces nulls and does not raise.
9. `report.md` for a session with no usage is byte-identical to the current golden.
10. `tests/unit/test_tool_payload.py`: the curated array is under a stated byte ceiling and no
    single tool object exceeds a per-tool ceiling (R1.2).

---

## R7. The common seam every lever shares

### R7.1 One flag carrier

Six levers each inventing a setting, a session record and a scorecard grouping is exactly the
repetition Principle V forbids. **One frozen `EfficiencySettings` model in `agent/settings.py`**,
beside `ProviderSettings` (VERIFIED, `settings.py:176-192`), which is already the single place
per-provider defaults live. Every field defaults to off. The fields are in
[data-model.md](data-model.md) section 7.

Threaded as **one keyword argument** through `start_review` (`runner.py:595-651`) and held on
`ReviewRun` (`:394-424`), exactly as `effort` and `max_steps` already are, and as one argument
through `run_benchmark` (`benchmark/runner.py:69-76`) and `cli._review_fn` (`cli.py:1341-1364`).
The alternative, one plumbed parameter per lever, is ten signature changes across three call
sites and ten separate contract edits (OQ-1).

### R7.2 The session must record which levers were on

`ReviewSession` gains an optional `efficiency` field, modelled on `provider_info`, optional for
the same reason: a session written before the field existed has none. Without it **no results row
can be attributed to a configuration and the A/B table cannot be rebuilt from the run folder**.

This is the strongest argument for doing R7.1 and R7.2 in Phase 1 with the measurement layer: it
is one contract edit and one golden refresh paid once for all ten flags instead of ten times.

### R7.3 The flags do not reach the pane

The pane's `settings.schema.json` does **not** grow lever checkboxes while the levers are being
measured. An engineer toggling experiment flags mid-pilot makes the pilot's own numbers
unreadable. The CLI flag (`swreview benchmark run --lever parallel_tool_calls`) is enough for the
benchmark, and **adopted levers become defaults in code, not checkboxes**.

---

## R8. The interaction matrix, because levers are not independent in effect

These couplings will cause trouble if the levers are implemented separately and then combined
without thought. This table is the reason the ledger has an "other levers on" column (R21).

| Pair | Interaction | What the design does about it |
|---|---|---|
| 2 and 3 | Lever 2 moves roughly 10 KB from the tool array into the system prompt. Both are in the cacheable prefix on OpenAI, so lever 2's saving is partly already captured by lever 3 on the second and later requests. | Measure lever 2 with lever 3 **off**, and record which other levers were on in the results row. `EfficiencySettings` on the session is what makes this auditable. |
| 4 and 3 | A tool array that changes mid-session invalidates the OpenAI prefix from that point. | Package-decidable tiers only, fixed for the whole session (R11.2). Removes the interaction entirely. |
| 5 and 7 | Lever 5 closes checklist items before the first turn; with 7 also on, a package whose deterministic checks close every item stops the turn almost immediately, before the model looks at fit, stack or drawings. | Never run 5 and 7 in the same A/B arm until each is gated alone. When combined, the strict stop predicate (R14.3) is not optional; it is what stops a pre-run from ending the review. |
| 5 and 2 | Lever 5 makes the RMS descriptions less load-bearing, and those are lever 2's biggest trims. | If both are wanted, gate 5 first, then re-measure 2's quality risk against the post-5 baseline. |
| 6 and 5 | Lever 5 removes the round trips lever 6 would have saved. Measured together, 6 looks worthless. | Measure 6 against the lever-5-off baseline and record it. |
| 6 and 7 | With batching on, the round that closes the last checklist item may also contain three more calls; mechanism C stops the *next* round, so those three still run. | Correct and intended. Stated in the spec so the measured saving is not read as a bug. |
| 4 and 5 | If a tier withholds RMS tools because the package has no feature rows, lever 5 has nothing to pre-run for RMS either, and both write coverage saying so. | One function decides "this package cannot be graded for RMS, and here is the sentence saying why". One reason, one writer. |
| 9 and 3 | A Gemini explicit cache cannot be keyed to a package today because `PackageId = Guid.NewGuid()` on every dump (VERIFIED, `Dump/PackageWriter.cs:136`). If lever 9 introduces a content key, lever 3 gets cross-session cache reuse for free. | Cross-referenced, not a reason to do 9 early. |

---

## R9. Lever 2: trim tool descriptions

**Flag**: `EfficiencySettings.trim_tool_descriptions`.

### R9.1 The honest ceiling

Of 34,065 bytes sent today, **15,274 (45 percent) is JSON structure** and lever 2 cannot reach
it; only lever 4 or a schema change can. 18,791 bytes (55 percent) is prose. Caps measured today:

| Cap (tool description / parameter description) | Bytes | Saved |
|---|---|---|
| none (today) | 34,065 | 0 |
| 300 / 120 | 27,158 | 20 percent |
| 200 / 100 | 25,020 | 27 percent |
| **160 / 90** | **23,834** | **30 percent** |
| 120 / 70 | 22,450 | 34 percent |
| everything stripped (the floor) | 15,274 | 55 percent |

So roughly 30 percent of the tool payload, about 2,550 tokens per request at the 4-bytes-per-token
estimate, about 153,000 tokens over a 60-call review (**UNVERIFIED** as token counts; R1.4). This
is below the input document's "a third to a half" at the upper end and the document is corrected
with this row.

Note also that the three largest tool *objects* are not the three longest *descriptions*:
`record_drawing_finding` is 2,156 bytes carrying 268 characters of description and
`mark_coverage` is 1,576 carrying 244. Those are structure and no trimming touches them.

### R9.2 The design: split the docstring, do not copy it

VERIFIED: there is exactly one path from docstring to schema. `tool_spec(fn)`
(`agent/providers/schema.py:402`) reads the docstring, `parse_docstring` (`:99`) splits body from
`Args:` entries, `canonical_schema` (`:150`) refuses a parameter with no `Args:` entry, and both
adapters read `tool.description` directly. **The docstring is the schema and there is no second
place a description is written.** That is the asset this lever must not destroy.

VERIFIED that `parse_docstring` already recognises Google-style section headers and already
collects `Notes:` into a `sections` dict and then throws it away. So:

- The tool description becomes the **first paragraph**. Everything from the second paragraph
  moves under a `Notes:` header **in the same docstring**.
- `parse_docstring` returns the `Notes:` text as a third value instead of discarding it.
- `ToolSpec` (`schema.py:389-397`) gains a `notes: str` field beside `description`.
- `build_system_prompt` (`runner.py:118-128`) gains a `## Tool notes` block rendered from the
  same `ToolSpec` objects the adapter is about to be handed.

Two properties make this right rather than clever. **Nothing is written twice**: the text still
lives in exactly one docstring, so a note that goes stale goes stale in one place. This is the
difference from "shorten the docstrings and paste the removed text into `system_v1.md`", which
would create the duplication this codebase has so far avoided. And **the system prompt is the
cacheable half**: moving 10 KB out of the tool array (which lever 4 wants to vary) into the
system prompt (which never varies) is the right direction for lever 3 as well.

### R9.3 What the long descriptions actually contain

Three kinds of text mixed together:

1. **What the tool is.** Must stay on the tool; it is what the model reads to choose among 32.
2. **Policy already in the system prompt.** `check_fastener_joint`'s "drill depth is not thread
   depth" is already in `system_v1.md` under "Things you must not do" (VERIFIED).
3. **Call-protocol warnings that fire once per session.** `check_rms_part` spends 1,296
   characters on a tool with one optional parameter.

Only the second and third kinds move.

### R9.4 Cap by construction, not by truncation

A run-time cap that truncates mid-sentence produces "...and never used as o" and the model reads
the fragment as complete. Instead, **each docstring is split at an existing paragraph boundary
chosen so the first paragraph is already under the cap, with no rewording**, and a unit test fails
the build when a first paragraph is over **160** characters or an `Args:` entry is over **90** -
the caps the table at R9.3 measures the 23,834-byte / 30 percent row at, so the enforced cap and
the quoted saving are the same number. Explicit over clever, the constraint is where a reviewer
sees it, and the measured "on" arm is a set of descriptions a human wrote rather than a machine's
amputation of them. A docstring that cannot be split under the cap without rewording is a **named
lever 2 exception** in the ledger row, not a silent rewrite.

**Superseded (OQ-2 resolved):** this section previously said the "off" arm was not recoverable by
flipping a flag and that the A/B therefore ran across two commits. It is recoverable and it must
be: with the flag off the adapter and the MCP toolset are handed the **rejoined** string, byte-equal
to the pre-split docstring body (FR-033, FR-039), so the post-split commit with every flag off
reproduces the pre-split wire bytes and SC-007 holds. Both arms run from one commit and `compare`
grants lever 2 no exception (contracts/levers.md lever 2, contracts/ab-harness.md sections 1-3).

### R9.5 The cache trap

VERIFIED: `_SPECS` is process-global and keyed by function (`tools/registry.py:257-261`). A flag
read inside `spec_for` means two runs in one process (the benchmark runner, the test suite)
silently share the first run's setting. **The flag must be applied after `spec_for`**, in the
`RecordedTool` wrapper or in `ToolRegistry.dispatch` (`:491-525`), where the run's settings are
already in scope.

### R9.6 Touch points, tests, metric, adoption

**Touch points**: `agent/providers/schema.py` (`parse_docstring`, `ToolSpec`, `tool_spec`),
`agent/runner.py` (`build_system_prompt`), `tools/registry.py` (the wrapper), 35 docstrings
across `tools/`.

**Tests**: the byte budget test; a **no-loss test** asserting `description + notes` after the
split equals the old full description modulo whitespace, with the old text pinned in the test
file so it is a diff against a known state rather than a tautology; a prompt test (flag on
contains every tool's notes exactly once, flag off contains none); a FakeProvider test asserting
two `session.json` files are identical except for the recorded settings; adapter tests asserting
the params carry the trimmed description.

**A/B metric**: bytes and tool count per provider encoding, off and on (deterministic, exact, no
API call, runs in CI); then the benchmark scorecard for quality. **The thing that actually needs
watching is which tool the model picks**, not the token count which is arithmetic. Add a
histogram of tool names from `session.steps` per run. A trim that changed the answer will usually
show first as a call-pattern change ("the model stopped calling `check_rms_part` with no argument
and started calling it per document"), which the scorecard would not catch. **UNVERIFIED**
whether this shows up at all.

**Adoption rule**: the general gate (R20.3), plus the tool-name histogram must not show a check
tool dropping out of the model's repertoire.

---

## R10. Lever 3: prompt caching

**Flags**: `EfficiencySettings.prompt_cache_key` (OpenAI),
`EfficiencySettings.gemini_explicit_cache` (Gemini).

### R10.1 The reframing this research produced

Our OpenAI prefix is **already stable**, so we are probably already getting substantial implicit
cache hits that we simply cannot see.

### R10.2 Three facts, all VERIFIED by reading

1. `system` is built once in `start_review` and never mutated; its three parts
   (`prompts/system_v1.md`, `checklist.render()`, `json.dumps(package_summary(package))`) are all
   deterministic.
2. `tool_params` is byte-identical every turn and across processes (R1.3).
3. History is append-only: `_run_turn` does `self.messages = [dict(m) for m in result.messages]`,
   `_encode_assistant` deep-copies and replays raw output items verbatim, and `answer_evidence`
   mutates `session.findings` and never `self.messages`.

Every round trip inside a turn extends an append-only prefix, so rounds 2..n of a 7-request turn
should hit on everything rounds 1..n-1 sent (**UNVERIFIED** as observed behaviour; probe L2).
**So lever 3 on OpenAI is not "add caching"; it is "name the cache, record the diagnostics, and
stop other levers from breaking what we already have".**

### R10.3 OpenAI, what the installed package offers

All VERIFIED, read today in `openai/types/responses/`:

- `prompt_cache_key: Optional[str]` (`response_create_params.py:158-163`; a named parameter at
  `resources/responses/responses.py:151`), echoed on the response at `response.py:421`.
- `prompt_cache_options` (`response_create_params.py:165-175`, `:385-411`;
  `Response.prompt_cache_options` at `response.py:428`) with `mode` (`implicit` default or
  `explicit`), `ttl` (`"30m"`, currently the only supported value) and `comparison_response_id`,
  stated as "supported for `gpt-5.6` and later models", which is our default model.
- `prompt_cache_retention: Optional[Literal["in_memory", "24h"]]` (`response.py:434-452`) is
  **deprecated** in favour of `prompt_cache_options.ttl`.

### R10.4 The highest-value thing in the package: `PromptCacheDiagnostics`

VERIFIED, `openai/types/responses/response.py:194-241`, field at `:418`. It is a discriminated
union on `type`:

| Variant | Carries |
|---|---|
| `cache_hit` | nothing but the type |
| `cache_miss` | `cache_missed_tokens: int`, `reason`, `comparison_reusable_tokens: int \| None` |
| `comparison_response_not_found` | nothing but the type |
| `unavailable` | nothing but the type |

The miss `reason` enum, VERIFIED verbatim at `response.py:204-213`:

```
model_changed | prompt_cache_key_changed | tools_changed | text_format_changed |
reasoning_effort_changed | verbosity_changed | context_compacted | input_changed |
service_tier_changed
```

That enum **is** the authoritative list of what breaks the prefix, straight out of the installed
SDK, and it is requested by setting `prompt_cache_options.comparison_response_id` to the previous
response's id. It turns "why did we miss" from a guess into a recorded field, and it is the
instrument that **prices lever 4 before lever 4 is written**: a tier change shows as
`tools_changed` with a `cache_missed_tokens` number.

### R10.5 The cache key must survive a process restart

The pane restarts the backend on a settings save and resumes the same run folder. Use
`prompt_cache_key = str(session.session_id)`, already persisted in `session.json`. A
process-local random value would look identical and silently drop every hit after a restart,
which would show up as `prompt_cache_key_changed`, which is precisely why the diagnostics are
worth recording.

### R10.6 What would break our prefix, ranked by how likely we are to do it to ourselves

1. **Lever 4 changing the tool list mid-session** (`tools_changed`). Designed-in; must be
   measured with diagnostics before adoption. R11.2 removes it by construction.
2. **Lever 2 toggled mid-session.** Safe if the flag is read once at `start_review`.
3. **Anything per-turn put into `system`** (a coverage digest, open checklist items, a
   timestamp), which invalidates the prefix for the whole session. This is the reason lever 5's
   digest goes in the first user message and not the system prompt (R12.2).
4. **Effort changed mid-session** (`reasoning_effort_changed`). The pane refuses a settings save
   during a turn but not between turns.
5. **Lever 8's two models**, meaning two prefixes and two caches (R15).

`parallel_tool_calls` is a request field, not prompt content, and does not appear in the miss
enum, so flipping it should not break the prefix (**UNVERIFIED**, probe L5).

The 1024-token minimum cacheable prefix is **not stated anywhere in the installed package**
(**UNVERIFIED**). Our prefix is far above any plausible threshold, so it is an unstated number,
not a risk.

### R10.7 Gemini explicit caching, as installed

All VERIFIED, read today:

- `client.caches.create(model, config)` returning `types.CachedContent`
  (`google/genai/caches.py:1144-1166`).
- `CreateCachedContentConfig` (`types.py:16434-16484`) carries `contents`, `system_instruction`,
  **`tools`**, `tool_config`, `display_name`, `ttl`, `expire_time`; `ttl` is a duration string
  ending in `s`.
- The returned `CachedContent.usage_metadata.total_token_count` is the denominator for "what
  fraction of the prefix did we actually cache".
- Reference it with `types.GenerateContentConfig(cached_content=<name>)` (`types.py:6612-6617`), a
  plain `str` on the same config `_config()` already builds.
- Lifecycle is `caches.get`, `caches.update` (extend the ttl), `caches.delete`, `caches.list`
  (leak cleanup).

**`tools` being cacheable is the whole point**: 33,897 bytes of function declarations (R1.1) is
the bulk of what we resend.

### R10.8 The trap, which is the highest-risk change in this lever

When `cached_content` is set, the fields that were cached must **not** also be sent on the
request, and the SDK does not enforce this (VERIFIED by grep: no validation anywhere in
`google/genai/`), so the failure is a 400 at run time and not a type error. Our `_config()`
always sets `system_instruction`, `tools`, `automatic_function_calling`, `thinking_config` and
`max_output_tokens`, so a cached run needs a second config shape:

```
cached:   system_instruction=None, tools=None, cached_content=cache.name
uncached: system_instruction=system, tools=[Tool(function_declarations=...)]
both:     automatic_function_calling, thinking_config, max_output_tokens
```

`AUTOMATIC_FUNCTION_CALLING_DISABLED` stays on the cached path for the reason the module
docstring gives: our loop runs every tool call, so the SDK must not. **A wrong branch does not
degrade, it 400s the whole review** (RK-18), which argues for the flag being read once at
`start_review` and for **one function with a single `cache_name: str | None` argument building
both shapes**, tested both ways, rather than an `if` sprinkled through `_config`.

TTL: bound it (1800s) and delete on `ReviewRun.close()`. A crashed process leaks one entry until
the TTL expires, which makes the leak cheap and self-healing. A long TTL plus a missing delete is
a standing bill nobody sees.

### R10.9 Gemini explicit caching may be pointless, and one measurement decides

Gemini reports implicit cache hits through the same `cached_content_token_count` field. If a
plain instrumented run already shows a healthy value on `gemini-3.5-flash`, the entire explicit
lifecycle (create, branch the config, extend, delete, handle a leaked cache, handle the 400) buys
little and costs real complexity. **Probe G4 gates whether any Gemini explicit-caching code is
written at all**, and it is available the day the measurement layer ships.

### R10.10 Touch points, tests, metric, adoption

**Touch points**: `openai_provider.py` `_respond` (add `prompt_cache_key`, optionally
`prompt_cache_options`, read `prompt_cache_diagnostics` onto the `usage` event body);
`gemini_provider.py` `_config` (the two-shape function) plus a cache lifecycle owned by
`ReviewRun`.

**Tests**: a **prefix-stability regression test** that fails if `system` or the tool list changes
within a session (this is the real deliverable for OpenAI); the two-shape config function tested
both ways with no network; a cached-run test asserting `system_instruction` and `tools` are
absent from the request when `cached_content` is set; a cache-delete-on-close test; a test that a
crashed close still leaves a bounded TTL.

**A/B metric**: cached input share per run (`cached_input_tokens / input_tokens`, well defined for
both providers only because in both, cached is contained in input; the OpenAI containment is
**UNVERIFIED** and is asserted by probe L1). Plus the recorded miss reasons and
`cache_missed_tokens`.

**Adoption rule**: the general gate, **with no exception** (superseded: this section previously
made lever 3 adoptable on probe L2 alone). `Decision` is computed from the scorecards by the
FR-028 rule, and probe L2's answer lives in the hand-written `probe-log.md`, not in a scorecard, so
it cannot enter the computed column at all (FR-024, FR-027, SC-009). Under 20 percent the row
computes `keep off`, and the observability case - the prefix hits, the key survives a restart, and
we can now see both - is carried in `decision_reason` and signed in `owner_signed_off`. Gemini
explicit caching is written **only if** G4 shows implicit caching is not already delivering.

---

## R11. Lever 4: tiered tool exposure

**Flag**: `EfficiencySettings.tool_tiers`.

### R11.1 More already exists than the baseline assumes

VERIFIED: the registry is already grouped by tier (`tools/registry.py:71` query, `:92`
measurement, `:102` check, `:116` session, `:127` bridge), named after the tables in
`contracts/agent-tools.md`, so **no new taxonomy is needed**. **One tier is already conditional**:
`ToolRegistry.functions_for(context)` (`:485-489`) adds bridge tools only when
`context.bridge is not None`, so "bridge tools only on the workstation" **is already
implemented** and the 32-tool number is the no-bridge number. A per-turn `ToolSet` wrapper is
already a shipped pattern: `StoppableTools` (`chat/server.py:355-379`) implements `__iter__`,
`__len__` and `call`, which is the whole `ToolSet` protocol.

### R11.2 Scope: package-decidable tiers only

Two of the baseline's three rules are decidable deterministically before the first turn:

- **RMS tier**: `package.features` empty (`ir/models.py:662`) or `extractor.profile` (`:619`)
  says what was dumped. This is exactly the condition `POST /checks/rms` already refuses with
  `EmptyFeatureTree`, so the rule is already written down; reuse it rather than restate it.
  Withholding `check_rms_part`, `check_rms_assembly`, `check_rms_equations`, `list_features`,
  `get_feature` and `list_equations` removes **8,093 bytes, 23.8 percent of the payload**, and
  takes the array from 32 tools to 26 (measured today).
- **Bridge tier**: already done.

One is **not** decidable before the first turn and is **dropped from lever 4 entirely**: "check
tools once evidence exists" is a claim about the conversation, not the package. Withholding check
tools from turn 1 and adding them from turn 2 invalidates the OpenAI prefix for the rest of the
session, makes the two turns structurally different in a way the step log does not record, and
conflicts with how a review actually runs: `start()` (`runner.py:443-460`) plays **one** opening
turn that does the whole review, and there is no turn 2 unless the engineer types something. The
waste it is betting against (the model flailing early) is attacked far better by lever 5 (OQ-3).

### R11.3 Per-turn subsets only, not per-round

VERIFIED: both adapters build their tool encoding once per turn before the loop
(`openai_provider.py:235`, `gemini_provider.py:310`), so a per-turn subset needs **no adapter
change at all**: the wrapper's `__iter__` yields fewer tools. A per-round subset would need both
adapters to rebuild their encoding each round, and on Gemini to rebuild `GenerateContentConfig`
per round, for a small marginal saving, plus a new axis of non-determinism in the step log.

### R11.4 A withheld tool must be unresolved coverage, never a silent miss

**Today's behaviour is wrong for this.** VERIFIED: a call to an unregistered name goes to
`ToolDispatch.call` (`registry.py:450-478`), returns `{"error": "no tool named ..."}`, and
`SessionSink.record` (`:226-253`) writes a **`failed`** coverage item. Three things are wrong with
that as the answer for a withheld tool:

1. `failed` says the tool broke. It did not; we declined to offer it.
2. `failed` is deliberately excluded from the checklist's closing buckets (VERIFIED,
   `agent/checklist.py:21-27`), so the item ends `unresolved` at finalization with the generic
   reason "the review ended without a finding or a coverage entry for it", and the engineer
   reading the report never learns we withheld the tool.
3. The error message hands the model a 32-name list inside a tool result.

**The design: a withheld tool is registered, not absent.** `WithheldTool` (full shape in
[data-model.md](data-model.md) section 11) is **not** in `__iter__` (no schema on the wire, which
is the entire point) but `ToolDispatch.by_name` resolves it, and its `call` returns an error
result **and** writes an `unresolved` coverage item through `ToolContext.record_coverage`
(`tools/context.py:165-171`) with `check=<checklist_item or "tool."+name>`, so it lands in the
bucket `Checklist.bucket_of` searches and closes the item **as unresolved with a sentence an
engineer can read**. That is the difference between "not covered" and "not covered because".
`ToolDispatch.tools` then holds two kinds of entry, `__iter__` filters and `by_name` does not: a
small explicit split in one dataclass, not a new layer.

### R11.5 The alternative worth naming so the choice is deliberate

VERIFIED: OpenAI has `tool_choice: {"type": "allowed_tools", ...}`
(`openai/types/responses/tool_choice_allowed.py`) and Gemini has
`FunctionCallingConfig(mode=ANY, allowed_function_names=[...])`
(`google/genai/types.py:6224-6237, 6258-6273`). Both narrow what the model may call **without
removing the schemas from the request**: perfect for the prompt cache, **zero tokens saved**. That
is the right mechanism for a future "focus the model" lever and the wrong one for lever 4, whose
whole purpose is bytes.

### R11.6 Touch points, tests, metric, adoption

**Touch points**: `tools/registry.py` (`functions_for`, `ToolDispatch`, the new `WithheldTool`),
`tools/context.py` (coverage write, reusing the existing path).

**Tests**: tier selection with no provider (exact tool names for a `model_check` fixture and a
full fixture, flag off and on); **the withheld path with FakeProvider**, scripting a
`check_rms_part` call against a package with no feature rows and asserting the tool was absent
from the iterated `ToolSet`, the call still produced a `tool.started`/`tool.finished` pair, the
result names the tier rule, `session.coverage.unresolved` holds an item whose `check` is
`modeling.resilience` with a reason naming the missing feature rows, and
`session.coverage.failed` is **empty** (this last assertion is the one that fails today); the
checklist consequence (`bucket_of` is `unresolved`, not `open`, so finalization does not add a
second vaguer item); and a regression guard that a hallucinated name still goes to `failed`.

**A/B metric**: tool count and bytes per package class (full, `model_check`, part-only). The
honest headline is an asymmetry that must be stated rather than averaged away: **23.8 percent off
a `model_check` package, 0 percent off a full assembly package.** Lever 4 does nothing for the
main case and a lot for the Model check tab's case. Quality metric: the unresolved count read as
**two numbers**, unresolved-because-withheld and unresolved-for-any-other-reason. A lever that
raises the first and leaves the second flat is behaving as designed.

**Adoption rule**: the general gate, plus unresolved-for-any-other-reason must not rise, plus the
OpenAI cache diagnostics must show no mid-session `tools_changed` (which the package-decidable
scope guarantees by construction and the test asserts).

---

## R12. Lever 5: pre-run deterministic checks

**Flag**: `EfficiencySettings.prerun_checks`.

### R12.1 The scope is smaller than the baseline states, and saying so is the point

Which checks can be enumerated without a model (all VERIFIED by reading):

| Check | Enumerable? | Why |
|---|---|---|
| RMS part rules | **Yes, already** | `run_part_checks(context, None)` grades every part document (`tools/rms_checks.py:103`) |
| RMS assembly rules | **Yes, already** | `run_assembly_checks(context)` takes no selection (`:157`) |
| RMS equations | **Yes, already** | same shape (`:186`) |
| Interference | **Yes** | `groups_of(package)` enumerates every group (`tools/checks_interference.py:32`); already drives `swreview check interference` (`cli.py:756-786`) |
| Fastener joint | **No enumerator exists** | needs `(fastener_id, hole_id, clamped_component_ids)`; the clamped stack is model-chosen |
| Hole alignment | **No enumerator exists** | needs a pair of holes and a drawing tolerance `SourceRef` for a verdict |
| Fit | **No, and probably never** | needs two drawing dimensions identified as bore and shaft |
| Axial stack | **No, and probably never** | needs an ordered list of dimensions with signs and a target gap |

So the lever as written is four checks that already enumerate themselves, two that would need new
deterministic enumerators, and two that are irreducibly model-driven.

**v1 ships the four.** The fastener-joint enumerator is a later, separately specified increment:
it is roughly 150 lines plus tests reusing `_is_coaxial`, it is a feature-sized piece of
engineering judgement encoded in code, a wrong pairing produces a *deterministic* wrong finding
that looks authoritative, and it deserves its own golden fixtures (OQ-4).

**Hole alignment should not be pre-run even if pairs are enumerable**, because
`check_hole_alignment` without a tolerance `SourceRef` returns `unresolved` by design, so
pre-running every pair manufactures a large number of verdictless unresolved findings and
degrades the report. Enumerate the candidate pairs into the digest instead.

### R12.2 Where it goes

There is already a function in exactly the right place doing exactly this shape of thing:
`record_partial_evidence(session, package)` (VERIFIED, `runner.py:157-183`) runs in
`start_review` before any turn and writes a `skipped` coverage item saying what the dump profile
never extracted. Its docstring is the argument for lever 5 in miniature.

The pre-run is its sibling, called from the same place (`runner.py:684`), and **the digest is
prepended to `OPENING_MESSAGE` (`runner.py:88-93`), not to the system prompt**, because the
system prompt is the cacheable prefix and the digest is per package (R10.6 item 3).

### R12.3 The correctness point that makes this honest

The pre-run calls the **same tool functions through the same `ToolDispatch`**, not a parallel copy
of the check logic. Every pre-run check therefore produces a real `InvestigationStep`, real
findings through `ToolContext.record_finding`, real coverage, and real
`tool.started`/`tool.finished` events. The pane shows the pre-run happening; the report is
structurally indistinguishable from a model-driven run; `Finding.tool_result_ids` still points at
a real step. A pre-run that bypassed the dispatch would have to synthesize all of that and the
report would start lying about provenance.

### R12.4 The digest, and the block that carries the risk

The digest is counts per check with the non-passing ones named, plus a **"NOT evaluated, and why"**
block. That block carries the risk the baseline names (the model treats the digest as complete
and stops exploring), and it must be **generated from the same coverage machinery, not written as
prose**: each not-evaluated line corresponds to a `skipped` coverage item written at the same
moment, so the report says the same thing the model was told. One source, two renderings.

```
Deterministic checks were run before this turn. Their findings are already in the session.

  modeling.resilience  34 rules over 7 part documents: 5 fail, 2 unresolved, 27 pass
      fail: rms.core.order (prt:3, prt:5), rms.detail.naming (prt:1)
  interference         3 conditions: 1 demonstrated, 1 excepted, 1 unresolved

NOT evaluated, and why:
  fastener joints   12 screws found; no joint evaluated. The clamped stack for each joint is
                    not derivable from the package, so you must name it.
  hole alignment    8 coaxial hole pairs found; none has a drawing tolerance in the package.
  fit, axial stack  not run: both need drawing dimensions you have to identify.
```

### R12.5 Expected effect

For a package with 3 interference groups, a minimal model-driven pass is 3 RMS calls plus 1
`list_interferences` plus 3 group checks, and with `parallel_tool_calls: False` that is **7 round
trips saved**, on the order of 60,000 to 100,000 input tokens at 8,500 tokens of schema plus a
growing history per trip. **UNVERIFIED**: the actual round-trip count today, which is exactly why
the measurement layer must land first.

### R12.6 Touch points, tests, metric, adoption

**Touch points**: `agent/runner.py` (a sibling of `record_partial_evidence`, called from
`start_review`; `OPENING_MESSAGE` assembly), `tools/rms_checks.py` and
`tools/checks_interference.py` (read, not changed), the coverage path.

**Tests**: (1) **the pre-run produces the same session a model-driven run does**, comparing on the
`_verdict_key` the runner already defines (`runner.py:324-345`) rather than on serialized lists,
which is the strongest possible statement that the pre-run is the same checks and not a second
implementation; (2) the digest names what was not evaluated and the counts in the digest equal the
counts in the session, with a `skipped` coverage item for each; (3) a pre-run check that fails
does not stop the review (`--fail-tool` already exists, `registry.py:491-525`); (4) an empty
`model_check` package runs nothing, the digest says so, and `record_partial_evidence`'s existing
`skipped` item is not duplicated.

**A/B metric**: round trips, input tokens, **wall clock to first finding** (which should drop
dramatically and is the number an engineer feels), and the full scorecard.

**Adoption rule**: the general gate, **plus a specific regression to watch**: the count of
`check_fit` and `check_axial_stack` calls per run, off and on. Those two are never pre-run, so if
they fall, the digest is suppressing exploration and the lever fails the gate regardless of what
the token number says (RK-6).

---

## R13. Lever 6: parallel tool calls, meaning round-trip batching only

**Flag**: `EfficiencySettings.parallel_tool_calls`.

### R13.1 The two adapters do not behave the same today

VERIFIED: OpenAI sends `"parallel_tool_calls": False` on every request
(`openai_provider.py:308`). Gemini sends no such setting: `_config` (`gemini_provider.py:444-466`)
sets `system_instruction`, `tools`, `automatic_function_calling`, `thinking_config` and
`max_output_tokens` and nothing else, and its loop is already written for multiple calls
(`round_.calls` is a list, `requests` is a slice against the budget, results append as one `tool`
content, `:334-357`).

**Gemini already makes parallel tool calls in production.** "One round trip per query" is true of
OpenAI only, and the input document is wrong about Gemini.

### R13.2 The OpenAI change is one line

VERIFIED by reading: the loop at `openai_provider.py:240-290` already handles multiple
`function_call` items in one response. `_tool_requests` (`:529`) collects **every** `function_call`
item, the caller iterates them, appends a `function_call_output` for each (`:283`), and only then
loops back. The budget check is per call and over-budget calls get the `BUDGET_EXHAUSTED` output
so the echoed history stays valid (`:279-285`). **UNVERIFIED** that a real response comes back
with several calls at a useful rate.

### R13.3 Local execution stays serial, and this is a correctness decision

The baseline conflates two things: **requesting** several calls in one round trip (the token and
latency win, needs no threads) and **running** those calls on several threads (saves wall clock
only if the calls are slow). Our calls are scans over in-memory pydantic lists and geometry over
already-loaded faces; the one exception is `check_tool_envelope`, which loads meshes with
`trimesh` (`tools/measure.py:218-313`).

A thread pool over five list comprehensions saves nothing and costs three real correctness
hazards, all VERIFIED by reading:

1. **`ToolContext.current_step_id` breaks.** It returns `len(session.steps)` (`context.py:127-140`);
   its own docstring explains that a tool writing a finding is citing the step it is about to be
   recorded as. Under concurrency two tools read the same value and one cites the other's step.
   `Finding.tool_result_ids` is "the only evidence a check has when its verdict rests on what the
   model was shown". **Silent provenance corruption, not a crash.**
2. **`SequentialIdAllocator.__next__` is not atomic** (`ids.py:14-17`), so two findings can take
   the same `F-003`.
3. **The step log stops being deterministic**, and `tests/golden/` compares sessions.

All three are fixable and none is worth fixing for a thread pool over list scans. **Lever 6 is
"allow the model to request several calls per round trip" and nothing more** (RK-9). With
execution serial in request order, "keep bridge calls serial on the STA thread" is satisfied by
construction, and the step log stays deterministic for free.

### R13.4 Gemini is not A/B-able for this lever

The flag is a no-op in the "on" direction and a **new capability** in the "off" direction: there is
no "disable parallel" switch in `GenerateContentConfig` (VERIFIED by absence), and dropping all
but the first call of a round would throw away work the model already did and measure something we
would never ship. **Lever 6 is measured on OpenAI only**, and the results row says "Gemini: on by
default, not measurable as A/B". That is a true statement and more useful than a fabricated
comparison.

### R13.5 Touch points, tests, metric, adoption

**Touch points**: `openai_provider.py` constructor (where `max_output_tokens` already comes from),
set by `cli.provider_factory`. **Not** a new argument on `AgentProvider.run`: that signature is the
port contract and changing it touches three adapters and every test that implements it.

**Tests**: the request carries the flag (recorded client, off and on); several calls in one
response are all executed in order (three `tool.started`/`tool.finished` pairs, three
`function_call_output` items, three steps with indices 0, 1, 2); the budget still bounds the turn
(three calls with `max_steps=2`: two run, the third gets `BUDGET_EXHAUSTED`, the turn ends
`max_steps`, the runner writes closeout coverage); **FakeProvider grows a multi-call round**
(`ScriptedTurn.tool_calls` is already a tuple but the fake appends one assistant message per call,
`fake.py:112-128`, which models the serial shape; add an optional grouping so a script can say
"these three were one round"); determinism (two runs of the same script produce byte-identical
`events.jsonl` apart from timestamps).

**A/B metric**: round trips primary; wall clock to session end and input tokens secondary (which
fall roughly as round trips fall).

**Adoption rule**: the general gate, **plus watch for speculative batching**: a model asked to
batch may call checks it would otherwise have skipped after reading an earlier result. That shows
as **step count going up while round trips go down**, and it can raise false alarms. Both numbers
must be in the results row.

---

## R14. Lever 7: coverage-driven stop

**Flag**: `EfficiencySettings.coverage_stop`.

### R14.1 The state already exists

VERIFIED, computed in one place for finalization: open checklist items via
`context.checklist.open_items(review)` (`checklist.py:68-70`, called at `runner.py:246`) and open
evidence requests via `request.status != "open"` (`runner.py:231-245`). The predicate lives beside
`finalize_session` (`runner.py:200`) and is **used by** `finalize_session`, not copied;
finalization's whole job is to enumerate the same two sets.

### R14.2 The hard part: a turn cannot be ended from outside

VERIFIED: `_run_turn` (`runner.py:528-576`) calls `provider.run(...)` once and that call does not
return until the model stops or the budget runs out. The only mid-turn seam is the `ToolSet`,
which is exactly what `StoppableTools` uses. Three mechanisms, not equivalent:

- **A. Raise out of `ToolSet.call`, the way Stop does.** `StoppableTools` raises `TurnStopped`, a
  `BaseException` chosen so the runner's `except Exception` does not turn it into an error
  (VERIFIED, `chat/server.py:344-352`). **The trap**: the triggering call gets no output, so on
  OpenAI the history holds a `function_call` with no matching `function_call_output`, and the
  module docstring says plainly that "every `function_call` in the echoed history needs a matching
  `function_call_output` or the next request is rejected" (VERIFIED,
  `openai_provider.py:96-99`). The session could then never be continued or have an evidence
  request answered, which is precisely what `continue_session` and `answer_evidence`
  (`runner.py:462-495`) exist to do. Stop gets away with it because Stop means the engineer
  abandoned the turn; coverage completion does not mean that. **This is the mechanism an
  implementer would reach for by analogy, and it would quietly break `answer_evidence` on
  OpenAI** (RK-8).
- **B. Soft stop**: answer the call, then append "coverage is complete; write your closing summary
  now" to the result. History stays valid; the model may ignore it. A hint, not a stop.
- **C. Withdraw the tools for the next round**: `tool_choice: "none"` on OpenAI (VERIFIED,
  `openai/types/responses/tool_choice_options.py`) or `FunctionCallingConfig(mode=NONE)` on Gemini
  (VERIFIED, `google/genai/types.py:482-483`, "Model will not predict any function calls"). The
  model physically cannot call another tool, writes its closing message, and the turn ends `end`
  through the existing path. Every call has its output; the history is valid and resumable.

**C, with B's sentence as the accompanying tool-result text.** C is the only one of the three that
both actually stops the exploration and leaves a session that can be continued. It costs one
adapter change each: Gemini builds `config` once before the loop (`gemini_provider.py:310`), so
this is the one place lever 7 forces a per-round rebuild, and that rebuild is the same seam lever
4's per-round variant would have needed. Build the seam once if both are ever wanted.

### R14.3 The honesty requirement, and why two guards ship with the lever

This lever converts `mark_coverage` from bookkeeping into a **turn-ending** call, which changes
the incentive: a model that wants to finish can close the checklist with nine
`mark_coverage(bucket="skipped")` calls and stop. Today that produces a bad report; with lever 7
it also produces a short, cheap run that **looks efficient in the results table** (RK-7).

1. **The stop predicate ignores `skipped` and `out_of_scope` as closers.** VERIFIED that
   `bucket_of` searches `("checked", "skipped", "unresolved", "out_of_scope")`
   (`checklist.py:21-27`). For *finalization* that is right: an item closed any way is closed. For
   *stopping early* it is not: a review that skipped six of nine items has not finished, it has
   given up. The predicate requires every item closed by a finding or by `checked`. **This makes
   the two functions deliberately different and needs a comment saying why, or someone will "DRY"
   them together later and reintroduce the hole.** It also makes the lever fire less often and
   save less, which is the correct trade (OQ-5).
2. **The scorecard must show the closing bucket mix.** A run whose `skipped` count jumped is the
   failure mode, and `PackageScore` (`benchmark/scorecard.py:65-78`) carries `unresolved_count`
   but no per-bucket breakdown. **Lever 7 cannot be gated without it**, so the breakdown is part of
   this lever's work.

### R14.4 Touch points, tests, metric, adoption

**Touch points**: `agent/runner.py` (the predicate beside `finalize_session`, used by it), a
`ToolSet` wrapper modelled on `StoppableTools`, `openai_provider.py` and `gemini_provider.py`
(per-round `tool_choice` / `ToolConfig`), `benchmark/scorecard.py` (bucket mix).

**Tests**: the predicate unit-tested directly over hand-built sessions with no provider (all items
closed by findings; one item open; one evidence request open; an item closed only by `skipped`)
since that is where the edge cases live and where they are cheapest; the stop fires (the final
scripted call did not run, the turn ended `end`, no step for it); **resumption survives it** (after
the stop, `answer_evidence` or `continue_session` runs; this needs the recorded-client OpenAI test
because it is the assertion that distinguishes C from A and the fake cannot see the difference);
an open evidence request keeps the turn alive; flag off produces byte-identical `events.jsonl`.

**A/B metric**: tokens and steps per run, the coverage bucket mix, and **how often the stop fired**.
A lever that fires on one package in five is not the same lever as one that fires on five in five,
and the token average hides that.

**Adoption rule**: the general gate, plus the `skipped` and `out_of_scope` counts must not rise,
plus the fire rate is recorded alongside the saving.

---

## R15. Lever 8: model tiers per job, deferred out of feature 005

**This is a scope recommendation, not a measurement result.**

Of four candidate jobs, only one is routable today.

- **The review turn** is one call with no internal orchestration/judgement split.
- **The Ask tab is not ours to route.** It is the SwpilotCLI terminal running Codex or Gemini CLI
  (`settings.terminal_cli`) against our stdio MCP server, and the engineer's CLI chooses the model.
  What we can do for the Ask tab is make its tool payload smaller, which is levers 2 and 4, and the
  spec says so rather than listing the Ask tab as a lever-8 deliverable it cannot be.
- **Tool-result summarisation does not exist.** VERIFIED: `summarize_result`
  (`agent/providers/__init__.py:270-283`) is a 200-character truncation with no model involved, so
  building it is a new feature with its own risk (a summary that drops the number a check needed is
  a quality regression no scorecard would attribute to the summariser).
- That leaves **`answer_evidence`** (`runner.py:470-495`), whose job is mechanical, and which is
  the **minority of turns**.

The cost of doing it anyway: `settings.py` needs a second `FAST_MODELS` table (a model id must
never be a literal anywhere else; the module docstring's first point exists because feature 001
wrote a retired vendor's id into `session.json`); `runner.py` needs an injected `fast_provider`;
`report/session.py`'s `ProviderInfo` is singular and `ReviewSession.model` is "the single field
every consumer can rely on", so two models per session breaks an invariant; `chat/server.py` and
`benchmark/runner.py` both grow a parameter; and the measurement needs **cost, not tokens**,
because tokens per tier are not comparable, which means the scorecard grows a price table. **Five
modules and two contracts for a saving on the minority of turns.**

If the owner wants it later, the narrow version is `answer_evidence` on the fast tier, and the
test that matters is that `_reconcile_reruns` (`runner.py:348-379`) still folds the re-run verdict
onto the original finding: a fast model that records a *new* finding instead of replacing the old
one produces two contradictory verdicts in the report.

---

## R16. Lever 9: package reuse

**Flag**: `EfficiencySettings.package_reuse` plus an extractor-side `--reuse`.

### R16.1 Half the baseline's premise is false today

The manifest has seven fields (VERIFIED, `ir/models.py:187-194`, `Dump/ManifestBuilder.cs:28-65`):
`document_id` (SHA-1 of the lowercased normalized **path**, not the content), `vault_path`,
`vault_version` (**null unless the vault writes that property back**, plus a `not_extracted` gap;
the EPDM API is not read by this build), `revision` (**null unless set**), `configuration`,
`local_modified` (**hardcoded null** plus an `unsupported` gap on every document, every dump,
`ManifestBuilder.cs:57,92-98`), `export_method`.

**There is no modification time, no file size and no content hash anywhere in the manifest, in
`Document` or in `EvidencePackage`.** So a key built from "path, version and modification time from
the manifest" reduces today to **path and configuration**, which says "the same files, in the same
configurations" and says nothing about whether they changed. Reusing on it makes the stale-package
failure **certain** rather than possible (RK-10).

### R16.2 The key that is honest

It requires new `ManifestEntry` fields `file_modified_utc` and `file_size_bytes`, a schema bump to
1.3.0 and a `test_schema_sync` regeneration. The exact key composition, the field types and the
full invalidation table are in [data-model.md](data-model.md) section 9. Each part of the key
earns its place:

- **extractor name and version, schema version**: a package written by an older build may be
  missing a phase a newer reviewer expects.
- **profile and the four dump options**: a `model_check` package has empty `holes[]`,
  `fasteners[]`, `faces[]` and `bodies[]` **by design** (VERIFIED, `Dump/PackageWriter.cs:200-235`),
  and handing one to a Review that asked for `full` silently narrows the review (RK-11).
- **every manifest entry, not just the root**: VERIFIED that `PackageWriter.DocumentPaths`
  (`:381-401`) collects every document the traversal referenced, which closes the input document's
  named risk (a referenced part edited outside the assembly).

The alternative, hashing document bytes, reads tens or hundreds of megabytes per dump on the
application thread and is probably slower than the dump phases it would skip (**UNVERIFIED**).

### R16.3 What the key still cannot catch, each needing an explicit refusal

- **Unsaved in-memory edits**: mtime does not move until save. `GetSaveFlag` is already consulted
  by `suppress-test`, so **refuse reuse when the active document reports unsaved changes** and say
  so in the status line.
- **A suppressed or lightweight component later resolved**: VERIFIED that `MeshExporter` skips
  non-resolved components with a gap (`Dump/MeshExporter.cs:57-69`), so resolving one changes what
  a review can see with no file change. **Put each component's suppression state in the key.**
- **A partial dump**: VERIFIED that `PackageWriter.Build` continues past a failed phase and writes
  the package either way with gaps (`:38-41,142-235`), and nothing says "this dump aborted". **Add
  `extractor.completed`, or refuse reuse of any package carrying a phase-level `tool_error` gap.**
- **Clock skew or a restored-from-backup file**: mtime can move backwards. The key is equality, not
  ordering, so this produces a false miss (re-extract), which is the safe direction.

### R16.4 The lookup

**There is no index of run folders today.** VERIFIED: `RunFolders.Create` always makes a fresh
timestamped folder (`Review/RunFolders.cs:296-317`); "the pane's latest run" is an in-memory field
cleared on detach (`Review/ReviewHost.cs:258,271,288,380`); and `RunFolders.ProfileOf` reads only
the first 8 KiB of one `package.json` (`:52,125-186`) **precisely because** a full package is tens
of megabytes and the read happens on the SOLIDWORKS application thread. So a scan that parses every
`package.json` is the thing those classes were written to avoid.

Use **`run_root/package-index.json`**, appended on every successful dump, one line per run folder
(`reuse_key`, folder, written-at, profile, byte size). A missing or unparseable index means "no
reuse", never an error; the lookup verifies the folder and its `package.json` still exist before
reusing. Fall back to a bounded head scan (the `ProfileOf` technique, capped at the N most recent
folders, with `reuse_key` near the top of the file) when the index is absent.

### R16.5 The reused package still needs its own run folder

VERIFIED: `chat/server.py` claims a run folder per chat and refuses a second (`RunDirInUse`,
`:233-238,1341-1381`), and `session.json`, `events.jsonl` and `report.md` are written into it. So
reuse means create the new folder as today, then **copy `package.json` and `meshes/` instead of
dumping**. Measure the copy against the dump time it replaced (probe P4); if the copy dominates,
fall back to a `package-source.json` pointer read by `load_package`, which is a change to one
function (`LoadedPackage.base_dir` is one directory and `mesh_file` resolves against it,
`ir/loader.py:23-32`).

### R16.6 Three guards, all required if this lever is adopted

1. **Reuse is stated, never silent.** `reused_from` and `reused_at` on the package; "Reusing the
   extraction from `<folder>` (<age>)" in the pane status line instead of "Extracting evidence from
   ..."; the fact in the report header and in `session.json`.
2. **Reuse never crosses a refusal.** Unsaved changes, a non-resolved component, an aborted dump, a
   different profile or dump option all mean extract again, because extraction is minutes and a
   wrong finding is hours.
3. **The key is recomputed at reuse time** from the live document's references now, never trusted
   from the file.

### R16.7 Touch points, tests, metric, adoption

**Touch points**: `Dump/ManifestBuilder.cs`, `Dump/PackageWriter.cs`, `ir/models.py`,
`contracts/ir.schema.json` (1.3.0), `Review/RunFolders.cs`, `Review/ReviewHost.cs`,
`ir/loader.py`, `swreview-extract dump --reuse`.

**Tests**: one unit test per row of the invalidation table asserting the key changes; an
unsaved-changes document refuses reuse; a `model_check` package never matches a `full` request; a
fake phase that throws produces a package that refuses reuse; a golden test that a reused package
produces a `session.json` whose `reused_from` is set.

**A/B metric and gate**: this lever is **invisible to `swreview benchmark run`** (VERIFIED:
`run_benchmark` iterates pre-built package directories, `benchmark/runner.py:88-104`; no dump
happens), so it needs a workstation harness: dump twice against an unchanged document, once cold
and once with `--reuse`, comparing dump wall clock. **Its quality gate is stronger and cheaper than
the scorecard**: the reused package must be **byte-identical to a fresh dump modulo `package_id`,
`created_at`, `reuse_key` and the new reuse fields** (probe P3 defines the exact modulo set). If
the reused package is not the package a fresh dump would write, the lever is wrong regardless of
what the model then says.

**Adoption rule**: the byte-identity gate is a pass/fail precondition, not a trade. Then a dump
wall-clock reduction worth the code.

---

## R17. Lever 10a: lazy meshes

**Flag**: `EfficiencySettings.lazy_meshes`, with extraction settings `extraction.meshes` (`eager`
default, `lazy`, `off`) and `extraction.lazy_fetch_body_limit`.

### R17.1 Meshes are separable

VERIFIED by `grep -rn "mesh_file\|load_mesh" reviewer/src/swreview`: exactly one reader opens a
mesh in the whole reviewer, `check_tool_envelope` via `_mesh_for` (`tools/measure.py:218-228,
283-303`). `MeshExporter` is a leaf phase and `--meshes none` already exists.

### R17.2 Faces are not separable

VERIFIED: with the default `--faces needed`, `FaceDumper` describes only faces **another dumper
already asked for** (`Dump/FaceDumper.cs:46-71`), and those requests are minted with live `IFace2`
handles inside the hole, fastener and mate phases (`HoleDumper.cs:364`, `FastenerDumper.cs:250`,
`MateDumper.cs:227,252`). So "faces off, holes on" produces a package whose `Hole.face_ids` name
faces that do not exist, and the extractor already treats the four geometry phases as one group.

### R17.3 A second, independent reason lazy faces is parked

VERIFIED: `ExceptionStore.refresh` (`exceptions.py:440-473`) recomputes each active exception's
fingerprint, and the `geometry` fingerprint hashes each component's transform **and the sorted
parameters of its faces** (`exceptions.py:184-187,287-295`). A package extracted without faces has
empty `faces[]` for every component, so **every accepted geometry exception would flip to
`needs_review` on the first lazy run and stay there**. Nothing is silenced wrongly (the store never
clears an exception), but the exception mechanism becomes noise and engineers learn to ignore it
(RK-13). Meshes are in neither fingerprint. **Lever 10 is meshes-only in v1 and 10b is parked as a
redesign, not a flag.**

### R17.4 The bridge fetch needs a fifth command

VERIFIED: the protocol vocabulary is exactly four (`ping`, `capture`, `measure`, `interference`,
`Serve/PROTOCOL.md`, mirrored by `bridge/client.py:348-409` and `tools/bridge.py`). Add
`tessellate` taking a `component_id` and returning `BodyRef` rows plus written paths. Design notes
with their reasons:

- **Reuse `MeshExporter.ExportBody`** (`Dump/MeshExporter.cs:119-180`); do not write a second
  tessellator, because a different chord tolerance in the two paths would make an envelope answer
  depend on how the mesh arrived.
- **The host chooses the path**, exactly as `capture` does, because a filesystem path in a request
  is a write the agent controls, and the client applies `_relative_inside_package`
  (`tools/bridge.py:77-90`) before touching anything.
- **The read-only guard passes it today and no guard change is needed or should be made.**
  VERIFIED: `ReadOnlyGuard` is a denylist (`Guard/ReadOnlyGuard.cs:23-80`) and `GetTessellation`,
  `Tessellate`, `CurveChordTolerance` and `GetBodies2` are not on it and are not covered by the
  `FeatureCut*`, `FeatureExtrusion*`, `InsertFeature*` or `SetSystemValue*` prefixes.
- **Review scope only.** A mesh fetch writes a file and can take seconds, so it does not go to
  general chat; the refusal stays the indistinguishable `unauthorized` the protocol already
  specifies.
- **One STA worker answers in arrival order**, so a tessellation blocks every other bridge call
  behind it (probe P2, RK-14).
- **Bump `PROTOCOL.md` to 1.1** and have `ping` report it.

**Off the workstation there is no bridge**, so a lazily extracted package reviewed later on a
machine with no SOLIDWORKS has no way to answer a tool-access question. That is acceptable only if
the answer is `unresolved` and says why. **Today it is silence**, which is R17.5.

### R17.5 Prerequisite defect, fixed first, as its own commit with its own test

VERIFIED by reading `check_tool_envelope` (`tools/measure.py:283-320`): with `bodies == []` both
`meshes` and `unresolved` stay empty, `envelope_raycast` with `meshes=[]` returns
`EnvelopeResult(hits=[], unresolved=[])` (`geometry/envelope.py:180-198`), and the result is
`status: "checked", bodies_swept: 0, hits: []`. **A model reading that sees a tool-access check
that ran and found nothing in the way.**

It is **reachable today** with `swreview-extract dump --meshes none --profile full`, and lever 10
would make it the normal case. It is a Principle I violation against the module's own docstring ("a
tool envelope that could not sweep a body has not established that the body is out of the way",
`tools/measure.py:14-16`). Fix: refuse `checked` when `bodies_swept == 0`; return `unresolved` with
the reason. One guard, one test, stands on its own merits (RK-12, Phase 1b).

### R17.6 `eager` is the default, and that is the constitution's position

A lazily extracted package reviewed off the workstation is a package with **less evidence**, and
the flag that reduces evidence is the one that is opted into. `lazy_fetch_body_limit` bounds how
much one review may pull back so a runaway does not stall the application thread; reaching the
limit is unresolved coverage, not a stop.

### R17.7 Tests, metric, gate

**Tests**: the zero-bodies guard; a body that cannot be fetched is named in `unresolved` (the path
`tools/measure.py:285-293` already takes for a missing mesh file); a bridge that refuses; the fetch
limit produces unresolved coverage.

**A/B metric and gate**: dump with `--meshes glb` and `--meshes none`, review each with the bridge
open; dump wall clock, bridge `elapsed_ms` per `tessellate`, total review wall clock. Gate: the
scorecard **plus** an assertion that `check_tool_envelope` returns the same hits and the same
`bodies_swept` in both arms, or `unresolved` naming what it could not fetch.

---

## R18. Lever 11a: incremental re-review, RMS only

**Flag**: `EfficiencySettings.carry_over_rms`.

### R18.1 The fingerprints already exist and no second hashing scheme is written

VERIFIED: `exceptions.fingerprint(package, component_ids, kind)` (`exceptions.py:249-295`) already
does both kinds.

- **`geometry`**, per component: the 4x4 transform plus the sorted parameters of its faces.
  Bounding box and area are deliberately excluded because they move under a rebuild that changed
  nothing (`:163-181`); rounded to 1e-9 m; order-independent.
- **`feature_tree`**, per document: every feature row in index order over index, type name, name,
  depth, folder id, suppressed, described-state, sketch presence and raw status and consumer count,
  fillet presence and default radius, child ids, plus every equation's left-hand side and global
  flag (`:190-246`).

`fingerprint_kind_for(check)` picks by the `rms.` prefix (`:89-91`), and a component id the package
does not hold raises `LookupError` rather than silently re-binding. **That is the DRY line to hold
in code review.**

### R18.2 A carry-over is a much stronger claim than an exception refresh

An exception says "this accepted condition still looks the same"; a carry-over says "re-running
this check would produce the same verdict", which needs **everything the check reads**. What the
fingerprints do not cover (all VERIFIED):

| Family | Reads, outside the fingerprint |
|---|---|
| `fastener.*` | `Hole.thread_depth`, `hole_depth`, `end_condition`, `Fastener.length`, `thread_designation`, the `Thickness` custom property (`checks_fastener.py:99-116`), and the answers to open evidence requests |
| `fit.*` and drawing checks | `DrawingSheet.dimensions`, `parse_status`, `general_notes` |
| `interference.*` | `package.interferences` and `InterferenceSettings` |
| **every** family | `EvidencePackage.gaps`, `extractor.profile`, the checklist version, `Calculation.function_version`, `exceptions.json` |

**So v1 carries over only the families whose entire input is already inside one fingerprint**,
which on today's tree is `rms.*` and nothing else, **excluding
`rms.detail.individually_suppressible`** because it reads `rms_suppress_test`
(`ir/models.py:508-560`) and that array is not in the feature-tree fingerprint.

This is a narrow v1 and it is the right one: it is the only scope where "the fingerprint covers
every input the check reads" is a statement defensible from the code rather than hoped for. It is
also the family with the most findings per part, so the saving is real. The broad alternative (a
per-check declared input digest) needs every check to declare and hash its inputs, and a check that
forgets one carries a wrong verdict forever (OQ-7).

### R18.3 Carry-over can never be silent

Three readers look at three artifacts; the exact fields are in [data-model.md](data-model.md)
section 10.

1. **The finding** gains optional `carried_over_from`, `carried_over_at` and `carry_over_key`.
   **`Finding.status` is not touched**: a carried `demonstrated` finding is still demonstrated;
   what changed is who demonstrated it and when, which is provenance, not status. Overloading
   `status` would break the scorecard's matching rules (`scorecard.py:106-142`).
2. **Coverage** reuses the `checked` bucket with a reason starting "carried over from ", rather
   than adding a sixth bucket that would touch the schema, the report renderer and the scorecard
   aggregate for the same information.
3. **The report** renders the originating run in the heading line and states how many findings were
   carried versus re-run, so an engineer can see at a glance which part of the report was not
   computed today (Principle VI).

### R18.4 Six guards, because a carried-over finding looks like a verdict and is actually a memory

1. Carry only from a session that **finished** (`ended_at` non-null and no `failed` coverage naming
   the check). A verdict from a run cut short by `max_steps` is not a verdict to reuse.
2. Carry only **`demonstrated` and `checked_within_scope`**; re-run every `suspected` and
   `unresolved`. Those two are where the model's judgement sits, which is exactly what should not
   be frozen, and an `unresolved` finding with an open evidence request is precisely what a new run
   might resolve.
3. **Never carry across a disposition.** A finding the engineer accepted, rejected or deferred has
   a human decision attached; carrying it without the decision is worse than re-running, and
   carrying it with the decision has the reviewer re-assert a human's judgement.
4. **Never carry if `ExceptionStore.refresh` moved any exception touching these components to
   `needs_review`.**
5. **Never carry across a profile, gap-set, checklist-version or check-version change** (covered by
   the key).
6. **Cap the carry** in age or in runs. A finding carried for twenty consecutive runs has not been
   computed for twenty runs.

### R18.5 Tests, metric, gate

**Tests**: the invariant that carried plus re-run equals total, and every carried finding's
`carry_over_key` recomputes to the same value against the current package; **a test that mutates
one feature row and asserts the finding is re-run rather than carried** is the minimum bar; a test
that a disposition blocks carry-over; a scorecard test over a session with carried findings.

**A/B metric and gate**: review a package, edit one part, re-dump, review again, flag off and on;
tokens and tool calls on the second review. Gate: the scorecard on the second review **plus** an
assertion that every finding touching the edited part was re-run and not carried. **And the results
row must record the carried count per arm**, so a reader can see whether the quality came from
computation or from memory. A lever that "improves" recall by remembering is not an improvement
(RK-16).

---

## R19. Lever 12: rules over tokens

**Not a flag. Standing practice.** Every finding class the model keeps producing that a rule can
express becomes a deterministic check, which costs zero tokens per part thereafter. The measurement
is the count of findings by check kind over time, which the instrumented scorecard gives for free.
It belongs in the spec as a practice with a review cadence, not as a phase task.

---

## R20. The evaluation protocol and the adoption rule

### R20.1 Preconditions, in order

1. **The measurement layer has landed**: per-round usage from both adapters, summed onto
   `session.json`, surfaced in `PackageScore` and `render_scorecard_md`.
2. **Round trips are recorded alongside steps** (delivered by `round_index`, R5.5).
3. **`EfficiencySettings` is recorded on the session** (R7.2).
4. **The benchmark set has grown.** This is the precondition most likely to be skipped and it
   invalidates every gate if it is. VERIFIED today: `benchmarks/sets/pilot.json` holds **one**
   package, `cover-blind-tap`, with `held_out: false`, whose answer key has **two** known defects,
   and whose `package.json` has **0 mates, 0 holes, 0 threads, 0 fasteners, 0 faces, 0 bodies, 0
   interferences, 0 captures, 0 features, 0 equations**. Consequences: `recall` is `None` whenever
   `held_out_known_defects` is zero (`scorecard.py:200-204`), so the headline quality metric does
   not compute; one lost defect out of two is a 50 percent swing; and **levers 9, 10 and 11 cannot
   be exercised on it at all**, because there is nothing to reuse that took time to build, no mesh
   to fetch, and no feature tree to fingerprint. Minimum to make the adoption rule mean anything:
   **build `rms-part`** from `benchmarks/native/rms-part/RECIPE.md` (its answer key already holds
   20 known defects across 20 distinct `rms.*` rules and 18 correct conditions) **and hold out at
   least one package**. The constitution asks for 5 to 10 representative designs (RK-17, OQ-8).
5. **For levers 9 and 10 only**: dump phase timing exists and a workstation with the pilot assembly
   is available. **No dump timing exists today**: VERIFIED that there is no `Stopwatch` and no
   elapsed field anywhere in `Dump/PackageWriter.cs`, and `DumpSummary` carries counts only
   (`AddIn/Review/ReviewServices.cs:23-53`). `SuppressTestRow.elapsed_ms` (`ir/models.py:487`) is
   the only elapsed precedent in a package, and `extractor.phases` as a list of
   `{name, elapsed_ms, status}` is the same shape. It is useful on its own for diagnosing a slow
   dump and it makes "which phase actually costs the time" answerable rather than guessed.
6. **The lever's flag exists, defaults off, and is threaded into `benchmark run`.**

**A pre-existing double write that the baseline table must name.** VERIFIED: `run_benchmark` times
each package with `time.perf_counter()` and writes it into `Timing.unattended_runtime_minutes` via
`_record_unattended_runtime`, **overwriting** the number `finalize_session` computed from
`started_at` to `ended_at`. Two writers of one field; the benchmark's wins because it runs last and
it includes package load and adapter construction. Not a bug, but the baseline table must say which
one it is quoting.

### R20.2 The procedure

For one lever, one provider and one model: **six runs, three off and three on, alternated (off, on,
off, on, off, on)** so provider-side drift during the session does not land entirely on one arm.
Then repeat for the second provider.

```powershell
cd reviewer
uv run swreview benchmark run --set ../benchmarks/sets/pilot.json `
  --out <runs>/lever06-<arm>-<rep> --provider openai --model gpt-5.6 --effort high
uv run swreview benchmark score <runs>/lever06-<arm>-<rep> `
  --answer-keys ../benchmarks/answer_keys
```

Fixed across all six runs of a pair: the set file, the answer keys, the model id, the effort,
`max_steps`, the checklist, the packages on disk (byte-identical), and the tree at one commit.
Recorded per run: the commit sha, the flag value, the provider, the model, the effort, the start
time.

Human timing (`benchmark time`) is recorded **once per package per arm**, not per repetition: a
human baseline does not change between repetitions and pretending to re-measure it would put noise
into `net_saved_minutes`.

**Repetitions are three separate runs into three run folders plus a `swreview benchmark compare`
reader over N scorecards**, not a `--repeat 3` flag inside `run_benchmark`. A repeat loop inside
the runner would have to invent a nested folder layout and an aggregation, which is the scorecard's
job, and three folders make a re-run of one flaky package possible.

### R20.3 The adoption rule, made decidable

The input document's rule is "no known defect lost, no new false alarm, and a token or time
reduction worth the code". Across three non-deterministic repetitions that needs four
clarifications, decided **before** the first run (OQ-9):

| Question | Answer | Why |
|---|---|---|
| "No known defect lost" over 3 reps | **Worst case.** Rejected if *any* on-run misses a defect that *any* off-run found. | A defect found two times in three is found unreliably; a lever that makes it two in three when it was three in three has cost quality. Conservative is the right direction for a review tool. |
| "No new false alarm" | **Median, with the worst case recorded.** | Asymmetric on purpose. False alarms are the noisier metric and the cheaper failure (minutes of an engineer's time, tracked as `false_alarm_handling_minutes`); a lost defect is the failure the product exists to prevent. |
| "Worth the code" threshold | **A median total-token reduction of at least 20 percent, or a median wall-clock reduction of at least 20 percent**, against the off arm's median over the whole set. | Below that is inside run-to-run variance at n=3 and does not justify a flag, a settings field, a test suite and a permanent branch in the code. |
| The three off-runs disagree with each other about defects found | **The set is too noisy to gate on; fix that first.** Record the disagreement, raise the repetition count for that package, or fix the checklist. | A gate whose control arm is unstable cannot decide anything. |

**Every lever that fails is kept off and its numbers are recorded.** That is the input document's
own instruction and the reason the ledger has a Decision column rather than a list of winners.

Levers 9, 10 and 11 have **additional pass/fail preconditions** that are stronger and cheaper than
the scorecard, stated at each lever: byte-identity of a reused package (R16.7), identical
`bodies_swept` or a named `unresolved` (R17.7), and re-run of every finding touching an edited part
(R18.5).

---

## R21. The results ledger

The table at the end of `docs/llm-efficiency-options.md` becomes a **rendering of N
`scorecard.json` files**, produced by `swreview benchmark compare`, not a hand-kept artifact.
Typed numbers go stale and cannot be audited. The row shapes and the one-source-per-column rule are
in [data-model.md](data-model.md) section 8. `Decision` is one of **adopt**, **keep off**,
**re-measure**.

---

## R22. Risks

| # | Risk | How it shows | Guard |
|---|---|---|---|
| RK-1 | A `None` token count is coerced to 0 and the ledger silently understates | A cached share that reads as a win or a regression and is neither | `int \| None` everywhere; any-null-makes-the-sum-null; the exact `construct` reproduction as a unit test (R4) |
| RK-2 | The usage of a turn that raised is lost, which is the expensive turn | Five paid rounds recorded as zero | Usage is a per-round event on the stream, not a field on `TurnResult` (R5.4) |
| RK-3 | The two providers' usage fields are compared as if they were the same quantity | A results table that reads as a win that is neither | Record raw provider fields; cross-provider comparison only on `total_tokens`; name the derivation (R3.1) |
| RK-4 | A lever that saves tokens quietly changes which tool the model picks | The scorecard passes and the review's character changed | The tool-name histogram per run (R9.6); the `check_fit` and `check_axial_stack` counts (R12.6) |
| RK-5 | A withheld tool becomes a silent miss | "modeling.resilience: not closed out" with no reason | `WithheldTool` writes `unresolved` coverage naming the tier rule; `failed` stays empty; the test asserts it (R11.4) |
| RK-6 | The pre-run digest suppresses exploration | Fewer model-driven checks, same token win | The "NOT evaluated, and why" block generated from the coverage machinery; the call-count gate (R12.4, R12.6) |
| RK-7 | Coverage-driven stop rewards giving up | Nine `skipped` items, a short cheap run that looks efficient | The strict stop predicate; the coverage bucket mix in the scorecard, shipped with the lever (R14.3) |
| RK-8 | Stop mechanism A breaks `answer_evidence` on OpenAI | A `function_call` with no `function_call_output`; the next request is rejected | Mechanism C; the resumption test on the recorded client (R14.2) |
| RK-9 | Concurrent local execution corrupts step provenance | A finding citing another tool's step; duplicate finding ids; non-deterministic goldens | Lever 6 is round-trip batching only; local execution serial in request order (R13.3) |
| RK-10 | A stale package is reused | A report that looks fresh and is not | The honest key; refusals for unsaved changes, non-resolved components and aborted dumps; recompute at reuse time; `reused_from` stated in three places (R16) |
| RK-11 | A reused `model_check` package is handed to a full Review | Holes, fasteners, faces and bodies silently empty | Profile and the four dump options are in the key (R16.2) |
| RK-12 | `check_tool_envelope` reports `checked` over zero bodies | A silent false clear on tool access, reachable today | The zero-bodies guard, fixed first as its own commit (R17.5) |
| RK-13 | Lazy faces re-open every geometry exception | `exceptions.json` fills with `needs_review` and engineers stop reading it | Lever 10 is meshes-only; 10b parked (R17.3) |
| RK-14 | A bridge tessellation stalls the STA worker | The pane appears hung during a review | Per-session fetch limit; the existing circuit breaker; review scope only (R17.4) |
| RK-15 | A carried-over finding should have changed | A verdict that is a memory | The six carry guards; `rms.*` only in v1; the edited-feature-row test (R18.4, R18.5) |
| RK-16 | Carry-over inflates `valid_findings` and "improves" recall by remembering | A lever that looks like a quality gain | The carried count is recorded per arm in the ledger (R18.5) |
| RK-17 | The benchmark set is too small for any gate to mean anything | Two defects decide a 50 percent swing; `recall` is `None` | Precondition 4 before any gating (R20.1) |
| RK-18 | A Gemini cached run 400s the whole review | A review that dies rather than degrades | One function builds both config shapes from `cache_name: str \| None`, tested both ways; the flag is read once at `start_review` (R10.8) |
| RK-19 | The static baseline in `docs/llm-efficiency-options.md` is transcribed and stays wrong | 29 tools versus 32; 32,435 bytes versus 34,065 | The regenerating script is a committed test; the doc's baseline row is corrected in the same change (R1.2) |

---

## R23. The phased plan

Each phase ends with a **recorded result**. No lever moves to "adopted" without a ledger row. A
lever that fails its gate stays off and its row stays in the ledger.

### Phase 1: the measurement layer and the common seam (no flags, nothing optional)

1. `TokenUsage` in `agent/providers/__init__.py`; the `usage` event type; both adapters read and
   emit per round; the fake emits a deterministic synthetic record.
2. `UsageLedger` on the `EventSink`; `SessionUsage` and `ReviewSession.usage` written in
   `finalize()`; optional `usage` on the `session.ended` body (OQ-10).
3. `EfficiencySettings` and `ReviewSession.efficiency`, threaded through `start_review`,
   `run_benchmark` and `cli._review_fn` as one argument.
4. Contract edits and golden refresh, paid once: `chat-events.schema.json`,
   `review-session.schema.json`, `scorecard.schema.json`.
5. `report.md` `## Tokens` section, rendered only when usage is present.
6. `PackageScore` and `Aggregate` additions; `seconds_to_first_finding` read from `events.jsonl`;
   three new markdown columns; `swreview benchmark compare`.
7. `tests/unit/test_tool_payload.py` as a pinned byte budget; the static baseline regenerated and
   `docs/llm-efficiency-options.md` corrected.
8. **The live probes** (R24), each in `reviewer/tests/live/` with
   `pytestmark = pytest.mark.live`, skipped without a key, 401/429/5xx reported as a skip rather
   than a failure, following the pattern `tests/live/test_openai_live_schemas.py` already sets.
9. **The baseline runs**: `swreview review` on the benchmark set on both providers, three reps,
   producing the first ledger rows (R0.3).

**Exit criterion**: every run in the tree records what it cost, the ledger has a baseline row per
provider and model, and probes L1, L2, G3 and G4 have answers.

### Phase 1b: two standalone correctness fixes, each its own commit with its own test

- The `check_tool_envelope` zero-bodies false clear (RK-12). Reachable today; stands on its own
  merits; also a prerequisite for lever 10.
- Dump phase timing (`extractor.phases`), if levers 9 or 10 are in scope, because those two have no
  metric at all today.

### Phase 1c: the benchmark set, which gates everything after it

Build `rms-part` on the workstation from its RECIPE; add at least one held-out package. Until this
lands, every Tier 2 and Tier 3 gate is decided by two known defects on a package with no geometry.

### Phase 2: Tier 1, each lever behind a flag, each measured, in this order

1. **Lever 3 (OpenAI half)**: `prompt_cache_key = session_id` plus `prompt_cache_diagnostics`
   recorded, plus the prefix-stability regression test. Do this **before** levers 2 and 4, because
   the diagnostics are the instrument that prices them.
2. **Lever 2**: the docstring split and the `## Tool notes` block, measured with lever 3's caching
   effect noted in the row, A/B run at **one commit for both arms** (flag off hands over the
   rejoined description).
3. **Lever 4**: package-decidable tiers plus `WithheldTool`. Its result row states the asymmetry
   (23.8 percent on a `model_check` package, 0 on a full assembly) rather than averaging it away.
4. **Lever 3 (Gemini half)**: written **only if** probe G4 shows implicit caching is not already
   delivering.

### Phase 3: Tier 2, one at a time, each gated by the scorecard

Order chosen so each lever is measured against a baseline the next one has not already consumed
(R8):

1. **Lever 6** (one line on OpenAI, everything downstream already works), measured against the
   lever-5-off baseline.
2. **Lever 5**, which is the largest expected saving and the largest behavioural risk.
3. **Lever 7**, with the strict stop predicate and the coverage bucket mix shipped together, and
   **never in the same arm as lever 5** until each has been gated alone.
4. **Lever 8 is not in this phase.** Deferred (R15). If the schedule has room, the fastener-joint
   enumerator (lever 5's second increment) or lever 12 work is a better use of it.

### Phase 4: Tier 3, on the workstation, with its own harness

`swreview benchmark run` cannot see levers 9 and 10 at all, so this phase needs the workstation
harness and the dump timing from Phase 1b.

1. **Lever 9**, including the `ManifestEntry` schema bump to 1.3.0 and the `package-index.json`
   lookup, gated first on byte-identity of the reused package.
2. **Lever 10a**, including the `tessellate` bridge command at PROTOCOL 1.1, gated on identical
   `bodies_swept` or a named `unresolved`.
3. **Lever 11a**, `rms.*` only, gated on every finding touching an edited part being re-run.
4. **Lever 12** is standing practice with a review cadence, not a phase task.

---

## R24. The UNVERIFIED list and the probes that settle it

Every probe is a key-gated live test or a workstation measurement. **None is a claim until it
runs.**

| # | UNVERIFIED claim | Probe |
|---|---|---|
| L1 | OpenAI sub-count containment (`cached <= input`, `reasoning <= output`, `total == input + output`) | One tiny request; three assertions, a few tokens. This is what keeps "cached share" honest. |
| L2 | Our prefix actually hits the implicit cache | Two identical requests in one process, same `prompt_cache_key`, full tool list, real system prompt; assert the second has `cached_tokens > 0`. **Tells us whether lever 3 on OpenAI has anything left to win.** |
| L3 | A tool-list change is a `tools_changed` miss, and what it costs | Third request with one tool removed and `comparison_response_id` set; assert `cache_miss` / `tools_changed`; record `cache_missed_tokens`. **Prices lever 4 before lever 4 is written.** |
| L3b | `prompt_cache_options` is accepted on `gpt-5.6` | Falls out of L3; a 400 means the diagnostics half of lever 3 is off the table on our seat. |
| L5 | `parallel_tool_calls` toggling does not break the prefix | Needed only when lever 6 is taken up; noted so it is not rediscovered. |
| G1 | `caches.create` accepts our system prompt plus 32 tool declarations, and we are over the unstated minimum | One create with `ttl="600s"`; assert a `name` comes back; record `usage_metadata.total_token_count`; delete. |
| G2 | Setting `cached_content` alongside `system_instruction` or `tools` is rejected, and what the rejection says | Send both deliberately; record status and message. Confirms the two-shape config is mandatory rather than tidy. |
| G3 | Gemini streaming populates `usage_metadata`, and the last chunk carries the totals | One streamed call; collect every chunk's usage; assert at least one is non-null and the last `total_token_count` is at least the first. Settles cumulative versus delta. |
| G4 | Implicit caching on `gemini-3.5-flash` | Two identical streamed calls, no explicit cache; record `cached_content_token_count` on the second. **A non-zero value is the argument for not writing the explicit-cache lifecycle at all.** |
| G5 | The explicit cache is used when referenced | After G1, one streamed call with `cached_content=<name>`; assert `cached_content_token_count > 0` and `prompt_token_count >= cached_content_token_count`. |
| P1 | Does the mesh phase dominate the dump? | Time each dump phase on the pilot assembly, cold, with `--meshes glb --faces needed`. **Lever 10's entire premise.** |
| P2 | Is a lazy fetch usable interactively? | Time one `tessellate` of the largest part over the bridge and measure how long it blocks the STA worker. |
| P3 | What is legitimately non-deterministic in a package? | Dump the same unchanged document twice and diff field by field. **Defines "byte-identical modulo X" for lever 9's gate.** |
| P4 | Is reuse-by-copy cheap enough? | Time the copy of `package.json` plus `meshes/` for the pilot assembly. Decides copy versus a `package-source.json` pointer. |
| P5 | Does `file_modified_utc` behave? | Confirm it moves on an ordinary save and does not move on open-and-close without save. **Lever 9's key.** |
| P6 | Do both adapters actually receive a usage object on a streamed turn? | Run `swreview review` on `cover-blind-tap` on both providers and record the fields. This is also the baseline row that does not exist. |
| P7 | Does the 20-defect answer key behave on a real RMS package? | Build `rms-part` from its RECIPE, dump it, score a review of it. |
| P8 | Does the feature-tree fingerprint move exactly when it should? | Edit one feature of `RMS-A.SLDPRT`, re-dump, diff the per-document fingerprints. **Lever 11's premise.** |
| T1 | Token counts behind the byte counts in R1 and R9.1 | Falls out of the first instrumented run (P6); every byte-to-token conversion in this document is an estimate until then. |
| T2 | Whether a description trim changes which tool the model picks | The tool-name histogram over the lever 2 A/B (R9.6). |
| T3 | Whether an OpenAI response really returns several `function_call` items at a useful rate | Falls out of the lever 6 A/B (R13.2). |

---

## R25. Open questions that change the design

Only questions whose answer changes what gets built are listed. Each needs an answer before the
phase that depends on it starts. Recommendations are mapped to the stated preferences (DRY,
well-tested, engineered enough, explicit over clever, edge cases over speed).

| # | Question | Blocks | Recommendation |
|---|---|---|---|
| OQ-1 | One `EfficiencySettings` object for all ten flags, or one plumbed argument per lever? | Phase 1 contract edit | **One object.** DRY, one contract edit instead of ten, and it makes the session record trivial. The cost is a settings object most levers do not read. |
| OQ-2 | Trim by rewriting docstrings under a test-enforced cap, or by truncating at run time? | Lever 2's shape | **Rewrite.** More work and more honest: the measured "on" arm is what we would ship and the failure mode is a red test rather than a mangled description. It does **not** cost the ability to flip back by a boolean: the flag-off path hands over the rejoined description, byte-equal to the pre-split text (FR-033, FR-039), so both arms run at one commit and SC-007 holds. |
| OQ-3 | Keep the dynamic "check tools once evidence exists" tier, or restrict lever 4 to the two package-decidable tiers? | Lever 4's scope | **Restrict.** The dynamic tier invalidates the OpenAI prefix mid-session, makes two turns structurally different in a way the step log does not record, and buys tokens only on multi-turn sessions that mostly do not happen. |
| OQ-4 | Is a deterministic fastener-joint enumerator in scope for 005? | Lever 5's scope | **Out of scope for 005.** Roughly 150 lines plus tests, and a wrong pairing produces a deterministic wrong finding that looks authoritative. A separately specified increment with its own golden fixtures. |
| OQ-5 | May `skipped` and `out_of_scope` close an item for the purpose of stopping, as they do for finalizing? | Lever 7's guard | **Strict**, with a comment explaining why the two predicates deliberately differ. It fires less often and saves less, which is the correct trade: finishing is not the same as giving up. |
| OQ-6 | Add `file_modified_utc` and `file_size_bytes` to `ManifestEntry` (schema 1.3.0), or drop lever 9? | Lever 9 entirely | **Add the two fields, or drop the lever.** Without them the key cannot detect a change at all. Hashing document bytes probably costs more than the dump it would skip. |
| OQ-7 | `rms.*` only, or a per-check declared input digest? | Lever 11's scope | **`rms.*` only in v1**, excluding `individually_suppressible`. The broad version needs every check to declare and hash its inputs, and a check that forgets one carries a wrong verdict forever. |
| OQ-8 | Build `rms-part` and hold out a package before gating anything, or gate on `cover-blind-tap` alone? | Every Tier 2 and Tier 3 gate | **Build the set first.** A scheduling decision, not a code decision, and the one most likely to be skipped under time pressure. |
| OQ-9 | Confirm the four answers in R20.3, in particular the 20 percent threshold and the asymmetric worst-case treatment of lost defects versus median treatment of false alarms. | The first A/B | **Fix them before the first run**, not after a result is in hand. |
| OQ-10 | Does `session.ended` also carry the session totals? | Phase 1, severable | **Add it.** It saves the pane from owning a summing rule `SessionUsage` already defines. Severable if the smallest possible Phase 1 contract edit matters more. |
