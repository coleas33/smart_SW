using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>
/// Feature 011 (contracts/confirmed-open.md section 3, guard.md section 7). The guard the
/// confirmed drawing's read-only open is gated by: an <see cref="ICallGuard"/> allowlist of
/// exactly three interface-qualified keys, in the shape of feature 004's
/// <see cref="RemodelGuard"/>, recorded as one entry of its own in
/// <c>specs/004-resilient-remodeler/contracts/guard-allowlist.md</c>.
///
/// Three answers, in this order:
///   1. a key on <see cref="AllowedKeys"/>, matched <b>ordinally</b> so a mis-spelling fails
///      closed rather than widening the surface, returns;
///   2. any other interface-qualified key is refused, because the three keys are the whole of
///      what the seam may do beyond reading; and
///   3. a bare member name - every read - is <see cref="ReadOnlyGuard"/>'s answer, unchanged.
///
/// It adds nothing to <see cref="ReadOnlyGuard"/> or <see cref="RemodelGuard"/>, and it is built
/// only by <c>Sw/DrawingOpenScope.cs</c>. Of the three keys only <c>DocumentVisible</c>
/// overrides a read-only denial (guard.md section 1's shared row); <c>OpenDoc6</c> and
/// <c>CloseDoc</c> are exclusions of guard.md section 3.
/// </summary>
public sealed class DrawingOpenGuard : ICallGuard
{
    /// <summary>
    /// <c>ISldWorks.DocumentVisible(false, swDocDRAWING = 3)</c> before the open, and
    /// <c>(true, 3)</c> in a <c>finally</c> after it: the drawing opens hidden, and the engineer's
    /// window keeps focus.
    /// </summary>
    public const string DocumentVisibleKey = "ISldWorks.DocumentVisible";

    /// <summary>
    /// <c>ISldWorks.OpenDoc6(path, 3, ReadOnly 2 | Silent 1 = 3, "")</c>: the one read-only open,
    /// never view-only, rapid draft or load-model.
    /// </summary>
    public const string OpenDocKey = "ISldWorks.OpenDoc6";

    /// <summary>
    /// <c>ISldWorks.CloseDoc(path)</c>: only when the seam opened this drawing, and only after the
    /// identity check.
    /// </summary>
    public const string CloseDocKey = "ISldWorks.CloseDoc";

    private static readonly HashSet<string> AllowedKeySet = new HashSet<string>(StringComparer.Ordinal)
    {
        DocumentVisibleKey,
        OpenDocKey,
        CloseDocKey,
    };

    /// <summary>The allowlist, for reading: the tests assert it as an exact set.</summary>
    public static readonly IReadOnlyCollection<string> AllowedKeys = AllowedKeySet;

    /// <inheritdoc />
    public void Assert(string interopMemberName)
    {
        if (string.IsNullOrWhiteSpace(interopMemberName))
        {
            throw new ArgumentException("An interop member name is required.", nameof(interopMemberName));
        }

        string key = interopMemberName.Trim();

        if (AllowedKeySet.Contains(key))
        {
            return;
        }

        if (CallKey.IsQualified(key))
        {
            throw new MutatingCallError(
                key,
                $"{key} is not on the confirmed drawing's allowlist ({DocumentVisibleKey}, {OpenDocKey}, "
                + $"{CloseDocKey}; specs/004-resilient-remodeler/contracts/guard-allowlist.md).");
        }

        // A bare member name is a read call site. The read-only rules apply to it unchanged.
        ReadOnlyGuard.Assert(key);
    }
}
