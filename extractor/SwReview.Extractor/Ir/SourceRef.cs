using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/SourceRef. Where a value came from. At least one
/// locator (sheet, annotation, persist_ref or page) must be set.
/// </summary>
public sealed class SourceRef
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("sheet")]
    public string? Sheet { get; set; }

    [JsonPropertyName("view")]
    public string? View { get; set; }

    [JsonPropertyName("annotation")]
    public string? Annotation { get; set; }

    /// <summary>Base64 of IModelDocExtension.GetPersistReference3 bytes, or null.</summary>
    [JsonPropertyName("persist_ref")]
    public string? PersistRef { get; set; }

    [JsonPropertyName("page")]
    public int? Page { get; set; }

    /// <summary>[x0, y0, x1, y1] in PDF points, or null.</summary>
    [JsonPropertyName("bbox")]
    public double[]? Bbox { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/Tolerance. Kind "none" means no tolerance was found;
/// it is never treated as zero.
/// </summary>
public sealed class Tolerance
{
    [JsonPropertyName("kind")]
    public ToleranceKind Kind { get; set; } = ToleranceKind.None;

    [JsonPropertyName("upper")]
    public Measure? Upper { get; set; }

    [JsonPropertyName("lower")]
    public Measure? Lower { get; set; }

    [JsonPropertyName("source")]
    public SourceRef Source { get; set; } = new SourceRef();
}

/// <summary>contracts/ir.schema.json #/$defs/Dimension.</summary>
public sealed class Dimension
{
    /// <summary>A length or an angle; see <see cref="Measure"/>.</summary>
    [JsonPropertyName("nominal")]
    public Measure Nominal { get; set; } = new Measure();

    [JsonPropertyName("tolerance")]
    public Tolerance Tolerance { get; set; } = new Tolerance();

    [JsonPropertyName("source")]
    public SourceRef Source { get; set; } = new SourceRef();

    /// <summary>The raw drawing text, kept verbatim even when the grammar failed.</summary>
    [JsonPropertyName("text_as_read")]
    public string TextAsRead { get; set; } = string.Empty;
}

/// <summary>contracts/ir.schema.json #/$defs/Note. A general note on a drawing sheet.</summary>
public sealed class Note
{
    [JsonPropertyName("text")]
    public string Text { get; set; } = string.Empty;

    [JsonPropertyName("source")]
    public SourceRef Source { get; set; } = new SourceRef();

    [JsonPropertyName("kind")]
    public NoteKind Kind { get; set; } = NoteKind.Other;
}
