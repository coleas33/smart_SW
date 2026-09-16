using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T023. The feature dumper is the only phase that reads a part's whole tree, and every RMS
/// rule is downstream of it, so what it records - and what it refuses to invent - is pinned
/// here over a fake <see cref="IFeatureReader"/>, on a machine with no SOLIDWORKS seat.
///
/// Four properties matter more than the field-by-field mapping:
///
///   * <b>Once per document.</b> A part used forty times has one tree, not forty. Rows per
///     instance would multiply every finding by the instance count.
///   * <b>Nothing is defaulted.</b> A read that failed is null plus a Gap of the entity kind
///     data-model section 1 names, so the rule layer reports unresolved instead of passing.
///   * <b>Nothing mutates.</b> The radius comes off <c>GetDefinition</c> without
///     <c>AccessSelections</c> (which rolls the model back), asserted on the member names the
///     production code actually put through the gate.
///   * <b>It teaches the census nothing.</b> Feature types are classified in Python against
///     <c>rms_types.yaml</c> (research R7), so this dumper consumes no type name and feeds
///     <see cref="TypeNameCensus"/> no pass.
/// </summary>
public class FeatureDumperTests
{
    private const string AssemblyPath = @"C:\vault\bracket-assy\bracket-assy.SLDASM";
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
    private const string CoverPath = @"C:\vault\bracket-assy\cover.SLDPRT";

    private readonly FakeFeatureReader _reader = new FakeFeatureReader();
    private readonly RecordingObserver _observer = new RecordingObserver();
    private readonly SwGate _gate = new SwGate();

    private DumpScope _scope = null!;

    public FeatureDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- one tree per document ---------------------------------------------------

    [Fact]
    public void Dump_WalksEachDocumentOnce_NotOncePerInstance()
    {
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(Feat("Sketch1", "ProfileFeature")));
        housing.Features.Add(Node(Feat("Boss-Extrude1", "Extrusion")));

        IReadOnlyList<Feature> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("housing-2", HousingPath));

        Assert.Equal(new[] { "Sketch1", "Boss-Extrude1" }, rows.Select(r => r.Name));
        Assert.Equal(new[] { HousingPath }, _reader.DocumentRequests);
    }

    [Fact]
    public void Dump_AllocatesIdsAcrossDocumentsWhileIndexRestarts()
    {
        _reader.Add(HousingPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));
        _reader.Add(CoverPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        IReadOnlyList<Feature> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Equal(new[] { "feat:0001", "feat:0002" }, rows.Select(r => r.Id));
        Assert.Equal(new[] { 0, 0 }, rows.Select(r => r.Index));
        Assert.Equal(
            new[] { _scope.DocumentId(HousingPath), _scope.DocumentId(CoverPath) },
            rows.Select(r => r.DocumentId));
    }

    [Fact]
    public void Dump_TakesIndexDepthAndFolderFromTheIndexer()
    {
        // The nested traversal shape: the folder owns its contents as sub-features. Depth
        // and folder_id come from structure alone - the dumper reads no name and no type.
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(
            Feat("3-Core", "FtrFolder"),
            Node(Feat("Boss-Extrude1", "Extrusion"))));
        housing.Features.Add(Node(Feat("Fillet1", "Fillet")));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.Equal(new[] { 0, 1, 2 }, rows.Select(r => r.Index));
        Assert.Equal(new[] { 0, 1, 0 }, rows.Select(r => r.Depth));
        Assert.Equal(new string?[] { null, "feat:0001", null }, rows.Select(r => r.FolderId));
    }

    [Fact]
    public void Dump_RecordsTheConfigurationTheTreeWasReadIn()
    {
        FakeDocument housing = _reader.Add(HousingPath);
        housing.ActiveConfiguration = "As Machined";
        housing.Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath, "As Machined"));

        Assert.Equal("As Machined", Assert.Single(rows).Configuration);
    }

    [Fact]
    public void Dump_RecordsTheTypeNameVerbatimAndTheName()
    {
        _reader.Add(HousingPath).Features.Add(Node(Feat("Mirror1", "MirrorPattern")));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Equal("Mirror1", row.Name);
        Assert.Equal("MirrorPattern", row.TypeName);
    }

    [Fact]
    public void Dump_AssemblyDocuments_AreNotWalked()
    {
        // An assembly has a feature tree too; RMS part rules are about parts, and the
        // subassembly documents are named in Python's coverage instead.
        _reader.Add(AssemblyPath).Features.Add(Node(Feat("MateGroup1", "MateGroup")));

        Assert.Empty(Dump(Root()));
        Assert.Empty(_reader.DocumentRequests);
    }

    // ---- component state ---------------------------------------------------------

    [Theory]
    [InlineData(SuppressionState.Lightweight)]
    [InlineData(SuppressionState.Suppressed)]
    [InlineData(SuppressionState.Unloaded)]
    public void Dump_ComponentThatIsNotResolved_IsAGapAndIsNeverResolved(SuppressionState state)
    {
        // Resolving a lightweight component changes the session the engineer is working in,
        // so the tree is left unread and the gap says which state stopped it.
        _reader.Add(HousingPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath, state: state)));

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_tree_unavailable");
        Assert.Equal("cmp:0002", gap.EntityId);
        Assert.Contains(PackageSerializer.EnumToJsonName(state), gap.Reason, StringComparison.Ordinal);
        Assert.Empty(_reader.DocumentRequests);
    }

    [Fact]
    public void Dump_OneUnresolvedInstance_DoesNotStopAResolvedOneOfTheSameDocument()
    {
        _reader.Add(HousingPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        IReadOnlyList<Feature> rows = Dump(
            Root(),
            Part("housing-1", HousingPath, state: SuppressionState.Lightweight),
            Part("housing-2", HousingPath));

        Assert.Single(rows);
        Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_tree_unavailable");
    }

    [Fact]
    public void Dump_ComponentWithNoLoadedDocument_IsAGapAndNoRows()
    {
        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_tree_unavailable");
        Assert.Equal("cmp:0002", gap.EntityId);
    }

    [Fact]
    public void Dump_DocumentUsedUnderAnotherConfiguration_IsAFeatureTreeConfigurationGap()
    {
        // The tree is read in the document's active configuration only. A part instanced
        // under a second configuration may have different features there, and the rules must
        // say so rather than judge the wrong tree.
        FakeDocument housing = _reader.Add(HousingPath);
        housing.ActiveConfiguration = "Default";
        housing.Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        Dump(Root(), Part("housing-1", HousingPath), Part("housing-2", HousingPath, "Machined"));

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_tree_configuration");
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Contains("Machined", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("Default", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_DocumentUsedUnderOneConfiguration_RaisesNoConfigurationGap()
    {
        _reader.Add(HousingPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        Dump(Root(), Part("housing-1", HousingPath), Part("housing-2", HousingPath));

        Assert.DoesNotContain(_scope.Gaps.Gaps, g => g.EntityKind == "feature_tree_configuration");
    }

    [Fact]
    public void Dump_WalkThatFailed_IsAGapAndTheOtherDocumentsAreStillRead()
    {
        _reader.Add(HousingPath).WalkFailure = new InvalidOperationException("the tree went away");
        _reader.Add(CoverPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        IReadOnlyList<Feature> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Single(rows);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature");
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Contains("the tree went away", gap.Error, StringComparison.Ordinal);
    }

    // ---- the three whole-document drops ------------------------------------------
    //
    // A resolved component whose tree could not be read whole leaves the document with no
    // rows. The rule layer reads component suppression and features[], so without a gap of
    // the kind it keys on - feature_tree_unavailable, the kind data-model section 1 names
    // for "tree not read" - it would grade the document as a fully read empty tree and
    // report a pass for six fail-severity rules. Each drop therefore records BOTH gaps: the
    // `feature` one carries which read failed, this one says the tree is not there.

    [Fact]
    public void Dump_ConfigurationThatCouldNotBeRead_DropsTheDocumentWithBothGaps()
    {
        FakeDocument housing = _reader.Add(HousingPath);
        housing.ConfigurationFailure = new InvalidOperationException("no active configuration");
        housing.Features.Add(Node(Feat("Sketch1", "ProfileFeature")));
        _reader.Add(CoverPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        IReadOnlyList<Feature> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Equal(new[] { _scope.DocumentId(CoverPath) }, rows.Select(r => r.DocumentId));
        Assert.Contains("no active configuration", Failure().Error, StringComparison.Ordinal);
        AssertTreeUnavailable("configuration");
    }

    [Fact]
    public void Dump_WalkThatFailed_AlsoSaysTheTreeIsUnavailable()
    {
        _reader.Add(HousingPath).WalkFailure = new InvalidOperationException("the tree went away");

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));

        AssertTreeUnavailable("walk");
    }

    [Fact]
    public void Dump_FeatureWithNoPersistRef_AlsoSaysTheTreeIsUnavailable()
    {
        FakeDocument housing = _reader.Add(HousingPath);
        FakeFeature unreferenced = Feat("Boss-Extrude1", "Extrusion");
        unreferenced.PersistRef = null;
        housing.Features.Add(Node(unreferenced));

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));

        AssertTreeUnavailable("persistent reference");
    }

    [Fact]
    public void Dump_WalkWithAHoleInIt_IsAGapAndTheOtherDocumentsAreStillRead()
    {
        // FeatureTreeIndexer refuses to index a walk with nothing in it rather than shift
        // every later index and silently re-group the tree. That throw must become this
        // document's gap: uncaught it escapes the phase, and PackageWriter then skips holes,
        // cosmetic threads, fasteners, faces and meshes for the whole package.
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(Feat("Sketch1", "ProfileFeature")));
        housing.Features.Add(null!);
        _reader.Add(CoverPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        IReadOnlyList<Feature> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Equal(new[] { _scope.DocumentId(CoverPath) }, rows.Select(r => r.DocumentId));
        Assert.Contains("ArgumentException", Failure().Error, StringComparison.Ordinal);
        AssertTreeUnavailable("index");
    }

    /// <summary>The one `feature` gap the drop recorded, naming the read that failed.</summary>
    private Gap Failure() =>
        Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature" && g.Error != null);

    /// <summary>The dropped document's `feature_tree_unavailable` gap and the reason's verb.</summary>
    private void AssertTreeUnavailable(string reason)
    {
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_tree_unavailable");
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Contains("housing.SLDPRT", gap.Reason, StringComparison.Ordinal);
        Assert.Contains(reason, gap.Reason, StringComparison.Ordinal);
    }

    // ---- per-feature reads -------------------------------------------------------

    [Fact]
    public void Dump_ChildrenAndParents_AreRecordedAsFeatureIds()
    {
        FakeDocument housing = _reader.Add(HousingPath);
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        FakeFeature boss = Feat("Boss-Extrude1", "Extrusion");
        sketch.Children.Add(boss);
        boss.Parents.Add(sketch);
        housing.Features.Add(Node(sketch));
        housing.Features.Add(Node(boss));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.Equal(new[] { "feat:0002" }, rows[0].ChildIds);
        Assert.Empty(rows[0].ParentIds!);
        Assert.Equal(new[] { "feat:0001" }, rows[1].ParentIds);
        Assert.Empty(rows[1].ChildIds!);
    }

    [Fact]
    public void Dump_ChildrenUnavailable_IsNullPlusAFeatureChildrenGap()
    {
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        sketch.ChildrenThrow = true;
        _reader.Add(HousingPath).Features.Add(Node(sketch));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.ChildIds);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_children");
        Assert.Equal("feat:0001", gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Fact]
    public void Dump_ParentsUnavailable_IsNullPlusAFeatureParentsGap()
    {
        FakeFeature boss = Feat("Boss-Extrude1", "Extrusion");
        boss.ParentsThrow = true;
        _reader.Add(HousingPath).Features.Add(Node(boss));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.ParentIds);
        Assert.Equal("feat:0001", Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_parents").EntityId);
    }

    [Fact]
    public void Dump_ChildThisDocumentDidNotWalk_IsAGapRatherThanASilentlyShorterList()
    {
        // A dependent the walk never saw cannot be named, and dropping it silently would
        // make a reference rule pass on a feature that does have an internal reference.
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        sketch.Children.Add(Feat("Elsewhere", "Extrusion"));
        _reader.Add(HousingPath).Features.Add(Node(sketch));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Empty(row.ChildIds!);
        Assert.Equal("feat:0001", Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_children").EntityId);
    }

    [Fact]
    public void Dump_Description_IsRecordedAndBlankStaysBlank()
    {
        FakeFeature described = Feat("Boss-Extrude1", "Extrusion");
        described.Description = "main boss";
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(described));
        housing.Features.Add(Node(Feat("Fillet1", "Fillet")));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.Equal("main boss", rows[0].Description);
        Assert.Equal(string.Empty, rows[1].Description);
        Assert.DoesNotContain(_scope.Gaps.Gaps, g => g.EntityKind == "feature_description");
    }

    [Fact]
    public void Dump_DescriptionThatCouldNotBeRead_IsNullPlusAFeatureDescriptionGap()
    {
        // Null and "" are different answers: "" is a feature with no description, which the
        // description rule fails; null is "we do not know", which it reports unresolved.
        FakeFeature boss = Feat("Boss-Extrude1", "Extrusion");
        boss.DescriptionThrows = true;
        _reader.Add(HousingPath).Features.Add(Node(boss));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Description);
        Assert.Equal("feat:0001", Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_description").EntityId);
    }

    [Fact]
    public void Dump_SuppressionIsReadInTheDocumentsActiveConfiguration()
    {
        FakeDocument housing = _reader.Add(HousingPath);
        housing.ActiveConfiguration = "As Machined";
        FakeFeature boss = Feat("Boss-Extrude1", "Extrusion");
        boss.SuppressedIn.Add("As Machined");
        FakeFeature fillet = Feat("Fillet1", "Fillet");
        fillet.SuppressedIn.Add("Default");
        housing.Features.Add(Node(boss));
        housing.Features.Add(Node(fillet));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath, "As Machined"));

        Assert.True(rows[0].Suppressed);
        Assert.False(rows[1].Suppressed);
        Assert.Equal(new[] { "As Machined", "As Machined" }, _reader.SuppressionConfigurations);
    }

    [Fact]
    public void Dump_SuppressionThatCouldNotBeRead_IsNullPlusAGap()
    {
        FakeFeature boss = Feat("Boss-Extrude1", "Extrusion");
        boss.SuppressedThrows = true;
        _reader.Add(HousingPath).Features.Add(Node(boss));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Suppressed);
        Assert.Contains(_scope.Gaps.Gaps, g => g.EntityId == "feat:0001" && g.Kind == GapKind.ToolError);
    }

    [Fact]
    public void Dump_ErrorCode_IsRecordedAndNullWhenUnreadable()
    {
        FakeFeature failed = Feat("Boss-Extrude1", "Extrusion");
        failed.ErrorCode = 4;
        FakeFeature unreadable = Feat("Fillet1", "Fillet");
        unreadable.ErrorCodeThrows = true;
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(failed));
        housing.Features.Add(Node(unreadable));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.Equal(4, rows[0].ErrorCode);
        Assert.Null(rows[1].ErrorCode);
    }

    // ---- sketches ----------------------------------------------------------------

    [Fact]
    public void Dump_SketchStatus_IsRecordedVerbatimWithTheConsumers()
    {
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        sketch.IsSketch = true;

        // 7 is "autosolve off" on 2024; it is recorded as 7 and mapped in Python, because a
        // dumper that mapped it would have to hold the RMS table (research R7).
        sketch.SketchStatus = 7;
        FakeFeature boss = Feat("Boss-Extrude1", "Extrusion");
        sketch.Children.Add(boss);
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(sketch));
        housing.Features.Add(Node(boss));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.Equal(7, rows[0].Sketch!.RawStatus);
        Assert.Equal(new[] { "feat:0002" }, rows[0].Sketch!.ConsumerIds);
        Assert.Null(rows[1].Sketch);
    }

    [Fact]
    public void Dump_SketchStatusThatFailed_IsNullPlusASketchStatusGap()
    {
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        sketch.IsSketch = true;
        sketch.SketchStatusThrows = true;
        _reader.Add(HousingPath).Features.Add(Node(sketch));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Sketch!.RawStatus);
        Assert.Equal("feat:0001", Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "sketch_status").EntityId);
    }

    [Fact]
    public void Dump_SketchWhoseChildrenFailed_HasNullConsumersAndOneChildrenGap()
    {
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        sketch.IsSketch = true;
        sketch.SketchStatus = 2;
        sketch.ChildrenThrow = true;
        _reader.Add(HousingPath).Features.Add(Node(sketch));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Sketch!.ConsumerIds);
        Assert.Null(row.ChildIds);
        Assert.Equal(2, row.Sketch!.RawStatus);

        // One gap, not two: the consumers ARE the children, so a second gap would double
        // count the same failure in the coverage report.
        Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature_children");
    }

    [Fact]
    public void Dump_SpecificFeatureThatFailed_IsNoSketchAndASketchStatusGap()
    {
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        sketch.SpecificFeatureThrows = true;
        _reader.Add(HousingPath).Features.Add(Node(sketch));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Sketch);
        Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "sketch_status");
    }

    // ---- fillets -----------------------------------------------------------------

    [Fact]
    public void Dump_SimpleFillet_RecordsTheDefaultRadiusInMeters()
    {
        FakeFeature fillet = Feat("Fillet1", "Fillet");
        fillet.Definition = FilletDefinitionKind.Simple;
        fillet.Radius = 0.003;
        _reader.Add(HousingPath).Features.Add(Node(fillet));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Equal(0.003, row.Fillet!.DefaultRadius!.Value);
        Assert.Equal(LengthUnit.M, row.Fillet!.DefaultRadius!.Unit);
        Assert.DoesNotContain(_scope.Gaps.Gaps, g => g.EntityKind == "fillet_radius");
    }

    [Fact]
    public void Dump_VariableFillet_IsNullPlusAFilletRadiusGap()
    {
        // A variable fillet has no single radius; reporting one would be an invented number.
        FakeFeature fillet = Feat("Fillet1", "Fillet");
        fillet.Definition = FilletDefinitionKind.Variable;
        _reader.Add(HousingPath).Features.Add(Node(fillet));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Fillet!.DefaultRadius);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "fillet_radius");
        Assert.Equal("feat:0001", gap.EntityId);
        Assert.Contains("variable", gap.Reason, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Dump_RadiusThatCouldNotBeRead_IsNullPlusAFilletRadiusGap()
    {
        FakeFeature fillet = Feat("Fillet1", "Fillet");
        fillet.Definition = FilletDefinitionKind.Simple;
        fillet.RadiusThrows = true;
        _reader.Add(HousingPath).Features.Add(Node(fillet));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Fillet!.DefaultRadius);
        Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "fillet_radius");
    }

    [Fact]
    public void Dump_FeatureThatIsNotAFillet_HasNoFilletInfoAndNoGap()
    {
        FakeFeature boss = Feat("Boss-Extrude1", "Extrusion");
        boss.Definition = FilletDefinitionKind.NotAFillet;
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(boss));

        // A feature with no definition object at all, the answer for a folder.
        housing.Features.Add(Node(Feat("3-Core", "FtrFolder")));

        IReadOnlyList<Feature> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.All(rows, row => Assert.Null(row.Fillet));
        Assert.DoesNotContain(_scope.Gaps.Gaps, g => g.EntityKind == "fillet_radius");
    }

    // ---- persistent references ---------------------------------------------------

    [Fact]
    public void Dump_PersistRefsAreScopedToThePartDocument()
    {
        _reader.Add(HousingPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        Feature row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Equal("RmVhdA==", row.PersistRef);
        Assert.Equal(_scope.DocumentId(HousingPath), row.PersistRefScope);
    }

    [Fact]
    public void Dump_FeatureWithNoPersistRef_DropsThatDocumentsRowsWithAGap()
    {
        // The IR requires a persistent reference on every entity (Principle IV), and a tree
        // missing one row silently re-groups every feature after it, so the document's tree
        // is dropped whole and the gap names the feature that could not be referenced.
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(Feat("Sketch1", "ProfileFeature")));
        FakeFeature unreferenced = Feat("Boss-Extrude1", "Extrusion");
        unreferenced.PersistRef = null;
        housing.Features.Add(Node(unreferenced));
        _reader.Add(CoverPath).Features.Add(Node(Feat("Sketch1", "ProfileFeature")));

        IReadOnlyList<Feature> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Equal(new[] { _scope.DocumentId(CoverPath) }, rows.Select(r => r.DocumentId));
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "feature");
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Contains("Boss-Extrude1", gap.Reason, StringComparison.Ordinal);
    }

    // ---- the guard and the census ------------------------------------------------

    [Fact]
    public void Dump_ReadsTheFilletRadiusOffGetDefinitionWithoutAccessSelections()
    {
        // AccessSelections rolls the model back and must be paired with
        // ReleaseSelectionAccess; the radius does not need it (research R5), so it is not
        // called at all. These are the names the production code put through the gate.
        FakeFeature fillet = Feat("Fillet1", "Fillet");
        fillet.Definition = FilletDefinitionKind.Simple;
        fillet.Radius = 0.002;
        _reader.Add(HousingPath).Features.Add(Node(fillet));

        Dump(Root(), Part("housing-1", HousingPath));

        Assert.Contains("GetDefinition", _observer.Members);
        Assert.DoesNotContain("AccessSelections", _observer.Members);
        Assert.DoesNotContain("ModifyDefinition", _observer.Members);
        Assert.DoesNotContain("ReleaseSelectionAccess", _observer.Members);
    }

    [Fact]
    public void Dump_NoMutatingMemberEverPassesThroughTheGate()
    {
        FakeFeature sketch = Feat("Sketch1", "ProfileFeature");
        sketch.IsSketch = true;
        FakeFeature fillet = Feat("Fillet1", "Fillet");
        fillet.Definition = FilletDefinitionKind.Variable;
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(sketch));
        housing.Features.Add(Node(fillet));

        Dump(Root(), Part("housing-1", HousingPath));

        Assert.NotEmpty(_observer.Members);
        foreach (string member in _observer.Members)
        {
            // The shipped denylist, not a copy of it.
            ReadOnlyGuard.Assert(member);
        }

        // The members this feature's own mutation path would use (research R6). They are
        // not on the denylist yet - T049 adds them - so naming them here is what keeps this
        // dumper out of the suppress-test's API family.
        foreach (string mutating in new[]
        {
            "SetSuppression2", "SetSuppression", "ForceRebuild3", "ForceRebuildAll",
            "EditRollback", "SetSaveFlag", "EditSuppress2", "EditUnsuppress2",
        })
        {
            Assert.DoesNotContain(mutating, _observer.Members);
        }
    }

    [Fact]
    public void Dump_FeedsTheTypeNameCensusNothing()
    {
        // The census exists to say "this type was walked past and no dumper read it". This
        // dumper reads EVERY feature and classifies none of them, so a pass from here would
        // report every ordinary type name as a gap on every part (research R7).
        FakeDocument housing = _reader.Add(HousingPath);
        housing.Features.Add(Node(Feat("Sketch1", "ProfileFeature")));
        housing.Features.Add(Node(Feat("SomeTypeNobodyReads", "SomeTypeNobodyReads")));

        Dump(Root(), Part("housing-1", HousingPath));

        Assert.Empty(_scope.Gaps.TypeNames.Unconsumed());
    }

    [Fact]
    public void Constructor_NullArgument_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new FeatureDumper(null!, _reader));
        Assert.Throws<ArgumentNullException>(() => new FeatureDumper(_gate, null!));
    }

    [Fact]
    public void Dump_NullScope_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new FeatureDumper(_gate, _reader).Dump(null!));
    }

    // ---- harness -----------------------------------------------------------------

    private IReadOnlyList<Feature> Dump(params ComponentNode[] nodes)
    {
        _scope = NewScope(nodes);
        return new FeatureDumper(_gate, _reader).Dump(_scope);
    }

    private static DumpScope NewScope(ComponentNode[] nodes)
    {
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = AssemblyPath,
            RootDocumentKind = DocumentKind.Assembly,
            DesignName = "bracket-assy",
            ActiveConfiguration = "Default",
        };

        tree.Nodes.AddRange(nodes);

        var scope = new DumpScope(new GapCollector(), new DumpOptions { OutputDirectory = "out" }, tree);

        // Ids exactly as PackageWriter allocates them, so cmp:0001 is the root here too.
        var ids = new IdAllocator("cmp");
        foreach (ComponentNode node in nodes)
        {
            scope.AddComponent(ids.Next(), scope.DocumentId(node.DocumentPath), node);
        }

        return scope;
    }

    private static ComponentNode Root() => new ComponentNode
    {
        Key = "bracket-assy-1",
        ParentKey = null,
        Name = "bracket-assy-1",
        DocumentPath = AssemblyPath,
        DocumentKind = DocumentKind.Assembly,
        ReferencedConfiguration = "Default",
        Transform = Transform.Identity(),
        Suppression = SuppressionState.Resolved,
        PersistRef = "Q29tcA==",
        PersistRefScopePath = AssemblyPath,
        Handle = new object(),
    };

    private static ComponentNode Part(
        string key,
        string path,
        string configuration = "Default",
        SuppressionState state = SuppressionState.Resolved) => new ComponentNode
        {
            Key = key,
            ParentKey = "bracket-assy-1",
            Name = key,
            DocumentPath = path,
            DocumentKind = DocumentKind.Part,
            ReferencedConfiguration = configuration,
            Transform = Transform.Identity(),
            Suppression = state,
            PersistRef = "Q29tcA==",
            PersistRefScopePath = AssemblyPath,
            Handle = new object(),
        };

    private static FakeFeature Feat(string name, string typeName) =>
        new FakeFeature { Name = name, TypeName = typeName };

    private static FeatureTreeNode Node(FakeFeature feature, params FeatureTreeNode[] subFeatures)
    {
        var node = new FeatureTreeNode
        {
            Name = feature.Name,
            TypeName = feature.TypeName,
            Handle = feature,
        };

        node.SubFeatures.AddRange(subFeatures);
        return node;
    }

    /// <summary>Every member the gate was asked about, in order, duplicates and all.</summary>
    private sealed class RecordingObserver : ISwGateObserver
    {
        public List<string> Members { get; } = new List<string>();

        public void Gated(string interopMember) => Members.Add(interopMember);

        public void Refused(MutatingCallError refusal)
        {
        }
    }

    /// <summary>One live feature, with a switch for every read that can fail.</summary>
    private sealed class FakeFeature
    {
        public string Name { get; set; } = string.Empty;

        public string TypeName { get; set; } = string.Empty;

        public string? Description { get; set; } = string.Empty;

        public bool DescriptionThrows { get; set; }

        public int ErrorCode { get; set; }

        public bool ErrorCodeThrows { get; set; }

        /// <summary>Configurations the feature is suppressed in.</summary>
        public HashSet<string> SuppressedIn { get; } = new HashSet<string>(StringComparer.Ordinal);

        public bool SuppressedThrows { get; set; }

        public List<FakeFeature> Children { get; } = new List<FakeFeature>();

        public bool ChildrenThrow { get; set; }

        public List<FakeFeature> Parents { get; } = new List<FakeFeature>();

        public bool ParentsThrow { get; set; }

        public bool IsSketch { get; set; }

        public bool SpecificFeatureThrows { get; set; }

        public int SketchStatus { get; set; }

        public bool SketchStatusThrows { get; set; }

        /// <summary>Null means GetDefinition answered nothing, as it does for a folder.</summary>
        public FilletDefinitionKind? Definition { get; set; }

        public double Radius { get; set; }

        public bool RadiusThrows { get; set; }

        public string? PersistRef { get; set; } = "RmVhdA==";
    }

    /// <summary>One open part document.</summary>
    private sealed class FakeDocument
    {
        public FakeDocument(string path)
        {
            Path = path;
        }

        public string Path { get; }

        public string ActiveConfiguration { get; set; } = "Default";

        public List<FeatureTreeNode> Features { get; } = new List<FeatureTreeNode>();

        public Exception? WalkFailure { get; set; }

        public Exception? ConfigurationFailure { get; set; }
    }

    /// <summary>The seam: what a live SOLIDWORKS would answer, scripted.</summary>
    private sealed class FakeFeatureReader : IFeatureReader
    {
        private readonly Dictionary<string, FakeDocument> _documents =
            new Dictionary<string, FakeDocument>(StringComparer.OrdinalIgnoreCase);

        /// <summary>Every document the dumper asked for, in order.</summary>
        public List<string> DocumentRequests { get; } = new List<string>();

        /// <summary>Every configuration a suppression read named.</summary>
        public List<string> SuppressionConfigurations { get; } = new List<string>();

        public FakeDocument Add(string path)
        {
            var document = new FakeDocument(path);
            _documents[path] = document;
            return document;
        }

        public object? Document(ScopedComponent component)
        {
            DocumentRequests.Add(component.Node.DocumentPath);
            FakeDocument found;
            return _documents.TryGetValue(component.Node.DocumentPath, out found) ? found : null;
        }

        public string ActiveConfiguration(object document)
        {
            FakeDocument doc = Doc(document);
            if (doc.ConfigurationFailure != null)
            {
                throw doc.ConfigurationFailure;
            }

            return doc.ActiveConfiguration;
        }

        public IReadOnlyList<FeatureTreeNode> Walk(object document)
        {
            FakeDocument doc = Doc(document);
            if (doc.WalkFailure != null)
            {
                throw doc.WalkFailure;
            }

            return doc.Features;
        }

        public string? Description(object feature) =>
            Throwing(feature, f => f.DescriptionThrows, "Description").Description;

        public int ErrorCode(object feature) =>
            Throwing(feature, f => f.ErrorCodeThrows, "GetErrorCode2").ErrorCode;

        public bool Suppressed(object feature, string configuration)
        {
            SuppressionConfigurations.Add(configuration);
            return Throwing(feature, f => f.SuppressedThrows, "IsSuppressed2")
                .SuppressedIn.Contains(configuration);
        }

        public IReadOnlyList<object> Children(object feature) =>
            Throwing(feature, f => f.ChildrenThrow, "GetChildren").Children.Cast<object>().ToList();

        public IReadOnlyList<object> Parents(object feature) =>
            Throwing(feature, f => f.ParentsThrow, "GetParents").Parents.Cast<object>().ToList();

        public object? Sketch(object feature)
        {
            FakeFeature f = Throwing(feature, x => x.SpecificFeatureThrows, "GetSpecificFeature2");
            return f.IsSketch ? feature : null;
        }

        public int SketchConstrainedStatus(object sketch) =>
            Throwing(sketch, f => f.SketchStatusThrows, "GetConstrainedStatus").SketchStatus;

        public object? Definition(object feature)
        {
            FakeFeature f = F(feature);
            return f.Definition == null ? null : feature;
        }

        public FilletDefinitionKind ClassifyFillet(object definition) => F(definition).Definition!.Value;

        public double SimpleFilletDefaultRadius(object definition) =>
            Throwing(definition, f => f.RadiusThrows, "DefaultRadius").Radius;

        public ScopedPersistRef? PersistRef(object document, object feature)
        {
            string? reference = F(feature).PersistRef;
            if (reference == null)
            {
                return null;
            }

            string path = Doc(document).Path;
            return new ScopedPersistRef(reference, DocumentIds.For(path), path);
        }

        private static FakeDocument Doc(object document) => (FakeDocument)document;

        private static FakeFeature F(object feature) => (FakeFeature)feature;

        private static FakeFeature Throwing(object feature, Func<FakeFeature, bool> fails, string member)
        {
            FakeFeature f = F(feature);
            if (fails(f))
            {
                throw new InvalidOperationException($"{member} failed for '{f.Name}'.");
            }

            return f;
        }
    }
}
