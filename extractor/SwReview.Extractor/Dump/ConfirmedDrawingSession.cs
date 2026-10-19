using System;
using System.Collections.Generic;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Feature 011, decision 141A (2026-10-19): what <see cref="ConfirmedDrawingRead"/> keeps for one
/// review session - its run folder, the opens it attempted that left no drawing record, and the
/// candidate drawing of each part or assembly in the package it last loaded.
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
    private IReadOnlyDictionary<string, string> _candidateDrawings = new Dictionary<string, string>();

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

    /// <summary>
    /// Remembers, from <paramref name="package"/> as the read just loaded or merged it, the candidate
    /// drawing of every part or assembly, by document id: the path of the first candidate row the
    /// document has, which is the row the read takes and the very path the seam would look up - in
    /// place of what the session last remembered. Once the session's failed opens alone reach the
    /// limit, the read asks SOLIDWORKS whether that drawing is open without loading the package
    /// again: its candidate rows only ever go, and its drawings only ever come. A package that holds
    /// ten drawings leaves nothing to remember, since every request then meets the ten-records bound,
    /// which is the read's to say once the package is loaded.
    /// </summary>
    internal void Remember(EvidencePackage package)
    {
        var drawings = new Dictionary<string, string>(StringComparer.Ordinal);
        if ((package.DrawingRecords?.Count ?? 0) < OpenDrawingDiscovery.MaxAttachedDrawings)
        {
            // The first document and the first candidate row of an id, as the read takes them.
            var kinds = new Dictionary<string, DocumentKind>(StringComparer.Ordinal);
            foreach (Document document in package.Documents)
            {
                if (!string.IsNullOrEmpty(document.DocumentId) && !kinds.ContainsKey(document.DocumentId))
                {
                    kinds.Add(document.DocumentId, document.Kind);
                }
            }

            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (DrawingCandidate row in package.DrawingCandidates ?? new List<DrawingCandidate>())
            {
                if (!string.IsNullOrEmpty(row.DocumentId)
                    && seen.Add(row.DocumentId)
                    && kinds.TryGetValue(row.DocumentId, out DocumentKind kind)
                    && (kind == DocumentKind.Part || kind == DocumentKind.Assembly)
                    && !string.IsNullOrWhiteSpace(row.Path))
                {
                    drawings.Add(row.DocumentId, row.Path);
                }
            }
        }

        lock (_lock)
        {
            _candidateDrawings = drawings;
        }
    }

    /// <summary>
    /// The candidate drawing's path of the part or assembly <paramref name="documentId"/> names, as
    /// the package the session last loaded or merged holds it; otherwise null.
    /// </summary>
    internal string? CandidateDrawingPath(string documentId)
    {
        lock (_lock)
        {
            return _candidateDrawings.TryGetValue(documentId, out string? path) ? path : null;
        }
    }
}
