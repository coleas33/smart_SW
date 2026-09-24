using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;

namespace SwReview.Extractor.Probes;

/// <summary>
/// A file as its folder lists it (probe D13): whether it is there, its length, write time and
/// attribute bits, read from the directory entry rather than by opening the file.
/// </summary>
public sealed class ProbeFileEntry : IEquatable<ProbeFileEntry>
{
    public ProbeFileEntry(bool present, long length, DateTime? lastWriteUtc, int attributes)
    {
        Present = present;
        Length = length;
        LastWriteUtc = lastWriteUtc;
        Attributes = attributes;
    }

    /// <summary>A file its folder does not list.</summary>
    public static ProbeFileEntry Absent { get; } = new ProbeFileEntry(false, 0, null, 0);

    public bool Present { get; }

    public long Length { get; }

    public DateTime? LastWriteUtc { get; }

    /// <summary><c>FileAttributes</c>, verbatim: an offline or recall-on-access bit is what a vault view's placeholder shows.</summary>
    public int Attributes { get; }

    public bool Equals(ProbeFileEntry? other) =>
        other != null
        && Present == other.Present
        && Length == other.Length
        && LastWriteUtc == other.LastWriteUtc
        && Attributes == other.Attributes;

    public override bool Equals(object? obj) => Equals(obj as ProbeFileEntry);

    public override int GetHashCode() => (Present, Length, LastWriteUtc, Attributes).GetHashCode();
}

/// <summary>A file's size, write time and SHA-256 (probe D14), read without changing it.</summary>
public sealed class ProbeFileState
{
    public ProbeFileState(long length, DateTime lastWriteUtc, string sha256)
    {
        Length = length;
        LastWriteUtc = lastWriteUtc;
        Sha256 = sha256 ?? throw new ArgumentNullException(nameof(sha256));
    }

    public long Length { get; }

    public DateTime LastWriteUtc { get; }

    /// <summary>Lower-case hex; compared, never printed.</summary>
    public string Sha256 { get; }
}

/// <summary>
/// The file-system reads probes D13 and D14 make, behind one seam so every rule around them is
/// tested with a fake. None of them writes, and none holds a file longer than the call.
/// </summary>
public interface IProbeFiles
{
    /// <summary><see cref="File.Exists(string)"/>: the very check discovery makes for a candidate.</summary>
    bool Exists(string path);

    /// <summary>The file's directory entry, or <see cref="ProbeFileEntry.Absent"/>.</summary>
    ProbeFileEntry Entry(string path);

    /// <summary>Size, write time and SHA-256, reading the bytes shared for reading, writing and deleting; throws when it cannot.</summary>
    ProbeFileState Read(string path);

    /// <summary>Opens the file for reading with no sharing and closes it at once; throws when another process holds it.</summary>
    void OpenExclusive(string path);
}

/// <summary>The file system itself.</summary>
public sealed class ProbeFiles : IProbeFiles
{
    public bool Exists(string path) => File.Exists(path);

    public ProbeFileEntry Entry(string path)
    {
        string? folder = Path.GetDirectoryName(path);
        string name = Path.GetFileName(path);
        if (string.IsNullOrEmpty(folder) || string.IsNullOrEmpty(name) || !Directory.Exists(folder))
        {
            return ProbeFileEntry.Absent;
        }

        FileInfo? entry = new DirectoryInfo(folder).EnumerateFiles(name).FirstOrDefault(
            file => string.Equals(file.Name, name, StringComparison.OrdinalIgnoreCase));
        return entry == null
            ? ProbeFileEntry.Absent
            : new ProbeFileEntry(true, entry.Length, entry.LastWriteTimeUtc, (int)entry.Attributes);
    }

    public ProbeFileState Read(string path)
    {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (var sha = SHA256.Create())
        {
            byte[] digest = sha.ComputeHash(stream);
            var info = new FileInfo(path);
            return new ProbeFileState(
                stream.Length,
                info.LastWriteTimeUtc,
                string.Concat(digest.Select(b => b.ToString("x2", System.Globalization.CultureInfo.InvariantCulture))));
        }
    }

    public void OpenExclusive(string path)
    {
        using (new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None))
        {
        }
    }
}
