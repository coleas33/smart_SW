# Workstation session 2026-09-18: what works, one real bug, two setup gaps

Pilot workstation, SOLIDWORKS 2024, WebView2 153.0.4234.32, Sophos Endpoint. Against `main`
`bada848` (the pull that brought the same-origin backend proxy, the event stream over the
page channel, feature 006 Standards, `check rms --out` and the document-following tool
service).

**Headline: the Sophos blocker is gone and reviews work end to end.** One real bug remains
in the pane, and two things that look like bugs are unfinished setup.

---

## 1. Confirmed fixed: the same-origin proxy

The [previous session](pane-backend-proxy.md) could not get a single page request to the
backend. Comparing backend logs across this pull, on the same workstation:

| Build | What the log shows for `/sessions/{id}/events` |
|---|---|
| Before (`backend-20260918-204520.log`) | `OPTIONS ... 204 No Content`, repeatedly, and **no `GET` ever** |
| After (`backend-20260918-215522.log`) | `GET ... 200 OK`, and **no `OPTIONS` at all** |

No preflight means no cross-origin request, which is the whole point. Page resources
(`index.html`, `app.css`, `shared/dom.js`, `render.js`, `app.js`) all serve `200` from the
host. No CORS error appears anywhere in the DevTools console.

---

## 2. THE BUG: the page never learns the session ended

**Reproduced on three consecutive runs.** The backend completes, writes `report.md` and
`session.json`, and emits `session.ended` into `events.jsonl`. The pane goes on showing:

```
Reviewing 4 components (23 gaps).
report.md has not been written yet; it appears once the review reports its first finding.
Streaming.
No model round trips yet.
```

All four statements are false by the time they are read. Consequences:

- the engineer cannot tell a finished review from a hung one;
- **Review stays disabled**, and `Stop` does not release it, so the only way to start
  another review is to restart SOLIDWORKS;
- the follow-up question box cannot be used.

### Evidence

Three reviews of the small assembly, named by their run folders' timestamps:

| Run | Duration | Ended with | `report.md` | Pane said |
|---|---|---|---|---|
| `20260918-214702-…` | 77 s | `session.ended` | 34,623 B | still reviewing |
| `20260918-215624-…` | ~95 s | `session.ended` | 34,630 B | still reviewing |
| `20260918-215755-…` | 97 s | `session.ended` | 41,034 B | still reviewing |

The host side is healthy: `GET /sessions/{id}/events` returns `200`, and every event
including `session.ended` is present in `events.jsonl`. So the break is **between the host
pump and the page**, not in the backend and not in the review engine.

The page reporting `Streaming.` while also reporting `No model round trips yet` is the
tell: the page believes the stream is open and has received nothing through it.

### Where to look

`extractor/SwReview.AddIn/Review/EventStreamPump.cs` and the page's handler for whatever
message the pump posts. `app.js` already owns a working SSE frame parser (`onFrame`), which
tracks `seq` and feeds `onChatEvent`; if the pump posts frames in a shape that handler does
not receive, or the page never asks the host to start pumping, this is exactly the symptom.

### Diagnostic that settles it in one step

In the pane's DevTools **Network** tab, look for a request to
`/__backend/sessions/<id>/events`:

- **absent** - the page is correctly leaving the stream to the host, so the fault is the
  host-to-page frame delivery or the page's handler;
- **present** - the page is still using the old `fetch` path, which is refused `501
  StreamNotProxyable` by design.

---

## 3. Not a bug: the Standards profile must be authored (FIXED this session)

The Standards tab reported:

```
the standards profile at 'C:\Users\csorkness\AppData\Local\SwReview\standards.yaml' could
not be opened (Could not find file ...). Check `StandardsProfilePath`.
```

This is designed behaviour, not a defect. `StandardsProfilePath` defaults to
`%LOCALAPPDATA%\SwReview\standards.yaml`, and feature 006 states there is **no fallback** -
"no default value exists for any field" (`specs/006-standards-check/tasks.md` T003). Task
**T100** is open and assigns the profile to the owner.

**Done on this workstation:** copied `config/standards.example.yaml` to
`%LOCALAPPDATA%\SwReview\standards.yaml` and confirmed `load_profile` accepts it.

**Still to do, by the owner:** every value in that file is fictional placeholder data. The
quickstart is explicit - "a value left as the example will simply grade documents against a
standard nobody uses". Real values come from the `research.md` R5 table. Fields awaiting
them: `vault_root`, the four `library` prefix lists, `data_card.properties`,
`part_number.pattern`, the `revision` block including `cell.row_from_end` and
`cell.column`, `material.configuration`, `export_control.phrase`.

Until then the tab exercises the mechanism only; its verdicts mean nothing.

**Worth considering upstream:** the refusal is correct but late. The tab could say "no
profile configured - see quickstart" rather than surfacing a file-not-found with a settings
key name, since a first run on any workstation hits this.

---

## 4. Not a bug: Remodel has no seat yet

```
the bridge returned status 'error': this bridge was not built with a remodel seat, so no
remodel command can reach SOLIDWORKS
```

This is the documented refusal. From `ToolService/ToolServiceHost.cs`:

> The seat itself is not wired here: this host attaches to the document the engineer has
> open, and the re-modeler reaches SOLIDWORKS through its own seat, so until one is handed
> over every remodel command answers "this bridge was not built with a remodel seat".

Feature 004's workstation bring-up has not started. Open and **blocking**: `T033`
(PROBE-1), `T034` (PROBE-3/4), `T035` (PROBE-2), plus `T031`/`T032` (the `probe remodel`
command itself) and `T003`/`T004` (the Phase 0 dry run and decision). Remodel cannot work
on this seat until those land.

**Recommendation:** do not test Remodel on this workstation, and consider having the tab
say so up front rather than letting the engineer press Start and receive a bridge error.

---

## 5. NEW BUG: an active drawing stops the tool service from starting

From `%LOCALAPPDATA%\SwReview\logs\addin.log`:

```
[2026-09-18T21:30:13] The SwReview tool service did not start.
System.InvalidOperationException: 'C:\...\810-11471.SLDDRW' reports no active configuration.
   at SwReview.Extractor.Sw.SwSession.ActiveConfiguration(IModelDoc2 document, SwGate gate)
   at SwReview.Extractor.Sw.SwSession.Attach(ISldWorks swApp, String documentPath, ...)
   at SwReview.AddIn.ToolService.ToolServiceHost.Attach(...)
```

The tool service attaches to whatever document is active. A **drawing** has no active
configuration, so `SwSession.Attach` throws and the service never starts - which silently
disables every bridge-backed feature for that session.

**Workaround:** do not have a `.SLDDRW` active when the add-in loads.

**Fix options:** skip drawings when choosing what to attach to and attach to the drawing's
referenced model or to nothing; or catch this and report "the active document is a drawing;
open a part or assembly" instead of an interop exception.

---

## 6. What the features actually produced

Recorded so the next session has a baseline rather than an impression.

### Review (agent, needs a key)

`20260918-215755-…`, the small assembly (one part plus dowel pins), `gpt-5.6-luna`, effort
`high`: **97 s**, **8 findings**, 34 tool calls, 3 evidence requests, 41 KB report.
Coverage: 5 checked, 11 skipped, 39 unresolved, 0 failed, 7 out of scope.

| Severity / status | Check |
|---|---|
| medium / demonstrated | `interference.static` (x2) |
| medium / demonstrated | `rms.grouping.all_features_in_a_group` - 53 content features outside every group |
| medium / demonstrated | `rms.sketches.fully_defined` - `Sketch2` under-defined |
| medium / demonstrated | `rms.assembly.mates_to_reference_geometry` - mates on faces of the part and the dowel pin |
| medium / demonstrated | `rms.params.global_variables_present` - equation manager empty |
| low / suspected | `rms.folders.present` - all six RMS group folders missing |
| low / suspected | `rms.params.dimensions_driven_by_equations` |

Two `interference.static` findings on a dowel-pin assembly are worth an engineer's
judgement: a pin in a reamed hole is often an intentional press fit, which is what the
exception mechanism is for.

An earlier run on the same assembly gave 6 findings in 77 s without the interference pair,
so run-to-run coverage varies - expected for an agent that chooses what to investigate, and
worth watching over more runs.

### Model check (no AI, no key)

`20260918-220310-…-check`, scope `part`: **3 findings**, 1 tool call, 16 KB report.
Coverage: 5 checked, 11 skipped, 5 unresolved, 0 failed, 6 out of scope.

`rms.folders.present` (low), `rms.grouping.all_features_in_a_group` (medium),
`rms.sketches.fully_defined` (medium).

The overlap with the review is expected: feature 003 exposes the RMS rules as tools the
review agent can also call. The review reached the same three conclusions plus interference
and the equation rules.

Note the run folders are distinguishable by construction: a check folder ends in `-check`
and holds `check.json` with no `events.jsonl`; a review folder has `events.jsonl` and no
`check.json`.

### Extract

The evidence package for the assembly came out at **107 KB** `package.json` across 4
components with 23 gaps, in roughly a second as part of the review's own extraction. The
Extract tab is native WinForms and was unaffected by the Sophos problem throughout.

---

## 7. Suggested order for the next session

1. Fix the event-stream handoff. Everything else in the pane is judged through it, and
   without it a working review is indistinguishable from a hung one.
2. Fix the drawing/tool-service crash, or report it clearly.
3. Have the Standards tab and the Remodel tab state their prerequisite up front instead of
   failing into a file-not-found and a bridge error.
4. Only then spend tokens on review quality, and record net minutes saved per design - the
   metric the pilot is actually judged on, and still unmeasured.
