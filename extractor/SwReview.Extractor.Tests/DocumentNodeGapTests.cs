using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 010 T127 and T131 (owner decision 166A, defect 1). The first tests of how
/// <see cref="HoleDumper"/>, <see cref="FastenerDumper"/>, <see cref="FaceDumper"/>'s
/// <c>--faces all</c> sweep and <see cref="MeshExporter"/> treat the node they are handed, over
/// interop stand-ins on a machine with no seat.
///
/// Each reads through an <c>IComponent2</c>. Two nodes have none, because the document IS the
/// node and carries its <c>IModelDoc2</c> as its handle (<see cref="ComponentDocuments"/>): the
/// part root of a part reviewed on its own, and every model a drawing's views reference
/// (<see cref="ComponentTreeDumper"/>). Before 166A the first three skipped such a node with no
/// gap, so a part review's thread check could not tell a part with no thread from one whose holes
/// were never read, and the mesh export said such a node "is not resolved". Now each records one
/// named gap, in the words of the gaps beside it, and still calls nothing on the document: which
/// interop members are called, and in what order, does not change. Reading those holes is 010
/// T130's (a part root, once PROBE-15, 003 T088, has answered at the seat) and T134's (a model a
/// drawing references).
///
/// T131 (the review of T128): the sentence says how the node is reviewed - on its own, or
/// referenced by a drawing; an assembly a drawing references is read through its components, so
/// only the holes and threads of its own assembly features are unread, and it records nothing
/// for the fastener, face and mesh reads; and a model a drawing references that is also a resolved
/// instance in the same configuration was read through that instance, so it records nothing.
///
/// The drawing forest root carries no handle at all and has no holes, faces or fastener
/// identity of its own, so it still records nothing; and a component with no loaded model keeps
/// the gaps and the calls it had.
/// </summary>
public class DocumentNodeGapTests : IDisposable
{
    private const string PartPath = @"C:\fict\FICT-PLATE.SLDPRT";
    private const string AssemblyPath = @"C:\fict\FICT-FRAME.SLDASM";
    private const string DrawingPath = @"C:\fict\FICT-PLATE.SLDDRW";
    private const string OnItsOwn = "is reviewed as a document of its own, not as a component of an assembly";
    private const string ByADrawing = "is referenced by a drawing, not reviewed as a component of an assembly";

    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();
    private readonly string _meshDirectory =
        Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));

    public DocumentNodeGapTests()
    {
        _gate.Observer = _observer;
    }

    public void Dispose()
    {
        if (Directory.Exists(_meshDirectory))
        {
            Directory.Delete(_meshDirectory, recursive: true);
        }
    }

    /// <summary>
    /// The part nodes whose handle is their document, and how each is reviewed: a part root
    /// (keyed on its design name, with no parent), and a part a drawing references (keyed on its
    /// path, under the drawing).
    /// </summary>
    public static IEnumerable<object?[]> PartNodes() => new[]
    {
        new object?[] { "FICT-PLATE", null, OnItsOwn },
        new object?[] { PartPath, DrawingPath, ByADrawing },
    };

    // ---- a part whose handle is its document ------------------------------------------

    [Theory]
    [MemberData(nameof(PartNodes))]
    public void HoleDumper_APartDocumentNode_RecordsOneHoleGapNamingIt_AndCallsNothing(
        string key, string? parentKey, string how)
    {
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(key, parentKey, PartPath, DocumentKind.Part, document.Instance));

        HoleDumpResult result = Holes().Dump(scope);

        Assert.Empty(result.Holes);
        Assert.Empty(result.Threads);
        AssertOnlyGap(scope, "hole", $"'{key}' {how}, so its holes and threads were not read.");
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    [Theory]
    [MemberData(nameof(PartNodes))]
    public void FastenerDumper_APartDocumentNode_RecordsOneFastenerGapNamingIt_AndCallsNothing(
        string key, string? parentKey, string how)
    {
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(key, parentKey, PartPath, DocumentKind.Part, document.Instance));

        IReadOnlyList<Fastener> fasteners = Fasteners().Dump(scope);

        Assert.Empty(fasteners);
        AssertOnlyGap(scope, "fastener", $"'{key}' {how}, so whether it is a fastener was not read.");
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    [Theory]
    [MemberData(nameof(PartNodes))]
    public void FaceDumper_SweepingEveryFace_APartDocumentNode_RecordsOneFaceGapNamingIt_AndCallsNothing(
        string key, string? parentKey, string how)
    {
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(key, parentKey, PartPath, DocumentKind.Part, document.Instance), FaceScope.All);

        IReadOnlyList<FaceGeometry> faces = Faces().Dump(scope);

        Assert.Empty(faces);
        AssertOnlyGap(scope, "face", $"'{key}' {how}, so its faces were not read.");
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    [Theory]
    [MemberData(nameof(PartNodes))]
    public void MeshExporter_APartDocumentNode_RecordsOneBodyGapSayingHowItIsReviewed_NotThatItIsUnresolved(
        string key, string? parentKey, string how)
    {
        // T131 (finding F4): it is resolved, so "is not resolved" was never true of it.
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(key, parentKey, PartPath, DocumentKind.Part, document.Instance));

        IReadOnlyList<BodyRef> bodies = Meshes().Dump(scope, _meshDirectory);

        Assert.Empty(bodies);
        AssertOnlyGap(scope, "body", $"'{key}' {how}, so no mesh was written for it.");
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    [Fact]
    public void FaceDumper_ReadingOnlyTheNeededFaces_ADocumentNodeRecordsNothing()
    {
        // With no face requested there is nothing to describe, as before: the sweep is the one
        // place the dumper walks the nodes.
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node("FICT-PLATE", null, PartPath, DocumentKind.Part, document.Instance));

        Assert.Empty(Faces().Dump(scope));
        Assert.Empty(scope.Gaps.Gaps);
        Assert.Empty(document.Calls);
    }

    // ---- an assembly a drawing references (T131, finding F1) --------------------------

    [Fact]
    public void HoleDumper_AnAssemblyADrawingReferences_RecordsOneGapForItsOwnAssemblyFeatures_AndCallsNothing()
    {
        // Its components are read one by one as IComponent2 nodes; what is lost is what an
        // assembly root's own read would have found - Hole Wizard holes and cosmetic threads that
        // are features of the assembly itself.
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(AssemblyPath, DrawingPath, AssemblyPath, DocumentKind.Assembly, document.Instance));

        HoleDumpResult result = Holes().Dump(scope);

        Assert.Empty(result.Holes);
        Assert.Empty(result.Threads);
        AssertOnlyGap(
            scope,
            "hole",
            $"'{AssemblyPath}' {ByADrawing}, so the holes and threads of its own assembly features were not read.");
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    [Fact]
    public void FastenerFaceAndMeshReads_AnAssemblyADrawingReferences_RecordNothing_AndCallNothing()
    {
        // Its parts' fastener identity, faces and bodies are read through its components; the
        // assembly carries none of its own, so a gap here would say less was read than was.
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(
            Node(AssemblyPath, DrawingPath, AssemblyPath, DocumentKind.Assembly, document.Instance), FaceScope.All);

        Assert.Empty(Fasteners().Dump(scope));
        Assert.Empty(Faces().Dump(scope));
        Assert.Empty(Meshes().Dump(scope, _meshDirectory));
        Assert.Empty(scope.Gaps.Gaps);
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    // ---- a model a drawing references that is also an instance (T131, finding F2) --------

    [Fact]
    public void APartADrawingReferences_ThatIsAlsoAResolvedInstanceInTheSameConfiguration_IsNotRecordedAsUnread()
    {
        // An assembly sheet and a part-detail sheet of one drawing: the plate is a referenced
        // model of its own and a component of the referenced frame. Its holes, identity, faces
        // and bodies are read through the instance (here the instance has no loaded model, so the
        // hole read names the instance instead), and a gap naming the plate's path would list a
        // document whose threads were checked. The instance's path differs in case only: the
        // document id is what says two nodes are one document.
        var plate = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        var frame = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        var instance = new InteropRecorder<IComponent2>();
        DumpScope scope = Forest(
            FaceScope.All,
            Node(DrawingPath, null, DrawingPath, DocumentKind.Drawing, handle: null),
            Node(AssemblyPath, DrawingPath, AssemblyPath, DocumentKind.Assembly, frame.Instance),
            Node("FICT-PLATE-1", AssemblyPath, PartPath.ToLowerInvariant(), DocumentKind.Part, instance.Instance),
            Node(PartPath, DrawingPath, PartPath, DocumentKind.Part, plate.Instance));

        RunAllFour(scope);

        Assert.Equal(
            new[]
            {
                $"'{AssemblyPath}' {ByADrawing}, so the holes and threads of its own assembly features were not read.",
                "'FICT-PLATE-1' has no loaded model document; its holes were not read.",
            },
            scope.Gaps.Gaps.Where(gap => gap.EntityKind == "hole").Select(gap => gap.Reason));
        Assert.DoesNotContain(scope.Gaps.Gaps, gap => gap.Reason.Contains($"'{PartPath}'"));
        Assert.Empty(plate.Calls);
        Assert.Empty(frame.Calls);
    }

    [Fact]
    public void APartADrawingReferences_WhoseInstanceIsInAnotherConfiguration_KeepsItsGaps()
    {
        // The instance's read is of its own configuration, whose holes may differ.
        var plate = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Forest(
            FaceScope.All,
            Node("FICT-PLATE-1", AssemblyPath, PartPath, DocumentKind.Part, new InteropRecorder<IComponent2>().Instance, "Long"),
            Node(PartPath, DrawingPath, PartPath, DocumentKind.Part, plate.Instance));

        RunAllFour(scope);

        Assert.Equal(
            new[]
            {
                $"'{PartPath}' {ByADrawing}, so its holes and threads were not read.",
                $"'{PartPath}' {ByADrawing}, so whether it is a fastener was not read.",
                $"'{PartPath}' {ByADrawing}, so its faces were not read.",
                $"'{PartPath}' {ByADrawing}, so no mesh was written for it.",
            },
            scope.Gaps.Gaps.Where(gap => gap.Reason.Contains($"'{PartPath}'")).Select(gap => gap.Reason));
        Assert.Empty(plate.Calls);
    }

    [Fact]
    public void APartADrawingReferences_WhoseInstanceIsSuppressed_KeepsItsGaps()
    {
        // A suppressed instance is not read, so nothing of the plate's was.
        var plate = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        ComponentNode suppressed = Node(
            "FICT-PLATE-1", AssemblyPath, PartPath, DocumentKind.Part, new InteropRecorder<IComponent2>().Instance);
        suppressed.Suppression = SuppressionState.Suppressed;
        DumpScope scope = Forest(FaceScope.All, suppressed, Node(PartPath, DrawingPath, PartPath, DocumentKind.Part, plate.Instance));

        RunAllFour(scope);

        Assert.Equal(
            new[]
            {
                $"'{PartPath}' {ByADrawing}, so its holes and threads were not read.",
                $"'{PartPath}' {ByADrawing}, so whether it is a fastener was not read.",
                $"'{PartPath}' {ByADrawing}, so its faces were not read.",
                $"'{PartPath}' {ByADrawing}, so no mesh was written for it.",
            },
            scope.Gaps.Gaps.Where(gap => gap.Reason.Contains($"'{PartPath}'")).Select(gap => gap.Reason));
        Assert.Empty(plate.Calls);
    }

    // ---- what does not change -----------------------------------------------------------

    [Fact]
    public void ADrawingForestRoot_HasNoHandle_AndRecordsNothingInAnyOfTheThree()
    {
        DumpScope scope = Scope(Node(DrawingPath, null, DrawingPath, DocumentKind.Drawing, handle: null), FaceScope.All);

        HoleDumpResult holes = Holes().Dump(scope);
        IReadOnlyList<Fastener> fasteners = Fasteners().Dump(scope);
        IReadOnlyList<FaceGeometry> faces = Faces().Dump(scope);

        Assert.Empty(holes.Holes);
        Assert.Empty(holes.Threads);
        Assert.Empty(fasteners);
        Assert.Empty(faces);
        Assert.Empty(scope.Gaps.Gaps);
        Assert.Empty(_observer.Members);
    }

    [Fact]
    public void HoleDumper_AComponentWithNoLoadedModel_AsksGetModelDoc2_AndKeepsItsOwnGap()
    {
        var component = new InteropRecorder<IComponent2>();
        DumpScope scope = Scope(Node("FICT-PLATE-1", "FICT-FRAME", PartPath, DocumentKind.Part, component.Instance));

        HoleDumpResult result = Holes().Dump(scope);

        Assert.Empty(result.Holes);
        AssertOnlyGap(scope, "hole", "'FICT-PLATE-1' has no loaded model document; its holes were not read.");
        Assert.Equal(new[] { "GetModelDoc2" }, component.Members);
        Assert.Equal(new[] { "GetModelDoc2" }, _observer.Members);
    }

    [Fact]
    public void FastenerDumper_AComponentWithNoLoadedModel_AsksGetModelDoc2_AndIsNoFastenerByItsName()
    {
        var component = new InteropRecorder<IComponent2>();
        DumpScope scope = Scope(Node("FICT-PLATE-1", "FICT-FRAME", PartPath, DocumentKind.Part, component.Instance));

        IReadOnlyList<Fastener> fasteners = Fasteners().Dump(scope);

        Assert.Empty(fasteners);
        Assert.Empty(scope.Gaps.Gaps);
        Assert.Equal(new[] { "GetModelDoc2" }, component.Members);
        Assert.Equal(new[] { "GetModelDoc2" }, _observer.Members);
    }

    [Fact]
    public void FaceDumper_SweepingEveryFace_AComponentWithNoLoadedModel_AsksGetModelDoc2_AndRecordsNothing()
    {
        var component = new InteropRecorder<IComponent2>();
        DumpScope scope = Scope(
            Node("FICT-PLATE-1", "FICT-FRAME", PartPath, DocumentKind.Part, component.Instance), FaceScope.All);

        Assert.Empty(Faces().Dump(scope));
        Assert.Empty(scope.Gaps.Gaps);
        Assert.Equal(new[] { "GetModelDoc2" }, component.Members);
        Assert.Equal(new[] { "GetModelDoc2" }, _observer.Members);
    }

    [Fact]
    public void MeshExporter_ASuppressedComponent_KeepsItsNotResolvedGap_AndCallsNothing()
    {
        var component = new InteropRecorder<IComponent2>();
        ComponentNode node = Node("FICT-PLATE-1", "FICT-FRAME", PartPath, DocumentKind.Part, component.Instance);
        node.Suppression = SuppressionState.Suppressed;
        DumpScope scope = Scope(node);

        Assert.Empty(Meshes().Dump(scope, _meshDirectory));
        AssertOnlyGap(scope, "body", "'FICT-PLATE-1' is not resolved, so no mesh was written for it.");
        Assert.Empty(component.Calls);
        Assert.Empty(_observer.Members);
    }

    // ---- helpers ------------------------------------------------------------------------

    private static ComponentNode Node(
        string key, string? parentKey, string path, DocumentKind kind, object? handle, string configuration = "Default") =>
        new ComponentNode
        {
            Key = key,
            ParentKey = parentKey,
            Name = key,
            DocumentPath = path,
            DocumentKind = kind,
            ReferencedConfiguration = configuration,
            Suppression = SuppressionState.Resolved,
            IsFixed = true,
            Handle = handle,
        };

    private static DumpScope Scope(ComponentNode node, FaceScope faces = FaceScope.Needed) => Forest(faces, node);

    private static DumpScope Forest(FaceScope faces, params ComponentNode[] nodes)
    {
        var tree = new ComponentTreeResult { RootDocumentPath = nodes[0].DocumentPath };
        tree.Nodes.AddRange(nodes);
        var scope = new DumpScope(new GapCollector(), new DumpOptions { Faces = faces }, tree);
        for (int i = 0; i < nodes.Length; i++)
        {
            scope.AddComponent($"cmp:{i + 1:D4}", scope.DocumentId(nodes[i].DocumentPath), nodes[i]);
        }

        return scope;
    }

    private void RunAllFour(DumpScope scope)
    {
        Holes().Dump(scope);
        Fasteners().Dump(scope);
        Faces().Dump(scope);
        Meshes().Dump(scope, _meshDirectory);
    }

    private static void AssertOnlyGap(DumpScope scope, string entityKind, string reason)
    {
        Gap gap = Assert.Single(scope.Gaps.Gaps);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal(entityKind, gap.EntityKind);
        Assert.Null(gap.EntityId);
        Assert.Equal(reason, gap.Reason);
        Assert.Null(gap.Error);
    }

    private HoleDumper Holes() => new HoleDumper(NewSession(), new PersistRefService(_gate));

    private FastenerDumper Fasteners() => new FastenerDumper(NewSession(), new PersistRefService(_gate));

    private FaceDumper Faces() => new FaceDumper(NewSession(), new PersistRefService(_gate), _ => null);

    private MeshExporter Meshes() => new MeshExporter(NewSession(), new PersistRefService(_gate));

    private ISwSession NewSession() => new Session(new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Instance, _gate);

    private sealed class Session : ISwSession
    {
        public Session(IModelDoc2 document, SwGate gate)
        {
            Document = document;
            Gate = gate;
        }

        public IModelDoc2 Document { get; }
        public IConfiguration? Configuration => null;
        public string? SwVersion => "2024 SP5.0";
        public SwGate Gate { get; }
    }
}
