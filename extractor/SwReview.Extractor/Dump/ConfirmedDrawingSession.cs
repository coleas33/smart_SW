using System;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Feature 011, decision 141A (2026-10-19): what <see cref="ConfirmedDrawingRead"/> keeps for one
/// review session - its run folder, and the opens it attempted that left no drawing record.
///
/// The host makes one for every review session it starts (the add-in's <c>SessionRecord</c>, which
/// holds it for as long as it holds the record) and hands it to the read through its own records:
/// a request's run id resolves to the latest review the host started in the run folder of that
/// name, and a request can name nothing else. So a Retry or a Recheck, a new session in the same run
/// folder, starts its own count; two sessions never share one; and a session's count goes when the
/// host lets its record go, so no count outlives what it bounds.
/// </summary>
public sealed class ConfirmedDrawingSession
{
    private readonly object _lock = new object();
    private int _unrecordedOpens;

    /// <param name="runFolder">The review's run folder, which holds its package.</param>
    public ConfirmedDrawingSession(string runFolder)
    {
        RunFolder = runFolder ?? throw new ArgumentNullException(nameof(runFolder));
    }

    /// <summary>The review's run folder, which holds its package.</summary>
    public string RunFolder { get; }

    /// <summary>
    /// The opens attempted for this session that left no drawing record - refused, failed, or read
    /// and not merged (decision 136A) - which count with the package's records toward its ten.
    /// </summary>
    public int UnrecordedOpens
    {
        get
        {
            lock (_lock)
            {
                return _unrecordedOpens;
            }
        }
    }

    /// <summary>Counts one more open that left no record. Only the confirmed read counts.</summary>
    internal void CountUnrecordedOpen()
    {
        lock (_lock)
        {
            _unrecordedOpens++;
        }
    }
}
