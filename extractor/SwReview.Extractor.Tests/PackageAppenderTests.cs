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
