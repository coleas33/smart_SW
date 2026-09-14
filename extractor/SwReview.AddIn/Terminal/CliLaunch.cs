using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.AddIn.Native;

namespace SwReview.AddIn.Terminal;

/// <summary>
/// The resolved command that starts a CLI: an executable image plus the arguments that come
/// before the CLI's own (`data-model.md`, `TerminalSession.launch_command`).
///
/// It is a record rather than a string because of one Windows fact that has no workaround:
/// `CreateProcess` - which ConPTY requires, since only `CreateProcess` takes the
/// `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE` attribute - can start an *image* and nothing else.
/// A `.cmd` or `.bat` is not an image, it is input for `cmd.exe`; a `.ps1` is input for
/// PowerShell. npm installs its CLIs as shims, so `gemini` on an engineer's PATH is
/// `gemini.cmd`, and a session that passed that path to `CreateProcess` would fail with
/// ERROR_BAD_EXE_FORMAT on every machine that installed the CLI the ordinary way.
/// `System.Diagnostics.Process` hides this by going through `ShellExecute`, and that is
/// exactly the road not taken here.
///
/// The mapping lives on the record rather than in <see cref="CliLocator"/> (T055) because the
/// record is what the mapping produces, and because two callers need it: the `--version`
/// probe and the terminal session have to start the CLI the same way, or a version that
/// probed fine fails to launch.
/// </summary>
public sealed class CliLaunch
{
    private CliLaunch(string executable, IReadOnlyList<string> arguments, string toolPath)
    {
        Executable = executable;
        Arguments = arguments;
        ToolPath = toolPath;
    }

    /// <summary>The image `CreateProcess` starts: the CLI itself, or the shim's interpreter.</summary>
    public string Executable { get; }

    /// <summary>What precedes the CLI's own arguments - empty for an `.exe`, the interpreter's
    /// switches and the script path for a shim.</summary>
    public IReadOnlyList<string> Arguments { get; }

    /// <summary>The file that was resolved: the `.exe`, `.cmd` or `.ps1` on PATH. Shown to the
    /// engineer, because <see cref="Executable"/> for a shim is `cmd.exe` and tells them
    /// nothing about which CLI is running.</summary>
    public string ToolPath { get; }

    /// <summary>A launch for an image that is already executable, with optional arguments.</summary>
    public static CliLaunch ForExecutable(string executable, params string[] arguments)
    {
        if (string.IsNullOrWhiteSpace(executable))
        {
            throw new ArgumentException("an executable path is required", nameof(executable));
        }

        return new CliLaunch(
            executable, (arguments ?? Array.Empty<string>()).ToList(), executable);
    }

    /// <summary>
    /// Resolves a file found on PATH into the command that runs it.
    ///
    /// `.exe`/`.com` run directly; `.cmd`/`.bat` run as `cmd.exe /c "&lt;path&gt;"`; `.ps1` runs
    /// as `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "&lt;path&gt;"` - no profile
    /// because an engineer's profile can print a banner into the terminal or change the
    /// working directory, and Bypass because an unsigned npm shim is refused under the default
    /// machine policy.
    ///
    /// Anything else is reported rather than guessed at: a `.py` or extensionless file on PATH
    /// is a CLI we do not know how to start, and starting it through `cmd.exe` would let the
    /// shell's own file association decide - which is how a text editor ends up opening in a
    /// pseudo-console.
    /// </summary>
    /// <param name="path">The file to run. Relative paths are made absolute, because
    /// `CreateProcess` is given this as `lpApplicationName` and does not search PATH.</param>
    /// <param name="launch">The resolved command, or null.</param>
    /// <param name="unsupported">Why it could not be resolved, or null. Safe to show.</param>
    public static bool TryResolve(string path, out CliLaunch? launch, out string? unsupported)
    {
        launch = null;
        unsupported = null;

        if (string.IsNullOrWhiteSpace(path))
        {
            unsupported = "no path was given for the CLI";
            return false;
        }

        string full;
        try
        {
            full = Path.GetFullPath(path);
        }
        catch (Exception error) when (error is ArgumentException || error is NotSupportedException
            || error is PathTooLongException || error is IOException)
        {
            unsupported = $"'{path}' is not a usable path: {error.Message}";
            return false;
        }

        string extension = Path.GetExtension(full);
        switch (extension.ToLowerInvariant())
        {
            case ".exe":
            case ".com":
                launch = new CliLaunch(full, Array.Empty<string>(), full);
                return true;

            case ".cmd":
            case ".bat":
                launch = new CliLaunch(
                    SystemExecutable("cmd.exe"), new[] { "/c", full }, full);
                return true;

            case ".ps1":
                launch = new CliLaunch(
                    SystemExecutable(Path.Combine("WindowsPowerShell", "v1.0", "powershell.exe")),
                    new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", full },
                    full);
                return true;

            default:
                unsupported = string.IsNullOrEmpty(extension)
                    ? $"'{full}' has no extension, so there is no way to know how to run it; "
                      + "an .exe, .cmd, .bat or .ps1 is expected"
                    : $"'{extension}' is not a kind of file this pane can run; "
                      + "an .exe, .cmd, .bat or .ps1 is expected";
                return false;
        }
    }

    /// <summary>This launch with <paramref name="arguments"/> appended - the CLI's own
    /// arguments, which always follow the interpreter's.</summary>
    public CliLaunch With(params string[] arguments)
    {
        if (arguments == null || arguments.Length == 0)
        {
            return this;
        }

        return new CliLaunch(
            Executable, Arguments.Concat(arguments).ToList(), ToolPath);
    }

    /// <summary>The command line as `CreateProcess` will see it. For logs and errors.</summary>
    public override string ToString() => ChildProcess.BuildCommandLine(Executable, Arguments);

    /// <summary>
    /// A full path under `%SystemRoot%\System32`.
    ///
    /// Never the bare name: `CreateProcess` is given this as `lpApplicationName`, which is not
    /// searched for on PATH, and a bare `cmd.exe` resolved through the working directory is
    /// how a run folder containing a file called `cmd.exe` would take over the terminal.
    /// </summary>
    private static string SystemExecutable(string relative) =>
        Path.Combine(Environment.SystemDirectory, relative);
}
