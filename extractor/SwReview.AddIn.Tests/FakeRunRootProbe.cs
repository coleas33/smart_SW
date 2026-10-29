using System;
using System.Collections.Generic;
using System.IO;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;

namespace SwReview.AddIn.Tests;

/// <summary>
/// A run root probe that answers what a test tells it (owner decision 154A): the seam through which a test
/// fakes a mapped network drive, a substituted drive, a link, a part that cannot be read or a final path
/// elsewhere without making one, and which records every question that reads the disk or the network, so a
/// test can show what the rule asked and what it never touched.
///
/// Unless told otherwise every drive is local and none is substituted; every part asked about is a folder,
/// or, when <see cref="Existing"/> is set, only the folders it names are; a folder's final path and its
/// long-name form are its own path; and a root's full path is the one Windows makes from its text alone
/// (<see cref="WindowsRunRootProbe.LexicalFullPathOf"/>), which reads nothing and so is not recorded in
/// <see cref="Asked"/> but in <see cref="Normalized"/>.
/// </summary>
internal sealed class FakeRunRootProbe : IRunRootProbe
{
    /// <summary>What every drive is that <see cref="Drives"/> does not name.</summary>
    public RunRootDrive EveryDrive { get; set; } = RunRootDrive.Local;

    /// <summary>What a drive root ("Z:\") is, by name.</summary>
    public Dictionary<string, RunRootDrive> Drives { get; } =
        new Dictionary<string, RunRootDrive>(StringComparer.OrdinalIgnoreCase);

    /// <summary>The folder a substituted drive ("S:") stands for, by drive.</summary>
    public Dictionary<string, string> Substitutes { get; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>The folders that exist, or null when every part asked about is one.</summary>
    public HashSet<string>? Existing { get; set; }

    /// <summary>The parts that are links: a junction, a symbolic link or a mount point.</summary>
    public HashSet<string> Links { get; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>The parts that are files.</summary>
    public HashSet<string> Files { get; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>The parts that are there but cannot be read as themselves: their attributes denied.</summary>
    public HashSet<string> Unreadable { get; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>A folder's final path where it is not the folder's own, or null where it cannot be read.</summary>
    public Dictionary<string, string?> FinalPaths { get; } =
        new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase);

    /// <summary>A folder's long-name form where it is not the folder's own, or null where it cannot be read.</summary>
    public Dictionary<string, string?> LongPaths { get; } =
        new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// A root's full path where it is not the one made from its text - a relative root under a current
    /// folder on a share - or null where it has none.
    /// </summary>
    public Dictionary<string, string?> FullPaths { get; } =
        new Dictionary<string, string?>(StringComparer.Ordinal);

    /// <summary>Every question that reads the disk or the network, in order: "DriveOf Z:\", "EntryOf C:\work", ...</summary>
    public List<string> Asked { get; } = new List<string>();

    /// <summary>Every root whose full path was asked for, in order: a question that reads nothing.</summary>
    public List<string> Normalized { get; } = new List<string>();

    /// <summary>A probe that answers every drive as a mapped network drive.</summary>
    public static FakeRunRootProbe OnANetworkDrive() => new FakeRunRootProbe { EveryDrive = RunRootDrive.Network };

    /// <summary>A probe that answers every drive as local and every folder as reached by its own path.</summary>
    public static FakeRunRootProbe Local() => new FakeRunRootProbe();

    /// <summary>
    /// <see cref="Local"/>, but with every folder from the drive's root down to <paramref name="folder"/> there and every
    /// other part missing: a run root below it not made yet, as the rule's walk reads it (the review of owner decision 160A).
    /// </summary>
    public static FakeRunRootProbe ExistingDownTo(string folder)
    {
        var existing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (string? at = WindowsRunRootProbe.LexicalFullPathOf(folder); at != null && at.Length > 3; at = Path.GetDirectoryName(at))
        {
            existing.Add(at);
        }

        return new FakeRunRootProbe { Existing = existing };
    }

    /// <summary>
    /// The things the rule refuses a run root as, for a host's tests to be refused each way - the fifth, a
    /// folder name ending in a period, since the reviews of 154A's merge (F1), and the sixth, a name no folder
    /// can have, since owner decision 160A.
    /// </summary>
    public static IEnumerable<object[]> RefusedKinds() => new[]
    {
        new object[] { "on a share" },
        new object[] { "through a link" },
        new object[] { "a device path" },
        new object[] { "could not be checked" },
        new object[] { "a name ending in a period" },
        new object[] { "an invalid folder name" },
    };

    /// <summary>
    /// A run root and a probe the rule refuses as <paramref name="kind"/>, made from a host's local root:
    /// the root on a mapped network drive, the root on a substituted drive, the root written as a device
    /// path, the root below a folder that cannot be read, the root with a period after its last folder's
    /// name, or the root with a quote after it, a character no folder can have. Nothing is made or touched: the
    /// probe is faked, and a device path, a name ending in a period and a quote are refused on sight.
    /// </summary>
    public static (string RunRoot, FakeRunRootProbe Probe, RunRootVerdict Verdict) Refusing(string kind, string localRoot)
    {
        switch (kind)
        {
            case "on a share":
                return (localRoot, OnANetworkDrive(), RunRootVerdict.Share);
            case "through a link":
                var substituted = new FakeRunRootProbe();
                substituted.Substitutes[localRoot.Substring(0, 2)] = @"C:\Fictional\work";
                return (localRoot, substituted, RunRootVerdict.Link);
            case "a device path":
                return (@"\\?\" + localRoot, Local(), RunRootVerdict.DevicePath);
            case "could not be checked":
                var unreadable = new FakeRunRootProbe();
                unreadable.Unreadable.Add(TopFolderOf(localRoot));
                return (localRoot, unreadable, RunRootVerdict.Unverified);
            case "a name ending in a period":
                return (localRoot.TrimEnd('\\') + ".", Local(), RunRootVerdict.NameEndsInSpaceOrPeriod);
            case "an invalid folder name":
                return (localRoot.TrimEnd('\\') + "\"", Local(), RunRootVerdict.InvalidFolderName);
            default:
                throw new ArgumentOutOfRangeException(nameof(kind), kind, "not a kind the rule refuses");
        }
    }

    /// <summary>The first folder below a drive path's root: <c>C:\Users</c> of <c>C:\Users\me\runs</c>.</summary>
    private static string TopFolderOf(string localRoot)
    {
        string full = WindowsRunRootProbe.LexicalFullPathOf(localRoot)
            ?? throw new ArgumentException("not a path: " + localRoot, nameof(localRoot));
        int next = full.IndexOf('\\', 3);
        return next < 0 ? full : full.Substring(0, next);
    }

    public RunRootDrive DriveOf(string driveRoot)
    {
        Asked.Add("DriveOf " + driveRoot);
        return Drives.TryGetValue(driveRoot, out RunRootDrive drive) ? drive : EveryDrive;
    }

    public string? SubstituteOf(string drive)
    {
        Asked.Add("SubstituteOf " + drive);
        return Substitutes.TryGetValue(drive, out string? folder) ? folder : null;
    }

    public RunRootEntry EntryOf(string path)
    {
        Asked.Add("EntryOf " + path);
        if (Links.Contains(path))
        {
            return RunRootEntry.Link;
        }

        if (Unreadable.Contains(path))
        {
            return RunRootEntry.Unreadable;
        }

        if (Files.Contains(path))
        {
            return RunRootEntry.Other;
        }

        return Existing == null || Existing.Contains(path) ? RunRootEntry.Folder : RunRootEntry.Missing;
    }

    public string? FinalPathOf(string folder)
    {
        Asked.Add("FinalPathOf " + folder);
        return FinalPaths.TryGetValue(folder, out string? final) ? final : folder;
    }

    public string? FullPathOf(string root)
    {
        Normalized.Add(root);
        return FullPaths.TryGetValue(root, out string? full) ? full : WindowsRunRootProbe.LexicalFullPathOf(root);
    }

    public string? LongPathOf(string folder)
    {
        Asked.Add("LongPathOf " + folder);
        return LongPaths.TryGetValue(folder, out string? longForm) ? longForm : folder;
    }
}
