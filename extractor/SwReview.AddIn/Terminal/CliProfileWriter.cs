using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.ToolService;

namespace SwReview.AddIn.Terminal;

/// <summary>
/// A generated CLI profile could not be produced, and the terminal must not start.
///
/// Every one of these is something the engineer can act on - sign in, install uv, open a
/// document - so the message is written for the Terminal tab, not for a log.
/// </summary>
public sealed class CliProfileException : Exception
{
    public CliProfileException(string message)
        : base(message)
    {
    }

    public CliProfileException(string message, Exception inner)
        : base(message, inner)
    {
    }
}

/// <summary>
/// How the generated profile starts `swreview mcp` (`contracts/cli-profiles.md`, "MCP server
/// command").
///
/// There is one correct spelling per kind of program the `python` setting can name, and the
/// contract tabulates them because the wrong one fails invisibly: the MCP server speaks on
/// stdio, so a server that will not start produces no message the engineer ever sees - only a
/// CLI with no `swreview` tools, which the first-launch tool listing check (T062) then refuses
/// to start on. `-m swreview.mcp` is the spelling that looks right and is not: the package has
/// no `swreview/mcp/__main__.py`.
/// </summary>
public sealed class McpServerCommand
{
    private const string Uv = "uv";
    private const string Python = "python";
    private const string ConsoleScript = "swreview";

    private McpServerCommand(string command, IReadOnlyList<string> argumentPrefix)
    {
        Command = command;
        ArgumentPrefix = argumentPrefix;
    }

    /// <summary>The program the CLI spawns for the MCP server.</summary>
    public string Command { get; }

    /// <summary>What comes before `--run-dir`: everything that gets from
    /// <see cref="Command"/> to the `mcp` subcommand.</summary>
    public IReadOnlyList<string> ArgumentPrefix { get; }

    /// <summary>Resolves from the settings file, the repository layout and PATH.</summary>
    public static McpServerCommand Resolve(UserSettings settings)
    {
        if (settings == null)
        {
            throw new ArgumentNullException(nameof(settings));
        }

        return Resolve(
            settings.Python, BackendLocator.FindReviewerProject(), BackendLocator.FindOnPath);
    }

    /// <param name="pythonSetting">The settings file's `python` field; null or blank to search.</param>
    /// <param name="reviewerProject">The reviewer project `uv run --project` is pointed at.</param>
    /// <param name="onPath">Looks one executable name up on PATH; injected for the tests.</param>
    public static McpServerCommand Resolve(
        string? pythonSetting, string? reviewerProject, Func<string, string?> onPath)
    {
        if (onPath == null)
        {
            throw new ArgumentNullException(nameof(onPath));
        }

        string? tool = string.IsNullOrWhiteSpace(pythonSetting) ? null : pythonSetting!.Trim();
        if (tool == null)
        {
            // uv first: it resolves the reviewer project's own environment with nothing
            // activated, which is the pilot layout (quickstart.md). A bare `python` on PATH is
            // whichever one the workstation installed first and need not have the package.
            tool = onPath(Uv) ?? onPath(Python);
            if (tool == null)
            {
                throw new CliProfileException(
                    "the general-chat tool server could not be located: neither 'uv' nor "
                    + "'python' is on PATH. Install uv, or set the `python` field in "
                    + @"%APPDATA%\SwReview\settings.json to uv.exe or to the python.exe of the "
                    + "environment that has the reviewer package installed.");
            }
        }
        else if (!File.Exists(tool))
        {
            throw new CliProfileException(
                $"the `python` setting names '{tool}', which does not exist. Point it at "
                + "uv.exe or at the python.exe of the environment that has the reviewer "
                + "package installed - or clear it to search PATH.");
        }

        string name = Path.GetFileNameWithoutExtension(tool) ?? string.Empty;

        if (string.Equals(name, Uv, StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(reviewerProject))
            {
                throw new CliProfileException(
                    $"'{tool}' is uv, but the reviewer project could not be found next to the "
                    + "add-in, so there is nothing for `uv run --project` to point at. Set the "
                    + @"`python` field in %APPDATA%\SwReview\settings.json to the python.exe of "
                    + "the environment that has the reviewer package installed.");
            }

            return new McpServerCommand(
                tool,
                new[] { "run", "--project", reviewerProject!, ConsoleScript, "mcp" });
        }

        if (name.StartsWith(Python, StringComparison.OrdinalIgnoreCase))
        {
            // `-m swreview.cli`, never `-m swreview.mcp`: there is no `swreview.mcp.__main__`.
            return new McpServerCommand(tool, new[] { "-m", "swreview.cli", "mcp" });
        }

        if (string.Equals(name, ConsoleScript, StringComparison.OrdinalIgnoreCase))
        {
            // Not a row in the contract's table, but a value the `python` setting legitimately
            // takes (BackendLocator accepts it and says so in its own error text), and running
            // `swreview.exe -m swreview.cli mcp` would be nonsense.
            return new McpServerCommand(tool, new[] { "mcp" });
        }

        throw new CliProfileException(
            $"the `python` setting names '{tool}', which is neither uv.exe, a python.exe, nor "
            + "swreview.exe, so there is no way to know how to start the general-chat tool "
            + "server with it.");
    }
}

/// <summary>What one Codex launch was given: where the generated home is, what to pass, and
/// what the previous profile in that folder had been edited into.</summary>
public sealed class CodexProfile
{
    internal CodexProfile(
        string home,
        string configPath,
        string instructionsPath,
        string authPath,
        IReadOnlyList<string> arguments,
        IReadOnlyDictionary<string, string> environment,
        IReadOnlyList<string> warnings)
    {
        Home = home;
        ConfigPath = configPath;
        InstructionsPath = instructionsPath;
        AuthPath = authPath;
        Arguments = arguments;
        Environment = environment;
        Warnings = warnings;
    }

    /// <summary>`&lt;run_dir&gt;\.swreview-cli\codex-home` - the whole config home, not a folder
    /// the CLI happens to read one file from.</summary>
    public string Home { get; }

    public string ConfigPath { get; }

    public string InstructionsPath { get; }

    /// <summary>The copy of the engineer's `auth.json` inside <see cref="Home"/>.</summary>
    public string AuthPath { get; }

    /// <summary>Everything after the CLI image, in order (`contracts/cli-profiles.md`).</summary>
    public IReadOnlyList<string> Arguments { get; }

    /// <summary>Added to the child's environment. `CODEX_HOME` and nothing else: the bridge
    /// secret reaches the MCP server through the generated config's own env block, one process
    /// further down, and never through the CLI's.</summary>
    public IReadOnlyDictionary<string, string> Environment { get; }

    /// <summary>Restriction keys the previous profile in this folder had lost or changed, for
    /// the Terminal tab. Empty is the normal case.</summary>
    public IReadOnlyList<string> Warnings { get; }
}

/// <summary>
/// T057. Writes the generated Codex config home under the run folder and returns the launch
/// that uses it.
///
/// Three things about this are load-bearing, and all three are in `contracts/cli-profiles.md`:
///
/// <b>The generated home is the config home.</b> Codex resolves `--profile swreview` against
/// `$CODEX_HOME/config.toml` and has no flag that points it at an arbitrary file, so a TOML
/// file merely sitting in the run folder is never read and `-c` overrides cannot register an
/// MCP server table. The launch therefore sets `CODEX_HOME`, and the `-c` overrides are belt
/// and braces for the five scalar restriction keys only.
///
/// <b>The sign-in comes with it.</b> `CODEX_HOME` relocates `auth.json` too, so owning the
/// config home means owning the credential; the engineer's `%USERPROFILE%\.codex\auth.json` is
/// copied in at every launch, and its absence refuses the start rather than producing a
/// terminal that 401s on the first turn.
///
/// <b>The secret travels in an environment block.</b> The general-chat secret goes into
/// `[mcp_servers.swreview.env]` and is never an argument, because a command line is readable
/// by every process on the workstation (FR-015). It is read here through
/// <see cref="IToolServiceAccess"/>, which exposes the general-chat half only: the review
/// secret also authorizes `interference`, and the CLI can read its own generated profile.
///
/// The profile is regenerated on every start and overwrites edits. An engineer who loosened it
/// to get something done is told which restriction key was missing rather than silently having
/// it put back.
/// </summary>
public sealed class CliProfileWriter
{
    /// <summary>The profile Codex is launched with, and the MCP server's name - `swreview`,
    /// no underscores, because Gemini names tools `mcp_swreview_&lt;tool&gt;`.</summary>
    public const string ProfileName = "swreview";

    /// <summary>The variable the bridge secret is passed in, named on the command line and
    /// valued in the config's env block.</summary>
    public const string BridgeSecretVariable = "SWREVIEW_BRIDGE_SECRET";

    /// <summary>The variable that makes the generated home Codex's config home.</summary>
    public const string HomeVariable = "CODEX_HOME";

    /// <summary>The generated-profile folder under the run folder (`.gitignore`d).</summary>
    public const string ProfileFolderName = ".swreview-cli";

    public const string CodexHomeFolderName = "codex-home";

    public const string ConfigFileName = "config.toml";

    public const string InstructionsFileName = "codex-instructions.md";

    public const string AuthFileName = "auth.json";

    /// <summary>
    /// The read-only toolset the profile allows (`contracts/mcp-toolset.md`), in the contract's
    /// order. One list: the first-launch tool listing check (T062) compares the CLI's own
    /// listing against this, so a profile and a check that disagreed would be a gate that
    /// passes on a CLI the profile never restricted.
    /// </summary>
    public static readonly IReadOnlyList<string> EnabledTools = new[]
    {
        "get_package_summary",
        "list_components",
        "get_component",
        "find_components",
        "list_mates",
        "list_holes",
        "list_fasteners",
        "list_interferences",
        "get_drawing_sheet",
        "find_dimensions",
        "list_gaps",
        "get_exceptions",
        "measure_axis_distance",
        "measure_face_gap",
        "check_tool_envelope",
        "bounding_box",
        "request_capture",
        "bridge_capture",
        "bridge_measure",
    };

    private static readonly Lazy<string> Instructions = new Lazy<string>(ReadInstructions);

    private static readonly UTF8Encoding Utf8NoBom = new UTF8Encoding(false);

    /// <summary>
    /// The contract's config, verbatim, with the placeholders it defines plus one of ours for
    /// <see cref="EnabledTools"/>. Kept as the whole file rather than assembled from parts,
    /// because <c>CliProfileWriterTests</c> compares the result with this same block in
    /// `contracts/cli-profiles.md` byte for byte, and a template that is a copy of the contract
    /// is the only shape in which that comparison is worth making.
    /// </summary>
    private const string CodexConfigTemplate = @"# <run_dir>/.swreview-cli/codex-home/config.toml - the whole config, not a fragment.
# Top-level keys are the defaults; the profile repeats the restriction keys so they win
# whichever level Codex reads.
sandbox_mode = ""read-only""
approval_policy = ""never""
web_search = ""disabled""
model_instructions_file = ""<run_dir>/.swreview-cli/codex-home/codex-instructions.md""

[features]
shell_tool = false           # decision 2026-09-13: general chat gets MCP tools only, no shell

[windows]
sandbox = ""unelevated""       # native Windows sandbox; overrides any WSL routing in user config

[profiles.swreview]
sandbox_mode = ""read-only""
approval_policy = ""never""
web_search = ""disabled""
model_instructions_file = ""<run_dir>/.swreview-cli/codex-home/codex-instructions.md""

[mcp_servers.swreview]
command = ""<mcp-command>""
args = [<mcp-args-prefix>, ""--run-dir"", ""<run_dir>"", ""--bridge-pipe"", ""<pipe>"", ""--bridge-secret-env"", ""SWREVIEW_BRIDGE_SECRET""]
startup_timeout_sec = 30
tool_timeout_sec = 120
enabled_tools = [<enabled-tools>]

[mcp_servers.swreview.env]
SWREVIEW_BRIDGE_SECRET = ""<secret>""";

    private readonly IToolServiceAccess _toolService;
    private readonly McpServerCommand _mcp;
    private readonly string _authSource;

    /// <param name="toolService">The add-in's tool service access - the general-chat bridge and
    /// nothing wider (`SwReviewAddIn.ToolService`).</param>
    /// <param name="mcp">How to start `swreview mcp`.</param>
    /// <param name="codexAuthSource">The engineer's Codex credential; defaults to
    /// `%USERPROFILE%\.codex\auth.json`. Injected for the tests.</param>
    public CliProfileWriter(
        IToolServiceAccess toolService, McpServerCommand mcp, string? codexAuthSource = null)
    {
        _toolService = toolService ?? throw new ArgumentNullException(nameof(toolService));
        _mcp = mcp ?? throw new ArgumentNullException(nameof(mcp));
        _authSource = string.IsNullOrWhiteSpace(codexAuthSource)
            ? DefaultCodexAuthSource()
            : codexAuthSource!;
    }

    /// <summary>The persona Codex runs under. Codex <i>replaces</i> its system prompt with
    /// `model_instructions_file`, so this is the whole of what the assistant is told.</summary>
    public static string CodexInstructions => Instructions.Value;

    /// <summary>`%USERPROFILE%\.codex\auth.json` - where `codex login` leaves the sign-in.</summary>
    public static string DefaultCodexAuthSource() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex", AuthFileName);

    /// <summary>
    /// Writes `&lt;run_dir&gt;/.swreview-cli/codex-home/` and returns the launch for it.
    /// </summary>
    /// <param name="runDirectory">The terminal's working directory: an existing run folder.</param>
    /// <exception cref="CliProfileException">The tool service is not listening, the run folder
    /// is not there, the sign-in is not there, or the folder cannot be written.</exception>
    public CodexProfile WriteCodex(string runDirectory)
    {
        if (string.IsNullOrWhiteSpace(runDirectory))
        {
            throw new CliProfileException("a run folder is required to write the Codex profile.");
        }

        string runDir;
        try
        {
            runDir = Path.GetFullPath(runDirectory);
        }
        catch (Exception failure) when (failure is ArgumentException || failure is NotSupportedException
            || failure is PathTooLongException || failure is IOException)
        {
            throw new CliProfileException(
                $"'{runDirectory}' is not a usable run folder: {failure.Message}", failure);
        }

        if (!Directory.Exists(runDir))
        {
            throw new CliProfileException(
                $"the run folder '{runDir}' does not exist, so there is nowhere to write the "
                + "Codex profile.");
        }

        // Both checks before anything is created: a half-written config home is worse than
        // none, because the next launch compares its restriction keys against it.
        BridgeConfig bridge = _toolService.GeneralChatBridge
            ?? throw new CliProfileException(
                "the SwReview tool service is not listening yet, so the general chat has no "
                + "connection to SOLIDWORKS and no secret to be given. Open a document and try "
                + "again.");

        if (!File.Exists(_authSource))
        {
            throw new CliProfileException(
                $"the Codex sign-in '{_authSource}' is not there. The terminal runs Codex with "
                + "its own config home, which is where it looks for the credential too, so the "
                + "existing sign-in has to be copied in. Run `codex login` once in a normal "
                + "terminal, then start this one again.");
        }

        string home = Path.Combine(runDir, ProfileFolderName, CodexHomeFolderName);
        string configPath = Path.Combine(home, ConfigFileName);
        string instructionsPath = Path.Combine(home, InstructionsFileName);
        string authPath = Path.Combine(home, AuthFileName);

        IReadOnlyList<string> warnings;
        try
        {
            warnings = InspectPrevious(configPath);
            Directory.CreateDirectory(home);
            File.WriteAllText(configPath, BuildConfig(runDir, bridge), Utf8NoBom);
            File.WriteAllText(instructionsPath, CodexInstructions, Utf8NoBom);

            // Copied every launch, never linked: a re-login refreshes the token in the
            // engineer's own home, and a stale copy fails exactly like no copy at all.
            File.Copy(_authSource, authPath, overwrite: true);
        }
        catch (Exception failure) when (failure is IOException || failure is UnauthorizedAccessException)
        {
            throw new CliProfileException(
                $"the Codex profile under '{home}' could not be written: {failure.Message}",
                failure);
        }

        return new CodexProfile(
            home,
            configPath,
            instructionsPath,
            authPath,
            BuildArguments(PathText(runDir)),
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                { HomeVariable, PathText(home) },
            },
            warnings);
    }

    /// <summary>
    /// The complete, normative argument list from `contracts/cli-profiles.md`.
    ///
    /// The five `-c` overrides restate the five scalar restriction keys the generated config
    /// already carries, so a config that somehow did not win still cannot leave the CLI
    /// unrestricted. They stop there because `-c` cannot express the MCP server table,
    /// `enabled_tools` or `model_instructions_file`, which is why owning `CODEX_HOME` is not
    /// optional.
    /// </summary>
    private static IReadOnlyList<string> BuildArguments(string runDirText) => new[]
    {
        "--profile", ProfileName,
        "-c", "sandbox_mode=\"read-only\"",
        "-c", "approval_policy=\"never\"",
        "-c", "web_search=\"disabled\"",
        "-c", "features.shell_tool=false",
        "-c", "windows.sandbox=\"unelevated\"",
        "-C", runDirText,
    };

    private string BuildConfig(string runDir, BridgeConfig bridge)
    {
        string config = CodexConfigTemplate
            .Replace("<enabled-tools>", string.Join(", ", EnabledTools.Select(Quoted).ToArray()))
            .Replace("<mcp-args-prefix>", string.Join(", ", _mcp.ArgumentPrefix.Select(Quoted).ToArray()))
            .Replace("<mcp-command>", PathText(_mcp.Command))
            .Replace("<run_dir>", PathText(runDir))
            .Replace("<pipe>", bridge.Pipe)
            .Replace("<secret>", bridge.Secret);

        return Crlf(config) + "\r\n";
    }

    /// <summary>
    /// What the previous profile in this folder had been edited into, one line per restriction
    /// key that is missing or changed.
    ///
    /// A text comparison rather than a TOML parse, and deliberately: the file being compared
    /// against is one this writer produced last launch, so an exact line is exactly what should
    /// be there, and .NET Framework 4.8 has no TOML parser that would not be a new dependency
    /// for one warning. A hand-edit that merely reformats a restriction key is reported too -
    /// which is the right way round, because a reformatted restriction key is still an edited
    /// one.
    /// </summary>
    private IReadOnlyList<string> InspectPrevious(string configPath)
    {
        if (!File.Exists(configPath))
        {
            return new string[0];
        }

        string previous = File.ReadAllText(configPath);
        var warnings = new List<string>();
        foreach (KeyValuePair<string, string> restriction in RestrictionKeys())
        {
            if (previous.IndexOf(restriction.Value, StringComparison.Ordinal) < 0)
            {
                warnings.Add(
                    $"The Codex profile at {configPath} no longer restricted "
                    + $"{restriction.Key}; it has been regenerated and the edit is gone.");
            }
        }

        return warnings;
    }

    /// <summary>The keys whose loss would widen what the CLI may do, and the exact text the
    /// generated profile states them with.</summary>
    private static IEnumerable<KeyValuePair<string, string>> RestrictionKeys()
    {
        yield return new KeyValuePair<string, string>("sandbox_mode", "sandbox_mode = \"read-only\"");
        yield return new KeyValuePair<string, string>("approval_policy", "approval_policy = \"never\"");
        yield return new KeyValuePair<string, string>("web_search", "web_search = \"disabled\"");
        yield return new KeyValuePair<string, string>("features.shell_tool", "shell_tool = false");
        yield return new KeyValuePair<string, string>("windows.sandbox", "sandbox = \"unelevated\"");
        yield return new KeyValuePair<string, string>(
            "mcp_servers.swreview.enabled_tools",
            "enabled_tools = [" + string.Join(", ", EnabledTools.Select(Quoted).ToArray()) + "]");
    }

    private static string Quoted(string value) => "\"" + PathText(value) + "\"";

    /// <summary>
    /// A path as the generated files spell it: forward slashes.
    ///
    /// Not cosmetic. Every path in the config sits inside a TOML basic string, where a
    /// backslash starts an escape sequence, so a Windows path written natively is a parse
    /// error rather than a path - and the contract writes its own paths this way. Windows
    /// accepts `/` as a separator in every path API, the CLI's `-C` included, so one spelling
    /// serves the config, the launch arguments and `CODEX_HOME` alike.
    /// </summary>
    private static string PathText(string value) => value.Replace('\\', '/');

    /// <summary>CRLF, whatever the source file or the checkout did: the generated file is
    /// compared byte for byte, so its line endings cannot depend on git's text policy.</summary>
    private static string Crlf(string text) => text.Replace("\r\n", "\n").Replace("\n", "\r\n");

    private static string ReadInstructions()
    {
        const string resource = "SwReview.AddIn.Terminal.Profiles.codex-instructions.md";
        using (Stream? stream = typeof(CliProfileWriter).Assembly.GetManifestResourceStream(resource))
        {
            if (stream == null)
            {
                throw new CliProfileException(
                    $"the general-chat persona '{resource}' is not embedded in the add-in; "
                    + "check the EmbeddedResource item in SwReview.AddIn.csproj.");
            }

            using (var reader = new StreamReader(stream, Utf8NoBom))
            {
                return Crlf(reader.ReadToEnd());
            }
        }
    }
}
