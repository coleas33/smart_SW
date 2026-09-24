# Workstation handover: the sitting for features 008 to 011, in order

Written 2026-09-23 for the next sitting on a licensed SOLIDWORKS seat, which may be a fresh
machine: the pilot seat declared itself done (`docs/roadmap-2026-09-22.md`). Addressed to the
assistant operating the seat. `docs/workstation-runbook.md` is the standing manual; read it first
and keep its three rules: never commit or push per-machine state, never push `main`, close
SOLIDWORKS before building or registering. This document replaces the 2026-09-20 round-2
handover as the current work; it is one ordered list of every seat task of features 008, 009, 010
and 011, each with its command, what decides pass or fail, and where its record goes. The task
texts in `specs/00N-*/tasks.md` stay the source of truth: where this document and a task
disagree, the task wins and the difference is a finding. The engineer who runs the sitting follows
`docs/workstation-test-plan-2026-09-23.md` (011 T100): the same sitting in plain, numbered steps,
each with its exact command and what counts as pass or fail, and its results sheet
`docs/workstation-results-2026-09-23.md`, which becomes the findings document. **Where this list
and the test plan differ, the test plan is what the seat follows.** On any failure, the test plan's
sections "When a step fails", "If SOLIDWORKS stops answering" and "Going back to the build you
had", and its Results table, are what the seat follows; this list does not repeat them.

**What the seat does not do.** It commits and pushes nothing at this sitting: the findings
document travels in the handover folder, and the owner reads it and commits it from the
development machine (runbook rule 2, the test plan's step 6.5). It saves nothing in SOLIDWORKS: the
one write is the test plan's Pack and Go copy into `%TEMP%` for the view-out-of-date probe (step
3.5), deleted at its step 6.0, and the plan fingerprints the real files before and after. Two
switches wait on this sitting's probe records - `DRAWING_BINDING_VALIDATED` (011 T066) and
`DrawingOpenScope.SeatValidated` (011 T077) - and the development machine sets them afterwards,
each in a commit of its own. What can only be seen with a switch on is 011 T095, at the sitting
after that. Two tasks are the development machine's once the folders come back: 008 T105 (replay
the sitting's runs) and 009 T085 (restore them offline).

## 0. Before the sitting: what the owner brings

1. **The real standards profile at version 3.** The owner's file on the development machine says
   `version: 1`: it loads, but feature 010's hygiene and general-tolerance checks and feature
   011's drawing comparison would come back skipped on every paid review, and 011 T068 cannot
   run. The owner rewrites it at version 3 - `general_tolerance`, `hygiene` and `drawing` added -
   from `config\standards.example.yaml`'s layout, with the company's values, and carries it by
   hand. It never enters the repository or this document.
2. **The o200k_base vocabulary**, if the seat's web filter blocks its download: the file
   `fb374d419588a4632f3f557e76b4b70aebbca790` from the development machine's
   `%LOCALAPPDATA%\SwReview\tokenizer\` (runbook section 2).
3. **A provider key** for the pane's Settings (the paid reviews), with the model and effort to use,
   and **a Gemini key** for 008 T106, which is set for one shell only, at a hidden prompt. The
   people, the cap for the big assembly's review and the answer to a "Before this review" panel
   are in the test plan's section 0.1.
4. **The documents the probes and reviews need**, named by the engineer before the sitting (the
   test plan's section 0.2 gives each a letter and says what it must carry): the
   two recorded assemblies (008 T102 and T103 name them); a multi-sheet drawing with a revision
   table off its first sheet (011 T062, 006 T103); an assembly with the drawings of two of its
   parts and of one unrelated part (T063); the drawings `specs/011-drawing-context/contracts/probes.md`
   names (T064, T065); a part drawing and an assembly drawing whose callouts the engineer names
   beforehand (T066); a reviewed part whose same-name drawing exists and is closed (T077); a
   design with a candidate drawing and a part drawn twice (T067); a design with its drawing open
   (T068).

## 1. Install or update, then check

On a fresh machine, runbook sections 2 and 3 (prerequisites, clone, gate, registration from an
elevated prompt; the test plan's section 0.3); on the old seat, section 4. Either way,
non-elevated, and pull **before** running the script, so the script that runs is the one that
arrived (a seat older than 2026-09-24 has a script without `-TokenizerFrom`, `-SolidWorksRoot` or
the `swreview-extract:` health line):

```powershell
$R = '<repo>'; cd $R
git status --porcelain; git branch --show-current     # nothing, then main
git rev-parse --short HEAD                            # the commit before the update: record it
git fetch origin; git log --oneline HEAD..origin/main
git pull --ff-only origin main; "pull exit code: $LASTEXITCODE"
.\extractor\tools\update-workstation.ps1 -NoPull      # add -TokenizerFrom "<file>" or -SolidWorksRoot "<root>" as section 2 says
git log --oneline -1                                  # this document's commit or a later one
Set-Alias swreview-extract "$R\extractor\SwReview.Extractor.Console\bin\x64\Release\net48\swreview-extract.exe"
Select-String -Path "$env:LOCALAPPDATA\SwReview\standards.yaml" -Pattern '^version:'   # after step 1 below
```

Pass: `pull exit code: 0`, the script ends at its health step with no step failed, and runbook
section 6's seven checks hold. Record the commit before and after and the versions of section 2 at
the top of the findings document. Every `swreview-extract` command below needs the alias in the
shell it runs in; every `uv run` command runs from `<repo>\reviewer`.

## 2. The order, and why

| Must come first | Before | Why |
|---|---|---|
| Step 1, the real profile (008 T101) | every Standards press and every paid review | an example or version 1 profile grades against nobody's standard, silently |
| Step 2, the dumps (010 T103 to T106) | step 11's review (010 T107) | T107 reads engagement the widened dump makes possible |
| Steps 3 to 6, the probes D1 to D13 | step 7 (011 T066) | T066 compares D6 and D8 with T064's D4 and D5 on the same drawing |
| Step 8's probe D14 | step 8's pane review (T077) | the pane half is read against the probe's answers |
| Step 11 (008 T102) | step 12 (T104) | T104 presses Retry on T102's run folder |
| everything else | step 18 (009 T082) | it builds an older commit, then returns to `main` |

## 3. The script

Each step: the task, what to run, what decides it, and where the record goes. "The findings
document" is `pane-findings-<date>.md` in `%LOCALAPPDATA%\SwReview\handover\<date>\` (runbook
section 8), where the date is the handover folder's, the sitting's first day: the test plan copies
`docs/workstation-results-2026-09-23.md` there at its step 1.4, on day 1, once the update has
brought it (an older checkout has no such file before the pull), and its Results table takes one
row per step and task id. The development machine moves each answer into the research file named.

1. **008 T101 and 006 T100: the real profile.** Place the owner's file at
   `%LOCALAPPDATA%\SwReview\standards.yaml`; `Select-String` shows `version: 3`; runbook section
   5's check command reports no schema error. Then one pane review: its run folder's
   `session.json` holds a pre-run step for `check_standards` (quickstart Scenario 11 of 008). A
   version below 3 stops the sitting's paid reviews until the owner rewrites it. Record: the
   findings document.
2. **010 T103 to T106: the dumps.** For each recorded assembly, active in SOLIDWORKS:
   `swreview-extract dump --out "<handover folder>\dumps\A" --meshes none` (then `B`), never under
   the run root, where step 16's exporter would take a dump for a review, then the check
   command in the Phase 13 note of `specs/010-mechanical-checks/tasks.md` on that folder. Pass:
   `mass_overridden read` equals `documents` and `mass_override gaps` is 0 (T103); every Hole
   Wizard hole has `Hole.wizard` and the fit and thread classes printed are recorded (T104);
   `model_dimensions` and `model_annotations` present where the models carry them, or 0 with no
   gap (T105); the named screws are fasteners, each with a shank face, and nothing else is (T106).
   The last line of each `extract.log`, `gated=...`, says which mass-override path answered:
   `GetOverrideOptions` in it means the first path failed somewhere. Record: the printed lines
   and the `gated=` line, for 010 `research.md`.
3. **011 T062: a multi-sheet drawing.** Once for the sitting,
   `New-Item -ItemType Directory -Force "<handover folder>\probes"`: every probe run writes its
   report there and never overwrites one. Open the drawing, then
   `swreview-extract probe drawings --out "<handover folder>\probes" --doc "<drawing>" --probe D1,D11`,
   then press Standards check; then 006 T103, T105 and T107 as their task texts say (T107's
   not-loaded model is the test plan's step 3.5, on a drawing opened in Detailing mode). Pass:
   the probe report's answers and its gate log (no writer, activation, open or close member). Record: the
   `drawings-probe-<time>.txt` files stay in the `--out` folder; the answers go to 011 research
   R4 and 006 research R4.
4. **011 T063: discovery.** With the assembly and the three drawings open:
   `swreview-extract probe drawings --out "<handover folder>\probes" --doc "<assembly>" --probe D2,D13`,
   then `--probe D3,D12` with each drawing as `--doc` (D3 and D12 read a drawing, so on the
   assembly they read nothing), then a
   pane review. Pass: the two part drawings are read and the unrelated one is not; nothing was
   opened; the candidate check neither fetched nor stalled. Record: discovery's time, from the
   probe report.
5. **011 T064: D4, D5, D8 and D11** on the drawings `contracts/probes.md` names, with
   `--probe D4,D5,D8,D11`. If D4 shows `units_decimal_places_raw` governs a document-precision
   dimension, that is a finding for the development machine (T064's one-line change), not an
   edit here.
6. **011 T065: D6, D7, D9 and D10** with `--probe D6,D7,D9,D10`. Pass: the typed annotations and
   tables are read or named in gaps, with no value silently absent.
7. **011 T066: the named callouts.** On the part drawing and on the assembly drawing whose
   callouts the engineer named: `--probe D6,D8`, and D4 and D5 again on the same drawing. Pass:
   every checked callout ties to the right hole, and D4 and D5 agree with `native_dimension`'s
   value, tolerance and unit. Record the verdict and every mismatch; do **not** change the switch.
8. **011 T077: the read-only open.** Beside the reviewed part whose same-name drawing is closed
   (the test plan's part J):
   `swreview-extract probe drawings --out "<handover folder>\probes" --doc "<part J>" --probe D14`,
   then again with the drawing open. Pass: every answer T077 lists (the `OpenDoc6` integers, the active document
   and focus unchanged, the hidden views read, the file's size, write time and SHA-256
   unchanged, no save flag, released after the close, the counts). Then a pane review with the
   candidate, confirmed: the pane shows the host's refusal ("the read-only open of a confirmed
   drawing is not yet validated on a seat") and nothing opens - which is right while the switch
   is off. Record: the report file and the pane's sentence. In the same pane reviews, 011 T101:
   the lanes' live checks of User Story 5's part B (the test plan's part J; its B is the big
   assembly) with the switch off - the `drawing.read` line of the
   tool-service log, the `drawing.confirmed_open` coverage for a candidate left closed and for one
   the engineer opened before confirming, the summary's drawings line before and after, one
   `drawing.context` line per document, and the pane at 300 by 600 (the test plan's steps 4.6
   and 4.7).
9. **011 T067: the questions.** A pane review of the design with a candidate drawing and a
   doubly-drawn part: the two questions appear (at most four drawing questions), answering them
   records the answers, and the part's brief lists them with all five sections. The brief's size,
   built with the profile as the review's `get_drawing_brief` is, with `$run` the run folder and
   `$doc` the id exactly as the run's package prints it (`doc:` and twelve hex digits):
   `cmd /c "uv run swreview drawing brief --package ""$run"" --run ""$run"" --document $doc --profile ""$env:LOCALAPPDATA\SwReview\standards.yaml"" > ""%TEMP%\swreview-brief.json"""`
   then `(Get-Item "$env:TEMP\swreview-brief.json").Length` (at most 6,001 bytes: the brief's 6,000
   and the newline the command ends it with). `cmd /c` keeps the brief's bytes; a PowerShell
   redirect would re-encode them.
10. **011 T068, its unswitched half.** With the version 3 profile, review the design with its
    drawing open: the drawing is compared with the profile's drawing section, any finding names
    only the drawing's values, and the general tolerance's answer names the seat validation
    ("drawing callouts are read but not yet validated on a seat..."). That answer reaches the
    report only when a stack-up asks the resolver, so the design needs a toleranced model
    dimension or an ISO 286 Hole Wizard fit on a joint; a report saying "no tolerance source is
    read for this package" means T068 is blocked at this sitting, not passed. The binding itself is
    T095.
11. **008 T102, 010 T107 and 009 T079, T080: the big assembly, paid.** A pane review with the
    defaults. Pass for T102: the report's input tokens, uncached plus cached, at most **995,853**
    (1.5 times the replay's "Requested, pane defaults" figure for `big-assembly`, 663,902, in
    `docs/llm-efficiency-options.md`); every detected interference group judged, as a finding or
    a contact; the rows in the run folder's `package.json`; the usage line and the report both
    show uncached and cached input as two numbers. Record the finding and contact counts; the
    comparison with the recorded findings by subject key is made on the development machine
    (T105). The same run is 010 T107's (contacts apart and outside "Start here", the joint, mass
    and hygiene findings before the first model turn, no model round spent on them), the
    summary 009 T079 and T080 read (T080's ten seconds first, before anyone scrolls), and the run
    folder from which the development machine counts 010 T106's engagement against the last
    sitting's. The test plan's step 4.2 stops the review at the owner's token cap.
12. **008 T104: Retry.** Retry is on the error card ("The review stopped") only; with none, T104's
    Retry half is blocked and is recorded so (whether to amend the task for a review that ends
    cleanly is the owner's decision). When there is one, press it once: the add-in makes a new run
    folder and extracts again, and its `package.json`'s row and gap counts do not grow; the
    development machine compares the group keys the two runs judged. Record the setup time - the
    add-in, not the page, sends `POST /sessions`, so the pane's DevTools never shows it: from
    `session.started` to that request's `201` line in the backend log (the test plan's
    `Show-SetupTime`, step 4.3) - and the seconds from `session.started` to the first `text.delta`:
    `Get-Content "<run folder>\events.jsonl" | ConvertFrom-Json | Where-Object { $_.type -in 'session.started','text.delta' } | Select-Object seq,type,at`
    (the pair after the Retry's `session.started`).
13. **008 T103 and 009 T079: the small assembly, paid.** A pane review with the defaults. Pass: the
    report's input tokens at most **300,000** (SC-003's 0.3M; it is below 1.5 times every
    estimate of `small-assembly-a`, so it is the line); the finding and contact counts recorded as
    in step 11. The replay's requested figure, 459,000, assumes the model makes the recorded
    calls; the 0.3M assumes it does not repeat what the digest reported (the regrouped estimate),
    so a review that repeats checks fails T103 by design - record which calls repeated.
14. **009 T081, T083, T084.** Configuration switch (T081), chips and restore (T083), three open
    questions answered in one send (T084), each as its task text says; T084's resumed turn's
    first round input goes beside the pane's resume sentence.
15. **008 T106: the live Gemini test.** The key at a hidden prompt, never on a command line
    (PSReadLine keeps every command line in a history file), and `GOOGLE_API_KEY` cleared, since
    the test reads it first:
    ```powershell
    if (Test-Path Env:GOOGLE_API_KEY) { 'GOOGLE_API_KEY is set and would be used instead; cleared for this window'; Remove-Item Env:GOOGLE_API_KEY }
    $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host 'Paste the Gemini key' -AsSecureString)))
    cd "$R\reviewer"; uv run pytest tests/live/test_gemini_live_function_response.py -m live -rs -p no:warnings; cd $R
    Remove-Item Env:GEMINI_API_KEY
    ```
    Pass: `1 passed` and no `SKIPPED` line. A skip proves nothing; a refused key or an unreachable
    API fails with its own sentence and is setup, not the protocol failure. After a Ctrl+C, close
    the window to drop the key.
16. **Evidence.** Zip the whole run folders of steps 1 and 3 to 14 (their `tool-results\`
    included), the dump folders of step 2, the probe `--out` folder and the logs into the handover
    folder (runbook section 8); not `swreview handoff`, which leaves `tool-results\` out.
17. **The findings document**, in the handover folder: the Results table filled (every row
    `pass`, `fail` or `blocked`) and every step's record above, in order, with the commit and the
    versions at the top; no company value in it. The key audit runs again after it is written.
18. **009 T082: before and after the FR-023 fix,** last, SOLIDWORKS closed for each build:
    ```powershell
    git status --porcelain; git branch --show-current       # nothing, then main
    Copy-Item "$env:APPDATA\SwReview\settings.json" "$env:APPDATA\SwReview\settings.json.before-5.5"
    git checkout 9464b9e                                     # the parent of 3e86d47, the fix
    .\extractor\tools\update-workstation.ps1 -NoPull -SkipTests
    # SOLIDWORKS: review A, Model check on part J, Show in SOLIDWORKS on an A finding - which package did it resolve against?
    git checkout main
    .\extractor\tools\update-workstation.ps1 -NoPull
    git log --oneline -1; (Get-Item "$R\extractor\SwReview.AddIn\bin\x64\Release\net48\SwReview.AddIn.dll").LastWriteTime
    # the same three presses: Show in SOLIDWORKS selects A's entity
    ```
    Registration survives both rebuilds. The older build's own script is used for its build, and
    `-SkipTests` only there: it is built to be looked at, not shipped. That script has no
    `-SolidWorksRoot` and runs `git fetch origin` even with `-NoPull`; on a seat installed
    elsewhere, or when that fetch is refused, build the old commit with
    `dotnet build extractor\SwReview.sln -c Release "-p:SwRedist=$sw\api\redist"` instead, `$sw`
    the SOLIDWORKS install folder (the Python side needs nothing: its lock file is the same on both
    builds). After the return, the add-in DLL's time must be after the return build started; if
    the return stops at a gate, run it once more, then with `-SkipTests`, and if `dotnet build`
    fails, clear SwReview's boxes in Tools > Add-ins: never leave the seat on the older add-in (the
    test plan's step 5.5). Record both answers.

## 4. After the sitting, on the development machine

The findings document and the zipped folders arrive by hand; the owner reads the document and
commits it. Before 008 T101 is ticked, the returned run folders are scanned for the owner's profile
values (006 T100's audit half); 010 T104's Hole Wizard fields and 010 T106's engagement are counted
from the dump folder and the big assembly's run folder. 008 T105 replays each run folder;
009 T085 restores each through `GET /reviews/{run_id}`; the answers move into 011 research R4,
010 `research.md`, 008 research R5 and `docs/llm-efficiency-options.md`, 006 research R4 and 009
research R5. If T066 and T077 passed, the development machine sets each switch in a commit of its
own, editing the one pin test the task names, and 011 T095 goes into the next handover.
