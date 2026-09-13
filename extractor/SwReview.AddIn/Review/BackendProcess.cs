using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Native;
using SwReview.AddIn.Settings;

namespace SwReview.AddIn.Review;

/// <summary>The executable and leading arguments that run `swreview`, before the subcommand.</summary>
public sealed class BackendCommand
{
    public BackendCommand(string executable, IEnumerable<string> arguments)
    {
        if (string.IsNullOrWhiteSpace(executable))
        {
            throw new ArgumentException("an executable path is required", nameof(executable));
        }

        Executable = executable;
        Arguments = (arguments ?? Enumerable.Empty<string>()).ToList();
    }

    public string Executable { get; }

    public IReadOnlyList<string> Arguments { get; }

    public override string ToString() =>
        ChildProcess.BuildCommandLine(Executable, Arguments);
}

/// <summary>Where the backend lives once it has handshaken.</summary>
public sealed class BackendEndpoint
{
    public BackendEndpoint(int port, string token)
    {
        Port = port;
        Token = token ?? throw new ArgumentNullException(nameof(token));
    }

    public int Port { get; }

    /// <summary>The bearer token for every request. Never put it in a URL (chat-api.md).</summary>
    public string Token { get; }

    /// <summary>`http://127.0.0.1:&lt;port&gt;` - loopback only, which is what the server binds.</summary>
    public string Origin => "http://127.0.0.1:" + Port.ToString(CultureInfo.InvariantCulture);
}

/// <summary>Everything <see cref="BackendProcess.Start"/> needs.</summary>
public sealed class BackendStartOptions
{
    public BackendStartOptions(BackendCommand command, string logPath)
    {
        Command = command ?? throw new ArgumentNullException(nameof(command));
        LogPath = logPath ?? throw new ArgumentNullException(nameof(logPath));
    }

    public BackendCommand Command { get; }

    /// <summary>Where the child's stderr is copied, redacted. Named in every start failure so
    /// an engineer has one place to look.</summary>
    public string LogPath { get; }

    /// <summary>`--run-root`; the server refuses any `run_dir` outside it (chat-api.md).</summary>
    public string? RunRoot { get; set; }

    /// <summary>`--allow-origin`; the page's virtual host, fixed by pane-host-messages.md.</summary>
    public string AllowOrigin { get; set; } = "https://swreview.invalid";

    public string? WorkingDirectory { get; set; }

    /// <summary>Credentials and endpoint overrides. The only channel a key travels on (FR-015).</summary>
    public IDictionary<string, string> Environment { get; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>Values masked in the log and in every error text (FR-015).</summary>
    public IList<string> Secrets { get; } = new List<string>();

    /// <summary>The kill-on-close job the child joins before its first thread runs.</summary>
    public JobObject? Job { get; set; }

    /// <summary>
    /// How long <see cref="BackendProcess.Dispose"/> waits for the backend to shut itself down
    /// after being asked, before terminating it.
    ///
    /// Five seconds because the work the backend does in that window is bounded and small -
    /// finalize each live chat, write `session.json`, close the event sinks - and because this
    /// runs on the add-in's unload path with SOLIDWORKS waiting for it: a graceful stop that
    /// can hang is worse than no graceful stop at all.
    /// </summary>
    public TimeSpan StopGrace { get; set; } = TimeSpan.FromSeconds(5);

    public TimeSpan HandshakeTimeout { get; set; } = TimeSpan.FromSeconds(60);

    public TimeSpan HealthTimeout { get; set; } = TimeSpan.FromSeconds(30);

    /// <summary>`GET /health` with the bearer token; injectable so the tests need no server.</summary>
    public Func<string, string, bool>? HealthProbe { get; set; }
}

/// <summary>The backend could not be started. The message is safe to show and to log.</summary>
public sealed class BackendStartException : Exception
{
    public BackendStartException(string message, int? processId = null, Exception? inner = null)
        : base(message, inner)
    {
        ProcessId = processId;
    }

    /// <summary>The child that failed, when one was created. It has already been stopped.</summary>
    public int? ProcessId { get; }
}

/// <summary>
/// The Python chat backend as a child process: `swreview chat serve --port 0`.
///
/// The handshake is the whole contract with it. The first stdout line is
/// `{"port": ..., "token": ...}` and nothing else is ever written to stdout, so this class
/// reads exactly one line, parses it, and from then on drains stdout into the log - draining
/// matters, because a child whose stdout pipe fills up blocks forever on its next write.
///
/// Four rules are enforced here rather than left to the caller:
/// the key is in the environment block and never on the command line (FR-015); the child is
/// in a kill-on-close job object before its first thread runs, so a SOLIDWORKS crash cannot
/// leave a server holding a port; a backend that never answers becomes a
/// <see cref="BackendStartException"/> naming the command and the log rather than a pane that
/// waits forever; and stopping means *asking first*.
///
/// That last one is the one that is easy to leave out. `TerminateProcess` delivers no signal,
/// so a backend that is only ever terminated never runs the uvicorn lifespan that finalizes
/// every live chat - `turn.ended {reason: "error"}`, `session.ended`, `session.json` with an
/// `ended_at` (chat-api.md, "Shutdown and settings changes"). Closing SOLIDWORKS mid-turn
/// would leave that session with no ended time for ever, which is what FR-008 forbids. So
/// <see cref="Dispose"/> sends a console break, waits <see cref="BackendStartOptions.StopGrace"/>,
/// and only then terminates.
///
/// The whole *tree* is what gets stopped, not the process we hold a handle to. The pilot
/// launcher is `uv run --project &lt;reviewer&gt; swreview chat serve`, so the HTTP server is a
/// grandchild of uv.exe; each backend therefore owns a nested kill-on-close job, closed on
/// dispose, so a restart for a settings change cannot leave the previous server alive holding
/// its loopback port and its copy of the key (FR-019).
/// </summary>
public sealed class BackendProcess : IDisposable
{
    private readonly ChildProcess _child;
    private readonly JobObject _tree;
    private readonly TimeSpan _stopGrace;
    private readonly StreamWriter _log;
    private readonly object _logGate;
    private readonly IReadOnlyList<string> _secrets;
    private bool _disposed;

    private BackendProcess(
        ChildProcess child,
        JobObject tree,
        TimeSpan stopGrace,
        StreamWriter log,
        object logGate,
        IReadOnlyList<string> secrets,
        BackendEndpoint endpoint,
        string logPath)
    {
        _child = child;
        _tree = tree;
        _stopGrace = stopGrace;
        _log = log;
        _logGate = logGate;
        _secrets = secrets;
        Endpoint = endpoint;
        LogPath = logPath;
        StartedAt = DateTimeOffset.Now;
    }

    public BackendEndpoint Endpoint { get; }

    public int Port => Endpoint.Port;

    public string Token => Endpoint.Token;

    public string Origin => Endpoint.Origin;

    public int ProcessId => _child.ProcessId;

    public string LogPath { get; }

    public DateTimeOffset StartedAt { get; }

    public bool HasExited => _child.HasExited;

    /// <summary>True once `/health` has answered and while the process is still alive.</summary>
    public bool Healthy => !_disposed && !_child.HasExited;

    /// <summary>
    /// Starts the backend and returns once it has printed its handshake line and answered
    /// `/health`. Throws <see cref="BackendStartException"/> otherwise, having stopped the
    /// child first.
    /// </summary>
    public static BackendProcess Start(BackendStartOptions options)
    {
        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        string[] secrets = options.Secrets.Where(secret => !string.IsNullOrWhiteSpace(secret)).ToArray();
        var gate = new object();
        StreamWriter log = OpenLog(options.LogPath);

        // Deliberately not disposed: the reader threads outlive a failed start and would set a
        // disposed event. They are background threads on pipes the child's exit closes.
        var handshakeSeen = new ManualResetEventSlim(false);
        var stderrDrained = new ManualResetEventSlim(false);

        ChildProcess? child = null;
        // This backend's own job, nested inside the host's. Closing it is what ends the
        // grandchildren `uv run` leaves between us and the server.
        JobObject? tree = null;
        string? handshake = null;
        bool stdoutEnded = false;

        try
        {
            var info = new ChildProcessStartInfo(options.Command.Executable, Arguments(options))
            {
                WorkingDirectory = options.WorkingDirectory,
            };
            foreach (KeyValuePair<string, string> variable in options.Environment)
            {
                info.Environment[variable.Key] = variable.Value;
            }

            Write(log, gate, secrets, "starting " + options.Command);

            // StartSuspended puts the child in both jobs before returning, so it is a member
            // before a single instruction of it runs (T050).
            tree = new JobObject();
            child = ChildProcess.StartSuspended(info, options.Job, tree);

            Pump(
                child.StandardError,
                line => Write(log, gate, secrets, line),
                () => stderrDrained.Set());
            Pump(
                child.StandardOutput,
                line =>
                {
                    bool first;
                    lock (gate)
                    {
                        first = handshake == null;
                        if (first)
                        {
                            handshake = line;
                        }
                    }

                    if (first)
                    {
                        handshakeSeen.Set();
                    }
                    else
                    {
                        // The contract forbids a second stdout line. Log it and keep draining:
                        // a child whose stdout pipe fills up blocks forever on its next write.
                        Write(log, gate, secrets, "unexpected stdout after the handshake: " + line);
                    }
                },
                () =>
                {
                    lock (gate)
                    {
                        stdoutEnded = true;
                    }

                    handshakeSeen.Set();
                });

            child.Resume();

            if (!handshakeSeen.Wait(options.HandshakeTimeout))
            {
                throw Fail(
                    child,
                    log,
                    gate,
                    secrets,
                    options,
                    "the backend did not print its {port, token} line within "
                    + $"{options.HandshakeTimeout.TotalSeconds:0.#} seconds");
            }

            string? firstLine;
            bool ended;
            lock (gate)
            {
                firstLine = handshake;
                ended = stdoutEnded;
            }

            if (firstLine == null)
            {
                child.WaitForExit(2000);
                throw Fail(
                    child,
                    log,
                    gate,
                    secrets,
                    options,
                    ended && child.HasExited
                        ? $"the backend exited with code {child.ExitCode} before printing its handshake line"
                        : "the backend closed stdout before printing its handshake line");
            }

            BackendEndpoint? endpoint = ParseHandshake(firstLine);
            if (endpoint == null)
            {
                // The line itself is never echoed: a misconfigured backend that prints the
                // request it failed on would put the key in the message (FR-015).
                throw Fail(
                    child,
                    log,
                    gate,
                    secrets,
                    options,
                    "the backend's first stdout line was not the {port, token} handshake");
            }

            var backend = new BackendProcess(
                child, tree, options.StopGrace, log, gate, secrets, endpoint, options.LogPath);
            child = null;
            tree = null;

            try
            {
                backend.WaitForHealth(options);
            }
            catch
            {
                backend.Dispose();
                throw;
            }

            return backend;
        }
        catch (Exception failure)
        {
            int? processId = child?.ProcessId;
            child?.Dispose();
            // Closing the job takes anything the failed child managed to start with it; a
            // start that got as far as spawning a server and then failed its health probe must
            // not leave that server behind.
            tree?.Dispose();

            // Let whatever the child said on stderr reach the log before it closes: that text
            // is the only explanation an engineer gets for "it did not start".
            stderrDrained.Wait(TimeSpan.FromSeconds(2));
            lock (gate)
            {
                try
                {
                    log.Dispose();
                }
                catch (IOException)
                {
                }
            }

            if (failure is BackendStartException)
            {
                throw;
            }

            throw new BackendStartException(
                "the backend could not be started: "
                + Redaction.Redact(failure.Message, secrets)
                + $" (log: {options.LogPath})",
                processId,
                failure);
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        RequestStop();
        // Kills the child if the request did not, and closes our handles to it...
        _child.Dispose();
        // ...and closing the job ends whatever the child started and did not take with it.
        _tree.Dispose();
        lock (_logGate)
        {
            try
            {
                _log.WriteLine($"[{DateTimeOffset.Now:O}] backend stopped");
                _log.Dispose();
            }
            catch (ObjectDisposedException)
            {
            }
            catch (IOException)
            {
            }
        }
    }

    /// <summary>
    /// Sends the shutdown signal and waits out the grace period, so the backend gets to run
    /// the lifespan that gives every live chat an `ended_at` (FR-008).
    ///
    /// Nothing here is allowed to throw or to hang: it runs on the add-in's unload path.
    /// A backend that ignores the signal is simply terminated when the grace period is up, and
    /// the log says which of the two happened - that line is the only evidence an engineer has
    /// when a session did turn up without an ended time.
    /// </summary>
    private void RequestStop()
    {
        try
        {
            if (_child.HasExited || !_child.TryRequestStop())
            {
                return;
            }

            Write(_log, _logGate, _secrets, "asked the backend to shut down (Ctrl+Break)");
            if (_child.WaitForExit((int)_stopGrace.TotalMilliseconds))
            {
                Write(_log, _logGate, _secrets, "the backend shut itself down");
                return;
            }

            Write(
                _log,
                _logGate,
                _secrets,
                $"the backend did not shut down within {_stopGrace.TotalSeconds:0.#} seconds; "
                + "terminating it - a session it was mid-turn on may have no ended time");
        }
        catch (Exception failure)
        {
            // Deliberately broad: this is a courtesy on the way to a guaranteed terminate, and
            // an exception escaping Dispose here would take the add-in's unload with it.
            Write(
                _log,
                _logGate,
                _secrets,
                "asking the backend to shut down failed: " + failure.Message);
        }
    }

    /// <summary>The parsed handshake, or null when the line was not one.</summary>
    internal static BackendEndpoint? ParseHandshake(string line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return null;
        }

        try
        {
            using (JsonDocument document = JsonDocument.Parse(line))
            {
                JsonElement root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object
                    || !root.TryGetProperty("port", out JsonElement port)
                    || !root.TryGetProperty("token", out JsonElement token)
                    || port.ValueKind != JsonValueKind.Number
                    || token.ValueKind != JsonValueKind.String
                    || !port.TryGetInt32(out int number)
                    || number <= 0
                    || number > 65535)
                {
                    return null;
                }

                string? text = token.GetString();
                return string.IsNullOrEmpty(text) ? null : new BackendEndpoint(number, text!);
            }
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static IEnumerable<string> Arguments(BackendStartOptions options)
    {
        foreach (string leading in options.Command.Arguments)
        {
            yield return leading;
        }

        yield return "chat";
        yield return "serve";
        yield return "--port";
        yield return "0";

        if (!string.IsNullOrWhiteSpace(options.AllowOrigin))
        {
            yield return "--allow-origin";
            yield return options.AllowOrigin;
        }

        if (!string.IsNullOrWhiteSpace(options.RunRoot))
        {
            yield return "--run-root";
            yield return options.RunRoot!;
        }
    }

    private static StreamWriter OpenLog(string path)
    {
        string? directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory!);
        }

        var stream = new FileStream(
            path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete);
        return new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true };
    }

    private static void Write(StreamWriter log, object gate, IReadOnlyList<string> secrets, string line)
    {
        lock (gate)
        {
            try
            {
                log.WriteLine($"[{DateTimeOffset.Now:O}] {Redaction.Redact(line, secrets)}");
            }
            catch (ObjectDisposedException)
            {
            }
            catch (IOException)
            {
            }
        }
    }

    /// <summary>Reads <paramref name="reader"/> to end on a background thread.</summary>
    private static void Pump(StreamReader reader, Action<string> onLine, Action onEnd)
    {
        var thread = new Thread(() =>
        {
            try
            {
                string? line;
                while ((line = reader.ReadLine()) != null)
                {
                    onLine(line);
                }
            }
            catch (Exception)
            {
                // The pipe closed under us, or the log did: the child is gone, which onEnd
                // reports. Nothing here may throw - an unhandled exception on a background
                // thread would take SOLIDWORKS down with it.
            }
            finally
            {
                try
                {
                    onEnd();
                }
                catch (Exception)
                {
                }
            }
        })
        {
            IsBackground = true,
            Name = "swreview-backend-reader",
        };
        thread.Start();
    }

    private static BackendStartException Fail(
        ChildProcess child,
        StreamWriter log,
        object gate,
        IReadOnlyList<string> secrets,
        BackendStartOptions options,
        string why)
    {
        int processId = child.ProcessId;
        Write(log, gate, secrets, why);
        child.Kill();
        return new BackendStartException(
            $"{why}. Command: {Redaction.Redact(options.Command.ToString(), secrets)}. "
            + $"See the log at {options.LogPath}.",
            processId);
    }

    private void WaitForHealth(BackendStartOptions options)
    {
        Func<string, string, bool> probe = options.HealthProbe ?? DefaultHealthProbe;
        DateTime deadline = DateTime.UtcNow + options.HealthTimeout;
        Exception? last = null;

        while (true)
        {
            if (_child.HasExited)
            {
                throw new BackendStartException(
                    $"the backend exited with code {_child.ExitCode} before answering /health. "
                    + $"See the log at {LogPath}.",
                    ProcessId,
                    last);
            }

            try
            {
                if (probe(Origin, Token))
                {
                    Write(_log, _logGate, _secrets, $"backend healthy on {Origin} (pid {ProcessId})");
                    return;
                }
            }
            catch (Exception failure)
            {
                last = failure;
            }

            if (DateTime.UtcNow >= deadline)
            {
                throw new BackendStartException(
                    $"the backend did not answer /health within {options.HealthTimeout.TotalSeconds:0.#} "
                    + $"seconds. See the log at {LogPath}.",
                    ProcessId,
                    last);
            }

            Thread.Sleep(100);
        }
    }

    /// <summary>`GET /health` on loopback with the bearer token, never with it in the URL.</summary>
    private static bool DefaultHealthProbe(string origin, string token)
    {
        var request = (HttpWebRequest)WebRequest.Create(origin + "/health");
        request.Method = "GET";
        request.Timeout = 2000;
        request.ReadWriteTimeout = 2000;
        // A corporate proxy must never be consulted for 127.0.0.1, and the default proxy
        // resolution can add seconds per attempt.
        request.Proxy = null;
        request.Headers["Authorization"] = "Bearer " + token;
        try
        {
            using (var response = (HttpWebResponse)request.GetResponse())
            {
                return response.StatusCode == HttpStatusCode.OK;
            }
        }
        catch (WebException)
        {
            return false;
        }
    }
}

/// <summary>
/// `settings.save` while a turn is running. A running turn owns process state that is not on
/// disk, so restarting the backend under it would lose the turn silently (chat-api.md,
/// "Shutdown and settings changes"); the pane refuses instead and offers Save again when the
/// turn ends.
/// </summary>
public sealed class TurnRunningException : Exception
{
    public TurnRunningException()
        : base("a review turn is running; settings are saved once it finishes. "
            + "Stop the turn, or wait for it to end, and press Save again.")
    {
    }

    /// <summary>The `error_class` the page is given, fixed by pane-host-messages.md.</summary>
    public string ErrorClass => "TurnRunning";
}

/// <summary>
/// Owns the one backend process the pane has, and the single rule about replacing it: never
/// while a turn is running.
///
/// The rule lives here rather than in <see cref="ReviewHost"/> so there is one place that can
/// say no - the host's `settings.save` handler and any future caller (an add-in reload, a
/// crash restart) go through the same gate.
/// </summary>
public sealed class BackendSupervisor : IDisposable
{
    private readonly Func<bool> _anyTurnRunning;
    private bool _disposed;

    public BackendSupervisor(Func<bool> anyTurnRunning)
    {
        _anyTurnRunning = anyTurnRunning ?? throw new ArgumentNullException(nameof(anyTurnRunning));
    }

    /// <summary>The running backend, or null before the first start and after a failed one.</summary>
    public BackendProcess? Current { get; private set; }

    /// <summary>Stops whatever is running and starts a new backend.</summary>
    public BackendProcess Start(BackendStartOptions options)
    {
        ThrowIfDisposed();
        Stop();
        // Stop first, then start: two backends alive at once would each hold a copy of the key
        // in their environment, and the second would be started before we know the first is gone.
        Current = BackendProcess.Start(options);
        return Current;
    }

    /// <summary>Restarts for a settings change, or refuses because a turn is running.</summary>
    public BackendProcess Restart(BackendStartOptions options)
    {
        ThrowIfDisposed();
        if (_anyTurnRunning())
        {
            throw new TurnRunningException();
        }

        return Start(options);
    }

    public void Stop()
    {
        Current?.Dispose();
        Current = null;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        Stop();
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(BackendSupervisor));
        }
    }
}
