using System;
using System.Collections.Generic;
using System.Globalization;
using SwReview.Extractor.Ir;

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
    private static readonly string[] RevisionProperties = { "Revision", "Rev" };

    private static readonly string[] VersionProperties = { "PDM Version", "Version", "PDMVersion" };

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

            manifest.Entries.Add(new ManifestEntry
            {
                DocumentId = document.DocumentId,
                VaultPath = document.Path,
                VaultVersion = version,
                Revision = revision,
                Configuration = configuration,
                LocalModified = null,
                ExportMethod = ExportMethod.Native,
            });

            RecordGaps(scope, document, revision, version);
        }

        return manifest;
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
