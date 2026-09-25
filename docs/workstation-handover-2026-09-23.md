# Workstation handover: the sitting for features 008 to 011, in order

Written 2026-09-23 for the next sitting on a licensed SOLIDWORKS seat, which may be a fresh
machine: the pilot seat declared itself done (`docs/roadmap-2026-09-22.md`). Addressed to the
assistant operating the seat. `docs/workstation-runbook.md` is the standing manual; read it first
and keep its three rules: never commit or push per-machine state, never push `main`, close
SOLIDWORKS before building or registering. This document replaces the 2026-09-20 round-2
handover as the current work; it is one ordered list of every seat task of features 008, 009, 010
and 011, and of four earlier ones the owner added (decision 15A, 2026-09-24: 006 T101 and T102 in
step 2, 007 T059 and T060 in step 13), and of three items of feature 004 the owner added
(decision 18A, 2026-09-25: 004 T164 in step 19, the packages for 004 T003 in step 20, the probes
004 T033 to T039 in step 21), each with its command, what decides pass or fail, and
where its record goes. The task
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
development machine (runbook section 8, the test plan's step 6.5). It saves nothing in SOLIDWORKS: the
one write from the real files is the test plan's Pack and Go copy into `%TEMP%` for the
view-out-of-date probe (step 3.5), deleted at its step 6.0, and the plan fingerprints the real
files before and after; the re-modeler probes (step 21) build, save and delete throwaway parts of
their own inside the handover folder, never a real file. Two
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
   people and the cap for the big assembly's review are in the test plan's section 0.1. A
   "Before this review" panel is answered as the owner decided (decision 14A, 2026-09-24, not a
   default awaiting confirmation): write down its first line, press "Review available evidence",
   and never resolve or unsuppress a part (the test plan's step 4, item 1).
4. **The documents the probes and reviews need**, named by the engineer before the sitting (the
   test plan's section 0.2 gives each a letter and says what it must carry): the
   two recorded assemblies (008 T102 and T103 name them); a multi-sheet drawing with a revision
   table off its first sheet (011 T062, 006 T103); an assembly with the drawings of two of its
   parts and of one unrelated part (T063); the drawings `specs/011-drawing-context/contracts/probes.md`
   names (T064, T065); a part drawing and an assembly drawing whose callouts the engineer names
   beforehand, each with its SOLIDWORKS name (T066); a reviewed part whose same-name drawing
   exists and is closed (T077); a design with a candidate drawing and a part drawn twice (T067); a
   design with its drawing open (T068); and three to five real single parts the owner names for
   004 T003's dry run, one of them with a long feature tree (the test plan's letter P).

## 1. Install or update, then check

On a fresh machine, runbook sections 2 and 3 (prerequisites, clone, gate, registration from an
elevated prompt; the test plan's section 0.3); on the old seat, section 4. Either way,
non-elevated, and pull **before** running the script, so the script that runs is the one that
arrived (a seat older than 2026-09-24 has a script without `-TokenizerFrom`, `-SolidWorksRoot` or
the `swreview-extract:` health line). First the test plan's setup block, in every PowerShell
window: it sets `$R` (the checkout), `$H` (the handover folder, `<handover folder>` below) and the
`swreview-extract` alias, and defines the helpers its steps call. Then its steps 1.2 to 1.4:

```powershell
git status --porcelain; git branch --show-current     # nothing, then main
if (-not (Test-Path "$H\notes\commit-before.txt")) { git rev-parse --short HEAD | Set-Content "$H\notes\commit-before.txt" }
git fetch origin; git log --oneline HEAD..origin/main
git pull --ff-only origin main; "pull exit code: $LASTEXITCODE"
.\extractor\tools\update-workstation.ps1 -NoPull      # add -TokenizerFrom "<file>" or -SolidWorksRoot "<root>" as section 2 says
git log --oneline -1; Test-Path docs\workstation-results-2026-09-23.md   # the commit, then True: the results sheet is there
git merge-base --is-ancestor 8d308be HEAD; "holds 8d308be: $($LASTEXITCODE -eq 0)"   # True: the probe names each dimension (T066)
Select-String -Path "$env:LOCALAPPDATA\SwReview\standards.yaml" -Pattern '^version:'   # after step 1 below
```

Pass: `pull exit code: 0`, the script ends at its health step with no step failed, and runbook
section 6's seven checks hold. The script fetches first even with `-NoPull`, and says
`-NoPull: building what is checked out`; the test plan's step 1.3 says what each other line means.
Record the commit before and after and the versions of section 2 at the top of the findings
document, which the test plan starts at step 1.4. Every `swreview-extract` command below needs the
alias in the shell it runs in; every `uv run` command runs from `<repo>\reviewer`.

## 2. The order, and why

| Must come first | Before | Why |
|---|---|---|
| Step 1, the real profile (008 T101) | every Standards press and every paid review | an example or version 1 profile grades against nobody's standard, silently |
| Step 2, the dumps (010 T103 to T106) | step 11's review (010 T107) | T107 reads engagement the widened dump makes possible |
| Steps 3 to 6, the probes D1 to D13 | step 7 (011 T066) | T066 compares D6 and D8 with T064's D4 and D5 on the same drawing |
| Step 8's probe D14 | step 8's pane review (T077) | the pane half is read against the probe's answers |
| Step 11 (008 T102) | step 12 (T104) | T104 presses Retry on T102's run folder |
| everything else but step 21 | step 18 (009 T082) | it builds an older commit, then returns to `main` |
| everything, step 18 included | step 21 (004 T033 to T039), then only the handoff | a refuted PROBE-1 can leave a "Cannot reorder" box holding SOLIDWORKS, and PROBE-1 asks for one on purpose |

## 3. The script

Each step: the task, what to run, what decides it, and where the record goes. "The findings
document" is `pane-findings-<date>.md` in `%LOCALAPPDATA%\SwReview\handover\<date>\` (runbook
section 8), where the date is the handover folder's, the sitting's first day: the test plan copies
`docs/workstation-results-2026-09-23.md` there at its step 1.4, on day 1, once the update has
brought it (an older checkout has no such file before the pull), and its Results table takes one
row per step and task id. The development machine moves each answer into the research file named.

1. **008 T101 and 006 T100: the real profile.** Place the owner's file at
   `%LOCALAPPDATA%\SwReview\standards.yaml`; `Select-String` shows `version: 3`; the test plan's
   step 2.4 check, `uv run swreview check standards` on a `-standards` run folder with the placed
   profile, ends `exit code: 0` (no schema error). Then one pane review, the test plan's step 3.4:
   `Show-ReviewFacts`'s `pre-run tools:` line includes `check_standards` (its run folder's
   `session.json` holds that pre-run step; quickstart Scenario 11 of 008) and the report holds
   `standards.release`. A version below 3 stops the sitting's paid reviews until the owner rewrites
   it. Record: the findings document.
2. **010 T103 to T106: the dumps.** For each recorded assembly, active in SOLIDWORKS:
   `swreview-extract dump --out "<handover folder>\dumps\A" --meshes none` (then `B`), never under
   the run root, where the test plan's exporter (its step 6.2, `swreview handoff` on every folder
   there) would take a dump for a review, then the check command in the Phase 13 note of
   `specs/010-mechanical-checks/tasks.md` on that folder. Pass:
   `mass_overridden read` equals `documents` and `mass_override gaps` is 0 (T103); every Hole
   Wizard hole has `Hole.wizard` and the fit and thread classes printed are recorded (T104);
   `model_dimensions` and `model_annotations` present where the models carry them, or 0 with no
   gap (T105); the named screws are fasteners, each with a shank face, and nothing else is (T106).
   The last line of each `extract.log`, `gated=...`, says which mass-override path answered:
   `GetOverrideOptions` in it means the first path failed somewhere. Record: the printed lines
   and the `gated=` line, for 010 `research.md`. **006 T101 and T102** run on the same two
   assemblies, each right after its dump and still active: `swreview-extract probe standards`
   into `probe-standards-A.txt` (then `-B`) in the probe folder, which prints PROBE-1 (the
   exploded reads, per configuration and per sub-assembly), PROBE-2 (the nine appearance slots)
   and PROBE-3 (the visibility reads beside the suppression) for every component. The engineer
   notes beforehand which components are transparent, overridden, hidden, suppressed or hidden in
   a display state, and finds each by the path the probe prints (the tree's `bracket<3>` inside
   `sub<2>` is `sub-2/bracket-3`); a kind neither assembly has is blocked, never made. Pass: the
   probe's gate log (no mutating member, refusal, activation, open or display change) and every
   kind found and read (the test plan's step 3.1). Record: component ids and answers only; the
   development machine moves the answers into 006 research R4 and flips `TRANSPARENCY_POLARITY`.
3. **011 T062: a multi-sheet drawing.** Every probe run writes its report in
   `<handover folder>\probes`, which the test plan's setup block makes, and never overwrites one.
   Open the drawing, then
   `swreview-extract probe drawings --out "<handover folder>\probes" --doc "<drawing>" --probe D1,D11`,
   then press Standards check, then
   `swreview-extract probe standards --doc "<drawing>"` into a file in the same folder (the test
   plan's step 3.2); then 006 T103, T105 and T107 as their task texts say (T107's not-loaded model
   is the test plan's step 3.5, on a drawing opened in Detailing mode). Pass: the probe report's
   answers and its gate log (no writer, activation, open or close member). Record: the
   `drawings-probe-<time>.txt` files stay in the `--out` folder; the answers go to 011 research
   R4 and 006 research R4.
4. **011 T063: discovery.** With the assembly and the three drawings open:
   `swreview-extract probe drawings --out "<handover folder>\probes" --doc "<assembly>" --probe D2,D13`,
   then `--probe D3,D12` with each drawing as `--doc` (D3 and D12 read a drawing, so on the
   assembly they read nothing), then `--probe D13` on the vault-view part whose drawing is not
   cached (the test plan's step 3.3), then a pane review (its step 3.4). Then, as its step 3.5
   says, `--probe D3` on the six-sheet drawing with sheet 3 active, and `--probe D12` on a Pack and
   Go copy in `%TEMP%` whose part was changed, and again on a drawing opened in Detailing mode.
   Pass: the two part drawings are read and the unrelated one is not; nothing was opened; the
   candidate check neither fetched nor stalled. Record: discovery's time, the review's
   `drawing phase` line (`Show-ReviewFacts`), and D13's `File.Exists` time and whether the local
   copy changed.
5. **011 T064: D4, D5, D8 and D11** on the drawings `contracts/probes.md` names, with
   `--probe D4,D5,D8,D11`. If D4 shows `units_decimal_places_raw` governs a document-precision
   dimension, that is a finding for the development machine (T064's one-line change), not an
   edit here.
6. **011 T065: D1, D6, D7, D9 and D10** with `--probe D1,D6,D7,D9,D10` on each drawing that
   carries the callouts, symbols and tables, its part open. Pass (the test plan's step 3.7): each
   count of D7, D9 and D10 equals the engineer's own count, written before the run, or D1 lists a
   gap of that kind; a count below it with no such gap is a value silently absent, a fail.
7. **011 T066: the named callouts.** On the part drawing and on the assembly drawing whose
   callouts the engineer named, each with its part open, one run each: `--probe D4,D5,D6,D8`
   (the test plan's step 3.8). Each named callout is found by the name and value D6 and D8 print
   on its line (`contracts/probes.md` section 1, amended 2026-09-24; the value is the nominal
   `native_dimension` uses); one found on no line, or on several, is recorded `not decidable` and
   keeps the switch off. Pass: every named callout found, with the value it must have, and tied
   to the right hole (D6's face is a cylinder of half the named hole's diameter); D8 reads
   `FullName equal true`, D5 `; agree true`, and D4's unit and decimals are the ones the engineer
   named. Record the verdict and every mismatch as the check that failed, never a dimension's
   name, view, value or radius (the probe report keeps them, in the handover folder); do **not**
   change the switch.
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
    `session.started` to that request's `201` line in the backend log - and the seconds from
    `session.started` to the first `text.delta`, as the test plan's step 4.3 reads them, with
    `$run` the big assembly's run folder: `Show-SetupTime $run` and `Show-ReviewFacts $run`'s last
    line. A Retry makes a new run folder, so after one both run again on that folder.
13. **008 T103 and 009 T079: the small assembly, paid.** A pane review with the defaults. Pass: the
    report's input tokens at most **300,000** (SC-003's 0.3M; it is below 1.5 times every
    estimate of `small-assembly-a`, so it is the line); the finding and contact counts recorded as
    in step 11. The replay's requested figure, 459,000, assumes the model makes the recorded
    calls; the 0.3M assumes it does not repeat what the digest reported (the regrouped estimate),
    so a review that repeats checks fails T103 by design - record which calls repeated. The same
    review is **007 T059**'s: when it ends, the pinned Start here panel's rows are the finding ids
    `report.md`'s "Start here" lists, in its order (`Show-StartHere $run`, the test plan's step
    4.1); Model check and Standards on part J show their Start here block above the chips, with
    the ids of their own folders' reports (its steps 5.1 and 5.2). And it is **007 T060**'s timed
    run: the engineer who knows the design gives the baseline, the seat notes supervision,
    verification and false-alarm minutes, and `swreview timing` records the four on its run
    folder only after a backend restart (the test plan's step 4.5, item 4), since a backend still
    holding the review could save over them; its `session.json` carrying the baseline is the
    evidence.
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
16. **Evidence.** Zip the whole run folders of steps 1, 3 to 14 and 20 (their `tool-results\`
    included), the dump folders of step 2, the probe `--out` folders (step 21's three among them)
    and the logs into the handover
    folder (runbook section 8; the test plan's step 6.3); not `swreview handoff`, which leaves
    `tool-results\` out. The test plan also runs that exporter on each review (its step 6.2), for a
    small key-masked summary beside the evidence, never in its place.
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
    `-SkipTests` only there: it is built to be looked at, not shipped. Every version of the script
    runs `git fetch origin` first, even with `-NoPull`, and on the detached checkout says
    `on 'HEAD' with -NoPull: building what is checked out`, which is expected; the older one has no
    `-SolidWorksRoot`. On a seat installed elsewhere, or when that fetch is refused (on the way
    there or back), build with
    `dotnet build extractor\SwReview.sln -c Release "-p:SwRedist=$sw\api\redist"` instead, `$sw`
    the SOLIDWORKS install folder (the Python side needs nothing: its lock file is the same on both
    builds). After the return, the add-in DLL's time must be after the return build started; if
    the return stops at a gate, run it once more, then with `-SkipTests`, and if `dotnet build`
    fails, clear SwReview's boxes in Tools > Add-ins: never leave the seat on the older add-in (the
    test plan's step 5.5). Record both answers.
19. **004 T164: FeatureWorks, for the record.** Feature 004's import path is on the back burner
    (its spec, owner decision 2026-09-19); whether the seat has FeatureWorks, the add-in that
    recognises features in an imported solid, informs the feasibility probe if the owner reopens
    that path. Read only: the test plan's step 1.7 prints one registry line (installed, listed as
    an add-in, start-up flag), then Tools > Add-ins is looked at, FeatureWorks's Active and
    Start Up boxes noted and the dialog closed with Cancel, and Help > About names the product
    (Standard, Professional or Premium; FeatureWorks ships with all three, 004 T149, so the boxes
    are the answer). Any answer passes; it is a record. Record: the line, the two boxes and the
    product, in the findings document.
20. **004 T003's packages: Model check on the owner's parts.** The three to five real parts the
    owner names (the test plan's P-1 to P-5, one with a long feature tree), each opened alone and
    Model checked (its step 5.1): each check folder's `package.json` is a current ModelCheck-profile
    package, the input 004 T003's dry run needs. The folders stay under the run root and travel in
    step 16's zip; the development machine runs `swreview remodel plan` over them and writes counts
    only. Record: each part's letter, its folder's stamp and letter, and the counts under its
    grade; no part name, number, feature name or folder name.
21. **004 T033 to T039: the re-modeler probes,** last before the handoff, SOLIDWORKS running with
    no document open (the probe refuses otherwise), on the current build. Three runs, each into
    its own folder, since a second run into the same folder overwrites the first one's answers
    file; first the probes that never reorder, then the three reorders no watchdog times, then
    PROBE-1 alone, which provokes a "Cannot reorder" box with the flag clear on purpose:
    ```powershell
    swreview-extract probe remodel --probe PROBE-2,PROBE-4,PROBE-6,PROBE-7,PROBE-8,PROBE-9,PROBE-10,PROBE-11,PROBE-12,PROBE-13,PROBE-21 --out "$H\probes\remodel-no-reorder" --acknowledge-throwaway-part; "exit code: $LASTEXITCODE"
    swreview-extract probe remodel --probe PROBE-3,PROBE-5,PROBE-20 --out "$H\probes\remodel-reorder" --acknowledge-throwaway-part; "exit code: $LASTEXITCODE"
    swreview-extract probe remodel --probe PROBE-1 --out "$H\probes\remodel-probe-1" --acknowledge-throwaway-part; "exit code: $LASTEXITCODE"
    ```
    After each, `Show-RemodelLedger` on its folder prints each probe's id, blocking flag, verdict
    (`verified`, `refuted` or `unresolved`) and reason. A message box is answered only after 30
    seconds (PROBE-1 times each of its two tries for 5 seconds), with OK; a run that hangs is recovered as the test
    plan's "If SOLIDWORKS stops answering" says and is not run again. Each run turns three
    SOLIDWORKS options off and puts them back when it ends; the plan notes them before the runs
    and checks them after (its step 5.6). Pass per probe: `verified`; `refuted` is a fail that is
    the answer the probe exists for, `unresolved` or a run that did not finish is blocked. Record:
    per run its exit code and `probes:` line, each `BLOCKING` line up to its colon, every box,
    the verdicts; the answers files `capabilities\remodel-<version>.yaml` and the logs stay in
    their folders under `<handover folder>\probes` and travel with it.

## 4. After the sitting, on the development machine

The findings document and the zipped folders arrive by hand; the owner reads the document and
commits it. Before 008 T101 is ticked, the returned run folders are scanned for the owner's profile
values (006 T100's audit half); 010 T104's Hole Wizard fields and 010 T106's engagement are counted
from the dump folder and the big assembly's run folder. 008 T105 replays each run folder;
009 T085 restores each through `GET /reviews/{run_id}`; the answers move into 011 research R4,
010 `research.md`, 008 research R5 and `docs/llm-efficiency-options.md`, 006 research R4 and 009
research R5. If T066 and T077 passed, the development machine sets each switch in a commit of its
own, editing the one pin test the task names, and 011 T095 goes into the next handover. For
feature 004: `swreview remodel plan` runs over each P folder's `package.json` for T003, counts
only and each part by its letter, into `specs/004-resilient-remodeler/phase0-decision.md`
section 4, replacing 004 T148's provisional counts; the three answers files of step 21 give T033
to T039 their verdicts, recorded as quickstart Scenario 4 says; step 19's record ticks T164. A
refuted blocking probe goes to the owner. The stage-1 runs, 004 T135 to T141, also wait on
004 T152 to T160, the production seat adapter and its wiring (decision 17A), before a later
sitting can run them.
