# Contract: the A/B harness and the results ledger

The A/B protocol, the runs it produces, and `swreview benchmark compare`, the one reader that
validates those runs and renders the ledger.

**The ledger is a rendering of N `scorecard.json` files, not a hand-kept artifact.** Typed numbers
go stale and cannot be audited, which is exactly what the table at the end of
`docs/llm-efficiency-options.md` becomes if it stays typed.

## 1. Shape of the harness, and what it deliberately does not do

**The harness is a stated procedure plus one reader command.** There is no `ab` sub-app and no
schedule file. The runs are made by the existing `swreview benchmark run` and scored by the
existing `swreview benchmark score`, both unchanged except for the `--lever` option; the reader is
one new command beside them.

| Step | Command | Contacts a provider | Reads | Writes |
|---|---|---|---|---|
| Run an arm | `swreview benchmark run --lever <name> ...` | yes | the benchmark set, the packages on disk | a run folder per package, plus the **run provenance record** |
| Score it | `swreview benchmark score <run dir> --answer-keys ...` | no | the run folder and the answer keys | `scorecard.json`, `scorecard.md` |
| Render the ledger | `swreview benchmark compare <run dirs...> --out <dir>` | **no** | each run folder's provenance record, `session.json`, `events.jsonl` and `scorecard.json` | `ledger.json` and `ledger.md` |

**`compare` never contacts a provider and never starts a run.** Three reasons, in order of weight:

1. **Six unattended live runs behind one command is hours of wall clock and real money with no
   seam to restart from.** Three separate run folders make a re-run of one flaky package possible;
   one nested run does not.
2. **`run_benchmark` deliberately knows nothing about arms, levers or commits**, and putting them
   inside it would have it invent a nested folder layout and an aggregation, which is the
   scorecard's job.
3. **Every arm is one commit**, so a wrapper would be pinning a tree it did not check out. Lever 2
   is no exception: its off arm is the rejoined description behind the flag (levers.md lever 2,
   FR-033), not an earlier commit.

The cost, stated rather than hidden: the engineer types six commands rather than one, and **the
alternation of the arms is a discipline this document states rather than something the code
enforces** (section 2). `compare` can only refuse an inconsistent set after the fact; it cannot
make the set consistent. If the owner prefers a single wrapper command, that is a thin shell
around these six plus the compare, and it should be argued on its own. See plan.md Q11.

## 2. The study protocol, and what `--lever` refuses

A study is **one lever, one provider, one model, one effort, three repetitions per arm** (more only
if the control arm proved unstable). **Each repetition is its own `swreview benchmark run`
invocation into its own run folder; there is no repetition option and no loop inside the runner**
(FR-023) - the `foreach` below is the loop. A second provider is a **second study**, not more arms
in this one.

```powershell
cd reviewer
$set  = "../benchmarks/sets/pilot.json"
$keys = "../benchmarks/answer_keys"
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "<studies>/lever06-openai/off-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever prompt_cache_key `
    --study parallel_tool_calls --arm off --rep $rep
  uv run swreview benchmark score "<studies>/lever06-openai/off-$rep" --answer-keys $keys
  uv run swreview benchmark run --set $set --out "<studies>/lever06-openai/on-$rep" `
    --provider openai --model gpt-5.6 --effort high --lever prompt_cache_key `
    --lever parallel_tool_calls `
    --study parallel_tool_calls --arm on --rep $rep
  uv run swreview benchmark score "<studies>/lever06-openai/on-$rep" --answer-keys $keys
}
$runs = Get-ChildItem -Directory "<studies>/lever06-openai" | ForEach-Object { $_.FullName }
uv run swreview benchmark compare @runs --out "<studies>/lever06-openai"
```

(`compare` takes run directories, not a glob, and PowerShell does not expand `*` for a native
command; `-Directory` also keeps the `ledger.*` files a previous `--out` wrote out of the list.)

**The run order is normative: alternated (off, on, off, on, off, on)**, so provider-side drift
during the session does not land entirely on one arm. This is protocol, not a code path; the
provenance record's start time is what lets a reader check it afterwards.

**Fixed across every run of a study**: the set file and the packages on disk (byte-identical), the
answer keys, the model id, the effort, `max_steps`, the checklist, and the tree at one commit per
arm. **Recorded per run** in the provenance record: the commit sha, the resolved
`EfficiencySettings` in full, the lever under test, the arm, the repetition index, the provider,
the model, the effort, `max_steps`, the checklist digest, the set-file digest and the start time.

`--lever` is repeatable. The lever under test is the one that differs between the arms; every
other `--lever` on the line is held on in **both** arms and becomes the ledger's "other levers on"
column (levers.md section 3).

**`--study <lever name|none> --arm off|on|baseline --rep <n>` supply the three provenance fields
the flags cannot.** Which lever a run is testing, which arm it is, and which repetition it is are
facts *about the study*, not about the settings: they exist across two run folders, not inside
one. Without them a lever-6 off run (`--lever prompt_cache_key`), a lever-3 on run
(`--lever prompt_cache_key`) and a baseline run (no `--lever` at all) are byte-identical in
settings, in `session.efficiency` and in the provenance record, and `compare` cannot place any of
them in the right arm of the right study. `--study none --arm baseline` is the baseline study of
section 8. These three are written into the provenance record verbatim; **nothing derives them and
nothing infers them from the folder name.**

**Refusals on `swreview benchmark run --lever`** (each a message naming the rule, not a stack
trace). They belong on `run` rather than on `compare` because that is where the lever is chosen,
and a refusal after six paid runs is worthless:

- An unknown `EfficiencySettings` field name. Unknown is refused, never ignored.
- `--lever coverage_stop` together with `--lever prerun_checks`. **Levers 5 and 7 never share an
  arm until each has been gated alone** (levers.md section 3).
- `--lever parallel_tool_calls` with `--provider gemini`. Gemini already makes parallel tool calls
  and has no disable switch (levers.md, lever 6); the refusal is better than an arm that measures
  nothing.
- `--lever package_reuse`, `lazy_meshes` or `carry_over_rms`. **These three are invisible to
  `swreview benchmark run`**, which iterates pre-built package directories and never dumps
  (VERIFIED, `benchmark/runner.py:88-104`). The refusal names the **workstation harness** instead:
  a script that drives the dump (and, for lever 11a, a review) on the seat and **writes a run
  directory of the same shape this runner writes** - the same provenance record, taking the same
  `--study`, `--arm` and `--rep`, plus a scorecard-shaped record carrying the per-phase dump wall
  clock, the lever's pass-or-fail precondition verdict and the session usage, with every field it
  cannot produce `null` rather than `0` or absent. `compare` therefore renders these three levers
  through this same reader, at the same three repetitions per arm, and no measured lever is absent
  from the ledger (FR-030a, FR-030b, SC-010). Their rows say the scorecard was not their gate.
- The benchmark set holds no `held_out: true` package, or fewer than the configured minimum of
  packages. This is precondition P-3 and it is **a refusal, not a warning**: gating on one package
  with two known defects and no geometry means one lost defect is a 50 percent regression and
  `recall` never computes (VERIFIED, `scorecard.py:200-204`). An explicit
  `--i-know-the-set-is-too-small` is accepted for a smoke test and is **written into the provenance
  record and therefore into every ledger row it produces**, so the row can never be read as a gate.
- **`--study`, `--arm` and `--lever` that contradict each other**, each named in the message:
  `--arm on` with the studied lever absent from `--lever`; `--arm off` with the studied lever
  present in `--lever`; `--arm baseline` with any `--lever` at all, or with `--study` anything
  other than `none`; `--study none` with `--arm off` or `--arm on`. A run mislabelled in its own
  provenance record is worse than no run, because it renders without complaint in the wrong arm.

**Every lever's two arms are one commit, lever 2 included.** Lever 2's off arm is recoverable by
flipping its flag: with `trim_tool_descriptions` off, the adapter and the MCP toolset are handed
the **rejoined** description, byte-equal to the pre-split docstring body (FR-033, FR-039), so both
arms run from the post-split commit. `compare` therefore has **no declared exception** to its
same-commit refusal. FR-032 stands as a general guard - a lever whose arms really were two commits
would carry both shas as `commit_off` and `commit_on` and would never be presented as a flag toggle
- but this feature has **no instance of it**, which is the state the guard is cheapest in.

**Human timing is recorded once per package per arm, not per repetition.** `swreview benchmark
time` is unchanged. A human baseline does not change between repetitions, and pretending to
re-measure it would put noise into `net_saved_minutes`.

## 3. What `compare` validates, and it is the point of the command (RK-20)

`compare` takes N run directories. For each one it reads the provenance record, `session.json`,
`events.jsonl` and `scorecard.json`, **per package**.

**Two independent writers, cross-checked.** `session.efficiency` is written by the runner from the
resolved `EfficiencySettings`; the provenance record is written by `cli.py` from the `--lever`
options actually typed. A run whose two records disagree is **refused, not scored**, and the
message names the field:

| Checked | Source of truth |
|---|---|
| `session.efficiency` equals the provenance record's full settings dump | `session.json` against the provenance record. A missing `efficiency` is refused with "this run predates the flag carrier and cannot be attributed to an arm" |
| provider, model, effort | `session.json` `provider_info` and `model`, against the provenance record |
| commit sha | the provenance record |
| benchmark set sha256 | the `benchmark-set.json` copy `benchmark run` already saves into the run directory, against the provenance record's `set_digest`, which **is the sha256 of that saved copy** (section 10.2) |
| answer-keys path | **not cross-checked**: `scorecard.json` records none (section 10.4). What is asserted instead, by path, is that `compare` reads no file under the answer-keys directory at all |
| checklist digest | **across the runs of a study, not against `session.json`**, which carries no checklist digest (section 10.3) |
| the scorecard exists | `scorecard.json` beside the run |
| the arm matches the studied lever's flag | for a run whose provenance `arm` is `off` or `on`, `session.efficiency[<the provenance record's `lever`>]` must equal `arm == "on"`; the refusal names the lever. This is a **second** clause and not a narrowing of the row above it, which still compares the whole settings dump field by field. A baseline run (`lever: "none"`, `arm: "baseline"`) has no lever under test and is exempt from this clause; it is checked instead as every flag false |

**Across the set**, `compare` refuses to place two runs in one comparison when the commit, model,
effort, set file or checklist differ, and it says which field differed. **There is no declared
exception**: every lever's two arms are one commit, including lever 2 (section 2).

**And the set has to be six runs, not one run named six times.** The adoption rule's repetition
precondition counts the runs it was handed, so `compare` refuses two things before counting:

- the **same run directory named more than once** on the command line, compared as resolved paths
  so `off-1` and `./off-1` are one folder, naming the folder; and
- two runs of one study **in the same arm at the same `rep`**, naming the arm and the repetition.
  A gated arm (`off` or `on`) whose run carries no `rep` at all is refused the same way, telling
  the operator to re-run it with `--rep <n>`. A baseline arm is exempt from that last clause only,
  because it gates nothing (section 8).

Without these, three copies of one folder satisfy "three repetitions per arm" and an `adopt` can
rest on a single measurement - the precise failure `compare` exists to prevent.

A run directory with **no provenance record at all** is not an error: it is rendered as a row with
those columns null. A run made before the convention existed is still a real run, and dropping it
silently would be worse than showing it as unattributable.

**`compare` reads no answer key.** It reads `scorecard.json`, which `benchmark score` already
produced. Principle VI and FR-025 are untouched.

`compare` is idempotent over the same folders: re-running it regenerates `ledger.json` and
`ledger.md` from the run directories, which are the only source. There is no append-only state to
drift.

## 4. `ledger.json`, the raw ledger

`ledger.json` holds two arrays, `runs` and `levers`. `runs` is **one object per run per package**.
Every field has **exactly one source and no field is computed twice**.

```json
{"ledger_schema": "1.0",
 "runs": [
  {"run": "lever06-openai/on-2", "arm": "on", "rep": 2, "lever": "parallel_tool_calls",
   "other_levers_on": ["prompt_cache_key"],
   "commit": "5733efd", "provider": "openai", "model": "gpt-5.6", "effort": "high",
   "package_id": "rms-part", "held_out": true,
   "input_tokens": 412033, "cached_input_tokens": 331200, "uncached_input_tokens": 80833,
   "output_tokens": 18422, "reasoning_tokens": 16004, "tool_result_input_tokens": null,
   "total_tokens": 430455,
   "rounds": 9, "tool_calls": 31, "cached_input_share": 0.8038,
   "wall_clock_s": 512.4, "seconds_to_first_finding": 44.1,
   "valid_findings": 17, "missed_known_defects": 1, "false_alarms": 2, "unresolved_count": 5,
   "coverage_bucket_mix": {"checked": 12, "skipped": 1, "unresolved": 5,
                           "out_of_scope": 3, "failed": 0},
   "unresolved_because_withheld": 0, "unresolved_other": 5,
   "lever_counter": {"steps": 31, "rounds": 9},
   "set_too_small_override": false,
   "run_dir": "<studies>/lever06-openai/on-2/rms-part"}
 ],
 "levers": ["... one decision object per lever per provider and model; section 5 ..."]}
```

| Field group | Source, and nothing else |
|---|---|
| `input_tokens` through `total_tokens`, `rounds` | `session.json` `usage.totals` and `usage.rounds`, verbatim. **Never re-summed here** |
| `uncached_input_tokens`, `cached_input_share` | derived **in the scorecard only**, read through. Null when either input is null. **Not published until probe L1 is recorded** (FR-047): until then the column renders as unknown, because the share is well defined only if cached input is contained in input |
| `tool_calls` | `len(session.steps)`. This is **not** `rounds` and the two must never be conflated; with lever 6 on they diverge by exactly the amount lever 6 saves |
| `wall_clock_s` | `PackageScore.wall_clock_s`, which is `started_at` to `ended_at` on the session. **Distinct from `unattended_runtime_minutes`**, which `run_benchmark` overwrites with a `time.perf_counter()` span that also covers package load and adapter construction (VERIFIED, `benchmark/runner.py:99-103,55-65`; usage.md section 9). The ledger quotes the session's own number, and the baseline row says so explicitly |
| `seconds_to_first_finding` | `events.jsonl`: the `at` of the first `finding` event minus the `at` of `session.started`. Null when the run produced no finding |
| `valid_findings` through `unresolved_count`, `coverage_bucket_mix` | the existing `PackageScore` |
| `unresolved_because_withheld`, `unresolved_other` | `PackageScore`. The two numbers FR-054 requires; they sum to `unresolved_count` |
| `lever`, `arm`, `rep`, `commit` | the run's provenance record, written from `--study`, `--arm`, `--rep` and the commit sha, cross-checked against `session.efficiency` (section 3) |
| `other_levers_on` | `session.efficiency`: every flag true other than the studied lever |
| `lever_counter` | the lever's own gate number; section 6 |

**Null is null.** A token field whose session total is null is `null` in the ledger, never `0` and
never omitted (RK-1). A median over a column containing nulls is computed over the non-null values
**and the row count is stated beside it**; a worst case over a column containing nulls is `null`.

This binds `worst_case_defects_lost` too. `0` there is a **measurement** - the defects-lost
comparison ran and found nothing - so it may be printed only from a verdict that reached rule 1.
A refused precondition, an unstable control arm and a baseline study all decide before rule 1
fires, so their `worst_case_defects_lost` is `null` and the cell reads `unknown`. A study nobody
compared may not report that nothing was lost.

## 5. The decision rows, and who owns the Decision

`compare` renders **one decision row per lever per provider and model** into `ledger.md`, applying
the four rules of levers.md section 7.

```
| Lever | Provider and model | Commit | Reps | Other levers on |
| Input tokens off -> on (median, min, max) | Cached input off -> on | Output off -> on |
| Reasoning or thoughts off -> on (named per provider) | Round trips off -> on |
| Tool calls off -> on | Wall clock off -> on | Dump wall clock off -> on (levers 9, 10) |
| Valid / missed / false alarms / unresolved off -> on | Recall (held out) off -> on |
| Median net saved minutes off -> on | Worst-case defects lost | Lever-specific counter |
| Decision | Owner signed off | Owner signed off at | Link to run dirs |
```

**Median net saved minutes is reported and never gated on** (feature 007 FR-006, and
`specs/007-attention-policy-gate/contracts/timing.md` section 4, which is normative for it). The
cell is the median **across the arm's runs** of each run's own per-package median
(`scorecard.aggregate.median_net_saved_minutes`), rendered like every other off/on cell and
carrying `n=` the number of runs that carried timing at all - `unknown` with `n=0` where none did,
which is what every study reads until the owner starts recording the four inputs with `swreview
timing`. It is the number the pilot is judged on and it is deliberately **not** one of the metrics
the four rules below read: `decide` names the metrics it reads, so a row can never be turned by a
figure the engineer typed by hand.

**`Decision` is computed, not typed.** It is derived from the scorecards by the rule below and is
**one of `adopt`, `keep off`, `re-measure`** and nothing else (FR-027, SC-009). A decision of
`adopt` with no six-run set behind it, or resting on a metric not present in the scorecards, cannot
be rendered at all. This is deliberate: the audited number must not be a free-text field.

**The owner still signs.** Adoption is the owner's act, and it is recorded in a **separate**
field beside the computed one: `owner_signed_off: bool` with `owner_signed_off_at`, both written by
hand into the committed `ledger.md` after the owner has read the row. A row may be computed `adopt`
and unsigned; **no flag default changes until it is signed**. What the owner may not do is retype
the computed column.

**A sign-off is carried, never computed.** `compare` regenerates the whole table between the
markers, so a hand-written sign-off would be erased by the next run and `--check` would report the
signed document as drifted. Instead, before rendering, `compare` **reads the two sign-off cells
back off the ledger it is about to overwrite** - the `--into` document, and the `ledger.md` already
in the `--out` directory, the document winning where both exist - and copies them onto the matching
`(lever, provider, model)` row. A row with no committed predecessor keeps its `false` default, and
nothing about a run can ever set the field. So the hand edit survives regeneration byte for byte,
and `--check` stays green on a signed document. Both cells are `yes` or `no` and an ISO date or
`unknown`; anything else in the sign-off cell is a typo in the column the gate rests on and is
refused rather than read as `no`.

**The precondition, read before the four rules (FR-029, SC-011).** `compare` **refuses to render a
decision row** for a study when either holds:

- the study's scorecards cannot produce a recall number - no `held_out: true` package, so
  `recall_held_out` is null in both arms (VERIFIED, `scorecard.py:200-204`); or
- any contributing run's provenance record carries `set_too_small_override: true`.

The message names which of the two fired and, for the second, which runs carry the override. The
command exits non-zero for a decision it was asked to compute and refused. In `ledger.json` the
study still appears in the `levers` array, with `decision: null` and the refusal reason in
`decision_reason`. **This is the one place `decision` may be absent**, and it is an absence rather
than a fourth value, so FR-027's closed three-value enum is not widened.

This rule lives **here and not in section 3**, because section 3's refusals reject *runs*: the raw
per-run rows of a smoke-test study must still render, which is what `set_too_small_override` in the
row object (section 4) exists for. The run-side refusal in section 2 stops the six paid runs from
being made; this one stops the gate from being read off them if they were made anyway.

**The four rules, applied mechanically:**

1. **Defects lost: worst case.** `FAIL` if *any* on-run misses a defect that *any* off-run found,
   and the defect ids are named. Not a median, not an average.
2. **False alarms: median, with the worst case printed beside it.** Asymmetric on purpose.
3. **Threshold: a median total-token reduction of at least 20 percent, or a median wall-clock
   reduction of at least 20 percent**, against the off arm's median over the whole set.
4. **Control-arm stability first.** If the off-runs disagree with each other about which defects
   were found, the computed decision is **`re-measure`**, the reason printed beside it is
   `CONTROL UNSTABLE`, the disagreeing defect ids and packages are named, and **no pass is
   printed**. A gate whose control arm is unstable cannot decide anything. `CONTROL UNSTABLE` is a
   printed reason, **not a fourth decision value**; the enum stays closed at three.

**Every lever that fails is kept off and its numbers are recorded**, which is why this column
exists rather than a list of winners.

**Reasoning and thoughts are never merged into one column**: OpenAI's `reasoning_tokens` is a
subset of `output_tokens` and Gemini's `thoughts_token_count` is a separate addend of the total
(usage.md section 3). The column header names the provider's own field.

**"Other levers on" is a required column**, not a footnote, because levers are not independent in
effect (levers.md section 3). A number without it is unattributable.

## 6. The lever-specific counter column

One column carrying the number that lever's own gate needs and no other's.

| Lever | `lever_counter` holds | The gate it serves |
|---|---|---|
| 2 `trim_tool_descriptions` | the tool-name histogram from `session.steps` | No check tool drops out of the model's repertoire |
| 3 `prompt_cache_key` | miss reasons and `cache_missed_tokens` per round | Whether the prefix is hitting, and what broke it when it is not |
| 4 `tool_tiers` | `unresolved_because_withheld` and `unresolved_other` | The first may rise; the second must not |
| 5 `prerun_checks` | the `check_fit` and `check_axial_stack` call counts | Those two are never pre-run; if they fall, the digest is suppressing exploration |
| 6 `parallel_tool_calls` | steps beside rounds | Steps up while rounds down is speculative batching |
| 7 `coverage_stop` | the stop fire rate, and the `skipped` and `out_of_scope` counts | A lever that fires on one package in five is a different lever from one that fires on five in five, and the token average hides that |
| 9 `package_reuse` | dump wall clock cold versus reused, and the byte-identity verdict | Byte-identity is a **precondition**, read before the scorecard |
| 10a `lazy_meshes` | `bodies_swept` per arm and bridge `elapsed_ms` per `tessellate` | Identical `bodies_swept`, or `unresolved` naming what could not be fetched |
| 11a `carry_over_rms` | carried versus re-run counts | A lever that "improves" recall by remembering is not an improvement |

## 7. Preconditions for the whole harness, in order

1. **The instrumentation has landed**: per-round usage from both adapters, summed onto
   `session.json`, surfaced in `PackageScore` and `render_scorecard_md`.
2. **Round trips are recorded alongside steps**, delivered by `round_index` (usage.md section 5).
3. **`EfficiencySettings` is recorded on the session** (levers.md section 1).
4. **P-3: the benchmark set has grown.** The precondition most likely to be skipped, and it
   invalidates every gate if it is. Today `benchmarks/sets/pilot.json` holds **one** package,
   `cover-blind-tap`, `held_out: false`, whose answer key has **two** known defects and whose
   `package.json` has **0 mates, 0 holes, 0 threads, 0 fasteners, 0 faces, 0 bodies, 0
   interferences, 0 captures, 0 features, 0 equations** (VERIFIED). Consequences: `recall` is
   `None` whenever `held_out_known_defects` is zero (VERIFIED, `scorecard.py:200-204`), so the
   headline quality metric does not compute; one lost defect out of two is a 50 percent swing; and
   **levers 9, 10 and 11 cannot be exercised on it at all**, because there is nothing to reuse that
   took time to build, no mesh to fetch and no feature tree to fingerprint. Minimum: **build
   `rms-part`** from `benchmarks/native/rms-part/RECIPE.md` (its answer key already holds 20 known
   defects across 20 distinct `rms.*` rules and 18 correct conditions) **and hold out at least one
   package**. The constitution asks for 5 to 10 representative designs.
5. **For levers 9 and 10 only**: dump phase timing exists and a workstation with the pilot assembly
   is available. **No dump timing exists today**: no `Stopwatch` and no elapsed field anywhere in
   `Dump/PackageWriter.cs`, and `DumpSummary` carries counts only
   (`AddIn/Review/ReviewServices.cs:23-53`). `SuppressTestRow.elapsed_ms` (`ir/models.py:487`) is
   the only elapsed precedent in a package, and `extractor.phases` as a list of
   `{name, elapsed_ms, status}` is the same shape.
6. **The lever's flag exists, defaults off, and is threaded into `benchmark run`.**
7. **The four adoption-rule answers are written down** (levers.md section 7) **before the first
   run**, not argued after a result is in hand.

## 8. The baseline, which is a study with no lever

The first thing the harness produces is the row that does not exist today. **No agent review has
ever been run on any package and there is no baseline token number for any provider.**

A baseline study is `swreview benchmark run` with **no `--lever` at all**, every flag off, three
repetitions, each its own invocation into its own run folder, each passing
`--study none --arm baseline --rep <n>`. Its provenance records carry `lever: "none"` and
`arm: "baseline"`. `compare` over a baseline study prints the distribution rather than a
comparison, and **no `Decision`**: there is nothing to compare against yet. Because it renders no
`Decision`, **the precondition rule of section 5 never blocks a baseline**: the Phase 2 baselines
are runnable against whatever set exists, which is the point of running them first.

**The baseline row names which wall-clock number it is quoting** (FR-010, SC-005). Two writers
touch the field: `finalize_session` computes it from `started_at` to `ended_at`, and
`_record_unattended_runtime` then overwrites `Timing.unattended_runtime_minutes` with the
benchmark's own `time.perf_counter()` span, which also covers package load and adapter
construction (VERIFIED). The ledger's `wall_clock_s` is the session's number; the baseline row says
so in words, so nobody later compares the two as if they were one quantity.

Two baseline studies are run in Phase 2, one per provider, three reps each. Everything after that
is measured against them.

## 9. Tests

All of these run with no key and no seat, because every input is a file.

1. Each refusal in section 2 is a test on `benchmark run --lever`: unknown lever, 5 with 7, lever 6
   on Gemini, a Tier 3 lever, a set with no held-out package (and the override flag recorded in the
   provenance record and in every row it produces), and each of the four `--study`/`--arm`/`--lever`
   contradictions: `--arm on` without the studied lever, `--arm off` with it, `--arm baseline` with
   any `--lever` or a `--study` other than `none`, and `--study none` with `--arm off|on`.
2. The provenance record holds the complete `EfficiencySettings` dump, not a diff, so a reader
   never has to reconstruct what the other nine flags were.
3. `compare` **refuses** a run folder whose `session.efficiency` does not match its provenance
   record, and the message names the field that differs.
4. `compare` refuses a run whose `session.json` has no `efficiency` at all, with the
   "predates the flag carrier" message.
5. `compare` refuses to place two runs in one comparison when the commit, model, effort, set file
   or checklist differ, and names the field; **there is no accepted exception**, lever 2 included,
   whose two arms are one commit behind its flag.
6. A run directory with no provenance record renders as a row with those columns null and exits 0.
7. A null token total produces a `null` ledger field, and the median over that column states how
   many rows contributed.
8. `compare` computes `keep off` on worst-case defect loss driven by a **single** on-run, over a
   hand-built set of scorecards.
9. `compare` computes **`re-measure`** with the printed reason `CONTROL UNSTABLE` and no pass when
   the off-runs disagree about defect ids; the decision value is one of the three and never a
   fourth.
10. `compare` applies the 20 percent threshold to the **median**, and a 19 percent median with a
    35 percent best case does not pass.
11. `owner_signed_off` defaults false and is never **computed** by `compare`; a computed `adopt`
    with `owner_signed_off: false` changes no flag default. A hand-written `yes` with a date in the
    committed ledger is **carried forward** into the next regeneration byte for byte, `--check`
    stays green on that signed document, and the computed `Decision` beside it is unchanged.
12. A baseline study renders a distribution and no `Decision`.
13. `compare` reads no file under the answer-keys directory (asserted by path, the way
    `_reject_answer_key_path` already asserts it).
14. Until probe L1 is recorded, the cached-share column renders as unknown rather than as a number
    (FR-047).
15. `compare` **refuses to render a decision row** over a study built on today's single-package
    `benchmarks/sets/pilot.json` (no `held_out: true`, `recall` null), names why, exits non-zero,
    and **still renders the raw per-run rows**; the same refusal fires when a contributing
    provenance record carries `set_too_small_override: true`, and the message names those runs.
    This is the test SC-011 asks for (FR-029).
16. `compare` refuses a run whose provenance `arm` is `on` while `session.efficiency` has the
    studied lever false (and the mirror case for `off`), naming the lever; a baseline run with
    `lever: "none"`, `arm: "baseline"` and every flag false is accepted.
17. `compare` refuses the **same run directory named twice** and refuses two runs of one arm at the
    same `rep`; a study whose three off-runs are all `--rep 1` cannot compute `adopt`. A gated-arm
    run with no `rep` is refused naming the folder.
18. `worst_case_defects_lost` is `null`, and its cell reads `unknown`, for an unstable control arm,
    for either refused precondition and for a baseline row; it is `0` only where the comparison
    ran and found nothing.

## 10. What the implementation settled (T037-T045)

Everything below was decided while building `benchmark/runner.py`, `benchmark/compare.py`,
`benchmark/adoption.py` and the `compare` command, and is recorded here rather than in a
fifth contract file.

### 10.1 The provenance record is `run-provenance.json`

`RunProvenance` (`reviewer/src/swreview/benchmark/runner.py`), written by `cli.py` into the
**root** of the run directory beside `benchmark-set.json`, because it describes the whole
invocation rather than one package. Its fields: `commit`, `lever`, `arm`, `rep`,
`provider`, `model`, `effort`, `max_steps`, `checklist_digest`, `set_digest`, `started_at`,
`set_too_small_override` and the complete `efficiency` dump. A record carrying a field this
build does not know **fails loudly**, for the reason `EfficiencySettings` does; a run
directory with no record at all reads as `None` and renders with its four provenance
columns null.

`commit` is the short sha from `git rev-parse --short HEAD`, and is **null** outside a
checkout or when git cannot answer. Null, never a guess (Principle I).

`max_steps` is recorded as `DEFAULT_MAX_STEPS`, because `swreview benchmark run` exposes no
`--max-steps` option and its review path takes the default. If that option is ever added,
the recorded value has to come from it.

### 10.2 `set_digest` is the digest of the saved copy

The sha256 of the `benchmark-set.json` the run saved, **not** of the file `--set` named.
Two consequences, both wanted: the cross-check of section 3 can be run entirely inside the
run directory, and two set files that differ only in whitespace are one set.

### 10.3 The checklist digest is checked across a study, not against the session

`ReviewSession` carries no checklist digest and this feature added none - that would be a
contract edit on `review-session.schema.json` paid for one cross-check. The digest is
therefore recorded in the provenance record and compared **between the runs of a study**,
which is where it is load-bearing: a checklist that changed mid-study invalidates the pair.

### 10.4 The answer-keys path is not cross-checked

`scorecard.json` records no answer-keys path, so there is nothing to compare it against.
The guarantee that matters is asserted directly instead: a test records every path
`compare` reads and asserts none of them is under the answer-keys directory (section 9,
test 13). Principle VI and FR-025 stand.

### 10.5 The same-commit refusal is applied within a study

The provider and the model are part of the study key - one decision row per lever per
provider and model - so **two models are two studies, not a refusal**, and a `compare` over
an OpenAI study and a Gemini study renders two rows as section 5 asks. Within one study the
four fields that must be equal are `commit`, `effort`, `set_digest` and `checklist_digest`,
and the refusal names the one that differed. There is still no declared exception, lever 2
included.

### 10.6 Two exits, which are not the same thing

A **refused run** - two records that disagree, a session with no `efficiency`, two runs of
one study at different commits, a missing `scorecard.json` - aborts the whole ledger: exit
1 and nothing is written, because such a run may not be placed in a comparison at all. A
**refused decision row** (section 5) writes `ledger.json` and `ledger.md` with the raw rows
in them and then exits 1, because those runs are real and only the gate is unreadable.

### 10.7 The decision, and the two cases `re-measure` also covers

The rules fire in this order, which is normative because more than one can hold at once:
the two preconditions of section 5, then control-arm stability, then defects lost, then
false alarms, then the repetition count and the presence of a metric, then the threshold.
A quality failure therefore decides at any repetition count, while `adopt` is reachable
only from a full six-run study. Beyond the unstable control arm, `re-measure` is also the
computed value when **an arm holds fewer than three runs** and when **neither a
total-token nor a wall-clock median is in the scorecards**; neither may be `adopt`
(SC-009). The remaining detail of the rule - what "no new false alarm" compares, what the
threshold reads, and that a null is never a zero - is fixed in spec.md FR-028.

### 10.8 Columns the implementation added, and columns it deferred

- **`total_tokens` is a decision-row column in its own right**, because the threshold reads
  its delta and section 5's header list did not name it.
- **`OffOn` carries `off_rows` and `on_rows`**, the number of runs that contributed to each
  median. That is how section 4's "the row count is stated beside it" is implemented, and
  it is rendered as `n=` in the cell.
- **Reasoning and thoughts are named per provider in the cell, not in the header**: one
  header serves rows of both providers, so the row says which field it is quoting. The two
  are still never added together.
- **`unresolved_because_withheld` and `unresolved_other` are raw-row columns as of lever 4**
  (T060-T062): `PackageScore` carries both, the raw rows render both, and lever 4's
  `lever_counter` is the first of them. They split the **unresolved coverage items** and so
  sum to `coverage_bucket_mix["unresolved"]`, **not** to `unresolved_count`, which counts
  findings whose status is unresolved - section 8.1's "they sum to `unresolved_count`" names
  the wrong population and is the one line of this contract the implementation does not
  follow. The first half is set membership over `session.withheld_checks`, which the
  withheld tool records beside the item it writes; reading it out of the reason sentence
  would have made a rewording of that sentence a silent change to a measured number.
- **`coverage_bucket_mix` is read from `session.coverage`**, one source, because
  `PackageScore` does not carry it either.
- **`lever_counter` is `{name, off, on}`**, and the **name is always present** even when
  the numbers are null, so the column says *which* number is missing rather than going
  blank. Only lever 6's counter - tool calls beside round trips - is computable from what
  the scorecard and the session carry today; every other lever's arrives with that lever.
- **`median_net_saved_minutes` is a decision-row column as of feature 007** (T015-T016).
  One `adoption.METRICS` entry reading `scorecard.aggregate.median_net_saved_minutes`, one
  `OffOn` field, one header title and one `_lever_line` cell; the per-design median keeps
  printing in `scorecard.md` and is not moved. It is the **only** metric in that table the
  rule does not read, and it gates nothing by construction rather than by a guard, because
  `decide` names the two metrics the threshold rests on. Until the owner records the four
  inputs with `swreview timing`, every cell reads `unknown` with `n=0`, which is the honest
  answer and never `0`.

### 10.9 A six-run set is six directories at six repetitions

`adoption.MIN_REPS` counts the runs it was handed, which copies satisfy. `compare` therefore
refuses a run directory named more than once (resolved paths) and two runs of one arm sharing a
`rep`, and requires a `rep` on every `off` and `on` run. The refusal is in `compare`, not in the
adoption rule, because the rule reads scorecards and cannot see a folder or a command line.

### 10.10 The sign-off lives in the regenerated block and is carried through it

The alternative was a second, hand-kept table outside the markers. It was rejected: two tables
describing one ledger is the drift this feature exists to stop, and a sign-off that does not sit
beside the row it approves is not beside it at all. So the sign-off stays in the generated block,
and `compare` reads it back before re-rendering (section 5). The `Owner signed off at` column was
added at the same time, because FR-027 asks for a date and the field had no column to live in.

### 10.11 `--into` and `--check`: the committed document cannot drift

`docs/llm-efficiency-options.md` holds the ledger between the markers `<!-- ledger:begin
-->` and `<!-- ledger:end -->`. `swreview benchmark compare ... --into <file>` rewrites
what sits between them, and `--check` verifies it and writes nothing, exiting 1 when the
file has drifted. The run directories the committed table is rendered from live under
`benchmarks/studies/`, and a unit test regenerates the section from exactly those folders
and asserts byte-identity.

`compare` accepts **zero** run directories and renders the empty ledger. That is the
honest rendering of a feature that has measured nothing yet, and it is what the committed
document holds today.
