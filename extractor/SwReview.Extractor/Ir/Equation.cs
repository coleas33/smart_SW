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

    /// <summary>
    /// Everything left of the FIRST '=', with quotes stripped and the whitespace trimmed:
    /// <c>"D1@Sketch1" = "Wall" * 2</c> becomes <c>D1@Sketch1</c>. It is evidence and a
    /// rule input, never an identity - <c>is_global</c> comes off the manager's own flag.
    ///
    /// A row with no '=' is its own left-hand side rather than an empty string: the manager
    /// also hands back rows that are not assignments, and dropping their text would hide
    /// what an engineer reading the finding needs to see.
    ///
    /// It lives here rather than in <c>EquationDumper</c> because the dumper is no longer the
    /// only reader: <c>remodel.snapshot</c> builds the same row from the copy's equation
    /// manager, and two spellings of "the left-hand side" would eventually disagree.
    /// </summary>
    public static string LhsOf(string text)
    {
        if (text == null)
        {
            throw new System.ArgumentNullException(nameof(text));
        }

        int split = text.IndexOf('=');
        string left = split < 0 ? text : text.Substring(0, split);
        return left.Replace("\"", string.Empty).Trim();
    }
}
