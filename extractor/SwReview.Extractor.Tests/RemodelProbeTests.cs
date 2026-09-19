using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T031. <c>probe remodel</c>'s pure logic: the throwaway-part recipe, the fifteen stage-1
/// probes' fixed metadata, the runner's verdict rules (a probe that throws records
/// <c>unresolved</c> and never <c>verified</c>), the YAML ledger writer, the save-path safety
/// check and the log lines. Nothing here touches SOLIDWORKS: <see cref="SwRemodelProbeHost"/>
/// is the one class that does, and it is exercised on the workstation, not here.
///
/// Command-line parsing for <c>probe remodel</c> is in <c>CommandLineOptionsTests</c>, beside
/// the other four commands', not duplicated here.
/// </summary>
public class RemodelProbeTests
{
    // ---- the throwaway-part recipe ------------------------------------------------

    [Fact]
    public void Default_HasSevenStepsInResearchMdOrder()
    {
        RemodelProbePartRecipe recipe = RemodelProbePartRecipe.Default();

        Assert.Equal(
            new[]
            {
                RemodelProbeFeatureKind.Box,
                RemodelProbeFeatureKind.Cut,
                RemodelProbeFeatureKind.Fillet,
                RemodelProbeFeatureKind.Chamfer,
                RemodelProbeFeatureKind.Shell,
                RemodelProbeFeatureKind.Folder,
                RemodelProbeFeatureKind.Equation,
            },
            recipe.Steps.Select(step => step.Kind));
    }

    [Fact]
    public void Default_TheFilletAndTheChamferShareAName()
    {
        RemodelProbePartRecipe recipe = RemodelProbePartRecipe.Default();

        RemodelProbeFeatureStep fillet = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Fillet);
        RemodelProbeFeatureStep chamfer = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Chamfer);

        Assert.Equal(fillet.Name, chamfer.Name);
    }

    [Fact]
    public void Default_TheBoxAndTheCutHaveDistinctNames()
    {
        RemodelProbePartRecipe recipe = RemodelProbePartRecipe.Default();

        RemodelProbeFeatureStep box = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Box);
        RemodelProbeFeatureStep cut = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Cut);

        Assert.NotEqual(box.Name, cut.Name);
    }

    [Fact]
    public void Default_TheFolderWrapsTheContiguousBoxAndCut()
    {
        RemodelProbePartRecipe recipe = RemodelProbePartRecipe.Default();

        RemodelProbeFeatureStep box = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Box);
        RemodelProbeFeatureStep cut = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Cut);
        RemodelProbeFeatureStep folder = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Folder);

        Assert.Equal(new[] { box.Name, cut.Name }, folder.FolderMembers);

        // Contiguous: the box and the cut are the recipe's first two steps, with nothing
        // between them and the folder step (PROBE-4's precondition).
        Assert.Equal(0, recipe.Steps.ToList().FindIndex(s => s == box));
        Assert.Equal(1, recipe.Steps.ToList().FindIndex(s => s == cut));
    }

    [Fact]
    public void Default_TheEquationIsProbe2sExactWording()
    {
        RemodelProbePartRecipe recipe = RemodelProbePartRecipe.Default();

        RemodelProbeFeatureStep equation = recipe.Steps.Single(s => s.Kind == RemodelProbeFeatureKind.Equation);

        Assert.Equal("\"w\" = 120", equation.EquationText);
    }

    [Fact]
    public void Default_EveryStepHasANonEmptyName()
    {
        RemodelProbePartRecipe recipe = RemodelProbePartRecipe.Default();

        Assert.All(recipe.Steps, step => Assert.False(string.IsNullOrWhiteSpace(step.Name)));
    }

    [Fact]
    public void FeatureStep_EmptyName_Throws()
    {
        Assert.Throws<ArgumentException>(
            () => new RemodelProbeFeatureStep(string.Empty, RemodelProbeFeatureKind.Box));
    }

    [Fact]
    public void FeatureStep_FolderWithNoMembers_Throws()
    {
        Assert.Throws<ArgumentException>(
            () => new RemodelProbeFeatureStep("Folder1", RemodelProbeFeatureKind.Folder));
    }

    [Fact]
    public void FeatureStep_EquationWithNoText_Throws()
    {
        Assert.Throws<ArgumentException>(
            () => new RemodelProbeFeatureStep("w", RemodelProbeFeatureKind.Equation));
    }

    [Fact]
    public void PartRecipe_NoSteps_Throws()
    {
        Assert.Throws<ArgumentException>(() => new RemodelProbePartRecipe(Array.Empty<RemodelProbeFeatureStep>()));
    }

    // ---- the fifteen stage-1 probes' metadata --------------------------------------

    [Fact]
    public void Catalog_AllIdsIsExactlyTheFifteenStage1ProbesInOrder()
    {
        Assert.Equal(
            new[]
            {
                "PROBE-1", "PROBE-2", "PROBE-3", "PROBE-4", "PROBE-5", "PROBE-6", "PROBE-7",
                "PROBE-8", "PROBE-9", "PROBE-10", "PROBE-11", "PROBE-12", "PROBE-13",
                "PROBE-20", "PROBE-21",
            },
            RemodelProbeCatalog.AllIds);
    }

    [Theory]
    [InlineData("PROBE-1")]
    [InlineData(" PROBE-1 ")]
    public void Catalog_IsKnown_TrueForARegisteredId(string id)
    {
        // Ordinal, exact-case, trimmed: case normalization is the CLI boundary's job
        // (Program.SplitProbeIds upper-cases before ever asking the catalog), the same
        // division RemodelGuard's ordinal AllowedKeySet already draws.
        Assert.True(RemodelProbeCatalog.IsKnown(id));
    }

    [Fact]
    public void Catalog_IsKnown_FalseForTheWrongCase()
    {
        Assert.False(RemodelProbeCatalog.IsKnown("probe-1"));
    }

    [Theory]
    [InlineData("PROBE-99")]
    [InlineData("")]
    [InlineData(null)]
    public void Catalog_IsKnown_FalseForAnythingElse(string? id)
    {
        Assert.False(RemodelProbeCatalog.IsKnown(id));
    }

    [Fact]
    public void Catalog_Get_ThrowsForAnUnknownId()
    {
        Assert.Throws<ArgumentException>(() => RemodelProbeCatalog.Get("PROBE-99"));
    }

    [Fact]
    public void Catalog_BlockingProbesAreExactlyOneTwoThreeFourEightTwelve()
    {
        IEnumerable<string> blocking = RemodelProbeCatalog.AllIds
            .Select(RemodelProbeCatalog.Get)
            .Where(definition => definition.Blocking)
            .Select(definition => definition.Id);

        Assert.Equal(
            new[] { "PROBE-1", "PROBE-2", "PROBE-3", "PROBE-4", "PROBE-8", "PROBE-12" },
            blocking);
    }

    [Fact]
    public void Catalog_EveryDefinitionNamesItsQuestionMethodAndFallback()
    {
        foreach (string id in RemodelProbeCatalog.AllIds)
        {
            RemodelProbeDefinition definition = RemodelProbeCatalog.Get(id);

            Assert.False(string.IsNullOrWhiteSpace(definition.Question));
            Assert.False(string.IsNullOrWhiteSpace(definition.Method));
            Assert.False(string.IsNullOrWhiteSpace(definition.Fallback));
        }
    }

    // ---- verdict spelling -----------------------------------------------------------

    [Theory]
    [InlineData(RemodelProbeVerdict.Verified, "verified")]
    [InlineData(RemodelProbeVerdict.Refuted, "refuted")]
    [InlineData(RemodelProbeVerdict.Unresolved, "unresolved")]
    public void Verdict_CliNameMatchesTasksMdsSpelling(RemodelProbeVerdict verdict, string expected)
    {
        Assert.Equal(expected, verdict.CliName());
    }

    [Fact]
    public void Verdict_UnknownValue_Throws()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => ((RemodelProbeVerdict)99).CliName());
    }

    // ---- the runner: a probe that throws records unresolved and never verified ----

    private static RemodelProbeContext Context(string swVersion = "32.5.0.48")
    {
        var part = new RemodelProbePart(new object(), @"C:\out\probe-part\remodel-probe.SLDPRT", Array.Empty<object>());
        return new RemodelProbeContext(part, new SwGate(), swVersion, new FakeRemodelProbeHost(), @"C:\out");
    }

    [Fact]
    public void Run_NoRegisteredBody_RecordsUnresolvedWithTheNotImplementedNote()
    {
        RemodelProbeRecord record = RemodelProbeRunner.Run(
            "PROBE-1", Context(), executors: new Dictionary<string, RemodelProbeExecutor>());

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.Equal(RemodelProbeRunner.NotImplementedNote, record.RawResult[RemodelProbeRunner.NoteKey]);
    }

    [Fact]
    public void Run_ABodyThatThrows_RecordsUnresolvedAndNeverVerified()
    {
        var executors = new Dictionary<string, RemodelProbeExecutor>
        {
            ["PROBE-3"] = _ => throw new InvalidOperationException("ReorderFeature raised a modal"),
        };

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-3", Context(), executors);

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.NotEqual(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal("ReorderFeature raised a modal", record.RawResult[RemodelProbeRunner.ErrorKey]);
    }

    [Fact]
    public void Run_ABodyThatAnswersVerified_RecordsVerifiedWithItsRawResultAndInteropMembers()
    {
        var executors = new Dictionary<string, RemodelProbeExecutor>
        {
            ["PROBE-2"] = _ => new RemodelProbeReading(
                RemodelProbeVerdict.Verified,
                new Dictionary<string, string> { ["equation_value_mm"] = "120" },
                new[] { "get_Equation", "get_Value" }),
        };

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-2", Context(), executors);

        Assert.Equal(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal("120", record.RawResult["equation_value_mm"]);
        Assert.Equal(new[] { "get_Equation", "get_Value" }, record.InteropMembers);
    }

    [Fact]
    public void Run_ABodyThatAnswersRefuted_RecordsRefuted()
    {
        var executors = new Dictionary<string, RemodelProbeExecutor>
        {
            ["PROBE-1"] = _ => new RemodelProbeReading(RemodelProbeVerdict.Refuted),
        };

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-1", Context(), executors);

        Assert.Equal(RemodelProbeVerdict.Refuted, record.Verdict);
    }

    [Fact]
    public void Run_CopiesTheDefinitionsMetadataOntoTheRecord()
    {
        RemodelProbeDefinition definition = RemodelProbeCatalog.Get("PROBE-8");

        RemodelProbeRecord record = RemodelProbeRunner.Run(
            "PROBE-8", Context("32.5.0.48"), new Dictionary<string, RemodelProbeExecutor>());

        Assert.Equal(definition.Id, record.ProbeId);
        Assert.Equal(definition.Question, record.Question);
        Assert.Equal(definition.Method, record.Method);
        Assert.Equal(definition.Blocking, record.Blocking);
        Assert.Equal(definition.Fallback, record.Fallback);
        Assert.Equal("32.5.0.48", record.SwVersion);
        Assert.True(record.DurationMs >= 0);
    }

    [Fact]
    public void Run_UnknownProbeId_Throws()
    {
        Assert.Throws<ArgumentException>(() => RemodelProbeRunner.Run("PROBE-99", Context()));
    }

    [Fact]
    public void RunAll_RunsEveryRequestedIdInOrder()
    {
        IReadOnlyList<RemodelProbeRecord> records = RemodelProbeRunner.RunAll(
            new[] { "PROBE-5", "PROBE-1" }, Context(), new Dictionary<string, RemodelProbeExecutor>());

        Assert.Equal(new[] { "PROBE-5", "PROBE-1" }, records.Select(r => r.ProbeId));
        Assert.All(records, r => Assert.Equal(RemodelProbeVerdict.Unresolved, r.Verdict));
    }

    // ---- the save-path safety check -------------------------------------------------

    [Fact]
    public void AssertPartSavePath_InsideTheRunFolderWithTheRightExtension_DoesNotThrow()
    {
        string runFolder = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", "run1");
        string savePath = Path.Combine(runFolder, "probe-part", "remodel-probe.SLDPRT");

        RemodelProbe.AssertPartSavePath(savePath, runFolder);
    }

    [Fact]
    public void AssertPartSavePath_WrongExtension_Throws()
    {
        string runFolder = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", "run2");
        string savePath = Path.Combine(runFolder, "probe-part", "remodel-probe.txt");

        Assert.Throws<RemodelProbeRefusedError>(() => RemodelProbe.AssertPartSavePath(savePath, runFolder));
    }

    [Fact]
    public void AssertPartSavePath_OutsideTheRunFolder_Throws()
    {
        string runFolder = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", "run3");
        string savePath = Path.Combine(Path.GetTempPath(), "elsewhere", "remodel-probe.SLDPRT");

        Assert.Throws<RemodelProbeRefusedError>(() => RemodelProbe.AssertPartSavePath(savePath, runFolder));
    }

    [Fact]
    public void AssertPartSavePath_DotDotEscapingTheRunFolder_Throws()
    {
        string runFolder = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", "run4");
        string savePath = Path.Combine(runFolder, "..", "escaped.SLDPRT");

        Assert.Throws<RemodelProbeRefusedError>(() => RemodelProbe.AssertPartSavePath(savePath, runFolder));
    }

    // ---- the ledger --------------------------------------------------------------

    private static RemodelProbeRecord SampleRecord(
        string probeId = "PROBE-1",
        RemodelProbeVerdict verdict = RemodelProbeVerdict.Verified,
        bool blocking = true) =>
        new RemodelProbeRecord(
            probeId,
            "Does it suppress the box?",
            "Ask twice.",
            blocking,
            "Stage 1 stops until the owner decides.",
            verdict,
            new Dictionary<string, string> { ["returned"] = "false", ["blocked_ms"] = "0" },
            "32.5.0.48",
            durationMs: 12,
            interopMembers: new[] { "set_CommandInProgress", "ReorderFeature" });

    [Fact]
    public void Ledger_Render_EmptyRecords_WritesAnEmptyList()
    {
        string yaml = RemodelProbeLedger.Render(
            "32.5.0.48", Array.Empty<RemodelProbeRecord>(), DateTimeOffset.UtcNow);

        Assert.Contains("sw_version: \"32.5.0.48\"", yaml);
        Assert.Contains("probes: []", yaml);
    }

    [Fact]
    public void Ledger_Render_OneRecord_CarriesEveryT031Field()
    {
        string yaml = RemodelProbeLedger.Render(
            "32.5.0.48", new[] { SampleRecord() }, DateTimeOffset.UtcNow);

        // {probe_id, question, method, raw_result, verdict, sw_version} - tasks.md T031's row shape.
        Assert.Contains("probe_id: \"PROBE-1\"", yaml);
        Assert.Contains("question: \"Does it suppress the box?\"", yaml);
        Assert.Contains("method: \"Ask twice.\"", yaml);
        Assert.Contains("verdict: verified", yaml);
        Assert.Contains("sw_version: \"32.5.0.48\"", yaml);
        Assert.Contains("\"returned\": \"false\"", yaml);
        Assert.Contains("\"blocked_ms\": \"0\"", yaml);

        // Plus the extras the record carries beyond the six required fields.
        Assert.Contains("blocking: true", yaml);
        Assert.Contains("fallback: \"Stage 1 stops until the owner decides.\"", yaml);
        Assert.Contains("duration_ms: 12", yaml);
        Assert.Contains("- \"set_CommandInProgress\"", yaml);
        Assert.Contains("- \"ReorderFeature\"", yaml);
    }

    [Fact]
    public void Ledger_Render_NoRawResultOrInteropMembers_WritesEmptyCollections()
    {
        var record = new RemodelProbeRecord(
            "PROBE-21",
            "q",
            "m",
            false,
            "f",
            RemodelProbeVerdict.Unresolved,
            new Dictionary<string, string>(),
            "32.5.0.48",
            0,
            Array.Empty<string>());

        string yaml = RemodelProbeLedger.Render("32.5.0.48", new[] { record }, DateTimeOffset.UtcNow);

        Assert.Contains("interop_members: []", yaml);
        Assert.Contains("raw_result: {}", yaml);
    }

    [Fact]
    public void Ledger_Render_EscapesQuotesAndBackslashes()
    {
        var record = new RemodelProbeRecord(
            "PROBE-1",
            "Says \"hi\" and uses a \\ backslash",
            "m",
            true,
            "f",
            RemodelProbeVerdict.Unresolved,
            new Dictionary<string, string>(),
            "32.5.0.48",
            0,
            Array.Empty<string>());

        string yaml = RemodelProbeLedger.Render("32.5.0.48", new[] { record }, DateTimeOffset.UtcNow);

        Assert.Contains("question: \"Says \\\"hi\\\" and uses a \\\\ backslash\"", yaml);
    }

    [Fact]
    public void Ledger_FilePath_ComposesTheCapabilitiesDirectoryAndTheSwVersion()
    {
        string path = RemodelProbeLedger.FilePath(@"C:\out", "32.5.0.48");

        Assert.Equal(Path.Combine(@"C:\out", "capabilities", "remodel-32.5.0.48.yaml"), path);
    }

    [Fact]
    public void Ledger_FilePath_SanitizesFilesystemHostileCharactersInTheVersion()
    {
        string path = RemodelProbeLedger.FilePath(@"C:\out", "32.5.0.48/beta?");

        Assert.DoesNotContain("/", Path.GetFileName(path));
        Assert.DoesNotContain("?", Path.GetFileName(path));
    }

    [Fact]
    public void Ledger_Write_CreatesTheCapabilitiesDirectoryAndWritesTheRenderedFile()
    {
        string root = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", Guid.NewGuid().ToString("N"));
        try
        {
            string path = RemodelProbeLedger.Write(root, "32.5.0.48", new[] { SampleRecord() });

            Assert.Equal(Path.Combine(root, "capabilities", "remodel-32.5.0.48.yaml"), path);
            Assert.True(File.Exists(path));
            Assert.Contains("probe_id: \"PROBE-1\"", File.ReadAllText(path));
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    // ---- log lines -----------------------------------------------------------------

    [Fact]
    public void LogLines_CountsEachVerdict()
    {
        var records = new[]
        {
            SampleRecord("PROBE-1", RemodelProbeVerdict.Verified),
            SampleRecord("PROBE-2", RemodelProbeVerdict.Refuted, blocking: true),
            SampleRecord("PROBE-5", RemodelProbeVerdict.Unresolved, blocking: false),
        };

        IReadOnlyList<string> lines = RemodelProbe.LogLines(records, Array.Empty<string>(), @"C:\out\ledger.yaml");

        Assert.Contains(lines, line => line.Contains("1 verified") && line.Contains("1 refuted") && line.Contains("1 unresolved"));
        Assert.Contains(lines, line => line == "interop members: (none)");
        Assert.Contains(lines, line => line == @"Wrote C:\out\ledger.yaml");
    }

    [Fact]
    public void LogLines_NamesEveryBlockingProbeThatIsNotVerified()
    {
        var records = new[]
        {
            SampleRecord("PROBE-1", RemodelProbeVerdict.Verified, blocking: true),
            SampleRecord("PROBE-3", RemodelProbeVerdict.Refuted, blocking: true),
        };

        IReadOnlyList<string> lines = RemodelProbe.LogLines(records, Array.Empty<string>(), @"C:\out\ledger.yaml");

        Assert.Contains(lines, line => line.StartsWith("BLOCKING PROBE-3 is refuted", StringComparison.Ordinal));
        Assert.DoesNotContain(lines, line => line.Contains("BLOCKING PROBE-1"));
    }

    [Fact]
    public void LogLines_ListsTheGatedMembers()
    {
        IReadOnlyList<string> lines = RemodelProbe.LogLines(
            new[] { SampleRecord() }, new[] { "FeatureExtrusion3", "ForceRebuild3" }, @"C:\out\ledger.yaml");

        Assert.Contains(lines, line => line == "interop members: FeatureExtrusion3, ForceRebuild3");
    }
}
