using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using IrCapture = SwReview.Extractor.Ir.Capture;

namespace SwReview.Extractor.Capture;

/// <summary>
/// The <c>--view</c> values from contracts/cli.md and the SOLIDWORKS named views they map
/// to. <c>fit</c> is not a named view: it means "zoom to the selection and leave the
/// camera where it is", which is what the engineer usually wants for a close-up.
/// </summary>
public static class CaptureViews
{
    public const string Iso = "iso";
    public const string Front = "front";
    public const string Top = "top";
    public const string Right = "right";
    public const string Fit = "fit";

    private static readonly Dictionary<string, string?> NamedViews =
        new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
        {
            // The leading asterisk is SOLIDWORKS' marker for a standard view; without it
            // ShowNamedView2 looks for a user-defined view of that name and finds none.
            { Iso, "*Isometric" },
            { Front, "*Front" },
            { Top, "*Top" },
            { Right, "*Right" },
            { Fit, null },
        };

    /// <summary>Every accepted <c>--view</c> value, for a usage message.</summary>
    public static IEnumerable<string> All => new[] { Iso, Front, Top, Right, Fit };

    /// <summary>True when <paramref name="view"/> is one of the five.</summary>
    public static bool IsKnown(string? view) => view != null && NamedViews.ContainsKey(view.Trim());

    /// <summary>
    /// The SOLIDWORKS named view for a <c>--view</c> value, or null for <c>fit</c>. Throws
    /// for anything else: a view name the reviewer invented must never reach interop.
    /// </summary>
    public static string? NamedView(string? view)
    {
        string key = (view ?? Fit).Trim();
        string? named;
        if (!NamedViews.TryGetValue(key, out named))
        {
            throw new ArgumentException(
                $"--view must be {string.Join(", ", new[] { Iso, Front, Top, Right, Fit })}; got '{view}'.",
                nameof(view));
        }

        return named;
    }

    /// <summary>The canonical lowercase spelling recorded in <c>Capture.view</c>.</summary>
    public static string Normalize(string? view) => (view ?? Fit).Trim().ToLowerInvariant();
}

/// <summary>
/// The SOLIDWORKS operations one capture needs, as an interface so the naming, the view
/// mapping and the gap-on-failure behaviour are unit tested with a fake
/// (constitution Principle III).
/// </summary>
public interface ICaptureView
{
    /// <summary>
    /// Clears the selection and selects whatever <paramref name="persistRef"/> resolves to
    /// in <paramref name="scopeDocumentPath"/>. False means the reference did not resolve;
    /// the message says why, and becomes the gap.
    /// </summary>
    bool TrySelect(string persistRef, string? scopeDocumentPath, out string reason);

    /// <summary>Component ids of whatever is selected, for <c>Capture.component_ids</c>.</summary>
    IReadOnlyList<string> SelectedComponentIds();

    /// <summary><c>IModelDoc2.ViewZoomToSelection</c>.</summary>
    void ZoomToSelection();

    /// <summary><c>IModelDoc2.ShowNamedView2</c> with a standard view such as <c>*Isometric</c>.</summary>
    void ShowNamedView(string namedView);

    /// <summary>Writes a PNG at <paramref name="pngPath"/>. False means SOLIDWORKS refused.</summary>
    bool SaveImage(string pngPath);
}

/// <summary>What one capture produced: the IR row, and the gap when it did not work.</summary>
public sealed class CaptureResult
{
    public CaptureResult(IrCapture? capture, Gap? gap)
    {
        Capture = capture;
        Gap = gap;
    }

    /// <summary>The row to append to <c>captures</c>, or null when nothing was saved.</summary>
    public IrCapture? Capture { get; }

    /// <summary>The gap to append to <c>gaps</c>, or null when the capture worked.</summary>
    public Gap? Gap { get; }

    public bool Succeeded => Capture != null;
}

/// <summary>
/// T070. Zooms to an entity and saves a PNG next to the package.
///
/// A capture that fails is a gap, never an exception that ends a review: a missing picture
/// is a nuisance, and the finding it illustrates is still worth reporting (Principle I).
///
/// File names come from the capture id so they are stable and collision-free, with the id's
/// colon replaced because Windows will not accept one in a file name:
/// <c>cap:0001</c> becomes <c>captures/cap-0001.png</c>.
/// </summary>
public sealed class CaptureService
{
    /// <summary>Subdirectory of the package directory that holds capture PNGs.</summary>
    public const string CaptureDirectoryName = "captures";

    /// <summary>Id prefix for <c>Capture.id</c>.</summary>
    public const string IdPrefix = "cap";

    /// <summary><c>Gap.entity_kind</c> for a capture that did not happen.</summary>
    public const string GapEntityKind = "capture";

    private readonly ICaptureView _view;
    private readonly IdAllocator _ids;

    public CaptureService(ICaptureView view, IdAllocator? ids = null)
    {
        _view = view ?? throw new ArgumentNullException(nameof(view));
        _ids = ids ?? new IdAllocator(IdPrefix);
    }

    /// <summary>
    /// The package-relative path a capture id is saved at, e.g.
    /// <c>captures/cap-0001.png</c>. Package-relative and forward-slashed, because that is
    /// what <c>Capture.file</c> carries and the Python reviewer joins it to the package
    /// directory on whatever platform it runs on.
    /// </summary>
    public static string RelativeFile(string captureId)
    {
        if (string.IsNullOrWhiteSpace(captureId))
        {
            throw new ArgumentException("A capture id is required.", nameof(captureId));
        }

        return CaptureDirectoryName + "/" + FileName(captureId);
    }

    /// <summary>The file name for a capture id: the colon is not legal in a Windows path.</summary>
    public static string FileName(string captureId) => captureId.Replace(':', '-') + ".png";

    /// <summary>
    /// Selects <paramref name="persistRef"/>, frames it, and saves a PNG under
    /// <paramref name="outputDirectory"/>/<c>captures</c>.
    /// </summary>
    /// <param name="persistRef">Base64 persistent reference of the entity to frame.</param>
    /// <param name="scopeDocumentPath">
    /// The document whose extension produced the reference; null means the session's own
    /// document. References only resolve against their own scope (T049).
    /// </param>
    /// <param name="view">One of <see cref="CaptureViews"/>.</param>
    /// <param name="outputDirectory">The package directory; <c>captures/</c> is created in it.</param>
    /// <param name="note">Free text recorded on the row, e.g. why the picture was taken.</param>
    public CaptureResult Capture(
        string persistRef,
        string? scopeDocumentPath,
        string? view,
        string outputDirectory,
        string note = "")
    {
        if (string.IsNullOrWhiteSpace(persistRef))
        {
            throw new ArgumentException("A persistent reference is required.", nameof(persistRef));
        }

        if (string.IsNullOrWhiteSpace(outputDirectory))
        {
            throw new ArgumentException("An output directory is required.", nameof(outputDirectory));
        }

        string normalizedView = CaptureViews.Normalize(view);
        string? namedView;
        try
        {
            namedView = CaptureViews.NamedView(view);
        }
        catch (ArgumentException error)
        {
            return Failed(null, normalizedView, GapKind.Unsupported, "choose the camera view", error.Message);
        }

        string id = _ids.Next();
        string relativeFile = RelativeFile(id);
        string absoluteFile = Path.Combine(outputDirectory, CaptureDirectoryName, FileName(id));

        try
        {
            string reason;
            if (!_view.TrySelect(persistRef, scopeDocumentPath, out reason))
            {
                return Failed(
                    persistRef,
                    normalizedView,
                    GapKind.NotExtracted,
                    "select the entity to capture",
                    reason);
            }

            IReadOnlyList<string> componentIds = _view.SelectedComponentIds() ?? new string[0];

            // Zoom first, then the standard view: ShowNamedView2 rotates the camera but
            // keeps the zoom, so the selection stays framed (research R12).
            _view.ZoomToSelection();
            if (namedView != null)
            {
                _view.ShowNamedView(namedView);
                _view.ZoomToSelection();
            }

            Directory.CreateDirectory(Path.Combine(outputDirectory, CaptureDirectoryName));

            // The one place an image file is written. AssertSaveAs is what keeps the
            // read-only guard's single exception honest: a .sldasm here would be a model
            // write dressed up as a screenshot (research R4).
            ReadOnlyGuard.AssertSaveAs(absoluteFile);

            if (!_view.SaveImage(absoluteFile))
            {
                return Failed(
                    persistRef,
                    normalizedView,
                    GapKind.ToolError,
                    "save the capture image",
                    $"SOLIDWORKS refused to write '{absoluteFile}'.");
            }

            return new CaptureResult(
                new IrCapture
                {
                    Id = id,
                    PersistRef = persistRef,
                    ComponentIds = new List<string>(componentIds),
                    File = relativeFile,
                    View = normalizedView,
                    Note = note ?? string.Empty,
                },
                null);
        }
        catch (CircuitOpenError)
        {
            // A dead session is not a capture problem; the caller stops.
            throw;
        }
        catch (MutatingCallError)
        {
            // Our bug, not the model's (see GapCollector).
            throw;
        }
        catch (Exception error)
        {
            return Failed(
                persistRef,
                normalizedView,
                GapKind.ToolError,
                "capture the entity",
                error.GetType().Name + ": " + error.Message);
        }
    }

    private static CaptureResult Failed(
        string? persistRef, string view, GapKind kind, string reason, string? error)
    {
        return new CaptureResult(
            null,
            new Gap
            {
                Kind = kind,
                EntityKind = GapEntityKind,
                EntityId = null,
                Reason = $"{reason} ({view} view)",
                Error = error,
            });
    }
}
