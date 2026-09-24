# Contract: The Read-Only Open of a Confirmed Candidate

Normative for FR-036, FR-053 to FR-056, User Story 5 acceptance scenarios 5 to 7 and SC-011. The
owner's answer of 2026-09-23 (research R5 Q2); the design is research R2.23. It replaces "the
engineer opens it and reviews again": the product opens the drawing, read-only, itself.

## 1. The trigger, on the backend

The candidate question's options (`questions.md` section 4) are `Yes, open it read-only and read
it` (`checks/drawing_context.CANDIDATE_CONFIRM`), `Review without it`, `It is not the right
drawing`. The page shows them and sends the chosen one verbatim through feature 008's batch route;
the page recognises nothing.

`ReviewRunner.answer_evidence_batch` (`agent/runner.py`), after the answers are marked and before
the resumed turn, calls `tools/drawings.read_confirmed_candidates(context, answered)`, which acts
only when an answered request **is** the candidate question - its `question`, `options` and
`entity_ids` equal the `candidates` `QuestionSpec` that `run_drawing_context` builds for this
package - **and** its answer equals `CANDIDATE_CONFIRM` exactly. Any other answer, or any other
request with the same words, opens nothing.

It then asks the bridge once per candidate of that question, in its (traversal) order, while the
package holds fewer than ten drawing records: `context.bridge.drawing_read(run_id, document_id)`,
where `run_id` is the run folder's own name. With no bridge, nothing is called. After the calls the
package is reloaded from the run folder into `context.ir`, so the resumed turn and every tool see
the new records. When a read succeeded, the runner then restates `check_drawings` over the
reloaded package - one recorded step through the registry's own dispatch, before the resumed turn,
exactly as the pre-run calls it - so each reviewed document's `drawing.context` item is restated
(the candidate's document is now drawn), the drawing just read is compared with the profile
(FR-046), and, with checks first on, the re-call guard answers a repeat from this step rather than
from the pre-run's outcome (008 `contracts/checks-first.md` section 5). Nothing else in the session
changes. *Corrected 2026-09-23 on review*: without the restated step the session held both
"opened read-only, read and closed" and "a drawing with its name sits beside it (candidate)" for
the same document, and under checks first the model could not refresh it (the guard answered
`already_run` and lever 13 had withheld the check). The joint stack and the standards run are not
restated: while `DRAWING_BINDING_VALIDATED` is false no drawing dimension binds, and the standards
run is attached once per review (T066 revisits the stack when it sets the switch).

Each candidate's outcome is one coverage item, check `drawing.confirmed_open`, subject the
document id:

| Status | When | Reason |
|---|---|---|
| `checked` | the host read it | "opened read-only, read and closed ({k} sheets)", or "read as it stood; it was already open, so it was left open" |
| `unresolved` | anything else | the host's refusal (section 2), the bridge error, "no SOLIDWORKS connection in this review, so the drawing was not opened; open it and review again", "the package already holds ten drawings, so this one was not opened", or section 4's not-validated sentence |

A refusal the host answers is a definite answer from a healthy host: the client raises
`BridgeRefusedError` for it (`bridge/client.REFUSING_COMMANDS`) and its circuit breaker never
counts it, so any number of refused candidates leaves the bridge working for the rest of the
review. A `drawing.read` the host never answered (a dead pipe, a timeout) is counted like any
other failure. *Corrected 2026-09-23 on review*: every refusal had counted, so the third refused
candidate opened the client's circuit and the fourth, and every later bridge call, got the
breaker's sentence instead.

## 2. The bridge command, `drawing.read` (protocol 1.3, additive)

```json
{"id": "7", "command": "drawing.read", "params": {"run_id": "<run folder name>", "document_id": "doc:0007"}}
```

Review scope only (`ScopedSecretPolicy`): the general-chat and remodel secrets are answered
`unauthorized`. Any other parameter is refused; **no path is ever accepted**. The console host has
no source for it and answers that this bridge cannot read a drawing.

The host (`IConfirmedDrawingSource` on `BridgeServices`, null by default; the add-in's
implementation) resolves everything from its own records, and refuses, naming the reason and
opening nothing, when any step fails:

1. `run_id` names a review this host started (its session record, as `report.open` resolves a
   chat); its run folder holds the package `SwReviewDump.Run` wrote;
2. the package's root document is the document this bridge is attached to;
3. `document_id` is a part or assembly row of that package's `documents[]`, and
   `drawing_candidates[]` holds a row for it;
4. that row's path equals the candidate path recomputed from the document's own path by the rule
   discovery uses (`OpenDrawingDiscovery.CandidatePath`, one function), compared as discovery
   compares; the file exists;
5. the package holds fewer than ten drawing records.

Item 1's records are `ReviewHost.ReviewRunDirectory(run_id)` in the add-in (T074, pane lane,
2026-09-23): the run folder of the review whose `SessionRecord.RunId` equals `run_id` ignoring
case, or null. The id is compared with the folder name and nothing else - never combined with,
compared with or read as a path, so a full, relative or `..` spelling answers null. Only a review
record answers; a Model check, Standards or remodel record (`TrackCheck`) never does. An id that
two reviews' distinct folders share (the run root moved between them) answers null. The add-in
hands this lookup to its `IConfirmedDrawingSource`; a null answer is item 1's refusal, which names
the `run_id`, and the package's presence in the folder is still item 1's to check.

Then, through the seam of section 3: the drawing is opened when it is not already open, read by the
existing drawing phase (`DrawingDumper`, the reader by document) with every drawing id and the
drawing's `doc:` id continuing the package's own sequences and each view's referenced document
matched against the package's `documents[]` by full path exactly as discovery matches, and closed
when the seam opened it. The package in the run folder is updated through
`PackageAppender.MergeDrawing`: the `DrawingRecord` with `opened_by_review: true` (`data-model.md`
section 1; false is never written - an already-open drawing's record omits it), its `documents[]`
row and manifest entry (`open-drawings.md` section 4), its id appended to
`design.drawing_document_ids`, its gaps appended, and the document's `drawing_candidates[]` row
removed.

*Amended 2026-09-23 (T078, T079)*: a review whose extraction read no drawing carries the dump's
standing drawing gap (`open-drawings.md` section 6: "No open drawing shows this design, so no
drawing was read natively...", or the listing or the profile sentence) beside a `drawing` phase
row `skipped`. Once a confirmed drawing is merged that sentence is false, and the row is not: the
dump did skip. So `MergeDrawing` leaves the row exactly as the dump wrote it and rewords the gap in
its own place - found by its shape (kind `unsupported`, entity kind `drawing`, no entity,
`PackageWriter.IsDrawingPhaseGap`), never by its words - to what stays true of the dump and every
drawing read afterwards, in the order merged:

```text
The extraction read no drawing natively: its drawing phase did not run. Read afterwards, when the
engineer confirmed the candidate question: 'housing.SLDDRW' (opened read-only by the review) and
'pin.SLDDRW' (already open, read as it stood).
```

Every drawing record of such a package is a later read, since the dump writes the gap only when
the phase did not run; a package whose phase ran has no such gap and nothing is reworded. The
reworded gap keeps its kind, so every gap count the backend shows is unchanged.

```json
{"document_id": "doc:0007", "drawing_document_id": "doc:0012", "opened": true, "closed": true,
 "sheets": 2, "gaps": 1}
```

## 3. The guarded seam

`Guard/DrawingOpenGuard.cs`, an `ICallGuard` in the shape of feature 004's `RemodelGuard`: an
allowlist of exactly three interface-qualified keys, matched ordinally; any other qualified key is
refused; a bare name (every read) is `ReadOnlyGuard`'s answer, unchanged. It is recorded as **one
entry** of its own in `specs/004-resilient-remodeler/contracts/guard-allowlist.md`, and it adds
nothing to `RemodelGuard` or `ReadOnlyGuard`.

| Key | Used for | Composition, asserted as integers |
|---|---|---|
| `ISldWorks.DocumentVisible` | hide drawings opened from here on, then restore | `(false, swDocDRAWING = 3)` before the open; `(true, 3)` in a `finally`, also when the open throws or answers null |
| `ISldWorks.OpenDoc6` | the one read-only open | type `3`; options exactly `ReadOnly (2) \| Silent (1) = 3` - never `ViewOnly (4)`, `RapidDraft (8)` or `LoadModel (16)`; configuration `""` |
| `ISldWorks.CloseDoc` | close what the seam opened | only when the seam opened this drawing, and only after `GetOpenDocumentByName(path)` answers the **same COM identity** the open returned; otherwise refused naming the check, nothing closed |

`Sw/DrawingOpenScope.cs` holds the rules over an `IDrawingOpenHost` seam (fakes in the tests; the
interop in `SwDrawingOpenHost`), with its own `SwGate` built on `DrawingOpenGuard` and the host's
recorder:

- **Already open** (`GetOpenDocumentByName(path)` answers before any open): no visibility call, no
  open, no close; the drawing is read as it stands and `OpenedByReview` is false.
- **Not open**: hide, open, restore; `OpenedByReview` is true. A null or throwing open is the
  refusal "SOLIDWORKS could not open '{file name}' read-only ({FileLoadErrors})".
- **Close**: in a `finally` around the read, when and only when `OpenedByReview`, with the
  identity check above. The seam never closes any other document, and never a model the drawing
  loaded. *Corrected 2026-09-23 on review*: once `OpenDoc6` has returned a document its close is
  unconditional. A restore that throws after a successful open closes the drawing without reading
  it, and the refusal names the restore failure, whether the drawing was closed, and that drawings
  opened afterwards may stay hidden until SOLIDWORKS is restarted (a raw `COMException` had escaped
  with the hidden drawing left open); a restore that throws after a failed open is named in the
  open's refusal. A lookup or `CloseDoc` that SOLIDWORKS fails is the close's reason
  (`CloseRefusal`), never an exception that would hide the read's own; a read that throws while
  the close is refused is one refusal carrying both, the read's exception inside it.
- Nothing the seam calls activates, rebuilds, saves or selects: no `ActivateDoc*`, `Save*`,
  `ForceRebuild*` or selection member appears in its gate log, and `OpenDoc6` and `CloseDoc`
  appear only under their qualified keys.

## 4. Shipped off until the seat confirms it

`DrawingOpenScope.SeatValidated = false`. While it is false, `drawing.read` opens nothing and
answers "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011
probe D14)"; an already-open candidate is still read, since reading it opens nothing. Probe D14
(`probes.md`) runs the seam from `swreview-extract probe drawings --out <folder> --probe D14` with the switch
overridden for that one command. T077 sets it true in a commit of its own citing the probe record,
or leaves it false and records why in research R4.

## 5. What does not move

The page, `EvidenceRequest`, the batch route, the tool array, every tool docstring and payload pin,
`TOOL_FUNCTIONS`, the MCP list and the terminal profile: `drawing.read` is a bridge command, never a
model tool, and no tool the model can call names a document. `RemodelGuard`'s allowlist and its
pinned five. A replay of every recorded review (none has a candidate). The command-line extraction,
which still opens no drawing (FR-003).

## 6. The tests

- `extractor/SwReview.Extractor.Tests/DrawingOpenTests.cs` (T069): the guard's table, its
  refusals and its delegation, the keys overriding a read-only denial exactly
  `ISldWorks.DocumentVisible`; the seam's sequence and integers over fakes, the already-open path,
  the null and throwing open, the close identity check, the close on a throwing read, the switch.
- `ConfirmedDrawingReadTests`, `PackageAppenderTests`, `BridgeDispatcherTests` (T071): every
  refusal of section 2, the id continuation, the path matching, the merge, the bound, the scope,
  protocol 1.3.
- `extractor/SwReview.AddIn.Tests/` (T073): the add-in wires the source with its own session
  record and the application thread; an unknown `run_id` refused.
- `reviewer/tests/unit/test_confirmed_drawing_read.py` (T075): section 1's trigger, bound,
  reload and coverage; the other answers; no bridge; the replay and payload invariants.

## 7. Landed as (T069 to T072, 2026-09-23)

- **The seam** (`Sw/DrawingOpenScope.cs`): `Read<T>(path, read)` returns `DrawingOpenResult<T>`
  (`Value`, `OpenedByReview`, `Closed`, `CloseRefusal`); a refusal is `DrawingOpenRefused` with the
  sentence. A close the identity check refuses does not lose the read: the result says why, and
  the confirmed read records it as one gap `drawing_confirmed_open` on the drawing's document id.
  `SeatValidated` is a static property answering `false`; a second constructor takes the switch
  (probe D14 and the seam's tests).
- **The command** (`Bridge/BridgeDispatcher.cs`): `IConfirmedDrawingSource.Read(runId,
  documentId)`, `ConfirmedDrawingResult` and `ConfirmedDrawingRefused` sit beside the dispatcher;
  `BridgeServices.ConfirmedDrawings` is null by default. An unknown `params` member is answered
  "'drawing.read' takes only \"run_id\" and \"document_id\"; \"{name}\" was refused, so nothing
  was opened."; a bridge with no source answers "This bridge cannot read a drawing: only the
  add-in's review host reads a confirmed candidate, from its own review records."; a source's
  refusal is the error word for word.
- **The rules** (`Dump/ConfirmedDrawingRead.cs`) are constructed over seven seams, which the
  add-in (T074) supplies: `runFolderOf(runId)` from its own session records (null for a run it did
  not start), the attached document's path, `File.Exists`, a `DrawingOpenScope` over
  `SwDrawingOpenHost`, the drawing phase (`DrawingDumper` over `SwDrawingReader`), the document
  phase (`PropertyDumper`) and the manifest (`ManifestBuilder`). Section 2's refusals are checked
  in its order, and one more before anything opens: a drawing already a document of the package
  is refused.
- **Identity.** The drawing ids continue the package's own (`DrawingIdAllocators.ContinuingFrom`,
  seeding the scope's allocators prefix by prefix). The drawing's `doc:` id is
  `DocumentIds.For(its path)`: every document id in an extractor package is derived from its path,
  never allocated in sequence, so this is the id any other extraction gives the same drawing, and
  it is checked to be new. Each view is tied to the package's documents by
  `OpenDrawingDiscovery.DocumentResolver` over `documents[]`' own `(path, document_id)` pairs.
- **The merge** (`PackageAppender.MergeDrawing`) is as section 2 says; the candidate member is
  omitted once its last row is removed, and a drawing whose record or document row is already in
  the package is refused with the package unchanged.
