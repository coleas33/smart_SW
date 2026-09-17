using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/CutListItem (schema 1.4.0, feature 006). One cut-list
/// item of one part document, written by the <c>cutlist</c> phase.
///
/// Identified structurally from the body-folder tree, never by matching a feature name: a
/// renamed item is not a waiver. The nullable members carry
/// <see cref="JsonIgnoreCondition.WhenWritingNull"/>, which overrides
/// <see cref="PackageSerializer"/>'s global "nulls are evidence" setting for exactly the
/// members contracts/ir-additions.md permits it for - each of them re-states its own absence
/// as a <see cref="Gap"/>, so omitting the null loses nothing a reader needs, and writing it
/// would move every package on disk.
/// </summary>
public sealed class CutListItem
{
    /// <summary>cut:NNNN, allocated in traversal order across the package.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>The configuration the body-folder tree was read in.</summary>
    [JsonPropertyName("configuration")]
    public string Configuration { get; set; } = string.Empty;

    /// <summary>IFeature.Name of the enclosing cut-list folder.</summary>
    [JsonPropertyName("folder_name")]
    public string FolderName { get; set; } = string.Empty;

    /// <summary>
    /// IFeature.GetTypeName2 of the enclosing folder, verbatim, so an unknown folder type is
    /// visible rather than silently dropped.
    /// </summary>
    [JsonPropertyName("folder_type_name")]
    public string FolderTypeName { get; set; } = string.Empty;

    /// <summary>IFeature.Name of the item itself.</summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// IBodyFolder.GetBodyCount(); null plus a cut_list_body_count gap. A folder whose count
    /// is 0 is not displayed by SOLIDWORKS and is not a subject of any check; it is still
    /// recorded so a coverage reason can say how many folders were seen and how many were
    /// displayable.
    /// </summary>
    [JsonPropertyName("body_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? BodyCount { get; set; }

    /// <summary>
    /// IFeature.ExcludeFromCutList(); null plus a cut_list_exclusion gap, and that item is
    /// then unresolved.
    /// </summary>
    [JsonPropertyName("excluded_from_cut_list")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? ExcludedFromCutList { get; set; }

    /// <summary>
    /// Base64 GetPersistReference3 bytes, or null when SOLIDWORKS gave none. A null is the
    /// statement FR-026 requires: <see cref="Id"/> is then a within-dump identity, so a
    /// consumer never presents it as a persistent one and the page shows no Show control.
    /// </summary>
    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    /// <summary>document_id whose IModelDocExtension produced <see cref="PersistRef"/>.</summary>
    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}
