using System;
using System.Linq;
using System.Text;
using System.Text.Json;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Mesh;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T056's file writers. The mesh is supplementary evidence (Principle IV), but a malformed
/// GLB is silently unreadable by trimesh on the Python side, so the container layout is
/// pinned here against a one-triangle mesh.
/// </summary>
public class GlbWriterTests
{
    private const uint MagicGltf = 0x46546C67;
    private const uint ChunkJson = 0x4E4F534A;
    private const uint ChunkBin = 0x004E4942;

    private static MeshData OneTriangle() => new MeshData
    {
        Name = "housing-1/body-1",
        Positions = new float[] { 0f, 0f, 0f, 0.01f, 0f, 0f, 0f, 0.02f, 0f },
        Indices = new uint[] { 0, 1, 2 },
        NodeTransform = Transform.Identity(),
        PersistRef = "AQIDBA==",
        PersistRefScope = "doc:0123456789ab",
        FaceFacetMap = new[] { 3 },
    };

    [Fact]
    public void Write_StartsWithTheGlbHeader()
    {
        byte[] glb = GlbWriter.Write(OneTriangle());

        Assert.Equal(MagicGltf, BitConverter.ToUInt32(glb, 0));
        Assert.Equal(2u, BitConverter.ToUInt32(glb, 4));
        Assert.Equal((uint)glb.Length, BitConverter.ToUInt32(glb, 8));
    }

    [Fact]
    public void Write_TotalLengthIsAMultipleOfFour()
    {
        Assert.Equal(0, GlbWriter.Write(OneTriangle()).Length % 4);
    }

    [Fact]
    public void Write_HasAJsonChunkThenABinChunk()
    {
        byte[] glb = GlbWriter.Write(OneTriangle());

        uint jsonLength = BitConverter.ToUInt32(glb, 12);
        Assert.Equal(ChunkJson, BitConverter.ToUInt32(glb, 16));
        Assert.Equal(0u, jsonLength % 4);

        int binHeader = 20 + (int)jsonLength;
        uint binLength = BitConverter.ToUInt32(glb, binHeader);
        Assert.Equal(ChunkBin, BitConverter.ToUInt32(glb, binHeader + 4));
        Assert.Equal(0u, binLength % 4);
        Assert.Equal(glb.Length, binHeader + 8 + (int)binLength);
    }

    [Fact]
    public void Write_JsonChunkIsPaddedWithSpaces()
    {
        byte[] glb = GlbWriter.Write(OneTriangle());
        uint jsonLength = BitConverter.ToUInt32(glb, 12);

        // The last byte of the chunk is either '}' or the 0x20 padding the spec requires.
        byte last = glb[20 + (int)jsonLength - 1];
        Assert.True(last == (byte)'}' || last == 0x20, $"unexpected JSON padding byte 0x{last:X2}");
    }

    [Fact]
    public void Write_JsonDescribesOneMeshWithOnePrimitive()
    {
        JsonElement gltf = ReadJson(GlbWriter.Write(OneTriangle()));

        Assert.Equal("2.0", gltf.GetProperty("asset").GetProperty("version").GetString());
        Assert.Equal(1, gltf.GetProperty("meshes").GetArrayLength());

        JsonElement primitive = gltf.GetProperty("meshes")[0].GetProperty("primitives")[0];
        Assert.Equal(4, primitive.GetProperty("mode").GetInt32());          // TRIANGLES
        Assert.Equal(0, primitive.GetProperty("indices").GetInt32());
        Assert.Equal(1, primitive.GetProperty("attributes").GetProperty("POSITION").GetInt32());
    }

    [Fact]
    public void Write_AccessorsDeclareUint32IndicesAndFloat32Positions()
    {
        JsonElement gltf = ReadJson(GlbWriter.Write(OneTriangle()));
        JsonElement accessors = gltf.GetProperty("accessors");

        Assert.Equal(5125, accessors[0].GetProperty("componentType").GetInt32());   // UNSIGNED_INT
        Assert.Equal("SCALAR", accessors[0].GetProperty("type").GetString());
        Assert.Equal(3, accessors[0].GetProperty("count").GetInt32());

        Assert.Equal(5126, accessors[1].GetProperty("componentType").GetInt32());   // FLOAT
        Assert.Equal("VEC3", accessors[1].GetProperty("type").GetString());
        Assert.Equal(3, accessors[1].GetProperty("count").GetInt32());
    }

    [Fact]
    public void Write_PositionAccessorCarriesMinAndMax()
    {
        // Required by the glTF spec for POSITION; trimesh and viewers rely on it.
        JsonElement position = ReadJson(GlbWriter.Write(OneTriangle())).GetProperty("accessors")[1];

        Assert.Equal(new[] { 0.0, 0.0, 0.0 }, position.GetProperty("min").EnumerateArray().Select(e => e.GetDouble()));
        Assert.Equal(
            new[] { 0.01, 0.02, 0.0 },
            position.GetProperty("max").EnumerateArray().Select(e => Math.Round(e.GetDouble(), 6)));
    }

    [Fact]
    public void Write_NodeCarriesTheTransformAsColumnMajorMeters()
    {
        MeshData mesh = OneTriangle();
        mesh.NodeTransform = new[]
        {
            new double[] { 1, 0, 0, 0.1 },
            new double[] { 0, 1, 0, 0.2 },
            new double[] { 0, 0, 1, 0.3 },
            new double[] { 0, 0, 0, 1 },
        };

        double[] matrix = ReadJson(GlbWriter.Write(mesh))
            .GetProperty("nodes")[0].GetProperty("matrix")
            .EnumerateArray().Select(e => e.GetDouble()).ToArray();

        Assert.Equal(16, matrix.Length);

        // glTF matrices are column-major: translation sits at indices 12, 13, 14.
        Assert.Equal(0.1, matrix[12], 6);
        Assert.Equal(0.2, matrix[13], 6);
        Assert.Equal(0.3, matrix[14], 6);
        Assert.Equal(1.0, matrix[15], 6);
    }

    [Fact]
    public void Write_NodeExtrasCarryThePersistRefAndFaceFacetMap()
    {
        JsonElement extras = ReadJson(GlbWriter.Write(OneTriangle()))
            .GetProperty("nodes")[0].GetProperty("extras");

        Assert.Equal("AQIDBA==", extras.GetProperty("persist_ref").GetString());
        Assert.Equal("doc:0123456789ab", extras.GetProperty("persist_ref_scope").GetString());
        Assert.Equal(new[] { 3 }, extras.GetProperty("face_facet_map").EnumerateArray().Select(e => e.GetInt32()));
    }

    [Fact]
    public void Write_OmitsTheFaceFacetMapWhenTessellationDidNotProvideOne()
    {
        MeshData mesh = OneTriangle();
        mesh.FaceFacetMap = null;

        JsonElement extras = ReadJson(GlbWriter.Write(mesh)).GetProperty("nodes")[0].GetProperty("extras");

        Assert.Equal(JsonValueKind.Null, extras.GetProperty("face_facet_map").ValueKind);
    }

    [Fact]
    public void Write_BinaryChunkHoldsTheIndicesThenThePositions()
    {
        byte[] glb = GlbWriter.Write(OneTriangle());
        uint jsonLength = BitConverter.ToUInt32(glb, 12);
        int binStart = 20 + (int)jsonLength + 8;

        Assert.Equal(0u, BitConverter.ToUInt32(glb, binStart));
        Assert.Equal(1u, BitConverter.ToUInt32(glb, binStart + 4));
        Assert.Equal(2u, BitConverter.ToUInt32(glb, binStart + 8));

        // Then the nine position floats: vertex 0 at +12, vertex 1's x at +24.
        Assert.Equal(0f, BitConverter.ToSingle(glb, binStart + 12), 6);
        Assert.Equal(0.01f, BitConverter.ToSingle(glb, binStart + 24), 6);
        Assert.Equal(0.02f, BitConverter.ToSingle(glb, binStart + 40), 6);
    }

    [Fact]
    public void Write_BufferViewsPointInsideTheBinaryChunk()
    {
        JsonElement gltf = ReadJson(GlbWriter.Write(OneTriangle()));
        JsonElement views = gltf.GetProperty("bufferViews");

        int bufferLength = gltf.GetProperty("buffers")[0].GetProperty("byteLength").GetInt32();
        foreach (JsonElement view in views.EnumerateArray())
        {
            int offset = view.GetProperty("byteOffset").GetInt32();
            int length = view.GetProperty("byteLength").GetInt32();
            Assert.True(offset + length <= bufferLength);
        }

        Assert.Equal(34963, views[0].GetProperty("target").GetInt32());   // ELEMENT_ARRAY_BUFFER
        Assert.Equal(34962, views[1].GetProperty("target").GetInt32());   // ARRAY_BUFFER
    }

    [Fact]
    public void Write_EmptyMesh_Throws()
    {
        MeshData mesh = OneTriangle();
        mesh.Indices = Array.Empty<uint>();

        Assert.Throws<ArgumentException>(() => GlbWriter.Write(mesh));
    }

    [Fact]
    public void Write_PositionsNotAMultipleOfThree_Throws()
    {
        MeshData mesh = OneTriangle();
        mesh.Positions = new float[] { 0f, 1f };

        Assert.Throws<ArgumentException>(() => GlbWriter.Write(mesh));
    }

    [Fact]
    public void Write_IndexOutOfRange_Throws()
    {
        MeshData mesh = OneTriangle();
        mesh.Indices = new uint[] { 0, 1, 9 };

        Assert.Throws<ArgumentException>(() => GlbWriter.Write(mesh));
    }

    private static JsonElement ReadJson(byte[] glb)
    {
        uint jsonLength = BitConverter.ToUInt32(glb, 12);
        string json = Encoding.UTF8.GetString(glb, 20, (int)jsonLength).TrimEnd(' ');
        return JsonDocument.Parse(json).RootElement.Clone();
    }
}

public class StlWriterTests
{
    private static MeshData OneTriangle() => new MeshData
    {
        Name = "housing-1/body-1",
        Positions = new float[] { 0f, 0f, 0f, 1f, 0f, 0f, 0f, 1f, 0f },
        Indices = new uint[] { 0, 1, 2 },
        NodeTransform = Transform.Identity(),
        PersistRef = "AQIDBA==",
        PersistRefScope = "doc:0123456789ab",
    };

    [Fact]
    public void Write_HasAnEightyByteHeaderThenTheTriangleCount()
    {
        byte[] stl = StlWriter.Write(OneTriangle());

        Assert.Equal(80 + 4 + 50, stl.Length);
        Assert.Equal(1u, BitConverter.ToUInt32(stl, 80));
    }

    [Fact]
    public void Write_StoresTheFacetNormalThenThreeVertices()
    {
        byte[] stl = StlWriter.Write(OneTriangle());
        int facet = 84;

        // The triangle lies in the XY plane wound counter-clockwise, so the normal is +Z.
        Assert.Equal(0f, BitConverter.ToSingle(stl, facet), 6);
        Assert.Equal(0f, BitConverter.ToSingle(stl, facet + 4), 6);
        Assert.Equal(1f, BitConverter.ToSingle(stl, facet + 8), 6);

        Assert.Equal(1f, BitConverter.ToSingle(stl, facet + 12 + 12), 6);   // vertex 1, x
        Assert.Equal(1f, BitConverter.ToSingle(stl, facet + 12 + 28), 6);   // vertex 2, y
        Assert.Equal(0, BitConverter.ToUInt16(stl, facet + 48));            // attribute count
    }

    [Fact]
    public void Write_BakesTheNodeTransformBecauseStlHasNoNodes()
    {
        MeshData mesh = OneTriangle();
        mesh.NodeTransform = new[]
        {
            new double[] { 1, 0, 0, 5 },
            new double[] { 0, 1, 0, 0 },
            new double[] { 0, 0, 1, 0 },
            new double[] { 0, 0, 0, 1 },
        };

        byte[] stl = StlWriter.Write(mesh);

        Assert.Equal(5f, BitConverter.ToSingle(stl, 84 + 12), 6);
    }

    [Fact]
    public void Write_EmptyMesh_Throws()
    {
        MeshData mesh = OneTriangle();
        mesh.Indices = Array.Empty<uint>();

        Assert.Throws<ArgumentException>(() => StlWriter.Write(mesh));
    }
}
