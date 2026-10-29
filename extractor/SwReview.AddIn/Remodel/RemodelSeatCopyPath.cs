using System;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// Owner decision 144A (feature 011, research R11.1 and its review): the run's copy, as the
/// re-modeler's pane seat (<see cref="SwRemodelSeat"/>) takes it before SOLIDWORKS is asked anything.
/// Its own file, so the seat's source holds only the calls the interop manifest's audit reads.
///
/// Since owner decision 148A (research R12.3) the rule is not the seat's own: it is
/// <see cref="RemodelCopy.CopyOf"/>, the one rule both seats take the copy by - the bridge's
/// <c>remodel.open</c> too - and this is the seat's door to it, which answers a path the rule refuses as
/// the seat always has: an <see cref="ArgumentException"/>, the caller's mistake, since the pipeline
/// resolves the copy from a run this host made. The seat uses the canonical form the rule answers for
/// every call and comparison after the check, so what SOLIDWORKS is handed is what was checked.
/// </summary>
internal static class RemodelSeatCopyPath
{
    /// <summary>
    /// The canonical form of <paramref name="copyPath"/> and the run folder it sits in, by
    /// <see cref="RemodelCopy.CopyOf"/>, or an <see cref="ArgumentException"/> carrying that rule's refusal.
    /// </summary>
    public static (string Path, string RunDirectory) Of(string copyPath)
    {
        if (copyPath == null)
        {
            throw new ArgumentNullException(nameof(copyPath));
        }

        try
        {
            return RemodelCopy.CopyOf(copyPath);
        }
        catch (MutatingCallError refusal)
        {
            throw new ArgumentException(refusal.Message, nameof(copyPath), refusal);
        }
    }
}
