using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// The IInterferenceDetectionMgr settings the run used, echoed into the IR so a finding
/// can state what was and was not treated as an interference.
/// </summary>
public sealed class InterferenceSettings
{
    [JsonPropertyName("treat_coincident_as_interference")]
    public bool TreatCoincidentAsInterference { get; set; }

    [JsonPropertyName("treat_subassemblies_as_components")]
    public bool TreatSubassembliesAsComponents { get; set; }

    [JsonPropertyName("include_multibody")]
    public bool IncludeMultibody { get; set; }

    [JsonPropertyName("ignore_hidden")]
    public bool IgnoreHidden { get; set; }

    [JsonPropertyName("fastener_folder_treatment")]
    public FastenerFolderTreatment FastenerFolderTreatment { get; set; } = FastenerFolderTreatment.Include;
}

/// <summary>
/// contracts/ir.schema.json #/$defs/Interference. One detected pair.
/// <see cref="Volume"/> stays null until the extractor has verified the unit of
/// IInterference.Volume on the workstation against a known overlap (research R12, T069).
/// </summary>
public sealed class Interference
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("configuration")]
    public string Configuration { get; set; } = string.Empty;

    /// <summary>Exactly two component ids.</summary>
    [JsonPropertyName("component_ids")]
    public List<string> ComponentIds { get; set; } = new List<string>();

    [JsonPropertyName("volume")]
    public Volume? Volume { get; set; }

    [JsonPropertyName("settings")]
    public InterferenceSettings Settings { get; set; } = new InterferenceSettings();

    /// <summary>IInterference.IsFastener: SOLIDWORKS placed the pair in the fasteners folder.</summary>
    [JsonPropertyName("is_fastener")]
    public bool IsFastener { get; set; }

    /// <summary>IInterference.IsPossibleInterference: coincident or touching, not overlapping.</summary>
    [JsonPropertyName("is_possible")]
    public bool IsPossible { get; set; }

    /// <summary>Truncated and failed pairs become unresolved coverage, never silent passes.</summary>
    [JsonPropertyName("status")]
    public InterferenceStatus Status { get; set; } = InterferenceStatus.Computed;

    [JsonPropertyName("error")]
    public string? Error { get; set; }

    /// <summary>Derived from the pattern ids of the pair; equal keys group into one finding.</summary>
    [JsonPropertyName("group_key")]
    public string GroupKey { get; set; } = string.Empty;
}
