using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/Fastener. Identity comes from Toolbox configuration
/// properties or a name parse; unparseable fields stay null rather than being guessed
/// (research R12, Toolbox identity).
/// </summary>
public sealed class Fastener
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    [JsonPropertyName("component_id")]
    public string ComponentId { get; set; } = string.Empty;

    [JsonPropertyName("kind")]
    public FastenerKind Kind { get; set; } = FastenerKind.Other;

    [JsonPropertyName("identity_source")]
    public IdentitySource IdentitySource { get; set; } = IdentitySource.NameParse;

    /// <summary>e.g. "M6x1.0".</summary>
    [JsonPropertyName("thread_designation")]
    public string? ThreadDesignation { get; set; }

    /// <summary>Under-head length for screws.</summary>
    [JsonPropertyName("length")]
    public Quantity? Length { get; set; }

    /// <summary>e.g. "socket head cap".</summary>
    [JsonPropertyName("head_type")]
    public string? HeadType { get; set; }

    [JsonPropertyName("head_diameter")]
    public Quantity? HeadDiameter { get; set; }

    [JsonPropertyName("head_height")]
    public Quantity? HeadHeight { get; set; }

    [JsonPropertyName("drive")]
    public string? Drive { get; set; }

    /// <summary>Assembly frame, pointing from the head toward the tip.</summary>
    [JsonPropertyName("axis")]
    public Axis Axis { get; set; } = new Axis();

    [JsonPropertyName("material")]
    public string? Material { get; set; }
}
