# Contract: The Words

Every sentence feature 015 adds, by where it lives, who reads it and where it shows (FR-034, the
spec's "the words are defaults"). Only the box's label and "Send to model" are the owner's (59A);
every other word here is a default taken 2026-10-08 that the owner may change as a one-line edit of
the file named. A sentence lives in exactly one place.

## 1. The words file: `reviewer/src/swreview/report/review_words_v1.yaml`

A new block, read by a new `SendWords` model (`Words.send`; a missing or misspelt key refuses the
file, as every block does). Served through the summary's `send` block and `resume_text`.

```yaml
# Feature 015: the Send block, beside "Send to model", and the questions panel while a review waits.
# `{tokens}` is the first request's counted input tokens, formatted 13,151; `{reason}` a provider's
# redacted message; `{time}` HH:MM and `{when}` YYYY-MM-DD HH:MM, the stored wall clock of the time
# (stamped by `local_now`, offset kept), never converted to the zone of the machine rendering it.
send:
  first_request: "Send starts the model's review. Its first request is {tokens} input tokens; the requests after it are not counted in advance."
  first_request_approximate: "Send starts the model's review. Its first request is about {tokens} input tokens (approximate: Gemini counts tokens its own way); the requests after it are not counted in advance."
  without: "Send starts the model's review."
  restored: "Send checks the saved evidence again, then starts the model's review."
  failed: "The model did not answer: {reason} ({time}). Nothing else changed; Send to model is offered again."
  not_started: "Send to model could not start: {reason} ({time}). Nothing was sent; Send to model is offered again."
  apply_answers: "Applying your answers regrades the review by code. Nothing is sent to the model."
  restored_line: "The backend restarted, so this review is shown from its run folder. Its checks ran {when}; its next answer, decision or Send checks the saved evidence again first."
  rerun_failed: "The saved evidence could not be checked again, so nothing changed and nothing was sent. The next answer, decision or Send tries again."
```

| Key | Shows | Serves |
|---|---|---|
| `first_request`, `first_request_approximate`, `without`, `restored` | the size sentence (`send.text`) | FR-012, FR-028 |
| `failed` | the failure line (`send.failure`) after a first request that failed | FR-017 |
| `not_started` | the failure line (`send.failure`) after a Send that failed before any request (`review-flow.md` section 6; *second review, 2026-10-09*) | FR-016, FR-017 |
| `apply_answers` | the questions panel's sentence (`resume_text`) while a review waits | FR-020 |
| `restored_line` | the line under the status line of a restored waiting review (`send.restored_text`) | FR-031 |
| `rerun_failed` | the failure line after a failed re-run (`send.rerun_failed_text`) | FR-041 |

`labels.errors` gains five keys (served by `GET /labels`; the pane fixture's labels block gains them,
regenerated in the commit that adds them, as is every fixture that carries the labels block, and
that commit's fixture diff reviewed for added keys only - research R2.25):

```yaml
    NoCredential: "No key is available, so nothing was sent. Save a key in Settings; the review keeps waiting."
    NotSent: "This review has not been sent to the model, so it takes no follow-up yet. Press Send to model first."
    NotWaiting: "This review is not waiting to be sent. Reload it to see where it stands."
    ReviewNotActive: "This review is of another document. Open that document in SOLIDWORKS, then try again."
    SettingNotSaved: "The setting could not be saved, so the box shows the stored setting again."
```

## 2. Page words: `extractor/SwReview.AddIn/Review/ReviewPage/app.js` and `render.js`

| Words | Where |
|---|---|
| "Send to the model when the checks finish" (59A) | the box's label (`index.html`) |
| "Send to model" (59A) | the Send block's button |
| "Checked by code. Not sent to the model." | the status line, waiting |
| "Checking the saved evidence again." | the status line, a re-run in flight |
| "Apply answers" | the questions panel's button while a review waits |
| "Not sent to the model yet: press Send to model first" | the follow-up box's placeholder while a review waits |
| " · not sent" | a chip's mark |
| "This decision no longer applies: its finding is not raised again." | a finding card's status, a decision a re-run could not carry |
| "Saving restarts the backend. The waiting review stays, and its next answer, decision or Send checks its saved evidence again first." | the Settings section while a review waits |
| "Checking the saved evidence again; save when it is done." | the Settings section while a re-run is in flight |
| "No key is stored. With the box ticked a review fails until one is entered; with it unticked the code checks run and Send waits for a key." | the key note, no key stored (replaces today's) |
| "Checked by code only: nothing is sent to the model until Send to model is pressed." | the Transcript's first line of an unticked review |
| "The checks ended at {ended_at}. Nothing was sent to the model." | the Transcript at `session.ended` while the review waits |
| "Sent to {provider} {model} ({requested} -> {param}={value})" and " - first request {n} input tokens" | the Transcript at `session.sent` |

## 3. Words the model reads: `reviewer/src/swreview/agent/runner.py` and `prerun.py`

| Constant | Words | Where |
|---|---|---|
| `WAIT_ANSWER_LINE` (`runner.py`) | "{request_id} ({question}) was answered before this review was sent: {answer}. The checks above were graded again by code with this answer." | the opening at Send, one per answered question (`review-flow.md` section 5) |
| `DRAWING_OUTCOME_LINE` (`runner.py:933`, feature 013) | "Drawing {file}: {outcome}" | unchanged; reused in the opening |
| `INTERFERENCE_ROWS_NOT_CARRIED` (`prerun.py`) | "{rows} live detection found when the checks first ran were never written to package.json, so this check of the saved evidence could not judge them" | the re-run's interference family row and digest line, when the first run's rows were not written (`recheck.md` section 3) |

`REGRADED_LINE` ("Checks first graded again after your answer: withdrew ...") and the resumed-turn
messages (`ANSWER_MESSAGE`, `ANSWERS_MESSAGE`) are not used for a review that waited (FR-023).

## 4. Words a person reads in the records: `agent/runner.py`, `prerun.py` and `report/markdown.py`

| Constant | Words | Where |
|---|---|---|
| `NOT_SENT_ITEM` (`runner.py`) | "{title}: not reviewed, because the review was not sent to the model" | an open model-owned checklist item of a review not sent |
| `NOT_SENT_SUFFIX` (`runner.py`) | "; the review was not sent to the model" | after feature 013's answered-but-open reason |
| `NOT_CARRIED` (`runner.py`) | "Not carried from the earlier check run: {items}." with items "the answer to {id} (its question is no longer asked)", "the answer to {id} (it matches more than one question)", "the {decision} of {id} (its finding is no longer raised)", "the {decision} of {id} (it matches more than one finding)", "the outcome of the drawing read for {id} (the read that merged its drawing did not finish)", and "the Standards profile it was graded with (the profile in Settings has changed since; this check of the saved evidence graded with the new one)" - the last two added on the second review, 2026-10-09; no item names a path | the re-run's `coverage.recheck` row |
| `INTERRUPTED_SEND` (`runner.py`) | "the backend stopped before the model answered" | a Send attempt's reason until its outcome is known |
| `CARRIED_LIVE_NOTE` (`prerun.py`) | "ran when the checks first ran; this check of the saved evidence carried its outcome and did not ask SOLIDWORKS again" | the `note` of a re-run's carried live-detection step (`recheck.md` section 3), read in the step's result and the Transcript's tool line |
| report header (`markdown.py`) | "- Model: not sent to the model (checked by code only)"; "- Model: not sent to the model; the last attempt failed at {at}: {reason}"; "- Sent to the model: {sent_at} (checks finished {checked_at})"; "- Earlier attempts that failed: {n}"; "- Checked again from session: {id}" | `records.md` section 4 |
| recording refusals (`benchmark/recording.py`) | "{RUN_DIR} was never sent to the model, so it has no model turn to replay"; "{RUN_DIR} was sent to the model after waiting for Send; the replay reads only reviews sent when their checks finished" | `records.md` section 6 |

## 5. Words the host writes: `extractor/SwReview.AddIn/Review/ReviewHost.cs`

| Words | Where |
|---|---|
| "Checked {n} components by code; nothing was sent to the model." | the ready status after an unticked start |
| "Checking the saved evidence again..." / "Checked the saved evidence again; nothing was sent to the model." | the status around a re-run (stage `checking`, then `ready`) |
| "send_when_checked '{token}' is not true or false; ticked is in use." | a settings load problem (`UserSettings`) |
| the `ReviewNotActive` and `SettingNotSaved` messages | the developer-facing message behind each class's label |
