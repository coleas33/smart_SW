using System;
using System.Collections.Generic;
using System.Text.Json;
using SwReview.AddIn.Settings;

namespace SwReview.AddIn.Review;

/// <summary>One model the provider offers, as `GET /models` returns it.</summary>
public sealed class ModelChoice
{
    public ModelChoice(string id, string label)
    {
        Id = id ?? throw new ArgumentNullException(nameof(id));
        Label = label ?? id;
    }

    public string Id { get; }

    public string Label { get; }
}

/// <summary>
/// Where the in-process tool service is listening and the secret that authorizes a request to
/// it. Passed to `POST /sessions` as `bridge` so the review's tool calls are served by the
/// running SOLIDWORKS session rather than by a second attach (T047, T048).
/// </summary>
public sealed class BridgeConfig
{
    public BridgeConfig(string pipe, string secret)
    {
        Pipe = pipe ?? throw new ArgumentNullException(nameof(pipe));
        Secret = secret ?? throw new ArgumentNullException(nameof(secret));
    }

    public string Pipe { get; }

    /// <summary>The per-launch review secret. It goes to the backend and nowhere else.</summary>
    public string Secret { get; }
}

/// <summary>Explicit saved context attachment; no local path or native approval claim.</summary>
public sealed class EngineeringContextAttachment
{
    public EngineeringContextAttachment(string contextId, string headDigest, string packageSha256)
    {
        ContextId = contextId ?? throw new ArgumentNullException(nameof(contextId));
        HeadDigest = headDigest ?? throw new ArgumentNullException(nameof(headDigest));
        PackageSha256 = packageSha256 ?? throw new ArgumentNullException(nameof(packageSha256));
    }
    public string ContextId { get; }
    public string HeadDigest { get; }
    public string PackageSha256 { get; }
}

/// <summary>The mutually exclusive review start modes.</summary>
public enum ReviewMode { Send, Wait, Recheck }

/// <summary>The `POST /sessions` body (chat-api.md).</summary>
public sealed class NewSessionRequest
{
    public NewSessionRequest(
        string runDirectory,
        string provider,
        string model,
        string effort,
        string engineer,
        BridgeConfig? bridge,
        string? retryOf,
        string? standardsProfilePath = null,
        ReviewMode mode = ReviewMode.Send,
        EngineeringContextAttachment? engineeringContext = null)
    {
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        Provider = provider ?? throw new ArgumentNullException(nameof(provider));
        Model = model ?? throw new ArgumentNullException(nameof(model));
        Effort = effort ?? throw new ArgumentNullException(nameof(effort));
        Engineer = engineer ?? throw new ArgumentNullException(nameof(engineer));
        Bridge = bridge;
        RetryOf = retryOf;
        StandardsProfilePath = standardsProfilePath;
        Mode = mode;
        EngineeringContext = engineeringContext;
    }

    /// <summary>`run_dir`: the folder the dump was just written into.</summary>
    public string RunDirectory { get; }

    public string Provider { get; }

    public string Model { get; }

    public string Effort { get; }

    /// <summary>Who is reviewing; the report and the dispositions are attributed to them.</summary>
    public string Engineer { get; }

    public BridgeConfig? Bridge { get; }

    /// <summary>The chat this one is retrying, or null (FR-028).</summary>
    public string? RetryOf { get; }

    /// <summary>
    /// The configured Standards profile for the reasoning-side pre-run, or null when the
    /// setting is blank. The backend owns loading and validating the file.
    /// </summary>
    public string? StandardsProfilePath { get; }

    public ReviewMode Mode { get; }

    /// <summary>The exact saved context selected for this review, or null for an ordinary review.</summary>
    public EngineeringContextAttachment? EngineeringContext { get; }
}

/// <summary>What `POST /sessions` returns: `201 {chat_id, review_session_id, not_examined}`.</summary>
public sealed class ChatSessionHandle
{
    public ChatSessionHandle(
        string chatId, string reviewSessionId, JsonElement? notExamined = null)
    {
        ChatId = chatId ?? throw new ArgumentNullException(nameof(chatId));
        ReviewSessionId = reviewSessionId ?? throw new ArgumentNullException(nameof(reviewSessionId));
        NotExamined = notExamined;
    }

    public string ChatId { get; }

    public string ReviewSessionId { get; }

    /// <summary>
    /// The extractor's full warning sentence and its instances, or null when every component
    /// was read. Kept as JSON because this object crosses directly to the page's shared
    /// `#not-examined` renderer and the backend owns the sentence wording.
    /// </summary>
    public JsonElement? NotExamined { get; }
}

/// <summary>
/// A backend call failed. `error_class` is the backend's own (`chat-api.md`: provider failures
/// surface as 502 carrying the provider's error class name), so the page can tell an
/// authentication problem from a connection problem without parsing prose.
/// </summary>
public sealed class BackendRequestException : Exception
{
    public BackendRequestException(string errorClass, string message, bool retryable, Exception? inner = null)
        : this(errorClass, message, retryable, inner, status: null)
    {
    }

    /// <param name="status">The HTTP status the backend answered with (<see cref="Status"/>).</param>
    public BackendRequestException(string errorClass, string message, bool retryable, Exception? inner, int? status)
        : base(message, inner)
    {
        ErrorClass = errorClass;
        Retryable = retryable;
        Status = status;
    }

    public string ErrorClass { get; }

    public bool Retryable { get; }

    /// <summary>
    /// The HTTP status the backend answered the call with; null when no HTTP answer came back -
    /// the connection was refused, reset or timed out, or there was no backend to ask - and for
    /// a refusal that is the add-in's own rather than the backend's. Whether a turn runs is read
    /// from what the backend answered, and only some answers rule one out (owner decision 143A,
    /// ReviewHost.LookAtTheTurns).
    /// </summary>
    public int? Status { get; }
}

/// <summary>
/// Everything <see cref="ReviewHost"/> does with the backend, behind one seam so the host is
/// testable with no Python, no socket and no child process.
///
/// <see cref="Restart"/> lives here with the HTTP calls on purpose: `settings.save` is one
/// operation - write the file, restart the child with the new environment, reply - and
/// splitting "the backend's API" from "the backend's process" across two interfaces would
/// make the host hold both halves and coordinate them, which is the thing this seam exists to
/// avoid. The implementation delegates to <see cref="BackendSupervisor"/>, which owns the
/// no-restart-while-a-turn-runs rule.
/// </summary>
public interface IBackendClient
{
    /// <summary>Where the backend is, or null before it has started (or after it died).</summary>
    BackendEndpoint? Endpoint { get; }

    /// <summary>`GET /models?provider=...`.</summary>
    /// <exception cref="BackendRequestException">The backend or the provider refused.</exception>
    IReadOnlyList<ModelChoice> ListModels(string provider);

    /// <summary>`GET /sessions/{chat_id}` state: whether that chat has a turn running.</summary>
    bool IsTurnRunning(string chatId);

    /// <summary>`POST /sessions`: starts the review turn on an already-dumped run folder.</summary>
    /// <exception cref="BackendRequestException">The backend refused (e.g. `InvalidRunDir`).</exception>
    ChatSessionHandle CreateSession(NewSessionRequest request);

    /// <summary>
    /// Restarts the child with the saved settings and the resolved key in its environment.
    /// </summary>
    /// <exception cref="TurnRunningException">A turn is running; nothing was changed.</exception>
    /// <exception cref="BackendStartException">The new backend would not start.</exception>
    void Restart(UserSettings settings, ResolvedApiKey key);

    /// <summary>
    /// Owner decision 163A (004 research R25): stops the backend in force for a restart that will start the next one with
    /// <see cref="Restart"/> - refusing, as that does, while a turn is running - and answers whether every process of it has
    /// exited, so that it can send the bridge nothing more. Once it is stopped, <see cref="Endpoint"/> is null.
    /// </summary>
    /// <exception cref="TurnRunningException">A turn is running; nothing was stopped.</exception>
    /// <returns>True once the whole backend has exited; false when a process of it was still alive when the bound ran out.</returns>
    bool StopForRestart();
}
