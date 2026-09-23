using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

// The tolerance evidence (schema 1.5.0, feature 010 US8): what a Hole Wizard feature says
// beyond its size and depths, the part documents' feature dimensions with their tolerances,
// and their geometric tolerances and datum tags (specs/010-mechanical-checks/data-model.md
// section 10, contracts/tolerances.md sections 1 and 2).
//
// Every value is recorded verbatim in the units SOLIDWORKS reports - metres and radians - and
// nothing is derived. Every nullable member carries WhenWritingNull, overriding
// PackageSerializer's global "nulls are evidence" setting exactly where the additivity rule
// permits it: a read that failed re-states its absence as a Gap, so the omitted null loses
// nothing a reader needs, and a package carrying none of this evidence serializes exactly as
// a 1.4.0 build wrote it. A list on these records is written even when empty, as the 1.4.0
// drawing records' lists are; the Python models, which omit it, read the empty list back.

/// <summary>
/// contracts/ir.schema.json #/$defs/HoleWizardData. <c>Hole.wizard</c>: the fit and thread
/// classes and the drill, counterbore and countersink sizes of one Hole Wizard feature, read
/// from <c>IWizardHoleFeatureData2</c> (FR-021). A read that failed is null plus a
/// <c>hole_wizard</c> gap naming the field; a zero or a blank (the field does not apply to
/// this hole type) is null with no gap.
/// </summary>
public sealed class HoleWizardData
{
    /// <summary>
    /// <c>HoleFit</c> as the name of its <c>swWzdHoleScrewClearanceTypes_e</c> member
    /// (<c>swScrewClearanceClose</c>, <c>...Normal</c>, <c>...Loose</c>), or the integer's
    /// text for a value the enumeration does not name. A screw clearance fit, never an ISO 286
    /// class; read for counterbore and countersink holes only, the types the API documents it
    /// for (reflected on the 2024 SP5 interop: the property is an <c>int</c>).
    /// </summary>
    [JsonPropertyName("fit_class_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FitClassRaw { get; set; }

    /// <summary><c>ThreadClass</c> verbatim (1B, 2B, 3B); a tapped hole only.</summary>
    [JsonPropertyName("thread_class_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ThreadClassRaw { get; set; }

    [JsonPropertyName("thru_hole_diameter")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Quantity? ThruHoleDiameter { get; set; }

    [JsonPropertyName("tap_drill_diameter")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Quantity? TapDrillDiameter { get; set; }

    [JsonPropertyName("counterbore_diameter")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Quantity? CounterboreDiameter { get; set; }

    [JsonPropertyName("counterbore_depth")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Quantity? CounterboreDepth { get; set; }

    [JsonPropertyName("countersink_diameter")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Quantity? CountersinkDiameter { get; set; }

    /// <summary><c>CounterSinkAngle</c>, radians: the API's system unit, not converted.</summary>
    [JsonPropertyName("countersink_angle")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Angle? CountersinkAngle { get; set; }

    [JsonPropertyName("head_clearance")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Quantity? HeadClearance { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/ModelDimension. One dimension of a part document's
/// features and its tolerance, written by the <c>tolerance</c> phase (FR-022). Every
/// dimension is recorded, toleranced or not: a tolerance binds to a hole only through the
/// unique dimension of its value in the document (research R2.18).
/// </summary>
public sealed class ModelDimension
{
    /// <summary>mdm:NNNN, allocated in traversal order across the package.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>IFeature.Name of the feature that owns the display dimension.</summary>
    [JsonPropertyName("feature_name")]
    public string FeatureName { get; set; } = string.Empty;

    /// <summary>IDimension.FullName, e.g. <c>D1@Sketch1@part.SLDPRT</c>.</summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>Named from <see cref="DimensionTypeRaw"/>; see ToleranceDumper.DimensionTypeOf.</summary>
    [JsonPropertyName("dimension_type")]
    public ModelDimensionType DimensionType { get; set; } = ModelDimensionType.Other;

    /// <summary>IDisplayDimension.Type2 verbatim (swDimensionType_e).</summary>
    [JsonPropertyName("dimension_type_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? DimensionTypeRaw { get; set; }

    /// <summary>IDimension.GetSystemValue3 in this configuration: metres or radians.</summary>
    [JsonPropertyName("nominal")]
    public Measure Nominal { get; set; } = new Measure();

    /// <summary>
    /// IDimensionTolerance read into the IR's tolerance, the limits being the signed deviations
    /// GetMinValue2/GetMaxValue2 report. Null when the type has no IR kind (MIN, MAX, FIT,
    /// BLOCK, GENERAL) or the read failed; null is never kind "none".
    /// </summary>
    [JsonPropertyName("tolerance")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Tolerance? Tolerance { get; set; }

    /// <summary>IDimensionTolerance.Type verbatim (swTolType_e).</summary>
    [JsonPropertyName("tolerance_type_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? ToleranceTypeRaw { get; set; }

    /// <summary>IDimensionTolerance.GetHoleFitValue verbatim (e.g. H7), for a fit type.</summary>
    [JsonPropertyName("fit_hole_class")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FitHoleClass { get; set; }

    /// <summary>IDimensionTolerance.GetShaftFitValue verbatim (e.g. g6), for a fit type.</summary>
    [JsonPropertyName("fit_shaft_class")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FitShaftClass { get; set; }

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/GtolFrame. One frame of a geometric tolerance. A GTol
/// created before SOLIDWORKS 2022 answers <c>GetFrameSymbols3</c> and <c>GetFrameValues</c>;
/// one in the 2022 format answers <c>IGtol.GetFrame(n).GetSymbolXml()</c>. Both are asked
/// and whichever answered is recorded verbatim (reflected and documented on 2024 SP5).
/// </summary>
public sealed class GtolFrame
{
    /// <summary>The one-based frame number the calls were asked for.</summary>
    [JsonPropertyName("number")]
    public int Number { get; set; } = 1;

    /// <summary>
    /// IGtol.GetFrameSymbols3 verbatim: the characteristic symbol, then the material
    /// condition symbols of tolerance 1, tolerance 2 and datums 1 to 3.
    /// </summary>
    [JsonPropertyName("symbols_raw")]
    public List<string> SymbolsRaw { get; set; } = new List<string>();

    /// <summary>IGtol.GetFrameValues verbatim: tolerance 1, tolerance 2, datums 1 to 3.</summary>
    [JsonPropertyName("values_raw")]
    public List<string> ValuesRaw { get; set; } = new List<string>();

    /// <summary>IGtolFrame.GetSymbolXml verbatim, for a GTol in the 2022 format.</summary>
    [JsonPropertyName("symbol_xml_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? SymbolXmlRaw { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/ModelAnnotation. One geometric tolerance or datum tag of
/// a part document, DimXpert or MBD, written by the <c>tolerance</c> phase (FR-022). It binds
/// to a hole only through <see cref="AttachedPersistRefs"/> (research R2.18).
/// </summary>
public sealed class ModelAnnotation
{
    /// <summary>man:NNNN, allocated in traversal order across the package.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("kind")]
    public ModelAnnotationKind Kind { get; set; } = ModelAnnotationKind.Gtol;

    /// <summary>A GTol's frames, 1 to IGtol.GetFrameCount(); empty for a datum tag.</summary>
    [JsonPropertyName("frames")]
    public List<GtolFrame> Frames { get; set; } = new List<GtolFrame>();

    /// <summary>IGtol.GetDatumIdentifier verbatim, when not blank.</summary>
    [JsonPropertyName("datum_identifier_raw")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? DatumIdentifierRaw { get; set; }

    /// <summary>IDatumTag.GetLabel, for a datum tag.</summary>
    [JsonPropertyName("label")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Label { get; set; }

    /// <summary>IAnnotation.IsDimXpert(); null plus a model_annotation gap when unreadable.</summary>
    [JsonPropertyName("is_dimxpert")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public bool? IsDimXpert { get; set; }

    /// <summary>
    /// The persistent references of the faces IAnnotation.GetAttachedEntities3 returns; an
    /// edge, a vertex or a dangling attachment carries no face reference and is left out.
    /// </summary>
    [JsonPropertyName("attached_persist_refs")]
    public List<string> AttachedPersistRefs { get; set; } = new List<string>();

    [JsonPropertyName("persist_ref")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRef { get; set; }

    [JsonPropertyName("persist_ref_scope")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PersistRefScope { get; set; }
}
