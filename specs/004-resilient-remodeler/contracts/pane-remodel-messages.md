# Page and Host Messages: the Remodel tab

Tab 5 of five. The pane's tabs are **Review, Ask, Extract, Model check, Remodel**, with a step
strip above them. Feature 003 US6 ships tab 4 (Model check); this feature adds tab 5.

Everything in feature 002 `contracts/pane-host-messages.md` applies unchanged and is not restated:
the `{type, id, payload}` envelope with replies echoing `id`, unknown types answered
`{type: "error", payload: {message}}`, the fixed virtual host `swreview.invalid`, the
byte-identical CSP meta tag, the `textContent`-only rule for every untrusted string, and
`NavigationStarting` and `NewWindowRequested` cancelled for any URL outside
`https://swreview.invalid/`.

**Two additions specific to this tab:**

1. The Remodel WebView is created **lazily, on first activation of the tab**, not at add-in load.
   Five tabs would otherwise cost four renderer processes inside the SOLIDWORKS process at
   startup. The browser process and the single `CoreWebView2Environment` are already shared.
   `WebViewFallbackTests` is extended to cover the lazy path, including activation while the
   environment is unavailable.
2. `RemodelHost` owns only `ready` and `remodel.*`. Every other row delegates to feature 003's
   `AddIn/Review/PaneActions.cs`, and the page loads feature 003's `AddIn/web/shared/dom.js`.
   Nothing on this page re-implements `entity.show`, `report.open`, `folder.open`, `log.open`,
   run-root containment, redaction, or the DOM helpers that enforce `textContent`.

## Page to host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, run_root, document: {path, configuration, kind} \| null, limits: {max_changes, max_minutes, max_rebuild_seconds}, remodel: {available: true \| false \| null, message: string \| null}, latest_run: {run_dir, at, state} \| null}`. `available: null` means the tool service is still attaching; the page keeps Remodel actions disabled until it receives a capability answer. |
| `remodel.plan` | `{}` | Refuse with `RemodelUnavailable` before any bridge call when `remodel.available` is false or still unknown. Otherwise read the scope signals off the active document with `remodel.probe_scope` and refuse with `error {error_class}` when there is no document, the document is not a part, it is dirty (`GetSaveFlag()`), it is read-only, it has external references, or it fails the scope gate, **all before anything is copied**. Otherwise create the run folder, copy the source, open and tag the copy, and roll and rebuild it; a non-zero rebuild-error count refuses with `PreexistingRebuildErrors` and deletes the copy, which is the one refusal that happens after a copy exists, because the reading needs a rollback and a rebuild and neither may touch the source. Then dump the copy, carry forward `exceptions.json`, and run the pure planner. Reply `remodel.planned {run_dir, plan_summary}`. Progress via `status` |
| `remodel.start` | `{run_dir}` | Refuse with `RemodelUnavailable` before any bridge call when the seat is false or still unknown. Otherwise run phases B (judge), C (apply) and D (verify) **to completion**; there is no approve-each-change mode. Progress via `status` and `remodel.progress`; each change is pushed as `remodel.change` as it is written. Reply `remodel.started {chat_id}` |
| `remodel.stop` | `{}` | Set the stop flag. The executor finishes the change in flight, inverts it if it failed, finalizes the artifacts, and reports the run as `truncated`. Reply `remodel.stopped {changes_applied}` |
| `remodel.result` | `{run_dir}` | Reply `{changes[], grade_before, grade_after, geometry, rebuild_list[], attestation, state}`, read from the run folder rather than from memory, so the tab answers after a restart |
| `remodel.open_copy` | `{run_dir}` | Activate the copy, re-opening it if it was closed; reply `ok`. The copy lives **only** in the run folder; it leaves through a Save As the engineer performs in SOLIDWORKS |
| `remodel.discard_copy` | `{run_dir}` | `CloseDoc` without saving, delete `copy/`, and **keep every other artifact**; reply `ok {kept: [...]}`  |
| `remodel.show_change` | `{run_dir, change_seq}` | Resolve that change's persist ref through feature 003's `FeatureSelection` and the existing `SwEntityResolver`; reply `entity.shown {ok, state_code, message, full_path \| null}`, deliberately the identical payload `entity.show` already returns, so one resolver serves three tabs |
| `report.open` / `folder.open` / `log.open` | `{run_dir}` / `{run_dir}` / `{}` | Delegated to `PaneActions`. The path is resolved from the host's own run record, canonicalized, and must be a descendant of `run_root` (or the log folder) before it reaches `ShellExecute`; anything else is answered `error` |

`backend.origin` is the page's own origin under the backend prefix,
`https://swreview.invalid/__backend` - the same value feature 002's `init` carries, never the
backend's loopback origin. This page makes no `fetch` today; the field is sent so that one
`init` field means one thing on every tab, and so that a fetch added here later is same-origin,
as this page's `connect-src 'self'` CSP requires. `backend.port` is for the pane and for
diagnostics; no page builds a URL out of it.

The page never supplies a path. `run_dir` is echoed back from a `remodel.planned` the host itself
issued, and the host resolves it against its own run record.

### Refusal classes

`error {error_class, message}`, the shape `settings.save` already uses for `TurnRunning`:

| `error_class` | When |
|---------------|------|
| `NoDocument` | No document is open |
| `NotAPart` | The active document is an assembly or a drawing. v1 is parts only |
| `DocumentDirty` | The source has unsaved changes. The source is never saved by this feature, so the engineer saves it or closes it |
| `DocumentReadOnly` | The source is open read-only, so its state cannot be attested |
| `ExternalReferences` | `ListExternalFileReferencesCount2() != 0` |
| `ScopeRefused` | The scope gate refused. `message` names **every** failing signal, not the first one |
| `PreexistingRebuildErrors` | The part is already broken; nothing the run did could be attributed. The only refusal raised after the copy exists, and the only one whose handler deletes a copy |
| `RunInProgress` | One remodel run per host |
| `RunNotFound` | `run_dir` is not a run this host created |
| `CopyDiscarded` | The run's copy was discarded; the artifacts remain readable |
| `ResumeRefused` | A run interrupted by a crash or an open circuit is never auto-resumed |
| `RemodelUnavailable` | The attached bridge has no remodel seat, or seat availability is still being checked; `message` tells the engineer to run the standalone remodel probe or wait for attachment |

A refusal costs nothing. A half-rebuilt sheet-metal part costs the engineer their afternoon. Per
Principle VI every refusal is recorded as a reported coverage gap, never a silent skip.

## Host to page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "copying" \| "dumping" \| "planning" \| "judging" \| "applying" \| "verifying" \| "saving" \| "backend_starting" \| "ready" \| "error", message}`. `backend_starting`, `ready` and `error` are also the backend-lifecycle stages the add-in fans out to every page (feature 002 `pane-host-messages.md`); the page writes the message into its run status line and treats none of them as a run phase |
| `remodel.progress` | `{applied, total, current: {seq, kind, subject_name}}` |
| `remodel.change` | one `ChangeRecord` as it is written, so the change list grows live (`run-artifacts.md`) |
| `document.changed` | `{path, configuration, kind, remodel: {available: true \| false \| null, message: string \| null}} \| {path, configuration} \| null`. The additive `remodel` field refreshes capability after tool-service attach/detach. If the **copy** goes away mid-run, the run aborts with the change log intact |
| `backend.stopped` | `{exit_code, log_path}`, unchanged from feature 002 |

## What the page shows

Three stacked regions, all rendered through `web/shared/dom.js`, so every untrusted string
(feature names, descriptions, model rationale, error messages) is inserted with `textContent`:

1. **Run header**: source path, configuration, run folder, run state - the eight `RunState`
   values of data-model.md section 11 and no others, because `remodel.result` reads `state`
   straight out of `plan.json`: `planned`, `judging`, `applying`, `verifying`, `saved`,
   `truncated`, `failed`, `discarded` - and the source attestation result (`unchanged` or, as a
   hard failure, `changed`).
2. **Result**: the before and after `RmsGrade` as counts per bucket with the fraction secondary
   and **the unresolved rule ids always named alongside** (there is no letter grade and no single
   percentage headline), the geometry verdict as `pass`, `fail` or `unresolved` with the compared
   quantities, and a coverage line stating what tier 1 cannot detect: a reflection, a rigid
   rotation about a symmetry axis, compensating add and remove pairs, any difference occupying no
   volume (split faces, cosmetic threads, material, custom properties, configuration data), and
   surface- and wire-body differences.
3. **Change list and rebuild list**: one row per `ChangeRecord` with its kind, subject, status and
   a **Show** button (`remodel.show_change`); then every feature that could not be reorganized,
   with its reason from the closed taxonomy (`backward_reference`, `shared_sketch`,
   `splits_group`, `cycle`, `radius_unreadable`, `ambiguous_name`, `unclassified`,
   `graph_unreadable`) and the blocking dependency edge. Fillets defaulted to `3-Core` are listed
   as "reviewed as structural; move to Quarantine if cosmetic". Then the judgement section: each
   accepted description, global and classification with the provider and the model that produced
   it, and each rejected proposal with the rule that refused it, listed rather than omitted. The
   page closes with the Resilient Modeling Strategy credit and the sentence that this copy is a
   proposal the engineer accepts or discards, not an engineering acceptance result (FR-056).

Two buttons and what they must say. **Open copy** activates the copy in SOLIDWORKS.
**Discard copy** deletes only the `.SLDPRT` and says so on the button's confirmation:
"Delete the copy. The plan, the change list and the report stay in the run folder."

## Tests

- `RemodelHostTests` mirrors `ReviewHostTests`: every row above, every refusal class, and the
  run-root containment of every path that reaches `ShellExecute`.
- `PaneActions` is parameterized over all three hosts so the four shared rows are **proven**
  identical rather than assumed; `ReviewHostTests` stays green with no edits, which is the
  regression proof for the extraction.
- `RemodelPageInjectionTests`: a feature named `<img src=x onerror=alert(1)>` and a rationale
  containing `</script>` render as text and execute nothing; the CSP meta tag is byte-identical
  to the one in feature 002 `contracts/pane-host-messages.md`.
- A lazy-creation test: no Remodel WebView exists until the tab is activated, and activation with
  the environment unavailable shows the documented fallback panel rather than throwing into
  SOLIDWORKS.
- A resume test: a run folder left in `applying` state - what a run interrupted mid-apply leaves
  on disk - is answered `ResumeRefused`.
