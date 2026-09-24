using System;
using System.IO;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using Xunit;
using IrCapture = SwReview.Extractor.Ir.Capture;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T071. <c>interference</c> and <c>capture</c> add to the package <c>dump</c> wrote rather
/// than producing one of their own, so their results can name its components
/// (contracts/cli.md).
///
/// Two things have to hold or the package quietly lies: a second interference run must not
/// leave the first run's rows behind - their ids restart at <c>int:0001</c>, and a stale
/// "nothing found" row reads as current - and a second capture must not overwrite the first.
/// </summary>
public class PackageAppenderTests : IDisposable
{
    private readonly string _directory;

    public PackageAppenderTests()
    {
        _directory = Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_directory);
    }

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }

    [Fact]
    public void Load_NoPackage_SaysToRunDumpFirst()
    {
        FileNotFoundException error = Assert.Throws<FileNotFoundException>(
            () => PackageAppender.Load(_directory));

        Assert.Contains("dump", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void SaveAndLoad_RoundTripsThroughTheIrSerializer()
    {
        var package = NewPackage();
        package.Interferences.Add(Interference("int:0001", "Default"));

        PackageAppender.Save(_directory, package);
        EvidencePackage reloaded = PackageAppender.Load(_directory);

        Assert.Equal("int:0001", Assert.Single(reloaded.Interferences).Id);
        Assert.Equal(
            Path.Combine(_directory, PackageWriter.PackageFileName),
            PackageAppender.PathIn(_directory));
    }

    [Fact]
    public void Merge_AddsTheRunsRowsAndGaps()
    {
        var package = NewPackage();

        PackageAppender.Merge(
            package,
            "Default",
            new[] { Interference("int:0001", "Default"), Interference("int:0002", "Default") },
            new[] { new Gap { Kind = GapKind.Unsupported, EntityKind = "interference", Reason = "why" } });

        Assert.Equal(2, package.Interferences.Count);
        Assert.Single(package.Gaps);
    }

    [Fact]
    public void Merge_SecondRunReplacesTheFirstRunsRowsForThatConfiguration()
    {
        var package = NewPackage();
        PackageAppender.Merge(
            package,
            "Default",
            new[] { Interference("int:0001", "Default"), Interference("int:0002", "Default") },
            new Gap[0]);

        // A re-run that found only one interference must not leave the other row behind.
        PackageAppender.Merge(
            package, "Default", new[] { Interference("int:0001", "Default") }, new Gap[0]);

        Assert.Equal(new[] { "int:0001" }, package.Interferences.Select(i => i.Id));
    }

    [Fact]
    public void Merge_LeavesOtherConfigurationsAlone()
    {
        var package = NewPackage();
        PackageAppender.Merge(
            package, "Machined", new[] { Interference("int:0001", "Machined") }, new Gap[0]);
        PackageAppender.Merge(
            package, "Default", new[] { Interference("int:0001", "Default") }, new Gap[0]);

        Assert.Equal(
            new[] { "Machined", "Default" },
            package.Interferences.Select(i => i.Configuration));
    }

    [Fact]
    public void Merge_GapsAccumulateAcrossRuns()
    {
        // A gap is a record of something that did not happen; a later run does not undo it.
        var package = NewPackage();
        var gap = new Gap { Kind = GapKind.ToolError, EntityKind = "interference", Reason = "one" };

        PackageAppender.Merge(package, "Default", new IrInterference[0], new[] { gap });
        PackageAppender.Merge(package, "Default", new IrInterference[0], new[] { gap });

        Assert.Equal(2, package.Gaps.Count);
    }

    [Fact]
    public void Merge_Capture_IsPurelyAdditive()
    {
        var package = NewPackage();

        PackageAppender.Merge(package, Capture("cap:0001"), null);
        PackageAppender.Merge(package, Capture("cap:0002"), null);

        Assert.Equal(new[] { "cap:0001", "cap:0002" }, package.Captures.Select(c => c.Id));
    }

    [Fact]
    public void Merge_FailedCapture_RecordsOnlyTheGap()
    {
        var package = NewPackage();

        PackageAppender.Merge(
            package, null, new Gap { Kind = GapKind.ToolError, EntityKind = "capture", Reason = "no" });

        Assert.Empty(package.Captures);
        Assert.Single(package.Gaps);
    }

    [Fact]
    public void CaptureIds_ContinuePastWhatThePackageAlreadyHolds()
    {
        var package = NewPackage();
        package.Captures.Add(Capture("cap:0001"));
        package.Captures.Add(Capture("cap:0007"));

        Assert.Equal("cap:0008", PackageAppender.CaptureIds(package).Next());
    }

    [Fact]
    public void CaptureIds_EmptyPackageStartsAtOne()
    {
        Assert.Equal("cap:0001", PackageAppender.CaptureIds(NewPackage()).Next());
    }

    [Fact]
    public void AppendInterferences_WritesTheFileBack()
    {
        PackageAppender.Save(_directory, NewPackage());

        string path = PackageAppender.AppendInterferences(
            _directory, "Default", new[] { Interference("int:0001", "Default") }, new Gap[0]);

        Assert.Equal(PackageAppender.PathIn(_directory), path);
        Assert.Single(PackageAppender.Load(_directory).Interferences);
    }

    [Fact]
    public void Merge_NullPackage_Throws()
    {
        Assert.Throws<ArgumentNullException>(
            () => PackageAppender.Merge(null!, "Default", new IrInterference[0], new Gap[0]));
        Assert.Throws<ArgumentNullException>(() => PackageAppender.CaptureIds(null!));
        Assert.Throws<ArgumentException>(() => PackageAppender.PathIn("  "));
        Assert.Throws<ArgumentNullException>(() => PackageAppender.Merge(null!, SuppressRun(1)));
        Assert.Throws<ArgumentNullException>(
            () => PackageAppender.Merge(NewPackage(), (SuppressTestRun)null!));
    }

    [Fact]
    public void AppendSuppressTest_WritesTheRunBackAndReplacesAnEarlierOne()
    {
        // T055. A package holds one run, and a second suppress-test is a complete re-test of
        // the same document: keeping the first alongside it would leave the reviewer reading
        // rows about a model that has since been tested again.
        PackageAppender.Save(_directory, NewPackage());

        PackageAppender.AppendSuppressTest(_directory, SuppressRun(1));
        string path = PackageAppender.AppendSuppressTest(_directory, SuppressRun(2));

        Assert.Equal(PackageAppender.PathIn(_directory), path);
        SuppressTestRun stored = PackageAppender.Load(_directory).RmsSuppressTest!;
        Assert.Equal(2, stored.FeaturesPresent);
        Assert.Equal(2, stored.Rows.Count);
        Assert.Equal(new[] { "feat:0001", "feat:0002" }, stored.Rows.Select(row => row.FeatureId).ToArray());
    }

    [Fact]
    public void AppendSuppressTest_LeavesTheRestOfThePackageAlone()
    {
        var package = NewPackage();
        package.Interferences.Add(Interference("int:0001", "Default"));
        PackageAppender.Save(_directory, package);

        PackageAppender.AppendSuppressTest(_directory, SuppressRun(1));

        EvidencePackage reloaded = PackageAppender.Load(_directory);
        Assert.Single(reloaded.Interferences);
        Assert.NotNull(reloaded.RmsSuppressTest);
    }

    /// <summary>A run over <paramref name="features"/> planned features, all clean.</summary>
    private static SuppressTestRun SuppressRun(int features)
    {
        var run = new SuppressTestRun
        {
            DocumentId = "doc:0002",
            Configuration = "Default",
            Group = "01_Detail",
            PlanFile = @"C:\out\suppress-plan.json",
            RunAt = DateTimeOffset.Now,
            Acknowledged = true,
            BaselineWhatsWrongCount = 0,
            Limit = 50,
            TimeoutSeconds = 900,
            FeaturesPresent = features,
            RestoreVerified = true,
        };

        for (int i = 1; i <= features; i++)
        {
            run.Rows.Add(new SuppressTestRow
            {
                FeatureId = "feat:000" + i.ToString(System.Globalization.CultureInfo.InvariantCulture),
                PersistRef = "cmVm",
                PersistRefScope = "doc:0002",
                Name = "Fillet" + i.ToString(System.Globalization.CultureInfo.InvariantCulture),
                Outcome = SuppressTestOutcome.Ok,
                WhatsWrongCount = 0,
                ElapsedMs = 12,
            });
        }

        return run;
    }

    // ---- MergeDrawing (feature 011 T071, contracts/confirmed-open.md section 2) --------------

    private static readonly string NewDrawingId = Ids.DocumentIds.For(Fakes.ConfirmedDrawingPackage.HousingDrawingPath);

    private static (DrawingRecord Record, Document Document, ManifestEntry Entry, Gap Gap) ConfirmedDrawing() =>
    (
        Fakes.ConfirmedDrawingPackage.Record(NewDrawingId, 2),
        new Document
        {
            DocumentId = NewDrawingId,
            Kind = DocumentKind.Drawing,
            FileName = "housing.SLDDRW",
            Path = Fakes.ConfirmedDrawingPackage.HousingDrawingPath,
            ActiveConfiguration = string.Empty,
        },
        new ManifestEntry
        {
            DocumentId = NewDrawingId,
            VaultPath = Fakes.ConfirmedDrawingPackage.HousingDrawingPath,
            Configuration = string.Empty,
            ExportMethod = ExportMethod.Native,
        },
        new Gap
        {
            Kind = GapKind.NotExtracted,
            EntityKind = "drawing_referenced_document",
            EntityId = "dvw:0002",
            Reason = "references 'C:\\Fictional\\other\\unrelated.SLDPRT', which is not part of this review",
        });

    [Fact]
    public void MergeDrawing_AppendsTheRecordItsDocumentItsManifestEntryItsIdAndItsGapsAndRemovesTheCandidate()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.Build();
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, new[] { drawing.Gap },
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);

        Assert.Same(drawing.Record, package.DrawingRecords!.Last());
        Assert.True(drawing.Record.OpenedByReview);
        Assert.Same(drawing.Document, package.Documents.Last());
        Assert.Same(drawing.Entry, package.Manifest.Entries.Last());
        Assert.Equal(NewDrawingId, package.Design.DrawingDocumentIds.Last());
        Assert.Same(drawing.Gap, package.Gaps.Last());
        Assert.Equal(
            new[] { Fakes.ConfirmedDrawingPackage.PinId },
            package.DrawingCandidates!.Select(candidate => candidate.DocumentId));

        // And the package still reads back through the IR serializer.
        PackageAppender.Save(_directory, package);
        Assert.True(PackageAppender.Load(_directory).DrawingRecords!.Last().OpenedByReview);
    }

    [Fact]
    public void MergeDrawing_OfADrawingThatWasAlreadyOpen_OmitsTheOpenedFlagRatherThanWritingFalse()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.Build();
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: false);

        Assert.Null(drawing.Record.OpenedByReview);
        Assert.DoesNotContain("opened_by_review", PackageSerializer.Serialize(package), StringComparison.Ordinal);
    }

    [Fact]
    public void MergeDrawing_OfTheLastCandidate_LeavesNoCandidateMember()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.Build();
        package.DrawingCandidates!.RemoveAt(1);
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);

        Assert.Null(package.DrawingCandidates);
    }

    [Fact]
    public void MergeDrawing_ASecondMergeOfTheSameDrawingIsRefusedAndChangesNothing()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.Build();
        var drawing = ConfirmedDrawing();
        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);
        string before = PackageSerializer.Serialize(package);
        var again = ConfirmedDrawing();

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(() => PackageAppender.MergeDrawing(
            package, again.Record, again.Document, again.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.PinId, openedByReview: true));

        Assert.Contains("already", refusal.Message, StringComparison.Ordinal);
        Assert.Equal(before, PackageSerializer.Serialize(package));
    }

    [Fact]
    public void MergeDrawing_IntoAPackageWithNoDrawingRecordYet_StartsTheList()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.Build(drawings: 0);
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);

        Assert.Same(drawing.Record, Assert.Single(package.DrawingRecords!));
    }

    // ---- the dump's drawing gap after a confirmed read (feature 011 T078, 2026-09-23) --------
    //
    // A review whose extraction read no drawing carries the dump's standing gap ("No open drawing
    // shows this design, so no drawing was read natively...") and a `drawing` phase row
    // `skipped`. Once a confirmed drawing is merged the sentence is false; the row is not - the
    // dump did skip - so the gap is reworded to say so and to name the later read, and the row is
    // left exactly as the dump wrote it (contracts/confirmed-open.md section 2).

    /// <summary>Every sentence <see cref="PackageWriter"/> writes its standing drawing gap with.</summary>
    public static TheoryData<string> StandingDrawingGaps() => new TheoryData<string>
    {
        PackageWriter.NoOpenDrawingGapSentence,
        PackageWriter.OpenDrawingsNotListedGapSentence,
        PackageWriter.ProfileSkippedDrawingGapSentence(DumpProfile.Full),
    };

    [Theory]
    [MemberData(nameof(StandingDrawingGaps))]
    public void MergeDrawing_AfterAnExtractionThatReadNoDrawing_RewordsTheStandingGapInPlace(string standing)
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.BuildWithNoDrawingRead(standing);
        int index = package.Gaps.FindIndex(PackageWriter.IsDrawingPhaseGap);
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);

        // Still one drawing-phase gap, where it was, of the same kind: reworded, never duplicated.
        Gap gap = Assert.Single(package.Gaps, PackageWriter.IsDrawingPhaseGap);
        Assert.Equal(index, package.Gaps.IndexOf(gap));
        Assert.Equal(GapKind.Unsupported, gap.Kind);
        Assert.Equal("drawing", gap.EntityKind);
        Assert.Null(gap.EntityId);

        // The claim that no drawing was read, and the advice to extract again, are gone.
        Assert.NotEqual(standing, gap.Reason);
        Assert.DoesNotContain("No open drawing shows this design", gap.Reason, StringComparison.Ordinal);
        Assert.DoesNotContain("extract again", gap.Reason, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("PDF ingest", gap.Reason, StringComparison.Ordinal);

        // What stays true about the dump, and the later read, named.
        Assert.Equal(
            "The extraction read no drawing natively: its drawing phase did not run. Read afterwards, "
            + "when the engineer confirmed the candidate question: 'housing.SLDDRW' (opened read-only "
            + "by the review).",
            gap.Reason);

        // The other phases' gaps are untouched.
        Assert.Equal(
            new[] { "feature_tree_unavailable", "drawing", "equations" },
            package.Gaps.Select(row => row.EntityKind));
    }

    [Fact]
    public void MergeDrawing_AfterAnExtractionThatReadNoDrawing_LeavesTheSkippedPhaseRowAsTheDumpWroteIt()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.BuildWithNoDrawingRead(
            PackageWriter.NoOpenDrawingGapSentence);
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);

        // History is not rewritten: the dump did skip, so the row says so, with no elapsed time.
        Assert.Equal(new[] { "cutlist", "drawing", "hole" }, package.Extractor.Phases.Select(row => row.Name));
        DumpPhase row = package.Extractor.Phases.Single(phase => phase.Name == "drawing");
        Assert.Equal(DumpPhaseStatus.Skipped, row.Status);
        Assert.Null(row.ElapsedMs);
    }

    [Fact]
    public void MergeDrawing_OfADrawingAlreadyOpen_RewordsTheGapToSayItWasReadAsItStood()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.BuildWithNoDrawingRead(
            PackageWriter.NoOpenDrawingGapSentence);
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: false);

        Assert.EndsWith(
            "confirmed the candidate question: 'housing.SLDDRW' (already open, read as it stood).",
            Assert.Single(package.Gaps, PackageWriter.IsDrawingPhaseGap).Reason,
            StringComparison.Ordinal);
    }

    [Fact]
    public void TwoConfirmedMerges_NameBothLaterReadsInTheOrderTheyWereMerged()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.BuildWithNoDrawingRead(
            PackageWriter.NoOpenDrawingGapSentence);
        var housing = ConfirmedDrawing();
        PackageAppender.MergeDrawing(
            package, housing.Record, housing.Document, housing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);

        string pinId = Ids.DocumentIds.For(Fakes.ConfirmedDrawingPackage.PinDrawingPath);
        var pinDocument = new Document
        {
            DocumentId = pinId,
            Kind = DocumentKind.Drawing,
            FileName = "pin.SLDDRW",
            Path = Fakes.ConfirmedDrawingPackage.PinDrawingPath,
            ActiveConfiguration = string.Empty,
        };
        var pinEntry = new ManifestEntry
        {
            DocumentId = pinId,
            VaultPath = Fakes.ConfirmedDrawingPackage.PinDrawingPath,
            Configuration = string.Empty,
            ExportMethod = ExportMethod.Native,
        };
        PackageAppender.MergeDrawing(
            package, Fakes.ConfirmedDrawingPackage.Record(pinId, 3), pinDocument, pinEntry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.PinId, openedByReview: false);

        Assert.Equal(
            "The extraction read no drawing natively: its drawing phase did not run. Read afterwards, "
            + "when the engineer confirmed the candidate question: 'housing.SLDDRW' (opened read-only "
            + "by the review) and 'pin.SLDDRW' (already open, read as it stood).",
            Assert.Single(package.Gaps, PackageWriter.IsDrawingPhaseGap).Reason);
        Assert.Null(package.DrawingCandidates);
    }

    [Fact]
    public void MergeDrawing_IntoAPackageWhoseDrawingPhaseRan_WritesNoDrawingPhaseGap()
    {
        // The dump read the root's drawing, so it wrote no standing gap and there is nothing to
        // reword: the merge adds the read's own gaps and nothing else.
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.Build();
        var drawing = ConfirmedDrawing();

        PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, new[] { drawing.Gap },
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true);

        Assert.DoesNotContain(package.Gaps, PackageWriter.IsDrawingPhaseGap);
        Assert.Same(drawing.Gap, Assert.Single(package.Gaps));
    }

    [Fact]
    public void ARefusedMerge_LeavesTheStandingGapAsItWas()
    {
        EvidencePackage package = Fakes.ConfirmedDrawingPackage.BuildWithNoDrawingRead(
            PackageWriter.NoOpenDrawingGapSentence);
        var drawing = ConfirmedDrawing();
        package.Documents.Add(drawing.Document);

        Assert.Throws<InvalidOperationException>(() => PackageAppender.MergeDrawing(
            package, drawing.Record, drawing.Document, drawing.Entry, Array.Empty<Gap>(),
            Fakes.ConfirmedDrawingPackage.HousingId, openedByReview: true));

        Assert.Equal(
            PackageWriter.NoOpenDrawingGapSentence,
            Assert.Single(package.Gaps, PackageWriter.IsDrawingPhaseGap).Reason);
    }

    [Theory]
    [InlineData(GapKind.NotExtracted, "drawing", null)]
    [InlineData(GapKind.Unsupported, "drawing_sheet", null)]
    [InlineData(GapKind.Unsupported, "drawing", "doc:0123456789ab")]
    public void OnlyTheDumpsStandingGapIsTheDrawingPhaseGap(GapKind kind, string entityKind, string? entityId)
    {
        // The rule is structural - the gap Finish writes, and no other - so a drawing gap of
        // another kind, another entity kind or naming an entity is never reworded.
        Assert.False(PackageWriter.IsDrawingPhaseGap(
            new Gap { Kind = kind, EntityKind = entityKind, EntityId = entityId, Reason = "x" }));
        Assert.True(PackageWriter.IsDrawingPhaseGap(
            new Gap { Kind = GapKind.Unsupported, EntityKind = "drawing", EntityId = null, Reason = "x" }));
    }

    /// <summary>
    /// Feature 011 T088 (2026-09-23): the cross-language pin. The backend's tests play this host
    /// - `reviewer/tests/unit/test_confirmed_drawing_read.py`'s fake host rewords the standing gap
    /// on a read, and its `test_the_fake_host_words_the_stale_gap_as_the_extractor_does` asserts
    /// these same three literals - so neither the extractor's words nor the fake's can change
    /// without the other side failing.
    /// </summary>
    [Fact]
    public void TheStandingAndRewordedSentencesAreTheOnesTheBackendsFakeHostPlays()
    {
        Assert.Equal(
            "No open drawing shows this design, so no drawing was read natively. Open its drawing "
            + "in SOLIDWORKS and extract again to include it.",
            PackageWriter.NoOpenDrawingGapSentence);
        Assert.Equal(
            "The extraction read no drawing natively: its drawing phase did not run. Read afterwards, "
            + "when the engineer confirmed the candidate question: 'FICT-KALO-8001.SLDDRW' (opened "
            + "read-only by the review).",
            PackageWriter.DrawingsReadAfterExtractionGapSentence(new[] { ("FICT-KALO-8001.SLDDRW", true) }));
        Assert.Equal(
            "The extraction read no drawing natively: its drawing phase did not run. Read afterwards, "
            + "when the engineer confirmed the candidate question: 'FICT-KALO-8001.SLDDRW' (opened "
            + "read-only by the review), 'FICT-KALO-8002.SLDDRW' (already open, read as it stood) and "
            + "'FICT-KALO-8003.SLDDRW' (opened read-only by the review).",
            PackageWriter.DrawingsReadAfterExtractionGapSentence(new[]
            {
                ("FICT-KALO-8001.SLDDRW", true),
                ("FICT-KALO-8002.SLDDRW", false),
                ("FICT-KALO-8003.SLDDRW", true),
            }));
    }

    private static EvidencePackage NewPackage() => new EvidencePackage
    {
        PackageId = Guid.NewGuid(),
        CreatedAt = DateTimeOffset.Now,
    };

    private static IrInterference Interference(string id, string configuration) => new IrInterference
    {
        Id = id,
        Configuration = configuration,
        ComponentIds = { "cmp:0001", "cmp:0002" },
        Volume = new Volume(1.0e-9, VolumeUnit.M3),
        GroupKey = "cmp:0001|cmp:0002",
    };

    private static IrCapture Capture(string id) => new IrCapture
    {
        Id = id,
        PersistRef = "cmVm",
        File = "captures/" + id.Replace(':', '-') + ".png",
        View = "iso",
    };
}
