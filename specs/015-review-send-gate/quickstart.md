# Quickstart: Send the Review to the Model Only When the Engineer Wants It

**Feature**: `015-review-send-gate` | **Date**: 2026-10-08 | **Plan**: [plan.md](plan.md)

How to see each story work with no licence (Scenarios 1 to 7, on the development machine, where
SOLIDWORKS is never started) and on the pilot workstation (Scenario 8, the [W] task). Commands run
from `reviewer/` unless they say otherwise. Every fixture is fictional; expected results name the
contract that defines them rather than repeating it.

## Prerequisites

- Features 001 to 013 on `main`; `uv sync` done; the tokenizer vocabulary fetched once
  (`uv run swreview tokenizer fetch`, or `--from <file>`), so `SWREVIEW_REQUIRE_TOKENIZER=1` holds.
- The .NET build tools and the WebView2 runtime for the add-in and page tests:
  `dotnet build extractor/SwReview.sln -c Release --nologo -v q` from the repository root.
- No key is needed for any scenario before Scenario 8: the backend's tests use the scripted provider
  and a provider stand-in that fails if it is ever built.

## The gate

```powershell
$env:SWREVIEW_REQUIRE_TOKENIZER = "1"
uv run pytest -q -p no:warnings -o addopts="" -m "not live"
uv run ruff check src tests
cd ..
dotnet build extractor/SwReview.sln -c Release --nologo -v q
dotnet test extractor/SwReview.sln -c Release --no-build --nologo
```

All green before every commit; the add-in tests are part of the gate (62A). The tracked-files guard
and the lever guard (`test_no_lever_in_pane_settings.py`) are in the first command and pass unchanged,
and so do the characterization golden of a ticked review and the prefix characterization, committed
first on the pre-feature code (research R2.28). A commit that changes the words file regenerates every
fixture carrying the labels block in that same commit, so it is green too.

**The replay regeneration step** (research R2.28), on a machine that holds the owner's recordings
mapping (`%LOCALAPPDATA%\SwReview\recordings.json`), at the gate of every phase that changes the
runner, the pre-run, a provider or the records, and at the final gate: run 008
`contracts/replay.md` section 8's three generator commands from `reviewer/`, then

```powershell
git diff --exit-code -- reviewer/tests/fixtures/replay
```

Expected: no difference. Where the mapping is absent, the step is skipped and the gate record says
so, naming why.

## Scenario 1: A checks-only review with no key (US1)

```powershell
uv run pytest -q -p no:warnings -o addopts="" tests/unit/test_send_gate_server.py -k "checks_only or no_key or ticked"
```

Expected: an unticked `POST /sessions` answers 201 with the chat `awaiting_send`, the provider factory
never called, `events.jsonl` ending at `session.ended` with no `turn.ended`, `session.started` carrying
`send_when_checked: false`, `session.json` carrying `model_status {state: "not_sent"}`, and `report.md`
reading "- Model: not sent to the model (checked by code only)" (`contracts/review-flow.md` section 1,
`contracts/records.md` sections 1 and 4). The ticked review with no key still fails 502 before any
check (FR-035). Coverage holds the close-out row, one row per open question and one "not reviewed,
because the review was not sent to the model" row per open model-owned item (SC-002).

By hand, against a running backend with the scripted provider (development build only):

```powershell
$fict = Join-Path $env:TEMP "fict-send-gate"
New-Item -ItemType Directory -Force "$fict\runs\20261008-090000-FICT-1001" | Out-Null
Copy-Item tests\fixtures\replay\big-assembly\package.json "$fict\runs\20261008-090000-FICT-1001\"
uv run swreview chat serve --port 0 --run-root "$fict\runs" --dev
# read {"port", "token"} from the first stdout line, then:
$h = @{ Authorization = "Bearer <token>" }
$body = @{ run_dir = "$fict\runs\20261008-090000-FICT-1001"; provider = "fake"; send_when_checked = $false } | ConvertTo-Json
$chat = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:<port>/sessions" -Headers $h -Body $body -ContentType "application/json"
Invoke-RestMethod -Uri "http://127.0.0.1:<port>/sessions/$($chat.chat_id)" -Headers $h        # state: awaiting_send
(Invoke-RestMethod -Uri "http://127.0.0.1:<port>/sessions/$($chat.chat_id)/attention" -Headers $h).summary.send
```

Expected: the `send` block in state `waiting` with the size sentence and its number
(`contracts/estimate.md` section 3).

## Scenario 2: Send, its size, and a failed first request (US2)

```powershell
uv run pytest -q -p no:warnings -o addopts="" tests/unit/test_send_gate_server.py tests/unit/test_runner_send.py tests/unit/test_send_estimate.py tests/unit/test_deferred_provider.py
```

Expected: Send's refusals in the order of `contracts/review-flow.md` section 3; every request of the
Send turn - the first and those after its tool calls, tool results included - byte-identical to a
ticked review's of the same package, because the checks' finalization rows are withdrawn before the
first request (SC-004; section 6 step 4); the size sentence's number equal
to `count_tokens(request_prefix(...))` of exactly that request; `None` and the "Send starts the model's
review." sentence with the vocabulary absent; Gemini's number called approximate; a failed first
request leaving the chat `awaiting_send`, its failure recorded, and a second Send carrying the opening
once (section 6); a Send that fails before any request - at each of five points - leaving the chat
waiting, one `error` and no turn event, no provider request, and `session.json` as it was before
Send (section 6's guard); a decision held in flight refusing Send (section 4). Continuing the hand
session of Scenario 1:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:<port>/sessions/$($chat.chat_id)/send" -Headers $h -Body "{}" -ContentType "application/json"
```

Expected: 202; the stream gains `session.sent` and the scripted turn; `session.json`'s `model_status`
becomes `sent` with `sent_at`, the estimate and `opening_finding_ids`; the report adds "- Sent to the
model: ...".

## Scenario 3: Answers while it waits (US3)

```powershell
uv run pytest -q -p no:warnings -o addopts="" tests/unit/test_waiting_answers.py
```

Expected, on feature 013's part-roles shape: "All bought" while waiting withdraws the unclear part's
findings - at least one named finding among them, besides the folded RMS ones - with no provider
request and recounts the size; the panel's sentence is `send.apply_answers`; after Send the opening
names no withdrawn finding, its folded counts line equals the regraded counts, it carries the answer
line, and it has no "withdrew" line and no instruction (SC-005; `contracts/review-flow.md` sections 4
and 5); the Reject made while waiting is still on its finding; an apply that fails writes one `error`,
fails the chat, and leaves `session.json` as it was before the apply.

## Scenario 4: A waiting review survives a restart (US4)

```powershell
uv run pytest -q -p no:warnings -o addopts="" tests/unit/test_recheck.py
```

Expected: a re-run in the same folder with zero extractions and zero bridge calls before the first
request; the interference line and rows equal the first run's, and its carried live step at the first
run's step index; the part-roles answer, the drawing answer whose read moved the numbers, and the
Reject each on their own item, or named in the `coverage.recheck` row; a `send_failed` record still
`send_failed` after its re-run; with nothing answered, the first request byte-identical to the live
waiting review's (SC-008); a failed and a refused re-run, and one cut off at each of three points,
each leaving `session.json` byte-equal to the earlier record and `GET /reviews` answering it, not
read-only, with Send offered; a second re-run after a discarded answer adopting the first
(`contracts/recheck.md` sections 2 to 8).

```powershell
cd ..
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~RunFoldersNotSentTests|FullyQualifiedName~ReviewHostTests|FullyQualifiedName~BackendClientSessionBodyTests"
```

Expected: the found-review search offers only the newest same-name folder's waiting record of this
path and configuration, never behind a newer review, within 2 s on 500 fictional folders
(`contracts/recheck.md` section 9); `review.recheck`'s refusals and request.

## Scenario 5: The box and the setting (US1)

```powershell
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~UserSettingsTests|FullyQualifiedName~PageMessageTests"
```

Expected: an absent, null or non-boolean value reads ticked, every other setting loads, a pre-feature
file saves to its own bytes; `send_when_checked.save` writes with no restart and is never refused; a
failed write is `SettingNotSaved` and the stored value stands (`contracts/pane.md` section 1).

## Scenario 6: The page (US1 to US4)

```powershell
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~ReviewPageSendGate|FullyQualifiedName~ReviewPageRecheck|FullyQualifiedName~ReviewPageSendLayout|FullyQualifiedName~ReviewPageViews"
```

Expected, in the offscreen WebView2 against the backend-made `review-waiting.json`,
`review-waiting-restored.json` and `review-waiting-big-assembly.json`: the box under the buttons; an
unticked start showing "Checked by code. Not sent to the model.", the Send block under the summary
and no Stop; Send, a failed first round beside Send, a Send that failed before any request beside
Send with no error card, "Apply answers"; a restored review's line and its re-run on the first
action, with real ids re-keyed; a reload during a re-run showing the review only once it ends; a
backend restart moving a waiting review to the restored state at once; at 300 by 600 the headline,
tally and not-reached line, and the Send to model button, in view in the four worst cases (SC-007;
`contracts/pane.md` section 11, which records the measured slack). The existing 300 by 600 tests run
with the box in place, unedited (measured to hold it: about 21 px of 226 px, research R2.21):

```powershell
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~ReviewPageSummaryAcceptance|FullyQualifiedName~ReviewPageNarrowLayout"
```

## Scenario 7: Nothing else moved

```powershell
uv run pytest -q -p no:warnings -o addopts="" tests/unit/test_ticked_review_golden.py tests/unit/test_request_prefix_characterization.py tests/unit/test_pane_fixture.py tests/unit/test_pane_waiting_fixtures.py tests/unit/test_replay_fixture_hygiene.py tests/unit/test_replay_fixtures.py tests/unit/test_recording.py tests/unit/test_cli_benchmark_replay.py tests/unit/test_no_lever_in_pane_settings.py
```

Expected: the characterization golden of a ticked review - every provider and presentation input,
`events.jsonl`, `session.json`, `report.md` and `attention.json`, captured on the pre-feature code -
byte-identical, and the replay's first-pass prefix of each committed fixture the characterized
sha256 and length (FR-035, SC-003; research R2.28); the pane fixture's snapshot part byte-identical
and its labels block only five keys longer; the three waiting fixtures equal a fresh generation and
pass the hygiene checks; every committed replay count unchanged; the replay refusing a never-sent
review and one sent after waiting in one sentence each (`contracts/records.md` section 6); the lever
guard green. Where the owner's recordings are, the replay regeneration step of the gate shows no
difference in any replay fixture.

## Scenario 8: The pilot workstation ([W], SC-010)

On the licensed seat, with the build of this feature and the owner's key stored:

1. In the Review tab, untick "Send to the model when the checks finish"; close and reopen SOLIDWORKS;
   the box is still unticked.
2. Open the small assembly; press Review. Expected: the checks run, the status line reads "Checked by
   code. Not sent to the model.", the Send block shows its sentence (with a number only if the
   tokenizer vocabulary is on the seat - record which), Stop is not offered, and the run folder's
   `session.json` says `not_sent`.
3. If the checks raise the part-roles question, answer it while the review waits; the findings it
   withdraws leave the list and the sentence is recounted. If they raise none, record that (the
   withdrawal is then proven on the fixture only, SC-005). If every finding it withdrew is in a
   folded family (counted in the opening, never named), record that too: step 4's named-ids check is
   then trivially true and proves nothing about them.
4. Press Send to model. Expected: the review runs as a review sent at once; it completes; the run folder
   holds one extraction in total, and `model_status.opening_finding_ids` names none of the findings the
   answer withdrew; the report says when it was sent.
5. Record in the results sheet: zero model rounds before Send (the `usage` events all follow
   `session.sent`), one extraction, the named ids, and whether the sentence carried a number.
6. Record two timings. Both run inside one host call with the long timeout every call with
   `send_when_checked` false has, 10 minutes (research RK-10), and these two numbers are what that
   bound is later set from.
   1. How long step 2's unticked `POST /sessions` took (from the backend log, or the time between the
      host's "checking" and "ready" statuses).
   2. How long a re-run takes. Press Review again with the box still unticked and wait until the
      review waits; save Settings, which restarts the backend; then press Send to model. Record how
      long the re-run before the first request took, measured the same way, and that the run folder
      still holds one extraction.

## Results

*(Recorded by the gate task on the development machine and by the [W] task at the sitting.)*
