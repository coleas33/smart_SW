# Contract: The Words

Every sentence feature 015 adds, by where it lives, who reads it and where it shows (FR-034, the
spec's "the words are defaults"). Only the box's label and "Send to model" are the owner's (59A);
every other word here is a default taken 2026-10-08 that the owner may change as a one-line edit of
the file named. A sentence lives in exactly one place. Amended on 2026-10-09 by the owner's plan
review (research R7): decisions 68A, 72A and 73A.

## 1. The words file: `reviewer/src/swreview/report/review_words_v1.yaml`

A new block, read by a new `SendWords` model (`Words.send`; a missing or misspelt key refuses the
file, as every block does). Served through the summary's `send` block and `resume_text`. And feature
009's `read_only` key is held as its two sentences, each a key (owner decision 73A), so a restored
not-sent review's line can begin with the first without a second copy of it:

```yaml
# Feature 009's read-only line, held as its two sentences (feature 015, owner decision 73A).
# `Words.read_only` composes them, a space between, word for word the sentence 009 shows today; a
# restored not-sent review's line is `read_only_lead`, a space, and `send.restored_line`.
read_only_lead: "The backend restarted, so this review is shown from its run folder."
read_only_off: "Follow-ups, decisions and answers are off."
```

The two keys replace the one `read_only` key; `Words` reads them as two fields and keeps `read_only`
as a property composing them, so `chat/server.py:1681` and every test that reads
`load_words().read_only` read 009's sentence unchanged. **Amends 009** `data-model.md` (its words
table's `read_only` row).

The `send` block:

```yaml
# Feature 015: the Send block, beside "Send to model", and the questions panel while a review waits.
# `{tokens}` is the first request's counted input tokens, formatted 13,151 by the one formatter the
# `resume` block's sentence uses; `{reason}` a provider's redacted message; `{time}` HH:MM and `{when}`
# YYYY-MM-DD HH:MM, the stored wall clock of the time (stamped by `local_now`, offset kept), never
# converted to the zone of the machine rendering it. `restored_line` follows `read_only_lead`.
send:
  first_request: "Send starts the model's review. Its first request is {tokens} input tokens; the requests after it are not counted in advance."
  first_request_approximate: "Send starts the model's review. Its first request is about {tokens} input tokens (approximate: Gemini counts tokens its own way); the requests after it are not counted in advance."
  without: "Send starts the model's review."
  restored: "Send checks the saved evidence again, then starts the model's review."
  failed: "The model did not answer: {reason} ({time}). Nothing else changed; Send to model is offered again."
  not_started: "Send to model could not start: {reason} ({time}). Nothing was sent; Send to model is offered again."
  apply_answers: "Applying your answers regrades the review by code. Nothing is sent to the model."
  restored_line: "Its checks ran {when}; Send checks the saved evidence again first."
  rerun_failed: "The saved evidence could not be checked again, so nothing changed and nothing was sent. The next Send tries again."
```

| Key | Shows | Serves |
|---|---|---|
| `first_request`, `first_request_approximate`, `without`, `restored` | the size sentence (`send.text`) | FR-012, FR-028 |
| `failed` | the failure line (`send.failure`) after a first request that failed | FR-017 |
| `not_started` | the failure line (`send.failure`) after a Send that failed before any request (`review-flow.md` section 6; *second review, 2026-10-09*) | FR-016, FR-017 |
| `apply_answers` | the questions panel's sentence (`resume_text`) while a review waits | FR-020 |
| `restored_line` | the second sentence of the line under the status line of a restored waiting review: the snapshot's `read_only_reason` is `read_only_lead` ("The backend restarted, so this review is shown from its run folder."), a space, and this sentence, composed by the backend (owner decision 73A; `recheck.md` section 8). The lead is one key, from which feature 009's `read_only` sentence is composed too, so the two never drift. 009's second sentence, `read_only_off`, is not part of this line: the restored review's questions panel, decisions and follow-up are off as on 009's restore, and the Send block under the summary says what Send does | FR-031 |
| `read_only_lead`, `read_only_off` (feature 009's `read_only`, split) | feature 009's read-only line, as `Words.read_only` composes them, shown for every restored review but a `not_sent` or `send_failed` one; `read_only_lead` also leads a restored not-sent review's line (owner decision 73A) | FR-031; 009 FR-021 |
| `rerun_failed` | the failure line after a failed re-run (`send.rerun_failed_text`) | FR-041 |

`labels.errors` gains five keys (served by `GET /labels`; `SettingNotSaved` is answered by both
`send_when_checked.save` and `settings.save`, owner decision 73A; the pane fixture's labels block gains them,
regenerated in the commit that adds them, as is every fixture that carries the labels block, and
that commit's fixture diff reviewed for added keys only - research R2.25):

```yaml
    NoCredential: "No key is available, so nothing was sent. Save a key in Settings; the review keeps waiting."
    NotSent: "This review has not been sent to the model, so it takes no follow-up yet. Press Send to model first."
    NotWaiting: "This review is not waiting to be sent. Reload it to see where it stands."
    ReviewNotActive: "This review is of another document. Open that document in SOLIDWORKS, then try again."
    SettingNotSaved: "The settings could not be saved, so the stored settings stand."
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
| " · not sent" | a chip's mark, from the host's `sessions` item (owner decision 73A) |
| "Saving restarts the backend. The waiting review stays, and its Send checks its saved evidence again first." | the Settings section while a review waits (owner decision 68A) |
| "Checking the saved evidence again; save when it is done." | the Settings section while a re-run is in flight |
| "No key is stored. With the box ticked a review fails until one is entered; with it unticked the code checks run and Send waits for a key." | the key note, no key stored (replaces today's) |
| "Checked by code only: nothing is sent to the model until Send to model is pressed." | the Transcript's first line of an unticked review |
| "The checks ended at {ended_at}. Nothing was sent to the model." | the Transcript at `session.ended` while the review waits |
| "Sending to {provider} {model} ({requested} -> {param}={value})" and " - first request {n} input tokens" | the Transcript at `session.sent`, which is written before the attempt's record and can precede a failure (owner decision 72A) |

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
| `NOT_CARRIED` (`runner.py`) | "Not carried from the earlier check run: {items}." with items "the answer to {id} (its question is no longer asked)", "the answer to {id} (it matches more than one question)", "the {decision} of {id} (its finding is no longer raised)", "the {decision} of {id} (it matches more than one finding)", "the {decision} of {id} (another decision matches the same finding)", "the outcome of the drawing read for {id} (the read that merged its drawing did not finish)", and "the Standards profile it was graded with (the profile in Settings has changed since; this check of the saved evidence graded with the new one)" - the drawing outcome and the profile added on the second review, 2026-10-09, and the decision another decision shares a finding with by owner decision 72A; no item names a path | the re-run's `coverage.recheck` row |
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
