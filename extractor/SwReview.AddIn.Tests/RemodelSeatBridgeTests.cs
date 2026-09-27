using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Remodel.Seat;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Measure;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004, build order lane B: the seat adapter fits the bridge. The real
/// <see cref="SwBridgeDispatcher"/> runs a whole Plan and Discard's worth of <c>remodel.*</c>
/// commands - probe, open, snapshot, a rename, geometry, rebuild and close - through the real
/// <see cref="SwRemodelBridgeSeat"/>, over recording stand-ins for SOLIDWORKS, the source and the
/// copy. So the adapter is exercised by the one consumer it is written for, with the bridge's own
/// gate around it, rather than only member by member.
///
/// What it pins: every command answers; the gate refuses nothing; the engineer's source is only
/// ever read and is never opened, closed, saved or written; the copy is opened once, at its own
/// path, with the pinned specification, and closed once; the tag round-trips; <c>VerifyTarget</c>'s
/// COM identity check passes on the document the seat opened; and the four settings are put back.
/// SOLIDWORKS is never started: what a real seat answers is the sitting's (research R13.8).
/// </summary>
public sealed class RemodelSeatBridgeTests : IDisposable
{
    private const string RunId = "20260927-100000-bracket-remodel";

    private readonly string _root;
    private readonly string _runDirectory;
    private readonly string _sourcePath;
    private readonly string _copyPath;

    private readonly StandInSolidworks _solidworks;
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();

    public RemodelSeatBridgeTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "swreview-seat-bridge", Guid.NewGuid().ToString("N"));
        _runDirectory = Path.Combine(_root, RunId);
        _sourcePath = Path.Combine(_root, "work", "bracket.SLDPRT");
        Directory.CreateDirectory(Path.GetDirectoryName(_sourcePath)!);
        Directory.CreateDirectory(_runDirectory);
        File.WriteAllText(_sourcePath, "the engineer's part, as bytes the attestation hashes");
        _copyPath = Path.GetFullPath(RemodelCopy.CopyPathFor(_runDirectory, _sourcePath));
        _solidworks = new StandInSolidworks(_sourcePath);
    }

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    [Fact]
    public void PlanAndDiscardRunThroughTheSeatWithTheSourceOnlyEverRead()
    {
        byte[] sourceBefore = File.ReadAllBytes(_sourcePath);
        SwBridgeDispatcher dispatcher = Dispatcher();

        var probe = Ok<RemodelProbeScopeResult>(dispatcher.Dispatch(Request(RemodelCommands.ProbeScope, new { source_path = _sourcePath })));
        Assert.Equal(1, probe.ScopeSignals!.DocumentType);
        Assert.Equal(1, probe.ScopeSignals.SolidBodyCount);
        Assert.Equal(0, probe.ScopeSignals.SheetBodyCount);
        Assert.False(probe.ScopeSignals.MeshBodyPresent);
        Assert.Equal(new[] { "Default" }, probe.ScopeSignals.ConfigurationNames);
        Assert.Empty(probe.ScopeSignals.RmsNamedFolders!);
        Assert.Equal(new[] { "Extrusion", "Extrusion" }, probe.ScopeSignals.FeatureTypeNames);
        Assert.Null(probe.ScopeSignals.Vault);

        var open = Ok<RemodelOpenResult>(dispatcher.Dispatch(Request(
            RemodelCommands.Open,
            new { source_path = _sourcePath, copy_path = _copyPath, run_id = RunId, probe_id = probe.ProbeId })));
        Assert.Equal(_copyPath, open.DocumentPath);
        Assert.Equal(RunId, open.Tag);
        Assert.Equal(2, open.FeatureCount);
        Assert.Equal("mm", open.DocumentLengthUnit);
        Assert.Equal(probe.ScopeSignals.FeatureTypeNames, open.ScopeSignals!.FeatureTypeNames);
        Assert.Null(open.SourceAttestation!.VaultPath);
        Assert.True(File.Exists(_copyPath));
        Assert.Equal(RunId, _solidworks.Tag);

        var snapshot = Ok<RemodelSnapshotResult>(dispatcher.Dispatch(Request(RemodelCommands.Snapshot, new { })));
        Assert.Equal(new[] { PersistRefCodec.Encode(StandInSolidworks.BossRef), PersistRefCodec.Encode(StandInSolidworks.CutRef) }, snapshot.Order);
        Assert.Equal("Boss-Extrude1", snapshot.Names[PersistRefCodec.Encode(StandInSolidworks.BossRef)]);
        Assert.Equal("\"w\" = 120", Assert.Single(snapshot.Equations).Text);

        var rename = Ok<RemodelRenameResult>(dispatcher.Dispatch(Request(
            RemodelCommands.Rename, new { persist_ref = PersistRefCodec.Encode(StandInSolidworks.CutRef), new_name = "Cut-Pocket1" })));
        Assert.Equal("Cut-Extrude1", rename.PreviousName);
        Assert.Equal(new object?[] { "Cut-Pocket1" }, Assert.Single(_solidworks.Cut.Calls, call => call.Member == "set_Name").Arguments);

        var geometry = Ok<GeometryReading>(dispatcher.Dispatch(Request(RemodelCommands.Geometry, new { })));
        Assert.Equal(RemodelGeometry.StatusOk, geometry.Status);
        Assert.Equal(0.000125, geometry.VolumeM3);
        Assert.Equal("6061-T6", geometry.MaterialName);

        var rebuild = Ok<RemodelRebuildResult>(dispatcher.Dispatch(Request(RemodelCommands.Rebuild, new { force = false })));
        Assert.Equal(0, rebuild.RebuildErrors);
        Assert.Equal(2, rebuild.FeatureErrors.Count);

        var close = Ok<RemodelCloseResult>(dispatcher.Dispatch(Request(RemodelCommands.Close, new { discard_copy = false })));
        Assert.True(close.Closed);
        Assert.False(close.CopyDeleted);

        // The gate refused nothing, and every write it saw was on the stage-1 allowlist.
        Assert.Empty(_observer.Refusals);

        // The source: read, never opened, closed, saved or written, and its bytes unchanged.
        Assert.Equal(sourceBefore, File.ReadAllBytes(_sourcePath));
        Assert.All(_solidworks.Source.AllMembers(), member => Assert.Contains(member, StandInSolidworks.SourceReads));
        Assert.DoesNotContain(_solidworks.Application.Calls, call => call.Member != "GetOpenDocumentByName" && call.Arguments.Contains(_sourcePath));

        // The copy: opened once at its own path with the pinned specification, closed once.
        Assert.Equal(new object?[] { _copyPath }, Assert.Single(_solidworks.Application.Calls, call => call.Member == "GetOpenDocSpec").Arguments);
        Assert.Single(_solidworks.Application.Calls, call => call.Member == "OpenDoc7");
        Assert.Equal(new object?[] { _copyPath }, Assert.Single(_solidworks.Application.Calls, call => call.Member == "CloseDoc").Arguments);
        Assert.Contains(("set_Silent", (object?)true), _solidworks.Specification.Calls.Select(call => (call.Member, call.Arguments[0])));
        Assert.Contains(("set_ReadOnly", (object?)false), _solidworks.Specification.Calls.Select(call => (call.Member, call.Arguments[0])));
        Assert.Contains(("set_ViewOnly", (object?)false), _solidworks.Specification.Calls.Select(call => (call.Member, call.Arguments[0])));

        // The tag went on at open and came off at close; the copy was never saved.
        Assert.Null(_solidworks.Tag);
        Assert.DoesNotContain("Save3", _solidworks.Copy.Document.Members);

        // The four settings were set and put back, CommandInProgress last each time.
        List<object?[]> commandInProgress = _solidworks.Application.Calls.Where(call => call.Member == "set_CommandInProgress").Select(call => call.Arguments).ToList();
        Assert.Equal(new[] { new object?[] { true }, new object?[] { false } }, commandInProgress);
        Assert.Equal("set_CommandInProgress", _solidworks.Application.Calls.Last(call => call.Member.StartsWith("Set", StringComparison.Ordinal) || call.Member.StartsWith("set_", StringComparison.Ordinal)).Member);
    }

    /// <summary>A source SOLIDWORKS does not have open is refused, and the seat does not open it to answer.</summary>
    [Fact]
    public void ASourceThatIsNotOpenIsRefusedAndNeverOpened()
    {
        _solidworks.Application.Handle("GetOpenDocumentByName", arguments => null);

        BridgeResponse response = Dispatcher().Dispatch(Request(RemodelCommands.ProbeScope, new { source_path = _sourcePath }));

        Assert.Equal(RemodelErrorCodes.SourceNotOpen, Assert.IsType<RemodelErrorResult>(response.Result).ErrorCode);
        Assert.Equal(new[] { "GetOpenDocumentByName" }, _solidworks.Application.Members);
        Assert.Empty(_solidworks.Source.AllMembers());
    }

    /// <summary>
    /// A failed open is <c>open_failed</c> naming the load error, and the bridge's own cleanup runs as
    /// it does for any failed open: the copy it made is deleted and the four settings are put back.
    /// </summary>
    [Fact]
    public void AFailedOpenIsOpenFailedAndTheBridgeCleansUp()
    {
        _solidworks.Application.Handle("OpenDoc7", arguments => null);
        _solidworks.Specification.Answer("get_Error", 2);
        SwBridgeDispatcher dispatcher = Dispatcher();
        var probe = Ok<RemodelProbeScopeResult>(dispatcher.Dispatch(Request(RemodelCommands.ProbeScope, new { source_path = _sourcePath })));

        BridgeResponse response = dispatcher.Dispatch(Request(
            RemodelCommands.Open,
            new { source_path = _sourcePath, copy_path = _copyPath, run_id = RunId, probe_id = probe.ProbeId }));

        Assert.Equal(RemodelErrorCodes.OpenFailed, Assert.IsType<RemodelErrorResult>(response.Result).ErrorCode);
        Assert.Contains("swFileNotFoundError", response.Error, StringComparison.Ordinal);
        Assert.False(File.Exists(_copyPath));
        Assert.Equal(
            new[] { new object?[] { true }, new object?[] { false } },
            _solidworks.Application.Calls.Where(call => call.Member == "set_CommandInProgress").Select(call => call.Arguments));
    }

    // ---- the world -------------------------------------------------------------------------------------

    private SwBridgeDispatcher Dispatcher()
    {
        InteropRecorder<ICaptureView> unused = new InteropRecorder<ICaptureView>(typeof(IMeasureSource), typeof(IInterferenceSource));
        var services = new BridgeServices(
            unused.Instance,
            unused.As<IMeasureSource>(),
            unused.As<IInterferenceSource>(),
            new ComponentIndex(new ComponentTreeResult()),
            _root)
        {
            RemodelSeat = new SwRemodelBridgeSeat(_solidworks.Application.Instance),
            RemodelGate = new SwGate(new CircuitBreaker(), new RemodelGuard()) { Observer = _observer },
            RemodelRunRoot = _runDirectory,
        };

        // The Start switch on (004 T172): this runs one change command, a rename, which a build
        // with Start switched off answers `start_not_validated` before the seat is asked anything.
        return new SwBridgeDispatcher(services, NoSecretPolicy.Instance, startValidated: true);
    }

    private static BridgeRequest Request(string command, object parameters) =>
        JsonSerializer.Deserialize<BridgeRequest>(
            "{\"id\":\"1\",\"command\":\"" + command + "\",\"params\":" + JsonSerializer.Serialize(parameters) + "}",
            BridgeCodec.Options)!;

    private static T Ok<T>(BridgeResponse response)
    {
        Assert.True(response.Status == BridgeStatus.Ok, "the bridge answered: " + response.Error);
        return Assert.IsType<T>(response.Result);
    }
}
