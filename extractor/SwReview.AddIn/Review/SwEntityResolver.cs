using System;
using System.IO;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.Review;

/// <summary>
/// The real <see cref="IEntityResolver"/>: Show in SOLIDWORKS.
///
/// Resolve the finding's persistent reference against the document whose extension produced
/// it, select what came back, zoom to it - all on the application thread, in one hop.
///
/// Two decisions worth stating:
///
/// <b>The state code is carried out, not folded into a boolean.</b> "Suppressed" and "deleted"
/// send the engineer to different places, and a reference that stopped resolving after a
/// rebuild is expected rather than exceptional, so the failure travels back with the code and
/// with the component's full instance path from the package (spec Edge Cases, SC-007).
///
/// <b>A component is selected by name.</b> <c>SelectByID2</c> with the IR's `full_path` plus
/// the top-level assembly name is how SOLIDWORKS itself addresses a component instance, and it
/// is the same string the engineer sees in the tree; the typed <c>Select4</c> path is the
/// fallback for references that are not components (a face, an edge, a feature).
///
/// It overlaps <c>SwCaptureView.TrySelect</c> by a dozen lines of interop. They are not merged
/// because that class reports a sentence for a capture's `note` and this one owes the page a
/// numeric state code, and because feature 001's goldens run through that path.
///
/// Compiled but not unit tested: it is interop. Every decision it makes about what the page is
/// told is in <see cref="ReviewHost"/>, which is.
/// </summary>
public sealed class SwEntityResolver : IEntityResolver
{
    private readonly ISldWorks _swApp;
    private readonly IApplicationThread _thread;
    private readonly Func<ISwSession> _session;
    private readonly Func<string, string?> _documentPath;
    private readonly Func<string, string?> _componentFullPath;

    /// <param name="swApp">The running SOLIDWORKS.</param>
    /// <param name="thread">Marshals onto the application thread.</param>
    /// <param name="session">The scope over the active document; asked for fresh each call
    /// because the engineer can close and reopen documents between findings.</param>
    /// <param name="documentPath">`document_id` to the path of the document that produced the
    /// reference, from the run's package.json.</param>
    /// <param name="componentFullPath">`component_id` to `IComponent2.Name2`, from the same
    /// package. This is what a failed resolve hands back instead of the entity.</param>
    public SwEntityResolver(
        ISldWorks swApp,
        IApplicationThread thread,
        Func<ISwSession> session,
        Func<string, string?> documentPath,
        Func<string, string?> componentFullPath)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _thread = thread ?? throw new ArgumentNullException(nameof(thread));
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _documentPath = documentPath ?? throw new ArgumentNullException(nameof(documentPath));
        _componentFullPath = componentFullPath ?? throw new ArgumentNullException(nameof(componentFullPath));
    }

    public EntityShowOutcome Show(EntityShowRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        return _thread.Invoke(() =>
        {
            string? fullPath = request.ComponentId == null ? null : _componentFullPath(request.ComponentId);
            ISwSession session = _session();
            var refs = new PersistRefService(session.Gate);

            IModelDoc2 document = session.Document;
            IModelDoc2 scope = document;

            string? scopePath = request.PersistRefScope == null
                ? null
                : _documentPath(request.PersistRefScope);
            if (!string.IsNullOrWhiteSpace(scopePath))
            {
                // A face's reference belongs to its own part document, not to the assembly.
                var scoped = session.Gate.Call(
                    "GetOpenDocumentByName",
                    () => _swApp.GetOpenDocumentByName(scopePath)) as IModelDoc2;
                if (scoped == null)
                {
                    return EntityShowOutcome.NotShown(
                        (int)SolidWorks.Interop.swconst.swPersistReferencedObjectStates_e
                            .swPersistReferencedObject_Invalid,
                        $"'{scopePath}' is not open, so its references cannot be resolved.",
                        fullPath);
                }

                scope = scoped;
            }

            ResolvedPersistRef resolved = refs.Resolve(scope, request.PersistRef);
            if (!resolved.IsOk || resolved.Entity == null)
            {
                return EntityShowOutcome.NotShown((int)resolved.State, resolved.Describe(), fullPath);
            }

            session.Gate.Call("ClearSelection2", () => { document.ClearSelection2(true); });

            if (!Select(session, document, resolved.Entity!, fullPath))
            {
                return EntityShowOutcome.NotShown(
                    (int)resolved.State,
                    "SOLIDWORKS resolved the reference but refused to select the entity.",
                    fullPath);
            }

            session.Gate.Call("ViewZoomToSelection", () => { document.ViewZoomToSelection(); });
            return EntityShowOutcome.Shown(fullPath);
        });
    }

    private bool Select(ISwSession session, IModelDoc2 document, object entity, string? fullPath)
    {
        if (entity is IComponent2 && !string.IsNullOrEmpty(fullPath))
        {
            // "<full instance path>@<top assembly name>" is how SOLIDWORKS names a component
            // instance for selection; the IR's full_path is the left half of it.
            string name = fullPath + "@" + Path.GetFileNameWithoutExtension(document.GetPathName());
            bool selected = session.Gate.Call(
                "SelectByID2",
                () => document.Extension.SelectByID2(name, "COMPONENT", 0, 0, 0, false, 0, null, 0));
            if (selected)
            {
                return true;
            }
        }

        var component = entity as IComponent2;
        if (component != null)
        {
            return session.Gate.Call("Component.Select4", () => component.Select4(false, null, false));
        }

        var feature = entity as IFeature;
        if (feature != null)
        {
            return session.Gate.Call("Feature.Select2", () => feature.Select2(false, 0));
        }

        var selectable = entity as IEntity;
        if (selectable != null)
        {
            return session.Gate.Call("Entity.Select4", () => selectable.Select4(false, null));
        }

        return false;
    }
}
