using System;
using System.Collections.Generic;
using SwReview.AddIn.Review;

namespace SwReview.AddIn.Tests;

/// <summary>
/// A run root probe that answers what a test tells it (owner decision 154A): the seam through which a test
/// fakes a mapped network drive, a substituted drive, a link or a final path elsewhere without making one,
/// and which records every question, so a test can show what the rule asked and what it never touched.
///
/// Unless told otherwise every drive is local and none is substituted; every part asked about is a folder,
/// or, when <see cref="Existing"/> is set, only the folders it names are; and a folder's final path is its
/// own path.
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

    /// <summary>A folder's final path where it is not the folder's own, or null where it cannot be read.</summary>
    public Dictionary<string, string?> FinalPaths { get; } =
        new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase);

    /// <summary>Every question asked, in order: "DriveOf Z:\", "EntryOf C:\work", ...</summary>
    public List<string> Asked { get; } = new List<string>();

    /// <summary>A probe that answers every drive as a mapped network drive.</summary>
    public static FakeRunRootProbe OnANetworkDrive() => new FakeRunRootProbe { EveryDrive = RunRootDrive.Network };

    /// <summary>A probe that answers every drive as local and every folder as reached by its own path.</summary>
    public static FakeRunRootProbe Local() => new FakeRunRootProbe();

    /// <summary>The three things the rule refuses a run root as, for a host's tests to be refused each way.</summary>
    public static IEnumerable<object[]> RefusedKinds() => new[]
    {
        new object[] { "on a share" },
        new object[] { "through a link" },
        new object[] { "a device path" },
    };

    /// <summary>
    /// A run root and a probe the rule refuses as <paramref name="kind"/>, made from a host's local root:
    /// the root on a mapped network drive, the root on a substituted drive, or the root written as a device
    /// path. Nothing is made or touched: the probe is faked, and a device path is refused on sight.
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
            default:
                throw new ArgumentOutOfRangeException(nameof(kind), kind, "not a kind the rule refuses");
        }
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
}
