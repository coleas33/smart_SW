using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>What <c>--meshes</c> asked for.</summary>
public enum MeshFormat
{
    Glb,
    Stl,
    None,
}

/// <summary>What <c>--features</c> asked for.</summary>
public enum FeatureScope
{
    /// <summary>Walk every resolved part document's feature tree into <c>features[]</c>.</summary>
    Tree,

    /// <summary>Walk none of them; the RMS rules then have nothing to read.</summary>
    None,
}

/// <summary>What <c>--equations</c> asked for.</summary>
public enum EquationScope
{
    /// <summary>Read every resolved part document's equation manager into <c>equations[]</c>.</summary>
    On,

    /// <summary>Read none of them; the two parametric rules then have nothing to read.</summary>
    Off,
}

/// <summary>
/// What <c>--profile</c> asked for: how much of the design the dump reads. Recorded on
/// <see cref="ExtractorInfo.Profile"/> as "full", "model_check" or "standards" (schema
/// 1.4.0), so a reader can tell a deliberately thin package from a dump that lost half its
/// evidence. A consumer that needs a particular phase decides from <c>extractor.phases</c>
/// rather than from this name (FR-043).
/// Named here, with the other <c>dump</c> options, because it is a dump decision; the IR
/// DTO carries the value but does not own the vocabulary.
/// </summary>
public enum DumpProfile
{
    /// <summary>Every phase: the design review dump (feature 001).</summary>
    Full,

    /// <summary>
    /// Document, manifest, mate, feature and equation phases only. The hole, tolerance,
    /// fastener, face and body or mesh phases are skipped, so those arrays are empty by design.
    /// </summary>
    ModelCheck,

    /// <summary>
    /// <see cref="ModelCheck"/>'s five phases plus <c>cutlist</c>, and <c>drawing</c> when
    /// the root document is a drawing (schema 1.4.0, FR-027). It still skips hole, fastener,
    /// face and body - the four phases that read face geometry, tessellate every body and
    /// write mesh files, which is most of a dump's cost and none of which any standards
    /// check reads - and the tolerance phase beside them (schema 1.5.0).
    /// </summary>
    Standards,
}

/// <summary>What <c>--faces</c> asked for.</summary>
public enum FaceScope
{
    /// <summary>Only faces a hole, thread, fastener or mate referenced.</summary>
    Needed,

    /// <summary>Every face of every body; large, and only useful for debugging.</summary>
    All,
}

/// <summary>The <c>dump</c> command's options (contracts/cli.md).</summary>
public sealed class DumpOptions
{
    /// <summary>Directory that receives package.json and meshes/.</summary>
    public string OutputDirectory { get; set; } = string.Empty;

    /// <summary>Configuration to dump; null means the document's active configuration.</summary>
    public string? Configuration { get; set; }

    public MeshFormat Meshes { get; set; } = MeshFormat.Glb;

    public FaceScope Faces { get; set; } = FaceScope.Needed;

    public FeatureScope Features { get; set; } = FeatureScope.Tree;

    public EquationScope Equations { get; set; } = EquationScope.On;

    /// <summary>
    /// How much of the design to read. <see cref="DumpProfile.Full"/> by default, because a
    /// caller that did not ask for a reduced dump is doing a design review and needs every
    /// phase; the reduced profile is opted into, never fallen back to.
    /// </summary>
    public DumpProfile Profile { get; set; } = DumpProfile.Full;
}

/// <summary>
/// One component instance as traversal found it, before ids exist. <see cref="Key"/> is the
/// full instance path (<c>IComponent2.Name2</c>), which is unique in the assembly;
/// <c>GetID</c> is never used because it collides across subassemblies (research R12).
/// </summary>
public sealed class ComponentNode
{
    /// <summary>
    /// Full instance path, e.g. "sub-2/bracket-3". Unique within the assembly.
    ///
    /// A node the dump SYNTHESIZES for a document rather than reading from an
    /// <c>IComponent2</c> - a drawing's forest root and each model its views reference
    /// (<see cref="ComponentTreeDumper.DrawingRootNode"/>,
    /// <see cref="ComponentTreeDumper.ReferencedModelNode"/>) - is keyed on its document path
    /// instead, because a file base name is not unique across a forest and
    /// <see cref="DumpScope.AddComponent"/> keeps the last write for a key.
    /// </summary>
    public string Key { get; set; } = string.Empty;

    /// <summary>The parent's <see cref="Key"/>; null for the root component.</summary>
    public string? ParentKey { get; set; }

    /// <summary>Component name with instance suffix, e.g. "bracket-3".</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>Full path of the part or assembly file this instance references.</summary>
    public string DocumentPath { get; set; } = string.Empty;

    public DocumentKind DocumentKind { get; set; } = DocumentKind.Part;

    public string ReferencedConfiguration { get; set; } = string.Empty;

    /// <summary>Row-major 4x4 in meters, relative to the root assembly.</summary>
    public double[][] Transform { get; set; } = Ir.Transform.Identity();

    public SuppressionState Suppression { get; set; } = SuppressionState.Resolved;

    public bool IsFixed { get; set; }

    /// <summary>Feature name of the component pattern this instance belongs to, or null.</summary>
    public string? PatternId { get; set; }

    public bool IsToolbox { get; set; }

    /// <summary>
    /// IComponent2.GetConstrainedStatus verbatim; null when the read failed (a Gap). The
    /// traversal records the number and names nothing.
    /// </summary>
    public int? ConstrainedStatusRaw { get; set; }

    /// <summary>
    /// What the <c>GetConstrainedStatus</c> read threw, or null when it did not throw. The
    /// gap itself is written by <c>PackageWriter</c>, which is the first place the
    /// component's <c>cmp:NNNN</c> exists for it to name (data-model section 1).
    /// </summary>
    public string? ConstrainedStatusError { get; set; }

    /// <summary>
    /// IComponent2.HasMaterialPropertyValues() (schema 1.4.0); null plus a
    /// component_transparency gap. Read before <see cref="TransparencyRaw"/>, because a
    /// component with no override has no slot to read and its null is not a gap.
    /// </summary>
    public bool? HasAppearanceOverride { get; set; }

    /// <summary>
    /// Slot 7 of IComponent2.GetMaterialPropertyValues2(1, null) verbatim (schema 1.4.0);
    /// null plus a component_transparency gap when the read failed, and null without one
    /// when there was no override to read. Which value means transparent is PROBE-2 and is
    /// decided in Python, never here.
    /// </summary>
    public double? TransparencyRaw { get; set; }

    /// <summary>
    /// IComponent2.Visible verbatim, in swComponentVisibilityState_e (schema 1.4.0); null
    /// plus a component_visibility gap. The traversal records the number and names nothing.
    /// </summary>
    public int? VisibilityRaw { get; set; }

    /// <summary>
    /// IComponent2.IsPatternInstance() (schema 1.4.0); null plus a component_pattern gap.
    /// <see cref="PatternId"/> keeps the pattern's name for the reason text and cannot
    /// replace this: a null PatternId conflates "not in a pattern" with "the pattern map was
    /// never built".
    /// </summary>
    public bool? IsPatternInstance { get; set; }

    /// <summary>Base64 persistent reference, or null when SOLIDWORKS gave none (a Gap).</summary>
    public string? PersistRef { get; set; }

    /// <summary>Path of the document whose extension produced <see cref="PersistRef"/>.</summary>
    public string PersistRefScopePath { get; set; } = string.Empty;

    /// <summary>
    /// The live <c>IComponent2</c>, so the later dumpers do not traverse twice. Typed as
    /// object to keep this contract free of the interop assembly; null in tests.
    /// </summary>
    public object? Handle { get; set; }
}

/// <summary>What component traversal produced.</summary>
public sealed class ComponentTreeResult
{
    public string RootDocumentPath { get; set; } = string.Empty;

    /// <summary>
    /// The kind of the open document, or null when it could not be read (T064). No
    /// initializer on purpose: the kind is engineering data, and a tree that answered
    /// "assembly" for a document nobody read would hand <see cref="FeatureDumper"/> and
    /// <see cref="EquationDumper"/> a node they skip, dropping that document's whole feature
    /// tree and equation list in silence. A null here means no node was recorded and a gap
    /// says why.
    /// </summary>
    public DocumentKind? RootDocumentKind { get; set; }

    /// <summary>File name without extension; the design's name in the report.</summary>
    public string DesignName { get; set; } = string.Empty;

    public string ActiveConfiguration { get; set; } = string.Empty;

    /// <summary>Depth-first traversal order; ids are allocated in this order.</summary>
    public List<ComponentNode> Nodes { get; } = new List<ComponentNode>();

    /// <summary>
    /// The open document's live <c>IModelDoc2</c> (feature 011): the handle the <c>drawing</c>
    /// phase reads a drawing root through. Typed as object to keep this contract free of the
    /// interop assembly, as <see cref="ComponentNode.Handle"/> is; null in tests that need none.
    /// </summary>
    public object? RootDocument { get; set; }

    /// <summary>
    /// What open-drawing discovery found for a review of this part or assembly (feature 011,
    /// contracts/open-drawings.md section 4): the drawings the <c>drawing</c> phase reads, in
    /// order, and the candidates. <see cref="Dump.AttachedDrawings.None"/> until
    /// <see cref="PackageWriter"/> runs discovery, and for every build that does not.
    /// </summary>
    public AttachedDrawings AttachedDrawings { get; set; } = AttachedDrawings.None;
}

/// <summary>
/// The seven drawing id allocators (feature 011, contracts/native-evidence.md section 1): the
/// six feature 006 gave each traversal, and <c>dtb</c> for the tables. One set per package, on
/// <see cref="DumpScope.DrawingIds"/>, so when several drawings are read each prefix continues
/// one sequence and an id names one record of one drawing in the package (FR-016). A drawing
/// root's single record numbers exactly as it did before.
/// </summary>
public sealed class DrawingIdAllocators
{
    public IdAllocator Sheets { get; } = new IdAllocator("dsh");

    public IdAllocator Views { get; } = new IdAllocator("dvw");

    public IdAllocator Dimensions { get; } = new IdAllocator("ddm");

    public IdAllocator Annotations { get; } = new IdAllocator("dan");

    public IdAllocator Notes { get; } = new IdAllocator("dnt");

    public IdAllocator RevisionTables { get; } = new IdAllocator("drv");

    public IdAllocator Tables { get; } = new IdAllocator("dtb");

    /// <summary>A fresh set: every prefix starts at 0001 (a dump).</summary>
    public DrawingIdAllocators()
    {
    }

    private DrawingIdAllocators(IReadOnlyCollection<DrawingRecord> records)
    {
        IdAllocator Continue(string prefix, IEnumerable<string> ids) =>
            new IdAllocator(prefix, IdAllocator.HighestIssued(prefix, ids));

        var sheets = new List<string>();
        var views = new List<string>();
        var dimensions = new List<string>();
        var annotations = new List<string>();
        var notes = new List<string>();
        var revisionTables = new List<string>();
        var tables = new List<string>();

        foreach (DrawingRecord record in records)
        {
            foreach (DrawingSheetRecord sheet in record.Sheets)
            {
                sheets.Add(sheet.Id);
                revisionTables.AddRange(sheet.RevisionTables.Select(table => table.Id));
                tables.AddRange((sheet.Tables ?? new List<DrawingTable>()).Select(table => table.Id));
                foreach (DrawingView view in sheet.Views)
                {
                    views.Add(view.Id);
                    dimensions.AddRange(view.DisplayDimensions.Select(dimension => dimension.Id));
                    annotations.AddRange(view.Annotations.Select(annotation => annotation.Id));
                    notes.AddRange(view.Notes.Select(note => note.Id));
                }
            }
        }

        Sheets = Continue("dsh", sheets);
        Views = Continue("dvw", views);
        Dimensions = Continue("ddm", dimensions);
        Annotations = Continue("dan", annotations);
        Notes = Continue("dnt", notes);
        RevisionTables = Continue("drv", revisionTables);
        Tables = Continue("dtb", tables);
    }

    /// <summary>
    /// A set continuing past every drawing id <paramref name="package"/> already holds, prefix by
    /// prefix (feature 011, contracts/confirmed-open.md section 2): a drawing appended to a
    /// package - the confirmed candidate's read - numbers after the drawings the dump read.
    /// </summary>
    public static DrawingIdAllocators ContinuingFrom(EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        return new DrawingIdAllocators(package.DrawingRecords ?? new List<DrawingRecord>());
    }
}

/// <summary>
/// One drawing the <c>drawing</c> phase reads: its path, which names it in the package, and the
/// live document it is read through - the root document for a drawing root, an open drawing
/// discovery attached for a part or assembly review (feature 011). A null document is a drawing
/// the phase cannot read, and it says so in a gap rather than reading another document.
/// </summary>
public sealed class ScopedDrawing
{
    public ScopedDrawing(
        string documentPath, object? document, Func<string, string?>? reviewedDocumentId = null)
    {
        if (string.IsNullOrWhiteSpace(documentPath))
        {
            throw new ArgumentException("A drawing is named by its document path.", nameof(documentPath));
        }

        DocumentPath = documentPath;
        Document = document;
        ReviewedDocumentId = reviewedDocumentId;
    }

    public string DocumentPath { get; }

    /// <summary>The live <c>IModelDoc2</c>, typed as object; null when none was handed over.</summary>
    public object? Document { get; }

    /// <summary>
    /// For a drawing read <b>with</b> a reviewed design - one discovery attached, or one the
    /// engineer confirmed - the rule that ties a view's referenced path to a document of the
    /// package, or null for a path outside the review
    /// (<see cref="OpenDrawingDiscovery.DocumentResolver"/>, contracts/open-drawings.md section 3).
    /// Null for a drawing root, whose views are read as feature 006 reads them.
    /// </summary>
    public Func<string, string?>? ReviewedDocumentId { get; }
}

/// <summary>A component that has been given its package id.</summary>
public sealed class ScopedComponent
{
    public ScopedComponent(string id, string documentId, ComponentNode node)
    {
        Id = id;
        DocumentId = documentId;
        Node = node;
    }

    public string Id { get; }

    public string DocumentId { get; }

    public ComponentNode Node { get; }
}

/// <summary>
/// A face another dumper referenced and wants described. The face itself stays a COM
/// handle until <see cref="IFaceSource"/> reads it.
/// </summary>
public sealed class FaceRequest
{
    public FaceRequest(object entity, string componentId, double[][] componentTransform, string scopeDocumentPath)
    {
        Entity = entity;
        ComponentId = componentId;
        ComponentTransform = componentTransform;
        ScopeDocumentPath = scopeDocumentPath;
    }

    /// <summary>The live <c>IFace2</c>.</summary>
    public object Entity { get; }

    public string ComponentId { get; }

    /// <summary>The owning component's world transform, for assembly-space geometry.</summary>
    public double[][] ComponentTransform { get; }

    /// <summary>Owning PART document; face refs are scoped to it, not the assembly.</summary>
    public string ScopeDocumentPath { get; }

    /// <summary>Set once the face has been described, so it is not described twice.</summary>
    public string? FaceId { get; set; }
}

/// <summary>Holes and cosmetic threads come from the same feature sweep.</summary>
public sealed class HoleDumpResult
{
    public List<Hole> Holes { get; } = new List<Hole>();

    public List<CosmeticThread> Threads { get; } = new List<CosmeticThread>();
}

/// <summary>
/// Everything a dumper needs that PackageWriter owns: the gap list, the options, the
/// component ids and document ids, and the id allocators. Passed to every phase so no
/// dumper invents an id of its own.
/// </summary>
public sealed class DumpScope
{
    private readonly Dictionary<string, ScopedComponent> _byKey =
        new Dictionary<string, ScopedComponent>(StringComparer.Ordinal);

    private readonly List<ScopedComponent> _components = new List<ScopedComponent>();
    private readonly List<FaceRequest> _faceRequests = new List<FaceRequest>();

    public DumpScope(
        GapCollector gaps, DumpOptions options, ComponentTreeResult tree, DrawingIdAllocators? drawingIds = null)
    {
        Gaps = gaps ?? throw new ArgumentNullException(nameof(gaps));
        Options = options ?? throw new ArgumentNullException(nameof(options));
        Tree = tree ?? throw new ArgumentNullException(nameof(tree));
        DrawingIds = drawingIds ?? new DrawingIdAllocators();
    }

    public GapCollector Gaps { get; }

    public DumpOptions Options { get; }

    public ComponentTreeResult Tree { get; }

    public string ActiveConfiguration => Tree.ActiveConfiguration;

    public IReadOnlyList<ScopedComponent> Components => _components;

    public IReadOnlyList<FaceRequest> FaceRequests => _faceRequests;

    public IdAllocator HoleIds { get; } = new IdAllocator("hol");

    public IdAllocator ThreadIds { get; } = new IdAllocator("thr");

    public IdAllocator FastenerIds { get; } = new IdAllocator("fas");

    public IdAllocator FaceIds { get; } = new IdAllocator("fac");

    public IdAllocator BodyIds { get; } = new IdAllocator("bod");

    public IdAllocator MateIds { get; } = new IdAllocator("mat");

    /// <summary>
    /// Cut-list item ids, allocated in traversal order across the package (schema 1.4.0), so
    /// <c>cut:0007</c> means one item of one document in one package - the same rule
    /// <see cref="FeatureIds"/> follows.
    /// </summary>
    public IdAllocator CutListIds { get; } = new IdAllocator("cut");

    /// <summary>
    /// Feature ids run across the package, not per document: one allocator for every
    /// document's tree, so <c>feat:0007</c> means one feature in one package (data-model
    /// section 1).
    /// </summary>
    public IdAllocator FeatureIds { get; } = new IdAllocator("feat");

    /// <summary>
    /// Model dimension ids (schema 1.5.0, feature 010), allocated in traversal order across the
    /// package, so <c>mdm:0007</c> means one dimension of one document in one package.
    /// </summary>
    public IdAllocator ModelDimensionIds { get; } = new IdAllocator("mdm");

    /// <summary>Model annotation ids (schema 1.5.0, feature 010), allocated the same way.</summary>
    public IdAllocator ModelAnnotationIds { get; } = new IdAllocator("man");

    /// <summary>
    /// The drawing ids (feature 011): one set for the package, so every drawing the
    /// <c>drawing</c> phase reads continues the same sequences - fresh for a dump, continuing the
    /// package's own for a drawing appended to it (<see cref="DrawingIdAllocators.ContinuingFrom"/>).
    /// </summary>
    public DrawingIdAllocators DrawingIds { get; }

    /// <summary>
    /// The drawings the <c>drawing</c> phase reads, in order: the root drawing for a drawing
    /// root (<see cref="PackageWriter.ScopeFor"/>), and, under a review, the open drawings
    /// discovery attached (feature 011).
    /// </summary>
    public List<ScopedDrawing> Drawings { get; } = new List<ScopedDrawing>();

    /// <summary>Registers a traversed component under its allocated id.</summary>
    public ScopedComponent AddComponent(string id, string documentId, ComponentNode node)
    {
        var scoped = new ScopedComponent(id, documentId, node);
        _components.Add(scoped);
        _byKey[node.Key] = scoped;
        return scoped;
    }

    /// <summary>The component id for a full instance path, or null if it was not traversed.</summary>
    public ScopedComponent? Find(string componentKey)
    {
        if (componentKey == null)
        {
            return null;
        }

        return _byKey.TryGetValue(componentKey, out ScopedComponent scoped) ? scoped : null;
    }

    /// <summary>The stable id for a document path.</summary>
    public string DocumentId(string documentPath) => DocumentIds.For(documentPath);

    /// <summary>
    /// Asks for a face to be described and returns the id it will carry. Called by the
    /// hole, thread, fastener and mate dumpers; <see cref="IFaceSource"/> fulfils them.
    /// </summary>
    public string RequestFace(object face, string componentId, double[][] componentTransform, string scopeDocumentPath)
    {
        if (face == null)
        {
            throw new ArgumentNullException(nameof(face));
        }

        var request = new FaceRequest(face, componentId, componentTransform, scopeDocumentPath)
        {
            FaceId = FaceIds.Next(),
        };

        _faceRequests.Add(request);
        return request.FaceId!;
    }
}

/// <summary>
/// The two seams open-drawing discovery needs (feature 011, contracts/open-drawings.md section
/// 2): the documents SOLIDWORKS already has open, and whether a file exists. Nothing here opens,
/// loads, activates or lists a folder; <see cref="SwOpenDrawingReader"/> is the SOLIDWORKS side,
/// and <see cref="OpenDrawingDiscovery.Discover"/> holds every rule.
/// </summary>
public interface IOpenDrawingSource
{
    /// <summary>
    /// <c>ISldWorks.GetDocuments</c>: every open document, in the order SOLIDWORKS lists them, each
    /// read lazily so a document that does not answer costs one gap and not the listing.
    /// </summary>
    IReadOnlyList<OpenDocument> OpenDocuments();

    /// <summary>Whether a file exists on disk from this process; nothing is opened or read.</summary>
    bool FileExists(string path);
}

/// <summary>Walks the component tree. The only phase that runs before ids exist.</summary>
public interface IComponentTreeSource
{
    ComponentTreeResult Traverse(GapCollector gaps, DumpOptions options);
}

/// <summary>Properties, material and mass for every document the tree referenced (T054).</summary>
public interface IDocumentSource
{
    IReadOnlyList<Document> Dump(DumpScope scope, IReadOnlyList<string> documentPaths);
}

/// <summary>Provenance per document (T057).</summary>
public interface IManifestSource
{
    Manifest Build(DumpScope scope, IReadOnlyList<Document> documents);
}

/// <summary>Mates of the root assembly (T051).</summary>
public interface IMateSource
{
    IReadOnlyList<Mate> Dump(DumpScope scope);
}

/// <summary>Feature trees of every resolved part document (T024).</summary>
public interface IFeatureSource
{
    IReadOnlyList<Feature> Dump(DumpScope scope);
}

/// <summary>Equation managers of every resolved part document (T038).</summary>
public interface IEquationSource
{
    IReadOnlyList<Equation> Dump(DumpScope scope);
}

/// <summary>
/// Cut-list items of every resolved part document (schema 1.4.0, feature 006). Items are
/// identified <b>structurally</b> from the body-folder tree, never by matching a feature
/// name: a renamed item is still the same item, so a renamed item is not a waiver.
/// </summary>
public interface ICutListSource
{
    IReadOnlyList<CutListItem> Dump(DumpScope scope);
}

/// <summary>
/// Sheets, views, dimensions, annotations, revision tables and notes of a drawing document
/// (schema 1.4.0, feature 006). Runs only when the root document is a drawing, and
/// <b>activates nothing</b>: a sheet that was not the active one is read as it stands, and
/// <c>was_active</c> says which rows a consumer can trust (FR-044).
/// </summary>
public interface IDrawingSource
{
    IReadOnlyList<DrawingRecord> Dump(DumpScope scope);
}

/// <summary>Hole Wizard features and cosmetic threads (T052).</summary>
public interface IHoleSource
{
    HoleDumpResult Dump(DumpScope scope);
}

/// <summary>
/// The part documents' feature dimensions with their tolerances, and their geometric tolerances
/// and datum tags (schema 1.5.0, feature 010 T091). Runs under the Full profile, after the hole
/// phase; the Model check and Standards profiles skip it.
/// </summary>
public interface IToleranceSource
{
    ToleranceDumpResult Dump(DumpScope scope);
}

/// <summary>What the <c>tolerance</c> phase read, in traversal order.</summary>
public sealed class ToleranceDumpResult
{
    public List<ModelDimension> Dimensions { get; } = new List<ModelDimension>();

    public List<ModelAnnotation> Annotations { get; } = new List<ModelAnnotation>();
}

/// <summary>Toolbox and other fasteners (T053).</summary>
public interface IFastenerSource
{
    IReadOnlyList<Fastener> Dump(DumpScope scope);
}

/// <summary>Face geometry for the requested faces, or all faces (T055).</summary>
public interface IFaceSource
{
    IReadOnlyList<FaceGeometry> Dump(DumpScope scope);
}

/// <summary>Per-body meshes written under meshes/ (T056).</summary>
public interface IMeshSource
{
    IReadOnlyList<BodyRef> Dump(DumpScope scope, string meshDirectory);

    /// <summary>
    /// One component's bodies, through the same export path <see cref="Dump"/> uses (T097).
    ///
    /// Lever 10a fetches a mesh over the bridge for a package extracted without one, and it
    /// reaches the export here rather than tessellating a second way: a different chord
    /// tolerance in the two paths would make a clearance answer depend on how the mesh
    /// arrived (FR-090).
    /// </summary>
    IReadOnlyList<BodyRef> DumpComponent(
        DumpScope scope, ScopedComponent component, string meshDirectory);
}
