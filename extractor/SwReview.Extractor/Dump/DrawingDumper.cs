using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using SwReview.Extractor.Guard;
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
/// What a model entity an annotation is attached to is, as far as the attachment rule cares
/// (feature 011, contracts/native-evidence.md section 3, "Attachments"): a face is kept, an edge
/// becomes its two adjacent faces, and anything else adds no row. A COM cast, not a call.
/// </summary>
public enum AttachedEntityKind
{
    Face,
    Edge,
    Other,
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
public interface IDrawingReader : IDimensionToleranceReads, IAnnotationSymbolReads
{
    /// <summary>
    /// <paramref name="document"/> as an <c>IDrawingDoc</c>, or null when it is not a drawing:
    /// the root document for a drawing root, or an open drawing a review attached (feature
    /// 011). A cast, nothing opened: every drawing read is one SOLIDWORKS already has open
    /// (FR-044).
    /// </summary>
    object? Drawing(object document);

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
    /// The record's persistent reference, scoped to <paramref name="document"/> - the drawing
    /// being read, so each drawing's references are its own (feature 011); null when
    /// SOLIDWORKS gave none, which PROBE-10 says is the likely answer for most of these
    /// kinds. Gates <c>GetPersistReference3</c> itself. An attached model face's reference is
    /// asked of its own part document the same way.
    /// </summary>
    ScopedPersistRef? PersistRef(object document, object entity);

    // ---- feature 011 (IR 1.6.0, contracts/native-evidence.md section 3) ----------------------
    //
    // One interop read each, gated by the dumper under the member named, unless the summary says
    // the member gates its several calls itself. The tolerance reads are IDimensionToleranceReads,
    // feature 010's, on the display dimension's IDimension.

    /// <summary><c>IDrawingDoc.IsDetailingMode()</c>.</summary>
    bool IsDetailingMode(object drawing);

    /// <summary>
    /// <c>IModelDocExtension.GetUserPreferenceInteger(preference, 0)</c> of the drawing's own
    /// document (<c>swUnitsLinear</c> 47, <c>swDetailingLinearDimPrecision</c> 24,
    /// <c>swUnitsLinearDecimalPlaces</c> 49, <c>swDetailingLinearTolPrecision</c> 25).
    /// </summary>
    int UserPreferenceInteger(object document, int preference);

    /// <summary>
    /// <c>IModelDocExtension.GetUserPreferenceString(preference, 0)</c>
    /// (<c>swDetailingDimensionStandardName</c> 65).
    /// </summary>
    string? UserPreferenceString(object document, int preference);

    /// <summary><c>ISheet.GetTemplateName()</c>: the sheet format's <c>.slddrt</c> path.</summary>
    string? SheetTemplateName(object sheet);

    /// <summary>
    /// <c>ISheet.GetProperties2()</c>: paper size, template, scale numerator, scale denominator,
    /// first angle, width, height and the rest, verbatim; null when it answered nothing.
    /// </summary>
    IReadOnlyList<double>? SheetProperties(object sheet);

    /// <summary><c>IView.ReferencedConfiguration</c>.</summary>
    string? ReferencedConfiguration(object view);

    /// <summary><c>IView.IsModelOutOfDate()</c>.</summary>
    bool IsModelOutOfDate(object view);

    /// <summary><c>IView.IsModelLoaded()</c>.</summary>
    bool IsModelLoaded(object view);

    /// <summary><c>IView.ScaleDecimal</c>.</summary>
    double ScaleDecimal(object view);

    /// <summary><c>IView.GetOrientationName()</c>.</summary>
    string? OrientationName(object view);

    /// <summary>
    /// <c>IDisplayDimension.GetText(part)</c>, <c>swDimensionTextParts_e</c>: prefix 1, suffix 2,
    /// callout above 3, callout below 4.
    /// </summary>
    string? DimensionText(object dimension, int part);

    /// <summary><c>IDisplayDimension.GetPrimaryPrecision2()</c>.</summary>
    int PrimaryPrecision(object dimension);

    /// <summary><c>IDisplayDimension.GetPrimaryTolPrecision2()</c>.</summary>
    int PrimaryTolerancePrecision(object dimension);

    /// <summary><c>IDisplayDimension.GetUseDocPrecision()</c>.</summary>
    bool UsesDocumentPrecision(object dimension);

    /// <summary><c>IDisplayDimension.GetUnits()</c>, <c>swLengthUnit_e</c> for a length.</summary>
    int Units(object dimension);

    /// <summary><c>IDisplayDimension.GetUseDocUnits()</c>.</summary>
    bool UsesDocumentUnits(object dimension);

    /// <summary>
    /// <c>IDisplayDimension.GetDimension2(0)</c>: the <c>IDimension</c> the tolerance and the
    /// driven state are read from; null when it gives none.
    /// </summary>
    object? DimensionOf(object dimension);

    /// <summary><c>IDisplayDimension.IsReferenceDim()</c>.</summary>
    bool IsReferenceDimension(object dimension);

    /// <summary><c>IDimension.DrivenState</c> of <see cref="DimensionOf"/>'s answer, verbatim.</summary>
    int DrivenState(object modelDimension);

    /// <summary><c>IDisplayDimension.IsHoleCallout()</c>.</summary>
    bool IsHoleCallout(object dimension);

    /// <summary>
    /// <c>IDisplayDimension.GetHoleCalloutVariables()</c>, each variable as "name=value" verbatim,
    /// in order; null when it answered nothing. Gates the enumeration and every variable's reads
    /// itself, because one list is several members.
    /// </summary>
    IReadOnlyList<string>? HoleCalloutVariables(object dimension);

    /// <summary><c>IDisplayDimension.GetAnnotation()</c>: the annotation its attachments are read from.</summary>
    object? DimensionAnnotation(object dimension);

    /// <summary><c>IAnnotation.GetAttachedEntities3()</c>; a null entry is a dangling attachment.</summary>
    IReadOnlyList<object?> AttachedEntities(object annotation);

    /// <summary><c>IView.GetCorrespondingEntity(entity)</c>: the model entity; null when it maps to none.</summary>
    object? CorrespondingEntity(object view, object entity);

    /// <summary>Whether a model entity is a face, an edge, or neither: a COM cast, not gated.</summary>
    AttachedEntityKind EntityKind(object entity);

    /// <summary><c>IEdge.GetTwoAdjacentFaces2()</c>.</summary>
    IReadOnlyList<object> AdjacentFaces(object edge);

    /// <summary>
    /// The part document that owns a model face: the view's referenced document for a part
    /// drawing, the face's component's document for an assembly drawing
    /// (<c>IEntity.GetComponent</c>, <c>IComponent2.GetModelDoc2</c>). Gates its reads itself; null
    /// when no document answers. Nothing is opened or resolved.
    /// </summary>
    object? FaceDocument(object view, object face);

    /// <summary><c>ISFSymbol.GetSymbol()</c>, verbatim.</summary>
    int SurfaceFinishSymbol(object symbol);

    /// <summary><c>ISFSymbol.GetTextCount()</c>.</summary>
    int SurfaceFinishTextCount(object symbol);

    /// <summary><c>ISFSymbol.GetTextAtIndex(index)</c>.</summary>
    string? SurfaceFinishText(object symbol, int index);

    /// <summary><c>ITableAnnotation.Title</c>.</summary>
    string? TableTitle(object table);

    /// <summary>
    /// <c>IBomTableAnnotation.GetModelPathNames(row, out, out)</c>: the model paths a bill of
    /// materials row stands for; null when it answers none. The cast to the bill-of-materials
    /// interface is a COM cast, not a call.
    /// </summary>
    IReadOnlyList<string>? BomModelPaths(object table, int row);
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

    /// <summary><c>swTableAnnotationType_e.swTableAnnotation_BillOfMaterials</c> (feature 011).</summary>
    private const int BillOfMaterialsTableType = 2;

    /// <summary>
    /// <c>swAnnotationType_e</c> (reflected on 2024 SP5): the typed annotations a drawing record
    /// gains fields for (feature 011) - datum tag 2, geometric tolerance 5, surface finish 7.
    /// </summary>
    private const int DatumTagAnnotation = 2;

    private const int GtolAnnotation = 5;

    private const int SurfaceFinishAnnotation = 7;

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

    /// <summary>
    /// <c>swUserPreferenceIntegerValue_e</c> (reflected on 2024 SP5): the drawing's settings the
    /// package records (feature 011, contracts/native-evidence.md section 3).
    /// </summary>
    private const int LengthUnitPreference = 47;

    private const int DimensionPrecisionPreference = 24;

    private const int DecimalPlacesPreference = 49;

    private const int TolerancePrecisionPreference = 25;

    /// <summary><c>swUserPreferenceStringValue_e.swDetailingDimensionStandardName</c>.</summary>
    private const int DraftingStandardPreference = 65;

    /// <summary><c>swDimensionTextParts_e</c>: prefix, suffix, callout above, callout below.</summary>
    private const int TextPrefix = 1;

    private const int TextSuffix = 2;

    private const int TextAbove = 3;

    private const int TextBelow = 4;

    /// <summary>The items of <c>ISheet.GetProperties2()</c> the sheet's scale and projection are.</summary>
    private const int ScaleNumeratorItem = 2;

    private const int ScaleDenominatorItem = 3;

    private const int FirstAngleItem = 4;

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

    /// <summary>
    /// One record per drawing of <see cref="DumpScope.Drawings"/>, in order, every id from the
    /// package's allocators (feature 011, T010). A drawing that cannot be read is a gap naming
    /// it and the others are still read.
    /// </summary>
    public IReadOnlyList<DrawingRecord> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var records = new List<DrawingRecord>();
        foreach (ScopedDrawing drawing in scope.Drawings)
        {
            DrawingRecord? record = DumpOne(scope, drawing);
            if (record != null)
            {
                records.Add(record);
            }
        }

        return records;
    }

    private DrawingRecord? DumpOne(DumpScope scope, ScopedDrawing scoped)
    {
        string documentId = scope.DocumentId(scoped.DocumentPath);

        if (scoped.Document == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_sheet",
                documentId,
                $"No document handle was handed over for '{scoped.DocumentPath}', so no sheet, view, "
                + "dimension, annotation, note or revision table of it was read.",
                null);
            return null;
        }

        object document = scoped.Document;
        object? drawing = null;
        if (!scope.Gaps.TryStep(
            "drawing_sheet",
            documentId,
            "read the open document as a drawing",
            () => { drawing = _reader.Drawing(document); }))
        {
            return null;
        }

        if (drawing == null)
        {
            // The dump was told this document is a drawing and the cast disagreed: recorded
            // rather than swallowed, because an empty drawing_records[] with nothing beside it
            // reads as a drawing with no sheets.
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_sheet",
                documentId,
                "The open document did not answer as a drawing, so no sheet, view, dimension, "
                + "annotation, note or revision table was read.",
                null);
            return null;
        }

        string? activeSheetName = scope.Gaps.TryStep(
            "drawing_sheet",
            documentId,
            "read which sheet is active",
            () => _reader.ActiveSheetName(drawing!));

        var pass = new DrawingPass(
            new DrawingTraversal(documentId, activeSheetName, scope.DrawingIds),
            document,
            scoped.ReviewedDocumentId);

        ReadSettings(scope, pass, drawing!, documentId);

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
            ReadSheet(scope, pass, drawing!, sheetNames[index], index, documentId);
        }

        return pass.Traversal.Record;
    }

    /// <summary>
    /// The drawing's settings (feature 011): detailing mode, the length unit, the default
    /// dimension and tolerance precisions and decimal places, and the drafting standard, each a
    /// <c>drawing_document_settings</c> gap on the drawing when it cannot be read.
    /// </summary>
    private void ReadSettings(DumpScope scope, DrawingPass pass, object drawing, string documentId)
    {
        DrawingRecord record = pass.Traversal.Record;
        const string Settings = "drawing_document_settings";

        record.IsDetailingMode = Read(
            scope, Settings, documentId, "read whether the drawing is in detailing mode",
            "IsDetailingMode", () => _reader.IsDetailingMode(drawing));
        record.LengthUnitRaw = ReadPreference(scope, pass, documentId, LengthUnitPreference, "length unit");
        record.DimensionPrecisionRaw = ReadPreference(
            scope, pass, documentId, DimensionPrecisionPreference, "default dimension precision");
        record.UnitsDecimalPlacesRaw = ReadPreference(
            scope, pass, documentId, DecimalPlacesPreference, "length decimal places");
        record.TolerancePrecisionRaw = ReadPreference(
            scope, pass, documentId, TolerancePrecisionPreference, "default tolerance precision");
        record.DraftingStandardName = ReadText(
            scope, Settings, documentId, "read the drawing's drafting standard",
            "GetUserPreferenceString", () => _reader.UserPreferenceString(pass.Document, DraftingStandardPreference));

        pass.DetailingMode = record.IsDetailingMode;
    }

    private int? ReadPreference(DumpScope scope, DrawingPass pass, string documentId, int preference, string what) =>
        Read(
            scope, "drawing_document_settings", documentId, $"read the drawing's {what}",
            "GetUserPreferenceInteger", () => _reader.UserPreferenceInteger(pass.Document, preference));

    /// <summary>
    /// One drawing's pass: the traversal that orders and numbers its records, the document every
    /// persistent reference of it is scoped to, and - for a drawing read with a reviewed design -
    /// the rule that ties a view's path to a document of the package, with the outside paths this
    /// drawing has already named (feature 011).
    /// </summary>
    private sealed class DrawingPass
    {
        private readonly HashSet<string> _outsideNamed = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        public DrawingPass(
            DrawingTraversal traversal, object document, Func<string, string?>? reviewedDocumentId)
        {
            Traversal = traversal;
            Document = document;
            ReviewedDocumentId = reviewedDocumentId;
        }

        public DrawingTraversal Traversal { get; }

        public object Document { get; }

        /// <summary>Null for a drawing root; see <see cref="ScopedDrawing.ReviewedDocumentId"/>.</summary>
        public Func<string, string?>? ReviewedDocumentId { get; }

        /// <summary>The drawing's detailing mode as read; null when it could not be.</summary>
        public bool? DetailingMode { get; set; }

        private readonly List<object> _tableHandles = new List<object>();
        private readonly HashSet<string> _tableReferences = new HashSet<string>(StringComparer.Ordinal);
        private Func<string, string?>? _packageDocumentId;

        /// <summary>Whether this very annotation was recorded already in this drawing's table walk.</summary>
        public bool TableHandleSeen(object table) => _tableHandles.Any(seen => ReferenceEquals(seen, table));

        /// <summary>
        /// Whether a table was recorded already in this drawing - by persistent reference when there
        /// is one, else by the annotation's identity - recording it as seen when it was not.
        /// </summary>
        public bool TableSeen(object table, string? persistRef)
        {
            if (TableHandleSeen(table) || (persistRef != null && !_tableReferences.Add(persistRef)))
            {
                return true;
            }

            _tableHandles.Add(table);
            return false;
        }

        /// <summary>
        /// The rule that ties a path to a document of this package: the reviewed documents' rule for
        /// an attached or confirmed drawing, and the traversal's components for a drawing root.
        /// </summary>
        public Func<string, string?> PackageDocumentId(DumpScope scope) =>
            ReviewedDocumentId ?? (_packageDocumentId ??= OpenDrawingDiscovery.DocumentResolver(
                scope.Components.Select(component => component.Node.DocumentPath)));

        /// <summary>
        /// True the first time an outside path is named in this drawing, so its gap is written
        /// once per path, on the first view that shows it (contracts/open-drawings.md section 3).
        /// </summary>
        public bool NameOutside(string path) =>
            _outsideNamed.Add(OpenDrawingDiscovery.Key(path) ?? path.Trim());
    }

    /// <summary>One sheet: its own reads, then its views, then its revision-table cross-check.</summary>
    private void ReadSheet(
        DumpScope scope,
        DrawingPass pass,
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

        DrawingSheetRecord record = pass.Traversal.AddSheet(sheetName, index);

        record.SheetFormatName = ReadText(
            scope, "drawing_sheet", record.Id,
            $"read the sheet format of '{sheetName}'",
            "GetSheetFormatName", () => _reader.SheetFormatName(sheet!));

        ReadSheetFormatAndScale(scope, record, sheet!, sheetName);

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "drawing_sheet",
            record.Id,
            $"read a persistent reference for sheet '{sheetName}'",
            () => _reader.PersistRef(pass.Document, sheet!));

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
            ReadView(scope, pass, record, view, sheetName);
        }

        CrossCheckRevisionTable(scope, record, sheet!, sheetName);
    }

    /// <summary>
    /// The sheet format's path, and the scale and projection from <c>GetProperties2</c> (feature
    /// 011): items 2 and 3 are the scale, item 4 is first angle. Properties that cannot be read, or
    /// that answer fewer than five items, leave all three null with one gap.
    /// </summary>
    private void ReadSheetFormatAndScale(DumpScope scope, DrawingSheetRecord record, object sheet, string sheetName)
    {
        record.SheetFormatPath = ReadText(
            scope, "drawing_sheet", record.Id, $"read the sheet format path of '{sheetName}'",
            "GetTemplateName", () => _reader.SheetTemplateName(sheet));

        IReadOnlyList<double>? properties = null;
        if (!scope.Gaps.TryStep(
            "drawing_sheet",
            record.Id,
            $"read the scale and projection of sheet '{sheetName}'",
            () => { properties = _gate.Call("GetProperties2", () => _reader.SheetProperties(sheet)); }))
        {
            return;
        }

        if (properties == null || properties.Count <= FirstAngleItem)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_sheet",
                record.Id,
                $"GetProperties2 answered {(properties == null ? "nothing" : properties.Count.ToString(CultureInfo.InvariantCulture) + " values")} "
                + $"for sheet '{sheetName}', fewer than the five its scale and projection are read "
                + "from, so neither was recorded.",
                null);
            return;
        }

        record.ScaleNumerator = properties[ScaleNumeratorItem];
        record.ScaleDenominator = properties[ScaleDenominatorItem];
        record.FirstAngle = properties[FirstAngleItem] != 0d;
    }

    /// <summary>One view, and everything it owns.</summary>
    private void ReadView(
        DumpScope scope,
        DrawingPass pass,
        DrawingSheetRecord sheet,
        object view,
        string sheetName)
    {
        DrawingView record = pass.Traversal.AddView(sheet);
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

        ReadReferencedDocument(scope, pass, record, view, where);
        ReadViewState(scope, record, view, where);

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "drawing_view",
            record.Id,
            $"read a persistent reference for {where}",
            () => _reader.PersistRef(pass.Document, view));

        record.PersistRef = reference?.Base64;
        record.PersistRefScope = reference?.ScopeDocumentId;

        var context = new ViewContext(record, view, sheetName, AttachmentsUnavailable(pass, record));
        ReadDimensions(scope, pass, context, where);
        ReadAnnotations(scope, pass, context, where);
        ReadNotes(scope, pass, record, view, where);
        ReadTables(scope, pass, sheet, record, view, where);
        NameSkippedAttachments(scope, context);
    }

    /// <summary>
    /// The view's state (feature 011): the configuration it shows, whether its model is out of
    /// date or loaded - <c>drawing_view_state</c> gaps - and its scale and orientation -
    /// <c>drawing_view</c> gaps.
    /// </summary>
    private void ReadViewState(DumpScope scope, DrawingView record, object view, string where)
    {
        const string State = "drawing_view_state";

        record.ReferencedConfiguration = ReadText(
            scope, State, record.Id, $"read the configuration {where} shows",
            "ReferencedConfiguration", () => _reader.ReferencedConfiguration(view));
        record.IsModelOutOfDate = Read(
            scope, State, record.Id, $"read whether the model of {where} is out of date",
            "IsModelOutOfDate", () => _reader.IsModelOutOfDate(view));
        record.IsModelLoaded = Read(
            scope, State, record.Id, $"read whether the model of {where} is loaded",
            "IsModelLoaded", () => _reader.IsModelLoaded(view));
        record.ScaleDecimal = Read(
            scope, "drawing_view", record.Id, $"read the scale of {where}",
            "ScaleDecimal", () => _reader.ScaleDecimal(view));
        record.OrientationName = ReadText(
            scope, "drawing_view", record.Id, $"read the orientation of {where}",
            "GetOrientationName", () => _reader.OrientationName(view));
    }

    /// <summary>
    /// Why the attachments of this view's dimensions and annotations cannot be read, or null when
    /// they can (feature 011, the "Attachments" rule): they need the view's model, so a model that
    /// is not loaded - or not known to be - and a drawing in detailing mode attempt none.
    /// </summary>
    private static string? AttachmentsUnavailable(DrawingPass pass, DrawingView view)
    {
        if (pass.DetailingMode == true)
        {
            return "the drawing is in detailing mode, which loads no model";
        }

        if (view.IsModelLoaded == false)
        {
            return $"the model of view {view.Id} is not loaded";
        }

        return view.IsModelLoaded == null
            ? $"whether the model of view {view.Id} is loaded could not be read"
            : null;
    }

    /// <summary>One drawing_attachment gap naming the view whose attachments were not attempted.</summary>
    private static void NameSkippedAttachments(DumpScope scope, ViewContext context)
    {
        if (context.SkippedAttachments == 0)
        {
            return;
        }

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "drawing_attachment",
            context.View.Id,
            $"What {context.SkippedAttachments.ToString(CultureInfo.InvariantCulture)} dimensions and "
            + $"annotations of view {context.View.Id} are attached to was not read: "
            + $"{context.AttachmentsUnavailable}. Nothing was loaded to read it.",
            null);
    }

    /// <summary>One view as its dimensions and annotations need it while they are read.</summary>
    private sealed class ViewContext
    {
        public ViewContext(DrawingView view, object handle, string sheetName, string? attachmentsUnavailable)
        {
            View = view;
            Handle = handle;
            SheetName = sheetName;
            AttachmentsUnavailable = attachmentsUnavailable;
        }

        public DrawingView View { get; }

        public object Handle { get; }

        public string SheetName { get; }

        /// <summary>Why no attachment of this view is read, or null when they are.</summary>
        public string? AttachmentsUnavailable { get; }

        /// <summary>How many dimensions and annotations had their attachments not attempted.</summary>
        public int SkippedAttachments { get; set; }
    }

    /// <summary>
    /// The document a view references, resolved to a document of this package. A referenced
    /// model that is not loaded is a gap naming it, and every part- and assembly-scope check
    /// for that document is then unresolved coverage (FR-025). <b>Nothing is opened or
    /// loaded to close it.</b>
    ///
    /// A drawing read with a reviewed design (feature 011) ties the view to a document of the
    /// package by discovery's matching; a view that shows a document outside the review keeps its
    /// path, names no document and is one gap on the view per outside path, and that document is
    /// not asked for (contracts/open-drawings.md section 3).
    /// </summary>
    private void ReadReferencedDocument(
        DumpScope scope, DrawingPass pass, DrawingView record, object view, string where)
    {
        if (pass.ReviewedDocumentId != null
            && !string.IsNullOrWhiteSpace(record.ReferencedModelPath)
            && pass.ReviewedDocumentId(record.ReferencedModelPath!) == null)
        {
            NameOutside(scope, pass, record, record.ReferencedModelPath!);
            return;
        }

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

        if (pass.ReviewedDocumentId == null)
        {
            record.ReferencedDocumentId = scope.DocumentId(path!);
            return;
        }

        // The package's own id for the document, however this view spells its path.
        string? reviewed = pass.ReviewedDocumentId(path!);
        if (reviewed == null)
        {
            NameOutside(scope, pass, record, path!);
            return;
        }

        record.ReferencedDocumentId = reviewed;
    }

    /// <summary>
    /// A view of an attached or confirmed drawing that shows a document outside the review: one
    /// <c>drawing_referenced_document</c> gap on the first view that shows each such path.
    /// </summary>
    private static void NameOutside(DumpScope scope, DrawingPass pass, DrawingView record, string path)
    {
        if (!pass.NameOutside(path))
        {
            return;
        }

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "drawing_referenced_document",
            record.Id,
            $"references '{path}', which is not part of this review",
            null);
    }

    private void ReadDimensions(DumpScope scope, DrawingPass pass, ViewContext view, string where)
    {
        IReadOnlyList<object>? dimensions = scope.Gaps.TryStep(
            "dimension_override",
            view.View.Id,
            $"enumerate the display dimensions of {where}",
            () => _gate.Call("GetDisplayDimensions", () => _reader.DisplayDimensions(view.Handle)));

        foreach (object dimension in dimensions ?? new List<object>())
        {
            ReadDimension(scope, pass, view, dimension, where);
        }
    }

    /// <summary>
    /// One display dimension: its identity, its override flag, and its two values; then (feature
    /// 011) its text, precision and units, its tolerance and driven state, whether it is a
    /// reference dimension or a hole callout, and the model faces it is attached to.
    /// </summary>
    private void ReadDimension(
        DumpScope scope,
        DrawingPass pass,
        ViewContext view,
        object dimension,
        string where)
    {
        DisplayDimensionRecord record = pass.Traversal.AddDimension(view.View);

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

        ReadDimensionText(scope, record, dimension, where);
        ReadDimensionPrecision(scope, record, dimension, where);
        ReadModelDimension(scope, pass, view, record, dimension, unit, where);
        ReadReferenceAndHoleCallout(scope, record, dimension, where);
        record.AttachedFaces = ReadAttachments(
            scope, view, record.Id, $"dimension {record.Id} on {where}",
            () => _gate.Call("GetAnnotation", () => _reader.DimensionAnnotation(dimension)));

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "dimension_override",
            record.Id,
            $"read a persistent reference for dimension {record.Id} on {where}",
            () => _reader.PersistRef(pass.Document, dimension));

        record.PersistRef = reference?.Base64;
        record.PersistRefScope = reference?.ScopeDocumentId;

        // The tolerance cites the dimension as feature 010's cites its model dimension, by
        // persistent reference too once there is one.
        if (record.Tolerance != null)
        {
            record.Tolerance.Source.PersistRef = record.PersistRef;
        }
    }

    /// <summary>The four text parts, verbatim, the empty string kept; <c>dimension_text</c> gaps.</summary>
    private void ReadDimensionText(DumpScope scope, DisplayDimensionRecord record, object dimension, string where)
    {
        string? Part(int part, string name) => ReadText(
            scope, "dimension_text", record.Id, $"read the {name} text of dimension {record.Id} on {where}",
            "GetText", () => _reader.DimensionText(dimension, part));

        record.TextPrefix = Part(TextPrefix, "prefix");
        record.TextSuffix = Part(TextSuffix, "suffix");
        record.TextAbove = Part(TextAbove, "callout-above");
        record.TextBelow = Part(TextBelow, "callout-below");
    }

    /// <summary>The written precision and units, own or the document's; <c>dimension_precision</c> gaps.</summary>
    private void ReadDimensionPrecision(DumpScope scope, DisplayDimensionRecord record, object dimension, string where)
    {
        const string Precision = "dimension_precision";
        string of = $"dimension {record.Id} on {where}";

        record.PrecisionRaw = Read(
            scope, Precision, record.Id, $"read the precision of {of}",
            "GetPrimaryPrecision2", () => _reader.PrimaryPrecision(dimension));
        record.TolerancePrecisionRaw = Read(
            scope, Precision, record.Id, $"read the tolerance precision of {of}",
            "GetPrimaryTolPrecision2", () => _reader.PrimaryTolerancePrecision(dimension));
        record.UsesDocumentPrecision = Read(
            scope, Precision, record.Id, $"read whether {of} uses the document's precision",
            "GetUseDocPrecision", () => _reader.UsesDocumentPrecision(dimension));
        record.UnitsRaw = Read(
            scope, Precision, record.Id, $"read the units of {of}",
            "GetUnits", () => _reader.Units(dimension));
        record.UsesDocumentUnits = Read(
            scope, Precision, record.Id, $"read whether {of} uses the document's units",
            "GetUseDocUnits", () => _reader.UsesDocumentUnits(dimension));
    }

    /// <summary>
    /// The dimension's <c>IDimension</c>: its tolerance, through feature 010's reads and mapping
    /// (<see cref="DimensionTolerance.Read"/>, shared, not copied) - <c>dimension_tolerance</c>
    /// gaps - and its driven state, a <c>dimension_override</c> gap. A dimension whose unit is
    /// unknown reads no tolerance: its limits could only be written with a guessed unit.
    /// </summary>
    private void ReadModelDimension(
        DumpScope scope,
        DrawingPass pass,
        ViewContext view,
        DisplayDimensionRecord record,
        object dimension,
        string? unit,
        string where)
    {
        const string ToleranceGap = "dimension_tolerance";
        string of = $"dimension {record.Id} on {where}";

        object? model = null;
        if (!scope.Gaps.TryStep(
            ToleranceGap, record.Id, $"read the IDimension of {of}",
            () => { model = _gate.Call("GetDimension2", () => _reader.DimensionOf(dimension)); }))
        {
            return;
        }

        if (model == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                ToleranceGap,
                record.Id,
                $"Dimension {record.Id} on {where} gave no IDimension, so its tolerance and driven "
                + "state are unknown.",
                null);
            return;
        }

        if (unit == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                ToleranceGap,
                record.Id,
                $"Dimension {record.Id} on {where} names no unit, so its tolerance was not read: its "
                + "limits could only be recorded with a guessed unit.",
                null);
        }
        else
        {
            var source = new SourceRef
            {
                DocumentId = pass.Traversal.Record.DocumentId,
                Sheet = view.SheetName,
                View = view.View.Name,
                Annotation = record.Id,
            };

            scope.Gaps.TryStep(
                ToleranceGap,
                record.Id,
                $"read the tolerance of {of}",
                () => ApplyTolerance(scope, record, DimensionTolerance.Read(_gate, _reader, model!, source, unit), where));
        }

        record.DrivenStateRaw = Read(
            scope, "dimension_override", record.Id, $"read the driven state of {of}",
            "DrivenState", () => _reader.DrivenState(model!));
    }

    private static void ApplyTolerance(
        DumpScope scope, DisplayDimensionRecord record, DimensionToleranceReading reading, string where)
    {
        if (reading.Missing)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "dimension_tolerance",
                record.Id,
                $"Dimension {record.Id} on {where} gave no IDimensionTolerance, so its tolerance is unknown.",
                null);
            return;
        }

        record.Tolerance = reading.Tolerance;
        record.ToleranceTypeRaw = reading.TypeRaw;
        record.FitHoleClass = reading.HoleFit;
        record.FitShaftClass = reading.ShaftFit;

        if (reading.InvalidLimits.Count > 0)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "dimension_tolerance",
                record.Id,
                $"Dimension {record.Id} on {where} has a tolerance of type "
                + $"{reading.TypeRaw.ToString(CultureInfo.InvariantCulture)} but "
                + $"{string.Join(" and ", reading.InvalidLimits)} reported the value not valid for it, so "
                + "that limit is unknown.",
                null);
        }
    }

    /// <summary>
    /// Whether the dimension is a reference dimension (<c>dimension_override</c>) and a hole
    /// callout, with its variables when it is one (<c>dimension_text</c>).
    /// </summary>
    private void ReadReferenceAndHoleCallout(
        DumpScope scope, DisplayDimensionRecord record, object dimension, string where)
    {
        string of = $"dimension {record.Id} on {where}";

        record.IsReference = Read(
            scope, "dimension_override", record.Id, $"read whether {of} is a reference dimension",
            "IsReferenceDim", () => _reader.IsReferenceDimension(dimension));
        record.IsHoleCallout = Read(
            scope, "dimension_text", record.Id, $"read whether {of} is a hole callout",
            "IsHoleCallout", () => _reader.IsHoleCallout(dimension));

        if (record.IsHoleCallout != true)
        {
            return;
        }

        IReadOnlyList<string>? variables = null;
        bool answered = scope.Gaps.TryStep(
            "dimension_text", record.Id, $"read the hole callout variables of {of}",
            () => { variables = _reader.HoleCalloutVariables(dimension); });

        if (answered && variables == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "dimension_text",
                record.Id,
                $"Hole callout {record.Id} on {where} gave no variables, so what it calls out was not read.",
                null);
        }

        if (variables != null && variables.Count > 0)
        {
            record.HoleCalloutVariablesRaw = new List<string>(variables);
        }
    }

    /// <summary>
    /// The model faces one dimension or typed annotation is attached to (feature 011, the
    /// "Attachments" rule of contracts/native-evidence.md section 3, probe D6): each entity of
    /// <c>GetAttachedEntities3</c> mapped through the view to its model entity; a face kept, an
    /// edge its two adjacent faces <c>via: edge</c>; each face scoped to its own part document by
    /// that document's persistent reference, and deduplicated by reference. An entity that adds no
    /// row - another kind, a step that answers null or throws - is counted, and the record gets one
    /// <c>drawing_attachment</c> gap. Null when there is no row. Not attempted at all when the
    /// view's model is not available: the view's one gap says so.
    /// </summary>
    private List<AttachedFace>? ReadAttachments(
        DumpScope scope, ViewContext view, string entityId, string what, Func<object?> annotation)
    {
        if (view.AttachmentsUnavailable != null)
        {
            view.SkippedAttachments++;
            return null;
        }

        object? handle = null;
        if (!scope.Gaps.TryStep(
            "drawing_attachment", entityId, $"read the annotation of {what}", () => { handle = annotation(); }))
        {
            return null;
        }

        if (handle == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_attachment",
                entityId,
                $"The {what} gave no annotation, so what it is attached to was not read.",
                null);
            return null;
        }

        IReadOnlyList<object?>? entities = scope.Gaps.TryStep(
            "drawing_attachment", entityId, $"read the entities {what} is attached to",
            () => _gate.Call("GetAttachedEntities3", () => _reader.AttachedEntities(handle!)));
        if (entities == null || entities.Count == 0)
        {
            return null;
        }

        var faces = new List<AttachedFace>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var errors = new List<string>();
        int dropped = 0;

        foreach (object? entity in entities)
        {
            if (!TieEntity(view, entity, faces, seen, errors))
            {
                dropped++;
            }
        }

        if (dropped > 0)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_attachment",
                entityId,
                $"{dropped.ToString(CultureInfo.InvariantCulture)} of "
                + $"{entities.Count.ToString(CultureInfo.InvariantCulture)} attached entities could not be "
                + $"tied to a model face ({what}).",
                errors.Count == 0 ? null : string.Join("; ", errors));
        }

        return faces.Count == 0 ? null : faces;
    }

    /// <summary>
    /// One attached entity: whether it tied to at least one model face. A step that throws is kept
    /// in <paramref name="errors"/> and the entity counts as not tied; a guard refusal or an open
    /// circuit is not a property of the model and ends the dump, as everywhere else.
    /// </summary>
    private bool TieEntity(
        ViewContext view, object? entity, List<AttachedFace> faces, HashSet<string> seen, List<string> errors)
    {
        if (entity == null)
        {
            return false;
        }

        try
        {
            object? model = _gate.Call(
                "GetCorrespondingEntity", () => _reader.CorrespondingEntity(view.Handle, entity));
            if (model == null)
            {
                return false;
            }

            switch (_reader.EntityKind(model))
            {
                case AttachedEntityKind.Face:
                    return TieFace(view, model, AttachedVia.Face, faces, seen);
                case AttachedEntityKind.Edge:
                    bool tied = false;
                    foreach (object face in _gate.Call("GetTwoAdjacentFaces2", () => _reader.AdjacentFaces(model)))
                    {
                        tied |= TieFace(view, face, AttachedVia.Edge, faces, seen);
                    }

                    return tied;
                default:
                    return false;
            }
        }
        catch (CircuitOpenError)
        {
            throw;
        }
        catch (MutatingCallError)
        {
            throw;
        }
        catch (Exception ex)
        {
            errors.Add(GapCollector.Describe(ex));
            return false;
        }
    }

    /// <summary>One model face, scoped to its own part document; true when it has a reference.</summary>
    private bool TieFace(
        ViewContext view, object face, AttachedVia via, List<AttachedFace> faces, HashSet<string> seen)
    {
        object? document = _reader.FaceDocument(view.Handle, face);
        if (document == null)
        {
            return false;
        }

        ScopedPersistRef? reference = _reader.PersistRef(document, face);
        if (reference == null)
        {
            return false;
        }

        if (seen.Add(reference.ScopeDocumentId + "|" + reference.Base64))
        {
            faces.Add(new AttachedFace { PersistRef = reference.Base64, Scope = reference.ScopeDocumentId, Via = via });
        }

        return true;
    }

    private void ReadAnnotations(DumpScope scope, DrawingPass pass, ViewContext view, string where)
    {
        IReadOnlyList<object>? annotations = scope.Gaps.TryStep(
            "annotation_identity",
            view.View.Id,
            $"enumerate the annotations of {where}",
            () => _gate.Call("GetAnnotations", () => _reader.Annotations(view.Handle)));

        foreach (object annotation in annotations ?? new List<object>())
        {
            DrawingAnnotation record = pass.Traversal.AddAnnotation(view.View);

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
                () => _reader.PersistRef(pass.Document, annotation));

            record.PersistRef = reference?.Base64;
            record.PersistRefScope = reference?.ScopeDocumentId;

            ReadTypedAnnotation(scope, view, record, annotation, where);
        }
    }

    /// <summary>
    /// A geometric tolerance's frames and datum identifier, a datum tag's label, a surface finish
    /// symbol and its texts (feature 011), each through feature 010's reads where 010 has them
    /// (<see cref="IAnnotationSymbolReads"/>, <see cref="GtolFrames.Read"/>) and each a
    /// <c>drawing_symbol_read</c> gap on the annotation when it cannot be read; then the model faces
    /// it is attached to. An annotation of any other type gains nothing.
    /// </summary>
    private void ReadTypedAnnotation(
        DumpScope scope, ViewContext view, DrawingAnnotation record, object annotation, string where)
    {
        int? type = record.TypeRaw;
        if (type != GtolAnnotation && type != DatumTagAnnotation && type != SurfaceFinishAnnotation)
        {
            return;
        }

        const string Symbol = "drawing_symbol_read";
        string of = $"annotation {record.Id} on {where}";
        string kind = type == GtolAnnotation
            ? "geometric tolerance"
            : type == DatumTagAnnotation ? "datum tag" : "surface finish symbol";

        object? specific = null;
        bool answered = scope.Gaps.TryStep(
            Symbol, record.Id, $"read the {kind} of {of}",
            () => { specific = _gate.Call("GetSpecificAnnotation", () => _reader.Specific(annotation)); });

        if (answered && specific == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                Symbol,
                record.Id,
                $"Annotation {record.Id} on {where} is of type "
                + $"{type!.Value.ToString(CultureInfo.InvariantCulture)} and gave no {kind}, so what it says was not read.",
                null);
        }

        if (specific != null)
        {
            switch (type)
            {
                case GtolAnnotation:
                    ReadGtol(scope, record, specific, of);
                    break;
                case DatumTagAnnotation:
                    scope.Gaps.TryStep(
                        Symbol, record.Id, $"read the label of {of}",
                        () => { record.DatumLabel = HoleDumper.Blank(_gate.Call("GetLabel", () => _reader.DatumLabel(specific!))); });
                    break;
                default:
                    ReadSurfaceFinish(scope, record, specific, of);
                    break;
            }
        }

        record.AttachedFaces = ReadAttachments(scope, view, record.Id, of, () => annotation);
    }

    /// <summary>The frames, each asked both ways, and the datum identifier of a GTol.</summary>
    private void ReadGtol(DumpScope scope, DrawingAnnotation record, object gtol, string of)
    {
        const string Symbol = "drawing_symbol_read";

        int? count = Read(
            scope, Symbol, record.Id, $"read the frame count of {of}",
            "GetFrameCount", () => _reader.FrameCount(gtol));

        var frames = new List<GtolFrame>();
        for (int frame = 1; frame <= (count ?? 0); frame++)
        {
            var errors = new List<string>();
            GtolFrame? read = GtolFrames.Read(_gate, _reader, gtol, frame, errors);
            if (read != null)
            {
                frames.Add(read);
            }
            else if (errors.Count > 0)
            {
                scope.Gaps.Add(
                    GapKind.ToolError,
                    Symbol,
                    record.Id,
                    $"No call answered for frame {frame.ToString(CultureInfo.InvariantCulture)} of {of} "
                    + "(GetFrameValues, GetFrameSymbols3, GetFrame and GetSymbolXml), so the frame was not "
                    + "recorded.",
                    string.Join("; ", errors));
            }
        }

        record.GtolFrames = frames.Count == 0 ? null : frames;

        scope.Gaps.TryStep(
            Symbol, record.Id, $"read the datum identifier of {of}",
            () => { record.DatumIdentifierRaw = HoleDumper.Blank(_gate.Call("GetDatumIdentifier", () => _reader.DatumIdentifier(gtol))); });
    }

    /// <summary>A surface finish symbol and every text of it, verbatim.</summary>
    private void ReadSurfaceFinish(DumpScope scope, DrawingAnnotation record, object symbol, string of)
    {
        const string Symbol = "drawing_symbol_read";

        record.SurfaceFinishSymbolRaw = Read(
            scope, Symbol, record.Id, $"read the symbol of {of}",
            "GetSymbol", () => _reader.SurfaceFinishSymbol(symbol));

        List<string>? texts = scope.Gaps.TryStep(
            Symbol, record.Id, $"read the texts of {of}",
            () =>
            {
                int count = _gate.Call("GetTextCount", () => _reader.SurfaceFinishTextCount(symbol));
                var read = new List<string>(count);
                for (int index = 0; index < count; index++)
                {
                    int at = index;
                    read.Add(_gate.Call("GetTextAtIndex", () => _reader.SurfaceFinishText(symbol, at)) ?? string.Empty);
                }

                return read;
            });

        record.SurfaceFinishTextsRaw = texts == null || texts.Count == 0 ? null : texts;
    }

    private void ReadNotes(
        DumpScope scope, DrawingPass pass, DrawingView view, object handle, string where)
    {
        IReadOnlyList<object>? notes = scope.Gaps.TryStep(
            "note_text",
            view.Id,
            $"enumerate the notes of {where}",
            () => _gate.Call("GetNotes", () => _reader.Notes(handle)));

        foreach (object note in notes ?? new List<object>())
        {
            DrawingNote record = pass.Traversal.AddNote(view);

            record.Text = ReadText(
                scope, "note_text", record.Id,
                $"read the text of note {record.Id} on {where}",
                "GetText", () => _reader.NoteText(note));

            ScopedPersistRef? reference = scope.Gaps.TryStep(
                "note_text",
                record.Id,
                $"read a persistent reference for note {record.Id} on {where}",
                () => _reader.PersistRef(pass.Document, note));

            record.PersistRef = reference?.Base64;
            record.PersistRefScope = reference?.ScopeDocumentId;
        }
    }

    /// <summary>
    /// The tables of one view, recorded on the sheet: a revision table in
    /// <c>revision_tables</c> exactly as feature 006 records it, and every other type in
    /// <c>tables</c> (feature 011). The enumeration is per view because that is the only walk that
    /// finds every table: <c>ISheet.RevisionTable</c> is single-valued and would lose the second
    /// one.
    /// </summary>
    private void ReadTables(
        DumpScope scope,
        DrawingPass pass,
        DrawingSheetRecord sheet,
        DrawingView owner,
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
                ReadDrawingTable(scope, pass, sheet, owner, table, type!.Value, where);
                continue;
            }

            ReadRevisionTable(scope, pass, sheet, table, where);
        }
    }

    /// <summary>
    /// One table that is not a revision table (feature 011, contracts/native-evidence.md section
    /// 3, "Tables"): its title, its shape and every cell through the walk revision tables use, and
    /// for a bill of materials the documents each row stands for. A table two views return is
    /// recorded once - by persistent reference, else by the annotation's identity - under the first
    /// view that returned it. Every failed read is a <c>drawing_table_read</c> gap.
    /// </summary>
    private void ReadDrawingTable(
        DumpScope scope,
        DrawingPass pass,
        DrawingSheetRecord sheet,
        DrawingView owner,
        object table,
        int type,
        string where)
    {
        const string TableGap = "drawing_table_read";

        if (pass.TableHandleSeen(table))
        {
            return;
        }

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            TableGap,
            sheet.Id,
            $"read a persistent reference for a table of type {type.ToString(CultureInfo.InvariantCulture)} on {where}",
            () => _reader.PersistRef(pass.Document, table));

        if (pass.TableSeen(table, reference?.Base64))
        {
            return;
        }

        DrawingTable record = pass.Traversal.AddTable(sheet, owner);
        record.TableTypeRaw = type;
        record.PersistRef = reference?.Base64;
        record.PersistRefScope = reference?.ScopeDocumentId;

        record.Title = ReadText(
            scope, TableGap, record.Id, $"read the title of table {record.Id} on {where}",
            "Title", () => _reader.TableTitle(table));

        RevisionTableShape? shape = null;
        if (!scope.Gaps.TryStep(
            TableGap,
            record.Id,
            $"read the row and column counts of table {record.Id} on {where}",
            () => { shape = _reader.TableShape(table); }))
        {
            return;
        }

        record.RowCount = shape!.Value.RowCount;
        record.ColumnCount = shape!.Value.ColumnCount;
        record.Rows.AddRange(ReadCells(scope, TableGap, record.Id, table, shape!.Value, where));

        if (type == BillOfMaterialsTableType)
        {
            record.BomRows = ReadBomRows(scope, pass, record, table, where);
        }
    }

    /// <summary>
    /// The documents each row of a bill of materials stands for: every row is asked, since
    /// whether the header sits inside <c>RowCount</c> is PROBE-4's; a row that answers no path adds
    /// nothing. Each path is a package document when discovery's matching ties it to one, and is
    /// kept verbatim otherwise. Null when no row answered.
    /// </summary>
    private List<BomRow>? ReadBomRows(
        DumpScope scope, DrawingPass pass, DrawingTable record, object table, string where)
    {
        Func<string, string?> documentOf = pass.PackageDocumentId(scope);
        var rows = new List<BomRow>();

        for (int row = 0; row < (record.RowCount ?? 0); row++)
        {
            int r = row;
            IReadOnlyList<string>? paths = scope.Gaps.TryStep(
                "drawing_table_read",
                record.Id,
                $"read the models of row {r.ToString(CultureInfo.InvariantCulture)} of bill of materials {record.Id} on {where}",
                () => _gate.Call("GetModelPathNames", () => _reader.BomModelPaths(table, r)));

            var documents = new List<string>();
            var unresolved = new List<string>();
            foreach (string path in paths ?? Array.Empty<string>())
            {
                if (string.IsNullOrWhiteSpace(path))
                {
                    continue;
                }

                string? documentId = documentOf(path);
                if (documentId == null)
                {
                    unresolved.Add(path);
                }
                else if (!documents.Contains(documentId))
                {
                    documents.Add(documentId);
                }
            }

            if (documents.Count > 0 || unresolved.Count > 0)
            {
                rows.Add(new BomRow
                {
                    Index = r,
                    DocumentIds = documents.Count == 0 ? null : documents,
                    UnresolvedPaths = unresolved.Count == 0 ? null : unresolved,
                });
            }
        }

        return rows.Count == 0 ? null : rows;
    }

    /// <summary>
    /// Every cell of a table, row by row: the walk a revision table and every other table share
    /// (feature 011, extracted from feature 006's revision-table loop, unchanged). An empty cell is
    /// the empty string; a null is one that could not be read, with a gap of
    /// <paramref name="entityKind"/>. Which row is a header is not decided here.
    /// </summary>
    private List<RevisionTableRow> ReadCells(
        DumpScope scope, string entityKind, string recordId, object table, RevisionTableShape shape, string where)
    {
        var rows = new List<RevisionTableRow>(shape.RowCount);
        for (int row = 0; row < shape.RowCount; row++)
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

            for (int column = 0; column < shape.ColumnCount; column++)
            {
                int r = row;
                int c = column;

                string? text = null;
                bool read = scope.Gaps.TryStep(
                    entityKind,
                    recordId,
                    $"read cell [{r}, {c}] of table {recordId} on {where}",
                    () => { text = _gate.Call("Text", () => _reader.Cell(table, r, c)); });

                // An empty cell is the empty string; a null is one that could not be read.
                // Confusing the two would turn a real revision mismatch into a pass.
                cells.Cells.Add(read ? text : null);
            }

            rows.Add(cells);
        }

        return rows;
    }

    /// <summary>One revision table: both revision readings, and every cell.</summary>
    private void ReadRevisionTable(
        DumpScope scope,
        DrawingPass pass,
        DrawingSheetRecord sheet,
        object table,
        string where)
    {
        RevisionTable record = pass.Traversal.AddRevisionTable(sheet);

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
        record.Rows.AddRange(ReadCells(scope, "revision_table_read", record.Id, table, shape!.Value, where));

        ScopedPersistRef? reference = scope.Gaps.TryStep(
            "revision_table_read",
            record.Id,
            $"read a persistent reference for table {record.Id} on {where}",
            () => _reader.PersistRef(pass.Document, table));

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
    /// One gated read of a value (feature 011): null plus a gap of <paramref name="entityKind"/>
    /// when it threw. A value type has no null answer to record.
    /// </summary>
    private T? Read<T>(
        DumpScope scope, string entityKind, string entityId, string reason, string member, Func<T> read)
        where T : struct
    {
        T? value = null;
        scope.Gaps.TryStep(entityKind, entityId, reason, () => { value = _gate.Call(member, read); });
        return value;
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
