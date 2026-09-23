using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// A review's package as the confirmed read finds it in its run folder (feature 011,
/// contracts/confirmed-open.md section 2): an assembly of a housing and a pin, one drawing already
/// attached - numbered from 0001 in every drawing id prefix - and a candidate beside each part.
/// Fictional paths only.
/// </summary>
internal static class ConfirmedDrawingPackage
{
    public const string Folder = @"C:\Fictional\bracket";
    public const string AssemblyPath = Folder + @"\bracket-assy.SLDASM";
    public const string HousingPath = Folder + @"\housing.SLDPRT";
    public const string PinPath = Folder + @"\pin.SLDPRT";
    public const string RootDrawingPath = Folder + @"\bracket-assy.SLDDRW";
    public const string HousingDrawingPath = Folder + @"\housing.SLDDRW";
    public const string PinDrawingPath = Folder + @"\pin.SLDDRW";

    public static string AssemblyId => DocumentIds.For(AssemblyPath);

    public static string HousingId => DocumentIds.For(HousingPath);

    public static string PinId => DocumentIds.For(PinPath);

    public static string RootDrawingId => DocumentIds.For(RootDrawingPath);

    /// <summary>The package, with <paramref name="drawings"/> drawing records (the first the root's drawing).</summary>
    public static EvidencePackage Build(int drawings = 1)
    {
        var package = new EvidencePackage
        {
            PackageId = Guid.NewGuid(),
            CreatedAt = DateTimeOffset.Now,
            Design = new Design
            {
                DesignId = DocumentIds.DesignId(AssemblyPath),
                Name = "bracket-assy",
                RootAssemblyDocumentId = AssemblyId,
                ActiveConfiguration = "Default",
            },
        };

        AddDocument(package, AssemblyPath, DocumentKind.Assembly, "Default");
        AddDocument(package, HousingPath, DocumentKind.Part, "Default");
        AddDocument(package, PinPath, DocumentKind.Part, "Default");

        package.DrawingRecords = new List<DrawingRecord>();
        for (int n = 1; n <= drawings; n++)
        {
            string path = n == 1 ? RootDrawingPath : Folder + $@"\other-{n:00}.SLDDRW";
            AddDocument(package, path, DocumentKind.Drawing, string.Empty);
            package.Design.DrawingDocumentIds.Add(DocumentIds.For(path));
            package.DrawingRecords.Add(Record(DocumentIds.For(path), n));
        }

        package.DrawingCandidates = new List<DrawingCandidate>
        {
            new DrawingCandidate { DocumentId = HousingId, Path = HousingDrawingPath },
            new DrawingCandidate { DocumentId = PinId, Path = PinDrawingPath },
        };

        return package;
    }

    /// <summary>One drawing record numbered <paramref name="n"/> in every drawing id prefix.</summary>
    public static DrawingRecord Record(string documentId, int n)
    {
        string Id(string prefix) => $"{prefix}:{n:0000}";
        var view = new DrawingView { Id = Id("dvw"), SheetId = Id("dsh") };
        view.DisplayDimensions.Add(new DisplayDimensionRecord { Id = Id("ddm"), ViewId = view.Id });
        view.Annotations.Add(new DrawingAnnotation { Id = Id("dan"), OwnerId = view.Id });
        view.Notes.Add(new DrawingNote { Id = Id("dnt"), OwnerId = view.Id, Text = "FICTIONAL NOTE" });

        var sheet = new DrawingSheetRecord { Id = Id("dsh"), Name = "Sheet1", Index = 0, WasActive = true };
        sheet.Views.Add(view);
        sheet.RevisionTables.Add(new RevisionTable { Id = Id("drv"), SheetId = sheet.Id });
        sheet.Tables = new List<DrawingTable>
        {
            new DrawingTable { Id = Id("dtb"), SheetId = sheet.Id, OwnerViewId = view.Id, TableTypeRaw = 5 },
        };

        var record = new DrawingRecord { DocumentId = documentId, ActiveSheetName = "Sheet1" };
        record.Sheets.Add(sheet);
        return record;
    }

    private static void AddDocument(EvidencePackage package, string path, DocumentKind kind, string configuration)
    {
        string id = DocumentIds.For(path);
        package.Documents.Add(new Document
        {
            DocumentId = id,
            Kind = kind,
            FileName = System.IO.Path.GetFileName(path),
            Path = path,
            ActiveConfiguration = configuration,
        });
        package.Manifest.Entries.Add(new ManifestEntry
        {
            DocumentId = id,
            VaultPath = path,
            Configuration = configuration,
            ExportMethod = ExportMethod.Native,
        });
    }
}

/// <summary>
/// The drawing phase as the confirmed read calls it: one record per drawing the scope hands over,
/// numbered from the scope's allocators in every prefix - as <see cref="DrawingDumper"/> numbers
/// them - with one gap, or a throw.
/// </summary>
internal sealed class FakeConfirmedDrawingPhase : IDrawingSource
{
    public List<ScopedDrawing> Seen { get; } = new List<ScopedDrawing>();

    public Exception? Failure { get; set; }

    public int Sheets { get; set; } = 2;

    public IReadOnlyList<DrawingRecord> Dump(DumpScope scope)
    {
        Seen.AddRange(scope.Drawings);
        if (Failure != null)
        {
            throw Failure;
        }

        return scope.Drawings.Select(drawing =>
        {
            var record = new DrawingRecord { DocumentId = scope.DocumentId(drawing.DocumentPath), ActiveSheetName = "Sheet1" };
            for (int index = 0; index < Sheets; index++)
            {
                var sheet = new DrawingSheetRecord
                {
                    Id = scope.DrawingIds.Sheets.Next(),
                    Name = "Sheet" + (index + 1),
                    Index = index,
                    WasActive = index == 0,
                };
                var view = new DrawingView { Id = scope.DrawingIds.Views.Next(), SheetId = sheet.Id };
                view.DisplayDimensions.Add(new DisplayDimensionRecord { Id = scope.DrawingIds.Dimensions.Next(), ViewId = view.Id });
                view.Annotations.Add(new DrawingAnnotation { Id = scope.DrawingIds.Annotations.Next(), OwnerId = view.Id });
                view.Notes.Add(new DrawingNote { Id = scope.DrawingIds.Notes.Next(), OwnerId = view.Id, Text = "FICTIONAL NOTE" });
                sheet.Views.Add(view);
                sheet.RevisionTables.Add(new RevisionTable { Id = scope.DrawingIds.RevisionTables.Next(), SheetId = sheet.Id });
                sheet.Tables = new List<DrawingTable>
                {
                    new DrawingTable { Id = scope.DrawingIds.Tables.Next(), SheetId = sheet.Id, OwnerViewId = view.Id },
                };
                record.Sheets.Add(sheet);
            }

            scope.Gaps.Add(
                GapKind.NotExtracted,
                "drawing_referenced_document",
                record.Sheets[0].Views[0].Id,
                @"references 'C:\Fictional\other\unrelated.SLDPRT', which is not part of this review",
                null);
            return record;
        }).ToList();
    }
}

/// <summary>The document and manifest phases for the one drawing the confirmed read adds.</summary>
internal sealed class FakeConfirmedDrawingDocuments : IDocumentSource, IManifestSource
{
    public List<string> DocumentPathsAsked { get; } = new List<string>();

    public IReadOnlyList<Document> Dump(DumpScope scope, IReadOnlyList<string> documentPaths)
    {
        DocumentPathsAsked.AddRange(documentPaths);
        return documentPaths.Select(path => new Document
        {
            DocumentId = scope.DocumentId(path),
            Kind = DocumentKind.Drawing,
            FileName = System.IO.Path.GetFileName(path),
            Path = path,
            ActiveConfiguration = string.Empty,
        }).ToList();
    }

    public Manifest Build(DumpScope scope, IReadOnlyList<Document> documents)
    {
        var manifest = new Manifest();
        foreach (Document document in documents)
        {
            manifest.Entries.Add(new ManifestEntry
            {
                DocumentId = document.DocumentId,
                VaultPath = document.Path,
                Configuration = document.ActiveConfiguration,
                ExportMethod = ExportMethod.Native,
            });
        }

        return manifest;
    }
}
