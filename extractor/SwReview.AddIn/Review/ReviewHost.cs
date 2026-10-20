using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using SwReview.AddIn.EngineeringContext;
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

    /// <summary>
    /// Whether <paramref name="path"/> and <paramref name="configuration"/> name this document:
    /// the path compared ignoring case, as Windows names one file however it is spelled, and
    /// the configuration exactly, as SOLIDWORKS names configurations (feature 015). The one rule
    /// a re-run's binding and the search for a review never sent both use.
    /// </summary>
    public bool IsSameDocument(string? path, string? configuration) =>
        string.Equals(path, Path, StringComparison.OrdinalIgnoreCase)
        && string.Equals(configuration, Configuration, StringComparison.Ordinal);

    /// <summary><see cref="IsSameDocument(string?, string?)"/> of another document; never null.</summary>
    public bool IsSameDocument(PageDocument? other) =>
        other != null && IsSameDocument(other.Path, other.Configuration);
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
    /// <summary>The last <see cref="Sequence"/> given out, across every record of the process.</summary>
    private static long _lastSequence;

    private SessionRecord(
        string? chatId, string runDirectory, bool isCheck, PageDocument? document, DateTimeOffset? startedAt)
    {
        ChatId = chatId;
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        IsCheck = isCheck;
        Document = document;
        StartedAt = startedAt;
        Sequence = Interlocked.Increment(ref _lastSequence);
        ConfirmedDrawings = new Extractor.Dump.ConfirmedDrawingSession(RunDirectory);
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

    /// <summary>Set while this record has not been sent to the model.</summary>
    public string? ModelStatus { get; set; }

    /// <summary>
    /// Feature 016's saved context this review was started with, or null for an ordinary review:
    /// what a Retry of it re-attaches in its own folder (owner decision 108A).
    /// </summary>
    public EngineeringContextAttachment? EngineeringContext { get; set; }

    /// <summary>The extraction a context review was started on, for a Retry's ready status.</summary>
    public DumpSummary? ContextExtraction { get; set; }

    /// <summary>
    /// Feature 011, decision 141A (2026-10-19): what the confirmed drawing read keeps for this
    /// review session - its run folder and the opens it attempted that left no drawing record. Each
    /// record has its own, so a Retry or Recheck in the same run folder, which is a new record,
    /// starts its own count, and the count goes when the record does. A <c>drawing.read</c> reaches
    /// it only through <see cref="ReviewHost.DrawingReadSession"/>.
    /// </summary>
    public Extractor.Dump.ConfirmedDrawingSession ConfirmedDrawings { get; }

    /// <summary>
    /// The order this record was made in among every record of the process (decision 141A): the
    /// latest of a run folder's reviews is the session a <c>drawing.read</c> belongs to, also when a
    /// Recheck put it in an earlier record's place in the list.
    /// </summary>
    internal long Sequence { get; }

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

    /// <summary>The bounded session head opener; null uses the shared replace-safe opener.</summary>
    public Func<string, Stream>? OpenSessionHead { get; set; }

    /// <summary>Read only the component census before a paid review; no run folder or model call.</summary>
    public Func<ReviewPreparation>? PrepareReview { get; set; }

    /// <summary>
    /// U25 (default taken 2026-09-28, the owner may revise): the models the open drawing at the
    /// given path shows, once each, in sheet-then-view order - read-only, through a gate, on the
    /// application thread - or null when they cannot be read. Asked only for a drawing, and only
    /// to name its model in the one sentence the Review tab gives a drawing
    /// (<see cref="ReviewHost.DrawingSentence"/>). Null: no reader, and the sentence names none.
    /// </summary>
    public Func<string, IReadOnlyList<string>?>? DrawingModels { get; set; }

    /// <summary>
    /// The in-process extractor. Null until the add-in is attached to a SOLIDWORKS session,
    /// which is a state the pane really has: the Task Pane exists before the first document.
    /// </summary>
    public IReviewDump? Dump { get; set; }

    /// <summary>Read-only selection prefill against prepared saved evidence; never freshness proof.</summary>
    public IEngineeringSelectionCapture? EngineeringSelection { get; set; }

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

    /// <summary>
    /// How often the host asks whether the turn a settings restart waits for has ended (owner
    /// decision 143A). A second: it bounds only how long the backend keeps the old settings with
    /// nothing running, since a new review makes the restart itself and a page call that would
    /// start a turn is not sent to the old backend; and it costs one `GET /sessions/{chat_id}` per
    /// review per poll, and only while a restart waits.
    /// </summary>
    public TimeSpan RestartPoll { get; set; } = TimeSpan.FromSeconds(1);

    /// <summary>
    /// Whether the backend is busy with work other than a review turn that a restart would end -
    /// a remodel run (feature 004) - asked before the turns are asked of the backend, whenever a
    /// restart for settings saved during a turn looks at what holds it back (owner decision 143A),
    /// and again under the restart's own lock by every restart, a save's made at once included
    /// (owner decision 145A). Read under that lock, so it must be quick and must not block. False
    /// when the caller has none.
    /// </summary>
    public Func<bool> BackendBusy { get; set; } = () => false;

    /// <summary>
    /// Tells every other tab that holds the backend's port and token - Model check, Standards and
    /// Remodel - that the backend was restarted with saved settings, so each asks for its `init`
    /// again (owner decision 145A). Called after every restart this host makes, a save's made at
    /// once or one made after it waited, and never after one that failed; the Review page is told
    /// by the save's reply or by `backend.restarted`. Nothing when the caller has no other tab.
    /// </summary>
    public Action BackendRestarted { get; set; } = () => { };

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
/// written and the backend is not restarted (chat-api.md). The one exception is a turn that
/// starts after that check and before the restart, which the backend refuses with the file
/// already written: the restart then waits until nothing holds it back, and a new review waits
/// for the restart rather than running on the old backend (owner decision 143A,
/// <see cref="DeferredRestart"/>). A remodel run is treated as a turn (owner decision 145A): a
/// save made during one is kept and its restart waits for the run, and a run begins only once no
/// restart waits (<see cref="BeginRemodelRun"/>).
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
/// (docs/history/pane-findings-2026-09-16.md, finding 1). So the list is guarded by its own lock, and
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

    /// <summary>
    /// The run folders of reviews the engineer removed (the chip's Remove), as
    /// <see cref="SameFolder"/> spells them and compared ignoring case. Kept for the SOLIDWORKS
    /// session, like the records, so the search never offers a removed review again (feature
    /// 015, owner decision 98A item 4). Guarded by <see cref="_sessionsLock"/>.
    /// </summary>
    private readonly HashSet<string> _forgottenFolders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
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

    /// <summary>
    /// The backend restart a save could not make because a turn had started, made once no turn
    /// runs (owner decision 143A). Every restart this host makes goes through it, so two never
    /// overlap and the one made last reads the settings saved last.
    /// </summary>
    private readonly DeferredRestart _restart;

    private UserSettings _settings;
    private string? _settingsError;
    private PreparedContext? _preparedContext;
    private long _contextGeneration;

    private sealed class PreparedContext
    {
        public PreparedContext(string directory, string sha256, PageDocument document, long generation, DumpSummary summary)
        { Directory = directory; Sha256 = sha256; Document = document; Generation = generation; Summary = summary; }
        public string Directory { get; }
        public string RunId => Path.GetFileName(Directory);
        public string Sha256 { get; }
        public PageDocument Document { get; }
        public long Generation { get; }
        /// <summary>The extraction's counts, for the ready status of a review of this package.</summary>
        public DumpSummary Summary { get; }
    }

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

        _restart = new DeferredRestart(
            RestartHeldBack,
            RemodelRunInProgress,
            RestartWithSettingsInForce,
            () =>
            {
                _actions.PostBackendRestarted(RestartSentences);
                TellTheOtherTabs();
            },
            failure => PostStatus("error", failure.Message),
            () => PostStatus("error", RestartNotAnswered),
            options.RestartPoll);
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
    public void TrackSession(string chatId, string runDirectory, PageDocument? document, DateTimeOffset? startedAt) =>
        TrackSession(chatId, runDirectory, document, startedAt, null);

    /// <summary>Publishes the review with its model mark already set. A check pump may make
    /// another record latest immediately afterward, so metadata belongs to this record.</summary>
    public void TrackSession(
        string chatId, string runDirectory, PageDocument? document, DateTimeOffset? startedAt, string? modelStatus)
    {
        if (chatId == null)
        {
            throw new ArgumentNullException(nameof(chatId));
        }

        Publish(new SessionRecord(chatId, runDirectory, document, startedAt) { ModelStatus = modelStatus }, makeLatest: true);
    }

    /// <summary>
    /// Tracks <paramref name="record"/>, and when <paramref name="makeLatest"/> makes it the
    /// latest run. With <paramref name="replacing"/> still tracked, the record takes its place in
    /// the list (a re-run, feature 015); otherwise any record of the same chat id is dropped and
    /// this one appended. A review the search found is not made latest (owner decision 98A item
    /// 3): the check tabs' Show and the Ask tab's folder read <see cref="LatestSession"/>, and a
    /// search the page runs on every document change must not move them to another document.
    /// </summary>
    private void Publish(SessionRecord record, bool makeLatest, SessionRecord? replacing = null)
    {
        lock (_sessionsLock)
        {
            int index = replacing == null ? -1 : _sessions.IndexOf(replacing);
            if (index >= 0)
            {
                _sessions[index] = record;
            }
            else
            {
                _sessions.RemoveAll(session => session.ChatId == record.ChatId);
                _sessions.Add(record);
            }
        }

        if (makeLatest)
        {
            LatestSession = record;
        }
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
    /// a record that is gone. Its run folder is remembered, so the search does not find it again
    /// (owner decision 98A item 4). Answers whether there was such a review.
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
            _forgottenFolders.Add(SameFolder(record.RunDirectory));
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

    /// <summary>
    /// Feature 011, decision 141A (2026-10-19): the review session a <c>drawing.read</c> naming
    /// <paramref name="runId"/> belongs to, as the confirmed read keeps it, or null. The folder is
    /// <see cref="ReviewRunDirectory"/>'s, by every rule it keeps; the session is the latest review
    /// this host started in that folder and still tracks - a Recheck's, or a context review's
    /// Retry's, once one has started there - since a new session in a folder takes over its reads
    /// from the earlier one, which a context review's Retry leaves tracked beside it. Each record
    /// holds its own (<see cref="SessionRecord.ConfirmedDrawings"/>), so a new session starts its own
    /// count of failed opens, and nothing a request supplies but the run id resolved here chooses or
    /// makes one. Asked on the SOLIDWORKS application thread, through the list's lock like the lookup.
    /// </summary>
    public Extractor.Dump.ConfirmedDrawingSession? DrawingReadSession(string? runId)
    {
        string? folder = ReviewRunDirectory(runId);
        if (folder == null)
        {
            return null;
        }

        string same = SameFolder(folder);
        return Reviews()
            .Where(review => string.Equals(SameFolder(review.RunDirectory), same, StringComparison.OrdinalIgnoreCase))
            .OrderBy(review => review.Sequence)
            .LastOrDefault()
            ?.ConfirmedDrawings;
    }

    /// <summary>What the backend says of the turns of the chats this host started.</summary>
    private enum TurnsSeen
    {
        /// <summary>No chat has a turn running, by every answer the backend gave.</summary>
        None,

        /// <summary>A chat has a turn running.</summary>
        Running,

        /// <summary>
        /// No chat was seen running, and of one at least the backend gave no answer that rules a
        /// turn out (<see cref="RulesOutATurn"/>).
        /// </summary>
        NoAnswer,
    }

    /// <summary>
    /// Whether any chat this host started has a turn in flight. A chat the backend gives no usable
    /// answer about counts as none here: refusing every save because the backend is down would
    /// leave the engineer unable to fix the settings that are keeping it down.
    /// </summary>
    public bool AnyTurnRunning() => LookAtTheTurns(stopAtNoAnswer: false) == TurnsSeen.Running;

    /// <param name="stopAtNoAnswer">Stop at the first chat the backend gives no usable answer
    /// about, as the restart for saved settings does (owner decision 143A): such a chat holds it
    /// back whatever the other chats say, and its look must cost one round trip's timeout, not one
    /// per chat.</param>
    private TurnsSeen LookAtTheTurns(bool stopAtNoAnswer)
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

        bool unanswered = false;
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
                    return TurnsSeen.Running;
                }
            }
            catch (BackendRequestException refusal) when (RulesOutATurn(refusal))
            {
                // No turn of this chat runs here: the backend does not hold it, or could not.
            }
            catch (Exception)
            {
                // No usable answer: none at all - the connection was refused, reset or timed out,
                // or the reply broke off - or one that rules nothing out.
                if (stopAtNoAnswer)
                {
                    return TurnsSeen.NoAnswer;
                }

                unanswered = true;
            }
        }

        return unanswered ? TurnsSeen.NoAnswer : TurnsSeen.None;
    }

    /// <summary>
    /// The refusals of `GET /sessions/{chat_id}` that rule a turn out, besides a readable state:
    /// 404 `UnknownChat`, a chat this backend does not hold - one found on disk, or one an earlier
    /// backend held - and 400 `InvalidRequest`, an id it could not hold. Every other answer - a
    /// 5xx, a body that is not the backend's own, any other refusal - says nothing of the turn,
    /// and neither does no answer at all (owner decision 143A).
    /// </summary>
    private static bool RulesOutATurn(BackendRequestException refusal) =>
        (refusal.Status == 404 && refusal.ErrorClass == "UnknownChat")
        || (refusal.Status == 400 && refusal.ErrorClass == "InvalidRequest");

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
    public void DocumentChanged()
    {
        ExpirePreparedContext();
        Post("document.changed", DocumentPayload(_options.CurrentDocument()));
    }

    public void Dispose()
    {
        // First, so nothing asks the backend about a turn or restarts it once the host is going.
        _restart.Dispose();
        _events.Dispose();
        lock (_sessionsLock)
        {
            _sessions.Clear();
            _forgottenFolders.Clear();
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

            case "send_when_checked.save":
                SaveSendWhenChecked(id, payload);
                return;

            case "settings.save":
                Save(id, payload);
                return;

            case "models.list":
                ListModels(id, payload);
                return;

            case "context.prepare":
                PrepareContext(id);
                return;

            case "context.selection":
                CaptureContextSelection(id, payload);
                return;

            case "context.review":
                ReviewContext(id, payload);
                return;

            case "review.prepare":
                PrepareReview(id);
                return;

            case "review.start":
                StartReview(id, payload);
                return;

            case "review.recheck":
                RecheckReview(id, payload);
                return;

            case "sessions.list":
                FindNotSentReview();
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
            { "engineering_context", _options.Dump != null },
            { "engineering_selection", _options.EngineeringSelection != null },
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

        if (!PersistSettings(next, id))
        {
            return;
        }

        ResolvedApiKey key = next.ResolveApiKey(_options.Environment);
        string? restartFailure = null;
        try
        {
            if (!_restart.Now(() => _options.Backend.Restart(next, key), out DeferredRestart.Hold waitsFor))
            {
                // A turn started between the gate above and here, or a remodel run is in progress,
                // which the restart would end. The settings are already written, so the honest
                // answer is "saved, not yet in force" - and the restart waits for what holds it
                // back rather than being dropped, and the sentence names it (owner decisions 143A
                // and 145A).
                restartFailure = Promise(waitsFor);
            }
            else
            {
                // The Review page learns of it from the reply; the other tabs from this.
                TellTheOtherTabs();
            }
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

    private void SaveSendWhenChecked(string? id, JsonElement payload)
    {
        bool? value = PagePayload.Flag(payload, "send_when_checked");
        if (!value.HasValue)
        {
            SendError(id, "InvalidRequest", "send_when_checked must be true or false", retryable: false);
            return;
        }
        UserSettings next = Clone(_settings);
        next.SendsWhenChecked = value.Value;
        if (PersistSettings(next, id))
        {
            Send("send_when_checked.saved", id, new { send_when_checked = next.SendsWhenChecked });
        }
    }

    private bool PersistSettings(UserSettings next, string? id)
    {
        try
        {
            next.Save(_options.SettingsPath);
        }
        catch (Exception failure)
        {
            SendError(id, "SettingNotSaved", failure.Message, retryable: false);
            return false;
        }
        _settings = next;
        _settingsError = null;
        return true;
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

    // ---- a restart for settings saved during a turn or a remodel run (143A, 145A) ----------

    /// <summary>
    /// The Review tab's sentence for a save a turn started during: the settings are written and in
    /// force in the host, and the backend is restarted with them once nothing holds it back.
    /// </summary>
    private const string RestartPromise =
        "the settings are saved; the backend restarts when the running turn ends.";

    /// <summary>
    /// ...for a save made while a remodel run is in progress, which the restart would end with its
    /// copy half changed, so the restart waits for the run (owner decision 145A).
    /// </summary>
    private const string RemodelRunPromise =
        "the settings are saved; the backend restarts when the remodel run ends.";

    /// <summary>...for one made during a remodel run that a turn also started during, so it waits for both.</summary>
    private const string TurnAndRemodelRunPromise =
        "the settings are saved; the backend restarts when the running turn and the remodel run end.";

    /// <summary>
    /// What the page is told when the watcher stops looking at a backend that does not answer
    /// (<see cref="DeferredRestart.UnansweredLooks"/>): the restart has not been made, it still
    /// waits for the next review, follow-up or remodel run, and a save made now - which asks
    /// whether a turn runs leniently - restarts the backend. "The saved settings", since owner
    /// decision 145A: a save made during a remodel run was not made during a turn. Saving again is
    /// still the way on, because the watcher reads a remodel run before the turns, so it says this
    /// only once no run holds the restart, and no run can begin while the backend gives no answer.
    /// </summary>
    private const string RestartNotAnswered =
        "the review backend is not answering, so it has not been restarted with the saved settings yet. "
        + "It will be before the next review, follow-up or remodel run, once it answers; to restart it "
        + "now, save the settings again.";

    /// <summary>
    /// The host's sentences about a restart that waits, as `backend.restarted` carries them once it
    /// is made: the page takes whichever of them is on its banner off it, and nothing else there.
    /// </summary>
    private static readonly string[] RestartSentences =
        { RestartPromise, RemodelRunPromise, TurnAndRemodelRunPromise, RestartNotAnswered };

    /// <summary>
    /// The sentence for a save whose restart waits, naming what it waits for (owner decision 145A):
    /// a turn that started during the save, which the backend's own check found; a remodel run in
    /// progress; or both - a remodel run, and a turn that started during the save, which is asked
    /// of the backend now, since the run was read before the backend's own check could be reached.
    /// A backend that gives no answer about a chat is no turn here: the sentence names the run, and
    /// the watcher says, once the run is over, if the backend still does not answer.
    /// </summary>
    private string Promise(DeferredRestart.Hold waitsFor)
    {
        if (waitsFor != DeferredRestart.Hold.RemodelRun)
        {
            return RestartPromise;
        }

        return LookAtTheTurns(stopAtNoAnswer: true) == TurnsSeen.Running
            ? TurnAndRemodelRunPromise
            : RemodelRunPromise;
    }

    /// <summary>A new review, or a page call that would start a turn, while a turn holds the restart back.</summary>
    private const string TurnHoldsTheRestart =
        "the backend restarts with the saved settings when the running turn ends, and nothing new starts "
        + "before then. Wait for the turn to end, or press Stop, then try again.";

    /// <summary>...while a remodel run holds it back.</summary>
    private const string RemodelRunHoldsTheRestart =
        "the backend restarts with the saved settings when the remodel run ends, and nothing new starts "
        + "before then. Wait for the run to end, then try again.";

    /// <summary>...while the backend does not answer whether a turn runs.</summary>
    private const string NoAnswerHoldsTheRestart =
        "the review backend did not answer whether a turn is running, so it has not been restarted with "
        + "the saved settings, and nothing new starts before then. Save the settings again to restart "
        + "it, then try again.";

    /// <summary>
    /// A remodel run - a plan or a Start - refused while a turn holds the restart back (owner
    /// decision 145A). On the Remodel tab, whose own Stop stops the run, so it names the Review
    /// tab's, which stops the turn.
    /// </summary>
    private const string TurnHoldsTheRemodelRun =
        "the backend restarts with the saved settings when the running review turn ends, and no remodel run "
        + "starts before then. Wait for the turn to end, or press Stop on the Review tab, then try again.";

    /// <summary>...while the backend does not answer whether a turn runs; the settings are saved on the Review tab.</summary>
    private const string NoAnswerHoldsTheRemodelRun =
        "the review backend did not answer whether a turn is running, so it has not been restarted with the "
        + "saved settings, and no remodel run starts before then. Save the settings again on the Review tab "
        + "to restart it, then try again.";

    /// <summary>
    /// Whether a remodel run is in progress (<see cref="ReviewHostOptions.BackendBusy"/>), which a
    /// restart would end with its copy half changed. One reading for the restart's look and for its
    /// check under its own lock (owner decision 145A). Not knowing whether a run is in progress is
    /// not knowing that none is.
    /// </summary>
    private bool RemodelRunInProgress()
    {
        try
        {
            return _options.BackendBusy();
        }
        catch (Exception)
        {
            return true;
        }
    }

    /// <summary>
    /// What holds the restart back. Read in the order the add-in can know it: no backend process
    /// at all holds nothing - the restart is what brings one back; then a remodel run in progress,
    /// which the restart would end with its copy half changed, and which the add-in knows without
    /// asking the backend; then the turns, asked of the backend: a turn running, or a backend that
    /// gave no answer, since not knowing whether a turn runs is not knowing that none does. The
    /// remodel run is read again under the restart's own lock, after this look (owner decision
    /// 145A), so one still in progress holds the restart back even with no backend: it cannot
    /// last, since every call it makes then fails.
    /// </summary>
    private DeferredRestart.Hold RestartHeldBack()
    {
        if (_options.Backend.Endpoint == null)
        {
            return DeferredRestart.Hold.None;
        }

        if (RemodelRunInProgress())
        {
            return DeferredRestart.Hold.RemodelRun;
        }

        switch (LookAtTheTurns(stopAtNoAnswer: true))
        {
            case TurnsSeen.Running:
                return DeferredRestart.Hold.Turn;

            case TurnsSeen.NoAnswer:
                return DeferredRestart.Hold.NoAnswer;

            default:
                return DeferredRestart.Hold.None;
        }
    }

    /// <summary>
    /// The restart <see cref="_restart"/> makes once nothing holds it back: the settings in force
    /// now - the last ones saved, however many saves the turn saw - with the key resolved from them
    /// now, so the backend is started with that provider's key and names it as the saved key's
    /// provider (owner decision 138A).
    /// </summary>
    private void RestartWithSettingsInForce()
    {
        UserSettings settings = _settings;
        _options.Backend.Restart(settings, settings.ResolveApiKey(_options.Environment));
    }

    /// <summary>
    /// Tells every other tab that holds the backend's port and token that this host has just
    /// restarted the backend (owner decision 145A, <see cref="ReviewHostOptions.BackendRestarted"/>).
    /// Never throws: a tab that cannot be told must not turn a restart that was made into a save
    /// answered with an error, or into a restart reported as failed.
    /// </summary>
    private void TellTheOtherTabs()
    {
        try
        {
            _options.BackendRestarted();
        }
        catch (Exception)
        {
            // Each host's post swallows its own failures; this guards anything else the add-in does.
        }
    }

    /// <summary>
    /// The refusal for what holds the restart back, or null when nothing does: the error class
    /// whose next step is true of it, the words for it, and the flag the backend gives a call it
    /// refuses for such a reason - its `TurnRunning` is not retryable (chat/server.py), a remodel
    /// run is answered as a turn is, and a backend that does not answer as the proxy answers one
    /// that is not there.
    /// </summary>
    private static BackendRequestException? HeldBackBy(DeferredRestart.Outcome outcome)
    {
        switch (outcome)
        {
            case DeferredRestart.Outcome.TurnRunning:
                return new BackendRequestException("TurnRunning", TurnHoldsTheRestart, retryable: false);

            case DeferredRestart.Outcome.RemodelRunning:
                return new BackendRequestException("RemodelRunning", RemodelRunHoldsTheRestart, retryable: false);

            case DeferredRestart.Outcome.NotAnswered:
                return new BackendRequestException("BackendUnavailable", NoAnswerHoldsTheRestart, retryable: true);

            default:
                return null;
        }
    }

    /// <summary>
    /// Makes the restart that settings saved during a turn wait for before a new review uses the
    /// backend, or waits for the one being made, so the review runs on the restarted backend
    /// with those settings and never on the old one. Answers false, having sent the refusal, when
    /// it cannot: something still holds the restart back, and the refusal says what; or the
    /// restart failed - this call's, or the one it waited for - which has been reported as a
    /// failed start is, and is this review's answer too. True when nothing waits, or once the
    /// restart has been made.
    /// </summary>
    private bool RestartedForNewReview(string? id)
    {
        DeferredRestart.Outcome outcome = _restart.Apply(out Exception? failure);
        BackendRequestException? held = HeldBackBy(outcome);
        if (held != null)
        {
            // Retryable, as this host's other refusals of a review are: it can be pressed again
            // once what holds it back has ended.
            SendError(id, held.ErrorClass, held.Message, retryable: true);
            return false;
        }

        if (outcome == DeferredRestart.Outcome.Failed)
        {
            SendError(id, "BackendUnavailable", failure!.Message, retryable: true);
            return false;
        }

        return true;
    }

    /// <summary>
    /// What a page call that would start a turn is answered with once the restart has ended the
    /// chat it was for.
    /// </summary>
    private const string ChatEndedWithTheRestart =
        "the backend restarted with the saved settings, and this review's chat ended with the backend "
        + "it ran on. Press Review to review again with the new settings.";

    /// <summary>
    /// The pane proxy's question (owner decision 143A): what a page call that would start a turn
    /// - a follow-up, an answer, a Send - is answered with while the backend waits to be
    /// restarted with settings saved during a turn, or null to send it on as always. Such a call
    /// is for a chat of the backend being replaced, so it is never sent: while something holds
    /// the restart back it is refused, saying what; otherwise the restart is made first, or
    /// waited for. Once one has been made the call is answered `UnknownChat` - the class, status
    /// and flag the restarted backend would answer it with, since that backend does not hold the
    /// chat - in words that say why; when the restart failed, made by this call or by the one it
    /// waited for, the call is answered with that failure, the old backend perhaps still up and
    /// holding its chat. Never throws, and asks nothing when nothing waits.
    /// </summary>
    public BackendRequestException? PageTurnRefusal()
    {
        DeferredRestart.Outcome outcome = _restart.Apply(out Exception? failure);
        BackendRequestException? held = HeldBackBy(outcome);
        if (held != null)
        {
            return held;
        }

        switch (outcome)
        {
            case DeferredRestart.Outcome.NotPending:
                return null;

            case DeferredRestart.Outcome.Restarted:
            case DeferredRestart.Outcome.RestartedMeanwhile:
                // The backend the call was for has gone, and the chat with it.
                return new BackendRequestException("UnknownChat", ChatEndedWithTheRestart, retryable: false);

            case DeferredRestart.Outcome.Failed:
                return new BackendRequestException("BackendUnavailable", Redact(failure!.Message), retryable: true);

            default:
                // Stopped: the add-in is unloading, and its backend with it.
                return new BackendRequestException(
                    "BackendUnavailable", "the review backend is stopping with the add-in.", retryable: false);
        }
    }

    /// <summary>
    /// Owner decision 145A: the gate a remodel run - a plan or a Start - begins through, from the
    /// Remodel page's own pump, so that it is treated as a turn. A settings restart that waits is
    /// made first, as a new review makes it, or the one being made is waited for - a save's made at
    /// once included - and then <paramref name="begin"/>, which marks the run in progress, runs
    /// under the restart's own lock (<see cref="DeferredRestart.Begin"/>): no restart can begin
    /// under the run, and none is under way when it begins, so the run never meets a backend that
    /// is going, nor runs on the old one with settings saved since.
    ///
    /// Null once <paramref name="begin"/> has run. Otherwise the refusal, and it has not run: while
    /// something holds the restart back, what - a turn (`TurnRunning`), a backend that does not
    /// answer (`BackendUnavailable`), or a remodel run (`RemodelRunning`), which only a reading that
    /// throws can give, since the Remodel host refuses a second run itself - in words for the
    /// Remodel tab; the failure of the restart this call made or waited for (`BackendUnavailable`),
    /// masked; or the add-in unloading. Retryable, as this host's refusals of a review are, except
    /// the last. Throws only what <paramref name="begin"/> throws.
    /// </summary>
    public BackendRequestException? BeginRemodelRun(Action begin)
    {
        DeferredRestart.Outcome outcome = _restart.Begin(begin, out Exception? failure);
        switch (outcome)
        {
            case DeferredRestart.Outcome.NotPending:
            case DeferredRestart.Outcome.Restarted:
            case DeferredRestart.Outcome.RestartedMeanwhile:
                return null;

            case DeferredRestart.Outcome.TurnRunning:
                return new BackendRequestException("TurnRunning", TurnHoldsTheRemodelRun, retryable: true);

            case DeferredRestart.Outcome.RemodelRunning:
                return new BackendRequestException("RemodelRunning", RemodelRunHoldsTheRestart, retryable: true);

            case DeferredRestart.Outcome.NotAnswered:
                return new BackendRequestException("BackendUnavailable", NoAnswerHoldsTheRemodelRun, retryable: true);

            case DeferredRestart.Outcome.Failed:
                return new BackendRequestException("BackendUnavailable", Redact(failure!.Message), retryable: true);

            default:
                // Stopped: the add-in is unloading, and its backend with it.
                return new BackendRequestException(
                    "BackendUnavailable", "the review backend is stopping with the add-in.", retryable: false);
        }
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
    /// The search behind `sessions.list` (feature 015, contracts/recheck.md section 9): a waiting
    /// review of the active part or assembly, tracked without becoming the latest run. A found
    /// folder the engineer removed is offered no more; since the search reads only the newest
    /// candidate and never falls back, that leaves nothing, never an older review (98A item 4).
    /// </summary>
    private void FindNotSentReview()
    {
        PageDocument? document = _options.CurrentDocument();
        if (document == null || !document.IsAttachable) return;
        if (Reviews().Any(record => document.IsSameDocument(record.Document))) return;

        SessionRecord? found = RunFolders.FindNotSentReview(_settings.RunRoot, document, _options.OpenSessionHead);
        if (found == null) return;
        lock (_sessionsLock)
        {
            if (_forgottenFolders.Contains(SameFolder(found.RunDirectory))) return;
        }

        Publish(found, makeLatest: false);
    }

    /// <summary>
    /// `sessions.list`: every review this host tracks, including a found waiting review, with what its chip
    /// names - `{chat_id, run_id, run_dir, path, configuration, started_at}` - and no check or
    /// remodel record (contracts/sessions.md section 2). `started_at` is ISO 8601 with its offset;
    /// what the host does not know is null rather than invented.
    /// </summary>
    private void SendReviews(string? id)
    {
        IReadOnlyList<SessionRecord> reviews = Reviews();
        foreach (SessionRecord record in reviews)
        {
            if (record.ModelStatus == null) continue;
            JsonElement? status = RunFolders.ReadModelStatus(record.RunDirectory, _options.OpenSessionHead);
            if (status.HasValue && status.Value.TryGetProperty("state", out JsonElement state)
                && state.ValueKind == JsonValueKind.String && state.GetString() == "sent")
            {
                record.ModelStatus = null;
            }
        }
        Send("sessions", id, new Dictionary<string, object?>
        {
            { "items", reviews.Select(ReviewItem).ToArray() },
        });
    }

    private static Dictionary<string, object?> ReviewItem(SessionRecord record)
    {
        var item = new Dictionary<string, object?>
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
        if (record.ModelStatus != null) item["model_status"] = record.ModelStatus;
        return item;
    }

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
    /// The Review tab's one sentence for a drawing (feature 011, contracts/attach.md section 5; U25,
    /// default taken 2026-09-28, the owner may revise): a drawing is not reviewed on its own, it
    /// is read with the part or assembly it documents for as long as it stays open in SOLIDWORKS
    /// (open-drawing discovery), and so the engineer keeps it open and activates that model. The
    /// host composes it once and it is used everywhere: the page's banner prints it as sent, and
    /// the preparation's and the start's refusal carry it, so the engineer reads the same words
    /// at every step.
    ///
    /// It names the model when the drawing's views say which: the first one, in sheet-then-view
    /// order, by file name - discovery matches a drawing to a model by path, never by
    /// configuration - with the others counted rather than chosen between. "Open or switch to",
    /// because a drawing opened on its own has its model loaded but no window of its own. With
    /// no model known the sentence names none.
    /// </summary>
    public static string DrawingSentence(string drawingPath, IReadOnlyList<string>? models)
    {
        if (drawingPath == null)
        {
            throw new ArgumentNullException(nameof(drawingPath));
        }

        string drawing = System.IO.Path.GetFileName(drawingPath);
        List<string> named = (models ?? Array.Empty<string>())
            .Where(model => !string.IsNullOrWhiteSpace(model))
            .Select(model => System.IO.Path.GetFileName(model.Trim()))
            .ToList();
        const string Reads = "Review reads open drawings whose views show the model.";

        if (named.Count == 0)
        {
            return $"{drawing} is a drawing. Keep it open in SOLIDWORKS and activate the part or "
                + $"assembly it documents, then press Review with that model active; {Reads}";
        }

        if (named.Count == 1)
        {
            return $"{drawing} is a drawing of {named[0]}. Keep the drawing open in SOLIDWORKS, open "
                + $"or switch to {named[0]}, then press Review with it active; {Reads}";
        }

        int others = named.Count - 1;
        return $"{drawing} is a drawing of {named[0]} and {others} other model{(others == 1 ? string.Empty : "s")}. "
            + $"Keep the drawing open in SOLIDWORKS, open or switch to {named[0]} or another model it "
            + $"shows, then press Review with that model active; {Reads}";
    }

    /// <summary>
    /// <see cref="DrawingSentence"/> for the drawing <paramref name="drawing"/>, with the models
    /// its views show as <see cref="ReviewHostOptions.DrawingModels"/> reads them. A reader that
    /// throws names no model: the sentence is guidance, and guidance never fails the page.
    /// </summary>
    private string DrawingGuidance(PageDocument drawing)
    {
        IReadOnlyList<string>? models;
        try
        {
            models = _options.DrawingModels?.Invoke(drawing.Path);
        }
        catch (Exception)
        {
            models = null;
        }

        return DrawingSentence(drawing.Path, models);
    }

    private long ExpirePreparedContext()
    {
        long generation = Interlocked.Increment(ref _contextGeneration);
        _preparedContext = null;
        return generation;
    }

    private static bool SameDocument(PageDocument? current, PageDocument saved) =>
        current != null
        && string.Equals(current.Path, saved.Path, StringComparison.OrdinalIgnoreCase)
        && string.Equals(current.Configuration, saved.Configuration, StringComparison.Ordinal);

    private static string PackageSha256(string directory)
    {
        using (var algorithm = SHA256.Create())
        {
            byte[] digest = algorithm.ComputeHash(File.ReadAllBytes(Path.Combine(directory, "package.json")));
            return BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
        }
    }

    private bool ContextReady(string? id)
    {
        if (AnyTurnRunning())
        {
            SendError(id, "TurnRunning", "Stop the running review before changing engineering context.", true);
            return false;
        }
        if (!RestartedForNewReview(id))
        {
            return false;
        }
        if (_options.Backend.Endpoint == null)
        {
            SendError(id, "BackendUnavailable", "The review backend is not running yet.", true);
            return false;
        }
        return true;
    }

    private void PrepareContext(string? id)
    {
        long generation = ExpirePreparedContext();
        _preparationId = null;
        _preparedDocument = null;
        if (!ContextReady(id)) return;
        PageDocument? document = _options.CurrentDocument();
        if (document == null || !document.IsAttachable)
        {
            SendError(id, "NoDocument", "Open a saved part or assembly to extract context evidence.", true);
            return;
        }
        if (_options.Dump == null)
        {
            SendError(id, "NotAttached", "Evidence extraction is not available in this host.", true);
            return;
        }
        try
        {
            string directory = RunFolders.CreateForDocument(_settings.RunRoot, document.Path, _options.Now());
            PostStatus("extracting", "Extracting saved evidence for engineering context; no review tokens used.");
            DumpSummary summary = _options.Dump.Run(directory, message => PostStatus("extracting", message));
            if (!SameDocument(_options.CurrentDocument(), document)
                || generation != Interlocked.Read(ref _contextGeneration))
            {
                SendError(id, "ContextExpired", "The active document or configuration changed. Extract context evidence again.", true);
                return;
            }
            var prepared = new PreparedContext(directory, PackageSha256(directory), document, generation, summary);
            if (generation != Interlocked.Read(ref _contextGeneration))
            {
                SendError(id, "ContextExpired", "The document changed during evidence extraction. Extract context evidence again.", true);
                return;
            }
            _preparedContext = prepared;
            Send("context.prepared", id, new Dictionary<string, object?>
            {
                { "run_id", prepared.RunId }, { "package_sha256", prepared.Sha256 },
                { "document", DocumentPayload(document) },
            });
            PostStatus("ready", "Context evidence extracted; no review tokens used.");
        }
        catch (Exception)
        {
            _preparedContext = null;
            SendError(id, "ContextPreparationFailed", "Context evidence could not be extracted. Check the log and try again.", true);
        }
    }

    private PreparedContext? CurrentContext(string? id, JsonElement payload)
    {
        if (!ContextReady(id)) return null;
        PreparedContext? prepared = _preparedContext;
        if (prepared == null || prepared.Generation != Interlocked.Read(ref _contextGeneration)
            || !string.Equals(Text(payload, "run_id"), prepared.RunId, StringComparison.Ordinal)
            || !SameDocument(_options.CurrentDocument(), prepared.Document)
            || !string.Equals(Text(payload, "package_sha256"), prepared.Sha256, StringComparison.Ordinal))
        {
            _preparedContext = null;
            SendError(id, "ContextExpired", "Saved context evidence no longer matches this document. Extract context evidence again.", true);
            return null;
        }
        try
        {
            if (PackageSha256(prepared.Directory) == prepared.Sha256
                && prepared.Generation == Interlocked.Read(ref _contextGeneration)
                && ReferenceEquals(_preparedContext, prepared)) return prepared;
        }
        catch (Exception) { }
        _preparedContext = null;
        SendError(id, "ContextExpired", "The saved evidence changed. Extract context evidence again.", true);
        return null;
    }

    private void CaptureContextSelection(string? id, JsonElement payload)
    {
        PreparedContext? prepared = CurrentContext(id, payload);
        if (prepared == null) return;
        if (_options.EngineeringSelection == null)
        {
            SendError(id, "SelectionUnavailable", "Selection entry is unavailable. Choose a saved target from the list.", false);
            return;
        }
        EngineeringSelectionObservation observation;
        try { observation = _options.EngineeringSelection.Capture(prepared.Directory, prepared.Sha256); }
        catch (Exception)
        {
            SendError(id, "SelectionUnavailable", "The selection could not be read. Choose a saved target from the list.", true);
            return;
        }
        if (!ReferenceEquals(_preparedContext, prepared))
        {
            SendError(id, "ContextExpired", "The document changed while reading the selection. Extract context evidence again.", true);
            return;
        }
        if (CurrentContext(id, payload) == null) return;
        if (!string.Equals(observation.PackageSha256, prepared.Sha256, StringComparison.Ordinal))
        {
            SendError(id, "SelectionUnavailable", "The selection did not match this saved evidence.", true);
            return;
        }
        Send("context.selected", id, observation);
    }

    private static bool IsDigest(string? text) => text != null && text.Length == 64
        && text.All(character => (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'));

    private void ReviewContext(string? id, JsonElement payload)
    {
        PreparedContext? prepared = CurrentContext(id, payload);
        if (prepared == null) return;
        string? contextId = Text(payload, "context_id");
        string? head = Text(payload, "head_digest");
        if (!Guid.TryParse(contextId, out _) || !IsDigest(head))
        {
            SendError(id, "InvalidContext", "Inspect the saved context before starting its review.", false);
            return;
        }
        // Owner decision 99A: the one session path every review takes, so the box decides Send or
        // Wait here as it does for review.start, and the record, status and reply say which.
        bool started = CreateReviewSession(prepared.Document, prepared.Directory, null,
            _settings.SendsWhenChecked ? ReviewMode.Send : ReviewMode.Wait, id, prepared.Summary,
            attachment: new EngineeringContextAttachment(contextId!, head!, prepared.Sha256));
        if (started) _preparedContext = null;
    }

    private void PrepareReview(string? id)
    {
        ExpirePreparedContext();
        _preparationId = null;
        _preparedDocument = null;
        PageDocument? document = _options.CurrentDocument();
        if (document != null && document.Kind == "drawing")
        {
            SendError(id, "DrawingActive", DrawingGuidance(document), true);
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
        ExpirePreparedContext();
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
        if (!CanReviewDocument(document, id))
        {
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

        string? retryOf = Blank(Text(payload, "retry_of"));
        SessionRecord? retried = retryOf == null ? null : FindSession(retryOf);
        if (retried?.EngineeringContext != null)
        {
            RetryContextReview(id, document, retried);
            return;
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

        if (!BackendReady(id))
        {
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

        CreateReviewSession(document, runDirectory, Blank(Text(payload, "retry_of")),
            _settings.SendsWhenChecked ? ReviewMode.Send : ReviewMode.Wait, id, summary);
    }

    /// <summary>
    /// Owner decision 108A: Retry on a failed context review. Its saved context lives in the
    /// review's own run folder, so nothing is extracted again: the same attachment (context id,
    /// head and saved package digest) is posted with that folder and the failed chat as
    /// `retry_of`, through the one gated session path, Send or Wait from the box. The backend
    /// validates the head again and refuses a changed context with its conflict.
    /// </summary>
    private void RetryContextReview(string? id, PageDocument document, SessionRecord retried)
    {
        if (!document.IsSameDocument(retried.Document))
        {
            SendError(id, "ReviewNotActive", "Open or switch to the reviewed document and configuration before retrying its review with saved context.", retryable: true);
            return;
        }
        if (!BackendReady(id))
        {
            return;
        }

        CreateReviewSession(retried.Document, retried.RunDirectory, retried.ChatId,
            _settings.SendsWhenChecked ? ReviewMode.Send : ReviewMode.Wait, id,
            retried.ContextExtraction ?? new DumpSummary(retried.RunDirectory, 0, 0),
            attachment: retried.EngineeringContext);
    }

    private bool CanReviewDocument(PageDocument document, string? id)
    {
        if (document.Kind != "drawing") return true;
        SendError(id, "DrawingActive", DrawingGuidance(document), retryable: true);
        return false;
    }

    private void RecheckReview(string? id, JsonElement payload)
    {
        string? chatId = Blank(Text(payload, "chat_id"));
        if (chatId == null)
        {
            SendError(id, "InvalidRequest", "the message needs a chat_id.", retryable: false);
            return;
        }

        SessionRecord? record = FindSession(chatId);
        if (record == null || record.IsCheck)
        {
            SendError(id, "UnknownChat", _runs.UnknownMessage(chatId), retryable: false);
            return;
        }

        CreateReviewSession(record.Document, record.RunDirectory, chatId, ReviewMode.Recheck, id,
            new DumpSummary(record.RunDirectory, 0, 0), replacing: record);
    }

    private bool BackendReady(string? id)
    {
        if (!RestartedForNewReview(id)) return false;
        if (_options.Backend.Endpoint != null) return true;
        SendError(id, "BackendUnavailable",
            "the review backend is not running yet, so there is nowhere to send the review. "
            + "Check the log, then press Review again.", retryable: true);
        return false;
    }

    /// <param name="replacing">The record a re-run replaces (`ReviewMode.Recheck` only): its
    /// place in the list and its own model status are kept, even if it was forgotten meanwhile.</param>
    /// <param name="attachment">Feature 016's saved context for this review, or null (owner decision
    /// 99A: a context review starts here like any other).</param>
    /// <returns>Whether the session was created; false after a refusal already answered.</returns>
    private bool CreateReviewSession(
        PageDocument? document, string runDirectory, string? previousChatId, ReviewMode mode,
        string? id, DumpSummary summary, SessionRecord? replacing = null,
        EngineeringContextAttachment? attachment = null)
    {
        PageDocument? active = mode == ReviewMode.Recheck ? _options.CurrentDocument() : document;
        if (active != null && !CanReviewDocument(active, id))
        {
            return false;
        }
        if (mode == ReviewMode.Recheck)
        {
            if (active == null || !active.IsSameDocument(document))
            {
                SendError(id, "ReviewNotActive", "Open or switch to the reviewed document and configuration before checking its saved evidence again.", retryable: true);
                return false;
            }
            if (!BackendReady(id))
            {
                return false;
            }

            // A recheck replaces this tracked chat; a fresh start instead sends the earlier
            // chat id as retry_of. Rechecks never ask the backend for a fresh retry.
            PostStatus("checking", "Checking the saved evidence again...");
        }
        ChatSessionHandle handle;
        try
        {
            // CreateSession checks the current endpoint. If the backend stopped during the
            // dump, its refusal follows the same error status and reply path as any request.
            handle = _options.Backend.CreateSession(new NewSessionRequest(
                runDirectory,
                _settings.Provider,
                _settings.Model,
                _settings.Effort,
                _options.Engineer,
                _options.Bridge,
                // FR-028: the page's Retry on an error card starts a fresh chat that says
                // which one it is replacing, so the pair can be read back in the run folder.
                mode == ReviewMode.Recheck ? null : previousChatId,
                Blank(_settings.StandardsProfilePath),
                mode: mode,
                engineeringContext: attachment));
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
        string? modelStatus = mode == ReviewMode.Recheck ? replacing?.ModelStatus
            : mode == ReviewMode.Send ? null : "not_sent";
        Publish(new SessionRecord(handle.ChatId, runDirectory, document, new DateTimeOffset(_options.Now()))
        {
            ModelStatus = modelStatus,
            EngineeringContext = attachment ?? replacing?.EngineeringContext,
            ContextExtraction = attachment != null ? summary : replacing?.ContextExtraction,
        }, makeLatest: true, replacing);
        PostStatus("ready", mode == ReviewMode.Recheck
            ? "Checked the saved evidence again; nothing was sent to the model."
            : mode == ReviewMode.Send
                ? ReadyMessage(summary.Components, summary.Gaps, summary.Unexamined)
                : $"Checked {summary.Components} components by code; nothing was sent to the model.");

        // `document` is the one captured before the dump, not whichever is active now: the
        // review is of what was extracted, and the page binds what it shows to this (U8).
        var reply = new Dictionary<string, object?>
        {
            { "chat_id", handle.ChatId },
            { "run_dir", runDirectory },
            { "not_examined", handle.NotExamined },
            { "document", DocumentPayload(document) },
        };
        if (mode == ReviewMode.Recheck) reply["previous_chat_id"] = previousChatId;
        else reply["send_when_checked"] = mode == ReviewMode.Send;
        Send(mode == ReviewMode.Recheck ? "review.rechecked" : "review.started", id, reply);
        return true;
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

    /// <summary>
    /// The document as `init`, `document.changed` and `review.started` carry it: the check tabs'
    /// shape, `kind` included, so every page reads one - and, for a drawing, the sentence the page
    /// prints for it (U25, default taken 2026-09-28, the owner may revise). `kind` is the host's
    /// one reading of what a path is (<see cref="PageDocument.Kind"/>), so the page decides
    /// "drawing" from it rather than from an extension table of its own.
    /// </summary>
    private Dictionary<string, object?>? DocumentPayload(PageDocument? document)
    {
        Dictionary<string, object?>? payload = CheckPaneHost.DocumentPayload(document);
        if (payload != null && document!.Kind == "drawing")
        {
            payload["drawing_guidance"] = DrawingGuidance(document);
        }

        return payload;
    }

    /// <summary>
    /// The settings as the page may see them: an explicit allow-list, so no field added to the
    /// settings file later can start being echoed by accident. `api_key_protected` is absent.
    /// </summary>
    private static Dictionary<string, object?> View(UserSettings settings)
    {
        return new Dictionary<string, object?>
        {
            { "version", settings.Version },
            { "send_when_checked", settings.SendsWhenChecked },
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
