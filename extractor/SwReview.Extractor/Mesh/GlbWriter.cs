using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace SwReview.Extractor.Mesh;

/// <summary>
/// A minimal binary glTF (.glb) writer: one buffer, one mesh, one primitive, one node.
/// Written here rather than pulled from a package because the whole need is 150 lines and
/// the container layout has to be pinned by a test anyway (a malformed GLB fails silently
/// in trimesh on the Python side).
///
/// Container (registry.khronos.org/glTF/specs/2.0/glTF-Binary.pdf):
///   12-byte header  magic "glTF", version 2, total length
///   chunk 0         length, type "JSON", UTF-8 JSON padded to 4 bytes with SPACES
///   chunk 1         length, type "BIN\0", binary payload padded to 4 bytes with ZEROS
///
/// Positions are float32 in meters; indices are uint32. The node's matrix is glTF's
/// COLUMN-major 16 floats, so the IR's row-major M[row][col] is written at index
/// col * 4 + row - the translation therefore lands at 12, 13, 14.
/// </summary>
public static class GlbWriter
{
    private const uint Magic = 0x46546C67;        // "glTF"
    private const uint Version = 2;
    private const uint JsonChunkType = 0x4E4F534A; // "JSON"
    private const uint BinChunkType = 0x004E4942;  // "BIN\0"

    private const int ComponentTypeFloat = 5126;
    private const int ComponentTypeUnsignedInt = 5125;
    private const int TargetArrayBuffer = 34962;
    private const int TargetElementArrayBuffer = 34963;
    private const int ModeTriangles = 4;

    /// <summary>The .glb bytes for one body.</summary>
    public static byte[] Write(MeshData mesh)
    {
        if (mesh == null)
        {
            throw new ArgumentNullException(nameof(mesh));
        }

        mesh.Validate();

        byte[] binary = BuildBinaryChunk(mesh, out int indexByteLength, out int positionOffset, out int positionByteLength);
        byte[] json = Pad(
            Encoding.UTF8.GetBytes(BuildJson(mesh, indexByteLength, positionOffset, positionByteLength, binary.Length)),
            (byte)' ');

        int total = 12 + 8 + json.Length + 8 + binary.Length;
        using (var stream = new MemoryStream(total))
        using (var writer = new BinaryWriter(stream))
        {
            writer.Write(Magic);
            writer.Write(Version);
            writer.Write((uint)total);

            writer.Write((uint)json.Length);
            writer.Write(JsonChunkType);
            writer.Write(json);

            writer.Write((uint)binary.Length);
            writer.Write(BinChunkType);
            writer.Write(binary);

            writer.Flush();
            return stream.ToArray();
        }
    }

    /// <summary>Writes the .glb to disk, creating the directory if needed.</summary>
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

    /// <summary>Indices first, then positions; both are 4-byte types so nothing needs padding between them.</summary>
    private static byte[] BuildBinaryChunk(
        MeshData mesh, out int indexByteLength, out int positionOffset, out int positionByteLength)
    {
        indexByteLength = mesh.Indices.Length * sizeof(uint);
        positionOffset = indexByteLength;
        positionByteLength = mesh.Positions.Length * sizeof(float);

        using (var stream = new MemoryStream(indexByteLength + positionByteLength))
        using (var writer = new BinaryWriter(stream))
        {
            foreach (uint index in mesh.Indices)
            {
                writer.Write(index);
            }

            foreach (float value in mesh.Positions)
            {
                writer.Write(value);
            }

            writer.Flush();
            return Pad(stream.ToArray(), 0);
        }
    }

    private static string BuildJson(
        MeshData mesh, int indexByteLength, int positionOffset, int positionByteLength, int bufferLength)
    {
        ComputeBounds(mesh.Positions, out float[] min, out float[] max);

        var json = new StringBuilder(1024);
        json.Append("{\"asset\":{\"version\":\"2.0\",\"generator\":\"SwReview.Extractor\"}");
        json.Append(",\"scene\":0,\"scenes\":[{\"nodes\":[0]}]");

        json.Append(",\"nodes\":[{\"mesh\":0,\"name\":").Append(Quote(mesh.Name));
        json.Append(",\"matrix\":").Append(ColumnMajor(mesh.NodeTransform));
        json.Append(",\"extras\":{\"persist_ref\":").Append(Quote(mesh.PersistRef));
        json.Append(",\"persist_ref_scope\":").Append(Quote(mesh.PersistRefScope));
        json.Append(",\"face_facet_map\":").Append(IntArray(mesh.FaceFacetMap)).Append("}}]");

        json.Append(",\"meshes\":[{\"name\":").Append(Quote(mesh.Name));
        json.Append(",\"primitives\":[{\"attributes\":{\"POSITION\":1},\"indices\":0,\"mode\":")
            .Append(ModeTriangles).Append("}]}]");

        json.Append(",\"accessors\":[");
        json.Append("{\"bufferView\":0,\"byteOffset\":0,\"componentType\":").Append(ComponentTypeUnsignedInt)
            .Append(",\"count\":").Append(mesh.Indices.Length).Append(",\"type\":\"SCALAR\"},");
        json.Append("{\"bufferView\":1,\"byteOffset\":0,\"componentType\":").Append(ComponentTypeFloat)
            .Append(",\"count\":").Append(mesh.Positions.Length / 3).Append(",\"type\":\"VEC3\"")
            .Append(",\"min\":").Append(FloatArray(min))
            .Append(",\"max\":").Append(FloatArray(max)).Append('}');
        json.Append(']');

        json.Append(",\"bufferViews\":[");
        json.Append("{\"buffer\":0,\"byteOffset\":0,\"byteLength\":").Append(indexByteLength)
            .Append(",\"target\":").Append(TargetElementArrayBuffer).Append("},");
        json.Append("{\"buffer\":0,\"byteOffset\":").Append(positionOffset)
            .Append(",\"byteLength\":").Append(positionByteLength)
            .Append(",\"target\":").Append(TargetArrayBuffer).Append('}');
        json.Append(']');

        json.Append(",\"buffers\":[{\"byteLength\":").Append(bufferLength).Append("}]}");
        return json.ToString();
    }

    private static void ComputeBounds(float[] positions, out float[] min, out float[] max)
    {
        min = new[] { positions[0], positions[1], positions[2] };
        max = new[] { positions[0], positions[1], positions[2] };

        for (int i = 0; i < positions.Length; i += 3)
        {
            for (int axis = 0; axis < 3; axis++)
            {
                float value = positions[i + axis];
                if (value < min[axis])
                {
                    min[axis] = value;
                }

                if (value > max[axis])
                {
                    max[axis] = value;
                }
            }
        }
    }

    /// <summary>Row-major M[row][col] to glTF's column-major array (index col * 4 + row).</summary>
    private static string ColumnMajor(double[][] matrix)
    {
        var json = new StringBuilder(160);
        json.Append('[');
        for (int col = 0; col < 4; col++)
        {
            for (int row = 0; row < 4; row++)
            {
                if (col != 0 || row != 0)
                {
                    json.Append(',');
                }

                json.Append(Number(matrix[row][col]));
            }
        }

        return json.Append(']').ToString();
    }

    private static string FloatArray(float[] values)
    {
        var json = new StringBuilder(48);
        json.Append('[');
        for (int i = 0; i < values.Length; i++)
        {
            if (i != 0)
            {
                json.Append(',');
            }

            json.Append(Number(values[i]));
        }

        return json.Append(']').ToString();
    }

    private static string IntArray(int[]? values)
    {
        if (values == null)
        {
            return "null";
        }

        var json = new StringBuilder(values.Length * 4);
        json.Append('[');
        for (int i = 0; i < values.Length; i++)
        {
            if (i != 0)
            {
                json.Append(',');
            }

            json.Append(values[i].ToString(CultureInfo.InvariantCulture));
        }

        return json.Append(']').ToString();
    }

    private static string Number(double value) =>
        value.ToString("R", CultureInfo.InvariantCulture);

    private static string Quote(string? text)
    {
        var json = new StringBuilder((text?.Length ?? 0) + 2);
        json.Append('"');
        foreach (char c in text ?? string.Empty)
        {
            switch (c)
            {
                case '"': json.Append("\\\""); break;
                case '\\': json.Append("\\\\"); break;
                case '\n': json.Append("\\n"); break;
                case '\r': json.Append("\\r"); break;
                case '\t': json.Append("\\t"); break;
                default:
                    if (c < 0x20)
                    {
                        json.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        json.Append(c);
                    }

                    break;
            }
        }

        return json.Append('"').ToString();
    }

    /// <summary>Every chunk length must be a multiple of four.</summary>
    private static byte[] Pad(byte[] bytes, byte filler)
    {
        int remainder = bytes.Length % 4;
        if (remainder == 0)
        {
            return bytes;
        }

        var padded = new byte[bytes.Length + (4 - remainder)];
        Buffer.BlockCopy(bytes, 0, padded, 0, bytes.Length);
        for (int i = bytes.Length; i < padded.Length; i++)
        {
            padded[i] = filler;
        }

        return padded;
    }
}
