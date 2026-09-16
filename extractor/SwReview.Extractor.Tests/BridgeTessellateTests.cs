using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Measure;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T096, the host half. The fifth command of the protocol, <c>tessellate</c>: one
/// <c>component_id</c> in, the <c>BodyRef</c> rows it wrote plus their absolute paths out.
///
/// The shapes and the refusals asserted here are the ones Serve/PROTOCOL.md 1.2 promises the
/// Python client, and three of them are behaviour rather than shape:
///
///   * <b>the host chooses the path</b>, exactly as <c>capture</c> does, because a filesystem
///     path in a request is a write the agent controls (research R4);
///   * <b>review scope only</b> - covered by BridgeSecretPolicyTests, which owns the scopes;
///   * a component the exporter could not tessellate comes back <b>ok with no rows and a
///     gap</b>, never an empty answer with nothing said, because the Python side turns "no
///     body came back" into unresolved coverage and needs the reason to name.
///
/// The source itself is faked here: <see cref="SwTessellateSource"/> needs SOLIDWORKS, and
/// what belongs to the dispatcher is which request reaches it and with what.
/// </summary>
public class BridgeTessellateTests : IDisposable
{
    private readonly string _packageDirectory;
    private readonly FakeTessellateSource _meshes = new FakeTessellateSource();

    public BridgeTessellateTests()
    {
        _packageDirectory = Path.Combine(
            Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_packageDirectory))
        {
            Directory.Delete(_packageDirectory, recursive: true);
        }
    }

    [Fact]
    public void Tessellate_IsInTheVocabulary()
    {
        Assert.Contains(BridgeCommands.Tessellate, BridgeCommands.All);
        Assert.Equal("tessellate", BridgeCommands.Tessellate);
    }

    [Fact]
    public void Dispatch_UnknownCommand_ListsTessellateAmongTheOnesItAnswers()
    {
        BridgeResponse response = Dispatch(Request("1", "remesh"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("tessellate", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Tessellate_PassesTheReadOnlyGuard()
    {
        // The guard is a denylist and GetTessellation, Tessellate, CurveChordTolerance and
        // GetBodies2 are not on it: no guard change is needed for this command and none was
        // made. Asserted here so a later prefix added to the denylist cannot silence the
        // command without a red test.
        ReadOnlyGuard.Assert(BridgeCommands.Tessellate);
    }

    [Fact]
    public void Tessellate_ReturnsTheBodyRowsAndTheirAbsolutePaths()
    {
        BridgeResponse response = Dispatch(
            Request("5", BridgeCommands.Tessellate, "{\"component_id\":\"cmp:0002\"}"));

        Assert.Equal(BridgeStatus.Ok, response.Status);
        var result = Assert.IsType<TessellateCommandResult>(response.Result);
        BodyRef body = Assert.Single(result.Bodies);
        Assert.Equal("cmp:0002", body.ComponentId);
        Assert.Equal("meshes/cmp-0002-bod-0001.glb", body.MeshFile);
        string path = Assert.Single(result.Paths);
        Assert.True(Path.IsPathRooted(path));
        Assert.True(File.Exists(path));
        Assert.Empty(result.Gaps);
        Assert.Equal(new[] { "cmp:0002" }, _meshes.Components.ToArray());
    }

    [Fact]
    public void Tessellate_ResultMembersAreTheOnesTheContractNames()
    {
        BridgeResponse response = Dispatch(
            Request("5", BridgeCommands.Tessellate, "{\"component_id\":\"cmp:0002\"}"));

        Assert.Equal(
            new[] { "bodies", "paths", "gaps" },
            MemberNames(response.Result!));
    }

    [Fact]
    public void Tessellate_WritesWhereTheHostSaidNotWhereTheClientSaid()
    {
        // A path in a request would be a filesystem write the agent controls (research R4),
        // so the request's own path fields are ignored exactly as capture ignores them.
        BridgeResponse response = Dispatch(
            Request(
                "5",
                BridgeCommands.Tessellate,
                "{\"component_id\":\"cmp:0002\",\"mesh_directory\":\"C:\\\\somewhere-else\","
                + "\"out\":\"C:\\\\somewhere-else\"}"));

        var result = Assert.IsType<TessellateCommandResult>(response.Result);
        Assert.Equal(new[] { _packageDirectory }, _meshes.Directories.ToArray());
        Assert.StartsWith(_packageDirectory, result.Paths[0], StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Tessellate_UnknownComponent_IsRefusedByName()
    {
        BridgeResponse response = Dispatch(
            Request("5", BridgeCommands.Tessellate, "{\"component_id\":\"cmp:9999\"}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("cmp:9999", response.Error!, StringComparison.Ordinal);
        Assert.Empty(_meshes.Components);
    }

    [Fact]
    public void Tessellate_WithoutAComponentId_NamesTheMissingField()
    {
        BridgeResponse response = Dispatch(Request("5", BridgeCommands.Tessellate, "{}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("component_id", response.Error!, StringComparison.Ordinal);
        Assert.Empty(_meshes.Components);
    }

    [Fact]
    public void Tessellate_OnAHostWithNoMeshSource_SaysSoRatherThanAnsweringEmpty()
    {
        // An empty answer would read as "this component has no body", which is a silent
        // clear: the reviewer sweeps nothing and reports a check that found nothing.
        BridgeResponse response = NewDispatcher(meshes: null).Dispatch(
            Request("5", BridgeCommands.Tessellate, "{\"component_id\":\"cmp:0002\"}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("tessellate", response.Error!, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Tessellate_AComponentWithNoBody_AnswersOkWithTheGapThatSaysWhy()
    {
        _meshes.Gap = new Gap
        {
            Kind = GapKind.NotExtracted,
            EntityKind = "body",
            EntityId = null,
            Reason = "'screw-1' is not resolved, so no mesh was written for it.",
        };

        BridgeResponse response = Dispatch(
            Request("5", BridgeCommands.Tessellate, "{\"component_id\":\"cmp:0003\"}"));

        Assert.Equal(BridgeStatus.Ok, response.Status);
        var result = Assert.IsType<TessellateCommandResult>(response.Result);
        Assert.Empty(result.Bodies);
        Assert.Empty(result.Paths);
        Assert.Contains("not resolved", Assert.Single(result.Gaps).Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Tessellate_ReportsTheElapsedMilliseconds()
    {
        // One STA worker answers in arrival order, so a tessellation blocks every other
        // bridge call behind it; elapsed_ms is how the reviewer prices that (probe P2).
        BridgeResponse response = Dispatch(
            Request("5", BridgeCommands.Tessellate, "{\"component_id\":\"cmp:0002\"}"));

        Assert.True(response.ElapsedMs >= 0);
    }

    // ---- helpers -----------------------------------------------------------------

    private static string[] MemberNames(object result)
    {
        using (JsonDocument document = JsonDocument.Parse(
            JsonSerializer.Serialize(result, result.GetType(), BridgeCodec.Options)))
        {
            return document.RootElement.EnumerateObject().Select(member => member.Name).ToArray();
        }
    }

    private static BridgeRequest Request(string id, string command, string? paramsJson = null)
    {
        string line = paramsJson == null
            ? $"{{\"id\":\"{id}\",\"command\":\"{command}\"}}"
            : $"{{\"id\":\"{id}\",\"command\":\"{command}\",\"params\":{paramsJson}}}";

        return JsonSerializer.Deserialize<BridgeRequest>(line, BridgeCodec.Options)!;
    }

    private BridgeResponse Dispatch(BridgeRequest request) =>
        NewDispatcher(_meshes).Dispatch(request);

    private SwBridgeDispatcher NewDispatcher(ITessellateSource? meshes)
    {
        var services = new BridgeServices(
            new FakeCaptureView(),
            new FakeMeasureSource("no measure source in this test"),
            new FakeInterferenceSource(new FakeInterferenceDetector()),
            Index(),
            _packageDirectory)
        {
            SwVersion = "32.5.0",
            DocumentPath = @"C:\work\bracket-assy.SLDASM",
            Configuration = "Default",
            TessellateSource = meshes,
        };

        return new SwBridgeDispatcher(services, NoSecretPolicy.Instance);
    }

    /// <summary>The same three-component index BridgeDispatcherTests builds.</summary>
    private static ComponentIndex Index()
    {
        var tree = new ComponentTreeResult { ActiveConfiguration = "Default" };
        tree.Nodes.Add(new ComponentNode
        {
            Key = "bracket-assy-1",
            DocumentPath = @"C:\work\bracket-assy.SLDASM",
        });
        tree.Nodes.Add(new ComponentNode
        {
            Key = "housing-1",
            DocumentPath = @"C:\work\housing.SLDPRT",
        });
        tree.Nodes.Add(new ComponentNode
        {
            Key = "screw-1",
            DocumentPath = @"C:\work\screw.SLDPRT",
            PatternId = "pat:screws",
        });

        return new ComponentIndex(tree);
    }

    /// <summary>
    /// The mesh export as the dispatcher sees it. The real one is
    /// <see cref="SwTessellateSource"/>, which needs a live component.
    /// </summary>
    private sealed class FakeTessellateSource : ITessellateSource
    {
        public List<string> Components { get; } = new List<string>();

        public List<string> Directories { get; } = new List<string>();

        /// <summary>Set to answer with no body and this gap instead.</summary>
        public Gap? Gap { get; set; }

        public TessellateCommandResult Tessellate(string componentId, string packageDirectory)
        {
            Components.Add(componentId);
            Directories.Add(packageDirectory);

            var result = new TessellateCommandResult();
            if (Gap != null)
            {
                result.Gaps.Add(Gap);
                return result;
            }

            string meshDirectory = Path.Combine(packageDirectory, PackageWriter.MeshDirectoryName);
            Directory.CreateDirectory(meshDirectory);
            string fileName = componentId.Replace(':', '-') + "-bod-0001.glb";
            File.WriteAllText(Path.Combine(meshDirectory, fileName), "glb");

            result.Bodies.Add(new BodyRef
            {
                Id = "bod:0001",
                PersistRef = "cmVm",
                PersistRefScope = "doc:2",
                ComponentId = componentId,
                MeshFile = PackageWriter.MeshDirectoryName + "/" + fileName,
                TriangleCount = 12,
                IsSolid = true,
            });
            result.Paths.Add(Path.Combine(meshDirectory, fileName));
            return result;
        }
    }
}
