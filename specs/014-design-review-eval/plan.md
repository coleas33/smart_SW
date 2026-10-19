# Implementation Plan: Design-Review Eval

**Branch**: `014-design-review-eval` (from `main` at `5cfb743`) | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md) | **Tasks**: [tasks.md](tasks.md)

**Input**: the spec (FR-001 to FR-061; owner decisions 1A to 36A; defaults D1 to D17), [research.md](research.md)
§1 to §8, and five area designs, integrated here. Every plan-level decision, the areas', the
integration's, the three review rounds' (§9.9 to §9.11), those applying 28A (§9.12) and those applying 33A to 36A,
from the owner's review of this plan on 2026-10-06 in CLAUDE.md's SMALL CHANGE form (31A, 32A; §9.14), is recorded with its rationale and
alternatives in research.md §9, which also marks every §4 cross-check item and §8 open point
resolved. Line numbers are at `5cfb743`; paths are under `reviewer/src/swreview/` unless another root
is given.

## Summary

Make `swreview benchmark` able to decide whether the Task Pane defaults cost review quality, in the
order 12A and 14A fix:

1. **Scorer** (US1): one matcher, exact check or `x.*` family, parts, drawing locations or (only
   then) provenance documents, and for joints, alignments, fits and stacks the exact references
   (`contracts/scoring.md` 2); 13A's status table; correct conditions with ids; eight origin values
   from a step mark and a session record; recall by producer and tag; key format 2 with its load-time
   refusals and held-out stamps over the prompt, the checklist and the tool descriptions (25A;
   `contracts/answer-key.md`); a scoring-rules version compare refuses before validation.
   With it the product change 19A: every fastener-joint result names its fastener and hole on every
   path. 19A and origin marks land as two commits, 19A first (RF-27).
2. **Parity** (US2): `benchmark run` resolves `--pane-defaults`, model view, explanations and the
   profile through `review`'s one resolver; provenance schema 2 written before any review; one
   must-match loop over every recorded field; the pane study, the pane baseline and the private
   study as their own keys; a location-free saved set; D12's profile stamp without its folder; one
   ledger schema bump with the final column order.
3. **Key extensions and scripted answers** (US3, US4): forbidden entries, expected coverage read
   with the report's own reader, the one question matcher and its columns; case files played through
   `answer_evidence_batch`, the method the pane's Send reaches, with a bound and an answer log.
4. **Generator and validation** (US5, FR-049): a committed generator writes 48 fictional packages
   (47 committed, one fully clean twin per core case, 24A; 1 pilot), their keys, case files and
   sets; an offline validation proves each
   producer tag and each key's reachability, and writes the golden scorecards and the version record.
5. **Report** (US6): one static HTML page and a transcript per package run, from run folders alone.
6. **Robustness** (US7): each attempt on a worker under a wall clock, request-level retries,
   served-model and provider-stop classes, `run-status.json`, promotion, `benchmark resume`, a dated
   price table; and `benchmark pack`, which compresses a finished run's event streams, each with its
   digest recorded, before the run's folder is committed (28A); `benchmark run --jobs N`, up to N
   packages at once, one thread writing the run's record, N recorded and never must-match (36A); a
   live test of one real attempt, run on demand (35A); then one Task Pane smoke review of the small
   assembly on the pilot workstation, before any paid run (33A).
7. **Simulator and verdict** (US8): a package-level t interval, one `judge` shared by compare and a
   simulator of 39 reference scenarios, and the three-valued verdict.
8. **Pilot and cost gate** (FR-055): first a paid smoke run, P0, two packages at one repetition per
   arm, every row read and any wiring fixed before the pilot (35A); then an off-arm pilot of 3
   repetitions over the committed set (27A), measured, sized, its study's wall clock projected at the
   chosen concurrency from P0's and the pilot's review times (36A), and approved by the owner.
9. **The paid pane study**, then the private slice as its own row.

Everything but the paid review calls runs offline with no key and no licence (FR-047). SOLIDWORKS is
never started by the eval or its tests; the one seat task, the Task Pane smoke review after slice 6's
gate (33A), is a paid review of the pane itself, one of the paid review calls FR-047 excepts. The
owner's review of 2026-10-06 also puts the add-in's page and host tests and a replay of the recorded
pane sessions into the gates of slices 1, 2 and 6 (33A), and makes `write_atomic` the only atomic
writer, the product's three older copies moved onto it in Phase 2 (34A).

## Technical Context

**Language/Version**: Python 3.11+ (the reviewer only). No C#, no JavaScript: the report is static
HTML written by Python with no script (`contracts/report.md` 1). The one file under `extractor/`
this feature moves is the add-in's JSON pane fixture, regenerated by D12's commit (RF-28).

**Primary Dependencies**: no new package. numpy (already a dependency, `reviewer/pyproject.toml:19`)
for the simulator's quadrature and random draws; the Student t distribution function is its
closed-form finite series for integer degrees of freedom, pinned (no scipy; RF-34); pytest-regressions
for golden scorecards, as the check goldens use it (`reviewer/tests/golden/test_golden.py:9`); the
existing `openai` and `google-genai` clients. Reused, not rebuilt (research §7 and §9): `_review_settings`
(`cli.py:407`, with RF-19's parameters), `start_review` and `answer_evidence_batch`
(`agent/runner.py:1497, 1138`), `finding_groups.goal_of` and the state decision of `_goal_line`
(`report/finding_groups.py:167, 207`, extracted as `goal_readings`, RF-23), the covering predicate of
`covering_requests` (`report/session.py:184-213`, extracted as `covers`, RF-6), the pre-run's tool
constants (`prerun.py:144-159, 209-213`), `_documents_named` (`tools/session.py:280`, made public),
`resolve_dimension` (`tools/refs.py:49`), `recorded_call` (`prerun.py:1201`), the pane's `TurnStopped`
and `StoppableTools` (`chat/server.py:434-466`, moved, forwarding lever 7's `tools_withdrawn`, RF-18),
the product's event-line reader `replay_events` (`chat/sessions.py:106-129`, moved beside
`EVENTS_FILE_NAME` in `agent/events.py` with an `on_unreadable` hook, RF-29), the replay's
stored-result check (`benchmark/replay.py:1012-1036`, extracted beside its writer as
`tools/registry.read_stored_result`, RF-30), `UsageLedger` (`agent/events.py:134`, gaining a public
`rounds()`), `load_profile` (`checks/standards/profile.py:617`), the fictional builders
(`reviewer/tests/support/`), `as_committed` (`reviewer/tests/unit/test_support_mechanical.py:266` and
`test_support_drawings.py:253`, moved once, RF-55), `sha256_of` (`benchmark/runner.py:100`, moved to a
dependency-free `benchmark/digest.py` and re-exported, RF-48), `generate_pane_fixture.py` (D12's pane
fixture, RF-28), `scramble._WINDOWS_ANCHOR` (`reviewer/tests/support/scramble.py:299`, made public).

**Storage**: files only. New: `run-status.json`, `attempts/<package>/<n>/`, `prompts.json`,
`answer-log.json` in run folders, and in a packed run folder `events.jsonl.gz` in place of each
`events.jsonl` with `event-streams.json` recording each stream's digest (28A, RF-82); the paid
smoke run's (P0, 35A) and pilot's run folders and `pilot-measurement.json` under `benchmarks/pilots/<study folder>/` (RF-36);
`benchmarks/sets/pane-smoke.json`, P0's two-package set, generated (35A, RF-89); `noise-floor.json` beside a pane study's folders (RF-53);
keys in format 2; case files under `benchmarks/case_files/`; `benchmark/prices.yaml`;
`reviewer/tests/golden/scoring_rules_versions.json`. Changed: `run-provenance.json` (schema 2; `jobs` from slice 6, record-only, 36A), the
saved set (location-free LF bytes), `scorecard.json` (`scoring_rules_version`, new required fields,
`price_table`, RF-45), `ledger.json` (1.1). Every record this feature writes goes through one
`write_atomic` (RF-31), and so do the product's three older atomic writes, moved onto it (34A, RF-88):
the review's `attention.json` is then LF on Windows too, where its text-mode write gave CRLF. `session.json` gains two optional fields omitted when absent. The `usage` body
gains an optional `served_model` and the `error` body an optional `stop_reason`, written on every
stream, the pane's included (feature 002's schema amended; RF-32); both bodies gain `retries`,
written only under a retry policy, which only benchmark attempts set. No IR schema change; generated
packages pin 1.6.0.

**Testing**: pytest (`SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts=""`,
`-m "not live"` where needed) and `uv run ruff check src tests`; opt-in markers `perf` (the report's
budget) and `simulation` (the 39-scenario sweep, run before any approval); the replay gate of each
change that regenerates the replay fixtures (the delivery order's slices 1 and 2; RF-2, RF-27,
RF-28); at the gates of slices 1, 2 and 6, the add-in's page and host tests (from the repository root on
Windows, `dotnet build extractor/SwReview.sln -c Release --nologo -v q` with zero warnings and `dotnet
test extractor/SwReview.sln -c Release --no-build --nologo`) and a replay of the recorded pane sessions,
the committed replay fixtures through the replay gate's steps 2 and 3 (013 `contracts/tokens.md` section
5), the pane's behaviour unchanged but for the evidence this plan allows (33A, RF-87); `-m live` for
`tests/live/test_benchmark_live_attempt.py`, one real attempt end to end, run on demand only and first
at P0 (35A, RF-89). New tests under `reviewer/tests/integration/`
that need no native package carry no `integration` marker, which is skipped wherever the native
package is absent (RF-26). Every behaviour names its failing test in its contract; the contracts'
test lists are the tasks' test tasks.

**Target Platform**: the development machine (Windows, `core.autocrlf true`) and any Linux checkout,
offline; paid runs on a machine with a provider key. SOLIDWORKS is never started by the eval or its tests;
benchmark attempts pass `bridge=False` and record it (`live_tools`); the one seat task reviews in the
Task Pane on the pilot workstation (33A).

**Project Type**: extends the reasoning side's benchmark harness (`benchmark/`, `cli.py`), with four
product changes (19A, origin marks, D12, and 34A's move of the product's three older atomic writes onto
the one writer) and small product seams (retry policy, served model, stop
reason, `PaneDefaults.explain_findings`, the event-line and stored-result readers moved beside their
writers).

**Performance Goals**: the validation over the committed set under three minutes; the report for
940 transcripts, the committed set at the cap in both arms (47 × 10 × 2), their streams packed (28A), under 60 s, above SC-009's
800 (RF-46); the simulator's intercept table about 50 ms per 4,000 studies; the default simulator
tests in the default suite, the full sweep about 4 to 6 minutes opt-in; compare simulates nothing
(the noise floor is read from its record, RF-53); a paid study's wall clock is projected at the cost
gate, at the `--jobs` N the owner chooses (36A, RF-91).

**Constraints**: Principles I to VI; the public repository holds no company value, real design name,
vault path or local absolute path (FR-048, FR-051), which the harness keeps out of the failure
messages it writes (RF-41, RF-73) and a scanner checks; runs never read keys (FR-032); the pane's
behaviour is unchanged wherever this feature adds an option (no retry policy, no `retries` field,
no `prompts.json`), and the pane's records gain only evidence: `served_model` and `stop_reason` on
its stream (RF-32) and the origin-marks record on its sessions (RF-27), their one byte change being
34A's, the attention record's line endings on Windows; checked at the gates of slices 1, 2 and 6 by the
add-in's tests and a pane replay, and once on the seat before any paid run (33A); owner decisions are fixed;
unknown is never 0.

**Scale/Scope**: 8 user stories; 61 FRs; 47 committed packages (36 held-out model-produced defects),
1 pilot-set package, 1 key-only key; 39 simulation scenarios; up to 94 × R paid reviews per pane study.
No NEEDS CLARIFICATION remains: every open point is resolved in research §9; of §9.7's owner
questions, 1, 2, 3 and 5 are answered (24A to 27A), 4, 6 and 7 keep their defaults, and 8 gates
slice 4, the plan proceeding on its option B. 28A (the committed event streams compressed) and 29A
(the tasks generated before the owner's review of the plan) followed the third round (§9.12). The owner
reviewed the plan on 2026-10-06 in CLAUDE.md's SMALL CHANGE form (31A, 32A), one question per review
section, and took 33A to 36A, which RF-87 to RF-91 apply (§9.14).

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 design.*

| Principle or section | Gate | How this plan meets it | Status |
|---|---|---|---|
| I. Evidence before conclusions | Unknown stays unknown; nothing dropped | Not-assessed columns are `null` with reasons, never 0 (`scoring.md` 7); origin `unknown` without the session record; cost `unknown` naming what is missing; an unreported served model fails nothing; the served model and a provider's stop reason are recorded on every stream, the pane's included (RF-32); a cleared defect is its own column; failed packages are listed, never scored as "found nothing"; 19A makes an unresolved joint name its joint | PASS |
| II. Deterministic numerics | The model computes no verdict | Matching, outcomes, intervals, the simulator and the verdict are code; no judge (8A); the model's words are never parsed; the noise floor is simulated once and stored, so compare renders the same bytes on every supported Python (RF-53), and its `runs_digest` reads each scorecard's canonical JSON, so every checkout agrees (RF-56) | PASS |
| III. Test-first, golden fixtures | Failing tests first; goldens follow code | Every contract lists the failing tests that pin it, invalid inputs included; golden scorecards and probes under a two-way version rule (SC-013); 19A regenerates its five check goldens and adds `joint-unknown-role` for the joint map's changed path, its replay regeneration asserted byte-identical; origin marks then regenerate the replay fixtures, differing only by one `"origin_marks": 1` in each `session.json` (RF-27); D12 regenerates the standards goldens, the replay fixtures and the add-in's pane fixture (RF-28); each in one change, in that order (008's 3A; RF-2); the existing tests the scorer moves are rewritten in its slice (RF-49); the validation is itself test-first (`cases.md` 7) | PASS |
| IV. Semantic fidelity | Persistent references; versioned schemas | 19A puts the joint's fastener and hole ids on every result (FR-061); keys reference package ids and dimension triples; generated packages pin IR 1.6.0; scorecard, provenance, key, case file, answer log, run status, pilot and noise-floor records are versioned | PASS |
| V. Engineered enough | DRY; explicit; edge cases named | One matcher (`benchmark/matching.py`), one question relation (built on the product's `covers`), one settings resolver, one root for set paths (`load_set(path, *, root)`), one set serializer with its file and saved forms (RF-54), one stop mechanism (the pane, the attempt and the replay, which calls `end_stopped` unconditionally, RF-3, RF-33), one `judge`, one event-line reader (the product's `replay_events`, read by the scorer, the report, the recording reader and `attempt_facts`, RF-29), the scorer, the report and `attempt_facts` finding a run's stream, plain or packed, through one resolver beside it (`event_stream`, 28A, RF-83), one packer and one digest record for the committed streams (`benchmark pack`, RF-82), one stored-result reader beside its writer (RF-30), one atomic writer, the product's three older copies moved onto it (RF-31, 34A, RF-88), one package scheduler shared by `benchmark run` and `benchmark resume` and the only writer of `run-status.json` (36A, RF-90), one raw-bytes digest and one canonical-JSON digest in a dependency-free module (RF-48, RF-56) and one digest display, one reading of a key's held-out flag and count (RF-67), one `not_assessed` map, one golden writer, one key-format definition, one key-writing test helper (RF-49), one `as_committed` (RF-55); the code-only tool set built from the pre-run's constants; every edge case named in a contract. What exceeds the simplest design is in Complexity Tracking | PASS |
| VI. Findings inspectable; coverage tracked | Quality measured per design | Coverage graded through the report's own reader; forbidden, withdrawn, re-ask and unanswerable columns; per-case transcripts; failures by kind and class | PASS |
| Documents are read, not written | No mutation | No document is opened for writing; no SOLIDWORKS call by the eval; live tools absent and recorded; the one seat task (33A) is a Task Pane review, which reads its documents and writes none | PASS |
| Reasoning side offline, no licence | Runs in CI | FR-047: everything but paid calls offline; without the tokenizer, counts read unknown and nothing refuses (`benchmark-run.md` 15); the one seat task (33A) is the pane's own paid review, on the seat, outside the eval's offline half, and the live test (35A) is skipped without a key | PASS |
| Curated tools; licences | No generic execution; licences respected | No tool added or re-described; 19A adds ids to existing results; no new dependency; the tokenizer vocabulary stays out of the repository | PASS |
| Product changes 19A, origin marks, D12 and 34A | Surgical; fixtures follow code | 19A is owner-sanctioned, origin marks are FR-007's session record, D12 is a default the spec takes; each lands as one commit with every fixture it moves, in the order and under the gates of "Sequencing" below (RF-2, RF-27, RF-28), with no C# change; origin marks apply to every review, the pane's included, and the pane's stream also gains `served_model` and `stop_reason` (RF-32). 34A moves the product's three older atomic writes onto `write_atomic`, each with its failing-first test, the attention record's bytes LF on Windows and the other two unchanged (RF-88). Findings' text unchanged; 19A and D12 justified in Complexity Tracking | PASS |
| The generator | No gold derived from check output | Imports only data models and fictional builders (`generator.md` 9): the key's format through the data-only `benchmark/answer_key_model.py`, never the key loader, which calls the matcher, the question reader and tool logic (RF-1); the structural test checks direct imports, and imports each data-only format module (the key's format, `case_file`, `sets`, `families`) and `benchmark.digest` alone to fail on any tool, agent or check module it loads (RF-48); byte-for-byte regeneration through the set's `file_form` (SC-006, RF-54); reachability proved by a separate validation (FR-054) | PASS |
| Development workflow: acceptance suite | 5 to 10 representative designs, keys withheld, some held out | 10 committed designs, within 5 to 10: the nine core designs of `cases.md` 6.2 and `mir`, the sitting's (6.3); plus the two real designs of the private slice, 23A's own study, shown and never deciding (RF-7). The spec's Assumptions line (`spec.md:428`, from D14.7) now reads the same: RF-7's reading, the private slice shown beside the suite and never deciding, was written into it (RF-47). Keys withheld by the loader guard and the run's refusal to open them; held out per item (15A). **How representative** (spec Assumptions): the nine core shapes are small mechanical assemblies of the kinds the pilot's reviews meet (`cases.md` 6.2's shape table: dowelled plates, a bracket on a base, a clevis, a bearing housing, a flange coupling, a motor mount, a carriage on a rail, a gear cover, a clamp block), and the anchors are the sitting's and the analysts' own defects (6.3). The known gap is size: every committed design is a small assembly of two to five part documents, while the pilot's real designs include large assemblies (the big assembly's 68 screws, research §3), where payload slimming and history pruning act most; the private slice covers that gap and is shown only | PASS |
| Spec Kit cycle; review gates | Plan reviewed before tasks | The plan was reviewed in three rounds before the tasks (research §9.9 to §9.11); 29A: the tasks are generated now and the owner reviews the plan and the tasks together before any implementation; the owner reviewed the plan on 2026-10-06 in CLAUDE.md's SMALL CHANGE form (31A, 32A) and took 33A to 36A, which the plan and the tasks apply (RF-87 to RF-91, §9.14); research §9.7's owner questions answered (24A to 27A; question 8 answered B on 2026-09-30, 30A, which slice 4's tasks follow) or kept at their defaults; each slice has a gate below | PASS |

**Post-design re-check**: passed; exceptions only as Complexity Tracking lists.

## Project Structure

### Documentation (this feature)

```text
specs/014-design-review-eval/
├── spec.md, plan.md, research.md (§9: plan decisions), data-model.md, quickstart.md
├── contracts/{README.md, scoring.md, answer-key.md, questions.md, scripted-answers.md,
│              benchmark-run.md, provenance.md, cases.md, generator.md, report.md, verdict.md}
└── checklists/requirements.md
```

### Source Code (repository root)

Lane letters are the "Lanes and file ownership" table's; a number is the slice (delivery order).

```text
reviewer/src/swreview/
├── atomic.py                      # P2 NEW write_atomic, the one atomic writer (RF-31); the product's three older copies moved onto it (34A, RF-88)
├── benchmark/digest.py            # S1 NEW sha256_of, moved from benchmark/runner.py, and canonical_sha256, dependency-free (RF-48, RF-56); B6 sha256_of_bytes, which sha256_of then calls (28A's stream digest, RF-82)
├── benchmark/matching.py          # S1 NEW the one matcher (check, targets, references, overlap)
├── benchmark/origins.py           # S1 NEW Origin, MODEL_ORIGINS, CODE_ONLY_TOOLS, finding_origin (RF-68)
├── benchmark/answer_key_model.py  # S1 NEW the key's format, data only (RF-1): defect and condition models, Stamp, the pattern grammar, the reference kinds, rows 1, 3-5, 6's grammar, 7, holds_held_out and held_out_model_defect_ids (RF-67); S3 the four extension lists' models
├── benchmark/answer_key.py        # S1 load_answer_key: rows 2, 6's typo guard, 8, 12-14, current_stamp with 25A's tool_descriptions_digest (RF-64); S3 rows 9-11
├── benchmark/scorecard.py         # S1 outcomes, conditions, false alarms, origins, graded_items, recall, key_sha256, version 2, read_scorecard; S3 forbidden, withdrawn and tuned-on hits, coverage, questions, one pass over the event lines through replay_events (RF-29), version 3; B6 run_status, cost, served_models, price_table (RF-45), unscored, failed attempts with folders
├── benchmark/questions.py         # S3 NEW request calls (stored results through read_stored_result, RF-30), QuestionIds, asks_within (wrapping report.session.covers), part-roles identity, columns
├── benchmark/case_file.py         # A3 NEW CaseFile, ScriptedAnswer (data only)
├── benchmark/answers.py           # A3 NEW load_case_file, drive_review, AnswerLog; B6 stop_requested
├── benchmark/sets.py              # P2 REPO_ROOT (moved), SetError with its "benchmark set {file name}:" prefix and row 3, load_set(path, *, root), file_form and saved_form (RF-54), load_saved_set; A3 case_file, case_file_sha256, row 5's case-file half; G4 key, design, twin_of, represents, keyed and keyless sets, rows 1, 2 and 4 to 7
├── benchmark/runner.py            # S1 sha256_of re-exported (RF-48); P2 RunProvenance schema 2, REPO_ROOT imported from sets, run_benchmark's root (RF-61), AttemptRequest with the model view and the profile (RF-44); A3 preflight_set (case files, the package id `attempts`), the PreflightedSet argument in place of the path and root, max_answer_turns, AttemptRequest's case file and bound; G4 existence checks; B6 attempts on a daemon worker (RF-50), run status, promotion, resume (RF-51's tree rules), package_outcome, attempt_facts (RF-29), messages without local paths (RF-41), AttemptRequest.stop, the one package scheduler of `--jobs` shared by run and resume (36A, RF-90)
├── benchmark/replay.py            # S3 _stored_result through read_stored_result (RF-30); B6 TurnStopped and end_stopped, unconditional, in place of _Stop (RF-3, RF-33)
├── benchmark/families.py          # G4 NEW family_of, ANCHOR_FAMILY
├── benchmark/set_summary.py       # G4 NEW
├── benchmark/report_page.py       # R5 NEW; R6 status and cost columns
├── benchmark/recording.py         # R5 _events replaced by replay_events, raising on the reported line (RF-29)
├── benchmark/attempt.py           # B6 NEW worker, wall clock, classification (the inferred Gemini overflow, RF-77); start_attempt and RunningAttempt.poll for the scheduler (36A)
├── benchmark/scrub.py             # B6 NEW without_local_paths (RF-41)
├── benchmark/streams.py           # B6 NEW pack_run and the event-streams record: packed streams and their digests (28A, RF-82)
├── benchmark/served.py            # B6 NEW aliases
├── benchmark/prices.py, prices.yaml  # B6 NEW
├── benchmark/stats.py, verdict.py # V7 NEW
├── benchmark/simulate.py          # V7 NEW scenarios, searches, the noise-floor record and its reader; V8 the noise floor's computation (RF-53)
├── benchmark/pilot.py             # V7 NEW PilotMeasurement, its digest and reader (RF-37); V8 the estimators, the sizing search, the smoke runs and the projected wall clock (35A, 36A, RF-91)
├── benchmark/compare.py           # S1 read_scorecard, key digests; P2 must-match loop, studies, cross-checks, the set-flag and missing-entry checks (RF-39, RF-62), columns, 1.1; R5 public _count/_distinct; B6 served-model re-check from served_models; V7 pane routing, refusals, pane_studies, --pilot, recorded_pilots over benchmarks/pilots/, pilot raw rows from the measurement (RF-36, RF-37), the noise-floor record (--noise-floor, recorded_noise_floors, RF-53)
├── cli.py                         # S1 score summary; P2 resolver, run options, refusals (row 1 without the resume pointer; row 3's adapter handed to the first attempt, RF-60), provenance first, _review_fn taking attempt (RF-44); A3 _review_fn driver, --max-answer-turns; G4 set-summary, --answer-keys optional; R5 report, prompts.json; B6 attempt body, use_retry, resume and row 1's pointer, row 6's price entry (RF-79), --package-time-limit, benchmark pack (RF-82), --jobs and resume's refusal of it (36A); V7 simulate, compare --pilot and --noise-floor; V8 pilot (with --smoke and --jobs, 35A, 36A), noise-floor
├── report/session.py              # S1 origin_mark, origin_marks; S3 covers, extracted from covering_requests (RF-6)
├── report/finding_groups.py       # S3 goal_readings, extracted from _goal_line (RF-23)
├── prerun.py                      # S1 recorded_call(mark=)
├── agent/checklist.py             # S1 SYSTEM_PROMPT_FILE, moved beside CHECKLIST_FILE (RF-1)
├── agent/events.py                # S3 replay_events, moved from chat/sessions.py with on_unreadable (RF-29), reading a packed stream, and event_stream with PACKED_EVENTS_FILE_NAME (28A, RF-83); B6 UsageLedger.rounds()
├── agent/runner.py                # S1 _restate mark, origin_marks, SYSTEM_PROMPT_FILE re-exported; B6 TurnStopped, StoppableTools (forwarding tools_withdrawn, RF-18), end_stopped
├── agent/settings.py              # P2 PaneDefaults.explain_findings, study names, INERT_SETTINGS, check_study_arm's typed markers (RF-19); V7 BETWEEN_TURN_SETTINGS (RF-14)
├── agent/providers/{__init__,openai_provider,gemini_provider,fake}.py, retry.py (NEW)   # B6 use_retry, stop_reason and served_model on every stream (RF-32), OpenAI's policy codes (RF-76)
├── chat/server.py                 # P2 explanations from PaneDefaults; B6 moved stop classes
├── chat/sessions.py               # S3 re-exports replay_events (RF-29)
├── checks/fastener.py, checks/joint_alignment.py, checks/golden_fastener.py   # S1 19A; the unknown-role golden's adapter
├── checks/standards/report.py     # P2 D12 stamp, stamped_profile_digest (RF-5)
├── checks/standards/profile.py, checks/tolerances.py   # P2 display_digest, which tolerances.profile_sha256 calls (RF-5)
├── tools/registry.py              # S3 read_stored_result beside _store (RF-30)
├── tools/session.py               # S3 documents_named (public)
├── ir/loader.py                   # P2 append_interference_run's write through write_atomic (34A); A3 the case_files segment
├── report/attention_record.py, tokens.py   # P2 their atomic writes through write_atomic (34A; the record LF on Windows)
└── handoff.py                     # P2 slice-2 allowlist, model_view, a package export reading the run root's provenance (RF-42); A3 max_answer_turns; B6 the five robustness fields (jobs among them, 36A), OPTIONAL_ARTIFACTS, the run root's run-status.json

reviewer/tests/
├── benchmark_cases/               # G4 NEW the generator: spec, seeds, stamps, vocabulary, render, generate, designs/*
├── support/{drawings,mechanical(as_committed, G4, RF-55),features,standards,studies,packages,scramble,scoring_probes(NEW),local_paths(NEW),answer_keys(NEW, S1, RF-49)}.py
├── golden/test_golden_scorecards.py (NEW), test_golden_scorecards/ (NEW), scoring_rules_versions.json (NEW)
├── golden/test_golden/{joint-bottoming,joint-ok,joint-unsupported,thread-mismatch,tool-envelope}.yml and joint-unknown-role.yml (NEW), golden/fixtures/joint-unknown-role/ (NEW) (S1), standards-*.yml (P2)
├── fixtures/replay/* (S1: 19A's regeneration asserted byte-identical, then origin marks' adding "origin_marks": 1 to each session.json, RF-27; P2: regenerated for D12), fixtures/ingest/cover-blind-tap/ (G4, moved)
├── checks/standards_fixtures.py   # G4 re-exports `card` from tests/support/standards.py
├── unit/, integration/, perf/test_benchmark_report_perf.py, simulation/ (NEW, opt-in)
├── unit/test_attention_record.py, test_tokens.py, test_ir_loader_append.py, test_checks_first_interference.py (P2, 34A); unit/test_benchmark_jobs.py (NEW, B6, 36A)
├── live/test_benchmark_live_attempt.py (NEW, B6, 35A: one real attempt, on demand only)
└── conftest.py                    # V7 the simulation gate
reviewer/pyproject.toml            # V7 the `simulation` marker
reviewer/scripts/make_cover_blind_tap_pdfs.py   # G4 re-pointed to the moved ingest inputs

extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json   # P2 regenerated by D12's commit (RF-28); no C#

benchmarks/  answer_keys/rms-part.json (S1 by hand), cover-blind-tap.json (S1 interim, G4 generated),
             packages/*, answer_keys/*, case_files/*, sets/{committed,pilot,pane-smoke}.json (G4 generated; pane-smoke is P0's, 35A),
             README.md (S1 the key line, format 2; G4 the rest),
             pilots/<study folder>/ (slice 8's smoke run P0, 35A, its paid pilot and its measurement, RF-36),
             studies/<study folder>/ (slice 9's runs and noise-floor.json, RF-53)
.gitattributes (P2, eol=lf and *.gz binary, RF-84), .gitignore (P2, the packed study and pilot event streams, RF-84), docs/llm-efficiency-options.md (P2, one regeneration)
specs/{001,002,005,006,008,010}/contracts/* and specs/001/data-model.md   # amendment text, with the task that lands it (006: the profile stamp, P2)
docs/test-plan-<date>/{workstation-handover,workstation-test-plan,workstation-results}.md, reviewer/tests/support/seat_tasks.py   # I, after slice 6's gate: the seat's smoke review, 014's one [W] task (33A)
```

**Structure Decision**: both source trees are extended in place; the generator stays test tooling
under `reviewer/tests/` because it is built on the fictional builders there (D14.1). New modules each
hold one reading the eval lacked (matching, origins, questions, attempts, statistics) or one helper
that an import cycle or a third copy made necessary (`atomic`, `digest`, `scrub`; `atomic` is the
product's only atomic writer since 34A); nothing is a second
copy of an existing one, and the product's own readers (`replay_events`, the replay's stored-result
check) move beside their writers rather than being copied.

## Phase 0 and Phase 1

Phase 0 is research §1 to §8 plus §9's decisions. Phase 1 is [data-model.md](data-model.md),
[contracts/](contracts/README.md) and [quickstart.md](quickstart.md). Points the tasks must honour:

1. **One matcher, one relation, one resolver, one root, one judge.** The key loader's overlap test,
   the scorer, the oracle builder and the pilot's never-detected list use `benchmark/matching.py`;
   the driver and the scorer use `benchmark/questions.py`, whose relation wraps the product's
   `covers`; `review`, the replay and `benchmark run` resolve through `_review_settings`; every set
   path resolves against the running checkout's root through one `load_set` core; compare and the
   simulator use `verdict.judge`.
2. **One reader per run-folder file, one writer per record.** Event lines through `replay_events`
   (the scorer, the report, the recording reader, `attempt_facts`; RF-29), each run's stream found,
   plain or packed, through `event_stream` beside it (28A, RF-83); packed streams and
   `event-streams.json` written by `benchmark pack` alone (RF-82); stored tool results
   through `read_stored_result` (the replay, the questions reader, the report; RF-30); every atomic
   write through `write_atomic`, this feature's records and the product's three older ones (RF-31,
   34A); `run-status.json` by the package scheduler's thread alone (36A, RF-90); every digest through `benchmark/digest.py`,
   `sha256_of` over a file's raw bytes or `canonical_sha256` over parsed JSON (RF-48, RF-56).
3. **Runs never read keys**: the run stats a key's existence and never opens it; only the scorer, the
   validation, the set summary and the pilot's never-detected list read keys.
4. **Held out is recorded once**, per item, in the key; the set flag is derived and checked, by
   `score` against the key and by compare against the scorecard's `graded_items` (RF-39).
5. **Unknown is never 0**; `not_assessed` names every `null` column's reason.
6. **File digests (`sha256_of`) are raw bytes**; checkouts agree through `.gitattributes` `eol=lf`
   (INT-3), except the golden digest, which reads files as git stores them (INT-12). `runs_digest`,
   `sizing_digest` and the tool digest are `canonical_sha256` over parsed values and need no
   line-ending rule (RF-56, RF-64, RF-65).
7. **Written before any review**: provenance and the saved set, after every refusal
   (`benchmark-run.md` 3; `preflight_set`, INT-14).
8. **Nothing appends to a completed package**; attempts are promoted by one rename.
9. **The pane's behaviour does not move** where this feature adds an option: no `use_retry` call
   (each library's own retries), no `retries` field, no `prompts.json`, `goal_lines` built from the
   extracted `goal_readings` unchanged. The pane's records gain only evidence: `served_model` and
   `stop_reason` on its stream (feature 002's schema amended, RF-32) and the origin-marks record on
   its sessions (RF-27). Checked at the gates of slices 1, 2 and 6 by the add-in's page and host tests
   and a replay of the committed replay fixtures through the replay gate's steps 2 and 3, and once on
   the pilot workstation by a Task Pane smoke review of the small assembly, before any paid run (33A,
   RF-87).
10. **Scorecards change only with a version bump** (INT-11); compare refuses before validation.
11. **The committed ledger header regenerates once**, in the parity slice, with `provenance.md` 5's
    final order.
12. **No local path in a committable record**: the harness's failure messages are scrubbed where it
    writes them (RF-41, RF-73), and the scanner checks every committable file (`provenance.md` 6.6),
    a packed stream by its decompressed text (RF-84).
13. **Committed streams are packed** (28A): a run writes plain `events.jsonl`; once the run is
    final, `benchmark pack` replaces each with `events.jsonl.gz` and records each stream's digest
    before the folder is committed (`provenance.md` 6.7); git ignores a plain stream everywhere but
    the replay fixtures and admits a packed one only under `benchmarks/studies/` and
    `benchmarks/pilots/` (RF-84).
14. **Concurrency measures nothing** (36A, RF-90): `benchmark run --jobs N` (default 1) runs up to N
    packages at once, each with its own folder, stream and daemon worker; one scheduling thread, shared
    by run and resume, writes the run's record and prints its lines, so no two writes interleave; N is
    recorded in provenance and exempt from must-match, since it changes no review's inputs; each
    stream still counts its own rate-limit retries; resume runs at the recorded N.
15. **A paid smoke run before the pilot** (35A, RF-89): quickstart P0 runs
    `benchmarks/sets/pane-smoke.json` (a held-out core case and the anchor with a case file) once per
    arm and reads every row, and the live test runs green; any wiring is fixed, failing test first,
    before the pilot, which runs from the commit of the P0 that passed. P0's folders are committed with
    the pilot's, and `benchmark pilot --smoke` reads their review times for the cost gate's projected
    wall clock (36A, RF-91).

## Delivery order

12A as refined by 14A. Each slice is test-first and lands on `main` in its order; its gate must pass
before the next slice's first merge. The seat is needed once: the Task Pane smoke review after slice
6's gate, before any paid run (33A).

| # | Slice | Deliverable | Gate (all offline unless said) |
|---|---|---|---|
| 1 | **Scorer** (US1; FR-001 to FR-010, FR-031 (tags and stamp), FR-032 (score half), FR-061) | `scoring.md` 1 to 3.2, 3.3's first bullet (false alarms), 5, 6, 7's slice-1 fields (3.1's and 3.2's lists, `finding_origins`, `graded_items`, `not_assessed`, `key_sha256`, their `Aggregate` sums, the summary line), 8, 9.2's oracle builder and null review (with the key-only stand-in, RF-15), 10; `answer-key.md` format 2 for defects and conditions, the data-only model and the loader (RF-1), `current_stamp()` over the new `benchmark/digest.py` with 25A's tool-description digest over each tool's full description and schema (RF-48, RF-64), `SYSTEM_PROMPT_FILE` beside `CHECKLIST_FILE`, and `benchmarks/README.md`'s key line; `rms-part` rewritten; `cover-blind-tap`'s interim key (INT-15); the existing tests the scorer moves, through one key-writing helper, and the integration isolation test's key assertions deleted (RF-49); `SCORING_RULES_VERSION = 2`; then two commits, in this order (RF-27): **19A** with its five regenerated goldens and the new `joint-unknown-role` golden (RF-2), and **origin marks** with feature 001's session schema | `scoring.md` 11's tests of sections 2 (`test_benchmark_matching.py` 6 without its forbidden rows), 3.1, 3.2, 3.3's first bullet (`test_scorecard.py` 8), 5, 6 (test 9 without its absent session, test 16's), 7's slice-1 fields (`test_scorecard.py` 12 on conditions only) and 8, and its 19A tests; `answer-key.md` 9's `test_answer_key.py` tests 1 (defects and conditions), 2 to 5, 6 without its forbidden half, 7, 8 without its forbidden rows, 11 to 15 (15: `holds_held_out()` and `held_out_model_defect_ids()`, RF-67); `test_committed_answer_keys.py` 1, 2, 3 on the interim key (D-2 and C-1), and 4 and 5: SC-002 and SC-001 on both committed keys, `rms-part` through its stand-in, 5 on the slice-1 columns only; `cases.md` 9's scorer-slice `test_held_out_stamps.py` tests: the tool digest, one `Args:` entry's change included, and the digested set's completeness (RF-64); `test_scorecard_usage.py` and `test_carry_over_guards.py` on format-2 keys (RF-49); compare refuses an old scorecard with the re-score line; 19A's replay regeneration byte-identical, the replay tests passing; then origin marks' regeneration differing from it only by one `"origin_marks": 1` in each of the three `session.json` files, every `events.jsonl` and `package.json` byte-identical, `test_pane_fixture.py` passing unchanged (RF-27); the add-in's page and host tests (`dotnet build extractor/SwReview.sln -c Release --nologo -v q`, zero warnings, and `dotnet test extractor/SwReview.sln -c Release --no-build --nologo`, from the repository root on Windows) and a replay of the committed replay fixtures through the replay gate's steps 2 and 3 (013 `contracts/tokens.md` section 5), every figure of 008 `contracts/replay.md` section 9's latest row unchanged, the pane's records differing only by `"origin_marks": 1` (33A, RF-87) |
| 2 | **Parity** (US2; FR-011 to FR-015, FR-050 to FR-052, FR-056 run half, FR-032 compare half) | `provenance.md` 1's slice-2 fields (data-model 7), 2's model-view, profile and set-flag cross-checks (RF-39), 3, 4, 5, 6.1 to 6.5, 6.6's scanner over the record, the saved set and the ledger, a packed stream read by its decompressed text (RF-84), 7's allowlist for the slice-2 fields, `_session_summary` and a package export's read of the run root's provenance (RF-42); `benchmark-run.md` 2 (with RF-19's parameters), 3 (rows 1 to 3, 5 to 7; row 1 without the resume pointer), 5's `AttemptRequest` with the model view and the profile, forwarded by `run_benchmark` and `_review_fn` (RF-44), 5.1's parity rows; `write_atomic` (RF-31); `load_set(path, *, root)` with `SetError` and row 3 (RF-4) and `BenchmarkSet.file_form` beside `saved_form` (RF-54); `run_benchmark`'s `root` (RF-61); `.gitignore`'s packed-stream rules (28A, RF-84); `.gitattributes`, with `*.gz binary` after `benchmarks/** eol=lf` (RF-84), then the example profile checked out again (`test_line_endings` green), then D12 with `stamped_profile_digest` and `display_digest` (RF-5), its one commit regenerating the standards goldens, the replay fixtures and the add-in's pane fixture (RF-28); ledger 1.1 with the final columns | `provenance.md` 8's tests not marked for a later slice, among them the private study's own key and raw rows and `settings_differed` at the function level; SC-003's parity test on the `start_review` arguments and the sessions' settings; the must-match partition test and the lever study's off and on pair (RF-10); the set-flag and missing-entry compare tests (RF-39, RF-62); `test_committable_paths.py` but its scrub test and its committed-folder digest test (slice 6), its offline run without `--max-answer-turns` (RF-59), with `test_packed_streams_are_committable_only_in_the_study_and_pilot_trees` and the scanner's packed-stream row (RF-84); `cases.md` 9's parity-slice tests: `test_benchmark_sets.py`'s root (row 3's `SetError` among them), second-worktree, `load_saved_set`, `saved_form` and `file_form` tests (RF-4, RF-54), and `test_held_out_stamps.py`'s equality of `current_stamp()` with the `prompt_digest` and `checklist_digest` a run records; `test_line_endings`; `benchmark-run.md` 15's parity-slice tests: `test_review_settings.py`, `test_benchmark_run_options.py` but its marked tests, `test_cli.py`'s `test_the_run_start_adapter_is_the_first_attempts` but its resume half (RF-60, RF-81), `test_atomic.py` with 34A's three writer tests (`test_attention_record.py`, `test_tokens.py`, `test_ir_loader_append.py`, the three failure tests they move among them; RF-88), and the tests it moves (`test_model_view_settings.py:70`, the three fakes taking `attempt`, `test_benchmark_run_on_a_missing_set_exits_1` naming the set); `test_provenance_records_every_field_its_slice_adds[2]`; `test_the_handoff_allowlist_names_every_provenance_field` (RF-42); the committed header regenerated once and byte-identical; D12's replay gate (fixtures regenerated on the development machine under 013's freeze, every profile stamp's sha256 equal to the LF example profile's, replay tests pass), `test_pane_fixture.py` passing on the regenerated pane fixture, and the add-in's WebView2 acceptance tests that load it re-run on a Windows machine (RF-28); at the gate, on `main`, the add-in's page and host tests again and a replay of the committed replay fixtures through the replay gate's steps 2 and 3, every figure unchanged but those D12's stamps move (33A, RF-87) |
| 3 | **Key extensions and scripted answers** (US3, US4; FR-017 to FR-026, FR-053, FR-060) | `scoring.md` 3.3, 4 (through `goal_readings`, RF-23), 7's slice-3 fields; the one event-line reader, `replay_events` moved to `agent/events.py` with `on_unreadable` and read by the scorer in one pass (RF-29), reading a packed stream, with `event_stream` beside it finding each run's stream, plain or packed (28A, RF-83); `read_stored_result` beside `_store`, called by the replay and the questions reader (RF-30); `questions.md` (with `covers`, RF-6); `answer-key.md` rows 9 to 11 and the forbidden halves of rows 6 and 8; `scripted-answers.md` (re-delivery, RF-13); `max_answer_turns` in provenance and the handoff allowlist (RF-42); `benchmark-run.md` 3 row 4 in `preflight_set`, the package id `attempts` included; `AttemptRequest`'s case file and bound (RF-44); version 3 | US3-1 to US3-8 and US4-1 to US4-9 tests; `test_scorecard.py` 7 and 12's forbidden and coverage columns; `test_benchmark_matching.py` 6's forbidden rows; `test_committed_answer_keys.py` 5's two answer-log columns; `cases.md` 9's scripted-answers-slice tests: `test_benchmark_sets.py`'s `case_file_sha256` test and the case-file halves of rows 4 and 5, and `test_answer_key_isolation.py`'s case-file half; `benchmark-run.md` 15's scripted-answers-slice tests: `test_a_package_id_attempts_is_refused`, and `test_run_benchmark_hands_the_review_function_the_model_view_and_the_profile` grown by the case file and the bound; `test_committable_paths.py`'s offline run with `--max-answer-turns 0` (RF-59); `test_answer_key.py` 1 (every list), 6's and 8's forbidden halves, 9, 10; `test_event_lines.py` 1 to 3, 4's `score_run` row (RF-59), and 5 and 6 (RF-83); `test_stored_result.py` (every reason, and the replay's classification unchanged); `test_scripted_answers_flow.py`; `test_questions_on_real_tools.py`; `test_provenance_records_every_field_its_slice_adds[3]` |
| 4 | **Generator and validation** (US5; FR-027 to FR-033, FR-048, FR-049, FR-054) | `generator.md` (sets through `file_form`, RF-54; `as_committed` moved once, RF-55); `cases.md` (keyed sets, RF-4; leg (a)'s call set, RF-38); the committed set; `benchmark score`'s `--answer-keys` omitted for a keyed set and refused if given (RF-85), required for a keyless one; golden scorecards, probes (with `GOLDEN_IDENTITY`, RF-43) and the version record (first row: version 3); `test_answer_key_isolation.py`'s `pkg-1` given its `package.json` (RF-44) | SC-001, SC-002, SC-004, SC-006, SC-011, SC-013, SC-014; `cases.md` 9's generator-slice tests, among them `test_held_out_stamps.py`'s stamp on every committed held-out item and `test_benchmark_sets.py`'s field, keyless and keyed-set tests and refusals (rows 1, 2 and 4 to 7), and `test_committed_benchmark_set.py`, its FR-029 tags read from the case specs (RF-80); `generator.md` 11's tests: `test_benchmark_case_generator.py`, `test_benchmark_generator_imports.py`, `test_support_sheets.py`, `test_support_mechanical.py`, `test_support_features.py` and `test_benchmark_cases_are_fictional.py`; `test_committed_answer_keys.py` 3 on the regenerated key; validation under 3 minutes; **owner question 8 answered before its first key is written** |
| 5 | **Report** (US6; FR-034, FR-057) | `report.md`, reading event lines through `replay_events`, each stream found through `event_stream`, and results through `read_stored_result` (RF-29, RF-30, RF-83); `recording._events` replaced by `replay_events` (RF-29); `prompts.json` from `benchmark-run.md` 12, written by `_review_fn` through `write_atomic` | R-1, R-2, R-5 to R-17, with `test_replay_recorded_runs.py` on the development machine (RF-59); `test_event_lines.py` 4's report and recording rows and its structural half; `test_prompts_record.py` but for its abandoned-attempt test (slice 6); R-18 (`-m perf`, 940 transcripts over packed streams, RF-46, 28A) run and recorded |
| 6 | **Robustness** (US7; FR-035, FR-036 to FR-043, FR-047's tokenizer clause) | `benchmark-run.md` 4 to 15: the attempt on a daemon worker (RF-50), row 1's resume pointer, messages without local paths (RF-41), `served_model` and `stop_reason` on every stream (RF-32), OpenAI's policy stops (RF-76), the inferred Gemini overflow (RF-77), section 3 row 6's price entry (RF-79), `attempt_facts` through `replay_events` and `UsageLedger.rounds()` (RF-29), resume re-applying the pane studies' tree rules (RF-51), `AttemptRequest.stop` (RF-44); `provenance.md` 1's slice-6 fields, 2's served-model check, 6.6's reach over `run-status.json`, attempt folders and `event-streams.json`, 6.7's `benchmark pack` in `benchmark/streams.py` with `event-streams.json` and `digest.sha256_of_bytes` (28A, RF-82), 7's robustness fields, `OPTIONAL_ARTIFACTS` and the run root's `run-status.json` (RF-42); scorecard `run_status`, `cost`, `served_models`, `price_table` (RF-45), unscored packages and failed attempts with their folders (INT-9, RF-16, RF-17), the next version with a record row; the replay's stop through `end_stopped`, unconditional (RF-3, RF-33); the report's R-3 and R-4; `benchmark run --jobs N`, the one package scheduler shared by run and resume and the only writer of `run-status.json`, `jobs` in provenance, record-only (36A, RF-90); the live attempt test (35A, RF-89) | `benchmark-run.md` 15's robustness-slice tests: every test of `test_benchmark_attempts.py` (US7-1 to US7-4 and US7-7; FR-039's served-model tests; FR-040's and 26A's provider stops, OpenAI's policy stops among them, RF-76, and the inferred Gemini overflow, RF-77; `test_a_hung_attempt_is_abandoned_and_the_process_still_exits`, RF-50; `test_an_internal_error_naming_a_local_path_records_no_local_path`, RF-41; `test_an_offline_run_without_the_tokenizer_vocabulary_refuses_nothing_and_counts_read_unknown`, FR-047's tokenizer clause), `test_provider_retry.py` (FR-038), `test_benchmark_resume.py`, `test_prices.py` (SC-008's offline half), `test_events_schema.py`, the provider tests' additions, `test_the_pane_stream_carries_the_served_model` (RF-32), `test_benchmark_and_pane_attempts_wrap_tools_in_the_one_stoppable_tools` (the stopped close-out, `cancel_presentation` included) and lever 7's withdrawal through the wrapper on `test_coverage_stop.py`'s OpenAI replay (RF-18, RF-63), `test_an_abandoned_attempt_still_records_its_opening`, SC-007's integration test, and the robustness halves of `test_benchmark_run_options.py` (the package time limit, row 1's pointer, row 6's price entry, RF-79, the stop reaching the review function) and of `test_the_run_start_adapter_is_the_first_attempts` (resume); the report's R-3 and R-4 (FR-035, US6-1); `test_event_lines.py` 4's `attempt_facts` row; the committable scrub test; `test_benchmark_pack.py` and `test_committed_run_folders_hold_packed_streams_matching_their_digests` (`provenance.md` 8; RF-82, RF-84); the report's R-19 (RF-83); `test_scorecard.py` 16; `test_provenance_records_every_field_its_slice_adds[6]`, `jobs` among its fields; `test_benchmark_jobs.py` and `test_jobs_never_refuses` (36A); the live attempt test collected and skipped with no key (35A); the price table filled from the providers' pages; the add-in's page and host tests and a replay of the committed replay fixtures through the replay gate's steps 2 and 3, every figure unchanged, the pane's live stream gaining only `served_model` and `stop_reason` (33A); then, on the pilot workstation, the Task Pane smoke review of the small assembly, written into the workstation handover, which every paid run waits for (33A, RF-87) |
| 7 | **Simulator and verdict** (US8; FR-044 to FR-046, FR-058, FR-059, FR-016) | `verdict.md` 1 to 9, 10.3 to 10.6 and 11: the t distribution by its closed-form series (RF-34); the `PilotMeasurement` model and its digest, compare's `--pilot` and `recorded_pilots()` over `benchmarks/pilots/`, the pilot raw rows from the measurement, and the noise-floor record's reader, each tested against hand-written files (RF-36, RF-37, RF-53) | V-1 to V-27, C-1 to C-17, S-1 to S-9; S-10 (`-m simulation`) run and its printout kept with the slice |
| 8 | **Pilot and cost gate** (FR-055, US5-13, US5-14) | `verdict.md` 10.1, 10.2 and 9.7's computation: `benchmark pilot` (its estimators and the sizing search; an existing `--out` refused, RF-40; `--smoke` and `--jobs`, and the study's projected wall clock, 36A, RF-91) and `benchmark noise-floor` (RF-53); then, on a machine with a key, once the seat's smoke review has passed, the smoke run P0 over `benchmarks/sets/pane-smoke.json`, one repetition per arm, every row read and the live test green, any wiring fixed before the pilot (35A, RF-89), then the paid pilot from P0's commit (3 repetitions of the off arm over the committed set, 27A, into `benchmarks/pilots/<study folder>/`, RF-36), `benchmark pilot`, the owner's approval, choosing N (36A), the smoke and pilot folders packed (`benchmark pack`, 28A) | P-1 to P-11, P-13 and P-14 offline; on P0 and the pilot: SC-008 (no "cost unknown"), and at P0 the live test green on `1 passed, 0 skipped`; SC-005 and the projected wall clock printed; the smoke and pilot folders, packed (28A), any growth units the approved size adds (generated and validated) and the approved measurement committed in one commit, the approval dated before any study run (quickstart P3; RF-40) |
| 9 | **Paid pane study**, then the private slice | both arms alternated at the approved size and `--jobs`, every repetition from the approval's commit; score; `benchmark noise-floor` after the last repetition (RF-53); `compare --pilot`; the verdict; `benchmark pack` over the study's folders before their commit (28A); the private study outside the repository | the verdict renders (or is refused, naming why); FR-051's test over the committed study and pilot folders, their packed streams included, each matching its recorded digest (RF-84), the study's committed after the last repetition, packed, with its noise-floor record |

**Sequencing that is not negotiable.** The scorer before any study is scored (12A; research §4).
19A, origin marks and D12 each land as one commit with every fixture they move, serialized on `main`
in that order (RF-27, RF-28). 19A moves check goldens only: its commit regenerates the replay
fixtures to assert they stay byte-identical (no recording calls a fastener rule or the joint map,
RF-2), so it takes no freeze. Origin marks follow it in slice 1: their commit regenerates the replay
fixtures, whose only change is one `"origin_marks": 1` in each `session.json`, and takes no freeze,
since nothing the model reads moves. D12 moves the replay fixtures (they carry the old profile stamp)
and the add-in's pane fixture (it carries the stamp five times) and takes 013's freeze: from the
start of the change until its one commit, fixtures regenerated, lands, no other change that moves
what the model reads merges. The ledger columns and `LEDGER_SCHEMA = "1.1"` land in one commit of
slice 2. A slice that changes scoring bumps `SCORING_RULES_VERSION` in the same commit (INT-11).
`.gitattributes` (slice 2) before any held-out stamp is written (slice 4). No paid run before slice
6's gate (FR-036 needs it) and the seat's Task Pane smoke review after it (33A); the smoke run P0
before the pilot, which runs from the commit of the P0 that passed (35A); and none of the pane study
before the approval (slice 8). Slice 4
starts only once owner question 8 is answered (research §9.7; answered B, 30A). The paid
study's runs share one commit and a clean tree (`provenance.md` 3.2 and 4): the smoke run's and the pilot's
folders, any growth units the approved size adds and the approved measurement are committed first (RF-40), every
repetition of both arms runs from that commit, and the study's folders, with the noise-floor record
simulated after the last repetition (RF-53), are committed only after it (quickstart P3 and P4; RK-15).
Each folder is packed (`benchmark pack`) after its run's last resume and before its commit (28A, RK-17).

## Lanes and file ownership

A task that edits a file is done by the lane that owns it in that slice; one owner per file per
slice. Lanes: **S** scorer, **P** parity and provenance, **A** scripted answers, **G** generator and
validation, **R** report, **B** robustness, **V** verdict, simulator and pilot.

| File (shared) | Owner by slice, and what each edits |
|---|---|
| `cli.py` | S1 the score summary; P2 `_review_settings` and its new parameters (RF-19), `benchmark run`'s options and refusals rows 1-3 and 5-7 (row 1 without the resume pointer; row 3's adapter the first attempt's, RF-60), provenance before any review, `_review_fn` taking `attempt` and forwarding the model view and the profile (RF-44); A3 `_review_fn` through `drive_review`, `--max-answer-turns`, row 4's case files; G4 `benchmark set-summary`, `benchmark score`'s `--answer-keys` omitted for a keyed set (RF-4) and refused if given (RF-85); R5 `benchmark report`, `prompts.json` in `_review_fn`; B6 the attempt body and its `use_retry` call (RF-20), the key redactor composed with `without_local_paths` (RF-41), `benchmark resume` and row 1's resume pointer, row 6's price entry (RF-79), `--package-time-limit`, `benchmark pack` (RF-82), `--jobs` and resume's refusal of it (36A); V7 `benchmark simulate`, `compare --pilot` and `--noise-floor` (RF-37, RF-53); V8 `benchmark pilot` with `--smoke` and `--jobs` (35A, 36A), `benchmark noise-floor`. Each lane edits only its command's region and its tests in `reviewer/tests/unit/test_cli.py` |
| `benchmark/compare.py` | S1 `_load_run` through `read_scorecard`, the key-digest refusal; P2 the must-match loop, studies, baselines, the model-view, profile and set-flag cross-checks and the missing-entry refusal (RF-39, RF-62), `settings_differed`, committable guard, run-dir rendering, `RunRow` and the final columns, 1.1; R5 `_count` and `_distinct` public; B6 the served-model re-check from `served_models` (RF-16), `jobs` among the must-match exemptions (36A); V7 pane routing, verdict refusals, `pane_studies`, the pane section, `--pilot`, `recorded_pilots` over `benchmarks/pilots/`, the pilot raw rows from the measurement's `pilot_runs` (RF-36, RF-37), the noise-floor record (`--noise-floor`, `recorded_noise_floors`, RF-53) |
| `benchmark/scorecard.py` | S1; S3 (the extension columns, the one-pass event read through `replay_events`, RF-29, version 3); B6 (INT-9, RF-16, RF-17, `price_table`, RF-45) |
| `benchmark/runner.py` | S1 `sha256_of` re-exported from `benchmark/digest.py` (RF-48); P2 `RunProvenance`, `AttemptRequest` with the model view and the profile and `run_benchmark`'s forwarding (RF-44), `run_benchmark`'s `root` (RF-61); A3 `preflight_set` (row 4, the package id `attempts` included) and the `PreflightedSet` argument, `max_answer_turns`, `AttemptRequest`'s case file and bound; G4 existence checks in `preflight_set`; B6 the attempt driver on a daemon worker (RF-50), run status, resume (RF-51), `attempt_facts` (RF-29), scrubbed messages (RF-41), `AttemptRequest.stop`, the one package scheduler of `--jobs`, shared by run and resume (36A, RF-90) |
| `benchmark/sets.py` | P2 `REPO_ROOT` moved here, `SetError` with its "benchmark set {file name}:" prefix, the one core `load_set(path, *, root)` with row 3 (a relative path outside `<root>/benchmarks/sets/`, another checkout's included), `file_form` and `saved_form` through one entry serializer (RF-54), `load_saved_set` (RF-4); A3 case-file fields and guard, row 5's case-file half, `case_file_sha256` through `digest.sha256_of` (RF-48); G4 the entry fields, keyed and keyless sets, and rows 1, 2 and 4 to 7 |
| `benchmark/answers.py` | A3; B6 `stop_requested` only |
| `benchmark/replay.py` | S3 `_stored_result` through `read_stored_result`, its classification unchanged (RF-30); B6 `TurnStopped` and `end_stopped`, unconditional, in place of `_Stop` (RF-3, RF-33) |
| `benchmark/simulate.py` | V7 scenarios, the level and size searches, the noise-floor record's model and reader; V8 the noise floor's computation over a study's runs (RF-53) |
| `benchmark/pilot.py` | V7 `PilotMeasurement`, `sizing_digest` and the reader compare uses (RF-37); V8 the estimators, the never-detected list, the sizing search, the smoke runs and the projected wall clock (35A, 36A, RF-91) and `benchmark pilot`'s refusals (RF-40) |
| `agent/events.py` | S3 `replay_events` moved here with `on_unreadable` (RF-29), reading a packed stream, and `event_stream` with `PACKED_EVENTS_FILE_NAME` (28A, RF-83); B6 `UsageLedger.rounds()` |
| `benchmark/digest.py` | S1 NEW `sha256_of` and `canonical_sha256` (RF-48, RF-56); B6 `sha256_of_bytes`, which `sha256_of` then calls (RF-82) |
| `agent/runner.py` | S1 `_restate` mark, `origin_marks`, `SYSTEM_PROMPT_FILE` re-exported from `agent/checklist.py` (RF-1); B6 the moved stop classes, `StoppableTools.tools_withdrawn` (RF-18), `end_stopped` |
| `agent/settings.py` | P2 `PaneDefaults.explain_findings`, the study names, `INERT_SETTINGS`, `check_study_arm`'s typed markers; V7 `BETWEEN_TURN_SETTINGS` (RF-14) |
| `report/session.py` | S1 `origin_mark`, `origin_marks`; S3 `covers`, extracted from `covering_requests` (RF-6) |
| `chat/server.py` | P2 `defaults.explain_findings`; B6 the moved imports and `_end_stopped` |
| `handoff.py` | P2 the allowlist's slice-2 fields, `model_view`, a package export reading the run root's `run-provenance.json` (RF-42); A3 `max_answer_turns` in the allowlist; B6 the allowlist's five robustness fields (`jobs` among them, 36A), `OPTIONAL_ARTIFACTS`, the run root's `run-status.json` |
| `ir/loader.py`, `report/attention_record.py`, `tokens.py` | P2 their atomic writes moved onto `write_atomic` (34A, RF-88; Phase 2's tasks); A3 `ir/loader.py`'s `case_files` segment |
| `reviewer/tests/unit/test_attention_record.py`, `test_tokens.py`, `test_ir_loader_append.py`, `test_checks_first_interference.py` | P2 only: 34A's failing-first tests and the moved failure tests' patch target (`swreview.atomic.os`) |
| `benchmark/report_page.py` | R5; R6 (status and cost columns, a lane-R task inside slice 6) |
| `reviewer/tests/support/studies.py` | S1 the new scorecard fields and version; P2 `RunSpec` record fields, the pane pair and baselines, `write_run`'s saved-set entry per package (RF-62); S3 the forbidden, coverage and question columns, version 3, and `RunSpec.max_answer_turns` on A3's behalf; B6 `run_status`, `cost`, `served_models`, the next version, `RunSpec.jobs` (36A); V7 pane-study scorecards |
| `reviewer/tests/support/scoring_probes.py` | S1 `oracle_review`, the null review and `stand_in_package`, written as package folders (RF-15, RF-58); S3 the oracle's coverage rows and question half, its calls through the real tool; G4 the probes, `MATCHING_RULES` and `GOLDEN_IDENTITY` (RF-43); B6 the behavioural-stop probe (`run_status` alone) |
| `reviewer/tests/support/answer_keys.py` | S1 NEW `write_key` for defects and conditions, through `AnswerKey` (RF-49); S3 the four extension lists |
| `reviewer/tests/unit/test_benchmark_compare.py` | S1 the key-digest test; P2 the parity tests, the lever study's off and on pair, the set-flag test (RF-39), the schema pin (`:741`) at 1.1, the byte-identity test; A3 the case-file digest and `max_answer_turns` refusals (`scripted-answers.md` 7); B6 the served-model re-check, `test_jobs_never_refuses` (36A); V7 `recorded_pilots` and `recorded_noise_floors` in the byte-identity test (`:993-1005`) |
| `reviewer/tests/unit/test_answer_key_isolation.py` | P2 its three `load_set` calls (`:48`, `:71`, `:105`) and its `run_benchmark` call at `:130` pass `root=tmp_path`, the smuggle stub (`:166`) takes the keyword (RF-61), its fake (`:118-127`) takes `attempt` (RF-44); A3 the `run_benchmark` calls take a `PreflightedSet`, the smuggle test building one directly, the case-file pins (RF-26); G4 the private-set rows (`cases.md` 9), `pkg-1` (`:109-110`) given its `package.json` (RF-44) |
| `reviewer/tests/integration/test_answer_key_isolation.py` | S1 its key assertions deleted (RF-49); P2 its fake (`:56-64`) takes `attempt` (RF-44); A3 its `run_benchmark` call takes a `PreflightedSet` |
| `reviewer/tests/unit/test_efficiency_settings.py` | P2 `check_study_arm`'s additions, its fake (`:365-374`) takes `attempt` (RF-44); A3 its `run_benchmark` call takes a `PreflightedSet` |
| `reviewer/tests/unit/test_scorecard_usage.py`, `test_carry_over_guards.py` | S1 only: format-2 keys through `write_key`, support packages saved at the entries' paths, `held_out=False` over tuned-on items (RF-49) |
| `docs/llm-efficiency-options.md` | P2 only: the one header regeneration, and one sentence in the hand-written "Measurements outside the ledger" that its quality figures were scored under scoring rules version 1 (INT-10); the paid study's rows are slice 9's regeneration under the same header |
| `specs/005-llm-efficiency/contracts/ab-harness.md` | S1 sections 4 and 9 (fields read, version refusal); P2 sections 2, 3, 4 (columns, the 1.1 record naming `pane_studies`), 10.1, 10.2, 10.5; B6 section 10.1 (failures no longer stop the set); V7 sections 5 and 7 (the pointer) |
| Golden scorecards and `scoring_rules_versions.json` | G4 creates; B6 regenerates for `run_status` and appends a row. Never in parallel |
| `reviewer/tests/fixtures/replay/*` | S1 twice, in order: 19A regenerates them only to assert they stay byte-identical (RF-2), then origin marks regenerate them, adding one `"origin_marks": 1` to each `session.json` (RF-27); P2 (D12) regenerates them, from the recordings on the development machine |
| `extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json` | P2 only: D12's commit regenerates it with `generate_pane_fixture.py --write`, after the replay fixtures (RF-28) |
| `reviewer/tests/golden/test_golden/*.yml` | S1 the five joint goldens (`joint-bottoming`, `joint-ok`, `joint-unsupported`, `thread-mismatch`, `tool-envelope`) and the new `joint-unknown-role` (RF-2); P2 the standards goldens; G4 re-runs them unchanged after `card` moves |
| `benchmarks/**` | S1 `rms-part.json`, the interim `cover-blind-tap.json` and `README.md`'s key line (format 2, `answer-key.md`'s amendment); G4 everything the generator writes, the ingest inputs moved out, the rest of `README.md`; slice 8's smoke run and paid pilot write `pilots/<study folder>/` and any growth units the approval adds (lane G's specs, regenerated); slice 9's study writes `studies/<study folder>/` |
| `.gitignore`, `.gitattributes` | P2 only. `.gitignore`: `**/events.jsonl.gz` after the `**/events.jsonl` rule (`.gitignore:77`), then `!benchmarks/studies/**/events.jsonl.gz` and `!benchmarks/pilots/**/events.jsonl.gz`, so a plain stream stays ignored everywhere but the replay fixtures and the committed study and pilot folders keep their streams packed (28A, RF-84; RF-78's plain-stream exceptions superseded). `.gitattributes`: `provenance.md` 6.5's `eol=lf` lines, then `*.gz binary` after `benchmarks/** eol=lf` (RF-84). `test_committable_paths.py`'s `test_packed_streams_are_committable_only_in_the_study_and_pilot_trees` pins both |
| The workstation handover of the sitting after slice 6's gate (`docs/test-plan-<date>/`: the handover, the test plan and the results sheet) and `reviewer/tests/support/seat_tasks.py` | I only: the seat's smoke review named as feature 014's one `[W]` task, and `PACKAGES` gaining `014-design-review-eval` (33A) |
| `reviewer/tests/unit/test_committable_paths.py` | P2 NEW: the scanner's tests, a packed stream read by its decompressed text among them, the offline run and the packed-stream rules test (RF-84); A3 the offline run's `--max-answer-turns 0` (RF-59); B6 the scrub test (RF-41) and `test_committed_run_folders_hold_packed_streams_matching_their_digests` (RF-84) |

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | 19A, origin marks and D12 regenerate the replay fixtures, which need the private recordings | All three regenerate on the development machine, where the mapping and three recording folders are present (checked 2026-09-29, existence only), in the order 19A, origin marks, D12: 19A's must leave them byte-identical (RF-2), origin marks' may add only one `"origin_marks": 1` to each `session.json` (RF-27), D12's moves them under the freeze with the add-in's pane fixture (RF-28); findings' text unchanged |
| RK-2 | A generated key no real finding can match (the audit's central failure) | Reference equality plus FR-054's two legs, decoys, and the validation's own failing-case tests (`cases.md` 7) |
| RK-3 | Clean bases raise findings (RMS on mate-less assemblies, standards on sheets, joint-map candidates) | Each failure named by leg (a); fixed in the design, never keyed away; per-design iteration budgeted in slice 4 |
| RK-4 | Drawing seed kinds turn out code-detectable, eroding the margin of 2 over 34 | Leg (a) names them; re-tag or replace in the spec; the floor refusal in compare stays |
| RK-5 | Windows working copies keep CRLF after `eol=lf` lands, so digests differ between machines | `test_line_endings` names the files; the pane studies refuse a digested input holding a carriage return before any paid run, and again on resume (INT-3, RF-51); the golden digest reads bytes as git stores them (INT-12) |
| RK-6 | Every old scorecard, study fixture and session byte moves (new required fields, origin marks) | Version refusal before validation with the re-score line; `studies.py` updated in the same slice; feature 001's schemas amended in the same commit; the existing scorer tests rewritten in slice 1 (RF-49) |
| RK-7 | Gemini's served-model form and overflow message are unverified without a key | Unknown aliases fail safe as `wrong_model` at round one; a matched overflow is a behavioural `provider_stop` (26A); one the pattern misses, a Gemini request error (a `GeminiRequestError`, recognised by type) after an answered round, is inferred as `provider_stop` `input_token_limit_inferred`, the service's words kept in `run-status.json` for the owner to read, and a refusal before any answered round stays `provider_error` (RF-77); the first pane study runs on OpenAI (D14.5) |
| RK-8 | An abandoned worker holds its socket until exit | Classed `abandoned`, never promoted; a daemon thread, so the process still exits (RF-50); the wall clock bounds it |
| RK-9 | Paid cost: 94 × R reviews per study plus the pilot; co-movement may push R to the cap and grow cases | The cost gate prints size, cost and the study's projected wall clock at the chosen N (36A) before any study run; growth units are committed with the approval, never a second pilot (RF-40); twin rule B (24A) keeps the set at 47 |
| RK-10 | Role-swapped fits score on their status, so a swap can clear a planted defect | Shown in the cleared guard's list; the pilot's clearances reveal how often |
| RK-11 | The report's budget breaks at real transcript sizes | R-18 measured before the pilot at 940 transcripts, the committed set's worst case (RF-46); linking results is the owner's fallback (`report.md` 8) |
| RK-12 | The pane studies refuse dirty trees and unknown commits | Stated in the quickstart; operators commit or stash, the pilot workstation included |
| RK-13 | A company value leaks into a generated case | Names held to the case vocabulary at generation on every machine; the owner's denylist test where the list exists; skipped, never passed, elsewhere |
| RK-14 | Validation runtime exceeds three minutes | Module-scoped caches; split by marker, never skipping a case |
| RK-15 | A commit lands between the paid study's repetitions, or a run starts before the approval is committed, so compare refuses the paid study on `commit` or `tree_dirty` | Quickstart P3 and P4's order: commit the pilot's folders, any growth units and the approved `pilot-measurement.json`, run every repetition of both arms from that commit (untracked run folders leave `tree_dirty` false), simulate the noise floor, commit the study's folders only after the last repetition; the run records `commit` and `tree_dirty`, so compare refuses a slip, naming the field, and never averages it in |
| RK-16 | A failure message names a local folder, so a paid run folder cannot be committed | The harness scrubs `run-status.json` and the runner's error body (RF-41); an adapter's error body or a tool's failure text is the scanner's to find before commit (RF-73) |
| RK-17 | A pilot or study folder is committed unpacked, so its streams, which git ignores in plain form, never reach the repository and the study cannot be re-scored or reported elsewhere | Quickstart P3 and P4 pack before each commit, and `git status` then lists every packed stream; `test_committed_run_folders_hold_packed_streams_matching_their_digests` fails on any checkout for a committed run folder lacking a stream or its digest (RF-84); the folder is packed and committed again, no paid run lost, since the plain streams stay on the machine that ran it until packed |
| RK-18 | Running N packages at once (36A) meets the provider's rate limits, tokens and requests per minute: retries lengthen reviews, an exhausted retry fails a package, and a review's wall clock nears W | N defaults to 1 and is the owner's choice at the cost gate, from the projection and the retry counts P0 and the pilot met; every rate-limit retry is counted on its stream (FR-038), and an exhausted one is an infrastructure failure, re-run by resume and never scored; N is recorded and changes no measurement, so no study is refused for it; P0 runs at the planned N first; quickstart P3 keeps N times one review's mean tokens per minute, which the cost gate prints, under the account's limit with room |
| RK-19 | The seat's smoke review (33A) waits for a sitting on the licensed seat, and every paid run waits with it; or it fails on something no offline gate can see | Slice 7 and slice 8's offline half go on meanwhile; the review is written into the workstation handover before the sitting; a fail stops the paid runs, its fix is a task of its own with its failing test, and the review runs again on the fix's build |
| RK-20 | P0 finds wiring the offline suite missed, after money is spent | P0 costs about four reviews against the pilot's 141; a fault is fixed with its own failing test and P0 runs again from the fix's commit into fresh folders; the pilot runs from the commit of the P0 that passed, and P0's failed folders are never committed (35A) |

## Complexity Tracking

| Beyond the simplest design | Why needed | Simpler alternative rejected because |
|---|---|---|
| Paired package-level verdict with a simulator (US8) | Model-produced defects are stochastic; D17's two 5% bounds hold only for the whole verdict, measured | `adoption.decide`: control stability pre-empts every verdict and the median rule calls identical arms a loss 35-46% of the time (research D1) |
| Eight origin values from a step mark and a session record (FR-007) | 17A decides on model origin; 20A splits called checks by tool; regrade findings happen in scripted runs | Three buckets misfile carried, set-up, regrade and code-only findings, biasing the false-alarm rule (research D9, D15) |
| Scoring-rules version with golden scorecards and probes (FR-008, FR-049) | A mixed study would compare scorecards scored under different rules without anyone seeing it | Always re-scoring: nothing refuses a stale scorecard; oracle and null goldens alone move on no counting change (research §8.15) |
| Scripted-answer driver (US4) | Three anchors (R-1, R-3, R-6) act only between turns, and so does one pane default, dropped reasoning (lever 14); the driver plays their answer turns through the pane's own method | Single-turn cases cannot observe R-1, R-3, R-6 or dropped reasoning at all. With the driver the anchors show them, with paired intervals; no held-out case takes an answer turn (CS-9), so the verdict names dropped reasoning as untested by it (RF-14); owner question 8 was answered B (30A): held-out cases take none |
| Report page (US6) | The grading sign-off means reading transcripts, per case and repetition, beside the numbers that graded them | The two simpler designs `report.md` 1 weighed: Markdown through `report/markdown.py`, which is a page only inside a viewer, while a browser opens HTML and its relative links from `file://`; `results.jsonl` with a committed JavaScript renderer, a second writer of every number, which a `file://` page cannot fetch and which needs Node to test |
| Case generator and separate validation (US5) | 34+ held-out defects, twins and anchors, byte-reproducible, with reachability proved | Hand-built packages: the audit's unreachable key; no byte-for-byte guarantee; hand edits drift |
| Product change 19A (FR-061) | An unresolved joint must name its joint so the scorer matches exactly (Principle IV). SR-5 goes beyond research §8.12's starting design: the fastener and hole ids lead `inputs` on resolved paths too, and `_unsupported` names the hole, so the scorer reads one field on every path (RF-2) | Part-level matching credits sibling joints (US1-17); forbidding siblings bars the anchors' own shapes (research §8.12); references on unresolved paths only would leave two fields for one reader |
| Product change D12 (FR-051) | Standards findings stamp a local folder into committable folders | Keeping study folders out of the repository loses the committed ledger's rows |
| Attempts on a worker, wall clock, promotion, resume (US7) | A hung stream must end; a failed attempt must never be appended to or scored | A subprocess per attempt loses in-process scripted tests and the finalized state a behavioural stop keeps; SDK timeouts are not independent of the stream (Gemini has none); an executor worker would be joined at exit, so the worker is a daemon thread (RF-50) |
| Request-level retries in the adapters (FR-038) | A rate limit at round 30 must not discard 29 paid rounds, and FR-038 asks the retries counted exactly | FR-038's own alternative, the libraries' jittered retries (OpenAI's client; google-genai 2.23's `HttpRetryOptions`) counted per request through each client's HTTP hook: those retries cannot consult the attempt's stop after the wall clock (RF-20 (c)); they do not retry OpenAI's `response.failed` or a stream that ended with no response, which arrive inside an HTTP exchange that succeeded; and a transport hook's count cannot be tied to the round's `usage` body, which is where "counted exactly" reads it (RF-35). A package re-run with library retries off discards paid rounds |
| Dated price table priced per round (FR-042) | Cost per package at the cost gate, with FR-042's three prices per model and no tiers (RF-8) | Pricing the session's totals (`SessionUsage`, `report/session.py:404-421`) with the same three prices: a total cannot price a round by the model the served id aliases, which may change per round (`benchmark-run.md` 7), cannot apply Gemini's zero-omission rule, which reads each round's reported total against its addends, and a failed attempt has no session total, only its events |
| Packages at once, `benchmark run --jobs N` (36A; RF-90) | Owner decision 36A: a pane study at the cap is up to 940 paid reviews, which `run_benchmark` reviews one at a time today (`benchmark/runner.py:236`) | Sequential runs only, the plan as it stood: the owner took 36A over it. A driver thread per package running `run_attempt`: Ctrl-C reaches only the main thread, so the interrupt record and the daemon workers' exit guarantee (RF-22, RF-50) would need a second mechanism; one scheduling thread polling every attempt keeps both and leaves the run's record one writer |
| Packed event streams and `benchmark pack` (28A; RF-82 to RF-84) | Owner decision 28A: about 12 MB of streams per study at the cap in every checkout's working tree rather than about 102 MB plain (RF-78's arithmetic), each committed study still re-scorable and reportable from the repository | Committing plain streams, RF-78 as first decided: the owner took 28A over it (option C). Packing inside `benchmark score`: a reader would rewrite the folder it reads. Packing in the run driver: an abandoned worker may still write into its folder until the process exits (RF-50) |
| Noise floor simulated once and stored (FR-046, D14.8) | The committed ledger must render the same bytes on every supported Python, and its byte-identity test runs in the default suite | Simulating inside compare on every render: `reviewer/uv.lock` resolves numpy 2.4.6 on Python 3.11 and 2.5.3 on 3.12+, whose distribution streams are not promised stable across releases, and each render would run 4,000-simulation searches over up to 100 grid points (RF-53) |
