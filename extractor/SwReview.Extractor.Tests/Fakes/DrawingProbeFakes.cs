using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Probes;
using IrMeasure = SwReview.Extractor.Ir.Measure;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// The fictional design <c>probe drawings</c> is tested on (feature 011 T080): a two-sheet drawing
/// of one part, with every kind of record the probes print, and the part's own extraction. Every
/// string the report must never carry - a path, a file or sheet name, a note, a cell, a property
/// value, a persistent reference - carries the <see cref="Private"/> marker or is listed in
/// <see cref="Forbidden"/>, so one scan of the report proves it printed ids and numbers only.
/// </summary>
internal static class ProbeFixture
{
    public const string Private = "PRIVATE";
    public const string Folder = @"C:\Fictional\PRIVATE-folder";
    public const string DrawingPath = Folder + @"\PRIVATE-knuckle.SLDDRW";
    public const string PartPath = Folder + @"\PRIVATE-knuckle.SLDPRT";
    public const string OtherPartPath = Folder + @"\PRIVATE-spigot.SLDPRT";
    public const string FaceReference = "UFJJVkFURS1GQUNF";
    public const string EdgeFaceReference = "RURHRS1GQUNFLVJFRg==";
    public const string UnmatchedReference = "Tk8tTUFUQ0gtUkVG";
    public const string SheetA = "PRIVATE-SHEET-A";
    public const string SheetB = "PRIVATE-SHEET-B";

    public static string DrawingId => DocumentIds.For(DrawingPath);

    public static string PartId => DocumentIds.For(PartPath);

    public static string OtherPartId => DocumentIds.For(OtherPartPath);

    /// <summary>Everything the report must not contain.</summary>
    public static IReadOnlyList<string> Forbidden() => new[]
    {
        Private, "Fictional", "FICTIONAL", "knuckle", "spigot", ".slddrt", FaceReference, EdgeFaceReference,
        UnmatchedReference, "Sketch1", "Cut-Extrude", "MyBore",
    };

    /// <summary>The drawing's Standards extraction: phases, gaps and one drawing record.</summary>
    public static EvidencePackage DrawingPackage()
    {
        var package = NewPackage(DrawingPath, DocumentKind.Drawing, DumpProfile.Standards);
        AddDocument(package, PartPath, DocumentKind.Part);
        AddDocument(package, OtherPartPath, DocumentKind.Part);

        foreach ((string name, DumpPhaseStatus status, int? ms) in new (string, DumpPhaseStatus, int?)[]
        {
            ("document", DumpPhaseStatus.Ok, 5), ("manifest", DumpPhaseStatus.Ok, 1), ("mate", DumpPhaseStatus.Ok, 0),
            ("feature", DumpPhaseStatus.Ok, 12), ("equation", DumpPhaseStatus.Ok, 2), ("cutlist", DumpPhaseStatus.Ok, 3),
            ("drawing", DumpPhaseStatus.Ok, 40), ("hole", DumpPhaseStatus.Skipped, null),
            ("tolerance", DumpPhaseStatus.Skipped, null), ("fastener", DumpPhaseStatus.Skipped, null),
            ("face", DumpPhaseStatus.Skipped, null), ("body", DumpPhaseStatus.Skipped, null),
        })
        {
            package.Extractor.Phases.Add(new DumpPhase { Name = name, Status = status, ElapsedMs = ms });
        }

        package.Gaps.Add(Gap(GapKind.NotExtracted, "drawing_sheet_views", "dsh:0002", "sheet 'PRIVATE-SHEET-B' views"));
        package.Gaps.Add(Gap(GapKind.NotExtracted, "drawing_sheet_views", "dsh:0002", "again 'PRIVATE-SHEET-B'"));
        package.Gaps.Add(Gap(GapKind.Unsupported, "drawing_attachment", "ddm:0002", "1 vertex of PRIVATE dropped"));
        package.Gaps.Add(Gap(GapKind.Unsupported, "drawing_attachment", "dan:0004", "an entity of PRIVATE dropped"));

        package.DrawingRecords = new List<DrawingRecord> { Record() };
        return package;
    }

    /// <summary>The part's own (Full) extraction: two model dimensions and the faces its holes name.</summary>
    public static EvidencePackage PartPackage()
    {
        var package = NewPackage(PartPath, DocumentKind.Part, DumpProfile.Full);
        package.ModelDimensions = new List<ModelDimension>
        {
            new ModelDimension
            {
                Id = "mdm:0001", DocumentId = PartId, FeatureName = "Sketch1", Name = "D1@Sketch1@PRIVATE-knuckle.SLDPRT",
                ToleranceTypeRaw = 4,
                Tolerance = Tol(ToleranceKind.Bilateral, 0.00005, -0.00002),
            },
            new ModelDimension
            {
                Id = "mdm:0002", DocumentId = PartId, FeatureName = "Cut-Extrude1", Name = "MyBore@Cut-Extrude1",
                ToleranceTypeRaw = 0, FitHoleClass = "H7",
            },
        };
        package.Faces.Add(new FaceGeometry
        {
            Id = "fac:0001", PersistRef = FaceReference, PersistRefScope = PartId, Kind = FaceKind.Cylinder,
            Cylinder = new CylinderSurface { RadiusM = 0.005 },
        });
        package.Faces.Add(new FaceGeometry
        {
            Id = "fac:0002", PersistRef = EdgeFaceReference, PersistRefScope = PartId, Kind = FaceKind.Plane,
        });
        return package;
    }

    /// <summary>
    /// Sheet 1 (active): the sheet-format view and a view of the part with a diameter, a hole
    /// callout, a GTol, a datum, a surface finish and a note. Sheet 2: an out-of-date view of the
    /// part, a bill of materials and a revision table.
    /// </summary>
    public static DrawingRecord Record()
    {
        var formatView = new DrawingView { Id = "dvw:0001", SheetId = "dsh:0001", ViewTypeRaw = 1 };
        var partView = new DrawingView
        {
            Id = "dvw:0002", SheetId = "dsh:0001", Name = "PRIVATE-VIEW", ViewTypeRaw = 7,
            ReferencedDocumentId = PartId, ReferencedModelPath = PartPath, ReferencedConfiguration = "PRIVATE-CONFIG",
            IsModelOutOfDate = false, IsModelLoaded = true, ScaleDecimal = 0.5,
        };
        partView.DisplayDimensions.Add(new DisplayDimensionRecord
        {
            Id = "ddm:0001", ViewId = "dvw:0002", Name = "D1@Sketch1@PRIVATE-knuckle.SLDPRT", DimensionTypeRaw = 6,
            Value = new IrMeasure(0.01, "m"), PrecisionRaw = 2, TolerancePrecisionRaw = 3, UsesDocumentPrecision = false,
            UnitsRaw = 0, UsesDocumentUnits = true, ToleranceTypeRaw = 4,
            Tolerance = Tol(ToleranceKind.Bilateral, 0.00005, -0.00002), IsReference = false, DrivenStateRaw = 1,
            AttachedFaces = new List<AttachedFace>
            {
                new AttachedFace { PersistRef = FaceReference, Scope = PartId, Via = AttachedVia.Face },
            },
        });
        partView.DisplayDimensions.Add(new DisplayDimensionRecord
        {
            Id = "ddm:0002", ViewId = "dvw:0002", Name = "MyBore@Cut-Extrude1@PRIVATE-knuckle.SLDPRT",
            DimensionTypeRaw = 6, IsHoleCallout = true,
            HoleCalloutVariablesRaw = new List<string> { "<MOD-DIAM>=10.00", "<HOLE-DEPTH>=5.00" },
            TextPrefix = "PRIVATE-PREFIX", TextSuffix = string.Empty, TextAbove = "2X", TextBelow = null,
            ToleranceTypeRaw = 0, Tolerance = new Tolerance { Kind = ToleranceKind.None }, FitHoleClass = "H8",
            AttachedFaces = new List<AttachedFace>
            {
                new AttachedFace { PersistRef = EdgeFaceReference, Scope = PartId, Via = AttachedVia.Edge },
                new AttachedFace { PersistRef = UnmatchedReference, Scope = PartId, Via = AttachedVia.Edge },
            },
        });
        partView.Annotations.Add(new DrawingAnnotation
        {
            Id = "dan:0001", OwnerId = "dvw:0002", Name = "PRIVATE-GTOL", TypeRaw = 5,
            GtolFrames = new List<GtolFrame>
            {
                new GtolFrame { Number = 1, SymbolsRaw = { "<GTOL-POSI>" }, ValuesRaw = { "0.1", "A" } },
                new GtolFrame { Number = 2, SymbolsRaw = { "<GTOL-FLAT>" }, ValuesRaw = { "0.05" } },
            },
            DatumIdentifierRaw = "B",
            AttachedFaces = new List<AttachedFace>
            {
                new AttachedFace { PersistRef = FaceReference, Scope = PartId, Via = AttachedVia.Face },
            },
        });
        partView.Annotations.Add(new DrawingAnnotation
        {
            Id = "dan:0002", OwnerId = "dvw:0002", TypeRaw = 2, DatumLabel = "A",
        });
        partView.Annotations.Add(new DrawingAnnotation
        {
            Id = "dan:0003", OwnerId = "dvw:0002", TypeRaw = 7, SurfaceFinishSymbolRaw = 3,
            SurfaceFinishTextsRaw = new List<string> { "PRIVATE-RA", string.Empty },
        });
        partView.Annotations.Add(new DrawingAnnotation { Id = "dan:0004", OwnerId = "dvw:0002", TypeRaw = 6 });
        partView.Notes.Add(new DrawingNote { Id = "dnt:0001", OwnerId = "dvw:0002", Text = "PRIVATE NOTE TEXT" });

        var sheetA = new DrawingSheetRecord
        {
            Id = "dsh:0001", Name = SheetA, Index = 0, WasActive = true, SheetFormatName = "PRIVATE-FORMAT",
            SheetFormatPath = @"C:\Fictional\formats\PRIVATE-FORMAT.slddrt", ScaleNumerator = 1, ScaleDenominator = 2,
            FirstAngle = false,
        };
        sheetA.Views.Add(formatView);
        sheetA.Views.Add(partView);

        var staleView = new DrawingView
        {
            Id = "dvw:0003", SheetId = "dsh:0002", ViewTypeRaw = 4, ReferencedDocumentId = PartId,
            ReferencedModelPath = PartPath, IsModelOutOfDate = true, IsModelLoaded = false,
        };
        var sheetB = new DrawingSheetRecord { Id = "dsh:0002", Name = SheetB, Index = 1, WasActive = false };
        sheetB.Views.Add(staleView);
        sheetB.Tables = new List<DrawingTable>
        {
            new DrawingTable
            {
                Id = "dtb:0001", SheetId = "dsh:0002", OwnerViewId = "dvw:0003", TableTypeRaw = 2, Title = "PRIVATE-TITLE",
                RowCount = 2, ColumnCount = 3,
                Rows =
                {
                    new RevisionTableRow { Index = 0, Cells = { "PRIVATE ITEM", "PRIVATE PART NO", "QTY" } },
                    new RevisionTableRow { Index = 1, Cells = { "1", null, "2" } },
                },
                BomRows = new List<BomRow>
                {
                    new BomRow { Index = 1, DocumentIds = new List<string> { PartId }, UnresolvedPaths = new List<string> { OtherPartPath } },
                    new BomRow { Index = 2 },
                },
            },
        };
        sheetB.RevisionTables.Add(new RevisionTable
        {
            Id = "drv:0001", SheetId = "dsh:0002", CurrentRevisionRaw = "PRIVATE-REV", RowCount = 1, ColumnCount = 2,
            Rows = { new RevisionTableRow { Index = 0, Cells = { "PRIVATE-A", "PRIVATE-DATE" } } },
        });

        var record = new DrawingRecord
        {
            DocumentId = DrawingId, ActiveSheetName = SheetA, IsDetailingMode = false, LengthUnitRaw = 0,
            DimensionPrecisionRaw = 2, UnitsDecimalPlacesRaw = 3, TolerancePrecisionRaw = 2,
            DraftingStandardName = "PRIVATE-STANDARD",
        };
        record.Sheets.Add(sheetA);
        record.Sheets.Add(sheetB);
        return record;
    }

    public static Tolerance Tol(ToleranceKind kind, double upperM, double lowerM) => new Tolerance
    {
        Kind = kind,
        Upper = new IrMeasure(upperM, "m"),
        Lower = new IrMeasure(lowerM, "m"),
    };

    private static EvidencePackage NewPackage(string rootPath, DocumentKind kind, DumpProfile profile)
    {
        var package = new EvidencePackage
        {
            PackageId = Guid.NewGuid(),
            CreatedAt = DateTimeOffset.Now,
            Design = new Design
            {
                DesignId = DocumentIds.DesignId(rootPath),
                Name = "PRIVATE-design",
                RootAssemblyDocumentId = DocumentIds.For(rootPath),
                ActiveConfiguration = string.Empty,
            },
        };
        package.Extractor.Profile = profile;
        AddDocument(package, rootPath, kind);
        return package;
    }

    private static void AddDocument(EvidencePackage package, string path, DocumentKind kind) =>
        package.Documents.Add(new Document
        {
            DocumentId = DocumentIds.For(path),
            Kind = kind,
            FileName = System.IO.Path.GetFileName(path),
            Path = path,
            ActiveConfiguration = string.Empty,
        });

    private static Gap Gap(GapKind kind, string entityKind, string? entityId, string reason) =>
        new Gap { Kind = kind, EntityKind = entityKind, EntityId = entityId, Reason = reason };
}

/// <summary>A millisecond clock that advances by <see cref="Step"/> each time it is read.</summary>
internal sealed class FakeClock
{
    private long _now;

    public long Step { get; set; } = 25;

    public long Read()
    {
        long now = _now;
        _now += Step;
        return now;
    }
}

/// <summary>The documents SOLIDWORKS has open, as discovery's seam lists them.</summary>
internal sealed class FakeOpenDocuments : IOpenDrawingSource
{
    public List<OpenDocument> Documents { get; } = new List<OpenDocument>();

    public Exception? ListingFailure { get; set; }

    public OpenDocument Add(DocumentKind kind, string path, params string[] referenced)
    {
        var document = new OpenDocument(new object(), () => kind, () => path, () => referenced);
        Documents.Add(document);
        return document;
    }

    public IReadOnlyList<OpenDocument> OpenDocuments() => ListingFailure != null ? throw ListingFailure : Documents;

    public bool FileExists(string path) => false;
}

/// <summary>The reads the probe makes beyond the extraction, with canned answers.</summary>
internal sealed class FakeDrawingProbeReads : IDrawingProbeReads
{
    private int _activeReads;

    public List<string> Calls { get; } = new List<string>();

    /// <summary>What successive active-sheet reads answer; the last one repeats.</summary>
    public List<string?> ActiveSheets { get; } = new List<string?> { ProbeFixture.SheetA };

    public Exception? ActiveSheetFailure { get; set; }

    public IReadOnlyList<IReadOnlyList<int>> ViewTypes { get; set; } = new[] { new[] { 1, 7 }, new[] { 1, 4 } };

    public Exception? ViewTypesFailure { get; set; }

    public IReadOnlyList<int?> PropertyCounts { get; set; } = new int?[] { 9, null };

    public Exception? PropertyCountsFailure { get; set; }

    public Dictionary<int, int> Preferences { get; } = new Dictionary<int, int> { [13] = 2 };

    public IReadOnlyList<HoleCalloutText> WholeTexts { get; set; } = new[]
    {
        new HoleCalloutText(1, 2, 2, 42, null),
        new HoleCalloutText(2, 1, 1, null, "COMException 0x80004005"),
    };

    public Exception? WholeTextsFailure { get; set; }

    public HashSet<object> Hidden { get; } = new HashSet<object>();

    public HashSet<object> VisibilityFails { get; } = new HashSet<object>();

    public HashSet<string> OpenPaths { get; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ProbeFixture.OtherPartPath };

    public string? ActiveSheetName(object document)
    {
        Calls.Add(nameof(ActiveSheetName));
        if (ActiveSheetFailure != null)
        {
            throw ActiveSheetFailure;
        }

        return ActiveSheets[Math.Min(_activeReads++, ActiveSheets.Count - 1)];
    }

    public IReadOnlyList<IReadOnlyList<int>> DocumentViewTypes(object document)
    {
        Calls.Add(nameof(DocumentViewTypes));
        return ViewTypesFailure != null ? throw ViewTypesFailure : ViewTypes;
    }

    public IReadOnlyList<int?> SheetPropertyCounts(object document)
    {
        Calls.Add(nameof(SheetPropertyCounts));
        return PropertyCountsFailure != null ? throw PropertyCountsFailure : PropertyCounts;
    }

    public int UserPreferenceInteger(object document, int preference)
    {
        Calls.Add(nameof(UserPreferenceInteger) + " " + preference);
        return Preferences.TryGetValue(preference, out int value)
            ? value
            : throw new System.Runtime.InteropServices.COMException("no such preference", unchecked((int)0x80020003));
    }

    public IReadOnlyList<HoleCalloutText> HoleCalloutWholeTexts(object document)
    {
        Calls.Add(nameof(HoleCalloutWholeTexts));
        return WholeTextsFailure != null ? throw WholeTextsFailure : WholeTexts;
    }

    public bool Visible(object document)
    {
        Calls.Add(nameof(Visible));
        if (VisibilityFails.Contains(document))
        {
            throw new System.Runtime.InteropServices.COMException("visible", unchecked((int)0x80004005));
        }

        return !Hidden.Contains(document);
    }

    public bool IsOpen(string path)
    {
        Calls.Add(nameof(IsOpen));
        return OpenPaths.Contains(path);
    }
}

/// <summary>The file seam, with the states before and after the probe.</summary>
internal sealed class FakeProbeFiles : IProbeFiles
{
    private int _reads;
    private int _entries;

    public static readonly DateTime Written = new DateTime(2026, 9, 1, 8, 0, 0, DateTimeKind.Utc);

    public List<string> Calls { get; } = new List<string>();

    public HashSet<string> Existing { get; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    public ProbeFileState Before { get; set; } = new ProbeFileState(123456, Written, new string('a', 64));

    /// <summary>What the second read answers; null answers <see cref="Before"/> again.</summary>
    public ProbeFileState? After { get; set; }

    public Exception? ReadFailure { get; set; }

    public Exception? ExclusiveFailure { get; set; }

    public Exception? ExistsFailure { get; set; }

    public ProbeFileEntry EntryBefore { get; set; } = new ProbeFileEntry(true, 123456, Written, 0x20);

    public ProbeFileEntry? EntryAfter { get; set; }

    public bool Exists(string path)
    {
        Calls.Add("Exists");
        return ExistsFailure != null ? throw ExistsFailure : Existing.Contains(path);
    }

    public ProbeFileEntry Entry(string path)
    {
        Calls.Add("Entry");
        return _entries++ == 0 ? EntryBefore : EntryAfter ?? EntryBefore;
    }

    public ProbeFileState Read(string path)
    {
        Calls.Add("Read");
        if (ReadFailure != null)
        {
            throw ReadFailure;
        }

        return _reads++ == 0 ? Before : After ?? Before;
    }

    public void OpenExclusive(string path)
    {
        Calls.Add("OpenExclusive");
        if (ExclusiveFailure != null)
        {
            throw ExclusiveFailure;
        }
    }
}

/// <summary>
/// SOLIDWORKS as probe D14 sees it: the confirmed open's seam (<see cref="FakeDrawingOpenHost"/>,
/// the one its own tests drive) plus the engineer's session around it - the active document, the
/// window with the focus, the open documents and their save flags - and what opening the drawing
/// does to them when a test says it misbehaves.
/// </summary>
internal sealed class FakeDrawingOpenProbeHost : IDrawingOpenProbeHost
{
    private readonly List<object> _documents = new List<object>();
    private readonly Dictionary<object, string> _paths = new Dictionary<object, string>();
    private readonly HashSet<object> _raised = new HashSet<object>();
    private object? _drawing;

    public FakeDrawingOpenProbeHost()
    {
        Engineer = AddDocument(ProbeFixture.PartPath);
    }

    public FakeDrawingOpenHost Seam { get; } = new FakeDrawingOpenHost();

    /// <summary>The engineer's part, the active document.</summary>
    public object Engineer { get; }

    public long EngineerWindow { get; set; } = 1001;

    public bool ActivatesTheDrawing { get; set; }

    public bool StealsFocus { get; set; }

    public bool RaisesTheEngineersSaveFlag { get; set; }

    /// <summary>The documents the drawing loads when it opens; they stay loaded after it closes.</summary>
    public List<string> LoadsModels { get; } = new List<string>();

    public List<string> Reads { get; } = new List<string>();

    public object AddDocument(string path, bool saveFlag = false)
    {
        var document = new object();
        _documents.Add(document);
        _paths[document] = path;
        if (saveFlag)
        {
            _raised.Add(document);
        }

        return document;
    }

    /// <summary>The drawing open before the probe runs, as the engineer left it.</summary>
    public void AlreadyOpen(string path)
    {
        object document = Seam.AlreadyOpen(path);
        _documents.Add(document);
        _paths[document] = path;
    }

    public object? OpenDocument(string path) => Seam.OpenDocument(path);

    public void DocumentVisible(bool visible, int documentType) => Seam.DocumentVisible(visible, documentType);

    public object? OpenDoc6(string path, int documentType, int options, string configuration, out int errors, out int warnings)
    {
        object? opened = Seam.OpenDoc6(path, documentType, options, configuration, out errors, out warnings);
        if (opened != null)
        {
            _drawing = opened;
            _documents.Add(opened);
            _paths[opened] = path;
            foreach (string model in LoadsModels)
            {
                AddDocument(model);
            }

            if (RaisesTheEngineersSaveFlag)
            {
                _raised.Add(Engineer);
            }
        }

        return opened;
    }

    public void CloseDoc(string path)
    {
        Seam.CloseDoc(path);
        if (_drawing != null)
        {
            _documents.Remove(_drawing);
            _drawing = null;
        }
    }

    public object? ActiveDocument()
    {
        Reads.Add(nameof(ActiveDocument));
        return ActivatesTheDrawing && _drawing != null ? _drawing : Engineer;
    }

    public IReadOnlyList<object> Documents()
    {
        Reads.Add(nameof(Documents));
        return _documents.ToList();
    }

    public string? PathOf(object document)
    {
        Reads.Add(nameof(PathOf));
        return _paths[document];
    }

    public bool SaveFlagOf(object document)
    {
        Reads.Add(nameof(SaveFlagOf));
        return _raised.Contains(document);
    }

    public long ForegroundWindow() => StealsFocus && _drawing != null ? 4242 : EngineerWindow;
}
