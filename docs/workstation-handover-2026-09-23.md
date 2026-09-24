# Workstation handover: the sitting for features 008 to 011, in order

Written 2026-09-23 for the next sitting on a licensed SOLIDWORKS seat, which may be a fresh
machine: the pilot seat declared itself done (`docs/roadmap-2026-09-22.md`). Addressed to the
assistant operating the seat. `docs/workstation-runbook.md` is the standing manual; read it first
and keep its three rules: never commit or push per-machine state, never push `main`, close
SOLIDWORKS before building or registering. This document replaces the 2026-09-20 round-2
handover as the current work; it is one ordered list of every seat task of features 008, 009, 010
and 011, each with its command, what decides pass or fail, and where its record goes. The task
texts in `specs/00N-*/tasks.md` stay the source of truth: where this document and a task
disagree, the task wins and the difference is a finding.

**What the seat does not do.** It commits nothing but a findings document (runbook rule 2). Two
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
3. **A provider key** for the pane's Settings (the paid reviews), and **a Gemini key** for 008
   T106, which is set for one shell only.
4. **The documents the probes and reviews need**, named by the engineer before the sitting: the
   two recorded assemblies (008 T102 and T103 name them); a multi-sheet drawing with a revision
   table off its first sheet (011 T062, 006 T103); an assembly with the drawings of two of its
   parts and of one unrelated part (T063); the drawings `specs/011-drawing-context/contracts/probes.md`
   names (T064, T065); a part drawing and an assembly drawing whose callouts the engineer names
   beforehand (T066); a reviewed part whose same-name drawing exists and is closed (T077); a
   design with a candidate drawing and a part drawn twice (T067); a design with its drawing open
   (T068).

## 1. Install or update, then check

On a fresh machine, runbook sections 2 and 3 (prerequisites, clone, gate, registration from an
elevated prompt); on the old seat, section 4. Either way, non-elevated:

```powershell
cd <repo>
git log --oneline -1                                  # this document's commit or a later one
.\extractor\tools\update-workstation.ps1              # add -TokenizerFrom <file> or -SolidWorksRoot <root> as section 2 says
Set-Alias swreview-extract <repo>\extractor\SwReview.Extractor.Console\bin\x64\Release\net48\swreview-extract.exe
Select-String -Path $env:LOCALAPPDATA\SwReview\standards.yaml -Pattern '^version:'   # after step 1 below
```

Pass: the script ends at its health step with no step failed, and runbook section 6's seven
checks hold. Record the commit (`git rev-parse --short HEAD`) and the versions of section 2 at the
top of the findings document. Every `swreview-extract` command below needs the alias in the shell
it runs in; every `uv run` command runs from `<repo>\reviewer`.

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
section 8); the development machine moves each answer into the research file named.

1. **008 T101: the real profile.** Place the owner's file at
   `%LOCALAPPDATA%\SwReview\standards.yaml`; `Select-String` shows `version: 3`; runbook section
   5's check command reports no schema error. Then one pane review: its run folder's
   `session.json` holds a pre-run step for `check_standards` (quickstart Scenario 11 of 008). A
   version below 3 stops the sitting's paid reviews until the owner rewrites it. Record: the
   findings document.
2. **010 T103 to T106: the dumps.** For each recorded assembly, active in SOLIDWORKS:
   `swreview-extract dump --out <run root>\<date>-<assembly>-dump --meshes none`, then the check
   command in the Phase 13 note of `specs/010-mechanical-checks/tasks.md` on that folder. Pass:
   `mass_overridden read` equals `documents` and `mass_override gaps` is 0 (T103); every Hole
   Wizard hole has `Hole.wizard` and the fit and thread classes printed are recorded (T104);
   `model_dimensions` and `model_annotations` present where the models carry them, or 0 with no
   gap (T105); the named screws are fasteners, each with a shank face, and nothing else is (T106).
   The last line of each `extract.log`, `gated=...`, says which mass-override path answered:
   `GetOverrideOptions` in it means the first path failed somewhere. Record: the printed lines
   and the `gated=` line, for 010 `research.md`.
3. **011 T062: a multi-sheet drawing.** Once for the sitting,
   `New-Item -ItemType Directory -Force <handover folder>\probes`: every probe run writes its
   report there and never overwrites one. Open the drawing, then
   `swreview-extract probe drawings --out <handover folder>\probes --probe D1,D11`, then press
   Standards; then 006 T103, T105 and T107 as their task texts say. Pass: the probe report's
   answers and its gate log (no writer, activation, open or close member). Record: the
   `drawings-probe-<time>.txt` files stay in the `--out` folder; the answers go to 011 research
   R4 and 006 research R4.
4. **011 T063: discovery.** With the assembly and the three drawings open:
   `swreview-extract probe drawings --out <handover folder>\probes --probe D2,D3,D12,D13`, then a
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
8. **011 T077: the read-only open.** Beside the reviewed part whose same-name drawing is closed:
   `swreview-extract probe drawings --out <handover folder>\probes --probe D14`, then again with
   the drawing open. Pass: every answer T077 lists (the `OpenDoc6` integers, the active document
   and focus unchanged, the hidden views read, the file's size, write time and SHA-256
   unchanged, no save flag, released after the close, the counts). Then a pane review with the
   candidate, confirmed: the pane shows the host's refusal ("the read-only open of a confirmed
   drawing is not yet validated on a seat") and nothing opens - which is right while the switch
   is off. Record: the report file and the pane's sentence.
9. **011 T067: the questions.** A pane review of the design with a candidate drawing and a
   doubly-drawn part: the two questions appear, answering them records the answers, and the part's
   brief lists them. The brief's size:
   `cmd /c "uv run swreview drawing brief --package <run folder> --run <run folder> --document <doc id> > %TEMP%\swreview-brief.json"`
   then `(Get-Item $env:TEMP\swreview-brief.json).Length` (at most 6,000 bytes). `cmd /c` keeps the
   brief's bytes; a PowerShell redirect would re-encode them.
10. **011 T068, its unswitched half.** With the version 3 profile, review the design with its
    drawing open: the drawing is compared with the profile's drawing section, any finding names
    only the drawing's values, and the general tolerance's answer names the seat validation
    ("drawing callouts are read but not yet validated on a seat..."). The binding itself is T095.
11. **008 T102, 010 T107 and 009 T079, T080: the big assembly, paid.** A pane review with the
    defaults. Pass for T102: the report's input tokens, uncached plus cached, at most **995,853**
    (1.5 times the replay's "Requested, pane defaults" figure for `big-assembly`, 663,902, in
    `docs/llm-efficiency-options.md`); every detected interference group judged, as a finding or
    a contact; the rows in the run folder's `package.json`; the usage line and the report both
    show uncached and cached input as two numbers. Record the finding and contact counts; the
    comparison with the recorded findings by subject key is made on the development machine
    (T105). The same run is 010 T107's (contacts apart and outside "Start here", the joint, mass
    and hygiene findings before the first model turn, no model round spent on them) and the
    summary 009 T079 and T080 read.
12. **008 T104: Retry.** On step 11's run folder press Retry: `package.json`'s row and gap counts
    do not grow and the same groups are judged. Record the `POST /sessions` duration from the
    pane's DevTools Network tab, and the seconds from `session.started` to the first
    `text.delta`:
    `Get-Content <run folder>\events.jsonl | ConvertFrom-Json | Where-Object { $_.type -in 'session.started','text.delta' } | Select-Object seq,type,at`
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
15. **008 T106: the live Gemini test.**
    `$env:GEMINI_API_KEY = '<key>'; uv run pytest tests/live/test_gemini_live_function_response.py -m live -rs -p no:warnings; Remove-Item Env:GEMINI_API_KEY`.
    Pass: `1 passed` and no `SKIPPED` line. A skip proves nothing; a refused key or an unreachable
    API fails with its own sentence and is setup, not the protocol failure.
16. **Evidence.** Zip the whole run folders of steps 1 and 3 to 14 (their `tool-results\`
    included), the dump folders of step 2, the probe `--out` folder and the logs into the handover
    folder (runbook section 8); not `swreview handoff`, which leaves `tool-results\` out.
17. **The findings document**, in the handover folder: every step's record above, in order, with
    the commit and the versions at the top; no company value in it.
18. **009 T082: before and after the FR-023 fix,** last, SOLIDWORKS closed for each build:
    ```powershell
    git checkout 9464b9e                                     # the parent of 3e86d47, the fix
    .\extractor\tools\update-workstation.ps1 -NoPull -SkipTests
    # SOLIDWORKS: review A, Model check on part B, Show on an A finding - which package did it resolve against?
    git checkout main
    .\extractor\tools\update-workstation.ps1 -NoPull
    # the same three presses: Show selects A's entity
    ```
    Registration survives both rebuilds. The older build's own script is used for its build, and
    `-SkipTests` only there: it is built to be looked at, not shipped. That script has no
    `-SolidWorksRoot`; on a seat installed elsewhere, build the old commit with
    `dotnet build extractor\SwReview.sln -c Release -p:SwRedist=<root>\api\redist` instead.
    Record both answers.

## 4. After the sitting, on the development machine

The findings document and the zipped folders arrive by hand. 008 T105 replays each run folder;
009 T085 restores each through `GET /reviews/{run_id}`; the answers move into 011 research R4,
010 `research.md`, 008 research R5 and `docs/llm-efficiency-options.md`, 006 research R4 and 009
research R5. If T066 and T077 passed, the development machine sets each switch in a commit of its
own, editing the one pin test the task names, and 011 T095 goes into the next handover.
