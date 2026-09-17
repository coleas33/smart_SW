using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>One entity a mate references.</summary>
public sealed class MateEntityRef
{
    [JsonPropertyName("component_id")]
    public string ComponentId { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref")]
    public string? PersistRef { get; set; }

    /// <summary>swSelectType_e name of the mated entity, e.g. "FACE", "PLANE".</summary>
    [JsonPropertyName("entity_kind")]
    public string EntityKind { get; set; } = string.Empty;

    /// <summary>
    /// What IMateEntity2.Reference gave, with <b>no new interop call</b> (schema 1.4.0), and
    /// omitted when null the way every 1.4.0 addition is. Null only in a package written
    /// before 1.4.0: without it, a reference that was null and a read that threw are both a
    /// null <see cref="PersistRef"/> and indistinguishable.
    /// </summary>
    [JsonPropertyName("resolution_status")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public MateEntityResolution? ResolutionStatus { get; set; }
}

/// <summary>contracts/ir.schema.json #/$defs/Mate.</summary>
public sealed class Mate
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    /// <summary>swMateType_e name, e.g. "COINCIDENT", "CONCENTRIC".</summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;

    [JsonPropertyName("entities")]
    public List<MateEntityRef> Entities { get; set; } = new List<MateEntityRef>();

    [JsonPropertyName("alignment")]
    public MateAlignment Alignment { get; set; } = MateAlignment.Closest;

    [JsonPropertyName("suppressed")]
    public bool Suppressed { get; set; }

    [JsonPropertyName("distance")]
    public Quantity? Distance { get; set; }

    [JsonPropertyName("angle")]
    public Angle? Angle { get; set; }
}
