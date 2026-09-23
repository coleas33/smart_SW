using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 010 T090. The <c>tolerance</c> phase: every part document's feature dimensions with
/// their tolerances, and its geometric tolerances and datum tags (schema 1.5.0, FR-022,
/// contracts/tolerances.md section 2), read through two seams -
/// <see cref="IDimensionToleranceReader"/> and <see cref="IModelAnnotationReader"/> - so every
/// decision is tested with no seat. The interop readers are the seat's to validate (T105).
///
/// The rules pinned below:
///
///   * <b>Verbatim, in system units.</b> A nominal is metres or radians by the dimension's
///     type; a tolerance's limits are the signed deviations SOLIDWORKS reports, in the same
///     unit; the raw type numbers are kept beside the names given to them.
///   * <b>Every dimension, toleranced or not.</b> A tolerance binds to a hole only through the
///     unique dimension of its value (research R2.18), so an untoleranced dimension is evidence.
///   * <b>Null is never "none".</b> A tolerance type the IR's kinds cannot express is a null
///     tolerance with its raw type kept; kind "none" is SOLIDWORKS saying there is none.
///   * <b>One gap per failed read, never an open circuit.</b> Each read of one dimension or one
///     annotation is optional: a failure is a gap on that item and the phase carries on.
///   * <b>Once per part document</b>, as the feature trees are read.
/// </summary>
public class ToleranceDumperTests
{
    private const string AssemblyPath = @"C:\Fictional\cover-assy\cover-assy.SLDASM";
    private const string PlatePath = @"C:\Fictional\cover-assy\plate.SLDPRT";
    private const string PinPath = @"C:\Fictional\cover-assy\pin.SLDPRT";

    private readonly FakeDimensionToleranceReader _dimensions = new FakeDimensionToleranceReader();
    private readonly FakeModelAnnotationReader _annotations = new FakeModelAnnotationReader();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();
    private DumpScope _scope = NewScope(Array.Empty<ComponentNode>());

    public ToleranceDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- dimensions --------------------------------------------------------------

    [Fact]
    public void Dump_ADiameterWithABilateralTolerance_IsAModelDimensionWithItsLimitsAndItsReference()
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension
        {
            FullName = "D1@Sketch1@plate.SLDPRT",
            Type2 = 6,
            Value = 0.01,
            Tolerance = new FakeTolerance { Type = 2, Min = -0.00001, Max = 0.000015 },
            PersistRef = "RGltMQ==",
        }));

        ToleranceDumpResult result = Dump(Plate("plate-1"));

        ModelDimension dimension = Assert.Single(result.Dimensions);
        Assert.Equal("mdm:0001", dimension.Id);
        Assert.Equal(DocumentIds.For(PlatePath), dimension.DocumentId);
        Assert.Equal("Sketch1", dimension.FeatureName);
        Assert.Equal("D1@Sketch1@plate.SLDPRT", dimension.Name);
        Assert.Equal(ModelDimensionType.Diameter, dimension.DimensionType);
        Assert.Equal(6, dimension.DimensionTypeRaw);
        Assert.Equal(0.01, dimension.Nominal.Value);
        Assert.Equal("m", dimension.Nominal.Unit);
        Assert.Equal("RGltMQ==", dimension.PersistRef);
        Assert.Equal("doc:scope", dimension.PersistRefScope);

        Tolerance tolerance = dimension.Tolerance!;
        Assert.Equal(ToleranceKind.Bilateral, tolerance.Kind);
        Assert.Equal(0.000015, tolerance.Upper!.Value);
        Assert.Equal(-0.00001, tolerance.Lower!.Value);
        Assert.Equal("m", tolerance.Upper.Unit);
        Assert.Equal(2, dimension.ToleranceTypeRaw);
        Assert.Equal(DocumentIds.For(PlatePath), tolerance.Source.DocumentId);
        Assert.Equal("D1@Sketch1@plate.SLDPRT", tolerance.Source.Annotation);
        Assert.Equal("RGltMQ==", tolerance.Source.PersistRef);
        Assert.Null(dimension.FitHoleClass);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Theory]
    [InlineData(0, ToleranceKind.None, false)]
    [InlineData(1, ToleranceKind.Basic, false)]
    [InlineData(2, ToleranceKind.Bilateral, true)]
    [InlineData(3, ToleranceKind.Bilateral, true)]
    [InlineData(4, ToleranceKind.Symmetric, true)]
    [InlineData(8, ToleranceKind.Bilateral, true)]
    [InlineData(9, ToleranceKind.Bilateral, true)]
    public void Dump_EveryToleranceTypeTheIrCanExpress_MapsToItsKind(int type, ToleranceKind kind, bool limits)
    {
        // swTolType_e (reflected): NONE 0, BASIC 1, BILAT 2, LIMIT 3, SYMMETRIC 4, FITWITHTOL 8,
        // FITTOLONLY 9. LIMIT is "bilateral" because GetMinValue2/GetMaxValue2 report the
        // deviations whatever the display, and the IR's "limits" means the two sizes themselves.
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension
        {
            Tolerance = new FakeTolerance { Type = type, Min = -0.00002, Max = 0.00002 },
        }));

        ModelDimension dimension = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Equal(kind, dimension.Tolerance!.Kind);
        Assert.Equal(type, dimension.ToleranceTypeRaw);
        if (limits)
        {
            Assert.Equal(0.00002, dimension.Tolerance.Upper!.Value);
            Assert.Equal(-0.00002, dimension.Tolerance.Lower!.Value);
        }
        else
        {
            Assert.Null(dimension.Tolerance.Upper);
            Assert.Null(dimension.Tolerance.Lower);
            Assert.DoesNotContain("GetMinValue2", _observer.Members);
            Assert.DoesNotContain("GetMaxValue2", _observer.Members);
        }
    }

    [Theory]
    [InlineData(5)]
    [InlineData(6)]
    [InlineData(10)]
    [InlineData(11)]
    [InlineData(42)]
    public void Dump_AToleranceTypeTheIrCannotExpress_IsNullWithItsTypeKept(int type)
    {
        // MIN 5, MAX 6, BLOCK 10, GENERAL 11, and anything unknown: null is "no IR kind", never
        // "none", which would say SOLIDWORKS reported no tolerance at all.
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension
        {
            Tolerance = new FakeTolerance { Type = type },
        }));

        ModelDimension dimension = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Null(dimension.Tolerance);
        Assert.Equal(type, dimension.ToleranceTypeRaw);
        Assert.Null(dimension.FitHoleClass);
        Assert.DoesNotContain("GetHoleFitValue", _observer.Members);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_AFitTolerance_KeepsBothClassesAndNoNumbers()
    {
        // swTolFIT (7) names the classes and no numbers: the tolerance is null, the classes are
        // recorded verbatim, and the ISO 286 table is Python's to apply.
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension
        {
            Tolerance = new FakeTolerance { Type = 7, HoleFit = "H7", ShaftFit = "g6", Min = null, Max = null },
        }));

        ModelDimension dimension = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Null(dimension.Tolerance);
        Assert.Equal(7, dimension.ToleranceTypeRaw);
        Assert.Equal("H7", dimension.FitHoleClass);
        Assert.Equal("g6", dimension.FitShaftClass);
    }

    [Fact]
    public void Dump_AFitWithItsTolerance_KeepsTheClassesAndTheDeviations()
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension
        {
            Tolerance = new FakeTolerance { Type = 8, HoleFit = "H7", ShaftFit = " ", Min = 0.0, Max = 0.000015 },
        }));

        ModelDimension dimension = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Equal(ToleranceKind.Bilateral, dimension.Tolerance!.Kind);
        Assert.Equal("H7", dimension.FitHoleClass);
        Assert.Null(dimension.FitShaftClass);
    }

    [Theory]
    [InlineData(6, ModelDimensionType.Diameter, "m")]
    [InlineData(5, ModelDimensionType.Radius, "m")]
    [InlineData(3, ModelDimensionType.Angular, "rad")]
    [InlineData(16, ModelDimensionType.Angular, "rad")]
    [InlineData(1, ModelDimensionType.Linear, "m")]
    [InlineData(2, ModelDimensionType.Linear, "m")]
    [InlineData(7, ModelDimensionType.Linear, "m")]
    [InlineData(8, ModelDimensionType.Linear, "m")]
    [InlineData(9, ModelDimensionType.Linear, "m")]
    [InlineData(11, ModelDimensionType.Linear, "m")]
    [InlineData(12, ModelDimensionType.Linear, "m")]
    [InlineData(4, ModelDimensionType.Other, "m")]
    [InlineData(10, ModelDimensionType.Other, "m")]
    [InlineData(14, ModelDimensionType.Other, "m")]
    [InlineData(15, ModelDimensionType.Other, "m")]
    public void Dump_TheDimensionTypeNamesTheKindAndDecidesTheUnit(
        int type2, ModelDimensionType expected, string unit)
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension
        {
            Type2 = type2,
            Value = 1.25,
            Tolerance = new FakeTolerance { Type = 4, Min = -0.001, Max = 0.001 },
        }));

        ModelDimension dimension = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Equal(expected, dimension.DimensionType);
        Assert.Equal(type2, dimension.DimensionTypeRaw);
        Assert.Equal(unit, dimension.Nominal.Unit);
        Assert.Equal(unit, dimension.Tolerance!.Upper!.Unit);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(13)]
    public void Dump_ADimensionWhoseTypeDecidesNoUnit_IsLeftOutWithAGap(int type2)
    {
        // Unknown (0) and scalar (13): a number with a guessed unit is worse than no number,
        // the rule DrawingDumper.UnitOf already applies to drawing dimensions.
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension { Type2 = type2 }));

        Assert.Empty(Dump(Plate("plate-1")).Dimensions);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_dimension", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains(type2.ToString(), gap.Reason, StringComparison.Ordinal);
        Assert.Contains("D1@Sketch1@part.SLDPRT", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AnUntolerancedDimension_IsStillRecorded()
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Boss-Extrude1", new FakeDimension
        {
            FullName = "D1@Boss-Extrude1@plate.SLDPRT",
            Type2 = 2,
            Value = 0.006,
            Tolerance = new FakeTolerance { Type = 0 },
        }));

        ModelDimension dimension = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Equal(ToleranceKind.None, dimension.Tolerance!.Kind);
        Assert.Equal(0.006, dimension.Nominal.Value);
    }

    [Fact]
    public void Dump_TheSameDimensionSightedTwice_IsRecordedOnce()
    {
        // A sketch's dimension can be sighted from the sketch and from the feature that absorbed
        // it; FullName is unique in a document, so it decides.
        var dimension = new FakeDimension { FullName = "D1@Sketch1@plate.SLDPRT" };
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        plate.Dimensions.Add(("Cut-Extrude1", dimension));
        plate.Dimensions.Add(("Sketch1", dimension));

        ModelDimension recorded = Assert.Single(Dump(Plate("plate-1")).Dimensions);
        Assert.Equal("Cut-Extrude1", recorded.FeatureName);
    }

    [Fact]
    public void Dump_ADisplayDimensionWithNoDimension_IsLeftOutWithAGap()
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension { HasDimension = false }));

        Assert.Empty(Dump(Plate("plate-1")).Dimensions);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_dimension", gap.EntityKind);
        Assert.Contains("Sketch1", gap.Reason, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("  ")]
    public void Dump_ADimensionWithNoName_IsLeftOutWithAGap(string? fullName)
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension { FullName = fullName }));

        Assert.Empty(Dump(Plate("plate-1")).Dimensions);
        Assert.Equal("model_dimension", Assert.Single(_scope.Gaps.Gaps).EntityKind);
    }

    [Fact]
    public void Dump_ADimensionWithNoValue_IsLeftOutWithAGap()
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension { Value = null }));

        Assert.Empty(Dump(Plate("plate-1")).Dimensions);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_dimension", gap.EntityKind);
        Assert.Contains("D1@Sketch1@part.SLDPRT", gap.Reason, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("Dimension")]
    [InlineData("FullName")]
    [InlineData("DimensionType")]
    [InlineData("SystemValue")]
    public void Dump_AnIdentityReadThatThrows_LeavesThatDimensionOutWithOneGap(string member)
    {
        var failing = new FakeDimension { FullName = "D1@Sketch1@plate.SLDPRT" };
        failing.Throwing.Add(member);
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        plate.Dimensions.Add(("Sketch1", failing));
        plate.Dimensions.Add(("Sketch2", new FakeDimension { FullName = "D1@Sketch2@plate.SLDPRT" }));

        ModelDimension survivor = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Equal("D1@Sketch2@plate.SLDPRT", survivor.Name);
        Assert.Equal("mdm:0001", survivor.Id);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_dimension", gap.EntityKind);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(member + " did not answer", gap.Error!, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("Tolerance")]
    [InlineData("ToleranceType")]
    [InlineData("ToleranceMin")]
    [InlineData("ToleranceMax")]
    public void Dump_AToleranceReadThatThrows_KeepsTheDimensionWithNoToleranceAndOneGap(string member)
    {
        var tolerance = new FakeTolerance { Type = 8, HoleFit = "H7" };
        tolerance.Throwing.Add(member);
        var dimension = new FakeDimension { Tolerance = tolerance };
        if (member == "Tolerance")
        {
            dimension.Throwing.Add(member);
        }

        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", dimension));

        ModelDimension recorded = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        // The whole tolerance block is one reading: a part of it is not recorded as the whole.
        Assert.Null(recorded.Tolerance);
        Assert.Null(recorded.ToleranceTypeRaw);
        Assert.Null(recorded.FitHoleClass);
        Assert.Null(recorded.FitShaftClass);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_dimension", gap.EntityKind);
        Assert.Equal(recorded.Id, gap.EntityId);
        Assert.Contains("tolerance", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_ADimensionWithNoToleranceObject_KeepsTheDimensionAndSaysSo()
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension { Tolerance = null }));

        ModelDimension recorded = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Null(recorded.Tolerance);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_dimension", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
    }

    [Fact]
    public void Dump_ALimitReportedNotValidForItsType_IsANullLimitAndAGap()
    {
        // Never a guessed zero: limits_mm refuses a bilateral tolerance with a missing side, so
        // the check reading it is unresolved.
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension
        {
            Tolerance = new FakeTolerance { Type = 2, Min = null, Max = 0.00002 },
        }));

        ModelDimension recorded = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Equal(ToleranceKind.Bilateral, recorded.Tolerance!.Kind);
        Assert.Null(recorded.Tolerance.Lower);
        Assert.Equal(0.00002, recorded.Tolerance.Upper!.Value);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_dimension", gap.EntityKind);
        Assert.Contains("GetMinValue2", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_ADimensionWithNoPersistentReference_IsKeptAndCitedByName()
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension { PersistRef = null }));

        ModelDimension recorded = Assert.Single(Dump(Plate("plate-1")).Dimensions);

        Assert.Null(recorded.PersistRef);
        Assert.Null(recorded.PersistRefScope);
        Assert.Null(recorded.Tolerance!.Source.PersistRef);
        Assert.Equal(recorded.Name, recorded.Tolerance.Source.Annotation);
        Assert.Equal("model_dimension", Assert.Single(_scope.Gaps.Gaps).EntityKind);
    }

    [Fact]
    public void Dump_DimensionReadsThatFail_NeverOpenTheCircuit()
    {
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        for (int i = 1; i <= 5; i++)
        {
            var dimension = new FakeDimension { FullName = $"D{i}@Sketch1@plate.SLDPRT" };
            dimension.Throwing.Add("SystemValue");
            plate.Dimensions.Add(("Sketch1", dimension));
        }

        Assert.Empty(Dump(Plate("plate-1")).Dimensions);

        Assert.Equal(5, _scope.Gaps.Count);
        Assert.False(_gate.Breaker.IsOpen);
    }

    // ---- annotations -------------------------------------------------------------

    [Fact]
    public void Dump_AGtolInThePre2022Format_KeepsEveryFrameVerbatimAndItsFaces()
    {
        var gtol = new FakeAnnotation { Type = 5, IsDimXpert = true, DatumIdentifier = "C" };
        gtol.Frames.Add(new FakeFrame
        {
            Values = new List<string> { "0.05", "", "A", "B", "" },
            Symbols = new List<string> { "<GTOL-POSI>", "<MOD-MMC>", "", "", "", "" },
        });
        gtol.Frames.Add(new FakeFrame { Values = new List<string> { "", "", "", "", "" }, Symbols = new List<string>() });
        gtol.AttachedFaces.Add("RmFjZTE=");
        _dimensions.Add(PlatePath).Annotations.Add(gtol);

        ModelAnnotation annotation = Assert.Single(Dump(Plate("plate-1")).Annotations);

        Assert.Equal("man:0001", annotation.Id);
        Assert.Equal(DocumentIds.For(PlatePath), annotation.DocumentId);
        Assert.Equal(ModelAnnotationKind.Gtol, annotation.Kind);
        Assert.Equal(2, annotation.Frames.Count);
        Assert.Equal(1, annotation.Frames[0].Number);
        Assert.Equal(new[] { "0.05", "", "A", "B", "" }, annotation.Frames[0].ValuesRaw);
        Assert.Equal(new[] { "<GTOL-POSI>", "<MOD-MMC>", "", "", "", "" }, annotation.Frames[0].SymbolsRaw);
        Assert.Null(annotation.Frames[0].SymbolXmlRaw);
        Assert.Equal(2, annotation.Frames[1].Number);
        Assert.Equal("C", annotation.DatumIdentifierRaw);
        Assert.True(annotation.IsDimXpert);
        Assert.Equal(new[] { "RmFjZTE=" }, annotation.AttachedPersistRefs);
        Assert.Equal("QW5uMQ==", annotation.PersistRef);
        Assert.Equal("doc:scope", annotation.PersistRefScope);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_AGtolInThe2022Format_KeepsTheFrameXmlWithNoGap()
    {
        // The pre-2022 calls are "valid only if this Gtol was created before SOLIDWORKS 2022":
        // one that throws beside an answering GetSymbolXml is the expected shape, not a gap.
        var gtol = new FakeAnnotation { Type = 5 };
        var frame = new FakeFrame { Xml = "<GTolFrame/>" };
        frame.Throwing.Add("FrameValues");
        frame.Throwing.Add("FrameSymbols");
        gtol.Frames.Add(frame);
        _dimensions.Add(PlatePath).Annotations.Add(gtol);

        ModelAnnotation annotation = Assert.Single(Dump(Plate("plate-1")).Annotations);

        GtolFrame recorded = Assert.Single(annotation.Frames);
        Assert.Equal("<GTolFrame/>", recorded.SymbolXmlRaw);
        Assert.Empty(recorded.ValuesRaw);
        Assert.Empty(recorded.SymbolsRaw);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_AFrameNoCallAnswers_IsLeftOutWithOneGapNamingItsErrors()
    {
        var gtol = new FakeAnnotation { Type = 5 };
        gtol.Frames.Add(new FakeFrame { Values = new List<string> { "0.1", "", "", "", "" } });
        var dead = new FakeFrame();
        dead.Throwing.Add("FrameValues");
        dead.Throwing.Add("FrameSymbols");
        dead.Throwing.Add("FrameXml");
        gtol.Frames.Add(dead);
        _dimensions.Add(PlatePath).Annotations.Add(gtol);

        ModelAnnotation annotation = Assert.Single(Dump(Plate("plate-1")).Annotations);

        Assert.Equal(1, Assert.Single(annotation.Frames).Number);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_annotation", gap.EntityKind);
        Assert.Equal(annotation.Id, gap.EntityId);
        Assert.Contains("frame 2", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("FrameValues of frame 2 did not answer", gap.Error!, StringComparison.Ordinal);
        Assert.Contains("FrameXml of frame 2 did not answer", gap.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AnEmptyFrameThatAnsweredNothingAndThrewNothing_IsLeftOutSilently()
    {
        // A GTol stores at least two frames and may leave one empty; an empty stored frame is
        // nothing to record and nothing failed.
        var gtol = new FakeAnnotation { Type = 5 };
        gtol.Frames.Add(new FakeFrame { Values = new List<string> { "0.1", "", "", "", "" } });
        gtol.Frames.Add(new FakeFrame());
        _dimensions.Add(PlatePath).Annotations.Add(gtol);

        ModelAnnotation annotation = Assert.Single(Dump(Plate("plate-1")).Annotations);

        Assert.Single(annotation.Frames);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_ADatumTag_KeepsItsLabelAndReadsNoFrame()
    {
        var datum = new FakeAnnotation { Type = 2, Label = "A" };
        datum.AttachedFaces.Add("RmFjZTI=");
        _dimensions.Add(PlatePath).Annotations.Add(datum);

        ModelAnnotation annotation = Assert.Single(Dump(Plate("plate-1")).Annotations);

        Assert.Equal(ModelAnnotationKind.Datum, annotation.Kind);
        Assert.Equal("A", annotation.Label);
        Assert.Empty(annotation.Frames);
        Assert.Null(annotation.DatumIdentifierRaw);
        Assert.Equal(new[] { "RmFjZTI=" }, annotation.AttachedPersistRefs);
        Assert.DoesNotContain("GetFrameCount", _observer.Members);
    }

    [Theory]
    [InlineData(1)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(6)]
    [InlineData(7)]
    public void Dump_AnAnnotationThatIsNeitherAGtolNorADatumTag_IsNotRecorded(int type)
    {
        // swAnnotationType_e (reflected): cosmetic thread 1, datum target 3, display dimension 4,
        // note 6, surface finish 7. Not a tolerance source here, and not a gap either.
        _dimensions.Add(PlatePath).Annotations.Add(new FakeAnnotation { Type = type });

        Assert.Empty(Dump(Plate("plate-1")).Annotations);
        Assert.Empty(_scope.Gaps.Gaps);
        Assert.DoesNotContain("GetSpecificAnnotation", _observer.Members);
    }

    [Fact]
    public void Dump_AnAnnotationWithNoSpecificObject_IsLeftOutWithAGap()
    {
        _dimensions.Add(PlatePath).Annotations.Add(new FakeAnnotation { Type = 5, HasSpecific = false });

        Assert.Empty(Dump(Plate("plate-1")).Annotations);
        Assert.Equal("model_annotation", Assert.Single(_scope.Gaps.Gaps).EntityKind);
    }

    [Theory]
    [InlineData("IsDimXpert")]
    [InlineData("AttachedFacePersistRefs")]
    [InlineData("DatumIdentifier")]
    [InlineData("PersistRef")]
    public void Dump_AnOptionalAnnotationReadThatThrows_KeepsTheAnnotationWithOneGap(string member)
    {
        var gtol = new FakeAnnotation { Type = 5, IsDimXpert = true, DatumIdentifier = "C" };
        gtol.Frames.Add(new FakeFrame { Values = new List<string> { "0.05", "", "A", "", "" } });
        gtol.AttachedFaces.Add("RmFjZTE=");
        gtol.Throwing.Add(member);
        _dimensions.Add(PlatePath).Annotations.Add(gtol);

        ModelAnnotation annotation = Assert.Single(Dump(Plate("plate-1")).Annotations);

        Assert.Single(annotation.Frames);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_annotation", gap.EntityKind);
        Assert.Equal(annotation.Id, gap.EntityId);
        Assert.Contains(member + " did not answer", gap.Error!, StringComparison.Ordinal);
        switch (member)
        {
            case "IsDimXpert":
                Assert.Null(annotation.IsDimXpert);
                break;
            case "AttachedFacePersistRefs":
                Assert.Empty(annotation.AttachedPersistRefs);
                break;
            case "DatumIdentifier":
                Assert.Null(annotation.DatumIdentifierRaw);
                break;
            default:
                Assert.Null(annotation.PersistRef);
                break;
        }
    }

    [Theory]
    [InlineData("AnnotationType")]
    [InlineData("Specific")]
    [InlineData("FrameCount")]
    public void Dump_AnIdentityAnnotationReadThatThrows_LeavesItOutWithOneGap(string member)
    {
        var gtol = new FakeAnnotation { Type = 5 };
        gtol.Throwing.Add(member);
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        plate.Annotations.Add(gtol);
        plate.Annotations.Add(new FakeAnnotation { Type = 2, Label = "B" });

        ModelAnnotation survivor = Assert.Single(Dump(Plate("plate-1")).Annotations);

        Assert.Equal("B", survivor.Label);
        Assert.Equal("man:0001", survivor.Id);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("model_annotation", gap.EntityKind);
        Assert.Contains(member + " did not answer", gap.Error!, StringComparison.Ordinal);
    }

    // ---- documents ---------------------------------------------------------------

    [Fact]
    public void Dump_EveryPartDocumentOnce_AndNoAssembly()
    {
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        plate.Dimensions.Add(("Sketch1", new FakeDimension { FullName = "D1@Sketch1@plate.SLDPRT" }));
        FakeToleranceDocument pin = _dimensions.Add(PinPath);
        pin.Dimensions.Add(("Revolve1", new FakeDimension { FullName = "D1@Revolve1@pin.SLDPRT" }));
        pin.Annotations.Add(new FakeAnnotation { Type = 2, Label = "A" });
        _dimensions.Add(AssemblyPath).Dimensions.Add(("Sketch1", new FakeDimension()));

        ToleranceDumpResult result = Dump(Root(), Plate("plate-1"), Part("pin-1", PinPath), Part("pin-2", PinPath));

        Assert.Equal(new[] { "mdm:0001", "mdm:0002" }, result.Dimensions.Select(d => d.Id));
        Assert.Equal(
            new[] { DocumentIds.For(PlatePath), DocumentIds.For(PinPath) },
            result.Dimensions.Select(d => d.DocumentId));
        Assert.Equal("man:0001", Assert.Single(result.Annotations).Id);
        Assert.Equal(1, _dimensions.Walks[PinPath]);
        Assert.False(_dimensions.Walks.ContainsKey(AssemblyPath));
    }

    [Theory]
    [InlineData(SuppressionState.Lightweight)]
    [InlineData(SuppressionState.Suppressed)]
    public void Dump_AnUnresolvedComponent_IsNotReadAndSaysSo(SuppressionState state)
    {
        _dimensions.Add(PlatePath).Dimensions.Add(("Sketch1", new FakeDimension()));
        ComponentNode plate = Plate("plate-1");
        plate.Suppression = state;

        ToleranceDumpResult result = Dump(plate);

        Assert.Empty(result.Dimensions);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("tolerance", gap.EntityKind);
        Assert.Equal("cmp:0001", gap.EntityId);
        Assert.Contains(PackageSerializer.EnumToJsonName(state), gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AnUnresolvedInstanceDoesNotStopAResolvedOneOfTheSamePart()
    {
        _dimensions.Add(PinPath).Dimensions.Add(("Revolve1", new FakeDimension()));
        ComponentNode first = Part("pin-1", PinPath);
        first.Suppression = SuppressionState.Lightweight;

        ToleranceDumpResult result = Dump(first, Part("pin-2", PinPath));

        Assert.Single(result.Dimensions);
    }

    [Fact]
    public void Dump_APartWithNoLoadedDocument_IsAGap()
    {
        ToleranceDumpResult result = Dump(Plate("plate-1"));

        Assert.Empty(result.Dimensions);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("tolerance", gap.EntityKind);
        Assert.Contains("no loaded model document", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AWalkThatFails_IsOneGapAndTheAnnotationsAreStillRead()
    {
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        plate.WalkThrows = true;
        plate.Annotations.Add(new FakeAnnotation { Type = 2, Label = "A" });

        ToleranceDumpResult result = Dump(Plate("plate-1"));

        Assert.Empty(result.Dimensions);
        Assert.Single(result.Annotations);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("tolerance", gap.EntityKind);
        Assert.Equal(DocumentIds.For(PlatePath), gap.EntityId);
    }

    [Fact]
    public void Dump_GetAnnotationsThatFails_IsOneGapAndTheDimensionsStand()
    {
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        plate.AnnotationsThrow = true;
        plate.Dimensions.Add(("Sketch1", new FakeDimension()));

        ToleranceDumpResult result = Dump(Plate("plate-1"));

        Assert.Single(result.Dimensions);
        Assert.Empty(result.Annotations);
        Assert.Equal("tolerance", Assert.Single(_scope.Gaps.Gaps).EntityKind);
    }

    [Fact]
    public void Dump_GatesEveryReadUnderItsInteropMemberName()
    {
        var gtol = new FakeAnnotation { Type = 5 };
        gtol.Frames.Add(new FakeFrame { Values = new List<string> { "0.1", "", "", "", "" } });
        FakeToleranceDocument plate = _dimensions.Add(PlatePath);
        plate.Dimensions.Add(("Sketch1", new FakeDimension()));
        plate.Annotations.Add(gtol);

        Dump(Plate("plate-1"));

        // The walk, the persistent references, the frame XML and the attached faces span
        // several members each and are gated inside the interop readers.
        Assert.Equal(
            new[]
            {
                "GetModelDoc2", "GetDimension2", "FullName", "Type2", "GetSystemValue3",
                "Tolerance", "DimensionTolerance.Type", "GetMinValue2", "GetMaxValue2",
                "GetAnnotations", "Annotation.GetType", "GetSpecificAnnotation", "GetFrameCount",
                "IsDimXpert", "GetFrameValues", "GetFrameSymbols3", "GetDatumIdentifier",
            },
            _observer.Members);
    }

    [Fact]
    public void Constructor_NullArguments_Throw()
    {
        Assert.Throws<ArgumentNullException>(() => new ToleranceDumper(null!, _dimensions, _annotations));
        Assert.Throws<ArgumentNullException>(() => new ToleranceDumper(_gate, null!, _annotations));
        Assert.Throws<ArgumentNullException>(() => new ToleranceDumper(_gate, _dimensions, null!));
        Assert.Throws<ArgumentNullException>(() => new ToleranceDumper(_gate, _dimensions, _annotations).Dump(null!));
    }

    // ---- harness -----------------------------------------------------------------

    private ToleranceDumpResult Dump(params ComponentNode[] nodes)
    {
        _scope = NewScope(nodes);
        return new ToleranceDumper(_gate, _dimensions, _annotations).Dump(_scope);
    }

    private static DumpScope NewScope(ComponentNode[] nodes)
    {
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = AssemblyPath,
            RootDocumentKind = DocumentKind.Assembly,
            DesignName = "cover-assy",
            ActiveConfiguration = "Default",
        };

        tree.Nodes.AddRange(nodes);
        var scope = new DumpScope(new GapCollector(), new DumpOptions { OutputDirectory = "out" }, tree);

        var ids = new IdAllocator("cmp");
        foreach (ComponentNode node in nodes)
        {
            scope.AddComponent(ids.Next(), scope.DocumentId(node.DocumentPath), node);
        }

        return scope;
    }

    private static ComponentNode Root() => new ComponentNode
    {
        Key = "cover-assy-1",
        Name = "cover-assy-1",
        DocumentPath = AssemblyPath,
        DocumentKind = DocumentKind.Assembly,
        ReferencedConfiguration = "Default",
        Suppression = SuppressionState.Resolved,
        Handle = new object(),
    };

    private static ComponentNode Plate(string key) => Part(key, PlatePath);

    private static ComponentNode Part(string key, string path) => new ComponentNode
    {
        Key = key,
        ParentKey = "cover-assy-1",
        Name = key,
        DocumentPath = path,
        DocumentKind = DocumentKind.Part,
        ReferencedConfiguration = "Default",
        Suppression = SuppressionState.Resolved,
        Handle = new object(),
    };
}
