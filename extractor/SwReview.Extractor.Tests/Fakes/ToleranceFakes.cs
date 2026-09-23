using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.Extractor.Dump;
using SwReview.Extractor.PersistRefs;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>One part document as the two tolerance fakes answer for it.</summary>
internal sealed class FakeToleranceDocument
{
    public FakeToleranceDocument(string path)
    {
        Path = path;
    }

    public string Path { get; }

    /// <summary>The display dimensions the walk sights, in order, with the feature owning each.</summary>
    public List<(string Feature, FakeDimension Dimension)> Dimensions { get; } =
        new List<(string Feature, FakeDimension Dimension)>();

    public List<FakeAnnotation> Annotations { get; } = new List<FakeAnnotation>();

    /// <summary>When true the feature-tree walk throws.</summary>
    public bool WalkThrows { get; set; }

    /// <summary>When true GetAnnotations throws.</summary>
    public bool AnnotationsThrow { get; set; }
}

/// <summary>
/// A display dimension and its IDimension in one object. A member named in
/// <see cref="Throwing"/> throws when read, as a dimension that does not answer would.
/// </summary>
internal sealed class FakeDimension
{
    public string? FullName { get; set; } = "D1@Sketch1@part.SLDPRT";

    /// <summary>IDisplayDimension.Type2: 6 is a diameter.</summary>
    public int Type2 { get; set; } = 6;

    /// <summary>GetSystemValue3's number in metres or radians; null when it gave none.</summary>
    public double? Value { get; set; } = 0.01;

    /// <summary>False when GetDimension2 gives no IDimension.</summary>
    public bool HasDimension { get; set; } = true;

    public FakeTolerance? Tolerance { get; set; } = new FakeTolerance();

    public string? PersistRef { get; set; } = "RGltMQ==";

    public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);
}

/// <summary>An IDimensionTolerance: a bilateral +0.015/0 mm by default, in metres.</summary>
internal sealed class FakeTolerance
{
    /// <summary>swTolType_e: 2 is bilateral.</summary>
    public int Type { get; set; } = 2;

    /// <summary>GetMinValue2's value; null when it reported the value not valid for the type.</summary>
    public double? Min { get; set; } = 0.0;

    public double? Max { get; set; } = 0.000015;

    public string? HoleFit { get; set; }

    public string? ShaftFit { get; set; }

    public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);
}

/// <summary>One GTol frame as the two API generations answer for it.</summary>
internal sealed class FakeFrame
{
    /// <summary>GetFrameValues; null when the pre-2022 call answers nothing.</summary>
    public List<string>? Values { get; set; }

    /// <summary>GetFrameSymbols3; null when the pre-2022 call answers nothing.</summary>
    public List<string>? Symbols { get; set; }

    /// <summary>GetFrame(n).GetSymbolXml(); null for a GTol in the pre-2022 format.</summary>
    public string? Xml { get; set; }

    public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);
}

/// <summary>An IAnnotation with its specific GTol or datum tag.</summary>
internal sealed class FakeAnnotation
{
    /// <summary>swAnnotationType_e: 5 is a GTol, 2 a datum tag.</summary>
    public int Type { get; set; } = 5;

    public bool IsDimXpert { get; set; }

    /// <summary>False when GetSpecificAnnotation gives nothing.</summary>
    public bool HasSpecific { get; set; } = true;

    public List<FakeFrame> Frames { get; } = new List<FakeFrame>();

    public string? DatumIdentifier { get; set; }

    public string? Label { get; set; }

    public List<string> AttachedFaces { get; } = new List<string>();

    public string? PersistRef { get; set; } = "QW5uMQ==";

    public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);
}

/// <summary><see cref="IDimensionToleranceReader"/> over <see cref="FakeToleranceDocument"/>s.</summary>
internal sealed class FakeDimensionToleranceReader : IDimensionToleranceReader
{
    private readonly Dictionary<string, FakeToleranceDocument> _documents =
        new Dictionary<string, FakeToleranceDocument>(StringComparer.OrdinalIgnoreCase);

    /// <summary>How many times each document's feature tree was walked.</summary>
    public Dictionary<string, int> Walks { get; } = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

    public FakeToleranceDocument Add(string path)
    {
        var document = new FakeToleranceDocument(path);
        _documents[path] = document;
        return document;
    }

    public object? Document(ScopedComponent component) =>
        _documents.TryGetValue(component.Node.DocumentPath, out FakeToleranceDocument document) ? document : null;

    public IReadOnlyList<DimensionSighting> DisplayDimensions(object document)
    {
        var doc = (FakeToleranceDocument)document;
        Walks[doc.Path] = Walks.TryGetValue(doc.Path, out int count) ? count + 1 : 1;
        if (doc.WalkThrows)
        {
            throw new COMException("the feature tree did not answer");
        }

        return doc.Dimensions.Select(item => new DimensionSighting(item.Feature, item.Dimension)).ToList();
    }

    public object? Dimension(object displayDimension)
    {
        FakeDimension dimension = Throw((FakeDimension)displayDimension, nameof(Dimension));
        return dimension.HasDimension ? dimension : null;
    }

    public int DimensionType(object displayDimension) =>
        Throw((FakeDimension)displayDimension, nameof(DimensionType)).Type2;

    public string? FullName(object dimension) => Throw((FakeDimension)dimension, nameof(FullName)).FullName;

    public double? SystemValue(object dimension) => Throw((FakeDimension)dimension, nameof(SystemValue)).Value;

    public object? Tolerance(object dimension) => Throw((FakeDimension)dimension, nameof(Tolerance)).Tolerance;

    public int ToleranceType(object tolerance) => Throw((FakeTolerance)tolerance, nameof(ToleranceType)).Type;

    public double? ToleranceMin(object tolerance) => Throw((FakeTolerance)tolerance, nameof(ToleranceMin)).Min;

    public double? ToleranceMax(object tolerance) => Throw((FakeTolerance)tolerance, nameof(ToleranceMax)).Max;

    public string? HoleFitValue(object tolerance) => Throw((FakeTolerance)tolerance, nameof(HoleFitValue)).HoleFit;

    public string? ShaftFitValue(object tolerance) => Throw((FakeTolerance)tolerance, nameof(ShaftFitValue)).ShaftFit;

    public ScopedPersistRef? PersistRef(object document, object entity)
    {
        var doc = (FakeToleranceDocument)document;
        string? persistRef = Throw((FakeDimension)entity, nameof(PersistRef)).PersistRef;
        return persistRef == null ? null : new ScopedPersistRef(persistRef, "doc:scope", doc.Path);
    }

    private static FakeDimension Throw(FakeDimension dimension, string member) =>
        dimension.Throwing.Contains(member) ? throw new COMException($"{member} did not answer") : dimension;

    private static FakeTolerance Throw(FakeTolerance tolerance, string member) =>
        tolerance.Throwing.Contains(member) ? throw new COMException($"{member} did not answer") : tolerance;
}

/// <summary><see cref="IModelAnnotationReader"/> over the same <see cref="FakeToleranceDocument"/>s.</summary>
internal sealed class FakeModelAnnotationReader : IModelAnnotationReader
{
    public IReadOnlyList<object> Annotations(object document)
    {
        var doc = (FakeToleranceDocument)document;
        if (doc.AnnotationsThrow)
        {
            throw new COMException("GetAnnotations did not answer");
        }

        return doc.Annotations.Cast<object>().ToList();
    }

    public int AnnotationType(object annotation) => Throw(annotation, nameof(AnnotationType)).Type;

    public bool IsDimXpert(object annotation) => Throw(annotation, nameof(IsDimXpert)).IsDimXpert;

    public object? Specific(object annotation)
    {
        FakeAnnotation fake = Throw(annotation, nameof(Specific));
        return fake.HasSpecific ? fake : null;
    }

    public int FrameCount(object gtol) => Throw(gtol, nameof(FrameCount)).Frames.Count;

    public IReadOnlyList<string>? FrameValues(object gtol, int frame) =>
        Frame(gtol, frame, nameof(FrameValues)).Values;

    public IReadOnlyList<string>? FrameSymbols(object gtol, int frame) =>
        Frame(gtol, frame, nameof(FrameSymbols)).Symbols;

    public string? FrameXml(object gtol, int frame) => Frame(gtol, frame, nameof(FrameXml)).Xml;

    public string? DatumIdentifier(object gtol) => Throw(gtol, nameof(DatumIdentifier)).DatumIdentifier;

    public string? DatumLabel(object datumTag) => Throw(datumTag, nameof(DatumLabel)).Label;

    public IReadOnlyList<string> AttachedFacePersistRefs(object document, object annotation) =>
        Throw(annotation, nameof(AttachedFacePersistRefs)).AttachedFaces;

    public ScopedPersistRef? PersistRef(object document, object annotation)
    {
        var doc = (FakeToleranceDocument)document;
        string? persistRef = Throw(annotation, nameof(PersistRef)).PersistRef;
        return persistRef == null ? null : new ScopedPersistRef(persistRef, "doc:scope", doc.Path);
    }

    private static FakeAnnotation Throw(object annotation, string member)
    {
        var fake = (FakeAnnotation)annotation;
        return fake.Throwing.Contains(member) ? throw new COMException($"{member} did not answer") : fake;
    }

    private static FakeFrame Frame(object gtol, int frame, string member)
    {
        FakeFrame fake = ((FakeAnnotation)gtol).Frames[frame - 1];
        return fake.Throwing.Contains(member) ? throw new COMException($"{member} of frame {frame} did not answer") : fake;
    }
}
