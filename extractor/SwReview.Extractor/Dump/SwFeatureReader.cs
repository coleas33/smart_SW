using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T024. The SOLIDWORKS side of <see cref="IFeatureReader"/>: interop calls and nothing
/// else, so that every decision <see cref="FeatureDumper"/> makes is testable without a seat
/// (the same split as <c>InterferenceRunner</c> and <c>SwInterferenceSource</c>).
///
/// Interop notes, all verified against the 2024 SP5 interop (research R5):
///   - <c>GetErrorCode2</c> takes an <c>out bool</c> warning flag; only the code is recorded.
///   - <c>IsSuppressed2</c> answers per configuration with a VARIANT that interop hands back
///     as a bool, a bool[], or an object[] of boxed bools depending on the build, so the one
///     configuration asked about is read out through the shared <see cref="SuppressionAnswer"/>
///     (the same helper <c>MateDumper</c> reads the mate feature's answer with).
///   - a variable-radius fillet is tested for FIRST: both fillet data interfaces expose
///     <c>DefaultRadius</c> and neither derives from the other, so asking "is it simple?"
///     first could report one of a variable fillet's radii as though it were the radius.
///   - <c>AccessSelections</c> is never called. It rolls the model back and would have to be
///     paired with <c>ReleaseSelectionAccess</c>; the radius reads without it.
/// </summary>
public sealed class SwFeatureReader : IFeatureReader
{
    /// <summary>
    /// How deep sub-features may nest before the walk gives up. A real tree is a handful of
    /// levels; a chain deeper than this means the model is answering in a cycle, and
    /// stopping silently would hand the rules a tree that is missing features.
    /// </summary>
    private const int MaxSubFeatureDepth = 64;

    private readonly SwGate _gate;
    private readonly PersistRefService _refs;

    public SwFeatureReader(SwGate gate, PersistRefService refs)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    /// <summary>
    /// The component's loaded document. Not gated here: the dumper names
    /// <c>GetModelDoc2</c> around this call, so one member is gated once.
    /// </summary>
    public object? Document(ScopedComponent component)
    {
        if (component == null)
        {
            throw new ArgumentNullException(nameof(component));
        }

        var handle = component.Node.Handle as IComponent2;
        return handle == null ? null : handle.GetModelDoc2() as IModelDoc2;
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
                + "configuration, so the tree cannot say which configuration it describes.");
        }

        return _gate.Call("Configuration.Name", () => configuration.Name) ?? string.Empty;
    }

    public IReadOnlyList<FeatureTreeNode> Walk(object document)
    {
        IModelDoc2 model = Doc(document);
        var nodes = new List<FeatureTreeNode>();

        var feature = _gate.Call("FirstFeature", () => model.FirstFeature()) as IFeature;
        while (feature != null)
        {
            IFeature current = feature;
            nodes.Add(ReadNode(current, depth: 0));
            feature = _gate.Call("GetNextFeature", () => current.GetNextFeature()) as IFeature;
        }

        return nodes;
    }

    public string? Description(object feature) =>
        Feature(feature).Description;

    public int ErrorCode(object feature)
    {
        bool isWarning;
        return Feature(feature).GetErrorCode2(out isWarning);
    }

    public bool Suppressed(object feature, string configuration)
    {
        object? answer = Feature(feature).IsSuppressed2(
            (int)swInConfigurationOpts_e.swSpecifyConfiguration,
            new[] { configuration });

        bool? flag = SuppressionAnswer.FirstFlag(answer);
        if (flag == null)
        {
            throw new InvalidOperationException(
                $"IsSuppressed2 answered {Describe(answer)} for '{configuration}', which carries no "
                + "suppression state; the dumper records this feature's suppression as unknown.");
        }

        return flag.Value;
    }

    public IReadOnlyList<object> Children(object feature) =>
        Features(Feature(feature).GetChildren());

    public IReadOnlyList<object> Parents(object feature) =>
        Features(Feature(feature).GetParents());

    public object? Sketch(object feature) =>
        Feature(feature).GetSpecificFeature2() as ISketch;

    public int SketchConstrainedStatus(object sketch) =>
        ((ISketch)sketch).GetConstrainedStatus();

    public object? Definition(object feature) =>
        Feature(feature).GetDefinition();

    public FilletDefinitionKind ClassifyFillet(object definition)
    {
        if (definition is IVariableFilletFeatureData2)
        {
            return FilletDefinitionKind.Variable;
        }

        return definition is ISimpleFilletFeatureData2
            ? FilletDefinitionKind.Simple
            : FilletDefinitionKind.NotAFillet;
    }

    public double SimpleFilletDefaultRadius(object definition) =>
        ((ISimpleFilletFeatureData2)definition).DefaultRadius;

    /// <summary>
    /// Which interface a definition object actually implements, for <c>probe rms</c>. An RCW
    /// reports its own type as <c>__ComObject</c>, so the two fillet interfaces are named by
    /// asking, and anything else falls back to the runtime type - which is exactly the
    /// calibration answer the probe exists to print (research R5).
    /// </summary>
    public string DescribeDefinition(object definition)
    {
        if (definition == null)
        {
            return "(none)";
        }

        if (definition is IVariableFilletFeatureData2)
        {
            return "IVariableFilletFeatureData2";
        }

        return definition is ISimpleFilletFeatureData2
            ? "ISimpleFilletFeatureData2"
            : definition.GetType().Name;
    }

    public ScopedPersistRef? PersistRef(object document, object feature) =>
        _refs.TryGet(Doc(document), feature);

    /// <summary>
    /// One node and the sub-features SOLIDWORKS lists under it, one level at a time. Which
    /// features own sub-features is the model's answer, not ours: a folder lists its
    /// contents, a boss lists its sketch, and the indexer turns either shape into
    /// depth and folder_id without reading a name (research R2).
    /// </summary>
    private FeatureTreeNode ReadNode(IFeature feature, int depth)
    {
        var node = new FeatureTreeNode
        {
            Name = _gate.Call("Feature.Name", () => feature.Name) ?? string.Empty,
            TypeName = _gate.Call("GetTypeName2", () => feature.GetTypeName2()) ?? string.Empty,
            Handle = feature,
        };

        if (depth >= MaxSubFeatureDepth)
        {
            throw new InvalidOperationException(
                $"The sub-features of '{node.Name}' nest deeper than {MaxSubFeatureDepth} levels; "
                + "the walk stopped rather than hand the rules part of a tree.");
        }

        var sub = _gate.Call("GetFirstSubFeature", () => feature.GetFirstSubFeature()) as IFeature;
        while (sub != null)
        {
            IFeature current = sub;
            node.SubFeatures.Add(ReadNode(current, depth + 1));
            sub = _gate.Call("GetNextSubFeature", () => current.GetNextSubFeature()) as IFeature;
        }

        return node;
    }

    /// <summary>
    /// <c>GetChildren</c> and <c>GetParents</c> answer with a VARIANT array, or with nothing
    /// when the feature has none. Anything in it that is not a feature is dropped here; the
    /// dumper's id mapping is what notices a feature it cannot name.
    /// </summary>
    private static IReadOnlyList<object> Features(object? answer)
    {
        var features = new List<object>();
        if (!(answer is object[] items))
        {
            return features;
        }

        foreach (object item in items)
        {
            if (item is IFeature)
            {
                features.Add(item);
            }
        }

        return features;
    }

    private static IModelDoc2 Doc(object document) => (IModelDoc2)document;

    private static IFeature Feature(object feature) => (IFeature)feature;

    private static string Describe(object? answer) =>
        answer == null ? "nothing" : answer.GetType().Name;
}
