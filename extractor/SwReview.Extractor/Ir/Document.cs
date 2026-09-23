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

    // The four schema 1.4.0 additions below are optional, absent from the contract's
    // `required` set, and omitted when null. WhenWritingNull overrides PackageSerializer's
    // global "nulls are evidence" setting, which is safe exactly here: each of them
    // re-states its own absence as a Gap, so omitting the null loses nothing a reader needs
    // - and writing it would move every package on disk (contracts/ir-additions.md,
    // additivity rule point 3).

    /// <summary>
    /// IModelDoc2.IsExploded() for an assembly document (schema 1.4.0); null plus an
    /// assembly_exploded gap when unreadable. Always null for a part or a drawing, where the
    /// question does not apply and the absence is not a gap.
    /// </summary>
    [JsonPropertyName("is_exploded")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? IsExploded { get; set; }

    /// <summary>
    /// IModelDocExtension.GetWhatsWrongCount read <b>as the document stands</b> - nothing is
    /// rebuilt (schema 1.4.0); null plus a rebuild_error_count gap when unreadable.
    /// </summary>
    [JsonPropertyName("rebuild_error_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? RebuildErrorCount { get; set; }

    /// <summary>
    /// Whether the mass is overridden, read <b>before</b> the volume gates so a surface-only
    /// part still answers (schema 1.4.0). From feature 010 through the interface that has it:
    /// IModelDocExtension.CreateMassProperty()'s IMassProperty.OverrideMass, else
    /// IMassProperty2.GetOverrideOptions()'s OverrideMass; null plus one mass_override gap
    /// naming both paths when neither answers.
    /// </summary>
    [JsonPropertyName("mass_overridden")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? MassOverridden { get; set; }

    /// <summary>
    /// The configuration <see cref="Material"/> was read in (schema 1.4.0). Null for an
    /// assembly or a drawing, and present whenever the read was attempted - including when
    /// the material came back null, because "no material in configuration X" and "no
    /// material, configuration unknown" are different facts.
    /// </summary>
    [JsonPropertyName("material_configuration")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? MaterialConfiguration { get; set; }
}
