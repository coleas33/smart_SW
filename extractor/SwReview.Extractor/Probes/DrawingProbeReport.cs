using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Probes;

/// <summary>
/// What one run of <c>probe drawings</c> prints, and the file the owner brings back in the handoff
/// (contracts/probes.md section 1): the header, every probe's section and the gate log, the same
/// lines on the console and in <c>drawings-probe-&lt;UTC time&gt;.txt</c> in <c>--out</c>. The file is
/// the one thing the run writes, it is never written over, and it names no file, path or value.
/// </summary>
public sealed class DrawingProbeReport
{
    /// <summary>The report file's name before its time stamp.</summary>
    public const string FilePrefix = "drawings-probe-";

    private const string FileExtension = ".txt";

    /// <summary>How many names one second's reports may take before the write gives up rather than loop.</summary>
    private const int MaxNames = 999;

    private readonly List<string> _lines = new List<string>();

    public IReadOnlyList<string> Lines => _lines;

    /// <summary>
    /// The run's own header: when, on which SOLIDWORKS, on what kind of document, and which probes -
    /// the document's kind and never its name. Null answers read <see cref="ProbeText.Unread"/>.
    /// </summary>
    public static IReadOnlyList<string> Header(
        DateTimeOffset generatedAt, string? swVersion, DocumentKind? kind, IReadOnlyList<string> probeIds) =>
        new[]
        {
            "swreview-extract probe drawings (feature 011, contracts/probes.md)",
            "generated: " + generatedAt.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
            "SOLIDWORKS: " + (string.IsNullOrWhiteSpace(swVersion) ? ProbeText.Unread : swVersion),
            "document: " + (kind == null ? ProbeText.Unread : PackageSerializer.EnumToJsonName(kind.Value)),
            "probes: " + (probeIds == null || probeIds.Count == 0 ? "none" : string.Join(", ", probeIds)),
        };

    public void Add(string line) => _lines.Add(line ?? string.Empty);

    public void AddRange(IEnumerable<string> lines)
    {
        foreach (string line in lines ?? Array.Empty<string>())
        {
            Add(line);
        }
    }

    /// <summary>Every line, each ended by a newline.</summary>
    public string Render()
    {
        var text = new StringBuilder();
        foreach (string line in _lines)
        {
            text.Append(line).Append('\n');
        }

        return text.ToString();
    }

    /// <summary>
    /// Writes the report in <paramref name="directory"/> (created when missing) as
    /// <c>drawings-probe-yyyyMMdd-HHmmss.txt</c> in UTC, and returns its path. A file of that name
    /// is never written over: the next free <c>-2</c>, <c>-3</c>... is taken, since two runs a
    /// second apart - D14 with the drawing closed, then open - are two records.
    /// </summary>
    public string Write(string directory, DateTimeOffset generatedAt)
    {
        if (string.IsNullOrWhiteSpace(directory))
        {
            throw new ArgumentException("The report is written in a folder, --out.", nameof(directory));
        }

        Directory.CreateDirectory(directory);
        string stem = FilePrefix + generatedAt.UtcDateTime.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
        byte[] bytes = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false).GetBytes(Render());

        for (int attempt = 1; attempt <= MaxNames; attempt++)
        {
            string path = Path.Combine(
                directory,
                stem + (attempt == 1 ? string.Empty : "-" + attempt.ToString(CultureInfo.InvariantCulture)) + FileExtension);
            try
            {
                using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    stream.Write(bytes, 0, bytes.Length);
                }

                return path;
            }
            catch (IOException) when (File.Exists(path))
            {
                // Taken: the next name. FileMode.CreateNew is the check, so no race can overwrite it.
            }
        }

        throw new IOException($"{MaxNames} reports of this second already exist in '{directory}', so this one was not written.");
    }
}
