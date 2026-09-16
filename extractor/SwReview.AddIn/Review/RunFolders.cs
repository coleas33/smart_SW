using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

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

    /// <summary>
    /// What marks a Model check's run folder (`contracts/model-check.md` section 4).
    ///
    /// A suffix rather than a subfolder or a separate root, so the check folders sort beside
    /// the review they belong to in the one listing the engineer reads in Explorer, and so
    /// they are obviously the disposable ones.
    /// </summary>
    public const string CheckSuffix = "-check";

    private const string TimestampFormat = "yyyyMMdd-HHmmss";

    /// <summary>How much of `package.json` <see cref="ProfileOf"/> reads. `extractor` is the
    /// fourth property of the file and `profile` its last member, so the answer is inside the
    /// first few hundred bytes; this leaves room for a long machine name.</summary>
    private const int HeadBytes = 8 * 1024;

    private static readonly byte[] ExtractorProperty = Encoding.UTF8.GetBytes("extractor");
    private static readonly byte[] ProfileProperty = Encoding.UTF8.GetBytes("profile");

    /// <summary>Creates the run folder for a review of <paramref name="documentPath"/>.</summary>
    public static string CreateForDocument(string runRoot, string? documentPath, DateTime timestamp) =>
        Create(runRoot, timestamp, DocumentName(documentPath));

    /// <summary>
    /// Creates the run folder for one Model check of <paramref name="documentPath"/>.
    ///
    /// Its own folder, every time. Writing into the latest review's folder was weighed and
    /// rejected: the check's `package.json` would overwrite a review's full package, and the
    /// exception-accept command reads `session.json` by name, so a rotated check session would
    /// be unreachable from the command line. One reusable scratch folder was rejected for
    /// destroying the previous check's evidence, which is exactly what an engineer compares
    /// against after an edit. The accepted cost is one folder per press of the button.
    /// </summary>
    public static string CreateForCheck(string runRoot, string? documentPath, DateTime timestamp) =>
        Create(runRoot, timestamp, DocumentName(documentPath) + CheckSuffix);

    /// <summary>Creates the run folder for a terminal session started without a review.</summary>
    public static string CreateForTerminal(string runRoot, DateTime timestamp) =>
        Create(runRoot, timestamp, TerminalName);

    /// <summary>
    /// Whether a run folder already holds an evidence package.
    ///
    /// One definition of "this session has evidence", used by the step strip above the tabs,
    /// by `init.evidence` on the Ask page and by nothing else: two would be two answers to the
    /// same question on the same screen.
    ///
    /// A path that cannot even be combined is answered "no" rather than thrown at the caller:
    /// every caller is a repaint or a page message, and neither is a place to fail.
    /// </summary>
    public static bool HasEvidence(string? runDirectory)
    {
        if (string.IsNullOrWhiteSpace(runDirectory))
        {
            return false;
        }

        try
        {
            return File.Exists(Path.Combine(runDirectory, PackageWriter.PackageFileName));
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    /// <summary>
    /// Which dump profile wrote this run folder's package, or null when there is no readable
    /// answer - no folder, no `package.json`, a half-written one, a profile name this build
    /// does not know.
    ///
    /// One definition of "what kind of evidence this session has", beside
    /// <see cref="HasEvidence"/>'s "is there any", because the step strip asks both questions
    /// in the same repaint (T084, FR-022).
    ///
    /// <b>Only the head of the file is read.</b> `extractor` is the fourth property of a
    /// package and `profile` the last of its members, so the answer is in the first few
    /// hundred bytes; a full review package is tens of megabytes and this runs on the
    /// SOLIDWORKS application thread every time a tab is selected.
    /// <see cref="RunPackageIndex"/> deserializes the whole package because it needs the
    /// component and document tables and can cache them for the life of a run; a repaint can
    /// do neither, which is why this reader is a separate, bounded one rather than a second
    /// copy of that one.
    ///
    /// <b>Nothing here throws.</b> Every caller is a repaint.
    /// </summary>
    public static DumpProfile? ProfileOf(string? runDirectory)
    {
        if (string.IsNullOrWhiteSpace(runDirectory))
        {
            return null;
        }

        byte[] head;
        try
        {
            using (var file = new FileStream(
                Path.Combine(runDirectory!, PackageWriter.PackageFileName),
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite))
            {
                head = new byte[HeadBytes];

                // A stream may hand back less than it was asked for without being at its
                // end, so the head is filled rather than read once.
                int filled = 0;
                int read;
                while (filled < head.Length
                    && (read = file.Read(head, filled, head.Length - filled)) > 0)
                {
                    filled += read;
                }

                if (filled < head.Length)
                {
                    Array.Resize(ref head, filled);
                }
            }
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
        catch (ArgumentException)
        {
            return null;
        }
        catch (NotSupportedException)
        {
            return null;
        }

        try
        {
            return ReadProfile(head);
        }
        catch (JsonException)
        {
            // A package that is being written while it is being read is the ordinary case,
            // not a broken one: the strip repaints again when the dump ends.
            return null;
        }
    }

    /// <summary>
    /// `extractor.profile` out of the head of a package, or null when it is not in there.
    ///
    /// <paramref name="head"/> is the first <see cref="HeadBytes"/> of the file, so the
    /// reader is told the input is not final and simply runs out of tokens rather than
    /// reporting the truncation as broken JSON.
    /// </summary>
    private static DumpProfile? ReadProfile(byte[] head)
    {
        var reader = new Utf8JsonReader(head, isFinalBlock: false, state: default);
        bool inExtractor = false;

        while (reader.Read())
        {
            if (reader.TokenType != JsonTokenType.PropertyName)
            {
                continue;
            }

            if (reader.CurrentDepth == 1)
            {
                // The top level again: either this is `extractor`, or whatever object we
                // were in has ended and the profile was not in it.
                inExtractor = reader.ValueTextEquals(ExtractorProperty);
                continue;
            }

            if (!inExtractor || reader.CurrentDepth != 2 || !reader.ValueTextEquals(ProfileProperty))
            {
                continue;
            }

            return reader.Read() && reader.TokenType == JsonTokenType.String
                ? ProfileNamed(reader.GetString())
                : null;
        }

        return null;
    }

    /// <summary>
    /// The member whose contract name is <paramref name="name"/>, or null for one this build
    /// does not have. The names come from the serializer's own policy rather than from
    /// literals here, so the two cannot drift apart.
    /// </summary>
    private static DumpProfile? ProfileNamed(string? name)
    {
        if (name == null)
        {
            return null;
        }

        foreach (DumpProfile candidate in Enum.GetValues(typeof(DumpProfile)))
        {
            if (string.Equals(
                SnakeCaseLowerNamingPolicy.Instance.ConvertName(candidate.ToString()),
                name,
                StringComparison.Ordinal))
            {
                return candidate;
            }
        }

        return null;
    }

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
