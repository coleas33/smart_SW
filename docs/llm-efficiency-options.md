# LLM efficiency, speed, and token options

Written 2026-09-16 as the input to feature 005. Updated 2026-09-20: instrumentation and
the original eleven efficiency flags and the new compact-query experiment are implemented
in `EfficiencySettings`; the flags still default off. Model routing and the Ask-tab
extensions below remain proposals. Implemented does
not mean adopted: the rule for feature 005 is
**instrument first, then one lever at a time behind a flag, adopted only on evidence**.

The next adoption candidate is parallel tool calls (lever 6), based on the pilot
measurements below. A different held-out real design and its engineer-reviewed answer key
are still needed before changing the pane default. The current reviewer improvements also
add a bounded automatic package brief and a compact finding-explanation pass; future A/B
arms must use the same code version so their overhead is included in both arms. No token
saving is claimed for those additions until measured on a provider.

For the next test build, `--lever compact_queries` adds bounded, paginated evidence
discovery without changing the default tool behavior. This is a new experiment, not an
adopted optimization. Use `--explain-findings` on both benchmark arms to include the
Review pane's explanation pass; the comparison rejects mismatched explanation modes
and step budgets. The generated raw ledger displays explanation mode explicitly.

## Baseline (measured on the tree at commit a0be95f plus the Phase 3 work in progress)

| What | Measured | Consequence |
|---|---|---|
| Tool schemas sent with every model request | 35 tools, **35,844 bytes** in the OpenAI encoding and 35,915 in the Gemini one (38 tools, 39,542 and 39,431 with the bridge); a pane review, once checks first has run its tools to completion (feature 008 lever 13), sends 29 tools and **29,217 bytes** (29,552 Gemini), 6,983 bytes and about 1,496 o200k tokens less per request (33 tools and 34,145 bytes with the bridge, which keeps `check_interference_group`); regenerated 2026-09-23 by `python -m tests.unit.test_tool_payload --write`, run from `reviewer/` | A review with 60 tool calls resends the whole array 60 times; the longest descriptions are `check_rms_assembly` (1,455 bytes), `check_rms_part` (1,296), `check_interference_group` (905) and `check_fastener_joint` (871), and the largest whole tool objects are `check_axial_stack` (2,734 bytes), `check_fit` (2,413) and `record_drawing_finding` (2,156); with every description emptied the array still weighs **16,042 bytes**, 45 percent of the payload and a floor no trimming can reach, so lever 2's ceiling is the other 55 percent |
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

### Tier 4 (added 2026-09-19): the agent inside the pane uses what we built

The numbers above are the option numbers of 2026-09-16; feature 005's flag table
(`specs/005-llm-efficiency/contracts/levers.md`) keys its flags by them, with option 11
(incremental re-review) carried as flag `11a carry_over_rms`. Feature 007's `procedural_gate`
took the bare number: it is **lever 11** in that table and in `EfficiencySettings`, its own
contract is `specs/007-attention-policy-gate/contracts/gate.md`, and its behaviour is being
implemented as this section is written.

The question asked on 2026-09-19: when an agentic model runs inside the add-in, how does it
use the checks, commands and scripts this repository already has, automatically, instead of
re-deriving them in prose or sending the engineer to another tab? What is true today:

- **The Review tab's model has no way not to.** Its whole API is the tool array: 32
  in-process functions (`tools/registry.py`), 35 in the pane, which always attaches the three
  bridge tools that are pipe calls into SOLIDWORKS; the eight deterministic checks are among
  them, and `check_standards` joins only when a standards run is attached. The system prompt
  says there is no shell, no file access and no way to run code
  (`agent/prompts/system_v1.md`). Lever 5, off by default, makes code call the four
  self-enumerating checks before the first turn; the procedural gate widens that; and lever 12
  is the standing practice of moving a finding class into a rule.
- **The Ask tab's CLI is registered by the host, not by the model.** On every launch the
  add-in writes a whole Codex home (`Terminal/CliProfileWriter.cs`, with a copy of the
  engineer's own Codex login) whose profile replaces the CLI's system prompt with ours,
  registers `swreview mcp` over the run folder with a 22-tool allowlist, turns the shell and
  web search off and the sandbox read-only (Codex's own `apply_patch` stays loaded and the
  sandbox refuses its writes), and refuses to start until a probe shows exactly those tools
  and that built-in loaded. The 22 are the query and measurement tools, capture, and two
  bridge tools. The allowlist is not the boundary, because the CLI can read its own generated
  profile: the boundary is the general-chat bridge secret, scoped to `ping`, `capture` and
  `measure`, and the tools the MCP server is built without. None of the eight deterministic
  checks, `check_standards`, or any `swreview` command is reachable from it, by construction:
  the terminal must create no finding (feature 002 FR-025), and the constitution forbids a
  generic execution tool.
- **The tab is hidden** (`TaskPaneControl.AskTabShown`); nothing below is measurable until it
  is part of the pilot, and only the Codex profile exists (the Gemini one is deferred).

| # | Lever | Expected effect | Trade-off or risk | How to measure |
|---|---|---|---|---|
| 13a | **Checks as Ask-tab tools**: add the deterministic checks (`check_rms_part`, `check_rms_assembly`, `check_rms_equations`, `check_interference_group`, `check_fit`, `check_axial_stack`, `check_fastener_joint`, `check_hole_alignment`, and `check_standards` when a profile is configured) to the stdio MCP toolset the generated profile registers, recorded in `chat-log.jsonl` and never in a session | A question about a fit, a stack or a clash is answered by the code the Review tab runs, in one call, instead of the CLI reading holes, mates and dimensions and reasoning about them; no "press Review" redirect | The MCP payload grows from 20 tools to 29 (22 to 31 with the bridge) on a path that levers 2 and 4 do not reach (feature 005 FR-077; FR-039b asks for lever 2 to reach it); `check_standards` dispatches only when a standards run is attached, which the MCP context has no way to do today; a check result in a chat log is not evidence, nothing in `report.md` cites it, and the persona has to say so; `check_interference_group` reads the package, but `bridge_interference` stays withheld because the general-chat secret scopes `ping`, `capture` and `measure` only; each tool moves the five pinned places of feature 003 `contracts/tools.md` plus `MCP_TOOL_FUNCTIONS`, the withheld list in `contracts/mcp-toolset.md` and its test mirror | Per Ask session, from `chat-log.jsonl`: check calls per question and questions answered with no tool call at all; the same ten questions on the small assembly's run folder with the checks off and on; payload bytes from `test_tool_payload.py`; zero findings or dispositions created from the terminal |
| 13b | **Commands as tools and prompts, never a shell**: the keyless commands with a fixed argument shape as MCP tools (`attention`, `rms suppress-plan`, `remodel plan`, `check rms`, `check standards`) and MCP prompts that open on the folder's ranking and report (`swreview://report` exists; add `swreview://attention`); the shell stays off | The CLI starts from what the run already found and what the policy put first, and answers "what do I fix first" without any model computing an order | A command that writes (a check run; `remodel plan` and `attention` write nothing) needs a scratch folder under the terminal's own run folder and a rule that it never claims a review folder; the server registers no prompts today ("none in v1") | Share of Ask sessions whose first call is a resource or prompt read; tokens to the first useful answer, where the CLI reports them |
| 13c | **Tool-first persona and a brief at start**: the generated prompt already says "Never answer from memory"; add that anything a tool can compute is computed, and hand the CLI the folder's "Start here" rows and coverage as its first resource, the way lever 5's digest and the gate's brief open a review | The CLI spends its turns on what the checks could not reach | Nothing types into the CLI today (the page forwards keystrokes only), so the brief is a resource plus an instruction, not a first message; every persona byte, and the MCP server's own `instructions` string on top of it, is resent on every turn | Feature 007's anti-drift check extended: the ids the CLI is handed equal `attention.json`'s |

Not this lever: `extractor/tools/update-workstation.ps1`, `register-addin.ps1`, the benchmark
package recipe (`benchmarks/README.md`) and the fixture generators are operator scripts. The
model that should run them is the assistant on the workstation, through
`docs/workstation-runbook.md`, which names the two scripts; an agent inside SOLIDWORKS must
never build, register or update the add-in it is running in.

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

**The adoption ledger is still empty.** Pilot measurements are recorded under
"Measurements outside the ledger" below; they do not satisfy the held-out adoption gate.
The formal baseline study is defined by `contracts/ab-harness.md` section 8, with three
repetitions per provider. Each lever row must be compared against its matching baseline.

<!-- ledger:begin -->

## Results ledger

### Runs

| run | commit | lever | arm | rep | provider | model | effort | explanations | package | input | cached in | uncached in | output | reasoning/thoughts | tool-result in | total | rounds | tool calls | cached share | wall clock s | s to 1st finding | valid | missed | false alarms | unresolved | unresolved withheld | unresolved other | coverage bucket mix |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

No runs: no run directories were compared.

### Decisions

| Lever | Provider and model | Commit | Reps | Other levers on | Input tokens off -> on (median, min-max) | Cached input off -> on | Output off -> on | Reasoning or thoughts off -> on | Total tokens off -> on | Round trips off -> on | Tool calls off -> on | Wall clock off -> on | Dump wall clock off -> on | Valid / missed / false alarms / unresolved off -> on | Recall (held out) off -> on | Median net saved minutes off -> on | Worst-case defects lost | Lever-specific counter | Decision | Owner signed off | Owner signed off at | Decision reason | Link to run dirs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

No decisions: no run directories were compared.

`Decision` is computed by the adoption rule and is never typed; `Owner signed off` and `Owner signed off at` are the owner's separate act, written by hand into the committed table once the row has been read and carried forward verbatim by every later regeneration. No flag default changes until they are written.

`wall clock s` is the session's own `started_at` to `ended_at`, **not** `unattended_runtime_minutes`, which the benchmark runner overwrites with a span that also covers package load and adapter construction.

<!-- ledger:end -->

## Measurements outside the ledger

Rows the generated ledger cannot carry: every run below was made on the one-package pilot
set with `--i-know-the-set-is-too-small`, so `compare` computes no decision and the study
folders stay outside `benchmarks/studies/` (a committed override row fails the check test).
They are evidence, not gates; the pane default changes nothing on their account. Recorded
from the workstation packet of 2026-09-19 (`docs/pane-findings-2026-09-19.md`).

**Token baseline, pilot workstation, 2026-09-19.** One review of the small assembly, the
dowel-pin one, with every lever off, openai `gpt-5.6-luna` at high effort: 1,215,720 tokens, of
which 95.3 percent of the input was served from the implicit cache; 32 round trips, one tool
call each; 84 s. Uncached input was 57,030 tokens. Two negative results follow from it and
are recorded so they are not tried first: lever 3's explicit cache has about 5 percent of
headroom left on this seat, and lowering the reasoning effort attacks 0.5 percent of the
bill. The multiplier to attack is the round count.

**Lever 6 (`parallel_tool_calls`), two studies, three repetitions per arm, alternated.**

| Package | Metric | Off (median) | On (median) | Change |
|---|---|---|---|---|
| the small assembly's dump (real design, provisional key of the six pane-baseline findings) | total tokens | 1,428,464 | 463,951 | -67.5 percent |
| | round trips | 35 | 11 | -68.6 percent |
| | tool calls | 34 | 42 | +23.5 percent |
| | wall clock s | 87 | 65 | -25.1 percent |
| | valid / missed / false alarms | 6 / 0 / 0 | 6 / 0 / 0 | unchanged on every rep |
| cover-blind-tap (fixture; both arms miss both keyed defects on every rep) | total tokens | 795,651 | 166,090 | -79.1 percent |
| | round trips | 44 | 8 | -81.8 percent |
| | wall clock s | 116 | 64 | -45.0 percent |

Reading: lever 6 batches calls into fewer rounds; the steps stay, the rounds collapse, and
on the real design no defect was lost and no false alarm appeared. The tool-call rise is
more work per cheaper round, not a thinner review. The cover-blind-tap rows say nothing
about quality: that package's key is not met by either arm.

**Decision taken 2026-09-19, outside the ledger:** command-line studies of this workload may
hold `--lever parallel_tool_calls` on in both arms from here (it becomes the "other levers
on" column of the next study). The pane default stays off until the set holds a held-out
package with an engineer's answer key and the ledger carries a signed-off row.

**Decision taken 2026-09-22, outside the ledger (feature 008):** by the owner's decision, all
four changes of feature 008 are pane defaults: checks first (lever 5) on every provider,
parallel tool calls (lever 6) on OpenAI, and the two model-view settings, payload slimming and
history pruning after two rounds. They are gated by the offline replay
(`swreview benchmark replay`, 008 `contracts/replay.md`), not by this ledger: the replay prices a
recorded review through the current code and fails when a recorded finding is lost. This
supersedes the 2026-09-19 rule above, that the pane default waits for a held-out package and a
signed-off ledger row, for levers 5 and 6. The model-view settings are **not levers**: they
change what the model reads, never what the review records (the session, the package, the report
and every stored result keep the full payload), so they are not in `LEVER_NAMES` and move no
lever count (008 research R2.32). Since 2026-09-23 lever 13 (`withhold_prerun_tools`: the tools
checks first ran to completion leave the array) is a pane default on the same terms (008 FR-030,
research R2.53).

The replay's figures, requested input tokens counted with o200k_base, copied from
`swreview benchmark replay` on the three committed fixtures (run from `reviewer/`, each with
`--standards-profile ../config/standards.example.yaml`, 2026-09-23, on the fixtures the current
code regenerated, 008 decision 3A; the figures of 008 `contracts/replay.md` section 9's last
row, measured on 2026-09-25 when the owner's decision 20A landed - feature 003 T090 to T092, the
eleven system types of the real dumps tolerated, read by feature 008's decision 23A - on the
fixtures it regenerated: the part check each recorded review made no longer names those rows, so
the recorded and as-recorded columns fall, and no requested figure moves, because checks first
answers the recorded part checks and its digest counts findings, not subjects. The requested
figures are those of feature 011's integration and of every re-measurement since). The fixtures record the scripted provider, whose pane runs checks first, lever 13, slimming
and pruning but no parallel calls; `--lever parallel_tool_calls` gives the OpenAI pane, on which
SC-003's regrouped estimate is read. The regrouped estimate assumes the model does not repeat a
check the digest reported and batches consecutive calls to one tool (008 `contracts/replay.md`
section 6); the requested figure assumes the model makes the recorded calls in the recorded
rounds.

| Fixture | Recorded | As recorded | Requested, pane defaults | Regrouped estimate, pane defaults (rule R) | Regrouped estimate, OpenAI pane (rules R and M) | Requested, `--prune-after 1` | Regrouped estimate, OpenAI pane, `--prune-after 1` |
|---|---:|---:|---:|---:|---:|---:|---:|
| big-assembly | 11,732,561 | 11,732,463 | 663,902 | 486,940 | 277,361 | 619,092 | 233,746 |
| small-assembly-a | 1,566,206 | 1,566,323 | 459,000 | 381,853 | 245,289 | 444,881 | 231,665 |
| small-assembly-b | 1,483,228 | 1,483,361 | 453,564 | 389,232 | 244,277 | 440,841 | 231,776 |

Commands, in column order: `--no-pane-defaults` (recorded and as recorded), the default, the
default's `regrouped estimate` line, `--lever parallel_tool_calls`, `--prune-after 1`, and
`--lever parallel_tool_calls --prune-after 1`. No recorded finding is lost, none is not
replayable, none is reclassified and none is narrowed in any run: the recordings' 3, 2 and 0
touching groups are recorded in the fixtures as the contacts feature 010's code judges them, and
every requested pass holds them, and the recordings' 20, 2 and 1 loose-feature findings are
recorded as the current type table narrows them (008 decision 23A); 62, 7 and 5 findings are
added by feature 010's checks in the pre-run. The big fixture's follow-up round is 22,719
requested against 383,392 recorded (22,099 at `--prune-after 1`). These are replay figures, not bills: the paid figures of the next workstation
sitting go beside them (008 T102 to T105).
