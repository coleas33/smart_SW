using System;
using System.Linq;
using System.Text.RegularExpressions;
using SwReview.Extractor.Ids;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Ids must be stable across dumps so two packages of the same design can be compared, and
/// the component id pattern is enforced by the IR schema (cmp:NNNN).
/// </summary>
public class DocumentIdsTests
{
    [Fact]
    public void For_SamePath_GivesTheSameIdEveryTime()
    {
        const string path = @"C:\vault\bracket-assy\housing.SLDPRT";

        Assert.Equal(DocumentIds.For(path), DocumentIds.For(path));
    }

    [Fact]
    public void For_IsCaseAndSeparatorInsensitive()
    {
        Assert.Equal(
            DocumentIds.For(@"C:\Vault\Bracket-Assy\Housing.SLDPRT"),
            DocumentIds.For(@"c:/vault/bracket-assy/housing.sldprt"));
    }

    [Fact]
    public void For_TrimsSurroundingWhitespace()
    {
        Assert.Equal(
            DocumentIds.For(@"C:\vault\housing.SLDPRT"),
            DocumentIds.For("  C:\\vault\\housing.SLDPRT  "));
    }

    [Fact]
    public void For_DifferentPaths_GiveDifferentIds()
    {
        Assert.NotEqual(
            DocumentIds.For(@"C:\vault\housing.SLDPRT"),
            DocumentIds.For(@"C:\vault\cover.SLDPRT"));
    }

    [Fact]
    public void For_ProducesTheDocumentedShape()
    {
        string id = DocumentIds.For(@"C:\vault\housing.SLDPRT");

        Assert.Matches(new Regex("^doc:[0-9a-f]{12}$"), id);
    }

    [Fact]
    public void DesignId_IsDerivedFromTheRootDocumentAndIsDistinctFromIt()
    {
        string design = DocumentIds.DesignId(@"C:\vault\bracket-assy.SLDASM");

        Assert.Matches(new Regex("^dsn:[0-9a-f]{12}$"), design);
        Assert.Equal(design, DocumentIds.DesignId(@"c:/vault/bracket-assy.SLDASM"));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void For_MissingPath_Throws(string? path)
    {
        Assert.Throws<ArgumentException>(() => DocumentIds.For(path!));
    }
}

public class IdAllocatorTests
{
    [Fact]
    public void Next_StartsAtOneAndPadsToFourDigits()
    {
        var ids = new IdAllocator("cmp");

        Assert.Equal("cmp:0001", ids.Next());
        Assert.Equal("cmp:0002", ids.Next());
    }

    [Fact]
    public void Next_MatchesTheSchemaComponentPattern()
    {
        var ids = new IdAllocator("cmp");
        var pattern = new Regex("^cmp:[0-9]{4,}$");

        for (int i = 0; i < 20; i++)
        {
            Assert.Matches(pattern, ids.Next());
        }
    }

    [Fact]
    public void Next_PastNineThousandNineHundredNinetyNine_GrowsToFiveDigits()
    {
        var ids = new IdAllocator("cmp");
        string last = string.Empty;
        for (int i = 0; i < 10_000; i++)
        {
            last = ids.Next();
        }

        Assert.Equal("cmp:10000", last);
        Assert.Matches(new Regex("^cmp:[0-9]{4,}$"), last);
    }

    [Fact]
    public void Next_UsesThePrefixItWasGiven()
    {
        Assert.Equal("hol:0001", new IdAllocator("hol").Next());
        Assert.Equal("fac:0001", new IdAllocator("fac").Next());
    }

    [Fact]
    public void Count_TracksWhatWasIssued()
    {
        var ids = new IdAllocator("mat");
        ids.Next();
        ids.Next();

        Assert.Equal(2, ids.Count);
    }

    [Fact]
    public void AllocatorsAreIndependent()
    {
        var components = new IdAllocator("cmp");
        var holes = new IdAllocator("hol");
        components.Next();

        Assert.Equal("hol:0001", holes.Next());
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData(" ")]
    public void Constructor_MissingPrefix_Throws(string? prefix)
    {
        Assert.Throws<ArgumentException>(() => new IdAllocator(prefix!));
    }

    [Fact]
    public void Ids_AreUnique()
    {
        var ids = new IdAllocator("cmp");
        string[] issued = Enumerable.Range(0, 500).Select(_ => ids.Next()).ToArray();

        Assert.Equal(issued.Length, issued.Distinct().Count());
    }
}
