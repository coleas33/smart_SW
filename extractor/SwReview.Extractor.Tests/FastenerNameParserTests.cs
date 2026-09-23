using SwReview.Extractor.Fasteners;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T047. Toolbox gives no fastener API in 2024 (research R12), so identity comes from the
/// referenced configuration name and the configuration's custom properties. This parser is
/// the last resort; the rule it must obey is that an unreadable name yields nulls, never a
/// plausible guess (constitution Principle I).
/// </summary>
public class FastenerNameParserTests
{
    [Fact]
    public void Parse_MetricSizeAndLength_ReadsBoth()
    {
        FastenerIdentity id = FastenerNameParser.Parse("M6 x 20");

        Assert.Equal("M6", id.ThreadDesignation);
        Assert.NotNull(id.Length);
        Assert.Equal(20.0, id.Length!.Value);
        Assert.Equal(LengthUnit.Mm, id.Length.Unit);
        Assert.Equal(IdentitySource.NameParse, id.IdentitySource);
    }

    [Fact]
    public void Parse_MetricSizeWithoutPitch_DoesNotInventAPitch()
    {
        // "M6" alone does not say coarse; M6x1.0 must not be assumed.
        Assert.Equal("M6", FastenerNameParser.Parse("M6 x 20").ThreadDesignation);
    }

    [Fact]
    public void Parse_MetricSizeWithPitchAndThreadLength_ReadsDesignationAndLength()
    {
        FastenerIdentity id = FastenerNameParser.Parse("M6x1.0 x 20 - 20N");

        Assert.Equal("M6x1.0", id.ThreadDesignation);
        Assert.Equal(20.0, id.Length!.Value);
        Assert.Equal(LengthUnit.Mm, id.Length.Unit);
    }

    [Fact]
    public void Parse_InchUnifiedThread_ReadsDesignationAndInchLength()
    {
        FastenerIdentity id = FastenerNameParser.Parse("1/4-20 x 1");

        Assert.Equal("1/4-20", id.ThreadDesignation);
        Assert.Equal(1.0, id.Length!.Value);
        Assert.Equal(LengthUnit.In, id.Length.Unit);
    }

    [Fact]
    public void Parse_InchFractionalLength_ReadsTheMixedNumber()
    {
        FastenerIdentity id = FastenerNameParser.Parse("1/4-20 x 1-1/2");

        Assert.Equal("1/4-20", id.ThreadDesignation);
        Assert.Equal(1.5, id.Length!.Value);
        Assert.Equal(LengthUnit.In, id.Length.Unit);
    }

    [Fact]
    public void Parse_NumberedInchScrew_ReadsTheDesignation()
    {
        FastenerIdentity id = FastenerNameParser.Parse("#10-32 x 0.75");

        Assert.Equal("#10-32", id.ThreadDesignation);
        Assert.Equal(0.75, id.Length!.Value);
        Assert.Equal(LengthUnit.In, id.Length.Unit);
    }

    [Fact]
    public void Parse_ToolboxDescription_ReadsHeadTypeAndKind()
    {
        FastenerIdentity id = FastenerNameParser.Parse("socket head cap screw_am");

        Assert.Equal("socket head cap", id.HeadType);
        Assert.Equal(FastenerKind.Screw, id.Kind);

        // No size or length is present, and none is invented.
        Assert.Null(id.ThreadDesignation);
        Assert.Null(id.Length);
    }

    [Fact]
    public void Parse_CombinesTheConfigurationNameWithTheDescription()
    {
        FastenerIdentity id = FastenerNameParser.Parse(
            configurationName: "M6x1.0 x 20 - 20N",
            description: "Socket Head Cap Screw_am");

        Assert.Equal("M6x1.0", id.ThreadDesignation);
        Assert.Equal(20.0, id.Length!.Value);
        Assert.Equal("socket head cap", id.HeadType);
        Assert.Equal(FastenerKind.Screw, id.Kind);
    }

    [Theory]
    [InlineData("hex head bolt", "hex head", FastenerKind.Bolt)]
    [InlineData("Hex Flange Nut", "hex flange", FastenerKind.Nut)]
    [InlineData("Plain Washer", null, FastenerKind.Washer)]
    [InlineData("Button Head Cap Screw", "button head cap", FastenerKind.Screw)]
    [InlineData("Flat Head Screw", "flat head", FastenerKind.Screw)]
    [InlineData("Dowel Pin", null, FastenerKind.Pin)]
    public void Parse_KnownVocabulary_ReadsHeadTypeAndKind(
        string description, string? expectedHead, FastenerKind expectedKind)
    {
        FastenerIdentity id = FastenerNameParser.Parse(null, description);

        Assert.Equal(expectedHead, id.HeadType);
        Assert.Equal(expectedKind, id.Kind);
    }

    [Theory]
    [InlineData("SPECIAL-PART-4471")]
    [InlineData("Default")]
    [InlineData("cfg-A")]
    [InlineData("")]
    [InlineData(null)]
    [InlineData("   ")]
    public void Parse_UnparseableName_YieldsNullsNotGuesses(string? name)
    {
        FastenerIdentity id = FastenerNameParser.Parse(name);

        Assert.Null(id.ThreadDesignation);
        Assert.Null(id.Length);
        Assert.Null(id.HeadType);
        Assert.Equal(FastenerKind.Other, id.Kind);
        Assert.Equal(IdentitySource.NameParse, id.IdentitySource);
    }

    [Fact]
    public void Parse_BareNumberWithNoThreadDesignation_DoesNotGuessTheUnit()
    {
        // "20" could be 20 mm or 20 inches; without a size there is no unit to read.
        FastenerIdentity id = FastenerNameParser.Parse("PART x 20");

        Assert.Null(id.ThreadDesignation);
        Assert.Null(id.Length);
    }

    [Fact]
    public void Parse_SizeWithoutLength_LeavesLengthNull()
    {
        FastenerIdentity id = FastenerNameParser.Parse("M8");

        Assert.Equal("M8", id.ThreadDesignation);
        Assert.Null(id.Length);
    }

    [Fact]
    public void Parse_IsCaseAndSpacingInsensitive()
    {
        FastenerIdentity spaced = FastenerNameParser.Parse("m10 X 35");
        FastenerIdentity tight = FastenerNameParser.Parse("M10x35");

        Assert.Equal("M10", spaced.ThreadDesignation);
        Assert.Equal(35.0, spaced.Length!.Value);
        Assert.Equal("M10", tight.ThreadDesignation);
        Assert.Equal(35.0, tight.Length!.Value);
    }

    [Fact]
    public void Parse_MetricWithPitchAndNoSeparateLength_LeavesLengthNull()
    {
        // "M6x1.0" is size and pitch. The 1.0 is a pitch, not a 1 mm screw.
        FastenerIdentity id = FastenerNameParser.Parse("M6x1.0");

        Assert.Equal("M6x1.0", id.ThreadDesignation);
        Assert.Null(id.Length);
    }

    [Fact]
    public void Parse_NeverReportsAToolboxIdentitySource()
    {
        // Only configuration-specific custom properties earn "custom_property"; a parsed
        // name is always the weaker "name_parse" (data-model.md confidence ordering).
        Assert.Equal(IdentitySource.NameParse, FastenerNameParser.Parse("M6 x 20").IdentitySource);
    }

    [Fact]
    public void Parse_LengthZeroOrNegative_IsRejected()
    {
        Assert.Null(FastenerNameParser.Parse("M6 x 0").Length);
        Assert.Null(FastenerNameParser.Parse("M6 x -5").Length);
    }

    [Fact]
    public void ParseLengthWithUnit_ReadsAnExplicitPropertyValue()
    {
        // The Toolbox "Length" custom property is usually a bare number in the part's unit.
        Assert.Equal(20.0, FastenerNameParser.ParseLength("20", LengthUnit.Mm)!.Value);
        Assert.Equal(20.0, FastenerNameParser.ParseLength("20mm", LengthUnit.In)!.Value);
        Assert.Equal(LengthUnit.Mm, FastenerNameParser.ParseLength("20mm", LengthUnit.In)!.Unit);
        Assert.Equal(0.5, FastenerNameParser.ParseLength("1/2\"", LengthUnit.Mm)!.Value);
        Assert.Equal(LengthUnit.In, FastenerNameParser.ParseLength("1/2\"", LengthUnit.Mm)!.Unit);
        Assert.Null(FastenerNameParser.ParseLength("as required", LengthUnit.Mm));
        Assert.Null(FastenerNameParser.ParseLength(null, LengthUnit.Mm));
    }

    // ---- feature 010: the shared vector table (T050) ------------------------------
    //
    // specs/010-mechanical-checks/contracts/fastener-name-vectors.json is the one list of
    // names both parsers answer. Every row this parser receives is asserted here; the
    // Python parser asserts the same rows, so the two cannot drift (contracts/fasteners.md
    // section 2).

    [Theory]
    [MemberData(nameof(FastenerNameVectors.CSharpRows), MemberType = typeof(FastenerNameVectors))]
    public void Parse_AnswersEveryRowOfTheSharedVectorTable(int index, string source, string text)
    {
        FastenerNameVectors.Row row = FastenerNameVectors.Rows[index];
        Assert.Equal(source, row.Source);
        Assert.Equal(text, row.Text);

        FastenerIdentity id = FastenerNameVectors.Parse(row);

        if (row.Expected == null)
        {
            // "Names no size": whatever else the text says, no designation is read from it.
            Assert.Null(id.ThreadDesignation);
            return;
        }

        Assert.Equal(row.Expected.Thread, FastenerNameVectors.NormalizedThread(id));
        Assert.Equal(row.Expected.Kind, FastenerNameVectors.KindName(id));
        Assert.Equal(row.Expected.HeadType, id.HeadType);

        double? length = FastenerNameVectors.LengthMm(id);
        if (row.Expected.LengthMm == null)
        {
            Assert.Null(length);
        }
        else
        {
            Assert.NotNull(length);
            Assert.Equal(row.Expected.LengthMm.Value, length!.Value, 9);
        }
    }

    [Fact]
    public void TheVectorTable_CoversEverySourceAndBothAnswers()
    {
        // A floor, not a count: a table that lost a source or every negative row would leave
        // the theory above green while testing half the grammar.
        foreach (string source in new[] { "file_name", "description", "configuration" })
        {
            Assert.Contains(
                FastenerNameVectors.Rows,
                row => row.CSharp && row.Source == source && row.Expected != null);
            Assert.Contains(
                FastenerNameVectors.Rows,
                row => row.CSharp && row.Source == source && row.Expected == null);
        }
    }

    // ---- feature 010: the vendor forms, one at a time (T050) ----------------------

    [Fact]
    public void Parse_VendorFileName_ReadsTheHeadCodeTheSizeThePitchAndTheLength()
    {
        FastenerIdentity id = FastenerNameParser.Parse(
            configurationName: "Default", description: null, fileName: "SHC_M4-0.7X12_FICT-0001.SLDPRT");

        Assert.Equal("M4x0.7", id.ThreadDesignation);
        Assert.Equal(12.0, id.Length!.Value);
        Assert.Equal(LengthUnit.Mm, id.Length.Unit);
        Assert.Equal(FastenerKind.Screw, id.Kind);
        Assert.Equal("socket head cap", id.HeadType);
        Assert.Equal(IdentitySource.NameParse, id.IdentitySource);
    }

    [Fact]
    public void Parse_VendorFileName_DropsOnlyASolidWorksExtension()
    {
        // "M4-0.7X12_FICT-0001" has a dot inside its pitch; treating everything after the last
        // dot as an extension would read ".7X12_FICT-0001" off as one.
        FastenerIdentity bare = FastenerNameParser.Parse(null, null, "SHC_M4-0.7X12_FICT-0001");
        FastenerIdentity part = FastenerNameParser.Parse(null, null, "SHC_M4-0.7X12_FICT-0001.sldprt");
        FastenerIdentity assembly = FastenerNameParser.Parse(null, null, "SHC_M4-0.7X12_FICT-0001.SLDASM");

        Assert.Equal("M4x0.7", bare.ThreadDesignation);
        Assert.Equal("M4x0.7", part.ThreadDesignation);
        Assert.Equal("M4x0.7", assembly.ThreadDesignation);
        Assert.Equal(12.0, bare.Length!.Value);
    }

    [Theory]
    [InlineData("FHT_M3-0.5X8_FICT-0002", "flat head")]
    [InlineData("BHT_M5-0.8X10_FICT-0003", "button head")]
    [InlineData("SHC_M10-1.5X16_FICT-0004", "socket head cap")]
    public void Parse_VendorFileName_MapsEveryKnownHeadCodeToAScrewAndItsHead(
        string fileName, string expectedHead)
    {
        FastenerIdentity id = FastenerNameParser.Parse(null, null, fileName);

        Assert.Equal(FastenerKind.Screw, id.Kind);
        Assert.Equal(expectedHead, id.HeadType);
    }

    [Fact]
    public void Parse_VendorFileName_WithAnUnknownHeadCode_ReadsTheSizeAndNoKind()
    {
        FastenerIdentity id = FastenerNameParser.Parse(null, null, "QZX_M6-1.0X20_FICT-0006");

        Assert.Equal("M6x1.0", id.ThreadDesignation);
        Assert.Equal(20.0, id.Length!.Value);
        Assert.Equal(FastenerKind.Other, id.Kind);
        Assert.Null(id.HeadType);
    }

    [Fact]
    public void Parse_VendorDescription_ReadsTheKindTheSizeAndTheLengthInMillimetres()
    {
        FastenerIdentity id = FastenerNameParser.Parse(null, "SCREW, SOC M4-0.7 X 12 MM, FICTIONAL");

        Assert.Equal("M4x0.7", id.ThreadDesignation);
        Assert.Equal(12.0, id.Length!.Value);
        Assert.Equal(LengthUnit.Mm, id.Length.Unit);
        Assert.Equal(FastenerKind.Screw, id.Kind);

        // "SOC" is an abbreviation no head vocabulary carries; it is not approximated.
        Assert.Null(id.HeadType);
    }

    [Fact]
    public void Parse_HyphenPitch_IsAPitchAndTheNextValueIsTheLength()
    {
        FastenerIdentity pitchOnly = FastenerNameParser.Parse("M4-0.7");
        FastenerIdentity withLength = FastenerNameParser.Parse("M4-0.7 x 12");

        Assert.Equal("M4x0.7", pitchOnly.ThreadDesignation);
        Assert.Null(pitchOnly.Length);
        Assert.Equal("M4x0.7", withLength.ThreadDesignation);
        Assert.Equal(12.0, withLength.Length!.Value);
    }

    [Fact]
    public void Parse_DecimalInchThread_ReadsTheDesignationAndTheInchLength()
    {
        FastenerIdentity id = FastenerNameParser.Parse("0.190-32 x 0.5");

        Assert.Equal("0.190-32", id.ThreadDesignation);
        Assert.Equal(0.5, id.Length!.Value);
        Assert.Equal(LengthUnit.In, id.Length.Unit);
    }

    [Theory]
    [InlineData("BRACKET_M5_TAPPED_FICT-0008")]
    [InlineData("PLATE_BASE_FICT-0007.SLDPRT")]
    [InlineData("SPACER M3 FICT-0010")]
    public void Parse_FileNameOutsideEveryFastenerForm_ReadsNoSize(string fileName)
    {
        // A size token somewhere in a name is not a size: every form is anchored, so a
        // bracket with M5 tapped holes is not read as an M5 anything (RK-10).
        FastenerIdentity id = FastenerNameParser.Parse(null, null, fileName);

        Assert.Null(id.ThreadDesignation);
        Assert.Null(id.Length);
    }

    [Fact]
    public void Parse_TheConfigurationNameStillOutranksTheDescriptionAndTheFileName()
    {
        // Toolbox writes the size into the configuration name, and a vendor part's file name
        // is the last word: the order today's parser reads in is kept, with the file name
        // appended after it.
        FastenerIdentity id = FastenerNameParser.Parse(
            configurationName: "M6x1.0 x 20",
            description: "SCREW, SOC M4-0.7 X 12 MM, FICTIONAL",
            fileName: "SHC_M5-0.8X10_FICT-0009");

        Assert.Equal("M6x1.0", id.ThreadDesignation);
        Assert.Equal(20.0, id.Length!.Value);

        // The kind comes from the description first, as it always has.
        Assert.Equal(FastenerKind.Screw, id.Kind);

        // No description or configuration names a head, so the file name's head code does.
        Assert.Equal("socket head cap", id.HeadType);
    }

    [Fact]
    public void Parse_TheDescriptionOutranksTheFileNameForTheSize()
    {
        FastenerIdentity id = FastenerNameParser.Parse(
            configurationName: "Default",
            description: "SCREW, SOC M4-0.7 X 12 MM, FICTIONAL",
            fileName: "SHC_M5-0.8X10_FICT-0009");

        Assert.Equal("M4x0.7", id.ThreadDesignation);
        Assert.Equal(12.0, id.Length!.Value);
    }
}
