using System;
using System.Collections.Generic;
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
        string? retryOf)
    {
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        Provider = provider ?? throw new ArgumentNullException(nameof(provider));
        Model = model ?? throw new ArgumentNullException(nameof(model));
        Effort = effort ?? throw new ArgumentNullException(nameof(effort));
        Engineer = engineer ?? throw new ArgumentNullException(nameof(engineer));
        Bridge = bridge;
        RetryOf = retryOf;
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
}

/// <summary>What `POST /sessions` returns: `201 {chat_id, review_session_id}`.</summary>
public sealed class ChatSessionHandle
{
    public ChatSessionHandle(string chatId, string reviewSessionId)
    {
        ChatId = chatId ?? throw new ArgumentNullException(nameof(chatId));
        ReviewSessionId = reviewSessionId ?? throw new ArgumentNullException(nameof(reviewSessionId));
    }

    public string ChatId { get; }

    public string ReviewSessionId { get; }
}

/// <summary>
/// A backend call failed. `error_class` is the backend's own (`chat-api.md`: provider failures
/// surface as 502 carrying the provider's error class name), so the page can tell an
/// authentication problem from a connection problem without parsing prose.
/// </summary>
public sealed class BackendRequestException : Exception
{
    public BackendRequestException(string errorClass, string message, bool retryable, Exception? inner = null)
        : base(message, inner)
    {
        ErrorClass = errorClass;
        Retryable = retryable;
    }

    public string ErrorClass { get; }

    public bool Retryable { get; }
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
}
