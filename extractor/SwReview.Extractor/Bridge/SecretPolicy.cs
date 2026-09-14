using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Bridge;

/// <summary>
/// T045. Decides whether the <see cref="BridgeRequest.Secret"/> on a line authorizes that
/// line's command.
///
/// Injected into <see cref="SwBridgeDispatcher"/> rather than baked into it, because the
/// two hosts differ and the command handling must not be duplicated to say so:
///
///   * the console host (<c>swreview-extract serve</c>) issues no secret - its boundary is
///     the named pipe an engineer started at the workstation - so it uses
///     <see cref="NoSecretPolicy"/>;
///   * the add-in's in-process host issues two per-launch secrets and requires one on every
///     line, so it uses <see cref="ScopedSecretPolicy"/>.
/// </summary>
public interface ISecretPolicy
{
    /// <summary>
    /// True when <paramref name="command"/> may run for <paramref name="secret"/>. A false
    /// answer becomes <c>status: "error"</c>, <c>error: "unauthorized"</c> - the same
    /// answer whether the secret was wrong, missing, or right but out of scope, so a
    /// caller learns nothing from the difference.
    /// </summary>
    bool IsAuthorized(string? secret, string command);
}

/// <summary>
/// The console host's policy: there is no secret, so every command is authorized and the
/// <c>secret</c> field on a request is ignored. A client written for the in-process host
/// therefore still works against <c>serve</c>.
/// </summary>
public sealed class NoSecretPolicy : ISecretPolicy
{
    public static readonly NoSecretPolicy Instance = new NoSecretPolicy();

    private NoSecretPolicy()
    {
    }

    public bool IsAuthorized(string? secret, string command) => true;
}

/// <summary>
/// The in-process host's policy (specs/002-task-pane-assistant/contracts/README.md): two
/// per-launch secrets naming two scopes.
///
///   * the <b>review</b> secret, held by the add-in's own review session, authorizes
///     <c>ping | capture | measure | interference</c>;
///   * the <b>general-chat</b> secret, handed to the CLI through its generated profile,
///     authorizes <c>ping | capture | measure</c> only.
///
/// Scoping is what makes the read-only subset promised by FR-022 a boundary rather than a
/// convention: the CLI can read the profile that lists its own tools, so leaving
/// <c>interference</c> out of the MCP allowlist withholds nothing on its own. One shared
/// secret would authenticate without bounding what it authorizes.
/// </summary>
public sealed class ScopedSecretPolicy : ISecretPolicy
{
    /// <summary>What the review-session secret authorizes: the whole vocabulary.</summary>
    public static readonly IReadOnlyList<string> ReviewCommands = new[]
    {
        BridgeCommands.Ping,
        BridgeCommands.Capture,
        BridgeCommands.Measure,
        BridgeCommands.Interference,
    };

    /// <summary>What the general-chat secret authorizes: everything but <c>interference</c>.</summary>
    public static readonly IReadOnlyList<string> GeneralChatCommands = new[]
    {
        BridgeCommands.Ping,
        BridgeCommands.Capture,
        BridgeCommands.Measure,
    };

    private readonly string _reviewSecret;
    private readonly string _generalChatSecret;

    public ScopedSecretPolicy(string reviewSecret, string generalChatSecret)
    {
        // An empty secret would be matched by a line that simply omits the field, which
        // would turn "required" into "optional" without anyone noticing.
        Require(reviewSecret, nameof(reviewSecret));
        Require(generalChatSecret, nameof(generalChatSecret));

        if (string.Equals(reviewSecret, generalChatSecret, StringComparison.Ordinal))
        {
            throw new ArgumentException(
                "The review and general-chat secrets must differ; one secret for both "
                + "scopes would authenticate without bounding what it authorizes.",
                nameof(generalChatSecret));
        }

        _reviewSecret = reviewSecret;
        _generalChatSecret = generalChatSecret;
    }

    public bool IsAuthorized(string? secret, string command)
    {
        if (string.IsNullOrEmpty(secret) || string.IsNullOrEmpty(command))
        {
            return false;
        }

        // Ordinal, so no culture ever makes two different secrets compare equal.
        if (string.Equals(secret, _reviewSecret, StringComparison.Ordinal))
        {
            return Allows(ReviewCommands, command);
        }

        if (string.Equals(secret, _generalChatSecret, StringComparison.Ordinal))
        {
            return Allows(GeneralChatCommands, command);
        }

        return false;
    }

    private static bool Allows(IReadOnlyList<string> scope, string command)
    {
        for (int i = 0; i < scope.Count; i++)
        {
            if (string.Equals(scope[i], command, StringComparison.Ordinal))
            {
                return true;
            }
        }

        // A command outside the vocabulary - "rebuild", "Save3" - is in no scope, so it is
        // refused here too and never reaches the read-only guard.
        return false;
    }

    private static void Require(string secret, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(secret))
        {
            throw new ArgumentException(
                "A per-launch secret is required and must not be empty.", parameterName);
        }
    }
}
