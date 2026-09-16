using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>One dump's line in <c>run_root/package-index.json</c> (data-model.md 9.4).</summary>
public sealed class PackageIndexRow
{
    /// <summary>The <see cref="ReuseKey"/> digest of the package in that folder.</summary>
    [JsonPropertyName("reuse_key")]
    public string ReuseKey { get; set; } = string.Empty;

    /// <summary>Run folder name, relative to the run root.</summary>
    [JsonPropertyName("folder")]
    public string Folder { get; set; } = string.Empty;

    /// <summary>When the package was written; the "(age)" the pane's status line prints.</summary>
    [JsonPropertyName("written_at")]
    public DateTimeOffset WrittenAt { get; set; }

    /// <summary>So a profile mismatch is rejected before any file is opened.</summary>
    [JsonPropertyName("profile")]
    public string Profile { get; set; } = string.Empty;

    /// <summary>So the copy cost is known before it is paid.</summary>
    [JsonPropertyName("package_bytes")]
    public long PackageBytes { get; set; }

    /// <summary>Whether every member a lookup needs is actually present.</summary>
    internal bool IsComplete =>
        !string.IsNullOrEmpty(ReuseKey)
        && !string.IsNullOrEmpty(Folder)
        && !string.IsNullOrEmpty(Profile)
        && WrittenAt != default
        && PackageBytes >= 0;
}

/// <summary>What a bounded head read of a <c>package.json</c> could answer.</summary>
public sealed class PackageHead
{
    internal PackageHead(string? reuseKey, DumpProfile? profile)
    {
        ReuseKey = reuseKey;
        Profile = profile;
    }

    /// <summary>Nothing readable: no folder, no package, a half-written one.</summary>
    public static readonly PackageHead Unknown = new PackageHead(null, null);

    /// <summary>The package's <c>reuse_key</c>, or null when it carries none.</summary>
    public string? ReuseKey { get; }

    /// <summary>The dump profile that wrote it, or null for one this build does not know.</summary>
    public DumpProfile? Profile { get; }
}

/// <summary>
/// The index of run folders lever 9 looks a package up in, and the bounded scan it falls back
/// to (data-model.md 9.4, T090/T091).
///
/// One line is appended per successful dump. There is no index in the shipped build (all
/// VERIFIED): <c>RunFolders.Create</c> always makes a fresh timestamped folder, the pane's
/// "latest run" is an in-memory field cleared on detach, and <c>RunFolders.ProfileOf</c> reads
/// only the first 8 KiB of one package <b>because</b> a full one is tens of megabytes and the
/// read happens on the SOLIDWORKS application thread. A lookup that parsed every package under
/// the run root is the thing that class was written to avoid.
///
/// <b>Nothing here throws.</b> A missing, unreadable or unparseable index is a miss - one
/// dump, which is what the lever was trying to save, and never a review that failed because a
/// cache was corrupt. The lookup verifies the folder and its package still exist, because the
/// index cannot know an engineer deleted a folder in Explorer.
/// </summary>
public static class PackageIndex
{
    /// <summary>The index file, in the run root beside the run folders.</summary>
    public const string IndexFileName = "package-index.json";

    /// <summary>
    /// How many folders the fallback scan may open, most recent first. A run root gains a
    /// folder per review, so an unbounded scan gets slower every week on the one thread
    /// SOLIDWORKS is waiting on. Past the cap the answer is "no reuse", which costs a dump.
    /// </summary>
    public const int ScanFolderLimit = 20;

    /// <summary>The <c>ProfileOf</c> budget: how much of a package a head read may read.</summary>
    private const int HeadBytes = 8 * 1024;

    private const string MeshDirectory = PackageWriter.MeshDirectoryName;

    private static readonly byte[] ExtractorProperty = Encoding.UTF8.GetBytes("extractor");
    private static readonly byte[] ProfileProperty = Encoding.UTF8.GetBytes("profile");
    private static readonly byte[] ReuseKeyProperty = Encoding.UTF8.GetBytes("reuse_key");

    private static readonly JsonSerializerOptions RowOptions = new JsonSerializerOptions
    {
        // One row, one line: the file is appended to, never rewritten, so a dump that dies
        // mid-write costs its own line and none of the rows before it.
        WriteIndented = false,
    };

    /// <summary>
    /// Appends one row. Returns false when it could not be written, which is not a failed
    /// dump: the package is on disk either way and the only cost is a future miss.
    /// </summary>
    public static bool Append(string? runRoot, PackageIndexRow row)
    {
        if (row == null)
        {
            throw new ArgumentNullException(nameof(row));
        }

        if (string.IsNullOrWhiteSpace(runRoot))
        {
            return false;
        }

        try
        {
            File.AppendAllText(
                Path.Combine(runRoot!, IndexFileName),
                JsonSerializer.Serialize(row, RowOptions) + Environment.NewLine,
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            return true;
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (NotSupportedException)
        {
            return false;
        }
    }

    /// <summary>Every readable row, in the order they were appended. Never throws.</summary>
    public static IReadOnlyList<PackageIndexRow> Read(string? runRoot)
    {
        if (string.IsNullOrWhiteSpace(runRoot))
        {
            return new PackageIndexRow[0];
        }

        string[] lines;
        try
        {
            string path = Path.Combine(runRoot!, IndexFileName);
            if (!File.Exists(path))
            {
                return new PackageIndexRow[0];
            }

            lines = File.ReadAllLines(path);
        }
        catch (IOException)
        {
            return new PackageIndexRow[0];
        }
        catch (UnauthorizedAccessException)
        {
            return new PackageIndexRow[0];
        }
        catch (ArgumentException)
        {
            return new PackageIndexRow[0];
        }
        catch (NotSupportedException)
        {
            return new PackageIndexRow[0];
        }

        var rows = new List<PackageIndexRow>();
        foreach (string line in lines)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            try
            {
                PackageIndexRow? row = JsonSerializer.Deserialize<PackageIndexRow>(line, RowOptions);
                if (row != null && row.IsComplete)
                {
                    rows.Add(row);
                }
            }
            catch (JsonException)
            {
                // The last line of an index was written by a dump that may have been killed
                // halfway through it. The rows before it are still true.
            }
        }

        return rows;
    }

    /// <summary>
    /// The most recent run folder holding a package with this key and profile, or null.
    ///
    /// The index first, because it answers without opening a package at all; then the bounded
    /// head scan, because an index that was never written - or was written by a build that had
    /// none - is a reason to look, not a reason to fail.
    /// </summary>
    public static PackageIndexRow? FindReusable(
        string? runRoot,
        string reuseKey,
        DumpProfile profile,
        int scanLimit = ScanFolderLimit)
    {
        if (string.IsNullOrWhiteSpace(runRoot) || string.IsNullOrEmpty(reuseKey))
        {
            return null;
        }

        string wanted = PackageSerializer.EnumToJsonName(profile);

        var rows = new List<PackageIndexRow>(Read(runRoot));
        rows.Sort((left, right) => right.WrittenAt.CompareTo(left.WrittenAt));
        foreach (PackageIndexRow row in rows)
        {
            if (!string.Equals(row.ReuseKey, reuseKey, StringComparison.Ordinal)
                || !string.Equals(row.Profile, wanted, StringComparison.Ordinal))
            {
                continue;
            }

            if (PackageOf(runRoot!, row.Folder) != null)
            {
                return row;
            }
        }

        return Scan(runRoot!, reuseKey, profile, scanLimit);
    }

    /// <summary>
    /// What a bounded read of the head of <paramref name="runDirectory"/>'s package can say.
    ///
    /// <b>Only the head of the file is read.</b> <c>reuse_key</c> is the fourth property of a
    /// package and <c>extractor.profile</c> the last member of the fifth, so the answer is in
    /// the first few hundred bytes; a full review package is tens of megabytes and this runs on
    /// the SOLIDWORKS application thread.
    ///
    /// <b>Nothing here throws.</b> Every caller is a repaint or a lookup.
    /// </summary>
    public static PackageHead HeadOf(string? runDirectory)
    {
        if (string.IsNullOrWhiteSpace(runDirectory))
        {
            return PackageHead.Unknown;
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

                // A stream may hand back less than it was asked for without being at its end,
                // so the head is filled rather than read once.
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
            return PackageHead.Unknown;
        }
        catch (UnauthorizedAccessException)
        {
            return PackageHead.Unknown;
        }
        catch (ArgumentException)
        {
            return PackageHead.Unknown;
        }
        catch (NotSupportedException)
        {
            return PackageHead.Unknown;
        }

        try
        {
            return ReadHead(head);
        }
        catch (JsonException)
        {
            // A package that is being written while it is being read is the ordinary case,
            // not a broken one: the caller asks again when the dump ends.
            return PackageHead.Unknown;
        }
    }

    /// <summary>
    /// <c>package.json</c> plus <c>meshes/</c>: what a reuse would copy, in bytes. 0 when
    /// there is nothing readable there.
    /// </summary>
    public static long PackageBytes(string? runDirectory)
    {
        if (string.IsNullOrWhiteSpace(runDirectory))
        {
            return 0;
        }

        try
        {
            long total = 0;
            var package = new FileInfo(Path.Combine(runDirectory!, PackageWriter.PackageFileName));
            if (package.Exists)
            {
                total += package.Length;
            }

            var meshes = new DirectoryInfo(Path.Combine(runDirectory!, MeshDirectory));
            if (meshes.Exists)
            {
                foreach (FileInfo mesh in meshes.GetFiles("*", SearchOption.AllDirectories))
                {
                    total += mesh.Length;
                }
            }

            return total;
        }
        catch (IOException)
        {
            return 0;
        }
        catch (UnauthorizedAccessException)
        {
            return 0;
        }
        catch (ArgumentException)
        {
            return 0;
        }
        catch (NotSupportedException)
        {
            return 0;
        }
    }

    /// <summary>The fallback: the head of the N most recent folders' packages.</summary>
    private static PackageIndexRow? Scan(string runRoot, string reuseKey, DumpProfile profile, int scanLimit)
    {
        string[] folders;
        try
        {
            folders = Directory.GetDirectories(runRoot);
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

        // Folder names start yyyyMMdd-HHmmss, so the name orders them without a stat each.
        Array.Sort(folders, (left, right) => string.CompareOrdinal(right, left));

        int examined = 0;
        foreach (string folder in folders)
        {
            if (examined >= scanLimit)
            {
                break;
            }

            examined++;
            PackageHead head = HeadOf(folder);
            if (!string.Equals(head.ReuseKey, reuseKey, StringComparison.Ordinal) || head.Profile != profile)
            {
                continue;
            }

            FileInfo package;
            try
            {
                package = new FileInfo(Path.Combine(folder, PackageWriter.PackageFileName));
            }
            catch (ArgumentException)
            {
                continue;
            }

            return new PackageIndexRow
            {
                ReuseKey = reuseKey,
                Folder = Path.GetFileName(folder),
                WrittenAt = new DateTimeOffset(package.LastWriteTimeUtc, TimeSpan.Zero),
                Profile = PackageSerializer.EnumToJsonName(profile),
                PackageBytes = PackageBytes(folder),
            };
        }

        return null;
    }

    /// <summary>
    /// The run folder a row names, or null when the row no longer describes one.
    ///
    /// A folder name that leaves the run root is refused rather than followed: a row nobody
    /// wrote on purpose must not be able to name a directory somewhere else on the machine.
    /// </summary>
    private static string? PackageOf(string runRoot, string folder)
    {
        try
        {
            string root = Path.GetFullPath(runRoot);
            string full = Path.GetFullPath(Path.Combine(root, folder));
            if (full.Length <= root.Length
                || !full.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }

            string package = Path.Combine(full, PackageWriter.PackageFileName);
            return File.Exists(package) ? package : null;
        }
        catch (ArgumentException)
        {
            return null;
        }
        catch (NotSupportedException)
        {
            return null;
        }
        catch (PathTooLongException)
        {
            return null;
        }
    }

    /// <summary>
    /// <c>reuse_key</c> and <c>extractor.profile</c> out of the head of a package.
    ///
    /// <paramref name="head"/> is the first <see cref="HeadBytes"/> of the file, so the reader
    /// is told the input is not final and simply runs out of tokens rather than reporting the
    /// truncation as broken JSON.
    /// </summary>
    private static PackageHead ReadHead(byte[] head)
    {
        var reader = new Utf8JsonReader(head, isFinalBlock: false, state: default);
        bool inExtractor = false;
        string? reuseKey = null;
        DumpProfile? profile = null;

        while (reader.Read())
        {
            if (reader.TokenType != JsonTokenType.PropertyName)
            {
                continue;
            }

            if (reader.CurrentDepth == 1)
            {
                // The top level again: either this names something we want, or whatever
                // object we were in has ended.
                inExtractor = reader.ValueTextEquals(ExtractorProperty);
                if (reader.ValueTextEquals(ReuseKeyProperty) && reader.Read())
                {
                    reuseKey = reader.TokenType == JsonTokenType.String ? reader.GetString() : null;
                }

                continue;
            }

            if (!inExtractor || reader.CurrentDepth != 2 || !reader.ValueTextEquals(ProfileProperty))
            {
                continue;
            }

            profile = reader.Read() && reader.TokenType == JsonTokenType.String
                ? ProfileNamed(reader.GetString())
                : null;
            break;
        }

        return new PackageHead(reuseKey, profile);
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
            if (string.Equals(PackageSerializer.EnumToJsonName(candidate), name, StringComparison.Ordinal))
            {
                return candidate;
            }
        }

        return null;
    }
}
