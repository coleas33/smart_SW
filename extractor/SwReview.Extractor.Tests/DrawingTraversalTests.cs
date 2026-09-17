using System;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T057. The <c>drawing</c> phase's ordering class (schema 1.4.0, <c>research.md</c> R9):
/// which record comes before which, what index and id each one carries, and which record
/// owns which.
///
/// It is pure, and the test that matters most is the last one here: <b>no interop type
/// appears anywhere in its signature</b>. The drawing phase reads a live
/// <c>IDrawingDoc</c> that this machine has no seat to produce, so the ordering rules -
/// the ones a reader of a package actually depends on - would otherwise be testable only
/// on the pilot workstation. <see cref="DrawingDumper"/> drives this class in
/// <c>GetSheetNames()</c> and <c>ISheet.GetViews()</c> order, and
/// <see cref="DrawingDumperTests"/> pins that.
///
/// Two rules are policy and live here rather than in the dumper:
///
///   * <b><c>was_active</c> is derived, never read per sheet.</b> Nothing activates a
///     sheet (FR-044), so the only honest reading is "the active sheet's name equals
///     mine", taken once from <c>GetCurrentSheet()</c>.
///   * <b>The sheet-format pseudo-view is a view.</b> <c>view_type_raw == 1</c> is the
///     view the export-control note lives on, and it is allocated, ordered and owned
///     exactly like any other view - the type number is recorded and nothing branches on
///     it here.
/// </summary>
public class DrawingTraversalTests
{
    private const string DocumentId = "doc:0a1b2c3d4e5f";

    // ---- the record itself ---------------------------------------------------------

    [Fact]
    public void Record_CarriesTheDocumentIdTheActiveSheetAndTheNativeSource()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet2");

        Assert.Equal(DocumentId, traversal.Record.DocumentId);
        Assert.Equal("Sheet2", traversal.Record.ActiveSheetName);
        Assert.Equal(DrawingEvidenceSource.Native, traversal.Record.Source);
        Assert.Empty(traversal.Record.Sheets);
    }

    [Fact]
    public void Record_WithNoActiveSheetName_CarriesNullAndNoSheetIsActive()
    {
        // GetCurrentSheet() that could not be read is a null, not "sheet 1": which sheet was
        // active is what tells a consumer which rows to trust, and guessing it would make a
        // sheet nobody looked at read as the one that was on screen.
        var traversal = new DrawingTraversal(DocumentId, null);

        Assert.Null(traversal.Record.ActiveSheetName);
        Assert.All(new[] { traversal.AddSheet("Sheet1", 0), traversal.AddSheet("Sheet2", 1) },
            sheet => Assert.False(sheet.WasActive));
    }

    // ---- sheets --------------------------------------------------------------------

    [Fact]
    public void AddSheet_NumbersSheetsFromZeroInCallOrder()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");

        traversal.AddSheet("Sheet1", 0);
        traversal.AddSheet("Sheet2", 1);
        traversal.AddSheet("Detail", 2);

        Assert.Equal(
            new[] { "Sheet1", "Sheet2", "Detail" },
            traversal.Record.Sheets.Select(sheet => sheet.Name));
        Assert.Equal(new[] { 0, 1, 2 }, traversal.Record.Sheets.Select(sheet => sheet.Index));
        Assert.Equal(
            new[] { "dsh:0001", "dsh:0002", "dsh:0003" },
            traversal.Record.Sheets.Select(sheet => sheet.Id));
    }

    [Fact]
    public void AddSheet_TakesTheGetSheetNamesPositionRatherThanCountingWhatWasRecorded()
    {
        // `index` is the sheet's position in GetSheetNames(), from 0
        // (contracts/ir-additions.md section 3.2) - not the number of sheets that happened to
        // be recorded before it. A sheet the Sheet[name] indexer will not answer for is
        // skipped by the dumper, and numbering the survivors 0, 1, 2 would make a check name
        // "sheet 2" for what is sheet 3 of the drawing, in a finding whose whole job is to
        // cite the sheet.
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");

        traversal.AddSheet("Sheet1", 0);
        traversal.AddSheet("Sheet3", 2);

        Assert.Equal(new[] { 0, 2 }, traversal.Record.Sheets.Select(sheet => sheet.Index));

        // The ids stay allocation order: dsh:NNNN is the package's own numbering and says
        // nothing about which sheet of the drawing it was.
        Assert.Equal(
            new[] { "dsh:0001", "dsh:0002" },
            traversal.Record.Sheets.Select(sheet => sheet.Id));
    }

    [Fact]
    public void AddSheet_RefusesANegativeIndex()
    {
        // There is no position before the first, so a negative index is a caller that lost
        // count rather than a sheet: it is refused here, where the call site is, instead of
        // reaching the package as a sheet number no reader can make sense of.
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");

        Assert.Throws<ArgumentOutOfRangeException>(() => traversal.AddSheet("Sheet1", -1));
    }

    [Fact]
    public void AddSheet_MarksOnlyTheSheetWhoseNameIsTheActiveOne()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet2");

        DrawingSheetRecord first = traversal.AddSheet("Sheet1", 0);
        DrawingSheetRecord second = traversal.AddSheet("Sheet2", 1);
        DrawingSheetRecord third = traversal.AddSheet("Sheet3", 2);

        Assert.False(first.WasActive);
        Assert.True(second.WasActive);
        Assert.False(third.WasActive);
    }

    [Fact]
    public void AddSheet_RecordsEverySheetAsNativelyExtracted()
    {
        // The per-sheet half of FR-024: a package can carry sheets from this phase and from
        // the PDF ingest at once, and the drawing checks grade the native ones only.
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");

        Assert.Equal(DrawingEvidenceSource.Native, traversal.AddSheet("Sheet1", 0).Source);
    }

    // ---- views ---------------------------------------------------------------------

    [Fact]
    public void AddView_AllocatesInTraversalOrderAcrossEverySheet()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");

        DrawingSheetRecord first = traversal.AddSheet("Sheet1", 0);
        traversal.AddView(first);
        traversal.AddView(first);

        DrawingSheetRecord second = traversal.AddSheet("Sheet2", 1);
        traversal.AddView(second);

        Assert.Equal(
            new[] { "dvw:0001", "dvw:0002" }, first.Views.Select(view => view.Id));
        Assert.Equal(new[] { "dvw:0003" }, second.Views.Select(view => view.Id));
    }

    [Fact]
    public void AddView_NamesTheSheetItWasReadFrom()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);

        Assert.Equal(sheet.Id, traversal.AddView(sheet).SheetId);
    }

    [Fact]
    public void AddView_CarriesTheSheetFormatPseudoViewLikeAnyOtherView()
    {
        // swDrawingViewTypes_e.swDrawingSheet = 1 is where the export-control note lives.
        // Nothing here branches on the type: the number is recorded by the dumper and named
        // in Python, and the pseudo-view keeps its place in GetViews() order.
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);

        DrawingView format = traversal.AddView(sheet);
        format.ViewTypeRaw = 1;
        DrawingView drawing = traversal.AddView(sheet);
        drawing.ViewTypeRaw = 4;

        Assert.Equal(new[] { "dvw:0001", "dvw:0002" }, sheet.Views.Select(view => view.Id));
        Assert.Equal(new int?[] { 1, 4 }, sheet.Views.Select(view => view.ViewTypeRaw));
    }

    // ---- the entities a view owns --------------------------------------------------

    [Fact]
    public void AddDimension_AllocatesInTraversalOrderAndNamesItsView()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);
        DrawingView first = traversal.AddView(sheet);
        DrawingView second = traversal.AddView(sheet);

        traversal.AddDimension(first);
        traversal.AddDimension(first);
        traversal.AddDimension(second);

        Assert.Equal(
            new[] { "ddm:0001", "ddm:0002" },
            first.DisplayDimensions.Select(dimension => dimension.Id));
        Assert.Equal(
            new[] { "ddm:0003" }, second.DisplayDimensions.Select(dimension => dimension.Id));
        Assert.All(first.DisplayDimensions, dimension => Assert.Equal(first.Id, dimension.ViewId));
        Assert.Equal(second.Id, second.DisplayDimensions[0].ViewId);
    }

    [Fact]
    public void AddAnnotation_AllocatesInTraversalOrderAndNamesTheViewItWasReadFrom()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);
        DrawingView view = traversal.AddView(sheet);

        traversal.AddAnnotation(view);
        traversal.AddAnnotation(view);

        Assert.Equal(new[] { "dan:0001", "dan:0002" }, view.Annotations.Select(a => a.Id));
        Assert.All(view.Annotations, annotation => Assert.Equal(view.Id, annotation.OwnerId));
    }

    [Fact]
    public void AddAnnotation_OnTheSheetFormatView_IsOwnedByThatPseudoView()
    {
        // contracts/ir-additions.md section 3.5: "a sheet-format annotation's owner is the
        // type-1 pseudo-view". It is not the sheet, and it is not the drawing.
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);

        DrawingView format = traversal.AddView(sheet);
        format.ViewTypeRaw = 1;

        Assert.Equal(format.Id, traversal.AddAnnotation(format).OwnerId);
        Assert.Equal(format.Id, traversal.AddNote(format).OwnerId);
    }

    [Fact]
    public void AddNote_AllocatesInTraversalOrderAndNamesTheViewItWasReadFrom()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);
        DrawingView first = traversal.AddView(sheet);
        DrawingView second = traversal.AddView(sheet);

        traversal.AddNote(first);
        traversal.AddNote(second);

        Assert.Equal("dnt:0001", Assert.Single(first.Notes).Id);
        Assert.Equal("dnt:0002", Assert.Single(second.Notes).Id);
        Assert.Equal(first.Id, first.Notes[0].OwnerId);
        Assert.Equal(second.Id, second.Notes[0].OwnerId);
    }

    // ---- revision tables -----------------------------------------------------------

    [Fact]
    public void AddRevisionTable_HangsOnTheSheetAndNamesIt()
    {
        // Enumerated per view (IView.GetTableAnnotations), recorded per sheet: two tables on
        // one sheet are two records, which is the whole reason ISheet.RevisionTable - which
        // returns at most one - is not the enumeration.
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord first = traversal.AddSheet("Sheet1", 0);
        DrawingSheetRecord second = traversal.AddSheet("Sheet2", 1);

        traversal.AddRevisionTable(first);
        traversal.AddRevisionTable(first);
        traversal.AddRevisionTable(second);

        Assert.Equal(
            new[] { "drv:0001", "drv:0002" }, first.RevisionTables.Select(table => table.Id));
        Assert.Equal(new[] { "drv:0003" }, second.RevisionTables.Select(table => table.Id));
        Assert.All(first.RevisionTables, table => Assert.Equal(first.Id, table.SheetId));
        Assert.Equal(second.Id, second.RevisionTables[0].SheetId);
    }

    // ---- ids across the package ----------------------------------------------------

    [Fact]
    public void Ids_AreAllocatedInTraversalOrderAcrossThePackage()
    {
        // One counter per prefix, never reset: dsh:0002 is the second sheet of this package
        // and of no other, which is what lets a finding cite a record by id.
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");

        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);
        DrawingView view = traversal.AddView(sheet);
        traversal.AddDimension(view);
        traversal.AddAnnotation(view);
        traversal.AddNote(view);
        traversal.AddRevisionTable(sheet);

        DrawingSheetRecord other = traversal.AddSheet("Sheet2", 1);
        DrawingView otherView = traversal.AddView(other);
        traversal.AddDimension(otherView);
        traversal.AddAnnotation(otherView);
        traversal.AddNote(otherView);
        traversal.AddRevisionTable(other);

        Assert.Equal(
            new[]
            {
                "dsh:0001", "dvw:0001", "ddm:0001", "dan:0001", "dnt:0001", "drv:0001",
                "dsh:0002", "dvw:0002", "ddm:0002", "dan:0002", "dnt:0002", "drv:0002",
            },
            new[]
            {
                sheet.Id, view.Id, view.DisplayDimensions[0].Id, view.Annotations[0].Id,
                view.Notes[0].Id, sheet.RevisionTables[0].Id,
                other.Id, otherView.Id, otherView.DisplayDimensions[0].Id,
                otherView.Annotations[0].Id, otherView.Notes[0].Id, other.RevisionTables[0].Id,
            });
    }

    [Fact]
    public void EveryRecord_StartsWithNoValueRead()
    {
        // The traversal allocates and orders; it never defaults engineering data. Every value
        // field starts null so that a read the dumper could not make stays unknown rather
        // than being written as an empty string or a zero (FR-026).
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");
        DrawingSheetRecord sheet = traversal.AddSheet("Sheet1", 0);
        DrawingView view = traversal.AddView(sheet);
        DisplayDimensionRecord dimension = traversal.AddDimension(view);
        DrawingAnnotation annotation = traversal.AddAnnotation(view);
        DrawingNote note = traversal.AddNote(view);
        RevisionTable table = traversal.AddRevisionTable(sheet);

        Assert.Null(sheet.SheetFormatName);
        Assert.Null(view.Name);
        Assert.Null(view.ViewTypeRaw);
        Assert.Null(view.ReferencedDocumentId);
        Assert.Null(view.ReferencedModelPath);
        Assert.Null(dimension.Name);
        Assert.Null(dimension.DimensionTypeRaw);
        Assert.Null(dimension.IsOverridden);
        Assert.Null(dimension.OverrideValue);
        Assert.Null(dimension.Value);
        Assert.Null(annotation.Name);
        Assert.Null(annotation.TypeRaw);
        Assert.Null(annotation.IsDangling);
        Assert.Null(note.Text);
        Assert.Null(table.CurrentRevisionRaw);
        Assert.Null(table.RowCount);
        Assert.Null(table.ColumnCount);
        Assert.Empty(table.Rows);

        // PROBE-10 has not answered which of the seven kinds SOLIDWORKS gives a reference
        // for, so every one of them starts null: the id is then a within-dump identity and
        // the page renders no Show control for it (contracts/ir-additions.md section 4).
        Assert.Null(sheet.PersistRef);
        Assert.Null(view.PersistRef);
        Assert.Null(dimension.PersistRef);
        Assert.Null(annotation.PersistRef);
        Assert.Null(note.PersistRef);
        Assert.Null(table.PersistRef);
    }

    [Fact]
    public void EveryAddMethod_RefusesANullOwner()
    {
        var traversal = new DrawingTraversal(DocumentId, "Sheet1");

        Assert.Throws<ArgumentNullException>(() => traversal.AddSheet(null!, 0));
        Assert.Throws<ArgumentNullException>(() => traversal.AddView(null!));
        Assert.Throws<ArgumentNullException>(() => traversal.AddDimension(null!));
        Assert.Throws<ArgumentNullException>(() => traversal.AddAnnotation(null!));
        Assert.Throws<ArgumentNullException>(() => traversal.AddNote(null!));
        Assert.Throws<ArgumentNullException>(() => traversal.AddRevisionTable(null!));
    }

    // ---- the referenced-model seam (T064) ------------------------------------------

    [Fact]
    public void ReferencedModels_KeepsSheetAndViewOrderAndNamesEachModelOnce()
    {
        // The list the drawing-rooted component traversal walks (contracts/ir-additions.md
        // section 7). A model two views reference is one subtree, not two.
        object housing = new object();
        object rail = new object();

        var references = new[]
        {
            new DrawingReference(@"C:\vault\housing.SLDPRT", housing),
            new DrawingReference(@"C:\vault\rail.SLDASM", rail),
            new DrawingReference(@"C:\vault\housing.SLDPRT", housing),
        };

        Assert.Equal(
            new[] { @"C:\vault\housing.SLDPRT", @"C:\vault\rail.SLDASM" },
            DrawingTraversal.ReferencedModels(references).Select(reference => reference.Path));
    }

    [Fact]
    public void ReferencedModels_TreatsOnePathSpelledTwoWaysAsOneModel()
    {
        // SOLIDWORKS reports the same file with either separator and either case depending on
        // how it was referenced; DocumentIds normalizes the same way, so a second spelling
        // would otherwise walk one document's tree twice under two keys.
        var references = new[]
        {
            new DrawingReference(@"C:\vault\housing.SLDPRT", new object()),
            new DrawingReference(@"c:/VAULT/Housing.sldprt", new object()),
        };

        Assert.Equal(
            @"C:\vault\housing.SLDPRT",
            Assert.Single(DrawingTraversal.ReferencedModels(references)).Path);
    }

    [Fact]
    public void ReferencedModels_KeepsTheLoadedHandleWhenOneSpellingCameBackUnloaded()
    {
        // Two views on one model, one of which answered null: the model IS loaded, so the
        // subtree is walked. Dropping it would cost that document every part and assembly
        // check on the strength of the weaker of two readings.
        object loaded = new object();

        var references = new[]
        {
            new DrawingReference(@"C:\vault\housing.SLDPRT", null),
            new DrawingReference(@"C:\vault\housing.SLDPRT", loaded),
        };

        Assert.Same(loaded, Assert.Single(DrawingTraversal.ReferencedModels(references)).Document);
    }

    [Fact]
    public void ReferencedModels_DropsAViewThatReferencesNothingAtAll()
    {
        // A detail view of the sheet format references no model and names none; that is not a
        // missing document and not a gap.
        var references = new[]
        {
            new DrawingReference(string.Empty, null),
            new DrawingReference("   ", null),
            new DrawingReference(@"C:\vault\housing.SLDPRT", new object()),
        };

        Assert.Equal(
            @"C:\vault\housing.SLDPRT",
            Assert.Single(DrawingTraversal.ReferencedModels(references)).Path);
    }

    [Fact]
    public void ReferencedModels_KeepsAModelThatIsNotLoaded()
    {
        // Recorded with a null handle rather than dropped: the path is what lets the
        // drawing_referenced_document gap name the model that was not loaded (FR-025).
        DrawingReference reference = Assert.Single(
            DrawingTraversal.ReferencedModels(
                new[] { new DrawingReference(@"C:\vault\housing.SLDPRT", null) }));

        Assert.Null(reference.Document);
        Assert.Equal(@"C:\vault\housing.SLDPRT", reference.Path);
    }

    // ---- the purity rule -----------------------------------------------------------

    [Fact]
    public void Signature_MentionsNoInteropType()
    {
        // research.md R9: "DrawingTraversal is a pure class that decides sheet, view and
        // entity order and allocates package ids, with no interop in its signature, so the
        // ordering rules are unit tested without a seat". This test is what makes that a
        // property of the build rather than a habit - a member that took an ISheet would
        // make every assertion above unreachable on a machine with no SOLIDWORKS.
        Type[] surface = typeof(DrawingTraversal).GetMethods()
            .SelectMany(method => method.GetParameters()
                .Select(parameter => parameter.ParameterType)
                .Concat(new[] { method.ReturnType }))
            .Concat(typeof(DrawingTraversal).GetConstructors()
                .SelectMany(constructor => constructor.GetParameters())
                .Select(parameter => parameter.ParameterType))
            .ToArray();

        Assert.DoesNotContain(
            surface,
            type => (type.Assembly.GetName().Name ?? string.Empty)
                .StartsWith("SolidWorks.Interop", StringComparison.Ordinal));
    }
}
