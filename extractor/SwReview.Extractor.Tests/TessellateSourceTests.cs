using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T096/T097. The half of <c>tessellate</c> that is not SOLIDWORKS: which component of the
/// traversed tree is exported, where the files land, and what a component that produced no
/// body answers.
///
/// The mesh source is faked because the real one, <see cref="MeshExporter"/>, needs live COM
/// pointers. What is pinned here is that <b>one</b> export path is called - the same
/// <c>ExportBody</c> the dump uses, reached through <see cref="IMeshSource.DumpComponent"/> -
/// so a chord tolerance can never differ between a mesh the dump wrote and a mesh the bridge
/// fetched, and that only the gaps of <b>this</b> call come back.
/// </summary>
public class TessellateSourceTests
{
    private const string PackageDirectory = @"C:\work\pkg";

    [Fact]
    public void Tessellate_ExportsTheNamedComponentIntoThePackagesMeshDirectory()
    {
        var meshes = new FakeMeshSource();
        SwTessellateSource source = NewSource(meshes);

        TessellateCommandResult result = source.Tessellate("cmp:0002", PackageDirectory);

        Assert.Equal("cmp:0002", Assert.Single(meshes.Exported).Id);
        Assert.Equal(
            Path.Combine(PackageDirectory, PackageWriter.MeshDirectoryName),
            Assert.Single(meshes.Directories));
        BodyRef body = Assert.Single(result.Bodies);
        Assert.Equal("cmp:0002", body.ComponentId);
        Assert.Empty(result.Gaps);
    }

    [Fact]
    public void Tessellate_PathsAreTheAbsolutePathOfEachRowsMeshFile()
    {
        var meshes = new FakeMeshSource();
        SwTessellateSource source = NewSource(meshes);

        TessellateCommandResult result = source.Tessellate("cmp:0002", PackageDirectory);

        // Package-relative and forward-slashed on the row, absolute on the path: the client
        // reads the row into package.json and the path is how it knows the file is inside
        // the package directory it was given.
        Assert.Equal("meshes/cmp-0002-bod-0001.glb", result.Bodies[0].MeshFile);
        Assert.Equal(
            Path.GetFullPath(Path.Combine(PackageDirectory, "meshes", "cmp-0002-bod-0001.glb")),
            Assert.Single(result.Paths));
    }

    [Fact]
    public void Tessellate_BodyIdsDoNotRepeatAcrossCalls()
    {
        // One allocator for the life of the bridge: two fetches in one review must not both
        // call their body bod:0001, or the package would hold two rows with one id.
        var meshes = new FakeMeshSource();
        SwTessellateSource source = NewSource(meshes);

        TessellateCommandResult first = source.Tessellate("cmp:0002", PackageDirectory);
        TessellateCommandResult second = source.Tessellate("cmp:0003", PackageDirectory);

        Assert.NotEqual(first.Bodies[0].Id, second.Bodies[0].Id);
    }

    [Fact]
    public void Tessellate_AComponentThatProducedNoBody_AnswersWithTheGapThatSaysWhy()
    {
        var meshes = new FakeMeshSource { Gap = "'screw-1' is not resolved, so no mesh was written for it." };
        SwTessellateSource source = NewSource(meshes);

        TessellateCommandResult result = source.Tessellate("cmp:0003", PackageDirectory);

        Assert.Empty(result.Bodies);
        Assert.Empty(result.Paths);
        Assert.Contains("not resolved", Assert.Single(result.Gaps).Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Tessellate_ReportsOnlyTheGapsOfThisCall()
    {
        // The scope lives as long as the bridge, so its gap list grows; a second fetch that
        // repeated the first one's gap would have the client record it twice.
        var meshes = new FakeMeshSource { Gap = "nothing came back" };
        SwTessellateSource source = NewSource(meshes);

        source.Tessellate("cmp:0002", PackageDirectory);
        TessellateCommandResult second = source.Tessellate("cmp:0003", PackageDirectory);

        Assert.Single(second.Gaps);
    }

    [Fact]
    public void Tessellate_AComponentTheTraversalNeverSaw_IsAGapNotAnEmptyAnswer()
    {
        // An empty answer would read as "this component has no body". It is a gap naming the
        // id, which the reviewer turns into unresolved coverage.
        var meshes = new FakeMeshSource();
        SwTessellateSource source = NewSource(meshes);

        TessellateCommandResult result = source.Tessellate("cmp:9999", PackageDirectory);

        Assert.Empty(result.Bodies);
        Assert.Empty(meshes.Exported);
        Assert.Contains("cmp:9999", Assert.Single(result.Gaps).Reason, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Tessellate_WithoutAComponentIdOrADirectory_Throws(string? blank)
    {
        SwTessellateSource source = NewSource(new FakeMeshSource());

        Assert.Throws<ArgumentException>(() => source.Tessellate(blank!, PackageDirectory));
        Assert.Throws<ArgumentException>(() => source.Tessellate("cmp:0002", blank!));
    }

    // ---- helpers -----------------------------------------------------------------

    private static SwTessellateSource NewSource(IMeshSource meshes)
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
        });

        DumpScope scope = PackageWriter.ScopeFor(
            new GapCollector(),
            new DumpOptions { OutputDirectory = ".", Configuration = "Default" },
            tree);

        return new SwTessellateSource(meshes, scope);
    }

    /// <summary>
    /// The export as the source sees it: it records what it was asked for and writes no file.
    /// </summary>
    private sealed class FakeMeshSource : IMeshSource
    {
        public List<ScopedComponent> Exported { get; } = new List<ScopedComponent>();

        public List<string> Directories { get; } = new List<string>();

        /// <summary>Set to record this gap and return no body, as the real exporter does.</summary>
        public string? Gap { get; set; }

        public IReadOnlyList<BodyRef> Dump(DumpScope scope, string meshDirectory) =>
            scope.Components.SelectMany(
                component => DumpComponent(scope, component, meshDirectory)).ToArray();

        public IReadOnlyList<BodyRef> DumpComponent(
            DumpScope scope, ScopedComponent component, string meshDirectory)
        {
            Exported.Add(component);
            Directories.Add(meshDirectory);

            if (Gap != null)
            {
                scope.Gaps.Add(GapKind.NotExtracted, "body", null, Gap, null);
                return Array.Empty<BodyRef>();
            }

            string bodyId = scope.BodyIds.Next();
            string fileName = component.Id.Replace(':', '-') + "-" + bodyId.Replace(':', '-') + ".glb";
            return new[]
            {
                new BodyRef
                {
                    Id = bodyId,
                    PersistRef = "cmVm",
                    PersistRefScope = "doc:2",
                    ComponentId = component.Id,
                    MeshFile = PackageWriter.MeshDirectoryName + "/" + fileName,
                    TriangleCount = 12,
                    IsSolid = true,
                },
            };
        }
    }
}
