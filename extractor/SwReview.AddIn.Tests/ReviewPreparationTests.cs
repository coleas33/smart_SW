using System.Linq;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.AddIn.Tests;

public sealed class ReviewPreparationTests
{
    [Fact]
    public void LargeTreesCountEveryUnreadInstanceButBoundTheDisplayedRowsAndText()
    {
        var tree = new ComponentTreeResult();
        for (int index = 0; index < 105; index++)
        {
            tree.Nodes.Add(new ComponentNode
            {
                Name = new string('x', 10000), Key = new string('y', 10000),
                ReferencedConfiguration = new string('z', 10000),
                Suppression = index < 100 ? SuppressionState.Lightweight : SuppressionState.Resolved,
            });
        }
        var result = new ReviewPreparation(tree, new GapCollector());
        Assert.Equal(105, result.Components);
        Assert.Equal(100, result.Unread);
        Assert.Equal(ReviewPreparation.RowLimit, result.Instances.Count);
        Assert.Equal(70, result.Payload("id", false)["omitted_instances"]);
        Assert.All(result.Instances.SelectMany(row => row.Values), value =>
            Assert.True(((string)value!).Length <= ReviewPreparation.TextLimit));
    }

    [Fact]
    public void GapsRemainVisibleEvenWhenNoUnreadNodeCouldBeEnumerated()
    {
        var gaps = new GapCollector();
        gaps.Add(GapKind.NotExtracted, "component", null, "Tree unavailable", null);
        var result = new ReviewPreparation(new ComponentTreeResult(), gaps);
        Assert.True((bool)result.Payload("id", false)["requires_attention"]!);
        Assert.Equal(1, result.Gaps);
        Assert.Empty(result.Instances);
    }
}
