using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/ComponentInstance. One instance in the assembly tree;
/// the tree is rebuilt from <see cref="ParentId"/>.
/// </summary>
public sealed class ComponentInstance
{
    /// <summary>Package-stable id, pattern <c>cmp:NNNN</c> (at least four digits).</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>Base64 of GetPersistReference3 bytes. Never compared byte-wise (research R12).</summary>
    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    /// <summary>document_id whose IModelDocExtension produced persist_ref; resolve against it.</summary>
    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    /// <summary>Component name including instance suffix, e.g. "bracket-3".</summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>IComponent2.Name2 full instance path, e.g. "sub-2/bracket-3"; unique in the assembly.</summary>
    [JsonPropertyName("full_path")]
    public string FullPath { get; set; } = string.Empty;

    /// <summary>The part or assembly document this instance references.</summary>
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>Null for the root component.</summary>
    [JsonPropertyName("parent_id")]
    public string? ParentId { get; set; }

    [JsonPropertyName("referenced_configuration")]
    public string ReferencedConfiguration { get; set; } = string.Empty;

    /// <summary>Row-major 4x4 relative to the root assembly, translation in meters.</summary>
    [JsonPropertyName("transform")]
    public double[][] Transform { get; set; } = Ir.Transform.Identity();

    /// <summary>Anything other than Resolved leaves dependent checks unresolved.</summary>
    [JsonPropertyName("suppression")]
    public SuppressionState Suppression { get; set; } = SuppressionState.Resolved;

    [JsonPropertyName("is_fixed")]
    public bool IsFixed { get; set; }

    /// <summary>Set when the instance belongs to a component pattern; used for grouping (FR-011).</summary>
    [JsonPropertyName("pattern_id")]
    public string? PatternId { get; set; }

    /// <summary>IModelDocExtension.ToolboxPartType != 0.</summary>
    [JsonPropertyName("is_toolbox")]
    public bool IsToolbox { get; set; }
}
