using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 010 T088. What <see cref="HoleDumper"/> writes from one Hole Wizard definition, read
/// through <see cref="IHoleWizardReader"/> so every decision is tested with no seat
/// (research R2.24). The interop implementation, <see cref="SwHoleWizardReader"/>, is the
/// seat's to validate (T104).
///
/// Four rules, each pinned below:
///
///   * <b>Verbatim.</b> Every wizard field is written as the reader returns it, in metres or
///     radians, and nothing is derived. A zero or a negative is "does not apply to this hole
///     type": null, with no gap.
///   * <b>One gap per failed read.</b> A wizard field whose read throws is null plus one
///     <c>hole_wizard</c> gap naming the field, and the other fields are still read.
///   * <b>Nothing else moves.</b> The hole's feature-001 fields are what they were, and
///     <c>thread_depth</c> is still written only for a tapped blind hole.
///   * <b>Only where it applies.</b> <c>HoleFit</c> (a screw clearance fit) is read for
///     counterbore and countersink holes, the types the API documents it for, and
///     <c>ThreadClass</c> for a tapped hole, the only kind with a thread.
/// </summary>
public class HoleWizardReaderTests
{
    private const string HoleId = "hol:0001";
    private const string FeatureName = "Counterbore Hole1";

    /// <summary>The eight wizard reads a counterbore or countersink hole makes, by the member answering each.</summary>
    public static IEnumerable<object[]> WizardMembers() => new[]
    {
        "HoleFit", "ThruHoleDiameter", "TapDrillDiameter", "CounterBoreDiameter",
        "CounterBoreDepth", "CounterSinkDiameter", "CounterSinkAngle", "HeadClearance",
    }.Select(member => new object[] { member });

    private readonly GapCollector _gaps = new GapCollector();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    public HoleWizardReaderTests()
    {
        _gate.Observer = _observer;
    }

    // ---- verbatim, in SOLIDWORKS' units ------------------------------------------

    [Fact]
    public void ReadDefinition_ACounterbore_WritesEveryWizardFieldAsTheReaderReturnsIt()
    {
        Hole hole = Read(new FakeHoleDefinition());

        HoleWizardData wizard = hole.Wizard!;
        Assert.Equal("swScrewClearanceNormal", wizard.FitClassRaw);
        AssertMetres(0.0066, wizard.ThruHoleDiameter);
        AssertMetres(0.011, wizard.CounterboreDiameter);
        AssertMetres(0.0064, wizard.CounterboreDepth);
        AssertMetres(0.0005, wizard.HeadClearance);

        // Fields that do not apply to a counterbore answered zero: null, with no gap.
        Assert.Null(wizard.TapDrillDiameter);
        Assert.Null(wizard.CountersinkDiameter);
        Assert.Null(wizard.CountersinkAngle);
        Assert.Null(wizard.ThreadClassRaw);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadDefinition_ACountersink_WritesItsDiameterAndItsAngleInRadians()
    {
        Hole hole = Read(new FakeHoleDefinition
        {
            HoleType = HoleType.Countersink,
            HoleFit = 0,
            CounterBoreDiameter = 0,
            CounterBoreDepth = 0,
            CounterSinkDiameter = 0.0126,
            CounterSinkAngle = Math.PI / 2,
        });

        HoleWizardData wizard = hole.Wizard!;
        Assert.Equal("swScrewClearanceClose", wizard.FitClassRaw);
        AssertMetres(0.0126, wizard.CountersinkDiameter);
        Assert.NotNull(wizard.CountersinkAngle);
        Assert.Equal(Math.PI / 2, wizard.CountersinkAngle!.Value);
        Assert.Equal(AngleUnit.Rad, wizard.CountersinkAngle.Unit);
        Assert.Null(wizard.CounterboreDiameter);
    }

    [Fact]
    public void ReadDefinition_ATappedBlindHole_WritesTheThreadClassAndTheThreadDepthAndNoFit()
    {
        Hole hole = Read(new FakeHoleDefinition
        {
            HoleType = HoleType.Tapped,
            FastenerSize = "M6x1.0",
            ThreadDepth = 0.012,
            ThreadEndCondition = 0,
            ThreadClass = "6H",
            TapDrillDiameter = 0.005,
            ThruHoleDiameter = 0,
            CounterBoreDiameter = 0,
            CounterBoreDepth = 0,
            HeadClearance = 0,
        });

        Assert.Equal("M6x1.0", hole.ThreadDesignation);
        AssertMetres(0.012, hole.ThreadDepth);
        Assert.Equal("6H", hole.Wizard!.ThreadClassRaw);
        AssertMetres(0.005, hole.Wizard.TapDrillDiameter);

        // A screw clearance fit has no meaning for a tapped hole, and it is not asked.
        Assert.Null(hole.Wizard.FitClassRaw);
        Assert.DoesNotContain("HoleFit", _observer.Members);
    }

    [Fact]
    public void ReadDefinition_AThroughTappedHole_StillLeavesThreadDepthUnknownWithTheHoleGap()
    {
        Hole hole = Read(new FakeHoleDefinition
        {
            HoleType = HoleType.Tapped,
            ThreadDepth = 0.004,
            ThreadEndCondition = 1,
        });

        // Principle I, unchanged: a through-tapped depth would be the material thickness,
        // which the feature does not know.
        Assert.Null(hole.ThreadDepth);
        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("hole", gap.EntityKind);
        Assert.Equal(HoleId, gap.EntityId);
        Assert.Contains("thread end condition 1", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("never derived from the drill depth", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void ReadDefinition_AClearanceHole_ReadsNoFitNoThreadAndNoThreadDepth()
    {
        Hole hole = Read(new FakeHoleDefinition { HoleType = HoleType.Clearance, ThreadDepth = 0.01 });

        Assert.Null(hole.ThreadDesignation);
        Assert.Null(hole.ThreadDepth);
        Assert.Null(hole.Wizard!.FitClassRaw);
        Assert.Null(hole.Wizard.ThreadClassRaw);
        Assert.DoesNotContain("HoleFit", _observer.Members);
        Assert.DoesNotContain("ThreadClass", _observer.Members);
        Assert.DoesNotContain("ThreadDepth", _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadDefinition_ZeroAndNegativeAnswers_AreNullWithoutAGap()
    {
        Hole hole = Read(new FakeHoleDefinition
        {
            ThruHoleDiameter = 0,
            CounterBoreDiameter = -0.011,
            CounterBoreDepth = 0,
            CounterSinkAngle = -1.0,
            HeadClearance = 0,
            ThreadClass = "   ",
        });

        HoleWizardData wizard = hole.Wizard!;
        Assert.Null(wizard.ThruHoleDiameter);
        Assert.Null(wizard.CounterboreDiameter);
        Assert.Null(wizard.CounterboreDepth);
        Assert.Null(wizard.CountersinkAngle);
        Assert.Null(wizard.HeadClearance);
        Assert.Empty(_gaps.Gaps);
    }

    [Theory]
    [InlineData(0, "swScrewClearanceClose")]
    [InlineData(1, "swScrewClearanceNormal")]
    [InlineData(2, "swScrewClearanceLoose")]
    [InlineData(7, "7")]
    [InlineData(-1, "-1")]
    public void HoleFitName_NamesTheClearanceTypeOrKeepsTheNumber(int code, string expected)
    {
        // swWzdHoleScrewClearanceTypes_e, reflected on the 2024 SP5 interop: close 0, normal 1,
        // loose 2. A value the enumeration does not name is kept as its number, never guessed.
        Assert.Equal(expected, HoleDumper.HoleFitName(code));
    }

    // ---- one gap per failed read -------------------------------------------------

    [Theory]
    [MemberData(nameof(WizardMembers))]
    public void ReadDefinition_AWizardReadThatThrows_IsNullPlusOneHoleWizardGapNamingIt(string member)
    {
        var definition = new FakeHoleDefinition
        {
            HoleType = HoleType.Countersink,
            TapDrillDiameter = 0.005,
            CounterSinkDiameter = 0.0126,
            CounterSinkAngle = Math.PI / 2,
        };
        Hole expected = Read(definition, new SwGate(), new GapCollector());

        var reader = new FakeHoleWizardReader(definition);
        reader.Throwing.Add(member);
        Hole hole = NewHole();
        HoleDumper.ReadDefinition(reader, hole, _gate, _gaps);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("hole_wizard", gap.EntityKind);
        Assert.Equal(HoleId, gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(member, gap.Reason, StringComparison.Ordinal);
        Assert.Contains(FeatureName, gap.Reason, StringComparison.Ordinal);
        Assert.Contains(member + " did not answer", gap.Error!, StringComparison.Ordinal);

        // The failed field is null and every other field is what the healthy read wrote.
        string field = WizardField(member);
        var written = WizardFields(hole.Wizard!);
        var healthy = WizardFields(expected.Wizard!);
        Assert.Null(written[field]);
        foreach (string other in healthy.Keys.Where(key => key != field))
        {
            Assert.Equal(healthy[other], written[other]);
        }

        AssertSameFeature001Fields(expected, hole);
    }

    [Fact]
    public void ReadDefinition_AThreadClassReadThatThrows_IsNullPlusOneHoleWizardGap()
    {
        var reader = new FakeHoleWizardReader(new FakeHoleDefinition
        {
            HoleType = HoleType.Tapped,
            ThreadDepth = 0.012,
        });
        reader.Throwing.Add("ThreadClass");
        Hole hole = NewHole();

        HoleDumper.ReadDefinition(reader, hole, _gate, _gaps);

        Assert.Null(hole.Wizard!.ThreadClassRaw);
        AssertMetres(0.012, hole.ThreadDepth);
        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("hole_wizard", gap.EntityKind);
        Assert.Contains("ThreadClass", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void ReadDefinition_EveryWizardReadThrowing_LeavesAnEmptyRecordAndOneGapEach()
    {
        var reader = new FakeHoleWizardReader(new FakeHoleDefinition());
        foreach (object[] member in WizardMembers())
        {
            reader.Throwing.Add((string)member[0]);
        }

        Hole hole = NewHole();
        HoleDumper.ReadDefinition(reader, hole, _gate, _gaps);

        Assert.NotNull(hole.Wizard);
        Assert.All(WizardFields(hole.Wizard!).Values, value => Assert.Null(value));
        Assert.Equal(8, _gaps.Gaps.Count);
        Assert.All(_gaps.Gaps, gap => Assert.Equal("hole_wizard", gap.EntityKind));

        // SOLIDWORKS may refuse a wizard property on every hole of one type. Eight refusals in
        // a row are eight gaps, not an open circuit that would end the dump as a dead session
        // does (SwGate.CallOptional); a dead session still opens it on the next counted call.
        Assert.False(_gate.Breaker.IsOpen);
        Assert.Equal(0, _gate.Breaker.ConsecutiveFailures);
    }

    [Fact]
    public void ReadDefinition_AFeature001ReadThatThrows_StillFailsTheWholeHole()
    {
        // Unchanged: a hole whose size or depth could not be read is not a hole the checks can
        // trust, so the exception reaches ReadHole's "hole" step, which records the gap.
        var reader = new FakeHoleWizardReader(new FakeHoleDefinition());
        reader.Throwing.Add("HoleDepth");

        Assert.Throws<COMException>(() => HoleDumper.ReadDefinition(reader, NewHole(), _gate, _gaps));
    }

    // ---- nothing else moves ------------------------------------------------------

    [Fact]
    public void ReadDefinition_WritesTheFeature001FieldsAsBefore()
    {
        Hole hole = Read(new FakeHoleDefinition
        {
            HoleType = HoleType.Counterbore,
            EndCondition = 1,
            Standard = "swStandardISO",
            FastenerSize = " M6 ",
            HoleDepth = 0.02,
            Diameter = 0.0066,
        });

        Assert.Equal(HoleType.Counterbore, hole.HoleType);
        Assert.Equal(EndCondition.Through, hole.EndCondition);
        Assert.Equal("swStandardISO", hole.Standard);
        Assert.Equal("M6", hole.Size);
        Assert.Null(hole.ThreadDesignation);
        AssertMetres(0.02, hole.HoleDepth);
        AssertMetres(0.0066, hole.Diameter);
        Assert.Null(hole.ThreadDepth);
    }

    [Fact]
    public void ReadDefinition_GatesEveryReadUnderItsInteropMemberName()
    {
        Read(new FakeHoleDefinition());

        // The guard and the gate log see the members SOLIDWORKS names; Standard is two
        // members (Standard2, then the free-text Standard) and SwHoleWizardReader gates both.
        Assert.Equal(
            new[]
            {
                "WizardHole.Type", "WizardHole.EndCondition", "FastenerSize", "HoleDepth",
                "WizardHole.Diameter", "HoleFit", "ThruHoleDiameter", "TapDrillDiameter",
                "CounterBoreDiameter", "CounterBoreDepth", "CounterSinkDiameter",
                "CounterSinkAngle", "HeadClearance",
            },
            _observer.Members);
    }

    [Theory]
    [InlineData(0, EndCondition.Blind)]
    [InlineData(1, EndCondition.Through)]
    [InlineData(2, EndCondition.Through)]
    [InlineData(9, EndCondition.Through)]
    [InlineData(11, EndCondition.Through)]
    [InlineData(3, EndCondition.Unknown)]
    [InlineData(4, EndCondition.Unknown)]
    [InlineData(5, EndCondition.Unknown)]
    [InlineData(6, EndCondition.Unknown)]
    [InlineData(7, EndCondition.Unknown)]
    [InlineData(10, EndCondition.Unknown)]
    [InlineData(-1, EndCondition.Unknown)]
    public void MapEndCondition_ReadsSwEndConditionsByItsReflectedValues(int code, EndCondition expected)
    {
        // swEndConditions_e on 2024 SP5: blind 0, through all 1, through next 2, up to vertex 3,
        // up to surface 4, offset from surface 5, mid plane 6, up to body 7, through all both 9,
        // up to selection 10, up to next 11. The mapping is the one HoleDumper always had.
        Assert.Equal(expected, HoleDumper.MapEndCondition(code));
    }

    [Fact]
    public void ReadDefinition_NullArguments_Throw()
    {
        var reader = new FakeHoleWizardReader(new FakeHoleDefinition());

        Assert.Throws<ArgumentNullException>(() => HoleDumper.ReadDefinition(null!, NewHole(), _gate, _gaps));
        Assert.Throws<ArgumentNullException>(() => HoleDumper.ReadDefinition(reader, null!, _gate, _gaps));
        Assert.Throws<ArgumentNullException>(() => HoleDumper.ReadDefinition(reader, NewHole(), null!, _gaps));
        Assert.Throws<ArgumentNullException>(() => HoleDumper.ReadDefinition(reader, NewHole(), _gate, null!));
    }

    // ---- harness -----------------------------------------------------------------

    private Hole Read(FakeHoleDefinition definition) => Read(definition, _gate, _gaps);

    private static Hole Read(FakeHoleDefinition definition, SwGate gate, GapCollector gaps)
    {
        Hole hole = NewHole();
        HoleDumper.ReadDefinition(new FakeHoleWizardReader(definition), hole, gate, gaps);
        return hole;
    }

    private static Hole NewHole() => new Hole
    {
        Id = HoleId,
        ComponentId = "cmp:0002",
        FeatureName = FeatureName,
        PersistRefScope = "doc:0002",
    };

    private static void AssertMetres(double expected, Quantity? actual)
    {
        Assert.NotNull(actual);
        Assert.Equal(expected, actual!.Value);
        Assert.Equal(LengthUnit.M, actual.Unit);
    }

    /// <summary>The IR field each wizard read writes.</summary>
    private static string WizardField(string member) => member switch
    {
        "HoleFit" => "fit_class_raw",
        "ThruHoleDiameter" => "thru_hole_diameter",
        "TapDrillDiameter" => "tap_drill_diameter",
        "CounterBoreDiameter" => "counterbore_diameter",
        "CounterBoreDepth" => "counterbore_depth",
        "CounterSinkDiameter" => "countersink_diameter",
        "CounterSinkAngle" => "countersink_angle",
        "HeadClearance" => "head_clearance",
        _ => throw new ArgumentOutOfRangeException(nameof(member), member, "not a wizard read"),
    };

    /// <summary>Every wizard field, by IR name, as comparable text (null stays null).</summary>
    private static Dictionary<string, string?> WizardFields(HoleWizardData wizard) =>
        new Dictionary<string, string?>
        {
            ["fit_class_raw"] = wizard.FitClassRaw,
            ["thread_class_raw"] = wizard.ThreadClassRaw,
            ["thru_hole_diameter"] = Text(wizard.ThruHoleDiameter),
            ["tap_drill_diameter"] = Text(wizard.TapDrillDiameter),
            ["counterbore_diameter"] = Text(wizard.CounterboreDiameter),
            ["counterbore_depth"] = Text(wizard.CounterboreDepth),
            ["countersink_diameter"] = Text(wizard.CountersinkDiameter),
            ["countersink_angle"] = wizard.CountersinkAngle == null
                ? null
                : wizard.CountersinkAngle.Value.ToString("R") + " " + wizard.CountersinkAngle.Unit,
            ["head_clearance"] = Text(wizard.HeadClearance),
        };

    private static string? Text(Quantity? quantity) =>
        quantity == null ? null : quantity.Value.ToString("R") + " " + quantity.Unit;

    private static void AssertSameFeature001Fields(Hole expected, Hole actual)
    {
        Assert.Equal(expected.HoleType, actual.HoleType);
        Assert.Equal(expected.Standard, actual.Standard);
        Assert.Equal(expected.Size, actual.Size);
        Assert.Equal(expected.ThreadDesignation, actual.ThreadDesignation);
        Assert.Equal(Text(expected.HoleDepth), Text(actual.HoleDepth));
        Assert.Equal(expected.EndCondition, actual.EndCondition);
        Assert.Equal(Text(expected.Diameter), Text(actual.Diameter));
        Assert.Equal(Text(expected.ThreadDepth), Text(actual.ThreadDepth));
    }
}
