namespace SwReview.Extractor.Guard;

/// <summary>
/// The seam <see cref="Sw.SwGate"/> consults before every interop call (research R6).
///
/// There is exactly one alternative to the read-only guard - <see cref="SuppressTestGuard"/>,
/// which the engineer-run suppress-test builds - and this interface exists so that path does
/// not reach into <see cref="ReadOnlyGuard"/>'s denylist or copy it. An implementation is
/// called synchronously on the SOLIDWORKS thread inside every call, so it allocates nothing.
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
