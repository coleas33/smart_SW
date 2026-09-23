# Contract: Open Drawings and Candidates

Normative for FR-008 to FR-016, User Story 2 and SC-002.

## 1. When discovery runs

| Profile | Root | Discovery | Drawing phase reads |
|---|---|---|---|
| `Full` (the Review tab, `swreview-extract dump`) | part or assembly | yes | the attached drawings |
| `Full` | drawing | no | the root drawing (feature 006) |
| `Standards` | drawing | no | the root drawing (feature 006) |
| `Standards` | part or assembly | no | nothing (006 FR-025, amended for `Full` only) |
| `ModelCheck` | any | no | nothing |

Discovery runs in `PackageWriter.Build` after the traversal and before the `document` phase, in the
full build **and** in the reuse probe (`BuildReuseProbe`), because the drawings enter the manifest
the reuse key is taken over. It is not a phase row: `PhaseOrder` keeps its twelve names.

## 2. What discovery reads, through `IOpenDrawingSource`

| Read | Interop (gated name) | Failure |
|---|---|---|
| the open documents | `ISldWorks.GetDocuments` (`GetDocuments`) | one `drawing_discovery` gap, nothing attached |
| each document's kind and path | `IModelDoc2.GetType` (`GetType`), `GetPathName` | a document whose kind or path does not answer is skipped with one `drawing_discovery` gap naming its position |
| each drawing's referenced paths | `IDrawingDoc.GetViews` (`GetViews`), then `IView.GetReferencedModelName` (`GetReferencedModelName`) per view | that drawing is not attached; one `drawing_discovery` gap naming its path |
| a candidate's existence | `File.Exists` through the source's `FileExists(path)` | one `drawing_candidate` gap naming the document |

`SwOpenDrawingReader` is the interop side; `OpenDrawingDiscovery.Discover(tree, documents,
fileExists, options)` is pure and holds every rule below, tested with fakes.

## 3. Matching and order

A drawing is **attached** when a referenced path equals the path of a document the traversal
reached, both put through `Path.GetFullPath` and compared ordinal-ignore-case. A file name alone
never matches. A path spelled through another route to the same file (a mapped drive and its UNC
path) does not match either; within one session SOLIDWORKS reports one spelling per open document,
so the view and the traversal agree, which probe D2 confirms. A drawing that also references documents outside the design is attached; those views
are recorded with `referenced_model_path` and add a `drawing_referenced_document` gap "references
'{path}', which is not part of this review", once per path.

Order: drawings that reference the root document, then by the lowest traversal index of any document
they reference, then by full path ordinal. The first **ten** are attached; each further drawing is
named in one `drawing_attachment_limit` gap: "{n} more open drawings show documents of this design
and were not read: {paths}. Close some and extract again to read them."

## 4. Where attached drawings go

- `ComponentTreeResult.AttachedDrawings` carries the ordered list; `DocumentPaths(tree)` appends
  their paths after the traversal's, so each gets a `documents[]` row (kind `drawing`, its own
  custom properties) and a manifest entry with `configuration: ""`.
- `design.drawing_document_ids` lists every attached drawing in order; for a drawing root, the root
  alone, as today.
- The `drawing` phase runs once and reads each drawing in order through one `DrawingDumper`, the ids
  allocated from the scope (`native-evidence.md` section 1); the phase row is `ok` when every drawing
  was read, `failed` with its gaps otherwise.
- Drawings are **not** components: no `ComponentInstance` is synthesised for an attached drawing
  (only a drawing root has the forest root node).

## 5. Candidates

For each part or assembly document the traversal reached that no attached drawing references,
`<directory of its path>\<file stem>.SLDDRW` is asked once - one function,
`OpenDrawingDiscovery.CandidatePath`, which the confirmed open recomputes with. When it exists, one
`DrawingCandidate` `{document_id, path, reason: "same_name_beside_model"}` is written, in
traversal order. The extraction never opens, reads, lists or fetches the file; no other name,
extension or folder is asked about. Only the engineer's confirmation of the candidate question
opens it, read-only, through `confirmed-open.md` (owner, 2026-09-23, research R5 Q2).
Suppressed and lightweight components' documents are asked about too - their files exist whether
or not the component is resolved. A document without a path is not asked about.

A same-name path that is **already open** is never a candidate: discovery examined it and it shows
none of the design (had it shown the document, it would be attached). It is named instead in one
`drawing_candidate` gap: "the open drawing '{path}' has the name of {document} but shows none of this
design, so it was not read". It raises no question.

## 6. The drawing gap

`PackageWriter.Finish`'s standing gap becomes three sentences by case:

| Case | Sentence |
|---|---|
| The phase ran | no gap (today) |
| `Full`, part or assembly root, nothing attached | "No open drawing shows this design, so no drawing was read natively. Open its drawing in SOLIDWORKS and extract again to include it." |
| Any other profile that skipped it | today's: "Drawing sheets were not read natively: the drawing phase did not run under the '{profile}' profile. Any sheets in this package came from the PDF ingest." |

## 7. Identity and reuse

The reuse key changes when the set of attached drawings changes, because their manifest entries
(path, size, write time) are in it; `ReuseRefusals` needs no new rule. A package reused from a run
with a drawing is refused when that drawing is closed, and the reverse, by the key alone.

## 8. The tests

`OpenDrawingDiscoveryTests` (pure): every row of sections 2, 3 and 5, the ten-drawing bound at 10
and 11, ordering with shuffled input, case and `..` normalisation, the file-name-only non-match.
`PackageWriterTests`: section 1's table with fakes; section 4 (rows, manifest, design ids, unique ids
across two drawings, phase list unchanged); section 6's sentences (the `full` part-root assertion
edited deliberately); section 7 (keys differ with and without an attached drawing; the probe and the
full build agree).
