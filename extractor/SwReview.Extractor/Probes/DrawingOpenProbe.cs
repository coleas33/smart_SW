using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Probes;

/// <summary>
/// What probe D14 needs of SOLIDWORKS beyond the confirmed open's own seam: the engineer's session
/// around the open - the active document, the window with the focus, the open documents and their
/// save flags. One interop call per member, gated by <see cref="DrawingOpenProbe"/> on the read-only
/// gate under <see cref="DrawingOpenProbe.ReadMembers"/>; <see cref="IDrawingOpenHost"/>'s four are
/// gated by <see cref="DrawingOpenScope"/> itself, as in the product.
/// </summary>
public interface IDrawingOpenProbeHost : IDrawingOpenHost
{
    /// <summary><c>ISldWorks.ActiveDoc</c>: compared by identity, never named.</summary>
    object? ActiveDocument();

    /// <summary><c>ISldWorks.GetDocuments</c>.</summary>
    IReadOnlyList<object> Documents();

    /// <summary><c>IModelDoc2.GetPathName</c>: its extension gives a document's kind; the path is never printed.</summary>
    string? PathOf(object document);

    /// <summary><c>IModelDoc2.GetSaveFlag</c>: true when the document has unsaved changes.</summary>
    bool SaveFlagOf(object document);

    /// <summary>The window with the keyboard focus (<c>user32 GetForegroundWindow</c>), not a SOLIDWORKS call.</summary>
    long ForegroundWindow();
}

/// <summary>What probe D14 runs the confirmed open through: the host, the drawing phase, the read-only gate and the seam's own recorder.</summary>
public sealed class DrawingOpenProbeSeam
{
    public DrawingOpenProbeSeam(
        IDrawingOpenProbeHost host, IDrawingSource drawings, SwGate readGate, RecordingGateObserver seamObserver)
    {
        Host = host ?? throw new ArgumentNullException(nameof(host));
        Drawings = drawings ?? throw new ArgumentNullException(nameof(drawings));
        ReadGate = readGate ?? throw new ArgumentNullException(nameof(readGate));
        SeamObserver = seamObserver ?? throw new ArgumentNullException(nameof(seamObserver));
    }

    public IDrawingOpenProbeHost Host { get; }

    /// <summary>The drawing phase (<see cref="DrawingDumper"/>), which reads the hidden drawing by its own handle.</summary>
    public IDrawingSource Drawings { get; }

    /// <summary>The run's read-only gate, for the session reads around the open.</summary>
    public SwGate ReadGate { get; }

    /// <summary>What <see cref="DrawingOpenScope"/>'s own gate gated: the three keys, when they were.</summary>
    public RecordingGateObserver SeamObserver { get; }
}

/// <summary>
/// Probe D14 (contracts/probes.md section 2, contracts/confirmed-open.md, T077): the one probe that
/// opens a document. Beside a reviewed part or assembly it runs the product's own seam -
/// <see cref="DrawingOpenScope"/> with its switch overridden for this command - on the same-name
/// drawing, and records everything <c>confirmed-open.md</c> requires of it: the open-mode integers as
/// passed, that the active document and the focus never moved, that the hidden drawing's views read,
/// that the file's size, write time and SHA-256 are unchanged and no save flag rose, that the seam
/// closed what it opened and the file is not left locked, the open documents before, during and
/// after, and - with the drawing already open - that no visibility, open or close key was gated.
///
/// It never closes anything itself: the seam closes what it opened, and models the drawing loaded
/// are recorded, never closed. It prints ids, counts and booleans; a sentence of the seam's is
/// printed with the drawing's path, name and stem replaced.
/// </summary>
public static class DrawingOpenProbe
{
    public const string LookupMember = "GetOpenDocumentByName";
    public const string ActiveDocumentMember = "ActiveDoc";
    public const string DocumentsMember = "GetDocuments";
    public const string PathMember = "GetPathName";
    public const string SaveFlagMember = "GetSaveFlag";

    /// <summary>Every member D14 names to the read-only gate; the tests assert each is a read.</summary>
    public static IReadOnlyList<string> ReadMembers { get; } =
        new[] { LookupMember, ActiveDocumentMember, DocumentsMember, PathMember, SaveFlagMember };

    /// <summary>The section's lines for the document at <paramref name="modelPath"/>, after the header.</summary>
    public static IReadOnlyList<string> Run(string? modelPath, DrawingOpenProbeSeam seam, IProbeFiles files)
    {
        if (seam == null)
        {
            throw new ArgumentNullException(nameof(seam));
        }

        if (files == null)
        {
            throw new ArgumentNullException(nameof(files));
        }

        if (string.IsNullOrWhiteSpace(modelPath))
        {
            return new[] { "  the document has never been saved, so it has no same-name drawing; nothing was opened" };
        }

        string candidate = OpenDrawingDiscovery.CandidatePath(modelPath!.Trim());
        ProbeAnswer<bool> exists = ProbeAnswer<bool>.Of(() => files.Exists(candidate));
        if (!exists.Answered)
        {
            return new[] { $"  File.Exists failed ({exists.Failure}), so nothing was opened" };
        }

        if (!exists.Value)
        {
            return new[] { "  no same-name drawing beside the document (File.Exists false), so nothing was opened" };
        }

        return new Sitting(candidate, seam, files).Run();
    }

    /// <summary>One run of the open, with everything read before, during and after it.</summary>
    private sealed class Sitting
    {
        private readonly string _candidate;
        private readonly DrawingOpenProbeSeam _seam;
        private readonly IProbeFiles _files;
        private readonly RecordingOpenHost _recording;

        public Sitting(string candidate, DrawingOpenProbeSeam seam, IProbeFiles files)
        {
            _candidate = candidate;
            _seam = seam;
            _files = files;
            _recording = new RecordingOpenHost(seam.Host);
        }

        private SwGate Gate => _seam.ReadGate;

        private IDrawingOpenProbeHost Host => _seam.Host;

        public IReadOnlyList<string> Run()
        {
            ProbeAnswer<bool> openBefore = ProbeAnswer<bool>.Of(() => Lookup() != null);
            Snapshot before = Take();

            DrawingOpenResult<During>? result = null;
            string? refusal = null;
            string? stopped = null;
            try
            {
                result = new DrawingOpenScope(_recording, _seam.SeamObserver, seatValidated: true)
                    .Read(_candidate, ReadDuring);
            }
            catch (DrawingOpenRefused refused)
            {
                refusal = ProbeText.Redact(refused.Message, _candidate);
            }
            catch (Exception error)
            {
                stopped = ProbeText.Failure(error);
            }

            During? during = result?.Value;
            Snapshot after = Take();
            ProbeAnswer<bool> answersAfter = ProbeAnswer<bool>.Of(() => Lookup() != null);
            ProbeAnswer<bool> exclusive = ProbeAnswer<bool>.Of(() =>
            {
                _files.OpenExclusive(_candidate);
                return true;
            });

            bool alreadyOpen = result != null && !result.OpenedByReview;
            IReadOnlyList<string> keys = _seam.SeamObserver.Members.Where(CallKey.IsQualified).ToList();

            var lines = new List<string>
            {
                "  drawing open before the probe: " + openBefore.Print(ProbeText.Bool),
                OpenDocLine(),
                VisibilityLine(),
                "  outcome: " + Outcome(result, refusal, stopped),
                "  active document unchanged: during " + DuringSame(before.Active, during?.Active, SameObject)
                    + ", after " + Same(before.Active, after.Active, SameObject),
                "  foreground window unchanged: during " + DuringSame(before.Foreground, during?.Foreground, SameWindow)
                    + ", after " + Same(before.Foreground, after.Foreground, SameWindow),
                "  drawing as read: " + DrawingLine(during),
                "  drawing file: " + FileLine(before, after),
                "  save flags: " + SaveFlagLine(before, after),
                "  afterwards: GetOpenDocumentByName answers " + answersAfter.Print(ProbeText.Bool)
                    + "; an exclusive read open " + (exclusive.Answered ? "succeeded" : $"failed ({exclusive.Failure})"),
                "  open documents: before " + CountOf(before) + ", during "
                    + (during == null ? "not taken" : during.Count.Print(ProbeText.Int)) + ", after " + CountOf(after),
                "  left loaded afterwards: " + LeftLoaded(before, after),
                "  seam keys gated: " + (keys.Count == 0 ? "none" : string.Join(", ", keys)),
            };

            if (alreadyOpen)
            {
                lines.Add("  with the drawing already open, no visibility, open or close key was gated: "
                    + ProbeText.Bool(!AnyKeyGated()));
            }

            IReadOnlyList<string> failures = alreadyOpen
                ? AlreadyOpenFailures(before, after, during, answersAfter)
                : OpenFailures(result, before, after, during, answersAfter, exclusive);
            lines.Add("  against confirmed-open.md: "
                + (failures.Count == 0 ? "every answer as required" : "not as required: " + string.Join(", ", failures)));
            return lines;
        }

        // ---- the reads ----------------------------------------------------------------------

        private object? Lookup() => Gate.Call(LookupMember, () => Host.OpenDocument(_candidate));

        private Snapshot Take() => new Snapshot(
            ProbeAnswer<object?>.Of(() => Gate.Call(ActiveDocumentMember, () => Host.ActiveDocument())),
            ProbeAnswer<long>.Of(() => Host.ForegroundWindow()),
            ProbeAnswer<IReadOnlyList<DocumentState>>.Of(ListDocuments),
            ProbeAnswer<ProbeFileState>.Of(() => _files.Read(_candidate)));

        private IReadOnlyList<DocumentState> ListDocuments()
        {
            var states = new List<DocumentState>();
            foreach (object document in Gate.Call(DocumentsMember, () => Host.Documents()))
            {
                ProbeAnswer<string?> path = ProbeAnswer<string?>.Of(() => Gate.Call(PathMember, () => Host.PathOf(document)));
                ProbeAnswer<bool> flag = ProbeAnswer<bool>.Of(() => Gate.Call(SaveFlagMember, () => Host.SaveFlagOf(document)));
                states.Add(new DocumentState(document, path.Answered ? path.Value : null, flag.Answered ? flag.Value : (bool?)null));
            }

            return states;
        }

        /// <summary>
        /// The read the seam runs while the drawing is open: the session around it and the drawing
        /// phase over its own handle. It never throws - a read that fails is its answer - so the seam
        /// always reaches its close with the read's value.
        /// </summary>
        private During ReadDuring(object handle) => new During(
            ProbeAnswer<object?>.Of(() => Gate.Call(ActiveDocumentMember, () => Host.ActiveDocument())),
            ProbeAnswer<long>.Of(() => Host.ForegroundWindow()),
            ProbeAnswer<int>.Of(() => Gate.Call(DocumentsMember, () => Host.Documents()).Count),
            ProbeAnswer<DrawingCounts>.Of(() => ReadDrawing(handle)));

        private DrawingCounts ReadDrawing(object handle)
        {
            var tree = new ComponentTreeResult
            {
                RootDocumentPath = _candidate,
                DesignName = string.Empty,
                ActiveConfiguration = string.Empty,
            };
            var gaps = new GapCollector();
            var scope = new DumpScope(gaps, DrawingProbeRunner.StandardsOptions(), tree);
            scope.Drawings.Add(new ScopedDrawing(_candidate, handle));
            DrawingRecord? record = _seam.Drawings.Dump(scope).FirstOrDefault();
            return new DrawingCounts(record?.Sheets.Count, record?.Sheets.Sum(sheet => sheet.Views.Count), gaps.Count);
        }

        private bool AnyKeyGated() =>
            _seam.SeamObserver.Members.Any(member => DrawingOpenGuard.AllowedKeys.Contains(member));

        // ---- the lines ----------------------------------------------------------------------

        private string OpenDocLine()
        {
            if (_recording.Opens.Count == 0)
            {
                return "  OpenDoc6: not called";
            }

            (int type, int options, string configuration) = _recording.Opens[0];
            return $"  OpenDoc6: type {type}, options {options} (ReadOnly 2 {Flag(options, 2)}, Silent 1 {Flag(options, 1)}, "
                + $"ViewOnly 4 {Flag(options, 4)}, RapidDraft 8 {Flag(options, 8)}, LoadModel 16 {Flag(options, 16)}), "
                + (configuration.Length == 0
                    ? "configuration \"\""
                    : $"configuration named ({configuration.Length} characters)");
        }

        private string VisibilityLine() =>
            _recording.Visibility.Count == 0
                ? "  DocumentVisible: not called"
                : "  DocumentVisible: " + string.Join(
                    ", then ",
                    _recording.Visibility.Select(call => $"{ProbeText.Bool(call.Visible)} (type {call.Type})"));

        private static string Flag(int options, int bit) => (options & bit) != 0 ? "yes" : "no";

        private string Outcome(DrawingOpenResult<During>? result, string? refusal, string? stopped)
        {
            if (refusal != null)
            {
                return "refused: " + refusal;
            }

            if (stopped != null || result == null)
            {
                return "stopped: " + (stopped ?? ProbeText.Unread);
            }

            if (!result.OpenedByReview)
            {
                return "already open, read as it stood and left open";
            }

            return result.Closed
                ? "opened by the probe and closed"
                : "opened by the probe; the close was refused: " + ProbeText.Redact(result.CloseRefusal ?? ProbeText.Unread, _candidate);
        }

        private string DrawingLine(During? during)
        {
            if (during == null)
            {
                return "not read (the drawing was not opened)";
            }

            if (!during.Drawing.Answered)
            {
                return $"not read ({during.Drawing.Failure})";
            }

            DrawingCounts counts = during.Drawing.Value;
            return counts.Sheets == null
                ? $"not read (the drawing phase gave no record, gaps {counts.Gaps})"
                : $"sheets {counts.Sheets}, views {counts.Views}, gaps {counts.Gaps}";
        }

        private static string FileLine(Snapshot before, Snapshot after)
        {
            if (!before.File.Answered)
            {
                return $"unreadable before ({before.File.Failure})";
            }

            if (!after.File.Answered)
            {
                return $"unreadable after ({after.File.Failure})";
            }

            ProbeFileState a = before.File.Value;
            ProbeFileState b = after.File.Value;
            return $"size unchanged {ProbeText.Bool(a.Length == b.Length)}, "
                + $"write time unchanged {ProbeText.Bool(a.LastWriteUtc == b.LastWriteUtc)}, "
                + $"SHA-256 unchanged {ProbeText.Bool(string.Equals(a.Sha256, b.Sha256, StringComparison.Ordinal))}";
        }

        private static string SaveFlagLine(Snapshot before, Snapshot after)
        {
            if (!before.Documents.Answered)
            {
                return $"unread before ({before.Documents.Failure})";
            }

            if (!after.Documents.Answered)
            {
                return $"unread after ({after.Documents.Failure})";
            }

            IReadOnlyList<DocumentState> a = before.Documents.Value;
            IReadOnlyList<DocumentState> b = after.Documents.Value;
            IReadOnlyList<string> raised = Positions(b, (state, earlier) => state.SaveFlag == true && earlier?.SaveFlag != true, a);
            return $"before {a.Count(state => state.SaveFlag == true)} of {a.Count} raised, "
                + $"after {b.Count(state => state.SaveFlag == true)} of {b.Count} raised; "
                + "raised by the run: " + (raised.Count == 0 ? "none" : string.Join(", ", raised));
        }

        private static string LeftLoaded(Snapshot before, Snapshot after)
        {
            if (!before.Documents.Answered || !after.Documents.Answered)
            {
                return ProbeText.Unread;
            }

            IReadOnlyList<string> added = Positions(after.Documents.Value, (state, earlier) => earlier == null, before.Documents.Value);
            return added.Count == 0 ? "none" : string.Join(", ", added);
        }

        /// <summary>
        /// The 1-based positions, in <paramref name="documents"/>, of the documents <paramref name="wanted"/>
        /// answers true for - handed each one and the same document as <paramref name="earlier"/> listed
        /// it, by identity, or null - each with its kind by extension.
        /// </summary>
        private static IReadOnlyList<string> Positions(
            IReadOnlyList<DocumentState> documents,
            Func<DocumentState, DocumentState?, bool> wanted,
            IReadOnlyList<DocumentState> earlier)
        {
            var positions = new List<string>();
            for (int i = 0; i < documents.Count; i++)
            {
                DocumentState state = documents[i];
                DocumentState? before = earlier.FirstOrDefault(row => ReferenceEquals(row.Handle, state.Handle));
                if (wanted(state, before))
                {
                    positions.Add($"{i + 1} ({ProbeText.KindByExtension(state.Path)})");
                }
            }

            return positions;
        }

        private static string CountOf(Snapshot snapshot) =>
            snapshot.Documents.Print(documents => documents.Count.ToString(System.Globalization.CultureInfo.InvariantCulture));

        private static bool SameObject(object? first, object? second) => ReferenceEquals(first, second);

        private static bool SameWindow(long first, long second) => first == second;

        private static string Same<T>(ProbeAnswer<T> first, ProbeAnswer<T> second, Func<T, T, bool> same) =>
            first.Answered && second.Answered
                ? ProbeText.Bool(same(first.Value, second.Value))
                : $"{ProbeText.Unread} ({first.Failure ?? second.Failure})";

        private static string DuringSame<T>(ProbeAnswer<T> before, ProbeAnswer<T>? during, Func<T, T, bool> same) =>
            during == null ? "not taken" : Same(before, during, same);

        // ---- the judgement ------------------------------------------------------------------

        private IReadOnlyList<string> OpenFailures(
            DrawingOpenResult<During>? result,
            Snapshot before,
            Snapshot after,
            During? during,
            ProbeAnswer<bool> answersAfter,
            ProbeAnswer<bool> exclusive)
        {
            var failures = new List<string>();
            if (_recording.Opens.Count == 0 || _recording.Opens.Any(open =>
                    open.Type != DrawingOpenScope.DrawingDocumentType
                    || open.Options != DrawingOpenScope.ReadOnlySilentOptions
                    || open.Configuration.Length != 0))
            {
                failures.Add("the open-mode integers");
            }

            if (result == null || !result.OpenedByReview)
            {
                failures.Add("the open");
            }

            AddSessionFailures(failures, before, after, during);

            if (!before.File.Answered || !after.File.Answered
                || before.File.Value.Length != after.File.Value.Length
                || before.File.Value.LastWriteUtc != after.File.Value.LastWriteUtc
                || !string.Equals(before.File.Value.Sha256, after.File.Value.Sha256, StringComparison.Ordinal))
            {
                failures.Add("the drawing file");
            }

            AddSaveFlagFailure(failures, before, after);

            bool closedWhatItOpened = result == null || !result.OpenedByReview || result.Closed;
            if (!closedWhatItOpened || !answersAfter.Answered || answersAfter.Value)
            {
                failures.Add("the close");
            }

            if (!exclusive.Answered)
            {
                failures.Add("the lock");
            }

            return failures;
        }

        private IReadOnlyList<string> AlreadyOpenFailures(
            Snapshot before, Snapshot after, During? during, ProbeAnswer<bool> answersAfter)
        {
            var failures = new List<string>();
            if (AnyKeyGated())
            {
                failures.Add("the seam keys");
            }

            if (!answersAfter.Answered || !answersAfter.Value)
            {
                failures.Add("left open");
            }

            AddSessionFailures(failures, before, after, during);
            AddSaveFlagFailure(failures, before, after);
            return failures;
        }

        /// <summary>The active document, the focus and the drawing's views - required in both cases, in that order.</summary>
        private static void AddSessionFailures(List<string> failures, Snapshot before, Snapshot after, During? during)
        {
            if (!Unchanged(before.Active, after.Active, during?.Active, SameObject))
            {
                failures.Add("the active document");
            }

            if (!Unchanged(before.Foreground, after.Foreground, during?.Foreground, SameWindow))
            {
                failures.Add("the foreground window");
            }

            if (during == null || !during.Drawing.Answered || !(during.Drawing.Value.Views > 0))
            {
                failures.Add("the drawing's views");
            }
        }

        private static void AddSaveFlagFailure(List<string> failures, Snapshot before, Snapshot after)
        {
            bool raised = !before.Documents.Answered || !after.Documents.Answered
                || Positions(
                    after.Documents.Value,
                    (state, earlier) => state.SaveFlag == true && earlier?.SaveFlag != true,
                    before.Documents.Value).Count > 0;
            if (raised)
            {
                failures.Add("the save flags");
            }
        }

        /// <summary>
        /// Unchanged across the run: read before and after and the same, and - when the drawing was
        /// open for a read during it - read then and the same as before.
        /// </summary>
        private static bool Unchanged<T>(ProbeAnswer<T> before, ProbeAnswer<T> after, ProbeAnswer<T>? during, Func<T, T, bool> same) =>
            before.Answered && after.Answered && same(before.Value, after.Value)
            && (during == null || (during.Answered && same(before.Value, during.Value)));
    }

    /// <summary>The session as one read saw it.</summary>
    private sealed class Snapshot
    {
        public Snapshot(
            ProbeAnswer<object?> active,
            ProbeAnswer<long> foreground,
            ProbeAnswer<IReadOnlyList<DocumentState>> documents,
            ProbeAnswer<ProbeFileState> file)
        {
            Active = active;
            Foreground = foreground;
            Documents = documents;
            File = file;
        }

        public ProbeAnswer<object?> Active { get; }

        public ProbeAnswer<long> Foreground { get; }

        public ProbeAnswer<IReadOnlyList<DocumentState>> Documents { get; }

        public ProbeAnswer<ProbeFileState> File { get; }
    }

    /// <summary>What was read while the drawing was open.</summary>
    private sealed class During
    {
        public During(
            ProbeAnswer<object?> active, ProbeAnswer<long> foreground, ProbeAnswer<int> count, ProbeAnswer<DrawingCounts> drawing)
        {
            Active = active;
            Foreground = foreground;
            Count = count;
            Drawing = drawing;
        }

        public ProbeAnswer<object?> Active { get; }

        public ProbeAnswer<long> Foreground { get; }

        public ProbeAnswer<int> Count { get; }

        public ProbeAnswer<DrawingCounts> Drawing { get; }
    }

    /// <summary>The drawing phase's record of the drawing, as counts; null counts when it gave no record.</summary>
    private sealed class DrawingCounts
    {
        public DrawingCounts(int? sheets, int? views, int gaps)
        {
            Sheets = sheets;
            Views = views;
            Gaps = gaps;
        }

        public int? Sheets { get; }

        public int? Views { get; }

        public int Gaps { get; }
    }

    /// <summary>One open document: its handle (compared by identity), its path (for its kind) and its save flag.</summary>
    private sealed class DocumentState
    {
        public DocumentState(object handle, string? path, bool? saveFlag)
        {
            Handle = handle;
            Path = path;
            SaveFlag = saveFlag;
        }

        public object Handle { get; }

        public string? Path { get; }

        public bool? SaveFlag { get; }
    }

    /// <summary>
    /// The host as the seam calls it, recording what was passed to <c>OpenDoc6</c> and
    /// <c>DocumentVisible</c> before each call - so the integers printed are the ones SOLIDWORKS was
    /// handed, not the constants they were meant to be.
    /// </summary>
    private sealed class RecordingOpenHost : IDrawingOpenHost
    {
        private readonly IDrawingOpenHost _host;

        public RecordingOpenHost(IDrawingOpenHost host)
        {
            _host = host;
        }

        public List<(int Type, int Options, string Configuration)> Opens { get; } =
            new List<(int Type, int Options, string Configuration)>();

        public List<(bool Visible, int Type)> Visibility { get; } = new List<(bool Visible, int Type)>();

        public object? OpenDocument(string path) => _host.OpenDocument(path);

        public void DocumentVisible(bool visible, int documentType)
        {
            Visibility.Add((visible, documentType));
            _host.DocumentVisible(visible, documentType);
        }

        public object? OpenDoc6(string path, int documentType, int options, string configuration, out int errors, out int warnings)
        {
            Opens.Add((documentType, options, configuration ?? string.Empty));
            return _host.OpenDoc6(path, documentType, options, configuration!, out errors, out warnings);
        }

        public void CloseDoc(string path) => _host.CloseDoc(path);
    }
}

/// <summary>
/// The SOLIDWORKS side of <see cref="IDrawingOpenProbeHost"/>: the confirmed open's own host for the
/// seam's four members, and one interop call per session read. Compiled but not unit tested, like
/// <see cref="SwDrawingOpenHost"/>; probe D14 at the seat is its run (T077).
/// </summary>
public sealed class SwDrawingOpenProbeHost : IDrawingOpenProbeHost
{
    private readonly ISldWorks _swApp;
    private readonly SwDrawingOpenHost _open;

    public SwDrawingOpenProbeHost(ISldWorks swApp)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _open = new SwDrawingOpenHost(swApp);
    }

    public object? OpenDocument(string path) => _open.OpenDocument(path);

    public void DocumentVisible(bool visible, int documentType) => _open.DocumentVisible(visible, documentType);

    public object? OpenDoc6(string path, int documentType, int options, string configuration, out int errors, out int warnings) =>
        _open.OpenDoc6(path, documentType, options, configuration, out errors, out warnings);

    public void CloseDoc(string path) => _open.CloseDoc(path);

    public object? ActiveDocument() => _swApp.ActiveDoc;

    public IReadOnlyList<object> Documents() =>
        _swApp.GetDocuments() is object[] documents ? documents : Array.Empty<object>();

    public string? PathOf(object document) => ((IModelDoc2)document).GetPathName();

    public bool SaveFlagOf(object document) => ((IModelDoc2)document).GetSaveFlag();

    public long ForegroundWindow() => GetForegroundWindow().ToInt64();

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();
}
