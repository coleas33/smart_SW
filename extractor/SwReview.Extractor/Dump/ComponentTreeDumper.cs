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

    public ComponentTreeDumper(ISwSession session, PersistRefService refs)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
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

        Dictionary<string, string> patternByComponent = ReadPatternMembership(gaps, rootPath);

        // The root component of an assembly is the assembly itself and carries no
        // persistent reference of its own, so it is recorded from the document.
        tree.Nodes.Add(RootNode(tree, root, rootKind.Value));
        Visit(root, tree.Nodes[0].Key, tree, gaps, patternByComponent, depth: 0);

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
            () => isToolbox = ReadIsToolbox(document));

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

    /// <summary>Depth-first, immediate children at each level (GetChildren does not recurse).</summary>
    private void Visit(
        IComponent2 parent,
        string parentKey,
        ComponentTreeResult tree,
        GapCollector gaps,
        IReadOnlyDictionary<string, string> patternByComponent,
        int depth)
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
                node = ReadNode(component, parentKey, tree, gaps, patternByComponent);
            });

            if (node == null)
            {
                continue;
            }

            tree.Nodes.Add(node);
            Visit(component, node.Key, tree, gaps, patternByComponent, depth + 1);
        }
    }

    private ComponentNode ReadNode(
        IComponent2 component,
        string parentKey,
        ComponentTreeResult tree,
        GapCollector gaps,
        IReadOnlyDictionary<string, string> patternByComponent)
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
            PersistRefScopePath = tree.RootDocumentPath,
            Handle = component,
        };

        ReadConstrainedStatus(component, node);

        double[][]? transform = ReadTransform(component, key, gaps);
        if (transform != null)
        {
            node.Transform = transform;
        }

        // Component references are scoped to the ASSEMBLY's extension, not the part's.
        ScopedPersistRef? reference = _refs.TryGet(_session.Document, component);
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

        return ReadIsToolbox(model);
    }

    /// <summary>
    /// The same read, from a document that is already in hand. Separate so the component
    /// path and the part-root path ask SOLIDWORKS the same question under the same gated
    /// member name rather than each spelling it out.
    /// </summary>
    private bool ReadIsToolbox(IModelDoc2 model) =>
        _session.Gate.Call("ToolboxPartType", () => model.Extension.ToolboxPartType) != 0;

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
    private Dictionary<string, string> ReadPatternMembership(GapCollector gaps, string rootDocumentPath)
    {
        var byComponent = new Dictionary<string, string>(StringComparer.Ordinal);
        var sightings = new List<TypeNameSighting>();
        SwGate gate = _session.Gate;

        var feature = gate.Call("FirstFeature", () => _session.Document.FirstFeature()) as IFeature;
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
