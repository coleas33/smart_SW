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

    // ---- an attached drawing's views (feature 011 T020, open-drawings.md section 3) ------
    //
    // A drawing a review attached is read with the rule that ties a view's path to a document
    // of the package (ScopedDrawing.ReviewedDocumentId). A view that shows a document outside
    // the review keeps its path, names no document, and is one gap on the view - once per
    // outside path per drawing - exactly as the assembly-drawings fixture records it. A drawing
    // root has no such rule and is read as feature 006 reads it.

    private const string OutsidePath = @"C:\vault\other\unrelated.SLDPRT";

    [Fact]
    public void Dump_AnAttachedDrawingsViewOfAnOutsideDocument_KeepsItsPathNamesNoDocumentAndIsOneGapOnTheView()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.ReferencedModelPath = OutsidePath;
        view.ReferencedDocument = new FakeModel(OutsidePath);

        DrawingView record = Single(DumpAttached());

        Assert.Null(record.ReferencedDocumentId);
        Assert.Equal(OutsidePath, record.ReferencedModelPath);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_referenced_document", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Equal("references '" + OutsidePath + "', which is not part of this review", gap.Reason);

        // The outside model is not read: its document is not asked for.
        Assert.DoesNotContain("ReferencedDocument", _observer.Members, StringComparer.Ordinal);
    }

    [Fact]
    public void Dump_TwoViewsOfOneOutsideDocument_AreOneGapOnTheFirstView()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        FakeView first = sheet.AddView("Drawing View1");
        first.ReferencedModelPath = OutsidePath;
        FakeView second = sheet.AddView("Drawing View2");
        second.ReferencedModelPath = OutsidePath.ToUpperInvariant();

        DrawingRecord record = Assert.Single(DumpAttached());

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal(record.Sheets[0].Views[0].Id, gap.EntityId);
        Assert.All(record.Sheets[0].Views, view => Assert.Null(view.ReferencedDocumentId));
    }

    [Fact]
    public void Dump_AnAttachedDrawingsViewOfAReviewedDocument_NamesThePackagesDocumentHoweverThePathIsSpelled()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        const string Spelled = @"C:\VAULT\bracket-assy\sub\..\HOUSING.sldprt";
        view.ReferencedModelPath = Spelled;
        view.ReferencedDocument = new FakeModel(Spelled);

        DrawingView record = Single(DumpAttached());

        Assert.Equal(DocumentIds.For(HousingPath), record.ReferencedDocumentId);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_AnAttachedDrawingsViewOfAReviewedDocumentThatIsNotLoaded_KeepsTheNotLoadedGap()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.ReferencedModelPath = HousingPath;
        view.ReferencedDocument = null;

        DrawingView record = Single(DumpAttached());

        Assert.Null(record.ReferencedDocumentId);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_referenced_document", gap.EntityKind);
        Assert.Contains("is not loaded", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AnAttachedDrawingsViewThatShowsNothing_RaisesNoGap()
    {
        _reader.AddSheet("Sheet1").AddView("Sheet format view").ReferencedModelPath = "";

        DrawingView record = Single(DumpAttached());

        Assert.Null(record.ReferencedDocumentId);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_ADrawingRootsViewOfAModelOutsideItsForest_IsReadAsFeature006ReadsIt()
    {
        // No reviewed-document rule on a drawing root: an unloaded model is "not loaded", never
        // "not part of this review".
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.ReferencedModelPath = OutsidePath;
        view.ReferencedDocument = null;

        Single(Dump());

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Contains("is not loaded", gap.Reason, StringComparison.Ordinal);
    }

    /// <summary>The root fake drawing, read as a drawing a review attached to a design of the housing.</summary>
    private IReadOnlyList<DrawingRecord> DumpAttached()
    {
        _scope = NewScope();
        _scope.Drawings.Add(new ScopedDrawing(
            DrawingPath,
            _reader.RootDocument,
            OpenDrawingDiscovery.DocumentResolver(new[] { HousingPath })));
        return new DrawingDumper(_gate, _reader).Dump(_scope);
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

    // ---- native evidence at 1.6.0 (feature 011 T026, contracts/native-evidence.md section 3) ----
    //
    // Every new read answering, throwing (its gap kind) and, for a reference read, answering
    // null. The fake answers every one of them by default, so the feature 006 tests above keep
    // their gap counts: a gap here is always one a test asked for.

    /// <summary>A lone sheet that is the active one, so an empty view list is no gap of its own.</summary>
    private FakeSheet ActiveSheet()
    {
        _reader.ActiveSheetName = "Sheet1";
        return _reader.AddSheet("Sheet1");
    }

    // -- the drawing --

    [Fact]
    public void Dump_RecordsTheDrawingsSettings()
    {
        ActiveSheet();
        FakeDrawing drawing = _reader.Root;
        drawing.IntegerPreferences[47] = 3;
        drawing.IntegerPreferences[24] = 2;
        drawing.IntegerPreferences[49] = 4;
        drawing.IntegerPreferences[25] = 3;
        drawing.DraftingStandard = "FICTIONAL-STANDARD";

        DrawingRecord record = Assert.Single(Dump());

        Assert.False(record.IsDetailingMode);
        Assert.Equal(3, record.LengthUnitRaw);
        Assert.Equal(2, record.DimensionPrecisionRaw);
        Assert.Equal(4, record.UnitsDecimalPlacesRaw);
        Assert.Equal(3, record.TolerancePrecisionRaw);
        Assert.Equal("FICTIONAL-STANDARD", record.DraftingStandardName);
        Assert.Empty(_scope.Gaps.Gaps);

        // The enumerators of contracts/native-evidence.md section 3, each asked with option 0,
        // of the drawing's own document.
        Assert.Equal(new[] { 47, 24, 49, 25 }, drawing.IntegerPreferencesAsked);
        Assert.Equal(new[] { 65 }, drawing.StringPreferencesAsked);
        Assert.Contains("IsDetailingMode", _observer.Members, StringComparer.Ordinal);
        Assert.Contains("GetUserPreferenceInteger", _observer.Members, StringComparer.Ordinal);
        Assert.Contains("GetUserPreferenceString", _observer.Members, StringComparer.Ordinal);
    }

    [Fact]
    public void Dump_ADrawingInDetailingMode_SaysSo()
    {
        ActiveSheet();
        _reader.Root.IsDetailingMode = true;

        Assert.True(Assert.Single(Dump()).IsDetailingMode);
    }

    [Theory]
    [InlineData("IsDetailingMode")]
    [InlineData("47")]
    [InlineData("24")]
    [InlineData("49")]
    [InlineData("25")]
    [InlineData("65")]
    public void Dump_ADrawingSettingThatThrows_IsNullPlusADrawingDocumentSettingsGapAndTheRestAreRead(string setting)
    {
        ActiveSheet();
        _reader.Root.Throwing.Add(setting);

        DrawingRecord record = Assert.Single(Dump());

        var read = new Dictionary<string, object?>
        {
            ["IsDetailingMode"] = record.IsDetailingMode,
            ["47"] = record.LengthUnitRaw,
            ["24"] = record.DimensionPrecisionRaw,
            ["49"] = record.UnitsDecimalPlacesRaw,
            ["25"] = record.TolerancePrecisionRaw,
            ["65"] = record.DraftingStandardName,
        };
        Assert.Null(read[setting]);
        Assert.All(read.Where(pair => pair.Key != setting), pair => Assert.NotNull(pair.Value));

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_document_settings", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(DrawingPath), gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Fact]
    public void Dump_ADraftingStandardThatAnswersNull_IsNullPlusAGap()
    {
        ActiveSheet();
        _reader.Root.DraftingStandard = null;

        Assert.Null(Assert.Single(Dump()).DraftingStandardName);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_document_settings", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
    }

    // -- the sheet --

    [Fact]
    public void Dump_RecordsTheSheetsTemplateScaleAndProjection()
    {
        FakeSheet sheet = ActiveSheet();
        sheet.TemplateName = @"C:\Fictional\Formats\FICTIONAL-FORMAT-A.slddrt";
        sheet.Properties = new[] { 12d, 0d, 1d, 2d, 1d, 0.42, 0.297 };

        DrawingSheetRecord record = Assert.Single(Dump()).Sheets[0];

        Assert.Equal(@"C:\Fictional\Formats\FICTIONAL-FORMAT-A.slddrt", record.SheetFormatPath);
        Assert.Equal(1d, record.ScaleNumerator);
        Assert.Equal(2d, record.ScaleDenominator);
        Assert.True(record.FirstAngle);
        Assert.Empty(_scope.Gaps.Gaps);
        Assert.Contains("GetTemplateName", _observer.Members, StringComparer.Ordinal);
        Assert.Contains("GetProperties2", _observer.Members, StringComparer.Ordinal);
    }

    [Fact]
    public void Dump_ASheetInThirdAngleProjection_IsNotFirstAngle()
    {
        ActiveSheet().Properties = new[] { 12d, 0d, 1d, 1d, 0d, 0.42, 0.297 };

        Assert.False(Assert.Single(Dump()).Sheets[0].FirstAngle);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void Dump_ATemplateNameThatThrowsOrAnswersNull_IsNullPlusADrawingSheetGap(bool throws)
    {
        FakeSheet sheet = ActiveSheet();
        if (throws)
        {
            sheet.Throwing.Add("GetTemplateName");
        }
        else
        {
            sheet.TemplateName = null;
        }

        DrawingSheetRecord record = Assert.Single(Dump()).Sheets[0];

        Assert.Null(record.SheetFormatPath);
        Assert.NotNull(record.ScaleNumerator);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_sheet", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Theory]
    [InlineData("throws")]
    [InlineData("null")]
    [InlineData("short")]
    public void Dump_SheetPropertiesThatCannotBeRead_LeaveScaleAndProjectionNullPlusADrawingSheetGap(string how)
    {
        FakeSheet sheet = ActiveSheet();
        if (how == "throws")
        {
            sheet.Throwing.Add("GetProperties2");
        }
        else
        {
            sheet.Properties = how == "null" ? null : new[] { 12d, 0d, 1d, 1d };
        }

        DrawingSheetRecord record = Assert.Single(Dump()).Sheets[0];

        Assert.Null(record.ScaleNumerator);
        Assert.Null(record.ScaleDenominator);
        Assert.Null(record.FirstAngle);
        Assert.NotNull(record.SheetFormatPath);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_sheet", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    // -- the view --

    [Fact]
    public void Dump_RecordsTheViewsStateScaleAndOrientation()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.ReferencedConfigurationName = "Machined";
        view.OutOfDate = true;
        view.Loaded = true;
        view.Scale = 0.5;
        view.Orientation = "*Top";

        DrawingView record = Single(Dump());

        Assert.Equal("Machined", record.ReferencedConfiguration);
        Assert.True(record.IsModelOutOfDate);
        Assert.True(record.IsModelLoaded);
        Assert.Equal(0.5, record.ScaleDecimal);
        Assert.Equal("*Top", record.OrientationName);
        Assert.Empty(_scope.Gaps.Gaps);
        foreach (string member in new[] { "ReferencedConfiguration", "IsModelOutOfDate", "IsModelLoaded", "ScaleDecimal", "GetOrientationName" })
        {
            Assert.Contains(member, _observer.Members, StringComparer.Ordinal);
        }
    }

    [Theory]
    [InlineData("ReferencedConfiguration", "drawing_view_state")]
    [InlineData("IsModelOutOfDate", "drawing_view_state")]
    [InlineData("IsModelLoaded", "drawing_view_state")]
    [InlineData("ScaleDecimal", "drawing_view")]
    [InlineData("GetOrientationName", "drawing_view")]
    public void Dump_AViewReadThatThrows_IsNullPlusItsGapOnTheView(string member, string gapKind)
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.Throwing.Add(member);

        DrawingView record = Single(Dump());

        var read = new Dictionary<string, object?>
        {
            ["ReferencedConfiguration"] = record.ReferencedConfiguration,
            ["IsModelOutOfDate"] = record.IsModelOutOfDate,
            ["IsModelLoaded"] = record.IsModelLoaded,
            ["ScaleDecimal"] = record.ScaleDecimal,
            ["GetOrientationName"] = record.OrientationName,
        };
        Assert.Null(read[member]);
        Assert.All(read.Where(pair => pair.Key != member), pair => Assert.NotNull(pair.Value));

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == gapKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Theory]
    [InlineData("ReferencedConfiguration", "drawing_view_state")]
    [InlineData("GetOrientationName", "drawing_view")]
    public void Dump_AViewTextReadThatAnswersNull_IsNullPlusItsGap(string member, string gapKind)
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        if (member == "ReferencedConfiguration")
        {
            view.ReferencedConfigurationName = null;
        }
        else
        {
            view.Orientation = null;
        }

        DrawingView record = Single(Dump());

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal(gapKind, gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
    }

    // -- the display dimension: text, precision and units --

    [Fact]
    public void Dump_RecordsADimensionsFourTextPartsVerbatimTheEmptyStringKept()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.Texts = new string?[] { "<MOD-DIAM>", "THRU", "", "2X" };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal("<MOD-DIAM>", record.TextPrefix);
        Assert.Equal("THRU", record.TextSuffix);
        Assert.Equal(string.Empty, record.TextAbove);
        Assert.Equal("2X", record.TextBelow);
        Assert.Equal(new[] { 1, 2, 3, 4 }, dimension.TextPartsAsked);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void Dump_ATextPartThatThrowsOrAnswersNull_IsNullPlusADimensionTextGap(bool throws)
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        if (throws)
        {
            dimension.Throwing.Add("GetText2");
        }
        else
        {
            dimension.Texts = new string?[] { "", null, "", "" };
        }

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.TextSuffix);
        Assert.Equal(string.Empty, record.TextPrefix);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("dimension_text", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_RecordsADimensionsPrecisionAndUnits()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Precision = 3;
        dimension.TolerancePrecision = 4;
        dimension.UsesDocumentPrecision = true;
        dimension.Units = 3;
        dimension.UsesDocumentUnits = false;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal(3, record.PrecisionRaw);
        Assert.Equal(4, record.TolerancePrecisionRaw);
        Assert.True(record.UsesDocumentPrecision);
        Assert.Equal(3, record.UnitsRaw);
        Assert.False(record.UsesDocumentUnits);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Theory]
    [InlineData("GetPrimaryPrecision2")]
    [InlineData("GetPrimaryTolPrecision2")]
    [InlineData("GetUseDocPrecision")]
    [InlineData("GetUnits")]
    [InlineData("GetUseDocUnits")]
    public void Dump_APrecisionOrUnitReadThatThrows_IsNullPlusADimensionPrecisionGap(string member)
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Throwing.Add(member);

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        var read = new Dictionary<string, object?>
        {
            ["GetPrimaryPrecision2"] = record.PrecisionRaw,
            ["GetPrimaryTolPrecision2"] = record.TolerancePrecisionRaw,
            ["GetUseDocPrecision"] = record.UsesDocumentPrecision,
            ["GetUnits"] = record.UnitsRaw,
            ["GetUseDocUnits"] = record.UsesDocumentUnits,
        };
        Assert.Null(read[member]);
        Assert.All(read.Where(pair => pair.Key != member), pair => Assert.NotNull(pair.Value));
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("dimension_precision", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    // -- the display dimension: the tolerance, through feature 010's reads and mapping --

    [Fact]
    public void Dump_ABilateralToleranceIsMappedAsTheModelDimensionsIsAndCitesTheDrawing()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        FakeDimension dimension = view.AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = 2, Min = 0.0, Max = 0.00001 };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal(2, record.ToleranceTypeRaw);
        Tolerance tolerance = record.Tolerance!;
        Assert.Equal(ToleranceKind.Bilateral, tolerance.Kind);
        Assert.Equal(0.00001, tolerance.Upper!.Value);
        Assert.Equal("m", tolerance.Upper!.Unit);
        Assert.Equal(0.0, tolerance.Lower!.Value);
        Assert.Equal(_scope.DocumentId(DrawingPath), tolerance.Source.DocumentId);
        Assert.Equal("Sheet1", tolerance.Source.Sheet);
        Assert.Equal("Drawing View1", tolerance.Source.View);
        Assert.Equal(record.Id, tolerance.Source.Annotation);
        Assert.Null(record.FitHoleClass);
        Assert.Empty(_scope.Gaps.Gaps);

        // The same gated names feature 010's ToleranceDumper reads the tolerance through.
        foreach (string member in new[] { "GetDimension2", "Tolerance", "DimensionTolerance.Type", "GetMinValue2", "GetMaxValue2" })
        {
            Assert.Contains(member, _observer.Members, StringComparer.Ordinal);
        }
    }

    [Theory]
    [InlineData(0, ToleranceKind.None)]
    [InlineData(1, ToleranceKind.Basic)]
    [InlineData(3, ToleranceKind.Bilateral)]
    [InlineData(4, ToleranceKind.Symmetric)]
    public void Dump_EachToleranceTypeTakesFeature010sKind(int type, ToleranceKind kind)
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = type, Min = -0.0001, Max = 0.0001 };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal(kind, record.Tolerance!.Kind);
        Assert.Equal(type, record.ToleranceTypeRaw);
        Assert.Equal(ToleranceDumper.KindOf(type), record.Tolerance!.Kind);
    }

    [Theory]
    [InlineData(10)]
    [InlineData(11)]
    [InlineData(5)]
    public void Dump_ABlockGeneralOrOtherToleranceIsANullToleranceWithItsTypeKept(int type)
    {
        // BLOCK 10 and GENERAL 11 have no IR kind: null, never "none"; Python reads the raw type
        // (contracts/drawing-source.md section 4).
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = type };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Tolerance);
        Assert.Equal(type, record.ToleranceTypeRaw);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_AFitWithToleranceCarriesBothClassesAndItsDeviations()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = 8, Min = 0.0, Max = 0.000012, HoleFit = "H7", ShaftFit = "g6" };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal("H7", record.FitHoleClass);
        Assert.Equal("g6", record.FitShaftClass);
        Assert.Equal(ToleranceKind.Bilateral, record.Tolerance!.Kind);
        Assert.Equal(8, record.ToleranceTypeRaw);
    }

    [Fact]
    public void Dump_AFitOnlyCarriesItsClassesAndNoKind()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = 7, HoleFit = "H7", ShaftFit = "" };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Tolerance);
        Assert.Equal("H7", record.FitHoleClass);
        Assert.Null(record.FitShaftClass);
    }

    [Fact]
    public void Dump_ADimensionThatGivesNoModelDimension_IsOneDimensionToleranceGap()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.HasModelDimension = false;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Tolerance);
        Assert.Null(record.ToleranceTypeRaw);
        Assert.Null(record.DrivenStateRaw);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("dimension_tolerance", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Theory]
    [InlineData("GetDimension2")]
    [InlineData("Tolerance")]
    [InlineData("ToleranceType")]
    public void Dump_AToleranceReadThatThrows_IsADimensionToleranceGapAndNoHalfOfATolerance(string member)
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = 2, Min = 0, Max = 0.00001 };
        if (member == "ToleranceType")
        {
            dimension.Tolerance.Throwing.Add(member);
        }
        else
        {
            dimension.Throwing.Add(member);
        }

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Tolerance);
        Assert.Null(record.ToleranceTypeRaw);
        Assert.Contains(_scope.Gaps.Gaps, gap => gap.EntityKind == "dimension_tolerance" && gap.EntityId == record.Id);
        Assert.All(_scope.Gaps.Gaps, gap => Assert.Equal("dimension_tolerance", gap.EntityKind));
    }

    [Fact]
    public void Dump_ADimensionWithNoToleranceObject_IsADimensionToleranceGap()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Tolerance = null;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Tolerance);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("dimension_tolerance", gap.EntityKind);
        Assert.Contains("IDimensionTolerance", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_ALimitReportedNotValidForItsType_IsNullAndNamedInADimensionToleranceGap()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = 2, Min = null, Max = 0.00001 };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Tolerance!.Lower);
        Assert.NotNull(record.Tolerance!.Upper);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("dimension_tolerance", gap.EntityKind);
        Assert.Contains("GetMinValue2", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_ADimensionWhoseUnitIsUnknown_ReadsNoToleranceAndSaysSo()
    {
        // Its limits could only be written with a guessed unit, so they are not read at all.
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 13;
        dimension.Tolerance = new Fakes.FakeTolerance { Type = 2, Min = 0, Max = 0.00001 };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.Tolerance);
        Assert.Null(record.ToleranceTypeRaw);
        Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "dimension_unit");
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "dimension_tolerance");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.DoesNotContain("Tolerance", _observer.Members, StringComparer.Ordinal);
    }

    // -- the display dimension: reference, driven state and hole callout --

    [Fact]
    public void Dump_RecordsTheReferenceFlagAndTheDrivenState()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.IsReference = true;
        dimension.DrivenState = 2;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.True(record.IsReference);
        Assert.Equal(2, record.DrivenStateRaw);
        Assert.Contains("IsReferenceDim", _observer.Members, StringComparer.Ordinal);
        Assert.Contains("DrivenState", _observer.Members, StringComparer.Ordinal);
    }

    [Theory]
    [InlineData("IsReferenceDim")]
    [InlineData("DrivenState")]
    public void Dump_AReferenceOrDrivenStateReadThatThrows_IsNullPlusADimensionOverrideGap(string member)
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Throwing.Add(member);

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(member == "IsReferenceDim" ? (object?)record.IsReference : record.DrivenStateRaw);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("dimension_override", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_AHoleCalloutRecordsItsVariablesVerbatimInOrder()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.IsHoleCallout = true;
        dimension.CalloutVariables = new List<string> { "<hw-cbore-dia>=0.008", "<hw-cbore-depth>=0.0044", "<hw-thru>=" };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.True(record.IsHoleCallout);
        Assert.Equal(dimension.CalloutVariables, record.HoleCalloutVariablesRaw);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_ADimensionThatIsNoHoleCallout_ReadsNoVariables()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.IsHoleCallout = false;
        dimension.CalloutVariables = new List<string> { "never read" };

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.False(record.IsHoleCallout);
        Assert.Null(record.HoleCalloutVariablesRaw);
        Assert.Equal(0, dimension.CalloutVariableReads);
    }

    [Theory]
    [InlineData("IsHoleCallout")]
    [InlineData("GetHoleCalloutVariables")]
    [InlineData("null")]
    public void Dump_AHoleCalloutReadThatFails_IsADimensionTextGap(string how)
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.IsHoleCallout = true;
        if (how == "null")
        {
            dimension.CalloutVariables = null;
        }
        else
        {
            dimension.Throwing.Add(how);
        }

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.HoleCalloutVariablesRaw);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("dimension_text", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    // -- attachments (the "Attachments" rule) --

    private const string PartModelPath = @"C:\Fictional\plate\plate.SLDPRT";

    [Fact]
    public void Dump_AnAttachedFaceIsOneRowScopedToItsPartDocument()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.Attach(new FakeModelFace(PartModelPath, "RmFjZTE="));

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        AttachedFace face = Assert.Single(record.AttachedFaces!);
        Assert.Equal("RmFjZTE=", face.PersistRef);
        Assert.Equal(DocumentIds.For(PartModelPath), face.Scope);
        Assert.Equal(AttachedVia.Face, face.Via);
        Assert.Empty(_scope.Gaps.Gaps);
        foreach (string member in new[] { "GetAnnotation", "GetAttachedEntities3", "GetCorrespondingEntity" })
        {
            Assert.Contains(member, _observer.Members, StringComparer.Ordinal);
        }
    }

    [Fact]
    public void Dump_AnAttachedEdgeIsItsTwoAdjacentFacesViaEdge()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Attach(new FakeModelEdge(
            new FakeModelFace(PartModelPath, "RmFjZUE="), new FakeModelFace(PartModelPath, "RmFjZUI=")));

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal(new[] { "RmFjZUE=", "RmFjZUI=" }, record.AttachedFaces!.Select(face => face.PersistRef));
        Assert.All(record.AttachedFaces!, face => Assert.Equal(AttachedVia.Edge, face.Via));
        Assert.Contains("GetTwoAdjacentFaces2", _observer.Members, StringComparer.Ordinal);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_FacesAreDeduplicatedByReference()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        var face = new FakeModelFace(PartModelPath, "RmFjZUE=");
        dimension.Attach(face);
        dimension.Attach(new FakeModelEdge(face, new FakeModelFace(PartModelPath, "RmFjZUI=")));

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal(new[] { "RmFjZUE=", "RmFjZUI=" }, record.AttachedFaces!.Select(row => row.PersistRef));
        Assert.Equal(new[] { AttachedVia.Face, AttachedVia.Edge }, record.AttachedFaces!.Select(row => row.Via));
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_AVertexAndAnUnmappedEntityAreDroppedAndCountedInOneGap()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Attach(new FakeModelFace(PartModelPath, "RmFjZTE="));
        dimension.Attach(new FakeModelVertex());
        dimension.AttachUnmapped();
        dimension.Attach(new FakeModelFace(PartModelPath, null));

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Single(record.AttachedFaces!);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_attachment", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains("3 of 4 attached entities could not be tied to a model face", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AnAttachmentStepThatThrows_DropsThatEntityIntoTheCountWithTheError()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        var face = new FakeModelFace(PartModelPath, "RmFjZTE=") { DocumentFailure = new InvalidOperationException("no component") };
        dimension.Attach(face);
        dimension.Attach(new FakeModelFace(PartModelPath, "RmFjZTI="));

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Equal(new[] { "RmFjZTI=" }, record.AttachedFaces!.Select(row => row.PersistRef));
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Contains("1 of 2 attached entities", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("no component", gap.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AnAnnotationThatCannotListItsAttachments_IsOneDrawingAttachmentGap()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;
        dimension.Throwing.Add("GetAttachedEntities3");

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.AttachedFaces);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_attachment", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_ADimensionAttachedToNothing_HasNoFacesAndNoGap()
    {
        FakeDimension dimension = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddDimension("D1@Sketch1");
        dimension.Type2 = 2;

        DisplayDimensionRecord record = Single(Dump()).DisplayDimensions[0];

        Assert.Null(record.AttachedFaces);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Theory]
    [InlineData("not loaded")]
    [InlineData("unread")]
    [InlineData("detailing")]
    public void Dump_AViewWhoseModelIsNotAvailable_AttemptsNoAttachmentAndIsOneGapNamingTheView(string why)
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        FakeDimension first = view.AddDimension("D1@Sketch1");
        first.Type2 = 6;
        first.Attach(new FakeModelFace(PartModelPath, "RmFjZTE="));
        view.AddDimension("D2@Sketch1").Type2 = 6;
        switch (why)
        {
            case "not loaded":
                view.Loaded = false;
                break;
            case "unread":
                view.Throwing.Add("IsModelLoaded");
                break;
            default:
                _reader.Root.IsDetailingMode = true;
                break;
        }

        DrawingView record = Single(Dump());

        Assert.All(record.DisplayDimensions, dimension => Assert.Null(dimension.AttachedFaces));
        Assert.Equal(2, record.DisplayDimensions.Count);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_attachment");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.DoesNotContain("GetAttachedEntities3", _observer.Members, StringComparer.Ordinal);
        Assert.DoesNotContain("GetAnnotation", _observer.Members, StringComparer.Ordinal);

        // The dimensions themselves are still read in full.
        Assert.All(record.DisplayDimensions, dimension => Assert.NotNull(dimension.TextPrefix));
    }

    [Fact]
    public void Dump_AViewWithNoDimensionAndNoModel_RaisesNoAttachmentGap()
    {
        _reader.AddSheet("Sheet1").AddView("Sheet Format1").Loaded = false;

        Dump();

        Assert.DoesNotContain(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_attachment");
    }

    [Fact]
    public void Dump_TheNewReadsNameOnlyReadMembersToTheGate()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        FakeDimension dimension = view.AddDimension("D1@Sketch1");
        dimension.Type2 = 6;
        dimension.IsHoleCallout = true;
        dimension.CalloutVariables = new List<string> { "<hw-thru>=" };
        dimension.Attach(new FakeModelEdge(new FakeModelFace(PartModelPath, "QQ=="), new FakeModelFace(PartModelPath, "Qg==")));

        Dump();

        Assert.Empty(_observer.Refusals);
        Assert.All(_observer.Members, member => ReadOnlyGuard.Assert(member));
        Assert.DoesNotContain(_observer.Members, member => member.StartsWith("Activate", StringComparison.Ordinal)
            || member.StartsWith("Select", StringComparison.Ordinal)
            || member.StartsWith("Set", StringComparison.Ordinal)
            || member.StartsWith("OpenDoc", StringComparison.Ordinal));
    }

    // ---- callouts and tables (feature 011 T039, contracts/native-evidence.md section 3) ------

    // -- typed annotations: 010's frame and datum reads, the surface finish, the attachments --

    [Fact]
    public void Dump_AGtolRecordsItsFramesAndDatumIdentifierThroughFeature010sReads()
    {
        var gtol = new Fakes.FakeAnnotation { DatumIdentifier = "C" };
        gtol.Frames.Add(new Fakes.FakeFrame
        {
            Values = new List<string> { "0.05", "", "A", "B", "" },
            Symbols = new List<string> { "<GTOL-POSI>", "<MOD-DIAM>", "", "", "", "" },
        });
        gtol.Frames.Add(new Fakes.FakeFrame { Xml = "<frame/>" });
        _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("GTOL1", 5, false).Specific = gtol;

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Assert.Equal(2, record.GtolFrames!.Count);
        GtolFrame first = record.GtolFrames[0];
        Assert.Equal(1, first.Number);
        Assert.Equal(new[] { "0.05", "", "A", "B", "" }, first.ValuesRaw);
        Assert.Equal(new[] { "<GTOL-POSI>", "<MOD-DIAM>", "", "", "", "" }, first.SymbolsRaw);
        Assert.Null(first.SymbolXmlRaw);
        Assert.Equal("<frame/>", record.GtolFrames[1].SymbolXmlRaw);
        Assert.Equal("C", record.DatumIdentifierRaw);
        Assert.Null(record.DatumLabel);
        Assert.Null(record.SurfaceFinishSymbolRaw);
        Assert.Empty(_scope.Gaps.Gaps);
        foreach (string member in new[] { "GetSpecificAnnotation", "GetFrameCount", "GetFrameValues", "GetFrameSymbols3", "GetDatumIdentifier" })
        {
            Assert.Contains(member, _observer.Members, StringComparer.Ordinal);
        }
    }

    [Fact]
    public void Dump_ADatumTagRecordsItsLabel()
    {
        _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("DATUMTAG1", 2, false).Specific =
            new Fakes.FakeAnnotation { Type = 2, Label = "A" };

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Assert.Equal("A", record.DatumLabel);
        Assert.Null(record.GtolFrames);
        Assert.Contains("GetLabel", _observer.Members, StringComparer.Ordinal);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_ASurfaceFinishSymbolRecordsItsSymbolAndTextsVerbatim()
    {
        _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("SFSYMBOL1", 7, false).Specific =
            new FakeSurfaceFinish { Symbol = 1, Texts = { "1.6", "" } };

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Assert.Equal(1, record.SurfaceFinishSymbolRaw);
        Assert.Equal(new[] { "1.6", "" }, record.SurfaceFinishTextsRaw);
        foreach (string member in new[] { "GetSymbol", "GetTextCount", "GetTextAtIndex" })
        {
            Assert.Contains(member, _observer.Members, StringComparer.Ordinal);
        }

        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Theory]
    [InlineData(4)]
    [InlineData(6)]
    [InlineData(9)]
    public void Dump_AnAnnotationOfAnotherTypeGainsNothingAndIsAskedNothingMore(int type)
    {
        _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("NOTE1", type, false);

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Assert.Null(record.GtolFrames);
        Assert.Null(record.DatumLabel);
        Assert.Null(record.SurfaceFinishSymbolRaw);
        Assert.Null(record.AttachedFaces);
        Assert.DoesNotContain("GetSpecificAnnotation", _observer.Members, StringComparer.Ordinal);
        Assert.DoesNotContain("GetAttachedEntities3", _observer.Members, StringComparer.Ordinal);
    }

    [Theory]
    [InlineData(5, "GetSpecificAnnotation")]
    [InlineData(5, "FrameCount")]
    [InlineData(5, "DatumIdentifier")]
    [InlineData(2, "GetSpecificAnnotation")]
    [InlineData(2, "DatumLabel")]
    [InlineData(7, "GetSpecificAnnotation")]
    [InlineData(7, "GetSymbol")]
    [InlineData(7, "GetTextCount")]
    [InlineData(7, "GetTextAtIndex")]
    public void Dump_ATypedReadThatThrows_IsADrawingSymbolReadGapOnTheAnnotation(int type, string member)
    {
        FakeAnnotation annotation = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("A1", type, false);
        if (type == 7)
        {
            var symbol = new FakeSurfaceFinish { Symbol = 1, Texts = { "1.6" } };
            symbol.Throwing.Add(member);
            annotation.Specific = symbol;
        }
        else
        {
            var specific = new Fakes.FakeAnnotation { Type = type, DatumIdentifier = "C", Label = "A" };
            specific.Frames.Add(new Fakes.FakeFrame { Values = new List<string> { "0.1" } });
            specific.Throwing.Add(member);
            annotation.Specific = specific;
        }

        if (member == "GetSpecificAnnotation")
        {
            annotation.Throwing.Add(member);
        }

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_symbol_read", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Theory]
    [InlineData(2)]
    [InlineData(5)]
    [InlineData(7)]
    public void Dump_ATypedAnnotationWithNoSpecificAnnotation_IsADrawingSymbolReadGap(int type)
    {
        _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("A1", type, false).Specific = null;

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_symbol_read", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
    }

    [Fact]
    public void Dump_AGtolFrameNoCallAnswered_IsLeftOutWithOneGapNamingEveryError()
    {
        var gtol = new Fakes.FakeAnnotation();
        var frame = new Fakes.FakeFrame();
        frame.Throwing.Add("FrameValues");
        frame.Throwing.Add("FrameSymbols");
        gtol.Frames.Add(frame);
        gtol.Frames.Add(new Fakes.FakeFrame { Values = new List<string> { "0.1" } });
        _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("GTOL1", 5, false).Specific = gtol;

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Assert.Equal(new[] { 2 }, record.GtolFrames!.Select(f => f.Number));
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_symbol_read", gap.EntityKind);
        Assert.Contains("frame 1", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("FrameValues", gap.Error, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(2)]
    [InlineData(5)]
    [InlineData(7)]
    public void Dump_ATypedAnnotationRecordsTheFacesItIsAttachedTo(int type)
    {
        FakeAnnotation annotation = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("A1", type, false);
        annotation.Specific = type == 7
            ? new FakeSurfaceFinish { Symbol = 1 }
            : (object)new Fakes.FakeAnnotation { Type = type, Label = "A" };
        annotation.Attach(new FakeModelFace(PartModelPath, "RmFjZTE="));

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        AttachedFace face = Assert.Single(record.AttachedFaces!);
        Assert.Equal("RmFjZTE=", face.PersistRef);
        Assert.Equal(DocumentIds.For(PartModelPath), face.Scope);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_ATypedAnnotationWhoseAttachmentsAreNotTied_IsOneDrawingAttachmentGapOnIt()
    {
        FakeAnnotation annotation = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddAnnotation("A1", 5, false);
        annotation.Specific = new Fakes.FakeAnnotation();
        annotation.AttachUnmapped();

        DrawingAnnotation record = Assert.Single(Single(Dump()).Annotations);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_attachment", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
        Assert.Contains("1 of 1 attached entities", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_AViewWithNoModel_CountsItsTypedAnnotationsWithItsDimensionsInOneGap()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        view.Loaded = false;
        view.AddDimension("D1@Sketch1").Type2 = 6;
        view.AddAnnotation("A1", 5, false).Specific = new Fakes.FakeAnnotation();
        view.AddAnnotation("NOTE1", 6, false);

        DrawingView record = Single(Dump());

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "drawing_attachment");
        Assert.Equal(record.Id, gap.EntityId);
        Assert.StartsWith("What 2 dimensions and annotations", gap.Reason, StringComparison.Ordinal);

        // The typed read still happens: it needs no model.
        Assert.Contains("GetSpecificAnnotation", _observer.Members, StringComparer.Ordinal);
    }

    // -- tables --

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(5)]
    [InlineData(9)]
    public void Dump_ATableThatIsNoRevisionTableIsRecordedOnTheSheetCellByCell(int type)
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Drawing View1");
        FakeTable table = view.AddTable(type, currentRevision: null);
        table.Title = "FICTIONAL TABLE";
        table.Rows = new[] { new string?[] { "ITEM", "QTY" }, new string?[] { "1", "" } };

        DrawingSheetRecord sheet = Assert.Single(Dump()).Sheets[0];

        Assert.Empty(sheet.RevisionTables);
        DrawingTable record = Assert.Single(sheet.Tables!);
        Assert.Equal("dtb:0001", record.Id);
        Assert.Equal(sheet.Id, record.SheetId);
        Assert.Equal(sheet.Views[0].Id, record.OwnerViewId);
        Assert.Equal(type, record.TableTypeRaw);
        Assert.Equal("FICTIONAL TABLE", record.Title);
        Assert.Equal(2, record.RowCount);
        Assert.Equal(2, record.ColumnCount);
        Assert.Equal(new[] { 0, 1 }, record.Rows.Select(row => row.Index));
        Assert.Equal(new string?[] { "1", "" }, record.Rows[1].Cells);
        Assert.All(record.Rows, row => Assert.Null(row.IsHeader));
        Assert.Contains("Title", _observer.Members, StringComparer.Ordinal);
    }

    [Fact]
    public void Dump_ARevisionTableStaysARevisionTableAndIsNoSheetTable()
    {
        FakeView view = _reader.AddSheet("Sheet1").AddView("Sheet Format1");
        view.AddTable(type: 3, currentRevision: "B").Rows = new[] { new string?[] { "B" } };
        view.AddTable(type: 5, currentRevision: null).Rows = new[] { new string?[] { "FICTIONAL TITLE" } };

        DrawingSheetRecord sheet = Assert.Single(Dump()).Sheets[0];

        Assert.Equal("drv:0001", Assert.Single(sheet.RevisionTables).Id);
        DrawingTable table = Assert.Single(sheet.Tables!);
        Assert.Equal(5, table.TableTypeRaw);
        Assert.Equal("dtb:0001", table.Id);
    }

    [Fact]
    public void Dump_ASheetWithNoOtherTable_HasNoTablesMember()
    {
        _reader.AddSheet("Sheet1").AddView("Sheet Format1").AddTable(type: 3, currentRevision: "A");

        Assert.Null(Assert.Single(Dump()).Sheets[0].Tables);
    }

    [Fact]
    public void Dump_ATableCellThatCannotBeRead_IsNullPlusADrawingTableReadGap()
    {
        FakeTable table = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddTable(0, null);
        table.Rows = new[] { new string?[] { "A", "B" } };
        table.CellFailures.Add((0, 1));

        DrawingTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].Tables!);

        Assert.Equal(new string?[] { "A", null }, record.Rows[0].Cells);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_table_read", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void Dump_ATableTitleThatThrowsOrAnswersNull_IsNullPlusADrawingTableReadGap(bool throws)
    {
        FakeTable table = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddTable(0, null);
        if (throws)
        {
            table.Throwing.Add("Title");
        }
        else
        {
            table.Title = null;
        }

        DrawingTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].Tables!);

        Assert.Null(record.Title);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_table_read", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_ATableWhoseShapeCannotBeRead_HasNoRowsAndAGap()
    {
        FakeTable table = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddTable(1, null);
        table.ShapeFailure = new InvalidCastException("not an ITableAnnotation");

        DrawingTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].Tables!);

        Assert.Empty(record.Rows);
        Assert.Null(record.RowCount);
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_table_read", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_ABillOfMaterialsResolvesItsRowsToPackageDocumentsAndKeepsAnUnresolvedPath()
    {
        const string LibraryPath = @"C:\vault\library\missing.SLDPRT";
        FakeTable table = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddTable(2, null);
        table.Rows = new[] { new string?[] { "ITEM" }, new string?[] { "1" }, new string?[] { "2" }, new string?[] { "3" } };
        table.ModelPaths[1] = new List<string> { HousingPath.ToUpperInvariant() };
        table.ModelPaths[2] = new List<string> { LibraryPath };
        table.ModelPaths[3] = new List<string> { HousingPath, LibraryPath };

        DrawingTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].Tables!);

        List<BomRow> rows = record.BomRows!;
        Assert.Equal(new[] { 1, 2, 3 }, rows.Select(row => row.Index));
        Assert.Equal(new[] { DocumentIds.For(HousingPath) }, rows[0].DocumentIds);
        Assert.Null(rows[0].UnresolvedPaths);
        Assert.Null(rows[1].DocumentIds);
        Assert.Equal(new[] { LibraryPath }, rows[1].UnresolvedPaths);
        Assert.Equal(new[] { DocumentIds.For(HousingPath) }, rows[2].DocumentIds);
        Assert.Equal(new[] { LibraryPath }, rows[2].UnresolvedPaths);
        Assert.Contains("GetModelPathNames", _observer.Members, StringComparer.Ordinal);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_OnlyABillOfMaterialsIsAskedForItsRowsModels()
    {
        FakeTable table = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddTable(0, null);
        table.Rows = new[] { new string?[] { "1" } };
        table.ModelPaths[0] = new List<string> { HousingPath };

        DrawingTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].Tables!);

        Assert.Null(record.BomRows);
        Assert.DoesNotContain("GetModelPathNames", _observer.Members, StringComparer.Ordinal);
    }

    [Fact]
    public void Dump_ABillOfMaterialsRowThatCannotBeResolved_IsADrawingTableReadGapAndTheOtherRowsAreKept()
    {
        FakeTable table = _reader.AddSheet("Sheet1").AddView("Drawing View1").AddTable(2, null);
        table.Rows = new[] { new string?[] { "1" }, new string?[] { "2" } };
        table.ModelPaths[1] = new List<string> { HousingPath };
        table.ModelPathFailures.Add(0);

        DrawingTable record = Assert.Single(Assert.Single(Dump()).Sheets[0].Tables!);

        Assert.Equal(new[] { 1 }, record.BomRows!.Select(row => row.Index));
        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("drawing_table_read", gap.EntityKind);
        Assert.Equal(record.Id, gap.EntityId);
    }

    [Fact]
    public void Dump_ATableTwoViewsReturnIsRecordedOnce()
    {
        FakeSheet sheet = _reader.AddSheet("Sheet1");
        FakeTable shared = sheet.AddView("Sheet Format1").AddTable(5, null);
        sheet.AddView("Drawing View1").Tables.Add(shared);

        DrawingSheetRecord record = Assert.Single(Dump()).Sheets[0];

        DrawingTable table = Assert.Single(record.Tables!);
        Assert.Equal(record.Views[0].Id, table.OwnerViewId);
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

        // Feature 011 (native-evidence.md section 3, "Tables").
        public string? Title { get; set; } = "FICTIONAL TABLE";

        /// <summary>GetModelPathNames per row, for a bill of materials; a row not here answers nothing.</summary>
        public Dictionary<int, List<string>?> ModelPaths { get; } = new Dictionary<int, List<string>?>();

        /// <summary>Rows whose GetModelPathNames throws.</summary>
        public HashSet<int> ModelPathFailures { get; } = new HashSet<int>();

        public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);
    }

    /// <summary>What GetAttachedEntities3 answers for a dimension or a typed annotation.</summary>
    private interface IFakeAttachable
    {
        List<FakeDrawingEntity?> Entities { get; }

        HashSet<string> Throwing { get; }
    }

    /// <summary>An ISFSymbol: its symbol and its texts.</summary>
    private sealed class FakeSurfaceFinish
    {
        public int Symbol { get; set; }

        public List<string?> Texts { get; } = new List<string?>();

        public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);
    }

    private sealed class FakeNote
    {
        public string? Text { get; set; }
    }

    private sealed class FakeAnnotation : IFakeAttachable
    {
        public string? Name { get; set; }

        public int Type { get; set; }

        public bool Dangling { get; set; }

        public Exception? DanglingFailure { get; set; }

        // Feature 011: the typed annotation behind it (feature 010's fake GTol or datum tag, or a
        // surface finish symbol), and what it is attached to.
        public object? Specific { get; set; }

        public List<FakeDrawingEntity?> Entities { get; } = new List<FakeDrawingEntity?>();

        public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);

        public void Attach(object model) => Entities.Add(new FakeDrawingEntity(model));

        public void AttachUnmapped() => Entities.Add(new FakeDrawingEntity(null));
    }

    private sealed class FakeDimension : IFakeAttachable
    {
        public string? Name { get; set; }

        public int Type2 { get; set; }

        public bool IsOverridden { get; set; }

        public double OverrideValue { get; set; }

        public double Value { get; set; }

        public Exception? OverrideFailure { get; set; }

        // Feature 011 (native-evidence.md section 3). Every read answers by default.

        /// <summary>GetText(1..4): prefix, suffix, callout above, callout below.</summary>
        public string?[] Texts { get; set; } = { "", "", "", "" };

        public List<int> TextPartsAsked { get; } = new List<int>();

        public int Precision { get; set; } = 2;

        public int TolerancePrecision { get; set; } = 3;

        public bool UsesDocumentPrecision { get; set; }

        public int Units { get; set; }

        public bool UsesDocumentUnits { get; set; } = true;

        /// <summary>False when GetDimension2 gives no IDimension.</summary>
        public bool HasModelDimension { get; set; } = true;

        /// <summary>Feature 010's fake tolerance; NONE by default, so no limit is read.</summary>
        public Fakes.FakeTolerance? Tolerance { get; set; } = new Fakes.FakeTolerance { Type = 0 };

        public bool IsReference { get; set; }

        public int DrivenState { get; set; } = 1;

        public bool IsHoleCallout { get; set; }

        public List<string>? CalloutVariables { get; set; }

        public int CalloutVariableReads { get; set; }

        /// <summary>What GetAttachedEntities3 answers for this dimension's annotation.</summary>
        public List<FakeDrawingEntity?> Entities { get; } = new List<FakeDrawingEntity?>();

        /// <summary>Members that throw when read ("GetText2" for the suffix, "Tolerance", ...).</summary>
        public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);

        /// <summary>A drawing entity whose model counterpart is <paramref name="model"/>.</summary>
        public void Attach(object model) => Entities.Add(new FakeDrawingEntity(model));

        /// <summary>A drawing entity GetCorrespondingEntity maps to nothing.</summary>
        public void AttachUnmapped() => Entities.Add(new FakeDrawingEntity(null));
    }

    /// <summary>One entity GetAttachedEntities3 answers, and its model counterpart.</summary>
    private sealed class FakeDrawingEntity
    {
        public FakeDrawingEntity(object? corresponding)
        {
            Corresponding = corresponding;
        }

        public object? Corresponding { get; }
    }

    /// <summary>A model face: its owning part document and its persistent reference.</summary>
    private sealed class FakeModelFace
    {
        public FakeModelFace(string documentPath, string? persistRef)
        {
            DocumentPath = documentPath;
            PersistRef = persistRef;
        }

        public string DocumentPath { get; }

        public string? PersistRef { get; }

        /// <summary>What finding its owning document throws, or null.</summary>
        public Exception? DocumentFailure { get; set; }
    }

    /// <summary>A model edge and its two adjacent faces.</summary>
    private sealed class FakeModelEdge
    {
        public FakeModelEdge(params FakeModelFace[] faces)
        {
            Faces = faces;
        }

        public IReadOnlyList<FakeModelFace> Faces { get; }
    }

    /// <summary>A model entity that is neither a face nor an edge.</summary>
    private sealed class FakeModelVertex
    {
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

        // Feature 011 (native-evidence.md section 3).
        public string? ReferencedConfigurationName { get; set; } = "Default";

        public bool OutOfDate { get; set; }

        public bool Loaded { get; set; } = true;

        public double Scale { get; set; } = 1.0;

        public string? Orientation { get; set; } = "*Front";

        public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);

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

        // Feature 011 (native-evidence.md section 3).
        public string? TemplateName { get; set; } = @"C:\Fictional\Formats\FICTIONAL-FORMAT-A.slddrt";

        /// <summary>GetProperties2: paper size, template, scale numerator and denominator, first angle, width, height.</summary>
        public double[]? Properties { get; set; } = { 12d, 0d, 1d, 1d, 0d, 0.42, 0.297 };

        public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);

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

        // Feature 011 (native-evidence.md section 3).
        public bool IsDetailingMode { get; set; }

        /// <summary>GetUserPreferenceInteger answers, by enumerator.</summary>
        public Dictionary<int, int> IntegerPreferences { get; } = new Dictionary<int, int>
        {
            [47] = 0,
            [24] = 2,
            [49] = 2,
            [25] = 3,
        };

        public string? DraftingStandard { get; set; } = "FICTIONAL-STANDARD";

        public List<int> IntegerPreferencesAsked { get; } = new List<int>();

        public List<int> StringPreferencesAsked { get; } = new List<int>();

        /// <summary>"IsDetailingMode", or a preference enumerator as text, that throws when read.</summary>
        public HashSet<string> Throwing { get; } = new HashSet<string>(StringComparer.Ordinal);
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

        /// <summary>The root drawing itself, for the settings a test scripts.</summary>
        public FakeDrawing Root => _root;

        /// <summary>Feature 010's tolerance fake answers the tolerance reads, shared rather than copied.</summary>
        private readonly Fakes.FakeDimensionToleranceReader _tolerances = new Fakes.FakeDimensionToleranceReader();

        /// <summary>Feature 010's annotation fake answers the frame and datum reads, shared rather than copied.</summary>
        private readonly Fakes.FakeModelAnnotationReader _annotationReads = new Fakes.FakeModelAnnotationReader();

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
            if (entity is FakeModelFace face)
            {
                string modelPath = ((FakeModel)document).Path;
                return face.PersistRef == null
                    ? null
                    : new ScopedPersistRef(face.PersistRef, DocumentIds.For(modelPath), modelPath);
            }

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

        // ---- feature 011 (native-evidence.md section 3) ----

        bool IDrawingReader.IsDetailingMode(object drawing) =>
            Answer(Of(drawing).Throwing, "IsDetailingMode", Of(drawing).IsDetailingMode);

        int IDrawingReader.UserPreferenceInteger(object document, int preference)
        {
            FakeDrawing drawing = _byDocument[document];
            drawing.IntegerPreferencesAsked.Add(preference);
            return Answer(drawing.Throwing, Text(preference), drawing.IntegerPreferences[preference]);
        }

        string? IDrawingReader.UserPreferenceString(object document, int preference)
        {
            FakeDrawing drawing = _byDocument[document];
            drawing.StringPreferencesAsked.Add(preference);
            return Answer(drawing.Throwing, Text(preference), drawing.DraftingStandard);
        }

        string? IDrawingReader.SheetTemplateName(object sheet) =>
            Answer(Sheet(sheet).Throwing, "GetTemplateName", Sheet(sheet).TemplateName);

        IReadOnlyList<double>? IDrawingReader.SheetProperties(object sheet) =>
            Answer(Sheet(sheet).Throwing, "GetProperties2", Sheet(sheet).Properties);

        string? IDrawingReader.ReferencedConfiguration(object view) =>
            Answer(View(view).Throwing, "ReferencedConfiguration", View(view).ReferencedConfigurationName);

        bool IDrawingReader.IsModelOutOfDate(object view) =>
            Answer(View(view).Throwing, "IsModelOutOfDate", View(view).OutOfDate);

        bool IDrawingReader.IsModelLoaded(object view) =>
            Answer(View(view).Throwing, "IsModelLoaded", View(view).Loaded);

        double IDrawingReader.ScaleDecimal(object view) =>
            Answer(View(view).Throwing, "ScaleDecimal", View(view).Scale);

        string? IDrawingReader.OrientationName(object view) =>
            Answer(View(view).Throwing, "GetOrientationName", View(view).Orientation);

        string? IDrawingReader.DimensionText(object dimension, int part)
        {
            FakeDimension found = Dimension(dimension);
            found.TextPartsAsked.Add(part);
            return Answer(found.Throwing, "GetText" + Text(part), found.Texts[part - 1]);
        }

        int IDrawingReader.PrimaryPrecision(object dimension) =>
            Answer(Dimension(dimension).Throwing, "GetPrimaryPrecision2", Dimension(dimension).Precision);

        int IDrawingReader.PrimaryTolerancePrecision(object dimension) =>
            Answer(Dimension(dimension).Throwing, "GetPrimaryTolPrecision2", Dimension(dimension).TolerancePrecision);

        bool IDrawingReader.UsesDocumentPrecision(object dimension) =>
            Answer(Dimension(dimension).Throwing, "GetUseDocPrecision", Dimension(dimension).UsesDocumentPrecision);

        int IDrawingReader.Units(object dimension) =>
            Answer(Dimension(dimension).Throwing, "GetUnits", Dimension(dimension).Units);

        bool IDrawingReader.UsesDocumentUnits(object dimension) =>
            Answer(Dimension(dimension).Throwing, "GetUseDocUnits", Dimension(dimension).UsesDocumentUnits);

        /// <summary>The display dimension stands for its own IDimension.</summary>
        object? IDrawingReader.DimensionOf(object dimension)
        {
            FakeDimension found = Dimension(dimension);
            return Answer<object?>(found.Throwing, "GetDimension2", found.HasModelDimension ? found : null);
        }

        bool IDrawingReader.IsReferenceDimension(object dimension) =>
            Answer(Dimension(dimension).Throwing, "IsReferenceDim", Dimension(dimension).IsReference);

        int IDrawingReader.DrivenState(object modelDimension) =>
            Answer(Dimension(modelDimension).Throwing, "DrivenState", Dimension(modelDimension).DrivenState);

        bool IDrawingReader.IsHoleCallout(object dimension) =>
            Answer(Dimension(dimension).Throwing, "IsHoleCallout", Dimension(dimension).IsHoleCallout);

        IReadOnlyList<string>? IDrawingReader.HoleCalloutVariables(object dimension)
        {
            FakeDimension found = Dimension(dimension);
            found.CalloutVariableReads++;
            return Answer(found.Throwing, "GetHoleCalloutVariables", found.CalloutVariables);
        }

        /// <summary>The display dimension stands for its own annotation.</summary>
        object? IDrawingReader.DimensionAnnotation(object dimension) =>
            Answer<object?>(Dimension(dimension).Throwing, "GetAnnotation", dimension);

        IReadOnlyList<object?> IDrawingReader.AttachedEntities(object annotation)
        {
            var attachable = (IFakeAttachable)annotation;
            return Answer<IReadOnlyList<object?>>(
                attachable.Throwing, "GetAttachedEntities3", attachable.Entities.Cast<object?>().ToList());
        }

        object? IAnnotationSymbolReads.Specific(object annotation) =>
            Answer(Annotation(annotation).Throwing, "GetSpecificAnnotation", Annotation(annotation).Specific);

        int IAnnotationSymbolReads.FrameCount(object gtol) => _annotationReads.FrameCount(gtol);

        IReadOnlyList<string>? IAnnotationSymbolReads.FrameValues(object gtol, int frame) =>
            _annotationReads.FrameValues(gtol, frame);

        IReadOnlyList<string>? IAnnotationSymbolReads.FrameSymbols(object gtol, int frame) =>
            _annotationReads.FrameSymbols(gtol, frame);

        string? IAnnotationSymbolReads.FrameXml(object gtol, int frame) => _annotationReads.FrameXml(gtol, frame);

        string? IAnnotationSymbolReads.DatumIdentifier(object gtol) => _annotationReads.DatumIdentifier(gtol);

        string? IAnnotationSymbolReads.DatumLabel(object datumTag) => _annotationReads.DatumLabel(datumTag);

        int IDrawingReader.SurfaceFinishSymbol(object symbol) =>
            Answer(((FakeSurfaceFinish)symbol).Throwing, "GetSymbol", ((FakeSurfaceFinish)symbol).Symbol);

        int IDrawingReader.SurfaceFinishTextCount(object symbol) =>
            Answer(((FakeSurfaceFinish)symbol).Throwing, "GetTextCount", ((FakeSurfaceFinish)symbol).Texts.Count);

        string? IDrawingReader.SurfaceFinishText(object symbol, int index) =>
            Answer(((FakeSurfaceFinish)symbol).Throwing, "GetTextAtIndex", ((FakeSurfaceFinish)symbol).Texts[index]);

        string? IDrawingReader.TableTitle(object table) => Answer(Table(table).Throwing, "Title", Table(table).Title);

        IReadOnlyList<string>? IDrawingReader.BomModelPaths(object table, int row)
        {
            FakeTable found = Table(table);
            if (found.ModelPathFailures.Contains(row))
            {
                throw new InvalidOperationException($"GetModelPathNames of row {row} did not answer");
            }

            return found.ModelPaths.TryGetValue(row, out List<string>? paths) ? paths : null;
        }

        object? IDrawingReader.CorrespondingEntity(object view, object entity) =>
            ((FakeDrawingEntity)entity).Corresponding;

        AttachedEntityKind IDrawingReader.EntityKind(object entity) => entity switch
        {
            FakeModelFace _ => AttachedEntityKind.Face,
            FakeModelEdge _ => AttachedEntityKind.Edge,
            _ => AttachedEntityKind.Other,
        };

        IReadOnlyList<object> IDrawingReader.AdjacentFaces(object edge) =>
            ((FakeModelEdge)edge).Faces.Cast<object>().ToList();

        object? IDrawingReader.FaceDocument(object view, object face)
        {
            var found = (FakeModelFace)face;
            return found.DocumentFailure != null ? throw found.DocumentFailure : new FakeModel(found.DocumentPath);
        }

        object? IDimensionToleranceReads.Tolerance(object dimension) =>
            Answer(Dimension(dimension).Throwing, "Tolerance", Dimension(dimension).Tolerance);

        int IDimensionToleranceReads.ToleranceType(object tolerance) => _tolerances.ToleranceType(tolerance);

        double? IDimensionToleranceReads.ToleranceMin(object tolerance) => _tolerances.ToleranceMin(tolerance);

        double? IDimensionToleranceReads.ToleranceMax(object tolerance) => _tolerances.ToleranceMax(tolerance);

        string? IDimensionToleranceReads.HoleFitValue(object tolerance) => _tolerances.HoleFitValue(tolerance);

        string? IDimensionToleranceReads.ShaftFitValue(object tolerance) => _tolerances.ShaftFitValue(tolerance);

        /// <summary><paramref name="value"/>, or a throw when <paramref name="member"/> is scripted to fail.</summary>
        private static T Answer<T>(HashSet<string> throwing, string member, T value) =>
            throwing.Contains(member) ? throw new InvalidOperationException($"{member} did not answer") : value;

        private static string Text(int value) => value.ToString(System.Globalization.CultureInfo.InvariantCulture);

        private static FakeDrawing Of(object drawing) => (FakeDrawing)drawing;

        private static FakeTable Table(object table) => (FakeTable)table;

        private static FakeSheet Sheet(object sheet) => (FakeSheet)sheet;

        private static FakeView View(object view) => (FakeView)view;

        private static FakeDimension Dimension(object dimension) => (FakeDimension)dimension;

        private static FakeAnnotation Annotation(object annotation) => (FakeAnnotation)annotation;
    }
}
