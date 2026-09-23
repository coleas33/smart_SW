# Contract: Native Drawing Evidence at IR 1.6.0

Normative for FR-016 to FR-019, FR-026 to FR-031 and SC-005. The fields are `data-model.md`
sections 1 and 2; this contract is what each is read from and what a failed read writes.

## 1. Identity across several drawings

The allocators `dsh`, `dvw`, `ddm`, `dan`, `dnt`, `drv` move from `DrawingTraversal` to
`DumpScope` (`DrawingSheetIds`, ...), and `dtb` (tables) joins them. `DrawingTraversal` takes the
scope's allocators and keeps every other rule it has (sheet order, `index` passed in, `was_active`
derived once). A drawing root's single record is numbered exactly as before; a second drawing
continues the sequences. `DrawingDumper.Dump(scope)` reads `scope.Drawings` - the root drawing, or
the attached drawings in order - and returns one `DrawingRecord` each. *Landed as (T010)*: the
seven allocators are one `DrawingIdAllocators` (`Sheets`, `Views`, `Dimensions`, `Annotations`,
`Notes`, `RevisionTables`, `Tables`) at `DumpScope.DrawingIds`; `scope.Drawings` holds
`ScopedDrawing(documentPath, document)`, and `PackageWriter.ScopeFor` lists a drawing root's own
drawing through `ComponentTreeResult.RootDocument`, the handle the traversal hands over. A
drawing with no handle is one `drawing_sheet` gap naming it, and the others are still read.

## 2. The reader seam

`IDrawingReader` changes in two members and gains the reads below; every member stays one interop
read or names the several it gates itself, as today.

| Member | Was | Now |
|---|---|---|
| `Drawing` | `object? Drawing()` - the session document cast | `object? Drawing(object document)` - that document cast; nothing opened |
| `PersistRef` | `ScopedPersistRef? PersistRef(object entity)` - scoped to the session document | `ScopedPersistRef? PersistRef(object document, object entity)` - scoped to the drawing being read |

`SwDrawingReader` serves the root and every attached drawing; `SwReview.Extractor.Tests/Fakes`'s
drawing fake gains the same members and a second drawing.

## 3. The reads, the fields and the gaps

Every read is through the dumper's gate as today (`TryStep`, `ReadText`, `ReadNumber`); a read that
throws, or a reference read that answers null, writes the gap named, and the field stays null or
empty. **Nothing is activated, selected or opened** by any read.

### Drawing (once per drawing)

| Field | Read (gated name) | Gap kind on failure |
|---|---|---|
| `is_detailing_mode` | `IDrawingDoc.IsDetailingMode` (`IsDetailingMode`) | `drawing_document_settings` |
| `length_unit_raw` | `IModelDocExtension.GetUserPreferenceInteger(47, 0)` (`GetUserPreferenceInteger`) | `drawing_document_settings` |
| `dimension_precision_raw` | `GetUserPreferenceInteger(24, 0)` | `drawing_document_settings` |
| `units_decimal_places_raw` | `GetUserPreferenceInteger(49, 0)` | `drawing_document_settings` |
| `tolerance_precision_raw` | `GetUserPreferenceInteger(25, 0)` | `drawing_document_settings` |
| `drafting_standard_name` | `GetUserPreferenceString(65, 0)` (`GetUserPreferenceString`) | `drawing_document_settings` |

### Sheet

| Field | Read | Gap kind |
|---|---|---|
| `sheet_format_path` | `ISheet.GetTemplateName` (`GetTemplateName`) | `drawing_sheet` |
| `scale_numerator`, `scale_denominator`, `first_angle` | `ISheet.GetProperties2` (`GetProperties2`), items 2, 3, 4 | `drawing_sheet` |
| `tables` | section "Tables" below | `drawing_table_read` |

### View

| Field | Read | Gap kind |
|---|---|---|
| `referenced_configuration` | `IView.ReferencedConfiguration` (`ReferencedConfiguration`) | `drawing_view_state` |
| `is_model_out_of_date` | `IView.IsModelOutOfDate` (`IsModelOutOfDate`) | `drawing_view_state` |
| `is_model_loaded` | `IView.IsModelLoaded` (`IsModelLoaded`) | `drawing_view_state` |
| `scale_decimal` | `IView.ScaleDecimal` (`ScaleDecimal`) | `drawing_view` |
| `orientation_name` | `IView.GetOrientationName` (`GetOrientationName`) | `drawing_view` |

A view whose model is not loaded, or a drawing in detailing mode, still has its annotations read;
the reads that need the model (the attachments below) are not attempted and one
`drawing_attachment` gap names the view.

### Display dimension

| Field | Read | Gap kind |
|---|---|---|
| `text_prefix` ... `text_below` | `IDisplayDimension.GetText(1..4)` (`GetText`) | `dimension_text` |
| `precision_raw`, `tolerance_precision_raw` | `GetPrimaryPrecision2`, `GetPrimaryTolPrecision2` | `dimension_precision` |
| `uses_document_precision` | `GetUseDocPrecision` | `dimension_precision` |
| `units_raw`, `uses_document_units` | `GetUnits`, `GetUseDocUnits` | `dimension_precision` |
| `tolerance`, `tolerance_type_raw`, `fit_hole_class`, `fit_shaft_class` | `GetDimension2(0)` then `IDimension.Tolerance`, `IDimensionTolerance.Type`, `GetMinValue2`, `GetMaxValue2`, `GetHoleFitValue`, `GetShaftFitValue` - the reads and the mapping of feature 010's `ToleranceDumper` (`KindOf`, `IsFitType`), shared, not copied | `dimension_tolerance` |
| `is_reference` | `IsReferenceDim` | `dimension_override` |
| `driven_state_raw` | `IDimension.DrivenState` (`DrivenState`) | `dimension_override` |
| `is_hole_callout`, `hole_callout_variables_raw` | `IsHoleCallout`, `GetHoleCalloutVariables` | `dimension_text` |
| `attached_faces` | section "Attachments" | `drawing_attachment` |

### Annotation (the typed reads, on the record 006 already writes)

| Type (`type_raw`) | Fields | Read | Gap kind |
|---|---|---|---|
| 5, geometric tolerance | `gtol_frames`, `datum_identifier_raw` | `IAnnotation.GetSpecificAnnotation`, then feature 010's `IModelAnnotationReader` members `FrameCount`, `FrameSymbols`, `FrameValues`, `FrameXml`, `DatumIdentifier`, reused | `drawing_symbol_read` |
| 2, datum tag | `datum_label` | `DatumLabel` (010's member) | `drawing_symbol_read` |
| 7, surface finish | `surface_finish_symbol_raw`, `surface_finish_texts_raw` | `ISFSymbol.GetSymbol`, `GetTextCount`, `GetTextAtIndex` | `drawing_symbol_read` |
| 2, 5, 7 | `attached_faces` | section "Attachments" | `drawing_attachment` |

### Attachments

For a display dimension (through `IDisplayDimension.GetAnnotation`) or a typed annotation:
`IAnnotation.GetAttachedEntities3`; for each entity, `IView.GetCorrespondingEntity` on the owning
view; a face is kept, an edge becomes its two adjacent faces (`IEdge.GetTwoAdjacentFaces2`, each
`via: edge`); for each face, the owning part document (the view's referenced document for a part
drawing, the entity's component's document for an assembly drawing) and that document's
`GetPersistReference3`. Faces are deduplicated by reference. Any other entity, or any step that
answers null or throws, adds no row; the annotation gets one `drawing_attachment` gap "{n} of {m}
attached entities could not be tied to a model face". This path is probe D6's; nothing binds through
it until T066 (`drawing-source.md` section 3).

### Tables

`IView.GetTableAnnotations` per view, as feature 006 walks it for revision tables, with the same
type read (`ITableAnnotation.Type`); type 3 goes to `revision_tables` exactly as today, every other
type to the sheet's `tables` as a `DrawingTable`:

| Field | Read | Gap kind |
|---|---|---|
| `title` | `ITableAnnotation.Title` (`Title`) | `drawing_table_read` |
| `row_count`, `column_count` | `RowCount`, `ColumnCount` behind the COM cast feature 006's `TableShape` makes | `drawing_table_read` |
| `rows` | `Text[row, column]` for every cell - the loop of `ReadRevisionTable`, extracted and shared | `drawing_table_read` per cell (the cell null) |
| `bom_rows` | type 2 only: the cast to `IBomTableAnnotation`, `GetModelPathNames(row, out, out)` per data row, each path resolved to a package document id or kept unresolved | `drawing_table_read` |

The per-view walk means a table anchored on the sheet format view is found; a table two views
return is recorded once (deduplicated by persistent reference, else by the COM identity of the
annotation within the view walk).

## 4. The C# tests

`DrawingDumperTests` (fakes) for every row of section 3, each read answering, throwing and answering
null; two drawings in one scope with distinct ids and each drawing's references scoped to itself;
the revision-table tests of feature 006 unedited and green. `DrawingTraversalTests` edited
deliberately where they construct a traversal with its own allocators. `IrSerializerTests` for every
new member omitted when null or empty and present when set, and a 1.5.0 fixture round-tripping.
