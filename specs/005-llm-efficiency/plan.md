# Implementation Plan: LLM efficiency, speed, and token usage

**Branch**: `005-llm-efficiency` | **Date**: 2026-09-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-llm-efficiency/spec.md`; source document
`docs/llm-efficiency-options.md`; design brief and research notes for feature 005.

## Summary

Make what a review costs visible, then reduce it one lever at a time, behind a flag, default
off, adopted only against a recorded number with no quality regression.

**The owner's rule governs every line of this plan.** Nothing here proposes turning anything
on. Each lever is a design plus a flag plus tests plus an A/B protocol plus an adoption rule,
and the adoption decision is the owner's, taken against a row in a ledger that is rendered from
`scorecard.json` files rather than typed by hand.

The work splits four ways and the split is the design. **Instrumentation** is not an experiment
and carries no flag: every model round trip records what it cost, in the fields both SDKs
actually report, with unknown preserved as unknown. **One flag carrier** (`EfficiencySettings`,
ten booleans, every one `False`) is threaded as a single argument and recorded on the session, so
a results row can be attributed to a configuration. **A harness** (the stated six-run protocol plus
`swreview benchmark compare`) turns six runs into one decision row and refuses to score a run
whose recorded settings do not match the arm it claims. **The levers themselves**, in three tiers, each gated
alone.

Today there is no number to improve on. `grep -rn "usage" reviewer/src/swreview/agent/providers/*.py`
returns nothing and `TurnResult` carries `reason`, `text`, `steps`, `messages` and no usage
(VERIFIED, `agent/providers/__init__.py:187-199`). **The first measurement of feature 005 is the
baseline itself.**

Every claim in this plan and in `contracts/` about an SDK field or an SDK behavior is marked
VERIFIED or UNVERIFIED. **VERIFIED** means read on 2026-09-16 in this tree, or in a package
installed under `reviewer/.venv/Lib/site-packages` (`openai` 3.13.0, `google-genai` 2.23.0), at
the file and line cited. It never means an API was observed behaving that way. **UNVERIFIED**
means it needs a live provider call, a SOLIDWORKS seat or a timed run, and every UNVERIFIED claim
that gates a decision is a numbered probe.

## Technical Context

**Language/Version**: Python 3.11+ for everything in Tier 1 and Tier 2 (the instrumentation, the
flag carrier, the harness, the levers, the scorecard, the CLI). C# on .NET Framework 4.8 x64 for
Tier 3 only (lever 9's manifest fields and package index, lever 10a's `tessellate` bridge
command).

**Primary Dependencies**: **No new packages on either side.** Python: the installed `openai`
3.13.0 and `google-genai` 2.23.0 (read for fields that already exist; no SDK is upgraded by this
feature), `pydantic`, `typer`, `pyyaml`, and the existing `agent/`, `tools/`, `report/`,
`benchmark/` and `chat/` modules. C#: existing interop, `MeshExporter`, `ManifestBuilder`,
`PackageWriter`, `RunFolders`, `BridgeProtocol`, `BridgeDispatcher`, `ReadOnlyGuard` (read, not
changed). Providers stay **OpenAI (default) and Gemini**; Claude is not a provider of this
product and no Anthropic dependency is added.

**Storage**: Files only. Per run folder, unchanged in location: `session.json` (gains `usage` and
`efficiency`, both optional), `events.jsonl` (gains a `usage` event type), `report.md` (gains a
`## Tokens` section rendered only when usage is present). Per benchmark run directory:
`scorecard.json` and `scorecard.md` (gain token, round-trip and coverage-mix columns). Per run folder, also: a **run provenance record** naming the commit, the resolved
`EfficiencySettings`, the lever, the arm and the repetition. Per A/B study:
`ledger.json` and `ledger.md`
([contracts/ab-harness.md](contracts/ab-harness.md)). Tier 3 only: `run_root/package-index.json`.

**Testing**: pytest. The whole instrumentation layer and every Tier 1 and Tier 2 lever is
testable with **no API key and no seat**: `ResponseUsage.construct` and a hand-built
`GenerateContentResponseUsageMetadata` drive the two mappers, `FakeProvider` drives the runner,
ledger, report and scorecard paths, and a recorded OpenAI client drives the request-shape and
resumption assertions. The live probes are `reviewer/tests/live/` with
`pytestmark = pytest.mark.live`, skipped without a key, reporting 401, 429 and 5xx as a skip
rather than a failure, following `tests/live/test_openai_live_schemas.py`. Tier 3 adds
workstation probes. Goldens of features 001, 002, 003 and 004 stay byte-identical unless a task
says otherwise and refreshes them in the same commit.

**Target Platform**: as features 001 to 004. The reasoning side runs with no SOLIDWORKS licence
and in CI; Tier 3 needs the pilot workstation.

**Project Type**: extends the reviewer; Tier 3 extends the extractor and the add-in.

**Performance Goals**: none are asserted by this plan, which is the point. The instrumentation
adds one accumulator per round and one appended event per round, and the byte-budget test bounds
the tool payload. Every other performance claim in this feature is a measured result, not a goal.

**Constraints**: the reviewer stays **read-only**; `ReadOnlyGuard` is not touched and gains no
entry, including for lever 10a's `tessellate` (`GetTessellation`, `Tessellate`,
`CurveChordTolerance` and `GetBodies2` are not on the denylist and are not covered by its
`FeatureCut*`, `FeatureExtrusion*`, `InsertFeature*` or `SetSystemValue*` prefixes, so no guard
change is needed and none is made). Every lever flag defaults to `False`. **No lever flag reaches
the pane's `settings.schema.json` while it is being measured**: an engineer toggling experiment
flags mid-pilot makes the pilot's own numbers unreadable, and an adopted lever becomes a default
in code, not a checkbox. No quality trade is accepted for tokens.

**Scale/Scope**: ten flags, three tiers, one ledger. Out of scope and argued out in
[contracts/levers.md](contracts/levers.md): lever 8 (model tiers per job), lever 10b (lazy faces),
lever 11b (per-check input digests), a deterministic fastener-joint enumerator, and concurrent
local tool execution.

## Constitution Check

Constitution 1.0.0, ratified 2026-09-12.

| Principle | Gate | How this plan meets it | Status |
|-----------|------|------------------------|--------|
| I. Evidence before conclusions | Unknown stays unknown | Every token field is `int \| None`, never coerced to `0`, because the SDK builds responses with `BaseModel.construct` and a field the server omitted becomes `None` even where the annotation says `int` (VERIFIED, `openai/_models.py:231-259`; `cache_write_tokens` reproduced as `None` in 2.1 below). **A sum over rounds where any round reported `None` is `None`, not a partial sum**, the same discipline `Timing.baseline_minutes` already follows. A withheld tool writes `unresolved` coverage naming the rule that withheld it, never a silent miss and never `failed`. A pre-run digest carries a "NOT evaluated, and why" block generated from the same coverage machinery that writes the `skipped` items, so the model and the report are told the same thing. `check_tool_envelope` over zero bodies stops reporting `checked` (RK-12). | PASS |
| II. Deterministic numerics | No model judgement in a verdict | No lever puts a model anywhere near arithmetic. Lever 5's pre-run calls the **same tool functions through the same `ToolDispatch`**, not a parallel copy of the check logic, so every pre-run finding has a real `InvestigationStep` behind it. Lever 11a's carry-over key is a hash over `exceptions.fingerprint`, which already exists; no second hashing scheme is written. Lever 7's stop predicate is a pure function over a session. | PASS |
| III. Test-first with goldens | Tests precede code | The ten measurement-layer tests (section "Key points", point 2) are written before either adapter is touched, including the exact `construct` reproduction that makes `None` a `None`. Every lever's tests are listed in [contracts/levers.md](contracts/levers.md) and precede its implementation task. The byte-budget test (`tests/unit/test_tool_payload.py`) and the static-baseline regenerating script ship as **committed tests**, so the baseline number cannot go stale again (RK-19). `report.md` for a session with no usage is asserted byte-identical to the current golden. | PASS |
| IV. Semantic fidelity | Versioned IR, additive contracts | The IR moves only for Tier 3 lever 9 (`ManifestEntry.file_modified_utc` and `file_size_bytes`, a minor bump to 1.3.0, both optional with a gap when the path cannot be stat'ed). Every other contract edit is additive: a new optional property left out of `required` in `review-session.schema.json`, following the `provider_info` and `retry_of` precedent, so every feature 001 session stays valid; a new event type and body in `chat-events.schema.json`, which is `additionalProperties: false` on every body and a closed `type` enum (VERIFIED), so both are deliberate edits. | PASS |
| V. Engineered enough | DRY, explicit, no speculation | **One** `EfficiencySettings` object for ten flags rather than ten plumbed parameters across three call sites. **One** summing rule, on `SessionUsage`, which the ledger listener and the scorecard both call. **One** function builds both Gemini config shapes from a single `cache_name: str \| None`, rather than an `if` sprinkled through `_config`. Lever 2 splits one docstring instead of copying its text into the system prompt, so the text still lives in exactly one place. Lever 4 reuses the registry's existing five groups and the already-conditional bridge group rather than inventing a taxonomy. Lever 5 is a sibling of `record_partial_evidence`, called from the same place. Lever 7's wrapper is modelled on the shipped `StoppableTools`. Lever 11a reuses `exceptions.fingerprint`. Explicit over clever: lever 2 caps descriptions **by construction under a failing test**, not by run-time truncation that produces "...and never used as o". | PASS |
| VI. Inspectable findings, coverage tracked | Every run ends in evidence | A withheld tool, a carried-over finding and a reused package are each **stated in three places** (the session, the report and the pane or the ledger), never silent. The report gains a `## Tokens` section. The scorecard gains the coverage bucket mix, without which lever 7 cannot be gated at all. The ledger's `Decision` column records **adopt, keep off or re-measure**, so a rejected lever leaves a row rather than disappearing. Principle VI's "measured per design, not only on the best example" is exactly why precondition P-3 (grow the benchmark set) gates every Tier 2 and Tier 3 decision. | PASS |
| Technical constraints: documents are read, not written | The reviewer stays read-only | No lever writes to a model. Lever 10a's `tessellate` reads a tessellation and writes a **file** the host chose inside the package directory, exactly as `capture` already does; `ReadOnlyGuard` is a denylist and gains no entry. Lever 9 reads `FileInfo.LastWriteTimeUtc` and copies files inside the run root. | PASS |
| Technical constraints: coarse out-of-process calls on one STA thread | Tier 3 only | `tessellate` is one call for one component returning every `BodyRef` it wrote, answered by the existing single STA worker in arrival order. It is **review scope only** and bounded by `extraction.lazy_fetch_body_limit`, because it can take seconds and blocks every other bridge call behind it (probe P2). | PASS |
| Technical constraints: reasoning side runs without a licence | Python testable in CI | The instrumentation, the flag carrier, the harness, the ledger and every Tier 1 and Tier 2 lever are pure or filesystem-only and run with no seat and no key. | PASS |
| Technical constraints: no generic code execution tools | The curated surface does not grow | Lever 4 **removes** tools from the wire and adds no tool. Lever 10a adds one bridge command to a protocol vocabulary of four, not a tool the model can aim anywhere. No lever adds a model-facing capability. | PASS |
| Technical constraints: benchmark packages are the acceptance suite | 5 to 10 designs, some held out | This is the gate most likely to be skipped and it invalidates every adoption decision if it is. Today `benchmarks/sets/pilot.json` holds **one** package, `cover-blind-tap`, `held_out: false`, with two known defects and a `package.json` carrying zero mates, holes, threads, fasteners, faces, bodies, interferences, captures, features and equations (VERIFIED). Precondition P-3 builds `rms-part` and holds out at least one package **before any Tier 2 or Tier 3 gate is read**. | **PASS only after P-3** (Delivery order, Phase 2; RK-17) |
| Technical constraints: third-party reuse respects licenses | No new dependency | This feature vendors nothing and adds no package. | PASS |

Post-design re-check: no written constitution exception is needed. One precondition (P-3) must
land before any Tier 2 or Tier 3 adoption decision is taken; four Complexity Tracking rows.

## Project Structure

### Documentation (this feature)

```text
specs/005-llm-efficiency/
├── plan.md, spec.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, usage.md, levers.md, ab-harness.md, tool-tiers.md}
└── checklists/requirements.md
```

### Source code (repository root)

```text
reviewer/src/swreview/
├── agent/providers/__init__.py        # + TokenUsage (beside EffortMapping; adapters produce it)
├── agent/providers/openai_provider.py # usage per round; prompt_cache_key; diagnostics;
│                                      #   parallel_tool_calls from the constructor; tool_choice
├── agent/providers/gemini_provider.py # usage per round read OUTSIDE the candidates loop;
│                                      #   one config builder taking cache_name: str | None
├── agent/providers/fake.py            # ScriptedTurn.usage, a fixed synthetic default; multi-call round
├── agent/providers/schema.py          # lever 2: parse_docstring returns notes; ToolSpec.notes
├── agent/usage.py                     # NEW. UsageLedger: an EventSink listener over `usage` events
├── agent/settings.py                  # + EfficiencySettings (ten flags, all False)
├── agent/runner.py                    # + usage wiring in finalize(); efficiency threaded as ONE
│                                      #   argument; prerun_checks beside record_partial_evidence;
│                                      #   the stop predicate beside (and used by) finalize_session
├── agent/checklist.py                 # read; COVERAGE_BUCKETS is NOT reused by the stop predicate
├── report/session.py                  # + SessionUsage (and the ONE summing rule),
│                                      #   ReviewSession.usage, ReviewSession.efficiency
├── report/markdown.py                 # + ## Tokens, rendered only when session.usage is not None
├── benchmark/scorecard.py             # + usage, round_trips, cached_input_share, wall_clock_s,
│                                      #   seconds_to_first_finding, coverage bucket mix; Aggregate
├── benchmark/compare.py               # NEW. Reads N run folders, validates each against
│                                      #   its provenance record; renders ledger.json + .md
├── benchmark/adoption.py              # NEW. The FR-028 rule; the computed Decision column
├── benchmark/runner.py                # + one efficiency argument, passed through
├── tools/registry.py                  # + WithheldTool; tier selection in functions_for;
│                                      #   the lever-2 flag applied AFTER spec_for
├── tools/context.py                   # read; the withheld path reuses record_coverage
├── tools/measure.py                   # RK-12: check_tool_envelope over zero bodies is unresolved
└── cli.py                             # + benchmark compare; --lever on benchmark run and
                                       #   review; the run provenance record

reviewer/tests/
├── unit/test_tool_payload.py          # NEW. Pinned byte budget, per-tool ceiling, the regenerated
│                                      #   static baseline as a committed script
├── unit/test_usage_mapping.py         # NEW. The two mappers, including the construct reproduction
├── live/test_usage_live.py            # NEW. Probes L1, L2, L3, L3b, G1, G2, G3, G4, G5
└── ...                                # one test module per lever, named in contracts/levers.md

extractor/SwReview.AddIn/Review/ReviewPage/   (Phase 1, the running usage line; FR-014)
├── app.js                             # + a `usage` case in the event switch (:375-412)
├── render.js                          # + the running usage line itself
└── index.html                         # where the line sits

extractor/  (Tier 3 only)
├── SwReview.Extractor/Dump/ManifestBuilder.cs  # + file_modified_utc, file_size_bytes (IR 1.3.0)
├── SwReview.Extractor/Dump/PackageWriter.cs    # + reuse_key, extractor.completed, phase timing
├── SwReview.Extractor/Dump/MeshExporter.cs     # ExportBody reused by tessellate; not forked
├── SwReview.Extractor.Console/Serve/PROTOCOL.md# 1.0 -> 1.1: + tessellate; ping reports it
└── SwReview.AddIn/Review/RunFolders.cs         # + package-index.json append and bounded lookup

docs/llm-efficiency-options.md                  # the corrected static baseline row (RK-19)
```

**Structure decision**: the instrumentation goes where the producer already is, and the
aggregation goes where the consumer already is. `TokenUsage` is provider-neutral, is produced by
adapters, and `report/session.py:22` already imports across that boundary (VERIFIED), so it lives
in `agent/providers/__init__.py` beside `EffortMapping` for the reason that module's docstring
already gives. `SessionUsage` and its summing rule live on the session, because the session is
what is written and read back. `agent/usage.py` is one small new module holding the listener,
rather than another block inside `agent/runner.py`, which is already the longest module in the
tree. `benchmark/compare.py` is new because an A/B study is not a benchmark run: it spans run folders
and commits, and `run_benchmark` deliberately knows about neither. There is no `ab` sub-app: the
study is a stated procedure of six `benchmark run` invocations and `compare` is the one reader
over what they left behind, which is what the design brief, spec.md FR-024 and
checklists/requirements.md already settled.

## Phase 0 and Phase 1

Research and the measured static baseline are in [research.md](research.md); the records are in
[data-model.md](data-model.md); the four contracts are in [contracts/](contracts/). Key points
that tasks must honor:

1. **Record the raw provider fields; derive nothing across providers except `total_tokens`.**
   Two field relationships are opposites of each other and both are easy to get wrong.
   `cached_content_token_count` is **inside** `prompt_token_count` (VERIFIED, `types.py:8468-8471`,
   "When `cached_content` is set, this also includes the number of tokens in the cached content"),
   so adding them double counts. `tool_use_prompt_token_count` is **outside**
   `prompt_token_count` and is a separate addend of `total_token_count` (VERIFIED,
   `types.py:8488-8491`); our reviewer feeds every tool result back as input, so on Gemini this is
   a first-class number and dropping it understates our input cost. Symmetrically, OpenAI's
   `reasoning_tokens` is a subset of `output_tokens` while Gemini's `thoughts_token_count` is a
   separate addend of the total. A single cross-provider "output tokens" column compares two
   different quantities. The full mapping table is normative in
   [contracts/usage.md](contracts/usage.md).

2. **Unknown stays unknown, and it decides the types.** VERIFIED against the installed package:

   ```
   python -c "from openai.types.responses.response_usage import ResponseUsage; \
   u = ResponseUsage.construct(input_tokens=100, input_tokens_details={'cached_tokens':64}, \
     output_tokens=10, output_tokens_details={'reasoning_tokens':4}, total_tokens=110); \
   print(u.input_tokens_details.cache_write_tokens)"
   -> None
   ```

   `cache_write_tokens` is annotated `int` (VERIFIED, `response_usage.py`, `InputTokensDetails`)
   and is `None` when the endpoint did not report it. So every field is `int | None` on our side;
   a reader typed `int` raises `TypeError` on the first sum and a reader that coerces to `0`
   reports "zero cached tokens" for "the endpoint did not say", which is a Principle I violation.
   Every sub-field is read with `getattr(..., None)`, because `input_tokens_details` itself can be
   `None` on a constructed response. `uncached_input_tokens` is a **property, not a field**, so it
   cannot go stale, the rule `Timing.replace` already follows.

3. **Usage is a per-round event on the stream, not a field on `TurnResult`, and the failure path
   is why.** `run()` is a `while True` loop and `_respond` is one HTTP request per iteration
   (VERIFIED, `openai_provider.py:240,292`), so a turn with six serial tool calls is seven
   requests: **usage is per round**. Both adapters raise out of the round loop on a provider
   error, and `ReviewRun._run_turn`'s `except Exception` branch finalizes and re-raises with no
   `TurnResult` to read. A design that carries usage on `TurnResult` therefore reports **zero cost
   for the turn that cost the most**: five successful rounds then a rate limit on the sixth.
   `EventSink.emit` opens, appends and closes per event precisely so the stream survives the
   process dying mid-review, so the five paid rounds are already on disk (RK-2).

4. **`round_index` is the round-trip counter, and it is the adapter's own per-turn counter.**
   Same convention `tool.started.step_index` already uses, for the reason the module docstring
   gives: an adapter sees one turn and cannot know a session-level number, and turns are delimited
   by the existing `turn.ended` events. **Levers 5, 6 and 7 are unmeasurable without it.**
   `TurnResult.steps` counts tool calls, which is a different number, and with lever 6 on the two
   diverge by exactly the amount lever 6 is trying to save.

5. **Gemini reads usage outside the candidates loop.** The current loop body runs only for chunks
   that have candidates (`for candidate in chunk.candidates or []`, VERIFIED,
   `gemini_provider.py:393-394`), so a final chunk carrying usage and no candidate is silently
   dropped. **The SDK does not aggregate chunk usage** (VERIFIED: `google/genai/models.py:1718`
   and `:1757` copy `usageMetadata` through per chunk and nothing merges it), so the adapter must
   choose. "Last chunk that carries usage wins" is correct under both "cumulative" and "only the
   final chunk carries it", and wrong only under "each chunk is a delta", which is **UNVERIFIED
   and is probe G3**.

6. **One flag carrier, threaded as one argument, recorded on the session.** `EfficiencySettings`
   is a frozen `extra="forbid"` model in `agent/settings.py` beside `ProviderSettings`, which is
   already the single place per-provider defaults live. It is one keyword argument through
   `start_review` (`runner.py:595-651`), held on `ReviewRun` (`:394-424`) exactly as `effort` and
   `max_steps` already are, one argument through `run_benchmark` (`benchmark/runner.py:69-76`) and
   one through `cli._review_fn` (`cli.py:1341-1364`). `ReviewSession.efficiency` is optional,
   modelled on `provider_info`, which is optional for the same reason: a session written before
   the field existed has none. **Without it no results row can be attributed to a configuration
   and the A/B table cannot be rebuilt from the run folder.** This is the argument for paying the
   one contract edit and one golden refresh in Phase 1 rather than ten times over.

7. **Levers are not independent in effect, so the arm records which others were on.** The
   interaction matrix is normative in [contracts/levers.md](contracts/levers.md). The four that
   change the plan: lever 2 moves about 10 KB from the tool array into the system prompt and both
   are in OpenAI's cacheable prefix, so **lever 2 is measured with lever 3 off**; a tool array that
   changes mid-session invalidates the prefix, so **lever 4's tiers are package-decidable and fixed
   for the whole session**, which removes the interaction by construction; lever 5 removes the
   round trips lever 6 would have saved, so **lever 6 is measured first, against the lever-5-off
   baseline**; and lever 5 plus lever 7 can end a turn before the model looks at fit, stack or
   drawings, so **5 and 7 never share an arm** until each is gated alone.

8. **The prefix is already stable, so lever 3 on OpenAI is mostly observability.** Three facts,
   all VERIFIED by reading: `system` is built once in `start_review` and never mutated, and its
   three parts are deterministic; `tool_params` is byte-identical every turn and across processes
   (`strictify` and `gemini_adapt` use no set iteration; the sha256 is identical under
   `PYTHONHASHSEED` 0, 1 and 12345); history is append-only (`self.messages = [dict(m) for m in
   result.messages]`, `_encode_assistant` replays raw output items verbatim, and `answer_evidence`
   mutates `session.findings` and never `self.messages`). So lever 3 is "name the cache, record
   the diagnostics, and stop the other levers from breaking what we already have".
   `prompt_cache_key = str(session.session_id)` because **the key must survive a process restart**:
   the pane restarts the backend on a settings save and resumes the same run folder, and a
   process-local random value would silently drop every hit afterwards.

9. **`PromptCacheDiagnostics` is the instrument that prices lever 4 before lever 4 is written.**
   VERIFIED, `openai/types/responses/response.py:195-241`, field at `:418`: a discriminated union
   of `cache_hit`, `cache_miss`, `comparison_response_not_found` and `unavailable`, where the miss
   variant carries `cache_missed_tokens`, `comparison_reusable_tokens` and an exact `reason` enum
   (`model_changed`, `prompt_cache_key_changed`, `tools_changed`, `text_format_changed`,
   `reasoning_effort_changed`, `verbosity_changed`, `context_compacted`, `input_changed`,
   `service_tier_changed`). That enum **is** the authoritative list of what breaks our prefix,
   straight out of the installed SDK. It is requested by setting
   `prompt_cache_options.comparison_response_id` to the previous response's id (VERIFIED,
   `response_create_params.py:165-175`; `PromptCacheOptions` says "Supported for `gpt-5.6` and
   later models", which is our default).

10. **A withheld tool is registered, not absent, and today's behaviour is wrong for it.** A call
    to an unregistered name goes to `ToolDispatch.call` (VERIFIED, `registry.py:450-478`), returns
    `{"error": "no tool named ...; the tools available are [...]"}`, and `SessionSink.record`
    (VERIFIED, `:226-253`) writes a **`failed`** coverage item. Three things are wrong with that
    as the answer for a tool we declined to offer: `failed` says the tool broke; `failed` is
    deliberately excluded from the checklist's closing buckets (VERIFIED,
    `agent/checklist.py:21-27`), so the item ends `unresolved` at finalization with the generic
    reason and the engineer never learns we withheld it; and the error message hands the model a
    32-name list in a tool result. The design and its assertions are normative in
    [contracts/tool-tiers.md](contracts/tool-tiers.md).

11. **Lever 6 is round-trip batching only; local execution stays serial in request order.**
    Requesting several calls in one round trip needs no threads and is the token and latency win.
    Running them on several threads costs three real correctness hazards and buys nothing over
    list comprehensions: `ToolContext.current_step_id` returns `len(session.steps)` and its own
    docstring explains that a tool writing a finding is citing the step it is about to be recorded
    as, so under concurrency two tools read the same value and one cites the other's step
    (**silent provenance corruption, not a crash**); `SequentialIdAllocator.__next__` is not atomic,
    so two findings can take the same `F-003`; and the step log stops being deterministic while
    `tests/golden/` compares sessions. Note also that **Gemini already makes parallel tool calls in
    production**: `_config` sets no such setting and its loop is already written for multiple calls
    (VERIFIED, `gemini_provider.py:444-466`), while OpenAI sends `"parallel_tool_calls": False` on
    every request (VERIFIED, `openai_provider.py:308`). "One round trip per query" is true of
    OpenAI only, so **lever 6 is measured on OpenAI only** and the ledger row says "Gemini: on by
    default, not measurable as A/B" rather than fabricating a comparison.

12. **Lever 7 stops by withdrawing the tools, never by raising out of `ToolSet.call`.** The
    mechanism an implementer would reach for by analogy is `StoppableTools`, which raises
    `TurnStopped` (VERIFIED, `chat/server.py:344-352`). The trap: the triggering call gets no
    output, so on OpenAI the history holds a `function_call` with no matching
    `function_call_output`, and the module docstring says plainly that every one needs a match or
    the next request is rejected (VERIFIED, `openai_provider.py:96-99`). That would quietly break
    `answer_evidence` and `continue_session`. Stop gets away with it because Stop means the
    engineer abandoned the turn; coverage completion does not. The lever instead sets
    `tool_choice: "none"` for the next round on OpenAI (VERIFIED,
    `openai/types/responses/tool_choice_options.py`) or `FunctionCallingConfig(mode=NONE)` on
    Gemini (VERIFIED, `google/genai/types.py:482-483`, "Model will not predict any function
    calls"), with the soft sentence carried as the accompanying tool-result text. Every call keeps
    its output and the session stays resumable (RK-8).

13. **Lever 7's stop predicate deliberately differs from `Checklist.bucket_of`, and the comment
    saying why is part of the deliverable.** `bucket_of` searches
    `("checked", "skipped", "unresolved", "out_of_scope")` (VERIFIED, `checklist.py:21-27`). For
    *finalizing*, an item closed any way is closed, and that is right. For *stopping early* it is
    not: a review that skipped six of nine items has not finished, it has given up. The stop
    predicate requires every item closed by a finding or by `checked`. It fires less often and
    saves less, which is the correct trade, and **someone will "DRY" the two together later and
    reintroduce the hole unless the comment is there** (RK-7).

14. **The scorecard must carry the coverage bucket mix, and it ships with lever 7, not after it.**
    `PackageScore` carries `unresolved_count` and no per-bucket breakdown (VERIFIED,
    `benchmark/scorecard.py:65-82`). Lever 7 converts `mark_coverage` into a turn-ending call,
    which changes the incentive: a model that wants to finish can close the checklist with nine
    `mark_coverage(bucket="skipped")` calls, producing a short cheap run that **looks efficient in
    the results table**. Lever 7 cannot be gated without the breakdown.

15. **The static baseline is regenerated from the tree, never transcribed.** Measured on this tree
    (VERIFIED): **32** tools with no bridge, **34,065 bytes** of OpenAI `tools` array (compact
    JSON), 34,248 bytes of Gemini function declarations, 35 tools and 37,709 bytes with
    `--bridge`, 14,685 bytes of descriptions alone, and **15,274 bytes with every description
    emptied**, which is the structural floor lever 2 cannot reach.
    `docs/llm-efficiency-options.md` records 29 tools and 32,435 bytes and names a different set of
    longest descriptions; the RMS tools have landed since. The regenerating script is committed as
    `tests/unit/test_tool_payload.py` and the document's baseline row is corrected in the same
    change (RK-19). Byte counts are **not** token counts; at the roughly 4 bytes per token the
    baseline itself implies, 34,065 bytes is about 8,500 tokens per request (UNVERIFIED as a token
    count), and the first instrumented run replaces the estimate with a real number.

16. **Two standalone correctness fixes, each its own commit with its own test, neither gated on a
    lever.** (a) `check_tool_envelope` over zero bodies: with `bodies == []` both `meshes` and
    `unresolved` stay empty, `envelope_raycast` with `meshes=[]` returns `EnvelopeResult(hits=[],
    unresolved=[])`, and the result is `status: "checked", bodies_swept: 0, hits: []`. A model
    reading that sees a tool-access check that ran and found nothing in the way. It is reachable
    today with `swreview-extract dump --meshes none --profile full` and it violates the module's
    own docstring ("a tool envelope that could not sweep a body has not established that the body
    is out of the way"). Fix: refuse `checked` when `bodies_swept == 0` (RK-12). (b) Dump phase
    timing: no `Stopwatch` and no elapsed field exists anywhere in `Dump/PackageWriter.cs`, and
    `DumpSummary` carries counts only, so levers 9 and 10 have **no metric at all** today.
    `extractor.phases` as a list of `{name, elapsed_ms, status}` follows the shape
    `SuppressTestRow.elapsed_ms` already set, and it is useful on its own for diagnosing a slow
    dump.

17. **`run_benchmark` already double-writes one timing field, and the baseline table must say
    which one it is quoting.** It times each package with `time.perf_counter()` and writes it into
    `Timing.unattended_runtime_minutes` via `_record_unattended_runtime`, **overwriting** the
    number `finalize_session` computed from `started_at` to `ended_at` (VERIFIED,
    `benchmark/runner.py`, `report/session.py`). The benchmark's wins because it runs last and it
    includes package load and adapter construction. Not a bug; a labelling requirement.

## Delivery order

Five phases. **Each phase ends with a recorded result, and no lever moves to "adopted" without a
ledger row.** A lever that fails its gate stays off and its row stays in the ledger, because the
record of what did not work is the point.

| Phase | Deliverable | Flags | Needs a key | Needs SOLIDWORKS | Exit criterion |
|-------|-------------|-------|-------------|------------------|----------------|
| **1. Instrument** | `TokenUsage`; the `usage` event; both adapters emit per round; `fake` emits a deterministic synthetic record; `agent/usage.py::UsageLedger`; `SessionUsage` and `ReviewSession.usage` written in `finalize()`; optional `usage` on `session.ended`; `EfficiencySettings` and `ReviewSession.efficiency` threaded as one argument; the three contract edits and the golden refresh, paid once; `report.md` `## Tokens`; `PackageScore` and `Aggregate` additions including `seconds_to_first_finding` read from `events.jsonl`; three new scorecard columns; `tests/unit/test_tool_payload.py` and the regenerated static baseline; the live probes L1, L2, L3, L3b, G1, G2, G3, G4, G5 | **none; nothing here is an experiment** | probes only | No | Every run in the tree records what it cost; probes L1, L2, G3 and G4 have answers |
| **1b. Standalone fixes** | The `check_tool_envelope` zero-bodies guard (RK-12); dump phase timing `extractor.phases` (needed before Tier 3 has any metric) | none | No | (b) yes, to time | Each is its own commit with its own test; neither is gated on a lever |
| **2. Harness** | `benchmark/compare.py`, `benchmark/adoption.py` and `swreview benchmark compare`; the run provenance record written by `benchmark run`; `ledger.json` and `ledger.md` ([contracts/ab-harness.md](contracts/ab-harness.md)); **the four adoption-rule answers fixed in writing before the first run** (section 5.3 of the brief, restated in the contract); **P-3: build `rms-part` from `benchmarks/native/rms-part/RECIPE.md` and hold out at least one package**; **the baseline runs**: three reps per provider on the grown set, which are the first ledger rows | none | yes, for the baseline runs | P-3 needs a seat to build `rms-part` | The ledger holds a baseline row per provider and model; `compare` refuses a run whose recorded `efficiency` does not match its provenance record |
| **3. Tier 1** | In this order, because the instrument comes before the thing it prices: **3-OpenAI** (`prompt_cache_key`, `prompt_cache_options`, diagnostics onto the `usage` event, plus the prefix-stability regression test); **2** (the docstring split and the `## Tool notes` block, both arms at one commit because flag-off hands over the rejoined description, measured with lever 3 off); **4** (package-decidable tiers plus `WithheldTool`, its row stating the asymmetry rather than averaging it away); **3-Gemini**, written **only if** probe G4 shows implicit caching is not already delivering | `prompt_cache_key`, `trim_tool_descriptions`, `tool_tiers`, `gemini_explicit_cache` | yes | No | One ledger decision row per lever per provider and model |
| **4. Tier 2** | In this order, so each lever is measured against a baseline the next has not consumed: **6** (one line on OpenAI; measured against the lever-5-off baseline; OpenAI only); **5** (largest expected saving, largest behavioural risk); **7** (the strict stop predicate and the coverage bucket mix ship together; **never in the same arm as 5** until each is gated alone). **Lever 8 is not in this phase**; it is deferred with reasons in [contracts/levers.md](contracts/levers.md) | `parallel_tool_calls`, `prerun_checks`, `coverage_stop` | yes | No | One ledger decision row per lever per provider and model, each carrying its lever-specific counter |
| **5. Tier 3** | On the workstation with its own harness, because `swreview benchmark run` iterates pre-built package directories and **no dump happens** (VERIFIED, `benchmark/runner.py:88-104`), so these three are invisible to it. **9** (`ManifestEntry` to IR 1.3.0, `reuse_key`, `package-index.json`), gated first on byte-identity of the reused package; **10a** (`tessellate` at PROTOCOL 1.1, meshes only), gated on identical `bodies_swept` or a named `unresolved`; **11a** (`rms.*` only), gated on every finding touching an edited part being re-run. **Lever 12 is standing practice with a review cadence, not a phase task** | `package_reuse`, `lazy_meshes`, `carry_over_rms` | yes | **Yes** | Each lever's pass/fail precondition holds before its scorecard row is read at all |

**Dependencies between phases**: Phase 2 cannot start before Phase 1, because an A/B with no
token number is not an A/B. **Phases 3, 4 and 5 cannot take an adoption decision before P-3**,
because a gate whose control arm is one package with two known defects and no geometry decides
nothing: one lost defect is a 50 percent swing and `recall` is `None` whenever
`held_out_known_defects` is zero (VERIFIED, `scorecard.py:200-204`). Tier 3 additionally needs
Phase 1b(b).

## Risks and mitigations

| # | Risk | How it shows | Mitigation | Residual |
|---|------|--------------|------------|----------|
| RK-1 | A `None` token count is coerced to `0` and the ledger silently understates | A cached share that reads as a win or a regression and is neither | `int \| None` everywhere; any-null-makes-the-sum-null, defined once on `SessionUsage`; the exact `construct` reproduction as a unit test | None |
| RK-2 | The usage of a turn that raised is lost, which is the expensive turn | Five paid rounds recorded as zero | Usage is a per-round event on the stream, written by `EventSink.emit`, which opens, appends and closes per event | None |
| RK-3 | The two providers' usage fields are compared as if they were the same quantity | A results table that reads as a win that is neither | Raw provider fields recorded; cross-provider comparison only on `total_tokens`; the derivation named in the contract | None |
| RK-4 | A lever that saves tokens quietly changes which tool the model picks | The scorecard passes and the review's character changed | A tool-name histogram per run from `session.steps` (lever 2); the `check_fit` and `check_axial_stack` call counts (lever 5) | UNVERIFIED whether the histogram is sensitive enough; recorded either way |
| RK-5 | A withheld tool becomes a silent miss | "modeling.resilience: not closed out" with no reason | `WithheldTool` writes `unresolved` coverage naming the tier rule; `failed` stays empty; the test asserts both | None |
| RK-6 | The pre-run digest suppresses exploration | Fewer model-driven checks for the same token win | The "NOT evaluated, and why" block generated from the coverage machinery, not written as prose; the call-count gate | Behavioural, so it is a measured gate rather than a guarantee |
| RK-7 | Coverage-driven stop rewards giving up | Nine `skipped` items and a short cheap run that looks efficient | The strict stop predicate with its comment; the coverage bucket mix in the scorecard, shipped with the lever | None |
| RK-8 | Stop mechanism A breaks `answer_evidence` on OpenAI | A `function_call` with no `function_call_output`; the next request is rejected | Mechanism C (withdraw the tools for the next round); the resumption test on the recorded client, which the fake cannot see the difference on | None |
| RK-9 | Concurrent local execution corrupts step provenance | A finding citing another tool's step; duplicate finding ids; non-deterministic goldens | Lever 6 is round-trip batching only; local execution serial in request order | None |
| RK-10 | A stale package is reused | A report that looks fresh and is not | The honest key (extractor and schema version, profile, the four dump options, every manifest entry, mtime, size, suppression state); refusals for unsaved changes, non-resolved components and aborted dumps; **the key is recomputed at reuse time** from the live document's references, never trusted from the file; `reused_from` stated in three places | Unsaved in-memory edits are refused rather than detected; clock skew produces a false miss, which is the safe direction |
| RK-11 | A reused `model_check` package is handed to a full Review | Holes, fasteners, faces and bodies silently empty by design | Profile and the four dump options are in the key | None |
| RK-12 | `check_tool_envelope` reports `checked` over zero bodies | A silent false clear on tool access, **reachable today** | The zero-bodies guard, fixed in Phase 1b as its own commit | None |
| RK-13 | Lazy faces re-open every geometry exception | `exceptions.json` fills with `needs_review` and engineers stop reading it | Lever 10 is **meshes only**; 10b is parked as a redesign, not a flag. The `geometry` fingerprint hashes the sorted parameters of each component's faces, so a package extracted without faces flips every accepted geometry exception | None, because the cause is scoped out |
| RK-14 | A bridge tessellation stalls the STA worker | The pane appears hung during a review | `extraction.lazy_fetch_body_limit`; the existing circuit breaker; review scope only; probe P2 measures it before adoption | Measured, not assumed |
| RK-15 | A carried-over finding should have changed | A verdict that is a memory | The six carry guards; `rms.*` only in v1, excluding `rms.detail.individually_suppressible`; the edited-feature-row test | None |
| RK-16 | Carry-over "improves" recall by remembering | A lever that looks like a quality gain | The carried count is recorded per arm in the ledger, and carried plus re-run equals total is an asserted invariant | None |
| RK-17 | The benchmark set is too small for any gate to mean anything | Two defects decide a 50 percent swing; `recall` is `None` | P-3 before any Tier 2 or Tier 3 adoption decision | **This is the one most likely to be skipped under time pressure** |
| RK-18 | A Gemini cached run 400s the whole review | A review that dies rather than degrades | When `cached_content` is set, the cached fields must **not** also be sent, and the SDK enforces nothing (VERIFIED by absence of any validation in `google/genai/`), so the failure is a run-time 400. One function builds both config shapes from a single `cache_name: str \| None`, tested both ways; the flag is read once at `start_review`; probe G2 confirms the rejection is real before the branch is trusted | None once G2 answers |
| RK-19 | The static baseline is transcribed and stays wrong | 29 tools versus 32; 32,435 bytes versus 34,065 | The regenerating script is a committed test; `docs/llm-efficiency-options.md` is corrected in the same change | None |
| RK-20 | A lever is adopted on a number produced by a different configuration | A row nobody can reproduce | Two independent writers, cross-checked: `session.efficiency` comes from the runner's resolved `EfficiencySettings`, the run provenance record comes from `cli.py` and the `--lever` options actually typed. `swreview benchmark compare` refuses a run whose `session.efficiency`, provider, model, effort, commit or set hash disagrees with its provenance record, and names the field; "other levers on" is a required ledger column | None |

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|-----------|------------|--------------------------------------|
| A settings object (`EfficiencySettings`) carrying ten booleans that most call sites never read | A results row that cannot be attributed to a configuration is not evidence, and ten levers each inventing a setting, a session record and a scorecard grouping is exactly the repetition Principle V forbids. One object is one contract edit to `review-session.schema.json`, one golden refresh and one threaded argument | One plumbed parameter per lever is ten signature changes across `start_review`, `run_benchmark` and `cli._review_fn`, ten contract edits, and ten chances to forget to record one. Reading flags from the environment inside the code that uses them would make a run's configuration unrecoverable from its own run folder |
| A new event type on a contract that is `additionalProperties: false` with a closed `type` enum, plus two new optional session fields, all in Phase 1 before any lever exists | The failure path is the reason (RK-2): usage carried home on `TurnResult` reports zero for the turn that cost the most. And paying the contract edit and the golden refresh once, up front, is strictly cheaper than paying it per lever | Recording usage only in memory, or only in the benchmark, loses the pane and the failure path. Deferring the contract edit until the first lever needs it means the baseline runs, which are the whole of Phase 1's output, produce nothing durable |
| A second, deliberately different "is this checklist item closed" predicate beside `Checklist.bucket_of` | Finalizing and stopping early are different questions. For finalizing, an item closed any way is closed. For stopping, `skipped` and `out_of_scope` mean the review gave up, and treating them as closers rewards a model for skipping its way to a cheap run that looks efficient in the results table (RK-7) | Reusing `bucket_of` is the DRY-looking answer and it is wrong: it makes the lever's saving come partly from abandonment. Parameterizing `bucket_of` with a bucket set would hide the distinction behind an argument nobody reads at the call site; the second predicate with a comment naming the trap is explicit over clever |
| A new `benchmark/compare.py` and a ledger that spans run folders and commits, rather than a `--repeat` flag on `benchmark run` | The protocol is six runs alternated across two arms, some of which are at different commits (lever 2's trim is not recoverable by flipping a boolean), and the decision needs worst-case and median treatment of different columns. Three separate run folders also make a re-run of one flaky package possible | A repeat loop inside `run_benchmark` would have to invent a nested folder layout and an aggregation, which is the scorecard's job, and it would leave `run_benchmark` knowing about arms, commits and levers. Keeping the ledger as a hand-typed table in `docs/` is what feature 005 exists to stop: typed numbers go stale and cannot be audited |

## Open questions

Q1 to Q10 are carried from the design brief and each names the phase it blocks, the options and a
recommendation. They are not restated here. One further question this plan raises:

**Q11 (Phase 2, blocks the harness's shape). Should the A/B harness be a single command that
runs the six arms, or a stated procedure plus one reader?** This plan says **a procedure plus one
reader**: the engineer runs `swreview benchmark run --lever ...` six times, alternated, scores
each, and then `swreview benchmark compare` validates the six run folders against their
provenance records and renders the decision row. `compare` never contacts a provider and never
starts a run. Six unattended live runs behind one command is hours of wall clock and real money
with no seam to restart from, and it would put arms, commits and levers inside `run_benchmark`,
which deliberately knows about none of them. Every arm is one commit, lever 2 included, whose off
arm is its flag off rather than an earlier commit. **The cost, stated rather than hidden**: the engineer runs six commands
rather than one, and the alternation of the arms is a discipline the contract states rather than
something the code enforces. A wrapper command that shells the six and then the compare is a thin
change and should be argued on its own. **Recommend: procedure plus one reader, and `compare`
never contacts a provider.**
