# Quickstart: Send the Review to the Model Only When the Engineer Wants It

**Feature**: `015-review-send-gate` | **Date**: 2026-10-08 | **Plan**: [plan.md](plan.md)

How to see each story work with no licence (Scenarios 1 to 7, on the development machine, where
SOLIDWORKS is never started) and on the pilot workstation (Scenario 8, the [W] task). Commands run
from `reviewer/` unless they say otherwise. Every fixture is fictional; expected results name the
contract that defines them rather than repeating it. Amended on 2026-10-09 for the owner's plan
review (decisions 68A to 80A, research R7).

## Prerequisites

- Features 001 to 013 on `main`, with the accepted 010-fine-pitch change integrated into the 015
  branch before its T007-T008 characterizations. Record the baseline commit and gate results in
  `review-2026-10-12.md`; the earlier `4818c62` code map is historical and its causes are re-verified
  before editing. For the current execution, wait for the root task's 010 and 014 integrations
  before capturing pins; reuse 014's `atomic.py` and skip T009-T010 when it is present. The open
  FR-041 finding in that review needs an owner decision before US4; the US1 milestone can proceed
  after the baseline gate.
- `uv sync` done; the tokenizer vocabulary fetched once
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
and so do the characterization of a ticked review (five goldens, its failures included) and the
prefix characterization, committed first on the pre-feature code (research R2.28). A commit that changes the words file regenerates every
fixture carrying the labels block in that same commit, so it is green too.

**The replay regeneration step** (research R2.28), on a machine that holds the owner's recordings
mapping (`%LOCALAPPDATA%\SwReview\recordings.json`), at the gate of every phase that changes the
runner, the pre-run, a provider or the records, and at the final gate: use 008
`contracts/replay.md` section 8's unchanged-fixture verification recipe from `reviewer/`:

```powershell
uv run python tests/fixtures/replay/verify_regeneration.py
```

Then from the repository root run the literal raw fixture check:

```powershell
git diff --exit-code -- reviewer/tests/fixtures/replay
```

Expected: no difference, with the nine package/session/event files byte-equal to the held
committed baseline. The verifier seeds only runtime producer inputs and calls the unchanged
generators and self-checks; its zero exit alone does not establish byte equality. Where the
mapping is absent, the step is skipped and the gate record says so, naming why.

## Scenario 1: A checks-only review with no key (US1)

```powershell
uv run pytest -q -p no:warnings -o addopts="" tests/unit/test_send_gate_server.py -k "checks_only or no_key or ticked"
```

Expected: an unticked `POST /sessions` answers 201 with the chat `awaiting_send`, the provider factory
never called, `events.jsonl` ending at `session.ended` with no `turn.ended`, `session.started` carrying
`send_when_checked: false`, `session.json` carrying `model_status {state: "not_sent"}`, `report.md`
reading "- Model: not sent to the model (checked by code only)", and the run's SOLIDWORKS pipe
released (`contracts/review-flow.md` sections 1 and 8, `contracts/records.md` sections 1 and 4). The
ticked review's no-key failure is pinned by the characterization (Scenario 7). Coverage holds the close-out row, one row per open question and one "not reviewed,
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
first request (SC-004; section 6 step 7); the size sentence's number, `session.sent`'s estimate and
`model_status`'s equal to `count_tokens(request_prefix(...))` of the request the provider received
(owner decision 78A); `None` and the "Send starts the model's
review." sentence with the vocabulary absent; Gemini's number called approximate; a failed first
request leaving the chat `awaiting_send`, its failure recorded, and a second Send carrying the opening
once (section 6); a Send that fails before any request - at each of its five points, the provider's
build among them - leaving the chat waiting, one `error` and no turn event, no provider request, and
`session.json` as it was before Send (section 6's guard, which only restores memory); a decision
held on the chat's worker with Send queued behind it (section 4); the snapshot's `send_in_flight`
while a Send is in flight (`contracts/pane.md` section 3). Continuing the hand
session of Scenario 1:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:<port>/sessions/$($chat.chat_id)/send" -Headers $h -Body "{}" -ContentType "application/json"
```

Expected: 202; the stream gains `session.sent` (the Transcript reads "Sending to ...") and the
scripted turn; `session.json`'s `model_status` becomes `sent` with `sent_at`, the estimate and
`opening_finding_ids`; the report adds "- Sent to the model: ...".

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
fails the chat, and leaves `session.json` as it was before the apply; a crash during the apply,
copied with `disk_at`, holds the record before the apply, its answers open and no turn event (its
read-only restore with Send offered is Scenario 4's, with the restored block).

## Scenario 4: A waiting review survives a restart (US4)

```powershell
uv run pytest -q -p no:warnings -o addopts="" tests/unit/test_recheck.py tests/unit/test_chat_review_routes.py tests/unit/test_review_snapshot.py
```

Expected, every restart a backend started afresh over the same run root and every cut-off the
folder a kill leaves (`tests/support/restart.py`): a re-run, started by Send, in the same folder with
zero extractions and zero bridge calls before the first request; the interference line and rows
equal the first run's, and its carried live step at the first run's step index; the part-roles
answer, the drawing answer whose read moved the numbers, and the Reject each on their own item, or
named in the `coverage.recheck` row, two decisions that meet one finding named and neither carried;
the opening after a carried part-roles answer naming no finding it withdrew; a `send_failed` record
still `send_failed` after its re-run; with nothing answered, the first request byte-identical to the
live waiting review's (SC-008); a failed and a refused re-run, and one cut off at each of three
points (the last inside `write_atomic`, its temporary left behind and passed over), each leaving
`session.json` byte-equal to the earlier record; a second re-run after a discarded answer adopting
the first (`contracts/recheck.md` sections 2 to 7). `GET /reviews` of a restarted app answers each
such folder, the copy a crash during an apply left (Scenario 3) and the `send_failed` copy a crash
during a Send left, read-only with the restored Send block and the composed restored line, and a
sent record as today (`test_chat_review_routes.py`; `contracts/recheck.md` section 8).

The re-run's time, opt-in (owner decision 70A):

```powershell
uv run pytest -m perf -s tests/perf/test_send_gate_perf.py
```

Expected: a ticked start, an unticked start and a re-run with a carry on the thousand-group package,
the seconds printed; the figures, and the bound they set - one 30 s rule when the larger re-run fits
inside 30 s, else `ChecksOnlyTimeout`, that re-run times three rounded up to the next 30 s - match
what research R2.17 and RK-10 record.

```powershell
cd ..
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~RunFoldersNotSentTests|FullyQualifiedName~RunFoldersModelStatusTests|FullyQualifiedName~ReviewHostTests|FullyQualifiedName~BackendClientSessionBodyTests"
```

Expected: the found-review search offers only the newest same-name folder's waiting record of this
path and configuration, never behind a newer review, opening one file of 500 fictional folders of the
same document and finishing within 2 s (`contracts/recheck.md` section 9); the head reader bounded at
64 KiB and opened so the backend can still replace the file; `sessions.list` refreshing only the
marked records; `review.recheck`'s refusals and request, its mode unable to ask for a re-run that
sends at once.

## Scenario 5: The box and the setting (US1)

```powershell
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~UserSettingsTests|FullyQualifiedName~PageMessageTests"
```

Expected: an absent, null or non-boolean value reads ticked, every other setting loads, a pre-feature
file saves to its own bytes; `send_when_checked.save` writes with no restart and is never refused; a
failed write is `SettingNotSaved` and the stored value stands, from `settings.save` too; a box save on
a file with a load problem clears the problem (`contracts/pane.md` section 1).

## Scenario 6: The page (US1 to US4)

```powershell
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~ReviewPageSendGate|FullyQualifiedName~ReviewPageRecheck|FullyQualifiedName~ReviewPageSendLayout|FullyQualifiedName~ReviewPageViews"
```

Expected, in the offscreen WebView2 against the backend-made `review-waiting.json`,
`review-waiting-restored.json` and `review-waiting-big-assembly.json`: the box under the buttons; an
unticked start showing "Checked by code. Not sent to the model.", the Send block under the summary
and no Stop; Send, a failed first round beside Send, a Send that failed before any request beside
Send with no error card, the same after a reload during the Send, "Apply answers"; a chip's "not
sent" from the host's item, after a reload too; a restored review read-only, its line feature 009's
sentence and the dated Send sentence, and its Send re-running it first; an apply that fails, and the
same after a reload, restoring the review read-only with Send; a reload during a re-run showing the
review only once it ends; a backend restart moving a waiting review to the restored state at once; at 300 by 600 the headline,
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

Expected: the characterization of a ticked review - five scenarios, each with its golden (success,
posted with no new key and with the host's body; a factory that raises; a first request that raises
before any round; a failure after a round; Stop at the first tool boundary), every provider and
presentation input, `events.jsonl`, `session.json`, `report.md` and `attention.json`, captured on the
pre-feature code - byte-identical, and the replay's first-pass prefix of each committed fixture the characterized
sha256 and length (FR-035, SC-003; research R2.28); the pane fixture's snapshot part byte-identical
and its labels block only five keys longer; the three waiting fixtures and the cross-language
record `review-not-sent-session.json` equal a fresh generation and pass the hygiene checks; every committed replay count unchanged; the replay refusing a never-sent
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
6. Close SOLIDWORKS while a review waits (owner decision 78A): press Review with the box still
   unticked and wait until the review waits; close SOLIDWORKS; reopen it and open the small
   assembly. Expected: the Review tab brings the review back from its run folder, read-only, its
   chip dated and marked not sent, with Send offered. Record that it came back with Send.
7. Record the timings, each inside one host call whose bound research R2.17 and RK-10 record from
   the development machine's measurement - the one 30 s rule when the re-run fitted inside 30 s,
   else `ChecksOnlyTimeout` (owner decision 70A); a re-run longer than 30 s under the one rule, or
   than a third of `ChecksOnlyTimeout`, sets the bound again by the same rule.
   1. How long step 2's unticked `POST /sessions` took (from the backend log, or else the time
      between the host's last "Extracting" status and its ready status: an unticked start posts no
      "checking" status, which only a re-run posts).
   2. How long a re-run takes: press Send to model on the review step 6 brought back. Record how long
      the re-run before the first request took (from the backend log, or the time between the host's
      "checking" and "ready" statuses), and that the run folder still holds one extraction.
   3. The same two timings on the big assembly: an unticked review of it, then SOLIDWORKS closed
      and reopened (or Settings saved, which restarts the backend), then Send.

## Results

*(Recorded by the gate task on the development machine and by the [W] task at the sitting.)*


- **T033 foundation, 2026-10-12:** combined T013–T032 candidate and input-only replay
  verification helper: 15,743 Python tests passed, 5 skipped, 7 deselected in 375.17 s;
  Ruff clean; Release zero warnings/errors; 9,060 extractor and 2,138 add-in tests passed,
  none skipped. Actual owner-mapped verifier completed all three unchanged generators
  with exact input budgets; literal fixture diff clean and all nine raw fixture files
  SHA256-equal to held bytes. Both frozen characterizations remain unchanged. The earlier
  combined run's stale renderer/words guards and their corrections are recorded in
  `review-2026-10-12.md`; it is not counted as green.

- **US1 backend checkpoint, 2026-10-12 (T034–T047; T057 pending):** combined candidate
  15,848 Python tests passed, 5 skipped, 7 deselected in 373.62 s; Ruff clean;
  Release zero warnings/errors; 9,060 extractor and 2,138 add-in tests passed, none
  skipped. Actual owner-mapped input-seeded regeneration left the literal replay diff
  clean and all nine raw fixture files unchanged; both frozen characterizations are unchanged.

- **T057 US1 checks-and-wait checkpoint, 2026-10-12:** final combined T048–T056
  candidate passed 15,870 Python tests, 5 skipped, 7 deselected in 380.50 s; Ruff
  clean; Release zero warnings/errors; 9,060 extractor and 2,176 add-in tests passed,
  none skipped. Post-gate actual owner-mapped verification completed all three unchanged
  generators, literal replay diff clean, nine raw fixture files byte-equal. Frozen ticked
  goldens/prefix pins and existing protected tests remain unchanged. Both actual waiting
  fixtures match independent raw generation; the 300x600 waiting page has 153.4375 px
  below Send and 199.828125 px below not-reached, with no overflow at 260/300/420 px.
  Independent final review found no issue. T118 and later stories remain incomplete;
  the displayed Send button gains its action in US2 T076. No partial-workflow main merge.


- **US2 Send and replay checkpoint, 2026-10-13 (T058–T079; T080/T081 pending):**
  final C39 candidate passed 15,962 Python tests, 5 skipped, 7 deselected in
  382.67 s; Ruff clean; Release zero warnings/errors; 9,060 extractor and
  2,220 add-in tests passed, none skipped. Actual owner-mapped verification
  completed all three unchanged replay generators, the literal replay diff
  was empty, and all nine replay outputs and 24 held public controls stayed
  raw SHA256-equal. Send, first-request failure/retry, stream replay, restore
  during Send, failed-Send layout and before-events replay refusals have their
  separate tests-first receipts in review-2026-10-12.md. The T077 300x600
  failed-Send acceptance passed with unchanged page assets. The strict T080
  estimate acceptance remains externally prepared and red: the unchanged
  25% SC-006 bound is exceeded by recorded gaps of 31.5%, 34.7% and 34.7%,
  also reproduced on the accepted pre-015 baseline. T081 and T118 remain
  incomplete; no US3 implementation, live provider run or SOLIDWORKS sitting
  is claimed, and this partial workflow has not been merged to main.


- **T081 US2 Send gate, 2026-10-13 (T058–T081 complete):** the owner approved
  SC-006's upper estimate tolerance of 35%; the required lower bound remains
  at billed input. T080 passed on all three actual recorded cases, with gaps
  of 31.5%, 34.7% and 34.7%. The final frozen C40 candidate passed 15,963
  Python tests, 5 skipped, 7 deselected in 385.77 s; Ruff clean; Release zero
  warnings/errors; 9,060 extractor and 2,220 add-in tests passed, none skipped.
  Actual owner-mapped regeneration completed all three unchanged generators,
  literal replay diff empty, nine replay outputs and all 24 held public
  controls raw SHA256-equal. Independent staged review was clean. This
  resolves the earlier T080/T081 pending decision; the estimator and request
  prefix were not changed. US3 starts at T082; T118 remains incomplete. No
  live provider run, SOLIDWORKS sitting or partial-workflow main merge is claimed.


- **T091 US3 answer-apply gate, 2026-10-14 UTC (T082-T091 complete):**
  final frozen C45 candidate passed 16,014 Python tests, 5 skipped,
  7 deselected in 393.11 s; Ruff clean; Release zero warnings/errors;
  9,060 extractor and 2,235 add-in tests passed, none skipped. Actual parent
  new page cases were 15 red before implementation and 15 green afterward.
  Actual owner-mapped verification completed all three unchanged replay
  generators, literal replay diff empty, all nine replay outputs and
  24 held public controls raw-equal. All 2,391 frozen files stayed unchanged
  through both full gates; protected assertions and both characterizations
  remain unchanged. Independent exact staged review was clean. Failed Apply
  restores the actual saved record read-only using genuine captured routes
  and events; restored Send stays disabled until US4. The full restart,
  carry and recheck flow begins at T092; T099/T100 and T118 remain pending.
  No live provider run, SOLIDWORKS sitting, remodel validation or partial
  workflow merge to main is claimed. See review-2026-10-12.md for exact
  test-first, fixture-provenance and failure-race receipts.
- **T110 US4 restart gate, 2026-10-15 (T092-T110 complete):** on the frozen candidate `38f37f0`:
  - Python 3.11.16, the worktree's own environment: 16,132 tests passed, 5 skipped, 7 deselected;
  - Ruff clean;
  - Release build: zero warnings/errors;
  - .NET: 9,138 extractor and 2,355 add-in tests passed, none skipped.

  The same not-live suite also passed 16,132 tests in isolated uv environments outside the
  repository, on Python 3.11.16 and on 3.12.3 (CI's matrix). Grep finds no 3.12-only API in
  `reviewer/src`, and all 199 source files compile on 3.11. The owner-mapped replay verification
  ran all three unchanged generators with seeded inputs; the literal replay diff was empty. Owner
  decision 93A fixes the re-run's commit point (FR-041). No live provider run or SOLIDWORKS sitting
  is claimed. See review-2026-10-12.md.
- **T117 the 014 merge and T118 final gate, 2026-10-15:** on the merge commit `579b0a5` (`main` at
  `48293bd`, 014 slice 5, merged in with no conflicts and nothing regenerated):
  - Python 3.11.16, the worktree's own environment: 16,307 tests passed, 5 skipped, 7 deselected;
  - Python 3.12.3, an isolated uv environment outside the repository: the same 16,307 passed,
    5 skipped, 7 deselected;
  - Ruff clean;
  - Release build, not incremental: zero warnings/errors;
  - .NET: 9,138 extractor and 2,364 add-in tests passed, none skipped.

  The five ticked goldens, the prefix characterization, the pane fixture and the pane parity pass as
  committed. The owner-mapped replay verification ran all three unchanged generators with seeded
  inputs, and the literal replay diff was empty. Scenarios 1 to 7 ran by their commands, all green.
  Scenarios 1 and 2 also ran by hand against a scratch backend: an unticked start waited with its
  size sentence, the record was `not_sent` and the report said so; Send answered 202, and the record
  became `sent`, with one `session.sent` and one turn. Scenario 4's perf run gave a ticked start of
  3.65 s, an unticked start of 3.87 s (0.20 s of added work) and a re-run with a carry of 4.09 s. All
  three are under R2.17's figures, and the re-run fits inside 30 s, so R2.17's one 30 s rule stands.
  The phase gates T033, T057, T081, T091 and T110 are recorded above. No live provider run or
  SOLIDWORKS sitting is claimed; T119 is the seat's. See review-2026-10-12.md.
