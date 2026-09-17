using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T040. The SOLIDWORKS side of <see cref="ICutListReader"/>: interop calls and nothing else,
/// so that every decision <see cref="CutListDumper"/> makes is testable without a seat - the
/// same split <see cref="SwFeatureReader"/> is to <see cref="FeatureDumper"/>.
///
/// Interop notes:
///   - <c>GetChildren</c> has no equivalent here: a cut-list folder lists its items as
///     SUB-features, so the walk is <c>GetFirstSubFeature</c> / <c>GetNextSubFeature</c>, the
///     same pair <see cref="SwFeatureReader"/> uses.
///   - <c>GetSpecificFeature2</c> is cast to <c>IBodyFolder</c> and to nothing else. The cast
///     IS the identification: no feature name is matched (difference bb).
///   - <c>ExcludeFromCutList</c> is the read. Its write, <c>set_ExcludeFromCutList</c>, is on
///     the denylist, and whether the read answers without activating the body folder is
///     PROBE-8 - if it does not, the gap says so rather than the dump activating anything.
/// </summary>
public sealed class SwCutListReader : ICutListReader
{
    /// <summary>
    /// How many features one walk may list before it gives up. Not the same guard
    /// <see cref="SwFeatureReader"/> uses - that one bounds recursion DEPTH - but it is the
    /// same answer to hitting it: a list this long means the model is answering in a cycle,
    /// so the walk throws and the dumper's <c>TryStep</c> turns it into a
    /// <c>cut_list_folder</c> gap. Truncating instead would hand the checks half a cut list
    /// and call it whole.
    /// </summary>
    private const int MaxFeatureCount = 100000;

    private readonly SwGate _gate;
    private readonly PersistRefService _refs;

    public SwCutListReader(SwGate gate, PersistRefService refs)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    /// <summary>
    /// The component's loaded document. Not gated here: the dumper names <c>GetModelDoc2</c>
    /// around this call, so one member is gated once.
    /// </summary>
    public object? Document(ScopedComponent component)
    {
        if (component == null)
        {
            throw new ArgumentNullException(nameof(component));
        }

        return ComponentDocuments.Of(component.Node);
    }

    public string ActiveConfiguration(object document)
    {
        IModelDoc2 model = Doc(document);
        var configuration = _gate.Call(
            "ConfigurationManager.ActiveConfiguration",
            () => model.ConfigurationManager?.ActiveConfiguration) as IConfiguration;

        if (configuration == null)
        {
            throw new InvalidOperationException(
                $"'{_gate.Call("GetPathName", () => model.GetPathName())}' reports no active "
                + "configuration, so its cut list cannot say which configuration it describes.");
        }

        return _gate.Call("Configuration.Name", () => configuration.Name) ?? string.Empty;
    }

    public IReadOnlyList<object> Features(object document)
    {
        IModelDoc2 model = Doc(document);
        var features = new List<object>();

        var feature = _gate.Call("FirstFeature", () => model.FirstFeature()) as IFeature;
        while (feature != null)
        {
            if (features.Count >= MaxFeatureCount)
            {
                throw new InvalidOperationException(
                    $"The feature tree of '{_gate.Call("GetPathName", () => model.GetPathName())}' "
                    + $"lists more than {MaxFeatureCount} features; the walk stopped rather than "
                    + "hand the checks half a cut list.");
            }

            IFeature current = feature;
            features.Add(current);
            feature = _gate.Call("GetNextFeature", () => current.GetNextFeature()) as IFeature;
        }

        return features;
    }

    public IReadOnlyList<object> SubFeatures(object feature)
    {
        IFeature folder = Feature(feature);
        var children = new List<object>();

        var sub = _gate.Call("GetFirstSubFeature", () => folder.GetFirstSubFeature()) as IFeature;
        while (sub != null)
        {
            if (children.Count >= MaxFeatureCount)
            {
                throw new InvalidOperationException(
                    $"'{_gate.Call("Feature.Name", () => folder.Name)}' lists more than "
                    + $"{MaxFeatureCount} sub-features; the walk stopped rather than hand the "
                    + "checks half a cut list.");
            }

            IFeature current = sub;
            children.Add(current);
            sub = _gate.Call("GetNextSubFeature", () => current.GetNextSubFeature()) as IFeature;
        }

        return children;
    }

    public string Name(object feature) => Feature(feature).Name ?? string.Empty;

    public string TypeName(object feature) => Feature(feature).GetTypeName2() ?? string.Empty;

    public object? BodyFolder(object feature) =>
        Feature(feature).GetSpecificFeature2() as IBodyFolder;

    public int BodyCount(object bodyFolder) => ((IBodyFolder)bodyFolder).GetBodyCount();

    public bool ExcludedFromCutList(object feature) => Feature(feature).ExcludeFromCutList;

    public ScopedPersistRef? PersistRef(object document, object feature) =>
        _refs.TryGet(Doc(document), feature);

    private static IModelDoc2 Doc(object document) => (IModelDoc2)document;

    private static IFeature Feature(object feature) => (IFeature)feature;
}
