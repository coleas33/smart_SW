using System;
using SwReview.Extractor.Guard;

namespace SwReview.Extractor.Sw;

/// <summary>
/// Watches what passes through a <see cref="SwGate"/> (feature 002, T047).
///
/// The add-in's tool-service log records, per request, the distinct set of interop member
/// names the gate was asked about and any <see cref="MutatingCallError"/> it raised; that
/// log is the artifact SC-004 is audited against, and nothing else in the process can see
/// those names. A per-call log line would be tens of thousands of writes on the SOLIDWORKS
/// thread, so the gate reports and the observer decides what to keep.
///
/// Called on the gate's own thread, synchronously, inside every interop call: an
/// implementation that allocates or blocks is paid for on the SOLIDWORKS thread.
/// </summary>
public interface ISwGateObserver
{
    /// <summary>Every member the gate is asked about, before the guard has judged it.</summary>
    void Gated(string interopMember);

    /// <summary>The guard refused <paramref name="refusal"/>; it is about to be thrown.</summary>
    void Refused(MutatingCallError refusal);
}

/// <summary>
/// The single door every SOLIDWORKS interop call goes through. Two jobs, both required by
/// the constitution: the member name is checked against <see cref="ReadOnlyGuard"/> before
/// the call runs (the assistant inspects reviewed models, it never edits them), and the
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

    /// <summary>
    /// Optional: told about every member this gate is asked about, and about every refusal
    /// (T047). Null - the console host and every dump - costs one null check per call.
    /// </summary>
    public ISwGateObserver? Observer { get; set; }

    /// <summary>Guards, then runs, an interop call that returns a value.</summary>
    public T Call<T>(string interopMember, Func<T> call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        Guard(interopMember);
        return _breaker.Execute(call);
    }

    /// <summary>Guards, then runs, an interop call that returns nothing.</summary>
    public void Call(string interopMember, Action call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        Guard(interopMember);
        _breaker.Execute<object?>(() =>
        {
            call();
            return null;
        });
    }

    /// <summary>
    /// The guard check, with the observer told what happened. The member is reported before
    /// the guard judges it, so a refused name is in the gated set as well as in the refusals:
    /// the SC-004 audit reads "what did this request touch", and a call that was attempted
    /// and refused is part of that answer.
    /// </summary>
    private void Guard(string interopMember)
    {
        ISwGateObserver? observer = Observer;
        if (observer == null)
        {
            ReadOnlyGuard.Assert(interopMember);
            return;
        }

        observer.Gated(interopMember);
        try
        {
            ReadOnlyGuard.Assert(interopMember);
        }
        catch (MutatingCallError refusal)
        {
            observer.Refused(refusal);
            throw;
        }
    }
}
