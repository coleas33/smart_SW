using System;
using System.Threading.Tasks;

namespace SwReview.Extractor.Rms;

/// <summary>
/// One watchdog-timed attempt's outcome: either <paramref name="call"/> returned within the
/// timeout (<see cref="Completed"/> true, <see cref="Result"/> its answer), or it did not
/// (<see cref="Completed"/> false, <see cref="Result"/> unset) - PROBE-1's whole question, for
/// one of its two attempts.
/// </summary>
public readonly struct RemodelProbeWatchdogOutcome
{
    private RemodelProbeWatchdogOutcome(bool completed, bool result)
    {
        Completed = completed;
        Result = result;
    }

    public static RemodelProbeWatchdogOutcome Returned(bool result) => new RemodelProbeWatchdogOutcome(true, result);

    public static readonly RemodelProbeWatchdogOutcome Blocked = new RemodelProbeWatchdogOutcome(false, false);

    /// <summary>False means <paramref name="call"/> did not return inside the timeout - it is presumed blocked, never awaited further.</summary>
    public bool Completed { get; }

    /// <summary>What the call returned. Meaningless when <see cref="Completed"/> is false.</summary>
    public bool Result { get; }
}

/// <summary>
/// PROBE-1's one piece of infrastructure: running a call that <b>might never return</b> - a
/// SOLIDWORKS interop call that can raise a modal message box on the STA thread it holds - and
/// reporting whether it blocked, without ever waiting on it past a bounded timeout.
///
/// The call still runs, on a background thread, for as long as it likes: nothing here can
/// safely abort a thread stuck inside a synchronous COM call, and killing the process is the
/// caller's decision, never this class's. A timed-out call's thread is simply abandoned; on the
/// real workstation, a genuinely blocked "Cannot reorder" dialog will still be sitting on
/// SOLIDWORKS's own message loop after this returns; see PROBE-1's own tasks.md fallback
/// ("Phases 5 and 8 stop until the owner decides") for why running PROBE-1 alone first, with
/// <c>--probe PROBE-1</c>, is the recommended order on the workstation.
/// </summary>
public static class RemodelProbeWatchdog
{
    /// <summary>
    /// The production timeout: long enough that a real SOLIDWORKS interop call which is simply
    /// slow (not blocked) has every chance to finish, short enough that a genuinely blocked
    /// call is reported - never waited on - in a run a human is watching.
    /// </summary>
    public static readonly TimeSpan DefaultTimeout = TimeSpan.FromSeconds(5);

    /// <summary>
    /// Runs <paramref name="call"/> on a background thread and waits at most
    /// <paramref name="timeout"/> for it. Never re-enters <paramref name="call"/> and never
    /// blocks the caller past <paramref name="timeout"/>, whatever <paramref name="call"/> does.
    /// </summary>
    public static RemodelProbeWatchdogOutcome RunWithTimeout(Func<bool> call, TimeSpan timeout)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        Task<bool> task = Task.Run(call);
        bool completedInTime = task.Wait(timeout);

        // task.IsFaulted here means the call itself threw within the timeout - that is not a
        // hang, and it is not this class's job to interpret; the caller sees it because
        // task.Result re-raises it (wrapped), which is exactly what awaiting the call directly
        // would have done.
        return completedInTime ? RemodelProbeWatchdogOutcome.Returned(task.Result) : RemodelProbeWatchdogOutcome.Blocked;
    }
}
