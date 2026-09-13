using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
using SwReview.AddIn.Review;

namespace SwReview.AddIn.Tests;

/// <summary>
/// A stand-in for `swreview chat serve` that <see cref="BackendProcessTests"/> and
/// <see cref="ProcessLifetimeTests"/> both drive.
///
/// It is a PowerShell script rather than a `.cmd` on purpose: `cmd.exe /c` re-parses its own
/// command line and strips quotes in ways that depend on how many quoted arguments follow, so
/// a temporary path containing a space (`C:\Users\First Last\AppData\...`) would make the
/// stub fail on some machines and pass on ours. `powershell.exe -File` parses arguments with
/// ordinary rules. Everything the stub does is driven by environment variables, so the
/// arguments on its command line are exactly the ones <see cref="BackendProcess"/> built -
/// which is what the "no key on the command line" assertion reads back.
/// </summary>
internal sealed class StubBackend : IDisposable
{
    /// <summary>What the stub prints when it is asked to hand shake.</summary>
    public const string DefaultToken = "0FAKEtoken_for_tests-0123456789AbCdEfGhIjKlMnOpQrSt";

    private const string Script = @"
param([Parameter(ValueFromRemainingArguments = $true)] $Rest)
$ErrorActionPreference = 'Stop'

if ($env:SWREVIEW_STUB_CMDLINE) {
    Set-Content -LiteralPath $env:SWREVIEW_STUB_CMDLINE -Value ([Environment]::CommandLine) -Encoding ascii
}
if ($env:SWREVIEW_STUB_ENVDUMP) {
    $lines = @(
        ""OPENAI_API_KEY=$($env:OPENAI_API_KEY)"",
        ""GEMINI_API_KEY=$($env:GEMINI_API_KEY)"",
        ""GOOGLE_API_KEY=$($env:GOOGLE_API_KEY)"",
        ""OPENAI_BASE_URL=$($env:OPENAI_BASE_URL)"",
        ""GOOGLE_CLOUD_PROJECT=$($env:GOOGLE_CLOUD_PROJECT)"",
        ""GOOGLE_CLOUD_LOCATION=$($env:GOOGLE_CLOUD_LOCATION)"",
        ""GOOGLE_GENAI_USE_ENTERPRISE=$($env:GOOGLE_GENAI_USE_ENTERPRISE)"",
        ""GOOGLE_GENAI_USE_VERTEXAI=$($env:GOOGLE_GENAI_USE_VERTEXAI)"")
    Set-Content -LiteralPath $env:SWREVIEW_STUB_ENVDUMP -Value $lines -Encoding ascii
}
if ($env:SWREVIEW_STUB_BREAK) {
    # A native console control handler, not [Console]::CancelKeyPress: the managed event runs
    # a delegate on the runspace, and this runspace spends its life inside Start-Sleep, so the
    # handler would never get to run. SetConsoleCtrlHandler is called on a thread the OS
    # injects and needs nothing from PowerShell.
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;

public static class StubBreak
{
    public delegate bool Handler(uint controlType);

    private static Handler _handler;
    private static string _path;

    [DllImport(""kernel32.dll"", SetLastError = true)]
    private static extern bool SetConsoleCtrlHandler(Handler handler, bool add);

    public static void Install(string path)
    {
        _path = path;
        _handler = OnControl;
        SetConsoleCtrlHandler(_handler, true);
    }

    private static bool OnControl(uint controlType)
    {
        File.WriteAllText(_path, controlType.ToString());
        Environment.Exit(0);
        return true;
    }
}
'@
    [StubBreak]::Install($env:SWREVIEW_STUB_BREAK)
}
if ($env:SWREVIEW_STUB_GRANDCHILD) {
    $self = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    $spawned = Start-Process -FilePath $self -PassThru -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 3600')
    Set-Content -LiteralPath $env:SWREVIEW_STUB_GRANDCHILD -Value $spawned.Id -Encoding ascii
}
if ($env:SWREVIEW_STUB_MARKER) {
    Set-Content -LiteralPath $env:SWREVIEW_STUB_MARKER -Value 'ran' -Encoding ascii
}
if ($env:SWREVIEW_STUB_STDERR) {
    [Console]::Error.WriteLine($env:SWREVIEW_STUB_STDERR)
}
if ($env:SWREVIEW_STUB_EXIT_CODE) {
    exit [int]$env:SWREVIEW_STUB_EXIT_CODE
}
if ($env:SWREVIEW_STUB_HANDSHAKE) {
    [Console]::Out.WriteLine($env:SWREVIEW_STUB_HANDSHAKE)
}
if ($env:SWREVIEW_STUB_EXTRA_STDOUT) {
    [Console]::Out.WriteLine($env:SWREVIEW_STUB_EXTRA_STDOUT)
}
while ($true) { Start-Sleep -Seconds 3600 }
";

    private readonly string _root;

    public StubBackend()
    {
        // No space in the folder name and no reliance on 8.3 short names: the assertions
        // below compare the child's command line against paths we build here.
        _root = Path.Combine(Path.GetTempPath(), "SwReview.Backend.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
        RunRoot = Path.Combine(_root, "runs");
        Directory.CreateDirectory(RunRoot);

        ScriptPath = Path.Combine(_root, "stub-backend.ps1");
        File.WriteAllText(ScriptPath, Script, new UTF8Encoding(false));

        MarkerPath = Path.Combine(_root, "marker.txt");
        CommandLinePath = Path.Combine(_root, "commandline.txt");
        EnvironmentDumpPath = Path.Combine(_root, "environment.txt");
        BreakPath = Path.Combine(_root, "break.txt");
        GrandchildPath = Path.Combine(_root, "grandchild.txt");
        LogPath = Path.Combine(_root, "backend.log");

        Command = new BackendCommand(
            Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe"),
            new[] { "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ScriptPath });
    }

    /// <summary>The executable and leading arguments <see cref="BackendProcess"/> starts.</summary>
    public BackendCommand Command { get; }

    public string ScriptPath { get; }

    public string RunRoot { get; }

    public string LogPath { get; }

    /// <summary>Written by the stub as its first act; absent while the child is suspended.</summary>
    public string MarkerPath { get; }

    public string CommandLinePath { get; }

    public string EnvironmentDumpPath { get; }

    /// <summary>Written by the stub when it is asked to shut down; absent if it was only killed.</summary>
    public string BreakPath { get; }

    public string GrandchildPath { get; }

    /// <summary>The knobs above, plus whatever the test adds, as the child's environment.</summary>
    public Dictionary<string, string> Knobs { get; } = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>Print a well-formed handshake line and then stay alive until killed.</summary>
    public StubBackend PrintsHandshake(int port = 51234, string token = DefaultToken)
    {
        Knobs["SWREVIEW_STUB_HANDSHAKE"] = "{\"port\": " + port + ", \"token\": \"" + token + "\"}";
        return this;
    }

    /// <summary>Print nothing at all, so the handshake read has to time out.</summary>
    public StubBackend PrintsNothing()
    {
        Knobs.Remove("SWREVIEW_STUB_HANDSHAKE");
        return this;
    }

    /// <summary>Print <paramref name="line"/> instead of a handshake.</summary>
    public StubBackend PrintsRawLine(string line)
    {
        Knobs["SWREVIEW_STUB_HANDSHAKE"] = line;
        return this;
    }

    /// <summary>Print a second stdout line after the handshake (the contract forbids it; the
    /// pane must not break on a backend that does it anyway).</summary>
    public StubBackend AlsoPrints(string line)
    {
        Knobs["SWREVIEW_STUB_EXTRA_STDOUT"] = line;
        return this;
    }

    /// <summary>Write <paramref name="line"/> to stderr, which the host logs.</summary>
    public StubBackend WritesToStandardError(string line)
    {
        Knobs["SWREVIEW_STUB_STDERR"] = line;
        return this;
    }

    /// <summary>Exit with <paramref name="code"/> before printing anything.</summary>
    public StubBackend ExitsWith(int code)
    {
        Knobs["SWREVIEW_STUB_EXIT_CODE"] = code.ToString();
        return this;
    }

    /// <summary>Record the child's own command line for the "no key in arguments" assertion.</summary>
    public StubBackend RecordsItsCommandLine()
    {
        Knobs["SWREVIEW_STUB_CMDLINE"] = CommandLinePath;
        return this;
    }

    /// <summary>Record the credential variables the child actually received.</summary>
    public StubBackend RecordsItsEnvironment()
    {
        Knobs["SWREVIEW_STUB_ENVDUMP"] = EnvironmentDumpPath;
        return this;
    }

    /// <summary>
    /// Handle the console break the host sends for a graceful stop: write
    /// <see cref="BreakPath"/> and exit. This is the stub's stand-in for uvicorn's own
    /// `SIGBREAK` handler, which is what runs the lifespan that finalizes every live chat.
    /// </summary>
    public StubBackend SignalsOnBreak()
    {
        Knobs["SWREVIEW_STUB_BREAK"] = BreakPath;
        return this;
    }

    /// <summary>
    /// Start a grandchild that sleeps for an hour and record its pid, the way
    /// `uv run ... swreview chat serve` leaves the real HTTP server a generation below the
    /// process the host holds a handle to.
    /// </summary>
    public StubBackend SpawnsAGrandchild()
    {
        Knobs["SWREVIEW_STUB_GRANDCHILD"] = GrandchildPath;
        return this;
    }

    /// <summary>Touch <see cref="MarkerPath"/> as the very first thing the child does.</summary>
    public StubBackend RecordsThatItRan()
    {
        Knobs["SWREVIEW_STUB_MARKER"] = MarkerPath;
        return this;
    }

    public string ReadCommandLine() => ReadWhenWritten(CommandLinePath);

    public string ReadEnvironmentDump() => ReadWhenWritten(EnvironmentDumpPath);

    /// <summary>The pid of the grandchild <see cref="SpawnsAGrandchild"/> started.</summary>
    public int ReadGrandchildProcessId() =>
        int.Parse(ReadWhenWritten(GrandchildPath).Trim(), CultureInfo.InvariantCulture);

    public string ReadLog() => File.Exists(LogPath) ? ReadShared(LogPath) : string.Empty;

    /// <summary>Waits for a file the child writes; the child is a real process, so every
    /// assertion about what it did has to allow for its start-up.</summary>
    public static bool Waits(Func<bool> condition, int milliseconds = 20000)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(milliseconds);
        while (DateTime.UtcNow < deadline)
        {
            if (condition())
            {
                return true;
            }

            Thread.Sleep(25);
        }

        return condition();
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
            // A killed child can still hold its script open for a moment; cleanup is not the test.
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private static string ReadWhenWritten(string path)
    {
        if (!Waits(() => File.Exists(path)))
        {
            throw new IOException($"the stub backend never wrote {path}");
        }

        return ReadShared(path);
    }

    private static string ReadShared(string path)
    {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (var reader = new StreamReader(stream))
        {
            return reader.ReadToEnd();
        }
    }
}
