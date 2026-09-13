using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/Hole. Hole Wizard data read from
/// IWizardHoleFeatureData2 scalars (research R12).
/// </summary>
public sealed class Hole
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    /// <summary>The component instance that owns the feature.</summary>
    [JsonPropertyName("component_id")]
    public string ComponentId { get; set; } = string.Empty;

    [JsonPropertyName("feature_name")]
    public string FeatureName { get; set; } = string.Empty;

    [JsonPropertyName("hole_type")]
    public HoleType HoleType { get; set; } = HoleType.Unknown;

    /// <summary>e.g. "ISO", "ANSI Metric". Null when no standard could be read.</summary>
    [JsonPropertyName("standard")]
    public string? Standard { get; set; }

    /// <summary>e.g. "M6".</summary>
    [JsonPropertyName("size")]
    public string? Size { get; set; }

    /// <summary>e.g. "M6x1.0".</summary>
    [JsonPropertyName("thread_designation")]
    public string? ThreadDesignation { get; set; }

    /// <summary>
    /// Usable thread depth. Null means unknown and MUST stay unknown: it is never derived
    /// from <see cref="HoleDepth"/> (Principle I, FR-008).
    /// </summary>
    [JsonPropertyName("thread_depth")]
    public Quantity? ThreadDepth { get; set; }

    /// <summary>Drill depth.</summary>
    [JsonPropertyName("hole_depth")]
    public Quantity? HoleDepth { get; set; }

    [JsonPropertyName("end_condition")]
    public EndCondition EndCondition { get; set; } = EndCondition.Unknown;

    /// <summary>Nominal hole diameter.</summary>
    [JsonPropertyName("diameter")]
    public Quantity? Diameter { get; set; }

    /// <summary>Assembly frame; from CylinderParams of the cylindrical face, never GetBox.</summary>
    [JsonPropertyName("axis")]
    public Axis Axis { get; set; } = new Axis();

    /// <summary>Ids of the cylindrical faces belonging to this hole.</summary>
    [JsonPropertyName("face_ids")]
    public List<string> FaceIds { get; set; } = new List<string>();
}

/// <summary>contracts/ir.schema.json #/$defs/CosmeticThread.</summary>
public sealed class CosmeticThread
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    [JsonPropertyName("component_id")]
    public string ComponentId { get; set; } = string.Empty;

    [JsonPropertyName("face_id")]
    public string FaceId { get; set; } = string.Empty;

    /// <summary>ICosmeticThreadFeatureData.ThreadCallout, e.g. "M6x1.0".</summary>
    [JsonPropertyName("designation")]
    public string Designation { get; set; } = string.Empty;

    [JsonPropertyName("depth")]
    public Quantity? Depth { get; set; }

    [JsonPropertyName("is_external")]
    public bool IsExternal { get; set; }
}
