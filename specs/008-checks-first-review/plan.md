# Implementation Plan: Checks-First Review and the Token Budget

**Branch**: `008-checks-first-review` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-checks-first-review/spec.md`, the owner's
decisions of 2026-09-22 in `docs/roadmap-2026-09-22.md`, and the Phase 0 reconciliation of three
design passes in [research.md](research.md).

## Summary

Make a review cost what its new information costs, without changing what it finds. The 830-02342
review billed 12.4M input tokens for 99 findings; 95.7% of every request was earlier tool output
resent, one 205k-token check result was resent about thirty times, and 90 of the findings came from
checks that take no arguments. Five pieces, in the order they ship:

1. **The replay** (User Story 1, the gate): `swreview benchmark replay RUN_DIR` re-runs a recorded
   review's calls, in their recorded rounds, through the current code with a scripted provider, and
   prices every round with one vendored tokenizer (`o200k_base`) against what the recording billed:
   within 0.023% of every recorded round on the three recorded runs. It names every finding the
   current code would lose and exits 1 if any. Three committed fixtures, generated from the recordings
   with every identifying string scrambled, carry every later story's acceptance.
2. **Checks first** (User Story 2): the pane runs lever 5's pre-run by default, widened with live
   interference detection (every detected group judged, the rows persisted into the run folder's
   `package.json`) and the standards family's reason when it cannot run; the model opens on a
   counts-only digest; a `PrerunGuard` answers a repeated check with the recorded outcome instead of
   duplicating findings; the modelling-practice findings fold into one ranking row and one collapsed
   report subsection.
3. **The model's view** (User Story 3): a view computed beside every tool result - persist references
   stripped, check results as digests with `get_finding` on demand, gap rows grouped, compact JSON -
   while the payload, the session, the package and the report keep everything; the two bridge tools
   take entity ids; results older than two rounds become deterministic stubs in both adapters; every
   result is written in full to `tool-results/step-<n>.json`.
4. **Asking and answering** (User Story 4): parallel tool calls on in the pane for OpenAI with the
   dispatch still serial; several evidence answers in one submission and one resumed turn; the
   replay's labelled regrouped estimate.
5. **Cost** (User Story 5): every step records its result's size in bytes and tokens; the report
   names the five largest and says when the cache split was not reported; the pane's usage line
   states uncached and cached input in the report's words.

The pane is the only surface whose defaults change. No thirteenth lever, no new event type, no IR
schema change, no new agent stage, no change to a finding's content.

## Technical Context

**Language/Version**: Python 3.11+ for everything but one page function; plain vendored JavaScript for
`usageLine`; C# only in the add-in test that pins that line. No C# production change.

**Primary Dependencies**: one new runtime package, `tiktoken>=0.9,<1`, with its `o200k_base`
vocabulary vendored and hash-checked (research R2.7). Reused rather than rebuilt: `prerun.py`
(`prerun_checks`, `planned_calls`, `not_evaluated_families`, `PrerunCall`, `PrerunResult`,
`attach_standards`), `tools/registry.py` (`ToolDispatch`, `RecordedTool`, `record_call`,
`SessionSink`, `_offered`'s conditional registration), `agent/providers/fake.py`
(`FakeProvider`, `ScriptedTurn`, `for_presentation`), `report/rerender.run_folder_session`,
`report/attention.py` (`rank`, `fold`, `start_here_lines`), `report/markdown.py`,
`agent/settings.efficiency_from_levers`, `tools/session.py`'s entity lookup idiom and
`error_result`/`unknown_id`, `checks_interference.groups_of`, the C# console's
`PackageAppender.Merge` rule (as the rule, not the code), `report/attention_record.py`'s atomic
write, `tests/golden/fixtures/rms-part/generate_package.py`'s generator convention.

**Storage**: files only. New in a review run folder: `tool-results/step-<n>.json` (rotated to
`tool-results.<n>` by a pane retry). Changed: `package.json` gains the live interference rows and
gaps (in the pane; a merged copy in `--out` on the command line); `session.json` gains optional
`model_view`, `folded_families` and step sizes. New in the package: the vendored vocabulary. New in
the repository: three generated fixtures (about 4 MB). Outside the repository: the owner's fixture
denylist under `%LOCALAPPDATA%\SwReview\`.

**Testing**: pytest, strictly test-first. Every story ends with a replay of the committed fixtures as
its acceptance (T049, T078, T086, T093). A local integration test replays the real recordings
(skipped where they are absent). Characterization before the Gemini rebuild (T051). Byte-identity
tests for the goldens, the unfolded ranking, the adapter's all-off request bodies and the session with
the view on and off. A perf test for 1,000 interference groups. One C# test file for the usage line.
The tests that go red by design are named in the task that lands each change (research R2.47 to
R2.49).

**Target Platform**: as features 001 to 007. Everything but the paid measurement runs with no
SOLIDWORKS licence and no key.

**Project Type**: extends the reasoning side and one page function; the extractor is untouched.

**Performance Goals**: the replay of the big fixture completes in seconds (a pass is about 0.08 s after
a 0.5 s import on the recorded run); the tokenizer loads once in about 0.13 s and counts 504 KB in
about 0.02 s; the pre-run judges 1,000 interference groups within 30 s (a marked test); live detection
took 4.44 s on the 830 assembly and runs before the first model turn.

**Constraints**: the constitution's Principles I to VI verbatim (below); the replay needs no key, no
network and no SOLIDWORKS and writes nothing into the folder it reads; the recordings never enter the
repository; FR-029's golden byte-identity; every new session field optional; `test_no_lever_in_pane_settings.py`,
`test_docstring_split.py` and `test_prefix_stability.py` unedited; the Review page files are being
edited concurrently by feature 009, so 008's one page change lands last, rebased.

**Scale/Scope**: sessions to about 100 findings and 113 interference groups on the recorded runs,
1,000 groups in the perf test; 38 tool calls and 41 rounds on the largest recording; five stories; one
new command; four new `review` switches; one new route; one new tool (conditional); three optional
session fields; one new run-folder sub-folder; one new runtime dependency.

**Targets, measured by the replay** (the story acceptances): with every change off, every round within
1% and the finding set exact (SC-001); with the pane defaults, the big fixture under 1.0M (SC-002),
each small fixture's regrouped estimate under 0.3M with the strict figure below the recorded total
(SC-003 as amended), the follow-up under 30k (SC-004), no recorded finding lost on any fixture.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design (result at the end of the
table).*

| Principle | Gate | How this plan meets it | Status |
|-----------|------|------------------------|--------|
| I. Evidence before conclusions | Numbers from checked code; unknown stays unknown | Every verdict the model reads - the digest's counts, the guard's outcome, the folded group's counts - is counted from findings checked code recorded, by one tested counting helper. Absent evidence stays absent and says so: a digest states `rows_omitted` and `finding_ids_omitted`, a stub states `pruned`, `ids_omitted` and how to fetch again, a gap group its row count and `entity_ids_omitted`, the opening digest `and N more`. A family that could not run is a coverage item **and** a digest line with its reason (no bridge, a part root, detection failed, rows colliding, rows not written, no standards profile); a clean live detection is recorded as checked within its stated scope, never as a pass beyond it. The replay labels every estimated and lower-bound round and lists every finding it could not replay offline rather than counting it kept; an unknown cache split is "not reported", never zero; an unavailable tokenizer records `null`, never zero. | PASS |
| II. Deterministic numerics, agentic investigation | The model never computes a verdict | Checks first moves every argument-free check - including interference judgement for every detected group - into code before the model speaks; the model receives counts and ids and spends its turns explaining, asking and investigating what no check scopes. The guard makes it impossible for a model's repeat to record a second verdict. The view is derived beside the payload and never feeds a finding; findings are recorded while the tool runs; no finding is ever re-derived from a stub. Token counts are computed by one named tokenizer over the exact serialization sent. | PASS |
| III. Test-first with golden fixtures | Tests precede code; goldens for regression | Every implementation task is preceded by its failing test (the one exception, T051, is a characterization written green before the Gemini rebuild, as the principle intends for refactors). Three replay fixtures shaped like the recorded runs are committed with a generator and a hygiene test; the existing golden reports are pinned byte-identical; the tests that go red by design are named in the landing task and edited deliberately, never loosened. The interference check itself is unchanged; its new callers are tested for invalid input (a bridge without interference), missing input (no bridge, a part root), failure (a bridge error, the open circuit, a failed write) and boundaries (zero rows, collisions, 1,000 groups), each asserting the gap is reported, not passed. | PASS |
| IV. Semantic fidelity and traceability | Evidence records authoritative; persistent refs kept; versioned schemas | References are stripped from **the model's view only**: the IR, `package.json`, `session.json`, `report.md` and every stored result keep them unchanged (FR-015); the bridge tools resolve the model's entity id server-side to the exact persistent reference, so a finding still points at the exact entity. Persisted interference rows use the IR's existing arrays, are re-validated as an `EvidencePackage` and must equal the in-memory package before the atomic write; values and key order are kept (the bytes change from CRLF and .NET floats, research R2.18). The session contract gains three optional properties and no required one, each in lockstep with its model; no IR version moves. | PASS |
| V. Engineered enough | Reuse; DRY; explicit over clever | The pre-run calls the same dispatch the model uses; one serialization (`tool_result_text`) for the adapter, the replay and the step sizes; one `prune_history` for both adapters and the replay; one `check_digest` for the guard and the view; one resolver for the command line's settings shared by `review` and `replay`; one `answerable()` for both answer routes (removing an existing duplicate); one function for the pane's defaults; the fake extended with rounds rather than a second replay provider; the generator reuses the recording reader and the scripted bridge. No thirteenth lever, no per-tool view field, no configurability not asked for. Every edge case the spec names has a test, and the ones this pass found (the command-line input folder, the census test, the fail-bridge count, the follow-up margin) are named in research. | PASS |
| VI. Findings inspectable, coverage tracked | Every finding reproducible; the full record kept | Every tool result of every review - pre-run, guard answers, withheld and failed calls included - is written in full to `tool-results/step-<n>.json` before any stub replaces it in the model's view, whatever the settings (FR-021, SC-008); a failed write is a failed coverage item. The folded group keeps every finding in the report (inside `<details>`) and in the ranking (its member ids). The report names the five largest results; the replay report names its tokenizer, its framing constant and every estimate. Quality per design is measured by the replay's finding comparison on each recorded design, and SC-010 measures it on the real designs at the next sitting. | PASS |
| Technical constraint: documents are read, not written | No SOLIDWORKS mutation | Live interference detection is the existing read-only bridge operation. The one new write is the reviewer's own `package.json` in the run folder (the file the add-in dumped, rewritten by the same merge rule the console already applies) - never a SOLIDWORKS document, and on the command line never the input folder. | PASS |
| Technical constraint: out-of-process calls coarse, one STA thread | Bridge calls one at a time | Parallel tool calls change only the history's shape; the dispatch stays serial in response order, so SOLIDWORKS still receives one call at a time (a non-reentrant scripted bridge proves it). | PASS |
| Technical constraint: no generic code execution exposed to the agent | Curated tools only | One new tool, `get_finding`, reads one finding from the session; offered in a review only with payload slimming. | PASS |
| Technical constraint: third-party reuse respects licences | Licences checked | `tiktoken` is MIT-licensed. The vendored `o200k_base` vocabulary file is published by OpenAI with no stated redistribution terms; vendoring follows the design pass's recommendation and is recorded as an owner item (research R5), reversible without code changes beyond `tokens.py`'s loader. | PASS, one owner item |
| Development workflow: benchmark packages are the acceptance suite | Adoption measured | The pane defaults are adopted on the owner's decision of 2026-09-22, gated by the replay on the recorded designs (same findings, a token cut on every recorded run) rather than by the ledger; the held-out rule of 2026-09-19 was feature 005's adoption rule, which the owner superseded, not this file's. `benchmark run` keeps every change off, so the ledger stays comparable, and SC-010 measures the change on the real designs. | PASS |

**Post-design re-check**: no exception, no Complexity Tracking row.

## Project Structure

### Documentation (this feature)

```text
specs/008-checks-first-review/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, replay.md, tokenizer.md, checks-first.md, model-view.md, answer-batch.md, cost.md, cli.md}
└── checklists/requirements.md
```

### Source Code (repository root)

Every file this feature adds or changes. A file not named here is not touched; in particular
`chat-events.schema.json`, `ir.schema.json`, `settings.schema.json`, `UserSettings.cs`,
`CliProfileWriter.cs`, `Serve/PROTOCOL.md`, `mcp/server.py`'s payloads, `checks/interference.py`,
every check module, every IR model and every C# production file except `render.js`'s `usageLine`
are **reused unchanged**.

```text
.gitattributes                              # CHANGED: reviewer/src/swreview/tokenizer/* -text (T002)

reviewer/
├── pyproject.toml, uv.lock                 # CHANGED: tiktoken>=0.9,<1 (T002)
└── src/swreview/
    ├── tokens.py                           # NEW: TOKENIZER_NAME, count_tokens, TokenizerUnavailable; hash-checked,
    │                                       #      offline load (T002)
    ├── tokenizer/fb374d41…a790             # NEW: vendored o200k_base vocabulary, 3,613,922 bytes (T002)
    ├── findings.py                         # CHANGED: ENTITY_ID, finding_subject_key (T008)
    ├── benchmark/recording.py              # NEW: Recording, read_recording and its refusals; answer batches (T016, T087)
    ├── benchmark/replay.py                 # NEW: two passes, classes, accounting, findings, ReplayReport; answered_from_checks,
    │                                       #      stored, views and stubs, regrouped estimate (T023, T050, T079, T087)
    ├── cli.py                              # CHANGED: benchmark replay (T025, T079); _review_settings and review's
    │                                       #      --pane-defaults/--payload-slimming/--history-pruning/--prune-after (T075)
    ├── agent/settings.py                   # CHANGED: checks_first, pane_efficiency (T028, T081); ModelViewSettings,
    │                                       #      MODEL_VIEW_OFF/PANE, PaneDefaults, pane_defaults (T053)
    ├── agent/runner.py                     # CHANGED: folded_families, standards attach via checks_first (T038); live call
    │                                       #      args (T042); PrerunGuard wrap (T044); finalize skips family rows (T046);
    │                                       #      session.model_view recorded (T053); CoverageStopTools view (T065);
    │                                       #      tool_results_dir (T067); model_view wiring (T073); answer batch (T083)
    ├── prerun.py                           # CHANGED: checks_first (T028); digest, PrerunCall.payload (T038); live
    │                                       #      interference, LiveOutcome (T042); repeat_key, PrerunGuard (T044)
    ├── ir/loader.py                        # CHANGED: append_interference_run (T040)
    ├── report/session.py                   # CHANGED: folded_families (T030), model_view (T053), step sizes (T090)
    ├── report/attention.py                 # CHANGED: FAMILY_TITLES, family_of, the family fold, AttentionRow.family/rule_count (T032)
    ├── report/markdown.py                  # CHANGED: folded subsection (T034); cache-split line, largest results (T092)
    ├── agent/providers/__init__.py         # CHANGED: tool_result_text, FRAMING_TOKENS (T004); ToolCallResult.view,
    │                                       #      model_payload (T065); ModelViewAware, compact (T071)
    ├── agent/providers/openai_provider.py  # CHANGED: tool_result_text (T004); model_payload (T065); use_model_view,
    │                                       #      pruning, compact (T071)
    ├── agent/providers/gemini_provider.py  # CHANGED: model_payload (T065); use_model_view, per-round rebuild (T071)
    ├── agent/providers/fake.py             # CHANGED: ScriptedRound, ScriptedTurn.rounds (T006); model_payload (T065)
    ├── agent/providers/pruning.py          # NEW: result_stub, prune_history (T069)
    ├── tools/model_view.py                 # NEW: count_findings, check_digest (T036); strip_references, grouped_gaps,
    │                                       #      MODEL_VIEWS, model_view (T061)
    ├── tools/refs.py                       # CHANGED: resolve_entity_ref (T055)
    ├── tools/bridge.py                     # CHANGED: entity ids on bridge_capture/bridge_measure (T057)
    ├── tools/session.py                    # CHANGED: get_finding (T063)
    ├── tools/registry.py                   # CHANGED: get_finding registration, model_view on dispatch (T063); the view in
    │                                       #      RecordedTool (T065); ToolCallRecord.payload, stored results (T067);
    │                                       #      step sizes (T090)
    ├── tools/context.py                    # CHANGED: tool_results_dir (T067)
    └── chat/server.py                      # CHANGED: pane checks first (T048); probe (T059); tool-results rotation (T067);
                                            #      pane_defaults (T077); build_provider parallel (T081); batch route (T085)

reviewer/tests/
├── support/replay.py, scramble.py, review_bridge.py   # NEW (T014, T010, T012)
├── support/prerun.py                                   # CHANGED: live_prerun_package, LIVE_ROWS, CHECKS_FIRST (T041)
├── fixtures/replay/generate_fixtures.py                # NEW (T018)
├── fixtures/replay/{big-assembly,small-assembly-a,small-assembly-b}/   # NEW: package.json, session.json, events.jsonl (T018)
├── integration/test_replay_recorded_runs.py            # NEW (T026)
├── perf/test_prerun_perf.py                            # NEW (T041)
└── unit/
    ├── test_tokens.py, test_tool_result_text.py, test_fake_rounds.py, test_finding_subject_key.py      # NEW (Setup)
    ├── test_support_scramble.py, test_support_review_bridge.py, test_support_replay.py                 # NEW (Setup)
    ├── test_replay_recording.py, test_replay_fixture_hygiene.py                                         # NEW (Setup)
    ├── test_replay_accounting.py, test_replay_classification.py, test_replay_findings.py               # NEW (US1)
    ├── test_replay_fixtures.py, test_cli_benchmark_replay.py                                            # NEW (US1)
    ├── test_attention_family_fold.py, test_report_family_fold.py, test_model_view.py                   # NEW (US2)
    ├── test_ir_loader_append.py, test_checks_first_interference.py, test_prerun_repeat_guard.py        # NEW (US2)
    ├── test_gemini_model_view.py, test_model_view_settings.py, test_tools_refs.py                      # NEW (US3)
    ├── test_tools_registry_view.py, test_tool_results_store.py, test_result_pruning.py                 # NEW (US3)
    ├── test_openai_model_view.py, test_runner_model_view.py                                             # NEW (US3)
    ├── test_step_sizes.py, test_honest_cost.py                                                          # NEW (US5)
    ├── test_efficiency_settings.py         # CHANGED: new tests only (T027, T080)
    ├── test_session.py                     # CHANGED: folded_families (T029)
    ├── test_prerun_digest.py               # CHANGED: new tests; three red by design (T037)
    ├── test_gate_standards_in_review.py    # CHANGED: one test renamed and inverted (T037)
    ├── test_finding_explanations.py        # CHANGED: family rows skipped (T045)
    ├── test_chat_server.py                 # CHANGED: pane checks first, one red by design (T047); model view (T076);
    │                                       #      parallel flag (T080); batch route and ROUTES (T084)
    ├── test_chat_attention_route.py        # CHANGED: one red by design (T047); files_in recursive (T066)
    ├── test_chat_timing_route.py           # CHANGED: files_in recursive (T066)
    ├── test_chat_main.py                   # CHANGED: two red by design (T047); the probe (T058)
    ├── test_tools_bridge.py, test_mcp_server.py   # CHANGED: entity ids, red by design (T056)
    ├── test_tool_payload.py                # CHANGED: bridge pins regenerated (T057); slimmed-array pin (T062)
    ├── test_tools_session.py               # CHANGED: get_finding (T062)
    ├── test_cli.py                         # CHANGED: review's switches (T074)
    ├── test_parallel_tool_calls.py         # CHANGED: pane adapter, serial bridge, four queries one round (T080)
    ├── test_runner_provider.py             # CHANGED: answer batch (T082)
    └── test_report_tokens.py               # CHANGED: new tests only (T091)

extractor/SwReview.AddIn/Review/ReviewPage/render.js       # CHANGED: usageLine only, rebased onto feature 009 (T095)
extractor/SwReview.AddIn.Tests/ReviewPageUsageLineTests.cs  # CHANGED: two red by design, new cases (T094)

specs/
├── 001-agentic-design-review/contracts/review-session.schema.json  # CHANGED: folded_families (T030), model_view (T053),
│                                                                   #          step sizes (T088)
├── 001-agentic-design-review/contracts/cli.md          # CHANGED: benchmark replay (T025), review's switches (T075)
├── 001-agentic-design-review/contracts/agent-tools.md  # CHANGED: already_run (T044), bridge ids (T057), get_finding (T063)
├── 002-task-pane-assistant/contracts/chat-api.md       # CHANGED: POST /sessions/{chat_id}/evidence (T085)
├── 005-llm-efficiency/contracts/levers.md              # CHANGED: lever 5 (T048) and lever 6 (T081) pane defaults
├── 005-llm-efficiency/contracts/usage.md               # CHANGED: sections 5 and 8 (T095)
├── 007-attention-policy-gate/contracts/attention.md    # CHANGED: sections 2 to 4, the family fold (T032, rebased on 009)
└── 007-attention-policy-gate/contracts/gate.md         # CHANGED: the FR-030 note (T038)

docs/llm-efficiency-options.md              # CHANGED: bridge figure (T057); the 2026-09-22 decision entry (T097)
docs/review-backlog.md                      # CHANGED: the follow-ups (T098)
README.md                                   # CHANGED (T096)
```

**Structure Decision**: both trees are extended in place, as every feature since 002 has done. The
replay lives under `benchmark/` because the benchmark group owns offline measurement; the view under
`tools/` because it knows tool shapes, which providers must not import; pruning under
`agent/providers/` because it is a pure function of the neutral history the adapters own; the
tokenizer at the package root because the replay, the recorder and the report all read it.

## Phase 0 and Phase 1

Research in [research.md](research.md) (R1 to R5, with every reconciliation marked). Design in
[data-model.md](data-model.md) and [contracts/](contracts/). Twelve points tasks must honour:

1. **The replay lands first and is the gate.** Pass A (as recorded) proves fidelity, pass B
   (requested) prices the change; five classes, then two more as stories land; 12 framing tokens;
   estimates from recorded growth, labelled; findings compared by subject key as multisets; a lost
   finding exits 1. It writes nothing into the folder it reads.
2. **One of each shared piece.** `tool_result_text` for every serialization of a result,
   `prune_history` for every pruned request (both adapters and the replay), `check_digest` for the
   guard and the view, `count_tokens` for every count, `_review_settings` for both commands,
   `answerable()` for both routes, `pane_efficiency`/`pane_defaults` for the pane's defaults.
3. **The fixtures are generated and checked, never copied.** Full size, fictional, graded with
   `config/standards.example.yaml` (the census test admits no fifth profile), with the live rows in
   FR-009's shape; the generator refuses to write unless the finding keys match, large results are
   within 5%, and no identifying token remains.
4. **Checks first is lever 5.** Both lever fields stay; `checks_first()` decides; the pane passes
   `pane_efficiency(provider)`; the command line and `benchmark run` stay off, and `--pane-defaults`
   reproduces the pane.
5. **Live interference goes through the dispatch.** Once, whole assembly, the recorded settings;
   same-configuration rows superseded and restored on failure; every failure a coverage row and a
   digest line; the rows written to `<out>/package.json` atomically, never to an input folder.
6. **The guard answers, never re-runs.** Keys that catch a `document_id` subset; a recorded step for
   every answer; counts only for a folded family.
7. **The fold is a session value.** `folded_families = ["rms"]` under checks first; `rank()` and the
   report read it; `attention.py` stays free of settings; check folders never fold; unfolded sessions
   and every golden are byte-identical; the explanation pass never sees a family row.
8. **The view is beside the payload.** Computed once at `RecordedTool._finish`; `model_payload` is
   the only history content; findings, summaries, events, MCP, the Model check route and the goldens
   read the payload; `get_finding` only with slimming; the bridge tools take ids always.
9. **Pruning is a pure view of an append-only history.** Age by trailing assistant messages; errors,
   user and assistant messages exempt; only when smaller; deterministic stubs; both adapters; between
   turns for free; the Gemini rebuild guarded by a characterization written first.
10. **Every result is stored, always.** `tool-results/step-<n>.json` with the session id, for every
    recorded step of a review, before the next request; rotated with the session on a pane retry.
11. **Parallel calls change the history, not the dispatch.** Serial in response order; a
    non-reentrant bridge proves one call at a time.
12. **Cost in the report's words.** Sizes of the full payload at the one funnel; the report adds a
    line and a section only when they apply; the pane line reads "uncached + cached", lands last, and
    touches nothing else in the page.

## Delivery order

| Order | Story | Deliverable | Needs SOLIDWORKS |
|-------|-------|-------------|------------------|
| 1 | Setup | Tokenizer, `tool_result_text`, fake rounds, the finding key, test support, the recording reader, the three fixtures and their hygiene | No (the generator needs the dumps on this machine) |
| 2 | **US1** (P1) | The replay engine and command; SC-001 on the fixtures; the real-recording integration test | No |
| 3 | **US2** (P2) | `checks_first`, `pane_efficiency`; the fold (session field, ranking, report); `check_digest`; the digest; `append_interference_run`; live interference; the guard; explanations skip families; the pane default; the replay's `answered_from_checks` and acceptance | No (scripted bridge) |
| 4 | **US3** (P3) | Settings and session field; the resolver and entity ids; the probe; the view module; `get_finding`; the view in the registry and adapters; the store; pruning; `ModelViewAware`; runner and CLI wiring; the pane's model view; the replay's views, stubs and stored results; SC-002, SC-007, SC-008 | No |
| 5 | **US4** (P4) | Parallel calls in the pane; the answer batch (runner, route); the replay's batches and regrouped estimate; SC-003, SC-004, SC-005 | No |
| 6 | **US5** (P5) | Step sizes; the report's two additions; the end-to-end cost test; the pane usage line, last, rebased onto feature 009 | No |
| 7 | Polish | README, the efficiency decision entry, the backlog follow-ups, quickstart, reconciliation | No |
| 8 | Measure | The real profile placed; a paid review of each recorded assembly against the replay (SC-010); Retry and setup latency; the sitting's folders replayed | Yes, and a key |

**Sequencing that is not negotiable.** Setup and US1 first: no later story can claim a token or finding
result without the replay. US2 before US3's replay acceptance, because the pane defaults include checks
first and the requested pass classes answered calls. US3 before US4 (the follow-up budget needs
pruning; the serial-bridge test needs the store) and before US5 (the step sizes share the recording
funnel with the store). The pane usage line last, after feature 009's increments 1 to 3 land. The
three session-contract edits in story order, each with its model.

**External dependencies**: features 005 (levers 5 and 6, the pre-run, the usage events), 006 (the
standards check and `attach_standards_run`), 007 (the ranking, the gate's standards half, the record);
the recorded dumps of 2026-09-20 on the development machine; feature 009's increments 1 to 3 (on main
since 2026-09-23: `2c48e2b`, `cf3c66e`, `b5cfcb4`) for the page and 007's attention contract, and its
later increments, which render 008's folded group and answer batch; feature 010, which owns the
size-for-size contact rule; the next workstation sitting for SC-010.

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | SC-003 is unreachable under the recorded rounds (0.56M to 0.59M modelled), and the regrouped estimate's margin is thin (0.29M to 0.30M). | The strict figure is reported and must fall below the recorded total; SC-003 is gated on the labelled regrouped estimate (research R2.43, R4); a red result is recorded for the owner with the `--prune-after 1` figure rather than the rule bent; SC-010 measures real behaviour. |
| RK-2 | A slimmed view or a stub silently changes a finding or loses evidence. | Findings are recorded while the tool runs; the view is beside the payload; the byte-identity test on session, package, report and ranking with the view on and off (T072); every result stored in full (T066); the replay's finding comparison on every fixture. |
| RK-3 | The model repeats a check the digest reported and duplicates findings. | The guard answers with the recorded outcome and records a step; its keys catch a `document_id` subset (T043). |
| RK-4 | Judging every group reports every zero-volume contact as a demonstrated interference until feature 010. | Stated in research R2.17 and R5; the settings are the recorded run's so no recorded finding is lost; feature 010's contact rule is the next wave. |
| RK-5 | Rewriting `package.json` collides with the add-in reading it, or corrupts it. | A raw parse, re-validation to model equality, a temporary file and `os.replace`; any failure leaves every file untouched and becomes an unresolved coverage row; the input folder of a command-line run is never written (T039, T041). |
| RK-6 | A hung live detection blocks session creation. | Every failure the transport reports is handled; the hang itself is recorded as an owner item with the alternative (moving the pre-run into `ReviewRun.start()`); the latency is measured at the sitting (T104). |
| RK-7 | The vendored vocabulary is corrupted by a CRLF checkout or changes under a tiktoken upgrade. | `-text` in `.gitattributes`, a sha256 check before loading, a version pin, and a network-blocked load test (T001). |
| RK-8 | The replay and the adapters drift apart. | The replay calls the adapters' own serialization and pruning functions; the US5 acceptance asserts a step's recorded tokens equal the replay's count (T093). |
| RK-9 | A fixture leaks a real name or path from the recordings. | The generator's self-check refuses to write; the committed hygiene test and the owner's local denylist; design ids forbidden by name; no recorded string in the generator or a commit message. |
| RK-10 | Payload drift in current code breaks the fixtures' SC-001 lock. | That failure is the intended alarm; the generator regenerates the fixtures on this machine, and the real-recording integration test (T026) separates a replay defect from a fixture defect. |
| RK-11 | The Gemini per-round rebuild changes what Gemini is sent. | The characterization test is written green first (T051) and must stay green; the cross-turn thought-signature test is unedited; a live Gemini check at the next key-holding sitting (T106). |
| RK-12 | The 008 page change collides with feature 009's concurrent page work. | One function, `usageLine`, landed last after rebasing onto 009's increments; 007's attention contract edit likewise rebased (T032). |
| RK-13 | The bridge tools now want ids while MCP general chat still shows references. | The error names the id; the MCP follow-up is recorded (research R2.38, T098). |
| RK-14 | A command-line run behaves unlike the pane and a paid run is made with the old defaults. | `--pane-defaults` reproduces the pane in one flag; SC-010's paid runs are made through the pane; the quickstart says so. |

## Complexity Tracking

None. This feature adds no constitution exception, no SOLIDWORKS write path, no transport, no provider
and no agent stage. The one new runtime dependency and its vendored vocabulary are required by FR-002,
FR-003 and FR-026 together (a named tokenizer, at run time, with no network), and the alternatives are
in research R2.7.
