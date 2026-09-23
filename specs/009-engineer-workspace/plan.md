# Implementation Plan: The Engineer's Workspace

**Branch**: `009-engineer-workspace` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/009-engineer-workspace/spec.md` (User Stories 1 and 2
landed on main as `2c48e2b`, `cf3c66e`, `b5cfcb4`), the owner's decisions of 2026-09-22 and
2026-09-23, the UI analyst's verified pass of 2026-09-23, and the Phase 0 decisions in
[research.md](research.md).

## Summary

Get every critical detail to a non-developer engineer as fast and as clearly as possible, without
losing any detail. The first two stories are on main: the review on screen is the model on screen,
and every finding is one headline and every issue reachable. Five stories remain, in the order they
ship:

1. **The summary** (User Story 3): a pure `report/summary.py` computes, from the ranking, the
   session and the package, one block the page prints verbatim at the top of Results - "99 findings
   in 18 issues", **Decide / Fix / Verify** by the policy's own keys (the owner's words, supplied by
   the backend from one words file), the questions, the parts not loaded, and one line per check
   goal (interference, fasteners, hole alignment, fits and stacks, tool access, mass and material,
   hygiene, drawings) with its state and a few words, the recorded reason in a fold. Feature 008's
   folded modelling-practice row becomes one collapsed group; feature 010's size-for-size contacts
   one folded list; part names replace component ids.
2. **Questions for you** (User Story 4): `request_evidence` gains an optional short form (a 140-
   character question, up to five offered answers, the checklist item it blocks); the page asks one
   question at a time above Start here and sends the answers together through feature 008's batch
   route, stating first what resuming will cost from the last conversation round's measured input.
3. **Results or Transcript** (User Story 5): two containers and a switch; Results holds what is
   wrong, Transcript how the reviewer got there - prose, tool calls, token counts - and a follow-up
   answer is pinned in Results.
4. **One review per model** (User Story 6): the host keeps a chip per review for the SOLIDWORKS
   session; choosing one restores it from the backend's live chat, or read-only from its run folder
   after a restart, through one snapshot builder and two read-only routes; returning to a document
   shows its newest review; a configuration switch is a document change; Show resolves against the
   review shown.
5. **Plain words** (User Story 7): status, bucket and error words from `GET /labels`; titles whole
   and named; check ids and component ids inside folds on every tab; errors that say what to do;
   Model check states rule statements rather than a fraction and an id list.

The ranking, `attention.json`, the check bodies, `report.md` and every finding's evidence do not
move; the only golden baselines that move are the ten holding a cut title, once.

## Technical Context

**Language/Version**: Python 3.11+ for the summary, the words, the routes and the tool's short form;
plain vendored JavaScript (no framework, no build step) for the Review page, the shared scripts and
the Model check page; C# (.NET Framework 4.8, as the add-in) for the host rows, Show by chat and the
configuration event.

**Primary Dependencies**: no new package on either side. Reused rather than rebuilt:
`report/attention.py` (`rank`, `Policy.needs_judgement_of`, `CHECKLIST_ITEM_IDS`, the family row of
feature 008), `report/unexamined.not_examined`, `report/session.load_session`, `ir/loader.load_package`,
`agent/events.UsageLedger`, `chat/server.resolve_run_dir` and the `GET /checks/{check_id}` pattern,
`web/shared/dom.js`, `web/shared/document.js`, `web/shared/attention.js`, `PaneActions`'
`PaneRunLookup`, `RunPackageIndex`, `tests/support/attention.py`, and feature 008's committed
`big-assembly` fixture.

**Storage**: files only, and only new files in the repository: `report/review_words_v1.yaml` (the
words and the goal table), the generated pane fixture
`extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json`. No run-folder file is added or
written by this feature: the two new routes read and write nothing. Page state lives in page memory.

**Testing**: pytest and xUnit with the offscreen WebView2 harness, strictly test-first. Each story
ends with an acceptance on one fixture shaped like the 830-02342 run: the backend summarizes 008's
`big-assembly` fixture (T022) and the page renders the snapshot of that same fixture (T032, T045,
T058, T065), kept in step by a byte-for-byte drift test (T023). A scan of the default view (SC-003),
a layout test at 300 by 600 (SC-001), a two-click reachability test (SC-006) and a 1,000-finding
performance bound. The tests that go red by design are named in the task that lands each change
(research R2.26).

**Target Platform**: as features 002 to 008: the Task Pane in SOLIDWORKS 2024 on Windows (WebView2,
a 260 to 420 px strip, no webfont) and the loopback backend. Everything but Phase 9 runs with no
SOLIDWORKS licence and no key.

**Project Type**: extends the reasoning side, the Review page, the shared page scripts and the
Review host in place.

**Performance Goals**: the summary is a pure pass over one session (the ranking route's own budget,
under 100 ms at 500 findings); Results renders 1,000 findings from a snapshot within 3 s offscreen;
restoring a chip is one `GET` and no model call.

**Constraints**: the constitution's Principles I to VI verbatim (below); the design rules - every
colour, face and size from `tokens.css`, no page script sorts or compares severity or status, every
string through `dom.js`, three tiers of ink; the backend computes every count, group, label and
order and the page prints and slices; every new field optional, so an older backend and an older
session render as before (FR-030); feature 008's code called rather than changed (one error-body
field excepted) and its `usageLine` body never touched; the recordings never enter the repository.

**Scale/Scope**: sessions to about 100 findings, 18 ranking rows and 4 open questions on the recorded
runs, 1,000 in the performance test; eight check goals; three reviews kept in a normal session; five
stories; three new backend routes, one new pure module per concern (summary, names, snapshot), one
words file; two new host rows and one new add-in file; three optional session properties.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design (result at the end of the
table).*

| Principle | Gate | How this plan meets it | Status |
|-----------|------|------------------------|--------|
| I. Evidence before conclusions | Unknown stays unknown; unresolved stays visible | A goal reads "not reached" when its own close-out row says an item was not closed, even if a rule row was checked, and "no check ran" when nothing speaks for it - never "checked" by default; the recorded reason travels verbatim in the fold, never cut. A question skipped stays open and nothing is filled in for it. An unknown resume cost says so rather than printing zero. A review restored from its folder is marked read-only with the reason. Parts not loaded are counted and named in the first block the engineer reads. | PASS |
| II. Deterministic numerics, agentic investigation | The model computes no verdict | Every count, group and state is computed by one tested Python function from the policy's own keys and the recorded coverage; the model's only new role is to phrase a short question with offered answers, which answer nothing until the engineer picks one. | PASS |
| III. Test-first with golden fixtures | Tests precede code | Every implementation task is preceded by its failing test; four acceptance tests are written after their implementation and pass with no further production code. The fixture is feature 008's committed, fictional `big-assembly`, and the page fixture is generated from it with a drift test. The golden baselines that move (ten, titles only) are named and regenerated deliberately, with their diff reviewed to `title:` lines. Every edge case of the spec has a test: an older backend, no findings, 1,000 findings, a question with no options, an answer from another window, a folder that is gone, a configuration switch during a turn. | PASS |
| IV. Semantic fidelity and traceability | Records authoritative; references kept; versioned schemas | No finding's evidence, id, component list or persist reference changes: titles are derived presentation, ids move into folds and stay in the transcript and the report. Show resolves against the review's own package by chat id, never against whichever run was latest. The session contract gains three optional properties in lockstep with the model; the words file carries its own version, echoed on the summary and the labels. | PASS |
| V. Engineered enough | Reuse; DRY; explicit over clever | One names helper replaces a copy in the explanations; one words file; one summary function behind three routes; one snapshot builder serving the live route, the disk route and the page fixture; one render path for a live turn's end and a restore; one run-folder lookup for `report.open`, `folder.open` and `entity.show`; the shared Start-here and rule rows changed once for every tab rather than forked. The chip rule is a scan of the host's list, not a new pointer; the page fixture is generated, not hand-copied; paging is added only if a measurement asks for it. | PASS |
| VI. Findings inspectable, coverage tracked | Every finding reproducible; coverage visible | The summary puts what was not reached, and why, above every list; every finding stays reachable in two clicks (SC-006) and every id and number in a fold, the transcript and `report.md`. The goal table is data, asserted complete against the checklist and the policy, so a check with no goal fails a test rather than vanishing from the summary. | PASS |
| Technical constraint: documents are read, not written | No SOLIDWORKS mutation | The configuration watch subscribes to a notification; Show selects as it does today. The two new routes read the run folder and write nothing (tested by every file's bytes and modification time). | PASS |
| Technical constraint: out-of-process calls coarse, one STA thread | COM on the application thread | The configuration event arrives on the SOLIDWORKS thread and only posts a message, as `ActiveDocChangeNotify` does; Show's lookup gains a folder argument and no new COM call. | PASS |
| Technical constraint: no generic code execution exposed to the agent | Curated tools only | No new tool; `request_evidence` gains three optional arguments. | PASS |
| Technical constraint: third-party reuse respects licences | Licences checked | No new dependency. | PASS |
| Development workflow: benchmark packages are the acceptance suite | Measured per design | The acceptance runs on the fixture shaped like the 830-02342 review; SC-007 and SC-002 are judged by an engineer on both recorded assemblies at the next sitting (Phase 9). | PASS |

**Post-design re-check**: no exception, no Complexity Tracking row.

## Project Structure

### Documentation (this feature)

```text
specs/009-engineer-workspace/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, review-summary.md, questions.md, views.md, sessions.md, plain-words.md}
└── checklists/requirements.md
```

### Source Code (repository root)

Every file this feature adds or changes. A file not named here is not touched; in particular
`report/attention.py`, `report/attention_record.py`, `report/markdown.py`, `chat-events.schema.json`,
`ir.schema.json`, `settings.schema.json`, `UserSettings.cs`, `Serve/PROTOCOL.md`, every check module
and 008's `usageLine` in `render.js` are **reused unchanged**.

```text
reviewer/src/swreview/
├── report/names.py                  # NEW: component_names, with_component_names (T006)
├── report/review_words_v1.yaml      # NEW: templates, group labels, goals, states, reasons, labels (T008)
├── report/summary.py                # NEW: Words, load_words (T008); the summary, ReviewRanking (T011);
│                                    #      family line (T017); contacts (T019); questions (T038); resume (T040)
├── report/snapshot.py               # NEW: review_snapshot (T021)
├── report/explanations.py           # CHANGED: calls component_names (T006)
├── report/unexamined.py             # CHANGED: NotExamined.headline (T013)
├── report/session.py                # CHANGED: EvidenceRequest.question/options/blocks (T034)
├── agent/events.py                  # CHANGED: UsageLedger.last_conversation_input (T040)
├── tools/session.py                 # CHANGED: request_evidence's short form (T036); title names (T062)
├── tools/recording.py               # CHANGED: title_from whole and named, TITLE_LENGTH removed (T062)
└── chat/server.py                   # CHANGED: attention route answers the summary (T015, T040);
                                     #      request_id on two refusals (T042); snapshot and disk routes,
                                     #      UnknownReview (T051); GET /labels (T060); rule_statements (T064)

reviewer/tests/
├── fixtures/pane/generate_pane_fixture.py                          # NEW (T023)
├── golden/test_golden/{ten baselines with a cut title}.yml         # CHANGED: titles only, red by design (T062)
└── unit/
    ├── test_report_names.py, test_review_words.py                  # NEW (Setup)
    ├── test_review_summary.py, test_review_goals.py                # NEW (US3; extended T016, T018, T037)
    ├── test_review_snapshot.py, test_review_summary_fixture.py     # NEW (US3)
    ├── test_pane_fixture.py                                        # NEW (US3; regenerated T062)
    ├── test_usage_ledger_resume.py                                 # NEW (US4)
    ├── test_chat_review_routes.py                                  # NEW (US6)
    ├── test_plain_words_fixture.py                                 # NEW (US7)
    ├── test_unexamined.py, test_chat_review_unexamined.py          # CHANGED (T012)
    ├── test_chat_attention_route.py                                # CHANGED (T014, T039)
    ├── test_session.py, test_events_schema.py                      # CHANGED (T033)
    ├── test_tools_session.py                                       # CHANGED (T035)
    ├── test_tool_payload.py                                        # CHANGED: pins regenerated, red by design (T036)
    ├── test_chat_server.py                                         # CHANGED: request_id (T041); ROUTES (T050, T059)
    ├── test_recording.py                                           # CHANGED (T061)
    └── test_chat_checks_routes.py                                  # CHANGED (T063)

extractor/SwReview.AddIn/
├── Review/ReviewPage/index.html     # CHANGED: summary (T025), questions (T044), the switch and two
│                                    #      containers (T047), chips (T057)
├── Review/ReviewPage/app.js         # CHANGED: T025, T027, T029, T031, T044, T047, T049, T057, T067, T071
├── Review/ReviewPage/render.js      # CHANGED: summaryBlock (T025), findingGroup (T027), contactList (T029),
│                                    #      questionsPanel, evidenceCard (T044), markers (T047), labels (T067),
│                                    #      the fold's Rule row (T069), plainError (T071) - never usageLine's body
├── Review/ReviewPage/app.css        # CHANGED: T025, T027, T029, T044, T047, T057 - tokens only
├── web/shared/attention.js          # CHANGED: attentionMeta options (T031, T067); data-check (T069)
├── web/shared/check-page.js, .css   # CHANGED: the rule id into the row's fold; .attention-check rule (T069)
├── Model/ModelCheckPage/check.js, check.css   # CHANGED: statements, not the fraction (T073)
├── Review/ReviewHost.cs             # CHANGED: record fields, sessions.list, session.forget (T053)
├── Review/PaneActions.cs            # CHANGED: entity.show's chat_id (T053)
├── Review/ReviewServices.cs         # CHANGED: EntityShowRequest.RunDirectory (T053)
├── Review/SwEntityResolver.cs       # CHANGED: (id, folder) lookups (T053)
├── Review/RunPackageIndex.cs        # CHANGED: an optional folder per lookup (T053)
├── ActiveConfigurationWatch.cs      # NEW (T055)
└── SwReviewAddIn.cs                 # CHANGED: lookups wiring (T053); the watch (T055)

extractor/SwReview.AddIn.Tests/
├── Fixtures/review-big-assembly.json                                # NEW, generated (T023)
├── SwReview.AddIn.Tests.csproj                                      # CHANGED: the fixture copied (T032)
├── SummarySample.cs, ReviewFixture.cs                               # NEW (T024, T032)
├── ReviewPageSummaryTests.cs, ReviewPageSummaryAcceptanceTests.cs   # NEW (US3)
├── ReviewPageFindingGroupTests.cs, ReviewPageContactsTests.cs, ReviewPageNamesTests.cs   # NEW (US3)
├── ReviewPageQuestionsTests.cs, ReviewPageQuestionsAcceptanceTests.cs                    # NEW (US4)
├── ReviewPageViewsTests.cs, ReviewPageScaleTests.cs                                      # NEW (US5)
├── ReviewPageSessionsTests.cs, ReviewPageSessionsAcceptanceTests.cs                      # NEW (US6)
├── ActiveConfigurationWatchTests.cs                                                     # NEW (US6)
├── ReviewPageDefaultViewScanTests.cs, ReviewPageLabelsTests.cs                           # NEW (US7)
├── ReviewPageErrorsTests.cs, ErrorLabelsCoverTheHostTests.cs                             # NEW (US7)
├── ReviewPageEventStreamTests.cs, ReviewPageAttentionPanelTests.cs,
│   ReviewPageNarrowLayoutTests.cs                                   # CHANGED: red by design (T046); harness (T068)
├── ReviewPageInjectionTests.cs, ModelCheckPageTests.cs, StandardsPageTests.cs,
│   SharedCheckPageTests.cs, AttentionSample.cs                      # CHANGED: red by design (T068, T072)
└── ReviewHostTests.cs, PaneActionsTests.cs, RunPackageIndexTests.cs # CHANGED (T052)

specs/
├── 001-agentic-design-review/contracts/review-session.schema.json  # CHANGED: EvidenceRequest (T034)
├── 001-agentic-design-review/contracts/agent-tools.md              # CHANGED: request_evidence (T036)
├── 002-task-pane-assistant/contracts/chat-api.md                   # CHANGED: T013, T015, T042, T051, T060
├── 002-task-pane-assistant/contracts/pane-host-messages.md         # CHANGED: T053, T055
├── 003-resilient-modeling/contracts/model-check.md                 # CHANGED: rule_statements (T064)
└── 007-attention-policy-gate/contracts/attention.md                # CHANGED: section 6 (T015, T047, T069)

README.md, docs/review-backlog.md                                    # CHANGED (T074, T075)
```

**Structure Decision**: both trees are extended in place, as every feature since 002 has done. The
summary, the names and the snapshot are three small pure modules under `report/` because they render
a session for a reader, which is what `report/` holds, and because keeping them out of
`attention.py` keeps the ranking a pure rule and away from feature 008's concurrent edit. The words
file sits beside the policy file it is not. The configuration watch is its own file because its
subscription rule is testable without SOLIDWORKS only behind a seam.

## Phase 0 and Phase 1

Research in [research.md](research.md) (R1 to R5). Design in [data-model.md](data-model.md) and
[contracts/](contracts/). Twelve points tasks must honour:

1. **The backend decides; the page prints.** Every count, group, order, label and sentence comes
   from the summary, the words file or an existing field; the page interpolates classes and slices
   in supplied order. `PageRuleScanTests` passes unedited.
2. **Groups by the policy's keys, over findings.** Within limits, decided, Decide, Fix, Verify,
   first match (the ranking's own precedence); severity never read; a folded family is its own line and in no group; the partition
   is asserted.
3. **Goals are data.** Longest prefix; "not reached" before "checked"; a category word on the line
   and the recorded sentence in the fold; the table asserted complete against the checklist and the
   policy.
4. **One words file.** Every backend word, versioned, no `%`, loaded once.
5. **The summary rides beside the ranking, not in it.** `ReviewRanking(Ranking)` on three routes;
   `attention.json`, the check bodies and `report.md` do not move.
6. **One snapshot builder.** The live route, the disk route and the page fixture; the disk route
   writes nothing and refuses anything it cannot read as an unknown review.
7. **The short form is optional.** Three arguments, checked in order, omitted when empty; the tool
   array pins move once, after 008's.
8. **One batch, one turn.** The page sends only answered questions through 008's route; the
   transcript card is a record; a refusal names its question through `request_id`.
9. **Two containers.** Results and Transcript own the pane in turn; findings live in Results and
   their markers in Transcript; only Transcript scrolls itself.
10. **Every action names its chat.** `entity.show` joins `report.open` and `folder.open`; no host
    pointer for the shown review.
11. **Restores cost nothing.** A chip is one `GET`; the transcript of a live chat is replayed only on
    demand, in a mode that does not close the stream per turn.
12. **Ids move, never vanish.** Titles whole and named at the one title funnel; ids in folds on every
    tab through the shared rows; errors in words with the class in the fold.

## Delivery order

| Order | Story | Deliverable | Needs SOLIDWORKS |
|---|---|---|---|
| 0 | US1, US2 | Landed on main (`2c48e2b`, `cf3c66e`, `b5cfcb4`) | No |
| 1 | Setup | The names helper; the words file | No |
| 2 | **US3** (P2) | The summary, its route, the headline; the family line (after 008 T032); contacts (after 010 T020); the snapshot builder; the fixture acceptance and the pane fixture (after 008 T018); the page's summary block, group, contacts, names; SC-001 | No |
| 3 | **US4** (P3) | The short form and its schema; the questions view; the resume cost; `request_id` (after 008 T085); the panel | No |
| 4 | **US5** (P4) | Results and Transcript; pinned answers; SC-006 and the performance bound | No |
| 5 | **US6** (P5) | The snapshot and disk routes; the host rows and Show by chat; the configuration watch; the chips, restore, read-only, replay | No (the watch is confirmed at the sitting) |
| 6 | **US7** (P6) | `GET /labels`; titles and the goldens; `rule_statements`; labels, ids into folds, errors, Model check on the page; SC-003 | No |
| 7 | Polish | README, backlog, quickstart, reconciliation, what must not move | No |
| 8 | Sitting | SC-007, SC-002, the configuration event, Show by chat, chips across a night, three answers in one turn | Yes, and a key for T084 |

**Sequencing that is not negotiable.** Setup before any backend task. The summary (T011) before any
page task that prints it lands on main (the page's own tests run on a sample and may be written
earlier). US4's page and US6's page after US5's containers only if they land after it; the order
above keeps each story's page work on the previous story's markup. The session-contract edit (T034)
serial with 008's three and 010 T020. The tool pins (T036) after 008's two. The title change (T062)
after the pane fixture exists (T023), because it regenerates it.

**External dependencies**: feature 008 - T018 (the committed fixtures), T030 and T032 (the folded
family), T057 and T062 (the tool pins), T083-T085 (the answer batch), T094-T095 (`usageLine`, which
this feature never edits); feature 010 - T020 (`Contact`, `ReviewSession.contacts`) and T022 (the
contact path), T016 and T043 (golden regenerations serial with T062), and T037, T047, T061, T067,
T075 (new policy classes, all under the goal prefixes; the goal table's completeness test names any
later one it lacks); the next workstation sitting for Phase 9.

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | The goal states read "checked" where the run did not close an item, overstating coverage. | "Not reached" precedes "checked" whenever the item's close-out row is unresolved, skipped or failed; tests for each precedence case (T010); the recorded reason in the fold. |
| RK-2 | A page change sneaks in a count or an order. | `PageRuleScanTests` unedited; the summary carries every number; the scan test of the default view (T065). |
| RK-3 | The restructure into two containers breaks pinned page behaviour silently. | The four pinned tests named red by design and rewritten deliberately (T046); every Review page suite green as each task's acceptance; the landed U8 binding tests kept green. |
| RK-4 | Show still resolves against the wrong package somewhere. | `entity.show` carries the chat id and resolves through the host's record (T052-T053); an end-to-end host test with a check tracked after the review; confirmed on a seat (T082). |
| RK-5 | Concurrent edits collide with feature 008 in `chat/server.py`, `report/session.py`, the schema, `test_tool_payload.py` and `attention.md`. | Each shared file is listed with both features' task ids (research R2.27); the 009 task names the 008 task it follows; page, host and summary work run in lanes 008 never touches. |
| RK-6 | Feature 010's contact list, check ids or task ids differ from what this plan read while 010 was being planned. | One accessor (`contacts_of`) adapts; the goal-table completeness test fails loudly on an unmapped id; T018, T034 and T062 re-verify 010's ids (T020, T016, T043) before they start. |
| RK-7 | Restoring a review's transcript by replay is heavy or closes the stream per turn. | The transcript is replayed only when chosen, in replay mode, with one scroll at the end (T056-T057); Results come from the snapshot. |
| RK-8 | The backend holds every kept review in memory. | Recorded as a follow-up (research R5); a normal night is three reviews. |
| RK-9 | The configuration event does not fire as the interop names suggest. | The handler types are verified in the 2024 SP5 redist; the rule is tested behind a seam; the sitting confirms it (T081), and until then a configuration switch is caught at the next document change as today. |
| RK-10 | Titles grow long enough to crowd the pane. | The landed two-line clamp; titles are the first sentence only; the full sentence is one press away. |
| RK-11 | A wording the owner has not approved reaches the engineer. | Only "Decide / Fix / Verify" is owner-decided; every other word is data in one file and listed for the owner (research R5). |

## Complexity Tracking

None. This feature adds no constitution exception, no SOLIDWORKS write path, no transport, no
provider, no tool and no agent stage.
