using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

namespace SwReview.AddIn.Review;

/// <summary>A bounded, read-only component census before extraction or provider calls.</summary>
public sealed class ReviewPreparation
{
    public const int RowLimit = 30;
    public const int TextLimit = 200;

    public ReviewPreparation(ComponentTreeResult tree, GapCollector gaps)
    {
        Document = new PageDocument(tree.RootDocumentPath, tree.ActiveConfiguration);
        Components = tree.Nodes.Count;
        Unread = tree.Nodes.Count(node => node.Suppression != SuppressionState.Resolved);
        Gaps = gaps.Count;
        Instances = tree.Nodes.Where(node => node.Suppression != SuppressionState.Resolved)
            .Take(RowLimit)
            .Select(node => new Dictionary<string, object?>
            {
                { "name", Clip(node.Name) },
                { "instance", Clip(node.Key) },
                { "configuration", Clip(node.ReferencedConfiguration) },
                { "state", node.Suppression.ToString().ToLowerInvariant() },
            }).ToArray();
    }

    public PageDocument Document { get; }
    public int Components { get; }
    public int Unread { get; }
    public int Gaps { get; }
    public IReadOnlyList<Dictionary<string, object?>> Instances { get; }

    public Dictionary<string, object?> Payload(string preparationId, bool standardsConfigured) =>
        new Dictionary<string, object?>
        {
            { "preparation_id", preparationId },
            { "document", new { path = Document.Path, configuration = Document.Configuration } },
            { "component_count", Components },
            { "unread_count", Unread },
            { "gap_count", Gaps },
            { "instances", Instances },
            { "omitted_instances", Unread - Instances.Count },
            { "requires_attention", Unread > 0 || Gaps > 0 },
            { "standards_configured", standardsConfigured },
        };

    private static string Clip(string text) =>
        text.Length <= TextLimit ? text : text.Substring(0, TextLimit - 1) + "…";
}
