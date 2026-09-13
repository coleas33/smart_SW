using System;
using System.IO;
using System.Linq;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Tests.Fakes;
using Xunit;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T069 and T070 against the contract itself. The rows the runner and the capture service
/// produce are not hand-written fixtures in this test - they come out of the real code and
/// are then validated against contracts/ir.schema.json, which is the same file the Python
/// reviewer's models are generated from (T105).
///
/// This is what catches the shapes a unit test looking at C# properties cannot: a status
/// spelled the wrong way, a volume unit the enum allows but the schema does not, a capture
/// file that does not end in .png, or the "exactly two component ids" rule broken by a
/// failed pair.
/// </summary>
public class InterferenceContractTests : IDisposable
{
    private readonly string _directory;

    public InterferenceContractTests()
    {
        _directory = Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }

    [Fact]
    public void RunnerAndCaptureOutput_SatisfyTheIrContract()
    {
        EvidencePackage package = IrSerializerTests.BuildSamplePackage();
        package.Interferences.Clear();
        package.Captures.Clear();

        InterferenceRunResult run = RunWithEveryStatus();
        PackageAppender.Merge(package, "Default", run.Interferences, run.Gaps);

        CaptureResult capture = new CaptureService(new FakeCaptureView()).Capture(
            "cmVm", null, CaptureViews.Iso, _directory, "evidence for the finding");
        PackageAppender.Merge(package, capture.Capture, capture.Gap);

        // Every status, a volume, a gap and a capture, straight out of the real code.
        Assert.Equal(
            new[] { InterferenceStatus.Failed, InterferenceStatus.Computed, InterferenceStatus.Truncated },
            package.Interferences.Select(i => i.Status));
        Assert.Single(package.Captures);

        IrContract.AssertValid(PackageSerializer.Serialize(package));
    }

    [Fact]
    public void FailedWholeAssemblyRow_SatisfiesTheTwoComponentIdRule()
    {
        EvidencePackage package = IrSerializerTests.BuildSamplePackage();
        package.Interferences.Clear();

        var source = new FakeInterferenceSource(
            new InvalidOperationException("this document is not an assembly"));
        InterferenceRunResult run = new InterferenceRunner(source).Run(
            "Default",
            new[] { InterferencePair.WholeAssembly() },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);

        PackageAppender.Merge(package, "Default", run.Interferences, run.Gaps);

        IrInterference row = Assert.Single(package.Interferences);
        Assert.Equal(InterferenceStatus.Failed, row.Status);
        Assert.Equal(
            new[] { InterferenceRunner.WholeAssemblyComponentId, InterferenceRunner.WholeAssemblyComponentId },
            row.ComponentIds);

        IrContract.AssertValid(PackageSerializer.Serialize(package));
    }

    [Fact]
    public void RunnerOutput_SurvivesASerializationRoundTrip()
    {
        EvidencePackage package = IrSerializerTests.BuildSamplePackage();
        package.Interferences.Clear();
        package.Captures.Clear();

        InterferenceRunResult run = RunWithEveryStatus();
        PackageAppender.Merge(package, "Default", run.Interferences, run.Gaps);

        EvidencePackage restored = PackageSerializer.Deserialize(PackageSerializer.Serialize(package));

        Assert.Equal(
            run.Interferences.Select(i => i.Status),
            restored.Interferences.Select(i => i.Status));
        Assert.Equal(
            VolumeUnit.M3,
            restored.Interferences.Single(i => i.Status == InterferenceStatus.Computed).Volume!.Unit);

        // "unknown" has to survive: a truncated row's volume is null, not zero.
        Assert.Null(restored.Interferences.Single(i => i.Status == InterferenceStatus.Truncated).Volume);
    }

    /// <summary>A run that produces one computed, one truncated and one failed row.</summary>
    private static InterferenceRunResult RunWithEveryStatus()
    {
        var housing = new FakeComponent("cmp:0001");
        var plate = new FakeComponent("cmp:0002");
        var screw = new FakeComponent("cmp:0011", "pat:screws");

        var detector = new FakeInterferenceDetector(scope =>
        {
            if (scope.Contains(plate))
            {
                throw new InvalidOperationException("this pair is broken");
            }

            return new IInterferenceResult[]
            {
                new FakeInterferenceResult(3.2e-9, housing, screw) { IsFastener = true },
            };
        });

        return new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[]
            {
                // Fails: the fake refuses any scope holding the plate. A failed row does not
                // count against --truncate-after, so the next pair still computes.
                InterferencePair.Of(housing.AsPairMember(), plate.AsPairMember()),
                InterferencePair.Of(housing.AsPairMember(), screw.AsPairMember()),

                // By now one row has been computed, so this one is truncated.
                InterferencePair.Of(plate.AsPairMember(), screw.AsPairMember()),
            },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent,
            truncateAfter: 1);
    }
}
