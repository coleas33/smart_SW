namespace SwReview.Extractor.Guard;

/// <summary>
/// The seam <see cref="Sw.SwGate"/> consults before every interop call (research R6).
///
/// There is exactly one alternative to the read-only guard - <see cref="SuppressTestGuard"/>,
/// which the engineer-run suppress-test builds - and this interface exists so that path does
/// not reach into <see cref="ReadOnlyGuard"/>'s denylist or copy it. An implementation is
/// called synchronously on the SOLIDWORKS thread inside every call, so it allocates nothing.
/// (Corrected 2026-10-19 on decision 144A's review, and again on its second review: that was true
/// when it was written. The alternatives are five now - <see cref="SuppressTestGuard"/> and
/// <see cref="RemodelProbeGuard"/>, each built by one of the console's gate factories;
/// <see cref="DrawingOpenGuard"/>, by the confirmed drawing's scope; <see cref="RemodelSeatGuard"/>,
/// by the re-modeler's pane seat; and <see cref="RemodelGuard"/>, by the add-in's tool service and by
/// the bridge's dispatcher when it is handed no gate - and the extractor's <c>GuardSweepTests</c>
/// holds the list the tests sweep to every guard the product defines. Since owner decision 151A,
/// 2026-10-20, the last three - the allowlists - answer through one shared rule,
/// <see cref="AllowlistGuard"/>.)
/// </summary>
public interface ICallGuard
{
    /// <summary>
    /// Throws <see cref="MutatingCallError"/> if this guard refuses the named interop
    /// member, and <see cref="System.ArgumentException"/> if no member was named.
    /// </summary>
    void Assert(string interopMemberName);
}

/// <summary>
/// The instance form of <see cref="ReadOnlyGuard"/>, and the guard every gate gets unless
/// it names another one. Stateless, so one shared instance serves every thread.
/// </summary>
public sealed class ReadOnlyCallGuard : ICallGuard
{
    /// <summary>The shared read-only guard.</summary>
    public static readonly ReadOnlyCallGuard Instance = new ReadOnlyCallGuard();

    private ReadOnlyCallGuard()
    {
    }

    /// <inheritdoc />
    public void Assert(string interopMemberName) => ReadOnlyGuard.Assert(interopMemberName);
}
