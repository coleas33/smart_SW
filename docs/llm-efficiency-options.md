# LLM efficiency, speed, and token options

Written 2026-09-16 as the input to feature 005. Nothing here is implemented yet; every
option is a hypothesis to be measured before it is adopted. The rule for feature 005 is
**instrument first, then one lever at a time behind a flag, adopted only on evidence**.

## Baseline (measured on the tree at commit a0be95f plus the Phase 3 work in progress)

| What | Measured | Consequence |
|---|---|---|
| Tool schemas sent with every model request | 32 tools, **34,065 bytes** in the OpenAI encoding and 34,217 in the Gemini one (35 tools, 37,712 and 37,682 with the bridge); regenerated 2026-09-16 by `python -m tests.unit.test_tool_payload --write`, run from `reviewer/` | A review with 60 tool calls resends the whole array 60 times; the longest descriptions are `check_rms_assembly` (1,455 bytes), `check_rms_part` (1,296), `check_fastener_joint` (871) and `check_interference_group` (870), and the largest whole tool objects are `check_axial_stack` (2,734 bytes), `check_fit` (2,413) and `record_drawing_finding` (2,156); with every description emptied the array still weighs **15,274 bytes**, 45 percent of the payload and a floor no trimming can reach, so lever 2's ceiling is the other 55 percent |
| System prompt plus checklist | 5,057 plus 2,909 bytes, about 2,000 tokens, plus the package census | Resent every request, but stable, so cacheable |
| Step budget | `max_steps` 200 per turn, no coverage-driven stop | A turn ends on the budget or on the model's own decision, never because coverage is complete |
| Parallel tool calls | `parallel_tool_calls: False` in the OpenAI adapter | One round trip per query; each round trip resends the whole growing history |
| Usage accounting | None recorded by either adapter or in `session.json` | No token or cost number exists for any run; gains cannot be measured or shown |
| First turn | The census from `package_summary`; every deterministic check is invoked by the model through tools | Discovery costs one round trip per check per subject |
| Extraction | Meshes and faces are dump phases with flags (`--meshes`, `--faces`); a new run always re-extracts | Wall clock is paid again for an unchanged assembly |

The tool-schema row first said 29 tools and 32,435 bytes. That count was taken before the
feature 003 RMS tools landed, which is why it was already wrong when this document was
read; the figures above are regenerated from `reviewer/tests/unit/test_tool_payload.py`,
which pins them, rather than typed in a second time.

**Bytes are not tokens.** Every figure in that row is UTF-8 bytes on the wire, which is
all that can be measured without a provider. Any token count derived from it is an
estimate, and the first instrumented run (lever 1) replaces the estimate with what the
provider actually billed.

## Evaluation protocol (applies to every lever)

- **Benchmark set**: the packages under `benchmarks/packages/` with answer keys under
  `benchmarks/answer_keys/` (the existing `swreview benchmark` runner and scorecard).
- **Metrics per run**: input tokens, cached input tokens, output tokens, reasoning tokens;
  wall clock to first finding and to session end; scorecard (known defects found, false
  alarms, unresolved count); round trips.
- **Method**: each lever is a settings flag, default off. Run the set with the flag off and
  on, same provider and model, three repetitions each (models are not deterministic).
- **Adoption rule**: no known defect lost, no new false alarm, and a token or time reduction
  worth the code. A lever that trades quality for tokens is kept off and the numbers recorded.
- **Record**: the results table at the end of this file, one row per lever per model.

## Levers

### Tier 1: low risk, measurable with a before/after

| # | Lever | Expected effect | Trade-off or risk | How to measure |
|---|---|---|---|---|
| 1 | **Usage accounting**: record per-turn token usage from both adapters into `session.json` and show it in the pane and the benchmark scorecard | None on cost; makes every other lever measurable | None | Present in every session after the change |
| 2 | **Trim tool descriptions**: cap descriptions, move long guidance into the system prompt once | Schema tokens per request down by an estimated third to a half | A description that loses a needed hint changes which tool the model picks | Schema bytes; scorecard unchanged |
| 3 | **Prompt caching**: keep system prompt, checklist, and tool list as a stable prefix; OpenAI caches automatically, Gemini gets an explicit cached context per session for the prompt, checklist, and package digest | Cached input tokens replace most of the repeated prefix | Cache misses when anything in the prefix changes mid-session (settings save, tool tier change) | Cached-token share per run |
| 4 | **Tiered tool exposure**: query tools always; check tools once evidence exists; bridge tools only on the workstation; RMS tools only for documents with feature trees | Fewer schemas per request | A tool withheld when the model needed it shows as an unresolved item, never as a silent miss | Schema bytes; unresolved count |

### Tier 2: changes review behavior, needs the scorecard gate

| # | Lever | Expected effect | Trade-off or risk | How to measure |
|---|---|---|---|---|
| 5 | **Pre-run deterministic checks**: run fit, stack, fastener, alignment, interference, and RMS before the first turn and hand the model a compact digest; the model triages, requests evidence, and writes the narrative | Fewer round trips; no check forgotten | The model may treat the digest as complete and stop exploring; the digest must state what was not evaluated (the coverage buckets already do) | Round trips, tokens, scorecard |
| 6 | **Parallel tool calls**: enable for pure package queries; keep SOLIDWORKS-bound bridge calls serial on the STA thread | Fewer round trips | Step ordering in the session log changes; recording must stay deterministic | Round trips, wall clock |
| 7 | **Coverage-driven stop**: end the turn when every checklist item is closed and no evidence request is open | Fewer exploratory turns at the end | Ends a turn the model would have used for a useful extra check; coverage must be honest first | Tokens per run, scorecard |
| 8 | **Model tiers per job**: a fast model for orchestration turns, tool-result summaries, and the Ask tab; the large model for judgement and the report | Cost per run down | Routing mistakes; two models to configure and audit | Tokens, wall clock, scorecard per tier |

### Tier 3: extraction and re-review, needs workstation timing

| # | Lever | Expected effect | Trade-off or risk | How to measure |
|---|---|---|---|---|
| 9 | **Package reuse**: key the package by document path, version, and modification time from the manifest; a Review or Ask on an unchanged assembly reuses it | Extraction skipped entirely on a repeat | A stale package if the key misses a change (a referenced part edited outside the assembly); the manifest already lists every document | Dump wall clock on repeat runs |
| 10 | **Lazy extraction**: meshes and faces off by default; a tool fetches a body's mesh through the bridge when a check needs it | Dump wall clock down on the workstation | Envelope and bounding-box checks become bridge-dependent off the workstation; keep a flag to extract eagerly | Dump wall clock; checks unchanged |
| 11 | **Incremental re-review**: carry findings on parts whose feature-tree and geometry fingerprints are unchanged since the last run as "unchanged since <run>" | Re-review pays only for what moved | Carry-over must be visible, never silent; fingerprints must cover every input the check reads | Tokens on a re-run |
| 12 | **Rules over tokens**: every finding class the model keeps producing that a rule can express becomes a deterministic check | Zero tokens per part for that class | Only classes that are genuinely deterministic | Count of findings by check kind over time |

## Proposed feature 005 phases

1. Instrumentation (lever 1) and the benchmark metrics; a baseline table for both providers.
2. Tier 1 levers 2 to 4, each behind a flag, each measured; adopt the winners as defaults.
3. Tier 2 levers 5 to 8, one at a time, each gated by the scorecard.
4. Tier 3 levers 9 to 11 on the workstation with timings; lever 12 is standing practice.

## Results

**This table is generated, never typed.** It is a rendering of the `scorecard.json` files
in the run directories under `benchmarks/studies/`, produced by `swreview benchmark
compare`, because a hand-kept table goes stale and cannot be audited - which is what the
table that used to sit here had become.

Regenerate it, and verify it, from `reviewer/`:

```powershell
uv run swreview benchmark compare <every run directory under ../benchmarks/studies> `
  --into ../docs/llm-efficiency-options.md
uv run swreview benchmark compare <the same directories> `
  --into ../docs/llm-efficiency-options.md --check   # exits 1 if this file has drifted
```

**Nothing has been measured yet.** No agent review has been run against any package on any
provider, so there is no baseline row and no lever row, and the ledger below is empty
rather than optimistic. The first thing the harness produces is the baseline study of
`contracts/ab-harness.md` section 8, three repetitions per provider, and every row after
that is measured against it.

<!-- ledger:begin -->

## Results ledger

### Runs

| run | commit | lever | arm | rep | provider | model | effort | package | input | cached in | uncached in | output | reasoning/thoughts | tool-result in | total | rounds | tool calls | cached share | wall clock s | s to 1st finding | valid | missed | false alarms | unresolved | unresolved withheld | unresolved other | coverage bucket mix |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

No runs: no run directories were compared.

### Decisions

| Lever | Provider and model | Commit | Reps | Other levers on | Input tokens off -> on (median, min-max) | Cached input off -> on | Output off -> on | Reasoning or thoughts off -> on | Total tokens off -> on | Round trips off -> on | Tool calls off -> on | Wall clock off -> on | Dump wall clock off -> on | Valid / missed / false alarms / unresolved off -> on | Recall (held out) off -> on | Worst-case defects lost | Lever-specific counter | Decision | Owner signed off | Owner signed off at | Decision reason | Link to run dirs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

No decisions: no run directories were compared.

`Decision` is computed by the adoption rule and is never typed; `Owner signed off` and `Owner signed off at` are the owner's separate act, written by hand into the committed table once the row has been read and carried forward verbatim by every later regeneration. No flag default changes until they are written.

`wall clock s` is the session's own `started_at` to `ended_at`, **not** `unattended_runtime_minutes`, which the benchmark runner overwrites with a span that also covers package load and adapter construction.

<!-- ledger:end -->
