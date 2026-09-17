using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>contracts/ir.schema.json #/$defs/Capture. A saved PNG keyed by persist ref.</summary>
public sealed class Capture
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>The entity the view was zoomed to, or null for a whole-assembly view.</summary>
    [JsonPropertyName("persist_ref")]
    public string? PersistRef { get; set; }

    [JsonPropertyName("component_ids")]
    public List<string> ComponentIds { get; set; } = new List<string>();

    /// <summary>Package-relative path; must end in .png.</summary>
    [JsonPropertyName("file")]
    public string File { get; set; } = string.Empty;

    /// <summary>Named view: iso, front, top, right or fit.</summary>
    [JsonPropertyName("view")]
    public string View { get; set; } = string.Empty;

    [JsonPropertyName("note")]
    public string Note { get; set; } = string.Empty;
}

/// <summary>
/// contracts/ir.schema.json #/$defs/SheetView. A view region on a PDF-ingested drawing
/// sheet, in PDF points.
///
/// Named <c>SheetView</c> rather than <c>DrawingView</c> from schema 1.4.0 on: it matches the
/// Python model of the same shape, and it frees the name for
/// <see cref="Ir.DrawingView"/>, the natively dumped view, which is a different thing
/// entirely - that one carries dimensions, annotations and notes, and this one carries a
/// bounding box a PDF parser measured.
/// </summary>
public sealed class SheetView
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>[x0, y0, x1, y1].</summary>
    [JsonPropertyName("bbox")]
    public double[] Bbox { get; set; } = new double[4];
}

/// <summary>
/// contracts/ir.schema.json #/$defs/DrawingSheet. Produced by the Python PDF ingest or by
/// a native drawing dump. A sheet with no text layer is parse_status "no_text" plus a Gap.
/// </summary>
public sealed class DrawingSheet
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("sheet_name")]
    public string SheetName { get; set; } = string.Empty;

    /// <summary>1-based page number in the source PDF.</summary>
    [JsonPropertyName("page")]
    public int Page { get; set; } = 1;

    [JsonPropertyName("scale")]
    public string? Scale { get; set; }

    [JsonPropertyName("units")]
    public SheetUnits Units { get; set; } = SheetUnits.Unknown;

    [JsonPropertyName("general_notes")]
    public List<Note> GeneralNotes { get; set; } = new List<Note>();

    [JsonPropertyName("dimensions")]
    public List<Dimension> Dimensions { get; set; } = new List<Dimension>();

    [JsonPropertyName("views")]
    public List<SheetView> Views { get; set; } = new List<SheetView>();

    [JsonPropertyName("parse_status")]
    public ParseStatus ParseStatus { get; set; } = ParseStatus.Text;

    /// <summary>Name and version of the parser that produced this sheet.</summary>
    [JsonPropertyName("parser")]
    public string Parser { get; set; } = string.Empty;

    /// <summary>
    /// Which path wrote this sheet (schema 1.4.0); the PDF ingest stamps
    /// <see cref="DrawingEvidenceSource.PdfIngest"/>. Null in a sheet written before the
    /// stamp existed, which a consumer reads as "source not recorded" and the drawing checks
    /// treat exactly as <c>pdf_ingest</c>.
    ///
    /// The DTO carries it because <see cref="PackageSerializer"/> sets
    /// <c>UnmappedMemberHandling.Disallow</c> and three readers deserialize packages produced
    /// elsewhere - RunPackageIndex, PackageAppender and PackageReuse - so without this member
    /// an ingest-written package would throw in all three.
    /// </summary>
    [JsonPropertyName("source")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public DrawingEvidenceSource? Source { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/Gap. Anything that could not be extracted. Every gap
/// becomes an unresolved coverage item in the review (Principle I).
/// </summary>
public sealed class Gap
{
    [JsonPropertyName("kind")]
    public GapKind Kind { get; set; } = GapKind.NotExtracted;

    /// <summary>The IR entity type the gap is about, e.g. "hole", "component", "drawing".</summary>
    [JsonPropertyName("entity_kind")]
    public string EntityKind { get; set; } = string.Empty;

    [JsonPropertyName("entity_id")]
    public string? EntityId { get; set; }

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = string.Empty;

    /// <summary>The exception text when the gap came from a failed call, else null.</summary>
    [JsonPropertyName("error")]
    public string? Error { get; set; }
}
