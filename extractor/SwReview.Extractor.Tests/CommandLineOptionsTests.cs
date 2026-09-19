using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Console;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T071's additions to the T059 parser: the switches, the whole-number option, the
/// <c>--fasteners</c> and <c>--view</c> enums, and the multi-valued <c>--pairs</c>.
/// <see cref="CommandLineTests"/> covers the parser itself.
///
/// Every one of these is a silent-wrong-answer guard. <c>--fasteners exclude</c> misread as
/// include reports interferences the engineer asked to leave out; <c>--pairs</c> misread
/// checks the wrong components and reports nothing found.
/// </summary>
public class CommandLineOptionsTests
{
    // The PRODUCTION option lists, not copies of them. A test-local copy proves nothing
    // about what the shipped command accepts - it would pass with the real list untouched -
    // and duplicating the lists here was a second place to forget an option (Principle V).
    private static readonly string[] DumpOptions = Program.KnownOptions(Program.DumpOptionNames);

    private static readonly string[] ResolveOptions =
        Program.KnownOptions(Program.ResolveOptionNames);

    private static readonly string[] InterferenceOptions =
        Program.KnownOptions(Program.InterferenceOptionNames);

    private static readonly string[] CaptureOptions =
        Program.KnownOptions(Program.CaptureOptionNames);

    private static readonly string[] ServeOptions = Program.KnownOptions(Program.ServeOptionNames);

    private static readonly string[] ProbeOptions = Program.KnownOptions(Program.ProbeOptionNames);

    private static readonly string[] SuppressTestOptions =
        Program.KnownOptions(Program.SuppressTestOptionNames);

    private static readonly string[] RemodelProbeOptions =
        Program.KnownOptions(Program.RemodelProbeOptionNames);

    // ---- switches ----------------------------------------------------------------

    [Fact]
    public void Flag_BareSwitch_IsTrue()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--coincident-as-interference", "--out", @"C:\out" },
            1,
            InterferenceOptions);

        Assert.True(parsed.Flag("coincident-as-interference"));
        Assert.Equal(@"C:\out", parsed.Value("out"));
    }

    [Fact]
    public void Flag_AbsentIsFalse()
    {
        // A run that did not ask for coincidence detection must not silently get it.
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--out", @"C:\out" }, 1, InterferenceOptions);

        Assert.False(parsed.Flag("coincident-as-interference"));
        Assert.False(parsed.Flag("ignore-hidden"));
        Assert.False(parsed.Flag("subassemblies-as-components"));
        Assert.False(parsed.Flag("include-multibody"));
    }

    [Theory]
    [InlineData("true", true)]
    [InlineData("false", false)]
    [InlineData("1", true)]
    [InlineData("0", false)]
    [InlineData("YES", true)]
    public void Flag_ExplicitValue_IsRead(string value, bool expected)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--ignore-hidden", value }, 1, InterferenceOptions);

        Assert.Equal(expected, parsed.Flag("ignore-hidden"));
    }

    [Fact]
    public void Flag_NonsenseValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--ignore-hidden", "maybe" }, 1, InterferenceOptions);

        Assert.Throws<UsageError>(() => parsed.Flag("ignore-hidden"));
    }

    // ---- dump --reuse (feature 005 lever 9, T091) ---------------------------------

    [Fact]
    public void Reuse_AbsentIsFalse()
    {
        // The lever is off unless it is asked for. A dump that quietly copied an earlier
        // package would answer about a design nobody checked was the one on screen.
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--out", @"C:\out" }, 1, DumpOptions);

        Assert.False(parsed.Flag("reuse"));
    }

    [Fact]
    public void Reuse_BareSwitch_IsTrue()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--reuse", "--out", @"C:\out" }, 1, DumpOptions);

        Assert.True(parsed.Flag("reuse"));
        Assert.Equal(@"C:\out", parsed.Value("out"));
    }

    [Theory]
    [InlineData("true", true)]
    [InlineData("false", false)]
    public void Reuse_ExplicitValue_IsRead(string value, bool expected)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--reuse", value, "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Equal(expected, parsed.Flag("reuse"));
    }

    [Fact]
    public void Reuse_NonsenseValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--reuse", "sometimes", "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.Flag("reuse"));
    }

    [Fact]
    public void Reuse_IsADumpOptionAndNotAnOptionOfEveryCommand()
    {
        // It changes what a dump reads; nothing else in the CLI has anything to reuse.
        Assert.Contains("reuse", DumpOptions);
        Assert.DoesNotContain("reuse", InterferenceOptions);
        Assert.DoesNotContain("reuse", CaptureOptions);
        Assert.DoesNotContain("reuse", ServeOptions);
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "capture", "--reuse" }, 1, CaptureOptions));
    }

    // ---- --truncate-after --------------------------------------------------------

    [Fact]
    public void Int_ReadsAWholeNumber()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--truncate-after", "3" }, 1, InterferenceOptions);

        Assert.Equal(3, parsed.Int("truncate-after"));
    }

    [Fact]
    public void Int_AbsentIsNull()
    {
        Assert.Null(
            CommandLine.Parse(new[] { "interference" }, 1, InterferenceOptions).Int("truncate-after"));
    }

    [Theory]
    [InlineData("many")]
    [InlineData("-1")]
    [InlineData("2.5")]
    public void Int_NotAWholeNumber_Throws(string value)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--truncate-after", value }, 1, InterferenceOptions);

        Assert.Throws<UsageError>(() => parsed.Int("truncate-after"));
    }

    [Fact]
    public void Int_OptionWithNoValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--truncate-after", "--out", @"C:\out" }, 1, InterferenceOptions);

        Assert.Throws<UsageError>(() => parsed.Int("truncate-after"));
    }

    // ---- --features --------------------------------------------------------------

    [Theory]
    [InlineData("tree", FeatureScope.Tree)]
    [InlineData("none", FeatureScope.None)]
    [InlineData("TREE", FeatureScope.Tree)]
    public void FeatureScope_ReadsEveryContractValue(string value, FeatureScope expected)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--features", value, "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Equal(expected, parsed.FeatureScope());
    }

    [Fact]
    public void FeatureScope_DefaultsToTree()
    {
        // The RMS family reads features[]; a dump that quietly stopped writing them would
        // leave every part rule unresolved with nothing on the command line to explain it.
        Assert.Equal(
            FeatureScope.Tree,
            CommandLine.Parse(new[] { "dump", "--out", @"C:\out" }, 1, DumpOptions).FeatureScope());
    }

    [Fact]
    public void FeatureScope_UnknownValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--features", "some" }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.FeatureScope());
    }

    [Fact]
    public void FeatureScope_IsOnlyAnOptionOfDump()
    {
        // A typo that lands --features on another command is a usage error, not a silent
        // no-op that dumps the trees anyway.
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "capture", "--features", "none" }, 1, CaptureOptions));
    }

    // ---- --equations -------------------------------------------------------------

    [Theory]
    [InlineData("on", EquationScope.On)]
    [InlineData("off", EquationScope.Off)]
    [InlineData("OFF", EquationScope.Off)]
    public void EquationScope_ReadsEveryContractValue(string value, EquationScope expected)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--equations", value, "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Equal(expected, parsed.EquationScope());
    }

    [Fact]
    public void EquationScope_DefaultsToOn()
    {
        // The two parametric rules read equations[]; a dump that quietly stopped writing
        // them would report "no global variables" about a manager nobody opened.
        Assert.Equal(
            EquationScope.On,
            CommandLine.Parse(new[] { "dump", "--out", @"C:\out" }, 1, DumpOptions).EquationScope());
    }

    [Fact]
    public void EquationScope_UnknownValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--equations", "none" }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.EquationScope());
    }

    [Fact]
    public void EquationScope_IsOnlyAnOptionOfDump()
    {
        // A typo that lands --equations on another command is a usage error, not a silent
        // no-op that reads the equations anyway.
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "capture", "--equations", "off" }, 1, CaptureOptions));
    }

    // ---- --profile ---------------------------------------------------------------

    [Theory]
    [InlineData("full", DumpProfile.Full)]
    [InlineData("model-check", DumpProfile.ModelCheck)]
    [InlineData("MODEL-CHECK", DumpProfile.ModelCheck)]
    [InlineData("standards", DumpProfile.Standards)]
    [InlineData("STANDARDS", DumpProfile.Standards)]
    public void DumpProfile_ReadsEveryContractValue(string value, DumpProfile expected)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--profile", value, "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Equal(expected, parsed.DumpProfile());
    }

    [Fact]
    public void DumpProfile_DefaultsToFull()
    {
        // The design review reads holes, fasteners, faces and meshes. A dump that quietly
        // fell back to the reduced profile would report a model with no holes at all, which
        // reads as a bad design rather than as a partial extract (FR-022).
        Assert.Equal(
            DumpProfile.Full,
            CommandLine.Parse(new[] { "dump", "--out", @"C:\out" }, 1, DumpOptions).DumpProfile());
    }

    [Theory]
    [InlineData("quick")]

    // The near misses this parser exists to refuse. `standard` and `model_check` are the
    // two a hand would actually type - the singular, and the IR spelling of the profile
    // beside it - and a dump that fell back to full on either would tessellate every body
    // on the one path built to avoid it (FR-027).
    [InlineData("standard")]
    [InlineData("model_check")]
    public void DumpProfile_UnknownValue_Throws(string value)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--profile", value }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.DumpProfile());
    }

    [Fact]
    public void DumpProfile_IsOnlyAnOptionOfDump()
    {
        // A typo that lands --profile on another command is a usage error, not a silent
        // no-op that runs every phase anyway.
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "capture", "--profile", "model-check" }, 1, CaptureOptions));
    }

    [Theory]
    [InlineData("full")]
    [InlineData("model-check")]
    [InlineData("standards")]
    public void DumpProfile_CliName_RoundTripsEveryContractValue(string value)
    {
        // extract.log reconstructs the command that ran, so the spelling it prints has to be
        // the spelling this parser takes back. One mapping, used by the parser and by the
        // log line, is what keeps the two from drifting.
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--profile", value, "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Equal(value, CommandLine.CliName(parsed.DumpProfile()));
    }

    [Fact]
    public void DumpProfile_CliName_IsNotTheIrSpelling()
    {
        // The trap this mapping exists for: the IR records model_check and the command line
        // takes model-check, so a log line written through the IR spelling records a command
        // that does not parse.
        Assert.Equal("model_check", PackageSerializer.EnumToJsonName(DumpProfile.ModelCheck));
        Assert.Equal("model-check", CommandLine.CliName(DumpProfile.ModelCheck));
        Assert.Equal("full", CommandLine.CliName(DumpProfile.Full));

        // The third profile is the one case where the two spellings agree; it is pinned so
        // that stays a fact about this mapping rather than a coincidence nobody checked.
        Assert.Equal("standards", PackageSerializer.EnumToJsonName(DumpProfile.Standards));
        Assert.Equal("standards", CommandLine.CliName(DumpProfile.Standards));
    }

    // ---- probe rms ---------------------------------------------------------------

    [Fact]
    public void Probe_ReadsTheDocumentOption()
    {
        // "probe rms --doc <part>": the probe's subject is args[1], so its options start at
        // index 2 and everything before that is not an option at all.
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "rms", "--doc", @"C:\vault\housing.SLDPRT" }, 2, ProbeOptions);

        Assert.Equal(@"C:\vault\housing.SLDPRT", parsed.Value("doc"));
    }

    [Fact]
    public void Probe_DocIsOptionalAndMeansTheActiveDocument()
    {
        Assert.Null(CommandLine.Parse(new[] { "probe", "rms" }, 2, ProbeOptions).Value("doc"));
    }

    [Theory]
    [InlineData("out")]
    [InlineData("meshes")]
    [InlineData("config")]
    public void Probe_TakesNoOptionThatImpliesAWriteOrADump(string option)
    {
        // The probe prints and writes nothing (contracts/cli.md). An option it does not have
        // is a usage error rather than a silent no-op that looks like it was honoured.
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "probe", "rms", "--" + option, "x" }, 2, ProbeOptions));
    }

    [Fact]
    public void Probe_NamesEveryInteropMemberItReadsPerFeatureToTheGuard()
    {
        // contracts/cli.md row 19: "Read-only; uses the read-only guard." SwFeatureReader
        // leaves its single-call members ungated on purpose - FeatureDumper names them, so
        // the fake path records the production names - which means the probe has to name
        // them itself. Ungated they reach no ReadOnlyGuard.Assert, no circuit breaker and no
        // SC-004 observer, and the probe would be running the RMS read surface outside the
        // guard the contract names. These are the production names, not copies.
        Assert.Equal(
            new[]
            {
                "GetChildren",
                "GetParents",
                "IsSuppressed2",
                "GetErrorCode2",
                "Description",
                "GetSpecificFeature2",
                "GetConstrainedStatus",
                "GetDefinition",
                "DefaultRadius",
            },
            Program.ProbeInteropMembers);

        foreach (string member in Program.ProbeInteropMembers)
        {
            ReadOnlyGuard.Assert(member);
        }
    }

    // ---- probe standards (T094) ---------------------------------------------------

    [Fact]
    public void StandardsProbe_IsTheSecondSubjectOfProbe()
    {
        // contracts/cli.md row 20: "probe standards --doc <document>". The subject list is
        // the shipped one, so a subject added to the switch and forgotten here - or the
        // reverse - is a failing test rather than an "Unknown probe" at the workstation.
        // "remodel" (tasks.md T031, T032) is the third and the one mutating subject.
        Assert.Equal(new[] { "rms", "standards", "remodel" }, Program.ProbeSubjects);
    }

    [Fact]
    public void StandardsProbe_ReadsTheDocumentOption()
    {
        // The subject is args[1], so the options start at index 2 - the same shape
        // "probe rms" parses with, and the same option list.
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "standards", "--doc", @"C:\vault\frame.SLDDRW" }, 2, ProbeOptions);

        Assert.Equal(@"C:\vault\frame.SLDDRW", parsed.Value("doc"));
    }

    [Fact]
    public void StandardsProbe_DocIsOptionalAndMeansTheActiveDocument()
    {
        Assert.Null(CommandLine.Parse(new[] { "probe", "standards" }, 2, ProbeOptions).Value("doc"));
    }

    [Theory]
    [InlineData("out")]
    [InlineData("profile")]
    [InlineData("meshes")]
    public void StandardsProbe_TakesNoOptionThatImpliesAWriteOrADump(string option)
    {
        // The probe prints and writes nothing (contracts/cli.md). An option it does not have
        // is a usage error rather than a silent no-op that looks like it was honoured.
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "probe", "standards", "--" + option, "x" }, 2, ProbeOptions));
    }

    [Fact]
    public void StandardsProbe_BuildsItsGateWithTheReadOnlyGuard()
    {
        // contracts/cli.md row 20: the run is read-only and "activates no sheet". The gate is
        // built HERE, not left to SwSession's default, so the guard it carries is a decision
        // the test can see - and it is the READ-ONLY guard, never the suppress-test one,
        // which is the only other ICallGuard in the product.
        var observer = new RecordingGateObserver();
        SwGate gate = Program.StandardsProbeGate(observer);

        Assert.Same(observer, gate.Observer);
        Assert.Equal("ok", gate.Call("GetViews", () => "ok"));
        Assert.Throws<MutatingCallError>(() => gate.Call("ActivateSheet", () => "no"));
        Assert.Throws<MutatingCallError>(() => gate.Call("ActivateView", () => "no"));
        Assert.Throws<MutatingCallError>(() => gate.Call("SetSuppression2", () => "no"));
        Assert.Throws<MutatingCallError>(() => gate.Call("ForceRebuild3", () => "no"));

        // Attempted-and-refused is part of "what did this run touch", so every name is in the
        // gated set and every refusal is recorded for the log to print.
        Assert.Equal(
            new[] { "GetViews", "ActivateSheet", "ActivateView", "SetSuppression2", "ForceRebuild3" },
            observer.Members);
        Assert.Equal(4, observer.Refusals.Count);
    }

    [Fact]
    public void StandardsProbe_NamesEveryInteropMemberItReadsToTheGuard()
    {
        // The ten probes of research.md R4 read members the shipped readers leave ungated on
        // purpose (their dumpers name them). Ungated they would reach no ReadOnlyGuard.Assert,
        // no circuit breaker and no observer, and the probe's own gate log - the artifact
        // contracts/cli.md says proves the run - would be missing exactly the reads it is
        // printing. These are the production names, not copies.
        Assert.Equal(
            new[]
            {
                // The run's own header, and the check that stops SwSession.Attach opening
                // anything - the only reason this command can claim it opened no document.
                "GetOpenDocumentByName",
                "GetPathName",
                "Configuration.Name",

                // PROBE-1, the exploded read.
                "IsExploded",
                "IModelDocExtension.IsExploded",
                "GetConfigurationNames",
                "GetConfigurationByName",
                "GetNumberOfExplodeSteps",
                "GetModelDoc2",

                // PROBE-2, the transparency-override polarity.
                "HasMaterialPropertyValues",
                "GetMaterialPropertyValues2",

                // PROBE-3, component visibility.
                "Visible",
                "GetVisibility",

                // PROBE-4, the revision-table read.
                "RevisionTable",
                "ITableAnnotation.Type",
                "CurrentRevision",
                "TotalRowCount",
                "Text",
                "DisplayedText",

                // PROBE-5, the note walk, and PROBE-7's sheet enumeration.
                "Sheet",
                "GetViews",
                "GetName",
                "Type",
                "GetNotes",
                "GetText",
                "GetFirstView",
                "GetNextView",

                // PROBE-6, the drawing-view and annotation walk.
                "GetName2",
                "GetReferencedModelName",
                "ReferencedDocument",
                "GetAnnotations",
                "GetAnnotationCount",
                "GetFirstAnnotation3",
                "GetNext3",
                "GetType",
                "IsDangling",
                "GetDisplayDimensions",
                "Type2",
                "GetOverride",
                "GetOverrideValue",

                // PROBE-8, the cut-list walk.
                "Feature.Name",
                "GetTypeName2",
                "GetSpecificFeature2",
                "GetBodyCount",
                "ExcludeFromCutList",

                // PROBE-9, the sketch text-segment read.
                "GetSketchTextSegments",

                // PROBE-10, the persistent references.
                "GetPersistReferenceCount3",
            },
            Program.StandardsProbeInteropMembers);

        foreach (string member in Program.StandardsProbeInteropMembers)
        {
            ReadOnlyGuard.Assert(member);
        }

        Assert.Equal(
            Program.StandardsProbeInteropMembers.Length,
            Program.StandardsProbeInteropMembers.Distinct(StringComparer.OrdinalIgnoreCase).Count());
    }

    [Fact]
    public void StandardsProbe_GateLogProvesTheThreeClaimsWhenNothingWasTouched()
    {
        // "Activates no sheet, opens no document, changes no display state, and its own gate
        // log is printed at the end so the run proves it" (contracts/cli.md row 20). Each
        // claim is its own line, and each names what it watched for, because a bare "none" is
        // only worth reading beside the list it is none of.
        IReadOnlyList<string> lines = Program.StandardsProbeGateLogLines(
            new[] { "GetViews", "GetNotes" }, new MutatingCallError[0]);

        Assert.Equal("gate log: the read-only guard, 2 distinct interop members", lines[0]);
        Assert.Contains("  members: GetViews, GetNotes", lines);
        Assert.Contains("  mutating members: none", lines);
        Assert.Contains("  refusals: none", lines);
        Assert.Contains(lines, line => line.StartsWith("  sheet activation: none  (watched: ActivateSheet, "));
        Assert.Contains(lines, line => line.StartsWith("  document opening: none  (watched: OpenDoc6, "));
        Assert.Contains(lines, line => line.StartsWith("  display state: none  (watched: "));
    }

    [Fact]
    public void StandardsProbe_GateLogNamesWhatWasTouchedWhenSomethingWas()
    {
        // The log is evidence, so it must be able to say "yes". A run that activated a sheet
        // prints the member on the sheet-activation line rather than a "none" nobody can
        // check.
        IReadOnlyList<string> lines = Program.StandardsProbeGateLogLines(
            new[] { "ActivateSheet", "OpenDoc6", "ShowNamedView2" }, new MutatingCallError[0]);

        Assert.Contains(lines, line => line.StartsWith("  mutating members: ActivateSheet"));
        Assert.Contains(lines, line => line.StartsWith("  sheet activation: ActivateSheet  (watched:"));
        Assert.Contains(lines, line => line.StartsWith("  document opening: OpenDoc6  (watched:"));
        Assert.Contains(lines, line => line.StartsWith("  display state: ShowNamedView2  (watched:"));
    }

    [Fact]
    public void StandardsProbe_GateLogNamesEveryRefusal()
    {
        IReadOnlyList<string> lines = Program.StandardsProbeGateLogLines(
            new[] { "ActivateSheet" },
            new[] { new MutatingCallError("ActivateSheet", "ActivateSheet modifies the model.") });

        Assert.Contains("  refusals: ActivateSheet modifies the model.", lines);
    }

    [Fact]
    public void StandardsProbe_GateLogIsPrintedEvenWhenTheRunGatedNothing()
    {
        // A run that failed on attach still prints its gate log: "it touched nothing" is the
        // answer the log exists to give, and a missing log reads as an unanswered question.
        IReadOnlyList<string> lines = Program.StandardsProbeGateLogLines(
            new string[0], new MutatingCallError[0]);

        Assert.Equal("gate log: the read-only guard, 0 distinct interop members", lines[0]);
        Assert.Contains("  members: none", lines);
        Assert.Contains("  mutating members: none", lines);
    }

    [Fact]
    public void StandardsProbe_WatchedMembersAnswerExactlyOneClaimEach()
    {
        // Three claims, three lists. A name on two of them would be reported twice and
        // silently make one line's "none" a lie about the other.
        string[] watched = Program.StandardsProbeSheetActivationMembers
            .Concat(Program.StandardsProbeDocumentOpeningMembers)
            .Concat(Program.StandardsProbeDisplayStateMembers)
            .ToArray();

        Assert.Equal(watched.Length, watched.Distinct(StringComparer.OrdinalIgnoreCase).Count());
        Assert.Contains("ActivateSheet", Program.StandardsProbeSheetActivationMembers);
        Assert.Contains("ActivateView", Program.StandardsProbeSheetActivationMembers);
        Assert.Contains("OpenDoc6", Program.StandardsProbeDocumentOpeningMembers);
    }

    [Fact]
    public void StandardsProbe_RefusesADocumentThatIsNotAlreadyOpen()
    {
        // SwSession.Attach would otherwise OPEN the named document read-only - the
        // extractor's one file-opening call - and contracts/cli.md says this run opens no
        // document. The refusal names the document and says why, before SOLIDWORKS is asked
        // for anything else.
        string message = Program.StandardsProbeDocumentNotOpenMessage(@"C:\vault\frame.SLDDRW");

        Assert.Contains(@"C:\vault\frame.SLDDRW", message);
        Assert.Contains("opens no document", message);
    }

    // ---- suppress-test -----------------------------------------------------------

    [Fact]
    public void SuppressTest_AcceptsExactlyTheContractsOptions()
    {
        // contracts/cli.md row 20. An option the command does not have is a usage error,
        // never a silent no-op: --limit misspelled must not run all 400 features.
        Assert.Equal(
            new[] { "doc", "plan", "acknowledge-rebuild", "out", "limit", "timeout-seconds" },
            Program.SuppressTestOptionNames);

        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "suppress-test", "--faces", "all" }, 1, SuppressTestOptions));
    }

    [Fact]
    public void SuppressTest_PlanIsRequired()
    {
        // The plan is the only place this command learns what to suppress; without one there
        // is nothing to run and nothing to default to (research R7).
        CommandLine parsed = CommandLine.Parse(
            new[] { "suppress-test", "--doc", @"C:\p.SLDPRT", "--out", @"C:\out" },
            1,
            SuppressTestOptions);

        Assert.Throws<UsageError>(() => Program.SuppressTestSettingsFrom(parsed));
    }

    [Fact]
    public void SuppressTest_AcknowledgementIsOffUnlessTheFlagIsGiven()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "suppress-test", "--doc", @"C:\p.SLDPRT", "--plan", @"C:\plan.json", "--out", @"C:\out" },
            1,
            SuppressTestOptions);

        Assert.False(Program.SuppressTestSettingsFrom(parsed).Acknowledged);
    }

    [Fact]
    public void SuppressTest_ReadsThePlanTheFlagAndTheBounds()
    {
        CommandLine parsed = CommandLine.Parse(
            new[]
            {
                "suppress-test",
                "--doc", @"C:\vault\housing.SLDPRT",
                "--plan", @"C:\out\suppress-plan.json",
                "--acknowledge-rebuild",
                "--out", @"C:\out",
                "--limit", "5",
                "--timeout-seconds", "60",
            },
            1,
            SuppressTestOptions);

        SuppressTestSettings settings = Program.SuppressTestSettingsFrom(parsed);

        Assert.Equal(@"C:\vault\housing.SLDPRT", parsed.Value("doc"));
        Assert.Equal(@"C:\out", parsed.Value("out"));
        Assert.Equal(@"C:\out\suppress-plan.json", settings.PlanFile);
        Assert.True(settings.Acknowledged);
        Assert.Equal(5, settings.Limit);
        Assert.Equal(60, settings.TimeoutSeconds);
    }

    [Fact]
    public void SuppressTest_BoundsDefaultToTheContractsValues()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "suppress-test", "--doc", @"C:\p.SLDPRT", "--plan", @"C:\plan.json", "--out", @"C:\out" },
            1,
            SuppressTestOptions);

        SuppressTestSettings settings = Program.SuppressTestSettingsFrom(parsed);

        Assert.Equal(50, settings.Limit);
        Assert.Equal(900, settings.TimeoutSeconds);
    }

    [Theory]
    [InlineData("limit")]
    [InlineData("timeout-seconds")]
    public void SuppressTest_ABoundOfZeroIsAUsageError(string option)
    {
        // Zero would run nothing and report a table of truncated rows as though the engineer
        // had asked for it.
        CommandLine parsed = CommandLine.Parse(
            new[]
            {
                "suppress-test", "--doc", @"C:\p.SLDPRT", "--plan", @"C:\plan.json",
                "--out", @"C:\out", "--" + option, "0",
            },
            1,
            SuppressTestOptions);

        Assert.Throws<UsageError>(() => Program.SuppressTestSettingsFrom(parsed));
    }

    [Fact]
    public void SuppressTest_WithoutTheFlag_RefusesBeforeTheSessionIsTouched()
    {
        // contracts/cli.md row 20: "Refuses, before touching anything: without the flag".
        // The library invariant in SuppressTest.Run refuses too, but only after the command
        // has attached to (or started) SOLIDWORKS and opened the engineer's part. The proof
        // that nothing was touched is the --out directory: ExecuteSuppressTest opens
        // suppress-test.log there as its first act, and the log creates the directory.
        string directory = Path.Combine(
            Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));

        int exit = Program.RunSuppressTest(new[]
        {
            "suppress-test",
            "--doc", Path.Combine(directory, "housing.SLDPRT"),
            "--plan", Path.Combine(directory, "suppress-plan.json"),
            "--out", directory,
        });

        Assert.Equal(1, exit);
        Assert.False(Directory.Exists(directory));
        Assert.Contains(
            "--acknowledge-rebuild",
            SuppressTest.AcknowledgementRequiredMessage,
            StringComparison.Ordinal);
    }

    [Fact]
    public void SuppressTest_BuildsItsGateWithTheSuppressTestGuard()
    {
        // The exemption exists in exactly one gate in the product. If this ever came back as
        // an ordinary gate the command would refuse its own suppression; if any other command
        // built one like it, the read-only promise would be gone.
        var observer = new RecordingGateObserver();
        SwGate gate = Program.SuppressTestGate(observer);

        Assert.True(gate.Call("SetSuppression2", () => true));
        Assert.True(gate.Call("ForceRebuild3", () => true));
        Assert.Throws<MutatingCallError>(() => gate.Call("Save3", () => true));
        Assert.Throws<MutatingCallError>(() => gate.Call("SetSaveFlag", () => true));
        Assert.Throws<MutatingCallError>(() => gate.Call("ForceRebuildAll", () => true));

        Assert.Equal(
            new[] { "SetSuppression2", "ForceRebuild3", "Save3", "SetSaveFlag", "ForceRebuildAll" },
            observer.Members.ToArray());
        Assert.Equal(3, observer.Refusals.Count);
    }

    // ---- probe remodel (T031) -----------------------------------------------------

    [Fact]
    public void RemodelProbe_AcceptsExactlyTheContractsOptions()
    {
        Assert.Equal(
            new[] { "probe", "out", "keep-part", "acknowledge-throwaway-part" },
            Program.RemodelProbeOptionNames);

        Assert.Contains("allow-start", RemodelProbeOptions);
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "probe", "remodel", "--doc", @"C:\p.SLDPRT" }, 2, RemodelProbeOptions));
    }

    [Fact]
    public void RemodelProbe_OutIsRequired()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "remodel", "--acknowledge-throwaway-part" }, 2, RemodelProbeOptions);

        Assert.Throws<UsageError>(() => Program.RemodelProbeSettingsFrom(parsed));
    }

    [Fact]
    public void RemodelProbe_AcknowledgementIsOffUnlessTheFlagIsGiven()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "remodel", "--out", @"C:\out" }, 2, RemodelProbeOptions);

        Assert.False(Program.RemodelProbeSettingsFrom(parsed).Acknowledged);
    }

    [Fact]
    public void RemodelProbe_KeepPartDefaultsToFalseAndTheBareSwitchIsTrue()
    {
        CommandLine absent = CommandLine.Parse(
            new[] { "probe", "remodel", "--out", @"C:\out" }, 2, RemodelProbeOptions);
        Assert.False(Program.RemodelProbeSettingsFrom(absent).KeepPart);

        CommandLine given = CommandLine.Parse(
            new[] { "probe", "remodel", "--out", @"C:\out", "--keep-part" }, 2, RemodelProbeOptions);
        Assert.True(Program.RemodelProbeSettingsFrom(given).KeepPart);
    }

    [Fact]
    public void RemodelProbe_ProbeIdsDefaultToEveryKnownProbeWhenTheOptionIsAbsent()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "remodel", "--out", @"C:\out" }, 2, RemodelProbeOptions);

        Assert.Equal(RemodelProbeCatalog.AllIds, Program.RemodelProbeSettingsFrom(parsed).ProbeIds);
    }

    [Fact]
    public void RemodelProbe_ProbeReadsACommaSeparatedListAndUpperCasesIt()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "remodel", "--probe", "probe-1,PROBE-3", "--out", @"C:\out" },
            2,
            RemodelProbeOptions);

        Assert.Equal(new[] { "PROBE-1", "PROBE-3" }, Program.RemodelProbeSettingsFrom(parsed).ProbeIds);
    }

    [Fact]
    public void RemodelProbe_UnknownProbeId_IsAUsageError()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "remodel", "--probe", "PROBE-99", "--out", @"C:\out" },
            2,
            RemodelProbeOptions);

        Assert.Throws<UsageError>(() => Program.RemodelProbeSettingsFrom(parsed));
    }

    [Fact]
    public void RemodelProbe_ReadsTheOutputDirectoryAndSwVersionFreeSettings()
    {
        CommandLine parsed = CommandLine.Parse(
            new[]
            {
                "probe", "remodel",
                "--probe", "PROBE-8",
                "--out", @"C:\out\remodel",
                "--keep-part",
                "--acknowledge-throwaway-part",
            },
            2,
            RemodelProbeOptions);

        RemodelProbeSettings settings = Program.RemodelProbeSettingsFrom(parsed);

        Assert.Equal(@"C:\out\remodel", settings.OutputDirectory);
        Assert.Equal(new[] { "PROBE-8" }, settings.ProbeIds);
        Assert.True(settings.KeepPart);
        Assert.True(settings.Acknowledged);
    }

    [Fact]
    public void RemodelProbe_WithoutTheFlag_RefusesBeforeTheSessionIsTouched()
    {
        // contracts/cli.md's "refuses, before touching anything" pattern (the suppress-test
        // precedent): the directory ExecuteProbeRemodel would open its log in must not exist
        // afterwards, proving nothing past the acknowledgement check ran.
        string directory = Path.Combine(
            Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));

        int exit = Program.RunProbe(new[] { "probe", "remodel", "--out", directory });

        Assert.Equal(1, exit);
        Assert.False(Directory.Exists(directory));
        Assert.Contains(
            "--acknowledge-throwaway-part",
            RemodelProbe.AcknowledgementRequiredMessage,
            StringComparison.Ordinal);
    }

    [Fact]
    public void RemodelProbe_BuildsItsGateWithTheRemodelProbeGuard()
    {
        // A separate guard from RemodelGuard on purpose: the probe builds a throwaway part and
        // needs the feature-creation family RemodelGuard refuses outright
        // (contracts/guard-allowlist.md), but nothing else the read-only guard denies.
        var observer = new RecordingGateObserver();
        SwGate gate = Program.RemodelProbeGate(observer);

        Assert.True(gate.Call("FeatureExtrusion3", () => true));
        Assert.True(gate.Call("FeatureCut4", () => true));
        Assert.True(gate.Call("InsertFeatureChamfer", () => true));
        Assert.True(gate.Call("InsertFeatureShell", () => true));
        Assert.True(gate.Call("InsertFeatureTreeFolder2", () => true));
        Assert.True(gate.Call("ForceRebuild3", () => true));
        Assert.True(gate.Call("SaveAs3", () => true));
        Assert.True(gate.Call(RemodelSystemToggles.ToggleMember, () => true));
        Assert.True(gate.Call(RemodelSystemToggles.CommandInProgressMember, () => true));

        // FeatureFillet3 needs no exemption: it is not on ReadOnlyGuard's denylist at all.
        Assert.True(gate.Call("FeatureFillet3", () => true));

        Assert.Throws<MutatingCallError>(() => gate.Call("Save3", () => true));
        Assert.Throws<MutatingCallError>(() => gate.Call("EditDelete", () => true));
        Assert.Throws<MutatingCallError>(() => gate.Call("SetSuppression2", () => true));
        Assert.Throws<MutatingCallError>(() => gate.Call("ForceRebuildAll", () => true));

        // A FeatureExtrusion* variant this probe never calls stays refused: the exemption is
        // an exact match on the calls the recipe actually makes, not a widened prefix.
        Assert.Throws<MutatingCallError>(() => gate.Call("FeatureExtrusion2", () => true));
    }

    // ---- --fasteners -------------------------------------------------------------

    [Theory]
    [InlineData("include", FastenerFolderTreatment.Include)]
    [InlineData("exclude", FastenerFolderTreatment.Exclude)]
    [InlineData("only", FastenerFolderTreatment.Only)]
    public void FastenerTreatment_ReadsTheOption(string value, FastenerFolderTreatment expected)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--fasteners", value }, 1, InterferenceOptions);

        Assert.Equal(expected, parsed.FastenerTreatment());
    }

    [Fact]
    public void FastenerTreatment_DefaultsToInclude()
    {
        Assert.Equal(
            FastenerFolderTreatment.Include,
            CommandLine.Parse(new[] { "interference" }, 1, InterferenceOptions).FastenerTreatment());
    }

    [Fact]
    public void FastenerTreatment_UnknownValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--fasteners", "some" }, 1, InterferenceOptions);

        Assert.Throws<UsageError>(() => parsed.FastenerTreatment());
    }

    // ---- --pairs -----------------------------------------------------------------

    [Fact]
    public void Pairs_AllMeansNoNamedPairs()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--pairs", "all" }, 1, InterferenceOptions);

        Assert.Empty(parsed.Pairs());
        Assert.False(parsed.HasNamedPairs());
    }

    [Fact]
    public void Pairs_AbsentMeansAll()
    {
        Assert.Empty(CommandLine.Parse(new[] { "interference" }, 1, InterferenceOptions).Pairs());
    }

    [Fact]
    public void Pairs_ReadsSeveralPairsOfComponentIds()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--pairs", "cmp:0001,cmp:0011", "cmp:0001,cmp:0012", "--out", @"C:\o" },
            1,
            InterferenceOptions);

        Assert.Equal(
            new[] { new[] { "cmp:0001", "cmp:0011" }, new[] { "cmp:0001", "cmp:0012" } },
            parsed.Pairs());

        // The option after the list is still parsed as an option, not swallowed by --pairs.
        Assert.Equal(@"C:\o", parsed.Value("out"));
        Assert.True(parsed.HasNamedPairs());
    }

    [Fact]
    public void Pairs_TrimsWhitespaceAroundIds()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--pairs", "cmp:0001, cmp:0011" }, 1, InterferenceOptions);

        Assert.Equal(new[] { "cmp:0001", "cmp:0011" }, Assert.Single(parsed.Pairs()));
    }

    [Theory]
    [InlineData("cmp:0001")]
    [InlineData("cmp:0001,cmp:0002,cmp:0003")]
    [InlineData("cmp:0001,")]
    [InlineData(",cmp:0002")]
    public void Pairs_MalformedPair_Throws(string value)
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--pairs", value }, 1, InterferenceOptions);

        Assert.Throws<UsageError>(() => parsed.Pairs());
    }

    [Fact]
    public void Pairs_AllMixedWithNamedPairs_Throws()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "interference", "--pairs", "all", "cmp:0001,cmp:0002" }, 1, InterferenceOptions);

        Assert.Throws<UsageError>(() => parsed.Pairs());
    }

    // ---- --view ------------------------------------------------------------------

    [Theory]
    [InlineData("iso")]
    [InlineData("front")]
    [InlineData("top")]
    [InlineData("right")]
    [InlineData("fit")]
    public void CaptureView_ReadsEveryContractValue(string value)
    {
        CommandLine parsed = CommandLine.Parse(new[] { "capture", "--view", value }, 1, CaptureOptions);

        Assert.Equal(value, parsed.CaptureView());
    }

    [Fact]
    public void CaptureView_DefaultsToFit()
    {
        Assert.Equal(
            CaptureViews.Fit,
            CommandLine.Parse(new[] { "capture" }, 1, CaptureOptions).CaptureView());
    }

    [Fact]
    public void CaptureView_UnknownValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "capture", "--view", "behind" }, 1, CaptureOptions);

        Assert.Throws<UsageError>(() => parsed.CaptureView());
    }

    // ---- --allow-start -----------------------------------------------------------

    [Fact]
    public void AllowStart_AbsentIsFalse()
    {
        // Attach-only is the default: without this flag the host must never reach
        // Activator.CreateInstance, because a second seat consumes a licence and describes
        // an empty session rather than the assembly on screen.
        Assert.False(
            CommandLine.Parse(new[] { "dump", "--out", @"C:\out" }, 1, DumpOptions)
                .Flag("allow-start"));
    }

    [Fact]
    public void AllowStart_BareSwitch_IsTrue()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--allow-start", "--out", @"C:\out" }, 1, DumpOptions);

        Assert.True(parsed.Flag("allow-start"));
        Assert.Equal(@"C:\out", parsed.Value("out"));
    }

    [Theory]
    [InlineData("dump")]
    [InlineData("resolve")]
    [InlineData("interference")]
    [InlineData("capture")]
    [InlineData("serve")]
    [InlineData("probe")]
    [InlineData("suppress-test")]
    public void AllowStart_IsAcceptedByEveryCommandThatAttaches(string command)
    {
        // Program.cs calls SwAttach.Connect from every command, so every one must accept the
        // flag; an option missing from one command's list is a usage error at run time.
        // This drives the shipped lists, so deleting Program.KnownOptions fails it.
        string[] known = KnownOptionsFor(command);

        Assert.Contains("allow-start", known);
        Assert.True(CommandLine.Parse(new[] { command, "--allow-start" }, 1, known).Flag("allow-start"));
    }

    private static string[] KnownOptionsFor(string command)
    {
        switch (command)
        {
            case "dump":
                return DumpOptions;
            case "resolve":
                return ResolveOptions;
            case "interference":
                return InterferenceOptions;
            case "capture":
                return CaptureOptions;
            case "serve":
                return ServeOptions;
            case "probe":
                return ProbeOptions;
            case "suppress-test":
                return SuppressTestOptions;
            default:
                throw new ArgumentOutOfRangeException(nameof(command), command, "No such command.");
        }
    }

    // ---- the multi-value change must not disturb the single-valued options --------

    [Fact]
    public void Values_SingleValuedOptionStillReadsAsBefore()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Equal(@"C:\out", parsed.Value("out"));
        Assert.Equal(new[] { @"C:\out" }, parsed.Values("out"));
        Assert.Equal(MeshFormat.Glb, parsed.MeshFormat());
    }

    [Fact]
    public void Values_AbsentOptionIsEmpty()
    {
        Assert.Empty(CommandLine.Parse(new[] { "dump" }, 1, DumpOptions).Values("out"));
    }

    [Fact]
    public void Has_SaysWhetherTheOptionAppeared()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--faces" }, 1, DumpOptions);

        Assert.True(parsed.Has("faces"));
        Assert.False(parsed.Has("out"));
    }
}
