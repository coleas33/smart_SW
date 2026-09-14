using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace SwReview.AddIn.Terminal;

/// <summary>
/// A CLI's tool listing could not be read at all - it was not JSON, or not a transcript.
///
/// Separate from <see cref="ToolListingException"/> because the two say different things to the
/// engineer: one is "the CLI loaded the wrong tools", the other is "whatever the CLI printed,
/// this is not a tool listing". Both refuse the start, and that is deliberate: an unreadable
/// listing means nobody checked, which is indistinguishable from a check that failed.
/// </summary>
public sealed class ToolListingFormatException : Exception
{
    public ToolListingFormatException(string message)
        : base(message)
    {
    }

    public ToolListingFormatException(string message, Exception inner)
        : base(message, inner)
    {
    }
}

/// <summary>The start was refused by the first-launch tool listing check (T062).</summary>
public sealed class ToolListingException : Exception
{
    public ToolListingException(ToolListingResult result)
        : base((result ?? throw new ArgumentNullException(nameof(result))).Message)
    {
        Result = result;
    }

    public ToolListingException(ToolListingResult result, Exception inner)
        : base((result ?? throw new ArgumentNullException(nameof(result))).Message, inner)
    {
        Result = result;
    }

    /// <summary>The difference, for the Terminal tab. Safe to show: it is tool names and the
    /// CLI's display name, nothing from a model and nothing from a secret.</summary>
    public ToolListingResult Result { get; }
}

/// <summary>
/// What one CLI said it had loaded: the MCP servers it connected to, and the tool names it took
/// from them, with the CLI's own prefixing undone.
///
/// The un-prefixing is the whole reason this is a type rather than a `string[]`. Gemini lists an
/// MCP tool as `mcp_&lt;server&gt;_&lt;tool&gt;` (`docs/tools/mcp-server.md`); Codex lists it bare.
/// A check that compared either spelling literally against `contracts/mcp-toolset.md` would be
/// wrong for one of the two CLIs, and wrong in the worst direction for Gemini - every tool
/// reported missing on a session that was in fact perfect, which is how an engineer learns to
/// click past the gate. It is the plan's "Gemini renames or truncates tool names" risk row, and
/// the prefixes are stripped using the server names out of the listing itself rather than a
/// hard-coded one, so a renamed server cannot silently turn the stripping off.
/// </summary>
public sealed class ToolListing
{
    private static readonly Regex GeminiServerLine = new Regex(
        @"^(?:(?<icon>\S+)\s+)?(?<name>[^\s()]+)\s+\((?<state>[A-Za-z_]+)\)\s*$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly Regex GeminiToolsLine = new Regex(
        @"^\s+Tools:\s*(?<list>.*)$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private ToolListing(IReadOnlyList<string> servers, IReadOnlyList<string> tools)
    {
        Servers = servers;
        Tools = tools;
    }

    /// <summary>The MCP servers the listing named, in the order it named them.</summary>
    public IReadOnlyList<string> Servers { get; }

    /// <summary>Every tool name, un-prefixed and de-duplicated, in the order first seen.</summary>
    public IReadOnlyList<string> Tools { get; }

    /// <summary>A listing assembled from names that are already known - the wiring that has a
    /// listing by some other route, and the tests.</summary>
    public static ToolListing FromNames(IEnumerable<string> servers, IEnumerable<string> tools)
    {
        if (servers == null)
        {
            throw new ArgumentNullException(nameof(servers));
        }

        if (tools == null)
        {
            throw new ArgumentNullException(nameof(tools));
        }

        List<string> serverNames = Distinct(servers);
        return new ToolListing(serverNames, Distinct(tools.Select(tool => Unprefix(tool, serverNames))));
    }

    /// <summary>
    /// Codex's startup tool listing: the `result` of an app-server `mcpServerStatus/list` reply
    /// (`Fixtures/ToolListing/README.md` records how one is captured).
    ///
    /// That request is used rather than `codex mcp list`/`codex mcp get`, which only echo
    /// `config.toml` back without ever starting the server - a gate built on those would pass
    /// happily on a CLI whose MCP server never came up, which is the failure it exists to catch.
    /// </summary>
    public static ToolListing FromCodex(string listing)
    {
        if (listing == null)
        {
            throw new ArgumentNullException(nameof(listing));
        }

        JsonElement root;
        try
        {
            using (JsonDocument document = JsonDocument.Parse(listing))
            {
                root = document.RootElement.Clone();
            }
        }
        catch (JsonException error)
        {
            throw new ToolListingFormatException(
                "the Codex CLI tool listing could not be read: it is not the JSON of an "
                + $"`mcpServerStatus/list` reply ({error.Message}). What the CLI printed instead "
                + "is usually the reason the terminal cannot start.", error);
        }

        if (root.ValueKind != JsonValueKind.Object
            || !root.TryGetProperty("data", out JsonElement data)
            || data.ValueKind != JsonValueKind.Array)
        {
            throw new ToolListingFormatException(
                "the Codex CLI tool listing is JSON but has no `data` array, so it is not an "
                + "`mcpServerStatus/list` reply.");
        }

        // A cursor means the reply was one page of the servers, and the tools on the pages
        // nobody fetched are tools nobody checked. Refusing is the only honest answer.
        if (root.TryGetProperty("nextCursor", out JsonElement cursor)
            && cursor.ValueKind == JsonValueKind.String)
        {
            throw new ToolListingFormatException(
                "the Codex CLI tool listing is only the first page of the MCP servers "
                + $"(nextCursor '{cursor.GetString()}'), so it cannot be checked. Fetch the "
                + "remaining pages and check the whole listing.");
        }

        var servers = new List<string>();
        var tools = new List<string>();
        foreach (JsonElement server in data.EnumerateArray())
        {
            if (server.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            if (server.TryGetProperty("name", out JsonElement name)
                && name.ValueKind == JsonValueKind.String)
            {
                servers.Add(name.GetString() ?? string.Empty);
            }

            if (server.TryGetProperty("tools", out JsonElement toolMap)
                && toolMap.ValueKind == JsonValueKind.Object)
            {
                // The map is keyed by tool name; the value repeats it in `name`. The key is
                // taken, because that is what Codex dispatches on.
                foreach (JsonProperty tool in toolMap.EnumerateObject())
                {
                    tools.Add(tool.Name);
                }
            }
        }

        List<string> serverNames = Distinct(servers);
        return new ToolListing(serverNames, Distinct(tools.Select(tool => Unprefix(tool, serverNames))));
    }

    /// <summary>
    /// Gemini's `/mcp` transcript, in the shape `docs/tools/mcp-server.md` documents: an
    /// `MCP Servers Status:` header, one `&lt;icon&gt; &lt;server&gt; (&lt;STATE&gt;)` line per
    /// server, indented `Command:` / `Working Directory:` / `Timeout:` / `Tools:` lines under
    /// each, and a closing `Discovery State:`.
    ///
    /// A server that is not connected simply has no `Tools:` line, which becomes every one of
    /// its tools missing and a refused start - the same outcome as a connected server that lost
    /// a tool, reached without a second code path to get it wrong.
    /// </summary>
    public static ToolListing FromGemini(string transcript)
    {
        if (transcript == null)
        {
            throw new ArgumentNullException(nameof(transcript));
        }

        if (transcript.IndexOf("MCP Servers Status:", StringComparison.Ordinal) < 0)
        {
            throw new ToolListingFormatException(
                "the Gemini CLI tool listing could not be read: it does not start with "
                + "'MCP Servers Status:', so it is not the output of `/mcp`.");
        }

        var servers = new List<string>();
        var tools = new List<string>();
        foreach (string line in transcript.Split('\n'))
        {
            string text = line.TrimEnd('\r');
            if (text.Length == 0)
            {
                continue;
            }

            Match toolsLine = GeminiToolsLine.Match(text);
            if (toolsLine.Success)
            {
                tools.AddRange(toolsLine.Groups["list"].Value
                    .Split(',')
                    .Select(name => name.Trim())
                    .Where(name => name.Length > 0));
                continue;
            }

            // Server lines are the unindented ones; an indented `Error: ... (whatever)` must
            // not be mistaken for one.
            if (char.IsWhiteSpace(text[0]))
            {
                continue;
            }

            Match serverLine = GeminiServerLine.Match(text);
            if (serverLine.Success)
            {
                servers.Add(serverLine.Groups["name"].Value);
            }
        }

        List<string> serverNames = Distinct(servers);
        return new ToolListing(serverNames, Distinct(tools.Select(tool => Unprefix(tool, serverNames))));
    }

    /// <summary>Strips the `mcp_&lt;server&gt;_` prefix Gemini gives an MCP tool. Names that
    /// already are bare, as Codex lists them, come back unchanged.</summary>
    private static string Unprefix(string tool, IReadOnlyList<string> servers)
    {
        string name = (tool ?? string.Empty).Trim();
        foreach (string server in servers)
        {
            if (server.Length == 0)
            {
                continue;
            }

            string prefix = "mcp_" + server + "_";
            if (name.Length > prefix.Length
                && name.StartsWith(prefix, StringComparison.Ordinal))
            {
                return name.Substring(prefix.Length);
            }
        }

        return name;
    }

    private static List<string> Distinct(IEnumerable<string> names)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var ordered = new List<string>();
        foreach (string name in names)
        {
            string trimmed = (name ?? string.Empty).Trim();
            if (trimmed.Length > 0 && seen.Add(trimmed))
            {
                ordered.Add(trimmed);
            }
        }

        return ordered;
    }
}

/// <summary>The difference between what a CLI loaded and what the generated profile asked for.</summary>
public sealed class ToolListingResult
{
    internal ToolListingResult(
        IReadOnlyList<string> missing, IReadOnlyList<string> unexpected, string message)
    {
        Missing = missing;
        Unexpected = unexpected;
        Message = message;
    }

    /// <summary>Allowlisted tools the CLI did not load. Any of these and the terminal does not
    /// start: a CLI missing `list_interferences` is a CLI whose answers quietly stop covering
    /// interferences.</summary>
    public IReadOnlyList<string> Missing { get; }

    /// <summary>Tools in neither the allowlist nor the CLI's intended built-in set. Any of these
    /// and the terminal does not start: it is the profile not having been applied.</summary>
    public IReadOnlyList<string> Unexpected { get; }

    /// <summary>What the Terminal tab shows, or empty when there is nothing to show.</summary>
    public string Message { get; }

    /// <summary>
    /// Whether the terminal may start.
    ///
    /// The message is part of the condition, not decoration on top of it. A listing that could
    /// not be produced or could not be read has nothing to put in
    /// <see cref="Missing"/> or <see cref="Unexpected"/> and must still refuse, so "no
    /// differences" alone would be a result that says start when the honest answer is that
    /// nobody checked.
    /// </summary>
    public bool Matches => Missing.Count == 0 && Unexpected.Count == 0 && Message.Length == 0;
}

/// <summary>
/// T062. The first-launch tool listing check: the gate that compares what a CLI actually loaded
/// with the two lists `contracts/cli-profiles.md` allows it, and refuses the start on any
/// difference.
///
/// It is a gate and not a warning, and the contract says why in one sentence: falling back to an
/// unrestricted CLI is the failure the read-only guarantee exists to prevent. A warning on a
/// Task Pane is a thing an engineer dismisses at eleven at night; a refused start is not.
///
/// The two lists are asymmetric, and the asymmetry is load-bearing:
///
/// <b>The MCP allowlist is required.</b> Every tool in `enabled_tools` has to be there. A
/// missing one means the generated profile and the running server disagree, and the engineer
/// would find out by getting an answer that quietly omitted whatever that tool covers.
///
/// <b>The built-in set is permitted, not required.</b> Neither CLI's listing includes its own
/// built-in tools - Codex's `mcpServerStatus/list` and Gemini's `/mcp` both report MCP servers
/// only - so requiring them would refuse every good session. Naming them is what keeps the
/// second rule honest: anything that is in neither list is a tool nobody sanctioned.
/// </summary>
public sealed class ToolListingCheck
{
    /// <summary>
    /// Codex's built-ins the profile intends to leave enabled.
    ///
    /// `apply_patch` alone. `contracts/cli-profiles.md` says it "cannot be disabled; the
    /// read-only sandbox refuses its writes (accepted risk)", so a listing that shows it is not
    /// evidence of anything wrong. The contract's "Verification on first launch" paragraph also
    /// names the read-only shell, and that half is stale: the same file's generated config sets
    /// `features.shell_tool = false` under the 2026-09-13 decision that general chat gets MCP
    /// tools only. A Codex that offered a shell anyway would be a Codex that did not read the
    /// generated profile, which is precisely what this gate is for, so `shell` is deliberately
    /// not sanctioned here.
    /// </summary>
    public static readonly IReadOnlyList<string> CodexBuiltIns = new[] { "apply_patch" };

    /// <summary>Gemini's built-ins the policy file leaves allowed
    /// (`contracts/cli-profiles.md`: the two `decision = "allow"` rules beside the deny-all).</summary>
    public static readonly IReadOnlyList<string> GeminiBuiltIns = new[] { "read_file", "list_directory" };

    private readonly string _displayName;

    /// <param name="displayName">What the engineer calls this CLI. Every message starts with it,
    /// because a pane with two CLI choices has to say which one it refused.</param>
    /// <param name="allowlist">The MCP `enabled_tools` allowlist. Required, all of it.</param>
    /// <param name="builtIns">The CLI's own tools the profile intends to leave enabled.
    /// Permitted, none of them required.</param>
    public ToolListingCheck(
        string displayName, IReadOnlyList<string> allowlist, IReadOnlyList<string> builtIns)
    {
        if (string.IsNullOrWhiteSpace(displayName))
        {
            throw new ArgumentException("a CLI display name is required", nameof(displayName));
        }

        _displayName = displayName;
        Allowlist = allowlist ?? throw new ArgumentNullException(nameof(allowlist));
        BuiltIns = builtIns ?? throw new ArgumentNullException(nameof(builtIns));
    }

    /// <summary>The MCP toolset the profile allows. The same object
    /// <see cref="CliProfileWriter.EnabledTools"/> writes into the profile: a gate holding its
    /// own copy would be a gate that still passed after the allowlist changed.</summary>
    public IReadOnlyList<string> Allowlist { get; }

    /// <summary>The CLI's own tools that are allowed to appear.</summary>
    public IReadOnlyList<string> BuiltIns { get; }

    public static ToolListingCheck ForCodex() => new ToolListingCheck(
        CliLocator.Definition("codex").DisplayName, CliProfileWriter.EnabledTools, CodexBuiltIns);

    public static ToolListingCheck ForGemini() => new ToolListingCheck(
        CliLocator.Definition("gemini").DisplayName, CliProfileWriter.EnabledTools, GeminiBuiltIns);

    public ToolListingResult Check(ToolListing listing)
    {
        if (listing == null)
        {
            throw new ArgumentNullException(nameof(listing));
        }

        var loaded = new HashSet<string>(listing.Tools, StringComparer.Ordinal);
        var sanctioned = new HashSet<string>(Allowlist, StringComparer.Ordinal);
        sanctioned.UnionWith(BuiltIns);

        // Reported in the contract's order rather than sorted: that is the order the engineer
        // reads the allowlist in, in the file they will open next.
        List<string> missing = Allowlist.Where(tool => !loaded.Contains(tool)).ToList();
        List<string> unexpected = listing.Tools.Where(tool => !sanctioned.Contains(tool)).ToList();

        return new ToolListingResult(missing, unexpected, Describe(missing, unexpected));
    }

    private string Describe(IReadOnlyList<string> missing, IReadOnlyList<string> unexpected)
    {
        if (missing.Count == 0 && unexpected.Count == 0)
        {
            return string.Empty;
        }

        var text = new StringBuilder();
        text.Append(_displayName)
            .Append(" started with a different toolset than the generated profile asks for, so ")
            .Append("the terminal was not started.");

        if (missing.Count > 0)
        {
            text.Append(Environment.NewLine)
                .Append("Missing from the ")
                .Append(CliProfileWriter.ProfileName)
                .Append(" MCP server: ")
                .Append(string.Join(", ", missing.ToArray()));
        }

        if (unexpected.Count > 0)
        {
            text.Append(Environment.NewLine)
                .Append("Not in the profile's allowlist or in ")
                .Append(_displayName)
                .Append("'s intended built-in tools: ")
                .Append(string.Join(", ", unexpected.ToArray()));
        }

        text.Append(Environment.NewLine)
            .Append("A terminal that started anyway would be an unrestricted CLI, so this is ")
            .Append("refused rather than warned about. Check that the generated profile under ")
            .Append(CliProfileWriter.ProfileFolderName)
            .Append(" is the one the CLI read.");

        return text.ToString();
    }
}

/// <summary>
/// The check plus the way to get the listing it checks - what a <see cref="TerminalSession"/> is
/// handed so that it can run the gate without knowing how a particular CLI is asked what it
/// loaded (Codex answers over its app-server protocol; Gemini would answer a `/mcp` typed into
/// the session).
/// </summary>
public sealed class ToolListingGate
{
    private readonly Func<string, ToolListing>? _parse;
    private readonly Func<string>? _probe;

    /// <summary>The <see cref="NotACli"/> sentinel: a gate with nothing to gate.</summary>
    private ToolListingGate()
    {
        Check = null;
        _parse = null;
        _probe = null;
    }

    /// <param name="check">The two lists this CLI is held to.</param>
    /// <param name="parse">Reads that CLI's listing format.</param>
    /// <param name="probe">Produces the listing text. Runs before the pseudo-console exists, so
    /// it may block; a probe that throws refuses the start, because what a failed probe means is
    /// that nobody checked.</param>
    public ToolListingGate(
        ToolListingCheck check, Func<string, ToolListing> parse, Func<string> probe)
    {
        Check = check ?? throw new ArgumentNullException(nameof(check));
        _parse = parse ?? throw new ArgumentNullException(nameof(parse));
        _probe = probe ?? throw new ArgumentNullException(nameof(probe));
    }

    /// <summary>The two lists this CLI is held to, or null for <see cref="NotACli"/>.</summary>
    public ToolListingCheck? Check { get; }

    /// <summary>
    /// The one gate that checks nothing, for a child that is not a CLI and has no MCP server:
    /// the `cmd.exe` children the ConPTY tests start to prove the pseudo-console, the read loop
    /// and the coalescing.
    ///
    /// It exists so that "no gate" has to be typed rather than defaulted.
    /// <see cref="TerminalSessionOptions"/> takes a gate as a constructor argument and refuses
    /// null, so the only way to start something unchecked is to name this, in a line a reviewer
    /// reads as the exception it is. A nullable property with a permissive default made the same
    /// thing an omission nobody could see - and what it omitted was the read-only guarantee.
    /// </summary>
    public static ToolListingGate NotACli { get; } = new ToolListingGate();

    public static ToolListingGate ForCodex(Func<string> probe) =>
        new ToolListingGate(ToolListingCheck.ForCodex(), ToolListing.FromCodex, probe);

    public static ToolListingGate ForGemini(Func<string> probe) =>
        new ToolListingGate(ToolListingCheck.ForGemini(), ToolListing.FromGemini, probe);

    /// <summary>Runs the probe and the comparison. Throws
    /// <see cref="ToolListingException"/> on any difference, on an unreadable listing and on a
    /// probe that failed.</summary>
    public ToolListingResult Verify()
    {
        if (Check == null || _probe == null || _parse == null)
        {
            // NotACli: there is no CLI, no MCP server and nothing to compare. An empty result
            // that matches, rather than a silent return, so a caller that logs what the gate
            // said gets the same shape either way.
            return new ToolListingResult(
                Array.Empty<string>(), Array.Empty<string>(), string.Empty);
        }

        string listing;
        try
        {
            listing = _probe();
        }
        catch (ToolListingException)
        {
            throw;
        }
        catch (Exception error)
        {
            throw new ToolListingException(Refusal(error.Message), error);
        }

        ToolListing parsed;
        try
        {
            parsed = _parse(listing);
        }
        catch (ToolListingFormatException error)
        {
            throw new ToolListingException(Refusal(error.Message), error);
        }

        ToolListingResult result = Check.Check(parsed);
        if (!result.Matches)
        {
            throw new ToolListingException(result);
        }

        return result;
    }

    /// <summary>A refusal that is not a tool difference: there is nothing to list as missing or
    /// unexpected, only a reason the check could not be made.</summary>
    private ToolListingResult Refusal(string reason) => new ToolListingResult(
        Array.Empty<string>(),
        Array.Empty<string>(),
        "the terminal was not started because its toolset could not be checked: " + reason);
}
