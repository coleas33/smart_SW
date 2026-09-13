using System;
using System.Collections.Generic;
using System.Linq;

namespace SwReview.Extractor.Dump;

/// <summary>
/// One feature the dump walked past: what <c>IFeature.GetTypeName2</c> called it, and
/// whether the dumper that saw it went on to extract it.
/// </summary>
public sealed class TypeNameSighting
{
    public TypeNameSighting(string typeName, bool consumed)
    {
        TypeName = typeName ?? string.Empty;
        Consumed = consumed;
    }

    /// <summary>e.g. "HoleWzd", "CosmeticThread", "MateGroup", "CutExtrude", "FtrFolder".</summary>
    public string TypeName { get; }

    /// <summary>True when a dumper matched this name and read the feature.</summary>
    public bool Consumed { get; }
}

/// <summary>One type name no dumper read, and how many of them the document holds.</summary>
public sealed class TypeNameCount
{
    public TypeNameCount(string typeName, int count)
    {
        TypeName = typeName;
        Count = count;
    }

    public string TypeName { get; }

    public int Count { get; }
}

/// <summary>What one document's feature tree held that no dumper read.</summary>
public sealed class DocumentTypeNames
{
    public DocumentTypeNames(string documentPath, IReadOnlyList<TypeNameCount> names)
    {
        DocumentPath = documentPath;
        Names = names;
    }

    /// <summary>The document as the first pass over it spelt it.</summary>
    public string DocumentPath { get; }

    /// <summary>Unconsumed names, most numerous first, then by name.</summary>
    public IReadOnlyList<TypeNameCount> Names { get; }

    /// <summary>
    /// "AdvHoleWzd x4, FtrFolder x3". One line, because <c>swreview validate</c> prints a
    /// gap's reason on one line and the engineer reads it there.
    /// </summary>
    public string Describe() =>
        string.Join(", ", Names.Select(name => name.TypeName + " x" + name.Count));
}

/// <summary>
/// The dump's record of the <c>GetTypeName2</c> names it SAW, so the names it does not
/// recognise stop being invisible.
///
/// Today an unrecognised feature type is discarded at the three read sites
/// (ComponentTreeDumper's pattern walk, HoleDumper, MateDumper) with no gap and no log
/// line, so a wrong type-name constant shows up only as "holes: 0" with no error at all.
/// PackageWriter turns this census into one <see cref="Ir.GapKind.Unsupported"/> gap per
/// document, which is the Principle I rule that unsupported coverage stays visible.
///
/// It is a pure accumulator: no interop, no session, no ids. Two merge rules, both forced
/// by how the dumpers traverse:
///
///   - COUNTS ARE PER DOCUMENT, NOT PER PASS. HoleDumper walks a part once per component
///     instance, so a part used forty times is walked forty times and every pass sees the
///     same features. The count kept is therefore the largest a single pass reported, not
///     the sum, which would read "CutExtrude x40" for eleven cuts.
///   - CONSUMPTION IS THE UNION OF THE PASSES. The root assembly is walked twice: the
///     component-pattern walk reads LocalLPattern and ignores MateGroup, the mate walk
///     does the opposite. Neither pass alone knows what the dump as a whole read.
/// </summary>
public sealed class TypeNameCensus
{
    /// <summary>
    /// What a feature whose <c>GetTypeName2</c> came back blank is counted under. It is a
    /// phrase, not a name, so nothing can mistake it for something to grep the API for.
    /// </summary>
    public const string NoTypeName = "(no type name)";

    /// <summary>
    /// Keyed the way <see cref="Ids.DocumentIds"/> hashes a path, so the same file
    /// referenced with different casing is one document and not two censuses.
    /// </summary>
    private readonly Dictionary<string, DocumentEntry> _byDocument =
        new Dictionary<string, DocumentEntry>(StringComparer.OrdinalIgnoreCase);

    private readonly List<DocumentEntry> _order = new List<DocumentEntry>();

    /// <summary>
    /// Records one walk of one document's feature tree. A feature whose name came back
    /// blank - the read sites read GetTypeName2 as <c>?? string.Empty</c> - is counted
    /// under <see cref="NoTypeName"/> rather than dropped: it was walked past and not
    /// read, which is the unresolved coverage this census exists to show.
    /// </summary>
    public void AddPass(string documentPath, IEnumerable<TypeNameSighting> sightings)
    {
        if (string.IsNullOrWhiteSpace(documentPath))
        {
            throw new ArgumentException("A census pass needs the document it walked.", nameof(documentPath));
        }

        if (sightings == null)
        {
            throw new ArgumentNullException(nameof(sightings));
        }

        DocumentEntry entry = EntryFor(documentPath);
        var pass = new Dictionary<string, int>(StringComparer.Ordinal);

        foreach (TypeNameSighting sighting in sightings)
        {
            if (sighting == null)
            {
                continue;
            }

            string typeName = string.IsNullOrWhiteSpace(sighting.TypeName) ? NoTypeName : sighting.TypeName;

            pass[typeName] = pass.TryGetValue(typeName, out int seen) ? seen + 1 : 1;

            if (sighting.Consumed)
            {
                entry.Consumed.Add(typeName);
            }
        }

        foreach (KeyValuePair<string, int> counted in pass)
        {
            if (!entry.Counts.TryGetValue(counted.Key, out int known) || counted.Value > known)
            {
                entry.Counts[counted.Key] = counted.Value;
            }
        }
    }

    /// <summary>
    /// Per document, the type names no pass consumed. Documents in the order they were
    /// first walked; a document whose every type name was read is left out entirely.
    /// </summary>
    public IReadOnlyList<DocumentTypeNames> Unconsumed()
    {
        var documents = new List<DocumentTypeNames>();

        foreach (DocumentEntry entry in _order)
        {
            List<TypeNameCount> names = entry.Counts
                .Where(counted => !entry.Consumed.Contains(counted.Key))
                .OrderByDescending(counted => counted.Value)
                .ThenBy(counted => counted.Key, StringComparer.Ordinal)
                .Select(counted => new TypeNameCount(counted.Key, counted.Value))
                .ToList();

            if (names.Count > 0)
            {
                documents.Add(new DocumentTypeNames(entry.DocumentPath, names));
            }
        }

        return documents;
    }

    private DocumentEntry EntryFor(string documentPath)
    {
        if (_byDocument.TryGetValue(documentPath, out DocumentEntry entry))
        {
            return entry;
        }

        entry = new DocumentEntry(documentPath);
        _byDocument[documentPath] = entry;
        _order.Add(entry);
        return entry;
    }

    private sealed class DocumentEntry
    {
        public DocumentEntry(string documentPath)
        {
            DocumentPath = documentPath;
        }

        public string DocumentPath { get; }

        /// <summary>Type name to the largest count a single pass reported.</summary>
        public Dictionary<string, int> Counts { get; } = new Dictionary<string, int>(StringComparer.Ordinal);

        /// <summary>Type names some pass read. GetTypeName2 names are case sensitive.</summary>
        public HashSet<string> Consumed { get; } = new HashSet<string>(StringComparer.Ordinal);
    }
}
