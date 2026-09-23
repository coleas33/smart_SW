# Data Model: Drawing Context, Read Only

**Feature**: `011-drawing-context` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

Three things change shape, each additively: the evidence package gains optional members at
schema **1.6.0** (sections 1 and 2); the standards profile gains a **version 3** with one section
(section 7); and the extractor's session and scope gain the types of section 3. The review session
gains nothing: questions are ordinary `EvidenceRequest`s and the one new finding is an ordinary
`Finding`. Everything in sections 4 to 6 is an in-memory Python type, pure and recomputable from
`package.json`, `session.json` and the profile. The contracts in [contracts/](contracts/) are
normative; this is the model.

Every new evidence field is optional, omitted when null or, for a list, when empty
(`ir/models.omit_additive`), mirrored in C# with `WhenWritingNull` or the same omission, and absent
from `required`; `SCHEMA_VERSION` and `EvidencePackage.CurrentSchemaVersion` become `"1.6.0"` and
`ir.schema.json` is regenerated.

---

## 1. Additions to feature 006's drawing models (`ir/models.py`, `Ir/DrawingRecord.cs`)

### `DrawingRecord` (one per drawing document)

| Field | Type | Source | Rules |
|---|---|---|---|
| `is_detailing_mode` | bool \| null | `IDrawingDoc.IsDetailingMode` | null plus a `drawing_document_settings` gap when unread |
| `length_unit_raw` | int \| null | `GetUserPreferenceInteger(swUnitsLinear = 47)` | `swLengthUnit_e` verbatim; Python names it (`mm` 0, `in` 3, others by number) |
| `dimension_precision_raw` | int \| null | `GetUserPreferenceInteger(swDetailingLinearDimPrecision = 24)` | the drawing's default dimension precision |
| `units_decimal_places_raw` | int \| null | `GetUserPreferenceInteger(swUnitsLinearDecimalPlaces = 49)` | recorded until probe D4 says which default governs |
| `tolerance_precision_raw` | int \| null | `GetUserPreferenceInteger(swDetailingLinearTolPrecision = 25)` | |
| `drafting_standard_name` | str \| null | `GetUserPreferenceString(swDetailingDimensionStandardName = 65)` | verbatim; compared by US7 |
| `opened_by_review` | bool \| null | the confirmed open (`contracts/confirmed-open.md`) | `true` only when the product opened this drawing read-only at the engineer's confirmation; omitted otherwise, never `false` (owner, 2026-09-23, research R5 Q2) |

Whether a record is the package's root drawing or an attached one is **derived**, not stored: it is
the root when `document_id == design.root_assembly_document_id`.

### `DrawingSheetRecord`

| Field | Type | Source | Rules |
|---|---|---|---|
| `sheet_format_path` | str \| null | `ISheet.GetTemplateName()` | the `.slddrt` path; null plus a `drawing_sheet` gap |
| `scale_numerator`, `scale_denominator` | float \| null | `ISheet.GetProperties2()` items 2, 3 | both or neither |
| `first_angle` | bool \| null | `ISheet.GetProperties2()` item 4 | true is first-angle projection |
| `tables` | list[`DrawingTable`] | section 2 | every table on the sheet that is not a revision table; omitted when empty |

`revision_tables` is unchanged.

### `DrawingView`

| Field | Type | Source | Rules |
|---|---|---|---|
| `referenced_configuration` | str \| null | `IView.ReferencedConfiguration` | null plus a `drawing_view_state` gap |
| `is_model_out_of_date` | bool \| null | `IView.IsModelOutOfDate()` | null means unread, and binds nothing |
| `is_model_loaded` | bool \| null | `IView.IsModelLoaded()` | |
| `scale_decimal` | float \| null | `IView.ScaleDecimal` | |
| `orientation_name` | str \| null | `IView.GetOrientationName()` | |

### `DisplayDimensionRecord`

| Field | Type | Source | Rules |
|---|---|---|---|
| `text_prefix`, `text_suffix`, `text_above`, `text_below` | str \| null | `IDisplayDimension.GetText(1..4)` | verbatim, empty string kept; null plus a `dimension_text` gap |
| `precision_raw` | int \| null | `GetPrimaryPrecision2()` | the dimension's own decimals, or the answer probe D4 records for "use document" |
| `tolerance_precision_raw` | int \| null | `GetPrimaryTolPrecision2()` | |
| `uses_document_precision` | bool \| null | `GetUseDocPrecision()` | |
| `units_raw` | int \| null | `GetUnits()` | `swLengthUnit_e` for a length |
| `uses_document_units` | bool \| null | `GetUseDocUnits()` | |
| `tolerance` | `Tolerance` \| null | `IDimension.Tolerance` | mapped exactly as feature 010's `ModelDimension.tolerance` (`ToleranceDumper.KindOf`); null is never `none` |
| `tolerance_type_raw` | int \| null | `IDimensionTolerance.Type` | `swTolType_e` verbatim: `NONE` 0 ... `BLOCK` 10, `GENERAL` 11 |
| `fit_hole_class`, `fit_shaft_class` | str \| null | `GetHoleFitValue`, `GetShaftFitValue` | for a fit type only |
| `is_reference` | bool \| null | `IsReferenceDim()` | |
| `driven_state_raw` | int \| null | `IDimension.DrivenState` | `swDimensionDrivenState_e` verbatim |
| `is_hole_callout` | bool \| null | `IsHoleCallout()` | |
| `hole_callout_variables_raw` | list[str] | `GetHoleCalloutVariables()` | each variable's name and value verbatim, in order; omitted when empty |
| `attached_faces` | list[`AttachedFace`] | section 2 | omitted when empty |

The existing `name`, `dimension_type_raw`, `is_overridden`, `override_value`, `value` and the
persistent reference are unchanged.

### `DrawingAnnotation`

| Field | Type | When | Source |
|---|---|---|---|
| `gtol_frames` | list[`GtolFrame`] | `type_raw == 5` | feature 010's frame reads, `GtolFrame` reused |
| `datum_identifier_raw` | str \| null | `type_raw == 5` | `IGtol.GetDatumIdentifier` |
| `datum_label` | str \| null | `type_raw == 2` | `IDatumTag.GetLabel` |
| `surface_finish_symbol_raw` | int \| null | `type_raw == 7` | `ISFSymbol.GetSymbol` |
| `surface_finish_texts_raw` | list[str] | `type_raw == 7` | `ISFSymbol.GetTextAtIndex(0..GetTextCount-1)` verbatim |
| `attached_faces` | list[`AttachedFace`] | types 2, 5, 7 | section 2 |

An annotation of another type gains nothing. A typed read that fails leaves the field null or empty
plus a `drawing_symbol_read` gap naming the annotation.

## 2. New evidence models

### `AttachedFace`

| Field | Type | Rules |
|---|---|---|
| `persist_ref` | `PersistRef` | the model face's persistent reference, from its owning part document's extension |
| `scope` | str | the `document_id` of that part document |
| `via` | Literal["face", "edge"] | `edge`: the annotation was attached to an edge and this is one of its two adjacent faces |

An attached entity that is neither a face nor an edge, or whose model counterpart or reference could
not be read, adds no row and one `drawing_attachment` gap per annotation naming how many were
dropped.

### `DrawingTable` (`DrawingSheetRecord.tables[]`)

| Field | Type | Rules |
|---|---|---|
| `id` | str | `dtb:NNNN`, package-scoped allocation (section 3) |
| `sheet_id`, `owner_view_id` | str | the sheet and the view whose `GetTableAnnotations` returned it |
| `table_type_raw` | int \| null | `ITableAnnotation.Type`, `swTableAnnotationType_e`; never 3 here |
| `title` | str \| null | `ITableAnnotation.Title` |
| `row_count`, `column_count` | int \| null | |
| `rows` | list[`RevisionTableRow`] | feature 006's row model reused: `index`, `cells` (a null cell is unread, an empty one is empty), `is_header` null |
| `bom_rows` | list[`BomRow`] | bill of materials only; omitted when empty |
| `persist_ref`, `persist_ref_scope` | as every drawing record | |

### `BomRow`

| Field | Type | Rules |
|---|---|---|
| `index` | int | the table row |
| `document_ids` | list[str] | `GetModelPathNames(row)` paths that are package documents |
| `unresolved_paths` | list[str] | paths that are not; recorded verbatim |

### `DrawingCandidate` (`EvidencePackage.drawing_candidates[]`)

| Field | Type | Rules |
|---|---|---|
| `document_id` | str | the reviewed part or assembly document |
| `path` | str | the drawing file beside it: same folder, same stem, `.SLDDRW` |
| `reason` | Literal["same_name_beside_model"] | the only rule |

Omitted when empty. Never written for a document that has an attached drawing.

### New gap `entity_kind` values

`drawing_discovery` (the open documents or one drawing's views could not be enumerated),
`drawing_attachment_limit` (open drawings beyond the ten read, named), `drawing_candidate` (an
existence check failed), `drawing_document_settings`, `drawing_view_state`, `dimension_text`,
`dimension_precision`, `dimension_tolerance`, `drawing_attachment`, `drawing_symbol_read`,
`drawing_table_read`. Each has a producing row in `contracts/native-evidence.md` or
`contracts/open-drawings.md`.

## 3. Extractor types (`extractor/SwReview.Extractor`)

| Type | Where | What |
|---|---|---|
| `AttachPurpose` | `Sw/SwSession.cs` | `Model` or `Dump`; `AttachRefusal(kind, path, purpose)` is pure |
| `ISwSession.ConfigurationName` | `Sw/SwSession.cs` | the bound configuration's name, or null for a drawing; `Configuration` becomes `IConfiguration?` |
| `OpenDocument` | `Dump/OpenDrawingDiscovery.cs` | one open document as discovery sees it: path, kind, the paths its views reference, and a handle for the drawing phase; built by `SwOpenDrawingReader` |
| `IOpenDrawingSource` | `Dump/DumpContracts.cs` | `OpenDocuments()` and `FileExists(path)`, the two seams discovery needs |
| `AttachedDrawings` | `Dump/OpenDrawingDiscovery.cs` | the ordered drawings to read (at most ten), the ones named in the limit gap, the candidates; pure `Discover(tree, documents, fileExists, options)` |
| Drawing id allocators | `Dump/DumpContracts.cs` `DumpScope` | `dsh`, `dvw`, `ddm`, `dan`, `dnt`, `drv`, `dtb`, moved from `DrawingTraversal` |
| `IDrawingReader` changes | `Dump/DrawingDumper.cs` | `Drawing(object document)`, `PersistRef(object document, object entity)`; the new reads of section 1 |
| `OpenDrawingDiscovery.CandidatePath` | `Dump/OpenDrawingDiscovery.cs` | `<directory>\<stem>.SLDDRW` of a model path: the one rule discovery and the confirmed open both use |
| `DrawingOpenGuard` | `Guard/DrawingOpenGuard.cs` | the confirmed open's allowlist: `ISldWorks.DocumentVisible`, `ISldWorks.OpenDoc6`, `ISldWorks.CloseDoc` (`contracts/confirmed-open.md` section 3) |
| `DrawingOpenScope`, `IDrawingOpenHost` | `Sw/DrawingOpenScope.cs` | the guarded seam: already open or opened (`OpenedByReview`), hide-open-restore, close only what it opened after the identity check; `SeatValidated = false` until T077 |
| `IConfirmedDrawingSource`, `ConfirmedDrawingRead` | `Bridge/BridgeDispatcher.cs`, `Dump/ConfirmedDrawingRead.cs` | the `drawing.read` command's host side: the refusals, the read with ids continuing the package's, `PackageAppender.MergeDrawing` |

`ComponentTreeResult.AttachedDrawings` carries discovery's result from `PackageWriter.Build` to
`DocumentPaths`, `BuildDesign` and the drawing phase.

## 4. Reading native drawing evidence (`reviewer/src/swreview/drawings/`, pure)

### `drawings/evidence.py`

| Type | Fields | Rules |
|---|---|---|
| `ViewEvidence` | `drawing_id`, `sheet`, `view`, `document_id`, `configuration`, `usable: bool`, `why: str \| None` | one per view that references a package document; `usable` false when the configuration differs from every instance's, the view is or may be out of date, or the model is not loaded |
| `DrawingIndex` | `views_by_document`, `drawings_by_document`, `candidates` | built once per package: which views show which document, in the fixed order drawing id, sheet index, view id |

`DrawingIndex.for_package(package)` never raises on a valid package; it records nothing.

### `drawings/native.py`

| Function | Returns | Rules |
|---|---|---|
| `native_dimension(record, view, sheet, drawing)` | `Dimension` \| str | the IR `Dimension` with `SourceRef(document_id=drawing, sheet=sheet name, annotation=ddm id)` and `text_as_read` composed from the text parts and the value at its written precision; a reason string when the value or its unit is unknown |
| `written_precision(record, drawing)` | int \| None | own precision, the drawing's default when `uses_document_precision`, else None |
| `written_unit(record, drawing)` | Literal["mm", "in"] \| None | own unit or the drawing's; another unit is None with the number kept for the reason |
| `native_sheets(package, document_id)` | list | what `get_drawing_sheet` and `find_dimensions` walk |

### `drawings/binding.py`

| Type | Fields | Rules |
|---|---|---|
| `DRAWING_BINDING_VALIDATED` | bool | `False` until the seat task T066; while false nothing binds and `refs.resolve_dimension` refuses a native dimension (R2.11) |
| `DrawingBinding` | `subject`, `record_id`, `view: ViewEvidence`, `route: Literal["attached_face", "model_dimension"]`, `via_edge: bool` | one piece of drawing evidence tied to one subject |
| `bindings_for(index, package, subject)` | tuple[`DrawingBinding`, ...] | every dimension or annotation that satisfies R2.8, in the fixed order |

### `DrawingAnswer` (`checks/tolerances.py`)

| Field | Type | Rules |
|---|---|---|
| `dimension` | `Dimension` \| None | the first binding with an explicit tolerance |
| `cited` | str \| None | "drawing {document}, sheet {name}, view {name}, {ddm id}" |
| `decimal_places`, `unit` | int \| None, str \| None | from the first untoleranced or block-toleranced binding, when every such binding agrees |
| `conflict` | str \| None | a later binding with different limits or a different precision |
| `why` | str | why nothing bound, when nothing did |

Replaces feature 010's `drawing_tolerance(package, subject) -> Dimension | None`; `SourceKind`
`"drawing"` and its label are unchanged.

## 5. The drawing check (`checks/drawing_context.py`, pure; `tools/drawings.py`)

| Type | Fields | Rules |
|---|---|---|
| `DocumentDrawingCoverage` | `document_id`, `read: tuple[drawing ids]`, `unusable: tuple[(view, why)]`, `candidate: str \| None`, `status: Literal["checked", "skipped", "unresolved"]` | one `drawing.context` coverage item per reviewed part or assembly document |
| `QuestionSpec` | `key`, `what`, `why`, `entity_ids`, `question`, `options`, `blocks` | a question `check_drawings` will write; `key` is `candidates` or `governing:<document id>` |
| `DrawingContextResult` | `coverage`, `questions`, `conformance` (from US7) | `run_drawing_context(package, profile=None)` |
| `CANDIDATE_CONFIRM` | `"Yes, open it read-only and read it"` | the candidate question's first option; the one answer that acts (`contracts/confirmed-open.md` section 1) |

`check_drawings()` returns `{"status": "recorded", "drawings": <read>, "candidates": <n>,
"questions": <n>, "findings": <n>, "finding_ids": [...], "coverage": {...}}`.

`tools/drawings.read_confirmed_candidates(context, answered)` is called by
`ReviewRunner.answer_evidence_batch` and writes one `drawing.confirmed_open` coverage item per
confirmed candidate (`checked` or `unresolved` with the reason); like `drawing.context` it is a
coverage `check`, never a finding's, and closes nothing.

## 6. The brief (`drawings/brief.py`)

`DrawingBrief` serializes to compact JSON in this key order:

| Key | Content | Bound |
|---|---|---|
| `brief_version` | 1 | |
| `document` | `id`, `file_name`, `kind`, `configuration`, `description` (the profile's description property when set), `material`, `mass_kg`, `instances` | |
| `assembly` | `joints`: per pattern group `{joint_ids, kind, partners (file names), fastener, offset_mm}`; `contacts`; `interference_finding_ids` | 20 groups |
| `interfaces` | per subject `{subject, joint_id, tolerance: {source, cited} \| {unresolved: searched}, drawing: bound record id \| why none, callout}` | 20 subjects |
| `drawing` | `attached`: per drawing `{document_id, file_name, sheets, views_of_document, usable_views, unusable: [why], dimensions, toleranced, hole_callouts, gtols, datums, surface_finishes, notes: [text], tables: [{kind, title, rows}]}`; `candidates` | 10 notes of 200 characters, 5 tables of 10 rows, 10 candidates |
| `answers` | per answered request about the document or its components `{request_id, question or what, answer}` | 10 |
| `conformance` | per drawing `{document_id, differs: [setting names], skipped: [setting names]}` (from US7) | |
| `omitted` | per list, how many items were left out | |

Compact JSON of the whole at most 6,000 bytes. No persistent reference, no profile value.

## 7. Standards profile version 3 (`checks/standards/profile.py`)

```text
DrawingSection (strict, closed, every key required)
  sheet_formats: list[str]          # accepted ISheet.GetSheetFormatName values; empty skips
  drafting_standard: str            # compared with drafting_standard_name; empty skips
  projection: "first_angle" | "third_angle" | ""
  dimension_unit: "mm" | "in" | ""  # the unit general_tolerance's decimal places are counted in
  drawing_template: str             # recorded for feature 012; not compared
  bom_template: str                 # recorded for feature 012; not compared
```

`PROFILE_VERSION = 3`; `KNOWN_VERSIONS = (1, 2, 3)`; `drawing` required on version 3 and absent on 1
and 2; version 3 also requires everything version 2 requires. `general_tolerance` is not restated.

## 8. New check id and class

| Check id | Emitted by | Class | Why not `drawing.` |
|---|---|---|---|
| `drawing_profile.conformance` | `check_drawings` (US7) | `manufacturing` | the checklist item `drawing.manufacturing_inputs` closes on any `drawing.` finding (research R2.18) |

The coverage id `drawing.context` is a coverage item's `check`, never a finding's, and is not the
checklist item's id, so it closes nothing.
