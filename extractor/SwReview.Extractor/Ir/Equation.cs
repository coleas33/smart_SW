using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/Equation (schema 1.1.0). One row of a document's
/// equation manager.
/// </summary>
public sealed class Equation
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>Position in the equation manager.</summary>
    [JsonPropertyName("index")]
    public int Index { get; set; }

    /// <summary>Full equation text as read.</summary>
    [JsonPropertyName("text")]
    public string Text { get; set; } = string.Empty;

    /// <summary>Left of the first '=', quotes stripped; evidence only.</summary>
    [JsonPropertyName("lhs")]
    public string Lhs { get; set; } = string.Empty;

    /// <summary>IEquationMgr.GlobalVariable(i); null plus an equations gap when unreadable.</summary>
    [JsonPropertyName("is_global")]
    public bool? IsGlobal { get; set; }

    /// <summary>Value(i); null when unreadable.</summary>
    [JsonPropertyName("value")]
    public double? Value { get; set; }
}
