using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/Quantity. A length stored in its source unit; the
/// reviewer converts on read and keeps both source and converted values.
/// </summary>
public sealed class Quantity
{
    [JsonPropertyName("value")]
    public double Value { get; set; }

    [JsonPropertyName("unit")]
    public LengthUnit Unit { get; set; } = LengthUnit.Mm;

    public Quantity()
    {
    }

    public Quantity(double value, LengthUnit unit)
    {
        Value = value;
        Unit = unit;
    }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/Angle. A distinct type from <see cref="Quantity"/>:
/// an angle is never assignable to a length field (Principle II, FR-022).
/// </summary>
public sealed class Angle
{
    [JsonPropertyName("value")]
    public double Value { get; set; }

    [JsonPropertyName("unit")]
    public AngleUnit Unit { get; set; } = AngleUnit.Deg;

    public Angle()
    {
    }

    public Angle(double value, AngleUnit unit)
    {
        Value = value;
        Unit = unit;
    }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/Volume. The unit is the one the extractor verified on
/// the workstation; IInterference.Volume units are undocumented (research R12).
/// </summary>
public sealed class Volume
{
    [JsonPropertyName("value")]
    public double Value { get; set; }

    [JsonPropertyName("unit")]
    public VolumeUnit Unit { get; set; } = VolumeUnit.Mm3;

    public Volume()
    {
    }

    public Volume(double value, VolumeUnit unit)
    {
        Value = value;
        Unit = unit;
    }
}

/// <summary>
/// The `Quantity | Angle` union the schema uses for Dimension.nominal and
/// Tolerance.upper/lower. C# has no anonymous unions, so this carries the same
/// {value, unit} shape with the unit as a string and validates against either $def.
/// Use <see cref="FromQuantity"/> / <see cref="FromAngle"/> so the unit string is never
/// invented by hand.
/// </summary>
public sealed class Measure
{
    [JsonPropertyName("value")]
    public double Value { get; set; }

    /// <summary>One of "mm", "in", "m", "deg", "rad".</summary>
    [JsonPropertyName("unit")]
    public string Unit { get; set; } = "mm";

    public Measure()
    {
    }

    public Measure(double value, string unit)
    {
        Value = value;
        Unit = unit;
    }

    public static Measure FromQuantity(Quantity quantity) =>
        new Measure(quantity.Value, PackageSerializer.EnumToJsonName(quantity.Unit));

    public static Measure FromAngle(Angle angle) =>
        new Measure(angle.Value, PackageSerializer.EnumToJsonName(angle.Unit));
}

/// <summary>contracts/ir.schema.json #/$defs/Vec3. Meters, assembly frame.</summary>
public sealed class Vec3
{
    [JsonPropertyName("x")]
    public double X { get; set; }

    [JsonPropertyName("y")]
    public double Y { get; set; }

    [JsonPropertyName("z")]
    public double Z { get; set; }

    public Vec3()
    {
    }

    public Vec3(double x, double y, double z)
    {
        X = x;
        Y = y;
        Z = z;
    }
}

/// <summary>contracts/ir.schema.json #/$defs/Axis.</summary>
public sealed class Axis
{
    [JsonPropertyName("origin")]
    public Vec3 Origin { get; set; } = new Vec3();

    [JsonPropertyName("direction")]
    public Vec3 Direction { get; set; } = new Vec3();

    public Axis()
    {
    }

    public Axis(Vec3 origin, Vec3 direction)
    {
        Origin = origin;
        Direction = direction;
    }
}

/// <summary>
/// Helpers for the schema's Transform type, a row-major 4x4 with translation in meters,
/// carried in the DTOs as <c>double[][]</c>.
/// </summary>
public static class Transform
{
    public const int Size = 4;

    public static double[][] Identity()
    {
        return new[]
        {
            new[] { 1.0, 0.0, 0.0, 0.0 },
            new[] { 0.0, 1.0, 0.0, 0.0 },
            new[] { 0.0, 0.0, 1.0, 0.0 },
            new[] { 0.0, 0.0, 0.0, 1.0 },
        };
    }
}
