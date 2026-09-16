using System;
using System.Collections.Generic;
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
}

/// <summary>
/// One component instance as traversal found it, before ids exist. <see cref="Key"/> is the
/// full instance path (<c>IComponent2.Name2</c>), which is unique in the assembly;
/// <c>GetID</c> is never used because it collides across subassemblies (research R12).
/// </summary>
public sealed class ComponentNode
{
    /// <summary>Full instance path, e.g. "sub-2/bracket-3". Unique within the assembly.</summary>
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

    public DocumentKind RootDocumentKind { get; set; } = DocumentKind.Assembly;

    /// <summary>File name without extension; the design's name in the report.</summary>
    public string DesignName { get; set; } = string.Empty;

    public string ActiveConfiguration { get; set; } = string.Empty;

    /// <summary>Depth-first traversal order; ids are allocated in this order.</summary>
    public List<ComponentNode> Nodes { get; } = new List<ComponentNode>();
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

    public DumpScope(GapCollector gaps, DumpOptions options, ComponentTreeResult tree)
    {
        Gaps = gaps ?? throw new ArgumentNullException(nameof(gaps));
        Options = options ?? throw new ArgumentNullException(nameof(options));
        Tree = tree ?? throw new ArgumentNullException(nameof(tree));
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

/// <summary>Hole Wizard features and cosmetic threads (T052).</summary>
public interface IHoleSource
{
    HoleDumpResult Dump(DumpScope scope);
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
}
