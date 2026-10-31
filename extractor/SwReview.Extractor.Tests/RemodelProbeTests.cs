using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
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

    // A thrown body's row carries the exception's type and HRESULT, never its message: a
    // SOLIDWORKS or file-system message may name a path with the user's name in it, and a
    // ledger from the probe's own throwaway part may be committed (owner decision 171A; 004
    // T334, research R27.3). Changed on purpose from T171's "the host's own words": the host's
    // own exception, not the wrapper's, still reaches the ledger - as its type.

    [Fact]
    public void Run_ABodyThatThrows_RecordsUnresolvedAndNeverVerified()
    {
        var error = new InvalidOperationException("ReorderFeature raised a modal");
        var executors = new Dictionary<string, RemodelProbeExecutor> { ["PROBE-3"] = _ => throw error };

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-3", Context(), executors);

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.NotEqual(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal($"InvalidOperationException 0x{error.HResult:X8}", record.RawResult[RemodelProbeRunner.ErrorKey]);
    }

    [Fact]
    public void Run_ABodyWhoseCallCameBackWrappedInATask_RecordsTheHostsOwnExceptionNotTheWrapper()
    {
        // A call made through a task arrives as an AggregateException, which says nothing of what
        // failed; the ledger records the host's own exception (013 T137, 004 T171), as its type.
        var executors = new Dictionary<string, RemodelProbeExecutor>
        {
            ["PROBE-1"] = _ => throw new AggregateException(new COMException("the host's own words", unchecked((int)0x80004005))),
        };

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-1", Context(), executors);

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.Equal("COMException 0x80004005", record.RawResult[RemodelProbeRunner.ErrorKey]);
    }

    [Fact]
    public void Run_ABodyWhoseWrappedCallsBothThrew_RecordsEveryHostExceptionInOrder()
    {
        var executors = new Dictionary<string, RemodelProbeExecutor>
        {
            ["PROBE-1"] = _ => throw new AggregateException(
                new COMException("first", unchecked((int)0x80004005)),
                new AggregateException(new COMException("second", unchecked((int)0x8001010A)))),
        };

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-1", Context(), executors);

        Assert.Equal("COMException 0x80004005; COMException 0x8001010A", record.RawResult[RemodelProbeRunner.ErrorKey]);
    }

    [Fact]
    public void Run_AnAggregateWithNoInnerException_RecordsItsOwnType()
    {
        // Nothing inside to prefer: its own type is what there is, never an empty string.
        var error = new AggregateException("the wrapper's only words", Array.Empty<Exception>());
        var executors = new Dictionary<string, RemodelProbeExecutor> { ["PROBE-1"] = _ => throw error };

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-1", Context(), executors);

        Assert.Equal($"AggregateException 0x{error.HResult:X8}", record.RawResult[RemodelProbeRunner.ErrorKey]);
    }

    [Fact]
    public void Run_AHostThatThrowsWithAPathInItsMessage_TheLedgerShowsItsTypeAndHresultOnly()
    {
        const string fictionalPath = @"C:\Users\FICT-engineer\Designs\FICT-bracket.SLDPRT";
        var host = new FakeRemodelProbeHost
        {
            ReopenPartImpl = _ => throw new COMException($"Could not open '{fictionalPath}'.", unchecked((int)0x80004005)),
        };
        var part = new RemodelProbePart(new object(), @"C:\out\probe-part\remodel-probe.SLDPRT", Array.Empty<object>());
        var context = new RemodelProbeContext(part, new SwGate(), "32.5.0.48", host, @"C:\out");

        RemodelProbeRecord record = RemodelProbeRunner.Run("PROBE-12", context);
        string yaml = RemodelProbeLedger.Render("32.5.0.48", new[] { record }, Fixed);

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.Equal("COMException 0x80004005", record.RawResult[RemodelProbeRunner.ErrorKey]);
        Assert.DoesNotContain("FICT-", yaml, StringComparison.Ordinal);
        Assert.DoesNotContain("Could not open", yaml, StringComparison.Ordinal);
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

    // ---- the ledger rewritten as each probe finishes (004 T332, decision 166A) -----------

    private static readonly DateTimeOffset Fixed = new DateTimeOffset(2026, 10, 31, 12, 0, 0, TimeSpan.Zero);

    private static IReadOnlyList<string> RowIds(string yaml) =>
        Regex.Matches(yaml, "^  - probe_id: \"([^\"]+)\"\r?$", RegexOptions.Multiline)
            .Cast<Match>().Select(match => match.Groups[1].Value).ToList();

    private static IReadOnlyList<string> RequestedIds(string yaml)
    {
        Match block = Regex.Match(yaml, "^requested:\r?\n((?:  - \"[^\"]+\"\r?\n)*)", RegexOptions.Multiline);
        Assert.True(block.Success, "no requested: list in\n" + yaml);
        return Regex.Matches(block.Groups[1].Value, "\"([^\"]+)\"")
            .Cast<Match>().Select(match => match.Groups[1].Value).ToList();
    }

    [Fact]
    public void Ledger_Render_ListsTheRequestedProbesBeforeTheRows()
    {
        string yaml = RemodelProbeLedger.Render(
            "32.5.0.48", new[] { SampleRecord("PROBE-1") }, Fixed, requested: new[] { "PROBE-1", "PROBE-3" });

        Assert.Contains(
            "generated_at: \"2026-10-31T12:00:00.0000000+00:00\"\nrequested:\n  - \"PROBE-1\"\n  - \"PROBE-3\"\nprobes:\n",
            yaml,
            StringComparison.Ordinal);
    }

    [Fact]
    public void Ledger_Render_WithNoRequestedListGiven_RequestsTheRowsOwnProbes()
    {
        string yaml = RemodelProbeLedger.Render(
            "32.5.0.48", new[] { SampleRecord("PROBE-1"), SampleRecord("PROBE-4") }, Fixed);

        Assert.Equal(new[] { "PROBE-1", "PROBE-4" }, RequestedIds(yaml));
    }

    [Fact]
    public void Ledger_Render_NothingRequestedAndNothingRun_WritesTwoEmptyLists()
    {
        string yaml = RemodelProbeLedger.Render("32.5.0.48", Array.Empty<RemodelProbeRecord>(), Fixed);

        Assert.Contains("requested: []\nprobes: []\n", yaml, StringComparison.Ordinal);
    }

    [Fact]
    public void RunAll_WithTheRecorder_AFakeHostThatThrowsInProbe3_HasLeftTwoRowsAndTheRequestedList()
    {
        // What a run that hangs or is killed inside the third probe leaves on disk: the file as it
        // stands while that probe's host call runs. The host then throws, and the run goes on.
        string root = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", Guid.NewGuid().ToString("N"));
        string[] requested = { "PROBE-2", "PROBE-6", "PROBE-3", "PROBE-21" };
        string ledger = RemodelProbeLedger.FilePath(root, "32.5.0.48");
        var logged = new List<string>();
        string? whileProbe3Ran = null;
        int loggedWhileProbe3Ran = -1;
        var host = new FakeRemodelProbeHost
        {
            ReorderFeatureImpl = (part, move, target, location) =>
            {
                whileProbe3Ran = File.Exists(ledger) ? File.ReadAllText(ledger) : null;
                loggedWhileProbe3Ran = logged.Count;
                throw new InvalidOperationException("the fake host stops here");
            },
        };
        var part = new RemodelProbePart(new object(), Path.Combine(root, "probe-part", "remodel-probe.SLDPRT"), Array.Empty<object>());
        var context = new RemodelProbeContext(part, new SwGate(), "32.5.0.48", host, root);

        try
        {
            IReadOnlyList<RemodelProbeRecord> records = RemodelProbeRunner.RunAll(
                requested, context, finished: RemodelProbeLedger.Recorder(root, "32.5.0.48", requested, logged.Add));

            Assert.NotNull(whileProbe3Ran);
            Assert.Equal(new[] { "PROBE-2", "PROBE-6" }, RowIds(whileProbe3Ran!));
            Assert.Equal(requested, RequestedIds(whileProbe3Ran!));
            Assert.Equal(2, loggedWhileProbe3Ran);

            string final = File.ReadAllText(ledger);
            Assert.Equal(requested, RowIds(final));
            Assert.Equal(requested, RequestedIds(final));
            Assert.Equal(RemodelProbeVerdict.Unresolved, records[2].Verdict);
            Assert.Equal(
                requested.Select((id, index) => $"finished {id}: {records[index].Verdict.CliName()} ({index + 1} of 4)"),
                logged);
            Assert.Equal(new[] { Path.GetFileName(ledger) }, Directory.GetFiles(Path.GetDirectoryName(ledger)!).Select(Path.GetFileName));
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public void Ledger_Write_ReplacesTheWholeFileAndLeavesNothingBesideIt()
    {
        string root = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", Guid.NewGuid().ToString("N"));
        try
        {
            RemodelProbeLedger.Write(root, "32.5.0.48", new[] { SampleRecord("PROBE-1"), SampleRecord("PROBE-2") });
            string path = RemodelProbeLedger.Write(
                root, "32.5.0.48", new[] { SampleRecord("PROBE-4") }, requested: new[] { "PROBE-4", "PROBE-12" });

            string text = File.ReadAllText(path);
            Assert.Equal(new[] { "PROBE-4" }, RowIds(text));
            Assert.Equal(new[] { "PROBE-4", "PROBE-12" }, RequestedIds(text));
            Assert.Equal(new[] { path }, Directory.GetFiles(Path.GetDirectoryName(path)!));
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    // ---- the review round of the ledger's rewrite (004 T342, decision 166A; research R27.9) ----

    private static void InRunFolder(Action<string> test)
    {
        string root = Path.Combine(Path.GetTempPath(), "swreview-probe-tests", Guid.NewGuid().ToString("N"));
        try
        {
            test(root);
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private static RemodelProbeContext RunContext(string root, FakeRemodelProbeHost host) => new RemodelProbeContext(
        new RemodelProbePart(new object(), Path.Combine(root, "probe-part", "remodel-probe.SLDPRT"), Array.Empty<object>()),
        new SwGate(),
        "32.5.0.48",
        host,
        root);

    [Theory]
    [InlineData("the ledger")]
    [InlineData("the temporary file")]
    public void RunAll_WithTheRecorder_AFileHeldAcrossARewrite_EveryProbeStillRunsAndTheLastRewriteHasEveryRow(string held)
    {
        // A reader that holds the ledger without sharing its delete (Get-Content, Python's open(),
        // a sync client) fails File.Replace; one that holds the temporary file fails the write.
        // Either is a rewrite that fails: it is logged, and the run goes on (review finding F1).
        InRunFolder(root =>
        {
            string[] requested = { "PROBE-4", "PROBE-6", "PROBE-3", "PROBE-21" };
            string ledger = RemodelProbeLedger.FilePath(root, "32.5.0.48");
            var logged = new List<string>();
            FileStream? hold = null;
            var host = new FakeRemodelProbeHost
            {
                GetEquationManagerImpl = _ =>
                {
                    hold = held == "the ledger"
                        ? new FileStream(ledger, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)
                        : new FileStream(ledger + ".tmp", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
                    return new FakeEquationManager();
                },
                ReorderFeatureImpl = (part, move, target, location) =>
                {
                    hold?.Dispose();
                    return true;
                },
            };
            IReadOnlyList<RemodelProbeRecord>? records = null;

            try
            {
                Exception? thrown = Record.Exception(() => records = RemodelProbeRunner.RunAll(
                    requested, RunContext(root, host), finished: RemodelProbeLedger.Recorder(root, "32.5.0.48", requested, logged.Add)));

                Assert.Null(thrown);
                Assert.Equal(requested, records!.Select(record => record.ProbeId));
                Assert.Equal(requested, RowIds(File.ReadAllText(ledger)));
                string[] failures = logged.Where(line => line.StartsWith("could not rewrite ", StringComparison.Ordinal)).ToArray();
                string failure = Assert.Single(failures);
                Assert.StartsWith("could not rewrite remodel-32.5.0.48.yaml after PROBE-6 (IOException 0x", failure, StringComparison.Ordinal);
                Assert.DoesNotContain(root, failure, StringComparison.OrdinalIgnoreCase);
                Assert.Equal(new[] { Path.GetFileName(ledger) }, Directory.GetFiles(Path.GetDirectoryName(ledger)!).Select(Path.GetFileName));
            }
            finally
            {
                hold?.Dispose();
            }
        });
    }

    [Fact]
    public void Recorder_StartsThisRunsLedger_AnEarlierRunsLedgerNeverStandsForIt()
    {
        // A run that hangs in its first probe, rerun into the same folder, must not leave the
        // earlier run's finished rows standing for it (review finding F2): the recorder writes
        // this run's requested list and no rows before the first probe starts.
        InRunFolder(root =>
        {
            RemodelProbeLedger.Write(root, "32.5.0.48", new[] { SampleRecord("PROBE-1"), SampleRecord("PROBE-2") });
            string[] requested = { "PROBE-3", "PROBE-6" };
            string ledger = RemodelProbeLedger.FilePath(root, "32.5.0.48");
            var logged = new List<string>();
            string? whileTheFirstRan = null;
            int loggedWhileTheFirstRan = -1;
            var host = new FakeRemodelProbeHost
            {
                ReorderFeatureImpl = (part, move, target, location) =>
                {
                    whileTheFirstRan ??= File.ReadAllText(ledger);
                    loggedWhileTheFirstRan = loggedWhileTheFirstRan < 0 ? logged.Count : loggedWhileTheFirstRan;
                    return true;
                },
            };

            RemodelProbeRunner.RunAll(
                requested, RunContext(root, host), finished: RemodelProbeLedger.Recorder(root, "32.5.0.48", requested, logged.Add));

            Assert.NotNull(whileTheFirstRan);
            Assert.Empty(RowIds(whileTheFirstRan!));
            Assert.Equal(requested, RequestedIds(whileTheFirstRan!));
            Assert.Contains("probes: []\n", whileTheFirstRan!, StringComparison.Ordinal);
            Assert.Equal(0, loggedWhileTheFirstRan);
        });
    }

    [Fact]
    public void Recorder_ALedgerThatCannotBeStarted_ThrowsBeforeAnyProbeRuns()
    {
        // Where the ledger cannot even be started, an earlier run's could stand for this one, so
        // the run is refused before its part is built (review finding F2).
        InRunFolder(root =>
        {
            Directory.CreateDirectory(root);
            File.WriteAllText(Path.Combine(root, RemodelProbeLedger.DirectoryName), "a file where the folder goes");

            Assert.Throws<IOException>(() => RemodelProbeLedger.Recorder(root, "32.5.0.48", new[] { "PROBE-3" }, _ => { }));
        });
    }

    [Fact]
    public void Ledger_Write_OverALeftoverTemporaryFile_WritesTheLedgerAndLeavesNothingBesideIt()
    {
        // A run killed between the temporary file's write and the replace leaves the temporary
        // file; the next write takes it over (review finding F6).
        InRunFolder(root =>
        {
            string ledger = RemodelProbeLedger.FilePath(root, "32.5.0.48");
            Directory.CreateDirectory(Path.GetDirectoryName(ledger)!);
            File.WriteAllText(ledger + ".tmp", "half of an earlier ledger");

            RemodelProbeLedger.Write(root, "32.5.0.48", new[] { SampleRecord("PROBE-4") });

            Assert.Equal(new[] { "PROBE-4" }, RowIds(File.ReadAllText(ledger)));
            Assert.Equal(new[] { ledger }, Directory.GetFiles(Path.GetDirectoryName(ledger)!));
        });
    }

    [Fact]
    public void RunAll_ABodyThatThrows_HandsItsExceptionToThrewAndOnlyItsTypeToTheLedger()
    {
        // 171A keeps the message out of the ledger; the console hands it to remodel-probe.log, which
        // is never committed, so a seat failure can still be read - 148A's "whether it names
        // OpenDoc7" among it (review finding F3).
        const string fictionalPath = @"C:\Users\FICT-engineer\Designs\FICT-bracket.SLDPRT";
        var error = new COMException($"OpenDoc7 could not open '{fictionalPath}'.", unchecked((int)0x80004005));
        var host = new FakeRemodelProbeHost { ReopenPartImpl = _ => throw error };
        var threw = new List<(string Probe, Exception Error)>();

        IReadOnlyList<RemodelProbeRecord> records = RemodelProbeRunner.RunAll(
            new[] { "PROBE-12", "PROBE-6" }, RunContext(@"C:\out", host), threw: (probe, thrown) => threw.Add((probe, thrown)));

        var only = Assert.Single(threw);
        Assert.Equal("PROBE-12", only.Probe);
        Assert.Same(error, only.Error);
        Assert.Equal("COMException 0x80004005", records[0].RawResult[RemodelProbeRunner.ErrorKey]);
    }

    // ---- the golden ledger the Python reader is pinned to (004 T336, decision 166A) -------

    /// <summary>
    /// <c>reviewer/tests/fixtures/remodel/ledger/remodel-32.5.0.yaml</c>: what <see cref="RemodelProbeLedger.Render"/>
    /// writes for a fictional run of the whole catalog that stopped in its last probe, PROBE-21 -
    /// every definition's own text, made-up readings. <c>swreview remodel ledger</c>'s tests parse
    /// the same file, so the renderer and the reader cannot drift apart. "32.5.0" is the spelling
    /// <c>ISldWorks.RevisionNumber</c> answers (<c>SwSession.ReadVersion</c>).
    /// </summary>
    internal static string GoldenLedgerPath() => Path.Combine(
        RemodelLengthUnitsTests.RepositoryRoot(), "reviewer", "tests", "fixtures", "remodel", "ledger", "remodel-32.5.0.yaml");

    private static RemodelProbeRecord GoldenRow(
        string id, RemodelProbeVerdict verdict, long durationMs, string[] interopMembers, params (string Key, string Value)[] raw)
    {
        RemodelProbeDefinition definition = RemodelProbeCatalog.Get(id);
        return new RemodelProbeRecord(
            id,
            definition.Question,
            definition.Method,
            definition.Blocking,
            definition.Fallback,
            verdict,
            raw.ToDictionary(entry => entry.Key, entry => entry.Value, StringComparer.Ordinal),
            "32.5.0",
            durationMs,
            interopMembers);
    }

    private static IReadOnlyList<RemodelProbeRecord> GoldenRows()
    {
        string[] none = Array.Empty<string>();
        return new[]
        {
            GoldenRow("PROBE-1", RemodelProbeVerdict.Verified, 10021, new[] { "ReorderFeature", "set_CommandInProgress" },
                ("blocked_with_flag_clear", "True"), ("blocked_with_flag_set", "False"),
                ("returned_with_flag_clear", "n/a (blocked)"), ("returned_with_flag_set", "False"),
                ("reason", RemodelProbe1Logic.Decide(true, false).Reason)),
            GoldenRow("PROBE-2", RemodelProbeVerdict.Verified, 41, new[] { "GetCount", "get_Equation", "get_Value" },
                ("equation_count", "1"), ("equation_text", "\"w\" = 120"), ("equation_value", "120"),
                ("unit", "document_units_mm"), ("reason", "get_Value returned 120: the equation number is in the document's length unit, matching R3.6.")),
            GoldenRow("PROBE-3", RemodelProbeVerdict.Verified, 230, new[] { "ReorderFeature", "GetName" },
                ("legal_returned", "True"), ("legal_order_unchanged", "True"), ("illegal_returned", "False"),
                ("illegal_order_unchanged", "True"), ("tree_before", "Boss-Extrude1,Cut-Extrude1,Fillet1,Fillet1,Shell1"),
                ("tree_after_illegal", "Boss-Extrude1,Cut-Extrude1,Fillet1,Fillet1,Shell1"),
                ("reason", RemodelProbe3Logic.Decide(true, true, false, true).Reason)),
            GoldenRow("PROBE-4", RemodelProbeVerdict.Verified, 95, new[] { "InsertFeatureTreeFolder2", "Select2" },
                ("contiguous_folder_built", "True"), ("non_contiguous_folder_built", "False"),
                ("reason", RemodelProbe4Logic.Decide(true, false).Reason)),
            GoldenRow("PROBE-5", RemodelProbeVerdict.Unresolved, 310, new[] { "ReorderFeature", "MoveToFolder", "MakeSubFeature" },
                ("reorder_to_folder", "True"), ("move_to_folder", "error: COMException 0x80004005"), ("make_sub_feature", "False"),
                ("reason", "1 of 3 calls threw; see the per-call entries above.")),
            GoldenRow("PROBE-6", RemodelProbeVerdict.Verified, 17, new[] { "Add3", "GetCount" },
                ("count_before", "1"), ("add3_result", "1"), ("count_after", "2"),
                ("reason", RemodelProbe6Logic.Decide(1, 1, 2).Reason)),
            GoldenRow("PROBE-7", RemodelProbeVerdict.Verified, 22, new[] { "Add3", "set_Equation", "get_Equation" },
                ("before", "\"probe7check\" = 1"), ("after", "\"probe7check\" = 99"),
                ("reason", "set_Equation's edit is reflected on the next read.")),
            GoldenRow("PROBE-8", RemodelProbeVerdict.Verified, 4120, new[] { "CreateMassProperty2", "Recalculate" },
                ("accuracy_level", "default"), ("measurement_scope", "whole_part"), ("box_status", "measured"),
                ("box_volume_rel_error", "3.000000E-012"), ("box_area_rel_error", "4.000000E-012"),
                ("cylinder_status", "measured"), ("cylinder_volume_rel_error", "6.000000E-011"),
                ("reason", "both default whole-part shapes measured cleanly and each override experiment was observed; only the plain readings supply attained calibration errors.")),
            GoldenRow("PROBE-9", RemodelProbeVerdict.Verified, 160, new[] { "SetSuppression2", "ForceRebuild3" },
                ("suppress_returned", "True"), ("whats_wrong_count", "2"), ("whats_wrong_element_kind", "feature_names"),
                ("reason", "GetWhatsWrong's Features array held feature_names on this build.")),
            GoldenRow("PROBE-10", RemodelProbeVerdict.Verified, 33, new[] { "GetName", "set_Name" },
                ("marker_before", "False"), ("marker_after", "False"), ("marker_name_after", "(none)"),
                ("reason", "no ___EndTag___ marker appeared on 2024, before or after the rename.")),
            GoldenRow("PROBE-11", RemodelProbeVerdict.Verified, 12, new[] { "GetTypeName2" },
                ("type[Comments]", "CommentsFolder"), ("type[Front Plane]", "RefPlane"), ("type[Origin]", "OriginProfileFeature"),
                ("type[Boss-Extrude1]", "Extrusion"), ("type[Cut-Extrude1]", "Cut"), ("type[Fillet1]", "Fillet"),
                ("type[Shell1]", "Shell"), ("type[Folder1]", "FtrFolder"), ("type[FICT-Feature1]", "FictProbeType"),
                ("reason", "every feature in the tree answered GetTypeName2; compare the census above against "
                    + "reviewer/src/swreview/checks/rms_types.yaml by hand - that table lives outside this build.")),
            GoldenRow("PROBE-12", RemodelProbeVerdict.Verified, 1880, new[] { "ICustomPropertyManager.Add3", "ISldWorks.OpenDoc7" },
                ("add_result", "0"), ("saved", "True"), ("found_after_reopen", "True"),
                ("value_after_reopen", "verify-me"), ("resolved_value_after_reopen", "verify-me"),
                ("reason", RemodelProbe12Logic.Decide(true, true, "verify-me", "verify-me").Reason)),
            GoldenRow("PROBE-13", RemodelProbeVerdict.Refuted, 8, none,
                ("file_copy_error", "IOException 0x80070020"), ("file_copy_succeeded", "False"), ("fallback_succeeded", "True"),
                ("reason", RemodelProbe13Logic.Decide(false, true).Reason)),
            GoldenRow("PROBE-20", RemodelProbeVerdict.Unresolved, 5, none,
                ("error", "COMException 0x80004005")),
        };
    }

    [Fact]
    public void Ledger_Render_WritesTheGoldenLedgerTheReaderIsPinnedTo()
    {
        string rendered = RemodelProbeLedger.Render(
            "32.5.0", GoldenRows(), Fixed, requested: RemodelProbeCatalog.AllIds);

        // A checkout may turn the file's line endings to CRLF; what is pinned is the text.
        string golden = File.ReadAllText(GoldenLedgerPath()).Replace("\r\n", "\n");
        Assert.Equal(golden, rendered);
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
