using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The census behind the "skipped feature types" gap. Today every GetTypeName2 name the
/// dumpers do not recognise is discarded with no gap and no log line, so the visible
/// symptom of a wrong type-name constant is "holes: 0" and nothing else (Principle I:
/// unsupported coverage must stay visible).
///
/// The accumulator is pure - no interop, no session - so the merge rules are tested here
/// rather than against a live feature tree.
/// </summary>
public class TypeNameCensusTests
{
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
    private const string AssemblyPath = @"C:\vault\bracket-assy\bracket-assy.SLDASM";

    [Fact]
    public void AddPass_UnconsumedName_IsReportedWithItsCount()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("CutExtrude", false), ("CutExtrude", false), ("FtrFolder", false)));

        DocumentTypeNames document = Assert.Single(census.Unconsumed());
        Assert.Equal(HousingPath, document.DocumentPath);
        Assert.Equal(new[] { "CutExtrude", "FtrFolder" }, document.Names.Select(n => n.TypeName));
        Assert.Equal(new[] { 2, 1 }, document.Names.Select(n => n.Count));
    }

    [Fact]
    public void AddPass_ConsumedName_IsNotReported()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("HoleWzd", true), ("HoleWzd", true), ("AdvHoleWzd", false)));

        DocumentTypeNames document = Assert.Single(census.Unconsumed());
        TypeNameCount name = Assert.Single(document.Names);
        Assert.Equal("AdvHoleWzd", name.TypeName);
        Assert.Equal(1, name.Count);
    }

    [Fact]
    public void AddPass_NothingUnconsumed_ReportsNoDocumentAtAll()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("HoleWzd", true), ("CosmeticThread", true)));

        Assert.Empty(census.Unconsumed());
    }

    [Fact]
    public void AddPass_EmptyPass_ReportsNoDocumentAtAll()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass());

        Assert.Empty(census.Unconsumed());
    }

    [Fact]
    public void AddPass_NameConsumedByALaterPassOverTheSameDocument_IsNotReported()
    {
        // The root assembly is walked twice: the component-pattern walk consumes
        // LocalLPattern and ignores MateGroup, the mate walk does the opposite. Neither
        // walk alone knows the whole answer, so consumption is the union of the passes.
        var census = new TypeNameCensus();

        census.AddPass(AssemblyPath, Pass(("LocalLPattern", true), ("MateGroup", false), ("Sensor", false)));
        census.AddPass(AssemblyPath, Pass(("LocalLPattern", false), ("MateGroup", true), ("Sensor", false)));

        DocumentTypeNames document = Assert.Single(census.Unconsumed());
        TypeNameCount name = Assert.Single(document.Names);
        Assert.Equal("Sensor", name.TypeName);
    }

    [Fact]
    public void AddPass_SameDocumentWalkedTwice_DoesNotDoubleTheCounts()
    {
        // A part used forty times is walked forty times; each walk sees the same features,
        // so "CutExtrude x40" would be a fabricated number.
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("CutExtrude", false), ("CutExtrude", false)));
        census.AddPass(HousingPath, Pass(("CutExtrude", false), ("CutExtrude", false)));

        TypeNameCount name = Assert.Single(Assert.Single(census.Unconsumed()).Names);
        Assert.Equal(2, name.Count);
    }

    [Fact]
    public void AddPass_ALaterPassSeesMoreOfAName_KeepsTheLargestSinglePassCount()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("CutExtrude", false)));
        census.AddPass(HousingPath, Pass(("CutExtrude", false), ("CutExtrude", false), ("CutExtrude", false)));
        census.AddPass(HousingPath, Pass(("CutExtrude", false)));

        Assert.Equal(3, Assert.Single(Assert.Single(census.Unconsumed()).Names).Count);
    }

    [Fact]
    public void AddPass_ANameOnlyALaterPassSaw_IsStillReported()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("CutExtrude", false)));
        census.AddPass(HousingPath, Pass(("CutExtrude", false), ("SketchHole", false)));

        Assert.Equal(
            new[] { "CutExtrude", "SketchHole" },
            Assert.Single(census.Unconsumed()).Names.Select(n => n.TypeName));
    }

    [Fact]
    public void AddPass_TwoDocuments_AreReportedSeparatelyInFirstSeenOrder()
    {
        var census = new TypeNameCensus();

        census.AddPass(AssemblyPath, Pass(("Sensor", false)));
        census.AddPass(HousingPath, Pass(("FtrFolder", false)));

        IReadOnlyList<DocumentTypeNames> documents = census.Unconsumed();

        Assert.Equal(new[] { AssemblyPath, HousingPath }, documents.Select(d => d.DocumentPath));
        Assert.Equal("Sensor", documents[0].Names[0].TypeName);
        Assert.Equal("FtrFolder", documents[1].Names[0].TypeName);
    }

    [Fact]
    public void AddPass_TheSameFileSpeltDifferently_IsOneDocument()
    {
        // SOLIDWORKS reports the same file with either case depending on how it was
        // referenced; DocumentIds already normalises that, and the census must agree or a
        // part is censused twice under two spellings.
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("CutExtrude", false), ("CutExtrude", false)));
        census.AddPass(HousingPath.ToLowerInvariant(), Pass(("CutExtrude", false), ("CutExtrude", false)));

        DocumentTypeNames document = Assert.Single(census.Unconsumed());
        Assert.Equal(HousingPath, document.DocumentPath);
        Assert.Equal(2, Assert.Single(document.Names).Count);
    }

    [Fact]
    public void AddPass_TypeNameIsCaseSensitive()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("HoleWzd", true), ("holewzd", false)));

        Assert.Equal("holewzd", Assert.Single(Assert.Single(census.Unconsumed()).Names).TypeName);
    }

    [Fact]
    public void AddPass_BlankTypeName_IsStillCountedUnderAReadablePlaceholder()
    {
        // GetTypeName2 is read as `?? string.Empty` at all three call sites, so a feature
        // the dump walked past can come back nameless. Dropping it would hide exactly the
        // coverage this census exists to show (Principle I): the engineer does not need a
        // name to grep for, they need to know N features were skipped without one.
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass((string.Empty, false), ("   ", false)));

        TypeNameCount counted = Assert.Single(Assert.Single(census.Unconsumed()).Names);
        Assert.Equal(TypeNameCensus.NoTypeName, counted.TypeName);
        Assert.Equal(2, counted.Count);
    }

    [Fact]
    public void AddPass_BlankTypeNamePlaceholder_ReadsAsAPhraseNotAnEmptyGap()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(("CutExtrude", false), (null!, false), ("   ", false)));

        Assert.Equal("(no type name) x2, CutExtrude x1", Assert.Single(census.Unconsumed()).Describe());
    }

    [Fact]
    public void AddPass_NullSighting_IsStillSkipped()
    {
        // A null entry is a caller bug, not a nameless feature; there is nothing to count.
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, new List<TypeNameSighting> { null! });

        Assert.Empty(census.Unconsumed());
    }

    [Fact]
    public void Unconsumed_OrdersByCountThenName()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(
            ("Zed", false),
            ("CutExtrude", false), ("CutExtrude", false), ("CutExtrude", false),
            ("Abc", false),
            ("FtrFolder", false), ("FtrFolder", false)));

        Assert.Equal(
            new[] { "CutExtrude", "FtrFolder", "Abc", "Zed" },
            Assert.Single(census.Unconsumed()).Names.Select(n => n.TypeName));
    }

    [Fact]
    public void Unconsumed_IsStableAcrossCalls()
    {
        var census = new TypeNameCensus();
        census.AddPass(HousingPath, Pass(("CutExtrude", false)));

        Assert.Equal(
            census.Unconsumed().Single().Describe(),
            census.Unconsumed().Single().Describe());
    }

    [Fact]
    public void Unconsumed_NoPassesAtAll_IsEmpty()
    {
        Assert.Empty(new TypeNameCensus().Unconsumed());
    }

    [Fact]
    public void Describe_IsOneReadableLine()
    {
        var census = new TypeNameCensus();

        census.AddPass(HousingPath, Pass(
            ("AdvHoleWzd", false), ("AdvHoleWzd", false), ("AdvHoleWzd", false), ("AdvHoleWzd", false),
            ("FtrFolder", false), ("FtrFolder", false), ("FtrFolder", false)));

        string text = Assert.Single(census.Unconsumed()).Describe();

        Assert.Equal("AdvHoleWzd x4, FtrFolder x3", text);
        Assert.DoesNotContain('\n', text);
        Assert.DoesNotContain('\r', text);
    }

    [Fact]
    public void AddPass_BlankDocumentPath_Throws()
    {
        var census = new TypeNameCensus();

        Assert.Throws<ArgumentException>(() => census.AddPass("  ", Pass(("CutExtrude", false))));
    }

    [Fact]
    public void AddPass_NullSightings_Throws()
    {
        var census = new TypeNameCensus();

        Assert.Throws<ArgumentNullException>(() => census.AddPass(HousingPath, null!));
    }

    private static IEnumerable<TypeNameSighting> Pass(params (string TypeName, bool Consumed)[] sightings) =>
        sightings.Select(s => new TypeNameSighting(s.TypeName, s.Consumed)).ToList();
}
