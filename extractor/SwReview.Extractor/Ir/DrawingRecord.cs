using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

// The eight models the `drawing` phase writes (schema 1.4.0, feature 006).
//
// These are new models, not an extension of DrawingSheet: that one is the Python PDF
// ingest's, and it requires page, parse_status and parser, none of which a natively dumped
// sheet has an honest value for (006 research R9). They live in their own
// EvidencePackage.drawing_records[] beside the untouched drawings[] for the same reason.
//
// Every record carries a package id allocated in traversal order, plus persist_ref and
// persist_ref_scope when SOLIDWORKS gave one. A null persist_ref is the statement FR-026
// requires: the id is a within-dump identity, so a consumer never presents it as a
// persistent one. Every nullable member carries WhenWritingNull, overriding
// PackageSerializer's global "nulls are evidence" setting exactly where
// contracts/ir-additions.md permits it.

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingRecord. One natively dumped drawing document,
/// keyed by its <see cref="DocumentId"/> - keyed rather than identified, because there is one
/// record per drawing document, so it carries neither a package id nor a persistent reference.
/// </summary>
public sealed class DrawingRecord
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>
    /// Constant <see cref="DrawingEvidenceSource.Native"/> for this model (FR-024); the
    /// contract pins it with a <c>const</c>, so the enum is the vocabulary and not a choice.
    /// </summary>
    [JsonPropertyName("source")]
    public DrawingEvidenceSource Source { get; set; } = DrawingEvidenceSource.Native;

    /// <summary>
    /// IDrawingDoc.GetCurrentSheet().GetName(), recorded read-only so the coverage reason can
    /// say which sheet was active while the others were read. <b>Nothing activates a sheet</b>
    /// (FR-044); ActivateSheet is on the read-only denylist.
    /// </summary>
    [JsonPropertyName("active_sheet_name")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ActiveSheetName { get; set; }

    /// <summary>
    /// GetSheetNames() order; empty plus a drawing_sheet gap when the enumeration failed.
    /// </summary>
    [JsonPropertyName("sheets")]
    public List<DrawingSheetRecord> Sheets { get; set; } = new List<DrawingSheetRecord>();
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingSheetRecord. One natively dumped sheet.
///
/// <see cref="WasActive"/> is load-bearing: nothing activates a sheet, so if only the active
/// sheet's contents come back, this is how a consumer knows which rows to trust.
/// </summary>
public sealed class DrawingSheetRecord
{
    /// <summary>dsh:NNNN.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>
    /// Constant <see cref="DrawingEvidenceSource.Native"/>: the per-sheet half of FR-024, so
    /// a sheet from either path says which produced it.
    /// </summary>
    [JsonPropertyName("source")]
    public DrawingEvidenceSource Source { get; set; } = DrawingEvidenceSource.Native;

    /// <summary>ISheet.GetName().</summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>Position in GetSheetNames(), from 0.</summary>
    [JsonPropertyName("index")]
    public int Index { get; set; }

    /// <summary>ISheet.GetSheetFormatName(); null plus a drawing_sheet gap.</summary>
    [JsonPropertyName("sheet_format_name")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? SheetFormatName { get; set; }

    /// <summary>Whether this sheet was the active one when it was read.</summary>
    [JsonPropertyName("was_active")]
    public bool WasActive { get; set; }

    /// <summary>
    /// ISheet.GetViews() order. Empty plus a drawing_sheet_views gap when the enumeration
    /// failed or came back empty on a non-active sheet.
    /// </summary>
    [JsonPropertyName("views")]
    public List<DrawingView> Views { get; set; } = new List<DrawingView>();

    /// <summary>
    /// Every revision table on the sheet, not just the one ISheet.RevisionTable returns: that
    /// property is single-valued, so a sheet carrying two tables would yield at most one
    /// record and the second would be silently invisible in the one check whose purpose is
    /// coverage.
    /// </summary>
    [JsonPropertyName("revision_tables")]
    public List<RevisionTable> RevisionTables { get; set; } = new List<RevisionTable>();

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingView. One view on one sheet, including the
/// sheet-format pseudo-view (<c>view_type_raw == 1</c>), which is where the notes live.
/// </summary>
public sealed class DrawingView
{
    /// <summary>dvw:NNNN.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("sheet_id")]
    public string SheetId { get; set; } = string.Empty;

    /// <summary>IView.GetName2(); null plus a drawing_view gap.</summary>
    [JsonPropertyName("name")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Name { get; set; }

    /// <summary>
    /// IView.Type verbatim, in swDrawingViewTypes_e; 1 is the sheet-format pseudo-view.
    /// Python names the number.
    /// </summary>
    [JsonPropertyName("view_type_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? ViewTypeRaw { get; set; }

    /// <summary>
    /// IView.ReferencedDocument resolved to a Document in this package; null when the view
    /// references nothing, or when the referenced model is not loaded - a
    /// drawing_referenced_document gap names the second case.
    /// </summary>
    [JsonPropertyName("referenced_document_id")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ReferencedDocumentId { get; set; }

    /// <summary>
    /// IView.GetReferencedModelName(), recorded even when
    /// <see cref="ReferencedDocumentId"/> is null, because it is what lets the gap name the
    /// model that was not loaded (FR-025).
    /// </summary>
    [JsonPropertyName("referenced_model_path")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ReferencedModelPath { get; set; }

    [JsonPropertyName("display_dimensions")]
    public List<DisplayDimensionRecord> DisplayDimensions { get; set; } =
        new List<DisplayDimensionRecord>();

    [JsonPropertyName("annotations")]
    public List<DrawingAnnotation> Annotations { get; set; } = new List<DrawingAnnotation>();

    [JsonPropertyName("notes")]
    public List<DrawingNote> Notes { get; set; } = new List<DrawingNote>();

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DisplayDimensionRecord. One display dimension on a view.
///
/// Both value members are the <c>Quantity | Angle</c> union <see cref="Measure"/> already
/// carries for Tolerance.upper/lower: <see cref="Quantity"/> holds a
/// <see cref="LengthUnit"/> only, so an angular dimension cannot be represented by one, and
/// <see cref="DimensionTypeRaw"/> is what decides which of the two a record carries.
/// </summary>
public sealed class DisplayDimensionRecord
{
    /// <summary>ddm:NNNN.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("view_id")]
    public string ViewId { get; set; } = string.Empty;

    /// <summary>
    /// IDimension.FullName, falling back to Name; null plus a dimension_override gap.
    /// </summary>
    [JsonPropertyName("name")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Name { get; set; }

    /// <summary>
    /// IDisplayDimension.Type2 verbatim: what decides whether the value is a length or an
    /// angle, and therefore its unit. Python names it.
    /// </summary>
    [JsonPropertyName("dimension_type_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? DimensionTypeRaw { get; set; }

    /// <summary>
    /// IDisplayDimension.GetOverride(); null plus a dimension_override gap, and the dimension
    /// is then unresolved.
    /// </summary>
    [JsonPropertyName("is_overridden")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? IsOverridden { get; set; }

    /// <summary>
    /// IDisplayDimension.GetOverrideValue() in the unit <see cref="DimensionTypeRaw"/>
    /// implies; null plus a dimension_unit gap when the unit could not be determined even
    /// though a number was read, because a number with a guessed unit is worse than no number.
    /// </summary>
    [JsonPropertyName("override_value")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Measure? OverrideValue { get; set; }

    /// <summary>
    /// IDimension.GetSystemValue3(1, null), the computed value, for the finding's observed
    /// text; same union and same null rule.
    /// </summary>
    [JsonPropertyName("value")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Measure? Value { get; set; }

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingAnnotation. One annotation of any type on a view;
/// every annotation type is in scope for the dangling check.
/// </summary>
public sealed class DrawingAnnotation
{
    /// <summary>dan:NNNN.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>
    /// The <see cref="DrawingView.Id"/> it was read from; a sheet-format annotation's owner
    /// is the type-1 pseudo-view.
    /// </summary>
    [JsonPropertyName("owner_id")]
    public string OwnerId { get; set; } = string.Empty;

    /// <summary>
    /// IAnnotation.GetName(); null plus an annotation_identity gap. The annotation is still a
    /// subject, identified by <see cref="Id"/>, its sheet and its view.
    /// </summary>
    [JsonPropertyName("name")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Name { get; set; }

    /// <summary>IAnnotation.GetType() verbatim, in swAnnotationType_e; Python names it.</summary>
    [JsonPropertyName("type_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? TypeRaw { get; set; }

    /// <summary>
    /// IAnnotation.IsDangling(); null plus an annotation_dangling gap, and that annotation is
    /// then unresolved.
    /// </summary>
    [JsonPropertyName("is_dangling")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? IsDangling { get; set; }

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingNote. One note read off a view. Notes are
/// reachable only through a view, and the export-control statement lives on the sheet-format
/// pseudo-view.
/// </summary>
public sealed class DrawingNote
{
    /// <summary>dnt:NNNN.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>The <see cref="DrawingView.Id"/> it was read from.</summary>
    [JsonPropertyName("owner_id")]
    public string OwnerId { get; set; } = string.Empty;

    /// <summary>
    /// INote.GetText(); null plus a note_text gap, which leaves the export-control check
    /// unresolved because an unread note cannot be shown not to carry the phrase.
    /// </summary>
    [JsonPropertyName("text")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Text { get; set; }

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/RevisionTable. One revision table on one sheet.
/// </summary>
public sealed class RevisionTable
{
    /// <summary>drv:NNNN.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("sheet_id")]
    public string SheetId { get; set; } = string.Empty;

    /// <summary>
    /// IRevisionTableAnnotation.CurrentRevision verbatim, <b>including the empty string</b>.
    /// Recorded alongside the rows because it comes back empty under some vaults; the check
    /// names both readings with their source rather than letting the dumper choose.
    /// </summary>
    [JsonPropertyName("current_revision_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? CurrentRevisionRaw { get; set; }

    /// <summary>ITableAnnotation.RowCount; null plus a revision_table_read gap.</summary>
    [JsonPropertyName("row_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? RowCount { get; set; }

    /// <summary>ITableAnnotation.ColumnCount; null plus a revision_table_read gap.</summary>
    [JsonPropertyName("column_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? ColumnCount { get; set; }

    /// <summary>Empty when the COM cast failed; the gap says so.</summary>
    [JsonPropertyName("rows")]
    public List<RevisionTableRow> Rows { get; set; } = new List<RevisionTableRow>();

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/RevisionTableRow. One row, keyed by its index inside that
/// table. Which row is the revision row, and whether a row is the header, are profile
/// questions answered in Python; the extractor records cells and classifies nothing.
/// </summary>
public sealed class RevisionTableRow
{
    /// <summary>Position in the table, from 0.</summary>
    [JsonPropertyName("index")]
    public int Index { get; set; }

    /// <summary>
    /// One per column, from ITableAnnotation.Text[row, col]. An empty cell is the empty
    /// string - a null cell is one that could not be read, and the two must not be confused:
    /// an empty revision cell is a real mismatch.
    /// </summary>
    [JsonPropertyName("cells")]
    public List<string?> Cells { get; set; } = new List<string?>();

    /// <summary>
    /// Only the extractor's reading of the table's own title-row structure (TotalRowCount
    /// versus RowCount); may be null, and no check relies on it alone.
    /// </summary>
    [JsonPropertyName("is_header")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? IsHeader { get; set; }
}
