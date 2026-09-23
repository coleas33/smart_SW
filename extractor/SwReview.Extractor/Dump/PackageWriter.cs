using System;
using System.Collections.Generic;
using System.Diagnostics;
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

    /// <summary>
    /// The phases of a dump, in the order <see cref="Build"/> runs them, and the order the
    /// timing rows come out in (feature 005 T033). One list: a phase that runs and is not
    /// named here would be timed and then dropped.
    /// </summary>
    private static readonly string[] PhaseOrder =
    {
        "document", "manifest", "mate", "feature", "equation", "cutlist", "drawing",
        "hole", "tolerance", "fastener", "face", "body",
    };

    /// <summary>
    /// The phase rows for a package no dump phase ran in: every name in
    /// <see cref="PhaseOrder"/>, <c>skipped</c>, with no elapsed time. The reuse path
    /// (Dump/PackageReuse.cs) copies an earlier package rather than dumping, so it stamps
    /// these over the rows it copied - repeating the original dump's wall clock would have
    /// the new package claim milliseconds nobody spent in it (Principle I).
    /// </summary>
    internal static IEnumerable<DumpPhase> NoPhaseRan() => new PhaseLog().Rows();

    private readonly IComponentTreeSource _components;
    private readonly IDocumentSource _documents;
    private readonly IManifestSource _manifest;
    private readonly IMateSource _mates;
    private readonly IFeatureSource _features;
    private readonly IEquationSource _equations;
    private readonly ICutListSource? _cutList;
    private readonly IDrawingSource? _drawings;
    private readonly IHoleSource _holes;
    private readonly IFastenerSource _fasteners;
    private readonly IFaceSource _faces;
    private readonly IMeshSource _meshes;
    private readonly IToleranceSource? _tolerances;
    private readonly string? _swVersion;
    private readonly string _machine;

    public PackageWriter(
        IComponentTreeSource components,
        IDocumentSource documents,
        IManifestSource manifest,
        IMateSource mates,
        IFeatureSource features,
        IEquationSource equations,
        ICutListSource? cutList,
        IDrawingSource? drawings,
        IHoleSource holes,
        IFastenerSource fasteners,
        IFaceSource faces,
        IMeshSource meshes,
        string? swVersion,
        string? machine = null,
        IToleranceSource? tolerances = null)
    {
        _components = components ?? throw new ArgumentNullException(nameof(components));
        _documents = documents ?? throw new ArgumentNullException(nameof(documents));
        _manifest = manifest ?? throw new ArgumentNullException(nameof(manifest));
        _mates = mates ?? throw new ArgumentNullException(nameof(mates));
        _features = features ?? throw new ArgumentNullException(nameof(features));
        _equations = equations ?? throw new ArgumentNullException(nameof(equations));

        // The two schema 1.4.0 phases are the only sources a caller may leave out, and the
        // omission is deliberate rather than defensive: a build with no interop reader wired
        // for them records the phase `skipped`, which is exactly the row `swreview check
        // standards` refuses a package on (FR-043). Silence would be the alternative, and
        // an empty cut_list_items[] with no row beside it reads as a part with no cut list.
        _cutList = cutList;
        _drawings = drawings;

        _holes = holes ?? throw new ArgumentNullException(nameof(holes));
        _fasteners = fasteners ?? throw new ArgumentNullException(nameof(fasteners));
        _faces = faces ?? throw new ArgumentNullException(nameof(faces));
        _meshes = meshes ?? throw new ArgumentNullException(nameof(meshes));

        // The schema 1.5.0 phase (feature 010) is optional for the reason the two 1.4.0 phases
        // are: a build with no reader wired records it `skipped`, which says so, rather than
        // writing no model_dimensions[] beside a row that claims it ran.
        _tolerances = tolerances;
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
    public EvidencePackage Build(DumpOptions options) => Build(options, keyOnly: false);

    /// <summary>
    /// The package a full dump would write, built only as far as the package-reuse key needs
    /// it: the traversal, the document phase, the manifest and the component instances
    /// (feature 005 lever 9, T091).
    ///
    /// The remaining phases are the minutes of hole, face and mesh work the lever exists to
    /// skip, and none of them is in the key, so a probe that ran them would cost exactly what
    /// reusing was meant to save. What comes back is a package in every other sense - and one
    /// nothing writes to disk: it is an answer to "which design is on screen, right now".
    /// </summary>
    public EvidencePackage BuildReuseProbe(DumpOptions options) => Build(options, keyOnly: true);

    private EvidencePackage Build(DumpOptions options, bool keyOnly)
    {
        var gaps = new GapCollector();
        var phases = new PhaseLog();

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

        DumpScope scope = ScopeFor(gaps, options, tree);

        var package = new EvidencePackage
        {
            SchemaVersion = EvidencePackage.CurrentSchemaVersion,
            PackageId = Guid.NewGuid(),
            CreatedAt = DateTimeOffset.Now,
            Extractor = BuildExtractorInfo(options),
            Design = BuildDesign(tree),
        };

        bool aborted = false;
        IReadOnlyList<Document> documents = Array.Empty<Document>();

        aborted |= !RunPhase(gaps, phases, "document", "read document properties, material and mass", () =>
        {
            documents = _documents.Dump(scope, DocumentPaths(tree));
            package.Documents.AddRange(documents);
        });

        if (!aborted)
        {
            aborted |= !RunPhase(gaps, phases, "manifest", "build the document manifest", () =>
                package.Manifest = _manifest.Build(scope, documents));
        }

        if (keyOnly)
        {
            return Finish(package, scope, gaps, phases, options);
        }

        if (!aborted)
        {
            aborted |= !RunPhase(gaps, phases, "mate", "read the assembly mates", () =>
                package.Mates.AddRange(_mates.Dump(scope)));
        }

        if (options.Features == FeatureScope.None)
        {
            // The trees were skipped on purpose. Recording it keeps the absence visible: a
            // package with no features[] and nothing saying why reads as parts whose trees
            // are empty, and the RMS rules would grade a tree nobody opened (Principle I).
            gaps.Add(
                GapKind.NotExtracted,
                "feature_tree_unavailable",
                null,
                "The part feature trees were not read: the dump was run with --features none.",
                null);
        }
        else if (!aborted)
        {
            aborted |= !RunPhase(gaps, phases, "feature", "read the part feature trees", () =>
                package.Features.AddRange(_features.Dump(scope)));
        }

        if (options.Equations == EquationScope.Off)
        {
            // Same reason as --features none: a package with no equations[] and nothing
            // saying why reads as parts that have no global variables at all, and
            // rms.params.global_variables_present would report a finding against an
            // equation manager nobody opened (Principle I).
            gaps.Add(
                GapKind.NotExtracted,
                "equations",
                null,
                "The part equations were not read: the dump was run with --equations off.",
                null);
        }
        else if (!aborted)
        {
            aborted |= !RunPhase(gaps, phases, "equation", "read the part equations", () =>
                package.Equations.AddRange(_equations.Dump(scope)));
        }

        // The cut list, under the Standards and Full profiles (006 FR-027): the standards
        // checks read it, and a full extract is never less complete than a standards one.
        bool standardsEvidence =
            options.Profile == DumpProfile.Full || options.Profile == DumpProfile.Standards;

        if (!aborted && standardsEvidence && _cutList != null)
        {
            aborted |= !RunPhase(gaps, phases, "cutlist", "read the part cut lists", () =>
            {
                IReadOnlyList<CutListItem> items = _cutList.Dump(scope);

                // Assigned only when it carries rows, so the member and the JSON say the
                // same thing: "the phase ran and found none" is the `ok` row beside it, not
                // an empty array (contracts/ir-additions.md, additivity rule point 3).
                if (items.Count > 0)
                {
                    package.CutListItems = new List<CutListItem>(items);
                }
            });
        }

        // The drawing phase runs only when the root document IS a drawing (FR-025). The dump
        // does not go looking for the drawings of an open model: a drawing enters a package
        // when it is itself the dumped document, and not otherwise.
        bool drawingRoot = tree.RootDocumentKind == DocumentKind.Drawing;

        if (!aborted && standardsEvidence && drawingRoot && _drawings != null)
        {
            aborted |= !RunPhase(gaps, phases, "drawing", "read the drawing sheets", () =>
            {
                IReadOnlyList<DrawingRecord> records = _drawings.Dump(scope);
                if (records.Count > 0)
                {
                    package.DrawingRecords = new List<DrawingRecord>(records);
                }
            });
        }

        // The geometry phases - hole, tolerance (schema 1.5.0), fastener, face and body - gated
        // by the profile (plan key point 8). ModelCheck
        // skips them and records NOTHING beyond extractor.profile: unlike --features none
        // and --equations off, which are a dump that dropped evidence it normally carries
        // and so owe the reader a sentence, a model-check package's shape is declared once
        // on the extractor block. A gap per skipped phase on every check run would be noise an engineer
        // learns to skip, which is how a real gap gets lost (Principle I).
        bool geometry = options.Profile == DumpProfile.Full;

        if (!aborted && geometry)
        {
            aborted |= !RunPhase(gaps, phases, "hole", "read Hole Wizard features and cosmetic threads", () =>
            {
                HoleDumpResult result = _holes.Dump(scope);
                package.Holes.AddRange(result.Holes);
                package.Threads.AddRange(result.Threads);
            });
        }

        // The tolerance phase (schema 1.5.0, feature 010): the part documents' dimensions with
        // their tolerances, and their GTols and datum tags. Under the Full profile only, with
        // the geometry phases it sits among, because no Model check or Standards check reads it.
        // The arrays are assigned only when they carry rows, as the cut list's is.
        if (!aborted && geometry && _tolerances != null)
        {
            aborted |= !RunPhase(gaps, phases, "tolerance", "read model dimension tolerances and annotations", () =>
            {
                ToleranceDumpResult result = _tolerances.Dump(scope);
                if (result.Dimensions.Count > 0)
                {
                    package.ModelDimensions = new List<ModelDimension>(result.Dimensions);
                }

                if (result.Annotations.Count > 0)
                {
                    package.ModelAnnotations = new List<ModelAnnotation>(result.Annotations);
                }
            });
        }

        if (!aborted && geometry)
        {
            aborted |= !RunPhase(gaps, phases, "fastener", "identify fasteners", () =>
                package.Fasteners.AddRange(_fasteners.Dump(scope)));
        }

        if (!aborted && geometry)
        {
            aborted |= !RunPhase(gaps, phases, "face", "read face geometry", () =>
                package.Faces.AddRange(_faces.Dump(scope)));
        }

        if (!aborted && geometry && options.Meshes != MeshFormat.None)
        {
            string meshDirectory = Path.Combine(options.OutputDirectory, MeshDirectoryName);
            aborted |= !RunPhase(gaps, phases, "body", "tessellate bodies and write meshes", () =>
                package.Bodies.AddRange(_meshes.Dump(scope, meshDirectory)));
        }

        return Finish(package, scope, gaps, phases, options);
    }

    /// <summary>
    /// The tail every build shares: the component instances, the feature types the sweep did
    /// not read, the drawing gap, the phase timings, the reuse key and the gaps themselves.
    ///
    /// Shared with the reuse probe rather than repeated for it, so the probe's key is taken
    /// over the same package the dump would have hashed - a second copy of these five steps is
    /// a second chance for the two to disagree about what a package is.
    /// </summary>
    private static EvidencePackage Finish(
        EvidencePackage package,
        DumpScope scope,
        GapCollector gaps,
        PhaseLog phases,
        DumpOptions options)
    {
        AddComponentInstances(package, scope);
        AddSkippedFeatureTypes(scope);

        // Every phase, in run order, whether it ran or not: a phase that never started is
        // the fact a reader needs most when a package comes back thin, and without the row
        // it could only be inferred by guessing from which arrays came back empty.
        package.Extractor.Phases.AddRange(phases.Rows());

        // Conditional from schema 1.4.0 (006 contracts/ir-additions.md section 5): emitted
        // only when the drawing phase did not run, and then naming the profile that skipped
        // it. A drawing root dumped `full` or `standards` runs the phase and carries the
        // sheets, so the old unconditional gap would have sat beside the very evidence it
        // said was missing; and a reader who does see it is told which extract to run again
        // rather than a fact about the extractor that is no longer true (FR-024).
        if (!phases.Ran("drawing"))
        {
            gaps.Add(
                GapKind.Unsupported,
                "drawing",
                null,
                "Drawing sheets were not read natively: the drawing phase did not run under "
                + $"the '{PackageSerializer.EnumToJsonName(options.Profile)}' profile. Any "
                + "sheets in this package came from the PDF ingest.",
                null);
        }

        // Last, because the key is taken over the manifest and the component instances and
        // both are complete only now. Gaps are deliberately not in it: they are evidence
        // about the dump, not about the design, and a dump that stopped short is refused by
        // ReuseRefusals rather than hidden behind a key that happens not to match.
        package.ReuseKey = ReuseKey.Of(package, options);

        package.Gaps.AddRange(gaps.Gaps);
        return package;
    }

    /// <summary>
    /// The scope the phases share, with every traversed component given its id. Public
    /// because <c>probe rms</c> runs two phases outside a dump and must give them the SAME
    /// ids the package would have: a probe that numbered components differently would read
    /// as a contradiction of the package it was run to explain.
    /// </summary>
    public static DumpScope ScopeFor(GapCollector gaps, DumpOptions options, ComponentTreeResult tree)
    {
        var scope = new DumpScope(gaps, options, tree);
        AllocateComponentIds(scope);

        // A drawing root is the one drawing its own dump reads (feature 006); the open drawings
        // a review attaches join the list after discovery (feature 011).
        if (tree.RootDocumentKind == DocumentKind.Drawing)
        {
            scope.Drawings.Add(new ScopedDrawing(tree.RootDocumentPath, tree.RootDocument));
        }

        return scope;
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

            // The traversal could not name the component - cmp:NNNN is allocated here - so
            // a failed GetConstrainedStatus read waits on the node for its id. Recorded
            // before the refusals below, because a component that never reaches the package
            // still had its status read attempted (data-model section 1).
            if (node.ConstrainedStatusError != null)
            {
                scope.Gaps.Add(
                    GapKind.ToolError,
                    "component_constrained_status",
                    scoped.Id,
                    $"GetConstrainedStatus failed for '{node.Key}', so whether it is fully "
                    + "constrained is unknown and any check that needs it is unresolved.",
                    node.ConstrainedStatusError);
            }

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
                ConstrainedStatusRaw = node.ConstrainedStatusRaw,
                HasAppearanceOverride = node.HasAppearanceOverride,
                TransparencyRaw = node.TransparencyRaw,
                VisibilityRaw = node.VisibilityRaw,
                IsPatternInstance = node.IsPatternInstance,
            });
        }
    }

    /// <summary>
    /// One gap per document listing the <c>GetTypeName2</c> names the dumpers walked past
    /// without reading. Without it an unrecognised feature type is discarded silently and
    /// the only symptom is "holes: 0" with no error (Principle I). One gap per document,
    /// not one per feature: on a real part a gap for every CutExtrude is noise an engineer
    /// learns to skip, which is how the signal gets lost.
    /// </summary>
    private static void AddSkippedFeatureTypes(DumpScope scope)
    {
        foreach (DocumentTypeNames document in scope.Gaps.TypeNames.Unconsumed())
        {
            scope.Gaps.Add(
                GapKind.Unsupported,
                "feature",
                scope.DocumentId(document.DocumentPath),
                $"Skipped feature types in {Path.GetFileName(document.DocumentPath)}: {document.Describe()}. "
                + "SOLIDWORKS reported these GetTypeName2 names in the feature tree and no dumper reads them.",
                null);
        }
    }

    /// <summary>
    /// Every distinct document the tree referenced, root first.
    ///
    /// For a <b>drawing</b> root that is the drawing's own path plus every referenced model
    /// the traversal hung a subtree for, so a drawing document enters <c>documents[]</c> and
    /// the manifest for the first time (schema 1.4.0, contracts/ir-additions.md section 7).
    /// No drawing-shaped branch is needed for it: the root is the root whatever its kind, and
    /// the referenced models arrive as nodes, which is exactly why
    /// <see cref="ComponentTreeDumper"/> hangs them under a synthesized forest root rather
    /// than reporting them some other way. The drawing's own custom properties then come from
    /// the document phase, which is what <c>standards.drawing.revision_matches</c> compares a
    /// revision table against.
    /// </summary>
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

    /// <summary>
    /// The design block. <c>root_assembly_document_id</c> holds the ROOT document's id
    /// whatever its kind - already true for a part opened alone since feature 003, and for a
    /// drawing root it is the drawing's. The field's name is a misnomer feature 003 made and
    /// this feature does not rename it: renaming a required IR field is a breaking change and
    /// the value is unambiguous.
    ///
    /// <c>drawing_document_ids</c> has existed in the IR since feature 001 and has never been
    /// set by a native dump (schema 1.4.0). It carries the drawing root and nothing else,
    /// because the dump does not go looking for the drawings of an open model: a drawing
    /// enters a package when it is itself the dumped document, and not otherwise (FR-025). An
    /// empty list is therefore a statement rather than an omission.
    /// </summary>
    private static Design BuildDesign(ComponentTreeResult tree)
    {
        var design = new Design
        {
            DesignId = DocumentIds.DesignId(tree.RootDocumentPath),
            Name = tree.DesignName,
            RootAssemblyDocumentId = DocumentIds.For(tree.RootDocumentPath),
            ActiveConfiguration = tree.ActiveConfiguration,
        };

        if (tree.RootDocumentKind == DocumentKind.Drawing)
        {
            design.DrawingDocumentIds.Add(DocumentIds.For(tree.RootDocumentPath));
        }

        return design;
    }

    private ExtractorInfo BuildExtractorInfo(DumpOptions options) => new ExtractorInfo
    {
        Name = "SwReview.Extractor",
        Version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "0.0.0",
        SwVersion = _swVersion,
        Machine = _machine,

        // The profile is what tells a reader that holes[], fasteners[], faces[] and
        // bodies[] are empty by design rather than because the dump lost them, which is
        // why the skipped phases below record nothing else (schema 1.2.0, FR-022).
        Profile = options.Profile,
    };

    /// <summary>
    /// Runs one phase, timed. Returns false when the session is gone and the remaining
    /// phases must be skipped; any other failure is recorded and the dump continues.
    ///
    /// The clock is read in a <c>finally</c>, so a phase that threw still reports the time
    /// it spent before it did: the dump spent that time either way, and a failed phase with
    /// no elapsed time would read exactly like one that never ran.
    /// </summary>
    private static bool RunPhase(
        GapCollector gaps, PhaseLog phases, string entityKind, string description, Action phase)
    {
        Stopwatch clock = Stopwatch.StartNew();
        DumpPhaseStatus status = DumpPhaseStatus.Ok;
        try
        {
            phase();
            return true;
        }
        catch (CircuitOpenError ex)
        {
            status = DumpPhaseStatus.Aborted;
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
            status = DumpPhaseStatus.Failed;
            gaps.Record(entityKind, null, $"Failed to {description}.", ex);
            return true;
        }
        finally
        {
            clock.Stop();
            phases.Record(entityKind, clock.ElapsedMilliseconds, status);
        }
    }

    /// <summary>
    /// What each phase cost and what became of it (feature 005 T033).
    ///
    /// Rows come out in <see cref="PhaseOrder"/> rather than in the order they were
    /// recorded, and every phase in that list gets one: a phase the dump never reached -
    /// switched off by the profile or the options, or behind one that aborted - is
    /// <c>skipped</c> with no elapsed time rather than absent, because "it ran and the row
    /// was lost" and "it never ran" are not the same package.
    ///
    /// It lives for one <see cref="Build"/> call and is passed down rather than held on the
    /// writer, so two dumps through one writer cannot pour their timings into each other.
    /// </summary>
    private sealed class PhaseLog
    {
        private readonly Dictionary<string, DumpPhase> _rows =
            new Dictionary<string, DumpPhase>(StringComparer.Ordinal);

        /// <summary>
        /// Whether a row was recorded for <paramref name="name"/> - that is, whether the
        /// phase actually started. A phase that threw or met an open circuit still ran, so
        /// it answers true: what this distinguishes is "ran" from "never started".
        /// </summary>
        public bool Ran(string name) => _rows.ContainsKey(name);

        public void Record(string name, long elapsedMilliseconds, DumpPhaseStatus status)
        {
            _rows[name] = new DumpPhase
            {
                Name = name,

                // Clamped rather than cast unchecked: int.MaxValue milliseconds is 24 days,
                // so this is only reachable by a clock that went wrong, and a wrapped
                // negative would be refused by every reader of the contract.
                ElapsedMs = (int)Math.Min(Math.Max(elapsedMilliseconds, 0L), int.MaxValue),
                Status = status,
            };
        }

        public IEnumerable<DumpPhase> Rows() => PhaseOrder.Select(
            name => _rows.TryGetValue(name, out DumpPhase row)
                ? row
                : new DumpPhase { Name = name, ElapsedMs = null, Status = DumpPhaseStatus.Skipped });
    }
}
