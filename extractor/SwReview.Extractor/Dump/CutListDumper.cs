using System;
using System.Collections.Generic;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// What <see cref="CutListDumper"/> needs SOLIDWORKS to answer, so that every decision the
/// dumper makes - which features are cut-list folders, what becomes a gap, what is recorded
/// when a read fails - is testable on a machine with no seat. The same seam
/// <see cref="IFeatureReader"/> is, and <see cref="SwCutListReader"/> is the SOLIDWORKS side.
///
/// Every member here that maps to ONE interop call is gated by the dumper, which names it, so
/// the read-only guard and the SC-010 audit see the production member names even under a fake.
/// <see cref="ActiveConfiguration"/>, <see cref="Features"/>, <see cref="SubFeatures"/> and
/// <see cref="PersistRef"/> span several calls each and gate them inside the implementation.
/// </summary>
public interface ICutListReader
{
    /// <summary><c>IComponent2.GetModelDoc2</c>; null when the document is not loaded.</summary>
    object? Document(ScopedComponent component);

    /// <summary>
    /// The configuration the document is loaded in, which is the configuration its body-folder
    /// tree describes. Gates <c>ConfigurationManager.ActiveConfiguration</c> and
    /// <c>Configuration.Name</c> itself.
    /// </summary>
    string ActiveConfiguration(object document);

    /// <summary>
    /// The document's top-level features, in tree order. Gates <c>FirstFeature</c> and
    /// <c>GetNextFeature</c> itself, because one walk is two members.
    /// </summary>
    IReadOnlyList<object> Features(object document);

    /// <summary>
    /// The features SOLIDWORKS lists under <paramref name="feature"/>, in tree order. Gates
    /// <c>GetFirstSubFeature</c> and <c>GetNextSubFeature</c> itself.
    /// </summary>
    IReadOnlyList<object> SubFeatures(object feature);

    /// <summary><c>IFeature.Name</c>.</summary>
    string Name(object feature);

    /// <summary><c>IFeature.GetTypeName2</c>, verbatim.</summary>
    string TypeName(object feature);

    /// <summary>
    /// <c>IFeature.GetSpecificFeature2</c> when it is an <c>IBodyFolder</c>, else null. This is
    /// the whole of the structural identification: a feature is a cut-list folder because
    /// SOLIDWORKS hands back a body folder for it, never because its name looks like one.
    /// </summary>
    object? BodyFolder(object feature);

    /// <summary><c>IBodyFolder.GetBodyCount()</c>.</summary>
    int BodyCount(object bodyFolder);

    /// <summary><c>IFeature.ExcludeFromCutList()</c> - the read; the write is denied.</summary>
    bool ExcludedFromCutList(object feature);

    /// <summary>
    /// The item's persistent reference, scoped to the part document that owns it; null when
    /// SOLIDWORKS gave none. Gates <c>GetPersistReference3</c> itself.
    /// </summary>
    ScopedPersistRef? PersistRef(object document, object feature);
}

/// <summary>
/// T040. The <c>cutlist</c> phase (schema 1.4.0): one row per cut-list item of every resolved
/// part document, once per document however many times the part is instanced.
///
/// Four rules shape every read here:
///
///   * <b>Identification is structural.</b> A feature is a cut-list folder because
///     <c>GetSpecificFeature2</c> gives an <c>IBodyFolder</c> for it, and an item is one of
///     that folder's sub-features that is itself a body folder. Names are recorded, never
///     matched (difference bb), so a renamed item is still the same item and a rename is not
///     a waiver. <c>folder_type_name</c> is recorded verbatim, so a 2024 SP5 name this build
///     has never seen is visible on the package instead of silently dropped (PROBE-8, RK-5).
///   * <b>Nothing is defaulted.</b> A body count or an exclusion flag that could not be read
///     is null plus the gap entity kind <c>data-model.md</c> section 2.4 names, and the item
///     is still recorded, so Python reports it unresolved rather than passing it.
///   * <b>An empty folder is evidence.</b> A folder whose body count is 0 is not displayed by
///     SOLIDWORKS and is no check's subject, but it is recorded, so the coverage reason can
///     say how many folders were seen and how many were displayable.
///   * <b>Nothing mutates.</b> <c>ExcludeFromCutList</c> is the read; the whole cut-list write
///     family beside it (<c>SetAutomaticCutList</c>, <c>UpdateCutList</c>, <c>SortCutList</c>,
///     <c>set_ExcludeFromCutList</c>) is on the denylist and none of it is called.
/// </summary>
public sealed class CutListDumper : ICutListSource
{
    private readonly SwGate _gate;
    private readonly ICutListReader _reader;

    public CutListDumper(SwGate gate, ICutListReader reader)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _reader = reader ?? throw new ArgumentNullException(nameof(reader));
    }

    public IReadOnlyList<CutListItem> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var items = new List<CutListItem>();
        var walked = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (ScopedComponent component in scope.Components)
        {
            ComponentNode node = component.Node;

            // Only parts carry a cut list, and a document already walked is not walked again;
            // neither is a loss, so neither is a gap.
            //
            // An instance that is not resolved is not one either: the component tree records
            // its suppression state and the feature phase records the same loss once per
            // instance (feature_tree_unavailable), and Python grades a document reached only
            // through such instances unresolved off the component tree alone. A cut_list_folder
            // gap here is keyed to the DOCUMENT, and claiming the document's cut list was
            // unread would be false whenever another instance of the same part resolves.
            if (node.DocumentKind != DocumentKind.Part
                || node.Suppression != SuppressionState.Resolved
                || walked.Contains(node.DocumentPath))
            {
                continue;
            }

            object? document = null;
            if (!scope.Gaps.TryStep(
                "cut_list_folder",
                component.DocumentId,
                $"read GetModelDoc2 for '{node.Key}'",
                () => { document = _gate.Call("GetModelDoc2", () => _reader.Document(component)); }))
            {
                continue;
            }

            if (document == null)
            {
                // A resolved instance whose document is not loaded IS a loss, and it is the
                // document's: swallowed, it would reach Python as "the part records no
                // cut-list items", which is a silent skip wearing the wrong reason
                // (difference aa). FeatureDumper names the same loss the same way.
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "cut_list_folder",
                    component.DocumentId,
                    $"'{node.Key}' has no loaded model document, so its cut list was not read.",
                    null);
                continue;
            }

            walked.Add(node.DocumentPath);
            ReadDocument(scope, component.DocumentId, document!, items);
        }

        return items;
    }

    /// <summary>Every cut-list folder of one document, and every item under each.</summary>
    private void ReadDocument(
        DumpScope scope, string documentId, object document, List<CutListItem> items)
    {
        string? configuration = scope.Gaps.TryStep<string>(
            "cut_list_folder",
            documentId,
            "read the active configuration before walking the body folders",
            () => _reader.ActiveConfiguration(document));

        if (configuration == null)
        {
            // Which configuration the tree was read in is part of the evidence, not a detail:
            // rows recorded without it would name a cut list nobody can say belongs to the
            // configuration the check graded.
            return;
        }

        IReadOnlyList<object>? features = scope.Gaps.TryStep<IReadOnlyList<object>>(
            "cut_list_folder",
            documentId,
            "walk the feature tree for body folders",
            () => _reader.Features(document));

        if (features == null)
        {
            return;
        }

        for (int i = 0; i < features.Count; i++)
        {
            object feature = features[i];
            int position = i;

            object? folder = null;
            bool answered = scope.Gaps.TryStep(
                "cut_list_folder",
                documentId,
                $"read GetSpecificFeature2 for feature {position} of the tree",
                () => { folder = _gate.Call("GetSpecificFeature2", () => _reader.BodyFolder(feature)); });

            // A feature that is not a body folder is not a cut list, and that is not a gap. A
            // read that threw IS one: swallowed, it would read as "this part has no cut list",
            // which is a silent pass on the check whose defect is an absence (RK-5).
            if (!answered || folder == null)
            {
                continue;
            }

            ReadFolder(scope, documentId, document, feature, configuration!, items);
        }
    }

    /// <summary>One cut-list folder: its own name and type, then a row per item under it.</summary>
    private void ReadFolder(
        DumpScope scope,
        string documentId,
        object document,
        object folder,
        string configuration,
        List<CutListItem> items)
    {
        // The folder's own reads fail into an empty string plus a gap, and its items are
        // recorded anyway: the folder's type name is context for the row, not the row.
        string folderName = ReadText(scope, documentId, "Feature.Name", () => _reader.Name(folder));
        string folderTypeName =
            ReadText(scope, documentId, "GetTypeName2", () => _reader.TypeName(folder));

        IReadOnlyList<object>? children = scope.Gaps.TryStep<IReadOnlyList<object>>(
            "cut_list_folder",
            documentId,
            $"read the sub-features of '{folderName}'",
            () => _reader.SubFeatures(folder));

        if (children == null)
        {
            return;
        }

        foreach (object child in children)
        {
            object? itemFolder = null;
            bool answered = scope.Gaps.TryStep(
                "cut_list_folder",
                documentId,
                $"read GetSpecificFeature2 for an item of '{folderName}'",
                () => { itemFolder = _gate.Call("GetSpecificFeature2", () => _reader.BodyFolder(child)); });

            // A child that is not itself a body folder is a body, not a cut-list item - an
            // ordinary part's Solid Bodies folder lists those - so it is no row. A child whose
            // read threw is recorded anyway, with an unknown body count, because it may well
            // have been one.
            if (answered && itemFolder == null)
            {
                continue;
            }

            items.Add(ReadItem(
                scope, documentId, document, child, itemFolder, folderName, folderTypeName, configuration));
        }
    }

    /// <summary>One cut-list item, with its id allocated in traversal order.</summary>
    private CutListItem ReadItem(
        DumpScope scope,
        string documentId,
        object document,
        object feature,
        object? bodyFolder,
        string folderName,
        string folderTypeName,
        string configuration)
    {
        string id = scope.CutListIds.Next();
        string name = ReadText(scope, documentId, "Feature.Name", () => _reader.Name(feature), id);

        int? bodyCount = null;
        if (bodyFolder != null)
        {
            object found = bodyFolder!;
            scope.Gaps.TryStep(
                "cut_list_body_count",
                id,
                $"read GetBodyCount for '{name}'",
                () => { bodyCount = _gate.Call("GetBodyCount", () => _reader.BodyCount(found)); });
        }

        bool? excluded = null;
        scope.Gaps.TryStep(
            "cut_list_exclusion",
            id,
            $"read ExcludeFromCutList for '{name}'",
            () =>
            {
                excluded = _gate.Call("ExcludeFromCutList", () => _reader.ExcludedFromCutList(feature));
            });

        // A reference SOLIDWORKS declined is a null pair and no gap: FR-026 wants that stated,
        // because the id is then a within-dump identity and the page shows no Show control.
        // A read that THREW is a gap - that is the dump failing, not SOLIDWORKS answering.
        ScopedPersistRef? reference = scope.Gaps.TryStep<ScopedPersistRef>(
            "cut_list_folder",
            id,
            $"read GetPersistReference3 for '{name}'",
            () => _reader.PersistRef(document, feature));

        return new CutListItem
        {
            Id = id,
            DocumentId = documentId,
            Configuration = configuration,
            FolderName = folderName,
            FolderTypeName = folderTypeName,
            Name = name,
            BodyCount = bodyCount,
            ExcludedFromCutList = excluded,
            PersistRef = reference?.Base64,
            PersistRefScope = reference?.ScopeDocumentId,
        };
    }

    /// <summary>
    /// One gated string read. An empty string plus a <c>cut_list_folder</c> gap when it threw:
    /// the record keeps its place in the package and the coverage says what was lost.
    /// </summary>
    private string ReadText(
        DumpScope scope, string documentId, string member, Func<string> read, string? entityId = null)
    {
        string? text = null;
        scope.Gaps.TryStep(
            "cut_list_folder",
            entityId ?? documentId,
            $"read {member} for a body folder",
            () => { text = _gate.Call(member, read); });

        return text ?? string.Empty;
    }
}
