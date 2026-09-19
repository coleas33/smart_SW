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
| SOLIDWORKS 2024 SP5 | `Test-Path "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll"` | the seat is not where the script expects; pass `-SolidWorksRoot` to the register script |
| WebView2 runtime (the Review, Model check, Standards and Remodel tabs) | `Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -Name pv` prints a version | install the Evergreen WebView2 runtime |
| Codex CLI (the Ask tab's terminal) | not needed: the Ask tab is hidden in this build (`TaskPaneControl.AskTabShown` is false) | when the tab is shown again: `npm install -g @openai/codex`, then sign in once |
| A provider key, for the Review tab only | entered in the pane's Settings; never in a file you write | the Model check and Standards tabs need no key |

## 3. First install

```powershell
git clone https://github.com/coleas33/smart_SW.git
cd smart_SW\reviewer
uv sync --all-extras
uv run pytest -q                      # reviewer suite; no SOLIDWORKS needed
cd ..
dotnet build extractor\SwReview.sln -c Release
dotnet test  extractor\SwReview.sln -c Release
```

Then, **with SOLIDWORKS closed**, from an elevated x64 "Windows PowerShell (Admin)" prompt
opened as the account that uses SOLIDWORKS:

```powershell
cd <repo>
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
cd <repo>
git status --porcelain                # must print nothing; see below if it does
git fetch origin
git log --oneline HEAD..origin/main   # what is about to arrive; read it
git pull --ff-only origin main
cd reviewer
uv sync --all-extras                  # picks up dependency and package changes
uv run pytest -q
cd ..
# SOLIDWORKS must be closed from here
dotnet build extractor\SwReview.sln -c Release
dotnet test  extractor\SwReview.sln -c Release
```

The same sequence as one command, stopping at the first step that fails, is
`.\extractor\tools\update-workstation.ps1` (add `-Register` on a first install, `-SkipTests`
only when a test failure has already been reported and the owner asked for the build anyway).
It refuses to run while SOLIDWORKS is open or the checkout is dirty, for the reasons below.

Then start SOLIDWORKS and run the health checks (section 6).

- **If `git status --porcelain` prints anything**, do not pull over it. Local edits on the
  workstation belong in a findings document (section 8), not in the tree. Move them aside
  with `git stash push -m "workstation <date>"` and record the stash in the findings document.
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

Validate it once after placing it, from `<repo>\reviewer`, against any package a Standards
press already dumped (a folder under the run root ending in `-standards`):

```powershell
uv run swreview check standards --package <a -standards run folder> --out $env:TEMP\swreview-profile-check --profile $env:LOCALAPPDATA\SwReview\standards.yaml
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
   `Review host started.`, and **no tool-service line**: the tool service logs only refusals
   and failures, so a line beginning `The SwReview tool service` means it did not attach, and
   one naming a `.SLDDRW` means the active document was a drawing. A clear check box or a
   missing load line is a load failure; the log names the step that failed.
2. **The backend is up.** The Review tab's backend state line reads as running, and a new
   `backend-<stamp>.log` appeared in the logs folder. If the tab says the backend could not be
   located, `uv` is not on the PATH SOLIDWORKS inherited (section 2).
3. **Model check works with no key.** Press Model check on a part: a grade and a findings list
   appear within seconds and a `<stamp>-<doc>-check` folder holds `session.json`,
   `report.md` and `check.json`.
4. **Standards works with the real profile.** Press Standards on the same part: a verdict with
   every check accounted for. A `NoProfile` banner or a file-not-found naming
   `StandardsProfilePath` means section 5 was skipped.
5. **A review ends on screen.** With a key configured, press Review on a small assembly. The
   transcript streams, and when the backend finishes the pane says "The session ended.",
   Review is enabled again and the follow-up box opens. If the pane sits on "Streaming." with
   "No model round trips yet" after `report.md` has been written, the page's event parser has
   regressed; that exact failure was fixed on 2026-09-18 and is pinned by a shared sample
   frame in both test suites, so a recurrence is a real regression to report.
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
| `swreview check rms` or `check standards` refuses to write into the package | by design: `--out` is required and the package directory is only read | pass `--out <new folder>` |
| Fusion log shows a failed by-name bind for `SwReview.AddIn` | benign; `/codebase` activation always tries a by-name bind first | ignore; SOLIDWORKS' own add-ins log the same |

## 8. Handing findings back

The owner's development machine cannot see this workstation. Everything learned here travels
as a document, in the shape the earlier handovers used (`docs/pane-findings-2026-09-16.md`,
`docs/pane-findings-2026-09-18.md`): a dated Markdown file in `docs/` that says what works,
what is a bug with the evidence (log lines, run folder names, durations, sizes), what is
setup rather than a bug, and a suggested order for the next session.

- **Evidence goes beside the document, not in it.** Zip the run folders and the logs of the
  session into `%LOCALAPPDATA%\SwReview\handover\<date>\` and tell the owner it is there;
  run folders hold vault paths and must never be committed.
- **No company value in the document**: no vault path, no library folder name, no property
  name, no export-control phrase. Name the profile by its path only.
- **If `git push` works from this machine**, commit the document alone on a branch
  `workstation/<date>` and push that branch. Never push `main`; never commit anything under
  the run root, the logs, the settings file or the profile.
- **If it does not**, leave the file in `docs/` and hand it over as a file.

Record in the document the commit the workstation was on (`git rev-parse --short HEAD`) and
the versions from section 2, so the owner can reproduce the machine's state.

## 9. Quick reference

```powershell
# update (SOLIDWORKS closed); the script is the same steps as the lines after it
.\extractor\tools\update-workstation.ps1
cd <repo>; git status --porcelain; git pull --ff-only origin main
cd reviewer; uv sync --all-extras; uv run pytest -q; cd ..
dotnet build extractor\SwReview.sln -c Release; dotnet test extractor\SwReview.sln -c Release

# first install only, elevated, SOLIDWORKS closed
.\extractor\tools\register-addin.ps1

# profile
Test-Path $env:LOCALAPPDATA\SwReview\standards.yaml
cd reviewer; uv run swreview check standards --package <-standards folder> --out $env:TEMP\swreview-profile-check --profile $env:LOCALAPPDATA\SwReview\standards.yaml

# after starting SOLIDWORKS
Get-Content $env:LOCALAPPDATA\SwReview\logs\addin.log -Tail 12
Get-ChildItem $env:LOCALAPPDATA\SwReview\logs\backend-*.log | Sort-Object LastWriteTime | Select-Object -Last 1

# never
git add <anything under the run root, the logs, %APPDATA%\SwReview or %LOCALAPPDATA%\SwReview>
git push origin main
```
