namespace SwReview.AddIn.Remodel;

/// <summary>
/// Putting the copy in front of the engineer, behind one seam.
///
/// One member, and it is here rather than on <see cref="IRemodelBackend"/> because it is the
/// one thing in this feature that is neither a bridge call nor a dump: activating a document is
/// a SOLIDWORKS UI action on the application thread, and the bridge's remodel vocabulary
/// deliberately has no command for it (`contracts/bridge-remodel.md` opens the copy once, at
/// `remodel.open`, and closes it; it never activates one on the engineer's behalf).
///
/// The seam exists so `remodel.open_copy` is testable with no seat, which is the same reason
/// <see cref="Review.IReviewDump"/> exists. The real implementation is
/// <see cref="SwRemodelSeat"/>.
///
/// The extractor has an <c>IRemodelSeat</c> of its own (<c>SwReview.Extractor.Rms</c>) and this
/// is not it: that one is the bridge's view of the application - the probe reads, the one open
/// of the copy, the close - and this one is the pane's single UI action. They are in different namespaces and neither
/// file imports the other's, so the name is never ambiguous at a use site.
/// </summary>
public interface IRemodelSeat
{
    /// <summary>
    /// Activates the copy, opening it again if the engineer closed it.
    ///
    /// <paramref name="copyPath"/> is always a file inside a run folder's `copy/`, resolved by
    /// the caller from a run this host created: the page never supplies a path.
    /// </summary>
    void ActivateOrOpen(string copyPath);
}
