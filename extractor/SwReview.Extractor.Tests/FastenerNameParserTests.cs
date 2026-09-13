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
}
