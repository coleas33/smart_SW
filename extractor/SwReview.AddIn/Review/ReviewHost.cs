using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Settings;

namespace SwReview.AddIn.Review;

/// <summary>The document the pane is looking at, as `init` and `document.changed` carry it.</summary>
public sealed class PageDocument
{
    public PageDocument(string path, string? configuration)
    {
        Path = path ?? throw new ArgumentNullException(nameof(path));
        Configuration = configuration;
    }

    public string Path { get; }

    public string? Configuration { get; }

    /// <summary>
    /// `part`, `assembly`, `drawing`, or null when the path does not say.
    ///
    /// Read from the extension because the extension is what SOLIDWORKS requires of a saved
    /// document, and the pane only ever sees saved ones - `CurrentDocument` reports no document
    /// at all when `GetPathName` is empty. Null rather than a guess for anything else: the
    /// Model check tab refuses what is not a part, and a wrong "part" here would run the RMS
    /// rules against a document they were never written for.
    /// </summary>
    public string? Kind
    {
        get
        {
            string extension = System.IO.Path.GetExtension(Path);
            if (string.Equals(extension, ".sldprt", StringComparison.OrdinalIgnoreCase))
            {
                return "part";
            }

            if (string.Equals(extension, ".sldasm", StringComparison.OrdinalIgnoreCase))
            {
                return "assembly";
            }

            if (string.Equals(extension, ".slddrw", StringComparison.OrdinalIgnoreCase))
            {
                return "drawing";
            }

            return null;
        }
    }

    /// <summary>
    /// Whether a scope can be attached to this document - which is to say, whether it is a part
    /// or an assembly.
    ///
    /// A drawing is not: it has no configuration, and <c>SwSession.Attach</c> binds the session
    /// to the active one. Attaching to one therefore throws, and the tool service swallows a
    /// failed start into addin.log, so a SOLIDWORKS loaded with a drawing active used to leave
    /// the bridge, the terminal's tools and the Remodel tab off for the whole session. The
    /// document is refused here instead, where the refusal can be said out loud.
    ///
    /// Read from <see cref="Kind"/> rather than from a second extension table, so the pane and
    /// the tool service can never disagree about what a path is; null - a path whose extension
    /// names no kind - is not attachable, for the reason <see cref="Kind"/> gives for not
    /// guessing.
    /// </summary>
    public bool IsAttachable => Kind == "part" || Kind == "assembly";
}

/// <summary>
/// What the host knows about one run it started: enough to answer `report.open` and
/// `folder.open` without ever taking a path from the page (pane-host-messages.md).
///
/// A record is either a chat - a review, with a `chat_id` the backend gave out - or a Model
/// check, which has no chat at all because nothing about it goes to a language model. Both are
/// tracked here because both are "the pane's latest run", which is what
/// `CurrentSessionRunDirectory` and <see cref="RunPackageIndex"/> read; only one of them is a
/// thing the backend can be asked about (FR-028).
/// </summary>
public sealed class SessionRecord
{
    private SessionRecord(
        string? chatId, string runDirectory, bool isCheck, PageDocument? document, DateTimeOffset? startedAt)
    {
        ChatId = chatId;
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        IsCheck = isCheck;
        Document = document;
        StartedAt = startedAt;
    }

    public SessionRecord(string chatId, string runDirectory)
        : this(chatId, runDirectory, null, null)
    {
    }

    /// <param name="document">The document `review.started` named - the one captured before
    /// the dump - or null when the caller does not know it.</param>
    /// <param name="startedAt">When the review was tracked, or null.</param>
    public SessionRecord(string chatId, string runDirectory, PageDocument? document, DateTimeOffset? startedAt)
        : this(chatId ?? throw new ArgumentNullException(nameof(chatId)), runDirectory, false, document, startedAt)
    {
    }

    /// <summary>The backend's chat id, or null for a check: there is no chat to name.</summary>
    public string? ChatId { get; }

    public string RunDirectory { get; }

    /// <summary>
    /// The run folder's own name - what `GET /reviews/{run_id}` is asked for when the backend no
    /// longer holds the chat (feature 009, contracts/sessions.md section 4).
    /// </summary>
    public string RunId => System.IO.Path.GetFileName(RunDirectory.TrimEnd('\\', '/'));

    /// <summary>
    /// The document the review is of, as `review.started` named it; null for a check or remodel
    /// record, and for a chat tracked without one. What a review chip names (feature 009 FR-020).
    /// </summary>
    public PageDocument? Document { get; }

    /// <summary>When the review was tracked (`ReviewHostOptions.Now`); null for a check.</summary>
    public DateTimeOffset? StartedAt { get; }

    /// <summary>
    /// Whether this run is a Model check.
    ///
    /// Stated rather than inferred from a null chat id, because what the any-turn-running scan
    /// needs to know is "is there a turn this could be running", and a reader of that scan
    /// should not have to work out that a missing id means no chat exists rather than that one
    /// has not arrived yet.
    /// </summary>
    public bool IsCheck { get; }

    /// <summary>A Model check's run folder: no chat id, because a check has no chat.</summary>
    public static SessionRecord ForCheck(string runDirectory) =>
        new SessionRecord(null, runDirectory, true, null, null);
}

/// <summary>Everything <see cref="ReviewHost"/> is given; injected so it is testable headless.</summary>
public sealed class ReviewHostOptions
{
    public ReviewHostOptions(IPageChannel channel, IBackendClient backend, string settingsPath)
    {
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        Backend = backend ?? throw new ArgumentNullException(nameof(backend));
        SettingsPath = settingsPath ?? throw new ArgumentNullException(nameof(settingsPath));
    }

    public IPageChannel Channel { get; }

    public IBackendClient Backend { get; }

    public string SettingsPath { get; }

    /// <summary>Whether the scripted `fake` provider may be offered and saved (FR-027).</summary>
    public BuildMode BuildMode { get; set; } = BuildModes.Current;

    /// <summary>%LOCALAPPDATA%\SwReview\logs by default; what `log.open` opens.</summary>
    public string LogFolder { get; set; } = DefaultLogFolder();

    /// <summary>The open document, asked for fresh each time; SOLIDWORKS owns the answer.</summary>
    public Func<PageDocument?> CurrentDocument { get; set; } = () => null;

    /// <summary>Read only the component census before a paid review; no run folder or model call.</summary>
    public Func<ReviewPreparation>? PrepareReview { get; set; }

    /// <summary>
    /// The in-process extractor. Null until the add-in is attached to a SOLIDWORKS session,
    /// which is a state the pane really has: the Task Pane exists before the first document.
    /// </summary>
    public IReviewDump? Dump { get; set; }

    /// <summary>Show in SOLIDWORKS. Null for the same reason as <see cref="Dump"/>.</summary>
    public IEntityResolver? EntityResolver { get; set; }

    /// <summary>What `report.open`, `folder.open` and `log.open` shell out through.</summary>
    public IPathOpener Opener { get; set; } = new ShellPathOpener();

    /// <summary>The in-process tool service, once it is listening (T048); null before that.</summary>
    public BridgeConfig? Bridge { get; set; }

    /// <summary>Who the review and its dispositions are attributed to.</summary>
    public string Engineer { get; set; } = System.Environment.UserName;

    /// <summary>Run-folder timestamps. Injected so the naming rule is testable.</summary>
    public Func<DateTime> Now { get; set; } = () => DateTime.Now;

    /// <summary>Reads one environment variable; injected so no test mutates the process.</summary>
    public Func<string, string?> Environment { get; set; } =
        System.Environment.GetEnvironmentVariable;

    internal static string DefaultLogFolder() => System.IO.Path.Combine(
        System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData),
        "SwReview",
        "logs");
}

/// <summary>
/// The Review page's other half: it receives `{type, id, payload}` from the page and answers
/// on the same channel.
///
/// This class holds the whole page-to-host table: the Settings half (`ready`/`init`,
/// `settings.get`, `settings.save`, `models.list`) and the review flow (`review.start`), on
/// one dispatch over one set of session records. The four rows every pane host shares -
/// `entity.show`, `report.open`, `folder.open`, `log.open` - live in <see cref="PaneActions"/>
/// and are delegated, because the Model check tab serves the same four and a second copy of
/// them would be a second copy of the run-root containment rule. SOLIDWORKS, the extractor,
/// the shell and the backend each reach it through an interface, so all of it is testable with
/// no SOLIDWORKS, no WebView2 and no Python.
///
/// Six rules are enforced here or in <see cref="PaneActions"/> because nowhere else can:
///
/// <b>The key goes out to the page in no form at all.</b> Every settings payload is built from
/// an explicit allow-list of fields (<see cref="View"/>) rather than by serializing
/// <see cref="UserSettings"/> and deleting one, so a field added to the settings file later
/// cannot silently start being echoed. The page learns only `key_source` (FR-015).
///
/// <b>`settings.save` is refused, whole, while a turn is running.</b> Not partially applied
/// and not queued: a running turn owns process state that is not on disk, so the file is not
/// written and the backend is not restarted (chat-api.md).
///
/// <b>A model the provider does not offer is refused, and the fresh list is pushed with the
/// refusal</b>, so the engineer re-picks from what exists instead of meeting it later as an
/// error in the middle of a review. When the provider cannot be asked at all - no key, no
/// network, a gateway that is down - the model is saved unchecked, because configuring the
/// pane must not require the thing being configured to already work.
///
/// <b>The page never names a path to open.</b> `report.open` and `folder.open` carry a
/// `chat_id`; the folder comes from this host's own session record, and every resolved path is
/// canonicalized and checked to be inside `run_root` (or the log folder) before it reaches the
/// shell. The page is the least trusted thing in the process - it renders text the model and
/// reviewed documents wrote - so a path it supplied would be a way to open anything on the
/// workstation.
///
/// <b>A reference that no longer resolves is an answer, not an error.</b> `entity.show` always
/// replies `entity.shown`, carrying the state code and the component's full path, so the
/// finding card can tell the engineer where to look by hand (spec Edge Cases, SC-007).
///
/// <b>Nothing thrown here reaches WebView2.</b> <see cref="Receive"/> answers every failure
/// with an `error` message, redacted; an exception escaping into the `WebMessageReceived`
/// handler would surface inside SOLIDWORKS.
///
/// Threading: <see cref="Receive"/> is not re-entrant. The caller delivers page messages one
/// at a time (see <see cref="IPageChannel"/>), off the SOLIDWORKS UI thread, because a
/// backend restart takes seconds. That pump thread is the only one that *mutates* the session
/// list, but it is no longer the only one that reads it: the tool-service gate asks
/// <see cref="AnyTurnRunning"/> from the thread it schedules its re-attach on, to decide
/// whether the bridge may follow the document the engineer just opened
/// (docs/pane-findings-2026-09-16.md, finding 1). So the list is guarded by its own lock, and
/// the backend round trips that scan makes are taken outside it.
/// </summary>
public sealed class ReviewHost : IDisposable
{
    private string? _preparationId;
    private PageDocument? _preparedDocument;
    private static readonly string[] AllProviders = { "openai", "gemini", "fake" };
    private static readonly string[] ReleaseProviders = { "openai", "gemini" };
    private static readonly string[] Efforts = { "low", "medium", "high", "xhigh" };

    private readonly ReviewHostOptions _options;
    private readonly List<SessionRecord> _sessions = new List<SessionRecord>();

    /// <summary>Guards <see cref="_sessions"/>; see the threading note in the class remarks.</summary>
    private readonly object _sessionsLock = new object();
    private readonly PaneActions _actions;

    /// <summary>
    /// How this host's page names a run - by `chat_id` - and how an unknown one is refused. Kept
    /// so `session.forget` refuses exactly as `report.open` does (contracts/sessions.md section 2).
    /// </summary>
    private readonly PaneRunLookup _runs;

    /// <summary>
    /// The one event-stream reader this host owns. One per host rather than one per chat: the
    /// page shows one chat at a time, and a reader for a chat nobody is looking at would be a
    /// socket and a thread kept open for a transcript that has been replaced.
    /// </summary>
    private readonly EventStreamPump _events;

    private UserSettings _settings;
    private string? _settingsError;

    public ReviewHost(ReviewHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
        SettingsLoadResult loaded = UserSettings.Load(options.SettingsPath, options.BuildMode);
        _settings = loaded.Settings;
        _settingsError = loaded.Error;

        _runs = new PaneRunLookup(
            "chat_id",
            "UnknownChat",
            chatId => $"this pane did not start a chat called '{chatId}', so it does not "
                + "know which folder to open.",
            chatId => FindSession(chatId)?.RunDirectory);

        _actions = new PaneActions(new PaneActionsOptions(options.Channel, () => _settings.RunRoot, _runs)
        {
            LogFolder = () => _options.LogFolder,
            EntityResolver = () => _options.EntityResolver,
            Opener = () => _options.Opener,
            Secrets = () => new[] { _settings.ResolveApiKey(_options.Environment).Key },
        });

        // Both callbacks run on the pump's reader thread. They go out through `Post`, which is
        // the same choke point every other unsolicited message uses, and both strings are
        // redacted: a frame carries a provider's own error message, and a failure reason carries
        // whatever the transport said (FR-015).
        _events = new EventStreamPump(
            () => _options.Backend.Endpoint,
            (chatId, frame) => Post("events.frame", new Dictionary<string, object?>
            {
                { "chat_id", chatId },
                { "frame", Redact(frame) },
            }),
            (chatId, reason) => Post("events.closed", new Dictionary<string, object?>
            {
                { "chat_id", chatId },
                { "reason", Redact(reason) },
            }));
    }

    /// <summary>The settings in force. Replaced by a successful `settings.save`.</summary>
    public UserSettings Settings => _settings;

    /// <summary>
    /// The chats this host started, newest last. A snapshot: the list itself is guarded, and a
    /// caller that walked the live one would be back to enumerating it while the pump appends.
    /// </summary>
    public IReadOnlyList<SessionRecord> Sessions
    {
        get
        {
            lock (_sessionsLock)
            {
                return _sessions.ToArray();
            }
        }
    }

    /// <summary>
    /// The chat the pane is showing: the most recently started one, or null before the first
    /// review.
    ///
    /// A single reference rather than a walk over <see cref="Sessions"/> because
    /// `entity.show` resolves against it from the SOLIDWORKS application thread while this
    /// host is on the page's message pump: a reference assignment crosses threads safely and
    /// a `List&lt;T&gt;` being appended to does not. The page shows one chat at a time -
    /// starting a review clears the transcript - so "the latest" is the one whose ids the
    /// finding cards carry.
    /// </summary>
    public SessionRecord? LatestSession { get; private set; }

    /// <summary>Records a chat so the host - and never the page - owns its run folder path.</summary>
    public void TrackSession(string chatId, string runDirectory) =>
        TrackSession(chatId, runDirectory, null, null);

    /// <summary>
    /// Records a review with what its chip names: the document `review.started` named and when
    /// it was tracked (feature 009 FR-020, contracts/sessions.md section 1). The record lives for
    /// the SOLIDWORKS session, not the backend process: a settings save restarts the backend and
    /// keeps every record.
    /// </summary>
    public void TrackSession(string chatId, string runDirectory, PageDocument? document, DateTimeOffset? startedAt)
    {
        if (chatId == null)
        {
            throw new ArgumentNullException(nameof(chatId));
        }

        var record = new SessionRecord(chatId, runDirectory, document, startedAt);
        lock (_sessionsLock)
        {
            _sessions.RemoveAll(session => session.ChatId == chatId);
            _sessions.Add(record);
        }

        LatestSession = record;
    }

    /// <summary>
    /// The reviews this host started, in the order it tracked them - chats only, never a check
    /// or remodel record. A snapshot taken under the lock, for the same reason as
    /// <see cref="Sessions"/>.
    /// </summary>
    public IReadOnlyList<SessionRecord> Reviews()
    {
        lock (_sessionsLock)
        {
            return _sessions.Where(session => !session.IsCheck && session.ChatId != null).ToArray();
        }
    }

    /// <summary>
    /// Forgets one review's record - the chip's Remove, for a review that can no longer be
    /// restored. `LatestSession` is cleared when it was that record, so nothing resolves against
    /// a record that is gone. Answers whether there was such a review.
    /// </summary>
    public bool ForgetSession(string chatId)
    {
        SessionRecord? record;
        lock (_sessionsLock)
        {
            record = _sessions.FirstOrDefault(session => session.ChatId != null && session.ChatId == chatId);
            if (record == null)
            {
                return false;
            }

            _sessions.Remove(record);
        }

        if (ReferenceEquals(LatestSession, record))
        {
            LatestSession = null;
        }

        return true;
    }

    /// <summary>
    /// Records a Model check's run folder as the pane's latest run.
    ///
    /// The check tab has its own host, but there is one answer to "which folder is the pane
    /// looking at": `CurrentSessionRunDirectory` and <see cref="RunPackageIndex"/> both read
    /// <see cref="LatestSession"/>, and `entity.show` resolves `document_id` to a path through
    /// the package in that folder. A check that registered somewhere else would silently
    /// degrade Show to "no full path" for every finding and open the Ask tab in an unrelated
    /// folder (FR-028, `contracts/model-check.md` section 4).
    /// </summary>
    public SessionRecord TrackCheck(string runDirectory)
    {
        var record = SessionRecord.ForCheck(runDirectory);
        lock (_sessionsLock)
        {
            _sessions.Add(record);
        }

        LatestSession = record;
        return record;
    }

    /// <summary>The record for <paramref name="chatId"/>, or null.</summary>
    public SessionRecord? FindSession(string chatId)
    {
        lock (_sessionsLock)
        {
            return _sessions.FirstOrDefault(session => session.ChatId == chatId);
        }
    }

    /// <summary>
    /// Feature 011 T074: the run folder of the review this host started whose folder is named
    /// <paramref name="runId"/>, or null. The one lookup the bridge's `drawing.read` resolves its
    /// `run_id` through (specs/011-drawing-context/contracts/confirmed-open.md section 2, item 1),
    /// read-only, from the host's own records - as `report.open` resolves a chat.
    ///
    /// <b>The id is never read as a path.</b> It is compared with each record's
    /// <see cref="SessionRecord.RunId"/> and with nothing else - never combined, normalized or
    /// probed - so a full folder, a relative one or a traversal answers null even when it spells a
    /// folder this host tracked. Ignoring case, because the id names a folder and Windows folder
    /// names are not case-sensitive (<c>RemodelHost.FindRun</c> matches a run id the same way).
    ///
    /// <b>Only a review answers.</b> A Model check's, a Standards run's or a remodel run's record
    /// (<see cref="TrackCheck"/>) is not a review: it has no candidate question a confirmation
    /// could have come from, and a remodel folder is the run that writes to a copy.
    ///
    /// <b>An ambiguous id answers null.</b> Two reviews' folders share a name only when a settings
    /// save moved the run root between them, and reading a drawing into the wrong review's package
    /// is worse than refusing. The same folder tracked twice is one folder.
    ///
    /// Asked on the SOLIDWORKS application thread while the page pump may be tracking a run, so it
    /// reads under the list's lock like every other reader here.
    /// </summary>
    public string? ReviewRunDirectory(string? runId)
    {
        if (string.IsNullOrWhiteSpace(runId))
        {
            return null;
        }

        SessionRecord[] matches;
        lock (_sessionsLock)
        {
            matches = _sessions
                .Where(session => !session.IsCheck && session.ChatId != null)
                .Where(session => string.Equals(session.RunId, runId, StringComparison.OrdinalIgnoreCase))
                .ToArray();
        }

        if (matches.Length == 0)
        {
            return null;
        }

        string folder = SameFolder(matches[0].RunDirectory);
        bool ambiguous = matches.Any(session =>
            !string.Equals(SameFolder(session.RunDirectory), folder, StringComparison.OrdinalIgnoreCase));
        return ambiguous ? null : matches[0].RunDirectory;
    }

    /// <summary>A tracked folder without its trailing separator, so one folder spelt two ways is one.</summary>
    private static string SameFolder(string runDirectory) => runDirectory.TrimEnd('\\', '/');

    /// <summary>Whether any chat this host started has a turn in flight.</summary>
    public bool AnyTurnRunning()
    {
        // A snapshot, because this is asked from the tool-service gate's thread while the page
        // pump may be tracking a `review.start` or a Model check: enumerating the live list
        // threw `Collection was modified` out of here, which the gate read as "cannot be asked"
        // and skipped the re-attach for. The round trip below is taken outside the lock - it is
        // the backend's 30-second timeout, and the pump must not queue behind it.
        SessionRecord[] sessions;
        lock (_sessionsLock)
        {
            sessions = _sessions.ToArray();
        }

        foreach (SessionRecord session in sessions)
        {
            // A check has no chat, so there is no chat id to ask the backend about. Skipped
            // explicitly rather than left to the catch below: a fabricated id would appear to
            // work, at the cost of one HTTP round trip per settings save and a record that lies.
            if (session.IsCheck || session.ChatId == null)
            {
                continue;
            }

            try
            {
                if (_options.Backend.IsTurnRunning(session.ChatId))
                {
                    return true;
                }
            }
            catch (Exception)
            {
                // A backend that cannot be asked has no turn worth protecting: refusing every
                // save because the backend is down would leave the engineer unable to fix the
                // settings that are keeping it down.
            }
        }

        return false;
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

                id = Text(root, "id");
                string? type = Text(root, "type");
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
        catch (BackendRequestException failure)
        {
            SendError(id, failure.ErrorClass, failure.Message, failure.Retryable);
        }
        catch (TurnRunningException failure)
        {
            SendError(id, failure.ErrorClass, failure.Message, retryable: true);
        }
        catch (Exception failure)
        {
            SendError(id, "HostError", failure.Message, retryable: false);
        }
    }

    /// <summary>Sends an unsolicited message (`status`, `document.changed`, `backend.stopped`).</summary>
    public void Post(string type, object? payload) => Send(type, null, payload);

    /// <summary>
    /// Tells the page which document the pane is looking at now, or that there is none.
    /// Called by the add-in's active-document notifications (pane-host-messages.md).
    /// </summary>
    public void DocumentChanged() => Post("document.changed", DocumentPayload(_options.CurrentDocument()));

    public void Dispose()
    {
        _events.Dispose();
        lock (_sessionsLock)
        {
            _sessions.Clear();
        }

        LatestSession = null;
    }

    private void Dispatch(string type, string? id, JsonElement payload)
    {
        // The four rows this host shares with every other pane host, answered by the one copy
        // of them (contracts/model-check.md section 2).
        if (_actions.TryHandle(type, id, payload))
        {
            return;
        }

        switch (type)
        {
            case "ready":
                // A page that says `ready` has reloaded: it has no transcript and no stream, so
                // a reader started for the page before it is writing into something that is gone.
                _events.Close();
                SendInit(id);
                return;

            case "events.open":
                OpenEventStream(id, payload);
                return;

            case "events.close":
                _events.Close();
                return;

            case "settings.get":
                SendSettings("settings", id);
                return;

            case "settings.save":
                Save(id, payload);
                return;

            case "models.list":
                ListModels(id, payload);
                return;

            case "review.prepare":
                PrepareReview(id);
                return;

            case "review.start":
                StartReview(id, payload);
                return;

            case "sessions.list":
                SendReviews(id);
                return;

            case "session.forget":
                Forget(id, payload);
                return;

            default:
                SendError(
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
        BackendEndpoint? endpoint = _options.Backend.Endpoint;
        ResolvedApiKey key = _settings.ResolveApiKey(_options.Environment);
        PageDocument? document = _options.CurrentDocument();

        Send("init", id, new Dictionary<string, object?>
        {
            {
                "backend",
                endpoint == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "port", endpoint.Port },

                        // The page's OWN origin under `/__backend`, not the backend's loopback
                        // one: the page never crosses the network boundary, the host serves
                        // that prefix from C# (docs/pane-backend-proxy.md), and the page's CSP
                        // is `connect-src 'self'`. The port stays because the pane still shows
                        // it and a diagnostic still needs it.
                        { "origin", BackendProxy.PageOrigin },
                    }
            },
            { "token", endpoint?.Token },
            { "settings", View(_settings) },
            { "key_source", key.Source },
            { "run_root", _settings.RunRoot },
            { "providers", Providers() },
            { "document", DocumentPayload(document) },
            { "review_preparation", _options.PrepareReview != null },
        });

        ReportSettingsProblems(key);
    }

    private string[] Providers() =>
        _options.BuildMode == BuildMode.Development ? AllProviders : ReleaseProviders;

    // ---- the event stream -----------------------------------------------------------------

    /// <summary>
    /// `events.open`: read this chat's stream in the host and post each frame to the page.
    ///
    /// There is no reply. The page is not waiting for one - what it is waiting for is frames -
    /// and a reader that answered `ok` before the first byte arrived would be saying something
    /// it does not know yet. A refusal is still an `error`, because a page that asked for a
    /// stream and will never get one has to be told.
    /// </summary>
    private void OpenEventStream(string? id, JsonElement payload)
    {
        string? chatId = Blank(Text(payload, "chat_id"));
        if (chatId == null)
        {
            SendError(
                id,
                "InvalidRequest",
                "events.open needs the chat_id of the stream to read.",
                retryable: false);
            return;
        }

        _events.Open(chatId, LastEventId(payload));
    }

    /// <summary>
    /// The `last_event_id` the page sent, as a header value.
    ///
    /// A number as well as a string, because the page's own `seq` is a number and asking it to
    /// stringify one before sending it would be a rule to forget. Zero and below mean "from the
    /// beginning", which is the absence of the header rather than an id of 0.
    /// </summary>
    private static string? LastEventId(JsonElement payload)
    {
        if (payload.ValueKind != JsonValueKind.Object
            || !payload.TryGetProperty("last_event_id", out JsonElement value))
        {
            return null;
        }

        if (value.ValueKind == JsonValueKind.String)
        {
            return Blank(value.GetString());
        }

        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out long seq))
        {
            return seq > 0 ? seq.ToString(CultureInfo.InvariantCulture) : null;
        }

        return null;
    }

    // ---- settings -----------------------------------------------------------------------

    private void SendSettings(string type, string? id)
    {
        ResolvedApiKey key = _settings.ResolveApiKey(_options.Environment);
        Send(type, id, new Dictionary<string, object?>
        {
            { "settings", View(_settings) },
            { "key_source", key.Source },
        });
        ReportSettingsProblems(key);
    }

    private void Save(string? id, JsonElement payload)
    {
        // The headline rule of the contract, checked before anything is parsed or written: a
        // running turn owns process state that is not on disk.
        if (AnyTurnRunning())
        {
            var running = new TurnRunningException();
            SendError(id, running.ErrorClass, running.Message, retryable: true);
            return;
        }

        string provider = (Text(payload, "provider") ?? string.Empty).Trim();
        string model = (Text(payload, "model") ?? string.Empty).Trim();
        string effort = (Text(payload, "effort") ?? string.Empty).Trim();

        if (provider == "fake" && _options.BuildMode == BuildMode.Release)
        {
            SendError(
                id,
                "FakeProviderNotAllowed",
                "provider 'fake' is the scripted development provider: it fabricates findings, so "
                + "a shipped build cannot run with it. Choose openai or gemini.",
                retryable: false);
            return;
        }

        if (!Providers().Contains(provider))
        {
            SendError(
                id,
                "InvalidSettings",
                $"provider '{provider}' is not one of {string.Join(", ", Providers())}",
                retryable: false);
            return;
        }

        if (!Efforts.Contains(effort))
        {
            SendError(
                id,
                "InvalidSettings",
                $"effort '{effort}' is not one of {string.Join(", ", Efforts)}",
                retryable: false);
            return;
        }

        if (model.Length == 0)
        {
            SendError(id, "InvalidSettings", "model must not be blank", retryable: false);
            return;
        }

        string? baseUrl = Blank(Text(payload, "base_url"));
        if (baseUrl != null && provider != "openai")
        {
            // `OPENAI_BASE_URL` is the only endpoint override the backend reads, and only for
            // the openai provider (agent/settings.py `_env_base_url`). Accepting one here,
            // echoing it back in `settings.saved` and then reviewing against the public
            // endpoint would tell the engineer their gateway was in use when it never was.
            SendError(
                id,
                "InvalidSettings",
                $"a base URL can only be set for the openai provider; '{provider}' has no "
                + "endpoint override. Clear the base URL, or switch the provider back.",
                retryable: false);
            return;
        }

        IReadOnlyList<ModelChoice>? offered = TryListModels(provider);
        if (offered != null && offered.Count > 0 && !offered.Any(choice => choice.Id == model))
        {
            // Push the list before the refusal so the picker is already re-rendered when the
            // page shows the error.
            Send("models", null, ModelsPayload(provider, offered));
            SendError(
                id,
                "UnknownModel",
                $"the {provider} provider does not offer a model called '{model}'. "
                + "Pick one from the refreshed list.",
                retryable: false);
            return;
        }

        bool providerChanged = provider != _settings.Provider;

        UserSettings next = Clone(_settings);
        next.Provider = provider;
        next.Model = model;
        next.Effort = effort;
        next.BaseUrl = baseUrl;
        next.GeminiEnterprise = Enterprise(payload);

        // Absent or null means "leave the stored key alone": the page's key box is blank
        // whenever a key is stored, because it can never be shown one, so a save that carries
        // no key must not be a save that deletes it. An empty string is the explicit clear.
        if (payload.ValueKind == JsonValueKind.Object
            && payload.TryGetProperty("api_key", out JsonElement apiKey)
            && apiKey.ValueKind == JsonValueKind.String)
        {
            next.SetApiKey(apiKey.GetString());
        }
        else if (providerChanged)
        {
            // ...unless the provider itself changed. There is one key slot in
            // settings.schema.json, and a key is a credential *for a vendor*: carrying the
            // stored OpenAI key over to a gemini save would put it in GEMINI_API_KEY and send
            // one vendor's secret to the other's endpoint. Since the key box is blank whenever
            // a key is stored, a bare provider switch is the normal case, not an odd one. The
            // key is retired instead, and the reply's `key_source` tells the page to ask for a
            // new one. Saving the new provider *and* its key in one go still works: the page
            // sent an `api_key`, so this branch is not reached.
            next.SetApiKey(null);
        }

        next.Save(_options.SettingsPath);
        _settings = next;
        _settingsError = null;

        ResolvedApiKey key = next.ResolveApiKey(_options.Environment);
        string? restartFailure = null;
        try
        {
            _options.Backend.Restart(next, key);
        }
        catch (TurnRunningException)
        {
            // A turn started between the gate above and here. The settings are already written,
            // so the honest answer is "saved, not yet in force".
            restartFailure = "the settings are saved; the backend restarts when the running turn ends.";
        }
        catch (BackendStartException failure)
        {
            restartFailure = failure.Message;
        }

        SendSettings("settings.saved", id);

        if (restartFailure != null)
        {
            PostStatus("error", restartFailure);
        }
    }

    private void ReportSettingsProblems(ResolvedApiKey key)
    {
        var problems = new List<string>();
        if (!string.IsNullOrEmpty(_settingsError))
        {
            problems.Add(_settingsError!);
        }

        if (!string.IsNullOrEmpty(key.Error))
        {
            problems.Add(key.Error!);
        }

        if (problems.Count == 0)
        {
            return;
        }

        PostStatus("error", string.Join(" ", problems.ToArray()));
    }

    // ---- models -------------------------------------------------------------------------

    private void ListModels(string? id, JsonElement payload)
    {
        string provider = (Text(payload, "provider") ?? _settings.Provider).Trim();
        if (!Providers().Contains(provider))
        {
            SendError(
                id,
                "InvalidSettings",
                $"provider '{provider}' is not one of {string.Join(", ", Providers())}",
                retryable: false);
            return;
        }

        if (_options.Backend.Endpoint == null)
        {
            SendError(
                id,
                "BackendUnavailable",
                "the review backend is not running yet, so the model list cannot be fetched.",
                retryable: true);
            return;
        }

        IReadOnlyList<ModelChoice> models = _options.Backend.ListModels(provider);
        Send("models", id, ModelsPayload(provider, models));
    }

    /// <summary>The provider's models, or null when the provider could not be asked at all.</summary>
    private IReadOnlyList<ModelChoice>? TryListModels(string provider)
    {
        if (_options.Backend.Endpoint == null)
        {
            return null;
        }

        try
        {
            return _options.Backend.ListModels(provider);
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static Dictionary<string, object?> ModelsPayload(
        string provider, IReadOnlyList<ModelChoice> models)
    {
        return new Dictionary<string, object?>
        {
            { "provider", provider },
            {
                "models",
                models.Select(choice => new Dictionary<string, object?>
                {
                    { "id", choice.Id },
                    { "label", choice.Label },
                }).ToArray()
            },
        };
    }

    // ---- the review list (feature 009 User Story 6) -------------------------------------

    /// <summary>
    /// `sessions.list`: every review this host started, in the order tracked, with what its chip
    /// names - `{chat_id, run_id, run_dir, path, configuration, started_at}` - and no check or
    /// remodel record (contracts/sessions.md section 2). `started_at` is ISO 8601 with its offset;
    /// what the host does not know is null rather than invented.
    /// </summary>
    private void SendReviews(string? id)
    {
        Send("sessions", id, new Dictionary<string, object?>
        {
            { "items", Reviews().Select(ReviewItem).ToArray() },
        });
    }

    private static Dictionary<string, object?> ReviewItem(SessionRecord record) =>
        new Dictionary<string, object?>
        {
            { "chat_id", record.ChatId },
            { "run_id", record.RunId },
            { "run_dir", record.RunDirectory },
            { "path", record.Document?.Path },
            { "configuration", record.Document?.Configuration },
            {
                "started_at",
                record.StartedAt?.ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture)
            },
        };

    /// <summary>
    /// `session.forget {chat_id}`: removes that review's record and answers the list without it.
    /// An id this host never recorded - a check record has none - is refused exactly as
    /// `report.open` refuses one, and nothing is removed.
    /// </summary>
    private void Forget(string? id, JsonElement payload)
    {
        string? chatId = Blank(Text(payload, _runs.IdField));
        if (chatId == null)
        {
            SendError(id, "InvalidRequest", $"the message needs a {_runs.IdField}.", retryable: false);
            return;
        }

        if (!ForgetSession(chatId))
        {
            SendError(id, _runs.UnknownErrorClass, _runs.UnknownMessage(chatId), retryable: false);
            return;
        }

        SendReviews(id);
    }

    // ---- review preparation and start ---------------------------------------------------

    /// <summary>
    /// The Review tab's refusal of a drawing (feature 011, contracts/attach.md section 5): a
    /// drawing is not reviewed on its own, and it is read with the part or assembly it documents
    /// for as long as it stays open in SOLIDWORKS (open-drawing discovery). One sentence for the
    /// preparation and the start, so the engineer reads the same words at either step.
    /// </summary>
    internal static string DrawingRefusal(PageDocument document) =>
        $"The Review tab reviews a part or an assembly, and '{System.IO.Path.GetFileName(document.Path)}' "
        + "is a drawing; open the part or assembly it documents - this drawing is read with it "
        + "while it stays open.";

    private void PrepareReview(string? id)
    {
        _preparationId = null;
        _preparedDocument = null;
        PageDocument? document = _options.CurrentDocument();
        if (document != null && document.Kind == "drawing")
        {
            SendError(id, "NoDocument", DrawingRefusal(document), true);
            return;
        }

        if (document == null || !document.IsAttachable)
        {
            SendError(id, "NoDocument", "Open a saved part or assembly to prepare a review.", true);
            return;
        }
        if (_options.PrepareReview == null)
        {
            SendError(id, "NotAttached", "Component preparation is not available in this host.", true);
            return;
        }
        if (AnyTurnRunning())
        {
            SendError(id, "TurnRunning", "Stop the running review before preparing another.", true);
            return;
        }
        PostStatus("preparing", "Reading component availability before the review...");
        ReviewPreparation preparation;
        try
        {
            preparation = _options.PrepareReview();
        }
        catch (Exception failure)
        {
            SendError(id, "PreparationFailed", failure.Message, true);
            return;
        }
        _preparationId = Guid.NewGuid().ToString("N");
        _preparedDocument = preparation.Document;
        Send("review.prepared", id, preparation.Payload(
            _preparationId, !string.IsNullOrWhiteSpace(_settings.StandardsProfilePath)));
        PostStatus("ready", "Component availability checked; no review tokens used.");
    }

    /// <summary>
    /// Press Review: name and create the run folder, dump the open document into it, hand the
    /// folder to the backend, and tell the page which chat it got.
    ///
    /// The order is not negotiable. The refusals come first because extraction is minutes of
    /// SOLIDWORKS time and a review with no document or no backend has nowhere to put it. The
    /// run folder is created before the dump because the dump writes `meshes/` into it. The
    /// session is tracked before the reply, so a `folder.open` that the page sends the instant
    /// it sees `review.started` already has a record to resolve.
    /// </summary>
    private void StartReview(string? id, JsonElement payload)
    {
        PageDocument? document = _options.CurrentDocument();
        if (document == null)
        {
            SendError(
                id,
                "NoDocument",
                "open the assembly or part you want reviewed in SOLIDWORKS first: the evidence "
                + "package is extracted from the active document.",
                retryable: true);
            return;
        }

        // Before the dump, whatever the preparation says: the extraction's attach reads a
        // drawing (feature 011), so the Review tab refuses one here rather than extracting it
        // as the design under review (contracts/attach.md section 3).
        if (document.Kind == "drawing")
        {
            SendError(id, "NoDocument", DrawingRefusal(document), retryable: true);
            return;
        }

        if (_options.PrepareReview != null)
        {
            bool matches = _preparationId != null
                && string.Equals(Text(payload, "preparation_id"), _preparationId, StringComparison.Ordinal)
                && string.Equals(document.Path, _preparedDocument?.Path, StringComparison.OrdinalIgnoreCase)
                && string.Equals(document.Configuration, _preparedDocument?.Configuration, StringComparison.Ordinal);
            _preparationId = null;
            _preparedDocument = null;
            if (!matches)
            {
                SendError(id, "PreparationExpired", "The active document or configuration changed. Check component availability again.", true);
                return;
            }
        }

        if (_options.Dump == null)
        {
            SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so nothing can be extracted.",
                retryable: true);
            return;
        }

        if (_options.Backend.Endpoint == null)
        {
            SendError(
                id,
                "BackendUnavailable",
                "the review backend is not running yet, so there is nowhere to send the review. "
                + "Check the log, then press Review again.",
                retryable: true);
            return;
        }

        string runDirectory;
        try
        {
            runDirectory = RunFolders.CreateForDocument(_settings.RunRoot, document.Path, _options.Now());
        }
        catch (Exception failure)
        {
            PostStatus("error", failure.Message);
            SendError(
                id,
                "RunFolderFailed",
                $"the run folder could not be created under '{_settings.RunRoot}': {failure.Message}",
                retryable: false);
            return;
        }

        DumpSummary summary;
        // "evidence", not "IR" and not the bare document name: this is the first line the page
        // shows after Review is pressed, and it is where an engineer learns what the pane
        // writes before it reads anything (the Extract tab's button says the same word).
        PostStatus(
            "extracting", $"Extracting evidence from {RunFolders.DocumentName(document.Path)}...");
        try
        {
            summary = _options.Dump.Run(runDirectory, message => PostStatus("extracting", message));
        }
        catch (Exception failure)
        {
            // The folder is left behind on purpose: whatever the dump did write is the
            // evidence for why it stopped (constitution Principle I).
            PostStatus("error", failure.Message);
            SendError(id, "ExtractionFailed", failure.Message, retryable: true);
            return;
        }

        ChatSessionHandle handle;
        try
        {
            handle = _options.Backend.CreateSession(new NewSessionRequest(
                runDirectory,
                _settings.Provider,
                _settings.Model,
                _settings.Effort,
                _options.Engineer,
                _options.Bridge,
                // FR-028: the page's Retry on an error card starts a fresh chat that says
                // which one it is replacing, so the pair can be read back in the run folder.
                Blank(Text(payload, "retry_of")),
                Blank(_settings.StandardsProfilePath)));
        }
        catch (Exception failure)
        {
            PostStatus("error", failure.Message);

            // Rethrown rather than answered here: `Receive` maps a BackendRequestException to
            // the backend's own `error_class`, which is the one the page acts on.
            throw;
        }

        // The document captured before the dump, and the moment the review was tracked: what its
        // chip in the pane names (feature 009 FR-020).
        TrackSession(handle.ChatId, runDirectory, document, new DateTimeOffset(_options.Now()));

        PostStatus("ready", ReadyMessage(summary.Components, summary.Gaps, summary.Unexamined));

        // `document` is the one captured before the dump, not whichever is active now: the
        // review is of what was extracted, and the page binds what it shows to this (U8).
        Send("review.started", id, new Dictionary<string, object?>
        {
            { "chat_id", handle.ChatId },
            { "run_dir", runDirectory },
            { "not_examined", handle.NotExamined },
            { "document", DocumentPayload(document) },
        });
    }

    // ---- plumbing -----------------------------------------------------------------------

    /// <summary>
    /// Posts one `status` message with the key masked out of it.
    ///
    /// Public because the add-in reports the backend start through it. That path is the one
    /// that can carry a key: `BackendProcess` redacts the `BackendStartException` it raises,
    /// but a job-object failure, a key-resolution failure or anything thrown before that
    /// wrapper arrives at the caller verbatim, and the caller has no way to mask it - the
    /// settings, and therefore the secret, live here. One choke point rather than a rule every
    /// call site has to remember (FR-015).
    /// </summary>
    public void PostStatus(string stage, string message) => _actions.PostStatus(stage, message);

    /// <summary>
    /// The ready status a review posts once the dump and the chat session both exist: the
    /// component count and any gaps. The full not-examined sentence travels on the
    /// <c>review.started</c> payload so it can wrap in the Review page's warning block instead
    /// of being clipped inside the header badge.
    /// </summary>
    internal static string ReadyMessage(int components, int gaps, int? unexamined)
    {
        string message = $"Reviewing {components} components";
        return gaps == 0 ? $"{message}." : $"{message} ({gaps} gaps).";
    }

    private static Dictionary<string, object?>? DocumentPayload(PageDocument? document) =>
        document == null
            ? null
            : new Dictionary<string, object?>
            {
                { "path", document.Path },
                { "configuration", document.Configuration },
            };

    /// <summary>
    /// The settings as the page may see them: an explicit allow-list, so no field added to the
    /// settings file later can start being echoed by accident. `api_key_protected` is absent.
    /// </summary>
    private static Dictionary<string, object?> View(UserSettings settings)
    {
        return new Dictionary<string, object?>
        {
            { "version", settings.Version },
            { "provider", settings.Provider },
            { "model", settings.Model },
            { "effort", settings.Effort },
            { "base_url", settings.BaseUrl },
            {
                "gemini_enterprise",
                settings.GeminiEnterprise == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "project", settings.GeminiEnterprise.Project },
                        { "location", settings.GeminiEnterprise.Location },
                    }
            },
            { "terminal_cli", settings.TerminalCli },
            { "python", settings.Python },
            { "run_root", settings.RunRoot },
        };
    }

    private static UserSettings Clone(UserSettings settings)
    {
        // Through the contract's own JSON, so a clone can never carry a field the file cannot.
        // The save is applied to the clone: a failed write must not leave the pane believing
        // settings it did not persist.
        return JsonSerializer.Deserialize<UserSettings>(settings.ToJson())
            ?? UserSettings.Defaults();
    }

    private static GeminiEnterpriseSettings? Enterprise(JsonElement payload)
    {
        if (payload.ValueKind != JsonValueKind.Object
            || !payload.TryGetProperty("gemini_enterprise", out JsonElement enterprise)
            || enterprise.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        string project = Text(enterprise, "project") ?? string.Empty;
        string location = Text(enterprise, "location") ?? string.Empty;
        if (project.Trim().Length == 0 || location.Trim().Length == 0)
        {
            // Half-configured enterprise settings fail inside the SDK on the first call, a long
            // way from the pane that accepted them.
            return null;
        }

        return new GeminiEnterpriseSettings { Project = project.Trim(), Location = location.Trim() };
    }

    private static string? Text(JsonElement element, string name) =>
        PagePayload.Text(element, name);

    private static string? Blank(string? value) => PagePayload.Blank(value);

    private void SendError(string? id, string errorClass, string message, bool retryable) =>
        _actions.SendError(id, errorClass, message, retryable);

    private void Send(string type, string? id, object? payload) =>
        _actions.Send(type, id, payload);

    /// <summary>
    /// Masks the configured key in anything headed for the page or the log (FR-015).
    ///
    /// Public for the same reason as <see cref="PostStatus"/>, and for one caller in
    /// particular: the add-in's `addin.log` line is written from `Exception.ToString()`, which
    /// carries every inner exception's message - and the inner exception is exactly where the
    /// unredacted launcher failure sits, because `BackendProcess` masks only the outer one.
    /// </summary>
    public string Redact(string text) => _actions.Redact(text);
}
