using System;
using System.IO;

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

    /// <summary>A file, or a part that cannot be read: nothing below it is looked at.</summary>
    Other,
}

/// <summary>
/// What the run root rule reads of Windows (owner decision 154A): one question each, so a test can fake a
/// share, a mapped drive, a substituted drive or a link without making one. The add-in's own is
/// <c>Native.WindowsRunRootProbe</c>. Every path it is handed is a full, local drive path, so none of the
/// questions goes over the network.
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
}

/// <summary>
/// The run root rule (owner decision 154A; feature 011 research R12.9, items 1 and 2): a run root is
/// acceptable only when it is a local folder reached by its own path. The one rule the settings save and every
/// run start read, so that such a root is refused in plain words before anything is made, rather than deep in
/// a run.
///
/// <b>Why.</b> The backend writes only into a local folder: its rule for a run folder
/// (<c>resolve_run_dir</c>, <c>reviewer/src/swreview/chat/server.py</c>) refuses a UNC or device path on every
/// route, so under a run root on a share nothing can review, check or plan. And it resolves the run folder it
/// is sent (<c>Path.resolve()</c>), following a junction, a symbolic link, a substituted drive or a mapped
/// network drive, while the add-in binds its own spelling of the folder - so under a run root reached through a
/// link the re-modeler's open refuses its copy at the comparison of run folders. The backend's rule stays; the
/// add-in names such a root before it begins.
///
/// <b>What is read, and in what order</b> - so that nothing is opened over the network or through a link:
/// the root in its full form, the one every run folder is made under (<see cref="RunFolders.FullFormOf"/>),
/// which expands an 8.3 short name and spells forward slashes and <c>..</c> away; a full form written as a UNC
/// or device path is refused on sight, as the backend refuses it, before anything is asked. Then the drive:
/// a mapped network drive is refused, and so is a substituted drive, by what Windows says of the letter alone.
/// Then each part from the top, by what it is and never by opening through it: a junction or a symbolic link
/// (any name-surrogate reparse point, a volume's mount point among them) is refused, and the walk stops at the
/// first part that is not there - a root the settings name before the run folder is made is judged by its
/// nearest existing folder. Last, that folder's final path (<c>GetFinalPathNameByHandle</c>), which is what the
/// backend's own resolution reads: one that differs from the full path other than by letter case is reached
/// through a link of some other kind, and refused. A root the rule cannot read at all - blank, with no full
/// form, on a drive letter that names no drive, with a part or a final path that cannot be read - is not
/// refused for it: the run folder is made under it, or reports why not, as before.
/// </summary>
public static class RunRootRule
{
    /// <summary>What the rule finds of <paramref name="runRoot"/>, read through <paramref name="probe"/>.</summary>
    public static RunRootVerdict Judge(string? runRoot, IRunRootProbe probe)
    {
        if (probe == null)
        {
            throw new ArgumentNullException(nameof(probe));
        }

        if (string.IsNullOrWhiteSpace(runRoot))
        {
            return RunRootVerdict.Accepted;
        }

        // The form every run folder is made under. A root with none - a device path under the legacy path
        // handling a host process may run with, a UNC path with no share - is read as it is written.
        string? full = FullFormOrNull(runRoot!);
        RunRootVerdict? named = NamedAsAShareOrADevice(full ?? runRoot!.TrimStart());
        if (named.HasValue)
        {
            return named.Value;
        }

        if (full == null || !IsDrivePath(full))
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
        // is opened through it.
        string reached = full.Substring(0, 3);
        foreach (string part in full.Substring(3).Split(new[] { '\\' }, StringSplitOptions.RemoveEmptyEntries))
        {
            string next = reached.TrimEnd('\\') + @"\" + part;
            RunRootEntry entry = probe.EntryOf(next);
            if (entry == RunRootEntry.Link)
            {
                return RunRootVerdict.Link;
            }

            if (entry != RunRootEntry.Folder)
            {
                break;
            }

            reached = next;
        }

        string? final = probe.FinalPathOf(reached);
        if (final == null
            || string.Equals(final.TrimEnd('\\'), reached.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
        {
            return RunRootVerdict.Accepted;
        }

        return IsUnc(final) ? RunRootVerdict.Share : RunRootVerdict.Link;
    }

    /// <summary>
    /// The refusal's words, true of the root and of the place it is refused: what the root is, the rule, what
    /// was not done (<paramref name="notDone"/>, "nothing was checked") and the way on, a local folder, ending
    /// with what to do once it is set (<paramref name="wayOn"/>, "press Model check again"). No path: the root
    /// can name a server, a share or a user, and the engineer knows where it is.
    ///
    /// The run root is read from the settings file when the add-in loads, and a settings save writes back the
    /// one in force, so the way on is the file and a restart of SOLIDWORKS: the Settings panel has no field for
    /// it.
    /// </summary>
    public static string Refusal(RunRootVerdict verdict, string notDone, string wayOn)
    {
        string what;
        switch (verdict)
        {
            case RunRootVerdict.Share:
                what = "The run root is on a network share or a mapped network drive";
                break;
            case RunRootVerdict.Link:
                what = "The run root is reached through a link, such as a junction, a symbolic link or a substituted drive";
                break;
            case RunRootVerdict.DevicePath:
                what = "The run root is written as a Windows device path";
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(verdict), verdict, "an accepted run root is not refused");
        }

        return what + ", and runs are made only in a local folder reached by its own path, so " + notDone
            + ". Set the run root in the add-in's settings file to a local folder, then restart SOLIDWORKS and "
            + wayOn + ".";
    }

    private static string? FullFormOrNull(string runRoot)
    {
        try
        {
            return RunFolders.FullFormOf(runRoot);
        }
        catch (Exception failure)
            when (failure is ArgumentException || failure is NotSupportedException
                || failure is PathTooLongException || failure is System.Security.SecurityException)
        {
            return null;
        }
    }

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

    /// <summary>"X:\" and what follows: the only shape of full form whose drive the rule can ask about.</summary>
    private static bool IsDrivePath(string full) =>
        full.Length >= 3
        && ((full[0] >= 'A' && full[0] <= 'Z') || (full[0] >= 'a' && full[0] <= 'z'))
        && full[1] == ':'
        && full[2] == '\\';
}
