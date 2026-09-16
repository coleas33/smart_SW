# Feature 005 probe log

Every probe below settles one **UNVERIFIED** claim from `research.md` R24. A claim stays
UNVERIFIED until this file records that probe's raw output; no task may call it VERIFIED on
anything else (tasks.md, "What VERIFIED and UNVERIFIED mean"), and no adoption decision may
rest on a number that is in neither this file nor a scorecard (FR-024, SC-009).

**Every probe in this file is `pending`.** Nothing below has been run, so nothing below
carries a number, and none of the claims quoted here has moved.

## How a section is filled in

When a probe runs, replace its **Status** line and append the record under it:

- `answered` - the raw output, verbatim, not a summary of it;
- `skipped` - the reason, which for a live probe is normally "no API key on this machine",
  or a 401, 429 or 5xx, which section 1g of tasks.md records as a skip and not a failure.
  A skipped probe is recorded as skipped, **never left absent**;
- the **date**, the **model id** (live probes) or the **seat and SOLIDWORKS build**
  (workstation probes), and the **commit sha** the probe ran at.

The commit sha this file was created at is `baa74248f32292746fef357a48a85ea6114efd55`. That
is the sha of the empty log, not of any answer: each section records its own.

Live probes run from `reviewer/` and are skipped without a key:

```powershell
uv run pytest tests/live -m live
```

Workstation probes (`[W]`) run on the SOLIDWORKS seat and are recorded by hand.

---

## The measured tool-payload baseline (T001), and what still disagrees with it

**Not a probe**: this section needs no key and no seat. It is here because it is the one
measured number this feature already has, and because measuring it found the spec package
quoting a figure the tree does not produce. **Owner decision needed** (see the last
paragraph); nothing in the spec package has been edited to match.

Regenerated 2026-09-16 at commit `baa74248f32292746fef357a48a85ea6114efd55`, from
`reviewer/`, by the helper T001 requires so the numbers are never transcribed:

```powershell
uv run python -m tests.unit.test_tool_payload --write
```

| Toolset | Encoding | Tools | Bytes |
|---|---|---:|---:|
| review | openai | 32 | 34,065 |
| review | gemini | 32 | **34,217** |
| review+bridge | openai | 35 | **37,712** |
| review+bridge | gemini | 35 | **37,682** |
| mcp (the Ask tab) | openai | 20 | 14,866 |
| mcp (the Ask tab) | gemini | 20 | 14,084 |

Withholding the six RMS tools: 26 tools, 25,972 bytes kept, 8,093 bytes and 23.8 percent
saved (openai). Structural floor with every description emptied: 15,274 bytes, 45 percent
of 34,065.

**The deviation.** T001's own text asks for the Gemini total to be pinned at **34,248**.
This tree produces **34,217**, so the constant in
`reviewer/tests/unit/test_tool_payload.py` is 34,217 and `docs/llm-efficiency-options.md`
(T002) quotes 34,217 and 37,712 / 37,682. Regenerating was the point of T001 - "transcribing
it by hand is what let two figures diverge across the package" - but the figure T001 quotes
was stale, and the divergence is now the other way round: the test and the doc agree with
the tree, and the spec package does not.

**Still quoting the stale figures**, each of which is one of the files this task may not
edit. Every one needs correcting in the change that is allowed to touch it:

| File and line | Quotes | Measured |
|---|---|---|
| `spec.md:62` | 34,248 Gemini, 37,709 bridge | 34,217, 37,712 |
| `plan.md:362` | 34,248 Gemini, 37,709 bridge | 34,217, 37,712 |
| `quickstart.md:59-60` | 34,248 Gemini, 37,709 bridge | 34,217, 37,712 |
| `research.md:119-120` | 34,248 and 37,709 as the brief's figures, "measured today 37,712 and **33,897**" | 34,217, 37,712 - the 33,897 is a third Gemini figure and matches nothing this tree produces |
| `contracts/levers.md:258` | 34,248 Gemini | 34,217 |
| `contracts/tool-tiers.md:42-43` | 34,248 Gemini, 37,709 bridge | 34,217, 37,712 |
| `tasks.md:61, 193` | 34,248 Gemini | 34,217 |

Byte counts are not token counts, and the first instrumented run replaces every
byte-to-token estimate that rests on them (R24 T1, still pending below).

---

## L1 - OpenAI sub-count containment

> OpenAI sub-count containment (`cached <= input`, `reasoning <= output`,
> `total == input + output`)

Why it matters: the cached-input-share column is well defined only if cached input is
contained in input. Until L1 answers, that column renders **unknown**, not a number (T023,
FR-047).

Settled by (T025):

```powershell
uv run pytest tests/live/test_openai_usage_live.py -m live -k l1
```

Record: `total_tokens`, `input_tokens`, `output_tokens`, `cached_tokens` and
`reasoning_tokens` from one tiny request.

**Status: pending.**

---

## L2 - does our prefix actually hit the implicit cache

> Our prefix actually hits the implicit cache

Why it matters: this decides whether lever 3 on OpenAI has anything left to win. Its answer
lives here and **not** in any scorecard, so it can never be a second route to `adopt`; it is
carried in `decision_reason` beside the computed column (T051, FR-027).

Settled by (T026):

```powershell
uv run pytest tests/live/test_openai_usage_live.py -m live -k l2
```

Record: `cached_tokens` on the second of two identical requests in one process, same
`prompt_cache_key`, the full 32-tool list and the real system prompt.

**Status: pending.**

---

## L3 - what a tool-list change costs

> A tool-list change is a `tools_changed` miss, and what it costs

Why it matters: this prices lever 4 before lever 4 is written.

Settled by (T027):

```powershell
uv run pytest tests/live/test_openai_usage_live.py -m live -k l3
```

Record: the `prompt_cache_diagnostics` member and, on a miss, its `reason` and
`cache_missed_tokens`.

**Status: pending.**

---

## L3b - is `prompt_cache_options` accepted on our default model

> `prompt_cache_options` is accepted on `gpt-5.6`

Why it matters: a 400 puts the diagnostics half of lever 3 off the table on our seat, and
T049 then ships the `prompt_cache_key` half alone and records that fact here. A 400 is a
recorded answer, not a failure.

Settled by (T027, falls out of L3):

```powershell
uv run pytest tests/live/test_openai_usage_live.py -m live -k l3b
```

Record: acceptance, or the full 400 body.

**Status: pending.**

---

## L5 - does toggling `parallel_tool_calls` break the prefix

> `parallel_tool_calls` toggling does not break the prefix

Why it matters: needed only once lever 6 is taken up (T070), and listed here so it is not
rediscovered.

Settled by (T070, folded into lever 6):

```powershell
uv run pytest tests/live -m live -k l5
```

Record: the `prompt_cache_diagnostics` member on the request that follows the toggle, and
its `reason` if it missed.

**Status: pending.**

---

## G1 - does `caches.create` accept our prefix

> `caches.create` accepts our system prompt plus 32 tool declarations, and we are over the
> unstated minimum

Why it matters: the returned token count is the denominator for "what fraction of the prefix
did we actually cache", and the minimum is unstated, so only a live create answers it.

Settled by (T028):

```powershell
uv run pytest tests/live/test_gemini_usage_live.py -m live -k g1
```

Record: the returned `name` and `usage_metadata.total_token_count`; then delete the cache.

**Status: pending.**

---

## G2 - is `cached_content` alongside `system_instruction` or `tools` rejected

> Setting `cached_content` alongside `system_instruction` or `tools` is rejected, and what
> the rejection says

Why it matters: the SDK validates nothing here (VERIFIED by grep over `google/genai/`), so
the two-shape config of lever 3 is mandatory rather than tidy only if the service refuses at
run time.

Settled by (T028):

```powershell
uv run pytest tests/live/test_gemini_usage_live.py -m live -k g2
```

Record: the status and the message, verbatim.

**Status: pending.**

---

## G3 - does Gemini streaming populate usage, cumulative or delta

> Gemini streaming populates `usage_metadata`, and the last chunk carries the totals

Why it matters: it settles cumulative against delta and confirms T009's
last-carrying-chunk-wins rule, which cannot be called VERIFIED without it.

Settled by (T029):

```powershell
uv run pytest tests/live/test_gemini_usage_live.py -m live -k g3
```

Record: every chunk's usage, and the last `total_token_count` against the first.

**Status: pending.**

---

## G4 - implicit caching on our default Gemini model

> Implicit caching on `gemini-3.5-flash`

Why it matters: a non-zero value is the argument for **not** writing the explicit-cache
lifecycle at all. G4 blocks T065 and therefore the whole Gemini half of lever 3.

Settled by (T030):

```powershell
uv run pytest tests/live/test_gemini_usage_live.py -m live -k g4
```

Record: `cached_content_token_count` on the second of two identical streamed calls with no
explicit cache.

**Status: pending.**

---

## G5 - is the explicit cache used when referenced

> The explicit cache is used when referenced

Settled by (T030, after G1):

```powershell
uv run pytest tests/live/test_gemini_usage_live.py -m live -k g5
```

Record: `cached_content_token_count` and `prompt_token_count` on a streamed call with
`cached_content=<name>`.

**Status: pending.**

---

## P1 [W] - does the mesh phase dominate the dump

> Does the mesh phase dominate the dump?

Why it matters: lever 10's entire premise. If the mesh phase does not dominate, the lever
closes here on the recorded numbers. Blocked on T033, which is the only thing that produces
dump phase timings at all.

Settled by (T095), on the seat, cold, on the pilot assembly:

```powershell
swreview-extract dump --out <run> --profile full --meshes glb --faces needed
```

Record: `extractor.phases` - every `{name, elapsed_ms, status}` row - and which phase
dominates.

**Status: pending.**

---

## P2 [W] - is a lazy fetch usable interactively

> Is a lazy fetch usable interactively?

Why it matters: one STA worker answers bridge calls in arrival order, so a tessellation
blocks every other bridge call behind it.

Settled by (T100): one `tessellate` of the largest part over the bridge.

Record: the bridge `elapsed_ms` for that call, and how long the STA worker was blocked.

**Status: pending.**

---

## P3 [W] - what is legitimately non-deterministic in a package

> What is legitimately non-deterministic in a package?

Why it matters: it **defines** "byte-identical modulo X" for lever 9's pass/fail gate
(T093). Without P3 there is no gate, only an opinion.

Settled by (T086): dump the same unchanged document twice and diff field by field.

Record: every field that moved, and the modulo set that follows from it.

**Status: pending.**

---

## P4 [W] - is reuse-by-copy cheap enough

> Is reuse-by-copy cheap enough?

Why it matters: if the copy dominates, lever 9 falls back to a `package-source.json` pointer
read by `load_package` instead of copying.

Settled by (T092): time the copy of `package.json` plus `meshes/` for the pilot assembly
against the dump time it replaced.

Record: both times, and the decision they force.

**Status: pending.**

---

## P5 [W] - does `file_modified_utc` behave

> Does `file_modified_utc` behave?

Why it matters: it is lever 9's key. `local_modified` is hardcoded null today
(`ManifestBuilder.cs:57,92-98`), so the field this probe tests is the one T089 adds.

Settled by (T086): save an ordinary edit and confirm it moves; open and close without saving
and confirm it does not.

Record: the value before and after each of the two operations.

**Status: pending.**

---

## P6 [K] - do both adapters actually receive a usage object on a streamed turn

> Do both adapters actually receive a usage object on a streamed turn?

Why it matters: this is also **the baseline row that does not exist**. No agent review has
ever been run on any package, so the first measurement of feature 005 is the baseline
itself, and no lever work starts until it exists and the owner has read it.

Settled by (T036), three repetitions per provider, each scored:

```powershell
uv run swreview benchmark run --set $set --out "$runs\baseline-openai-$rep" --provider openai --model gpt-5.6 --effort high --study none --arm baseline --rep $rep
uv run swreview benchmark score "$runs\baseline-openai-$rep" --answer-keys $keys
```

and the same with `--provider gemini --model gemini-3.5-flash`.

Record: every token field each adapter actually returned (unknown where the provider
reported nothing, never 0), the commit sha, provider, model, effort, `max_steps`, the
checklist, the start time, and **which wall clock is being quoted** - `run_benchmark`
overwrites `Timing.unattended_runtime_minutes` with its own `perf_counter` number.

**Status: pending.**

---

## P7 [W] - does the 20-defect answer key behave on a real RMS package

> Does the 20-defect answer key behave on a real RMS package?

Why it matters: `recall` is `None` while the set holds no held-out package, so the headline
quality metric does not compute and no Tier 2 or Tier 3 gate means anything. P7 blocks T035.

Settled by (T034), on the seat, from `benchmarks/native/rms-part/RECIPE.md`:

```powershell
swreview-extract dump --out ..\benchmarks\packages\rms-part\native --profile full
uv run swreview validate ../benchmarks/packages/rms-part/native
uv run swreview check rms --package ../benchmarks/packages/rms-part/native --scope part
```

Record: which of the 20 known defects were found, across which of the 20 distinct `rms.*`
rules, and whether the 18 correct conditions passed.

**Status: pending.**

---

## P8 [W] - does the feature-tree fingerprint move exactly when it should

> Does the feature-tree fingerprint move exactly when it should?

Why it matters: lever 11's premise. P8 blocks T104.

Settled by (T103): edit one feature of `RMS-A.SLDPRT`, re-dump, and diff the per-document
fingerprints.

Record: the fingerprints before and after, per document, and every one that moved.

**Status: pending.**

---

## Claims settled by other work, not by a probe of their own

R24 lists three UNVERIFIED claims with no probe of their own. They are recorded here so they
are not mistaken for VERIFIED, and each names the run that answers it.

| # | UNVERIFIED claim | Settled by | Status |
|---|---|---|---|
| T1 | The token counts behind the byte counts in R1 and R9.1; every byte-to-token conversion in `research.md` is an estimate until then | falls out of P6, the first instrumented run | pending |
| T2 | Whether a description trim changes which tool the model picks | the tool-name histogram over the lever 2 A/B | pending |
| T3 | Whether an OpenAI response really returns several `function_call` items at a useful rate | falls out of the lever 6 A/B (T073) | pending |
