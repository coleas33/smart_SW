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
/// Everything is resolved from the host's own records - the review session and its run folder
/// from the run id, the candidate from the package - and any step that fails is a sentence with
/// nothing opened: the fake seam records no call. Then the candidate is opened through the guarded
/// seam, read by the drawing phase with every id continuing the package's, merged, and closed when
/// the seam opened it.
/// </summary>
public class ConfirmedDrawingReadTests : IDisposable
{
    private const string RunId = "20260923-101500-chat0001";

    private readonly string _runFolder;

    /// <summary>The review session the host resolves <see cref="RunId"/> to (decision 141A).</summary>
    private readonly ConfirmedDrawingSession _session;

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
        _session = new ConfirmedDrawingSession(_runFolder);
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
    /// the candidate's open refused, the next read is refused by the bound, in a sentence naming both
    /// counts, and nothing is opened. Edited deliberately for decision 141A (2026-10-19): the bound
    /// now refuses at the seam's lookup, since a drawing already open is never refused for failed
    /// opens, so SOLIDWORKS is asked that one thing, where before it was asked nothing.
    /// </summary>
    [Fact]
    public void ARefusedOpenCountsTowardTheTen_SoTheNextReadOpensNothing()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        _host.OpenAnswersNull = true;
        Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));
        _host.Calls.Clear();
        _host.OpenAnswersNull = false;

        AssertRefusedAfterOnlyTheLookup(
            () => Read(RunId, HousingId),
            HousingDrawingPath,
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

    /// <summary>Edited deliberately for decision 141A: refused at the seam's lookup, as above.</summary>
    [Fact]
    public void AnOpenSolidWorksDidNotMakeReadOnlyCountsTowardTheTen()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        _host.OpenedReadOnly = false;
        Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));
        _host.Calls.Clear();
        _host.OpenedReadOnly = true;

        AssertRefusedAfterOnlyTheLookup(
            () => Read(RunId, PinId), PinDrawingPath, "the limit of ten drawings for this review is reached");
    }

    /// <summary>Edited deliberately for decision 141A: refused at the seam's lookup, as above.</summary>
    [Fact]
    public void AReadThatThrowsAfterTheOpenCountsTowardTheTen()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        _phase.Failure = new InvalidOperationException("the sheets did not answer");
        Assert.Throws<InvalidOperationException>(() => Read(RunId, HousingId));
        _phase.Failure = null;
        _phase.Seen.Clear();
        _host.Calls.Clear();

        AssertRefusedAfterOnlyTheLookup(
            () => Read(RunId, PinId), PinDrawingPath, "the limit of ten drawings for this review is reached");
    }

    /// <summary>
    /// A drawing read counts once, by its record: with eight held, a read that lands makes nine, a
    /// refused open the tenth, and the next is refused naming nine in the package and one refused.
    /// Edited deliberately for decision 141A: refused at the seam's lookup, as above.
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

        AssertRefusedAfterOnlyTheLookup(
            () => Read(RunId, PinId),
            PinDrawingPath,
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
    /// Edited deliberately for decision 141A (2026-10-19): the refusal comes after SOLIDWORKS is asked
    /// whether the candidate's drawing is open - the drawing the session knows from its package as it
    /// last loaded it - since one already open is never refused for failed opens; that one lookup is
    /// all, where before nothing was asked.
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
        Assert.Equal(new[] { "OpenDocument " + HousingDrawingPath }, _host.Calls.Select(call => call.ToString()));
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

        ConfirmedDrawingResult result =
            Source(id => id == "20260923-111500-chat0002" ? new ConfirmedDrawingSession(otherFolder) : null)
                .Read("20260923-111500-chat0002", HousingId);

        Assert.True(result.Opened);
    }

    // ---- decision 141A (2026-10-19): the count is the review session's -------------------------------

    /// <summary>
    /// A Retry or Recheck is a new review session in the same run folder (the add-in's
    /// <c>ReviewHost.RetryContextReview</c> and <c>RecheckReview</c>), and the host hands the read the
    /// new session's own: its count starts at nothing, so it opens again where the earlier session's
    /// failed opens had spent the limit, and the earlier session's stays spent.
    /// </summary>
    [Fact]
    public void ANewReviewSessionInTheSameRunFolderStartsItsOwnCount()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 0));
        _host.OpenAnswersNull = true;
        for (int attempt = 0; attempt < 10; attempt++)
        {
            Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, attempt % 2 == 0 ? HousingId : PinId));
        }

        _host.OpenAnswersNull = false;
        _host.Calls.Clear();
        var retried = new ConfirmedDrawingSession(_runFolder);

        ConfirmedDrawingResult result = Source(id => id == RunId ? retried : null).Read(RunId, HousingId);

        Assert.True(result.Opened);
        Assert.Single(_host.Calls, call => call.Name == "OpenDoc6");
        Assert.Equal(0, retried.UnrecordedOpens);
        Assert.Equal(10, _session.UnrecordedOpens);

        _host.Calls.Clear();
        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, PinId));
        Assert.StartsWith("the limit of ten drawings for this review is reached: 10 opens", refusal.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(_host.Calls, call => call.Name == "OpenDoc6");
    }

    /// <summary>
    /// Two review sessions of one run folder never share a count. With eight drawings held, each
    /// session's refused open leaves the other's room alone, so the first still opens the ninth -
    /// shared, the two refused opens would have filled the ten - and the second is then refused by
    /// the nine records and its own one refused open, never the other's.
    /// </summary>
    [Fact]
    public void TwoSessionsOfOneRunFolderDoNotShareACount()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 8));
        var other = new ConfirmedDrawingSession(_runFolder);
        _host.OpenAnswersNull = true;
        Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));
        Assert.Throws<ConfirmedDrawingRefused>(() => ReadIn(other, HousingId));
        _host.OpenAnswersNull = false;

        ConfirmedDrawingResult result = Read(RunId, PinId);

        Assert.True(result.Opened);
        Assert.Equal(9, Reloaded().DrawingRecords!.Count);
        _host.Calls.Clear();
        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => ReadIn(other, HousingId));
        Assert.StartsWith(
            "the limit of ten drawings for this review is reached: 9 in the package and 1 more open that was refused "
                + "or failed, so this one was not opened",
            refusal.Message,
            StringComparison.Ordinal);
        Assert.DoesNotContain(_host.Calls, call => call.Name == "OpenDoc6");
        Assert.Equal(1, _session.UnrecordedOpens);
        Assert.Equal(1, other.UnrecordedOpens);
    }

    /// <summary>
    /// The count is keyed by the session the host resolves, never by anything a request supplies:
    /// a run id spelt as the host's own lookup still matches it (ignoring case), any document of
    /// the review, and a source built anew for every request all reach the one session, so a spent
    /// session stays spent and nothing more is opened.
    /// </summary>
    [Fact]
    public void NothingARequestSuppliesResetsTheCount()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 0));
        string shouted = RunId.ToUpperInvariant();
        Func<string, ConfirmedDrawingSession?> records =
            id => string.Equals(id, RunId, StringComparison.OrdinalIgnoreCase) ? _session : null;
        _host.OpenAnswersNull = true;
        for (int attempt = 0; attempt < 10; attempt++)
        {
            string runId = attempt % 2 == 0 ? RunId : shouted;
            Assert.Throws<ConfirmedDrawingRefused>(() => Source(records).Read(runId, attempt % 3 == 0 ? HousingId : PinId));
        }

        _host.OpenAnswersNull = false;
        _host.Calls.Clear();

        foreach (string runId in new[] { RunId, shouted })
        {
            foreach (string documentId in new[] { HousingId, PinId })
            {
                ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(
                    () => Source(records).Read(runId, documentId));
                Assert.StartsWith("the limit of ten drawings for this review is reached", refusal.Message, StringComparison.Ordinal);
            }
        }

        Assert.DoesNotContain(_host.Calls, call => call.Name == "OpenDoc6");
        Assert.Empty(_phase.Seen);
        Assert.Equal(10, _session.UnrecordedOpens);
    }

    // ---- decision 141A (2026-10-19): a drawing already open is never refused for failed opens ------

    /// <summary>
    /// Once the session's failed opens have spent the limit - on their own, or with the package's
    /// records - a drawing the engineer has open is still read as it stands, since reading it opens
    /// nothing: no visibility call, no open, no close, and the count unchanged. SOLIDWORKS is asked
    /// only whether it is open: by the seam, and, when the failed opens alone spent the limit, once
    /// before the package is loaded as well.
    /// </summary>
    [Theory]
    [InlineData(0, 10)]
    [InlineData(9, 1)]
    [InlineData(5, 5)]
    public void ADrawingAlreadyOpenIsReadAfterTheCountIsSpent(int drawings, int failedOpens)
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: drawings));
        SpendWithFailedOpens(failedOpens);
        _host.AlreadyOpen(HousingDrawingPath);

        ConfirmedDrawingResult result = Read(RunId, HousingId);

        Assert.False(result.Opened);
        Assert.False(result.Closed);
        Assert.Equal(
            Enumerable.Repeat("OpenDocument " + HousingDrawingPath, failedOpens >= 10 ? 2 : 1),
            _host.Calls.Select(call => call.ToString()));
        Assert.Contains(Reloaded().DrawingRecords!, record => record.DocumentId == DocumentIds.For(HousingDrawingPath));
        Assert.Equal(drawings + 1, Reloaded().DrawingRecords!.Count);
        Assert.Equal(failedOpens, _session.UnrecordedOpens);
    }

    /// <summary>
    /// The limit of ten drawing records still applies to a drawing already open: the read that makes
    /// the tenth record lands, and the next already-open drawing is refused with the ten-records
    /// sentence before SOLIDWORKS is asked anything.
    /// </summary>
    [Fact]
    public void TheTenDrawingRecordsStillBoundADrawingAlreadyOpen()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 9));
        SpendWithFailedOpens(1);
        _host.AlreadyOpen(HousingDrawingPath);
        _host.AlreadyOpen(PinDrawingPath);
        Assert.False(Read(RunId, HousingId).Opened);
        _host.Calls.Clear();
        _phase.Seen.Clear();

        AssertRefusedOpeningNothing(
            () => Read(RunId, PinId), "the package already holds ten drawings, so this one was not opened");
    }

    /// <summary>
    /// The engineer closes the drawing between the look that let the request past the early refusal
    /// and the seam's own lookup: the seam decides at its lookup, so the spent session's drawing is
    /// refused there and never opened.
    /// </summary>
    [Fact]
    public void ADrawingClosedBetweenTheLookAndTheReadIsRefusedNotOpened()
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 0));
        SpendWithFailedOpens(10);
        _host.AlreadyOpen(HousingDrawingPath);
        _host.AfterLookup = path => _host.EngineerCloses(path);

        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, HousingId));

        Assert.StartsWith(
            "the limit of ten drawings for this review is reached: 10 opens that were refused or failed, so this one "
                + "was not opened",
            refusal.Message,
            StringComparison.Ordinal);
        Assert.Equal(
            new[] { "OpenDocument " + HousingDrawingPath, "OpenDocument " + HousingDrawingPath },
            _host.Calls.Select(call => call.ToString()));
        Assert.Empty(_phase.Seen);
        Assert.Equal(10, _session.UnrecordedOpens);
    }

    /// <summary>
    /// The early refusal is for a candidate the spent session knows from its package: a document it
    /// knows no candidate for goes through every rule as before, and is refused by the rule it fails.
    /// (Failed opens alone reach ten only while the package holds no drawing, so the package holding
    /// the root drawing is written once the session is spent.)
    /// </summary>
    [Theory]
    [InlineData("root drawing", "is a drawing")]
    [InlineData("assembly", "names no candidate drawing")]
    [InlineData("unknown", "is not a document of the review")]
    public void ARequestTheSpentSessionKnowsNoCandidateForMeetsEveryRuleAsBefore(string which, string refusedWith)
    {
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 0));
        SpendWithFailedOpens(10);
        PackageAppender.Save(_runFolder, ConfirmedDrawingPackage.Build(drawings: 1));
        string documentId = which == "root drawing" ? RootDrawingId : which == "assembly" ? AssemblyId : "doc:000000000000";

        AssertRefusedOpeningNothing(() => Read(RunId, documentId), refusedWith);
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

    /// <summary>A read that <see cref="RunId"/> resolves to <paramref name="session"/>, as a new session of the same review would.</summary>
    private ConfirmedDrawingResult ReadIn(ConfirmedDrawingSession session, string documentId) =>
        Source(id => string.Equals(id, RunId, StringComparison.Ordinal) ? session : null).Read(RunId, documentId);

    private ConfirmedDrawingRead Source() =>
        Source(id => string.Equals(id, RunId, StringComparison.Ordinal) ? _session : null);

    private ConfirmedDrawingRead Source(Func<string, ConfirmedDrawingSession?> sessionOf) =>
        new ConfirmedDrawingRead(
            sessionOf,
            _attachedDocument,
            path => _existing.Contains(path),
            new DrawingOpenScope(_host, null, _seatValidated),
            _phase,
            _documents,
            _documents);

    private EvidencePackage Reloaded() => PackageAppender.Load(_runFolder);

    /// <summary>
    /// <paramref name="failedOpens"/> requests of the session whose opens SOLIDWORKS refuses, by
    /// turns for the pin and the housing; then SOLIDWORKS opens again, and the calls and the reads
    /// seen so far are cleared.
    /// </summary>
    private void SpendWithFailedOpens(int failedOpens)
    {
        _host.OpenAnswersNull = true;
        for (int attempt = 0; attempt < failedOpens; attempt++)
        {
            Assert.Throws<ConfirmedDrawingRefused>(() => Read(RunId, attempt % 2 == 0 ? PinId : HousingId));
        }

        Assert.Equal(failedOpens, _session.UnrecordedOpens);
        _host.OpenAnswersNull = false;
        _host.Calls.Clear();
        _phase.Seen.Clear();
    }

    /// <summary>
    /// Decision 141A: refused by the bound with SOLIDWORKS asked one thing only - whether the drawing
    /// at <paramref name="drawingPath"/> is open, since one already open is still read - and nothing
    /// hidden, opened, read or closed, the package unchanged.
    /// </summary>
    private void AssertRefusedAfterOnlyTheLookup(Func<ConfirmedDrawingResult> read, string drawingPath, string contains)
    {
        string before = File.ReadAllText(PackageAppender.PathIn(_runFolder));

        ConfirmedDrawingRefused refusal = Assert.Throws<ConfirmedDrawingRefused>(() => read());

        Assert.Contains(contains, refusal.Message, StringComparison.Ordinal);
        Assert.Equal(new[] { "OpenDocument " + drawingPath }, _host.Calls.Select(call => call.ToString()));
        Assert.Empty(_phase.Seen);
        Assert.Equal(before, File.ReadAllText(PackageAppender.PathIn(_runFolder)));
    }

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
