# Contract: The Seat Probes

Normative for the workstation tasks (T062 to T068) and research R4. SOLIDWORKS has no licence on the
development machine; every probe runs at the next sitting on the licensed seat.

## 1. The command

```text
swreview-extract probe drawings --out <folder> [--doc <open drawing or model>] [--probe D1,D4,...]
```

A new subject of the console's existing `probe` command, beside `probe rms` and `probe standards`:
read-only, on the read-only guard watched by a recorder, attached with `AttachForDump`, refusing a
document that is not open (as `probe standards` does), writing no file but its own report, printing
the gate log at the end whether or not a probe failed. It prints **ids, counts, member answers, enum
numbers and millimetres only** - never a file name, path, property value, note text or cell text, so
its output can be pasted into `research.md` of a public repository. `--probe` selects sections; the
default is all that apply to the open document's kind.

*Amended 2026-09-23 (T080, T081)*: every run writes its report - the header (UTC time, SOLIDWORKS
version, the document's kind, the probes), every section and both gate logs, the same lines it
prints - to `drawings-probe-<yyyyMMdd-HHmmss>.txt` in `--out`, which is therefore required; a file
of that name is never written over (the next free `-2`, `-3` is taken). That file is the one thing
the run writes, and it is what the owner brings back in the handoff. **D14 runs only when named**:
the default selection is every other probe that applies, so a run nobody asked to open anything
opens nothing. A named document that is not open is refused before anything is read, and the
report says so without its path; a stop's full message goes to stderr only.

*Amended 2026-09-24 (T066: a named callout must be findable)*: with ids alone the engineer could
not tell which line was "the 10 mm hole callout", so T066 would come back not decidable. D6's and
D8's **dimension lines** now also give, after the id and the sheet, the dimension's name up to its
feature, its view's name and its value -
`name "D1@Sketch2", view "Drawing View1", value 10.0000 mm;` - each `unread` when the extraction
did not read it. The name is the first two `@` segments of `IDimension.FullName`, stopping before
any segment that is a document name, so the file the dimension belongs to is never named; the value
is `IDimension.GetSystemValue3` in millimetres, or degrees for an angle, to four decimals. All three
are what the Standards extraction already read through its guarded reads (`IDimension.FullName`,
`IView.GetName2`, `GetSystemValue3`): the probe adds no read and no writer. Because those lines
carry design names and values, a report with a D6 or D8 section stays in the handoff folder,
outside the repository, like the run folders; the development machine copies only its ids, counts
and answers into research R4, and no name or value from it enters a tracked file or a fixture.
Every other line keeps the rule above.

## 2. The sections

| Probe | Run on | Prints | Recorded in |
|---|---|---|---|
| D1 | an open multi-sheet drawing | the Standards extraction's phase rows, sheet and view counts, gap kinds with counts, elapsed ms | R4, 006 T107 |
| D2 | a model with three drawings open, one hidden behind another window | per open document: position, kind, whether it is visible, the count of views and referenced documents; whether any model appears twice | R4 |
| D3 | a six-sheet drawing, sheet 3 active | `IDrawingDoc.GetViews` per sheet: view count and view types; the same from `ISheet.GetViews`; the active sheet before and after | R4, 006 T103 |
| D4 | a drawing with dimensions at their own precision and at the document's | per dimension: `GetPrimaryPrecision2`, `GetPrimaryTolPrecision2`, `GetUseDocPrecision`, `GetUnits`, `GetUseDocUnits`; the document's preferences 24, 25, 47, 49 | R4, `drawing-source.md` section 2 |
| D5 | a drawing with a model-item and a reference dimension on one hole | per dimension: `Tolerance.Type`, min, max, fit classes; the part's own `ModelDimension` reading of the same dimension | R4 |
| D6 | a part drawing and an assembly drawing of one part, with a diameter, a hole callout and a GTol on known holes | per annotation: the attached entity count and types; per entity the corresponding model entity's type; whether its persistent reference from the owning part equals the face phase's reference for the known face (a boolean and the face id, never the bytes); per dimension also its name, view name and value (section 1, amended 2026-09-24) | R4, T066 |
| D7 | a counterbore callout | `IsHoleCallout`, the callout variables' count and names, `GetText(1..4)` lengths, and whether any read returns the whole rendered text (its length) | R4 |
| D8 | the D5 drawing | per dimension its name, view name and value (section 1, amended 2026-09-24); the model item's `FullName` shape (the part before `@`, the suffix's form) against the part's | R4, T066 |
| D9 | a drawing with GTols, datums and surface-finish symbols | frame counts, symbol and value slot counts, datum label lengths, surface-finish text slot counts | R4 |
| D10 | a drawing with one table of each kind | per table: type, row and column counts, readable cell count; per bill-of-materials row: model path count and how many are open documents | R4 |
| D11 | the D1 drawing | `GetProperties2` items, `GetTemplateName` present or not, preferences 13, 47, 65 answered or not | R4 |
| D12 | an up-to-date view, a view left out of date after a model edit, and a drawing in detailing mode | per view: `ReferencedConfiguration` present, `IsModelOutOfDate`, `IsModelLoaded`; `IsDetailingMode` | R4 |
| D13 | a reviewed part in a vault view whose same-name drawing is not cached locally | `File.Exists` answer, elapsed ms, and whether the local cache gained the file (checked by timestamp before and after, printed as a boolean) | R4 |
| D14 | a reviewed part whose same-name drawing is not open, then the same with the drawing open (`--probe D14`, the one probe that opens a document: it runs `DrawingOpenScope` with its switch overridden for this command) | the `OpenDoc6` type and options integers; the active document's identity (a boolean "unchanged") before, during and after, and whether the engineer's window kept focus; the hidden drawing's sheet and view counts as read; the drawing file's size, write time and SHA-256 equality (booleans) and every open document's save flag before and after; after the close, whether `GetOpenDocumentByName` still answers and whether an exclusive read open of the file succeeds (not locked); the open-document count before, during and after; with the drawing already open, that no visibility, open or close key was gated | R4, T077, SC-011 |

## 3. What each probe's answer changes

| Answer | Change |
|---|---|
| D3: non-active sheets' views come back | nothing; otherwise the per-sheet gap of 006 FR-024 stands for attached drawings too |
| D4: a document-precision dimension reports -1 or the default | `drawings/native.written_precision` reads `dimension_precision_raw` (expected) or `units_decimal_places_raw` - one line, T064 |
| D6 and D8: every known callout ties to the right face | T066 sets `DRAWING_BINDING_VALIDATED = True` (on the development machine, editing only the pin `test_the_switch_ships_off` beside it, T094) and adds the known case, fictionalised, as a regression row in `test_drawing_binding.py`; any mismatch leaves it false and records why |
| D7: a whole rendered text is readable | a later task may record it; `text_as_read` stays composed until then |
| D12: out-of-date views read reliably | nothing; an unreliable read keeps such views unusable (their evidence is unused, never guessed) |
| D13: the check fetches the file or takes over a second | discovery skips the candidate check under a vault view and writes one `drawing_candidate` gap saying so - one rule in `OpenDrawingDiscovery`, recorded in research and `open-drawings.md` section 5 |
| D14: every answer as `confirmed-open.md` requires | T077 sets `DrawingOpenScope.SeatValidated => true` in its own commit citing the record (on the development machine, editing only the pin `TheSeamShipsOffUntilTheSeatConfirmsIt` beside it, T094); the drawing activated, took focus, was written, stayed locked, or its hidden views did not read: the switch stays false and research R4 records why; models left loaded after the close are recorded, never closed by the product |

## 4. Landed as (T080, T081, 2026-09-23)

- **Where.** `extractor/SwReview.Extractor/Probes/`: `DrawingProbeCatalog` (the fourteen, in this
  order, with the kind each runs on; `DefaultFor` leaves D14 out), `DrawingProbeRunner` (the
  sections), `DrawingOpenProbe` (D14), `DrawingProbeReport` (the header and the file), `ProbeText`
  (how everything is printed), `ProbeFiles` (the file seam) and the interop sides
  `SwDrawingProbeReads` and `SwDrawingOpenProbeHost`. The console's `probe drawings` wires them in
  `Program.cs`; `--probe` shares `probe remodel`'s parser.
- **One extraction for the drawing sections.** D1 and D3 to D12 print what the shipped extraction
  read: one Standards extraction of the open drawing with the Standards tab's options, built and
  never written (`PackageWriter.Build`), shared by every section and its failure remembered rather
  than retried. So the seat validates the product's own reads, not a copy of them; a value the read
  did not answer prints `unread`, and D1 counts the gaps by kind.
- **The part's own reading (D5, D6, D8).** Each part document the drawing's views show or its
  attachments name - at most five, the rest counted - gets one Full extraction (the review's options,
  no meshes) **only when SOLIDWORKS already has it open**; a part that is not open is said and never
  opened. D5 and D8 pair a drawing dimension with the model dimension of the same
  `dimension@feature` (the first two `@` segments; none, or several, is said); D8 prints each full
  name's shape - its segment count, `default D<n>` or `renamed (<n> characters)`, and whether the
  last segment is a document name naming the view's document - never the whole name. *Amended
  2026-09-24*: D6's and D8's dimension lines also give the name up to its feature, the view's name
  and the value (section 1; `ProbeText.DimensionName`, `ProbeText.Quoted`, `ProbeText.Nominal`),
  never a document segment. D6 ties an attached
  face to the part's face phase by persistent reference **and** document id, printing the face id,
  its kind and a cylinder's radius; the face phase describes the faces holes, mates and fasteners
  name.
- **The reads beyond the extraction.** D3's `IDrawingDoc.GetViews` per sheet and the active sheet
  read before the extraction and after it (as positions); D7's `GetText(0)` on every hole callout, by
  sheet, view and dimension position, as a length; D10's open check of a bill-of-materials path the
  package did not resolve; D11's `GetProperties2` item count per sheet and preference 13
  (`swDetailingDimensionStandard`); D2's `IModelDoc2.Visible`. Each is gated on the read-only gate
  under the drawing phase's own member names (`DrawingProbeMember`).
- **D2** lists by position: kind, visibility and, for a drawing, its views, blank ones and distinct
  referenced documents; documents listed twice by full path.
- **D13** reads the candidate's directory entry (length, write time, attribute bits) before and after
  the timed `File.Exists`, and prints whether it changed.
- **D14** runs `DrawingOpenScope` with its switch overridden over a recording host, so the integers
  printed are the ones passed. It prints whether the drawing was open before; `OpenDoc6`'s type,
  options (each bit named) and configuration; the `DocumentVisible` calls; the outcome (opened and
  closed, the close's refusal, already open and left open, or the seam's refusal, each with the
  drawing's path, name and stem replaced by `<drawing>`); the active document and the foreground
  window, during and after, compared by identity; the drawing phase's sheet and view counts from the
  hidden drawing's own handle; the file's size, write time and SHA-256 before and after; every open
  document's save flag before and after, and the positions it rose on; whether
  `GetOpenDocumentByName` still answers and whether an exclusive read open succeeds; the open
  documents before, during and after, and those left loaded; the seam's keys; and last, the probe's
  own reading against `confirmed-open.md` - `every answer as required`, or the requirements that were
  not met (for a drawing it opened: the open-mode integers, the open, the active document, the
  foreground window, the drawing's views, the drawing file, the save flags, the close, the lock; for
  one already open: the seam keys, left open, the active document, the foreground window, the
  drawing's views, the save flags). T077 decides; the line only saves reading the others twice.
- **The report.** Beside the read-only gate's log it prints the confirmed open's own guard's
  members, which the read-only log cannot show. Its exit code is 0 when the run completed, whatever
  a probe printed, and 1 when it was refused, stopped or could not write its report.
