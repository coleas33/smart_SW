using System;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Guard;
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

/// <summary>
/// Decision 136A (2026-10-19, feature 011 <c>contracts/attach.md</c> section 4): the console
/// attach's own read-only open. A part or assembly that is not open is opened with
/// <c>OpenDoc6</c>, read-only and silent, and left open on purpose; nothing checked that SOLIDWORKS
/// honoured the option. Now the document the open returned is asked <c>IsOpenedReadOnly()</c>
/// through the session's gate, and one that is not open read-only - or will not say - is refused and
/// closed again, after the identity check feature 011's drawing open uses, never read. A document
/// already open is used as it stands: not asked, never closed.
///
/// SOLIDWORKS is the interop stand-in (<see cref="InteropRecorder{TInterface}"/>): no COM object
/// exists and SOLIDWORKS is never started. The part file is an empty, fictional file in a temporary
/// folder, there only because the open first checks that the path exists.
/// </summary>
public sealed class SwSessionReadOnlyOpenTests : IDisposable
{
    private readonly string _folder;
    private readonly string _partPath;
    private readonly InteropRecorder<ISldWorks> _app = new InteropRecorder<ISldWorks>();
    private readonly InteropRecorder<IModelDoc2> _document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();

    /// <summary>What SOLIDWORKS answers the part's path with: nothing until the open, then the document.</summary>
    private object? _answersThePath;

    public SwSessionReadOnlyOpenTests()
    {
        _folder = Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_folder);
        _partPath = Path.Combine(_folder, "bracket.SLDPRT");
        File.WriteAllBytes(_partPath, new byte[0]);

        var configuration = new InteropRecorder<IConfiguration>(typeof(Configuration)).Answer("get_Name", "Default");
        var manager = new InteropRecorder<IConfigurationManager>(typeof(ConfigurationManager))
            .Answer("get_ActiveConfiguration", configuration.Instance);
        _document
            .Answer("GetType", 1)
            .Answer("GetPathName", _partPath)
            .Answer("get_ConfigurationManager", manager.Instance)
            .Answer("IsOpenedReadOnly", true);
        _app
            .Handle("GetOpenDocumentByName", arguments => _answersThePath)
            .Handle("OpenDoc6", arguments =>
            {
                _answersThePath = _document.Instance;
                return _document.Instance;
            })
            .Handle("CloseDoc", arguments =>
            {
                _answersThePath = null;
                return null;
            })
            .Answer("RevisionNumber", "32.5.0");
    }

    public void Dispose()
    {
        if (Directory.Exists(_folder))
        {
            Directory.Delete(_folder, recursive: true);
        }
    }

    [Fact]
    public void APartSolidWorksOpenedReadOnlyIsAttached_AfterTheCheckGatedAsABareRead()
    {
        SwSession session = Attach();

        Assert.Same(_document.Instance, session.Document);
        Assert.Contains("IsOpenedReadOnly", _document.Members);
        Assert.DoesNotContain("CloseDoc", _app.Members);
        Assert.Equal(new[] { "GetOpenDocumentByName", "OpenDoc6", "IsOpenedReadOnly" }, _observer.Members.Take(3));
        Assert.Empty(_observer.Refusals);
    }

    [Fact]
    public void APartSolidWorksDidNotOpenReadOnly_IsRefusedUnreadAndClosedAfterTheIdentityCheck()
    {
        _document.Answer("IsOpenedReadOnly", false);

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(() => Attach());

        Assert.Equal(
            $"SOLIDWORKS opened '{_partPath}', but not read-only (IsOpenedReadOnly answered false; "
            + FileLoadErrors.Describe(0, 0) + "), so it was not read; it was closed again.",
            refusal.Message);
        Assert.Null(refusal.InnerException);
        Assert.Equal(new[] { "GetOpenDocumentByName", "OpenDoc6", "GetOpenDocumentByName", "CloseDoc" }, _app.Members);
        Assert.Equal(new object?[] { _partPath }, _app.Calls.Last().Arguments);
        Assert.DoesNotContain("get_ConfigurationManager", _document.Members);
        Assert.Equal(
            new[] { "GetOpenDocumentByName", "OpenDoc6", "IsOpenedReadOnly", "CloseDoc" },
            _observer.Members);
        Assert.Empty(_observer.Refusals);
    }

    [Fact]
    public void ACheckThatThrows_FailsClosed_ThePartRefusedUnreadAndClosed_TheFailureKeptInside()
    {
        var failure = new COMException("SOLIDWORKS is busy");
        _document.Fail("IsOpenedReadOnly", failure);

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(() => Attach());

        Assert.Same(failure, refusal.InnerException);
        Assert.Equal(
            $"SOLIDWORKS opened '{_partPath}', but did not confirm it read-only (IsOpenedReadOnly failed: "
            + "COMException: SOLIDWORKS is busy; " + FileLoadErrors.Describe(0, 0) + "), so it was not read; it "
            + "was closed again.",
            refusal.Message);
        Assert.Equal("CloseDoc", _app.Members.Last());
        Assert.DoesNotContain("get_ConfigurationManager", _document.Members);
    }

    [Fact]
    public void APartAlreadyOpenIsNeitherCheckedNorClosed_WhateverItsReadOnlyState()
    {
        _answersThePath = _document.Instance;
        _document.Answer("IsOpenedReadOnly", false);

        SwSession session = Attach();

        Assert.Same(_document.Instance, session.Document);
        Assert.Equal(new[] { "GetOpenDocumentByName", "RevisionNumber" }, _app.Members);
        Assert.DoesNotContain("IsOpenedReadOnly", _document.Members);
    }

    [Fact]
    public void ANotReadOnlyPartWhoseCloseFails_SaysSoInTheRefusal()
    {
        _document.Answer("IsOpenedReadOnly", false);
        _app.Fail("CloseDoc", new COMException("close failed"));

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(() => Attach());

        Assert.EndsWith(
            $"so it was not read; '{_partPath}' was not closed: SOLIDWORKS failed while the extractor was closing "
            + "it (COMException: close failed).",
            refusal.Message,
            StringComparison.Ordinal);
    }

    [Fact]
    public void ANotReadOnlyPartTheIdentityCheckRefusesToClose_ClosesNothingAndSaysWhy()
    {
        _document.Answer("IsOpenedReadOnly", false);
        var another = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        _app.Handle("OpenDoc6", arguments =>
        {
            _answersThePath = another.Instance;
            return _document.Instance;
        });

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(() => Attach());

        Assert.EndsWith(
            $"so it was not read; '{_partPath}' was not closed: SOLIDWORKS answers its path with a document that "
            + "is not the same document the extractor opened, so nothing was closed.",
            refusal.Message,
            StringComparison.Ordinal);
        Assert.DoesNotContain("CloseDoc", _app.Members);
    }

    /// <summary>
    /// The identity check closes nothing SOLIDWORKS no longer answers the path with, and the refusal
    /// names the open's warnings. Edited deliberately on decision 136A's review (2026-10-19): it had
    /// used the "already open" warning, which now means the part was not this attach's to check or
    /// close (<see cref="APartOpenUnderAnotherSpellingOfItsPath_IsAttachedAsItStands_AsBefore136A"/>);
    /// another warning keeps both assertions.
    /// </summary>
    [Fact]
    public void ANotReadOnlyPartTheLookupNeverAnswers_ClosesNothing_AndTheRefusalNamesTheOpensWarnings()
    {
        _document.Answer("IsOpenedReadOnly", false);
        _app.Handle("OpenDoc6", arguments =>
        {
            arguments[5] = 32;
            return _document.Instance;
        });

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(() => Attach());

        Assert.Contains(
            "(IsOpenedReadOnly answered false; error 0 (none), warning 32 (swFileLoadWarning_NeedsRegen))",
            refusal.Message,
            StringComparison.Ordinal);
        Assert.EndsWith(
            $"'{_partPath}' was not closed: SOLIDWORKS no longer answers its path with the same document the "
            + "extractor opened, so nothing was closed.",
            refusal.Message,
            StringComparison.Ordinal);
        Assert.DoesNotContain("CloseDoc", _app.Members);
    }

    // ---- decision 136A's review (2026-10-19): never close what this attach did not open -------

    /// <summary>
    /// The review's case: the engineer opens the part between the lookup and the open, or an open
    /// assembly already holds it, so <c>OpenDoc6</c> answers with that document and says it was
    /// already open - in its warnings, or in its errors' older twin - and SOLIDWORKS now answers the
    /// path with it. It was not opened by this attach: it is attached to as it stands, exactly as one
    /// the lookup found - not asked <c>IsOpenedReadOnly</c>, never closed with the engineer's unsaved
    /// changes.
    /// </summary>
    [Theory]
    [InlineData(0, 128)]
    [InlineData(512, 0)]
    public void APartTheOpenSaysWasAlreadyOpen_IsAttachedAsItStands_NeitherCheckedNorClosed(int errors, int warnings)
    {
        _document.Answer("IsOpenedReadOnly", false);
        _app.Handle("OpenDoc6", arguments =>
        {
            arguments[4] = errors;
            arguments[5] = warnings;
            _answersThePath = _document.Instance;
            return _document.Instance;
        });

        SwSession session = Attach();

        Assert.Same(_document.Instance, session.Document);
        Assert.DoesNotContain("IsOpenedReadOnly", _document.Members);
        Assert.DoesNotContain("CloseDoc", _app.Members);
        Assert.DoesNotContain("IsOpenedReadOnly", _observer.Members);
    }

    /// <summary>
    /// A part the engineer has open under another spelling of its path - a mapped drive against its
    /// UNC path, say - is not found by the lookup, and the open answers with it, saying it was already
    /// open. It is attached to as it stands, as it was before decision 136A, not refused with a
    /// sentence that says the extractor opened it.
    /// </summary>
    [Fact]
    public void APartOpenUnderAnotherSpellingOfItsPath_IsAttachedAsItStands_AsBefore136A()
    {
        _document.Answer("IsOpenedReadOnly", false);
        _app.Handle("OpenDoc6", arguments =>
        {
            arguments[5] = 128;
            return _document.Instance;
        });

        SwSession session = Attach();

        Assert.Same(_document.Instance, session.Document);
        Assert.DoesNotContain("IsOpenedReadOnly", _document.Members);
        Assert.Equal(new[] { "GetOpenDocumentByName", "OpenDoc6", "RevisionNumber" }, _app.Members);
    }

    [Fact]
    public void TheExtractionsAttachMakesTheSameCheck()
    {
        _document.Answer("IsOpenedReadOnly", false);

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(
            () => SwSession.AttachForDump(_app.Instance, _partPath, null, Gate()));

        Assert.EndsWith("so it was not read; it was closed again.", refusal.Message, StringComparison.Ordinal);
        Assert.Equal("CloseDoc", _app.Members.Last());
    }

    private SwSession Attach() => SwSession.Attach(_app.Instance, _partPath, null, Gate());

    private SwGate Gate() => new SwGate(new CircuitBreaker()) { Observer = _observer };
}
