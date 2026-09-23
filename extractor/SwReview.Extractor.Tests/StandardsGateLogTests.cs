using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Console;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T093, the C# half of the read-only proof (FR-044, SC-010, quickstart gate 11 and
/// Scenario 11): <b>a standards dump's</b> gate log - not one phase's - contains zero
/// mutating interop members and no sheet-activation member.
///
/// The per-phase tests already make that claim phase by phase
/// (<see cref="DrawingDumperTests"/>, <see cref="CutListDumperTests"/>). What only this file
/// can say is the sentence the quickstart asks an engineer to confirm from ONE log: the
/// phase set <see cref="PackageWriter"/> actually runs for <c>--profile standards</c> - over
/// an assembly root and over a drawing root, which run different phase sets - passed
/// <see cref="ReadOnlyGuard"/> end to end, with nothing refused and no sheet made active.
/// So the four phases that reach interop through a reader seam are the SHIPPED dumpers on
/// ONE gate and ONE <see cref="RecordingGateObserver"/>, and the union of what they asked
/// the gate is the log under test.
///
/// What this cannot cover, and why: the component-tree, document, manifest and mate phases
/// take an <c>ISwSession</c> and the <c>ISldWorks</c> pointer rather than a reader
/// interface, so they cannot run on a machine with no SOLIDWORKS seat. They are stubbed
/// here, contribute nothing to the log, and are covered on the gate by their own tests
/// (<see cref="ComponentTreeDumperTests"/>, <see cref="PropertyDumperTests"/>,
/// <see cref="ManifestBuilderTests"/>, <see cref="MateDumperTests"/>). The assertion below
/// that names a member per running phase is what keeps this from quietly becoming a test of
/// four stubs.
///
/// The mutating claim is asked of <see cref="ReadOnlyGuard"/> itself rather than of a typed
/// list, the same way <c>Program.IsMutating</c> does, so a member added to the denylist is
/// covered here the same day. The sheet-activation claim is the production list
/// <see cref="Program.StandardsProbeSheetActivationMembers"/>, because <c>SheetNext</c> and
/// <c>SheetPrevious</c> activate a sheet and are NOT on the denylist.
/// </summary>
public class StandardsGateLogTests : IDisposable
{
    private const string AssemblyPath = @"C:\vault\bracket-assy\bracket-assy.SLDASM";
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
    private const string DrawingPath = @"C:\vault\bracket-assy\bracket-assy.SLDDRW";

    /// <summary>
    /// One member per phase that really runs here, so "the log is clean" cannot be satisfied
    /// by a log that is clean because it is empty. Each is gated by the dumper itself - not
    /// by its reader - so a fake cannot supply it.
    /// </summary>
    private static readonly string[] MembersEachRunningPhaseGates =
    {
        "GetModelDoc2",          // feature, equation and cut-list phases
        "GetChildren",           // feature
        "GetEquationMgr",        // equation
        "ExcludeFromCutList",    // cutlist
        "GetBodyCount",          // cutlist
    };

    /// <summary>The same, for the phase only a drawing root adds.</summary>
    private static readonly string[] MembersTheDrawingPhaseGates =
    {
        "Sheet", "GetViews", "GetDisplayDimensions", "GetAnnotations", "GetNotes",
        "ITableAnnotation.Type", "RevisionTable",
    };

    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();
    private readonly string _outputDirectory =
        Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));

    public StandardsGateLogTests()
    {
        _gate.Observer = _observer;
    }

    public void Dispose()
    {
        if (Directory.Exists(_outputDirectory))
        {
            Directory.Delete(_outputDirectory, recursive: true);
        }
    }

    [Fact]
    public void StandardsDumpOverAnAssemblyRoot_LogsNoMutatingMemberAndNoSheetActivation()
    {
        EvidencePackage package = Dump(DocumentKind.Assembly);

        Assert.Equal(DumpProfile.Standards, package.Extractor.Profile);
        AssertTheLogIsReadOnly();
        AssertEveryRunningPhaseIsInTheLog(MembersEachRunningPhaseGates);

        // The drawing phase does not run for a model root (FR-025), so its members are not in
        // this log - which is what makes the drawing-root case below a second measurement
        // rather than a repeat of this one.
        Assert.DoesNotContain("GetViews", _observer.Members, StringComparer.OrdinalIgnoreCase);
    }

    [Fact]
    public void StandardsDumpOverADrawingRoot_LogsNoMutatingMemberAndNoSheetActivation()
    {
        EvidencePackage package = Dump(DocumentKind.Drawing);

        Assert.Equal(DumpProfile.Standards, package.Extractor.Profile);
        Assert.NotNull(package.DrawingRecords);
        AssertTheLogIsReadOnly();
        AssertEveryRunningPhaseIsInTheLog(
            MembersEachRunningPhaseGates.Concat(MembersTheDrawingPhaseGates).ToArray());
    }

    /// <summary>
    /// Feature 011 T015 (FR-001, FR-007, SC-001 at the desk): a drawing on its own, attached
    /// with no configuration, is extracted under the Standards profile and the whole dump's log
    /// holds no member the guard denies - the feature 011 drawing families included, since
    /// <see cref="ReadOnlyGuard.Assert"/> reads the generated table - and no member that opens
    /// or activates a document: the drawing was already open, and the extraction opens nothing.
    /// Here rather than in <see cref="PackageWriterTests"/> because this file already drives
    /// the shipped <see cref="DrawingDumper"/> through <see cref="PackageWriter"/> on one gate,
    /// and a third fake drawing reader would be a copy of this one.
    /// </summary>
    [Fact]
    public void StandardsDumpOverADrawingRootWithNoConfiguration_LogsNoDenialAndOpensNothing()
    {
        EvidencePackage package = Dump(DocumentKind.Drawing);

        Assert.Equal(string.Empty, package.Design.ActiveConfiguration);
        Assert.NotNull(package.DrawingRecords);
        AssertTheLogIsReadOnly();

        Assert.DoesNotContain(
            _observer.Members,
            member => member.StartsWith("OpenDoc", StringComparison.OrdinalIgnoreCase)
                || member.StartsWith("ActivateDoc", StringComparison.OrdinalIgnoreCase));
        foreach (string member in Program.StandardsProbeDocumentOpeningMembers)
        {
            Assert.DoesNotContain(member, _observer.Members, StringComparer.OrdinalIgnoreCase);
        }
    }

    [Fact]
    public void StandardsDumpOverADrawingRoot_ReadsEverySheetWithoutActivatingOne()
    {
        // The claim quickstart Scenario 11 turns on: a six-sheet drawing is read where it
        // stands. Two sheets, only one of them active, and the log still names no activation.
        EvidencePackage package = Dump(DocumentKind.Drawing, sheetNames: new[] { "Sheet1", "Sheet2" });

        DrawingRecord record = Assert.Single(package.DrawingRecords!);
        Assert.Equal(new[] { true, false }, record.Sheets.Select(sheet => sheet.WasActive));

        foreach (string member in Program.StandardsProbeSheetActivationMembers)
        {
            Assert.DoesNotContain(member, _observer.Members, StringComparer.OrdinalIgnoreCase);
        }
    }

    // ---- the two claims ------------------------------------------------------------

    /// <summary>
    /// Zero mutating members, zero refusals, and no sheet activation - over the whole dump's
    /// log rather than one phase's.
    /// </summary>
    private void AssertTheLogIsReadOnly()
    {
        Assert.NotEmpty(_observer.Members);

        // Derived from the shipped guard, never from a copy of the denylist: this is the
        // "zero mutating interop members" half of SC-010.
        Assert.All(_observer.Members, member => ReadOnlyGuard.Assert(member));

        // A refusal would mean the dump TRIED to write and the guard stopped it. The claim
        // is that it never tried.
        Assert.Empty(_observer.Refusals);

        foreach (string member in Program.StandardsProbeSheetActivationMembers)
        {
            Assert.DoesNotContain(member, _observer.Members, StringComparer.OrdinalIgnoreCase);
        }
    }

    /// <summary>
    /// The non-vacuity guard: every phase that runs here left its own gated member in the
    /// log, so a phase that silently stopped running would fail this rather than make the
    /// read-only claim easier to satisfy.
    /// </summary>
    private void AssertEveryRunningPhaseIsInTheLog(IReadOnlyList<string> members)
    {
        foreach (string member in members)
        {
            Assert.Contains(member, _observer.Members, StringComparer.Ordinal);
        }
    }

    // ---- the dump ------------------------------------------------------------------

    /// <summary>
    /// A standards-profile dump of one assembly (or of the drawing of it), through the
    /// shipped <see cref="PackageWriter"/> so the phase set is the profile's own decision
    /// and not this test's.
    /// </summary>
    private EvidencePackage Dump(DocumentKind rootKind, string[]? sheetNames = null)
    {
        var sources = new StubbedPhases(rootKind);
        var drawings = new FakeDrawingReader(sheetNames ?? new[] { "Sheet1" });

        var writer = new PackageWriter(
            sources,
            sources,
            sources,
            sources,
            new FeatureDumper(_gate, new FakeFeatureReader()),
            new EquationDumper(_gate, new FakeEquationReader()),
            cutList: new CutListDumper(_gate, new FakeCutListReader()),
            drawings: new DrawingDumper(_gate, drawings),
            sources,
            sources,
            sources,
            sources,
            "2024 SP5",
            "TEST-WORKSTATION");

        return writer.Build(new DumpOptions
        {
            OutputDirectory = Path.Combine(_outputDirectory, "native"),
            Profile = DumpProfile.Standards,
        });
    }

    /// <summary>
    /// The four phases that cannot run without a SOLIDWORKS seat, plus the four geometry
    /// phases the standards profile never runs. They touch no gate, which is stated here
    /// rather than left to be inferred: the log under test is the other four phases'.
    /// </summary>
    private sealed class StubbedPhases
        : IComponentTreeSource, IDocumentSource, IManifestSource, IMateSource,
          IHoleSource, IFastenerSource, IFaceSource, IMeshSource
    {
        private readonly DocumentKind _rootKind;

        public StubbedPhases(DocumentKind rootKind)
        {
            _rootKind = rootKind;
        }

        public ComponentTreeResult Traverse(GapCollector gaps, DumpOptions options)
        {
            bool drawing = _rootKind == DocumentKind.Drawing;

            var tree = new ComponentTreeResult
            {
                RootDocumentPath = drawing ? DrawingPath : AssemblyPath,
                RootDocumentKind = _rootKind,
                DesignName = "bracket-assy",

                // What the traversal records (feature 011, attach.md section 2): a drawing
                // session has no configuration, so a drawing root's is "".
                ActiveConfiguration = drawing ? string.Empty : "Default",

                // Feature 011 T009: the drawing phase reads each drawing through its own
                // document handle, and the traversal hands over the root's.
                RootDocument = new object(),
            };

            tree.Nodes.Add(new ComponentNode
            {
                Key = "housing-1",
                ParentKey = null,
                Name = "housing",
                DocumentPath = HousingPath,
                DocumentKind = DocumentKind.Part,
                ReferencedConfiguration = "Default",
                Transform = Transform.Identity(),
                Suppression = SuppressionState.Resolved,
                PersistRefScopePath = HousingPath,
                Handle = new object(),
            });

            return tree;
        }

        public IReadOnlyList<Document> Dump(DumpScope scope, IReadOnlyList<string> documentPaths) =>
            Array.Empty<Document>();

        public Manifest Build(DumpScope scope, IReadOnlyList<Document> documents) => new Manifest();

        IReadOnlyList<Mate> IMateSource.Dump(DumpScope scope) => Array.Empty<Mate>();

        HoleDumpResult IHoleSource.Dump(DumpScope scope) => new HoleDumpResult();

        IReadOnlyList<Fastener> IFastenerSource.Dump(DumpScope scope) => Array.Empty<Fastener>();

        IReadOnlyList<FaceGeometry> IFaceSource.Dump(DumpScope scope) => Array.Empty<FaceGeometry>();

        IReadOnlyList<BodyRef> IMeshSource.Dump(DumpScope scope, string meshDirectory) =>
            Array.Empty<BodyRef>();

        public IReadOnlyList<BodyRef> DumpComponent(
            DumpScope scope, ScopedComponent component, string meshDirectory) =>
            Array.Empty<BodyRef>();
    }

    // ---- the readers ---------------------------------------------------------------
    //
    // Minimal on purpose. Each phase's own test file owns the rich fake that exercises its
    // decisions; these exist only to make the shipped dumper reach the gate, which is the
    // one thing this file measures.

    private sealed class FakeFeatureReader : IFeatureReader
    {
        private readonly object _feature = new object();

        public object? Document(ScopedComponent component) => new object();

        public string ActiveConfiguration(object document) => "Default";

        public IReadOnlyList<FeatureTreeNode> Walk(object document) => new[]
        {
            new FeatureTreeNode
            {
                Name = "Boss-Extrude1", TypeName = "Extrusion", Handle = _feature,
            },
        };

        public string? Description(object feature) => null;

        public int ErrorCode(object feature) => 0;

        public bool Suppressed(object feature, string configuration) => false;

        public IReadOnlyList<object> Children(object feature) => Array.Empty<object>();

        public IReadOnlyList<object> Parents(object feature) => Array.Empty<object>();

        public object? Sketch(object feature) => null;

        public int SketchConstrainedStatus(object sketch) => 0;

        public object? SketchTextSegments(object sketch) => null;

        public object? Definition(object feature) => null;

        public FilletDefinitionKind ClassifyFillet(object definition) =>
            FilletDefinitionKind.NotAFillet;

        public double SimpleFilletDefaultRadius(object definition) => 0d;

        // Non-null on purpose: FeatureDumper records no row for a feature SOLIDWORKS would
        // not give a persistent reference for, and a null here would stop the phase before
        // it reached the gate at all.
        public ScopedPersistRef? PersistRef(object document, object feature) =>
            new ScopedPersistRef("AAECAwQ=", "doc:0001", HousingPath);
    }

    private sealed class FakeEquationReader : IEquationReader
    {
        public object? Document(ScopedComponent component) => new object();

        public object? Manager(object document) => new object();

        public int Count(object manager) => 1;

        public string? Text(object manager, int index) => "\"Width\" = 100";

        public bool GlobalVariable(object manager, int index) => true;

        public double Value(object manager, int index) => 100d;
    }

    private sealed class FakeCutListReader : ICutListReader
    {
        private readonly object _folder = new object();
        private readonly object _item = new object();
        private readonly object _bodyFolder = new object();

        public object? Document(ScopedComponent component) => new object();

        public string ActiveConfiguration(object document) => "Default";

        public IReadOnlyList<object> Features(object document) => new[] { _folder };

        public IReadOnlyList<object> SubFeatures(object feature) =>
            ReferenceEquals(feature, _folder) ? new[] { _item } : Array.Empty<object>();

        public string Name(object feature) =>
            ReferenceEquals(feature, _folder) ? "Cut list(1)" : "Cut-List-Item1";

        public string TypeName(object feature) => "CutListFolder";

        public object? BodyFolder(object feature) => _bodyFolder;

        public int BodyCount(object bodyFolder) => 1;

        public bool ExcludedFromCutList(object feature) => false;

        public ScopedPersistRef? PersistRef(object document, object feature) => null;
    }

    /// <summary>
    /// One sheet per name, each with one view carrying one dimension, one annotation, one
    /// note and one revision table - enough for every read the drawing phase makes to
    /// happen at least once. The first sheet is the active one, so a second name is a
    /// non-active sheet read where it stands.
    /// </summary>
    private sealed class FakeDrawingReader : IDrawingReader
    {
        private readonly object _drawing = new object();
        private readonly object _view = new object();
        private readonly object _dimension = new object();
        private readonly object _annotation = new object();
        private readonly object _note = new object();
        private readonly object _table = new object();
        private readonly string[] _sheetNames;
        private readonly Dictionary<string, object> _sheets =
            new Dictionary<string, object>(StringComparer.Ordinal);

        public FakeDrawingReader(string[] sheetNames)
        {
            _sheetNames = sheetNames;
            foreach (string name in sheetNames)
            {
                _sheets[name] = new object();
            }
        }

        public object? Drawing(object document) => _drawing;

        public string? ActiveSheetName(object drawing) => _sheetNames[0];

        public IReadOnlyList<string> SheetNames(object drawing) => _sheetNames;

        public object? Sheet(object drawing, string name) =>
            _sheets.TryGetValue(name, out object? sheet) ? sheet : null;

        public string? SheetName(object sheet) =>
            _sheets.First(pair => ReferenceEquals(pair.Value, sheet)).Key;

        public string? SheetFormatName(object sheet) => "A3 - ISO";

        public IReadOnlyList<object> Views(object sheet) => new[] { _view };

        public object? SheetRevisionTable(object sheet) => _table;

        public string? ViewName(object view) => "Drawing View1";

        public int ViewType(object view) => 2;

        public string? ReferencedModelPath(object view) => HousingPath;

        public object? ReferencedDocument(object view) => null;

        public string? DocumentPath(object document) => HousingPath;

        public IReadOnlyList<object> DisplayDimensions(object view) => new[] { _dimension };

        public IReadOnlyList<object> Annotations(object view) => new[] { _annotation };

        public IReadOnlyList<object> Notes(object view) => new[] { _note };

        public IReadOnlyList<object> TableAnnotations(object view) => new[] { _table };

        public int TableAnnotationType(object table) => 3;

        public string? DimensionName(object dimension) => "D1@Sketch1";

        public int DimensionType(object dimension) => 2;

        public bool IsOverridden(object dimension) => false;

        public double OverrideValue(object dimension) => 0d;

        public double DimensionValue(object dimension) => 0.05d;

        public string? AnnotationName(object annotation) => "RC1";

        public int AnnotationType(object annotation) => 6;

        public bool IsDangling(object annotation) => false;

        public string? NoteText(object note) => "UNLESS OTHERWISE SPECIFIED";

        public string? CurrentRevision(object table) => "B";

        public RevisionTableShape TableShape(object table) => new RevisionTableShape(1, 2);

        public string? Cell(object table, int row, int column) => "B";

        public ScopedPersistRef? PersistRef(object document, object entity) => null;

        // Feature 011 (IR 1.6.0): every new read answers, so the drawing phase reaches each one's
        // gate and the log under test carries it.

        public bool IsDetailingMode(object drawing) => false;

        public int UserPreferenceInteger(object document, int preference) => 0;

        public string? UserPreferenceString(object document, int preference) => "FICTIONAL-STANDARD";

        public string? SheetTemplateName(object sheet) => @"C:\Fictional\Formats\FICTIONAL-FORMAT-A.slddrt";

        public IReadOnlyList<double>? SheetProperties(object sheet) => new[] { 12d, 0d, 1d, 1d, 0d, 0.42, 0.297 };

        public string? ReferencedConfiguration(object view) => "Default";

        public bool IsModelOutOfDate(object view) => false;

        public bool IsModelLoaded(object view) => true;

        public double ScaleDecimal(object view) => 1d;

        public string? OrientationName(object view) => "*Front";

        public string? DimensionText(object dimension, int part) => string.Empty;

        public int PrimaryPrecision(object dimension) => 2;

        public int PrimaryTolerancePrecision(object dimension) => 3;

        public bool UsesDocumentPrecision(object dimension) => true;

        public int Units(object dimension) => 0;

        public bool UsesDocumentUnits(object dimension) => true;

        public object? DimensionOf(object dimension) => dimension;

        public bool IsReferenceDimension(object dimension) => false;

        public int DrivenState(object modelDimension) => 1;

        public bool IsHoleCallout(object dimension) => false;

        public IReadOnlyList<string>? HoleCalloutVariables(object dimension) => null;

        public object? DimensionAnnotation(object dimension) => _annotation;

        public IReadOnlyList<object?> AttachedEntities(object annotation) => new object?[] { _dimension };

        public object? CorrespondingEntity(object view, object entity) => _face;

        public AttachedEntityKind EntityKind(object entity) =>
            ReferenceEquals(entity, _face) ? AttachedEntityKind.Face : AttachedEntityKind.Other;

        public IReadOnlyList<object> AdjacentFaces(object edge) => new[] { _face };

        public object? FaceDocument(object view, object face) => null;

        public object? Tolerance(object dimension) => _tolerance;

        public int ToleranceType(object tolerance) => 0;

        public double? ToleranceMin(object tolerance) => null;

        public double? ToleranceMax(object tolerance) => null;

        public string? HoleFitValue(object tolerance) => null;

        public string? ShaftFitValue(object tolerance) => null;

        public object? Specific(object annotation) => null;

        public int FrameCount(object gtol) => 0;

        public IReadOnlyList<string>? FrameValues(object gtol, int frame) => null;

        public IReadOnlyList<string>? FrameSymbols(object gtol, int frame) => null;

        public string? FrameXml(object gtol, int frame) => null;

        public string? DatumIdentifier(object gtol) => null;

        public string? DatumLabel(object datumTag) => null;

        public int SurfaceFinishSymbol(object symbol) => 0;

        public int SurfaceFinishTextCount(object symbol) => 0;

        public string? SurfaceFinishText(object symbol, int index) => null;

        public string? TableTitle(object table) => "FICTIONAL TABLE";

        public IReadOnlyList<string>? BomModelPaths(object table, int row) => null;

        private readonly object _face = new object();

        private readonly object _tolerance = new object();
    }
}
