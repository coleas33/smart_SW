using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>What one dump produced.</summary>
public sealed class DumpResult
{
    public DumpResult(EvidencePackage package, string packageFilePath)
    {
        Package = package;
        PackageFilePath = packageFilePath;
    }

    public EvidencePackage Package { get; }

    /// <summary>Absolute path of the package.json that was written.</summary>
    public string PackageFilePath { get; }

    public IReadOnlyList<Gap> Gaps => Package.Gaps;
}

/// <summary>
/// Orchestrates the dump (T058): traversal, id allocation, every other phase, then
/// package.json and meshes/.
///
/// It touches no interop itself; each phase is an interface so the orchestration - id
/// order, gap merging, what a failed phase does to the rest of the dump - is unit tested
/// with fakes on a machine with no SOLIDWORKS seat.
///
/// A phase that throws does not end the dump: it becomes a Gap and the remaining phases
/// run, because a package missing its mates is still worth reviewing and the gap says what
/// is missing (Principle I). A <see cref="CircuitOpenError"/> is different - SOLIDWORKS has
/// stopped answering - so it stops the remaining phases and the package is written with
/// what was gathered.
/// </summary>
public sealed class PackageWriter
{
    /// <summary>The file name every consumer looks for (contracts/cli.md).</summary>
    public const string PackageFileName = "package.json";

    /// <summary>Subdirectory of the output directory that holds per-body meshes.</summary>
    public const string MeshDirectoryName = "meshes";

    private readonly IComponentTreeSource _components;
    private readonly IDocumentSource _documents;
    private readonly IManifestSource _manifest;
    private readonly IMateSource _mates;
    private readonly IHoleSource _holes;
    private readonly IFastenerSource _fasteners;
    private readonly IFaceSource _faces;
    private readonly IMeshSource _meshes;
    private readonly string? _swVersion;
    private readonly string _machine;

    public PackageWriter(
        IComponentTreeSource components,
        IDocumentSource documents,
        IManifestSource manifest,
        IMateSource mates,
        IHoleSource holes,
        IFastenerSource fasteners,
        IFaceSource faces,
        IMeshSource meshes,
        string? swVersion,
        string? machine = null)
    {
        _components = components ?? throw new ArgumentNullException(nameof(components));
        _documents = documents ?? throw new ArgumentNullException(nameof(documents));
        _manifest = manifest ?? throw new ArgumentNullException(nameof(manifest));
        _mates = mates ?? throw new ArgumentNullException(nameof(mates));
        _holes = holes ?? throw new ArgumentNullException(nameof(holes));
        _fasteners = fasteners ?? throw new ArgumentNullException(nameof(fasteners));
        _faces = faces ?? throw new ArgumentNullException(nameof(faces));
        _meshes = meshes ?? throw new ArgumentNullException(nameof(meshes));
        _swVersion = swVersion;
        _machine = machine ?? Environment.MachineName;
    }

    /// <summary>Runs every phase and writes package.json into the output directory.</summary>
    public DumpResult Write(DumpOptions options)
    {
        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        if (string.IsNullOrWhiteSpace(options.OutputDirectory))
        {
            throw new ArgumentException("An output directory is required.", nameof(options));
        }

        EvidencePackage package = Build(options);

        Directory.CreateDirectory(options.OutputDirectory);
        string path = Path.Combine(options.OutputDirectory, PackageFileName);
        File.WriteAllText(path, PackageSerializer.Serialize(package));

        return new DumpResult(package, path);
    }

    /// <summary>Runs every phase without writing anything. Used by the tests and the add-in preview.</summary>
    public EvidencePackage Build(DumpOptions options)
    {
        var gaps = new GapCollector();

        ComponentTreeResult tree = _components.Traverse(gaps, options);

        // Every id in the package is derived from the root document's path, and so is the
        // manifest's vault path. An unsaved document has neither, so it is refused here
        // with a sentence the engineer can act on rather than failing later on a hash.
        if (string.IsNullOrWhiteSpace(tree.RootDocumentPath))
        {
            throw new InvalidOperationException(
                "The document has never been saved, so it has no path. "
                + "Save it first: the package's document ids and its manifest are derived from the path.");
        }

        var scope = new DumpScope(gaps, options, tree);
        AllocateComponentIds(scope);

        var package = new EvidencePackage
        {
            SchemaVersion = EvidencePackage.CurrentSchemaVersion,
            PackageId = Guid.NewGuid(),
            CreatedAt = DateTimeOffset.Now,
            Extractor = BuildExtractorInfo(),
            Design = BuildDesign(tree),
        };

        bool aborted = false;
        IReadOnlyList<Document> documents = Array.Empty<Document>();

        aborted |= !RunPhase(gaps, "document", "read document properties, material and mass", () =>
        {
            documents = _documents.Dump(scope, DocumentPaths(tree));
            package.Documents.AddRange(documents);
        });

        if (!aborted)
        {
            aborted |= !RunPhase(gaps, "manifest", "build the document manifest", () =>
                package.Manifest = _manifest.Build(scope, documents));
        }

        if (!aborted)
        {
            aborted |= !RunPhase(gaps, "mate", "read the assembly mates", () =>
                package.Mates.AddRange(_mates.Dump(scope)));
        }

        if (!aborted)
        {
            aborted |= !RunPhase(gaps, "hole", "read Hole Wizard features and cosmetic threads", () =>
            {
                HoleDumpResult result = _holes.Dump(scope);
                package.Holes.AddRange(result.Holes);
                package.Threads.AddRange(result.Threads);
            });
        }

        if (!aborted)
        {
            aborted |= !RunPhase(gaps, "fastener", "identify fasteners", () =>
                package.Fasteners.AddRange(_fasteners.Dump(scope)));
        }

        if (!aborted)
        {
            aborted |= !RunPhase(gaps, "face", "read face geometry", () =>
                package.Faces.AddRange(_faces.Dump(scope)));
        }

        if (!aborted && options.Meshes != MeshFormat.None)
        {
            string meshDirectory = Path.Combine(options.OutputDirectory, MeshDirectoryName);
            aborted |= !RunPhase(gaps, "body", "tessellate bodies and write meshes", () =>
                package.Bodies.AddRange(_meshes.Dump(scope, meshDirectory)));
        }

        AddComponentInstances(package, scope);

        // Native drawing extraction is not part of this build; drawing sheets come from the
        // Python PDF ingest (US1). Recording it keeps the absence visible.
        gaps.Add(
            GapKind.Unsupported,
            "drawing",
            null,
            "The native extractor does not read drawing sheets; they come from the PDF ingest.",
            null);

        package.Gaps.AddRange(gaps.Gaps);
        return package;
    }

    /// <summary>
    /// Ids are allocated in traversal order, so cmp:0001 is the root and a reader can
    /// follow the tree by id. A component with no file path cannot be given a document id,
    /// so it becomes a gap rather than a half-populated instance.
    /// </summary>
    private static void AllocateComponentIds(DumpScope scope)
    {
        var ids = new IdAllocator("cmp");

        foreach (ComponentNode node in scope.Tree.Nodes)
        {
            if (string.IsNullOrWhiteSpace(node.DocumentPath))
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "component",
                    null,
                    $"Component '{node.Key}' reports no file path, so it cannot be identified.",
                    null);
                continue;
            }

            scope.AddComponent(ids.Next(), scope.DocumentId(node.DocumentPath), node);
        }
    }

    private static void AddComponentInstances(EvidencePackage package, DumpScope scope)
    {
        foreach (ScopedComponent scoped in scope.Components)
        {
            ComponentNode node = scoped.Node;

            if (node.PersistRef == null)
            {
                // Principle IV: an entity with no persistent reference cannot be navigated
                // back to, so it is recorded as a gap instead of written without a locator.
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "component",
                    scoped.Id,
                    $"GetPersistReference3 gave no reference for '{node.Key}'.",
                    null);
                continue;
            }

            // A reference with no scope cannot be resolved later, so the component's own
            // document is recorded as the scope and the ambiguity is made visible.
            string scopePath = node.PersistRefScopePath;
            if (string.IsNullOrWhiteSpace(scopePath))
            {
                scopePath = node.DocumentPath;
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "component",
                    scoped.Id,
                    $"The persistent reference for '{node.Key}' names no scope document; "
                    + "its own document was recorded instead and may not resolve it.",
                    null);
            }

            package.Components.Add(new ComponentInstance
            {
                Id = scoped.Id,
                PersistRef = node.PersistRef,
                PersistRefScope = scope.DocumentId(scopePath),
                Name = node.Name,
                FullPath = node.Key,
                DocumentId = scoped.DocumentId,
                ParentId = node.ParentKey == null ? null : scope.Find(node.ParentKey)?.Id,
                ReferencedConfiguration = node.ReferencedConfiguration,
                Transform = node.Transform,
                Suppression = node.Suppression,
                IsFixed = node.IsFixed,
                PatternId = node.PatternId,
                IsToolbox = node.IsToolbox,
            });
        }
    }

    /// <summary>Every distinct document the tree referenced, root first.</summary>
    private static IReadOnlyList<string> DocumentPaths(ComponentTreeResult tree)
    {
        var paths = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        if (!string.IsNullOrWhiteSpace(tree.RootDocumentPath) && seen.Add(tree.RootDocumentPath))
        {
            paths.Add(tree.RootDocumentPath);
        }

        foreach (ComponentNode node in tree.Nodes)
        {
            if (!string.IsNullOrWhiteSpace(node.DocumentPath) && seen.Add(node.DocumentPath))
            {
                paths.Add(node.DocumentPath);
            }
        }

        return paths;
    }

    private static Design BuildDesign(ComponentTreeResult tree) => new Design
    {
        DesignId = DocumentIds.DesignId(tree.RootDocumentPath),
        Name = tree.DesignName,
        RootAssemblyDocumentId = DocumentIds.For(tree.RootDocumentPath),
        ActiveConfiguration = tree.ActiveConfiguration,
    };

    private ExtractorInfo BuildExtractorInfo() => new ExtractorInfo
    {
        Name = "SwReview.Extractor",
        Version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "0.0.0",
        SwVersion = _swVersion,
        Machine = _machine,
    };

    /// <summary>
    /// Runs one phase. Returns false when the session is gone and the remaining phases
    /// must be skipped; any other failure is recorded and the dump continues.
    /// </summary>
    private static bool RunPhase(GapCollector gaps, string entityKind, string description, Action phase)
    {
        try
        {
            phase();
            return true;
        }
        catch (CircuitOpenError ex)
        {
            gaps.Add(
                GapKind.ToolError,
                entityKind,
                null,
                $"SOLIDWORKS stopped answering while trying to {description}; later phases were skipped.",
                ex.Message);
            return false;
        }
        catch (Exception ex)
        {
            gaps.Record(entityKind, null, $"Failed to {description}.", ex);
            return true;
        }
    }
}
