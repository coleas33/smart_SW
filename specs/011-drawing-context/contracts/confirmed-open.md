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
the new records; nothing else in the session changes.

Each candidate's outcome is one coverage item, check `drawing.confirmed_open`, subject the
document id:

| Status | When | Reason |
|---|---|---|
| `checked` | the host read it | "opened read-only, read and closed ({k} sheets)", or "read as it stood; it was already open, so it was left open" |
| `unresolved` | anything else | the host's refusal (section 2), the bridge error, "no SOLIDWORKS connection in this review, so the drawing was not opened; open it and review again", "the package already holds ten drawings, so this one was not opened", or section 4's not-validated sentence |

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
  loaded.
- Nothing the seam calls activates, rebuilds, saves or selects: no `ActivateDoc*`, `Save*`,
  `ForceRebuild*` or selection member appears in its gate log, and `OpenDoc6` and `CloseDoc`
  appear only under their qualified keys.

## 4. Shipped off until the seat confirms it

`DrawingOpenScope.SeatValidated = false`. While it is false, `drawing.read` opens nothing and
answers "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011
probe D14)"; an already-open candidate is still read, since reading it opens nothing. Probe D14
(`probes.md`) runs the seam from `swreview-extract probe drawings --probe D14` with the switch
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
