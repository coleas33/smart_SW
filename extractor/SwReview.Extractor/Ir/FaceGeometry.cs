using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>ISurface.CylinderParams transformed to the assembly frame; meters.</summary>
public sealed class CylinderSurface
{
    [JsonPropertyName("axis_origin")]
    public Vec3 AxisOrigin { get; set; } = new Vec3();

    [JsonPropertyName("axis_dir")]
    public Vec3 AxisDir { get; set; } = new Vec3();

    [JsonPropertyName("radius_m")]
    public double RadiusM { get; set; }
}

/// <summary>ISurface.PlaneParams transformed to the assembly frame; meters.</summary>
public sealed class PlaneSurface
{
    [JsonPropertyName("origin")]
    public Vec3 Origin { get; set; } = new Vec3();

    [JsonPropertyName("normal")]
    public Vec3 Normal { get; set; } = new Vec3();
}

/// <summary>An axis-aligned box in the assembly frame, meters.</summary>
public sealed class BoundingBox
{
    [JsonPropertyName("min")]
    public Vec3 Min { get; set; } = new Vec3();

    [JsonPropertyName("max")]
    public Vec3 Max { get; set; } = new Vec3();
}

/// <summary>
/// contracts/ir.schema.json #/$defs/FaceGeometry. Only faces a check needs are emitted.
/// <see cref="Bbox"/> comes from IFace2.GetBox, which is approximate and must never be
/// used for an axis or a distance (research R12).
/// </summary>
public sealed class FaceGeometry
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    /// <summary>The owning part document, not the assembly.</summary>
    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    [JsonPropertyName("component_id")]
    public string ComponentId { get; set; } = string.Empty;

    [JsonPropertyName("body_id")]
    public string BodyId { get; set; } = string.Empty;

    [JsonPropertyName("kind")]
    public FaceKind Kind { get; set; } = FaceKind.Other;

    [JsonPropertyName("cylinder")]
    public CylinderSurface? Cylinder { get; set; }

    [JsonPropertyName("plane")]
    public PlaneSurface? Plane { get; set; }

    [JsonPropertyName("bbox")]
    public BoundingBox Bbox { get; set; } = new BoundingBox();

    [JsonPropertyName("area_m2")]
    public double? AreaM2 { get; set; }
}

/// <summary>contracts/ir.schema.json #/$defs/BodyRef. Points at an exported mesh file.</summary>
public sealed class BodyRef
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    [JsonPropertyName("component_id")]
    public string ComponentId { get; set; } = string.Empty;

    /// <summary>Package-relative path; must end in .glb or .stl.</summary>
    [JsonPropertyName("mesh_file")]
    public string MeshFile { get; set; } = string.Empty;

    [JsonPropertyName("triangle_count")]
    public int TriangleCount { get; set; }

    [JsonPropertyName("is_solid")]
    public bool IsSolid { get; set; }
}
