using System;
using System.Collections.Generic;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The shape of a revision table as <c>ITableAnnotation</c> reports it. A struct of two
/// numbers rather than two reader members, because reaching either one needs the same
/// runtime COM cast - <c>IRevisionTableAnnotation</c> declares no base interface in this
/// interop (PROBE-4) - and a cast that failed for one would have failed for the other.
/// </summary>
public readonly struct RevisionTableShape
{
    public RevisionTableShape(int rowCount, int columnCount)
    {
        RowCount = rowCount;
        ColumnCount = columnCount;
    }

    public int RowCount { get; }

    public int ColumnCount { get; }
}

/// <summary>
/// What <see cref="DrawingDumper"/> needs SOLIDWORKS to answer, so that every decision the
/// dumper makes - what becomes a gap, what is recorded when a read fails, what is never
/// called - is testable on a machine with no seat. The same seam
/// <see cref="ICutListReader"/> is, and <see cref="SwDrawingReader"/> is the SOLIDWORKS side.
///
/// Every member here that maps to ONE interop call is gated by the dumper, which names it,
/// so the read-only guard and the SC-010 audit see the production member names even under a
/// fake. <see cref="ActiveSheetName"/>, <see cref="SheetNames"/>,
/// <see cref="DimensionName"/>, <see cref="DimensionValue"/>, <see cref="TableAnnotations"/>,
/// <see cref="TableShape"/> and <see cref="PersistRef"/> span several calls each and gate
/// them inside the implementation. The dumper does not gate those a second time: one read
/// reported twice is a gate log that counts calls nobody made.
/// </summary>
public interface IDrawingReader
{
    /// <summary>
    /// The open document as an <c>IDrawingDoc</c>, or null when it is not a drawing. Nothing
    /// is opened to produce it: the drawing phase reads the document the dump is already
    /// attached to (FR-044).
    /// </summary>
    object? Drawing();

    /// <summary>
    /// <c>IDrawingDoc.GetCurrentSheet()</c> -> <c>ISheet.GetName()</c>: which sheet was
    /// active while the others were read. Gates both calls itself. <b>Nothing activates a
    /// sheet.</b>
    /// </summary>
    string? ActiveSheetName(object drawing);

    /// <summary>
    /// <c>IDrawingDoc.GetSheetNames()</c>, cross-checked against <c>GetSheetCount()</c>.
    /// Gates both calls itself, because one enumeration is two members.
    /// </summary>
    IReadOnlyList<string> SheetNames(object drawing);

    /// <summary>The <c>IDrawingDoc.Sheet</c> indexer; null when the name resolved to nothing.</summary>
    object? Sheet(object drawing, string name);

    /// <summary><c>ISheet.GetName()</c>.</summary>
    string? SheetName(object sheet);

    /// <summary><c>ISheet.GetSheetFormatName()</c>.</summary>
    string? SheetFormatName(object sheet);

    /// <summary><c>ISheet.GetViews()</c>, in the order it returned them.</summary>
    IReadOnlyList<object> Views(object sheet);

    /// <summary>
    /// <c>ISheet.RevisionTable</c>: the single-valued property, read as a <b>cross-check</b>
    /// on the per-view walk and never as the enumeration.
    /// </summary>
    object? SheetRevisionTable(object sheet);

    /// <summary><c>IView.GetName2()</c>.</summary>
    string? ViewName(object view);

    /// <summary><c>IView.Type</c>, verbatim; 1 is the sheet-format pseudo-view.</summary>
    int ViewType(object view);

    /// <summary><c>IView.GetReferencedModelName()</c>.</summary>
    string? ReferencedModelPath(object view);

    /// <summary><c>IView.ReferencedDocument</c>; null when the model is not loaded.</summary>
    object? ReferencedDocument(object view);

    /// <summary><c>IModelDoc2.GetPathName()</c> of a referenced model.</summary>
    string? DocumentPath(object document);

    /// <summary><c>IView.GetDisplayDimensions()</c>.</summary>
    IReadOnlyList<object> DisplayDimensions(object view);

    /// <summary><c>IView.GetAnnotations()</c> - every annotation type, unfiltered.</summary>
    IReadOnlyList<object> Annotations(object view);

    /// <summary><c>IView.GetNotes()</c>.</summary>
    IReadOnlyList<object> Notes(object view);

    /// <summary>
    /// <c>IView.GetTableAnnotations()</c>, unfiltered: which of them is a revision table is
    /// decided by <see cref="TableAnnotationType"/> in the dumper, so the filter is testable.
    /// Gates the enumeration itself.
    /// </summary>
    IReadOnlyList<object> TableAnnotations(object view);

    /// <summary><c>ITableAnnotation.Type</c>, in swTableAnnotationType_e.</summary>
    int TableAnnotationType(object table);

    /// <summary>
    /// <c>IDisplayDimension.GetDimension2(0)</c> -> <c>IDimension.FullName</c>, falling back
    /// to <c>Name</c>. Gates all three itself.
    /// </summary>
    string? DimensionName(object dimension);

    /// <summary><c>IDisplayDimension.Type2</c>, verbatim.</summary>
    int DimensionType(object dimension);

    /// <summary><c>IDisplayDimension.GetOverride()</c>.</summary>
    bool IsOverridden(object dimension);

    /// <summary><c>IDisplayDimension.GetOverrideValue()</c>, in system units.</summary>
    double OverrideValue(object dimension);

    /// <summary>
    /// <c>IDimension.GetSystemValue3(1, null)</c>, the computed value. Two interop calls -
    /// the display dimension's <c>GetDimension2(0)</c> and then <c>GetSystemValue3</c> - each
    /// gated inside the implementation under its own member name.
    /// </summary>
    double DimensionValue(object dimension);

    /// <summary><c>IAnnotation.GetName()</c>.</summary>
    string? AnnotationName(object annotation);

    /// <summary><c>IAnnotation.GetType()</c>, verbatim, in swAnnotationType_e.</summary>
    int AnnotationType(object annotation);

    /// <summary><c>IAnnotation.IsDangling()</c>.</summary>
    bool IsDangling(object annotation);

    /// <summary><c>INote.GetText()</c>.</summary>
    string? NoteText(object note);

    /// <summary><c>IRevisionTableAnnotation.CurrentRevision</c>, verbatim.</summary>
    string? CurrentRevision(object table);

    /// <summary>
    /// <c>ITableAnnotation.RowCount</c> and <c>ColumnCount</c>, behind the runtime COM cast
    /// PROBE-4 asks about. Throws when the cast fails; the dumper turns that into a
    /// <c>revision_table_read</c> gap and the table keeps its <c>current_revision_raw</c>.
    /// </summary>
    RevisionTableShape TableShape(object table);

    /// <summary><c>ITableAnnotation.Text[row, column]</c>.</summary>
    string? Cell(object table, int row, int column);

    /// <summary>
    /// The record's persistent reference, scoped to the drawing document; null when
    /// SOLIDWORKS gave none, which PROBE-10 says is the likely answer for most of these
    /// kinds. Gates <c>GetPersistReference3</c> itself.
    /// </summary>
    ScopedPersistRef? PersistRef(object entity);
}

/// <summary>
/// T060. The <c>drawing</c> phase (schema 1.4.0): one <see cref="DrawingRecord"/> for the
/// drawing document the dump is attached to, with its sheets, views, display dimensions,
/// annotations, notes and revision tables.
///
/// <see cref="DrawingTraversal"/> owns the order and the ids; this class owns the reads and
/// what becomes of a read that failed. Four rules shape every one of them:
///
///   * <b>Nothing is activated.</b> A non-active sheet is read as it stands. If its views
///     come back empty - PROBE-7's open question - that is a <c>drawing_sheet_views</c> gap
///     naming the sheet, and every drawing check is then unresolved for that sheet.
///     <c>ActivateSheet</c> and <c>ActivateView</c> are on the read-only denylist and are
///     not called (FR-044, research R2.7).
///   * <b>A number is never written with a guessed unit.</b> <c>dimension_type_raw</c>
///     decides whether a value is a length or an angle; a type that decides neither leaves
///     both value fields null plus a <c>dimension_unit</c> gap, so the check reports that
///     dimension unresolved rather than rendering a number the engineer cannot trust. This
///     is difference p, and it is the macro's own bug.
///   * <b>An unreadable value is a gap, never an empty string.</b> An annotation with no
///     readable name is still a subject, identified by its id, its sheet and its view
///     (difference o); a note whose text could not be read leaves the export-control check
///     unresolved, because an unread note cannot be shown not to carry the statement.
///   * <b>Both revision readings are kept.</b> <c>current_revision_raw</c> is recorded
///     verbatim, including the empty string it returns under some vaults, alongside the
///     cells; the check names both with their source rather than letting the dumper choose
///     (RK-4).
/// </summary>
public sealed class DrawingDumper : IDrawingSource
{
    /// <summary>
    /// swTableAnnotationType_e.swTableAnnotation_RevisionBlock. The filter that turns
    /// "every table annotation on this view" into "the revision tables"; a bill of materials
    /// or a hole chart on the same sheet is a table annotation too.
    /// </summary>
    private const int RevisionBlockTableType = 3;

    /// <summary>
    /// swDimensionType_e values whose dimension is an <b>angle</b> on the pilot interop
    /// (32.5.0.48): swAngularDimension = 3 and swAngularOrdinateDimension = 16.
    /// </summary>
    private static readonly HashSet<int> AngularDimensionTypes = new HashSet<int> { 3, 16 };

    /// <summary>
    /// swDimensionType_e values whose dimension is a <b>length</b>: ordinate (1), linear (2),
    /// arc length (4), radial (5), diameter (6), horizontal and vertical ordinate (7, 8),
    /// z-axis (9), chamfer (10), horizontal and vertical linear (11, 12), radial linear (14)
    /// and diametric linear (15).
    ///
    /// swDimensionTypeUnknown (0) and swScalarDimension (13) are deliberately in neither set:
    /// the first says SOLIDWORKS does not know, and the second is a pure number with no unit
    /// at all. Both leave the value null plus a <c>dimension_unit</c> gap, which is the whole
    /// point of the rule.
    /// </summary>
    private static readonly HashSet<int> LengthDimensionTypes =
        new HashSet<int> { 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15 };

    private readonly SwGate _gate;
    private readonly IDrawingReader _reader;

    public DrawingDumper(SwGate gate, IDrawingReader reader)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _reader = reader ?? throw new ArgumentNullException(nameof(reader));
    }

    /// <summary>
    /// The unit a dimension's value is recorded in, decided by <c>IDisplayDimension.Type2</c>
    /// alone, or null when the type decides no unit at all.
    ///
    /// The units are SOLIDWORKS' documented <b>system</b> units - metres and radians - and
    /// nothing is converted here: the macro multiplied by one thousand "blindly assuming the
    /// system units are in metres" and then assigned a formatted string back into a number.
    /// What <c>GetOverrideValue</c> actually reports is PROBE-6; until it answers, this is
    /// the reading the package states, and Python renders whichever of the two units the
    /// package recorded.
    /// </summary>
    public static string? UnitOf(int? dimensionTypeRaw)
    {
        if (dimensionTypeRaw == null)
        {
            return null;
        }

        if (LengthDimensionTypes.Contains(dimensionTypeRaw.Value))
        {
            return PackageSerializer.EnumToJsonName(LengthUnit.M);
        }

        return AngularDimensionTypes.Contains(dimensionTypeRaw.Value)
            ? PackageSerializer.EnumToJsonName(AngleUnit.Rad)
            : null;
    }

    public IReadOnlyList<DrawingRecord> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        string documentId = scope.DocumentId(scope.Tree.RootDocumentPath);

        object? drawing = null;
        if (!scope.Gaps.TryStep(
            "drawing_sheet",
            documentId,
            "read the open document as a drawing",
            () => { drawing = _reader.Drawing(); }))
        {
            return new List<DrawingRecord>();
        }

        if (drawing == null)
        {
            // The phase runs only for a drawing root, so this is the dump disagreeing with
            // itself: recorded rather than swallowed, because an empty drawing_records[] with
            // nothing beside it reads as a drawing with no sheets.
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_sheet",
                documentId,
                "The open document did not answer as a drawing, so no sheet, view, dimension, "
                + "annotation, note or revision table was read.",
                null);
            return new List<DrawingRecord>();
        }

        string? activeSheetName = scope.Gaps.TryStep(
            "drawing_sheet",
            documentId,
            "read which sheet is active",
            () => _reader.ActiveSheetName(drawing!));

        var traversal = new DrawingTraversal(documentId, activeSheetName);

        List<string>? names = scope.Gaps.TryStep(
            "drawing_sheet",
            documentId,
            "enumerate the drawing's sheets",
            () => new List<string>(_reader.SheetNames(drawing!)));

        List<string> sheetNames = names ?? new List<string>();

        // The loop position IS the sheet's index in the package (section 3.2), so it is
        // carried down rather than recomputed: a name the Sheet[name] indexer will not answer
        // for records no sheet, and the sheets after it keep the positions the drawing gives
        // them instead of sliding up one.
        for (int index = 0; index < sheetNames.Count; index++)
        {
            ReadSheet(scope, traversal, drawing!, sheetNames[index], index, documentId);
        }

        return new List<DrawingRecord> { traversal.Record };
    }

    /// <summary>One sheet: its own reads, then its views, then its revision-table cross-check.</summary>
    private void ReadSheet(
        DumpScope scope,
        DrawingTraversal traversal,
        object drawing,
        string name,
        int index,
        string documentId)
    {
        object? sheet = null;
        if (!scope.Gaps.TryStep(
            "drawing_sheet",
            documentId,
            $"read sheet '{name}'",
            () => { sheet = _gate.Call("Sheet", () => _reader.Sheet(drawing, name)); }))
        {
            return;
        }

        if (sheet == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_sheet",
                documentId,
                $"GetSheetNames listed '{name}', but the drawing gave no sheet for that name, "
                + "so nothing on it was read.",
                null);
            return;
        }

        // The name GetSheetNames gave is the fallback: a sheet that answered the enumeration
        // and then would not name itself is still that sheet, and dropping it would lose
        // everything on it over one string.
        string sheetName = ReadText(
            scope, "drawing_sheet", documentId, $"read the name of sheet '{name}'",
            "GetName", () => _reader.SheetName(sheet!)) ?? name;

        DrawingSheetRecord record = traversal.AddSheet(sheetName, index);

        record.SheetFormatName = ReadText(
            scope, "drawing_sheet", record.Id,
            $"read the sheet format of '{sheetName}'",
            "GetSheetFormatName", () => _reader.SheetFormatName(sheet!));

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "drawing_sheet",
            record.Id,
            $"read a persistent reference for sheet '{sheetName}'",
            () => _reader.PersistRef(sheet!));

        record.PersistRef = reference?.Base64;
        record.PersistRefScope = reference?.ScopeDocumentId;

        IReadOnlyList<object>? views = scope.Gaps.TryStep(
            "drawing_sheet_views",
            record.Id,
            $"enumerate the views of sheet '{sheetName}'",
            () => _gate.Call("GetViews", () => _reader.Views(sheet!)));

        if (views == null)
        {
            return;
        }

        if (views.Count == 0 && !record.WasActive)
        {
            // PROBE-7. Whether a non-active sheet's contents come back without activating it
            // is the open question, and this is the answer when they do not: an unresolved
            // row naming the sheet, never an activation and never "the sheet has no views".
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_sheet_views",
                record.Id,
                $"Sheet '{sheetName}' was not the active sheet and listed no views, so nothing "
                + "on it could be read. The sheet was not activated to look again.",
                null);
            return;
        }

        foreach (object view in views)
        {
            ReadView(scope, traversal, record, view, sheetName);
        }

        CrossCheckRevisionTable(scope, record, sheet!, sheetName);
    }

    /// <summary>One view, and everything it owns.</summary>
    private void ReadView(
        DumpScope scope,
        DrawingTraversal traversal,
        DrawingSheetRecord sheet,
        object view,
        string sheetName)
    {
        DrawingView record = traversal.AddView(sheet);
        string where = $"view {record.Id} of sheet '{sheetName}'";

        record.Name = ReadText(
            scope, "drawing_view", record.Id, $"read the name of {where}",
            "GetName2", () => _reader.ViewName(view));

        int? viewType = null;
        scope.Gaps.TryStep(
            "drawing_view",
            record.Id,
            $"read the view type of {where}",
            () => { viewType = _gate.Call("Type", () => _reader.ViewType(view)); });
        record.ViewTypeRaw = viewType;

        // Recorded whether or not the model is loaded: the path is what lets the gap below
        // name the model that was not read (FR-025). A view that references nothing names
        // nothing, and that is not a loss.
        record.ReferencedModelPath = scope.Gaps.TryStep(
            "drawing_view",
            record.Id,
            $"read the referenced model name of {where}",
            () => _gate.Call(
                "GetReferencedModelName", () => _reader.ReferencedModelPath(view)));

        ReadReferencedDocument(scope, record, view, where);

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "drawing_view",
            record.Id,
            $"read a persistent reference for {where}",
            () => _reader.PersistRef(view));

        record.PersistRef = reference?.Base64;
        record.PersistRefScope = reference?.ScopeDocumentId;

        ReadDimensions(scope, traversal, record, view, where);
        ReadAnnotations(scope, traversal, record, view, where);
        ReadNotes(scope, traversal, record, view, where);
        ReadRevisionTables(scope, traversal, sheet, view, where);
    }

    /// <summary>
    /// The document a view references, resolved to a document of this package. A referenced
    /// model that is not loaded is a gap naming it, and every part- and assembly-scope check
    /// for that document is then unresolved coverage (FR-025). <b>Nothing is opened or
    /// loaded to close it.</b>
    /// </summary>
    private void ReadReferencedDocument(
        DumpScope scope, DrawingView record, object view, string where)
    {
        object? referenced = scope.Gaps.TryStep(
            "drawing_referenced_document",
            record.Id,
            $"read the referenced document of {where}",
            () => _gate.Call("ReferencedDocument", () => _reader.ReferencedDocument(view)));

        if (referenced == null)
        {
            if (!string.IsNullOrWhiteSpace(record.ReferencedModelPath))
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "drawing_referenced_document",
                    record.Id,
                    $"'{record.ReferencedModelPath}' is referenced by {where} and is not "
                    + "loaded, so it was not read and its checks are unresolved.",
                    null);
            }

            return;
        }

        string? path = scope.Gaps.TryStep(
            "drawing_referenced_document",
            record.Id,
            $"read the path of the document {where} references",
            () => _gate.Call("GetPathName", () => _reader.DocumentPath(referenced!)));

        if (string.IsNullOrWhiteSpace(path))
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_referenced_document",
                record.Id,
                $"The document {where} references has no file path, so it could not be "
                + "identified as a document of this package.",
                null);
            return;
        }

        record.ReferencedDocumentId = scope.DocumentId(path!);
    }

    private void ReadDimensions(
        DumpScope scope, DrawingTraversal traversal, DrawingView view, object handle, string where)
    {
        IReadOnlyList<object>? dimensions = scope.Gaps.TryStep(
            "dimension_override",
            view.Id,
            $"enumerate the display dimensions of {where}",
            () => _gate.Call("GetDisplayDimensions", () => _reader.DisplayDimensions(handle)));

        foreach (object dimension in dimensions ?? new List<object>())
        {
            ReadDimension(scope, traversal, view, dimension, where);
        }
    }

    /// <summary>One display dimension: its identity, its override flag, and its two values.</summary>
    private void ReadDimension(
        DumpScope scope,
        DrawingTraversal traversal,
        DrawingView view,
        object dimension,
        string where)
    {
        DisplayDimensionRecord record = traversal.AddDimension(view);

        record.Name = ReadText(
            scope, "dimension_override", record.Id,
            $"read the name of dimension {record.Id} on {where}",
            "GetDimension2", () => _reader.DimensionName(dimension));

        int? typeRaw = null;
        scope.Gaps.TryStep(
            "dimension_override",
            record.Id,
            $"read the dimension type of {record.Id} on {where}",
            () => { typeRaw = _gate.Call("Type2", () => _reader.DimensionType(dimension)); });
        record.DimensionTypeRaw = typeRaw;

        bool? overridden = null;
        scope.Gaps.TryStep(
            "dimension_override",
            record.Id,
            $"read the override flag of dimension {record.Id} on {where}",
            () => { overridden = _gate.Call("GetOverride", () => _reader.IsOverridden(dimension)); });
        record.IsOverridden = overridden;

        string? unit = UnitOf(typeRaw);
        bool numberRead = false;

        // No member name: DimensionValue spans GetDimension2 and GetSystemValue3 and gates
        // both itself, so naming one here would report it twice for a single read.
        double? value = ReadNumber(
            scope, record.Id, $"read the value of dimension {record.Id} on {where}",
            null, () => _reader.DimensionValue(dimension));

        numberRead |= value != null;
        record.Value = unit == null || value == null ? null : new Ir.Measure(value.Value, unit);

        // Only an overridden dimension has an override to read; asking otherwise would give
        // every dimension of every drawing a number nobody wrote.
        if (overridden == true)
        {
            double? overrideValue = ReadNumber(
                scope, record.Id,
                $"read the override value of dimension {record.Id} on {where}",
                "GetOverrideValue", () => _reader.OverrideValue(dimension));

            numberRead |= overrideValue != null;
            record.OverrideValue = unit == null || overrideValue == null
                ? null
                : new Ir.Measure(overrideValue.Value, unit);
        }

        if (unit == null && numberRead)
        {
            // Difference p: a number whose unit is unknown is not recorded at all, and the
            // check reports that dimension unresolved rather than rendering a length that may
            // be an angle or a count.
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "dimension_unit",
                record.Id,
                $"Dimension {record.Id} on {where} reports type "
                + $"{typeRaw?.ToString() ?? "unknown"}, which names no unit, so its value was "
                + "not recorded rather than recorded with a guessed one.",
                null);
        }

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "dimension_override",
            record.Id,
            $"read a persistent reference for dimension {record.Id} on {where}",
            () => _reader.PersistRef(dimension));

        record.PersistRef = reference?.Base64;
        record.PersistRefScope = reference?.ScopeDocumentId;
    }

    private void ReadAnnotations(
        DumpScope scope, DrawingTraversal traversal, DrawingView view, object handle, string where)
    {
        IReadOnlyList<object>? annotations = scope.Gaps.TryStep(
            "annotation_identity",
            view.Id,
            $"enumerate the annotations of {where}",
            () => _gate.Call("GetAnnotations", () => _reader.Annotations(handle)));

        foreach (object annotation in annotations ?? new List<object>())
        {
            DrawingAnnotation record = traversal.AddAnnotation(view);

            record.Name = ReadText(
                scope, "annotation_identity", record.Id,
                $"read the name of annotation {record.Id} on {where}",
                "GetName", () => _reader.AnnotationName(annotation));

            int? typeRaw = null;
            scope.Gaps.TryStep(
                "annotation_identity",
                record.Id,
                $"read the type of annotation {record.Id} on {where}",
                () => { typeRaw = _gate.Call("GetType", () => _reader.AnnotationType(annotation)); });
            record.TypeRaw = typeRaw;

            bool? dangling = null;
            scope.Gaps.TryStep(
                "annotation_dangling",
                record.Id,
                $"read the dangling flag of annotation {record.Id} on {where}",
                () => { dangling = _gate.Call("IsDangling", () => _reader.IsDangling(annotation)); });
            record.IsDangling = dangling;

            ScopedPersistRef? reference = scope.Gaps.TryStep(
                "annotation_identity",
                record.Id,
                $"read a persistent reference for annotation {record.Id} on {where}",
                () => _reader.PersistRef(annotation));

            record.PersistRef = reference?.Base64;
            record.PersistRefScope = reference?.ScopeDocumentId;
        }
    }

    private void ReadNotes(
        DumpScope scope, DrawingTraversal traversal, DrawingView view, object handle, string where)
    {
        IReadOnlyList<object>? notes = scope.Gaps.TryStep(
            "note_text",
            view.Id,
            $"enumerate the notes of {where}",
            () => _gate.Call("GetNotes", () => _reader.Notes(handle)));

        foreach (object note in notes ?? new List<object>())
        {
            DrawingNote record = traversal.AddNote(view);

            record.Text = ReadText(
                scope, "note_text", record.Id,
                $"read the text of note {record.Id} on {where}",
                "GetText", () => _reader.NoteText(note));

            ScopedPersistRef? reference = scope.Gaps.TryStep(
                "note_text",
                record.Id,
                $"read a persistent reference for note {record.Id} on {where}",
                () => _reader.PersistRef(note));

            record.PersistRef = reference?.Base64;
            record.PersistRefScope = reference?.ScopeDocumentId;
        }
    }

    /// <summary>
    /// The revision tables of one view, filtered on the revision type and recorded on the
    /// sheet. The enumeration is per view because that is the only walk that finds every
    /// table: <c>ISheet.RevisionTable</c> is single-valued and would lose the second one.
    /// </summary>
    private void ReadRevisionTables(
        DumpScope scope,
        DrawingTraversal traversal,
        DrawingSheetRecord sheet,
        object view,
        string where)
    {
        IReadOnlyList<object>? tables = scope.Gaps.TryStep(
            "revision_table_read",
            sheet.Id,
            $"enumerate the table annotations of {where}",
            () => _reader.TableAnnotations(view));

        foreach (object table in tables ?? new List<object>())
        {
            int? type = null;
            if (!scope.Gaps.TryStep(
                "revision_table_read",
                sheet.Id,
                $"read the type of a table annotation on {where}",
                () => { type = _gate.Call("ITableAnnotation.Type", () => _reader.TableAnnotationType(table)); }))
            {
                continue;
            }

            if (type != RevisionBlockTableType)
            {
                continue;
            }

            ReadRevisionTable(scope, traversal, sheet, table, where);
        }
    }

    /// <summary>One revision table: both revision readings, and every cell.</summary>
    private void ReadRevisionTable(
        DumpScope scope,
        DrawingTraversal traversal,
        DrawingSheetRecord sheet,
        object table,
        string where)
    {
        RevisionTable record = traversal.AddRevisionTable(sheet);

        // Verbatim, including the empty string: the macro's author recorded that this comes
        // back empty under the vault, and the check names both readings with their source
        // rather than letting the dumper pick one (RK-4).
        record.CurrentRevisionRaw = ReadText(
            scope, "revision_table_read", record.Id,
            $"read the current revision of table {record.Id} on {where}",
            "CurrentRevision", () => _reader.CurrentRevision(table));

        RevisionTableShape? shape = null;
        if (!scope.Gaps.TryStep(
            "revision_table_read",
            record.Id,
            $"read the row and column counts of table {record.Id} on {where}",
            () => { shape = _reader.TableShape(table); }))
        {
            // PROBE-4: IRevisionTableAnnotation declares no base interface, so reaching the
            // cells needs a runtime COM cast. A failed cast leaves the rows empty and says
            // so; the check is then unresolved for this table rather than reading it as a
            // table with nothing in it.
            return;
        }

        record.RowCount = shape!.Value.RowCount;
        record.ColumnCount = shape!.Value.ColumnCount;

        for (int row = 0; row < shape!.Value.RowCount; row++)
        {
            var cells = new RevisionTableRow
            {
                Index = row,

                // Which row is the revision row, and which is the header, are profile
                // questions answered in Python from the profile's revision cell and its
                // header row. PROBE-4 has not settled whether the header sits inside
                // RowCount or outside it, so the extractor classifies nothing rather than
                // guessing.
                IsHeader = null,
            };

            for (int column = 0; column < shape!.Value.ColumnCount; column++)
            {
                int r = row;
                int c = column;

                string? text = null;
                bool read = scope.Gaps.TryStep(
                    "revision_table_read",
                    record.Id,
                    $"read cell [{r}, {c}] of table {record.Id} on {where}",
                    () => { text = _gate.Call("Text", () => _reader.Cell(table, r, c)); });

                // An empty cell is the empty string; a null is one that could not be read.
                // Confusing the two would turn a real revision mismatch into a pass.
                cells.Cells.Add(read ? text : null);
            }

            record.Rows.Add(cells);
        }

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "revision_table_read",
            record.Id,
            $"read a persistent reference for table {record.Id} on {where}",
            () => _reader.PersistRef(table));

        record.PersistRef = reference?.Base64;
        record.PersistRefScope = reference?.ScopeDocumentId;
    }

    /// <summary>
    /// <c>ISheet.RevisionTable</c>, read and compared against the per-view walk. It is not
    /// the enumeration - it returns at most one table - but a sheet whose property names a
    /// revision table the walk never found is a <b>visible disagreement</b> rather than an
    /// absence nobody can see, which is the one thing a coverage check cannot afford.
    ///
    /// The comparison is presence, not identity: two interop wrappers for one table need not
    /// be the same object, and a false disagreement on every sheet would be noise an engineer
    /// learns to skip.
    /// </summary>
    private void CrossCheckRevisionTable(
        DumpScope scope, DrawingSheetRecord sheet, object handle, string sheetName)
    {
        object? property = scope.Gaps.TryStep(
            "revision_table_read",
            sheet.Id,
            $"read the revision table property of sheet '{sheetName}'",
            () => _gate.Call("RevisionTable", () => _reader.SheetRevisionTable(handle)));

        if (property == null || sheet.RevisionTables.Count > 0)
        {
            return;
        }

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "revision_table_read",
            sheet.Id,
            $"Sheet '{sheetName}' reports a revision table that the view walk did not find, "
            + "so its rows were not read and the revision check is unresolved for it.",
            null);
    }

    /// <summary>
    /// One gated string read. Null plus a gap of <paramref name="entityKind"/> when it threw
    /// <b>or when SOLIDWORKS answered null</b>: an unreadable value is unresolved coverage,
    /// and recording it as an empty string would make it a pass.
    /// </summary>
    private string? ReadText(
        DumpScope scope,
        string entityKind,
        string entityId,
        string reason,
        string member,
        Func<string?> read)
    {
        string? text = null;
        bool answered = scope.Gaps.TryStep(
            entityKind, entityId, reason, () => { text = _gate.Call(member, read); });

        if (answered && text == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                entityKind,
                entityId,
                $"SOLIDWORKS gave no value for {member} when asked to {reason}.",
                null);
        }

        return text;
    }

    /// <summary>
    /// One number read; null plus a <c>dimension_override</c> gap when it threw.
    ///
    /// <paramref name="member"/> is the interop member the read maps to, gated here so the
    /// read-only guard and the SC-010 audit see the production name even under a fake. It is
    /// null for the one reader member that spans several interop calls and gates every one of
    /// them itself - <see cref="IDrawingReader.DimensionValue"/> - because gating it here as
    /// well would report the same read twice.
    /// </summary>
    private double? ReadNumber(
        DumpScope scope, string entityId, string reason, string? member, Func<double> read)
    {
        double? value = null;
        scope.Gaps.TryStep(
            "dimension_override",
            entityId,
            reason,
            () => { value = member == null ? read() : _gate.Call(member, read); });

        return value;
    }
}
