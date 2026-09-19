using System;
using System.Collections.Generic;
using System.Linq;

namespace SwReview.Extractor.Rms;

/// <summary>
/// PROBE-8's two shapes: a box and a cylinder of exactly known analytic dimensions, each
/// sketched and extruded <b>centred on the origin</b> (a centred rectangle or a circle, a
/// <c>Mid-Plane</c> extrude) so the analytic centre of mass is <c>(0, 0, 0)</c> regardless of
/// how "Front Plane" maps its local sketch axes onto the document's global ones - there is no
/// VERIFIED mapping for that in research.md, so nothing here depends on one.
/// </summary>
public sealed class AnalyticSolidSpec
{
    private AnalyticSolidSpec(string kind, double dimension1, double dimension2, double height)
    {
        Kind = kind;
        Dimension1 = dimension1;
        Dimension2 = dimension2;
        Height = height;
    }

    /// <summary>A box of <paramref name="widthM"/> x <paramref name="depthM"/> x <paramref name="heightM"/>, in metres.</summary>
    public static AnalyticSolidSpec Box(double widthM, double depthM, double heightM)
    {
        RequirePositive(widthM, nameof(widthM));
        RequirePositive(depthM, nameof(depthM));
        RequirePositive(heightM, nameof(heightM));
        return new AnalyticSolidSpec("box", widthM, depthM, heightM);
    }

    /// <summary>A cylinder of <paramref name="radiusM"/> and <paramref name="heightM"/>, in metres.</summary>
    public static AnalyticSolidSpec Cylinder(double radiusM, double heightM)
    {
        RequirePositive(radiusM, nameof(radiusM));
        RequirePositive(heightM, nameof(heightM));
        return new AnalyticSolidSpec("cylinder", radiusM, double.NaN, heightM);
    }

    /// <summary><c>"box"</c> or <c>"cylinder"</c>: the ledger's own spelling for this shape.</summary>
    public string Kind { get; }

    /// <summary>The box's width, or the cylinder's radius, in metres.</summary>
    public double Dimension1 { get; }

    /// <summary>The box's depth, in metres. <c>NaN</c> for a cylinder.</summary>
    public double Dimension2 { get; }

    /// <summary>The box's or the cylinder's height (extrude depth), in metres.</summary>
    public double Height { get; }

    public bool IsBox => Kind == "box";

    private static void RequirePositive(double value, string paramName)
    {
        if (!(value > 0))
        {
            throw new ArgumentOutOfRangeException(paramName, value, "A solid dimension must be positive.");
        }
    }
}

/// <summary>
/// The exact analytic properties of an <see cref="AnalyticSolidSpec"/>, and the error arithmetic
/// PROBE-8 compares SOLIDWORKS's measured numbers against. Every formula here is the standard
/// textbook one for a box or a right circular cylinder about its own centroid; none of it is a
/// SOLIDWORKS interop call, and none of it needs a seat to test.
/// </summary>
public static class AnalyticSolidMath
{
    /// <summary>The solid's volume, in cubic metres.</summary>
    public static double Volume(AnalyticSolidSpec spec)
    {
        if (spec == null)
        {
            throw new ArgumentNullException(nameof(spec));
        }

        return spec.IsBox
            ? spec.Dimension1 * spec.Dimension2 * spec.Height
            : Math.PI * spec.Dimension1 * spec.Dimension1 * spec.Height;
    }

    /// <summary>The solid's total surface area, in square metres.</summary>
    public static double SurfaceArea(AnalyticSolidSpec spec)
    {
        if (spec == null)
        {
            throw new ArgumentNullException(nameof(spec));
        }

        if (spec.IsBox)
        {
            double w = spec.Dimension1;
            double d = spec.Dimension2;
            double h = spec.Height;
            return 2.0 * (w * d + w * h + d * h);
        }

        double r = spec.Dimension1;
        return 2.0 * Math.PI * r * (r + spec.Height);
    }

    /// <summary>
    /// <c>(0, 0, 0)</c>: both shapes are built centred on the origin (see
    /// <see cref="AnalyticSolidSpec"/>'s own remarks), so this is the same for every spec and
    /// takes none - a component the measured reading disagrees with by more than the seat's
    /// numerical noise is evidence of a real placement error, not a units mistake.
    /// </summary>
    public static readonly IReadOnlyList<double> CenterOfMass = new double[] { 0.0, 0.0, 0.0 };

    /// <summary>
    /// The three principal moments of inertia about the centroid, in kg*m^2, <b>sorted
    /// ascending</b> - the same rule <c>RemodelGeometry.Read</c> applies, because a
    /// symmetry-degenerate rotation returns the same three numbers permuted. Needs
    /// <paramref name="densityKgM3"/> because a moment of inertia is a property of mass, not of
    /// shape alone; PROBE-8 reads the throwaway part's own measured density
    /// (<c>IMassProperty2.get_Density</c>) rather than assuming or assigning one, since no
    /// interop member for setting material is VERIFIED in research.md.
    /// </summary>
    public static IReadOnlyList<double> PrincipalMomentsOfInertia(AnalyticSolidSpec spec, double densityKgM3)
    {
        if (spec == null)
        {
            throw new ArgumentNullException(nameof(spec));
        }

        double mass = densityKgM3 * Volume(spec);
        double[] moments;

        if (spec.IsBox)
        {
            double w = spec.Dimension1;
            double d = spec.Dimension2;
            double h = spec.Height;
            moments = new[]
            {
                mass / 12.0 * (d * d + h * h),
                mass / 12.0 * (w * w + h * h),
                mass / 12.0 * (w * w + d * d),
            };
        }
        else
        {
            double r = spec.Dimension1;
            double h = spec.Height;
            moments = new[]
            {
                mass / 12.0 * (3.0 * r * r + h * h),
                mass / 12.0 * (3.0 * r * r + h * h),
                mass / 2.0 * r * r,
            };
        }

        Array.Sort(moments);
        return moments;
    }

    /// <summary>
    /// <c>|measured - exact| / |exact|</c>. Refuses a zero or non-finite <paramref name="exact"/>
    /// rather than dividing by it: every quantity this is used for (volume, area, a nonzero
    /// principal moment) is strictly positive by construction, so a zero here is a caller
    /// mistake, not a legitimate reading.
    /// </summary>
    public static double RelativeError(double measured, double exact)
    {
        if (exact == 0.0 || double.IsNaN(exact) || double.IsInfinity(exact))
        {
            throw new ArgumentOutOfRangeException(
                nameof(exact), exact, "A relative error needs a nonzero, finite exact value.");
        }

        return Math.Abs(measured - exact) / Math.Abs(exact);
    }

    /// <summary>
    /// <c>|measuredComponent| / characteristicLengthM</c>: the error metric for a centre-of-mass
    /// component whose exact value is <c>0</c>, where a plain relative error is undefined. The
    /// solid's largest dimension is the natural characteristic length - the same deviation
    /// means less on a metre-scale part than on a millimetre-scale one.
    /// </summary>
    public static double NormalizedAbsoluteError(double measuredComponent, double characteristicLengthM)
    {
        if (!(characteristicLengthM > 0))
        {
            throw new ArgumentOutOfRangeException(
                nameof(characteristicLengthM), characteristicLengthM,
                "A characteristic length must be positive.");
        }

        return Math.Abs(measuredComponent) / characteristicLengthM;
    }

    /// <summary>The solid's largest dimension, in metres - <see cref="NormalizedAbsoluteError"/>'s characteristic length.</summary>
    public static double CharacteristicLength(AnalyticSolidSpec spec)
    {
        if (spec == null)
        {
            throw new ArgumentNullException(nameof(spec));
        }

        return spec.IsBox
            ? new[] { spec.Dimension1, spec.Dimension2, spec.Height }.Max()
            : Math.Max(spec.Dimension1 * 2.0, spec.Height);
    }
}
