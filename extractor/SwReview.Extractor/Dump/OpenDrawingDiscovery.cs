using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// One document SOLIDWORKS has open, as discovery sees it (feature 011, contracts/open-drawings.md
/// section 2): its kind, its path, the paths its views reference, and the live handle the
/// <c>drawing</c> phase reads it through. Each read is a delegate the source builds over one
/// gated interop member, called by <see cref="OpenDrawingDiscovery.Discover"/> in the order it
/// needs them - the kind of every document, the path and views of a drawing only - so a document
/// that does not answer costs one gap rather than the whole listing.
/// </summary>
public sealed class OpenDocument
{
    private readonly Func<DocumentKind> _kind;
    private readonly Func<string?> _path;
    private readonly Func<IReadOnlyList<string>> _referencedPaths;

    public OpenDocument(
        object? handle,
        Func<DocumentKind> kind,
        Func<string?> path,
        Func<IReadOnlyList<string>> referencedPaths)
    {
        Handle = handle;
        _kind = kind ?? throw new ArgumentNullException(nameof(kind));
        _path = path ?? throw new ArgumentNullException(nameof(path));
        _referencedPaths = referencedPaths ?? throw new ArgumentNullException(nameof(referencedPaths));
    }

    /// <summary>The live <c>IModelDoc2</c>, typed as object; null in a test that needs none.</summary>
    public object? Handle { get; }

    /// <summary><c>IModelDoc2.GetType</c>.</summary>
    public DocumentKind ReadKind() => _kind();

    /// <summary><c>IModelDoc2.GetPathName</c>; blank for a document that was never saved.</summary>
    public string? ReadPath() => _path();

    /// <summary>
    /// <c>IDrawingDoc.GetViews</c>, then <c>IView.GetReferencedModelName</c> per view, on every
    /// sheet: the path each view shows, blank for a view that shows nothing.
    /// </summary>
    public IReadOnlyList<string> ReadReferencedPaths() => _referencedPaths();
}

/// <summary>One open drawing a review attached: its path, which names it, and its live handle.</summary>
public sealed class AttachedDrawing
{
    public AttachedDrawing(string path, object? handle)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("An attached drawing is named by its path.", nameof(path));
        }

        Path = path;
        Handle = handle;
    }

    /// <summary>The drawing's path as SOLIDWORKS reports it.</summary>
    public string Path { get; }

    /// <summary>The live <c>IModelDoc2</c>, typed as object.</summary>
    public object? Handle { get; }
}

/// <summary>
/// What discovery found (contracts/open-drawings.md sections 3 and 5): the open drawings to read,
/// in order and at most <see cref="OpenDrawingDiscovery.MaxAttachedDrawings"/>; the ones beyond
/// the bound, which the limit gap names; and the same-name drawings beside the design.
/// </summary>
public sealed class AttachedDrawings
{
    public AttachedDrawings(
        bool listed,
        IReadOnlyList<AttachedDrawing> drawings,
        IReadOnlyList<string> notRead,
        IReadOnlyList<DrawingCandidate> candidates)
    {
        Listed = listed;
        Drawings = drawings ?? throw new ArgumentNullException(nameof(drawings));
        NotRead = notRead ?? throw new ArgumentNullException(nameof(notRead));
        Candidates = candidates ?? throw new ArgumentNullException(nameof(candidates));
    }

    /// <summary>
    /// Nothing listed, attached, named or asked about: what every build discovery does not run
    /// in gets.
    /// </summary>
    public static AttachedDrawings None { get; } = new AttachedDrawings(
        false, Array.Empty<AttachedDrawing>(), Array.Empty<string>(), Array.Empty<DrawingCandidate>());

    /// <summary>
    /// Whether the documents open in SOLIDWORKS were listed. False when discovery did not run, or
    /// when the listing failed - and then "no open drawing shows this design" is not known.
    /// </summary>
    public bool Listed { get; }

    /// <summary>The drawings the <c>drawing</c> phase reads, in order.</summary>
    public IReadOnlyList<AttachedDrawing> Drawings { get; }

    /// <summary>The paths of the open drawings that show the design beyond the bound, in order.</summary>
    public IReadOnlyList<string> NotRead { get; }

    /// <summary>The <c>drawing_candidates[]</c> rows, in traversal order.</summary>
    public IReadOnlyList<DrawingCandidate> Candidates { get; }
}

/// <summary>
/// Feature 011 (contracts/open-drawings.md): which of the drawings already open in SOLIDWORKS a
/// review extraction reads with the part or assembly it reviews, and which same-name drawings
/// beside the design it names as candidates. Pure over <see cref="IOpenDrawingSource"/>: every
/// rule is here and tested with fakes; <see cref="SwOpenDrawingReader"/> is the interop.
///
/// <b>Nothing is opened, loaded, activated or listed.</b> A drawing is read only when SOLIDWORKS
/// already has it open and one of its views shows a document the traversal reached; a candidate
/// is one existence check of one file name per document, never read.
/// </summary>
public static class OpenDrawingDiscovery
{
    /// <summary>The most open drawings one extraction reads (section 3).</summary>
    public const int MaxAttachedDrawings = 10;

    /// <summary>The extension a candidate is asked about with, and the only one.</summary>
    private const string CandidateExtension = ".SLDDRW";

    /// <summary>
    /// Section 1: discovery runs under the <c>Full</c> profile for a part or assembly root, and
    /// never otherwise - a drawing root reads itself (feature 006), and the Standards and Model
    /// check extractions never discover a drawing (006 FR-025, amended for <c>Full</c> only).
    /// </summary>
    public static bool RunsFor(ComponentTreeResult tree, DumpOptions options)
    {
        if (tree == null)
        {
            throw new ArgumentNullException(nameof(tree));
        }

        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        return options.Profile == DumpProfile.Full
            && (tree.RootDocumentKind == DocumentKind.Part
                || tree.RootDocumentKind == DocumentKind.Assembly);
    }

    /// <summary>
    /// Section 5: the one file a model's candidate is: <c>&lt;directory of its path&gt;\&lt;file
    /// stem&gt;.SLDDRW</c>. Discovery asks about it, and the confirmed open recomputes it from the
    /// document's own path to check the row it was handed (contracts/confirmed-open.md section 2).
    /// </summary>
    public static string CandidatePath(string modelPath)
    {
        if (string.IsNullOrWhiteSpace(modelPath))
        {
            throw new ArgumentException("A candidate is asked about beside a model's path.", nameof(modelPath));
        }

        string directory = Path.GetDirectoryName(modelPath) ?? string.Empty;
        return Path.Combine(directory, Path.GetFileNameWithoutExtension(modelPath) + CandidateExtension);
    }

    /// <summary>
    /// Section 3: whether two paths name the same document as discovery compares them - both put
    /// through <see cref="Path.GetFullPath(string)"/>, compared ordinal-ignore-case. A path that is
    /// not rooted (a file name alone) names no document and matches nothing, whatever the current
    /// directory is.
    /// </summary>
    public static bool SamePath(string? first, string? second)
    {
        string? a = Key(first);
        string? b = Key(second);
        return a != null && b != null && string.Equals(a, b, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// The rule that ties a view's referenced path to a document of the package, for an attached
    /// or confirmed drawing (<see cref="ScopedDrawing.ReviewedDocumentId"/>): the id of the
    /// document whose path <see cref="SamePath"/> matches, or null for a path outside the review.
    /// One rule with discovery's matching, so the drawing phase and discovery agree on which views
    /// show the design.
    /// </summary>
    public static Func<string, string?> DocumentResolver(IEnumerable<string> documentPaths)
    {
        if (documentPaths == null)
        {
            throw new ArgumentNullException(nameof(documentPaths));
        }

        return DocumentResolver(documentPaths.Select(path => (path, DocumentIds.For(path))));
    }

    /// <summary>
    /// <see cref="DocumentResolver(IEnumerable{string})"/> over documents that already carry their
    /// ids - a package's <c>documents[]</c> - so a path ties to the id the package gave it.
    /// </summary>
    public static Func<string, string?> DocumentResolver(IEnumerable<(string Path, string DocumentId)> documents)
    {
        if (documents == null)
        {
            throw new ArgumentNullException(nameof(documents));
        }

        var byKey = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach ((string path, string documentId) in documents)
        {
            string? key = Key(path);
            if (key != null && !byKey.ContainsKey(key))
            {
                byKey[key] = documentId;
            }
        }

        return path =>
        {
            string? key = Key(path);
            return key != null && byKey.TryGetValue(key, out string id) ? id : null;
        };
    }

    /// <summary>
    /// The comparison key of a path: its full path, or null when it is blank or not rooted. A
    /// path <see cref="Path.GetFullPath(string)"/> refuses (a character the file system does not
    /// allow) is compared as written rather than dropped.
    /// </summary>
    internal static string? Key(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        try
        {
            return Path.IsPathRooted(path) ? Path.GetFullPath(path) : null;
        }
        catch (Exception ex) when (ex is ArgumentException || ex is NotSupportedException
            || ex is PathTooLongException || ex is SecurityException)
        {
            return path;
        }
    }

    /// <summary>
    /// Sections 2, 3 and 5 over one listing of the open documents: the drawings that show the
    /// design, in order and bounded, and the candidates, with every gap the contract names
    /// recorded in <paramref name="gaps"/>. Under a profile or root that does not discover
    /// (<see cref="RunsFor"/>), the source is asked nothing.
    /// </summary>
    public static AttachedDrawings Discover(
        ComponentTreeResult tree, IOpenDrawingSource source, DumpOptions options, GapCollector gaps)
    {
        if (source == null)
        {
            throw new ArgumentNullException(nameof(source));
        }

        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        if (!RunsFor(tree, options))
        {
            return AttachedDrawings.None;
        }

        IReadOnlyList<ReachedDocument> reached = Reached(tree);
        var indexByKey = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (ReachedDocument document in reached)
        {
            indexByKey[document.Key] = document.Index;
        }

        IReadOnlyList<OpenDrawing>? open = Examine(source, gaps, indexByKey);
        bool listed = open != null;
        open ??= Array.Empty<OpenDrawing>();

        List<OpenDrawing> showing = open
            .Where(drawing => drawing.LowestIndex != null)
            .OrderBy(drawing => drawing.ReferencesRoot ? 0 : 1)
            .ThenBy(drawing => drawing.LowestIndex!.Value)
            .ThenBy(drawing => drawing.Key, StringComparer.Ordinal)
            .ToList();

        List<OpenDrawing> attached = showing.Take(MaxAttachedDrawings).ToList();
        List<OpenDrawing> beyond = showing.Skip(MaxAttachedDrawings).ToList();

        if (beyond.Count > 0)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "drawing_attachment_limit",
                null,
                $"{beyond.Count} more open drawings show documents of this design and were not read: "
                + string.Join(", ", beyond.Select(drawing => drawing.Path))
                + ". Close some and extract again to read them.",
                null);
        }

        // A view of an attached drawing that shows a document outside the design is the drawing
        // phase's to name: its gap belongs to that view's dvw id, which exists only once the phase
        // numbers the view (ScopedDrawing.ReviewedDocumentId, DrawingDumper).

        IReadOnlyList<DrawingCandidate> candidates = Candidates(
            reached, attached, open, source, gaps);

        return new AttachedDrawings(
            listed,
            attached.Select(drawing => new AttachedDrawing(drawing.Path, drawing.Handle)).ToList(),
            beyond.Select(drawing => drawing.Path).ToList(),
            candidates);
    }

    /// <summary>
    /// Every distinct document the traversal reached, root first then in traversal order, each
    /// with its index: the order candidates are written in and the order drawings are sorted by.
    /// A document with no path is not reached (it cannot be matched or asked about).
    /// </summary>
    private static IReadOnlyList<ReachedDocument> Reached(ComponentTreeResult tree)
    {
        var reached = new List<ReachedDocument>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void Reach(string path, DocumentKind kind)
        {
            string? key = Key(path);
            if (key != null && seen.Add(key))
            {
                reached.Add(new ReachedDocument(path, key, reached.Count, kind));
            }
        }

        Reach(tree.RootDocumentPath, tree.RootDocumentKind!.Value);
        foreach (ComponentNode node in tree.Nodes)
        {
            Reach(node.DocumentPath, node.DocumentKind);
        }

        return reached;
    }

    /// <summary>
    /// Section 2: one listing, then per document its kind, and per drawing its path and the paths
    /// its views show. Each failure is one <c>drawing_discovery</c> gap and the next document is
    /// read. The drawings come back examined - matched or not - because the candidate rule needs
    /// to know which same-name files are already open. Null when the listing itself failed.
    /// </summary>
    private static IReadOnlyList<OpenDrawing>? Examine(
        IOpenDrawingSource source, GapCollector gaps, IReadOnlyDictionary<string, int> indexByKey)
    {
        var drawings = new List<OpenDrawing>();

        IReadOnlyList<OpenDocument>? documents = gaps.TryStep(
            "drawing_discovery",
            null,
            "The documents open in SOLIDWORKS could not be listed, so no open drawing was read with "
            + "this design.",
            () => source.OpenDocuments());

        if (documents == null)
        {
            return null;
        }

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < documents.Count; i++)
        {
            OpenDocument document = documents[i];
            int position = i + 1;

            DocumentKind? kind = null;
            if (!gaps.TryStep(
                "drawing_discovery",
                null,
                $"The kind of open document {position} could not be read, so it was not examined as "
                + "a drawing of this design.",
                () => { kind = document.ReadKind(); }))
            {
                continue;
            }

            if (kind != DocumentKind.Drawing)
            {
                continue;
            }

            string? path = null;
            if (!gaps.TryStep(
                "drawing_discovery",
                null,
                $"The path of open document {position}, a drawing, could not be read, so it was not "
                + "examined as a drawing of this design.",
                () => { path = document.ReadPath(); }))
            {
                continue;
            }

            bool saved = !string.IsNullOrWhiteSpace(path);
            string? key = saved ? Key(path) ?? path : null;
            if (key != null && !seen.Add(key))
            {
                // Listed twice: one drawing, examined once.
                continue;
            }

            IReadOnlyList<string>? references = gaps.TryStep(
                "drawing_discovery",
                saved ? DocumentIds.For(path!) : null,
                saved
                    ? $"The views of the open drawing '{path}' could not be read, so whether it shows "
                        + "this design is unknown and it was not read."
                    : $"The views of open document {position}, an unsaved drawing, could not be read.",
                () => document.ReadReferencedPaths());

            OpenDrawing examined = Match(path, key, document.Handle, references, indexByKey);

            if (!saved)
            {
                if (examined.LowestIndex != null)
                {
                    gaps.Add(
                        GapKind.NotExtracted,
                        "drawing_discovery",
                        null,
                        $"The drawing listed as open document {position} shows this design but has "
                        + "never been saved, so it has no path to identify it by and was not read. Save "
                        + "it and extract again to include it.",
                        null);
                }

                continue;
            }

            drawings.Add(examined);
        }

        return drawings;
    }

    /// <summary>
    /// Section 3's matching of one drawing's view paths against the reached documents: every
    /// traversal index it shows. Blank view paths show nothing, and a path that is not one of the
    /// reached documents shows nothing of the design.
    /// </summary>
    private static OpenDrawing Match(
        string? path,
        string? key,
        object? handle,
        IReadOnlyList<string>? references,
        IReadOnlyDictionary<string, int> indexByKey)
    {
        var shown = new HashSet<int>();
        foreach (string reference in references ?? Array.Empty<string>())
        {
            string? referenceKey = Key(reference);
            if (referenceKey != null && indexByKey.TryGetValue(referenceKey, out int index))
            {
                shown.Add(index);
            }
        }

        return new OpenDrawing(path ?? string.Empty, key, handle, references != null, shown);
    }

    /// <summary>
    /// Section 5: for each part or assembly document no attached drawing shows, its same-name
    /// drawing - asked about once, unless it is already open, when it is either read already, named
    /// in the limit gap, or shows none of the design and is named in its own gap.
    /// </summary>
    private static IReadOnlyList<DrawingCandidate> Candidates(
        IReadOnlyList<ReachedDocument> reached,
        IReadOnlyList<OpenDrawing> attached,
        IReadOnlyList<OpenDrawing> open,
        IOpenDrawingSource source,
        GapCollector gaps)
    {
        var shown = new HashSet<int>(attached.SelectMany(drawing => drawing.ShownIndexes));
        var openByKey = new Dictionary<string, OpenDrawing>(StringComparer.OrdinalIgnoreCase);
        foreach (OpenDrawing drawing in open)
        {
            if (drawing.Key != null)
            {
                openByKey[drawing.Key] = drawing;
            }
        }

        var candidates = new List<DrawingCandidate>();
        foreach (ReachedDocument document in reached)
        {
            if ((document.Kind != DocumentKind.Part && document.Kind != DocumentKind.Assembly)
                || shown.Contains(document.Index))
            {
                continue;
            }

            string documentId = DocumentIds.For(document.Path);
            string fileName = Path.GetFileName(document.Path);

            string? candidatePath = null;
            bool? exists = null;
            bool asked = gaps.TryStep(
                "drawing_candidate",
                documentId,
                $"Whether a drawing with the name of {fileName} sits beside it could not be checked, "
                + "so none is named as a candidate.",
                () =>
                {
                    candidatePath = CandidatePath(document.Path);
                    string? candidateKey = Key(candidatePath);
                    if (candidateKey != null && openByKey.TryGetValue(candidateKey, out OpenDrawing? already))
                    {
                        if (already.ViewsRead && already.LowestIndex == null)
                        {
                            gaps.Add(
                                GapKind.NotExtracted,
                                "drawing_candidate",
                                documentId,
                                $"the open drawing '{candidatePath}' has the name of {fileName} but shows "
                                + "none of this design, so it was not read",
                                null);
                        }

                        return;
                    }

                    exists = source.FileExists(candidatePath);
                });

            if (asked && exists == true)
            {
                candidates.Add(new DrawingCandidate
                {
                    DocumentId = documentId,
                    Path = candidatePath!,
                    Reason = DrawingCandidateReason.SameNameBesideModel,
                });
            }
        }

        return candidates;
    }

    /// <summary>One document the traversal reached.</summary>
    private sealed class ReachedDocument
    {
        public ReachedDocument(string path, string key, int index, DocumentKind kind)
        {
            Path = path;
            Key = key;
            Index = index;
            Kind = kind;
        }

        public string Path { get; }

        public string Key { get; }

        public int Index { get; }

        public DocumentKind Kind { get; }
    }

    /// <summary>One open drawing as discovery examined it.</summary>
    private sealed class OpenDrawing
    {
        public OpenDrawing(
            string path,
            string? key,
            object? handle,
            bool viewsRead,
            IReadOnlyCollection<int> shownIndexes)
        {
            Path = path;
            Key = key;
            Handle = handle;
            ViewsRead = viewsRead;
            ShownIndexes = shownIndexes;
        }

        public string Path { get; }

        /// <summary>The comparison key; null for an unsaved drawing.</summary>
        public string? Key { get; }

        public object? Handle { get; }

        /// <summary>Whether its views answered; false means whether it shows the design is unknown.</summary>
        public bool ViewsRead { get; }

        /// <summary>Every traversal index of a reached document one of its views shows.</summary>
        public IReadOnlyCollection<int> ShownIndexes { get; }

        /// <summary>The lowest traversal index it shows; null when it shows none of the design.</summary>
        public int? LowestIndex => ShownIndexes.Count == 0 ? (int?)null : ShownIndexes.Min();

        /// <summary>Whether it shows the root document, which is traversal index 0.</summary>
        public bool ReferencesRoot => ShownIndexes.Contains(0);
    }
}
