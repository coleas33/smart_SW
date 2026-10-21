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
        RunRootsInForce = () => new[] { RunRoot() };
    }

    public IPageChannel Channel { get; }

    public Func<string> RunRoot { get; }

    /// <summary>
    /// Every run root that has been in force in this SOLIDWORKS session, the one in force among them (owner
    /// decision 154A, the reviews' finding F6): a run made under any of them is this pane's to open - its report
    /// and its folder - after a settings save has moved the run root. The run root in force alone by default.
    /// </summary>
    public Func<IReadOnlyList<string>> RunRootsInForce { get; set; }

    /// <summary>
    /// The run root saved in the Review tab's Settings, which the next restart brings into force, or null when no
    /// review host knows it (the reviews of 154A's merge, N4): a start refused for the run root in force while
    /// another is saved says to retry the restart, not to choose a folder again. None by default.
    /// </summary>
    public Func<string?> RunRootSaved { get; set; } = () => null;

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

    /// <summary>
    /// Owner decision 157A: begins a check as a turn begins, so a settings restart and a check never overlap.
    /// Called with the step that marks the check in progress, after every refusal that needs no call: a settings
    /// restart that waits is made first, or the one being made is waited for, then the step is run under the
    /// restart's own lock and null answered; or the step is not run and the refusal is answered - what holds the
    /// restart back, or the restart's failure - with its class, words and flag. The add-in answers it through the
    /// review host (`ReviewHost.BeginCheck`). By default there is no restart to wait for, and the step runs at once.
    /// </summary>
    public Func<Action, BackendRequestException?> BeginCheck { get; set; } = begin =>
    {
        begin();
        return null;
    };

    /// <summary>
    /// Owner decision 157A: whether a settings restart stands before a check - one waits to be made, or one is
    /// being made - which the gate (<see cref="BeginCheck"/>) makes, or waits for, first. Read only to tell the
    /// page so; the gate decides. The add-in answers it through the review host (`ReviewHost.RestartAhead`). By
    /// default none does.
    /// </summary>
    public Func<bool> RestartAhead { get; set; } = () => false;

    /// <summary>
    /// Owner decision 157A: how long a check, once its run is handed to the page, holds the restart back waiting
    /// for the page's evaluation call to reach the pane's proxy. The page makes that call as soon as it reads the
    /// reply; a page that has gone - reloaded, or closed - never makes it, and this bounds the hold it leaves.
    /// </summary>
    public TimeSpan HandOverLimit { get; set; } = DefaultHandOverLimit;

    /// <summary>The <see cref="HandOverLimit"/> the add-in runs with: a minute.</summary>
    public static readonly TimeSpan DefaultHandOverLimit = TimeSpan.FromSeconds(60);

    /// <summary>
    /// A clock that only goes forward, for the <see cref="HandOverLimit"/>: <see cref="MonotonicClock"/> by default,
    /// which no change of the wall clock moves. Injected so the limit is testable.
    /// </summary>
    public Func<TimeSpan> Clock { get; set; } = MonotonicClock;

    /// <summary>The time since the add-in's process first asked, by a stopwatch: a clock no change of the wall clock moves.</summary>
    public static TimeSpan MonotonicClock() => Monotonic.Elapsed;

    private static readonly System.Diagnostics.Stopwatch Monotonic = System.Diagnostics.Stopwatch.StartNew();
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
/// <b>A check holds a settings restart back</b> (owner decision 157A), as a remodel run does since
/// 145A, and the hold is kept here for both owners: an owner's start begins through the review host's
/// gate (<see cref="BeginCheck"/>) once every refusal that needs no call is behind it, and the hold lasts
/// until the page's evaluation of the check has been answered - through the start, the hand-over of its
/// run to the page (<see cref="HandOver"/>) and the evaluation the pane's proxy holds it for while it is
/// out (<see cref="HoldEvaluation"/>) - or until the start ends any other way (<see cref="EndCheck"/>), or
/// the hand-over's limit passes with no evaluation, for a page that has gone. The review host's restart
/// reads <see cref="CheckInProgress"/> under its own lock.
///
/// Threading: <see cref="Receive"/> is not re-entrant and must not run on the SOLIDWORKS UI
/// thread - an owner's start step occupies the application thread for as long as its dump
/// takes. The caller delivers page messages one at a time, as it already does for every pane.
/// The hold is guarded by a lock of its own, taken under the restart's lock - by the gate's step and
/// the restart's reading - and by the proxy's thread, and nothing is called, waited on or asked of
/// SOLIDWORKS while it is held; the start's dump and its readings of the document run under no lock.
/// </summary>
public sealed class CheckPaneHost : IDisposable
{
    private readonly CheckPaneHostOptions _options;
    private readonly PaneActions _actions;
    private readonly List<CheckRecord> _checks = new List<CheckRecord>();

    /// <summary>
    /// Guards <see cref="_holds"/> and <see cref="_startHold"/> (owner decision 157A). Taken under the review host's
    /// restart lock - by the gate's step and by the restart's reading of <see cref="CheckInProgress"/> - and by the
    /// pane's proxy; never held while anything else is taken or waited on.
    /// </summary>
    private readonly object _holdLock = new object();

    /// <summary>
    /// Every check of this tab that holds a settings restart back (owner decision 157A): the one whose start runs on the
    /// tab's pump, and any handed to the page whose evaluation is out or awaited - two when a page loaded again presses
    /// again while its predecessor's evaluation is out.
    /// </summary>
    private readonly List<CheckHold> _holds = new List<CheckHold>();

    /// <summary>The hold of the check whose start runs on this tab's pump, from its gate's step to its hand-over; null otherwise.</summary>
    private CheckHold? _startHold;

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
            RunRootsInForce = () => options.RunRootsInForce(),
            RunRootSaved = () => options.RunRootSaved(),
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

    // ---- a check holds a settings restart back (owner decision 157A) -------------------------

    /// <summary>
    /// Whether a check of this tab holds a settings restart back (owner decision 157A): from its gate's step until the
    /// page's evaluation of it has been answered - while its start runs, once its run is handed to the page and until
    /// the hand-over's limit passes with no evaluation, and while the evaluation the pane's proxy holds for it is out.
    /// The review host reads it under its restart's own lock, so it takes only this tab's own lock, which nothing
    /// holds while it waits on anything.
    /// </summary>
    public bool CheckInProgress
    {
        get
        {
            lock (_holdLock)
            {
                TimeSpan now = _options.Clock();
                return _holds.Any(hold => Holds(hold, now));
            }
        }
    }

    /// <summary>
    /// Owner decision 157A: begins a check through the review host's gate, after every refusal that needs no call, as
    /// a remodel run begins (owner decision 145A): a settings restart that waits is made first, or the one being made
    /// is waited for, and the check takes its hold under the restart's own lock; or the press is answered with the
    /// gate's refusal - its class, words and flag - and nothing is held. The page is told first, in
    /// <paramref name="restartFirst"/>, when a restart stands before the press, since the gate can wait through it for
    /// seconds. A gate that throws leaves nothing held, whether or not it took the hold, and the throw is the press's
    /// answer. Answers whether the check holds the restart now; the owner then ends its start with
    /// <see cref="HandOver"/> or, any other way, <see cref="EndCheck"/>.
    /// </summary>
    public bool BeginCheck(string? id, string restartFirst)
    {
        if (RestartAhead())
        {
            PostStatus("backend_starting", restartFirst);
        }

        BackendRequestException? held;
        try
        {
            held = _options.BeginCheck(TakeTheHold);
        }
        catch (Exception)
        {
            EndCheck();
            throw;
        }

        if (held == null)
        {
            return true;
        }

        EndCheck();
        _actions.SendError(id, held.ErrorClass, held.Message, held.Retryable);
        return false;
    }

    /// <summary>
    /// Owner decision 157A: the start of the check that holds the restart has handed its run in
    /// <paramref name="runDirectory"/> to the page, whose evaluation of it the hold now waits for - until the pane's
    /// proxy takes the hold over for that evaluation (<see cref="HoldEvaluation"/>), or the hand-over's limit passes.
    /// Called before the page is told, so an evaluation sent the instant it is finds the hold handed over.
    /// </summary>
    public void HandOver(string runDirectory)
    {
        lock (_holdLock)
        {
            if (_startHold == null)
            {
                return;
            }

            _startHold.HandedOver = runDirectory;
            _startHold.HandedOverAt = _options.Clock();
            _startHold = null;
        }
    }

    /// <summary>
    /// Owner decision 157A: the start of the check that holds the restart has ended without handing its run on - it
    /// was refused, or failed, once its gate was passed - and lets the hold go. Nothing when no start holds it.
    /// </summary>
    public void EndCheck()
    {
        lock (_holdLock)
        {
            if (_startHold != null)
            {
                _holds.Remove(_startHold);
                _startHold = null;
            }
        }
    }

    /// <summary>
    /// Owner decision 157A: the pane's proxy takes over the hold of the check whose run was handed to the page in
    /// <paramref name="runDirectory"/> - the folder the page's evaluation names, compared ignoring letter case and a
    /// trailing separator - for as long as the evaluation is out, and lets it go, once, when the evaluation has been
    /// answered. Null when no check of this tab waits for that evaluation: no hand-over of that folder, one already
    /// taken over, or one whose limit has passed, which no evaluation brings back, since a restart may be under way.
    /// </summary>
    public IDisposable? HoldEvaluation(string runDirectory)
    {
        lock (_holdLock)
        {
            TimeSpan now = _options.Clock();
            CheckHold? hold = _holds.FirstOrDefault(candidate =>
                candidate.HandedOver != null
                && !candidate.TakenOver
                && Holds(candidate, now)
                && SameFolder(candidate.HandedOver, runDirectory));
            if (hold == null)
            {
                return null;
            }

            hold.TakenOver = true;
            return new EvaluationHold(this, hold);
        }
    }

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

    /// <summary><see cref="PostStatus(string, string)"/>, marked as the add-in's own word on the backend when <paramref name="lifecycle"/> (owner decision 145A).</summary>
    public void PostStatus(string stage, string message, bool lifecycle) => _actions.PostStatus(stage, message, lifecycle);

    /// <summary>Tells the page which document the pane is looking at now, or that there is none.</summary>
    public void DocumentChanged() =>
        Post("document.changed", DocumentPayload(_options.CurrentDocument()));

    /// <summary>
    /// Tells the page the backend was restarted with saved settings, so it asks `ready` again for
    /// the new port and token (owner decision 145A): both check pages call their check routes with
    /// what `init` carried, and the restarted backend refuses the old token. The add-in calls it
    /// after every restart the review host makes. No sentence travels with it: the Review tab's
    /// sentences about a restart that waited are shown on the Review tab alone.
    /// </summary>
    public void BackendRestarted() => _actions.PostBackendRestarted(Array.Empty<string>());

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
    /// A path setting as `init` carries it: the setting, or null when it is blank. Both check
    /// tabs hand the page the standards profile's path this way (the Standards tab as
    /// `profile_path`, the Model check tab as `standards_profile`, feature 013 T150), so "a blank
    /// setting is no setting" is written once.
    /// </summary>
    public static string? Configured(string? setting) =>
        string.IsNullOrWhiteSpace(setting) ? null : setting;

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

        // The add-in unloading: nothing of this tab holds a restart any more (owner decision 157A).
        lock (_holdLock)
        {
            _holds.Clear();
            _startHold = null;
        }
    }

    /// <summary>
    /// Owner decision 157A: the gate's step - the check takes its hold, under the restart's own lock, so it is in
    /// progress before any restart can look again. Takes only this tab's own lock. Holds whose hand-over passed its
    /// limit are dropped here, since nothing can bring one back.
    /// </summary>
    private void TakeTheHold()
    {
        lock (_holdLock)
        {
            TimeSpan now = _options.Clock();
            _holds.RemoveAll(hold => !Holds(hold, now));
            _startHold = new CheckHold();
            _holds.Add(_startHold);
        }
    }

    /// <summary>
    /// Whether <paramref name="hold"/> holds the restart back at <paramref name="now"/>: while its start runs, while the
    /// proxy holds its evaluation, and once handed over, until the hand-over's limit. Called under <see cref="_holdLock"/>.
    /// </summary>
    private bool Holds(CheckHold hold, TimeSpan now) =>
        hold.HandedOver == null || hold.TakenOver || now - hold.HandedOverAt < _options.HandOverLimit;

    /// <summary>Lets <paramref name="hold"/> go, once its evaluation has been answered: that hold, and no other check's.</summary>
    private void LetGo(CheckHold hold)
    {
        lock (_holdLock)
        {
            _holds.Remove(hold);
        }
    }

    /// <summary>
    /// Whether a restart stands before the press. Only words for the page hang on it, so a reading that throws is none:
    /// the press goes on through the gate, which decides.
    /// </summary>
    private bool RestartAhead()
    {
        try
        {
            return _options.RestartAhead();
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>The same run folder: as written, ignoring letter case and a trailing separator, as Windows names a folder.</summary>
    private static bool SameFolder(string handedOver, string named) =>
        string.Equals(
            handedOver.TrimEnd(System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar),
            named.TrimEnd(System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar),
            StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// One check's hold on a settings restart (owner decision 157A): taken by its gate's step; handed over with its run
    /// to the page (<see cref="HandedOver"/>, null while its start runs); taken over by the pane's proxy while the
    /// evaluation is out (<see cref="TakenOver"/>). Guarded by <see cref="_holdLock"/>.
    /// </summary>
    private sealed class CheckHold
    {
        public string? HandedOver;

        public TimeSpan HandedOverAt;

        public bool TakenOver;
    }

    /// <summary>The proxy's hold of one evaluation: let go once, and only its own check's hold.</summary>
    private sealed class EvaluationHold : IDisposable
    {
        private readonly CheckHold _hold;
        private CheckPaneHost? _pane;

        public EvaluationHold(CheckPaneHost pane, CheckHold hold)
        {
            _pane = pane;
            _hold = hold;
        }

        public void Dispose() => System.Threading.Interlocked.Exchange(ref _pane, null)?.LetGo(_hold);
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
