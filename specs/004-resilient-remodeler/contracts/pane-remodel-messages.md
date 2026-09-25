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
| `remodel.start` | `{run_dir}` | Refuse with `SessionLost` before any bridge call when the tool service has re-attached since the plan was made (decision 22A, below). Refuse with `RemodelUnavailable` before any bridge call when the seat is false or still unknown. Otherwise run phases B (judge), C (apply) and D (verify) **to completion**; there is no approve-each-change mode. Progress via `status` and `remodel.progress`; each change is pushed as `remodel.change` as it is written. Reply `remodel.started {chat_id}` |
| `remodel.stop` | `{}` | Set the stop flag. The executor finishes the change in flight, inverts it if it failed, finalizes the artifacts, and reports the run as `truncated`. Reply `remodel.stopped {changes_applied}` |
| `remodel.result` | `{run_dir}` | Reply `{changes[], grade_before, grade_after, geometry, rebuild_list[], attestation, state}`, read from the run folder rather than from memory, so the tab answers after a restart |
| `remodel.open_copy` | `{run_dir}` | Activate the copy, re-opening it if it was closed; reply `ok`. The copy lives **only** in the run folder; it leaves through a Save As the engineer performs in SOLIDWORKS |
| `remodel.discard_copy` | `{run_dir}` | `CloseDoc` without saving, delete `copy/`, and **keep every other artifact**; reply `ok {kept: [...]}`. The close goes only through the attachment the run's plan was made on; when that attachment is gone the close is skipped and the rest is unchanged (decision 22A, T168, below)  |
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
| `SessionLost` | The tool service re-attached between the plan and Start - which it does when SOLIDWORKS switches documents - so the bridge session holding the plan's copy is gone. Raised by `remodel.start` only, before anything is changed; `message` is `RemodelHost.SessionLostMessage`, in plain words, and sends the engineer back to Remodel a copy. Not retryable: pressing Start again gets the same answer (decision 22A, 2026-09-25) |
| `RemodelUnavailable` | The attached bridge has no remodel seat, or seat availability is still being checked; `message` says in plain words that Remodel is not in this build yet and that the tab will not change the open part, or asks the engineer to wait for attachment. It names no console command: the standalone probe belongs in the workstation handover, not the Task Pane (U13, 2026-09-22) |

A refusal costs nothing. A half-rebuilt sheet-metal part costs the engineer their afternoon. Per
Principle VI every refusal is recorded as a reported coverage gap, never a silent skip.

### A plan belongs to one tool-service attachment (decision 22A)

*Added 2026-09-25 (owner, decision 22A; 004 T160).* `remodel.open` leaves the run's
`RemodelSession` - the probe, the copy, the toggles - on the dispatcher of the tool service that
answered it (`bridge-remodel.md`, "The session and the tool service's attachment"). When
SOLIDWORKS switches documents and nothing holds the bridge, `ToolServiceGate.FollowDocument`
replaces that service, and a plan waiting for Start holds nothing: `RemodelHost.RunInProgress`
is true only while a plan or a run is executing. **The session does not survive the re-attach,
and Start refuses the plan by name.**

- `RemodelHost` records on each run the attachment its plan was made on: the attachment's pipe
  name (`ToolServiceGate.Attachment`), which `PipeNames` mints fresh for every start, so it names
  one dispatcher. It is read once the plan holds the host busy and before `remodel.probe_scope`.
- `remodel.start` compares it with the attachment listening now. A different attachment, none
  now (a restart in flight), or none recorded is `SessionLost`; a blank name is none, and none
  never matches none, because an unknown attachment is not the same one.
- The order of `remodel.start`'s refusals is `RunNotFound`, `RunInProgress`, `CopyDiscarded`,
  `ResumeRefused`, `SessionLost`, `RemodelUnavailable`, `NotAttached`. A run that can never be
  resumed says so first; a lost session comes before the seat check, because while the service
  is restarting the seat reads as still being checked, and a Start the host answered with a wait
  would only lead to `SessionLost` on the next press. *Amended 2026-09-25 on review:* that order
  decides only a Start that reaches the host mid-restart - one the page sent before the
  availability refresh reached it. It is not what the engineer usually sees. A re-attach reaches
  the page first as that refresh (`ToolServiceGate.Stop` publishes no service, and
  `RemodelHost.RefreshAvailability` posts `available` unknown with
  `RemodelHost.SeatCheckingMessage`); the page then disables Start, shows that wait itself and
  sends nothing, and once the new service is attached Start is pressable again and is answered
  `SessionLost`. So the engineer is asked to wait, by the page, and then told the plan is lost:
  safe, since nothing is changed, but the page learns of the loss only when Start is pressed.
  Telling the engineer at the re-attach itself would need the host to push it, which decision
  22A does not do. `RemodelPageContractTests` pins that sequence. *Amended 2026-09-25 (owner,
  decision 24A):* the host now pushes it (`remodel.plan_lost`, below), so this sequence is what a
  page sees only when that notice has not reached it, and `SessionLost` stays the backstop.
- The refusal is answered before `remodel.started`, before any pipeline, backend or bridge call,
  and writes nothing: not `plan.json`, not the copy, not the run folder, not the engineer's file.
  The run stays readable through `remodel.result`, `report.open`, `folder.open` and
  `remodel.open_copy`.
- The attachment decides, never the document: a re-attach back to the same document is a new
  attachment and is refused; the same document spelt differently and a configuration switch
  re-attach nothing (`FollowDocument` compares the document canonically) and are not refused.
- Start pressed twice after a re-attach is refused twice, identically, and leaves the host free to
  plan; the new plan is made on the attachment listening now and starts. A refused plan tracks no
  run, so a Start naming its folder is `RunNotFound`, and it neither rescues nor invalidates an
  earlier plan.
- The page prints the host's sentence verbatim in its banner, like every other refusal; the
  Remodel page reads no words file.
- *Added 2026-09-25 (decision 22A, found while implementing T160; T168).* `remodel.close` names no
  run: the bridge closes whatever session its dispatcher holds. So `remodel.discard_copy` asks the
  pipeline to close the copy only when the run's attachment is the one listening now - the same
  predicate as Start's - and otherwise deletes `copy/` and writes `discarded` without it. A run
  whose attachment is gone has no session anywhere, and a close sent through the new attachment
  would close the session of the plan made there. A copy the dead session left open in
  SOLIDWORKS is 004 T167's.

### The page is told when a plan is lost (decision 24A)

*Added 2026-09-25 (owner, decision 24A; 004 T170).* Decision 22A refuses Start for a plan whose
tool-service attachment is gone, and the page learned of it only at the next Start. **The host
now tells the page as soon as it sees the plan lost, before the engineer presses anything.**

- **What is told.** `remodel.plan_lost {run_dir, message}`, unsolicited (the table below).
  `run_dir` is the plan's folder as `remodel.planned` named it. `message` is
  `RemodelHost.PlanLostMessage`, in the plain words `SessionLostMessage` keeps - no command, no
  path, none of the build's plumbing - saying that nothing was changed, in the one sentence the
  two share, and naming the button the page offers, Plan again, by its label. The page prints it
  verbatim: the Remodel page reads no words file, so the host is its words source.
- **Which plan.** The plan on screen: the host's latest run - the one `init.latest_run` and the
  last `remodel.planned` named - while it is planned and waiting for Start: not started, not
  finished, its copy not discarded. No plan held, nothing told.
- **When it is lost.** By Start's own predicate: the attachment the plan was made on is not the
  one listening now - another one, or none while a restart is in flight. The attachment decides,
  never the document: a re-attach back to the same document is lost, because the attachment
  identity changed; a configuration switch and the same document spelt differently re-attach
  nothing and tell nothing.
- **When the host asks.** On every tool-service attach and detach. The add-in's gate calls
  `RemodelHost.RefreshAvailability` each time it withdraws a service (before the old one is
  closed) and each time a new one listens, so a re-attach is seen at the withdrawal, while the
  page is still showing the seat-checking wait. And once more when a plan releases the host,
  because nothing is told while a plan or a run holds it: a re-attach that lands during a plan
  (22A's race) is told when the plan ends - about the plan just recorded, lost on arrival, or, if
  that plan was refused, about the plan still on screen. A run holds the tool service
  (`RunInProgress` is part of the gate's busy question), so no re-attach should land under one; a
  refresh during a run tells nothing, and a finished run is not a plan waiting for Start.
- **Once per plan.** A re-attach is two refreshes, the withdrawal and the new service, and two
  re-attaches in a row are four; the page is told once per plan. A plan made on the new
  attachment is told about when it, in turn, is lost.
- **What the page does.** It shows the line in a notice of its own above the run header, apart
  from the banner: the seat-checking wait and its clearing go through the banner and must not
  take the notice with them. It disables Start for that plan and sends no `remodel.start` for it,
  clears the run status line's "Press Start", which is no longer true, and offers **Plan again**,
  the plan button's action (`remodel.plan`) under the notice's own label, pressable whenever the
  plan button is. A notice naming a folder the page is not showing changes nothing. The page keeps
  the notice by folder, so the plan Plan again makes - a new folder - is startable, and a refused
  Plan again leaves the notice where it was. The notice's rules use `web/shared/tokens.css` and
  its text goes through `web/shared/dom.js`.
- **What it changes.** Nothing but the page. The notice writes nothing to the run folder, the copy
  or the engineer's file, and the run stays readable through `remodel.result`, `report.open`,
  `folder.open`, `remodel.open_copy` and `remodel.discard_copy`. `remodel.start` is unchanged:
  `SessionLost` stays the backstop, for a Start that reaches the host before the notice reaches
  the page.

## Host to page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "copying" \| "dumping" \| "planning" \| "judging" \| "applying" \| "verifying" \| "saving" \| "backend_starting" \| "ready" \| "error", message}`. `backend_starting`, `ready` and `error` are also the backend-lifecycle stages the add-in fans out to every page (feature 002 `pane-host-messages.md`); the page writes the message into its run status line and treats none of them as a run phase |
| `remodel.progress` | `{applied, total, current: {seq, kind, subject_name}}` |
| `remodel.change` | one `ChangeRecord` as it is written, so the change list grows live (`run-artifacts.md`) |
| `document.changed` | `{path, configuration, kind, remodel: {available: true \| false \| null, message: string \| null}} \| {path, configuration} \| null`. The additive `remodel` field refreshes capability after tool-service attach/detach. If the **copy** goes away mid-run, the run aborts with the change log intact |
| `remodel.plan_lost` | `{run_dir, message}`: the plan in `run_dir` can no longer be started, because the tool service re-attached after it was made (decision 24A, above). Posted once per plan, as soon as the host sees it; `message` is `RemodelHost.PlanLostMessage`, printed verbatim. The page disables Start for that plan and offers Plan again; a `run_dir` it is not showing changes nothing |
| `backend.stopped` | `{exit_code, log_path}`, unchanged from feature 002 |

## What the page shows

Three stacked regions, all rendered through `web/shared/dom.js`, so every untrusted string
(feature names, descriptions, model rationale, error messages) is inserted with `textContent`.
Above them, under the banner, a plan the host has said can no longer be started is shown as a
notice of its own with **Plan again** (decision 24A, above):

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
- Decision 22A's cases in `RemodelHostTests`: a re-attach between the plan and Start is
  `SessionLost` with nothing called and nothing written; the refusal's place in the order above;
  a re-attach back to the same document, a configuration switch, Start pressed twice, a refused
  plan, a restart in flight and a re-attach that lands during the plan. `ToolServiceWiringTests`
  pins what `ToolServiceGate.Attachment` answers across starts, re-attaches, spellings, drawings,
  a busy bridge and a restart in flight, and `RemodelPageContractTests` that the host's sentence
  reaches the banner verbatim and names the button the engineer presses. *Added 2026-09-25 on
  review:* `RemodelPageContractTests` also pins what a re-attach after the plan shows on the page
  (the wait, then `SessionLost` on the next Start), and `ToolServiceWiringTests` that the add-in
  builds `RemodelHostOptions` in one place and reads `ToolServiceAttachment` off its gate per
  call - the one production line without which every Start is `SessionLost`, since the option's
  default is none.
- Decision 24A's cases (004 T170). `RemodelHostTests`: the notice at the withdrawal, after the
  capability refresh, in the host's words, and nothing more when the new service listens;
  nothing told with no plan held (none yet, a refused plan, a finished run, a discarded copy); a
  re-attach back to the same document told once and still refused at Start; a configuration
  switch, the same document spelt differently and a refresh on the plan's own attachment tell
  nothing; two re-attaches in a row tell once; a refresh while a run is in progress tells
  nothing, and neither does one after it; a re-attach during a plan told when the plan ends,
  about the run it recorded or, when the plan fails, the plan still on screen; a plan made on the
  new attachment told about when it, in turn, is lost; the notice writes nothing and Start still
  answers `SessionLost`; and three of these again through a real `ToolServiceGate` wired as the
  add-in wires it (a re-attach and back, a configuration switch, a switch while a run holds the
  service). `ToolServiceWiringTests`: the gate publishes every attachment change, with the new
  attachment already in place, and nothing else; and the add-in's gate is built in one place, its
  publish callback refreshes the Remodel host and its busy question reads `RunInProgress`.
  `RemodelPageContractTests`: the notice over the real transport - the host's sentence verbatim,
  Start disabled and not sent, Plan again pressable; a refused Plan again leaving the notice and
  an accepted one planning a startable folder; a notice before the plan, for another folder or for
  none changing nothing; the re-attach as the host tells it ending with the notice standing and
  Start disabled; markup written as text; the sentence naming the Plan again button by its label;
  and `tokens.css` linked before `remodel.css`, with the notice's rules naming tokens only.
  `PageRuleScanTests` sweeps this page too.
