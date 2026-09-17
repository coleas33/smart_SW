using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;

namespace SwReview.AddIn.Review;

/// <summary>
/// One check a pane host ran: enough to answer `report.open` and `folder.open` without ever
/// taking a path from the page.
///
/// <see cref="CheckId"/> is the run folder's own name, which is also how the backend addresses
/// a check (`GET /checks/{check_id}`). One id, so a page holding a check's result can ask its
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

    /// <summary>The run folder's name, `&lt;yyyyMMdd-HHmmss&gt;-&lt;doc&gt;-&lt;check&gt;`.</summary>
    public string CheckId { get; }

    public string RunDirectory { get; }

    /// <summary>When the check was started, as `init.latest_check.at` carries it.</summary>
    public DateTime At { get; }
}

/// <summary>Everything <see cref="CheckPaneHost"/> is given; injected so it is testable headless.</summary>
public sealed class CheckPaneHostOptions
{
    /// <param name="channel">Where replies and unsolicited messages go.</param>
    /// <param name="runRoot">The run root in force, read fresh: a settings save moves it.</param>
    /// <param name="startType">The one message type the owner answers itself.</param>
    /// <param name="start">
    /// The owner's start step, given the page message's id so its reply and its refusals echo
    /// it. It is the only thing about a check tab this class does not know.
    /// </param>
    public CheckPaneHostOptions(
        IPageChannel channel, Func<string> runRoot, string startType, Action<string?> start)
    {
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        RunRoot = runRoot ?? throw new ArgumentNullException(nameof(runRoot));
        StartType = startType ?? throw new ArgumentNullException(nameof(startType));
        Start = start ?? throw new ArgumentNullException(nameof(start));
    }

    public IPageChannel Channel { get; }

    public Func<string> RunRoot { get; }

    /// <summary>`check.start` for the Model check tab, `standards.start` for the Standards tab.</summary>
    public string StartType { get; }

    /// <summary>The owner's one start step.</summary>
    public Action<string?> Start { get; }

    /// <summary>
    /// The backend's endpoint, or null before it is listening. Both check pages call their
    /// check routes themselves with what `init` carries, so this is the whole of a check host's
    /// involvement with it.
    /// </summary>
    public Func<BackendEndpoint?> Backend { get; set; } = () => null;

    /// <summary>The open document, asked for fresh each time; SOLIDWORKS owns the answer.</summary>
    public Func<PageDocument?> CurrentDocument { get; set; } = () => null;

    /// <summary>
    /// Makes the check's folder the pane's latest run (`ReviewHost.TrackCheck`). There is one
    /// answer to "which folder is the pane looking at" and it is not a check host's to keep.
    /// </summary>
    public Action<string> RegisterLatestRun { get; set; } = _ => { };

    /// <summary>Show in SOLIDWORKS; null before the add-in is attached.</summary>
    public Func<IEntityResolver?> EntityResolver { get; set; } = () => null;

    /// <summary>What `report.open`, `folder.open` and `log.open` shell out through.</summary>
    public Func<IPathOpener> Opener { get; set; } = () => new ShellPathOpener();

    /// <summary>%LOCALAPPDATA%\SwReview\logs by default; what `log.open` opens.</summary>
    public Func<string> LogFolder { get; set; } = ReviewHostOptions.DefaultLogFolder;

    /// <summary>
    /// The run-folder suffix this pane's own checks carry - <see cref="RunFolders.CheckSuffix"/>
    /// for the Model check tab, <see cref="RunFolders.StandardsSuffix"/> for the Standards tab -
    /// or null to look on disk for nothing.
    ///
    /// It is what <see cref="SendInit"/> reads the newest run back by after a restart, from the
    /// folder names alone (`contracts/standards-check.md` section 4). There is no default: an
    /// owner that did not say which suffix is its own reports only the checks this session ran,
    /// which is exactly the behaviour every pane had before the scan existed. A wrong default
    /// here would answer one tab with the other tab's run.
    /// </summary>
    public string? LatestCheckSuffix { get; set; }

    /// <summary>
    /// Fields the owner adds to its own `init` reply, or null. The Standards tab's
    /// `profile_path` is the only one (`contracts/standards-check.md` section 2, D9); the Model
    /// check tab adds none, and its `init` is unchanged.
    ///
    /// A seam rather than a `profile_path` field on this class, because a profile is the
    /// Standards tab's business and nothing here should know it exists.
    /// </summary>
    public Func<IEnumerable<KeyValuePair<string, object?>>?> ExtraInitFields { get; set; } =
        () => null;

    /// <summary>Check-record timestamps. Injected so the naming rule is testable.</summary>
    public Func<DateTime> Now { get; set; } = () => DateTime.Now;

    /// <summary>Values that must never reach the page (FR-015).</summary>
    public Func<IEnumerable<string?>> Secrets { get; set; } = () => new string?[0];
}

/// <summary>
/// The page-channel plumbing both check tabs hold: the envelope, `ready`, the check records,
/// the unsolicited messages and the four shared rows. Everything a check tab does that is not
/// its own start step.
///
/// <b>A collaborator, not a base class.</b> A shared abstract host over all four panes stays
/// rejected for the reason feature 003 gave - <see cref="ReviewHost"/> needs backend chat
/// state and the re-modeler needs a seat and a pipeline, and inheritance would drag all four
/// sets of dependencies into one type. But that argument is about the two hosts that are not in
/// question. The two check hosts need the same plumbing and neither needs the other's
/// dependencies, so they <i>hold</i> one copy of it and keep their own start verb and their own
/// refusals (plan.md Structure Decision 3). Composition also keeps each host's dependencies
/// visible in its own constructor, which a base class would hide.
///
/// <b>One deviation from that sentence, and it is not paraphrased away.</b> Structure Decision 3
/// also says the two hosts keep "their own record type", and they do not:
/// <see cref="CheckRecord"/> moved here out of `Model/ModelCheckHost.cs` and both hosts share
/// it. Two identical three-field records, one per host, would be a copy of exactly what this
/// class exists to stop copying, and keeping them apart would mean making
/// <see cref="TrackCheck"/>, <see cref="FindCheck"/>, <see cref="Checks"/> and
/// <see cref="LatestCheck"/> generic over an owner-supplied type for no behaviour. The record
/// carries a folder name, a directory and a timestamp and says nothing about a family, so the
/// substance of the sentence - no family leaks between the hosts - holds; its letter does not.
/// It is recorded as a deviation for the owner rather than quietly rewritten.
///
/// <b>The four shared rows are still <see cref="PaneActions"/>'s.</b> This class asks it first
/// and falls through to `ready` and the owner's start type; it re-implements none of them, and
/// `PaneActions` is not edited. `PaneActionsTests` is parameterized over the hosts and proves
/// the rows identical across them rather than assuming it from a shared parent.
///
/// <b>What it still does not do</b> is most of the design: it evaluates nothing (there is one
/// no-language-model evaluation entry point and it is in Python, FR-024), it registers no tool
/// and writes to no document, and it does not own "the pane's latest run" - it hands each
/// check's folder to <see cref="CheckPaneHostOptions.RegisterLatestRun"/> so `entity.show`
/// resolves `document_id` through the package that was just written.
///
/// Threading: <see cref="Receive"/> is not re-entrant and must not run on the SOLIDWORKS UI
/// thread - an owner's start step occupies the application thread for as long as its dump
/// takes. The caller delivers page messages one at a time, as it already does for every pane.
/// </summary>
public sealed class CheckPaneHost : IDisposable
{
    private readonly CheckPaneHostOptions _options;
    private readonly PaneActions _actions;
    private readonly List<CheckRecord> _checks = new List<CheckRecord>();

    public CheckPaneHost(CheckPaneHostOptions options)
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
            LogFolder = () => options.LogFolder(),
            EntityResolver = () => options.EntityResolver(),
            Opener = () => options.Opener(),
            Secrets = () => options.Secrets(),
        });
    }

    /// <summary>
    /// The four shared rows and the envelope, for the owner's own replies and refusals. There
    /// is one <see cref="PaneActions"/> per pane and the owner sends through this one.
    /// </summary>
    public PaneActions Actions => _actions;

    /// <summary>The checks this pane ran, oldest first.</summary>
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

    /// <summary>
    /// The `init` reply: the backend, the token, the run root, the open document, whatever the
    /// owner adds, and the newest check this pane can answer for - the one this session ran, or
    /// failing that the newest folder on disk carrying this pane's own suffix, which is how a
    /// check survives a restart (FR-034, SC-009).
    /// </summary>
    public void SendInit(string? id)
    {
        BackendEndpoint? endpoint = _options.Backend();
        CheckRecord? latest = LatestCheck ?? NewestOnDisk();

        var payload = new Dictionary<string, object?>
        {
            {
                "backend",
                endpoint == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "port", endpoint.Port },

                        // The page's OWN origin under `/__backend`, as `ReviewHost` sends: a
                        // check page calls its check route and reads the result back, and it
                        // does both through the host rather than over loopback
                        // (docs/pane-backend-proxy.md). The port stays for diagnostics.
                        { "origin", BackendProxy.PageOrigin },
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
        };

        IEnumerable<KeyValuePair<string, object?>>? extra = _options.ExtraInitFields();
        if (extra != null)
        {
            foreach (KeyValuePair<string, object?> field in extra)
            {
                payload[field.Key] = field.Value;
            }
        }

        _actions.Send("init", id, payload);
    }

    /// <summary>
    /// The newest run folder on disk carrying this pane's own suffix, as a record, or null.
    ///
    /// It is <b>recorded</b> as well as reported, so `report.open` and `folder.open` answer for
    /// the run the page was just told about: a check read back after a restart that could be
    /// rendered but not opened would be a button that always refuses. It is <b>not</b> handed to
    /// <see cref="CheckPaneHostOptions.RegisterLatestRun"/> and does not become
    /// <see cref="LatestCheck"/> - this session did not run it, and re-pointing the pane's
    /// latest run at an old folder would move `entity.show` and the Ask tab off whatever the
    /// engineer is actually working in.
    /// </summary>
    private CheckRecord? NewestOnDisk()
    {
        if (_options.LatestCheckSuffix == null)
        {
            return null;
        }

        string? directory = RunFolders.NewestCheckFolder(
            _options.RunRoot(), _options.LatestCheckSuffix!);
        if (directory == null)
        {
            return null;
        }

        string name = System.IO.Path.GetFileName(directory);
        CheckRecord? known = FindCheck(name);
        if (known != null)
        {
            return known;
        }

        // The folder's own name carries when the run started, which is the same thing
        // `TrackCheck` records from the clock for a run this session made.
        var record = new CheckRecord(
            name, directory, RunFolders.TimestampOf(name) ?? _options.Now());
        _checks.Add(record);
        return record;
    }

    /// <summary>
    /// The document as `init` and `document.changed` both carry it, or null when there is none.
    /// One shape, so no page has two to read, and a kind the extension does not name stays null
    /// rather than becoming a guess.
    /// </summary>
    public static Dictionary<string, object?>? DocumentPayload(PageDocument? document) =>
        document == null
            ? null
            : new Dictionary<string, object?>
            {
                { "path", document.Path },
                { "configuration", document.Configuration },
                { "kind", document.Kind },
            };

    public void Dispose()
    {
        _checks.Clear();
        LatestCheck = null;
    }

    private void Dispatch(string type, string? id, JsonElement payload)
    {
        // The four rows this pane shares with every other one, answered by the one copy of them.
        if (_actions.TryHandle(type, id, payload))
        {
            return;
        }

        if (type == "ready")
        {
            SendInit(id);
            return;
        }

        if (type == _options.StartType)
        {
            _options.Start(id);
            return;
        }

        _actions.SendError(
            id,
            "UnknownMessage",
            $"the host does not handle a '{type}' message",
            retryable: false);
    }
}
