using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>
/// The guard the engineer-run suppress-test builds its gate with (research R6, contracts
/// cli.md): <see cref="ReadOnlyGuard"/> minus exactly two members.
///
/// The test suppresses one Detail feature, rebuilds, reads the error count, and restores the
/// tree, so it needs <c>IFeature.SetSuppression2</c> and <c>IModelDoc2.ForceRebuild3</c> and
/// nothing else. It is written as an exemption over the read-only guard rather than as its
/// own list so that every member added to the denylist is refused here the same day - and so
/// that the hundreds of getters the extraction surface uses need no enumeration.
///
/// Reached only from the console <c>suppress-test</c> command. The add-in, the bridge and
/// the MCP server never build one.
/// </summary>
public sealed class SuppressTestGuard : ICallGuard
{
    /// <summary>
    /// The whole exemption set. Anything else the read-only guard refuses is still refused,
    /// including <c>ForceRebuildAll</c>, <c>EditRollback</c>, <c>SetSaveFlag</c>, <c>Save3</c>
    /// and every feature-creation family.
    /// </summary>
    private static readonly HashSet<string> ExemptMembers = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "SetSuppression2",
        "ForceRebuild3",
    };

    /// <inheritdoc />
    public void Assert(string interopMemberName)
    {
        if (!string.IsNullOrWhiteSpace(interopMemberName)
            && ExemptMembers.Contains(interopMemberName.Trim()))
        {
            return;
        }

        // Everything else - including a missing member name - is the read-only guard's answer.
        ReadOnlyGuard.Assert(interopMemberName);
    }
}
