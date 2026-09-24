# Workstation test plan: the sitting for features 008 to 011

Written 2026-09-23 for the engineer who runs the next sitting on a licensed SOLIDWORKS seat. You do
not need to be a developer to follow it. Every step says what to do, gives the exact command to
paste, says what to look at, and says what counts as a pass and what counts as a fail. Write each
result in the **Results table** of the findings document as soon as the step ends: you start that
document once, on day 1, at step 1.4, from `docs/workstation-results-2026-09-23.md`, the results
sheet, which step 1.3's update brings to a checkout older than this plan. Each row is one step and
one task id, and takes `pass`, `fail` or `blocked`, the value you observed, and notes. Step 6
collects it.

Each step carries the task ids it answers in square brackets, with the feature in front, for
example **[011 T062]**: that is the row of `specs/011-drawing-context/tasks.md` the development
machine ticks from your result. The plan was built from what is on `main` with it: every seat task
(`[W]`) of features 008, 009, 010 and 011, and `docs/workstation-runbook.md`. The assistant's
version of the same sitting, with the reasons for its order, is
`docs/workstation-handover-2026-09-23.md`; **where this plan and the handover differ, follow this
plan.** Where this plan and a task text disagree, the task wins; write the difference down as a
finding.

## The rules for the whole sitting

1. **Save nothing in SOLIDWORKS.** When SOLIDWORKS asks whether to save, choose **Don't Save**. The
   product only reads your files, and this sitting proves it, so nothing else may change them
   either. The one write of the sitting is step 3.5's Pack and Go copy into a scratch folder under
   `%TEMP%`, which step 6.0 deletes. **Check nothing out of the vault** during the sitting: a file
   you have not checked out is read-only on disk, so a wrong Save cannot reach it. Steps 3.1, 3.5
   and 6.0 fingerprint your files and show whether anything changed.
2. **Edit no file in the checkout, and commit or push nothing.** The findings document travels in
   the handover folder; the owner reads it and commits it from the development machine (step
   6.5). Step 5.5 switches the checkout to an older build and back, and that is the one thing done
   to it. A wrong result is a finding to write down, never something to fix at the seat. The
   standards profile is the owner's: the one line you may change is the vault location (step
   2.2).
3. **Close SOLIDWORKS before building** (steps 1 and 5.5).
4. **Keys go in two places only**: the OpenAI key in the pane's Settings (step 2.5), the Gemini key
   at the prompt of step 5.4. Never in a file, on a command line, in a chat or in the findings
   document.
5. **In the findings document, call documents by their letters** (section 0.2), not by their file
   names; the two recorded assemblies may also be called the small assembly (A) and the big
   assembly (B), never by their numbers (the owner's decision 11B: no committed file names them).
   No vault path, folder name, property name or value, sheet format or template name goes in it.
   A run folder is named after its document: write it as its time stamp and letter (for example
   `20261001-101112-A`), never its name. Copy a log line only as far as the end of its `gated=`
   list; if it has `target=`, write that it did and how many paths, never the paths; replace any
   name inside `error="..."` with its letter.
6. **Do not click or type while a probe runs.** Probe D14 checks that the window in front and the
   active document do not change; your own click would fail it.
7. **A step that fails**: record what it says to record, look the failure up in "When a step
   fails" below, and mark every task it blocks as `blocked` in the Results table, with the step
   number (for example `blocked by 2.3`). Then go on, unless that section says to stop.

## When a step fails: what is still possible

The console steps (3.1, 3.2 items 1 and 3, 3.3, 3.5 items 1 and 2, 3.6 to 3.9) attach to the
running SOLIDWORKS directly and need neither the add-in nor the pane.

| What failed | What to do | What is blocked |
|---|---|---|
| SOLIDWORKS will not start (no licence, a crash at start) | **Stop.** Record the message. | everything but 5.4 and step 6 |
| A gate at 1.3 (a red line ending `failed with exit code <n>; nothing after it was run.`) | **Stop** and call the owner; see "Going back to the build you had" at the end | everything |
| The vocabulary download is refused and the owner's file is not at hand | **Stop**: the gate needs it | everything |
| 1.5 (registration), or 1.6 check 1 still failing after one retry | Go on with the console steps. The retry: read the `addin.log` line after the last good one and look it up in runbook section 7; restart SOLIDWORKS once; if SwReview's box is clear in Tools > Add-ins, tick it under **Active** and **Start Up** and restart; if SwReview is not listed at all, do 1.5 once | every pane step: `blocked by 1.6` |
| 1.6 check 2 (the badge never reads `Backend ready`) | Runbook section 7: check `uv --version` in a fresh window, then sign out of Windows and back in once | the Review tab's steps; Model check, Standards and the console steps go on |
| 2.3 (the profile is version 1 or 2) | Call the owner; the console steps and the Standards presses go on | 3.4 and step 4 (the paid reviews) until the owner rewrites it |
| 2.4 (the profile is invalid) | Tell the owner the field it names | as 2.3, and also 3.2 item 2, 3.5 item 3's Standards press and 5.2 |
| A key refused, no quota, or no connection at the first paid review | Step 4's box, item 6 | every paid step: `blocked: provider` |
| A lettered document cannot be found (section 0.2) | Mark its steps blocked, using the table's "Used by" column | those steps: `blocked: no document <letter>` |
| A dump at 3.1 fails | Retry once as 3.1 says, then go on: 4.2 still runs, because the pane extracts for itself | 010 T103 to T106 for that assembly |
| A D14 report at 3.9 ends `against confirmed-open.md: not as required: ...` | Go on: the switch stays off | nothing more |
| 6.1 or 6.5 names a leaked file | **Stop and send nothing**; call the owner | the handoff |

## If SOLIDWORKS stops answering (steps 3 to 5)

1. A probe or review that has printed nothing for 10 minutes, or a SOLIDWORKS title bar that says
   **Not Responding**: first look for a SOLIDWORKS message box behind other windows (Alt+Tab). A box
   waiting for an answer holds every call. Write down its title and first sentence, with no path,
   then answer **Cancel**, **No** or **Don't Save**.
2. If there is no box, press Ctrl+C in PowerShell and wait 5 minutes.
3. If SOLIDWORKS still does not answer, end it in Task Manager (**End task**). That never saves
   anything.
4. When SOLIDWORKS starts again and shows **Document Recovery**, close that pane without opening or
   saving the recovered files: they are older copies of real files.
5. Record the step, the time, the last line printed, and whether a crash report appeared. Reopen
   the documents and go on with the next step. Run a crashed probe once more, at most.
6. After a D14 run (step 3.9) that crashed or was stopped, restart SOLIDWORKS before any other step
   with J: a drawing opened hidden may still be loaded.
7. If SOLIDWORKS closes between 4.1 and 4.5, the review chips are gone. Review A again (its first
   review stays 008 T103's record), then A-pin and A-plate, before 4.4. The backend closes with
   SOLIDWORKS, so nothing keeps spending.

## How long it takes

About **10 hours at the seat**, best planned as two days: day 1 steps 1 to 3, day 2 steps 4 to 6.
Keep SOLIDWORKS open from step 4.1 to step 4.5 on day 2: the review chips of steps 4.4 and 4.5
live only as long as the SOLIDWORKS session. Before the sitting, allow **half a day** to find and
note documents C to M (section 0.2); a new machine (section 0.3) adds about an hour.

| Step | What | Estimate |
|---|---|---|
| 1 | Update, gates, health checks (registration only on a new machine) | 50 min |
| 2 | Profile and key | 20 min |
| 3 | Dumps, probes D1 to D14 and one pane review, with the fingerprints | 3 h 45 min |
| 4 | The pane reviews | 3 h |
| 5.1 to 5.4 | Model check, Standards, Remodel, the Gemini test | 30 min |
| 5.5 | The older build and back: two builds, two SOLIDWORKS restarts, two reviews of A | 1 h |
| 6 | Handoff | 45 min |

The dump of B (step 3.1) may take many minutes; do not click in SOLIDWORKS while it runs. The paid
model use is roughly 3 to 4 million input tokens over about ten reviews, most of them small,
against the 12.4 million of the one review of the big assembly at the last sitting; this is an
estimate from the replay's figures, not a measurement.

## 0. Before the sitting

### 0.1 What the owner brings, and decides

1. **This plan on GitHub.** The seat updates from GitHub (`origin/main`); the commit that added
   this plan, or a later one, has to be pushed before the sitting.
2. **The real standards profile at version 3**, carried by hand (step 2 says what it must hold). It
   never goes into the repository or into the findings document.
3. **The o200k_base vocabulary file** `fb374d419588a4632f3f557e76b4b70aebbca790`, from the
   development machine's `%LOCALAPPDATA%\SwReview\tokenizer\`, in case the seat's web filter blocks
   its download (step 1.3).
4. **An OpenAI key** for the pane's reviews, with **the model and reasoning effort** to use (the
   recorded runs used `gpt-5.6-luna` at `high`), and **a Gemini key** for step 5.4. The owner writes
   the model and effort, never a key, in `notes\documents.txt`.
5. **People**: the owner reachable by phone on both days (steps 1.3, 2.2 to 2.4, 6.1); the engineer
   who knows A, at step 4.1 and again at 4.2 (about 10 minutes each); a colleague who has not seen
   the result, at the end of B's review in step 4.2 (1 minute). Their names stay out of the
   findings document.
6. **Two decisions, written in `notes\documents.txt`**: the input-token cap at which B's review is
   stopped (step 4.2; if none is written, 3,000,000), and what to press when a **Before this
   review** panel appears (step 4's box, item 1; the default is **Review available evidence**).

### 0.2 The documents, named before the sitting

Find these before the sitting and write the list, letter by letter with the file each letter
means, in `notes\documents.txt` in the handover folder (the setup block below makes the folder;
`notepad "$H\notes\documents.txt"` opens the file). Also write `notes\paths.txt`: the full path of
every lettered file, one per line (Copy as path; the quotes are fine). Both files stay in the
handover folder and travel by hand; they are never pushed.

| Letter | What it must be | Used by |
|---|---|---|
| A | the small assembly of the last sittings (a machined plate and two dowel pins), and its pin and plate parts (A-pin, A-plate); its number is not in this plan, the owner writes it in `notes\documents.txt` | steps 3.1, 4.1, 4.4, 4.5, 5.2, 5.5 |
| B | the big assembly reviewed at the last sitting; its number is not in this plan, the owner writes it in `notes\documents.txt` | steps 3.1, 4.2, 4.3 |
| C | a drawing of six sheets with a revision table on a sheet other than the first; write down, per sheet tab, how many views you see | steps 3.2, 3.5 |
| D | an assembly, with D-1 and D-2 the drawings of two of its parts and D-X the drawing of a part that is not in it. At least one joint of D carries a model dimension with a tolerance or fit class, or a Hole Wizard hole with an ISO 286 fit class, so a stack-up runs. D-1 was last saved in SOLIDWORKS 2020 or later with Tools > Options > Performance > **Include detailing mode data when saving** turned on | steps 3.3, 3.4, 3.5 |
| E | a part opened from a vault view whose same-name drawing is not in the local cache | step 3.3 |
| F | a drawing with some dimensions at their own precision and some at the document's, and a model dimension and a reference dimension on one hole; the part it shows. Best: a drawing whose document dimension precision (Document Properties > Dimensions) differs from its units decimal places (Document Properties > Units) | step 3.6 |
| G | drawings that between them carry: a diameter, a hole callout and a geometric tolerance on known holes, on a part drawing (G-1) and on an assembly drawing of the same part (G-2); a counterbore callout; geometric tolerances, datums and surface-finish symbols; one table of each kind (bill of materials, revision, hole, general) | step 3.7 |
| H | a part drawing (H-part) and an assembly drawing (H-asm) whose callouts you name in advance: for each, the sheet, what it is, the hole it is on, that hole's diameter in millimetres, the unit it is written in (mm or in) and how many decimals it shows. Choose callouts that are **the only display dimension on their sheet**, so the sheet number alone identifies their lines in the report | step 3.8 |
| J | a part whose drawing of exactly the same name sits in the same folder | steps 3.9, 4.7, 5.1, 5.2, 5.3, 5.5 |
| K | an assembly in which one part's same-name drawing sits closed beside it (K-1), and two other parts (K-2, K-3) are each shown by two drawings you will open | step 4.6 |
| L | a weldment or sheet-metal part, if one exists (006 T105's cut-list item) | step 3.2 |
| M | a part and an assembly that each have at least two configurations (A-pin and A will do if they have) | step 4.4 |

### 0.3 A new machine only: install and clone

Skip this on a seat that already has the checkout. On a new machine, signed in as the account
that uses SOLIDWORKS:

1. Install, or have IT install: **Git for Windows**, the **.NET SDK** (8 or 9), **uv** (for this
   user), and the **Evergreen WebView2 runtime**. Then **sign out of Windows and back in**, so
   SOLIDWORKS will see uv on its PATH.
2. Open a new, non-elevated **Windows PowerShell** and check each (runbook section 2):

   ```powershell
   git --version; dotnet --version; uv --version
   foreach ($k in 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') { if (Test-Path $k) { 'WebView2 ' + (Get-ItemProperty $k -Name pv).pv } }
   ```

   Pass: a Git version, a .NET version starting 8 or 9, a uv version, and at least one `WebView2`
   line with a version. Fail: any red line or a missing line: install what is missing and check
   again.
3. Clone the checkout:

   ```powershell
   git clone https://github.com/coleas33/smart_SW.git C:\smart_SW
   ```

   Pass: it ends without a red line and `C:\smart_SW` holds `extractor` and `reviewer`. If Windows
   refuses to create `C:\smart_SW`, clone into `"$env:USERPROFILE\smart_SW"` instead. Whichever
   folder you used is `$R` in the setup block below. **On a new machine step 1.5 (registration) is
   required, not optional.**

## Every PowerShell window: paste this first

Use **Windows PowerShell** (the blue one), not elevated, signed in as the account that uses
SOLIDWORKS. Change the two lines marked `CHANGE` once. `$R` is **the smart_SW folder itself**, the
one that holds `extractor` and `reviewer` (on a new machine, `C:\smart_SW`), not the folder above
it. Paste the whole block into every new PowerShell window, on day 2 too, with the same date.

```powershell
$R = 'C:\<the path>\smart_SW'                                                   # CHANGE once: the smart_SW folder itself, the one that holds extractor and reviewer
$H = "$env:LOCALAPPDATA\SwReview\handover\<first day of the sitting, yyyy-MM-dd>"   # CHANGE once
$since = [datetime]::ParseExact((Split-Path $H -Leaf), 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
$findings = "$H\pane-findings-$(Split-Path $H -Leaf).md"
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

function Get-SeatHash {
    param([string] $path)
    $stream = [IO.File]::Open($path, 'Open', 'Read', 'ReadWrite, Delete')
    try { -join ([Security.Cryptography.SHA256]::Create().ComputeHash($stream) | ForEach-Object { $_.ToString('X2') }) }
    finally { $stream.Dispose() }
}

function Save-Fingerprint {
    param([string] $name)
    $paths = @(Get-Content "$H\notes\paths.txt" -ErrorAction SilentlyContinue | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ })
    foreach ($package in @(Get-ChildItem "$H\dumps" -Filter package.json -Recurse -ErrorAction SilentlyContinue)) {
        $paths += @(Select-String -LiteralPath $package.FullName -Pattern '"path":\s*"([^"]+)"' -AllMatches | ForEach-Object { $_.Matches } | ForEach-Object { [regex]::Unescape($_.Groups[1].Value) } | Where-Object { $_ -match '\.(sldprt|sldasm|slddrw)$' })
    }
    $rows = @(foreach ($path in @($paths | Sort-Object -Unique)) {
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path
            $hash = try { Get-SeatHash $path } catch { 'unreadable' }
            [pscustomobject]@{ Path = $path; Length = $item.Length; Written = $item.LastWriteTimeUtc.ToString('o'); ReadOnly = $item.IsReadOnly; SHA256 = $hash }
        }
        else { [pscustomobject]@{ Path = $path; Length = ''; Written = ''; ReadOnly = ''; SHA256 = 'missing' } }
    })
    $rows | Export-Csv "$H\notes\fingerprint-$name.csv" -NoTypeInformation -Encoding UTF8
    "fingerprint-$name`: $($rows.Count) files, $(@($rows | Where-Object SHA256 -eq 'missing').Count) missing, $(@($rows | Where-Object SHA256 -eq 'unreadable').Count) unreadable, $(@($rows | Where-Object ReadOnly -eq $false).Count) writable"
}

function Compare-Fingerprint {
    param([string] $name)
    $before = @{}
    foreach ($row in @(Import-Csv "$H\notes\fingerprint-before.csv")) { $before[$row.Path] = $row }
    $changed = @(); $compared = 0; $notCompared = 0
    foreach ($row in @(Import-Csv "$H\notes\fingerprint-$name.csv")) {
        $old = $before[$row.Path]
        if (-not $old -or $old.SHA256 -eq 'missing' -or $row.SHA256 -eq 'missing') { $notCompared++; continue }
        $compared++
        $hashesDiffer = $old.SHA256 -ne 'unreadable' -and $row.SHA256 -ne 'unreadable' -and $old.SHA256 -ne $row.SHA256
        if ($old.Length -ne $row.Length -or $old.Written -ne $row.Written -or $hashesDiffer) { $changed += $row.Path }
    }
    "compared: $compared | changed: $($changed.Count) | not compared (missing, or new since before): $notCompared"
    $changed | ForEach-Object { 'changed (terminal only, never in the findings): ' + $_ }
}

Set-Location $R
"checkout $R | handover folder $H | run folders $runs | checkout found: $(Test-Path "$R\extractor\tools\update-workstation.ps1")"
```

Pass: the last line names the checkout, the handover folder and the run folders (the run
folders appear with the first review or check), ends `checkout found: True`, and nothing above it
is red. A red `Cannot find path`, `Illegal characters in path` or `String was not recognized as a
valid DateTime` means a `CHANGE` line was not changed, or its date is not written `yyyy-MM-dd`.
`checkout found: False` means `$R` is not the smart_SW folder itself: fix the first line and paste
the block again.

Once, on day 1, when the block works: run `notepad "$H\notes\setup.ps1.txt"`, paste the block as
you edited it, and save. On day 2, press Windows+R, paste `%LOCALAPPDATA%\SwReview\handover` and
press Enter; open the sitting's folder, then `notes`, then `setup.ps1.txt`; select all, copy, and
paste it into the new PowerShell window. `explorer $H` opens the handover folder at any time.

What the commands do, so you know what you are running (each only reads):

- `Show-ReviewFacts '<run folder>'` prints the facts of one review: its tokens, findings, contacts,
  interference groups judged, which checks ran before the model's first round, its drawings line,
  its questions and answers, and a timing.
- `Show-DumpFacts '<dump folder>'` prints the counts feature 010's dump tasks ask for. It is the
  command of `specs/010-mechanical-checks/tasks.md` Phase 13, unchanged.
- `Show-Documents '<run folder>'` lists a review's documents with their ids: `doc:` and twelve
  letters and digits, like `doc:3f2a9c1b7e04`.
- `Show-SetupTime '<run folder>'` reads the backend log for how long the review's setup took.
- `Show-DrawingReadLog` prints the last three `drawing.read` lines of the tool-service logs; the
  last line printed is the newest.
- `Get-SeatHash "<full path>"` prints a file's SHA-256 while SOLIDWORKS may hold it open.
- `Save-Fingerprint '<name>'` records the size, write time and SHA-256 of every lettered file and of
  every document the dumps list, in `notes\fingerprint-<name>.csv`; `Compare-Fingerprint '<name>'`
  compares that record with the one named `before`. Both only read; hashing B's documents can
  take a few minutes.

If a `Show-` command prints a red Python traceback, copy its last line into the Notes of the step's
row, write `facts not read` there, and go on: the run folder travels in step 6.3 and the
development machine reads it there. The step's on-screen checks still count.

**Finding a run folder.** On the Review tab press **Open run folder**; on the Model check and
Standards tabs the button is **Open check folder**. In the Explorer window that opens, click the
address bar, copy the path, and paste it between the quotes of `$run = '<paste here>'`. If the path
holds an apostrophe (`'`), type it twice there.

**Finding a document's full path.** In File Explorer, hold Shift, right-click the file and choose
**Copy as path**. The path comes with its own double quotes: paste it over `"<...>"`, quotes
included. Every file or folder placeholder in this plan is written in double quotes for that
reason; only the run folder placeholders (`$run`, `$package`, `$pin`), copied from the Explorer
address bar, are in single quotes.

## The pane

SwReview's pane is in SOLIDWORKS's **Task Pane** on the right: the SwReview icon, whose tooltip is
`SwReview evidence extractor (read-only)`. It has five tabs: **Review**, **Extract**, **Model
check**, **Remodel** and **Standards**. Each tab that runs something has its own run button and
folder button: on the Review tab **Review** and **Open run folder**; on the Model check tab **Model
check** and **Open check folder**; on the Standards tab **Standards check** and **Open check
folder**. The badge at the top of a tab reads `Backend starting` or `Starting the review
backend...` while the backend starts, then `Backend ready` (with or without a full stop), or
`Error`. **Settings** is at the top of the Review tab.

## Step 1. Update the workstation

The findings document starts at 1.4: its results sheet arrives with the update, so a checkout
older than this plan does not have it before 1.3's pull. Until then, what 1.1 to 1.3 say to record
goes in `notes\update.txt` (`notepad "$H\notes\update.txt"` opens it), and 1.2 keeps the commit in
`notes\commit-before.txt`; at 1.4 you write 1.3's result in its row.

### 1.1 SOLIDWORKS is closed

```powershell
Get-Process SLDWORKS -ErrorAction SilentlyContinue
```

Pass: nothing is printed. Fail: a line naming `SLDWORKS`: close SOLIDWORKS (Don't Save) and run it
again.

### 1.2 The checkout is clean, on main, and what it was

```powershell
git status --porcelain
git branch --show-current
if (-not (Test-Path "$H\notes\commit-before.txt")) { git rev-parse --short HEAD | Set-Content "$H\notes\commit-before.txt" }
"commit before the update: $(Get-Content "$H\notes\commit-before.txt") | free on C: $([math]::Round((Get-PSDrive C).Free / 1GB, 1)) GB"
```

Pass: nothing from the first line, `main` from the second, then a commit and at least 10 GB free
(if the run folders are on another drive, check that drive has 10 GB too). The commit is written
once, the first time: running this again after the update keeps the commit the seat had. Fail:
any line from the first: **stop**, copy the lines into `$H\notes\update.txt`, and call the owner;
do not stash, delete or move anything. Any branch other than `main`: stop and call the owner; do
not merge on the seat. Less than 10 GB: free space first, or call the owner.

### 1.3 Update, build and gate

```powershell
git fetch origin; git log --oneline HEAD..origin/main
git pull --ff-only origin main; "pull exit code: $LASTEXITCODE"
.\extractor\tools\update-workstation.ps1 -NoPull
```

The first two lines bring the new build; the third builds it with the script that just arrived,
so its flags and health lines are the ones this plan describes (an older script, run before the
pull, would not know them). Add `-TokenizerFrom "<where the owner's vocabulary file is>"` to the
third line if the vocabulary could not be downloaded before, and `-SolidWorksRoot "<SOLIDWORKS
install folder>"` if SOLIDWORKS is not in `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS`. If
Windows says running scripts is disabled, run
`powershell -ExecutionPolicy Bypass -File .\extractor\tools\update-workstation.ps1 -NoPull`
instead, with the same additions.

Look at: `pull exit code: 0`, then each `== <step>` heading as it passes (fetch, `uv sync`,
`tokenizer fetch`, `pytest`, `ruff`, `dotnet build`, `dotnet test`), then the `== health` block at
the end.

- Pass: `pull exit code: 0`; the script reaches `== health`; the pytest line says `passed` with no
  `failed`; `dotnet test` says `Passed!` for both test projects; the health block prints
  `uv on PATH: <a path>` and `swreview-extract: <a path>`. `standards profile: MISSING` is expected
  on a new machine until step 2; `standards profile: present at` is expected otherwise.
- `Not possible to fast-forward` from the pull: someone committed on this machine. **Stop** and call
  the owner (runbook section 4).
- Fail: a red line ending `failed with exit code <n>; nothing after it was run.` **Stop the
  sitting**: copy the last 40 lines of the window into `$H\notes\update.txt`, call the owner, and do
  what the owner says: either run the script again with `-SkipTests` and write `on an ungated
  build` in the Notes of every row, or follow "Going back to the build you had" at the end.
- The script can also refuse before it builds, with a red line that is not a fail of the sitting.
  Fix the cause and run the third line again:
  - `SOLIDWORKS is running and holds SwReview.AddIn.dll open`: close SOLIDWORKS (Don't Save), and
    do 1.1 again.
  - `No SOLIDWORKS interops at ...`: add `-SolidWorksRoot`.
  - `The checkout has local changes`: go back to step 1.2.
  - `The checkout is on '<branch>', not main`: stop and call the owner. This seat keeps its own
    lane; do not merge here.
  - `git status failed`: the `$R` line of the setup block is wrong.
  - `A parameter cannot be found that matches parameter name`: the third line ran an older script;
    run the first two lines, then the third again.
- A refusal from the network at `== git fetch origin`, `== uv sync --all-extras` or `== dotnet
  build` (a web filter or proxy page in the output) is setup, not a defect: copy the lines into
  `$H\notes\update.txt`, write `blocked by 1.3: network` in the Results table, and call the owner. A
  download refused at `tokenizer fetch` is not a fail: run the third line again with
  `-TokenizerFrom` and the owner's file.

### 1.4 Which build this is, and the findings document

```powershell
git log --oneline -1; Test-Path docs\workstation-test-plan-2026-09-23.md
git --version; dotnet --version; uv --version
foreach ($k in 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') { if (Test-Path $k) { 'WebView2 ' + (Get-ItemProperty $k -Name pv).pv } }
```

Pass: the second line prints `True` (the checkout holds this plan, so it is this build or a later
one), and every other line prints a commit or a version. `False`: the update did not bring this
plan (section 0.1, item 1): stop and call the owner. No `WebView2` line at all: write
`WebView2: not found in the registry` and go on; the pane's tabs showing at 1.6 is the real test.

Then start the findings document, once:

```powershell
if (-not (Test-Path $findings)) { Copy-Item "$R\docs\workstation-results-2026-09-23.md" $findings }
notepad $findings
```

This copies the results sheet the update brought into the handover folder as
`pane-findings-<date>.md`, where the date is the handover folder's own date, the first day of the
sitting, and opens it; run again, on day 2 or later, it only opens the document you are filling in.
Pass: Notepad shows a document headed `# Workstation findings <date>`. A red `Cannot find path`
naming `workstation-results-2026-09-23.md` means the checkout does not hold this plan: the second
line of the block above printed `False`.

Write 1.3's result in its row, then the commit and versions above at the top of the document
(SOLIDWORKS's own version comes at 1.6), and anything `notes\update.txt` holds under the heading
of step 1. Keep the document open and fill in the Results table as each step ends (Ctrl+S saves).
Each result is one word:

- `pass`: every pass condition the step gives for this task held.
- `fail`: the step ran and a condition did not hold. Quote the line that shows it in Observed.
- `blocked`: the step could not run, or the case it needs did not arise. Name the step, letter or
  condition in Notes, for example `blocked by 2.3: profile version 1`, `blocked: no document K` or
  `blocked: B ended without an error card`.

A task spread over several rows passes only if every row passed, fails if any row failed, and
otherwise is blocked. Observed holds a count, a report file name, a run folder's stamp and letter,
or a quoted line: never a path or a name. What a step says to record in more detail goes under
that step's heading further down the document.

### 1.5 Registration, only when needed

Needed on a new machine (section 0.3), after the checkout moved, or when Tools > Add-ins in
SOLIDWORKS does not list SwReview at all. With SOLIDWORKS closed, open **Windows PowerShell as
administrator**, signed in as the account that uses SOLIDWORKS, then:

```powershell
cd "<the smart_SW folder, as in the setup block>"
.\extractor\tools\register-addin.ps1
```

If SOLIDWORKS is not in `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS`, run
`.\extractor\tools\register-addin.ps1 -SolidWorksRoot "<SOLIDWORKS install folder>"` instead.

Pass: a line starting `registered SwReview.AddIn, and enabled it for`, followed by one starting
`If the box is clear there`. Fail: any red line: copy it into `$H\notes\update.txt` and see "When a
step fails". Close the administrator window afterwards and carry on in the ordinary one. Write
`registration: done` or `registration: not needed` at the top of the findings document.

### 1.6 The health checks

Start SOLIDWORKS and open a **part** (not an assembly, not a drawing). Write SOLIDWORKS's version
and service pack from Help > About at the top of the findings document. Then:

```powershell
Get-Content "$env:LOCALAPPDATA\SwReview\logs\addin.log" -Tail 12
```

Every line of that log starts with its time in square brackets; read what follows it. These are
`docs/workstation-runbook.md` section 6:

1. Tools > Add-ins shows SwReview ticked, and the log above ends with `AssemblyRedirect
   installed.`, `Attached to SOLIDWORKS.`, `Task Pane created.`, `Review host started.`, with no
   line whose text after the `[time]` begins `The SwReview tool service`.
2. The Review tab's badge reads `Backend ready` (not `Backend starting` or `Starting the review
   backend...`, and not `Error`).
3. On the Model check tab, **Model check** on the open part gives a grade within seconds (step 5.1
   looks closer).
4. Standards gives a verdict: needs the profile, so it is read at step 2.4.
5. A review ends on screen: needs the key, so it is read at step 3.4.
6. The pane has five tabs: Review, Extract, Model check, Remodel, Standards. No Ask tab.
7. `git status --porcelain` still prints nothing.

Record: pass or fail for checks 1, 2, 3, 6 and 7 in the 1.6 row; on a fail, the log lines (each
after its `[time]`). A fail of check 1 or 2: "When a step fails" says what to try once and what
can still go on.

## Step 2. The standards profile and the key

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

### 2.2 Place the file [006 T100]

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\SwReview" | Out-Null
if (Test-Path "$env:LOCALAPPDATA\SwReview\standards.yaml") { Copy-Item "$env:LOCALAPPDATA\SwReview\standards.yaml" "$H\notes\standards.yaml.before" }
Copy-Item "<where the owner put the new file>" "$env:LOCALAPPDATA\SwReview\standards.yaml"
$settings = if (Test-Path "$env:APPDATA\SwReview\settings.json") { Get-Content "$env:APPDATA\SwReview\settings.json" -Raw | ConvertFrom-Json }
if ($settings -and ($settings.PSObject.Properties.Name -contains 'standards_profile_path')) { "profile setting: [" + $settings.standards_profile_path + "]" } else { 'profile setting: the default' }
```

Pass: the last line is `profile setting: the default`, or names
`...\AppData\Local\SwReview\standards.yaml` between the brackets: the pane reads the file you
placed (006 T100, the profile entry: `StandardsProfilePath` resolves it). Fail: `profile setting:
[]`, which means no profile is configured (the Standards tab refuses and reviews run without the
standards checks), or another file: stop and ask the owner which file the pane should read. The
one line you may change in the profile is `vault_root`, if the vault is mounted somewhere else on
this machine (runbook section 5). The backup in `$H\notes` is the old profile; it travels by hand
like the rest of the folder and is never pasted anywhere.

### 2.3 It is version 3 [008 T101]

```powershell
Select-String -Path "$env:LOCALAPPDATA\SwReview\standards.yaml" -Pattern '^version:'
```

Pass: `version: 3`. Fail: `version: 1` or `version: 2`: the paid reviews wait until the owner
rewrites it (the probes of step 3 can go ahead).

### 2.4 It is valid [006 T100]

In SOLIDWORKS, with any part open, go to the Standards tab and press **Standards check** once. It
makes a run folder ending `-standards`. Press **Open check folder** and copy the address bar,
then:

```powershell
$package = '<paste the -standards run folder>'
cd "$R\reviewer"; uv run swreview check standards --package $package --out "$H\notes\profile-check" --profile "$env:LOCALAPPDATA\SwReview\standards.yaml"; "exit code: $LASTEXITCODE"; cd $R
```

Pass: `exit code: 0` (the backend validates the profile; 006 T100). This is also health check 4:
the Standards tab gave a verdict. Fail: `exit code: 1` with a message naming a field: tell the
owner the field it names (do not paste the file's contents anywhere); nothing is graded until it
is fixed. If the pane cannot be used (step 1.6 failed), the package can come from the console
instead, with part J active: `swreview-extract dump --out "$H\dumps\profile-J" --profile standards`,
then `$package = "$H\dumps\profile-J"`.

### 2.5 The OpenAI key

In the pane's Review tab press **Settings**. The Model list comes from the provider using the saved
key, so the key goes in first:

1. Choose Provider `openai`, paste the key into **API key**, and press **Save**.
2. When the badge reads `Backend ready` again and the note under the key field says
   `A key is stored for this Windows account. Leave this blank to keep it.`, press **Refresh**
   beside Model. (Before a key is saved the list may say `No model list yet. Press Refresh.`)
3. Choose the Model and Reasoning effort the owner wrote in `notes\documents.txt`, leave the key box
   blank, and press **Save** again.

Pass: the key note as above, the badge reads `Backend ready` after the second save, and Settings
shows the model and effort you chose. Record: the provider, model and effort (never the key). Save
does not test the key: the first paid review, step 3.4, does.

The second half of 008 T101, that a review runs `check_standards` before the model's first round,
is read at the first review, step 3.4.

## Step 3. The extractor: dumps and probes

**How to read every probe run in this step.** Each `swreview-extract probe drawings` run prints
its report and writes the same lines to a new file `drawings-probe-<time>.txt` in `$H\probes`; it
never overwrites one. It prints ids, counts, answers and millimetres only, never a name or a
value. After each run look at:

- the `exit code:` line: `0` means the run completed; `1` means it was refused, stopped, or could
  not write its report. Any other number (often a large negative one) means the console itself
  crashed: copy the last 20 lines, note whether a `drawings-probe-<time>.txt` file was written,
  retry once, then go on ("If SOLIDWORKS stops answering");
- a time-stamped line `Attached to the running SOLIDWORKS session.` before the report: that is
  normal;
- the line after the report, `Wrote <file>`: anything else printed there is a message to copy
  into the findings document, after checking it names no path or value;
- the gate log at the end, which must read `mutating members: none`, `refusals: none`,
  `sheet activation: none`, `document opening: none` and `display state: none`, and the last line
  `gate log: the confirmed open's guard (DrawingOpenGuard, D14 only): none` on every run but
  step 3.9's. At step 3.9 that last line lists what the confirmed open's guard saw: in run 1
  `GetOpenDocumentByName, ISldWorks.DocumentVisible, ISldWorks.OpenDoc6, ISldWorks.CloseDoc`, in
  run 2 `GetOpenDocumentByName` alone.

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
prints and the last line of `extract.log`: a time stamp, then `gated=` and the members.

- 010 T103, pass: in the `documents` line, `mass_overridden read` equals `documents`, and
  `mass_override gaps` is `0`.
- 010 T104: record the `holes` line, with the fit and thread classes it prints. The seat's pass is
  provisional: `Hole.wizard filled` is above 0 wherever the models use Hole Wizard holes. The
  development machine counts, from the dump folder, the holes whose source feature is a Hole Wizard
  feature, and passes T104 only when every one has `Hole.wizard`, each field filled or named in a
  gap. Write `provisional` in the row's Notes.
- 010 T105: `model_dimensions` and `model_annotations` are above 0 where the models carry DimXpert
  or MBD dimensions, and 0 where they do not. Say whether the team uses DimXpert or MBD.
- 010 T106, pass (on B): `fasteners 68` and `with a shank face 68`: the 68 named screws, each with
  its shank face, and nothing else. Its other half, the engagement those faces make possible, is
  read from B's review (step 4.2).
- Fail: any of those numbers otherwise.
- `exit code: 1`: run `Get-Content "$H\dumps\A\extract.log" -Tail 8` and record the lines from
  `dump failed.` on, after checking they hold no path. Retry once into a new folder, `$H\dumps\A-2`
  (so each attempt keeps its own log), and use that folder in the two lines after it.

Record: the four lines and the `gated=` line for A and for B. Say whether `GetOverrideOptions`
appears in the `gated=` line: it appears only when the first way of reading a mass override gave
no answer on some document.

Then, with both dumps done, fingerprint your files:

```powershell
Save-Fingerprint 'before'
```

Pass: `0 missing`. A missing file means a line of `notes\paths.txt` is wrong: fix it and run the
line again. Record the whole line in the `real files fingerprinted` row. The `unreadable` count is
the files SOLIDWORKS would not let anyone read while open; they are compared by size and write
time only. The `writable` count is how many files a wrong Save could change (rule 1).

### 3.2 A multi-sheet drawing on its own [011 T062; 011 T064; 006 T103; 006 T105; 006 T107]

1. Open drawing C and click its sheet 1 tab. Then:

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of C>" --probe D1,D11; "exit code: $LASTEXITCODE"
   ```

   Look at D1: `completed in <n> ms`, the phases row, the `drawing records ..., sheets <n>, views
   <n> (by sheet: ...)` line, and the gap kinds with their counts. Look at D11 (the drawing
   `contracts/probes.md` names for it, so this run is 011 T064's D11): per sheet, the
   `GetProperties2` item count, the scale, first angle, whether `GetTemplateName` is present, and
   the preferences 13, 47 and 65.
   - 011 T062 and 011 T064 (D11), pass: exit code 0 and the gate log as the box says.
   - 006 T103, pass: D1's `completed in` is under 10,000 ms; its `sheets` is 6; and its `by sheet`
     view counts equal the ones you wrote down for C (section 0.2), or D1 lists a gap of that kind.
     The rest of T103 (every referenced document, display dimension, annotation, revision-table
     row and note read or named in a gap) the development machine reads from item 2's run folder.

   Record: the report's file name, the D1 `completed in` time and the `drawing records` line.
2. With C still the active document, on the Standards tab press **Standards check** (006 T107).
   - Pass: a verdict with every one of the sixteen checks in a bucket; the words
     `no drawing graded` do **not** appear (the drawing is graded); every model the views show is
     graded once; no new window opens (SOLIDWORKS's Window menu lists the same documents before
     and after); **Open report** shows a report that says `nothing was rebuilt`. The case of a
     model that is not loaded is created at step 3.5.
   - 006 T105, the page half: a finding whose subject is on the drawing (a sheet, a view, a
     dimension, an annotation, a note or a revision table), or a data-card property, shows **no
     Show button**.
   - Fail: any of these otherwise. Record: the verdict line and the counts per bucket.
3. The Standards probe on the same drawing (006 T103 and T105):

   ```powershell
   swreview-extract probe standards --doc "<full path of C>" | Out-File -FilePath "$H\probes\probe-standards-C.txt" -Encoding utf8; "exit code: $LASTEXITCODE"; Get-Content "$H\probes\probe-standards-C.txt"
   ```

   Pass: exit code 0, and at the end `mutating members: none` and `sheet activation: none`. Copy any
   line printed above the report (it went to the screen, not the file) into your notes, after
   checking it names no path. If you have a weldment or sheet-metal part (L), open it and run the
   same line with its path and `probe-standards-L.txt`: that is the one kind, the cut-list item, the
   drawing cannot show. Without L, write `partial: cut-list item not probed` in the 006 T105 row.
   Record: the file names; the development machine reads PROBE-4 to PROBE-7 and PROBE-10 out of
   them.

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
3. Open part E (the vault-view part whose drawing is not cached). In the vault view, the drawing's
   icon shows it is not local (greyed). If the company has no vault view, write `blocked: no vault
   view` and skip this item.

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of E>" --probe D13; "exit code: $LASTEXITCODE"
   ```

   Look at D13: `File.Exists <true or false> in <n> ms`, the directory entry before and after, and
   `the local copy changed across the check: <true or false>`. Record all three. A time above
   1,000 ms, or `true` on the last line, is the answer that makes the development machine skip the
   candidate check under a vault view (`contracts/probes.md` section 3): record it; it is not a fail
   of the sitting, but it leaves 011 T063 open until the development machine lands that rule, so
   write `open: vault-view rule` in the row's Notes.

### 3.4 The pane review of assembly D [011 T063; 011 T068; 008 T101]

This is the sitting's first paid review; step 2 must be complete. Keep D, D-1, D-2 and D-X open,
and click D's window so the assembly is the active document. Note the documents SOLIDWORKS's Window
menu lists. On the Review tab press **Review**; if a **Before this review** panel appears, step 4's
box, item 1, says what to press. Wait for `The review has finished.` or `Waiting for your
answers.`; if it ends on `The review stopped`, step 4's box, item 6. Copy the run folder (Open run
folder), then:

```powershell
$run = '<paste the run folder>'
Show-ReviewFacts $run
```

- 011 T063, pass: the `drawings line` names D-1 and D-2 as read and does not name D-X; the
  summary at the top of Results shows the same line; the Window menu lists the same documents as
  before (nothing was opened); the review finished. Record the `drawing phase` time: it is
  discovery's time (with the reading of D-1 and D-2), and a candidate check that fetched a file or
  stalled shows there as extra seconds.
- 008 T101, pass: `pre-run tools:` includes `check_standards`, and **Open report**, searched
  (Ctrl+F) for `standards.release`, finds it: the standards findings are in the session. Fail:
  either is missing, or the profile was not version 3. This review is also health check 5.
- 011 T068, pass: the drawings were compared with the profile's drawing section. Open the **Not
  reached** fold at the bottom of Results: either a `drawing_profile.conformance` line that says
  the drawing `agrees with the profile's drawing standard in` some settings, or a finding that says
  a drawing `differs from the company's drawing standard` and names only the drawing's own values.
  Fail: a line saying the profile `which has no drawing section`. Then search the report (Ctrl+F):
  - `drawing callouts are read but not yet validated on a seat` found: pass for this sitting (the
    general tolerance's answer names the seat validation; the binding itself waits for the switch,
    section 3.10);
  - not found, but `no tolerance source is read for this package` found: no stack-up asked the
    drawing, so T068 cannot be judged at this sitting: write `blocked: no tolerance source on D`
    (row D of section 0.2 asks for one);
  - neither found: write `fail: not found`; the development machine reads the run folder before
    the task is judged.

Answer any questions the review asks (step 4's box, item 5, says how), then go on.

### 3.5 The views of other sheets, views out of date, and a model not loaded [011 T063; 006 T107]

1. Open drawing C and click its **sheet 3** tab (D3 asks for a six-sheet drawing with sheet 3
   active):

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of C>" --probe D3; "exit code: $LASTEXITCODE"
   ```

   Pass: the `active sheet:` line reads `position 3 before the run, 3 after, unchanged true`, and
   each sheet's views are listed.
2. A view out of date, **on a copy**, so no real file is ever changed. Close everything with
   Window > Close All, choosing **Don't Save**. Make a scratch folder and keep the path it prints:

   ```powershell
   (New-Item -ItemType Directory -Force "$env:TEMP\swreview-scratch").FullName
   ```

   Open D-1 on its own, then File > **Pack and Go**: include D-1 and the part it shows, choose
   **Save to folder** with the printed path, set **Add prefix** to `ZZ-`, press **Save**, and close
   D-1 (Don't Save). Open the `ZZ-` drawing from the scratch folder, then the `ZZ-` part it shows.
   Change one of the part's dimensions and rebuild (Ctrl+B). Then:

   ```powershell
   swreview-extract probe drawings --out "$H\probes" --doc "<full path of the ZZ- drawing>" --probe D12; "exit code: $LASTEXITCODE"
   ```

   Look: `IsModelOutOfDate true` on that view. Close both copies (Don't Save).
3. Detailing mode, and a model that is not loaded. With nothing else open (Window > Close All,
   Don't Save), File > Open D-1 with Mode **Detailing**. If Detailing is not offered, write
   `blocked: no detailing data in D-1` in both rows of this item and go on. Otherwise run the D12
   line with D-1's own path: `detailing mode true`. Then, with D-1 still active in Detailing mode,
   on the Standards tab press **Standards check** (006 T107, the not-loaded half). Pass: the model
   D-1 shows appears as a gap and as an unresolved check, no window opens (the Window menu is
   unchanged), and **Open report** says `nothing was rebuilt`. Close D-1.

Record: the three report file names and the lines named above. Then check your files:

```powershell
Save-Fingerprint 'after-3.5'; Compare-Fingerprint 'after-3.5'
```

Pass: `changed: 0`. On a change: look the file up in the vault's history. A new version checked in
by someone else explains it: write the letter and the reason. Otherwise it is a fail: stop, tell
the owner, and leave that file closed.

### 3.6 Precision, tolerance and names [011 T064]

Open drawing F; the part it shows opens with it.

```powershell
swreview-extract probe drawings --out "$H\probes" --doc "<full path of F>" --probe D4,D5,D8,D11; "exit code: $LASTEXITCODE"
```

- If the report says the part `is not open, so it was not read (nothing is opened)`, open the part
  (File > Open) and run the line again.
- D4: the `document:` line gives the drawing's preferences, among them `24
  (swDetailingLinearDimPrecision) <n>` and `49 (swUnitsLinearDecimalPlaces) <n>`; then, for each
  dimension, `GetPrimaryPrecision2`, `GetPrimaryTolPrecision2`, `GetUseDocPrecision`, `GetUnits`
  and `GetUseDocUnits`. Now the question T064 asks, which of 24 and 49 decides a dimension that
  uses the document's precision: in SOLIDWORKS click one dimension of F whose precision follows the
  document (its PropertyManager, under Tolerance/Precision, shows the document's precision), count
  the decimals it shows on the sheet, and press Esc. Write the count in `notes\documents.txt` (a
  count, never the value).
  - The count equals 24's number: the product reads the right preference.
  - It equals 49's number and not 24's: T064's one-line change to `written_precision` is needed,
    on the development machine (never here). Write that in the row's Notes.
  - 24 and 49 print the same number: not decidable on F; write `not decidable: 24 equals 49`.
- D5: each dimension's tolerance next to the part's, ending `; agree true` or `; agree false`.
- D8: each dimension's full-name shape next to the part's, ending `FullName equal true` or
  `FullName equal false`.

Pass: exit code 0, gate log as the box says, and the part read. Record: the file name, the D4
`document:` line with your count, and how many `agree false` and `FullName equal false` lines
there are.

### 3.7 Callouts, symbols and tables [011 T065]

Run this once on each G drawing (G-1, G-2 and whichever carry the counterbore, the symbols and the
tables), with the part each shows open. **Before each run**, write in `notes\documents.txt` what the
drawing visibly carries: the number of hole callouts, geometric tolerances, datums and
surface-finish symbols, and the tables by kind with their row counts.

```powershell
swreview-extract probe drawings --out "$H\probes" --doc "<full path of G-1>" --probe D1,D6,D7,D9,D10; "exit code: $LASTEXITCODE"
```

- D1: the gap kinds with their counts (`gaps <n>: <kind>/<entity kind> <n>, ...`).
- D6: each dimension's and annotation's attached faces; per face either
  `the part's face phase fac:<n> (<kind>, radius <r> mm)` or
  `no face the part's face phase described has this reference`.
- D7: `hole callouts in the extraction: <n>`, then each hole callout's variables and the lengths of
  `GetText(1)` to `GetText(4)`, and the whole text's length by position.
- D9: `geometric tolerances <n>, datums <n>, surface finishes <n>`, then the frame, slot and label
  counts. D10: `tables <n>, revision tables <n>`, then each table's type (0 general, 1 hole table,
  2 bill of materials, 5 title block, 9 general tolerance), its rows and readable cells, and for a
  bill of materials how many rows' documents are open.

Pass: exit code 0, the gate log as the box says, and each count of D7, D9 and D10 equals yours, or
D1 lists a gap of that kind. A count below yours with no such gap is a **fail**: a value silently
absent. Record: the file names, your counts beside the report's, and every `unread`.

### 3.8 The named callouts [011 T066]

Open H-part, then H-asm, each with its part open, and run on each:

```powershell
swreview-extract probe drawings --out "$H\probes" --doc "<full path of H-part>" --probe D4,D5,D6,D8; "exit code: $LASTEXITCODE"
```

For each callout you named in `notes\documents.txt`, find its lines **by its sheet number**: each
dimension's line names its id and `sheet <n>`. D4 prints one line per dimension, so if D4 shows
more than one dimension id (`ddm:...`) on that sheet, record every line for that sheet and write
`not decidable: <n> dimensions on sheet <s>`; never pick one by its radius, which is the thing
under test.

- D6: the face line must read `the part's face phase fac:<n> (cylinder, radius <r> mm)` with `<r>`
  half the named hole's diameter (a 10 mm hole reads `radius 5.0000 mm`).
- D8: `FullName equal true`. D5: `; agree true`.
- D4, the unit and decimals: the unit is the callout's `GetUnits` when it reads `GetUseDocUnits
  false`, or the `document:` line's `47 (swUnitsLinear)` when it reads `GetUseDocUnits true`; 0 is
  mm and 3 is inches. The decimals are its `GetPrimaryPrecision2` when it reads `GetUseDocPrecision
  false`, or the preference step 3.6 found governing (24, unless 3.6 found 49) when it reads
  `GetUseDocPrecision true`. Both must equal what you named.

Pass: every named callout ties to its hole that way, on both drawings. Fail: any
`no face the part's face phase described has this reference`, a radius that is not the named
hole's, `FullName equal false`, `agree false`, a unit or decimals that are not the ones you named,
or the part not read. Record: one line per callout, matched, not matched or not decidable, with
the line that shows it. No probe prints a dimension's value, so the value half of T066 rests on the
radius tie alone: that difference from the task text is itself a finding, and it is already
written here. **Change nothing**: the switch this decides is set on the development machine
(section 3.10).

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

The last line of each D14 section is the probe's own reading; any `not as required: ...` there is
a fail and names what failed. Record: both report file names, both last lines, the `open
documents` and `left loaded afterwards` lines (recorded, never a fail), and every line that
differs from the blocks above. Change nothing: section 3.10 says who sets the switch.

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
   `no face the part's face phase described has this reference`. A callout recorded `not decidable`
   keeps the switch off.
3. Each named dimension reads `FullName equal true` in D8 and `; agree true` in D5.
4. For every dimension with `GetUseDocPrecision true`, the decimals shown on the sheet equal
   preference 24 as D4 reads it, and preference 24 is not `-1` or unread. If they equal preference
   49 instead, T064's one-line change to `drawings/native.written_precision` lands first, in its own
   commit.
5. Every named callout's unit and decimals, resolved from D4 as step 3.8 says, equal what the
   engineer named.

How, on the development machine: in `reviewer/src/swreview/drawings/binding.py` change
`DRAWING_BINDING_VALIDATED: bool = False` to `True`; edit the one test that reads the shipped
value, `test_drawing_binding.test_the_switch_ships_off` (011 T094); add the known case, made
fictional, as a regression row in `test_drawing_binding.py`; and, as T066 says, extend the check
restated after a confirmed read to `check_joints`, with its test; the gates green; T066 ticked. Any
mismatch keeps it off, and research R4 records why.

## Step 4. The reviews

**How to read a review, every time in this step.**

1. Press **Review** with the document active. If a panel headed **Before this review** appears
   instead (`<n> of <n> component instances are not resolved. <n> gaps were recorded while reading
   the tree. No review tokens have been used.`), copy its first line into your notes, change
   nothing in SOLIDWORKS (do not resolve or unsuppress anything: that would change the design
   under review), and press **Review available evidence**, unless the owner wrote otherwise in
   `notes\documents.txt`. The same panel can appear after Retry. The Results view then shows
   `The review is running.` Wait for `The review has finished.` or `Waiting for your answers.`
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
4. Press **Transcript**: its head shows the usage line,
   `<n> uncached + <n> cached input - <n> tokens in all - <n> round trips - last round <n> s`.
   Uncached plus cached is the review's input. Press **Results** to go back.
5. **Questions**: when **Questions for you** appears above Start here, it shows `Question 1 of
   <n>` with **Previous** and **Next**. Choose an answer on each question (or type one, or press
   **Skip for now**), then press **Send answers** once, for all of them together. Before sending,
   note the sentence beside Send, `Sending resumes the review once. Its last round sent <n> input
   tokens.` In every step except 4.6 and 4.7, answer a same-name drawing question `Review without
   it`.
6. **A review that stops.** If it ends on a card headed `The review stopped`, record the card's
   sentence, and the class and message from its fold, with no path.
   - If they name the provider (a refused key, no quota, a rate limit, no connection), press
     **Retry** once only. If it stops the same way, the key or account is the problem: carry on with
     the console steps, and mark every paid step `blocked: provider` until the owner gives a working
     key.
   - For any other stop, press **Retry** once. The retried run is the one the step reads; say so in
     the Notes.
   - A review that shows `The review is running.` with no new round in the Transcript for 15
     minutes counts as hung: press **Stop** and treat it as stopped.

**A chip does not switch SOLIDWORKS's document.** The row of chips above Results holds one chip per
review of this SOLIDWORKS session. Pressing a chip shows that review; if its document is not the
active one, the review hides and the pane says `This review is of <document>. Press Review to
review <active document>.` Do **not** press Review then: it starts a new paid review. Make the
chip's document active first (SOLIDWORKS's Window menu); the pane then shows its newest review by
itself, or press its chip. Pressing the chip of the review already on screen does nothing: press
**Clear review** first.

### 4.1 A, the small assembly [008 T103; 009 T079]

Open A resolved and make it active; press Review (the box above). Note the time it started and
finished.

- 008 T103, pass: the `tokens` line's `input` is **at most 300,000**. The last sitting's reviews of
  the small assembly took 1.47 million and 1.58 million. Fail: above 300,000. The task counts the
  report's total, so if you answered questions (last bullet), judge on the `tokens` line after the
  answers; if only that line is above 300,000, write `fail` and say so in the Notes: the
  development machine decides whether the answers' turn counts.
- Record the `pre-run tools called again after the first model round` line every time: it names
  the checks the model repeated, and a repeat fails T103 by design.
- `pre-run tools:` names the checks that ran before the model's first round (checks first): the
  three `check_rms_...` checks, `bridge_interference`, `check_interference_group`, `check_joints`,
  `check_mass_material`, `check_hygiene` and `check_standards`, and `check_drawings` when the
  review found drawings. Record the line.
- `interference groups ... | not judged 0`: every detected group judged, as a finding or a contact.
- The comparison of the findings with the recorded small-assembly findings is the development
  machine's (008 T105): record the `findings` and `contacts` counts.
- 009 T079: read the summary with the engineer who knows A. Pass: they agree the **Decide** line
  names the decisions that are theirs, and the `not reached` goals are the ones the review did not
  reach. Record their words.
- If the review asked questions, answer them all in one send (box, item 5) and run
  `Show-ReviewFacts $run` again: record both `tokens` lines, before and after.

Record: the facts, the headline, the Decide, Fix and Verify lines, the goal lines, the drawings
line (with letters in place of names), the usage line, and the start and end times.

### 4.2 B, the big assembly [009 T080; 008 T102; 010 T107; 010 T106; 009 T079]

Open B resolved and make it active; press Review. Note the start and end times. While it runs,
every 15 minutes press **Transcript**, read the usage line, and press **Results** again without
scrolling. If uncached plus cached passes the cap the owner wrote in `notes\documents.txt`
(3,000,000 if none) before B finishes, press **Stop**: 008 T102 fails at that figure; read the
rest of 4.2 from what is on screen.

- **009 T080, first, before you touch the pane or run anything**: as soon as `The review has
  finished.` or `Waiting for your answers.` appears, call the colleague who has not seen the result
  over, show them the Results view for ten seconds, and ask how many decisions are theirs and which
  goals were not reached. Pass: they say the Decide count and the goals marked `not reached`.
  Record their answer. If no colleague who has not seen it is available, write `blocked: no
  colleague` in the ten-second row; the screenshot row still runs.
- 009 T080, the screenshot, next: make the docked pane 300 pixels wide and 600 high (drag its edge;
  un-maximize SOLIDWORKS and size its window). At a display scale of 125 percent that is 375 by 750,
  at 150 percent 450 by 900 (Windows Settings > System > Display > Scale). Press Windows+Shift+S,
  snip the pane, then:

  ```powershell
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  $shot = [Windows.Forms.Clipboard]::GetImage()
  if ($shot) { "snip: $($shot.Width) x $($shot.Height) pixels" } else { 'no picture on the clipboard: snip again' }
  ```

  Adjust the pane and snip again until the size is within 10 pixels of the target either way,
  then save it:

  ```powershell
  $shot.Save("$H\notes\pane-300x600-B.png", [Drawing.Imaging.ImageFormat]::Png)
  ```

  Pass: the headline, the three groups and every `not reached` goal are in the picture without
  scrolling. Only then go on to the facts below.
- 008 T102, pass: the `tokens` line's `input` (uncached plus cached) is **at most 995,853**, against
  the **12.4 million** of the same review at the last sitting; the usage line shows uncached and
  cached as two numbers, and so does the report's Tokens section (Open report). Fail: above
  995,853. With answers sent, judge as step 4.1 says: the report's total, both lines recorded.
- 008 T102 and 010 T107, pass: `not judged 0`; the contacts appear in their own fold after the
  findings, `<n> size-for-size contacts`, and no Start here row has the same title as a row in that
  contacts fold; `pre-run tools:` includes `check_joints`, `check_mass_material` and
  `check_hygiene`; and the next line, `called again after the first model round`, names none of
  the three (no model round spent on them).
- 010 T106, the engagement half: nothing to read on screen. The development machine counts, from
  B's run folder, the screws whose thread engagement is computed, against the last sitting's run
  of B (the screws that had no shank face before now compute). Record B's run folder stamp in the
  row.
- Record the `findings`, `contacts`, `interference rows` and `gaps` counts. The comparison with the
  99 findings recorded last time, by subject, is the development machine's (008 T105): the
  standards findings now come from the real profile, not the example, so the counts will differ.
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
there is nothing to press: write `blocked: B ended without an error card` in the Retry row, and do
not stop or restart anything to make one. (The task asks for Retry on B's run folder; whether to
amend 008 T104 for a review that ends cleanly is the owner's decision after the sitting.) If the
card is there, press **Retry** once (box, item 6); when the new review finishes, copy its run
folder into `$run` and run `Show-ReviewFacts $run` and `Show-SetupTime $run`. Pass: the new run's
`interference rows in package.json` and `gaps` are no more than B's, with `not judged 0`; the
development machine compares the group keys the two runs judged (the task's "the same groups are
judged"). Retry makes a new run folder and extracts again; it does not reuse B's.

### 4.4 Two part reviews, and switching configuration [009 T081]

Keep SOLIDWORKS open from step 4.1 to step 4.5. Open A-pin and make it active; press Review and
wait for it to finish. Then the same for A-plate. The row of chips above Results now holds B, A,
A-pin and A-plate, each with its configuration and time.

This needs M: a part and an assembly that each have two configurations (A-pin and A, if they
have; otherwise review M's part and assembly the same way first).

1. Make the assembly active in SOLIDWORKS; its review shows by itself (or press its chip). Open the
   ConfigurationManager (the tab above the feature tree) and double-click the other
   configuration. Pass: the review hides, and the pane says
   `This review is of <the document> [<its configuration>].` and what to press instead (do not
   press it). Double-click the first configuration again. Pass: the review comes back.
2. The same with the part: make it active, let its review show, switch, switch back.
3. During a running turn: make the assembly active; type a short follow-up question in the box at
   the bottom and press **Send**; while it runs, switch configuration. Pass: **Stop** stays
   available. Press it: the turn ends. Switch back.

Record: each pass or fail. Save no configuration change.

### 4.5 The review chips [009 T083]

1. Press **Transcript** and note the usage lines of A, A-pin and A-plate: for each, make its
   document active in SOLIDWORKS (Window menu); its review shows by itself, or press its chip. Then
   do the same round again. Pass: each review comes back with its own usage line unchanged:
   restoring spends no tokens. If the pane says `This review is of ... Press Review to review ...`,
   do **not** press Review (the box above).
2. Press **Settings**, then **Save** without changing anything: the backend restarts. When the
   badge reads `Backend ready` again, make A active, press **Clear review**, then press A's chip.
   Pass: A's review comes back with the sentence
   `The backend restarted, so this review is shown from its run folder. Follow-ups, decisions and answers are off.`
   (If Clear review is disabled, show another document's review first, then come back to A.)
3. Make A-pin active and press its chip; press **Open run folder**, copy the address bar, and close
   that Explorer window. Then copy A-pin's run folder into `$H\kept`, so nothing is lost, and delete
   the original only if the copy is whole:

   ```powershell
   $pin = '<paste the run folder of A-pin>'
   $pin = $pin.TrimEnd('\')
   if ((Split-Path $pin -Parent) -ne $runs.TrimEnd('\') -or -not (Test-Path -LiteralPath "$pin\session.json")) { 'not a run folder under the run root: nothing copied, nothing deleted' }
   else { try { Copy-Item -LiteralPath $pin "$H\kept" -Recurse -ErrorAction Stop; $kept = Join-Path "$H\kept" (Split-Path $pin -Leaf); if (@(Get-ChildItem -LiteralPath $kept -Recurse -File).Count -eq @(Get-ChildItem -LiteralPath $pin -Recurse -File).Count) { Remove-Item -LiteralPath $pin -Recurse; 'kept and deleted' } else { 'the copy is incomplete: nothing deleted' } } catch { 'the copy failed: nothing deleted. ' + $_.Exception.Message } }
   ```

   Pass: `kept and deleted`. Any other line: nothing was lost; fix the cause (the pasted path, free
   space) and run it again. Then press **Clear review**, then A-pin's chip. Pass:
   `This review can no longer be restored.` with a **Remove** button; Remove takes the chip away.

Record: each pass or fail. From here on SOLIDWORKS may be closed and reopened.

### 4.6 Drawing questions, three answers in one send, and a confirmed candidate left closed [011 T067; 009 T084; 011 T077; 011 T101]

Open assembly K with K-1's same-name drawing **closed**, and open two drawings of K-2 and two of
K-3 (all four showing their part in a view). Note the Window menu. Make K active and press Review.

- 011 T067, pass: the questions include
  `A drawing with the same name sits beside <n> reviewed file(s) but is not open. Should the review read it?`
  (answers `Yes, open it read-only and read it`, `Review without it` and
  `It is not the right drawing`) and one question per doubly drawn part,
  `2 open drawings show <stem>. Which one governs it?` (the drawings' names and `They all apply`);
  and the review asked **at most four** drawing questions (011 SC-008).
- Answer the same-name question `Yes, open it read-only and read it`, and each governing question
  with the drawing that governs (or `They all apply`). Answer every other question too, all in the
  same send; do not use **Skip for now** in this step. Before sending, record the sentence beside
  Send. Before sending, also open the **Not reached** fold and count the lines that begin
  `drawing.context`. Then press **Send answers** once.
- When it finishes, put K's run folder in `$run` and run `Show-ReviewFacts $run` (the box, item
  2). 009 T084, pass: `answers sent` equals the number of questions (three or more), `turns ended
  between the first and last answer 0`, and `turns ended after the last answer 1`; record `first
  round input after the answers` beside the sentence you recorded. With fewer than three questions,
  write `blocked: <n> questions` in the 009 T084 row: T084 then waits for a review that asks three.
- 011 T077's pane half and 011 T101 part 1, pass, while the switch is off: the Not reached fold's
  unresolved bucket has the line
  `drawing.confirmed_open - the bridge returned status 'error': the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 probe D14) [BridgeRefusedError]`
  (it passes when the line contains
  `the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 probe D14)`);
  no drawing window or document appeared (the Window menu is as before); and

  ```powershell
  Show-DrawingReadLog
  ```

  prints, as its **last** line, the newest `drawing.read` line: it has `command=drawing.read
  status=error`, `gated=GetOpenDocumentByName` and nothing more in the `gated=` list, and no
  `target=`.
- 011 T101 part 3, pass: the fold holds as many `drawing.context` lines as before the answers.
- 011 T067, the brief: find K-2's and K-1's document ids with `Show-Documents $run`, then for each:

  ```powershell
  $doc = '<the id exactly as Show-Documents prints it, doc: included>'
  cd "$R\reviewer"; cmd /c "uv run swreview drawing brief --package ""$run"" --run ""$run"" --document $doc --profile ""$env:LOCALAPPDATA\SwReview\standards.yaml"" > ""%TEMP%\swreview-brief.json"""; "exit code: $LASTEXITCODE"; cd $R
  (Get-Item "$env:TEMP\swreview-brief.json").Length
  Select-String -Path "$env:TEMP\swreview-brief.json" -SimpleMatch '"answers":[{' -Quiet
  $brief = Get-Content "$env:TEMP\swreview-brief.json" -Raw -Encoding UTF8 | ConvertFrom-Json; 'document', 'assembly', 'interfaces', 'drawing', 'answers' | ForEach-Object { "$_ " + ($brief.PSObject.Properties.Name -contains $_) }
  ```

  Pass: exit code 0, a size of **at most 6,001** bytes (the brief's 6,000 plus the newline the
  command ends it with), `True` (the brief lists your answers), and the five section lines each
  ending `True` (011 SC-006). The brief is built with the profile, as the review's own
  `get_drawing_brief` is; it stays in `%TEMP%` and is never pasted anywhere. `cmd /c` keeps the
  brief's bytes; do not change it to a PowerShell redirect, which would change them. Record: each
  size, the True or False, and the five section lines. Whether the review's model itself called
  `get_drawing_brief` the development machine reads from the run folder.

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
   - `Show-DrawingReadLog`'s last line has `command=drawing.read status=ok`, a `gated=` list
     beginning `GetOpenDocumentByName`, no `target=` and no `refused=`;
   - J's drawing is still open;
   - the drawings line now reads `Drawing read: <J's drawing>` with no `found but not open` part,
     in the same place;
   - as many `drawing.context` lines as before the answer.
4. **Settings**, **Save** (the backend restarts); when the badge reads `Backend ready` again, with
   part J active press **Clear review**, then J's chip. Pass: the review comes back read-only with
   the same drawings line.
5. The screenshot of step 4.2 again, now with the drawings line: pass when the headline, the three
   groups, the drawings line and every `not reached` goal fit in 300 by 600 without scrolling. Save
   it with the same two blocks as step 4.2, naming the file `$H\notes\pane-300x600-J.png`.

Record: each pass or fail, the log line (as far as its `gated=` list), and any wording the owner
would change (it would go in `review_words_v1.yaml` on the development machine).

## Step 5. The other tabs, the live Gemini test, and the older build

### 5.1 Model check

Open part J; on the Model check tab press **Model check**. Pass: a grade within seconds, headed
`Grade: <J's file name> [<configuration>]`, with its counts; under the counts either
`Every rule reached a verdict.` or `Not graded, evidence missing:` followed by sentences, the rule
ids only inside the **Rule ids** fold; no fraction anywhere in the grade; **Show** on a finding
selects its feature in J; and **Open check folder** opens a new folder ending `-check` that holds
`session.json`, `report.md` and `check.json`. Record: the counts, the line under them, and the
folder's stamp (never its name).

### 5.2 Standards

On the Standards tab press **Standards check** on part J and then on assembly A. Pass for each: a
verdict with every check in a bucket; `ready to release` only when there are no errors **and** no
unresolved checks; no banner about a missing profile; on A, the verdict notes `no drawing graded`.
Record: both verdict lines.

### 5.3 Remodel

With part J open:

```powershell
$f = "<full path of part J>"
Get-SeatHash $f; Get-Item -LiteralPath $f | Select-Object Length, LastWriteTime
```

Open the **Remodel** tab. Pass: it says
`Remodel is not in this build yet. This tab will not change the open part.` and offers nothing to
run. Go back to the Review tab and run the second line again. Pass: the hash, size and time are
unchanged. Record: pass or fail.

### 5.4 The live Gemini test [008 T106]

The prompt hides the key as you paste it and keeps it out of the command history (a file, which
the task's own rule forbids); the last line clears it:

```powershell
if (Test-Path Env:GOOGLE_API_KEY) { 'GOOGLE_API_KEY is set and would be used instead; cleared for this window'; Remove-Item Env:GOOGLE_API_KEY }
$env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host 'Paste the Gemini key' -AsSecureString)))
cd "$R\reviewer"; uv run pytest tests/live/test_gemini_live_function_response.py -m live -rs -p no:warnings; cd $R
Remove-Item Env:GEMINI_API_KEY
```

Pass: `1 passed` and **no** `SKIPPED` line. A skip proves nothing: record it as `blocked`, with the
reason the `SKIPPED` line gives. A failure saying the key was refused is setup, not the defect this
test looks for; a failure naming a connection, a proxy or a certificate is setup too: record
`blocked: network`. The defect is a failure beginning `the forced tool call was rejected` or `a
role="tool" function response was rejected`. Record the last lines. If you pressed Ctrl+C, or are
not sure the last line ran, close this PowerShell window: that is the sure way to drop the key.
Open a new one and paste the setup block.

### 5.5 Before and after the Show fix, on the older build: last [009 T082]

This builds an older version, looks at one thing, and comes back. Close SOLIDWORKS (Don't Save).
Then check the checkout and keep a copy of the settings file beside it (not in `$H`: it holds the
protected key):

```powershell
git status --porcelain; git branch --show-current
Copy-Item "$env:APPDATA\SwReview\settings.json" "$env:APPDATA\SwReview\settings.json.before-5.5"
```

Pass: nothing, then `main`. Anything else: stop and call the owner. Then:

```powershell
git checkout 9464b9e
.\extractor\tools\update-workstation.ps1 -NoPull -SkipTests
```

git prints `You are in 'detached HEAD' state` and a few lines of advice: that is expected. `9464b9e`
is the build before the fix (`3e86d47`); `-SkipTests` only here, because this build is only looked
at. If Windows says running scripts is disabled, run
`powershell -ExecutionPolicy Bypass -File .\extractor\tools\update-workstation.ps1 -NoPull -SkipTests`.
The older script has no `-SolidWorksRoot`, and it runs `git fetch origin` even with `-NoPull`. If
SOLIDWORKS is not in its usual folder, or the older script stops at `== git fetch origin`, build
directly instead (the Python side needs nothing: its lock file is the same on both builds, and the
backend runs from the checkout):

```powershell
$sw = "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS"   # or "<SOLIDWORKS install folder>"
dotnet build extractor\SwReview.sln -c Release "-p:SwRedist=$sw\api\redist"
```

Then start SOLIDWORKS, open A and part J, and:

1. With A active, press Review (the key is still in Settings) and wait for it to finish.
2. Make J active and on the Model check tab press **Model check**.
3. Make A active again, and in the Review tab press **Show in SOLIDWORKS** on one of A's findings.
   Record what SOLIDWORKS selected: something in A, something in J, nothing, or an error.

If the older build's review of A stops, or shows no finding, write `blocked` in the 009 T082 row
with the reason, and come back all the same. Close SOLIDWORKS (Don't Save) and come back to the
current build:

```powershell
git checkout main
.\extractor\tools\update-workstation.ps1 -NoPull
git log --oneline -1; (Get-Item "$R\extractor\SwReview.AddIn\bin\x64\Release\net48\SwReview.AddIn.dll").LastWriteTime
```

Pass: the script reaches `== health` as in step 1.3, the log line names the commit of step 1.4,
and the add-in's time is after the return build started. If the return stops at pytest or ruff
(both passed on this commit at 1.3), run it once more. If it stops again, run
`.\extractor\tools\update-workstation.ps1 -NoPull -SkipTests`, so the current add-in is at least
built, and record the failing test. If `dotnet build` fails, clear SwReview's two boxes (Active and
Start Up) in Tools > Add-ins and call the owner. **Never leave the seat on the older add-in.**

Start SOLIDWORKS and repeat the three presses. Pass: this time Show in SOLIDWORKS selects A's own
entity. Record: both answers. The registration survives both builds; nothing to register. If
Settings now shows a different provider, model or no key, close SOLIDWORKS and put the copy back:
`Copy-Item "$env:APPDATA\SwReview\settings.json.before-5.5" "$env:APPDATA\SwReview\settings.json"`.

## Step 6. The handoff

This is `docs/workstation-runbook.md` section 8.

### 6.0 SOLIDWORKS closed, your files unchanged

Close SOLIDWORKS (Don't Save), so every log is closed and no file is held open. Then:

```powershell
Get-Process SLDWORKS -ErrorAction SilentlyContinue
Save-Fingerprint 'after'; Compare-Fingerprint 'after'
Remove-Item "$env:TEMP\swreview-scratch" -Recurse -ErrorAction SilentlyContinue
```

Pass: nothing from the first line, then `changed: 0`. On a change, do as step 3.5 says (the vault's
history, then the owner). The last line deletes step 3.5's Pack and Go copies, so no copy of company
files lingers.

### 6.1 No key reached a file

```powershell
cd "$R\reviewer"; uv run swreview audit-secrets $runs "$env:LOCALAPPDATA\SwReview\logs" $H; "exit code: $LASTEXITCODE"; cd $R
```

Pass: `exit code: 0` and a line beginning `none: no configured secret appears in`. Read any other
line two ways:

- `<file>:<line>: <source>` is a leak: **do not zip or send anything**; call the owner. The output
  never shows the key itself.
- `could not read <file>` is a file another program holds: check that
  `Get-Process SLDWORKS, python, uv -ErrorAction SilentlyContinue` prints nothing, then run the
  audit again.

### 6.2 The exporter, on each review

The exporter, `swreview handoff`, makes a small, key-masked archive of one review with a manifest
of what it holds and what is missing. It is the quick summary; it is **not** the evidence, because
it leaves out `tool-results\` by design (6.3 carries the whole folders).

```powershell
cd "$R\reviewer"
Get-ChildItem $runs -Directory | Where-Object { $_.CreationTime -ge $since -and $_.Name -notmatch '-(check|standards|remodel)$' } | ForEach-Object { uv run swreview handoff $_.FullName --out "$H\exports\$($_.Name).zip" }
cd $R
```

Pass: one `wrote <archive>` per review and no `Missing artifacts: ` line. Record: the stamp and
letter of any review with a `Missing artifacts` line, and the files it names.

### 6.3 The whole run folders, the logs, the probe reports and the dumps

```powershell
$folders = @(Get-ChildItem $runs -Directory | Where-Object { $_.CreationTime -ge $since })
$folders | Select-Object Name
$need = [math]::Round((($folders | ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Recurse -File }) | Measure-Object Length -Sum).Sum / 1GB, 2)
"the run folders take $need GB; free on C: $([math]::Round((Get-PSDrive C).Free / 1GB, 1)) GB"
Compress-Archive -LiteralPath $folders.FullName -DestinationPath "$H\run-folders.zip" -Force
Compress-Archive -Path "$env:LOCALAPPDATA\SwReview\logs\*" -DestinationPath "$H\logs.zip" -Force
Get-ChildItem "$H\probes", "$H\dumps" | Select-Object Name
```

Pass: the list names every run folder of the sitting (the reviews, the `-check` and `-standards`
folders), free space is at least twice the figure, both zips are written (`-Force` replaces a zip
left by an earlier try), and the probe reports and dump folders are listed. If `Compress-Archive`
stops, delete the partial `run-folders.zip`, then copy the folders instead with
`Copy-Item -LiteralPath $folders.FullName "$H\run-folders" -Recurse`. The run folders hold vault
paths: they travel in the handover folder only and are never committed.

### 6.4 Finish the findings document

Open it (`notepad $findings`). At the top: the commit and versions from 1.4, SOLIDWORKS's version
from 1.6, `registration: done` or `not needed`, and the commit before the update (from
`notes\commit-before.txt`). Pass: every row of the Results table holds `pass`, `fail` or `blocked`,
each `fail` quotes its line, and each `blocked` names what blocked it. Under each step's heading
goes what the step said to record; last, "What to look at first next time".

No vault path, folder name, property name or value, template or sheet format name, and no key
(rule 5). The probe reports, dump folders, zips, screenshots and `notes\` sit beside it in the
handover folder.

### 6.5 Check again, then hand it over

Run step 6.1's line once more: the findings document and the screenshots were written after its
first run. Pass, and the same two readings, as at 6.1.

This sitting pushes nothing. The findings document stays in the handover folder with everything
else; tell the owner the folder is ready: it travels by hand, whole. The owner reads the document
and commits it from the development machine (the repository is public, and the owner is the one
who can see a company value in it). If git ever asks who you are, or a GitHub sign-in window
opens, you have run a command this plan does not give: close it and call the owner.

### 6.6 The checkout is clean

```powershell
git status --porcelain; git branch --show-current; git log --oneline origin/main..main
```

Pass: nothing, then `main`, then nothing (no commit was made on this machine).

## Going back to the build you had

Use this only when the owner says so after a stop at 1.3, or when the add-in no longer loads and
SOLIDWORKS is needed for work. SOLIDWORKS closed, non-elevated, the setup block pasted:

```powershell
$previous = (Get-Content "$H\notes\commit-before.txt").Trim()
git checkout --detach $previous; git log --oneline -1
.\extractor\tools\update-workstation.ps1 -NoPull
```

Pass: the log line names the commit in `commit-before.txt`, and the script reaches `== health`. The
checkout is now detached: the next update starts with `git checkout main`, and the script says so
if you forget. If the new profile is the problem, put the old one back with
`Copy-Item "$H\notes\standards.yaml.before" "$env:LOCALAPPDATA\SwReview\standards.yaml"`. If going
back fails too, or this is a new machine with no earlier build, clear both SwReview boxes (Active
and Start Up) in SOLIDWORKS under Tools > Add-ins: SOLIDWORKS then runs without the add-in until the
owner rebuilds. Record which of these you did.

## Not in this sitting

For the development machine, once the folder comes back:

| Package | Task | Why not now |
|---|---|---|
| 011 | 011 T095 | the sitting after the development machine sets the two switches: T068's binding by decimal places, and the read-only open of a closed candidate from the pane, with the `gated=` line and the drawings line the add-in and backend lanes asked for then |
| 008 | 008 T105 | the development machine replays this sitting's run folders; it also compares the findings of steps 4.1 and 4.2 with the recorded ones |
| 009 | 009 T085 | the development machine restores this sitting's run folders offline |
| 006 | 006 T100, the audit half | the development machine scans the returned run folders for the owner's profile values before 008 T101 is ticked; the seat does the profile entry (steps 2.2 and 2.4) |
| 010, 011 | setting either switch; 010 T104's and T106's counts | the development machine, as sections 3.10, 3.1 and 4.2 say |

Open seat or key tasks of earlier features, not asked this time:

| Package | Task | Why not now |
|---|---|---|
| 001 | 001 T044, 001 T098, 001 T099 | the benchmark packages and the pilot benchmark set: benchmark work, not a test of this build |
| 001 | 001 T061, 001 T076 | the bracket-assembly benchmark on the workstation; T076 also adds pane buttons that are not built |
| 001 | 001 T103 | every quickstart scenario of feature 001 end to end: a sweep of its own |
| 002 | 002 T044, 002 T051 | quickstart scenarios on the bracket fixture, which is not prepared (001 T061) |
| 002 | 002 T055a, 002 T063 | the Ask tab's terminal (Codex, Gemini CLI): the Ask tab is hidden in this build |
| 002 | 002 T067 | every quickstart scenario of feature 002 end to end: a sweep of its own |
| 003 | 003 T062, 003 T088, 003 T089 | the RMS fixture parts and their probes; step 5.1 touches Model check on J only |
| 004 | 004 T003, 004 T033 to T039, 004 T135 to T141 | the re-modeler's dry run, probes and stage-1 runs: the Remodel tab is off in this build (step 5.3 checks exactly that) |
| 005 | 005 T025 to T030 | the live usage probes: their test files are not written yet |
| 005 | 005 T034, 005 T036 | building `rms-part` and the benchmark baseline: benchmark work |
| 005 | 005 T085a | the workstation A/B harness: not built |
| 005 | 005 T050, 005 T058, 005 T063, 005 T068, 005 T073, 005 T078, 005 T084 | lever A/B runs: need the harness of 005 T085a |
| 005 | 005 T086, 005 T092, 005 T093, 005 T095, 005 T100, 005 T101, 005 T103, 005 T108 | lever 9 to 11 probes and A/B runs: need the harness, or wait on their levers |
| 006 | 006 T101, 006 T102 | not asked; one `swreview-extract probe standards` line on A or B during step 3.1 would record PROBE-1, PROBE-3 and part of PROBE-2 at almost no cost: the owner's call for a later sitting |
| 006 | 006 T104 | PROBE-8 and PROBE-9 on a weldment and a sheet-metal part, graded end to end: not asked (step 3.2 only probes L) |
| 006 | 006 T106, 006 T108 | the tab end to end and its timing on a 40-component assembly: not asked |
| 006 | 006 T109, 006 T110 | read-only proved on a standards dump, and agreement with the macro on copies: not asked |
| 007 | 007 T059, 007 T060 | the pinned panel against `report.md`, and `swreview timing` after each run: not asked, though both would fit step 4.1: the owner's call |
| 007 | 007 T061 to T063 | the procedural gate's study runs: need the lever study set-up |
