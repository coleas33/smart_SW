using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T058. Every phase of the dump is an interface, so the orchestration - id order, gap
/// merging, what a failed phase does to the rest of the dump, the shape of the file that
/// lands on disk - is tested here with fakes, on a machine with no SOLIDWORKS seat.
/// </summary>
public class PackageWriterTests : IDisposable
{
    private readonly string _outputDirectory;

    public PackageWriterTests()
    {
        _outputDirectory = Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_outputDirectory))
        {
            Directory.Delete(_outputDirectory, recursive: true);
        }
    }

    [Fact]
    public void Build_AllocatesComponentIdsInTraversalOrder()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Equal(new[] { "cmp:0001", "cmp:0002", "cmp:0003" }, package.Components.Select(c => c.Id));
        Assert.Equal(
            new[] { "bracket-assy-1", "housing-1", "screw-1" },
            package.Components.Select(c => c.FullPath));
    }

    [Fact]
    public void Build_LinksChildrenToTheirParentById()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Null(package.Components[0].ParentId);
        Assert.Equal("cmp:0001", package.Components[1].ParentId);
        Assert.Equal("cmp:0001", package.Components[2].ParentId);
    }

    [Fact]
    public void Build_CarriesTheComponentsRawConstrainedStatusThroughToThePackage()
    {
        // T006. The first-component rule reads this number, so it has to survive the whole
        // way from the traversal to package.json. An unread status stays null: the rule
        // reports unresolved rather than treating "not read" as "not constrained".
        var sources = new FakeSources();
        sources.Nodes[1].ConstrainedStatusRaw = 2;

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(2, package.Components[1].ConstrainedStatusRaw);
        Assert.Null(package.Components[2].ConstrainedStatusRaw);
    }

    [Fact]
    public void Build_ConstrainedStatusThatCouldNotBeRead_IsAGapNamingTheComponent()
    {
        // data-model.md section 1: every added gap entity kind names one entity_id. The
        // traversal cannot name one - cmp:NNNN is allocated here - so it carries the
        // failure on the node and the gap is written where the id exists.
        var sources = new FakeSources();
        sources.Nodes[1].ConstrainedStatusError = "COMException: the component did not answer.";

        EvidencePackage package = NewWriter(sources).Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "component_constrained_status");
        Assert.Equal("cmp:0002", gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Equal("COMException: the component did not answer.", gap.Error);
        Assert.Contains("housing-1", gap.Reason, StringComparison.Ordinal);
        Assert.Null(package.Components[1].ConstrainedStatusRaw);
    }

    [Fact]
    public void Build_ConstrainedStatusThatWasRead_RaisesNoGap()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.DoesNotContain(package.Gaps, g => g.EntityKind == "component_constrained_status");
    }

    [Fact]
    public void Build_CarriesMateSuppressionThroughToThePackage()
    {
        // The chain-depth rule must not walk a suppressed mate as an edge.
        Assert.False(Assert.Single(NewWriter().Build(Options()).Mates).Suppressed);

        var sources = new FakeSources();
        sources.MateSuppressed = true;

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.True(Assert.Single(package.Mates).Suppressed);
    }

    [Fact]
    public void Build_GivesTheSameFileTheSameDocumentIdEveryDump()
    {
        EvidencePackage first = NewWriter().Build(Options());
        EvidencePackage second = NewWriter().Build(Options());

        Assert.Equal(first.Components[1].DocumentId, second.Components[1].DocumentId);
        Assert.Equal(first.Design.RootAssemblyDocumentId, second.Design.RootAssemblyDocumentId);
    }

    [Fact]
    public void Build_PutsEveryReferencedDocumentInTheDocumentsList()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Equal(3, package.Documents.Count);
        foreach (ComponentInstance component in package.Components)
        {
            Assert.Contains(package.Documents, d => d.DocumentId == component.DocumentId);
        }
    }

    [Fact]
    public void Build_ScopesThePersistRefToTheDocumentThatProducedIt()
    {
        EvidencePackage package = NewWriter().Build(Options());

        string assemblyDocumentId = package.Design.RootAssemblyDocumentId;
        Assert.All(package.Components, c => Assert.Equal(assemblyDocumentId, c.PersistRefScope));
    }

    [Fact]
    public void Build_IncludesTheManifestTheSourceProduced()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Equal(3, package.Manifest.Entries.Count);
        Assert.All(package.Manifest.Entries, e => Assert.Equal(ExportMethod.Native, e.ExportMethod));
    }

    [Fact]
    public void Build_MergesGapsFromEveryPhase()
    {
        var sources = new FakeSources();
        sources.TraversalGap = "a suppressed child could not be resolved";
        sources.HoleGap = "GetDefinition returned null for Hole1";

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Contains(package.Gaps, g => g.Reason == sources.TraversalGap);
        Assert.Contains(package.Gaps, g => g.Reason == sources.HoleGap);
    }

    [Fact]
    public void Build_RecordsThatDrawingsAreNotExtractedNatively()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "drawing");
        Assert.Equal(GapKind.Unsupported, gap.Kind);
    }

    [Fact]
    public void Build_FeatureTypesNoDumperRead_BecomeOneUnsupportedGapPerDocument()
    {
        var sources = new FakeSources();
        sources.SeeFeatureTypes(
            ("HoleWzd", true),
            ("CosmeticThread", true),
            ("AdvHoleWzd", false),
            ("AdvHoleWzd", false),
            ("CutExtrude", false));

        EvidencePackage package = NewWriter(sources).Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "feature");
        Assert.Equal(GapKind.Unsupported, gap.Kind);
        Assert.Equal(package.Components[1].DocumentId, gap.EntityId);
        Assert.Contains("housing.SLDPRT", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("AdvHoleWzd x2", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("CutExtrude x1", gap.Reason, StringComparison.Ordinal);
        Assert.DoesNotContain("CosmeticThread", gap.Reason, StringComparison.Ordinal);
        Assert.Null(gap.Error);
    }

    [Fact]
    public void Build_FeatureCensusGap_ReadsAsOneLineInValidateOutput()
    {
        var sources = new FakeSources();
        sources.SeeFeatureTypes(("FtrFolder", false));

        EvidencePackage package = NewWriter(sources).Build(Options());

        string reason = Assert.Single(package.Gaps, g => g.EntityKind == "feature").Reason;
        Assert.DoesNotContain('\n', reason);
        Assert.DoesNotContain('\r', reason);
    }

    [Fact]
    public void Build_EveryFeatureTypeWasRead_EmitsNoCensusGap()
    {
        var sources = new FakeSources();
        sources.SeeFeatureTypes(("HoleWzd", true));

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.DoesNotContain(package.Gaps, g => g.EntityKind == "feature");
    }

    [Fact]
    public void Build_NoDumperCensusedAnything_EmitsNoCensusGap()
    {
        Assert.DoesNotContain(NewWriter().Build(Options()).Gaps, g => g.EntityKind == "feature");
    }

    [Fact]
    public void Build_FeatureWithNoTypeName_IsCountedUnderAReadablePlaceholder()
    {
        // GetTypeName2 can come back blank; the feature was still walked past and still
        // not read, so it stays visible in the gap instead of vanishing (Principle I).
        var sources = new FakeSources();
        sources.SeeFeatureTypes((string.Empty, false), ("CutExtrude", false));

        EvidencePackage package = NewWriter(sources).Build(Options());

        string reason = Assert.Single(package.Gaps, g => g.EntityKind == "feature").Reason;
        Assert.Contains("(no type name) x1", reason, StringComparison.Ordinal);
        Assert.Contains("CutExtrude x1", reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_RootFeatureTypesTheTraversalWalkedPast_BecomeAGapForTheRootDocument()
    {
        // ComponentTreeDumper censuses the root assembly's own feature tree during
        // Traverse, before any phase runs; the fake mirrors that.
        var sources = new FakeSources();
        sources.SeeRootFeatureTypes(("LocalLPattern", true), ("MateGroup", false));

        EvidencePackage package = NewWriter(sources).Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "feature");
        Assert.Equal(package.Components[0].DocumentId, gap.EntityId);
        Assert.Contains("MateGroup x1", gap.Reason, StringComparison.Ordinal);
        Assert.DoesNotContain("LocalLPattern", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_ACensusGapStillValidatesAgainstTheContract()
    {
        var sources = new FakeSources();
        sources.SeeFeatureTypes(("AdvHoleWzd", false));

        IrContract.AssertValid(PackageSerializer.Serialize(NewWriter(sources).Build(Options())));
    }

    [Fact]
    public void Build_ComponentWithNoPersistRef_BecomesAGapNotAnUnnavigableInstance()
    {
        var sources = new FakeSources();
        sources.Nodes[2].PersistRef = null;

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(2, package.Components.Count);
        Assert.Contains(package.Gaps, g => g.EntityKind == "component" && g.EntityId == "cmp:0003");
    }

    [Fact]
    public void Build_ComponentWithNoFilePath_BecomesAGapAndDoesNotConsumeAnId()
    {
        var sources = new FakeSources();
        sources.Nodes[1].DocumentPath = string.Empty;

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(new[] { "cmp:0001", "cmp:0002" }, package.Components.Select(c => c.Id));
        Assert.Equal("screw-1", package.Components[1].FullPath);
        Assert.Contains(package.Gaps, g => g.EntityKind == "component" && g.Reason.Contains("housing-1"));
    }

    [Fact]
    public void Build_FailingPhase_BecomesAGapAndTheLaterPhasesStillRun()
    {
        var sources = new FakeSources();
        sources.MateFailure = new InvalidOperationException("GetMates blew up");

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Empty(package.Mates);
        Assert.Contains(package.Gaps, g => g.EntityKind == "mate" && g.Error!.Contains("GetMates blew up"));

        // The dump continued: holes, fasteners and faces are all present.
        Assert.NotEmpty(package.Holes);
        Assert.NotEmpty(package.Fasteners);
        Assert.NotEmpty(package.Faces);
    }

    [Fact]
    public void Build_OpenCircuit_StopsTheRemainingPhasesAndStillProducesAPackage()
    {
        var sources = new FakeSources();
        sources.MateFailure = new CircuitOpenError("the circuit is open");

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Contains(package.Gaps, g => g.EntityKind == "mate" && g.Reason.Contains("stopped answering"));
        Assert.Empty(package.Holes);
        Assert.Empty(package.Fasteners);
        Assert.Empty(package.Faces);

        // What was gathered before the session died survives.
        Assert.Equal(3, package.Components.Count);
        Assert.Equal(3, package.Documents.Count);
    }

    [Fact]
    public void Build_MeshesNone_SkipsTheMeshPhase()
    {
        var sources = new FakeSources();
        DumpOptions options = Options();
        options.Meshes = MeshFormat.None;

        EvidencePackage package = NewWriter(sources).Build(options);

        Assert.Empty(package.Bodies);
        Assert.False(sources.MeshesWereDumped);
    }

    [Fact]
    public void Build_MeshesGlb_RunsTheMeshPhaseIntoTheMeshesDirectory()
    {
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.NotEmpty(package.Bodies);
        Assert.EndsWith(Path.Combine("native", "meshes"), sources.MeshDirectory!, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_CarriesTheFeatureRowsThroughToThePackage()
    {
        // T024. The RMS rules read features[]; a phase whose rows never reach the package
        // would leave every part rule unresolved with nothing saying why.
        EvidencePackage package = NewWriter().Build(Options());

        Ir.Feature feature = Assert.Single(package.Features);
        Assert.Equal("feat:0001", feature.Id);
        Assert.Equal(package.Components[1].DocumentId, feature.DocumentId);
    }

    [Fact]
    public void Build_FeaturesNone_SkipsTheFeaturePhase()
    {
        var sources = new FakeSources();
        DumpOptions options = Options();
        options.Features = FeatureScope.None;

        EvidencePackage package = NewWriter(sources).Build(options);

        Assert.Empty(package.Features);
        Assert.False(sources.FeaturesWereDumped);
    }

    [Fact]
    public void Build_FeaturesNone_RecordsThatNoTreeWasRead()
    {
        // Without this gap the package is indistinguishable from one whose parts have empty
        // trees, and every part rule would report a vacuous pass over a tree nobody opened
        // (constitution Principle I: missing coverage stays visible).
        DumpOptions options = Options();
        options.Features = FeatureScope.None;

        EvidencePackage package = NewWriter().Build(options);

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "feature_tree_unavailable");
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Null(gap.EntityId);
        Assert.Contains("--features none", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_FeaturesTree_RecordsNoFeatureTreeUnavailableGapOfItsOwn()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.DoesNotContain(package.Gaps, g => g.EntityKind == "feature_tree_unavailable");
    }

    [Fact]
    public void Build_FeaturesDefaultsToTheTreePhaseRunning()
    {
        var sources = new FakeSources();

        NewWriter(sources).Build(Options());

        Assert.Equal(FeatureScope.Tree, sources.SeenOptions!.Features);
        Assert.True(sources.FeaturesWereDumped);
    }

    [Fact]
    public void Build_CarriesTheEquationRowsThroughToThePackage()
    {
        // T038. The two parametric rules read equations[]; rows that never reach the
        // package would leave both of them unresolved with nothing saying why.
        EvidencePackage package = NewWriter().Build(Options());

        Equation equation = Assert.Single(package.Equations);
        Assert.Equal(package.Components[1].DocumentId, equation.DocumentId);
        Assert.Equal("WallThickness", equation.Lhs);
    }

    [Fact]
    public void Build_EquationsOff_SkipsTheEquationPhase()
    {
        var sources = new FakeSources();
        DumpOptions options = Options();
        options.Equations = EquationScope.Off;

        EvidencePackage package = NewWriter(sources).Build(options);

        Assert.Empty(package.Equations);
        Assert.False(sources.EquationsWereDumped);
    }

    [Fact]
    public void Build_EquationsOff_RecordsThatNoEquationsWereRead()
    {
        // Without this gap the package is indistinguishable from one whose parts have no
        // equations at all, and rms.params.global_variables_present would report a finding
        // against an equation manager nobody opened (constitution Principle I).
        DumpOptions options = Options();
        options.Equations = EquationScope.Off;

        EvidencePackage package = NewWriter().Build(options);

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "equations");
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Null(gap.EntityId);
        Assert.Contains("--equations off", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_EquationsOn_RecordsNoEquationsGapOfItsOwn()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.DoesNotContain(package.Gaps, g => g.EntityKind == "equations");
    }

    [Fact]
    public void Build_EquationsDefaultsToThePhaseRunning()
    {
        var sources = new FakeSources();

        NewWriter(sources).Build(Options());

        Assert.Equal(EquationScope.On, sources.SeenOptions!.Equations);
        Assert.True(sources.EquationsWereDumped);
    }

    [Fact]
    public void Build_PassesTheOptionsThroughToTheSources()
    {
        var sources = new FakeSources();
        DumpOptions options = Options();
        options.Faces = FaceScope.All;
        options.Configuration = "as-shipped";

        NewWriter(sources).Build(options);

        Assert.Equal(FaceScope.All, sources.SeenOptions!.Faces);
        Assert.Equal("as-shipped", sources.SeenOptions.Configuration);
    }

    [Fact]
    public void Build_FillsTheExtractorBlock()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Equal("SwReview.Extractor", package.Extractor.Name);
        Assert.Equal("2024 SP5", package.Extractor.SwVersion);
        Assert.Equal("TEST-WORKSTATION", package.Extractor.Machine);
        Assert.NotEmpty(package.Extractor.Version);
    }

    [Fact]
    public void Build_FillsTheDesignBlockFromTheRootDocument()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Equal("bracket-assy", package.Design.Name);
        Assert.Equal("Default", package.Design.ActiveConfiguration);
        Assert.StartsWith("dsn:", package.Design.DesignId, StringComparison.Ordinal);
        Assert.StartsWith("doc:", package.Design.RootAssemblyDocumentId, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_UsesTheCurrentSchemaVersion()
    {
        Assert.Equal(EvidencePackage.CurrentSchemaVersion, NewWriter().Build(Options()).SchemaVersion);
    }

    [Fact]
    public void Build_ProducesAPackageThatValidatesAgainstTheContract()
    {
        IrContract.AssertValid(PackageSerializer.Serialize(NewWriter().Build(Options())));
    }

    [Fact]
    public void Build_APackageFullOfGapsStillValidatesAgainstTheContract()
    {
        var sources = new FakeSources();
        sources.MateFailure = new CircuitOpenError("the circuit is open");
        sources.Nodes[2].PersistRef = null;

        IrContract.AssertValid(PackageSerializer.Serialize(NewWriter(sources).Build(Options())));
    }

    [Fact]
    public void Write_WritesPackageJsonIntoTheOutputDirectory()
    {
        DumpResult result = NewWriter().Write(Options());

        Assert.True(File.Exists(result.PackageFilePath));
        Assert.Equal(PackageWriter.PackageFileName, Path.GetFileName(result.PackageFilePath));

        EvidencePackage reloaded = PackageSerializer.Deserialize(File.ReadAllText(result.PackageFilePath));
        Assert.Equal(3, reloaded.Components.Count);
        Assert.Equal(result.Package.PackageId, reloaded.PackageId);
    }

    [Fact]
    public void Write_CreatesTheOutputDirectoryIfItIsMissing()
    {
        Assert.False(Directory.Exists(_outputDirectory));

        NewWriter().Write(Options());

        Assert.True(Directory.Exists(Path.Combine(_outputDirectory, "native")));
    }

    [Fact]
    public void Write_MissingOutputDirectory_Throws()
    {
        var options = new DumpOptions { OutputDirectory = "  " };

        Assert.Throws<ArgumentException>(() => NewWriter().Write(options));
    }

    [Fact]
    public void Build_UnsavedDocument_IsRefusedWithAReadableMessage()
    {
        var sources = new FakeSources { RootDocumentPath = string.Empty };

        InvalidOperationException error =
            Assert.Throws<InvalidOperationException>(() => NewWriter(sources).Build(Options()));

        Assert.Contains("never been saved", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_PersistRefWithNoScope_FallsBackToTheComponentsOwnDocumentAndSaysSo()
    {
        var sources = new FakeSources();
        sources.Nodes[1].PersistRefScopePath = string.Empty;

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(package.Components[1].DocumentId, package.Components[1].PersistRefScope);
        Assert.Contains(package.Gaps, g => g.EntityId == "cmp:0002" && g.Reason.Contains("names no scope"));
    }

    [Fact]
    public void Constructor_NullSource_Throws()
    {
        var sources = new FakeSources();

        Assert.Throws<ArgumentNullException>(() => new PackageWriter(
            null!, sources, sources, sources, sources, sources, sources, sources, sources, sources,
            "2024 SP5"));

        Assert.Throws<ArgumentNullException>(() => new PackageWriter(
            sources, sources, sources, sources, null!, sources, sources, sources, sources, sources,
            "2024 SP5"));

        Assert.Throws<ArgumentNullException>(() => new PackageWriter(
            sources, sources, sources, sources, sources, null!, sources, sources, sources, sources,
            "2024 SP5"));
    }

    private DumpOptions Options() => new DumpOptions
    {
        OutputDirectory = Path.Combine(_outputDirectory, "native"),
    };

    private static PackageWriter NewWriter(FakeSources? sources = null)
    {
        FakeSources s = sources ?? new FakeSources();
        return new PackageWriter(s, s, s, s, s, s, s, s, s, s, "2024 SP5", "TEST-WORKSTATION");
    }

    /// <summary>
    /// One class standing in for all nine phases. It returns canned IR objects, so the
    /// test exercises PackageWriter and nothing else.
    /// </summary>
    private sealed class FakeSources
        : IComponentTreeSource, IDocumentSource, IManifestSource, IMateSource, IFeatureSource,
          IEquationSource, IHoleSource, IFastenerSource, IFaceSource, IMeshSource
    {
        private const string AssemblyPath = @"C:\vault\bracket-assy\bracket-assy.SLDASM";
        private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
        private const string ScrewPath = @"C:\vault\toolbox\hex-cap-screw.SLDPRT";

        private readonly List<TypeNameSighting> _holePass = new List<TypeNameSighting>();

        private readonly List<TypeNameSighting> _traversalPass = new List<TypeNameSighting>();

        public List<ComponentNode> Nodes { get; } = new List<ComponentNode>
        {
            NewNode("bracket-assy-1", null, AssemblyPath, DocumentKind.Assembly),
            NewNode("housing-1", "bracket-assy-1", HousingPath, DocumentKind.Part),
            NewNode("screw-1", "bracket-assy-1", ScrewPath, DocumentKind.Part),
        };

        public string RootDocumentPath { get; set; } = AssemblyPath;

        public string? TraversalGap { get; set; }

        public string? HoleGap { get; set; }

        public Exception? MateFailure { get; set; }

        /// <summary>What the mate phase read off the mate feature's IsSuppressed2.</summary>
        public bool MateSuppressed { get; set; }

        public bool MeshesWereDumped { get; private set; }

        public bool FeaturesWereDumped { get; private set; }

        public bool EquationsWereDumped { get; private set; }

        public string? MeshDirectory { get; private set; }

        public DumpOptions? SeenOptions { get; private set; }

        /// <summary>
        /// The feature type names the hole phase will report having walked over the housing
        /// part, the way <see cref="HoleDumper"/> reports one census pass per component.
        /// </summary>
        public void SeeFeatureTypes(params (string TypeName, bool Consumed)[] sightings)
        {
            foreach ((string TypeName, bool Consumed) sighting in sightings)
            {
                _holePass.Add(new TypeNameSighting(sighting.TypeName, sighting.Consumed));
            }
        }

        /// <summary>
        /// The feature type names the traversal will report having walked over the root
        /// assembly, the way <see cref="ComponentTreeDumper"/> censuses the root's own
        /// feature tree from inside Traverse.
        /// </summary>
        public void SeeRootFeatureTypes(params (string TypeName, bool Consumed)[] sightings)
        {
            foreach ((string TypeName, bool Consumed) sighting in sightings)
            {
                _traversalPass.Add(new TypeNameSighting(sighting.TypeName, sighting.Consumed));
            }
        }

        public ComponentTreeResult Traverse(GapCollector gaps, DumpOptions options)
        {
            SeenOptions = options;
            if (TraversalGap != null)
            {
                gaps.Add(GapKind.NotExtracted, "component", null, TraversalGap, null);
            }

            var tree = new ComponentTreeResult
            {
                RootDocumentPath = RootDocumentPath,
                RootDocumentKind = DocumentKind.Assembly,
                DesignName = "bracket-assy",
                ActiveConfiguration = "Default",
            };

            tree.Nodes.AddRange(Nodes);

            // Guarded exactly as ComponentTreeDumper.ReadPatternMembership guards it: an
            // unsaved document has no path to census under, and Build must reach its own
            // refusal rather than dying inside the census.
            if (!string.IsNullOrWhiteSpace(RootDocumentPath))
            {
                gaps.TypeNames.AddPass(RootDocumentPath, _traversalPass);
            }

            return tree;
        }

        public IReadOnlyList<Document> Dump(DumpScope scope, IReadOnlyList<string> documentPaths) =>
            documentPaths.Select(path => new Document
            {
                DocumentId = scope.DocumentId(path),
                Kind = path.EndsWith(".SLDASM", StringComparison.OrdinalIgnoreCase)
                    ? DocumentKind.Assembly
                    : DocumentKind.Part,
                FileName = Path.GetFileName(path),
                Path = path,
                Configurations = { "Default" },
                ActiveConfiguration = "Default",
                Material = null,
                Mass = null,
            }).ToList();

        public Manifest Build(DumpScope scope, IReadOnlyList<Document> documents)
        {
            var manifest = new Manifest();
            foreach (Document document in documents)
            {
                manifest.Entries.Add(new ManifestEntry
                {
                    DocumentId = document.DocumentId,
                    VaultPath = document.Path,
                    VaultVersion = null,
                    Revision = null,
                    Configuration = document.ActiveConfiguration,
                    LocalModified = null,
                    ExportMethod = ExportMethod.Native,
                });
            }

            return manifest;
        }

        IReadOnlyList<Mate> IMateSource.Dump(DumpScope scope)
        {
            if (MateFailure != null)
            {
                throw MateFailure;
            }

            return new List<Mate>
            {
                new Mate
                {
                    Id = scope.MateIds.Next(),
                    PersistRef = "TWF0ZQ==",
                    PersistRefScope = scope.DocumentId(AssemblyPath),
                    Type = "swMateCONCENTRIC",
                    Alignment = MateAlignment.Aligned,
                    Suppressed = MateSuppressed,
                    Entities =
                    {
                        new MateEntityRef
                        {
                            ComponentId = scope.Components[1].Id,
                            PersistRef = "TWF0ZUVudDE=",
                            EntityKind = "face",
                        },
                        new MateEntityRef
                        {
                            ComponentId = scope.Components[2].Id,
                            PersistRef = "TWF0ZUVudDI=",
                            EntityKind = "face",
                        },
                    },
                },
            };
        }

        IReadOnlyList<Ir.Feature> IFeatureSource.Dump(DumpScope scope)
        {
            FeaturesWereDumped = true;

            return new List<Ir.Feature>
            {
                new Ir.Feature
                {
                    Id = scope.FeatureIds.Next(),
                    PersistRef = "RmVhdA==",
                    PersistRefScope = scope.DocumentId(HousingPath),
                    DocumentId = scope.DocumentId(HousingPath),
                    Configuration = "Default",
                    Name = "Boss-Extrude1",
                    TypeName = "Extrusion",
                    Description = string.Empty,
                    Index = 0,
                    Depth = 0,
                    FolderId = null,
                    Suppressed = false,
                    ErrorCode = 0,
                    ChildIds = new List<string>(),
                    ParentIds = new List<string>(),
                },
            };
        }

        IReadOnlyList<Equation> IEquationSource.Dump(DumpScope scope)
        {
            EquationsWereDumped = true;

            return new List<Equation>
            {
                new Equation
                {
                    DocumentId = scope.DocumentId(HousingPath),
                    Index = 0,
                    Text = "\"WallThickness\" = 3",
                    Lhs = "WallThickness",
                    IsGlobal = true,
                    Value = 3.0,
                },
            };
        }

        HoleDumpResult IHoleSource.Dump(DumpScope scope)
        {
            if (HoleGap != null)
            {
                scope.Gaps.Add(GapKind.NotExtracted, "hole", null, HoleGap, null);
            }

            if (_holePass.Count > 0)
            {
                scope.Gaps.TypeNames.AddPass(HousingPath, _holePass);
            }

            var result = new HoleDumpResult();
            result.Holes.Add(new Hole
            {
                Id = scope.HoleIds.Next(),
                PersistRef = "SG9sZQ==",
                PersistRefScope = scope.DocumentId(HousingPath),
                ComponentId = scope.Components[1].Id,
                FeatureName = "M6 Tapped Hole1",
                HoleType = HoleType.Tapped,
                ThreadDepth = null,
                HoleDepth = new Quantity(0.012, LengthUnit.M),
                EndCondition = EndCondition.Blind,
            });

            return result;
        }

        IReadOnlyList<Fastener> IFastenerSource.Dump(DumpScope scope) => new List<Fastener>
        {
            new Fastener
            {
                Id = scope.FastenerIds.Next(),
                PersistRef = "RmFzdA==",
                PersistRefScope = scope.DocumentId(AssemblyPath),
                ComponentId = scope.Components[2].Id,
                Kind = FastenerKind.Screw,
                IdentitySource = IdentitySource.NameParse,
                ThreadDesignation = "M6",
                Length = new Quantity(0.02, LengthUnit.M),
            },
        };

        IReadOnlyList<FaceGeometry> IFaceSource.Dump(DumpScope scope) => new List<FaceGeometry>
        {
            new FaceGeometry
            {
                Id = scope.FaceIds.Next(),
                PersistRef = "RmFjZQ==",
                PersistRefScope = scope.DocumentId(HousingPath),
                ComponentId = scope.Components[1].Id,
                BodyId = "bod:0001",
                Kind = FaceKind.Cylinder,
                Cylinder = new CylinderSurface
                {
                    AxisOrigin = new Vec3(0, 0, 0),
                    AxisDir = new Vec3(0, 0, 1),
                    RadiusM = 0.003,
                },
            },
        };

        IReadOnlyList<BodyRef> IMeshSource.Dump(DumpScope scope, string meshDirectory)
        {
            MeshesWereDumped = true;
            MeshDirectory = meshDirectory;

            return new List<BodyRef>
            {
                new BodyRef
                {
                    Id = scope.BodyIds.Next(),
                    PersistRef = "Qm9keQ==",
                    PersistRefScope = scope.DocumentId(HousingPath),
                    ComponentId = scope.Components[1].Id,
                    MeshFile = "meshes/cmp-0002-bod-0001.glb",
                    TriangleCount = 12,
                    IsSolid = true,
                },
            };
        }

        private static ComponentNode NewNode(string key, string? parentKey, string path, DocumentKind kind) =>
            new ComponentNode
            {
                Key = key,
                ParentKey = parentKey,
                Name = key,
                DocumentPath = path,
                DocumentKind = kind,
                ReferencedConfiguration = "Default",
                Transform = Transform.Identity(),
                Suppression = SuppressionState.Resolved,
                PersistRef = "Q29tcA==",
                PersistRefScopePath = AssemblyPath,
            };
    }
}
