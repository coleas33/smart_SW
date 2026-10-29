using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>
/// Owner decision 144A (feature 011, 2026-10-19; research R11, contracts/guard.md section 8). The
/// guard the re-modeler's pane seat - the add-in's <c>SwRemodelSeat</c>: <c>remodel.open_copy</c>,
/// and the activation of the run's copy before each dump (feature 004 T159) - builds its gate with:
/// an <see cref="ICallGuard"/> allowlist, recorded as one entry of its own in
/// <c>specs/004-resilient-remodeler/contracts/guard-allowlist.md</c>.
///
/// <b>A closed allowlist</b> since owner decision 148A (2026-10-20; research R12.1): exactly the
/// seat's own calls, and nothing else. Three answers, in this order:
///   1. a key on <see cref="AllowedKeys"/> - the activation and the open, by their interface-qualified
///      keys - matched <b>ordinally</b>, so a mis-spelling fails closed rather than widening the
///      surface, returns;
///   2. a read on <see cref="AllowedReads"/> - the five the seat makes, by the bare names it gates them
///      under - matched ordinally too, returns; and
///   3. any other name, bare or qualified, is refused, naming it.
///
/// Until decision 148A a bare name was <see cref="ReadOnlyGuard"/>'s answer, as it is in
/// <see cref="DrawingOpenGuard"/>, so the bare <c>CloseDoc</c>, <c>OpenDoc6</c> and <c>OpenDoc7</c> the read-only
/// guard left allowed passed this one too (research R11.7, finding 3). The tests hold each read on the list
/// to a bare name the read-only guard allows, so the list can never name a writer it refuses, and hold the
/// list to the members the seat's gate is asked about, way by way.
///
/// It sees member names, never documents: that the seat opens or activates the run's copy and
/// nothing else is the seat's own check, made before the first call and after each lookup or open
/// (the copy's path must be a part inside a run folder's <c>copy/</c>, and the document SOLIDWORKS
/// answers must be at that path), as <c>RemodelScope</c> is <see cref="RemodelGuard"/>'s second layer.
/// It adds nothing to <see cref="ReadOnlyGuard"/>, <see cref="RemodelGuard"/> or
/// <see cref="DrawingOpenGuard"/>, and it is built only by
/// <c>SwRemodelSeat</c>. Both keys override a read-only denial (the shared <c>ISldWorks</c> row of
/// contracts/guard.md section 1): <c>ActivateDoc3</c> since feature 011's T004, and <c>OpenDoc7</c>
/// since owner decision 148A, which had the open's two other callers - <c>remodel.open</c>, under
/// <see cref="RemodelGuard"/>, and <c>probe remodel</c>'s reopen, under <see cref="RemodelProbeGuard"/> -
/// name it by this key too, and the read-only guard refuse the bare name.
///
/// Since owner decision 151A (2026-10-20; research R13.1) the three answers are
/// <see cref="AllowlistGuard"/>'s, the rule the product's three allowlist guards share, with this guard's
/// bare names its own reads alone (<see cref="BareNamePolicy.OwnReadsOnly"/>): this class keeps its keys,
/// its reads, its words for a refusal - one sentence for any name off its list, as before - and its one
/// construction site.
/// </summary>
public sealed class RemodelSeatGuard : AllowlistGuard
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
    public static readonly IReadOnlyCollection<string> AllowedKeys = new ReadOnlySet<string>(AllowedKeySet);

    /// <summary>
    /// Decision 148A: the reads the seat makes, by the bare names every read call site of the product
    /// gives them - the lookup of the copy among the documents SOLIDWORKS has open, a document's path and
    /// its title, the active document after an activation, and the open request <c>OpenDoc7</c> takes.
    /// </summary>
    private static readonly HashSet<string> AllowedReadSet = new HashSet<string>(StringComparer.Ordinal)
    {
        "GetOpenDocumentByName",
        "GetPathName",
        "GetTitle",
        "ActiveDoc",
        "GetOpenDocSpec",
    };

    /// <summary>The reads the seat makes, for reading: the tests assert them as an exact set.</summary>
    public static readonly IReadOnlyCollection<string> AllowedReads = new ReadOnlySet<string>(AllowedReadSet);

    /// <summary>A closed allowlist: the seat's two keys and its five reads, and no other name.</summary>
    public RemodelSeatGuard()
        : base(AllowedKeySet, AllowedReadSet)
    {
    }

    /// <inheritdoc />
    protected override string Refusal(string key) =>
        $"{key} is not on the re-modeler pane seat's allowlist, which holds the seat's own calls and "
        + $"nothing else: {ActivateDocKey}, {OpenDocKey} and the reads "
        + string.Join(", ", AllowedReadSet)
        + " (specs/004-resilient-remodeler/contracts/guard-allowlist.md).";
}
