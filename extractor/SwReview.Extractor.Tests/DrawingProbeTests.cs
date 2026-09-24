using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using SwReview.Extractor.Console;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Probes;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;
using static SwReview.Extractor.Tests.Fakes.ProbeFixture;
using IrMeasure = SwReview.Extractor.Ir.Measure;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 011 T080 (contracts/probes.md): <c>swreview-extract probe drawings</c>, the one command
/// the next sitting runs for probes D1 to D14. Everything that decides what a probe prints is
/// tested here over fakes - the extraction as packages built in the test, discovery's seam, the
/// confirmed open's own seam and drawing phase - so the seat only has to supply the answers.
///
/// Three rules run through every test: a probe prints ids, counts, member answers, enum numbers
/// and millimetres, never a path, note, cell or property value, and no name but the
/// <c>dimension@feature</c>, view name and value D6 and D8 print on a dimension's line; a read that
/// fails is a line and the run goes on; and nothing is opened except by D14, and only when it is
/// named.
/// </summary>
public class DrawingProbeTests : IDisposable
{
    private static readonly string PartIdText = PartId;

    private readonly FakeClock _clock = new FakeClock();
    private readonly FakeOpenDocuments _open = new FakeOpenDocuments();
    private readonly FakeDrawingProbeReads _reads = new FakeDrawingProbeReads();
    private readonly FakeProbeFiles _files = new FakeProbeFiles();
    private readonly FakeDrawingOpenProbeHost _host = new FakeDrawingOpenProbeHost();
    private readonly FakeConfirmedDrawingPhase _phase = new FakeConfirmedDrawingPhase();
    private readonly RecordingGateObserver _readObserver = new RecordingGateObserver();
    private readonly RecordingGateObserver _seamObserver = new RecordingGateObserver();
    private readonly List<DumpOptions> _builds = new List<DumpOptions>();
    private readonly List<(string Path, DumpOptions Options)> _modelBuilds = new List<(string, DumpOptions)>();
    private readonly object _document = new object();
    private readonly string _directory =
        Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));

    private Func<DumpOptions, EvidencePackage> _build = options => DrawingPackage();

    private Func<string, DumpOptions, EvidencePackage?> _buildModel = (path, options) =>
        string.Equals(path, PartPath, StringComparison.OrdinalIgnoreCase) ? PartPackage() : null;

    public DrawingProbeTests()
    {
        _files.Existing.Add(DrawingPath);
    }

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }

    // ---- the catalog (contracts/probes.md section 2) ------------------------------------------

    [Fact]
    public void TheCatalogIsD1ToD14InOrder()
    {
        Assert.Equal(
            Enumerable.Range(1, 14).Select(n => "D" + n),
            DrawingProbeCatalog.AllIds);
    }

    [Fact]
    public void EachProbeRunsOnTheKindTheContractsTableNames()
    {
        foreach (string id in new[] { "D1", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12" })
        {
            Assert.Equal(DrawingProbeTarget.Drawing, DrawingProbeCatalog.Get(id).Target);
        }

        Assert.Equal(DrawingProbeTarget.Any, DrawingProbeCatalog.Get("D2").Target);
        Assert.Equal(DrawingProbeTarget.Model, DrawingProbeCatalog.Get("D13").Target);
        Assert.Equal(DrawingProbeTarget.Model, DrawingProbeCatalog.Get("D14").Target);

        // D14 is the one probe that opens a document.
        Assert.Equal(new[] { "D14" }, DrawingProbeCatalog.All.Where(probe => probe.OpensADocument).Select(probe => probe.Id));
    }

    [Fact]
    public void TheDefaultForADrawingIsEveryProbeThatAppliesToIt()
    {
        Assert.Equal(
            new[] { "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12" },
            DrawingProbeCatalog.DefaultFor(DocumentKind.Drawing));
    }

    [Theory]
    [InlineData(DocumentKind.Part)]
    [InlineData(DocumentKind.Assembly)]
    public void TheDefaultForAModelNeverIncludesD14WhichRunsOnlyWhenNamed(DocumentKind kind)
    {
        Assert.Equal(new[] { "D2", "D13" }, DrawingProbeCatalog.DefaultFor(kind));
        Assert.True(DrawingProbeCatalog.Get("D14").AppliesTo(kind));
    }

    [Fact]
    public void NamedProbesRunInCatalogOrderOnceEach()
    {
        Assert.Equal(
            new[] { "D2", "D4", "D14" },
            DrawingProbeCatalog.InCatalogOrder(new[] { "D14", "D4", "D2", "D4" }));
    }

    [Theory]
    [InlineData("D1", true)]
    [InlineData("D14", true)]
    [InlineData("D15", false)]
    [InlineData("d1", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    public void IsKnownIsAnExactMatch(string? id, bool known)
    {
        Assert.Equal(known, DrawingProbeCatalog.IsKnown(id));
    }

    // ---- the command (contracts/probes.md section 1) -------------------------------------------

    [Fact]
    public void DrawingsIsTheFourthSubjectOfProbe()
    {
        Assert.Contains("drawings", Program.ProbeSubjects);
    }

    [Fact]
    public void TheCommandTakesExactlyTheDocumentTheProbesAndTheReportFolder()
    {
        Assert.Equal(new[] { "doc", "probe", "out" }, Program.DrawingsProbeOptionNames);

        string[] known = Program.KnownOptions(Program.DrawingsProbeOptionNames);
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "probe", "drawings", "--profile", "full", "--out", _directory }, 2, known));
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "probe", "drawings", "--meshes", "glb", "--out", _directory }, 2, known));
    }

    [Fact]
    public void TheSettingsReadTheFolderTheDocumentAndTheProbesInAnyCaseAndList()
    {
        DrawingProbeSettings settings = Settings(
            "--out", _directory, "--doc", PartPath, "--probe", "d14,D2", " d13 ");

        Assert.Equal(_directory, settings.OutputDirectory);
        Assert.Equal(PartPath, settings.DocumentPath);
        Assert.Equal(new[] { "D2", "D13", "D14" }, settings.ProbeIds);
    }

    [Fact]
    public void WithoutProbeTheSettingsLeaveTheChoiceToTheDocumentsKind()
    {
        DrawingProbeSettings settings = Settings("--out", _directory);

        Assert.Null(settings.ProbeIds);
        Assert.Null(settings.DocumentPath);
    }

    [Fact]
    public void AnUnknownProbeIsAUsageErrorNamingTheKnownOnes()
    {
        UsageError error = Assert.Throws<UsageError>(() => Settings("--out", _directory, "--probe", "D1,D99"));

        Assert.Contains("'D99'", error.Message, StringComparison.Ordinal);
        Assert.Contains("D1, D2, D3", error.Message, StringComparison.Ordinal);
        Assert.Contains("D14", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void AnEmptyProbeListIsAUsageError()
    {
        Assert.Throws<UsageError>(() => Settings("--out", _directory, "--probe", " , "));
    }

    [Fact]
    public void TheReportFolderIsRequired()
    {
        UsageError error = Assert.Throws<UsageError>(() => Settings("--doc", PartPath));

        Assert.Contains("--out", error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("--out", "{dir}", "--probe", "D99")]
    [InlineData("--probe", "D1")]
    public void ABadCommandLineIsRefusedBeforeSolidWorksIsAskedForAnything(params string[] options)
    {
        var args = new List<string> { "probe", "drawings" };
        args.AddRange(options.Select(option => option.Replace("{dir}", _directory)));

        int exit = Program.RunProbe(args.ToArray());

        Assert.Equal(1, exit);
        Assert.False(Directory.Exists(_directory));
    }

    [Fact]
    public void ADocumentThatIsNotOpenIsRefusedWithASentenceThatSaysOnlyD14Opens()
    {
        string message = Program.DrawingsProbeDocumentNotOpenMessage(PartPath);

        Assert.Contains(PartPath, message, StringComparison.Ordinal);
        Assert.Contains("is not open", message, StringComparison.Ordinal);
        Assert.Contains("D14", message, StringComparison.Ordinal);
    }

    [Fact]
    public void TheCommandAcceptsAllowStartLikeEveryCommandThatAttaches()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "drawings", "--allow-start", "--out", _directory },
            2,
            Program.KnownOptions(Program.DrawingsProbeOptionNames));

        Assert.True(parsed.Flag("allow-start"));
        Assert.Equal(_directory, Program.DrawingsProbeSettingsFrom(parsed).OutputDirectory);
    }

    [Fact]
    public void TheReportNamesWhatTheConfirmedOpensOwnGuardSawBesideTheReadOnlyGateLog()
    {
        Assert.Equal(
            "gate log: the confirmed open's guard (DrawingOpenGuard, D14 only): none",
            Program.DrawingsProbeSeamGateLogLine(Array.Empty<string>()));
        Assert.Equal(
            "gate log: the confirmed open's guard (DrawingOpenGuard, D14 only): GetOpenDocumentByName, ISldWorks.OpenDoc6",
            Program.DrawingsProbeSeamGateLogLine(new[] { "GetOpenDocumentByName", "ISldWorks.OpenDoc6" }));
    }

    [Fact]
    public void EveryMemberTheProbeNamesPassesTheReadOnlyGuard()
    {
        // The probe reads through the read-only guard (contracts/probes.md section 1): every member
        // it names to that gate - its own reads beyond the extraction, and D14's reads of the
        // engineer's session - is a read. D14's three keys go to the confirmed open's own gate.
        foreach (string member in DrawingProbeMember.All.Concat(DrawingOpenProbe.ReadMembers))
        {
            ReadOnlyGuard.Assert(member);
        }

        Assert.DoesNotContain(DrawingOpenProbe.ReadMembers, member => DrawingOpenGuard.AllowedKeys.Contains(member));
    }

    // ---- the runner ---------------------------------------------------------------------------

    [Fact]
    public void EachSectionOpensWithItsIdTitleAndWhatItRunsOn()
    {
        IReadOnlyList<string> lines = RunOnDrawing("D4");

        Assert.Equal("D4: dimension precision and units", lines[0]);
        Assert.Equal("  run on: a drawing with dimensions at their own precision and at the document's", lines[1]);
    }

    [Fact]
    public void AProbeNamedForTheOtherKindSaysSoAndTheRunGoesOn()
    {
        IReadOnlyList<string> lines = RunOnPart("D1", "D13");

        Assert.Equal("  does not apply to a part, so nothing was read", Section(lines, "D1")[2]);
        Assert.Contains("  File.Exists true in 25 ms", Section(lines, "D13"));
        Assert.Empty(_builds);
    }

    [Fact]
    public void AnExtractionThatStopsIsALineAndTheNextProbeStillRuns()
    {
        _build = options => throw new COMException("the drawing did not answer", unchecked((int)0x80010105));

        IReadOnlyList<string> lines = RunOnDrawing("D1", "D4", "D12");

        Assert.Equal("  stopped after 25 ms: COMException 0x80010105", Section(lines, "D1")[2]);
        Assert.Equal("  not read: the Standards extraction stopped (COMException 0x80010105)", Section(lines, "D4")[2]);
        Assert.Equal("  not read: the Standards extraction stopped (COMException 0x80010105)", Section(lines, "D12")[2]);

        // One extraction for all three: the failure is remembered, not retried.
        Assert.Single(_builds);
    }

    [Fact]
    public void TheDrawingSectionsShareOneStandardsExtractionWithTheStandardsTabsOptions()
    {
        RunOnDrawing("D1", "D3", "D4", "D7", "D9", "D10", "D11", "D12");

        DumpOptions options = Assert.Single(_builds);
        Assert.Equal(DumpProfile.Standards, options.Profile);
        Assert.Equal(FaceScope.Needed, options.Faces);
        Assert.Equal(MeshFormat.None, options.Meshes);
        Assert.Null(options.Configuration);
        Assert.Empty(_modelBuilds);
    }

    [Fact]
    public void AProbeThatThrowsIsALineAndTheRunGoesOn()
    {
        _open.ListingFailure = new COMException("listing", unchecked((int)0x80004005));
        _reads.Preferences.Remove(13);

        IReadOnlyList<string> lines = RunOnDrawing("D2", "D11");

        Assert.Equal("  GetDocuments failed: COMException 0x80004005", Section(lines, "D2")[2]);
        Assert.StartsWith("  preferences: 13 (swDetailingDimensionStandard) unread (COMException 0x80020003)", Section(lines, "D11").Last());
    }

    // ---- D1 ------------------------------------------------------------------------------------

    [Fact]
    public void D1_PrintsThePhaseRowsTheCountsAndTheGapKinds()
    {
        Assert.Equal(
            new[]
            {
                "D1: the Standards extraction",
                "  run on: an open multi-sheet drawing",
                "  completed in 25 ms",
                "  phases: document ok 5 ms, manifest ok 1 ms, mate ok 0 ms, feature ok 12 ms, equation ok 2 ms, "
                    + "cutlist ok 3 ms, drawing ok 40 ms, hole skipped, tolerance skipped, fastener skipped, "
                    + "face skipped, body skipped",
                "  drawing records 1, sheets 2, views 3 (by sheet: 2, 1)",
                "  gaps 4: not_extracted/drawing_sheet_views 2, unsupported/drawing_attachment 2",
            },
            RunOnDrawing("D1"));
    }

    [Fact]
    public void D1_WithNoDrawingRecordAndNoGapSaysSo()
    {
        _build = options =>
        {
            EvidencePackage package = DrawingPackage();
            package.DrawingRecords = null;
            package.Gaps.Clear();
            package.Extractor.Phases.Clear();
            return package;
        };

        IReadOnlyList<string> lines = Section(RunOnDrawing("D1"), "D1");

        Assert.Contains("  phases: none recorded", lines);
        Assert.Contains("  drawing records 0", lines);
        Assert.Contains("  gaps 0", lines);
    }

    // ---- D2 ------------------------------------------------------------------------------------

    [Fact]
    public void D2_ListsEveryOpenDocumentByPositionKindVisibilityAndViewsAndNamesTheOnesListedTwice()
    {
        _open.Add(DocumentKind.Part, PartPath);
        OpenDocument drawing = _open.Add(DocumentKind.Drawing, DrawingPath, "", PartPath, PartPath.ToUpperInvariant(), "");
        _open.Documents.Add(new OpenDocument(
            new object(),
            () => throw new COMException("kind", unchecked((int)0x80004005)),
            () => OtherPartPath,
            () => Array.Empty<string>()));
        _open.Add(DocumentKind.Part, PartPath.ToLowerInvariant());
        _reads.Hidden.Add(drawing.Handle!);

        Assert.Equal(
            new[]
            {
                "D2: the open documents",
                "  run on: a model with three drawings open, one hidden behind another window",
                "  documents listed 4",
                "  1: part, visible true",
                "  2: drawing, visible false, views 4 (blank 2), referenced documents 1",
                "  3: kind unread (COMException 0x80004005), visible true",
                "  4: part, visible true",
                "  listed twice: 1 and 4",
            },
            RunOnPart("D2"));
    }

    [Fact]
    public void D2_AReadThatFailsForOneDocumentCostsOnlyThatAnswer()
    {
        OpenDocument part = _open.Add(DocumentKind.Part, PartPath);
        _open.Documents.Add(new OpenDocument(
            new object(), () => DocumentKind.Drawing, () => DrawingPath,
            () => throw new COMException("views", unchecked((int)0x80004005))));
        _reads.VisibilityFails.Add(part.Handle!);

        IReadOnlyList<string> lines = Section(RunOnPart("D2"), "D2");

        Assert.Contains("  1: part, visible unread (COMException 0x80004005)", lines);
        Assert.Contains("  2: drawing, visible true, views unread (COMException 0x80004005)", lines);
        Assert.Contains("  listed twice: none", lines);
    }

    // ---- D3 ------------------------------------------------------------------------------------

    [Fact]
    public void D3_PrintsBothEnumerationsPerSheetAndTheActiveSheetBeforeAndAfter()
    {
        Assert.Equal(
            new[]
            {
                "D3: the views of every sheet, from the document and from each sheet",
                "  run on: a six-sheet drawing, sheet 3 active",
                "  active sheet: position 1 before the run, 1 after, unchanged true; the extraction read position 1 as active",
                "  sheet 1: IDrawingDoc.GetViews 2 views, types 1, 7; ISheet.GetViews 2 views, types 1, 7",
                "  sheet 2: IDrawingDoc.GetViews 2 views, types 1, 4; ISheet.GetViews 1 view, type 4",
            },
            RunOnDrawing("D3"));

        // "Before" is read before the extraction runs, "after" once it has.
        Assert.Equal(
            new[] { nameof(IDrawingProbeReads.ActiveSheetName), nameof(IDrawingProbeReads.ActiveSheetName), nameof(IDrawingProbeReads.DocumentViewTypes) },
            _reads.Calls);
    }

    [Fact]
    public void D3_AnActiveSheetThatMovedAndADocumentEnumerationThatFailedAreBothSaid()
    {
        _reads.ActiveSheets.Clear();
        _reads.ActiveSheets.Add(SheetA);
        _reads.ActiveSheets.Add(SheetB);
        _reads.ViewTypesFailure = new COMException("views", unchecked((int)0x80004005));

        IReadOnlyList<string> lines = Section(RunOnDrawing("D3"), "D3");

        Assert.Contains(
            "  active sheet: position 1 before the run, 2 after, unchanged false; the extraction read position 1 as active",
            lines);
        Assert.Contains("  IDrawingDoc.GetViews failed: COMException 0x80004005", lines);
        Assert.Contains("  sheet 1: IDrawingDoc.GetViews unread; ISheet.GetViews 2 views, types 1, 7", lines);
    }

    [Fact]
    public void D3_ASheetTheExtractionDidNotReadIsStillPrintedFromTheDocument()
    {
        _reads.ViewTypes = new[] { new[] { 1, 7 }, new[] { 1, 4 }, new[] { 1 } };
        _reads.ActiveSheets.Clear();
        _reads.ActiveSheets.Add("PRIVATE-SHEET-UNKNOWN");

        IReadOnlyList<string> lines = Section(RunOnDrawing("D3"), "D3");

        Assert.Contains("  sheet 3: IDrawingDoc.GetViews 1 view, type 1; ISheet.GetViews not read", lines);
        Assert.Contains(
            "  active sheet: not among the sheets read before the run, not among the sheets read after, unchanged true; "
                + "the extraction read position 1 as active",
            lines);
    }

    // ---- D4 ------------------------------------------------------------------------------------

    [Fact]
    public void D4_PrintsTheDocumentsPreferencesAndEveryDimensionsPrecisionAndUnits()
    {
        Assert.Equal(
            new[]
            {
                "D4: dimension precision and units",
                "  run on: a drawing with dimensions at their own precision and at the document's",
                "  document: 24 (swDetailingLinearDimPrecision) 2, 25 (swDetailingLinearTolPrecision) 2, "
                    + "47 (swUnitsLinear) 0, 49 (swUnitsLinearDecimalPlaces) 3",
                "  ddm:0001 (sheet 1, dvw:0002): GetPrimaryPrecision2 2, GetPrimaryTolPrecision2 3, "
                    + "GetUseDocPrecision false, GetUnits 0, GetUseDocUnits true",
                "  ddm:0002 (sheet 1, dvw:0002): GetPrimaryPrecision2 unread, GetPrimaryTolPrecision2 unread, "
                    + "GetUseDocPrecision unread, GetUnits unread, GetUseDocUnits unread",
            },
            RunOnDrawing("D4"));
    }

    // ---- D5, D6, D8: against the part's own extraction ------------------------------------------

    [Fact]
    public void D5_ComparesEachDimensionsToleranceWithThePartsOwnReadingOfTheSameDimension()
    {
        Assert.Equal(
            new[]
            {
                "D5: dimension tolerances, against the part's own reading",
                "  run on: a drawing with a model-item and a reference dimension on one hole",
                $"  the part's own extraction: {PartIdText} read, 2 model dimensions, 2 faces",
                "  ddm:0001 (sheet 1, dvw:0002): Tolerance.Type 4, bilateral, upper +0.0500 mm, lower -0.0200 mm, "
                    + "fit none; reference false, driven state 1",
                "    the part: mdm:0001 Tolerance.Type 4, bilateral, upper +0.0500 mm, lower -0.0200 mm, fit none; agree true",
                "  ddm:0002 (sheet 1, dvw:0002): Tolerance.Type 0, none, upper unread, lower unread, fit H8/-; "
                    + "reference unread, driven state unread",
                "    the part: mdm:0002 Tolerance.Type 0, unread, upper unread, lower unread, fit H7/-; agree false",
            },
            RunOnDrawing("D5"));
    }

    [Fact]
    public void D5_ThePartIsExtractedOnceWithTheReviewsOptionsAndNoMeshes()
    {
        RunOnDrawing("D5", "D6", "D8");

        (string path, DumpOptions options) = Assert.Single(_modelBuilds);
        Assert.Equal(PartPath, path);
        Assert.Equal(DumpProfile.Full, options.Profile);
        Assert.Equal(MeshFormat.None, options.Meshes);
        Assert.Equal(FaceScope.Needed, options.Faces);
        Assert.Null(options.Configuration);
    }

    [Fact]
    public void D5_APartThatIsNotOpenIsSaidAndNeverOpened()
    {
        _buildModel = (path, options) => null;

        IReadOnlyList<string> lines = Section(RunOnDrawing("D5"), "D5");

        Assert.Contains(
            $"  the part's own extraction: {PartIdText} is not open, so it was not read (nothing is opened)", lines);
        Assert.Contains("    the part: not read", lines);
    }

    [Fact]
    public void D5_APartWhoseExtractionStopsIsALine()
    {
        _buildModel = (path, options) => throw new COMException("part", unchecked((int)0x80010105));

        Assert.Contains(
            $"  the part's own extraction: {PartIdText} stopped: COMException 0x80010105",
            Section(RunOnDrawing("D5"), "D5"));
    }

    [Fact]
    public void D5_ADimensionWithNoMatchOrTwoMatchesIsSaid()
    {
        _buildModel = (path, options) =>
        {
            EvidencePackage package = PartPackage();
            package.ModelDimensions![0].Name = "D9@Sketch1@PRIVATE-knuckle.SLDPRT";
            package.ModelDimensions.Add(new ModelDimension { Id = "mdm:0003", DocumentId = PartId, Name = "MyBore@Cut-Extrude1@x.SLDPRT" });
            return package;
        };

        IReadOnlyList<string> lines = Section(RunOnDrawing("D5"), "D5");

        Assert.Contains("    the part: no model dimension with the same dimension@feature", lines);
        Assert.Contains("    the part: 2 model dimensions with the same dimension@feature (mdm:0002, mdm:0003)", lines);
    }

    [Fact]
    public void D5_AtMostFivePartsAreExtractedAndTheRestAreCounted()
    {
        _build = options =>
        {
            EvidencePackage package = DrawingPackage();
            DrawingView view = package.DrawingRecords![0].Sheets[0].Views[1];
            for (int n = 1; n <= 6; n++)
            {
                string path = Folder + $@"\PRIVATE-extra-{n}.SLDPRT";
                package.Documents.Add(new Document
                {
                    DocumentId = Ids.DocumentIds.For(path), Kind = DocumentKind.Part, FileName = "x", Path = path,
                    ActiveConfiguration = string.Empty,
                });
                view.DisplayDimensions.Add(new DisplayDimensionRecord
                {
                    Id = $"ddm:01{n:00}", ViewId = view.Id,
                    AttachedFaces = new List<AttachedFace>
                    {
                        new AttachedFace { PersistRef = FaceReference, Scope = Ids.DocumentIds.For(path), Via = AttachedVia.Face },
                    },
                });
            }

            return package;
        };
        _buildModel = (path, options) => PartPackage();

        IReadOnlyList<string> lines = Section(RunOnDrawing("D6"), "D6");

        Assert.Equal(DrawingProbeRunner.MaxModelReadings, _modelBuilds.Count);
        Assert.Contains("  2 more part documents were not read: the probe reads at most 5", lines);
    }

    [Fact]
    public void D6_TiesEachAttachedFaceToThePartsFacePhaseByReferenceAndDocument()
    {
        Assert.Equal(
            new[]
            {
                "D6: annotation attachments, against the part's face phase",
                "  run on: a part drawing and an assembly drawing of one part, with a diameter, a hole callout and a GTol on known holes",
                $"  the part's own extraction: {PartIdText} read, 2 model dimensions, 2 faces",
                "  ddm:0001 (dimension, sheet 1, dvw:0002): name \"D1@Sketch1\", view \"Drawing View2\", value 10.0000 mm; "
                    + "attached faces 1 (via face 1, via edge 0), attachment gaps 0",
                $"    face 1 of {PartIdText}: the part's face phase fac:0001 (cylinder, radius 5.0000 mm)",
                "  ddm:0002 (dimension, sheet 1, dvw:0002): name \"MyBore@Cut-Extrude1\", view \"Drawing View2\", value unread; "
                    + "attached faces 2 (via face 0, via edge 2), attachment gaps 1",
                $"    face 1 of {PartIdText}: the part's face phase fac:0002 (plane)",
                $"    face 2 of {PartIdText}: no face the part's face phase described has this reference",
                "  dan:0001 (annotation type 5, sheet 1, dvw:0002): attached faces 1 (via face 1, via edge 0), attachment gaps 0",
                $"    face 1 of {PartIdText}: the part's face phase fac:0001 (cylinder, radius 5.0000 mm)",
                "  dan:0004 (annotation type 6, sheet 1, dvw:0002): attached faces 0 (via face 0, via edge 0), attachment gaps 1",
            },
            RunOnDrawing("D6"));
    }

    [Fact]
    public void D6_AFaceOfAnotherDocumentWithTheSameBytesIsNotAMatch()
    {
        _buildModel = (path, options) =>
        {
            EvidencePackage package = PartPackage();
            package.Faces[0].PersistRefScope = OtherPartId;
            return package;
        };

        Assert.Contains(
            $"    face 1 of {PartIdText}: no face the part's face phase described has this reference",
            Section(RunOnDrawing("D6"), "D6"));
    }

    [Fact]
    public void D6_WithThePartNotReadTheFacesAreNotCompared()
    {
        _buildModel = (path, options) => null;

        Assert.Contains(
            $"    face 1 of {PartIdText}: not compared (the part was not read)",
            Section(RunOnDrawing("D6"), "D6"));
    }

    [Fact]
    public void D8_PrintsEachDimensionsNameViewAndValueAndItsFullNamesShapeBesideThePartsNeverItsDocument()
    {
        Assert.Equal(
            new[]
            {
                "D8: dimension full names, against the part's",
                "  run on: the D5 drawing",
                $"  the part's own extraction: {PartIdText} read, 2 model dimensions, 2 faces",
                "  ddm:0001 (sheet 1, dvw:0002): name \"D1@Sketch1\", view \"Drawing View2\", value 10.0000 mm; "
                    + "FullName 3 segments, default D1, document suffix .SLDPRT naming the view's document true",
                "    the part: mdm:0001 FullName 3 segments, default D1, document suffix .SLDPRT naming the part true; FullName equal true",
                "  ddm:0002 (sheet 1, dvw:0002): name \"MyBore@Cut-Extrude1\", view \"Drawing View2\", value unread; "
                    + "FullName 3 segments, renamed (6 characters), document suffix .SLDPRT naming the view's document true",
                "    the part: mdm:0002 FullName 2 segments, renamed (6 characters), no document suffix; FullName equal false",
            },
            RunOnDrawing("D8"));
    }

    [Fact]
    public void D8_ADimensionWhoseNameWasNotReadSaysSo()
    {
        _build = options =>
        {
            EvidencePackage package = DrawingPackage();
            package.DrawingRecords![0].Sheets[0].Views[1].DisplayDimensions[0].Name = null;
            return package;
        };

        IReadOnlyList<string> lines = Section(RunOnDrawing("D8"), "D8");

        Assert.Contains("  ddm:0001 (sheet 1, dvw:0002): name unread, view \"Drawing View2\", value 10.0000 mm; FullName unread", lines);
        Assert.Contains("    the part: not compared (the dimension's name was not read)", lines);
    }

    [Fact]
    public void D6AndD8_ADimensionWhoseNameViewAndValueWereNotReadSaysEachUnread()
    {
        _build = options =>
        {
            EvidencePackage package = DrawingPackage();
            DrawingView view = package.DrawingRecords![0].Sheets[0].Views[1];
            view.Name = null;
            view.DisplayDimensions[0].Name = "   ";
            view.DisplayDimensions[0].Value = null;
            return package;
        };

        IReadOnlyList<string> lines = RunOnDrawing("D6", "D8");

        Assert.Contains(
            "  ddm:0001 (dimension, sheet 1, dvw:0002): name unread, view unread, value unread; "
                + "attached faces 1 (via face 1, via edge 0), attachment gaps 0",
            Section(lines, "D6"));
        Assert.Contains(
            "  ddm:0001 (sheet 1, dvw:0002): name unread, view unread, value unread; FullName unread",
            Section(lines, "D8"));
    }

    [Fact]
    public void D6AndD8_TheNameViewAndValueAreTheExtractionsWithNoReadOfTheirOwn()
    {
        RunOnDrawing("D6", "D8");

        Assert.Empty(_reads.Calls);
        Assert.Single(_builds);
        Assert.Single(_modelBuilds);
        Assert.Empty(_host.Seam.Calls);
    }

    [Fact]
    public void D6AndD8_AnAngleIsInDegreesAndANameKeepsOnlyItsDimensionAndFeature()
    {
        _build = options =>
        {
            EvidencePackage package = DrawingPackage();
            DisplayDimensionRecord dimension = package.DrawingRecords![0].Sheets[0].Views[1].DisplayDimensions[0];
            dimension.Name = "D3@Sketch1@PRIVATE-knuckle.SLDPRT@PRIVATE-spigot.SLDASM";
            dimension.Value = new IrMeasure(Math.PI / 2, "rad");
            return package;
        };

        IReadOnlyList<string> lines = RunOnDrawing("D6", "D8");

        Assert.Contains(
            "  ddm:0001 (sheet 1, dvw:0002): name \"D3@Sketch1\", view \"Drawing View2\", value 90.0000 deg; "
                + "FullName 4 segments, default D3, document suffix .SLDASM naming the view's document false",
            Section(lines, "D8"));
        Assert.Contains(
            "  ddm:0001 (dimension, sheet 1, dvw:0002): name \"D3@Sketch1\", view \"Drawing View2\", value 90.0000 deg; "
                + "attached faces 1 (via face 1, via edge 0), attachment gaps 0",
            Section(lines, "D6"));
    }

    // ---- D7, D9, D10, D11, D12 -------------------------------------------------------------------

    [Fact]
    public void D7_PrintsEachHoleCalloutsVariablesAndTextLengthsAndTheWholeTextByPosition()
    {
        Assert.Equal(
            new[]
            {
                "D7: hole callouts",
                "  run on: a counterbore callout",
                "  hole callouts in the extraction: 1",
                "  ddm:0002 (sheet 1, dvw:0002): IsHoleCallout true, variables 2 (<MOD-DIAM>, <HOLE-DEPTH>), "
                    + "GetText lengths: 1 14, 2 0, 3 2, 4 unread",
                "  GetText(0), the whole text, by position (sheet, view, dimension):",
                "    1, 2, 2: length 42",
                "    2, 1, 1: unread (COMException 0x80004005)",
            },
            RunOnDrawing("D7"));
    }

    [Fact]
    public void D7_AWholeTextWalkThatFailsOrFindsNothingIsSaid()
    {
        _reads.WholeTextsFailure = new COMException("walk", unchecked((int)0x80004005));
        Assert.Contains("  GetText(0) walk failed: COMException 0x80004005", Section(RunOnDrawing("D7"), "D7"));

        _reads.WholeTextsFailure = null;
        _reads.WholeTexts = Array.Empty<HoleCalloutText>();
        Assert.Contains(
            "  GetText(0): no dimension answered IsHoleCallout in the direct walk", Section(RunOnDrawing("D7"), "D7"));
    }

    [Fact]
    public void D9_PrintsFramesDatumsAndSurfaceFinishSlotsAsCountsAndLengths()
    {
        Assert.Equal(
            new[]
            {
                "D9: geometric tolerances, datums and surface finish",
                "  run on: a drawing with GTols, datums and surface-finish symbols",
                "  geometric tolerances 1, datums 1, surface finishes 1",
                "  dan:0001 (GTol, sheet 1, dvw:0002): frames 2 (frame 1: symbols 1, values 2; frame 2: symbols 1, values 1), "
                    + "datum identifier length 1",
                "  dan:0002 (datum, sheet 1, dvw:0002): label length 1",
                "  dan:0003 (surface finish, sheet 1, dvw:0002): symbol 3, text slots 2 (with text 1)",
            },
            RunOnDrawing("D9"));
    }

    [Fact]
    public void D10_PrintsEveryTableAndEachBillOfMaterialsRowsOpenDocuments()
    {
        Assert.Equal(
            new[]
            {
                "D10: tables",
                "  run on: a drawing with one table of each kind",
                "  tables 1, revision tables 1",
                "  dtb:0001 (sheet 2): type 2, rows 2, columns 3, readable cells 5 of 6",
                "    bill of materials row 1: model paths 2, open documents 2",
                "    bill of materials row 2: model paths unread",
                "  drv:0001 (sheet 2): revision table, rows 1, columns 2, readable cells 2 of 2",
            },
            RunOnDrawing("D10"));
    }

    [Fact]
    public void D10_AnUnresolvedPathThatIsNotOpenIsNotCounted()
    {
        _reads.OpenPaths.Clear();

        Assert.Contains(
            "    bill of materials row 1: model paths 2, open documents 1", Section(RunOnDrawing("D10"), "D10"));
    }

    [Fact]
    public void D11_PrintsEachSheetsPropertiesAndTheThreePreferences()
    {
        Assert.Equal(
            new[]
            {
                "D11: sheet properties and document settings",
                "  run on: the D1 drawing",
                "  sheet 1: GetProperties2 items 9, scale 1:2, first angle false, GetTemplateName present true",
                "  sheet 2: GetProperties2 items unread, scale unread, first angle unread, GetTemplateName present false",
                "  preferences: 13 (swDetailingDimensionStandard) 2, 47 (swUnitsLinear) 0, "
                    + "65 (swDetailingDimensionStandardName) answered true",
            },
            RunOnDrawing("D11"));
    }

    [Fact]
    public void D11_APropertiesReadThatFailsIsSaidForEverySheet()
    {
        _reads.PropertyCountsFailure = new COMException("properties", unchecked((int)0x80004005));

        IReadOnlyList<string> lines = Section(RunOnDrawing("D11"), "D11");

        Assert.Contains(
            "  sheet 1: GetProperties2 items unread (COMException 0x80004005), scale 1:2, first angle false, "
                + "GetTemplateName present true",
            lines);
    }

    [Fact]
    public void D12_PrintsEachViewsStateAndTheDetailingMode()
    {
        Assert.Equal(
            new[]
            {
                "D12: view state and detailing mode",
                "  run on: an up-to-date view, a view left out of date after a model edit, and a drawing in detailing mode",
                "  detailing mode false",
                "  dvw:0001 (sheet 1): ReferencedConfiguration present false, IsModelOutOfDate unread, IsModelLoaded unread",
                "  dvw:0002 (sheet 1): ReferencedConfiguration present true, IsModelOutOfDate false, IsModelLoaded true",
                "  dvw:0003 (sheet 2): ReferencedConfiguration present false, IsModelOutOfDate true, IsModelLoaded false",
            },
            RunOnDrawing("D12"));
    }

    [Fact]
    public void TheDrawingSectionsSayWhenTheExtractionHeldNoDrawingRecord()
    {
        _build = options =>
        {
            EvidencePackage package = DrawingPackage();
            package.DrawingRecords = null;
            return package;
        };

        foreach (string id in new[] { "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12" })
        {
            Assert.Contains("  the extraction produced no drawing record", Section(RunOnDrawing(id), id));
        }
    }

    // ---- D13 -------------------------------------------------------------------------------------

    [Fact]
    public void D13_TimesTheCandidateCheckAndComparesTheDirectoryEntryBeforeAndAfter()
    {
        Assert.Equal(
            new[]
            {
                "D13: the candidate check",
                "  run on: a reviewed part in a vault view whose same-name drawing is not cached locally",
                "  File.Exists true in 25 ms",
                "  directory entry before: present, length 123456, attributes 0x00000020; "
                    + "after: present, length 123456, attributes 0x00000020",
                "  the local copy changed across the check: false",
            },
            RunOnPart("D13"));
        Assert.Equal(new[] { "Entry", "Exists", "Entry" }, _files.Calls);
    }

    [Fact]
    public void D13_ACheckThatFetchedTheFileIsSaid()
    {
        _files.EntryBefore = ProbeFileEntry.Absent;
        _files.EntryAfter = new ProbeFileEntry(true, 5, FakeProbeFiles.Written, 0x20);

        IReadOnlyList<string> lines = Section(RunOnPart("D13"), "D13");

        Assert.Contains(
            "  directory entry before: absent; after: present, length 5, attributes 0x00000020", lines);
        Assert.Contains("  the local copy changed across the check: true", lines);
    }

    [Fact]
    public void D13_AnUnsavedDocumentAsksAboutNothing()
    {
        IReadOnlyList<string> lines = DrawingProbeRunner.Run(new[] { "D13" }, Context(DocumentKind.Part, null));

        Assert.Equal("  the document has never been saved, so no same-name drawing is asked about", lines[2]);
        Assert.Empty(_files.Calls);
    }

    [Fact]
    public void D13_ACheckThatThrowsIsALine()
    {
        _files.ExistsFailure = new IOException("vault", unchecked((int)0x80070035));

        Assert.Contains(
            "  File.Exists failed after 25 ms: IOException 0x80070035", Section(RunOnPart("D13"), "D13"));
    }

    // ---- D14 (contracts/confirmed-open.md, T077) -------------------------------------------------

    [Fact]
    public void D14_OpensTheClosedDrawingReadOnlyAndHiddenReadsItClosesItAndProvesNothingChanged()
    {
        Assert.Equal(
            new[]
            {
                "D14: the read-only open of a confirmed candidate",
                "  run on: a reviewed part whose same-name drawing is not open, then the same with the drawing open",
                "  drawing open before the probe: false",
                "  OpenDoc6: type 3, options 3 (ReadOnly 2 yes, Silent 1 yes, ViewOnly 4 no, RapidDraft 8 no, "
                    + "LoadModel 16 no), configuration \"\"",
                "  DocumentVisible: false (type 3), then true (type 3)",
                "  outcome: opened by the probe and closed",
                "  active document unchanged: during true, after true",
                "  foreground window unchanged: during true, after true",
                "  drawing as read: sheets 2, views 2, gaps 1",
                "  drawing file: size unchanged true, write time unchanged true, SHA-256 unchanged true",
                "  save flags: before 0 of 1 raised, after 0 of 1 raised; raised by the run: none",
                "  afterwards: GetOpenDocumentByName answers false; an exclusive read open succeeded",
                "  open documents: before 1, during 2, after 1",
                "  left loaded afterwards: none",
                "  seam keys gated: ISldWorks.DocumentVisible, ISldWorks.OpenDoc6, ISldWorks.CloseDoc",
                "  against confirmed-open.md: every answer as required",
            },
            RunOnPart("D14"));
    }

    [Fact]
    public void D14_ReadsTheHiddenDrawingThroughTheDrawingPhaseByItsOwnHandle()
    {
        RunOnPart("D14");

        ScopedDrawing drawing = Assert.Single(_phase.Seen);
        Assert.Equal(DrawingPath, drawing.DocumentPath);
        Assert.Same(_host.Seam.Opened, drawing.Document);
        Assert.Null(drawing.ReviewedDocumentId);
    }

    [Fact]
    public void D14_TheOpenGoesThroughTheConfirmedOpensSeamInItsOrder()
    {
        RunOnPart("D14");

        Assert.Equal(
            new[]
            {
                "OpenDocument " + DrawingPath,
                "OpenDocument " + DrawingPath,
                "DocumentVisible False 3",
                "OpenDoc6 " + DrawingPath + " 3 3 ",
                "DocumentVisible True 3",
                "OpenDocument " + DrawingPath,
                "CloseDoc " + DrawingPath,
                "OpenDocument " + DrawingPath,
            },
            _host.Seam.Calls.Select(call => call.ToString()));
    }

    [Fact]
    public void D14_ReadsTheEngineersSessionThroughTheReadOnlyGateOnly()
    {
        RunOnPart("D14");

        Assert.Equal(
            DrawingOpenProbe.ReadMembers.OrderBy(member => member, StringComparer.Ordinal),
            _readObserver.Members.OrderBy(member => member, StringComparer.Ordinal));
        Assert.Empty(_readObserver.Refusals);
        Assert.Empty(_seamObserver.Refusals);
    }

    [Fact]
    public void D14_WithTheDrawingAlreadyOpenGatesNoVisibilityOpenOrCloseKeyAndLeavesItOpen()
    {
        _host.AlreadyOpen(DrawingPath);

        Assert.Equal(
            new[]
            {
                "D14: the read-only open of a confirmed candidate",
                "  run on: a reviewed part whose same-name drawing is not open, then the same with the drawing open",
                "  drawing open before the probe: true",
                "  OpenDoc6: not called",
                "  DocumentVisible: not called",
                "  outcome: already open, read as it stood and left open",
                "  active document unchanged: during true, after true",
                "  foreground window unchanged: during true, after true",
                "  drawing as read: sheets 2, views 2, gaps 1",
                "  drawing file: size unchanged true, write time unchanged true, SHA-256 unchanged true",
                "  save flags: before 0 of 2 raised, after 0 of 2 raised; raised by the run: none",
                "  afterwards: GetOpenDocumentByName answers true; an exclusive read open succeeded",
                "  open documents: before 2, during 2, after 2",
                "  left loaded afterwards: none",
                "  seam keys gated: none",
                "  with the drawing already open, no visibility, open or close key was gated: true",
                "  against confirmed-open.md: every answer as required",
            },
            RunOnPart("D14"));
        Assert.DoesNotContain(_host.Seam.Calls, call => call.Name != "OpenDocument");
    }

    [Fact]
    public void D14_EveryWayTheOpenCanMisbehaveIsNamedAndTheModelsItLoadedAreRecorded()
    {
        _host.ActivatesTheDrawing = true;
        _host.StealsFocus = true;
        _host.RaisesTheEngineersSaveFlag = true;
        _host.LoadsModels.Add(OtherPartPath);
        _files.After = new ProbeFileState(123456, FakeProbeFiles.Written, new string('b', 64));
        _files.ExclusiveFailure = new IOException("locked", unchecked((int)0x80070020));

        IReadOnlyList<string> lines = Section(RunOnPart("D14"), "D14");

        Assert.Contains("  active document unchanged: during false, after true", lines);
        Assert.Contains("  foreground window unchanged: during false, after true", lines);
        Assert.Contains("  drawing file: size unchanged true, write time unchanged true, SHA-256 unchanged false", lines);
        Assert.Contains("  save flags: before 0 of 1 raised, after 1 of 2 raised; raised by the run: 1 (part)", lines);
        Assert.Contains(
            "  afterwards: GetOpenDocumentByName answers false; an exclusive read open failed (IOException 0x80070020)",
            lines);
        Assert.Contains("  open documents: before 1, during 3, after 2", lines);
        Assert.Contains("  left loaded afterwards: 2 (part)", lines);
        Assert.Equal(
            "  against confirmed-open.md: not as required: the active document, the foreground window, "
                + "the drawing file, the save flags, the lock",
            lines.Last());
    }

    [Fact]
    public void D14_AnOpenTheSeamRefusesIsSaidWithoutTheFileNameAndStillTakesTheAfterState()
    {
        _host.Seam.OpenAnswersNull = true;
        _host.Seam.OpenErrors = 2;

        IReadOnlyList<string> lines = Section(RunOnPart("D14"), "D14");

        Assert.Contains(
            "  outcome: refused: SOLIDWORKS could not open '<drawing>' read-only ("
                + FileLoadErrors.Describe(2, 0) + ")",
            lines);
        Assert.Contains("  drawing as read: not read (the drawing was not opened)", lines);
        Assert.Contains("  afterwards: GetOpenDocumentByName answers false; an exclusive read open succeeded", lines);
        Assert.Contains("  active document unchanged: during not taken, after true", lines);
        Assert.Contains("  against confirmed-open.md: not as required: the open, the drawing's views", lines);
    }

    [Fact]
    public void D14_ADrawingReadThatThrowsIsALineAndTheDrawingIsStillClosed()
    {
        _phase.Failure = new InvalidOperationException("sheets");

        IReadOnlyList<string> lines = Section(RunOnPart("D14"), "D14");

        Assert.Contains("  drawing as read: not read (InvalidOperationException 0x80131509)", lines);
        Assert.Contains("  outcome: opened by the probe and closed", lines);
        Assert.Equal("CloseDoc " + DrawingPath, _host.Seam.Calls[_host.Seam.Calls.Count - 2].ToString());
    }

    [Fact]
    public void D14_ACloseTheSeamRefusesIsSaidAndFailsTheClose()
    {
        _host.Seam.AfterOpenAnswer = new object();

        IReadOnlyList<string> lines = Section(RunOnPart("D14"), "D14");

        Assert.Contains(
            "  outcome: opened by the probe; the close was refused: '<drawing>' was not closed: SOLIDWORKS answers its "
                + "path with a document that is not the same document the review opened, so nothing was closed.",
            lines);
        Assert.Contains("the close", lines.Last(), StringComparison.Ordinal);
    }

    [Fact]
    public void D14_WithNoSameNameDrawingBesideTheDocumentNothingIsOpenedOrAsked()
    {
        _files.Existing.Clear();

        IReadOnlyList<string> lines = Section(RunOnPart("D14"), "D14");

        Assert.Equal("  no same-name drawing beside the document (File.Exists false), so nothing was opened", lines[2]);
        Assert.Empty(_host.Seam.Calls);
        Assert.Empty(_host.Reads);
    }

    [Fact]
    public void D14_AnUnsavedDocumentOpensNothing()
    {
        IReadOnlyList<string> lines = DrawingProbeRunner.Run(new[] { "D14" }, Context(DocumentKind.Part, " "));

        Assert.Equal("  the document has never been saved, so it has no same-name drawing; nothing was opened", lines[2]);
        Assert.Empty(_host.Seam.Calls);
    }

    [Fact]
    public void D14_OnADrawingOpensNothing()
    {
        IReadOnlyList<string> lines = RunOnDrawing("D14");

        Assert.Equal("  does not apply to a drawing, so nothing was read", lines[2]);
        Assert.Empty(_host.Seam.Calls);
    }

    [Fact]
    public void D14_AnExistenceCheckThatFailsOpensNothing()
    {
        _files.ExistsFailure = new IOException("vault", unchecked((int)0x80070035));

        IReadOnlyList<string> lines = Section(RunOnPart("D14"), "D14");

        Assert.Equal("  File.Exists failed (IOException 0x80070035), so nothing was opened", lines[2]);
        Assert.Empty(_host.Seam.Calls);
    }

    [Fact]
    public void D14_ADrawingFileThatCannotBeReadIsSaid()
    {
        _files.ReadFailure = new IOException("share", unchecked((int)0x80070020));

        Assert.Contains(
            "  drawing file: unreadable before (IOException 0x80070020)", Section(RunOnPart("D14"), "D14"));
    }

    // ---- public-repo hygiene ------------------------------------------------------------------

    [Fact]
    public void NoProbePrintsAPathANoteACellAPropertyValueOrAReferenceAndOnlyD6AndD8ADimensionsName()
    {
        _open.Add(DocumentKind.Part, PartPath);
        _open.Add(DocumentKind.Drawing, DrawingPath, PartPath, OtherPartPath);
        _host.Seam.AfterOpenAnswer = new object();
        _files.ExclusiveFailure = new IOException(DrawingPath + " is locked", unchecked((int)0x80070020));

        var lines = new List<string>(DrawingProbeRunner.Run(
            DrawingProbeCatalog.AllIds, Context(DocumentKind.Drawing, DrawingPath)));
        lines.AddRange(DrawingProbeRunner.Run(DrawingProbeCatalog.AllIds, Context(DocumentKind.Part, PartPath)));
        _build = options => throw new InvalidOperationException(DrawingPath + " failed");
        lines.AddRange(DrawingProbeRunner.Run(DrawingProbeCatalog.AllIds, Context(DocumentKind.Drawing, DrawingPath)));

        foreach (string forbidden in Forbidden())
        {
            Assert.DoesNotContain(lines, line => line.IndexOf(forbidden, StringComparison.Ordinal) >= 0);
        }

        // D6 and D8 print a dimension's dimension@feature and its view's name on the dimension's own
        // line, so the engineer can find a named callout; no other line carries either.
        string section = string.Empty;
        var named = new List<(string Section, string Line)>();
        foreach (string line in lines)
        {
            if (!line.StartsWith(" ", StringComparison.Ordinal))
            {
                section = line.Substring(0, line.IndexOf(':'));
            }
            else if (NamedOnDimensionLines().Any(name => line.IndexOf(name, StringComparison.Ordinal) >= 0))
            {
                named.Add((section, line));
            }
        }

        Assert.Contains(named, row => row.Section == "D6");
        Assert.Contains(named, row => row.Section == "D8");
        Assert.All(named, row =>
        {
            Assert.Contains(row.Section, new[] { "D6", "D8" });
            Assert.StartsWith("  ddm:", row.Line, StringComparison.Ordinal);
        });
    }

    // ---- the report ---------------------------------------------------------------------------

    [Fact]
    public void TheReportOpensWithTheRunsVersionKindAndProbes()
    {
        Assert.Equal(
            new[]
            {
                "swreview-extract probe drawings (feature 011, contracts/probes.md)",
                "generated: 2026-09-23T10:15:00Z",
                "SOLIDWORKS: 32.5.0.48",
                "document: drawing",
                "probes: D1, D11",
            },
            DrawingProbeReport.Header(
                new DateTimeOffset(2026, 9, 23, 12, 15, 0, TimeSpan.FromHours(2)), "32.5.0.48", DocumentKind.Drawing,
                new[] { "D1", "D11" }));

        Assert.Equal(
            new[] { "SOLIDWORKS: unread", "document: unread", "probes: none" },
            DrawingProbeReport.Header(DateTimeOffset.UtcNow, null, null, Array.Empty<string>()).Skip(2));
    }

    [Fact]
    public void TheReportIsWrittenInTheFolderAndNeverOverwritesOne()
    {
        var at = new DateTimeOffset(2026, 9, 23, 10, 15, 0, TimeSpan.Zero);
        var first = new DrawingProbeReport();
        first.Add("first");
        var second = new DrawingProbeReport();
        second.Add("second");

        string firstPath = first.Write(_directory, at);
        string secondPath = second.Write(_directory, at);

        Assert.Equal(Path.Combine(_directory, "drawings-probe-20260923-101500.txt"), firstPath);
        Assert.Equal(Path.Combine(_directory, "drawings-probe-20260923-101500-2.txt"), secondPath);
        Assert.Equal("first\n", File.ReadAllText(firstPath));
        Assert.Equal("second\n", File.ReadAllText(secondPath));
    }

    // ---- the text rules -----------------------------------------------------------------------

    [Fact]
    public void AFailureIsItsTypeAndResultNeverItsMessage()
    {
        string text = ProbeText.Failure(new COMException(@"C:\Fictional\PRIVATE.SLDPRT failed", unchecked((int)0x80004005)));

        Assert.Equal("COMException 0x80004005", text);
    }

    [Fact]
    public void RedactReplacesThePathTheFileNameAndTheStemInAnyCase()
    {
        string text = ProbeText.Redact(
            @"'PRIVATE-knuckle.slddrw' at C:\FICTIONAL\PRIVATE-folder\PRIVATE-knuckle.SLDDRW, stem private-KNUCKLE",
            DrawingPath);

        Assert.Equal("'<drawing>' at <drawing>, stem <drawing>", text);
        Assert.Equal("nothing to replace", ProbeText.Redact("nothing to replace", null, " "));
        Assert.Equal(string.Empty, ProbeText.Redact(null!, DrawingPath));
    }

    [Theory]
    [InlineData(@"C:\a\b<c>.SLDPRT", "b<c>.SLDPRT", ".SLDPRT", "part")]
    [InlineData("MyBore@Cut|Extrude1", "MyBore@Cut|Extrude1", "", "other")]
    [InlineData("D1@Sketch1@x\"y\".sldasm", "D1@Sketch1@x\"y\".sldasm", ".sldasm", "assembly")]
    [InlineData("folder/.hidden", ".hidden", "", "other")]
    public void ThePathHelpersNeverThrowOnACharacterTheFileSystemRefuses(
        string text, string fileName, string extension, string kind)
    {
        // A dimension's full name is asked the same questions as a path, and .NET Framework's Path
        // throws on '<', '|' or '"'; the probe must print an answer, not stop.
        Assert.Equal(fileName, ProbeText.FileName(text));
        Assert.Equal(extension, ProbeText.Extension(text));
        Assert.Equal(kind, ProbeText.KindByExtension(text));
    }

    [Theory]
    [InlineData(0.00005, "m", "+0.0500 mm")]
    [InlineData(-0.02, "mm", "-0.0200 mm")]
    [InlineData(0.001, "in", "+0.0254 mm")]
    [InlineData(0.5, "deg", "+0.5000 deg")]
    [InlineData(1.0, "rad", "+57.2958 deg")]
    public void ALimitIsPrintedInMillimetresOrDegrees(double value, string unit, string expected)
    {
        Assert.Equal(expected, ProbeText.Limit(new IrMeasure(value, unit)));
    }

    [Theory]
    [InlineData(0.01, "m", "10.0000 mm")]
    [InlineData(10.0, "mm", "10.0000 mm")]
    [InlineData(0.5, "in", "12.7000 mm")]
    [InlineData(-0.002, "m", "-2.0000 mm")]
    [InlineData(90.0, "deg", "90.0000 deg")]
    [InlineData(Math.PI / 2, "rad", "90.0000 deg")]
    public void ADimensionsValueIsPrintedInMillimetresOrDegreesSignedOnlyWhenNegative(
        double value, string unit, string expected)
    {
        Assert.Equal(expected, ProbeText.Nominal(new IrMeasure(value, unit)));
    }

    [Theory]
    [InlineData("D1@Sketch1@PRIVATE-knuckle.SLDPRT", "D1@Sketch1")]
    [InlineData("MyBore@Cut-Extrude1", "MyBore@Cut-Extrude1")]
    [InlineData("RD1@Drawing View1", "RD1@Drawing View1")]
    [InlineData("D2@Sketch3@Sub@PRIVATE-spigot.SLDASM", "D2@Sketch3")]
    [InlineData("D1@PRIVATE-knuckle.sldprt", "D1")]
    [InlineData("D1", "D1")]
    [InlineData("PRIVATE-knuckle.SLDDRW", null)]
    [InlineData("@Sketch1", null)]
    [InlineData("   ", null)]
    [InlineData(null, null)]
    public void ADimensionsNameIsItsDimensionAndFeatureNeverADocument(string? fullName, string? expected)
    {
        Assert.Equal(expected, ProbeText.DimensionName(fullName));
    }

    [Fact]
    public void AQuotedNameIsInDoubleQuotesAndAnUnreadOneSaysSo()
    {
        Assert.Equal("\"Drawing View1\"", ProbeText.Quoted("Drawing View1"));
        Assert.Equal("unread", ProbeText.Quoted(null));
        Assert.Equal("unread", ProbeText.Nominal(null));
    }

    [Fact]
    public void AnUnreadValueSaysSo()
    {
        Assert.Equal("unread", ProbeText.Limit(null));
        Assert.Equal("unread", ProbeText.Bool(null));
        Assert.Equal("unread", ProbeText.Int(null));
        Assert.Equal("true", ProbeText.Bool(true));
        Assert.Equal("7", ProbeText.Int(7));
    }

    // ---- the file seam, on real files ------------------------------------------------------------

    [Fact]
    public void TheFileSeamReadsSizeWriteTimeAndSha256WithoutChangingTheFile()
    {
        Directory.CreateDirectory(_directory);
        string path = Path.Combine(_directory, "fictional.SLDDRW");
        byte[] bytes = { 1, 2, 3, 4, 5 };
        File.WriteAllBytes(path, bytes);
        DateTime written = File.GetLastWriteTimeUtc(path);
        string expected;
        using (var sha = SHA256.Create())
        {
            expected = string.Concat(sha.ComputeHash(bytes).Select(b => b.ToString("x2")));
        }

        var files = new ProbeFiles();
        ProbeFileState state = files.Read(path);

        Assert.Equal(5, state.Length);
        Assert.Equal(written, state.LastWriteUtc);
        Assert.Equal(expected, state.Sha256);
        Assert.Equal(written, File.GetLastWriteTimeUtc(path));
        Assert.True(files.Exists(path));
        Assert.Equal(new ProbeFileEntry(true, 5, written, (int)File.GetAttributes(path)), files.Entry(path));
    }

    [Fact]
    public void TheFileSeamSaysWhenAFileIsAbsentOrHeld()
    {
        Directory.CreateDirectory(_directory);
        string path = Path.Combine(_directory, "fictional.SLDDRW");
        var files = new ProbeFiles();

        Assert.False(files.Exists(path));
        Assert.Equal(ProbeFileEntry.Absent, files.Entry(path));
        Assert.Equal(ProbeFileEntry.Absent, files.Entry(Path.Combine(_directory, "missing", "x.SLDDRW")));
        Assert.Throws<FileNotFoundException>(() => files.Read(path));

        File.WriteAllBytes(path, new byte[] { 9 });
        files.OpenExclusive(path);
        using (new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        {
            Assert.Throws<IOException>(() => files.OpenExclusive(path));
        }

        using (new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
        {
            Assert.Throws<IOException>(() => files.Read(path));
        }
    }

    // ---- helpers --------------------------------------------------------------------------------

    private DrawingProbeContext Context(DocumentKind kind, string? path) => new DrawingProbeContext(
        kind,
        path,
        _document,
        options =>
        {
            _builds.Add(options);
            return _build(options);
        },
        (modelPath, options) =>
        {
            _modelBuilds.Add((modelPath, options));
            return _buildModel(modelPath, options);
        },
        _open,
        _reads,
        _files,
        new DrawingOpenProbeSeam(
            _host,
            _phase,
            new SwGate(new CircuitBreaker(), ReadOnlyCallGuard.Instance) { Observer = _readObserver },
            _seamObserver),
        _clock.Read);

    private IReadOnlyList<string> RunOnDrawing(params string[] ids) =>
        DrawingProbeRunner.Run(ids, Context(DocumentKind.Drawing, DrawingPath));

    private IReadOnlyList<string> RunOnPart(params string[] ids) =>
        DrawingProbeRunner.Run(ids, Context(DocumentKind.Part, PartPath));

    /// <summary>The lines of one probe's section: its header and every indented line after it.</summary>
    private static IReadOnlyList<string> Section(IReadOnlyList<string> lines, string id)
    {
        int start = lines.ToList().FindIndex(line => line.StartsWith(id + ": ", StringComparison.Ordinal));
        Assert.True(start >= 0, $"no section {id}");
        var section = new List<string> { lines[start] };
        for (int i = start + 1; i < lines.Count && lines[i].StartsWith(" ", StringComparison.Ordinal); i++)
        {
            section.Add(lines[i]);
        }

        return section;
    }

    private static DrawingProbeSettings Settings(params string[] options)
    {
        var args = new List<string> { "probe", "drawings" };
        args.AddRange(options);
        return Program.DrawingsProbeSettingsFrom(
            CommandLine.Parse(args.ToArray(), 2, Program.KnownOptions(Program.DrawingsProbeOptionNames)));
    }
}
