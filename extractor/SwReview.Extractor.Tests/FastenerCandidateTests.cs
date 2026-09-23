using SwReview.Extractor.Dump;
using SwReview.Extractor.Fasteners;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 010 T050 and T052. Which components the fastener phase treats as fasteners.
///
/// Until this feature only a Toolbox component was one, and <c>is_toolbox</c> was false on
/// every component of both recorded assemblies, so 68 screws named in the vendor pattern
/// never became fasteners (research R2.11). A component is now a candidate when it is a
/// Toolbox part, or when its names give <b>both</b> a kind and a size from any source: a
/// size alone is a bracket with tapped holes, and a kind alone is a description with no
/// screw in it (RK-10). A candidate gets the shank-face request every Toolbox fastener gets
/// today (contracts/fasteners.md section 7).
/// </summary>
public class FastenerCandidateTests
{
    // ---- FastenerNameParser.IsCandidate (T050) ------------------------------------

    [Fact]
    public void IsCandidate_AVendorFileName_GivesAKindAndASize()
    {
        Assert.True(FastenerNameParser.IsCandidate("SHC_M4-0.7X12_FICT-0001.SLDPRT", null, "Default"));
    }

    [Fact]
    public void IsCandidate_AVendorDescription_GivesAKindAndASize()
    {
        Assert.True(FastenerNameParser.IsCandidate(
            "PART_FICT-0001.SLDPRT", "SCREW, SOC M4-0.7 X 12 MM, FICTIONAL", "Default"));
    }

    [Fact]
    public void IsCandidate_TheKindAndTheSizeMayComeFromDifferentSources()
    {
        // The Toolbox shape: the description names the screw, the configuration its size.
        Assert.True(FastenerNameParser.IsCandidate(
            "PART_FICT-0001.SLDPRT", "Socket Head Cap Screw_am", "M6x1.0 x 20 - 20N"));
    }

    [Fact]
    public void IsCandidate_ASizeWithNoKind_IsNotACandidate()
    {
        // An unknown head code reads the size and no kind, and a bare Toolbox size names no
        // kind at all: neither says "this part is a fastener".
        Assert.False(FastenerNameParser.IsCandidate("QZX_M6-1.0X20_FICT-0006.SLDPRT", null, "Default"));
        Assert.False(FastenerNameParser.IsCandidate("PART_FICT-0001.SLDPRT", null, "M6x1.0 x 20"));
    }

    [Fact]
    public void IsCandidate_AKindWithNoSize_IsNotACandidate()
    {
        Assert.False(FastenerNameParser.IsCandidate(
            "PART_FICT-0001.SLDPRT", "Socket Head Cap Screw_am", "Default"));
    }

    [Theory]
    [InlineData("PLATE_BASE_FICT-0007.SLDPRT", "PLATE, BASE, FICTIONAL", "Default")]
    [InlineData("BRACKET_M5_TAPPED_FICT-0008.SLDPRT", null, "Default")]
    [InlineData(null, null, null)]
    [InlineData("", "", "")]
    public void IsCandidate_APartNamedWithNoFastenerForm_IsNever(
        string? fileName, string? description, string? configuration)
    {
        Assert.False(FastenerNameParser.IsCandidate(fileName, description, configuration));
    }

    /// <summary>
    /// The predicate over the shared vector table: a row is a candidate exactly when the table
    /// expects both a kind and a size from it. One table therefore tests the parser and the
    /// gate built on it, as contracts/fasteners.md section 7 asks.
    /// </summary>
    [Theory]
    [MemberData(nameof(FastenerNameVectors.CSharpRows), MemberType = typeof(FastenerNameVectors))]
    public void IsCandidate_AgreesWithEveryRowOfTheSharedVectorTable(int index, string source, string text)
    {
        FastenerNameVectors.Row row = FastenerNameVectors.Rows[index];
        Assert.Equal(source, row.Source);
        Assert.Equal(text, row.Text);

        bool expected = row.Expected != null && row.Expected.Kind != null;

        Assert.Equal(expected, FastenerNameVectors.IsCandidate(row));
    }

    // ---- FastenerDumper.IsFastenerCandidate (T052) --------------------------------

    [Theory]
    [InlineData(null, null, null)]
    [InlineData("PLATE_BASE_FICT-0007.SLDPRT", "PLATE, BASE, FICTIONAL", "Default")]
    [InlineData("socket head cap screw_am.sldprt", "Socket Head Cap Screw_am", "Default")]
    public void IsFastenerCandidate_AToolboxComponent_IsAlwaysOne(
        string? fileName, string? description, string? configuration)
    {
        // Today's behaviour, unchanged: a Toolbox part is a fastener whatever its names say,
        // and its unreadable names become the gaps the dumper already records.
        Assert.True(FastenerDumper.IsFastenerCandidate(true, fileName, description, configuration));
    }

    [Fact]
    public void IsFastenerCandidate_ANonToolboxComponentWhoseFileNameParses_IsOne()
    {
        Assert.True(FastenerDumper.IsFastenerCandidate(
            false, "SHC_M4-0.7X12_FICT-0001.SLDPRT", null, "Default"));
    }

    [Fact]
    public void IsFastenerCandidate_ANonToolboxComponentWhoseDescriptionParses_IsOne()
    {
        Assert.True(FastenerDumper.IsFastenerCandidate(
            false, "PART_FICT-0001.SLDPRT", "SCREW, SOC M4-0.7 X 12 MM, FICTIONAL", "Default"));
    }

    [Fact]
    public void IsFastenerCandidate_ANonToolboxComponentWhoseConfigurationNameParses_IsOne()
    {
        // The configuration gives the size and the head code in its own vendor form gives
        // the kind: "a kind and a size from any source".
        Assert.True(FastenerDumper.IsFastenerCandidate(
            false, "PART_FICT-0001.SLDPRT", null, "SHC_M4-0.7X12_FICT-0001"));
    }

    [Theory]
    [InlineData("PLATE_BASE_FICT-0007.SLDPRT", "PLATE, BASE, FICTIONAL", "Default")]
    [InlineData("BRACKET_M5_TAPPED_FICT-0008.SLDPRT", null, "Default")]
    [InlineData("PART_FICT-0001.SLDPRT", null, "M6x1.0 x 20")]
    [InlineData(null, null, null)]
    public void IsFastenerCandidate_ANonToolboxPlateNamedWithNoFastener_IsNever(
        string? fileName, string? description, string? configuration)
    {
        Assert.False(FastenerDumper.IsFastenerCandidate(false, fileName, description, configuration));
    }
}
