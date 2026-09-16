# Quickstart: Measuring the LLM Efficiency Levers

**Feature**: `005-llm-efficiency` | **Plan**: [plan.md](plan.md) | **Tasks**: [tasks.md](tasks.md) | **Contracts**: [contracts/](contracts/)

One scenario per phase. Every scenario states the exact commands and the ledger rows they must produce. **A number written into a table below as `<n>` is a number nobody has measured yet**; a number written out is one this tree already produced and a scenario that disagrees with it has found a defect, not a new baseline.

## Prerequisites

Everything from features 001, 002 and 003. Scenarios 1a, 2 and the deterministic halves of 3 and 4 run with **no SOLIDWORKS and no API key** on any machine that can run the Python test suite. Scenario 1b and every A/B arm need a live provider key and **spend real money**. Scenario 5 needs the pilot workstation: SOLIDWORKS 2024 SP5 with the interop assemblies at 32.5.0.48, the add-in registered, and the pilot assembly plus the `rms-part` fixtures built by hand from `benchmarks/native/rms-part/RECIPE.md`.

The reviewer stays read-only in every scenario here. Nothing below writes to a model, and Scenario 5's `tessellate` reads tessellation through members that are already off the `ReadOnlyGuard` denylist, so no guard change is made and none should be.

### The run root

Every scenario writes into one scratch run root, never into the repository, because `benchmark run` creates one subdirectory per package and `benchmark score` writes `scorecard.json` and `scorecard.md` beside them.

```powershell
cd reviewer
$runs = "$env:TEMP\swreview-005"
New-Item -ItemType Directory -Force $runs | Out-Null
$keys = "..\benchmarks\answer_keys"
$set  = "..\benchmarks\sets\pilot.json"
```

### The one rule every A/B arm obeys

Six runs per lever per provider and model, three off and three on, **alternated** (off, on, off, on, off, on), so provider-side drift during the session does not land entirely on one arm. Fixed across all six: the set file, the answer keys, the model id, the effort, `max_steps`, the checklist, the packages on disk byte-identical, and the tree at one commit. Human timing is recorded **once per package per arm, not per repetition**, because a human baseline does not change between repetitions and re-measuring it would put noise into `net_saved_minutes`.

---

## Scenario 1 (Phase 1): instrumentation and the baseline

### 1a The measurement layer, offline

```powershell
uv run pytest tests/unit/test_tool_payload.py tests/unit/test_usage_model.py `
  tests/unit/test_usage_openai.py tests/unit/test_usage_gemini.py `
  tests/unit/test_fake_usage.py tests/unit/test_usage_event.py `
  tests/unit/test_usage_ledger.py tests/unit/test_efficiency_settings.py `
  tests/unit/test_usage_contracts.py tests/unit/test_no_lever_in_pane_settings.py `
  tests/unit/test_report_tokens.py `
  tests/unit/test_scorecard_usage.py tests/unit/test_schema_sync.py
uv run pytest tests/golden
uv run python -m tests.unit.test_tool_payload --write
```

Expected from the unit suite: `cache_write_tokens` reads `None` and never `0` for a response built with `ResponseUsage.construct` that omitted it; an all-`None` Gemini `usage_metadata` yields an all-`None` `TokenUsage`; a Gemini stream whose final chunk carries usage and **no candidates** records that usage; a turn that raises on its third round still records rounds 1 and 2 in `session.usage`; one null in one round makes that total null rather than a partial sum; a `usage` event validates against the amended `chat-events.schema.json` and every existing event type still validates unchanged; a feature 001 `session.json` with no `usage` and no `efficiency` still loads and validates; and **none of the ten `EfficiencySettings` field names appears anywhere in the pane's `settings.schema.json`** (SC-008), iterated from the model so a lever added later is covered without anyone remembering to extend the test.

Then open the Task Pane on a running review and watch the line above the transcript: the tokens spent so far, the cached share, the round trips and the latency of the last round update **while the turn is still running**, accumulated in the pane from the `usage` events it already consumes (FR-014, US1 scenario 9). The cached share reads `unknown` until probe L1 is recorded, and a null in any round reads `unknown` and never `0`. `GET /sessions/{chat_id}` is unchanged: these numbers live on the stream and in `session.json`, and a third copy is what this feature is avoiding.

Expected from `tests/golden`: **byte-identical**. The `## Tokens` section renders only when `session.usage is not None`, so every feature 001, 002 and 003 golden report for a session without usage is unchanged. A golden diff here is a defect in this feature, not a baseline to refresh.

Expected from `--write`, which regenerates the static baseline rather than transcribing it:

| What | Measured on this tree |
|---|---|
| Tools sent every request, no bridge | **32** |
| OpenAI `tools` array, compact JSON | **34,065 bytes** |
| Gemini function declarations, compact | **34,248 bytes** |
| With the three bridge tools (`--bridge`) | 35 tools, **37,709 bytes** |
| Tool descriptions alone | 14,685 bytes |
| Every description emptied (the structural floor) | **15,274 bytes**, 45 percent of the payload |
| Longest descriptions | `check_rms_assembly` 1,455, `check_rms_part` 1,296, `check_fastener_joint` 871, `check_interference_group` 870 |
| Largest whole tool objects | `check_axial_stack` 2,734, `check_fit` 2,413, `record_drawing_finding` 2,156 |
| `prompts/system_v1.md` | 4,981 bytes |
| Rendered checklist | 3,061 bytes |
| Tool schema sha256 | identical under `PYTHONHASHSEED` 0, 1 and 12345 |

`docs/llm-efficiency-options.md` records 29 tools and 32,435 bytes and a different set of longest descriptions. That row is **wrong** because the RMS tools landed after it was written, and T002 corrects it in the same change. Byte counts are not token counts; at the roughly 4 bytes per token the baseline itself implies, 34,065 bytes is roughly 8,500 tokens per request (UNVERIFIED as a token count) and a review with 60 tool calls spends roughly 510,000 input tokens on tool schemas alone. Scenario 1b replaces that estimate with a real number.

### 1b The probes and the baseline runs, with keys

```powershell
uv run pytest tests/live -m live
```

Expected: every probe answers or **skips**. A 401, 429 or 5xx is reported as a skip, not a failure, following the pattern `tests/live/test_openai_live_schemas.py` already sets. Record every answer in `specs/005-llm-efficiency/probe-log.md` with the date, the model id and the commit sha:

| Probe | What it settles | What must be recorded |
|---|---|---|
| L1 | OpenAI sub-count containment | `total == input + output`, `cached <= input`, `reasoning <= output` |
| L2 | Whether our prefix already hits the implicit cache | `cached_tokens` on the second identical request; **this decides whether lever 3 on OpenAI has anything left to win** |
| L3 | What a tool-list change costs | `cache_miss` with reason `tools_changed`, and `cache_missed_tokens`; **this prices lever 4 before lever 4 is written** |
| L3b | Whether `prompt_cache_options` is accepted on `gpt-5.6` | acceptance, or the 400, which puts the diagnostics half of lever 3 off the table on our seat |
| G1 | Whether `caches.create` takes our prompt plus 32 tool declarations | the returned `name` and `usage_metadata.total_token_count` |
| G2 | Whether `cached_content` alongside `system_instruction` or `tools` is rejected | the status and the message; confirms the two-shape config is mandatory, not tidy |
| G3 | Whether Gemini streaming populates usage, cumulative or delta | every chunk's usage; the last `total_token_count` against the first |
| G4 | Implicit caching on `gemini-3.5-flash` | `cached_content_token_count` on the second identical call; **a non-zero value is the argument for not writing the explicit-cache lifecycle at all** |
| G5 | Whether the explicit cache is used when referenced | `cached_content_token_count > 0` and `prompt_token_count >= cached_content_token_count` |

Then the baseline itself. **There is no baseline row for any provider today and no agent review has ever been run on any package**, so this is the first measurement of the feature:

```powershell
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\baseline-openai-$rep" `
    --provider openai --model gpt-5.6 --effort high `
    --study none --arm baseline --rep $rep
  uv run swreview benchmark score "$runs\baseline-openai-$rep" --answer-keys $keys
}
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\baseline-gemini-$rep" `
    --provider gemini --model gemini-3.5-flash --effort high `
    --study none --arm baseline --rep $rep
  uv run swreview benchmark score "$runs\baseline-gemini-$rep" --answer-keys $keys
}
```

Expected: `scorecard.md` now carries three new columns, total tokens, cached share and round trips, and `scorecard.json` carries the detail. `report.md` carries a `## Tokens` section naming each provider's own fields, because OpenAI's `reasoning_tokens` is a **subset of** `output_tokens` while Gemini's `thoughts_token_count` is a **separate addend** of the total, so one shared "output tokens" column would compare two different quantities. Gemini's `tool_result_input_tokens` is non-null and OpenAI's is null, because on OpenAI that cost sits inside `input_tokens`. Any token field the provider did not report reads as **unknown**, never as 0.

Note in the record which wall clock is being quoted: `run_benchmark` times each package with `time.perf_counter()` and writes it into `Timing.unattended_runtime_minutes`, **overwriting** the number `finalize_session` computed from `started_at` to `ended_at`. Two writers of one field; the benchmark's wins because it runs last and it includes package load and adapter construction.

**Expected ledger rows** after Scenario 2 renders these runs, one per run folder per package:

| run | commit | lever | arm | rep | provider | model | effort | package | total | rounds | tool calls | cached share | wall clock s | s to 1st finding | valid | missed | false alarms | unresolved |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline-openai-1 | `<sha>` | none | baseline | 1 | openai | gpt-5.6 | high | cover-blind-tap | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` |
| baseline-gemini-1 | `<sha>` | none | baseline | 1 | gemini | gemini-3.5-flash | high | cover-blind-tap | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` |

**`recall` will read `null` on this run and that is the point.** `benchmarks/sets/pilot.json` holds one package with `held_out: false` and two known defects, so `recall` never computes and one lost defect is a 50 percent swing. Scenario 1c fixes it, and until it does, no gate in Scenarios 3, 4 or 5 means anything.

### 1c The benchmark set, on the workstation

```powershell
swreview-extract dump --out ..\benchmarks\packages\rms-part\native --profile full
uv run swreview validate ../benchmarks/packages/rms-part/native
uv run swreview check rms --package ../benchmarks/packages/rms-part/native --scope part
```

Expected: the 20 seeded defects of `benchmarks/answer_keys/rms-part.json` are found across 20 distinct `rms.*` rules, and the 18 correct conditions pass. Then add `rms-part` and **at least one held-out package** to `benchmarks/sets/pilot.json` and re-run Scenario 1b's baseline. Expected on the re-run: `recall` computes instead of reading `null`.

### 1d The two standalone fixes

```powershell
uv run pytest tests/unit/test_measure.py -k envelope
dotnet test ..\extractor\SwReview.Extractor.Tests -f net48 --filter PackageWriterTests
```

Expected: `check_tool_envelope` with zero bodies returns **`unresolved` with a reason**, never `status: "checked", bodies_swept: 0, hits: []`, which is reachable today with `--meshes none --profile full` and reads to a model as a tool-access check that ran and found nothing in the way. And `extractor.phases` now carries `{name, elapsed_ms, status}` per phase, which is the only metric levers 9 and 10 have.

---

## Scenario 2 (Phase 2): the ledger renders

```powershell
uv run swreview benchmark compare `
  "$runs\baseline-openai-1" "$runs\baseline-openai-2" "$runs\baseline-openai-3" `
  "$runs\baseline-gemini-1" "$runs\baseline-gemini-2" "$runs\baseline-gemini-3" `
  --out "$runs\ledger" --json
uv run swreview benchmark compare --check --out "$runs\ledger" ..\docs\llm-efficiency-options.md
```

Expected: `ledger.json` (holding the `runs` and `levers` arrays) and `ledger.md` (holding the per-run table and the per-lever decision table), plus a **baseline decision row** with lever `none` and arm `baseline`, one per provider and model. Every column has exactly one source: `input` through `total` and `rounds` come from `session.json` `usage.totals` and `usage.rounds`; `uncached in` and `cached share` are derived in the scorecard only; `wall clock s` is `PackageScore.wall_clock_s`; `s to 1st finding` comes from `events.jsonl`; `valid` through `unresolved` is the existing `PackageScore`; `lever`, `arm`, `rep` and `commit` come from the run's **provenance record** (written from `--study`, `--arm`, `--rep` and the commit sha), cross-checked against `session.efficiency`, which supplies the settings only; a run directory with no provenance record renders those four as null. A null in any contributing round renders as an explicit unknown marker, **never as 0 and never as a blank cell**.

Expected from `--check`: the table committed in `docs/llm-efficiency-options.md` regenerates byte-identically from the recorded run directories. The ledger is a rendering of N `scorecard.json` files, not a hand-kept artifact; typed numbers go stale and cannot be audited.

Expected refusals: `compare` refuses a run whose `session.efficiency` disagrees with that run's provenance record, naming the field, which is the RK-20 guard and the point of the command; it refuses a run whose `session.json` carries no `efficiency` at all, with the message that the run predates the flag carrier; and it refuses to place two runs in one comparison when the commit, model, effort, set file or checklist differ, saying which field differed, with **no declared exception** - lever 2 included, whose off arm is its flag off rather than an earlier commit. It refuses a run whose provenance `arm` is `on` while `session.efficiency` has the studied lever false, and the mirror case for `off`, naming the lever; a baseline run (`lever: "none"`, `arm: "baseline"`, every flag false) is exempt from that clause. And it **refuses to render a decision row** for a study whose scorecards produce no recall number - today's single-package set - or any of whose runs carry `set_too_small_override: true`, naming which condition fired and exiting non-zero, while **still rendering the raw per-run rows** (FR-029, SC-011); that study appears in `ledger.json`'s `levers` array with `decision: null` and the reason in `decision_reason`, which is the one place `decision` may be absent. A run directory with no provenance record at all is **not** a refusal: it renders with those columns null, because a run made before the convention existed is still a real run.

Expected on the Decision column: it is **computed** from the scorecards by the FR-028 rule and is one of `adopt`, `keep off`, `re-measure` (FR-027, SC-009). The owner's approval is a **separate** field beside it, `owner_signed_off` with a date, written by hand into the committed `ledger.md`; `compare` never writes it, and no flag default changes until it is signed. The cached-share column renders as **unknown** until probe L1 has been recorded (FR-047).

**Confirm the regenerated baseline equals the numbers recorded at Checkpoint 1.** A mismatch means one of the two readings is wrong, and it is worth finding now rather than after six paid runs.

```powershell
uv run pytest tests/unit/test_run_provenance.py tests/unit/test_benchmark_compare.py `
  tests/unit/test_adoption_rule.py
```

Expected from the adoption rule, which is fixed **before** the first A/B and not argued after a result is in hand: "no known defect lost" is **worst case**, so the lever is rejected if any on-run misses a defect any off-run found; "no new false alarm" is **median with the worst case recorded**, asymmetric on purpose; "worth the code" is a **median 20 percent** reduction in total tokens or in wall clock against the off arm's median over the whole set; and three off-runs that disagree with each other about defects found produce **`re-measure`** with `CONTROL UNSTABLE` as the printed reason beside it, never a pass, because a gate whose control arm is unstable cannot decide anything. `Decision` is a closed enum of exactly three, `adopt`, `keep off`, `re-measure`; the control-arm signal is the reason string, not a fourth value.

---

## Scenario 3 (Phase 3): the Tier 1 levers

Order matters. Lever 3's diagnostics are the instrument that prices levers 2 and 4, so it goes first.

### 3a Lever 3, OpenAI half

```powershell
uv run pytest tests/unit/test_prefix_stability.py tests/unit/test_openai_prompt_cache.py

foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever03-off-$rep" `
    --provider openai --model gpt-5.6 --effort high `
    --study prompt_cache_key --arm off --rep $rep
  uv run swreview benchmark score "$runs\lever03-off-$rep" --answer-keys $keys
  uv run swreview benchmark run --set $set --out "$runs\lever03-on-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever prompt_cache_key `
    --study prompt_cache_key --arm on --rep $rep
  uv run swreview benchmark score "$runs\lever03-on-$rep" --answer-keys $keys
}
uv run swreview benchmark compare "$runs\lever03-*" --out "$runs\ledger"
```

Expected from the tests: the system prompt and the encoded tool array are byte-identical at every round of a session, which is **the real deliverable of this half**; the request carries `prompt_cache_key = str(session.session_id)`, which survives a process restart, where a process-local random value would look identical while silently dropping every hit after the pane restarts the backend on a settings save; `prompt_cache_diagnostics` lands on the `usage` event as `cache_diagnostic` with the miss reason and `cache_missed_tokens` verbatim, and an absent diagnostic records as `None`, never as a hit.

**Expected decision row**:

| Lever | Provider and model | Commit | Reps | Other levers on | Cached input off -> on | Total tokens off -> on (median, min, max) | Round trips off -> on | Valid / missed / false alarms / unresolved off -> on | Worst-case defects lost | Lever-specific counter | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 (OpenAI) | openai / gpt-5.6 | `<sha>` | 3 | none | `<n>` -> `<n>` | `<n>` -> `<n>` | `<n>` -> `<n>` | `<n>` -> `<n>` | `<n>` | miss reasons and `cache_missed_tokens` | `<adopt / keep off / re-measure>` |

If probe L2 showed we were already hitting the implicit cache at a healthy rate, **say so in the row**: the saving is small because we already had it, and what this lever bought is the ability to see it. That is **not** a second route to `adopt`. `Decision` is computed by the FR-028 rule from the scorecards, and L2's answer lives in the hand-written `probe-log.md`, so when both reductions are under 20 percent the row computes **`keep off`** and the observability case is carried in **`decision_reason`** beside it and signed in **`owner_signed_off`** (FR-024, FR-027, SC-009).

### 3b Lever 2

```powershell
uv run pytest tests/unit/test_docstring_split.py tests/unit/test_tool_notes_prompt.py `
  tests/unit/test_tool_payload.py
uv run python -m tests.unit.test_tool_payload --write   # on both commits
```

Expected deterministically, with no API call and inside CI, at the **enforced** 160/90 cap - the same cap the build test asserts over all 35 docstrings, so the quoted saving and the enforced cap are one number:

| Cap (tool / parameter description) | Bytes | Saved |
|---|---|---|
| none (today) | 34,065 | 0 |
| 300 / 120 | 27,158 | 20 percent |
| 200 / 100 | 25,020 | 27 percent |
| **160 / 90** | **23,834** | **30 percent** |
| 120 / 70 | 22,450 | 34 percent |
| everything stripped (floor) | 15,274 | 55 percent |

So roughly 2,550 tokens per request and roughly 153,000 over a 60-call review, which is **below** the input document's "a third to a half" at the upper end. Also expected: the rejoin `description + "\n\n" + dedented notes` is **byte-equal** to the old full docstring body, against text pinned in the test file; the encoded tool array in both provider encodings, built at this commit with every flag off, is **byte-equal to the pinned pre-split encoding** (SC-007); the MCP toolset honours the flag too, since `mcp/server.py` builds its own list and has no system prompt; the `## Tool notes` block contains every tool's notes exactly once with the flag on and none with it off; and the flag is applied **after** `spec_for`, because `_SPECS` is process-global and keyed by function, so a flag read inside `spec_for` would make two runs in one process silently share the first run's setting.

Then the benchmark A/B, **with lever 3 off** and at **one commit for both arms**. The cap is enforced by docstrings split at a paragraph boundary rather than by run-time truncation, but the off arm is still reachable by flipping the flag: with `trim_tool_descriptions` off the adapter and the MCP toolset are handed the **rejoined** description, byte-equal to the pre-split text (FR-033, FR-039), which is what SC-007 asserts at the wire level:

```powershell
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever02-off-$rep" `
    --provider openai --model gpt-5.6 --effort high `
    --study trim_tool_descriptions --arm off --rep $rep
  uv run swreview benchmark score "$runs\lever02-off-$rep" --answer-keys $keys
}
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever02-on-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever trim_tool_descriptions `
    --study trim_tool_descriptions --arm on --rep $rep
  uv run swreview benchmark score "$runs\lever02-on-$rep" --answer-keys $keys
}
```

**Expected decision row**: `commit_off` equal to `commit_on`, because both arms run from the post-split commit; the deterministic byte and tool-count deltas for both encodings, the median token and wall-clock deltas, and the **tool-name histogram diff** as the lever-specific counter. The thing that actually needs watching is which tool the model picks, not the token count, which is arithmetic; a trim that changed the answer usually shows first as a call-pattern change the scorecard would not catch. The gate is the general rule plus: **no check tool may drop out of the model's repertoire.**

### 3c Lever 4

```powershell
uv run pytest tests/unit/test_tool_tiers.py
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever04-off-$rep" `
    --provider openai --model gpt-5.6 --effort high `
    --study tool_tiers --arm off --rep $rep
  uv run swreview benchmark run --set $set --out "$runs\lever04-on-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever tool_tiers `
    --study tool_tiers --arm on --rep $rep
}
```

Expected from the withheld path, which is the assertion that fails today: a withheld tool is **absent from the iterated `ToolSet`** but still resolved by `by_name`, so a model that asks for it gets a `tool.started` and `tool.finished` pair, a result naming the tier rule, an **`unresolved`** coverage item whose `check` is `modeling.resilience` with a reason naming the missing feature rows, and **`session.coverage.failed` empty**. A hallucinated tool name still goes to `failed`. Today a withheld tool would be written as `failed`, which says the tool broke when we declined to offer it, and `failed` is excluded from the checklist's closing buckets, so the engineer reading the report never learns we withheld it.

**Expected decision row, reported as two rows and not averaged**:

| Package class | Tools off -> on | Bytes off -> on | Saved |
|---|---|---|---|
| `model_check` (no feature rows) | 32 -> 26 | 34,065 -> 25,972 | **23.8 percent** |
| full assembly | 32 -> 32 | 34,065 -> 34,065 | **0 percent** |

Lever 4 does nothing for the main case and a lot for the Model check tab's case, and the ledger must say so rather than average it away. The quality metric is unresolved read as **two numbers**, unresolved-because-withheld and unresolved-for-any-other-reason; the first rising and the second flat is the lever behaving as designed. The gate additionally requires the OpenAI cache diagnostics to show **no mid-session `tools_changed`**, which the package-decidable scope guarantees by construction.

### 3d Lever 3, Gemini half

**Read probe G4 before writing any code.** If a plain instrumented Gemini run already shows a healthy `cached_content_token_count`, close the lever here with a ledger row reading "not written; implicit caching already delivering `<n>` percent" and run nothing further. The entire explicit lifecycle, create, branch the config, extend, delete, handle a leaked cache, handle the 400, buys little against a cache we already get.

If it is written:

```powershell
uv run pytest tests/unit/test_gemini_cached_config.py
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever03g-off-$rep" `
    --provider gemini --model gemini-3.5-flash --effort high `
    --study gemini_explicit_cache --arm off --rep $rep
  uv run swreview benchmark run --set $set --out "$runs\lever03g-on-$rep" `
    --provider gemini --model gemini-3.5-flash --effort high --lever gemini_explicit_cache `
    --study gemini_explicit_cache --arm on --rep $rep
}
```

Expected: a cached run sends `cached_content` and **no** `system_instruction` and **no** `tools`, an uncached run sends the reverse, both send `automatic_function_calling`, `thinking_config` and `max_output_tokens`, and `AUTOMATIC_FUNCTION_CALLING_DISABLED` stays on the cached path because our loop runs every tool call. **A wrong branch does not degrade, it 400s the whole review**, and the SDK enforces nothing here. The cache is deleted on `ReviewRun.close()` and the TTL is bounded at 1800s, so a crashed process leaks one entry that expires by itself.

---

## Scenario 4 (Phase 4): the Tier 2 levers

**Levers 5 and 7 are never run in the same arm** until each has been gated alone: lever 5 closes checklist items before the first turn, and with 7 also on, a package whose deterministic checks close every item stops the turn almost immediately, before the model looks at fit, stack or drawings.

### 4a Lever 6, round-trip batching, OpenAI only

```powershell
uv run pytest tests/unit/test_parallel_tool_calls.py
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever06-off-$rep" `
    --provider openai --model gpt-5.6 --effort high `
    --study parallel_tool_calls --arm off --rep $rep
  uv run swreview benchmark run --set $set --out "$runs\lever06-on-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever parallel_tool_calls `
    --study parallel_tool_calls --arm on --rep $rep
}
```

Expected: three calls in one response produce three `tool.started` and `tool.finished` pairs, three `function_call_output` items and three steps with indices 0, 1, 2, **executed serially in request order**; three calls with `max_steps=2` run two and give the third `BUDGET_EXHAUSTED` so the echoed history stays valid; two runs of the same fake script produce byte-identical `events.jsonl` apart from timestamps.

**Expected decision row**: round trips off and on as the primary number, wall clock and input tokens secondary, and the **Gemini row reading "on by default, not measurable as A/B"**. Gemini already makes parallel tool calls in production, there is no disable-parallel switch in `GenerateContentConfig`, and dropping all but the first call of a round would measure something we would never ship. That is a true statement and more useful than a fabricated comparison.

The gate additionally watches for **speculative batching**: a model asked to batch may call checks it would otherwise have skipped after reading an earlier result, which shows as **step count up while round trips are down** and can raise false alarms. Both numbers go in the row.

### 4b Lever 5, pre-run deterministic checks

```powershell
uv run pytest tests/unit/test_prerun_same_session.py tests/unit/test_prerun_digest.py
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever05-off-$rep" `
    --provider openai --model gpt-5.6 --effort high `
    --study prerun_checks --arm off --rep $rep
  uv run swreview benchmark run --set $set --out "$runs\lever05-on-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever prerun_checks `
    --study prerun_checks --arm on --rep $rep
}
```

Expected from the tests: **the pre-run produces the same session a model-driven run does**, compared on the runner's own `_verdict_key`, because the pre-run calls the same tool functions through the same `ToolDispatch` rather than a second copy of the check logic, so it writes real steps, real findings, real coverage and real events, and `Finding.tool_result_ids` still points at a real step. The digest's counts equal the session's counts, and every "NOT evaluated" line has a matching `skipped` coverage item, because the block is generated from the coverage machinery and not written as prose: one source, two renderings.

Expected digest shape in the first user message, **not** in the system prompt, because the system prompt is the cacheable prefix:

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

**Expected decision row**: round trips, input tokens and **wall clock to first finding**, which should drop dramatically and is the number an engineer feels, with the lever-specific counter being the **`check_fit` and `check_axial_stack` call counts off and on**. Those two are never pre-run, so if they fall, the digest is suppressing exploration and the lever fails the gate regardless of what the token number says.

### 4c Lever 7, coverage-driven stop

```powershell
uv run pytest tests/unit/test_stop_predicate.py tests/integration/test_coverage_stop.py `
  tests/unit/test_coverage_bucket_mix.py
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$runs\lever07-off-$rep" `
    --provider openai --model gpt-5.6 --effort high `
    --study coverage_stop --arm off --rep $rep
  uv run swreview benchmark run --set $set --out "$runs\lever07-on-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever coverage_stop `
    --study coverage_stop --arm on --rep $rep
}
```

Expected: the stop fires only when every checklist item is closed **by a finding or by `checked`**, so an item closed only by `skipped` does not fire it. The two predicates deliberately differ from `bucket_of`, which counts `skipped` and `out_of_scope` as closers, because for finalizing an item closed any way is closed and for stopping early it is not: a review that skipped six of nine items has not finished, it has given up. **Resumption survives the stop**: after it fires, `answer_evidence` and `continue_session` still run on the recorded OpenAI client, which is the assertion that distinguishes withdrawing the tools from raising out of `ToolSet.call`. Raising would leave a `function_call` with no matching `function_call_output` and the next request would be rejected.

**Expected decision row**: tokens and steps, the **coverage bucket mix** off and on, and the **fire rate** as the lever-specific counter. A lever that fires on one package in five is not the same lever as one that fires on five in five, and the token average hides that. The gate requires the `skipped` and `out_of_scope` counts **not to rise**, because lever 7 turns `mark_coverage` into a turn-ending call and a model that wants to finish can close the checklist with nine `skipped` calls and produce a short, cheap run that looks efficient in this very table.

Note, so the measured saving is not read as a bug: with lever 6 on, the round that closes the last checklist item may also contain three more calls, and the stop withdraws the tools for the *next* round, so those three still run. Correct and intended.

---

## Scenario 5 (Phase 5): the Tier 3 levers, on the workstation

`swreview benchmark run` **cannot see levers 9 and 10 at all**, because it iterates pre-built package directories and no dump happens, so every arm here is timed by hand against a real document. Run each lever's probes first: a probe can close a lever before its implementation is written.

### 5a Lever 9, package reuse

```powershell
swreview-extract dump --out $runs\reuse\cold-1 --profile full --meshes glb --faces needed
swreview-extract dump --out $runs\reuse\cold-2 --profile full --meshes glb --faces needed
swreview-extract dump --out $runs\reuse\warm   --profile full --meshes glb --faces needed --reuse
uv run pytest tests/unit/test_reuse_key.py tests/unit/test_reuse_refusals.py `
  tests/unit/test_package_index.py
```

Expected from P3, the two cold dumps of an unchanged document: a field-by-field diff naming exactly what is legitimately non-deterministic, which defines the modulo set for the gate. Expected from P5: `file_modified_utc` moves on an ordinary save and does **not** move on open-and-close without save.

**The gate is a pass/fail precondition, not a trade**: the reused package must be **byte-identical to a fresh dump modulo `package_id`, `created_at`, `reuse_key` and the new reuse fields**. If the reused package is not the package a fresh dump would write, the lever is wrong regardless of what the model then says.

Expected refusals, each of which must be observed rather than assumed: a document with unsaved changes; a component that was suppressed or lightweight at dump time and is resolved now; a dump that continued past a failed phase; a `model_check` package handed to a request for `full`; and any of the four dump options differing. Expected statements, because reuse is never silent: `reused_from` and `reused_at` on the package, "Reusing the extraction from `<folder>` (`<age>`)" in the pane status line instead of "Extracting evidence from ...", and the fact in the report header and in `session.json`.

**Expected decision row**: `dump wall clock off -> on` with the per-phase breakdown from `extractor.phases`, the byte-identity result as pass or fail, and P4's copy-against-pointer decision recorded with its numbers.

### 5b Lever 10a, lazy meshes

```powershell
swreview-extract dump --out $runs\lazy\eager --profile full --meshes glb --faces needed
swreview-extract dump --out $runs\lazy\lazy  --profile full --meshes none --faces needed
uv run swreview review $runs\lazy\eager --out $runs\lazy\eager-review --bridge `
  --provider openai --model gpt-5.6 --effort high
uv run swreview review $runs\lazy\lazy --out $runs\lazy\lazy-review --bridge `
  --provider openai --model gpt-5.6 --effort high --lever lazy_meshes
```

Expected from P1, this lever's entire premise: the per-phase dump timing on the pilot assembly, and whether the mesh phase dominates. **If it does not, close the lever here with the recorded numbers.** Expected from P2: how long one `tessellate` of the largest part blocks the STA worker, which decides whether a lazy fetch is usable interactively at all, since one STA worker answers in arrival order and a tessellation blocks every other bridge call behind it.

Expected from the review: `PROTOCOL.md` reports 1.1 on `ping`; a body that cannot be fetched is **named in `unresolved`**; reaching `extraction.lazy_fetch_body_limit` is unresolved coverage, not a stop; and off the workstation, with no bridge, the answer is `unresolved` with a reason rather than silence, which is only true because the zero-bodies guard landed in Scenario 1d.

**The gate**: the scorecard **plus** `check_tool_envelope` returning the same hits and the same `bodies_swept` in both arms, or `unresolved` naming what it could not fetch. `eager` stays the default whatever the numbers say, because a lazily extracted package reviewed off the workstation is a package with less evidence, and the flag that reduces evidence is the one that is opted into.

### 5c Lever 11a, carry over the RMS verdicts

```powershell
uv run swreview review $runs\carry\dump-1 --out $runs\carry\review-1 `
  --provider openai --model gpt-5.6 --effort high
# edit one feature of one part in SOLIDWORKS, save, then re-dump
swreview-extract dump --out $runs\carry\dump-2 --profile full
uv run swreview review $runs\carry\dump-2 --out $runs\carry\review-2-off `
  --provider openai --model gpt-5.6 --effort high
uv run swreview review $runs\carry\dump-2 --out $runs\carry\review-2-on `
  --provider openai --model gpt-5.6 --effort high --lever carry_over_rms
uv run pytest tests/unit/test_carry_over_key.py tests/unit/test_carry_over_guards.py
```

Expected from P8: the per-document feature-tree fingerprint moves for the edited part and for no other. **The pass/fail precondition**: every finding touching the edited part was **re-run and not carried**. Expected from the guards: only `demonstrated` and `checked_within_scope` are carried, every `suspected` and `unresolved` is re-run because that is where the model's judgement sits, a finding with a disposition is never carried, and the carry is capped in age or in runs, because a finding carried for twenty consecutive runs has not been computed for twenty runs.

Expected in the artifacts, because a carry-over can never be silent: `carried_over_from`, `carried_over_at` and `carry_over_key` on the finding with **`Finding.status` untouched**, since a carried `demonstrated` finding is still demonstrated and what changed is who demonstrated it and when; a `checked` coverage item whose reason starts "carried over from "; and a report heading naming the originating run with the carried count against the re-run count.

**Expected decision row**: tokens and tool calls on the **second** review off and on, with the **carried count per arm** as the lever-specific counter, so a reader can see whether the quality came from computation or from memory. A lever that "improves" recall by remembering is not an improvement, and the row must make that visible rather than hide it inside a recall number.

---

## Regression gate

Run before any phase is called done.

```powershell
uv run pytest
uv run pytest tests/golden
dotnet test ..\extractor\SwReview.Extractor.Tests -f net48
uv run swreview benchmark compare --check --out "$runs\ledger" ..\docs\llm-efficiency-options.md
```

Expected: feature 001, 002 and 003 goldens byte-identical, with the single authorized exception that a session **carrying** usage renders a `## Tokens` section; `test_schema_sync` green on the bumped schema; `test_tool_payload` green against the pinned counts and byte ceilings; every `EfficiencySettings` field still defaulting to `False`, because **no lever is adopted by default in this feature and every default change is a separate, recorded decision**; every lever that failed its gate still off with its numbers still in the ledger; and the committed table in `docs/llm-efficiency-options.md` still regenerable from the run directories it claims to summarize.
