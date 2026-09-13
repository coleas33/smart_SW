using System;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Measure;

/// <summary>
/// What SOLIDWORKS' Measure tool reported between two entities. Lengths are meters:
/// <c>IMeasure</c> answers in system units, and the reviewer converts on read, so nothing
/// here is rounded or reformatted (Principle II - a number carries its unit).
/// </summary>
public sealed class MeasureReading
{
    public MeasureReading(double distanceM, double deltaXM, double deltaYM, double deltaZM)
    {
        Distance = new Quantity(distanceM, LengthUnit.M);
        DeltaX = new Quantity(deltaXM, LengthUnit.M);
        DeltaY = new Quantity(deltaYM, LengthUnit.M);
        DeltaZ = new Quantity(deltaZM, LengthUnit.M);
    }

    /// <summary><c>IMeasure.Distance</c>: the shortest distance between the two entities.</summary>
    public Quantity Distance { get; }

    public Quantity DeltaX { get; }

    public Quantity DeltaY { get; }

    public Quantity DeltaZ { get; }
}

/// <summary>
/// Raised when SOLIDWORKS cannot measure the two entities - the usual reason is a pairing
/// the Measure tool has no answer for. The bridge turns it into an error response with the
/// message, never into a number (constitution Principle I).
/// </summary>
[Serializable]
public class MeasureNotAvailableError : Exception
{
    public MeasureNotAvailableError(string message)
        : base(message)
    {
    }
}

/// <summary>
/// The measure half of the bridge (T072), as an interface so the dispatcher is tested
/// without SOLIDWORKS.
/// </summary>
public interface IMeasureSource
{
    /// <summary>
    /// Measures between the two entities the references resolve to. Throws
    /// <see cref="MeasureNotAvailableError"/> when SOLIDWORKS declines.
    /// </summary>
    /// <param name="persistRefA">Base64 persistent reference of the first entity.</param>
    /// <param name="scopeA">Document that produced <paramref name="persistRefA"/>, or null.</param>
    /// <param name="persistRefB">Base64 persistent reference of the second entity.</param>
    /// <param name="scopeB">Document that produced <paramref name="persistRefB"/>, or null.</param>
    MeasureReading Measure(string persistRefA, string? scopeA, string persistRefB, string? scopeB);
}
