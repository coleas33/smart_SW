using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using SwReview.AddIn.Review;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel;

/// <summary>Everything <see cref="RemodelHost"/> is given; injected so it is testable headless.</summary>
public sealed class RemodelHostOptions
{
    /// <param name="channel">Where replies and unsolicited messages go.</param>
    /// <param name="runRoot">The run root in force, read fresh: a settings save moves it.</param>
    public RemodelHostOptions(IPageChannel channel, Func<string> runRoot)
    {
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        RunRoot = runRoot ?? throw new ArgumentNullException(nameof(runRoot));
    }

    public IPageChannel Channel { get; }

    public Func<string> RunRoot { get; }

    /// <summary>The backend's endpoint, or null before it is listening.</summary>
    public Func<BackendEndpoint?> Backend { get; set; } = () => null;

    /// <summary>The open document, asked for fresh each time; SOLIDWORKS owns the answer.</summary>
    public Func<PageDocument?> CurrentDocument { get; set; } = () => null;

    /// <summary>
    /// The copy, the dump, the planner and the executor. Null until the add-in is attached to a
    /// SOLIDWORKS session, which is a state the pane really has.
    /// </summary>
    public IRemodelPipeline? Pipeline { get; set; }

    /// <summary>
    /// Whether the attached bridge can execute remodel commands. The add-in reads this from
    /// the tool service; tests and future seat-backed hosts can provide their own capability.
    /// Unknown leaves the bridge unavailable check to the pipeline, while Unavailable is
    /// refused before any bridge call is made.
    /// </summary>
    public Func<RemodelAvailability> RemodelAvailability { get; set; } =
        () => global::SwReview.AddIn.Remodel.RemodelAvailability.Available;

    /// <summary>
    /// Makes the run's folder the pane's latest run, the same way a Model check's folder does
    /// (<see cref="Model.ModelCheckHostOptions.RegisterLatestRun"/>). There is one answer to
    /// "which folder is the pane looking at" and it is not this host's to keep: `entity.show`
    /// resolves ids through the package in that folder and the Ask tab opens in it.
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

    /// <summary>What the executor is bounded by. Reported to the page, never set by it.</summary>
    public RemodelLimits Limits { get; set; } = RemodelLimits.Default;

    /// <summary>
    /// Where phases B to D actually execute.
    ///
    /// Off the message thread by default, and that is not an optimisation: a run can take
    /// twenty minutes, and `remodel.stop` is delivered on the message thread. A run that
    /// occupied that thread would be a run that cannot be stopped. Tests substitute an inline
    /// scheduler so the message order they read is the order the page would see.
    /// </summary>
    public Action<Action> Schedule { get; set; } = work => Task.Run(work);
}

/// <summary>
/// The Remodel page's other half: `ready`, every `remodel.*` row of
/// `specs/004-resilient-remodeler/contracts/pane-remodel-messages.md`, and the four rows every
/// pane host shares, delegated to feature 003's <see cref="PaneActions"/>.
///
/// What it does not do is, again, most of the design:
///
/// <b>It decides nothing about the model.</b> What should move, where it should go, whether a
/// group is contiguous, what cannot be fixed and whether the geometry is unchanged are Python
/// pure functions; what SOLIDWORKS is asked to do is <see cref="IRemodelPipeline"/>. This class
/// owns the order of the messages and the refusals, and that is all it owns.
///
/// <b>It never takes a handle to the source.</b> The source's path leaves this class once, in
/// a <see cref="RemodelCopyRequest"/>, as the source of a filesystem copy. Every other call
/// addresses the run folder. The source is unreachable rather than merely un-targeted, which
/// is the property the constitution's re-modeler exception rests on.
///
/// <b>It does not remember the run's state.</b> `plan.json` carries it, and `remodel.result`
/// and `remodel.start` both read it from there, so a run interrupted by a crash still answers
/// and is still refused a resume (data-model.md section 11).
///
/// <b>It takes no path from the page.</b> `run_dir` is echoed back from a `remodel.planned`
/// this host issued and is resolved against this host's own run record; anything else is
/// `RunNotFound`, before any filesystem call is made with it.
///
/// One run per host, and the page is told so by name: a second `remodel.plan` or
/// `remodel.start` while one is in flight is `error {error_class: "RunInProgress"}`, the same
/// shape `settings.save` already uses for `TurnRunning` (RK-10).
///
/// Threading: <see cref="Receive"/> is not re-entrant and is delivered one message at a time,
/// off the SOLIDWORKS UI thread. The run itself executes on
/// <see cref="RemodelHostOptions.Schedule"/> so that `remodel.stop` can be delivered while it
/// is running; the only state the two share is the run's stop flag and the pending stop id,
/// both written atomically.
/// </summary>
public sealed class RemodelHost : IDisposable
{
    /// <summary>The actionable guidance when this build has no in-process remodel seat.</summary>
    public const string NoSeatMessage =
        "this build has no remodel seat; run swreview-extract probe remodel "
        + "--acknowledge-throwaway-part with no document open.";

    /// <summary>What a forged request reads while the service is still attaching.</summary>
    public const string SeatCheckingMessage =
        "remodel seat availability is still being checked; wait for the tool service to attach.";

    /// <summary>The only scope this feature reorganizes. Parts only, by owner decision.</summary>
    private const string PartKind = "part";

    /// <summary>What `plan.json` says a run that has only been planned is.</summary>
    private const string PlannedState = "planned";

    /// <summary>What `plan.json` says a run whose copy the engineer deleted is.</summary>
    private const string DiscardedState = "discarded";

    /// <summary>The member of `plan.json` that carries the run state: one name for the reader
    /// and the writer of it.</summary>
    private const string StateMember = "state";

    /// <summary>The folder inside a run folder that the copy - and only the copy - lives in.</summary>
    private const string CopyFolderName = RemodelCopy.CopyFolderName;

    private readonly RemodelHostOptions _options;
    private readonly PaneActions _actions;
    private readonly List<RemodelRun> _runs = new List<RemodelRun>();

    /// <summary>A plan or a run is in flight. One per host.</summary>
    private volatile bool _busy;

    /// <summary>The run the executor is inside, so `remodel.stop` has something to set.</summary>
    private volatile RemodelRun? _active;

    /// <summary>The `remodel.stop` that is waiting for the executor to finalize.</summary>
    private string? _pendingStopId;

    public RemodelHost(RemodelHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
        _actions = new PaneActions(new PaneActionsOptions(
            options.Channel,
            options.RunRoot,
            new PaneRunLookup(
                "run_dir",
                "RunNotFound",
                runDir => $"this pane did not start a remodel run in '{runDir}', so it does not "
                    + "know which folder to open.",
                runDir => FindRun(runDir)?.RunDirectory))
        {
            LogFolder = options.LogFolder,
            EntityResolver = options.EntityResolver,
            Opener = options.Opener,
            Secrets = options.Secrets,
        });
    }

    /// <summary>The runs this host planned, oldest first.</summary>
    public IReadOnlyList<RemodelRun> Runs => _runs;

    /// <summary>
    /// Whether a plan or a run is in flight - the same fact `remodel.plan` refuses a second
    /// one on. Read by <see cref="SwReview.AddIn.ToolService.ToolServiceGate.FollowDocument"/>:
    /// every write the run makes goes through the bridge, so restarting the tool service
    /// underneath one would fail it mid-copy.
    /// </summary>
    public bool RunInProgress => _busy;

    /// <summary>The newest run, or null before the first `remodel.plan`.</summary>
    public RemodelRun? LatestRun { get; private set; }

    /// <summary>
    /// The run <paramref name="key"/> names, or null.
    ///
    /// The key is the run folder or the run id, and it is matched against this host's own
    /// records: a page that could name a folder this host never created could ask for anything
    /// on the workstation to be opened.
    /// </summary>
    public RemodelRun? FindRun(string? key)
    {
        string trimmed = (key ?? string.Empty).Trim();
        if (trimmed.Length == 0)
        {
            return null;
        }

        string normalized = trimmed.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        return _runs.FirstOrDefault(run =>
            string.Equals(run.RunDirectory, normalized, StringComparison.OrdinalIgnoreCase)
            || string.Equals(run.RunId, normalized, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>Handles one message from the page. Never throws.</summary>
    public void Receive(string json)
    {
        string? id = null;
        try
        {
            using (JsonDocument document = JsonDocument.Parse(json))
            {
                JsonElement root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object)
                {
                    throw new FormatException("a page message must be a JSON object");
                }

                id = PagePayload.Text(root, "id");
                string? type = PagePayload.Text(root, "type");
                if (string.IsNullOrEmpty(type))
                {
                    throw new FormatException("a page message must carry a 'type'");
                }

                JsonElement payload = root.TryGetProperty("payload", out JsonElement value)
                    ? value
                    : default;
                Dispatch(type!, id, payload);
            }
        }
        catch (RemodelRefusal refusal)
        {
            // Before the catch below, and that order is the whole point: the pipeline's members
            // return readings rather than error objects, so a refusal the backend or the bridge
            // named travels out of them as an exception with its class attached. Answered as
            // `HostError` it would read to the engineer as a bug in the pane rather than as the
            // condition of the part it is (`contracts/pane-remodel-messages.md`, refusal classes).
            SendRefusal(id, refusal);
        }
        catch (Exception failure)
        {
            // An exception escaping into the `WebMessageReceived` handler would surface inside
            // SOLIDWORKS.
            _actions.SendError(id, "HostError", failure.Message, retryable: false);
        }
    }

    /// <summary>Sends an unsolicited message (`status`, `document.changed`, `backend.stopped`).</summary>
    public void Post(string type, object? payload) => _actions.Send(type, null, payload);

    /// <summary>Posts one `status`, with every secret masked out of it (FR-015).</summary>
    public void PostStatus(string stage, string message) => _actions.PostStatus(stage, message);

    /// <summary>
    /// The `status` stages this page has a branch for, closed by
    /// `contracts/pane-remodel-messages.md`.
    ///
    /// On the Review and Model check tabs `status` reports the backend's lifecycle; here it is
    /// the run's own phase strip, which is why the remodel contract's row does not carry
    /// `backend_starting` where feature 002's `pane-host-messages.md` and feature 003's
    /// `model-check.md` do. `SwReviewAddIn.PostStatusToPages` fans one backend-lifecycle
    /// `status` out to all three pages and filters this page's share through
    /// <see cref="IsStatusStage"/>, so a stage the page cannot show is never posted to it.
    /// `ready` and `error` are on both lists and do arrive - which is what lets a Remodel tab
    /// opened while the backend was still starting ask for its `init` again.
    /// </summary>
    public static IReadOnlyCollection<string> StatusStages => Stages;

    /// <summary>Whether <paramref name="stage"/> is on <see cref="StatusStages"/>.</summary>
    public static bool IsStatusStage(string stage) => stage != null && Stages.Contains(stage);

    private static readonly HashSet<string> Stages = new HashSet<string>(
        new[]
        {
            "copying",
            "dumping",
            "planning",
            "judging",
            "applying",
            "verifying",
            "saving",
            "backend_starting",
            "ready",
            "error",
        },
        StringComparer.Ordinal);

    /// <summary>
    /// Tells the page which document the pane is looking at now - and aborts a run whose copy
    /// has gone away.
    ///
    /// RK-14: the engineer closes or deletes the copy mid-run. The stop flag is set, so the
    /// executor finishes the change in flight, inverts it if it failed and finalizes, leaving
    /// the change log intact. A `document.changed` that names the copy itself is the ordinary
    /// case - `remodel.open_copy` causes one - and changes nothing.
    /// </summary>
    public void DocumentChanged()
    {
        Post("document.changed", DocumentPayload(_options.CurrentDocument()));

        RemodelRun? run = _active;
        if (run == null || run.StopRequested || CopyExists(run))
        {
            return;
        }

        run.RequestStop();
        PostStatus(
            "error",
            $"the copy '{run.CopyPath}' is no longer there, so the run is stopping. The change "
            + "log in the run folder is intact.");
    }

    /// <summary>
    /// Refreshes the page's capability banner when the tool service finishes attaching or
    /// detaches. It uses the existing document message so no new page protocol row is needed.
    /// </summary>
    public void RefreshAvailability() =>
        Post("document.changed", DocumentPayloadWithCapability(_options.CurrentDocument()));

    public void Dispose()
    {
        _runs.Clear();
        LatestRun = null;
        _active = null;
    }

    private void Dispatch(string type, string? id, JsonElement payload)
    {
        // The four rows this host shares with every other pane host, answered by the one copy
        // of them.
        if (_actions.TryHandle(type, id, payload))
        {
            return;
        }

        switch (type)
        {
            case "ready":
                SendInit(id);
                return;

            case "remodel.plan":
                Plan(id);
                return;

            case "remodel.start":
                Start(id, payload);
                return;

            case "remodel.stop":
                Stop(id);
                return;

            case "remodel.result":
                SendResult(id, payload);
                return;

            case "remodel.open_copy":
                OpenCopy(id, payload);
                return;

            case "remodel.discard_copy":
                DiscardCopy(id, payload);
                return;

            case "remodel.show_change":
                ShowChange(id, payload);
                return;

            default:
                _actions.SendError(
                    id,
                    "UnknownMessage",
                    $"the host does not handle a '{type}' message",
                    retryable: false);
                return;
        }
    }

    // ---- ready / init -------------------------------------------------------------------

    private void SendInit(string? id)
    {
        BackendEndpoint? endpoint = _options.Backend();
        RemodelRun? latest = LatestRun;
        RemodelLimits limits = _options.Limits;

        _actions.Send("init", id, new Dictionary<string, object?>
        {
            {
                "backend",
                endpoint == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "port", endpoint.Port },

                        // The page's OWN origin under `/__backend`, as `ReviewHost` and
                        // `ModelCheckHost` send: one field, one meaning in all three
                        // contracts. This page does not fetch today - its backend work is
                        // host-side - but handing it the loopback origin would be a trap,
                        // because the page's CSP is `connect-src 'self'`, so the first fetch
                        // built from it would be refused by the renderer
                        // (docs/pane-backend-proxy.md). The port stays because the pane still
                        // shows it and a diagnostic still needs it.
                        { "origin", BackendProxy.PageOrigin },
                    }
            },
            { "token", endpoint?.Token },
            { "run_root", _options.RunRoot() },
            { "document", DocumentPayload(_options.CurrentDocument()) },
            {
                "limits",
                new Dictionary<string, object?>
                {
                    { "max_changes", limits.MaxChanges },
                    { "max_minutes", limits.MaxMinutes },
                    { "max_rebuild_seconds", limits.MaxRebuildSeconds },
                }
            },
            {
                "remodel",
                RemodelCapabilityPayload()
            },
            {
                "latest_run",
                latest == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "run_dir", latest.RunDirectory },
                        { "at", latest.At.ToString("o", CultureInfo.InvariantCulture) },
                        { "state", StateOf(latest.RunDirectory) },
                    }
            },
        });
    }

    private Dictionary<string, object?> RemodelCapabilityPayload()
    {
        RemodelAvailability availability = _options.RemodelAvailability();
        return new Dictionary<string, object?>
        {
            { "available", availability == RemodelAvailability.Unknown
                ? null
                : (object)(availability == RemodelAvailability.Available) },
            { "message", availability == RemodelAvailability.Unavailable
                ? NoSeatMessage
                : availability == RemodelAvailability.Unknown
                    ? SeatCheckingMessage
                    : null },
        };
    }

    private Dictionary<string, object?>? DocumentPayloadWithCapability(PageDocument? document)
    {
        var payload = DocumentPayload(document);
        if (payload == null)
        {
            return null;
        }

        payload["remodel"] = RemodelCapabilityPayload();
        return payload;
    }

    // ---- remodel.plan -------------------------------------------------------------------

    /// <summary>
    /// Press Remodel: refuse everything that can be refused <b>before anything is copied</b>,
    /// then create the run folder, copy, open, tag, roll and rebuild the copy, dump it and run
    /// the pure planner.
    ///
    /// The order is the contract's and is not negotiable. Every refusal but one lands before a
    /// copy exists; the exception is `PreexistingRebuildErrors`, whose reading needs a rollback
    /// and a rebuild and so can only be taken on the copy - and whose handler is therefore the
    /// one that deletes a copy.
    /// </summary>
    private void Plan(string? id)
    {
        if (_busy)
        {
            SendRunInProgress(id);
            return;
        }

        PageDocument? document = _options.CurrentDocument();
        if (document == null)
        {
            _actions.SendError(
                id,
                "NoDocument",
                "open the part you want reorganized in SOLIDWORKS first: the re-modeler copies "
                + "the active document.",
                retryable: true);
            return;
        }

        RemodelAvailability availability = _options.RemodelAvailability();
        if (availability != RemodelAvailability.Available)
        {
            SendUnavailable(id, availability);
            return;
        }

        IRemodelPipeline? pipeline = _options.Pipeline;
        if (pipeline == null)
        {
            _actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so nothing can be copied "
                + "or reorganized.",
                retryable: true);
            return;
        }

        if (!string.Equals(document.Kind, PartKind, StringComparison.Ordinal))
        {
            _actions.SendError(
                id,
                "NotAPart",
                "the re-modeler reorganizes a part's feature tree, and the active document is "
                + (document.Kind == null ? "not a SOLIDWORKS part" : "a " + document.Kind)
                + ". Open the part on its own and press Remodel again.",
                retryable: true);
            return;
        }

        _busy = true;
        try
        {
            RemodelScopeReading scope;
            try
            {
                scope = pipeline.ProbeScope();
            }
            catch (Exception failure)
            {
                PostStatus("error", failure.Message);
                throw;
            }

            if (!ScopeAllowsARun(id, scope))
            {
                return;
            }

            string runDirectory;
            try
            {
                runDirectory = RunFolders.CreateForRemodel(
                    _options.RunRoot(), document.Path, _options.Now());
            }
            catch (Exception failure)
            {
                PostStatus("error", failure.Message);
                _actions.SendError(
                    id,
                    "RunFolderFailed",
                    $"the run folder could not be created under '{_options.RunRoot()}': "
                    + failure.Message,
                    retryable: false);
                return;
            }

            var reporter = new RunReporter(this, null);
            PostStatus(
                "copying",
                $"Copying {RunFolders.DocumentName(document.Path)} into the run folder...");

            RemodelCopyReading copy;
            try
            {
                copy = pipeline.OpenCopy(
                    new RemodelCopyRequest(runDirectory, document.Path, document.Configuration),
                    reporter);
            }
            catch (Exception failure)
            {
                // The run folder is left behind on purpose: whatever it holds is the evidence
                // for why the run stopped (constitution Principle I).
                PostStatus("error", failure.Message);
                throw;
            }

            if (copy.RebuildErrorCount == null)
            {
                // Unknown is not zero. A part whose rebuild-error count could not be read is a
                // part whose baseline cannot be established, and every change after it would be
                // unattributable.
                //
                // Reported as `PreexistingRebuildErrors` rather than `ScopeRefused`, because
                // the contract makes that class the only refusal raised after the copy exists
                // and the only one whose handler deletes a copy; `ScopeRefused` is a pre-copy
                // verdict on the source. The message says the count could not be read rather
                // than that errors exist: those are different facts about the part.
                DeleteCopyFolder(pipeline, runDirectory);
                _actions.SendError(
                    id,
                    "PreexistingRebuildErrors",
                    "the rebuild-error count could not be read on the copy, so the run has no "
                    + "baseline to attribute changes against. The copy has been deleted; the "
                    + "run folder is kept.",
                    retryable: true);
                return;
            }

            if (copy.RebuildErrorCount > 0)
            {
                DeleteCopyFolder(pipeline, runDirectory);
                _actions.SendError(
                    id,
                    "PreexistingRebuildErrors",
                    $"the part already has {copy.RebuildErrorCount} rebuild "
                    + (copy.RebuildErrorCount == 1 ? "error" : "errors")
                    + ", so nothing this run did could be attributed to it. Fix the part first. "
                    + "The copy has been deleted; the run folder is kept.",
                    retryable: true);
                return;
            }

            if (!copy.CopyPresent)
            {
                // The copy is gone and the count that came back with it is 0, so the count
                // alone would let this run through - and everything after this line addresses
                // "the copy", starting with a dump that attaches to whatever document
                // SOLIDWORKS still has active. That document is the engineer's source.
                //
                // The class is the same one, because this is the same refusal: the bridge
                // raised `preexisting_rebuild_errors` and deleted the copy before it answered.
                // The message says what is known and not what the count would have implied.
                DeleteCopyFolder(pipeline, runDirectory);
                _actions.SendError(
                    id,
                    "PreexistingRebuildErrors",
                    "the copy was refused for pre-existing rebuild errors and has already been "
                    + "deleted, so there is nothing left to plan against. The count that came "
                    + "back with the refusal was 0, which does not say how many errors were "
                    + "found. Check the part in SOLIDWORKS; the run folder is kept.",
                    retryable: true);
                return;
            }

            PostStatus("planning", "Planning the reorganization...");
            string planSummary;
            try
            {
                planSummary = pipeline.Plan(runDirectory, reporter);
            }
            catch (Exception failure)
            {
                PostStatus("error", failure.Message);
                throw;
            }

            RemodelRun run = Track(runDirectory, copy.CopyPath);
            PostStatus("ready", "Planned. Press Start to apply the plan to the copy.");

            using (JsonDocument summary = JsonDocument.Parse(planSummary))
            {
                _actions.Send("remodel.planned", id, new Dictionary<string, object?>
                {
                    { "run_dir", run.RunDirectory },
                    { "plan_summary", summary.RootElement },
                });
            }
        }
        finally
        {
            _busy = false;
        }
    }

    /// <summary>
    /// The scope half of the refusals, in the contract's order: the three the bridge raises
    /// before any signal comes back, then the pure gate's verdict, then any signal that could
    /// not be read at all.
    ///
    /// A null signal is <b>not</b> a pass (data-model.md section 4.1). Every failing reason is
    /// named in the one message, because a refusal that named one of two sends the engineer
    /// back twice.
    /// </summary>
    private bool ScopeAllowsARun(string? id, RemodelScopeReading scope)
    {
        ScopeSignals signals = scope.Signals;

        if (signals.SaveFlagDirty == true)
        {
            _actions.SendError(
                id,
                "DocumentDirty",
                "the part has unsaved changes. This feature never saves your file, so save it "
                + "or close it yourself, then press Remodel again.",
                retryable: true);
            return false;
        }

        if (signals.ReadOnly == true)
        {
            _actions.SendError(
                id,
                "DocumentReadOnly",
                "the part is open read-only, so its state cannot be attested before the copy is "
                + "made.",
                retryable: true);
            return false;
        }

        if (signals.ExternalReferenceCount > 0)
        {
            _actions.SendError(
                id,
                "ExternalReferences",
                $"the part carries {signals.ExternalReferenceCount} external file "
                + (signals.ExternalReferenceCount == 1 ? "reference" : "references")
                + ", which a copy cannot carry with it.",
                retryable: false);
            return false;
        }

        var refusals = new List<string>(scope.Refusals);

        // Every unreadable signal the host itself reads is reported as `signal_unresolved`,
        // spelled the way `bridge/remodel_client.py` spells it, because a token that differs by
        // an underscore is a refusal that maps to no class on the Python side.
        if (signals.SaveFlagDirty == null)
        {
            refusals.Add("signal_unresolved: save_flag_dirty could not be read");
        }

        if (signals.ReadOnly == null)
        {
            refusals.Add("signal_unresolved: read_only could not be read");
        }

        if (signals.ExternalReferenceCount == null)
        {
            refusals.Add("signal_unresolved: external_reference_count could not be read");
        }

        if (refusals.Count == 0)
        {
            return true;
        }

        _actions.SendError(
            id,
            "ScopeRefused",
            "the re-modeler will not run on this part: " + string.Join("; ", refusals) + ".",
            retryable: false);
        return false;
    }

    // ---- remodel.start / remodel.stop ----------------------------------------------------

    private void Start(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id, PagePayload.Text(payload, "run_dir"));
            return;
        }

        if (_busy)
        {
            SendRunInProgress(id);
            return;
        }

        if (run.CopyDiscarded || !CopyExists(run))
        {
            _actions.SendError(
                id,
                "CopyDiscarded",
                "this run's copy has been discarded, so there is nothing left to reorganize. "
                + "The plan, the change list and the report are still in the run folder.",
                retryable: false);
            return;
        }

        // The state comes off the disk, not out of this host's memory: a run interrupted
        // mid-apply left `applying` in `plan.json`, and the tree it left behind was never
        // re-verified. Replaying changes onto it is exactly the wrong risk.
        string? state = StateOf(run.RunDirectory);
        if (!string.Equals(state, PlannedState, StringComparison.Ordinal))
        {
            _actions.SendError(
                id,
                "ResumeRefused",
                $"this run is '{state ?? "unreadable"}' rather than 'planned', and a run is "
                + "never resumed: the copy it left behind was not re-verified. Press Remodel "
                + "again to start a fresh run.",
                retryable: false);
            return;
        }

        RemodelAvailability availability = _options.RemodelAvailability();
        if (availability != RemodelAvailability.Available)
        {
            SendUnavailable(id, availability);
            return;
        }

        IRemodelPipeline? pipeline = _options.Pipeline;
        if (pipeline == null)
        {
            _actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so the plan cannot be "
                + "applied.",
                retryable: true);
            return;
        }

        _busy = true;
        run.Phase = RemodelRunPhase.Running;
        _active = run;

        // The reply goes first, so the page has the chat id before the first `status` or
        // `remodel.change` arrives on it.
        _actions.Send("remodel.started", id, new Dictionary<string, object?>
        {
            { "chat_id", run.RunId },
        });

        _options.Schedule(() => Execute(pipeline, run));
    }

    /// <summary>
    /// Phases B to D, to completion, off the message thread.
    ///
    /// Never throws into the scheduler: a faulted background task in a SOLIDWORKS add-in is an
    /// unobserved exception nobody sees. A failure is a `status {stage: "error"}` and an
    /// `error` message, and the run ends `failed`.
    /// </summary>
    private void Execute(IRemodelPipeline pipeline, RemodelRun run)
    {
        RemodelRunOutcome outcome;
        try
        {
            PostStatus("judging", "Running the plan against the copy...");
            outcome = pipeline.Run(run.RunDirectory, new RunReporter(this, run));
        }
        catch (RemodelRefusal refusal)
        {
            // Unsolicited: `remodel.started` was answered before the run began, so there is no
            // message left to reply to. The class still travels, for the reason it does on the
            // message thread.
            PostStatus("error", refusal.Message);
            SendRefusal(null, refusal);
            outcome = new RemodelRunOutcome("failed", 0);
        }
        catch (Exception failure)
        {
            PostStatus("error", failure.Message);
            _actions.SendError(null, "HostError", failure.Message, retryable: false);
            outcome = new RemodelRunOutcome("failed", 0);
        }
        finally
        {
            run.Phase = RemodelRunPhase.Finished;
            _active = null;
            _busy = false;
        }

        if (outcome.State == "failed")
        {
            PostStatus("error", "The run ended without saving the copy. The report says why.");
        }
        else
        {
            PostStatus(
                "ready",
                $"The run ended '{outcome.State}'. Open the report for the change list, the "
                + "grade and the geometry comparison.");
        }

        // The stop is answered when the executor has finalized, not when the flag was set:
        // `changes_applied` is not knowable until the change in flight has landed or been
        // inverted.
        string? stopId = Interlocked.Exchange(ref _pendingStopId, null);
        if (stopId != null || run.StopRequested)
        {
            _actions.Send("remodel.stopped", stopId, new Dictionary<string, object?>
            {
                { "changes_applied", outcome.ChangesApplied },
            });
        }
    }

    private void Stop(string? id)
    {
        RemodelRun? run = _active;
        if (run == null)
        {
            _actions.SendError(
                id,
                "RunNotFound",
                "no remodel run is in flight, so there is nothing to stop.",
                retryable: false);
            return;
        }

        Interlocked.Exchange(ref _pendingStopId, id);
        run.RequestStop();
        PostStatus(
            "applying",
            "Stopping: the change in flight is finished and the artifacts are finalized first.");
    }

    // ---- remodel.result ------------------------------------------------------------------

    /// <summary>
    /// Read from the run folder and not from memory, so the tab answers after a restart - and
    /// so the numbers on screen are the numbers in the files the engineer can open beside them.
    ///
    /// Anything that has not been written yet is <b>null</b>, never a zero: a `grade_after`
    /// with no failures would read as a part that passed.
    /// </summary>
    private void SendResult(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id, PagePayload.Text(payload, "run_dir"));
            return;
        }

        var open = new List<JsonDocument>();
        try
        {
            JsonDocument? plan = Load(open, run.RunDirectory, "plan.json");
            JsonDocument? grades = Load(open, run.RunDirectory, "grades.json");
            JsonDocument? geometry = Load(open, run.RunDirectory, "geometry.json");
            JsonDocument? attestation = Load(open, run.RunDirectory, "source-attestation.json");

            _actions.Send("remodel.result", id, new Dictionary<string, object?>
            {
                { "changes", ReadChanges(open, run.RunDirectory) },
                { "grade_before", Member(grades, "before") },
                { "grade_after", Member(grades, "after") },
                { "geometry", geometry?.RootElement },
                { "rebuild_list", Member(plan, "rebuild") ?? (object?)new object[0] },
                { "attestation", attestation?.RootElement },
                { "state", Text(plan, StateMember) },
            });
        }
        finally
        {
            foreach (JsonDocument document in open)
            {
                document.Dispose();
            }
        }
    }

    // ---- remodel.open_copy / remodel.discard_copy ----------------------------------------

    private void OpenCopy(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id, PagePayload.Text(payload, "run_dir"));
            return;
        }

        if (run.CopyDiscarded || !CopyExists(run))
        {
            _actions.SendError(
                id,
                "CopyDiscarded",
                "this run's copy has been discarded. The plan, the change list and the report "
                + "are still in the run folder.",
                retryable: false);
            return;
        }

        IRemodelPipeline? pipeline = _options.Pipeline;
        if (pipeline == null)
        {
            _actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so the copy cannot be "
                + "opened.",
                retryable: true);
            return;
        }

        try
        {
            pipeline.ActivateCopy(run.RunDirectory);
        }
        catch (RemodelRefusal refusal)
        {
            // A seat that refused by name keeps that name. `OpenFailed` is for the SOLIDWORKS
            // that would not open the file, which is a different thing to tell the engineer.
            SendRefusal(id, refusal);
            return;
        }
        catch (Exception failure)
        {
            _actions.SendError(id, "OpenFailed", failure.Message, retryable: true);
            return;
        }

        _actions.Send("ok", id, new Dictionary<string, object?>());
    }

    /// <summary>
    /// Delete the copy and <b>keep every other artifact</b>, so "what did it propose?" stays
    /// answerable after the engineer says no.
    /// </summary>
    private void DiscardCopy(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id, PagePayload.Text(payload, "run_dir"));
            return;
        }

        if (_busy && ReferenceEquals(_active, run))
        {
            SendRunInProgress(id);
            return;
        }

        IRemodelPipeline? pipeline = _options.Pipeline;
        try
        {
            DeleteCopyFolder(pipeline, run.RunDirectory);
        }
        catch (Exception failure)
        {
            _actions.SendError(id, "DiscardFailed", failure.Message, retryable: true);
            return;
        }

        run.CopyDiscarded = true;

        // `discarded` is a state transition like any other, and data-model.md section 11 has
        // `RunState` "rewritten to plan.json at every transition". It is written here because
        // this is the one transition no other component can make - the executor has finished by
        // the time the engineer presses Discard - and because `remodel.result` and
        // `init.latest_run` both read `state` straight out of `plan.json`. A host that only set
        // a field in memory would keep reporting `saved` for a run whose copy it had just
        // deleted.
        try
        {
            WritePlanState(run.RunDirectory, DiscardedState);
        }
        catch (Exception failure)
        {
            _actions.SendError(
                id,
                "DiscardFailed",
                "the copy was deleted, but 'discarded' could not be written to plan.json, so "
                + "this tab would go on reporting the state the run ended in: " + failure.Message,
                retryable: false);
            return;
        }

        _actions.Send("ok", id, new Dictionary<string, object?>
        {
            { "kept", Kept(run.RunDirectory) },
        });
    }

    /// <summary>
    /// Rewrites `plan.json`'s `state` member and leaves every other member exactly as it was
    /// read, member for member and value for value: the rest of that file is the plan, and the
    /// plan is what "what did it propose?" is answered out of after the copy is gone.
    ///
    /// A run folder with no `plan.json` is left alone. There is no state on disk to go stale,
    /// and inventing a `plan.json` here would be this host writing a plan it did not plan.
    /// </summary>
    private static void WritePlanState(string runDirectory, string state)
    {
        string path = Path.Combine(runDirectory, "plan.json");
        if (!File.Exists(path))
        {
            return;
        }

        byte[] rewritten;
        using (JsonDocument plan = JsonDocument.Parse(File.ReadAllBytes(path)))
        {
            if (plan.RootElement.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException(
                    $"'{path}' is not a JSON object, so its state cannot be rewritten.");
            }

            using (var buffer = new MemoryStream())
            {
                using (var writer = new Utf8JsonWriter(
                    buffer, new JsonWriterOptions { Indented = true }))
                {
                    writer.WriteStartObject();
                    bool replaced = false;
                    foreach (JsonProperty member in plan.RootElement.EnumerateObject())
                    {
                        if (member.NameEquals(StateMember))
                        {
                            writer.WriteString(StateMember, state);
                            replaced = true;
                        }
                        else
                        {
                            member.WriteTo(writer);
                        }
                    }

                    if (!replaced)
                    {
                        writer.WriteString(StateMember, state);
                    }

                    writer.WriteEndObject();
                }

                rewritten = buffer.ToArray();
            }
        }

        File.WriteAllBytes(path, rewritten);
    }

    // ---- remodel.show_change -------------------------------------------------------------

    /// <summary>
    /// Show one change in SOLIDWORKS, through the persistent reference `changes.jsonl` recorded
    /// for it and through feature 003's resolver and <see cref="FeatureSelection"/>, so one
    /// resolver serves three tabs and the reply is the identical `entity.shown` payload
    /// `entity.show` already returns.
    ///
    /// A change that cannot be shown is answered, never thrown and never silently ignored: a
    /// Show that selected nothing and reported success is the behaviour FR-027 exists to
    /// prevent.
    /// </summary>
    private void ShowChange(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id, PagePayload.Text(payload, "run_dir"));
            return;
        }

        if (payload.ValueKind != JsonValueKind.Object
            || !payload.TryGetProperty("change_seq", out JsonElement value)
            || value.ValueKind != JsonValueKind.Number
            || !value.TryGetInt32(out int seq))
        {
            _actions.SendError(
                id,
                "InvalidRequest",
                "remodel.show_change needs the change's change_seq.",
                retryable: false);
            return;
        }

        var open = new List<JsonDocument>();
        try
        {
            // The last line wins: `changes.jsonl` is append-only and a change is written once
            // as `attempting` and again with its terminal status.
            JsonElement? record = ReadChanges(open, run.RunDirectory)
                .Where(change => change.TryGetProperty("seq", out JsonElement number)
                    && number.ValueKind == JsonValueKind.Number
                    && number.TryGetInt32(out int candidate)
                    && candidate == seq)
                .Select(change => (JsonElement?)change)
                .LastOrDefault();

            if (record == null)
            {
                _actions.SendEntityShown(
                    id,
                    EntityShowOutcome.NotShown(
                        -1,
                        $"change {seq} is not in this run's change list, so there is nothing to "
                        + "select.",
                        null));
                return;
            }

            string? persistRef = null;
            if (record.Value.TryGetProperty("subject", out JsonElement subject))
            {
                persistRef = PagePayload.Blank(PagePayload.Text(subject, "persist_ref"));
            }

            if (persistRef == null)
            {
                _actions.SendEntityShown(
                    id,
                    EntityShowOutcome.NotShown(
                        -1,
                        $"change {seq} recorded no persistent reference for its subject, so it "
                        + "cannot be selected. Find it in the feature tree by name.",
                        null));
                return;
            }

            // No scope and no component: the copy is a part opened on its own, so the reference
            // belongs to the document on screen and the host invents neither.
            _actions.ShowPersistRef(id, new EntityShowRequest(persistRef, null, null));
        }
        finally
        {
            foreach (JsonDocument document in open)
            {
                document.Dispose();
            }
        }
    }

    // ---- the run record and the run folder -----------------------------------------------

    /// <summary>
    /// Records the run and makes its folder the pane's latest run.
    ///
    /// Here and nowhere else, because this is the one moment a remodel folder comes into
    /// existence as something the pane is looking at: a refused plan records no run and must
    /// leave the pane pointed wherever it already was.
    /// </summary>
    private RemodelRun Track(string runDirectory, string copyPath)
    {
        var run = new RemodelRun(runDirectory, copyPath, _options.Now());
        _runs.Add(run);
        LatestRun = run;
        _options.RegisterLatestRun(runDirectory);
        return run;
    }

    /// <summary>
    /// Closes the copy without saving and deletes `copy/` and nothing else.
    ///
    /// One method for both callers - the `PreexistingRebuildErrors` refusal and
    /// `remodel.discard_copy` - because they are the same operation and a second copy of it
    /// would be a second chance to delete the wrong folder.
    ///
    /// A copy that is already gone is the ordinary case rather than a failure: the bridge's own
    /// `preexisting_rebuild_errors` handler deletes the copy and closes the document before it
    /// refuses (`contracts/bridge-remodel.md`), which reaches the host as `copy_present: false`.
    /// The close is still attempted - the host does not know which half the bridge managed -
    /// and a folder that is not there is left alone.
    /// </summary>
    private static void DeleteCopyFolder(IRemodelPipeline? pipeline, string runDirectory)
    {
        if (pipeline != null)
        {
            try
            {
                pipeline.CloseCopy(runDirectory);
            }
            catch (Exception)
            {
                // A copy that is not open, or a SOLIDWORKS that will not answer, must not stop
                // the folder being deleted: the file is what the engineer asked to be rid of.
            }
        }

        string folder = Path.Combine(runDirectory, CopyFolderName);
        if (Directory.Exists(folder))
        {
            Directory.Delete(folder, recursive: true);
        }
    }

    /// <summary>What is left in the run folder after a discard, as the reply lists it.</summary>
    private static string[] Kept(string runDirectory)
    {
        try
        {
            return Directory.GetFileSystemEntries(runDirectory)
                .Select(Path.GetFileName)
                .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
                .ToArray();
        }
        catch (Exception)
        {
            return new string[0];
        }
    }

    private bool CopyExists(RemodelRun run)
    {
        try
        {
            return File.Exists(run.CopyPath);
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>
    /// The run's state, read out of `plan.json`, or null when there is no readable answer.
    ///
    /// One reader for `init.latest_run.state`, `remodel.result.state` and the resume refusal,
    /// because three readings of the same field could disagree about a run.
    /// </summary>
    private static string? StateOf(string runDirectory)
    {
        var open = new List<JsonDocument>();
        try
        {
            return Text(Load(open, runDirectory, "plan.json"), StateMember);
        }
        finally
        {
            foreach (JsonDocument document in open)
            {
                document.Dispose();
            }
        }
    }

    /// <summary>
    /// Every `ChangeRecord` in `changes.jsonl`, in file order. A line that is not JSON is
    /// skipped rather than sent to the page as text: the page reads a record, and half a line
    /// is what a crash mid-write leaves behind.
    /// </summary>
    private static List<JsonElement> ReadChanges(List<JsonDocument> open, string runDirectory)
    {
        var changes = new List<JsonElement>();
        string path = Path.Combine(runDirectory, "changes.jsonl");
        if (!File.Exists(path))
        {
            return changes;
        }

        string[] lines;
        try
        {
            lines = File.ReadAllLines(path);
        }
        catch (Exception)
        {
            return changes;
        }

        foreach (string line in lines)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            try
            {
                JsonDocument document = JsonDocument.Parse(line);
                open.Add(document);
                changes.Add(document.RootElement);
            }
            catch (JsonException)
            {
            }
        }

        return changes;
    }

    /// <summary>One artifact, parsed, or null when it is absent or unreadable.</summary>
    private static JsonDocument? Load(List<JsonDocument> open, string runDirectory, string name)
    {
        string path;
        try
        {
            path = Path.Combine(runDirectory, name);
        }
        catch (ArgumentException)
        {
            return null;
        }

        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
            open.Add(document);
            return document;
        }
        catch (Exception)
        {
            // A half-written artifact is unknown, not empty. The page renders an absent value
            // as absent.
            return null;
        }
    }

    private static object? Member(JsonDocument? document, string name) =>
        document != null
        && document.RootElement.ValueKind == JsonValueKind.Object
        && document.RootElement.TryGetProperty(name, out JsonElement value)
            ? (object?)value
            : null;

    private static string? Text(JsonDocument? document, string name) =>
        document == null ? null : PagePayload.Text(document.RootElement, name);

    // ---- the refusals two handlers share --------------------------------------------------

    /// <summary>
    /// One `error {error_class, message}` carrying the class whoever refused chose - the
    /// backend's reply body, or the pipeline's own pre-call refusal. One copy of it, because
    /// three handlers answer the same exception and three spellings of "pass the class through"
    /// is three chances to drop it.
    /// </summary>
    private void SendRefusal(string? id, RemodelRefusal refusal) =>
        _actions.SendError(id, refusal.ErrorClass, refusal.Message, refusal.Retryable);

    private void SendRunInProgress(string? id) =>
        _actions.SendError(
            id,
            "RunInProgress",
            "a remodel run is already in flight in this pane. One run at a time: two runs would "
            + "share one SOLIDWORKS session and neither could be attributed.",
            retryable: true);

    private void SendRunNotFound(string? id, string? runDir) =>
        _actions.SendError(
            id,
            "RunNotFound",
            $"this pane did not start a remodel run in '{runDir}', so it will not act on it.",
            retryable: false);

    private void SendUnavailable(string? id, RemodelAvailability availability) =>
        _actions.SendError(
            id,
            "RemodelUnavailable",
            availability == RemodelAvailability.Unknown ? SeatCheckingMessage : NoSeatMessage,
            retryable: availability == RemodelAvailability.Unknown);

    private static Dictionary<string, object?>? DocumentPayload(PageDocument? document) =>
        document == null
            ? null
            : new Dictionary<string, object?>
            {
                { "path", document.Path },
                { "configuration", document.Configuration },
                { "kind", document.Kind },
            };

    /// <summary>
    /// The executor's one way to reach the page: the three unsolicited message types the
    /// contract defines and the stop flag, and nothing else.
    /// </summary>
    private sealed class RunReporter : IRemodelRunReporter
    {
        private readonly RemodelHost _host;
        private readonly RemodelRun? _run;

        public RunReporter(RemodelHost host, RemodelRun? run)
        {
            _host = host;
            _run = run;
        }

        /// <summary>
        /// False during the plan phase, which has no run to stop: `remodel.stop` is refused
        /// before a run exists, so there is no flag to read.
        /// </summary>
        public bool StopRequested => _run != null && _run.StopRequested;

        public void Status(string stage, string message) => _host.PostStatus(stage, message);

        public void Progress(int applied, int total, int seq, string kind, string? subjectName) =>
            _host._actions.Send("remodel.progress", null, new Dictionary<string, object?>
            {
                { "applied", applied },
                { "total", total },
                {
                    "current",
                    new Dictionary<string, object?>
                    {
                        { "seq", seq },
                        { "kind", kind },
                        { "subject_name", subjectName },
                    }
                },
            });

        public void Change(string changeRecordJson)
        {
            try
            {
                using (JsonDocument record = JsonDocument.Parse(changeRecordJson))
                {
                    _host._actions.Send("remodel.change", null, record.RootElement);
                }
            }
            catch (JsonException)
            {
                // Half a line is what a crash mid-write leaves behind. The file is the record;
                // the page's live list is a convenience and must not carry a fragment.
            }
        }
    }
}
