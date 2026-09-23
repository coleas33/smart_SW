using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

namespace SwReview.AddIn.Review;

/// <summary>
/// The two id lookups <see cref="SwEntityResolver"/> needs, read out of the run folder's own
/// package - `package.json`, or the `package-before.json` a remodel run holds instead.
///
/// A finding names entities the way the package names them: `persist_ref_scope` is a
/// `document_id` and the affected component is a `component_id`. SOLIDWORKS knows neither. It
/// wants the document's path - so a reference belonging to a part is resolved against that part
/// and not against the assembly - and the component's full instance path, which is what
/// <c>SelectByID2</c> addresses a component by and what a failed resolve hands back so the
/// engineer can find the component in the tree (spec Edge Cases, SC-007).
///
/// The package is read once per run folder and kept. A review of a large assembly writes tens of
/// megabytes, Show is pressed once per finding, and the parse happens on the SOLIDWORKS
/// application thread with the engineer waiting on it.
///
/// <b>A lookup may name its folder</b> (feature 009 FR-023). The Review tab's Show names the chat
/// it shows, and the host resolves that chat's folder; that folder wins over the one the
/// constructor's <c>Func</c> names - the pane's latest run, which a Model check or a remodel
/// replaces - and a null folder falls back to it. What is kept is each folder's two id maps, not
/// its package, so alternating Show between a review and a check tab parses neither again.
///
/// <b>Nothing here throws.</b> No run yet, no package under either name, a half-written one, an
/// id that is not in it - all of them answer null, and Show then falls back to selecting the resolved
/// entity by type and reports no full path. That is a worse answer than the right one and a far
/// better one than an exception out of the application thread.
/// </summary>
public sealed class RunPackageIndex
{
    private static readonly IReadOnlyDictionary<string, string> Empty =
        new Dictionary<string, string>(StringComparer.Ordinal);

    /// <summary>
    /// The names a run folder can hold its package under, in the order they are tried.
    ///
    /// A review's folder holds `package.json`. A remodel's holds no such file: the add-in's
    /// before-dump is written by the extractor under that name and then renamed to
    /// `package-before.json` (`contracts/run-artifacts.md` rows 27-28). That folder becomes the
    /// pane's latest run the moment a plan is made - `RemodelHostOptions.RegisterLatestRun`
    /// goes to <see cref="ReviewHost.TrackCheck"/>, exactly as a Model check's does - so
    /// without the second name, pressing Remodel would silently cost the Review and Model check
    /// tabs the full path on every Show for as long as the remodel stayed the latest run.
    ///
    /// The order is fixed rather than "whichever is newer", so Show resolves the same way on
    /// every press.
    /// </summary>
    private static readonly string[] PackageNames =
    {
        PackageWriter.PackageFileName,
        RunFolders.PackageBeforeName,
    };

    private readonly Func<string?> _runDirectory;
    private readonly object _gate = new object();

    /// <summary>Each folder's two id maps, by folder, once its package has been read.</summary>
    private readonly Dictionary<string, Maps> _loaded = new Dictionary<string, Maps>(StringComparer.OrdinalIgnoreCase);

    /// <param name="runDirectory">The run folder whose package the ids belong to, asked for on
    /// every lookup because the pane follows the engineer: a second review replaces the first
    /// and the cards then carry the second run's ids.</param>
    public RunPackageIndex(Func<string?> runDirectory)
    {
        _runDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
    }

    /// <summary>The path of the document a `document_id` names, or null.</summary>
    public string? DocumentPath(string documentId) => DocumentPath(documentId, null);

    /// <summary>
    /// The path of the document a `document_id` names in <paramref name="runDirectory"/>'s
    /// package - the pane's latest run when that is null - or null.
    /// </summary>
    public string? DocumentPath(string documentId, string? runDirectory) =>
        Lookup(documentId, runDirectory, documents: true);

    /// <summary>The full instance path of the component a `component_id` names, or null.</summary>
    public string? ComponentFullPath(string componentId) => ComponentFullPath(componentId, null);

    /// <summary>
    /// The full instance path of the component a `component_id` names in
    /// <paramref name="runDirectory"/>'s package - the pane's latest run when that is null - or null.
    /// </summary>
    public string? ComponentFullPath(string componentId, string? runDirectory) =>
        Lookup(componentId, runDirectory, documents: false);

    private string? Lookup(string? id, string? runDirectory, bool documents)
    {
        if (string.IsNullOrEmpty(id))
        {
            return null;
        }

        lock (_gate)
        {
            Maps maps = Load(runDirectory ?? _runDirectory());
            IReadOnlyDictionary<string, string> map = documents ? maps.Documents : maps.Components;
            return map.TryGetValue(id!, out string? value) && !string.IsNullOrEmpty(value) ? value : null;
        }
    }

    private Maps Load(string? runDirectory)
    {
        if (string.IsNullOrWhiteSpace(runDirectory))
        {
            return Maps.None;
        }

        if (_loaded.TryGetValue(runDirectory!, out Maps? kept))
        {
            return kept;
        }

        EvidencePackage? package = FirstPackageIn(runDirectory!);
        if (package == null)
        {
            // No package under either name, one still being written, or one this build cannot
            // parse. The run folder is left to speak for itself; Show degrades rather than
            // failing loudly in the middle of an unrelated action - and nothing is kept, so the
            // package is read once it has been written.
            return Maps.None;
        }

        var documents = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (Document document in package.Documents)
        {
            if (!string.IsNullOrEmpty(document.DocumentId))
            {
                documents[document.DocumentId] = document.Path;
            }
        }

        var components = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (ComponentInstance component in package.Components)
        {
            if (!string.IsNullOrEmpty(component.Id))
            {
                components[component.Id] = component.FullPath;
            }
        }

        var maps = new Maps(documents, components);
        _loaded[runDirectory!] = maps;
        return maps;
    }

    /// <summary>One folder's two id maps: what is kept of a package once it has been read.</summary>
    private sealed class Maps
    {
        public static readonly Maps None = new Maps(Empty, Empty);

        public Maps(IReadOnlyDictionary<string, string> documents, IReadOnlyDictionary<string, string> components)
        {
            Documents = documents;
            Components = components;
        }

        public IReadOnlyDictionary<string, string> Documents { get; }

        public IReadOnlyDictionary<string, string> Components { get; }
    }

    /// <summary>
    /// The first of <see cref="PackageNames"/> this folder holds and this build can parse, or
    /// null when it holds none.
    ///
    /// A name that is missing and a name that is there but unreadable are treated the same way
    /// and both fall through to the next one: a dump killed halfway leaves a file that is not a
    /// package, and the folder may still hold one that answers.
    /// </summary>
    private static EvidencePackage? FirstPackageIn(string runDirectory)
    {
        foreach (string name in PackageNames)
        {
            try
            {
                return PackageSerializer.Deserialize(
                    File.ReadAllText(Path.Combine(runDirectory, name)));
            }
            catch (Exception)
            {
                // Missing, half-written, or written to a schema this build cannot read.
            }
        }

        return null;
    }
}
