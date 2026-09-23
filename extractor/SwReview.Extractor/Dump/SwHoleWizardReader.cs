using System;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Feature 010 T089. The SOLIDWORKS side of <see cref="IHoleWizardReader"/>: one
/// <c>IWizardHoleFeatureData2</c>, read and nothing else, so every decision
/// <see cref="HoleDumper"/> makes is testable without a seat (the split
/// <see cref="SwFeatureReader"/> makes for <see cref="FeatureDumper"/>).
///
/// Every property below was reflected on the 2024 SP5 interop (32.5.0.48):
/// <c>HoleFit</c> is an <c>int</c> in <c>swWzdHoleScrewClearanceTypes_e</c> and applies to
/// counterbore and countersink holes; <c>ThreadClass</c> is a string (1B, 2B, 3B for ANSI inch);
/// the diameters, depths and <c>HeadClearance</c> are doubles in metres and
/// <c>CounterSinkAngle</c> a double in radians. Every one is a getter read off the definition
/// <c>GetDefinition</c> returned, without <c>AccessSelections</c>, which rolls the model back and
/// is denied. Their setters are on the read-only denylist (feature 010's table in
/// <c>004-resilient-remodeler/contracts/guard-allowlist.md</c>). What a seat actually answers is
/// T104's to record.
/// </summary>
public sealed class SwHoleWizardReader : IHoleWizardReader
{
    private readonly IWizardHoleFeatureData2 _data;
    private readonly SwGate _gate;

    public SwHoleWizardReader(IWizardHoleFeatureData2 data, SwGate gate)
    {
        _data = data ?? throw new ArgumentNullException(nameof(data));
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
    }

    public HoleType HoleType => MapHoleType(_data.Type);

    public int EndCondition => _data.EndCondition;

    /// <summary>Gates <c>Standard2</c> and the free-text <c>Standard</c> itself: two members.</summary>
    public string? Standard => ReadStandard();

    public string? FastenerSize => _data.FastenerSize;

    public double HoleDepth => _data.HoleDepth;

    public double Diameter => _data.Diameter;

    public double ThreadDepth => _data.ThreadDepth;

    public int ThreadEndCondition => _data.ThreadEndCondition;

    public int HoleFit => _data.HoleFit;

    public string? ThreadClass => _data.ThreadClass;

    public double ThruHoleDiameter => _data.ThruHoleDiameter;

    public double TapDrillDiameter => _data.TapDrillDiameter;

    public double CounterBoreDiameter => _data.CounterBoreDiameter;

    public double CounterBoreDepth => _data.CounterBoreDepth;

    public double CounterSinkDiameter => _data.CounterSinkDiameter;

    public double CounterSinkAngle => _data.CounterSinkAngle;

    public double HeadClearance => _data.HeadClearance;

    /// <summary>
    /// <c>Standard2</c> is an enum; -1 means a copied or custom standard, and then the
    /// free-text <c>Standard</c> is the only answer (research R12).
    /// </summary>
    private string? ReadStandard()
    {
        int standard2 = _gate.Call("Standard2", () => _data.Standard2);
        if (standard2 != -1)
        {
            string? name = Enum.GetName(typeof(swWzdHoleStandards_e), standard2);
            if (!string.IsNullOrEmpty(name))
            {
                return name;
            }
        }

        return HoleDumper.Blank(_gate.Call("WizardHole.Standard", () => _data.Standard));
    }

    /// <summary>
    /// <c>swWzdHoleTypes_e</c> has more than eighty members (every counterbore, countersink
    /// and slot combination). They are classified by the enum member name rather than
    /// listed one by one: the name carries the primary feature, and a member added in a
    /// later service pack still lands in the right bucket instead of silently becoming a
    /// simple hole.
    /// </summary>
    internal static HoleType MapHoleType(int typeCode)
    {
        string? name = Enum.GetName(typeof(swWzdHoleTypes_e), typeCode);
        if (string.IsNullOrEmpty(name))
        {
            return HoleType.Unknown;
        }

        if (name!.IndexOf("Tap", StringComparison.Ordinal) >= 0)
        {
            return HoleType.Tapped;
        }

        if (name.StartsWith("swCounterBore", StringComparison.Ordinal)
            || name.StartsWith("swCounterDrilled", StringComparison.Ordinal))
        {
            return HoleType.Counterbore;
        }

        if (name.StartsWith("swCounterSink", StringComparison.Ordinal)
            || name.StartsWith("swCounterSunk", StringComparison.Ordinal))
        {
            return HoleType.Countersink;
        }

        if (name.StartsWith("swHole", StringComparison.Ordinal)
            || name.StartsWith("swSlot", StringComparison.Ordinal))
        {
            // The wizard's "Hole" type is a clearance hole sized for a named fastener.
            return HoleType.Clearance;
        }

        if (name.StartsWith("swSimple", StringComparison.Ordinal))
        {
            return HoleType.Simple;
        }

        return HoleType.Unknown;
    }
}
