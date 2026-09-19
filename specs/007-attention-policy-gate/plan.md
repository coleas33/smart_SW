# Implementation Plan: Attention Policy and Procedural Gate

**Branch**: `007-attention-policy-gate` | **Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/007-attention-policy-gate/spec.md`, the design
brief [design-brief.md](design-brief.md) recorded from the 2026-09-18 planning session, and
the Phase 0 reading pass in [research.md](research.md).

## Summary

Make the pilot's own metric recordable, then decide in code which findings the engineer reads
first, reach every surface the report is rendered on with that decision, and only then let the
model start where the deterministic checks stopped. Four pieces, in the order they ship:

1. **Timing** (User Story 1): one writer for the four human minute inputs, reachable from a new
   `swreview timing <run_dir>` command over any run folder and a new session-scoped backend
   route for a pane review. The benchmark command becomes a wrapper over the same writer. The
   one model change is the `ge=0` the committed schema already states for the baseline. The
   adoption ledger gains a reported median column.
2. **The attention policy** (User Story 2): one pure module, `report/attention.py`, and one
   versioned policy file. A nine-key tuple sort with no weights, a fold recorded in the ranking
   rather than on the session, a "Start here" section of at most five rows above Findings, a
   not-amplified line and a coverage block; an `attention.json` record beside the session; a
   keyless `swreview attention <run_dir>` reader. The report renderer takes a keyword-only
   ranking that defaults to none, so its one golden does not move.
3. **Every surface** (User Story 3): all eight production renders of the report pass a ranking;
   the three offline re-renders go through one folder-aware helper; the record is written where
   the session is written, on the review path (including failure) and on both check paths; the
   two check bodies gain `attention` and the Review tab gets `GET /sessions/{chat_id}/attention`;
   the two keyless tabs render the rows above their bucket chips and the Review tab renders a
   pinned panel on session end, computed nowhere in the page.
4. **The gate** (User Story 4): an eleventh efficiency lever, `procedural_gate`, default off,
   that runs lever 5's pre-run widened with the standards check when a profile is attached,
   ranks the result and makes the ranked brief the first user message; a `standards.` checklist
   item; the number guard on the one tool where model text becomes a claim; the anti-drift test;
   the per-run fit and axial-stack counter the ledger has only ever named; and the ledger
   discipline before anything is adopted.

No new agent stage, no second provider round trip, no new event type, no model input to the
rank, no new field on `Finding` or `ReviewSession`.

## Technical Context

**Language/Version**: Python 3.11+ for everything but the pane rendering (the policy, the
record, the renderer, the folder re-render, the CLI, the routes, the pre-run, the lever, the
guard, the ledger); plain vendored JavaScript for the three pages; C# only in the add-in tests
that scan those pages. No new C# production code.

**Primary Dependencies**: no new packages; the CLI has no Rich and gains none. Python:
`pydantic` (the record and policy models), `pyyaml` (the policy file, already present). The
pieces reused rather than rebuilt: `report/markdown.render_report` (the single renderer for
every surface), `checks/rules/run.write_check_record` and `check_record` (the model for the
record), `checks/rules/run.write_report` and `checks/standards/run._write_report` (the check
paths' seam), `prerun.py` (`NotEvaluated`, `PrerunCall`, `PrerunResult.digest`, `planned_calls`,
`not_evaluated_families`, `prerun_checks`), `tools/standards_checks.attach_standards_run` and
`graded_documents`, `benchmark/timing.record_timing` (becomes a wrapper),
`benchmark/adoption.METRICS` and `decide`, `benchmark/compare._histogram_counter` (the idiom
for the new counter), `benchmark/scorecard.tool_histogram` (already records the counts), the
`error_result` pattern in `tools/session.py`, `_drawing_coverage_limits`'s sheet lookup, and
`web/shared/check-page.js` for the two check tabs.

**Storage**: files only. `attention.json` beside `session.json` in every review and check run
folder (new; rotated to `attention.N.json` beside `session.N.json`); the four timing inputs on
`session.json`'s existing `Timing`; `report/attention_policy_v1.yaml` in the package. No change
to `package.json`, `exceptions.json`, `check.json` or `events.jsonl`.

**Testing**: pytest over two committed fixture sessions shaped like the 2026-09-18 review and
model check (built on rules outside every family's high-severity set, research R2.4); a golden
report **with** a ranking beside the one existing golden of this renderer, which stays
byte-identical; the catalogue test over the four registries including the fastener family's
five constants; the "imports no provider, settings or network" assertion in the manner of
`test_standards_no_llm.py`; in-process ASGI tests for the two new routes, each added to the
door test's `ROUTES` tuple; the anti-drift test in `test_prerun_digest.py`'s style; xUnit page
scans for "no sort, no severity comparison in any page script" beside the existing usage-line
scan, and offscreen renders for the rows and the panel; and the workstation read-through of
`swreview attention` over the copied 2026-09-18 folders, the one validation that needs the
owner. The tests that go red by design and are edited deliberately are named in research R3.

**Target Platform**: as features 001 to 006. Everything but the pane rendering runs with no
SOLIDWORKS licence and no key.

**Project Type**: extends the reasoning side and the pane pages; the extractor is untouched.

**Performance Goals**: ranking a 500-finding session completes in under 100 ms (a marked
test); rendering the section adds nothing measurable to a report render; the gate's added wall
clock before the first model token is **measured, not targeted**, on the pilot assembly before
the gate reaches the pane (feature 006 T108's open number; the pre-run's quadratic coaxial-hole
scan is the likely cost and is on the backlog).

**Constraints**: the constitution's Principles I, II, III and VI verbatim (below); the two
keyless tabs construct no provider and read no key on any path, proven by making the provider
factories raise; the one golden byte-identical with `ranking=None`; lever 5's digest
byte-identical with the gate off; no new event type; no new field on `Finding` or
`ReviewSession`; the record reproducible from `session.json` alone; a check folder still told
apart from a review folder by the same rule; no `%` in any rendered attention text.

**Scale/Scope**: sessions to 500 findings; the consequence table over roughly sixty emittable
check ids; four user stories; two new commands; two new routes; one new lever; one new key on
two bodies; one new report section; one new run-folder file; one new folder re-render.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design (result at the end of
the table).*

| Principle | Gate | How this plan meets it | Status |
|-----------|------|------------------------|--------|
| I. Evidence before conclusions | Unknown stays unknown | The ranking amplifies and never filters: every finding stays in the severity sections below "Start here", suppressed findings render in full, and the not-amplified line counts what the top five left out. Coverage gaps get their own block rather than a place in the finding order. A check id the table does not name sorts `unclassified` and is printed by name; the catalogue test, not the report, is the guard. The gate's not-evaluated lines are backed one-to-one by skipped coverage items from the same object, in all three standards cases. The number guard refuses a drawing finding whose number no cited sheet carries. | PASS |
| II. Deterministic numerics, agentic investigation | The model computes no verdict and no rank | The policy is a pure function over a finished session; no tool accepts a rank; the model receives the rendered rows and an instruction not to re-derive them; its only authored text that reaches the report is a drawing finding, whose severity is a two-entry map and which cannot claim `demonstrated`. Severity is read as recorded, never recomputed. | PASS |
| III. Test-first with golden fixtures | Tests precede code; goldens for regression | Every task pair is test then implementation. A golden report **with** a ranking is added; the one existing golden of this renderer is pinned byte-identical with `ranking=None`; the fixture sessions pin the top five; ranking a shuffled session is asserted byte-identical; the catalogue test fails the build when a rule lands unclassified; lever 5's digest is pinned byte-identical with the gate off. | PASS |
| IV. Semantic fidelity and traceability | Persistent refs; versioned schemas | No IR change. The policy file is versioned and the version travels in `attention.json` and in the report's footer line. The record's per-row key values make any placement reproducible by hand. The review-session contract gains one optional lever name in `properties` only. | PASS |
| V. Engineered enough | DRY; explicit over clever; no speculative abstraction | One writer for timing shared by two commands and a route; one renderer with one keyword reaching eight call sites, enumerated by a test; one folder re-render replacing three lossy offline re-renders that exist or would exist on the day it lands; one policy module and one table; the fold recorded in the ranking rather than a mutation of the session; `attention.json` modelled on the check record; the gate reshapes a message already sent; the lever pays the four pinned edits rather than sidestepping the invariant; the fit/axial-stack counter serves lever 5 and lever 11 with one branch. A tuple of named lookups rather than a weighted sum. The needs-judgement set and the consequence table are the two knobs, both in the policy file. | PASS |
| VI. Findings inspectable, coverage tracked | Every finding reproducible; coverage on the report; time measured per design | "Start here" adds a reason line per row naming the key that placed it; the coverage block states the bucket counts and the run's own close-out rows with their reasons; timing becomes recordable on every real run and the median is reported on the ledger, which is the constitution's own measurement rule made possible for the first time. | PASS |
| Technical constraint: documents are read, not written | No mutation | Nothing in this feature touches SOLIDWORKS. | PASS |
| Technical constraint: 2026 dependencies | None | No interop member is added or called. | PASS |
| Technical constraint: no generic code execution exposed to the agent | No new tool | The gate registers no tool; it calls the check tools the model already has, and the standards tool is offered to a review context by the same attribute a standards run sets. The number guard narrows an existing tool. | PASS |

**Post-design re-check**: no exception, no Complexity Tracking row.

## Project Structure

### Documentation (this feature)

```text
specs/007-attention-policy-gate/
├── spec.md, design-brief.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, attention.md, timing.md, gate.md, cli.md}
└── checklists/requirements.md
```

`tasks.md` is Phase 2 output and is not created by this plan.

### Source Code (repository root)

Every file this feature adds or changes. A file not named here is not touched; in particular
`findings.py` (the fold never sets `group`), `checks/rms/*`, `checks/standards/*.py` other than
`run.py` and `verdict.py`, `agent/prompts/system_v1.md`, `tools/registry.py`'s
`REGISTRATIONS`, `web/shared/dom.js`, every C# production file and every IR model are
**reused unchanged**. The one existing golden of `report/markdown.render_report` does not
move. Reconciled 2026-09-19 against what landed (T058): the entries marked *landed as* below
differ from the plan as written.

```text
reviewer/src/swreview/
├── report/attention.py                 # NEW: the policy - AttentionKey, AttentionRow, Ranking, fold(), rank(),
│                                       #      the section lines (one function, two callers); loads the policy once;
│                                       #      imports no provider, settings or network module; never raises
├── report/attention_policy_v1.yaml     # NEW: version, needs_judgement, classes per check id, blind_spots per
│                                       #      pre-run family, triage_pass_preconditions
├── report/attention_record.py          # NEW: write_attention_record / read_attention_record (attention.json),
│                                       #      modelled on checks/rules/run.py write_check_record
├── report/rerender.py                  # NEW: rerender_run_folder(run_dir, *, package=None): session + package
│                                       #      when present + the standards header from check.json + ranking ->
│                                       #      report.md and attention.json; the one offline re-render (research
│                                       #      R2.7). Landed as: the `package=` keyword, for `_save_run`, whose
│                                       #      check folders hold no package.json
├── report/markdown.py                  # CHANGED: render_report(session, package=None, *, ranking=None);
│                                       #      "## Start here" between Summary and Findings; the footer line
├── report/dispositions.py              # CHANGED: apply_disposition re-renders through rerender_run_folder (site 8)
├── report/session.py                   # CHANGED: Timing.baseline_minutes gains Field(ge=0). Landed as: also owns
│                                       #      SESSION_FILE_NAME (rerender.py re-exports it), so attention_record
│                                       #      can read it without a cycle
├── checks/standards/verdict.py         # CHANGED (landed as): verdict_header(design_id, verdict_json), the header
│                                       #      rerender_run_folder rebuilds from check.json
├── benchmark/timing.py                 # CHANGED: record_timing_at extracted; record_timing is a wrapper; docstrings
├── benchmark/adoption.py               # CHANGED: METRICS["median_net_saved_minutes"]
├── benchmark/compare.py                # CHANGED: LeverDecision.median_net_saved_minutes, LEVER_COLUMNS, _lever_line;
│                                       #      LeverCounter.fell_in_runs; the fit/axial-stack _counter branch;
│                                       #      LEVER_COUNTERS entries for lever 5 and lever 11
├── cli.py                              # CHANGED: `timing` and `attention` commands; `--standards-profile` on review;
│                                       #      sites 1-3 pass a ranking (review :563, report :607, _save_run :1303,
│                                       #      the latter two through rerender_run_folder)
├── chat/server.py                      # CHANGED: POST /sessions/{chat_id}/timing; GET /sessions/{chat_id}/attention;
│                                       #      `attention` on check_result (:655) and standards_result (:785);
│                                       #      _render_report passes a ranking (site 4); _rotate_previous moves
│                                       #      attention.json; _start_review passes efficiency (T063, behind the
│                                       #      ledger row; not landed)
├── chat/sessions.py                    # CHANGED: record_disposition passes a ranking (site 5); record_timing_live
├── checks/rules/run.py                 # CHANGED: write_report passes a ranking (site 6) and writes attention.json
├── checks/standards/run.py             # CHANGED: _write_report passes a ranking (site 7) and writes attention.json;
│                                       #      the header renderer moved to verdict.py; missing_standards_phases
│                                       #      split out so the gate's not-evaluated line and the family's refusal
│                                       #      read one rule
├── agent/runner.py                     # CHANGED: finalize writes attention.json (including the failure path);
│                                       #      start_review(standards_profile=); the standards run attached between
│                                       #      build_context (:892) and the dispatch (:946); the brief at :988-989
├── prerun.py                           # CHANGED: prerun_checks runs when either lever is on; planned_calls reads
│                                       #      standards_run(context); three standards NotEvaluated reasons;
│                                       #      gate_brief(prerun, ranking); the guarded error read at :388
├── agent/settings.py                   # CHANGED: EfficiencySettings.procedural_gate (appended); _levers_sentence;
│                                       #      efficiency_from_levers refuses 11+5 and 11+7
├── agent/checklist_v1.yaml             # CHANGED: one item, standards.release / standards.
└── tools/session.py                    # CHANGED: record_drawing_finding's number guard (an error_result, never a raise)

reviewer/tests/
├── unit/test_attention.py              # NEW: the nine keys, the cross product, total order, the two fixture sessions,
│                                       #      the edge cases, no `%`, the no-provider import assertion
├── perf/test_attention_perf.py         # NEW (landed as): the 100 ms mark, with the other perf tests (`-m perf`)
├── unit/test_support_attention.py      # NEW (landed as): the builder reproduces every committed fixture byte for byte
├── unit/test_attention_policy_file.py  # NEW (landed as): the policy file's shape, classes, blind spots, no `%`
├── unit/test_attention_catalogue.py    # NEW: every emittable check id has a class (lands after the read-through)
├── unit/test_attention_fold.py         # NEW: the fold rule; session.findings untouched
├── unit/test_attention_record.py       # NEW: round-trip; reproducible from session.json; folder-kind; rotation
├── unit/test_report_start_here.py      # NEW: ranking=None byte-identical; the ranked golden; the eight-site
│                                       #      enumeration matched on the import; section order
├── unit/test_report_start_here/        # NEW: the ranked golden fixture
├── unit/test_rerender.py               # NEW: the three folder kinds; the standards header survives; the package is used
├── unit/test_timing.py                 # CHANGED: record_timing_at over the flat shape; the six wrapper tests unchanged
├── unit/test_session.py                # CHANGED: a negative baseline is refused naming the field
├── unit/test_cli.py                    # CHANGED: `timing` and `attention` in the --help tuple; two folder lists
├── unit/test_cli_timing.py             # NEW: records, refuses, re-renders; benchmark root refused naming benchmark time
├── unit/test_cli_attention.py          # NEW: keyless, writes nothing (hash before and after), the 2026-09-18 order
├── unit/test_chat_timing_route.py      # NEW: the six shapes of the disposition-route block; survives the next turn
├── unit/test_chat_attention_route.py   # NEW: 200 Ranking, empty_reason, 404, never writes
├── unit/test_chat_checks_routes.py     # CHANGED: `attention` on POST and GET, byte-equal; no provider
├── unit/test_chat_standards_routes.py  # CHANGED: the strict key set gains `attention`; the same
├── unit/test_chat_server.py            # CHANGED: ROUTES tuple gains both routes; rotation moves attention.json
├── unit/test_rms_run.py, test_standards_run.py  # CHANGED: the strict folder lists gain attention.json
├── unit/test_prerun_digest.py          # CHANGED: gate off byte-identical; the anti-drift assertion
├── unit/test_gate_brief.py             # NEW: the brief's sections, caps, lists; ids from ranking.rows
├── unit/test_gate_same_session.py      # NEW: gate calls are real steps and events; planned_calls with standards
├── unit/test_gate_standards_in_review.py  # NEW: two families in one session; the three not-evaluated reasons
├── unit/test_drawing_finding_number_guard.py  # NEW
├── unit/test_checklist.py              # NEW (landed as): the ten items, standards.release closes by prefix and by id
├── unit/test_efficiency_settings.py    # CHANGED: eleven levers; the two new refusals
├── unit/test_no_lever_in_pane_settings.py  # CHANGED: eleven
├── unit/test_usage_contracts.py        # CHANGED: a session carrying the eleventh lever validates
├── unit/test_prefix_stability.py       # UNCHANGED (landed as): it computes the prefix digests from start_review and
│                                       #      reads no fixture, so the checklist item moved nothing there
├── integration/test_coverage_stop.py   # CHANGED (landed as): the checklist counts nine -> ten
├── golden/test_golden/cover-blind-tap.yml  # CHANGED (landed as): one more open checklist item
├── unit/test_tool_histogram.py         # CHANGED (landed as): the fit and axial-stack counter per run
├── unit/test_benchmark_compare.py      # CHANGED: the median column; the counter and fell_in_runs; the committed doc
├── unit/test_adoption_rule.py          # CHANGED: the new metric changes no verdict
├── fixtures/attention/                 # NEW: session-20260918-review.json, session-20260918-check.json, and a
│                                       #      review-folder / check-folder pair for the CLI tests
├── support/attention.py                # NEW: builders for sessions with findings of given check, status, severity, subjects
├── support/prerun.py                   # CHANGED: a package with a cutlist phase row; a fictional profile; GATE_ON
└── support/studies.py                  # CHANGED: PackageSpec / scorecard grow timing fields

docs/llm-efficiency-options.md          # UNCHANGED by this feature (landed as): the ledger block is generated and no
                                        #      study is recorded, so the new column changed no committed byte
README.md                               # CHANGED: "What to read first"; timing and attention in the entry points
docs/review-backlog.md                  # CHANGED: the pre-run ordering entry marked resolved (research R3)

extractor/SwReview.AddIn/
├── web/shared/check-page.js            # CHANGED: renderAttention(result) called from renderResult before renderFilters
├── web/shared/check-page.css           # CHANGED: the rows' style
├── Review/ReviewPage/app.css           # CHANGED (landed as): the same class vocabulary for the Review panel
├── Model/ModelCheckPage/index.html     # CHANGED: <section id="attention"> above #filters
├── Standards/StandardsPage/index.html  # CHANGED: <section id="attention"> above #checks
├── Review/ReviewPage/index.html        # CHANGED: <section id="attention-panel" class="panel" hidden> above #transcript
├── Review/ReviewPage/render.js         # CHANGED: attentionPanel(ranking) builder, exported on SwReviewRender
└── Review/ReviewPage/app.js            # CHANGED: endSession fetches GET /sessions/{id}/attention, drops a stale
                                        #      response, renders the panel; resetTranscript clears it; bind()
extractor/SwReview.AddIn.Tests/
├── SharedCheckPageTests.cs             # CHANGED: renderAttention in SharedFunctions; the css selector rows
├── ModelCheckPageTests.cs, StandardsPageTests.cs  # CHANGED: the rows render in order; the sample bodies carry attention
├── ModelCheckPageInjectionTests.cs, StandardsPageInjectionTests.cs  # CHANGED: a hostile reason line renders as text
├── ReviewPageContractTests.cs          # UNCHANGED (landed as): its scan matches dotted message types only, so
│                                       #      '/attention' never reaches it
├── AttentionSample.cs                  # NEW (landed as): the one ranking fixture the three page suites share
├── ReviewPageAttentionPanelTests.cs    # NEW: the panel on session.ended from a stubbed fetch; the empty case; cleared
│                                       #      by a second Review press; a hostile reason line
└── PageRuleScanTests.cs                # NEW: no .sort(, localeCompare, severity literal list or severity/status
                                        #      comparison in any page script, comments stripped, with the allowlist

specs/
├── 001-agentic-design-review/contracts/review-session.schema.json  # CHANGED: procedural_gate in properties only
├── 001-agentic-design-review/contracts/cli.md           # CHANGED: three cross-reference rows
├── 002-task-pane-assistant/contracts/chat-api.md        # CHANGED: the two route rows
├── 003-resilient-modeling/contracts/model-check.md      # CHANGED: `attention`; attention.json in the folder listing;
│                                                        #      the stale "scope is part" sentence and the missing
│                                                        #      `reason` field corrected (research R3)
├── 005-llm-efficiency/contracts/levers.md               # CHANGED: the lever 11 row (landed as: it quotes no checklist
│                                                        #      byte counts, only tool-array bytes, so none moved)
├── 005-llm-efficiency/contracts/ab-harness.md           # CHANGED: sections 5 and 10.8 record the column
└── 006-standards-check/contracts/standards-check.md     # CHANGED: `attention`; attention.json; the `reason` field
```

**Structure Decision**: both trees are extended in place, as every feature since 002 has done.
The policy, the record and the folder re-render are new modules under `report/` because their
consumers are the renderer, the run folder and the CLI; the policy is not under `checks/`
because it grades nothing and not under `agent/` because the model never sees it except
rendered. The gate lives in `prerun.py` because it is that pre-run widened, not a second one.

## Phase 0 and Phase 1

Research in [research.md](research.md) (R1 to R5). Design in [data-model.md](data-model.md)
and [contracts/](contracts/). Eleven points tasks must honour:

1. **Timing first and alone, with one model constraint.** `record_timing_at(session_path, ...)`
   is the writer; `record_timing` wraps it and its six tests pass unedited. `swreview timing`
   takes a run folder, like `disposition`, and re-renders through `rerender_run_folder`;
   `record_timing` never re-rendered and still does not. `Timing.baseline_minutes` gains the
   `ge=0` its schema already states (research R2.9). The route copies `disposition`'s shape,
   writes the live session, and refuses any key that is not one of the four by name, because the
   model silently accepts a supplied net. The route reaches pane reviews; check folders are
   timed from the command line.
2. **One policy, one table, no arithmetic.** `rank()` sorts by a tuple of nine named lookups.
   Suppressed means `checked_within_scope` or an accepted or rejected disposition, and nothing
   else (R2.1). The consequence table and the needs-judgement set are the policy file, so a
   change is a data edit plus a fixture expectation. `rank()` never raises; the cross product
   proves it.
3. **Amplify, never filter, and never write.** Nothing leaves `session.findings`; the fold is a
   row in the ranking carrying its member ids (R2.2); suppressed rows sort last and render in
   full; the not-amplified line accounts for every row the top five left out; the coverage block
   is sourced from the session's buckets, its checklist close-out rows with their recorded
   reasons, and its open evidence requests (research R2.5).
4. **`ranking=None` is the default, eight call sites pass one, and three of them share a
   re-render.** The keyword default keeps the one golden byte-identical and keeps the
   re-modeler's separate renderer out of scope. A test enumerates the call sites of the import
   `from swreview.report.markdown import render_report`. `swreview disposition`, `swreview
   timing` and `exceptions accept-*` re-render through `rerender_run_folder`, which loads the
   package when present and keeps the standards verdict header (R2.7).
5. **The record is written where the session is written.** `finalize()` (including the failure
   path), `write_report` and `_write_report` each write `attention.json` from the same `Ranking`
   the report was rendered from. `is_check_folder` does not read it; `SESSION_FILES` does not
   list it; `_rotate_previous` moves it explicitly beside `session.N.json`. A review can claim an
   RMS check folder today and not a standards one; the rotation test covers what exists.
6. **The tabs fetch, never compute.** `check_result` and `standards_result` gain `attention`,
   byte-equal on POST and GET; `GET /sessions/{chat_id}/attention` serves the Review panel
   (R2.8). The page scripts render rows in the order supplied; one new test scans every page
   script for a sort or a severity comparison; the shared script names neither "grade" nor
   "verdict"; nothing rendered carries `%`.
7. **The gate is lever 5 widened, behind its own lever, and implies the pre-run.** `prerun_checks`
   runs when either lever is on; `procedural_gate` with `prerun_checks` and with `coverage_stop`
   are refused (R2.10). The brief is composed at the opening-message site from the digest and
   the same `Ranking` lines the report renders; `PrerunResult.digest()` is untouched and
   byte-identical with the gate off. No new event type.
8. **Standards inside a review is attached before the dispatch, and fails into a line.** The
   profile is loaded and the run attached between `build_context` and the dispatch, because the
   tool array is fixed at dispatch time; any failure - no profile, an unreadable profile, a
   package without the phase rows - is a `NotEvaluated` line and a skipped item, never a refusal
   (R2.11). The `standards.release` checklist item is added with it and moves the system prompt
   for every review, so the prefix-stability fixtures and the byte counts in `levers.md` are
   updated in the same change.
9. **The number guard reads the cited sheets.** `record_drawing_finding` refuses, as an
   `error_result`, an `observed` or `requirement` carrying a number-like token that no cited
   sheet's dimension text, note or annotation carries; ids and dates are not number-like; the
   free transcript is not guarded (R2.13).
10. **The named regression is computed, not named.** A `_counter` branch sums `check_fit` and
    `check_axial_stack` per run from `tool_calls_by_name` and fills `fell_in_runs` for every
    on-arm run below the off arm's minimum; it serves lever 5's placeholder and lever 11 alike.
11. **Nothing is adopted without the ledger.** The gate is default off until six alternated runs
    are on the ledger, `fell_in_runs` is empty, and the benchmark set holds held-out packages.
    The last task, passing the efficiency settings from `_start_review`, is the single line that
    changes the product's default, and it lands behind that evidence.

## Delivery order

| Order | Story | Deliverable | Needs SOLIDWORKS |
|-------|-------|-------------|------------------|
| 1 | Setup | The session builder, the two committed 2026-09-18-shaped sessions and the folder pair; the policy file skeleton; `rerender_run_folder` with its three-kind test (it serves US1 and US2) | No |
| 2 | **US1** (P1) | `record_timing_at`, the `ge=0`, `swreview timing`, the route, the ledger column with the regenerated document and the amended harness contract, the studies builder's timing fields | No |
| 3 | **US2** (P2) | `report/attention.py` and the policy file; the key, cross-product, total-order, fixture, fold, no-import and no-`%` tests; `swreview attention`; the owner's read-through; then the catalogue test enabled; `render_report(ranking=)`, the section, the ranked golden; `attention.json` on the three writers and in the rotation | The read-through needs the copied folders, not a seat |
| 4 | **US3** (P3) | The remaining call sites and the enumeration test; `attention` on the two bodies and the two contracts; `GET /sessions/{chat_id}/attention`; the two check tabs' rows; the Review panel; the page-rule scan | One workstation run to see the rows |
| 5 | **US4** (P4) | Lever 11 with its four pinned edits and two refusals; `start_review(standards_profile=)` and `--standards-profile`; the pre-run widened with the three not-evaluated reasons and the guarded error read; `gate_brief`; the checklist item with the prefix fixtures; the number guard; the counter branch; the anti-drift and standards-in-review tests | No |
| 6 | Measure | Six alternated runs, the ledger row, `fell_in_runs`, the gate's wall clock on the pilot assembly | Yes, and a key |
| 7 | Default | `_start_review` passes the efficiency settings with the gate on, behind the ledger row | Yes |

**Sequencing that is not negotiable.** US1 first, because nothing after it can be claimed
without a recordable metric. US2's read-through with the owner precedes the catalogue test
landing enabled and precedes any surface shipping the ranking: the consequence table is an
opinion and it is argued against real findings first. US3's Review panel is behind the
event-stream fix, which has landed (`b3cb948`). US4's standards half is behind the
drawing-attach fix, which has landed (`7e700e4`), and behind feature 006 T100, which has not.
Steps 6 and 7 are calendar-bound, not effort-bound, and step 6 on the one-package set exits
`benchmark compare` with 1 by design; the ledger file is the result.

**External dependencies**: feature 005's lever machinery and its pre-run; feature 003's check
record and run-folder skeleton; feature 006's standards check, its profile and its
`attach_standards_run`; the two pane bug fixes already on main; the 2026-09-18 run folders
copied off the pilot workstation.

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | The consequence table is wrong for the owner's engineering and the top five misleads. | The keyless reader and the read-through against the real 2026-09-18 findings come before any surface ships the ranking; the table is data with a version; a change is one edit plus a fixture expectation, and the record says which version ordered any past report. |
| RK-2 | The "Start here" section is erased by the next render, or a lossy offline re-render deletes the standards header. | Eight call sites are wired and a test enumerates them from the import; the three offline re-renders share `rerender_run_folder`, whose test covers all three folder kinds. |
| RK-3 | A rule lands with no consequence class and silently sorts mid-table. | It sorts `unclassified` and is printed by name; the catalogue test fails the build. It lands enabled only after the read-through so it never pins an unagreed table. |
| RK-4 | Run-to-run variance moves the top row between runs of the same assembly. | The ranking never invents a row; the coverage block makes an unevaluated family visible as a gap; the variance belongs to step 6's measurement, which records it. |
| RK-5 | The gate suppresses exploration: the model, told not to re-derive, also stops calling the fit and stack tools. | The counter is computed per run and `fell_in_runs` is a worst-case list; a non-empty list fails the gate regardless of any token saving. |
| RK-6 | The lever count invariant breaks in a place nobody listed. | Four pinned places named in research R2.10, edited in one change; the fifth, documentation-only, in `levers.md`. |
| RK-7 | The record and the report drift apart, or the brief and the report. | Both are produced from one `Ranking` object per write; the section lines are one function with two callers; the anti-drift test compares ids structurally; the record is asserted reproducible from `session.json`. |
| RK-8 | A review claiming an RMS check folder loses the check's ranking. | `_rotate_previous` moves `attention.json` with the session and a test reads the rotated record back. |
| RK-9 | The Model check tab cannot demonstrate the judgement key, and the first shipped surface is mistaken for proof of the policy's central claim. | Stated in the spec and the quickstart: that surface validates the consequence class; the report and the Standards tab exercise the judgement key; the read-through does. |
| RK-10 | Timing is recordable but nobody records it. | A named step: the owner records the four inputs from the CLI after each pilot run; the ledger column states `n=` so an empty column is visible. |
| RK-11 | The number guard refuses legitimate text. | Number-like is defined (a standalone decimal, with or without a unit); ids, sheet names and dates are test rows; a refusal is an error result the model may answer once. |
| RK-12 | The gate's wall clock before the first model token makes a review look hung in the pane. | Measured on the pilot assembly in step 6 before step 7; the gate's tool cards arrive on the stream before the first model text. The quadratic coaxial-hole scan in the pre-run is the likely cost and is already on the backlog. |
| RK-13 | Adding the ledger column turns two committed-document tests red. | The document is regenerated and the harness contract amended in the same change as the column; the tests are named in research R3. |
| RK-14 | The `standards.release` checklist item moves the system prompt for every review. | Named in point 8; the prefix-stability fixtures and the `levers.md` byte counts are updated in the same change, gate on or off. |
| RK-15 | `ChatServer._render_report` swallows exceptions, so a ranking bug on the pane path loses the report silently. | `rank()` is total by test; the ranking is computed inside the same try, so a failure costs what a render failure costs today and is logged the same way. |

## Complexity Tracking

None. This feature adds no constitution exception, no mutation path, no transport, no
provider and no new agent stage. The two new modules under `report/` are the policy, which has
three consumers and no home, and the folder re-render, which replaces three lossy writers with
one on the day it lands; the one new lever pays the existing invariant's pinned edits rather
than avoiding it.
