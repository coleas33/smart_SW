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
/// The in-process host's policy (specs/002-task-pane-assistant/contracts/README.md, and
/// feature 004's contracts/bridge-remodel.md, "Authorization"): per-launch secrets naming
/// separate scopes.
///
///   * the <b>review</b> secret, held by the add-in's own review session, authorizes
///     <c>ping | capture | measure | interference | tessellate</c>;
///   * the <b>general-chat</b> secret, handed to the CLI through its generated profile,
///     authorizes <c>ping | capture | measure</c> only;
///   * the <b>remodel</b> secret, handed only to the remodel backend session, authorizes
///     <c>ping</c> and the <c>remodel.*</c> family and nothing else - not <c>capture</c>, not
///     <c>measure</c>, not <c>interference</c>.
///
/// The three scopes are disjoint where it matters, and that is the point: neither of the two
/// read-only scopes can call anything that writes, and the one scope that can write cannot
/// call the review vocabulary. Scoping is what makes the read-only subset promised by FR-022 a
/// boundary rather than a convention: the CLI can read the profile that lists its own tools,
/// so leaving <c>interference</c> out of the MCP allowlist withholds nothing on its own. One
/// shared secret would authenticate without bounding what it authorizes.
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

        // Protocol 1.2, lever 10a. Here and not in the general-chat scope: a mesh fetch
        // writes a file and can take seconds on the one STA worker every other call queues
        // behind, which is a review's cost to pay and not a chat turn's.
        BridgeCommands.Tessellate,

        // Protocol 1.3, feature 011: the confirmed candidate's read-only open answers the
        // review that asked the engineer, and no other scope (contracts/confirmed-open.md
        // section 2).
        BridgeCommands.DrawingRead,
    };

    /// <summary>
    /// What the general-chat secret authorizes: everything but <c>interference</c> and
    /// <c>tessellate</c>.
    /// </summary>
    public static readonly IReadOnlyList<string> GeneralChatCommands = new[]
    {
        BridgeCommands.Ping,
        BridgeCommands.Capture,
        BridgeCommands.Measure,
    };

    /// <summary>
    /// What the remodel secret authorizes: <c>ping</c>, so the run can check the bridge is
    /// alive, and the twelve <c>remodel.*</c> commands by name.
    ///
    /// By name, and not by the <c>remodel.</c> prefix: a prefix would authorize a thirteenth
    /// command the moment somebody named one, which is exactly the accidental widening the
    /// stage-1 allowlist exists to prevent one layer down.
    /// </summary>
    public static readonly IReadOnlyList<string> RemodelScopeCommands = BuildRemodelScope();

    private readonly string _reviewSecret;
    private readonly string _generalChatSecret;

    /// <summary>Null on a host that runs no re-modeler: then no secret authorizes any of it.</summary>
    private readonly string? _remodelSecret;

    /// <param name="remodelSecret">
    /// Feature 004's third scope, handed only to the remodel backend session. Null - the
    /// default - is a host that mints no remodel secret, and then <b>no</b> secret authorizes
    /// a <c>remodel.*</c> command at all, which is the right answer for a host that answers
    /// none of them.
    /// </param>
    public ScopedSecretPolicy(
        string reviewSecret, string generalChatSecret, string? remodelSecret = null)
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

        if (remodelSecret != null)
        {
            Require(remodelSecret, nameof(remodelSecret));

            if (string.Equals(remodelSecret, reviewSecret, StringComparison.Ordinal)
                || string.Equals(remodelSecret, generalChatSecret, StringComparison.Ordinal))
            {
                throw new ArgumentException(
                    "The remodel secret must differ from the review and general-chat secrets; "
                    + "sharing it would give a read-only scope the one scope that writes.",
                    nameof(remodelSecret));
            }
        }

        _reviewSecret = reviewSecret;
        _generalChatSecret = generalChatSecret;
        _remodelSecret = remodelSecret;
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

        if (_remodelSecret != null
            && string.Equals(secret, _remodelSecret, StringComparison.Ordinal))
        {
            return Allows(RemodelScopeCommands, command);
        }

        return false;
    }

    private static IReadOnlyList<string> BuildRemodelScope()
    {
        var scope = new List<string>(RemodelCommands.All.Length + 1) { BridgeCommands.Ping };
        scope.AddRange(RemodelCommands.All);
        return scope;
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
