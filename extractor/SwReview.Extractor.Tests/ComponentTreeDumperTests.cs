using System;
using System.Collections.Generic;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T033. The four schema 1.4.0 reads <see cref="ComponentTreeDumper.ReadNode"/> adds to every
/// traversed instance: the appearance override, the transparency slot, the visibility state
/// and the pattern origin (<c>contracts/ir-additions.md</c> section 1).
///
/// They live inside <c>Traverse</c>, where no <c>cmp:NNNN</c> exists yet, so every failure is
/// a <see cref="GapCollector.TryStep"/> gap with a null entity id - the same shape every other
/// traversal gap has, and the reason the deferred-gap dance
/// <c>ConstrainedStatusError</c> needs is not repeated here.
///
/// The reads are pinned through the dumper's gated helpers rather than through
/// <c>Traverse</c>, because the traversal holds a live <c>IComponent2</c> and this machine has
/// no SOLIDWORKS seat. Each helper owns the policy: which read is worth making at all, what
/// becomes a gap, and what is recorded when the answer is unknown. The interop expression
/// (<c>component.Visible</c>, <c>component.GetMaterialPropertyValues2(1, null)</c>) stays at
/// the call site.
///
/// Two of the four are here because the macro got them wrong:
///
///   * <b>The transparency slot replaces a -1 sentinel</b> that conflated "no appearance
///     override" with a real value, so <c>has_appearance_override</c> is read first and the
///     slot is only asked for when there is something to read.
///   * <b><c>IsHidden(bool)</c> is never called.</b> With ConsiderSuppressed it is the macro's
///     difference-c bug - a suppressed component reading as hidden - and <c>Visible</c>
///     answers the same question with one fewer conflated state (research R3.4).
/// </summary>
public class ComponentTreeDumperTests
{
    private const string Key = "sub-2/bracket-3";
    private const string DrawingPath = @"C:\vault\bracket-assy\bracket-assy.SLDDRW";
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
    private const string RailPath = @"C:\vault\bracket-assy\rail.SLDASM";

    private readonly GapCollector _gaps = new GapCollector();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    public ComponentTreeDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- HasMaterialPropertyValues -------------------------------------------------

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ReadHasAppearanceOverride_RecordsTheAnswerThroughTheGate(bool answer)
    {
        bool? has = ComponentTreeDumper.ReadHasAppearanceOverride(Key, _gaps, _gate, () => answer);

        Assert.Equal(answer, has);
        Assert.Equal(new[] { "HasMaterialPropertyValues" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadHasAppearanceOverride_ThatThrew_IsNullPlusAComponentTransparencyGap()
    {
        bool? has = ComponentTreeDumper.ReadHasAppearanceOverride(
            Key, _gaps, _gate, () => throw new InvalidOperationException("no answer"));

        Assert.Null(has);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_transparency", gap.EntityKind);

        // Inside Traverse: no cmp:NNNN exists yet, so the gap names the component in its
        // reason and carries no entity id, exactly as every other traversal gap does.
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
        Assert.Contains("no answer", gap.Error!, StringComparison.Ordinal);
    }

    // ---- GetMaterialPropertyValues2 slot 7 -----------------------------------------

    [Fact]
    public void ReadTransparency_RecordsSlotSevenVerbatim()
    {
        // Verbatim: the extractor does not decide which number means transparent. Which it is
        // - and whether slot 7 is the slot on this build - is PROBE-2, and until it answers
        // the Python constant TRANSPARENCY_POLARITY leaves the check unresolved.
        var values = new double[] { 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 0.9 };

        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true, key: Key, gaps: _gaps, gate: _gate, read: () => values);

        Assert.Equal(0.85, transparency);
        Assert.Equal(new[] { "GetMaterialPropertyValues2" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadTransparency_ReadsSlotSevenOutOfABoxedVariantArrayToo()
    {
        object[] values = { 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.25, 0.9 };

        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true, key: Key, gaps: _gaps, gate: _gate, read: () => values);

        Assert.Equal(0.25, transparency);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadTransparency_WithNoAppearanceOverride_IsNullWithoutAGapAndWithoutTheCall()
    {
        // There is nothing to read, so the null is not a gap: a coverage row on every
        // component of every assembly would bury the components that really could not be read
        // (contracts/ir-additions.md section 1).
        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: false,
            key: Key,
            gaps: _gaps,
            gate: _gate,
            read: () => throw new InvalidOperationException("there is nothing to read"));

        Assert.Null(transparency);
        Assert.Empty(_gaps.Gaps);
        Assert.Empty(_observer.Members);
    }

    [Fact]
    public void ReadTransparency_WhenTheOverrideItselfWasUnreadable_AddsNoSecondGap()
    {
        // has_appearance_override null means ReadHasAppearanceOverride already wrote the gap.
        // Asking anyway would record the same failure twice in the coverage report.
        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: null,
            key: Key,
            gaps: _gaps,
            gate: _gate,
            read: () => throw new InvalidOperationException("never called"));

        Assert.Null(transparency);
        Assert.Empty(_gaps.Gaps);
        Assert.Empty(_observer.Members);
    }

    [Fact]
    public void ReadTransparency_ThatThrew_IsNullPlusAComponentTransparencyGap()
    {
        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true,
            key: Key,
            gaps: _gaps,
            gate: _gate,
            read: () => throw new InvalidOperationException("the appearance did not answer"));

        Assert.Null(transparency);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_transparency", gap.EntityKind);
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(null)]
    [InlineData(4)]
    public void ReadTransparency_WithNoSlotSeven_IsNullPlusAComponentTransparencyGap(int? length)
    {
        // An answer that is not a nine-slot array is an answer nobody can read slot 7 out of.
        // Unknown stays unknown: it is a gap, never a zero.
        object? answer = length == null ? null : new double[length.Value];

        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true, key: Key, gaps: _gaps, gate: _gate, read: () => answer);

        Assert.Null(transparency);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_transparency", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    // ---- Visible -------------------------------------------------------------------

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(-1)]
    public void ReadVisibility_RecordsTheStateVerbatim(int state)
    {
        // swComponentVisibilityState_e: hidden 0, visible 1, unknown -1. The extractor records
        // the number and Python names it (plan Structure Decision 1).
        int? visibility = ComponentTreeDumper.ReadVisibility(Key, _gaps, _gate, () => state);

        Assert.Equal(state, visibility);
        Assert.Equal(new[] { "Visible" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadVisibility_NeverAsksIsHidden()
    {
        ComponentTreeDumper.ReadVisibility(Key, _gaps, _gate, () => 1);

        // research R3.4: with ConsiderSuppressed = true IsHidden is the macro's difference-c
        // bug, and with false it answers the same question with one fewer state.
        Assert.DoesNotContain("IsHidden", _observer.Members);
    }

    [Fact]
    public void ReadVisibility_ThatThrew_IsNullPlusAComponentVisibilityGap()
    {
        int? visibility = ComponentTreeDumper.ReadVisibility(
            Key, _gaps, _gate, () => throw new InvalidOperationException("no answer"));

        Assert.Null(visibility);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_visibility", gap.EntityKind);
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    // ---- IsPatternInstance ---------------------------------------------------------

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ReadIsPatternInstance_RecordsTheAnswerThroughTheGate(bool answer)
    {
        bool? pattern = ComponentTreeDumper.ReadIsPatternInstance(Key, _gaps, _gate, () => answer);

        Assert.Equal(answer, pattern);
        Assert.Equal(new[] { "IsPatternInstance" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadIsPatternInstance_ThatThrew_IsNullPlusAComponentPatternGap()
    {
        bool? pattern = ComponentTreeDumper.ReadIsPatternInstance(
            Key, _gaps, _gate, () => throw new InvalidOperationException("no answer"));

        Assert.Null(pattern);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_pattern", gap.EntityKind);
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void PatternId_AndIsPatternInstance_AreTwoFactsNotOne()
    {
        // pattern_id keeps the pattern's NAME for the reason text and cannot replace the
        // flag: a null pattern_id conflates "not in a pattern" with "the pattern map was
        // never built" (contracts/ir-additions.md section 1). The node carries both, and one
        // does not default the other.
        var node = new ComponentNode
        {
            Key = Key,
            PatternId = "LocalLPattern1",
            IsPatternInstance = ComponentTreeDumper.ReadIsPatternInstance(
                Key, _gaps, _gate, () => throw new InvalidOperationException("no answer")),
        };

        Assert.Equal("LocalLPattern1", node.PatternId);
        Assert.Null(node.IsPatternInstance);
    }

    // ---- the four fields travel on the node ----------------------------------------

    [Fact]
    public void TheFourFields_DefaultToUnknownOnANodeNobodyRead()
    {
        // Null, not false and not zero: a node built by a caller that never asked carries no
        // answer, and PackageWriter copies exactly that onto the instance.
        var node = new ComponentNode();

        Assert.Null(node.HasAppearanceOverride);
        Assert.Null(node.TransparencyRaw);
        Assert.Null(node.VisibilityRaw);
        Assert.Null(node.IsPatternInstance);
    }

    // ---- the drawing-rooted forest (T063, FR-025) -----------------------------------

    // ---- a drawing session has no configuration (feature 011 T015, attach.md section 2) ----

    [Fact]
    public void ActiveConfigurationOf_ADrawingRootIsTheEmptyStringAndItsConfigurationIsNeverAsked()
    {
        // The kind is read first and decides: a drawing session has no configuration, so asking
        // it for one would be a null dereference on the seat, and the design block records ""
        // ("empty for a drawing root, which has none").
        var asked = new List<string>();

        string configuration = ComponentTreeDumper.ActiveConfigurationOf(
            DocumentKind.Drawing, () => { asked.Add("configuration"); return "Default"; });

        Assert.Equal(string.Empty, configuration);
        Assert.Empty(asked);
    }

    [Theory]
    [InlineData(DocumentKind.Part)]
    [InlineData(DocumentKind.Assembly)]
    public void ActiveConfigurationOf_AModelRootIsTheSessionsBoundConfiguration(DocumentKind kind)
    {
        Assert.Equal("Machined", ComponentTreeDumper.ActiveConfigurationOf(kind, () => "Machined"));
    }

    [Fact]
    public void ActiveConfigurationOf_AnUnreadKindStillRecordsTheBoundConfiguration()
    {
        // As before feature 011: an unread kind is its own gap and traverses nothing, and the
        // configuration the session is bound to is still what the design block names.
        Assert.Equal("Default", ComponentTreeDumper.ActiveConfigurationOf(null, () => "Default"));
    }

    [Theory]
    [InlineData(DocumentKind.Part)]
    [InlineData(DocumentKind.Assembly)]
    [InlineData(null)]
    public void ActiveConfigurationOf_ASessionWithNoConfigurationNameIsTheEmptyStringNeverNull(
        DocumentKind? kind)
    {
        // ConfigurationName is null for a session with no configuration; the design block's
        // active_configuration is a required string, so null is written as "" rather than
        // leaking into the IR.
        Assert.Equal(string.Empty, ComponentTreeDumper.ActiveConfigurationOf(kind, () => null));
    }

    /// <summary>
    /// The forest root a drawing root is traversed under: the drawing document itself, with
    /// no parent, so the subtrees its views reference hang somewhere (research R9).
    ///
    /// Python walks it through and never grades it as a component of itself - an instance
    /// whose document is the root document is not one - which is why it can be synthesized
    /// here without inventing a component nobody modelled.
    /// </summary>
    [Fact]
    public void DrawingRootNode_IsTheDrawingDocumentItselfWithNoParent()
    {
        ComponentTreeResult tree = DrawingTree();

        ComponentNode root = ComponentTreeDumper.DrawingRootNode(
            tree, new ScopedPersistRef("RHJhd2luZw==", "doc:drw", DrawingPath));

        // Keyed on the drawing's PATH, not its file name. SOLIDWORKS names a drawing after
        // the model it documents, so a base-name key collides with the referenced model's in
        // the ordinary case; the name a report reads out lives in Name.
        Assert.Equal(DrawingPath, root.Key);
        Assert.Equal("bracket-assy", root.Name);
        Assert.Null(root.ParentKey);
        Assert.Equal(DrawingPath, root.DocumentPath);
        Assert.Equal(DocumentKind.Drawing, root.DocumentKind);
        Assert.Equal(SuppressionState.Resolved, root.Suppression);
        Assert.True(root.IsFixed);
        Assert.Equal("RHJhd2luZw==", root.PersistRef);
        Assert.Equal(DrawingPath, root.PersistRefScopePath);

        // The drawing is not an instance inside anything, so there is no constrained status
        // to read and no pattern to belong to. Null says so; false would be an answer nobody
        // gave.
        Assert.Null(root.ConstrainedStatusRaw);
        Assert.Null(root.IsPatternInstance);
        Assert.Null(root.PatternId);
    }

    [Fact]
    public void DrawingRootNode_WithNoPersistentReference_CarriesNoneAndStillStandsUp()
    {
        // PackageWriter turns the null into its own gap once cmp:NNNN exists, exactly as it
        // does for a part opened alone; the forest still hangs off this node.
        ComponentNode root = ComponentTreeDumper.DrawingRootNode(DrawingTree(), null);

        Assert.Null(root.PersistRef);
        Assert.Equal(DrawingPath, root.PersistRefScopePath);
    }

    [Fact]
    public void AddDrawingForest_HangsOneSubtreePerReferencedModelUnderTheForestRoot()
    {
        ComponentTreeResult tree = DrawingTree();
        ComponentNode root = ComponentTreeDumper.DrawingRootNode(tree, null);
        object housing = new object();
        object rail = new object();

        var walked = new List<(string Path, string ParentKey)>();

        ComponentTreeDumper.AddDrawingForest(
            tree,
            _gaps,
            root,
            new[]
            {
                new DrawingReference(HousingPath, housing),
                new DrawingReference(RailPath, rail),
            },
            (reference, parentKey) => walked.Add((reference.Path, parentKey)));

        // The forest root comes first, so cmp:0001 is the drawing and a reader can follow the
        // tree by id the way they can under an assembly root.
        Assert.Same(root, Assert.Single(tree.Nodes));
        Assert.Equal(new[] { (HousingPath, root.Key), (RailPath, root.Key) }, walked);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void AddDrawingForest_WalksAModelTwoViewsReferenceExactlyOnce()
    {
        // One document, one subtree: walking it twice would grade its parts twice and double
        // every finding on them (SC-006).
        ComponentTreeResult tree = DrawingTree();
        ComponentNode root = ComponentTreeDumper.DrawingRootNode(tree, null);
        object housing = new object();

        var walked = new List<string>();

        ComponentTreeDumper.AddDrawingForest(
            tree,
            _gaps,
            root,
            new[]
            {
                new DrawingReference(HousingPath, housing),
                new DrawingReference(HousingPath, housing),
            },
            (reference, parentKey) => walked.Add(reference.Path));

        Assert.Equal(new[] { HousingPath }, walked);
    }

    [Fact]
    public void AddDrawingForest_ModelThatIsNotLoaded_IsAGapNamingItAndNoSubtree()
    {
        // Nothing is opened, loaded or resolved to close the gap (FR-044): the model is named
        // so the engineer can open it and extract again, and every part- and assembly-scope
        // check for it is unresolved coverage in the meantime.
        ComponentTreeResult tree = DrawingTree();
        ComponentNode root = ComponentTreeDumper.DrawingRootNode(tree, null);
        var walked = new List<string>();

        ComponentTreeDumper.AddDrawingForest(
            tree,
            _gaps,
            root,
            new[]
            {
                new DrawingReference(HousingPath, null),
                new DrawingReference(RailPath, new object()),
            },
            (reference, parentKey) => walked.Add(reference.Path));

        Assert.Equal(new[] { RailPath }, walked);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("drawing_referenced_document", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Null(gap.EntityId);
        Assert.Contains(HousingPath, gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void AddDrawingForest_OfADrawingWithNoViewsAtAll_IsTheForestRootAndNoGap()
    {
        // A drawing that references nothing is a drawing whose own four checks still run
        // (quickstart Scenario 4). It is not a failed traversal and it is not a gap.
        ComponentTreeResult tree = DrawingTree();
        ComponentNode root = ComponentTreeDumper.DrawingRootNode(tree, null);
        var walked = new List<string>();

        ComponentTreeDumper.AddDrawingForest(
            tree, _gaps, root, new DrawingReference[0],
            (reference, parentKey) => walked.Add(reference.Path));

        Assert.Same(root, Assert.Single(tree.Nodes));
        Assert.Empty(walked);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void AddDrawingForest_HandsTheWalkTheDocumentItWasGivenAndNothingElse()
    {
        // The list comes from the DrawingTraversal seam, which reads IView.ReferencedDocument
        // and nothing else: the forest never asks SOLIDWORKS to find, open or resolve a
        // document, and never goes looking for the drawings of an open model.
        ComponentTreeResult tree = DrawingTree();
        ComponentNode root = ComponentTreeDumper.DrawingRootNode(tree, null);
        object housing = new object();
        var handles = new List<object?>();

        ComponentTreeDumper.AddDrawingForest(
            tree, _gaps, root, new[] { new DrawingReference(HousingPath, housing) },
            (reference, parentKey) => handles.Add(reference.Document));

        Assert.Same(housing, Assert.Single(handles));
        Assert.Empty(_observer.Members);
    }

    // ---- one referenced model's subtree (T063/T064, FR-025) ------------------------

    /// <summary>
    /// T063(a). A referenced ASSEMBLY is walked exactly as an assembly root is: its own node,
    /// then its component tree, so the document, manifest, mate, feature, equation and
    /// cut-list phases all run over it.
    /// </summary>
    [Fact]
    public void AddReferencedSubtree_OfAReferencedAssembly_RecordsItsNodeAndWalksItsTree()
    {
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel rail = reader.Add(RailPath, DocumentKind.Assembly);
        rail.ConfigurationName = "Assembled";
        rail.RootComponent = new object();

        ComponentTreeResult tree = DrawingTree();
        var walked = new List<(object Root, ComponentNode Node)>();

        ComponentNode? node = ComponentTreeDumper.AddReferencedSubtree(
            tree,
            _gaps,
            DrawingPath,
            new DrawingReference(RailPath, rail.Handle),
            reader,
            (root, walkedNode) => walked.Add((root, walkedNode)));

        Assert.NotNull(node);
        Assert.Same(node, Assert.Single(tree.Nodes));
        Assert.Equal(DocumentKind.Assembly, node!.DocumentKind);
        Assert.Equal("Assembled", node.ReferencedConfiguration);
        Assert.Equal(DrawingPath, node.ParentKey);

        (object Root, ComponentNode Node) call = Assert.Single(walked);
        Assert.Same(rail.RootComponent, call.Root);

        // The walk is handed the referenced model's own node, and that is what the subtree's
        // SubtreeScope is built from: a component of a referenced assembly has no persistent
        // reference in the DRAWING's extension, so scoping it to the drawing would cost it
        // its place in components[].
        Assert.Same(rail.Handle, call.Node.Handle);
        Assert.Equal(RailPath, call.Node.DocumentPath);
        Assert.Empty(_gaps.Gaps);
    }

    /// <summary>
    /// T063(a). A referenced PART is one node and no more - it has no component tree - and
    /// the node carries the model as its handle, which is what FeatureDumper, EquationDumper
    /// and CutListDumper read it through.
    /// </summary>
    [Fact]
    public void AddReferencedSubtree_OfAReferencedPart_IsOneNodeCarryingTheModelAndNoWalk()
    {
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel housing = reader.Add(HousingPath, DocumentKind.Part);

        ComponentTreeResult tree = DrawingTree();
        var walked = new List<object>();

        ComponentNode? node = Walk(tree, reader, housing, walked);

        Assert.NotNull(node);
        Assert.Same(node, Assert.Single(tree.Nodes));
        Assert.Equal(DocumentKind.Part, node!.DocumentKind);
        Assert.Same(housing.Handle, node.Handle);
        Assert.Empty(walked);
        Assert.Empty(_gaps.Gaps);
    }

    /// <summary>
    /// The node is an instance of nothing - the drawing does not instance the model - so, like
    /// a part opened alone, it is resolved and fixed, belongs to no pattern, and has no
    /// constrained status, which describes how an instance sits inside its parent.
    /// </summary>
    [Fact]
    public void AddReferencedSubtree_RecordsTheModelAsAnInstanceOfNothing()
    {
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel housing = reader.Add(HousingPath, DocumentKind.Part);
        housing.PersistRef = new ScopedPersistRef("SG91c2luZw==", "doc:hsg", HousingPath);
        housing.IsToolbox = true;

        ComponentNode? node = Walk(DrawingTree(), reader, housing, new List<object>());

        Assert.Equal(HousingPath, node!.DocumentPath);
        Assert.Equal(SuppressionState.Resolved, node.Suppression);
        Assert.True(node.IsFixed);
        Assert.True(node.IsToolbox);
        Assert.Null(node.PatternId);
        Assert.Null(node.IsPatternInstance);
        Assert.Null(node.ConstrainedStatusRaw);
        Assert.Equal("SG91c2luZw==", node.PersistRef);
        Assert.Equal(HousingPath, node.PersistRefScopePath);
    }

    /// <summary>
    /// The defect this keying exists to prevent. SOLIDWORKS names a drawing after the model
    /// it documents, so housing.SLDDRW over housing.SLDPRT is the ORDINARY case: keyed on the
    /// file's base name both nodes are "housing", <c>DumpScope.AddComponent</c> keeps the last
    /// write for a key, and the model's ParentKey then resolves to the model itself - a
    /// package shipping an instance that is its own parent, a forest root with no children,
    /// and two instances with one full_path.
    /// </summary>
    [Fact]
    public void AddReferencedSubtree_OfAModelNamedAfterItsDrawing_KeepsAKeyOfItsOwn()
    {
        ComponentTreeResult tree = NamesakeDrawingTree();
        ComponentNode root = ComponentTreeDumper.DrawingRootNode(tree, null);

        var reader = new FakeReferencedModelReader();
        FakeReferencedModel housing = reader.Add(HousingPath, DocumentKind.Part);

        ComponentNode? node = ComponentTreeDumper.AddReferencedSubtree(
            tree,
            _gaps,
            root.Key,
            new DrawingReference(HousingPath, housing.Handle),
            reader,
            (_, __) => throw new InvalidOperationException("a part has no tree to walk"));

        Assert.NotEqual(root.Key, node!.Key);
        Assert.Equal(root.Key, node.ParentKey);

        // The base name is still what a report reads out; only the key is the path.
        Assert.Equal("housing", node.Name);
        Assert.Equal("housing", root.Name);
    }

    /// <summary>
    /// The same collision between two referenced models: a vault that keeps one part number
    /// per project folder has two housing.SLDPRTs, both referenced by one drawing.
    /// <c>DrawingTraversal.ReferencedModels</c> keeps both, because they are two documents.
    /// </summary>
    [Fact]
    public void AddReferencedSubtree_OfTwoModelsNamedAlikeInDifferentFolders_KeepsTheirKeysApart()
    {
        const string FirstPath = @"C:\vault\project-a\housing.SLDPRT";
        const string SecondPath = @"C:\vault\project-b\housing.SLDPRT";

        var reader = new FakeReferencedModelReader();
        FakeReferencedModel first = reader.Add(FirstPath, DocumentKind.Part);
        FakeReferencedModel second = reader.Add(SecondPath, DocumentKind.Part);

        ComponentTreeResult tree = DrawingTree();
        var walked = new List<object>();

        ComponentNode? one = Walk(tree, reader, first, walked);
        ComponentNode? two = Walk(tree, reader, second, walked);

        Assert.NotEqual(one!.Key, two!.Key);
        Assert.Equal("housing", one.Name);
        Assert.Equal("housing", two.Name);
        Assert.Equal(DrawingPath, one.ParentKey);
        Assert.Equal(DrawingPath, two.ParentKey);
    }

    [Fact]
    public void AddReferencedSubtree_OfSomethingThatIsNotAModelDocument_IsAGapAndNoNode()
    {
        var reader = new FakeReferencedModelReader();
        ComponentTreeResult tree = DrawingTree();
        var walked = new List<object>();

        ComponentNode? node = ComponentTreeDumper.AddReferencedSubtree(
            tree, _gaps, DrawingPath, new DrawingReference(HousingPath, new object()), reader,
            (root, _) => walked.Add(root));

        Assert.Null(node);
        Assert.Empty(tree.Nodes);
        Assert.Empty(walked);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("drawing_referenced_document", gap.EntityKind);
        Assert.Contains(HousingPath, gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void AddReferencedSubtree_OfAModelThatReportsNoPath_IsAGapNamingTheViewAndNoNode()
    {
        // With no path there is no document id to record it under, so nothing later could
        // resolve it; the name the view gave is what the gap can still say.
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel housing = reader.Add(HousingPath, DocumentKind.Part);
        housing.Path = "   ";

        ComponentTreeResult tree = DrawingTree();
        var walked = new List<object>();

        ComponentNode? node = ComponentTreeDumper.AddReferencedSubtree(
            tree,
            _gaps,
            DrawingPath,
            new DrawingReference(HousingPath, housing.Handle),
            reader,
            (root, _) => walked.Add(root));

        Assert.Null(node);
        Assert.Empty(tree.Nodes);
        Assert.Empty(walked);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("drawing_referenced_document", gap.EntityKind);
        Assert.Contains(HousingPath, gap.Reason, StringComparison.Ordinal);
        Assert.Contains("bracket-assy", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void AddReferencedSubtree_OfAModelWhoseKindWouldNotRead_IsAGapAndNoNode()
    {
        // Unknown stays unknown: "part" would walk a tree that may be an assembly's, and
        // "assembly" would drop a part's whole feature tree without a word.
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel housing = reader.Add(HousingPath, DocumentKind.Part);
        housing.KindFailure = new InvalidOperationException("GetType failed");

        ComponentTreeResult tree = DrawingTree();
        var walked = new List<object>();

        ComponentNode? node = Walk(tree, reader, housing, walked);

        Assert.Null(node);
        Assert.Empty(tree.Nodes);
        Assert.Empty(walked);

        // The failed read's own row, then the refusal that names what it cost.
        Assert.Equal(2, _gaps.Gaps.Count);
        Assert.All(_gaps.Gaps, gap => Assert.Equal("component", gap.EntityKind));
        Assert.Contains(_gaps.Gaps, gap => gap.Reason.Contains(HousingPath));
    }

    [Fact]
    public void AddReferencedSubtree_OfAnAssemblyWithNoActiveConfiguration_IsTheNodeAndAGap()
    {
        // The node is still recorded - the document IS in the package - and the gap says its
        // parts were not graded, rather than the assembly reading as one with no components.
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel rail = reader.Add(RailPath, DocumentKind.Assembly);
        rail.Configuration = null;

        ComponentTreeResult tree = DrawingTree();
        var walked = new List<object>();

        ComponentNode? node = Walk(tree, reader, rail, walked);

        Assert.NotNull(node);
        Assert.Equal(string.Empty, node!.ReferencedConfiguration);
        Assert.Same(node, Assert.Single(tree.Nodes));
        Assert.Empty(walked);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component", gap.EntityKind);
        Assert.Contains(RailPath, gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void AddReferencedSubtree_OfAnAssemblyWithNoRootComponent_IsTheNodeAndAGap()
    {
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel rail = reader.Add(RailPath, DocumentKind.Assembly);
        rail.RootComponent = null;

        ComponentTreeResult tree = DrawingTree();
        var walked = new List<object>();

        ComponentNode? node = Walk(tree, reader, rail, walked);

        Assert.NotNull(node);
        Assert.Same(node, Assert.Single(tree.Nodes));
        Assert.Empty(walked);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component", gap.EntityKind);
        Assert.Contains(RailPath, gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void AddReferencedSubtree_WhoseIdentityReadsFail_RecordsTheNodeWithGapsForEach()
    {
        // A locator that could not be read is a coverage row, not an invented one: the node
        // still reaches the later phases, and PackageWriter turns the missing reference into
        // its own gap once cmp:NNNN exists.
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel housing = reader.Add(HousingPath, DocumentKind.Part);
        housing.PersistRefFailure = new InvalidOperationException("GetPersistReference3 failed");
        housing.ToolboxFailure = new InvalidOperationException("ToolboxPartType failed");

        ComponentNode? node = Walk(DrawingTree(), reader, housing, new List<object>());

        Assert.Null(node!.PersistRef);
        Assert.Equal(HousingPath, node.PersistRefScopePath);
        Assert.False(node.IsToolbox);

        Assert.Equal(2, _gaps.Gaps.Count);
        Assert.All(_gaps.Gaps, gap => Assert.Equal("component", gap.EntityKind));
        Assert.All(_gaps.Gaps, gap => Assert.Contains("housing", gap.Reason, StringComparison.Ordinal));
    }

    /// <summary>
    /// T063(b). Nothing is opened, loaded, resolved or activated: the decisions ask the gate
    /// nothing at all, and every interop expression they do reach lives behind
    /// <see cref="IReferencedModelReader"/>, whose SOLIDWORKS side gates each call under its
    /// own member name.
    /// </summary>
    [Fact]
    public void AddReferencedSubtree_MakesNoCallOfItsOwn()
    {
        var reader = new FakeReferencedModelReader();
        FakeReferencedModel rail = reader.Add(RailPath, DocumentKind.Assembly);
        rail.RootComponent = new object();

        Walk(DrawingTree(), reader, rail, new List<object>());

        Assert.Empty(_observer.Members);
        Assert.Empty(reader.Refused);
    }

    /// <summary>One referenced model, with the forest root's key as its parent.</summary>
    private ComponentNode? Walk(
        ComponentTreeResult tree,
        FakeReferencedModelReader reader,
        FakeReferencedModel model,
        List<object> walked) =>
        ComponentTreeDumper.AddReferencedSubtree(
            tree,
            _gaps,
            DrawingPath,
            new DrawingReference(model.Path ?? string.Empty, model.Handle),
            reader,
            (root, _) => walked.Add(root));

    private static ComponentTreeResult DrawingTree() => new ComponentTreeResult
    {
        RootDocumentPath = DrawingPath,
        RootDocumentKind = DocumentKind.Drawing,
        DesignName = "bracket-assy",
        ActiveConfiguration = "Default",
    };

    /// <summary>A drawing named after the model it documents - the ordinary convention.</summary>
    private static ComponentTreeResult NamesakeDrawingTree() => new ComponentTreeResult
    {
        RootDocumentPath = @"C:\vault\bracket-assy\housing.SLDDRW",
        RootDocumentKind = DocumentKind.Drawing,
        DesignName = "housing",
        ActiveConfiguration = "Default",
    };

    /// <summary>One model a drawing view references, with a switch for every read.</summary>
    private sealed class FakeReferencedModel
    {
        public object Handle { get; } = new object();

        public string? Path { get; set; }

        public DocumentKind Kind { get; set; } = DocumentKind.Part;

        public Exception? KindFailure { get; set; }

        public object? Configuration { get; set; } = new object();

        public string? ConfigurationName { get; set; } = "Default";

        public object? RootComponent { get; set; }

        public bool IsToolbox { get; set; }

        public Exception? ToolboxFailure { get; set; }

        public ScopedPersistRef? PersistRef { get; set; }

        public Exception? PersistRefFailure { get; set; }
    }

    /// <summary>
    /// A scripted set of referenced models. A handle it was never told about is not a model
    /// document, which is exactly what <c>IView.ReferencedDocument</c> handing back something
    /// else looks like.
    /// </summary>
    private sealed class FakeReferencedModelReader : IReferencedModelReader
    {
        private readonly Dictionary<object, FakeReferencedModel> _byHandle =
            new Dictionary<object, FakeReferencedModel>();

        private readonly Dictionary<object, FakeReferencedModel> _byConfiguration =
            new Dictionary<object, FakeReferencedModel>();

        /// <summary>Handles asked about that this reader knows nothing of.</summary>
        public List<object> Refused { get; } = new List<object>();

        public FakeReferencedModel Add(string path, DocumentKind kind)
        {
            var model = new FakeReferencedModel { Path = path, Kind = kind };
            _byHandle[model.Handle] = model;
            if (model.Configuration != null)
            {
                _byConfiguration[model.Configuration] = model;
            }

            return model;
        }

        public bool IsModel(object document)
        {
            if (_byHandle.ContainsKey(document))
            {
                return true;
            }

            Refused.Add(document);
            return false;
        }

        public string? Path(object model) => Model(model).Path;

        public DocumentKind Kind(object model)
        {
            FakeReferencedModel found = Model(model);
            return found.KindFailure != null ? throw found.KindFailure : found.Kind;
        }

        public object? Configuration(object model) => Model(model).Configuration;

        public string? ConfigurationName(object configuration) =>
            _byConfiguration[configuration].ConfigurationName;

        public object? RootComponent(object configuration) =>
            _byConfiguration[configuration].RootComponent;

        public bool IsToolbox(object model)
        {
            FakeReferencedModel found = Model(model);
            return found.ToolboxFailure != null ? throw found.ToolboxFailure : found.IsToolbox;
        }

        public ScopedPersistRef? PersistRef(object model)
        {
            FakeReferencedModel found = Model(model);
            return found.PersistRefFailure != null ? throw found.PersistRefFailure : found.PersistRef;
        }

        private FakeReferencedModel Model(object handle) => _byHandle[handle];
    }
}
