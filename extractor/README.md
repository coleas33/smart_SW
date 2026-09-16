# extractor

The C# half of the pilot and the only tree that touches the SOLIDWORKS API: the extraction
library, the in-process SOLIDWORKS 2024 add-in with its Task Pane, and the console host.
Design documents: `specs/001-agentic-design-review/plan.md` and
`specs/002-task-pane-assistant/plan.md`.

```text
SwReview.Extractor/          class library: IR dump, interference, captures, measurement,
                             persistent references, mesh export, the read-only API guard
                             and circuit breaker, the bridge dispatcher
SwReview.Extractor.Console/  out-of-process host (dump, interference, capture, resolve, serve)
SwReview.AddIn/              the add-in: Task Pane with a Review tab (WebView2 chat page fed
                             by the Python backend) and a Terminal tab (an external CLI in a
                             ConPTY pseudo-console rendered by xterm.js), the in-process tool
                             service, the backend child process, DPAPI-protected settings
SwReview.*.Tests/            xUnit
```

Every SOLIDWORKS call is made on the application thread; the guard allows only verified API
members and the circuit breaker trips after consecutive COM failures.

## Build and test

Windows with SOLIDWORKS 2024 installed. Interop DLLs are read from
`C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist`; override with `-p:SwRedist=...`.

```powershell
dotnet build extractor\SwReview.sln -c Release
dotnet test  extractor\SwReview.sln -c Release
```

Build and test the solution rather than a single project with `--no-build`: the projects
share build outputs and a stale one turns into a failure that does not belong to the change
being tested.

## Register the add-in

From an **elevated x64** prompt, with SOLIDWORKS closed:

```powershell
extractor\tools\register-addin.ps1                 # -Configuration Release, -Unregister
```

The script stages `SolidWorks.Interop.{sldworks,swconst,swpublished}.dll` from the seat's
`api\redist` into the add-in's output folder and then runs the 64-bit
`regasm /codebase SwReview.AddIn.dll`. The staging step is not optional: `regasm` loads
`swpublished` to reflect over `ISwAddin` while registering, and this project sets
`<Private>false</Private>` so the build does not copy the seat's interops, which live outside
every assembly probing path. A plain `regasm` on a clean build fails with `RA0000`. The copies
are local to `bin\`, which is not tracked, and are never redistributed.

The `[ComRegisterFunction]` in `SwReviewAddIn.cs`, which `regasm` invokes, writes both the
`HKLM\SOFTWARE\SOLIDWORKS\AddIns` keys and `HKCU\...\AddInsStartup = 1` for the account that
ran it, so **SwReview** is already ticked in Tools > Add-ins the next time SOLIDWORKS starts.
(If the elevated prompt ran as a *different* admin account, that flag landed in that account's
hive and this one has to tick the box once.)

A check box that is clear there is therefore not a step still to do: the add-in failed to
load, and SOLIDWORKS reports it that way and nothing else. Read
`%LOCALAPPDATA%\SwReview\logs\addin.log`, which carries a line per load step, and
`../docs/addin-load-fix.md`.

## Third-party licenses

The terminal page's vendored xterm.js and fit addon carry their versions, digests and MIT
texts in `SwReview.AddIn/Terminal/TerminalPage/vendor/LICENSES.md`. Everything else this
repository borrows from is listed in `../NOTICE.md`. SOLIDWORKS interop assemblies are
Dassault Systèmes property, referenced from the local installation and never redistributed.
