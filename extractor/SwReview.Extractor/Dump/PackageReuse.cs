using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>What one attempt to reuse an earlier extraction decided.</summary>
public sealed class ReuseOutcome
{
    internal ReuseOutcome(
        DumpResult? result,
        PackageIndexRow? row,
        string message,
        IReadOnlyList<ReuseRefusal> refusals)
    {
        Result = result;
        Row = row;
        Message = message;
        Refusals = refusals;
    }

    /// <summary>The copied package, or null when the caller must dump after all.</summary>
    public DumpResult? Result { get; }

    /// <summary>The run folder that was reused, or null.</summary>
    public PackageIndexRow? Row { get; }

    /// <summary>
    /// One sentence saying what happened, reused or not. Never empty: reuse is stated, never
    /// silent, and so is a refusal to reuse - an engineer who asked for it and did not get it
    /// is owed the reason on the spot.
    /// </summary>
    public string Message { get; }

    /// <summary>Why reuse was refused, empty when it was not.</summary>
    public IReadOnlyList<ReuseRefusal> Refusals { get; }
}

/// <summary>
/// Lever 9's reuse path: copy an earlier run's <c>package.json</c> and <c>meshes/</c> into this
/// run's folder instead of dumping (data-model.md 9.5, T091).
///
/// <b>The reused package still needs its own run folder.</b> VERIFIED that <c>chat/server.py</c>
/// claims a run folder per chat and refuses a second (<c>RunDirInUse</c>), and that
/// <c>session.json</c>, <c>events.jsonl</c> and <c>report.md</c> are written into it. So reuse
/// is "create the folder as today, then copy instead of dump", never "point at the old folder".
///
/// Three guards, all required:
/// <list type="number">
/// <item><b>Stated, never silent</b>: <c>reused_from</c> and <c>reused_at</c> on the package,
/// <see cref="StatusLine"/> in the pane instead of "Extracting evidence from ...", and the fact
/// in the report header and in <c>session.json</c> (both read it off the package).</item>
/// <item><b>Never crosses a refusal</b>: <see cref="ReuseRefusals"/> is asked about the live
/// document's package <i>and</i> about the candidate on disk, and any refusal means dump.</item>
/// <item><b>The key is recomputed at reuse time</b> from the live document's references now.
/// The stored <c>reuse_key</c> is only ever used to find candidates, never to trust one.</item>
/// </list>
/// </summary>
public static class PackageReuse
{
    /// <summary>
    /// Reuses an earlier extraction into <c>options.OutputDirectory</c>, or explains why not.
    ///
    /// <paramref name="probe"/> is the package a full dump of the live document would write,
    /// built as far as the key needs it (<see cref="PackageWriter.BuildReuseProbe"/>): the key
    /// is taken over what is on screen now, not over what some file claims.
    /// </summary>
    public static ReuseOutcome Reuse(
        EvidencePackage probe,
        DumpOptions options,
        string? runRoot,
        bool? unsavedChanges,
        DateTimeOffset now)
    {
        if (probe == null)
        {
            throw new ArgumentNullException(nameof(probe));
        }

        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        IReadOnlyList<ReuseRefusal> refusals = ReuseRefusals.Of(probe, unsavedChanges);
        if (refusals.Count > 0)
        {
            return Refused(refusals);
        }

        string key = ReuseKey.Of(probe, options);
        PackageIndexRow? row = PackageIndex.FindReusable(runRoot, key, options.Profile);
        if (row == null)
        {
            return new ReuseOutcome(
                null,
                null,
                "No earlier extraction of this document, dumped this way, was found; extracting.",
                new ReuseRefusal[0]);
        }

        string source = Path.Combine(runRoot!, row.Folder);
        EvidencePackage candidate;
        try
        {
            candidate = PackageSerializer.Deserialize(
                File.ReadAllText(Path.Combine(source, PackageWriter.PackageFileName)));
        }
        catch (Exception error) when (IsFileOrFormatError(error))
        {
            return new ReuseOutcome(
                null,
                null,
                $"The extraction in {row.Folder} could not be read ({error.Message}); extracting.",
                new ReuseRefusal[0]);
        }

        // The index and the head read are a finding aid, nothing more: what is reused is judged
        // on what the candidate actually contains, recomputed here, never on the key it claims.
        if (!string.Equals(ReuseKey.Of(candidate, options), key, StringComparison.Ordinal))
        {
            return new ReuseOutcome(
                null,
                null,
                $"The extraction in {row.Folder} is not the design on screen, whatever its "
                + "recorded key says; extracting.",
                new ReuseRefusal[0]);
        }

        IReadOnlyList<ReuseRefusal> candidateRefusals = ReuseRefusals.OfPackage(candidate);
        if (candidateRefusals.Count > 0)
        {
            return Refused(candidateRefusals);
        }

        try
        {
            DumpResult result = Copy(source, row.Folder, candidate, options, now);
            return new ReuseOutcome(result, row, StatusLine(row, now), new ReuseRefusal[0]);
        }
        catch (Exception error) when (IsFileOrFormatError(error))
        {
            return new ReuseOutcome(
                null,
                null,
                $"The extraction in {row.Folder} could not be copied ({error.Message}); extracting.",
                new ReuseRefusal[0]);
        }
    }

    /// <summary>
    /// What the pane says instead of "Extracting evidence from ...". The folder and the age are
    /// both in it because "reused" without "from what, and how old" is not a statement an
    /// engineer can act on.
    /// </summary>
    public static string StatusLine(PackageIndexRow row, DateTimeOffset now)
    {
        if (row == null)
        {
            throw new ArgumentNullException(nameof(row));
        }

        return $"Reusing the extraction from {row.Folder} ({Age(now - row.WrittenAt)}).";
    }

    /// <summary>
    /// How old the reused extraction is, in the coarsest unit that is still true. Rounded down:
    /// an extraction reported as older than it is costs a dump, one reported as newer than it
    /// is costs trust.
    /// </summary>
    public static string Age(TimeSpan age)
    {
        if (age < TimeSpan.Zero)
        {
            // A folder written "in the future" is a clock that moved, not an age.
            return "age unknown";
        }

        if (age.TotalMinutes < 1)
        {
            return "under a minute old";
        }

        if (age.TotalHours < 1)
        {
            return Count((int)age.TotalMinutes, "minute") + " old";
        }

        if (age.TotalDays < 1)
        {
            return Count((int)age.TotalHours, "hour") + " old";
        }

        return Count((int)age.TotalDays, "day") + " old";
    }

    /// <summary>
    /// Copies <c>package.json</c> and <c>meshes/</c> into this run's folder, stamping the
    /// provenance onto the package as it goes.
    ///
    /// The package is rewritten rather than copied byte for byte because the provenance has to
    /// change; everything else is the object the source file deserialized to, through the one
    /// serializer both sides use, so the result is the source package plus its provenance.
    ///
    /// The one exception is <c>extractor.phases</c>, which is re-stamped rather than carried:
    /// those rows are wall clock from a dump that ran in another run, and no dump phase runs
    /// here at all.
    /// </summary>
    private static DumpResult Copy(
        string source,
        string folder,
        EvidencePackage candidate,
        DumpOptions options,
        DateTimeOffset now)
    {
        candidate.ReusedFrom = folder;
        candidate.ReusedAt = now;

        // "No phase ran here", said out loud, rather than the timings of the dump this
        // package was copied from. A reader of a reused package - and lever 9's own A/B
        // harness, whose only dump metric this is - would otherwise read measurements of a
        // run that did not happen.
        candidate.Extractor.Phases.Clear();
        candidate.Extractor.Phases.AddRange(PackageWriter.NoPhaseRan());

        Directory.CreateDirectory(options.OutputDirectory);
        string path = Path.Combine(options.OutputDirectory, PackageWriter.PackageFileName);
        File.WriteAllText(path, PackageSerializer.Serialize(candidate));

        var meshes = new DirectoryInfo(Path.Combine(source, PackageWriter.MeshDirectoryName));
        if (meshes.Exists)
        {
            string target = Path.Combine(options.OutputDirectory, PackageWriter.MeshDirectoryName);
            Directory.CreateDirectory(target);
            foreach (FileInfo mesh in meshes.GetFiles())
            {
                mesh.CopyTo(Path.Combine(target, mesh.Name), overwrite: true);
            }
        }

        return new DumpResult(candidate, path);
    }

    private static ReuseOutcome Refused(IReadOnlyList<ReuseRefusal> refusals)
    {
        string first = refusals[0].Reason;
        string rest = refusals.Count > 1
            ? $" ({refusals.Count - 1} more reason{(refusals.Count == 2 ? string.Empty : "s")})"
            : string.Empty;

        return new ReuseOutcome(null, null, $"Not reusing an earlier extraction: {first}{rest}", refusals);
    }

    private static string Count(int value, string unit) =>
        value.ToString(CultureInfo.InvariantCulture) + " " + unit + (value == 1 ? string.Empty : "s");

    /// <summary>
    /// The failures that mean "this candidate cannot be used", as opposed to a bug here. A
    /// candidate that cannot be read or copied is a miss: the dump it would have saved runs.
    /// </summary>
    private static bool IsFileOrFormatError(Exception error) =>
        error is IOException
        || error is UnauthorizedAccessException
        || error is System.Text.Json.JsonException
        || error is ArgumentException
        || error is NotSupportedException;
}
