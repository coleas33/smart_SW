using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Ir;
using IrCapture = SwReview.Extractor.Ir.Capture;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T071. <c>interference</c> and <c>capture</c> add to a package a <c>dump</c> already
/// wrote rather than producing one of their own, so the results land next to the components
/// and faces they talk about (contracts/cli.md: "Appends ... to package.json").
///
/// Loading and re-serializing through <see cref="PackageSerializer"/> is deliberate: the
/// serializer refuses unknown properties, so appending to a package written by a different
/// schema version fails here with a clear message instead of silently dropping fields.
/// </summary>
public static class PackageAppender
{
    /// <summary>The package.json in <paramref name="packageDirectory"/>.</summary>
    public static string PathIn(string packageDirectory)
    {
        if (string.IsNullOrWhiteSpace(packageDirectory))
        {
            throw new ArgumentException("A package directory is required.", nameof(packageDirectory));
        }

        return Path.Combine(packageDirectory, PackageWriter.PackageFileName);
    }

    /// <summary>
    /// Loads the package in <paramref name="packageDirectory"/>. Throws
    /// <see cref="FileNotFoundException"/> with an instruction when there is none: running
    /// <c>interference</c> before <c>dump</c> is the common mistake, and a package invented
    /// here would have no components for the results to name.
    /// </summary>
    public static EvidencePackage Load(string packageDirectory)
    {
        string path = PathIn(packageDirectory);
        if (!File.Exists(path))
        {
            throw new FileNotFoundException(
                $"No {PackageWriter.PackageFileName} in '{packageDirectory}'. "
                + "Run 'dump --out' there first: interferences and captures are appended to an "
                + "existing package so they can name its components.",
                path);
        }

        return PackageSerializer.Deserialize(File.ReadAllText(path));
    }

    /// <summary>Writes the package back over the file it was loaded from.</summary>
    public static string Save(string packageDirectory, EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        string path = PathIn(packageDirectory);
        Directory.CreateDirectory(packageDirectory);
        File.WriteAllText(path, PackageSerializer.Serialize(package));
        return path;
    }

    /// <summary>
    /// Merges one interference run into <paramref name="package"/>.
    ///
    /// A run is a complete re-detection for one configuration, and its ids restart at
    /// <c>int:0001</c>, so rows from an earlier run of the SAME configuration are replaced
    /// rather than appended to: two runs appending would leave duplicate ids and a stale
    /// "no interference" row the reviewer would read as current. Other configurations are
    /// left alone.
    /// </summary>
    public static void Merge(
        EvidencePackage package,
        string configuration,
        IReadOnlyList<IrInterference> interferences,
        IReadOnlyList<Gap> gaps)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        package.Interferences.RemoveAll(
            row => string.Equals(row.Configuration, configuration, StringComparison.Ordinal));

        if (interferences != null)
        {
            package.Interferences.AddRange(interferences);
        }

        if (gaps != null)
        {
            package.Gaps.AddRange(gaps);
        }
    }

    /// <summary>
    /// Merges one interference run into the package on disk and saves it. Returns the path
    /// written.
    /// </summary>
    public static string AppendInterferences(
        string packageDirectory,
        string configuration,
        IReadOnlyList<IrInterference> interferences,
        IReadOnlyList<Gap> gaps)
    {
        EvidencePackage package = Load(packageDirectory);
        Merge(package, configuration, interferences, gaps);
        return Save(packageDirectory, package);
    }

    /// <summary>
    /// The allocator a new capture should use so its id continues past the captures the
    /// package already holds (ids restart at <c>cap:0001</c> in a fresh process).
    /// </summary>
    public static Ids.IdAllocator CaptureIds(EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        var existing = new List<string>(package.Captures.Count);
        foreach (IrCapture capture in package.Captures)
        {
            existing.Add(capture.Id);
        }

        return new Ids.IdAllocator(
            Capture.CaptureService.IdPrefix,
            Ids.IdAllocator.HighestIssued(Capture.CaptureService.IdPrefix, existing));
    }

    /// <summary>Merges one capture into <paramref name="package"/>. Captures are purely additive.</summary>
    public static void Merge(EvidencePackage package, IrCapture? capture, Gap? gap)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        if (capture != null)
        {
            package.Captures.Add(capture);
        }

        if (gap != null)
        {
            package.Gaps.Add(gap);
        }
    }
}
