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

    // ---- helpers ------------------------------------------------------------------------------

    private ConfirmedDrawingResult Read(string runId, string documentId) =>
        new ConfirmedDrawingRead(
            id => string.Equals(id, RunId, StringComparison.Ordinal) ? _runFolder : null,
            _attachedDocument,
            path => _existing.Contains(path),
            new DrawingOpenScope(_host, null, _seatValidated),
            _phase,
            _documents,
            _documents).Read(runId, documentId);

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
