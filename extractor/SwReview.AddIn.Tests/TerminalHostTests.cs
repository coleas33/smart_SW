using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.Terminal;
using SwReview.AddIn.ToolService;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T060's host half: the other end of every row of the `Terminal page -> host` table in
/// `contracts/pane-host-messages.md`.
///
/// <see cref="TerminalPageContractTests"/> scans the page and proves it posts nothing the
/// contract does not define. That test cannot see the failure this one exists for: a contract
/// row with a sender and no handler. With the Terminal tab unwired, every one of the five rows
/// was in exactly that state - the page's Start button posted `terminal.start` and waited for a
/// reply that was never going to come, `CODEX_HOME` and the generated profile never reached a
/// child, and `CliLocator`, `CliProfileWriter`, `ToolListingGate` and `TerminalSession` were
/// composed only in tests. The suite was green throughout.
///
/// So this is the mirror: every row is driven through a real <see cref="TerminalHost"/> over a
/// recording channel, with a real <see cref="CliProfileWriter"/> writing a real generated
/// profile into a real run folder. Only three things are faked, and each for a reason no
/// injection would fix: there is no Codex CLI on the machines that build this solution
/// (<see cref="FakeSession"/> and the gate's probe), and no SOLIDWORKS behind the tool service.
/// </summary>
public sealed class TerminalHostTests
{
    // ---- the contract, from both sides -------------------------------------------------------

    /// <summary>
    /// Every `Terminal page -> host` row is handled - the host-side mirror of
    /// `EveryTerminalPageToHostRowIsExercisedByThePage`.
    ///
    /// "Handled" is the weakest claim that catches the failure: the host does not answer the
    /// message with `UnknownMessage`. The rows that do something visible are asserted properly
    /// below; this one is the sweep that a row added to the contract later cannot slip past.
    /// </summary>
    [Fact]
    public void EveryTerminalPageToHostRowHasAHandler()
    {
        var unhandled = new List<string>();

        foreach (string type in ContractRows())
        {
            using (var fixture = new Fixture())
            {
                fixture.Host.Receive(Message(type, "m1"));
                if (fixture.Channel.Replies("m1").Any(IsUnknownMessage))
                {
                    unhandled.Add(type);
                }
            }
        }

        Assert.True(
            unhandled.Count == 0,
            "The host answers documented Terminal page messages with UnknownMessage: "
                + string.Join(", ", unhandled)
                + ". The page is the only sender these rows have, so an unhandled one is a "
                + "button that does nothing and a request that never settles.");
    }

    [Fact]
    public void AnUndocumentedTypeIsAnsweredWithAnError()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.resized", "m1"));

            JsonElement error = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("error", Type(error));
            Assert.Contains("terminal.resized", Payload(error).GetProperty("message").GetString()!);
        }
    }

    [Fact]
    public void NothingMalformedEscapesAsAnException()
    {
        using (var fixture = new Fixture())
        {
            // The pane's message pump is a background thread; an exception out of Receive would
            // take SOLIDWORKS down with it.
            fixture.Host.Receive("not json");
            fixture.Host.Receive("[]");
            fixture.Host.Receive("{\"id\":\"m1\"}");

            Assert.All(fixture.Channel.Messages, message => Assert.Equal("error", Type(message)));
        }
    }

    // ---- ready ------------------------------------------------------------------------------

    [Fact]
    public void ReadyIsAnsweredWithTheCliListAndTheLastChoice()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("ready", "m1", new { cols = 100, rows = 40 }));

            JsonElement init = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("init", Type(init));

            JsonElement payload = Payload(init);
            Assert.Equal("codex", payload.GetProperty("last_choice").GetString());

            JsonElement[] clis = payload.GetProperty("clis").EnumerateArray().ToArray();
            Assert.Equal(new[] { "codex", "gemini" }, clis.Select(c => c.GetProperty("name").GetString()));

            // The contract's row is `{name, found, version, path, minimum}`; the page also shows
            // the host's own sentence and install steps rather than inventing one.
            JsonElement codex = clis[0];
            Assert.True(codex.GetProperty("found").GetBoolean());
            Assert.Equal("ready", codex.GetProperty("status").GetString());
            Assert.Equal("0.115.0", codex.GetProperty("version").GetString());
            Assert.False(string.IsNullOrEmpty(codex.GetProperty("path").GetString()));
            Assert.False(string.IsNullOrEmpty(codex.GetProperty("install_steps").GetString()));

            // Gemini is installed on this fixture's PATH and still not offered: the terminal
            // for it is deferred (decision 2026-09-13), which is a different sentence from "not
            // installed" and has to reach the dropdown as one.
            Assert.True(clis[1].GetProperty("found").GetBoolean());
            Assert.Equal("deferred", clis[1].GetProperty("status").GetString());
        }
    }

    [Fact]
    public void ReadyAnswersEvenWhenNoCliIsInstalled()
    {
        using (var fixture = new Fixture())
        {
            fixture.Clis = new[] { Discovery.NotInstalled() };
            fixture.Host.Receive(Message("ready", "m1", new { cols = 80, rows = 24 }));

            JsonElement init = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("init", Type(init));

            // An empty dropdown with no explanation is what the tab showed while the host did
            // not exist; the whole point of `init` is that the refusal arrives with it.
            JsonElement cli = Assert.Single(Payload(init).GetProperty("clis").EnumerateArray());
            Assert.False(cli.GetProperty("found").GetBoolean());
            Assert.Contains("npm install", cli.GetProperty("install_steps").GetString()!);
        }
    }

    // ---- terminal.start ----------------------------------------------------------------------

    [Fact]
    public void StartWritesTheProfileGatesTheListingAndRunsInTheTerminalRunFolder()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex", cols = 100, rows = 40 }));

            JsonElement started = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("terminal.started", Type(started));

            JsonElement payload = Payload(started);
            Assert.Equal(FakeSession.Pid, payload.GetProperty("pid").GetInt32());
            Assert.Equal(fixture.RunDirectory, payload.GetProperty("cwd").GetString());

            // The generated profile is on disk under the run folder, and the page is told where.
            string[] paths = payload.GetProperty("profile_paths").EnumerateArray()
                .Select(path => path.GetString()!)
                .ToArray();
            Assert.NotEmpty(paths);
            Assert.All(paths, path => Assert.True(File.Exists(path), path + " was not written"));
            Assert.Contains(paths, path => path.EndsWith("config.toml", StringComparison.Ordinal));

            // The gate ran, and it ran before the session was started: an unrestricted CLI that
            // was started and then complained about has already been a process on the
            // workstation (contracts/cli-profiles.md).
            Assert.Equal(1, fixture.ProbeCalls);
            Assert.True(fixture.GateVerifiedBeforeStart);

            // The session was started the way the contract describes: in the run folder, with
            // the generated home in its environment and the profile's own arguments.
            TerminalSessionOptions options = Assert.Single(fixture.Started);
            Assert.Equal(fixture.RunDirectory, options.WorkingDirectory);
            Assert.Equal(
                fixture.Profile!.Home.Replace('\\', '/'),
                options.Environment[CliProfileWriter.HomeVariable]);
            Assert.Contains("--profile", options.Launch.Arguments);
            Assert.Contains(CliProfileWriter.ProfileName, options.Launch.Arguments);
            Assert.Equal(100, options.Columns);
            Assert.Equal(40, options.Rows);
            Assert.NotNull(options.ToolListing.Check);
        }
    }

    /// <summary>
    /// What the add-in actually starts with.
    ///
    /// Every test above replaces the gate, because there is no Codex CLI on a build machine -
    /// which is exactly how a default of "no gate at all" would survive a green suite. The
    /// default is asserted to be the real thing: a Codex check over
    /// <see cref="CliProfileWriter.EnabledTools"/>, fed by the app-server probe.
    /// </summary>
    [Fact]
    public void TheDefaultGateIsACodexToolListingCheckAndNotAnOptOut()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            var defaults = new TerminalHostOptions(
                fixture.Channel, () => fixture.RunDirectory, _ => fixture.Profile!);

            ToolListingGate gate = defaults.Gate(
                fixture.Clis[0], fixture.Profile!, fixture.RunDirectory);

            Assert.NotSame(ToolListingGate.NotACli, gate);
            Assert.NotNull(gate.Check);
            Assert.Same(CliProfileWriter.EnabledTools, gate.Check!.Allowlist);
            Assert.Equal(ToolListingCheck.CodexBuiltIns, gate.Check.BuiltIns);
        }
    }

    [Fact]
    public void StartIsRefusedWithInstallStepsWhenTheCliIsNotThere()
    {
        using (var fixture = new Fixture())
        {
            fixture.Clis = new[] { Discovery.NotInstalled() };

            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            JsonElement error = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("error", Type(error));
            Assert.Contains("npm install", Payload(error).GetProperty("install_steps").GetString()!);
            Assert.Empty(fixture.Started);
        }
    }

    [Fact]
    public void StartIsRefusedWhenTheCliIsDeferred()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "gemini" }));

            JsonElement error = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("error", Type(error));
            Assert.Contains(
                "deferred", Payload(error).GetProperty("message").GetString()!,
                StringComparison.OrdinalIgnoreCase);
            Assert.Empty(fixture.Started);
        }
    }

    [Fact]
    public void AStartFailureMessageNeverCarriesTheGeneralChatSecret()
    {
        using (var fixture = new Fixture())
        {
            fixture.ProfileFailure = new InvalidOperationException("writer saw " + Fixture.Secret);

            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            JsonElement error = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("error", Type(error));
            string message = Payload(error).GetProperty("message").GetString()!;
            Assert.DoesNotContain(Fixture.Secret, message);
            Assert.Contains("[redacted]", message);
            Assert.Empty(fixture.Started);
        }
    }

    [Fact]
    public void StartIsRefusedWhenTheToolListingDiffers()
    {
        using (var fixture = new Fixture())
        {
            fixture.Listing = Fixture.ListingWith("write_file");

            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            JsonElement error = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("error", Type(error));
            Assert.Contains("write_file", Payload(error).GetProperty("message").GetString()!);

            // The refusal is the whole point: nothing was started.
            Assert.Empty(fixture.Started);
        }
    }

    [Fact]
    public void StartIsRefusedWhenTheProfileCannotBeWritten()
    {
        using (var fixture = new Fixture())
        {
            // The engineer has never run `codex login`, so there is no credential to copy into
            // the generated home - a refusal with something to do about it, not a stack trace.
            fixture.DeleteAuth();

            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            JsonElement error = Assert.Single(fixture.Channel.Replies("m1"));
            Assert.Equal("error", Type(error));
            Assert.Contains("codex login", Payload(error).GetProperty("message").GetString()!);
            Assert.Empty(fixture.Started);
        }
    }

    [Fact]
    public void AnEditedProfileIsReportedToThePage()
    {
        using (var fixture = new Fixture())
        {
            fixture.WritePreviousProfile("sandbox_mode = \"danger-full-access\"\r\n");

            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            Assert.Equal("terminal.started", Type(Assert.Single(fixture.Channel.Replies("m1"))));

            // `CodexProfile.Warnings` had nowhere to go while the host did not exist. The
            // profile is regenerated either way; the engineer is told their edit is gone.
            JsonElement warning = Assert.Single(
                fixture.Channel.Unsolicited(), message => Type(message) == "error");
            Assert.Contains("sandbox_mode", Payload(warning).GetProperty("message").GetString()!);
        }
    }

    [Fact]
    public void ASecondStartWhileOneIsRunningIsRefused()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));
            fixture.Host.Receive(Message("terminal.start", "m2", new { cli = "codex" }));

            Assert.Equal("terminal.started", Type(Assert.Single(fixture.Channel.Replies("m1"))));
            Assert.Equal("error", Type(Assert.Single(fixture.Channel.Replies("m2"))));
            Assert.Single(fixture.Started);
        }
    }

    // ---- input, resize, stop -----------------------------------------------------------------

    [Fact]
    public void InputAndResizeReachTheSessionAndStopEndsIt()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            fixture.Host.Receive(Message("terminal.input", "m2", new { data = "codex --help\r" }));
            fixture.Host.Receive(Message("terminal.resize", "m3", new { cols = 132, rows = 50 }));
            fixture.Host.Receive(Message("terminal.stop", "m4"));

            FakeSession session = Assert.Single(fixture.Sessions);
            Assert.Equal("codex --help\r", Assert.Single(session.Written));
            Assert.Equal((short)132, session.Columns);
            Assert.Equal((short)50, session.Rows);
            Assert.True(session.Stopped);

            // The contract gives input and resize no reply; a page that waited for one would
            // leak a pending entry per keystroke.
            Assert.Empty(fixture.Channel.Replies("m2"));
            Assert.Empty(fixture.Channel.Replies("m3"));
            Assert.Equal("terminal.stopped", Type(Assert.Single(fixture.Channel.Replies("m4"))));
        }
    }

    [Fact]
    public void StopWithNoSessionIsStillAnswered()
    {
        using (var fixture = new Fixture())
        {
            // The page sends Stop when it believes a session is running; if the CLI has just
            // exited, the honest answer is still `terminal.stopped` rather than an error the
            // page would show as a banner.
            fixture.Host.Receive(Message("terminal.stop", "m1"));

            Assert.Equal("terminal.stopped", Type(Assert.Single(fixture.Channel.Replies("m1"))));
        }
    }

    [Fact]
    public void InputIsDroppedRatherThanThrownWhenNothingIsRunning()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.input", "m1", new { data = "x" }));
            fixture.Host.Receive(Message("terminal.resize", "m2", new { cols = 80, rows = 24 }));

            Assert.Empty(fixture.Channel.Messages);
        }
    }

    /// <summary>The size the page negotiated in `ready` is the size the first CLI starts at.</summary>
    [Fact]
    public void AResizeBeforeTheStartIsRememberedForIt()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("ready", "m1", new { cols = 90, rows = 30 }));
            fixture.Host.Receive(Message("terminal.start", "m2", new { cli = "codex" }));

            TerminalSessionOptions options = Assert.Single(fixture.Started);
            Assert.Equal(90, options.Columns);
            Assert.Equal(30, options.Rows);
        }
    }

    // ---- chatlog.count -------------------------------------------------------------------------

    [Fact]
    public void TheChatLogCountIsPostedAsTheLogGrows()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("terminal.start", "m1", new { cli = "codex" }));

            // The count the page shows before any tool call has been made.
            Assert.Equal(0, LastCount(fixture));

            File.AppendAllText(fixture.ChatLogPath, "{\"tool\":\"list_components\"}\n");
            fixture.Host.PollChatLog();
            Assert.Equal(1, LastCount(fixture));

            File.AppendAllText(fixture.ChatLogPath, "{\"tool\":\"list_mates\"}\n");
            fixture.Host.PollChatLog();
            Assert.Equal(2, LastCount(fixture));

            // Only when it moves: a message per tick would be a message per second for as long
            // as the terminal is open, each one a marshalled call onto the SOLIDWORKS UI thread.
            int before = fixture.Channel.Unsolicited().Count(m => Type(m) == "chatlog.count");
            fixture.Host.PollChatLog();
            Assert.Equal(
                before, fixture.Channel.Unsolicited().Count(m => Type(m) == "chatlog.count"));
        }
    }

    // ---- FR-015 --------------------------------------------------------------------------------

    [Fact]
    public void NoMessageToThePageCarriesTheToolServiceSecret()
    {
        using (var fixture = new Fixture())
        {
            fixture.Host.Receive(Message("ready", "m1", new { cols = 80, rows = 24 }));
            fixture.Host.Receive(Message("terminal.start", "m2", new { cli = "codex" }));
            fixture.Host.Receive(Message("terminal.stop", "m3"));

            foreach (string json in fixture.Channel.Raw)
            {
                Assert.DoesNotContain(Fixture.Secret, json, StringComparison.Ordinal);
            }

            // ...and it does reach the CLI, in the one place FR-015 allows: the generated
            // profile's own environment block, which the child reads and nobody else does.
            Assert.Contains(
                Fixture.Secret,
                File.ReadAllText(Path.Combine(fixture.Profile!.Home, "config.toml")),
                StringComparison.Ordinal);
        }
    }

    // ---- helpers ---------------------------------------------------------------------------------

    private static int LastCount(Fixture fixture) => fixture.Channel.Unsolicited()
        .Where(message => Type(message) == "chatlog.count")
        .Select(message => Payload(message).GetProperty("count").GetInt32())
        .Last();

    private static bool IsUnknownMessage(JsonElement message) =>
        Type(message) == "error"
        && Payload(message).TryGetProperty("error_class", out JsonElement kind)
        && kind.GetString() == "UnknownMessage";

    private static string Type(JsonElement message) => message.GetProperty("type").GetString()!;

    private static JsonElement Payload(JsonElement message) => message.GetProperty("payload");

    private static string Message(string type, string id, object? payload = null) =>
        JsonSerializer.Serialize(new
        {
            type,
            id,
            payload = payload ?? new { },
        });

    /// <summary>The `type` column of the contract's `Terminal page -> host` table.</summary>
    private static IReadOnlyList<string> ContractRows()
    {
        var rows = new List<string>();
        var row = new Regex(@"^\|\s*`([a-z][a-z0-9_.]*)`\s*\|", RegexOptions.Compiled);
        string? section = null;

        foreach (string raw in ReviewPageFiles.ReadContract("pane-host-messages.md").Split('\n'))
        {
            string line = raw.TrimEnd('\r');
            if (line.StartsWith("## ", StringComparison.Ordinal))
            {
                section = line.Substring(3).Trim();
                continue;
            }

            Match match = row.Match(line);
            if (match.Success && section != null
                && section.StartsWith("Terminal page", StringComparison.Ordinal))
            {
                rows.Add(match.Groups[1].Value);
            }
        }

        Assert.Equal(5, rows.Count);
        return rows;
    }

    // ---- the fixture -------------------------------------------------------------------------------

    /// <summary>
    /// A run folder, a generated profile, a recording channel and a host over them.
    ///
    /// The profile writer, the profile itself and the gate are the real ones: what is faked is
    /// the CLI (there is none on this machine), the listing it would have reported, and the tool
    /// service's SOLIDWORKS half.
    /// </summary>
    private sealed class Fixture : IDisposable
    {
        public const string Secret = "general-chat-secret-0123456789";

        private const string Pipe = @"\\.\pipe\swreview-fixture";

        private readonly string _root;
        private readonly string _authSource;
        private readonly List<FakeSession> _sessions = new List<FakeSession>();
        private readonly List<TerminalSessionOptions> _started = new List<TerminalSessionOptions>();

        public Fixture()
        {
            _root = Path.Combine(
                Path.GetTempPath(), "SwReview.TerminalHost", Guid.NewGuid().ToString("N"));
            RunDirectory = Path.Combine(_root, "20260913-101500-terminal");
            Directory.CreateDirectory(RunDirectory);

            string reviewer = Path.Combine(_root, "reviewer");
            Directory.CreateDirectory(reviewer);
            string python = Path.Combine(_root, "python.exe");
            File.WriteAllText(python, "MZ");

            string codexHome = Path.Combine(_root, "dot-codex");
            Directory.CreateDirectory(codexHome);
            _authSource = Path.Combine(codexHome, "auth.json");
            File.WriteAllText(_authSource, "{\"tokens\":{\"access_token\":\"fixture\"}}");

            var writer = new CliProfileWriter(
                new StubToolService(new BridgeConfig(Pipe, Secret)),
                McpServerCommand.Resolve(python, reviewer, _ => null),
                _authSource);

            Channel = new RecordingChannel();
            Clis = new[]
            {
                Discovery.Ready(Path.Combine(_root, "codex.cmd")),
                Discovery.Gemini(Path.Combine(_root, "gemini.cmd")),
            };

            var options = new TerminalHostOptions(
                Channel,
                () => RunDirectory,
                runDirectory =>
                {
                    if (ProfileFailure != null)
                    {
                        throw ProfileFailure;
                    }

                    Profile = writer.WriteCodex(runDirectory);
                    return Profile;
                })
            {
                LocateClis = () => Clis,
                LastChoice = () => "codex",
                Secrets = () => new[] { Secret },
                Gate = (cli, profile, runDirectory) => ToolListingGate.ForCodex(() =>
                {
                    ProbeCalls++;
                    GateVerifiedBeforeStart = _started.Count == 0;
                    return Listing;
                }),
                // An hour, so the only chat-log ticks in these tests are the ones they ask for.
                ChatLogInterval = TimeSpan.FromHours(1),
                StartSession = sessionOptions =>
                {
                    // The first thing TerminalSession.Start does, and the fake has to do it too
                    // or the gate would be untested here: a refusal has to refuse before
                    // anything exists (ToolListingCheckTests proves the real one does it).
                    sessionOptions.ToolListing.Verify();

                    _started.Add(sessionOptions);
                    var session = new FakeSession(sessionOptions.WorkingDirectory ?? RunDirectory);
                    _sessions.Add(session);
                    return session;
                },
            };

            Host = new TerminalHost(options);
            Listing = ListingWith();
        }

        public TerminalHost Host { get; }

        /// <summary>When set, the profile writer throws it: a start failure whose message the
        /// host must redact before it reaches the page.</summary>
        public Exception? ProfileFailure { get; set; }

        public RecordingChannel Channel { get; }

        public string RunDirectory { get; }

        public string ChatLogPath => Path.Combine(RunDirectory, "chat-log.jsonl");

        /// <summary>What <see cref="CliLocator"/> would have found.</summary>
        public IReadOnlyList<CliDiscovery> Clis { get; set; }

        /// <summary>What the CLI reports it loaded, as the app-server probe would return it.</summary>
        public string Listing { get; set; } = string.Empty;

        public CodexProfile? Profile { get; private set; }

        public int ProbeCalls { get; private set; }

        public bool GateVerifiedBeforeStart { get; private set; }

        public IReadOnlyList<TerminalSessionOptions> Started => _started;

        public IReadOnlyList<FakeSession> Sessions => _sessions;

        /// <summary>An `mcpServerStatus/list` result carrying the whole allowlist, plus whatever
        /// extra tool names a test wants to slip past the gate.</summary>
        public static string ListingWith(params string[] extra)
        {
            var tools = new StringBuilder();
            foreach (string tool in CliProfileWriter.EnabledTools.Concat(extra))
            {
                if (tools.Length > 0)
                {
                    tools.Append(',');
                }

                tools.Append('"').Append(tool).Append("\":{\"name\":\"").Append(tool).Append("\"}");
            }

            return "{\"data\":[{\"name\":\"" + CliProfileWriter.ProfileName
                + "\",\"authStatus\":\"unsupported\",\"resources\":[],\"resourceTemplates\":[],"
                + "\"tools\":{" + tools + "}}],\"nextCursor\":null}";
        }

        public void DeleteAuth() => File.Delete(_authSource);

        public void WritePreviousProfile(string content)
        {
            string home = Path.Combine(
                RunDirectory, CliProfileWriter.ProfileFolderName, CliProfileWriter.CodexHomeFolderName);
            Directory.CreateDirectory(home);
            File.WriteAllText(Path.Combine(home, "config.toml"), content, new UTF8Encoding(false));
        }

        public void Dispose()
        {
            Host.Dispose();
            try
            {
                Directory.Delete(_root, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        private sealed class StubToolService : IToolServiceAccess
        {
            private readonly BridgeConfig _bridge;

            public StubToolService(BridgeConfig bridge) => _bridge = bridge;

            public BridgeConfig? GeneralChatBridge => _bridge;

            public string? DocumentPath => null;
        }
    }

    /// <summary>The `CliDiscovery` rows the tests need, built through the real locator.</summary>
    private static class Discovery
    {
        public static CliDiscovery Ready(string path)
        {
            File.WriteAllText(path, "@echo off\r\necho 0.115.0\r\n");
            return Locate("codex", path, "0.115.0");
        }

        public static CliDiscovery NotInstalled() => Locate("codex", null, null);

        /// <summary>Installed and new enough, and still deferred: the status the Terminal tab
        /// has to show as a sentence rather than as a Start button that fails.</summary>
        public static CliDiscovery Gemini(string path)
        {
            File.WriteAllText(path, "@echo off\r\necho 0.10.0\r\n");
            return Locate("gemini", path, "0.10.0");
        }

        /// <summary>
        /// Through <see cref="CliLocator"/> itself rather than by hand: the status rules - ready,
        /// deferred, not installed, too old - are the locator's, and a fixture that made its own
        /// would test the host against a world that cannot happen.
        /// </summary>
        private static CliDiscovery Locate(string name, string? path, string? version)
        {
            string? directory = path == null ? null : Path.GetDirectoryName(path);
            var locator = new CliLocator(
                directory == null ? Array.Empty<string>() : new[] { directory },
                _ => CliVersionOutput.FromText(version ?? string.Empty));

            return locator.Locate(name);
        }
    }

    /// <summary>A CLI that is not there: the pane cannot start one on a build machine.</summary>
    private sealed class FakeSession : ITerminalSession
    {
        public const int Pid = 4242;

        private readonly List<string> _written = new List<string>();

        public FakeSession(string workingDirectory) => WorkingDirectory = workingDirectory;

        public int ProcessId => Pid;

        public string WorkingDirectory { get; }

        public bool HasExited { get; private set; }

        public short Columns { get; private set; }

        public short Rows { get; private set; }

        public bool Stopped { get; private set; }

        public IReadOnlyList<string> Written => _written;

        public void Write(string data) => _written.Add(data);

        public void Resize(short columns, short rows)
        {
            Columns = columns;
            Rows = rows;
        }

        public void Stop()
        {
            Stopped = true;
            HasExited = true;
        }

        public void Dispose() => Stop();
    }

    /// <summary>The page, as far as the host can tell.</summary>
    private sealed class RecordingChannel : IPageChannel
    {
        private readonly object _gate = new object();
        private readonly List<string> _raw = new List<string>();

        public IReadOnlyList<string> Raw
        {
            get
            {
                lock (_gate)
                {
                    return _raw.ToList();
                }
            }
        }

        public IReadOnlyList<JsonElement> Messages => Raw
            .Select(json => JsonDocument.Parse(json).RootElement.Clone())
            .ToList();

        public void PostMessage(string json)
        {
            lock (_gate)
            {
                _raw.Add(json);
            }
        }

        /// <summary>Replies that echo one request's id.</summary>
        public IReadOnlyList<JsonElement> Replies(string id) => Messages
            .Where(message => message.TryGetProperty("id", out JsonElement value)
                && value.ValueKind == JsonValueKind.String
                && value.GetString() == id)
            .ToList();

        /// <summary>Everything sent with no request behind it.</summary>
        public IReadOnlyList<JsonElement> Unsolicited() => Messages
            .Where(message => !message.TryGetProperty("id", out JsonElement value)
                || value.ValueKind != JsonValueKind.String)
            .ToList();
    }
}
