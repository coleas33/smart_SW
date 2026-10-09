# Contract: A Waiting Review Survives a Restart

Normative for the re-run of a not-sent review's checks after its backend restarted, and for finding
such a review again after SOLIDWORKS reopens (FR-028 to FR-031, FR-041, FR-042, SC-008). Amends 002
`chat-api.md` (`POST /sessions` and `GET /reviews`) and `pane-host-messages.md`; 008 FR-008, FR-009,
FR-030 and `checks-first.md` sections 2 (row 1), 3 and 7; 009 FR-021 and `contracts/sessions.md`
sections 4 to 6.

A **waiting review** is a review whose record says `not_sent` or `send_failed` (`records.md`
section 1). It is **live** while this backend holds its chat in `awaiting_send`, and **restored**
when it is shown from its run folder. A restored waiting review's questions, decisions and Send stay
usable (the spec's question 4 default); the first of them used re-runs the checks first.

## 1. The trigger

| From | Message | Answer |
|---|---|---|
| page | `review.recheck {chat_id}` | `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document, carried, review_session_id}`, or `error` |

The host, in this order (a refusal changes nothing):

| Order | Check | Refusal |
|---|---|---|
| 1 | `chat_id` names a review record of this host | `InvalidRequest` (none given), `UnknownChat` |
| 2 | the active document is not a drawing | `DrawingActive`, with the drawing sentence, as `review.start` |
| 3 | the active document is the review's own (path ignoring case, configuration exactly; feature 009's binding) | `ReviewNotActive` |
| 4 | the backend is running | `BackendUnavailable` |

Then it posts `status {stage: "checking", message: "Checking the saved evidence again..."}`, calls
`POST /sessions` with the record's own run folder, the settings in effect, the engineer, the
Standards profile, the live bridge as for any review, `send_when_checked: false` and `recheck: true` -
**no run folder is created and nothing is dumped** - then replaces its record (the same folder and
document, the new chat id, the time now), posts `status {stage: "ready", message: "Checked the saved
evidence again; nothing was sent to the model."}` and answers `review.rechecked`. A backend refusal
is re-thrown with the backend's own class (`Receive` maps it), as `review.start` does.

**The call's timeout.** A re-run runs the checks inside `POST /sessions`, so its call is made with
the long timeout, 10 minutes (default; `BackendClient.TimeoutFor`), not the 30 s other backend calls
keep (`BackendClient.cs:39`). One rule covers every such call: `TimeoutFor` returns the long timeout
whenever `SendWhenChecked` is false - a re-run and an unticked start (`review-flow.md` section 1) -
and 30 s for a ticked start and every other call (*second review, 2026-10-09*). If the host gives up
anyway, the backend may still finish the re-run and hold its chat waiting; the next
`review.recheck` adopts that chat (section 2), so the review is never left refused until a restart.

The page sends `review.recheck` only for a restored waiting review, and only as the first step of
an answer, a decision or Send (`pane.md` section 7). While it is in flight, the host's pump is busy
with it, so a Settings save the page could still send would be handled after it; the page refuses
Save itself for that time (FR-041).

## 2. The claim and the rotation

`POST /sessions` with `recheck: true`:

1. `_claim_run_dir(run_dir, retry_of=None, recheck=True)`:
   - a live chat on the folder that is `awaiting_send` is **adopted**: nothing runs, nothing is
     rotated or written, and the call answers `201` with that chat's `chat_id`,
     `review_session_id`, `not_examined` and the `carried` maps stored on its run (`ReviewRun.carried`;
     empty maps for a chat that is not a re-run). This is what a host that timed out on a re-run the
     backend finished meets on its next try;
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
   reads true. `GET /reviews` reads only the canonical `session.json`, never an index.

Until the re-run's finalization replaces it (atomically, `records.md` section 8), the canonical
`session.json` is still the earlier record. So a re-run that fails, is refused after the claim, or is
cut off by a crash, a shutdown or SOLIDWORKS closing leaves `session.json` the earlier record -
restorable through `GET /reviews`, offered after a reopen (section 9), with its answers and decisions
intact - and the failed attempt's stream and results beside it in the folder (FR-041). After a
failed or killed re-run the folder holds: the canonical `session.json` and `attention.json` (the
earlier record, whole); their copies and the earlier record's own stream at index N; and, as the
canonical `events.jsonl` and `tool-results/`, the failed attempt's partial stream and results, or
nothing when it was cut off before its first event. The next re-run moves those to their own index
(the second case above). Nothing is sent, and nothing needs recovering.

## 3. What the re-run runs

`start_review(..., send_when_checked=False, earlier=<the earlier record>)`, as an unticked review
(`review-flow.md` section 1), with three differences:

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

## 4. What is carried, and how it is matched

`ReviewRun.carry_from(earlier)`, after `start_review` returns and before the finalization. It
changes **only the in-memory session** and emits events: it never calls `record_disposition`,
`record_timing_live` or `save_session`, so nothing on disk changes until the re-run's finalization,
whose `write_atomic` of `session.json` is the re-run's one write of it.

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
   which `_verdict_key` does not (`docs/review-backlog.md`). Exactly one: the disposition is copied
   whole (decision, note, by, at) onto the in-memory finding and announced with one `disposition`
   event.
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

Nothing is carried by its number alone (FR-029). The re-run's opening is rebuilt when anything was
carried (`review-flow.md` section 5), so its wait lines are the earlier answers' and outcome lines.
The carry ends by building the Send cache, before the finalization (`review-flow.md` section 5).

## 5. What is not carried is named

One unresolved coverage row, check `coverage.recheck`, when anything is not carried, reason
`NOT_CARRIED` (`words.md` section 4) listing each item: an answer whose question is no longer asked
(other than section 4.1's drawing case), a decision whose finding is no longer raised, an answer or
a decision that matches more than one item, a drawing outcome an unfinished read lost (section 4.6),
and a changed Standards profile (section 4.7). No row when everything carried.

## 6. Failure

A re-run that raises - an unreadable package, a check that cannot be set up, a finalization that
cannot write - answers today's error body (`InvalidPackage` and the rest) and registers no chat: the
finalization and render run before the chat is registered, as for any unticked start
(`review-flow.md` section 1). Section 2 has already left the earlier record in place, and section 4
wrote nothing. The page prints the summary's `rerun_failed_text` and the error's class and message in
a fold, keeps the restored review's controls usable, and offers no Retry: nothing needs extracting
again, and the next answer, decision or Send tries again (FR-041).

## 7. The `POST /sessions` answer of a re-run

`201 {chat_id, review_session_id, not_examined, carried}`, where `carried` is `{requests: {old id:
new id}, findings: {old id: new id}}` for every earlier request and finding that matched exactly one
re-run item, answered and decided or not. The run keeps it (`ReviewRun.carried`), and an adoption
answers it again (section 2). `ChatSessionHandle.Carried` holds it, and the host passes it and
`review_session_id` through in `review.rechecked`.

The page re-keys its drafts and the action it is about to take by `carried`, unless
`review_session_id` equals the `session_id` of the `send` block it shows: then it already shows that
record (it reloaded the folder after a re-run the host had given up on, and adopted it), and nothing
is re-keyed. An id with no entry is not carried (section 5).

## 8. A restored waiting review (`GET /reviews/{run_id}`)

`_read_review` answers a record whose `model_status.state` is `not_sent` or `send_failed` with
`read_only: false`, `read_only_reason: null`, and the summary's `send` block `{state: "restored",
session_id, input_tokens: null, text: send.restored, restored_text, rerun_failed_text, failure}`
(`pane.md` section 3), `session_id` being the record's own; `restored_text` names the date and time
the checks ran - `checked_at`'s stored wall clock, `YYYY-MM-DD HH:MM`, never converted to the zone of
the machine rendering it (`records.md` section 1). Every other record is read-only as today. The route
still writes nothing.

## 9. Finding a waiting review after SOLIDWORKS reopens

`sessions.list`, before it answers, runs `FindNotSentReview` when the active document is a part or an
assembly and this host holds no review record of it (path ignoring case, configuration exactly):

1. the run root's folder **names** only: those whose name is `<yyyyMMdd-HHmmss>-<DocumentName(path)>`
   with or without a `-N` collision suffix (`RunFolders.DocumentName`, `TimestampOf`), skipping
   `-check`, `-standards` and `-remodel` folders; the newest by the name's timestamp, then by name;
2. that one folder's `session.json`, at most its first 64 KiB, read with `Utf8JsonReader` to the
   top-level `model_status` and no further - no package is opened;
3. offered only when `model_status.state` is `not_sent` or `send_failed` **and** its `document`
   names this document's full path and configuration. A newest same-name folder that is anything
   else (a review sent at once, a check run that failed with no `session.json`, another document of
   the same file name) offers nothing, so an older waiting review behind a newer review of the same
   document is never offered (default).

An offered review is tracked as a kept review: chat id its `session_id`, time its `checked_at`,
`ModelStatus` its state; the `sessions` item carries `model_status`. Its chat id is unknown to the
backend, so choosing it restores it from its folder (section 8). The search runs on the host's
page-message thread, never the SOLIDWORKS UI thread, enumerates names before it opens anything, and
on a run root of 500 fictional folders finishes within 2 s on the development machine (FR-030,
default bound). Nothing here throws: an unreadable root or file offers nothing.

The page asks `sessions.list` again on `document.changed`, after following with the list it holds
(009 `sessions.md` section 6 unchanged for every review it already has), and follows again with the
answer by the same rule, so a found review of the active document is shown when none of its reviews
is on screen (`pane.md` section 8; *tasks review, 2026-10-09*). Its first answer, decision or Send
then sends `review.recheck` with the found review's chat id, which the host accepts as any record it
tracks (section 1).

## 10. A restart with a waiting review on screen

After an `init` that names a different backend (port or token), the page re-shows the review on
screen from its folder at once when it was a live waiting review (FR-042): the restored line, the
sentence without a number, and its next action re-runs it. A review that was not waiting keeps
feature 009's rule. A Settings save made while a review waits is not refused (FR-027); the Settings
section said beforehand what it would do (`pane.md` section 9).

## 11. Tests

`test_recheck.py` (research R4.1) and, on the add-in side, `ReviewHostTests.cs` (`review.recheck`),
`RunFoldersNotSentTests.cs`, `BackendClientSessionBodyTests.cs` and `ReviewPageRecheckTests.cs`
(research R4.2). The failed and refused re-runs, and a re-run cut off at each of three points (after
the rotation; after `start_review` and the carry, before the finalization; inside the finalization's
write), each end with `session.json` byte-equal to the earlier record, `GET /reviews` of the folder
answering it not read-only with Send offered, the provider factory never called, and a second re-run
succeeding at the next index. Two failed re-runs followed by one that succeeds leave every index a
session with its own stream or a failed attempt's stream alone. An adoption after a discarded answer
returns the same chat and `carried` and runs nothing. The carried step, the carried model status and
timing, and the `finding_subject_key` match each have their own case; so do (*second review,
2026-10-09*) a first run with `persist_error` whose stale rows the re-run must not judge, a carried
`drawing_read` on the re-run's record with no bridge call on a second re-run, a changed profile
(another file, and the same file edited) and an unchanged one, and an open drawing question whose
drawing an unfinished read merged. `ReviewPageRecheckTests` reloads the page while a re-run is held
and sees the review only once it ends, waiting. Section 9 is pinned end to end (*tasks review,
2026-10-09*): `ReviewHostTests` re-runs a found review by its `session_id`, and
`ReviewPageRecheckTests` finds one after a `document.changed`, shows it restored, and sends it
through `review.recheck`.
