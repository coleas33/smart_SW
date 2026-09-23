using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Feature 011 (contracts/confirmed-open.md section 2, owner 2026-09-23): the host side of
/// <c>drawing.read</c>. When the engineer confirms the candidate question, the backend asks, once
/// per candidate, for one document's candidate to be read into one review's package; this class
/// holds every rule of that read over its seams, so each is tested with fakes and no seat.
///
/// Everything is resolved from the host's own records, and any step that fails refuses with the
/// sentence it is answered with and <b>opens nothing</b>:
///   1. the run id names a review this host started, whose run folder holds its package;
///   2. the package's root document is the document this bridge is attached to;
///   3. the document is a part or assembly of that package, with a candidate row;
///   4. the row's path is the drawing beside the document by discovery's own rule
///      (<see cref="OpenDrawingDiscovery.CandidatePath"/>), compared as discovery compares, and
///      the file exists;
///   5. the package holds fewer than ten drawing records.
///
/// Then the drawing is opened through the guarded seam (<see cref="DrawingOpenScope"/>) when it is
/// not open, read by the drawing phase with every drawing id continuing the package's own and each
/// view tied to the package's documents by discovery's matching, given its <c>documents[]</c> row
/// and manifest entry, and closed again when the seam opened it; the package in the run folder is
/// updated through <see cref="PackageAppender.MergeDrawing"/>. A read that throws is closed and
/// merges nothing.
/// </summary>
public sealed class ConfirmedDrawingRead : IConfirmedDrawingSource
{
    private readonly Func<string, string?> _runFolderOf;
    private readonly string? _attachedDocumentPath;
    private readonly Func<string, bool> _fileExists;
    private readonly DrawingOpenScope _open;
    private readonly IDrawingSource _drawings;
    private readonly IDocumentSource _documents;
    private readonly IManifestSource _manifest;

    /// <param name="runFolderOf">
    /// The run folder of a review this host started, from its own session records, or null when
    /// the run id names none. Never a path read from the request.
    /// </param>
    /// <param name="attachedDocumentPath">The document this bridge is attached to.</param>
    /// <param name="fileExists">Whether a file exists; nothing is read of it.</param>
    /// <param name="open">The guarded seam that opens, and closes, the drawing.</param>
    /// <param name="drawings">The drawing phase (<see cref="DrawingDumper"/>).</param>
    /// <param name="documents">The document phase, for the drawing's row (<see cref="PropertyDumper"/>).</param>
    /// <param name="manifest">The manifest, for the drawing's entry (<see cref="ManifestBuilder"/>).</param>
    public ConfirmedDrawingRead(
        Func<string, string?> runFolderOf,
        string? attachedDocumentPath,
        Func<string, bool> fileExists,
        DrawingOpenScope open,
        IDrawingSource drawings,
        IDocumentSource documents,
        IManifestSource manifest)
    {
        _runFolderOf = runFolderOf ?? throw new ArgumentNullException(nameof(runFolderOf));
        _attachedDocumentPath = attachedDocumentPath;
        _fileExists = fileExists ?? throw new ArgumentNullException(nameof(fileExists));
        _open = open ?? throw new ArgumentNullException(nameof(open));
        _drawings = drawings ?? throw new ArgumentNullException(nameof(drawings));
        _documents = documents ?? throw new ArgumentNullException(nameof(documents));
        _manifest = manifest ?? throw new ArgumentNullException(nameof(manifest));
    }

    /// <inheritdoc />
    public ConfirmedDrawingResult Read(string runId, string documentId)
    {
        if (string.IsNullOrWhiteSpace(runId))
        {
            throw new ConfirmedDrawingRefused("No review was named, so no drawing was opened.");
        }

        if (string.IsNullOrWhiteSpace(documentId))
        {
            throw new ConfirmedDrawingRefused("No document was named, so no drawing was opened.");
        }

        // 1. The run, from the host's own records.
        string folder = _runFolderOf(runId)
            ?? throw new ConfirmedDrawingRefused(
                $"'{runId}' is not a review this SOLIDWORKS session started, so no drawing was opened.");
        if (!File.Exists(PackageAppender.PathIn(folder)))
        {
            throw new ConfirmedDrawingRefused(
                $"The review '{runId}' has no package in its run folder, so no drawing was opened.");
        }

        EvidencePackage package = PackageAppender.Load(folder);

        // 2. The package is of the document this bridge is attached to.
        Document? root = package.Documents.FirstOrDefault(
            row => string.Equals(row.DocumentId, package.Design.RootAssemblyDocumentId, StringComparison.Ordinal));
        if (root == null || !OpenDrawingDiscovery.SamePath(root.Path, _attachedDocumentPath))
        {
            throw new ConfirmedDrawingRefused(
                $"The review '{runId}' is of '{root?.Path ?? package.Design.RootAssemblyDocumentId}', which is "
                + $"not the document this bridge is attached to ('{_attachedDocumentPath ?? "none"}'), so no "
                + "drawing was opened.");
        }

        // 3. A part or assembly of the package, with a candidate row.
        Document document = package.Documents.FirstOrDefault(
                row => string.Equals(row.DocumentId, documentId, StringComparison.Ordinal))
            ?? throw new ConfirmedDrawingRefused(
                $"'{documentId}' is not a document of the review '{runId}', so no drawing was opened.");
        if (document.Kind != DocumentKind.Part && document.Kind != DocumentKind.Assembly)
        {
            throw new ConfirmedDrawingRefused(
                $"'{documentId}' is a drawing; only the candidate drawing of a part or an assembly is read, "
                + "so nothing was opened.");
        }

        DrawingCandidate candidate = package.DrawingCandidates?.FirstOrDefault(
                row => string.Equals(row.DocumentId, documentId, StringComparison.Ordinal))
            ?? throw new ConfirmedDrawingRefused(
                $"The review '{runId}' names no candidate drawing for '{document.FileName}', so nothing was opened.");

        // 4. The row is discovery's own rule, and the file is there.
        string expected = OpenDrawingDiscovery.CandidatePath(document.Path);
        if (!OpenDrawingDiscovery.SamePath(candidate.Path, expected))
        {
            throw new ConfirmedDrawingRefused(
                $"The candidate row for '{document.FileName}' names '{candidate.Path}', which is not the "
                + $"drawing beside it ('{expected}'), so it was not opened.");
        }

        if (!_fileExists(candidate.Path))
        {
            throw new ConfirmedDrawingRefused(
                $"The candidate drawing '{candidate.Path}' no longer exists, so it was not opened.");
        }

        // A drawing this package already holds is not read twice.
        string drawingId = DocumentIds.For(candidate.Path);
        if (package.Documents.Exists(row => string.Equals(row.DocumentId, drawingId, StringComparison.Ordinal)))
        {
            throw new ConfirmedDrawingRefused(
                $"'{candidate.Path}' is already a document of the review '{runId}', so it was not opened again.");
        }

        // 5. The bound discovery keeps.
        if ((package.DrawingRecords?.Count ?? 0) >= OpenDrawingDiscovery.MaxAttachedDrawings)
        {
            throw new ConfirmedDrawingRefused("the package already holds ten drawings, so this one was not opened");
        }

        DrawingOpenResult<ReadDrawing> result;
        try
        {
            result = _open.Read(candidate.Path, handle => ReadOne(package, root.Path, candidate.Path, handle));
        }
        catch (DrawingOpenRefused refusal)
        {
            throw new ConfirmedDrawingRefused(refusal.Message);
        }

        ReadDrawing read = result.Value;
        var gaps = new List<Gap>(read.Gaps);
        if (result.CloseRefusal != null)
        {
            gaps.Add(new Gap
            {
                Kind = GapKind.NotExtracted,
                EntityKind = "drawing_confirmed_open",
                EntityId = read.Record.DocumentId,
                Reason = result.CloseRefusal,
            });
        }

        PackageAppender.MergeDrawing(
            package, read.Record, read.Document, read.Entry, gaps, documentId, result.OpenedByReview);
        PackageAppender.Save(folder, package);

        return new ConfirmedDrawingResult
        {
            DocumentId = documentId,
            DrawingDocumentId = read.Record.DocumentId,
            Opened = result.OpenedByReview,
            Closed = result.Closed,
            Sheets = read.Record.Sheets.Count,
            Gaps = gaps.Count,
        };
    }

    /// <summary>
    /// The read itself, while the drawing is open: the drawing phase over this one drawing - its
    /// own handle, the package's documents to tie its views to, ids continuing the package's - and
    /// its document row and manifest entry.
    /// </summary>
    private ReadDrawing ReadOne(EvidencePackage package, string rootPath, string path, object handle)
    {
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = rootPath,
            DesignName = package.Design.Name,
            ActiveConfiguration = package.Design.ActiveConfiguration,
        };

        var gaps = new GapCollector();
        var scope = new DumpScope(
            gaps,
            new DumpOptions { Profile = DumpProfile.Full },
            tree,
            DrawingIdAllocators.ContinuingFrom(package));
        scope.Drawings.Add(new ScopedDrawing(
            path,
            handle,
            OpenDrawingDiscovery.DocumentResolver(package.Documents.Select(row => (row.Path, row.DocumentId)))));

        string drawingId = scope.DocumentId(path);
        IReadOnlyList<DrawingRecord> records = _drawings.Dump(scope);
        DrawingRecord record = records.FirstOrDefault(row => string.Equals(row.DocumentId, drawingId, StringComparison.Ordinal))
            ?? throw new ConfirmedDrawingRefused(
                $"'{Path.GetFileName(path)}' was opened but could not be read as a drawing: "
                + string.Join(" ", gaps.Gaps.Select(gap => gap.Reason)));

        Document document = _documents.Dump(scope, new[] { path }).Single();
        ManifestEntry entry = _manifest.Build(scope, new[] { document }).Entries.Single();

        return new ReadDrawing(record, document, entry, gaps.Gaps);
    }

    /// <summary>What one read produced, before it is merged.</summary>
    private sealed class ReadDrawing
    {
        public ReadDrawing(DrawingRecord record, Document document, ManifestEntry entry, IReadOnlyList<Gap> gaps)
        {
            Record = record;
            Document = document;
            Entry = entry;
            Gaps = gaps;
        }

        public DrawingRecord Record { get; }

        public Document Document { get; }

        public ManifestEntry Entry { get; }

        public IReadOnlyList<Gap> Gaps { get; }
    }
}
