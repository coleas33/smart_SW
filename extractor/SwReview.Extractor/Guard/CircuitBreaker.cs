using System;
using System.Runtime.InteropServices;

namespace SwReview.Extractor.Guard;

/// <summary>
/// Raised when the circuit is open: SOLIDWORKS has failed repeatedly and further calls are
/// refused until <see cref="CircuitBreaker.Reset"/> is called. The reviewer turns this into
/// failed coverage rather than a passing check (Principle I).
/// </summary>
[Serializable]
public class CircuitOpenError : Exception
{
    public CircuitOpenError(string message)
        : base(message)
    {
    }
}

/// <summary>
/// Stops hammering a SOLIDWORKS session that has stopped answering (research R4, adapted
/// from the MIT-licensed solidworks-skills pattern; attribution lands in NOTICE.md, T101).
///
/// A COM failure in a running session is almost never transient: the application is modal,
/// the session died, or an interop pointer went stale. After
/// <see cref="DefaultFailureThreshold"/> consecutive COM or invalid-operation failures the
/// breaker opens and every later call fails immediately, so the review reports the gap
/// instead of blocking on a dead process.
///
/// Not thread-safe by design: every COM call runs on the single STA worker thread that owns
/// the SldWorks pointer (constitution, Technical Constraints), and that thread owns one
/// breaker.
/// </summary>
public sealed class CircuitBreaker
{
    public const int DefaultFailureThreshold = 3;

    private int _consecutiveFailures;

    public CircuitBreaker()
        : this(DefaultFailureThreshold)
    {
    }

    public CircuitBreaker(int failureThreshold)
    {
        if (failureThreshold < 1)
        {
            throw new ArgumentOutOfRangeException(
                nameof(failureThreshold), failureThreshold, "The failure threshold must be at least 1.");
        }

        FailureThreshold = failureThreshold;
    }

    /// <summary>Consecutive failures needed to open the circuit.</summary>
    public int FailureThreshold { get; }

    /// <summary>Consecutive COM failures since the last success or reset.</summary>
    public int ConsecutiveFailures => _consecutiveFailures;

    /// <summary>True once the threshold is reached; stays true until <see cref="Reset"/>.</summary>
    public bool IsOpen => _consecutiveFailures >= FailureThreshold;

    /// <summary>
    /// Runs <paramref name="operation"/> unless the circuit is open. A success clears the
    /// failure count; a COM or invalid-operation failure increments it and is rethrown
    /// unchanged, so the caller still sees the real error that opened the circuit.
    /// Any other exception type propagates without counting: it is a bug in our code, not a
    /// sick SOLIDWORKS session.
    /// </summary>
    public T Execute<T>(Func<T> operation)
    {
        if (operation == null)
        {
            throw new ArgumentNullException(nameof(operation));
        }

        ThrowIfOpen();

        try
        {
            T result = operation();
            _consecutiveFailures = 0;
            return result;
        }
        catch (COMException)
        {
            _consecutiveFailures++;
            throw;
        }
        catch (InvalidOperationException)
        {
            _consecutiveFailures++;
            throw;
        }
    }

    /// <summary>
    /// Runs an OPTIONAL read (feature 010): one whose failure the caller records as a gap on that
    /// one value, such as a Hole Wizard field SOLIDWORKS may not answer for a hole type. An open
    /// circuit refuses it exactly as <see cref="Execute{T}"/> does, and a success clears the count
    /// because the session answered; a failure is rethrown unchanged and is NOT counted. A
    /// property refused on every hole of one type therefore cannot open the circuit by itself,
    /// while a dead session still opens it on the next counted call.
    /// </summary>
    public T ExecuteOptional<T>(Func<T> operation)
    {
        if (operation == null)
        {
            throw new ArgumentNullException(nameof(operation));
        }

        ThrowIfOpen();

        T result = operation();
        _consecutiveFailures = 0;
        return result;
    }

    /// <summary>Refuses every call while the circuit is open, naming the count that opened it.</summary>
    private void ThrowIfOpen()
    {
        if (IsOpen)
        {
            throw new CircuitOpenError(
                $"The SOLIDWORKS circuit is open after {_consecutiveFailures} consecutive failures. "
                + "Call Reset() once the session is known good.");
        }
    }

    /// <summary>Closes the circuit and clears the failure count.</summary>
    public void Reset()
    {
        _consecutiveFailures = 0;
    }
}
