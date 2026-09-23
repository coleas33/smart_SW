using System;
using System.Collections.Generic;
using System.Globalization;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
// SwReview.Extractor.Measure is a namespace (the remodel geometry), so the IR union type is
// named explicitly, as IrSerializerTests names it.
using IrMeasure = SwReview.Extractor.Ir.Measure;

namespace SwReview.Extractor.Dump;

/// <summary>One display dimension sighted in a feature tree, with the feature that owns it.</summary>
public sealed class DimensionSighting
{
    public DimensionSighting(string featureName, object displayDimension)
    {
        FeatureName = featureName ?? string.Empty;
        DisplayDimension = displayDimension ?? throw new ArgumentNullException(nameof(displayDimension));
    }

    public string FeatureName { get; }

    public object DisplayDimension { get; }
}

/// <summary>
/// The dimension reads <see cref="ToleranceDumper"/> needs, with no interop type in the signature
/// (<see cref="SwDimensionToleranceReader"/> is the SOLIDWORKS one). Every member that maps to one
/// interop call is gated by the dumper under that call's name; <see cref="DisplayDimensions"/> and
/// <see cref="PersistRef"/> span several calls and gate them inside the implementation. The six
/// tolerance reads are <see cref="IDimensionToleranceReads"/>, which a drawing's display dimension
/// is read through too (feature 011).
/// </summary>
public interface IDimensionToleranceReader : IDimensionToleranceReads
{
    /// <summary><c>IComponent2.GetModelDoc2</c>; null when the document is not loaded.</summary>
    object? Document(ScopedComponent component);

    /// <summary>
    /// Every display dimension of every feature and sub-feature, in tree order, with the owning
    /// feature's name (<c>FirstFeature</c>, <c>GetNextFeature</c>, <c>GetFirstSubFeature</c>,
    /// <c>GetNextSubFeature</c>, <c>IFeature.Name</c>, <c>GetFirstDisplayDimension</c>,
    /// <c>GetNextDisplayDimension</c>).
    /// </summary>
    IReadOnlyList<DimensionSighting> DisplayDimensions(object document);

    /// <summary><c>IDisplayDimension.GetDimension2(0)</c>; null when it gives none.</summary>
    object? Dimension(object displayDimension);

    /// <summary><c>IDisplayDimension.Type2</c> verbatim (<c>swDimensionType_e</c>).</summary>
    int DimensionType(object displayDimension);

    /// <summary><c>IDimension.FullName</c>.</summary>
    string? FullName(object dimension);

    /// <summary><c>IDimension.GetSystemValue3(swThisConfiguration, null)</c>'s number; null when none.</summary>
    double? SystemValue(object dimension);

    /// <summary>The display dimension's persistent reference, scoped to its part; null when none.</summary>
    ScopedPersistRef? PersistRef(object document, object entity);
}

/// <summary>
/// The annotation reads <see cref="ToleranceDumper"/> needs, with no interop type in the
/// signature (<see cref="SwModelAnnotationReader"/> is the SOLIDWORKS one). The same gating rule
/// as <see cref="IDimensionToleranceReader"/>; <see cref="FrameXml"/>,
/// <see cref="AttachedFacePersistRefs"/> and <see cref="PersistRef"/> gate inside.
/// </summary>
public interface IModelAnnotationReader
{
    /// <summary><c>IModelDocExtension.GetAnnotations</c>, as a list.</summary>
    IReadOnlyList<object> Annotations(object document);

    /// <summary><c>IAnnotation.GetType</c> verbatim (<c>swAnnotationType_e</c>).</summary>
    int AnnotationType(object annotation);

    /// <summary><c>IAnnotation.IsDimXpert</c>.</summary>
    bool IsDimXpert(object annotation);

    /// <summary><c>IAnnotation.GetSpecificAnnotation</c>: the IGtol or IDatumTag.</summary>
    object? Specific(object annotation);

    /// <summary><c>IGtol.GetFrameCount</c>.</summary>
    int FrameCount(object gtol);

    /// <summary><c>IGtol.GetFrameValues(frame)</c> as strings; null when it answers nothing.</summary>
    IReadOnlyList<string>? FrameValues(object gtol, int frame);

    /// <summary><c>IGtol.GetFrameSymbols3(frame)</c> as strings; null when it answers nothing.</summary>
    IReadOnlyList<string>? FrameSymbols(object gtol, int frame);

    /// <summary><c>IGtol.GetFrame(frame)</c> then <c>IGtolFrame.GetSymbolXml</c>; null for the pre-2022 format.</summary>
    string? FrameXml(object gtol, int frame);

    /// <summary><c>IGtol.GetDatumIdentifier</c>.</summary>
    string? DatumIdentifier(object gtol);

    /// <summary><c>IDatumTag.GetLabel</c>.</summary>
    string? DatumLabel(object datumTag);

    /// <summary>
    /// The persistent references of the faces <c>IAnnotation.GetAttachedEntities3</c> returns;
    /// an edge, a vertex or a dangling attachment has no face reference and is left out.
    /// </summary>
    IReadOnlyList<string> AttachedFacePersistRefs(object document, object annotation);

    /// <summary>The annotation's own persistent reference, scoped to its part; null when none.</summary>
    ScopedPersistRef? PersistRef(object document, object annotation);
}

/// <summary>
/// Feature 010 T091. The <c>tolerance</c> phase (schema 1.5.0, FR-022,
/// contracts/tolerances.md section 2): every part document's feature dimensions with their
/// tolerances, and its geometric tolerances and datum tags, DimXpert or MBD.
///
/// Four rules shape it:
///
///   * <b>Once per part document</b>, as <see cref="FeatureDumper"/> reads the feature trees: a
///     part instanced forty times has one set of dimensions, and an unresolved instance is a
///     <c>tolerance</c> gap that does not stop a resolved instance of the same part.
///   * <b>Every dimension, toleranced or not.</b> A tolerance binds to a hole only through the
///     unique dimension of its value in the document (research R2.18).
///   * <b>Verbatim.</b> System units (metres, radians) decided by the dimension's type exactly as
///     <see cref="DrawingDumper.UnitOf"/> decides them; the raw type numbers kept beside the
///     names; a tolerance type the IR's kinds cannot express is a null tolerance, never "none".
///   * <b>One gap per failed read, never an open circuit.</b> Every read of one dimension or one
///     annotation goes through <see cref="SwGate.CallOptional{T}"/>: a failure is a
///     <c>model_dimension</c> or <c>model_annotation</c> gap on that item and the phase carries
///     on, so a read SOLIDWORKS refuses for one kind of dimension cannot end the dump.
///
/// Nothing is written: every member read here is a getter, and the setters beside them are on the
/// read-only denylist (feature 010's table in <c>004-resilient-remodeler/contracts/guard-allowlist.md</c>).
/// </summary>
public sealed class ToleranceDumper : IToleranceSource
{
    /// <summary>swAnnotationType_e (reflected on 2024 SP5): datum tag 2, GTol 5.</summary>
    private const int DatumTagAnnotation = 2;

    private const int GtolAnnotation = 5;

    private readonly SwGate _gate;
    private readonly IDimensionToleranceReader _dimensions;
    private readonly IModelAnnotationReader _annotations;

    public ToleranceDumper(SwGate gate, IDimensionToleranceReader dimensions, IModelAnnotationReader annotations)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _dimensions = dimensions ?? throw new ArgumentNullException(nameof(dimensions));
        _annotations = annotations ?? throw new ArgumentNullException(nameof(annotations));
    }

    public ToleranceDumpResult Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var result = new ToleranceDumpResult();
        var walked = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (ScopedComponent component in scope.Components)
        {
            ComponentNode node = component.Node;
            if (node.DocumentKind != DocumentKind.Part || walked.Contains(node.DocumentPath))
            {
                continue;
            }

            if (node.Suppression != SuppressionState.Resolved)
            {
                // Not marked as walked: a later instance of the same part may be resolved.
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "tolerance",
                    component.Id,
                    $"'{node.Key}' is {PackageSerializer.EnumToJsonName(node.Suppression)}, so its "
                    + "dimensions, tolerances and annotations were not read; it was not resolved, "
                    + "because resolving it would change the open session.",
                    null);
                continue;
            }

            object? document = null;
            if (!scope.Gaps.TryStep(
                "tolerance",
                component.Id,
                $"open the model document for '{node.Key}'",
                () => { document = _gate.Call("GetModelDoc2", () => _dimensions.Document(component)); }))
            {
                continue;
            }

            if (document == null)
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "tolerance",
                    component.Id,
                    $"'{node.Key}' has no loaded model document, so its dimensions, tolerances "
                    + "and annotations were not read.",
                    null);
                continue;
            }

            walked.Add(node.DocumentPath);
            string documentId = scope.DocumentId(node.DocumentPath);
            result.Dimensions.AddRange(ReadDimensions(scope, document!, documentId, node.Key));
            result.Annotations.AddRange(ReadAnnotations(scope, document!, documentId, node.Key));
        }

        return result;
    }

    // ---- dimensions ------------------------------------------------------------------

    private List<ModelDimension> ReadDimensions(
        DumpScope scope, object document, string documentId, string componentKey)
    {
        var dimensions = new List<ModelDimension>();

        IReadOnlyList<DimensionSighting>? sightings = scope.Gaps.TryStep(
            "tolerance",
            documentId,
            $"walk the feature dimensions of '{componentKey}'",
            () => _dimensions.DisplayDimensions(document));
        if (sightings == null)
        {
            return dimensions;
        }

        // A sketch's dimension can be sighted from the sketch and from the feature that absorbed
        // it; FullName is unique in a document, so the first sighting is kept.
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (DimensionSighting sighting in sightings)
        {
            ModelDimension? dimension = scope.Gaps.TryStep(
                "model_dimension",
                documentId,
                $"read a dimension of feature '{sighting.FeatureName}'",
                () => ReadDimension(scope, document, documentId, sighting, names));
            if (dimension != null)
            {
                dimensions.Add(dimension);
            }
        }

        return dimensions;
    }

    private ModelDimension? ReadDimension(
        DumpScope scope, object document, string documentId, DimensionSighting sighting, HashSet<string> names)
    {
        object display = sighting.DisplayDimension;
        object? dimension = _gate.CallOptional("GetDimension2", () => _dimensions.Dimension(display));
        if (dimension == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_dimension",
                documentId,
                $"A display dimension of feature '{sighting.FeatureName}' gave no IDimension, so it "
                + "was not recorded.",
                null);
            return null;
        }

        string? name = HoleDumper.Blank(_gate.CallOptional("FullName", () => _dimensions.FullName(dimension)));
        if (name == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_dimension",
                documentId,
                $"A dimension of feature '{sighting.FeatureName}' has no name, so it cannot be cited "
                + "and was not recorded.",
                null);
            return null;
        }

        if (!names.Add(name))
        {
            return null;
        }

        int typeRaw = _gate.CallOptional("Type2", () => _dimensions.DimensionType(display));
        string? unit = DrawingDumper.UnitOf(typeRaw);
        if (unit == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_dimension",
                documentId,
                $"Dimension '{name}' is of type {typeRaw.ToString(CultureInfo.InvariantCulture)} "
                + "(swDimensionType_e), which decides no unit, so it was not recorded: a number with "
                + "a guessed unit is worse than none.",
                null);
            return null;
        }

        double? value = _gate.CallOptional("GetSystemValue3", () => _dimensions.SystemValue(dimension));
        if (value == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_dimension",
                documentId,
                $"Dimension '{name}' gave no value from GetSystemValue3, so it was not recorded.",
                null);
            return null;
        }

        var record = new ModelDimension
        {
            Id = scope.ModelDimensionIds.Next(),
            DocumentId = documentId,
            FeatureName = sighting.FeatureName,
            Name = name,
            DimensionType = DimensionTypeOf(typeRaw),
            DimensionTypeRaw = typeRaw,
            Nominal = new IrMeasure(value.Value, unit),
        };

        ScopedPersistRef? reference = null;
        bool answered = scope.Gaps.TryStep(
            "model_dimension",
            record.Id,
            $"read the persistent reference of dimension '{name}'",
            () => { reference = _dimensions.PersistRef(document, display); });
        if (answered && reference == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_dimension",
                record.Id,
                $"Dimension '{name}' has no persistent reference; it is cited by its name.",
                null);
        }
        else if (reference != null)
        {
            record.PersistRef = reference.Base64;
            record.PersistRefScope = reference.ScopeDocumentId;
        }

        scope.Gaps.TryStep(
            "model_dimension",
            record.Id,
            $"read the tolerance of dimension '{name}'",
            () => ReadTolerance(scope, dimension, record, unit));
        return record;
    }

    /// <summary>
    /// The dimension's tolerance, read as one through <see cref="DimensionTolerance.Read"/> - the
    /// read and mapping the drawing's display dimensions share (feature 011) - and assigned only
    /// once every read has answered, so a read that throws leaves no half of a tolerance behind.
    /// </summary>
    private void ReadTolerance(DumpScope scope, object dimension, ModelDimension record, string unit)
    {
        var source = new SourceRef
        {
            DocumentId = record.DocumentId,
            Annotation = record.Name,
            PersistRef = record.PersistRef,
        };

        DimensionToleranceReading reading = DimensionTolerance.Read(_gate, _dimensions, dimension, source, unit);
        if (reading.Missing)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_dimension",
                record.Id,
                $"Dimension '{record.Name}' gave no IDimensionTolerance, so its tolerance is unknown.",
                null);
            return;
        }

        record.Tolerance = reading.Tolerance;
        record.ToleranceTypeRaw = reading.TypeRaw;
        record.FitHoleClass = reading.HoleFit;
        record.FitShaftClass = reading.ShaftFit;

        if (reading.InvalidLimits.Count > 0)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_dimension",
                record.Id,
                $"Dimension '{record.Name}' has a tolerance of type "
                + $"{reading.TypeRaw.ToString(CultureInfo.InvariantCulture)} but "
                + $"{string.Join(" and ", reading.InvalidLimits)} reported the value not valid for it, so "
                + "that limit is unknown.",
                null);
        }
    }

    /// <summary>
    /// <c>swTolType_e</c> (reflected on 2024 SP5) to the IR's tolerance kind: NONE 0 is "none",
    /// BASIC 1 "basic", SYMMETRIC 4 "symmetric", and BILAT 2, LIMIT 3, FITWITHTOL 8 and FITTOLONLY
    /// 9 "bilateral", because GetMinValue2/GetMaxValue2 report signed deviations whatever the
    /// display and the IR's "limits" means the two sizes themselves. MIN 5, MAX 6, FIT 7, BLOCK 10,
    /// GENERAL 11 and anything else have no IR kind: null, never "none".
    /// </summary>
    public static ToleranceKind? KindOf(int toleranceType) => toleranceType switch
    {
        0 => ToleranceKind.None,
        1 => ToleranceKind.Basic,
        2 or 3 or 8 or 9 => ToleranceKind.Bilateral,
        4 => ToleranceKind.Symmetric,
        _ => null,
    };

    /// <summary>FIT 7, FITWITHTOL 8 and FITTOLONLY 9: the types that carry hole and shaft classes.</summary>
    public static bool IsFitType(int toleranceType) => toleranceType == 7 || toleranceType == 8 || toleranceType == 9;

    /// <summary>
    /// <c>swDimensionType_e</c> (reflected) to the IR's dimension type: diameter 6, radial 5,
    /// angular 3 and angular ordinate 16, and linear for the ordinate and linear types 1, 2, 7, 8,
    /// 9, 11, 12. Arc length, chamfer, radial linear and diametric linear are "other", with the
    /// raw number beside the name.
    /// </summary>
    public static ModelDimensionType DimensionTypeOf(int dimensionType) => dimensionType switch
    {
        6 => ModelDimensionType.Diameter,
        5 => ModelDimensionType.Radius,
        3 or 16 => ModelDimensionType.Angular,
        1 or 2 or 7 or 8 or 9 or 11 or 12 => ModelDimensionType.Linear,
        _ => ModelDimensionType.Other,
    };

    // ---- annotations -----------------------------------------------------------------

    private List<ModelAnnotation> ReadAnnotations(
        DumpScope scope, object document, string documentId, string componentKey)
    {
        var annotations = new List<ModelAnnotation>();

        IReadOnlyList<object>? all = scope.Gaps.TryStep(
            "tolerance",
            documentId,
            $"list the annotations of '{componentKey}'",
            () => _gate.CallOptional("GetAnnotations", () => _annotations.Annotations(document)));
        if (all == null)
        {
            return annotations;
        }

        foreach (object annotation in all)
        {
            ModelAnnotation? record = scope.Gaps.TryStep(
                "model_annotation",
                documentId,
                $"read an annotation of '{componentKey}'",
                () => ReadAnnotation(scope, document, documentId, annotation));
            if (record != null)
            {
                annotations.Add(record);
            }
        }

        return annotations;
    }

    private ModelAnnotation? ReadAnnotation(DumpScope scope, object document, string documentId, object annotation)
    {
        int type = _gate.CallOptional("Annotation.GetType", () => _annotations.AnnotationType(annotation));
        if (type != GtolAnnotation && type != DatumTagAnnotation)
        {
            return null;
        }

        object? specific = _gate.CallOptional("GetSpecificAnnotation", () => _annotations.Specific(annotation));
        if (specific == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "model_annotation",
                documentId,
                $"An annotation of type {type.ToString(CultureInfo.InvariantCulture)} "
                + "(swAnnotationType_e) gave no GTol or datum tag, so it was not recorded.",
                null);
            return null;
        }

        bool gtol = type == GtolAnnotation;
        int frameCount = gtol ? _gate.CallOptional("GetFrameCount", () => _annotations.FrameCount(specific)) : 0;

        var record = new ModelAnnotation
        {
            Id = scope.ModelAnnotationIds.Next(),
            DocumentId = documentId,
            Kind = gtol ? ModelAnnotationKind.Gtol : ModelAnnotationKind.Datum,
        };

        scope.Gaps.TryStep(
            "model_annotation",
            record.Id,
            "read IsDimXpert",
            () => { record.IsDimXpert = _gate.CallOptional("IsDimXpert", () => _annotations.IsDimXpert(annotation)); });

        if (gtol)
        {
            for (int frame = 1; frame <= frameCount; frame++)
            {
                GtolFrame? read = ReadFrame(scope, record, specific, frame);
                if (read != null)
                {
                    record.Frames.Add(read);
                }
            }

            scope.Gaps.TryStep(
                "model_annotation",
                record.Id,
                "read GetDatumIdentifier",
                () =>
                {
                    record.DatumIdentifierRaw = HoleDumper.Blank(
                        _gate.CallOptional("GetDatumIdentifier", () => _annotations.DatumIdentifier(specific)));
                });
        }
        else
        {
            scope.Gaps.TryStep(
                "model_annotation",
                record.Id,
                "read GetLabel",
                () => { record.Label = HoleDumper.Blank(_gate.CallOptional("GetLabel", () => _annotations.DatumLabel(specific))); });
        }

        scope.Gaps.TryStep(
            "model_annotation",
            record.Id,
            "read the faces the annotation is attached to",
            () => { record.AttachedPersistRefs.AddRange(_annotations.AttachedFacePersistRefs(document, annotation)); });

        scope.Gaps.TryStep(
            "model_annotation",
            record.Id,
            "read the persistent reference of the annotation",
            () =>
            {
                ScopedPersistRef? reference = _annotations.PersistRef(document, annotation);
                record.PersistRef = reference?.Base64;
                record.PersistRefScope = reference?.ScopeDocumentId;
            });

        return record;
    }

    /// <summary>
    /// One frame, asked both ways: the pre-2022 calls and the 2022 format's XML, since the API
    /// answers each for one generation of GTol only. A frame any call answered is kept with
    /// whatever answered. A frame no call answered is left out: silently when nothing failed (a
    /// stored, empty frame), and with one gap naming every error when something did.
    /// </summary>
    private GtolFrame? ReadFrame(DumpScope scope, ModelAnnotation record, object gtol, int frame)
    {
        var errors = new List<string>();

        IReadOnlyList<string>? values = OptionalFrameRead(
            errors, () => _gate.CallOptional("GetFrameValues", () => _annotations.FrameValues(gtol, frame)));
        IReadOnlyList<string>? symbols = OptionalFrameRead(
            errors, () => _gate.CallOptional("GetFrameSymbols3", () => _annotations.FrameSymbols(gtol, frame)));
        string? xml = OptionalFrameRead(errors, () => HoleDumper.Blank(_annotations.FrameXml(gtol, frame)));

        bool answered = (values != null && values.Count > 0) || (symbols != null && symbols.Count > 0) || xml != null;
        if (answered)
        {
            var read = new GtolFrame { Number = frame, SymbolXmlRaw = xml };
            if (values != null)
            {
                read.ValuesRaw.AddRange(values);
            }

            if (symbols != null)
            {
                read.SymbolsRaw.AddRange(symbols);
            }

            return read;
        }

        if (errors.Count > 0)
        {
            scope.Gaps.Add(
                GapKind.ToolError,
                "model_annotation",
                record.Id,
                $"No call answered for frame {frame.ToString(CultureInfo.InvariantCulture)} of the "
                + "GTol (GetFrameValues, GetFrameSymbols3, GetFrame and GetSymbolXml), so the frame "
                + "was not recorded.",
                string.Join("; ", errors));
        }

        return null;
    }

    /// <summary>
    /// One frame read whose failure is expected for one GTol format: the error is kept for the
    /// frame's gap and the answer is null. A guard refusal or an open circuit is not a format.
    /// </summary>
    private static T? OptionalFrameRead<T>(List<string> errors, Func<T?> read)
        where T : class
    {
        try
        {
            return read();
        }
        catch (CircuitOpenError)
        {
            throw;
        }
        catch (MutatingCallError)
        {
            throw;
        }
        catch (Exception ex)
        {
            errors.Add(GapCollector.Describe(ex));
            return null;
        }
    }
}
