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

    /// <summary>
    /// IComponent2.GetConstrainedStatus verbatim (swConstrainedStatus_e); null plus a
    /// component_constrained_status gap when unreadable. Named in Python, not here.
    /// </summary>
    [JsonPropertyName("constrained_status_raw")]
    public int? ConstrainedStatusRaw { get; set; }

    // The four schema 1.4.0 additions below are omitted when null, unlike
    // ConstrainedStatusRaw above and every earlier member, which keep their nulls: dropping
    // those would change the shape feature 001's readers were written against
    // (contracts/ir-additions.md, additivity rule point 3).

    /// <summary>
    /// Slot 7 of IComponent2.GetMaterialPropertyValues2(1, null) verbatim (schema 1.4.0);
    /// null plus a component_transparency gap when unreadable, and null <b>without</b> a gap
    /// when <see cref="HasAppearanceOverride"/> is false - there is nothing to read.
    /// </summary>
    [JsonPropertyName("transparency_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public double? TransparencyRaw { get; set; }

    /// <summary>
    /// IComponent2.HasMaterialPropertyValues() (schema 1.4.0); null plus a
    /// component_transparency gap when unreadable. Replaces the macro's -1 sentinel, which
    /// conflated "no override" with a real value.
    /// </summary>
    [JsonPropertyName("has_appearance_override")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? HasAppearanceOverride { get; set; }

    /// <summary>
    /// IComponent2.Visible verbatim, in swComponentVisibilityState_e - hidden 0, visible 1,
    /// unknown -1 (schema 1.4.0); null plus a component_visibility gap when unreadable. The
    /// extractor records the number; Python names it.
    /// </summary>
    [JsonPropertyName("visibility_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? VisibilityRaw { get; set; }

    /// <summary>
    /// IComponent2.IsPatternInstance() (schema 1.4.0); null plus a component_pattern gap when
    /// unreadable. <see cref="PatternId"/> keeps the pattern's name and cannot replace this: a
    /// null PatternId conflates "not in a pattern" with "the pattern map was never built".
    /// </summary>
    [JsonPropertyName("is_pattern_instance")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? IsPatternInstance { get; set; }
}
