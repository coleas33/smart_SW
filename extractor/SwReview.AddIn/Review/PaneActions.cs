using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Settings;

namespace SwReview.AddIn.Review;

/// <summary>
/// Reading the fields a page message carries. Two lines, in one place, because both hosts
/// read the same envelope and a second copy would be a second set of rules about what counts
/// as absent.
/// </summary>
internal static class PagePayload
{
    /// <summary>The string field <paramref name="name"/>, or null when it is absent or not a string.</summary>
    public static string? Text(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object
            || !element.TryGetProperty(name, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    }

    /// <summary>A JSON boolean, or null when absent or of another kind.</summary>
    public static bool? Flag(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object
            || !element.TryGetProperty(name, out JsonElement value)
            || (value.ValueKind != JsonValueKind.True && value.ValueKind != JsonValueKind.False))
        {
            return null;
        }
        return value.GetBoolean();
    }

    /// <summary>Trimmed, or null when there was nothing but whitespace.</summary>
    public static string? Blank(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value!.Trim();
}

/// <summary>
/// How one host names the run that a `report.open` or `folder.open` is about.
///
/// The two hosts track different things - <see cref="ReviewHost"/> tracks chats, the Model
/// check host tracks checks - so the payload field and the refusal differ by a noun. Everything
/// downstream of the lookup, which is all of the security, is the same code either way.
/// </summary>
public sealed class PaneRunLookup
{
    /// <param name="idField">The payload field the page names a run in (`chat_id`, `run_id`).</param>
    /// <param name="unknownErrorClass">The `error_class` for an id the host never recorded.</param>
    /// <param name="unknownMessage">The sentence that goes with it, given the id.</param>
    /// <param name="resolve">The host's own record: an id to a run directory, or null.</param>
    public PaneRunLookup(
        string idField,
        string unknownErrorClass,
        Func<string, string> unknownMessage,
        Func<string, string?> resolve)
    {
        IdField = idField ?? throw new ArgumentNullException(nameof(idField));
        UnknownErrorClass = unknownErrorClass
            ?? throw new ArgumentNullException(nameof(unknownErrorClass));
        UnknownMessage = unknownMessage ?? throw new ArgumentNullException(nameof(unknownMessage));
        Resolve = resolve ?? throw new ArgumentNullException(nameof(resolve));
    }

    public string IdField { get; }

    public string UnknownErrorClass { get; }

    public Func<string, string> UnknownMessage { get; }

    public Func<string, string?> Resolve { get; }
}

/// <summary>Everything <see cref="PaneActions"/> is given; injected so it is testable headless.</summary>
public sealed class PaneActionsOptions
{
    /// <param name="channel">Where replies go.</param>
    /// <param name="runRoot">The run root in force, read fresh: a settings save moves it.</param>
    /// <param name="runs">How this host's page names a run, and how the host resolves one.</param>
    public PaneActionsOptions(IPageChannel channel, Func<string> runRoot, PaneRunLookup runs)
    {
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        RunRoot = runRoot ?? throw new ArgumentNullException(nameof(runRoot));
        Runs = runs ?? throw new ArgumentNullException(nameof(runs));
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
    /// review host knows it (the reviews of 154A's merge, N4): a run start refused for the run root in force while
    /// another is saved says to retry the restart, not to choose a folder again. None by default.
    /// </summary>
    public Func<string?> RunRootSaved { get; set; } = () => null;

    public PaneRunLookup Runs { get; }

    /// <summary>%LOCALAPPDATA%\SwReview\logs by default; what `log.open` opens.</summary>
    public Func<string> LogFolder { get; set; } = ReviewHostOptions.DefaultLogFolder;

    /// <summary>
    /// Show in SOLIDWORKS. Read fresh, and null until the add-in is attached to a session -
    /// a state the pane really has, because the Task Pane exists before the first document.
    /// </summary>
    public Func<IEntityResolver?> EntityResolver { get; set; } = () => null;

    /// <summary>What `report.open`, `folder.open` and `log.open` shell out through.</summary>
    public Func<IPathOpener> Opener { get; set; } = () => new ShellPathOpener();

    /// <summary>
    /// Values that must never reach the page, read per call because the configured key changes
    /// under a live host (FR-015).
    /// </summary>
    public Func<IEnumerable<string?>> Secrets { get; set; } = () => new string?[0];
}

/// <summary>
/// The four rows every pane host serves the same way: `entity.show`, `report.open`,
/// `folder.open` and `log.open`, plus the envelope, the run-root containment and the redaction
/// they all depend on.
///
/// Extracted from <see cref="ReviewHost"/> when the Model check tab needed the same four
/// (`contracts/model-check.md` section 2). The alternative - a shared abstract `PaneHost` base
/// class - is rejected in plan.md: inheritance would drag settings and backend state into a
/// host that needs neither. This is composition instead, so a host owns only what it actually
/// has, and the rows are proven identical by tests parameterized over both hosts rather than
/// assumed identical because they share a parent.
///
/// Three rules live here because nowhere else can:
///
/// <b>The page never names a path to open.</b> `report.open` and `folder.open` carry an id;
/// the folder comes from the host's own record, and every resolved path is canonicalized and
/// checked to be inside the run root (or the log folder) before it reaches the shell. The page
/// is the least trusted thing in the process - it renders text the model and the reviewed
/// documents wrote - so a path it supplied would be a way to open anything on the workstation.
///
/// <b>A reference that no longer resolves is an answer, not an error.</b> `entity.show` always
/// replies `entity.shown`, carrying the state code and the component's full path, so the card
/// can tell the engineer where to look by hand (spec Edge Cases, SC-007).
///
/// <b>Nothing thrown here reaches the page unmasked.</b> Every message out of
/// <see cref="Send"/> and <see cref="SendError"/> goes through <see cref="Redact"/> (FR-015).
/// </summary>
public sealed class PaneActions
{
    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        WriteIndented = false,
    };

    private readonly PaneActionsOptions _options;

    public PaneActions(PaneActionsOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
    }

    /// <summary>
    /// Handles <paramref name="type"/> when it is one of the four shared rows, and says so.
    ///
    /// A host calls this first and falls through to its own table; the four rows exist once,
    /// which is the whole point of the class.
    /// </summary>
    public bool TryHandle(string type, string? id, JsonElement payload)
    {
        switch (type)
        {
            case "entity.show":
                ShowEntity(id, payload);
                return true;

            case "report.open":
                OpenReport(id, payload);
                return true;

            case "folder.open":
                OpenRunFolder(id, payload);
                return true;

            case "log.open":
                OpenLogFolder(id);
                return true;

            default:
                return false;
        }
    }

    // ---- entity.show --------------------------------------------------------------------

    /// <summary>
    /// Show in SOLIDWORKS. The answer is always an `entity.shown`, never an exception and -
    /// except for a malformed message - never a bare `error`: a reference that no longer
    /// resolves is an expected outcome that belongs on the card, with the state code and the
    /// component's full path, not in an error banner (spec Edge Cases, SC-007).
    /// </summary>
    private void ShowEntity(string? id, JsonElement payload)
    {
        string persistRef = (PagePayload.Text(payload, "persist_ref") ?? string.Empty).Trim();
        if (persistRef.Length == 0)
        {
            SendError(
                id,
                "InvalidRequest",
                "entity.show needs the finding's persist_ref.",
                retryable: false);
            return;
        }

        IEntityResolver? resolver = _options.EntityResolver();
        if (resolver == null)
        {
            SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so nothing can be selected.",
                retryable: true);
            return;
        }

        // Feature 009 FR-023: a page that names the run it is showing - the Review tab always
        // sends its chat's `chat_id` - has its ids looked up in that run's package, resolved
        // through the same record `report.open` reads. The page names an id, never a path; an id
        // this host never recorded is refused as `report.open` refuses one. With no id, the
        // resolver reads the pane's latest run, as the check tabs' Show always has.
        string? runDirectory = null;
        if (PagePayload.Blank(PagePayload.Text(payload, _options.Runs.IdField)) != null)
        {
            if (!TryRunDirectory(id, payload, out string resolved))
            {
                return;
            }

            runDirectory = resolved;
        }

        ShowPersistRef(id, new EntityShowRequest(
            persistRef,
            PagePayload.Blank(PagePayload.Text(payload, "persist_ref_scope")),

            // The page decides which instance of a part to show and sends that component's
            // id; the host passes it through and never picks one for the engineer.
            PagePayload.Blank(PagePayload.Text(payload, "component_id")),
            runDirectory));
    }

    /// <summary>
    /// Shows what <paramref name="request"/> names and answers `entity.shown`, for a host that
    /// resolved the reference from its own records rather than from the page's message.
    ///
    /// Feature 004's `remodel.show_change` carries a change's sequence number, not a reference:
    /// the host reads the persistent reference out of `changes.jsonl` and hands it here, so one
    /// resolver, one failure vocabulary and one payload shape serve three tabs (T130).
    /// </summary>
    public void ShowPersistRef(string? id, EntityShowRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        IEntityResolver? resolver = _options.EntityResolver();
        if (resolver == null)
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
            outcome = resolver.Show(request);
        }
        catch (Exception failure)
        {
            // -1 is not a swPersistReferencedObjectStates_e value: SOLIDWORKS never answered
            // at all (a modal dialog on the application thread, a closed document, an open
            // circuit), which is a different thing from a reference that resolved to nothing.
            outcome = EntityShowOutcome.NotShown(-1, failure.Message, null);
        }

        SendEntityShown(id, outcome);
    }

    /// <summary>
    /// Sends one `entity.shown` for an outcome that is already known.
    ///
    /// Public because a host can know the answer without asking SOLIDWORKS - a change whose
    /// sequence number is not in the change list, or which recorded no persistent reference -
    /// and that answer belongs on the card in the same shape as every other one, not in an
    /// error banner.
    /// </summary>
    public void SendEntityShown(string? id, EntityShowOutcome outcome)
    {
        if (outcome == null)
        {
            throw new ArgumentNullException(nameof(outcome));
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
        if (!TrySafePath(id, report, _options.RunRootsInForce(), out string full))
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

        Shell(id, runDirectory, _options.RunRootsInForce());
    }

    private void OpenLogFolder(string? id)
    {
        string folder = _options.LogFolder();
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

        Shell(id, folder, new[] { folder });
    }

    /// <summary>
    /// The run folder for the id in <paramref name="payload"/>, from the host's own records.
    ///
    /// The page supplies an id and nothing else. Any path it sent is ignored: a page that
    /// could name the path to open could open anything on the workstation with one crafted
    /// message, and the page is the least trusted thing in the process. One lookup for
    /// `report.open`, `folder.open` and `entity.show` (feature 009), so the three cannot
    /// disagree about which run an id names.
    /// </summary>
    private bool TryRunDirectory(string? id, JsonElement payload, out string runDirectory)
    {
        runDirectory = string.Empty;

        PaneRunLookup runs = _options.Runs;
        string key = (PagePayload.Text(payload, runs.IdField) ?? string.Empty).Trim();
        if (key.Length == 0)
        {
            SendError(
                id, "InvalidRequest", $"the message needs a {runs.IdField}.", retryable: false);
            return false;
        }

        string? resolved = runs.Resolve(key);
        if (resolved == null)
        {
            SendError(id, runs.UnknownErrorClass, runs.UnknownMessage(key), retryable: false);
            return false;
        }

        runDirectory = resolved;
        return true;
    }

    /// <summary>
    /// Canonicalizes <paramref name="path"/>, refuses anything that is not inside one of
    /// <paramref name="roots"/>, and opens what is left (pane-host-messages.md: "Every resolved
    /// path is canonicalized and must be a descendant of `run_root` (or the log folder) before
    /// it reaches `ShellExecute`") - every run root in force this session, so a run made under one
    /// a settings save has since moved still opens (owner decision 154A, the reviews' finding F6).
    /// </summary>
    private void Shell(string? id, string path, IReadOnlyList<string> roots)
    {
        if (TrySafePath(id, path, roots, out string full))
        {
            Open(id, full);
        }
    }

    /// <summary>Canonicalizes and refuses anything that is not inside one of <paramref name="roots"/>.</summary>
    private bool TrySafePath(string? id, string path, IReadOnlyList<string> roots, out string full)
    {
        full = string.Empty;

        try
        {
            full = System.IO.Path.GetFullPath(path);
        }
        catch (Exception)
        {
            SendError(id, "PathRefused", "that path cannot be opened.", retryable: false);
            return false;
        }

        // UNC and Win32 device paths are refused by name as well as by containment: a run root
        // that is itself a share would otherwise make `\\server\share\...` a descendant.
        string canonical = full;
        if (full.StartsWith(@"\\", StringComparison.Ordinal) || !roots.Any(root => RunFolders.IsUnder(canonical, root)))
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
            _options.Opener().Open(path);
        }
        catch (Exception failure)
        {
            SendError(id, "OpenFailed", failure.Message, retryable: false);
            return;
        }

        Send("ok", id, new Dictionary<string, object?>());
    }


    // ---- the envelope -------------------------------------------------------------------

    /// <summary>Sends one `{type, id, payload}` document to the page.</summary>
    public void Send(string type, string? id, object? payload)
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
    /// Owner decision 154A: refuses a run start whose run root the run root rule refuses
    /// (<see cref="RunRootRule"/>: on a network share, reached through a link, or written as a device path), and
    /// says whether it did. The one refusal every host makes, written once: <c>error {error_class:
    /// "RunRootRefused"}</c>, not retryable - pressing again cannot help until a local folder for runs is
    /// chosen in the Review tab's Settings (the owner's follow-up) - in the rule's words for what the root is,
    /// with the host's own <paramref name="notDone"/> and <paramref name="wayOn"/>, and no path. Each caller
    /// asks before it does anything else, so a refused start reads, makes and restarts nothing.
    ///
    /// The reviews of 154A's merge, N4: while another folder is saved for runs than the run root in force - a save
    /// chose it and its restart failed - the engineer has chosen a folder already, so the refusal is
    /// <c>RunRootChosenNotInForce</c>, whose way on is the restart that brings the folder chosen in
    /// (<see cref="RunRootRule.ChosenNotInForceRefusal"/>); the saved folder is told apart from the one in force by
    /// <see cref="RunRootRule.SameRunRoot"/>.
    /// </summary>
    /// <param name="runRoot">The run root in force, the one the start would make its folder under.</param>
    /// <param name="probe">What the rule reads of Windows.</param>
    /// <param name="notDone">What was not done, true of this host: "nothing was checked".</param>
    /// <param name="where">Where the Settings are, seen from this tab: <see cref="RunRootRule.InSettings"/>, or
    /// <see cref="RunRootRule.InSettingsOnTheReviewTab"/>.</param>
    /// <param name="wayOn">What to do once the root is a local folder: "press Model check again".</param>
    public bool RefusedRunRoot(string? id, string runRoot, IRunRootProbe probe, string notDone, string where, string wayOn)
    {
        RunRootVerdict verdict = RunRootRule.Judge(runRoot, probe);
        if (verdict == RunRootVerdict.Accepted)
        {
            return false;
        }

        string? saved = _options.RunRootSaved();
        if (saved != null && !RunRootRule.SameRunRoot(saved, runRoot))
        {
            SendError(
                id, "RunRootChosenNotInForce", RunRootRule.ChosenNotInForceRefusal(verdict, notDone, where, wayOn), retryable: false);
            return true;
        }

        SendError(id, "RunRootRefused", RunRootRule.Refusal(verdict, notDone, where, wayOn), retryable: false);
        return true;
    }

    /// <summary>
    /// The reviews of decision 154A, N8, written once for every start that passes a gate (owner decision 157A): the
    /// run root a start goes on under once its gate is passed - the gate can make a waiting settings restart, which
    /// can bring another run root into force - from <paramref name="runRootNow"/>, the run root for a new run read
    /// again then. None, while a start of the backend under way would bring another in, is answered as a start then is
    /// (<see cref="SendRunRootMoving"/>); the one <paramref name="judged"/> before the gate, as written, is gone on
    /// under; another is judged again (<see cref="RefusedRunRoot"/>). Null once the press is answered with a refusal.
    /// </summary>
    public string? RunRootToUse(
        string? id, string judged, string? runRootNow, IRunRootProbe probe, string notDone, string where, string wayOn)
    {
        if (runRootNow == null)
        {
            SendRunRootMoving(id, notDone, wayOn);
            return null;
        }

        if (string.Equals(runRootNow, judged, StringComparison.Ordinal))
        {
            return runRootNow;
        }

        return RefusedRunRoot(id, runRootNow, probe, notDone, where, wayOn) ? null : runRootNow;
    }

    /// <summary>
    /// How a page's word on a settings restart before a press begins (owner decisions 145A and 157A), posted as
    /// `status {stage: "backend_starting"}` before the gate when a restart stands before the press, the press's own
    /// words after it: true whether the gate makes the restart, waits for one being made, or finds a turn or a backend
    /// that does not answer holding it back and refuses the press (145A's third review). The Remodel tab's and the
    /// check tabs' alike.
    /// </summary>
    public const string WaitingForTheRestart =
        "Waiting for the review backend to restart with the saved settings, then ";

    /// <summary>
    /// The reviews of 154A's merge, N6: whether a Model check or a Standards run, whose folder was made before its
    /// extraction, is answered here because the run root moved meanwhile. Since owner decision 157A a check holds every
    /// settings restart back from its gate until its evaluation has been answered while a backend is up, so no restart
    /// moves the run root during the extraction then; a start that brings a backend up where there was none - a save's
    /// made with no backend up, or the add-in's first start - still can, since nothing holds it back, and the backend
    /// would refuse the folder at the page's first call. <paramref name="runRootNow"/> is the run root for a new run
    /// read again once the extraction is over: none, while a start of the backend under way would bring another in, is
    /// answered as a start then is (<see cref="SendRunRootMoving"/>); one that no longer holds the folder,
    /// <c>RunRootChanged</c>, not retryable, in the rule's words (<see cref="RunRootRule.ChangedRefusal"/>). The
    /// folder is left as the evidence.
    /// </summary>
    public bool AnsweredForAMovedRunRoot(
        string? id, string runDirectory, string? runRootNow, string during, string notDone, string wayOn)
    {
        if (runRootNow == null)
        {
            SendRunRootMoving(id, notDone, wayOn);
            return true;
        }

        if (!RunFolders.IsUnder(runDirectory, runRootNow))
        {
            SendError(id, "RunRootChanged", RunRootRule.ChangedRefusal(during, notDone, wayOn), retryable: false);
            return true;
        }

        return false;
    }

    /// <summary>
    /// Owner decision 154A, with 153A's record of the settings in force: refuses a run start on the Model check,
    /// Standards or Remodel tab while a start of the backend under way would bring another run root into force
    /// (<c>ReviewHost.RunRootForANewRun</c> answering none) - <c>error {error_class: "BackendUnavailable"}</c>, as a
    /// review asked for while a start is under way is refused, and retryable, since the start ends in seconds -
    /// in the rule's words (<see cref="RunRootRule.MovingRefusal"/>) with the host's own
    /// <paramref name="notDone"/> and <paramref name="wayOn"/>. Written once for the three.
    /// </summary>
    public void SendRunRootMoving(string? id, string notDone, string wayOn) =>
        SendError(id, "BackendUnavailable", RunRootRule.MovingRefusal(notDone, wayOn), retryable: true);

    /// <summary>Sends one `error`, with the message masked (FR-015).</summary>
    public void SendError(string? id, string errorClass, string message, bool retryable) =>
        Send("error", id, ErrorPayload(errorClass, message, retryable));

    /// <summary>
    /// One `error`'s payload, with the message masked (FR-015): what <see cref="SendError"/> sends, and what an
    /// answer that carries an error's shape inside it - a save's `run_root_refusal` - carries.
    /// </summary>
    public Dictionary<string, object?> ErrorPayload(string errorClass, string message, bool retryable) =>
        new Dictionary<string, object?>
        {
            { "error_class", errorClass },
            { "message", Redact(message) },
            { "retryable", retryable },
        };

    /// <summary>
    /// Posts one `status` message with every secret masked out of it.
    ///
    /// One choke point rather than a rule every call site has to remember: the paths that can
    /// carry a key - a launcher failure, a key-resolution failure, anything thrown before the
    /// redacting wrapper - arrive verbatim, and the caller has no way to mask them (FR-015).
    /// </summary>
    public void PostStatus(string stage, string message) => PostStatus(stage, message, lifecycle: false);

    /// <summary><see cref="PostStatus(string, string)"/>, marked `lifecycle: true` when <paramref name="lifecycle"/>.</summary>
    /// <param name="stage">The stage.</param>
    /// <param name="message">The message, masked here.</param>
    /// <param name="lifecycle">Whether this is the add-in's own word on the backend - its start, or
    /// a restart that failed: a banner the page put up for such an `error` comes down once a later
    /// `init` names a backend, and no other banner does (owner decision 145A, third review), and the
    /// page's backend strip says the backend is not running from such an `error` until then (owner
    /// decision 150A). Nothing else is so marked.</param>
    public void PostStatus(string stage, string message, bool lifecycle)
    {
        Dictionary<string, object?> payload = StatusPayload(stage, message);
        if (lifecycle)
        {
            payload["lifecycle"] = true;
        }

        Send("status", null, payload);
    }

    /// <summary>
    /// A `status` payload - the stage, and the message with every secret masked - for a sender that
    /// adds a field of its own before it sends it (the Review host's `settings_not_in_force`, owner
    /// decision 153A). Every `status` is built here, in one shape.
    /// </summary>
    internal Dictionary<string, object?> StatusPayload(string stage, string message) =>
        new Dictionary<string, object?>
        {
            { "stage", stage },
            { "message", Redact(message) },
        };

    /// <summary>
    /// Tells the page the backend was restarted with saved settings, so the port and token of its
    /// last `init` are the old backend's and it asks `ready` again (owner decisions 143A and 145A):
    /// `backend.restarted {sentences}`. <paramref name="sentences"/> are the host's own sentences
    /// about a restart that waited, which the page takes off its banner - the Review tab's - or
    /// none, for a page that was shown none. One message in one shape for every page that holds
    /// the backend's port and token, sent from one place.
    /// </summary>
    public void PostBackendRestarted(IReadOnlyList<string> sentences) =>
        Send("backend.restarted", null, new Dictionary<string, object?>
        {
            { "sentences", sentences ?? throw new ArgumentNullException(nameof(sentences)) },
        });

    /// <summary>Masks every configured secret in anything headed for the page or the log.</summary>
    public string Redact(string text)
    {
        IEnumerable<string?> secrets;
        try
        {
            secrets = _options.Secrets();
        }
        catch (Exception)
        {
            // Resolving the key must never be the reason an error message cannot be sent.
            secrets = new string?[0];
        }

        return Redaction.Redact(text, secrets);
    }
}
