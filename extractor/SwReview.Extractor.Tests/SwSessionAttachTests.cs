using System;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// What <see cref="SwSession.Attach"/> refuses before it asks for a configuration.
///
/// The failure this targets: SOLIDWORKS was loaded with a drawing active, the add-in attached
/// to whatever was open, and every drawing answers null to
/// <c>ConfigurationManager.ActiveConfiguration</c>. The session then failed with "reports no
/// active configuration", which names a symptom and no action - and because the tool service
/// swallows a failed start into addin.log, every bridge-backed feature was silently off for
/// the session.
///
/// Attaching is what needs the configuration, not the document: the manifest, the reuse key
/// and every dumper are bound to one. So a drawing is refused by name, with the document to
/// open instead. Choosing that sentence is pure and is testable here; making the call that
/// discovers the kind needs SOLIDWORKS and is not.
/// </summary>
public class SwSessionAttachTests
{
    private const string Drawing = @"C:\vault\FICT-PLATE-2001.SLDDRW";

    [Fact]
    public void AttachRefusal_ADrawingIsRefusedByNameWithTheDocumentToOpenInstead()
    {
        string? refusal = SwSession.AttachRefusal(DocumentKind.Drawing, Drawing, AttachPurpose.Model);

        Assert.NotNull(refusal);
        Assert.Contains(Drawing, refusal!, StringComparison.Ordinal);
        Assert.Contains("drawing", refusal, StringComparison.Ordinal);
        Assert.Contains("open the part or assembly", refusal, StringComparison.Ordinal);
    }

    [Fact]
    public void AttachRefusal_DoesNotFallBackToTheSentenceThatNamedNoCause()
    {
        // The old message. A drawing reaching it again would mean the kind test was lost, and
        // the engineer would be back to a symptom with no action in it.
        Assert.DoesNotContain(
            "reports no active configuration",
            SwSession.AttachRefusal(DocumentKind.Drawing, Drawing, AttachPurpose.Model)!,
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(DocumentKind.Part)]
    [InlineData(DocumentKind.Assembly)]
    public void AttachRefusal_WhatTheExtractorIsForIsNotRefused(DocumentKind kind)
    {
        // The refusal is one document kind wide. A part or an assembly that reports no
        // configuration is a different failure and keeps its own message.
        Assert.Null(SwSession.AttachRefusal(kind, @"C:\vault\FICT-PLATE-2001.SLDPRT", AttachPurpose.Model));
    }
}

/// <summary>
/// Feature 011 (contracts/attach.md sections 1, 2 and 4): the two attach purposes. The model
/// purpose - the tool service, the terminal, the bridge and every other caller of
/// <see cref="SwSession.Attach"/> - refuses a drawing with today's sentence word for word; the
/// dump purpose (<see cref="SwSession.AttachForDump"/>, the extraction only) accepts one, with no
/// configuration. What each purpose refuses is pure, so it is decided here with no seat.
/// </summary>
public class AttachPurposeTests
{
    private const string DrawingPath = @"C:\Fictional\plate\plate.SLDDRW";
    private const string PartPath = @"C:\Fictional\plate\plate.SLDPRT";
    private const string AssemblyPath = @"C:\Fictional\plate\plate-assy.SLDASM";

    /// <summary>Today's sentence, word for word (attach.md section 1): the model purpose's.</summary>
    private const string TodaysDrawingSentence =
        "'" + DrawingPath + "' is a drawing, which has no configuration to bind a session to; "
        + "open the part or assembly it documents.";

    // ---- section 1: the purpose table --------------------------------------------------

    [Fact]
    public void AttachRefusal_TheModelPurposeRefusesADrawingWithTodaysSentenceWordForWord()
    {
        Assert.Equal(
            TodaysDrawingSentence,
            SwSession.AttachRefusal(DocumentKind.Drawing, DrawingPath, AttachPurpose.Model));
    }

    [Fact]
    public void AttachRefusal_TheDumpPurposeAcceptsADrawing()
    {
        Assert.Null(SwSession.AttachRefusal(DocumentKind.Drawing, DrawingPath, AttachPurpose.Dump));
    }

    [Theory]
    [InlineData(DocumentKind.Part, PartPath, AttachPurpose.Model)]
    [InlineData(DocumentKind.Part, PartPath, AttachPurpose.Dump)]
    [InlineData(DocumentKind.Assembly, AssemblyPath, AttachPurpose.Model)]
    [InlineData(DocumentKind.Assembly, AssemblyPath, AttachPurpose.Dump)]
    public void AttachRefusal_PartsAndAssembliesAreAcceptedForBothPurposes(
        DocumentKind kind, string path, AttachPurpose purpose)
    {
        Assert.Null(SwSession.AttachRefusal(kind, path, purpose));
    }

    [Fact]
    public void AttachPurpose_HasExactlyTheTwoPurposesTheContractNames()
    {
        // A third purpose would be a third answer to "may this caller meet a drawing", which the
        // contract's table does not have a column for.
        Assert.Equal(
            new[] { "Model", "Dump" },
            Enum.GetNames(typeof(AttachPurpose)));
    }

    // ---- section 2: a configuration named with a drawing -------------------------------

    [Fact]
    public void ConfigurationRefusal_AConfigurationNamedWithADrawingIsRefusedNamingBoth()
    {
        Assert.Equal(
            "'" + DrawingPath + "' is a drawing and has no configuration; 'Machined' cannot be selected",
            SwSession.ConfigurationRefusal(DocumentKind.Drawing, DrawingPath, "Machined"));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void ConfigurationRefusal_ADrawingWithNoConfigurationNamedIsNotRefused(string? name)
    {
        // The console's --config is optional and the pane passes none: "no name" is not a
        // configuration asked for.
        Assert.Null(SwSession.ConfigurationRefusal(DocumentKind.Drawing, DrawingPath, name));
    }

    [Theory]
    [InlineData(DocumentKind.Part, PartPath)]
    [InlineData(DocumentKind.Assembly, AssemblyPath)]
    public void ConfigurationRefusal_AModelWithAConfigurationNamedIsLeftToTheActiveConfigurationRule(
        DocumentKind kind, string path)
    {
        // A model's named configuration is checked against its active one by the attach itself,
        // with its own sentence; this rule is about drawings only.
        Assert.Null(SwSession.ConfigurationRefusal(kind, path, "Machined"));
    }

    // ---- section 4: a drawing that is not open -----------------------------------------

    [Fact]
    public void NotOpenRefusal_ADrawingThatIsNotOpenIsRefusedByTheDumpPurposeWithTheSentenceOfSection4()
    {
        Assert.Equal(
            "'" + DrawingPath + "' is a drawing that is not open in SOLIDWORKS. Open it first: the "
            + "extractor does not open drawings, because opening one loads every model its views show.",
            SwSession.NotOpenRefusal(DrawingPath, AttachPurpose.Dump));
    }

    [Fact]
    public void NotOpenRefusal_TheModelPurposeRefusesANotOpenDrawingWithTodaysSentenceBeforeAnyOpen()
    {
        // Before feature 011 a drawing path that was not open was opened read-only - loading
        // every model its views show - and only then refused. The model purpose would refuse it
        // open or not, so it is refused with that same sentence before anything is opened.
        Assert.Equal(TodaysDrawingSentence, SwSession.NotOpenRefusal(DrawingPath, AttachPurpose.Model));
    }

    [Theory]
    [InlineData(@"C:\Fictional\plate\PLATE.slddrw")]
    [InlineData(@"C:\Fictional\plate\plate.SldDrw")]
    public void NotOpenRefusal_TheDrawingExtensionIsMatchedInAnyCase(string path)
    {
        Assert.NotNull(SwSession.NotOpenRefusal(path, AttachPurpose.Dump));
        Assert.NotNull(SwSession.NotOpenRefusal(path, AttachPurpose.Model));
    }

    [Theory]
    [InlineData(PartPath)]
    [InlineData(AssemblyPath)]
    [InlineData(@"C:\Fictional\plate\plate.slddrw.SLDPRT")]
    [InlineData(@"C:\Fictional\plate\plate.SLDDRT")]
    public void NotOpenRefusal_APartOrAssemblyFileMayStillBeOpenedReadOnly(string path)
    {
        // OpenReadOnly opens models only (attach.md section 4): a part or an assembly that is
        // not open is opened read-only as before, for both purposes. A sheet-format file is not
        // a drawing, and a name that merely contains ".slddrw" is not one either.
        Assert.Null(SwSession.NotOpenRefusal(path, AttachPurpose.Dump));
        Assert.Null(SwSession.NotOpenRefusal(path, AttachPurpose.Model));
    }

    [Fact]
    public void NotOpenRefusal_NeverSuggestsTheExtractorWillOpenTheDrawing()
    {
        // The sentence is the action the engineer takes; the extractor never takes it for them.
        string refusal = SwSession.NotOpenRefusal(DrawingPath, AttachPurpose.Dump)!;

        Assert.Contains("Open it first", refusal, StringComparison.Ordinal);
        Assert.Contains("does not open drawings", refusal, StringComparison.Ordinal);
    }
}
