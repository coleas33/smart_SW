# Contract: The Pane Study's Verdict, the Simulator, the Pilot and the Cost Gate

Normative for FR-044, FR-045, FR-046, FR-058 and FR-059, the pane-study half of FR-016, FR-032 and
FR-052, the compare half of FR-056, FR-055, SC-005 and SC-010, User Story 8, and US5-5, US5-13 and
US5-14. Owner decisions 3A, 10A, 14A, 17A, 18A, 21A, 22A and 23A, and 35A and 36A (the smoke run and the projected wall clock, section 10); defaults D1, D2, D15, D16 and
D17; research §6, §8.1, §8.2, §8.10 and §8.13. Line numbers are at `be01974`; paths are under
`reviewer/src/swreview/` unless another root is given. Every example value is fictional.

What this contract fixes: how `swreview benchmark compare` turns the pane study's scored run folders
into one of three verdicts; the package-level interval every rule and every shown measure uses; the
order the rules are read in; what is refused before any verdict; the simulator that sets the levels
and the size and bounds both 5% rates; the paid off-arm pilot and the smoke run before it, the measurement they yield, with the study's
projected wall clock, and the owner's approval at the cost gate. It does not restate what other contracts own: run loading, the
must-match fields and the arms check (the compare contract), the scorecard's columns and origins
(the scorecard contract), run status and cost (the run-status contract), the set and its private
entries (the benchmark-set contract). Section 2 names each field this contract reads and who writes
it.

Amends feature 005's `contracts/ab-harness.md` sections 5 and 7: the pane study is not decided by
`adoption.decide` and none of its four rules applies to it (FR-045). A one-line pointer lands there
with the task that routes the study.

## 1. Shape

| Step | Command | Contacts a provider | Reads | Writes |
|---|---|---|---|---|
| Pilot runs | `swreview benchmark run`, the pane study's off arm, `--rep 1..n`, each into its own folder under `benchmarks/pilots/<study folder>/` (plan decision RF-36) | yes | the set, the packages | run folders, unchanged shape |
| Score them | `swreview benchmark score` | no | run folders, keys | `scorecard.json` |
| Measure and size | `swreview benchmark pilot <run dirs...> --out <file>` | **no** | the pilot's scorecards and sessions; the keys, through the scorer's loader, for the never-detected list only (section 10.2) | `pilot-measurement.json`, beside the pilot's folders |
| Approve | the owner edits the file's `approval` block by hand | no | | |
| Study runs | `swreview benchmark run`, both arms, alternated (ab-harness section 2), under `benchmarks/studies/<study folder>/` | yes | | run folders |
| Noise floor | `swreview benchmark noise-floor <run dirs...> --pilot <file> --out <file>`, once, after the last repetition is scored (section 9.7; plan decision RF-53) | **no** | the study's scorecards and saved sets, the pilot measurement | `noise-floor.json`, beside the study's folders |
| Verdict | `swreview benchmark compare <run dirs...> --pilot <file> --noise-floor <file>` | **no** | scorecards, provenance, sessions, the pilot measurement and its pilot runs' scorecards, the noise-floor record | `ledger.json`, `ledger.md` |
| Pack | `swreview benchmark pack <run dirs...>`, once a run is final: the pilot's folders before their commit with the approval (section 10.3), the study's after the last repetition, before their commit (section 9.7) (`provenance.md` 6.7; owner decision 28A) | no | `run-status.json`, each package's and attempt's `events.jsonl` | `events.jsonl.gz` in place of each plain stream, `event-streams.json` with each stream's digest |
| Reference check | `swreview benchmark simulate [--scenario <name> ...]` | no | nothing | stdout (and `--json`) |

Five modules, each pure where it can be:

| Module | Holds |
|---|---|
| `benchmark/stats.py` (new) | `t_quantile` over the t distribution function's closed-form series (section 4), `package_interval`, `mc_upper_bound`, the Gauss-Hermite rule and the intercept table |
| `benchmark/verdict.py` (new) | `StudyStats`, the sufficient statistics of one or many studies as arrays with a leading study axis; `judge(stats, rules)`, **the one implementation of the rule order** (section 5); `study_stats(runs)`, which builds `StudyStats` from loaded runs and keeps the ids the verdict names; the `PaneStudy` ledger model |
| `benchmark/simulate.py` (new) | Scenarios, simulated `StudyStats`, the level search, the size search; the noise-floor record's model and reader (the verdict slice) and the noise floor's computation (the pilot slice, which has the estimators it needs; plan decisions RF-37, RF-53) |
| `benchmark/pilot.py` (new) | `PilotMeasurement`, its `sizing_digest` and the reader compare uses (the verdict slice); the estimators, the never-detected list and the sizing search (the pilot slice; plan decision RF-37) |
| `benchmark/compare.py` | Routes the pane study to `verdict` instead of `_decision_row` (`:653-675`, which calls `decide`); the refusals of section 7; `--pilot`, `recorded_pilots()` and the pilot raw rows (section 10); `--noise-floor` and `recorded_noise_floors()` (section 9.7); the ledger block |

**One rule, two callers.** `compare` calls `judge` with one study; the simulator calls it with
4,000. Neither restates the order, so the bounds the simulator measures are the bounds of the rule
compare applies. Test V-25 holds the two paths equal.

**No new dependency.** The reviewer already depends on numpy (`reviewer/pyproject.toml:19`) and not
on scipy; the t distribution function, a closed-form series, and the quadrature are written here
(section 4) and pinned against published values.

## 2. What the verdict reads

Everything comes from files `compare` already reads (`benchmark/compare.py:300-326`); no key is
opened (feature 005 test 13, `reviewer/tests/unit/test_benchmark_compare.py:443-465`, extended to
the pane study).

| Quantity | Read from | Written by |
|---|---|---|
| Arm, repetition, start time, provider, model, study | `run-provenance.json` (`benchmark/runner.py:57-97`) | the compare contract (parity); the pane study's name and arms are its (PP-2, PP-3); written `<pane study>` below |
| The settings the arms differed in, and those recorded inert (FR-052) | provenance | the compare contract |
| Each package run's status: completed, bound-reached, behavioural stop (class), infrastructure failure (kind, class) | `PackageScore.run_status` and `bound_reached`, `Scorecard.unscored_packages` (`scoring.md` section 7) | the run-status contract (FR-036, D16), copied by the scorer (plan decision INT-9) |
| Per known defect: id, producer, tag (held out or tuned-on), detected (credited or flagged), cleared | the scorecard's per-package defect outcomes | the scorecard contract (FR-002, FR-005, FR-006, FR-031) |
| Per false alarm: finding id, origin (seven values; origin 3 as code-only or configured), whether it hit a tuned-on entry | the scorecard's per-package false-alarm records | the scorecard contract (FR-007, D9, D15) |
| The held-out model-produced count the keys name, before failures | the scorecard aggregate | the scorecard contract (FR-032, research §8.7) |
| Whether each session carries the origin-marks record | `session.json` | the scorecard contract (FR-007, research §8.5) |
| Every other scorecard column (FR-059) | the scorecard | the scorecard contract |
| Fit and axial-stack calls | `PackageScore.tool_calls_by_name` (`benchmark/scorecard.py:201`), for `check_fit` and `check_axial_stack` (`benchmark/compare.py:112-116`); the pre-run never calls either (ab-harness section 6, lever 5's row) | exists |
| Private entries | the saved set (`cli.py:2313-2314`): a package outside the repository | the benchmark-set contract (research §8.8) |
| Which packages take answer turns | the saved set's entries: a `case_file` beside a key holding a held-out item | the benchmark-set contract (`cases.md` 4.1) |
| The noise floor | the study's `noise-floor.json`, read, never simulated by compare (section 9.7) | `swreview benchmark noise-floor` (plan decision RF-53) |
| The pilot runs' raw rows | the scorecards of the folders the measurement's `pilot_runs` lists, under `benchmarks/pilots/` (section 10.6) | the paid pilot (plan decision RF-36) |

**Model-origin false alarms that decide** (17A, 20A, D15): per package run, the false alarms whose
origin is the model, or a check the model called of the configured kind, and which hit no tuned-on
entry. A false alarm hitting no entry at all counts. Every other false alarm is shown (section 6).

## 3. Figures, rates and drops

Two figures, each read with the same rules (FR-041, FR-058):

| Figure | A package run counts when its status is | Its detections | Its false alarms |
|---|---|---|---|
| Main | completed or bound-reached (D16) | as scored | as scored |
| Sensitivity | completed, bound-reached or a behavioural stop | as scored; a stopped run detects nothing (FR-041) | as scored from the state at the stop, "up to the stop" |

Infrastructure failures count in neither (D2). For figure `f`, arm `a` and package `k`, `n(k, a, f)`
is the number of counted runs.

- **Detection rate** of held-out model-produced defect `i` in package `k`: the share of its counted
  runs that detected it. A defect whose package has `n = 0` in either arm is **dropped from both arms
  of that figure**, counted and named (US8-11, FR-058).
- **False-alarm rate** of package `k`: its deciding false alarms per counted run. A package with
  `n = 0` in either arm is dropped from both arms of that figure's false-alarm rule, counted and
  named. The rule averages over **every** package of the study's set, clean twins and anchors
  included (FR-044).
- **Retained count**: the held-out model-produced defects left on each figure after drops. The floor
  (34, FR-028) is read on each figure separately (section 5, step 3).

## 4. The package-level interval

One implementation serves every rule and shown measure: `stats.package_interval(sums, weights,
alpha, sides)` is the 1-D wrapper over `prepare_package_intervals` and
`package_intervals_from_moments`, which the batched judge also uses. Units (defects for recall,
packages for false alarms and for every per-package
measure) are grouped into the `K` packages holding at least one retained unit. For package `k` with
`m_k` retained units and paired differences `d_u = on − off`:

```
S_k = sum of d_u over the package's units
D   = sum(S_k) / sum(m_k)                                  the estimate: the mean over units
SE  = sqrt( K/(K-1) * sum( (S_k - D*m_k)^2 ) ) / sum(m_k)  the package-level standard error
t   = t_quantile(K - 1, 1 - alpha)
one-sided at alpha:  upper = D + t*SE,  lower = D - t*SE
```

With every `m_k` equal this is the paired t interval on the package means; for false alarms and
per-package measures `m_k = 1` and it is exactly that. The ratio form keeps recall the mean over
defects (FR-044) when drops leave packages with one defect and others with two (research §6: pooled
recall equals the per-defect mean only when repetitions are equal).

- **Not computable** when `K < 2` or `SE = 0` (a zero-width interval, research §6). Recall: the
  verdict is inconclusive, saying why; false alarms: no loss, shown "not computable" (US8-9,
  RR-A8). In the verdict, equality of package means is tested exactly from integer counts,
  using common denominators and integer cross-multiplication before floating subtraction
  (112A). This applies to recall and false alarms; rounding cannot make an exactly equal
  collection computable. Statistics supplied as floating values retain their real small variance.
- **The quantile** (plan decision RF-34): the degrees of freedom are always `K − 1`, an integer, so
  the Student t distribution function is its closed-form finite series: with `θ = arctan(t/√ν)` and
  `A = P(|T| ≤ t)`, for even ν `A = sin θ (1 + ½cos²θ + (1·3)/(2·4) cos⁴θ + … + (1·3⋯(ν−3))/(2·4⋯(ν−2))
  cos^(ν−2)θ)` (Abramowitz and Stegun 26.7.4), for odd ν `A = (2/π)(θ + sin θ cos θ (1 + (2/3)cos²θ +
  … + (2·4⋯(ν−3))/(3·5⋯(ν−2)) cos^(ν−3)θ))` and `A = 2θ/π` at ν = 1 (26.7.3), and `F(t) = (1 + A)/2`
  for `t ≥ 0`. `t_quantile` bisects on it, bracketed by doubling from 1, to 1e-10; no continued
  fraction and no incomplete beta. Pinned (test V-1): `t(16, 0.975) = 2.119905`, `t(16, 0.99) =
  2.583487`, `t(16, 0.995) = 2.920782`, `t(33, 0.975) = 2.034515`, `t(50, 0.975) = 2.008559`,
  `t(4, 0.975) = 2.776445`; an offline check of the series reproduces all six to six decimals.
- **Why a t interval** (research §8.1): analytic, so it needs no resample seed and costs one
  evaluation per simulated study; the plain percentile bootstrap runs 3.3 to 5.1% per tail on
  identical arms (RR-B4). An offline check for this contract, 17 packages of 2, uniform rates,
  4,000 simulations, put it at 2.3 to 2.6% per tail at 3, 6 and 10 repetitions with a shock of SD 0
  or 1.0. It is not taken as calibrated: the level search absorbs whatever the scenario gives
  (section 9.5).
- **Shown measures** use the same function two-sided at 95% (2.5% per tail), a fixed constant
  printed beside them, named when the interval excludes zero (FR-016, FR-059).

## 5. The rules and the order

The paired rules, each at the approved one-sided level `alpha` (the same for all four, section
9.5):

| Rule | Figure | Estimate | Loss when |
|---|---|---|---|
| Recall | main, sensitivity | mean over retained held-out model-produced defects of on − off detection rate, in points | `upper < 0` |
| False alarms | main, sensitivity | mean over retained packages of on − off deciding false alarms per run | `lower > 0` |

The guards (FR-045, D17):

- **Code guard.** For each code-produced defect, held out or tuned-on, on the main figure: a loss
  when every counted off-run of its package detected it and at least one counted on-run did not,
  naming the defect and the on-runs. When the off-runs disagree the guard does not fire on it, and
  the defect is named "the off arm detected it only sometimes" (US8-3). A package with no counted run
  in either arm is named and skipped.
- **Cleared guard.** For each known defect: named when some on-run, completed or stopped, cleared it
  and no off-run did (clears before a behavioural stop count). It decides, for held-out items only,
  exactly when the approval record says it does (section 9.6); otherwise it is named and never
  decides (US8-4).

`judge` reads them in this order (research §8.10; D17; RR3-1):

1. Rates and drops per figure (section 3).
2. Every deciding rule on what remains, whatever the retained count: the four paired rules, the code
   guard, and the cleared guard where it decides. **Any loss gives `quality loss`**, every firing
   rule listed with its figure (US8-2, US8-12).
3. Otherwise, a retained count below 34 on either figure gives `inconclusive`, naming both counts
   and the drops that caused them (US8-13).
4. Otherwise, recall not computable on either figure gives `inconclusive`, saying which and why.
5. Otherwise, `no 10-point loss` needs the recall rule's lower end above −10 points on **both**
   figures; anything else is `inconclusive`, naming the figure and its lower end (US8-10).

Comparisons are strict: `upper < 0`, `lower > 0`, `lower > −10 points`. Reasons are constants a
reader can grep, as `adoption.py:64-72`'s are: `RECALL LOSS`, `FALSE-ALARM RISE`,
`CODE DEFECT LOST`, `CLEARED` (each suffixed with its figure where it has one), `BELOW FLOOR`,
`RECALL NOT COMPUTABLE`, `LOWER END AT OR BELOW -10 POINTS`. The verdict is one of
`quality loss`, `no 10-point loss`, `inconclusive`; a refused verdict is `null` with its reason,
an absence beside the enum and never a fourth value, as feature 005's refused decision is
(`benchmark/adoption.py:362-366`).

Nothing of `adoption.decide` applies (FR-045): no control-stability read (`adoption.py:214-226`),
no median false-alarm rule, no token or wall-clock threshold (`:60`; D1: the defaults are already
adopted), and no `LeverDecision` row for the pane study.

## 6. Shown, never deciding

Beside the verdict, per arm with the paired difference and its two-sided 95% interval, named when
it excludes zero (FR-059):

- every regression guard: recall on tuned-on model-produced defects; detection of code-produced
  defects; hits on tuned-on forbidden entries and correct conditions (US8-6);
- every other scorecard column, including false alarms by each origin with the model's code-only
  calls beside the pre-run's (US8-5, US8-15), flagged below expected, status mismatches, forbidden
  and withdrawn forbidden hits, coverage mismatches, unresolved coverage, unanswerable requests,
  re-asks seen and refused, repeats of open questions, unmatched requests, question-count misses and
  unscripted questions;
- bound-reached reviews per arm;
- fit and axial-stack calls per run (FR-016, 18A; US8-7): their fall is named, the verdict unchanged;
- failures by arm, kind and class, and behavioural stops by class;
- the noise floor (section 9.7);
- code-produced defects the off arm detected only sometimes; cleared defects and the runs that
  cleared them; held-out model-produced defects detected on every counted run of both arms, and on
  none;
- the settings the arms differed in and those recorded inert (FR-052; a Gemini study names parallel
  calls and dropped reasoning, D14.5);
- **the settings the verdict does not test** (plan decision RF-14): every setting the arms differed
  in that is in `BETWEEN_TURN_SETTINGS` (`agent/settings.py`, beside `INERT_SETTINGS`; today
  `drop_prior_reasoning`, which acts only at a turn boundary, `agent/settings.py:482-488`) and not
  recorded inert, when no saved-set entry whose key holds a held-out item names a case file: "acts
  only between turns; no held-out case takes an answer turn, so the verdict does not test it; the
  anchors show it". Under `cases.md` 3 (CS-9) that is every OpenAI pane study, owner question 8
  having been answered B (owner decision 30A); should core cases ever script answers, the list empties by itself.

A per-package measure's unit is the package; a per-defect one uses the ratio form of section 4. A
column the keys do not grade reads "not assessed" (FR-021) and gets no interval.

## 7. Refusals before a verdict

Run-level refusals stay the compare contract's and abort the whole ledger with exit 1, as today
(ab-harness 10.6): records that disagree, mixed must-match fields, repeated folders or repetitions
(`benchmark/compare.py:483-534, 749-766`), and another scorer version. The refusals below reject
the **verdict** only: the ledger is written with the raw rows, the pane block carries
`verdict: null` and the reason, and the command exits 1, as a refused decision row does
(`cli.py:2553-2570`). They are read in this order, and each message names what it read and the
rule:

| # | Refused when | The message names |
|---|---|---|
| 1 | an arm of the pane study has no run | the arm present and the one missing |
| 2 | a `pane_defaults` study's saved sets name a private package (the run-time rule of `provenance.md` section 3.2 already refuses one; this is the second reader) | the private entries; "a pane study's set holds committed cases only; the private slice is its own study, `pane_defaults_private`" (FR-056) |
| 3 | a session lacks the origin-marks record; a false alarm reads origin `unknown` because it cites a step its session does not hold (`scoring.md` 5.3 rule 4; plan decision SR-25); or a package's `run_status` is `not_recorded` (a run made before the robustness slice, whose figures cannot be told apart; INT-9) | the run, the package, the finding where there is one, and the command that re-runs it (FR-007, US1-12) |
| 4 | the keys name fewer than 34 held-out model-produced defects | the count and the floor (US5-5, FR-032) |
| 5 | no pilot measurement matches the study, or two do | the study key, and `--pilot` |
| 6 | the measurement's digest does not match its computed blocks | "the sizing was edited by hand; re-run `swreview benchmark pilot`" |
| 7 | its `approval.approved` is not `true`; `approved_at` is empty or not a valid `YYYY-MM-DD` date; or the approved sizing has no alpha or an unknown, nonfinite or out-of-range simulated rate | the file and the field; an approved sizing must supply a level and rates in `[0, 1]` |
| 8 | `approved_at` is later than the date of the earliest study run's `started_at` | both dates; "levels chosen after the paid runs void the 5% bounds" (research §8.1) |
| 9 | the keys' count is below the approved size; an arm has fewer distinct repetitions than approved; or the study's saved sets do not hold every package id the measurement's `sizing.pilot_packages` names plus at least `sizing.growth_units` core cases beyond them (a package outside `pilot_packages` whose `graded_items` hold a held-out known defect, so a twin, whose held-out items are conditions, is never a unit; plan decisions RF-40, RF-66) | the count, the repetitions, or the missing pilot packages and the growth units found, against the approval (US5-5, FR-032) |

A `pane_defaults_private` study is refused on rows 1 and 3 only, which its intervals need as much
as the verdict does; rows 2 and 4 to 9 do not apply to it: it is the private slice's study, shown
and never deciding (23A, section 11; plan decision RF-24).

**Pilot runs are never a study's** (plan decision RF-36, which supersedes RF-11's separation step).
The paid pilot's folders and its measurement live under `benchmarks/pilots/<study folder>/`, which
`recorded_runs()` never scans (it walks `benchmarks/studies/` for every `scorecard.json`,
`benchmark/compare.py:89, 769-779`), so a regenerated committed document never meets a pilot run
among a study's runs, and nothing has to be taken out before `_check_one_study` and
`_check_repetitions` (`:483-534`). The pilot's raw rows are rendered from the matched
measurement's `pilot_runs` list (section 10.6). A pilot folder typed among a study's run
folders meets the existing repetition and must-match refusals, as any stray run does.

## 8. Output

`ledger.json` gains `pane_studies`, one object per pane study, omitted when none was compared. The
ledger schema moves once for the whole feature (research §4, "one bump or two": one), to `1.1` in
the parity slice, whose schema record already names this key; this slice fills it and moves neither
the version nor the committed header (`provenance.md` section 5; plan decision INT-10).

```json
{"study": "<pane study>", "provider": "openai", "model": "<model>", "commit": "5733efd",
 "slice": "committed", "run_dirs": ["pane-openai/off-1", "..."],
 "reps": {"off": 6, "on": 6},
 "verdict": "inconclusive",
 "reasons": ["LOWER END AT OR BELOW -10 POINTS: sensitivity -11.2"],
 "refusal": null,
 "approval": {"file_sha256": "…", "approved_at": "2026-10-05", "alpha": 0.02,
              "held_out_model_defects": 36, "reps": 6, "cleared_guard_decides": false,
              "seed": 140514, "simulated": {"power_proportional": 0.83, "power_room": 0.87,
              "identical_loss": 0.036, "identical_loss_upper": 0.041,
              "no_loss_at_drop": 0.021, "no_loss_at_drop_upper": 0.025}},
 "figures": {
   "main": {"retained_defects": 36, "retained_packages": 47,
            "dropped_defects": [], "dropped_packages": [],
            "recall": {"estimate": -0.031, "lower": -0.092, "upper": 0.030, "alpha": 0.02,
                       "df": 17, "packages": 18, "computable": true, "loss": false},
            "false_alarms": {"estimate": 0.04, "lower": -0.11, "upper": 0.19, "alpha": 0.02,
                             "df": 46, "packages": 47, "computable": true, "loss": false}},
   "sensitivity": {"…": "the same shape"}},
 "code_guard": {"lost": [], "off_only_sometimes": [{"package_id": "…", "defect_id": "D-3"}],
                "skipped": []},
 "cleared_guard": {"decides": false, "named": []},
 "noise_floor": {"state": "computed", "points": 8.5, "seed": 140514, "numpy": "2.4.6"},
 "arms_differed_in": ["prerun_checks", "withhold_prerun_tools", "parallel_tool_calls",
                      "drop_prior_reasoning", "payload_slimming", "history_pruning"],
 "inert": [],
 "untested_between_turns": [{"setting": "drop_prior_reasoning",
                             "reason": "acts only between turns; no held-out case takes an answer turn, so the verdict does not test it; the anchors show it"}],
 "shown": [{"name": "fit and axial-stack calls per run", "off": 3.1, "on": 2.4,
            "estimate": -0.7, "lower": -1.3, "upper": -0.1, "level": 0.95,
            "excludes_zero": true}]}
```

Rates and intervals are stored as fractions and rendered in points; a null is `unknown` in the
markdown, never 0 (`benchmark/compare.py:806-810`).

`ledger.md` gains a `### Pane study` section **only when a pane study was compared**, so the
committed document's empty ledger (`docs/llm-efficiency-options.md:164-186`) keeps its bytes. The
section holds, per study: the verdict line and reasons; a table of the four paired rules (estimate,
interval, level, packages, retained defects, result); the two guards; the drops per figure; the
approval line (date, size, repetitions, `alpha`, cleared guard, seed, the simulated rates); the
noise floor with its seed; the settings the arms differed in, those recorded inert and those the
verdict does not test (section 6); and the shown table. That is User Story 8's scenario 1, item by
item.

**Reproducible** (FR-046, US8-8). The intervals are analytic, and compare draws no random number:
the noise floor is read from its record (section 9.7), simulated once with the approval's seed and
numpy's `PCG64` and stored with the numpy version that drew it. So the same folders, the same
measurement and the same record give the same `ledger.json` byte for byte on every supported Python,
although `reviewer/uv.lock` resolves numpy 2.4.6 on Python 3.11 and 2.5.3 on 3.12 and later
(`:776, 858`), whose distribution streams are not promised equal (plan decision RF-53).

## 9. The simulator (SC-005, SC-010, research §8.2)

### 9.1 A simulated study

Built as `StudyStats` directly, with a leading axis of `sims` studies, and judged by `judge`:

- **Layout**: packages each holding 0 to 2 held-out model-produced defects, plus clean-twin
  packages holding none. Reference (SC-010, as the spec fixes it): 17 packages of 2 defects and 34
  twin packages, growing as packages of 2 defects and 2 twins. After the pilot: the committed set's
  own layout, read from the saved set and the scorecards' `graded_items`, growing by its own unit,
  one core case and the twins whose `twin_of` names it (2 defects and 1 twin under `cases.md`'s twin
  rule B; plan decision INT-4).
- **Off-arm rates**: reference `half` (every rate 0.5), `uniform` (each drawn from U(0, 1) per
  simulated study), `polar` (13 at 0, 13 at 1 and 8 at 0.5 of 34; defects added as cases grow are drawn from the
  same three-point distribution, 3/8, 3/8 and 1/4);
  after the pilot, drawn from its Beta fit (section 10.2). Placed in packages at random, per
  simulated study, with the seed.
- **Marginal rates** (RR4-2). A stated rate is the defect's expected detection over the shock. Per
  defect and arm the intercept `a` solves `E[logistic(a + sigma*Z)] = p`, `Z` standard normal, by a
  40-node Gauss-Hermite rule (`numpy.polynomial.hermite_e.hermegauss`). Solving per simulated defect
  is too slow (an offline check: about 12 s per 4,000 studies), so `stats.intercept_table(sigma)`
  solves once on 3,999 rates `j/4000` inside (0, 1) and `numpy.interp` reads it. Against independent
  160-node quadrature, measured marginal-rate error is below `2.5e-5` inside
  `[1/4000, 3999/4000]` on the SD grid 0, 0.25, …, 2.5 (worst measured `2.14381e-5`). Positive
  rates outside that range clamp to its endpoints; error approaches `2.5e-4` at 0 and 1
  (`p=1e-6` gives `2.49e-4` at SD 0). The interpolation is retained to preserve seeded outputs
  (111A, 112A), at about 50 ms per 4,000 studies. Rates of exactly 0 and 1 are never and always,
  whatever the shock. Identical arms share each intercept.
- **Shock**: one `N(0, sigma^2)` logit shock per package run, independent across runs and arms.
- **Detections**: each defect in each run, `uniform < logistic(a + shock)`.
- **The drop**: `D = 10` points in mean detection over the `n` held-out model-produced defects, in
  marginal terms, then intercepts re-solved for the on arm. **Proportional**: defect `i` falls by
  `D * p_i / mean(p)`. **Room**: the total `n * D` shared equally among defects with `p_i > 0`; any
  defect whose share exceeds what it has left falls to 0 and leaves the pool, and the rest of the
  total is re-shared equally, until no share exceeds a rate. Example (test S-1): rates 0, 0.05, 0.5,
  0.9 at `D = 0.10` become 0, 0, 0.325, 0.725. A shape whose total exceeds what the rates hold
  (`mean(p) < D` for proportional, `sum(p) < n*D` for room) is excluded **per simulated study**
  (112A). Its excluded share is printed when nonzero (omitted means zero). A shape is printed
  "not attainable" only when no simulated study can take its drop. Exclusion retains the original
  random draw order for the remaining studies.
- **False alarms** per package run: negative binomial with mean `m` and size `k` (variance
  `m + m^2/k`), drawn as Poisson of a Gamma(`k`, `m/k`) rate per package run, or Poisson(`m`). Equal
  in both arms, under the null and under the drop.
- **Behavioural stops** (when the scenario has them): a Bernoulli per package run and arm. A stopped
  run leaves the main figure; in the sensitivity figure it detects nothing and keeps a binomial
  thinning of its false alarms at a fraction drawn from U(0, 1) (FR-041).
- **Clearances**: a Bernoulli per chosen defect, run and arm, independent of detection.
- **Code-produced defects** (21A): the on arm detects each on every run; the off arm at its rate.

### 9.2 Reference scenarios (SC-010)

36 main scenarios: three rate distributions × shock SD 0 or 1.0 × false-alarm mean 0.2, 1 or 3 ×
size 0.5 or Poisson, with no stops, clearances or code-produced defects. Three more, each adding one
thing to `uniform`, SD 1.0, mean 1, size 0.5: stops on 5% of runs per arm; 10 held-out defects each
cleared on 5% of runs; 10 code-produced defects the off arm detects on 95% of runs. 4,000
simulations each, the seed fixed in the test. Each is named, for example
`uniform-sd1.0-fa1-nb0.5-clear`, and `--scenario` takes those names.

### 9.3 What is measured at one size and one level

- **Identical-arms loss rate**: the share of null studies whose whole verdict is `quality loss`.
- **Power** under each drop shape: the share of drop studies in which the recall rule on the main
  figure calls a loss (spec Terms).
- **No-loss-at-drop rate** under each shape: the share of drop studies whose verdict is
  `no 10-point loss`; the higher of the two shapes governs.

Power and no-loss-at-drop are conditional on the studies that can take that shape's drop.
Each shape uses its own attainable count as its rate and Wilson-bound denominator. The larger
of the two shapes' rates, and separately the larger of their upper bounds, govern (with different
denominators the two can come from different shapes, which is conservative); the identical-arms
rate still uses all `sims` studies.

### 9.4 The Monte Carlo bound

`stats.mc_upper_bound(hits, n)`: the one-sided 95% Wilson score upper bound,
`(p + z²/2n + z·sqrt(p(1−p)/n + z²/4n²)) / (1 + z²/n)` with `z = 1.6448536`. A rate holds its 5%
bound when this is at most 0.05: at 4,000 simulations 176 hits (4.4%) pass at 0.0496 and 180 (4.5%)
fail at 0.0507 (test V-5), research §8.2's "about 4.4% or less".

### 9.5 The level search and the size search

- **Levels**: one `alpha` for the four paired tests, from the ladder 0.025, 0.02, 0.015, 0.01,
  0.005, 0.0025. At a size, the chosen `alpha` is the loosest on the ladder at which both bounds
  hold (identical-arms loss, and no-loss-at-drop under the higher shape). Tightening helps both and
  costs power (research §8.1). No `alpha` on the ladder passing is a failed size.
- **Size**: repetitions from 3 up to the cap (10 unless the owner sets another at the cost gate,
  22A), one at a time, at the current layout; the first size whose chosen `alpha` gives power of at
  least 80% under **both** shapes is the answer. At the cap, cases grow one growth unit at a time
  (9.1: 2 defects and 2 twins in the reference scenarios, the committed unit after the pilot), up to
  200 held-out model-produced defects, beyond which the search prints "not reached". The size is
  never below 34 defects or 3 repetitions (SC-005).
- Every size tried is printed: repetitions, packages, defects, the chosen `alpha` or "none", both
  powers, both rates with their upper bounds.

### 9.6 The cleared guard's place

At the size the search found, with the guard named only, the search is run again at that size with
the guard deciding. It decides only when some `alpha` on the ladder holds both bounds **and** power
stays at 80% or more under both shapes; the approval then carries that `alpha`. Otherwise it is
named only. The printout says which and why (research §8.1, RR2-5). The guard has no level of its
own, so at SC-010's clearance scenario its null rate alone is
`1 − prod(1 − (1 − (1 − q)^R)(1 − q)^R)` over the 10 defects, `q = 0.05`: 0.729, 0.885 and 0.936 at
3, 6 and 10 repetitions; the simulator is expected to print "named only", and the test checks the
simulated rate against that closed form (RR-B3).

The code guard adds nothing to the null rate: the on arm detects every code-produced defect (21A,
FR-054). The **stress case**, both arms at the off arm's rate, is printed and never bounded:
`1 − prod(1 − p_j^R (1 − p_j^R))` over the code-produced defects; at SC-010's ten at 0.95 it is the
same 0.729, 0.885 and 0.936 (test S-5).

### 9.7 The noise floor (spec Terms, D14.8)

On the study's own layout and counted repetitions, each defect at its own off-arm rate shrunk by the
study's Beta fit (section 10.2), the shock at the study's plug-in estimate, the approved `alpha` and
seed, and 4,000 simulations: the smallest drop on a 0.5-point grid from 0.5 to 50 points whose power,
under the lower of the attainable shapes, is at least 80%. "Above 50 points" or "not attainable"
otherwise.

**Simulated once, stored, read** (plan decision RF-53). `swreview benchmark noise-floor <run
dirs...> --pilot <file> --out <file>` computes it after the study's last repetition is scored, and
writes `noise-floor.json` beside the study's folders through `write_atomic`: `noise_floor_schema` 1;
the study key (study, provider, model); `runs_digest`, `digest.canonical_sha256` over the sorted
pairs of each study run's folder, relative to the file with `/`, and the `canonical_sha256` of its
parsed `scorecard.json`, never the file's raw bytes: `benchmark score` writes a scorecard with
`write_text` (`cli.py:2382`), so the Windows working copy that wrote it holds CRLF while every
checkout of the committed file holds LF (`benchmarks/** eol=lf`), and a raw digest would read
"stale" everywhere but the writer's copy (plan decision RF-56); the seed, the simulations, the
grid and `numpy_version`; and the result. It refuses runs that are not one pane study's two arms,
an unscored run, and an existing `--out`. Compare reads the record, through `--noise-floor <file>` or
`recorded_noise_floors()`, which finds every `noise-floor.json` under `benchmarks/studies/`, matched
by the study key, and simulates nothing: with no matching record the pane block reads the noise floor
"not computed: run swreview benchmark noise-floor", and with a record whose `runs_digest` differs
from the compared runs' it reads "stale: computed over other runs"; two records matching one study
are named on one line and the noise floor reads "not computed" until one is removed; none of these
refuses anything, since the noise floor is shown and never decides (FR-059). The record is committed
with the study's folders, their event streams packed first (`provenance.md` 6.7; owner decision 28A;
quickstart P4). Neither `benchmark noise-floor` nor `benchmark pilot` reads a stream: both read
scorecards, saved sets and sessions, so packing moves neither the record nor the measurement.

### 9.8 The command

`swreview benchmark simulate [--scenario <name> ...] [--seed <n>] [--cap <n>] [--sims <n>] [--json]`.
With no scenario it runs all 39. For each it prints every input with its value or source (the rate
distribution, the shock, the marginal-rate rule, the layout, the false-alarm model, stops,
clearances, code-produced defects, the drop and both shapes, the ladder, the deciding rules,
simulations, seed, cap, numpy version) and then the search of section 9.5, the cleared guard's
place, the stress case where there are code-produced defects, and the result. Exit 0; a scenario
that reaches no size within 200 defects is printed, not an error.

## 10. The pilot and the cost gate (FR-055, 14A, 22A)

### 10.1 The pilot runs

The pane study's off arm (all levers off, the explanation setting stated, PP-2) over the pane
study's committed set, with the study's provider, model and effort, each repetition its own
`benchmark run --study <pane study> --arm off --rep <n>` into its own folder under
`benchmarks/pilots/<study folder>/`, a folder `recorded_runs()` never scans (plan decision RF-36), then
scored. Three repetitions over the whole committed set (owner decision 27A). The name clashes with nothing but reads close to the
product pilot's `benchmarks/sets/pilot.json`; this contract always says "the paid pilot" where the
two could be confused.

**The smoke run before it** (quickstart P0; owner decision 35A; plan decision RF-89): the pane
study's two arms, one repetition each, over `benchmarks/sets/pane-smoke.json` (`kalo-1`, a held-out
core case, and `kalo-fit-1`, the anchor with a case file), with the pilot's provider, model, effort,
explanation setting and profile and the `--jobs` the owner plans, into
`benchmarks/pilots/<study folder>/smoke-off` and `smoke-on`. Every row is read before the pilot, and
any wiring is fixed, failing test first, after which P0 runs again from the fix's commit. The pilot
runs from the commit of the P0 that passed. The two folders are kept, packed and committed with the
pilot's, and are a time input only (section 10.2's projection): no rate, fit or count reads them, and
the ledger never renders them.

### 10.2 The measurement

`swreview benchmark pilot <run dirs...> --smoke <folder> --smoke <folder> --out <file> [--cap <n>]
[--seed <n>] [--jobs <n>]` loads the runs, and the smoke run's two, with
compare's loader and study checks (`benchmark/compare.py:300-326, 483-534`), and refuses runs that
are not the pane study's off arm, fewer than 2 repetitions ("co-movement needs at least two runs of
a package"), an unscored run, or an `--out` that already exists ("{out} exists: one study has one
measurement; delete the unapproved file to size again", plan decision RF-40); and `--smoke` given
other than twice, or naming anything but one `--arm off` and one `--arm on` run of the same pane
study at the pilot runs' provider, model, effort and commit, over a saved set every pilot run's saved
set holds, each scored with every package kept (naming the folder and the field; owner decisions
35A and 36A). `--jobs` below 1 is a usage error, exit 2. It measures, over
completed runs:

- **Per held-out model-produced defect**: detections `x_i` over counted runs `n_i`. A defect with
  `n_i = 0` (its package has no counted run, after infrastructure failures) is dropped, counted and
  named in `measured`, as section 3 drops it.
- **The rate distribution**, Beta by moments with the binomial noise taken out: `mu = sum(x)/sum(n)`
  over the defects with `n_i >= 1`; `V = var(x_i/n_i) − mean(r_i(1 − r_i)/(n_i − 1))` over the
  defects with `n_i >= 2` only, `r_i = x_i/n_i`, since the correction divides by zero at `n_i = 1`;
  each defect left out of `V` is named and counted in `measured` (plan decision RF-9). Fewer than
  two defects with `n_i >= 2` gives `V` not computable, read as the `V <= 0` branch below (the least
  favourable to power) and said so. `a + b = mu(1 − mu)/V − 1`. `V <= 0` gives
  every rate `mu` (no spread; the least favourable to power); `V >= mu(1 − mu)` gives rates of 0 or
  1 with `P(1) = mu` (the polarised limit).
- **Co-movement**: for each shock SD on the grid 0, 0.25, ..., 2.5, the marginal log-likelihood of
  the observed detection vectors of every package run, each defect's intercept solved from its
  shrunk rate `(a + x_i)/(a + b + n_i)` at that SD, integrated by the same Gauss-Hermite rule. The
  estimate is the maximum; **the SD used for sizing** is the largest grid value within the 80%
  profile-likelihood limit, `2(l_max − l(sd)) <= 1.6424` (research §8.13, how the pilot's noise
  enters: co-movement is the least well measured input and the one that costs most power, so sizing
  takes its upper plausible value; the rates are already shrunk).
- **Code-produced defects**: the off arm's detection rate of each, for the stress case.
- **Behavioural stops**: stops per package run, pooled. **Clearances**: per defect, cleared runs
  over counted runs, with the defects named.
- **False alarms**: deciding false alarms per package run, mean `m` and variance `v`: negative
  binomial with `k = m²/(v − m)` when `v > m`, else Poisson(`m`).
- **Cost and time**: mean priced cost and mean wall clock per package run, from the run-status
  contract's cost; a package run with unknown cost is named and left out of the mean, and the line
  says how many were.
- **The projected wall clock** (owner decision 36A; plan decision RF-91), `pilot.project_wall_clock`:
  a package's off-arm time is its mean `wall_clock_s` over its counted pilot runs; its on-arm time is
  that times the smoke ratio, the sum of the smoke run's on-arm package times over the sum of its
  off-arm ones; a growth package (section 9.5) takes the mean off-arm time of the committed core
  cases and twins; one run's wall clock is the list schedule of its packages' times in set order on
  `--jobs` slots, each package starting on the first slot to free, which is the schedule
  `benchmark run --jobs` runs (`benchmark-run.md` section 5.4); the study's is the approved
  repetitions times one off run plus one on run, the runs one at a time and the arms alternated. A
  package with no counted pilot run makes the projection unknown, naming it, never 0. Printed per run
  and for the study, with the ratio's two sums and the mean tokens per minute of one off-arm review
  (its input and output tokens over its wall clock), so that N times it can be held under the
  account's limit (plan risk RK-18).
- **Never detected** (US5-14): each held-out defect no pilot run detected, with every finding, of any
  check and status, on its parts or documents in those runs, found with the scorecard contract's
  part-and-document overlap and its key loader (FR-003's first test, without the check and
  reference tests), so the owner can tell a hard defect from an unmatchable key.

Then it runs the search of section 9.5 on those inputs over the committed layout, at the cap, with
the seed (default: drawn once and recorded).

### 10.3 `pilot-measurement.json`

Written beside the pilot's own run folders (`benchmarks/pilots/<pane study folder>/` for a committed
study; plan decision RF-36), through `write_atomic`, holding no absolute path (FR-051); run folders
are named relative to the folder the file sits in. The model, `sizing_digest` and the reader land
with the verdict slice, tested against hand-written files; the estimators and the search that fill
it land with the pilot slice (plan decision RF-37).

| Block | Holds |
|---|---|
| identity | `pilot_schema`, study, provider, model, commit, `set_digest`, scorer version |
| `pilot_runs` | each pilot run's folder (relative), arm, repetition, `started_at` and commit |
| `smoke_runs` | the smoke run's two folders (relative), arm, repetition, `started_at` and commit (owner decisions 35A and 36A) |
| `measured` | section 10.2's inputs and the never-detected list |
| `sizing` | the cap, floor, seed, simulations, ladder; every size tried; `pilot_packages`, the package ids of the paid pilot runs' saved sets (the committed set at the pilot's commit), sorted, never `benchmarks/sets/pilot.json`'s (section 10.1); the result: repetitions, packages, held-out model-produced defects, `growth_units` (the core cases, each with its twin, to add; 0 when none), `alpha`, the deciding rules, whether the cleared guard decides, both powers, both bound rates with their upper bounds, the stress case, the estimated study cost (the off arm's mean package-run cost for both arms, an upper estimate); `jobs`, the concurrency the projection assumes, and `projected_wall_clock` (per arm one run's projected seconds, the study's, the smoke ratio and its two sums, and the mean tokens per minute of one off-arm review; 36A) |
| `sizing_digest` | `digest.canonical_sha256` (sorted keys, no whitespace, UTF-8) of every block but `approval`: identity, `pilot_runs`, `smoke_runs`, `measured` and `sizing`, so an edit to any computed block is refused (plan decisions RF-56, RF-65) |
| `approval` | `{"approved": false, "approved_at": null}` as written; **the owner's act, never computed** |

The command prints the cost gate: the size, repetitions, deciding rules, `alpha`, the cleared
guard's place, the stress case, the cost, the projected wall clock at `--jobs`, and the growth units
to add (US5-13). The size was
searched over the grown layout, so approving it approves the growth: the owner approves the printed
size, the growth units are written as case specs, generated and validated (`cases.md` 6.5 and 7), and
they are committed in one commit with the pilot's folders, their event streams packed
(`provenance.md` 6.7; owner decision 28A), and the approved measurement, with no second paid pilot; refusal 9 holds the study's sets to the pilot's packages plus those units (plan
decision RF-40). If the owner sets another cap before approving, they delete the unapproved file and
re-run `benchmark pilot` with `--cap` over the same folders; an existing file is never overwritten,
so one study never has two measurements (refusal 5). The owner chooses the study's concurrency the
same way, re-running with `--jobs` before approving; `jobs` is record-only in the runs
(`provenance.md` section 4), so a study run at another N is refused nothing, but the approved
projection assumes the recorded one.

### 10.4 The approval

The owner writes `"approved": true` and the date into `approval`, and nothing else; the computed
blocks are the feature 005 rule's "computed, not typed" (ab-harness section 5). Compare recomputes
`sizing_digest` and refuses a mismatch (section 7, refusal 6). Pilot runs are never study runs
(research §9.7, question 6, the default kept): they live under `benchmarks/pilots/`, which `recorded_runs()` never scans, so they
never meet a study's run-level checks (section 7; RF-36).

### 10.5 Where compare finds it

`--pilot <file>`, repeatable, matched to a study by study, provider and model. For the committed
document, `recorded_pilots()` finds every `pilot-measurement.json` under `benchmarks/pilots/` (plan
decision RF-36), as `recorded_runs()` finds scorecards under `benchmarks/studies/`
(`benchmark/compare.py:769-779`), and `recorded_noise_floors()` every `noise-floor.json` under
`benchmarks/studies/` (section 9.7); the byte-identity test
(`reviewer/tests/unit/test_benchmark_compare.py:993-1005`) passes all three. A measurement matching no
compared study prints one line, naming the file and its study key, and refuses nothing (test
C-15).

### 10.6 Pilot runs in the ledger

Rendered from the matched measurement's `pilot_runs` list: each listed folder, relative to the
measurement's, is loaded with compare's loader and rendered as a raw row; never in a verdict, a
decision row, a repetition count or a study's run-level checks. The mark sits inside `provenance.md`
5's fixed run columns, which this slice does not move: the arm cell reads `off (pilot)` (plan
decision RF-36). A listed folder that is missing or unscored is named on one line and refuses
nothing. The measurement's `smoke_runs` are never rendered: they are the projection's time input,
not pilot repetitions (owner decision 35A).

## 11. The private slice (23A, FR-056)

The study `pane_defaults_private` (`provenance.md` section 3.1; the slice is read from the study
name, never inferred from the saved sets, plan decision INT-13) renders as its own row with
`slice: "private"`: every interval, guard and shown measure of sections 5 and 6 at the shown level,
`verdict: null` and the reason "private slice (23A): shown beside the pane study's verdict, never
deciding". Refusals 1 and 3 apply to it; 2 and 4 to 9 do not (section 7; RF-24). Its runs and
page never enter the repository (FR-051, D12).

## 12. Tests

Hand-built scorecards and provenance, like `reviewer/tests/unit/test_adoption_rule.py`; no key, no
provider, no SOLIDWORKS.

`test_benchmark_stats.py`:
- V-1 `t_quantile` equals the six pinned values to 6 decimals, through the closed-form series for
  odd and even degrees of freedom and `ν = 1` (FR-044; RF-34).
- V-2 with equal weights `package_interval` equals the paired t interval on package means; with
  weights 1 and 2 it equals a hand-computed ratio estimate and standard error.
- V-3 `K = 1` and `SE = 0` give not computable (US8-9).
- V-4 the intercept table: measured marginal error under `2.5e-5` over the whole knot range on
  the SD grid 0, 0.25, …, 2.5, against independent quadrature; positive tails clamp, explicitly
  tested at `1e-6` and `1-1e-6`; SD 0 is the logit at knots; 0 and 1 are never and always.
- V-5 `mc_upper_bound(176, 4000)` passes and `(180, 4000)` fails the 5% bound.
- V-26 invalid inputs refuse with a `ValueError` naming them (RF-9): `t_quantile` with degrees of
  freedom 0 or below and with a probability outside (0, 1); `package_interval` with `alpha` 0,
  below 0 or above 0.5, and with weights of another length than the sums; `mc_upper_bound` with
  `n = 0`, negative hits or hits above `n`.

`test_benchmark_verdict.py`, each through `study_stats` and `judge`:
- V-6 a code-produced defect detected on every completed off-run and missed on one completed on-run:
  `quality loss`, naming the defect and run, whatever else holds (US8-2).
- V-7 off-runs that disagree on a code-produced defect: named "only sometimes", the guard silent,
  and not by itself inconclusive (US8-3).
- V-8 a held-out defect cleared on one on-run and no off-run: named; `quality loss` only when the
  approval makes the guard decide (US8-4).
- V-9 unchanged model-origin false alarms, on-arm pre-run false alarms up: shown and named, verdict
  unchanged (US8-5).
- V-10 a tuned-on forbidden hit: in the regression guards, outside the deciding figure (US8-6).
- V-11 fewer fit and stack calls on the on arm: shown with its interval, named, verdict unchanged
  (US8-7, FR-016).
- V-12 a zero-width recall interval: inconclusive, saying why; a zero-width false-alarm interval: no
  loss, "not computable" (US8-9).
- V-13 a recall interval of −18 to +4 points: inconclusive, never `no 10-point loss` (US8-10).
- V-14 an infrastructure failure in one arm: rates over completed runs; a defect whose package has
  none dropped from both arms, counted and named (US8-11).
- V-15 behavioural stops: no loss on the main figure, a loss on the sensitivity figure:
  `quality loss` (US8-12).
- V-16 drops below 34 on one figure and no deciding loss: inconclusive naming both counts; the same
  with a code-guard loss: `quality loss` (US8-13, RR3-1).
- V-17 the median of false alarms up while the paired interval includes zero: no loss (US8-14).
- V-18 an off-arm code-only call hitting a held-out forbidden entry: a code-origin false alarm,
  shown beside the pre-run's, not deciding (US8-15).
- V-19 a bound-reached review counts in the main figure (D16).
- V-20 an unstable off arm gives no `CONTROL UNSTABLE`, no `LeverDecision` row, and no threshold
  is read (FR-045).
- V-21 a Gemini study names the settings the arms differed in and those recorded inert (FR-052).
- V-22 the ledger block names both differences with intervals, the sensitivity figure, both guards,
  the rules and `alpha`, the simulated rates, the noise floor and its seed, and the shown table
  (US8-1).
- V-23 comparisons are strict: an upper end of exactly 0, a lower end of exactly −10 points.
- V-24 a per-package shown measure the keys do not grade reads "not assessed", with no interval.
- V-25 for 200 small random studies from a fixed seed, the verdict from `study_stats` of written
  scorecards equals the simulator's `judge` on the same detections (one rule, two callers).
- V-27 an OpenAI pane study whose held-out entries name no case file lists `drop_prior_reasoning`
  under `untested_between_turns` with its reason; the same study with a case file on a held-out
  entry lists nothing; a Gemini study lists it under `inert` only (RF-14).

`test_benchmark_compare_pane.py`, through the command:
- C-1 to C-9 each refusal of section 7, the ledger still written with the raw rows, exit 1, the
  message naming what the table says (US5-5, FR-032, FR-056, FR-007, US1-12); C-3 three times: a
  session without the record, a false alarm citing a step its session does not hold (SR-25), and a
  `not_recorded` run status; C-6 twice: `sizing` edited and `pilot_runs` edited (RF-65); C-9 four
  times: the keys' count below the approved size, an arm short of the approved repetitions, a saved
  set missing a `pilot_packages` id or holding fewer than `growth_units` new core cases (RF-40), and
  one core case with its twin added where two units are approved (RF-66). C-5 to C-9 run against hand-written measurement files, in
  the verdict slice (RF-37).
- C-10 an all-private study renders the private row, no verdict, exit 0 (23A).
- C-11 a measurement under a temporary `benchmarks/pilots/` listing three pilot runs beside it, at
  repetitions 1 to 3 and an earlier commit: `recorded_runs()` over the temporary `benchmarks/studies/`
  finds none of them, the study's checks pass, and the pilot runs render as raw rows read from
  `pilot_runs`, arm cell `off (pilot)`, in no count; a listed folder that is missing is named and
  refuses nothing (sections 7, 10.4, 10.6; RF-36).
- C-12 the same folders compared twice give identical `ledger.json` bytes (US8-8, FR-046).
- C-13 compare opens no file under any key path the sets name (Principle VI).
- C-14 the committed document regenerates byte-identically with `recorded_pilots()` over
  `benchmarks/pilots/` and `recorded_noise_floors()`, and an empty ledger's markdown is unchanged by
  the verdict slice's code (the parity slice's one regeneration already moved its header).
- C-15 a measurement matching no compared study prints one line naming it and its study key, and
  refuses nothing (section 10.5).
- C-16 a `pane_defaults_private` study missing an arm is refused on row 1, and one holding a session
  without the origin-marks record on row 3; the same study with both arms and the record renders its
  row with no refusal from rows 2 and 4 to 9 (section 7; RF-24).
- C-17 the noise floor (section 9.7; RF-53): a hand-written record matching the study renders its
  points, seed and numpy version, and compare calls no simulation (a spy on `benchmark/simulate.py`'s
  search); no record renders "not computed", a record whose `runs_digest` differs renders "stale",
  two records for one study are named and render "not computed", and none refuses anything; the same
  folders and record compared twice give identical bytes.

`test_benchmark_simulate.py` (default run):
- S-1 the drop shapes: the room example of section 9.1; the mean drop is exactly `D` under both; an
  unattainable shape is printed "not attainable".
- S-2 marginal rates: at SD 1.0 simulated detection means match the stated rates within Monte Carlo
  tolerance, and a drop from 0.5 to 0.4 is 10 marginal points (RR4-2).
- S-3 false alarms: simulated mean and variance match `m` and `m + m²/k`; the Poisson branch.
- S-4 printed inputs: every input of section 9.8 is present with its value or source (SC-010).
- S-5 the stress case and the cleared guard's null rate match their closed forms at 3, 6 and 10
  repetitions within tolerance; the clearance scenario prints "named only" (RR-B3, RR2-5).
- S-6 the level search tightens `alpha` when a bound is exceeded, and never loosens past 0.025.
- S-7 `half`, SD 1.0 reaches the cap of 10 and grows cases (SC-010); a `--cap 6` search stops
  repetitions at 6 (22A); a search that grows cases records how many growth units it added.
- S-8 the same seed gives the same printout; the size never falls below 34 × 3.
- S-9 the uniform co-moving clearance and code-defect scenarios and `half`, SD 1.0, at 4,000
  simulations, hold both bounds at the chosen size and `alpha`.

`tests/simulation/test_reference_scenarios.py`, collected only when `-m simulation` names it, as
`tests/perf/` is gated (`reviewer/tests/conftest.py:39-66`):
- S-10 all 39 scenarios: both 5% bounds held at the chosen size and `alpha`, power of at least 80%
  under both attainable shapes, every size tried printed; and every `half-sd1.0-*` scenario (the six
  of SC-010's "every-0.5 scenarios with shock SD 1.0") reaches 10 repetitions and then adds at least
  one growth unit (SC-010). Run before any approval.

`test_benchmark_pilot.py`:
- P-1 the Beta fit recovers `(a, b)` from simulated pilot data within tolerance; `V <= 0` and
  `V >= mu(1 − mu)` take their stated branches.
- P-9 counted runs per defect (RF-9): a defect with one counted run enters `mu` and is left out of
  `V`, named and counted in `measured`; a defect with none is dropped, named and counted; fewer
  than two defects with two or more counted runs reads `V` not computable, taken as the `V <= 0`
  branch and said so; no division by zero anywhere.
- P-2 the co-movement grid recovers SD 0 and 1.0 from simulated pilot data (34 defects, 5
  repetitions) within one grid step, and the SD used is at least the estimate.
- P-3 the false-alarm fit takes the negative-binomial and Poisson branches.
- P-4 a never-detected defect is listed with the findings on its parts and documents under other
  checks (US5-14).
- P-5 refusals: runs not of the pane study's off arm; one repetition; an unscored run; mixed commits
  (compare's own check).
- P-10 an existing `--out` is refused naming it, approved or not, and nothing is written (RF-40).
- P-11 `sizing` records `pilot_packages`, equal to the sorted package ids of the saved sets of the
  runs `pilot_runs` lists (never `benchmarks/sets/pilot.json`'s), and `growth_units`, equal to the
  growth units the size search added, 0 when it added none (RF-40).
- P-6 the written file holds an unapproved block, a digest that verifies, and no local absolute path
  (FR-051's test over it).
- P-7 a package run with unknown cost is named and the cost line says how many were left out.
- P-13 the projected wall clock (owner decision 36A): over hand-built pilot and smoke runs whose
  `wall_clock_s` are chosen, the off-arm times are the pilot means, the on arm's the off times by the
  smoke ratio (printed with its sums), a growth package's the core cases' and twins' mean; five
  packages of 10, 40, 20, 30 and 10 s schedule to 110 s at `--jobs` 1, 60 s at 2, 40 s at 3 and 40 s,
  the longest, at 5 or more; the study's is the repetitions times one off and one on run; a package
  with no counted run makes it unknown, never 0; `--jobs` 0 is a usage error; `sizing.jobs` and
  `sizing.projected_wall_clock` hold what the printout shows, beside the mean tokens per minute.
- P-14 the smoke runs (owner decisions 35A and 36A): `--smoke` given other than twice, two runs of one
  arm, a run of another study, provider, model, effort or commit, a saved set holding a package no
  pilot run holds, an unscored run and a package with no kept attempt are each refused naming the
  folder and the field; `smoke_runs` lists the two folders relative to the measurement's; no block
  of `measured` reads them, and the ledger does not render them.
- P-8 `benchmark noise-floor`: the same runs and seed give the same record byte for byte; "above 50
  points" when unreached; `runs_digest` names the study's runs; one scorecard written with CRLF and
  with LF line endings, or with its keys reordered, gives one `runs_digest`, and a changed value
  another (RF-56); written through `write_atomic`; an existing `--out`, runs of two studies and an
  unscored run refused (RF-53).

## 13. Defaults this contract takes

Each is reversible; plan.md records it with its alternatives.

- **The interval**: the package-level t interval of section 4, analytic. Alternatives: a studentised
  bootstrap over packages (inner resamples multiply the simulation's cost); the percentile
  bootstrap (undercovers, RR-B4).
- **One `alpha` for the four paired tests, from a fixed ladder**, tightened equally (research §8.1).
  Alternative: separate levels per rule, which spends the budget on the rule the owner cares about
  least.
- **The Monte Carlo bound**: Wilson, one-sided 95%, closed form. Alternative: Clopper-Pearson, a
  little more conservative, needing a numeric root.
- **Intercepts by table**, measured marginal error below `2.5e-5` inside the knots on the SD grid
  0 to 2.5, with positive tails clamped and errors approaching `2.5e-4` (section 9.1). Alternative:
  solving per simulated defect, about 240 times slower. The table retains the pinned draw outputs.
- **The pilot's noise**: Beta by moments for the rates; the shock SD at its 80% profile-likelihood
  upper limit. Alternatives: plug-in estimates throughout (optimistic about co-movement); a
  parametric bootstrap of the pilot with sizing at its 80th percentile (tens of full searches).
- **The approval**: a hand-set block beside a digest of the computed blocks, dated before the first
  paid run. Alternative: a provenance field typed on every study run naming the approval, which adds
  a must-match field to the parity contract.
- **The stress case**: printed in the cost-gate record, where the owner reads it before approving; no
  narrower code guard is designed now (research §8.1's open point). Alternative: design one now,
  before the pilot says whether it is needed.
- **The 39-scenario sweep**: opt-in by marker; three full scenarios and the mechanics in the default
  run. Alternative: the whole sweep in the default run, about four to six minutes more.
- **The noise floor, simulated once and stored** (RF-53). Alternatives: simulated by compare on every
  render (bytes that may differ between the numpy versions the lock resolves, and 4,000-simulation
  searches in the default suite); one numpy pinned across the Python markers.
- **The projected wall clock** (36A; RF-91): the list schedule of the measured per-package times on
  N slots, the on arm scaled by the smoke run's ratio. Alternatives: the total time over N (blind to
  imbalance); the off arm's times for both arms (no smoke input, an upper estimate).
- **The pilot's folders beside its measurement, apart from the study's** (RF-36). Alternative: under
  the study's folder, separated from the study before its run-level checks (RF-11).
