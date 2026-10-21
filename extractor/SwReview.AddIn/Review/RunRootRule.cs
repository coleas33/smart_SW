using System;

namespace SwReview.AddIn.Review;

/// <summary>What <see cref="RunRootRule"/> found of a run root (owner decision 154A).</summary>
public enum RunRootVerdict
{
    /// <summary>
    /// Nothing the rule refuses: a local folder reached by its own path - or a root the rule cannot read at
    /// all (blank, with no full form, on a drive letter that names no drive), which it leaves to the run
    /// folder, whose making reports it as it always has.
    /// </summary>
    Accepted,

    /// <summary>On a network share: written as a UNC path, on a mapped network drive, or with its final path on a share.</summary>
    Share,

    /// <summary>
    /// Reached through a link: on a substituted drive, with a junction or a symbolic link among its existing
    /// folders, or with a final path that differs from its full path other than by letter case.
    /// </summary>
    Link,

    /// <summary>Written as a Windows device path (<c>\\?\C:\...</c>, <c>\\.\...</c>), which the backend refuses with a UNC path.</summary>
    DevicePath,

    /// <summary>
    /// Could not be checked (the reviews of decision 154A, finding F2): a part of its path that is there
    /// cannot be read as itself, or its nearest existing folder's final path or long name cannot be read - so
    /// whether it is reached through a link cannot be told, and a link to a share can lie below a folder whose
    /// attributes are denied while Windows still lets every user pass through it.
    /// </summary>
    Unverified,

    /// <summary>
    /// Has a folder whose name ends in a space or a period (the reviews of 154A's merge, finding F1), which Windows
    /// reads two ways: <c>GetFullPathNameW</c> and the backend's own resolution keep <c>Work </c> and <c>Work..</c>
    /// as written, while .NET's legacy path handling - SOLIDWORKS' most likely - trims them when the add-in makes its
    /// run folders, so every run's folder would lie under another folder than the backend's run root.
    /// </summary>
    NameEndsInSpaceOrPeriod,

    /// <summary>Has a character no Windows folder name can have, or a name longer than 255 characters (decision 160A).</summary>
    InvalidFolderName,
}

/// <summary>What kind of drive a drive root is, as the run root rule reads it.</summary>
public enum RunRootDrive
{
    /// <summary>A drive on this computer: a fixed disk, a removable one, an optical drive or a RAM disk.</summary>
    Local,

    /// <summary>A mapped network drive.</summary>
    Network,

    /// <summary>No drive by that letter.</summary>
    Missing,
}

/// <summary>What one part of a run root is, as the run root rule reads it.</summary>
public enum RunRootEntry
{
    /// <summary>Nothing by that path.</summary>
    Missing,

    /// <summary>A folder reached by its own name.</summary>
    Folder,

    /// <summary>A link: a junction, a symbolic link or a volume's mount point - a name-surrogate reparse point.</summary>
    Link,

    /// <summary>A file, or anything else there that is not a folder: nothing below it is looked at.</summary>
    Other,

    /// <summary>
    /// Something there that cannot be read as itself - its attributes denied, or its open failing for any
    /// reason but its absence - so what it is, a folder or a link, cannot be told.
    /// </summary>
    Unreadable,
}

/// <summary>
/// What the run root rule reads of Windows (owner decision 154A): one question each, so a test can fake a
/// share, a mapped drive, a substituted drive, a link or a part that cannot be read without making one. The
/// add-in's own is <c>Native.WindowsRunRootProbe</c>. The rule asks for a full path only of a root not written
/// as a share, and that question reads nothing; every other path it hands the probe is a full, local drive
/// path, so none of the questions goes over the network.
/// </summary>
public interface IRunRootProbe
{
    /// <summary>What kind of drive <paramref name="driveRoot"/> ("C:\") is; asks nothing of the drive itself.</summary>
    RunRootDrive DriveOf(string driveRoot);

    /// <summary>The folder a drive (<paramref name="drive"/>, "S:") substituted by <c>subst</c> stands for, or null when it is not one.</summary>
    string? SubstituteOf(string drive);

    /// <summary>What the part at <paramref name="path"/> is, read without following it when it is a link.</summary>
    RunRootEntry EntryOf(string path);

    /// <summary>
    /// The folder's final path - the path Windows reaches it by once every link is followed, with no
    /// <c>\\?\</c> prefix, a share's as <c>\\server\share\...</c> - or null when it cannot be read.
    /// </summary>
    string? FinalPathOf(string folder);

    /// <summary>
    /// The root's full path, made from its text alone (<c>GetFullPathNameW</c>): rooted, with no <c>.</c> or
    /// <c>..</c> segment and a backslash between segments, an 8.3 short name left as written - nothing on the
    /// disk or the network is read - or null when it has none.
    /// </summary>
    string? FullPathOf(string root);

    /// <summary>
    /// The folder's long-name form - each 8.3 short name in it expanded (<c>GetLongPathNameW</c>), which reads
    /// each folder above it - with no <c>\\?\</c> prefix, or null when it cannot be read.
    /// </summary>
    string? LongPathOf(string folder);
}

/// <summary>
/// The run root rule (owner decision 154A; feature 011 research R12.9, items 1 and 2): a run root is
/// acceptable only when it is a local folder reached by its own path. The one rule every run start reads, so
/// that such a root is refused in plain words before anything is made, rather than deep in a run - and that a
/// settings save reads of the folder chosen for runs and of the run root it keeps (the owner's follow-up).
///
/// <b>Why.</b> The backend writes only into a local folder: its rule for a run folder
/// (<c>resolve_run_dir</c>, <c>reviewer/src/swreview/chat/server.py</c>) refuses a UNC or device path on every
/// route, so under a run root on a share nothing can review, check or plan. And it resolves the run folder it
/// is sent (<c>Path.resolve()</c>), following a junction, a symbolic link, a substituted drive or a mapped
/// network drive, while the add-in binds its own spelling of the folder - so under a run root reached through a
/// link the re-modeler's open refuses its copy at the comparison of run folders. The backend's rule stays; the
/// add-in names such a root before it begins.
///
/// <b>What is read, and in what order</b> - so that nothing is opened over the network or through a link
/// before the rule has refused what it can (the reviews of decision 154A, finding F1): the root as it is
/// written, a UNC or device path refused on sight, as the backend refuses it, before anything is read or made
/// of it - and, since the reviews of 154A's merge (F1), a folder name ending in a space or a period, which
/// Windows reads both with and without it. Then its full path, made from the text alone
/// (<see cref="IRunRootProbe.FullPathOf"/>), which spells forward slashes and <c>..</c> away and reads nothing -
/// unlike <c>Path.GetFullPath</c>, which expands an 8.3 short name by reading each folder of the path, over the
/// network for a share - and which names a share
/// when a relative root lies under a current folder on one. Then the drive: a mapped network drive is refused,
/// and so is a substituted drive, by what Windows says of the letter alone. Then each part from the top, by
/// what it is and never by opening through it: a junction or a symbolic link (any name-surrogate reparse
/// point, a volume's mount point among them) is refused; a part that is there but cannot be read as itself
/// could be one, and leaves the root unverified, refused (finding F2); and the walk stops at the first part
/// that is not there - a root the settings name before the run folder is made is judged by its nearest
/// existing folder. Last, that folder's final path (<c>GetFinalPathNameByHandle</c>), which is what the
/// backend's own resolution reads, compared with its spelling and, when it is not that, with its long-name
/// form, read only now that no part is a link: one that differs from both other than by letter case is
/// reached through a link of some other kind, and refused; one that is an 8.3 short name's long name is not
/// (finding F3); and one that cannot be read leaves the root unverified. Since decision 160A, a character no
/// folder can have or a name longer than 255 characters is refused on the text too: the save must not keep a
/// folder no run can ever be made under. A blank root, one with no full form or on a drive letter that names
/// no drive is still left to the run folder.
/// </summary>
public static class RunRootRule
{
    /// <summary>What the rule finds of <paramref name="runRoot"/>, read through <paramref name="probe"/>.</summary>
    public static RunRootVerdict Judge(string? runRoot, IRunRootProbe probe) => Judge(runRoot, probe, out _);

    /// <summary>
    /// Also hands a search the verified, existing root in its final long-name form (decision 160A).
    /// A missing root has no such answer. Reusing this reading avoids opening an 8.3-spelled root twice.
    /// </summary>
    internal static RunRootVerdict Judge(string? runRoot, IRunRootProbe probe, out string? existingLongRoot)
    {
        existingLongRoot = null;
        if (probe == null)
        {
            throw new ArgumentNullException(nameof(probe));
        }

        if (string.IsNullOrWhiteSpace(runRoot))
        {
            return RunRootVerdict.Accepted;
        }

        // The root as it is written: a share or a device path is refused before anything is read or made of it.
        string written = runRoot!.Trim();
        RunRootVerdict? named = NamedAsAShareOrADevice(written);
        if (named.HasValue)
        {
            return named.Value;
        }

        if (NamesNoFolderCanHave(written))
        {
            return RunRootVerdict.InvalidFolderName;
        }

        // The reviews of 154A's merge, F1: a name Windows reads two ways, on its text too.
        if (HasANameEndingInASpaceOrAPeriod(written))
        {
            return RunRootVerdict.NameEndsInSpaceOrPeriod;
        }

        // Its full path, made from the text alone: a relative root under a current folder on a share is on it.
        string? full = probe.FullPathOf(written);
        if (full == null)
        {
            return RunRootVerdict.Accepted;
        }

        named = NamedAsAShareOrADevice(full);
        if (named.HasValue)
        {
            return named.Value;
        }

        if (!IsDrivePath(full))
        {
            return RunRootVerdict.Accepted;
        }

        string drive = full.Substring(0, 2).ToUpperInvariant();
        switch (probe.DriveOf(drive + @"\"))
        {
            case RunRootDrive.Network:
                return RunRootVerdict.Share;
            case RunRootDrive.Missing:
                return RunRootVerdict.Accepted;
        }

        string? substitute = probe.SubstituteOf(drive);
        if (substitute != null)
        {
            return IsUnc(substitute) ? RunRootVerdict.Share : RunRootVerdict.Link;
        }

        // From the top down to the nearest existing folder: a link is refused for what it is, before anything
        // is opened through it, and a part that cannot be read could be one.
        string reached = full.Substring(0, 3);
        foreach (string part in full.Substring(3).Split(new[] { '\\' }, StringSplitOptions.RemoveEmptyEntries))
        {
            string next = reached.TrimEnd('\\') + @"\" + part;
            RunRootEntry entry = probe.EntryOf(next);
            if (entry == RunRootEntry.Link)
            {
                return RunRootVerdict.Link;
            }

            if (entry == RunRootEntry.Unreadable)
            {
                return RunRootVerdict.Unverified;
            }

            if (entry != RunRootEntry.Folder)
            {
                break;
            }

            reached = next;
        }

        // That folder's final path, which the backend's own resolution reads: its spelling, or - an 8.3 short
        // name in it - its long-name form, read only now that no part is a link.
        string? final = probe.FinalPathOf(reached);
        if (final == null)
        {
            return RunRootVerdict.Unverified;
        }

        if (SameFolder(final, reached))
        {
            if (SameFolder(reached, full)) existingLongRoot = final;
            return RunRootVerdict.Accepted;
        }

        if (IsUnc(final))
        {
            return RunRootVerdict.Share;
        }

        string? longForm = probe.LongPathOf(reached);
        if (longForm == null)
        {
            return RunRootVerdict.Unverified;
        }

        if (!SameFolder(final, longForm)) return RunRootVerdict.Link;
        if (SameFolder(reached, full)) existingLongRoot = longForm;
        return RunRootVerdict.Accepted;
    }

    /// <summary>
    /// A run start's words, true of the root and of the place it is refused: what the root is, the rule, what
    /// was not done (<paramref name="notDone"/>, "nothing was checked") and the way on, a local folder chosen in
    /// Settings, ending with what to do once it is chosen (<paramref name="wayOn"/>, "press Model check
    /// again"). No path: the root can name a server, a share or a user, and the engineer knows where it is.
    ///
    /// The way on is the run-root field of the Review tab's Settings (the owner's follow-up to decision 154A),
    /// which a save checks by this rule and brings into force with the backend's restart.
    /// </summary>
    public static string Refusal(RunRootVerdict verdict, string notDone, string where, string wayOn) =>
        "The run root " + Kind(verdict) + RuleFor(verdict) + ", so " + notDone + ". Choose a local folder for runs " + where + ", then "
        + wayOn + ".";

    /// <summary>Where the Review tab's own refusals send the engineer: the Settings on that tab.</summary>
    public const string InSettings = "in Settings";

    /// <summary>
    /// Where the Model check, Standards and Remodel tabs' refusals send the engineer: their pages print the
    /// message whole and have no Settings of their own (as decision 150A's way on for a backend that did not
    /// start, <c>ReviewHost.StartItAgainOnTheReviewTab</c>).
    /// </summary>
    public const string InSettingsOnTheReviewTab = "in Settings on the Review tab";

    /// <summary>
    /// Whether a folder chosen for runs is written as a full path (the reviews of decision 154A, finding F7): its
    /// drive letter and a separator, or two separators - a share or a device path, which the rule itself refuses.
    /// A relative path, one rooted on the current drive and one on a drive with no separator after its letter -
    /// relative to that drive's current folder - are not: each is resolved against a current folder, which the
    /// add-in and the backend can each read as another, and SOLIDWORKS can move its own.
    /// </summary>
    public static bool IsFullPath(string root)
    {
        if (root == null)
        {
            throw new ArgumentNullException(nameof(root));
        }

        string text = root.Trim();
        if (text.Length >= 2 && IsSeparator(text[0]) && IsSeparator(text[1]))
        {
            return true;
        }

        return text.Length >= 3 && IsLetter(text[0]) && text[1] == ':' && IsSeparator(text[2]);
    }

    /// <summary>
    /// A save's words for a folder chosen for runs that is not written as a full path (finding F7): the one field
    /// not saved, with the way on. No path: the engineer typed it.
    /// </summary>
    public const string NotFullPathRefusal =
        "The folder chosen for runs is not written as a full path, starting with its drive letter, so the run root "
        + "was not changed; the other settings were saved. Type the folder's full path, then save again.";

    /// <summary>
    /// A save's words for a folder chosen for runs in Settings that the rule refuses (the owner's follow-up to
    /// decision 154A): the save goes through, and this one field is not saved - the run root in force is
    /// unchanged and every other setting was saved - so the words speak of the folder chosen, not of the run
    /// root.
    /// </summary>
    public static string ChosenRefusal(RunRootVerdict verdict) =>
        verdict == RunRootVerdict.InvalidFolderName
        ? "The folder chosen for runs has a name Windows cannot use for a folder, so the run root was not "
            + "changed; the other settings were saved. Use folder names of at most 255 characters, with no "
            + "invalid characters, then save again."
        : "The folder chosen for runs " + Kind(verdict) + Rule
        + ", so the run root was not changed; the other settings were saved. Choose a local folder for runs, then save again.";

    /// <summary>
    /// A save's words for the run root it leaves in force when the rule refuses it - the one the settings file
    /// names, or the default under a Documents on a share (the owner's follow-up to decision 154A): the save
    /// goes through, and its answer says every run is refused until the run root is changed.
    /// </summary>
    public static string KeptRefusal(RunRootVerdict verdict) =>
        "The run root " + Kind(verdict) + RuleFor(verdict)
        + ", so every run is refused until it is changed; the settings were saved. Choose a local folder for runs, then save again.";

    /// <summary>
    /// What a run start on the Model check, Standards or Remodel tab is refused with while a start of the backend
    /// under way would bring another run root into force (owner decision 154A, with 153A's record of the settings
    /// in force): why, what was not done (<paramref name="notDone"/>, "nothing was checked") and the way on, the
    /// same press in a moment (<paramref name="wayOn"/>, "press Model check again"). Nothing is made under either
    /// run root until the start ends, and a press then goes on under the one it leaves in force. No path; the
    /// pages print it whole.
    /// </summary>
    public static string MovingRefusal(string notDone, string wayOn) =>
        "The review backend is being started with another folder for runs, so " + notDone + ". " + Begun(wayOn)
        + " in a moment.";

    /// <summary>
    /// A run start's words while a folder chosen for runs in Settings is not in force - its save's restart failed -
    /// and the run root in force is one the rule refuses (the reviews of 154A's merge, N4): what the run root in
    /// force is, the rule, what was not done, and the way on, the restart that brings the folder chosen in - not a
    /// local folder chosen again, which <see cref="Refusal"/> says and the engineer has just done. No path.
    /// </summary>
    public static string ChosenNotInForceRefusal(RunRootVerdict verdict, string notDone, string where, string wayOn) =>
        "The run root in force " + Kind(verdict) + RuleFor(verdict) + ", so " + notDone + ". The folder chosen for runs " + where
        + " is not in force until the review backend restarts with it: save the settings again to retry the restart, then "
        + wayOn + ".";

    /// <summary>
    /// What a Model check or a Standards run is answered with when, read again once its extraction is over, the run
    /// root in force no longer holds its folder (the reviews of 154A's merge, N6): what changed and while what
    /// (<paramref name="during"/>, "the feature tree was read"), why it matters, what was not done and the way on.
    /// No path; the pages print it whole.
    /// </summary>
    public static string ChangedRefusal(string during, string notDone, string wayOn) =>
        "The run root changed while " + during + ", and the backend makes runs only under the one in force, so " + notDone
        + ". " + Begun(wayOn) + ".";

    /// <summary>
    /// Whether two run roots are the same (owner decision 154A): as written, ignoring letter case, as Windows names a
    /// folder. The one rule for the run roots in force, for whether the run root saved is the one in force, for whether
    /// a start under way moves it, and for whether a refused run root in force has another chosen in its place.
    /// Another spelling of the same folder - a trailing separator, an 8.3 short name - counts as another run root:
    /// telling them apart would read the disk, which the restart's lock must not wait on.
    /// </summary>
    public static bool SameRunRoot(string first, string second) =>
        string.Equals(first, second, StringComparison.OrdinalIgnoreCase);

    /// <summary>A way on as the start of a sentence: "press Model check again" as "Press Model check again".</summary>
    private static string Begun(string wayOn) => char.ToUpperInvariant(wayOn[0]) + wayOn.Substring(1);

    /// <summary>The rule, as every refusal states it.</summary>
    private const string Rule = ", and runs are made only in a local folder reached by its own path";

    /// <summary>An impossible name needs usable folder names; locality and links do not explain its refusal.</summary>
    private static string RuleFor(RunRootVerdict verdict) => verdict == RunRootVerdict.InvalidFolderName ? "" : Rule;

    /// <summary>What a refused root is, after its subject: "is on a network share ...".</summary>
    private static string Kind(RunRootVerdict verdict)
    {
        switch (verdict)
        {
            case RunRootVerdict.Share:
                return "is on a network share or a mapped network drive";
            case RunRootVerdict.Link:
                return "is reached through a link, such as a junction, a symbolic link or a substituted drive";
            case RunRootVerdict.DevicePath:
                return "is written as a Windows device path";
            case RunRootVerdict.Unverified:
                return "could not be checked, since a part of its path cannot be read";
            case RunRootVerdict.NameEndsInSpaceOrPeriod:
                return "has a folder whose name ends in a space or a period, which Windows reads both with and without it";
            case RunRootVerdict.InvalidFolderName:
                return "has a name Windows cannot use for a folder";
            default:
                throw new ArgumentOutOfRangeException(nameof(verdict), verdict, "an accepted run root is not refused");
        }
    }

    /// <summary>
    /// Whether <paramref name="written"/> names something no folder's path can: a character Windows refuses in a
    /// name, a wildcard, a control character, or a colon anywhere but after a drive letter - or, since the reviews of
    /// 154A's merge (N8), a name longer than the 255 characters a folder's can be, whose open Windows answers as an
    /// invalid name, which the walk would read as a part that cannot be read. Decision 160A refuses such a
    /// root at the save and at every run start; the rule reads nothing of it.
    /// </summary>
    private static bool NamesNoFolderCanHave(string written)
    {
        for (int index = 0; index < written.Length; index++)
        {
            char character = written[index];
            if (character < ' ' || character == '"' || character == '<' || character == '>' || character == '|'
                || character == '*' || character == '?' || (character == ':' && index != 1))
            {
                return true;
            }
        }

        foreach (string name in Names(written))
        {
            if (name.Length > LongestName)
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>The longest name a folder can have on Windows' file systems.</summary>
    private const int LongestName = 255;

    /// <summary>
    /// Whether a name in <paramref name="written"/> - any of its folders', the last too, but <c>.</c> and <c>..</c>,
    /// which name a folder and the one above it - ends in a space or a period (the reviews of 154A's merge, F1).
    /// </summary>
    private static bool HasANameEndingInASpaceOrAPeriod(string written)
    {
        foreach (string name in Names(written))
        {
            if (name != "." && name != ".." && (name[name.Length - 1] == ' ' || name[name.Length - 1] == '.'))
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>The names between the separators of <paramref name="written"/>, either separator counted, none empty.</summary>
    private static string[] Names(string written) =>
        written.Split(new[] { '\\', '/' }, StringSplitOptions.RemoveEmptyEntries);

    /// <summary>Whether two paths name one folder as Windows spells it: the same but for letter case and a final separator.</summary>
    private static bool SameFolder(string path, string other) =>
        string.Equals(path.TrimEnd('\\'), other.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase);

    private static bool IsLetter(char character) =>
        (character >= 'A' && character <= 'Z') || (character >= 'a' && character <= 'z');

    /// <summary>
    /// A root written as a UNC path - <c>\\server\share</c> or <c>\\?\UNC\server\share</c> - is on a share, and
    /// any other that begins with two separators is a device path (<c>\\?\C:\...</c>, <c>\\.\...</c>), either
    /// separator counted; null for anything else.
    /// </summary>
    private static RunRootVerdict? NamedAsAShareOrADevice(string form)
    {
        if (form.Length < 2 || !IsSeparator(form[0]) || !IsSeparator(form[1]))
        {
            return null;
        }

        string spelled = form.Replace('/', '\\');
        if (spelled.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)
            || spelled.StartsWith(@"\\.\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            return RunRootVerdict.Share;
        }

        return spelled.StartsWith(@"\\?\", StringComparison.Ordinal) || spelled.StartsWith(@"\\.\", StringComparison.Ordinal)
            ? RunRootVerdict.DevicePath
            : RunRootVerdict.Share;
    }

    private static bool IsSeparator(char character) => character == '\\' || character == '/';

    private static bool IsUnc(string path) => path.StartsWith(@"\\", StringComparison.Ordinal);

    /// <summary>"X:\" and what follows: the only shape of full path whose drive the rule can ask about.</summary>
    private static bool IsDrivePath(string full) =>
        full.Length >= 3 && IsLetter(full[0]) && full[1] == ':' && full[2] == '\\';
}
