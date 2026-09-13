using System;
using System.IO;
using System.Text;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Mesh;

/// <summary>
/// Binary STL, the <c>--meshes stl</c> fallback for a viewer or a workstation where the
/// GLB path is in doubt. The format carries no node and no metadata, so the component
/// transform is baked into the vertices and the persistent reference is NOT carried in the
/// file - only <c>BodyRef.persist_ref</c> in the IR has it.
///
/// Layout: 80-byte ASCII header, uint32 facet count, then per facet 12 float32
/// (normal, v0, v1, v2) and a uint16 attribute byte count of 0. Lengths stay in meters.
/// </summary>
public static class StlWriter
{
    private const int HeaderBytes = 80;
    private const int FacetBytes = 50;

    /// <summary>The binary STL bytes for one body, in assembly space.</summary>
    public static byte[] Write(MeshData mesh)
    {
        if (mesh == null)
        {
            throw new ArgumentNullException(nameof(mesh));
        }

        mesh.Validate();

        Vec3[] vertices = TransformedVertices(mesh);
        int facets = mesh.Indices.Length / 3;

        using (var stream = new MemoryStream(HeaderBytes + 4 + (facets * FacetBytes)))
        using (var writer = new BinaryWriter(stream))
        {
            writer.Write(Header(mesh.Name));
            writer.Write((uint)facets);

            for (int i = 0; i < mesh.Indices.Length; i += 3)
            {
                Vec3 a = vertices[mesh.Indices[i]];
                Vec3 b = vertices[mesh.Indices[i + 1]];
                Vec3 c = vertices[mesh.Indices[i + 2]];

                WriteVec3(writer, Normal(a, b, c));
                WriteVec3(writer, a);
                WriteVec3(writer, b);
                WriteVec3(writer, c);
                writer.Write((ushort)0);
            }

            writer.Flush();
            return stream.ToArray();
        }
    }

    /// <summary>Writes the .stl to disk, creating the directory if needed.</summary>
    public static void WriteFile(string path, MeshData mesh)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("A file path is required.", nameof(path));
        }

        string? directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllBytes(path, Write(mesh));
    }

    private static Vec3[] TransformedVertices(MeshData mesh)
    {
        var vertices = new Vec3[mesh.Positions.Length / 3];
        for (int i = 0; i < vertices.Length; i++)
        {
            var local = new Vec3(
                mesh.Positions[i * 3],
                mesh.Positions[(i * 3) + 1],
                mesh.Positions[(i * 3) + 2]);

            vertices[i] = SwTransform.ApplyToPoint(mesh.NodeTransform, local);
        }

        return vertices;
    }

    /// <summary>Right-handed facet normal from the winding; zero for a degenerate facet.</summary>
    private static Vec3 Normal(Vec3 a, Vec3 b, Vec3 c)
    {
        double ux = b.X - a.X, uy = b.Y - a.Y, uz = b.Z - a.Z;
        double vx = c.X - a.X, vy = c.Y - a.Y, vz = c.Z - a.Z;

        double nx = (uy * vz) - (uz * vy);
        double ny = (uz * vx) - (ux * vz);
        double nz = (ux * vy) - (uy * vx);

        double length = Math.Sqrt((nx * nx) + (ny * ny) + (nz * nz));
        return length <= 0 ? new Vec3(0, 0, 0) : new Vec3(nx / length, ny / length, nz / length);
    }

    private static void WriteVec3(BinaryWriter writer, Vec3 v)
    {
        writer.Write((float)v.X);
        writer.Write((float)v.Y);
        writer.Write((float)v.Z);
    }

    private static byte[] Header(string name)
    {
        var header = new byte[HeaderBytes];
        byte[] text = Encoding.ASCII.GetBytes("SwReview " + (name ?? string.Empty));
        Buffer.BlockCopy(text, 0, header, 0, Math.Min(text.Length, HeaderBytes));
        return header;
    }
}
