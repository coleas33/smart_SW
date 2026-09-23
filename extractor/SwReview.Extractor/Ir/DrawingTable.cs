using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

// The four models schema 1.6.0 adds for the drawing context (feature 011,
// specs/011-drawing-context/data-model.md section 2). Every list is null rather than empty
// when it has no rows and carries WhenWritingNull, so it is omitted exactly as the Python
// models omit it; OmitEmptyAdditiveArrays turns an empty list a writer assigned into null on
// the way into PackageSerializer.Serialize.

/// <summary>
/// contracts/ir.schema.json #/$defs/AttachedFace. One model face a drawing dimension or
/// annotation is attached to: read through IAnnotation.GetAttachedEntities3 and
/// IView.GetCorrespondingEntity, an edge recorded as its two adjacent faces.
/// </summary>
public sealed class AttachedFace
{
    /// <summary>The model face's persistent reference, from its owning part document.</summary>
    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    /// <summary>The document_id of that part document.</summary>
    [JsonPropertyName("scope")]
    public string Scope { get; set; } = string.Empty;

    /// <summary>
    /// <see cref="AttachedVia.Edge"/>: the annotation was attached to an edge and this is one
    /// of its two adjacent faces.
    /// </summary>
    [JsonPropertyName("via")]
    public AttachedVia Via { get; set; } = AttachedVia.Face;
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingTable. One table on a sheet that is not a revision
/// table - a bill of materials, a hole table, a general tolerance table, a title block or a
/// general table - cell by cell. Revision tables stay in
/// <see cref="DrawingSheetRecord.RevisionTables"/> exactly as feature 006 records them.
/// </summary>
public sealed class DrawingTable
{
    /// <summary>dtb:NNNN, allocated from the package's scope.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("sheet_id")]
    public string SheetId { get; set; } = string.Empty;

    /// <summary>The <see cref="DrawingView.Id"/> whose GetTableAnnotations returned it.</summary>
    [JsonPropertyName("owner_view_id")]
    public string OwnerViewId { get; set; } = string.Empty;

    /// <summary>ITableAnnotation.Type verbatim, in swTableAnnotationType_e; never 3 here.</summary>
    [JsonPropertyName("table_type_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? TableTypeRaw { get; set; }

    /// <summary>ITableAnnotation.Title; null plus a drawing_table_read gap.</summary>
    [JsonPropertyName("title")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Title { get; set; }

    [JsonPropertyName("row_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? RowCount { get; set; }

    [JsonPropertyName("column_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? ColumnCount { get; set; }

    /// <summary>
    /// Feature 006's row model, reused: a null cell is unread, an empty one is empty. Written
    /// always, as <see cref="RevisionTable.Rows"/> is.
    /// </summary>
    [JsonPropertyName("rows")]
    public List<RevisionTableRow> Rows { get; set; } = new List<RevisionTableRow>();

    /// <summary>For a bill of materials only; null and omitted otherwise.</summary>
    [JsonPropertyName("bom_rows")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<BomRow>? BomRows { get; set; }

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }

    /// <summary>Nulls the empty 1.6.0 lists below this table, so they are omitted.</summary>
    internal void OmitEmptyAdditiveArrays()
    {
        BomRows = AdditiveArrays.NullIfEmpty(BomRows);
        if (BomRows == null)
        {
            return;
        }

        foreach (BomRow row in BomRows)
        {
            row.OmitEmptyAdditiveArrays();
        }
    }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/BomRow. The documents one bill-of-materials row stands for,
/// from IBomTableAnnotation.GetModelPathNames.
/// </summary>
public sealed class BomRow
{
    /// <summary>The table row.</summary>
    [JsonPropertyName("index")]
    public int Index { get; set; }

    /// <summary>The paths that are package documents, as their document ids.</summary>
    [JsonPropertyName("document_ids")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<string>? DocumentIds { get; set; }

    /// <summary>The paths that are not, recorded verbatim.</summary>
    [JsonPropertyName("unresolved_paths")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<string>? UnresolvedPaths { get; set; }

    internal void OmitEmptyAdditiveArrays()
    {
        DocumentIds = AdditiveArrays.NullIfEmpty(DocumentIds);
        UnresolvedPaths = AdditiveArrays.NullIfEmpty(UnresolvedPaths);
    }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingCandidate. A drawing file of the same name beside a
/// reviewed part or assembly document, not open, and never opened by the extraction
/// (011 contracts/open-drawings.md section 5).
/// </summary>
public sealed class DrawingCandidate
{
    /// <summary>The reviewed part or assembly document.</summary>
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>The drawing file beside it: same folder, same stem, .SLDDRW.</summary>
    [JsonPropertyName("path")]
    public string Path { get; set; } = string.Empty;

    /// <summary>The only rule.</summary>
    [JsonPropertyName("reason")]
    public DrawingCandidateReason Reason { get; set; } = DrawingCandidateReason.SameNameBesideModel;
}

/// <summary>
/// The one rule every schema 1.4.0 and later additive list follows on the way out: a list with
/// no rows is written as no member, never as <c>[]</c>, because <c>WhenWritingNull</c> omits a
/// null list only.
/// </summary>
internal static class AdditiveArrays
{
    public static List<T>? NullIfEmpty<T>(List<T>? list) => list == null || list.Count == 0 ? null : list;
}
