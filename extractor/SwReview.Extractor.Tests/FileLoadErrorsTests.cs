using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The decode table for OpenDoc6's two out parameters.
///
/// "error 2, warning 0" tells the reviewer nothing, and the obvious fix does not work:
/// neither swFileLoadError_e nor swFileLoadWarning_e carries [Flags] (verified by
/// reflecting the installed interop - see FileLoadErrors.cs), so
/// ((swFileLoadError_e)1026).ToString() hands the raw "1026" straight back. Both enums are
/// bit-valued, so the bits are decomposed explicitly here and anything left over is
/// printed rather than dropped (Principle I: a value we cannot explain stays visible).
/// </summary>
public class FileLoadErrorsTests
{
    // ---- errors ------------------------------------------------------------------

    [Fact]
    public void DescribeErrors_ZeroIsNone()
    {
        Assert.Equal("none", FileLoadErrors.DescribeErrors(0));
    }

    [Theory]
    [InlineData(1, "swGenericError")]
    [InlineData(2, "swFileNotFoundError")]
    [InlineData(4, "swIdMatchError")]
    [InlineData(8, "swReadOnlyWarn")]
    [InlineData(1024, "swInvalidFileTypeError")]
    [InlineData(262144, "swLowResourcesError")]
    [InlineData(2097152, "swFileRequiresRepairError")]
    [InlineData(8388608, "swApplicationBusy")]
    [InlineData(16777216, "swConnectedIsOffline")]
    public void DescribeErrors_SingleBit_IsTheMemberName(int value, string expected)
    {
        Assert.Equal(expected, FileLoadErrors.DescribeErrors(value));
    }

    [Fact]
    public void DescribeErrors_CompositeValue_NamesEveryBitInOrder()
    {
        // 1026 = swFileNotFoundError | swInvalidFileTypeError. This is the case the interop
        // enum cannot render at all.
        Assert.Equal(
            "swFileNotFoundError|swInvalidFileTypeError", FileLoadErrors.DescribeErrors(1026));
    }

    [Fact]
    public void DescribeErrors_CompositeValue_IsNotJustTheNumberBack()
    {
        Assert.DoesNotContain("1026", FileLoadErrors.DescribeErrors(1026));
    }

    [Fact]
    public void DescribeErrors_UnknownBit_IsPrintedAsHexRatherThanDropped()
    {
        // 0x02000000 is one bit past the highest member of swFileLoadError_e (2024 SP5);
        // a later release adding a bit must not silently vanish from the message.
        Assert.Equal(
            "swFileNotFoundError + unknown bits 0x02000000",
            FileLoadErrors.DescribeErrors(2 | 0x02000000));
    }

    [Fact]
    public void DescribeErrors_OnlyUnknownBits_StillSaysSomething()
    {
        Assert.Equal("unknown bits 0x40000000", FileLoadErrors.DescribeErrors(0x40000000));
    }

    [Fact]
    public void DescribeErrors_SignBit_IsDecodedAsABitNotAsANegativeNumber()
    {
        // int.MinValue is bit 31. Iterating signed would loop or sign-extend; the decode
        // works on the unsigned bit pattern.
        Assert.Equal("unknown bits 0x80000000", FileLoadErrors.DescribeErrors(int.MinValue));
    }

    [Fact]
    public void DescribeErrors_EveryKnownBitSet_NamesThemAllWithNoResidue()
    {
        string described = FileLoadErrors.DescribeErrors(0x01FFFFFF);

        Assert.DoesNotContain("unknown", described);
        Assert.Equal(25, described.Split('|').Length);
        Assert.StartsWith("swGenericError|swFileNotFoundError|", described);
        Assert.EndsWith("|swApplicationBusy|swConnectedIsOffline", described);
    }

    // ---- warnings ----------------------------------------------------------------

    [Fact]
    public void DescribeWarnings_ZeroIsNone()
    {
        Assert.Equal("none", FileLoadErrors.DescribeWarnings(0));
    }

    [Theory]
    [InlineData(1, "swFileLoadWarning_IdMismatch")]
    [InlineData(2, "swFileLoadWarning_ReadOnly")]
    [InlineData(4, "swFileLoadWarning_SharingViolation")]
    [InlineData(128, "swFileLoadWarning_AlreadyOpen")]
    [InlineData(8192, "swFileLoadWarning_ModelOutOfDate")]
    [InlineData(1048576, "swFileLoadWarning_MissingExternalReferences")]
    public void DescribeWarnings_SingleBit_IsTheMemberName(int value, string expected)
    {
        Assert.Equal(expected, FileLoadErrors.DescribeWarnings(value));
    }

    [Fact]
    public void DescribeWarnings_CompositeValue_NamesEveryBitInOrder()
    {
        Assert.Equal(
            "swFileLoadWarning_IdMismatch|swFileLoadWarning_ReadOnly",
            FileLoadErrors.DescribeWarnings(3));
    }

    [Fact]
    public void DescribeWarnings_WarningBitsAreNotTheErrorBits()
    {
        // The two enums use the same low bits for different meanings: 2 is
        // swFileNotFoundError but swFileLoadWarning_ReadOnly. Decoding a warning with the
        // error table would report a missing file for a read-only open.
        Assert.NotEqual(FileLoadErrors.DescribeErrors(2), FileLoadErrors.DescribeWarnings(2));
    }

    [Fact]
    public void DescribeWarnings_UnknownBit_IsPrintedAsHex()
    {
        Assert.Equal(
            "swFileLoadWarning_IdMismatch + unknown bits 0x00200000",
            FileLoadErrors.DescribeWarnings(1 | 0x00200000));
    }

    [Fact]
    public void DescribeWarnings_EveryKnownBitSet_NamesThemAllWithNoResidue()
    {
        string described = FileLoadErrors.DescribeWarnings(0x001FFFFF);

        Assert.DoesNotContain("unknown", described);
        Assert.Equal(21, described.Split('|').Length);
    }

    // ---- the sentence the caller prints -------------------------------------------

    [Fact]
    public void Describe_KeepsTheRawNumbersNextToTheNames()
    {
        // The raw ints stay in the message: they are what the SOLIDWORKS API documentation
        // and forum posts are searched by.
        Assert.Equal(
            "error 2 (swFileNotFoundError), warning 0 (none)", FileLoadErrors.Describe(2, 0));
    }

    [Fact]
    public void Describe_BothSides_AreDecodedIndependently()
    {
        Assert.Equal(
            "error 0 (none), warning 3 "
            + "(swFileLoadWarning_IdMismatch|swFileLoadWarning_ReadOnly)",
            FileLoadErrors.Describe(0, 3));
    }

    [Fact]
    public void Describe_NothingReported_IsStillSaid()
    {
        // OpenDoc6 can hand back null with no error set at all; "0, 0" must not read as
        // success.
        Assert.Equal("error 0 (none), warning 0 (none)", FileLoadErrors.Describe(0, 0));
    }
}
