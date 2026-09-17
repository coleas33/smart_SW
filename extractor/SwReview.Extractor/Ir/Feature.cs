using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/SketchInfo (schema 1.1.0). What the extractor reads off
/// a feature's sketch.
///
/// <see cref="RawStatus"/> is <c>ISketch.GetConstrainedStatus</c> verbatim: the extractor
/// classifies nothing, so the name behind the number is Python's job against
/// <c>checks/rms_types.yaml</c>.
/// </summary>
public sealed class SketchInfo
{
    /// <summary>ISketch.GetConstrainedStatus verbatim; null plus a sketch_status gap.</summary>
    [JsonPropertyName("raw_status")]
    public int? RawStatus { get; set; }

    /// <summary>
    /// Feature ids that consume this sketch (GetChildren); null plus a feature_children gap
    /// when unavailable, empty when the sketch has no consumer.
    /// </summary>
    [JsonPropertyName("consumer_ids")]
    public List<string>? ConsumerIds { get; set; }

    /// <summary>
    /// len(ISketch.GetSketchTextSegments()), 0 for an empty or null array (schema 1.4.0);
    /// null plus a sketch_text gap when unreadable, which leaves the sketch unresolved
    /// because the text exemption can then neither be applied nor ruled out. Omitted when
    /// null, unlike the two members above, which keep theirs.
    /// </summary>
    [JsonPropertyName("text_segment_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? TextSegmentCount { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/FilletInfo (schema 1.1.0). The default radius of a
/// simple fillet feature.
/// </summary>
public sealed class FilletInfo
{
    /// <summary>
    /// ISimpleFilletFeatureData2.DefaultRadius in meters; null plus a fillet_radius gap when
    /// unreadable or when the fillet is variable, which has no single radius to report.
    /// </summary>
    [JsonPropertyName("default_radius")]
    public Quantity? DefaultRadius { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/Feature (schema 1.1.0). One node of a part document's
/// feature tree, in traversal order.
///
/// The extractor decides nothing about folders, end tags, groups or classes: those are
/// derived in Python from <see cref="TypeName"/> and <see cref="Name"/> against
/// <c>checks/rms_types.yaml</c>. <see cref="Depth"/> and <see cref="FolderId"/> come from
/// sub-feature structure alone (<see cref="Dump.FeatureTreeIndexer"/>), so in the flat
/// traversal shape every row is depth 0 with no folder.
/// </summary>
public sealed class Feature
{
    /// <summary>Package-stable id, pattern <c>feat:NNNN</c>; allocated across the package.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>Base64 of GetPersistReference3 bytes.</summary>
    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    /// <summary>document_id whose IModelDocExtension produced persist_ref; the owning part.</summary>
    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    /// <summary>The part document that owns the tree.</summary>
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>The configuration the tree was read in (the document's active one).</summary>
    [JsonPropertyName("configuration")]
    public string Configuration { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>GetTypeName2 verbatim; may be a name no table knows.</summary>
    [JsonPropertyName("type_name")]
    public string TypeName { get; set; } = string.Empty;

    /// <summary>IFeature.Description; null when unreadable (gap), "" when blank.</summary>
    [JsonPropertyName("description")]
    public string? Description { get; set; }

    /// <summary>Flat order within the document's tree, folders and their contents inline.</summary>
    [JsonPropertyName("index")]
    public int Index { get; set; }

    /// <summary>0 top level, 1 inside a folder; from sub-feature structure only.</summary>
    [JsonPropertyName("depth")]
    public int Depth { get; set; }

    /// <summary>Id of the nearest enclosing feature, or null at top level.</summary>
    [JsonPropertyName("folder_id")]
    public string? FolderId { get; set; }

    /// <summary>In <see cref="Configuration"/>; null when unreadable.</summary>
    [JsonPropertyName("suppressed")]
    public bool? Suppressed { get; set; }

    /// <summary>GetErrorCode2; null when unreadable.</summary>
    [JsonPropertyName("error_code")]
    public int? ErrorCode { get; set; }

    /// <summary>Dependents from GetChildren; null plus a feature_children gap.</summary>
    [JsonPropertyName("child_ids")]
    public List<string>? ChildIds { get; set; }

    /// <summary>Dependencies from GetParents; null plus a feature_parents gap.</summary>
    [JsonPropertyName("parent_ids")]
    public List<string>? ParentIds { get; set; }

    /// <summary>Present only for features GetSpecificFeature2 returns an ISketch for.</summary>
    [JsonPropertyName("sketch")]
    public SketchInfo? Sketch { get; set; }

    /// <summary>Present only for features whose definition is a simple fillet.</summary>
    [JsonPropertyName("fillet")]
    public FilletInfo? Fillet { get; set; }
}
