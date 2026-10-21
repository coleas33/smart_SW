using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
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
///
/// <b>In its full, long-name form</b> (owner decisions 148A and 160A; feature 011 research R12.3): every folder
/// made, and every folder found, is named under the existing run root's long-name form, whatever spelling
/// of it the setting holds. The folder is handed on as
/// it is named: to the backend, whose rule for a run folder refuses a <c>..</c> segment rather than
/// resolve it, to the bridge's bind, and, as the folder of a re-modeler's copy, to the pane seat,
/// whose rule for the copy's path refuses one too - so under a run root spelled
/// <c>C:\work\..\runs</c> a folder named as it was spelled ended every plan before it began
/// (research R11.8 item 5). A folder made and the same folder found are spelled one way, which the
/// review host's comparison of a removed review's folder with the one its search finds relies on.
/// </summary>
public static class RunFolders
{
    /// <summary>The top-level model status in the bounded head, or no readable answer.</summary>
    public static JsonElement? ReadModelStatus(string? runDirectory, Func<string, Stream>? openHead = null) =>
        ReadSessionHead(runDirectory, openHead, readSessionId: false, out _);

    private static JsonElement? ReadSessionHead(
        string? runDirectory, Func<string, Stream>? openHead, bool readSessionId, out string? sessionId)
    {
        sessionId = null;
        if (string.IsNullOrWhiteSpace(runDirectory)) return null;
        try
        {
            byte[] head;
            using (Stream stream = (openHead ?? OpenSessionHead)(Path.Combine(runDirectory!, "session.json")))
            {
                head = PackageIndex.FillHead(stream, 65536);
            }
            var reader = new Utf8JsonReader(head, isFinalBlock: false, state: default);
            while (reader.Read())
            {
                if (reader.TokenType != JsonTokenType.PropertyName || reader.CurrentDepth != 1) continue;
                if (readSessionId && reader.ValueTextEquals("session_id"))
                {
                    if (reader.Read() && reader.TokenType == JsonTokenType.String)
                    {
                        sessionId = reader.GetString();
                    }
                    continue;
                }
                if (!reader.ValueTextEquals("model_status")) continue;
                if (!reader.Read() || reader.TokenType != JsonTokenType.StartObject) return null;
                if (!JsonDocument.TryParseValue(ref reader, out JsonDocument? status)) return null;
                using (status) { return status.RootElement.Clone(); }
            }
        }
        catch (Exception)
        {
            // A missing, replaced, half-written or unreadable head keeps the existing mark.
        }
        return null;
    }

    internal static Stream OpenSessionHead(string path) => new FileStream(
        path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);

    /// <summary>
    /// A waiting review of this document, from the newest matching review folder only.
    /// Names decide the candidate before its one bounded session head is opened; a sent,
    /// missing or unreadable head never falls back to an older waiting review. Nothing throws.
    /// </summary>
    public static SessionRecord? FindNotSentReview(
        string? runRoot, PageDocument document, Func<string, Stream>? openHead = null, IRunRootProbe? probe = null)
    {
        if (string.IsNullOrWhiteSpace(runRoot)) return null;
        try
        {
            string? root = ExistingLongRoot(runRoot!, probe);
            if (root == null) return null;
            string label = "-" + DocumentName(document.Path);
            string? newest = null;
            DateTime newestStamp = DateTime.MinValue;
            foreach (string directory in Directory.EnumerateDirectories(root))
            {
                string name = Path.GetFileName(directory);
                DateTime? stamp = TimestampOf(name);
                if (stamp == null || CarriesSuffix(name, CheckSuffix)
                    || CarriesSuffix(name, StandardsSuffix) || CarriesSuffix(name, RemodelSuffix)) continue;

                string stem = name.Substring(0, TimestampFormat.Length) + label;
                if (!string.Equals(name, stem, StringComparison.OrdinalIgnoreCase)
                    && !(name.StartsWith(stem + "-", StringComparison.OrdinalIgnoreCase)
                        && name.LastIndexOf('-') == stem.Length && CarriesSuffix(name, label))) continue;

                if (newest == null || stamp.Value > newestStamp
                    || (stamp.Value == newestStamp && string.CompareOrdinal(name, Path.GetFileName(newest)) > 0))
                {
                    newest = directory;
                    newestStamp = stamp.Value;
                }
            }
            if (newest == null) return null;

            JsonElement? status = ReadSessionHead(newest, openHead, readSessionId: true, out string? sessionId);
            if (!status.HasValue || string.IsNullOrWhiteSpace(sessionId)) return null;
            JsonElement value = status.Value;
            string? state = HeadText(value, "state");
            if (state != "not_sent" && state != "send_failed") return null;
            if (!value.TryGetProperty("document", out JsonElement saved)
                || saved.ValueKind != JsonValueKind.Object) return null;
            string? path = HeadText(saved, "path");
            string? configuration = HeadText(saved, "configuration");
            if (!document.IsSameDocument(path, configuration)) return null;
            if (!DateTimeOffset.TryParse(HeadText(value, "checked_at"), CultureInfo.InvariantCulture,
                DateTimeStyles.None, out DateTimeOffset checkedAt)) return null;

            return new SessionRecord(sessionId!, newest, new PageDocument(path!, configuration), checkedAt)
            {
                ModelStatus = state,
            };
        }
        catch (Exception)
        {
            // A root or head that cannot be read offers no review.
            return null;
        }
    }

    private static string? HeadText(JsonElement value, string name) =>
        value.TryGetProperty(name, out JsonElement member) && member.ValueKind == JsonValueKind.String
            ? member.GetString() : null;

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
    public static string CreateForDocument(string runRoot, string? documentPath, DateTime timestamp, IRunRootProbe? probe = null) =>
        Create(runRoot, timestamp, DocumentName(documentPath), probe);

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
    public static string CreateForCheck(string runRoot, string? documentPath, DateTime timestamp, IRunRootProbe? probe = null) =>
        Create(runRoot, timestamp, DocumentName(documentPath) + CheckSuffix, probe);

    /// <summary>
    /// Creates the run folder for one Standards check of <paramref name="documentPath"/>.
    ///
    /// Its own folder, every time, for the reasons <see cref="CreateForCheck"/> gives, and named
    /// by the same rule so the two kinds of check sort beside the review they belong to in the
    /// one listing the engineer reads in Explorer.
    /// </summary>
    public static string CreateForStandards(string runRoot, string? documentPath, DateTime timestamp, IRunRootProbe? probe = null) =>
        Create(runRoot, timestamp, DocumentName(documentPath) + StandardsSuffix, probe);

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
    public static string? NewestCheckFolder(string? runRoot, string suffix, IRunRootProbe? probe = null)
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
            string? root = ExistingLongRoot(runRoot!, probe);
            directories = root == null ? new string[0] : Directory.GetDirectories(root);
        }
        catch (Exception failure)
            when (failure is IOException || failure is UnauthorizedAccessException
                || failure is ArgumentException || failure is NotSupportedException
                || failure is System.Security.SecurityException)
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
    public static string CreateForRemodel(string runRoot, string? documentPath, DateTime timestamp, IRunRootProbe? probe = null) =>
        Create(runRoot, timestamp, DocumentName(documentPath) + RemodelSuffix, probe);

    /// <summary>Creates the run folder for a terminal session started without a review.</summary>
    public static string CreateForTerminal(string runRoot, DateTime timestamp, IRunRootProbe? probe = null) =>
        Create(runRoot, timestamp, TerminalName, probe);

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

    private static string Create(string runRoot, DateTime timestamp, string label, IRunRootProbe? probe)
    {
        if (string.IsNullOrWhiteSpace(runRoot))
        {
            throw new ArgumentException(
                "the run root is blank; set `run_root` in %APPDATA%\\SwReview\\settings.json.",
                nameof(runRoot));
        }

        string stem = timestamp.ToString(TimestampFormat, CultureInfo.InvariantCulture) + "-" + label;

        // The caller has judged the root before anything is made (154A). Once it exists, read its
        // long name once, outside any lock, so the backend and the re-modeler's seat name it alike (160A).
        string root = FullFormOf(runRoot);
        Directory.CreateDirectory(root);
        root = (probe ?? Native.WindowsRunRootProbe.Instance).LongPathOf(root)
            ?? throw new IOException("The run root's long name could not be read.");

        // Two reviews of the same document inside one second is a double-click, not an error,
        // and the second one must not be written into the first one's folder.
        string candidate = Path.Combine(root, stem);
        for (int suffix = 2; Directory.Exists(candidate); suffix++)
        {
            candidate = Path.Combine(root, stem + "-" + suffix.ToString(CultureInfo.InvariantCulture));
        }

        Directory.CreateDirectory(candidate);
        return candidate;
    }

    /// <summary>
    /// The run root in its full form - <c>Path.GetFullPath</c>: canonical, rooted, with no <c>.</c> or
    /// <c>..</c> segment and a backslash between segments - the one form every folder this class makes or
    /// is compared under (owner decision 148A). A root that names no folder throws here as it would
    /// below. The run root rule judges the same folder from the root's
    /// text without reading anything (owner decision 154A and its reviews, <see cref="RunRootRule"/>), where
    /// this form can expand an 8.3 short name by reading the folders of the path - and, under the newer path
    /// handling, can leave one as written. Creation and searches therefore read the existing root's long
    /// form explicitly, outside any lock (decision 160A), before any run folder is named under it.
    /// </summary>
    private static string FullFormOf(string runRoot) => Path.GetFullPath(runRoot);

    /// <summary>
    /// The search's root in its long-name form, only after the run-root rule has checked every existing
    /// ancestor. Searches can run before a run start has judged the root; no long-name lookup or enumeration
    /// may read over a share or through a link. The rule's final-path reading already names an existing root
    /// in long names, and its 8.3 comparison reads that long name once, so reuse that answer.
    /// </summary>
    private static string? ExistingLongRoot(string runRoot, IRunRootProbe? probe)
    {
        IRunRootProbe source = probe ?? Native.WindowsRunRootProbe.Instance;
        return RunRootRule.Judge(runRoot, source, out string? root) == RunRootVerdict.Accepted ? root : null;
    }

    /// <summary>
    /// Whether <paramref name="folder"/> is <paramref name="runRoot"/> or lies below it, each in its full form,
    /// ignoring letter case; false when either has none. What a run's folder is held to before it is handed to
    /// the backend, which makes runs only under the run root it was started with, and what a folder the pane
    /// opens is held to (owner decision 154A, the reviews' finding F6). A mismatch also checks the existing
    /// root's verified long form, outside callers' locks, since decision 160A names new folders that way even
    /// when the setting keeps an 8.3 spelling. The usual lexical match needs no additional disk reading.
    /// </summary>
    internal static bool IsUnder(string folder, string runRoot, IRunRootProbe? probe = null)
    {
        string fullFolder;
        string fullRoot;
        try
        {
            fullFolder = Path.GetFullPath(folder);
            fullRoot = FullFormOf(runRoot);
        }
        catch (Exception failure) when (failure is ArgumentException || failure is NotSupportedException
            || failure is PathTooLongException || failure is System.Security.SecurityException)
        {
            return false;
        }

        if (IsWithin(fullFolder, fullRoot)) return true;

        try
        {
            string? longRoot = ExistingLongRoot(fullRoot, probe);
            return longRoot != null && IsWithin(fullFolder, longRoot);
        }
        catch (Exception failure) when (failure is IOException || failure is UnauthorizedAccessException
            || failure is ArgumentException || failure is NotSupportedException || failure is System.Security.SecurityException)
        {
            return false;
        }
    }

    private static bool IsWithin(string fullFolder, string fullRoot)
    {
        string trimmed = fullRoot.TrimEnd(Path.DirectorySeparatorChar);
        if (string.Equals(trimmed, fullFolder.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return fullFolder.StartsWith(trimmed + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }
}
