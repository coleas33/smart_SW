using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using SwReview.AddIn.Settings;

namespace SwReview.AddIn.Review;

/// <summary>
/// Finds the program that runs `swreview chat serve`.
///
/// There are exactly two supported shapes and no guessing between them, because a wrong guess
/// here produces a start failure whose message points at Python rather than at the setting
/// that caused it:
///
/// - <b>`swreview` itself</b> - the console script a `uv sync`, a `pip install` or a
///   `uv tool install` puts next to the interpreter. Run directly with no wrapper.
/// - <b>`uv`</b> - run as `uv run --project &lt;reviewer&gt; swreview ...`, which is how the
///   pilot workstation is set up (quickstart.md) and which resolves the project's own
///   environment without anything being activated.
///
/// The settings file's `python` field overrides the search and may name either of those, or an
/// interpreter - in which case the console script beside it is what gets run, because the
/// package has no `__main__`, so `python -m swreview` would fail with a message about modules
/// rather than about settings.
/// </summary>
public static class BackendLocator
{
    private const string ConsoleScript = "swreview";
    private const string Uv = "uv";

    /// <summary>Resolves using the settings override, the repository layout, and PATH.</summary>
    public static BackendCommand Resolve(UserSettings settings)
    {
        if (settings == null)
        {
            throw new ArgumentNullException(nameof(settings));
        }

        return Resolve(settings.Python, FindReviewerProject(), FindOnPath);
    }

    /// <summary>
    /// Resolves the launcher.
    /// </summary>
    /// <param name="overridePath">The settings file's `python` field; null or blank to search.</param>
    /// <param name="projectDirectory">The reviewer project `uv run --project` is pointed at;
    /// null to let uv resolve from the working directory.</param>
    /// <param name="onPath">Looks one executable name up on PATH; injected for the tests.</param>
    public static BackendCommand Resolve(
        string? overridePath, string? projectDirectory, Func<string, string?> onPath)
    {
        if (onPath == null)
        {
            throw new ArgumentNullException(nameof(onPath));
        }

        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            return FromOverride(overridePath!.Trim(), projectDirectory);
        }

        string? script = onPath(ConsoleScript);
        if (script != null)
        {
            return new BackendCommand(script, new string[0]);
        }

        string? uv = onPath(Uv);
        if (uv != null)
        {
            return UvCommand(uv, projectDirectory);
        }

        throw new BackendStartException(
            "the review backend could not be located: neither 'swreview' nor 'uv' is on PATH. "
            + "Install the reviewer package (`uv sync` in the reviewer folder), or set the "
            + "`python` field in %APPDATA%\\SwReview\\settings.json to uv.exe, to swreview.exe, "
            + "or to the python.exe of the environment that has it.");
    }

    /// <summary>The first `&lt;name&gt;.exe` (or `.cmd`, `.bat`) on PATH, or null.</summary>
    public static string? FindOnPath(string name)
    {
        string? path = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrEmpty(path))
        {
            return null;
        }

        foreach (string directory in path!.Split(Path.PathSeparator))
        {
            if (string.IsNullOrWhiteSpace(directory))
            {
                continue;
            }

            foreach (string extension in new[] { ".exe", ".cmd", ".bat" })
            {
                string candidate;
                try
                {
                    candidate = Path.Combine(directory.Trim(), name + extension);
                }
                catch (ArgumentException)
                {
                    // A PATH entry with invalid characters is not worth failing over.
                    break;
                }

                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
        }

        return null;
    }

    /// <summary>
    /// `&lt;repo&gt;\reviewer` found by walking up from the add-in assembly, or null.
    ///
    /// The pilot runs the add-in out of its build output inside the repository, which is the
    /// only layout in which `uv run --project` has anything to point at; a deployed add-in is
    /// expected to have `swreview` on PATH instead.
    /// </summary>
    public static string? FindReviewerProject()
    {
        string? directory;
        try
        {
            directory = Path.GetDirectoryName(new Uri(typeof(BackendLocator).Assembly.CodeBase!).LocalPath);
        }
        catch (Exception failure) when (failure is UriFormatException || failure is ArgumentException)
        {
            directory = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        }

        while (!string.IsNullOrEmpty(directory))
        {
            string candidate = Path.Combine(directory!, "reviewer");
            if (File.Exists(Path.Combine(candidate, "pyproject.toml")))
            {
                return candidate;
            }

            directory = Path.GetDirectoryName(directory!);
        }

        return null;
    }

    private static BackendCommand FromOverride(string overridePath, string? projectDirectory)
    {
        if (!File.Exists(overridePath))
        {
            throw new BackendStartException(
                $"the `python` setting names '{overridePath}', which does not exist. Point it at "
                + "uv.exe, at swreview.exe, or at the python.exe of the environment that has the "
                + "reviewer package installed - or clear it to search PATH.");
        }

        string name = Path.GetFileNameWithoutExtension(overridePath) ?? string.Empty;
        if (string.Equals(name, Uv, StringComparison.OrdinalIgnoreCase))
        {
            return UvCommand(overridePath, projectDirectory);
        }

        if (string.Equals(name, ConsoleScript, StringComparison.OrdinalIgnoreCase))
        {
            return new BackendCommand(overridePath, new string[0]);
        }

        // An interpreter: the console script lives beside it, or in its Scripts folder.
        string directory = Path.GetDirectoryName(overridePath) ?? string.Empty;
        var looked = new List<string>();
        foreach (string candidate in new[]
        {
            Path.Combine(directory, ConsoleScript + ".exe"),
            Path.Combine(directory, "Scripts", ConsoleScript + ".exe"),
        })
        {
            looked.Add(candidate);
            if (File.Exists(candidate))
            {
                return new BackendCommand(candidate, new string[0]);
            }
        }

        throw new BackendStartException(
            $"the `python` setting names the interpreter '{overridePath}', but the swreview "
            + "console script is not installed in it - looked for "
            + string.Join(" and ", looked.ToArray())
            + ". Run `uv sync` in the reviewer folder, or point the setting at uv.exe instead.");
    }

    private static BackendCommand UvCommand(string uv, string? projectDirectory)
    {
        var arguments = new List<string> { "run" };
        if (!string.IsNullOrWhiteSpace(projectDirectory))
        {
            arguments.Add("--project");
            arguments.Add(projectDirectory!);
        }

        arguments.Add(ConsoleScript);
        return new BackendCommand(uv, arguments);
    }
}
