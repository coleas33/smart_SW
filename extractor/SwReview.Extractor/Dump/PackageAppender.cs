using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Ir;
using IrCapture = SwReview.Extractor.Ir.Capture;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T071. <c>interference</c> and <c>capture</c> add to a package a <c>dump</c> already
/// wrote rather than producing one of their own, so the results land next to the components
/// and faces they talk about (contracts/cli.md: "Appends ... to package.json").
///
/// Loading and re-serializing through <see cref="PackageSerializer"/> is deliberate: the
/// serializer refuses unknown properties, so appending to a package written by a different
/// schema version fails here with a clear message instead of silently dropping fields.
/// </summary>
public static class PackageAppender
{
    /// <summary>The package.json in <paramref name="packageDirectory"/>.</summary>
    public static string PathIn(string packageDirectory)
    {
        if (string.IsNullOrWhiteSpace(packageDirectory))
        {
            throw new ArgumentException("A package directory is required.", nameof(packageDirectory));
        }

        return Path.Combine(packageDirectory, PackageWriter.PackageFileName);
    }

    /// <summary>
    /// Loads the package in <paramref name="packageDirectory"/>. Throws
    /// <see cref="FileNotFoundException"/> with an instruction when there is none: running
    /// <c>interference</c> before <c>dump</c> is the common mistake, and a package invented
    /// here would have no components for the results to name.
    /// </summary>
    public static EvidencePackage Load(string packageDirectory)
    {
        string path = PathIn(packageDirectory);
        if (!File.Exists(path))
        {
            throw new FileNotFoundException(
                $"No {PackageWriter.PackageFileName} in '{packageDirectory}'. "
                + "Run 'dump --out' there first: interferences and captures are appended to an "
                + "existing package so they can name its components.",
                path);
        }

        return PackageSerializer.Deserialize(File.ReadAllText(path));
    }

    /// <summary>Writes the package back over the file it was loaded from.</summary>
    public static string Save(string packageDirectory, EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        string path = PathIn(packageDirectory);
        Directory.CreateDirectory(packageDirectory);
        File.WriteAllText(path, PackageSerializer.Serialize(package));
        return path;
    }

    /// <summary>
    /// Merges one interference run into <paramref name="package"/>.
    ///
    /// A run is a complete re-detection for one configuration, and its ids restart at
    /// <c>int:0001</c>, so rows from an earlier run of the SAME configuration are replaced
    /// rather than appended to: two runs appending would leave duplicate ids and a stale
    /// "no interference" row the reviewer would read as current. Other configurations are
    /// left alone.
    /// </summary>
    public static void Merge(
        EvidencePackage package,
        string configuration,
        IReadOnlyList<IrInterference> interferences,
        IReadOnlyList<Gap> gaps)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        package.Interferences.RemoveAll(
            row => string.Equals(row.Configuration, configuration, StringComparison.Ordinal));

        if (interferences != null)
        {
            package.Interferences.AddRange(interferences);
        }

        if (gaps != null)
        {
            package.Gaps.AddRange(gaps);
        }
    }

    /// <summary>
    /// Merges one interference run into the package on disk and saves it. Returns the path
    /// written.
    /// </summary>
    public static string AppendInterferences(
        string packageDirectory,
        string configuration,
        IReadOnlyList<IrInterference> interferences,
        IReadOnlyList<Gap> gaps)
    {
        EvidencePackage package = Load(packageDirectory);
        Merge(package, configuration, interferences, gaps);
        return Save(packageDirectory, package);
    }

    /// <summary>
    /// The allocator a new capture should use so its id continues past the captures the
    /// package already holds (ids restart at <c>cap:0001</c> in a fresh process).
    /// </summary>
    public static Ids.IdAllocator CaptureIds(EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        var existing = new List<string>(package.Captures.Count);
        foreach (IrCapture capture in package.Captures)
        {
            existing.Add(capture.Id);
        }

        return new Ids.IdAllocator(
            Capture.CaptureService.IdPrefix,
            Ids.IdAllocator.HighestIssued(Capture.CaptureService.IdPrefix, existing));
    }

    /// <summary>
    /// Merges one suppress-test run into <paramref name="package"/>, replacing whatever run
    /// was there.
    ///
    /// A package holds ONE run (<c>rms_suppress_test</c> is a single object in the schema), and
    /// replacing is the only honest merge: a second run is a complete re-test of one document
    /// in one configuration, and keeping the first alongside it would leave the reviewer
    /// reading rows about a model that has since been re-tested.
    /// </summary>
    public static void Merge(EvidencePackage package, SuppressTestRun run)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        if (run == null)
        {
            throw new ArgumentNullException(nameof(run));
        }

        package.RmsSuppressTest = run;
    }

    /// <summary>
    /// Merges one suppress-test run into the package on disk and saves it. Returns the path
    /// written.
    /// </summary>
    public static string AppendSuppressTest(string packageDirectory, SuppressTestRun run)
    {
        EvidencePackage package = Load(packageDirectory);
        Merge(package, run);
        return Save(packageDirectory, package);
    }

    /// <summary>
    /// Merges the confirmed candidate's drawing into <paramref name="package"/> (feature 011,
    /// contracts/confirmed-open.md section 2): the record - <c>opened_by_review: true</c> when the
    /// read opened it, the member omitted otherwise and never false - its <c>documents[]</c> row
    /// and manifest entry, its id in <c>design.drawing_document_ids</c>, its gaps, and the removal
    /// of the document's candidate row. A drawing the package already holds is refused, and the
    /// package is left as it was.
    /// </summary>
    public static void MergeDrawing(
        EvidencePackage package,
        DrawingRecord record,
        Document document,
        ManifestEntry entry,
        IReadOnlyList<Gap> gaps,
        string candidateDocumentId,
        bool openedByReview)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        if (record == null)
        {
            throw new ArgumentNullException(nameof(record));
        }

        if (document == null)
        {
            throw new ArgumentNullException(nameof(document));
        }

        if (entry == null)
        {
            throw new ArgumentNullException(nameof(entry));
        }

        bool already = (package.DrawingRecords ?? new List<DrawingRecord>())
                .Exists(row => string.Equals(row.DocumentId, record.DocumentId, StringComparison.Ordinal))
            || package.Documents.Exists(row => string.Equals(row.DocumentId, document.DocumentId, StringComparison.Ordinal));
        if (already)
        {
            throw new InvalidOperationException(
                $"'{document.Path}' ({record.DocumentId}) is already in this package; a drawing is not merged twice.");
        }

        record.OpenedByReview = openedByReview ? true : (bool?)null;
        (package.DrawingRecords ??= new List<DrawingRecord>()).Add(record);
        package.Documents.Add(document);
        package.Manifest.Entries.Add(entry);
        package.Design.DrawingDocumentIds.Add(record.DocumentId);

        RewordDrawingPhaseGap(package);

        if (gaps != null)
        {
            package.Gaps.AddRange(gaps);
        }

        if (package.DrawingCandidates != null)
        {
            package.DrawingCandidates.RemoveAll(
                row => string.Equals(row.DocumentId, candidateDocumentId, StringComparison.Ordinal));
            if (package.DrawingCandidates.Count == 0)
            {
                package.DrawingCandidates = null;
            }
        }
    }

    /// <summary>
    /// Feature 011 T079 (contracts/confirmed-open.md section 2, 2026-09-23). A review whose
    /// extraction read no drawing carries the dump's standing gap - "No open drawing shows this
    /// design, so no drawing was read natively...", or the listing or profile sentence - beside a
    /// <c>drawing</c> phase row <c>skipped</c>. Once a confirmed drawing is merged the sentence is
    /// false and the row is not: the dump did skip. So the row is left as the dump wrote it, and the
    /// gap is reworded in its own place to say what stays true of the dump and to name every drawing
    /// read afterwards. Every drawing record of such a package is a later read, because
    /// <see cref="PackageWriter"/> writes the gap only when the phase did not run. A package whose
    /// phase ran has no such gap, and nothing is reworded.
    /// </summary>
    private static void RewordDrawingPhaseGap(EvidencePackage package)
    {
        int index = package.Gaps.FindIndex(PackageWriter.IsDrawingPhaseGap);
        if (index < 0)
        {
            return;
        }

        var readAfterwards = new List<(string FileName, bool OpenedByReview)>();
        foreach (DrawingRecord record in package.DrawingRecords ?? new List<DrawingRecord>())
        {
            Document? document = package.Documents.Find(
                row => string.Equals(row.DocumentId, record.DocumentId, StringComparison.Ordinal));
            readAfterwards.Add((document?.FileName ?? record.DocumentId, record.OpenedByReview == true));
        }

        Gap standing = package.Gaps[index];
        package.Gaps[index] = new Gap
        {
            Kind = standing.Kind,
            EntityKind = standing.EntityKind,
            EntityId = standing.EntityId,
            Reason = PackageWriter.DrawingsReadAfterExtractionGapSentence(readAfterwards),
            Error = standing.Error,
        };
    }

    /// <summary>Merges one capture into <paramref name="package"/>. Captures are purely additive.</summary>
    public static void Merge(EvidencePackage package, IrCapture? capture, Gap? gap)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        if (capture != null)
        {
            package.Captures.Add(capture);
        }

        if (gap != null)
        {
            package.Gaps.Add(gap);
        }
    }
}
