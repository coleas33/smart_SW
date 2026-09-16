using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T057. Provenance for every document: where it came from, which version, which revision,
/// which configuration.
///
/// The EPDM API is out of scope for this task, so the vault version is read only from
/// custom properties a vault typically writes back ("PDM Version", "Version"), and the
/// revision from "Revision" or "Rev". When neither is present the field is null AND a Gap
/// is recorded: a review that cannot say which version it looked at cannot claim the
/// finding applies to the released design (constitution Principle I, FR-002).
///
/// <c>vault_path</c> is the file path as SOLIDWORKS reports it; on a vault workstation that
/// IS the vault view path. <c>local_modified</c> stays null for the same reason as the
/// version: only the vault knows.
/// </summary>
public sealed class ManifestBuilder : IManifestSource
{
    /// <summary>
    /// What the gate is asked about before a document's path is stat'ed. Every read a dump
    /// makes is named at the door, so "what did this dump touch" is one record and not two.
    /// </summary>
    public const string FileStatMember = "FileInfo.LastWriteTimeUtc";

    private static readonly string[] RevisionProperties = { "Revision", "Rev" };

    private static readonly string[] VersionProperties = { "PDM Version", "Version", "PDMVersion" };

    private readonly SwGate? _gate;

    /// <summary>
    /// Builds a manifest. <paramref name="gate"/> is the session's gate, so the file stat the
    /// reuse key needs is recorded with every other read the dump made; null - the tests and
    /// any caller with no session - stats the file directly.
    /// </summary>
    public ManifestBuilder(SwGate? gate = null)
    {
        _gate = gate;
    }

    public Manifest Build(DumpScope scope, IReadOnlyList<Document> documents)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        if (documents == null)
        {
            throw new ArgumentNullException(nameof(documents));
        }

        var manifest = new Manifest();

        foreach (Document document in documents)
        {
            string configuration = document.ActiveConfiguration;
            IReadOnlyDictionary<string, string> properties = Properties(document, configuration);

            string? revision = Lookup(properties, RevisionProperties);
            int? version = ParseVersion(Lookup(properties, VersionProperties));
            FileStat stat = Stat(document.Path);

            manifest.Entries.Add(new ManifestEntry
            {
                DocumentId = document.DocumentId,
                VaultPath = document.Path,
                VaultVersion = version,
                Revision = revision,
                Configuration = configuration,
                LocalModified = null,
                ExportMethod = ExportMethod.Native,
                FileModifiedUtc = stat.ModifiedUtc,
                FileSizeBytes = stat.SizeBytes,
            });

            RecordGaps(scope, document, revision, version);
            RecordStatGap(scope, document, stat);
        }

        return manifest;
    }

    /// <summary>
    /// The document file's modification time and size, or <see cref="FileStat.Unknown"/>.
    ///
    /// The read goes through the gate so it is named with every other read the dump made, and
    /// it cannot throw through it: a path that is gone, on a share that dropped, or spelled in
    /// a way the filesystem rejects is an <b>answer</b>, and counting it as a failed interop
    /// call would push the circuit breaker towards stopping a dump that is working fine.
    /// </summary>
    private FileStat Stat(string path)
    {
        return _gate == null ? FileStat.Read(path) : _gate.Call(FileStatMember, () => FileStat.Read(path));
    }

    /// <summary>
    /// A path that could not be stat'ed is null plus a gap, never 0 and never "now": a review
    /// that cannot say when the file it read was last saved must say so (Principle I), and the
    /// package-reuse key refuses to match on an unknown rather than assuming it unchanged.
    /// </summary>
    private static void RecordStatGap(DumpScope scope, Document document, FileStat stat)
    {
        if (stat.ModifiedUtc != null && stat.SizeBytes != null)
        {
            return;
        }

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "manifest",
            document.DocumentId,
            $"The file modification time and size of '{document.FileName}' could not be read "
            + $"from '{document.Path}', so a reader cannot tell whether it changed since a "
            + "previous run.",
            stat.Error);
    }

    private static void RecordGaps(DumpScope scope, Document document, string? revision, int? version)
    {
        if (version == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "manifest",
                document.DocumentId,
                $"No vault version was found for '{document.FileName}'. The EPDM API is not read by "
                + "this build, and no 'PDM Version' or 'Version' custom property is set, so the "
                + "version this review looked at cannot be stated.",
                null);
        }

        if (revision == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "manifest",
                document.DocumentId,
                $"No revision was found for '{document.FileName}' "
                + "('Revision' or 'Rev' custom property is not set).",
                null);
        }

        scope.Gaps.Add(
            GapKind.Unsupported,
            "manifest",
            document.DocumentId,
            $"Whether '{document.FileName}' is modified locally relative to the vault was not "
            + "determined; only the vault knows, and the EPDM API is out of scope for this build.",
            null);
    }

    /// <summary>
    /// The configuration's own properties when it has any, otherwise the document's.
    /// Configuration-specific values win, because that is what a BOM would show.
    /// </summary>
    private static IReadOnlyDictionary<string, string> Properties(Document document, string configuration)
    {
        if (!string.IsNullOrEmpty(configuration)
            && document.ConfigProperties.TryGetValue(configuration, out Dictionary<string, string> config)
            && config.Count > 0)
        {
            var merged = new Dictionary<string, string>(document.CustomProperties, StringComparer.OrdinalIgnoreCase);
            foreach (KeyValuePair<string, string> pair in config)
            {
                merged[pair.Key] = pair.Value;
            }

            return merged;
        }

        return document.CustomProperties;
    }

    private static string? Lookup(IReadOnlyDictionary<string, string> properties, string[] names)
    {
        foreach (string name in names)
        {
            if (properties.TryGetValue(name, out string value) && !string.IsNullOrWhiteSpace(value))
            {
                return value.Trim();
            }
        }

        return null;
    }

    /// <summary>
    /// What one <see cref="FileInfo"/> read produced: both values, or neither and the reason.
    ///
    /// A pair rather than two reads, because a file that is replaced between the two would
    /// otherwise contribute one document's size and another's modification time to the key.
    /// </summary>
    private sealed class FileStat
    {
        private FileStat(DateTimeOffset? modifiedUtc, long? sizeBytes, string? error)
        {
            ModifiedUtc = modifiedUtc;
            SizeBytes = sizeBytes;
            Error = error;
        }

        public DateTimeOffset? ModifiedUtc { get; }

        public long? SizeBytes { get; }

        /// <summary>What the read threw, or null when it simply found nothing there.</summary>
        public string? Error { get; }

        /// <summary>
        /// Stats <paramref name="path"/>, answering unknown rather than throwing.
        ///
        /// The time is truncated to the microsecond the IR carries: a .NET tick is 100 ns, a
        /// Python datetime stops at the microsecond, and a value written finer than it can be
        /// read back would hash to one key on this side and another on the other.
        /// </summary>
        public static FileStat Read(string? path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return new FileStat(null, null, null);
            }

            try
            {
                var file = new FileInfo(path);
                if (!file.Exists)
                {
                    return new FileStat(null, null, null);
                }

                DateTime modified = file.LastWriteTimeUtc;
                return new FileStat(
                    new DateTimeOffset(
                        new DateTime(modified.Ticks - (modified.Ticks % 10), DateTimeKind.Utc)),
                    file.Length,
                    null);
            }
            catch (ArgumentException error)
            {
                return new FileStat(null, null, error.Message);
            }
            catch (IOException error)
            {
                return new FileStat(null, null, error.Message);
            }
            catch (NotSupportedException error)
            {
                return new FileStat(null, null, error.Message);
            }
            catch (UnauthorizedAccessException error)
            {
                return new FileStat(null, null, error.Message);
            }
        }
    }

    /// <summary>A version is an integer or it is unknown; "A.2" is not silently truncated.</summary>
    private static int? ParseVersion(string? text)
    {
        if (text == null)
        {
            return null;
        }

        return int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out int version)
            ? version
            : (int?)null;
    }
}
