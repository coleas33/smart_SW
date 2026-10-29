using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Owner decision 159A, on Codex's review of the merge (C1, defence in depth; 004 T240): the run's
/// identity on the bridge. A run's session lives on the dispatcher that answered its
/// <c>remodel.open</c>, and no command after the open named a run. So a run's worker that outlived
/// its session - the add-in took a status poll the backend did not answer for the run's end, closed
/// the session and opened the next plan on the same bridge - had its next change carried out on the
/// next run's copy: <c>VerifyTarget</c> checks the copy the session holds, and that copy was the next
/// run's own, tagged with the next run's id.
///
/// Every command after <c>remodel.open</c> now names its run, <c>run_id</c>: the id the open was
/// given and tagged the copy with. The bridge refuses one that names another run
/// (<c>session_mismatch</c>) or none (<c>bad_request</c>) before anything is read or written. With no
/// session the answer is <c>target_mismatch</c>, as it was, whatever run the command names.
/// </summary>
public class RemodelRunIdentityTests
{
    /// <summary>Another run of the same part, as the run folders name them.</summary>
    private const string OtherRunId = "20260916-142305-bracket-remodel";

    private const string RenameParams = "{\"persist_ref\":\"ref:boss\",\"new_name\":\"Boss-Base1\"}";

    /// <summary>Every command on the scope, with parameters it would be carried out with.</summary>
    public static IEnumerable<object[]> SessionCommandRows =>
        RemodelCommandTable.Commands
            .Where(shape => shape.Stage == RemodelCommandStage.OnScope)
            .Select(shape => new object[] { shape.Command, SessionParams(shape.Command) });

    [Fact]
    public void EveryCommandOnTheScopeNamesItsRunFirst()
    {
        Assert.Equal(10, SessionCommandRows.Count());
        Assert.All(
            RemodelCommandTable.Commands.Where(shape => shape.Stage == RemodelCommandStage.OnScope),
            shape => Assert.Equal("run_id", shape.ParameterNames.First()));

        // The probe runs before any run's session exists; the open is given the run's id, tags
        // the copy with it, and the session keeps it.
        Assert.DoesNotContain("run_id", RemodelCommandTable.For(RemodelCommands.ProbeScope).ParameterNames);
        Assert.Contains("run_id", RemodelCommandTable.For(RemodelCommands.Open).ParameterNames);
    }

    [Fact]
    public void TheRefusalIsAStableTokenOfItsOwnBesideTargetMismatch()
    {
        Assert.Equal("session_mismatch", RemodelErrorCodes.SessionMismatch);
        int target = Array.IndexOf(RemodelErrorCodes.All, RemodelErrorCodes.TargetMismatch);
        Assert.Equal(RemodelErrorCodes.SessionMismatch, RemodelErrorCodes.All[target + 1]);
        Assert.Equal(27, RemodelErrorCodes.All.Length);
        Assert.Equal(RemodelErrorCodes.All.Length, RemodelErrorCodes.All.Distinct(StringComparer.Ordinal).Count());
    }

    [Theory]
    [MemberData(nameof(SessionCommandRows))]
    public void ACommandOfAnotherRunIsRefusedBeforeAnythingIsReadOrWritten(string command, string parameters)
    {
        using (RemodelHarness harness = Opened())
        {
            int gated = harness.Observer.Members.Count;

            BridgeResponse response = harness.DispatchFor(OtherRunId, command, parameters);

            Assert.Equal(RemodelErrorCodes.SessionMismatch, RemodelHarness.Refusal(response));
            Assert.Contains(command, response.Error!, StringComparison.Ordinal);
            Assert.Contains("'" + OtherRunId + "'", response.Error!, StringComparison.Ordinal);
            Assert.Contains("'" + RemodelHarness.RunId + "'", response.Error!, StringComparison.Ordinal);
            Assert.Contains("nothing was read or written", response.Error!, StringComparison.Ordinal);
            AssertNothingReachedTheCopy(harness, gated);
        }
    }

    [Theory]
    [MemberData(nameof(SessionCommandRows))]
    public void ACommandNamingNoRunIsRefusedBeforeAnythingIsReadOrWritten(string command, string parameters)
    {
        using (RemodelHarness harness = Opened())
        {
            int gated = harness.Observer.Members.Count;

            BridgeResponse response = harness.DispatchFor(null, command, parameters);

            Assert.Equal(RemodelErrorCodes.BadRequest, RemodelHarness.Refusal(response));
            Assert.Contains("params.run_id", response.Error!, StringComparison.Ordinal);
            AssertNothingReachedTheCopy(harness, gated);
        }
    }

    /// <summary>A run id that is not a non-empty string names no run.</summary>
    [Theory]
    [InlineData("\"\"")]
    [InlineData("\"   \"")]
    [InlineData("null")]
    [InlineData("7")]
    [InlineData("[\"20260916-142201-bracket-remodel\"]")]
    public void ARunIdThatIsNotANonEmptyStringNamesNoRun(string runId)
    {
        using (RemodelHarness harness = Opened())
        {
            int gated = harness.Observer.Members.Count;

            BridgeResponse response = harness.DispatchFor(
                null, RemodelCommands.Rename, "{\"run_id\":" + runId + "," + RenameParams.Substring(1));

            Assert.Equal(RemodelErrorCodes.BadRequest, RemodelHarness.Refusal(response));
            AssertNothingReachedTheCopy(harness, gated);
        }
    }

    /// <summary>
    /// Compared exactly, as <c>VerifyTarget</c> compares the copy's tag: a run id in another case, or
    /// one that only begins or ends like this run's, is another run's.
    /// </summary>
    [Theory]
    [InlineData("20260916-142201-BRACKET-remodel")]
    [InlineData("20260916-142201-bracket-remodel-2")]
    [InlineData("20260916-142201-bracket")]
    [InlineData("x20260916-142201-bracket-remodel")]
    public void ARunIdIsComparedExactly(string runId)
    {
        using (RemodelHarness harness = Opened())
        {
            int gated = harness.Observer.Members.Count;

            BridgeResponse response = harness.DispatchFor(runId, RemodelCommands.Rename, RenameParams);

            Assert.Equal(RemodelErrorCodes.SessionMismatch, RemodelHarness.Refusal(response));
            AssertNothingReachedTheCopy(harness, gated);
        }
    }

    /// <summary>Read as the open reads the id it is given, space around it trimmed; then exactly.</summary>
    [Fact]
    public void ARunIdIsReadAsTheOpenReadsIt()
    {
        using (RemodelHarness harness = Opened())
        {
            RemodelHarness.Ok<RemodelRenameResult>(
                harness.DispatchFor(" " + RemodelHarness.RunId + " ", RemodelCommands.Rename, RenameParams));

            Assert.Equal("Boss-Base1", harness.Copy.Features[0].Name);
        }
    }

    [Theory]
    [MemberData(nameof(SessionCommandRows))]
    public void ACommandOfThisRunIsCarriedOut(string command, string parameters)
    {
        using (RemodelHarness harness = Opened())
        {
            if (command == RemodelCommands.Save)
            {
                harness.GeometryGate();
            }

            Assert.Equal(BridgeStatus.Ok, harness.DispatchFor(RemodelHarness.RunId, command, parameters).Status);
        }
    }

    /// <summary>
    /// No session is still <c>target_mismatch</c> whatever run a command names: before the open, and
    /// after the close that ended the run's session.
    /// </summary>
    [Fact]
    public void WithNoSessionTheAnswerIsTargetMismatchWhateverRunTheCommandNames()
    {
        using (var harness = new RemodelHarness(new FakeFeature("ref:boss", "Boss-Extrude1")))
        {
            Assert.Equal(
                RemodelErrorCodes.TargetMismatch,
                RemodelHarness.Refusal(harness.DispatchFor(RemodelHarness.RunId, RemodelCommands.Snapshot, "{}")));
            Assert.Equal(
                RemodelErrorCodes.TargetMismatch,
                RemodelHarness.Refusal(harness.DispatchFor(null, RemodelCommands.Snapshot, "{}")));

            harness.Open();
            RemodelHarness.Ok<RemodelCloseResult>(harness.Dispatch(RemodelCommands.Close, "{\"discard_copy\":false}"));

            Assert.Equal(
                RemodelErrorCodes.TargetMismatch,
                RemodelHarness.Refusal(harness.DispatchFor(RemodelHarness.RunId, RemodelCommands.Rename, RenameParams)));
            Assert.Equal(
                RemodelErrorCodes.TargetMismatch,
                RemodelHarness.Refusal(harness.DispatchFor(OtherRunId, RemodelCommands.Rename, RenameParams)));
        }
    }

    /// <summary>
    /// The race Codex found, in the stub world: run A's session is closed while A's worker still runs,
    /// the next plan - run B, the same part - opens its copy on the same bridge, and A's worker sends
    /// its next change. Before 159A it was carried out on B's copy, which passes every check
    /// <c>VerifyTarget</c> makes because it is B's own. Now it is refused, B's copy untouched, and B's
    /// own change is carried out.
    /// </summary>
    [Fact]
    public void ARunsWorkerThatOutlivedItsSessionCannotChangeTheNextRunsCopy()
    {
        using (RemodelHarness harness = Opened())
        {
            RemodelHarness.Ok<RemodelCloseResult>(harness.Dispatch(RemodelCommands.Close, "{\"discard_copy\":false}"));

            string nextRun = Path.Combine(harness.Root, OtherRunId);
            Directory.CreateDirectory(nextRun);
            string nextCopyPath = Path.GetFullPath(RemodelCopy.CopyPathFor(nextRun, harness.SourcePath));
            var nextCopy = new FakeRemodelDocument(
                nextCopyPath,
                new FakeFeature("ref:boss", "Boss-Extrude1"),
                new FakeFeature("ref:fillet", "Fillet1"));
            harness.Seat.Copy = nextCopy;
            harness.Dispatcher.BindRemodelRun(nextRun);
            var probe = RemodelHarness.Ok<RemodelProbeScopeResult>(harness.Dispatch(
                RemodelCommands.ProbeScope,
                "{\"source_path\":" + JsonSerializer.Serialize(harness.SourcePath) + "}"));
            RemodelHarness.Ok<RemodelOpenResult>(harness.Dispatch(
                RemodelCommands.Open,
                "{\"source_path\":" + JsonSerializer.Serialize(harness.SourcePath)
                + ",\"copy_path\":" + JsonSerializer.Serialize(nextCopyPath)
                + ",\"run_id\":" + JsonSerializer.Serialize(OtherRunId)
                + ",\"probe_id\":" + JsonSerializer.Serialize(probe.ProbeId) + "}"));
            nextCopy.Members.Clear();
            harness.Seat.ToggleWrites.Clear();

            BridgeResponse late = harness.DispatchFor(RemodelHarness.RunId, RemodelCommands.Rename, RenameParams);

            Assert.Equal(RemodelErrorCodes.SessionMismatch, RemodelHarness.Refusal(late));
            Assert.Equal("Boss-Extrude1", nextCopy.Features[0].Name);
            Assert.Empty(nextCopy.Members);
            Assert.Empty(nextCopy.Resolved);
            Assert.Empty(harness.Seat.ToggleWrites);
            Assert.Equal(nextCopyPath, harness.Dispatcher.RemodelTargetPath);

            RemodelHarness.Ok<RemodelRenameResult>(harness.DispatchFor(OtherRunId, RemodelCommands.Rename, RenameParams));
            Assert.Equal("Boss-Base1", nextCopy.Features[0].Name);
        }
    }

    private static RemodelHarness Opened()
    {
        var harness = new RemodelHarness(
            new FakeFeature("ref:boss", "Boss-Extrude1"),
            new FakeFeature("ref:fillet", "Fillet1"));
        harness.Open();
        harness.Seat.ToggleWrites.Clear();
        return harness;
    }

    /// <summary>Not a read, not a resolve, not a gate key, not a setting, not a close; the session as it was.</summary>
    private static void AssertNothingReachedTheCopy(RemodelHarness harness, int gated)
    {
        Assert.Empty(harness.Copy.Members);
        Assert.Empty(harness.Copy.EquationManager.Members);
        Assert.Empty(harness.Copy.Resolved);
        Assert.Equal(gated, harness.Observer.Members.Count);
        Assert.Empty(harness.Seat.ToggleWrites);
        Assert.Empty(harness.Seat.Closed);
        Assert.Equal(new[] { "Boss-Extrude1", "Fillet1" }, harness.Copy.Features.Select(feature => feature.Name));
        Assert.True(File.Exists(harness.CopyPath), "the copy was deleted");
        Assert.Equal(harness.CopyPath, harness.Dispatcher.RemodelTargetPath);
    }

    private static string SessionParams(string command)
    {
        switch (command)
        {
            case RemodelCommands.Snapshot:
            case RemodelCommands.Geometry:
                return "{}";
            case RemodelCommands.Rename:
                return RenameParams;
            case RemodelCommands.Reorder:
                return "{\"feature_persist_ref\":\"ref:fillet\",\"anchor_persist_ref\":\"ref:boss\",\"location\":\"before\"}";
            case RemodelCommands.Folder:
                return "{\"op\":\"create\",\"name\":\"1-Reference\",\"member_persist_refs\":[\"ref:boss\"],\"folder_persist_ref\":null}";
            case RemodelCommands.Describe:
                return "{\"persist_ref\":\"ref:boss\",\"text\":\"the base plate\"}";
            case RemodelCommands.Equation:
                return "{\"op\":\"add\",\"index\":null,\"text\":\"\\\"w\\\" = 120\",\"which_configs\":2}";
            case RemodelCommands.Rebuild:
                return "{\"force\":false}";
            case RemodelCommands.Save:
                return RemodelHarness.SaveParams("pass");
            case RemodelCommands.Close:
                return "{\"discard_copy\":true}";
            default:
                throw new ArgumentOutOfRangeException(nameof(command), command, "not a command on the scope");
        }
    }
}
