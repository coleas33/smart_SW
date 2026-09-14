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

## Third-party licenses

The terminal page's vendored xterm.js and fit addon carry their versions, digests and MIT
texts in `SwReview.AddIn/Terminal/TerminalPage/vendor/LICENSES.md`. Everything else this
repository borrows from is listed in `../NOTICE.md`. SOLIDWORKS interop assemblies are
Dassault Systèmes property, referenced from the local installation and never redistributed.
