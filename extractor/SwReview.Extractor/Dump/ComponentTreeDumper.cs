using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T050. Walks the active configuration's component tree.
///
/// Gotchas this implementation exists to respect (research R12):
///   - <c>GetChildren</c> returns IMMEDIATE children only, so recursion is explicit.
///   - <c>GetID</c> collides across subassemblies, so instances are keyed by the full
///     <c>Name2</c> path and by persistent reference. GetID is never read.
///   - <c>GetModelDoc2</c> returns null for suppressed and lightweight components, so the
///     file path comes from <c>GetPathName</c>, which answers in every state.
///   - <c>Transform2</c> is already relative to the ROOT assembly, so child transforms are
///     used as they come; they are not composed with the parent's.
///   - <c>GetSuppression2</c> is preferred over <c>IsSuppressed</c>, which is configuration
///     dependent. State 5 (internal id mismatch) becomes "unloaded" plus a Gap.
///
/// Pattern membership is read from the assembly's component pattern features, because
/// SOLIDWORKS 2024 offers no "which pattern am I in" question on IComponent2.
/// </summary>
public sealed class ComponentTreeDumper : IComponentTreeSource
{
    /// <summary>
    /// Feature type names (<c>GetTypeName2</c>) of assembly component patterns.
    ///
    /// This is a membership test and nothing else, so an extra name is inert - no feature
    /// returns a name that does not exist - while a missing name fails silently. Names are
    /// therefore added on evidence and never removed on the strength of a doc page this
    /// machine cannot reach. The exact set, and the provenance of every name in it, is
    /// pinned by PatternFeatureTypesTests.
    /// </summary>
    private static readonly HashSet<string> PatternFeatureTypes = new HashSet<string>(StringComparer.Ordinal)
    {
        "LocalLPattern",
        "LocalCirPattern",
        "LocalSketchPattern",
        "LocalCurvePattern",
        "LocalChainPattern",
        "DerivedLPattern",
        "DerivedCirPattern",
        "ChainPatternFeat",
        "MirrorComponent",
        "MirrorCompFeat",

        // "TablePattern" is commented out rather than deleted. swFmTablePattern = 106 sits
        // in the PART pattern block of swFeatureNameID_e (CurvePattern 103, SketchPattern
        // 104, FillPattern 105, TablePattern 106, DimPattern 107), whereas the component
        // patterns are the Local* family 108-112 plus the Derived* pair and MirrorComponent
        // 116; SOLIDWORKS 2024 has no table-driven COMPONENT pattern. The module boundary
        // does not settle it on its own - moTablePattern_c is in sldasmu.dll, but so are
        // part classes like moLPattern_c - so this stays a claim the type-name census can
        // refute: if TablePattern ever appears unconsumed in an assembly's census, restore
        // the line. Left in the set it can only misfire, walking a part feature's
        // sub-features for components and raising a spurious "listed no component
        // instances" gap.
    };

    private readonly ISwSession _session;
    private readonly PersistRefService _refs;
    private readonly IDrawingReferenceSource? _drawings;

    /// <summary>
    /// <paramref name="drawings"/> is the seam the drawing-rooted forest takes its
    /// referenced-model list from (schema 1.4.0, FR-025). Null - a caller with no drawing
    /// reader wired - traverses a drawing root as a forest root and nothing under it, with a
    /// gap saying so, rather than pretending the drawing references nothing.
    /// </summary>
    public ComponentTreeDumper(
        ISwSession session, PersistRefService refs, IDrawingReferenceSource? drawings = null)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
        _drawings = drawings;
    }

    public ComponentTreeResult Traverse(GapCollector gaps, DumpOptions options)
    {
        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        SwGate gate = _session.Gate;
        IModelDoc2 document = _session.Document;
        string rootPath = gate.Call("GetPathName", () => document.GetPathName());

        // Read before the tree is built, because whether a missing root component means "a
        // part opened alone" or "an assembly that answered nothing" turns on it. A failed
        // read is a gap rather than a thrown dump: Traverse runs outside RunPhase, so an
        // escaping exception would cost the whole package.
        DocumentKind? rootKind = null;
        gaps.TryStep(
            "component",
            null,
            "read the document type of the open document",
            () => rootKind = SwSession.KindOf(document, gate));

        var tree = new ComponentTreeResult
        {
            RootDocumentPath = rootPath,
            DesignName = Path.GetFileNameWithoutExtension(rootPath),
            ActiveConfiguration = gate.Call("Configuration.Name", () => _session.Configuration.Name),
            RootDocumentKind = rootKind,
        };

        if (rootKind == null)
        {
            // An unread kind stays unread. Every node carries a DocumentKind, and the two
            // choices here are both defaults for engineering data: "part" walks a tree that
            // may be an assembly's, and "assembly" is worse, because FeatureDumper and
            // EquationDumper skip every node that is not a Part, so the document's whole
            // feature tree and equation list would be dropped without a word. An empty tree
            // and this gap say what happened; before T064 the failed read escaped Traverse
            // and cost the whole package, so this is the quieter of the two, not a silence.
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                "The type of the open document could not be read, so no component was "
                + "recorded and nothing was traversed; the document kind is not assumed.",
                null);
            return tree;
        }

        // A drawing root is a forest, not a tree: it has no component of its own, and what a
        // reviewer means by "grade this drawing" is the models its views reference (FR-025).
        if (rootKind == DocumentKind.Drawing)
        {
            TraverseDrawing(tree, gaps);
            return tree;
        }

        // GetRootComponent3(false) is used rather than GetRootComponent: it returns the
        // modern Component2 the rest of this code needs, and false means "do not resolve",
        // so lightweight components stay lightweight (resolving them changes the session).
        var root = gate.Call(
            "GetRootComponent3",
            () => _session.Configuration.GetRootComponent3(false)) as IComponent2;

        if (root == null)
        {
            // T064, RK-15. A part opened alone is expected to answer nothing here (PROBE-15
            // records what 2024 SP5 actually returns), and without a node for it the
            // component list is empty, FeatureDumper iterates nothing, and every part rule
            // comes back unresolved on a part that is fine. The document IS the root, so it
            // is recorded as one instance rather than the dump reporting a design with no
            // components. An unread document kind never reaches here - it was refused above
            // with its own gap - because "assume it was a part" is exactly the default
            // engineering data must not get.
            if (rootKind == DocumentKind.Part)
            {
                tree.Nodes.Add(PartRootNode(tree, document, gaps));
                return tree;
            }

            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                "The active configuration returned no root component; nothing could be traversed.",
                null);
            return tree;
        }

        var scope = new SubtreeScope(document, rootPath);
        Dictionary<string, string> patternByComponent =
            ReadPatternMembership(gaps, document, rootPath);

        // The root component of an assembly is the assembly itself and carries no
        // persistent reference of its own, so it is recorded from the document.
        tree.Nodes.Add(RootNode(tree, root, rootKind.Value));
        Visit(root, tree.Nodes[0].Key, tree, gaps, patternByComponent, depth: 0, scope: scope);

        return tree;
    }

    /// <summary>
    /// The root node of a traversed tree. The document kind is a parameter rather than a
    /// read of <see cref="ComponentTreeResult.RootDocumentKind"/>, because a node must carry
    /// a kind that was read: <c>Traverse</c> refuses the dump before it gets here when the
    /// kind is unknown, and the signature is what says so.
    /// </summary>
    private ComponentNode RootNode(
        ComponentTreeResult tree, IComponent2 root, DocumentKind rootKind)
    {
        SwGate gate = _session.Gate;
        string name = gate.Call("Name2", () => root.Name2);

        return new ComponentNode
        {
            Key = string.IsNullOrEmpty(name) ? tree.DesignName : name,
            ParentKey = null,
            Name = string.IsNullOrEmpty(name) ? tree.DesignName : name,
            DocumentPath = tree.RootDocumentPath,
            DocumentKind = rootKind,
            ReferencedConfiguration = tree.ActiveConfiguration,
            Transform = Ir.Transform.Identity(),
            Suppression = SuppressionState.Resolved,
            IsFixed = true,
            PatternId = null,
            IsToolbox = false,

            // The root IS the assembly; GetConstrainedStatus is about how an instance is
            // mated inside its parent, so there is nothing to read and null says so.
            ConstrainedStatusRaw = null,
            PersistRef = _refs.TryGet(_session.Document, root)?.Base64,
            PersistRefScopePath = tree.RootDocumentPath,
            Handle = root,
        };
    }

    /// <summary>
    /// The single root node for a part opened alone (T064, FR-023).
    ///
    /// <c>GetRootComponent3(false)</c> is expected to answer nothing for a part
    /// configuration - what 2024 SP5 actually returns is recorded by PROBE-15, not assumed -
    /// and an empty tree costs the dump every part feature: <see cref="FeatureDumper"/> walks
    /// <c>DumpScope.Components</c>, so no component means no feature rows and all 34 RMS
    /// rules unresolved on the one document type the family was written for (RK-15).
    ///
    /// The node IS the document. Nothing in it is guessed: a part opened alone is resolved,
    /// and it is fixed, because there is no parent for it to be under-constrained in. As on
    /// the assembly root, <c>GetConstrainedStatus</c> is not read - it describes how an
    /// instance is mated inside its parent, and this node has none.
    ///
    /// The persistent reference is the one thing that cannot be had for certain: there is no
    /// <c>IComponent2</c> to hand <c>GetPersistReference3</c>, so the document is offered as
    /// its own subject and a refusal becomes a gap (written by <see cref="PackageWriter"/>,
    /// where cmp:NNNN exists) rather than an invented locator. That costs the instance in
    /// <c>components[]</c> and not the feature rows, which are dumped from the scope before
    /// the instances are written.
    /// </summary>
    private ComponentNode PartRootNode(ComponentTreeResult tree, IModelDoc2 document, GapCollector gaps)
    {
        ScopedPersistRef? reference = gaps.TryStep(
            "component",
            null,
            $"read a persistent reference for the part root of '{tree.DesignName}'",
            () => _refs.TryGet(document, document));

        bool isToolbox = false;
        gaps.TryStep(
            "component",
            null,
            $"read Toolbox identity for the part root of '{tree.DesignName}'",
            () => isToolbox = ReadIsToolbox(document, _session.Gate));

        return new ComponentNode
        {
            Key = tree.DesignName,
            ParentKey = null,
            Name = tree.DesignName,
            DocumentPath = tree.RootDocumentPath,
            DocumentKind = DocumentKind.Part,
            ReferencedConfiguration = tree.ActiveConfiguration,
            Transform = Ir.Transform.Identity(),
            Suppression = SuppressionState.Resolved,
            IsFixed = true,
            PatternId = null,
            IsToolbox = isToolbox,
            ConstrainedStatusRaw = null,
            PersistRef = reference?.Base64,
            PersistRefScopePath = reference?.ScopeDocumentPath ?? tree.RootDocumentPath,

            // No IComponent2 exists, so the document itself is the handle; the feature and
            // equation readers take it as the document rather than asking a component for one.
            Handle = document,
        };
    }

    /// <summary>
    /// T064. The forest a drawing root is traversed as (FR-025, contracts/ir-additions.md
    /// section 7): the drawing itself as a synthesized forest root, and one subtree under it
    /// per model a view on any sheet references.
    ///
    /// The referenced-model list comes from <see cref="IDrawingReferenceSource"/>, the seam
    /// beside <see cref="DrawingTraversal"/>, and not from the drawing phase: the traversal
    /// runs before any phase, and the phases that matter here - document, manifest, mate,
    /// feature, equation and cut list - all read the tree this produces.
    ///
    /// <b>Nothing is opened, loaded, resolved or activated</b> to do it. A model that is not
    /// loaded is a <c>drawing_referenced_document</c> gap naming it and no subtree, so its
    /// checks come back unresolved rather than absent.
    /// </summary>
    private void TraverseDrawing(ComponentTreeResult tree, GapCollector gaps)
    {
        ScopedPersistRef? reference = gaps.TryStep(
            "component",
            null,
            $"read a persistent reference for the drawing '{tree.DesignName}'",
            () => _refs.TryGet(_session.Document, _session.Document));

        ComponentNode root = DrawingRootNode(tree, reference);

        if (_drawings == null)
        {
            // No drawing reader is wired in this build. The forest root is still recorded -
            // the drawing IS a document of this package - and the absence is stated, because
            // an empty forest and no word about it reads as a drawing that references nothing.
            tree.Nodes.Add(root);
            gaps.Add(
                GapKind.NotExtracted,
                "drawing_referenced_document",
                null,
                $"'{tree.RootDocumentPath}' was traversed with no drawing reader, so the "
                + "models its views reference were not identified and none of them was graded.",
                null);
            return;
        }

        IReadOnlyList<DrawingReference>? references = gaps.TryStep(
            "drawing_referenced_document",
            null,
            $"read the models the views of '{tree.DesignName}' reference",
            () => _drawings.ReferencedModels());

        AddDrawingForest(
            tree,
            gaps,
            root,
            references ?? new List<DrawingReference>(),
            (model, parentKey) => WalkReferencedModel(model, parentKey, tree, gaps));
    }

    /// <summary>
    /// The synthesized forest root of a drawing: the drawing document itself, with no parent,
    /// so every referenced model's subtree hangs somewhere (research R9).
    ///
    /// Python walks it through and never grades it as a component of itself - an instance
    /// whose <c>document_id</c> is the root's is not one - which is why it can be synthesized
    /// without inventing a component nobody modelled. Nothing about it is guessed: a drawing
    /// is resolved, it is fixed because there is no parent to be under-constrained in, and
    /// there is no <c>GetConstrainedStatus</c> to read, which describes how an instance sits
    /// inside its parent and this node has none.
    ///
    /// <b>The key is the drawing's path, not its file name</b>, and so is a referenced model's
    /// (<see cref="ReferencedModelNode"/>). SOLIDWORKS names a drawing after the model it
    /// documents, so <c>housing.SLDDRW</c> over <c>housing.SLDPRT</c> is the ordinary case and
    /// not the odd one: two nodes keyed "housing" would collide in
    /// <c>DumpScope.AddComponent</c>, whose last write wins, and the model's
    /// <c>ParentKey</c> would then resolve to the model itself - a package shipping an
    /// instance that is its own parent, a forest root with no children, and two instances
    /// with one <c>full_path</c>. A path is unique per document by construction, so no pair
    /// of synthesized nodes can collide however the files are named. Keys inside an assembly
    /// stay <c>Name2</c>, because a mate names its components by <c>Name2</c>.
    /// </summary>
    public static ComponentNode DrawingRootNode(
        ComponentTreeResult tree, ScopedPersistRef? reference)
    {
        if (tree == null)
        {
            throw new ArgumentNullException(nameof(tree));
        }

        return new ComponentNode
        {
            Key = tree.RootDocumentPath,
            ParentKey = null,
            Name = tree.DesignName,
            DocumentPath = tree.RootDocumentPath,
            DocumentKind = DocumentKind.Drawing,
            ReferencedConfiguration = tree.ActiveConfiguration,
            Transform = Ir.Transform.Identity(),
            Suppression = SuppressionState.Resolved,
            IsFixed = true,
            PatternId = null,
            IsToolbox = false,
            ConstrainedStatusRaw = null,
            PersistRef = reference?.Base64,
            PersistRefScopePath = reference?.ScopeDocumentPath ?? tree.RootDocumentPath,
        };
    }

    /// <summary>
    /// The forest root and one <paramref name="walkSubtree"/> call per referenced model, in
    /// sheet and view order, each model once however many views reference it - walking it
    /// twice would grade its parts twice and double every finding on them (SC-006).
    ///
    /// Static and free of interop, so the rules a package depends on - what is walked, what
    /// becomes a gap, what hangs under what - are tested on a machine with no seat. A model
    /// that is not loaded is named in a gap and is not walked: <b>nothing is opened or
    /// resolved to close that gap</b> (FR-044).
    /// </summary>
    public static void AddDrawingForest(
        ComponentTreeResult tree,
        GapCollector gaps,
        ComponentNode forestRoot,
        IReadOnlyList<DrawingReference> references,
        Action<DrawingReference, string> walkSubtree)
    {
        if (tree == null)
        {
            throw new ArgumentNullException(nameof(tree));
        }

        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        if (forestRoot == null)
        {
            throw new ArgumentNullException(nameof(forestRoot));
        }

        if (walkSubtree == null)
        {
            throw new ArgumentNullException(nameof(walkSubtree));
        }

        // First, so cmp:0001 is the drawing and a reader can follow the forest by id exactly
        // as they follow a tree under an assembly root.
        tree.Nodes.Add(forestRoot);

        foreach (DrawingReference model in DrawingTraversal.ReferencedModels(references))
        {
            if (model.Document == null)
            {
                gaps.Add(
                    GapKind.NotExtracted,
                    "drawing_referenced_document",
                    null,
                    $"'{model.Path}' is referenced by a view of '{tree.DesignName}' and is not "
                    + "loaded, so its component tree was not walked and its checks are "
                    + "unresolved. It was not opened to look.",
                    null);
                continue;
            }

            walkSubtree(model, forestRoot.Key);
        }
    }

    /// <summary>
    /// One referenced model's subtree, walked exactly as an assembly root is walked: its own
    /// node under the forest root, then - for an assembly - its component tree.
    ///
    /// The interop lives in <see cref="SwReferencedModelReader"/> and the decisions live in
    /// <see cref="AddReferencedSubtree"/>, so every rule a package depends on here is tested
    /// on a machine with no seat - the same split <see cref="IDrawingReader"/> is to
    /// <see cref="DrawingDumper"/>.
    /// </summary>
    private void WalkReferencedModel(
        DrawingReference reference, string parentKey, ComponentTreeResult tree, GapCollector gaps)
    {
        AddReferencedSubtree(
            tree,
            gaps,
            parentKey,
            reference,
            new SwReferencedModelReader(_session, _refs),
            (rootComponent, node) => WalkReferencedAssembly(rootComponent, node, tree, gaps));
    }

    /// <summary>
    /// The component tree of a referenced ASSEMBLY, from its own root component down.
    ///
    /// The scope is the referenced model, never the drawing (<see cref="SubtreeScope"/>): a
    /// component of a referenced assembly has no persistent reference in the DRAWING's
    /// extension, and asking for one there would return nothing and cost that component its
    /// place in <c>components[]</c>. <c>depth: 1</c> because the referenced model's own node
    /// is level 0 of this subtree, as the root assembly's is under an assembly root.
    /// </summary>
    private void WalkReferencedAssembly(
        object rootComponent, ComponentNode node, ComponentTreeResult tree, GapCollector gaps)
    {
        var model = (IModelDoc2)node.Handle!;
        var scope = new SubtreeScope(model, node.DocumentPath);
        Dictionary<string, string> patternByComponent =
            ReadPatternMembership(gaps, model, node.DocumentPath);

        Visit(
            (IComponent2)rootComponent,
            node.Key,
            tree,
            gaps,
            patternByComponent,
            depth: 1,
            scope: scope);
    }

    /// <summary>
    /// T064. What one entry of the drawing's referenced-model list becomes: the node, the
    /// refusals that produce a coverage row instead of one, and whether a component tree is
    /// walked under it. Returns the node, or null when nothing could be recorded.
    ///
    /// A referenced <b>part</b> is one node and no more, the same shape a part opened alone
    /// gets: it has no component tree, and without the node its features, equations and cut
    /// list would never be dumped, because every later phase walks
    /// <see cref="DumpScope.Components"/>. A referenced <b>assembly</b> is that node plus its
    /// tree, walked by <paramref name="walkSubtree"/>.
    ///
    /// <b>Nothing is opened, loaded, resolved or activated</b> (FR-044): every question is
    /// asked of the handle a view already held. A model whose kind, path or configuration
    /// will not answer is an unresolved coverage row naming it, never a guess and never a
    /// silent skip - "part" would walk a tree that may be an assembly's, and "assembly" would
    /// drop a part's whole feature tree without a word.
    ///
    /// Static and interop-free, like <see cref="AddDrawingForest"/> above it, so these rules
    /// are tested without a SOLIDWORKS seat.
    /// </summary>
    public static ComponentNode? AddReferencedSubtree(
        ComponentTreeResult tree,
        GapCollector gaps,
        string parentKey,
        DrawingReference reference,
        IReferencedModelReader reader,
        Action<object, ComponentNode> walkSubtree)
    {
        if (tree == null)
        {
            throw new ArgumentNullException(nameof(tree));
        }

        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        if (reference == null)
        {
            throw new ArgumentNullException(nameof(reference));
        }

        if (reader == null)
        {
            throw new ArgumentNullException(nameof(reader));
        }

        if (walkSubtree == null)
        {
            throw new ArgumentNullException(nameof(walkSubtree));
        }

        object? model = reference.Document;
        if (model == null || !reader.IsModel(model))
        {
            gaps.Add(
                GapKind.NotExtracted,
                "drawing_referenced_document",
                null,
                $"'{reference.Path}' came back as something other than a model document, so "
                + "its component tree was not walked.",
                null);
            return null;
        }

        string? path = reader.Path(model);
        if (string.IsNullOrWhiteSpace(path))
        {
            // The view named it, so the gap can too; but with no path there is no document id
            // to record it under and nothing later could resolve it.
            gaps.Add(
                GapKind.NotExtracted,
                "drawing_referenced_document",
                null,
                $"The model a view of '{tree.DesignName}' references reports no file path "
                + $"(the view named it '{reference.Path}'), so it could not be identified.",
                null);
            return null;
        }

        DocumentKind? kind = null;
        gaps.TryStep(
            "component",
            null,
            $"read the document type of '{path}'",
            () => kind = reader.Kind(model));

        if (kind == null)
        {
            // The same refusal the root gets: "part" would walk a tree that may be an
            // assembly's, and "assembly" would drop a part's whole feature tree in silence.
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                $"The type of '{path}' could not be read, so no subtree was recorded for it "
                + "and the document kind is not assumed.",
                null);
            return null;
        }

        object? configuration = reader.Configuration(model);
        string configurationName = configuration == null
            ? string.Empty
            : reader.ConfigurationName(configuration) ?? string.Empty;

        ComponentNode node = ReferencedModelNode(
            gaps, reader, model, path!, kind.Value, configurationName, parentKey);

        tree.Nodes.Add(node);

        if (kind != DocumentKind.Assembly)
        {
            return node;
        }

        if (configuration == null)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                $"'{path}' reports no active configuration, so its component tree was not "
                + "walked and the parts under it were not graded.",
                null);
            return node;
        }

        object? rootComponent = reader.RootComponent(configuration);
        if (rootComponent == null)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                $"'{path}' returned no root component, so nothing under it was traversed.",
                null);
            return node;
        }

        walkSubtree(rootComponent, node);
        return node;
    }

    /// <summary>
    /// The node for a model a drawing view references. It is an instance of nothing - the
    /// drawing does not instance it - so, like a part opened alone, it is resolved and fixed,
    /// carries no constrained status, and takes its persistent reference from its own
    /// document rather than from an <c>IComponent2</c> that does not exist.
    ///
    /// <b>The key is the document's path.</b> A file base name is not unique across a forest:
    /// SOLIDWORKS names a drawing after the model it documents, so <c>housing.SLDDRW</c> and
    /// its <c>housing.SLDPRT</c> would share the key "housing", and two models named alike in
    /// different vault folders would share theirs. <c>DumpScope.AddComponent</c> keeps the
    /// last write for a key, so a collision makes this node's <c>ParentKey</c> resolve to
    /// this node - a package shipping an instance that is its own parent and a forest root
    /// with no children. The path cannot collide, and <see cref="ComponentNode.Name"/> keeps
    /// the base name a report reads out. Keys INSIDE an assembly stay <c>Name2</c>: a mate
    /// names its components by <c>Name2</c>, so making those unique would break the one thing
    /// they are for.
    /// </summary>
    public static ComponentNode ReferencedModelNode(
        GapCollector gaps,
        IReferencedModelReader reader,
        object model,
        string path,
        DocumentKind kind,
        string configuration,
        string parentKey)
    {
        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        if (reader == null)
        {
            throw new ArgumentNullException(nameof(reader));
        }

        string name = Path.GetFileNameWithoutExtension(path);

        ScopedPersistRef? reference = gaps.TryStep(
            "component",
            null,
            $"read a persistent reference for the referenced model '{name}'",
            () => reader.PersistRef(model));

        bool isToolbox = false;
        gaps.TryStep(
            "component",
            null,
            $"read Toolbox identity for the referenced model '{name}'",
            () => isToolbox = reader.IsToolbox(model));

        return new ComponentNode
        {
            Key = path,
            ParentKey = parentKey,
            Name = name,
            DocumentPath = path,
            DocumentKind = kind,
            ReferencedConfiguration = configuration,
            Transform = Ir.Transform.Identity(),
            Suppression = SuppressionState.Resolved,
            IsFixed = true,
            PatternId = null,
            IsToolbox = isToolbox,
            ConstrainedStatusRaw = null,
            PersistRef = reference?.Base64,
            PersistRefScopePath = reference?.ScopeDocumentPath ?? path,
            Handle = model,
        };
    }

    /// <summary>
    /// The SOLIDWORKS side of <see cref="IReferencedModelReader"/>: interop expressions and
    /// nothing else, each one gated under its own member name.
    /// </summary>
    private sealed class SwReferencedModelReader : IReferencedModelReader
    {
        private readonly ISwSession _session;
        private readonly PersistRefService _refs;

        public SwReferencedModelReader(ISwSession session, PersistRefService refs)
        {
            _session = session;
            _refs = refs;
        }

        private SwGate Gate => _session.Gate;

        /// <summary>A type test, not a call: <c>IView.ReferencedDocument</c> is typed object.</summary>
        public bool IsModel(object document) => document is IModelDoc2;

        public string? Path(object model) =>
            Gate.Call("GetPathName", () => ((IModelDoc2)model).GetPathName());

        public DocumentKind Kind(object model) => SwSession.KindOf((IModelDoc2)model, Gate);

        public object? Configuration(object model) => Gate.Call(
            "ConfigurationManager.ActiveConfiguration",
            () => ((IModelDoc2)model).ConfigurationManager?.ActiveConfiguration) as IConfiguration;

        public string? ConfigurationName(object configuration) =>
            Gate.Call("Configuration.Name", () => ((IConfiguration)configuration).Name);

        /// <summary>
        /// <c>false</c> is "do not resolve": a lightweight component stays lightweight,
        /// because resolving it would change the session (FR-044).
        /// </summary>
        public object? RootComponent(object configuration) => Gate.Call(
            "GetRootComponent3",
            () => ((IConfiguration)configuration).GetRootComponent3(false)) as IComponent2;

        public bool IsToolbox(object model) => ReadIsToolbox((IModelDoc2)model, Gate);

        public ScopedPersistRef? PersistRef(object model) =>
            _refs.TryGet((IModelDoc2)model, model);
    }

    /// <summary>
    /// The document one subtree's persistent references are scoped to, and its path.
    ///
    /// Under an assembly root that is the root assembly for every node. Under a drawing root
    /// there is one per referenced model: a component of a referenced assembly has no
    /// reference in the DRAWING's extension, and asking for one there would return nothing
    /// and cost that component its place in <c>components[]</c>.
    /// </summary>
    private sealed class SubtreeScope
    {
        public SubtreeScope(IModelDoc2 document, string path)
        {
            Document = document;
            Path = path;
        }

        public IModelDoc2 Document { get; }

        public string Path { get; }
    }

    /// <summary>Depth-first, immediate children at each level (GetChildren does not recurse).</summary>
    private void Visit(
        IComponent2 parent,
        string parentKey,
        ComponentTreeResult tree,
        GapCollector gaps,
        IReadOnlyDictionary<string, string> patternByComponent,
        int depth,
        SubtreeScope scope)
    {
        // A cyclic reference would be a corrupt assembly, but the traversal must not hang
        // on one; 64 levels is far deeper than any real product structure.
        if (depth > 64)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                $"Traversal stopped below '{parentKey}': the component tree is deeper than 64 levels.",
                null);
            return;
        }

        var children = _session.Gate.Call("GetChildren", () => parent.GetChildren()) as object[];
        if (children == null)
        {
            return;
        }

        foreach (object child in children)
        {
            if (!(child is IComponent2 component))
            {
                continue;
            }

            ComponentNode? node = null;
            gaps.TryStep("component", null, $"read a child of '{parentKey}'", () =>
            {
                node = ReadNode(component, parentKey, gaps, patternByComponent, scope);
            });

            if (node == null)
            {
                continue;
            }

            tree.Nodes.Add(node);
            Visit(component, node.Key, tree, gaps, patternByComponent, depth + 1, scope);
        }
    }

    private ComponentNode ReadNode(
        IComponent2 component,
        string parentKey,
        GapCollector gaps,
        IReadOnlyDictionary<string, string> patternByComponent,
        SubtreeScope scope)
    {
        SwGate gate = _session.Gate;

        string key = gate.Call("Name2", () => component.Name2) ?? string.Empty;
        string path = gate.Call("GetPathName", () => component.GetPathName()) ?? string.Empty;
        SuppressionState suppression = ReadSuppression(component, key, gaps);

        var node = new ComponentNode
        {
            Key = key,
            ParentKey = parentKey,
            Name = LeafName(key),
            DocumentPath = path,
            DocumentKind = path.EndsWith(".sldasm", StringComparison.OrdinalIgnoreCase)
                ? DocumentKind.Assembly
                : DocumentKind.Part,
            ReferencedConfiguration =
                gate.Call("ReferencedConfiguration", () => component.ReferencedConfiguration) ?? string.Empty,
            Suppression = suppression,
            IsFixed = gate.Call("IsFixed", () => component.IsFixed()),
            PatternId = patternByComponent.TryGetValue(key, out string pattern) ? pattern : null,
            IsToolbox = ReadIsToolbox(component, gaps, key),
            PersistRefScopePath = scope.Path,
            Handle = component,
        };

        ReadConstrainedStatus(component, node);

        // The four schema 1.4.0 reads (contracts/ir-additions.md section 1). They sit inside
        // Traverse, where no cmp:NNNN exists yet, so each failure is a TryStep gap that names
        // the component in its reason - the shape every other traversal gap has.
        node.HasAppearanceOverride = ReadHasAppearanceOverride(
            key, gaps, gate, () => component.HasMaterialPropertyValues());

        node.TransparencyRaw = ReadTransparency(
            node.HasAppearanceOverride,
            key,
            gaps,
            gate,
            () => component.GetMaterialPropertyValues2(
                (int)swInConfigurationOpts_e.swThisConfiguration, null));

        node.VisibilityRaw = ReadVisibility(key, gaps, gate, () => component.Visible);
        node.IsPatternInstance = ReadIsPatternInstance(
            key, gaps, gate, () => component.IsPatternInstance());

        double[][]? transform = ReadTransform(component, key, gaps);
        if (transform != null)
        {
            node.Transform = transform;
        }

        // Component references are scoped to the ASSEMBLY's extension, not the part's - and
        // for a drawing root that assembly is the referenced model whose tree this is, not
        // the drawing the dump is attached to.
        ScopedPersistRef? reference = _refs.TryGet(scope.Document, component);
        if (reference == null)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                $"SOLIDWORKS gave no persistent reference for '{key}'.",
                null);
        }
        else
        {
            node.PersistRef = reference.Base64;
            node.PersistRefScopePath = reference.ScopeDocumentPath;
        }

        return node;
    }

    /// <summary>
    /// <c>HasMaterialPropertyValues()</c>: whether this instance overrides the appearance of
    /// the document it references. It is read <b>before</b> the transparency slot and decides
    /// whether that slot is worth asking for at all; it replaces the macro's <c>-1</c>
    /// sentinel, which conflated "no override" with a real value.
    ///
    /// The interop expression stays at the call site and the policy lives here, because the
    /// traversal holds a live <c>IComponent2</c> that no machine without a seat can produce -
    /// the same split <see cref="FeatureDumper"/> makes with <see cref="IFeatureReader"/>,
    /// one delegate wide instead of one interface wide.
    /// </summary>
    public static bool? ReadHasAppearanceOverride(
        string key, GapCollector gaps, SwGate gate, Func<bool> read) =>
        Read("component_transparency", "HasMaterialPropertyValues", key, gaps, gate, read);

    /// <summary>
    /// Slot 7 of <c>GetMaterialPropertyValues2(1, null)</c>, verbatim. Which number means
    /// transparent, and whether slot 7 is the slot on this build, is PROBE-2 and is decided in
    /// Python; the extractor records what it was given (plan Structure Decision 1).
    ///
    /// <paramref name="hasOverride"/> false means there is nothing to read, so the null is
    /// silent: a coverage row on every component of every assembly would bury the components
    /// that really could not be read. Null means the override read itself failed and has
    /// already written the gap, so this one adds no second row for the same failure.
    /// </summary>
    public static double? ReadTransparency(
        bool? hasOverride, string key, GapCollector gaps, SwGate gate, Func<object?> read)
    {
        if (hasOverride != true)
        {
            return null;
        }

        object? values = null;
        bool answered = gaps.TryStep(
            "component_transparency",
            null,
            $"read GetMaterialPropertyValues2 for '{key}'",
            () => { values = gate.Call("GetMaterialPropertyValues2", read); });

        if (!answered)
        {
            return null;
        }

        double? transparency = Slot(values, 7);
        if (transparency == null)
        {
            // An answer nobody can read slot 7 out of is unknown, never a zero: a zero would
            // be a number the rule could act on.
            gaps.Add(
                GapKind.NotExtracted,
                "component_transparency",
                null,
                $"GetMaterialPropertyValues2 answered for '{key}' with no slot 7, so its "
                + "transparency is unknown.",
                null);
        }

        return transparency;
    }

    /// <summary>
    /// <c>Visible</c> verbatim, in <c>swComponentVisibilityState_e</c> (hidden 0, visible 1,
    /// unknown -1). Python names the number. <c>IsHidden(bool)</c> is deliberately not called:
    /// with <c>ConsiderSuppressed</c> it is the macro's difference-c bug, and without it the
    /// answer is this one with a state fewer (research R3.4).
    /// </summary>
    public static int? ReadVisibility(string key, GapCollector gaps, SwGate gate, Func<int> read) =>
        Read("component_visibility", "Visible", key, gaps, gate, read);

    /// <summary>
    /// <c>IsPatternInstance()</c>. <see cref="ComponentNode.PatternId"/> keeps the pattern's
    /// name for the reason text and cannot replace this: a null PatternId conflates "not in a
    /// pattern" with "the pattern map was never built".
    /// </summary>
    public static bool? ReadIsPatternInstance(
        string key, GapCollector gaps, SwGate gate, Func<bool> read) =>
        Read("component_pattern", "IsPatternInstance", key, gaps, gate, read);

    /// <summary>One gated read of one component, null plus a gap when it threw.</summary>
    private static T? Read<T>(
        string entityKind, string member, string key, GapCollector gaps, SwGate gate, Func<T> read)
        where T : struct
    {
        T? value = null;
        gaps.TryStep(
            entityKind,
            null,
            $"read {member} for '{key}'",
            () => { value = gate.Call(member, read); });

        return value;
    }

    /// <summary>
    /// One slot of the appearance array, which interop hands back as a <c>double[]</c> or as
    /// a VARIANT array of boxed doubles depending on the build. Null when the answer carries
    /// no such slot.
    /// </summary>
    private static double? Slot(object? values, int index)
    {
        if (values is double[] doubles)
        {
            return doubles.Length > index ? doubles[index] : (double?)null;
        }

        if (values is object[] boxed && boxed.Length > index && boxed[index] is double boxedValue)
        {
            return boxedValue;
        }

        return null;
    }

    private double[][]? ReadTransform(IComponent2 component, string key, GapCollector gaps)
    {
        object? arrayData = gaps.TryStep<object>("component", null, $"read Transform2 for '{key}'", () =>
        {
            var transform = _session.Gate.Call("Transform2", () => component.Transform2);
            return transform?.ArrayData;
        });

        if (arrayData == null)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                $"'{key}' has no Transform2; its world position is unknown.",
                null);
            return null;
        }

        return SwTransform.FromComValue(arrayData);
    }

    /// <summary>
    /// <c>GetSuppression2</c> mapped per research R12. State 5 means SOLIDWORKS could not
    /// match the component's internal id, which is a real loss of information, so it is
    /// recorded as a Gap as well as "unloaded".
    /// </summary>
    private SuppressionState ReadSuppression(IComponent2 component, string key, GapCollector gaps)
    {
        int state = _session.Gate.Call("GetSuppression2", () => component.GetSuppression2());

        switch ((swComponentSuppressionState_e)state)
        {
            case swComponentSuppressionState_e.swComponentSuppressed:
                return SuppressionState.Suppressed;

            case swComponentSuppressionState_e.swComponentLightweight:
            case swComponentSuppressionState_e.swComponentFullyLightweight:
                return SuppressionState.Lightweight;

            case swComponentSuppressionState_e.swComponentFullyResolved:
            case swComponentSuppressionState_e.swComponentResolved:
                return SuppressionState.Resolved;

            case swComponentSuppressionState_e.swComponentInternalIdMismatch:
                gaps.Add(
                    GapKind.NotExtracted,
                    "component",
                    null,
                    $"'{key}' reports an internal id mismatch (GetSuppression2 = 5); "
                    + "its geometry was not loaded and every check that needs it is unresolved.",
                    null);
                return SuppressionState.Unloaded;

            default:
                gaps.Add(
                    GapKind.NotExtracted,
                    "component",
                    null,
                    $"'{key}' returned an unrecognized suppression state {state}.",
                    null);
                return SuppressionState.Unloaded;
        }
    }

    /// <summary>
    /// <c>ToolboxPartType</c> is 0 not Toolbox, 1 standard, 2 copied. It lives on the
    /// component's own model document, which is null for a suppressed or lightweight
    /// component - then the answer is unknown, recorded as false plus a Gap.
    /// </summary>
    private bool ReadIsToolbox(IComponent2 component, GapCollector gaps, string key)
    {
        var model = _session.Gate.Call("GetModelDoc2", () => component.GetModelDoc2()) as IModelDoc2;
        if (model == null)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "component",
                null,
                $"'{key}' has no loaded model document, so Toolbox identity could not be read.",
                null);
            return false;
        }

        return ReadIsToolbox(model, _session.Gate);
    }

    /// <summary>
    /// The same read, from a document that is already in hand. Separate so the component
    /// path, the part-root path and the drawing's referenced models ask SOLIDWORKS the same
    /// question under the same gated member name rather than each spelling it out.
    /// </summary>
    private static bool ReadIsToolbox(IModelDoc2 model, SwGate gate) =>
        gate.Call("ToolboxPartType", () => model.Extension.ToolboxPartType) != 0;

    /// <summary>
    /// <c>GetConstrainedStatus</c> verbatim (swConstrainedStatus_e). The extractor does not
    /// name the number - Python maps it through the same table sketches use - and a failed
    /// read is null plus a Gap, never a guessed status: the first-component rule reports
    /// unresolved rather than treating "not read" as "not constrained".
    ///
    /// The Gap is not written here. Every <c>component_constrained_status</c> gap names one
    /// <c>entity_id</c> (data-model section 1) and cmp:NNNN does not exist during traversal,
    /// so the failure rides on the node and <c>PackageWriter</c> writes the gap once the id
    /// is allocated. The catch policy is still <see cref="GapCollector.TryStep"/>'s - a
    /// throwaway collector holds the description rather than a second hand-rolled try/catch
    /// that would have to repeat which exception types must never be swallowed.
    /// </summary>
    private void ReadConstrainedStatus(IComponent2 component, ComponentNode node)
    {
        var deferred = new GapCollector();
        int? status = null;

        deferred.TryStep(
            "component_constrained_status",
            null,
            $"read GetConstrainedStatus for '{node.Key}'",
            () => status = _session.Gate.Call("GetConstrainedStatus", () => component.GetConstrainedStatus()));

        node.ConstrainedStatusRaw = status;
        node.ConstrainedStatusError = deferred.Count == 0 ? null : deferred.Gaps[0].Error;
    }

    /// <summary>"sub-2/bracket-3" to "bracket-3".</summary>
    private static string LeafName(string fullPath)
    {
        int slash = fullPath.LastIndexOf('/');
        return slash < 0 ? fullPath : fullPath.Substring(slash + 1);
    }

    /// <summary>
    /// Full instance path to the name of the pattern feature that created it. The pattern
    /// feature's tree children ARE its instances, so the feature tree is walked once and
    /// the answer cached; there is no per-component question to ask in 2024.
    /// </summary>
    private Dictionary<string, string> ReadPatternMembership(
        GapCollector gaps, IModelDoc2 document, string rootDocumentPath)
    {
        var byComponent = new Dictionary<string, string>(StringComparer.Ordinal);
        var sightings = new List<TypeNameSighting>();
        SwGate gate = _session.Gate;

        var feature = gate.Call("FirstFeature", () => document.FirstFeature()) as IFeature;
        while (feature != null)
        {
            IFeature current = feature;
            gaps.TryStep("component_pattern", null, "read component pattern membership", () =>
            {
                string typeName = gate.Call("GetTypeName2", () => current.GetTypeName2()) ?? string.Empty;
                bool consumed = PatternFeatureTypes.Contains(typeName);
                sightings.Add(new TypeNameSighting(typeName, consumed));

                if (consumed)
                {
                    RecordPatternInstances(current, byComponent, gaps);
                }
            });

            feature = gate.Call("GetNextFeature", () => current.GetNextFeature()) as IFeature;
        }

        // The ten pattern names above are the only ones this walk claims; every other
        // type name in the root assembly's tree is censused as unread, and the mate walk
        // over the same tree marks MateGroup read.
        //
        // A never-saved document reports an empty path and so has no key to census under.
        // The census is right to refuse a blank key, and this is the one call site that
        // runs before PackageWriter.Build has proved the root path non-blank, so the check
        // belongs here: without it an unsaved assembly dies on an internal parameter-name
        // error instead of Build's "save it first" sentence a few statements later. There
        // is no test over the real dumper - ISwSession hands out raw IModelDoc2 and no
        // fake of it exists - so the shape is pinned through PackageWriterTests' fake
        // traversal, which censuses the same way.
        if (!string.IsNullOrWhiteSpace(rootDocumentPath))
        {
            gaps.TypeNames.AddPass(rootDocumentPath, sightings);
        }

        return byComponent;
    }

    private void RecordPatternInstances(
        IFeature pattern, Dictionary<string, string> byComponent, GapCollector gaps)
    {
        SwGate gate = _session.Gate;
        string patternName = gate.Call("Feature.Name", () => pattern.Name) ?? string.Empty;

        var child = gate.Call("GetFirstSubFeature", () => pattern.GetFirstSubFeature()) as IFeature;
        int found = 0;

        while (child != null)
        {
            IFeature current = child;
            var instance = gate.Call("GetSpecificFeature2", () => current.GetSpecificFeature2()) as IComponent2;
            if (instance != null)
            {
                string key = gate.Call("Name2", () => instance.Name2) ?? string.Empty;
                if (key.Length > 0)
                {
                    byComponent[key] = patternName;
                    found++;
                }
            }

            child = gate.Call("GetNextSubFeature", () => current.GetNextSubFeature()) as IFeature;
        }

        if (found == 0)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "component_pattern",
                null,
                $"Pattern feature '{patternName}' listed no component instances, "
                + "so its members are not grouped in the report.",
                null);
        }
    }
}


/// <summary>
/// What <see cref="ComponentTreeDumper.AddReferencedSubtree"/> needs SOLIDWORKS to answer
/// about one model a drawing view references, so that every decision it makes - what is
/// refused, what becomes a gap, what hangs under what, and which document a subtree's
/// persistent references are scoped to - is tested on a machine with no seat. The same seam
/// <see cref="IDrawingReader"/> is to <see cref="DrawingDumper"/>, and
/// <c>ComponentTreeDumper.SwReferencedModelReader</c> is the SOLIDWORKS side.
///
/// Everything is typed <c>object</c>, because the handle comes from
/// <see cref="DrawingReference.Document"/> - which <c>IView.ReferencedDocument</c> fills in
/// and which this contract must not name an interop type for.
///
/// <b>Nothing here opens, loads, resolves or activates anything</b> (FR-044): every member
/// is a question asked of a handle a view already held.
/// </summary>
public interface IReferencedModelReader
{
    /// <summary>Whether the handle is a model document at all, before anything is asked of it.</summary>
    bool IsModel(object document);

    /// <summary><c>IModelDoc2.GetPathName()</c>, verbatim.</summary>
    string? Path(object model);

    /// <summary>
    /// The document's kind. It throws rather than answering null when it cannot be read: the
    /// caller records that as an unresolved coverage row, because a defaulted kind would walk
    /// an assembly's tree as a part's or drop a part's feature tree in silence.
    /// </summary>
    DocumentKind Kind(object model);

    /// <summary>
    /// <c>IModelDoc2.ConfigurationManager.ActiveConfiguration</c>, or null when the document
    /// reports none. The ACTIVE one: no configuration is switched, because switching rebuilds.
    /// </summary>
    object? Configuration(object model);

    /// <summary><c>IConfiguration.Name</c>.</summary>
    string? ConfigurationName(object configuration);

    /// <summary>
    /// <c>IConfiguration.GetRootComponent3(false)</c> - "do not resolve", so a lightweight
    /// component stays lightweight. Null for a document that has no component tree.
    /// </summary>
    object? RootComponent(object configuration);

    /// <summary><c>IModelDocExtension.ToolboxPartType</c> is not 0.</summary>
    bool IsToolbox(object model);

    /// <summary>
    /// The document's own persistent reference, scoped to itself: a referenced model is an
    /// instance of nothing, so there is no <c>IComponent2</c> to ask.
    /// </summary>
    ScopedPersistRef? PersistRef(object model);
}
