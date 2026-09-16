using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T013. The indexer is the one place that turns a feature walk into the
/// <c>index</c>/<c>depth</c>/<c>folder_id</c> triple every RMS rule reads, and it is pure so
/// both traversal shapes SOLIDWORKS 2024 produces can be pinned on a machine with no seat.
///
/// The thing these tests exist to protect is what the indexer does NOT do: it never looks at
/// a feature's name or its type name. Folders, end-tag markers, groups and classes are
/// Python's job against <c>checks/rms_types.yaml</c> (data-model section 1), so a name that
/// looks like an end tag or a type name that looks like a folder must change nothing here.
/// </summary>
public class FeatureTreeIndexerTests
{
    [Fact]
    public void NestedShape_FolderContentsAreDepthOneUnderTheFolder()
    {
        // The shape SOLIDWORKS answers with when a folder owns its contents as sub-features.
        IReadOnlyList<FeatureTreeRow> rows = Index(
            Node("Sketch1", "ProfileFeature"),
            Node("2-Construction", "FtrFolder", Node("Plane1", "RefPlane"), Node("Axis1", "RefAxis")),
            Node("Boss-Extrude1", "Extrusion"));

        Assert.Equal(new[] { "Sketch1", "2-Construction", "Plane1", "Axis1", "Boss-Extrude1" }, Names(rows));
        Assert.Equal(new[] { 0, 1, 2, 3, 4 }, rows.Select(r => r.Index));
        Assert.Equal(new[] { 0, 0, 1, 1, 0 }, rows.Select(r => r.Depth));
        Assert.Equal(
            new string?[] { null, null, "feat:0002", "feat:0002", null },
            rows.Select(r => r.FolderId));
    }

    [Fact]
    public void FlatShape_FolderWithNoSubFeaturesLeavesItsContentsAtTopLevel()
    {
        // The other shape: the folder lists no sub-features and its contents follow it as
        // siblings. The indexer cannot tell that the folder owns them - only the type table
        // knows what a folder is - so every row stays depth 0 with no folder, and Python's
        // group assigner recovers the membership from the end-tag marker.
        IReadOnlyList<FeatureTreeRow> rows = Index(
            Node("2-Construction", "FtrFolder"),
            Node("Plane1", "RefPlane"),
            Node("2-Construction___EndTag___", "FtrFolder"),
            Node("Boss-Extrude1", "Extrusion"));

        Assert.Equal(new[] { 0, 1, 2, 3 }, rows.Select(r => r.Index));
        Assert.All(rows, row => Assert.Equal(0, row.Depth));
        Assert.All(rows, row => Assert.Null(row.FolderId));
    }

    [Fact]
    public void Ids_AreFeatNNNNInTraversalOrder()
    {
        IReadOnlyList<FeatureTreeRow> rows = Index(
            Node("Sketch1", "ProfileFeature"),
            Node("3-Core", "FtrFolder", Node("Boss-Extrude1", "Extrusion")),
            Node("Fillet1", "Fillet"));

        Assert.Equal(
            new[] { "feat:0001", "feat:0002", "feat:0003", "feat:0004" },
            rows.Select(r => r.Id));
    }

    [Fact]
    public void Ids_ContinueAcrossDocumentsWhileIndexRestarts()
    {
        // Feature ids are allocated across the package (data-model section 1) but `index` is
        // the position within one document's tree, so a second document indexed with the
        // same allocator carries on at feat:0003 and starts again at index 0.
        var ids = new IdAllocator("feat");

        IReadOnlyList<FeatureTreeRow> first = FeatureTreeIndexer.Index(
            new[] { Node("Sketch1", "ProfileFeature"), Node("Boss-Extrude1", "Extrusion") }, ids);
        IReadOnlyList<FeatureTreeRow> second = FeatureTreeIndexer.Index(
            new[] { Node("Sketch1", "ProfileFeature") }, ids);

        Assert.Equal(new[] { "feat:0001", "feat:0002" }, first.Select(r => r.Id));
        Assert.Equal(new[] { "feat:0003" }, second.Select(r => r.Id));
        Assert.Equal(new[] { 0 }, second.Select(r => r.Index));
    }

    [Fact]
    public void AnEndTagName_IsTreatedLikeAnyOtherFeature()
    {
        // A folder named like an end-tag marker is still just a feature with sub-features:
        // deciding that the name means "end tag" is the type table's job, not the walk's.
        IReadOnlyList<FeatureTreeRow> rows = Index(
            Node("Folder1___EndTag___", "FtrFolder", Node("Fillet1", "Fillet")));

        Assert.Equal(new[] { 0, 1 }, rows.Select(r => r.Index));
        Assert.Equal(new[] { 0, 1 }, rows.Select(r => r.Depth));
        Assert.Equal(new string?[] { null, "feat:0001" }, rows.Select(r => r.FolderId));
    }

    [Fact]
    public void AFolderTypeName_IsTreatedLikeAnyOtherFeature()
    {
        // Symmetrically: a feature whose type name is the folder type but which lists no
        // sub-features produces one ordinary row. Depth comes from structure alone.
        IReadOnlyList<FeatureTreeRow> rows = Index(
            Node("5-Modify", "FtrFolder"),
            Node("Sketch1", "ProfileFeature"));

        Assert.Equal(new[] { 0, 0 }, rows.Select(r => r.Depth));
        Assert.All(rows, row => Assert.Null(row.FolderId));
    }

    [Fact]
    public void NestedSubfolder_IsDepthTwoUnderItsOwnFolder()
    {
        // The coupled-pair exception needs the inner folder's id, so nesting is not flattened.
        IReadOnlyList<FeatureTreeRow> rows = Index(
            Node(
                "4-Detail",
                "FtrFolder",
                Node("Sketch1", "ProfileFeature"),
                Node("CoupledPair", "FtrFolder", Node("Cut-Extrude1", "Cut"))));

        Assert.Equal(new[] { "4-Detail", "Sketch1", "CoupledPair", "Cut-Extrude1" }, Names(rows));
        Assert.Equal(new[] { 0, 1, 1, 2 }, rows.Select(r => r.Depth));
        Assert.Equal(
            new string?[] { null, "feat:0001", "feat:0001", "feat:0003" },
            rows.Select(r => r.FolderId));
    }

    [Fact]
    public void EveryRowCarriesTheNodeItCameFrom()
    {
        // The dumper reads the live feature off the row, so the row must not lose it.
        FeatureTreeNode folder = Node("3-Core", "FtrFolder", Node("Boss-Extrude1", "Extrusion"));

        IReadOnlyList<FeatureTreeRow> rows = Index(folder);

        Assert.Same(folder, rows[0].Node);
        Assert.Same(folder.SubFeatures[0], rows[1].Node);
    }

    [Fact]
    public void NoFeatures_IsNoRowsAndNoIds()
    {
        var ids = new IdAllocator("feat");

        IReadOnlyList<FeatureTreeRow> rows = FeatureTreeIndexer.Index(new FeatureTreeNode[0], ids);

        Assert.Empty(rows);
        Assert.Equal(0, ids.Count);
    }

    private static IReadOnlyList<FeatureTreeRow> Index(params FeatureTreeNode[] features) =>
        FeatureTreeIndexer.Index(features, new IdAllocator("feat"));

    private static IEnumerable<string> Names(IEnumerable<FeatureTreeRow> rows) =>
        rows.Select(row => row.Node.Name);

    private static FeatureTreeNode Node(string name, string typeName, params FeatureTreeNode[] subFeatures)
    {
        var node = new FeatureTreeNode
        {
            Name = name,
            TypeName = typeName,
            Handle = new object(),
        };

        node.SubFeatures.AddRange(subFeatures);
        return node;
    }
}
