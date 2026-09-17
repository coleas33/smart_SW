using System;
using System.Globalization;
using System.IO;
using System.Text;
using SwReview.Extractor.Dump;

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

    /// <summary>
    /// What marks a Standards check's run folder (`contracts/standards-check.md` section 4).
    ///
    /// A second suffix rather than a shared `-check` one, and that is the whole mechanism
    /// behind <see cref="NewestCheckFolder"/>: one enumeration of the run root answers "what is
    /// this tab's newest run" for each check tab <b>from the folder names alone</b>, so neither
    /// tab's latest check is ever the other tab's and `init` opens nothing. The `family` field
    /// inside `check.json` answers the other question - what a check id the backend was handed
    /// turns out to be - and the two mechanisms are not interchangeable.
    /// </summary>
    public const string StandardsSuffix = "-standards";

    /// <summary>
    /// What marks a re-modeler's run folder (`contracts/run-artifacts.md`).
    ///
    /// A suffix, for the same reasons as <see cref="CheckSuffix"/>: the folder sorts beside the
    /// review and the checks of the same document in the one listing the engineer reads in
    /// Explorer, and is obviously the disposable one. The folder's own name is also the run id
    /// written into `plan.json` and into the copy's `SwReviewRemodelRun` custom property, so it
    /// is spelled here and nowhere else.
    /// </summary>
    public const string RemodelSuffix = "-remodel";

    /// <summary>
    /// What a remodel run folder holds its reading of the copy under
    /// (`contracts/run-artifacts.md`).
    ///
    /// The extractor writes `package.json` and the add-in renames it, so a remodel folder never
    /// holds the name a review's folder does - and that folder becomes the pane's latest run,
    /// which is the folder <see cref="RunPackageIndex"/> resolves every `document_id` through.
    /// Spelled here because two places need it and a run artifact with two spellings is a run
    /// artifact one of them will stop finding.
    /// </summary>
    public const string PackageBeforeName = "package-before.json";

    private const string TimestampFormat = "yyyyMMdd-HHmmss";

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

    /// <summary>
    /// Creates the run folder for one Standards check of <paramref name="documentPath"/>.
    ///
    /// Its own folder, every time, for the reasons <see cref="CreateForCheck"/> gives, and named
    /// by the same rule so the two kinds of check sort beside the review they belong to in the
    /// one listing the engineer reads in Explorer.
    /// </summary>
    public static string CreateForStandards(string runRoot, string? documentPath, DateTime timestamp) =>
        Create(runRoot, timestamp, DocumentName(documentPath) + StandardsSuffix);

    /// <summary>
    /// The newest check run folder under <paramref name="runRoot"/> carrying
    /// <paramref name="suffix"/> (<see cref="CheckSuffix"/> or <see cref="StandardsSuffix"/>),
    /// or null when there is none.
    ///
    /// <b>The run root is enumerated and nothing inside it is opened.</b> This is called from
    /// `init`, which runs on every tab activation, and a `check.json` read per sibling folder
    /// would put one file read per check ever run on that path. A name comparison is free where
    /// a file read is not - and the name is all that is needed, because the folder's name <i>is</i>
    /// the check id the page hands to `GET /checks/{check_id}`
    /// (`contracts/standards-check.md` section 4).
    ///
    /// "Newest" is decided by the timestamp the name carries, then by the name itself, which is
    /// what puts a collision-suffixed `...-standards-2` after the `...-standards` of the same
    /// second. A folder whose name does not start with a run timestamp was not named here and
    /// is not a candidate.
    ///
    /// <b>Nothing here throws.</b> Every caller is a page message: a run root that is not there,
    /// cannot be combined or cannot be listed is answered "none", which is the same answer as
    /// an empty one and is equally true of a tab opened before the first run.
    /// </summary>
    public static string? NewestCheckFolder(string? runRoot, string suffix)
    {
        if (suffix == null)
        {
            throw new ArgumentNullException(nameof(suffix));
        }

        if (string.IsNullOrWhiteSpace(runRoot))
        {
            return null;
        }

        string[] directories;
        try
        {
            directories = Directory.Exists(runRoot)
                ? Directory.GetDirectories(runRoot)
                : new string[0];
        }
        catch (Exception failure)
            when (failure is IOException || failure is UnauthorizedAccessException
                || failure is ArgumentException)
        {
            return null;
        }

        string? newest = null;
        DateTime newestStamp = DateTime.MinValue;
        foreach (string directory in directories)
        {
            string name = Path.GetFileName(directory);
            if (!CarriesSuffix(name, suffix))
            {
                continue;
            }

            DateTime? stamp = TimestampOf(name);
            if (stamp == null)
            {
                continue;
            }

            if (newest == null
                || stamp.Value > newestStamp
                || (stamp.Value == newestStamp
                    && string.CompareOrdinal(name, Path.GetFileName(newest)) > 0))
            {
                newest = directory;
                newestStamp = stamp.Value;
            }
        }

        return newest;
    }

    /// <summary>
    /// The timestamp a run folder's name begins with, or null when it does not begin with one.
    ///
    /// The name is the run id, so this is the one place that reads it back, and it reads only
    /// the fixed-width prefix <see cref="Create"/> wrote.
    /// </summary>
    public static DateTime? TimestampOf(string? folderName)
    {
        if (folderName == null || folderName.Length < TimestampFormat.Length)
        {
            return null;
        }

        return DateTime.TryParseExact(
            folderName.Substring(0, TimestampFormat.Length),
            TimestampFormat,
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out DateTime parsed)
            ? parsed
            : (DateTime?)null;
    }

    /// <summary>
    /// Whether a folder name is one this helper named with <paramref name="suffix"/>: the
    /// suffix ends the name, or the collision suffix does - `...-standards-2` is the second
    /// standards run of that second, not a folder of some other kind.
    /// </summary>
    private static bool CarriesSuffix(string name, string suffix)
    {
        if (name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        int end = name.LastIndexOf('-');
        if (end <= 0 || end == name.Length - 1)
        {
            return false;
        }

        for (int index = end + 1; index < name.Length; index++)
        {
            if (!char.IsDigit(name[index]))
            {
                return false;
            }
        }

        return name.Substring(0, end).EndsWith(suffix, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Creates the run folder for one re-modeler run over <paramref name="documentPath"/>.
    ///
    /// Its own folder, every time, and the only place the `-remodel` convention is written. What
    /// goes inside it - `copy/` and the `-RMS.SLDPRT` name - belongs to
    /// <c>SwReview.Extractor.Rms.RemodelCopy</c>, so neither convention is spelled twice. The
    /// copy lives <b>only</b> under this folder and never beside the source: one bad path join
    /// beside a source inside an EPDM vault writes into the vault.
    /// </summary>
    public static string CreateForRemodel(string runRoot, string? documentPath, DateTime timestamp) =>
        Create(runRoot, timestamp, DocumentName(documentPath) + RemodelSuffix);

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
    /// <b>Only the head of the file is read</b>, and by <see cref="PackageIndex.HeadOf"/>,
    /// which is the same bounded read the reuse lookup makes and now the only copy of it: a
    /// full review package is tens of megabytes and this runs on the SOLIDWORKS application
    /// thread every time a tab is selected. <see cref="RunPackageIndex"/> deserializes the
    /// whole package because it needs the component and document tables and can cache them for
    /// the life of a run; a repaint can do neither.
    ///
    /// <b>Nothing here throws.</b> Every caller is a repaint.
    /// </summary>
    public static DumpProfile? ProfileOf(string? runDirectory) =>
        PackageIndex.HeadOf(runDirectory).Profile;

    /// <summary>
    /// The run folder whose package was dumped from this design, this way, or null (feature
    /// 005 lever 9, T091). The add-in's one door to the reuse lookup, beside its one door to
    /// naming a run folder, so the pane never learns the shape of the index itself.
    ///
    /// A miss is the ordinary answer and never an error: it costs the dump the lever was
    /// trying to skip.
    /// </summary>
    public static PackageIndexRow? FindReusable(string? runRoot, string reuseKey, DumpProfile profile) =>
        PackageIndex.FindReusable(runRoot, reuseKey, profile);

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
