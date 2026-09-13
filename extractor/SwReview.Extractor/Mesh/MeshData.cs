using System;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Mesh;

/// <summary>
/// One tessellated body, ready to be written. Positions are in the body's own (part)
/// frame in METERS; <see cref="NodeTransform"/> places that frame in the assembly.
/// GLB keeps the two separate (the node carries the matrix); STL has no node concept, so
/// <see cref="StlWriter"/> bakes the transform into the vertices.
/// </summary>
public sealed class MeshData
{
    /// <summary>Component and body name, for the glTF node and mesh.</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>x, y, z triples in meters.</summary>
    public float[] Positions { get; set; } = Array.Empty<float>();

    /// <summary>Triangle indices into <see cref="Positions"/>, three per facet.</summary>
    public uint[] Indices { get; set; } = Array.Empty<uint>();

    /// <summary>Row-major 4x4 in meters, the component's world transform.</summary>
    public double[][] NodeTransform { get; set; } = Transform.Identity();

    /// <summary>Base64 persistent reference of the body.</summary>
    public string PersistRef { get; set; } = string.Empty;

    /// <summary>document_id whose extension produced <see cref="PersistRef"/>.</summary>
    public string PersistRefScope { get; set; } = string.Empty;

    /// <summary>
    /// Facet index to face index, from <c>ITessellation.NeedFaceFacetMap</c>. Null when
    /// the tessellation did not supply one; a check that needs per-face facets then
    /// reports unresolved rather than guessing.
    /// </summary>
    public int[]? FaceFacetMap { get; set; }

    /// <summary>True for a solid body, false for a surface body.</summary>
    public bool IsSolid { get; set; } = true;

    /// <summary>Facet count implied by <see cref="Indices"/>.</summary>
    public int TriangleCount => Indices.Length / 3;

    /// <summary>
    /// Rejects a mesh no writer could produce a usable file from. The caller records a
    /// <see cref="Ir.Gap"/> instead of writing a zero-triangle body.
    /// </summary>
    public void Validate()
    {
        if (Positions.Length == 0 || Positions.Length % 3 != 0)
        {
            throw new ArgumentException(
                $"Positions must be a non-empty multiple of 3, got {Positions.Length}.", nameof(Positions));
        }

        if (Indices.Length == 0 || Indices.Length % 3 != 0)
        {
            throw new ArgumentException(
                $"Indices must be a non-empty multiple of 3, got {Indices.Length}.", nameof(Indices));
        }

        int vertexCount = Positions.Length / 3;
        foreach (uint index in Indices)
        {
            if (index >= vertexCount)
            {
                throw new ArgumentException(
                    $"Index {index} is outside the {vertexCount} vertices.", nameof(Indices));
            }
        }
    }
}
