using System;
using System.Collections.Generic;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
// SwReview.Extractor.Measure is a namespace (the remodel geometry), so the IR union type is
// named explicitly, as ToleranceDumper names it.
using IrMeasure = SwReview.Extractor.Ir.Measure;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The six reads of one <c>IDimension</c>'s tolerance, with no interop type in the signature: the
/// part of feature 010's <see cref="IDimensionToleranceReader"/> that a drawing's display
/// dimension is read through too (feature 011, contracts/native-evidence.md section 3), so the
/// model and the drawing read a tolerance through one set of members.
/// </summary>
public interface IDimensionToleranceReads
{
    /// <summary><c>IDimension.Tolerance</c> (<c>IDimensionTolerance</c>); null when it gives none.</summary>
    object? Tolerance(object dimension);

    /// <summary><c>IDimensionTolerance.Type</c> verbatim (<c>swTolType_e</c>).</summary>
    int ToleranceType(object tolerance);

    /// <summary><c>IDimensionTolerance.GetMinValue2</c>'s value; null when it is not valid for the type.</summary>
    double? ToleranceMin(object tolerance);

    /// <summary><c>IDimensionTolerance.GetMaxValue2</c>'s value; null when it is not valid for the type.</summary>
    double? ToleranceMax(object tolerance);

    /// <summary><c>IDimensionTolerance.GetHoleFitValue</c>.</summary>
    string? HoleFitValue(object tolerance);

    /// <summary><c>IDimensionTolerance.GetShaftFitValue</c>.</summary>
    string? ShaftFitValue(object tolerance);
}

/// <summary>What one tolerance read found, before a dumper writes it onto its own record.</summary>
public sealed class DimensionToleranceReading
{
    private DimensionToleranceReading(
        bool missing,
        int typeRaw,
        Tolerance? tolerance,
        string? holeFit,
        string? shaftFit,
        IReadOnlyList<string> invalidLimits)
    {
        Missing = missing;
        TypeRaw = typeRaw;
        Tolerance = tolerance;
        HoleFit = holeFit;
        ShaftFit = shaftFit;
        InvalidLimits = invalidLimits;
    }

    /// <summary>The dimension gave no <c>IDimensionTolerance</c>: nothing else was read.</summary>
    public bool Missing { get; }

    /// <summary><c>swTolType_e</c> verbatim.</summary>
    public int TypeRaw { get; }

    /// <summary>
    /// The IR tolerance, or null for a type the IR's kinds cannot express - never "none"
    /// (<see cref="ToleranceDumper.KindOf"/>).
    /// </summary>
    public Tolerance? Tolerance { get; }

    /// <summary>The hole class, for a fit type only; a blank answer is null.</summary>
    public string? HoleFit { get; }

    /// <summary>The shaft class, for a fit type only; a blank answer is null.</summary>
    public string? ShaftFit { get; }

    /// <summary>The limit reads that reported their value not valid for the type, by member name.</summary>
    public IReadOnlyList<string> InvalidLimits { get; }

    internal static DimensionToleranceReading NoTolerance { get; } = new DimensionToleranceReading(
        true, 0, null, null, null, Array.Empty<string>());

    internal static DimensionToleranceReading Of(
        int typeRaw, Tolerance? tolerance, string? holeFit, string? shaftFit, IReadOnlyList<string> invalidLimits) =>
        new DimensionToleranceReading(false, typeRaw, tolerance, holeFit, shaftFit, invalidLimits);
}

/// <summary>
/// Feature 010's tolerance read and mapping, extracted so the model's <c>tolerance</c> phase and
/// the drawing's display dimensions share one reading of one interop answer (feature 011 T027,
/// "one tolerance mapping"): the type, the fit classes for a fit type, and the two signed
/// deviations for a kind that carries them, each read gated under the name
/// <see cref="ToleranceDumper"/> has always used. Nothing is assigned by the caller until the
/// whole read has answered, so a read that throws leaves no half of a tolerance behind.
/// </summary>
public static class DimensionTolerance
{
    /// <summary>
    /// The tolerance of <paramref name="dimension"/> (an <c>IDimension</c>), its limits in
    /// <paramref name="unit"/>, cited by <paramref name="source"/>.
    /// </summary>
    public static DimensionToleranceReading Read(
        SwGate gate, IDimensionToleranceReads reader, object dimension, SourceRef source, string unit)
    {
        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        if (reader == null)
        {
            throw new ArgumentNullException(nameof(reader));
        }

        if (source == null)
        {
            throw new ArgumentNullException(nameof(source));
        }

        object? tolerance = gate.CallOptional("Tolerance", () => reader.Tolerance(dimension));
        if (tolerance == null)
        {
            return DimensionToleranceReading.NoTolerance;
        }

        int type = gate.CallOptional("DimensionTolerance.Type", () => reader.ToleranceType(tolerance));

        string? holeFit = null;
        string? shaftFit = null;
        if (ToleranceDumper.IsFitType(type))
        {
            holeFit = HoleDumper.Blank(gate.CallOptional("GetHoleFitValue", () => reader.HoleFitValue(tolerance)));
            shaftFit = HoleDumper.Blank(gate.CallOptional("GetShaftFitValue", () => reader.ShaftFitValue(tolerance)));
        }

        ToleranceKind? kind = ToleranceDumper.KindOf(type);
        Tolerance? reading = null;
        var invalid = new List<string>();
        if (kind != null)
        {
            reading = new Tolerance { Kind = kind.Value, Source = source };

            if (kind == ToleranceKind.Bilateral || kind == ToleranceKind.Symmetric)
            {
                double? min = gate.CallOptional("GetMinValue2", () => reader.ToleranceMin(tolerance));
                double? max = gate.CallOptional("GetMaxValue2", () => reader.ToleranceMax(tolerance));
                reading.Lower = min == null ? null : new IrMeasure(min.Value, unit);
                reading.Upper = max == null ? null : new IrMeasure(max.Value, unit);
                if (min == null)
                {
                    invalid.Add("GetMinValue2");
                }

                if (max == null)
                {
                    invalid.Add("GetMaxValue2");
                }
            }
        }

        return DimensionToleranceReading.Of(type, reading, holeFit, shaftFit, invalid);
    }
}
