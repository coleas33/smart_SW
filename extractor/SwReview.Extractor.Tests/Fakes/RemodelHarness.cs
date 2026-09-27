using System;
using System.IO;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// A bridge with a remodel seat behind it, a real run folder on disk and a source file to copy
/// from: everything the <c>remodel.*</c> handlers need and nothing SOLIDWORKS.
///
/// <see cref="Open"/> drives <c>remodel.probe_scope</c> and <c>remodel.open</c>, so a test of a
/// command that runs on the scope starts where that command starts. The open sequence itself
/// has its own suite, <c>RemodelOpenHandlerTests</c>, which wires the bridge explicitly because
/// what it asserts on <i>is</i> the wiring.
///
/// The Start switch (004 T172) is <b>on</b> by default here, because most of what this harness
/// drives is the change commands only a validated build answers; a test of the switch itself
/// builds its harness with the switch it means.
/// </summary>
public sealed class RemodelHarness : IDisposable
{
    public const string RunId = "20260916-142201-bracket-remodel";

    public RemodelHarness(params FakeFeature[] features)
        : this(true, features)
    {
    }

    /// <param name="startValidated">The Start switch the dispatcher is built with (004 T172).</param>
    /// <param name="features">The copy's feature tree, top to bottom.</param>
    public RemodelHarness(bool startValidated, params FakeFeature[] features)
    {
        Root = Path.Combine(Path.GetTempPath(), "swreview-remodel", Guid.NewGuid().ToString("N"));
        RunDirectory = Path.Combine(Root, RunId);
        SourcePath = Path.Combine(Root, "work", "bracket.SLDPRT");

        Directory.CreateDirectory(Path.GetDirectoryName(SourcePath)!);
        Directory.CreateDirectory(RunDirectory);
        File.WriteAllText(SourcePath, "not really a part, but a file with bytes and a hash");

        CopyPath = Path.GetFullPath(RemodelCopy.CopyPathFor(RunDirectory, SourcePath));
        Copy = new FakeRemodelDocument(CopyPath, features);
        Seat = new FakeRemodelSeat(new FakeProbeSource(), Copy);
        Gate = new SwGate(new CircuitBreaker(), new RemodelGuard()) { Observer = Observer };

        Services = new BridgeServices(
            new FakeCaptureView(),
            new FakeMeasureSource("no measure source in this test"),
            new FakeInterferenceSource(new FakeInterferenceDetector()),
            new ComponentIndex(new ComponentTreeResult()),
            Root)
        {
            RemodelSeat = Seat,
            RemodelGate = Gate,
            RemodelRunRoot = RunDirectory,
        };

        Dispatcher = new SwBridgeDispatcher(Services, NoSecretPolicy.Instance, startValidated);
    }

    /// <summary>What the dispatcher was built with, so a test can read the run root it holds.</summary>
    public BridgeServices Services { get; }

    public string Root { get; }

    public string RunDirectory { get; }

    public string SourcePath { get; }

    public string CopyPath { get; }

    public FakeRemodelDocument Copy { get; }

    public FakeRemodelSeat Seat { get; }

    public SwGate Gate { get; }

    public RecordingGateObserver Observer { get; } = new RecordingGateObserver();

    public SwBridgeDispatcher Dispatcher { get; }

    public void Dispose()
    {
        if (Directory.Exists(Root))
        {
            Directory.Delete(Root, recursive: true);
        }
    }

    /// <summary>
    /// Bind this run's folder, probe, then open, asserting both succeeded. The state every scope
    /// command needs. The bind is the host's, before every open (004 T158): <c>remodel.open</c>
    /// uses the bound root up, so a second open in one test needs a second bind, as a second run
    /// does.
    /// </summary>
    public void Open()
    {
        Dispatcher.BindRemodelRun(RunDirectory);

        var probe = Ok<RemodelProbeScopeResult>(Dispatch(
            RemodelCommands.ProbeScope,
            "{\"source_path\":" + JsonSerializer.Serialize(SourcePath) + "}"));

        Ok<RemodelOpenResult>(Dispatch(
            RemodelCommands.Open,
            "{\"source_path\":" + JsonSerializer.Serialize(SourcePath)
            + ",\"copy_path\":" + JsonSerializer.Serialize(CopyPath)
            + ",\"run_id\":" + JsonSerializer.Serialize(RunId)
            + ",\"probe_id\":" + JsonSerializer.Serialize(probe.ProbeId) + "}"));

        Copy.Members.Clear();
        Copy.EquationManager.Members.Clear();
    }

    /// <summary>
    /// The two readings the geometry gate is reached from - the baseline and the one after the
    /// last change - taken through the bridge, so a test of <c>remodel.save</c> starts where a
    /// real run's save starts: after the gate has actually run.
    /// </summary>
    public void GeometryGate()
    {
        Ok<GeometryReading>(Dispatch(RemodelCommands.Geometry, "{}"));
        Ok<GeometryReading>(Dispatch(RemodelCommands.Geometry, "{}"));
    }

    /// <summary><c>remodel.save</c>'s params: the verdict Python reached, and nothing else.</summary>
    public static string SaveParams(string verdict) =>
        "{\"verdict\":" + JsonSerializer.Serialize(verdict) + "}";

    public BridgeResponse Dispatch(string command, string paramsJson) =>
        Dispatcher.Dispatch(
            JsonSerializer.Deserialize<BridgeRequest>(
                $"{{\"id\":\"1\",\"command\":\"{command}\",\"params\":{paramsJson}}}",
                BridgeCodec.Options)!);

    public static T Ok<T>(BridgeResponse response)
    {
        Assert.Equal(BridgeStatus.Ok, response.Status);
        return Assert.IsType<T>(response.Result);
    }

    /// <summary>The stable token a refused response carries in <c>result.error_code</c>.</summary>
    public static string Refusal(BridgeResponse response)
    {
        Assert.Equal(BridgeStatus.Error, response.Status);
        return Assert.IsType<RemodelErrorResult>(response.Result).ErrorCode;
    }
}
