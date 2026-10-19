using System;
using System.Threading;

namespace SwReview.AddIn.Review;

/// <summary>
/// Owner decision 143A: the backend restart a settings save could not make because a turn was
/// running, made as soon as no turn runs, with the settings in force at that moment.
///
/// <b>Why it exists.</b> `settings.save` asks whether a turn is running before it writes
/// anything, and <see cref="BackendSupervisor.Restart"/> asks again before it stops the old
/// backend. A turn the page starts in between - a follow-up, an answer or a Send goes to the
/// backend directly, not through the host - leaves the settings written and in force in the
/// host while the backend keeps the environment it was started with. The pane tells the
/// engineer the backend restarts when that turn ends; this is what restarts it.
///
/// <b>One restart, whoever asks.</b> Three callers can carry it out, and each goes through
/// <see cref="Apply"/>: the watcher, which asks every poll whether a turn still runs; a review
/// the host is about to start, which must run on the restarted backend and never on the old
/// one; and a page call that would start a turn on a chat of the old backend. <see cref="Apply"/>
/// holds one lock for the whole restart and asks again, once it has it, whether a restart is
/// still waiting - so however many ask, the backend restarts once - and the restart reads the
/// settings only then, so several saves during one turn restart it once, with the last of them.
/// A save made when no turn runs restarts it at once (<see cref="Now"/>), under the same lock,
/// and that restart is the one for the settings in force, so anything still waiting is dropped.
///
/// <b>Nothing waits for a turn.</b> <see cref="Apply"/> answers <see cref="Outcome.TurnRunning"/>
/// at once while one runs; the only thing a caller waits for is a restart already being made,
/// which the backend's own start timeouts bound. <see cref="Dispose"/> stops the watcher without
/// waiting for a restart in flight, and nothing is restarted after it.
/// </summary>
internal sealed class DeferredRestart : IDisposable
{
    /// <summary>What one <see cref="Apply"/> did.</summary>
    internal enum Outcome
    {
        /// <summary>
        /// No restart was waiting once the lock was taken: there was none, or another caller had
        /// just made it.
        /// </summary>
        NotPending,

        /// <summary>This call restarted the backend with the settings in force.</summary>
        Restarted,

        /// <summary>A turn is running: nothing was changed, and the restart still waits.</summary>
        TurnRunning,

        /// <summary>
        /// The restart was tried and failed. The failure has been reported, and nothing waits
        /// any more: the next save is the engineer's retry, as after any failed start.
        /// </summary>
        Failed,

        /// <summary>The owner was disposed: nothing was changed, and nothing ever will be.</summary>
        Stopped,
    }

    /// <summary>
    /// How long <see cref="Dispose"/> waits for the watcher to notice, like the page pumps'
    /// bound: it may be inside a round trip or a restart, and SOLIDWORKS is not made to wait.
    /// </summary>
    private static readonly TimeSpan StopTimeout = TimeSpan.FromSeconds(2);

    private readonly Func<bool> _anyTurnRunning;
    private readonly Action _restart;
    private readonly Action _restarted;
    private readonly Action<Exception> _failed;
    private readonly TimeSpan _poll;

    /// <summary>
    /// Guards <see cref="_pending"/>, <see cref="_disposed"/> and <see cref="_watcher"/>, and is
    /// what the watcher waits on between polls. Never held while anything slow runs.
    /// </summary>
    private readonly object _state = new object();

    /// <summary>Held for the whole of one restart, so that two never overlap.</summary>
    private readonly object _restarting = new object();

    private bool _pending;
    private bool _disposed;
    private Thread? _watcher;

    /// <param name="anyTurnRunning">Whether any chat has a turn running; never throws.</param>
    /// <param name="restart">Restarts the backend with the settings in force when it is called.
    /// Throws <see cref="TurnRunningException"/> when the backend's own check finds a turn, and
    /// anything else when the restart fails.</param>
    /// <param name="restarted">Tells the page the backend was replaced.</param>
    /// <param name="failed">Tells the engineer why the restart failed.</param>
    /// <param name="poll">How often the watcher asks whether a turn still runs.</param>
    public DeferredRestart(
        Func<bool> anyTurnRunning, Action restart, Action restarted, Action<Exception> failed, TimeSpan poll)
    {
        _anyTurnRunning = anyTurnRunning ?? throw new ArgumentNullException(nameof(anyTurnRunning));
        _restart = restart ?? throw new ArgumentNullException(nameof(restart));
        _restarted = restarted ?? throw new ArgumentNullException(nameof(restarted));
        _failed = failed ?? throw new ArgumentNullException(nameof(failed));
        if (poll <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(poll), poll, "the poll must be positive");
        }

        _poll = poll;
    }

    /// <summary>Whether a restart is waiting for the turns that are running to end.</summary>
    public bool Pending
    {
        get
        {
            lock (_state)
            {
                return _pending;
            }
        }
    }

    /// <summary>
    /// The restart a save makes when it saw no turn running, under the lock a deferred restart
    /// holds: the two never overlap, and whichever comes second reads the newer settings.
    /// </summary>
    /// <param name="restart">The restart, with the settings just saved.</param>
    /// <returns>True when the backend was restarted now; false when the backend's own check
    /// found a turn that started after the save's, in which case the restart waits for it.</returns>
    /// <exception cref="Exception">Whatever <paramref name="restart"/> throws other than
    /// <see cref="TurnRunningException"/>, unchanged: the save answers it as it always has.</exception>
    public bool Now(Action restart)
    {
        if (restart == null)
        {
            throw new ArgumentNullException(nameof(restart));
        }

        lock (_restarting)
        {
            try
            {
                restart();
            }
            catch (TurnRunningException)
            {
                Defer();
                return false;
            }
            catch (Exception)
            {
                // The restart for the settings in force was tried and failed. Retrying it when
                // the turns end would fail the same way; the failure is the save's to report.
                Drop();
                throw;
            }

            Drop();
            return true;
        }
    }

    /// <summary>
    /// Makes the waiting restart now if no turn is running, or waits for the one another caller
    /// is making. Never throws: a failure is reported through the callback and answered as
    /// <see cref="Outcome.Failed"/>, with the exception in <paramref name="failure"/>.
    /// </summary>
    public Outcome Apply(out Exception? failure)
    {
        failure = null;
        Outcome? settled = Settled();
        if (settled.HasValue)
        {
            return settled.Value;
        }

        // Asked before the lock is taken, because it is a round trip per chat and a save or a
        // new review that wants the lock must not queue behind it. The backend asks again before
        // it stops anything (BackendSupervisor.Restart), which is the check that decides - so a
        // look that cannot be made is not a reason to throw, nor to restart unchecked.
        bool running;
        try
        {
            running = _anyTurnRunning();
        }
        catch (Exception)
        {
            running = false;
        }

        if (running)
        {
            return Outcome.TurnRunning;
        }

        lock (_restarting)
        {
            settled = Settled();
            if (settled.HasValue)
            {
                return settled.Value;
            }

            try
            {
                _restart();
            }
            catch (TurnRunningException)
            {
                // A turn started after the look above. Nothing was changed, so it still waits.
                return Outcome.TurnRunning;
            }
            catch (Exception caught)
            {
                // Every failure, not only a BackendStartException: this runs on the watcher's
                // thread or a proxied request's, where nothing may escape, and a restart that
                // failed unseen is the silence this class exists to end.
                Drop();
                failure = caught;
                Report(() => _failed(caught));
                return Outcome.Failed;
            }

            Drop();
            Report(_restarted);
            return Outcome.Restarted;
        }
    }

    /// <summary>
    /// Stops the watcher and refuses every later restart. A restart already in flight is not
    /// waited for: the backend client's own disposal sees it out, and stops what it started.
    /// </summary>
    public void Dispose()
    {
        Thread? watcher;
        lock (_state)
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            _pending = false;
            watcher = _watcher;
            _watcher = null;
            Monitor.PulseAll(_state);
        }

        if (watcher != null && watcher != Thread.CurrentThread)
        {
            watcher.Join(StopTimeout);
        }
    }

    /// <summary>The outcome when there is nothing to restart, or null when a restart waits.</summary>
    private Outcome? Settled()
    {
        lock (_state)
        {
            if (_disposed)
            {
                return Outcome.Stopped;
            }

            return _pending ? (Outcome?)null : Outcome.NotPending;
        }
    }

    /// <summary>A restart waits from now on, and the watcher is started if it is not running.</summary>
    private void Defer()
    {
        lock (_state)
        {
            if (_disposed)
            {
                return;
            }

            _pending = true;
            if (_watcher != null)
            {
                return;
            }

            _watcher = new Thread(Watch)
            {
                IsBackground = true,
                Name = "swreview-settings-restart",
            };
            _watcher.Start();
        }
    }

    private void Drop()
    {
        lock (_state)
        {
            _pending = false;
        }
    }

    /// <summary>
    /// The watcher: waits a poll, then asks. It ends when nothing waits any more - the restart
    /// was made, by it or by anyone, or failed, or the owner was disposed.
    /// </summary>
    private void Watch()
    {
        while (true)
        {
            lock (_state)
            {
                if (!_disposed && _pending)
                {
                    Monitor.Wait(_state, _poll);
                }

                if (_disposed || !_pending)
                {
                    if (_watcher == Thread.CurrentThread)
                    {
                        _watcher = null;
                    }

                    return;
                }
            }

            try
            {
                Apply(out _);
            }
            catch (Exception)
            {
                // Apply answers rather than throws, and reports its own failures; this is the
                // last guard on a background thread inside SOLIDWORKS, where an exception would
                // end the process.
            }
        }
    }

    /// <summary>A report that cannot be made must not turn a made restart into a thrown one.</summary>
    private static void Report(Action report)
    {
        try
        {
            report();
        }
        catch (Exception)
        {
            // Posting to the page swallows its own failures; this is the guard for anything else.
        }
    }
}
