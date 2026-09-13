using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Capture;

/// <summary>
/// The real <see cref="ICaptureView"/>: resolve a persistent reference, select what it
/// points at, frame it, and write a PNG (research R12).
///
/// <c>SaveBMP</c> is used rather than <c>SaveAs3</c> on purpose. Both can produce an image,
/// but <c>SaveAs3</c> is on the read-only guard's denylist - it is the API that writes
/// model files - so routing a screenshot through it would mean punching a hole in the one
/// guard that keeps the assistant from editing customer data. <c>SaveBMP</c> cannot write a
/// model at all, so the BMP is written and converted to PNG in this process instead
/// (<c>Capture.file</c> must end in <c>.png</c>).
///
/// Compiled but not unit tested: it is interop plus a bitmap conversion. The decisions live
/// in <see cref="CaptureService"/>.
/// </summary>
public sealed class SwCaptureView : ICaptureView
{
    private readonly ISwSession _session;
    private readonly PersistRefService _refs;
    private readonly Func<string, IModelDoc2?> _openDocument;
    private readonly Func<object, string?> _componentIdLookup;

    private object? _selected;

    /// <param name="session">The session that owns the document and the gate.</param>
    /// <param name="refs">Persistent reference resolution (T049).</param>
    /// <param name="openDocument">
    /// Path to an already-open document, for references scoped to a part rather than to the
    /// assembly. Returns null when the document is not open.
    /// </param>
    /// <param name="componentIdLookup">
    /// Live <c>IComponent2</c> to package component id, so <c>Capture.component_ids</c>
    /// names the components rather than repeating the reference.
    /// </param>
    public SwCaptureView(
        ISwSession session,
        PersistRefService refs,
        Func<string, IModelDoc2?> openDocument,
        Func<object, string?> componentIdLookup)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
        _openDocument = openDocument ?? throw new ArgumentNullException(nameof(openDocument));
        _componentIdLookup = componentIdLookup ?? throw new ArgumentNullException(nameof(componentIdLookup));
    }

    public bool TrySelect(string persistRef, string? scopeDocumentPath, out string reason)
    {
        _selected = null;

        IModelDoc2 scope = _session.Document;
        if (!string.IsNullOrWhiteSpace(scopeDocumentPath))
        {
            IModelDoc2? scoped = _openDocument(scopeDocumentPath!);
            if (scoped == null)
            {
                reason = $"'{scopeDocumentPath}' is not open, so its references cannot be resolved.";
                return false;
            }

            scope = scoped;
        }

        ResolvedPersistRef resolved = _refs.Resolve(scope, persistRef);
        if (!resolved.IsOk || resolved.Entity == null)
        {
            reason = "The reference did not resolve: " + resolved.Describe() + ".";
            return false;
        }

        IModelDoc2 document = _session.Document;
        _session.Gate.Call("ClearSelection2", () => { document.ClearSelection2(true); });

        if (!Select(resolved.Entity!))
        {
            reason = "SOLIDWORKS resolved the reference but refused to select the entity.";
            return false;
        }

        _selected = resolved.Entity;
        reason = string.Empty;
        return true;
    }

    public IReadOnlyList<string> SelectedComponentIds()
    {
        object? owner = OwningComponent(_selected);
        if (owner == null)
        {
            return new string[0];
        }

        string? id = _componentIdLookup(owner);
        return string.IsNullOrEmpty(id) ? new string[0] : new[] { id! };
    }

    public void ZoomToSelection()
    {
        IModelDoc2 document = _session.Document;
        _session.Gate.Call("ViewZoomToSelection", () => { document.ViewZoomToSelection(); });
    }

    public void ShowNamedView(string namedView)
    {
        IModelDoc2 document = _session.Document;

        // The second argument is swStandardViews_e; -1 means "use the name", which is the
        // only way to ask for a standard view by its *Isometric style name.
        _session.Gate.Call("ShowNamedView2", () => { document.ShowNamedView2(namedView, -1); });
    }

    public bool SaveImage(string pngPath)
    {
        IModelDoc2 document = _session.Document;
        string bmpPath = Path.ChangeExtension(pngPath, ".bmp");

        // 0, 0 means "the size of the graphics window", which keeps the aspect ratio the
        // engineer is looking at instead of stretching it to a guessed size.
        bool saved = _session.Gate.Call("SaveBMP", () => document.SaveBMP(bmpPath, 0, 0));
        if (!saved || !File.Exists(bmpPath))
        {
            return false;
        }

        try
        {
            using (var bitmap = new Bitmap(bmpPath))
            {
                bitmap.Save(pngPath, ImageFormat.Png);
            }
        }
        finally
        {
            try
            {
                File.Delete(bmpPath);
            }
            catch (IOException)
            {
                // A leftover BMP is untidy, not a failure: the PNG the IR names exists.
            }
        }

        return File.Exists(pngPath);
    }

    private bool Select(object entity)
    {
        var component = entity as IComponent2;
        if (component != null)
        {
            return _session.Gate.Call("Component.Select4", () => component.Select4(false, null, false));
        }

        var feature = entity as IFeature;
        if (feature != null)
        {
            return _session.Gate.Call("Feature.Select2", () => feature.Select2(false, 0));
        }

        var selectable = entity as IEntity;
        if (selectable != null)
        {
            return _session.Gate.Call("Entity.Select4", () => selectable.Select4(false, null));
        }

        return false;
    }

    private object? OwningComponent(object? entity)
    {
        if (entity == null)
        {
            return null;
        }

        if (entity is IComponent2)
        {
            return entity;
        }

        var selectable = entity as IEntity;
        if (selectable == null)
        {
            return null;
        }

        return _session.Gate.Call("Entity.GetComponent", () => selectable.GetComponent());
    }
}
