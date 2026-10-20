using System;
using System.IO;
using System.Linq;
using System.Security;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// Owner decision 144A (feature 011, research R11.1 and its review): the run's copy, as the
/// re-modeler's pane seat (<see cref="SwRemodelSeat"/>) takes it - the one rule the seat checks a path
/// by before SOLIDWORKS is asked anything. Its own file, so the seat's source holds only the calls the
/// interop manifest's audit reads.
///
/// A path is the run's copy when it is a full path - a drive's or a share's - to a part (<c>.SLDPRT</c>)
/// inside a run folder's <c>copy/</c> (<see cref="RemodelCopy.RunDirectoryOf"/>'s rule, which the
/// bridge seat checks too), the run folder being a folder and not the root of a drive or a share, with
/// no <c>..</c> in it. The seat uses the full, canonical form for every call and comparison after the
/// check, so what SOLIDWORKS is handed is what was checked. Which run's copy it is the caller's to
/// know: the pipeline resolves it from a run this host made.
/// </summary>
internal static class RemodelSeatCopyPath
{
    /// <summary>
    /// The canonical form of <paramref name="copyPath"/> and the run folder it sits in, or an
    /// <see cref="ArgumentException"/> saying why it is not the run's copy - the caller's mistake, as the
    /// bridge seat's refusal of a path outside a run folder's <c>copy/</c> is.
    /// </summary>
    public static (string Path, string RunDirectory) Of(string copyPath)
    {
        if (copyPath == null)
        {
            throw new ArgumentNullException(nameof(copyPath));
        }

        string trimmed = copyPath.Trim();
        if (!IsFullyQualified(trimmed))
        {
            throw new ArgumentException(
                "'" + copyPath + "' is not a full path - a drive's or a share's - so it names no document; "
                + "the seat opens and activates the run's copy only.",
                nameof(copyPath));
        }

        if (trimmed.Split('\\', '/').Any(segment => segment == ".."))
        {
            throw new ArgumentException(
                "'" + copyPath + "' climbs out of a folder ('..'); the seat takes the run's copy by its own "
                + "path only.",
                nameof(copyPath));
        }

        string canonical;
        string runDirectory;
        try
        {
            canonical = Path.GetFullPath(trimmed);
            runDirectory = RemodelCopy.RunDirectoryOf(canonical);
        }
        catch (Exception refusal) when (refusal is MutatingCallError
            || refusal is RemodelCopyError
            || refusal is ArgumentException
            || refusal is NotSupportedException
            || refusal is PathTooLongException
            || refusal is SecurityException)
        {
            throw new ArgumentException(refusal.Message, nameof(copyPath), refusal);
        }

        if (string.Equals(Path.GetPathRoot(runDirectory), runDirectory, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException(
                "'" + copyPath + "' is in a '" + RemodelCopy.CopyFolderName + "' folder at the root of a drive "
                + "or a share, which is in no run folder.",
                nameof(copyPath));
        }

        if (!string.Equals(Path.GetExtension(canonical), RemodelCopy.PartExtension, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException(
                "'" + copyPath + "' is not a part (" + RemodelCopy.PartExtension + "): the run's copy is a "
                + "part, and the seat opens and activates nothing else.",
                nameof(copyPath));
        }

        return (canonical, runDirectory);
    }

    /// <summary>
    /// A drive letter, a colon and a separator, or a share - two separators and a server's name - and
    /// never a path relative to a drive's own folder (<c>C:copy\...</c>) or to the current drive's root
    /// (<c>\runs\...</c>), which <see cref="Path.IsPathRooted"/> accepts and which resolve against wherever
    /// the process is, nor a device path (<c>\\?\</c>, <c>\\.\</c>).
    /// </summary>
    private static bool IsFullyQualified(string path) =>
        (path.Length >= 3 && char.IsLetter(path[0]) && path[1] == ':' && IsSeparator(path[2]))
        || (path.Length >= 3 && IsSeparator(path[0]) && IsSeparator(path[1])
            && path[2] != '?' && path[2] != '.' && !IsSeparator(path[2]));

    private static bool IsSeparator(char character) => character == '\\' || character == '/';
}
