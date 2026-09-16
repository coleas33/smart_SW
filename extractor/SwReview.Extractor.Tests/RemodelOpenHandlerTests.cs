using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Measure;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T061. <c>remodel.probe_scope</c>, <c>remodel.open</c> and <c>remodel.snapshot</c>, driven
/// over a fake scope so every branch is exercised with no SOLIDWORKS.
///
/// The ordering these three commands encode is the whole of FR-001. Every scope refusal is
/// reached <b>before any copy is made and before any SOLIDWORKS document handle to the source
/// exists</b>, which is why the signals are read by <c>probe_scope</c> on the engineer's
/// already-open document and not at the end of <c>open</c>: by then the copy is on disk and a
/// document is open.
///
/// <c>probe_scope</c> is the one command that touches the source, and it only reads it. Its
/// machine-checkable form is here: the recorded <c>refused=</c> set is <b>empty</b> and the
/// <c>gated=</c> set is a subset of the checked-in read-only probe surface with no stage-1
/// allowlist key in it. The gated set is deliberately <b>not</b> empty - <c>SwGate.Guard</c>
/// gates reads too - so "the source is only ever read" is a statement about which members were
/// gated, not about whether any were.
///
/// <c>open</c> refuses an unknown <c>probe_id</c> <b>before</b> the copy, so FR-001's "before
/// any copy is made" is structural rather than conventional, and its one post-copy refusal -
/// <c>preexisting_rebuild_errors</c>, which needs a rollback and a rebuild to read and so can
/// only be taken on the copy - deletes the copy and closes the document.
/// </summary>
public class RemodelOpenHandlerTests : IDisposable
{
    /// <summary>
    /// The read-only probe surface, exactly as contracts/bridge-remodel.md fixes it: the
    /// members of the <c>scope_signals</c> table plus <c>GetOpenDocumentByName</c>,
    /// <c>GetType</c>, <c>GetSaveFlag</c> and <c>ListExternalFileReferencesCount2</c>.
    /// </summary>
    private static readonly string[] ProbeSurface =
    {
        "GetOpenDocumentByName",
        "GetType",
        "GetSaveFlag",
        "ListExternalFileReferencesCount2",
        "GetBodies2",
        "IsWeldment",
        "GetSheetMetalFolder",
        "IsMeshBody",
        "IsGraphicsBody",
        "Is3DInterconnectFeature",
        "GetImportedFileName",
        "GetConfigurationNames",
        "GetTypeName2",
    };

    private const string RunId = "20260916-142201-bracket-remodel";

    private readonly string _root;
    private readonly string _runDirectory;
    private readonly string _sourcePath;
    private readonly string _copyPath;
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();

    public RemodelOpenHandlerTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "swreview-remodel", Guid.NewGuid().ToString("N"));
        _runDirectory = Path.Combine(_root, RunId);
        _sourcePath = Path.Combine(_root, "work", "bracket.SLDPRT");

        Directory.CreateDirectory(Path.GetDirectoryName(_sourcePath)!);
        Directory.CreateDirectory(_runDirectory);
        File.WriteAllText(_sourcePath, "not really a part, but a file with bytes and a hash");

        _copyPath = RemodelCopy.CopyPathFor(_runDirectory, _sourcePath);
    }

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    // ---- remodel.probe_scope ---------------------------------------------------------

    [Fact]
    public void ProbeScope_ReadsTheOpenSource_AndOpensNothingAndCopiesNothing()
    {
        FakeRemodelSeat seat = Seat();

        var result = Ok<RemodelProbeScopeResult>(Dispatcher(seat).Dispatch(ProbeRequest()));

        Assert.False(string.IsNullOrWhiteSpace(result.ProbeId));
        Assert.Equal(Path.GetFullPath(_sourcePath), result.SourcePath);
        Assert.Equal(1, result.ScopeSignals!.DocumentType);
        Assert.Equal(1, result.ScopeSignals.SolidBodyCount);

        // No handle, no copy: the run has not begun.
        Assert.Empty(seat.Opened);
        Assert.False(File.Exists(_copyPath));

        // rebuild_error_count is the one signal the probe cannot read - it needs a rollback
        // and a rebuild, both writes - and unknown stays unknown rather than becoming zero.
        Assert.Null(result.ScopeSignals.RebuildErrorCount);
    }

    [Fact]
    public void ProbeScope_ReadsOneMemberPerScopeSignal()
    {
        FakeRemodelSeat seat = Seat();
        Dispatcher(seat).Dispatch(ProbeRequest());

        Assert.Equal(
            new[]
            {
                nameof(FakeProbeSource.IsOpen),
                nameof(FakeProbeSource.GetDocumentType),
                nameof(FakeProbeSource.GetSaveFlag),
                nameof(FakeProbeSource.GetExternalReferenceCount),

                // Read twice on purpose: step 2 refuses a document that is not a part before
                // any body or feature is touched, and document_type is also a signal row that
                // step 12 re-reads on the copy and compares.
                nameof(FakeProbeSource.GetDocumentType),
                nameof(FakeProbeSource.GetBodyCount),
                nameof(FakeProbeSource.GetBodyCount),
                nameof(FakeProbeSource.IsWeldment),
                nameof(FakeProbeSource.HasSheetMetalFolder),
                nameof(FakeProbeSource.HasMeshBody),
                nameof(FakeProbeSource.HasGraphicsBody),
                nameof(FakeProbeSource.Is3DInterconnect),
                nameof(FakeProbeSource.GetImportedFileNames),
                nameof(FakeProbeSource.GetConfigurationNames),
                nameof(FakeProbeSource.GetFolders),
            },
            seat.Probe.Members);
    }

    [Fact]
    public void ProbeScope_RefusesNothingAndGatesOnlyTheReadOnlyProbeSurface()
    {
        // The machine-checkable form of "the source is only ever read". The gated set is NOT
        // empty: SwGate.Guard reports every member before the guard judges it, reads included.
        FakeRemodelSeat seat = Seat();
        Dispatcher(seat).Dispatch(ProbeRequest());

        Assert.NotEmpty(_observer.Members);
        Assert.Empty(_observer.Refusals);
        Assert.All(
            _observer.Members,
            member => Assert.Contains(member, ProbeSurface, StringComparer.Ordinal));
        Assert.All(
            _observer.Members,
            member => Assert.DoesNotContain(member, RemodelGuard.AllowedKeys, StringComparer.Ordinal));

        // The same list, from the product, so a member added to the probe has to be added to
        // the contract's table as well.
        Assert.Equal(
            ProbeSurface.OrderBy(member => member, StringComparer.Ordinal),
            RemodelScopeProbe.ProbeSurface.OrderBy(member => member, StringComparer.Ordinal));
    }

    [Fact]
    public void ProbeScope_SourceSolidWorksDoesNotHaveOpen_IsRefusedWithoutOpeningIt()
    {
        // Opening the source to answer would give away the one property the constitution
        // exception rests on.
        FakeRemodelSeat seat = Seat();
        seat.Probe.Open = false;

        Assert.Equal(
            RemodelErrorCodes.SourceNotOpen, Refusal(Dispatcher(seat).Dispatch(ProbeRequest())));
        Assert.Empty(seat.Opened);
    }

    [Fact]
    public void ProbeScope_NotASldprt_OrNotAPartDocument_IsNotAPart()
    {
        FakeRemodelSeat seat = Seat();
        string assembly = Path.Combine(_root, "work", "bracket.SLDASM");
        File.WriteAllText(assembly, "an assembly");

        Assert.Equal(
            RemodelErrorCodes.NotAPart,
            Refusal(Dispatcher(seat).Dispatch(ProbeRequest(assembly))));

        seat.Probe.DocumentType = 2;
        Assert.Equal(RemodelErrorCodes.NotAPart, Refusal(Dispatcher(seat).Dispatch(ProbeRequest())));
    }

    [Fact]
    public void ProbeScope_MissingFile_IsNotAPart()
    {
        Assert.Equal(
            RemodelErrorCodes.NotAPart,
            Refusal(Dispatcher(Seat()).Dispatch(ProbeRequest(Path.Combine(_root, "gone.SLDPRT")))));
    }

    [Fact]
    public void ProbeScope_DirtySource_IsSourceDirty()
    {
        FakeRemodelSeat seat = Seat();
        seat.Probe.SaveFlag = true;

        Assert.Equal(
            RemodelErrorCodes.SourceDirty, Refusal(Dispatcher(seat).Dispatch(ProbeRequest())));
    }

    [Fact]
    public void ProbeScope_ExternalReferences_IsExternalRefs()
    {
        FakeRemodelSeat seat = Seat();
        seat.Probe.ExternalReferenceCount = 2;

        Assert.Equal(
            RemodelErrorCodes.ExternalRefs, Refusal(Dispatcher(seat).Dispatch(ProbeRequest())));
    }

    [Fact]
    public void ProbeScope_MintsAProbeIdPerProbe()
    {
        SwBridgeDispatcher dispatcher = Dispatcher(Seat());

        string first = Ok<RemodelProbeScopeResult>(dispatcher.Dispatch(ProbeRequest())).ProbeId;
        string second = Ok<RemodelProbeScopeResult>(dispatcher.Dispatch(ProbeRequest())).ProbeId;

        Assert.NotEqual(first, second);
    }

    // ---- remodel.open ----------------------------------------------------------------

    [Fact]
    public void Open_UnknownProbeId_IsScopeNotProbed_AndNothingIsCopied()
    {
        FakeRemodelSeat seat = Seat();

        Assert.Equal(
            RemodelErrorCodes.ScopeNotProbed,
            Refusal(Dispatcher(seat).Dispatch(OpenRequest("probe:never-minted"))));
        Assert.False(File.Exists(_copyPath));
        Assert.Empty(seat.Opened);
    }

    [Fact]
    public void Open_ProbeIdMintedForAnotherPath_IsScopeNotProbed()
    {
        string other = Path.Combine(_root, "work", "other.SLDPRT");
        File.WriteAllText(other, "another part");

        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);
        string probeId = Ok<RemodelProbeScopeResult>(
            dispatcher.Dispatch(ProbeRequest(other))).ProbeId;

        Assert.Equal(
            RemodelErrorCodes.ScopeNotProbed, Refusal(dispatcher.Dispatch(OpenRequest(probeId))));
        Assert.False(File.Exists(_copyPath));
    }

    [Fact]
    public void Open_CopiesTheSourceIntoTheRunFolderAndOpensTheCopyAtItsOwnPath()
    {
        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);

        var result = Ok<RemodelOpenResult>(dispatcher.Dispatch(OpenRequest(Probe(dispatcher))));

        Assert.True(File.Exists(_copyPath));
        Assert.Equal(File.ReadAllBytes(_sourcePath), File.ReadAllBytes(_copyPath));
        Assert.Equal(Path.GetFullPath(_copyPath), result.DocumentPath);
        Assert.NotEqual(Path.GetFullPath(_sourcePath), result.DocumentPath);

        // Silent | LoadModel = 17 exactly, and never ReadOnly(2) or ViewOnly(4).
        Assert.Equal(17, Assert.Single(seat.OpenOptions));
        Assert.Equal(Path.GetFullPath(_copyPath), Assert.Single(seat.Opened));

        // The tag is read back, not assumed: PROBE-6 saw Add3 answer -1 and add nothing.
        Assert.Equal(RunId, result.Tag);
        Assert.Equal(RunId, seat.Copy!.SessionTag);

        Assert.Equal(2, result.FeatureCount);
        Assert.Equal(new[] { "Default" }, result.Configurations);
        Assert.Equal("mm", result.DocumentLengthUnit);
        Assert.Equal(0, result.ScopeSignals!.RebuildErrorCount);
        Assert.Equal(Path.GetFullPath(_sourcePath), result.SourceAttestation!.Path);
        Assert.Equal(new FileInfo(_sourcePath).Length, result.SourceAttestation.LengthBytes);
    }

    [Fact]
    public void Open_RollsTheBarToTheEndAndRebuildsBeforeReadingTheCopysSignals()
    {
        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);
        dispatcher.Dispatch(OpenRequest(Probe(dispatcher)));

        List<string> members = seat.Copy!.Members;
        Assert.Contains(nameof(FakeRemodelDocument.EditRollbackToEnd), members);
        Assert.True(
            members.IndexOf(nameof(FakeRemodelDocument.EditRollbackToEnd))
            < members.IndexOf(nameof(FakeRemodelDocument.ForceRebuild)),
            "the rollback runs before the rebuild");
        Assert.True(
            members.IndexOf(nameof(FakeRemodelDocument.ForceRebuild))
            < members.LastIndexOf(nameof(FakeRemodelDocument.GetFolders)),
            "the copy's signals are read after the rebuild");
    }

    [Fact]
    public void Open_AFeatureStillRolledBack_StopsTheRunAndDeletesTheCopy()
    {
        FakeRemodelSeat seat = Seat();
        seat.Copy!.Features[1].RolledBack = true;
        SwBridgeDispatcher dispatcher = Dispatcher(seat);

        Assert.Equal(
            RemodelErrorCodes.OpenFailed, Refusal(dispatcher.Dispatch(OpenRequest(Probe(dispatcher)))));
        Assert.False(File.Exists(_copyPath));
    }

    [Fact]
    public void Open_PreexistingRebuildErrors_DeletesTheCopyAndClosesTheDocument()
    {
        // The one refusal in the feature that can happen after a copy exists, and therefore
        // the one that has to clean up after itself: the part was already broken and nothing
        // after this point could be attributed to the run.
        FakeRemodelSeat seat = Seat();
        seat.Copy!.WhatsWrongCount = 3;
        SwBridgeDispatcher dispatcher = Dispatcher(seat);

        Assert.Equal(
            RemodelErrorCodes.PreexistingRebuildErrors,
            Refusal(dispatcher.Dispatch(OpenRequest(Probe(dispatcher)))));
        Assert.False(File.Exists(_copyPath));
        Assert.Equal(Path.GetFullPath(_copyPath), Assert.Single(seat.Closed));

        // The unwind's close is the same allowlisted write remodel.close makes, on the path
        // where the audit record matters most, so it is gated like the other one.
        Assert.Contains("ISldWorks.CloseDoc", _observer.Members);
    }

    [Fact]
    public void Open_CopySignalsDifferingFromTheProbes_IsScopeChangedAndDeletesTheCopy()
    {
        // The document being changed is not the one the verdict was reached on.
        FakeRemodelSeat seat = Seat();
        seat.Copy!.Signals.SolidBodyCount = 4;
        SwBridgeDispatcher dispatcher = Dispatcher(seat);

        BridgeResponse response = dispatcher.Dispatch(OpenRequest(Probe(dispatcher)));

        Assert.Equal(RemodelErrorCodes.ScopeChanged, Refusal(response));
        Assert.Contains("solid_body_count", response.Error!, StringComparison.Ordinal);
        Assert.False(File.Exists(_copyPath));
    }

    [Fact]
    public void Open_ADestinationThatAlreadyExists_IsCopyExistsAndTheFileIsLeftAlone()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_copyPath)!);
        File.WriteAllText(_copyPath, "someone else's file");

        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);

        Assert.Equal(
            RemodelErrorCodes.CopyExists, Refusal(dispatcher.Dispatch(OpenRequest(Probe(dispatcher)))));
        Assert.Equal("someone else's file", File.ReadAllText(_copyPath));
    }

    /// <summary>
    /// The run folder is the host's, and the request cannot choose one. Each of these paths
    /// would satisfy "inside this run's folder" if the run folder were derived from the path
    /// itself - the third one is the interesting case, because its parent <b>is</b> named
    /// <c>copy</c> and it still sits beside the engineer's file, which is exactly the write
    /// OQ-10 says must be structurally impossible.
    /// </summary>
    [Theory]
    [InlineData("work", "bracket-RMS.SLDPRT")]
    [InlineData("work", "copy", "bracket-RMS.SLDPRT")]
    [InlineData("20260916-999999-another-run", "copy", "bracket-RMS.SLDPRT")]
    public void Open_ACopyPathOutsideTheRunFolder_IsRefusedByTheGuard(params string[] segments)
    {
        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);
        string outside = Path.Combine(_root, Path.Combine(segments));

        Assert.Equal(
            RemodelErrorCodes.GuardRefused,
            Refusal(dispatcher.Dispatch(OpenRequest(Probe(dispatcher), outside))));
        Assert.False(File.Exists(outside));
    }

    /// <summary>
    /// And a bridge with a seat but no run folder refuses rather than deriving one from the
    /// request, which is the same refusal read from the other side.
    /// </summary>
    [Fact]
    public void Open_OnABridgeWithNoRunFolder_IsRefusedBeforeAnythingIsCopied()
    {
        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat, runRoot: null);

        Assert.Equal(
            RemodelErrorCodes.TargetMismatch,
            Refusal(dispatcher.Dispatch(OpenRequest(Probe(dispatcher)))));
        Assert.False(File.Exists(_copyPath));
    }

    /// <summary>
    /// The rollback from a failed open is the caller that matters: it is unwinding, and the
    /// two calls it makes - a COM close and a filesystem delete - can both throw on a path
    /// that is already failing. The four settings are put back in a <c>finally</c>, so they
    /// come back whatever those two do.
    /// </summary>
    [Fact]
    public void Open_WhoseRollbackAlsoFails_StillRestoresTheEngineersSettings()
    {
        FakeRemodelSeat seat = Seat();
        seat.Copy!.WhatsWrongCount = 2;
        seat.CloseFailure = new InvalidOperationException("the seat could not close the copy");
        SwBridgeDispatcher dispatcher = Dispatcher(seat);

        // The refusal itself is the close failure, not preexisting_rebuild_errors: the run is
        // unwinding and this is what went wrong last. What matters is what is left behind.
        Assert.Equal(BridgeStatus.Error, dispatcher.Dispatch(OpenRequest(Probe(dispatcher))).Status);

        Assert.Equal(
            new[]
            {
                "10=False", "77=False", "329=False", "CommandInProgress=True",
                "10=False", "77=False", "329=False", "CommandInProgress=False",
            },
            seat.ToggleWrites);
    }

    [Fact]
    public void Open_SetsTheThreeTogglesAndTheCommandFlag()
    {
        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);
        dispatcher.Dispatch(OpenRequest(Probe(dispatcher)));

        Assert.Equal(
            new[] { "10=False", "77=False", "329=False", "CommandInProgress=True" },
            seat.ToggleWrites);

        // They are writes to the engineer's application-wide settings, so they are on the
        // audited gated= set under their own two allowlist keys, exactly like every other
        // write the run makes. Without this the four writes the feature makes first would be
        // the four nothing records.
        Assert.Contains(RemodelSystemToggles.ToggleMember, _observer.Members);
        Assert.Contains(RemodelSystemToggles.CommandInProgressMember, _observer.Members);
    }

    [Fact]
    public void Open_TwiceOnOneSession_IsRunInProgress()
    {
        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);
        string probeId = Probe(dispatcher);
        dispatcher.Dispatch(OpenRequest(probeId));

        Assert.Equal(
            RemodelErrorCodes.RunInProgress, Refusal(dispatcher.Dispatch(OpenRequest(probeId))));
    }

    [Fact]
    public void Open_ASourceDirtiedBetweenTheProbeAndTheRun_IsRefusedBeforeTheCopy()
    {
        FakeRemodelSeat seat = Seat();
        SwBridgeDispatcher dispatcher = Dispatcher(seat);
        string probeId = Probe(dispatcher);

        seat.Probe.SaveFlag = true;

        Assert.Equal(
            RemodelErrorCodes.SourceDirty, Refusal(dispatcher.Dispatch(OpenRequest(probeId))));
        Assert.False(File.Exists(_copyPath));
    }

    // ---- remodel.snapshot ------------------------------------------------------------

    [Fact]
    public void Snapshot_IsKeyedByPersistRefAndCarriesTheCountsAndEquations()
    {
        FakeRemodelSeat seat = Seat();
        seat.Copy!.Features[1].Description = null;
        seat.Copy.EquationManager.Equations.Add("\"w\" = 120");
        SwBridgeDispatcher dispatcher = Opened(seat);

        var result = Ok<RemodelSnapshotResult>(
            dispatcher.Dispatch(Request("9", RemodelCommands.Snapshot, "{}")));

        Assert.Equal(new[] { "ref:boss", "ref:fillet" }, result.Order);
        Assert.Equal("Boss-Extrude1", result.Names["ref:boss"]);

        // null is unreadable, which is not "" (absent): an inverse that wrote "" over
        // something unreadable would be a silent edit.
        Assert.Equal(string.Empty, result.Descriptions["ref:boss"]);
        Assert.Null(result.Descriptions["ref:fillet"]);

        Assert.Equal(2, result.FeatureCount);
        Assert.Equal(0, result.RebuildErrors);

        Ir.Equation equation = Assert.Single(result.Equations);
        Assert.Equal("\"w\" = 120", equation.Text);
        Assert.Equal("w", equation.Lhs);
        Assert.Equal(0, equation.Index);
    }

    [Fact]
    public void Snapshot_AnUnreadableEquation_IsReportedAndNotDropped()
    {
        // The snapshot is what the executor diffs before and after every change. A row whose
        // text will not read cannot become an IR Equation - Equation.text is a string and an
        // empty one would be a default written over engineering data - so it is named in
        // unreadable_equation_indexes instead. A quietly shorter equations[] with nothing
        // recording it is the failure this pins.
        FakeRemodelSeat seat = Seat();
        seat.Copy!.EquationManager.Equations.Add("\"w\" = 120");
        seat.Copy.EquationManager.Equations.Add("\"t\" = 4");
        seat.Copy.EquationManager.UnreadableIndexes.Add(0);
        SwBridgeDispatcher dispatcher = Opened(seat);

        var result = Ok<RemodelSnapshotResult>(
            dispatcher.Dispatch(Request("9", RemodelCommands.Snapshot, "{}")));

        Ir.Equation equation = Assert.Single(result.Equations);
        Assert.Equal("\"t\" = 4", equation.Text);

        // The surviving row keeps the index the manager addresses it by, and the missing one
        // is named rather than inferred from a gap in the indexes.
        Assert.Equal(1, equation.Index);
        Assert.Equal(new[] { 0 }, result.UnreadableEquationIndexes);
    }

    [Fact]
    public void Snapshot_EveryEquationReadable_NamesNoUnreadableRow()
    {
        FakeRemodelSeat seat = Seat();
        seat.Copy!.EquationManager.Equations.Add("\"w\" = 120");
        SwBridgeDispatcher dispatcher = Opened(seat);

        var result = Ok<RemodelSnapshotResult>(
            dispatcher.Dispatch(Request("9", RemodelCommands.Snapshot, "{}")));

        Assert.Empty(result.UnreadableEquationIndexes);
    }

    [Fact]
    public void Snapshot_BeforeOpen_IsRefusedBecauseThereIsNoDocumentToReach()
    {
        Assert.Equal(
            RemodelErrorCodes.TargetMismatch,
            Refusal(Dispatcher(Seat()).Dispatch(Request("9", RemodelCommands.Snapshot, "{}"))));
    }

    [Fact]
    public void Snapshot_TakesNoParametersAndIgnoresOneThatNamesADocument()
    {
        // The target is unreachable, not validated: a member the table does not declare is
        // simply not read, and the snapshot is of the scope's copy either way.
        SwBridgeDispatcher dispatcher = Opened(Seat());

        var result = Ok<RemodelSnapshotResult>(dispatcher.Dispatch(
            Request(
                "9",
                RemodelCommands.Snapshot,
                "{\"document\":\"C:\\\\work\\\\somebody-elses.SLDPRT\"}")));

        Assert.Equal(2, result.FeatureCount);
    }

    // ---- helpers ---------------------------------------------------------------------

    /// <summary>A two-feature copy and a source SOLIDWORKS already has open.</summary>
    private FakeRemodelSeat Seat()
    {
        var copy = new FakeRemodelDocument(
            Path.GetFullPath(_copyPath),
            new FakeFeature("ref:boss", "Boss-Extrude1"),
            new FakeFeature("ref:fillet", "Fillet1"));

        return new FakeRemodelSeat(new FakeProbeSource(), copy);
    }

    private SwBridgeDispatcher Dispatcher(FakeRemodelSeat seat) => Dispatcher(seat, _runDirectory);

    private SwBridgeDispatcher Dispatcher(FakeRemodelSeat seat, string? runRoot)
    {
        var services = new BridgeServices(
            new FakeCaptureView(),
            new FakeMeasureSource("no measure source in this test"),
            new FakeInterferenceSource(new FakeInterferenceDetector()),
            new ComponentIndex(new ComponentTreeResult()),
            _root)
        {
            RemodelSeat = seat,
            RemodelGate = new SwGate(new CircuitBreaker(), new RemodelGuard()) { Observer = _observer },

            // The run folder is the host's, exactly as RunFolders.CreateForRemodel hands it
            // over, and never one derived from a request's copy_path.
            RemodelRunRoot = runRoot,
        };

        return new SwBridgeDispatcher(services, NoSecretPolicy.Instance);
    }

    /// <summary>A dispatcher with the probe done and the copy open.</summary>
    private SwBridgeDispatcher Opened(FakeRemodelSeat seat)
    {
        SwBridgeDispatcher dispatcher = Dispatcher(seat);
        BridgeResponse response = dispatcher.Dispatch(OpenRequest(Probe(dispatcher)));
        Assert.Equal(BridgeStatus.Ok, response.Status);
        return dispatcher;
    }

    private string Probe(SwBridgeDispatcher dispatcher) =>
        Ok<RemodelProbeScopeResult>(dispatcher.Dispatch(ProbeRequest())).ProbeId;

    private BridgeRequest ProbeRequest(string? sourcePath = null) =>
        Request(
            "1",
            RemodelCommands.ProbeScope,
            "{\"source_path\":" + JsonSerializer.Serialize(sourcePath ?? _sourcePath) + "}");

    private BridgeRequest OpenRequest(string probeId, string? copyPath = null) =>
        Request(
            "2",
            RemodelCommands.Open,
            "{\"source_path\":" + JsonSerializer.Serialize(_sourcePath)
            + ",\"copy_path\":" + JsonSerializer.Serialize(copyPath ?? _copyPath)
            + ",\"run_id\":" + JsonSerializer.Serialize(RunId)
            + ",\"probe_id\":" + JsonSerializer.Serialize(probeId) + "}");

    private static BridgeRequest Request(string id, string command, string paramsJson) =>
        JsonSerializer.Deserialize<BridgeRequest>(
            $"{{\"id\":\"{id}\",\"command\":\"{command}\",\"params\":{paramsJson}}}",
            BridgeCodec.Options)!;

    private static T Ok<T>(BridgeResponse response)
    {
        Assert.Equal(BridgeStatus.Ok, response.Status);
        return Assert.IsType<T>(response.Result);
    }

    /// <summary>The stable token a refused response carries in <c>result.error_code</c>.</summary>
    private static string Refusal(BridgeResponse response)
    {
        Assert.Equal(BridgeStatus.Error, response.Status);
        return Assert.IsType<RemodelErrorResult>(response.Result).ErrorCode;
    }
}
