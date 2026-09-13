using System;
using System.Collections.Generic;
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
}

/// <summary>
/// What the host knows about one chat: enough to answer `report.open` and `folder.open`
/// without ever taking a path from the page (pane-host-messages.md).
/// </summary>
public sealed class SessionRecord
{
    public SessionRecord(string chatId, string runDirectory)
    {
        ChatId = chatId ?? throw new ArgumentNullException(nameof(chatId));
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
    }

    public string ChatId { get; }

    public string RunDirectory { get; }
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
/// `settings.get`, `settings.save`, `models.list`) and the review flow (`review.start`,
/// `entity.show`, `report.open`, `folder.open`, `log.open`), on one dispatch over one set of
/// session records. SOLIDWORKS, the extractor, the shell and the backend each reach it
/// through an interface, so all of it is testable with no SOLIDWORKS, no WebView2 and no
/// Python.
///
/// Six rules are enforced here because nowhere else can:
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
/// customer documents wrote - so a path it supplied would be a way to open anything on the
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
/// backend restart takes seconds.
/// </summary>
public sealed class ReviewHost : IDisposable
{
    private static readonly string[] AllProviders = { "openai", "gemini", "fake" };
    private static readonly string[] ReleaseProviders = { "openai", "gemini" };
    private static readonly string[] Efforts = { "low", "medium", "high", "xhigh" };

    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        WriteIndented = false,
    };

    private readonly ReviewHostOptions _options;
    private readonly List<SessionRecord> _sessions = new List<SessionRecord>();
    private UserSettings _settings;
    private string? _settingsError;

    public ReviewHost(ReviewHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
        SettingsLoadResult loaded = UserSettings.Load(options.SettingsPath, options.BuildMode);
        _settings = loaded.Settings;
        _settingsError = loaded.Error;
    }

    /// <summary>The settings in force. Replaced by a successful `settings.save`.</summary>
    public UserSettings Settings => _settings;

    /// <summary>The chats this host started, newest last.</summary>
    public IReadOnlyList<SessionRecord> Sessions => _sessions;

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
    public void TrackSession(string chatId, string runDirectory)
    {
        if (chatId == null)
        {
            throw new ArgumentNullException(nameof(chatId));
        }

        _sessions.RemoveAll(session => session.ChatId == chatId);
        var record = new SessionRecord(chatId, runDirectory);
        _sessions.Add(record);
        LatestSession = record;
    }

    /// <summary>The record for <paramref name="chatId"/>, or null.</summary>
    public SessionRecord? FindSession(string chatId) =>
        _sessions.FirstOrDefault(session => session.ChatId == chatId);

    /// <summary>Whether any chat this host started has a turn in flight.</summary>
    public bool AnyTurnRunning()
    {
        foreach (SessionRecord session in _sessions)
        {
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
        _sessions.Clear();
        LatestSession = null;
    }

    private void Dispatch(string type, string? id, JsonElement payload)
    {
        switch (type)
        {
            case "ready":
                SendInit(id);
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

            case "review.start":
                StartReview(id, payload);
                return;

            case "entity.show":
                ShowEntity(id, payload);
                return;

            case "report.open":
                OpenReport(id, payload);
                return;

            case "folder.open":
                OpenRunFolder(id, payload);
                return;

            case "log.open":
                OpenLogFolder(id);
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
                        { "origin", endpoint.Origin },
                    }
            },
            { "token", endpoint?.Token },
            { "settings", View(_settings) },
            { "key_source", key.Source },
            { "run_root", _settings.RunRoot },
            { "providers", Providers() },
            { "document", DocumentPayload(document) },
        });

        ReportSettingsProblems(key);
    }

    private string[] Providers() =>
        _options.BuildMode == BuildMode.Development ? AllProviders : ReleaseProviders;

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

    // ---- review.start -------------------------------------------------------------------

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
        PostStatus("extracting", $"Extracting {RunFolders.DocumentName(document.Path)}...");
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
                Blank(Text(payload, "retry_of"))));
        }
        catch (Exception failure)
        {
            PostStatus("error", failure.Message);

            // Rethrown rather than answered here: `Receive` maps a BackendRequestException to
            // the backend's own `error_class`, which is the one the page acts on.
            throw;
        }

        TrackSession(handle.ChatId, runDirectory);

        PostStatus(
            "ready",
            summary.Gaps == 0
                ? $"Reviewing {summary.Components} components."
                : $"Reviewing {summary.Components} components ({summary.Gaps} gaps).");

        Send("review.started", id, new Dictionary<string, object?>
        {
            { "chat_id", handle.ChatId },
            { "run_dir", runDirectory },
        });
    }

    // ---- entity.show --------------------------------------------------------------------

    /// <summary>
    /// Show in SOLIDWORKS. The answer is always an `entity.shown`, never an exception and -
    /// except for a malformed message - never a bare `error`: a reference that no longer
    /// resolves is an expected outcome that belongs on the finding card, with the state code
    /// and the component's full path, not in an error banner (spec Edge Cases, SC-007).
    /// </summary>
    private void ShowEntity(string? id, JsonElement payload)
    {
        string persistRef = (Text(payload, "persist_ref") ?? string.Empty).Trim();
        if (persistRef.Length == 0)
        {
            SendError(
                id,
                "InvalidRequest",
                "entity.show needs the finding's persist_ref.",
                retryable: false);
            return;
        }

        if (_options.EntityResolver == null)
        {
            SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so nothing can be selected.",
                retryable: true);
            return;
        }

        EntityShowOutcome outcome;
        try
        {
            outcome = _options.EntityResolver.Show(new EntityShowRequest(
                persistRef,
                Blank(Text(payload, "persist_ref_scope")),
                Blank(Text(payload, "component_id"))));
        }
        catch (Exception failure)
        {
            // -1 is not a swPersistReferencedObjectStates_e value: SOLIDWORKS never answered
            // at all (a modal dialog on the application thread, a closed document, an open
            // circuit), which is a different thing from a reference that resolved to nothing.
            outcome = EntityShowOutcome.NotShown(-1, failure.Message, null);
        }

        Send("entity.shown", id, new Dictionary<string, object?>
        {
            { "ok", outcome.Ok },
            { "state_code", outcome.StateCode },
            { "message", outcome.Message == null ? null : Redact(outcome.Message) },
            { "full_path", outcome.FullPath },
        });
    }

    // ---- report.open / folder.open / log.open -------------------------------------------

    private void OpenReport(string? id, JsonElement payload)
    {
        if (!TryRunDirectory(id, payload, out string runDirectory))
        {
            return;
        }

        string report;
        try
        {
            report = System.IO.Path.Combine(runDirectory, "report.md");
        }
        catch (ArgumentException)
        {
            SendError(id, "PathRefused", "that path cannot be opened.", retryable: false);
            return;
        }

        // Containment before existence: a path outside the run root is refused as such, and
        // is not probed for what happens to be on disk there.
        if (!TrySafePath(id, report, _settings.RunRoot, out string full))
        {
            return;
        }

        if (!System.IO.File.Exists(full))
        {
            SendError(
                id,
                "NotFound",
                "report.md has not been written yet; it appears once the review reports its "
                + "first finding.",
                retryable: true);
            return;
        }

        Open(id, full);
    }

    private void OpenRunFolder(string? id, JsonElement payload)
    {
        if (!TryRunDirectory(id, payload, out string runDirectory))
        {
            return;
        }

        Shell(id, runDirectory, _settings.RunRoot);
    }

    private void OpenLogFolder(string? id)
    {
        string folder = _options.LogFolder;
        try
        {
            // The host's own folder: an engineer pressing View log before anything has been
            // logged should get an empty folder, not "the path does not exist".
            System.IO.Directory.CreateDirectory(folder);
        }
        catch (Exception failure)
        {
            SendError(id, "OpenFailed", failure.Message, retryable: false);
            return;
        }

        Shell(id, folder, folder);
    }

    /// <summary>
    /// The run folder for the `chat_id` in <paramref name="payload"/>, from the host's own
    /// session records.
    ///
    /// The page supplies a chat id and nothing else. Any path it sent is ignored: a page that
    /// could name the path to open could open anything on the workstation with one crafted
    /// message, and the page is the least trusted thing in the process - it renders text the
    /// model and customer documents wrote.
    /// </summary>
    private bool TryRunDirectory(string? id, JsonElement payload, out string runDirectory)
    {
        runDirectory = string.Empty;

        string chatId = (Text(payload, "chat_id") ?? string.Empty).Trim();
        if (chatId.Length == 0)
        {
            SendError(id, "InvalidRequest", "the message needs a chat_id.", retryable: false);
            return false;
        }

        SessionRecord? record = FindSession(chatId);
        if (record == null)
        {
            SendError(
                id,
                "UnknownChat",
                $"this pane did not start a chat called '{chatId}', so it does not know which "
                + "folder to open.",
                retryable: false);
            return false;
        }

        runDirectory = record.RunDirectory;
        return true;
    }

    /// <summary>
    /// Canonicalizes <paramref name="path"/>, refuses anything that is not inside
    /// <paramref name="root"/>, and opens what is left (pane-host-messages.md: "Every resolved
    /// path is canonicalized and must be a descendant of `run_root` (or the log folder) before
    /// it reaches `ShellExecute`").
    /// </summary>
    private void Shell(string? id, string path, string root)
    {
        if (TrySafePath(id, path, root, out string full))
        {
            Open(id, full);
        }
    }

    /// <summary>Canonicalizes and refuses anything that is not inside <paramref name="root"/>.</summary>
    private bool TrySafePath(string? id, string path, string root, out string full)
    {
        full = string.Empty;

        string fullRoot;
        try
        {
            full = System.IO.Path.GetFullPath(path);
            fullRoot = System.IO.Path.GetFullPath(root);
        }
        catch (Exception)
        {
            SendError(id, "PathRefused", "that path cannot be opened.", retryable: false);
            return false;
        }

        // UNC and Win32 device paths are refused by name as well as by containment: a run root
        // that is itself a share would otherwise make `\\server\share\...` a descendant.
        if (full.StartsWith(@"\\", StringComparison.Ordinal) || !Contains(fullRoot, full))
        {
            SendError(
                id,
                "PathRefused",
                "that folder is outside the run root, so the pane will not open it.",
                retryable: false);
            return false;
        }

        return true;
    }

    private void Open(string? id, string path)
    {
        try
        {
            _options.Opener.Open(path);
        }
        catch (Exception failure)
        {
            SendError(id, "OpenFailed", failure.Message, retryable: false);
            return;
        }

        Send("ok", id, new Dictionary<string, object?>());
    }

    /// <summary>Whether <paramref name="candidate"/> is <paramref name="root"/> or below it.</summary>
    private static bool Contains(string root, string candidate)
    {
        string trimmed = root.TrimEnd(System.IO.Path.DirectorySeparatorChar);
        if (string.Equals(trimmed, candidate.TrimEnd(System.IO.Path.DirectorySeparatorChar),
                StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return candidate.StartsWith(
            trimmed + System.IO.Path.DirectorySeparatorChar,
            StringComparison.OrdinalIgnoreCase);
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
    public void PostStatus(string stage, string message) => Post("status", new Dictionary<string, object?>
    {
        { "stage", stage },
        { "message", Redact(message) },
    });

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

    private static string? Text(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object
            || !element.TryGetProperty(name, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    }

    private static string? Blank(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value!.Trim();

    private void SendError(string? id, string errorClass, string message, bool retryable)
    {
        Send("error", id, new Dictionary<string, object?>
        {
            { "error_class", errorClass },
            { "message", Redact(message) },
            { "retryable", retryable },
        });
    }

    private void Send(string type, string? id, object? payload)
    {
        var envelope = new Dictionary<string, object?>
        {
            { "type", type },
            { "id", id },
            { "payload", payload },
        };

        try
        {
            _options.Channel.PostMessage(JsonSerializer.Serialize(envelope, JsonOptions));
        }
        catch (Exception)
        {
            // The page is gone (the pane closed mid-handler). There is nobody left to tell.
        }
    }

    /// <summary>
    /// Masks the configured key in anything headed for the page or the log (FR-015).
    ///
    /// Public for the same reason as <see cref="PostStatus"/>, and for one caller in
    /// particular: the add-in's `addin.log` line is written from `Exception.ToString()`, which
    /// carries every inner exception's message - and the inner exception is exactly where the
    /// unredacted launcher failure sits, because `BackendProcess` masks only the outer one.
    /// </summary>
    public string Redact(string text)
    {
        var secrets = new List<string?>();
        try
        {
            secrets.Add(_settings.ResolveApiKey(_options.Environment).Key);
        }
        catch (Exception)
        {
            // Resolving the key must never be the reason an error message cannot be sent.
        }

        return Redaction.Redact(text, secrets);
    }
}
