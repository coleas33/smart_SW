# Workstation test plan: the sitting for features 008 to 011

Written 2026-09-23 for the engineer who runs the next sitting on a licensed SOLIDWORKS seat. You do
not need to be a developer to follow it. Every step says what to do, gives the exact command to
paste, says what to look at, and says what counts as a pass and what counts as a fail. Write each
result in the findings document (step 6.4) under the step's number.

Each step carries the task ids it answers in square brackets, with the feature in front, for
example **[011 T062]**: that is the row of `specs/011-drawing-context/tasks.md` the development
machine ticks from your result. The plan was built from what is on `main` with it: every seat task
(`[W]`) of features 008, 009, 010 and 011, and `docs/workstation-runbook.md`. The assistant's
version of the same sitting, with the reasons for its order, is
`docs/workstation-handover-2026-09-23.md`. Where this plan and a task text disagree, the task wins;
write the difference down as a finding.

## The rules for the whole sitting

1. **Save nothing in SOLIDWORKS.** When SOLIDWORKS asks whether to save, choose **Don't Save**. The
   product only reads your files, and this sitting proves it, so nothing else may change them
   either.
2. **Edit no file in the checkout, and commit or push nothing** except the findings document at
   step 6.5, and only as that step says; step 5.5 switches the checkout to an older build and
   back, and that is the one other thing done to it. A wrong result is a finding to write down,
   never something to fix at the seat. The standards profile is the owner's: the one line you may
   change is the vault location (step 2.2).
3. **Close SOLIDWORKS before building** (steps 1 and 5.5).
4. **Keys go in two places only**: the OpenAI key in the pane's Settings (step 2.5), the Gemini key
   at the prompt of step 5.4. Never in a file, on a command line, in a chat or in the findings
   document.
5. **In the findings document, call documents by their letters** (section 0.2), not by their file
   names; the two recorded assemblies may also be called the small assembly (A) and the big
   assembly (B), never by their numbers: the findings document is committed, and no committed
   file names them (the owner's decision 11B). No vault path, folder name, property name or
   value, sheet format or template name goes in it.
6. **Do not click or type while a probe runs.** Probe D14 checks that the window in front and the
   active document do not change; your own click would fail it.
7. **A step that fails**: record what the step says to record, then go on to the next step,
   unless the step says to stop.

## How long it takes

About **9 hours at the seat**, best planned as two days: day 1 steps 1 to 3, day 2 steps 4 to 6.
Keep SOLIDWORKS open from step 4.1 to step 4.5 on day 2: the review chips of steps 4.4 and 4.5
live only as long as the SOLIDWORKS session.

| Step | What | Estimate |
|---|---|---|
| 1 | Update, gates, health checks (registration only on a new machine) | 50 min |
| 2 | Profile and key | 20 min |
| 3 | Dumps and probes D1 to D14, with one pane review | 3 h 30 min |
| 4 | The pane reviews | 3 h |
| 5 | Model check, Standards and Remodel, the Gemini test, the older build | 1 h 30 min |
| 6 | Handoff | 40 min |

Most of step 3 is opening the right documents; with the documents of section 0.2 found and noted
before the sitting it can be an hour shorter. The paid model use is roughly 3 to 4 million input
tokens over about ten reviews, most of them small, against the 12.4 million of the one review of the
big assembly at the last sitting; this is an estimate from the replay's figures, not a measurement.

## 0. Before the sitting

### 0.1 What the owner brings

1. **This plan on GitHub.** The seat updates from GitHub (`origin/main`); the commit that added
   this plan, or a later one, has to be pushed before the sitting.
2. **The real standards profile at version 3**, carried by hand (step 2 says what it must hold). It
   never goes into the repository or into the findings document.
3. **The o200k_base vocabulary file** `fb374d419588a4632f3f557e76b4b70aebbca790`, from the
   development machine's `%LOCALAPPDATA%\SwReview\tokenizer\`, in case the seat's web filter blocks
   its download (step 1.3).
4. **An OpenAI key** for the pane's reviews, and **a Gemini key** for step 5.4.

### 0.2 The documents, named before the sitting

Find these before the sitting and write the list, letter by letter with the file each letter
means, in `notes\documents.txt` in the handover folder (the setup block below makes the folder;
`notepad "$H\notes\documents.txt"` opens the file). That file stays in the handover folder and
travels by hand; it is never pushed.

| Letter | What it must be | Used by |
|---|---|---|
| A | the small assembly of the last sittings (a machined plate and two dowel pins), and its pin and plate parts (A-pin, A-plate); its number is not in this plan, the owner writes it in `notes\documents.txt` | steps 3.1, 4.1, 4.4, 4.5, 5.5 |
| B | the big assembly reviewed at the last sitting; its number is not in this plan, the owner writes it in `notes\documents.txt` | steps 3.1, 4.2, 4.3 |
| C | a drawing of six sheets with a revision table on a sheet other than the first | steps 3.2, 3.5 |
| D | an assembly, with D-1 and D-2 the drawings of two of its parts and D-X the drawing of a part that is not in it | steps 3.3, 3.4, 3.5 |
| E | a part opened from a vault view whose same-name drawing is not in the local cache | step 3.3 |
| F | a drawing with some dimensions at their own precision and some at the document's, and a model dimension and a reference dimension on one hole; the part it shows | step 3.6 |
| G | drawings that between them carry: a diameter, a hole callout and a geometric tolerance on known holes, on a part drawing (G-1) and on an assembly drawing of the same part (G-2); a counterbore callout; geometric tolerances, datums and surface-finish symbols; one table of each kind (bill of materials, revision, hole, general) | step 3.7 |
| H | a part drawing (H-part) and an assembly drawing (H-asm) whose callouts you name in advance: for each, the sheet, what it is, the hole it is on, and that hole's diameter in millimetres | step 3.8 |
| J | a part whose drawing of exactly the same name sits in the same folder | steps 3.9, 4.7, 5.1, 5.3, 5.5 |
| K | an assembly in which one part's same-name drawing sits closed beside it (K-1), and two other parts (K-2, K-3) are each shown by two drawings you will open | step 4.6 |
| M | a part and an assembly that each have at least two configurations (A-pin and A will do if they have) | step 4.4 |

## Every PowerShell window: paste this first

Use **Windows PowerShell** (the blue one), not elevated, signed in as the account that uses
SOLIDWORKS. Change the two lines marked `CHANGE` once; paste the whole block into every new
PowerShell window, on day 2 too, with the same date.

```powershell
$R = 'C:\<the folder smart_SW is cloned in>'                                  # CHANGE once
$H = "$env:LOCALAPPDATA\SwReview\handover\<first day of the sitting, yyyy-MM-dd>"   # CHANGE once
$since = [datetime]::ParseExact((Split-Path $H -Leaf), 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
New-Item -ItemType Directory -Force "$H\probes", "$H\dumps", "$H\notes", "$H\exports", "$H\kept" | Out-Null
Set-Alias swreview-extract "$R\extractor\SwReview.Extractor.Console\bin\x64\Release\net48\swreview-extract.exe"
$runs = $null
if (Test-Path "$env:APPDATA\SwReview\settings.json") { $runs = (Get-Content "$env:APPDATA\SwReview\settings.json" -Raw | ConvertFrom-Json).run_root }
if (-not $runs) { $runs = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'SwReview\runs' }

function Show-ReviewFacts {
    param([string] $run)
    $run = $run.TrimEnd('\')
    Push-Location "$R\reviewer"
    try { uv run python -c "import sys, json; from pathlib import Path; from datetime import datetime; from swreview.ir.loader import load_package; from swreview.report.session import load_session; from swreview.report.summary import drawings_of; from swreview.tools.checks_interference import groups_of; r = Path(sys.argv[1]); s = load_session(r / 'session.json'); p = load_package(r).package; ev = [json.loads(x) for x in (r / 'events.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]; us = [e for e in ev if e['type'] == 'usage']; first = us[0]['seq'] if us else 10**9; pre = [e['body']['tool'] for e in ev if e['type'] == 'tool.started' and e['seq'] < first]; later = [e['body']['tool'] for e in ev if e['type'] == 'tool.started' and e['seq'] > first]; keys = {g.group_key for g in groups_of(p)}; judged = {st.arguments.get('group_key') for st in s.steps if st.tool == 'check_interference_group'}; t = s.usage.totals if s.usage else None; print('tokens: input', t and t.input_tokens, '| cached', t and t.cached_input_tokens, '| uncached', t and t.uncached_input_tokens, '| rounds', s.usage and s.usage.rounds, '| turns', s.usage and s.usage.turns); print('findings', len(s.findings), '| contacts', len(s.contacts or []), '| interference rows in package.json', len(p.interferences), '| gaps', len(p.gaps)); print('interference groups', len(keys), '| judged', len(keys & judged), '| not judged', len(keys - judged)); print('pre-run tools:', ', '.join(dict.fromkeys(pre)) or 'none'); print('pre-run tools called again after the first model round:', ', '.join(sorted(set(pre) & set(later))) or 'none'); d = {x.name: x for x in p.extractor.phases}.get('drawing'); print('drawing phase:', (d.status + ('' if d.elapsed_ms is None else ' ' + str(d.elapsed_ms) + ' ms')) if d else 'not recorded'); dl = drawings_of(p); print('drawings line:', dl.text if dl else 'none'); ers = s.evidence_requests; print('questions: asked', len(ers), '| answered', sum(x.status == 'answered' for x in ers)); ans = [e['seq'] for e in ev if e['type'] == 'evidence.answered']; ends = [e['seq'] for e in ev if e['type'] == 'turn.ended']; print('answers sent', len(ans), '| turns ended between the first and last answer', sum(ans[0] < x < ans[-1] for x in ends) if ans else 0, '| turns ended after the last answer', sum(x > ans[-1] for x in ends) if ans else 0, '| first round input after the answers', next((e['body']['input_tokens'] for e in us if ans and e['seq'] > ans[-1]), None)); f = lambda a: datetime.fromisoformat(a.replace('Z', '+00:00')); st = next(e['at'] for e in ev if e['type'] == 'session.started'); td = next((e['at'] for e in ev if e['type'] == 'text.delta'), None); print('seconds from session.started to the first text.delta:', round((f(td) - f(st)).total_seconds(), 1) if td else 'no text.delta')" $run }
    finally { Pop-Location }
}

function Show-DumpFacts {
    param([string] $folder)
    $folder = $folder.TrimEnd('\')
    Push-Location "$R\reviewer"
    try { uv run python -c "import sys; from collections import Counter; from swreview.ir.loader import load_package; from swreview.checks.fastener_identity import recognise_fasteners; p = load_package(sys.argv[1]).package; d = p.documents; print('documents', len(d), '| mass_overridden read', sum(x.mass_overridden is not None for x in d), '| mass_override gaps', sum(g.entity_kind == 'mass_override' for g in p.gaps)); w = [h for h in p.holes if h.wizard is not None]; print('holes', len(p.holes), '| Hole.wizard filled', len(w), '| fit classes', sorted({h.wizard.fit_class_raw for h in w if h.wizard.fit_class_raw}), '| thread classes', sorted({h.wizard.thread_class_raw for h in w if h.wizard.thread_class_raw})); print('model_dimensions', len(p.model_dimensions), '| model_annotations', len(p.model_annotations)); r = recognise_fasteners(p); print('fasteners', len(p.fasteners), dict(Counter(f.identity_source for f in p.fasteners)), '| with a shank face', sum(x.shank_face_id is not None for x in r))" $folder }
    finally { Pop-Location }
}

function Show-Documents {
    param([string] $run)
    $run = $run.TrimEnd('\')
    Push-Location "$R\reviewer"
    try { uv run python -c "import sys; from swreview.ir.loader import load_package; p = load_package(sys.argv[1]).package; [print(d.document_id, d.kind, d.file_name) for d in p.documents]" $run }
    finally { Pop-Location }
}

function Show-SetupTime {
    param([string] $run)
    $run = $run.TrimEnd('\')
    $started = [DateTimeOffset]((Get-Content "$run\events.jsonl" -TotalCount 1 | ConvertFrom-Json).at)
    $created = Select-String -Path "$env:LOCALAPPDATA\SwReview\logs\backend-*.log" -SimpleMatch '"POST /sessions HTTP/1.1" 201' |
        ForEach-Object { [DateTimeOffset]$_.Line.Substring(1, $_.Line.IndexOf(']') - 1) } |
        Where-Object { $_ -ge $started } | Sort-Object | Select-Object -First 1
    if ($created) { 'setup, from session.started to the 201 answer to POST /sessions: {0:N1} s' -f ($created - $started).TotalSeconds }
    else { 'no POST /sessions 201 line after session.started in the backend logs' }
}

function Show-DrawingReadLog {
    Select-String -Path "$env:LOCALAPPDATA\SwReview\logs\tool-service-*.log" -SimpleMatch 'command=drawing.read' |
        Select-Object -Last 3 | ForEach-Object { $_.Line }
}

Set-Location $R
"checkout $R | handover folder $H | run folders $runs"
```

Pass: the last line names the checkout, the handover folder and the run folders (the run
folders appear with the first review or check), and nothing above it is red. A red
`Cannot find path` or `String was not recognized as a valid DateTime` means a `CHANGE` line was
not changed, or its date is not written `yyyy-MM-dd`.

What the five commands do, so you know what you are running (each only reads):

- `Show-ReviewFacts '<run folder>'` prints the facts of one review: its tokens, findings, contacts,
  interference groups judged, which checks ran before the model's first round, its drawings line,
  its questions and answers, and a timing.
- `Show-DumpFacts '<dump folder>'` prints the counts feature 010's dump tasks ask for. It is the
  command of `specs/010-mechanical-checks/tasks.md` Phase 13, unchanged.
- `Show-Documents '<run folder>'` lists a review's documents with their ids (`doc:0012`).
- `Show-SetupTime '<run folder>'` reads the backend log for how long the review's setup took.
- `Show-DrawingReadLog` prints the last three `drawing.read` lines of the tool-service logs.

**Finding a run folder.** In the pane, press **Open run folder**. In the Explorer window that
opens, click the address bar, copy the path, and paste it between the quotes of
`$run = '<paste here>'`. If the path holds an apostrophe (`'`), type it twice there.

**Finding a document's full path.** In File Explorer, hold Shift, right-click the file and choose
**Copy as path**. The path comes with its own double quotes: paste it over `"<...>"`, quotes
included.

## Step 1. Update the workstation

### 1.1 SOLIDWORKS is closed

```powershell
Get-Process SLDWORKS -ErrorAction SilentlyContinue
```

Pass: nothing is printed. Fail: a line naming `SLDWORKS`: close SOLIDWORKS (Don't Save) and run it
again.

### 1.2 The checkout is clean

```powershell
git status --porcelain
```

Pass: nothing is printed. Fail: any line. Do not delete anything: copy the lines into
`$H\notes\update.txt` and follow `docs/workstation-runbook.md` section 4, "If `git status
--porcelain` prints anything".

### 1.3 Update, build and gate

```powershell
.\extractor\tools\update-workstation.ps1
```

Add `-TokenizerFrom '<where the owner's vocabulary file is>'` if the vocabulary could not be
downloaded before, and `-SolidWorksRoot '<SOLIDWORKS install folder>'` if SOLIDWORKS is not in
`C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS`. If Windows says running scripts is disabled, run
`powershell -ExecutionPolicy Bypass -File .\extractor\tools\update-workstation.ps1` instead.

Look at: each `== <step>` heading as it passes (fetch, pull, `uv sync`, `tokenizer fetch`, `pytest`,
`ruff`, `dotnet build`, `dotnet test`), then the `== health` block at the end.

- Pass: it reaches `== health`; the pytest line says `passed` with no `failed`; `dotnet test` says
  `Passed!` for both test projects; the health block prints `uv on PATH: <a path>` and
  `swreview-extract: <a path>`. `standards profile: MISSING` is expected on a new machine until
  step 2; `standards profile: present at` is expected otherwise.
- Fail: a red line ending `failed with exit code <n>; nothing after it was run.` **Stop the
  sitting**: copy the last 40 lines of the window into `$H\notes\update.txt` and call the owner.
  A download refused by the web filter at `tokenizer fetch` is not a fail: run the command again
  with `-TokenizerFrom` and the owner's file.

### 1.4 Which build this is

```powershell
git log --oneline -1; Test-Path docs\workstation-test-plan-2026-09-23.md
git --version; dotnet --version; uv --version
(Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -Name pv).pv
```

Pass: the second line prints `True` (the checkout holds this plan, so it is this build or a later
one), and every other line prints a commit or a version. Record: all of it, plus the SOLIDWORKS
version and service pack from SOLIDWORKS's Help > About, at the top of the findings document.

### 1.5 Registration, only when needed

Needed only on a machine where SwReview was never registered, after the checkout moved, or when
Tools > Add-ins in SOLIDWORKS does not list SwReview at all. With SOLIDWORKS closed, open **Windows
PowerShell as administrator**, signed in as the account that uses SOLIDWORKS, then:

```powershell
cd '<the folder smart_SW is cloned in>'
.\extractor\tools\register-addin.ps1
```

Pass: the last line starts `registered SwReview.AddIn, and enabled it for`. Close the
administrator window afterwards and carry on in the ordinary one.

### 1.6 The health checks

Start SOLIDWORKS and open a **part or an assembly** (not a drawing), then:

```powershell
Get-Content "$env:LOCALAPPDATA\SwReview\logs\addin.log" -Tail 12
```

These are `docs/workstation-runbook.md` section 6; each must hold:

1. Tools > Add-ins shows SwReview ticked, and the log above ends with `AssemblyRedirect
   installed.`, `Attached to SOLIDWORKS.`, `Task Pane created.`, `Review host started.`, with no
   line beginning `The SwReview tool service`.
2. The Review tab's backend badge says the backend is running (not "starting" and not an error).
3. Model check on the open part gives a grade and findings within seconds (step 5.1 looks closer).
4. Standards gives a verdict once step 2 is done (step 5.2).
5. A review ends on screen (step 4 does this many times).
6. The pane has five tabs: Review, Extract, Model check, Remodel, Standards. No Ask tab.
7. `git status --porcelain` still prints nothing.

Record: pass or fail for each of the seven; on a fail, the log lines.

## Step 2. The standards profile and the key [008 T101]

### 2.1 What the owner fills in

The owner's current profile says `version: 1`. That file still loads, but then the hygiene
checks, the general tolerance and the drawing comparison are skipped on every review, and 011
T068 cannot be judged. The owner rewrites it at **version 3**, using the layout of
`config\standards.example.yaml` (whose values are all fictional), and fills in:

| Field | What the owner writes |
|---|---|
| `version` | `3` |
| `general_tolerance.linear` | the title block's general tolerance, one band per written precision: `decimal_places` (a dimension written `.X` has 1, `.XX` has 2, `.XXX` has 3) and `plus_minus_mm`. The bands go in rising order of decimal places, each once. `plus_minus_mm` is **always millimetres**, even when the drawings are in inches: a title block's 0.005 in is 0.127. An empty list, `[]`, says the company declares none |
| `general_tolerance.angular_deg` | the general angular tolerance in degrees, or `null` for none |
| `hygiene.part_number_property` and `hygiene.description_property` | the names of the custom properties holding the part number and the description; empty skips the checks that need them |
| `drawing.sheet_formats` | the sheet format names a drawing's sheets may use, each once |
| `drawing.drafting_standard` | the dimensioning standard the drawings use |
| `drawing.projection` | `first_angle`, `third_angle`, or empty |
| `drawing.dimension_unit` | `mm`, `in`, or empty: the unit the decimal places above are counted in. Empty means the general tolerance applies to no drawing dimension |
| `drawing.drawing_template` and `drawing.bom_template` | the template names; kept for later drawing creation and never compared, so empty is allowed |
| the version 1 sections | `vault_root`, `library`, `data_card`, `part_number`, `revision`, `material`, `export_control`, as in the owner's current file |

Every key must be there; an empty value skips that one comparison and is never counted as a
pass. Numbers are written without quotes.

### 2.2 Place the file

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\SwReview" | Out-Null
if (Test-Path "$env:LOCALAPPDATA\SwReview\standards.yaml") { Copy-Item "$env:LOCALAPPDATA\SwReview\standards.yaml" "$H\notes\standards.yaml.before" }
Copy-Item '<where the owner put the new file>' "$env:LOCALAPPDATA\SwReview\standards.yaml"
$settings = if (Test-Path "$env:APPDATA\SwReview\settings.json") { Get-Content "$env:APPDATA\SwReview\settings.json" -Raw | ConvertFrom-Json }
if ($settings -and ($settings.PSObject.Properties.Name -contains 'standards_profile_path')) { "profile setting: [" + $settings.standards_profile_path + "]" } else { 'profile setting: the default' }
```

Pass: the last line is `profile setting: the default`, or names
`...\AppData\Local\SwReview\standards.yaml` between the brackets: the pane reads the file you
placed. Fail: `profile setting: []`, which means no profile is configured (the Standards tab
refuses and reviews run without the standards checks), or another file: stop and ask the owner
which file the pane should read. The one line you may change in the profile is `vault_root`, if
the vault is mounted somewhere else on this machine (runbook section 5). The backup in
`$H\notes` is the old profile; it travels by hand like the rest of the folder and is never pasted
anywhere.

### 2.3 It is version 3

```powershell
Select-String -Path "$env:LOCALAPPDATA\SwReview\standards.yaml" -Pattern '^version:'
```

Pass: `version: 3`. Fail: `version: 1` or `version: 2`: the paid reviews wait until the owner
rewrites it (the probes of step 3 can go ahead).

### 2.4 It is valid

In SOLIDWORKS, with any part open, press **Standards** in the pane once. It makes a run folder
ending `-standards`. Copy that folder's path (the newest folder in the run folders), then:

```powershell
$package = '<paste the -standards run folder>'
cd "$R\reviewer"; uv run swreview check standards --package $package --out "$H\notes\profile-check" --profile "$env:LOCALAPPDATA\SwReview\standards.yaml"; "exit code: $LASTEXITCODE"; cd $R
```

Pass: `exit code: 0`. Fail: `exit code: 1` with a message naming a field: tell the owner the field
it names (do not paste the file's contents anywhere); nothing is graded until it is fixed.

### 2.5 The OpenAI key

In the pane's Review tab press **Settings**. Choose Provider `openai`, the Model and Reasoning
effort the owner names (the recorded runs used `gpt-5.6-luna` at `high`), paste the key into
**API key**, and press **Save**.

Pass: the note under the key field says a key is stored, and the backend badge comes back as
running after the save. Record: the provider, model and effort (never the key).

The second half of 008 T101, that a review runs `check_standards` before the model's first round,
is read at the first review, step 3.4.

## Step 3. The extractor: dumps and probes

**How to read every probe run in this step.** Each `swreview-extract probe drawings` run prints
its report and writes the same lines to a new file `drawings-probe-<time>.txt` in `$H\probes`; it
never overwrites one. It prints ids, counts, answers and millimetres only, never a name or a
value. After each run look at:

- the `exit code:` line: `0` means the run completed; `1` means it was refused, stopped, or could
  not write its report;
- the line after the report, `Wrote <file>`: anything else printed there is a message to copy
  into the findings document, after checking it names no path or value;
- the gate log at the end, which must read `mutating members: none`, `refusals: none`,
  `sheet activation: none`, `document opening: none` and `display state: none`, and the last line
  `gate log: the confirmed open's guard (DrawingOpenGuard, D14 only): none` on every run but
  step 3.9's.

Pass: exit code 0 and the gate log as above. Fail: exit code 1, or any of those words other than
`none`: copy the lines into the findings document. A line `stopped: <Type> 0x<number>` or
`unread (<Type> 0x<number>)` inside a section is **not** a fail of the sitting: it is SOLIDWORKS's
answer on this release, and recording it is half the point of the probes. A report that says
`refused: the named document is not open in SOLIDWORKS, so nothing was read and nothing was opened`
means the document named after `--doc` is not open, or its path was mistyped: open it and run the
command again.

### 3.1 The dumps of the two recorded assemblies [010 T103 to T106]

For A, then for B: open the assembly **resolved** (File > Open, Mode: Resolved), and click its
window so it is the active document. Do not add `--doc` to this command: the active document is
the one it dumps.

```powershell
swreview-extract dump --out "$H\dumps\A" --meshes none; "exit code: $LASTEXITCODE"
Show-DumpFacts "$H\dumps\A"
Get-Content "$H\dumps\A\extract.log" -Tail 1
```

For B, the same three lines with `B` in place of `A`. Look at the four lines `Show-DumpFacts`
prints and the last line of `extract.log`, which starts `gated=`.

- 010 T103, pass: in the `documents` line, `mass_overridden read` equals `documents`, and
  `mass_override gaps` is `0`.
- 010 T104, pass: `Hole.wizard filled` is above 0 wherever the models use Hole Wizard holes.
- 010 T105: `model_dimensions` and `model_annotations` are above 0 where the models carry DimXpert
  or MBD dimensions, and 0 where they do not. Say whether the team uses DimXpert or MBD.
- 010 T106, pass (on B): `fasteners 68` and `with a shank face 68`: the 68 named screws, each with
  its shank face, and nothing else.
- Fail: any of those numbers otherwise, or an exit code of 1.

Record: the four lines and the `gated=` line for A and for B. Say whether `GetOverrideOptions`
appears in the `gated=` line: it appears only when the first way of reading a mass override gave
no answer on some document.

### 3.2 A multi-sheet drawing on its own [011 T062; 006 T103; 006 T105; 006 T107]

1. Open drawing C and click its sheet 1 tab. Then:

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of C>" --probe D1,D11; "exit code: $LASTEXITCODE"
   ```

   Look at D1: `completed in <n> ms`, each phase row, the sheet and view counts, the gap kinds with
   their counts. Look at D11: per sheet, the `GetProperties2` item count, the scale, first angle,
   whether `GetTemplateName` is present, and the preferences 13, 47 and 65. Pass and fail as the box
   at the top of step 3 says. Record: the report's file name and the D1 `completed in` time.
2. With C still the active document, press **Standards** in the pane (006 T107).
   - Pass: a verdict with every one of the sixteen checks in a bucket; the words
     `no drawing graded` do **not** appear (the drawing is graded); every model the views show
     that is already open is graded once; a model the views show that is not open appears as a
     gap and an unresolved check, and no new window opens (SOLIDWORKS's Window menu lists the same
     documents before and after); **Open report** shows a report that says `nothing was rebuilt`.
   - A finding whose subject is a note, a sheet, a revision-table row, a cut-list item or a
     property shows **no Show button** (006 T105's page half).
   - Fail: any of these otherwise. Record: the verdict line and the counts per bucket.
3. The Standards probe on the same drawing (006 T103 and T105):

   ```powershell
   swreview-extract probe standards --doc "<full path of C>" | Tee-Object -FilePath "$H\probes\probe-standards-C.txt"; "exit code: $LASTEXITCODE"
   ```

   Pass: exit code 0, and at the end `mutating members: none` and `sheet activation: none`. If a
   weldment or sheet-metal part is at hand, open it and run the same line with its path and
   `probe-standards-weldment.txt`: that is the one kind, the cut-list item, the drawing cannot
   show. Record: the two file names; the development machine reads PROBE-4 to PROBE-7 and PROBE-10
   out of them.

### 3.3 Discovery: an assembly, its part drawings and an unrelated drawing [011 T063]

Open assembly D, drawings D-1 and D-2, and drawing D-X, and leave at least one drawing window
behind another (SOLIDWORKS stacks them; do not tile them).

1. On the assembly (D2 lists every open document; D13 checks D's own same-name drawing):

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of D>" --probe D2,D13; "exit code: $LASTEXITCODE"
   ```

   Look at D2: one line per open document with its kind, whether it is visible, its views, blank
   views and referenced documents, then `listed twice:`. Record the `listed twice` line.
2. On each of D-1, D-2 and D-X in turn (three runs):

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of D-1>" --probe D3,D12; "exit code: $LASTEXITCODE"
   ```

   Look at D3: the `active sheet:` line, which must say `unchanged true` (the probe activates no
   sheet), and each sheet's views by both ways of listing them. Look at D12: the `detailing mode`
   line, and per view `ReferencedConfiguration present`, `IsModelOutOfDate` and `IsModelLoaded`.
3. Open part E (the vault-view part whose drawing is not cached):

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of E>" --probe D13; "exit code: $LASTEXITCODE"
   ```

   Look at D13: `File.Exists <true or false> in <n> ms`, the directory entry before and after, and
   `the local copy changed across the check: <true or false>`. Record all three. A time above
   1,000 ms, or `true` on the last line, is the answer that makes the development machine skip the
   candidate check under a vault view: record it; it is not a fail of the sitting.

### 3.4 The pane review of assembly D [011 T063; 011 T068; 008 T101]

This is the sitting's first paid review; step 2 must be complete. Keep D, D-1, D-2 and D-X open,
and click D's window so the assembly is the active document. Note the documents SOLIDWORKS's Window
menu lists. In the pane's Review tab press **Review** and wait for `The review has finished.` or
`Waiting for your answers.`. Copy the run folder (Open run folder), then:

```powershell
$run = '<paste the run folder>'
Show-ReviewFacts $run
```

- 011 T063, pass: the `drawings line` names D-1 and D-2 as read and does not name D-X; the
  summary at the top of Results shows the same line; the Window menu lists the same documents as
  before (nothing was opened); the review finished. Record the `drawing phase` time: it is
  discovery's time, and a candidate check that fetched a file or stalled shows there as seconds.
- 008 T101, pass: `pre-run tools:` includes `check_standards`. Fail: it does not, or the profile
  was not version 3.
- 011 T068, pass: the drawings were compared with the profile's drawing section. Open the **Not
  reached** fold at the bottom of Results: either a `drawing_profile.conformance` line that says
  the drawing `agrees with the profile's drawing standard in` some settings, or a finding that says
  a drawing `differs from the company's drawing standard` and names only the drawing's own values.
  Fail: a line saying the profile `which has no drawing section`. Then press **Open report** and
  search it (Ctrl+F) for `drawing callouts are read but not yet validated on a seat`: found, where
  the review computed a fit or a stack-up, is the pass for this sitting (the binding itself waits
  for the switch, section 3.10). Record: found, not found, or no fit or stack-up in this review.

Answer any questions the review asks (step 4's box says how), then go on.

### 3.5 The views of other sheets, and views out of date [011 T063]

1. Open drawing C and click its **sheet 3** tab (D3 asks for a six-sheet drawing with sheet 3
   active):

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of C>" --probe D3; "exit code: $LASTEXITCODE"
   ```

   Pass: the `active sheet:` line reads `position 3 before the run, 3 after, unchanged true`, and
   each sheet's views are listed.
2. A view out of date: open the part D-1 shows, change one of its dimensions, and rebuild (Ctrl+B),
   **without saving**. D-1's view of it is now out of date. Then:

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of D-1>" --probe D12; "exit code: $LASTEXITCODE"
   ```

   Look: `IsModelOutOfDate true` on that view. Afterwards undo the change (Ctrl+Z) and close the
   part choosing **Don't Save**.
3. Detailing mode: close D-1 (Don't Save), then File > Open D-1 with Mode **Detailing**, and run
   the same D12 line again. Look: `detailing mode true`. Close it again.

Record: the three report file names and the lines named above.

### 3.6 Precision, tolerance and names [011 T064]

Open drawing F; the part it shows opens with it.

```powershell
swreview-extract probe drawings --out "$H\probes" --doc "<full path of F>" --probe D4,D5,D8,D11; "exit code: $LASTEXITCODE"
```

- If the report says the part `is not open, so it was not read (nothing is opened)`, open the part
  (File > Open) and run the line again.
- D4: the document's preferences 24, 25, 47 and 49, and for each dimension `GetPrimaryPrecision2`,
  `GetPrimaryTolPrecision2`, `GetUseDocPrecision`, `GetUnits` and `GetUseDocUnits`. Mark any
  dimension that says `GetUseDocPrecision true` and `GetPrimaryPrecision2 -1`: that is the case
  where T064's one-line change is made on the development machine (never here).
- D5: each dimension's tolerance next to the part's, ending `; agree true` or `; agree false`.
- D8: each dimension's full-name shape next to the part's, ending `FullName equal true` or
  `FullName equal false`.

Pass: exit code 0, gate log as the box says, and the part read. Record: the file name, the marked
D4 lines, and how many `agree false` and `FullName equal false` lines there are.

### 3.7 Callouts, symbols and tables [011 T065]

Run this once on each G drawing (G-1, G-2 and whichever carry the counterbore, the symbols and the
tables), with the part each shows open:

```powershell
swreview-extract probe drawings --out "$H\probes" --doc "<full path of G-1>" --probe D6,D7,D9,D10; "exit code: $LASTEXITCODE"
```

- D6: each dimension's and annotation's attached faces; per face either
  `the part's face phase fac:<n> (<kind>, radius <r> mm)` or
  `no face the part's face phase described has this reference`.
- D7: each hole callout's variables and the lengths of `GetText(1)` to `GetText(4)`, and the whole
  text's length by position.
- D9: the frame, slot and label counts. D10: each table's type, its readable cells, and for a bill
  of materials how many rows' documents are open.

Pass: exit code 0 and the gate log as the box says. Every `unread` is recorded; the development
machine checks each against the gaps. Record: the file names.

### 3.8 The named callouts [011 T066]

Open H-part, then H-asm, each with its part open, and run on each:

```powershell
swreview-extract probe drawings --out "$H\probes" --doc "<full path of H-part>" --probe D4,D5,D6,D8; "exit code: $LASTEXITCODE"
```

For each callout you named in `notes\documents.txt`, find its lines on its sheet:

- D6: the face line must read `the part's face phase fac:<n> (cylinder, radius <r> mm)` with `<r>`
  half the named hole's diameter (a 10 mm hole reads `radius 5.000 mm`).
- D8: `FullName equal true`. D5: `; agree true`.

Pass: every named callout ties to its hole that way, on both drawings. Fail: any
`no face the part's face phase described has this reference`, a radius that is not the named
hole's, `FullName equal false`, `agree false`, or the part not read. Record: one line per
callout, matched or not, with the line that shows it. **Change nothing**: the switch this decides
is set on the development machine (section 3.10).

### 3.9 The read-only open, probed [011 T077]

1. Close J's drawing if it is open. Open part J and click its window, so J is the active
   document. Click into PowerShell, paste the line, press Enter, and then **touch nothing** until
   the prompt comes back:

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of part J>" --probe D14; "exit code: $LASTEXITCODE"
   ```

   Pass: the D14 section reads, line for line (the sheet, view, gap and document counts are J's
   own; the views must be at least 1):

   ```text
     drawing open before the probe: false
     OpenDoc6: type 3, options 3 (ReadOnly 2 yes, Silent 1 yes, ViewOnly 4 no, RapidDraft 8 no, LoadModel 16 no), configuration ""
     DocumentVisible: false (type 3), then true (type 3)
     outcome: opened by the probe and closed
     active document unchanged: during true, after true
     foreground window unchanged: during true, after true
     drawing as read: sheets <n>, views <n>, gaps <n>
     drawing file: size unchanged true, write time unchanged true, SHA-256 unchanged true
     save flags: before <n> of <n> raised, after <n> of <n> raised; raised by the run: none
     afterwards: GetOpenDocumentByName answers false; an exclusive read open succeeded
     open documents: before <n>, during <n>, after <n>
     left loaded afterwards: <none, or the positions>
     seam keys gated: ISldWorks.DocumentVisible, ISldWorks.OpenDoc6, ISldWorks.CloseDoc
     against confirmed-open.md: every answer as required
   ```

   and no drawing window appeared (the Window menu is as before). If it says
   `no same-name drawing beside the document (File.Exists false), so nothing was opened`, J's
   drawing does not have exactly J's name in J's folder: choose another J.
2. Open J's drawing yourself (File > Open), then use the Window menu to make part J active again,
   and run the same line. Pass:

   ```text
     drawing open before the probe: true
     OpenDoc6: not called
     DocumentVisible: not called
     outcome: already open, read as it stood and left open
     active document unchanged: during true, after true
     foreground window unchanged: during true, after true
     drawing as read: sheets <n>, views <n>, gaps <n>
     drawing file: size unchanged true, write time unchanged true, SHA-256 unchanged true
     save flags: before <n> of <n> raised, after <n> of <n> raised; raised by the run: none
     afterwards: GetOpenDocumentByName answers true; an exclusive read open <succeeded or failed>
     open documents: before <n>, during <n>, after <n>
     left loaded afterwards: <none, or the positions>
     seam keys gated: none
     with the drawing already open, no visibility, open or close key was gated: true
     against confirmed-open.md: every answer as required
   ```

   and the drawing is still open afterwards.

The last line of each is the probe's own reading; any `not as required: ...` there is a fail and
names what failed. Record: both report file names, both last lines, the `open documents` and
`left loaded afterwards` lines (recorded, never a fail), and every line that differs from the
blocks above. Change nothing: section 3.10 says who sets the switch.

### 3.10 The two switches: what allows them, and how

Both ship **off**. The seat never edits a file to change them; the development machine does it
after the sitting, in a commit of its own for each, citing the probe report files by name. Until
then the pane reads a confirmed drawing only when it is already open, and no drawing dimension
enters a calculation.

**`DrawingOpenScope.SeatValidated` (011 T077)** may be switched on only when every one of these
holds:

1. Both D14 reports of step 3.9 exist, on the same part J, each with exit code 0.
2. The drawing-closed report matches the first block of step 3.9 line for line: type 3, options 3
   with only ReadOnly and Silent, configuration `""`; hidden then shown again, type 3; opened by the
   probe and closed; the active document and the window in front unchanged, during and after; at
   least one view read; the file's size, write time and SHA-256 unchanged; no save flag raised by
   the run; afterwards not open and not locked; the three seam keys; `every answer as required`.
3. The drawing-open report matches the second block: nothing opened, hidden or closed; `seam keys
   gated: none`; the drawing still open; the same unchanged lines; `every answer as required`.
4. Both reports' read-only gate log says `mutating members: none` and `refusals: none`.
5. No drawing window appeared during the first run, and the drawing stayed open after the second.

How, on the development machine: in `extractor/SwReview.Extractor/Sw/DrawingOpenScope.cs` change
`public static bool SeatValidated => false;` to `=> true;`, and edit the one test that reads the
shipped value, `DrawingOpenScopeTests.TheSeamShipsOffUntilTheSeatConfirmsIt` in
`extractor/SwReview.Extractor.Tests/DrawingOpenTests.cs` (011 T094); the gates green; T077 ticked.
If any answer failed, it stays off and research R4 records why. The validated open, end to end
from the pane, is then 011 T095, at the sitting after.

**`DRAWING_BINDING_VALIDATED` (011 T066)** may be switched on only when every one of these holds:

1. The reports of steps 3.6 (F) and 3.8 (H-part and H-asm) exist, each with exit code 0, no
   `stopped:` inside the D4, D5, D6 or D8 sections, and the part's own extraction read (no `is not
   open, so it was not read`).
2. Every callout named in advance ties to the right hole on both H drawings: its D6 face line is
   a cylinder whose radius is half the named hole's diameter, never
   `no face the part's face phase described has this reference`.
3. Each named dimension reads `FullName equal true` in D8 and `; agree true` in D5.
4. No dimension that uses the document's precision (`GetUseDocPrecision true`) reads
   `GetPrimaryPrecision2 -1` in D4. If one does, T064's one-line change to
   `drawings/native.written_precision` lands first, in its own commit.

How, on the development machine: in `reviewer/src/swreview/drawings/binding.py` change
`DRAWING_BINDING_VALIDATED: bool = False` to `True`; edit the one test that reads the shipped
value, `test_drawing_binding.test_the_switch_ships_off` (011 T094); add the known case, made
fictional, as a regression row in `test_drawing_binding.py`; and, as T066 says, extend the check
restated after a confirmed read to `check_joints`, with its test; the gates green; T066 ticked. Any
mismatch keeps it off, and research R4 records why.

## Step 4. The reviews

**How to read a review, every time in this step.**

1. Press **Review** with the document active. The Results view shows `The review is running.`
   Wait for `The review has finished.` or `Waiting for your answers.`
2. Copy the run folder (Open run folder) and run `Show-ReviewFacts` on it:

   ```powershell
   $run = '<paste the run folder>'
   Show-ReviewFacts $run
   ```

3. Read the summary at the top of Results, in the backend's own words:
   - the headline, `<n> findings in <n> issues`;
   - three lines, **Decide** (`<n> need your decision`), **Fix** (`<n> to fix`) and **Verify**
     (`<n> to verify`), each followed by the check goals it covers with their counts;
   - the questions line, `<n> questions for you`, and the parts line, `<n> of <n> parts not
     loaded`, when there are any;
   - **the drawings line**, when the review read or found drawings: `Drawings read: ...` and
     `Same-name drawings found but not open: ...`;
   - nine goal lines, Interference to Modelling practice, each `issues found`, `checked, no issue`,
     `not reached` (with a short reason) or `not applicable`.
4. Press **Transcript**: its head shows the usage line, `<n> uncached + <n> cached input - <n> tokens
   in all - <n> round trips - last round <n> s`. Uncached plus cached is the review's input. Press
   **Results** to go back.
5. **Questions**: when **Questions for you** appears above Start here, it shows `Question 1 of
   <n>` with **Previous** and **Next**. Choose an answer on each question (or type one, or press
   **Skip for now**), then press **Send answers** once, for all of them together. Before sending,
   note the sentence beside Send, `Sending resumes the review once. Its last round sent <n> input
   tokens.` For a same-name drawing question in steps 4.1 and 4.2, answer `Review without it`.

### 4.1 A, the small assembly [008 T103; 009 T079]

Open A resolved and make it active; press Review (the box above). Note the time it started and
finished.

- 008 T103, pass: the `tokens` line's `input` is **at most 300,000** when the review first
  finishes, before any answer is sent. The last sitting's reviews of the small assembly took
  1.47 million and 1.58 million. Fail: above 300,000; then record the `pre-run tools called
  again after the first model round` line, which names the checks the model repeated (a repeat
  fails T103 by design).
- `pre-run tools:` names the checks that ran before the model's first round (checks first): the
  three `check_rms_...` checks, `bridge_interference`, `check_interference_group`, `check_joints`,
  `check_mass_material`, `check_hygiene` and `check_standards`, and `check_drawings` when the
  review found drawings. Record the line.
- `interference groups ... | not judged 0`: every detected group judged, as a finding or a contact.
- 009 T079: read the summary with the engineer who knows A. Pass: they agree the **Decide** line
  names the decisions that are theirs, and the `not reached` goals are the ones the review did not
  reach. Record their words.
- If the review asked questions, answer them all in one send (box, item 5) and run
  `Show-ReviewFacts $run` again: record both `tokens` lines, before and after.

Record: the facts, the headline, the Decide, Fix and Verify lines, the goal lines, the drawings
line (with letters in place of names), the usage line, and the start and end times.

### 4.2 B, the big assembly [008 T102; 010 T107; 009 T079; 009 T080]

Open B resolved and make it active; press Review. Note the start and end times.

- 008 T102, pass: the `tokens` line's `input` (uncached plus cached) is **at most 995,853** when
  the review first finishes, against the **12.4 million** of the same review at the last sitting;
  the usage line shows uncached and cached as two numbers, and so does the report's Tokens section
  (Open report). Fail: above 995,853.
- 008 T102 and 010 T107, pass: `not judged 0`; the contacts appear in their own fold after the
  findings, `<n> size-for-size contacts`, and none of them in Start here; `pre-run tools:`
  includes `check_joints`, `check_mass_material` and `check_hygiene`; and the next line, `called
  again after the first model round`, names none of the three (no model round spent on them).
- Record the `findings`, `contacts`, `interference rows` and `gaps` counts. The comparison with the
  99 findings recorded last time, by subject, is the development machine's (008 T105): the
  standards findings now come from the real profile, not the example, so the counts will differ.
- 009 T080, **before anyone scrolls**: show the Results view for ten seconds to an engineer who has
  not seen it (a colleague, or yourself if nobody else is there) and ask how many decisions are
  theirs and which goals were not reached. Pass: they say the Decide count and the goals marked
  `not reached`. Record their answer.
- 009 T080, the screenshot: make the docked pane 300 pixels wide and 600 high (drag its edge;
  un-maximize SOLIDWORKS and size its window). Press Windows+Shift+S, snip the pane, paste it into
  Paint: Paint's status bar shows the size. At a display scale of 125 percent that is 375 by 750,
  at 150 percent 450 by 900 (Windows Settings > System > Display > Scale). Save it as
  `$H\notes\pane-300x600-B.png`. Pass: the headline, the three groups and every `not reached` goal
  are in the picture without scrolling.
- 009 T079: the engineer's words on Decide and on the not-reached goals, as in step 4.1.
- Answer the questions all in one send, as in step 4.1, and record both `tokens` lines.

### 4.3 Retry, and the setup time [008 T104]

Right after step 4.2, in the same PowerShell window:

```powershell
Show-SetupTime $run
```

Record the setup time and, from step 4.2's facts, the `seconds from session.started to the first
text.delta`. Those are the two timings T104 asks for (the pane's DevTools cannot show this: the
add-in sends `POST /sessions`, not the page).

**Retry** appears only on a card headed `The review stopped`. If B's review ended without one,
there is nothing to press: record `T104: not reachable, B's review ended without an error card`,
and do not stop or restart anything to make one. If the card is there, press **Retry**; when the
new review finishes, copy its run folder into `$run` and run `Show-ReviewFacts $run` and
`Show-SetupTime $run`. Pass: the new run's `interference rows in package.json` and `gaps` are no
more than B's, and `judged` is the same with `not judged 0`. (Retry makes a new run folder and
extracts again; it does not reuse B's.)

### 4.4 Two part reviews, and switching configuration [009 T081]

Keep SOLIDWORKS open from step 4.1 to step 4.5. Open A-pin and make it active; press Review and
wait for it to finish. Then the same for A-plate. The row of chips above Results now holds A,
A-pin and A-plate, each with its configuration and time.

This needs M: a part and an assembly that each have two configurations (A-pin and A, if they
have; otherwise review M's part and assembly the same way first).

1. Make the assembly active in SOLIDWORKS and press its chip, so its review is on screen. Open the
   ConfigurationManager (the tab above the feature tree) and double-click the other
   configuration. Pass: the review hides, and the pane says
   `This review is of <the document> [<its configuration>].` and what to press instead.
   Double-click the first configuration again. Pass: the review comes back.
2. The same with the part: make it active, press its chip, switch, switch back.
3. During a running turn: make the assembly active and press its chip; type a short follow-up
   question in the box at the bottom and press **Send**; while it runs, switch configuration.
   Pass: **Stop** stays available. Press it: the turn ends. Switch back.

Record: each pass or fail. Save no configuration change.

### 4.5 The review chips [009 T083]

1. Note A's usage line (Transcript view). Press A-pin's chip, then A-plate's, then A's. Pass: each
   review comes back, and A's usage line is unchanged: restoring spends no tokens.
2. Press **Settings**, then **Save** without changing anything: the backend restarts. When the
   badge says running again, press A's chip. Pass: A's review comes back with the sentence
   `The backend restarted, so this review is shown from its run folder. Follow-ups, decisions and answers are off.`
3. Copy A-pin's run folder into `$H\kept` first, so nothing is lost, then delete the original:

   ```powershell
   $pin = '<paste the run folder of A-pin>'
   Copy-Item $pin "$H\kept" -Recurse
   Remove-Item $pin -Recurse
   ```

   Press A-pin's chip. Pass: `This review can no longer be restored.` with a **Remove** button;
   Remove takes the chip away.

Record: each pass or fail. From here on SOLIDWORKS may be closed and reopened.

### 4.6 Drawing questions, three answers in one send, and a confirmed candidate left closed [011 T067; 009 T084; 011 T077; 011 T101]

Open assembly K with K-1's same-name drawing **closed**, and open two drawings of K-2 and two of
K-3 (all four showing their part in a view). Note the Window menu. Make K active and press Review.

- 011 T067, pass: the questions include
  `A drawing with the same name sits beside <n> reviewed file(s) but is not open. Should the review read it?`
  (answers `Yes, open it read-only and read it`, `Review without it` and
  `It is not the right drawing`) and one question per doubly drawn part,
  `2 open drawings show <stem>. Which one governs it?` (the drawings' names and `They all apply`).
- Answer the same-name question `Yes, open it read-only and read it`, and each governing question
  with the drawing that governs (or `They all apply`). Before sending, record the sentence beside
  Send. Before sending, also open the **Not reached** fold and count the lines that begin
  `drawing.context`. Then press **Send answers** once.
- When it finishes, put K's run folder in `$run` and run `Show-ReviewFacts $run` (the box, item
  2). 009 T084, pass: `answers sent 3 | turns ended between the first and last answer 0 | turns
  ended after the last answer 1`, and record `first round input after the answers` beside the
  sentence you recorded. With fewer than three questions, record how
  many there were: T084 then waits for a review that asks three.
- 011 T077's pane half and 011 T101 part 1, pass, while the switch is off: the Not reached fold has
  an unresolved line
  `drawing.confirmed_open - the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 probe D14)`;
  no drawing window or document appeared (the Window menu is as before); and

  ```powershell
  Show-DrawingReadLog
  ```

  prints a line with `command=drawing.read status=error`, `gated=GetOpenDocumentByName` and
  nothing more in the `gated=` list, and no `target=`.
- 011 T101 part 3, pass: the fold holds as many `drawing.context` lines as before the answers.
- 011 T067, the brief: find K-2's and K-1's document ids with `Show-Documents $run`, then for each:

  ```powershell
  $doc = 'doc:<the id>'
  cd "$R\reviewer"; cmd /c "uv run swreview drawing brief --package ""$run"" --run ""$run"" --document $doc > ""%TEMP%\swreview-brief.json"""; "exit code: $LASTEXITCODE"; cd $R
  (Get-Item "$env:TEMP\swreview-brief.json").Length
  Select-String -Path "$env:TEMP\swreview-brief.json" -SimpleMatch '"answers":[{' -Quiet
  ```

  Pass: exit code 0, a size of **at most 6,000** bytes, and `True` (the brief lists your answers).
  `cmd /c` keeps the brief's bytes; do not change it to a PowerShell redirect, which would change
  them. Record: each size and the True or False.

### 4.7 A candidate opened by you before confirming [011 T101]

1. Close J's drawing. Open part J only and make it active; press Review. When
   `Waiting for your answers.` appears, record the summary's drawings line: pass, it reads
   `Same-name drawing found but not open: <J's drawing>`, below the parts line if there is one and
   above the goal lines. In the Not reached fold, J's `drawing.context` line ends
   `a drawing with its name sits beside it (candidate)`; count the lines that begin
   `drawing.context`.
2. Open J's drawing yourself (File > Open). Use the Window menu to make part J active again; the
   review shows again. Answer `Yes, open it read-only and read it` and press **Send answers**.
3. When it finishes, pass for each:
   - the Not reached fold's checked bucket has
     `drawing.confirmed_open - read as it stood; it was already open, so it was left open`;
   - `Show-DrawingReadLog`'s newest line has `command=drawing.read status=ok`, a `gated=` list
     beginning `GetOpenDocumentByName`, no `target=` and no `refused=`;
   - J's drawing is still open;
   - the drawings line now reads `Drawing read: <J's drawing>` with no `found but not open` part,
     in the same place;
   - as many `drawing.context` lines as before the answer.
4. **Settings**, **Save** (the backend restarts); when it is running again press J's chip. Pass:
   the review comes back read-only with the same drawings line.
5. The screenshot of step 4.2 again, now with the drawings line: pass when the headline, the three
   groups, the drawings line and every `not reached` goal fit in 300 by 600 without scrolling. Save
   it as `$H\notes\pane-300x600-J.png`.

Record: each pass or fail, the log line, and any wording the owner would change (it would go in
`review_words_v1.yaml` on the development machine).

## Step 5. The other tabs, the live Gemini test, and the older build

### 5.1 Model check

Open part J, press **Model check**. Pass: a grade and findings within seconds; the grade header
names the rules it could not settle by what they say, with their ids only inside a fold, and shows
no fraction; **Show** on a finding selects its feature in J; a new run folder ending `-check`
holds `session.json`, `report.md` and `check.json`. Record: the grade line and the folder name.

### 5.2 Standards

Press **Standards** on part J and then on assembly A. Pass for each: a verdict with every check in
a bucket; `ready to release` only when there are no errors **and** no unresolved checks; no banner
about a missing profile; on A, the verdict notes `no drawing graded`. Record: both verdict lines.

### 5.3 Remodel

With part J open:

```powershell
Get-FileHash '<full path of part J>'; Get-Item '<full path of part J>' | Select-Object Length, LastWriteTime
```

Open the **Remodel** tab. Pass: it says
`Remodel is not in this build yet. This tab will not change the open part.` and offers nothing to
run. Go back to the Review tab and run the two lines again. Pass: the hash, size and time are
unchanged. Record: pass or fail.

### 5.4 The live Gemini test [008 T106]

The prompt hides the key as you paste it and keeps it out of the command history; the last line
clears it:

```powershell
$env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host 'Paste the Gemini key' -AsSecureString)))
cd "$R\reviewer"; uv run pytest tests/live/test_gemini_live_function_response.py -m live -rs -p no:warnings; cd $R
Remove-Item Env:GEMINI_API_KEY
```

Pass: `1 passed` and **no** `SKIPPED` line. A skip proves nothing: record it as not run, with the
reason the `SKIPPED` line gives. A failure saying the key was refused, or that the network never
reached the API, is setup, not the defect this test looks for; the defect is a failure beginning
`the forced tool call was rejected` or `a role="tool" function response was rejected`. Record the
last lines.

### 5.5 Before and after the Show fix, on the older build: last [009 T082]

This builds an older version, looks at one thing, and comes back. Close SOLIDWORKS (Don't Save).

```powershell
git checkout 9464b9e
.\extractor\tools\update-workstation.ps1 -NoPull -SkipTests
```

`9464b9e` is the build before the fix (`3e86d47`); `-SkipTests` only here, because this build is
only looked at. If SOLIDWORKS is not in its usual folder, this older script has no
`-SolidWorksRoot`; build with this line instead:
`dotnet build extractor\SwReview.sln -c Release -p:SwRedist='<SOLIDWORKS install folder>\api\redist'`.
Then start SOLIDWORKS, open A and part J, and:

1. With A active, press Review (the key is still in Settings) and wait for it to finish.
2. Make J active and press **Model check**.
3. Make A active again, and in the Review tab press **Show** on one of A's findings. Record what
   SOLIDWORKS selected: something in A, something in J, nothing, or an error.

Close SOLIDWORKS (Don't Save) and come back to the current build:

```powershell
git checkout main
.\extractor\tools\update-workstation.ps1 -NoPull
```

Pass: the script reaches `== health` as in step 1.3. Start SOLIDWORKS and repeat the three presses.
Pass: this time Show selects A's own entity. Record: both answers. The registration survives both
builds; nothing to register.

## Step 6. The handoff

This is `docs/workstation-runbook.md` section 8. Close SOLIDWORKS (Don't Save) first, so every log
is closed.

### 6.1 No key reached a file

```powershell
cd "$R\reviewer"; uv run swreview audit-secrets $runs "$env:LOCALAPPDATA\SwReview\logs" $H; "exit code: $LASTEXITCODE"; cd $R
```

Pass: `exit code: 0` and a line beginning `none: no configured secret appears in`. Fail: any line
naming a file: **do not zip or send anything**; call the owner. The output never shows the key
itself.

### 6.2 The exporter, on each review

The exporter, `swreview handoff`, makes a small, key-masked archive of one review with a manifest
of what it holds and what is missing. It is the quick summary; it is **not** the evidence, because
it leaves out `tool-results\` by design (6.3 carries the whole folders).

```powershell
cd "$R\reviewer"
Get-ChildItem $runs -Directory | Where-Object { $_.CreationTime -ge $since -and $_.Name -notmatch '-(check|standards|remodel)$' } | ForEach-Object { uv run swreview handoff $_.FullName --out "$H\exports\$($_.Name).zip" }
cd $R
```

Pass: one `wrote <archive>` per review and no `Missing artifacts: ` line. Record: any review with
a `Missing artifacts` line, and the files it names.

### 6.3 The whole run folders, the logs, the probe reports and the dumps

```powershell
$folders = Get-ChildItem $runs -Directory | Where-Object { $_.CreationTime -ge $since }
$folders | Select-Object Name
Compress-Archive -Path $folders.FullName -DestinationPath "$H\run-folders.zip"
Compress-Archive -Path "$env:LOCALAPPDATA\SwReview\logs\*" -DestinationPath "$H\logs.zip"
Get-ChildItem "$H\probes", "$H\dumps" | Select-Object Name
```

Pass: the list names every run folder of the sitting (the reviews, the `-check` and `-standards`
folders), both zips are written, and the probe reports and dump folders are listed. If
`Compress-Archive` stops on size, copy the folders instead with
`Copy-Item $folders.FullName "$H\run-folders" -Recurse`. The run folders hold vault paths: they
travel in the handover folder only and are never committed.

### 6.4 The findings document

Create `$H\pane-findings-<date>.md` (Notepad will do) in this shape, one section per step, each with
its result (pass, fail, or not run and why) and what the step said to record:

```text
# Workstation findings <date>

Commit: <from 1.4>   Versions: git, dotnet, uv, WebView2, SOLIDWORKS <from 1.4>
Documents: by letter only (the list is notes\documents.txt in the handover folder)

## 1. Update and health: 1.3, 1.6 (seven checks)
## 2. Profile and key [008 T101]
## 3.1 Dumps [010 T103 to T106]
## 3.2 [011 T062; 006 T103; 006 T105; 006 T107]
## 3.3 to 3.5 [011 T063]
## 3.4 [011 T068; 008 T101]
## 3.6 [011 T064]   ## 3.7 [011 T065]   ## 3.8 [011 T066]   ## 3.9 [011 T077]
## 4.1 [008 T103; 009 T079]   ## 4.2 [008 T102; 010 T107; 009 T079; 009 T080]
## 4.3 [008 T104]   ## 4.4 [009 T081]   ## 4.5 [009 T083]
## 4.6 [011 T067; 009 T084; 011 T077; 011 T101]   ## 4.7 [011 T101]
## 5.1 to 5.3 Model check, Standards, Remodel   ## 5.4 [008 T106]   ## 5.5 [009 T082]
## 6. Handoff: the audit, the exports, the zips
## What to look at first next time
```

No vault path, folder name, property name or value, template or sheet format name, and no key. The
probe reports, dump folders, zips, screenshots and `notes\` sit beside it in the handover folder.

### 6.5 Handing it over

If `git push` works from this machine, put the findings document, and only it, on a branch of its
own; otherwise skip this and hand over the folder.

```powershell
$date = Split-Path $H -Leaf
git checkout -b "workstation/$date"
Copy-Item "$H\pane-findings-$date.md" docs\
git add "docs\pane-findings-$date.md"
git commit -m "Workstation findings $date"
git push origin "workstation/$date"
git checkout main
```

If the commit or the push fails, undo it so the checkout is clean again, then hand over the
folder as below:

```powershell
git reset -q; Remove-Item "docs\pane-findings-$date.md" -ErrorAction SilentlyContinue; git checkout main; git branch -D "workstation/$date"
```

Never push `main`. Tell the owner the handover folder is ready: it travels by hand, whole.

### 6.6 The checkout is clean

```powershell
git status --porcelain; git branch --show-current
```

Pass: nothing, then `main`.

## Not in this sitting

- **011 T095**, the sitting after the development machine sets the two switches: T068's binding
  by decimal places, and the read-only open of a closed candidate from the pane, with the
  `gated=` line and the drawings line the add-in and backend lanes asked for then.
- **008 T105 and 009 T085**: the development machine replays and restores this sitting's run
  folders once they arrive.
- **Setting either switch**: the development machine, as section 3.10 says.
- Not asked this time, though open: feature 006's other seat tasks (T100 to T102, T104, T106, T108
  to T110), feature 004's re-modeler probes, and feature 007's T059 to T063.
