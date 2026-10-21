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
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, run_root, document: {path, configuration, kind} \| null, limits: {max_changes, max_minutes, max_rebuild_seconds}, remodel: {available: true \| false \| null, message: string \| null}, latest_run: {run_dir, at, state, plan_lost: string \| null, running: true \| false} \| null}`. `available: null` means the tool service is still attaching; the page keeps Remodel actions disabled until it receives a capability answer. `plan_lost` is `RemodelHost.PlanLostMessage` when the latest run is a plan that can no longer be started, by `remodel.plan_lost`'s own rule, and null otherwise (decision 24A, amended on review, below). *Amended 2026-10-20 (owner decision 155A; `research.md` R18.3):* `running` is true while that run is in flight in this host - started and not yet ended - which `state`, the plan's, does not say. A page that loads again shows such a run running, as the page that pressed Start did: Stop pressable, and none of Remodel a copy, Start, Open copy and Discard copy offered, which the host refuses while the run holds it, until the run's terminal `status` or the answer to Stop ends it; an `init` never ends a run the page shows running. The flag is read, and the `init` posted, under the lock that frees the host at the run's end, so a page is never told after the run's ending that it is in flight |
| `remodel.plan` | `{}` | Refuse with `RemodelUnavailable` before any bridge call when `remodel.available` is false or still unknown. Refuse with `SourceIsRemodelCopy` before any bridge call when the active document is one of the re-modeler's own copies, and when an earlier plan waits for Start, end that plan's session and mark it lost before the probe (T173, below; added 2026-09-26, landed 2026-09-27). Otherwise read the scope signals off the active document with `remodel.probe_scope` and refuse with `error {error_class}` when there is no document, the document is not a part, it is dirty (`GetSaveFlag()`), it has external references, or it fails the scope gate, **all before anything is copied**. A saved, read-only source may proceed; an unreadable read-only signal remains `ScopeRefused`, and *since 2026-09-28 (U26, `tasks.md` T186; default taken 2026-09-28, the owner may revise)* so does a read-only source whose unsaved changes SOLIDWORKS would not report (`save_flag_dirty` null: "Don't prompt to save read-only referenced documents" is selected, or could not be read), its `message` naming the option and the two ways past it. Otherwise create the run folder, hand exactly that folder to the tool service (T158; a hand-over that fails is `BridgeUnavailable`, and nothing is copied and no open is sent), copy the source, open and tag the copy, and roll and rebuild it; a non-zero rebuild-error count refuses with `PreexistingRebuildErrors` and deletes the copy, which is the one refusal that deletes a copy, because the reading needs a rollback and a rebuild and neither may touch the source. Then make the copy the active document - activate only, never an open (T159; `CopyNotActive` otherwise, with nothing dumped) - dump it, carry forward `exceptions.json`, and run the pure planner. Reply `remodel.planned {run_dir, plan_summary}`. Progress via `status`. *Amended 2026-09-27 (T175, T176; below):* once the open was asked for, a plan that fails ends the session before it answers, and a plan made while Start is switched off ends its session before `remodel.planned`. *Amended 2026-10-19 (feature 002, owner decision 145A):* after every refusal that needs no call and before any call - the earlier plan's close (T173) and the probe included - the plan begins through the review host's settings restart: a restart that waits is made first, or the one being made is waited for, and the plan is refused - `TurnRunning` while a review turn holds that restart back, `BackendUnavailable` while the backend does not answer whether a turn runs, or with the restart's failure - with nothing called, created or recorded ("A settings restart and a remodel run", below). *Amended on review the same day:* once the gate has marked the host busy, the active document is read again, before any call, and a plan whose document changed meanwhile is refused `DocumentChanged`. *Amended 2026-10-20 (feature 002, owner decision 154A):* refused first, before every other refusal - a run in progress, the document, the seat, the gate, an earlier plan's session, the probe - `RunRootRefused` when the run root is on a network share, reached through a link or written as a device path, or could not be checked (below). *Amended 2026-10-21 (feature 002, owner decision 154A, with 153A's record of the settings in force):* once its gate is passed, refused `BackendUnavailable`, retryable, while a start of the backend under way would bring another run root into force - the add-in's first start, the one start the gate does not hold back - before anything is asked or made, the host left free (below) |
| `remodel.start` | `{run_dir}` | Refuse with `StartNotValidated` before any bridge call while Start is switched off in this build (T172, below; added 2026-09-26, landed 2026-09-27). Refuse with `SessionLost` before any bridge call when the tool service has re-attached since the plan was made (decision 22A, below). Refuse with `RemodelUnavailable` before any bridge call when the seat is false or still unknown. Otherwise run phases B (judge), C (apply) and D (verify) **to completion**; there is no approve-each-change mode. Progress via `status` and `remodel.progress`; each change is pushed as `remodel.change` as it is written. Reply `remodel.started {chat_id}`. *Amended 2026-10-19 (feature 002, owner decision 145A):* after every refusal that needs no call and before `remodel.started`, the run begins through the review host's settings restart, as a plan does, and is refused the same way, the plan staying startable. Once the restart's gate has marked the host busy, the plan's session is read again, and one that went while the gate waited - the tool service re-attached, or a teardown ended it - is refused `SessionLost`, as before the press, with nothing called and the host left free. *Amended 2026-10-20 (feature 002, owner decision 154A):* refused first, before the run is looked up, `RunRootRefused` when the run root is on a network share, reached through a link or written as a device path, or could not be checked (below): nothing begins and the plan stays startable. *Amended 2026-10-21 (feature 002, owner decision 154A, with 153A's record of the settings in force):* once its gate is passed, refused `BackendUnavailable`, retryable, the same way: nothing begins, and the plan stays startable once the start has ended (below) |
| `remodel.stop` | `{}` | Set the stop flag. The executor finishes the change in flight, inverts it if it failed, finalizes the artifacts, and reports the run as `truncated`. Reply `remodel.stopped {changes_applied}` |
| `remodel.result` | `{run_dir}` | Reply `{changes[], grade_before, grade_after, geometry, rebuild_list[], attestation, state}`, read from the run folder rather than from memory, so the tab answers after a restart |
| `remodel.open_copy` | `{run_dir}` | Activate the copy, re-opening it if it was closed; reply `ok`. The copy lives **only** in the run folder; it leaves through a Save As the engineer performs in SOLIDWORKS. *Amended 2026-10-19 (owner decision 144A; feature 011's research R11.1):* the pane seat makes every call through a gate of its own and takes only the run's copy: a path that is not a full path to a part inside a run folder's `copy/` is refused before any call, and a document SOLIDWORKS answers - the lookup's, the activation's or the open's - that is not at the copy's own path is neither activated nor taken as the copy, and is not named; either way the reply is `error` `OpenFailed` with the seat's sentence, as for any failure of the seat; and the action writes its begin and outcome lines to the run's `remodel.log` (`run-artifacts.md`). *Amended 2026-10-20 (feature 011, owner decision 148A; its research R12.3, R12.4):* the path is taken by `RemodelCopy.CopyOf`, the one rule `remodel.open` takes the copy by; and while a plan or a run is in flight in this host - any run's, not only this one's - Open copy is refused `RunInProgress`, retryable, before anything is asked of SOLIDWORKS, in the words of `RemodelHost.OpenCopyWhileARunIsInProgressMessage`, which name no path; the page disables Open copy while a run runs, as it disables Discard copy. *Amended on the decision's second review (feature 011 research R12.8a):* and both while a plan is made, the host's "a plan or a run": a press mid-plan waited behind the plan on the host's one message thread and acted on the earlier run's copy while the page showed the new plan |
| `remodel.discard_copy` | `{run_dir}` | `CloseDoc` without saving, delete `copy/`, and **keep every other artifact**; reply `ok {kept: [...]}`. The close goes only through the attachment the run's plan was made on; when that attachment is gone the close is skipped and the rest is unchanged (decision 22A, T168, below). *Amended 2026-10-20 (feature 011, owner decision 148A's second review; its research R12.8a):* the page offers Discard copy as it offers Open copy - not while a plan is made or a run runs; the host refuses a discard only while its own run is in flight (`RunInProgress`) |
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
| `DocumentDirty` | The source has unsaved changes. The source is never saved by this feature, so the engineer saves it or closes it. *Amended 2026-10-20 (owner decision 155A; `research.md` R18.1):* `message` is `RemodelHost.DocumentDirtyMessage`, in plain words with no path, whoever refused - this host's reading of the probe's signals, or the bridge's probe or its reading of the part again inside `remodel.open`, whose sentences name the part's full path and which the backend passes on ([`backend-remodel.md`](backend-remodel.md)); the run line's `status {stage: "error"}` posted beside a refusal of the bridge's carries the same words |
| `ExternalReferences` | `ListExternalFileReferencesCount2() != 0`. *Amended 2026-10-20 (owner decision 155A):* `message` is `RemodelHost.ExternalReferencesMessage`, whoever refused, as for `DocumentDirty`; it names no button, since pressing again changes nothing |
| `ScopeRefused` | The scope gate refused. `message` names **every** failing signal, not the first one. *Since 2026-09-28 (U26):* including an unresolved `save_flag_dirty` on a read-only source, worded with the option to turn off. *Amended 2026-10-20 (feature 002, owner decision 149A):* the backend's `ScopeRefused` for the bridge's `scope_not_probed` and `scope_changed` on `remodel.open` carries plain words that name no path ([`backend-remodel.md`](backend-remodel.md), Error classes), where it carried the bridge's sentence, which can name the part's full path; this host's own, after the probe, names the gate's signals and no path |
| `PreexistingRebuildErrors` | The part is already broken; nothing the run did could be attributed. The only refusal raised after the copy exists, and the only one whose handler deletes a copy. *Amended 2026-09-27 (T159):* `CopyNotActive` is raised after the copy exists too, and deletes nothing, so this stays the only one that deletes a copy |
| `RunInProgress` | One remodel run per host. *Amended 2026-10-20 (feature 011, owner decision 148A):* also `remodel.open_copy` while a plan or a run is in flight, since the copy activated or opened between the run's requests to the bridge would change the document SOLIDWORKS has active under the run |
| `RunNotFound` | `run_dir` is not a run this host created. *Amended 2026-10-20 (owner decision 155A):* `message` is `RemodelHost.RunNotFoundMessage`, in plain words with no path, on every row that looks a run up - `remodel.start`, `remodel.result`, `remodel.open_copy`, `remodel.discard_copy`, `remodel.show_change` and the shared rows' lookup (`report.open`, `folder.open`, `entity.show`) - where it named the folder the page sent. `remodel.stop`'s own, with no run in flight, named none and is unchanged |
| `CopyDiscarded` | The run's copy was discarded; the artifacts remain readable |
| `ResumeRefused` | A run interrupted by a crash or an open circuit is never auto-resumed |
| `SessionLost` | The tool service re-attached between the plan and Start - which it does when SOLIDWORKS switches documents - so the bridge session holding the plan's copy is gone. Raised by `remodel.start` only, before anything is changed; `message` is `RemodelHost.SessionLostMessage`, in plain words, and sends the engineer back to Remodel a copy. Not retryable: pressing Start again gets the same answer (decision 22A, 2026-09-25) |
| `StartNotValidated` | *Added 2026-09-26 (default taken 2026-09-26, the owner may revise; T172, landed 2026-09-27).* Start is switched off in this build until the workstation probes that decide whether it is safe have verdicts. Raised by `remodel.start` only, before anything is called or written; `message` is `RemodelHost.StartNotValidatedMessage`, in plain words with no command, no path and no probe number, saying that Plan and Discard work and that nothing was changed |
| `SourceIsRemodelCopy` | *Added 2026-09-26 (default taken 2026-09-26, the owner may revise; T173, landed 2026-09-27).* The active document lies in a run folder's `copy/` under `run_root`: it is one of the re-modeler's own copies, not the engineer's part. Raised by `remodel.plan` before any bridge call; `message` names no path and sends the engineer back to their own part. *Amended 2026-10-20 (feature 002, owner decision 154A's reviews, finding F6):* under any run root in force in this SOLIDWORKS session - the one in force, or one a settings save has since moved from - so a copy made before the move is still a copy |
| `BridgeUnavailable` | *Named here 2026-09-27; the class was already answered.* The add-in's tool service is not listening yet, so the re-modeler cannot reach SOLIDWORKS; or (T158's host half, default taken 2026-09-27, the owner may revise) the run folder the host just made could not be handed to the tool service before `remodel.open` - the hand-over answered false or threw - so nothing was copied and no open was sent, and `message` is `RemodelHost.RunNotBoundMessage`, in plain words. Retryable. The backend answers the same class when the bridge does not answer one of its routes (`backend-remodel.md`) |
| `CopyNotActive` | *Added 2026-09-27 (default taken 2026-09-27, the owner may revise; T159).* Before either dump the host makes the copy the active document - activate only, never an open - and SOLIDWORKS could not: it does not have the copy open, would not activate it, or another document was active afterwards; or no copy is left in `copy/` to activate. Nothing is dumped, renamed or posted. `message` is `RemodelHost.CopyNotActiveBeforePlanMessage` before the plan (retryable: plan again) and `RemodelHost.CopyNotActiveAfterChangesMessage` after the changes (not retryable: the run cannot be checked and the copy is not saved), in plain words. Raised after the copy exists, like `PreexistingRebuildErrors`, but it deletes nothing: the run folder and the copy stay as the evidence |
| `RemodelUnavailable` | The attached bridge has no remodel seat, or seat availability is still being checked; `message` says in plain words that Remodel is not in this build yet and that the tab will not change the open part, or asks the engineer to wait for attachment. It names no console command: the standalone probe belongs in the workstation handover, not the Task Pane (U13, 2026-09-22) |
| `TurnRunning` | *Added 2026-10-19 (feature 002, owner decision 145A).* A settings restart waits, and a review turn on the Review tab holds it back: `remodel.plan` and `remodel.start` are refused before anything is called, `message` naming the turn and the Stop on the Review tab - this tab's own Stop stops the run. Retryable: pressed again once the turn ends, the press makes the restart first |
| `BackendUnavailable` | *Named here 2026-10-19; the class was already answered:* the backend is not running (the pipeline's own refusal, before any call). *Added 2026-10-19 (feature 002, owner decision 145A):* also while a settings restart waits and the backend does not answer whether a turn runs - `message` says to save the settings again on the Review tab - when the restart a press made or waited for failed - `message` is the failure, masked - and while the add-in is unloading. *Amended 2026-10-21 (feature 002, owner decision 154A, with 153A's record of the settings in force):* also from `remodel.plan` and `remodel.start` once their gate is passed, while a start of the backend under way would bring another run root into force: `message` says the review backend is being started with another folder for runs, that nothing was copied (a plan) or the plan was not applied (a Start), and Remodel a copy pressed again in a moment; no path. Retryable |
| `RemodelRunning` | *Added 2026-10-19 (feature 002, owner decision 145A).* A settings restart waits and whether a remodel run is in progress cannot be read, which is read as one in progress. Never answered while the host can read its own run: a second press is `RunInProgress` |
| `DocumentChanged` | *Added 2026-10-19 (feature 002, owner decision 145A, found on review).* `remodel.plan` only: the active document - its path or its configuration - is not the one the press was for when the host reads it again after the settings-restart gate, which can wait through a restart for seconds. Raised before any call: nothing is probed, copied or closed, no folder is made, and an earlier plan waiting for Start is left as it was. `message` names no path. Retryable: the engineer makes their part the active document and presses again |
| `RunRootChanged` | *Added 2026-10-20 (feature 002, owner decision 154A's reviews, finding F6).* A `remodel.start` whose plan's run folder is not under the run root in force - a settings save moved the run root after the plan - once its gate is passed and before the run begins: the backend makes runs only under the run root it was started with, and would refuse the folder inside the run. `message` says the plan's run folder is under a run root no longer in force, that the plan was not applied, and the way on, Remodel a copy pressed again; no path. Not retryable. A plan made before the move that is still the active document's copy is refused as `SourceIsRemodelCopy` all the same: every run root in force this session is read (002 `pane-host-messages.md`, "The run root rule") |
| `RunRootRefused` | *Added 2026-10-20 (feature 002, owner decision 154A; 011 research R12.9, items 1 and 2).* The run root is on a network share, reached through a link - a substituted drive, a junction, a symbolic link, any root whose final path differs from its full path other than by letter case - or written as a device path: the backend refuses a run folder on a share on every route, and spells one reached through a link by its final path, which step 4 of `remodel.open` compares with the folder this host binds, so such a root ended every plan. Raised by `remodel.plan` and `remodel.start` first, before anything is asked or made. `message` says which the root is, that nothing was copied (a plan) or the plan was not applied (a Start), and the way on - a local folder chosen for runs in the Review tab's Settings, and Remodel a copy pressed again - and names no path. Not retryable (002 `pane-host-messages.md`, "The run root rule"). *Amended on the reviews of owner decision 154A's merge (feature 002), 2026-10-21:* also a run root with a folder name ending in a space or a period (F1) |
| `RunRootChosenNotInForce` | *Added on the reviews of owner decision 154A's merge (feature 002, N4), 2026-10-21.* `remodel.plan` and `remodel.start`, where `RunRootRefused` would be, while another folder chosen for runs in the Review tab's Settings is saved than the run root in force - its save's restart failed: `message` says what the run root in force is, that nothing was copied (a plan) or the plan was not applied (a Start), and that the folder chosen is not in force until the review backend restarts with it, with the way on, to save the settings again to retry the restart, then Remodel a copy pressed again; no path. Not retryable (002 `pane-host-messages.md`, "The run root rule") |

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
  *Amended 2026-10-20 (owner decision 152A; 002 `research.md`, 152A):* a switch made while a turn,
  a plan or a run holds the bridge is no longer skipped for good. `ToolServiceGate` owes it and
  looks again every second (`FollowPoll`) until nothing holds the bridge - a plan or a run, a review
  turn running, or one the backend gives no answer about - then follows the document active at that
  moment, by its path, as a switch would: a re-attach, so a plan made on the old attachment is lost
  and told as any re-attach is (24A), and a run's end is followed within a second. The planned
  copy's attachment (T180) is kept by that look exactly as by a switch: a plan holds the bridge
  while it opens and activates its copy, and the look once it ends finds the exact held copy active
  and keeps the plan's attachment. With Start switched off (T172) a plan closes its session before
  it answers (T176), so no held copy keeps the attachment, and the look follows whatever the plan's
  close left active: the original part, normally, which changes nothing; or the copy, if the close
  left it open and active, which the tool service then follows, telling the plan lost (24A) where
  before 152A nothing was told until the next switch - put to the owner (002 research 152A). A
  configuration switch re-attaches nothing, at the switch or in a look; a review that finds the
  bridge on another configuration asks the gate to follow the active document
  (`ToolServiceGate.FollowActiveDocument`), which re-attaches it with its configuration, and a plan
  on the old attachment is then lost like any other. *Amended 2026-10-20 (owner decision 152A, on
  the Codex review; 002 `research.md`, 152A):* a plan or a run holds the tool service's attachment
  through the gate (`RemodelHostOptions.HoldToolService`, `ToolServiceGate.HoldAttachment`) from
  just after the host is marked busy - before a plan reads its attachment, before a run's session is
  read again - until the host is free again: a plan's end, whatever ended it, and a run's once its
  session is closed. A look whose busy question was answered before the plan or the run began then
  waits for it rather than taking the bridge down under it, a plan still being planned included; once
  planned, the next look keeps the plan's attachment for its copy as before. With no service
  listening to hold - none started, or one a follow is taking down - a plan is refused
  `RemodelUnavailable`, retryable, in the words while the tool service attaches, and a Start
  `SessionLost`, before any pipeline call; nothing waits for the next service. *Merged with owner
  decision 154A, 2026-10-21 (002 `research.md`, 152A, the merge of `main`):* a plan and a Start
  judge again the run root their gate may have brought in - and a Start checks its plan's folder
  under it - before they take the hold, so a press refused for its run root (`RunRootRefused`,
  `RunRootChosenNotInForce`, `RunRootChanged`, or `BackendUnavailable` while a start of the backend
  would bring another in) takes none, whether or not one was to be had: 154A judges the run root
  before anything is asked or made under it, and the hold asks the tool service (corrected on 152A's
  final reviews, N1).
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
  path, none of the build's plumbing - saying that the engineer's original part was not changed,
  and naming the button the page offers, Plan again, by its label. The page prints it
  verbatim: the Remodel page reads no words file, so the host is its words source.
- **Which plan.** The plan on screen: the host's latest run - the one `init.latest_run` and the
  last `remodel.planned` named - while it is planned and waiting for Start: not started, not
  finished, its copy not discarded. No plan held, nothing told.
- **When it is lost.** By Start's own predicate: the attachment the plan was made on is not the
  one listening now - another one, or none while a restart is in flight. The attachment decides,
  never the document: a re-attach back to the same document is lost, because the attachment
  identity changed; a configuration switch and the same document spelt differently re-attach
  nothing and tell nothing. *Amended 2026-10-13 (T180):* an ending reported for the exact known
  run and copy also loses that held session on the same attachment. A plan closed at Plan while
  Start is switched off remains the deliberate T176 exception.
- **When the host asks.** On every tool-service attach and detach. The add-in's gate calls
  `RemodelHost.RefreshAvailability` each time it withdraws a service and each time a new one
  listens. *Amended 2026-10-13 (T180):* withdrawal still precedes disposal and refreshes the
  capability banner immediately, but the plan-loss notice waits until after the disposal
  attempt. A timeout may leave application-thread cleanup pending, so the notice promises only
  that the engineer's original part was not changed; late cleanup facts are reported separately. And once more when a plan releases the host,
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

### Held-copy activation and finished-run closure (T180)

*Recorded 2026-10-13 before Start enablement.* With a validated Start seam, a waiting plan
preserves its original tool-service attachment only for the exact copy recorded by that
host's latest planned run, on that run's original pipe, while its session is still held.
Case and canonical path spelling do not change identity. An arbitrary path under `copy/`,
a different run or attachment, a discarded or ended copy, and a finished run do not qualify.
The scheduled follow checks the current active document, so a later document change cannot
make an older copy-activation event preserve the wrong attachment. An ordinary document
switch retains the existing teardown/re-attach behavior; this exception does not make the
waiting host busy.

After the executor finishes, the host closes the held session through the existing pipeline
close with `discard_copy: false`, before it releases its busy guard. It preserves the saved
copy and every report/artifact. An answered close marks that exact run ended so a later
Discard cannot close a newer waiting plan on the same pipe. An unanswered close reports
that cleanup is unconfirmed and may leave the copy open. The next plan can open normally
after an acknowledged ending. The shipping Start switch remains off until the separate
workstation gates authorize enablement.

### When a re-attach or an unload ends the session (T167)

*Added 2026-09-26 (default taken 2026-09-26, the owner may revise; 004 T167, not yet built).* A
tool-service re-attach or an add-in unload now ends the plan's session on the application thread
before the old pipe closes (`bridge-remodel.md`, "Ending a session"): the copy is closed unsaved
and stays in `copy/`, and the four settings `remodel.open` changed are restored. **The page is
told no cleanup error when that succeeds**: the plan is lost exactly as decision 24A says.
*Amended 2026-10-13 (T180):* `SessionLostMessage`, `PlanLostMessage` and `PlanClosedMessage`
reassure only that the original part was not changed, including a disposal timeout, failure
or an answered close that left settings or the copy open. When the teardown reports a failure, the host posts **one** `status`
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
session, post nothing. *Amended 2026-09-27 (004 T177):* a `remodel.open` that fails after it
changed the settings is an ending too, with the reason `remodel.open`, and is worded the same way:
the reason decides no word. A session tag the routine could not remove is not worded: the close is
unsaved, so a closed copy took its tag with it, and a copy left open is already said. *Restated
2026-09-27 on review (T183, research R15.5):* the untag reaches only the open document - an unsaved
close discards the tag there, and a copy `remodel.save` saved keeps on disk the tag it was saved
with, whatever the untag answered - so a failed untag changes nothing on disk, and a copy
left open is already said.
*Amended 2026-09-27 (default taken 2026-09-27, the owner may revise; `tasks.md` T179, research
R15.3):* `CopyClosed` is now what SOLIDWORKS answered - `CloseDoc` returned and SOLIDWORKS then has
no document open at the copy's path - so a close it did not carry out, and one nobody could
confirm, are a copy not closed, and the page says that the copy may still be open, which is true of
both. The words are unchanged; the page stays quiet about the copy only when its close was confirmed.

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

### A plan leaves no session behind (T175, T176)

*Added 2026-09-27 (defaults taken 2026-09-27, the owner may revise; 004 T175 and T176, research
R14.1 and R14.2).* Once `remodel.plan` has asked the pipeline for the open, the bridge may hold a
session: the copy open and tagged, and the engineer's four application-wide settings changed.

1. **A plan that fails from there closes it** (T175): the open refused or failed, or the plan step
   after it failed (`CopyNotActive`, the dump, `POST /remodel/plan`). The host closes through the
   pipeline's close (`backend-remodel.md`, `POST /remodel/close` with `discard_copy: false`: the
   routine, unsaved, deleting nothing), before the page is answered, and the page gets the plan's
   own refusal unchanged; a close that fails is swallowed, and the copy and the run folder stay as
   the evidence. `PreexistingRebuildErrors` keeps its own close-and-delete, once. So a Remodel a
   copy pressed again is not refused `RunInProgress` by a bridge still holding the failed plan's
   session.
2. **While Start is switched off, a plan made closes it before `remodel.planned`** (T176), since no
   Start can use it: after the run is recorded and before the `ready` status, the same close, the
   copy left in `copy/` and `plan.json` `planned`. The plan is on screen and not lost; Start is
   `StartNotValidated` as before; Discard deletes `copy/` and sends no close, and planning again
   sends none for it (`RemodelHost.HoldsItsSession` reads `RemodelRun.SessionClosedAtPlan`). A close
   the bridge could not answer - `BridgeUnavailable`, or no named refusal - leaves the plan holding
   its session, so Discard, planning again, a re-attach or an unload still end it; one it answered
   ends it, and what it left is the one status error of "When a re-attach or an unload ends the
   session", posted before `remodel.planned`. With Start switched on the plan keeps its session
   for Start (T180 decides what it holds meanwhile, before the switch is set).

So in this build a re-attach or an unload while a plan waits finds no session, and the page hears
only decision 24A's notice. Nothing new is added to the message tables.

### A settings restart and a remodel run (feature 002, owner decision 145A)

*Added 2026-10-19.* A settings save on the Review tab restarts the backend, and a plan or a run holds
the backend for its whole length: the plan calls its `/remodel/*` routes, and the run is a job inside
the backend's process, which a restart kills, leaving the copy half changed. **A remodel run is
treated as a turn** (feature 002 `pane-host-messages.md`, `settings.save`).

- A save made while a plan or a run is in progress is kept, and the backend is restarted with it once
  the plan or the run ends - never under it; the Review tab says so.
- `remodel.plan` and `remodel.start` begin through the review host's restart
  (`RemodelHostOptions.BeginRun`, which the add-in answers through `ReviewHost.BeginRemodelRun`), after
  every refusal that needs no call - so a press refused on the spot makes no restart - and before the
  first pipeline call or `remodel.started`. A restart that waits is made first, as a new review makes it,
  or the one being made - a save's included - is waited for; the host is then marked busy
  (`RunInProgress`) under that restart's own lock, so no restart can begin under the plan or the run.
  While a review turn holds the restart back the press is refused `TurnRunning`; while the backend does
  not answer whether a turn runs, `BackendUnavailable`; when the restart the press made or waited for
  failed, `BackendUnavailable` with the failure. A refusal is answered before anything is called,
  created or recorded, in words for this tab: the turn's Stop and the settings are on the Review tab.
- The gate can wait through a restart, seconds in which the host is not yet busy, so the tool service
  is free to re-attach and a teardown to end a plan's session. Start reads the plan's session again
  once the gate has marked the host busy, and a session that went meanwhile is `SessionLost`, in the
  words it has before the press (decision 22A, above): a run never starts on a session that is gone.
- The engineer can make another document active in those seconds too. A plan reads the active
  document again once the gate has marked the host busy, before any call, and one whose document -
  path or configuration - changed is refused `DocumentChanged`, in words that name no path. Without
  it the probe would read the document active by then and the bridge would refuse the open as
  `scope_not_probed`, which reaches the page as `ScopeRefused` with both paths in its message.
  *Amended 2026-10-20 (owner decision 149A):* a part made active in the moment between the second
  reading and the probe still meets that refusal, and it now reaches the page in plain words, with
  no path.
- The page is told when a press meets a restart first. Before the gate, when a restart waits or is
  being made, the host posts `status {stage: "backend_starting"}` - "Waiting for the review backend to
  restart with the saved settings, then reading the part..." for a plan, "...then starting the
  run..." for a Start - which the page writes into its run status line, a backend-lifecycle stage and
  never a run phase. The words are true whether the gate makes the restart, waits for it, or finds a
  turn or a backend that does not answer holding it back and refuses the press (amended on the third
  review the same day: they said the backend was restarting). Only words hang on it: the gate decides,
  and a reading that cannot be made says nothing. A refusal replaces it, and a refused Start, like a
  refused plan, leaves the run status line empty.
- The page is told of every restart with `backend.restarted` (below) and asks `ready` again for the new
  port and token, leaving the run on screen as it is: the run's record is its run folder, which the
  restart does not touch, and this host reads `remodel.result` out of it, not the backend.
- Discard copy's close is one backend round trip and does not hold the restart back: a restart that
  lands during it fails the close, and Discard deletes `copy/` anyway, as it does when the bridge does
  not answer.

## Host to page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "copying" \| "dumping" \| "planning" \| "judging" \| "applying" \| "verifying" \| "saving" \| "backend_starting" \| "ready" \| "error", message}`. `backend_starting`, `ready` and `error` are also the backend-lifecycle stages the add-in fans out to every page (feature 002 `pane-host-messages.md`); the page writes the message into its run status line and treats none of them as a run phase. *Amended 2026-10-19 (feature 002, owner decision 145A, found on review):* `error` also when a settings restart failed once the old backend had stopped, with the failure, masked, as the add-in posts a failed first start; and `backend_starting` from this host itself, before a plan or a Start whose gate makes a waiting settings restart first or waits for one being made ("A settings restart and a remodel run", below). *Amended on the third review the same day:* the add-in marks its own word on the backend `lifecycle: true`, and the page takes down a banner it put up for such an `error` once a later `init` names a backend; no other banner - a run's or a teardown's - and not this host's own `backend_starting` *Amended 2026-10-20 (feature 002, owner decision 150A):* from such an `error` the page's backend strip says "Backend not running" until an `init` names a backend - through an `init` that names none, and whatever banner is put up meanwhile - where it followed `init` alone and said "Backend ready" under that banner; any other `error` - a run's or a teardown's - leaves the strip as it was *Amended on the 150A review, 2026-10-20 (feature 002, owner decision 150A):* the add-in's `error` - a first start that failed, or a settings restart that failed once the old backend had stopped - ends with the way on, "Save Settings on the Review tab to start it again.": the failure is followed by a full stop when it does not end in one, then that sentence *Amended 2026-10-20 (owner decision 155A; `research.md` R18.4):* the page ends its running state on `ready` and `error`, and offers Open copy and Discard copy again, so neither is posted while a run holds the host - from `remodel.started` until the run's session is closed and the host freed - but for one: a Start whose run cannot be handed to its scheduler posts its `error` before it frees the host, on the host's message thread, where a press waits behind it and meets a free host (named on the decision's review, `research.md` R18.8). What the run's ending says meanwhile - the executor's caught failure with its unsolicited `error`, the pipeline's own `error`, and the words of "When a re-attach or an unload ends the session" for a close made under the run - is held and told once the host is free, in the order it was made, then the run's last word and the answer to Stop; the order of the messages is the one they had. The stop when the copy goes away mid-run is `applying` (`document.changed`, below) |
| `remodel.progress` | `{applied, total, current: {seq, kind, subject_name}}` |
| `remodel.change` | one `ChangeRecord` as it is written, so the change list grows live (`run-artifacts.md`) |
| `document.changed` | `{path, configuration, kind, remodel: {available: true \| false \| null, message: string \| null}} \| {path, configuration} \| null`. The additive `remodel` field refreshes capability after tool-service attach/detach. If the **copy** goes away mid-run, the run aborts with the change log intact. *Amended 2026-10-20 (owner decision 155A; `research.md` R18.1, R18.4):* the page is told so in `status {stage: "applying", message}`, `message` being `RemodelHost.CopyGoneMessage` - plain words with no path - as the engineer's own Stop is told, where it was told in `error` with the copy's full path: `error` ended the page's running state while the run still finished the change in flight and held the host |
| `remodel.plan_lost` | `{run_dir, message}`: the plan in `run_dir` can no longer be started, because the tool service re-attached after it was made (decision 24A, above). Posted once per plan, as soon as the host sees it; `message` is `RemodelHost.PlanLostMessage`, printed verbatim. The page disables Start for that plan and offers Plan again; a `run_dir` it is not showing changes nothing |
| `backend.stopped` | `{exit_code, log_path}`, unchanged from feature 002. *Amended 2026-10-20 (feature 002, owner decision 150A):* the page says "The backend stopped. Save Settings on the Review tab to start it again.": the add-in starts the backend when it loads and a settings save, made on the Review tab, restarts it, so reopening the pane, which the sentence named before, starts nothing. No host posts it |
| `backend.restarted` | `{sentences}` - *added 2026-10-19 (feature 002, owner decision 145A):* the add-in restarted the backend with saved settings, a save's restart made at once or one made after it waited, so the port and token of the page's last `init` are the old backend's. `sentences` is empty: the Review tab's sentences about a restart that waited are shown there alone. The page sends `ready` again - once more after an `init` already on its way - takes the new port and token, and leaves the run on screen as it is: it does not read `latest_run` again, since the run's record is its run folder, which the restart does not touch, and this host reads it, not the backend |

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
- *Added 2026-09-27 (lanes D, E and F integrated).* `RemodelPlanEndToEndTests`: a Plan driven over
  the fakes through the real Remodel host, pipeline, gate, tool service and dispatcher, with the
  production seat over recording stand-ins - probe, bind, open, geometry, activation, dump and plan
  in that order, the engineer's part only read, the copy opened once and tagged - then Start
  refused `StartNotValidated` in the host's words with no backend run, a change command refused
  `start_not_validated` at the bridge, and Discard ending the session with nothing posted; and a
  tool service stopped while a plan waits telling the page the plan is lost, then, in one status
  error, the settings its teardown could not put back. *Amended 2026-09-27 (T176):* reworked on
  purpose - the Plan ends with the routine's close, the copy closed unsaved and the settings back
  before `remodel.planned`, and Discard sends no second close; a closing that cannot put the
  settings back posts its one status error before `remodel.planned`; and a tool service stopped
  while a plan waits finds no session, so the page hears only that the plan is lost.
- *Added 2026-09-27 (on review: T175, T176, T177).* `RemodelHostTests`, over a fake pipeline that
  keeps the bridge's one session when asked, so a refused retry fails the case: each failing plan
  step and a failed open closing once before the page is answered, with the plan's own refusal and
  the next plan going ahead; each kind of failed close replacing nothing; no close before the open;
  `PreexistingRebuildErrors` closing once; with Start switched on a plan holding its session until
  Discard; with it off the close before `remodel.planned`, the plan not lost, Discard and planning
  again sending no close for it, an unanswered close leaving the session held and an answered one
  ending it; and a failed open's ending worded as every other.
- *Added 2026-10-19 (owner decision 144A; feature 011 T163 and T174).* `SwRemodelSeatTests`: both
  actions, `ActivateOrOpen` as well as `ActivateOpenCopy`, every call placed under the gate entry of
  the seat's own gate it is made under; the activation by title without a rebuild, and the writable
  open through the one request, `Silent | LoadModel = 17` and never `ReadOnly` or `ViewOnly`; an
  open answering no document, refused naming the load errors; a document that is not at the copy's
  path, from the lookup, the activation or the open, neither activated nor kept; a path that is not
  the run's copy refused before any call, and the canonical form handed on; one hop onto the
  application thread; a COM failure passed on unchanged; the gate refusing any qualified call off
  its allowlist; and the begin and outcome lines. `RemodelPlanEndToEndTests`: the plan's activation
  lines read from the run's `remodel.log`, and Open copy after a plan opening the copy again,
  writable, through the production wiring, with its two lines beside the plan's two and nothing
  refused.
- *Added 2026-10-20 (owner decision 155A; `tasks.md` T189, T193, T195).* `RemodelHostTests`:
  `DocumentDirty` and `ExternalReferences` in the host's words, whoever refused - its own reading of
  the probe, the bridge's probe and the bridge's reading of the part again inside `remodel.open` -
  in the refusal and in the run line's status, with nothing posted naming a path; `RunNotFound` in
  one plain sentence on every row that looks a run up; the copy-gone stop in plain words, in
  `applying`; the four sentences word for word; `init.latest_run.running` true while the run is in
  flight and false otherwise; every `ready` and `error` of a run's ending posted with the host free,
  in order, over five endings; Open copy and Discard copy pressed the moment a failed run's ending
  offers them, answered; and an `init` held inside its post as the run ends never told after the
  ending that the run is in flight. `RemodelPageContractTests`, over the real page and transport: a
  page loaded again mid-run showing the run running, Stop the one button offered and working, and
  the run ending at its terminal status; and the sentences naming the plan button by its label.
