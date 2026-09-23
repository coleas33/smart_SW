using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using IrMeasure = SwReview.Extractor.Ir.Measure;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T058. Every phase of the dump is an interface, so the orchestration - id order, gap
/// merging, what a failed phase does to the rest of the dump, the shape of the file that
/// lands on disk - is tested here with fakes, on a machine with no SOLIDWORKS seat.
/// </summary>
public class PackageWriterTests : IDisposable
{
    private const string AssemblyPath = @"C:\vault\bracket-assy\bracket-assy.SLDASM";
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
    private const string ScrewPath = @"C:\vault\toolbox\hex-cap-screw.SLDPRT";

    /// <summary>The two open drawings the discovery tests attach (feature 011 T020).</summary>
    private const string AssemblyDrawingPath = @"C:\vault\bracket-assy\bracket-assy.SLDDRW";
    private const string HousingDrawingPath = @"C:\vault\bracket-assy\housing.SLDDRW";

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
    public void Build_CarriesTheFourSchema140ComponentReadsThroughToThePackage()
    {
        // T034. The appearance override, the transparency slot, the visibility state and the
        // pattern origin are read in ComponentTreeDumper.ReadNode and have to survive the
        // whole way to package.json, exactly as IsFixed and IsToolbox do. A read that did not
        // happen stays null: the rules report unresolved rather than treating "not read" as
        // "not transparent" or "not hidden".
        var sources = new FakeSources();
        ComponentNode node = sources.Nodes[1];
        node.HasAppearanceOverride = true;
        node.TransparencyRaw = 0.75;
        node.VisibilityRaw = 0;
        node.IsPatternInstance = true;
        node.PatternId = "LocalLPattern1";

        EvidencePackage package = NewWriter(sources).Build(Options());

        ComponentInstance instance = package.Components[1];
        Assert.True(instance.HasAppearanceOverride);
        Assert.Equal(0.75, instance.TransparencyRaw);
        Assert.Equal(0, instance.VisibilityRaw);
        Assert.True(instance.IsPatternInstance);

        // pattern_id keeps the pattern's NAME for the reason text and does not stand in for
        // the flag; the two travel independently.
        Assert.Equal("LocalLPattern1", instance.PatternId);

        ComponentInstance unread = package.Components[2];
        Assert.Null(unread.HasAppearanceOverride);
        Assert.Null(unread.TransparencyRaw);
        Assert.Null(unread.VisibilityRaw);
        Assert.Null(unread.IsPatternInstance);
        Assert.Null(unread.PatternId);
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

    // ---- --profile ---------------------------------------------------------------

    [Fact]
    public void Build_ProfileDefaultsToFullAndEveryPhaseRuns()
    {
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(DumpProfile.Full, sources.SeenOptions!.Profile);
        Assert.True(sources.DocumentsWereDumped);
        Assert.True(sources.ManifestWasBuilt);
        Assert.True(sources.MatesWereDumped);
        Assert.True(sources.FeaturesWereDumped);
        Assert.True(sources.EquationsWereDumped);
        Assert.True(sources.CutListWasDumped);
        Assert.True(sources.HolesWereDumped);
        Assert.True(sources.FastenersWereDumped);
        Assert.True(sources.FacesWereDumped);
        Assert.True(sources.MeshesWereDumped);
        Assert.Equal(DumpProfile.Full, package.Extractor.Profile);
    }

    [Fact]
    public void Build_ModelCheckProfile_RunsTheDocumentManifestMateFeatureAndEquationPhases()
    {
        // FR-022. The Model check tab grades the feature tree and the equations, so those
        // five phases are exactly what it needs; a profile that skipped one of them would
        // leave rules unresolved on a part that is fine.
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(ModelCheckOptions());

        Assert.True(sources.DocumentsWereDumped);
        Assert.True(sources.ManifestWasBuilt);
        Assert.True(sources.MatesWereDumped);
        Assert.True(sources.FeaturesWereDumped);
        Assert.True(sources.EquationsWereDumped);

        Assert.NotEmpty(package.Documents);
        Assert.NotEmpty(package.Manifest.Entries);
        Assert.NotEmpty(package.Mates);
        Assert.NotEmpty(package.Features);
        Assert.NotEmpty(package.Equations);
    }

    // ---- the tolerance phase (feature 010 T090) ------------------------------------

    [Fact]
    public void Build_FullProfile_RunsTheTolerancePhaseAndWritesWhatItRead()
    {
        var sources = new FakeSources();
        sources.ToleranceResult.Dimensions.Add(new ModelDimension
        {
            Id = "mdm:0001",
            DocumentId = "doc:housing",
            FeatureName = "Sketch1",
            Name = "D1@Sketch1@housing.SLDPRT",
            DimensionType = ModelDimensionType.Diameter,
            Nominal = new IrMeasure(0.01, "m"),
        });
        sources.ToleranceResult.Annotations.Add(new ModelAnnotation
        {
            Id = "man:0001",
            DocumentId = "doc:housing",
            Kind = ModelAnnotationKind.Datum,
            Label = "A",
        });

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.True(sources.TolerancesWereDumped);
        Assert.Equal("mdm:0001", Assert.Single(package.ModelDimensions!).Id);
        Assert.Equal("man:0001", Assert.Single(package.ModelAnnotations!).Id);
        Assert.Equal(
            DumpPhaseStatus.Ok,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "tolerance").Status);
    }

    [Fact]
    public void Build_TolerancePhaseThatReadNothing_WritesNeitherArray()
    {
        // "The phase ran and found none" is the ok row, not an empty array that would move a
        // package on disk (the 1.4.0 rule, applied to the 1.5.0 arrays).
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.True(sources.TolerancesWereDumped);
        Assert.Null(package.ModelDimensions);
        Assert.Null(package.ModelAnnotations);
        Assert.Equal(
            DumpPhaseStatus.Ok,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "tolerance").Status);
    }

    [Fact]
    public void Build_ModelCheckAndStandardsProfiles_SkipTheTolerancePhase()
    {
        // The tolerance reads walk every part's dimensions and annotations, and no Model check
        // or Standards check reads them: the two reduced profiles skip the phase with the
        // geometry phases it sits among.
        foreach (DumpOptions options in new[] { ModelCheckOptions(), StandardsOptions() })
        {
            var sources = new FakeSources();

            EvidencePackage package = NewWriter(sources).Build(options);

            Assert.False(sources.TolerancesWereDumped);
            DumpPhase row = Assert.Single(package.Extractor.Phases, phase => phase.Name == "tolerance");
            Assert.Equal(DumpPhaseStatus.Skipped, row.Status);
            Assert.Null(row.ElapsedMs);
        }
    }

    [Fact]
    public void Build_WithNoToleranceSourceWired_RecordsThePhaseSkipped()
    {
        // The optional source, as for the two 1.4.0 phases: a build with no reader wired says
        // so in the row rather than writing nothing.
        FakeSources s = new FakeSources();
        var writer = new PackageWriter(s, s, s, s, s, s, s, s, s, s, s, s, "2024 SP5", "TEST-WORKSTATION");

        EvidencePackage package = writer.Build(Options());

        Assert.False(s.TolerancesWereDumped);
        Assert.Equal(
            DumpPhaseStatus.Skipped,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "tolerance").Status);
    }

    [Fact]
    public void Build_ModelCheckProfile_NeverCallsTheHoleFastenerFaceOrMeshSources()
    {
        // Not "returns nothing": the saving is the reads themselves, because the skipped
        // phases tessellate every body, write GLB files and read face geometry (plan key
        // point 8). Asserting on the empty arrays alone would pass with the full cost paid.
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(ModelCheckOptions());

        Assert.False(sources.HolesWereDumped);
        Assert.False(sources.FastenersWereDumped);
        Assert.False(sources.FacesWereDumped);
        Assert.False(sources.MeshesWereDumped);

        Assert.Empty(package.Holes);
        Assert.Empty(package.Threads);
        Assert.Empty(package.Fasteners);
        Assert.Empty(package.Faces);
        Assert.Empty(package.Bodies);
    }

    [Fact]
    public void Build_ModelCheckProfile_RecordsNothingButTheProfile()
    {
        // The skipped geometry phases add no gap of their own, unlike --features none and
        // --equations off. Those two are a dump that dropped evidence it normally carries,
        // so the absence needs a sentence; model-check is a package whose shape is declared
        // by extractor.profile, and a gap per skipped phase on every check run would be
        // noise an engineer learns to skip - which is how a real gap gets lost (Principle I).
        //
        // Compared on kind, entity kind and entity id rather than on the reason text: from
        // schema 1.4.0 the standing drawing gap names the profile that skipped it, so the
        // one sentence that differs between these two packages is that one, and it is
        // asserted on its own below (contracts/ir-additions.md section 5).
        EvidencePackage full = NewWriter().Build(Options());
        EvidencePackage thin = NewWriter().Build(ModelCheckOptions());

        Assert.Equal(DumpProfile.ModelCheck, thin.Extractor.Profile);
        Assert.Equal(
            full.Gaps.Select(g => $"{PackageSerializer.EnumToJsonName(g.Kind)}|{g.EntityKind}|{g.EntityId}"),
            thin.Gaps.Select(g => $"{PackageSerializer.EnumToJsonName(g.Kind)}|{g.EntityKind}|{g.EntityId}"));

        // Every reason except the drawing gap's is word for word what it was.
        Assert.Equal(
            full.Gaps.Where(g => g.EntityKind != "drawing").Select(g => g.Reason),
            thin.Gaps.Where(g => g.EntityKind != "drawing").Select(g => g.Reason));
    }

    [Fact]
    public void Build_ModelCheckProfile_ProducesAPackageThatValidatesAgainstTheContract()
    {
        IrContract.AssertValid(PackageSerializer.Serialize(NewWriter().Build(ModelCheckOptions())));
    }

    // ---- the cutlist and drawing phases (T016, schema 1.4.0) ---------------------

    [Fact]
    public void Build_StandardsProfile_RunsTheFiveModelCheckPhasesAndTheCutListPhase()
    {
        // FR-027. The standards profile extends model-check: the sixteen checks read the
        // documents, the mates, the feature trees, the equations and the cut list, and none
        // of them reads face geometry or a mesh - which is most of a dump's cost.
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(StandardsOptions());

        Assert.True(sources.DocumentsWereDumped);
        Assert.True(sources.ManifestWasBuilt);
        Assert.True(sources.MatesWereDumped);
        Assert.True(sources.FeaturesWereDumped);
        Assert.True(sources.EquationsWereDumped);
        Assert.True(sources.CutListWasDumped);

        Assert.NotNull(package.CutListItems);
        Assert.Equal(new[] { "cut:0001" }, package.CutListItems!.Select(item => item.Id));
        Assert.Equal(DumpProfile.Standards, package.Extractor.Profile);
    }

    [Fact]
    public void Build_StandardsProfile_NeverCallsTheHoleFastenerFaceOrMeshSources()
    {
        // Not "returns nothing": the saving is the reads themselves. Asserting on the empty
        // arrays alone would pass with the full cost paid.
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(StandardsOptions());

        Assert.False(sources.HolesWereDumped);
        Assert.False(sources.FastenersWereDumped);
        Assert.False(sources.FacesWereDumped);
        Assert.False(sources.MeshesWereDumped);

        Assert.Empty(package.Holes);
        Assert.Empty(package.Fasteners);
        Assert.Empty(package.Faces);
        Assert.Empty(package.Bodies);
    }

    [Fact]
    public void Build_StandardsProfileOverAnAssembly_RecordsTheDrawingPhaseAsSkipped()
    {
        // The drawing phase runs only when the root document IS a drawing (FR-025): the dump
        // does not go looking for the drawings of an open model. The row says so, which is
        // what lets `swreview check standards` tell "no drawing here" from "nobody looked".
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(StandardsOptions());

        Assert.False(sources.DrawingsWereDumped);
        Assert.Equal(
            DumpPhaseStatus.Skipped,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "drawing").Status);
        Assert.Null(package.DrawingRecords);
    }

    [Fact]
    public void Build_ModelCheckProfile_RecordsTheTwoNewPhasesAsSkippedAndCallsNeitherSource()
    {
        // The Model check tab reads neither the cut list nor a drawing, so both phases cost
        // it nothing - and the rows are what say that, rather than two empty arrays a reader
        // would have to guess about.
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(ModelCheckOptions());

        Assert.False(sources.CutListWasDumped);
        Assert.False(sources.DrawingsWereDumped);
        Assert.Equal(
            new[] { "cutlist:skipped", "drawing:skipped" },
            Rows(package).Where(row => row.StartsWith("cutlist", StringComparison.Ordinal)
                || row.StartsWith("drawing", StringComparison.Ordinal)));
        Assert.Null(package.CutListItems);
        Assert.Null(package.DrawingRecords);
    }

    [Fact]
    public void Build_FullProfile_RunsTheCutListPhaseToo()
    {
        // A full extract is never less complete than a standards one (FR-027), so the phase
        // the standards profile added runs here as well.
        var sources = new FakeSources();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.True(sources.CutListWasDumped);
        Assert.NotNull(package.CutListItems);
    }

    [Fact]
    public void Build_FullProfileOverADrawingRoot_RunsTheDrawingPhase()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.True(sources.DrawingsWereDumped);
        Assert.Equal(
            DumpPhaseStatus.Ok,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "drawing").Status);
        Assert.Equal(
            new[] { "doc:drawing" },
            package.DrawingRecords!.Select(record => record.DocumentId));
    }

    [Fact]
    public void Build_StandardsProfileOverADrawingRoot_RunsTheDrawingPhase()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(StandardsOptions());

        Assert.True(sources.DrawingsWereDumped);
        Assert.NotNull(package.DrawingRecords);
    }

    /// <summary>
    /// The standing drawing gap becomes conditional (contracts/ir-additions.md section 5):
    /// it is emitted only when the drawing phase did not run, and it then names the profile
    /// that skipped it, so a reader is told which extract to run again rather than being told
    /// a permanent fact about the extractor that is no longer true.
    ///
    /// This assertion is <b>added</b> beside
    /// <see cref="Build_RecordsThatDrawingsAreNotExtractedNatively"/>, which asserts the
    /// entity kind and the gap kind and never the message string, and which keeps passing
    /// unedited - though its name is now stale.
    /// </summary>
    /// <remarks>
    /// Feature 011 T020 edits this deliberately: the <c>full</c> row is gone, because a full dump
    /// of a part or assembly now looks for the open drawings of its design, and when none shows
    /// it the gap says that instead (contracts/open-drawings.md section 6,
    /// <see cref="Build_FullPartRootWithNothingAttached_SaysNoOpenDrawingShowsTheDesign"/>). The
    /// profile sentence stays for the two profiles that skip the phase, and for a full dump built
    /// with no open-drawing source wired (<see cref="Build_FullWithNoOpenDrawingSource_KeepsTheProfileSentence"/>).
    /// </remarks>
    [Theory]
    [InlineData(DumpProfile.ModelCheck, "model_check")]
    [InlineData(DumpProfile.Standards, "standards")]
    public void Build_DrawingPhaseThatDidNotRun_IsAGapNamingTheProfileThatSkippedIt(
        DumpProfile profile, string spelling)
    {
        DumpOptions options = Options();
        options.Profile = profile;

        EvidencePackage package = NewWriter().Build(options);

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "drawing");
        Assert.Equal(GapKind.Unsupported, gap.Kind);
        Assert.Contains(spelling, gap.Reason, StringComparison.Ordinal);
        Assert.Contains("PDF ingest", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_DrawingPhaseThatRan_EmitsNoDrawingGapAtAll()
    {
        // The other half of "only when the phase did not run". Without it the conditional
        // could be wired to the profile alone and a drawing root would still carry a gap
        // saying its sheets were never read - beside the sheets.
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.DoesNotContain(package.Gaps, g => g.EntityKind == "drawing");
    }

    [Fact]
    public void Build_DrawingRootPackage_ValidatesAgainstTheContract()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        IrContract.AssertValid(PackageSerializer.Serialize(NewWriter(sources).Build(Options())));
    }

    // ---- the package a drawing root produces (T061, schema 1.4.0) -----------------

    /// <summary>
    /// T061. The drawing itself becomes a document of the package, with a manifest entry -
    /// which no native dump has ever produced. Before this, a drawing could only reach a
    /// package through the Python PDF ingest, so its own custom properties were unreadable
    /// and <c>standards.drawing.revision_matches</c> had nothing to compare the revision
    /// table against (contracts/ir-additions.md section 7, FR-024).
    /// </summary>
    [Fact]
    public void Build_DrawingRoot_PutsTheDrawingItselfInDocumentsAndInTheManifest()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        string drawingId = DocumentIds.For(sources.RootDocumentPath);
        Document drawing = Assert.Single(
            package.Documents, document => document.DocumentId == drawingId);

        Assert.Equal(DocumentKind.Drawing, drawing.Kind);
        Assert.Contains(package.Manifest.Entries, entry => entry.DocumentId == drawingId);
    }

    /// <summary>
    /// T061. And so does every model its views reference: the drawing-rooted traversal hangs
    /// one subtree per referenced model, so the document, manifest, mate, feature, equation
    /// and cut-list phases run over them exactly as they do under an assembly root (FR-025).
    /// </summary>
    [Fact]
    public void Build_DrawingRoot_PutsEveryReferencedModelInDocumentsToo()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Contains(
            package.Documents,
            document => document.DocumentId == DocumentIds.For(sources.Nodes[0].DocumentPath));
        Assert.Equal(
            package.Documents.Select(document => document.DocumentId).OrderBy(id => id),
            package.Manifest.Entries.Select(entry => entry.DocumentId).OrderBy(id => id));
    }

    /// <summary>
    /// The forest has real parents. A drawing is normally named after the model it documents,
    /// so housing.SLDDRW over housing.SLDPRT is the ordinary case, and two nodes keyed on the
    /// file's base name would collide in <c>DumpScope</c> - whose last write for a key wins -
    /// leaving the referenced model resolving its own ParentKey to itself. An instance that
    /// names itself is what <c>checks/standards/traversal.py</c> calls a defect in whatever
    /// wrote the package; Python survives it, and the package is still wrong.
    /// </summary>
    [Fact]
    public void Build_DrawingRootWhoseModelSharesItsName_HangsTheModelUnderTheForestRoot()
    {
        var sources = new FakeSources();
        sources.UseNamesakeDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.DoesNotContain(package.Components, component => component.ParentId == component.Id);

        Assert.Equal(2, package.Components.Count);
        ComponentInstance forestRoot = package.Components[0];
        ComponentInstance model = package.Components[1];

        Assert.Null(forestRoot.ParentId);
        Assert.Equal(forestRoot.Id, model.ParentId);
        Assert.NotEqual(forestRoot.DocumentId, model.DocumentId);

        // And one full_path per instance: two instances sharing one is the same collision
        // seen from the reader's side.
        Assert.Equal(2, package.Components.Select(component => component.FullPath).Distinct().Count());
    }

    /// <summary>
    /// T061. <c>design.drawing_document_ids</c> has existed in the IR since feature 001 and
    /// has never been set by a native dump. It is what tells a consumer which document of the
    /// package is the drawing, without inferring it from a file extension.
    /// </summary>
    [Fact]
    public void Build_DrawingRoot_PopulatesTheDesignsDrawingDocumentIds()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(
            new[] { DocumentIds.For(sources.RootDocumentPath) },
            package.Design.DrawingDocumentIds);
    }

    /// <summary>
    /// T061. <c>root_assembly_document_id</c> holds the ROOT document's id whatever its kind -
    /// already true for a part opened alone since feature 003, and now for a drawing. The
    /// field's name is a misnomer feature 003 made, and it is deliberately <b>not</b> renamed:
    /// renaming a required IR field is a breaking change, and the value is unambiguous.
    /// </summary>
    [Fact]
    public void Build_DrawingRoot_HoldsTheDrawingsIdAsTheRootDocumentId()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(
            DocumentIds.For(sources.RootDocumentPath), package.Design.RootAssemblyDocumentId);
        Assert.Equal(
            DocumentIds.DesignId(sources.RootDocumentPath), package.Design.DesignId);
    }

    [Theory]
    [InlineData(DumpProfile.Full)]
    [InlineData(DumpProfile.ModelCheck)]
    [InlineData(DumpProfile.Standards)]
    public void Build_OfAPartOrAssemblyRoot_NamesNoDrawingDocument(DumpProfile profile)
    {
        // The dump does not discover the drawings of an open model: a drawing enters a package
        // when it is itself the dumped document, and not otherwise (FR-025). An empty list
        // here is the statement, not an oversight.
        DumpOptions options = Options();
        options.Profile = profile;

        Assert.Empty(NewWriter().Build(options).Design.DrawingDocumentIds);
    }

    [Fact]
    public void Build_StandardsProfileOverADrawingRoot_EmitsNoDrawingGapAtAll()
    {
        // The standards half of the conditional gap. The tab runs this profile, so a package
        // carrying both the sheets and a gap saying the sheets were never read would be the
        // one a reviewer actually sees (contracts/ir-additions.md section 5).
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(StandardsOptions());

        Assert.DoesNotContain(package.Gaps, g => g.EntityKind == "drawing");
    }

    [Fact]
    public void Build_StandardsProfilePackage_ValidatesAgainstTheContract()
    {
        IrContract.AssertValid(
            PackageSerializer.Serialize(NewWriter().Build(StandardsOptions())));
    }

    // ---- a drawing root with no configuration (feature 011 T015, attach.md section 2) ------

    /// <summary>
    /// The Standards tab's extraction of a drawing on its own: the session has no
    /// configuration, so the traversal records "" and the caller passes a null
    /// <see cref="DumpOptions.Configuration"/> (the document's active configuration, which a
    /// drawing does not have). The design block says "" - "empty for a drawing root, which has
    /// none" - rather than a configuration name nobody read.
    /// </summary>
    [Fact]
    public void Build_DrawingRootWithNoConfiguration_WritesAnEmptyActiveConfigurationOnTheDesign()
    {
        var sources = new FakeSources();
        sources.UseDrawingRootTree();
        DumpOptions options = StandardsOptions();

        EvidencePackage package = NewWriter(sources).Build(options);

        Assert.Null(options.Configuration);
        Assert.Null(sources.SeenOptions!.Configuration);
        Assert.Equal(string.Empty, package.Design.ActiveConfiguration);
    }

    [Fact]
    public void Build_DrawingRootWithNoConfiguration_WritesTheDrawingsManifestEntryWithAnEmptyConfiguration()
    {
        // The drawing's own entry is "" (it has none); a referenced model's configuration is its
        // own, as it was before feature 011.
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(StandardsOptions());

        ManifestEntry drawing = Assert.Single(
            package.Manifest.Entries,
            entry => entry.DocumentId == DocumentIds.For(sources.RootDocumentPath));
        Assert.Equal(string.Empty, drawing.Configuration);

        ManifestEntry model = Assert.Single(
            package.Manifest.Entries,
            entry => entry.DocumentId == DocumentIds.For(sources.Nodes[0].DocumentPath));
        Assert.Equal("Default", model.Configuration);
    }

    [Fact]
    public void Build_DrawingRootWithNoConfiguration_RunsTheDrawingPhaseUnderTheStandardsProfile()
    {
        // FR-001: the no-configuration session is graded through the same phase list a drawing
        // root always ran, the drawing phase included, and the package still validates.
        var sources = new FakeSources();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(StandardsOptions());

        Assert.True(sources.DrawingsWereDumped);
        Assert.Equal(
            DumpPhaseStatus.Ok,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "drawing").Status);
        Assert.DoesNotContain(package.Gaps, gap => gap.EntityKind == "drawing");
        IrContract.AssertValid(PackageSerializer.Serialize(package));
    }

    // ---- the open drawings of a reviewed part or assembly (feature 011 T020) ----------------
    //
    // contracts/open-drawings.md sections 1, 4, 6 and 7, over the fake open-drawing source; the
    // rules of discovery itself are OpenDrawingDiscoveryTests'.

    /// <summary>Two open drawings: one of the assembly (the root) and one of the housing.</summary>
    private static FakeSources WithTwoOpenDrawings()
    {
        var sources = new FakeSources();
        sources.OpenDrawing(HousingDrawingPath, HousingPath);
        sources.OpenDrawing(AssemblyDrawingPath, AssemblyPath);
        return sources;
    }

    [Fact]
    public void Build_FullAssemblyRootWithTwoOpenDrawings_WritesARecordPerDrawingWithDisjointIds()
    {
        FakeSources sources = WithTwoOpenDrawings();

        EvidencePackage package = NewWriter(sources).Build(Options());

        // The root's drawing first, then by traversal index (section 3).
        Assert.Equal(
            new[] { DocumentIds.For(AssemblyDrawingPath), DocumentIds.For(HousingDrawingPath) },
            package.DrawingRecords!.Select(record => record.DocumentId));
        Assert.Equal(
            new[] { "dsh:0001", "dsh:0002" },
            package.DrawingRecords!.Select(record => Assert.Single(record.Sheets).Id));
        Assert.Equal(
            new[] { AssemblyDrawingPath, HousingDrawingPath },
            sources.SeenDrawings.Select(drawing => drawing.DocumentPath));
        Assert.All(sources.SeenDrawings, drawing => Assert.NotNull(drawing.Document));
        Assert.Equal(
            DumpPhaseStatus.Ok,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "drawing").Status);
    }

    [Fact]
    public void Build_AttachedDrawings_HandTheDrawingPhaseTheReviewsDocumentsToTieViewsTo()
    {
        // Each attached drawing is read with the rule that ties a view's path to a document of
        // this package (DrawingDumper names an outside path in a gap on its view).
        FakeSources sources = WithTwoOpenDrawings();

        NewWriter(sources).Build(Options());

        ScopedDrawing drawing = sources.SeenDrawings[0];
        Assert.NotNull(drawing.ReviewedDocumentId);
        Assert.Equal(DocumentIds.For(HousingPath), drawing.ReviewedDocumentId!.Invoke(HousingPath.ToUpperInvariant()));
        Assert.Null(drawing.ReviewedDocumentId!.Invoke(@"C:\vault\other\unrelated.SLDPRT"));
        Assert.Null(drawing.ReviewedDocumentId!.Invoke(AssemblyDrawingPath));
    }

    [Fact]
    public void Build_AttachedDrawings_EachGetADocumentsRowAndAManifestEntryWithNoConfiguration()
    {
        EvidencePackage package = NewWriter(WithTwoOpenDrawings()).Build(Options());

        foreach (string path in new[] { AssemblyDrawingPath, HousingDrawingPath })
        {
            string id = DocumentIds.For(path);
            Document document = Assert.Single(package.Documents, row => row.DocumentId == id);
            Assert.Equal(DocumentKind.Drawing, document.Kind);
            Assert.Equal(path, document.Path);

            ManifestEntry entry = Assert.Single(package.Manifest.Entries, row => row.DocumentId == id);
            Assert.Equal(string.Empty, entry.Configuration);
        }

        // After the traversal's documents, in the drawings' order (section 4).
        Assert.Equal(
            new[] { AssemblyPath, HousingPath, ScrewPath, AssemblyDrawingPath, HousingDrawingPath },
            package.Documents.Select(document => document.Path));
    }

    [Fact]
    public void Build_AttachedDrawings_AreListedInTheDesignsDrawingDocumentIdsInOrder()
    {
        EvidencePackage package = NewWriter(WithTwoOpenDrawings()).Build(Options());

        Assert.Equal(
            new[] { DocumentIds.For(AssemblyDrawingPath), DocumentIds.For(HousingDrawingPath) },
            package.Design.DrawingDocumentIds);

        // The root stays the root: a drawing attached to a review is not the design's document.
        Assert.Equal(DocumentIds.For(AssemblyPath), package.Design.RootAssemblyDocumentId);
    }

    [Fact]
    public void Build_AttachedDrawings_AreNotComponents()
    {
        EvidencePackage package = NewWriter(WithTwoOpenDrawings()).Build(Options());

        Assert.Equal(3, package.Components.Count);
        Assert.DoesNotContain(
            package.Components,
            component => component.DocumentId == DocumentIds.For(AssemblyDrawingPath)
                || component.DocumentId == DocumentIds.For(HousingDrawingPath));
    }

    [Fact]
    public void Build_WithAttachedDrawings_KeepsTheSameTwelvePhaseNames()
    {
        EvidencePackage package = NewWriter(WithTwoOpenDrawings()).Build(Options());

        Assert.Equal(
            new[]
            {
                "document", "manifest", "mate", "feature", "equation", "cutlist", "drawing",
                "hole", "tolerance", "fastener", "face", "body",
            },
            package.Extractor.Phases.Select(phase => phase.Name));
    }

    [Theory]
    [InlineData(DumpProfile.Standards)]
    [InlineData(DumpProfile.ModelCheck)]
    public void Build_TheStandardsAndModelCheckExtractionsOfTheSameRootAttachNothing(DumpProfile profile)
    {
        FakeSources sources = WithTwoOpenDrawings();
        sources.ExistingFiles.Add(@"C:\vault\toolbox\hex-cap-screw.SLDDRW");
        DumpOptions options = Options();
        options.Profile = profile;

        EvidencePackage package = NewWriter(sources).Build(options);

        Assert.Equal(0, sources.OpenDocumentsListed);
        Assert.False(sources.DrawingsWereDumped);
        Assert.Null(package.DrawingRecords);
        Assert.Null(package.DrawingCandidates);
        Assert.Empty(package.Design.DrawingDocumentIds);
        Assert.DoesNotContain(package.Documents, document => document.Kind == DocumentKind.Drawing);
    }

    [Fact]
    public void Build_FullOfADrawingRoot_DiscoversNothing()
    {
        FakeSources sources = WithTwoOpenDrawings();
        sources.UseDrawingRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(0, sources.OpenDocumentsListed);
        Assert.Equal(new[] { "doc:drawing" }, package.DrawingRecords!.Select(record => record.DocumentId));
    }

    [Fact]
    public void Build_WritesTheCandidatesInTraversalOrder()
    {
        var sources = new FakeSources();
        sources.ExistingFiles.Add(@"C:\vault\toolbox\hex-cap-screw.SLDDRW");
        sources.ExistingFiles.Add(AssemblyDrawingPath);

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(
            new[] { DocumentIds.For(AssemblyPath), DocumentIds.For(ScrewPath) },
            package.DrawingCandidates!.Select(candidate => candidate.DocumentId));
        Assert.Equal(
            new[] { AssemblyDrawingPath, @"C:\vault\toolbox\hex-cap-screw.SLDDRW" },
            package.DrawingCandidates!.Select(candidate => candidate.Path));
        IrContract.AssertValid(PackageSerializer.Serialize(package));
    }

    [Fact]
    public void Build_WithNoCandidate_WritesNoCandidateMember()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Null(package.DrawingCandidates);
        Assert.DoesNotContain("drawing_candidates", PackageSerializer.Serialize(package), StringComparison.Ordinal);
    }

    [Fact]
    public void Build_ADiscoveryGap_ReachesThePackage()
    {
        FakeSources sources = WithTwoOpenDrawings();
        sources.OpenDocumentsFailure = new InvalidOperationException("no answer");

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Contains(package.Gaps, gap => gap.EntityKind == "drawing_discovery");
        Assert.Null(package.DrawingRecords);
    }

    [Fact]
    public void Build_TheReuseKeyDiffersWithAndWithoutAnAttachedDrawing()
    {
        string without = NewWriter().Build(Options()).ReuseKey!;
        string with = NewWriter(WithTwoOpenDrawings()).Build(Options()).ReuseKey!;

        Assert.NotEqual(without, with);
    }

    [Fact]
    public void BuildReuseProbe_WithAttachedDrawings_AgreesWithTheFullBuild()
    {
        // Discovery runs in the probe too (section 1), because the drawings enter the manifest the
        // key is taken over; a probe that skipped it would never match a package with a drawing.
        FakeSources sources = WithTwoOpenDrawings();

        string probe = NewWriter(sources).BuildReuseProbe(Options()).ReuseKey!;
        string full = NewWriter(WithTwoOpenDrawings()).Build(Options()).ReuseKey!;

        Assert.Equal(full, probe);
        Assert.Equal(1, sources.OpenDocumentsListed);
        Assert.False(sources.DrawingsWereDumped);
    }

    // ---- section 6: the drawing gap by case -------------------------------------------------

    [Fact]
    public void Build_AttachedDrawingsRead_RaiseNoDrawingGap()
    {
        EvidencePackage package = NewWriter(WithTwoOpenDrawings()).Build(Options());

        Assert.DoesNotContain(package.Gaps, gap => gap.EntityKind == "drawing");
    }

    [Fact]
    public void Build_FullPartRootWithNothingAttached_SaysNoOpenDrawingShowsTheDesign()
    {
        var sources = new FakeSources();
        sources.UsePartRootTree();

        EvidencePackage package = NewWriter(sources).Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "drawing");
        Assert.Equal(GapKind.Unsupported, gap.Kind);
        Assert.Equal(
            "No open drawing shows this design, so no drawing was read natively. Open its drawing "
            + "in SOLIDWORKS and extract again to include it.",
            gap.Reason);
        Assert.Equal(
            DumpPhaseStatus.Skipped,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "drawing").Status);
    }

    [Fact]
    public void Build_FullAssemblyRootWithNothingAttached_SaysNoOpenDrawingShowsTheDesign()
    {
        var sources = new FakeSources();
        sources.OpenDrawing(@"C:\vault\other\unrelated.SLDDRW", @"C:\vault\other\unrelated.SLDPRT");

        EvidencePackage package = NewWriter(sources).Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "drawing");
        Assert.StartsWith("No open drawing shows this design", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_FullWhoseOpenDocumentsCouldNotBeListed_SaysSoRatherThanThatNoneShowsIt()
    {
        // "No open drawing shows this design" would be a claim nobody checked.
        FakeSources sources = WithTwoOpenDrawings();
        sources.OpenDocumentsFailure = new InvalidOperationException("no answer");

        EvidencePackage package = NewWriter(sources).Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "drawing");
        Assert.Equal(
            "The drawings open in SOLIDWORKS could not be listed, so no drawing was read natively. "
            + "Extract again to include them.",
            gap.Reason);
    }

    [Fact]
    public void Build_FullWithNoOpenDrawingSource_KeepsTheProfileSentence()
    {
        // A build with no source wired never looked, so it says which phase did not run rather
        // than what SOLIDWORKS had open.
        var sources = new FakeSources();
        var writer = new PackageWriter(
            sources, sources, sources, sources, sources, sources, sources, sources, sources,
            sources, sources, sources, "2024 SP5", "TEST-WORKSTATION", tolerances: sources);

        EvidencePackage package = writer.Build(Options());

        Gap gap = Assert.Single(package.Gaps, g => g.EntityKind == "drawing");
        Assert.Contains("'full'", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("PDF ingest", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Build_AnAttachedDrawingThatCouldNotBeRead_RecordsTheDrawingPhaseFailed()
    {
        // Section 4: the row is ok when every drawing was read and failed otherwise, with the
        // drawing phase's own gaps saying which.
        FakeSources sources = WithTwoOpenDrawings();
        sources.UnreadDrawings.Add(HousingDrawingPath);

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(
            DumpPhaseStatus.Failed,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "drawing").Status);
        Assert.Equal(
            new[] { DocumentIds.For(AssemblyDrawingPath) },
            package.DrawingRecords!.Select(record => record.DocumentId));
        Assert.Contains(
            package.Gaps,
            gap => gap.EntityKind == "drawing_sheet" && gap.EntityId == DocumentIds.For(HousingDrawingPath));
        Assert.DoesNotContain(package.Gaps, gap => gap.EntityKind == "drawing");
    }

    // ---- dump phase timing (feature 005, T033) -----------------------------------

    /// <summary>
    /// One row per phase, in the order the dump runs them, every row timed. Before this
    /// there was no <c>Stopwatch</c> and no elapsed field anywhere in the dump, so "which
    /// phase actually costs the time" was guessed rather than answered - and levers 9
    /// (package reuse) and 10 (lazy meshes) had no metric at all.
    /// </summary>
    [Fact]
    public void Build_TimesEveryPhaseItRan_InTheOrderItRanThem()
    {
        EvidencePackage package = NewWriter().Build(Options());

        Assert.Equal(
            new[]
            {
                "document:ok", "manifest:ok", "mate:ok", "feature:ok", "equation:ok",
                "cutlist:ok", "drawing:skipped",
                "hole:ok", "tolerance:ok", "fastener:ok", "face:ok", "body:ok",
            },
            Rows(package));
        // Every phase that ran is timed. `drawing` is the one exception and it is not an
        // exception to the rule: the root document here is an assembly, so that phase never
        // started, and a phase that never started has no elapsed time (schema 1.4.0).
        Assert.All(
            package.Extractor.Phases.Where(phase => phase.Status != DumpPhaseStatus.Skipped),
            phase =>
            {
                Assert.NotNull(phase.ElapsedMs);
                Assert.True(phase.ElapsedMs >= 0, $"{phase.Name} reported {phase.ElapsedMs} ms");
            });
        Assert.Null(
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "drawing").ElapsedMs);
    }

    /// <summary>
    /// The four phases the Model check profile does not run are recorded as skipped with
    /// <b>no</b> elapsed time. Zero would read as a phase that ran and cost nothing, which
    /// is the one thing it did not do (Principle I), and it is exactly the number a reader
    /// comparing mesh cost across the two arms would average in.
    /// </summary>
    [Fact]
    public void Build_ModelCheckProfile_RecordsTheFourSkippedPhasesWithNoElapsedTime()
    {
        EvidencePackage package = NewWriter().Build(ModelCheckOptions());

        Assert.Equal(
            new[]
            {
                "document:ok", "manifest:ok", "mate:ok", "feature:ok", "equation:ok",
                "cutlist:skipped", "drawing:skipped",
                "hole:skipped", "tolerance:skipped", "fastener:skipped", "face:skipped", "body:skipped",
            },
            Rows(package));
        Assert.All(
            package.Extractor.Phases.Where(phase => phase.Status == DumpPhaseStatus.Skipped),
            phase => Assert.Null(phase.ElapsedMs));
    }

    [Fact]
    public void Build_FeaturesNoneAndEquationsOff_RecordThoseTwoPhasesAsSkipped()
    {
        DumpOptions options = Options();
        options.Features = FeatureScope.None;
        options.Equations = EquationScope.Off;

        EvidencePackage package = NewWriter().Build(options);

        Assert.Equal(
            new[]
            {
                "document:ok", "manifest:ok", "mate:ok", "feature:skipped", "equation:skipped",
                "cutlist:ok", "drawing:skipped",
                "hole:ok", "tolerance:ok", "fastener:ok", "face:ok", "body:ok",
            },
            Rows(package));
    }

    [Fact]
    public void Build_MeshesNone_RecordsTheMeshPhaseAsSkipped()
    {
        DumpOptions options = Options();
        options.Meshes = MeshFormat.None;

        EvidencePackage package = NewWriter().Build(options);

        Assert.Equal(
            DumpPhaseStatus.Skipped,
            Assert.Single(package.Extractor.Phases, phase => phase.Name == "body").Status);
    }

    /// <summary>
    /// A phase that threw still spent the time it spent, and the dump went on. Recording it
    /// as skipped would lose both facts at once.
    /// </summary>
    [Fact]
    public void Build_PhaseThatThrew_IsRecordedAsFailedAndStillCarriesItsElapsedTime()
    {
        var sources = new FakeSources();
        sources.MateFailure = new InvalidOperationException("GetMates blew up");

        EvidencePackage package = NewWriter(sources).Build(Options());

        DumpPhase mate = Assert.Single(package.Extractor.Phases, phase => phase.Name == "mate");
        Assert.Equal(DumpPhaseStatus.Failed, mate.Status);
        Assert.NotNull(mate.ElapsedMs);
        Assert.Equal(
            new[]
            {
                "document:ok", "manifest:ok", "mate:failed", "feature:ok", "equation:ok",
                "cutlist:ok", "drawing:skipped",
                "hole:ok", "tolerance:ok", "fastener:ok", "face:ok", "body:ok",
            },
            Rows(package));
    }

    /// <summary>
    /// The open circuit is its own status: the phase that met it is <c>aborted</c> and every
    /// phase behind it is <c>skipped</c>. "The session died here" and "these never ran" are
    /// different facts, and a reader diagnosing a short dump needs both.
    /// </summary>
    [Fact]
    public void Build_OpenCircuit_RecordsTheAbortedPhaseAndEveryPhaseItStopped()
    {
        var sources = new FakeSources();
        sources.MateFailure = new CircuitOpenError("the circuit is open");

        EvidencePackage package = NewWriter(sources).Build(Options());

        Assert.Equal(
            new[]
            {
                "document:ok", "manifest:ok", "mate:aborted", "feature:skipped",
                "equation:skipped", "cutlist:skipped", "drawing:skipped", "hole:skipped",
                "tolerance:skipped", "fastener:skipped", "face:skipped", "body:skipped",
            },
            Rows(package));
        Assert.All(
            package.Extractor.Phases.Where(phase => phase.Status == DumpPhaseStatus.Skipped),
            phase => Assert.Null(phase.ElapsedMs));
    }

    /// <summary>
    /// The reuse probe runs two phases and stops (feature 005 lever 9). Its rows say so, so
    /// a probe package is never mistaken for a dump whose remaining phases cost nothing.
    /// </summary>
    [Fact]
    public void BuildReuseProbe_RecordsTheTwoPhasesItRanAndSkipsTheRest()
    {
        EvidencePackage package = NewWriter().BuildReuseProbe(Options());

        Assert.Equal(
            new[]
            {
                "document:ok", "manifest:ok", "mate:skipped", "feature:skipped",
                "equation:skipped", "cutlist:skipped", "drawing:skipped", "hole:skipped",
                "tolerance:skipped", "fastener:skipped", "face:skipped", "body:skipped",
            },
            Rows(package));
    }

    /// <summary><c>&lt;name&gt;:&lt;status&gt;</c> per row, in order: one assertion says both
    /// which phases were recorded and what happened to each.</summary>
    private static string[] Rows(EvidencePackage package) => package.Extractor.Phases
        .Select(phase => phase.Name + ":" + PackageSerializer.EnumToJsonName(phase.Status))
        .ToArray();

    // ---- the part-root node ------------------------------------------------------

    [Fact]
    public void Build_PartRootTree_YieldsOneComponentInstanceForTheDocumentItself()
    {
        // T064, RK-15. GetRootComponent3(false) is expected to return nothing for a part
        // opened alone, so ComponentTreeDumper synthesizes one node for the document. This
        // pins the end of that path: without the node the component list is empty, the
        // feature phase iterates nothing, and all 34 rules come back unresolved.
        var sources = new FakeSources();
        sources.UsePartRootTree();

        EvidencePackage package = NewWriter(sources).Build(ModelCheckOptions());

        ComponentInstance instance = Assert.Single(package.Components);
        Assert.Equal("cmp:0001", instance.Id);
        Assert.Equal("housing", instance.FullPath);
        Assert.Null(instance.ParentId);
        Assert.True(instance.IsFixed);
        Assert.False(instance.IsToolbox);
        Assert.Equal(SuppressionState.Resolved, instance.Suppression);
        Assert.Equal(package.Design.RootAssemblyDocumentId, instance.DocumentId);
        Assert.Equal(instance.DocumentId, instance.PersistRefScope);
    }

    [Fact]
    public void Build_PartRootTree_CarriesThatDocumentsFeaturesAndEquations()
    {
        var sources = new FakeSources();
        sources.UsePartRootTree();

        EvidencePackage package = NewWriter(sources).Build(ModelCheckOptions());

        string documentId = Assert.Single(package.Components).DocumentId;
        Assert.Equal(documentId, Assert.Single(package.Features).DocumentId);
        Assert.Equal(documentId, Assert.Single(package.Equations).DocumentId);
    }

    [Fact]
    public void Build_PartRootTree_ProducesAPackageThatValidatesAgainstTheContract()
    {
        var sources = new FakeSources();
        sources.UsePartRootTree();

        IrContract.AssertValid(PackageSerializer.Serialize(NewWriter(sources).Build(ModelCheckOptions())));
    }

    [Fact]
    public void ComponentTreeResult_RootDocumentKind_HasNoDefault()
    {
        // T064. The kind of the open document is engineering data, so the tree carries no
        // default for it: when the read fails, ComponentTreeDumper leaves this null, records
        // the gap and writes no root node at all. A field initialized to Assembly would
        // stamp "assembly" on a document whose kind nobody read, and FeatureDumper and
        // EquationDumper skip every node that is not a Part - so that document's whole
        // feature tree and equation list would be dropped in silence.
        Assert.Null(new ComponentTreeResult().RootDocumentKind);
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
    public void ScopeFor_OfADrawingRoot_ListsTheRootDrawingWithItsOwnHandle()
    {
        // Feature 011 T010: the drawing phase reads scope.Drawings, and a drawing root is the
        // one drawing its own dump reads, through the handle the traversal handed over.
        var handle = new object();
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = @"C:\Fictional\plate.SLDDRW",
            RootDocumentKind = DocumentKind.Drawing,
            RootDocument = handle,
        };

        DumpScope scope = PackageWriter.ScopeFor(new GapCollector(), Options(), tree);

        ScopedDrawing drawing = Assert.Single(scope.Drawings);
        Assert.Equal(@"C:\Fictional\plate.SLDDRW", drawing.DocumentPath);
        Assert.Same(handle, drawing.Document);
    }

    [Theory]
    [InlineData(DocumentKind.Part)]
    [InlineData(DocumentKind.Assembly)]
    public void ScopeFor_OfAModelRoot_ListsNoDrawing(DocumentKind kind)
    {
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = @"C:\Fictional\plate.SLDPRT",
            RootDocumentKind = kind,
            RootDocument = new object(),
        };

        Assert.Empty(PackageWriter.ScopeFor(new GapCollector(), Options(), tree).Drawings);
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
            sources, sources, "2024 SP5"));

        Assert.Throws<ArgumentNullException>(() => new PackageWriter(
            sources, sources, sources, sources, null!, sources, sources, sources, sources, sources,
            sources, sources, "2024 SP5"));

        Assert.Throws<ArgumentNullException>(() => new PackageWriter(
            sources, sources, sources, sources, sources, null!, sources, sources, sources, sources,
            sources, sources, "2024 SP5"));
    }

    private DumpOptions Options() => new DumpOptions
    {
        OutputDirectory = Path.Combine(_outputDirectory, "native"),
    };

    private DumpOptions ModelCheckOptions()
    {
        DumpOptions options = Options();
        options.Profile = DumpProfile.ModelCheck;
        return options;
    }

    private DumpOptions StandardsOptions()
    {
        DumpOptions options = Options();
        options.Profile = DumpProfile.Standards;
        return options;
    }

    private static PackageWriter NewWriter(FakeSources? sources = null)
    {
        FakeSources s = sources ?? new FakeSources();
        return new PackageWriter(
            s, s, s, s, s, s, s, s, s, s, s, s, "2024 SP5", "TEST-WORKSTATION", tolerances: s,
            openDrawings: s);
    }

    /// <summary>
    /// One class standing in for all eleven phases. It returns canned IR objects, so the
    /// test exercises PackageWriter and nothing else.
    /// </summary>
    private sealed class FakeSources
        : IComponentTreeSource, IDocumentSource, IManifestSource, IMateSource, IFeatureSource,
          IEquationSource, ICutListSource, IDrawingSource, IHoleSource, IFastenerSource,
          IFaceSource, IMeshSource, IToleranceSource, IOpenDrawingSource
    {
        private const string DrawingPath = @"C:\vault\bracket-assy\bracket-assy.SLDDRW";
        private const string NamesakeDrawingPath = @"C:\vault\bracket-assy\housing.SLDDRW";

        private readonly List<TypeNameSighting> _holePass = new List<TypeNameSighting>();

        private readonly List<TypeNameSighting> _traversalPass = new List<TypeNameSighting>();

        public List<ComponentNode> Nodes { get; } = new List<ComponentNode>
        {
            NewNode("bracket-assy-1", null, AssemblyPath, DocumentKind.Assembly),
            NewNode("housing-1", "bracket-assy-1", HousingPath, DocumentKind.Part),
            NewNode("screw-1", "bracket-assy-1", ScrewPath, DocumentKind.Part),
        };

        public string RootDocumentPath { get; set; } = AssemblyPath;

        public DocumentKind RootDocumentKind { get; set; } = DocumentKind.Assembly;

        public string DesignName { get; set; } = "bracket-assy";

        /// <summary>
        /// What the traversal records as the root's configuration: the bound one for a model
        /// root, "" for a drawing root, whose session has none (feature 011, attach.md section 2).
        /// </summary>
        public string ActiveConfiguration { get; set; } = "Default";

        public string? TraversalGap { get; set; }

        public string? HoleGap { get; set; }

        public Exception? MateFailure { get; set; }

        /// <summary>What the mate phase read off the mate feature's IsSuppressed2.</summary>
        public bool MateSuppressed { get; set; }

        public bool DocumentsWereDumped { get; private set; }

        public bool ManifestWasBuilt { get; private set; }

        public bool MatesWereDumped { get; private set; }

        public bool HolesWereDumped { get; private set; }

        public bool FastenersWereDumped { get; private set; }

        public bool FacesWereDumped { get; private set; }

        public bool MeshesWereDumped { get; private set; }

        public bool FeaturesWereDumped { get; private set; }

        public bool EquationsWereDumped { get; private set; }

        public bool CutListWasDumped { get; private set; }

        public bool DrawingsWereDumped { get; private set; }

        public bool TolerancesWereDumped { get; private set; }

        /// <summary>What the tolerance phase returns; empty unless a test fills it.</summary>
        public ToleranceDumpResult ToleranceResult { get; } = new ToleranceDumpResult();

        public string? MeshDirectory { get; private set; }

        public DumpOptions? SeenOptions { get; private set; }

        /// <summary>The documents the fake SOLIDWORKS has open (feature 011 discovery).</summary>
        public List<OpenDocument> OpenDocumentList { get; } = new List<OpenDocument>();

        /// <summary>Files the existence check answers true for.</summary>
        public HashSet<string> ExistingFiles { get; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        /// <summary>What listing the open documents throws, or null.</summary>
        public Exception? OpenDocumentsFailure { get; set; }

        public int OpenDocumentsListed { get; private set; }

        /// <summary>The drawings the drawing phase was handed, in order.</summary>
        public List<ScopedDrawing> SeenDrawings { get; } = new List<ScopedDrawing>();

        /// <summary>
        /// Attached drawings the drawing phase reads no record for, with a gap naming each, as
        /// DrawingDumper does for a drawing it cannot read.
        /// </summary>
        public HashSet<string> UnreadDrawings { get; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        /// <summary>An open drawing whose views show <paramref name="references"/>.</summary>
        public object OpenDrawing(string path, params string[] references)
        {
            var handle = new object();
            OpenDocumentList.Add(new OpenDocument(
                handle, () => DocumentKind.Drawing, () => path, () => references));
            return handle;
        }

        IReadOnlyList<OpenDocument> IOpenDrawingSource.OpenDocuments()
        {
            OpenDocumentsListed++;
            return OpenDocumentsFailure == null ? OpenDocumentList : throw OpenDocumentsFailure;
        }

        bool IOpenDrawingSource.FileExists(string path) => ExistingFiles.Contains(path);

        /// <summary>
        /// The tree <see cref="ComponentTreeDumper"/> synthesizes for a part opened alone
        /// (T064): one fixed, resolved root node for the document itself, with no parent and
        /// no children. The canned feature and equation rows already describe the housing
        /// part, so the single node and those rows name the same document.
        /// </summary>
        public void UsePartRootTree()
        {
            RootDocumentPath = HousingPath;
            RootDocumentKind = DocumentKind.Part;
            DesignName = "housing";

            ComponentNode root = NewNode("housing", null, HousingPath, DocumentKind.Part);
            root.IsFixed = true;
            root.PersistRefScopePath = HousingPath;

            Nodes.Clear();
            Nodes.Add(root);
        }

        /// <summary>
        /// A drawing opened alone: the root document is the drawing itself, and the tree is
        /// the one subtree its views reference (FR-025). Nothing is opened, loaded or
        /// activated to produce it.
        /// </summary>
        public void UseDrawingRootTree()
        {
            RootDocumentPath = DrawingPath;
            RootDocumentKind = DocumentKind.Drawing;
            DesignName = "bracket-assy";
            ActiveConfiguration = string.Empty;

            ComponentNode root = NewNode("housing", null, HousingPath, DocumentKind.Part);
            root.IsFixed = true;
            root.PersistRefScopePath = HousingPath;

            Nodes.Clear();
            Nodes.Add(root);
        }

        /// <summary>
        /// The ordinary SOLIDWORKS naming convention: a drawing named after the model it
        /// documents. Both synthesized nodes are keyed on their own document path, which is
        /// what keeps them apart in <c>DumpScope</c>, so the model hangs under the forest root
        /// instead of overwriting it and becoming its own parent.
        /// </summary>
        public void UseNamesakeDrawingRootTree()
        {
            RootDocumentPath = NamesakeDrawingPath;
            RootDocumentKind = DocumentKind.Drawing;
            DesignName = "housing";
            ActiveConfiguration = string.Empty;

            ComponentNode root = NewNode(
                NamesakeDrawingPath, null, NamesakeDrawingPath, DocumentKind.Drawing);
            root.Name = "housing";
            root.IsFixed = true;
            root.PersistRefScopePath = NamesakeDrawingPath;

            ComponentNode model = NewNode(
                HousingPath, NamesakeDrawingPath, HousingPath, DocumentKind.Part);
            model.Name = "housing";
            model.IsFixed = true;
            model.PersistRefScopePath = HousingPath;

            Nodes.Clear();
            Nodes.Add(root);
            Nodes.Add(model);
        }

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
                RootDocumentKind = RootDocumentKind,
                DesignName = DesignName,
                ActiveConfiguration = ActiveConfiguration,
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

        public IReadOnlyList<Document> Dump(DumpScope scope, IReadOnlyList<string> documentPaths)
        {
            DocumentsWereDumped = true;

            // As PropertyDumper reads them: a drawing answers no active configuration, which is
            // recorded as "", and lists none (feature 011, attach.md section 2).
            return documentPaths.Select(path =>
            {
                bool drawing = DocumentKindOf(path) == DocumentKind.Drawing;
                var document = new Document
                {
                    DocumentId = scope.DocumentId(path),
                    Kind = DocumentKindOf(path),
                    FileName = Path.GetFileName(path),
                    Path = path,
                    ActiveConfiguration = drawing ? string.Empty : "Default",
                    Material = null,
                    Mass = null,
                };

                if (!drawing)
                {
                    document.Configurations.Add("Default");
                }

                return document;
            }).ToList();
        }

        public Manifest Build(DumpScope scope, IReadOnlyList<Document> documents)
        {
            ManifestWasBuilt = true;

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
            MatesWereDumped = true;

            if (MateFailure != null)
            {
                throw MateFailure;
            }

            // A part opened alone has no assembly mates, and the canned mate below names two
            // child components a one-node part-root tree does not have.
            if (scope.Components.Count < 3)
            {
                return new List<Mate>();
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

        IReadOnlyList<CutListItem> ICutListSource.Dump(DumpScope scope)
        {
            CutListWasDumped = true;

            return new List<CutListItem>
            {
                new CutListItem
                {
                    // A literal rather than an allocator off the scope: the id vocabulary belongs to
                    // the real CutListDumper, and a fake that invented one would pin it here.
                    Id = "cut:0001",
                    DocumentId = scope.DocumentId(HousingPath),
                    Configuration = scope.ActiveConfiguration,
                    FolderName = "Cut list",
                    FolderTypeName = "CutListFolder",
                    Name = "Cut-List-Item1",
                    BodyCount = 1,
                    ExcludedFromCutList = false,
                },
            };
        }

        IReadOnlyList<DrawingRecord> IDrawingSource.Dump(DumpScope scope)
        {
            DrawingsWereDumped = true;
            SeenDrawings.AddRange(scope.Drawings);

            // A review's attached drawings (feature 011): one record per drawing the scope hands
            // over, each numbered from the package's allocators, as DrawingDumper numbers them.
            if (RootDocumentKind != DocumentKind.Drawing)
            {
                foreach (ScopedDrawing unread in scope.Drawings.Where(d => UnreadDrawings.Contains(d.DocumentPath)))
                {
                    scope.Gaps.Add(
                        GapKind.NotExtracted,
                        "drawing_sheet",
                        scope.DocumentId(unread.DocumentPath),
                        "The open document did not answer as a drawing.",
                        null);
                }

                return scope.Drawings.Where(d => !UnreadDrawings.Contains(d.DocumentPath)).Select(drawing => new DrawingRecord
                {
                    DocumentId = scope.DocumentId(drawing.DocumentPath),
                    ActiveSheetName = "Sheet1",
                    Sheets =
                    {
                        new DrawingSheetRecord
                        {
                            Id = scope.DrawingIds.Sheets.Next(),
                            Name = "Sheet1",
                            Index = 0,
                            WasActive = true,
                        },
                    },
                }).ToList();
            }

            return new List<DrawingRecord>
            {
                new DrawingRecord
                {
                    DocumentId = "doc:drawing",
                    ActiveSheetName = "Sheet1",
                    Sheets =
                    {
                        new DrawingSheetRecord
                        {
                            Id = "dsh:0001",
                            Name = "Sheet1",
                            Index = 0,
                            WasActive = true,
                        },
                    },
                },
            };
        }

        ToleranceDumpResult IToleranceSource.Dump(DumpScope scope)
        {
            TolerancesWereDumped = true;
            return ToleranceResult;
        }

        HoleDumpResult IHoleSource.Dump(DumpScope scope)
        {
            HolesWereDumped = true;

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

        IReadOnlyList<Fastener> IFastenerSource.Dump(DumpScope scope)
        {
            FastenersWereDumped = true;

            return new List<Fastener>
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
        }

        IReadOnlyList<FaceGeometry> IFaceSource.Dump(DumpScope scope)
        {
            FacesWereDumped = true;

            return new List<FaceGeometry>
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
        }

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

        /// <summary>The dump never calls this one; the bridge's `tessellate` does (T097).</summary>
        IReadOnlyList<BodyRef> IMeshSource.DumpComponent(
            DumpScope scope, ScopedComponent component, string meshDirectory) =>
            throw new NotSupportedException("The dump exports every component, not one.");

        private static DocumentKind DocumentKindOf(string path)
        {
            if (path.EndsWith(".SLDASM", StringComparison.OrdinalIgnoreCase))
            {
                return DocumentKind.Assembly;
            }

            return path.EndsWith(".SLDDRW", StringComparison.OrdinalIgnoreCase)
                ? DocumentKind.Drawing
                : DocumentKind.Part;
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
