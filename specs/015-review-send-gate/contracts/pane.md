# Contract: The Pane - the Box, Send, and a Waiting Review

Normative for the Review tab and its host (FR-001 to FR-005, FR-012, FR-018 to FR-020, FR-025 to
FR-027, FR-030 to FR-034, FR-042, SC-007). Amends 002 `contracts/pane-host-messages.md`,
`contracts/settings.schema.json` and `data-model.md` section 4; 009 `contracts/views.md` sections 2
and 3, `contracts/questions.md` sections 4 and 5, `contracts/sessions.md` sections 5 and 6, and
`contracts/review-summary.md` section 1. Every rule of the pane design system holds: `tokens.css`
linked first, no literal colour, `script-src 'self'` and `style-src 'self'` (no inline handler or
style), every string set with `textContent` or `createTextNode`, and no page-side ranking. Amended on
2026-10-09 by the owner's plan review (research R7): decisions 68A, 69A, 72A, 73A and 77A.

## 1. The box

**Markup** (`index.html`, in `#session`, directly after the buttons' `.row`):

```html
<label class="check send-when-checked"><input type="checkbox" id="send-when-checked"> Send to the model when the checks finish</label>
<p id="send-when-checked-note" class="note bad" role="status" hidden></p>
```

The label is the owner's (59A). It sits outside both views, so it shows in Results and in
Transcript. It is never disabled - not while a review runs, waits, is applied to or is checked again
(FR-002, FR-003). It is a line in `#session` in every state, the ticked default included, so it takes
height from `#results` in every review: about 21 px of the 226 px measured (section 11).

**Behaviour** (`app.js`): `init`, `settings` and `settings.saved` set it from
`settings.send_when_checked`. A change posts `send_when_checked.save {send_when_checked}` at once; the
page keeps showing the new value. On `send_when_checked.saved` the stored value is the shown one; on
`error` the box is put back to the stored value and the note prints `labels.errors[class]` (one line;
the class and message in a fold, as 009 `plain-words.md` section 5 prints a refusal), cleared at the
next change. The review that is running or waiting keeps the value it started with.

**Host** (`ReviewHost`): `send_when_checked.save` reads a JSON boolean (`PagePayload.Flag`, new; a
missing or non-boolean value is `InvalidRequest`), clones the settings, sets `SendsWhenChecked`, and
hands the clone to `PersistSettings(next)`; **no restart, and no turn check**. The reply is
`send_when_checked.saved {send_when_checked}`.

**One persist step** (owner decision 73A). `PersistSettings(next)` is the one write of the settings
file, which `settings.save` calls too: it saves the file (`UserSettings.Save`, atomic), replaces
`_settings` and clears `_settingsError`, so a box click on a file with a load problem leaves no stale
problem on screen, exactly as a Settings save does. A failed write is `SettingNotSaved` (redacted
message) from either handler - `settings.save` answered `HostError` through `Receive`'s catch-all
before (`ReviewHost.cs:596-599`) - and the stored settings stand. `settings.save` restarts the backend
after it, as today; the box's save does not.

**The setting** (`Settings/UserSettings.cs`; data-model section 1). The file's token is held raw,
`[JsonPropertyName("send_when_checked")] JsonElement? SendWhenCheckedValue`, because a JSON converter
cannot reach the `problems` list `Normalize(mode, problems)` fills after deserialization
(`UserSettings.cs:253-255`, `:400`). `[JsonIgnore] bool SendsWhenChecked` reads it (`false` exactly for
a held JSON `false`, else `true`) and its setter stores a boolean: two members for the one setting
(owner decision 73A). `Normalize` adds the one load problem ("send_when_checked '{token}' is not true
or false; ticked is in use.") for a held token that is not a boolean, and clears it, as it replaces
every other bad field, so every other field loads as today and the next save drops the bad token.
Omitted from the file while no token is held, so a file written before this feature saves to its own
bytes. 002 `settings.schema.json` gains, not in `required`:

```json
"send_when_checked": { "type": "boolean", "description": "Feature 015: whether pressing Review sends the review to the model when the code checks finish (true, and absent) or waits for Send to model (false). A review-flow setting, saved from the Review tab without restarting the backend." }
```

`ReviewHost.View` gains `send_when_checked: SendsWhenChecked` (always stated).

## 2. Starting a review

`review.start` is unchanged. The host reads `SendsWhenChecked` when it handles it and passes it as
`CreateReviewSession(..., ReviewMode.Wait)` (or `ReviewMode.Send` when ticked; data-model section 9,
owner decision 71A); `review.started` gains `send_when_checked`. With it `false`, the host sets the
record's `ModelStatus` to `not_sent` (owner decision 73A), its ready status reads "Checked {n}
components by code; nothing was sent to the model.", and the page does **not** mark a turn running:
it opens the stream (whose events end at `session.ended`, and whose `loadAttention` then draws the
Send block) and shows the waiting status at once, from `review.started` until the summary arrives. The "Before this review" panel and its sentence ("No review tokens have been used.")
are unchanged; the box's value is read at "Review available evidence" (FR-003).

*Amended 2026-10-15 (feature 016 lands on this feature, owner decision 99A):* 016's
`context.review` starts through the same `CreateReviewSession`, with the box read as above and
its saved-context attachment passed by name, so its reply, record and status are the ones this
section gives. The page's context panel is refused while `startPending`, `turnRunning`,
`awaitingSend`, `sendPending` or `rechecking` holds (016 `contracts/pane-context.md`).

## 3. The Send block

**Markup**: `<section id="send" class="send-panel" aria-label="Send to model" hidden></section>` in
Results, **directly after `#summary` and before `#questions`** (*second review, 2026-10-09*: measured,
section 11; the engineer reads what the code found, then decides to send). Built whole by
`render.sendBlock(send, extras)`:

| Part | Content | Shown |
|---|---|---|
| the button | "Send to model" (page word, 59A), `button.primary`, `data-action="send"` | always in the block |
| the size sentence | `send.text`, small, tier 3 ink | always |
| one failure or refusal line | a current Send refusal's `labels.errors[class]`; else `send.failure` (a recorded failed first request, `send.failed`, or a Send that failed before any request, `send.not_started`, the provider's build included: owner decision 69A); else a failed re-run's `send.rerun_failed_text` with the error's class and message in a fold | when there is one |

**Implementation/contract clarification, 2026-10-12:** a current retry refusal takes display
priority over an earlier recorded failure, so the engineer sees why this press was refused.
The next press clears that current error; the stored failure remains its fallback.

The block is shown exactly while `state.summary.send` is present and no Send of this review is in
flight (`state.sending`). It is the second exception to 009 `views.md` section 2's "Results shows no
token count", beside the questions panel's resume sentence (FR-034); the page prints the sentence and
computes nothing.

**The button is enabled** when a chat is shown, it is of the active document (not `resultsStale`, and
no drawing is active), no start, re-run or turn is in flight, and the review is not a read-only one
(FR-018) - except a restored waiting review, which is read-only and whose block is in state
`restored`: its Send is the one control it offers (owner decision 68A). Leaving the document disables it with the other review actions; returning offers it again.

**Pressing it**: for a live waiting review, `POST /sessions/{id}/send`; on `202` the block hides,
`state.sending` is set, the turn is marked running and the stream is reopened; on a refusal (every
refusal is a `404` or `409`: the provider's build is no longer one, 69A) the block stays with the
refusal line. For a restored waiting review, section 7 first. The first `usage` event clears
`state.sending` and adds the chat to `state.sentSeen`, so its chip drops the mark at once (section 8);
`session.ended` clears `state.sending` too.

**An `error` event while `state.sending` is set ends the Send on the page** (*second review,
2026-10-09*): it is **not** drawn as an error card; `state.sending` is cleared and the turn unmarked;
its Transcript line is written; and the page re-reads the attention, whose summary's `send` block
already carries the failure line, which redraws the block with Send offered again. One rule covers
both ways a Send fails before the model answers: a first request that failed (an `error`, then
`turn.ended {error}` and `session.ended`, which re-read it again) and a Send that failed before any
request (one `error` and nothing after it). The backend sets the run's waiting state and its failure
before it writes the `error` (`review-flow.md` section 6), so the re-read never meets a summary
without its `send` block. A Send pressed while the backend still finalizes the failed attempt is
`409 TurnRunning`, printed as any refusal, and works once pressed again. A Send whose turn later
fails after a round is today's error card.

**After a reload** (owner decision 77A). `state.sending` lives in page memory, and a reload of a running
chat restores from the snapshot and reads every later event as live (`app.js:1412-1434`). The snapshot
therefore carries `send_in_flight: true` while the run's `_send_in_flight` is set (from the route's
accepting the Send to its first round, or to its return to waiting; data-model sections 3 and 6),
and omits the key otherwise; the page's restore sets `state.sending` from it. So the rule above holds
after a reload: an `error` that follows - a first request that failed, or a Send that failed before
any request and wrote one `error` and nothing after it - draws no error card and offers no Retry,
and the Send block comes back with its failure line and Send.

## 4. The status line

009 `views.md` section 3, amended. `#results-state`, page words, first match:

| State | Words |
|---|---|
| no chat | nothing (hidden) |
| a reconnect is pending | "Reconnecting to the review." |
| a re-run is in flight (`state.rechecking`) | "Checking the saved evidence again." |
| the summary has a `send` block and no Send is in flight | "Checked by code. Not sent to the model." |
| a turn is running | "The review is running." |
| open questions in the summary | "Waiting for your answers." |
| otherwise | "The review has finished." |

A waiting review shows its state even with open questions (FR-033). While answers are applied to a
waiting review the line stays "Checked by code. Not sent to the model.", and a page reloaded then, or a
chip chosen then, shows the same (the snapshot's summary has the `send` block), never "running".

## 5. The questions panel

009 `questions.md` sections 4 and 5, amended: while the summary has a `send` block, the panel's button
reads "Apply answers" (page word) and the sentence beside it is the summary's `resume_text`, which the
backend sets to `send.apply_answers` for a waiting run. The panel is locked while a re-run or a Send is
in flight, as while a turn runs. Applying posts the same `POST /sessions/{id}/evidence`; the page marks
the turn running for the apply (so the panel locks) but draws the status line, Stop and the Send block
by section 4's rule. A restored waiting review's panel is read-only, as on any read-only restore: its
questions wait until after Send (owner decision 68A).

**An apply that fails** (`review-flow.md` section 4): the stream carries one `error` event while the
apply is in flight, and no `turn.ended` or `session.ended`. The rule is keyed on the summary's `send`
block, not on page memory: an `error` on a running chat whose summary has a `send` block and with no
Send in flight (`state.sending` unset) is an apply's failure, so the rule holds after a reload during
the apply too (owner decision 77A). The page draws **no error card** for it: it ends the apply (the
panel unlocks), forgets the live chat for this review, and restores the review from its folder
(`GET /reviews/{run_id}`, section 7's restored state, as FR-042 does: read-only, with Send offered),
with the error's label in the Send block's failure line and its class and message in a fold, printed
as any refusal is (009 `plain-words.md` section 5). The page shows whichever record the folder holds
(*second review, 2026-10-09*): when the failure came before the finalization wrote `session.json`,
the answers that were being applied show open again; when it came after (the attention record's
write), they show answered, and the re-run carries them. Either way the review's Send re-runs it
(68A). When a confirmed read had merged its drawing before the failure, that
drawing's question is not asked again and the re-run names the outcome line it lost (`recheck.md`
section 5).

**Implementation sequence, 2026-10-13:** US3 brings forward only the disk Send-state
forwarding needed for this restore (`review-flow.md` section 4). A `not_sent` or `send_failed`
disk record supplies the existing restored Send block with an unknown count and its persisted
failure history, while retaining today's generic read-only reason. The page may show its
local apply-error label and fold with that block; the restored Send action stays unavailable
until US4's recheck path exists. This does not complete T099/T100 or the composed dated line.

*Landed as* (T100, T108, T115, 2026-10-15): the sequence above is complete and superseded.
- A failed apply's restore is section 7's restored review. Its reason is the composed dated line
  that T100's backend gives, and its Send is enabled and posts `review.recheck`.
- `ReviewPageSendGateTests` (`AssertFailedApplyRestored`) moved deliberately: the restore offers
  Send.
- Its fixture's `restored` snapshots still carry 009's whole sentence as `read_only_reason`. That
  sentence is what the route answered when the capture was made (section 13's *Landed as*). The
  page prints whatever reason the snapshot gives, so the case still holds.

## 6. The follow-up box and Stop

While the summary has a `send` block, or no `usage` of this review has arrived after its Send, the
follow-up box and its Send button are disabled and the box's placeholder reads "Not sent to the model
yet: press Send to model first" (page words; FR-019). Stop is disabled while the review waits, while
answers are applied to a waiting review, and while a re-run is in flight (FR-025, FR-041); once a Send
is in flight, Stop is today's.

## 7. A restored waiting review, and its re-run

Owner decision 68A: a snapshot from `GET /reviews` whose summary has `send` with state `restored` is
read-only, as feature 009 shows every restored review: the line under the status line (`#read-only`)
prints the snapshot's `read_only_reason`, which for this record is the first sentence of feature
009's read-only line (`read_only_lead`) followed by `send.restored_line` (composed by the backend,
`recheck.md` section 8; 73A); the questions
panel, the decision buttons and the follow-up box are off, as on any read-only restore. The one
difference is the Send block, whose Send is enabled (section 3). Send is the only re-run trigger.

Its Send:

1. `state.rechecking = true`; the status line, Save, Review, the chips and Send are refused
   (disabled; a press does nothing) and Stop is not offered;
2. `review.recheck {chat_id}`;
3. on `review.rechecked`: the pins of `previous_chat_id` move to the new `chat_id`, the review is
   shown from the new chat's snapshot (a live waiting review), and the page posts
   `POST /sessions/{chat_id}/send` for it, as section 3 does. Nothing is re-keyed: the page held no
   draft and no pending action for a read-only review. If that Send is refused (`NoCredential`, say),
   the review stays the live waiting review the re-run made - its questions and decisions usable, its
   size sentence counted - with the refusal line beside Send;
4. on `error`: `state.rechecking = false`; for `UnknownReview`, feature 009's "This review can no
   longer be restored." on the chip and no review shown; for anything else, the Send block's failure
   line prints `send.rerun_failed_text` with the class and message in a fold, the restored review
   stays read-only with Send offered, and no Retry is offered (FR-041).

**A restart with a waiting review on screen** (FR-042): when `init` names a backend other than the one
the page held and the review on screen was a live waiting one, the page calls `showReview` for it at
once; its snapshot is gone (`UnknownChat`), so it is restored from its folder as above: read-only,
with Send offered. A draft answer typed before the restart is dropped with the live chat (68A).

## 8. The chips

*Landed as* (T108, 2026-10-15): the page has no separate "found" flag; it dates a chip whose
`sessions` item carries `model_status`, from the stored wall clock of `started_at`. Only a found
review can have another day, so this is the rule below.

009 `sessions.md` section 5, amended: a chip's label gains " · not sent" while its `sessions` item
carries `model_status` and the chat is not in `state.sentSeen`. The mark comes from the host's record
alone (owner decision 73A; data-model section 9): the host sets it at an unticked start, keeps it
across a re-run, sets it for a found review, and on every `sessions.list` refreshes each marked record
with one bounded head read, so the mark is exact after a page reload, before the chip is chosen, and a
ticked review's chip never carries it. A found review's chip names
the date before the time, "{YYYY-MM-DD} {HH:MM}", when that date is not today on this machine - the
stored wall clock of its `checked_at`, never converted (`records.md` section 1). Every
other chip is today's. Pressing Review or Clear review while a review waits leaves its chip, marked
(FR-026). On `document.changed` the page follows with the list it holds (009 section 6, unchanged) and
then asks `sessions.list` again, which may add a found review (`recheck.md` section 9). When the answer
comes, the page follows again by the same rule, as it does after `init` (`requestSessions(true)`), so
a found review of the active document is shown, restored from its folder, when no review of that
document is on screen (FR-030: "the Review tab then shows that review"). A review of the document
already on screen stays shown (*tasks review, 2026-10-09*; default, research R2.20).

## 9. The Settings section

While the review on screen waits (live or restored), one line under Save (`.note`, page words):
"Saving restarts the backend. The waiting review stays, and its Send checks its saved evidence again
first." (owner decision 68A) While a re-run is in flight, Save is disabled and the line reads
"Checking the saved evidence again; save when it is done." (FR-027, FR-041). The no-key sentence
(`describeKeySource('none')`) becomes "No key is stored. With the box ticked a review fails until one
is entered; with it unticked the code checks run and Send waits for a key."

*Landed as* (T116, owner decision 98A, 2026-10-15): the waiting line is not shown while a Send is
in flight (from its press to its first usage), when a save is refused (FR-027).

## 10. The Transcript

Page words, live and in a transcript replay:

| Event | Line |
|---|---|
| `session.started` with `send_when_checked: false` | "Checked by code only: nothing is sent to the model until Send to model is pressed." |
| `session.ended` while the review waits | "The checks ended at {ended_at}. Nothing was sent to the model." |
| `session.sent` | "Sending to {provider} {model} ({requested} -> {param}={value})", and " - first request {n} input tokens" when its estimate counted one; the effort part shared with `describeStart`. It reads "Sending": `session.sent` is written before the attempt's record, which can still fail (owner decision 72A) |

Every other line is today's, the failed attempt's `error` line and "The turn ended: error." included.

*Landed as* (T116, owner decision 98A item 5, 2026-10-15): "while the review waits" is decided from
the stream, not from the page's state: the line is printed for a `session.ended` of a stream whose
`session.started` was unticked and on which no `session.sent` came before it. A failed attempt's
end, after its `session.sent`, reads "The session ended at {ended_at}.". A restore that joins a
stream part-way seeds the two facts from the snapshot (`chat_state`, the summary's `send`,
`send_in_flight`); a replay reads them from the stream's start.

## 11. The layout budget

**Measured** (research R2.21, *second review, 2026-10-09*): on the committed build, a block of N px
added at the end of `#session` leaves `ReviewPageSummaryAcceptanceTests` green up to 226 px and
pushes the not-reached line below the fold at 228 px, on the finished big assembly at 300 by 600;
`ReviewPageNarrowLayoutTests` stays green at every height tried. Stand-ins for the planned text
showed that a Send block **above** the summary fails its worst case (a restored review after a failed
re-run) by about 40 px, so the block sits **under** the summary (section 3), where it moves nothing
SC-007 reads.

- **The box.** At 260 to 420 px the six session buttons wrap as today (two rows at 300 px) with the
  box on its own line under them in `.check`'s small face: about 21 px (12 px at line height 1.45,
  and its 4 px top margin). The first page task runs the two existing 300 by 600 tests with the real
  box in place and the box ticked, unedited; no margin or padding is trimmed for it.
- **Above the summary** stand only the box and, for a restored review, the restored line under the
  status line: about 91 px of the 226 on the proxy, whose restored line held about 70 px. Under owner
  decisions 68A and 73A the line is the first sentence of feature 009's read-only line and the dated
  Send sentence, a few words shorter than the proxy's (which also named an answer and a decision as
  re-run triggers); `ReviewPageSendLayoutTests` measures the real one on the fixture.
- **The Send block** sits under the summary, in every state.
- **What is checked**: `ReviewPageSendLayoutTests`, on the big-assembly waiting fixture
  (`review-waiting-big-assembly.json`), in each worst case a waiting review shows - `waiting`;
  `failed_send`, with its failure line; `restored`, with the restored line under the status line and
  the restored sentence; and `restored` after a failed re-run, with the `rerun_failed` line: the
  summary's headline, tally and not-reached line inside 300 by 600 (SC-007), and the Send to model
  button inside the viewport too. The figure measured on that fixture is recorded in research R2.21.
- **The end state.** If SC-007 fails there even so - the waiting summary would have to be about
  135 px taller than the finished one - the page work stops and the owner is asked which gives way
  while a review waits: the restored line's length (FR-031's content) or SC-007's not-reached line.
  No page-only fallback is left to try.

## 12. Page-to-host rows

002 `pane-host-messages.md`, amended - two new rows, and four amended:

| type | payload | host action |
|------|---------|-------------|
| `send_when_checked.save` (*new*) | `{send_when_checked: boolean}` | Write the setting with no restart and no turn check; reply `send_when_checked.saved {send_when_checked}`; `error {error_class: "SettingNotSaved"}` when the file cannot be written, the stored value unchanged; `InvalidRequest` for a missing or non-boolean value. *Amended 2026-10-20 (feature 002, owner decision 154A):* `RunRootRefused`, nothing written, when the run root in force is on a network share, reached through a link or written as a device path (002 `pane-host-messages.md`, "The run root rule"). |
| `review.recheck` (*new*) | `{chat_id}` | `recheck.md` section 1: re-run a restored waiting review's checks from its own run folder with no dump, as the first step of its Send, the call's timeout the measured bound (`ChecksOnlyTimeout`, or the one 30 s rule when the measured re-run fits inside 30 s; owner decision 70A); reply `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document}`. Refusals `InvalidRequest`, `UnknownChat`, `DrawingActive`, `ReviewNotActive`, `BackendUnavailable`, and the backend's own classes. *Amended 2026-10-20 (feature 002, owner decision 154A):* `RunRootRefused` before them all ([recheck.md](recheck.md) section 1). |
| `ready` (amended) | `{}` | `init.settings` carries `send_when_checked`. |
| `settings.save` / `settings.get` (amended) | as today | the replies' `settings` carry `send_when_checked`; a save keeps it; a save's write goes through `PersistSettings`, and a failed write is `SettingNotSaved` (owner decision 73A). |
| `review.start` (amended) | as today | the stored `send_when_checked` goes to `POST /sessions`; `review.started` carries `send_when_checked`. |
| `sessions.list` (amended) | `{}` | first looks for a waiting review of the active document (`recheck.md` section 9), and refreshes every record whose `ModelStatus` is set with one bounded head read each; items carry `model_status` for every record that waits for Send - an unticked start's, a re-run's, a found one's (owner decision 73A). |

*Landed as* (T104, T108, T115, 2026-10-15): `review.recheck`'s call keeps the one 30 s rule, the
client's `CallTimeout`. T098's measured re-run, 8.8 s, fits inside 30 s, so `ChecksOnlyTimeout`
and `TimeoutFor` were removed (research R2.17; `recheck.md` section 1's *Landed as*). 002
`pane-host-messages.md` holds the rows as landed.

Host to page: `status` gains the stage `checking`. `ReviewPageContractTests` holds both new rows to the
page's sends (its rules 1 and 2), so each new row lands in the commit where the page first posts it,
never with its host handler alone (tasks T055 and T108).

## 13. Tests

Research R4.2: `UserSettingsTests.cs`, `PageMessageTests.cs`, `ReviewHostTests.cs`,
`ReviewPageSendGateTests.cs`, `ReviewPageRecheckTests.cs`, `ReviewPageSendLayoutTests.cs`,
`ReviewPageDefaultViewScanTests.cs` (the raw tokens `awaiting_send`, `not_sent` and `send_failed`
never visible on the waiting fixtures), and the moved `ReviewPageViewsTests.cs`,
`ErrorLabelsCoverTheHostTests.cs` and `ReviewPageContractTests.cs` (the `review.start` row's reply
substring gains `send_when_checked`); `ReviewPageSummaryAcceptanceTests.cs` and
`ReviewPageNarrowLayoutTests.cs` run unedited with the box in place (section 11). `ReviewPageDriver.cs`,
which plays the host, answers `send_when_checked.save` and `review.recheck` (the latter with a
fixture's `rechecked` body), has an error mode for each, answers `sessions.list` with items that carry
`model_status` (73A), and holds a re-run in flight with
`HoldReviewRecheck` / `ReleaseReviewRecheck` as it holds a start with `HoldReviewStart` /
`ReleaseReviewStart` - except that a held re-run also queues every later message and answers them in
order on release, as the host's one pump does, so a page reloaded during a re-run is answered only
once it ends (FR-033).

Page tests load backend-made fixtures, never a hand-built summary (research R2.25), all three written
by `tests/fixtures/pane/generate_waiting_fixtures.py` with every clock pinned:
`review-waiting.json` (a fictional package whose checks raise the part-roles question and a
drawing-candidate question: `waiting`, `sending` - the live snapshot while a Send is held, carrying
`send_in_flight: true` - and `failed_send`) for `ReviewPageSendGateTests`;
`review-waiting-restored.json` (the same package: `restored`, and `rechecked`, the re-run's
`POST /sessions` answer with the re-run's live snapshot) for `ReviewPageRecheckTests`; and `review-waiting-big-assembly.json` (`waiting`, `failed_send`,
`restored`) for `ReviewPageSendLayoutTests` only.

*Landed as* (T089-T090, T101-T102, T107-T108, T115, 2026-10-15):
- **`rechecked`.** In `review-waiting-restored.json` it is `{answer, snapshot}`. `answer` is the
  re-run's `POST /sessions` body, its three keys exactly. `snapshot` is the new chat's live
  `awaiting_send` snapshot, with the Send block and its counted size.
- **The driver's re-run.** The driver answers `review.recheck` through `RecheckReply`, which the
  test builds from that fixture. It replaces the review's `sessions` item with the new chat id,
  as the host replaces its record. `RecheckError` is its error mode.
- **A fourth generated fixture.** `generate_waiting_fixtures.py` also writes
  `review-not-sent-session.json`, a not-sent `session.json` as `save_session` writes it. The
  host's `RunFoldersNotSentTests` reads it (`recheck.md` section 9).
- **A captured fixture.** `review-waiting-apply-failure.json` (C45, US3) has no committed
  generator. It holds untouched route captures, its clocks pinned before capture, made before
  T100. Its two `restored` snapshots therefore carry 009's whole read-only sentence as
  `read_only_reason`, where today's backend composes `read_only_lead` and the dated
  `send.restored_line`. It is left as captured. Editing a capture by hand would break research
  R2.25 and the fixture's recorded hashes, and regenerating it would need a generator, which is
  code. The page prints the reason it is given, and the cases that read this fixture assert only
  that.
