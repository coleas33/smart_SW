using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Measure;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T072, the command half. The dispatcher is driven with fakes, so every branch a client can
/// reach is exercised without SOLIDWORKS: the four commands, the guard, the circuit breaker,
/// and every way a request can be wrong.
///
/// The shapes asserted here are the ones Serve/PROTOCOL.md promises the Python client.
/// </summary>
public class BridgeDispatcherTests : IDisposable
{
    private readonly string _captureDirectory;
    private readonly FakeCaptureView _captureView = new FakeCaptureView();

    public BridgeDispatcherTests()
    {
        _captureDirectory = Path.Combine(
            Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_captureDirectory))
        {
            Directory.Delete(_captureDirectory, recursive: true);
        }
    }

    // ---- the envelope ------------------------------------------------------------

    [Fact]
    public void Dispatch_UnknownCommand_ListsTheOnesItAnswers()
    {
        BridgeResponse response = Dispatch(Request("1", "rebuild"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("interference", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Dispatch_CommandNamedAfterAMutatingApi_IsRefusedByTheGuard()
    {
        // The guard sees the command name itself, so a handler for it could never be added
        // by accident (research R4).
        BridgeResponse response = Dispatch(Request("1", "Save3"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("read-only", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Dispatch_EchoesTheRequestId()
    {
        Assert.Equal("abc", Dispatch(Request("abc", BridgeCommands.Ping)).Id);
    }

    [Fact]
    public void Dispatch_CircuitOpen_IsItsOwnStatusNotAnError()
    {
        // The client must stop asking rather than retry, and must record failed coverage.
        var view = new FakeCaptureView
        {
            ThrowOnZoom = new CircuitOpenError("SOLIDWORKS stopped answering"),
        };

        BridgeResponse response = Dispatch(
            Request("1", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\"}"), view);

        Assert.Equal(BridgeStatus.CircuitOpen, response.Status);
        Assert.Null(response.Result);
    }

    // ---- ping --------------------------------------------------------------------

    [Fact]
    public void Ping_SaysWhichDocumentTheWorkerIsOn()
    {
        BridgeResponse response = Dispatch(Request("1", BridgeCommands.Ping));

        var result = Assert.IsType<PingResult>(response.Result);
        Assert.True(result.Pong);
        Assert.Equal(SwBridgeDispatcher.ProtocolVersion, result.Protocol);
        Assert.Equal(@"C:\work\bracket-assy.SLDASM", result.Document);
        Assert.Equal("Default", result.Configuration);
        Assert.Equal(3, result.ComponentCount);
    }

    // ---- capture -----------------------------------------------------------------

    [Fact]
    public void Capture_ReturnsTheIrRowAndAnAbsolutePath()
    {
        BridgeResponse response = Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\",\"view\":\"iso\"}"));

        Assert.Equal(BridgeStatus.Ok, response.Status);
        var result = Assert.IsType<CaptureCommandResult>(response.Result);
        Assert.Equal("captures/cap-0001.png", result.Capture!.File);
        Assert.True(Path.IsPathRooted(result.Path));
        Assert.True(File.Exists(result.Path));
        Assert.Null(result.Gap);
    }

    [Fact]
    public void Capture_WritesWhereTheHostSaidNotWhereTheClientSaid()
    {
        // A path in a request would be a filesystem write the agent controls (research R4).
        BridgeResponse response = Dispatch(
            Request(
                "2",
                BridgeCommands.Capture,
                "{\"persist_ref\":\"cmVm\",\"out\":\"C:\\\\somewhere-else\"}"));

        var result = Assert.IsType<CaptureCommandResult>(response.Result);
        Assert.StartsWith(_captureDirectory, result.Path!, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Capture_UnknownView_IsRefusedBeforeAnythingRuns()
    {
        BridgeResponse response = Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\",\"view\":\"behind\"}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Empty(_captureView.Calls);
    }

    [Fact]
    public void Capture_MissingPersistRef_NamesTheField()
    {
        BridgeResponse response = Dispatch(Request("2", BridgeCommands.Capture, "{}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("persist_ref", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Capture_ThatFails_StillReturnsTheGap()
    {
        // The client records unresolved coverage instead of losing the request.
        var view = new FakeCaptureView { SelectFailure = "deleted: the entity no longer exists" };

        BridgeResponse response = Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\"}"), view);

        Assert.Equal(BridgeStatus.Error, response.Status);
        var result = Assert.IsType<CaptureCommandResult>(response.Result);
        Assert.Null(result.Capture);
        Assert.NotNull(result.Gap);
        Assert.Equal(CaptureService.GapEntityKind, result.Gap!.EntityKind);
    }

    [Fact]
    public void Capture_IdsContinueAcrossRequestsOnOneConnection()
    {
        var dispatcher = NewDispatcher(_captureView);

        var first = (CaptureCommandResult)dispatcher.Dispatch(
            Request("1", BridgeCommands.Capture, "{\"persist_ref\":\"a\"}")).Result!;
        var second = (CaptureCommandResult)dispatcher.Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"b\"}")).Result!;

        Assert.Equal("cap:0001", first.Capture!.Id);
        Assert.Equal("cap:0002", second.Capture!.Id);
    }

    // ---- measure -----------------------------------------------------------------

    [Fact]
    public void Measure_ReturnsMetresWithTheirUnit()
    {
        var reading = new MeasureReading(0.0123, 0.0123, 0.0, 0.0);
        BridgeResponse response = Dispatch(
            Request(
                "3",
                BridgeCommands.Measure,
                "{\"persist_ref_a\":\"aa\",\"persist_ref_b\":\"bb\"}"),
            measure: new FakeMeasureSource(reading));

        var result = Assert.IsType<MeasureCommandResult>(response.Result);
        Assert.Equal(0.0123, result.Distance!.Value);
        Assert.Equal(LengthUnit.M, result.Distance.Unit);
        Assert.Equal(LengthUnit.M, result.DeltaZ!.Unit);
    }

    [Fact]
    public void Measure_PassesBothReferencesThrough()
    {
        var source = new FakeMeasureSource(new MeasureReading(1.0, 1.0, 0.0, 0.0));
        Dispatch(
            Request(
                "3",
                BridgeCommands.Measure,
                "{\"persist_ref_a\":\"aa\",\"persist_ref_b\":\"bb\"}"),
            measure: source);

        Assert.Equal("aa", source.LastA);
        Assert.Equal("bb", source.LastB);
    }

    [Fact]
    public void Measure_UnsupportedPairing_IsAnErrorWithASentenceNotANumber()
    {
        BridgeResponse response = Dispatch(
            Request(
                "3",
                BridgeCommands.Measure,
                "{\"persist_ref_a\":\"aa\",\"persist_ref_b\":\"bb\"}"),
            measure: new FakeMeasureSource("The Measure tool has no answer for this pairing."));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Null(response.Result);
        Assert.Contains("no answer", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Measure_MissingReference_NamesTheField()
    {
        BridgeResponse response = Dispatch(
            Request("3", BridgeCommands.Measure, "{\"persist_ref_a\":\"aa\"}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("persist_ref_b", response.Error!, StringComparison.Ordinal);
    }

    // ---- interference ------------------------------------------------------------

    [Fact]
    public void Interference_NoComponentIds_ChecksTheWholeAssembly()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(Request("4", BridgeCommands.Interference, "{}"), interference: detector);

        Assert.Empty(Assert.Single(detector.Scopes));
    }

    [Fact]
    public void Interference_TwoComponentIds_ChecksThatPair()
    {
        var detector = new FakeInterferenceDetector();
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");

        Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"component_ids\":[\"cmp:0001\",\"cmp:0002\"]}"),
            interference: detector,
            handles: new[] { a, b });

        Assert.Equal(new object[] { a, b }, Assert.Single(detector.Scopes));
    }

    [Fact]
    public void Interference_MoreThanTwoComponentIds_ChecksEveryUnorderedPair()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"component_ids\":[\"cmp:0001\",\"cmp:0002\",\"cmp:0003\"]}"),
            interference: detector);

        Assert.Equal(3, detector.Scopes.Count);
    }

    [Fact]
    public void Interference_OneComponentId_IsRefused()
    {
        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{\"component_ids\":[\"cmp:0001\"]}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
    }

    [Fact]
    public void Interference_UnknownComponentId_IsRefusedByNameNotDropped()
    {
        // Dropping it would report "no interference" for a pair that was never checked.
        BridgeResponse response = Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"component_ids\":[\"cmp:0001\",\"cmp:9999\"]}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("cmp:9999", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Interference_ReadsTheSettingsFromTheRequest()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"settings\":{\"treat_coincident_as_interference\":true,\"ignore_hidden\":true,"
                + "\"fastener_folder_treatment\":\"only\"}}"),
            interference: detector);

        Assert.True(detector.Properties.TreatCoincidenceAsInterferenceValue);
        Assert.True(detector.Properties.IgnoreHiddenBodiesValue);
        Assert.False(detector.Properties.TreatSubAssembliesAsComponentsValue);
        Assert.Equal(FastenerFolderTreatment.Only, detector.ConfiguredWith!.Fasteners);
    }

    [Fact]
    public void Interference_OmittedSettings_UseTheDialogDefaults()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(Request("4", BridgeCommands.Interference, "{}"), interference: detector);

        Assert.False(detector.Properties.TreatCoincidenceAsInterferenceValue);
        Assert.True(detector.Properties.CreateFastenersFolderValue);
    }

    [Fact]
    public void Interference_BadSettingType_IsAnErrorNamingTheField()
    {
        BridgeResponse response = Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"settings\":{\"ignore_hidden\":\"yes please\"}}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("ignore_hidden", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Interference_ReturnsTheRowsAndTheGaps()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(3.2e-9, a, b) });

        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{}"), interference: detector, handles: new[] { a, b });

        var result = Assert.IsType<InterferenceCommandResult>(response.Result);
        Assert.Equal(InterferenceStatus.Computed, Assert.Single(result.Interferences).Status);

        // Until T069's workstation check, the volume unit is an assumption and says so.
        Assert.Contains(
            result.Gaps, g => g.EntityKind == InterferenceRunner.VolumeUnitGapEntityKind);
    }

    [Fact]
    public void Interference_TruncateAfter_IsHonoured()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var detector = new FakeInterferenceDetector(scope => new IInterferenceResult[]
        {
            new FakeInterferenceResult(1e-9, a, b),
            new FakeInterferenceResult(2e-9, a, b),
        });

        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{\"truncate_after\":1}"),
            interference: detector,
            handles: new[] { a, b });

        var result = Assert.IsType<InterferenceCommandResult>(response.Result);
        Assert.Equal(
            new[] { InterferenceStatus.Computed, InterferenceStatus.Truncated },
            result.Interferences.Select(i => i.Status));
    }

    [Fact]
    public void Interference_ConfigurationDefaultsToTheAttachedOne()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, a, b) });

        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{}"), interference: detector, handles: new[] { a, b });

        var result = Assert.IsType<InterferenceCommandResult>(response.Result);
        Assert.Equal("Default", Assert.Single(result.Interferences).Configuration);
    }

    // ---- helpers -----------------------------------------------------------------

    private static BridgeRequest Request(string id, string command, string? paramsJson = null)
    {
        string line = paramsJson == null
            ? $"{{\"id\":\"{id}\",\"command\":\"{command}\"}}"
            : $"{{\"id\":\"{id}\",\"command\":\"{command}\",\"params\":{paramsJson}}}";

        // Built through the codec so the tests exercise the same parse the pipe does. The
        // guard check happens in Dispatch, not here, so a denied name still gets this far.
        return JsonSerializer.Deserialize<BridgeRequest>(line, BridgeCodec.Options)!;
    }

    private BridgeResponse Dispatch(
        BridgeRequest request,
        FakeCaptureView? capture = null,
        IMeasureSource? measure = null,
        FakeInterferenceDetector? interference = null,
        FakeComponent[]? handles = null)
    {
        return NewDispatcher(capture ?? _captureView, measure, interference, handles).Dispatch(request);
    }

    private SwBridgeDispatcher NewDispatcher(
        FakeCaptureView capture,
        IMeasureSource? measure = null,
        FakeInterferenceDetector? interference = null,
        FakeComponent[]? handles = null)
    {
        var services = new BridgeServices(
            capture,
            measure ?? new FakeMeasureSource("no measure source in this test"),
            new FakeInterferenceSource(interference ?? new FakeInterferenceDetector()),
            Index(handles),
            _captureDirectory)
        {
            SwVersion = "32.5.0",
            DocumentPath = @"C:\work\bracket-assy.SLDASM",
            Configuration = "Default",
        };

        // The command handling, with the secret question answered "yes" - the scopes have
        // their own tests in BridgeSecretPolicyTests.
        return new SwBridgeDispatcher(services, NoSecretPolicy.Instance);
    }

    /// <summary>
    /// A three-component index: cmp:0001, cmp:0002 and cmp:0003, the last two patterned, so
    /// a request can name ids the way the Python side reads them out of package.json.
    /// </summary>
    private static ComponentIndex Index(FakeComponent[]? handles)
    {
        var tree = new ComponentTreeResult { ActiveConfiguration = "Default" };
        tree.Nodes.Add(new ComponentNode
        {
            Key = "bracket-assy-1",
            DocumentPath = @"C:\work\bracket-assy.SLDASM",
            Handle = handles != null && handles.Length > 0 ? handles[0] : null,
        });
        tree.Nodes.Add(new ComponentNode
        {
            Key = "housing-1",
            DocumentPath = @"C:\work\housing.SLDPRT",
            Handle = handles != null && handles.Length > 1 ? handles[1] : null,
        });
        tree.Nodes.Add(new ComponentNode
        {
            Key = "screw-1",
            DocumentPath = @"C:\work\screw.SLDPRT",
            PatternId = "pat:screws",
            Handle = handles != null && handles.Length > 2 ? handles[2] : null,
        });

        return new ComponentIndex(tree);
    }
}
