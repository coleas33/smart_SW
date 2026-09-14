using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;

namespace SwReview.AddIn.Terminal;

/// <summary>
/// The `terminal.output` coalescing rule, on its own so it can be reasoned about and tested
/// on its own (contracts/pane-host-messages.md): bytes go in, and at most one post leaves per
/// <see cref="Interval"/> or per <see cref="Threshold"/> bytes, whichever comes first, and
/// nothing is dropped.
///
/// Both halves matter and for opposite reasons. Without the threshold a CLI printing a large
/// file would build an unbounded buffer in memory and land on the page as one enormous
/// message. Without the interval a two-byte prompt would sit in the buffer waiting for 32 KB
/// that never comes, and the engineer would watch a terminal that types nothing back.
///
/// What it replaces is a post per read, which on this path is thousands of
/// `PostWebMessageAsJson` calls for a megabyte - each one a marshalled call onto the
/// SOLIDWORKS UI thread, which is the same thread that draws SOLIDWORKS.
/// </summary>
public sealed class OutputCoalescer : IDisposable
{
    private readonly object _gate = new object();

    /// <summary>Held across a post, so two threads cannot interleave chunks and hand the
    /// terminal its bytes out of order - which in a VT stream is corruption, not a delay.</summary>
    private readonly object _postGate = new object();

    private readonly Action<byte[]> _post;
    private readonly MemoryStream _buffer = new MemoryStream();
    private readonly Timer _timer;

    private bool _scheduled;
    private bool _disposed;

    /// <param name="interval">How long a byte may wait for company. ~16 ms - one frame - is
    /// the contract's figure.</param>
    /// <param name="threshold">The buffer size that posts immediately. 32 KB in the contract.</param>
    /// <param name="post">Called with each chunk, in order. Must not block for long: it runs
    /// on the read loop's thread or on a timer thread.</param>
    public OutputCoalescer(TimeSpan interval, int threshold, Action<byte[]> post)
    {
        if (interval <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(interval), "a coalescing interval has to be positive");
        }

        if (threshold <= 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(threshold), "a coalescing threshold has to be positive");
        }

        Interval = interval;
        Threshold = threshold;
        _post = post ?? throw new ArgumentNullException(nameof(post));
        _timer = new Timer(_ => Flush(), null, Timeout.Infinite, Timeout.Infinite);
    }

    public TimeSpan Interval { get; }

    public int Threshold { get; }

    /// <summary>Takes <paramref name="count"/> bytes, and posts if the rule says to.</summary>
    public void Append(byte[] buffer, int offset, int count)
    {
        if (buffer == null)
        {
            throw new ArgumentNullException(nameof(buffer));
        }

        if (offset < 0 || count < 0 || offset + count > buffer.Length)
        {
            throw new ArgumentOutOfRangeException(nameof(count), "the range is not inside the buffer");
        }

        if (count == 0)
        {
            return;
        }

        bool full;
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            _buffer.Write(buffer, offset, count);
            full = _buffer.Length >= Threshold;
            if (!full && !_scheduled)
            {
                _scheduled = true;
                _timer.Change((int)Interval.TotalMilliseconds, Timeout.Infinite);
            }
        }

        if (full)
        {
            Flush();
        }
    }

    /// <summary>Posts whatever is buffered, if anything. Safe to call from any thread and on
    /// an empty buffer.</summary>
    public void Flush()
    {
        lock (_postGate)
        {
            byte[] chunk;
            lock (_gate)
            {
                if (_buffer.Length == 0)
                {
                    // Nothing to send, and no timer to leave armed for an empty buffer.
                    CancelTimer();
                    return;
                }

                chunk = _buffer.ToArray();
                _buffer.SetLength(0);
                CancelTimer();
            }

            _post(chunk);
        }
    }

    /// <summary>
    /// Stops the timer. Deliberately does not flush: the caller decides what the last message
    /// before `terminal.exited` is, and a flush from a finalizing timer would land after it.
    /// </summary>
    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            CancelTimer();
        }

        _timer.Dispose();
    }

    private void CancelTimer()
    {
        _scheduled = false;
        try
        {
            _timer.Change(Timeout.Infinite, Timeout.Infinite);
        }
        catch (ObjectDisposedException)
        {
        }
    }
}

/// <summary>Everything <see cref="TerminalSession.Start"/> needs.</summary>
public sealed class TerminalSessionOptions
{
    /// <param name="launch">The resolved launch command.</param>
    /// <param name="channel">Where `terminal.output` and `terminal.exited` go.</param>
    /// <param name="toolListing">The first-launch tool listing gate (T062). Required, and
    /// required as a constructor argument rather than as a property, so that starting a CLI
    /// without one cannot be an omission: see <see cref="ToolListing"/>.</param>
    public TerminalSessionOptions(
        CliLaunch launch, IPageChannel channel, ToolListingGate toolListing)
    {
        Launch = launch ?? throw new ArgumentNullException(nameof(launch));
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        ToolListing = toolListing ?? throw new ArgumentNullException(
            nameof(toolListing),
            "a terminal session needs a tool listing gate. Pass ToolListingGate.ForCodex(...) "
            + "for a CLI, or the named ToolListingGate.NotACli for a child that is not a CLI "
            + "at all - falling back to an unrestricted CLI is the failure the read-only "
            + "guarantee exists to prevent (contracts/cli-profiles.md).");
    }

    /// <summary>The resolved launch command - never a bare CLI name (see <see cref="CliLaunch"/>).</summary>
    public CliLaunch Launch { get; }

    /// <summary>Where `terminal.output` and `terminal.exited` go. The implementation marshals
    /// onto the UI thread; the read loop here is a background thread and `PostWebMessageAsJson`
    /// has UI-thread affinity.</summary>
    public IPageChannel Channel { get; }

    /// <summary>The terminal run folder (contracts/pane-host-messages.md), reported to the page
    /// as `terminal.started.cwd`.</summary>
    public string? WorkingDirectory { get; set; }

    /// <summary>Added to the parent's environment - the CLI's profile home and, for the tool
    /// service, its secret. The only channel a secret travels on (FR-015).</summary>
    public IDictionary<string, string> Environment { get; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    public short Columns { get; set; } = 120;

    public short Rows { get; set; } = 30;

    /// <summary>The host's kill-on-close job. The session nests its own inside it.</summary>
    public JobObject? Job { get; set; }

    /// <summary>
    /// T062. The first-launch tool listing check (`contracts/cli-profiles.md`, "Verification on
    /// first launch"): what the CLI actually loaded, against the MCP allowlist and the built-in
    /// set the profile intends to leave enabled.
    ///
    /// Not optional, and not a property with a permissive default. It was both, once: a
    /// nullable property and a `ToolListing?.Verify()` in <see cref="TerminalSession.Start"/>,
    /// which made starting an unchecked CLI a one-line omission in a caller - and no test could
    /// have caught it, because "no gate" looked exactly like every other default. The one case
    /// with nothing to check - the `cmd.exe` children the ConPTY tests run to prove the
    /// pseudo-console, the reading and the coalescing work at all - now has to say so in as many
    /// words, with <see cref="ToolListingGate.NotACli"/>.
    ///
    /// <see cref="TerminalSession.Start"/> runs it before it creates anything, so a CLI whose
    /// toolset does not match is a CLI that was never started, rather than one that was started
    /// and then complained about.
    /// </summary>
    public ToolListingGate ToolListing { get; }

    /// <summary>One frame (contracts/pane-host-messages.md).</summary>
    public TimeSpan CoalesceInterval { get; set; } = TimeSpan.FromMilliseconds(16);

    /// <summary>32 KB (contracts/pane-host-messages.md).</summary>
    public int CoalesceBytes { get; set; } = 32 * 1024;

    /// <summary>
    /// What <see cref="TerminalSession.Stop"/> types before it terminates anything.
    ///
    /// Both CLIs and `cmd.exe` end on `exit`, and asking first is what lets a CLI write out
    /// whatever it keeps - a session transcript, a credential refresh - instead of losing it
    /// to `TerminateProcess`.
    /// </summary>
    public string ExitCommand { get; set; } = "exit\r";

    /// <summary>How long <see cref="TerminalSession.Stop"/> waits after the exit command
    /// before ending the process tree.</summary>
    public TimeSpan StopGrace { get; set; } = TimeSpan.FromSeconds(3);
}

/// <summary>
/// The running CLI, as much of it as <see cref="TerminalHost"/> uses.
///
/// It exists for the same reason <c>IBackendClient</c> and <c>IReviewDump</c> do: the host's
/// whole message contract - `terminal.start`, `terminal.input`, `terminal.resize`,
/// `terminal.stop` - has to be testable on a machine with no Codex CLI, no SOLIDWORKS and no
/// WebView2. A host test that had to start a real pseudo-console would be a host test that only
/// ran on one workstation.
/// </summary>
public interface ITerminalSession : IDisposable
{
    /// <summary>The CLI's process id, as `terminal.started.pid`.</summary>
    int ProcessId { get; }

    /// <summary>The terminal run folder, as `terminal.started.cwd`.</summary>
    string WorkingDirectory { get; }

    bool HasExited { get; }

    /// <summary>`terminal.input`.</summary>
    void Write(string data);

    /// <summary>`terminal.resize`.</summary>
    void Resize(short columns, short rows);

    /// <summary>`terminal.stop`: the exit command, then the process tree.</summary>
    void Stop();
}

/// <summary>
/// One CLI running in a pseudo-console, with its screen going to the Terminal page and the
/// page's keystrokes coming back (T053, contracts/pane-host-messages.md).
///
/// The four things it is responsible for, and why each is here rather than in the host:
///
/// <b>Starting the resolved launch command</b> through <see cref="ChildProcess"/> into a job
/// object, suspended, so a CLI cannot escape the job in the window before its first
/// instruction (T050) and cannot outlive SOLIDWORKS.
///
/// <b>Reading on a thread of its own.</b> A pseudo-console read blocks until the child draws
/// something, which for an idle CLI is for ever; on the UI thread that is a frozen
/// SOLIDWORKS. Everything the loop posts is marshalled back by the channel.
///
/// <b>Coalescing.</b> See <see cref="OutputCoalescer"/>.
///
/// <b>Stopping in that order</b>: the exit command, then the grace period, then the whole
/// process tree. The tree matters because a CLI shim is `cmd.exe /c gemini.cmd`, which is
/// `cmd.exe`, then `node.exe`, then whatever the CLI spawned: terminating the process we hold
/// a handle to would leave the node process running with the tool-service secret in its
/// environment. A nested kill-on-close job is what ends all of them.
/// </summary>
public sealed class TerminalSession : ITerminalSession
{
    private const int ReadChunk = 8192;

    /// <summary>The longest <see cref="Stop"/> waits for the exit to be observed and posted,
    /// after the child itself is already gone. Only a wedged read of the last few bytes can
    /// take this long, and the pane must not hang on the unload path if it does.</summary>
    private const int WatchdogMilliseconds = 15000;

    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        WriteIndented = false,
    };

    private readonly TerminalSessionOptions _options;
    private readonly ConPty _conpty;
    private readonly ChildProcess _child;
    private readonly JobObject _tree;
    private readonly OutputCoalescer _coalescer;
    private readonly object _writeGate = new object();

    private Thread? _reader;
    private Thread? _watcher;
    private long _bytesRead;
    private long _bytesPosted;
    private int _exitPosted;
    private bool _disposed;

    private TerminalSession(
        TerminalSessionOptions options, ConPty conpty, ChildProcess child, JobObject tree)
    {
        _options = options;
        _conpty = conpty;
        _child = child;
        _tree = tree;
        _coalescer = new OutputCoalescer(options.CoalesceInterval, options.CoalesceBytes, PostOutput);
        WorkingDirectory = options.WorkingDirectory ?? System.Environment.CurrentDirectory;
        StartedAt = DateTimeOffset.Now;
    }

    public int ProcessId => _child.ProcessId;

    /// <summary>What the page is told as `terminal.started.cwd`.</summary>
    public string WorkingDirectory { get; }

    public DateTimeOffset StartedAt { get; }

    public short Columns => _conpty.Columns;

    public short Rows => _conpty.Rows;

    public bool HasExited => _child.HasExited;

    /// <summary>Bytes taken off the pseudo-console. Equal to <see cref="BytesPosted"/> once the
    /// session has ended - that equality is what "the coalescer drops nothing" means, and it
    /// is asserted in <c>ConPtyTests</c>.</summary>
    public long BytesRead => Interlocked.Read(ref _bytesRead);

    /// <summary>Bytes handed to the page in `terminal.output` messages.</summary>
    public long BytesPosted => Interlocked.Read(ref _bytesPosted);

    /// <summary>
    /// Creates the pseudo-console, starts the CLI in it, and begins reading. Returns as soon as
    /// the child is running; output arrives on the channel from then on.
    /// </summary>
    public static TerminalSession Start(TerminalSessionOptions options)
    {
        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        // T062, and before anything else exists. A gate that ran after the pseudo-console and
        // the child would have let the unrestricted CLI be a process on the workstation for as
        // long as it took to notice, which is most of the way to the thing being prevented.
        // A difference, an unreadable listing and a probe that failed all throw
        // ToolListingException from here, with the difference named.
        options.ToolListing.Verify();

        ConPty? conpty = null;
        JobObject? tree = null;
        ChildProcess? child = null;

        try
        {
            conpty = ConPty.Create(options.Columns, options.Rows);

            var info = new ChildProcessStartInfo(options.Launch.Executable, options.Launch.Arguments)
            {
                WorkingDirectory = options.WorkingDirectory,
                PseudoConsole = conpty.Handle,
            };
            foreach (KeyValuePair<string, string> variable in options.Environment)
            {
                info.Environment[variable.Key] = variable.Value;
            }

            // The session's own job, nested inside the host's: closing it ends the shim, the
            // interpreter and everything they started.
            tree = new JobObject();
            child = ChildProcess.StartSuspended(info, options.Job, tree);

            var session = new TerminalSession(options, conpty, child, tree);
            conpty = null;
            tree = null;
            child = null;

            session.Run();
            return session;
        }
        catch
        {
            child?.Dispose();
            tree?.Dispose();
            conpty?.Dispose();
            throw;
        }
    }

    /// <summary>Sends keystrokes from the page (`terminal.input`) to the CLI.</summary>
    public void Write(string data)
    {
        if (string.IsNullOrEmpty(data))
        {
            return;
        }

        byte[] bytes = Encoding.UTF8.GetBytes(data);
        lock (_writeGate)
        {
            try
            {
                _conpty.Input.Write(bytes, 0, bytes.Length);
                _conpty.Input.Flush();
            }
            catch (IOException)
            {
                // The CLI has gone and taken its console with it. A keystroke that arrives in
                // that window is the ordinary end of a session, not a fault to report.
            }
            catch (ObjectDisposedException)
            {
            }
        }
    }

    /// <summary>The page's `terminal.resize`.</summary>
    public void Resize(short columns, short rows) => _conpty.Resize(columns, rows);

    /// <summary>
    /// Asks the CLI to exit, waits <see cref="TerminalSessionOptions.StopGrace"/>, then ends
    /// the process tree. Returns once the exit has been observed and `terminal.exited` posted.
    /// Idempotent.
    /// </summary>
    public void Stop()
    {
        if (!_child.HasExited)
        {
            Write(_options.ExitCommand);
            _child.WaitForExit((int)_options.StopGrace.TotalMilliseconds);
        }

        if (!_child.HasExited)
        {
            // Not a failure of the CLI: a TUI waiting on a prompt, or one that is mid-request,
            // has nothing to do with the word "exit" typed at it.
            _child.Kill();
        }

        // Whatever the child started is a generation below the handle we hold; the job is what
        // reaches it.
        _tree.Dispose();

        // The watcher is what closes the console, drains the last of the output and posts
        // `terminal.exited`; the host's reply to `terminal.stop` has to come after that.
        _watcher?.Join(WatchdogMilliseconds);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;

        try
        {
            Stop();
        }
        catch (Exception)
        {
            // Cleanup runs on the add-in's unload path with SOLIDWORKS waiting for it; a
            // throw here would be the last thing that ever happened.
        }

        // The console after the watcher, not before: closing it is how the read loop is given
        // its end of file, and the watcher does it in the ordinary case.
        _conpty.Dispose();
        _reader?.Join(2000);
        _coalescer.Dispose();
        _child.Dispose();
        _tree.Dispose();
    }

    private void Run()
    {
        _reader = new Thread(ReadLoop)
        {
            IsBackground = true,
            Name = "swreview-terminal-read",
        };
        _watcher = new Thread(WatchForExit)
        {
            IsBackground = true,
            Name = "swreview-terminal-exit",
        };

        // Reading before running, so the first frame the CLI draws is not waiting on a pipe
        // nobody is at.
        _reader.Start();
        _watcher.Start();
        _child.Resume();
    }

    private void ReadLoop()
    {
        var buffer = new byte[ReadChunk];
        while (true)
        {
            int read;
            try
            {
                read = _conpty.Output.Read(buffer, 0, buffer.Length);
            }
            catch (IOException)
            {
                break;
            }
            catch (ObjectDisposedException)
            {
                break;
            }

            if (read <= 0)
            {
                // End of file: the pseudo-console has been closed.
                break;
            }

            Interlocked.Add(ref _bytesRead, read);
            _coalescer.Append(buffer, 0, read);
        }
    }

    private void WatchForExit()
    {
        _child.WaitForExit(-1);

        // Taking the console away is what ends the read loop: `ClosePseudoConsole` flushes
        // what the child drew last and then closes our end, so the loop sees the final bytes
        // and then end of file. Waiting on the child alone would leave the loop blocked, and
        // reading until end of file alone would never happen while the console is open.
        _conpty.Dispose();
        _reader?.Join(5000);

        // The last partial buffer, before the exit message rather than after it: a page that
        // was told the session ended and then handed more of its output would draw it below
        // the exit notice.
        _coalescer.Flush();
        PostExited(_child.ExitCode);
    }

    private void PostOutput(byte[] chunk)
    {
        Interlocked.Add(ref _bytesPosted, chunk.Length);
        Post("terminal.output", new Dictionary<string, object?>
        {
            { "data_base64", Convert.ToBase64String(chunk) },
        });
    }

    private void PostExited(int exitCode)
    {
        if (Interlocked.Exchange(ref _exitPosted, 1) != 0)
        {
            return;
        }

        Post("terminal.exited", new Dictionary<string, object?>
        {
            { "exit_code", exitCode },
        });
    }

    /// <summary>One unsolicited host-to-page message: `{type, id: null, payload}`.</summary>
    private void Post(string type, object payload)
    {
        var envelope = new Dictionary<string, object?>
        {
            { "type", type },
            { "id", null },
            { "payload", payload },
        };

        try
        {
            _options.Channel.PostMessage(JsonSerializer.Serialize(envelope, JsonOptions));
        }
        catch (Exception)
        {
            // The page is gone (the pane closed while the CLI was still drawing). There is
            // nobody left to tell, and this runs on a background thread where a throw would
            // take the process down.
        }
    }
}
