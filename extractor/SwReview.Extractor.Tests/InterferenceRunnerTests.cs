using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Tests.Fakes;
using Xunit;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T069. The orchestration around SOLIDWORKS interference detection: what a failed pair
/// becomes, how rows are grouped, and the volume unit that has not been verified yet.
///
/// Every one of these is a Principle I promise. A pair that could not be computed must not
/// read as a clean pair, and a number whose unit is a guess must say so.
/// </summary>
public class InterferenceRunnerTests
{
    private static readonly FakeComponent Housing = new FakeComponent("cmp:0001");
    private static readonly FakeComponent Plate = new FakeComponent("cmp:0002");
    private static readonly FakeComponent ScrewA = new FakeComponent("cmp:0011", "pat:screws");
    private static readonly FakeComponent ScrewB = new FakeComponent("cmp:0012", "pat:screws");

    // ---- Done() ------------------------------------------------------------------

    [Fact]
    public void Run_CallsDoneExactlyOnce()
    {
        var detector = new FakeInterferenceDetector();
        RunWholeAssembly(detector);

        Assert.Equal(1, detector.DoneCount);
    }

    [Fact]
    public void Run_CallsDoneEvenWhenAPairFails()
    {
        var detector = new FakeInterferenceDetector(
            scope => throw new InvalidOperationException("detection blew up"));

        RunWholeAssembly(detector);

        Assert.Equal(1, detector.DoneCount);
    }

    [Fact]
    public void Run_DoneFailing_IsAGapNotAnException()
    {
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, Plate) })
        {
            ThrowOnDone = new InvalidOperationException("Done refused"),
        };

        InterferenceRunResult run = RunWholeAssembly(detector);

        Assert.Single(run.Interferences);
        Assert.Contains(run.Gaps, g => g.Error != null && g.Error.Contains("Done refused"));
    }

    // ---- failure -----------------------------------------------------------------

    [Fact]
    public void Run_PairThatThrows_BecomesAFailedRowAndAGap()
    {
        var detector = new FakeInterferenceDetector(
            scope => throw new InvalidOperationException("GetInterferenceCount failed"));

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.Of(Housing.AsPairMember(), Plate.AsPairMember()) },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);

        IrInterference row = Assert.Single(run.Interferences);
        Assert.Equal(InterferenceStatus.Failed, row.Status);
        Assert.Contains("GetInterferenceCount failed", row.Error!, StringComparison.Ordinal);
        Assert.Equal(new[] { "cmp:0001", "cmp:0002" }, row.ComponentIds);
        Assert.Null(row.Volume);

        Gap gap = Assert.Single(run.Gaps);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Equal(InterferenceRunner.GapEntityKind, gap.EntityKind);
        Assert.Contains("cmp:0001", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Run_OneFailedPairDoesNotStopTheRest()
    {
        var detector = new FakeInterferenceDetector(scope =>
        {
            // The failing scope is the one that holds the plate.
            if (scope.Contains(Plate))
            {
                throw new InvalidOperationException("this pair is broken");
            }

            return new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, ScrewA) };
        });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[]
            {
                InterferencePair.Of(Housing.AsPairMember(), Plate.AsPairMember()),
                InterferencePair.Of(Housing.AsPairMember(), ScrewA.AsPairMember()),
            },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);

        Assert.Equal(
            new[] { InterferenceStatus.Failed, InterferenceStatus.Computed },
            run.Interferences.Select(i => i.Status));
    }

    [Fact]
    public void Run_ManagerThatCannotBeOpened_FailsEveryPair()
    {
        var source = new FakeInterferenceSource(
            new InvalidOperationException("this document is not an assembly"));

        InterferenceRunResult run = new InterferenceRunner(source).Run(
            "Default",
            new[]
            {
                InterferencePair.Of(Housing.AsPairMember(), Plate.AsPairMember()),
                InterferencePair.Of(Housing.AsPairMember(), ScrewA.AsPairMember()),
            },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);

        Assert.Equal(2, run.Interferences.Count);
        Assert.All(run.Interferences, row => Assert.Equal(InterferenceStatus.Failed, row.Status));
        Assert.Single(run.Gaps);
    }

    [Fact]
    public void Run_SettingsThatCannotBeApplied_ComputeNothing()
    {
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, Plate) })
        {
            ThrowOnConfigure = new InvalidOperationException("the manager refused the settings"),
        };

        InterferenceRunResult run = RunWholeAssembly(detector);

        // Results computed under settings that were never applied would be reported against
        // the settings the IR echoes, which would be a lie.
        IrInterference row = Assert.Single(run.Interferences);
        Assert.Equal(InterferenceStatus.Failed, row.Status);
        Assert.Single(run.Gaps);
        Assert.Equal(1, detector.DoneCount);
    }

    [Fact]
    public void Run_ReadingComponentsThatThrows_BecomesAFailedRow()
    {
        var broken = new FakeInterferenceResult(1e-9, Housing, Plate)
        {
            ThrowOnComponents = new COMException("the component pointer is stale"),
        };

        InterferenceRunResult run = RunWholeAssembly(
            new FakeInterferenceDetector(scope => new IInterferenceResult[] { broken }));

        Assert.Equal(InterferenceStatus.Failed, Assert.Single(run.Interferences).Status);
        Assert.Single(run.Gaps);
    }

    [Fact]
    public void Run_CircuitOpen_PropagatesInsteadOfBecomingAGapPerPair()
    {
        var detector = new FakeInterferenceDetector(
            scope => throw new CircuitOpenError("SOLIDWORKS stopped answering"));

        Assert.Throws<CircuitOpenError>(() =>
            new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
                "Default",
                new[] { InterferencePair.Of(Housing.AsPairMember(), Plate.AsPairMember()) },
                new InterferenceRunSettings(),
                InterferenceSettingsTests.AnyComponent));

        // Even then, Done() ran.
        Assert.Equal(1, detector.DoneCount);
    }

    [Fact]
    public void Run_ComponentsTheDumpNeverSaw_AreAGapNotAGuess()
    {
        var stranger = new FakeComponent("cmp:9999");
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, stranger) });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.WholeAssembly() },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.Lookup(Housing));

        Assert.Empty(run.Interferences);
        Gap gap = Assert.Single(run.Gaps);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
    }

    [Fact]
    public void Run_UnmappedComponentInANamedPair_FallsBackToThePairsOwnIds()
    {
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[]
            {
                // A lightweight subassembly answers with something the tree never indexed.
                new FakeInterferenceResult(1e-9, new FakeComponent("cmp:7777")),
            });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.Of(Housing.AsPairMember(), Plate.AsPairMember()) },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.Lookup(Housing, Plate));

        IrInterference row = Assert.Single(run.Interferences);
        Assert.Equal(new[] { "cmp:0001", "cmp:0002" }, row.ComponentIds);
    }

    // ---- group_key ---------------------------------------------------------------

    [Fact]
    public void Run_GroupKeyUsesPatternIdsWhereTheyExist()
    {
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, ScrewA) });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.Of(Housing.AsPairMember(), ScrewA.AsPairMember()) },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);

        Assert.Equal("cmp:0001|pat:screws", Assert.Single(run.Interferences).GroupKey);
    }

    [Fact]
    public void Run_EveryInstanceOfOnePatternSharesAGroupKey()
    {
        var detector = new FakeInterferenceDetector(scope => new IInterferenceResult[]
        {
            new FakeInterferenceResult(1e-9, Housing, ScrewA),
            new FakeInterferenceResult(1e-9, Housing, ScrewB),
        });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.WholeAssembly() },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent,
            id => id == "cmp:0011" || id == "cmp:0012" ? "pat:screws" : null);

        Assert.Equal(2, run.Interferences.Count);
        Assert.Equal(run.Interferences[0].GroupKey, run.Interferences[1].GroupKey);
        Assert.Equal("cmp:0001|pat:screws", run.Interferences[0].GroupKey);
    }

    [Fact]
    public void Run_GroupKeyDoesNotDependOnTheOrderSolidWorksListedTheComponents()
    {
        var forwards = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, Plate) });
        var backwards = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Plate, Housing) });

        Assert.Equal(
            Assert.Single(RunWholeAssembly(forwards).Interferences).GroupKey,
            Assert.Single(RunWholeAssembly(backwards).Interferences).GroupKey);
    }

    [Fact]
    public void Run_GroupKeyIsStableAcrossRuns()
    {
        string First() => Assert.Single(RunWholeAssembly(new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, Plate) }))
            .Interferences).GroupKey;

        Assert.Equal(First(), First());
    }

    [Fact]
    public void Run_UnpatternedPairGroupsOnItsComponentIdsSorted()
    {
        InterferenceRunResult run = RunWholeAssembly(new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Plate, Housing) }));

        Assert.Equal("cmp:0001|cmp:0002", Assert.Single(run.Interferences).GroupKey);
    }

    // ---- the volume unit ---------------------------------------------------------

    [Fact]
    public void Run_RecordsVolumeInTheAssumedUnit()
    {
        InterferenceRunResult run = RunWholeAssembly(new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(3.2e-9, Housing, Plate) }));

        Ir.Volume volume = Assert.Single(run.Interferences).Volume!;
        Assert.Equal(3.2e-9, volume.Value);
        Assert.Equal(VolumeUnit.M3, volume.Unit);
    }

    [Fact]
    public void Run_RecordsTheUnverifiedUnitGapOncePerRun()
    {
        // Until the workstation check in T069 flips VolumeUnitVerified, every volume in the
        // package is an assumption and says so exactly once.
        Assert.False(InterferenceRunner.VolumeUnitVerified);

        InterferenceRunResult run = RunWholeAssembly(new FakeInterferenceDetector(
            scope => new IInterferenceResult[]
            {
                new FakeInterferenceResult(1e-9, Housing, Plate),
                new FakeInterferenceResult(2e-9, Housing, ScrewA),
            }));

        Gap gap = Assert.Single(
            run.Gaps, g => g.EntityKind == InterferenceRunner.VolumeUnitGapEntityKind);
        Assert.Equal(GapKind.Unsupported, gap.Kind);
        Assert.Equal(InterferenceRunner.VolumeUnitGapReason, gap.Reason);
    }

    [Fact]
    public void Run_NoVolumeRecorded_NoUnitGap()
    {
        InterferenceRunResult run = RunWholeAssembly(new FakeInterferenceDetector());

        Assert.Empty(run.Interferences);
        Assert.DoesNotContain(
            run.Gaps, g => g.EntityKind == InterferenceRunner.VolumeUnitGapEntityKind);
    }

    // ---- ids, scope and configuration --------------------------------------------

    [Fact]
    public void Run_AllocatesIdsInRunOrder()
    {
        InterferenceRunResult run = RunWholeAssembly(new FakeInterferenceDetector(
            scope => new IInterferenceResult[]
            {
                new FakeInterferenceResult(1e-9, Housing, Plate),
                new FakeInterferenceResult(2e-9, Housing, ScrewA),
            }));

        Assert.Equal(new[] { "int:0001", "int:0002" }, run.Interferences.Select(i => i.Id));
    }

    [Fact]
    public void Run_EchoesTheConfigurationOntoEveryRow()
    {
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, Housing, Plate) });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Machined",
            new[] { InterferencePair.WholeAssembly() },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);

        Assert.Equal("Machined", Assert.Single(run.Interferences).Configuration);
    }

    [Fact]
    public void Run_WholeAssembly_ScopesToNothing()
    {
        var detector = new FakeInterferenceDetector();
        RunWholeAssembly(detector);

        Assert.Empty(Assert.Single(detector.Scopes));
    }

    [Fact]
    public void Run_NamedPair_ScopesToBothComponents()
    {
        var detector = new FakeInterferenceDetector();

        new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.Of(Housing.AsPairMember(), Plate.AsPairMember()) },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);

        IReadOnlyList<object> scope = Assert.Single(detector.Scopes);
        Assert.Equal(2, scope.Count);
        Assert.Contains(Housing, scope);
        Assert.Contains(Plate, scope);
    }

    [Fact]
    public void Run_RecordsIsFastenerAndIsPossible()
    {
        InterferenceRunResult run = RunWholeAssembly(new FakeInterferenceDetector(
            scope => new IInterferenceResult[]
            {
                new FakeInterferenceResult(0.0, Housing, ScrewA)
                {
                    IsFastener = true,
                    IsPossibleInterference = true,
                },
            }));

        IrInterference row = Assert.Single(run.Interferences);
        Assert.True(row.IsFastener);
        Assert.True(row.IsPossible);
    }

    [Fact]
    public void Run_NullArguments_Throw()
    {
        var runner = new InterferenceRunner(new FakeInterferenceSource(new FakeInterferenceDetector()));
        var pairs = new[] { InterferencePair.WholeAssembly() };

        Assert.Throws<ArgumentNullException>(() =>
            runner.Run("Default", null!, new InterferenceRunSettings(), _ => null));
        Assert.Throws<ArgumentNullException>(() =>
            runner.Run("Default", pairs, null!, _ => null));
        Assert.Throws<ArgumentNullException>(() =>
            runner.Run("Default", pairs, new InterferenceRunSettings(), null!));
        Assert.Throws<ArgumentNullException>(() => new InterferenceRunner(null!));
    }

    private static InterferenceRunResult RunWholeAssembly(FakeInterferenceDetector detector) =>
        new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.WholeAssembly() },
            new InterferenceRunSettings(),
            InterferenceSettingsTests.AnyComponent);
}
