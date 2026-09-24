# Workstation handover, 2026-09-19: what to do with this build

Addressed to the assistant operating the pilot workstation. `docs/workstation-runbook.md` is
the standing manual (install, update, profile, health checks, how findings come back); read it
first and follow its three rules throughout: never commit or push per-machine state, never push
`main`, close SOLIDWORKS before building or registering. This document is the work for this
build, in order, with what to record for each step. When a step fails, stop that step, keep
the evidence, and carry on with the next one that does not depend on it.

Feature 007 (`specs/007-attention-policy-gate/`) landed on `main` today. Everything that could
be built and tested without a SOLIDWORKS seat or a provider key is done; the five tasks left
(T059 to T063 in its `tasks.md`) are the ones only this machine can do. Tasks A and B need
the seat only. Tasks C and D also need a provider key in the pane's settings or the
environment, and C needs the standards profile from runbook section 5.

## 1. Update and confirm the build

```powershell
cd <repo>
.\extractor\tools\update-workstation.ps1        # SOLIDWORKS closed; add -Register on a first install
git log --oneline -1                             # this document's commit, or a later one
```

Then runbook section 6 (health checks) in full. Two of them changed with this build:

- The pane still shows **five** tabs: Review, Extract, Model check, Remodel, Standards. There is
  no Ask tab and the Codex CLI is still not needed.
- After any review or check, the run folder holds a further file, `attention.json`, beside
  `session.json`, `report.md` and (for checks) `check.json`. Its absence after a run that
  ended is a bug to report.

Confirm the profile is in place (runbook section 5): `Test-Path $env:LOCALAPPDATA\SwReview\standards.yaml`
must print `True` before Task C, unless the settings file's `standards_profile_path` points
somewhere else, in which case test that path.

## 2. What is new in this build, in this machine's terms

- **"Start here"**: every `report.md` now opens its findings with a section of the five
  findings a fixed rule put first. Checks that need engineering judgement come first
  (interference, fit, fastener, hole), then rebuild breakers, then interface, manufacturing,
  unclassified, discipline and hygiene classes; waived and decided findings sort last but
  are never removed.
  The rule is code, versioned `attention_policy_v1`; no model contributes to the order.
- **The same rows on three tabs**: above the bucket chips on Model check and Standards, and in
  a panel above the Review transcript once a session ends.
- **`uv run swreview attention <run folder>`** prints the order and the nine key values behind
  every row. It writes nothing. Run it from `<repo>\reviewer`.
- **`uv run swreview timing <run folder> --baseline M --supervision M --verification M --false-alarms M`**
  records the engineer's minutes against any run folder and prints the net figure into the
  report's Timing section. Also from `<repo>\reviewer`.
- **`--lever procedural_gate`** on `swreview review`, off by default: the deterministic checks
  run before the model's first turn and the model's first user message is their ranked brief.
  With `--standards-profile <yaml>` the sixteen release checks run inside the same review.

## 3. Task A: the panel matches the report (T059)

With the small assembly open, the dowel-pin one (the one reviewed on 2026-09-18):

1. Press **Review** and let the session run to its end. When "The session ended." appears,
   a **Start here** panel must appear above the transcript with up to five rows, each showing
   a finding id, a check id and a reason.
2. Open the run folder (`Documents\SwReview\runs\<stamp>-...` by default, or the run root in
   the pane's settings) and read the `## Start here` section of `report.md`. The ids, in
   order, must be the panel's ids in order.
3. From `<repo>\reviewer`, `uv run swreview attention "<that run folder>"` must print the
   same ids in the same order, and the folder's files must not change (compare
   `Get-ChildItem "<that run folder>" | Select-Object Name, Length, LastWriteTime` before
   and after).
4. Press **Model check** and then **Standards** on the same document. On both tabs the rows
   sit above the chips, and each tab's run folder has a `report.md` whose "Start here" lists
   the same ids the tab shows.
5. Press **Review** again and stop it early with the Stop control. The panel from step 1
   must be gone; when this second session ends, a panel for *it* appears.

Record: the run folder names, the five ids in order from the panel and from the report, and
whether any of the five checks above failed and how. The expected order for this assembly on
2026-09-18 was the two `interference.static` rows, `rms.assembly.mates_to_reference_geometry`,
`rms.sketches.fully_defined`, `rms.grouping.all_features_in_a_group`; a different order is
not by itself a bug (the findings may differ), but the panel and the report disagreeing is.

## 4. Task B: minutes after every pilot run (T060)

From now on, after each review the engineer reads, record four numbers on its run folder:

| Input | What it means |
|---|---|
| `--baseline` | the minutes the engineer estimates the same review would take unassisted |
| `--supervision` | minutes spent starting, watching and steering the run |
| `--verification` | minutes spent checking the findings against the model and drawings |
| `--false-alarms` | minutes spent on findings that turned out to be wrong |

```powershell
cd <repo>\reviewer
uv run swreview timing "<run folder>" --baseline 45 --supervision 6 --verification 9 --false-alarms 2
```

Net saved minutes is derived, never typed; the command refuses a negative number naming the
field; the report's Timing section then prints the figure. Check folders take the same
command. The first real `session.json` carrying a baseline is the evidence the pilot has
been missing; note the folder name in the findings document.

## 5. Task C: the gate's wall clock (T061, needs a key and the profile)

The number that decides whether the gate belongs in the pane is the seconds between the
session starting and the model's first word.

```powershell
cd <repo>\reviewer
$pkg = "<a folder holding a package.json dumped from the small assembly>"   # a Review run folder is one
foreach ($i in 1,2,3) {
  $run = "$env:TEMP\gate-run-$i"                    # one folder per run: events.jsonl is append-only
  uv run swreview review $pkg --out $run --lever procedural_gate `
    --standards-profile $env:LOCALAPPDATA\SwReview\standards.yaml
  $events  = Get-Content "$run\events.jsonl" | ForEach-Object { $_ | ConvertFrom-Json }
  $started = ($events | Where-Object type -eq 'session.started' | Select-Object -First 1).at
  $first   = ($events | Where-Object type -eq 'text.delta'      | Select-Object -First 1).at
  "run $i : $(([datetime]$first - [datetime]$started).TotalSeconds) s"
}
```

Record all three numbers and the model id from the `session.started` event. Then say
whether the standards checks ran: in `report.md`'s `## Coverage`, a skipped row named
`prerun.standards` means they did not, and its reason is one of four (no profile was
configured; the profile could not be loaded; the package was not dumped with the standards
phases, which a package the pane dumped for Review has; the root document cannot be graded).
The same sentence appears as `standards: ...` in the model's first user message, which is
in `events.jsonl`, not in the report. The owner records the result in research R5.

## 6. Task D: six alternated runs (T062, needs a key)

The protocol is `specs/005-llm-efficiency/contracts/ab-harness.md` section 2: three
repetitions per arm, alternated off, on, off, on, off, on, each its own command. The pilot set
holds one package with `held_out: false`, so `benchmark run` refuses unless told the set is
too small; that flag is written into every row the study produces, so the row can never be
read as a gate. That is expected for this build.

The study folder lives **outside the repository**, under the handover folder: the ledger
tests regenerate `docs/llm-efficiency-options.md` from whatever sits under
`benchmarks/studies/`, and a row carrying the too-small override makes the check exit 1, so
a study committed there would stop the next `update-workstation.ps1` at its test gate. Pin
the model and the effort on every line, as the protocol requires; the 2026-09-18 pane runs
used `gpt-5.6-luna` at `high`.

```powershell
cd <repo>\reviewer
$set   = "../benchmarks/sets/pilot.json"
$keys  = "../benchmarks/answer_keys"
$out   = "$env:LOCALAPPDATA\SwReview\handover\2026-09-19\studies\lever11-openai"
$model = "<the model id the pane uses>"
foreach ($rep in 1,2,3) {
  uv run swreview benchmark run --set $set --out "$out\off-$rep" --provider openai `
    --model $model --effort high `
    --study procedural_gate --arm off --rep $rep --i-know-the-set-is-too-small
  uv run swreview benchmark score "$out\off-$rep" --answer-keys $keys
  uv run swreview benchmark run --set $set --out "$out\on-$rep" --provider openai `
    --model $model --effort high --lever procedural_gate `
    --study procedural_gate --arm on --rep $rep --i-know-the-set-is-too-small
  uv run swreview benchmark score "$out\on-$rep" --answer-keys $keys
}
$runs = Get-ChildItem -Directory $out | ForEach-Object { $_.FullName }   # PowerShell does not expand * for uv
uv run swreview benchmark compare @runs --out $out
uv run swreview audit-secrets $out
```

`compare` exits 1 on the one-package set by design, after writing `ledger.json` and
`ledger.md` into `$out`; read `ledger.md`, not the exit code. An exit 1 that wrote no
`ledger.md` is a real failure: read the error. What the row must show: the lever counter
named "check_fit and check_axial_stack calls per run (must not fall)" with an empty
`fell_in_runs`, and a median net saved minutes column carrying `n=`. `audit-secrets` must
print one line beginning `none:` and exit 0.

Do not run `compare --into` against the committed document and do not commit the study
folder: hand back `ledger.md` and the six run folders in the handover zip (runbook section
8), and the owner decides how the row is recorded. The benchmark package is fictional, so
the folders carry no company value, but `ledger.md` names this machine's absolute paths; say
so in the findings document. `benchmark run` takes no `--standards-profile`, so every
on-arm brief carries the line `standards: no profile was configured for this review`; that
is the protocol for now, not a defect.

## 7. Not yet: the pane default (T063)

Nothing to do on this machine until Task D's row is in the document and the benchmark set
has a held-out package. The gate stays off in the pane; do not edit `ChatServer._start_review`.

## 8. Handing back

One dated findings document, in the shape of `docs/pane-findings-2026-09-18.md`, with:

- the commit (`git rev-parse --short HEAD`) and the versions from runbook section 2;
- Task A: folder names, the ids in order from the panel and from the report, any mismatch;
- Task B: the first run folder that carries a baseline, and the four numbers;
- Task C: the three wall-clock numbers, the model id, the standards line;
- Task D: the study folder in the handover zip, the ledger row as rendered, `fell_in_runs`,
  the `n=` column;
- anything that broke, with log lines from `%LOCALAPPDATA%\SwReview\logs\addin.log` and the
  newest `backend-*.log`, and the run folder names.

Run folders of real designs are zipped into `%LOCALAPPDATA%\SwReview\handover\2026-09-19\`
and never committed; the document names them and carries no vault path, library folder,
property name or export-control phrase.

## 9. Never

- `git push origin main`, or a commit touching the run root, the logs, the settings file or
  the profile.
- Editing the standards profile to make a check pass; a wrong profile is a finding.
- Running `update-workstation.ps1` or `dotnet build` with SOLIDWORKS open.
- Turning the Ask tab back on (`TaskPaneControl.AskTabShown`): it is off for the pilot.
