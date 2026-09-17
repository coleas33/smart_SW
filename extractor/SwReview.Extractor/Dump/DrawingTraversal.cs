using System;
using System.Collections.Generic;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T058. The order the <c>drawing</c> phase writes its records in, the package ids it gives
/// them, and which record owns which (schema 1.4.0, <c>research.md</c> R9).
///
/// <b>Pure: no interop type appears in any signature here</b>, and
/// <c>DrawingTraversalTests.Signature_MentionsNoInteropType</c> is what keeps it that way.
/// The phase itself reads a live <c>IDrawingDoc</c> that a machine with no SOLIDWORKS seat
/// cannot produce, so the rules a reader of a package actually depends on - sheet order,
/// id order, owner wiring - would otherwise be testable only on the pilot workstation.
/// <see cref="DrawingDumper"/> drives this class in <c>GetSheetNames()</c> and
/// <c>ISheet.GetViews()</c> order and fills in the values it read.
///
/// Two decisions are policy and live here rather than in the dumper:
///
///   * <b><c>was_active</c> is derived once, never read per sheet.</b> Nothing activates a
///     sheet (FR-044), so the only honest reading is "the name
///     <c>IDrawingDoc.GetCurrentSheet()</c> gave equals mine".
///   * <b>The sheet-format pseudo-view is a view.</b> <c>view_type_raw == 1</c> is where the
///     export-control note lives, and nothing here branches on it: it is allocated, ordered
///     and owned exactly like any other view, and Python names the number.
///
/// The six id allocators live on the instance rather than on <see cref="DumpScope"/>,
/// which is where <c>cut:</c> lives, because one package carries at most one drawing
/// record: the phase runs only for a drawing root and reads that one document, so one
/// traversal IS the package's allocation order for these six prefixes.
/// </summary>
public sealed class DrawingTraversal
{
    private readonly IdAllocator _sheetIds = new IdAllocator("dsh");
    private readonly IdAllocator _viewIds = new IdAllocator("dvw");
    private readonly IdAllocator _dimensionIds = new IdAllocator("ddm");
    private readonly IdAllocator _annotationIds = new IdAllocator("dan");
    private readonly IdAllocator _noteIds = new IdAllocator("dnt");
    private readonly IdAllocator _revisionTableIds = new IdAllocator("drv");

    private readonly string? _activeSheetName;

    /// <summary>
    /// Starts a traversal of the drawing document <paramref name="documentId"/> names.
    /// <paramref name="activeSheetName"/> is <c>GetCurrentSheet()</c>'s answer, or null when
    /// it could not be read - in which case no sheet is marked active, because guessing
    /// would make a sheet nobody looked at read as the one that was on screen.
    /// </summary>
    public DrawingTraversal(string documentId, string? activeSheetName)
    {
        if (string.IsNullOrWhiteSpace(documentId))
        {
            throw new ArgumentException(
                "A drawing record is keyed by its document id.", nameof(documentId));
        }

        _activeSheetName = activeSheetName;

        Record = new DrawingRecord
        {
            DocumentId = documentId,
            Source = DrawingEvidenceSource.Native,
            ActiveSheetName = activeSheetName,
        };
    }

    /// <summary>
    /// The record being built. Every <c>Add</c> below appends to it, so the record is the
    /// traversal's output and there is no second assembly step to disagree with this one.
    /// </summary>
    public DrawingRecord Record { get; }

    /// <summary>
    /// One sheet, in <c>GetSheetNames()</c> order.
    ///
    /// <paramref name="index"/> is that sheet's <b>position in <c>GetSheetNames()</c></b>,
    /// from 0 (<c>contracts/ir-additions.md</c> section 3.2), and is passed in rather than
    /// derived from <c>Record.Sheets.Count</c>: the dumper records no sheet for a listed name
    /// the <c>Sheet[name]</c> indexer will not answer for, so counting what was recorded would
    /// number the survivors of a three-sheet drawing 0 and 1 and make a finding cite "sheet 2"
    /// for the drawing's sheet 3. The id is still allocation order - <c>dsh:NNNN</c> is the
    /// package's numbering and says nothing about which sheet of the drawing it was.
    /// </summary>
    public DrawingSheetRecord AddSheet(string name, int index)
    {
        if (name == null)
        {
            throw new ArgumentNullException(nameof(name));
        }

        if (index < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(index), index, "A sheet's position in GetSheetNames() starts at 0.");
        }

        var sheet = new DrawingSheetRecord
        {
            Id = _sheetIds.Next(),
            Source = DrawingEvidenceSource.Native,
            Name = name,
            Index = index,

            // Ordinal: both names come from the same API on the same document in the same
            // call, so a difference in case is a difference in sheet, not in spelling.
            WasActive = _activeSheetName != null
                && string.Equals(name, _activeSheetName, StringComparison.Ordinal),
        };

        Record.Sheets.Add(sheet);
        return sheet;
    }

    /// <summary>One view of <paramref name="sheet"/>, in <c>ISheet.GetViews()</c> order.</summary>
    public DrawingView AddView(DrawingSheetRecord sheet)
    {
        if (sheet == null)
        {
            throw new ArgumentNullException(nameof(sheet));
        }

        var view = new DrawingView
        {
            Id = _viewIds.Next(),
            SheetId = sheet.Id,
        };

        sheet.Views.Add(view);
        return view;
    }

    /// <summary>One display dimension of <paramref name="view"/>.</summary>
    public DisplayDimensionRecord AddDimension(DrawingView view)
    {
        if (view == null)
        {
            throw new ArgumentNullException(nameof(view));
        }

        var dimension = new DisplayDimensionRecord
        {
            Id = _dimensionIds.Next(),
            ViewId = view.Id,
        };

        view.DisplayDimensions.Add(dimension);
        return dimension;
    }

    /// <summary>
    /// One annotation of <paramref name="view"/>. A sheet-format annotation's owner is the
    /// type-1 pseudo-view it was read from - not the sheet, and not the drawing
    /// (<c>contracts/ir-additions.md</c> section 3.5).
    /// </summary>
    public DrawingAnnotation AddAnnotation(DrawingView view)
    {
        if (view == null)
        {
            throw new ArgumentNullException(nameof(view));
        }

        var annotation = new DrawingAnnotation
        {
            Id = _annotationIds.Next(),
            OwnerId = view.Id,
        };

        view.Annotations.Add(annotation);
        return annotation;
    }

    /// <summary>One note of <paramref name="view"/>, owned by the view it was read from.</summary>
    public DrawingNote AddNote(DrawingView view)
    {
        if (view == null)
        {
            throw new ArgumentNullException(nameof(view));
        }

        var note = new DrawingNote
        {
            Id = _noteIds.Next(),
            OwnerId = view.Id,
        };

        view.Notes.Add(note);
        return note;
    }

    /// <summary>
    /// One revision table of <paramref name="sheet"/>. Tables are enumerated per view
    /// (<c>IView.GetTableAnnotations()</c>) and recorded per sheet, so a sheet carrying two
    /// of them carries two records - which is the whole reason the single-valued
    /// <c>ISheet.RevisionTable</c> is not the enumeration.
    /// </summary>
    public RevisionTable AddRevisionTable(DrawingSheetRecord sheet)
    {
        if (sheet == null)
        {
            throw new ArgumentNullException(nameof(sheet));
        }

        var table = new RevisionTable
        {
            Id = _revisionTableIds.Next(),
            SheetId = sheet.Id,
        };

        sheet.RevisionTables.Add(table);
        return table;
    }

    /// <summary>
    /// The models a drawing's views reference, once each, in sheet and view order: the list
    /// <see cref="ComponentTreeDumper"/> hangs one subtree per entry of for a drawing root
    /// (<c>contracts/ir-additions.md</c> section 7).
    ///
    /// A view that references nothing is dropped, because that is not a missing document. A
    /// model that is not loaded is <b>kept</b>, with a null handle: its path is what lets the
    /// <c>drawing_referenced_document</c> gap name it (FR-025). Two views on one model are
    /// one entry, matched on the path the way <see cref="Ids.DocumentIds"/> matches it, and
    /// the entry keeps whichever reading found a loaded document - a model IS loaded if any
    /// view says so, and grading it on the weaker of two readings would cost that document
    /// every part and assembly check.
    /// </summary>
    public static IReadOnlyList<DrawingReference> ReferencedModels(
        IEnumerable<DrawingReference> references)
    {
        if (references == null)
        {
            throw new ArgumentNullException(nameof(references));
        }

        var order = new List<string>();
        var byPath = new Dictionary<string, DrawingReference>(StringComparer.Ordinal);

        foreach (DrawingReference reference in references)
        {
            if (reference == null || string.IsNullOrWhiteSpace(reference.Path))
            {
                continue;
            }

            string key = NormalizePath(reference.Path);
            if (!byPath.TryGetValue(key, out DrawingReference first))
            {
                order.Add(key);
                byPath[key] = reference;
                continue;
            }

            if (first.Document == null && reference.Document != null)
            {
                byPath[key] = new DrawingReference(first.Path, reference.Document);
            }
        }

        var models = new List<DrawingReference>(order.Count);
        foreach (string key in order)
        {
            models.Add(byPath[key]);
        }

        return models;
    }

    /// <summary>
    /// Lowercase with backslash separators, exactly as <see cref="Ids.DocumentIds"/>
    /// normalizes a path before hashing it: two spellings that produce one document id must
    /// produce one subtree.
    /// </summary>
    private static string NormalizePath(string path) =>
        path.Trim().Replace('/', '\\').ToLowerInvariant();
}

/// <summary>
/// One model a drawing view references: the path <c>IView.GetReferencedModelName()</c> gave,
/// and the document <c>IView.ReferencedDocument</c> gave - null when the model is referenced
/// but not loaded.
///
/// The document is typed <c>object</c> so this file keeps no interop in its signature; the
/// only thing that reads it is the SOLIDWORKS side.
/// </summary>
public sealed class DrawingReference
{
    public DrawingReference(string path, object? document)
    {
        Path = path ?? throw new ArgumentNullException(nameof(path));
        Document = document;
    }

    /// <summary>The referenced model's full path, verbatim.</summary>
    public string Path { get; }

    /// <summary>The loaded <c>IModelDoc2</c>, or null when the model is not loaded.</summary>
    public object? Document { get; }
}

/// <summary>
/// What the drawing-rooted component traversal needs SOLIDWORKS to answer: which models the
/// open drawing's views reference, and which of them are loaded.
///
/// It is its own seam rather than part of <see cref="IDrawingReader"/> because it is needed
/// at a different time - <see cref="ComponentTreeDumper.Traverse"/> runs before any phase,
/// and the <c>drawing</c> phase runs sixth - and because the tree dumper has no business
/// holding the whole drawing-reading surface to ask one question.
///
/// <b>Nothing is opened, loaded, resolved or activated to answer it</b> (FR-044).
/// </summary>
public interface IDrawingReferenceSource
{
    /// <summary>
    /// Every model a view on any sheet of the open drawing references, in sheet and view
    /// order, with duplicates left in - <see cref="DrawingTraversal.ReferencedModels"/>
    /// decides what one model is.
    /// </summary>
    IReadOnlyList<DrawingReference> ReferencedModels();
}
