using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Probes;

/// <summary>One hole callout's whole text as <c>IDisplayDimension.GetText(0)</c> answered it (probe D7), by position.</summary>
public sealed class HoleCalloutText
{
    public HoleCalloutText(int sheet, int view, int dimension, int? length, string? failure)
    {
        Sheet = sheet;
        View = view;
        Dimension = dimension;
        Length = length;
        Failure = failure;
    }

    /// <summary>1-based, in <c>GetSheetNames</c> order.</summary>
    public int Sheet { get; }

    /// <summary>1-based, in <c>ISheet.GetViews</c> order.</summary>
    public int View { get; }

    /// <summary>1-based, in <c>IView.GetDisplayDimensions</c> order.</summary>
    public int Dimension { get; }

    /// <summary>The text's length - never the text - or null when the read failed or answered nothing.</summary>
    public int? Length { get; }

    /// <summary>The read's failure as <see cref="ProbeText.Failure"/> prints it, or null.</summary>
    public string? Failure { get; }
}

/// <summary>
/// The reads <c>probe drawings</c> makes beyond the extraction (contracts/probes.md section 2):
/// what the drawing phase does not record, and the probe needs to answer D2, D3, D7, D10 and D11.
/// Each implementation gates its own interop calls under the names of <see cref="DrawingProbeMember"/>,
/// as <see cref="SwOpenDrawingReader"/> does, so a fake needs no gate.
/// </summary>
public interface IDrawingProbeReads
{
    /// <summary>D3: <c>IDrawingDoc.GetCurrentSheet</c> then <c>ISheet.GetName</c>, compared, never printed.</summary>
    string? ActiveSheetName(object document);

    /// <summary>D3: <c>IDrawingDoc.GetViews</c>, per sheet, each view's <c>IView.Type</c>.</summary>
    IReadOnlyList<IReadOnlyList<int>> DocumentViewTypes(object document);

    /// <summary>D11: the number of items <c>ISheet.GetProperties2</c> answers, per sheet in <c>GetSheetNames</c> order; null where it answered nothing.</summary>
    IReadOnlyList<int?> SheetPropertyCounts(object document);

    /// <summary>D11: <c>IModelDocExtension.GetUserPreferenceInteger(preference, 0)</c>.</summary>
    int UserPreferenceInteger(object document, int preference);

    /// <summary>D7: <c>IDisplayDimension.GetText(0)</c> for every dimension that answers <c>IsHoleCallout</c>, by position.</summary>
    IReadOnlyList<HoleCalloutText> HoleCalloutWholeTexts(object document);

    /// <summary>D2: <c>IModelDoc2.Visible</c>.</summary>
    bool Visible(object document);

    /// <summary>D10: whether <c>ISldWorks.GetOpenDocumentByName</c> answers the path. Nothing is opened.</summary>
    bool IsOpen(string path);
}

/// <summary>
/// The interop members the probe's own reads name to the read-only gate, by the name each is gated
/// under - the drawing phase's names wherever it reads the same member - so the tests can assert
/// every one is a read. Named once so <see cref="SwDrawingProbeReads"/> and the list cannot drift.
/// </summary>
public static class DrawingProbeMember
{
    public const string CurrentSheet = "GetCurrentSheet";
    public const string Name = "GetName";
    public const string DocumentViews = "GetViews";
    public const string ViewType = "Type";
    public const string SheetCount = "GetSheetCount";
    public const string SheetNames = "GetSheetNames";
    public const string Sheet = "Sheet";
    public const string SheetProperties = "GetProperties2";
    public const string UserPreferenceInteger = "GetUserPreferenceInteger";
    public const string DisplayDimensions = "GetDisplayDimensions";
    public const string IsHoleCallout = "IsHoleCallout";
    public const string Text = "GetText";
    public const string Visible = "Visible";
    public const string OpenDocumentByName = "GetOpenDocumentByName";

    public static IReadOnlyList<string> All { get; } = new[]
    {
        CurrentSheet, Name, DocumentViews, ViewType, SheetCount, SheetNames, Sheet, SheetProperties,
        UserPreferenceInteger, DisplayDimensions, IsHoleCallout, Text, Visible, OpenDocumentByName,
    };
}

/// <summary>
/// The SOLIDWORKS side of <see cref="IDrawingProbeReads"/>, reading through the shipped
/// <see cref="SwDrawingReader"/> wherever it has the member, each call gated by name on the
/// session's gate. <b>Nothing is opened, activated or written</b>: every member is a read of a
/// document SOLIDWORKS already has open. Compiled but not unit tested, like the other interop-only
/// readers; the seat run is T062 to T065.
/// </summary>
public sealed class SwDrawingProbeReads : IDrawingProbeReads
{
    /// <summary><c>swDimensionTextParts_e.swDimensionTextAll</c>.</summary>
    private const int WholeText = 0;

    private readonly ISldWorks _swApp;
    private readonly SwGate _gate;
    private readonly SwDrawingReader _reader;

    public SwDrawingProbeReads(ISldWorks swApp, ISwSession session, PersistRefService refs)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        if (session == null)
        {
            throw new ArgumentNullException(nameof(session));
        }

        _gate = session.Gate;
        _reader = new SwDrawingReader(session, refs ?? throw new ArgumentNullException(nameof(refs)));
    }

    public string? ActiveSheetName(object document) => _reader.ActiveSheetName(Drawing(document));

    public IReadOnlyList<IReadOnlyList<int>> DocumentViewTypes(object document)
    {
        var drawing = (IDrawingDoc)Drawing(document);
        var sheets = new List<IReadOnlyList<int>>();
        foreach (object sheet in Items(_gate.Call(DrawingProbeMember.DocumentViews, () => drawing.GetViews())))
        {
            var types = new List<int>();
            foreach (object item in Items(sheet))
            {
                if (item is IView view)
                {
                    types.Add(_gate.Call(DrawingProbeMember.ViewType, () => view.Type));
                }
            }

            sheets.Add(types);
        }

        return sheets;
    }

    public IReadOnlyList<int?> SheetPropertyCounts(object document)
    {
        object drawing = Drawing(document);
        var counts = new List<int?>();
        foreach (string name in _reader.SheetNames(drawing))
        {
            try
            {
                object? sheet = _gate.Call(DrawingProbeMember.Sheet, () => _reader.Sheet(drawing, name));
                counts.Add(sheet == null
                    ? (int?)null
                    : _gate.Call(DrawingProbeMember.SheetProperties, () => _reader.SheetProperties(sheet))?.Count);
            }
            catch (Exception error) when (!(error is Guard.MutatingCallError) && !(error is Guard.CircuitOpenError))
            {
                counts.Add(null);
            }
        }

        return counts;
    }

    public int UserPreferenceInteger(object document, int preference) =>
        _gate.Call(DrawingProbeMember.UserPreferenceInteger, () => _reader.UserPreferenceInteger(document, preference));

    public IReadOnlyList<HoleCalloutText> HoleCalloutWholeTexts(object document)
    {
        object drawing = Drawing(document);
        var texts = new List<HoleCalloutText>();
        IReadOnlyList<string> names = _reader.SheetNames(drawing);
        for (int s = 0; s < names.Count; s++)
        {
            string name = names[s];
            object? sheet = _gate.Call(DrawingProbeMember.Sheet, () => _reader.Sheet(drawing, name));
            if (sheet == null)
            {
                continue;
            }

            IReadOnlyList<object> views = _gate.Call(DrawingProbeMember.DocumentViews, () => _reader.Views(sheet));
            for (int v = 0; v < views.Count; v++)
            {
                object view = views[v];
                IReadOnlyList<object> dimensions =
                    _gate.Call(DrawingProbeMember.DisplayDimensions, () => _reader.DisplayDimensions(view));
                for (int d = 0; d < dimensions.Count; d++)
                {
                    object dimension = dimensions[d];
                    if (!_gate.Call(DrawingProbeMember.IsHoleCallout, () => _reader.IsHoleCallout(dimension)))
                    {
                        continue;
                    }

                    try
                    {
                        string? text = _gate.Call(DrawingProbeMember.Text, () => _reader.DimensionText(dimension, WholeText));
                        texts.Add(new HoleCalloutText(s + 1, v + 1, d + 1, text?.Length, null));
                    }
                    catch (Exception error) when (!(error is Guard.MutatingCallError) && !(error is Guard.CircuitOpenError))
                    {
                        texts.Add(new HoleCalloutText(s + 1, v + 1, d + 1, null, ProbeText.Failure(error)));
                    }
                }
            }
        }

        return texts;
    }

    public bool Visible(object document) =>
        _gate.Call(DrawingProbeMember.Visible, () => ((IModelDoc2)document).Visible);

    public bool IsOpen(string path) =>
        _gate.Call(DrawingProbeMember.OpenDocumentByName, () => _swApp.GetOpenDocumentByName(path)) is IModelDoc2;

    private object Drawing(object document) =>
        _reader.Drawing(document)
        ?? throw new InvalidOperationException("The document reported itself a drawing and did not answer as one.");

    private static IReadOnlyList<object> Items(object? array) =>
        array is object[] items ? items : Array.Empty<object>();
}
