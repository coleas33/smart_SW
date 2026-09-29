using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The SOLIDWORKS side of <see cref="IOpenDrawingSource"/> (feature 011, contracts/open-drawings.md
/// section 2): interop reads and nothing else, each gated by its own member name, so every
/// decision <see cref="OpenDrawingDiscovery"/> makes is testable without a seat - the split
/// <see cref="SwDrawingReader"/> is to <see cref="DrawingDumper"/>.
///
/// <b>Nothing is opened, loaded, activated or selected.</b> <c>GetDocuments</c> lists what
/// SOLIDWORKS already has open; <c>IDrawingDoc.GetViews</c> and <c>GetReferencedModelName</c> read
/// a drawing where it stands; a candidate is <see cref="File.Exists(string)"/>, which reads no byte
/// of the file.
///
/// Compiled but not unit tested, like the other interop-only readers; the seat run is T063.
/// </summary>
public sealed class SwOpenDrawingReader : IOpenDrawingSource
{
    private readonly ISldWorks _swApp;
    private readonly SwGate _gate;

    public SwOpenDrawingReader(ISldWorks swApp, SwGate gate)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
    }

    public IReadOnlyList<OpenDocument> OpenDocuments()
    {
        var documents = new List<OpenDocument>();
        foreach (object item in Items(_gate.Call("GetDocuments", () => _swApp.GetDocuments())))
        {
            if (!(item is IModelDoc2 document))
            {
                continue;
            }

            documents.Add(new OpenDocument(
                document,
                () => SwSession.KindOf(document, _gate),
                () => _gate.Call("GetPathName", () => document.GetPathName()),
                () => ViewPaths(document, _gate)));
        }

        return documents;
    }

    public bool FileExists(string path) => File.Exists(path);

    /// <summary>
    /// Every view on every sheet, and the path each shows. <c>IDrawingDoc.GetViews</c> answers an
    /// array per sheet whose first element is the sheet's own view, which shows no model and so
    /// answers a blank name - kept, because discovery ignores a blank path by rule rather than by
    /// position. The arrays are read by <see cref="SwDrawingReader.PerSheetViews"/>, the one reading
    /// the drawing phase uses too (feature 013).
    ///
    /// Public and static since U25 (2026-09-28): the Review tab names the model an active drawing
    /// documents from this same walk (<see cref="OpenDrawingDiscovery.ModelsShown"/>), through a
    /// gate of its own, rather than from a second copy of it. Two reads per view and one per
    /// drawing, all reads; nothing is activated, opened or selected.
    /// </summary>
    public static IReadOnlyList<string> ViewPaths(IModelDoc2 document, SwGate gate)
    {
        if (document == null)
        {
            throw new ArgumentNullException(nameof(document));
        }

        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        IDrawingDoc drawing = SwSession.DrawingOf(document)
            ?? throw new InvalidOperationException(
                "The document reported itself a drawing and did not answer as one.");

        var paths = new List<string>();
        foreach (IReadOnlyList<IView> sheet in SwDrawingReader.PerSheetViews(gate.Call("GetViews", () => drawing.GetViews())))
        {
            foreach (IView view in sheet)
            {
                paths.Add(gate.Call(
                    "GetReferencedModelName", () => view.GetReferencedModelName()) ?? string.Empty);
            }
        }

        return paths;
    }

    /// <summary>The array interop hands back as <c>object</c>, as a list; null is empty.</summary>
    private static IReadOnlyList<object> Items(object? array) =>
        array is object[] items ? items : Array.Empty<object>();
}
