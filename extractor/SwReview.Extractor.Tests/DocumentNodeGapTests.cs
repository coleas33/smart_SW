using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 010 T127 (owner decision 166A, defect 1). The first tests of how
/// <see cref="HoleDumper"/>, <see cref="FastenerDumper"/> and <see cref="FaceDumper"/>'s
/// <c>--faces all</c> sweep treat the node they are handed, over interop stand-ins on a machine
/// with no seat.
///
/// Each reads through an <c>IComponent2</c>. Two nodes have none, because the document IS the
/// node and carries its <c>IModelDoc2</c> as its handle (<see cref="ComponentDocuments"/>): the
/// part root of a part reviewed on its own, and every model a drawing's views reference
/// (<see cref="ComponentTreeDumper"/>). Before 166A all three skipped such a node with no gap, so
/// a part review's thread check could not tell a part with no thread from one whose holes were
/// never read. Now each records one named gap, in the words of the gaps beside it, and still
/// calls nothing on the document: which interop members are called, and in what order, does not
/// change. Reading those holes is 010 T130's, once PROBE-15 (003 T088) has answered at the seat.
///
/// The drawing forest root carries no handle at all and has no holes, faces or fastener
/// identity of its own, so it still records nothing; and a component with no loaded model keeps
/// the gaps and the calls it had.
/// </summary>
public class DocumentNodeGapTests
{
    private const string PartPath = @"C:\fict\FICT-PLATE.SLDPRT";
    private const string AssemblyPath = @"C:\fict\FICT-FRAME.SLDASM";
    private const string DrawingPath = @"C:\fict\FICT-PLATE.SLDDRW";
    private const string Reviewed = "is reviewed as a document of its own, not as a component of an assembly";

    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    public DocumentNodeGapTests()
    {
        _gate.Observer = _observer;
    }

    /// <summary>
    /// The nodes whose handle is their document: a part root (keyed on its design name, with no
    /// parent), and a part and an assembly a drawing references (keyed on their path, under the
    /// drawing).
    /// </summary>
    public static IEnumerable<object?[]> DocumentNodes() => new[]
    {
        new object?[] { "FICT-PLATE", null, PartPath, DocumentKind.Part },
        new object?[] { PartPath, DrawingPath, PartPath, DocumentKind.Part },
        new object?[] { AssemblyPath, DrawingPath, AssemblyPath, DocumentKind.Assembly },
    };

    // ---- a node whose handle is its document -----------------------------------------

    [Theory]
    [MemberData(nameof(DocumentNodes))]
    public void HoleDumper_ADocumentNode_RecordsOneHoleGapNamingIt_AndCallsNothing(
        string key, string? parentKey, string path, DocumentKind kind)
    {
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(key, parentKey, path, kind, document.Instance));

        HoleDumpResult result = new HoleDumper(NewSession(), new PersistRefService(_gate)).Dump(scope);

        Assert.Empty(result.Holes);
        Assert.Empty(result.Threads);
        AssertOnlyGap(scope, "hole", $"'{key}' {Reviewed}, so its holes and threads were not read.");
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    [Theory]
    [MemberData(nameof(DocumentNodes))]
    public void FastenerDumper_ADocumentNode_RecordsOneFastenerGapNamingIt_AndCallsNothing(
        string key, string? parentKey, string path, DocumentKind kind)
    {
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(key, parentKey, path, kind, document.Instance));

        IReadOnlyList<Fastener> fasteners = new FastenerDumper(NewSession(), new PersistRefService(_gate)).Dump(scope);

        Assert.Empty(fasteners);
        AssertOnlyGap(scope, "fastener", $"'{key}' {Reviewed}, so whether it is a fastener was not read.");
        Assert.Empty(document.Calls);
        Assert.Empty(_observer.Members);
    }

    [Theory]
    [MemberData(nameof(DocumentNodes))]
    public void FaceDumper_SweepingEveryFace_ADocumentNode_RecordsOneFaceGapNamingIt_AndCallsNothing(
        string key, string? parentKey, string path, DocumentKind kind)
    {
        var document = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2));
        DumpScope scope = Scope(Node(key, parentKey, path, kind, document.Instance), FaceScope.All);

        IReadOnlyList<FaceGeometry> faces = Faces().Dump(scope);

        Assert.Empty(faces);
        AssertOnlyGap(scope, "face", $"'{key}' {Reviewed}, so its faces were not read.");
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

    // ---- what does not change -----------------------------------------------------------

    [Fact]
    public void ADrawingForestRoot_HasNoHandle_AndRecordsNothingInAnyOfTheThree()
    {
        DumpScope scope = Scope(Node(DrawingPath, null, DrawingPath, DocumentKind.Drawing, handle: null), FaceScope.All);
        var refs = new PersistRefService(_gate);

        HoleDumpResult holes = new HoleDumper(NewSession(), refs).Dump(scope);
        IReadOnlyList<Fastener> fasteners = new FastenerDumper(NewSession(), refs).Dump(scope);
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

        HoleDumpResult result = new HoleDumper(NewSession(), new PersistRefService(_gate)).Dump(scope);

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

        IReadOnlyList<Fastener> fasteners = new FastenerDumper(NewSession(), new PersistRefService(_gate)).Dump(scope);

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

    // ---- helpers ------------------------------------------------------------------------

    private static ComponentNode Node(
        string key, string? parentKey, string path, DocumentKind kind, object? handle) => new ComponentNode
    {
        Key = key,
        ParentKey = parentKey,
        Name = key,
        DocumentPath = path,
        DocumentKind = kind,
        Suppression = SuppressionState.Resolved,
        IsFixed = true,
        Handle = handle,
    };

    private static DumpScope Scope(ComponentNode node, FaceScope faces = FaceScope.Needed)
    {
        var tree = new ComponentTreeResult { RootDocumentPath = node.DocumentPath };
        tree.Nodes.Add(node);
        var scope = new DumpScope(new GapCollector(), new DumpOptions { Faces = faces }, tree);
        scope.AddComponent("cmp:0001", scope.DocumentId(node.DocumentPath), node);
        return scope;
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

    private FaceDumper Faces() => new FaceDumper(NewSession(), new PersistRefService(_gate), _ => null);

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
