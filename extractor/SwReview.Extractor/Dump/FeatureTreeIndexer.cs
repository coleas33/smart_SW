using System;
using System.Collections.Generic;
using SwReview.Extractor.Ids;

namespace SwReview.Extractor.Dump;

/// <summary>
/// One feature of a part's tree as the walk found it, before ids exist. The sub-features
/// are the ones <c>GetFirstSubFeature</c>/<c>GetNextSubFeature</c> listed, one level at a
/// time; a feature that lists none has an empty list, which is how the flat traversal shape
/// reaches the indexer (research R2).
/// </summary>
public sealed class FeatureTreeNode
{
    /// <summary>The feature's <c>IFeature.Name</c>. Carried for the dumper; never read here.</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary><c>GetTypeName2</c> verbatim. Carried for the dumper; never read here.</summary>
    public string TypeName { get; set; } = string.Empty;

    /// <summary>
    /// The live <c>IFeature</c>, so the dumper does not walk twice. Typed as object to keep
    /// this contract free of the interop assembly; null in tests.
    /// </summary>
    public object? Handle { get; set; }

    /// <summary>Immediate sub-features, in the order the walk listed them.</summary>
    public List<FeatureTreeNode> SubFeatures { get; } = new List<FeatureTreeNode>();
}

/// <summary>A feature that has been given its package id and its place in the tree.</summary>
public sealed class FeatureTreeRow
{
    public FeatureTreeRow(string id, int index, int depth, string? folderId, FeatureTreeNode node)
    {
        Id = id;
        Index = index;
        Depth = depth;
        FolderId = folderId;
        Node = node;
    }

    /// <summary>Package id, pattern <c>feat:NNNN</c>.</summary>
    public string Id { get; }

    /// <summary>Flat order within this document's tree, folders and their contents inline.</summary>
    public int Index { get; }

    /// <summary>0 top level, 1 inside a feature that listed it as a sub-feature, and so on.</summary>
    public int Depth { get; }

    /// <summary>Id of the nearest enclosing feature, or null at top level.</summary>
    public string? FolderId { get; }

    /// <summary>The node this row describes.</summary>
    public FeatureTreeNode Node { get; }
}

/// <summary>
/// T014. Turns a feature walk into the <c>index</c>/<c>depth</c>/<c>folder_id</c> triple the
/// IR records, and nothing else. Pure, so both traversal shapes are testable without a seat.
///
/// It deliberately reads neither <see cref="FeatureTreeNode.Name"/> nor
/// <see cref="FeatureTreeNode.TypeName"/>: the extractor decides nothing about folders, end
/// tags, groups or classes (data-model section 1), so depth and folder come from sub-feature
/// structure alone. In the flat shape - the folder lists no sub-features and its contents
/// follow it as siblings - every row is depth 0 with no folder, and Python's group assigner
/// recovers the membership from the folder's end-tag marker.
/// </summary>
public static class FeatureTreeIndexer
{
    /// <summary>
    /// Rows for one document's tree, in traversal order. <paramref name="ids"/> is the
    /// package's feature allocator, so ids continue across documents while
    /// <see cref="FeatureTreeRow.Index"/> starts again at zero for each call.
    /// </summary>
    public static IReadOnlyList<FeatureTreeRow> Index(IEnumerable<FeatureTreeNode> features, IdAllocator ids)
    {
        if (features == null)
        {
            throw new ArgumentNullException(nameof(features));
        }

        if (ids == null)
        {
            throw new ArgumentNullException(nameof(ids));
        }

        var rows = new List<FeatureTreeRow>();
        Visit(features, ids, rows, depth: 0, folderId: null);
        return rows;
    }

    private static void Visit(
        IEnumerable<FeatureTreeNode> features,
        IdAllocator ids,
        List<FeatureTreeRow> rows,
        int depth,
        string? folderId)
    {
        foreach (FeatureTreeNode node in features)
        {
            if (node == null)
            {
                // Skipping it would shift every later index and, in Python, re-group every
                // feature after it: a walk with a hole in it is a walk that lost a feature,
                // and the caller turns this into a gap rather than a quietly shorter tree.
                throw new ArgumentException(
                    $"The feature walk holds nothing at position {rows.Count}"
                    + (folderId == null ? string.Empty : $" under {folderId}")
                    + "; a feature tree cannot be indexed with a feature missing from it.",
                    nameof(features));
            }

            string id = ids.Next();
            rows.Add(new FeatureTreeRow(id, rows.Count, depth, folderId, node));

            // A feature's own id is the folder of its sub-features: the indexer does not ask
            // whether it is a folder, only whether it owns anything.
            Visit(node.SubFeatures, ids, rows, depth + 1, id);
        }
    }
}
