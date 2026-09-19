---

description: "Task list for the attention policy and the procedural gate"
---

# Tasks: Attention Policy and Procedural Gate

**Input**: Design documents from `/specs/007-attention-policy-gate/` (`spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`, `design-brief.md`)

**Prerequisites**: features 001 to 006 complete; the two pane fixes on main (`b3cb948` event stream, `7e700e4` drawing attach). Feature 006 T100 (the real standards profile) gates only the measurement of the gate's standards half, not its code. The 2026-09-18 run folders are not in the repository; T024 needs them copied off the pilot workstation.

**Tests**: REQUIRED, and **strictly test-first**: every implementation task below is preceded by the test task that must be written and must fail first. The one golden of `report/markdown.render_report` stays byte-identical with no ranking (SC-004); lever 5's digest stays byte-identical with the gate off (FR-030); `Finding`, `ReviewSession`, `chat-events.schema.json`, the MCP function list and the terminal profile do not move. The tests that go red **by design** when a change lands are named in the task that lands it (research R3), and each is edited deliberately in that task, never loosened.

**Organization**: Setup (the session builder, the two 2026-09-18-shaped fixtures, the policy file skeleton), Foundational (the one folder re-render), US1 timing, US2 the policy and the report, US3 every surface, US4 the gate, Polish, then Measurement and workstation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on another unfinished task)
- **[Story]**: `US1` to `US4`; Setup, Foundational and Polish tasks carry no story tag
- **[W]**: needs the pilot workstation, a SOLIDWORKS seat, or the copied run folders
- **[K]**: needs an API key - only the measurement tasks in Phase 8 carry it; no test in Phases 1 to 7 does

## Path Conventions

- Python: `reviewer/src/swreview/`, tests in `reviewer/tests/`
- C# add-in pages and tests: `extractor/SwReview.AddIn/`, `extractor/SwReview.AddIn.Tests/`
- Contracts: `specs/007-attention-policy-gate/contracts/`; other features' contracts are edited in the task that changes their shape

---

## Phase 1: Setup

**Purpose**: the builder every fixture in this feature is written by, the two committed sessions shaped like the 2026-09-18 workstation runs, and the policy file's skeleton so the consequence table exists as data before anything reads it.

- [x] T001 [P] Write `reviewer/tests/unit/test_support_attention.py`: the builder writes a `ReviewSession` whose findings carry a given check id, status, severity, component ids, drawing locations, disposition, `exception_id` and carry-over fields, with provenance and `tool_result_ids` that satisfy the review-session contract (`contract_validator("review-session.schema.json")`); coverage buckets are settable by count per bucket and by check id; **re-running the builder reproduces a written fixture byte for byte**, so a drifted fixture is a failure and not a rewrite (research R2.4: the rule ids used must be outside every family's `high_severity` set, and the test asserts it against `RMS_FAMILY.high_severity` and `STANDARDS_FAMILY.high_severity`)
- [x] T002 Implement `reviewer/tests/support/attention.py` on top of `tests/support/packages.py` and `tests/unit/test_report.py`'s `build_session` idiom. Acceptance: T001 green
- [x] T003 Create the fixtures with the T002 builder: `reviewer/tests/fixtures/attention/session-20260918-review.json` (eight findings - `interference.static` on pin A, `interference.static` on pin B, `rms.assembly.mates_to_reference_geometry` bound to the root assembly's component id with the part and the pin in its inputs (as the real finding is), `rms.sketches.fully_defined`, `rms.grouping.all_features_in_a_group`, `rms.params.global_variables_present`, all medium and demonstrated; `rms.folders.present` and `rms.params.dimensions_driven_by_equations`, low and suspected; coverage 5 checked, 11 skipped, 39 unresolved, 0 failed, 7 out of scope, the unresolved items being the seven checklist close-out rows with their reasons, three `coverage.evidence_request` rows, one `coverage.closeout` row and RMS rule rows, as the real session holds them), `session-20260918-check.json` (the three RMS findings; coverage 5/11/5/0/6), and the two folder fixtures `review-folder/` (session + a small `package.json`) and `check-folder/` (session + package + `check.json` with `family: "rms"` and `scope: "part"`) for the CLI tests. Acceptance: each validates against the contract; the regeneration assertion of T001 covers all four
- [x] T004 [P] Create `reviewer/src/swreview/report/attention_policy_v1.yaml` with `version: attention_policy_v1`, `needs_judgement: [interference., fit., fastener., hole.]`, a `classes` map that names **every** emittable check id (the RMS rules from `checks/rms/registry.py`, the sixteen standards checks, `interference.static`, the five fastener constants, the fit, stack, hole-alignment and drawing check ids) with the classes the owner agreed on 2026-09-19 (research R2.15: `rms.assembly.mates_to_reference_geometry`, `rms.sketches.fully_defined` and `rms.assembly.first_component_fixed` rebuild_breaker; `rms.grouping.*` and `rms.params.*` discipline; `rms.folders.present` hygiene; `interference.static`, `fit.*`, `fastener.*`, `hole.*` interface; `standards.drawing.*` manufacturing; every other id a first opinion for T022's confirmation run), `blind_spots` with one sentence per pre-run family (`fastener_joint`, `hole_alignment`, `fit`, `axial_stack`, `interference`, `standards`), and `triage_pass_preconditions` verbatim from spec FR-035. Acceptance: loads as YAML; no `%` in any sentence (research R2.14)

**Checkpoint**: two committed sessions reproduce the 2026-09-18 runs, the builder reproduces them byte for byte, and the consequence table exists as data.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the one folder-aware re-render that US1's `timing`, US3's offline sites and the record writer all need, landed before any of them so there is one and not three (research R2.7).

- [x] T005 [P] Write `reviewer/tests/unit/test_rerender.py`: `rerender_run_folder(run_dir)` over the three folder kinds - a review folder with `package.json` (component names in the report come from the package, and Manifest Discrepancies is a table, not the "not supplied" placeholder), a review folder without one (the placeholder, as `swreview report` renders today), an RMS check folder, and a standards check folder whose `check.json` carries a `verdict` (**the verdict header is re-prepended byte-identical to what `run_standards_check` wrote**); it returns the report path; a folder with no `session.json` raises `OSError` naming the path and writes nothing; a benchmark run root (no session at the top, a `<package_id>/session.json` below) raises `ValueError` naming `swreview benchmark time`. At this phase it writes `report.md` only; T030 extends it
- [x] T006 Implement `reviewer/src/swreview/report/rerender.py` (`rerender_run_folder`), extracting the verdict header of `checks/standards/run.py:392 _write_report` into a function that renders from `verdict_json` so the header can be rebuilt from `check.json`; `_write_report` calls the same function. Acceptance: T005 green; `test_standards_run.py`'s report assertions unchanged

**Checkpoint**: one function re-renders any run folder without losing its package or its verdict header.

---

## Phase 3: User Story 1 - Engineer Minutes Are Recordable on Every Real Run (Priority: P1) 🎯 MVP

**Goal**: the four human inputs recordable against any run folder from the command line and against a pane review through the backend, net derived and never accepted, a negative refused naming the field, the report's Timing section printing the figure, and the ledger reporting the median as a column.

**Independent Test**: `swreview timing <fixture review folder> --baseline 45 --supervision 6 --verification 9 --false-alarms 2` prints `net saved: 28.0` and the re-rendered report's Timing section reads `Net saved minutes: 28.0`; `--baseline -1` exits 1 naming `baseline_minutes` with the session unchanged; the route does the same for a pane review and survives the next turn; `test_timing.py`'s six tests pass unchanged; the ledger row carries the median column with `n=` and `decide()` is unchanged by it. No licence, no key.

- [x] T007 [P] [US1] Extend `reviewer/tests/unit/test_timing.py`: `record_timing_at(session_path, ...)` over a **flat** `<dir>/session.json` proves the same six facts the existing tests prove for the nested shape (net derived, unattended runtime excluded, `None` baseline gives `None`, an omitted input keeps its value, the write reaches disk, `baseline=None` cannot un-set); the six existing `record_timing` tests are **unedited**; a negative supervision input raises `ValidationError` naming the field and the file is unchanged (FR-002, FR-003, FR-005)
- [x] T008 [US1] Extract `record_timing_at` in `reviewer/src/swreview/benchmark/timing.py`; `record_timing` becomes the two-line wrapper; rewrite the module docstring ("against a benchmark run" is no longer true) and add the new caller to `Timing.replace`'s docstring list in `reviewer/src/swreview/report/session.py`. Acceptance: T007 green
- [x] T009 [P] [US1] Extend `reviewer/tests/unit/test_session.py`: `Timing(baseline_minutes=-5.0, ...)` raises `ValidationError` naming `baseline_minutes`; a session with `baseline_minutes: 0` validates against the contract; the existing `net_saved_minutes: 999.0 -> 50.0` test is unchanged (FR-003, research R2.9)
- [x] T010 [US1] Add `Field(ge=0)` to `Timing.baseline_minutes` in `reviewer/src/swreview/report/session.py`. Acceptance: T009 green; `test_session_json_validates_against_the_contract` green
- [x] T011 [P] [US1] Write `reviewer/tests/unit/test_cli_timing.py` (importing `invoke`/`payload` from `test_cli`): over a copy of `fixtures/attention/review-folder`, `swreview timing <dir> --baseline 45 --supervision 6 --verification 9 --false-alarms 2 --json` writes the four values to `session.json`, the payload carries `run_dir`, `session_file`, `report_file` and the whole `timing` with `net_saved_minutes == 28.0`, and `report.md` is re-rendered with `Net saved minutes: 28.0` **and the package's component names**; over a copy of `check-folder` with a standards `check.json`, the verdict header survives; `--baseline -1` exits 1 with `baseline_minutes` in stderr and both files byte-identical; a folder with no session exits 1 naming the path; a benchmark run root exits 1 naming `benchmark time`; and `test_cli.py`'s `--help` tuple gains `timing` (FR-001, FR-003, FR-004)
- [x] T012 [US1] Implement `swreview timing` in `reviewer/src/swreview/cli.py` beside `disposition` (a run-folder argument, the four options, `JsonFlag`, `with _errors_as_exit_1():`, `record_timing_at(run_dir / SESSION_FILE_NAME, ...)` then `rerender_run_folder(run_dir)`, `_emit`); add `timing` to `test_cli.py`'s help tuple; add the row to `specs/001-agentic-design-review/contracts/cli.md` cross-referencing `contracts/timing.md`. Acceptance: T011 green
- [x] T013 [P] [US1] Write `reviewer/tests/unit/test_chat_timing_route.py` on the `chat_with_a_finding` fixture pattern of `test_chat_server.py:1162-1255`: `POST /sessions/{chat_id}/timing` with the four inputs returns `200 {timing}` with the net derived; the write reaches `run_dir/session.json` and `report.md` is re-rendered with the run's package; the values **survive the next turn** (a follow-up message and its finalize); a body carrying `net_saved_minutes`, an unknown key, a string, or a negative is `400 InvalidTiming` naming the key; a running turn is `409 TurnRunning`; an unknown chat `404 UnknownChat`; the route is added to `test_chat_server.py`'s `ROUTES` tuple so the door test covers it (FR-001, FR-002, FR-003)
- [x] T014 [US1] Implement the route in `reviewer/src/swreview/chat/server.py` (`InvalidTiming` beside the other `ChatError` subclasses; `async def timing` copying `disposition`'s shape; the `Route`) and `record_timing_live(run, **inputs)` in `reviewer/src/swreview/chat/sessions.py` beside `record_disposition` (mutates `run.session.timing` through `replace`, saves, re-renders with `run.context.ir`); add the row to `specs/002-task-pane-assistant/contracts/chat-api.md`. Acceptance: T013 green
- [x] T015 [P] [US1] Extend `reviewer/tests/support/studies.py` (`PackageSpec` and `scorecard()` gain optional timing fields feeding `net_saved_minutes`, `median_net_saved_minutes` and `packages_with_timing`), `reviewer/tests/unit/test_adoption_rule.py` (`decide()` returns the same `Verdict` with and without timing on the scorecards - FR-006's "never gates"), and `reviewer/tests/unit/test_benchmark_compare.py` (the decision row carries `median_net_saved_minutes` as an `OffOn` with `n=` the runs that carried timing, `unknown` for null, rendered under the new `LEVER_COLUMNS` title; `test_every_column_comes_from_its_one_source` covers it; the committed-document tests are updated to the regenerated block) (FR-006)
- [x] T016 [US1] Add `median_net_saved_minutes` to `reviewer/src/swreview/benchmark/adoption.py` `METRICS`, the `OffOn` field on `LeverDecision`, the `LEVER_COLUMNS` title and the `_lever_line` cell in `reviewer/src/swreview/benchmark/compare.py`; regenerate the ledger block in `docs/llm-efficiency-options.md` with `benchmark compare --into`; record the column in `specs/005-llm-efficiency/contracts/ab-harness.md` sections 5 and 10.8. Acceptance: T015 green; `test_the_committed_results_table_regenerates_byte_identically` and `test_check_exits_zero_on_the_committed_document` green

**Checkpoint**: every real run folder can carry the four inputs and print a net figure; a pane review can be timed from the backend; the ledger reports the median and gates nothing on it.

---

## Phase 4: User Story 2 - The Engineer Reads the Right Findings First (Priority: P2)

**Goal**: the policy as one pure module and one data file; the keyless reader; the owner's read-through; the "Start here" section with its golden; the record beside the session.

**Independent Test**: `swreview attention` over the review fixture folder prints the two interference rows first, then mates, sketch, grouping, with `rms.folders.present` last of eight; over the check fixture, the sketch first; ranking the shuffled review session is byte-identical; the one golden is byte-identical with no ranking and the ranked golden matches; the catalogue test passes; the policy module imports no provider, settings or network module; `attention.json` reproduces from `session.json`. No licence, no key.

### The policy

- [x] T017 [P] [US2] Write `reviewer/tests/unit/test_attention.py`: each of the nine keys fires exactly once in a table-driven set of pairs differing in one field; the 4 statuses x 4 severities x {no disposition, accepted, rejected, deferred} x {`exception_id` unset, set} cross product lands where `contracts/attention.md` section 1 says - `checked_within_scope` and accepted/rejected last, deferred and `exception_id`-only competing (FR-008); the two fixtures rank to the orders `quickstart.md` Scenario 2 states, with each row's `reason` naming the key that placed it; ranking the review session with its findings reversed is byte-identical (FR-014); a drawing finding has reach 0 and is not dropped; a needs-judgement finding that is `checked_within_scope` sorts last; a carried-over finding sorts below an otherwise identical fresh one; a check id absent from the table sorts as `unclassified` between `manufacturing` and `discipline` and its reason names the id; a session with zero findings yields `rows == []` and `empty_reason == "no findings were recorded"` with the coverage block still filled; an all-informational session yields the other `empty_reason` and a not-amplified count; **no rendered string contains `%`** (research R2.14); ranking a 500-finding session takes under 100 ms (`@pytest.mark.perf`); and, in a subprocess, importing `swreview.report.attention` loads no module under `swreview.agent.providers`, `swreview.agent.settings`, `httpx`, `openai` or `google` (FR-015) (FR-007 to FR-010, FR-014, FR-016)
- [x] T018 [P] [US2] Write `reviewer/tests/unit/test_attention_fold.py`: twelve `rms.grouping.all_features_in_a_group` findings on twelve parts with equal status and severity fold into one row with twelve `member_finding_ids`, the lowest id surviving and `component_ids` the sorted union; one differing severity makes two rows; two findings sharing a component never fold; two `interference.static` findings with disjoint subjects never fold; a single finding is a row of one; and **`session.findings` and every `Finding.group` are equal before and after** `rank()` (deep equality on the model dumps) (FR-012)
- [x] T019 [US2] Implement `reviewer/src/swreview/report/attention.py` per `data-model.md` sections 1 and 2: `AttentionKey`, `AttentionRow`, `NotAmplified`, `CoverageBlock`, `Ranking`, `load_policy()` (once, cached), `fold()`, `rank(session, policy=None)`, and the section-line renderers `start_here_lines(ranking)` and `coverage_line(ranking)` that both the report and the brief call; the coverage block lists the close-out rows (unresolved items whose `check` is one of the checklist item ids **other than `coverage.closeout`**, which is the run's own close-out summary rather than an unreached item, with their reasons verbatim, at most five), the count of `coverage.evidence_request` rows, and the counts of every other unresolved and skipped item (research R2.5). Acceptance: T017 and T018 green
- [x] T020 [P] [US2] Write `reviewer/tests/unit/test_cli_attention.py` (with `test_cli_remodel_plan.py`'s `no_provider` fixture and `digest()` idiom): `swreview attention <review-folder>` prints the policy version, the rows in order with reasons and key values, the not-amplified line and the coverage block; `--json` carries `run_dir`, `session_file` and `attention` equal to `rank()`'s JSON; the folder's hash map is identical before and after; a folder with no session exits 1 naming the path; the check-folder fixture ranks the sketch first; `test_cli.py`'s help tuple gains `attention` (FR-017)
- [x] T021 [US2] Implement `swreview attention` in `reviewer/src/swreview/cli.py` in the shape of `rms types` (reads, writes nothing); add `attention` to the help tuple; add the row to `specs/001-agentic-design-review/contracts/cli.md`. Acceptance: T020 green
- [x] T022 [W] [US2] **The read-through.** The folders are already on the development machine at `%LOCALAPPDATA%\SwReview\handover\runs` (fourteen: the three 2026-09-18 reviews and two checks of 810-11249, the 810-11504 pair, the three 810-11450 reviews, and the empty or aborted rest), and the decisions were taken on 2026-09-19 over a preview of the same rule (research R2.15). What remains here is the confirmation: run `swreview attention` over each folder with the owner and check the tool reproduces the agreed orders; any disagreement is an edit to `attention_policy_v1.yaml`'s `classes` or `needs_judgement` and a change to the fixture's expected order in T017. Acceptance: the tool's top five on `20260918-215755-810-11249` is the two interference rows, mates to reference geometry, the under-defined sketch and grouping; on the two check folders the sketch leads; on the 810-11450 reviews the two rebuild-breaker rows lead, the unfixed first component before mates to reference geometry because they tie on every key but the check id (RK-1). Confirmed 2026-09-19 over the ten folders that hold a `session.json`, every folder byte-identical afterwards (research R2.15, second table)
- [x] T023 [P] [US2] Write `reviewer/tests/unit/test_attention_catalogue.py` (lands **after** T022): every emittable check id - `checks/rms/registry.py` `RULES`, `checks/standards/registry.py`'s sixteen, `interference.static`, the five `checks/fastener.py` `CHECK_*` constants, the `CHECK` constants of `fit.py`, `stack.py` and `hole_alignment.py`, and the drawing check ids `record_drawing_finding` accepts - has a class in the policy file, and the file names no id the product cannot emit (FR-011)
- [x] T024 [US2] Complete `attention_policy_v1.yaml`'s `classes` per T022 and T023. Acceptance: T023 green; T017's fixture orders still hold. Nothing to complete: T022's confirmation changed no class and T023 finds the sixty emittable ids classed with nothing extra

### The report

- [x] T025 [P] [US2] Write `reviewer/tests/unit/test_report_start_here.py`: `render_report(session, package, ranking=None)` is byte-identical to `render_report(session, package)` and `test_report_tokens.py`'s golden is unchanged; with a ranking the section sits between `## Summary` and `## Findings` (the `text.index` idiom), lists exactly `top_n` rows in `rank()`'s order with their reasons, the not-amplified line, the coverage line and the footer naming the policy version; the empty cases print their sentences; no finding is absent from the severity sections below; no `%`; a session rendered with no package still renders the section; and a ranked report matches a **new golden** `reviewer/tests/unit/test_report_start_here/test_the_ranked_report_matches_the_golden.md` through `file_regression` (FR-013, FR-018, SC-004)
- [x] T026 [US2] Implement in `reviewer/src/swreview/report/markdown.py`: `render_report(session, package=None, *, ranking=None)`, `_render_start_here(ranking)` calling `attention.start_here_lines` and `coverage_line`, guarded like `## Tokens`; update the module docstring's section order. Acceptance: T025 green; the existing golden byte-identical (research R2.3, R2.6)

### The record

- [x] T027 [P] [US2] Write `reviewer/tests/unit/test_attention_record.py`: `write_attention_record(directory, ranking, session_id)` writes `attention.json` with `indent=2` and a trailing newline; `read_attention_record` round-trips; `rank(load_session(...))` reproduces the record exactly; a record whose `session_id` is not the session's is reported stale; `is_check_folder` is still true for an RMS check folder holding the record; and the four strict folder-content assertions are edited to expect the fourth file - `test_rms_run.py:278`, `test_standards_run.py:274`, `test_cli.py:1905`, `test_cli.py:1995` - each keeping its exact-list form (FR-020, FR-021)
- [x] T028 [US2] Implement `reviewer/src/swreview/report/attention_record.py`; write the record in `ReviewRun.finalize` (`reviewer/src/swreview/agent/runner.py:719`, from the same ranking the report will render, on the success and failure paths), in `checks/rules/run.py:228 write_report` and `checks/standards/run.py:392 _write_report` (each now takes or computes the ranking and passes it to `render_report`); extend `rerender_run_folder` (T006) to rank and write the record. Acceptance: T027 green; T005 extended for the record
- [x] T029 [P] [US2] Extend `reviewer/tests/unit/test_chat_server.py`'s rotation block: a review claiming an RMS check folder that holds `attention.json` rotates it to `attention.1.json` beside `session.1.json`; a folder holding only `attention.json` and no session is **not** refused as "already holds a review" (`SESSION_FILES` untouched) (FR-021)
- [x] T030 [US2] Move the record explicitly in `ChatServer._rotate_previous` (`reviewer/src/swreview/chat/server.py:1697`), leaving `SESSION_FILES` and `_claim_run_dir` untouched. Acceptance: T029 green

**Checkpoint**: the policy ranks the real runs the way the owner agreed, `report.md` opens its findings with "Start here" on the review CLI, the RMS check and the standards check, and every one of those writes a reproducible record.

---

## Phase 5: User Story 3 - The Ranking Reaches Every Surface the Engineer Reads (Priority: P3)

**Goal**: the remaining render sites and the enumeration that pins them; the `attention` key on both check bodies and the review route; the rows on the two keyless tabs and the pinned panel on the Review tab.

**Independent Test**: a fixture session rendered through each of the eight paths carries the section, and after a disposition, a waiver, a turn and a stop it is still there; `POST /checks/rms` and `/checks/standards` carry `attention` byte-equal to the `GET` re-read with the provider factories raising; `GET /sessions/{chat_id}/attention` answers the live ranking and writes nothing; the offscreen pages render the rows in the supplied order and the Review panel appears on `session.ended`; no page script sorts or compares severities.

### The remaining render sites

- [ ] T031 [P] [US3] Extend `reviewer/tests/unit/test_report_start_here.py` with the enumeration: every production call of `render_report` imported `from swreview.report.markdown` (matched on the import, so `remodel/report.py` is excluded) either passes `ranking=` or is one of the offline sites that call `rerender_run_folder`; the eight are listed by path and the test fails on a ninth; extend `reviewer/tests/unit/test_report.py`'s `apply_disposition` block: after a disposition the report still carries "Start here" and a standards folder keeps its header; extend `test_cli.py`'s `exceptions accept` tests likewise (FR-019)
- [ ] T032 [US3] Wire the remaining sites: `reviewer/src/swreview/cli.py:563` (the review command ranks and passes), `:607` (`report <session.json>` ranks and passes), `:1303` (`_save_run` re-renders through `rerender_run_folder`); `reviewer/src/swreview/chat/server.py:1853 _render_report` computes the ranking inside the same `try` and writes the record; `reviewer/src/swreview/chat/sessions.py:324 record_disposition` and `record_timing_live` pass the ranking and write the record; `reviewer/src/swreview/report/dispositions.py:92 apply_disposition` re-renders through `rerender_run_folder`. Acceptance: T031 green (RK-2, RK-15)

### The check bodies and the review route

- [ ] T033 [P] [US3] Extend `reviewer/tests/unit/test_chat_checks_routes.py` and `test_chat_standards_routes.py`: the POST body carries `attention` equal to `rank()` over the run's session minus `session_id`; the `GET /checks/{check_id}` re-read carries a byte-equal `attention` and the folder's three files are unchanged (the existing re-read tests extended, so `GET` computes and never writes); the Accept re-render carries it; the standards module's strict `set(result) == {...}` gains `attention` and a mirror-image strict assertion is added to the rms module; both `TestNoLanguageModel` classes still pass with the key present (FR-022, FR-025)
- [ ] T034 [US3] Add `attention` to `check_result` (`reviewer/src/swreview/chat/server.py:655`, after `exceptions_carried_forward`) and `standards_result` (`:785`, beside `rebuilt`); amend `specs/003-resilient-modeling/contracts/model-check.md` (the key in the block, a bullet, `attention.json` in the folder listing, and the two drift fixes research R3 names: the `reason` field of `exceptions_carried_forward` and the stale "scope is part" sentence) and `specs/006-standards-check/contracts/standards-check.md` (the key, a bullet, the listing, the `reason` field, and the note that the two blocks are identical so no difference row is added). Acceptance: T033 green
- [ ] T035 [P] [US3] Write `reviewer/tests/unit/test_chat_attention_route.py`: `GET /sessions/{chat_id}/attention` on a settled review answers `200` with `rank()`'s JSON over the live session; on a review that produced no findings, `rows == []` with `empty_reason`; `404 UnknownChat`; the run folder's hash map is unchanged by the call; the route joins `test_chat_server.py`'s `ROUTES` tuple; and `extractor/SwReview.AddIn.Tests/ReviewPageContractTests.cs`'s vocabulary scan admits the new path (FR-023)
- [ ] T036 [US3] Implement the route in `reviewer/src/swreview/chat/server.py` (an `async def attention` beside `get_session`, the `Route` placed before any `{param}` pattern that would shadow it) and the row in `specs/002-task-pane-assistant/contracts/chat-api.md`. Acceptance: T035 green (research R2.8)

### The two check tabs

- [x] T037 [P] [US3] Extend `extractor/SwReview.AddIn.Tests/SharedCheckPageTests.cs` (`renderAttention` in `SharedFunctions`; the new css selectors in the shared-stylesheet theory; the shared script still names neither "grade" nor "verdict"), `ModelCheckPageTests.cs` and `StandardsPageTests.cs` (a sample body carrying `attention` renders its rows into `#attention` **in the supplied order** - the `attrs(...)` idiom - above `#filters`, each row showing the finding id, the check and the reason; an empty ranking renders its `empty_reason`; `EveryElementIdTheScriptLooksUpExistsInTheHtml` passes because both `index.html` files carry `id="attention"`; `NoLetterGradeAndNoSinglePercentageIsRenderedAnywhere` still passes with the block present), and `ModelCheckPageInjectionTests.cs` / `StandardsPageInjectionTests.cs` (a reason line of `<img src=x onerror=alert(1)>` renders as text: `injected == 0`, `handlers == 0`) (FR-023)
- [x] T038 [US3] Implement `renderAttention(result)` in `extractor/SwReview.AddIn/web/shared/check-page.js`, called from `renderResult` between `page.renderHeader` and `renderFilters`, through `dom.*` only; the rules in `web/shared/check-page.css`; `<section id="attention">` above `#filters` in `extractor/SwReview.AddIn/Model/ModelCheckPage/index.html` and above `#checks` in `extractor/SwReview.AddIn/Standards/StandardsPage/index.html`. Acceptance: T037 green (research R2.14)

### The Review panel

- [x] T039 [P] [US3] Write `extractor/SwReview.AddIn.Tests/ReviewPageAttentionPanelTests.cs` on `ReviewPageEventStreamTests`' `Drive()` pattern with the `AcceptStub`-style `window.fetch` stub from `ModelCheckPageTests`: after the contract sample's `session.ended`, the page called `GET /sessions/chat-1/attention` with the bearer header and rendered the stubbed ranking's rows in order into `#attention-panel` above `#transcript`; an empty ranking renders its `empty_reason` sentence; a response arriving after a second Review press (a different `chat_id`) is discarded; a second Review press clears and hides the panel; `render.attentionPanel` is exported on `window.SwReviewRender` and a hostile reason line renders as text (FR-023, FR-024)
- [x] T040 [US3] Implement `attentionPanel(ranking)` in `extractor/SwReview.AddIn/Review/ReviewPage/render.js`, the fetch in `endSession` and the clear in `resetTranscript` in `Review/ReviewPage/app.js`, the `bind()` entry, and `<section id="attention-panel" class="panel" hidden>` above `<main id="transcript">` in `Review/ReviewPage/index.html`. Acceptance: T039 green
- [x] T041 [P] [US3] Write `extractor/SwReview.AddIn.Tests/PageRuleScanTests.cs`: over `PageScripts.Collect(...)` for all three pages (so `dom.js` is included for the Review page too), comments stripped, no script contains `.sort(`, `localeCompare`, a literal list of the four severity words, or a comparison on a `severity` or `status` value, with an explicit allowlist of the existing bucket display orders (`BUCKETS` in `check-page.js`, the `COUNTS` rows in `standards.js`, `coverageSummary`'s `order` in `render.js`) and the `warn`-to-`warned` mapping. Acceptance: green on the T038 and T040 code with no edit to it (FR-023)

**Checkpoint**: the same five rows appear in `report.md`, on both keyless tabs, and on the Review tab when the session ends, and no page computed any of them.

---

## Phase 6: User Story 4 - The Procedural Gate (Priority: P4)

**Goal**: lever 11 with its refusals and pinned edits; the pre-run widened and made to fail into a line; the brief from the same ranking the report renders; the standards checklist item; the number guard; the counter the ledger has only ever named.

**Independent Test**: with `procedural_gate` on and a fixture package with a scripted provider, the first user message holds the digest, the ranked rows, the three lists and the instruction, and its ids equal the report's "Start here"; with the gate off, `prerun_checks` produces today's digest byte for byte; without a profile, with an unreadable profile, and with a package missing the cutlist row, a not-evaluated line and its skipped item appear; with a profile and a standards package, standards findings close `standards.release` and the two families' summary items stay disjoint; a drawing finding carrying `0.05 mm` is refused without a cited source and accepted with one; eleven levers, none in the pane schema; the counter computes. No licence, no key.

### The lever

- [x] T042 [P] [US4] Extend `reviewer/tests/unit/test_efficiency_settings.py` (`EXPECTED_LEVERS` gains `procedural_gate` last; `[False] * 11`; the two refusals - `procedural_gate` with `prerun_checks`, and with `coverage_stop` - name levers 5 and 11 and 7 and 11; the unknown-name message says "the eleven levers"), `reviewer/tests/unit/test_no_lever_in_pane_settings.py` (`== 11`; the parametrized pane-schema scan covers the new name), and `reviewer/tests/unit/test_usage_contracts.py` (a session carrying `EfficiencySettings()` with eleven fields validates; `procedural_gate` is in `properties` and **not** in `required`, and a session written without it still validates) (FR-026)
- [x] T043 [US4] Add `procedural_gate: bool = False` ("Lever 11: …") last in `EfficiencySettings` in `reviewer/src/swreview/agent/settings.py`, the two refusals in `efficiency_from_levers`, "the eleven levers" in `_levers_sentence`; add the name to `properties` only in `specs/001-agentic-design-review/contracts/review-session.schema.json`; add the row to `specs/005-llm-efficiency/contracts/levers.md`'s flag table. Acceptance: T042 green (research R2.10)

### The pre-run and the brief

- [ ] T044 [P] [US4] Extend `reviewer/tests/unit/test_prerun_digest.py`: with `prerun_checks=True, procedural_gate=False` the opening message is **byte-identical** to today's (the existing assertions unedited); with `procedural_gate=True` alone the pre-run ran and the opening message begins with the unchanged digest; the anti-drift assertion: for the review fixture session run through the gate, the finding ids in the brief's `Start here:` block equal the ids in the report's `## Start here` in order (FR-030, FR-031)
- [ ] T045 [P] [US4] Write `reviewer/tests/unit/test_gate_brief.py`: `gate_brief(prerun, ranking)` renders the six parts of `contracts/gate.md` section 3 in order; the `Start here:` lines are `attention.start_here_lines` verbatim; six rows are capped at five with the sixth counted in the not-amplified line; `Needs your judgement:` lists exactly the rows with judgement key 0, or `none`; `Not reached in this run:` lists the close-out rows with their reasons, the open evidence requests and the rule counts; `Not visible to any rule:` has one sentence per `NotEvaluated` family from the policy file's `blind_spots` and each is backed by a `coverage.prerun.<family>` skipped item; the instruction sentence is verbatim; the message ends with `OPENING_MESSAGE` (FR-029)
- [ ] T046 [US4] Implement in `reviewer/src/swreview/prerun.py`: `prerun_checks` runs when either lever is on; `gate_brief(prerun, ranking)`; guard the `result.payload["error"]` read at `:388`; in `reviewer/src/swreview/agent/runner.py` compose the brief at the opening-message site (`:988-989`) when the gate is on, ranking the session the pre-run just wrote with `attention.rank`. Acceptance: T044 and T045 green (research R2.12)
- [ ] T047 [P] [US4] Write `reviewer/tests/unit/test_gate_same_session.py` on `test_prerun_same_session.py`'s pattern with `GATE_ON` in `reviewer/tests/support/prerun.py`: every gate call is a real `InvestigationStep` with contiguous indices, real `tool.started`/`tool.finished`/`finding`/`coverage` events, and findings whose `tool_result_ids` name a step that exists; `session.started` is still first on the stream; `planned_calls(context, tools)` equals `MODEL_DRIVEN_CALLS` plus `check_standards` when a standards run is attached and equals `MODEL_DRIVEN_CALLS` when none is; `tools.withheld` still filters (lever 4); no event type outside the fourteen is emitted (`test_events_schema.py`'s full-run assertion unchanged) (FR-027, FR-032)
- [ ] T048 [P] [US4] Write `reviewer/tests/unit/test_gate_standards_in_review.py`: with `standards_profile` naming a fictional profile and a package that carries the `cutlist` phase row (extend `tests/support/prerun.py` with `standards_prerun_package()`), the gate runs `check_standards` as a real step, standards findings are recorded, `standards.release` is closed (by prefix through a finding, and by id through the summary item), and `modeling.resilience`'s summary item is unaffected; the three not-evaluated cases - no `standards_profile`; a path that does not exist or a file that fails its schema; a package whose `cutlist` row is `skipped` - each produce the `contracts/gate.md` section 2 line **and** a `coverage.prerun.standards` skipped item, and the review still starts; `swreview review --standards-profile <yaml>` passes the path through (`invoke` with the fake provider) (FR-027, FR-028)
- [ ] T049 [US4] Implement `start_review(standards_profile: Path | None = None)` in `reviewer/src/swreview/agent/runner.py` (load the profile, compute `graded_documents`, `attach_standards_run` **between** `build_context` at `:892` and the dispatch at `:946`; every failure recorded as a `NotEvaluated` for the pre-run rather than raised), `planned_calls` reading `standards_run(context)` and the standards reason in `not_evaluated_families` in `reviewer/src/swreview/prerun.py`, and `--standards-profile` on `swreview review` in `reviewer/src/swreview/cli.py` with its row in `specs/001-agentic-design-review/contracts/cli.md`. Acceptance: T047 and T048 green (research R2.11)

### The checklist item

- [ ] T050 [P] [US4] Extend the checklist tests (`reviewer/tests/unit/test_checklist.py` or the module that loads `checklist_v1.yaml`): a tenth item `standards.release` with `check_prefix: standards.` loads; `bucket_of` closes it on a `standards.*` finding and on a coverage item whose check is `standards.release`; regenerate the prompt-prefix fixtures `reviewer/tests/unit/test_prefix_stability.py` reads and update the checklist byte counts quoted in `specs/005-llm-efficiency/contracts/levers.md` (FR-028, RK-14)
- [ ] T051 [US4] Add the item to `reviewer/src/swreview/agent/checklist_v1.yaml` per `contracts/gate.md` section 4. Acceptance: T050 green; `test_prefix_stability.py` green against the regenerated fixtures

### The number guard

- [x] T052 [P] [US4] Write `reviewer/tests/unit/test_drawing_finding_number_guard.py` on `test_tools_session.py`'s `context`/`use_context` fixtures with a package carrying one PDF-ingest sheet (`dimensions[].text_as_read`, `general_notes`) and one native drawing (`DrawingNote.text`): an `observed` of "the wall is 0.05 mm thick" is refused as an `error_result` naming `0.05 mm` and the sheets searched when no cited sheet carries it, and accepted when a cited dimension text does; `12`, `12.5 mm`, `1/4-20` and `±0.1` are number-like; `F-003`, `cmp:0002`, `dnt:0007`, `Sheet 2` and `2026-09-18` are not and are accepted; the same rule applies to `requirement`; a refusal is a returned dict, never a raise (FR-033)
- [x] T053 [US4] Implement the guard in `reviewer/src/swreview/tools/session.py` `record_drawing_finding` as the sixth refusal before `build_finding`, reusing `_drawing_coverage_limits`'s sheet lookup for the cited sheets' text. Acceptance: T052 green (research R2.13)

### The counter

- [x] T054 [P] [US4] Extend `reviewer/tests/unit/test_tool_histogram.py` and `test_benchmark_compare.py` with `PackageSpec(tool_names=...)` runs: for `--study procedural_gate` and for `--study prerun_checks` the row's `lever_counter` is named "check_fit and check_axial_stack calls per run (must not fall)", `off`/`on` are the arm medians of the per-run sums, and `fell_in_runs` names every on-arm run whose sum fell below the off arm's minimum and is empty otherwise; `_counter_cell` renders the list after the medians the way `dropped_tools` renders (FR-034, SC-010)
- [x] T055 [US4] Implement the branch in `reviewer/src/swreview/benchmark/compare.py` `_counter`, `LeverCounter.fell_in_runs`, the `_counter_cell` clause, and the two `LEVER_COUNTERS` entries (lever 5's placeholder replaced). Acceptance: T054 green

**Checkpoint**: the gate exists behind its lever, is off by default, produces a brief whose ids match the report, fails into lines rather than refusals, guards the one path where model text becomes a claim, and the ledger can compute the regression it is gated on.

---

## Phase 7: Polish

- [ ] T056 [P] Update `README.md` (the "Start here" section, `swreview timing`, `swreview attention`, the lever, in the run and check sections) and mark `docs/review-backlog.md`'s stale pre-run ordering entry (`:1164`) resolved with the reason research R3 gives
- [ ] T057 [P] Run `quickstart.md` Scenarios 0 to 9 and the regression gate (`uv run pytest -q`, `uv run ruff check src tests`, `dotnet build`/`dotnet test SwReview.sln -c Release`); fix anything they surface in the task that owns it
- [ ] T058 [P] `specs/007-attention-policy-gate/checklists/requirements.md` re-validated against the amended spec; `plan.md`'s Source Code block reconciled with what landed (a file touched that is not listed, or listed and not touched, is corrected there)

---

## Phase 8: Measurement and workstation

- [ ] T059 [W] `quickstart.md` Scenario 11: on the pilot workstation, one review of the 810-11249 assembly ends with a pinned panel whose rows equal `report.md`'s "Start here"; Model check and Standards show the rows above the chips (SC-011)
- [ ] T060 [W] The owner records the four timing inputs with `swreview timing` after each pilot run from here on; the first real `session.json` carrying a baseline is the evidence (SC-001, RK-10)
- [ ] T061 [W] [K] `quickstart.md` Scenario 12: the gate's wall clock from `session.started` to the first `text.delta` on the pilot assembly with `--lever procedural_gate --standards-profile <real profile>`, recorded in `research.md` R5 (RK-12)
- [ ] T062 [W] [K] `quickstart.md` Scenario 13: six alternated runs with `--study procedural_gate`, scored, compared; the ledger row's `fell_in_runs` is empty and the median column carries `n=`; the row is committed to `docs/llm-efficiency-options.md` (FR-034, SC-010)
- [ ] T063 [W] [K] Behind T062's row and a held-out benchmark set: `ChatServer._start_review` (`reviewer/src/swreview/chat/server.py:1721`) passes `efficiency=EfficiencySettings(procedural_gate=True)` and the configured standards profile path as a code default; `test_no_lever_in_pane_settings.py` still green (no pane control); a pane review shows the gate's tool cards before the first model text and `report.md` opened from the pane carries "Start here" (FR-034)

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: after Setup; blocks US1 (the `timing` re-render) and US3 (the offline sites)
- **US1 (Phase 3)**: after Foundational; independent of US2 to US4
- **US2 (Phase 4)**: after Setup; T028 needs T006; T023 and T024 wait for T022 (the read-through)
- **US3 (Phase 5)**: after US2 (it needs `rank`, the section and the record); T039/T040 need `b3cb948` (landed)
- **US4 (Phase 6)**: after US2 (the brief renders the ranking); T048/T049 need `7e700e4` (landed) for a workstation-dumped standards package, not for the fixture
- **Polish (Phase 7)**: after every story chosen for the checkpoint
- **Measurement (Phase 8)**: T059 after US3; T060 after US1; T061 to T063 after US4 and after T100 of feature 006

### Task-level dependencies

- T003 after T002; T004 alone; T006 after T005
- T008 after T007; T010 after T009; T012 after T011 and T006; T014 after T013 and T010; T016 after T015
- T019 after T017, T018 and T004; T021 after T020 and T019; T022 after T021; T023 and T024 after T022; T026 after T025 and T019; T028 after T027, T026 and T006; T030 after T029 and T028
- T032 after T031 and T028; T034 after T033 and T019; T036 after T035; T038 after T037 and T034; T040 after T039 and T036; T041 after T038 and T040
- T043 after T042; T046 after T044, T045, T043 and T026; T049 after T047, T048 and T046; T051 after T050; T053 after T052; T055 after T054
- T063 after T062 and T060

### Parallel opportunities

- Phase 1: T001 and T004 together; Phase 2: T005 alone
- US1: T007, T009, T011, T013 and T015 are five test files that can be written together; their implementations land in order T008, T010, T012, T014, T016
- US2: T017, T018 and T020 together; T025, T027 and T029 together once T019 exists
- US3: T031, T033, T035 together; T037, T039 and T041 together (C#) while the Python sites land
- US4: T042, T044, T045, T047, T048, T050, T052 and T054 are eight test files that can be written together
- US3 and US4 may proceed in parallel after US2: they share `attention.py` read-only and touch no common file except `chat/server.py` (T032/T034/T036 against T063, which is last anyway)

---

## Requirement coverage

Every functional requirement has at least one task; the tasks listed are the ones whose acceptance would fail if the requirement were not met.

| FR | Tasks | FR | Tasks |
|---|---|---|---|
| FR-001 | T011, T012, T013, T014 | FR-019 | T031, T032 |
| FR-002 | T007, T008, T013, T014 | FR-020 | T027, T028 |
| FR-003 | T007, T009, T010, T011, T013 | FR-021 | T027, T029, T030 |
| FR-004 | T011, T012, T014 | FR-022 | T033, T034 |
| FR-005 | T007, T008 | FR-023 | T035 to T041 |
| FR-006 | T015, T016 | FR-024 | T039, T040 |
| FR-007 | T017, T019 | FR-025 | T033, T034 |
| FR-008 | T017, T019 | FR-026 | T042, T043 |
| FR-009 | T004, T017 | FR-027 | T047, T048, T049 |
| FR-010 | T004, T017, T024 | FR-028 | T048, T050, T051 |
| FR-011 | T023, T024 | FR-029 | T045, T046 |
| FR-012 | T018, T019 | FR-030 | T044, T046 |
| FR-013 | T025, T026 | FR-031 | T044, T046 |
| FR-014 | T017, T019 | FR-032 | T047 |
| FR-015 | T017, T019 | FR-033 | T052, T053 |
| FR-016 | T017, T019, T046 | FR-034 | T054, T055, T062, T063 |
| FR-017 | T020, T021 | FR-035 | T004 |
| FR-018 | T025, T026 | | |

---

## Notes

- **The policy is argued before it ships.** T022 is a task with an owner and no code; T023's catalogue test lands after it so it never pins a table nobody agreed to. Until T022, `swreview attention` exists and `report.md` does not carry the section.
- **Amplify, never filter, never write.** A task that removes a finding from a section, sets `Finding.group`, or makes rendering write to `session.json` has misread the feature; the fold is a row in the ranking.
- **Suppressed is a status or a decision, never the exception reference.** `exception_id` is set for a re-review waiver too; reading it would suppress the finding FR-008 protects.
- **The offline re-render is one function.** `timing`, `disposition` and `exceptions accept-*` go through `rerender_run_folder`; a fourth writer that renders without the package or without the standards header is the defect this feature removes.
- **`GET` computes and never writes.** The check re-read and the review route recompute the ranking in memory; the record is written only where the session is written.
- **Four pinned places for the lever, in one change.** The two test files, the prose sentence, and the review-session contract's `properties` (never `required`); `levers.md` is the fifth, documentation only.
- **No `%` anywhere in rendered attention text**, and neither "grade" nor "verdict" in the shared check page, because two existing page tests forbid them.
- **Nothing is adopted without the ledger.** T063 is the single line that changes the product's default and it lands behind T062's row and a held-out set.
