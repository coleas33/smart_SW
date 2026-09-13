using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace SwReview.AddIn.Review;

/// <summary>
/// Names and creates run folders. The one place that decides what a run folder is called.
///
/// Two callers, one rule: <see cref="ReviewHost"/> creates
/// `&lt;run_root&gt;/&lt;yyyyMMdd-HHmmss&gt;-&lt;doc&gt;` when the engineer presses Review, and the
/// Terminal tab (T060) creates `&lt;run_root&gt;/&lt;yyyyMMdd-HHmmss&gt;-terminal` when it is
/// started with no review and no document open. They share this helper rather than each
/// formatting a timestamp, because the folder name is what the engineer sorts by in Explorer
/// and what `chat-log.jsonl`, `package.json` and `report.md` are found under; two formats
/// would be two conventions.
///
/// The folder is created, not just named: every caller writes into it immediately, and a
/// name handed back without the directory behind it would fail later, inside the extractor or
/// inside a CLI's working-directory switch, where the message no longer points here.
/// </summary>
public static class RunFolders
{
    /// <summary>
    /// How much of the document name the folder may spend. `meshes\&lt;body id&gt;.glb` goes
    /// underneath it and .NET Framework 4.8 still enforces MAX_PATH by default, so a 200
    /// character assembly name has to be cut here rather than fail on the first mesh.
    /// </summary>
    public const int MaxNameLength = 48;

    /// <summary>What the terminal-first run folder is called (pane-host-messages.md).</summary>
    public const string TerminalName = "terminal";

    private const string TimestampFormat = "yyyyMMdd-HHmmss";

    /// <summary>Creates the run folder for a review of <paramref name="documentPath"/>.</summary>
    public static string CreateForDocument(string runRoot, string? documentPath, DateTime timestamp) =>
        Create(runRoot, timestamp, DocumentName(documentPath));

    /// <summary>Creates the run folder for a terminal session started without a review.</summary>
    public static string CreateForTerminal(string runRoot, DateTime timestamp) =>
        Create(runRoot, timestamp, TerminalName);

    /// <summary>
    /// The document's file name, reduced to something a folder can be called.
    ///
    /// The path comes from SOLIDWORKS and is normally clean, so this is defensive: it parses
    /// by hand rather than through <c>Path.GetFileNameWithoutExtension</c>, which throws on
    /// invalid path characters in .NET Framework, because a strange path must not be the
    /// reason a review cannot start.
    /// </summary>
    public static string DocumentName(string? documentPath)
    {
        string name = documentPath ?? string.Empty;

        int separator = name.LastIndexOfAny(new[] { '\\', '/' });
        if (separator >= 0)
        {
            name = name.Substring(separator + 1);
        }

        int extension = name.LastIndexOf('.');
        if (extension >= 0)
        {
            name = name.Substring(0, extension);
        }

        char[] invalid = Path.GetInvalidFileNameChars();
        var cleaned = new StringBuilder(name.Length);
        foreach (char character in name)
        {
            cleaned.Append(Array.IndexOf(invalid, character) >= 0 ? '-' : character);
        }

        // Windows silently drops a trailing dot or space from a directory name, which would
        // make the folder the host reports back differ from the one on disk.
        string trimmed = cleaned.ToString().Trim(' ', '.', '-');
        if (trimmed.Length > MaxNameLength)
        {
            trimmed = trimmed.Substring(0, MaxNameLength).Trim(' ', '.', '-');
        }

        return trimmed.Length == 0 ? "document" : trimmed;
    }

    private static string Create(string runRoot, DateTime timestamp, string label)
    {
        if (string.IsNullOrWhiteSpace(runRoot))
        {
            throw new ArgumentException(
                "the run root is blank; set `run_root` in %APPDATA%\\SwReview\\settings.json.",
                nameof(runRoot));
        }

        string stem = timestamp.ToString(TimestampFormat, CultureInfo.InvariantCulture) + "-" + label;

        // Two reviews of the same document inside one second is a double-click, not an error,
        // and the second one must not be written into the first one's folder.
        string candidate = Path.Combine(runRoot, stem);
        for (int suffix = 2; Directory.Exists(candidate); suffix++)
        {
            candidate = Path.Combine(runRoot, stem + "-" + suffix.ToString(CultureInfo.InvariantCulture));
        }

        Directory.CreateDirectory(candidate);
        return candidate;
    }
}
