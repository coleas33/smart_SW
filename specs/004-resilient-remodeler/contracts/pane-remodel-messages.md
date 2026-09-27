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
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, run_root, document: {path, configuration, kind} \| null, limits: {max_changes, max_minutes, max_rebuild_seconds}, remodel: {available: true \| false \| null, message: string \| null}, latest_run: {run_dir, at, state, plan_lost: string \| null} \| null}`. `available: null` means the tool service is still attaching; the page keeps Remodel actions disabled until it receives a capability answer. `plan_lost` is `RemodelHost.PlanLostMessage` when the latest run is a plan that can no longer be started, by `remodel.plan_lost`'s own rule, and null otherwise (decision 24A, amended on review, below). |
| `remodel.plan` | `{}` | Refuse with `RemodelUnavailable` before any bridge call when `remodel.available` is false or still unknown. Refuse with `SourceIsRemodelCopy` before any bridge call when the active document is one of the re-modeler's own copies, and when an earlier plan waits for Start, end that plan's session and mark it lost before the probe (T173, below; added 2026-09-26, landed 2026-09-27). Otherwise read the scope signals off the active document with `remodel.probe_scope` and refuse with `error {error_class}` when there is no document, the document is not a part, it is dirty (`GetSaveFlag()`), it is read-only, it has external references, or it fails the scope gate, **all before anything is copied**. Otherwise create the run folder, hand exactly that folder to the tool service (T158; a hand-over that fails is `BridgeUnavailable`, and nothing is copied and no open is sent), copy the source, open and tag the copy, and roll and rebuild it; a non-zero rebuild-error count refuses with `PreexistingRebuildErrors` and deletes the copy, which is the one refusal that deletes a copy, because the reading needs a rollback and a rebuild and neither may touch the source. Then make the copy the active document - activate only, never an open (T159; `CopyNotActive` otherwise, with nothing dumped) - dump it, carry forward `exceptions.json`, and run the pure planner. Reply `remodel.planned {run_dir, plan_summary}`. Progress via `status` |
| `remodel.start` | `{run_dir}` | Refuse with `StartNotValidated` before any bridge call while Start is switched off in this build (T172, below; added 2026-09-26, landed 2026-09-27). Refuse with `SessionLost` before any bridge call when the tool service has re-attached since the plan was made (decision 22A, below). Refuse with `RemodelUnavailable` before any bridge call when the seat is false or still unknown. Otherwise run phases B (judge), C (apply) and D (verify) **to completion**; there is no approve-each-change mode. Progress via `status` and `remodel.progress`; each change is pushed as `remodel.change` as it is written. Reply `remodel.started {chat_id}` |
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
| `PreexistingRebuildErrors` | The part is already broken; nothing the run did could be attributed. The only refusal raised after the copy exists, and the only one whose handler deletes a copy. *Amended 2026-09-27 (T159):* `CopyNotActive` is raised after the copy exists too, and deletes nothing, so this stays the only one that deletes a copy |
| `RunInProgress` | One remodel run per host |
| `RunNotFound` | `run_dir` is not a run this host created |
| `CopyDiscarded` | The run's copy was discarded; the artifacts remain readable |
| `ResumeRefused` | A run interrupted by a crash or an open circuit is never auto-resumed |
| `SessionLost` | The tool service re-attached between the plan and Start - which it does when SOLIDWORKS switches documents - so the bridge session holding the plan's copy is gone. Raised by `remodel.start` only, before anything is changed; `message` is `RemodelHost.SessionLostMessage`, in plain words, and sends the engineer back to Remodel a copy. Not retryable: pressing Start again gets the same answer (decision 22A, 2026-09-25) |
| `StartNotValidated` | *Added 2026-09-26 (default taken 2026-09-26, the owner may revise; T172, landed 2026-09-27).* Start is switched off in this build until the workstation probes that decide whether it is safe have verdicts. Raised by `remodel.start` only, before anything is called or written; `message` is `RemodelHost.StartNotValidatedMessage`, in plain words with no command, no path and no probe number, saying that Plan and Discard work and that nothing was changed |
| `SourceIsRemodelCopy` | *Added 2026-09-26 (default taken 2026-09-26, the owner may revise; T173, landed 2026-09-27).* The active document lies in a run folder's `copy/` under `run_root`: it is one of the re-modeler's own copies, not the engineer's part. Raised by `remodel.plan` before any bridge call; `message` names no path and sends the engineer back to their own part |
| `BridgeUnavailable` | *Named here 2026-09-27; the class was already answered.* The add-in's tool service is not listening yet, so the re-modeler cannot reach SOLIDWORKS; or (T158's host half, default taken 2026-09-27, the owner may revise) the run folder the host just made could not be handed to the tool service before `remodel.open` - the hand-over answered false or threw - so nothing was copied and no open was sent, and `message` is `RemodelHost.RunNotBoundMessage`, in plain words. Retryable. The backend answers the same class when the bridge does not answer one of its routes (`backend-remodel.md`) |
| `CopyNotActive` | *Added 2026-09-27 (default taken 2026-09-27, the owner may revise; T159).* Before either dump the host makes the copy the active document - activate only, never an open - and SOLIDWORKS could not: it does not have the copy open, would not activate it, or another document was active afterwards; or no copy is left in `copy/` to activate. Nothing is dumped, renamed or posted. `message` is `RemodelHost.CopyNotActiveBeforePlanMessage` before the plan (retryable: plan again) and `RemodelHost.CopyNotActiveAfterChangesMessage` after the changes (not retryable: the run cannot be checked and the copy is not saved), in plain words. Raised after the copy exists, like `PreexistingRebuildErrors`, but it deletes nothing: the run folder and the copy stay as the evidence |
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
  *Amended 2026-09-26 (T172, landed 2026-09-27):* `StartNotValidated` joins the order after
  `ResumeRefused` and before `SessionLost`, so a Start this build can never honour says so before
  anything about the plan's session, and the engineer is not sent to plan again for nothing.
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
  SOLIDWORKS is 004 T167's. *Decided 2026-09-26 (default taken 2026-09-26, the owner may revise;
  T167):* the teardown closes it unsaved before the old pipe closes, so a later discard of that run
  finds it closed and deletes `copy/`. *Amended 2026-09-27 (004 T173; default taken 2026-09-27,
  the owner may revise):* nor is a close sent for a run planning again already closed
  (`RemodelHost.HoldsItsSession`, one predicate for Discard's close and planning again's), since the
  session the bridge then holds is the new plan's.

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
- **A page that starts again.** *Amended 2026-09-25 on review (004 T170):* the notice is told
  once per plan, and a page keeps what it was told only while it lives. A page that loads again -
  a reload, or the pane building its view anew - starts from `init` alone, and `init` said
  nothing of a lost plan, so the page showed the lost plan with Start pressable (Start was still
  refused, `SessionLost`). So `init.latest_run` carries `plan_lost`: `PlanLostMessage` when the
  latest run is a plan that can no longer be started, null otherwise. It is the notice's own
  predicate, `RemodelHost.IsLostPlan` - planned and waiting for Start, its copy not discarded,
  made on an attachment that is not the one listening now - read afresh for every `init`, whether
  or not the notice was ever posted and whatever holds the host, since `init` describes the run it
  names; the once-per-plan claim is the notice's alone and `init` neither spends nor needs it. The
  page treats it as the notice for that folder: the same line verbatim, Start disabled and not
  sent, Plan again offered. `init` changes nothing either.

### When a re-attach or an unload ends the session (T167)

*Added 2026-09-26 (default taken 2026-09-26, the owner may revise; 004 T167, not yet built).* A
tool-service re-attach or an add-in unload now ends the plan's session on the application thread
before the old pipe closes (`bridge-remodel.md`, "Ending a session"): the copy is closed unsaved
and stays in `copy/`, and the four settings `remodel.open` changed are restored. **The page is
told nothing when that succeeds**: the plan is lost exactly as decision 24A says, and the "Nothing
was changed" of `SessionLostMessage` and `PlanLostMessage` is now true of the seat as well as of
the part and the copy. When the teardown reports a failure, the host posts **one** `status`
`{stage: "error", message}` to the Remodel page, in plain words: what was left - each setting not
restored, by its Tools > Options label, and whether the copy is still open - and how to put it
right, with no path and no command. The host hears the outcome through
`ToolServiceOptions.RemodelSessionEnded`. Nothing new is added to the message tables.

*The host's half landed 2026-09-27 (lane E; defaults taken 2026-09-27, the owner may revise; the
labels are a seat item).* The host's seam is `RemodelHost.SessionEnded(togglesNotRestored,
commandInProgressNotRestored, copyClosed)`: the toggles the routine could not put back, by their
`swUserPreferenceToggle_e` values (`RemodelSystemToggles`' three); whether `CommandInProgress` is
still set; and whether the routine closed the copy. The add-in maps the routine's outcome onto it
from `ToolServiceOptions.RemodelSessionEnded`, for a teardown that ended a session, when lanes D
and E are integrated. It posts one `status {stage: "error"}` carrying
`RemodelHost.SessionEndedMessage(...)`, and nothing when everything was put back and the copy was
closed. The words say that not everything the plan changed in SOLIDWORKS could be put back and
that the engineer's part was not changed; name each toggle left by its label under Tools >
Options > System Options > General - "Input dimension value", "Show errors every rebuild", "Warn
before saving documents with update errors" - quoted, in that order, once each, and ask for them
to be set back the way the engineer had them; say, for `CommandInProgress`, which has no label,
that SOLIDWORKS may keep some of its messages hidden until it is restarted; and say, for a copy the
routine did not close, that it may still be open, by its `-RMS` suffix and never its path, to be
closed without saving. A value that is not one of the three toggles is worded as another setting,
so nothing that was left goes unsaid. A null list reads as none, and the method never throws: it
is called from the tool service's teardown.

*Recorded 2026-09-27 for lanes D and E integrated (defaults taken 2026-09-27, the owner may
revise).* The add-in sets `ToolServiceOptions.RemodelSessionEnded = outcome => _remodelHost?.SessionEnded(outcome)`,
read through the field per ending, and `RemodelHost.SessionEnded(RemodelSessionEnd)` reads the
routine's outcome onto the three facts above: each name in `SettingsOutstanding` that is a toggle's
`RemodelSystemToggles.SettingName` becomes that toggle, `CommandInProgress` is read apart, and a
name none of the three toggles has is worded as another setting; whether the copy was closed is
`CopyClosed`. The routine tells every ending of a session that existed - `remodel.close`'s
(Discard, planning again) as well as a re-attach's or an unload's - so the same words follow a
Discard or a planning again whose close left something. A null outcome, and an ending of no
session, post nothing. A session tag the routine could not remove is not worded: the close is
unsaved, so a closed copy took its tag with it, and a copy left open is already said.

### Start is switched off until the blocking probes pass (T172)

*Added 2026-09-26 (default taken 2026-09-26, the owner may revise; 004 T172, landed 2026-09-27).*
While `RemodelStart.SeatValidated` is false - until PROBE-1, 2, 3, 4 and 12 have verdicts from a
seat - Plan runs as it does, and so do Discard, Open copy and the report rows, but `remodel.start`
is refused `StartNotValidated` before any pipeline, backend or bridge call, with nothing written,
in the order above. The page prints the host's sentence verbatim in its banner, like every other
refusal. The plan stays on screen and stays readable; once a build with the switch set true is
installed, a new plan starts as today. The bridge refuses the change commands too, as a backstop
(`bridge-remodel.md`, "The Start switch").

*The host's half landed 2026-09-27 (lane E; defaults taken 2026-09-27, the owner may revise).*
The switch is `RemodelStart.SeatValidated` in `SwReview.Extractor/Rms/RemodelStart.cs`, the one
member the bridge's backstop reads too. `StartNotValidated` is not retryable, and
`RemodelHost.StartNotValidatedMessage` names the two buttons that work, Remodel a copy and Discard
copy, by the labels the page gives them. *Integrated with lane D 2026-09-27:* the host takes the
switch as a constructor argument, as T172 says and as lane D built it (`RemodelHost(options)`
passes `RemodelStart.SeatValidated`, and `RemodelHost.StartValidated` reads it back), rather than
as the option lane E recorded; nothing in the add-in passes or assigns a switch
(`RemodelWiringTests`). A plan made while it is off is the plan that starts once it is on, shown as
the same plan made by a host built either way. The sentence is lane D's, which says the plan stays
in its run folder, the page's own words for where it lives.

### Planning again while a plan waits (T173)

*Added 2026-09-26 (default taken 2026-09-26, the owner may revise; 004 T173, landed 2026-09-27).* The
page keeps Plan enabled while a plan waits for Start, and until now a second Plan made a new run
folder only for the bridge to refuse its open as `run_in_progress`, because the earlier session was
still open. Now, when `remodel.plan` arrives while the host's latest run is a plan waiting for
Start (planned, not started, not finished, its copy not discarded):

1. The refusals that need no bridge call come first - `RemodelUnavailable`, `NoDocument`,
   `NotAPart`, `RunInProgress` and `SourceIsRemodelCopy` - so a Plan refused on the spot leaves
   the earlier plan startable.
2. The host ends the earlier plan's session through the pipeline's close (`backend-remodel.md`,
   `POST /remodel/close` with `discard_copy: false`), when that plan's attachment is the one
   listening now - the predicate `remodel.start` and `remodel.discard_copy` share - and sends
   nothing when it is gone, since that session went with its attachment. The copy is closed
   unsaved and stays in `copy/`; the folder stays whole and `plan.json` stays `planned`.
3. The host marks that plan lost in its own run record: the page is told
   `remodel.plan_lost {run_dir, message}` for it once, and a Start naming it is `SessionLost`,
   both with `RemodelHost.PlanClosedMessage`, in `SessionLostMessage`'s plain words.
   `RemodelHost.IsLostPlan` reads the mark as well as the attachment, so an `init` whose latest
   run is still that plan (the new plan was refused) carries the same sentence as `plan_lost`.
4. Then the plan goes ahead as the row above says.

A close the bridge could not answer refuses the new plan with `BridgeUnavailable` and leaves the
earlier plan as it was; a close that answered with what it left posts the status error of "When a
re-attach or an unload ends the session", and the new plan goes ahead, because the bridge clears
the session whatever it left. A new plan the scope gate refuses leaves the earlier plan lost and its
notice standing. `SourceIsRemodelCopy` is checked on every Plan, not only when a plan waits: once
the pipeline activates the copy for its dump (004 T159), the copy can be the active document when
the engineer presses Plan.

*Amended 2026-09-27 (defaults taken 2026-09-27, the owner may revise; `tasks.md`, lane D's note):*
the refusals that need no bridge call keep the order `remodel.plan` already answers them in -
`RunInProgress`, `NoDocument`, `RemodelUnavailable`, `NotAttached`, `NotAPart` - with
`SourceIsRemodelCopy` after them. A close refused as `BridgeUnavailable`, or one that fails without
a named refusal, is a close the bridge could not answer; any other named refusal is one it
answered, and what it left reaches the page as the one status error of "When a re-attach or an
unload ends the session", because `ToolServiceOptions.RemodelSessionEnded` is told every ending,
`remodel.close`'s included. A plan closed this way answers `PlanClosedMessage` for its notice, for
`init.latest_run.plan_lost` and at a Start naming it, whatever else it also lost.
`SourceIsRemodelCopy` is the copy rule `remodel.open` reads (a file in a `copy` folder, the run
folder above it) on the canonical path, plus "that run folder is a direct child of `run_root`",
compared case-insensitively.

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
  `PageRuleScanTests` sweeps this page too. *Added 2026-09-25 on review:* `RemodelHostTests`:
  `init.latest_run.plan_lost` is the host's sentence after a re-attach, the notice still posted
  once; it is so when the attachment changed with no refresh to post the notice; it is null for
  a plan on its own attachment, a finished run and a discarded copy; an `init` changes nothing
  and Start still answers `SessionLost`. `RemodelPageContractTests`: a page reloaded after the
  notice shows it again from `init` - the host's sentence, Start disabled and not sent, Plan
  again pressable - and a page reloaded with `plan_lost` null starts its plan.
- *Added 2026-09-26 (T172 and T173 landed 2026-09-27; T167's pane words not yet built).* T167's, T172's and T173's cases, listed in their tasks:
  `RemodelHostTests` pins the teardown's failure status (the settings and the copy named, no path)
  and silence on success; `StartNotValidated`, its words, its place in the order and that nothing
  is called or written; and planning again - the close, the mark and the notice in that order,
  after the refusals that need no call - and `SourceIsRemodelCopy`. `RemodelPageContractTests`
  pins both sentences reaching the page verbatim and Plan again with a plan held ending in a
  startable new plan.
- *Added 2026-09-27 (lane E: T158's host half, T159, T167's words, T172's host refusal).*
  `BackendRemodelPipelineTests`: the run folder is bound once per open, the request's own, before
  the open and never for the probe, the plan or the run; a bind that answers false or throws is
  `BridgeUnavailable` in the host's words with no open sent; both dumps make the copy the active
  document first, activate only and never an open, and each way that fails is `CopyNotActive` in
  that dump's words with nothing dumped, renamed or posted. `SwRemodelSeatTests`:
  `ActivateOpenCopy`'s calls and arguments over the recording stand-ins, on the application thread,
  with no open in any case. `RemodelHostTests`: `StartNotValidated`'s words, its place in the
  order and that nothing is called or written (with lane D's pin and constructor cases); and T167's words for each thing that
  can be left, alone and together, and silence when nothing was. `RemodelPageContractTests`: each
  new sentence reaching the banner verbatim over the real transport, naming the buttons by their
  labels. `RemodelWiringTests`: the add-in's one pipeline is built with its bind, and nothing in the
  add-in sets the switch: its one host and its one dispatcher are built through the shipped
  constructors, which pass `RemodelStart.SeatValidated`.
