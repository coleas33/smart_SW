using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>
/// Owner decision 144A (feature 011, 2026-10-19; research R11, contracts/guard.md section 8). The
/// guard the re-modeler's pane seat - the add-in's <c>SwRemodelSeat</c>: <c>remodel.open_copy</c>,
/// and the activation of the run's copy before each dump (feature 004 T159) - builds its gate with:
/// an <see cref="ICallGuard"/> allowlist of exactly two interface-qualified keys, in the shape of
/// <see cref="DrawingOpenGuard"/>, recorded as one entry of its own in
/// <c>specs/004-resilient-remodeler/contracts/guard-allowlist.md</c>.
///
/// Three answers, in this order:
///   1. a key on <see cref="AllowedKeys"/>, matched <b>ordinally</b> so a mis-spelling fails
///      closed rather than widening the surface, returns;
///   2. any other interface-qualified key is refused, because the two keys are the whole of what
///      the seat may do beyond reading; and
///   3. a bare member name - every read - is <see cref="ReadOnlyGuard"/>'s answer, unchanged.
///
/// It sees member names, never documents: that the seat opens or activates the run's copy and
/// nothing else is the seat's own check, made before the first call and after each lookup or open
/// (the copy's path must be a part inside a run folder's <c>copy/</c>, and the document SOLIDWORKS
/// answers must be at that path), as <c>RemodelScope</c> is <see cref="RemodelGuard"/>'s second
/// layer. It adds nothing to <see cref="ReadOnlyGuard"/>, <see cref="RemodelGuard"/> or
/// <see cref="DrawingOpenGuard"/>, and it is built only by <c>SwRemodelSeat</c>. Of the two keys
/// only <c>ActivateDoc3</c> overrides a read-only denial (the shared <c>ISldWorks</c> row of
/// contracts/guard.md section 1); <c>OpenDoc7</c> is an exclusion of section 3.
/// </summary>
public sealed class RemodelSeatGuard : ICallGuard
{
    /// <summary>
    /// <c>ISldWorks.ActivateDoc3(title, false, swDontRebuildActiveDoc = 1, ref errors)</c>: the run's
    /// copy made the active document, by its title, without a rebuild.
    /// </summary>
    public const string ActivateDocKey = "ISldWorks.ActivateDoc3";

    /// <summary>
    /// <c>ISldWorks.OpenDoc7(request)</c>: the run's copy opened again when the engineer closed it,
    /// <c>Silent | LoadModel = 17</c> and never <c>ReadOnly</c> or <c>ViewOnly</c>, since the copy
    /// opens writable for the engineer's Save As.
    /// </summary>
    public const string OpenDocKey = "ISldWorks.OpenDoc7";

    private static readonly HashSet<string> AllowedKeySet = new HashSet<string>(StringComparer.Ordinal)
    {
        ActivateDocKey,
        OpenDocKey,
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
                $"{key} is not on the re-modeler pane seat's allowlist ({ActivateDocKey}, {OpenDocKey}; "
                + "specs/004-resilient-remodeler/contracts/guard-allowlist.md).");
        }

        // A bare member name is a read call site. The read-only rules apply to it unchanged.
        ReadOnlyGuard.Assert(key);
    }
}
