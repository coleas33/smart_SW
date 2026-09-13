using System;
using SwReview.Extractor.Guard;

namespace SwReview.Extractor.Sw;

/// <summary>
/// The single door every SOLIDWORKS interop call goes through. Two jobs, both required by
/// the constitution: the member name is checked against <see cref="ReadOnlyGuard"/> before
/// the call runs (the assistant inspects customer models, it never edits them), and the
/// call is wrapped in a <see cref="CircuitBreaker"/> so a dead session stops the dump
/// instead of producing hundreds of identical failures.
///
/// Call sites read as <c>_sw.Call("GetChildren", () =&gt; component.GetChildren())</c>: the
/// string is the member the guard is asked about, so a new API family cannot be reached
/// without naming it.
///
/// Not thread-safe, by design: one gate per STA worker thread that owns the SldWorks
/// pointer (constitution, Technical Constraints).
/// </summary>
public sealed class SwGate
{
    private readonly CircuitBreaker _breaker;

    public SwGate()
        : this(new CircuitBreaker())
    {
    }

    public SwGate(CircuitBreaker breaker)
    {
        _breaker = breaker ?? throw new ArgumentNullException(nameof(breaker));
    }

    /// <summary>The breaker this gate counts failures against.</summary>
    public CircuitBreaker Breaker => _breaker;

    /// <summary>Guards, then runs, an interop call that returns a value.</summary>
    public T Call<T>(string interopMember, Func<T> call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        ReadOnlyGuard.Assert(interopMember);
        return _breaker.Execute(call);
    }

    /// <summary>Guards, then runs, an interop call that returns nothing.</summary>
    public void Call(string interopMember, Action call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        ReadOnlyGuard.Assert(interopMember);
        _breaker.Execute<object?>(() =>
        {
            call();
            return null;
        });
    }
}
