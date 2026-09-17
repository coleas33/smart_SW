using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T060. The SOLIDWORKS side of <see cref="IDrawingReader"/> and of
/// <see cref="IDrawingReferenceSource"/>: interop calls and nothing else, so that every
/// decision <see cref="DrawingDumper"/> and the drawing-rooted traversal make is testable
/// without a seat - the same split <see cref="SwCutListReader"/> is to
/// <see cref="CutListDumper"/>.
///
/// Interop notes, each one a row of <c>research.md</c> R3.3:
///   - <c>IDrawingDoc</c> is reached by casting the open <c>IModelDoc2</c>
///     (<see cref="SwSession.DrawingOf"/>). Nothing is opened, and no sheet or view is
///     activated: <c>ActivateSheet</c> and <c>ActivateView</c> are on the read-only denylist.
///   - Revision tables are enumerated with <c>IView.GetTableAnnotations()</c> and filtered by
///     the dumper on <c>ITableAnnotation.Type</c>. <c>ISheet.RevisionTable</c> is read only as
///     a cross-check: it is single-valued, so a sheet carrying two tables would yield one
///     record and silently lose the other.
///   - <c>IRevisionTableAnnotation</c> declares no base interface in this interop, so reading
///     a cell needs a runtime COM cast to <c>ITableAnnotation</c>. That cast is what
///     <see cref="TableShape"/> and <see cref="Cell"/> make, and PROBE-4 is whether it works.
///   - <c>IDimension.GetSystemValue3</c> is declared as returning <c>object</c> and hands
///     back one value per configuration; the first is the one asked for.
/// </summary>
public sealed class SwDrawingReader : IDrawingReader, IDrawingReferenceSource
{
    private readonly ISwSession _session;
    private readonly PersistRefService _refs;

    public SwDrawingReader(ISwSession session, PersistRefService refs)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    private SwGate Gate => _session.Gate;

    /// <summary>
    /// The open document as a drawing, or null when it is not one. Not gated: a COM cast is
    /// not a member call, and the document is the one the dump is already attached to.
    /// </summary>
    public object? Drawing() => SwSession.DrawingOf(_session.Document);

    public string? ActiveSheetName(object drawing)
    {
        var sheet = Gate.Call("GetCurrentSheet", () => Doc(drawing).GetCurrentSheet()) as ISheet;
        return sheet == null ? null : Gate.Call("GetName", () => sheet.GetName());
    }

    public IReadOnlyList<string> SheetNames(object drawing)
    {
        IDrawingDoc doc = Doc(drawing);
        int count = Gate.Call("GetSheetCount", () => doc.GetSheetCount());
        var names = Gate.Call("GetSheetNames", () => doc.GetSheetNames()) as object[];

        if (names == null)
        {
            throw new InvalidOperationException(
                $"GetSheetNames returned nothing for a drawing that reports {count} sheets, "
                + "so no sheet could be read.");
        }

        var sheets = new List<string>(names.Length);
        foreach (object name in names)
        {
            if (name is string text)
            {
                sheets.Add(text);
            }
        }

        return sheets;
    }

    public object? Sheet(object drawing, string name) => Doc(drawing).Sheet[name];

    public string? SheetName(object sheet) => AsSheet(sheet).GetName();

    public string? SheetFormatName(object sheet) => AsSheet(sheet).GetSheetFormatName();

    public IReadOnlyList<object> Views(object sheet) => Items(AsSheet(sheet).GetViews());

    public object? SheetRevisionTable(object sheet) => AsSheet(sheet).RevisionTable;

    public string? ViewName(object view) => AsView(view).GetName2();

    public int ViewType(object view) => AsView(view).Type;

    public string? ReferencedModelPath(object view) => AsView(view).GetReferencedModelName();

    public object? ReferencedDocument(object view) => AsView(view).ReferencedDocument;

    public string? DocumentPath(object document) => ((IModelDoc2)document).GetPathName();

    public IReadOnlyList<object> DisplayDimensions(object view) =>
        Items(AsView(view).GetDisplayDimensions());

    public IReadOnlyList<object> Annotations(object view) => Items(AsView(view).GetAnnotations());

    public IReadOnlyList<object> Notes(object view) => Items(AsView(view).GetNotes());

    public IReadOnlyList<object> TableAnnotations(object view) =>
        Items(Gate.Call("GetTableAnnotations", () => AsView(view).GetTableAnnotations()));

    public int TableAnnotationType(object table) => ((ITableAnnotation)table).Type;

    /// <summary>
    /// <c>GetDimension2(0).FullName</c>, falling back to <c>Name</c>. The fall-back is not a
    /// preference: <c>FullName</c> is what identifies a dimension across a drawing, and
    /// <c>Name</c> alone ("D1") would name half a dozen dimensions on one sheet.
    /// </summary>
    public string? DimensionName(object dimension)
    {
        var value = Gate.Call(
            "GetDimension2", () => AsDisplayDimension(dimension).GetDimension2(0)) as IDimension;

        if (value == null)
        {
            return null;
        }

        string? full = Gate.Call("FullName", () => value.FullName);
        return string.IsNullOrWhiteSpace(full) ? Gate.Call("Name", () => value.Name) : full;
    }

    public int DimensionType(object dimension) => AsDisplayDimension(dimension).Type2;

    public bool IsOverridden(object dimension) => AsDisplayDimension(dimension).GetOverride();

    public double OverrideValue(object dimension) => AsDisplayDimension(dimension).GetOverrideValue();

    /// <summary>
    /// <c>IDimension.GetSystemValue3(swThisConfiguration, null)</c>. The display dimension's
    /// own <c>IDimension</c> is fetched again rather than passed in, so that one reader member
    /// is one answer and the dumper never holds two handles for one dimension.
    ///
    /// Two interop calls, so both are gated here under their own member names, the way
    /// <see cref="DimensionName"/> gates its three: the dumper gates the members that map to
    /// ONE call, and a member that spans several is its own gate. Reaching
    /// <c>GetDimension2</c> ungated would put a call past the read-only guard and leave it out
    /// of the SC-010 log.
    /// </summary>
    public double DimensionValue(object dimension)
    {
        var value = Gate.Call(
            "GetDimension2", () => AsDisplayDimension(dimension).GetDimension2(0)) as IDimension;

        if (value == null)
        {
            throw new InvalidOperationException(
                "The display dimension gave no IDimension, so its computed value is unknown.");
        }

        object? values = Gate.Call(
            "GetSystemValue3",
            () => value.GetSystemValue3(
                (int)SolidWorks.Interop.swconst.swInConfigurationOpts_e.swThisConfiguration, null));

        return First(values);
    }

    public string? AnnotationName(object annotation) => AsAnnotation(annotation).GetName();

    public int AnnotationType(object annotation) => AsAnnotation(annotation).GetType();

    public bool IsDangling(object annotation) => AsAnnotation(annotation).IsDangling();

    public string? NoteText(object note) => ((INote)note).GetText();

    public string? CurrentRevision(object table) =>
        ((IRevisionTableAnnotation)table).CurrentRevision;

    /// <summary>
    /// The runtime COM cast PROBE-4 asks about, and the two counts behind it. An
    /// <c>InvalidCastException</c> here is the whole table's rows lost, which
    /// <see cref="DrawingDumper"/> records as a <c>revision_table_read</c> gap.
    /// </summary>
    public RevisionTableShape TableShape(object table)
    {
        ITableAnnotation annotation = AsTable(table);
        int rows = Gate.Call("RowCount", () => annotation.RowCount);
        int columns = Gate.Call("ColumnCount", () => annotation.ColumnCount);
        return new RevisionTableShape(rows, columns);
    }

    public string? Cell(object table, int row, int column) => AsTable(table).Text[row, column];

    public ScopedPersistRef? PersistRef(object entity) => _refs.TryGet(_session.Document, entity);

    /// <summary>
    /// Every model a view on any sheet references, in sheet and view order, with duplicates
    /// left in - <see cref="DrawingTraversal.ReferencedModels"/> decides what one model is.
    ///
    /// <b>Nothing is opened, loaded, resolved or activated</b> (FR-044): a model that is not
    /// loaded comes back with a null document and its path, which is what lets the
    /// <c>drawing_referenced_document</c> gap name it.
    ///
    /// A sheet or view that will not answer is skipped rather than thrown on: this runs
    /// inside <see cref="ComponentTreeDumper.Traverse"/>, which is outside a phase, so an
    /// escaping exception would cost the whole package. The drawing phase reads the same
    /// views again and records a gap for each one it could not read.
    /// </summary>
    public IReadOnlyList<DrawingReference> ReferencedModels()
    {
        var references = new List<DrawingReference>();

        object? drawing = Drawing();
        if (drawing == null)
        {
            return references;
        }

        foreach (string name in SheetNames(drawing))
        {
            object? sheet = Gate.Call("Sheet", () => Sheet(drawing, name));
            if (sheet == null)
            {
                continue;
            }

            foreach (object view in Gate.Call("GetViews", () => Views(sheet)))
            {
                string? path = Gate.Call(
                    "GetReferencedModelName", () => ReferencedModelPath(view));

                if (string.IsNullOrWhiteSpace(path))
                {
                    continue;
                }

                object? document = Gate.Call("ReferencedDocument", () => ReferencedDocument(view));
                references.Add(new DrawingReference(path!, document));
            }
        }

        return references;
    }

    /// <summary>
    /// The array interop hands back as <c>object</c>, as a list. A null is an empty list
    /// rather than a throw: SOLIDWORKS returns null for "none of these", and the dumper's
    /// own rules decide when an empty list is a gap - on a non-active sheet it is one, and
    /// on a view with no annotations it is not.
    /// </summary>
    private static IReadOnlyList<object> Items(object? array)
    {
        if (array is object[] items)
        {
            return items;
        }

        return new object[0];
    }

    /// <summary>
    /// The first value of an interop array of doubles, or the value itself when interop
    /// handed back one number rather than an array.
    /// </summary>
    private static double First(object? value)
    {
        switch (value)
        {
            case double[] doubles when doubles.Length > 0:
                return doubles[0];
            case object[] boxed when boxed.Length > 0 && boxed[0] is double first:
                return first;
            case double single:
                return single;
            default:
                throw new InvalidOperationException(
                    "GetSystemValue3 returned no number, so the dimension's computed value is unknown.");
        }
    }

    private static IDrawingDoc Doc(object drawing) => (IDrawingDoc)drawing;

    private static ISheet AsSheet(object sheet) => (ISheet)sheet;

    private static IView AsView(object view) => (IView)view;

    private static IDisplayDimension AsDisplayDimension(object dimension) =>
        (IDisplayDimension)dimension;

    private static IAnnotation AsAnnotation(object annotation) => (IAnnotation)annotation;

    private static ITableAnnotation AsTable(object table) => (ITableAnnotation)table;
}
