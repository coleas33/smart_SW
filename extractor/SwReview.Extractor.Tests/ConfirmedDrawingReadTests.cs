using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;
using static SwReview.Extractor.Tests.Fakes.ConfirmedDrawingPackage;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 011 T071 (contracts/confirmed-open.md section 2): the host side of <c>drawing.read</c>.
/// Everything is resolved from the host's own records - the run folder from the run id, the
/// candidate from the package - and any step that fails is a sentence with nothing opened: the
/// fake seam records no call. Then the candidate is opened through the guarded seam, read by the
/// drawing phase with every id continuing the package's, merged, and closed when the seam opened
/// it.
/// </summary>
public class ConfirmedDrawingReadTests : IDisposable
{
    private const string RunId = "20260923-101500-chat0001";

    private readonly string _runFolder;
    private readonly FakeDrawingOpenHost _host = new FakeDrawingOpenHost();
    private readonly FakeConfirmedDrawingPhase _phase = new FakeConfirmedDrawingPhase();
    private readonly FakeConfirmedDrawingDocuments _documents = new FakeConfirmedDrawingDocuments();
    private readonly HashSet<string> _existing = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        HousingDrawingPath,
        PinDrawingPath,
    };

    private string? _attachedDocument = AssemblyPath;
    private bool _seatValidated = true;

    public ConfirmedDrawingReadTests()
    {
        _runFolder = Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"), RunId);
        Directory.CreateDirectory(_runFolder);
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build());
    }

    public void Dispose()
    {
        string parent = Path.GetDirectoryName(_runFolder)!;
        if (Directory.Exists(parent))
        {
            Directory.Delete(parent, recursive: true);
        }
    }

    // ---- section 2 items 1 to 5: each refusal is a sentence and opens nothing -------------

    [Fact]
    public void AnUnknownRunIsRefused()
    {
        AssertRefusedOpeningNothing(() => Read("20260923-000000-other", HousingId), "is not a review");
    }

    [Fact]
    public void ARunFolderWithNoPackageIsRefused()
    {
        File.Delete(PackageAppender.PathIn(_runFolder));

        AssertRefusedOpeningNothing(() => Read(RunId, HousingId), "no package");
    }

    [Theory]
    [InlineData(@"C:\Fictional\other\other-assy.SLDASM")]
    [InlineData(null)]
    public void APackageWhoseRootIsNotTheBridgesDocumentIsRefused(string? attached)
    {
        _attachedDocument = attached;

        AssertRefusedOpeningNothing(() => Read(RunId, HousingId), "not the document this bridge is attached to");
    }

    [Fact]
    public void TheRootIsComparedAsDiscoveryComparesPaths()
    {
        _attachedDocument = @"C:\FICTIONAL\Bracket\sub\..\bracket-assy.sldasm";

        ConfirmedDrawingResult result = Read(RunId, HousingId);

        Assert.Equal(HousingId, result.DocumentId);
    }

    [Fact]
    public void AnUnknownDocumentIsRefused()
    {
        AssertRefusedOpeningNothing(() => Read(RunId, "doc:000000000000"), "is not a document");
    }

    [Fact]
    public void ADrawingDocumentIsRefused()
    {
        AssertRefusedOpeningNothing(() => Read(RunId, RootDrawingId), "is a drawing");
    }

    [Fact]
    public void ADocumentWithNoCandidateRowIsRefused()
    {
        AssertRefusedOpeningNothing(() => Read(RunId, AssemblyId), "no candidate drawing");
    }

    [Fact]
    public void ACandidateRowWhosePathIsNotTheRuleOfDiscoveryIsRefused()
    {
        EvidencePackage package = PackageAppender.Load(_runFolder);
        package.DrawingCandidates![0].Path = @"C:\Fictional\elsewhere\housing.SLDDRW";
        PackageAppender.Save(_runFolder, package);
        _existing.Add(@"C:\Fictional\elsewhere\housing.SLDDRW");

        AssertRefusedOpeningNothing(() => Read(RunId, HousingId), "not the drawing beside");
    }

    [Fact]
    public void ACandidateRowSpelledDifferentlyButNamingTheSameFileIsRead()
    {
        EvidencePackage package = PackageAppender.Load(_runFolder);
        package.DrawingCandidates![0].Path = @"c:\fictional\BRACKET\housing.slddrw";
        PackageAppender.Save(_runFolder, package);
        _existing.Add(@"c:\fictional\BRACKET\housing.slddrw");

        Assert.Equal(HousingId, Read(RunId, HousingId).DocumentId);
    }

    [Fact]
    public void ACandidateFileThatNoLongerExistsIsRefused()
    {
        _existing.Remove(HousingDrawingPath);

        AssertRefusedOpeningNothing(() => Read(RunId, HousingId), "no longer exists");
    }

    [Fact]
    public void APackageAlreadyHoldingTenDrawingsIsRefused()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 10));

        AssertRefusedOpeningNothing(
            () => Read(RunId, HousingId), "the package already holds ten drawings, so this one was not opened");
    }

    [Fact]
    public void WhileTheSeatHasNotValidatedTheOpenAClosedCandidateIsRefusedWithThatSentence()
    {
        _seatValidated = false;

        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));

        Assert.Equal(DrawingOpenScope.NotValidatedSentence, refusal.Message);
        Assert.DoesNotContain(_host.Calls, call => call.Name != "OpenDocument");
        Assert.Empty(_phase.Seen);
    }

    // ---- the read ---------------------------------------------------------------------------

    [Fact]
    public void EveryDrawingIdContinuesThePackagesHighest()
    {
        Read(RunId, HousingId);

        DrawingRecord record = Reloaded().DrawingRecords!.Last();
        Assert.Equal(new[] { "dsh:0002", "dsh:0003" }, record.Sheets.Select(sheet => sheet.Id));
        Assert.Equal("dvw:0002", record.Sheets[0].Views[0].Id);
        Assert.Equal("ddm:0002", record.Sheets[0].Views[0].DisplayDimensions[0].Id);
        Assert.Equal("dan:0002", record.Sheets[0].Views[0].Annotations[0].Id);
        Assert.Equal("dnt:0002", record.Sheets[0].Views[0].Notes[0].Id);
        Assert.Equal("drv:0002", record.Sheets[0].RevisionTables[0].Id);
        Assert.Equal("dtb:0002", record.Sheets[0].Tables![0].Id);
    }

    [Fact]
    public void TheDrawingsDocumentIdIsTheIdEveryExtractorPackageGivesItsPathAndIsNew()
    {
        EvidencePackage before = PackageAppender.Load(_runFolder);

        ConfirmedDrawingResult result = Read(RunId, HousingId);

        Assert.Equal(DocumentIds.For(HousingDrawingPath), result.DrawingDocumentId);
        Assert.DoesNotContain(before.Documents, document => document.DocumentId == result.DrawingDocumentId);
    }

    [Fact]
    public void TheDrawingPhaseReadsTheOpenedDrawingByItsOwnHandleWithTheReviewsDocumentsToTieViewsTo()
    {
        Read(RunId, HousingId);

        ScopedDrawing drawing = Assert.Single(_phase.Seen);
        Assert.Equal(HousingDrawingPath, drawing.DocumentPath);
        Assert.Same(_host.Opened, drawing.Document);

        // Each view's path is matched against the package's documents by full path, exactly as
        // discovery matches; a path outside the package is null (the phase's gap names it).
        Func<string, string?> reviewed = drawing.ReviewedDocumentId!;
        Assert.Equal(HousingId, reviewed(@"C:\FICTIONAL\bracket\sub\..\housing.sldprt"));
        Assert.Equal(PinId, reviewed(PinPath));
        Assert.Null(reviewed(@"C:\Fictional\other\unrelated.SLDPRT"));
        Assert.Null(reviewed("housing.SLDPRT"));
    }

    [Fact]
    public void ThePackageIsUpdatedInTheRunFolderAndTheCandidateRowIsGone()
    {
        Read(RunId, HousingId);

        EvidencePackage package = Reloaded();
        string drawingId = DocumentIds.For(HousingDrawingPath);

        DrawingRecord record = Assert.Single(package.DrawingRecords!, row => row.DocumentId == drawingId);
        Assert.True(record.OpenedByReview);
        Document document = Assert.Single(package.Documents, row => row.DocumentId == drawingId);
        Assert.Equal(DocumentKind.Drawing, document.Kind);
        Assert.Contains(package.Manifest.Entries, entry => entry.DocumentId == drawingId && entry.Configuration == string.Empty);
        Assert.Equal(new[] { RootDrawingId, drawingId }, package.Design.DrawingDocumentIds);
        Assert.Contains(package.Gaps, gap => gap.EntityKind == "drawing_referenced_document");
        Assert.Equal(new[] { PinId }, package.DrawingCandidates!.Select(candidate => candidate.DocumentId));
        Assert.Equal(new[] { HousingDrawingPath }, _documents.DocumentPathsAsked);
    }

    [Fact]
    public void ADrawingAlreadyOpenIsReadAsItStoodAndLeftOpenAndItsRecordCarriesNoOpenedFlag()
    {
        _host.AlreadyOpen(HousingDrawingPath);

        ConfirmedDrawingResult result = Read(RunId, HousingId);

        Assert.False(result.Opened);
        Assert.False(result.Closed);
        Assert.Null(Reloaded().DrawingRecords!.Last().OpenedByReview);
        Assert.DoesNotContain(_host.Calls, call => call.Name == "CloseDoc" || call.Name == "OpenDoc6");
    }

    [Fact]
    public void TheResultNamesTheDocumentTheDrawingWhatTheSeamDidTheSheetsAndTheGaps()
    {
        ConfirmedDrawingResult result = Read(RunId, HousingId);

        Assert.Equal(HousingId, result.DocumentId);
        Assert.Equal(DocumentIds.For(HousingDrawingPath), result.DrawingDocumentId);
        Assert.True(result.Opened);
        Assert.True(result.Closed);
        Assert.Equal(2, result.Sheets);
        Assert.Equal(1, result.Gaps);
    }

    [Fact]
    public void AReadThatThrows_ClosesWhatTheSeamOpenedAndMergesNothing()
    {
        _phase.Failure = new InvalidOperationException("the sheets did not answer");
        string before = File.ReadAllText(PackageAppender.PathIn(_runFolder));

        Assert.Throws<InvalidOperationException>(() => Read(RunId, HousingId));

        Assert.Equal("CloseDoc " + HousingDrawingPath, _host.Calls.Last().ToString());
        Assert.Equal(before, File.ReadAllText(PackageAppender.PathIn(_runFolder)));
    }

    [Fact]
    public void AnOpenTheSeamRefusesIsARefusalAndMergesNothing()
    {
        _host.OpenAnswersNull = true;

        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));

        Assert.StartsWith("SOLIDWORKS could not open 'housing.SLDDRW' read-only", refusal.Message, StringComparison.Ordinal);
        Assert.Null(Reloaded().DrawingRecords!.SingleOrDefault(row => row.DocumentId == DocumentIds.For(HousingDrawingPath)));
    }

    /// <summary>
    /// Decision 136A (2026-10-19): a candidate SOLIDWORKS did not open read-only is refused, closed
    /// again and never read, and the package is left as it was. The refusal is the sentence the
    /// backend records, word for word, as the <c>drawing.confirmed_open</c> item's reason
    /// (<c>contracts/confirmed-open.md</c> section 1), so the review says why.
    /// </summary>
    [Fact]
    public void ACandidateSolidWorksDidNotOpenReadOnlyIsARefusalSayingWhy_ClosedUnreadAndMergingNothing()
    {
        _host.OpenedReadOnly = false;
        string before = File.ReadAllText(PackageAppender.PathIn(_runFolder));

        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));

        Assert.Equal(
            "SOLIDWORKS opened 'housing.SLDDRW', but not read-only (IsOpenedReadOnly answered false; "
            + FileLoadErrors.Describe(0, 0) + "), so it was not read; it was closed again.",
            refusal.Message);
        Assert.Equal("CloseDoc " + HousingDrawingPath, _host.Calls.Last().ToString());
        Assert.Empty(_phase.Seen);
        Assert.Equal(before, File.ReadAllText(PackageAppender.PathIn(_runFolder)));
    }

    /// <summary>
    /// Decision 136A's review (2026-10-19): a candidate the open says SOLIDWORKS already had open -
    /// the engineer opened it after the lookup, or has it open under another spelling of its path -
    /// was not opened by this read: it is read as it stood and left open, recorded as one the lookup
    /// found, never asked whether it is read-only and never closed.
    /// </summary>
    [Fact]
    public void ACandidateTheOpenSaysWasAlreadyOpenIsReadAsItStoodAndLeftOpen()
    {
        _host.OpenWarnings = 128;
        _host.OpenedReadOnly = false;

        ConfirmedDrawingResult result = Read(RunId, HousingId);

        Assert.False(result.Opened);
        Assert.False(result.Closed);
        Assert.Null(Reloaded().DrawingRecords!.Last().OpenedByReview);
        Assert.DoesNotContain(_host.Calls, call => call.Name == "CloseDoc" || call.Name == "IsOpenedReadOnly");
    }

    [Fact]
    public void ACloseTheSeamRefusesIsRecordedAsAGapOnTheDrawing()
    {
        _host.AfterOpenAnswer = new object();

        ConfirmedDrawingResult result = Read(RunId, HousingId);

        Assert.True(result.Opened);
        Assert.False(result.Closed);
        Gap gap = Assert.Single(Reloaded().Gaps, g => g.EntityKind == "drawing_confirmed_open");
        Assert.Equal(DocumentIds.For(HousingDrawingPath), gap.EntityId);
    }

    /// <summary>
    /// T078 (2026-09-23): the review's extraction read no drawing, so its package says "No open
    /// drawing shows this design..." beside a <c>drawing</c> row <c>skipped</c>. After the
    /// confirmed read the package the backend reloads names the later read in that gap's place,
    /// and the row still says the dump skipped - which it did.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void AfterAnExtractionThatReadNoDrawing_TheReloadedPackageNamesTheLaterReadAndKeepsTheSkippedRow(bool alreadyOpen)
    {
        PackageAppender.Save(
            _runFolder, ConfirmedDrawingPackage.BuildWithNoDrawingRead(PackageWriter.NoOpenDrawingGapSentence));
        if (alreadyOpen)
        {
            _host.AlreadyOpen(HousingDrawingPath);
        }

        Read(RunId, HousingId);

        EvidencePackage package = Reloaded();
        Gap gap = Assert.Single(package.Gaps, PackageWriter.IsDrawingPhaseGap);
        Assert.EndsWith(
            alreadyOpen
                ? "'housing.SLDDRW' (already open, read as it stood)."
                : "'housing.SLDDRW' (opened read-only by the review).",
            gap.Reason,
            StringComparison.Ordinal);
        Assert.DoesNotContain(package.Gaps, row => row.Reason == PackageWriter.NoOpenDrawingGapSentence);
        DumpPhase row = package.Extractor.Phases.Single(phase => phase.Name == "drawing");
        Assert.Equal(DumpPhaseStatus.Skipped, row.Status);
        Assert.Null(row.ElapsedMs);
        IrContract.AssertValid(File.ReadAllText(PackageAppender.PathIn(_runFolder)));
    }

    /// <summary>
    /// The backend reloads the run folder's package right after <c>drawing.read</c> answers
    /// (reviewer tools/drawings.read_confirmed_candidates), through the Python models that
    /// contracts/ir.schema.json is generated from. So the package every successful read leaves -
    /// opened and closed, read as it stood, or with its close refused - must satisfy the contract,
    /// or the engineer's confirmed drawing would be read and then lost to a reload error.
    /// </summary>
    [Theory]
    [InlineData("opened and closed")]
    [InlineData("already open")]
    [InlineData("close refused")]
    public void ThePackageEverySuccessfulReadLeavesSatisfiesTheIrContract(string outcome)
    {
        if (outcome == "already open")
        {
            _host.AlreadyOpen(HousingDrawingPath);
        }
        else if (outcome == "close refused")
        {
            _host.AfterOpenAnswer = new object();
        }

        Read(RunId, HousingId);

        IrContract.AssertValid(File.ReadAllText(PackageAppender.PathIn(_runFolder)));
    }

    [Fact]
    public void ASecondReadOfTheSameCandidateIsRefusedAndOpensNothing()
    {
        Read(RunId, HousingId);
        _host.Calls.Clear();
        _phase.Seen.Clear();

        AssertRefusedOpeningNothing(() => Read(RunId, HousingId), "no candidate drawing");
    }

    // ---- decision 136A (2026-10-19): every attempted open counts toward the ten --------------------

    /// <summary>
    /// An open that left no drawing record still counts toward the bound: with nine drawings held and
    /// the candidate's open refused, the next read is refused by the bound before anything is asked
    /// of SOLIDWORKS, in a sentence naming both counts.
    /// </summary>
    [Fact]
    public void ARefusedOpenCountsTowardTheTen_SoTheNextReadOpensNothing()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        _host.OpenAnswersNull = true;
        Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));
        _host.Calls.Clear();
        _host.OpenAnswersNull = false;

        AssertRefusedOpeningNothing(
            () => Read(RunId, HousingId),
            "the limit of ten drawings for this review is reached: 9 in the package and 1 more open that was "
                + "refused or failed, so this one was not opened");
    }

    /// <summary>
    /// The opens are bounded whatever happens: every open fails, the review asks again and again, and
    /// each request reaches a source built anew, as the add-in builds one on every attach - and still
    /// only the room the package left, nine opens, is ever tried.
    /// </summary>
    [Fact]
    public void OpensThatAllFailAreBoundedByTheRoomLeft_HoweverOftenAndThroughHoweverManySources()
    {
        _host.OpenAnswersNull = true;

        for (int attempt = 0; attempt < 25; attempt++)
        {
            Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, attempt % 2 == 0 ? HousingId : PinId));
        }

        Assert.Equal(9, _host.Calls.Count(call => call.Name == "OpenDoc6"));
        Assert.Empty(_phase.Seen);
    }

    [Fact]
    public void AnOpenSolidWorksDidNotMakeReadOnlyCountsTowardTheTen()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        _host.OpenedReadOnly = false;
        Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));
        _host.Calls.Clear();
        _host.OpenedReadOnly = true;

        AssertRefusedOpeningNothing(() => Read(RunId, PinId), "the limit of ten drawings for this review is reached");
    }

    [Fact]
    public void AReadThatThrowsAfterTheOpenCountsTowardTheTen()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        _phase.Failure = new InvalidOperationException("the sheets did not answer");
        Assert.Throws<InvalidOperationException>(() => Read(RunId, HousingId));
        _phase.Failure = null;
        _phase.Seen.Clear();
        _host.Calls.Clear();

        AssertRefusedOpeningNothing(() => Read(RunId, PinId), "the limit of ten drawings for this review is reached");
    }

    /// <summary>
    /// A drawing read counts once, by its record: with eight held, a read that lands makes nine, a
    /// refused open the tenth, and the next is refused naming nine in the package and one refused.
    /// </summary>
    [Fact]
    public void AReadThatLandsCountsOnceByItsRecordAndARefusedOneByItsAttempt()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 8));
        Read(RunId, HousingId);
        _host.OpenAnswersNull = true;
        Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, PinId));
        _host.Calls.Clear();
        _phase.Seen.Clear();
        _host.OpenAnswersNull = false;

        AssertRefusedOpeningNothing(
            () => Read(RunId, PinId),
            "the limit of ten drawings for this review is reached: 9 in the package and 1 more open that was "
                + "refused or failed, so this one was not opened");
    }

    /// <summary>
    /// Only an open counts: a refusal before the seam, the seam's own refusal while the seat has not
    /// validated it, and a read of a drawing already open that throws open nothing, so with nine held
    /// the tenth drawing is still read afterwards.
    /// </summary>
    [Fact]
    public void WhatOpensNothingCountsForNothing()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        for (int attempt = 0; attempt < 3; attempt++)
        {
            Assert.Throws<ConfirmedDrawingRefused>(() => Read("20260923-000000-other", HousingId));
        }

        _seatValidated = false;
        for (int attempt = 0; attempt < 3; attempt++)
        {
            Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, PinId));
        }

        _seatValidated = true;
        _host.AlreadyOpen(HousingDrawingPath);
        _phase.Failure = new InvalidOperationException("the sheets did not answer");
        for (int attempt = 0; attempt < 3; attempt++)
        {
            Assert.Throws<InvalidOperationException>(() => Read(RunId, HousingId));
        }

        _phase.Failure = null;
        ConfirmedDrawingResult result = Read(RunId, PinId);

        Assert.True(result.Opened);
        Assert.Equal(10, Reloaded().DrawingRecords!.Count);
    }

    /// <summary>
    /// Decision 136A's review (2026-10-19): once the opens that left no record reach the limit on
    /// their own, a request is refused before the review's package is loaded - here a package that
    /// can no longer be loaded at all - so a spent review costs SOLIDWORKS's thread nothing more.
    /// </summary>
    [Fact]
    public void AReviewWhoseFailedOpensAloneReachTheLimitIsRefusedBeforeItsPackageIsLoaded()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 0));
        _host.OpenAnswersNull = true;
        for (int attempt = 0; attempt < 10; attempt++)
        {
            Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, attempt % 2 == 0 ? HousingId : PinId));
        }

        Assert.Equal(10, _host.Calls.Count(call => call.Name == "OpenDoc6"));
        File.WriteAllText(PackageAppender.PathIn(_runFolder), "not a package");
        _host.Calls.Clear();

        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));

        Assert.Equal(
            "the limit of ten drawings for this review is reached: 10 opens that were refused or failed, so this "
                + "one was not opened",
            refusal.Message);
        Assert.Empty(_host.Calls);
        Assert.Empty(_phase.Seen);
    }

    /// <summary>The count is per review: refused opens of one run leave another's room alone.</summary>
    [Fact]
    public void TheCountIsKeptPerReview()
    {
        string otherFolder = Path.Combine(Path.GetDirectoryName(_runFolder)!, "20260923-111500-chat0002");
        Directory.CreateDirectory(otherFolder);
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        PackageAppender.Save(otherFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        _host.OpenAnswersNull = true;
        Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));
        _host.OpenAnswersNull = false;

        ConfirmedDrawingResult result = Source(id => id == "20260923-111500-chat0002" ? otherFolder : null)
            .Read("20260923-111500-chat0002", HousingId);

        Assert.True(result.Opened);
    }

    // ---- the switch ping reports (feature 013 T072, contracts/drawing-capability.md section 1) --

    /// <summary>
    /// The source reports the switch of the very seam it opens through, so what ping says and what
    /// <c>drawing.read</c> does cannot disagree (research R2.24); asking opens and reads nothing.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void OpensClosedDrawingsIsTheSwitchOfTheSeamItOpensThrough(bool seatValidated)
    {
        _seatValidated = seatValidated;

        Assert.Equal(seatValidated, Source().OpensClosedDrawings);
        Assert.Empty(_host.Calls);
        Assert.Empty(_phase.Seen);
    }

    // ---- helpers ------------------------------------------------------------------------------

    private ConfirmedDrawingResult Read(string runId, string documentId) => Source().Read(runId, documentId);

    private ConfirmedDrawingRead Source() =>
        Source(id => string.Equals(id, RunId, StringComparison.Ordinal) ? _runFolder : null);

    private ConfirmedDrawingRead Source(Func<string, string?> runFolderOf) =>
        new ConfirmedDrawingRead(
            runFolderOf,
            _attachedDocument,
            path => _existing.Contains(path),
            new DrawingOpenScope(_host, null, _seatValidated),
            _phase,
            _documents,
            _documents);

    private EvidencePackage Reloaded() => PackageAppender.Load(_runFolder);

    private void AssertRefusedOpeningNothing(Func<ConfirmedDrawingResult> read, string contains)
    {
        string before = File.Exists(PackageAppender.PathIn(_runFolder))
            ? File.ReadAllText(PackageAppender.PathIn(_runFolder))
            : string.Empty;

        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => read());

        Assert.Contains(contains, refusal.Message, StringComparison.Ordinal);
        Assert.Empty(_host.Calls);
        Assert.Empty(_phase.Seen);
        if (before.Length > 0)
        {
            Assert.Equal(before, File.ReadAllText(PackageAppender.PathIn(_runFolder)));
        }
    }
}
