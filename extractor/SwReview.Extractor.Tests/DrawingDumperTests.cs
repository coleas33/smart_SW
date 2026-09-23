using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T059. The <c>drawing</c> phase (schema 1.4.0), over a fake <see cref="IDrawingReader"/> on
/// a machine with no SOLIDWORKS seat - the same split <see cref="CutListDumper"/> makes with
/// <see cref="ICutListReader"/>, and for the same reason: every decision the dumper makes
/// (what becomes a gap, what is recorded when a read fails, what is never called at all) is
/// then testable here rather than only on the pilot workstation.
///
/// One case per row of <c>contracts/ir-additions.md</c> section 3, plus the four properties
/// that matter more than the field mapping:
///
///   * <b>Nothing is activated.</b> A non-active sheet is read as it stands; if its views
///     come back empty that is a <c>drawing_sheet_views</c> gap naming the sheet (PROBE-7),
///     never a call to <c>ActivateSheet</c> - which is on the read-only denylist and could
///     not be made even by mistake (FR-044).
///   * <b>A number is never written with a guessed unit.</b> <c>dimension_type_raw</c>
///     decides whether a value is a length or an angle; a type that decides neither is a
///     null value plus a <c>dimension_unit</c> gap, so Python reports that dimension
///     unresolved. This is difference p - the macro multiplied by one thousand "blindly
///     assuming the system units are in meters".
///   * <b>An unreadable value is a gap, never an empty string.</b> An annotation with no
///     readable name is still a subject, identified by its id, its sheet and its view
///     (difference o); a note whose text could not be read leaves the export-control check
///     unresolved rather than passing it.
///   * <b>Revision tables are enumerated from the views</b>, filtered on the revision type,
///     because <c>ISheet.RevisionTable</c> is single-valued and would silently lose the
///     second table on a sheet. That property is still read, and a disagreement with the
///     walk is recorded rather than left invisible.
/// </summary>
public class DrawingDumperTests
{
    private const string DrawingPath = @"C:\vault\bracket-assy\bracket-assy.SLDDRW";
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";

    private readonly FakeDrawingReader _reader = new FakeDrawingReader();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    private DumpScope _scope = null!;

    public DrawingDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- the record and the active sheet (section 3.1) -----------------------------

    [Fact]
    public void Dump_RecordsOneNativeRecordKeyedByTheDrawingDocument()
    {
        _reader.AddSheet("Sheet1");

        DrawingRecord record = Assert.Single(Dump());

        Assert.Equal(_scope.DocumentId(DrawingPath), record.DocumentId);
        Assert.Equal(DrawingEvidenceSource.Native, record.Source);
    }

    [Fact]
    public void Dump_RecordsTheActiveSheetNameReadOnlyAndMarksThatSheet()
    {
        _reader.ActiveSheetName = "Sheet2";
        _reader.AddSheet("Sheet1");
        _reader.AddSheet("Sheet2");

        DrawingRecord record = Assert.Single(Dump());

        Assert.Equal("Sheet2", record.ActiveSheetName);
        Assert.Equal(new[] { false, true }, record.Sheets.Select(sheet => sheet.WasActive));

        // Read-only means read-only: the name is recorded so a coverage reason can say which
        // sheet was on screen while the others were read, and no sheet is made active to
        // read it.
        Assert.DoesNotContain("ActivateSheet", _observer.Members, StringComparer.OrdinalIgnoreCase);
    }

    [Fact]
    public void Dump_ThatCannotReadTheCurrentSheet_RecordsNullAndAGapAndStillReadsTheSheets()
    {
        _reader.ActiveSheetFailure = new InvalidOperationException("no current sheet");
        _reader.AddSheet("Sheet1");

        DrawingRecord record = Assert.Single(Dump());

        Assert.Null(record.ActiveSheetName);
        Assert.All(record.Sheets, sheet => Assert.False(sheet.WasActive));
        Assert.Contains(_scope.Gaps.Gaps, gap => gap.EntityKind == "drawing_sheet");
    }

    [Fact]
    public void Dump_OfADocumentThatIsNoDrawing_RecordsNothingAndSaysSo()
    {
        _reader.Drawing = null;

        Assert.Empty(Dump());

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_sheet", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(DrawingPath), gap.EntityId);
    }

    // ---- several drawings in one package (feature 011 T009, FR-016) -----------------

    private const string SecondDrawingPath = @"C:\vault\bracket-assy\housing.SLDDRW";

    [Fact]
    public void Dump_ReadsEveryDrawingOfTheScopeInOrder_WithIdsContinuingOneSequence()
    {
        ScriptOneOfEach(_reader.AddSheet("Sheet1"));
        FakeDrawing second = _reader.AddDrawing(SecondDrawingPath);
        ScriptOneOfEach(FakeDrawingReader.AddSheet(second, "Sheet1"));

        IReadOnlyList<DrawingRecord> records = Dump();

        Assert.Equal(
            new[] { _scope.DocumentId(DrawingPath), _scope.DocumentId(SecondDrawingPath) },
            records.Select(record => record.DocumentId));
        Assert.Equal(new[] { "dsh:0001", "dvw:0001", "ddm:0001", "dan:0001", "dnt:0001", "drv:0001" }, IdsOf(records[0]));
        Assert.Equal(new[] { "dsh:0002", "dvw:0002", "ddm:0002", "dan:0002", "dnt:0002", "drv:0002" }, IdsOf(records[1]));
    }

    [Fact]
    public void Dump_AsksTheReaderForEachDrawingByItsOwnDocument()
    {
        _reader.AddSheet("Sheet1");
        FakeDrawingReader.AddSheet(_reader.AddDrawing(SecondDrawingPath), "Sheet1");

        Dump();

        Assert.Equal(
            new[] { _reader.RootDocument, _reader.OtherDrawings[0].Document },
            _reader.DocumentsAsked);
    }

    [Fact]
    public void Dump_ScopesEveryPersistentReferenceToItsOwnDrawing()
    {
        _reader.AddSheet("Sheet1").PersistRef = "AAAA";
        FakeDrawingReader.AddSheet(_reader.AddDrawing(SecondDrawingPath), "Sheet1").PersistRef = "BBBB";

        IReadOnlyList<DrawingRecord> records = Dump();

        Assert.Equal(_scope.DocumentId(DrawingPath), records[0].Sheets[0].PersistRefScope);
        Assert.Equal(_scope.DocumentId(SecondDrawingPath), records[1].Sheets[0].PersistRefScope);
        Assert.Contains(_reader.OtherDrawings[0].Document, _reader.ReferenceDocumentsAsked);
        Assert.Contains(_reader.RootDocument, _reader.ReferenceDocumentsAsked);
    }

    [Fact]
    public void Dump_OfAScopeWithNoDrawing_RecordsNothingAndWritesNoGap()
    {
        _scope = NewScope();

        Assert.Empty(new DrawingDumper(_gate, _reader).Dump(_scope));
        Assert.Empty(_scope.Gaps.Gaps);
        Assert.Empty(_reader.DocumentsAsked);
    }

    [Fact]
    public void Dump_OfADrawingWithNoDocumentHandle_RecordsAGapAndStillReadsTheOthers()
    {
        _reader.ActiveSheetName = "Sheet1";
        _reader.AddSheet("Sheet1");
        _scope = NewScope();
        _scope.Drawings.Add(new ScopedDrawing(SecondDrawingPath, null));
        _scope.Drawings.Add(new ScopedDrawing(DrawingPath, _reader.RootDocument));

        DrawingRecord record = Assert.Single(new DrawingDumper(_gate, _reader).Dump(_scope));

        Assert.Equal(_scope.DocumentId(DrawingPath), record.DocumentId);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_sheet", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(SecondDrawingPath), gap.EntityId);
    }

    /// <summary>One view with a dimension, an annotation, a note and a revision table.</summary>
    private static void ScriptOneOfEach(FakeSheet sheet)
    {
        FakeView view = sheet.AddView("Drawing View1");
        view.AddDimension("D1@Sketch1").Type2 = 2;
        view.AddAnnotation("Note1", 6, false);
        view.AddNote("FICTIONAL NOTE");
        view.AddTable(3, "A").Rows = new[] { new[] { "A" } };
    }

    private static IReadOnlyList<string> IdsOf(DrawingRecord record)
    {
        DrawingSheetRecord sheet = Assert.Single(record.Sheets);
        DrawingView view = Assert.Single(sheet.Views);
        return new[]
        {
            sheet.Id,
            view.Id,
            Assert.Single(view.DisplayDimensions).Id,
            Assert.Single(view.Annotations).Id,
            Assert.Single(view.Notes).Id,
            Assert.Single(sheet.RevisionTables).Id,
        };
    }

    // ---- sheets (section 3.2) ------------------------------------------------------

    [Fact]
    public void Dump_RecordsSheetsInGetSheetNamesOrderWithTheirFormatAndIndex()
    {
        _reader.AddSheet("Sheet1").FormatName = "A3 - ISO";
        _reader.AddSheet("Detail").FormatName = "A2 - ISO";

        DrawingRecord record = Assert.Single(Dump());

        Assert.Equal(new[] { "Sheet1", "Detail" }, record.Sheets.Select(sheet => sheet.Name));
        Assert.Equal(new[] { 0, 1 }, record.Sheets.Select(sheet => sheet.Index));
        Assert.Equal(new[] { "dsh:0001", "dsh:0002" }, record.Sheets.Select(sheet => sheet.Id));
        Assert.Equal(
            new string?[] { "A3 - ISO", "A2 - ISO" },
            record.Sheets.Select(sheet => sheet.SheetFormatName));
        Assert.All(record.Sheets, sheet => Assert.Equal(DrawingEvidenceSource.Native, sheet.Source));
    }

    [Fact]
    public void Dump_SheetTheIndexerWillNotAnswerFor_LeavesTheSheetsAfterItAtTheirOwnPosition()
    {
        // `index` is the sheet's position in GetSheetNames(), from 0
        // (contracts/ir-additions.md section 3.2), and a listed name the Sheet[name] indexer
        // gives nothing for records no sheet. The third of three listed sheets is still sheet
        // 3 of the drawing: numbering the survivors 0 and 1 would make every finding on it
        // cite "sheet 2", in checks whose whole job is to name the sheet.
        _reader.AddSheet("Sheet1");
        _reader.AddSheet("Sheet2").NotFoundByName = true;
        _reader.AddSheet("Sheet3");

        DrawingRecord record = Assert.Single(Dump());

        Assert.Equal(new[] { "Sheet1", "Sheet3" }, record.Sheets.Select(sheet => sheet.Name));
        Assert.Equal(new[] { 0, 2 }, record.Sheets.Select(sheet => sheet.Index));

        // The ids stay allocation order: dsh:NNNN is the package's numbering, and the sheet
        // that recorded nothing consumed none of it.
        Assert.Equal(new[] { "dsh:0001", "dsh:0002" }, record.Sheets.Select(sheet => sheet.Id));

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_sheet");
        Assert.Contains("Sheet2", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_SheetWithNoReadableFormatName_IsNullPlusADrawingSheetGap()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        sheet.FormatName = null;

        DrawingSheetRecord record = Assert.Single(Assert.Single(Dump()).Sheets);

        Assert.Null(record.SheetFormatName);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_sheet");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Contains("Sheet1", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_SheetThatCouldNotBeEnumerated_IsAGapAndAnEmptySheetList()
    {
        _reader.SheetNamesFailure = new InvalidOperationException("GetSheetNames failed");

        DrawingRecord record = Assert.Single(Dump());

        Assert.Empty(record.Sheets);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_sheet");
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Fact]
    public void Dump_NonActiveSheetWhoseViewsComeBackEmpty_IsAGapNamingTheSheetAndNoActivation()
    {
        // PROBE-7: whether a non-active sheet's views come back populated is exactly what is
        // unsettled, and the answer this dump gives when they do not is an unresolved row -
        // never an activation, and never "the sheet has no views" (FR-024, FR-044).
        _reader.ActiveSheetName = "Sheet1";
        _reader.AddSheet("Sheet1").AddView("Drawing View1");
        _reader.AddSheet("Sheet2");

        DrawingRecord record = Assert.Single(Dump());

        Assert.Empty(record.Sheets[1].Views);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_sheet_views");
        Assert.Equal(record.Sheets[1].Id, gap.EntityId);
        Assert.Contains("Sheet2", gap.Reason, StringComparison.Ordinal);
        Assert.DoesNotContain("ActivateSheet", _observer.Members, StringComparer.OrdinalIgnoreCase);
    }

    [Fact]
    public void Dump_ActiveSheetWithNoViews_IsNoGap()
    {
        // A sheet that really has no views is not a loss, and a coverage row on it would be
        // noise an engineer learns to skip - which is how a real gap gets lost.
        _reader.ActiveSheetName = "Sheet1";
        _reader.AddSheet("Sheet1");

        Dump();

        Assert.DoesNotContain(_scope.Gaps.Gaps, gap => gap.EntityKind == "drawing_sheet_views");
    }

    [Fact]
    public void Dump_SheetWhoseViewEnumerationThrew_IsAGapNamingTheSheet()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        sheet.ViewsFailure = new InvalidOperationException("GetViews failed");

        DrawingRecord record = Assert.Single(Dump());

        Assert.Empty(record.Sheets[0].Views);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_sheet_views");
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains("Sheet1", gap.Reason, StringComparison.Ordinal);
    }

    // ---- views and their referenced documents (section 3.3) ------------------------

    [Fact]
    public void Dump_RecordsEveryViewWithItsNameAndItsTypeVerbatim()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");

        // The sheet-format pseudo-view is carried like any other view: it is the only place
        // the export-control statement is ever found, so a phase that skipped it would make
        // "the phrase appears nowhere" a silent pass.
        sheet.AddView("Sheet Format1").Type = 1;
        sheet.AddView("Drawing View1").Type = 4;

        DrawingSheetRecord record = Assert.Single(Assert.Single(Dump()).Sheets);

        Assert.Equal(
            new string?[] { "Sheet Format1", "Drawing View1" },
            record.Views.Select(view => view.Name));
        Assert.Equal(new int?[] { 1, 4 }, record.Views.Select(view => view.ViewTypeRaw));
        Assert.Equal(new[] { "dvw:0001", "dvw:0002" }, record.Views.Select(view => view.Id));
        Assert.All(record.Views, view => Assert.Equal(record.Id, view.SheetId));
    }

    [Fact]
    public void Dump_ViewWithNoReadableName_IsNullPlusADrawingViewGap()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView(null);

        DrawingView record = Assert.Single(Assert.Single(Assert.Single(Dump()).Sheets).Views);

        Assert.Null(record.Name);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_view");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.NotNull(view);
    }

    [Fact]
    public void Dump_ViewWhoseModelIsLoaded_ResolvesItToADocumentOfThisPackage()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.ReferencedModelPath = HousingPath;
        view.ReferencedDocument = new FakeModel(HousingPath);

        DrawingView record = Assert.Single(Assert.Single(Assert.Single(Dump()).Sheets).Views);

        Assert.Equal(_scope.DocumentId(HousingPath), record.ReferencedDocumentId);
        Assert.Equal(HousingPath, record.ReferencedModelPath);
        Assert.DoesNotContain(
            _scope.Gaps.Gaps, gap => gap.EntityKind == "drawing_referenced_document");
    }

    [Fact]
    public void Dump_ViewWhoseModelIsNotLoaded_RecordsThePathAndNamesItInAGap()
    {
        // GetReferencedModelName is recorded even though ReferencedDocument gave nothing:
        // the name is the whole point of the gap, because it is what tells the engineer
        // which model to open before extracting again (FR-025).
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.ReferencedModelPath = HousingPath;
        view.ReferencedDocument = null;

        DrawingView record = Assert.Single(Assert.Single(Assert.Single(Dump()).Sheets).Views);

        Assert.Null(record.ReferencedDocumentId);
        Assert.Equal(HousingPath, record.ReferencedModelPath);

        Gap gap = Assert.Single(
            _scope.Gaps.Gaps, g => g.EntityKind == "drawing_referenced_document");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Contains(HousingPath, gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_ViewThatReferencesNothing_IsNoGap()
    {
        // A detail or sheet-format view references no model and names none. That is not a
        // missing document.
        _reader.AddSheet("Sheet1").AddView("Sheet Format1").Type = 1;

        Dump();

        Assert.DoesNotContain(
            _scope.Gaps.Gaps, gap => gap.EntityKind == "drawing_referenced_document");
    }

    // ---- display dimensions (section 3.4) ------------------------------------------

    [Fact]
    public void Dump_RecordsAnOverriddenLengthDimensionWithItsUnit()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1")
            .AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.IsOverridden = true;
        dimension.OverrideValue = 0.05;
        dimension.Value = 0.0485;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal("D1@Sketch1", record.Name);
        Assert.Equal(2, record.DimensionTypeRaw);
        Assert.True(record.IsOverridden);
        Assert.Equal(0.05, record.OverrideValue!.Value);
        Assert.Equal("m", record.OverrideValue!.Unit);
        Assert.Equal(0.0485, record.Value!.Value);
        Assert.Equal("m", record.Value!.Unit);
    }

    [Fact]
    public void Dump_RecordsAnAngularDimensionAsAnAngle()
    {
        // Quantity carries a LengthUnit only, so an angular dimension cannot be represented
        // by one: dimension_type_raw is what decides which of the two the record carries.
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1")
            .AddDimension("A1@Sketch1");
        dimension.Type2 = 3;
        dimension.IsOverridden = true;
        dimension.OverrideValue = 0.7853981633974483;
        dimension.Value = 0.7853981633974483;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal("rad", record.OverrideValue!.Unit);
        Assert.Equal("rad", record.Value!.Unit);
    }

    [Fact]
    public void Dump_DimensionWhoseUnitCannotBeDetermined_IsNullPlusADimensionUnitGap()
    {
        // Difference p, and the one rule this record exists to enforce: a number whose unit
        // is unknown is not recorded. The check then reports that dimension unresolved
        // rather than rendering a length that may be an angle or a count.
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1")
            .AddDimension("D1@Sketch1");
        dimension.Type2 = 0;
        dimension.IsOverridden = true;
        dimension.OverrideValue = 0.05;
        dimension.Value = 0.05;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal(0, record.DimensionTypeRaw);
        Assert.True(record.IsOverridden);
        Assert.Null(record.OverrideValue);
        Assert.Null(record.Value);

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "dimension_unit");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
    }

    [Theory]
    [InlineData(1, "m")]
    [InlineData(2, "m")]
    [InlineData(3, "rad")]
    [InlineData(4, "m")]
    [InlineData(5, "m")]
    [InlineData(6, "m")]
    [InlineData(11, "m")]
    [InlineData(12, "m")]
    [InlineData(16, "rad")]
    [InlineData(0, null)]
    [InlineData(13, null)]
    [InlineData(99, null)]
    [InlineData(null, null)]
    public void UnitOf_MapsTheDimensionTypeToASystemUnitOrToNothingAtAll(int? typeRaw, string? unit)
    {
        // swDimensionType_e on the pilot interop (32.5.0.48): swAngularDimension = 3 and
        // swAngularOrdinateDimension = 16 are the angles; swDimensionTypeUnknown = 0 and
        // swScalarDimension = 13 decide no unit at all, and neither does a value this build
        // has never seen. What unit GetOverrideValue actually reports is PROBE-6; the
        // mapping records SOLIDWORKS' documented system units and nothing is converted.
        Assert.Equal(unit, DrawingDumper.UnitOf(typeRaw));
    }

    [Fact]
    public void Dump_DimensionWithNoReadableOverrideFlag_IsNullPlusADimensionOverrideGap()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1")
            .AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.OverrideFailure = new InvalidOperationException("GetOverride failed");

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.IsOverridden);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "dimension_override");
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_DimensionWithNoReadableName_IsStillARecordedSubject()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1")
            .AddDimension(null);
        dimension.Type2 = 2;
        dimension.IsOverridden = false;
        dimension.Value = 0.01;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Name);
        Assert.Equal("ddm:0001", record.Id);
        Assert.Contains(_scope.Gaps.Gaps, gap => gap.EntityKind == "dimension_override");
    }

    [Fact]
    public void Dump_DimensionThatIsNotOverridden_HasNoOverrideValueAndNoGapForIt()
    {
        // There is no override to read, so the null is silent: a coverage row on every
        // dimension of every drawing would bury the ones that really could not be read.
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1")
            .AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.IsOverridden = false;
        dimension.Value = 0.02;
        dimension.OverrideValue = 999.0;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.OverrideValue);
        Assert.Equal(0.02, record.Value!.Value);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    // ---- annotations (section 3.5) -------------------------------------------------

    [Fact]
    public void Dump_RecordsEveryAnnotationTypeWithItsNameTypeAndDanglingFlag()
    {
        // Every annotation type is in scope for the dangling check, which is why the type is
        // recorded verbatim and nothing is filtered here.
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.AddAnnotation("RC1", type: 6, dangling: false);
        view.AddAnnotation("DIMENSION2", type: 4, dangling: true);
        view.AddAnnotation("GTOL1", type: 5, dangling: false);

        IReadOnlyList<DrawingAnnotation> records = Single(Dump()).Annotations;

        Assert.Equal(new string?[] { "RC1", "DIMENSION2", "GTOL1" }, records.Select(a => a.Name));
        Assert.Equal(new int?[] { 6, 4, 5 }, records.Select(a => a.TypeRaw));
        Assert.Equal(new bool?[] { false, true, false }, records.Select(a => a.IsDangling));
        Assert.Equal(new[] { "dan:0001", "dan:0002", "dan:0003" }, records.Select(a => a.Id));
    }

    [Fact]
    public void Dump_AnnotationWithNoReadableName_IsStillASubjectWithItsOwnIdAndView()
    {
        // Difference o: the macro reported "Dangling annotation found." and named nothing, so
        // the engineer had to hunt. The id, the sheet and the view are enough to find it.
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.AddAnnotation(null, type: 6, dangling: true);

        DrawingView record = Single(Dump());
        DrawingAnnotation annotation = Assert.Single(record.Annotations);

        Assert.Null(annotation.Name);
        Assert.Equal("dan:0001", annotation.Id);
        Assert.Equal(record.Id, annotation.OwnerId);
        Assert.True(annotation.IsDangling);

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "annotation_identity");
        Assert.Equal(annotation.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_AnnotationWithNoReadableDanglingFlag_IsNullPlusAnAnnotationDanglingGap()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        FakeAnnotation annotation = view.AddAnnotation("RC1", type: 6, dangling: false);
        annotation.DanglingFailure = new InvalidOperationException("IsDangling failed");

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Assert.Null(record.IsDangling);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "annotation_dangling");
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_SheetFormatAnnotation_IsOwnedByTheTypeOneView()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        FakeView format = sheet.AddView("Sheet Format1");
        format.Type = 1;
        format.AddAnnotation("Note1", type: 6, dangling: false);

        DrawingView record = Assert.Single(Assert.Single(Dump()).Sheets[0].Views);

        Assert.Equal(1, record.ViewTypeRaw);
        Assert.Equal(record.Id, Assert.Single(record.Annotations).OwnerId);
    }

    // ---- notes (section 3.6) -------------------------------------------------------

    [Fact]
    public void Dump_RecordsEveryNoteWithItsTextAndItsView()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        view.Type = 1;
        view.AddNote("UNLESS OTHERWISE SPECIFIED");
        view.AddNote("BREAK ALL SHARP EDGES");

        DrawingView record = Single(Dump());

        Assert.Equal(
            new string?[] { "UNLESS OTHERWISE SPECIFIED", "BREAK ALL SHARP EDGES" },
            record.Notes.Select(note => note.Text));
        Assert.Equal(new[] { "dnt:0001", "dnt:0002" }, record.Notes.Select(note => note.Id));
        Assert.All(record.Notes, note => Assert.Equal(record.Id, note.OwnerId));
    }

    [Fact]
    public void Dump_NoteWithNoReadableText_IsNullPlusANoteTextGap()
    {
        // An unread note cannot be shown not to carry the export-control statement, so the
        // check is unresolved rather than passing - the defect there is a presence.
        _reader.AddSheet("Sheet1").AddView("Sheet Format1").AddNote(null);

        DrawingNote record = Assert.Single(Single(Dump()).Notes);

        Assert.Null(record.Text);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "note_text");
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_NoteWithEmptyText_IsAnEmptyStringAndNoGap()
    {
        // An empty note is a real answer: it carries no statement, and it is not unread.
        _reader.AddSheet("Sheet1").AddView("Sheet Format1").AddNote(string.Empty);

        Assert.Equal(string.Empty, Assert.Single(Single(Dump()).Notes).Text);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    // ---- revision tables (section 3.7) ---------------------------------------------

    [Fact]
    public void Dump_EnumeratesRevisionTablesFromTheViewsAndFiltersOnTheRevisionType()
    {
        // Filtered on swTableAnnotationType_e.swTableAnnotation_RevisionBlock (3): a bill of
        // materials on the same sheet is a table annotation too and is not a revision table.
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        view.AddTable(type: 2, currentRevision: "-");
        view.AddTable(type: 3, currentRevision: "B");

        DrawingSheetRecord sheet = Assert.Single(Dump()).Sheets[0];

        RevisionTable table = Assert.Single(sheet.RevisionTables);
        Assert.Equal("B", table.CurrentRevisionRaw);
        Assert.Equal(sheet.Id, table.SheetId);
        Assert.Equal("drv:0001", table.Id);
    }

    [Fact]
    public void Dump_RecordsTwoRevisionTablesOnOneSheet()
    {
        // The reason ISheet.RevisionTable is not the enumeration: it is single-valued, so the
        // second table would be silently invisible in the one check whose purpose is coverage.
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        view.AddTable(type: 3, currentRevision: "A");
        view.AddTable(type: 3, currentRevision: "B");

        Assert.Equal(
            new string?[] { "A", "B" },
            Assert.Single(Dump()).Sheets[0].RevisionTables.Select(t => t.CurrentRevisionRaw));
    }

    [Fact]
    public void Dump_SheetPropertyNamingATableTheWalkDidNotFind_IsAVisibleDisagreement()
    {
        // ISheet.RevisionTable is read as a cross-check, so a table the filtered walk missed
        // is a recorded disagreement rather than an absence nobody can see.
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        sheet.AddView("Sheet Format1");
        sheet.RevisionTableProperty = new FakeTable { Type = 3, CurrentRevision = "B" };

        DrawingSheetRecord record = Assert.Single(Dump()).Sheets[0];

        Assert.Empty(record.RevisionTables);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "revision_table_read");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Contains("Sheet1", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_RecordsTheCurrentRevisionVerbatimIncludingTheEmptyString()
    {
        // The macro's author recorded that this comes back empty under the vault and parsed
        // the table instead. Both readings are kept, and the check names both with their
        // source rather than letting the dumper choose (RK-4).
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        FakeTable table = view.AddTable(type: 3, currentRevision: string.Empty);
        table.Rows = new[]
        {
            new string?[] { "REV", "DESCRIPTION", "DATE" },
            new string?[] { "B", "Updated tolerance", "2026-05-02" },
        };

        RevisionTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].RevisionTables);

        Assert.Equal(string.Empty, record.CurrentRevisionRaw);
        Assert.Equal(2, record.RowCount);
        Assert.Equal(3, record.ColumnCount);
        Assert.Equal(new[] { 0, 1 }, record.Rows.Select(row => row.Index));
        Assert.Equal(new string?[] { "REV", "DESCRIPTION", "DATE" }, record.Rows[0].Cells);
        Assert.Equal(
            new string?[] { "B", "Updated tolerance", "2026-05-02" }, record.Rows[1].Cells);
    }

    [Fact]
    public void Dump_RecordsAnEmptyCellAsAnEmptyStringAndAnUnreadOneAsNull()
    {
        // An empty revision cell is a real mismatch; an unread one is unresolved coverage.
        // Confusing the two would turn a defect into a pass or a pass into a defect.
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        FakeTable table = view.AddTable(type: 3, currentRevision: "B");
        table.Rows = new[] { new string?[] { "B", string.Empty } };
        table.CellFailures.Add((0, 1));

        RevisionTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].RevisionTables);

        Assert.Equal(new string?[] { "B", null }, record.Rows[0].Cells);
        Assert.Contains(_scope.Gaps.Gaps, gap => gap.EntityKind == "revision_table_read");
    }

    [Fact]
    public void Dump_RevisionTableThatCannotBeCast_IsAGapAndNoRowsAtAll()
    {
        // IRevisionTableAnnotation declares no base interface in this interop, so reading
        // cells needs a runtime COM cast (PROBE-4). A failed cast is the table's rows lost,
        // and the check is then unresolved for it - never a table read as empty.
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        FakeTable table = view.AddTable(type: 3, currentRevision: "B");
        table.ShapeFailure = new InvalidCastException("not an ITableAnnotation");

        RevisionTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].RevisionTables);

        Assert.Equal("B", record.CurrentRevisionRaw);
        Assert.Null(record.RowCount);
        Assert.Null(record.ColumnCount);
        Assert.Empty(record.Rows);

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "revision_table_read");
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_ClassifiesNoRowAsAHeader()
    {
        // Which row is the revision row, and whether a row is the header, are profile
        // questions answered in Python from the profile's revision cell and its header row.
        // PROBE-4 has not settled whether the header is inside RowCount or outside it, so the
        // extractor records cells and classifies nothing rather than guessing.
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        FakeTable table = view.AddTable(type: 3, currentRevision: "B");
        table.Rows = new[]
        {
            new string?[] { "REV" },
            new string?[] { "B" },
        };

        RevisionTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].RevisionTables);

        Assert.All(record.Rows, row => Assert.Null(row.IsHeader));
    }

    // ---- identity (section 4) ------------------------------------------------------

    [Fact]
    public void Dump_RecordsAPersistentReferenceWhenSolidWorksGivesOne()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        sheet.PersistRef = "U2hlZXQx";
        FakeView view = sheet.AddView("Drawing View1");
        view.PersistRef = "Vmlldw==";

        DrawingSheetRecord record = Assert.Single(Dump()).Sheets[0];

        Assert.Equal("U2hlZXQx", record.PersistRef);
        Assert.Equal(_scope.DocumentId(DrawingPath), record.PersistRefScope);
        Assert.Equal("Vmlldw==", record.Views[0].PersistRef);
    }

    [Fact]
    public void Dump_RecordsANullReferenceWithoutAGap()
    {
        // PROBE-10 records which of the seven kinds SOLIDWORKS gives a reference for. A
        // refusal is not a failure: the null IS the statement FR-026 requires, and the page
        // renders no Show control for that subject rather than one that always fails.
        _reader.AddSheet("Sheet1").AddView("Drawing View1");

        DrawingSheetRecord record = Assert.Single(Dump()).Sheets[0];

        Assert.Null(record.PersistRef);
        Assert.Null(record.PersistRefScope);
        Assert.Null(record.Views[0].PersistRef);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    // ---- what the phase never does -------------------------------------------------

    [Fact]
    public void Dump_AsksTheGateAboutEveryReadAndAboutNothingThatWrites()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        FakeView view = sheet.AddView("Sheet Format1");
        view.Type = 1;
        view.AddDimension("D1@Sketch1").Type2 = 2;
        view.AddAnnotation("RC1", type: 6, dangling: false);
        view.AddNote("UNLESS OTHERWISE SPECIFIED");
        view.AddTable(type: 3, currentRevision: "B");

        Dump();

        Assert.NotEmpty(_observer.Members);
        Assert.Empty(_observer.Refusals);
        Assert.All(
            _observer.Members,
            member => ReadOnlyGuard.Assert(member));

        // Named rather than derived: these two are the release-checklist macro's one side
        // effect, and the drawing phase is written not to need them (research R2.7, R8).
        Assert.DoesNotContain("ActivateSheet", _observer.Members, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("ActivateView", _observer.Members, StringComparer.OrdinalIgnoreCase);
    }

    [Fact]
    public void Dump_LeavesTheDimensionValueReadToGateItsOwnTwoCalls()
    {
        // IDrawingReader.DimensionValue spans two interop calls - IDisplayDimension
        // .GetDimension2 and IDimension.GetSystemValue3 - so, like DimensionName, it gates
        // both of them inside the SOLIDWORKS implementation, where the read-only guard and
        // the SC-010 audit see each one under its own member name. Gating it here as well
        // would report GetSystemValue3 twice for a single read.
        _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1").Type2 = 2;

        Dump();

        // The dimension really was read: the members that DO map to one call are still named
        // by the dumper, so this is not an absence a skipped dimension could produce.
        Assert.Contains("GetOverride", _observer.Members, StringComparer.Ordinal);
        Assert.DoesNotContain("GetSystemValue3", _observer.Members, StringComparer.Ordinal);
    }

    [Fact]
    public void Dump_ReadsNoCustomPropertyOfTheDrawing()
    {
        // The drawing's own custom properties are Document.custom_properties, read by the
        // document phase now that a drawing document enters documents[] (T062). Reading them
        // here as well would give one drawing two readings that could disagree.
        _reader.AddSheet("Sheet1").AddView("Drawing View1");

        Dump();

        Assert.DoesNotContain(
            _observer.Members, member => member.Contains("CustomProperty") || member == "GetAll3");
    }

    [Fact]
    public void Dump_OpensNothingAndResolvesNothing()
    {
        _reader.AddSheet("Sheet1").AddView("Drawing View1").ReferencedModelPath = HousingPath;

        Dump();

        Assert.DoesNotContain("OpenDoc6", _observer.Members, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("LoadFile4", _observer.Members, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain(
            "ResolveAllLightWeightComponents", _observer.Members, StringComparer.OrdinalIgnoreCase);
    }

    // ---- helpers -------------------------------------------------------------------

    private IReadOnlyList<DrawingRecord> Dump()
    {
        _scope = NewScope();
        _scope.Drawings.Add(new ScopedDrawing(DrawingPath, _reader.RootDocument));
        foreach ((string path, object document) in _reader.OtherDrawings)
        {
            _scope.Drawings.Add(new ScopedDrawing(path, document));
        }

        return new DrawingDumper(_gate, _reader).Dump(_scope);
    }

    /// <summary>The one view of a single-sheet, single-view fake.</summary>
    private static DrawingView Single(IReadOnlyList<DrawingRecord> records) =>
        Assert.Single(Assert.Single(Assert.Single(records).Sheets).Views);

    private static DumpScope NewScope()
    {
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = DrawingPath,
            RootDocumentKind = DocumentKind.Drawing,
            DesignName = "bracket-assy",
            ActiveConfiguration = "Default",
        };

        var node = new ComponentNode
        {
            Key = "housing",
            ParentKey = null,
            Name = "housing",
            DocumentPath = HousingPath,
            DocumentKind = DocumentKind.Part,
            ReferencedConfiguration = "Default",
            Transform = Transform.Identity(),
            Suppression = SuppressionState.Resolved,
            PersistRefScopePath = HousingPath,
            Handle = new object(),
        };

        tree.Nodes.Add(node);

        var scope = new DumpScope(
            new GapCollector(), new DumpOptions { OutputDirectory = "out" }, tree);
        scope.AddComponent(new IdAllocator("cmp").Next(), scope.DocumentId(HousingPath), node);
        return scope;
    }

    // ---- the fake drawing ----------------------------------------------------------

    private sealed class FakeModel
    {
        public FakeModel(string path)
        {
            Path = path;
        }

        public string Path { get; }
    }

    private sealed class FakeTable
    {
        public int Type { get; set; } = 3;

        public string? CurrentRevision { get; set; }

        public Exception? CurrentRevisionFailure { get; set; }

        public string?[][] Rows { get; set; } = new string?[0][];

        /// <summary>The runtime COM cast to ITableAnnotation failing (PROBE-4).</summary>
        public Exception? ShapeFailure { get; set; }

        /// <summary>Cells whose Text[row, col] read throws.</summary>
        public List<(int Row, int Column)> CellFailures { get; } = new List<(int, int)>();
    }

    private sealed class FakeNote
    {
        public string? Text { get; set; }
    }

    private sealed class FakeAnnotation
    {
        public string? Name { get; set; }

        public int Type { get; set; }

        public bool Dangling { get; set; }

        public Exception? DanglingFailure { get; set; }
    }

    private sealed class FakeDimension
    {
        public string? Name { get; set; }

        public int Type2 { get; set; }

        public bool IsOverridden { get; set; }

        public double OverrideValue { get; set; }

        public double Value { get; set; }

        public Exception? OverrideFailure { get; set; }
    }

    private sealed class FakeView
    {
        public string? Name { get; set; }

        public int Type { get; set; }

        public string? ReferencedModelPath { get; set; }

        public FakeModel? ReferencedDocument { get; set; }

        public string? PersistRef { get; set; }

        public List<FakeDimension> Dimensions { get; } = new List<FakeDimension>();

        public List<FakeAnnotation> Annotations { get; } = new List<FakeAnnotation>();

        public List<FakeNote> Notes { get; } = new List<FakeNote>();

        public List<FakeTable> Tables { get; } = new List<FakeTable>();

        public FakeDimension AddDimension(string? name)
        {
            var dimension = new FakeDimension { Name = name };
            Dimensions.Add(dimension);
            return dimension;
        }

        public FakeAnnotation AddAnnotation(string? name, int type, bool dangling)
        {
            var annotation = new FakeAnnotation { Name = name, Type = type, Dangling = dangling };
            Annotations.Add(annotation);
            return annotation;
        }

        public FakeNote AddNote(string? text)
        {
            var note = new FakeNote { Text = text };
            Notes.Add(note);
            return note;
        }

        public FakeTable AddTable(int type, string? currentRevision)
        {
            var table = new FakeTable { Type = type, CurrentRevision = currentRevision };
            Tables.Add(table);
            return table;
        }
    }

    private sealed class FakeSheet
    {
        public string Name { get; set; } = string.Empty;

        public string? FormatName { get; set; } = "A3 - ISO";

        public string? PersistRef { get; set; }

        /// <summary>
        /// A sheet <c>GetSheetNames()</c> lists and the <c>Sheet[name]</c> indexer will not
        /// answer for. It is the one way a listed sheet records nothing, so it is what pins
        /// that the sheets after it keep their own positions.
        /// </summary>
        public bool NotFoundByName { get; set; }

        public Exception? ViewsFailure { get; set; }

        public FakeTable? RevisionTableProperty { get; set; }

        public List<FakeView> Views { get; } = new List<FakeView>();

        public FakeView AddView(string? name)
        {
            var view = new FakeView { Name = name, Type = 4 };
            Views.Add(view);
            return view;
        }
    }

    /// <summary>
    /// A scripted drawing, with a switch for every read the dumper is expected to turn into a
    /// gap. Handles are the fake objects themselves, which is all the dumper ever treats them
    /// as.
    /// </summary>
    /// <summary>
    /// One scripted drawing document: its sheets and the reads that can fail. It is also the
    /// handle <see cref="IDrawingReader.Drawing"/> answers for its document, which is all the
    /// dumper ever treats a handle as.
    /// </summary>
    private sealed class FakeDrawing
    {
        public FakeDrawing(string path)
        {
            Path = path;
        }

        public string Path { get; }

        public List<FakeSheet> Sheets { get; } = new List<FakeSheet>();

        public string? ActiveSheetName { get; set; }

        public Exception? ActiveSheetFailure { get; set; }

        public Exception? SheetNamesFailure { get; set; }
    }

    private sealed class FakeDrawingReader : IDrawingReader
    {
        private readonly FakeDrawing _root = new FakeDrawing(DrawingPath);
        private readonly Dictionary<object, FakeDrawing> _byDocument = new Dictionary<object, FakeDrawing>();
        private readonly List<(string Path, object Document)> _others = new List<(string, object)>();

        public FakeDrawingReader()
        {
            _byDocument[RootDocument] = _root;
            Drawing = _root;
        }

        /// <summary>The root drawing's document handle, which the scope names it by.</summary>
        public object RootDocument { get; } = new object();

        /// <summary>
        /// What <see cref="IDrawingReader.Drawing"/> answers for the root document; null makes
        /// the root document one that is not a drawing.
        /// </summary>
        public object? Drawing { get; set; }

        /// <summary>The drawings added after the root, in the order the scope reads them.</summary>
        public IReadOnlyList<(string Path, object Document)> OtherDrawings => _others;

        /// <summary>Every document the dumper asked to read as a drawing, in order.</summary>
        public List<object> DocumentsAsked { get; } = new List<object>();

        /// <summary>Every document a persistent reference was asked of, in order.</summary>
        public List<object> ReferenceDocumentsAsked { get; } = new List<object>();

        public string? ActiveSheetName
        {
            get => _root.ActiveSheetName;
            set => _root.ActiveSheetName = value;
        }

        public Exception? ActiveSheetFailure
        {
            get => _root.ActiveSheetFailure;
            set => _root.ActiveSheetFailure = value;
        }

        public Exception? SheetNamesFailure
        {
            get => _root.SheetNamesFailure;
            set => _root.SheetNamesFailure = value;
        }

        public FakeSheet AddSheet(string name) => AddSheet(_root, name);

        /// <summary>A second drawing document, read after the root one.</summary>
        public FakeDrawing AddDrawing(string path)
        {
            var drawing = new FakeDrawing(path);
            var document = new object();
            _byDocument[document] = drawing;
            _others.Add((path, document));
            return drawing;
        }

        public static FakeSheet AddSheet(FakeDrawing drawing, string name)
        {
            var sheet = new FakeSheet { Name = name };
            drawing.Sheets.Add(sheet);
            return sheet;
        }

        object? IDrawingReader.Drawing(object document)
        {
            DocumentsAsked.Add(document);
            return ReferenceEquals(document, RootDocument) ? Drawing : _byDocument[document];
        }

        string? IDrawingReader.ActiveSheetName(object drawing)
        {
            FakeDrawing found = Of(drawing);
            return found.ActiveSheetFailure != null ? throw found.ActiveSheetFailure : found.ActiveSheetName;
        }

        IReadOnlyList<string> IDrawingReader.SheetNames(object drawing)
        {
            FakeDrawing found = Of(drawing);
            return found.SheetNamesFailure != null
                ? throw found.SheetNamesFailure
                : found.Sheets.Select(sheet => sheet.Name).ToList();
        }

        object? IDrawingReader.Sheet(object drawing, string name) =>
            Of(drawing).Sheets.FirstOrDefault(sheet => sheet.Name == name && !sheet.NotFoundByName);

        string? IDrawingReader.SheetName(object sheet) => Sheet(sheet).Name;

        string? IDrawingReader.SheetFormatName(object sheet) => Sheet(sheet).FormatName;

        IReadOnlyList<object> IDrawingReader.Views(object sheet)
        {
            FakeSheet found = Sheet(sheet);
            return found.ViewsFailure != null
                ? throw found.ViewsFailure
                : found.Views.Cast<object>().ToList();
        }

        object? IDrawingReader.SheetRevisionTable(object sheet) => Sheet(sheet).RevisionTableProperty;

        string? IDrawingReader.ViewName(object view) => View(view).Name;

        int IDrawingReader.ViewType(object view) => View(view).Type;

        string? IDrawingReader.ReferencedModelPath(object view) => View(view).ReferencedModelPath;

        object? IDrawingReader.ReferencedDocument(object view) => View(view).ReferencedDocument;

        string? IDrawingReader.DocumentPath(object document) => ((FakeModel)document).Path;

        IReadOnlyList<object> IDrawingReader.DisplayDimensions(object view) =>
            View(view).Dimensions.Cast<object>().ToList();

        IReadOnlyList<object> IDrawingReader.Annotations(object view) =>
            View(view).Annotations.Cast<object>().ToList();

        IReadOnlyList<object> IDrawingReader.Notes(object view) =>
            View(view).Notes.Cast<object>().ToList();

        IReadOnlyList<object> IDrawingReader.TableAnnotations(object view) =>
            View(view).Tables.Cast<object>().ToList();

        int IDrawingReader.TableAnnotationType(object table) => Table(table).Type;

        string? IDrawingReader.DimensionName(object dimension) => Dimension(dimension).Name;

        int IDrawingReader.DimensionType(object dimension) => Dimension(dimension).Type2;

        bool IDrawingReader.IsOverridden(object dimension)
        {
            FakeDimension found = Dimension(dimension);
            return found.OverrideFailure != null ? throw found.OverrideFailure : found.IsOverridden;
        }

        double IDrawingReader.OverrideValue(object dimension) => Dimension(dimension).OverrideValue;

        double IDrawingReader.DimensionValue(object dimension) => Dimension(dimension).Value;

        string? IDrawingReader.AnnotationName(object annotation) => Annotation(annotation).Name;

        int IDrawingReader.AnnotationType(object annotation) => Annotation(annotation).Type;

        bool IDrawingReader.IsDangling(object annotation)
        {
            FakeAnnotation found = Annotation(annotation);
            return found.DanglingFailure != null ? throw found.DanglingFailure : found.Dangling;
        }

        string? IDrawingReader.NoteText(object note) => ((FakeNote)note).Text;

        string? IDrawingReader.CurrentRevision(object table)
        {
            FakeTable found = Table(table);
            return found.CurrentRevisionFailure != null
                ? throw found.CurrentRevisionFailure
                : found.CurrentRevision;
        }

        RevisionTableShape IDrawingReader.TableShape(object table)
        {
            FakeTable found = Table(table);
            if (found.ShapeFailure != null)
            {
                throw found.ShapeFailure;
            }

            return new RevisionTableShape(
                found.Rows.Length, found.Rows.Length == 0 ? 0 : found.Rows[0].Length);
        }

        string? IDrawingReader.Cell(object table, int row, int column)
        {
            FakeTable found = Table(table);
            return found.CellFailures.Contains((row, column))
                ? throw new InvalidOperationException($"cell {row},{column} could not be read")
                : found.Rows[row][column];
        }

        ScopedPersistRef? IDrawingReader.PersistRef(object document, object entity)
        {
            ReferenceDocumentsAsked.Add(document);
            string? reference = entity is FakeSheet sheet
                ? sheet.PersistRef
                : entity is FakeView view ? view.PersistRef : null;

            // Scoped to the document it was asked of, exactly as PersistRefService scopes a
            // reference to the extension that produced it.
            string path = _byDocument[document].Path;
            return reference == null
                ? null
                : new ScopedPersistRef(reference, DocumentIds.For(path), path);
        }

        private static FakeDrawing Of(object drawing) => (FakeDrawing)drawing;

        private static FakeTable Table(object table) => (FakeTable)table;

        private static FakeSheet Sheet(object sheet) => (FakeSheet)sheet;

        private static FakeView View(object view) => (FakeView)view;

        private static FakeDimension Dimension(object dimension) => (FakeDimension)dimension;

        private static FakeAnnotation Annotation(object annotation) => (FakeAnnotation)annotation;
    }
}
