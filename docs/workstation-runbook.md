# Workstation runbook: installing, updating and keeping SwReview running

For the assistant operating the pilot workstation. Everything here is a command you can run
or a check you can make; nothing in it needs a decision from the owner except the two places
that say so. Read it whole once, then use the Quick reference at the end.

**Three rules that override everything else in this file.**

1. **Never commit or push per-machine state.** The settings file, the standards profile, the
   logs, the run folders, the generated Codex home, `.venv`, `bin` and `obj` are not in the
   repository and must not enter it. The repository is public. A committed test scans the
   whole tree for the company's profile values and fails the build if one appears.
2. **Never push to `main`.** Hand work back as a findings document (section 8), on a branch
   named `workstation/<date>` if pushing works from this machine, otherwise as a file.
3. **Close SOLIDWORKS before building or registering.** A loaded add-in holds its own DLL
   open; a build that fails with `The file is locked by: "SolidWorks (<pid>)"` is telling you
   that, and it is also proof the add-in loaded.

---

**The current work for this machine** is in a dated handover beside this file; the latest is
`docs/workstation-handover-2026-09-23.md`: the sitting for features 008 to 011, every seat task
in one ordered list with its command, what decides it and where its record goes. The engineer
who runs the sitting follows `docs/workstation-test-plan-2026-09-23.md`: the same sitting in
plain, numbered steps, each with its exact command and what counts as pass or fail. The earlier
rounds (`docs/workstation-handover-2026-09-20.md`, `-2026-09-19.md`) are history. This runbook
does not change per handover; the handover says what to do with a given build.

## 1. Where everything is

| What | Where | In git? |
|---|---|---|
| The checkout | wherever it was cloned; `<repo>` below | yes |
| The add-in DLL SOLIDWORKS loads | `<repo>\extractor\SwReview.AddIn\bin\x64\Release\net48\SwReview.AddIn.dll` | no (build output) |
| The Python reviewer and its environment | `<repo>\reviewer`, `.venv` inside it | code yes, `.venv` no |
| User settings (provider, model, effort, the DPAPI-protected key, terminal CLI, run root, profile path) | `%APPDATA%\SwReview\settings.json` | **no** |
| The standards profile | `%LOCALAPPDATA%\SwReview\standards.yaml` (the default; `standards_profile_path` in the settings file can point elsewhere) | **no** |
| Add-in log, one line per load step and per failure | `%LOCALAPPDATA%\SwReview\logs\addin.log` | no |
| Backend logs, one file per backend start | `%LOCALAPPDATA%\SwReview\logs\backend-<stamp>.log` | no |
| Run folders (one per review or check: `<stamp>-<doc>`, `-check`, `-standards`) | `Documents\SwReview\runs` by default (`run_root` in the settings file) | **no** |
| SOLIDWORKS 2024 SP5 and its interops | `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS`, `api\redist` under it | no |
| The registration script | `<repo>\extractor\tools\register-addin.ps1` | yes |
| `swreview-extract.exe`, the console every probe and dump task calls by its bare name | `<repo>\extractor\SwReview.Extractor.Console\bin\x64\Release\net48\swreview-extract.exe` (not the stale `bin\Release\net48` beside it); nothing puts it on PATH, so in each shell: `Set-Alias swreview-extract "<that path>"` (the update script prints the line) | no (build output) |
| The o200k_base vocabulary every token count reads | `%LOCALAPPDATA%\SwReview\tokenizer\fb374d419588a4632f3f557e76b4b70aebbca790` | **no** |

The add-in is registered by CLSID with a `/codebase` pointing at the DLL path above.
Registration survives rebuilds: same GUID, same path, no re-registration needed. It needs
redoing only on a first install, after the checkout moves, or after `-Unregister`.

## 2. Prerequisites, each with its check

Run these first on a fresh machine and after any Windows or SOLIDWORKS update.

| Need | Check | If missing |
|---|---|---|
| Git | `git --version` | install Git for Windows |
| .NET SDK (builds the .NET Framework 4.8 add-in) | `dotnet --version` prints 8 or 9 | install the .NET SDK |
| `uv` (Python 3.11+ environments; the add-in launches the backend through it) | `uv --version` **from a fresh, non-elevated PowerShell**, because SOLIDWORKS inherits the same PATH | install uv for the user, then log out and in so PATH is refreshed for SOLIDWORKS |
| SOLIDWORKS 2024 SP5 | `Test-Path "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll"` | the seat is not where the scripts expect; pass `-SolidWorksRoot "<install root>"` to both `update-workstation.ps1` (it builds against that root's `api\redist`) and `register-addin.ps1` |
| The o200k_base vocabulary (the gate fails without it) | from `<repo>\reviewer`: `uv run swreview tokenizer fetch` prints `written` or `already in place` | the download needs the vocabulary host, which a web filter may block: carry the file above from the development machine's `%LOCALAPPDATA%\SwReview\tokenizer\` by hand, outside the repository as the profile is, then `uv run swreview tokenizer fetch --from "<file>"` (or `update-workstation.ps1 -TokenizerFrom "<file>"`); the hash is checked either way |
| WebView2 runtime (the Review, Model check, Standards and Remodel tabs) | `foreach ($k in 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') { if (Test-Path $k) { 'WebView2 ' + (Get-ItemProperty $k -Name pv).pv } }` prints a version (a per-machine install is under HKLM, a per-user one under HKCU) | install the Evergreen WebView2 runtime |
| Codex CLI (the Ask tab's terminal) | not needed: the Ask tab is hidden in this build (`TaskPaneControl.AskTabShown` is false) | when the tab is shown again: `npm install -g @openai/codex`, then sign in once |
| A provider key, for the Review tab only | entered in the pane's Settings; never in a file you write | the Model check and Standards tabs need no key. The one exception is 008 T106's live test, which reads `GEMINI_API_KEY` from the environment: set it for that one shell, run the handover's command, and `Remove-Item Env:GEMINI_API_KEY` after; never in a profile script |

## 3. First install

Everything but the registration runs **non-elevated, as the account that uses SOLIDWORKS**: the
reviewer's `.venv` and the vocabulary go into that account's profile, and git refuses a checkout
another account owns.

```powershell
git clone https://github.com/coleas33/smart_SW.git
cd smart_SW\reviewer
uv sync --all-extras
uv run swreview tokenizer fetch       # or: --from "<file carried by hand>" (section 2)
$env:SWREVIEW_REQUIRE_TOKENIZER = "1" # a missing vocabulary fails the tests rather than skipping them
uv run pytest -q -m "not live"        # reviewer suite, as CI runs it; no SOLIDWORKS needed
Remove-Item Env:SWREVIEW_REQUIRE_TOKENIZER
cd ..
dotnet build extractor\SwReview.sln -c Release
dotnet test  extractor\SwReview.sln -c Release
```

`.\extractor\tools\update-workstation.ps1 -NoPull` runs the same steps after the clone. Then,
**with SOLIDWORKS closed**, from an elevated x64 "Windows PowerShell (Admin)" prompt opened as the
account that uses SOLIDWORKS:

```powershell
cd '<repo>'
.\extractor\tools\register-addin.ps1
```

The script stages the seat's three interop DLLs into the output folder and runs the 64-bit
`regasm /codebase`. It also enables the add-in for the account that ran it, so SwReview is
already ticked in Tools > Add-ins on the next SOLIDWORKS start. If the elevated prompt ran as
a different account than the one that uses SOLIDWORKS, tick the box once for that account.

Then place the standards profile (section 5), start SOLIDWORKS, and run the health checks
(section 6).

## 4. Updating to the latest

Do this whenever the owner says a change landed, and at least once a day the workstation is
in use. Every step is safe to repeat.

```powershell
cd '<repo>'
git status --porcelain                # must print nothing; see below if it does
git fetch origin
git log --oneline HEAD..origin/main   # what is about to arrive; read it
git pull --ff-only origin main
cd reviewer
uv sync --all-extras                  # picks up dependency and package changes
uv run swreview tokenizer fetch       # nothing to do once it is in place
$env:SWREVIEW_REQUIRE_TOKENIZER = "1"
uv run pytest -q -m "not live"        # the live tests call a paid API; 008 T106 runs one on its own
Remove-Item Env:SWREVIEW_REQUIRE_TOKENIZER
cd ..
# SOLIDWORKS must be closed from here
dotnet build extractor\SwReview.sln -c Release
dotnet test  extractor\SwReview.sln -c Release
```

The same sequence as one command, stopping at the first step that fails, is
`.\extractor\tools\update-workstation.ps1`, run non-elevated (`-SkipTests` only when a test
failure has already been reported and the owner asked for the build anyway; `-SolidWorksRoot` and
`-TokenizerFrom` as section 2 says). Register on a first install with `register-addin.ps1` on its
own from an elevated prompt (section 3); the script's `-Register` is only for a machine where the
SOLIDWORKS account's own prompt is the elevated one, and the script warns when it runs elevated.
It refuses to run while SOLIDWORKS is open or the checkout is dirty, for the reasons below.
PowerShell reads a script whole before running it, so the script that runs is the one already
checked out: on a checkout that may be behind (any seat not updated since 2026-09-24, whose
script lacks `-TokenizerFrom`, `-SolidWorksRoot` and the `swreview-extract:` health line), pull
first and build with the script that arrived: `git pull --ff-only origin main`, then
`.\extractor\tools\update-workstation.ps1 -NoPull` (the test plan's step 1.3 does exactly this).
`-NoPull` skips the pull, not the fetch: every version of the script starts with `git fetch
origin` to show what is arriving, so a refused fetch stops it even then. The script pulls only on
`main`. A seat that keeps its own documentation commits on a lane (the pilot workstation's
`local`) merges GitHub in by hand, `git fetch origin` then `git merge origin/main`, and runs the
script with `-NoPull` to build and gate what is checked out; on a lane without `-NoPull` the script
stops and says so rather than failing a fast-forward, and with `-NoPull` it says
`on '<branch>' with -NoPull: building what is checked out` and builds, a detached checkout
included.

Then start SOLIDWORKS and run the health checks (section 6).

- **If `git status --porcelain` prints anything**, do not pull over it. Local edits on the
  workstation belong in a findings document (section 8), not in the tree, and a findings document
  belongs in the handover folder, not in `docs\`. Move a findings document there; move anything
  else aside with `git stash push --include-untracked -m "workstation <date>"` (a plain
  `git stash push` leaves untracked files where they are, and the tree stays dirty) and record
  the stash in the findings document.
- **If the pull says "Not possible to fast-forward"**, someone committed on this machine.
  Stop and report; do not merge or rebase on the workstation.
- **Re-register only if** the checkout moved, the DLL path changed, or the log says the add-in
  did not load after a registration-related change. `register-addin.ps1` is idempotent.
- **If `uv run pytest` reports `No module named swreview`**, run
  `uv sync --all-extras --reinstall-package swreview`.

## 5. The standards profile

The Standards tab grades against a profile file the owner supplies. It carries the company's
vault root, library folders, property names and export-control phrase, so it exists only on
machines that run checks and is delivered out of band, never through the repository.

| | |
|---|---|
| Path | `%LOCALAPPDATA%\SwReview\standards.yaml` unless `standards_profile_path` in the settings file says otherwise |
| Where it comes from | the owner's handover folder (`%LOCALAPPDATA%\SwReview\handover\standards.yaml` on the development machine); ask the owner if you do not have it |
| What a wrong file looks like | `config\standards.example.yaml` copied into place: every value in it is fictional placeholder data, and the tab then grades against a standard nobody uses without any error |
| The one field that may need this machine's value | `vault_root`, the vault's local mount path; every library prefix is written relative to it, so only that line changes between machines |
| Its version | `Select-String -Path $env:LOCALAPPDATA\SwReview\standards.yaml -Pattern '^version:'` prints `version: 3`. A version 1 or 2 file still loads, and the sections it lacks - `general_tolerance` and `hygiene` (version 2), `drawing` (version 3) - are simply absent, so feature 010's hygiene and general-tolerance checks and feature 011's drawing comparison come back skipped without an error. A lower version is the owner's to rewrite, from `config\standards.example.yaml`'s version 3 layout; do not edit it here |

Validate it once after placing it, from `<repo>\reviewer`, against any package a Standards
press already dumped (a folder under the run root ending in `-standards`):

```powershell
uv run swreview check standards --package '<a -standards run folder>' --out "$env:TEMP\swreview-profile-check" --profile "$env:LOCALAPPDATA\SwReview\standards.yaml"
```

A schema error is reported field by field and nothing is graded until it is fixed. A refusal
naming missing phases means the package was not dumped by the Standards tab; press Standards
once and use that folder. Never paste the file's contents into a document, a commit or a chat
transcript that leaves this machine.

## 6. Health checks after every install or update

Start SOLIDWORKS with a **part or assembly** active, not a drawing (a drawing is refused by
the tool service, out loud, since the fix of 2026-09-18; before it, a drawing active at load
silently disabled every bridge-backed feature).

1. **The add-in loaded.** Tools > Add-ins shows SwReview ticked. The tail of
   `%LOCALAPPDATA%\SwReview\logs\addin.log` for this start shows, in order:
   `AssemblyRedirect installed.`, `Attached to SOLIDWORKS.`, `Task Pane created.`,
   `Review host started.`, each after its `[time]`, and **no tool-service line**: the tool
   service logs only refusals and failures, so a line whose text after the `[time]` begins
   `The SwReview tool service` means it did not attach, and
   one naming a `.SLDDRW` means the active document was a drawing. A clear check box or a
   missing load line is a load failure; the log names the step that failed.
2. **The backend is up.** The Review tab's backend badge reads `Backend ready` (not `Backend
   starting`, `Starting the review backend...` or `Error`), and a new
   `backend-<stamp>.log` appeared in the logs folder. If the tab says the backend could not be
   located, `uv` is not on the PATH SOLIDWORKS inherited (section 2).
3. **Model check works with no key.** Press Model check on a part: a grade and a findings list
   appear within seconds and a `<stamp>-<doc>-check` folder holds `session.json`,
   `report.md` and `check.json`.
4. **Standards works with the real profile.** Press Standards on the same part: a verdict with
   every check accounted for. A `NoProfile` banner or a file-not-found naming
   `StandardsProfilePath` means section 5 was skipped.
5. **A review ends on screen.** With a key configured, press Review on a small assembly. The
   Results view (the default since feature 009) fills with the summary, the findings and the
   coverage, and when the backend finishes its state line reads "The review has finished." (or
   "Waiting for your answers." while a question is open), Review is enabled again and the
   follow-up box opens. The line "The session ended at <time>." is in the Transcript view, not in
   Results. If the pane sits on "Streaming." with "No model round trips
   yet" after `report.md` has been written, the page's event parser has regressed; that exact
   failure was fixed on 2026-09-18 and is pinned by a shared sample frame in both test suites, so
   a recurrence is a real regression to report.
6. **There is no Ask tab.** Five tabs: Review, Extract, Model check, Remodel, Standards. The
   Ask tab is hidden by design in this build; a pane showing one is running a build that
   turned it back on, which is a change to report.
7. **Nothing landed in the repository.** `git status --porcelain` in the checkout prints
   nothing.

## 7. Failure modes already met, and their fixes

| Symptom | Cause | Fix |
|---|---|---|
| Add-in box clear after start; log stops after `AssemblyRedirect installed.` or `Attached to SOLIDWORKS.` | a load failure; SOLIDWORKS clears the startup flag on any exception out of `ConnectToSW` | read the next line of `addin.log`; the three historical causes and their proofs are in `docs/addin-load-fix.md` |
| `RegAsm : error RA0000 : Could not load file or assembly 'SolidWorks.Interop.swpublished'` | the interops were not staged beside the DLL | run `register-addin.ps1`, which stages them; do not call regasm by hand |
| `dotnet build` says the DLL is locked by SolidWorks | SOLIDWORKS is running with the add-in loaded | close SOLIDWORKS; the lock proves the add-in loads |
| Review tab: backend could not be located | `uv` (or `swreview`) is not on the PATH SOLIDWORKS sees | install uv for the user, log out and in; or set `python` in the settings file to the full path of `uv.exe` |
| Page requests never reach the backend; DevTools shows preflights and no `GET`; "Sophos" or a web filter is installed | the endpoint filter blocks browser loopback HTTP | already fixed: the host serves the pages and proxies the backend on the same origin (`docs/pane-backend-proxy.md`); if it recurs, report the DevTools Network tab, not a PowerShell test, which the filter does not intercept |
| Tool service did not start; log names a `.SLDDRW` and "no active configuration" | a drawing was the active document | fixed 2026-09-18: a drawing is skipped and the pane says so; open the part or assembly it documents |
| Standards tab: profile could not be opened at `...\standards.yaml` | no profile placed, or the settings path points elsewhere | section 5 |
| Standards verdicts look wrong on every document | the fictional example was copied into place | replace it with the owner's file (section 5) |
| `swreview check rms` or `check standards` refuses to write into the package | by design: `--out` is required and the package directory is only read | pass `--out "<new folder>"` |
| Fusion log shows a failed by-name bind for `SwReview.AddIn` | benign; `/codebase` activation always tries a by-name bind first | ignore; SOLIDWORKS' own add-ins log the same |

## 8. Handing findings back

The owner's development machine cannot see this workstation. Everything learned here travels
as a document, in the shape the earlier handovers used (`docs/pane-findings-2026-09-16.md`,
`docs/pane-findings-2026-09-18.md`): a dated Markdown file, `pane-findings-<date>.md`, that says
what works, what is a bug with the evidence (log lines, run folder names, durations, sizes), what
is setup rather than a bug, and a suggested order for the next session. Write it in
`%LOCALAPPDATA%\SwReview\handover\<date>\`, not in the checkout: an untracked file in `docs\`
makes the next `update-workstation.ps1` refuse the tree.

- **Evidence goes beside the document, not in it.** Zip the **whole** run folders of the session
  - `tool-results\` included, which 008 T105's replay reads to size every call it cannot
  reproduce - and the logs into the same `%LOCALAPPDATA%\SwReview\handover\<date>\`, with the
  `--out` folder of every `swreview-extract probe` run (its `drawings-probe-<time>.txt` files are
  feature 011's record) and every dump folder a task names, and tell the owner it is there. Do not
  use `swreview handoff` for this: its bundle is a bounded allowlist that leaves `tool-results\`
  out by design. Run folders hold vault paths and must never be committed.
- **No company value in the document**: no vault path, no library folder name, no property
  name, no export-control phrase. Name the profile by its path only.
- **If `git push` works from this machine**, copy the document into `docs\` on a branch
  `workstation/<date>`, commit it alone, push that branch and `git checkout main` again, so the
  next update finds `main` clean. Never push `main`; never commit anything under the run root,
  the logs, the settings file or the profile.
- **If it does not**, the document stays in the handover folder and is handed over with it.
- **A sitting run by an engineer from the test plan pushes nothing** (its step 6.5): the document
  stays in the handover folder, and the owner reads it and commits it from the development
  machine, since the repository is public and the owner is the one who can see a company value
  in it.

Record in the document the commit the workstation was on (`git rev-parse --short HEAD`) and
the versions from section 2, so the owner can reproduce the machine's state.

## 9. Quick reference

```powershell
# update (SOLIDWORKS closed, non-elevated): pull first, then build with the script that arrived (section 4)
cd '<repo>'; git status --porcelain; git pull --ff-only origin main
.\extractor\tools\update-workstation.ps1 -NoPull  # -TokenizerFrom "<file>", -SolidWorksRoot "<root>" as needed
# or, instead of the script, the same build and gates by hand
cd reviewer; uv sync --all-extras; uv run swreview tokenizer fetch
$env:SWREVIEW_REQUIRE_TOKENIZER = "1"; uv run pytest -q -m "not live"; Remove-Item Env:SWREVIEW_REQUIRE_TOKENIZER; cd ..
dotnet build extractor\SwReview.sln -c Release; dotnet test extractor\SwReview.sln -c Release

# the console the probe and dump tasks call, for this shell
Set-Alias swreview-extract '<repo>\extractor\SwReview.Extractor.Console\bin\x64\Release\net48\swreview-extract.exe'

# first install only, elevated, SOLIDWORKS closed
.\extractor\tools\register-addin.ps1

# profile: present, and version 3
Test-Path $env:LOCALAPPDATA\SwReview\standards.yaml
Select-String -Path $env:LOCALAPPDATA\SwReview\standards.yaml -Pattern '^version:'
cd reviewer; uv run swreview check standards --package '<-standards folder>' --out "$env:TEMP\swreview-profile-check" --profile "$env:LOCALAPPDATA\SwReview\standards.yaml"

# after starting SOLIDWORKS
Get-Content $env:LOCALAPPDATA\SwReview\logs\addin.log -Tail 12
Get-ChildItem $env:LOCALAPPDATA\SwReview\logs\backend-*.log | Sort-Object LastWriteTime | Select-Object -Last 1

# never
git add '<anything under the run root, the logs, %APPDATA%\SwReview or %LOCALAPPDATA%\SwReview>'
git push origin main
```
