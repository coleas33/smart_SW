# Implementation Plan: Send the Review to the Model Only When the Engineer Wants It

**Branch**: `015-review-send-gate` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/015-review-send-gate/spec.md` (owner decisions 59A to
62A of 2026-10-08), four read-only maps of the same day, and the defaults recorded in
[research.md](research.md) R2.

## Summary

One box beside Review - "Send to the model when the checks finish", ticked by default so today's
review is unchanged - and, when it is unticked, a review that runs every code check, saves itself, and
waits for "Send to model". In the order the stories need it:

1. **Checks only** (US1): the setting `send_when_checked` (stored by the host, written without a
   restart, read when a review starts); `POST /sessions` with `send_when_checked: false` sets the run up
   with a `DeferredProvider` (no key, no client), runs the checks, finalizes with no turn before the
   chat is registered, and holds the chat in one new state, `awaiting_send`; the records, the report
   and the transcript say it was not sent; the page shows the box, the waiting status, and no Stop.
2. **Send** (US2): one route, `POST /sessions/{id}/send`, refused in a fixed order (no key included),
   its adapter built off the event loop; the real adapter is configured as setup would have; the
   checks' finalization rows are withdrawn so the turn reads the coverage a ticked review's first turn
   reads; the opening is the frozen one, byte for byte; the opening and the first request's size
   (feature 008's tokenizer) are built once on the worker and only read by the routes and by Send; a
   Send that fails before any request - its prepare half changes nothing, its commit half is guarded -
   leaves the review waiting and its record as it was, and a first request that fails before any
   round leaves it waiting with the failure recorded; either way the reason sits beside Send.
3. **Work while it waits** (US3): answers go through feature 008's batch route and are applied by code
   with no turn; decisions through today's route, which holds a waiting chat busy for its write so no
   Send runs beside it; the opening at Send is rebuilt from the regraded pre-run, with the wait's lines
   and no "withdrew" line; an apply that fails leaves the folder's whole record (before or after the
   apply, by where it failed) and the review restorable from its folder.
4. **Restart** (US4): a restored waiting review stays usable; its first action re-runs its checks from
   the same folder - live detection (one carried step), the drawing capability, the outcome lines,
   the answers, the decisions, the timing inputs and the model status carried, by identity, never by
   number, in memory until the re-run's one write; graded with the Standards profile in effect, a
   change named - with the record copied (not moved) so a failed re-run leaves it restorable, and a
   re-run the host gave up on adopted by the next; the host finds a waiting review again after
   SOLIDWORKS reopens.

Before any of it, a characterization of a ticked review - its requests, events and records - is
captured on the code as it was before this feature, so "today's behaviour, byte for byte" is held to
the old code, not to the feature's own (research R2.28).

Everything lands with no licence: the C# against fakes and the offscreen WebView2 driver, the Python
against fictional fixtures. One seat check (62A, SC-010) closes it.

## Technical Context

**Language/Version**: Python 3.11+ (the chat server, the runner, the providers, the pre-run, the
records, the words, the replay's reader); C# on .NET Framework 4.8 (the Review host, the backend
client, the run-folder search, the settings); JavaScript in the Review page under the pane's CSP.

**Primary Dependencies**: no new packages. Reused rather than rebuilt: feature 002's chat state
machine, `_require_idle`, `_play` and the retry rotation; feature 008's pre-run, `PrerunResult`, the
re-call guard, the answer batch, the one tokenizer, the replay's prefix and the replay's
`finding_subject_key`; feature 009's summary, words file, snapshot, chips, restore paths and
questions panel; feature 011's confirmed read; feature 013's part-roles regrade, `_restate`, drawing
outcome lines and `drawing_read`; `registry.record_call` for the carried live step; the host's
run-folder naming (`RunFolders`) and bounded head read pattern (`PackageIndex.HeadOf`); feature 014's
`write_atomic` (research R3).

**Storage**: files only. `settings.json` gains one optional boolean; `session.json` gains three
optional fields written only for an unticked review; `events.jsonl` gains one optional field and one
event type; a re-run adds `session.N.json` / `events.N.jsonl` / `tool-results.N/` as a retry does, and
a failed re-run's stream sits at an index of its own with no session file. No IR or package change; no
new run-folder file.

**Testing**: pytest (`SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts=""
-m "not live"`) and `uv run ruff check src tests`; xUnit (`dotnet build extractor/SwReview.sln -c
Release`, zero warnings, then `dotnet test`), the add-in tests in the gate (62A); page tests in the
offscreen WebView2 driver (`ReviewPageDriver`) against backend-made fixtures; the characterization
golden of a ticked review and the prefix characterization, committed first on the pre-feature code
(`pytest-regressions`, already a development dependency); the replay regeneration step where the
owner's recordings are (research R2.28); one [W] task on the seat.

**Target Platform**: as features 001 to 013. SOLIDWORKS is never started off the seat.

**Project Type**: extends the reasoning side's chat backend and runner, the add-in's Review host and
settings, and the Review page.

**Performance Goals**: the found-review search under 2 s on a 500-folder run root (FR-030, a marked
perf test); the estimate counted once per opening change, in the Send cache on a worker, never in a
route (the vocabulary loads once per process, about 0.13 s, `tokens.py`); no extra round trip on a
ticked review.

**Constraints**: the constitution's Principles I to VI; no new read-only exception, tool, bridge
command or lever; every new field optional and omitted at its default; a ticked review byte-identical
(the characterization golden captured before any refactor, the pane fixture's snapshot part, every
replay fixture, every model request; FR-035); the pane layout budget (260 to 420 px, two button rows
at 300 px, the summary in 300 by 600; measured: about 226 px of slack above the fold, research
R2.21); no company value or local path anywhere (FR-039).

**Scale/Scope**: four user stories; one setting; one chat state; one backend route; two host messages;
one event type; three session fields; one new provider class; one new clock function; six 015
contracts (`contracts/`) and amendment notes in features 001, 002, 008, 009, 011 and 013; about 140
tasks, one on the seat (an estimate for `/speckit-tasks`).

No NEEDS CLARIFICATION remains: every open point is a default in research R2, and the three questions
this plan adds (research R6) have defaults the tasks build.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design.*

| Principle | Gate | How this plan meets it | Status |
|---|---|---|---|
| I. Evidence before conclusions | Unknown stays unknown; nothing silently dropped | A review not sent leaves every model-owned item unresolved, saying why; nothing is marked checked because the model did not look (FR-009). An unknown size is "not counted", never zero. A re-run carries the first run's live outcome verbatim - never "not attached" after a live detection - and names in one row every answer or decision it could not carry. The restored line names when the checks ran, so old evidence shows its age | PASS |
| II. Deterministic numerics, agentic investigation | The model computes no verdict | The checks, the regrade, the identity matching, the token count and the running time are code; the model's opening states what code applied and asks it to re-derive nothing | PASS |
| III. Test-first with golden fixtures | Tests precede code; fixtures follow the code | Every implementation task follows its failing test (research R4); a characterization golden of a ticked review (every request, event and record) and of the replay's prefix, committed on the pre-feature code before any refactor, and a replay regeneration step where the recordings are (R2.28); the pane fixture's snapshot part and every replay fixture byte-identical, the labels block gaining keys only, regenerated in the commit that adds them; three new page fixtures generated with every clock pinned - two from a fictional package whose checks raise the part-roles and a drawing-candidate question, one from the fictional big assembly for the layout - held to a fresh generation; every request of the Send turn compared with a ticked review's; Send's guard at five failure points; fail tests and kill tests at three points for the re-run; the seat check last ([W]) | PASS |
| IV. Semantic fidelity and traceability | Native data; versioned schemas | No IR change; the session schema grows by optional, versioned-by-presence fields in 001's schema; carried decisions match on `finding_subject_key` (check, component ids, drawing places, entity inputs, configuration), carried answers on the question's own text, options and entity ids; the carried live step keeps every step index the first run's | PASS |
| V. Engineered enough | DRY; explicit; no speculation | One setting, one state, one route, two host messages; the shared pieces extracted or reused rather than copied - `configure_provider`, `request_prefix` (the replay's prefix moved), `asks_same` (two existing copies and a third use), `_apply_answers` (one body for the resumed and the waiting path), `_render_run` (one render for `_play` and the unticked start), `finding_subject_key` and `record_call` (reused as they are), `write_atomic` (014's), the test suite's one recording provider (moved to `tests/support`, no ninth copy); busy work reuses the one `running` state rather than a lock; no CLI flag (FR-037); every edge case of the spec named in a contract and a test | PASS |
| VI. Findings inspectable, coverage tracked | Reproducible; coverage visible | `model_status` with times, failures (carried across a re-run), the estimate and the ids the opening named; the report and the handoff say whether the review was sent; failed attempts and failed re-runs are kept in the folder, each stream at an index of its own | PASS |
| Documents are read, not written | No mutation | Nothing writes a document; the re-run reads no SOLIDWORKS; the drawing read stays feature 011's read-only seam, unchanged | PASS |
| SOLIDWORKS-side code; out-of-process calls coarse | No new bridge traffic | No new bridge command; a re-run makes no bridge call before Send; the found-review search runs off the SOLIDWORKS UI thread and opens one bounded file | PASS |
| Reasoning side runs without a licence (and, now, without a key) | Python, typed, versioned | A checks-only review needs neither; every new type is pydantic with `extra="forbid"` | PASS |
| Pilot scope; curated tools | Findings only; no generic execution | No new tool; the tool list a sent review carries is unchanged | PASS |

**Post-design re-check**: no exception, no Complexity Tracking row.

## Project Structure

### Documentation (this feature)

```text
specs/015-review-send-gate/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md (next)
├── contracts/{README.md, review-flow.md, estimate.md, records.md, recheck.md, pane.md, words.md}
└── checklists/requirements.md
```

### Source Code (repository root)

Every file this feature adds or changes, with the lane that owns it (Lanes below).

```text
reviewer/src/swreview/
├── chat/sessions.py                     # B: ChatState.AWAITING_SEND, TRANSITIONS
├── chat/server.py                       # B: POST /sessions fields and the unticked path (finalized and rendered before registered; `_render_run` extracted from `_render_report`); the send route (its adapter built in the thread pool); the decision and timing routes holding a waiting chat `running` for their write; NotWaiting, NotSent, NoCredential; the recheck claim (adoption; `_rechecking` holds a re-run's folder until it answers) and copy-rotation (the stray-stream rule); _play's settle; _read_review's restored block; the route table
├── agent/runner.py                      # B: start_review(send_when_checked=, earlier=); configure_provider; request_prefix; ReviewRun.awaiting_send, carried, _send_cache and build_send_cache, _send_error, attach_provider, send (prepare and commit halves, the guard, the finalization rows withdrawn), opening_at_send, first_request_estimate, _apply_answers (and its failure path), carry_from (in memory, finding_subject_key, timing, model status, the profile's change, a lost drawing outcome); the _run_turn failure hook (the deferred provider put back); the first-usage mark; finalize_session's not-sent reasons and running time; WAIT_ANSWER_LINE, NOT_SENT_ITEM, NOT_SENT_SUFFIX, NOT_CARRIED, INTERRUPTED_SEND
├── agent/events.py                      # B: local_now (the model-status clock)
├── agent/providers/deferred.py          # B: NEW DeferredProvider, ProviderNotSent
├── agent/providers/__init__.py          # B: EventType gains "session.sent"
├── agent/providers/openai_provider.py   # B: effort_mapping_for (the method delegates)
├── agent/providers/gemini_provider.py   # B: effort_mapping_for
├── agent/providers/fake.py              # B: effort_mapping_for
├── agent/settings.py                    # B: ProviderSettings.has_credential
├── prerun.py                            # B: prerun_checks(carried_live=); the carried live step (record_call) and call; the reviewed configuration's rows removed when the first run could not write them; restated(); named_finding_ids(); LiveOutcome.as_record/from_record; INTERFERENCE_ROWS_NOT_CARRIED, CARRIED_LIVE_NOTE
├── tools/context.py                     # B: carry_drawing_read (the cache and session.drawing_read)
├── checks/questions.py                  # B: asks_same
├── checks/part_roles.py                 # B: answered_roles through asks_same (no behaviour change)
├── tools/drawings.py                    # B: _is_confirmed_candidate through asks_same (no behaviour change)
├── report/session.py                    # R: ModelStatus (with the profile's identity), SendFailure, SendEstimate, LiveDetectionRecord, DrawingOutcome; three fields; save_session through write_atomic
├── atomic.py                            # R: NEW only if 014 is not on main first (research R3)
├── report/summary.py                    # R: SendWords, SendBlock (with session_id), ReviewSummary.send (omitted when None), review_ranking(send=), resume_text while waiting
├── report/snapshot.py                   # R: _root_document public and shared; the restored block
├── report/markdown.py                   # R: the header's model-status lines
├── report/review_words_v1.yaml          # R: the send block (with not_started), five labels.errors keys
├── benchmark/recording.py               # R: the two refusals
├── benchmark/replay.py                  # R: _prefix calls runner.request_prefix
└── handoff.py                           # R: model_status in the session summary

extractor/SwReview.AddIn/
├── Settings/UserSettings.cs             # H: SendWhenChecked (bool?, lenient), SendsWhenChecked, the load problem
├── Review/ReviewHost.cs                 # H: View; send_when_checked.save; review.start passes the value; review.started carries it; review.recheck; sessions.list's search; SessionRecord.ModelStatus; ReadyMessage variant
├── Review/IBackendClient.cs             # H: NewSessionRequest.SendWhenChecked, Recheck; ChatSessionHandle.Carried (optional parameter)
├── Review/BackendClient.cs              # H: the two body fields; carried in the handle; TimeoutFor (a re-run's own timeout)
├── Review/RunFolders.cs                 # H: FindNotSentReview (names first, one bounded session head)
├── Review/PaneActions.cs                # H: PagePayload.Flag
└── Review/ReviewPage/{index.html, app.js, render.js, app.css}   # W: the box, #send, the status line, the questions button, the follow-up and Stop, recheckThen, chips, Settings lines, transcript lines

reviewer/tests/unit/                     # each lane's tests (research R4.1)
reviewer/tests/unit/test_ticked_review_golden.py, test_ticked_review_golden/, test_request_prefix_characterization.py, test_request_prefix_characterization/   # G: NEW, first, on the pre-feature code (research R2.28)
reviewer/tests/support/recording_provider.py   # G: moved from test_prefix_stability.py, with for_presentation (R2.28)
reviewer/tests/support/questions_package.py    # G: NEW, the fictional questions package (R2.25)
reviewer/tests/support/roles_review.py   # B: extended only if its unclear part raises no named (hygiene) finding for the answer to withdraw (research R4.1)
reviewer/tests/fixtures/pane/generate_waiting_fixtures.py         # G: NEW (a fictional questions package built by code; every clock pinned)
reviewer/tests/unit/test_pane_waiting_fixtures.py, test_replay_fixture_hygiene.py   # G: NEW / the three fixtures join the hygiene list
extractor/SwReview.AddIn.Tests/Fixtures/review-waiting.json, review-waiting-restored.json, review-waiting-big-assembly.json   # G: NEW, generated
extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json  # G: labels block regenerated (keys only)
extractor/SwReview.AddIn.Tests/ReviewPageDriver.cs                # W: send_when_checked.save and review.recheck replies, error modes, HoldReviewRecheck (queuing later messages as the host's pump does)
extractor/SwReview.AddIn.Tests/                                   # each lane's tests (research R4.2)
specs/001-agentic-design-review/contracts/{review-session.schema.json, README.md}   # C
specs/002-task-pane-assistant/{spec.md, data-model.md, contracts/{chat-api.md, pane-host-messages.md, settings.schema.json, chat-events.schema.json, handoff-export.md}}   # C
specs/{008,009,011,013}/... (contracts/README.md's amendments table)   # C: one-line notes
docs/test-plan-2026-09-27/workstation-test-plan.md, reviewer/tests/support/seat_tasks.py   # S: the [W] step
```

**Structure Decision**: both trees extended in place. The send gate is a state of the existing chat
and a branch of the existing `create_session`, not a second server path; the deferred provider is a
small adapter beside the real ones because it stands where they stand; the re-run is a `POST /sessions`
variant because a retry already is one; the search is in `RunFolders` because that class owns the
folder names it reads.

## Phase 0 and Phase 1

Research in [research.md](research.md) (R1 to R6). Design in [data-model.md](data-model.md) and
[contracts/](contracts/). Points the tasks must honour:

1. **A ticked review is today's, byte for byte**, against the code as it was: the characterization
   golden and the prefix characterization are committed on the pre-feature code before any refactor,
   and every later commit keeps them byte-equal; the provider is built first, the opening, the
   events, the records and the pane fixture's snapshot part are unchanged (FR-035, SC-003; research
   R2.28).
2. **No provider is built before Send**: every unticked path is tested against a factory that records
   each call (`ProviderControl.built == []`) (FR-007, SC-001).
3. **One state, and `running` for work in flight**: no new busy flag; the page reads "waiting" from
   the summary's `send` block (research R2.4).
4. **The frozen opening when nothing changed; the one builder otherwise**, pinned to reproduce it
   (SC-004, research R2.8).
5. **The failed-send hook reads the round count before `emit_turn_failed`** (research R2.10).
6. **The record is copied, not moved, on a re-run**, the carry writes nothing before the re-run's
   one write, and a failed attempt's stream rotates alone (research R2.17).
7. **Identity, never number** for everything a re-run carries (FR-029): `asks_same` for answers,
   `finding_subject_key` for decisions, one carried step at the first run's index for the live call.
8. **Every sentence in one place** (`contracts/words.md`).
9. **No CLI flag** (FR-037).
10. **The Send turn starts from a ticked review's coverage**: the checks' finalization rows are
    withdrawn before the first request, and every request of the turn is compared, not only the
    first (research R2.27).
11. **Nothing is registered before it is finalized**: an unticked start and a re-run register their
    chat only after the finalization and render (research R2.6); a re-run the host gave up on is
    adopted, not refused (R2.17).
12. **An apply that fails** puts the record on disk back, writes one `error` and fails the chat; the
    page restores the review from its folder (research R2.13).
13. **Every fixture clock is pinned**, and model-status times render as stored (research R2.15,
    R2.25).
14. **Send has a prepare half that changes nothing and a guarded commit half**: a failure before any
    request undoes the pre-write, writes one `error`, and leaves the review waiting with its record as
    it was (research R2.10).
15. **No route builds an opening or counts a token**: the Send cache is built on the worker inside
    paths whose failure is defined, and the routes and Send only read it (research R2.8).
16. **No two threads write a waiting session**: a decision or timing write holds the waiting chat
    `running` (research R2.12).
17. **The Send block sits under the summary**, measured (research R2.21); the end state if SC-007
    fails there is an owner question, not another fallback.

## Delivery order

| Order | Phase | Deliverable | Needs SOLIDWORKS |
|---|---|---|---|
| 1 | Setup | the one-line amendment notes in the owning contracts; `feature.json` | No |
| 2 | Foundational | **first**, on the pre-feature code: the recording provider moved to `tests/support`, the fictional questions package, the characterization golden of a ticked review and the prefix characterization (research R2.28); then the setting (C#) and its schema; `ChatState.AWAITING_SEND`; the session fields and their schema; `write_atomic`; `local_now`; `DeferredProvider`, `effort_mapping_for`, `configure_provider`; `request_prefix` moved; `asks_same` extracted; `_render_run` extracted; the words file's new keys with the pane fixture's labels regenerated in the same commit; `ReviewPageDriver`'s two replies | No |
| 3 | **US1** (P1) | the box line run against `ReviewPageSummaryAcceptanceTests` and `ReviewPageNarrowLayoutTests`, unedited (measured to fit, R2.21); the unticked `POST /sessions` (the Send cache, the finalization and the render before registration); finalization's not-sent reasons and running time; the report header; `session.started`'s field; the host's box message, `review.start` and `review.started`, and the long timeout for `send_when_checked: false`; the page's box, waiting status, no Stop, follow-up off, transcript line; the summary's `send` block (sentence only); the waiting fixtures and their generator | No |
| 4 | **US2** (P2) | the send route and its refusals (its adapter built in the thread pool); `ReviewRun.send`'s prepare and commit halves, its guard and the finalization rows withdrawn; the estimate read from the cache; the first-usage mark and its mid-turn save; the failed-send hook; `session.sent`; the decision and timing hold; the page's Send block under the summary, Send, the failure line and the one `error` rule; `ReviewPageSendLayoutTests` measured and recorded; the replay's refusals | No |
| 5 | **US3** (P3) | `_apply_answers`, the waiting branch with the cache rebuilt, and its failure path with its two sub-cases; `drawing_outcomes`; `prerun.restated` and the rebuilt opening with the wait's lines; `named_finding_ids`; "Apply answers"; the page's apply-failure restore | No |
| 6 | **US4** (P3) | the recheck claim (adoption) and copy-rotation (the stray-stream rule); the carried live step, the rows a first run could not write, and `drawing_read` on the session; `carry_from` (in memory; answers, `finding_subject_key` decisions, timing, model status, the profile's change, a lost drawing outcome) and `coverage.recheck`; `carried` maps; `GET /reviews` restored block; `review.recheck` in the host; `FindNotSentReview` in `sessions.list`; the page's restored flow, the re-keying, the restart rule, the dated chip and a reload during a re-run | No |
| 7 | Polish | the handoff's model status; contracts landed-as; quickstart results; the workstation step and `seat_tasks` | No |
| 8 | Workstation [W] | SC-010 on the small assembly | Yes |

**Sequencing that is not negotiable.** The characterization golden and the prefix characterization
first, each committed on the pre-feature code before any product change; every later commit keeps
both byte-equal (research R2.28). The session fields and their schema before any writer (US1).
`configure_provider` and `DeferredProvider` before the unticked path. `request_prefix` moved, in one
commit with the replay's call, after the prefix characterization and before the estimate. `asks_same`
extracted, with the two existing callers, before the re-run's carry. The words file, the `Words`
model and the regeneration of every fixture that carries the labels block (the pane fixture, and the
waiting fixtures once they exist) in one commit, so every commit passes the gate; its review checks
each fixture's diff is added label keys only. The waiting fixtures regenerated by the lane that
changes what they show, in the commit that changes it.

**Sequencing against other features.** 015 needs 001 to 013 on `main`, which they are. Feature 014 is
not merged; research R3's table says who reconciles each shared file, and whichever branch merges
second classifies `send_when_checked` and `earlier` in 014's pane-parity test, passes `mark` on every
015 call of `recorded_call` and marks the carried live step `prerun`, regenerates the pane fixture
and the characterization golden (the golden on the first-merged side alone) in the merge commit,
and runs the replay regeneration step against the other branch's fixtures.

## Lanes and file ownership

| Lane | Owns | Tags |
|---|---|---|
| B - backend and runner | `chat/{sessions,server}.py`, `agent/{runner,events}.py`, `agent/providers/{deferred,__init__,openai_provider,gemini_provider,fake}.py`, `agent/settings.py`, `prerun.py`, `tools/context.py`, `checks/questions.py`, the `asks_same` call sites in `checks/part_roles.py` and `tools/drawings.py` | [py] |
| R - records, report and words | `report/{session,summary,snapshot,markdown}.py`, `report/review_words_v1.yaml`, `atomic.py`, `benchmark/{recording,replay}.py`, `handoff.py` | [py] |
| H - host and settings | `Settings/UserSettings.cs`, `Review/{ReviewHost,IBackendClient,BackendClient,RunFolders,PaneActions}.cs`, their tests | [C#] |
| W - the Review page | `Review/ReviewPage/*`, its page tests, `SwReview.AddIn.Tests/ReviewPageDriver.cs` | [page] |
| C - contracts and schemas | the owning features' contracts and schemas listed in `contracts/README.md` | [doc] |
| G - generated fixtures and characterizations | `tests/fixtures/pane/*`, `SwReview.AddIn.Tests/Fixtures/review-*.json`, `test_pane_waiting_fixtures.py`, the hygiene list, `tests/support/{recording_provider,questions_package}.py`, `test_ticked_review_golden.py` and `test_request_prefix_characterization.py` with their goldens | [py] |
| S - seat | the workstation test plan's step, `seat_tasks.py` | [doc] |

Hot files and their order: `agent/runner.py` (B: `configure_provider` and `request_prefix`, then the
unticked `start_review`, then `send` and the hook, then `_apply_answers` and the rebuild, then the
carry); `chat/server.py` (B: the unticked path, then the send route, then the recheck claim);
`app.js` (W: the box, then the waiting state, then Send, then the questions button, then the restored
flow); `ReviewHost.cs` (H: the view and the box message, then `review.start`, then `review.recheck`,
then the search).

## Risks and mitigations

Research R5 (RK-1 to RK-15). The ones that shape the order: RK-15, a refactor of the ticked path
drifting unseen, is closed first, by the characterizations committed before any refactor; RK-3, the
300 by 600 budget, was measured for this plan (about 226 px of slack; the box about 21 px; a Send
block above the summary failed its worst case, so it sits under the summary) and is measured again
on the big-assembly waiting fixture by `ReviewPageSendLayoutTests`, with an owner question as the end
state; RK-4, the re-run leaving a folder unrestorable, is closed by the copy-rotation, the
stray-stream rule and the fail and kill tests before the host or the page call it; RK-11, the Send
turn reading the checks' finalization rows, is closed with `ReviewRun.send` by the every-request
comparison, and RK-13 and RK-14, a Send failing before any request and two writers on one waiting
session, by its guard and the decision hold. RK-10, `POST /sessions` doing more before its 201, is
met by one long timeout for every call with `send_when_checked` false and the re-run's adoption, and
measured at the seat ([W]).

## Complexity Tracking

None. No constitution exception, no new tool, transport, lever or read-only exception. The one new
class (`DeferredProvider`) replaces nothing and stands where the adapters stand; every other addition
is a field, a state, a route or a message, and each shared piece is extracted from code that already
exists rather than added beside it.
