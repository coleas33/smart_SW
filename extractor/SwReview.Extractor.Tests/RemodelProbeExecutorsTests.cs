using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The fifteen probe bodies (tasks.md T033 to T039): every executor's verified, refuted and
/// unresolved cases scripted against <see cref="FakeRemodelProbeHost"/>, a throw recorded as
/// unresolved, the pure decision logic exhaustively, and the whole-catalog round trip.
/// </summary>
public class RemodelProbeExecutorsTests
{
    private static RemodelProbeContext Context(
        FakeRemodelProbeHost host,
        string outputDirectory = @"C:\out",
        Func<CancellationToken, Task>? watchdogDeadline = null)
    {
        var part = new RemodelProbePart(new object(), @"C:\out\probe-part\remodel-probe.SLDPRT", Array.Empty<object>());
        return new RemodelProbeContext(
            part, new SwGate(), "32.5.0.48", host, outputDirectory, watchdogDeadline: watchdogDeadline);
    }

    /// <summary>A watchdog deadline that never fires: for a run whose reorders all return or throw.</summary>
    private static Task NeverFires(CancellationToken _) => new TaskCompletionSource<bool>().Task;

    private static RemodelProbeRecord Run(string probeId, RemodelProbeContext context) =>
        RemodelProbeRunner.Run(probeId, context, RemodelProbeExecutors.ByProbeId);

    // ---- the catalog and the registry agree --------------------------------------------

    [Fact]
    public void ByProbeId_HasExactlyTheFifteenCatalogIds()
    {
        Assert.Equal(
            RemodelProbeCatalog.AllIds.OrderBy(id => id, StringComparer.Ordinal),
            RemodelProbeExecutors.ByProbeId.Keys.OrderBy(id => id, StringComparer.Ordinal));
    }

    // ---- PROBE-1: the watchdog itself is RemodelProbeWatchdogTests'; here, the wiring ----
    //
    // Every attempt is scripted by the flag it sees and watched by "attempt k parked", never by a
    // clock (013 T136, 004 T171): an attempt that parks is blocked the moment it parks, and one
    // that returns or throws has a deadline that never fires.

    private static RemodelProbeRecord RunProbe1(FakeRemodelProbeHost host, ParkingReorder reorder) =>
        Run("PROBE-1", Context(host, watchdogDeadline: reorder.Deadlines()));

    [Fact]
    public void Probe1_NeitherTryBlocks_SetsTheFlagThenClearsIt_AndRecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost();
        using var reorder = new ParkingReorder(host, _ => ReorderAttempt.Returns);

        RemodelProbeRecord record = RunProbe1(host, reorder);

        Assert.Equal(new[] { true, false }, host.CommandInProgressHistory);
        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
    }

    [Fact]
    public void Probe1_TheFlagSetTryRunsFirst_SoABoxTheFlagClearTryLeavesCannotSpoilIt()
    {
        var host = new FakeRemodelProbeHost();
        using var reorder = new ParkingReorder(host, _ => ReorderAttempt.Returns);

        RunProbe1(host, reorder);

        Assert.Equal(new[] { true, false }, reorder.FlagSeenByAttempt);
    }

    [Fact]
    public void Probe1_HostThrows_RecordsUnresolvedWithTheHostsOwnMessage()
    {
        var host = new FakeRemodelProbeHost();
        using var reorder = new ParkingReorder(host, _ => ReorderAttempt.Throws);

        RemodelProbeRecord record = RunProbe1(host, reorder);

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.Equal(ParkingReorder.HostMessage, record.RawResult[RemodelProbeRunner.ErrorKey]);
    }

    [Fact]
    public void Probe1_BlocksOnlyWithTheFlagClear_RecordsVerified_UnderTheLedgersOwnKeys()
    {
        var host = new FakeRemodelProbeHost();
        using var reorder = new ParkingReorder(host, flag => flag ? ReorderAttempt.Returns : ReorderAttempt.Parks);

        RemodelProbeRecord record = RunProbe1(host, reorder);

        Assert.Equal(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal("True", record.RawResult["blocked_with_flag_clear"]);
        Assert.Equal("False", record.RawResult["blocked_with_flag_set"]);
        Assert.Equal("n/a (blocked)", record.RawResult["returned_with_flag_clear"]);
        Assert.Equal("True", record.RawResult["returned_with_flag_set"]);
    }

    [Fact]
    public void Probe1_BothTriesBlock_RecordsRefuted()
    {
        var host = new FakeRemodelProbeHost();
        using var reorder = new ParkingReorder(host, _ => ReorderAttempt.Parks);

        Assert.Equal(RemodelProbeVerdict.Refuted, RunProbe1(host, reorder).Verdict);
    }

    [Fact]
    public void Probe1_BlocksOnlyWithTheFlagSet_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost();
        using var reorder = new ParkingReorder(host, flag => flag ? ReorderAttempt.Parks : ReorderAttempt.Returns);

        Assert.Equal(RemodelProbeVerdict.Unresolved, RunProbe1(host, reorder).Verdict);
    }

    [Fact]
    public void Probe1_AfterTheFakeIsDisposed_NoThreadIsLeftParked()
    {
        var host = new FakeRemodelProbeHost();
        var reorder = new ParkingReorder(host, _ => ReorderAttempt.Parks);

        RunProbe1(host, reorder);
        Assert.Equal(2, reorder.ParkedNow);

        reorder.Dispose();

        Assert.True(
            SpinWait.SpinUntil(() => reorder.ParkedNow == 0, TimeSpan.FromSeconds(30)),
            $"{reorder.ParkedNow} attempt(s) still parked after Dispose released them.");
    }

    // ---- PROBE-2: equation units --------------------------------------------------------

    [Fact]
    public void Probe2_ValueMatchesDocumentUnits_RecordsVerified()
    {
        var equations = new FakeEquationManager();
        equations.Equations.Add("\"w\" = 120");
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations, GetEquationValueImpl = (_, _) => 120.0 };

        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-2", Context(host)).Verdict);
    }

    [Fact]
    public void Probe2_ValueMatchesMetres_RecordsRefuted()
    {
        var equations = new FakeEquationManager();
        equations.Equations.Add("\"w\" = 120");
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations, GetEquationValueImpl = (_, _) => 0.12 };

        Assert.Equal(RemodelProbeVerdict.Refuted, Run("PROBE-2", Context(host)).Verdict);
    }

    [Fact]
    public void Probe2_ValueMatchesNeitherUnit_RecordsUnresolved()
    {
        var equations = new FakeEquationManager();
        equations.Equations.Add("\"w\" = 120");
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations, GetEquationValueImpl = (_, _) => 42.0 };

        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-2", Context(host)).Verdict);
    }

    [Fact]
    public void Probe2_EquationNotFound_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => new FakeEquationManager() };

        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-2", Context(host)).Verdict);
    }

    [Fact]
    public void Probe2_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => throw new InvalidOperationException("boom") };

        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-2", Context(host)).Verdict);
    }

    // ---- PROBE-3: reorder ---------------------------------------------------------------

    [Theory]
    [InlineData(true, true, false, true, RemodelProbeVerdict.Verified)]
    [InlineData(true, true, true, true, RemodelProbeVerdict.Refuted)]
    [InlineData(true, true, false, false, RemodelProbeVerdict.Refuted)]
    [InlineData(false, false, false, true, RemodelProbeVerdict.Unresolved)]
    [InlineData(false, true, false, true, RemodelProbeVerdict.Refuted)]
    public void Probe3Logic_Decide_MatchesExpectedVerdict(
        bool legalReturned, bool legalOrderUnchanged, bool illegalReturned, bool illegalOrderUnchanged, RemodelProbeVerdict expected)
    {
        (RemodelProbeVerdict verdict, string reason) =
            RemodelProbe3Logic.Decide(legalReturned, legalOrderUnchanged, illegalReturned, illegalOrderUnchanged);

        Assert.Equal(expected, verdict);
        Assert.False(string.IsNullOrWhiteSpace(reason));
    }

    [Fact]
    public void Probe3_LegalNoOpWorksAndIllegalRefusesCleanly_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost { GetFeatureNamesImpl = _ => new[] { "Boss-Extrude1", "Cut-Extrude1", "Shell1" } };
        host.ReorderFeatureImpl = (part, move, target, location) => move == "Cut-Extrude1";

        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-3", Context(host)).Verdict);
    }

    [Fact]
    public void Probe3_IllegalReorderReturnsTrue_RecordsRefuted()
    {
        var host = new FakeRemodelProbeHost
        {
            GetFeatureNamesImpl = _ => new[] { "Boss-Extrude1", "Cut-Extrude1", "Shell1" },
            ReorderFeatureImpl = (_, _, _, _) => true,
        };

        Assert.Equal(RemodelProbeVerdict.Refuted, Run("PROBE-3", Context(host)).Verdict);
    }

    [Fact]
    public void Probe3_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetFeatureNamesImpl = _ => throw new InvalidOperationException("tree unreadable") };

        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-3", Context(host)).Verdict);
    }

    // ---- PROBE-4: contiguous folders -----------------------------------------------------

    private static int FolderStepIndexForTests() => RemodelProbePartRecipe.Default().Steps
        .Select((step, index) => (step, index))
        .Single(pair => pair.step.Kind == RemodelProbeFeatureKind.Folder)
        .index;

    private static RemodelProbePart PartWithFolderStep(bool built)
    {
        int count = RemodelProbePartRecipe.Default().Steps.Count;
        var features = new object[count];
        for (int i = 0; i < count; i++)
        {
            features[i] = new object();
        }

        if (!built)
        {
            features[FolderStepIndexForTests()] = null!;
        }

        return new RemodelProbePart(new object(), @"C:\out\probe-part\remodel-probe.SLDPRT", features);
    }

    private static RemodelProbeContext ContextWithPart(RemodelProbePart part, FakeRemodelProbeHost host) =>
        new RemodelProbeContext(part, new SwGate(), "32.5.0.48", host, @"C:\out");

    [Theory]
    [InlineData(true, false, RemodelProbeVerdict.Verified)]
    [InlineData(false, false, RemodelProbeVerdict.Refuted)]
    [InlineData(true, true, RemodelProbeVerdict.Refuted)]
    public void Probe4Logic_Decide(bool contiguousBuilt, bool nonContiguousBuilt, RemodelProbeVerdict expected)
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe4Logic.Decide(contiguousBuilt, nonContiguousBuilt);
        Assert.Equal(expected, verdict);
    }

    [Fact]
    public void Probe4_ContiguousBuiltNonContiguousDidNot_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost { TryInsertFeatureTreeFolderImpl = (_, _) => null };
        RemodelProbeRecord record = Run("PROBE-4", ContextWithPart(PartWithFolderStep(built: true), host));
        Assert.Equal(RemodelProbeVerdict.Verified, record.Verdict);
    }

    [Fact]
    public void Probe4_ContiguousDidNotBuild_RecordsRefuted()
    {
        var host = new FakeRemodelProbeHost { TryInsertFeatureTreeFolderImpl = (_, _) => null };
        RemodelProbeRecord record = Run("PROBE-4", ContextWithPart(PartWithFolderStep(built: false), host));
        Assert.Equal(RemodelProbeVerdict.Refuted, record.Verdict);
    }

    [Fact]
    public void Probe4_NonContiguousAlsoBuilds_RecordsRefuted()
    {
        var host = new FakeRemodelProbeHost { TryInsertFeatureTreeFolderImpl = (_, _) => new object() };
        RemodelProbeRecord record = Run("PROBE-4", ContextWithPart(PartWithFolderStep(built: true), host));
        Assert.Equal(RemodelProbeVerdict.Refuted, record.Verdict);
    }

    [Fact]
    public void Probe4_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost
        {
            TryInsertFeatureTreeFolderImpl = (_, _) => throw new InvalidOperationException("boom"),
        };
        RemodelProbeRecord record = Run("PROBE-4", ContextWithPart(PartWithFolderStep(built: true), host));
        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
    }

    // ---- PROBE-5: the three folder optimisations -----------------------------------------

    [Fact]
    public void Probe5_AllThreeAnswerWithoutThrowing_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost();
        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-5", Context(host)).Verdict);
    }

    [Fact]
    public void Probe5_OneCallThrows_RecordsUnresolvedAndKeepsTheOtherTwoAnswers()
    {
        var host = new FakeRemodelProbeHost { MoveToFolderImpl = (_, _, _, _) => throw new InvalidOperationException("boom") };
        RemodelProbeRecord record = Run("PROBE-5", Context(host));

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.Contains("error", record.RawResult["move_to_folder"]);
        Assert.DoesNotContain("error", record.RawResult["reorder_to_folder"]);
        Assert.DoesNotContain("error", record.RawResult["make_sub_feature"]);
    }

    // ---- PROBE-6: Add3 ---------------------------------------------------------------------

    [Theory]
    [InlineData(0, 0, 1, RemodelProbeVerdict.Verified)]
    [InlineData(0, -1, 0, RemodelProbeVerdict.Refuted)]
    [InlineData(0, 5, 0, RemodelProbeVerdict.Unresolved)]
    [InlineData(0, -1, 1, RemodelProbeVerdict.Unresolved)]
    public void Probe6Logic_Decide(int before, int addResult, int after, RemodelProbeVerdict expected)
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe6Logic.Decide(before, addResult, after);
        Assert.Equal(expected, verdict);
    }

    [Fact]
    public void Probe6_Add3WorksProperly_RecordsVerified()
    {
        var equations = new FakeEquationManager { Add3Answer = 0, Add3Adds = true };
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations };
        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-6", Context(host)).Verdict);
    }

    [Fact]
    public void Probe6_Add3ReturnsMinusOneAndAddsNothing_RecordsRefuted()
    {
        var equations = new FakeEquationManager { Add3Answer = -1, Add3Adds = false };
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations };
        Assert.Equal(RemodelProbeVerdict.Refuted, Run("PROBE-6", Context(host)).Verdict);
    }

    [Fact]
    public void Probe6_MismatchedResultAndCount_RecordsUnresolved()
    {
        var equations = new FakeEquationManager { Add3Answer = 3, Add3Adds = false };
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-6", Context(host)).Verdict);
    }

    [Fact]
    public void Probe6_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-6", Context(host)).Verdict);
    }

    // ---- PROBE-7: set_Equation -------------------------------------------------------------

    [Fact]
    public void Probe7_SetEquationWrites_RecordsVerified()
    {
        var equations = new FakeEquationManager { Add3Answer = 0, Add3Adds = true, SetEquationWrites = true };
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations };
        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-7", Context(host)).Verdict);
    }

    [Fact]
    public void Probe7_SetEquationDoesNotWrite_RecordsRefuted()
    {
        var equations = new FakeEquationManager { Add3Answer = 0, Add3Adds = true, SetEquationWrites = false };
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations };
        Assert.Equal(RemodelProbeVerdict.Refuted, Run("PROBE-7", Context(host)).Verdict);
    }

    [Fact]
    public void Probe7_NeitherAddWorks_RecordsUnresolved()
    {
        var equations = new FakeEquationManager { Add3Answer = -1, Add3Adds = false, Add2Answer = -1, Add2Adds = false };
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => equations };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-7", Context(host)).Verdict);
    }

    [Fact]
    public void Probe7_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetEquationManagerImpl = _ => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-7", Context(host)).Verdict);
    }

    // ---- PROBE-8: tolerance calibration -----------------------------------------------------

    [Fact]
    public void Probe8_BothShapesMeasureCleanly_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost();
        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-8", Context(host)).Verdict);
    }

    [Fact]
    public void Probe8_RecordsAttainedErrorsPerQuantity()
    {
        var host = new FakeRemodelProbeHost();
        RemodelProbeRecord record = Run("PROBE-8", Context(host));

        Assert.Contains("box_volume_rel_error", record.RawResult.Keys);
        Assert.Contains("box_area_rel_error", record.RawResult.Keys);
        Assert.Contains("box_com_normalized_abs_error", record.RawResult.Keys);
        Assert.Contains("box_moments_max_rel_error", record.RawResult.Keys);
        Assert.Contains("cylinder_volume_rel_error", record.RawResult.Keys);
    }

    [Fact]
    public void Probe8_RecalculateFails_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { MeasureMassPropertiesImpl = _ => new FakeMassProperty { RecalculateAnswer = false } };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-8", Context(host)).Verdict);
    }

    [Fact]
    public void Probe8_CreateMassPropertyReturnsNothing_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { MeasureMassPropertiesImpl = _ => null };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-8", Context(host)).Verdict);
    }

    [Fact]
    public void Probe8_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { BuildAnalyticSolidImpl = (_, _) => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-8", Context(host)).Verdict);
    }

    [Fact]
    public void Probe8_ClosesAndDeletesEachAnalyticPart()
    {
        var closed = new List<string>();
        var host = new FakeRemodelProbeHost { ClosePartImpl = part => closed.Add(part.Path) };
        Run("PROBE-8", Context(host));

        Assert.Equal(2, closed.Count);
        Assert.Contains(closed, path => path.Contains("probe-8-box"));
        Assert.Contains(closed, path => path.Contains("probe-8-cylinder"));
    }

    // ---- PROBE-9: force a rebuild error ------------------------------------------------------

    [Theory]
    [InlineData(false, 0, "empty", RemodelProbeVerdict.Unresolved)]
    [InlineData(true, 0, "empty", RemodelProbeVerdict.Unresolved)]
    [InlineData(true, 3, "feature_names", RemodelProbeVerdict.Verified)]
    [InlineData(true, 3, "feature_objects", RemodelProbeVerdict.Verified)]
    [InlineData(true, 3, "unknown:Int32", RemodelProbeVerdict.Unresolved)]
    public void Probe9Logic_Decide(bool suppressReturned, int count, string elementKind, RemodelProbeVerdict expected)
    {
        var whatsWrong = new RemodelWhatsWrongReading(count, true, elementKind);
        (RemodelProbeVerdict verdict, _) = RemodelProbe9Logic.Decide(suppressReturned, whatsWrong);
        Assert.Equal(expected, verdict);
    }

    [Fact]
    public void Probe9Logic_Decide_NullReading_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => RemodelProbe9Logic.Decide(true, null!));
    }

    [Fact]
    public void Probe9_WhatsWrongHoldsFeatureNames_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost { ReadWhatsWrongImpl = _ => new RemodelWhatsWrongReading(2, true, "feature_names") };
        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-9", Context(host)).Verdict);
    }

    [Fact]
    public void Probe9_SuppressReturnsFalse_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { SetFeatureSuppressionImpl = (_, _, _) => false };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-9", Context(host)).Verdict);
    }

    [Fact]
    public void Probe9_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { SetFeatureSuppressionImpl = (_, _, _) => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-9", Context(host)).Verdict);
    }

    // ---- PROBE-10: the ___EndTag___ marker ------------------------------------------------

    [Theory]
    [InlineData(false, null, "Folder1", "Renamed", RemodelProbeVerdict.Verified)]
    [InlineData(true, null, "Folder1", "Renamed", RemodelProbeVerdict.Unresolved)]
    [InlineData(true, "Folder1___EndTag___", "Folder1", "Renamed", RemodelProbeVerdict.Verified)]
    [InlineData(true, "Renamed___EndTag___", "Folder1", "Renamed", RemodelProbeVerdict.Refuted)]
    [InlineData(true, "Something___EndTag___Else", "Folder1", "Renamed", RemodelProbeVerdict.Unresolved)]
    public void Probe10Logic_Decide(bool markerBefore, string? markerNameAfter, string defaultName, string newName, RemodelProbeVerdict expected)
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe10Logic.Decide(markerBefore, markerNameAfter, defaultName, newName);
        Assert.Equal(expected, verdict);
    }

    [Fact]
    public void Probe10_NoMarkerEverAppears_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost { GetFeatureNamesImpl = _ => new[] { "Boss-Extrude1", "Folder1", "Shell1" } };
        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-10", Context(host)).Verdict);
    }

    [Fact]
    public void Probe10_MarkerTracksTheRename_RecordsRefuted()
    {
        bool renamed = false;
        var host = new FakeRemodelProbeHost { SetFeatureNameImpl = (_, _, _) => renamed = true };
        host.GetFeatureNamesImpl = _ => renamed
            ? new[] { "Boss-Extrude1", "Probe10RenamedFolder", "Probe10RenamedFolder___EndTag___", "Shell1" }
            : new[] { "Boss-Extrude1", "Folder1", "Folder1___EndTag___", "Shell1" };

        Assert.Equal(RemodelProbeVerdict.Refuted, Run("PROBE-10", Context(host)).Verdict);
    }

    [Fact]
    public void Probe10_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetFeatureNamesImpl = _ => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-10", Context(host)).Verdict);
    }

    // ---- PROBE-11: GetTypeName2 census ---------------------------------------------------

    [Fact]
    public void Probe11_EveryFeatureAnswers_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost
        {
            GetFeatureNamesImpl = _ => new[] { "Boss-Extrude1", "Cut-Extrude1", "Shell1" },
            GetFeatureTypeNameImpl = (_, _) => "Extrusion",
        };

        RemodelProbeRecord record = Run("PROBE-11", Context(host));
        Assert.Equal(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal("Extrusion", record.RawResult["type[Boss-Extrude1]"]);
    }

    [Fact]
    public void Probe11_OneFeatureTypeUnreadable_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost
        {
            GetFeatureNamesImpl = _ => new[] { "Boss-Extrude1", "Cut-Extrude1" },
            GetFeatureTypeNameImpl = (_, name) => name == "Cut-Extrude1" ? null : "Extrusion",
        };

        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-11", Context(host)).Verdict);
    }

    [Fact]
    public void Probe11_DuplicateNamesAreQueriedOnce()
    {
        var host = new FakeRemodelProbeHost { GetFeatureNamesImpl = _ => new[] { "Fillet1", "Fillet1", "Shell1" } };
        Run("PROBE-11", Context(host));

        Assert.Equal(2, host.Calls.Count(c => c == "GetFeatureTypeName"));
    }

    [Fact]
    public void Probe11_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetFeatureNamesImpl = _ => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-11", Context(host)).Verdict);
    }

    // ---- PROBE-12: tag, save, close, reopen, read back -------------------------------------

    [Theory]
    [InlineData(false, false, null, "v", RemodelProbeVerdict.Unresolved)]
    [InlineData(true, true, "v", "v", RemodelProbeVerdict.Verified)]
    [InlineData(true, false, null, "v", RemodelProbeVerdict.Refuted)]
    [InlineData(true, true, "different", "v", RemodelProbeVerdict.Refuted)]
    public void Probe12Logic_Decide(bool saved, bool found, string? valueAfter, string expectedValue, RemodelProbeVerdict expectedVerdict)
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe12Logic.Decide(saved, found, valueAfter, expectedValue);
        Assert.Equal(expectedVerdict, verdict);
    }

    [Fact]
    public void Probe12_TagSurvivesRoundTrip_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost
        {
            SaveExistingPartImpl = _ => true,
            GetCustomPropertyImpl = (RemodelProbePart part, string key, out string? value, out string? resolvedValue) =>
            {
                value = "verify-me";
                resolvedValue = "verify-me";
                return true;
            },
        };

        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-12", Context(host)).Verdict);
    }

    [Fact]
    public void Probe12_TagNotFoundAfterReopen_RecordsRefuted()
    {
        var host = new FakeRemodelProbeHost
        {
            SaveExistingPartImpl = _ => true,
            GetCustomPropertyImpl = (RemodelProbePart part, string key, out string? value, out string? resolvedValue) =>
            {
                value = null;
                resolvedValue = null;
                return false;
            },
        };

        Assert.Equal(RemodelProbeVerdict.Refuted, Run("PROBE-12", Context(host)).Verdict);
    }

    [Fact]
    public void Probe12_SaveFails_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { SaveExistingPartImpl = _ => false };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-12", Context(host)).Verdict);
    }

    [Fact]
    public void Probe12_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { AddCustomPropertyImpl = (_, _, _) => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-12", Context(host)).Verdict);
    }

    // ---- PROBE-13: File.Copy against an open part ------------------------------------------

    [Theory]
    [InlineData(true, false, RemodelProbeVerdict.Verified)]
    [InlineData(false, true, RemodelProbeVerdict.Refuted)]
    [InlineData(false, false, RemodelProbeVerdict.Unresolved)]
    public void Probe13Logic_Decide(bool copySucceeded, bool fallbackSucceeded, RemodelProbeVerdict expected)
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe13Logic.Decide(copySucceeded, fallbackSucceeded);
        Assert.Equal(expected, verdict);
    }

    [Fact]
    public void Probe13_SourceFileExistsAndUnlocked_RecordsVerified()
    {
        string dir = Path.Combine(Path.GetTempPath(), "swreview-probe-executor-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        string source = Path.Combine(dir, "remodel-probe.SLDPRT");
        File.WriteAllText(source, "fake part contents");

        try
        {
            var part = new RemodelProbePart(new object(), source, Array.Empty<object>());
            var context = new RemodelProbeContext(part, new SwGate(), "32.5.0.48", new FakeRemodelProbeHost(), dir);

            Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-13", context).Verdict);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void Probe13_SourceFileDoesNotExist_RecordsUnresolved()
    {
        string dir = Path.Combine(Path.GetTempPath(), "swreview-probe-executor-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        string source = Path.Combine(dir, "does-not-exist.SLDPRT");

        try
        {
            var part = new RemodelProbePart(new object(), source, Array.Empty<object>());
            var context = new RemodelProbeContext(part, new SwGate(), "32.5.0.48", new FakeRemodelProbeHost(), dir);

            Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-13", context).Verdict);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    // ---- PROBE-20: description survival ----------------------------------------------------

    [Theory]
    [InlineData(false, "expected", null, RemodelProbeVerdict.Unresolved)]
    [InlineData(true, "expected", "expected", RemodelProbeVerdict.Verified)]
    [InlineData(true, "expected", "different", RemodelProbeVerdict.Refuted)]
    public void Probe20Logic_Decide(bool moved, string expected, string? after, RemodelProbeVerdict expectedVerdict)
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe20Logic.Decide(moved, expected, after);
        Assert.Equal(expectedVerdict, verdict);
    }

    [Fact]
    public void Probe20_DescriptionSurvives_RecordsVerified()
    {
        string? description = null;
        var host = new FakeRemodelProbeHost
        {
            SetFeatureDescriptionImpl = (_, _, text) => description = text,
            ReorderFeatureImpl = (_, _, _, _) => true,
            GetFeatureDescriptionImpl = (_, _) => description,
        };

        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-20", Context(host)).Verdict);
    }

    [Fact]
    public void Probe20_ReorderFails_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { ReorderFeatureImpl = (_, _, _, _) => false };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-20", Context(host)).Verdict);
    }

    [Fact]
    public void Probe20_DescriptionLost_RecordsRefuted()
    {
        var host = new FakeRemodelProbeHost
        {
            ReorderFeatureImpl = (_, _, _, _) => true,
            GetFeatureDescriptionImpl = (_, _) => string.Empty,
        };

        Assert.Equal(RemodelProbeVerdict.Refuted, Run("PROBE-20", Context(host)).Verdict);
    }

    [Fact]
    public void Probe20_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { SetFeatureDescriptionImpl = (_, _, _) => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-20", Context(host)).Verdict);
    }

    // ---- PROBE-21: no equations yet ---------------------------------------------------------

    [Fact]
    public void Probe21_CountIsZero_RecordsVerified()
    {
        var host = new FakeRemodelProbeHost { GetEquationCountImpl = _ => 0 };
        Assert.Equal(RemodelProbeVerdict.Verified, Run("PROBE-21", Context(host)).Verdict);
    }

    [Fact]
    public void Probe21_CountIsNonZero_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetEquationCountImpl = _ => 3 };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-21", Context(host)).Verdict);
    }

    [Fact]
    public void Probe21_HostThrows_RecordsUnresolved()
    {
        var host = new FakeRemodelProbeHost { GetEquationCountImpl = _ => throw new InvalidOperationException("boom") };
        Assert.Equal(RemodelProbeVerdict.Unresolved, Run("PROBE-21", Context(host)).Verdict);
    }

    [Fact]
    public void Probe21_DiscardsTheBlankDocumentEvenWhenGetEquationCountThrows()
    {
        bool discarded = false;
        var host = new FakeRemodelProbeHost
        {
            GetEquationCountImpl = _ => throw new InvalidOperationException("boom"),
            DiscardBlankDocumentImpl = _ => discarded = true,
        };

        Run("PROBE-21", Context(host));
        Assert.True(discarded);
    }

    // ---- the whole catalog, run together --------------------------------------------------

    [Fact]
    public void FullRun_AllFifteenProbes_EveryOneAnswersAndTheLedgerRoundTrips()
    {
        var host = new FakeRemodelProbeHost();
        RemodelProbeContext context = Context(host, watchdogDeadline: NeverFires);

        IReadOnlyList<RemodelProbeRecord> records = RemodelProbeRunner.RunAll(
            RemodelProbeCatalog.AllIds, context, RemodelProbeExecutors.ByProbeId);

        Assert.Equal(15, records.Count);
        Assert.Equal(RemodelProbeCatalog.AllIds, records.Select(r => r.ProbeId));

        // No probe fell through to the "not yet implemented" placeholder.
        Assert.DoesNotContain(records, r => r.RawResult.ContainsKey(RemodelProbeRunner.NoteKey));

        string yaml = RemodelProbeLedger.Render("32.5.0.48", records, DateTimeOffset.UtcNow);
        foreach (string id in RemodelProbeCatalog.AllIds)
        {
            Assert.Contains($"probe_id: \"{id}\"", yaml);
        }
    }

    [Fact]
    public void RunAll_SubsetOfProbeIds_RunsOnlyThoseAndTouchesOnlyTheirMembers()
    {
        var host = new FakeRemodelProbeHost();
        RemodelProbeContext context = Context(host);

        IReadOnlyList<RemodelProbeRecord> records = RemodelProbeRunner.RunAll(
            new[] { "PROBE-2", "PROBE-9" }, context, RemodelProbeExecutors.ByProbeId);

        Assert.Equal(new[] { "PROBE-2", "PROBE-9" }, records.Select(r => r.ProbeId));

        // PROBE-9's own body suppresses a feature; PROBE-4's builds a second folder. Only the
        // requested ids' work should show up in the host's call log.
        Assert.Contains(host.Calls, c => c == "SetFeatureSuppression");
        Assert.DoesNotContain(host.Calls, c => c == "TryInsertFeatureTreeFolder");
    }
}

/// <summary>
/// U24's reproduction (013 T135, 004 T171), in a collection of its own that runs alone, because
/// it starves the thread pool on purpose: PROBE-1 over a host whose <c>ReorderFeature</c> throws on
/// its first line, through the production watchdog's timer, must read <c>unresolved</c> - a throw
/// is an answer, not a block - however loaded the machine is. A watchdog that queued its call on
/// the pool and started its clock at once would count the queueing as blocking, time out both
/// tries while they were still waiting for a thread, and record <c>refuted</c>.
/// </summary>
[Collection(SaturatedPoolCollection.Name)]
public sealed class RemodelProbeWatchdogSaturatedPoolTests
{
    [Fact]
    public void Probe1_WithThePoolSaturated_AHostThatThrowsIsUnresolvedAndNeverRefuted()
    {
        using var release = new ManualResetEventSlim(false);
        int held = Environment.ProcessorCount * 2;
        try
        {
            for (int i = 0; i < held; i++)
            {
                ThreadPool.QueueUserWorkItem(_ => release.Wait());
            }

            var host = new FakeRemodelProbeHost
            {
                ReorderFeatureImpl = (_, _, _, _) => throw new InvalidOperationException("the host's own words"),
            };
            var part = new RemodelProbePart(new object(), @"C:\out\probe-part\remodel-probe.SLDPRT", Array.Empty<object>());
            var context = new RemodelProbeContext(
                part, new SwGate(), "32.5.0.48", host, @"C:\out", TimeSpan.FromMilliseconds(500));

            RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-1", context, RemodelProbeExecutors.ByProbeId);

            Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        }
        finally
        {
            release.Set();
        }
    }
}

/// <summary>The tests that starve the thread pool on purpose, run alone so no other test shares the starvation.</summary>
[CollectionDefinition(Name, DisableParallelization = true)]
public sealed class SaturatedPoolCollection
{
    public const string Name = "the thread pool saturated on purpose";
}
