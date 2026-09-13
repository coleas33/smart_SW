using System;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T071. The index is the only thing that makes a <c>cmp:0011</c> read out of package.json
/// mean the same component to the interference and capture paths. It must allocate ids the
/// way <see cref="PackageWriter"/> does, including skipping the same nodes - one extra or
/// one missing and every id after it shifts, silently attributing a finding to the wrong
/// part.
/// </summary>
public class ComponentIndexTests
{
    [Fact]
    public void Ids_AreAllocatedInTraversalOrderLikeThePackage()
    {
        ComponentIndex index = Index(
            Node("bracket-assy-1", @"C:\work\bracket-assy.SLDASM"),
            Node("housing-1", @"C:\work\housing.SLDPRT"),
            Node("screw-1", @"C:\work\screw.SLDPRT"));

        Assert.Equal(3, index.Count);
        Assert.NotNull(index.ById("cmp:0001"));
        Assert.NotNull(index.ById("cmp:0002"));
        Assert.NotNull(index.ById("cmp:0003"));
    }

    [Fact]
    public void Ids_SkipNodesWithoutAFilePathExactlyAsPackageWriterDoes()
    {
        // PackageWriter records a gap and skips such a node; skipping it here too is what
        // keeps the two id sequences identical.
        ComponentIndex index = Index(
            Node("bracket-assy-1", @"C:\work\bracket-assy.SLDASM"),
            Node("never-saved-1", string.Empty),
            Node("screw-1", @"C:\work\screw.SLDPRT"));

        Assert.Equal(2, index.Count);
        Assert.Null(index.ById("cmp:0003"));
    }

    [Fact]
    public void IdOf_FindsTheComponentTheTraversalSaw()
    {
        var handle = new FakeComponent("housing");
        ComponentIndex index = Index(
            Node("bracket-assy-1", @"C:\work\bracket-assy.SLDASM"),
            Node("housing-1", @"C:\work\housing.SLDPRT", handle: handle));

        Assert.Equal("cmp:0002", index.IdOf(handle));
    }

    [Fact]
    public void IdOf_ComponentTheTraversalNeverSaw_IsNull()
    {
        // The caller records a gap rather than guessing an id.
        ComponentIndex index = Index(Node("bracket-assy-1", @"C:\work\bracket-assy.SLDASM"));

        Assert.Null(index.IdOf(new FakeComponent("stranger")));
        Assert.Null(index.IdOf(null!));
    }

    [Fact]
    public void ById_CarriesTheHandleAndThePatternSoAPairCanBeScopedAndGrouped()
    {
        var handle = new FakeComponent("screw");
        ComponentIndex index = Index(
            Node("bracket-assy-1", @"C:\work\bracket-assy.SLDASM"),
            Node("screw-1", @"C:\work\screw.SLDPRT", pattern: "pat:screws", handle: handle));

        InterferenceComponent component = index.ById("cmp:0002")!;
        Assert.Equal("cmp:0002", component.Id);
        Assert.Equal("pat:screws", component.PatternId);
        Assert.Same(handle, component.Handle);
        Assert.Equal("pat:screws", component.GroupMember);
    }

    [Fact]
    public void PatternOf_UnpatternedComponent_IsNull()
    {
        ComponentIndex index = Index(Node("bracket-assy-1", @"C:\work\bracket-assy.SLDASM"));

        Assert.Null(index.PatternOf("cmp:0001"));
        Assert.Null(index.PatternOf("cmp:9999"));
        Assert.Null(index.ById("  "));
    }

    [Fact]
    public void Constructor_NullTree_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new ComponentIndex(null!));
    }

    private static ComponentIndex Index(params ComponentNode[] nodes)
    {
        var tree = new ComponentTreeResult { ActiveConfiguration = "Default" };
        tree.Nodes.AddRange(nodes);
        return new ComponentIndex(tree);
    }

    private static ComponentNode Node(
        string key, string documentPath, string? pattern = null, object? handle = null) =>
        new ComponentNode
        {
            Key = key,
            DocumentPath = documentPath,
            PatternId = pattern,
            Handle = handle,
        };
}
