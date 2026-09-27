using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;

namespace SwReview.Extractor.Rms;

/// <summary>
/// <see cref="IMassPropertyReading"/> over a real <c>IMassProperty2</c>: one interop member per
/// interface member, and nothing else (feature 004, T153's amendment; build order lane A). The
/// copy's geometry reading (<see cref="RemodelGeometry.Read"/>, through
/// <see cref="IGeometrySource.CreateMassProperty"/>) and PROBE-8 measure with this one mapping, so
/// the probe calibrates exactly the member sequence the gate relies on, not a probe-only shortcut.
///
/// <b>Ungated on purpose.</b> Every caller gates it from outside: <see cref="RemodelGeometry.Read"/>
/// gates each member under its bare read key, and the probe host wraps it in
/// <see cref="GatedMassPropertyReading"/> under the same bare keys, because the probe executors
/// call it with no gate around them. A gate in here would gate each call twice.
/// </summary>
public sealed class SwMassProperty : IMassPropertyReading
{
    private readonly IMassProperty2 _massProperty;

    public SwMassProperty(IMassProperty2 massProperty)
    {
        _massProperty = massProperty ?? throw new ArgumentNullException(nameof(massProperty));
    }

    /// <inheritdoc />
    public void SetAccuracyLevel(int accuracyLevel) => _massProperty.AccuracyLevel = accuracyLevel;

    /// <inheritdoc />
    public void SetSelectedItems(IReadOnlyList<object> bodies)
    {
        if (bodies == null)
        {
            throw new ArgumentNullException(nameof(bodies));
        }

        // The setter takes a SAFEARRAY: an object[] of its own, in the caller's order.
        _massProperty.SelectedItems = bodies.ToArray();
    }

    /// <inheritdoc />
    public void SetUseSystemUnits(bool useSystemUnits) => _massProperty.UseSystemUnits = useSystemUnits;

    /// <inheritdoc />
    public bool Recalculate() => _massProperty.Recalculate();

    /// <inheritdoc />
    public double GetVolume() => _massProperty.Volume;

    /// <inheritdoc />
    public double GetSurfaceArea() => _massProperty.SurfaceArea;

    /// <inheritdoc />
    public IReadOnlyList<double>? GetCenterOfMass() => ToDoubleArray(_massProperty.CenterOfMass);

    /// <inheritdoc />
    public IReadOnlyList<double>? GetPrincipalMomentsOfInertia() => ToDoubleArray(_massProperty.PrincipalMomentsOfInertia);

    /// <inheritdoc />
    public double GetMass() => _massProperty.Mass;

    /// <inheritdoc />
    public double GetDensity() => _massProperty.Density;

    /// <summary>
    /// The raw <c>object</c> a mass property getter answers with: a SAFEARRAY of doubles, which
    /// arrives as a <c>double[]</c> or, depending on the interop build, as another one-dimensional
    /// array - possibly with a lower bound of one. It is read only when every element is a number.
    /// Anything else is unreadable (null) rather than guessed: not an array, more than one
    /// dimension, or any element that is not a number. <see cref="Convert.ToDouble(object)"/> is
    /// not used because it reads a null element as zero and a string in the current culture, and
    /// a guessed zero in a centre of mass is a number the gate would compare
    /// (<see cref="RemodelGeometry"/>'s rule; default taken 2026-09-27, the owner may revise). The
    /// length is not judged here: a triple of the wrong length is the caller's to refuse.
    /// </summary>
    private static IReadOnlyList<double>? ToDoubleArray(object? value)
    {
        if (value is double[] doubles)
        {
            return doubles;
        }

        if (!(value is Array array) || array.Rank != 1)
        {
            return null;
        }

        int lowerBound = array.GetLowerBound(0);
        var converted = new double[array.Length];
        for (int i = 0; i < array.Length; i++)
        {
            if (!TryReadNumber(array.GetValue(lowerBound + i), out converted[i]))
            {
                return null;
            }
        }

        return converted;
    }

    /// <summary>A boxed number of any primitive numeric type (or <c>decimal</c>), and nothing else.</summary>
    private static bool TryReadNumber(object? element, out double number)
    {
        switch (element)
        {
            case double value:
                number = value;
                return true;
            case float value:
                number = value;
                return true;
            case int value:
                number = value;
                return true;
            case long value:
                number = value;
                return true;
            case short value:
                number = value;
                return true;
            case byte value:
                number = value;
                return true;
            case sbyte value:
                number = value;
                return true;
            case uint value:
                number = value;
                return true;
            case ulong value:
                number = value;
                return true;
            case ushort value:
                number = value;
                return true;
            case decimal value:
                number = (double)value;
                return true;
            default:
                number = 0;
                return false;
        }
    }
}
