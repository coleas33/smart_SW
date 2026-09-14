using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.ToolService;

namespace SwReview.AddIn.Terminal;

/// <summary>Everything <see cref="TerminalHost"/> is given; injected so it is testable headless.</summary>
public sealed class TerminalHostOptions
{
    /// <param name="channel">Where replies and unsolicited messages go
    /// (<c>TaskPaneControl.TerminalChannel</c>).</param>
    /// <param name="runFolder">The terminal run folder, resolved by the pane
    /// (<c>TaskPaneControl.TerminalRunFolder</c>): the current chat session's folder when there
    /// is one, and otherwise a fresh `&lt;run_root&gt;/&lt;timestamp&gt;-terminal`.</param>
    /// <param name="writeProfile">Writes the generated Codex config home into that folder and
    /// returns the launch for it (<see cref="CliProfileWriter.WriteCodex"/>).</param>
    public TerminalHostOptions(
        IPageChannel channel, Func<string> runFolder, Func<string, CodexProfile> writeProfile)
    {
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        RunFolder = runFolder ?? throw new ArgumentNullException(nameof(runFolder));
        WriteProfile = writeProfile ?? throw new ArgumentNullException(nameof(writeProfile));
    }

    public IPageChannel Channel { get; }

    public Func<string> RunFolder { get; }

    public Func<string, CodexProfile> WriteProfile { get; }

    /// <summary>What the dropdown is built from. Blocks for up to 20 seconds per CLI, which is
    /// why nothing here may run on the SOLIDWORKS UI thread.</summary>
    public Func<IReadOnlyList<CliDiscovery>> LocateClis { get; set; } =
        () => new CliLocator().LocateAll();

    /// <summary>`init.last_choice`: the settings file's `terminal_cli`.</summary>
    public Func<string?> LastChoice { get; set; } = () => null;

    /// <summary>
    /// The first-launch tool listing gate for one start (T062), given the CLI that was found,
    /// the profile just written and the run folder.
    ///
    /// Injected only so the host can be tested on a machine with no Codex CLI. The default is
    /// the real thing: a `codex app-server` child over the generated `CODEX_HOME`.
    /// </summary>
    public Func<CliDiscovery, CodexProfile, string, ToolListingGate> Gate { get; set; } =
        DefaultGate;

    /// <summary>Starts the session. Injected for the same reason as <see cref="Gate"/>.</summary>
    public Func<TerminalSessionOptions, ITerminalSession> StartSession { get; set; } =
        options => TerminalSession.Start(options);

    /// <summary>The host's kill-on-close job: the CLI dies with SOLIDWORKS (T050).</summary>
    public JobObject? Job { get; set; }

    /// <summary>
    /// Values that must never reach the page: redacted from every error message the host
    /// sends (FR-015), the way <c>ReviewHost.Redact</c> masks the API key. In production it is
    /// the general-chat bridge secret; read per call so a tool service that starts after the
    /// host does is still covered.
    /// </summary>
    public Func<IEnumerable<string?>> Secrets { get; set; } = () => Array.Empty<string?>();

    /// <summary>How often `chat-log.jsonl` is counted while a session runs.</summary>
    public TimeSpan ChatLogInterval { get; set; } = TimeSpan.FromSeconds(1);

    /// <summary>
    /// The real gate: ask the CLI itself, over the app-server protocol, with the generated
    /// config home.
    ///
    /// The probe's child carries no reference to the host's job, and does not need one: it runs
    /// inside a nested kill-on-close job of its own that <see cref="CodexAppServerProbe.Run"/>
    /// closes before it returns, and a SOLIDWORKS that dies mid-probe has that handle closed by
    /// the kernel, which is the same protection by the same mechanism.
    /// </summary>
    private static ToolListingGate DefaultGate(
        CliDiscovery cli, CodexProfile profile, string runDirectory)
    {
        var probe = new CodexAppServerProbe(
            cli.Launch ?? throw new InvalidOperationException(
                "a CLI with no resolved launch command cannot be probed"),
            profile.Home,
            runDirectory);

        return ToolListingGate.ForCodex(probe.Run);
    }
}

/// <summary>
/// The Terminal page's other half: the five `Terminal page -> host` rows of
/// `contracts/pane-host-messages.md`, and the three the host sends unasked.
///
/// It is to the Terminal tab what <see cref="ReviewHost"/> is to the Review tab, and it exists
/// for a reason worth writing down: without it the tab was a page talking to nobody. The Start
/// button posted `terminal.start` and waited for a reply that could not come, `ready` never
/// settled so the dropdown stayed empty with no message in it, and <see cref="CliLocator"/>,
/// <see cref="CliProfileWriter"/>, <see cref="ToolListingGate"/> and
/// <see cref="TerminalSession"/> - all of them built and all of them tested - were composed
/// nowhere in the product.
///
/// What it is responsible for, in the order one start goes through them:
///
/// <b>Finding the CLI.</b> `ready` answers with every CLI the locator found, its version and
/// the sentence to show when it cannot be started, so the page decides nothing about a CLI for
/// itself (FR-023, spec scenario 4).
///
/// <b>Owning the run folder.</b> `terminal.start` asks the pane for it rather than taking one
/// from the page, exactly as `report.open` does on the Review side: the page is the least
/// trusted thing in the process.
///
/// <b>Regenerating the profile every start.</b> The generated Codex home is rewritten under the
/// run folder and an edit that loosened a restriction key is reported rather than silently put
/// back (FR-020, contracts/cli-profiles.md).
///
/// <b>Gating on the toolset.</b> The tool listing check runs before the CLI is started at all.
/// A difference refuses the start; so does a listing that could not be read or produced,
/// because what that means is that nobody checked (T062).
///
/// <b>Counting the chat log.</b> `chatlog.count` is posted as `chat-log.jsonl` grows, which is
/// the only feedback the engineer has that the CLI is answering out of the evidence package
/// rather than out of the model's memory (FR-022, SC-003).
///
/// Threading, and it matters: <see cref="Receive"/> is not re-entrant and must not run on the
/// SOLIDWORKS UI thread - `CliLocator.LocateAll` waits up to twenty seconds per CLI and the
/// tool listing probe waits for the MCP server to start. <see cref="Attach"/> therefore drains
/// the page's messages on one background thread of its own, in arrival order, exactly as the
/// add-in does for the Review page.
/// </summary>
public sealed class TerminalHost : IDisposable
{
    /// <summary>The file the MCP server appends one line to per tool call
    /// (`contracts/mcp-toolset.md`, `swreview.mcp.chat_log`).</summary>
    public const string ChatLogFileName = "chat-log.jsonl";

    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        WriteIndented = false,
    };

    private readonly TerminalHostOptions _options;
    private readonly object _gate = new object();

    private ITerminalSession? _session;
    private string? _chatLogPath;
    private int _chatLogCount = -1;
    private Timer? _chatLogTimer;

    private short _columns = 120;
    private short _rows = 30;

    private BlockingCollection<string>? _queue;
    private Thread? _pump;
    private Action? _unsubscribe;
    private bool _disposed;

    public TerminalHost(TerminalHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
    }

    /// <summary>The running CLI, or null. Read by the tests and by <see cref="Dispose"/>.</summary>
    public ITerminalSession? Session
    {
        get
        {
            lock (_gate)
            {
                return _session;
            }
        }
    }

    /// <summary>
    /// Builds the host the pane uses and subscribes it to the Terminal page.
    ///
    /// One call, because this is the whole wiring: the add-in holds the result and disposes it.
    /// Everything the host needs that only the add-in knows - the tool service's general-chat
    /// half, the settings, the host job - arrives here.
    /// </summary>
    /// <param name="pane">The Task Pane: its terminal channel, and its run-folder rule.</param>
    /// <param name="toolService">The general-chat bridge the generated profile carries. Never
    /// the review bridge: its secret also authorizes `interference`, and the CLI can read its
    /// own generated profile (contracts/README.md).</param>
    /// <param name="settings">The settings in force, read fresh at every start: the `python`
    /// field decides how `swreview mcp` is spelled and `terminal_cli` is the last choice.</param>
    /// <param name="job">The add-in's kill-on-close job.</param>
    public static TerminalHost Attach(
        TaskPaneControl pane,
        IToolServiceAccess toolService,
        Func<UserSettings> settings,
        JobObject? job)
    {
        if (pane == null)
        {
            throw new ArgumentNullException(nameof(pane));
        }

        if (toolService == null)
        {
            throw new ArgumentNullException(nameof(toolService));
        }

        if (settings == null)
        {
            throw new ArgumentNullException(nameof(settings));
        }

        var options = new TerminalHostOptions(
            pane.TerminalChannel,
            pane.TerminalRunFolder,
            // Resolved per start, not once: the `python` setting can be changed from the
            // Settings tab between one terminal and the next, and a writer built at connect
            // time would keep writing the old spelling into the generated profile.
            runDirectory => new CliProfileWriter(
                    toolService, McpServerCommand.Resolve(settings()))
                .WriteCodex(runDirectory))
        {
            LastChoice = () => settings().TerminalCli,
            Job = job,
            Secrets = () => new[] { toolService.GeneralChatBridge?.Secret },
        };

        var host = new TerminalHost(options);
        host.Listen(pane);
        return host;
    }

    /// <summary>Handles one message from the page. Never throws.</summary>
    public void Receive(string json)
    {
        string? id = null;
        try
        {
            using (JsonDocument document = JsonDocument.Parse(json))
            {
                JsonElement root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object)
                {
                    throw new FormatException("a page message must be a JSON object");
                }

                id = Text(root, "id");
                string? type = Text(root, "type");
                if (string.IsNullOrEmpty(type))
                {
                    throw new FormatException("a page message must carry a 'type'");
                }

                JsonElement payload = root.TryGetProperty("payload", out JsonElement value)
                    ? value
                    : default;
                Dispatch(type!, id, payload);
            }
        }
        catch (Exception failure)
        {
            SendError(id, "HostError", failure.Message, null);
        }
    }

    /// <summary>Sends an unsolicited message (`terminal.output` is the session's own job).</summary>
    public void Post(string type, object? payload) => Send(type, null, payload);

    /// <summary>
    /// One tick of the chat-log counter: count the lines and post the number if it moved.
    ///
    /// Public so a test can drive it without waiting on a clock. A count rather than a watcher:
    /// `FileSystemWatcher` misses writes under load and reports some of them twice, and this
    /// number only has to be approximately live - it is the engineer's confidence that the CLI
    /// is asking the evidence package rather than remembering.
    /// </summary>
    public void PollChatLog()
    {
        string? path;
        ITerminalSession? session;
        lock (_gate)
        {
            path = _chatLogPath;
            session = _session;
        }

        if (path == null)
        {
            return;
        }

        int count = CountLines(path);
        bool changed;
        lock (_gate)
        {
            changed = count != _chatLogCount;
            _chatLogCount = count;
        }

        if (changed)
        {
            Post("chatlog.count", new Dictionary<string, object?> { { "count", count } });
        }

        if (session != null && session.HasExited)
        {
            // The CLI has gone; the number will not move again, and a timer that kept ticking
            // would keep reading a file in a folder the engineer may be deleting.
            StopChatLog();
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
        }

        try
        {
            _unsubscribe?.Invoke();
        }
        catch (Exception)
        {
        }

        _unsubscribe = null;

        BlockingCollection<string>? queue = _queue;
        if (queue != null)
        {
            try
            {
                queue.CompleteAdding();
            }
            catch (Exception)
            {
            }

            // Bounded: the pump may be inside a twenty-second locate, and SOLIDWORKS is not made
            // to wait for it.
            _pump?.Join(TimeSpan.FromSeconds(2));
        }

        _pump = null;
        StopChatLog();
        EndSession();
    }

    // ---- the pump ---------------------------------------------------------------------------

    /// <summary>
    /// Subscribes to the pane's Terminal page and drains its messages on one background thread.
    ///
    /// `WebMessageReceived` is raised on the SOLIDWORKS UI thread, and everything this host does
    /// with a message can block for seconds - locating a CLI, writing a profile, probing a tool
    /// listing. One thread rather than the thread pool because the handlers are not re-entrant
    /// and the page's messages are ordered: a `terminal.input` overtaking the `terminal.start`
    /// it was typed into would be a keystroke sent to a console that does not exist yet.
    /// </summary>
    private void Listen(TaskPaneControl pane)
    {
        var queue = new BlockingCollection<string>();
        _queue = queue;

        EventHandler<string> handler = (_, json) =>
        {
            try
            {
                queue.Add(json);
            }
            catch (Exception)
            {
                // The pump is shutting down; the page is about to go with it.
            }
        };

        pane.TerminalPageMessageReceived += handler;
        _unsubscribe = () => pane.TerminalPageMessageReceived -= handler;

        _pump = new Thread(() =>
        {
            foreach (string json in queue.GetConsumingEnumerable())
            {
                try
                {
                    Receive(json);
                }
                catch (Exception)
                {
                    // Receive answers its own failures; an exception escaping onto this
                    // background thread would take SOLIDWORKS down with it.
                }
            }
        })
        {
            IsBackground = true,
            Name = "swreview-terminal-messages",
        };
        _pump.Start();
    }

    // ---- dispatch ---------------------------------------------------------------------------

    private void Dispatch(string type, string? id, JsonElement payload)
    {
        switch (type)
        {
            case "ready":
                Ready(id, payload);
                return;

            case "terminal.start":
                Start(id, payload);
                return;

            case "terminal.input":
                Input(payload);
                return;

            case "terminal.resize":
                Resize(payload);
                return;

            case "terminal.stop":
                Stop(id);
                return;

            default:
                SendError(
                    id,
                    "UnknownMessage",
                    $"the terminal host does not handle a '{type}' message",
                    null);
                return;
        }
    }

    // ---- ready ------------------------------------------------------------------------------

    private void Ready(string? id, JsonElement payload)
    {
        RememberSize(payload);

        IReadOnlyList<CliDiscovery> clis;
        try
        {
            clis = _options.LocateClis();
        }
        catch (Exception failure)
        {
            // A PATH that cannot be walked is not a reason to leave the tab with an empty
            // dropdown and no explanation, which is exactly what it showed before this host
            // existed.
            SendError(id, "CliLookupFailed", failure.Message, null);
            return;
        }

        Send("init", id, new Dictionary<string, object?>
        {
            { "clis", clis.Select(Row).ToArray() },
            { "last_choice", LastChoice() },
        });
    }

    /// <summary>One row of `init.clis`: the contract's `{name, found, version, path, minimum}`
    /// plus the host's own sentence, so the page shows a refusal rather than composing one.</summary>
    private static Dictionary<string, object?> Row(CliDiscovery cli) =>
        new Dictionary<string, object?>
        {
            { "name", cli.Cli.Name },
            { "display_name", cli.Cli.DisplayName },
            { "found", cli.Launch != null },
            { "status", StatusText(cli.Status) },
            { "version", cli.Version?.ToString(3) },
            { "path", cli.Launch?.ToolPath },
            { "minimum", cli.Cli.MinimumVersion?.ToString(3) },
            { "message", cli.Message },
            { "install_steps", cli.Cli.InstallSteps },
        };

    /// <summary>The status as the page spells it (`term.js` STATUS_TEXT).</summary>
    private static string StatusText(CliStatus status)
    {
        switch (status)
        {
            case CliStatus.Ready:
                return "ready";
            case CliStatus.Deferred:
                return "deferred";
            case CliStatus.NotInstalled:
                return "not_installed";
            case CliStatus.Unsupported:
                return "unsupported";
            case CliStatus.TooOld:
                return "too_old";
            case CliStatus.VersionUnreadable:
                return "version_unreadable";
            default:
                return "not_installed";
        }
    }

    private string? LastChoice()
    {
        try
        {
            return _options.LastChoice();
        }
        catch (Exception)
        {
            // An unreadable settings file is the Review tab's problem to report; here it just
            // means the dropdown opens on its first row.
            return null;
        }
    }

    // ---- terminal.start ----------------------------------------------------------------------

    /// <summary>
    /// Press Start: find the CLI, create the run folder, regenerate the profile, check what the
    /// CLI loads, and only then start it.
    ///
    /// The order is the contract's and is not negotiable. The refusals come first because each
    /// of them has something for the engineer to do about it. The profile is written before the
    /// gate because the gate probes the CLI *with* the generated home - a check against
    /// anything else would be a check of a configuration that is not the one being started. And
    /// the gate runs before the session because a CLI that was started and then complained about
    /// has already been an unrestricted process on the workstation.
    /// </summary>
    private void Start(string? id, JsonElement payload)
    {
        RememberSize(payload);

        lock (_gate)
        {
            if (_session != null && !_session.HasExited)
            {
                SendError(
                    id,
                    "TerminalRunning",
                    "a terminal is already running in this pane. Stop it before starting "
                    + "another.",
                    null);
                return;
            }
        }

        string name = (Text(payload, "cli") ?? string.Empty).Trim();
        if (name.Length == 0)
        {
            SendError(id, "InvalidRequest", "terminal.start needs the name of a CLI.", null);
            return;
        }

        CliDiscovery? cli;
        try
        {
            cli = _options.LocateClis().FirstOrDefault(
                found => string.Equals(found.Cli.Name, name, StringComparison.OrdinalIgnoreCase));
        }
        catch (Exception failure)
        {
            SendError(id, "CliLookupFailed", failure.Message, null);
            return;
        }

        if (cli == null)
        {
            SendError(
                id,
                "UnknownCli",
                $"'{name}' is not a CLI this pane knows.",
                null);
            return;
        }

        if (!cli.CanStart)
        {
            // The locator's own sentence, verbatim: it already says whether the CLI is missing,
            // too old, deferred or of a kind that cannot be started, and it is the same sentence
            // the dropdown is showing.
            SendError(id, Refusal(cli.Status), cli.Message, cli.Cli.InstallSteps);
            return;
        }

        if (!string.Equals(cli.Cli.Name, "codex", StringComparison.OrdinalIgnoreCase))
        {
            // Unreachable while Gemini is the only other CLI and is deferred, and here anyway:
            // the profile writer below writes a Codex config home, and a second CLI arriving
            // without its own profile must be a refusal rather than a Codex profile handed to
            // something else.
            SendError(
                id,
                "CliNotSupported",
                $"{cli.Cli.DisplayName} has no generated profile in this version, so it cannot "
                + "be started from the pane.",
                cli.Cli.InstallSteps);
            return;
        }

        string runDirectory;
        try
        {
            runDirectory = _options.RunFolder();
        }
        catch (Exception failure)
        {
            SendError(id, "RunFolderFailed", failure.Message, null);
            return;
        }

        CodexProfile profile;
        try
        {
            profile = _options.WriteProfile(runDirectory);
        }
        catch (CliProfileException failure)
        {
            SendError(id, "ProfileFailed", failure.Message, cli.Cli.InstallSteps);
            return;
        }
        catch (Exception failure)
        {
            SendError(id, "ProfileFailed", failure.Message, null);
            return;
        }

        var options = new TerminalSessionOptions(
            cli.Launch!.With(profile.Arguments.ToArray()),
            _options.Channel,
            Gate(cli, profile, runDirectory))
        {
            WorkingDirectory = runDirectory,
            Columns = _columns,
            Rows = _rows,
            Job = _options.Job,
        };

        foreach (KeyValuePair<string, string> variable in profile.Environment)
        {
            options.Environment[variable.Key] = variable.Value;
        }

        ITerminalSession session;
        try
        {
            session = _options.StartSession(options);
        }
        catch (ToolListingException refused)
        {
            // The gate. The message is tool names and the CLI's display name - nothing from a
            // model and nothing from a secret - so it goes to the page unchanged.
            SendError(id, "ToolListingRefused", refused.Message, null);
            return;
        }
        catch (Exception failure)
        {
            SendError(id, "TerminalStartFailed", failure.Message, cli.Cli.InstallSteps);
            return;
        }

        lock (_gate)
        {
            _session = session;
        }

        Send("terminal.started", id, new Dictionary<string, object?>
        {
            { "pid", session.ProcessId },
            { "cwd", session.WorkingDirectory },
            {
                "profile_paths",
                new[] { profile.ConfigPath, profile.InstructionsPath, profile.AuthPath }
            },
        });

        // After the reply, so the page has already left its "starting" state when the banner
        // appears: a profile the engineer had loosened is regenerated either way, and being told
        // is the whole of what they can do about it.
        ReportWarnings(profile);

        StartChatLog(runDirectory);
    }

    private ToolListingGate Gate(CliDiscovery cli, CodexProfile profile, string runDirectory)
    {
        ToolListingGate? gate = _options.Gate(cli, profile, runDirectory);
        if (gate == null)
        {
            // A gate factory that answered null would be the permissive default this design
            // exists to remove; it is a refusal, not a start.
            throw new ToolListingException(
                ToolListingCheck.ForCodex().Check(ToolListing.FromNames(
                    Array.Empty<string>(), Array.Empty<string>())));
        }

        return gate;
    }

    private void ReportWarnings(CodexProfile profile)
    {
        if (profile.Warnings.Count == 0)
        {
            return;
        }

        // One message rather than one per warning: they are all the same event - the previous
        // profile in this folder had been edited - and the page shows them in one banner.
        Post("error", new Dictionary<string, object?>
        {
            { "error_class", "ProfileRegenerated" },
            { "message", string.Join(" ", profile.Warnings.ToArray()) },
            { "retryable", false },
        });
    }

    private static string Refusal(CliStatus status) =>
        status == CliStatus.Deferred ? "CliDeferred" : "CliUnavailable";

    // ---- input / resize / stop -----------------------------------------------------------------

    private void Input(JsonElement payload)
    {
        ITerminalSession? session = Session;
        string? data = Text(payload, "data");
        if (session == null || string.IsNullOrEmpty(data))
        {
            // A keystroke that arrives after the CLI exited is the ordinary end of a session,
            // not a fault to report: the contract gives `terminal.input` no reply at all, so an
            // error here would surface on the page as a banner with no request behind it.
            return;
        }

        try
        {
            session.Write(data!);
        }
        catch (Exception)
        {
            // The session reports its own end through `terminal.exited`.
        }
    }

    private void Resize(JsonElement payload)
    {
        RememberSize(payload);

        ITerminalSession? session = Session;
        if (session == null)
        {
            return;
        }

        try
        {
            session.Resize(_columns, _rows);
        }
        catch (Exception)
        {
        }
    }

    private void Stop(string? id)
    {
        EndSession();

        // Always `terminal.stopped`, even with nothing running: the page sends Stop when it
        // believes a session is live, and a CLI that exited a moment earlier would otherwise
        // leave the button disabled behind an error banner.
        Send("terminal.stopped", id, new Dictionary<string, object?>());
    }

    private void EndSession()
    {
        ITerminalSession? session;
        lock (_gate)
        {
            session = _session;
            _session = null;
        }

        StopChatLog();

        if (session == null)
        {
            return;
        }

        try
        {
            session.Stop();
        }
        catch (Exception)
        {
        }

        try
        {
            session.Dispose();
        }
        catch (Exception)
        {
        }
    }

    // ---- chatlog.count -------------------------------------------------------------------------

    private void StartChatLog(string runDirectory)
    {
        string path;
        try
        {
            path = Path.Combine(runDirectory, ChatLogFileName);
        }
        catch (ArgumentException)
        {
            return;
        }

        lock (_gate)
        {
            _chatLogPath = path;
            _chatLogCount = -1;
        }

        // The first tick now, so the page shows a number from the moment the terminal opens
        // rather than after the first second.
        PollChatLog();

        var timer = new Timer(_ => SafePoll(), null, _options.ChatLogInterval, _options.ChatLogInterval);
        Timer? previous;
        lock (_gate)
        {
            previous = _chatLogTimer;
            _chatLogTimer = timer;
        }

        previous?.Dispose();
    }

    private void SafePoll()
    {
        try
        {
            PollChatLog();
        }
        catch (Exception)
        {
            // A timer callback is a thread-pool thread: a throw here ends the process.
        }
    }

    private void StopChatLog()
    {
        Timer? timer;
        lock (_gate)
        {
            timer = _chatLogTimer;
            _chatLogTimer = null;
            _chatLogPath = null;
        }

        timer?.Dispose();
    }

    /// <summary>
    /// The number of complete lines in `chat-log.jsonl`, or 0 when there is none yet.
    ///
    /// Opened with the widest possible sharing, because the MCP server is appending to this file
    /// from another process while it is being read; a read that failed would be a counter that
    /// stopped, so anything that goes wrong is answered with the count so far.
    /// </summary>
    private static int CountLines(string path)
    {
        try
        {
            using (var stream = new FileStream(
                path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream, new UTF8Encoding(false)))
            {
                int count = 0;
                while (reader.ReadLine() != null)
                {
                    count++;
                }

                return count;
            }
        }
        catch (FileNotFoundException)
        {
            return 0;
        }
        catch (DirectoryNotFoundException)
        {
            return 0;
        }
        catch (Exception)
        {
            return 0;
        }
    }

    // ---- plumbing -------------------------------------------------------------------------------

    private void RememberSize(JsonElement payload)
    {
        short columns = Size(payload, "cols", _columns);
        short rows = Size(payload, "rows", _rows);

        _columns = columns;
        _rows = rows;
    }

    private static short Size(JsonElement payload, string name, short fallback)
    {
        if (payload.ValueKind != JsonValueKind.Object
            || !payload.TryGetProperty(name, out JsonElement value)
            || value.ValueKind != JsonValueKind.Number
            || !value.TryGetInt32(out int number))
        {
            return fallback;
        }

        // A pane dragged to nothing reports zero cells, and a pseudo-console refuses a
        // non-positive size; the last good size is better than a refused resize.
        return number <= 0 || number > short.MaxValue ? fallback : (short)number;
    }

    private static string? Text(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object
            || !element.TryGetProperty(name, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    }

    private void SendError(string? id, string errorClass, string message, string? installSteps)
    {
        Send("error", id, new Dictionary<string, object?>
        {
            { "error_class", errorClass },
            { "message", Redaction.Redact(message, _options.Secrets()) },
            { "install_steps", installSteps },
            { "retryable", true },
        });
    }

    private void Send(string type, string? id, object? payload)
    {
        var envelope = new Dictionary<string, object?>
        {
            { "type", type },
            { "id", id },
            { "payload", payload },
        };

        try
        {
            _options.Channel.PostMessage(JsonSerializer.Serialize(envelope, JsonOptions));
        }
        catch (Exception)
        {
            // The page is gone (the pane closed mid-handler). There is nobody left to tell.
        }
    }
}
