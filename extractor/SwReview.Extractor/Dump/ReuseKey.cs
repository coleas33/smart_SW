using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// What a package claims to be: a SHA-256 over the design it was dumped from and the way it
/// was dumped (feature 005 lever 9, data-model.md 9.2). Written to
/// <see cref="EvidencePackage.ReuseKey"/> by <see cref="PackageWriter"/>, and recomputed from
/// the live document before any package is reused, never trusted from the file.
///
/// The key decides <b>matching</b> and nothing else. Two keys that differ mean "dump again",
/// which costs one dump and is always safe. What matching still cannot make safe - unsaved
/// in-memory edits, a non-resolved component, a dump that stopped short - is refused
/// separately by <see cref="ReuseRefusals"/>.
///
/// <b>This is one half of a cross-language agreement.</b> `reviewer/swreview/benchmark/reuse.py`
/// computes the same digest over the same package, and `ReuseKeyTests` pins the canonical form
/// and the digest against the text that module produces. Three rules keep the two in step, and
/// each is a bug the moment it is broken:
/// <list type="bullet">
/// <item>the form is JSON, so a configuration named <c>a"b</c> is one value and not two;</item>
/// <item>documents and components are sorted by id, so a traversal order is not a change;</item>
/// <item>a timestamp is rendered as the UTC instant it is, to microseconds - which is all a
/// Python datetime can carry, and therefore all the manifest records.</item>
/// </list>
/// </summary>
public static class ReuseKey
{
    /// <summary>The digest of <see cref="CanonicalForm"/>, lowercase hex.</summary>
    public static string Of(EvidencePackage package, DumpOptions options)
    {
        byte[] digest;
        using (var sha = SHA256.Create())
        {
            digest = sha.ComputeHash(Encoding.UTF8.GetBytes(CanonicalForm(package, options)));
        }

        var text = new StringBuilder(digest.Length * 2);
        foreach (byte value in digest)
        {
            text.Append(value.ToString("x2", CultureInfo.InvariantCulture));
        }

        return text.ToString();
    }

    /// <summary>
    /// The exact text the digest is taken over. Public because it is the thing the
    /// cross-language test compares: a digest that differs says nothing about why.
    /// </summary>
    public static string CanonicalForm(EvidencePackage package, DumpOptions options)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        IReadOnlyDictionary<string, IReadOnlyList<string>> references =
            ReferencedConfigurations(package);

        var form = new StringBuilder();
        form.Append('{');
        Member(form, "extractor_name", package.Extractor.Name, first: true);
        Member(form, "extractor_version", package.Extractor.Version);
        Member(form, "schema_version", package.SchemaVersion);
        Member(form, "profile", PackageSerializer.EnumToJsonName(package.Extractor.Profile));
        Member(form, "meshes", PackageSerializer.EnumToJsonName(options.Meshes));
        Member(form, "faces", PackageSerializer.EnumToJsonName(options.Faces));
        Member(form, "features", PackageSerializer.EnumToJsonName(options.Features));
        Member(form, "equations", PackageSerializer.EnumToJsonName(options.Equations));
        Member(form, "root_assembly_document_id", package.Design.RootAssemblyDocumentId);
        Member(form, "active_configuration", package.Design.ActiveConfiguration);

        form.Append(",\"documents\":[");
        bool firstDocument = true;
        foreach (ManifestEntry entry in package.Manifest.Entries
            .OrderBy(entry => entry.DocumentId, StringComparer.Ordinal))
        {
            if (!firstDocument)
            {
                form.Append(',');
            }

            firstDocument = false;
            form.Append('{');
            Member(form, "document_id", entry.DocumentId, first: true);
            Member(form, "configuration", entry.Configuration);
            form.Append(",\"referenced_configurations\":[");
            IReadOnlyList<string> configurations = references.TryGetValue(
                entry.DocumentId, out IReadOnlyList<string> found)
                ? found
                : new string[0];
            for (int i = 0; i < configurations.Count; i++)
            {
                if (i > 0)
                {
                    form.Append(',');
                }

                Text(form, configurations[i]);
            }

            form.Append("],\"file_modified_utc\":");
            if (entry.FileModifiedUtc == null)
            {
                form.Append("null");
            }
            else
            {
                Text(form, Instant(entry.FileModifiedUtc.Value));
            }

            form.Append(",\"file_size_bytes\":");
            form.Append(entry.FileSizeBytes == null
                ? "null"
                : entry.FileSizeBytes.Value.ToString(CultureInfo.InvariantCulture));
            form.Append('}');
        }

        form.Append("],\"components\":[");
        bool firstComponent = true;
        foreach (ComponentInstance component in package.Components
            .OrderBy(component => component.Id, StringComparer.Ordinal))
        {
            if (!firstComponent)
            {
                form.Append(',');
            }

            firstComponent = false;
            form.Append('{');
            Member(form, "component_id", component.Id, first: true);
            Member(form, "suppression", PackageSerializer.EnumToJsonName(component.Suppression));
            form.Append('}');
        }

        form.Append("]}");
        return form.ToString();
    }

    /// <summary>
    /// Document id to the sorted set of configurations its instances reference.
    ///
    /// <see cref="ManifestEntry.Configuration"/> is the <i>document's</i> active
    /// configuration while <see cref="ComponentInstance.ReferencedConfiguration"/> is per
    /// instance, so a per-instance switch is invisible without this.
    /// </summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<string>> ReferencedConfigurations(
        EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        var found = new Dictionary<string, SortedSet<string>>(StringComparer.Ordinal);
        foreach (ComponentInstance component in package.Components)
        {
            if (!found.TryGetValue(component.DocumentId, out SortedSet<string> configurations))
            {
                configurations = new SortedSet<string>(StringComparer.Ordinal);
                found[component.DocumentId] = configurations;
            }

            configurations.Add(component.ReferencedConfiguration);
        }

        var sorted = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        foreach (KeyValuePair<string, SortedSet<string>> pair in found)
        {
            sorted[pair.Key] = pair.Value.ToArray();
        }

        return sorted;
    }

    /// <summary>
    /// A modification time as the instant it is, normalised to UTC and to the microsecond.
    ///
    /// The same moment written <c>+00:00</c> and <c>-05:00</c> is the same file, and a false
    /// miss costs a whole dump. The microsecond is where the manifest stops, because that is
    /// where a Python datetime stops; a .NET tick below it would be hashed on one side and
    /// dropped on the other.
    /// </summary>
    public static string Instant(DateTimeOffset value)
    {
        DateTime utc = value.ToUniversalTime().UtcDateTime;
        long microseconds = (utc.Ticks % TimeSpan.TicksPerSecond) / 10;

        string text = utc.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture);
        if (microseconds != 0)
        {
            text += "." + microseconds.ToString("D6", CultureInfo.InvariantCulture);
        }

        return text + "+00:00";
    }

    private static void Member(StringBuilder form, string name, string value, bool first = false)
    {
        if (!first)
        {
            form.Append(',');
        }

        Text(form, name);
        form.Append(':');
        Text(form, value);
    }

    /// <summary>
    /// One JSON string, escaped the way `json.dumps(..., ensure_ascii=False)` escapes it:
    /// the two structural characters, the five short forms, and every other control
    /// character as <c>\u00xx</c>. Written by hand rather than through a serializer because
    /// the bytes are a wire format shared with another language, not a formatting choice.
    /// </summary>
    private static void Text(StringBuilder form, string? value)
    {
        form.Append('"');
        foreach (char character in value ?? string.Empty)
        {
            switch (character)
            {
                case '"':
                    form.Append("\\\"");
                    break;
                case '\\':
                    form.Append("\\\\");
                    break;
                case '\b':
                    form.Append("\\b");
                    break;
                case '\f':
                    form.Append("\\f");
                    break;
                case '\n':
                    form.Append("\\n");
                    break;
                case '\r':
                    form.Append("\\r");
                    break;
                case '\t':
                    form.Append("\\t");
                    break;
                default:
                    if (character < ' ')
                    {
                        form.Append("\\u");
                        form.Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        form.Append(character);
                    }

                    break;
            }
        }

        form.Append('"');
    }
}
