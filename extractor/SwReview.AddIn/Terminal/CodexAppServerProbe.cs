using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Native;

namespace SwReview.AddIn.Terminal;

/// <summary>
/// The Codex startup tool listing could not be obtained.
///
/// Always a refusal, never a warning: <see cref="ToolListingGate"/> turns anything thrown by the
/// probe into a refused start, because a probe that failed means nobody checked what the CLI
/// loaded, which is indistinguishable from a check that failed (contracts/cli-profiles.md).
/// </summary>
public sealed class CodexAppServerException : Exception
{
    public CodexAppServerException(string message)
        : base(message)
    {
    }

    public CodexAppServerException(string message, Exception inner)
        : base(message, inner)
    {
    }
}

/// <summary>
/// T062's probe: asks a Codex CLI, over its app-server protocol, which MCP servers it connected
/// to and which tools it loaded from them.
///
/// It is what makes the gate real. <see cref="ToolListingGate.ForCodex"/> takes a
/// `Func&lt;string&gt;` that produces a listing, and without this the only callers of it were
/// tests with fixture lambdas: the parser, the comparison and the refusal all existed and
/// nothing ever fed them a running CLI.
///
/// <b>Why `codex app-server` and not `codex mcp list`.</b> `mcp list` and `mcp get` echo
/// `config.toml` back without ever starting a server, so a gate built on them would pass
/// happily on a CLI whose MCP server never came up - the failure the gate exists to catch. The
/// app-server's `mcpServerStatus/list` is the CLI reporting the servers it actually connected to
/// and the tools it actually loaded (`Fixtures/ToolListing/README.md` records the same exchange
/// as the capture procedure for the fixtures).
///
/// <b>Why a second process rather than reading the session's own output.</b> The terminal's CLI
/// is drawing a TUI into a pseudo-console; its startup listing is rendered text mixed with
/// cursor movement, and parsing it would be parsing a screenshot. The gate also has to run
/// *before* the session exists - a CLI that was started and then complained about is a CLI that
/// ran - so the listing has to come from somewhere else, and a short-lived child over the same
/// generated `CODEX_HOME` is the only place that answers the question being asked.
///
/// <b>The transport</b> is newline-delimited JSON-RPC on stdio (`--listen stdio://`, the
/// default), measured against codex-cli 0.115.0: one JSON document per line in each direction,
/// replies carrying the `id` of the request. Three messages: `initialize`, the `initialized`
/// notification, then `mcpServerStatus/list`, whose `result` is the listing.
///
/// Everything is bounded. The child is started suspended into a nested kill-on-close job like
/// every other child the pane starts, both its streams are drained on threads of their own so a
/// full pipe cannot wedge it, and the whole conversation is under one timeout after which the
/// job is closed and the start refused.
/// </summary>
public sealed class CodexAppServerProbe
{
    /// <summary>The subcommand that speaks the protocol.</summary>
    public const string Subcommand = "app-server";

    /// <summary>
    /// How long the whole conversation may take.
    ///
    /// Generous, because `mcpServerStatus/list` waits for the MCP servers themselves to start
    /// and the generated profile allows each one `startup_timeout_sec = 30`; a probe that timed
    /// out sooner than the CLI's own patience would refuse a terminal that was about to be
    /// perfectly good. It runs off the UI thread, so the cost of the generosity is a Start
    /// button that takes a moment, not a frozen SOLIDWORKS.
    /// </summary>
    public static readonly TimeSpan DefaultTimeout = TimeSpan.FromSeconds(60);

    private const int InitializeId = 1;
    private const int ListId = 2;

    /// <summary>What the app-server is told it is talking to. It appears in the CLI's own user
    /// agent string, which is the only place it is ever read.</summary>
    private const string ClientName = "swreview-pane";

    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        WriteIndented = false,
    };

    private readonly CliLaunch _launch;
    private readonly string? _workingDirectory;

    /// <param name="launch">The resolved Codex launch command - the same one
    /// <see cref="TerminalSession"/> will start, so a CLI that cannot be probed is a CLI that
    /// could not have been started either.</param>
    /// <param name="codexHome">The generated config home (`CliProfileWriter.WriteCodex`). The
    /// whole gate rests on this: a probe run against the engineer's own `%USERPROFILE%\.codex`
    /// would report the toolset of a CLI that is not the one being started.</param>
    /// <param name="workingDirectory">The run folder, so the probe and the session resolve
    /// relative paths in the generated config the same way.</param>
    public CodexAppServerProbe(CliLaunch launch, string codexHome, string? workingDirectory = null)
    {
        _launch = launch ?? throw new ArgumentNullException(nameof(launch));
        if (string.IsNullOrWhiteSpace(codexHome))
        {
            throw new ArgumentException(
                "the generated Codex home is required: a probe without one reports the tools of "
                + "the engineer's own Codex configuration rather than of the profile being "
                + "started",
                nameof(codexHome));
        }

        _workingDirectory = workingDirectory;
        Environment[CliProfileWriter.HomeVariable] = codexHome;
    }

    /// <summary>Added to the child's environment. `CODEX_HOME` is set by the constructor.</summary>
    public IDictionary<string, string> Environment { get; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>The host's kill-on-close job, so the probe cannot outlive SOLIDWORKS either.</summary>
    public JobObject? Job { get; set; }

    public TimeSpan Timeout { get; set; } = DefaultTimeout;

    /// <summary>
    /// Starts `&lt;codex&gt; app-server`, holds the conversation, and returns the `result` of
    /// `mcpServerStatus/list` as JSON text - what <see cref="ToolListing.FromCodex"/> parses.
    ///
    /// This is the `Func&lt;string&gt;` <see cref="ToolListingGate.ForCodex"/> is given.
    /// </summary>
    /// <exception cref="CodexAppServerException">The child would not start, said nothing, ended
    /// early, or answered with an error. Every one of them refuses the terminal start.</exception>
    public string Run()
    {
        var info = new ChildProcessStartInfo(_launch.Executable, _launch.With(Subcommand).Arguments)
        {
            WorkingDirectory = _workingDirectory,
            RedirectStandardInput = true,
        };
        foreach (KeyValuePair<string, string> variable in Environment)
        {
            info.Environment[variable.Key] = variable.Value;
        }

        ChildProcess? child = null;
        JobObject? tree = null;
        var stderr = new StringBuilder();
        try
        {
            try
            {
                // A nested job of its own, like CliLocator.Probe: a `.cmd` shim is `cmd.exe`
                // starting `node.exe`, and `codex app-server` starts the MCP servers named in
                // the generated config - so what has to end when this returns is the tree.
                tree = new JobObject();
                child = ChildProcess.StartSuspended(info, Job, tree);
            }
            catch (Exception failure)
            {
                throw new CodexAppServerException(
                    $"`{_launch.ToolPath} {Subcommand}` could not be started: {failure.Message}",
                    failure);
            }

            // Drained, not ignored: a child whose stderr pipe fills blocks on its next write,
            // and the last few lines of it are the only explanation a failed probe ever has.
            Drain(child.StandardError, stderr);

            child.Resume();

            StreamWriter input = child.StandardInput
                ?? throw new CodexAppServerException(
                    "the app-server child was started without a standard input pipe, so the "
                    + "JSON-RPC handshake cannot be sent.");

            try
            {
                return ReadListing(child.StandardOutput, input, Timeout);
            }
            catch (CodexAppServerException failure)
            {
                string trailing = Tail(stderr);
                throw trailing.Length == 0
                    ? failure
                    : new CodexAppServerException(
                        failure.Message + " The CLI printed: " + trailing, failure);
            }
        }
        finally
        {
            // The job first, so the shim, the CLI and the MCP servers all go; the child handle
            // after it. Neither may throw on the way out of a refused start.
            try
            {
                tree?.Dispose();
            }
            catch (Exception)
            {
            }

            try
            {
                child?.Dispose();
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>
    /// The conversation on its own, without a process: write `initialize`, wait for its reply,
    /// send `initialized`, ask `mcpServerStatus/list`, return its `result`.
    ///
    /// Separated from <see cref="Run"/> so the protocol can be tested against a canned
    /// transcript on every machine that builds this solution, rather than only on one with the
    /// Codex CLI installed.
    /// </summary>
    /// <param name="fromServer">The app-server's stdout, one JSON document per line.</param>
    /// <param name="toServer">The app-server's stdin.</param>
    /// <param name="timeout">The budget for the whole exchange.</param>
    public static string ReadListing(TextReader fromServer, TextWriter toServer, TimeSpan timeout)
    {
        if (fromServer == null)
        {
            throw new ArgumentNullException(nameof(fromServer));
        }

        if (toServer == null)
        {
            throw new ArgumentNullException(nameof(toServer));
        }

        var deadline = Stopwatch.StartNew();
        using (var replies = new Replies(fromServer))
        {
            Send(toServer, new Dictionary<string, object?>
            {
                { "jsonrpc", "2.0" },
                { "id", InitializeId },
                { "method", "initialize" },
                {
                    "params",
                    new Dictionary<string, object?>
                    {
                        {
                            "clientInfo",
                            new Dictionary<string, object?>
                            {
                                { "name", ClientName },
                                { "version", Version() },
                            }
                        },
                    }
                },
            });

            Await(replies, InitializeId, timeout, deadline);

            // A notification: no id, and no reply to wait for. Sending it as a request would
            // hang the probe on an answer that never comes.
            Send(toServer, new Dictionary<string, object?>
            {
                { "jsonrpc", "2.0" },
                { "method", "initialized" },
                { "params", new Dictionary<string, object?>() },
            });

            Send(toServer, new Dictionary<string, object?>
            {
                { "jsonrpc", "2.0" },
                { "id", ListId },
                { "method", "mcpServerStatus/list" },
                { "params", new Dictionary<string, object?>() },
            });

            return Await(replies, ListId, timeout, deadline);
        }
    }

    /// <summary>Writes one JSON document and the newline that terminates it.</summary>
    private static void Send(TextWriter toServer, IDictionary<string, object?> message)
    {
        try
        {
            // "\n" rather than WriteLine: the transport is newline-delimited JSON and this
            // process's line ending is CRLF, which would put a stray CR inside the framing.
            toServer.Write(JsonSerializer.Serialize(message, JsonOptions));
            toServer.Write('\n');
            toServer.Flush();
        }
        catch (Exception failure)
        {
            throw new CodexAppServerException(
                "the Codex app-server stopped reading before the tool listing could be asked "
                + $"for: {failure.Message}",
                failure);
        }
    }

    /// <summary>Reads until the reply with <paramref name="id"/> arrives, the server ends, or
    /// the budget is spent.</summary>
    private static string Await(Replies replies, int id, TimeSpan timeout, Stopwatch elapsed)
    {
        while (true)
        {
            TimeSpan left = timeout - elapsed.Elapsed;
            if (left <= TimeSpan.Zero)
            {
                throw TimedOut(id, timeout);
            }

            string? line = replies.Next(left);
            if (line == null)
            {
                throw replies.Ended
                    ? new CodexAppServerException(
                        "the Codex app-server ended before it answered "
                        + $"{Method(id)}. Its tool listing is what the terminal start is gated "
                        + "on, so the terminal was not started.")
                    : TimedOut(id, timeout);
            }

            JsonElement message;
            try
            {
                using (JsonDocument document = JsonDocument.Parse(line))
                {
                    message = document.RootElement.Clone();
                }
            }
            catch (JsonException)
            {
                // Not a JSON-RPC line at all. A log line on stdout is not a protocol failure -
                // the reply being waited for may still be behind it.
                continue;
            }

            if (message.ValueKind != JsonValueKind.Object
                || !message.TryGetProperty("id", out JsonElement replyId)
                || replyId.ValueKind != JsonValueKind.Number
                || !replyId.TryGetInt32(out int value)
                || value != id)
            {
                // A notification, or the answer to a request that is not this one.
                continue;
            }

            if (message.TryGetProperty("error", out JsonElement error)
                && error.ValueKind != JsonValueKind.Null)
            {
                throw new CodexAppServerException(
                    $"the Codex app-server refused {Method(id)}: {Describe(error)}");
            }

            if (!message.TryGetProperty("result", out JsonElement result))
            {
                throw new CodexAppServerException(
                    $"the Codex app-server's reply to {Method(id)} carried neither a result nor "
                    + "an error.");
            }

            return result.GetRawText();
        }
    }

    private static CodexAppServerException TimedOut(int id, TimeSpan timeout) =>
        new CodexAppServerException(
            $"the Codex app-server did not answer {Method(id)} within "
            + $"{timeout.TotalSeconds:0.#} seconds. The terminal is not started on a tool "
            + "listing that could not be read.");

    private static string Method(int id) =>
        id == InitializeId ? "`initialize`" : "`mcpServerStatus/list`";

    private static string Describe(JsonElement error)
    {
        if (error.ValueKind == JsonValueKind.Object
            && error.TryGetProperty("message", out JsonElement message)
            && message.ValueKind == JsonValueKind.String)
        {
            return message.GetString() ?? error.GetRawText();
        }

        return error.GetRawText();
    }

    private static string Version() =>
        typeof(CodexAppServerProbe).Assembly.GetName().Version?.ToString() ?? "0.0.0";

    /// <summary>The last of what the child printed on stderr, for a failure message.</summary>
    private static string Tail(StringBuilder stderr)
    {
        string text;
        lock (stderr)
        {
            text = stderr.ToString();
        }

        text = text.Replace("\r", " ").Replace("\n", " ").Trim();
        return text.Length <= 300 ? text : text.Substring(text.Length - 300);
    }

    private static void Drain(StreamReader reader, StringBuilder into)
    {
        var thread = new Thread(() =>
        {
            try
            {
                string? line;
                while ((line = reader.ReadLine()) != null)
                {
                    lock (into)
                    {
                        into.AppendLine(line);
                    }
                }
            }
            catch (Exception)
            {
                // The child is gone and took the pipe with it. Nothing on a background thread
                // may throw: it would take SOLIDWORKS down with it.
            }
        })
        {
            IsBackground = true,
            Name = "swreview-codex-probe-stderr",
        };
        thread.Start();
    }

    /// <summary>
    /// The server's lines, read on a thread of its own so the wait for one can be bounded.
    ///
    /// `TextReader.ReadLine` blocks until there is a line or the stream ends, and on a pipe
    /// belonging to a CLI that is thinking about it that is unbounded. The read therefore
    /// happens somewhere the probe can walk away from.
    /// </summary>
    private sealed class Replies : IDisposable
    {
        private readonly BlockingCollection<string> _lines = new BlockingCollection<string>();
        private readonly Thread _thread;

        private volatile bool _ended;

        public Replies(TextReader reader)
        {
            _thread = new Thread(() =>
            {
                try
                {
                    string? line;
                    while ((line = reader.ReadLine()) != null)
                    {
                        _lines.Add(line);
                    }
                }
                catch (Exception)
                {
                    // A closed pipe is the end of the conversation, not a fault to report: the
                    // caller sees it as "ended before answering", which is the honest account.
                }
                finally
                {
                    _ended = true;
                    try
                    {
                        _lines.CompleteAdding();
                    }
                    catch (Exception)
                    {
                    }
                }
            })
            {
                IsBackground = true,
                Name = "swreview-codex-probe",
            };
            _thread.Start();
        }

        /// <summary>Whether the server's stdout reached end of file.</summary>
        public bool Ended => _ended;

        /// <summary>The next line, or null on a timeout or the end of the stream.</summary>
        public string? Next(TimeSpan within)
        {
            try
            {
                return _lines.TryTake(out string line, (int)Math.Max(0, within.TotalMilliseconds))
                    ? line
                    : null;
            }
            catch (InvalidOperationException)
            {
                // The collection was completed - or disposed, which is an
                // ObjectDisposedException and so one of these - while we were waiting: either
                // way the server has nothing more to say.
                return null;
            }
        }

        public void Dispose()
        {
            // The reading thread is a background thread over a stream the caller owns; it ends
            // when that stream does. Nothing here waits for it: the whole point of the class is
            // that a server which never answers cannot hold the Terminal tab.
            try
            {
                _lines.Dispose();
            }
            catch (Exception)
            {
            }
        }
    }
}
