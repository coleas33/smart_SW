# Contract: A Waiting Review Survives a Restart

Normative for the re-run of a not-sent review's checks after its backend restarted, and for finding
such a review again after SOLIDWORKS reopens (FR-028 to FR-031, FR-041, FR-042, SC-008). Amends 002
`chat-api.md` (`POST /sessions` and `GET /reviews`) and `pane-host-messages.md`; 008 FR-008, FR-009,
FR-030 and `checks-first.md` sections 2 (row 1), 3 and 7; 009 FR-021 and `contracts/sessions.md`
sections 4 to 6. Amended on 2026-10-09 by the owner's plan review (research R7): decisions 68A, 70A,
71A, 72A, 73A, 76A, 78A and 80A.

A **waiting review** is a review whose record says `not_sent` or `send_failed` (`records.md`
section 1). It is **live** while this backend holds its chat in `awaiting_send`, and **restored**
when it is shown from its run folder. A restored waiting review is read-only, as feature 009
restores any review, plus the Send block (owner decision 68A, the spec's question 4 answered with
its alternative). **Send is the only re-run trigger**: Send re-runs the checks first, then sends. An
answer or decision the engineer wants to make after the restart waits until after Send, when the
review is a sent review and takes today's paths.

## 1. The trigger

| From | Message | Answer |
|---|---|---|
| page | `review.recheck {chat_id}` | `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document}`, or `error` |

The host, in this order (a refusal changes nothing):

| Order | Check | Refusal |
|---|---|---|
| 1 | `chat_id` names a review record of this host | `InvalidRequest` (none given), `UnknownChat` |
| 2 | the active document is not a drawing | `DrawingActive`, with the drawing sentence, as `review.start` |
| 3 | the active document is the review's own (path ignoring case, configuration exactly; feature 009's binding) | `ReviewNotActive` |
| 4 | the backend is running | `BackendUnavailable` |

*Amended 2026-10-20 (feature 002, owner decision 154A):* before check 1, the run root: one on a
network share, reached through a link or written as a device path, or could not be checked is `RunRootRefused`, not
retryable, and the record is kept - a re-run hands the backend its folder under the run root, which
the backend refuses on a share and spells otherwise through a link (002 `pane-host-messages.md`,
"The run root rule"). *Amended on 154A's reviews (findings F6 and N8):* the run root is judged again
once the backend is ready if a restart moved it, and a record whose run folder is not under the run
root in force - a settings save moved it since the review - is refused before the backend is asked,
`RunRootChanged`, not retryable, its record kept; the way on is a new review.

Check 1 is `review.recheck`'s own: it finds the record whose document and folder the rest uses.
Checks 2 to 4 run inside `CreateReviewSession(document, runDirectory, retryOf, ReviewMode.Recheck)` -
the one body `review.start` uses too (owner decision 71A; data-model section 9) - whose drawing
refusal and backend check are `review.start`'s; for `ReviewMode.Recheck` only, the document binding
sits between them, so a drawing active while a review of another document is re-run answers
`DrawingActive`, and another document with no backend answers `ReviewNotActive`. Then it posts `status {stage:
"checking", message: "Checking the saved evidence again..."}`, calls `POST /sessions` with the
record's own run folder, the settings in effect, the engineer, the Standards profile, the live bridge
as for any review, `send_when_checked: false` and `recheck: true` (what `ReviewMode.Recheck` writes) -
**no run folder is created and nothing is dumped** - then replaces its record (the same folder and
document, the new chat id, the time now, its `ModelStatus` kept: owner decision 73A), posts `status
{stage: "ready", message: "Checked the saved evidence again; nothing was sent to the model."}` and
answers `review.rechecked`. A backend refusal is re-thrown with the backend's own class (`Receive`
maps it), as `review.start` does.

**The call's timeout** (owner decision 70A). A re-run runs the checks inside `POST /sessions`, and
the host's one message pump waits for the call (`SwReviewAddIn.cs:1257-1289`), so the wait is a
measured bound, not a chosen one. `BackendClient.TimeoutFor` returns `ChecksOnlyTimeout` for the
`Wait` and `Recheck` modes - an unticked start (`review-flow.md` section 1) and a re-run - and 30 s
for a ticked start and every other call (`BackendClient.cs:39`). `ChecksOnlyTimeout` is set from
`reviewer/tests/perf/test_send_gate_perf.py`, which times a ticked start, an unticked start and a
re-run with a carry on `test_prerun_perf.py`'s thousand-group package. When the larger measured
re-run fits inside 30 s, research R2.17 says so and one 30 s rule covers every call: `TimeoutFor`
and `ChecksOnlyTimeout` go. Otherwise `ChecksOnlyTimeout` is that re-run times the margin R2.17
states (three, rounded up to the next 30 s: a default taken 2026-10-09, which the owner may
revise), recorded there and in RK-10. The [W] task times the re-run of the small and
the big assembly on the seat. If the host gives up anyway, the backend may still finish the re-run
and hold its chat waiting; the next `review.recheck` adopts that chat (section 2), so the review is
never left refused until a restart.

*Landed as* (T098, T103-T104, T115, 2026-10-15):
- **The timeout.** T098 measured the larger re-run at 8.8 s on the thousand-group package, inside
  30 s (research R2.17). So T104 removed `TimeoutFor` and `ChecksOnlyTimeout`: one 30 s rule,
  the client's `CallTimeout`, covers every call, a re-run's included.
  `BackendClientSessionBodyTests` pins that neither member exists. The seat's re-run timings
  (T119) set the bound again by R2.17's rule if one exceeds 30 s.
- **The shared body.** It is `CreateReviewSession(document, runDirectory, previousChatId, mode, id,
  summary, replacing)`. `review.recheck` passes the tracked record as `replacing`, and
  `retry_of` is sent as null for a re-run.
- **The binding.** It is `PageDocument.IsSameDocument`: the path ignoring case and the
  configuration exactly. The search (section 9) uses the same rule, and so does the host's check
  that it already tracks a review of the active document.
- **The record.** It is replaced through `Publish(record, replacing)`, the step `TrackSession`
  uses too. While `replacing` is still tracked, the new record takes its place in the list.
  Otherwise any record of the new chat id is dropped and the new one appended. The new record's
  `ModelStatus` is `replacing`'s own, so a `send_failed` record forgotten during its re-run is
  tracked again as `send_failed`.

The page sends `review.recheck` only for a restored waiting review, and only as the first step of
its Send (`pane.md` section 7; owner decision 68A). While it is in flight, the host's pump is busy
with it, so a Settings save the page could still send would be handled after it; the page refuses
Save itself for that time (FR-041).

## 2. The claim and the rotation

`POST /sessions` with `recheck: true`:

1. `_claim_run_dir(run_dir, retry_of=None, recheck=True)`:
   - a live chat on the folder that is `awaiting_send` is **adopted**: nothing runs, nothing is
     rotated or written, and the call answers `201` with that chat's `chat_id`, `review_session_id`
     and `not_examined`. This is what a host that timed out on a re-run the backend finished meets
     on its next try;
   - any other live chat on the folder (one that is `running`: answers being applied, a Send in
     flight) is `409 RunDirInUse`, as today;
   - a folder whose re-run is still running in this backend is `409 RunDirInUse` too. A re-run's
     chat is registered only after its finalization (`review-flow.md` section 1), so the claim
     itself holds the folder from the claim to the call's answer (`ChatServer._rechecking`, a set of
     folders added to and removed from on the event loop, so with no lock): a second re-run asked
     for while the first still runs - a host that timed out and asked again - is refused and starts
     nothing, and the one after the first answers adopts it. No host path today makes two
     concurrent claims of one folder (every `review.start` makes a new folder), so a ticked review
     never meets this refusal;
   - with no live chat: a folder with no readable `session.json` is `404 UnknownReview` (feature
     009's "This review can no longer be restored." on the page); a record with no `model_status`,
     or one in state `sent`, is `409 NotWaiting`. The earlier record is that `session.json`, loaded.
2. `_rotate_previous(chat, keep_record=True)`, by what the canonical stream is:
   - **the earlier record's own stream** (the first line of `events.jsonl` is a `session.started`
     naming `session.json`'s `session_id`): one free index N for the set, as a retry's, but
     `session.json` and `attention.json` are **copied** to `session.N.json` and `attention.N.json`,
     while `events.jsonl` and `tool-results/` are **moved** to `events.N.jsonl` and
     `tool-results.N/`;
   - **a failed attempt's stream, or none** (the first event names another session, or the file is
     absent, empty or unreadable - what a failed or killed re-run leaves): the stray `events.jsonl`
     and `tool-results/`, those present, move to their own free index with **no session file
     beside them**, and the earlier record is not copied again, because the attempt that left them
     copied it. Only when no `session.K.json` in the folder holds the canonical record's
     `session_id` (a stream deleted by hand) are `session.json` and `attention.json` copied to that
     index too.

   So every index holds either a session with the stream it wrote, or a failed attempt's stream
   with no session, and `_next_free_index`'s one index per session (`chat/server.py:542-555`) still
   reads true. `GET /reviews` reads only the canonical `session.json`, never an index. A leftover
   `.session.json.<random>.tmp`, which a kill inside `write_atomic` leaves between writing the
   temporary and its `os.replace`, is neither a session nor a stream: `GET /reviews`, the rotation
   and the next re-run pass over it (owner decision 76A's cut-off, section 11).

Until the re-run's finalization replaces it (atomically, `records.md` section 8), the canonical
`session.json` is still the earlier record. So a re-run that fails, is refused after the claim, or is
cut off by a crash, a shutdown or SOLIDWORKS closing leaves `session.json` the earlier record -
restorable through `GET /reviews`, read-only with Send offered, offered after a reopen (section 9),
with its answers and decisions intact - and the failed attempt's stream and results beside it in the
folder (FR-041). After a
failed or killed re-run the folder holds: the canonical `session.json` and `attention.json` (the
earlier record, whole); their copies and the earlier record's own stream at index N; and, as the
canonical `events.jsonl` and `tool-results/`, the failed attempt's partial stream and results, or
nothing when it was cut off before its first event. The next re-run moves those to their own index
(the second case above). Nothing is sent, and nothing needs recovering.

*Landed as* (T094-T095 and owner decision 90A, T115, 2026-10-15):
- **The held folder.** There is no `ChatServer._rechecking` set. The folder is held in the
  existing `ChatServer._pending_run_dirs`, which already held every start's folder from its claim
  to its answer. `_claim_run_dir` checks that set first, so a second claim of a folder whose
  re-run still runs is `409 RunDirInUse` (C47, research R8).
- **The record read.** `create_session` adds the folder to `_pending_run_dirs` right after the
  claim. It then reads the earlier record (`_waiting_record`) on the thread pool, so a second
  claim made while the read awaits is refused too (90A). A refusal from that read releases the
  folder.
- **The rotation.** It is `_rotate_previous(chat, keep_record=<the earlier record's
  session_id>)`, not `keep_record=True`. It hands over to `_rotate_kept`, which compares that id
  with the stream's first event and with each `session.K.json`.

**The commit point** (owner decision 93A, 2026-10-15). The re-run's finalization writes
`session.json` first, through `write_atomic`'s `os.replace`; that replace is the commit point.
Everything above holds before it. After it the re-run is complete and its new waiting record is
canonical: a failure or a kill after it - while `attention.json` is written, or while
`session.ended` is emitted - leaves the new record, which `GET /reviews` restores read-only with
Send offered, which FR-030 offers after a reopen, and whose Send re-runs it (its `rechecked_from`
names the earlier record, kept at index N). `attention.json` may then still be the earlier
session's ranking. It is never read for the restore - `GET /reviews` ranks from `session.json`
alone (section 8) - and `read_attention_record` refuses it by its session id
(`StaleAttentionRecord`). The next re-run's rotation copies each canonical file to an index only when
it is the record's own, so that ranking is not kept beside a record it does not rank, and the
re-run's finalization writes `attention.json` again.

*Amended 2026-10-15 (feature 016 lands on this feature, owner decision 99A; the T116 integration
review's fourth finding):* a waiting review started with saved engineering context records its
attachment in `model_status.engineering_context` (`records.md` section 1). Its re-run carries it:
after the record read, the backend reloads the context that field names from the run's fixed
private store and requires the store's head to be that exact context id and head digest with that
saved package digest. It does not require the folder's package
to be the saved baseline, since the first run's live checks may have appended evidence to it,
which the summary marks as needing review. *Amended 2026-10-15 (owner decisions 105A and 107A):*
it does require the baseline's package id, root document and configuration, and the live check's
own rewrite now keeps inputs matched (016 `pane-context.md`). The refusal's message names the one
action left, new context evidence from the Engineering context panel, and the page's label for
`EngineeringContextConflict` points there too. A head changed since then is `409
EngineeringContextConflict` before the rotation, so nothing in the folder moves and the earlier
record stays canonical and restorable. `POST /sessions` with `recheck: true` and an
`engineering_context` member is `400 InvalidRequest`. A re-run never unlinks the retained
`engineering-context-summary.json`; the summary it writes over the same context and package is
byte-equal to the earlier one.

## 3. What the re-run runs

`start_review(..., send_when_checked=False, earlier=<the earlier record>)`, as an unticked review
(`review-flow.md` section 1), with four differences:

- **live detection is carried, not repeated.** `prerun_checks(..., carried_live=LiveOutcome.from_record(
  earlier.live_detection))` makes no `bridge_interference` call, even with SOLIDWORKS attached.
  Where the first run made its live call - the pre-run's first call - the re-run records **one
  carried step** through `registry.record_call` (the funnel the guard's own repeat answer uses:
  no dispatch, no finding): tool `bridge_interference`, the first run's arguments
  (`{"component_ids": [], "configuration": live.configuration, "settings": live.settings}`), the
  payload `{"status": "carried", "note": CARRIED_LIVE_NOTE, "outcome": <live.as_record()>}`, and,
  for a first call that failed, the first run's error - which records the same `failed` row the
  first run's call did. It is recorded at the point the first run recorded its call, so its index
  is `live.step_index` (a test asserts it), every later step and every finding's citation keep the
  first run's numbers, and `tool-results/step-N.json` holds the carried payload where the first
  run's result was. The result's carried `PrerunCall(tool="bridge_interference", arguments=...,
  step_index=<the carried step>, findings=(), error=live.error)` is first in the result, so the
  digest's live line, the `checked` row of a clean detection, the "NOT evaluated" families and the
  re-call guard's answer (`ran_at_step` names the carried step) are the first run's. A first run
  whose live call was never attempted (`not_attempted`) made no step, and the re-run records none.
  A first run that detected live is never reported as "not attached". A failed detection is carried
  as failed and not retried. When the first run could not write its detected rows (`persist_error`),
  the re-run cannot judge them: its family row reads `INTERFERENCE_ROWS_NOT_CARRIED` (unresolved,
  `coverage.prerun.interference_rows`; `words.md` section 3) in place of today's not-written line,
  and the findings of those rows are not raised, so decisions on them are named (section 5). After
  feature 014 merges, the carried step carries `origin_mark: "prerun"` (research R3).
- **the interference rows judged are the package's.** The rows the first run merged into the folder's
  `package.json` are the rows `planned_calls` enumerates; the drawings the first run's reads merged
  are in the package too. Nothing reads SOLIDWORKS (default). **Except when the first run could not
  write them** (`persist_error`): the folder's package then still holds the dump's rows for the
  reviewed configuration, which the first run removed from its in-memory package before its call
  and never judged (`_live_interference`, `prerun.py:1280-1281`). The carried path removes that
  configuration's rows from the in-memory package in the same way, so the re-run judges none of
  them, and its family row is `INTERFERENCE_ROWS_NOT_CARRIED` (*second review, 2026-10-09*). A
  carried *failed* call keeps the rows, as the first run put them back.
- **the drawing-read capability is carried.** `ToolContext.carry_drawing_read(earlier.drawing_read)`
  (new) sets the cached answer **and** `session.drawing_read`, as `drawing_read_mode` does when it
  asks (`tools/context.py:413-419`), so the host is not pinged and the re-run's own record keeps the
  value: a second restart's re-run of that record makes no bridge call either (SC-008; *second
  review, 2026-10-09*). `None` leaves it lazy, as today.
- **the Standards profile is the one in effect** (default; research R6 question 3). The re-run is
  graded with the profile the settings name now - the usual restart is a Settings save, which may
  have changed it - as Send uses the provider in effect (FR-016). Its identity (`{path, sha256}`,
  `records.md` section 1) is recorded on the re-run's `model_status.profile`, and when it differs
  from the earlier record's, the change is named (section 5).

Lever 13 withholds what the carried outcome and the package give it: with SOLIDWORKS attached as at
the first run, the same tools. After Send, the review has the live SOLIDWORKS tools exactly as a
review started now would; only the pre-run's live call is skipped (FR-028). With nothing answered,
the same provider and model and SOLIDWORKS attached as at the first run, the first request is the
live waiting review's, byte for byte (SC-008).

*Landed as* (owner decision 87A item 8, T115, 2026-10-15): the carried step's index is pinned by a
test and also guarded. `prerun._carried_interference` refuses a carried step that would not land at
`live.step_index`, before the step is recorded or the seat is asked.

## 4. What is carried, and how it is matched

`ReviewRun.carry_from(earlier)`, called by the re-run path of `create_session` on the thread pool,
after `start_review` returns and before `_open_waiting` (so before the finalization). It
changes **only the in-memory session** and emits events: it never calls `record_disposition`,
`record_timing_live` or `save_session`, so nothing on disk changes until the re-run's finalization,
whose `write_atomic` of `session.json` is the re-run's one write of it. Because Send is the only
re-run trigger (68A), the carry always runs on the way to a Send: whatever it carries reaches the
model's opening, and the id maps a page would need to re-key its own work are not kept or sent.

1. **answers.** For each answered request of the earlier record, in answer order: the re-run
   request `r` with `asks_same(earlier_request, r)` (`checks/questions.asks_same`: the same
   `question`, `options` and `entity_ids` in order - the rule `part_roles.answered_roles` and
   `drawings._is_confirmed_candidate` already apply, extracted so the three share it). Exactly one
   match: the request is answered with the earlier `answer` and `answered_at`, one `evidence.answered`
   event each, through `_apply_answers(..., read_drawings=False)` - so the part-roles answer is
   regraded by code (013 `part-roles.md` section 9) and a drawing answer reads nothing. A drawing
   question whose drawing the earlier read put in the package is not asked again: its answer is not
   named, and its outcome line is carried (step 3).
2. **decisions.** For each earlier finding with a disposition: the re-run finding with the same
   `findings.finding_subject_key` - the check, the sorted component ids, the drawing places with
   their persistent references, the entity ids among the inputs, and the configuration; the
   replay's key for findings "independent of how the run that made it was numbered", which a re-run
   of the same package is. It tells two `hole.coaxiality` findings on one pair of components apart,
   which `_verdict_key` does not (`docs/review-backlog.md`). Exactly one: the decision is applied
   through `report/dispositions.set_disposition(session, new_id, decision, note, by, at=earlier.at)`
   - the validated step every decision takes, which keeps the time it was first made - and announced
   with the `disposition` event `record_disposition` emits, through the one function both call
   (owner decision 72A); no second writer of a disposition exists. **Many to one** (72A): when two or
   more earlier decided findings match the same re-run finding - a profile change can merge them -
   none of them is carried, and each is named (section 5), so no decision silently replaces
   another and `set_disposition` never meets a finding already decided by the carry. 72A says only
   that the many-to-one decision is named; that none of them is carried is a default taken
   2026-10-09 to fill that rule, which the owner may revise (the alternative: carry the first, by
   the earlier record's order, and name the rest; research R7, 72A).
3. **outcome lines.** `earlier.drawing_outcomes`, verbatim, in order.
4. **timing.** The four human inputs of `earlier.timing` (baseline, supervision, verification, false
   alarms) are carried whole; the running time is the re-run's own (`records.md` section 3).
5. **the record.** `model_status` is the earlier record's, carried: its `state` (`not_sent` or
   `send_failed`), `document` and `failures` (oldest first) stay as they were; `rechecked_from` is
   the earlier record's `session_id`; `checked_at` and `profile` are the re-run's own. So a re-run
   of a failed send (the usual case, since saving a key in Settings restarts the backend) still says
   when the send failed and why (FR-032), and a later successful Send reports every earlier failure,
   those before the restart included (`records.md` section 4).
6. **what an unfinished read lost.** For each earlier **open** drawing-candidate question whose
   drawing is now in the folder's package - so the re-run does not ask it - and whose file no
   `earlier.drawing_outcomes` entry names: a confirmed read merged the drawing and the apply that
   made it did not finish (`review-flow.md` section 4). Nothing is carried; the loss is named
   (section 5).
7. **the profile.** When the profile in effect differs from `earlier.model_status.profile` (another
   path, or the same path with other bytes, or one of the two absent), the change is named (section
   5); decisions whose findings the new profile no longer raises are named by step 2's rule.

Nothing is carried by its number alone (FR-029). The carry ends with `_settle_waiting(applied)`,
the step the waiting apply ends with too (owner decision 71A; `review-flow.md` section 4): the
restated tools' calls replace theirs in `_prerun` (`prerun.restated`), so the rebuilt digest names no
finding a carried part-roles answer withdrew (FR-023, SC-005 on the restart path), and
`_opening_changed` is set when anything was carried, so the opening is rebuilt (`review-flow.md`
section 5) and its wait lines are the earlier answers' and outcome lines. `_open_waiting` then runs
`close_waiting()`, which builds the Send cache and finalizes (`review-flow.md` section 1).

*Landed as* (T096-T097 and owner decisions 87A to 90A, research R8; T115, 2026-10-15):
- **Where the carry runs** (87A item 5). The server does not call `carry_from` as a separate step
  on the thread pool between `start_review` and `_open_waiting`, and there is no `_carry`.
  `_open_waiting(chat, run, earlier)` calls `run.carry_from(earlier)` inside its thread function,
  before `close_waiting()`. A carry that raises therefore takes the one failure path a failed
  finalization takes: the run is closed, and the chat is `failed` and never registered.
- **When the carry settles** (88A). The carry ends with `_settle_waiting(applied)` only when it
  carried answers or drawing outcome lines. A decision or a timing input carried alone leaves the
  opening as it was, as a decision made while a live review waits does. With only a Reject
  carried, every request of Send's first turn is the live waiting review's, and
  `_opening_changed` stays false. Tests pin both.
- **Two answers on one question** (89A, step 1). When two earlier answers each match the same
  re-run question and nothing else, neither is carried. Each is named "the answer to {id}
  (another answer matches the same question)", and the question stays open for after Send. This
  is 72A's rule for decisions.
- **A partial drawing read** (90A (d), steps 1 and 6). An earlier drawing-candidate question can
  be answered with a read that merged a drawing for some of its documents, while a candidate row
  remains for another (the read was refused or failed for the rest). The re-run asks the narrower
  question again, with no new read, and names the answer "the answer to {id} (part of its drawing
  read was refused or failed, so its question is asked again)". The earlier outcome lines are
  carried as they stand. "Some" is counted by candidate row, not by drawing: one drawing file
  beside two documents of one stem, read whole, is not a partial read (`_drawing_read_of`). An
  **open** question whose unfinished read merged some of its drawings is named by step 6's
  lost-outcome item, as one that merged all of them is.
- **The drawing index** (90A (b)). `carry_from` builds one `DrawingIndex` and passes it to both
  the answer match and the lost-outcome search.
- **The profile** (90A (a), step 7). "Another path" means the paths differ as
  `drawings.evidence.file_key` compares Windows paths, ignoring case and separator. The digest
  is compared exactly (`runner._same_profile`).

## 5. What is not carried is named

One unresolved coverage row, check `coverage.recheck`, when anything is not carried, reason
`NOT_CARRIED` (`words.md` section 4) listing each item: an answer whose question is no longer asked
(other than section 4.1's drawing case), a decision whose finding is no longer raised, an answer or
a decision that matches more than one item, a decision another earlier decision shares its finding
with (section 4.2, 72A), a drawing outcome an unfinished read lost (section 4.6), and a changed
Standards profile (section 4.7). No row when everything carried.

*Landed as* (owner decisions 89A and 90A, T115, 2026-10-15): the list has two more items. One is an
answer that another earlier answer shares its one matching question with (neither is carried). The
other is an answer whose drawing read was partial, so its question is asked again (section 4's
*Landed as*). The items' words are `words.md` section 4.

## 6. Failure

A re-run that raises - an unreadable package, a check that cannot be set up, a finalization that
cannot write - answers today's error body (`InvalidPackage` and the rest) and registers no chat: the
finalization and render run before the chat is registered, as for any unticked start
(`review-flow.md` section 1). Section 2 has already left the earlier record in place, and section 4
wrote nothing. The page prints the summary's `rerun_failed_text` and the error's class and message in
a fold, keeps the restored review read-only with Send offered, and offers no Retry: nothing needs
extracting again, and the next Send tries again (FR-041).

## 7. The `POST /sessions` answer of a re-run

`201 {chat_id, review_session_id, not_examined}`, as an unticked start's, and the same for an
adoption (section 2). Nothing else (owner decision 68A): the page's only action on a restored review
is Send, which names no finding or question, so no map from earlier ids to the re-run's is kept on
the run, returned, held by the host or read by the page. The host passes `chat_id` through in
`review.rechecked`, and the page posts `POST /sessions/{chat_id}/send` for it (`pane.md` section 7).

## 8. A restored waiting review (`GET /reviews/{run_id}`)

`_read_review` answers a record whose `model_status.state` is `not_sent` or `send_failed` read-only,
as it answers every record today (owner decision 68A), with two differences: `read_only_reason` is
the words file's `read_only_lead`, a space, and `send.restored_line`, which names the date and time
the checks ran - `checked_at`'s stored wall clock, `YYYY-MM-DD HH:MM`, never converted to the zone of
the machine rendering it (`records.md` section 1) - composed by the backend so the restored line
begins with the first sentence of feature 009's read-only line word for word, from the one key 009's
line is composed from too (owner decision 73A; `words.md` section 1); 009's second sentence
(`read_only_off`) is not in it; and the summary carries the
`send` block `{state: "restored", input_tokens: null, text: send.restored, rerun_failed_text,
failure}` (`pane.md` section 3). Every other record is read-only as today, with today's sentence
(`Words.read_only`, the two keys composed).
The route still writes nothing.

**Implementation sequence, 2026-10-13:** US3's failed-apply restore brings forward only
the restored Send block through `_read_review`'s existing `SendInput` seam. It uses the
persisted model status and provider metadata, reports no input count, and retains the
current generic read-only reason. The composed dated reason, restart/carry/recheck tests
and actions, and T099/T100 remain pending; this prerequisite does not complete US4.

*Landed as* (T099-T100, 2026-10-14): `report/snapshot.restored_snapshot` composes the reason and
the block; `_read_review` answers it. `{when}` is `checked_at.strftime("%Y-%m-%d %H:%M")`.

## 9. Finding a waiting review after SOLIDWORKS reopens

`sessions.list`, before it answers, runs `FindNotSentReview` when the active document is a part or an
assembly and this host holds no review record of it (path ignoring case, configuration exactly):

1. the run root's folder **names** only: those whose name is `<yyyyMMdd-HHmmss>-<DocumentName(path)>`
   with or without a `-N` collision suffix (`RunFolders.DocumentName`, `TimestampOf`), skipping
   `-check`, `-standards` and `-remodel` folders; the newest by the name's timestamp, then by name;
2. that one folder's `session.json`, at most its first 64 KiB, read by `RunFolders.ReadModelStatus`
   with `Utf8JsonReader` to the top-level `model_status` and no further - no package is opened, and
   no other file of any folder (owner decision 80A). The file is opened through the injectable head
   opener, whose default is a `FileStream` with `FileShare.ReadWrite | FileShare.Delete`, so the
   backend's `os.replace` of that file, which `write_atomic` makes, never fails while the host reads
   it; the buffer is filled by `PackageIndex.FillHead`, the bounded fill loop `PackageIndex.HeadOf`
   now calls too (data-model section 9);
3. offered only when `model_status.state` is `not_sent` or `send_failed` **and** its `document`
   names this document's full path and configuration. A newest same-name folder that is anything
   else (a review sent at once, a check run that failed with no `session.json`, another document of
   the same file name) offers nothing, so an older waiting review behind a newer review of the same
   document is never offered (default).

An offered review is tracked as a kept review: chat id its `session_id`, time its `checked_at`,
`ModelStatus` its state; the `sessions` item carries `model_status`, the one source of its chip's
mark (owner decision 73A). Its chat id is unknown to the backend, so choosing it restores it from its
folder (section 8). The search runs on the host's page-message thread, never the SOLIDWORKS UI
thread, and enumerates names before it opens anything. Its access pattern is pinned by structure, not
by the machine's speed (80A): on a run root of 500 folders of the same document, each with a
`session.json`, it opens exactly one file, the newest folder's, and a stream that throws past 65,536
bytes shows it never reads beyond the cap. The 2 s bound on such a root stays a plain `[Fact]` on the
development machine (FR-030, default bound). Nothing here throws: an unreadable root or file offers
nothing.

*Landed as* (T105-T106, T115, 2026-10-15):
- **The head read.** The search reads the one head through the reader `ReadModelStatus` shares
  (`RunFolders.ReadSessionHead`, private). It takes the top-level `session_id` as well as
  `model_status`, within the same 65,536 bytes, and stops at `model_status`.
  `ReadModelStatus(runDirectory, openHead = null)` reads `model_status` alone.
- **What offers nothing.** A head with no `session_id`, a `document` that is not an object, or a
  `checked_at` that does not parse offers nothing.
- **The match.** The document is matched by `PageDocument.IsSameDocument` (section 1's
  *Landed as*). The found record's document is the one stored in `model_status.document`.
- **When the search runs.** The host runs it only for an active part or assembly with no tracked
  review that `IsSameDocument` matches. It adds the found record through `TrackSession`, before
  the marks are refreshed.
- **The cross-language check.** `RunFoldersNotSentTests` reads T102's backend-written
  `review-not-sent-session.json` through both readers.

**The kept records' marks** (73A). `sessions.list` also refreshes every record this host tracks
whose `ModelStatus` is set - an unticked start's, a re-run's, a found review's - with the same
`ReadModelStatus`, one bounded read each, and clears the mark of a record whose file now says
`sent`; a read that finds nothing (no `session.json`, an unreadable file, or no `model_status` within
64 KiB) keeps the record's `ModelStatus`, so only a head that says `sent` clears a mark. A ticked
review's record is never read. So every chip's mark is the host's record, exact
after a page reload.

The page asks `sessions.list` again on `document.changed`, after following with the list it holds
(009 `sessions.md` section 6 unchanged for every review it already has), and follows again with the
answer by the same rule, so a found review of the active document is shown when none of its reviews
is on screen (`pane.md` section 8; *tasks review, 2026-10-09*). Its Send then sends
`review.recheck` with the found review's chat id, which the host accepts as any record it tracks
(section 1).

## 10. A restart with a waiting review on screen

After an `init` that names a different backend (port or token), the page re-shows the review on
screen from its folder at once when it was a live waiting review (FR-042): read-only, the restored
line, the sentence without a number, and Send offered, which re-runs it (68A). A review that was not waiting keeps
feature 009's rule. A Settings save made while a review waits is not refused (FR-027); the Settings
section said beforehand what it would do (`pane.md` section 9).

*Landed as* (T108, T115, 2026-10-15): the page tells another backend by the token alone. An `init`
whose `token` differs from the one the page holds is a restart; the port is not compared. Every
backend start makes a new token.

## 11. Tests

`test_recheck.py` (research R4.1) and, on the add-in side, `ReviewHostTests.cs` (`review.recheck`),
`RunFoldersNotSentTests.cs`, `RunFoldersModelStatusTests.cs`, `BackendClientSessionBodyTests.cs` and
`ReviewPageRecheckTests.cs` (research R4.2). Every case that stands for a restart starts from
`tests/support/restart.py`'s `restarted_app(run_root, settings)`, a backend started afresh over the
same run root with no live chat, and every cut-off is the folder `disk_at(folder, hook)` copied at
the point a kill would cut, with nothing raised (owner decision 76A); a raise inside the same app
runs code a kill skips (`write_atomic`'s clean-up, `_play`'s render) and holds the earlier chat. The
failed and refused re-runs (raised, FR-041's "a re-run that fails"), and a re-run cut off at each of
three points (after the rotation; after `start_review` and the carry, before the finalization; inside
`write_atomic` once its temporary is written and before `os.replace`), each end with `session.json`
byte-equal to the earlier record, `GET /reviews` of the folder answering it read-only with the
restored Send block (pinned in `test_chat_review_routes.py`, with the copies a crash during a Send or
an apply leaves), the leftover temporary passed over, the provider factory never called, and a
second re-run succeeding at the next index. Two failed re-runs followed by one that succeeds leave
every index a session with its own stream or a failed attempt's stream alone. An adoption after a
discarded answer returns the same chat and runs nothing (the same app, which is what an adoption
meets). The carried step, the carried model status and timing, the `finding_subject_key` match and
two earlier decisions that meet one finding (72A) each have their own case; so do (*second review,
2026-10-09*) a first run with `persist_error` whose stale rows the re-run must not judge, a carried
`drawing_read` on the re-run's record with no bridge call on a second re-run, a changed profile
(another file, the same file edited, a profile added where the earlier record had none, and one
removed: owner decision 78A) and an unchanged one, and an open drawing question whose drawing an
unfinished read merged. A carried part-roles answer, then Send: the opening names no finding the
answer withdrew (71A). After a re-run, the size sentence's number, `session.sent`'s and
`model_status`'s estimates and the count of the request prefix the provider received are one number
(78A). `test_send_gate_perf.py` (opt-in) times the re-run (70A). `ReviewPageRecheckTests` reloads the
page while a re-run is held and sees the review only once it ends. Section 9 is pinned end to end
(*tasks review, 2026-10-09*): `ReviewHostTests` re-runs a found review by its `session_id`, and
`ReviewPageRecheckTests` finds one after a `document.changed`, shows it restored, and sends it
through `review.recheck`. `RunFoldersNotSentTests` pins the one file opened (80A) and a newest
folder of another document name whose record names this document, never offered (78A).
