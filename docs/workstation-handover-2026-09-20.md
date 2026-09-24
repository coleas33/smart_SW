# Workstation handover, round 2: what to test and what to fix next time

Written 2026-09-19 for the next session on the pilot workstation, after the packet that
came back that day (`docs/pane-findings-2026-09-19.md`, `docs/task-a-2026-09-19.md`,
`docs/feature-request-resolve-lightweight.md`). Addressed to the assistant operating the
seat. `docs/workstation-runbook.md` is the standing manual; read it first and keep its three
rules: never commit or push per-machine state, never push `main`, close SOLIDWORKS before
building or registering. The previous round's manual, `docs/workstation-handover-2026-09-19.md`,
still holds for the command lines of Tasks C and D; this document says what changed, what to
fix on the seat before testing, what to test, and what to send back.

## 1. What changed in this build

- **The three tabs are reworked.** Review, Model check and Standards now show "Start here" as
  numbered cards, every finding or rule as one line with a Details fold, the transcript
  folded to a count of tool calls and rounds (findings, evidence requests and errors stay
  visible), coverage as a "Not reached" fold, and colour by bucket. Nothing was removed; it
  moved into folds.
- **Lightweight components are now said out loud.** When an instance was not read, the
  Review status line says "Reviewing 4 components, 2 not read (lightweight or suppressed)",
  the report's Summary carries a "Not examined" line naming the instances, and both check
  tabs show the same sentence above "Start here". Nothing is resolved; the seat is read as
  found.
- **`update-workstation.ps1` knows about the `local` lane.** On any branch but `main` it
  stops with a message instead of failing a fast-forward; merge GitHub in by hand and run
  it with `-NoPull`.
- **Recorded from your packet:** Task A passed; the two lever 6 studies are in
  `docs/llm-efficiency-options.md` under "Measurements outside the ledger", with the decision
  that command-line studies may hold `--lever parallel_tool_calls` on in both arms from now
  on. The pane default stays off.

## 2. Update, on the lane

```powershell
cd <repo>
git fetch origin
git merge origin/main                    # the lane keeps its own commits; GitHub comes in by merge
.\extractor\tools\update-workstation.ps1 -NoPull
git log --oneline -1                     # this document's commit or a later one
```

Then runbook section 6 (health checks). The five-tab check stands; the Ask tab stays hidden.

## 3. Fix on the seat before testing

1. **The standards profile is the example file.** Every Standards verdict from the seat is
   meaningless until the real profile is in place. The owner has it on the development
   machine at `%LOCALAPPDATA%\SwReview\standards.yaml`; it travels by hand, never through git.
   Ask the owner for it before Task C; confirm with runbook section 5's check command, and
   confirm the two false unresolved rows from the packet (`material_assigned` on `AsBuilt`,
   `data_card_complete` on the `EX-####-??` pattern) are gone.
2. **Name the flaky test.** Run the add-in suite with its output captured, so a red gate is
   never anonymous again:
   ```powershell
   dotnet test extractor\SwReview.sln -c Release --no-build --nologo --logger "trx;LogFileName=addin.trx" 2>&1 | Tee-Object -FilePath $env:LOCALAPPDATA\SwReview\handover\<date>\dotnet-test.log
   ```
   If one test fails and passes on re-run, put its name and the `.trx` in the packet.
3. **Know the load state before every run.** In the FeatureManager, note which components
   show as lightweight (the feather icon). Record it beside each run folder name in your
   findings document; it decides what the review can see.

## 4. Task A2: the reworked tabs

With the small assembly open, run Review, then Model check on the part, then Standards.
On each tab confirm, and say in the findings document:

- "Start here" is a numbered card list with a bold headline and a coloured stripe; the
  reason chip reads what `report.md`'s section says; pressing a card scrolls to the
  matching finding or rule and lights it.
- Every finding on Review is one line (id, status and severity chips, check id) plus a bold
  title; Details opens the fold with Affects, Requirement, Inputs, Calculation, Sources and
  the Accept / Reject / Defer group; the disposition sentence appears after a press.
- The transcript header counts tool calls and rounds while the run streams, and the
  Transcript button unfolds the calls and the model's prose.
- "Not reached" is folded with its counts on one line and opens to the coverage buckets.
- On the check tabs the count chips are filled in their colour when pressed, the rule rows
  carry a badge and a bold statement, and "All 16 checks" on Standards is one folded line.
- Anything cut off, overlapping or unreadable at the pane's width, with the width in pixels
  (drag the pane narrower to about 300 px and look again).

Screenshots of the pane are welcome in the handover folder, never in the repository.

## 5. Task E: the lightweight warning, both ways

1. With both dowel pins lightweight (as they were on 2026-09-19), press Review. Before the
   first model round, the status line must read
   `Reviewing 4 components, 2 not read (lightweight or suppressed) (N gaps).`
   When the session ends, `report.md`'s Summary carries
   `- Not examined: 2 of 4 component instances were not read: ...` naming both pins with
   their state, and Model check and Standards show the same sentence above "Start here".
2. In SOLIDWORKS, set both pins to Resolved (right-click the component, Set Lightweight to
   Resolved) and press Review again. The warning must be absent everywhere, and "Start
   here" should open with the two `interference.static` rows that 2026-09-18 produced.
   Record both run folder names; the pair is the evidence that the warning tells the truth
   and that the review changes with the load state.

## 6. Tasks C and D: the gate, with the key

Both are unchanged from `docs/workstation-handover-2026-09-19.md` sections 5 and 6, with two
amendments: hold `--lever parallel_tool_calls` on in **both** arms of Task D (the decision
recorded from your packet), and keep the study folder under the handover folder, not under
`benchmarks/studies/`. Task C needs the real profile from section 3.

## 7. Task F: the re-modeler probes

Feature 004 stops at its Phase 2 probes, which nobody has run: whether SOLIDWORKS 2024 lets
the executor reorder a feature without a message box, what units the equation manager
returns, whether a custom-property tag round-trips, and how accurately mass properties
measure a known solid. This build carries the command and all fifteen probe bodies. With
SOLIDWORKS running and **no document open**:

```powershell
cd <repo>\reviewer
swreview-extract probe remodel --out "$env:LOCALAPPDATA\SwReview\handover\<date>\remodel-probes" --acknowledge-throwaway-part
```

It builds a throwaway part in that folder, never touches a document of yours, runs the
fifteen probes and writes `capabilities\remodel-<version>.yaml` with one verdict each
(`verified`, `refuted`, `unresolved`) and the raw readings behind it. Follow
`specs/004-resilient-remodeler/quickstart.md` Scenario 4 for what each verdict means. Put
the ledger and the command's console output in the packet; the seven blocking probes
(1, 2, 3, 4, 8, 12, 13) are what decide whether stage 1 can run on a real part next round.
If a probe hangs, the watchdog reports it as unresolved after its timeout; say so rather
than killing SOLIDWORKS. Add `--keep-part` if you want the throwaway part left behind for
the owner to look at.

## 8. What to send back

One dated findings document in the shape of the last ones, plus a handover folder holding,
for every run folder you name: `package.json`, `session.json`, `attention.json`, `report.md`
and `events.jsonl`. The reader, the timing command and the policy read-through all work
from `session.json`; a folder with only the package cannot be replayed. Also:

- Task E's two run folders, and the FeatureManager load state for each.
- The `.trx` and log from section 3 if any test failed.
- Task D's `ledger.md` and six run folders.
- **A second design.** Every adoption decision is blocked on the one-package set. Ask the
  engineer for one more assembly with two or three defects they already know about, dump it
  with Review, and write the known defects down in the shape of
  `benchmarks/answer_keys/cover-blind-tap.json`. That file and the dump are the held-out
  package the ledger needs; the owner scrubs the paths and commits it.
- The re-modeler ledger from Task F when it ran.

Run folders of real designs carry vault paths: they go in the handover folder and never in
a commit. The findings document names folders and carries no vault path, library folder,
property name or export-control phrase.

## 9. Never

- `git push origin main`, or a commit touching the run root, the logs, the settings file or
  the profile.
- Editing the standards profile to make a check pass; a wrong profile is a finding.
- Building or registering with SOLIDWORKS open.
- Turning the Ask tab back on.
