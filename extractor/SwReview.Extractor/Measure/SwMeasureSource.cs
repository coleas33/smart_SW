using System;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Measure;

/// <summary>
/// The real <see cref="IMeasureSource"/>: select the two entities, then
/// <c>IModelDocExtension.CreateMeasure</c> → <c>IMeasure.Calculate(null)</c>, which
/// measures the current selection (research R12).
///
/// Compiled but not unit tested; it is interop only.
/// </summary>
public sealed class SwMeasureSource : IMeasureSource
{
    private readonly ISwSession _session;
    private readonly PersistRefService _refs;
    private readonly Func<string, IModelDoc2?> _openDocument;

    public SwMeasureSource(ISwSession session, PersistRefService refs, Func<string, IModelDoc2?> openDocument)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
        _openDocument = openDocument ?? throw new ArgumentNullException(nameof(openDocument));
    }

    public MeasureReading Measure(string persistRefA, string? scopeA, string persistRefB, string? scopeB)
    {
        if (string.IsNullOrWhiteSpace(persistRefA) || string.IsNullOrWhiteSpace(persistRefB))
        {
            throw new ArgumentException("Two persistent references are required to measure.");
        }

        IModelDoc2 document = _session.Document;
        _session.Gate.Call("ClearSelection2", () => { document.ClearSelection2(true); });

        SelectOrThrow(persistRefA, scopeA, append: false, which: "the first entity");
        SelectOrThrow(persistRefB, scopeB, append: true, which: "the second entity");

        var measure = _session.Gate.Call("CreateMeasure", () => document.Extension.CreateMeasure()) as IMeasure;
        if (measure == null)
        {
            throw new MeasureNotAvailableError(
                "SOLIDWORKS did not return a Measure object for this document.");
        }

        // null means "measure what is selected"; the two entities were just selected.
        bool calculated = _session.Gate.Call("Measure.Calculate", () => measure.Calculate(null));
        if (!calculated)
        {
            throw new MeasureNotAvailableError(
                "SOLIDWORKS could not measure between these two entities. "
                + "The Measure tool has no answer for this pairing; pick faces, edges or vertices.");
        }

        return new MeasureReading(
            _session.Gate.Call("Measure.Distance", () => measure.Distance),
            _session.Gate.Call("Measure.DeltaX", () => measure.DeltaX),
            _session.Gate.Call("Measure.DeltaY", () => measure.DeltaY),
            _session.Gate.Call("Measure.DeltaZ", () => measure.DeltaZ));
    }

    private void SelectOrThrow(string persistRef, string? scopeDocumentPath, bool append, string which)
    {
        IModelDoc2 scope = _session.Document;
        if (!string.IsNullOrWhiteSpace(scopeDocumentPath))
        {
            IModelDoc2? scoped = _openDocument(scopeDocumentPath!);
            if (scoped == null)
            {
                throw new MeasureNotAvailableError(
                    $"'{scopeDocumentPath}' is not open, so {which}'s reference cannot be resolved.");
            }

            scope = scoped;
        }

        ResolvedPersistRef resolved = _refs.Resolve(scope, persistRef);
        if (!resolved.IsOk || resolved.Entity == null)
        {
            throw new MeasureNotAvailableError(
                $"{which} did not resolve: {resolved.Describe()}.");
        }

        var selectable = resolved.Entity as IEntity;
        if (selectable == null)
        {
            throw new MeasureNotAvailableError(
                $"{which} resolved to something the Measure tool cannot take "
                + $"({resolved.Entity!.GetType().Name}); pick a face, edge or vertex.");
        }

        bool selected = _session.Gate.Call("Entity.Select4", () => selectable.Select4(append, null));
        if (!selected)
        {
            throw new MeasureNotAvailableError($"SOLIDWORKS refused to select {which}.");
        }
    }
}
