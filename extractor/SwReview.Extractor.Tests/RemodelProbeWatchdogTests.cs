using System;
using System.Diagnostics;
using System.Threading;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// PROBE-1's watchdog: running a call that might never return, and reporting "blocked" without
/// ever waiting on it past a bounded timeout.
/// </summary>
public class RemodelProbeWatchdogTests
{
    // Short enough that "blocked" tests stay fast, generous enough that a trivial Task.Run
    // scheduling delay under CI load never makes a genuinely-quick call look blocked.
    private static readonly TimeSpan ShortTimeout = TimeSpan.FromMilliseconds(50);
    private static readonly TimeSpan GenerousTimeout = TimeSpan.FromSeconds(2);

    [Fact]
    public void RunWithTimeout_CallReturnsQuickly_ReportsCompletedWithItsAnswer()
    {
        RemodelProbeWatchdogOutcome outcome = RemodelProbeWatchdog.RunWithTimeout(() => true, GenerousTimeout);

        Assert.True(outcome.Completed);
        Assert.True(outcome.Result);
    }

    [Fact]
    public void RunWithTimeout_CallReturnsFalseQuickly_ReportsCompletedWithFalse()
    {
        RemodelProbeWatchdogOutcome outcome = RemodelProbeWatchdog.RunWithTimeout(() => false, GenerousTimeout);

        Assert.True(outcome.Completed);
        Assert.False(outcome.Result);
    }

    [Fact]
    public void RunWithTimeout_CallNeverReturns_ReportsBlockedAndReturnsPromptly()
    {
        // A host whose interop call blocks forever - a message box nothing will ever dismiss.
        // This must never be waited on past the timeout, so the whole test is bounded well
        // under a second even though the scripted call itself never completes.
        var stopwatch = Stopwatch.StartNew();

        RemodelProbeWatchdogOutcome outcome = RemodelProbeWatchdog.RunWithTimeout(
            () =>
            {
                Thread.Sleep(Timeout.Infinite);
                return true; // unreachable
            },
            ShortTimeout);

        stopwatch.Stop();

        Assert.False(outcome.Completed);
        Assert.True(
            stopwatch.Elapsed < TimeSpan.FromSeconds(5),
            $"RunWithTimeout took {stopwatch.Elapsed}, far longer than its {ShortTimeout} timeout; it must never wait on a blocked call.");
    }

    [Fact]
    public void RunWithTimeout_NullCall_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => RemodelProbeWatchdog.RunWithTimeout(null!, ShortTimeout));
    }

    [Fact]
    public void RunWithTimeout_CallThrows_PropagatesTheException()
    {
        Assert.ThrowsAny<Exception>(() => RemodelProbeWatchdog.RunWithTimeout(
            () => throw new InvalidOperationException("ReorderFeature raised a modal"), GenerousTimeout));
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
