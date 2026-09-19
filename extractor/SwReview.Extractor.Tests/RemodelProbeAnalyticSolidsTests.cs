using System;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// PROBE-8's pure math: exact analytic properties of a box and a cylinder, and the error
/// arithmetic that compares a measured reading against them. Every number here is hand-computed
/// against the textbook formula, independent of <see cref="RemodelProbeExecutors"/> and of
/// anything SOLIDWORKS answers.
/// </summary>
public class RemodelProbeAnalyticSolidsTests
{
    private const double Epsilon = 1e-9;

    // ---- AnalyticSolidSpec construction --------------------------------------------------

    [Theory]
    [InlineData(0.0, 1.0, 1.0)]
    [InlineData(1.0, 0.0, 1.0)]
    [InlineData(1.0, 1.0, 0.0)]
    [InlineData(-1.0, 1.0, 1.0)]
    public void Box_NonPositiveDimension_Throws(double width, double depth, double height)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => AnalyticSolidSpec.Box(width, depth, height));
    }

    [Theory]
    [InlineData(0.0, 1.0)]
    [InlineData(1.0, 0.0)]
    [InlineData(-1.0, 1.0)]
    public void Cylinder_NonPositiveDimension_Throws(double radius, double height)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => AnalyticSolidSpec.Cylinder(radius, height));
    }

    [Fact]
    public void Box_IsBoxIsTrue()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Box(1, 1, 1);
        Assert.True(spec.IsBox);
        Assert.Equal("box", spec.Kind);
    }

    [Fact]
    public void Cylinder_IsBoxIsFalse()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Cylinder(1, 1);
        Assert.False(spec.IsBox);
        Assert.Equal("cylinder", spec.Kind);
    }

    // ---- Volume -----------------------------------------------------------------------

    [Fact]
    public void Volume_Box_2x3x4_Is24()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Box(2, 3, 4);
        Assert.Equal(24.0, AnalyticSolidMath.Volume(spec), 9);
    }

    [Fact]
    public void Volume_Cylinder_Radius1Height2_IsTwoPi()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Cylinder(1, 2);
        Assert.Equal(2.0 * Math.PI, AnalyticSolidMath.Volume(spec), 9);
    }

    // ---- SurfaceArea ------------------------------------------------------------------

    [Fact]
    public void SurfaceArea_Box_2x3x4_Is52()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Box(2, 3, 4);
        Assert.Equal(52.0, AnalyticSolidMath.SurfaceArea(spec), 9);
    }

    [Fact]
    public void SurfaceArea_Cylinder_Radius1Height2_IsSixPi()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Cylinder(1, 2);
        Assert.Equal(6.0 * Math.PI, AnalyticSolidMath.SurfaceArea(spec), 9);
    }

    // ---- CenterOfMass -------------------------------------------------------------------

    [Fact]
    public void CenterOfMass_IsAlwaysTheOrigin()
    {
        Assert.Equal(new[] { 0.0, 0.0, 0.0 }, AnalyticSolidMath.CenterOfMass);
    }

    // ---- PrincipalMomentsOfInertia ------------------------------------------------------

    [Fact]
    public void PrincipalMomentsOfInertia_Box_2x3x4_Density1_SortedAscending()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Box(2, 3, 4);

        // mass = 24. Ixx = 24/12*(9+16) = 50, Iyy = 24/12*(4+16) = 40, Izz = 24/12*(4+9) = 26.
        var moments = AnalyticSolidMath.PrincipalMomentsOfInertia(spec, densityKgM3: 1.0);

        Assert.Equal(3, moments.Count);
        Assert.Equal(26.0, moments[0], 9);
        Assert.Equal(40.0, moments[1], 9);
        Assert.Equal(50.0, moments[2], 9);
    }

    [Fact]
    public void PrincipalMomentsOfInertia_Cylinder_Radius1Height2_Density1_SortedAscending()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Cylinder(1, 2);

        // mass = 2*pi. Iaxis = mass/2*r^2 = pi. Itransverse = mass/12*(3+4) = 7*pi/6 (twice).
        var moments = AnalyticSolidMath.PrincipalMomentsOfInertia(spec, densityKgM3: 1.0);

        Assert.Equal(3, moments.Count);
        Assert.Equal(Math.PI, moments[0], 6);
        Assert.Equal(7.0 * Math.PI / 6.0, moments[1], 6);
        Assert.Equal(7.0 * Math.PI / 6.0, moments[2], 6);
    }

    [Fact]
    public void PrincipalMomentsOfInertia_ScalesLinearlyWithDensity()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Box(1, 1, 1);
        var atDensity1 = AnalyticSolidMath.PrincipalMomentsOfInertia(spec, 1.0);
        var atDensity10 = AnalyticSolidMath.PrincipalMomentsOfInertia(spec, 10.0);

        for (int i = 0; i < 3; i++)
        {
            Assert.Equal(atDensity1[i] * 10.0, atDensity10[i], 9);
        }
    }

    // ---- RelativeError ------------------------------------------------------------------

    [Fact]
    public void RelativeError_TenPercentOver_IsPointOne()
    {
        Assert.Equal(0.1, AnalyticSolidMath.RelativeError(110.0, 100.0), 9);
    }

    [Fact]
    public void RelativeError_ExactMatch_IsZero()
    {
        Assert.Equal(0.0, AnalyticSolidMath.RelativeError(50.0, 50.0), 9);
    }

    [Fact]
    public void RelativeError_IsSymmetricInDirection()
    {
        Assert.Equal(
            AnalyticSolidMath.RelativeError(90.0, 100.0),
            AnalyticSolidMath.RelativeError(110.0, 100.0),
            9);
    }

    [Theory]
    [InlineData(0.0)]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    public void RelativeError_ZeroOrNonFiniteExact_Throws(double exact)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => AnalyticSolidMath.RelativeError(1.0, exact));
    }

    // ---- NormalizedAbsoluteError ----------------------------------------------------------

    [Fact]
    public void NormalizedAbsoluteError_DividesByCharacteristicLength()
    {
        Assert.Equal(0.02, AnalyticSolidMath.NormalizedAbsoluteError(0.002, 0.1), 9);
    }

    [Fact]
    public void NormalizedAbsoluteError_TakesTheAbsoluteValueOfTheComponent()
    {
        Assert.Equal(
            AnalyticSolidMath.NormalizedAbsoluteError(-0.002, 0.1),
            AnalyticSolidMath.NormalizedAbsoluteError(0.002, 0.1),
            9);
    }

    [Fact]
    public void NormalizedAbsoluteError_NonPositiveCharacteristicLength_Throws()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => AnalyticSolidMath.NormalizedAbsoluteError(0.001, 0.0));
    }

    // ---- CharacteristicLength -------------------------------------------------------------

    [Fact]
    public void CharacteristicLength_Box_IsTheLargestDimension()
    {
        AnalyticSolidSpec spec = AnalyticSolidSpec.Box(2, 3, 4);
        Assert.Equal(4.0, AnalyticSolidMath.CharacteristicLength(spec), Epsilon);
    }

    [Fact]
    public void CharacteristicLength_Cylinder_IsTheLargerOfDiameterAndHeight()
    {
        AnalyticSolidSpec tallSpec = AnalyticSolidSpec.Cylinder(1, 10);
        Assert.Equal(10.0, AnalyticSolidMath.CharacteristicLength(tallSpec), Epsilon);

        AnalyticSolidSpec wideSpec = AnalyticSolidSpec.Cylinder(10, 1);
        Assert.Equal(20.0, AnalyticSolidMath.CharacteristicLength(wideSpec), Epsilon);
    }
}
