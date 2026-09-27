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

    private static readonly byte[] BossRef = { 1, 1, 1 };
    private static readonly byte[] CutRef = { 2, 2, 2 };

    private readonly string _root;
    private readonly string _runDirectory;
    private readonly string _sourcePath;
    private readonly string _copyPath;

    private readonly InteropRecorder<ISldWorks> _application = new InteropRecorder<ISldWorks>();
    private readonly InteropRecorder<IDocumentSpecification> _specification = new InteropRecorder<IDocumentSpecification>();
    private readonly StandInDocument _source = new StandInDocument();
    private readonly StandInDocument _copy = new StandInDocument();
    private readonly InteropRecorder<Feature> _boss = StandInDocument.Feature("Boss-Extrude1");
    private readonly InteropRecorder<Feature> _cut = StandInDocument.Feature("Cut-Extrude1");
    private readonly InteropRecorder<EquationMgr> _equations = new InteropRecorder<EquationMgr>();
    private readonly InteropRecorder<IMassProperty2> _massProperty = new InteropRecorder<IMassProperty2>();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();

    private bool _copyOpen;
    private string? _tag;

    public RemodelSeatBridgeTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "swreview-seat-bridge", Guid.NewGuid().ToString("N"));
        _runDirectory = Path.Combine(_root, RunId);
        _sourcePath = Path.Combine(_root, "work", "bracket.SLDPRT");
        Directory.CreateDirectory(Path.GetDirectoryName(_sourcePath)!);
        Directory.CreateDirectory(_runDirectory);
        File.WriteAllText(_sourcePath, "the engineer's part, as bytes the attestation hashes");
        _copyPath = Path.GetFullPath(RemodelCopy.CopyPathFor(_runDirectory, _sourcePath));

        WireApplication();
        WirePart(_source);
        WirePart(_copy);
        WireCopy();
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
        Assert.Equal(RunId, _tag);

        var snapshot = Ok<RemodelSnapshotResult>(dispatcher.Dispatch(Request(RemodelCommands.Snapshot, new { })));
        Assert.Equal(new[] { PersistRefCodec.Encode(BossRef), PersistRefCodec.Encode(CutRef) }, snapshot.Order);
        Assert.Equal("Boss-Extrude1", snapshot.Names[PersistRefCodec.Encode(BossRef)]);
        Assert.Equal("\"w\" = 120", Assert.Single(snapshot.Equations).Text);

        var rename = Ok<RemodelRenameResult>(dispatcher.Dispatch(Request(
            RemodelCommands.Rename, new { persist_ref = PersistRefCodec.Encode(CutRef), new_name = "Cut-Pocket1" })));
        Assert.Equal("Cut-Extrude1", rename.PreviousName);
        Assert.Equal(new object?[] { "Cut-Pocket1" }, Assert.Single(_cut.Calls, call => call.Member == "set_Name").Arguments);

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
        Assert.All(_source.AllMembers(), member => Assert.Contains(member, SourceReads));
        Assert.DoesNotContain(_application.Calls, call => call.Member != "GetOpenDocumentByName" && call.Arguments.Contains(_sourcePath));

        // The copy: opened once at its own path with the pinned specification, closed once.
        Assert.Equal(new object?[] { _copyPath }, Assert.Single(_application.Calls, call => call.Member == "GetOpenDocSpec").Arguments);
        Assert.Single(_application.Calls, call => call.Member == "OpenDoc7");
        Assert.Equal(new object?[] { _copyPath }, Assert.Single(_application.Calls, call => call.Member == "CloseDoc").Arguments);
        Assert.Contains(("set_Silent", (object?)true), _specification.Calls.Select(call => (call.Member, call.Arguments[0])));
        Assert.Contains(("set_ReadOnly", (object?)false), _specification.Calls.Select(call => (call.Member, call.Arguments[0])));
        Assert.Contains(("set_ViewOnly", (object?)false), _specification.Calls.Select(call => (call.Member, call.Arguments[0])));

        // The tag went on at open and came off at close; the copy was never saved.
        Assert.Null(_tag);
        Assert.DoesNotContain("Save3", _copy.Document.Members);

        // The four settings were set and put back, CommandInProgress last each time.
        List<object?[]> commandInProgress = _application.Calls.Where(call => call.Member == "set_CommandInProgress").Select(call => call.Arguments).ToList();
        Assert.Equal(new[] { new object?[] { true }, new object?[] { false } }, commandInProgress);
        Assert.Equal("set_CommandInProgress", _application.Calls.Last(call => call.Member.StartsWith("Set", StringComparison.Ordinal) || call.Member.StartsWith("set_", StringComparison.Ordinal)).Member);
    }

    /// <summary>A source SOLIDWORKS does not have open is refused, and the seat does not open it to answer.</summary>
    [Fact]
    public void ASourceThatIsNotOpenIsRefusedAndNeverOpened()
    {
        _application.Handle("GetOpenDocumentByName", arguments => null);

        BridgeResponse response = Dispatcher().Dispatch(Request(RemodelCommands.ProbeScope, new { source_path = _sourcePath }));

        Assert.Equal(RemodelErrorCodes.SourceNotOpen, Assert.IsType<RemodelErrorResult>(response.Result).ErrorCode);
        Assert.Equal(new[] { "GetOpenDocumentByName" }, _application.Members);
        Assert.Empty(_source.AllMembers());
    }

    /// <summary>
    /// A failed open is <c>open_failed</c> naming the load error, and the bridge's own cleanup runs as
    /// it does for any failed open: the copy it made is deleted and the four settings are put back.
    /// </summary>
    [Fact]
    public void AFailedOpenIsOpenFailedAndTheBridgeCleansUp()
    {
        _application.Handle("OpenDoc7", arguments => null);
        _specification.Answer("get_Error", 2);
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
            _application.Calls.Where(call => call.Member == "set_CommandInProgress").Select(call => call.Arguments));
    }

    // ---- the world -------------------------------------------------------------------------------------

    /// <summary>What the source may be asked: the probe's reads and the accessors that reach them.</summary>
    private static readonly HashSet<string> SourceReads = new HashSet<string>(StringComparer.Ordinal)
    {
        "IModelDoc2.GetType", "IModelDoc2.GetSaveFlag", "IModelDoc2.ListExternalFileReferencesCount2",
        "IModelDoc2.GetBodies2", "IModelDoc2.IsWeldment", "IModelDoc2.get_FeatureManager", "IModelDoc2.GetConfigurationNames",
        "IModelDoc2.get_Extension", "IFeatureManager.GetSheetMetalFolder", "IFeatureManager.GetFeatures",
        "IModelDocExtension.GetPersistReference3",
    };

    private void WireApplication()
    {
        _application
            .Handle("GetOpenDocumentByName", arguments =>
            {
                string path = (string)arguments[0]!;
                if (string.Equals(path, _sourcePath, StringComparison.OrdinalIgnoreCase))
                {
                    return _source.Instance;
                }

                return _copyOpen && string.Equals(path, _copyPath, StringComparison.OrdinalIgnoreCase) ? _copy.Instance : null;
            })
            .Answer("GetOpenDocSpec", _specification.Instance)
            .Handle("OpenDoc7", arguments =>
            {
                _copyOpen = true;
                return _copy.Instance;
            })
            .Handle("CloseDoc", arguments =>
            {
                _copyOpen = false;
                return null;
            })
            .Answer("GetUserPreferenceToggle", true)
            .Answer("get_CommandInProgress", false);
    }

    /// <summary>The same part, read the same way, for the source and its byte copy: step 12 compares them.</summary>
    private void WirePart(StandInDocument part)
    {
        var body = new InteropRecorder<IBody2>().Answer("GetFaceCount", 6).Answer("GetEdgeCount", 12);
        part.Document
            .Answer("GetType", 1)
            .Answer("GetSaveFlag", false)
            .Answer("ListExternalFileReferencesCount2", 0)
            .Answer("IsWeldment", false)
            .Answer("GetConfigurationNames", new[] { "Default" });
        part.WithBodies(new Dictionary<int, object?> { [0] = new object[] { body.Instance }, [-1] = new object[] { body.Instance } });
        part.WithFeatures(_boss, _cut);
        part.WithPersistReferences(new Dictionary<object, byte[]> { [_boss.Instance] = BossRef, [_cut.Instance] = CutRef });
    }

    /// <summary>The copy's own answers: its path, the tag, the rollback, the rebuild, the units, the geometry.</summary>
    private void WireCopy()
    {
        _copy.Document
            .Answer("GetPathName", _copyPath)
            .Answer("ForceRebuild3", true)
            .Answer("GetUnits", new[] { 0, 0, 2, 3, 0 })
            .Answer("GetEquationMgr", _equations.Instance)
            .Answer("GetMaterialPropertyName2", "6061-T6");
        _copy.ActiveConfiguration.Answer("get_Name", "Default");
        _copy.Manager.Answer("EditRollback", true);
        _copy.Extension
            .Answer("GetWhatsWrongCount", 0)
            .Answer("CreateMassProperty2", _massProperty.Instance)
            .Handle("GetObjectByPersistReference3", arguments =>
            {
                var bytes = (byte[])arguments[0]!;
                arguments[1] = 0;
                return bytes.SequenceEqual(BossRef) ? _boss.Instance : bytes.SequenceEqual(CutRef) ? _cut.Instance : (object?)null;
            });
        _copy.Properties
            .Handle("Add3", arguments =>
            {
                _tag = (string)arguments[2]!;
                return 1;
            })
            .Handle("Get4", arguments =>
            {
                arguments[2] = _tag ?? string.Empty;
                arguments[3] = _tag ?? string.Empty;
                return _tag != null;
            })
            .Handle("Delete2", arguments =>
            {
                _tag = null;
                return 0;
            });
        _equations.Answer("GetCount", 1).Answer("get_Equation", "\"w\" = 120");
        _massProperty
            .Answer("Recalculate", true)
            .Answer("get_Volume", 0.000125)
            .Answer("get_SurfaceArea", 0.015)
            .Answer("get_CenterOfMass", new[] { 0.0, 0.0, 0.0025 })
            .Answer("get_PrincipalMomentsOfInertia", new[] { 1e-6, 2e-6, 3e-6 })
            .Answer("get_Mass", 0.3375)
            .Answer("get_Density", 2700.0);
    }

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
            RemodelSeat = new SwRemodelBridgeSeat(_application.Instance),
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
