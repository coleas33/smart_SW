using System;

namespace SwReview.Extractor.Probes;

/// <summary>
/// One read a probe made: its value, or the failure it printed instead. A probe whose member throws
/// prints the failure and the run carries on - which members fail on this release is half of what
/// the probes are for - so every read is taken through <see cref="Of"/>.
/// </summary>
internal sealed class ProbeAnswer<T>
{
    private ProbeAnswer(T value, string? failure)
    {
        Value = value;
        Failure = failure;
    }

    /// <summary>What the read answered; the type's default when it failed.</summary>
    public T Value { get; }

    /// <summary>The failure as <see cref="ProbeText.Failure"/> prints it, or null when the read answered.</summary>
    public string? Failure { get; }

    public bool Answered => Failure == null;

    public static ProbeAnswer<T> Of(Func<T> read)
    {
        try
        {
            return new ProbeAnswer<T>(read(), null);
        }
        catch (Exception error)
        {
            return new ProbeAnswer<T>(default!, ProbeText.Failure(error));
        }
    }

    /// <summary>The value printed by <paramref name="print"/>, or <c>unread (failure)</c>.</summary>
    public string Print(Func<T, string> print) => Answered ? print(Value) : $"{ProbeText.Unread} ({Failure})";
}
