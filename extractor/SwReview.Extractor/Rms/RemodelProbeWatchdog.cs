using System;
using System.Globalization;
using System.Threading;
using System.Threading.Tasks;

namespace SwReview.Extractor.Rms;

/// <summary>
/// One watchdog-timed attempt's outcome: either the call returned before its deadline
/// (<see cref="Completed"/> true, <see cref="Result"/> its answer), or the deadline came first
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

    /// <summary>False means the call did not return before its deadline - it is presumed blocked, never awaited further.</summary>
    public bool Completed { get; }

    /// <summary>What the call returned. Meaningless when <see cref="Completed"/> is false.</summary>
    public bool Result { get; }
}

/// <summary>
/// PROBE-1's one piece of infrastructure: running a call that <b>might never return</b> - a
/// SOLIDWORKS interop call that can raise a modal message box on the STA thread it holds - and
/// reporting whether it blocked, without ever waiting on it past its deadline.
///
/// The verdict is decided by signals, never by a race (013 contracts/readings.md section 4, 004
/// T171): the call runs on a thread of its own, never the pool, so no queue can delay it; the
/// deadline starts only once the call has begun, so a loaded machine can never read as a block;
/// and whichever of the two finishes first decides. A test hands in a deadline it controls ("the
/// call has parked", or "never"); production's is <see cref="Deadline"/>, a timer.
///
/// The call still runs for as long as it likes: nothing here can safely abort a thread stuck
/// inside a synchronous COM call, and killing the process is the caller's decision, never this
/// class's. A blocked call's thread is simply abandoned; on the real workstation, a genuinely
/// blocked "Cannot reorder" dialog will still be sitting on SOLIDWORKS's own message loop after
/// this returns; see PROBE-1's own tasks.md fallback ("Phases 5 and 8 stop until the owner
/// decides") for why running PROBE-1 alone, with <c>--probe PROBE-1</c>, is the order on the
/// workstation.
/// </summary>
public static class RemodelProbeWatchdog
{
    /// <summary>
    /// The production timeout: long enough that a real SOLIDWORKS interop call which is simply
    /// slow (not blocked) has every chance to finish, short enough that a genuinely blocked
    /// call is reported - never waited on - in a run a human is watching. It is counted from the
    /// moment the call has begun, not from when it was asked for.
    /// </summary>
    public static readonly TimeSpan DefaultTimeout = TimeSpan.FromSeconds(5);

    /// <summary>
    /// How long <see cref="Run"/> waits for the call's thread to begin before failing: a thread of
    /// its own starts at once, so a start this late means the machine cannot run the probe at
    /// all, which is an explicit error and never a verdict.
    /// </summary>
    public static readonly TimeSpan StartBound = TimeSpan.FromSeconds(30);

    /// <summary>The production deadline: <paramref name="timeout"/> on a timer, cancelled once the call answers.</summary>
    public static Func<CancellationToken, Task> Deadline(TimeSpan timeout) => token => Task.Delay(timeout, token);

    /// <summary>
    /// Runs <paramref name="call"/> on a thread of its own and waits for it or for
    /// <paramref name="deadline"/>, whichever finishes first. The deadline is asked for only once
    /// the call has signalled that it began; a call whose thread has not begun within
    /// <paramref name="startBound"/> is a <see cref="TimeoutException"/>, and the deadline is then
    /// never started. A call that answers first returns its answer and cancels the deadline; a
    /// call that throws first rethrows the host's own exception, never a wrapper; a deadline that
    /// finishes first is <see cref="RemodelProbeWatchdogOutcome.Blocked"/>.
    /// </summary>
    /// <param name="startCall">
    /// How the call's thread is started: null for a thread of its own (production). A test passes
    /// its own to hold the call before its first line and see that no deadline starts meanwhile.
    /// </param>
    public static RemodelProbeWatchdogOutcome Run(
        Func<bool> call,
        Func<CancellationToken, Task> deadline,
        TimeSpan startBound,
        Func<Func<bool>, Task<bool>>? startCall = null)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        if (deadline == null)
        {
            throw new ArgumentNullException(nameof(deadline));
        }

        // Completed inline on the call's thread: a signal that waited for a pool thread to be
        // delivered would put the pool's queue back into the verdict.
        var started = new TaskCompletionSource<bool>();
        Task<bool> answer = (startCall ?? OnAThreadOfItsOwn)(() =>
        {
            started.TrySetResult(true);
            return call();
        });

        if (Task.WaitAny(new Task[] { started.Task, answer }, startBound) < 0)
        {
            throw new TimeoutException(
                $"The watched call did not start within {startBound.TotalSeconds.ToString(CultureInfo.InvariantCulture)} "
                + "seconds, so whether it blocks was not measured.");
        }

        if (!started.Task.IsCompleted)
        {
            // The thread ended without running the call: its own failure, rethrown as it was.
            answer.GetAwaiter().GetResult();
            throw new InvalidOperationException("The watched call's thread ended without running the call.");
        }

        using (var cancel = new CancellationTokenSource())
        {
            Task clock = deadline(cancel.Token)
                ?? throw new InvalidOperationException("The watchdog's deadline factory answered no task.");

            if (Task.WaitAny(answer, clock) != 0)
            {
                return RemodelProbeWatchdogOutcome.Blocked;
            }

            cancel.Cancel();
            return RemodelProbeWatchdogOutcome.Returned(answer.GetAwaiter().GetResult());
        }
    }

    /// <summary>
    /// The production wrapper: <see cref="Run"/> with <see cref="Deadline"/>(<paramref name="timeout"/>)
    /// and <see cref="StartBound"/>. Never re-enters <paramref name="call"/> and never blocks the
    /// caller past <paramref name="timeout"/> once the call has begun, whatever it does.
    /// </summary>
    public static RemodelProbeWatchdogOutcome RunWithTimeout(Func<bool> call, TimeSpan timeout) =>
        Run(call, Deadline(timeout), StartBound);

    private static Task<bool> OnAThreadOfItsOwn(Func<bool> body) =>
        Task.Factory.StartNew(body, CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
}
