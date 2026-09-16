using System;
using System.Collections.Generic;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>One reason a package was not reused, in words a status line can print.</summary>
public sealed class ReuseRefusal
{
    public ReuseRefusal(string code, string reason)
    {
        Code = code;
        Reason = reason;
    }

    /// <summary>One of the closed list on <see cref="ReuseRefusals"/>.</summary>
    public string Code { get; }

    public string Reason { get; }
}

/// <summary>
/// What the package-reuse key cannot catch (data-model.md 9.3, feature 005 lever 9).
///
/// <see cref="ReuseKey"/> answers "is this the same design, dumped the same way". This answers
/// the different question "is matching enough", and the two are deliberately separate: a key
/// that differs costs one dump, while a hole in this list costs a wrong finding an engineer
/// then has to chase. Extraction is minutes; a wrong finding is hours.
///
/// The Python half is `swreview/benchmark/reuse.py::reuse_refusals`, with the same codes and
/// the same closed list. One difference, and it is in the contract rather than in the code:
/// this build has no <c>extractor.completed</c>, so an aborted dump is caught by the other
/// route data-model.md 9.3 allows - a <b>phase-level</b> <c>tool_error</c> gap, which
/// <c>PackageWriter.RunPhase</c> records with a <b>null</b> entity id, unlike a per-entity
/// <c>tool_error</c> which names its entity and is the ordinary unknown a review carries.
///
/// Clock skew is deliberately not here: modification time can move backwards, the key is
/// equality and not ordering, so skew is a false <b>miss</b> - one wasted dump, the safe
/// direction - never a stale package accepted as fresh.
/// </summary>
public static class ReuseRefusals
{
    public const string UnsavedChanges = "unsaved_changes";
    public const string SaveStateUnknown = "save_state_unknown";
    public const string UnresolvedComponent = "unresolved_component";
    public const string AbortedDump = "aborted_dump";
    public const string AmbiguousReferencedConfiguration = "ambiguous_referenced_configuration";
    public const string UnknownFileStat = "unknown_file_stat";

    /// <summary>
    /// Every reason this package must not be reused, not only the first.
    ///
    /// <paramref name="unsavedChanges"/> is the live document's <c>GetSaveFlag</c> answer:
    /// true refuses, and null - unreadable - refuses too. It is an argument rather than a
    /// package member because an in-memory edit changes nothing on disk, which is exactly why
    /// the key cannot see it.
    /// </summary>
    public static IReadOnlyList<ReuseRefusal> Of(EvidencePackage package, bool? unsavedChanges)
    {
        var refusals = new List<ReuseRefusal>();

        if (unsavedChanges == null)
        {
            refusals.Add(new ReuseRefusal(
                SaveStateUnknown,
                "The active document's save state could not be read, so reuse cannot be shown "
                + "to be safe."));
        }
        else if (unsavedChanges.Value)
        {
            refusals.Add(new ReuseRefusal(
                UnsavedChanges,
                "The active document has unsaved changes, which no file modification time can "
                + "see."));
        }

        refusals.AddRange(OfPackage(package));
        return refusals;
    }

    /// <summary>
    /// The reasons that are visible in the package itself, for the candidate on disk: the one
    /// being considered for reuse is read from a file, and whether <i>it</i> was a complete
    /// dump of a fully resolved assembly is a property of that file, not of the live session.
    /// </summary>
    public static IReadOnlyList<ReuseRefusal> OfPackage(EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        var refusals = new List<ReuseRefusal>();

        var components = new List<ComponentInstance>(package.Components);
        components.Sort((left, right) => string.CompareOrdinal(left.Id, right.Id));
        foreach (ComponentInstance component in components)
        {
            if (component.Suppression != SuppressionState.Resolved)
            {
                // MeshExporter skips a non-resolved component with a gap, so resolving one
                // changes what a review can see with no file change at all.
                refusals.Add(new ReuseRefusal(
                    UnresolvedComponent,
                    $"Component {component.Id} is "
                    + $"{PackageSerializer.EnumToJsonName(component.Suppression)}, so the dump "
                    + "read less of it than a resolved dump would."));
            }
        }

        foreach (Gap gap in package.Gaps)
        {
            if (gap.Kind == GapKind.ToolError && gap.EntityId == null)
            {
                refusals.Add(new ReuseRefusal(
                    AbortedDump,
                    $"The {gap.EntityKind} phase failed during this dump, so the package is "
                    + "missing evidence a fresh dump would hold."));
            }
        }

        IReadOnlyDictionary<string, IReadOnlyList<string>> references =
            ReuseKey.ReferencedConfigurations(package);
        var documents = new List<string>(references.Keys);
        documents.Sort(StringComparer.Ordinal);
        foreach (string documentId in documents)
        {
            IReadOnlyList<string> configurations = references[documentId];
            if (configurations.Count > 1)
            {
                refusals.Add(new ReuseRefusal(
                    AmbiguousReferencedConfiguration,
                    $"Document {documentId} is referenced in {configurations.Count} "
                    + $"configurations ({string.Join(", ", configurations)}), which the key "
                    + "records as a set and cannot tell apart per instance."));
            }
        }

        var entries = new List<ManifestEntry>(package.Manifest.Entries);
        entries.Sort((left, right) => string.CompareOrdinal(left.DocumentId, right.DocumentId));
        foreach (ManifestEntry entry in entries)
        {
            if (entry.FileModifiedUtc == null || entry.FileSizeBytes == null)
            {
                refusals.Add(new ReuseRefusal(
                    UnknownFileStat,
                    $"Document {entry.DocumentId} has no recorded modification time or file "
                    + "size, so a change to it would be invisible to the key."));
            }
        }

        return refusals;
    }

    /// <summary>Whether this package may be reused: exactly the absence of refusals.</summary>
    public static bool MayReuse(EvidencePackage package, bool? unsavedChanges) =>
        Of(package, unsavedChanges).Count == 0;
}
