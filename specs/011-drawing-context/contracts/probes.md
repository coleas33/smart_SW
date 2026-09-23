# Contract: The Seat Probes

Normative for the workstation tasks (T062 to T068) and research R4. SOLIDWORKS has no licence on the
development machine; every probe runs at the next sitting on the licensed seat.

## 1. The command

```text
swreview-extract probe drawings [--doc <open drawing or model>] [--probe D1,D4,...]
```

A new subject of the console's existing `probe` command, beside `probe rms` and `probe standards`:
read-only, on the read-only guard watched by a recorder, attached with `AttachForDump`, refusing a
document that is not open (as `probe standards` does), writing no file, printing the gate log at the
end whether or not a probe failed. It prints **ids, counts, member answers, enum numbers and
millimetres only** - never a file name, path, property value, note text or cell text, so its output
can be pasted into `research.md` of a public repository. `--probe` selects sections; the default is
all that apply to the open document's kind.

## 2. The sections

| Probe | Run on | Prints | Recorded in |
|---|---|---|---|
| D1 | an open multi-sheet drawing | the Standards extraction's phase rows, sheet and view counts, gap kinds with counts, elapsed ms | R4, 006 T107 |
| D2 | a model with three drawings open, one hidden behind another window | per open document: position, kind, whether it is visible, the count of views and referenced documents; whether any model appears twice | R4 |
| D3 | a six-sheet drawing, sheet 3 active | `IDrawingDoc.GetViews` per sheet: view count and view types; the same from `ISheet.GetViews`; the active sheet before and after | R4, 006 T103 |
| D4 | a drawing with dimensions at their own precision and at the document's | per dimension: `GetPrimaryPrecision2`, `GetPrimaryTolPrecision2`, `GetUseDocPrecision`, `GetUnits`, `GetUseDocUnits`; the document's preferences 24, 25, 47, 49 | R4, `drawing-source.md` section 2 |
| D5 | a drawing with a model-item and a reference dimension on one hole | per dimension: `Tolerance.Type`, min, max, fit classes; the part's own `ModelDimension` reading of the same dimension | R4 |
| D6 | a part drawing and an assembly drawing of one part, with a diameter, a hole callout and a GTol on known holes | per annotation: the attached entity count and types; per entity the corresponding model entity's type; whether its persistent reference from the owning part equals the face phase's reference for the known face (a boolean and the face id, never the bytes) | R4, T066 |
| D7 | a counterbore callout | `IsHoleCallout`, the callout variables' count and names, `GetText(1..4)` lengths, and whether any read returns the whole rendered text (its length) | R4 |
| D8 | the D5 drawing | the model item's `FullName` shape (the part before `@`, the suffix's form) against the part's | R4, T066 |
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
| D6 and D8: every known callout ties to the right face | T066 sets `DRAWING_BINDING_VALIDATED = True` and adds the known case, fictionalised, as a regression row in `test_drawing_binding.py`; any mismatch leaves it false and records why |
| D7: a whole rendered text is readable | a later task may record it; `text_as_read` stays composed until then |
| D12: out-of-date views read reliably | nothing; an unreliable read keeps such views unusable (their evidence is unused, never guessed) |
| D13: the check fetches the file or takes over a second | discovery skips the candidate check under a vault view and writes one `drawing_candidate` gap saying so - one rule in `OpenDrawingDiscovery`, recorded in research and `open-drawings.md` section 5 |
| D14: every answer as `confirmed-open.md` requires | T077 sets `DrawingOpenScope.SeatValidated = true` in its own commit citing the record; the drawing activated, took focus, was written, stayed locked, or its hidden views did not read: the switch stays false and research R4 records why; models left loaded after the close are recorded, never closed by the product |
