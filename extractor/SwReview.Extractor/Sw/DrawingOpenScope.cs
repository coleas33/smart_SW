using System;
using System.IO;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Guard;

namespace SwReview.Extractor.Sw;

/// <summary>
/// What <see cref="DrawingOpenScope"/> needs SOLIDWORKS to answer, with no interop type in the
/// signature, so every rule of the confirmed drawing's open is tested with fakes
/// (<see cref="SwDrawingOpenHost"/> is the SOLIDWORKS side). Each member is one interop call, and
/// the scope gates each one under its key.
/// </summary>
public interface IDrawingOpenHost
{
    /// <summary><c>ISldWorks.GetOpenDocumentByName(path)</c>: the open document, or null.</summary>
    object? OpenDocument(string path);

    /// <summary><c>ISldWorks.DocumentVisible(visible, documentType)</c>.</summary>
    void DocumentVisible(bool visible, int documentType);

    /// <summary><c>ISldWorks.OpenDoc6(path, documentType, options, configuration, ref errors, ref warnings)</c>.</summary>
    object? OpenDoc6(string path, int documentType, int options, string configuration, out int errors, out int warnings);

    /// <summary><c>ISldWorks.CloseDoc(path)</c>.</summary>
    void CloseDoc(string path);
}

/// <summary>A confirmed drawing's read, and what the seam did around it.</summary>
public sealed class DrawingOpenResult<T>
{
    public DrawingOpenResult(T value, bool openedByReview, bool closed, string? closeRefusal)
    {
        Value = value;
        OpenedByReview = openedByReview;
        Closed = closed;
        CloseRefusal = closeRefusal;
    }

    /// <summary>What the read returned.</summary>
    public T Value { get; }

    /// <summary>True when the seam opened the drawing; false when it was already open.</summary>
    public bool OpenedByReview { get; }

    /// <summary>True when the seam closed what it opened.</summary>
    public bool Closed { get; }

    /// <summary>Why the seam did not close a drawing it opened, or null.</summary>
    public string? CloseRefusal { get; }
}

/// <summary>A refusal of the seam, with the sentence the engineer is told.</summary>
public sealed class DrawingOpenRefused : InvalidOperationException
{
    public DrawingOpenRefused(string message)
        : base(message)
    {
    }

    public DrawingOpenRefused(string message, Exception inner)
        : base(message, inner)
    {
    }
}

/// <summary>
/// Feature 011 (contracts/confirmed-open.md sections 3 and 4, owner 2026-09-23). The one product
/// path that opens a drawing: a candidate the engineer confirmed, opened read-only and hidden,
/// read, and closed again when - and only when - this seam opened it.
///
///   * <b>Already open</b>: no visibility call, no open, no close; the drawing is read as it
///     stands and <see cref="DrawingOpenResult{T}.OpenedByReview"/> is false.
///   * <b>Not open</b>: <c>DocumentVisible(false, 3)</c>, <c>OpenDoc6(path, 3, 3, "")</c>, and
///     <c>DocumentVisible(true, 3)</c> in a <c>finally</c>, also when the open throws or answers
///     null - each of those a refusal naming the file and its load errors.
///   * <b>Close</b>: in a <c>finally</c> around the read, only when this seam opened the drawing,
///     and only after <c>GetOpenDocumentByName(path)</c> answers the same COM identity the open
///     returned; otherwise nothing is closed and the result says why. No other document is ever
///     closed, and never a model the drawing loaded.
///
/// Every call goes through a gate built on <see cref="DrawingOpenGuard"/>, so the three keys are
/// the whole of what it may do beyond reading; nothing it calls activates, rebuilds, saves or
/// selects. Shipped off (<see cref="SeatValidated"/>) until probe D14 passes at the seat (T077).
/// </summary>
public sealed class DrawingOpenScope
{
    /// <summary><c>swDocumentTypes_e.swDocDRAWING</c>.</summary>
    public const int DrawingDocumentType = 3;

    /// <summary>
    /// <c>swOpenDocOptions_e</c>: ReadOnly 2 | Silent 1 - never ViewOnly 4, RapidDraft 8 or
    /// LoadModel 16.
    /// </summary>
    public const int ReadOnlySilentOptions = 3;

    private const string DrawingExtension = ".slddrw";

    private const string LookupMember = "GetOpenDocumentByName";

    private readonly IDrawingOpenHost _host;
    private readonly SwGate _gate;
    private readonly bool _seatValidated;

    /// <summary>The seam as shipped: <see cref="SeatValidated"/> decides whether a closed drawing may be opened.</summary>
    public DrawingOpenScope(IDrawingOpenHost host, ISwGateObserver? observer = null)
        : this(host, observer, SeatValidated)
    {
    }

    /// <summary>
    /// The seam with the switch given: <c>true</c> only for probe D14 and the tests of the open
    /// itself (contracts/confirmed-open.md section 4).
    /// </summary>
    public DrawingOpenScope(IDrawingOpenHost host, ISwGateObserver? observer, bool seatValidated)
    {
        _host = host ?? throw new ArgumentNullException(nameof(host));
        _gate = new SwGate(new CircuitBreaker(), new DrawingOpenGuard()) { Observer = observer };
        _seatValidated = seatValidated;
    }

    /// <summary>
    /// False until probe D14 records, at a licensed seat, that the open neither changes nor saves
    /// nor locks the drawing and leaves the engineer's window where it was (T077 sets it true in a
    /// commit of its own citing the probe record). While it is false a closed drawing is refused;
    /// a drawing already open is still read, since reading it opens nothing.
    /// </summary>
    public static bool SeatValidated => false;

    /// <summary>The sentence a closed drawing is refused with while <see cref="SeatValidated"/> is false.</summary>
    public const string NotValidatedSentence =
        "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 probe D14)";

    /// <summary>
    /// Reads the drawing at <paramref name="path"/> with <paramref name="read"/>, opening it
    /// read-only and hidden when it is not open and closing it again only when this seam opened
    /// it. A refusal is a <see cref="DrawingOpenRefused"/> with the sentence to show; an exception
    /// from <paramref name="read"/> propagates after the close.
    /// </summary>
    public DrawingOpenResult<T> Read<T>(string path, Func<object, T> read)
    {
        if (read == null)
        {
            throw new ArgumentNullException(nameof(read));
        }

        if (string.IsNullOrWhiteSpace(path) || !path.EndsWith(DrawingExtension, StringComparison.OrdinalIgnoreCase))
        {
            throw new DrawingOpenRefused(
                $"'{path}' is not a drawing file (.SLDDRW), so it was not opened.");
        }

        object? existing = _gate.Call(LookupMember, () => _host.OpenDocument(path));
        if (existing != null)
        {
            return new DrawingOpenResult<T>(read(existing), openedByReview: false, closed: false, closeRefusal: null);
        }

        if (!_seatValidated)
        {
            throw new DrawingOpenRefused(NotValidatedSentence);
        }

        object opened = Open(path);

        bool closed = false;
        string? closeRefusal = null;
        T value;
        try
        {
            value = read(opened);
        }
        finally
        {
            closeRefusal = Close(path, opened);
            closed = closeRefusal == null;
        }

        return new DrawingOpenResult<T>(value, openedByReview: true, closed, closeRefusal);
    }

    /// <summary>Hide, open read-only, restore: the restore in a <c>finally</c>, whatever the open did.</summary>
    private object Open(string path)
    {
        string fileName = Path.GetFileName(path);
        int errors = 0;
        int warnings = 0;
        object? opened;

        _gate.Call(DrawingOpenGuard.DocumentVisibleKey, () => _host.DocumentVisible(false, DrawingDocumentType));
        try
        {
            opened = _gate.Call(
                DrawingOpenGuard.OpenDocKey,
                () => _host.OpenDoc6(path, DrawingDocumentType, ReadOnlySilentOptions, string.Empty, out errors, out warnings));
        }
        catch (Exception error) when (!(error is MutatingCallError) && !(error is CircuitOpenError))
        {
            throw new DrawingOpenRefused(
                $"SOLIDWORKS could not open '{fileName}' read-only ({FileLoadErrors.Describe(errors, warnings)}): "
                + error.Message,
                error);
        }
        finally
        {
            _gate.Call(DrawingOpenGuard.DocumentVisibleKey, () => _host.DocumentVisible(true, DrawingDocumentType));
        }

        return opened ?? throw new DrawingOpenRefused(
            $"SOLIDWORKS could not open '{fileName}' read-only ({FileLoadErrors.Describe(errors, warnings)})");
    }

    /// <summary>
    /// Closes what this seam opened, after checking SOLIDWORKS still answers the path with the
    /// very document the open returned; returns why it did not close, or null when it closed.
    /// </summary>
    private string? Close(string path, object opened)
    {
        object? current = _gate.Call(LookupMember, () => _host.OpenDocument(path));
        if (!ReferenceEquals(current, opened))
        {
            return current == null
                ? $"'{Path.GetFileName(path)}' was not closed: SOLIDWORKS no longer answers its path with the "
                    + "same document the review opened, so nothing was closed."
                : $"'{Path.GetFileName(path)}' was not closed: SOLIDWORKS answers its path with a document "
                    + "that is not the same document the review opened, so nothing was closed.";
        }

        _gate.Call(DrawingOpenGuard.CloseDocKey, () => _host.CloseDoc(path));
        return null;
    }
}

/// <summary>
/// The SOLIDWORKS side of <see cref="IDrawingOpenHost"/>: one interop call per member, and
/// nothing else. Compiled but not unit tested, like the other interop-only classes; probe D14 is
/// its seat run (T077).
/// </summary>
public sealed class SwDrawingOpenHost : IDrawingOpenHost
{
    private readonly ISldWorks _swApp;

    public SwDrawingOpenHost(ISldWorks swApp)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
    }

    public object? OpenDocument(string path) => _swApp.GetOpenDocumentByName(path);

    public void DocumentVisible(bool visible, int documentType) => _swApp.DocumentVisible(visible, documentType);

    public object? OpenDoc6(string path, int documentType, int options, string configuration, out int errors, out int warnings)
    {
        int e = 0;
        int w = 0;
        object? document = _swApp.OpenDoc6(path, documentType, options, configuration, ref e, ref w);
        errors = e;
        warnings = w;
        return document;
    }

    public void CloseDoc(string path) => _swApp.CloseDoc(path);
}
