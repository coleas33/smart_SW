using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.AddIn.Review;
using SwReview.AddIn.Terminal;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T061a. The first-launch tool listing check, against listings the CLIs really produce.
///
/// The check is a gate, not a warning (`contracts/cli-profiles.md`, "Verification on first
/// launch"): a CLI that quietly loaded a different toolset than the generated profile asked
/// for is exactly the failure the read-only guarantee exists to prevent, and a terminal that
/// started anyway would be an unrestricted CLI sitting in the Task Pane looking restricted.
/// So there are three things to prove, and they are the three the task names:
///
/// 1. an exact listing starts the session;
/// 2. a missing allowlisted tool blocks it, and the message names the tool;
/// 3. a tool outside both the MCP allowlist and the CLI's intended built-in set blocks it, and
///    the message names that tool.
///
/// The Codex fixtures are captured from codex-cli 0.115.0; the Gemini ones are hand-authored
/// from the documented `/mcp` output while that terminal is deferred. See
/// `Fixtures/ToolListing/README.md` - the provenance is the point, because a parser tested
/// only against listings we invented proves nothing about the CLI.
/// </summary>
public sealed class ToolListingCheckTests
{
    /// <summary>The contract's allowlist. Read off <see cref="CliProfileWriter"/> rather than
    /// retyped: the profile and the gate disagreeing is a gate that passes on a CLI the profile
    /// never restricted, so there is one list or there is no guarantee.</summary>
    private static IReadOnlyList<string> Allowlist => CliProfileWriter.EnabledTools;

    private static string FixturePath(string name) =>
        Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Fixtures", "ToolListing", name);

    private static string Fixture(string name) => File.ReadAllText(FixturePath(name));

    // ---------------------------------------------------------------- Codex, parsing

    [Fact]
    public void CodexListingYieldsEveryAllowlistedToolAndNothingElse()
    {
        ToolListing listing = ToolListing.FromCodex(Fixture("codex-startup-listing.json"));

        Assert.Equal(new[] { "swreview" }, listing.Servers);
        Assert.Equal(Allowlist.OrderBy(n => n, StringComparer.Ordinal), listing.Tools.OrderBy(n => n, StringComparer.Ordinal));
    }

    [Fact]
    public void CodexListingWithNoServersParsesAsEmptyRatherThanThrowing()
    {
        // A `config.toml` that never registered the server, or a server that failed to start:
        // an ordinary state of a workstation, and it has to become a blocked start with a
        // sentence on it, not an exception out of the parser.
        ToolListing listing = ToolListing.FromCodex("{\"data\": [], \"nextCursor\": null}");

        Assert.Empty(listing.Servers);
        Assert.Empty(listing.Tools);
    }

    [Fact]
    public void PagedCodexListingIsRefusedRatherThanCheckedHalfWay()
    {
        // `mcpServerStatus/list` pages. The tools on the pages nobody fetched are tools nobody
        // checked, so a first page is not a listing - it only looks like one.
        ToolListingFormatException error = Assert.Throws<ToolListingFormatException>(
            () => ToolListing.FromCodex(
                "{\"data\": [{\"name\": \"swreview\", \"tools\": {}}], \"nextCursor\": \"page-2\"}"));

        Assert.Contains("page-2", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void CodexListingThatIsNotJsonIsReportedAsUnreadable()
    {
        ToolListingFormatException error = Assert.Throws<ToolListingFormatException>(
            () => ToolListing.FromCodex("Error: config profile 'swreview' not found"));

        Assert.Contains("Codex", error.Message, StringComparison.Ordinal);
    }

    // ---------------------------------------------------------------- Codex, the gate

    [Fact]
    public void ExactCodexListingStartsTheSession()
    {
        ToolListingResult result = ToolListingCheck.ForCodex().Check(
            ToolListing.FromCodex(Fixture("codex-startup-listing.json")));

        Assert.True(result.Matches);
        Assert.Empty(result.Missing);
        Assert.Empty(result.Unexpected);
    }

    [Fact]
    public void CodexListingMissingAnAllowlistedToolBlocksTheStartAndNamesIt()
    {
        ToolListingResult result = ToolListingCheck.ForCodex().Check(
            ToolListing.FromCodex(Fixture("codex-startup-listing-missing-tool.json")));

        Assert.False(result.Matches);
        Assert.Equal(new[] { "list_mates" }, result.Missing);
        Assert.Empty(result.Unexpected);
        Assert.Contains("list_mates", result.Message, StringComparison.Ordinal);
        // The other eighteen were there; a message that named them too would bury the one
        // fact the engineer has to act on.
        Assert.DoesNotContain("bounding_box", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void CodexListingWithAToolOutsideBothListsBlocksTheStartAndNamesIt()
    {
        ToolListingResult result = ToolListingCheck.ForCodex().Check(
            ToolListing.FromCodex(Fixture("codex-startup-listing-extra-tool.json")));

        Assert.False(result.Matches);
        Assert.Empty(result.Missing);
        Assert.Equal(new[] { "write_file" }, result.Unexpected);
        Assert.Contains("write_file", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void CodexListingWithNoToolsAtAllNamesEveryMissingTool()
    {
        // The shape a profile that was ignored produces: the CLI came up, the server did not.
        ToolListingResult result = ToolListingCheck.ForCodex().Check(
            ToolListing.FromCodex("{\"data\": [], \"nextCursor\": null}"));

        Assert.False(result.Matches);
        Assert.Equal(Allowlist.Count, result.Missing.Count);
        foreach (string tool in Allowlist)
        {
            Assert.Contains(tool, result.Message, StringComparison.Ordinal);
        }
    }

    // ---------------------------------------------------------------- Gemini, parsing

    [Fact]
    public void GeminiTranscriptToolNamesAreComparedWithoutTheServerPrefix()
    {
        // The plan's "Gemini renames or truncates tool names" risk row. Gemini lists an MCP
        // tool as `mcp_<server>_<tool>`; a gate that compared that literally would report all
        // nineteen tools missing on a session that was in fact perfect, and an engineer who
        // saw that every time would learn to ignore the gate.
        ToolListing listing = ToolListing.FromGemini(Fixture("gemini-mcp-transcript.txt"));

        Assert.Equal(new[] { "swreview" }, listing.Servers);
        Assert.Equal(Allowlist.OrderBy(n => n, StringComparer.Ordinal), listing.Tools.OrderBy(n => n, StringComparer.Ordinal));
    }

    [Fact]
    public void GeminiTranscriptWithoutAToolsLineParsesAsEmptyRatherThanThrowing()
    {
        ToolListing listing = ToolListing.FromGemini(Fixture("gemini-mcp-transcript-disconnected.txt"));

        Assert.Equal(new[] { "swreview" }, listing.Servers);
        Assert.Empty(listing.Tools);
    }

    [Fact]
    public void GeminiTranscriptThatIsNotATranscriptIsReportedAsUnreadable()
    {
        ToolListingFormatException error = Assert.Throws<ToolListingFormatException>(
            () => ToolListing.FromGemini("Unknown command: /mcp"));

        Assert.Contains("Gemini", error.Message, StringComparison.Ordinal);
    }

    // ---------------------------------------------------------------- Gemini, the gate

    [Fact]
    public void ExactGeminiTranscriptStartsTheSession()
    {
        ToolListingResult result = ToolListingCheck.ForGemini().Check(
            ToolListing.FromGemini(Fixture("gemini-mcp-transcript.txt")));

        Assert.True(result.Matches);
        Assert.Empty(result.Missing);
        Assert.Empty(result.Unexpected);
    }

    [Fact]
    public void GeminiTranscriptMissingAnAllowlistedToolBlocksTheStartAndNamesIt()
    {
        ToolListingResult result = ToolListingCheck.ForGemini().Check(
            ToolListing.FromGemini(Fixture("gemini-mcp-transcript-missing-tool.txt")));

        Assert.False(result.Matches);
        Assert.Equal(new[] { "list_mates" }, result.Missing);
        Assert.Contains("list_mates", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void GeminiTranscriptWithAToolOutsideBothListsBlocksTheStartAndNamesIt()
    {
        ToolListingResult result = ToolListingCheck.ForGemini().Check(
            ToolListing.FromGemini(Fixture("gemini-mcp-transcript-extra-tool.txt")));

        Assert.False(result.Matches);
        Assert.Empty(result.Missing);
        Assert.Equal(new[] { "write_file" }, result.Unexpected);
        Assert.Contains("write_file", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void GeminiDisconnectedServerBlocksTheStartWithEveryToolMissing()
    {
        ToolListingResult result = ToolListingCheck.ForGemini().Check(
            ToolListing.FromGemini(Fixture("gemini-mcp-transcript-disconnected.txt")));

        Assert.False(result.Matches);
        Assert.Equal(Allowlist.Count, result.Missing.Count);
    }

    // ---------------------------------------------------------------- the two lists

    [Fact]
    public void AllowlistComesFromTheProfileWriterSoThereIsOnlyOneOfIt()
    {
        Assert.Same(CliProfileWriter.EnabledTools, ToolListingCheck.ForCodex().Allowlist);
        Assert.Same(CliProfileWriter.EnabledTools, ToolListingCheck.ForGemini().Allowlist);
    }

    [Fact]
    public void GeminiBuiltInsArePermittedWhenPresent()
    {
        // `contracts/cli-profiles.md`: the Gemini policy leaves `read_file` and
        // `list_directory` allowed, so a listing that shows them is not a difference. They are
        // permitted, never required - the documented `/mcp` output lists MCP servers only, so
        // requiring them would block every good session.
        ToolListingCheck check = ToolListingCheck.ForGemini();
        var listing = ToolListing.FromNames(
            new[] { "swreview" }, Allowlist.Concat(new[] { "read_file", "list_directory" }));

        ToolListingResult result = check.Check(listing);

        Assert.True(result.Matches);
    }

    [Fact]
    public void CodexBuiltInApplyPatchIsPermittedWhenPresent()
    {
        // `apply_patch` cannot be disabled and the read-only sandbox refuses its writes
        // (`contracts/cli-profiles.md`, accepted risk), so its presence is not a difference.
        ToolListingCheck check = ToolListingCheck.ForCodex();
        var listing = ToolListing.FromNames(
            new[] { "swreview" }, Allowlist.Concat(new[] { "apply_patch" }));

        Assert.True(check.Check(listing).Matches);
    }

    [Fact]
    public void CodexShellIsNotABuiltInTheProfileIntendsToLeaveEnabled()
    {
        // Decision 2026-09-13, carried in the generated config as `features.shell_tool = false`:
        // general chat gets MCP tools only. A Codex that listed a shell tool anyway is a
        // profile that was not applied, which is the whole reason for the gate.
        ToolListingCheck check = ToolListingCheck.ForCodex();
        var listing = ToolListing.FromNames(new[] { "swreview" }, Allowlist.Concat(new[] { "shell" }));

        ToolListingResult result = check.Check(listing);

        Assert.False(result.Matches);
        Assert.Equal(new[] { "shell" }, result.Unexpected);
    }

    [Fact]
    public void BothDifferencesAreReportedTogether()
    {
        ToolListingCheck check = ToolListingCheck.ForCodex();
        var listing = ToolListing.FromNames(
            new[] { "swreview" },
            Allowlist.Where(n => n != "list_gaps").Concat(new[] { "write_file" }));

        ToolListingResult result = check.Check(listing);

        Assert.False(result.Matches);
        Assert.Equal(new[] { "list_gaps" }, result.Missing);
        Assert.Equal(new[] { "write_file" }, result.Unexpected);
        Assert.Contains("list_gaps", result.Message, StringComparison.Ordinal);
        Assert.Contains("write_file", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void TheMessageNamesTheCliSoTheTerminalTabCanShowItUnchanged()
    {
        string codex = ToolListingCheck.ForCodex()
            .Check(ToolListing.FromCodex(Fixture("codex-startup-listing-extra-tool.json"))).Message;
        string gemini = ToolListingCheck.ForGemini()
            .Check(ToolListing.FromGemini(Fixture("gemini-mcp-transcript-extra-tool.txt"))).Message;

        Assert.Contains("Codex CLI", codex, StringComparison.Ordinal);
        Assert.Contains("Gemini CLI", gemini, StringComparison.Ordinal);
    }

    [Fact]
    public void AMatchingResultHasNothingToSay()
    {
        ToolListingResult result = ToolListingCheck.ForCodex().Check(
            ToolListing.FromCodex(Fixture("codex-startup-listing.json")));

        Assert.Equal(string.Empty, result.Message);
    }

    // ---------------------------------------------------------------- the gate in the session

    [Fact]
    public void SessionRefusesToStartWhenTheListingDiffers()
    {
        // T062. The point of putting it here rather than in the caller: there is no path to a
        // running pseudo-console that skips it, so a mismatch cannot become a terminal.
        var channel = new NullChannel();
        var options = new TerminalSessionOptions(
            CmdLaunch(),
            channel,
            ToolListingGate.ForCodex(() => Fixture("codex-startup-listing-extra-tool.json")));

        ToolListingException error = Assert.Throws<ToolListingException>(
            () => TerminalSession.Start(options));

        Assert.False(error.Result.Matches);
        Assert.Contains("write_file", error.Message, StringComparison.Ordinal);
        // Nothing was started: a refused gate that had already spawned the CLI would have let
        // the unrestricted process exist, which is the thing being prevented.
        Assert.Empty(channel.Messages);
    }

    [Fact]
    public void SessionStartsWhenTheListingMatches()
    {
        var channel = new NullChannel();
        var options = new TerminalSessionOptions(
            CmdLaunch(),
            channel,
            ToolListingGate.ForCodex(() => Fixture("codex-startup-listing.json")));

        using (TerminalSession session = TerminalSession.Start(options))
        {
            Assert.True(session.ProcessId > 0);
            session.Stop();
        }
    }

    [Fact]
    public void SessionRefusesToStartWhenTheListingCannotBeProduced()
    {
        // The probe itself failing - the CLI would not run, the listing timed out - is a
        // difference like any other, because what it means is that nobody checked.
        var channel = new NullChannel();
        var options = new TerminalSessionOptions(
            CmdLaunch(),
            channel,
            ToolListingGate.ForCodex(() => throw new IOException("the listing probe timed out")));

        ToolListingException error = Assert.Throws<ToolListingException>(
            () => TerminalSession.Start(options));

        Assert.Contains("the listing probe timed out", error.Message, StringComparison.Ordinal);
        Assert.Empty(channel.Messages);
    }

    [Fact]
    public void SessionRefusesToStartWhenTheListingIsUnreadable()
    {
        var channel = new NullChannel();
        var options = new TerminalSessionOptions(
            CmdLaunch(), channel, ToolListingGate.ForCodex(() => "not a listing at all"));

        Assert.Throws<ToolListingException>(() => TerminalSession.Start(options));
        Assert.Empty(channel.Messages);
    }

    /// <summary>
    /// A session cannot be described without saying which gate it runs under.
    ///
    /// The gate used to be a nullable property with a `?.Verify()` behind it, which made
    /// starting a CLI with no check at all a single forgotten line in a caller - and one that no
    /// test could have failed on, because a missing gate looked exactly like every other
    /// unset option. Requiring it in the constructor turns that omission into a build error.
    /// </summary>
    [Fact]
    public void ASessionCannotBeDescribedWithoutAGate()
    {
        ArgumentNullException missing = Assert.Throws<ArgumentNullException>(
            () => new TerminalSessionOptions(CmdLaunch(), new NullChannel(), null!));

        Assert.Contains("NotACli", missing.Message, StringComparison.Ordinal);
    }

    /// <summary>
    /// The one opt-out, and it has to be named. `cmd.exe` is not a CLI, has no MCP server and
    /// has nothing to list; the ConPTY tests start it to prove the pseudo-console works at all.
    /// </summary>
    [Fact]
    public void TheNamedOptOutChecksNothingAndStarts()
    {
        Assert.Null(ToolListingGate.NotACli.Check);
        Assert.True(ToolListingGate.NotACli.Verify().Matches);

        var channel = new NullChannel();
        using (TerminalSession session = TerminalSession.Start(
            new TerminalSessionOptions(CmdLaunch(), channel, ToolListingGate.NotACli)))
        {
            Assert.True(session.ProcessId > 0);
            session.Stop();
        }
    }

    private static CliLaunch CmdLaunch() => CliLaunch.ForExecutable(
        Path.Combine(Environment.SystemDirectory, "cmd.exe"), "/c", "exit");

    private sealed class NullChannel : IPageChannel
    {
        private readonly List<string> _messages = new List<string>();

        public IReadOnlyList<string> Messages
        {
            get
            {
                lock (_messages)
                {
                    return _messages.ToList();
                }
            }
        }

        public void PostMessage(string json)
        {
            lock (_messages)
            {
                _messages.Add(json);
            }
        }
    }
}
