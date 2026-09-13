using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/MassProperties. System units (kg, m, m^3) via
/// IModelDocExtension.CreateMassProperty2 with UseSystemUnits = true (research R12).
/// </summary>
public sealed class MassProperties
{
    [JsonPropertyName("mass_kg")]
    public double MassKg { get; set; }

    [JsonPropertyName("volume_m3")]
    public double VolumeM3 { get; set; }

    [JsonPropertyName("center_of_mass")]
    public Vec3 CenterOfMass { get; set; } = new Vec3();

    [JsonPropertyName("configuration")]
    public string Configuration { get; set; } = string.Empty;
}

/// <summary>contracts/ir.schema.json #/$defs/Document.</summary>
public sealed class Document
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("kind")]
    public DocumentKind Kind { get; set; } = DocumentKind.Part;

    [JsonPropertyName("file_name")]
    public string FileName { get; set; } = string.Empty;

    [JsonPropertyName("path")]
    public string Path { get; set; } = string.Empty;

    [JsonPropertyName("configurations")]
    public List<string> Configurations { get; set; } = new List<string>();

    [JsonPropertyName("active_configuration")]
    public string ActiveConfiguration { get; set; } = string.Empty;

    /// <summary>Document-level custom properties (ICustomPropertyManager.GetAll3).</summary>
    [JsonPropertyName("custom_properties")]
    public Dictionary<string, string> CustomProperties { get; set; } = new Dictionary<string, string>();

    /// <summary>Configuration name -> that configuration's custom properties.</summary>
    [JsonPropertyName("config_properties")]
    public Dictionary<string, Dictionary<string, string>> ConfigProperties { get; set; } =
        new Dictionary<string, Dictionary<string, string>>();

    /// <summary>Parts only; null when unknown (and then a Gap is recorded).</summary>
    [JsonPropertyName("material")]
    public string? Material { get; set; }

    /// <summary>Null for surface-only models; a Gap records why (research R12).</summary>
    [JsonPropertyName("mass")]
    public MassProperties? Mass { get; set; }
}
