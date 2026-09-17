using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// What <c>IFeature.GetDefinition</c> handed back, classified by the interface it implements
/// and by nothing else. The dumper needs the three cases apart because a variable-radius
/// fillet has no single radius to report and must become a gap, while an extrusion's
/// definition is simply not a fillet and is no gap at all.
/// </summary>
public enum FilletDefinitionKind
{
    /// <summary>Some other feature's definition object; there is no radius to look for.</summary>
    NotAFillet,

    /// <summary><c>ISimpleFilletFeatureData2</c>: <c>DefaultRadius</c> is readable.</summary>
    Simple,

    /// <summary><c>IVariableFilletFeatureData2</c>: no single radius exists (research R5).</summary>
    Variable,
}

/// <summary>
/// The live reads <see cref="FeatureDumper"/> needs, with no interop type in the signature
/// (<see cref="SwFeatureReader"/> is the SOLIDWORKS one). The seam exists so the dumper's
/// policy - one tree per document, what becomes a gap, how ids are mapped - is unit tested
/// on a machine with no seat, exactly as <c>IInterferenceSource</c> is.
///
/// Every member here that maps to ONE interop call is gated by the dumper, which names it,
/// so the read-only guard and the SC-004 audit see the production member names even under a
/// fake. <see cref="ActiveConfiguration"/>, <see cref="Walk"/> and <see cref="PersistRef"/>
/// span several calls each and gate them inside the implementation.
/// </summary>
public interface IFeatureReader
{
    /// <summary><c>IComponent2.GetModelDoc2</c>; null when the document is not loaded.</summary>
    object? Document(ScopedComponent component);

    /// <summary>
    /// The name of the configuration the document is loaded in. Gates
    /// <c>ConfigurationManager.ActiveConfiguration</c> and <c>Configuration.Name</c> itself.
    /// </summary>
    string ActiveConfiguration(object document);

    /// <summary>
    /// The document's feature tree, sub-features nested where SOLIDWORKS nests them. Gates
    /// <c>FirstFeature</c>, <c>GetNextFeature</c>, <c>GetFirstSubFeature</c> and
    /// <c>GetNextSubFeature</c> itself, because one walk is four members.
    /// </summary>
    IReadOnlyList<FeatureTreeNode> Walk(object document);

    /// <summary><c>IFeature.Description</c> verbatim; may be null.</summary>
    string? Description(object feature);

    /// <summary><c>IFeature.GetErrorCode2</c>.</summary>
    int ErrorCode(object feature);

    /// <summary><c>IFeature.IsSuppressed2</c> in <paramref name="configuration"/> only.</summary>
    bool Suppressed(object feature, string configuration);

    /// <summary><c>IFeature.GetChildren</c>: the features that depend on this one.</summary>
    IReadOnlyList<object> Children(object feature);

    /// <summary><c>IFeature.GetParents</c>: the features this one depends on.</summary>
    IReadOnlyList<object> Parents(object feature);

    /// <summary>
    /// <c>IFeature.GetSpecificFeature2</c> when it is an <c>ISketch</c>, else null. The
    /// dumper wants no other specific feature, so the cast lives here.
    /// </summary>
    object? Sketch(object feature);

    /// <summary><c>ISketch.GetConstrainedStatus</c> verbatim; never mapped here (research R7).</summary>
    int SketchConstrainedStatus(object sketch);

    /// <summary>
    /// <c>ISketch.GetSketchTextSegments()</c> as it came: an array, or nothing when the sketch
    /// carries no text (schema 1.4.0). The count is taken by the dumper, so "empty" and
    /// "absent" are one answer in one place.
    /// </summary>
    object? SketchTextSegments(object sketch);

    /// <summary><c>IFeature.GetDefinition</c>; null for a feature that has none.</summary>
    object? Definition(object feature);

    /// <summary>Which fillet interface a definition object implements. A cast, not a call.</summary>
    FilletDefinitionKind ClassifyFillet(object definition);

    /// <summary><c>ISimpleFilletFeatureData2.DefaultRadius</c> in meters.</summary>
    double SimpleFilletDefaultRadius(object definition);

    /// <summary>
    /// The feature's persistent reference, scoped to the part document that owns it; null
    /// when SOLIDWORKS gave none. Gates <c>GetPersistReference3</c> itself.
    /// </summary>
    ScopedPersistRef? PersistRef(object document, object feature);
}

/// <summary>
/// T024. The feature tree of every part document the assembly resolves, once per document.
///
/// What it does NOT do is the point of the design (research R7): it reads no name and no
/// type name for meaning, keeps no RMS constant, and feeds <see cref="TypeNameCensus"/>
/// nothing. Folders, end tags, groups and classes are derived in Python against
/// <c>checks/rms_types.yaml</c>, so recalibrating for a new SOLIDWORKS release touches YAML
/// and tests rather than this file.
///
/// Three rules shape every read here:
///
///   * <b>Once per document.</b> A part instanced forty times has one tree; rows per
///     instance would multiply every finding by the instance count.
///   * <b>Nothing is resolved.</b> A lightweight, suppressed or unloaded component is a
///     <c>feature_tree_unavailable</c> gap; resolving it would change the session the
///     engineer is working in.
///   * <b>Nothing is defaulted.</b> A failed read is null plus the gap entity kind
///     data-model section 1 names, so the rule reports unresolved instead of passing
///     (constitution Principle I).
///
/// Nothing on the mutating side of the API is touched: the fillet radius comes off
/// <c>GetDefinition</c> without <c>AccessSelections</c>, which rolls the model back and would
/// have to be paired with <c>ReleaseSelectionAccess</c> (research R5).
/// </summary>
public sealed class FeatureDumper : IFeatureSource
{
    private readonly SwGate _gate;
    private readonly IFeatureReader _reader;

    public FeatureDumper(SwGate gate, IFeatureReader reader)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _reader = reader ?? throw new ArgumentNullException(nameof(reader));
    }

    public IReadOnlyList<Feature> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var rows = new List<Feature>();
        var walked = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (ScopedComponent component in scope.Components)
        {
            ComponentNode node = component.Node;

            // An assembly has a feature tree too, but the RMS part rules are about parts and
            // the subassembly documents are named in Python's coverage instead.
            if (node.DocumentKind != DocumentKind.Part || walked.Contains(node.DocumentPath))
            {
                continue;
            }

            if (node.Suppression != SuppressionState.Resolved)
            {
                // Deliberately not marked as walked: a later instance of the same part may be
                // resolved, and that one carries the tree.
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "feature_tree_unavailable",
                    component.Id,
                    $"'{node.Key}' is {PackageSerializer.EnumToJsonName(node.Suppression)}, so its "
                    + "feature tree was not read; it was not resolved, because resolving it would "
                    + "change the open session.",
                    null);
                continue;
            }

            object? document = null;
            if (!scope.Gaps.TryStep(
                "feature_tree_unavailable",
                component.Id,
                $"open the model document for '{node.Key}'",
                () => { document = _gate.Call("GetModelDoc2", () => _reader.Document(component)); }))
            {
                continue;
            }

            if (document == null)
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "feature_tree_unavailable",
                    component.Id,
                    $"'{node.Key}' has no loaded model document, so its feature tree was not read.",
                    null);
                continue;
            }

            walked.Add(node.DocumentPath);
            rows.AddRange(DumpDocument(scope, component, document!));
        }

        return rows;
    }

    /// <summary>One document's rows, or none when the tree could not be read whole.</summary>
    private IReadOnlyList<Feature> DumpDocument(DumpScope scope, ScopedComponent component, object document)
    {
        string documentId = component.DocumentId;
        string fileName = System.IO.Path.GetFileName(component.Node.DocumentPath);

        string? configuration = null;
        if (!scope.Gaps.TryStep(
                "feature",
                documentId,
                $"read the active configuration of {fileName}",
                () => { configuration = _reader.ActiveConfiguration(document); })
            || configuration == null)
        {
            // Without the configuration the rows could not say which tree they describe, and
            // a tree labelled with the wrong configuration is worse than no tree.
            return Dropped(scope, documentId, fileName, "its active configuration could not be read");
        }

        RecordOtherConfigurations(scope, component, configuration!);

        IReadOnlyList<FeatureTreeNode>? walk = null;
        if (!scope.Gaps.TryStep(
                "feature",
                documentId,
                $"walk the feature tree of {fileName}",
                () => { walk = _reader.Walk(document); })
            || walk == null)
        {
            return Dropped(scope, documentId, fileName, "the walk of its feature tree failed");
        }

        // The indexer refuses a walk with nothing in it rather than shift every later index,
        // so it throws here. Uncaught, that throw escapes the whole phase and PackageWriter
        // skips every later one - holes, threads, fasteners, faces, meshes - for one bad node
        // in one part, so it is this document's gap like every other failed read.
        IReadOnlyList<FeatureTreeRow>? indexed = null;
        var ids = new FeatureIdIndex();
        if (!scope.Gaps.TryStep(
                "feature",
                documentId,
                $"index the feature tree of {fileName}",
                () =>
                {
                    indexed = FeatureTreeIndexer.Index(walk!, scope.FeatureIds);
                    foreach (FeatureTreeRow row in indexed!)
                    {
                        ids.Add(row.Node.Handle, row.Id);
                    }
                })
            || indexed == null)
        {
            return Dropped(scope, documentId, fileName, "its feature tree could not be indexed");
        }

        var rows = new List<Feature>(indexed!.Count);
        foreach (FeatureTreeRow row in indexed!)
        {
            Feature? feature = ReadFeature(scope, document, documentId, configuration!, ids, row);
            if (feature == null)
            {
                // A row that cannot be written would leave a hole in the tree, and the group
                // assigner reads the rows in order: a missing folder or end tag silently
                // re-groups everything after it. The document's tree is dropped whole instead.
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "feature",
                    documentId,
                    $"'{row.Node.Name}' in {fileName} has no persistent reference, so it cannot be "
                    + "navigated to; the document's feature rows were dropped rather than written "
                    + "with a hole, which would change how every later feature is grouped.",
                    null);
                return Dropped(
                    scope,
                    documentId,
                    fileName,
                    $"'{row.Node.Name}' has no persistent reference");
            }

            rows.Add(feature!);
        }

        return rows;
    }

    /// <summary>
    /// No rows for this document, with the absence recorded in the kind the rule layer keys
    /// on. The <c>feature</c> gap the caller already wrote carries WHICH read failed; this
    /// one carries the consequence. Without it a document with a resolved instance and no
    /// rows is indistinguishable from one whose tree is genuinely empty, and the part rules
    /// grade an empty tree: six fail-severity rules pass over a tree nobody opened
    /// (constitution Principle I, and rules.md "Unresolved part documents").
    /// </summary>
    private static IReadOnlyList<Feature> Dropped(
        DumpScope scope, string documentId, string fileName, string why)
    {
        scope.Gaps.Add(
            GapKind.NotExtracted,
            "feature_tree_unavailable",
            documentId,
            $"The feature tree of {fileName} was not read: {why}.",
            null);

        return Array.Empty<Feature>();
    }

    /// <summary>
    /// The tree is read in the document's active configuration only. A part instanced under
    /// another configuration may have different features there, so the gap says which ones
    /// were not read rather than letting the rules judge the wrong tree.
    /// </summary>
    private static void RecordOtherConfigurations(
        DumpScope scope, ScopedComponent component, string configuration)
    {
        var others = new List<string>();
        foreach (ScopedComponent other in scope.Components)
        {
            string referenced = other.Node.ReferencedConfiguration;
            if (!string.Equals(other.Node.DocumentPath, component.Node.DocumentPath, StringComparison.OrdinalIgnoreCase)
                || string.IsNullOrWhiteSpace(referenced)
                || string.Equals(referenced, configuration, StringComparison.Ordinal)
                || others.Contains(referenced, StringComparer.Ordinal))
            {
                continue;
            }

            others.Add(referenced);
        }

        if (others.Count == 0)
        {
            return;
        }

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "feature_tree_configuration",
            scope.DocumentId(component.Node.DocumentPath),
            $"The feature tree was read in '{configuration}', and this document is also used under "
            + $"{string.Join(", ", others)}; the features of those configurations were not read.",
            null);
    }

    /// <summary>One row, or null when it has no persistent reference to carry.</summary>
    private Feature? ReadFeature(
        DumpScope scope,
        object document,
        string documentId,
        string configuration,
        FeatureIdIndex ids,
        FeatureTreeRow row)
    {
        string id = row.Id;
        string name = row.Node.Name;
        object? handle = row.Node.Handle;
        if (handle == null)
        {
            return null;
        }

        ScopedPersistRef? reference = null;
        if (!scope.Gaps.TryStep(
                "feature",
                id,
                $"read the persistent reference for '{name}'",
                () => { reference = _reader.PersistRef(document, handle!); })
            || reference == null)
        {
            return null;
        }

        List<string>? childIds = null;
        scope.Gaps.TryStep(
            "feature_children",
            id,
            $"read GetChildren for '{name}'",
            () =>
            {
                childIds = Map(
                    scope,
                    ids,
                    id,
                    name,
                    "feature_children",
                    "dependent",
                    _gate.Call("GetChildren", () => _reader.Children(handle!)));
            });

        List<string>? parentIds = null;
        scope.Gaps.TryStep(
            "feature_parents",
            id,
            $"read GetParents for '{name}'",
            () =>
            {
                parentIds = Map(
                    scope,
                    ids,
                    id,
                    name,
                    "feature_parents",
                    "dependency",
                    _gate.Call("GetParents", () => _reader.Parents(handle!)));
            });

        string? description = null;
        bool descriptionRead = scope.Gaps.TryStep(
            "feature_description",
            id,
            $"read Description for '{name}'",
            () => { description = _gate.Call("Description", () => _reader.Description(handle!)); });

        if (descriptionRead && description == null)
        {
            // SOLIDWORKS answered, with nothing. Blank ("") and unknown (null) are different
            // answers to the description rule - one fails, the other is unresolved - so the
            // absence is recorded as unknown and said out loud rather than read as blank.
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "feature_description",
                id,
                $"Description returned no text for '{name}', so whether it has one is unknown.",
                null);
        }

        int? errorCode = null;
        scope.Gaps.TryStep(
            "feature",
            id,
            $"read GetErrorCode2 for '{name}'",
            () => { errorCode = _gate.Call("GetErrorCode2", () => _reader.ErrorCode(handle!)); });

        bool? suppressed = null;
        scope.Gaps.TryStep(
            "feature",
            id,
            $"read IsSuppressed2 for '{name}' in '{configuration}'",
            () =>
            {
                suppressed = _gate.Call("IsSuppressed2", () => _reader.Suppressed(handle!, configuration));
            });

        return new Feature
        {
            Id = id,
            PersistRef = reference!.Base64,
            PersistRefScope = reference!.ScopeDocumentId,
            DocumentId = documentId,
            Configuration = configuration,
            Name = name,
            TypeName = row.Node.TypeName,
            Description = description,
            Index = row.Index,
            Depth = row.Depth,
            FolderId = row.FolderId,
            Suppressed = suppressed,
            ErrorCode = errorCode,
            ChildIds = childIds,
            ParentIds = parentIds,
            Sketch = ReadSketch(scope, id, name, handle!, childIds),
            Fillet = ReadFillet(scope, id, name, handle!),
        };
    }

    /// <summary>
    /// The sketch's raw status and its consumers, or null when this feature is not a sketch.
    /// The consumers ARE the children, so a failed <c>GetChildren</c> is one gap, not two.
    /// </summary>
    private SketchInfo? ReadSketch(
        DumpScope scope, string id, string name, object handle, List<string>? childIds)
    {
        object? sketch = null;
        scope.Gaps.TryStep(
            "sketch_status",
            id,
            $"read GetSpecificFeature2 for '{name}'",
            () => { sketch = _gate.Call("GetSpecificFeature2", () => _reader.Sketch(handle)); });

        if (sketch == null)
        {
            return null;
        }

        object found = sketch!;
        int? raw = null;
        scope.Gaps.TryStep(
            "sketch_status",
            id,
            $"read GetConstrainedStatus for sketch '{name}'",
            () =>
            {
                raw = _gate.Call("GetConstrainedStatus", () => _reader.SketchConstrainedStatus(found));
            });

        return new SketchInfo
        {
            RawStatus = raw,
            ConsumerIds = childIds,
            TextSegmentCount = ReadTextSegmentCount(scope, id, name, found),
        };
    }

    /// <summary>
    /// How many text segments the sketch carries (schema 1.4.0), recorded for EVERY sketch the
    /// tree holds - including one SOLIDWORKS nests under a hole-wizard feature, because
    /// difference z makes every recorded sketch a subject of
    /// <c>standards.part.sketches_fully_defined</c>.
    ///
    /// An empty or absent array is <c>0</c>, which rules the text exemption out; a read that
    /// threw is null plus a <c>sketch_text</c> gap, which leaves that sketch unresolved,
    /// because the exemption can then neither be applied nor ruled out. Whether an empty
    /// sketch answers with an empty array or with nothing is PROBE-9, and both read as 0 here:
    /// neither is a failure.
    /// </summary>
    private int? ReadTextSegmentCount(DumpScope scope, string id, string name, object sketch)
    {
        int? count = null;
        scope.Gaps.TryStep(
            "sketch_text",
            id,
            $"read GetSketchTextSegments for sketch '{name}'",
            () =>
            {
                object? segments = _gate.Call(
                    "GetSketchTextSegments", () => _reader.SketchTextSegments(sketch));

                count = segments is object[] array ? array.Length : 0;
            });

        return count;
    }

    /// <summary>
    /// The fillet's default radius in meters, or null plus a gap for a variable fillet and
    /// for a read that failed. A feature whose definition is not a fillet gets no
    /// <see cref="FilletInfo"/> and no gap: there was never a radius to find.
    /// </summary>
    private FilletInfo? ReadFillet(DumpScope scope, string id, string name, object handle)
    {
        object? definition = null;
        scope.Gaps.TryStep(
            "fillet_radius",
            id,
            $"read GetDefinition for '{name}'",
            () => { definition = _gate.Call("GetDefinition", () => _reader.Definition(handle)); });

        if (definition == null)
        {
            return null;
        }

        object found = definition!;
        FilletDefinitionKind kind = _reader.ClassifyFillet(found);

        if (kind == FilletDefinitionKind.NotAFillet)
        {
            return null;
        }

        if (kind == FilletDefinitionKind.Variable)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "fillet_radius",
                id,
                $"'{name}' is a variable-radius fillet, which has no single default radius; "
                + "its radius is left unknown rather than reported as one of its radii.",
                null);
            return new FilletInfo { DefaultRadius = null };
        }

        double? radius = null;
        scope.Gaps.TryStep(
            "fillet_radius",
            id,
            $"read DefaultRadius for '{name}'",
            () =>
            {
                radius = _gate.Call("DefaultRadius", () => _reader.SimpleFilletDefaultRadius(found));
            });

        return new FilletInfo
        {
            DefaultRadius = radius == null ? null : new Quantity(radius.Value, LengthUnit.M),
        };
    }

    /// <summary>
    /// Live features to the ids this document's walk gave them. A handle the walk never saw
    /// cannot be named, and dropping it silently would shorten a dependency list - which is
    /// exactly how a reference rule passes on a feature that does have a reference - so the
    /// ids that could be mapped are kept and the omission is a gap.
    /// </summary>
    private static List<string> Map(
        DumpScope scope,
        FeatureIdIndex ids,
        string featureId,
        string featureName,
        string entityKind,
        string relation,
        IReadOnlyList<object> handles)
    {
        var mapped = new List<string>();
        int unknown = 0;

        foreach (object handle in handles)
        {
            string? id = ids.IdOf(handle);
            if (id == null)
            {
                unknown++;
                continue;
            }

            mapped.Add(id!);
        }

        if (unknown > 0)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                entityKind,
                featureId,
                $"{unknown} {relation} feature(s) of '{featureName}' are not in this document's "
                + "tree, so they could not be named; the list is shorter than SOLIDWORKS reported.",
                null);
        }

        return mapped;
    }

    /// <summary>
    /// Live feature to package id. Reference identity first, then <c>Equals</c>, for the same
    /// reason <c>ComponentIndex</c> does: the CLR caches one RCW per COM identity per
    /// apartment, but interop can still hand back a second one, and an RCW's
    /// <c>Equals</c> compares the COM identity. It is not shared with that class because this
    /// one maps features within a single document and that one maps components across the
    /// package; merging them would need a generic index neither of them asked for.
    /// </summary>
    private sealed class FeatureIdIndex
    {
        private readonly Dictionary<object, string> _byReference =
            new Dictionary<object, string>(ReferenceComparer.Instance);

        private readonly List<KeyValuePair<object, string>> _byValue =
            new List<KeyValuePair<object, string>>();

        public void Add(object? handle, string id)
        {
            if (handle == null)
            {
                return;
            }

            _byReference[handle!] = id;
            _byValue.Add(new KeyValuePair<object, string>(handle!, id));
        }

        public string? IdOf(object? handle)
        {
            if (handle == null)
            {
                return null;
            }

            string found;
            if (_byReference.TryGetValue(handle!, out found))
            {
                return found;
            }

            foreach (KeyValuePair<object, string> entry in _byValue)
            {
                if (entry.Key.Equals(handle))
                {
                    return entry.Value;
                }
            }

            return null;
        }

        private sealed class ReferenceComparer : IEqualityComparer<object>
        {
            public static readonly ReferenceComparer Instance = new ReferenceComparer();

            public new bool Equals(object x, object y) => ReferenceEquals(x, y);

            public int GetHashCode(object obj) =>
                System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
        }
    }
}
