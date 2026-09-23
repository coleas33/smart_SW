using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// What one Hole Wizard definition answers, in SOLIDWORKS' own units: metres, radians, and the
/// raw integers of <c>swEndConditions_e</c> and <c>swWzdHoleScrewClearanceTypes_e</c>. The
/// defaults are a counterbore for an M6 screw, the case with the most wizard fields.
/// </summary>
internal sealed class FakeHoleDefinition
{
    public HoleType HoleType { get; set; } = HoleType.Counterbore;

    public int EndCondition { get; set; }

    public string? Standard { get; set; } = "swStandardISO";

    public string? FastenerSize { get; set; } = "M6";

    public double HoleDepth { get; set; } = 0.02;

    public double Diameter { get; set; }

    public double ThreadDepth { get; set; }

    public int ThreadEndCondition { get; set; }

    public int HoleFit { get; set; } = 1;

    public string? ThreadClass { get; set; } = string.Empty;

    public double ThruHoleDiameter { get; set; } = 0.0066;

    public double TapDrillDiameter { get; set; }

    public double CounterBoreDiameter { get; set; } = 0.011;

    public double CounterBoreDepth { get; set; } = 0.0064;

    public double CounterSinkDiameter { get; set; }

    public double CounterSinkAngle { get; set; }

    public double HeadClearance { get; set; } = 0.0005;
}

/// <summary>
/// <see cref="IHoleWizardReader"/> over a <see cref="FakeHoleDefinition"/>. A member named in
/// <see cref="Throwing"/> throws a <see cref="COMException"/> when read, as a definition that
/// does not answer would.
/// </summary>
internal sealed class FakeHoleWizardReader : IHoleWizardReader
{
    private readonly FakeHoleDefinition _definition;

    public FakeHoleWizardReader(FakeHoleDefinition definition)
    {
        _definition = definition ?? throw new ArgumentNullException(nameof(definition));
    }

    /// <summary>The members that throw when read, by interface member name.</summary>
    public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);

    /// <summary>Every member read, in order, including the ones that threw.</summary>
    public List<string> Reads { get; } = new List<string>();

    public HoleType HoleType => Answer(nameof(HoleType), _definition.HoleType);

    public int EndCondition => Answer(nameof(EndCondition), _definition.EndCondition);

    public string? Standard => Answer(nameof(Standard), _definition.Standard);

    public string? FastenerSize => Answer(nameof(FastenerSize), _definition.FastenerSize);

    public double HoleDepth => Answer(nameof(HoleDepth), _definition.HoleDepth);

    public double Diameter => Answer(nameof(Diameter), _definition.Diameter);

    public double ThreadDepth => Answer(nameof(ThreadDepth), _definition.ThreadDepth);

    public int ThreadEndCondition => Answer(nameof(ThreadEndCondition), _definition.ThreadEndCondition);

    public int HoleFit => Answer(nameof(HoleFit), _definition.HoleFit);

    public string? ThreadClass => Answer(nameof(ThreadClass), _definition.ThreadClass);

    public double ThruHoleDiameter => Answer(nameof(ThruHoleDiameter), _definition.ThruHoleDiameter);

    public double TapDrillDiameter => Answer(nameof(TapDrillDiameter), _definition.TapDrillDiameter);

    public double CounterBoreDiameter => Answer(nameof(CounterBoreDiameter), _definition.CounterBoreDiameter);

    public double CounterBoreDepth => Answer(nameof(CounterBoreDepth), _definition.CounterBoreDepth);

    public double CounterSinkDiameter => Answer(nameof(CounterSinkDiameter), _definition.CounterSinkDiameter);

    public double CounterSinkAngle => Answer(nameof(CounterSinkAngle), _definition.CounterSinkAngle);

    public double HeadClearance => Answer(nameof(HeadClearance), _definition.HeadClearance);

    private T Answer<T>(string member, T value)
    {
        Reads.Add(member);
        if (Throwing.Contains(member))
        {
            throw new COMException($"{member} did not answer");
        }

        return value;
    }
}
