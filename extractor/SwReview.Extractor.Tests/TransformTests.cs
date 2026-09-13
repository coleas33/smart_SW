using System;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T046. Every world position in the IR comes through this conversion, so the SOLIDWORKS
/// ArrayData convention (rotation ordering, translation in meters, the scale at index 12)
/// is pinned here rather than discovered on the workstation.
/// </summary>
public class SwTransformTests
{
    private const double Tol = 1e-12;

    /// <summary>ArrayData for an identity transform: unit rotation, no translation, scale 1.</summary>
    private static double[] Identity() => new double[]
    {
        1, 0, 0,
        0, 1, 0,
        0, 0, 1,
        0, 0, 0,
        1,
        0, 0, 0,
    };

    [Fact]
    public void FromArrayData_Identity_ProducesTheIdentityMatrix()
    {
        double[][] m = SwTransform.FromArrayData(Identity());

        for (int r = 0; r < 4; r++)
        {
            for (int c = 0; c < 4; c++)
            {
                Assert.Equal(r == c ? 1.0 : 0.0, m[r][c], 12);
            }
        }
    }

    [Fact]
    public void FromArrayData_ProducesFourRowsOfFour()
    {
        double[][] m = SwTransform.FromArrayData(Identity());

        Assert.Equal(4, m.Length);
        Assert.All(m, row => Assert.Equal(4, row.Length));
    }

    [Fact]
    public void FromArrayData_TranslationLandsInTheLastColumnInMeters()
    {
        double[] data = Identity();
        data[9] = 0.1;
        data[10] = -0.25;
        data[11] = 0.003;

        double[][] m = SwTransform.FromArrayData(data);

        // Meters straight through: the extractor never converts to mm (data-model.md).
        Assert.Equal(0.1, m[0][3], 12);
        Assert.Equal(-0.25, m[1][3], 12);
        Assert.Equal(0.003, m[2][3], 12);
    }

    [Fact]
    public void FromArrayData_BottomRowIsAffine()
    {
        double[] data = Identity();
        data[9] = 1.5;

        double[][] m = SwTransform.FromArrayData(data);

        Assert.Equal(new[] { 0.0, 0.0, 0.0, 1.0 }, m[3]);
    }

    [Fact]
    public void FromArrayData_RotationIsTransposedIntoColumnVectorConvention()
    {
        // SOLIDWORKS stores the rotation row-major for the row-vector product v' = v * R,
        // so ArrayData[0..2] is the image of the X axis. A 90 degree turn about Z sends
        // X to Y, Y to -X. The IR matrix multiplies a column vector, so it must be the
        // transpose: applying it to (1,0,0) must give (0,1,0).
        double[] data = Identity();
        data[0] = 0; data[1] = 1; data[2] = 0;    // X -> Y
        data[3] = -1; data[4] = 0; data[5] = 0;   // Y -> -X
        data[6] = 0; data[7] = 0; data[8] = 1;    // Z -> Z

        double[][] m = SwTransform.FromArrayData(data);

        Assert.Equal(0.0, m[0][0], 12);
        Assert.Equal(-1.0, m[0][1], 12);
        Assert.Equal(1.0, m[1][0], 12);
        Assert.Equal(0.0, m[1][1], 12);

        Vec3 rotated = SwTransform.ApplyToPoint(m, new Vec3(1, 0, 0));
        Assert.Equal(0.0, rotated.X, 12);
        Assert.Equal(1.0, rotated.Y, 12);
        Assert.Equal(0.0, rotated.Z, 12);
    }

    [Fact]
    public void FromArrayData_ScaleMultipliesTheRotationBlockOnly()
    {
        double[] data = Identity();
        data[9] = 0.5;
        data[12] = 2.0;

        double[][] m = SwTransform.FromArrayData(data);

        Assert.Equal(2.0, m[0][0], 12);
        Assert.Equal(2.0, m[1][1], 12);
        Assert.Equal(2.0, m[2][2], 12);

        // The translation is already an absolute position in meters.
        Assert.Equal(0.5, m[0][3], 12);
    }

    [Fact]
    public void FromArrayData_UnitScaleLeavesTheRotationUntouched()
    {
        double[] data = Identity();
        data[0] = 0.6; data[1] = 0.8;
        data[3] = -0.8; data[4] = 0.6;

        double[][] m = SwTransform.FromArrayData(data);

        Assert.Equal(0.6, m[0][0], 12);
        Assert.Equal(-0.8, m[0][1], 12);
        Assert.Equal(0.8, m[1][0], 12);
        Assert.Equal(0.6, m[1][1], 12);
    }

    [Fact]
    public void FromArrayData_TrailingUnusedElementsAreIgnored()
    {
        double[] data = Identity();
        data[13] = 123;
        data[14] = -4;
        data[15] = 7;

        double[][] m = SwTransform.FromArrayData(data);

        Assert.Equal(new[] { 0.0, 0.0, 0.0, 1.0 }, m[3]);
    }

    [Fact]
    public void FromArrayData_Null_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => SwTransform.FromArrayData(null!));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(12)]
    [InlineData(15)]
    [InlineData(17)]
    public void FromArrayData_WrongLength_Throws(int length)
    {
        Assert.Throws<ArgumentException>(() => SwTransform.FromArrayData(new double[length]));
    }

    [Fact]
    public void FromArrayData_NonFiniteValue_Throws()
    {
        double[] data = Identity();
        data[9] = double.NaN;

        Assert.Throws<ArgumentException>(() => SwTransform.FromArrayData(data));
    }

    [Theory]
    [InlineData(0.0)]
    [InlineData(-1.0)]
    public void FromArrayData_NonPositiveScale_Throws(double scale)
    {
        // A zero or negative scale is a degenerate transform; silently accepting it would
        // collapse every position it produced.
        double[] data = Identity();
        data[12] = scale;

        Assert.Throws<ArgumentException>(() => SwTransform.FromArrayData(data));
    }

    [Fact]
    public void FromComValue_AcceptsTheBoxedArrayInteropReturns()
    {
        object arrayData = Identity();

        double[][]? m = SwTransform.FromComValue(arrayData);

        Assert.NotNull(m);
        Assert.Equal(1.0, m![3][3], 12);
    }

    [Fact]
    public void FromComValue_Null_ReturnsNull()
    {
        Assert.Null(SwTransform.FromComValue(null));
    }

    [Fact]
    public void ApplyToPoint_TranslatesAndRotates()
    {
        double[] data = Identity();
        data[0] = 0; data[1] = 1; data[2] = 0;
        data[3] = -1; data[4] = 0; data[5] = 0;
        data[9] = 1.0; data[10] = 2.0; data[11] = 3.0;

        Vec3 p = SwTransform.ApplyToPoint(SwTransform.FromArrayData(data), new Vec3(1, 0, 0));

        Assert.Equal(1.0, p.X, 12);
        Assert.Equal(3.0, p.Y, 12);
        Assert.Equal(3.0, p.Z, 12);
    }

    [Fact]
    public void ApplyToDirection_IgnoresTranslation()
    {
        double[] data = Identity();
        data[9] = 10; data[10] = 20; data[11] = 30;

        Vec3 d = SwTransform.ApplyToDirection(SwTransform.FromArrayData(data), new Vec3(0, 0, 1));

        Assert.Equal(0.0, d.X, 12);
        Assert.Equal(0.0, d.Y, 12);
        Assert.Equal(1.0, d.Z, 12);
    }

    [Fact]
    public void ApplyToDirection_ReNormalizesAScaledAxis()
    {
        double[] data = Identity();
        data[12] = 3.0;

        Vec3 d = SwTransform.ApplyToDirection(SwTransform.FromArrayData(data), new Vec3(0, 1, 0));

        Assert.Equal(1.0, Math.Sqrt(d.X * d.X + d.Y * d.Y + d.Z * d.Z), 12);
    }

    [Fact]
    public void ApplyToPoint_NullMatrix_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => SwTransform.ApplyToPoint(null!, new Vec3(0, 0, 0)));
    }

    [Fact]
    public void Identity_MatchesTheIrIdentity()
    {
        double[][] fromData = SwTransform.FromArrayData(Identity());
        double[][] irIdentity = Transform.Identity();

        for (int r = 0; r < 4; r++)
        {
            Assert.Equal(irIdentity[r], fromData[r]);
        }
    }

    [Fact]
    public void FromArrayData_DoesNotAliasTheSourceArray()
    {
        double[] data = Identity();
        double[][] m = SwTransform.FromArrayData(data);

        data[0] = 99;

        Assert.Equal(1.0, m[0][0], 12);
    }

    [Fact]
    public void Multiply_ComposesTwoTransforms()
    {
        // Assembly space for a face inside a subassembly needs parent * child.
        double[] childData = Identity();
        childData[9] = 1.0;

        double[] parentData = Identity();
        parentData[0] = 0; parentData[1] = 1; parentData[2] = 0;
        parentData[3] = -1; parentData[4] = 0; parentData[5] = 0;

        double[][] composed = SwTransform.Multiply(
            SwTransform.FromArrayData(parentData),
            SwTransform.FromArrayData(childData));

        // The child's +X offset is rotated into +Y by the parent.
        Vec3 origin = SwTransform.ApplyToPoint(composed, new Vec3(0, 0, 0));
        Assert.Equal(0.0, origin.X, 12);
        Assert.Equal(1.0, origin.Y, 12);
    }
}
