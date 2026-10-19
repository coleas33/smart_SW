using System;
using System.Collections.Generic;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Feature 011, decision 141A (2026-10-19): what <see cref="ConfirmedDrawingRead"/> keeps for one
/// review session - its run folder, the opens it attempted that left no drawing record, and the
/// path of each part or assembly with a candidate row in the package it last loaded.
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
    private IReadOnlyDictionary<string, string> _candidateModels = new Dictionary<string, string>();

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
    /// Remembers, from <paramref name="package"/> as the read just loaded it, the path of every part
    /// or assembly that has a candidate row, by document id - in place of what the session last
    /// remembered. Once the session's failed opens alone reach the limit, the read asks SOLIDWORKS
    /// whether the drawing beside such a document is open without loading the package again: the
    /// package is read only by its own session's requests, and its candidate rows only ever go.
    /// </summary>
    internal void Remember(EvidencePackage package)
    {
        var candidates = new HashSet<string>(StringComparer.Ordinal);
        foreach (DrawingCandidate row in package.DrawingCandidates ?? new List<DrawingCandidate>())
        {
            candidates.Add(row.DocumentId);
        }

        var models = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (Document document in package.Documents)
        {
            if ((document.Kind == DocumentKind.Part || document.Kind == DocumentKind.Assembly)
                && !string.IsNullOrEmpty(document.DocumentId)
                && !string.IsNullOrWhiteSpace(document.Path)
                && candidates.Contains(document.DocumentId)
                && !models.ContainsKey(document.DocumentId))
            {
                models.Add(document.DocumentId, document.Path);
            }
        }

        lock (_lock)
        {
            _candidateModels = models;
        }
    }

    /// <summary>
    /// The path of the part or assembly <paramref name="documentId"/> names when the package the
    /// session last loaded holds it with a candidate row; otherwise null.
    /// </summary>
    internal string? CandidateModelPath(string documentId)
    {
        lock (_lock)
        {
            return _candidateModels.TryGetValue(documentId, out string? path) ? path : null;
        }
    }
}
