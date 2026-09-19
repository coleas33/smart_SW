using System;
using System.Collections.Generic;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;

namespace SwReview.AddIn.Model;

/// <summary>Everything <see cref="ModelCheckHost"/> is given; injected so it is testable headless.</summary>
public sealed class ModelCheckHostOptions
{
    /// <param name="channel">Where replies and unsolicited messages go.</param>
    /// <param name="runRoot">The run root in force, read fresh: a settings save moves it.</param>
    public ModelCheckHostOptions(IPageChannel channel, Func<string> runRoot)
    {
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        RunRoot = runRoot ?? throw new ArgumentNullException(nameof(runRoot));
    }

    public IPageChannel Channel { get; }

    public Func<string> RunRoot { get; }

    /// <summary>
    /// The backend's endpoint, or null before it is listening. The page calls the check routes
    /// itself with what `init` carries, so this is the whole of the host's involvement with it.
    /// </summary>
    public Func<BackendEndpoint?> Backend { get; set; } = () => null;

    /// <summary>The open document, asked for fresh each time; SOLIDWORKS owns the answer.</summary>
    public Func<PageDocument?> CurrentDocument { get; set; } = () => null;

    /// <summary>
    /// The in-process extractor - the same <see cref="IReviewDump"/> the Review tab runs, asked
    /// for the <see cref="DumpProfile.ModelCheck"/> profile. Null until the add-in is attached
    /// to a SOLIDWORKS session, which is a state the pane really has.
    /// </summary>
    public IReviewDump? Dump { get; set; }

    /// <summary>
    /// Makes the check's folder the pane's latest run (`ReviewHost.TrackCheck`). There is one
    /// answer to "which folder is the pane looking at" and it is not this host's to keep.
    /// </summary>
    public Action<string> RegisterLatestRun { get; set; } = _ => { };

    /// <summary>Show in SOLIDWORKS; null before the add-in is attached.</summary>
    public Func<IEntityResolver?> EntityResolver { get; set; } = () => null;

    /// <summary>What `report.open`, `folder.open` and `log.open` shell out through.</summary>
    public Func<IPathOpener> Opener { get; set; } = () => new ShellPathOpener();

    /// <summary>%LOCALAPPDATA%\SwReview\logs by default; what `log.open` opens.</summary>
    public Func<string> LogFolder { get; set; } = ReviewHostOptions.DefaultLogFolder;

    /// <summary>Run-folder timestamps. Injected so the naming rule is testable.</summary>
    public Func<DateTime> Now { get; set; } = () => DateTime.Now;

    /// <summary>Values that must never reach the page (FR-015).</summary>
    public Func<IEnumerable<string?>> Secrets { get; set; } = () => new string?[0];
}

/// <summary>
/// The Model check page's other half: `ready`, `check.start`, and the four rows every pane host
/// shares, delegated to <see cref="PaneActions"/> (`contracts/model-check.md` sections 2 and 3).
///
/// Everything except `check.start` is <see cref="CheckPaneHost"/>'s - the envelope, `ready` and
/// its `init`, the check records, the unsolicited messages and the four shared rows - because
/// the Standards check tab needs the same plumbing and copying it would be the second largest
/// copy this codebase could make. The collaborator is <b>held, not inherited</b> (plan.md
/// Structure Decision 3, feature 006): a base class over the pane hosts would drag backend chat
/// state into a host that has none, and this host keeps its own start verb, its own refusals and
/// its own options either way. What it no longer keeps is a record type of its own:
/// <see cref="CheckRecord"/> is now <see cref="CheckPaneHost"/>'s and both check hosts share it,
/// which is a deviation from that decision's wording and is written down there.
///
/// What it does not do is most of the design:
///
/// <b>It evaluates nothing.</b> The page calls `POST /checks/rms` itself, with the token and
/// origin it received in `init`, the same way the Review page already calls the message,
/// evidence and disposition routes. There is exactly one no-language-model evaluation entry
/// point and it is in Python (FR-024); a host that called the rules would be a second one, and
/// keeping a potentially large result off the `postMessage` channel is a second reason.
///
/// <b>It registers no tool and writes to no document</b> (FR-031).
///
/// <b>It does not own "the pane's latest run".</b> It creates the check folder and the
/// collaborator hands it to <see cref="ModelCheckHostOptions.RegisterLatestRun"/>, so
/// `entity.show` resolves `document_id` through the package that was just written and the Ask
/// tab opens in the same place (FR-028).
///
/// What it does own is the order of one `check.start`, and it is not negotiable. The refusals
/// come first because a dump is SOLIDWORKS time. The run folder is created before the dump
/// because the dump writes into it. The folder is registered before the reply, so a
/// `POST /checks/rms` the page sends the instant it sees `check.extracted` resolves ids
/// through the right folder.
///
/// Threading: <see cref="Receive"/> is not re-entrant, and must not run on the SOLIDWORKS UI
/// thread - a dump occupies the application thread for as long as it takes. The caller
/// delivers page messages one at a time, as it already does for the Review page.
/// </summary>
public sealed class ModelCheckHost : IDisposable
{
    /// <summary>The only scope this increment evaluates (`contracts/model-check.md`).</summary>
    private const string PartKind = "part";

    /// <summary>The one message type this host answers itself.</summary>
    private const string StartType = "check.start";

    private readonly ModelCheckHostOptions _options;
    private readonly CheckPaneHost _pane;

    public ModelCheckHost(ModelCheckHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));

        // Every accessor is wrapped rather than handed over, so a caller that replaces one
        // after construction still has it read fresh - which is what "a settings save moves
        // the run root" and "the backend started after the pane opened" both depend on.
        _pane = new CheckPaneHost(new CheckPaneHostOptions(
            options.Channel, () => options.RunRoot(), StartType, StartCheck)
        {
            Backend = () => options.Backend(),
            CurrentDocument = () => options.CurrentDocument(),

            // What `init` reads the newest check back by after a restart, from the folder names
            // alone. `-check` is this tab's own suffix, so the Standards tab's runs are never
            // answered with here and this tab's are never answered with there
            // (`contracts/standards-check.md` section 4).
            LatestCheckSuffix = RunFolders.CheckSuffix,
            RegisterLatestRun = directory => options.RegisterLatestRun(directory),
            EntityResolver = () => options.EntityResolver(),
            Opener = () => options.Opener(),
            LogFolder = () => options.LogFolder(),
            Now = () => options.Now(),
            Secrets = () => options.Secrets(),
        });
    }

    /// <summary>The checks this host ran, oldest first.</summary>
    public IReadOnlyList<CheckRecord> Checks => _pane.Checks;

    /// <summary>The newest check, or null before the first one.</summary>
    public CheckRecord? LatestCheck => _pane.LatestCheck;

    /// <summary>Records a check's folder and makes it the pane's latest run.</summary>
    public CheckRecord TrackCheck(string runDirectory) => _pane.TrackCheck(runDirectory);

    /// <summary>The record for <paramref name="checkId"/>, or null.</summary>
    public CheckRecord? FindCheck(string checkId) => _pane.FindCheck(checkId);

    /// <summary>Handles one message from the page. Never throws.</summary>
    public void Receive(string json) => _pane.Receive(json);

    /// <summary>Sends an unsolicited message (`status`, `document.changed`, `backend.stopped`).</summary>
    public void Post(string type, object? payload) => _pane.Post(type, payload);

    /// <summary>Posts one `status`, with every secret masked out of it (FR-015).</summary>
    public void PostStatus(string stage, string message) => _pane.PostStatus(stage, message);

    /// <summary>Tells the page which document the pane is looking at now, or that there is none.</summary>
    public void DocumentChanged() => _pane.DocumentChanged();

    public void Dispose() => _pane.Dispose();

    // ---- check.start --------------------------------------------------------------------

    /// <summary>
    /// Press Model check: refuse what cannot be checked, name and create the check run folder,
    /// dump the open part into it with the reduced profile, register the folder as the pane's
    /// latest run, and tell the page where it is. The page does the rest.
    /// </summary>
    private void StartCheck(string? id)
    {
        PaneActions actions = _pane.Actions;

        PageDocument? document = _options.CurrentDocument();
        if (document == null)
        {
            actions.SendError(
                id,
                "NoDocument",
                "open the part you want checked in SOLIDWORKS first: the feature tree is read "
                + "from the active document.",
                retryable: true);
            return;
        }

        if (_options.Dump == null)
        {
            actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so nothing can be extracted.",
                retryable: true);
            return;
        }

        if (!string.Equals(document.Kind, PartKind, StringComparison.Ordinal))
        {
            // The rule family is written about a part's feature tree. An assembly answered with
            // 34 unresolved rules would read as a bad design rather than as a scope this
            // increment does not cover, so the refusal names the scope instead.
            actions.SendError(
                id,
                "NotAPart",
                "the Model check reads a part's feature tree, and the active document is "
                + (document.Kind == null ? "not a SOLIDWORKS part" : "a " + document.Kind)
                + ". Open the part on its own and press Model check again.",
                retryable: true);
            return;
        }

        string runDirectory;
        try
        {
            runDirectory = RunFolders.CreateForCheck(
                _options.RunRoot(), document.Path, _options.Now());
        }
        catch (Exception failure)
        {
            PostStatus("error", failure.Message);
            actions.SendError(
                id,
                "RunFolderFailed",
                $"the check folder could not be created under '{_options.RunRoot()}': "
                + failure.Message,
                retryable: false);
            return;
        }

        DumpSummary summary;
        PostStatus(
            "extracting",
            $"Reading the feature tree of {RunFolders.DocumentName(document.Path)}...");
        try
        {
            summary = _options.Dump.Run(
                runDirectory,
                message => PostStatus("extracting", message),

                // The hole, fastener, face and mesh phases are most of a dump's cost and no RMS
                // rule reads any of them. The package records that this profile ran, so a thin
                // package is never mistaken for a model with no holes in it (FR-022, RK-19).
                DumpProfile.ModelCheck);
        }
        catch (Exception failure)
        {
            // The folder is left behind on purpose: whatever the dump did write is the evidence
            // for why it stopped (constitution Principle I). It is not registered, because a
            // half-written package must not become the folder Show and the Ask tab read from.
            PostStatus("error", failure.Message);
            actions.SendError(id, "ExtractionFailed", failure.Message, retryable: true);
            return;
        }

        TrackCheck(runDirectory);

        PostStatus(
            "ready",
            (summary.Gaps == 0 ? "Extracted" : $"Extracted with {summary.Gaps} gaps")
                + DumpSummary.UnexaminedClause(summary.Unexamined)
                + ". Checking the model...");

        actions.Send("check.extracted", id, new Dictionary<string, object?>
        {
            { "run_dir", runDirectory },
            { "document", document.Path },
            { "configuration", document.Configuration },
            {
                "counts",
                new Dictionary<string, object?>
                {
                    { "documents", summary.Documents },
                    { "features", summary.Features },
                    { "equations", summary.Equations },
                }
            },
            { "gaps", summary.Gaps },
        });
    }
}
