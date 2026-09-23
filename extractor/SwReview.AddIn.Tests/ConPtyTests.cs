using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;
using SwReview.AddIn.Terminal;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T052: the pseudo-console half of the Terminal tab, against real children.
///
/// Everything here runs `cmd.exe` rather than a CLI, on purpose: the Codex and Gemini CLIs
/// are not installed on every machine that builds this solution, and the thing under test is
/// the console plumbing, which does not care what is attached to it.
///
/// Five facts are worth one test each because each of them is a way the pane breaks in front
/// of an engineer and in no other way:
///
/// - a child's output reaches the page at all, and its exit code follows it;
/// - a `.cmd` shim starts. `CreateProcess`, which ConPTY requires, cannot execute a `.cmd`:
///   it is not an image, it is input for `cmd.exe`. The Gemini CLI ships as `gemini.cmd` and
///   npm ships every other CLI the same way, so a session that only ever runs `.exe` files
///   works on our machine and fails on the engineer's. The launch command is therefore
///   resolved (<see cref="CliLaunch"/>) and the session starts what the resolution produced;
/// - a resize reaches the child. xterm.js resizes on every pane drag, and a CLI that is told
///   80x25 forever draws its TUI into the wrong box;
/// - closing the pseudo-console ends the child. This is the only stop path that works when
///   the CLI has stopped reading its input, and it is what a closed pane relies on;
/// - bytes are forwarded untranslated and coalesced without loss. A terminal is a byte
///   stream: a stray CR/LF rewrite or a dropped escape byte corrupts the TUI, and a post per
///   read would flood the WebView2 message queue (contracts/pane-host-messages.md: at most
///   one `terminal.output` per ~16 ms or 32 KB, dropping nothing).
///
/// The coalescing rule is tested twice and deliberately. Through a real pseudo-console the
/// *content* cannot be asserted - ConPTY renders a screen, so what comes out is VT, not what
/// the child printed - so that test asserts the accounting (every byte read was posted) and
/// the message bound. <see cref="OutputCoalescer"/> is then driven directly, where the bytes
/// in and the bytes out must match exactly and both halves of the rule (32 KB, ~16 ms) can be
/// separated from each other.
/// </summary>
public sealed class ConPtyTests
{
    private const int Megabyte = 1024 * 1024;

    /// <summary>
    /// The stated bound for 1 MB of output (the "fewer than" in T052).
    ///
    /// The rule allows one message per 32 KB plus one per ~16 ms, so for 1 MB that is 32
    /// size-driven posts plus one per 16 ms the child spends producing them. Measured here:
    /// 34 messages for 1,048,710 bytes, which is the 32 the size rule demands and two from
    /// the interval. The bound is set well above that - 256 - because the second half of the
    /// rule is a clock, and a loaded machine that takes 3.5 seconds over the same megabyte is
    /// obeying the rule, not breaking it. Even so it is an order of magnitude below the
    /// thousands of posts a message-per-read loop makes on this path, which is what the bound
    /// exists to catch.
    /// </summary>
    private const int MaxMessagesForAMegabyte = 256;

    private static string Cmd => Path.Combine(Environment.SystemDirectory, "cmd.exe");

    [Fact]
    public void ACmdChildsOutputReachesThePage()
    {
        var channel = new RecordingChannel();
        using (var temp = new TempFolder())
        using (TerminalSession session = TerminalSession.Start(Options(
            channel, temp, CliLaunch.ForExecutable(Cmd, "/c", "echo hello"))))
        {
            Assert.True(session.ProcessId > 0);
            Assert.True(channel.WaitForExit(), "the session never reported terminal.exited");

            Assert.Contains("hello", channel.Text, StringComparison.Ordinal);
            Assert.Equal(0, channel.ExitCode);
            Assert.True(channel.OutputMessages > 0);
        }
    }

    [Fact]
    public void TheChildsExitCodeReachesThePage()
    {
        var channel = new RecordingChannel();
        using (var temp = new TempFolder())
        using (TerminalSession session = TerminalSession.Start(Options(
            channel, temp, CliLaunch.ForExecutable(Cmd, "/c", "exit 3"))))
        {
            Assert.True(channel.WaitForExit(), "the session never reported terminal.exited");
            Assert.Equal(3, channel.ExitCode);
        }
    }

    [Fact]
    public void ACmdShimStartsThroughTheResolvedLaunchCommand()
    {
        using (var temp = new TempFolder())
        {
            // Exactly the shape npm installs a CLI as, `gemini.cmd` included.
            string shim = temp.Write("swreview-probe.cmd", "@echo off\r\necho shim-ok\r\n");

            Assert.True(CliLaunch.TryResolve(shim, out CliLaunch? launch, out string? unsupported));
            Assert.Null(unsupported);
            Assert.NotNull(launch);
            Assert.Equal(Cmd, launch!.Executable, StringComparer.OrdinalIgnoreCase);
            Assert.Equal(new[] { "/c", shim }, launch.Arguments);

            // The CLI's own arguments go after the interpreter's, never before: `cmd.exe
            // --version /c gemini.cmd` is a different program. This is the seam the version
            // probe and the profile switches (T055, T057) both hang off.
            Assert.Equal(new[] { "/c", shim, "--version" }, launch.With("--version").Arguments);
            Assert.Equal(new[] { "/c", shim }, launch.Arguments);

            var channel = new RecordingChannel();
            using (TerminalSession session = TerminalSession.Start(Options(channel, temp, launch)))
            {
                Assert.True(channel.WaitForExit(), "the shim session never reported terminal.exited");
                Assert.Contains("shim-ok", channel.Text, StringComparison.Ordinal);
                Assert.Equal(0, channel.ExitCode);
            }
        }
    }

    [Fact]
    public void APowerShellShimResolvesToPowerShellAndAnUnknownExtensionIsUnsupported()
    {
        using (var temp = new TempFolder())
        {
            string script = temp.Write("swreview-probe.ps1", "Write-Output 'ps-ok'\r\n");

            Assert.True(CliLaunch.TryResolve(script, out CliLaunch? launch, out _));
            Assert.EndsWith(
                @"\powershell.exe", launch!.Executable, StringComparison.OrdinalIgnoreCase);
            Assert.Equal(
                new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script },
                launch.Arguments);

            string other = temp.Write("swreview-probe.py", "print('no')\r\n");
            Assert.False(CliLaunch.TryResolve(other, out CliLaunch? none, out string? unsupported));
            Assert.Null(none);
            Assert.NotNull(unsupported);
            Assert.Contains(".py", unsupported!, StringComparison.OrdinalIgnoreCase);
        }
    }

    [Fact]
    public void ResizingIsVisibleToTheChild()
    {
        var channel = new RecordingChannel();
        using (var temp = new TempFolder())
        using (TerminalSession session = TerminalSession.Start(
            Options(channel, temp, CliLaunch.ForExecutable(Cmd), columns: 80, rows: 25)))
        {
            // `mode con` asks the console itself, so it reports what ConPTY told the child -
            // which is the only thing worth asserting here.
            session.Write("mode con\r\n");
            Assert.True(
                channel.WaitFor(text => Columns(text).Contains(80)),
                "the child never reported the starting width: " + channel.Text);
            Assert.Contains(25, Lines(channel.Text));

            channel.Forget();
            session.Resize(100, 45);
            session.Write("mode con\r\n");

            Assert.True(
                channel.WaitFor(text => Columns(text).Contains(100)),
                "the child never reported the new width: " + channel.Text);
            Assert.Contains(45, Lines(channel.Text));

            session.Stop();
            Assert.True(channel.WaitForExit(), "the session never reported terminal.exited");
        }
    }

    [Fact]
    public void ClosingThePseudoConsoleEndsTheChild()
    {
        // At the ConPTY level rather than through TerminalSession, because the session's own
        // stop path terminates the child and would prove nothing about the console.
        using (var conpty = ConPty.Create(80, 25))
        using (var job = new JobObject())
        {
            var info = new ChildProcessStartInfo(Cmd, Array.Empty<string>())
            {
                PseudoConsole = conpty.Handle,
            };

            using (ChildProcess child = ChildProcess.StartSuspended(info, job))
            {
                // ClosePseudoConsole flushes what the child has written before it closes, so
                // something has to be reading or the close can block. In the session that is
                // the read loop; here it is this thread.
                var drain = new Thread(() =>
                {
                    var buffer = new byte[4096];
                    try
                    {
                        while (conpty.Output.Read(buffer, 0, buffer.Length) > 0)
                        {
                        }
                    }
                    catch (IOException)
                    {
                    }
                    catch (ObjectDisposedException)
                    {
                    }
                })
                {
                    IsBackground = true,
                    Name = "conpty-test-drain",
                };
                drain.Start();

                child.Resume();

                // An interactive `cmd.exe` sits at its prompt for ever; nothing but the close
                // below can end it.
                Thread.Sleep(750);
                Assert.False(child.HasExited);

                conpty.Dispose();

                Assert.True(
                    child.WaitForExit(15000),
                    "closing the pseudo-console left the child running");
            }
        }
    }

    [Fact]
    public void OutputArrivesAsRawBytesWithoutTranslation()
    {
        var channel = new RecordingChannel();
        using (var temp = new TempFolder())
        using (TerminalSession session = TerminalSession.Start(Options(
            channel, temp, CliLaunch.ForExecutable(Cmd, "/c", "echo hello"))))
        {
            Assert.True(channel.WaitForExit(), "the session never reported terminal.exited");

            byte[] raw = channel.Output;

            // Bytes, not text: every message carries base64 and nothing else, and what it
            // decodes to is exactly what came off the pipe.
            Assert.All(channel.Payloads, payload => Assert.Equal(
                new[] { "data_base64" }, payload.Keys.ToArray()));
            Assert.Equal(raw.Length, session.BytesRead);
            Assert.Equal(session.BytesRead, session.BytesPosted);

            // A text-mode reader is what would break this: CR LF arrives as two bytes, and the
            // escape byte that starts every VT sequence is not text at all.
            Assert.True(Contains(raw, new byte[] { 0x0D, 0x0A }), "no CR LF survived the read loop");
            Assert.Contains((byte)0x1B, raw);
        }
    }

    [Fact]
    public void AMegabyteOfOutputIsCoalescedAndNothingIsLost()
    {
        using (var temp = new TempFolder())
        {
            // 78 characters plus CR LF, so nothing wraps at the 120-column default and ConPTY
            // has the least possible work to do; ~1.02 MB in total.
            var line = new string('x', 78) + "\r\n";
            var builder = new StringBuilder(Megabyte + 4096);
            while (builder.Length < Megabyte)
            {
                builder.Append(line);
            }

            temp.Write("big.txt", builder.ToString());

            // Named relatively, against the session's working directory: `cmd /c` re-parses
            // its own command line and a quoted path inside a quoted argument is exactly the
            // case its rules mangle.
            var channel = new RecordingChannel();
            using (TerminalSession session = TerminalSession.Start(Options(
                channel, temp, CliLaunch.ForExecutable(Cmd, "/c", "type big.txt"))))
            {
                Assert.True(channel.WaitForExit(120000), "the 1 MB child never finished");

                Assert.True(
                    session.BytesRead >= Megabyte,
                    $"only {session.BytesRead} bytes came out of the pseudo-console");
                // Not one byte buffered and forgotten: what was read is what was posted.
                Assert.Equal(session.BytesRead, session.BytesPosted);
                Assert.Equal(session.BytesPosted, channel.Output.LongLength);

                Assert.True(
                    channel.OutputMessages <= MaxMessagesForAMegabyte,
                    $"{channel.OutputMessages} terminal.output messages for "
                    + $"{session.BytesRead} bytes exceeds the stated bound of "
                    + MaxMessagesForAMegabyte);
            }
        }
    }

    // ---- the coalescing rule on its own --------------------------------------------------

    [Fact]
    public void TheCoalescerPostsOnThirtyTwoKilobytesAndLosesNothing()
    {
        var posted = new List<byte[]>();
        var payload = new byte[Megabyte];
        new Random(20260913).NextBytes(payload);

        // A ten-minute interval so only the size half of the rule can fire: this test is about
        // 32 KB, and a timer that went off mid-run would make the chunk sizes below a race.
        using (var coalescer = new OutputCoalescer(
            TimeSpan.FromMinutes(10), 32 * 1024, chunk => posted.Add(chunk)))
        {
            for (int offset = 0; offset < payload.Length; offset += 4096)
            {
                coalescer.Append(payload, offset, Math.Min(4096, payload.Length - offset));
            }

            coalescer.Flush();
        }

        Assert.Equal(payload, posted.SelectMany(chunk => chunk).ToArray());
        Assert.True(posted.Count <= 48, $"{posted.Count} posts for 1 MB is not coalescing");
        // Every post but the last one is a full buffer: that is what "at 32 KB" means.
        Assert.All(
            posted.Take(posted.Count - 1),
            chunk => Assert.True(chunk.Length >= 32 * 1024, $"a short post of {chunk.Length} bytes"));
    }

    [Fact]
    public void TheCoalescerPostsASmallWriteAfterTheInterval()
    {
        var interval = TimeSpan.FromMilliseconds(200);
        var gate = new ManualResetEventSlim(false);
        var posted = new List<byte[]>();
        var clock = new System.Diagnostics.Stopwatch();
        TimeSpan postedAfter = TimeSpan.Zero;
        using (var coalescer = new OutputCoalescer(
            interval,
            32 * 1024,
            chunk =>
            {
                lock (posted)
                {
                    postedAfter = clock.Elapsed;
                    posted.Add(chunk);
                }

                gate.Set();
            }))
        {
            clock.Start();
            coalescer.Append(Encoding.ASCII.GetBytes("$ "), 0, 2);

            // A prompt is two bytes and must not wait for 32 KB that will never come, nor be
            // posted on the spot. The time is taken inside the callback rather than by
            // asserting "nothing yet" after Append: on a loaded machine the test thread can
            // lose more than the interval between the two lines, and the flush then lands
            // first although the coalescer did wait. The slack is the Windows timer
            // resolution (15.6 ms), by which a timer may fire early. The wait is long because
            // the flush runs on a thread-pool timer, and the parallel test run can hold every
            // pool thread for several seconds (seen: 5 s passed with no flush while the reviewer
            // suite ran beside it); a coalescer that never flushes still fails, only later.
            Assert.True(gate.Wait(30000), "the interval never flushed the buffer");
            lock (posted)
            {
                Assert.Equal(new[] { (byte)'$', (byte)' ' }, Assert.Single(posted));
                Assert.True(
                    postedAfter >= interval - TimeSpan.FromMilliseconds(20),
                    $"posted after {postedAfter.TotalMilliseconds:F0} ms, before the interval");
            }
        }
    }

    [Fact]
    public void TheCoalescerRejectsAnUnusableRule()
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => new OutputCoalescer(TimeSpan.Zero, 32 * 1024, _ => { }));
        Assert.Throws<ArgumentOutOfRangeException>(
            () => new OutputCoalescer(TimeSpan.FromMilliseconds(16), 0, _ => { }));
        Assert.Throws<ArgumentNullException>(
            () => new OutputCoalescer(TimeSpan.FromMilliseconds(16), 1024, null!));
    }

    // ---- helpers -------------------------------------------------------------------------

    private static TerminalSessionOptions Options(
        RecordingChannel channel,
        TempFolder temp,
        CliLaunch launch,
        short columns = 120,
        short rows = 30)
    {
        // `ToolListingGate.NotACli` in as many words: these children are `cmd.exe`, not a CLI
        // with an MCP server, and the gate is required of everything else (T062).
        return new TerminalSessionOptions(launch, channel, ToolListingGate.NotACli)
        {
            WorkingDirectory = temp.Path,
            Columns = columns,
            Rows = rows,
            StopGrace = TimeSpan.FromMilliseconds(750),
        };
    }

    private static bool Contains(byte[] haystack, byte[] needle)
    {
        for (int start = 0; start + needle.Length <= haystack.Length; start++)
        {
            bool all = true;
            for (int offset = 0; offset < needle.Length && all; offset++)
            {
                all = haystack[start + offset] == needle[offset];
            }

            if (all)
            {
                return true;
            }
        }

        return false;
    }

    private static IReadOnlyList<int> Columns(string text) => Numbers(text, "Columns");

    private static IReadOnlyList<int> Lines(string text) => Numbers(text, "Lines");

    /// <summary>
    /// Every `Lines:`/`Columns:` number `mode con` printed, in order.
    ///
    /// The escape sequences ConPTY interleaves with the text are stripped first; without that
    /// a cursor move landing between the label and the number hides the match.
    /// </summary>
    private static IReadOnlyList<int> Numbers(string text, string label)
    {
        string plain = Regex.Replace(text, "\\[[0-9;?]*[ -/]*[@-~]", string.Empty);
        plain = Regex.Replace(plain, "[]P^_][^]*(|\\\\)?", string.Empty);
        plain = Regex.Replace(plain, "[()][A-Za-z0-9]", string.Empty);

        return Regex.Matches(plain, label + @":\s*(\d+)")
            .Cast<Match>()
            .Select(match => int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture))
            .ToList();
    }

    /// <summary>The page, as far as a <see cref="TerminalSession"/> can tell.</summary>
    private sealed class RecordingChannel : IPageChannel
    {
        private readonly object _gate = new object();
        private readonly List<IReadOnlyDictionary<string, string>> _payloads =
            new List<IReadOnlyDictionary<string, string>>();
        private readonly MemoryStream _output = new MemoryStream();
        private readonly ManualResetEventSlim _exited = new ManualResetEventSlim(false);
        private readonly ManualResetEventSlim _arrived = new ManualResetEventSlim(false);

        private int _outputMessages;
        private int? _exitCode;

        public int OutputMessages
        {
            get
            {
                lock (_gate)
                {
                    return _outputMessages;
                }
            }
        }

        public int? ExitCode
        {
            get
            {
                lock (_gate)
                {
                    return _exitCode;
                }
            }
        }

        public byte[] Output
        {
            get
            {
                lock (_gate)
                {
                    return _output.ToArray();
                }
            }
        }

        public string Text => Encoding.UTF8.GetString(Output);

        public IReadOnlyList<IReadOnlyDictionary<string, string>> Payloads
        {
            get
            {
                lock (_gate)
                {
                    return _payloads.ToList();
                }
            }
        }

        public void PostMessage(string json)
        {
            using (JsonDocument document = JsonDocument.Parse(json))
            {
                JsonElement root = document.RootElement;
                string type = root.GetProperty("type").GetString()!;
                JsonElement payload = root.GetProperty("payload");

                // Unsolicited host -> page messages carry a null id (contracts).
                Assert.Equal(JsonValueKind.Null, root.GetProperty("id").ValueKind);

                lock (_gate)
                {
                    if (type == "terminal.output")
                    {
                        var fields = new Dictionary<string, string>(StringComparer.Ordinal);
                        foreach (JsonProperty property in payload.EnumerateObject())
                        {
                            fields[property.Name] = property.Value.GetString() ?? string.Empty;
                        }

                        _payloads.Add(fields);
                        _outputMessages++;
                        byte[] bytes = Convert.FromBase64String(fields["data_base64"]);
                        _output.Write(bytes, 0, bytes.Length);
                        _arrived.Set();
                    }
                    else if (type == "terminal.exited")
                    {
                        _exitCode = payload.GetProperty("exit_code").GetInt32();
                        _exited.Set();
                    }
                    else
                    {
                        throw new Xunit.Sdk.XunitException("unexpected host message: " + type);
                    }
                }
            }
        }

        public bool WaitForExit(int milliseconds = 30000) => _exited.Wait(milliseconds);

        /// <summary>Waits until the decoded stream satisfies <paramref name="predicate"/>.</summary>
        public bool WaitFor(Func<string, bool> predicate, int milliseconds = 20000)
        {
            var deadline = DateTime.UtcNow.AddMilliseconds(milliseconds);
            while (DateTime.UtcNow < deadline)
            {
                if (predicate(Text))
                {
                    return true;
                }

                _arrived.Reset();
                _arrived.Wait(100);
            }

            return predicate(Text);
        }

        /// <summary>Drops what has been received so far, so a second `mode con` is read on its
        /// own rather than matching the first one's numbers.</summary>
        public void Forget()
        {
            lock (_gate)
            {
                _output.SetLength(0);
                _payloads.Clear();
            }
        }
    }

    private sealed class TempFolder : IDisposable
    {
        public TempFolder()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(), "SwReview.ConPty.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public string Write(string name, string content)
        {
            string full = System.IO.Path.Combine(Path, name);
            File.WriteAllText(full, content, new UTF8Encoding(false));
            return full;
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(Path, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
}
