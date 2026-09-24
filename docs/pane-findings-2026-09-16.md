# Two smaller findings from the 2026-09-16 pane session

Both found on the pilot workstation against `main` `8b09438`, while diagnosing the Task
Pane. Neither is the pane blocker - that one has its own brief,
[`pane-backend-proxy.md`](pane-backend-proxy.md). Both are real and reproducible, and
**both are now fixed** - finding 1 in `extractor/SwReview.AddIn/ToolService/` and
`SwReviewAddIn.cs`, finding 2 in `reviewer/src/swreview/cli.py` and
`reviewer/src/swreview/checks/rms/run.py`. Each has a **Fixed** paragraph at the end saying
what landed.

---

## 1. The tool service attaches to one document and never re-attaches

**Symptom, as the engineer sees it.** The Remodel tab reports:

```
the SOLIDWORKS bridge did not answer remodel.probe_scope: the bridge returned status
'error': document no longer open: the model the tool service attached to was closed in
SOLIDWORKS
```

...while the pane header shows a perfectly open document.

**What actually happened.** From `%LOCALAPPDATA%\SwReview\logs\tool-service-*.log`:

```
[20:47:04] listening on \\.\pipe\swreview-<guid>
[20:47:04] attached to C:\...\<an assembly's folder>\<an assembly>.SLDASM [Default], 6 components
[20:51:00] id=1 command=remodel.probe_scope status=error elapsed_ms=2
           gated=GetOpenDocumentByName
           error="document no longer open: the model the tool service attached to was closed"
```

The tool service bound to whichever document was open when the add-in started
(an assembly, `.SLDASM`). The engineer then switched to a different part
(`.SLDPRT`). The service never re-attached, so every bridge command afterwards
asked about a document that no longer exists.

`POST /remodel/probe` reaching the backend and returning `502` is consistent with this: the
call is made by `Remodel/RemodelBackendClient.cs` in C#, succeeds, and the failure comes
from the bridge behind it.

**Why the message misleads.** It is accurate about the document the service attached to,
but the engineer reads it against the document they are looking at. It should name the
document it attached to, and say that switching documents requires a reconnect.

**Workaround.** Open the target document *first*, then untick and re-tick SwReview in
*Tools > Add-ins* so the tool service attaches to it.

**Worth considering.** `SwReviewAddIn` already subscribes to `ActiveDocChangeNotify`
(`OnActiveDocumentChanged`), so the add-in knows when the document changed; the tool
service attachment does not follow it. Either follow the active document, or fail with a
message naming both documents.

**Fixed.** Both, as it turned out. `ToolServiceGate.FollowDocument(activePath)` is called from
`SwReviewAddIn.OnActiveDocumentChanged` right after `EnsureStarted()`: when a service is
running and the document it attached to is not the active one - compared canonically and
case-insensitively, and a null active path means "nothing open" and is left alone - the gate
disposes it and schedules a fresh start, which attaches to the now-active document exactly as
the first start did, and the existing `service => reviewOptions.Bridge = service.ReviewBridge`
callback re-points the review bridge.

It does not do that while work holds the bridge. The gate takes an injected `Func<bool> busy`,
wired in `SwReviewAddIn` to `_reviewHost.AnyTurnRunning() || _remodelHost.RunInProgress`;
disposing a scope underneath a running turn or remodel would fail work that was going fine. In
that case the engineer is told rather than left with a silent no-op - one line into the
service's own tool-service log, beside the `attached to ...` line: `not re-attaching to
<active>: a turn is running against <attached>`.

And the message that misled now names both documents.
`DocumentPresenceDispatcher.DocumentClosedError(attachedDocumentPath)` reads `document no
longer open: the tool service is attached to <attached>, which is no longer open in
SOLIDWORKS`; `document no longer open` is kept as `DocumentClosedPrefix`, because that half is
the marker the Python client matches on and the rest of the sentence is for the engineer.

Covered in `extractor/SwReview.AddIn.Tests/ToolServiceWiringTests.cs`: a change to another
document restarts once and attaches to it, the same document does not restart, a busy bridge
does not restart and logs, a null active document does not restart, and a dispose during a
pending restart is safe.

---

## 2. `swreview check rms` writes into the package directory it is grading

**Reproduction**, from `reviewer/`:

```powershell
uv run swreview check rms --package tests\golden\fixtures\rms-part --scope part
git status --short
```

Result: three files appear **inside the golden fixture**:

```
?? reviewer/tests/golden/fixtures/rms-part/check.json
?? reviewer/tests/golden/fixtures/rms-part/report.md
?? reviewer/tests/golden/fixtures/rms-part/session.json
```

Deleting them and re-running `uv run pytest tests/golden` passes (33 tests), so nothing was
corrupted this time - but a grading command that writes into the package it grades can
modify a golden fixture, and the fixtures are the project's regression baseline.

**Why this stands out.** `check interference` documents the opposite rule in
`reviewer/src/swreview/cli.py`, and does so deliberately:

> Read-only, unlike `exceptions list`: `interference_case` refreshes the store in memory so
> a stale exception is reported as `needs_review` and silences nothing, but neither it nor
> this command writes `exceptions.json` back. **Grading a package must not edit it.**

`check rms` does not hold to that.

**Options.** Require an explicit `--out` for the run artifacts; or default them to a run
folder under the run root rather than the package; or refuse when the package is inside
`tests/golden/fixtures`. The first is the most explicit and matches the rest of the CLI,
where `review` already takes `--out`.

**Fixed.** `swreview check rms` takes a required `--out <dir>`: `session.json`, `report.md`
and `check.json` go in that run folder, the package directory is never written, and the
carry-forward run root is `--out`'s parent. `run_rms_check` gained `out_dir`, defaulting to
`package_dir` for `POST /checks/rms`, whose check run folder is its own package directory.
`reviewer/tests/unit/test_cli.py` runs the command against
`tests/golden/fixtures/rms-part` and asserts `git status` of that folder is empty.
