using System;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Geometry;

/// <summary>
/// Converts <c>IMathTransform.ArrayData</c> into the IR's 4x4 matrix and applies it.
///
/// SOLIDWORKS convention (help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IMathTransform~ArrayData.html):
/// ArrayData is 16 doubles laid out as
///
///     [0..8]   3x3 rotation, row-major for the ROW-vector product v' = v * R
///     [9..11]  translation x, y, z in METERS
///     [12]     scale factor (1.0 for every component transform seen so far)
///     [13..15] unused
///
/// The IR matrix (data-model.md section 1) is row-major for the COLUMN-vector product
/// p' = M * p - the convention trimesh and numpy use on the Python side. The rotation is
/// therefore TRANSPOSED on the way in: ArrayData[0..2] is the image of the X axis, which
/// becomes the first COLUMN of M, not its first row. Getting this backwards produces a
/// mirrored assembly that still looks plausible, so <c>SwTransformTests</c> pins it with a
/// 90-degree turn about Z.
///
/// The scale multiplies the rotation block only: the translation is already an absolute
/// position in meters. Component transforms always report scale 1.0, so the workstation
/// check (T061) only has to confirm that one number.
///
/// Lengths stay in meters throughout; the extractor never converts to millimetres.
/// </summary>
public static class SwTransform
{
    /// <summary>Number of doubles SOLIDWORKS puts in ArrayData.</summary>
    public const int ArrayDataLength = 16;

    private const int ScaleIndex = 12;

    /// <summary>Row-major 4x4 in meters for the column-vector product p' = M * p.</summary>
    public static double[][] FromArrayData(double[] arrayData)
    {
        if (arrayData == null)
        {
            throw new ArgumentNullException(nameof(arrayData));
        }

        if (arrayData.Length != ArrayDataLength)
        {
            throw new ArgumentException(
                $"MathTransform.ArrayData must have {ArrayDataLength} elements, got {arrayData.Length}.",
                nameof(arrayData));
        }

        // Only the 13 elements we read have to be finite; [13..15] are documented unused.
        for (int i = 0; i <= ScaleIndex; i++)
        {
            if (double.IsNaN(arrayData[i]) || double.IsInfinity(arrayData[i]))
            {
                throw new ArgumentException(
                    $"MathTransform.ArrayData[{i}] is not a finite number ({arrayData[i]}).",
                    nameof(arrayData));
            }
        }

        double scale = arrayData[ScaleIndex];
        if (scale <= 0.0)
        {
            throw new ArgumentException(
                $"MathTransform.ArrayData[12] is a scale of {scale}; a non-positive scale is degenerate.",
                nameof(arrayData));
        }

        var m = new double[4][];
        for (int row = 0; row < 3; row++)
        {
            m[row] = new double[4];
            for (int col = 0; col < 3; col++)
            {
                // Transpose: ArrayData[col * 3 + row], not [row * 3 + col].
                m[row][col] = arrayData[(col * 3) + row] * scale;
            }

            m[row][3] = arrayData[9 + row];
        }

        m[3] = new double[] { 0, 0, 0, 1 };
        return m;
    }

    /// <summary>
    /// Converts the boxed array interop returns from <c>ArrayData</c>. Null in, null out,
    /// so a caller can record a gap for a component whose transform is missing.
    /// </summary>
    public static double[][]? FromComValue(object? arrayData)
    {
        if (arrayData == null)
        {
            return null;
        }

        if (arrayData is double[] data)
        {
            return FromArrayData(data);
        }

        throw new ArgumentException(
            $"MathTransform.ArrayData returned {arrayData.GetType().Name}, not a double array.",
            nameof(arrayData));
    }

    /// <summary>p' = M * p, with the translation applied.</summary>
    public static Vec3 ApplyToPoint(double[][] matrix, Vec3 point)
    {
        RequireMatrix(matrix);
        if (point == null)
        {
            throw new ArgumentNullException(nameof(point));
        }

        return new Vec3(
            (matrix[0][0] * point.X) + (matrix[0][1] * point.Y) + (matrix[0][2] * point.Z) + matrix[0][3],
            (matrix[1][0] * point.X) + (matrix[1][1] * point.Y) + (matrix[1][2] * point.Z) + matrix[1][3],
            (matrix[2][0] * point.X) + (matrix[2][1] * point.Y) + (matrix[2][2] * point.Z) + matrix[2][3]);
    }

    /// <summary>
    /// Rotates a direction (no translation) and re-normalizes it, so a scaled transform
    /// still yields a unit axis for hole and fastener axes.
    /// </summary>
    public static Vec3 ApplyToDirection(double[][] matrix, Vec3 direction)
    {
        RequireMatrix(matrix);
        if (direction == null)
        {
            throw new ArgumentNullException(nameof(direction));
        }

        double x = (matrix[0][0] * direction.X) + (matrix[0][1] * direction.Y) + (matrix[0][2] * direction.Z);
        double y = (matrix[1][0] * direction.X) + (matrix[1][1] * direction.Y) + (matrix[1][2] * direction.Z);
        double z = (matrix[2][0] * direction.X) + (matrix[2][1] * direction.Y) + (matrix[2][2] * direction.Z);

        double length = Math.Sqrt((x * x) + (y * y) + (z * z));
        if (length <= 0.0)
        {
            return new Vec3(x, y, z);
        }

        return new Vec3(x / length, y / length, z / length);
    }

    /// <summary>
    /// outer * inner: the transform of an entity that sits inside another frame, for
    /// example a face inside a component inside a subassembly.
    /// </summary>
    public static double[][] Multiply(double[][] outer, double[][] inner)
    {
        RequireMatrix(outer);
        RequireMatrix(inner);

        var m = new double[4][];
        for (int row = 0; row < 4; row++)
        {
            m[row] = new double[4];
            for (int col = 0; col < 4; col++)
            {
                double sum = 0;
                for (int k = 0; k < 4; k++)
                {
                    sum += outer[row][k] * inner[k][col];
                }

                m[row][col] = sum;
            }
        }

        return m;
    }

    private static void RequireMatrix(double[][] matrix)
    {
        if (matrix == null)
        {
            throw new ArgumentNullException(nameof(matrix));
        }

        if (matrix.Length != 4)
        {
            throw new ArgumentException("A 4x4 transform is required.", nameof(matrix));
        }

        foreach (double[] row in matrix)
        {
            if (row == null || row.Length != 4)
            {
                throw new ArgumentException("A 4x4 transform is required.", nameof(matrix));
            }
        }
    }
}
