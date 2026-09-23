using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Feature 010 T091. The SOLIDWORKS side of <see cref="IDimensionToleranceReader"/>: interop
/// calls and nothing else, so every decision <see cref="ToleranceDumper"/> makes is testable
/// without a seat.
///
/// Interop notes, every member reflected on the 2024 SP5 interop (32.5.0.48):
///   - The tolerance is read through <c>IDimension.Tolerance</c> (<c>IDimensionTolerance</c>):
///     <c>IDimension.GetToleranceType</c>, <c>GetToleranceValues</c> and
///     <c>GetToleranceFitValues</c> exist but the 2024 API documents them as obsolete.
///   - <c>GetMinValue2</c>/<c>GetMaxValue2</c> return an <c>swDimensionToleranceWarning_e</c>
///     status (0 valid for the type, 1 not) and the value through an <c>out</c>; a value
///     reported not valid is null here, never the number that came with it.
///   - The feature walk is <see cref="SwFeatureReader.Walk"/>'s, so the feature tree is read one
///     way; each feature's display dimensions are listed with <c>GetFirstDisplayDimension</c> and
///     <c>GetNextDisplayDimension</c>, as optional reads, bounded so a list that never ends stops.
///   - <c>GetSystemValue3</c> is read as <see cref="SwDrawingReader"/> reads it.
/// What a seat answers - which tolerance types the team's models carry, whether a display
/// dimension has a persistent reference - is T105's to record.
/// </summary>
public sealed class SwDimensionToleranceReader : IDimensionToleranceReader
{
    /// <summary>How many display dimensions one feature may list before the walk gives up.</summary>
    private const int MaxDisplayDimensionsPerFeature = 10000;

    private readonly SwGate _gate;
    private readonly PersistRefService _refs;
    private readonly SwFeatureReader _features;

    public SwDimensionToleranceReader(SwGate gate, PersistRefService refs)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
        _features = new SwFeatureReader(gate, refs);
    }

    /// <summary>Not gated here: the dumper names <c>GetModelDoc2</c> around this call.</summary>
    public object? Document(ScopedComponent component)
    {
        if (component == null)
        {
            throw new ArgumentNullException(nameof(component));
        }

        return ComponentDocuments.Of(component.Node);
    }

    public IReadOnlyList<DimensionSighting> DisplayDimensions(object document)
    {
        var sightings = new List<DimensionSighting>();
        foreach (FeatureTreeNode node in _features.Walk(document))
        {
            AddSightings(node, sightings);
        }

        return sightings;
    }

    public object? Dimension(object displayDimension) =>
        ((IDisplayDimension)displayDimension).GetDimension2(0);

    public int DimensionType(object displayDimension) => ((IDisplayDimension)displayDimension).Type2;

    public string? FullName(object dimension) => ((IDimension)dimension).FullName;

    public double? SystemValue(object dimension) =>
        SwDrawingReader.FirstNumber(((IDimension)dimension).GetSystemValue3(
            (int)swInConfigurationOpts_e.swThisConfiguration, null));

    public object? Tolerance(object dimension) => ((IDimension)dimension).Tolerance;

    public int ToleranceType(object tolerance) => ((IDimensionTolerance)tolerance).Type;

    public double? ToleranceMin(object tolerance)
    {
        int status = ((IDimensionTolerance)tolerance).GetMinValue2(out double value);
        return status == (int)swDimensionToleranceWarning_e.swDimensionTolerance_ValidForType ? value : (double?)null;
    }

    public double? ToleranceMax(object tolerance)
    {
        int status = ((IDimensionTolerance)tolerance).GetMaxValue2(out double value);
        return status == (int)swDimensionToleranceWarning_e.swDimensionTolerance_ValidForType ? value : (double?)null;
    }

    public string? HoleFitValue(object tolerance) => ((IDimensionTolerance)tolerance).GetHoleFitValue();

    public string? ShaftFitValue(object tolerance) => ((IDimensionTolerance)tolerance).GetShaftFitValue();

    /// <summary>Gates <c>GetPersistReference3</c> and <c>GetPathName</c> through the service.</summary>
    public ScopedPersistRef? PersistRef(object document, object entity) =>
        _refs.TryGet((IModelDoc2)document, entity);

    /// <summary>One feature's display dimensions, then its sub-features', depth first.</summary>
    private void AddSightings(FeatureTreeNode node, List<DimensionSighting> sightings)
    {
        if (node.Handle is IFeature feature)
        {
            object? display = _gate.CallOptional("GetFirstDisplayDimension", () => feature.GetFirstDisplayDimension());
            int count = 0;
            while (display != null)
            {
                if (++count > MaxDisplayDimensionsPerFeature)
                {
                    throw new InvalidOperationException(
                        $"Feature '{node.Name}' listed more than {MaxDisplayDimensionsPerFeature} display "
                        + "dimensions; the walk stopped rather than follow a list that does not end.");
                }

                object current = display;
                sightings.Add(new DimensionSighting(node.Name, current));
                display = _gate.CallOptional(
                    "GetNextDisplayDimension", () => feature.GetNextDisplayDimension(current));
            }
        }

        foreach (FeatureTreeNode sub in node.SubFeatures)
        {
            AddSightings(sub, sightings);
        }
    }
}

/// <summary>
/// Feature 010 T091. The SOLIDWORKS side of <see cref="IModelAnnotationReader"/>.
///
/// Interop notes, every member reflected on the 2024 SP5 interop (32.5.0.48):
///   - <c>IModelDocExtension.GetAnnotations</c> lists a part's annotations in one call;
///     <c>IAnnotation.GetType</c> (<c>swAnnotationType_e</c>: GTol 5, datum tag 2) decides which
///     are read.
///   - A GTol created before SOLIDWORKS 2022 answers <c>GetFrameValues(short)</c> and
///     <c>GetFrameSymbols3(int)</c>; one in the 2022 format answers <c>GetFrame(int)</c>, an
///     <c>IGtolFrame</c> whose <c>GetSymbolXml</c> is the frame. Each call is documented valid for
///     one generation only, so both are asked (see <see cref="ToleranceDumper"/>).
///   - <c>GetAttachedEntities3</c> answers faces, edges, vertices and nulls for dangling or
///     unsupported attachments; only the faces carry the persistent reference a hole's faces are
///     matched on, so only they are kept.
/// Whether the team's models carry DimXpert or MBD annotations at all is T105's to record.
/// </summary>
public sealed class SwModelAnnotationReader : IModelAnnotationReader
{
    private readonly SwGate _gate;
    private readonly PersistRefService _refs;

    public SwModelAnnotationReader(SwGate gate, PersistRefService refs)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    public IReadOnlyList<object> Annotations(object document) =>
        ((IModelDoc2)document).Extension.GetAnnotations() is object[] items
            ? items.Where(item => item != null).ToList()
            : new List<object>();

    public int AnnotationType(object annotation) => ((IAnnotation)annotation).GetType();

    public bool IsDimXpert(object annotation) => ((IAnnotation)annotation).IsDimXpert();

    public object? Specific(object annotation) => ((IAnnotation)annotation).GetSpecificAnnotation();

    public int FrameCount(object gtol) => ((IGtol)gtol).GetFrameCount();

    public IReadOnlyList<string>? FrameValues(object gtol, int frame) =>
        Strings(((IGtol)gtol).GetFrameValues((short)frame));

    public IReadOnlyList<string>? FrameSymbols(object gtol, int frame) =>
        Strings(((IGtol)gtol).GetFrameSymbols3(frame));

    /// <summary>Two calls, both gated here: <c>GetFrame</c>, then <c>GetSymbolXml</c>.</summary>
    public string? FrameXml(object gtol, int frame)
    {
        var read = _gate.CallOptional("GetFrame", () => ((IGtol)gtol).GetFrame(frame)) as IGtolFrame;
        return read == null ? null : _gate.CallOptional("GetSymbolXml", () => read.GetSymbolXml());
    }

    public string? DatumIdentifier(object gtol) => ((IGtol)gtol).GetDatumIdentifier();

    public string? DatumLabel(object datumTag) => ((IDatumTag)datumTag).GetLabel();

    /// <summary>
    /// Gates <c>GetAttachedEntities3</c> here, and <c>GetPersistReference3</c> through the
    /// service for each face.
    /// </summary>
    public IReadOnlyList<string> AttachedFacePersistRefs(object document, object annotation)
    {
        var references = new List<string>();
        var entities = _gate.CallOptional(
            "GetAttachedEntities3", () => ((IAnnotation)annotation).GetAttachedEntities3()) as object[];
        if (entities == null)
        {
            return references;
        }

        foreach (object entity in entities)
        {
            if (entity is IFace2 face)
            {
                ScopedPersistRef? reference = _refs.TryGet((IModelDoc2)document, face);
                if (reference != null)
                {
                    references.Add(reference.Base64);
                }
            }
        }

        return references;
    }

    /// <summary>Gates <c>GetPersistReference3</c> and <c>GetPathName</c> through the service.</summary>
    public ScopedPersistRef? PersistRef(object document, object annotation) =>
        _refs.TryGet((IModelDoc2)document, annotation);

    /// <summary>An interop array of strings as a list, empty entries kept; null when none came back.</summary>
    private static IReadOnlyList<string>? Strings(object? value)
    {
        switch (value)
        {
            case string[] strings:
                return strings;
            case object[] items:
                return items.Select(item => item as string ?? string.Empty).ToList();
            default:
                return null;
        }
    }
}
