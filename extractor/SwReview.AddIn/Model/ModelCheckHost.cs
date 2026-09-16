using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;

namespace SwReview.AddIn.Model;

/// <summary>
/// One Model check this host ran: enough to answer `report.open` and `folder.open` without
/// ever taking a path from the page.
///
/// <see cref="CheckId"/> is the run folder's own name, which is also how the backend addresses
/// a check (`GET /checks/{check_id}`). One id, so a page holding a check's result can ask this
/// host to open the folder it came from without a second identifier to keep in step.
/// </summary>
public sealed class CheckRecord
{
    internal CheckRecord(string checkId, string runDirectory, DateTime at)
    {
        CheckId = checkId ?? throw new ArgumentNullException(nameof(checkId));
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        At = at;
    }

    /// <summary>The run folder's name, `&lt;yyyyMMdd-HHmmss&gt;-&lt;doc&gt;-check`.</summary>
    public string CheckId { get; }

    public string RunDirectory { get; }

    /// <summary>When the check was started, as `init.latest_check.at` carries it.</summary>
    public DateTime At { get; }
}

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
/// <b>It does not own "the pane's latest run".</b> It creates the check folder and hands it to
/// <see cref="ModelCheckHostOptions.RegisterLatestRun"/>, so `entity.show` resolves
/// `document_id` through the package that was just written and the Ask tab opens in the same
/// place (FR-028).
///
/// What it does own is the order of one `check.start`, and it is not negotiable. The refusals
/// come first because a dump is SOLIDWORKS time. The run folder is created before the dump
/// because the dump writes into it. The folder is registered before the reply, so a
/// `POST /checks/rms` the page sends the instant it sees `check.extracted` resolves ids
/// through the right folder.
///
/// No abstract base class shared with <see cref="ReviewHost"/>: inheritance would drag settings
/// and backend state into a host that has neither (plan.md, Structure decision). The four
/// common rows are composed in instead, and their tests are parameterized over both hosts.
///
/// Threading: <see cref="Receive"/> is not re-entrant, and must not run on the SOLIDWORKS UI
/// thread - a dump occupies the application thread for as long as it takes. The caller
/// delivers page messages one at a time, as it already does for the Review page.
/// </summary>
public sealed class ModelCheckHost : IDisposable
{
    /// <summary>The only scope this increment evaluates (`contracts/model-check.md`).</summary>
    private const string PartKind = "part";

    private readonly ModelCheckHostOptions _options;
    private readonly PaneActions _actions;
    private readonly List<CheckRecord> _checks = new List<CheckRecord>();

    public ModelCheckHost(ModelCheckHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
        _actions = new PaneActions(new PaneActionsOptions(
            options.Channel,
            options.RunRoot,
            new PaneRunLookup(
                "run_id",
                "UnknownCheck",
                runId => $"this pane did not run a check called '{runId}', so it does not "
                    + "know which folder to open.",
                runId => FindCheck(runId)?.RunDirectory))
        {
            LogFolder = options.LogFolder,
            EntityResolver = options.EntityResolver,
            Opener = options.Opener,
            Secrets = options.Secrets,
        });
    }

    /// <summary>The checks this host ran, oldest first.</summary>
    public IReadOnlyList<CheckRecord> Checks => _checks;

    /// <summary>The newest check, or null before the first one.</summary>
    public CheckRecord? LatestCheck { get; private set; }

    /// <summary>Records a check's folder and makes it the pane's latest run.</summary>
    public CheckRecord TrackCheck(string runDirectory)
    {
        if (runDirectory == null)
        {
            throw new ArgumentNullException(nameof(runDirectory));
        }

        var record = new CheckRecord(
            System.IO.Path.GetFileName(runDirectory.TrimEnd(
                System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar)),
            runDirectory,
            _options.Now());

        _checks.RemoveAll(check => check.CheckId == record.CheckId);
        _checks.Add(record);
        LatestCheck = record;
        _options.RegisterLatestRun(runDirectory);
        return record;
    }

    /// <summary>The record for <paramref name="checkId"/>, or null.</summary>
    public CheckRecord? FindCheck(string checkId) =>
        _checks.FirstOrDefault(check => check.CheckId == checkId);

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

    /// <summary>Tells the page which document the pane is looking at now, or that there is none.</summary>
    public void DocumentChanged() =>
        Post("document.changed", DocumentPayload(_options.CurrentDocument()));

    public void Dispose()
    {
        _checks.Clear();
        LatestCheck = null;
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

            case "check.start":
                StartCheck(id);
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
        CheckRecord? latest = LatestCheck;

        _actions.Send("init", id, new Dictionary<string, object?>
        {
            {
                "backend",
                endpoint == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "port", endpoint.Port },
                        { "origin", endpoint.Origin },
                    }
            },
            { "token", endpoint?.Token },
            { "run_root", _options.RunRoot() },
            { "document", DocumentPayload(_options.CurrentDocument()) },
            {
                "latest_check",
                latest == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "run_dir", latest.RunDirectory },
                        { "at", latest.At.ToString("o", CultureInfo.InvariantCulture) },
                    }
            },
        });
    }

    // ---- check.start --------------------------------------------------------------------

    /// <summary>
    /// Press Model check: refuse what cannot be checked, name and create the check run folder,
    /// dump the open part into it with the reduced profile, register the folder as the pane's
    /// latest run, and tell the page where it is. The page does the rest.
    /// </summary>
    private void StartCheck(string? id)
    {
        PageDocument? document = _options.CurrentDocument();
        if (document == null)
        {
            _actions.SendError(
                id,
                "NoDocument",
                "open the part you want checked in SOLIDWORKS first: the feature tree is read "
                + "from the active document.",
                retryable: true);
            return;
        }

        if (_options.Dump == null)
        {
            _actions.SendError(
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
            _actions.SendError(
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
            _actions.SendError(
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
            _actions.SendError(id, "ExtractionFailed", failure.Message, retryable: true);
            return;
        }

        TrackCheck(runDirectory);

        PostStatus(
            "ready",
            summary.Gaps == 0
                ? "Extracted. Checking the model..."
                : $"Extracted with {summary.Gaps} gaps. Checking the model...");

        _actions.Send("check.extracted", id, new Dictionary<string, object?>
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

    private static Dictionary<string, object?>? DocumentPayload(PageDocument? document) =>
        document == null
            ? null
            : new Dictionary<string, object?>
            {
                { "path", document.Path },
                { "configuration", document.Configuration },
                { "kind", document.Kind },
            };
}
