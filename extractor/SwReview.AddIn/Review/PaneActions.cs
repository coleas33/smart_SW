using System;
using System.Collections.Generic;
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
    }

    public IPageChannel Channel { get; }

    public Func<string> RunRoot { get; }

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

        EntityShowOutcome outcome;
        try
        {
            outcome = resolver.Show(new EntityShowRequest(
                persistRef,
                PagePayload.Blank(PagePayload.Text(payload, "persist_ref_scope")),

                // The page decides which instance of a part to show and sends that component's
                // id; the host passes it through and never picks one for the engineer.
                PagePayload.Blank(PagePayload.Text(payload, "component_id"))));
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
        if (!TrySafePath(id, report, _options.RunRoot(), out string full))
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

        Shell(id, runDirectory, _options.RunRoot());
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

        Shell(id, folder, folder);
    }

    /// <summary>
    /// The run folder for the id in <paramref name="payload"/>, from the host's own records.
    ///
    /// The page supplies an id and nothing else. Any path it sent is ignored: a page that
    /// could name the path to open could open anything on the workstation with one crafted
    /// message, and the page is the least trusted thing in the process.
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
            _options.Opener().Open(path);
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

    /// <summary>Sends one `error`, with the message masked (FR-015).</summary>
    public void SendError(string? id, string errorClass, string message, bool retryable)
    {
        Send("error", id, new Dictionary<string, object?>
        {
            { "error_class", errorClass },
            { "message", Redact(message) },
            { "retryable", retryable },
        });
    }

    /// <summary>
    /// Posts one `status` message with every secret masked out of it.
    ///
    /// One choke point rather than a rule every call site has to remember: the paths that can
    /// carry a key - a launcher failure, a key-resolution failure, anything thrown before the
    /// redacting wrapper - arrive verbatim, and the caller has no way to mask them (FR-015).
    /// </summary>
    public void PostStatus(string stage, string message) =>
        Send("status", null, new Dictionary<string, object?>
        {
            { "stage", stage },
            { "message", Redact(message) },
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
