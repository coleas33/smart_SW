using System;
using System.Threading;
using System.Threading.Tasks;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// PROBE-1's watchdog (013 contracts/readings.md section 4, 004 T171): running a call that might
/// never return, and reporting "blocked" without ever waiting on it - decided by signals the test
/// controls, never by a race against a clock. A deadline here is "never" for a call that returns
/// or throws and "the call has parked" for one that blocks; the one production-timer test runs in
/// the blocking direction only, where no load can change the answer.
/// </summary>
public class RemodelProbeWatchdogTests
{
    /// <summary>How long a test waits for a watchdog that must already have answered, before failing rather than hanging.</summary>
    private static readonly TimeSpan Bound = TimeSpan.FromSeconds(30);

    private static Task NeverFires(CancellationToken _) => new TaskCompletionSource<bool>().Task;

    /// <summary>
    /// A call that blocks until <see cref="Dispose"/>: <see cref="HasParked"/> completes the moment
    /// it blocks, which is the deadline a blocking script uses.
    /// </summary>
    private sealed class ParkedCall : IDisposable
    {
        private readonly TaskCompletionSource<bool> _parked = new TaskCompletionSource<bool>();

        private readonly ManualResetEventSlim _release = new ManualResetEventSlim(false);

        public Task HasParked => _parked.Task;

        public bool Call()
        {
            _parked.TrySetResult(true);
            _release.Wait();
            return true;
        }

        public void Dispose() => _release.Set();
    }

    /// <summary>Runs the watchdog off the test's thread and fails, rather than hangs, if it waits on a blocked call.</summary>
    private static RemodelProbeWatchdogOutcome Answered(Func<RemodelProbeWatchdogOutcome> watch) =>
        Finished(OnAThreadOfItsOwn(watch));

    private static Task<T> OnAThreadOfItsOwn<T>(Func<T> work) =>
        Task.Factory.StartNew(work, CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

    /// <summary>The answer of a watchdog that must already be answering; a failure, never a hang, when it is not.</summary>
    private static T Finished<T>(Task<T> running)
    {
        Assert.True(running.Wait(Bound), "The watchdog waited on a blocked call instead of answering.");
        return running.Result;
    }

    [Fact]
    public void Run_CallReturnsTrue_WithADeadlineThatNeverFires_ReportsCompletedTrue()
    {
        RemodelProbeWatchdogOutcome outcome = RemodelProbeWatchdog.Run(() => true, NeverFires, Bound);

        Assert.True(outcome.Completed);
        Assert.True(outcome.Result);
    }

    [Fact]
    public void Run_CallReturnsFalse_WithADeadlineThatNeverFires_ReportsCompletedFalse()
    {
        RemodelProbeWatchdogOutcome outcome = RemodelProbeWatchdog.Run(() => false, NeverFires, Bound);

        Assert.True(outcome.Completed);
        Assert.False(outcome.Result);
    }

    [Fact]
    public void Run_CallThrows_RethrowsTheHostsOwnExceptionNotAWrapper()
    {
        InvalidOperationException error = Assert.Throws<InvalidOperationException>(() => RemodelProbeWatchdog.Run(
            () => throw new InvalidOperationException("ReorderFeature raised a modal"), NeverFires, Bound));

        Assert.Equal("ReorderFeature raised a modal", error.Message);
    }

    [Fact]
    public void Run_CallParked_WithAFiringDeadline_ReportsBlockedPromptly()
    {
        using var parked = new ParkedCall();

        RemodelProbeWatchdogOutcome outcome = Answered(
            () => RemodelProbeWatchdog.Run(parked.Call, _ => parked.HasParked, Bound));

        Assert.False(outcome.Completed);
    }

    [Fact]
    public void Run_TheCallRunsOnAThreadOfItsOwn_NeverThePool()
    {
        // The pool's queue is what a loaded machine delays; a thread of its own starts at once.
        bool? onThePool = null;

        RemodelProbeWatchdog.Run(
            () =>
            {
                onThePool = Thread.CurrentThread.IsThreadPoolThread;
                return true;
            },
            NeverFires,
            Bound);

        Assert.False(onThePool);
    }

    [Fact]
    public void Run_ACallThatNeverStarts_FailsExplicitlyAfterTheStartBound_AndNeverStartsTheDeadline()
    {
        // The deadline starts only once the call has begun: a call held before its first line
        // never starts the clock, so a queue can never read as a block.
        bool deadlineInvoked = false;

        TimeoutException error = Assert.Throws<TimeoutException>(() => RemodelProbeWatchdog.Run(
            () => true,
            _ =>
            {
                deadlineInvoked = true;
                return NeverFires(CancellationToken.None);
            },
            TimeSpan.FromMilliseconds(50),
            startCall: _ => new TaskCompletionSource<bool>().Task));

        Assert.False(deadlineInvoked);
        Assert.Contains("did not start", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Run_StartsTheDeadlineOnlyOnceTheCallHasBegun()
    {
        using var holding = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        int deadlinesInvoked = 0;
        bool invokedWhileHeld = true;

        Task<RemodelProbeWatchdogOutcome> running = OnAThreadOfItsOwn(
            () => RemodelProbeWatchdog.Run(
                () => true,
                _ =>
                {
                    Interlocked.Increment(ref deadlinesInvoked);
                    return NeverFires(CancellationToken.None);
                },
                Bound,
                startCall: body => OnAThreadOfItsOwn(
                    () =>
                    {
                        holding.Set();
                        release.Wait();
                        return body();
                    })));

        Assert.True(holding.Wait(Bound));
        invokedWhileHeld = Volatile.Read(ref deadlinesInvoked) > 0;
        release.Set();

        RemodelProbeWatchdogOutcome outcome = Finished(running);
        Assert.False(invokedWhileHeld);
        Assert.True(outcome.Completed);
        Assert.Equal(1, deadlinesInvoked);
    }

    [Fact]
    public void Run_WhenTheCallAnswersFirst_CancelsTheDeadline()
    {
        CancellationToken seen = default;

        RemodelProbeWatchdog.Run(
            () => true,
            token =>
            {
                seen = token;
                return Task.Delay(Timeout.Infinite, token);
            },
            Bound);

        Assert.True(seen.IsCancellationRequested);
    }

    [Fact]
    public void Run_NullArguments_Throw()
    {
        Assert.Throws<ArgumentNullException>(() => RemodelProbeWatchdog.Run(null!, NeverFires, Bound));
        Assert.Throws<ArgumentNullException>(() => RemodelProbeWatchdog.Run(() => true, null!, Bound));
    }

    [Fact]
    public void Run_ADeadlineFactoryThatAnswersNoTask_IsRefusedByName()
    {
        InvalidOperationException error = Assert.Throws<InvalidOperationException>(
            () => RemodelProbeWatchdog.Run(() => true, _ => null!, Bound));

        Assert.Contains("deadline", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void RunWithTimeout_TheProductionTimer_ReportsAParkedCallBlocked()
    {
        // The one test on the production timer, in the blocking direction only: however loaded
        // the machine, a parked call is still parked when the timer fires.
        using var parked = new ParkedCall();

        RemodelProbeWatchdogOutcome outcome = Answered(
            () => RemodelProbeWatchdog.RunWithTimeout(parked.Call, TimeSpan.FromMilliseconds(50)));

        Assert.False(outcome.Completed);
    }

    [Fact]
    public void RunWithTimeout_NullCall_Throws()
    {
        Assert.Throws<ArgumentNullException>(
            () => RemodelProbeWatchdog.RunWithTimeout(null!, RemodelProbeWatchdog.DefaultTimeout));
    }

    // ---- PROBE-1's pure decision, independent of how the watchdog was run --------------

    [Fact]
    public void Decide_NeitherAttemptBlocked_IsUnresolved()
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe1Logic.Decide(blockedWithFlagClear: false, blockedWithFlagSet: false);
        Assert.Equal(RemodelProbeVerdict.Unresolved, verdict);
    }

    [Fact]
    public void Decide_BlockedOnlyWithFlagClear_IsVerified()
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe1Logic.Decide(blockedWithFlagClear: true, blockedWithFlagSet: false);
        Assert.Equal(RemodelProbeVerdict.Verified, verdict);
    }

    [Fact]
    public void Decide_BlockedWithBothFlags_IsRefuted()
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe1Logic.Decide(blockedWithFlagClear: true, blockedWithFlagSet: true);
        Assert.Equal(RemodelProbeVerdict.Refuted, verdict);
    }

    [Fact]
    public void Decide_BlockedOnlyWithFlagSet_IsUnresolved()
    {
        (RemodelProbeVerdict verdict, _) = RemodelProbe1Logic.Decide(blockedWithFlagClear: false, blockedWithFlagSet: true);
        Assert.Equal(RemodelProbeVerdict.Unresolved, verdict);
    }

    [Fact]
    public void Decide_EveryOutcomeNamesAReason()
    {
        foreach (bool clear in new[] { false, true })
        {
            foreach (bool set in new[] { false, true })
            {
                (_, string reason) = RemodelProbe1Logic.Decide(clear, set);
                Assert.False(string.IsNullOrWhiteSpace(reason));
            }
        }
    }
}
