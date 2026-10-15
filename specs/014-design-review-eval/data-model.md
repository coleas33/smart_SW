# Data Model: Design-Review Eval

**Feature**: `014-design-review-eval` | **Date**: 2026-09-29 | **Plan**: [plan.md](plan.md)

Every entity the eval reads or writes, consolidated from the contracts. Each names its fields, its
validation, its relationships, where it is stored and who writes it; the contract that is normative
for it is named in brackets and wins on any detail this summary leaves out. Paths are under
`reviewer/src/swreview/` unless another root is given; line numbers are at `be01974`. "Slice" is the
plan's delivery order.

## 1. Overview

```text
case spec (tests/benchmark_cases, Python) --generator--> package.json, answer key, case file, set entry
                                                                |
set file --load_set/preflight_set--> benchmark run --> run folder:
   run-provenance.json (once, before any review)   benchmark-set.json (saved, location-free)
   run-status.json (driver)   attempts/<pkg>/<n>/ --promote--> <pkg>/{session.json, events.jsonl,
                                                     tool-results/, prompts.json, answer-log.json}
key + run folder --benchmark score--> scorecard.json (scoring_rules_version)
scorecards + provenance + sessions --benchmark compare--> ledger.json 1.1 (runs, decisions, pane_studies)
pilot and smoke run folders (benchmarks/pilots/) --benchmark pilot--> pilot-measurement.json (projected wall clock, 36A) --owner approval--> compare --pilot
study scorecards + measurement --benchmark noise-floor--> noise-floor.json --> compare (read, never simulated)
run folders + saved set + packages --benchmark report--> index.html, transcripts/
finished run folder --benchmark pack--> events.jsonl.gz per stream + event-streams.json (28A; before a commit)
```

Rules every entity follows: strict models (an unknown field is refused, `findings.ReviewModel`,
`findings.py:60-61`); optional fields omitted when absent so older files keep their bytes; unknown is
`null`, never 0 (Principle I); no local absolute path in anything committable (FR-051), the
harness's own failure messages scrubbed where it writes them (RF-41, RF-73); every atomic
write goes through the one `write_atomic` (`swreview/atomic.py`, RF-31), this feature's records and,
since owner decision 34A, the product's three older ones (the attention record, the tokenizer
vocabulary, the package a live interference run updates), each as the bytes given: UTF-8 LF for every
record (a packed stream as its compressed bytes); every digest is `benchmark/digest.py`'s, `sha256_of` over a
file's raw bytes (through `sha256_of_bytes`, which a packed stream's digest calls on its plain bytes,
RF-82) or `canonical_sha256` over parsed JSON, sorted keys, no whitespace (RF-48, RF-56); a run's event stream, `events.jsonl` or,
packed, `events.jsonl.gz` (28A), is found only by `agent/events.event_stream` and read only through
`agent/events.replay_events` (RF-29, RF-83), and a stored tool result only through
`tools/registry.read_stored_result` (RF-30).

## 2. The answer key, format 2  [answer-key.md; questions.md 5]

Stored at `benchmarks/answer_keys/<package_id>.json` (committed; generated, or `rms-part.json` by
hand) or at the absolute path a private set entry names. The format's one definition is the
data-only `benchmark/answer_key_model.py` (the models, `Stamp`, the pattern grammar, the reference
kinds, the model's own validators), which the generator writes through; the one reader is
`benchmark/answer_key.py` `load_answer_key(path, *, package, checklist, words)`, which also holds
`current_stamp()` and the refusals that need the matcher, the question reader, the checklist, the
report's goals or the package (RF-1); nothing under `tools/`, `agent/`, `checks/` or
`benchmark/runner.py` imports either (FR-032).

| Field | Rule |
|---|---|
| `key_format` | `2`; absent is format 1, refused naming the contract |
| `package_id` | equals the file stem and the set entry's id |
| `key_only` | optional `true`: loads with no package, ids unchecked; refused when the package exists; scoring refuses it |
| `known_defects[]` | `D-<n>`, `check` (exact or `x.*`), `component_ids`, `document_ids` (one non-empty), `references` (exactly on the eleven reference-keyed checks), `producer` (`code`/`model`), `expected_status` (`demonstrated`/`suspected`/`unresolved`), tag fields, `description` |
| `correct_conditions[]` | `C-<n>` (required, SP-5), as a defect less producer and status |
| `forbidden[]` | `FB-<n>`, `checks[]` (exact or families), parts or documents, never references, tag fields |
| `expected_coverage[]` | `CV-<n>`, `item` (a checklist item read by a report goal), `statuses` from `checked`, `unresolved`, `skipped`, `out_of_scope`, tag fields |
| `unanswerable_requests[]` | `U-<n>`, `documents` (non-empty), `item` or `null`, tag fields (questions.md 5.1) |
| `question_counts[]` | `Q-<n>`, `part_roles: true` or `item` with optional `ids`, `min` 0 or 1, optional `max`, tag fields (questions.md 5.2) |
| tag fields (every entry) | `tag` `held_out` or `tuned_on`; `held_out_against {prompt, checklist, tools}` exactly when held out: `benchmark/digest.sha256_of` over the raw bytes of `agent/prompts/system_v1.md` and `agent/checklist_v1.yaml`, and (25A) `tools`, `digest.canonical_sha256` of `{name: {"description": spec.full_description, "schema": spec.schema}}` over every tool a design review can offer, `Args:` entries included through the schema (`answer_key.tool_descriptions_digest()`), all named once by `answer_key.current_stamp()` (RF-48, RF-64) |

**References** (one element per covered item): joint `{fastener, hole}` (the four fastener rules and
`fastener.unsupported`); recess `{recess: "<hole>#<n>"}` (`fastener.head_fit`); hole pair `{holes: [a,
b]}` (`hole.coaxiality`); joint instances `{hole_instances: [...]}` (`hole.nominal_alignment`,
`hole.position_stack`); fit `{bore, shaft}`; stack `{contributors: [...], target}`; a dimension is
`{document_id, sheet, annotation}`, resolved by `tools/refs.resolve_dimension`.

**Validation** (answer-key.md 4). The model's, run whenever an `AnswerKey` is built: format and
fields; ids and prefixes; producer, status and tag; parts or documents; the check-pattern grammar
(no family over a reference-keyed check on a defect or condition, AK-4); reference shapes. Then the
loader's: package id against the file stem and the set entry; every id under a report goal (the typo
guard, AK-6); overlaps (defect/defect, defect/condition, forbidden/defect) through the matcher's
primitives; coverage items (one per goal; a goal holding a defect's check must allow `checked`); the
question sections' refusals; key-only; with the package: id resolution and reference ownership.

**Derived** (RF-67): `AnswerKey.holds_held_out()` is the set's `held_out` flag and
`held_out_model_defect_ids()` the held-out model-produced count, wherever either is computed (the
generator, `score`, the set summary).

**Lifecycle**: an item tagged `held_out` becomes `tuned_on` in the commit whose prompt, checklist or
tool-description change cites it (15A, 25A); a stale digest is listed, never refused; `key_only` is removed when the package
is built (the loader refuses the marker then). Slices: defects and conditions in 1; the four
extension lists in 3.

## 3. The case file and the answer log  [scripted-answers.md; questions.md]

**CaseFile** (`benchmark/case_file.py`, data only; loaded only by `benchmark/answers.load_case_file`):
`case_file_version` 1, `package_id`, `answers[]` of `{id: "A-<n>", part_roles: true | item: str|null
+ ids: [...], answer: str}`. Stored at `benchmarks/case_files/<package_id>.json` (anchors only) or a
private absolute path; never inside a package folder; protected by the key-isolation guard's
`benchmarks/case_files` segment and by the set's withheld paths. Refused before any review
(scripted-answers.md 2.3): version, package id, entry shape, blank answer, an item not in the
checklist or code-owned, an id not a component instance or document, two entries on one item with
intersecting resolved ids, two part-roles entries, a part-roles entry the product's classifier would
never ask.

**AnswerLog** (`<run>/<package>/answer-log.json`, written by `drive_review` in a `finally`):
`answer_log_version` 1; `points[]` of `{after_turn, steps_before, sent: [{request_id, entry,
outside_options?}], unscripted: [{request_id, reason: no_answer|ambiguous|names_nothing, entries?}],
held: [request ids]}`; `ended` one of `no_open_questions`, `all_unscripted`, `bound_reached`,
`turn_did_not_end`, `stopped`; `last_turn_end`; `unused_entries`. Ids only: no answer text, no path.
Checked against the session before scoring (every sent id answered, every answered request sent once).

**Driver states**: opening turn -> answer point -> (stop: turn did not end / stop requested / no open
question / all unscripted / bound reached) or answer turn -> next answer point. An entry is delivered
at every point where it is the one entry an open request asks within, so a question asked again and
recorded is answered again (RF-13).

## 4. The benchmark set  [cases.md 4; provenance.md 6.1; scripted-answers.md 6]

**Set file**: `{name, packages[]}`; an entry (`BenchmarkPackageRef`, `benchmark/sets.py:22-27`)
holds `package_id`, `path`, and, optional in the model: `key`, `case_file`, `held_out` (derived:
true exactly when the key holds a held-out item), `design`, `twin_of`, `represents` (R-1..R-8,
AF-1..AF-3). Committed files (`benchmarks/sets/committed.json`, `pilot.json`, and `pane-smoke.json`, quickstart
P0's two entries of `committed.json`, `kalo-1` and `kalo-fit-1`, owner decision 35A) are generated through
`BenchmarkSet.file_form(*, root)` (RF-54), name repository-relative POSIX paths and carry `key`,
`held_out`, `design` on every entry; a private set
lives outside the repository with absolute paths. One root decides every path rule: the running
checkout's `REPO_ROOT` (moved to `benchmark/sets.py`), a keyword parameter of the one core
`load_set(path, *, root)`. Relative paths resolve only in a set file under `<root>/benchmarks/sets/`;
one in another checkout's `benchmarks/sets/` is refused naming both roots. A set is **keyed**
when some entry names `key`, and then every entry must; a **keyless** set (every set written before
this feature) reads its keys from `--answer-keys` (RF-4). Refusals (`SetError`, cases.md 4.3):
unreadable, duplicate ids, a relative path outside `<root>/benchmarks/sets/`, a package
under a withheld segment, a package at or under any named key's or case file's folder (and the
reverse), in a keyed set an entry without a key or a key on the wrong side of the root, a bad
`twin_of` or `represents`.

**Saved set** (`<run>/benchmark-set.json`): `BenchmarkSet.saved_form(*, root)` and `file_form(*,
root)` share one entry serializer (RF-54): in-checkout paths relative with `/`, private ones absolute;
UTF-8 JSON, indent 2, LF, a final newline; `saved_form` adds each entry's `case_file_sha256`, which
`file_form` (a set file) never writes. `set_digest` is the sha256 of the saved bytes, so it is the same
from any checkout location and platform; read back with `load_saved_set(path, *, root)`, a thin caller
of `load_set`'s core that accepts relative entries.

**PreflightedSet** (`benchmark/runner.preflight_set`, in memory): the loaded set with every package's
`package.json` present, every key present (stat only), every case file loaded and checked; required by
`run_benchmark` (INT-14).

## 5. Case specs and the generator's records  [generator.md; cases.md 5, 6]

Python frozen dataclasses under `reviewer/tests/benchmark_cases/`, never rendered: **CaseSpec**
(`case_id`, `design`, `variant`, `seeds`, `conditions`, `forbidden`, `expected_coverage`,
`unanswerable_requests`, `question_counts`, `answers`, `represents`, `decoys`, `twin`, `sets`);
**Seed** (`kind`, `at` role to place name, `tag` `HeldOut(stamp)` or `TunedOn(reason)`,
`represents`; the key-only entries carry an optional `represents` too, and one naming an anchor is
tuned-on, RF-80); **SeedKind** (`check`, `producer`, `expected_status`, `withheld` from
`joint_placement`, `joint_absent`, `tolerance_source`, `drawing_only`, planted and clean forms, the
correct call, decoys). Invariants: a seed's family is `families.family_of(check)`; withheld is
non-empty exactly when the producer is model; checks are exact; twins are derived (`<case>-twin`,
every seed in its clean form, each keyed as a correct condition, twin rule B, owner decision 24A).
Identity: the IR `package_id` inside `package.json` is `uuid5(CASE_NAMESPACE, case_id)`, a UUID
distinct from the set's and the key's `package_id`, which is the case id; `design.design_id` is the
case id (RF-75); IR pinned at 1.6.0; `created_at = mechanical.CREATED_AT`.

**Ingested drawing sheet** (`SheetBuilder`, `reviewer/tests/support/drawings.py`): a drawing
`Document` and its `pdf` manifest entry (one writer shared with `DrawingBuilder`), `DrawingSheet`s in
mm (unreadable: `no_text` and its gap), `Dimension`s `dim-<page>-<n>` with a bilateral, symmetric or
no tolerance and the text as read.

**Set summary** (printed by `swreview benchmark set-summary`, never stored): per judgement family,
held-out model-produced, with a clean twin, code-produced guards, tuned-on items, anchors and
analyst-found covered; the total against the floor of 34; the largest design share; stale held-out
items.

## 6. Session and event additions  [scoring.md 5.2; benchmark-run.md 6-8]

| Entity | Field | Rule |
|---|---|---|
| `InvestigationStep` (`report/session.py:55`) | `origin_mark: "prerun" \| "regrade" \| None` | set only by `prerun.recorded_call(mark=...)` after the call (`_prerun_call` prerun, `_restate` regrade); omitted when `None` |
| `ReviewSession` | `origin_marks: int \| None` | `ORIGIN_MARKS_VERSION = 1`, written by `start_review` on every new session, the pane's included; absence means origins unknown. Its commit regenerates the replay fixtures after 19A's, adding one `"origin_marks": 1` to each `session.json` and nothing else (RF-27) |
| `usage` event body | `served_model?`, `retries?` | `served_model`: the served id whenever the provider reports one, on every stream, the pane's included (RF-32); `retries`: only under a retry policy, which only benchmark attempts set |
| `error` event body | `stop_reason?`, `retries?` | `stop_reason`: only for a provider-reported stop, on every stream (RF-32); `retries`: only under a policy. Both on the adapter's body; the runner's generic body after an escaped failure (`emit_turn_failed`) carries neither, and readers read the fields, never count `error` events (RF-52) |

**Origin** (derived, never stored on a finding; `benchmark/origins.py`): `prerun`, `regrade`,
`code_only_call`, `configured_check`, `model`, `carried`, `setup`, `unknown`; first rule wins:
carried, model-written, no session record (unknown), the highest cited step's mark or tool
(`CODE_ONLY_TOOLS`, built from the pre-run's constants, RF-6, or else configured), no cited step
(`provenance.` is setup, else configured); a cited step the session does not hold reads unknown even
with the record, and a pane study holding such a false alarm has its verdict refused (SR-25).
`MODEL_ORIGINS = {model, configured_check}` decide the pane study's false alarms (17A, 20A).

**RequestCall** (derived by `benchmark/questions.py`): a `request_evidence` step with its stored
result: item, raw and instance-resolved ids, outcome (`recorded`, `already_answered`,
`already_asked`, `closed_by_code`), request id; an error envelope is no question.

## 7. The run folder  [benchmark-run.md; provenance.md]

**RunProvenance** (`<run>/run-provenance.json`, written once by `cli.py` before any review; strict):
existing fields (`commit`, `lever`, `arm`, `rep`, `provider`, `model`, `effort`, `max_steps`,
`checklist_digest`, `set_digest`, `started_at`, `set_too_small_override`, `efficiency`,
`explanations_enabled`) plus `provenance_schema` (2; absent reads 1), `pane_defaults`, `model_view`,
`profile_digest`, `profile_is_example`, `live_tools`, `inert_settings`, `prompt_digest`, `tree_dirty`
(slice 2); `max_answer_turns` (slice 3); `package_time_limit_s`, `stream_activity_window_s`,
`stop_grace_s`, `retry_policy`, `jobs` (slice 6; `jobs` how many packages ran at once, owner decision
36A). An absent field reads "not recorded". Never a path.
Must-match across a study: every field but `rep`, `started_at`, `live_tools`, `jobs` (record-only, 36A), the study key (`lever`,
`provider`, `model`), `arm` across the arms of every study (RF-10), and across a pane study's arms
`efficiency`, `model_view`, `pane_defaults` (the studied lever's flag, across a lever study's arms).

**AttemptRequest** (`benchmark/runner.py`, frozen, in memory; RF-44): what `run_benchmark` hands the
review function as its one new keyword, `attempt`, beside `provider`, `model`, `effort`,
`efficiency` and `explain_findings` (still forwarded only when true): `model_view` and
`standards_profile` (slice 2), `case_file` (the loaded `CaseFile` or `None`) and `max_answer_turns`
(slice 3), `stop` (slice 6, the attempt's stop event).

**RunStatus** (`<run>/run-status.json`, the driver's one scheduling thread only, through
`write_atomic`; packages in set order whatever order they end in, owner decision 36A): `run_status_version`
1; `packages{id: {kept_attempt, attempts[{attempt, started_at, ended_at, resumed, kind, class,
stop_reason, error_class, message, stream_active_at_limit, folder}]}}`; `message` is redacted of keys
and passed through `benchmark/scrub.without_local_paths`, so it names `<run>`, `<repo>`, `<tmp>` or
`<home>` and never a local folder (RF-41). Read only through `package_outcome()` and
`attempt_facts()`; usage, served ids and retries come from the attempt's events, which
`attempt_facts` finds through `event_stream`, plain or packed, and reads through `replay_events` into
`UsageLedger` (`rounds()`), never from this file (RF-29, RF-83).

Attempt state transitions:

```text
(started, kind null) --worker returns--> completed | behavioural(max_steps, truncated, provider_stop, wall_clock)
                     --any infrastructure condition--> infrastructure(provider_error, wrong_model,
                           served_model_changed, wall_clock_silent, abandoned, internal_error, interrupted)
completed | behavioural --recorded, then one rename--> kept: <run>/<package>/  (never appended to)
                       --rename fails--> recorded kept, still in attempts/ --resume--> renamed (RF-22)
infrastructure --stays in attempts/--> benchmark resume --> new attempt n+1 from the start
kind null on a folder no process runs --resume--> interrupted
every attempt with an outcome, promotions complete --benchmark pack--> each events.jsonl -> events.jsonl.gz, digest recorded
```

Precedence: the first infrastructure condition wins, then the first behavioural stop, else
completed. Reaching the answer-turn bound is completed (D16). Each attempt runs on a
`threading.Thread(daemon=True)`, so an abandoned one never holds the process at exit (RF-50). Resuming
a pane study re-applies `provenance.md` 3.2's tree rules before any review (RF-51). Up to `jobs`
attempts run at once (36A, RF-90): one scheduler, which `run_benchmark` and `resume_benchmark` both
call, starts them in set order through `attempt.start_attempt` and polls each **RunningAttempt** (in
memory: the attempt's worker, stop, listener and clock; `poll(now)` returns its outcome once there is
one, W, A and G applied without blocking) on its own thread, the only writer of the run's record;
the run-start adapter's one-shot holder is taken under a lock; resume runs at the recorded `jobs`.

**Attempt folder**: `session.json`, `events.jsonl` (`events.jsonl.gz` once packed), `attention.json`,
`tool-results/`, `prompts.json`, `answer-log.json`.

**EventStreams** (`<run>/event-streams.json`, written only by `swreview benchmark pack` through
`write_atomic`; model in `benchmark/streams.py`; slice 6; `provenance.md` 6.7; 28A, RF-82):
`event_streams_version` 1; `streams{path: sha256}`, `path` each packed stream's run-relative path
with `/` separators (`<package>/events.jsonl.gz`, `attempts/<package>/<n>/events.jsonl.gz`),
`sha256` the `digest.sha256_of_bytes` of its plain bytes, as the run wrote them; UTF-8 JSON, sorted
keys, LF. A later pack of the same run (after a resume) adds rows and never changes one. Read by
`benchmark pack` and by `test_committable_paths.py`, never by a scorer or report (RF-83). A packed
folder holds `events.jsonl.gz` and no `events.jsonl`; a folder holding both is an unfinished pack,
which `event_stream` refuses and a second pack finishes.

**PromptsRecord** (`prompts.json`, written by the benchmark attempt only, before the first turn and
when the body ends): `prompts_version` 1, `system` (`ReviewRun.system`), `user_messages[]` (every
`role: user` message of `ReviewRun.messages` in order; message `k` opens turn `k`). Absent reads "not
recorded".

**RetryPolicy** (`agent/providers/retry.py`): `retries`, `initial_delay_s`, `max_delay_s`;
`BENCHMARK_RETRY = (5, 2.0, 60.0)`; reaches an adapter only through the optional
`use_retry(policy, *, stop_requested)`, which the attempt body calls (RF-20); no call keeps each
library's own behaviour; the loop retries only before a request's first text delta, never once
the attempt's stop is set and never an error carrying `stop_reason` (RF-76); the adapter emits one
`error` per failed request (RF-52). **ProviderError**
(`agent/providers/__init__.py`): base of both adapters' errors, with `error_class`, `retryable`,
`stop_reason`, each a class-level default (`error_class` falling back to the class name,
`stop_reason` `None`) and no `__init__` of its own, so both families construct unchanged (RF-72).

**PriceTable** (`benchmark/prices.yaml`, strict): `prices_version`, `currency`, `per_tokens`,
`models[{provider, model, input, cached_input, output}]`, each price with `source` and `date`; three
prices per model (FR-042) and no tiers (RF-8), with an optional `short_context_max_input_tokens` above which a round reads cost unknown (103A), cache-write tokens counted and never priced. **Cost**:
amount or `null`, `missing[]`, basis notes, `synthetic`; priced per round by `price_rounds`.

## 8. The scorecard  [scoring.md 3-9; questions.md 6]

`scorecard.json`, written by `benchmark score`, read only through `read_scorecard(run_dir)`, which
checks `scoring_rules_version` before validating and refuses a lower or higher one.

**PackageScore** gains (all required; lists in key order; counts derived where rendered):

| Group | Fields |
|---|---|
| Defects (13A) | `matched_defect_ids` (detected), `flagged_defect_ids`, `status_mismatch_defect_ids`, `flagged_below_expected_defect_ids`, `cleared_defect_ids`, `missed_defect_ids` |
| Conditions | `contradicted_condition_ids`, `confirmed_condition_ids` (`null` with no condition) |
| False alarms | `false_alarm_finding_ids`, `forbidden_hit_finding_ids`, `withdrawn_forbidden_hit_finding_ids`, `tuned_on_false_alarm_finding_ids` |
| Coverage | `coverage_mismatches[{entry, item, read}]` |
| Origins, items | `finding_origins{finding id: Origin}`, `graded_items[{id, kind, tag, producer?, expected_status?}]` |
| Questions | `re_asks`, `open_repeats`, `unanswerable_requests`, `unmatched_requests`, `question_counts`, `unscripted_questions`, `bound_reached` |
| Reasons | `not_assessed{column: reason}`, the one map for every `null` column |
| Run (slice 6) | `run_status{kind: completed|behavioural|not_recorded, class, stop_reason}`, `cost`, `served_models` (the kept attempt's distinct served ids, `[]` when none reported; RF-16) |

Invariants: matched, flagged below expected and missed are disjoint; every other defect is cleared;
flagged and mismatches lie within matched and are disjoint; missed and cleared are disjoint.

**Scorecard** gains `scoring_rules_version` (2 in slice 1, 3 in slice 3, the next with slice 6's run
fields), `key_sha256{package id: hex}`, and in slice 6 `unscored_packages[{package_id, kind, class,
error_class, attempts, folder}]` (infrastructure failures: no session, no `PackageScore`),
`failed_attempts[{package_id, attempt, class, retries, cost, folder}]`, `folder` run-relative
(RF-17), and `price_table` (`null` when no round was priced, else `{prices_version, models[{provider,
model, input, cached_input, output}]}`, each price's `{source, date}` as `benchmark/prices.yaml`
holds it, for every entry a round of the run was priced by; outside the golden view, RF-45);
`per_package` may be empty.
**Aggregate** gains the summed outcome counts, `findings_by_origin`, `false_alarms_by_origin`,
`recall_by_producer{model|code: {held_out, tuned_on}}`, `held_out_model_defects` (from every package's
key, before failures), the question sums, and in slice 6 `cost` and `failed_attempts_cost`; a column no
package assesses is `null`; `packages` may be 0.

**Golden scorecards** (`reviewer/tests/golden/test_golden_scorecards/<case>--<review>.yml`): the golden
view is `PackageScore` less `GOLDEN_EXCLUDED` (`session_id`, timing minutes, `usage`, `round_trips`,
`cached_input_share`, `wall_clock_s`, `seconds_to_first_finding`, `tool_calls_by_name`, `cost`,
`served_models`), for
each committed case's oracle and null reviews and each probe (`reviewer/tests/support/scoring_probes.py`,
beside `MATCHING_RULES`). The oracle and null reviews are written as package folders, `session.json`,
a one-event `events.jsonl` and the oracle's stored request results, and scored as a run's package is
(RF-58). `GOLDEN_IDENTITY` (`package_id`, `held_out`, `graded_items`) is in the view
and moved by no probe, pinned by its own test; every other field of the view is declared by a probe
(RF-43). **Version record** (`reviewer/tests/golden/scoring_rules_versions.json`):
rows `{version, goldens_sha256, reason, goldens_unchanged?}`, appended, never edited, the first at
version 3; the digest reads each golden as git stores it (CRLF as LF); consecutive versions; no two
rows share a digest unless the later declares `goldens_unchanged: true` with its reason (a bump that
moves only fields outside the view, RF-21); an edited committed row is left to review (RF-69).

## 9. The ledger  [provenance.md 5; verdict.md 8]

`ledger.json` schema `1.1` (one bump, slice 2) and `ledger.md` / the committed block.

- **RunRow** gains `model_view` (from the session), `profile_digest`, `live_tools`, `pane_defaults`,
  and the scorer's outcome columns; the run table's final order is `provenance.md` 5's. The decision
  table gains recall by producer. The pane baseline's label is `none (pane defaults)`.
- **PaneStudy** (`pane_studies[]`, omitted when none; filled from slice 7): `study`, `provider`,
  `model`, `commit`, `slice` (`committed` for `pane_defaults`, `private` for
  `pane_defaults_private`), `run_dirs`, `reps{off, on}`, `verdict` (`quality loss`, `no 10-point loss`,
  `inconclusive`, or `null` with `refusal`), `reasons[]`, `approval{...}`, `figures{main, sensitivity}`
  each with retained and dropped defects and packages and the `recall` and `false_alarms`
  **PairedInterval**s (`estimate`, `lower`, `upper`, `alpha`, `df`, `packages`, `computable`,
  `loss`), `code_guard`, `cleared_guard`, `noise_floor {state, points, seed, numpy}` (`state`
  `computed`, `not_computed` or `stale`, read from the noise-floor record, RF-53),
  `arms_differed_in`, `inert`, `untested_between_turns[{setting, reason}]` (RF-14), `shown[]`
  (**ShownMeasure**: per-arm values, estimate, two-sided 95% interval, `excludes_zero`). Rates stored
  as fractions, rendered in points; `null` renders unknown.
- **Pilot runs** live under `benchmarks/pilots/`, which `recorded_runs()` never scans, so they never
  enter a study; compare renders them as raw rows from the matched measurement's `pilot_runs` list,
  the arm cell reading `off (pilot)`, in no count (RF-36).
- **Set flags**: compare checks each scored package's saved-set `held_out` against "some
  `graded_items` entry is held out", a mismatch a run-level refusal (RF-39), and refuses a scored
  package the saved set does not hold (RF-62); both only where the saved copy exists.

## 10. The verdict's working records  [verdict.md]

- **StudyStats** (memory only): arrays with a leading study axis: per defect, arm and figure the
  detections and counted runs with the package index; per package, arm and figure the deciding false
  alarms and counted runs; code-defect detections; clears; ids on the compare path. Built by
  `study_stats(runs)` or by the simulator; judged only by `verdict.judge`.
- **Simulation scenario** (named constants in `benchmark/simulate.py`): rate distribution, shock SD,
  layout and growth unit (SC-010's for the reference scenarios; the committed set's after the pilot),
  false-alarm model, stops, clearances, code-produced defects, the drop and its two shapes, the
  `alpha` ladder, 4,000 simulations, seed, cap, floor.
- **PilotMeasurement** (`benchmarks/pilots/<study folder>/pilot-measurement.json`, beside the
  pilot's own run folders, RF-36; model and digest in `benchmark/pilot.py` from slice 7, RF-37; no
  absolute path): identity (`pilot_schema`, study, provider, model, commit, `set_digest`, scorer
  version), `pilot_runs[]` (folder relative to the file, arm, repetition, `started_at`, commit),
  `smoke_runs[]` (quickstart P0's two runs, the same fields, a time input only; owner decisions 35A
  and 36A), `measured` (per-defect `x/n`, the defects dropped with no counted run and those left out of the
  Beta fit's variance with one, each named and counted (RF-9), Beta fit, co-movement grid and the SD
  used, code defects, stops, clearances, false-alarm fit, cost and time, never-detected list),
  `sizing` (cap, floor, seed, sims, ladder, every size tried, `pilot_packages` (the package ids of
  the paid pilot runs' saved sets, which is the committed set at the pilot's commit, sorted; never
  `benchmarks/sets/pilot.json`'s), `growth_units` (0 when none), `jobs`, the result with `projected_wall_clock`: per arm one run's
  projected seconds at `jobs`, the study's, the smoke ratio and its two sums, the mean tokens per
  minute of one off-arm review; 36A, RF-91), `sizing_digest`,
  `approval{approved, approved_at}`; `sizing_digest` is `digest.canonical_sha256` of every block but
`approval` (RF-65). State: written `approved: false`, never over an existing file
  (`benchmark pilot` refuses one, so a study has one measurement, RF-40); the owner sets `approved:
  true` and a date on or before the first study run and changes nothing else; compare recomputes the
  digest and refuses an edited, unapproved or late approval, and a study whose saved sets lack a
  `pilot_packages` id or hold fewer than `growth_units` core cases beyond them, a unit being a
  package whose items hold a held-out known defect, never a twin (RF-66).
- **NoiseFloorRecord** (`benchmarks/studies/<study folder>/noise-floor.json`, written once by
  `swreview benchmark noise-floor` after the study's last repetition, through `write_atomic`; model
  and reader in `benchmark/simulate.py`; RF-53): `noise_floor_schema` 1, the study key (study,
  provider, model), `runs_digest` (`digest.canonical_sha256` over the sorted pairs of each study run's
  relative folder and its parsed `scorecard.json`'s `canonical_sha256`, so the scorecard's line
  endings and key order move nothing, RF-56), seed, sims, `numpy_version`, the grid, and the result (points,
  `above 50 points` or `not attainable`). Compare reads it and simulates nothing: no record reads
  `not_computed`, a record whose `runs_digest` differs from the compared runs' reads `stale`; neither
  refuses anything.

## 11. Settings and study constants  [benchmark-run.md 2; provenance.md 3]

- **ResolvedReview** (`cli._review_settings`): `efficiency`, `model_view`, `explain_findings`; a
  typed flag wins, else the base (`pane_defaults(provider)` with `--pane-defaults`, else all off).
  `_review_settings` also takes `study`, `arm` and `allow_workstation_levers` (defaults: today's), so
  `benchmark run` keeps its workstation-lever refusal and study checks through it (RF-19).
- **PaneDefaults** gains `explain_findings` (`True`); the chat server reads it.
- **Study names** (`agent/settings.py`): `PANE_STUDY = "pane_defaults"` (committed set, the example
  profile, arms `on`/`off`, explanations typed, known commit, clean tree),
  `PRIVATE_PANE_STUDY = "pane_defaults_private"` (the real profile, private packages, `--out` outside
  the repository). **INERT_SETTINGS**: Gemini `("parallel_tool_calls", "drop_prior_reasoning")`,
  otherwise empty. **BETWEEN_TURN_SETTINGS**: `("drop_prior_reasoning",)`, the settings that act only
  at a turn boundary, which the verdict names as untested when no held-out case takes an answer turn
  (RF-14).

## 12. The report  [report.md]

Output only, never committed: `<out>/index.html` (run heads with the price table's sources and dates
from `Scorecard.price_table`, totals, one section per case with a
row per run folder: status, held-out, code-produced and tuned-on detections, false alarms by
deciding and other origin, tokens including cache-write, cost with its basis, wall clock, a link) and
`<out>/transcripts/<run>/<package>.html` (header, system prompt, legend, the log in order with each
turn's user message, answers, calls with full results, findings, final-state grading, failed
attempts). Every number is the scorecard's; no script, no timestamp, no local absolute path.
