using System;
using SwReview.Extractor.PersistRefs;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T045. The persistent reference is the one link between a finding and the SOLIDWORKS
/// entity it is about (constitution Principle IV), so the byte/base64 conversion is
/// tested on its own before any COM code depends on it.
/// </summary>
public class PersistRefCodecTests
{
    [Fact]
    public void Encode_ThenDecode_ReturnsTheSameBytes()
    {
        byte[] original = { 0x00, 0x01, 0x7F, 0x80, 0xFE, 0xFF, 0x00 };

        string encoded = PersistRefCodec.Encode(original);

        Assert.Equal(original, PersistRefCodec.Decode(encoded));
    }

    [Fact]
    public void Encode_ProducesStandardBase64()
    {
        Assert.Equal("AAECAw==", PersistRefCodec.Encode(new byte[] { 0, 1, 2, 3 }));
    }

    [Fact]
    public void Encode_SingleByte_RoundTrips()
    {
        Assert.Equal(new byte[] { 0x2A }, PersistRefCodec.Decode(PersistRefCodec.Encode(new byte[] { 0x2A })));
    }

    [Fact]
    public void Encode_LongRefRoundTrips()
    {
        // Real persist refs are tens to hundreds of bytes; length must not matter.
        var original = new byte[512];
        for (int i = 0; i < original.Length; i++)
        {
            original[i] = (byte)(i * 7 % 256);
        }

        Assert.Equal(original, PersistRefCodec.Decode(PersistRefCodec.Encode(original)));
    }

    [Fact]
    public void Encode_Null_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => PersistRefCodec.Encode(null!));
    }

    [Fact]
    public void Encode_EmptyRef_Throws()
    {
        // An empty ref means SOLIDWORKS gave us nothing; the schema's minLength is 1 and
        // the caller must record a Gap instead of writing an unusable reference.
        PersistRefError error = Assert.Throws<PersistRefError>(() => PersistRefCodec.Encode(Array.Empty<byte>()));
        Assert.Contains("empty", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Decode_MissingText_Throws(string? text)
    {
        Assert.Throws<PersistRefError>(() => PersistRefCodec.Decode(text!));
    }

    [Fact]
    public void Decode_NotBase64_Throws()
    {
        Assert.Throws<PersistRefError>(() => PersistRefCodec.Decode("not base64 !!"));
    }

    [Fact]
    public void Decode_ValidBase64OfZeroBytes_Throws()
    {
        // "" decodes cleanly to an empty array; that is still an unusable reference.
        Assert.Throws<PersistRefError>(() => PersistRefCodec.Decode("===="));
    }

    [Fact]
    public void TryEncode_EmptyRef_ReturnsFalseWithoutThrowing()
    {
        Assert.False(PersistRefCodec.TryEncode(Array.Empty<byte>(), out string? encoded));
        Assert.Null(encoded);
    }

    [Fact]
    public void TryEncode_NonEmptyRef_ReturnsTrue()
    {
        Assert.True(PersistRefCodec.TryEncode(new byte[] { 1, 2 }, out string? encoded));
        Assert.Equal("AQI=", encoded);
    }

    [Fact]
    public void FromComObject_UnwrapsTheObjectArrayInteropReturns()
    {
        // GetPersistReference3 is declared as returning object; the runtime hands back a
        // byte[] boxed as object. The codec must accept that shape.
        object comValue = new byte[] { 9, 8, 7 };

        Assert.Equal("CQgH", PersistRefCodec.EncodeComValue(comValue));
    }

    [Fact]
    public void FromComObject_Null_Throws()
    {
        Assert.Throws<PersistRefError>(() => PersistRefCodec.EncodeComValue(null));
    }

    [Fact]
    public void FromComObject_WrongType_Throws()
    {
        Assert.Throws<PersistRefError>(() => PersistRefCodec.EncodeComValue("a string"));
    }
}
