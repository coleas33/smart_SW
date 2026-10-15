# Contracts: Send the Review to the Model Only When the Engineer Wants It

Normative interfaces of feature 015. Each contract names the requirements it serves; `tasks.md`
names the contract every task implements. Every example value is fictional (`FICT-`), and no
contract carries a company value, a design name or number, or a local path (FR-039).

| Contract | What it fixes | Serves |
|---|---|---|
| [review-flow.md](review-flow.md) | `POST /sessions`' two new fields and the checks-only path (finalized and rendered before the chat is registered by the one tail it shares with a re-run, with the host's measured timeout); the `awaiting_send` state; `POST /sessions/{id}/send`, whose adapter is built inside Send on the chat's worker; answers, decisions and timing (queued on the chat's worker), follow-ups, Stop and shutdown while waiting, and an apply that fails; the opening at Send and the Send cache built on the worker; Send's prepare and commit halves (`session.sent` before the pre-write) and their guard, which only restores memory; the Send turn's coverage (the checks' finalization rows withdrawn first); a failed first request; `DeferredProvider`, what it loads, and `configure_provider`; a waiting run's SOLIDWORKS pipe released; the two event changes | FR-003, FR-006 to FR-011, FR-014 to FR-020, FR-023 to FR-025, FR-035 |
| [estimate.md](estimate.md) | The first request's size: what is counted, when (in the Send cache, never by a route), the unknown cases, Gemini, where it is shown and recorded, SC-006, and the characterization that proves `request_prefix` moved byte for byte | FR-012, FR-013, SC-006 |
| [records.md](records.md) | `model_status` (carried whole by a re-run; untouched by a Send that failed before any request) with its times and the profile's identity; `live_detection`, `drawing_outcomes`; finalization's not-sent reasons; the running time; the report header; the transcript's events; the replay's refusals; the handoff; the atomic write | FR-009 to FR-011, FR-032, FR-036, FR-040 |
| [recheck.md](recheck.md) | The re-run after a restart, which only Send starts: the host message and its measured timeout, the claim (adopting a waiting re-run) and the rotation by copy (a failed attempt's stream alone), the carried live step (and the rows a first run could not write), the carried drawing-read capability, the Standards profile in effect, what is carried (in memory only) and how it is matched, the line naming what is not, failure and cut-off, the re-run's answer, the restored snapshot (read-only, with the Send block), finding a waiting review after SOLIDWORKS reopens with one file opened, and the host's marks | FR-028 to FR-031, FR-041, FR-042, SC-008 |
| [pane.md](pane.md) | The box, its host message and the one settings write; `review.start`; the Send block (under the summary) and how an `error` ends a Send, a reload included; the status line; the questions panel; the follow-up and Stop; the restored review (read-only, with Send) and its re-run; the chips, marked from the host's record; the Settings section; the transcript lines; the layout budget, measured; every page-to-host row | FR-001 to FR-005, FR-012, FR-018 to FR-020, FR-025 to FR-027, FR-030 to FR-034, FR-042, SC-007 |
| [words.md](words.md) | Every sentence this feature adds, by key, where it shows and who reads it | FR-034, the spec's "the words are defaults" |

## Contracts of other features this feature amends

Each owning contract gains a one-line note dated 2026-10-08 pointing to the 015 contract that holds
the amendment, in Setup task T001. The amendment text and the JSON-schema additions land with the
task that changes the code (`tasks.md`, "Amends"); schemas cannot carry the Setup note, so it sits
in their owning README. This list is FR-038's, with what the plan found added (marked *plan*). The
owner's plan review of 2026-10-09 (decisions 68A to 80A, research R7) changed what several rows carry,
added one row (009's words table, 73A) and removed none.

| Feature | Contract or requirement | What moves | Text in |
|---|---|---|---|
| 001 | `contracts/review-session.schema.json` (+ `contracts/README.md`) | `ModelStatus`, `SendFailure`, `SendEstimate`, `LiveDetection`, `DrawingOutcome` defs; three optional `ReviewSession` properties | `records.md` section 1 |
| 002 | spec FR-006 | a review that waited takes no follow-up until the model has answered once | `review-flow.md` section 4 |
| 002 | `contracts/chat-api.md` | `POST /sessions` body (`send_when_checked`, `recheck`); "starts the review turn immediately" only when ticked; the new `POST /sessions/{id}/send` row; `POST /messages` refusal `NotSent`; `GET /reviews` of a waiting record: read-only with the restored Send block and the composed line; "Shutdown and settings changes" (a save while a review waits) | `review-flow.md` sections 1 to 4, `recheck.md` sections 1, 7, 8 |
| 002 | `data-model.md` section 3 (chat session state table) and section 4 (settings) | `awaiting_send` and its transitions; `send_when_checked` | `review-flow.md` section 2, `pane.md` section 1 |
| 002 | `contracts/pane-host-messages.md` | new rows `send_when_checked.save`, `review.recheck`; `ready`/`init` and `settings.saved` views carry `send_when_checked`; a failed `settings.save` write is `SettingNotSaved`; `review.started` carries it; `sessions.list` searches, refreshes its marked records and its items carry `model_status`; `status` stage `checking` | `pane.md` section 12 |
| 002 | `contracts/settings.schema.json` | the optional `send_when_checked` property | `pane.md` section 1 |
| 002 | `contracts/chat-events.schema.json` | `session.started.send_when_checked`; the `session.sent` event | `review-flow.md` section 7 |
| 002 | `contracts/handoff-export.md` (*plan*) | the session summary carries `model_status` | `records.md` section 7 |
| 008 | spec FR-008, FR-009; `contracts/checks-first.md` section 1 (no provider is set up and no first request follows when unticked), section 2 row 1 and section 3 (a re-run carries the first run's live outcome and does not detect again), section 4 (the opening rebuilt after a regrade; the wait's lines), section 7 (a re-run withholds the first run's tools) | the pre-run's live call, the opening, lever 13 on a re-run | `review-flow.md` sections 1 and 5, `recheck.md` section 3 |
| 008 | spec FR-030 | the tools withheld on a re-run are those of the first run's outcome | `recheck.md` section 3 |
| 008 | `contracts/answer-batch.md` section 1 step 3 | on a waiting run the answers are applied with no turn and carried into the opening | `review-flow.md` section 4 |
| 008 | `contracts/cost.md` (a new surface), `contracts/tokenizer.md` section 1 (the pane sentence names no encoding; a Gemini figure is called approximate) | the Send sentence | `estimate.md` |
| 008 | `contracts/replay.md` section 2 | two refusals ahead of the event read | `records.md` section 6 |
| 009 | spec FR-015 | on a waiting review a submission regrades by code and resumes nothing | `review-flow.md` section 4 |
| 009 | spec FR-021; `contracts/sessions.md` sections 4, 5, 6 | a restored not-sent review is read-only with the Send block, and its Send re-runs it; the snapshot's optional `send_in_flight`; the found review and its dated chip; the "not sent" chip mark from the host's record; `document.changed` asks the host again | `recheck.md` sections 8, 9; `pane.md` sections 3, 7, 8 |
| 009 | `contracts/views.md` section 2 (a second exception to "no token count", the Send block, under the summary) and section 3 (two status-line states) | the Send block, the status line | `pane.md` sections 3, 4 |
| 009 | `contracts/questions.md` sections 4, 5 | "Apply answers" and its sentence while a review waits | `pane.md` section 5 |
| 009 | `contracts/review-summary.md` section 1 | the summary's `send` block | `pane.md` section 3, `words.md` section 1 |
| 009 | `data-model.md` (the words table's `read_only` row) | the read-only line held as its two sentences, `read_only_lead` and `read_only_off`, composed to today's words; the lead also begins a restored not-sent review's line (73A) | `words.md` section 1 |
| 011 | `contracts/confirmed-open.md` section 1 | on a waiting review the read runs with no resumed turn after it; its outcome goes into the opening | `review-flow.md` section 4 |
| 013 | spec FR-040; `contracts/drawing-capability.md` section 6 | for a review that waited, the outcome lines go into the opening | `review-flow.md` section 5 |
| 013 | `contracts/part-roles.md` section 9 | on a waiting review the answer starts no turn, its line is stated as applied by code, and the "withdrew" line is left out | `review-flow.md` sections 4, 5 |

Feature 014 is not merged; its overlap with this feature is research R3's merge note, not an
amendment. No contract of features 003 to 007, 010 or 012 moves.

*Landed as* (T115, 2026-10-15): every row above has its amendment text in the owning document, not
only T001's note. Each was checked against the code as landed:
- **001.** Schema and README: T013-T014.
- **002.** Spec FR-006: T041. `chat-api.md`: T041, T049, T061 and T064, T066, T068, T095, T100.
  `data-model.md` sections 3 and 4: T017-T018, T032. `pane-host-messages.md`: T049, T051,
  T055, T074, T104, T106, T108. `settings.schema.json`: T032. `chat-events.schema.json` and
  its README: T035, T064. `handoff-export.md`: T111-T112.
- **008.** Spec FR-008, FR-009 and FR-030, and `checks-first.md` sections 1 to 4 and 7: T035,
  T086, T093. `answer-batch.md`: T084. `cost.md` and `tokenizer.md`: T044-T045. `replay.md`:
  T052-T053, T079.
- **009.** Spec FR-015 and FR-021. `sessions.md` sections 3 to 6: T055, T070, T100, T106,
  T108. `views.md`: T044-T045, T055, T075-T076, T108. `questions.md`: T090.
  `review-summary.md`: T044-T045. `data-model.md`'s words table: T030.
- **011.** `confirmed-open.md`: T084.
- **013.** Spec FR-040, `drawing-capability.md` section 6 and `part-roles.md` section 9: T086.

Where the code had to differ from a 015 contract, that contract carries a dated *Landed as* note at
the place it differs.
