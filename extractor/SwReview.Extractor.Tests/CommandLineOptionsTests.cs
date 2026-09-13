using System;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Console;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
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
    public void AllowStart_IsAcceptedByEveryCommandThatAttaches(string command)
    {
        // Program.cs calls SwAttach.Connect from all five commands, so all five must accept
        // the flag; an option missing from one command's list is a usage error at run time.
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
