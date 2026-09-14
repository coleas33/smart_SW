using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Native;
using SwReview.AddIn.Terminal;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T062's missing half: the thing that actually asks Codex what it loaded.
///
/// <see cref="ToolListingCheck"/> compares a listing against the allowlist and
/// <see cref="ToolListingGate"/> refuses the start on a difference, but both are handed a
/// listing by a `Func&lt;string&gt;`. Until something produced that string from a real CLI the
/// gate was machinery with no input: every parse, comparison and refusal was exercised only by
/// fixtures, and the first real Codex launch would have had to pass a lambda of its own or -
/// the failure the gate exists to prevent - no gate at all.
///
/// <see cref="CodexAppServerProbe"/> is that input: a short-lived `codex app-server` child with
/// the generated `CODEX_HOME`, spoken to in newline-delimited JSON-RPC on stdio - `initialize`,
/// the `initialized` notification, then `mcpServerStatus/list` - whose `result` is the listing.
/// `Fixtures/ToolListing/README.md` records that exchange as the capture procedure for the
/// fixtures; this is the same exchange, run at every terminal start.
///
/// The conversation is tested against a canned transcript rather than against a real Codex,
/// because the CLI is not installed on every machine that builds this solution and a gate whose
/// tests only run on one workstation is a gate nobody notices breaking. One test does drive the
/// whole probe - process, pipes, environment and all - against a replay child, because the
/// stdin pipe is the part that cannot be proved any other way: every other child the pane
/// starts is given `NUL`.
/// </summary>
public sealed class CodexAppServerProbeTests
{
    /// <summary>What a real app-server answers `initialize` with, shortened.</summary>
    private const string InitializeReply =
        "{\"id\":1,\"result\":{\"userAgent\":\"swreview/0.115.0 (Windows 10.0.26200; x86_64)\"}}";

    // ---- the conversation ---------------------------------------------------------------

    [Fact]
    public void TheProbeInitializesAndThenAsksForTheMcpServerStatus()
    {
        var written = new StringWriter();
        string listing = CodexAppServerProbe.ReadListing(
            Transcript(InitializeReply, ListReply(Fixture("codex-startup-listing.json"))),
            written,
            TimeSpan.FromSeconds(5));

        // The order is the protocol's, not a preference: `mcpServerStatus/list` before the
        // handshake is answered is a request to a server that has not started its MCP clients.
        List<JsonElement> sent = Sent(written.ToString());
        Assert.Equal(
            new[] { "initialize", "initialized", "mcpServerStatus/list" },
            sent.Select(message => message.GetProperty("method").GetString()).ToArray());

        // The notification carries no id - that is what makes it a notification rather than a
        // request nobody ever answers, which would hang the probe until its timeout.
        Assert.False(sent[1].TryGetProperty("id", out _));
        Assert.NotEqual(
            sent[0].GetProperty("id").GetRawText(), sent[2].GetProperty("id").GetRawText());

        // What comes back is the `result` and nothing around it: the gate's parser is given the
        // same document the fixtures hold.
        Assert.Equal(
            Normalize(Fixture("codex-startup-listing.json")), Normalize(listing));
    }

    [Fact]
    public void EveryLineTheProbeWritesIsOneJsonDocument()
    {
        var written = new StringWriter();
        CodexAppServerProbe.ReadListing(
            Transcript(InitializeReply, ListReply(Fixture("codex-startup-listing.json"))),
            written,
            TimeSpan.FromSeconds(5));

        // The transport is newline-delimited JSON (measured against codex-cli 0.115.0): a
        // pretty-printed request would be read as several malformed ones and answered with
        // nothing at all.
        foreach (string line in written.ToString().Split('\n'))
        {
            if (line.Trim().Length == 0)
            {
                continue;
            }

            Assert.False(line.EndsWith("\r", StringComparison.Ordinal), "a CR ended a JSONL line");
            using (JsonDocument.Parse(line))
            {
            }
        }
    }

    [Fact]
    public void TheListingTheProbeReturnsIsOneTheGateAccepts()
    {
        string listing = CodexAppServerProbe.ReadListing(
            Transcript(InitializeReply, ListReply(Fixture("codex-startup-listing.json"))),
            new StringWriter(),
            TimeSpan.FromSeconds(5));

        Assert.True(ToolListingCheck.ForCodex().Check(ToolListing.FromCodex(listing)).Matches);
    }

    [Fact]
    public void AnErrorReplyRefusesRatherThanReturningNothing()
    {
        CodexAppServerException failure = Assert.Throws<CodexAppServerException>(
            () => CodexAppServerProbe.ReadListing(
                Transcript(
                    InitializeReply,
                    "{\"id\":2,\"error\":{\"code\":-32601,\"message\":\"method not found\"}}"),
                new StringWriter(),
                TimeSpan.FromSeconds(5)));

        Assert.Contains("method not found", failure.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void AnAppServerThatSaysNothingTimesOutRatherThanHangingTheTab()
    {
        // The gate runs before the pseudo-console exists, on the terminal host's own thread. A
        // probe with no timeout would be a Start button that never answers.
        using (var silence = new BlockingReader())
        {
            CodexAppServerException failure = Assert.Throws<CodexAppServerException>(
                () => CodexAppServerProbe.ReadListing(
                    silence, new StringWriter(), TimeSpan.FromMilliseconds(250)));

            Assert.Contains("did not answer", failure.Message, StringComparison.OrdinalIgnoreCase);
        }
    }

    [Fact]
    public void AnAppServerThatEndsBeforeAnsweringIsRefused()
    {
        CodexAppServerException failure = Assert.Throws<CodexAppServerException>(
            () => CodexAppServerProbe.ReadListing(
                Transcript(InitializeReply), new StringWriter(), TimeSpan.FromSeconds(5)));

        Assert.Contains("ended", failure.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void NoiseOnTheWayToTheAnswerIsSkipped()
    {
        // A real app-server interleaves notifications with the replies, and a blank line or a
        // log line on stdout is not unheard of. Anything that is not the reply being waited for
        // is passed over rather than treated as a protocol failure.
        string listing = CodexAppServerProbe.ReadListing(
            Transcript(
                string.Empty,
                "{\"method\":\"loginChatGptComplete\",\"params\":{}}",
                InitializeReply,
                "not json at all",
                "{\"id\":99,\"result\":{}}",
                ListReply(Fixture("codex-startup-listing.json"))),
            new StringWriter(),
            TimeSpan.FromSeconds(5));

        Assert.Equal(Normalize(Fixture("codex-startup-listing.json")), Normalize(listing));
    }

    // ---- the whole probe, against a replay child ------------------------------------------

    /// <summary>
    /// The plumbing, end to end: a child started through <see cref="ChildProcess"/> into a job,
    /// with the generated `CODEX_HOME` in its environment and a pipe on its standard input.
    ///
    /// The child is a PowerShell replay of the transcript above rather than Codex itself, for
    /// the reason the class remarks give. What it proves is the half a canned
    /// <see cref="TextReader"/> cannot: that the requests reach a real process's stdin at all.
    /// Every other child the pane starts is given `NUL` for its input, so this pipe exists for
    /// this probe and is tested here or nowhere.
    /// </summary>
    [Fact]
    public void TheProbeSpeaksToARealChildOverItsStandardInput()
    {
        using (var temp = new TempFolder())
        {
            string replyPath = temp.Write(
                "reply.jsonl", ListReply(Fixture("codex-startup-listing.json")) + "\r\n");
            string script = temp.Write("app-server.ps1", ReplayScript);
            string home = temp.Directory("codex-home");

            Assert.True(CliLaunch.TryResolve(script, out CliLaunch? launch, out _));

            var probe = new CodexAppServerProbe(launch!, home, temp.Path)
            {
                Timeout = TimeSpan.FromSeconds(60),
            };
            probe.Environment["SWREVIEW_TEST_REPLY"] = replyPath;

            string listing = probe.Run();

            Assert.True(ToolListingCheck.ForCodex().Check(ToolListing.FromCodex(listing)).Matches);

            // The gate is what the terminal host builds out of it, and it is the whole point of
            // the probe existing: a listing nobody compares is a listing nobody checked.
            Assert.True(ToolListingGate.ForCodex(probe.Run).Verify().Matches);
        }
    }

    [Fact]
    public void AChildThatCannotBeStartedIsARefusalAndNotACrash()
    {
        using (var temp = new TempFolder())
        {
            var probe = new CodexAppServerProbe(
                CliLaunch.ForExecutable(Path.Combine(temp.Path, "not-here.exe")),
                temp.Directory("codex-home"),
                temp.Path);

            Assert.Throws<CodexAppServerException>(() => probe.Run());

            // And through the gate, which is how the terminal host meets it: a probe that threw
            // is a refused start with the reason in it, never an unchecked CLI.
            ToolListingException refused = Assert.Throws<ToolListingException>(
                () => ToolListingGate.ForCodex(probe.Run).Verify());
            Assert.False(refused.Result.Matches);
        }
    }

    [Fact]
    public void TheProbeIsGivenTheGeneratedCodexHome()
    {
        using (var temp = new TempFolder())
        {
            string home = temp.Directory("codex-home");
            var probe = new CodexAppServerProbe(
                CliLaunch.ForExecutable(Path.Combine(Environment.SystemDirectory, "cmd.exe")),
                home,
                temp.Path);

            // The whole gate rests on this one variable: a probe run against the engineer's own
            // `%USERPROFILE%\.codex` would report the tools of a CLI that is not the one being
            // started.
            Assert.Equal(home, probe.Environment[CliProfileWriter.HomeVariable]);
        }
    }

    // ---- the replay child -------------------------------------------------------------------

    /// <summary>
    /// Answers the two requests the probe makes, by id, and then ends.
    ///
    /// The ids are fixed rather than echoed because the probe's ids are fixed: they are a
    /// constant of the conversation, and a script that echoed whatever it was sent would still
    /// pass if the probe stopped matching replies to requests at all.
    /// </summary>
    private const string ReplayScript = @"
$ErrorActionPreference = 'Stop'
$reply = (Get-Content -Raw -LiteralPath $env:SWREVIEW_TEST_REPLY).Trim()
while ($null -ne ($line = [Console]::In.ReadLine())) {
  if ($line -match '""method"":""initialize""') {
    [Console]::Out.WriteLine('" + InitializeReply + @"')
  } elseif ($line -match 'mcpServerStatus/list') {
    [Console]::Out.WriteLine($reply)
    break
  }
}
";

    // ---- helpers -----------------------------------------------------------------------------

    private static string ListReply(string listing) =>
        "{\"id\":2,\"result\":" + Normalize(listing) + "}";

    private static TextReader Transcript(params string[] lines) =>
        new StringReader(string.Join("\n", lines) + "\n");

    private static string Normalize(string json)
    {
        using (JsonDocument document = JsonDocument.Parse(json))
        {
            return JsonSerializer.Serialize(document.RootElement);
        }
    }

    private static List<JsonElement> Sent(string written) => written
        .Split('\n')
        .Where(line => line.Trim().Length > 0)
        .Select(line => JsonDocument.Parse(line).RootElement.Clone())
        .ToList();

    private static string Fixture(string name)
    {
        string path = Path.Combine(AppContext.BaseDirectory, "Fixtures", "ToolListing", name);
        Assert.True(File.Exists(path), $"{name} is missing from {Path.GetDirectoryName(path)}.");
        return File.ReadAllText(path);
    }

    /// <summary>A server that is up and says nothing - the case the timeout exists for.</summary>
    private sealed class BlockingReader : TextReader
    {
        private readonly ManualResetEventSlim _never = new ManualResetEventSlim(false);

        public override string? ReadLine()
        {
            _never.Wait(TimeSpan.FromSeconds(30));
            return null;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _never.Set();
                _never.Dispose();
            }

            base.Dispose(disposing);
        }
    }

    private sealed class TempFolder : IDisposable
    {
        public TempFolder()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(), "SwReview.Probe.Tests", Guid.NewGuid().ToString("N"));
            System.IO.Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public string Directory(string name)
        {
            string full = System.IO.Path.Combine(Path, name);
            System.IO.Directory.CreateDirectory(full);
            return full;
        }

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
                System.IO.Directory.Delete(Path, recursive: true);
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
