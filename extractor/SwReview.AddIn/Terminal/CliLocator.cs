using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using SwReview.AddIn.Native;

namespace SwReview.AddIn.Terminal;

/// <summary>What the Terminal tab found when it looked for a CLI (T054/T055).</summary>
public enum CliStatus
{
    /// <summary>On PATH, startable, and new enough. The only status that starts a terminal.</summary>
    Ready,

    /// <summary>Installed and startable, but the terminal for it is not in this version
    /// (decision 2026-09-13: the Gemini terminal is deferred).</summary>
    Deferred,

    /// <summary>Nothing by that name on PATH.</summary>
    NotInstalled,

    /// <summary>A file by that name is on PATH, but it is not a kind this pane can start -
    /// the npm bash shim, typically (<see cref="CliLaunch.TryResolve"/>).</summary>
    Unsupported,

    /// <summary>Older than <see cref="CliDefinition.MinimumVersion"/>.</summary>
    TooOld,

    /// <summary>`--version` could not be run, or printed something with no version in it. Not
    /// a warning: a CLI whose version cannot be read through the resolved launch command is a
    /// CLI that will not start through it either.</summary>
    VersionUnreadable,
}

/// <summary>
/// One CLI the Terminal tab knows about: what it is called on PATH, what it needs to be, and
/// what to tell the engineer when it is not there.
/// </summary>
public sealed class CliDefinition
{
    internal CliDefinition(
        string name,
        string displayName,
        Version? minimumVersion,
        bool terminalSupported,
        string installSteps)
    {
        Name = name;
        DisplayName = displayName;
        MinimumVersion = minimumVersion;
        TerminalSupported = terminalSupported;
        InstallSteps = installSteps;
    }

    /// <summary>The settings spelling and the executable's base name: `codex`, `gemini`
    /// (`data-model.md`, `UserSettings.terminal_cli`).</summary>
    public string Name { get; }

    /// <summary>What the engineer calls it. Every message starts with this.</summary>
    public string DisplayName { get; }

    /// <summary>
    /// The oldest version this pane has been verified against, or null when none has been.
    ///
    /// Null is not "any version will do by accident": it is Gemini, whose profile is still
    /// unverified (`contracts/cli-profiles.md` leaves it to spike T055a). Refusing a version
    /// there would mean refusing on a number nobody has tested, and the Gemini terminal cannot
    /// start in this version anyway.
    /// </summary>
    public Version? MinimumVersion { get; }

    /// <summary>Whether a terminal can be started for it at all in this version.</summary>
    public bool TerminalSupported { get; }

    /// <summary>The install command, plus any prerequisite. Shown verbatim.</summary>
    public string InstallSteps { get; }
}

/// <summary>
/// What `&lt;cli&gt; --version` produced: its output, or the reason it could not be run.
///
/// Two fields rather than an exception because this crosses a boundary the pane cannot let
/// throw - a missing CLI, a shim that will not start and a CLI that hangs are all ordinary
/// states of an engineer's machine, and each of them has to become a sentence on the Terminal
/// tab rather than a stack trace in SOLIDWORKS.
/// </summary>
public sealed class CliVersionOutput
{
    private CliVersionOutput(string? text, string? failure)
    {
        Text = text;
        Failure = failure;
    }

    /// <summary>Everything the CLI printed - stdout and stderr together, because CLIs disagree
    /// about which one a version goes on.</summary>
    public string? Text { get; }

    /// <summary>Why the probe produced nothing usable, or null. Safe to show.</summary>
    public string? Failure { get; }

    public static CliVersionOutput FromText(string? text) => new CliVersionOutput(text, null);

    public static CliVersionOutput FromFailure(string failure) =>
        new CliVersionOutput(null, failure ?? "the version probe failed");
}

/// <summary>The answer for one CLI: whether the Terminal tab can start it, how, and what to
/// show when it cannot.</summary>
public sealed class CliDiscovery
{
    internal CliDiscovery(
        CliDefinition cli,
        CliStatus status,
        CliLaunch? launch,
        Version? version,
        string? versionText,
        string message)
    {
        Cli = cli;
        Status = status;
        Launch = launch;
        Version = version;
        VersionText = versionText;
        Message = message;
    }

    public CliDefinition Cli { get; }

    public CliStatus Status { get; }

    /// <summary>How to start it - the same command the `--version` probe used, minus
    /// `--version`. Null unless a startable file was found.</summary>
    public CliLaunch? Launch { get; }

    /// <summary>The parsed version, normalized to four components, or null.</summary>
    public Version? Version { get; }

    /// <summary>What `--version` printed, trimmed. Kept so a version that could not be parsed
    /// can be quoted back at the engineer instead of summarized away.</summary>
    public string? VersionText { get; }

    /// <summary>One complete sentence for the Terminal tab, install steps included. Never
    /// empty, whatever the status.</summary>
    public string Message { get; }

    /// <summary>Whether a terminal may be started from this. Only <see cref="CliStatus.Ready"/>
    /// says yes.</summary>
    public bool CanStart => Status == CliStatus.Ready;
}

/// <summary>
/// Finds the terminal CLIs on PATH, resolves how to start each one, and reads its version
/// (T055; FR-023 and spec scenario 4: a missing or too-old CLI is reported with the install
/// steps and the version requirement, not with an empty terminal).
///
/// Three things make this more than a `where.exe`:
///
/// <b>The search is by extension, in a fixed order.</b> npm installs a CLI as three files -
/// `codex`, `codex.cmd`, `codex.ps1` - and the extensionless one is a bash script that Windows
/// cannot run. PATHEXT is not the rule to follow either, because `.ps1` is not in the default
/// PATHEXT and the CLI would be missed on a machine that has only the PowerShell shim. So the
/// order is written down here: an image first, then the shims, then - if only an unrunnable
/// file is there - that file is named in the message rather than reported as "not installed",
/// which would send the engineer to reinstall something already installed.
///
/// <b>The version probe goes through the resolved launch command</b>
/// (<see cref="CliLaunch"/>), the same one <see cref="TerminalSession"/> starts. A probe that
/// shelled out on its own would disagree with the terminal about whether a CLI works, and the
/// disagreement would surface as a version that checked out followed by a terminal that never
/// opened.
///
/// <b>Nothing here throws at the caller</b> except for an unknown CLI name, which is a bug
/// rather than a machine state. A deleted PATH directory, a shim that will not start, a CLI
/// that hangs: each becomes a status and a sentence.
/// </summary>
public sealed class CliLocator
{
    /// <summary>
    /// The extensions that are tried, in the order they are tried.
    ///
    /// Exactly the ones <see cref="CliLaunch.TryResolve"/> knows how to start, and in
    /// preference order: a real image needs no interpreter between the pane and the CLI;
    /// `.cmd` before `.ps1` because `cmd.exe` starts faster than PowerShell and carries no
    /// execution-policy question with it.
    /// </summary>
    private static readonly IReadOnlyList<string> Extensions =
        new[] { ".exe", ".com", ".cmd", ".bat", ".ps1" };

    /// <summary>
    /// A version anywhere in the output: `0.115.0`, `v1.2.3`, `1.2.3-preview`.
    ///
    /// The output is searched rather than assumed to be one line, because a CLI can print a
    /// configuration warning above its version. Two or three components are accepted and any
    /// pre-release suffix is ignored for comparison - a `0.116.0-alpha` is treated as
    /// `0.116.0`, which is the generous direction and the right one: the engineer running a
    /// pre-release chose it.
    /// </summary>
    private static readonly Regex VersionPattern = new Regex(
        @"(?<![\w.])v?(?<n>\d{1,9}(?:\.\d{1,9}){1,3})(?![\d.])",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);

    /// <summary>How long <see cref="Probe"/> waits for `--version`. Generous, because the first
    /// run of a Node CLI on a cold file cache is slow and a false "not installed" is worse than
    /// a slow Terminal tab; short enough that a wedged CLI does not hold the tab for ever.</summary>
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(20);

    private static readonly IReadOnlyList<CliDefinition> KnownClis = new[]
    {
        new CliDefinition(
            "codex",
            "Codex CLI",
            // 0.115.0 is the version `contracts/cli-profiles.md` and research R4 were verified
            // against: the version on which `CODEX_HOME`, `--profile swreview` and the `-c`
            // overrides were observed to work. An older Codex may well accept the generated
            // profile, but nobody has watched it do so, and a profile that is silently ignored
            // is a CLI running without the read-only sandbox.
            new Version(0, 115, 0, 0),
            terminalSupported: true,
            "install it with `npm install -g @openai/codex` and sign in with `codex login`"),
        new CliDefinition(
            "gemini",
            "Gemini CLI",
            // No minimum: see CliDefinition.MinimumVersion.
            null,
            terminalSupported: false,
            "install Node 20 or later (22 recommended), then `npm install -g @google/gemini-cli`"),
    };

    private readonly IReadOnlyList<string> _searchPath;
    private readonly Func<CliLaunch, CliVersionOutput> _probe;

    /// <summary>The locator the pane uses: the process PATH, and a real `--version` run.</summary>
    public CliLocator()
        : this(PathDirectories(), launch => Probe(launch, ProbeTimeout))
    {
    }

    /// <param name="searchPath">Directories to look in, in order. Entries that are blank,
    /// quoted, unusable as paths or simply gone are skipped rather than rejected: all four are
    /// ordinary on a real machine's PATH.</param>
    /// <param name="probe">Runs `--version` for a resolved launch command.</param>
    public CliLocator(IEnumerable<string> searchPath, Func<CliLaunch, CliVersionOutput> probe)
    {
        if (searchPath == null)
        {
            throw new ArgumentNullException(nameof(searchPath));
        }

        _searchPath = searchPath.ToList();
        _probe = probe ?? throw new ArgumentNullException(nameof(probe));
    }

    /// <summary>The CLIs the Terminal tab knows, in the order the dropdown lists them. The same
    /// two values `UserSettings.terminal_cli` allows.</summary>
    public static IReadOnlyList<CliDefinition> Definitions => KnownClis;

    /// <summary>The definition for a settings `terminal_cli` value.</summary>
    /// <exception cref="ArgumentException">The name is not one of <see cref="Definitions"/>.
    /// `UserSettings` has already rejected anything else, so this is a programming error.
    /// </exception>
    public static CliDefinition Definition(string name)
    {
        CliDefinition? found = KnownClis.FirstOrDefault(
            cli => string.Equals(cli.Name, name, StringComparison.OrdinalIgnoreCase));
        if (found == null)
        {
            throw new ArgumentException(
                $"'{name}' is not a CLI this pane knows; expected one of "
                + string.Join(", ", KnownClis.Select(cli => cli.Name)),
                nameof(name));
        }

        return found;
    }

    /// <summary>Looks for one CLI.</summary>
    public CliDiscovery Locate(string name) => Locate(Definition(name));

    /// <summary>Looks for every CLI, in <see cref="Definitions"/> order - what the Terminal
    /// tab's dropdown is built from.</summary>
    public IReadOnlyList<CliDiscovery> LocateAll() => KnownClis.Select(Locate).ToList();

    /// <summary>
    /// The version in `--version` output, normalized to four components, or null when there
    /// is none to be found.
    ///
    /// Four components because <see cref="System.Version"/> compares a missing component as -1:
    /// left alone, `0.115` would be *older* than `0.115.0`, and a CLI would be refused for
    /// printing its version the short way.
    /// </summary>
    public static Version? ParseVersion(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        Match match = VersionPattern.Match(text);
        if (!match.Success)
        {
            return null;
        }

        int[] parts = match.Groups["n"].Value
            .Split('.')
            .Select(part => int.Parse(part, CultureInfo.InvariantCulture))
            .ToArray();

        return new Version(
            parts[0],
            parts.Length > 1 ? parts[1] : 0,
            parts.Length > 2 ? parts[2] : 0,
            parts.Length > 3 ? parts[3] : 0);
    }

    /// <summary>
    /// Runs a resolved launch command and returns what it printed.
    ///
    /// Through <see cref="ChildProcess"/> and a kill-on-close job, like everything else the
    /// pane starts: a `.cmd` shim is `cmd.exe` starting `node.exe`, so the thing to end when
    /// the CLI does not answer is the tree, not the process we hold a handle to. Both streams
    /// are drained on threads of their own, because a child that fills a pipe nobody is reading
    /// blocks on its next write and then the timeout below is the only thing left.
    /// </summary>
    /// <param name="launch">The command, `--version` already appended.</param>
    /// <param name="timeout">How long to wait before ending the tree.</param>
    public static CliVersionOutput Probe(CliLaunch launch, TimeSpan timeout)
    {
        if (launch == null)
        {
            throw new ArgumentNullException(nameof(launch));
        }

        var output = new StringBuilder();
        var gate = new object();
        var drained = new CountdownEvent(2);

        ChildProcess? child = null;
        JobObject? tree = null;
        try
        {
            tree = new JobObject();
            child = ChildProcess.StartSuspended(
                new ChildProcessStartInfo(launch.Executable, launch.Arguments), null, tree);

            Drain(child.StandardOutput, output, gate, drained);
            Drain(child.StandardError, output, gate, drained);

            child.Resume();

            if (!child.WaitForExit((int)Math.Max(0, timeout.TotalMilliseconds)))
            {
                return CliVersionOutput.FromFailure(
                    $"`{launch.ToolPath} --version` did not answer within "
                    + $"{timeout.TotalSeconds:0.#} seconds");
            }

            // The child is gone; its pipes close, so the readers end on their own. The wait is
            // bounded anyway - a reader that never ends must not hold the Terminal tab.
            drained.Wait(TimeSpan.FromSeconds(2));

            string text;
            lock (gate)
            {
                text = output.ToString().Trim();
            }

            if (text.Length == 0)
            {
                return CliVersionOutput.FromFailure(
                    $"`{launch.ToolPath} --version` printed nothing (exit code {child.ExitCode})");
            }

            return CliVersionOutput.FromText(text);
        }
        catch (Exception error)
        {
            return CliVersionOutput.FromFailure(
                $"`{launch.ToolPath} --version` could not be run: {error.Message}");
        }
        finally
        {
            // The job goes first: closing it ends the whole tree, which is what a timed-out
            // `cmd.exe` -> `node.exe` needs. Disposing the child alone would leave the grandchild.
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

    private CliDiscovery Locate(CliDefinition cli)
    {
        if (!TryFind(cli.Name, out CliLaunch? launch, out string? unrunnable))
        {
            return unrunnable == null
                ? new CliDiscovery(
                    cli,
                    CliStatus.NotInstalled,
                    null,
                    null,
                    null,
                    $"{cli.DisplayName} was not found on PATH. To use it, {cli.InstallSteps}"
                    + MinimumSuffix(cli) + ".")
                : new CliDiscovery(
                    cli,
                    CliStatus.Unsupported,
                    null,
                    null,
                    null,
                    $"{cli.DisplayName}: {unrunnable} To use it, {cli.InstallSteps}"
                    + MinimumSuffix(cli) + ".");
        }

        CliVersionOutput probed = _probe(launch!.With("--version"));
        if (probed.Failure != null)
        {
            return new CliDiscovery(
                cli,
                CliStatus.VersionUnreadable,
                launch,
                null,
                null,
                $"{cli.DisplayName} was found at {launch.ToolPath}, but its version could not "
                + $"be read: {probed.Failure}.");
        }

        string? versionText = probed.Text?.Trim();
        Version? version = ParseVersion(versionText);
        if (version == null)
        {
            return new CliDiscovery(
                cli,
                CliStatus.VersionUnreadable,
                launch,
                null,
                versionText,
                $"{cli.DisplayName} was found at {launch.ToolPath}, but `--version` printed no "
                + $"version number: {Quote(versionText)}.");
        }

        if (cli.MinimumVersion != null && version < cli.MinimumVersion)
        {
            return new CliDiscovery(
                cli,
                CliStatus.TooOld,
                launch,
                version,
                versionText,
                $"{cli.DisplayName} {version.ToString(3)} at {launch.ToolPath} is older than "
                + $"{cli.MinimumVersion.ToString(3)}, the oldest version this pane has been "
                + $"verified against. To update it, {cli.InstallSteps}.");
        }

        if (!cli.TerminalSupported)
        {
            return new CliDiscovery(
                cli,
                CliStatus.Deferred,
                launch,
                version,
                versionText,
                $"{cli.DisplayName} {version.ToString(3)} was found at {launch.ToolPath}, but "
                + "the terminal for it is deferred and not available in this version; choose "
                + "Codex CLI instead.");
        }

        return new CliDiscovery(
            cli,
            CliStatus.Ready,
            launch,
            version,
            versionText,
            $"{cli.DisplayName} {version.ToString(3)} at {launch.ToolPath}.");
    }

    /// <summary>
    /// Walks the search path for <paramref name="name"/>.
    /// </summary>
    /// <param name="unrunnable">Set when the only thing found is a file this pane cannot start
    /// - the npm bash shim, a `.py`. It is a sentence, not a path, because "not installed" and
    /// "installed in a form we cannot start" send the engineer to different places.</param>
    private bool TryFind(string name, out CliLaunch? launch, out string? unrunnable)
    {
        launch = null;
        unrunnable = null;

        foreach (string entry in _searchPath)
        {
            string? directory = Normalize(entry);
            if (directory == null)
            {
                continue;
            }

            foreach (string extension in Extensions)
            {
                string candidate = Path.Combine(directory, name + extension);
                if (!FileExists(candidate))
                {
                    continue;
                }

                if (CliLaunch.TryResolve(candidate, out launch, out string? why))
                {
                    return true;
                }

                // TryResolve knows every extension in Extensions, so this is unreachable short
                // of the two lists drifting apart. Report it rather than pretend nothing was
                // found, and keep looking.
                unrunnable = unrunnable ?? why;
                launch = null;
            }

            if (unrunnable == null && FileExists(Path.Combine(directory, name)))
            {
                // The npm bash shim: `codex` with no extension, next to the `.cmd` that is
                // missing here. Naming it is the difference between an engineer checking their
                // PATH and an engineer reinstalling a CLI they already have.
                unrunnable =
                    $"'{Path.Combine(directory, name)}' was found on PATH, but it is not a kind "
                    + "of file this pane can start; an .exe, .cmd, .bat or .ps1 is expected "
                    + "(npm installs one next to it).";
            }
        }

        return false;
    }

    private static string MinimumSuffix(CliDefinition cli) =>
        cli.MinimumVersion == null
            ? string.Empty
            : $" (version {cli.MinimumVersion.ToString(3)} or later)";

    private static string Quote(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return "nothing at all";
        }

        string one = text!.Replace("\r", " ").Replace("\n", " ").Trim();
        return one.Length > 200 ? "'" + one.Substring(0, 200) + "...'" : "'" + one + "'";
    }

    /// <summary>A PATH entry as a usable directory, or null. Quotes come off (`"C:\Program
    /// Files\x"` is a legal PATH entry); everything unusable is skipped.</summary>
    private static string? Normalize(string entry)
    {
        if (string.IsNullOrWhiteSpace(entry))
        {
            return null;
        }

        string trimmed = entry.Trim().Trim('"');
        if (trimmed.Length == 0)
        {
            return null;
        }

        try
        {
            return Path.GetFullPath(trimmed);
        }
        catch (Exception error) when (error is ArgumentException || error is NotSupportedException
            || error is PathTooLongException || error is IOException
            || error is System.Security.SecurityException)
        {
            return null;
        }
    }

    private static bool FileExists(string path)
    {
        try
        {
            return File.Exists(path);
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static IReadOnlyList<string> PathDirectories()
    {
        string path = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        return path.Split(';').ToList();
    }

    /// <summary>Reads a stream to end on a background thread, appending under
    /// <paramref name="gate"/> so the two readers cannot tear each other's writes.</summary>
    private static void Drain(
        StreamReader reader, StringBuilder into, object gate, CountdownEvent done)
    {
        var thread = new Thread(() =>
        {
            try
            {
                string? line;
                while ((line = reader.ReadLine()) != null)
                {
                    lock (gate)
                    {
                        into.AppendLine(line);
                    }
                }
            }
            catch (Exception)
            {
                // The pipe closed under us - the child is gone, which the wait above already
                // knows. Nothing on a background thread may throw: it would take SOLIDWORKS
                // down with it.
            }
            finally
            {
                try
                {
                    done.Signal();
                }
                catch (Exception)
                {
                }
            }
        })
        {
            IsBackground = true,
            Name = "swreview-cli-version",
        };
        thread.Start();
    }
}
