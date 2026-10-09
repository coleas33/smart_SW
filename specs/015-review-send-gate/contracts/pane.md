# Contract: The Pane - the Box, Send, and a Waiting Review

Normative for the Review tab and its host (FR-001 to FR-005, FR-012, FR-018 to FR-020, FR-025 to
FR-027, FR-030 to FR-034, FR-042, SC-007). Amends 002 `contracts/pane-host-messages.md`,
`contracts/settings.schema.json` and `data-model.md` section 4; 009 `contracts/views.md` sections 2
and 3, `contracts/questions.md` sections 4 and 5, `contracts/sessions.md` sections 5 and 6, and
`contracts/review-summary.md` section 1. Every rule of the pane design system holds: `tokens.css`
linked first, no literal colour, `script-src 'self'` and `style-src 'self'` (no inline handler or
style), every string set with `textContent` or `createTextNode`, and no page-side ranking.

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
missing or non-boolean value is `InvalidRequest`), clones the settings, sets `SendWhenChecked`, saves
the file (`UserSettings.Save`, atomic) and replaces the settings; **no restart, and no turn check**.
A failed write is `SettingNotSaved` (redacted message), and the stored value stands. The reply is
`send_when_checked.saved {send_when_checked}`.

**The setting** (`Settings/UserSettings.cs`; data-model section 1). The file's token is held raw,
`[JsonPropertyName("send_when_checked")] JsonElement? SendWhenCheckedValue`, because a JSON converter
cannot reach the `problems` list `Normalize(mode, problems)` fills after deserialization
(`UserSettings.cs:253-255`, `:400`). `[JsonIgnore] bool? SendWhenChecked` is derived from it (`true` or
`false` for a JSON boolean, else `null`) and its setter stores a boolean. `Normalize` adds the one
load problem ("send_when_checked '{token}' is not true or false; ticked is in use.") for a held token
that is not a boolean, and clears it, as it replaces every other bad field, so every other field loads
as today and the next save drops the bad token. `SendsWhenChecked => SendWhenChecked != false`.
Omitted from the file while no token is held, so a file written before this feature saves to its own
bytes. 002 `settings.schema.json` gains, not in `required`:

```json
"send_when_checked": { "type": "boolean", "description": "Feature 015: whether pressing Review sends the review to the model when the code checks finish (true, and absent) or waits for Send to model (false). A review-flow setting, saved from the Review tab without restarting the backend." }
```

`ReviewHost.View` gains `send_when_checked: SendsWhenChecked` (always stated).

## 2. Starting a review

`review.start` is unchanged. The host reads `SendsWhenChecked` when it handles it and passes it as
`NewSessionRequest.SendWhenChecked`; `review.started` gains `send_when_checked`. With it `false`, the
host's ready status reads "Checked {n} components by code; nothing was sent to the model." and the page
does **not** mark a turn running: it opens the stream (whose events end at `session.ended`, and whose
`loadAttention` then draws the Send block), sets `state.notSent[chat_id]`, and shows the waiting
status at once. The "Before this review" panel and its sentence ("No review tokens have been used.")
are unchanged; the box's value is read at "Review available evidence" (FR-003).

## 3. The Send block

**Markup**: `<section id="send" class="send-panel" aria-label="Send to model" hidden></section>` in
Results, **directly after `#summary` and before `#questions`** (*second review, 2026-10-09*: measured,
section 11; the engineer reads what the code found, then decides to send). Built whole by
`render.sendBlock(send, extras)`:

| Part | Content | Shown |
|---|---|---|
| the button | "Send to model" (page word, 59A), `button.primary`, `data-action="send"` | always in the block |
| the size sentence | `send.text`, small, tier 3 ink | always |
| one failure or refusal line | `send.failure` (a recorded failed first request, `send.failed`, or a Send that failed before any request, `send.not_started`); else a Send refusal's `labels.errors[class]`; else a failed re-run's `send.rerun_failed_text` with the error's class and message in a fold | when there is one |

The block is shown exactly while `state.summary.send` is present and no Send of this review is in
flight (`state.sending`). It is the second exception to 009 `views.md` section 2's "Results shows no
token count", beside the questions panel's resume sentence (FR-034); the page prints the sentence and
computes nothing.

**The button is enabled** when a chat is shown, it is of the active document (not `resultsStale`, and
no drawing is active), no start, re-run or turn is in flight, and the review is not a read-only one
(FR-018). Leaving the document disables it with the other review actions; returning offers it again.

**Pressing it**: for a live waiting review, `POST /sessions/{id}/send`; on `202` the block hides,
`state.sending` is set, the turn is marked running and the stream is reopened; on a refusal the block
stays with the refusal line. For a restored waiting review, section 7 first. The first `usage` event
clears `state.sending` and `state.notSent[chat]`; `session.ended` clears `state.sending` too.

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
by section 4's rule. A restored waiting review's panel is unlocked, and applying goes through section 7
first.

**An apply that fails** (`review-flow.md` section 4): the stream carries one `error` event while the
apply is in flight, and no `turn.ended` or `session.ended`. The page draws **no error card** for it:
it ends the apply (the panel unlocks), forgets the live chat for this review, and restores the review
from its folder (`GET /reviews/{run_id}`, section 7's restored state, as FR-042 does), with the
error's label in the Send block's failure line and its class and message in a fold, printed as any
refusal is (009 `plain-words.md` section 5). The page shows whichever record the folder holds
(*second review, 2026-10-09*): when the failure came before the finalization wrote `session.json`,
the answers that were being applied show open again; when it came after (the attention record's
write), they show answered, and the re-run carries them. Either way the review's next answer,
decision or Send re-runs it. When a confirmed read had merged its drawing before the failure, that
drawing's question is not asked again and the re-run names the outcome line it lost (`recheck.md`
section 5).

## 6. The follow-up box and Stop

While the summary has a `send` block, or no `usage` of this review has arrived after its Send, the
follow-up box and its Send button are disabled and the box's placeholder reads "Not sent to the model
yet: press Send to model first" (page words; FR-019). Stop is disabled while the review waits, while
answers are applied to a waiting review, and while a re-run is in flight (FR-025, FR-041); once a Send
is in flight, Stop is today's.

## 7. A restored waiting review, and its re-run

A snapshot from `GET /reviews` whose summary has `send` with state `restored` is shown with
`read_only` false: the line under the status line (`#read-only`) prints `send.restored_text`; the
questions panel, the decision buttons and Send are enabled; the follow-up box is disabled (section 6);
feature 009's read-only sentence is not shown (FR-031).

Its first answer, decision or Send runs `recheckThen(action)`:

1. `state.rechecking = true`; the status line, Save, Review, the chips, the questions panel, the
   decision buttons and Send are refused (disabled; a press does nothing) and Stop is not offered;
2. `review.recheck {chat_id}`;
3. on `review.rechecked`: the drafts and pins of `previous_chat_id` move to the new `chat_id`, each
   draft and the pending action re-keyed by `carried` (an id with no entry is dropped, and the
   pending decision's card says "This decision no longer applies: its finding is not raised again."),
   unless `review_session_id` equals the shown `send.session_id`, when the page already shows that
   record (an adopted re-run after a reload, `recheck.md` section 7) and re-keys nothing;
   the review is shown from the new chat's snapshot; then the action runs through its live route
   (`/send`, `/evidence`, `/findings/{id}/disposition`);
4. on `error`: `state.rechecking = false`; for `UnknownReview`, feature 009's "This review can no
   longer be restored." on the chip and no review shown; for anything else, the Send block's failure
   line prints `send.rerun_failed_text` with the class and message in a fold, the restored review's
   controls stay usable, and no Retry is offered (FR-041).

**A restart with a waiting review on screen** (FR-042): when `init` names a backend other than the one
the page held and the review on screen was a live waiting one, the page calls `showReview` for it at
once; its snapshot is gone (`UnknownChat`), so it is restored from its folder as above.

## 8. The chips

009 `sessions.md` section 5, amended: a chip's label gains " · not sent" while `state.notSent[chat]` is
set or its item carries `model_status`; a found review's chip (its item carries `model_status`) names
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
"Saving restarts the backend. The waiting review stays, and its next answer, decision or Send checks
its saved evidence again first." While a re-run is in flight, Save is disabled and the line reads
"Checking the saved evidence again; save when it is done." (FR-027, FR-041). The no-key sentence
(`describeKeySource('none')`) becomes "No key is stored. With the box ticked a review fails until one
is entered; with it unticked the code checks run and Send waits for a key."

## 10. The Transcript

Page words, live and in a transcript replay:

| Event | Line |
|---|---|
| `session.started` with `send_when_checked: false` | "Checked by code only: nothing is sent to the model until Send to model is pressed." |
| `session.ended` while the review waits | "The checks ended at {ended_at}. Nothing was sent to the model." |
| `session.sent` | "Sent to {provider} {model} ({requested} -> {param}={value})", and " - first request {n} input tokens" when its estimate counted one; the effort part shared with `describeStart` |

Every other line is today's, the failed attempt's `error` line and "The turn ended: error." included.

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
  status line (at most about 70 px): about 91 px of the 226.
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
| `send_when_checked.save` (*new*) | `{send_when_checked: boolean}` | Write the setting with no restart and no turn check; reply `send_when_checked.saved {send_when_checked}`; `error {error_class: "SettingNotSaved"}` when the file cannot be written, the stored value unchanged; `InvalidRequest` for a missing or non-boolean value. |
| `review.recheck` (*new*) | `{chat_id}` | `recheck.md` section 1: re-run a restored waiting review's checks from its own run folder with no dump, the call's own 10-minute timeout; reply `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document, carried, review_session_id}`. Refusals `InvalidRequest`, `UnknownChat`, `DrawingActive`, `ReviewNotActive`, `BackendUnavailable`, and the backend's own classes. |
| `ready` (amended) | `{}` | `init.settings` carries `send_when_checked`. |
| `settings.save` / `settings.get` (amended) | as today | the replies' `settings` carry `send_when_checked`; a save keeps it. |
| `review.start` (amended) | as today | the stored `send_when_checked` goes to `POST /sessions`; `review.started` carries `send_when_checked`. |
| `sessions.list` (amended) | `{}` | first looks for a waiting review of the active document (`recheck.md` section 9); items carry `model_status` for a review found that way. |

Host to page: `status` gains the stage `checking`. `ReviewPageContractTests` holds both new rows to the
page's sends (its rules 1 and 2), so each new row lands in the commit where the page first posts it,
never with its host handler alone (tasks T051 and T099).

## 13. Tests

Research R4.2: `UserSettingsTests.cs`, `PageMessageTests.cs`, `ReviewHostTests.cs`,
`ReviewPageSendGateTests.cs`, `ReviewPageRecheckTests.cs`, `ReviewPageSendLayoutTests.cs`,
`ReviewPageDefaultViewScanTests.cs` (the raw tokens `awaiting_send`, `not_sent` and `send_failed`
never visible on the waiting fixtures), and the moved `ReviewPageViewsTests.cs`,
`ErrorLabelsCoverTheHostTests.cs` and `ReviewPageContractTests.cs` (the `review.start` row's reply
substring gains `send_when_checked`); `ReviewPageSummaryAcceptanceTests.cs` and
`ReviewPageNarrowLayoutTests.cs` run unedited with the box in place (section 11). `ReviewPageDriver.cs`,
which plays the host, answers `send_when_checked.save` and `review.recheck` (the latter with a
fixture's `rechecked` body), has an error mode for each, and holds a re-run in flight with
`HoldReviewRecheck` / `ReleaseReviewRecheck` as it holds a start with `HoldReviewStart` /
`ReleaseReviewStart` - except that a held re-run also queues every later message and answers them in
order on release, as the host's one pump does, so a page reloaded during a re-run is answered only
once it ends (FR-033).

Page tests load backend-made fixtures, never a hand-built summary (research R2.25), all three written
by `tests/fixtures/pane/generate_waiting_fixtures.py` with every clock pinned:
`review-waiting.json` (a fictional package whose checks raise the part-roles question and a
drawing-candidate question: `waiting`, `failed_send`) for `ReviewPageSendGateTests`;
`review-waiting-restored.json` (the same package: `restored`, `restored_answered` after an answer, a
confirmed read that moved the numbers and a Reject, and `rechecked` with its real `carried` maps) for
`ReviewPageRecheckTests`; and `review-waiting-big-assembly.json` (`waiting`, `failed_send`,
`restored`) for `ReviewPageSendLayoutTests` only.
