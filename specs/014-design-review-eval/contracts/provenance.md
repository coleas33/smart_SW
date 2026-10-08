# Contract: Run Provenance, Study Rules and Location-Free Run Folders

Normative for FR-013, FR-014, FR-051, FR-052 and FR-056's refusals; User Story 2 scenarios 3
to 6 and 8 to 11, and US5-15; owner decision 28A, the committed event streams packed (sections 6.6
and 6.7). Research D5, D12, D14.9, PP-3, PP-4, PP-7, PP-9, §8.8, and the cross-check of §4 as it
concerns run and compare. How a run is started, its attempts, their
failure classes and `run-status.json` are `benchmark-run.md`'s; the pane study's verdict is the
verdict contract's; the set's own fields (keys, case files, held-out flags) are the benchmark-set
contract's and `scripted-answers.md`'s. Line numbers are at `be01974`; paths are under
`reviewer/src/swreview/` unless another root is given. Every example value is fictional.

Amends: feature 005 `contracts/ab-harness.md` sections 3, 4, 10.1, 10.2 and 10.5 (the record's
fields, the must-match rule, the saved set's form, the ledger's columns); feature 006's profile
identity on standards findings (the stamp names the file, not its folder, section 6.2).

**Slices.** This contract lands in parts (the plan's delivery order; `data-model.md` 7). The parity
slice: section 1's fields but `max_answer_turns`, the clock values and `retry_policy`; section 2's
model-view, profile and set-flag cross-checks; sections 3 to 5; 6.1 to 6.5 (6.2 with the add-in's
pane fixture, RF-28); 6.6's scanner over the record, the saved set and the ledger, a packed stream
read by its decompressed text, `.gitignore`'s packed-stream rules and `.gitattributes`' `*.gz binary`
(owner decision 28A; plan decision RF-84); section 7's allowlist for its fields,
`_session_summary`, and a package export's read of the run root's `run-provenance.json`. The
scripted-answers slice: `max_answer_turns`, in the record and in section
7's allowlist (lane A3). The robustness slice: the clock values, `retry_policy` and `jobs` (owner decision 36A), in the record and
in section 7's allowlist (lane B6), section 2's served-model check, 6.6's reach over
`run-status.json`, the attempt folders and `event-streams.json`, section 6.7's `benchmark pack`
(RF-82) and 6.6's check of every committed run folder's packed streams against their digests
(RF-84), and section 7's `OPTIONAL_ARTIFACTS` and the run root's `run-status.json` (plan decision
RF-42). Each slice's tests (section 8) are its gate: a test marked
with a later slice is that slice's, and every unmarked test is the parity slice's. What only the
verdict can show (the private-package refusal at the verdict, the private row, the pane block's
settings) is `verdict.md` 12's C-2, C-10 and V-21, in the verdict slice.

## 1. The record

`RunProvenance` (`benchmark/runner.py:57-97`), `run-provenance.json` at the run's root, written
by `cli.py` once, before any review (`benchmark-run.md` section 3), from what was typed and
resolved. What the run learns later (outcomes, served models, retries) is `run-status.json`'s
and the attempts' streams, never this file's. It stays strict: an unknown field fails loudly
(`benchmark/runner.py:135-146`).

| Field | Written from | Absent (a record older than this feature) |
|---|---|---|
| `provenance_schema` | `2` | read as `1` |
| `commit`, `lever`, `arm`, `rep`, `provider`, `model`, `effort`, `max_steps`, `checklist_digest`, `set_digest`, `started_at`, `set_too_small_override`, `efficiency`, `explanations_enabled` | as today (`cli.py:2315-2333`); `set_digest` over the location-free saved set (section 6.1) | as today |
| `pane_defaults` | `--pane-defaults` as typed: the marker PP-3 reads | `false`: the option did not exist |
| `model_view` | the resolved `ModelViewSettings` | `null`, "not recorded" |
| `profile_digest` | `load_profile(path).identity.sha256` (`checks/standards/profile.py:626`), the digest every standards finding stamps; `null` with no profile | `null` |
| `profile_is_example` | whether the profile's bytes equal the checkout's `config/standards.example.yaml` at run time; `null` with no profile | `null` |
| `live_tools` | whether the live SOLIDWORKS tools were offered (`bridge`); `false` from `benchmark run` always | `null` |
| `inert_settings` | `INERT_SETTINGS[provider]` (section 3.5) | `null` |
| `max_answer_turns` | `scripted-answers.md` section 4 | `null` |
| `prompt_digest` | sha256 of `agent/prompts/system_v1.md` (`agent/runner.py:143`), beside the checklist's | `null` |
| `tree_dirty` | whether `git status --porcelain --untracked-files=no` lists anything; `null` when git cannot answer | `null` |
| `package_time_limit_s`, `stream_activity_window_s`, `stop_grace_s` | W, A and G (`benchmark-run.md` section 5.3) | `null` |
| `retry_policy` | `BENCHMARK_RETRY` (`benchmark-run.md` section 6) | `null` |
| `jobs` | `--jobs` as typed, default 1: how many packages the run reviewed at once (`benchmark-run.md` section 5.4; owner decision 36A); record-only (section 4) | `null` |

**No path, ever** (FR-013, FR-051): not the profile's, not its folder, not the set file's, a
package's, a key's, a case file's or the output folder's. `profile_is_example` is recorded
rather than recomputed later because the example profile may change after a study ran; a reader
at another commit could not tell whether a recorded digest was the example's at the run's
commit.

## 2. Two writers, cross-checked

`compare` refuses a run whose session and record disagree, naming the field (RK-20; today
efficiency, provider, model, effort and explanations, `benchmark/compare.py:329-369`). Added:

- **Model view** (PP-3): `session.model_view` (written at `agent/runner.py:1621`) equals
  `model_view`. A schema-2 record against a session with none is refused.
- **Profile digest** (US2-3): every `standards.*` finding of the session stamps the sha256 its
  review graded against (`checks/standards/report.py:258`); each must equal `profile_digest`,
  and a stamp on a run that recorded no profile is refused. The cross-check planned in research
  §4 as "not against the session, which carries none" is not written: every standards finding
  carries one. The stamp is read by one parser beside the format it parses (section 6.2).
- **Served models**: every round of a kept attempt was served by an id within the requested
  model's aliases (`benchmark-run.md` section 7), read from the scorecard's
  `PackageScore.served_models`, which the scorer copies from `attempt_facts` (`scoring.md` 7; plan
  decision RF-16), so compare still reads the scorecard and no attempt's events; the run already
  failed any other attempt, and this is the second check a second reader makes.

- **Set flags** (FR-032's compare half, US5-12; plan decision RF-39): each scored package's saved-set
  `held_out` equals "some `graded_items` entry of its `PackageScore` has tag `held_out`", the
  scorecard's copy of the key's tags (`scoring.md` 6). A mismatch is a run-level refusal naming the
  run and the package: "{run}: the saved set marks {package} held_out={flag}, but its scored items
  hold {n} held-out items; the flag is derived from the key". Compare reads no key; `score` made the
  same check against the key, including for a package that then failed and has no `PackageScore`.
  A scored package the saved set does not hold is refused the same way, naming both: "{run}:
  {package} is scored but not in the run's saved set" (plan decision RF-62). Both checks run only
  where the saved copy is there, as the digest check does (`benchmark/compare.py:400-415`: the
  workstation harness writes none). `tests/support/studies.py`'s `write_run` therefore writes one
  saved-set entry per `PackageSpec` (its `package_id`, a repository-relative path, and `held_out`
  equal to the flag its `graded_items` derive) where it writes `"packages": []` today (`:401-405`),
  and records `set_digest` over those bytes as today.

Only a package with a kept attempt has a session (`benchmark-run.md` section 4). A package whose
outcome is an infrastructure failure is checked through `package_outcome` alone and contributes
no session.

## 3. Studies

### 3.1 Names and keys

- `agent/settings.py` gains `PANE_STUDY = "pane_defaults"` and `PRIVATE_PANE_STUDY =
  "pane_defaults_private"` beside `NO_STUDY` (`:640`); `check_study_arm`, which accepts only a
  lever or `none` today (`:747-748`), accepts both.
- A study's key stays `(label, provider, model)` (`benchmark/compare.py:475-480`); the label is
  `lever` except for the pane baseline, whose label is **`none (pane defaults)`** (PP-4). The
  sign-off is carried by label (`benchmark/compare.py:1065-1147`), so the two baselines keep two
  sign-offs.

### 3.2 The pane study (3A, FR-014, PP-2, PP-3)

Two arms, `on` and `off`, one commit, one profile, one set.

At run time, usage errors (exit 2) from `check_study_arm`, each naming the flags:

| Refused | Gist |
|---|---|
| no `--arm` | "name the arm: on or off" |
| `--arm baseline` | "a baseline's study is none" (`agent/settings.py:757-761` for levers today) |
| neither `--explain-findings` nor `--no-explain-findings` typed (PP-2, US2-4) | "type the explanation setting in both arms; the pane study holds it equal and stated" |
| `--arm on` without `--pane-defaults`, or with any `--lever`, `--payload-slimming`, `--history-pruning` or `--prune-after` | "the on arm is exactly --pane-defaults" |
| `--arm off` with any of those or `--pane-defaults` | "the off arm has every change off" |

At run time, after the profile loads (exit 1, `benchmark-run.md` section 3 row 6):

| Study | Refused |
|---|---|
| `pane_defaults` | no `--standards-profile`, or one whose `profile_is_example` is false: every committed case is keyed against the example (FR-027), and one study has one profile (D5) |
| `pane_defaults` | a set naming a package outside the repository (FR-056, US5-15) |
| both | `commit` unknown, or `tree_dirty` true: a paid study must name the code it measured, and two unknown commits would pass the must-match rule as equal |
| both | a digested input inside the repository (the prompt, the checklist, the profile, the set file, a case file) whose bytes hold a carriage return: "check {file} out again: section 6.5's `eol=lf` has not reached this working copy". A stale Windows working copy would otherwise record digests another machine's runs do not share, and compare would refuse the study only after it was paid for (plan decision INT-3) |
| both | from the robustness slice, which adds the price table (`benchmark-run.md` section 13): a requested model the table cannot price by that section's lookup: "no price for {provider} {model} in benchmark/prices.yaml: a pane study's cost must be known (SC-008); add the entry with its source and date". `test_prices.py` checks the default models' entries only, so a paid run with another `--model` would otherwise read "cost unknown" on every package and fail SC-008 after it was paid for; a lever study over the same model is not refused (plan decision RF-79) |
| `pane_defaults_private` | no `--standards-profile`; an `--out` inside the repository, through section 6.4 |

`benchmark resume` applies the clean-tree and carriage-return rows again before any review of a
pane study (a clean tracked tree, no carriage return in a digested input; the commit it already
re-checks), so a resumed attempt never runs on code the record calls clean while it is not
(`benchmark-run.md` 11; plan decision RF-51). The price row needs no second reading:
`benchmark/prices.yaml` is committed, and resume refuses another commit and a dirty tracked tree.

In `compare` (PP-3): the on arm carries `pane_defaults: true` and settings that are not the off
arm's (an on arm whose levers are all off and whose model view is `MODEL_VIEW_OFF` is refused as
mislabelled: it would measure nothing); the off arm carries `pane_defaults: false`, every lever
off and `MODEL_VIEW_OFF` (`agent/settings.py:550`), checked against those constants. The on
arm's settings are not re-derived from today's `pane_defaults()`: the run-time rule above made
them equal at the run's commit, and re-deriving would refuse every recorded pane study the day
the pane defaults change (PP-3's alternative B). Also refused, as run-level refusals that abort the
ledger: a run of either pane study with no arm; a `pane_defaults` run whose `profile_is_example` is
not true. A `pane_defaults` study whose saved sets name a private package is refused at the verdict
only (`verdict.md` section 7, row 2), so its raw rows still render (plan decision INT-13). The
private study is its own key, so its row is never the pane study's (23A); the slice a pane study
reads as is its study name, `pane_defaults` committed and `pane_defaults_private` private
(`verdict.md` section 11). Until the verdict slice routes a pane study to `verdict` (`verdict.md`
section 1), compare renders the runs of both pane studies as raw rows, each under its own study
key, after the checks above, and never passes them to `_decision_row` (`benchmark/compare.py:653`),
whose `decide` never applies to a pane study (FR-045).

### 3.3 Baselines (PP-4, D5)

- **The plain baseline**: `--study none --arm baseline`, every lever off; a model-view switch is
  now refused at run time with the levers (`agent/settings.py:756-766` names `--lever` only),
  and `compare` checks `MODEL_VIEW_OFF` beside every flag off (`benchmark/compare.py:378-386`).
- **The pane baseline**: `--study none --arm baseline --pane-defaults` and nothing else; label
  `none (pane defaults)`; `compare` checks the marker and that its settings are not all off.
  It tracks the shipped configuration across commits; explanations may be left untyped, and
  then run as the pane runs them.
- Both render a distribution and no decision, as a baseline does today (`compare.py:653-676`),
  as two rows; neither enters any verdict (US2-5).
- `compare`'s baseline branch applies to `arm == "baseline"` only. Today it also fires for lever
  `none` with no arm (`compare.py:378`), so a no-study smoke run with a model-view switch or
  `--pane-defaults` would be refused as a bad baseline; it now renders as a raw row, as any run
  with no arm does (`compare.py:475-480`).
- A baseline's label is read off its arm and its marker alone, so `compare` refuses a record with
  arm `baseline` and a lever other than `none`, the pane baseline's marker set or not, as a
  run-level refusal: "{run}: arm baseline with lever '{lever}': a baseline run is the study with no
  lever under test, so its lever is none; the record is inconsistent", as `check_study_arm`
  refuses `--arm baseline` with a study at run time. Labelled, the pane baseline would drop its
  lever, and a plain baseline would join that lever's study as its off arm (refined: research
  9.14, implementation follow-ups).

### 3.4 Lever studies

Unchanged, except that section 4's rule now holds their other settings equal: every lever but
the studied one, the model view and the pane-defaults marker (research §4 cross-check; the
ab-harness contract states "held on in both arms" but nothing checked it).

### 3.5 Inert settings (FR-052, D14.5)

`agent/settings.py` gains, beside `pane_efficiency` (`:502-521`), `INERT_SETTINGS:
Mapping[ProviderName, tuple[str, ...]]`: Gemini's is `("parallel_tool_calls",
"drop_prior_reasoning")`: Gemini makes parallel calls whatever the flag, which `pane_efficiency`
records off for it (`:506-508`), and sends no reasoning items for lever 14 to drop (`:482-488`);
OpenAI's and the scripted provider's are empty. Recorded per run as `inert_settings`.
`compare.settings_differed(off, on)` returns the efficiency and model-view fields whose values
differ between the arms, and the inert ones; the verdict prints both (US2-8). An OpenAI pane
study differs in six settings that act. A Gemini one differs in five recorded settings, of which
dropped reasoning is inert, and names parallel calls inert too (recorded off in both arms, made
in parallel in both): four act (D14.5).

## 4. What must match (US2-6, D5, PP-9)

Across every run of one study, every field of the record must be equal except:

| Field | Exempt | Why |
|---|---|---|
| `rep`, `started_at` | always | run identity |
| `arm` | across the arms of every study, lever and pane alike | what names the arm; a lever study's off and on runs share one study key (`compare.py:475-480`), so without it every lever study would be refused (US2-6: "across arms, the arm"; plan decision RF-10) |
| `live_tools` | always; shown in the ledger | PP-9: recorded, never must-match |
| `efficiency`, `model_view`, `pane_defaults` | across the two arms of a pane study only | what the pane study varies (D5) |
| the studied lever's flag in `efficiency` | across the arms of a lever study only | the lever under test (`compare.py:372-397`) |
| `lever`, `provider`, `model` | not compared | the study's key |
| `jobs` | always | record-only (owner decision 36A; plan decision RF-90): how many packages ran at once changes no review's inputs, only when each starts, so it changes nothing measured. Not a ledger column: it arrives with the robustness slice, after the header's one regeneration (section 5) |

Everything else must match, which is today's six fields (`compare.py:500-502`) and every new
one: `profile_digest`, `profile_is_example`, `explanations_enabled` (PP-2), `max_answer_turns`
(D14.3), `set_too_small_override` (D5), `set_digest` (which holds each case file's digest,
`scripted-answers.md` section 6), `prompt_digest`, `tree_dirty`, the three clock values,
`retry_policy`, `inert_settings`, `provenance_schema`. The refusal names the first differing
field and both values, in the existing message's shape (`compare.py:504-509`). An absent value is
quoted "not recorded" only for a field named in `NOT_RECORDED_WHEN_ABSENT`, a set beside the
exemption sets in `benchmark/compare.py`: the fields whose absence can only mean a record an older
build wrote, `max_answer_turns` from the scripted-answers slice and the clock values,
`retry_policy` and `jobs` from the robustness slice. Every other field's value is quoted as it
is, since its `null` means something in a schema-2 record (`profile_digest` and
`profile_is_example`: no profile; `commit`: git could not answer). The set says how a value is
quoted and exempts nothing (owner decision 47A). The responding
model is exempt within its aliases, which the run enforces per attempt (`benchmark-run.md`
section 7), since snapshots may differ between repetitions.

`compare` implements this as one loop over `RunProvenance.model_fields` minus the named
exemption sets, so a field added later must match until someone exempts it by name; a
structural test holds that every field is in exactly one set.

## 5. The ledger (PP-7, US2-3)

- `RunRow` (`benchmark/compare.py:156-196`) gains `model_view` (from the session, one source per
  column; section 2 has checked the record equal), `profile_digest`, `live_tools` and
  `pane_defaults` (from the record).
- Three columns follow "explanations" (`compare.py:844`, `:910`): **model view** reads `off` for
  `MODEL_VIEW_OFF` and for a session written before feature 008, which that constant defines as
  off (`agent/settings.py:550-552`), `pane` for `MODEL_VIEW_PANE`, otherwise its switches
  (`slimming`, `pruning after N`, or both); **profile** reads `display_digest(profile_digest)`,
  the one 12-character display (`checks/standards/profile.py`, which the tolerance reading's
  `profile_sha256` also calls, `checks/tolerances.py:313-317`; plan decision RF-5), `none` with no
  profile, `unknown` with no record; **live tools** reads `yes`, `no` or `unknown`.
- The lever column reads the study's label (section 3.1); `LEVER_COUNTERS` (`compare.py:120-145`)
  gains the pane baseline's label beside `none`'s (`:135`).
- `tool calls` stays `len(session.steps)` (`compare.py:293-295, 452`), which counts the pre-run's
  and the regrade's steps; the ledger's closing notes say so, and it is not split by the step mark in
  this feature (plan decision INT-10; `scoring.md` section 5.2).
- **The final order, fixed up front** (plan decision INT-10). `RUN_COLUMNS` (`compare.py:835-865`),
  new columns in bold: run, commit, lever, arm, rep, provider, model, effort, explanations, **model
  view**, **profile**, **live tools**, package, input, cached in, uncached in, output,
  reasoning/thoughts, tool-result in, total, rounds, tool calls, cached share, wall clock s, s to
  1st finding, valid, missed, **flagged**, **below expected**, **status mismatch**, **cleared**,
  false alarms, **contradicted**, **confirmed**, unresolved, unresolved withheld, unresolved other,
  coverage bucket mix, **findings by origin**, **false alarms by origin**. The two origin cells are
  mixes like the coverage bucket mix (`prerun 3 / configured_check 1 / ...`, zero origins left
  out), written by `scorecard.fmt_origins`, the scorecard's own origin formatter, with ` / ` for
  its separator (refined: research 9.14, implementation follow-ups); a column a key does not grade
  reads `not assessed`. `LEVER_COLUMNS` gains **Recall by
  producer (held out) off -> on** after "Recall (held out) off -> on" (SP-13 A). Nothing else
  moves. No run-status column: its source, the scorecard's `run_status`, arrives with the
  robustness slice, and a column added then would regenerate the header a second time; a run's
  status is shown by the pane block (failures and stops by arm and class, `verdict.md` section 6)
  and by the report, and a failed package has no run row (`scoring.md` section 7).
- **One schema bump**, to `1.1` (`compare.py:75`), landing with the columns above in the parity
  slice, so the committed header (`docs/llm-efficiency-options.md:164-186`) is regenerated once. The
  1.1 schema, as ab-harness section 4 records it, also names `pane_studies` (`verdict.md` section 8):
  a key omitted when no pane study was compared, filled from the verdict slice on, so that slice
  moves neither the version nor the committed header (`ledger.json` is written and never read back by
  code, `compare.py:796`; the committed document is the markdown, whose pane section renders only
  when present).

## 6. Paths (FR-051; D12; §8.8)

### 6.1 The saved set

- `benchmark-set.json` names every path it carries (a package's; a private entry's key and case
  file, per the benchmark-set contract and `scripted-answers.md` section 6) **relative to the
  checkout root, with `/` separators**, when the resolved path lies under that root: the checkout
  the run's code comes from, `REPO_ROOT` (`benchmark/runner.py:52` today, moved to
  `benchmark/sets.py`). It is the one root of `cases.md` 4.2, which decides resolution, which
  entries are private and this saved form alike, and which refuses the relative paths of a set file
  in another checkout's `benchmarks/sets/` rather than resolve them against that checkout's
  grandparent (plan decision RF-4). A path outside the checkout is written absolute, and that entry is private. The
  root is a parameter of the one set core `load_set(path, *, root)`, of `saved_form()`, of the
  ledger's rendering (section 6.3) and of the committable test (section 6.4), defaulting to the
  running checkout, so a test passes a temporary one.
- It is written as UTF-8 bytes with `\n` line endings (`benchmark-run.md` section 4), not with
  `write_text`, which writes `\r\n` on Windows (`cli.py:2314`). `set_digest` stays the sha256 of
  the saved bytes (ab-harness section 10.2), so it is the same from any checkout at any location
  on any platform (US2-11).
- Today the loaded set is saved with every path resolved absolute (`benchmark/sets.py:51-58`,
  `cli.py:2313-2314`), so the run folder carries the checkout's location, the user's name
  included, and two checkouts' runs are refused as different sets (RR-B0).
- The saved copy is read by `load_saved_set(path, *, root)`, a thin caller of `load_set`'s core
  that accepts relative entries outside `benchmarks/sets/`, resolved against the checkout the
  reader runs in, never the run folder's grandparent (`benchmark/sets.py:45` today). `benchmark score`
  (`cli.py:2353-2362`), `benchmark resume` and the report read the saved copy through it.

### 6.2 The profile stamp (D12)

- `PROFILE_LIMIT` (`checks/standards/report.py:92`) becomes `profile:{name} sha256:{sha256}`,
  `name` the file name of `identity.path`, stamped at `:258`: the digest and the file name, never
  the folder. `ProfileIdentity.path` itself (`checks/standards/profile.py:184-189`) is unchanged:
  the Standards tab and `swreview check standards` still say where the file is.
- `stamped_profile_digest(limits) -> str | None`, beside the format, reads the full digest of
  either form, the old path-bearing one included, for section 2's cross-check. It is not named
  `profile_sha256`: `checks/tolerances.py:313-317` already exports a public `profile_sha256(profile)`
  returning the first 12 characters, and a wrong import of one for the other would compare 12
  characters against 64 and refuse every study. The 12-character display is one helper,
  `display_digest(sha256)` in `checks/standards/profile.py`, which that `profile_sha256`, the
  ledger's profile column (section 5) and the resume and exit messages (`benchmark-run.md` 11, 14)
  call (plan decision RF-5).
- Pinned text regenerates in the same change (feature 008's decision 3A): the standards goldens
  (`reviewer/tests/golden/test_golden/standards-*.yml`, whose harness tokenises the path the
  stamp no longer carries, `reviewer/tests/checks/golden_standards.py:72-79`); the replay
  fixtures that hold the old stamp (`reviewer/tests/fixtures/replay/*/session.json` and
  `events.jsonl`), regenerated from the recordings on the machine that holds them, after 19A's
  byte-identical check (RF-2) and origin marks' regeneration (RF-27), both in the scorer slice; and
  then the add-in's pane fixture, `extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json`,
  which carries the old stamp five times (`profile:..\\config\\standards.example.yaml sha256:…`)
  and which `reviewer/tests/unit/test_pane_fixture.py:49` requires to equal a fresh generation from
  `tests/fixtures/replay/big-assembly/` (`generate_pane_fixture.py:43-47`): `uv run python
  tests/fixtures/pane/generate_pane_fixture.py --write`, after the replay regeneration (plan decision
  RF-28). No C# changes; only the JSON fixture moves, and the add-in's WebView2 acceptance tests
  that load it re-run on a Windows machine.

### 6.3 Run folders in the ledger

`RunRow.run_dir` and `LeverDecision.run_dirs` (`compare.py:432`, `:714`, rendered at `:988`)
render a folder inside the checkout relative to its root with `/` separators; the committed
table is regenerated from absolute paths under `benchmarks/studies/` (`compare.py:769-779`) and
would otherwise carry the checkout's location the day the first study lands. A folder outside
renders as typed, which only a ledger written outside the repository can hold (section 6.4).

### 6.4 Committable folders and the committed ledger

**Committable** means inside the checkout root (`benchmark/runner.py:52`) and not ignored by
`git check-ignore`, asked as `git check-ignore -q -- <path>` so that a folder named like an option
(`-x`, `--stdin`) is read as a path; when git cannot answer, inside the checkout counts as
committable. Inside is
one rule, `benchmark/sets.py`'s `checkout_relative(path, *, root)`: both resolved, then
`is_relative_to`, giving the path relative to the root or `None`. `runner.committable`, a set's
two written forms (6.1), `benchmark run`'s private packages and its carriage-return row (3.2)
and the ledger's run folders (6.3) read it. The helper and `runner`'s `committable`, `tree_dirty`
and `profile_is_example` take `root` by keyword with no default, since a command passes the root
it read (refined twice: research 9.14, implementation follow-ups).

- **At run time** (`benchmark-run.md` section 3 row 5), exit 1 before any review: a committable
  `--out` with a set naming a package outside the repository, or with a profile whose
  `profile_is_example` is false: "{out} is inside the repository, where it may be committed; this
  run {names private package P / grades against a profile other than the fictional example}:
  write it outside the repository".
- **In `compare`** (US2-10), when `--out` or `--into` is committable (the committed ledger is
  `--into docs/llm-efficiency-options.md`), and under `--check` too: a run whose
  `profile_is_example` is false, whose saved set names an absolute path (any path an entry names,
  a package's or a case file's, `sets.named_paths`; refined: research 9.14, implementation
  follow-ups), or whose folder is not committable is refused: "the committed ledger holds only fictional-profile studies over
  committed cases, from run folders the repository holds (FR-051): render {run} with --out
  outside the repository". A run with no profile (`profile_is_example` null) is not refused: it
  graded against no profile at all.

### 6.5 Line endings of the inputs a run digests

`.gitattributes` gains `eol=lf` for `config/standards.example.yaml`,
`reviewer/src/swreview/agent/checklist_v1.yaml`, `reviewer/src/swreview/agent/prompts/*.md` and
`benchmarks/**`. Under today's `* text=auto` (`.gitattributes:2`) and Git for Windows'
`core.autocrlf`, these check out with `\r\n` on Windows (this checkout's example profile does,
at `be01974`) and `\n` elsewhere, so `checklist_digest`, `prompt_digest`, `profile_digest` (the
product's raw-byte identity, `checks/standards/profile.py:625-626`) and every case file's digest
would differ between two machines of one study, which section 4 would refuse. Digests stay over
raw bytes; the checkouts agree instead. A checkout made before the change keeps its `\r\n`
working copies until those files are checked out again; the test below says so by name.

### 6.6 The committable-folder test (§8.8; round 3, RR3-5)

A scanner in `reviewer/tests/support/local_paths.py` reads every file, JSON as strings so
escaping hides nothing, and flags:

- a path under the checkout root, the user profile folder or the temporary folder, all known when
  the test runs, compared case-insensitively with either separator;
- a saved set (`benchmark-set.json`) naming any path outside the repository: a private entry;
- any drive-letter or UNC path, found with `tests/support/scramble.py`'s anchor pattern
  (`_WINDOWS_ANCHOR`, `:299`, made public as `WINDOWS_ANCHOR` and imported, not restated; plan
  decision RF-6), or rooted path, whose prefix is not one of the named fictional roots:
  `FICTIONAL_ROOT` (`reviewer/tests/support/mechanical.py:104`), the replay scrubber's
  (`reviewer/tests/support/scramble.py:108`), `/Designs/` (`reviewer/tests/support/features.py:717`,
  `reviewer/tests/support/packages.py:54`), the example profile's `vault_root`
  (`config/standards.example.yaml:11`), the golden profiles' (`reviewer/tests/fixtures/standards/
  profile-a.yaml:10`, `profile-b.yaml:10`) and `/Library/`. The named constant and the four
  `vault_root`s are read from their sources, so they cannot drift; `/Designs/` and `/Library/`,
  written inline by the builders, are listed with those citations. A rooted path is a `/` at a token boundary (not after a
  word character, `:`, `/` or `.`) followed by a non-space, so `and/or`, `1/2` and a URL's `//`
  are not paths; nor is an HTML end tag's `/` (`</td>`, `</table>`) or a self-closing tag's
  `/>`, since the report slice may commit its pages, though a path written straight after `<`
  (`</srv/x>`) is one. A UNC anchor and a drive letter with `/` start a path only at a token
  boundary (not after a word character); a drive letter and its backslash start one wherever they
  stand, so a single-backslash drive path glued to a word character in plain text (an escaped
  line quoted, `...\nE:\...`) is flagged, and so, by decision, is plain text such as `regex:\d+`
  (read as `x:\d+`), a false alarm kept on the refusing side. A path lies under a fictional root
  only once its `..` are applied, so one that starts at a root and climbs out of it is flagged
  (refined: research 9.14, implementation follow-ups).

It runs over every file under `benchmarks/studies/` and `benchmarks/pilots/` (the paid pilot's
folders, plan decision RF-36) that git does not ignore, and over the ledger block of
`docs/llm-efficiency-options.md`. A file whose name ends `.gz` is scanned by its decompressed text
(`gzip.decompress`, then UTF-8), so a path inside a packed stream is found as in a plain file (plan
decision RF-84); a `.jsonl` file, a decompressed `events.jsonl.gz` included, is read line by line,
each line parsed as JSON on its own and one that is not JSON read as its text (refined: research
9.14, implementation follow-ups). Every committable file a run, `score`, `compare`, `benchmark pilot`,
`benchmark noise-floor` or `benchmark pack` writes is in its reach: the record, the saved set,
`run-status.json`, every attempt folder (`session.json`, `events.jsonl.gz` once packed,
`tool-results/`, `prompts.json`, `answer-log.json`), `event-streams.json`, `scorecard.*`,
`ledger.*`, `pilot-measurement.json` and `noise-floor.json`.

**The event streams are committed, packed** (owner decision 28A; plan decisions RF-78, RF-84).
`.gitignore` ignores `**/events.jsonl` (`.gitignore:77`), with the replay fixtures its one exception
(`:80`), and at `be01974` no rule ignores `events.jsonl.gz`. The parity slice adds, after that rule,
`**/events.jsonl.gz`, then `!benchmarks/studies/**/events.jsonl.gz` and
`!benchmarks/pilots/**/events.jsonl.gz`. So a plain stream, the working form while a run writes,
stays ignored everywhere, the two trees included, and never reaches a commit; a packed stream is
committable only in the two trees, since a packed stream of a run written anywhere else in the
checkout is model output and reviewed document text like a plain one (`.gitignore:74-75`).
`.gitattributes` gains `*.gz binary` after section 6.5's `benchmarks/** eol=lf`, the later line
winning, so no checkout converts a compressed byte. Re-scoring a committed study (withdrawn hits),
`attempt_facts` (cost, served models, the failed attempts' spend) and the report read the streams,
each found by `agent/events.event_stream`, plain or packed (plan decision RF-83); without them a
committed study could be neither re-scored nor reported from another checkout. Packed, a study at the
cap puts about 12 MB of streams into every checkout's working tree rather than about 102 MB (research
RF-78's arithmetic). The cases are fictional, and the scanner reads the packed streams like every
other file.

The scanner is the detector; the harness keeps a local path out of what it writes. A failure's
message is passed through `benchmark/scrub.without_local_paths` before `run-status.json` records it,
and the runner's generic error body goes through the same helper (`benchmark-run.md` 10; plan
decisions RF-41, RF-73), so no failure the harness writes needs a hand edit. An adapter's own error
body and a tool's failure text are not scrubbed: the scanner finds one before a paid folder is
committed.

### 6.7 Packing a run folder (28A; plan decision RF-82)

`swreview benchmark pack <run dirs...>` (`benchmark/streams.py` `pack_run(run_dir)`; the robustness
slice, lane B6) compresses a finished run's event streams in place. The operator runs it after the
run's last `benchmark resume` and before its folder is committed (quickstart P3 and P4); it contacts
no provider and reads no key.

Refused, exit 1, one line naming the folder, and nothing packed in any named folder, since every
folder's refusals are checked before the first is packed:

| Refused | Gist |
|---|---|
| no `run-provenance.json` | "{folder} is not a run folder" |
| no `run-status.json` | "{folder} was made before runs recorded their status; it cannot be packed" |
| an attempt whose `kind` is `null` (`benchmark-run.md` 10: running, or interrupted) | "attempt {n} of {package} has no outcome: run `swreview benchmark resume {run}` first" |
| a recorded kept attempt still under `attempts/` | `package_outcome`'s "promotion incomplete: run `swreview benchmark resume <run>`" (`benchmark-run.md` 4) |
| an `events.jsonl.gz` with no `events.jsonl` beside it and no row in `event-streams.json` | "{path} is packed but unrecorded" |
| a folder holding both forms whose `events.jsonl.gz` decompresses to bytes other than its `events.jsonl` | "{path}: the packed stream differs from the plain one beside it" |
| a plain stream whose row in `event-streams.json` (left by a pack that stopped before its deletions) names another digest than its bytes' | "{path}: its recorded digest differs from the stream" |

Then, per run folder:

1. Each `<run>/<package>/events.jsonl` and `<run>/attempts/<package>/<n>/events.jsonl`, and no
   other file, is read as bytes; its digest is `benchmark/digest.sha256_of_bytes` of those bytes,
   the stream as the run wrote it (`sha256_of` calls the same helper; the one raw-bytes digest,
   RF-48); it is compressed with `gzip.compress(data, compresslevel=9, mtime=0)`, whose header holds
   no file name and no time, so one stream packs to one set of bytes on one zlib; the result is
   decompressed again in memory and must equal the bytes read; it is written beside the stream as
   `events.jsonl.gz` through `write_atomic`. A folder already holding both forms (a pack stopped
   after this step) is verified by the refusal above and not written again.
2. `<run>/event-streams.json` is written through `write_atomic`: `{"event_streams_version": 1,
   "streams": {"<run-relative path of each packed stream, / separators>": "<its digest>"}}`, UTF-8,
   sorted keys, LF. The rows of an earlier pack are kept and never changed.
3. Each plain stream packed is deleted.

A run with nothing left to pack prints "{run}: already packed" and exits 0. A packed run resumes as
any run: its new attempts write plain streams, and packing it again packs them and adds their rows.
An attempt that failed before its first event has no stream and no row. A folder holding both forms
is an unfinished pack: `agent/events.event_stream` refuses it, naming the folder and this command
(plan decision RF-83), and packing the run again finishes it.

No reader checks the digest. The pack verifies what it writes, and section 8's
`test_committed_run_folders_hold_packed_streams_matching_their_digests` verifies every committed
stream on every checkout. A handoff export of a packed package folder records `events.jsonl` as
missing, as it records any missing core record (`handoff.py:52-58`); a committed folder travels by
git, not by the export.

## 7. The handoff export (D14.9, US2-9)

- `_provenance_summary`'s allowlist (`handoff.py:425-433`) gains, with the slice that adds each
  field (plan decision RF-42): `provenance_schema`, `pane_defaults`, `model_view`, `profile_digest`,
  `profile_is_example`, `live_tools`, `inert_settings`, `prompt_digest` and `tree_dirty` (parity);
  `max_answer_turns` (scripted answers, lane A3); `package_time_limit_s`,
  `stream_activity_window_s`, `stop_grace_s`, `retry_policy` and `jobs` (robustness, lane B6; `jobs` from
  owner decision 36A). None is a
  path; the allowlist stays a literal tuple, the guard that keeps any later field out until it is
  named, and a test holds it equal to `RunProvenance.model_fields`, so no recorded field silently
  misses the bundle.
- `_session_summary` (`handoff.py:360-414`) gains `model_view`, which the session already holds.
- **Which folder a benchmark export takes.** `export_handoff` reads one input tree
  (`handoff.py:128-155`), while a benchmark run keeps its provenance and status at the run root,
  which holds no session, and its session, events, prompts and answer log in `<run>/<package>/`,
  which holds no provenance. A benchmark export takes `<run>/<package>` as its input tree, as a
  review's folder today, and, when the parent holds `run-provenance.json` beside
  `benchmark-set.json` (a benchmark run's root), also reads those names only from the parent:
  `run-provenance.json` from the parity slice, `run-status.json` from the robustness slice. Nothing
  else of the run root or of another package is read, and the archive must lie outside the run root
  as well as outside the package folder. The archive holds both folders' names at its top level, so
  each manifest artifact record names its `source`: `run_root` for a name read from the run root,
  `run_dir` for every name read from the input tree, a review's included (refined: research 9.14,
  implementation follow-ups).
- `OPTIONAL_ARTIFACTS` (`handoff.py:61-76`) gains `prompts.json` and `answer-log.json` (robustness
  slice), the records a benchmark package folder now holds (none carries a path by section 6.6's
  test, though a private run's messages may name real designs, as the export's source policy
  already allows for packages, `handoff.py:112-116`).

## 8. Tests

Every test fails before its behaviour exists (constitution III); all offline (FR-047).

`reviewer/tests/unit/test_run_provenance.py`:
- `test_provenance_records_every_field_its_slice_adds[slice]`, parametrized by slice (2, 3, 6), each
  asserting the fields that slice lands (the Slices note above; FR-013);
- `test_provenance_holds_no_path` (the record's bytes contain neither the profile's path nor its
  folder, the set file's, a package's nor `--out`'s);
- `test_a_record_older_than_this_feature_reads_the_new_fields_not_recorded` and
  `test_an_unknown_field_still_fails_loudly`;
- `test_profile_is_example_is_true_only_for_the_checkouts_example_bytes`;
- `test_tree_dirty_reads_tracked_changes_only_and_is_null_without_git`;
- `test_inert_settings_name_parallel_calls_and_dropped_reasoning_on_gemini_only` (FR-052).

`reviewer/tests/unit/test_efficiency_settings.py` (`check_study_arm` additions):
- each section 3.2 usage refusal, naming the flags (US2-4, PP-2);
- `test_the_pane_baseline_is_exactly_pane_defaults` and
  `test_a_plain_baseline_refuses_a_model_view_switch` (PP-4);
- the four existing contradictions unchanged.

`reviewer/tests/unit/test_benchmark_run_pane_study.py`:
- `test_the_pane_study_requires_the_example_profile` (no profile, another profile);
- `test_the_pane_study_refuses_a_private_package` (US5-15, FR-056);
- `test_a_pane_study_refuses_an_unknown_commit_and_a_dirty_tree`;
- `test_a_pane_study_refuses_a_digested_input_holding_a_carriage_return` (INT-3), and a private
  profile outside the repository is not checked;
- `test_the_private_pane_study_takes_the_real_profile_and_private_packages`;
- section 3.2's price row is pinned by `benchmark-run.md` 15's
  `test_a_pane_study_refuses_a_model_the_price_table_cannot_price` (the robustness slice; RF-79),
  which asserts this table's message.

`reviewer/tests/unit/test_benchmark_compare.py` additions (`tests/support/studies.py`'s `RunSpec`
gains the new record fields, a pane-baseline spec and a pane-study pair, and `write_run` a saved-set
entry per package, section 2):
- `test_compare_refuses_a_session_whose_model_view_differs_from_the_record` (PP-3);
- `test_compare_refuses_a_standards_stamp_whose_digest_differs_from_the_record` and
  `test_compare_refuses_a_stamp_on_a_run_that_recorded_no_profile` (section 2);
- `test_runs_of_one_study_differing_in_any_must_match_field_are_refused_naming_it`, parametrized
  over every field section 4 does not exempt (US2-6);
- `test_a_lever_studys_off_and_on_runs_pass_the_must_match_loop`, the lever study's own pair beside
  the partition test, which alone would not see an exemption missing (RF-10);
- `test_repetition_start_time_and_live_tools_never_refuse` (US2-6, PP-9);
- `test_jobs_never_refuses` (the robustness slice; owner decision 36A): two runs of one study recorded at
  `jobs` 1 and 4 compare with no refusal, and the partition test finds `jobs` among the named exemptions;
- `test_the_pane_study_arms_may_differ_only_in_levers_model_view_and_the_marker` (US2-4, D5);
- `test_the_pane_study_refuses_unequal_explanation_settings` (US2-4);
- `test_an_off_arm_with_any_change_is_refused`, `test_an_on_arm_without_the_marker_is_refused`
  and `test_an_on_arm_with_every_setting_off_is_refused_as_mislabelled` (PP-3);
- `test_a_lever_study_whose_arms_differ_in_another_lever_is_refused` (section 3.4);
- `test_a_pane_baseline_and_a_plain_baseline_are_two_rows_with_two_sign_offs` (US2-5, PP-4);
- `test_a_no_study_run_with_a_model_view_switch_renders_as_a_raw_row` (section 3.3);
- `test_the_private_pane_study_is_its_own_key_and_renders_as_raw_rows` (23A, section 3.2): a
  `pane_defaults_private` pair and a `pane_defaults` pair of the same provider and model form two
  study keys, and each renders raw rows with no decision row; the private row itself is C-10's, and the refusal of a `pane_defaults`
  study whose saved sets name a private package is C-2's (FR-056), both in the verdict slice;
- `test_settings_differed_returns_the_differing_and_the_inert_settings` (US2-8, FR-052; section
  3.5), on `compare.settings_differed(off, on)` itself: an OpenAI pane pair returns its six differing
  settings and no inert one, a Gemini pair its five recorded differences with dropped reasoning and
  parallel calls named inert; V-21 pins the pane block that prints them (the verdict slice);
- `test_the_provenance_fields_are_partitioned_into_must_match_and_named_exemptions`;
- `test_compare_refuses_a_set_flag_that_disagrees_with_the_scored_items` (section 2; RF-39): a saved
  set marking a package `held_out: true` whose `graded_items` hold no held-out item, and the
  reverse, each refused naming the run and the package;
- `test_compare_refuses_a_scored_package_missing_from_the_saved_set`, naming the run and the
  package; a run with no saved copy runs neither check (section 2; RF-62);
- `test_compare_refuses_a_kept_attempt_served_outside_the_aliases`, from a scorecard whose
  `served_models` names an id outside the requested model's aliases, compare reading no attempt's
  events (section 2; RF-16; the robustness slice);
- `test_the_run_and_decision_columns_are_section_5s_final_order` (INT-10: the header pinned whole,
  so a later slice cannot insert a column without failing it);
- `test_the_ledger_shows_model_view_profile_and_live_tools` and
  `test_a_row_whose_session_predates_the_model_view_reads_off` (US2-3, PP-7);
- `test_the_committed_ledger_refuses_another_profile_a_private_package_and_an_outside_folder`, and
  `test_a_ledger_written_outside_the_repository_accepts_them` (US2-10);
- `test_run_folders_render_repository_relative_inside_the_checkout` (section 6.3);
- the existing `test_the_committed_results_table_regenerates_byte_identically`, with the header
  regenerated once at schema 1.1.

`reviewer/tests/unit/test_saved_set_paths.py`:
- `test_the_saved_set_names_repository_paths_relatively` (FR-051);
- `test_two_checkouts_at_different_locations_save_the_same_bytes_and_digest` (US2-11);
- `test_a_private_entry_is_saved_absolute`;
- `test_the_saved_set_is_written_with_lf_bytes`;
- `test_the_saved_copy_resolves_against_the_readers_checkout`;
- the second-worktree refusal is `cases.md` 9's
  `test_a_set_file_in_a_second_worktree_is_refused_naming_both_roots`, which this contract relies
  on for "one root" (RF-4).

`reviewer/tests/unit/test_standards_report.py` (`:303` revised):
- `test_the_profile_stamp_names_the_file_and_its_digest_never_its_folder` (D12, US2-3);
- `test_the_stamp_parser_reads_the_full_digest_of_the_old_and_the_new_form` (`stamped_profile_digest`);
- `test_display_digest_is_the_one_twelve_character_reading` (`tolerances.profile_sha256`, the ledger's
  profile cell and the resume refusal's text all equal `display_digest` of the same digest; RF-5).

`reviewer/tests/unit/test_committable_paths.py` (FR-051, §8.8):
- the scanner: flags the checkout, the home and the temporary folder in both separators and
  JSON-escaped; flags a drive-letter, UNC and rooted path outside the fictional roots, the first two
  through `scramble.WINDOWS_ANCHOR`; passes each
  fictional root; ignores `and/or`, `1/2` and a URL; flags a saved set with an absolute entry;
- `test_the_scanner_finds_nothing_in_a_message_scrubbed_of_local_paths`: a message naming the run
  folder, the checkout, the temporary and the home folder, in forward-slash, backslash and
  `repr`-doubled spellings, is flagged by the scanner, and passes it after
  `benchmark/scrub.without_local_paths` (RF-41; the robustness slice, which adds `scrub.py`, RF-59);
- `test_no_committable_file_holds_a_local_path_or_a_private_set_entry`, over section 6.6's reach,
  `benchmarks/pilots/` included;
- `test_packed_streams_are_committable_only_in_the_study_and_pilot_trees` (28A; RF-84, which
  supersedes RF-78's plain-stream test): `git check-ignore -q --no-index` reports neither
  `benchmarks/studies/<study>/<run>/<package>/events.jsonl.gz` nor
  `benchmarks/pilots/<study>/<run>/<package>/events.jsonl.gz`, nor either tree's
  `<run>/attempts/<package>/<n>/events.jsonl.gz`, as ignored, and reports as ignored a plain
  `events.jsonl` at each of those places and an `events.jsonl.gz` elsewhere under `benchmarks/`;
  `git check-attr binary text eol` reports each of those `.gz` paths `binary: set` and `text: unset`
  (`*.gz binary` after `benchmarks/** eol=lf`); skipped where git is absent, never passed;
- the scanner over a packed stream: an `events.jsonl.gz` whose decompressed text names the checkout
  folder is flagged, and one naming only a fictional root passes (RF-84);
- `test_committed_run_folders_hold_packed_streams_matching_their_digests` (the robustness slice;
  RF-84): over every run folder under `benchmarks/studies/` and `benchmarks/pilots/` whose
  `run-provenance.json` git tracks: `event-streams.json` is tracked; every tracked `session.json`
  has a tracked `events.jsonl.gz` beside it; every tracked `events.jsonl.gz` decompresses to bytes
  whose `digest.sha256_of_bytes` is its row; every row names a tracked `events.jsonl.gz`; a run
  folder git does not track (a study still running, plan RK-15) is not checked; skipped where git is
  absent, never passed. Pinned the other way on a temporary repository: a committed folder with a
  stream missing, a row missing, an edited stream, and a row naming no stream each fail it, naming
  the file;
- `test_an_offline_run_over_a_committed_style_package_writes_no_local_path`: a scripted
  `benchmark run` with the example profile, in a temporary checkout, then `score` and `compare`, the
  whole folder scanned (US2-11). In the parity slice it runs without `--max-answer-turns`, which
  does not exist yet, the review being one turn with no driver; the scripted-answers slice (lane A3)
  adds `--max-answer-turns 0` with the option (the one-turn fake script cannot play an anchor's
  scripted answer, plan decisions RF-25, RF-59);
- `test_a_committable_run_folder_is_refused_for_a_private_package_or_another_profile`.

`reviewer/tests/unit/test_benchmark_pack.py` (the robustness slice; section 6.7, 28A, RF-82), over run
folders a scripted `benchmark run` wrote, one package with a failed first attempt among them:
- `test_pack_replaces_every_stream_with_its_packed_form_and_records_its_digest`: kept packages' and
  attempts' streams alike; each `events.jsonl.gz` decompresses to the bytes the plain stream held;
  `event-streams.json` holds one row per packed stream, its run-relative path and the
  `sha256_of_bytes` of the plain bytes, sorted, LF, written through `write_atomic` (a spy); no
  `events.jsonl` remains; an attempt that failed before its first event has no row;
- `test_packing_is_reproducible`: the same stream packs to the same bytes twice, its header holding
  no file name and no time;
- `test_a_packed_run_scores_as_before`: `benchmark score` over the packed folder writes the same
  `scorecard.json` bytes as over the plain one, `attempt_facts` included (withdrawn hits, cost,
  served models, the failed attempt's spend);
- each section 6.7 refusal, exit 1, naming the folder, with nothing packed in any named folder:
  not a run folder; no `run-status.json`; an attempt with no outcome, naming resume; an incomplete
  promotion; a packed but unrecorded stream; both forms whose bytes differ; a recorded digest that
  differs from its plain stream;
- `test_an_unfinished_pack_is_refused_by_the_readers_and_finished_by_packing_again`: both forms left
  in one package folder (the deletion patched to raise): `score` refuses naming the folder and
  `benchmark pack`; packing again verifies, deletes the plain stream and changes no row;
- `test_a_resumed_packed_run_packs_only_its_new_attempts`: a pack, then a resume re-running the
  failed package, then a pack: the new attempt's row is added, every earlier row and packed file is
  unchanged;
- `test_packing_a_packed_run_says_already_packed` (exit 0, nothing written).

`reviewer/tests/unit/test_line_endings.py`:
- `test_digested_inputs_check_out_with_lf`: `git check-attr eol` reports `lf` for section 6.5's
  files, and their bytes hold no `\r`, the failure message naming the files to check out again;
  skipped where git is absent, never passed (as D13's identifier tests are).

`reviewer/tests/unit/test_handoff.py` additions, each exporting a package folder that a scripted
`benchmark run` actually wrote (RF-42):
- `test_a_pane_defaults_benchmark_run_exports_its_provenance_fields_and_never_the_profile_path`
  (US2-9): `<run>/<package>` exported; the model view, digest, marker and live tools in
  `recorded_run_provenance`, read from the run root; neither the profile's path nor its folder
  anywhere in the archive's bytes;
- `test_the_session_summary_carries_the_model_view`;
- `test_the_handoff_allowlist_names_every_provenance_field`: the allowlist equals
  `RunProvenance.model_fields` at every slice, and no value the scripted run recorded is a path;
- `test_a_package_export_reads_only_the_run_roots_provenance_and_status` (the robustness slice's
  half adds `run-status.json`): no other file of the run root or of another package is in the
  archive, and a folder whose parent is not a run root reads nothing from it;
- `test_run_status_prompts_and_answer_log_are_exported_when_present` (the robustness slice).
