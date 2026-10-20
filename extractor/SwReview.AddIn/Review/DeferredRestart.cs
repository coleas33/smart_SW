using System;
using System.Threading;

namespace SwReview.AddIn.Review;

/// <summary>
/// Owner decision 143A: the backend restart a settings save could not make because a turn was
/// running, made as soon as nothing holds it back - no turn runs, and no other work the restart
/// would end - with the settings in force at that moment.
///
/// <b>Why it exists.</b> `settings.save` asks whether a turn is running before it writes
/// anything, and <see cref="BackendSupervisor.Restart"/> asks again before it stops the old
/// backend. A turn the page starts in between - a follow-up, an answer or a Send goes to the
/// backend directly, not through the host - leaves the settings written and in force in the
/// host while the backend keeps the environment it was started with. The pane tells the
/// engineer the backend restarts when that turn ends; this is what restarts it.
///
/// <b>One restart, whoever asks.</b> Three callers can carry it out, and each goes through
/// <see cref="Apply"/>: the watcher, which looks every poll at what holds it back; a review
/// the host is about to start, which must run on the restarted backend and never on the old
/// one; and a page call that would start a turn on a chat of the old backend. <see cref="Apply"/>
/// holds one lock for the whole restart and asks again, once it has it, whether a restart is
/// still waiting - so however many ask, the backend restarts once - and the restart reads the
/// settings only then, so several saves during one turn restart it once, with the last of them.
/// A save made when no turn runs restarts it at once (<see cref="Now"/>), under the same lock,
/// and that restart is the one for the settings in force, so anything still waiting is dropped.
///
/// <b>Nothing waits for a turn.</b> <see cref="Apply"/> answers at once, naming what holds the
/// restart back, while something does; the only thing a caller waits for is a restart already
/// being made, which the backend's own start timeouts bound.
///
/// <b>A backend that does not answer is watched, but not for ever.</b> Not knowing whether a turn
/// runs is not knowing that none does, so a look the backend leaves without a usable answer
/// holds the restart back; after <see cref="UnansweredLooks"/> such looks in a row the watcher
/// stops looking and the engineer is told (<c>notAnswered</c>). The restart still waits: the
/// next review or turn call looks once more, through <see cref="Apply"/>, and makes it if the
/// backend has answered that nothing holds it back - so nothing ever runs on the old backend.
/// A save refused again starts a new watcher.
///
/// <b>Disposing</b> stops the watcher and refuses every restart that has not begun. A restart
/// already under way - past the lock's check that one is still waiting - is neither stopped nor
/// waited for here: the backend client's own disposal ends it (BackendClient.Dispose).
/// </summary>
internal sealed class DeferredRestart : IDisposable
{
    /// <summary>
    /// How many looks in a row the backend may leave unanswered before the watcher stops waiting.
    /// Each such look is at least one round trip the backend let time out (30 seconds each, by
    /// BackendClient's call timeout) or refused outright: three in a row is a backend that has
    /// stopped answering, not one that was slow once.
    /// </summary>
    internal const int UnansweredLooks = 3;

    /// <summary>What holds the restart back, as one look at the backend finds it.</summary>
    internal enum Hold
    {
        /// <summary>Nothing: the restart can be made.</summary>
        None,

        /// <summary>A turn is running on the backend.</summary>
        Turn,

        /// <summary>A remodel run is in progress, which the restart would end with its copy half changed.</summary>
        RemodelRun,

        /// <summary>The backend gave no usable answer, so whether a turn runs is not known.</summary>
        NoAnswer,
    }

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

        /// <summary>
        /// A turn holds the restart back - the look found one, or the backend's own check found
        /// one that started after it: nothing was changed, and it still waits.
        /// </summary>
        TurnRunning,

        /// <summary>A remodel run holds the restart back: nothing was changed, and it still waits.</summary>
        RemodelRunning,

        /// <summary>
        /// The backend gave no usable answer to whether a turn runs: nothing was changed, and it
        /// still waits. After <see cref="UnansweredLooks"/> such looks of the watcher's in a row
        /// the watcher stops looking, and the restart waits for the next caller's look.
        /// </summary>
        NotAnswered,

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

    /// <summary>
    /// The shortest poll the watcher can wait out. A wait of less than a millisecond is a wait of
    /// none, and the watcher would spin.
    /// </summary>
    private static readonly TimeSpan ShortestPoll = TimeSpan.FromMilliseconds(1);

    private readonly Func<Hold> _heldBack;
    private readonly Action _restart;
    private readonly Action _restarted;
    private readonly Action<Exception> _failed;
    private readonly Action _notAnswered;
    private readonly TimeSpan _poll;

    /// <summary>
    /// Guards <see cref="_pending"/>, <see cref="_deferrals"/>, <see cref="_disposed"/> and
    /// <see cref="_watcher"/>, and is what the watcher waits on between polls. Never held while
    /// anything slow runs.
    /// </summary>
    private readonly object _state = new object();

    /// <summary>Held for the whole of one restart, so that two never overlap.</summary>
    private readonly object _restarting = new object();

    private bool _pending;

    /// <summary>
    /// One more each time a restart is refused and starts waiting: a newer refusal is a newer
    /// save, and the watcher counts its unanswered looks from that save on.
    /// </summary>
    private long _deferrals;

    private bool _disposed;
    private Thread? _watcher;

    /// <param name="heldBack">What holds the restart back - a turn running, a remodel run the
    /// restart would end, or a backend that does not answer - or nothing; never throws.</param>
    /// <param name="restart">Restarts the backend with the settings in force when it is called.
    /// Throws <see cref="TurnRunningException"/> when the backend's own check finds a turn, and
    /// anything else when the restart fails.</param>
    /// <param name="restarted">Tells the page the backend was replaced.</param>
    /// <param name="failed">Tells the engineer why the restart failed.</param>
    /// <param name="notAnswered">Tells the engineer the watcher stopped looking at a backend that
    /// does not answer, and how to go on. Called while the restart's own lock is held, so that it
    /// lands before anything a later save posts; it must not block.</param>
    /// <param name="poll">How often the watcher looks at what holds the restart back.</param>
    public DeferredRestart(
        Func<Hold> heldBack,
        Action restart,
        Action restarted,
        Action<Exception> failed,
        Action notAnswered,
        TimeSpan poll)
    {
        _heldBack = heldBack ?? throw new ArgumentNullException(nameof(heldBack));
        _restart = restart ?? throw new ArgumentNullException(nameof(restart));
        _restarted = restarted ?? throw new ArgumentNullException(nameof(restarted));
        _failed = failed ?? throw new ArgumentNullException(nameof(failed));
        _notAnswered = notAnswered ?? throw new ArgumentNullException(nameof(notAnswered));
        // Refused here rather than met on the watcher's thread, where an exception from
        // Monitor.Wait would end SOLIDWORKS and a poll under a millisecond would spin it.
        if (poll < ShortestPoll || poll.TotalMilliseconds > int.MaxValue)
        {
            throw new ArgumentOutOfRangeException(
                nameof(poll), poll, "the poll must be at least a millisecond and no longer than a wait can take");
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
    /// Makes the waiting restart now if nothing holds it back, or waits for the one another caller
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
        Hold hold;
        try
        {
            hold = _heldBack();
        }
        catch (Exception)
        {
            hold = Hold.None;
        }

        switch (hold)
        {
            case Hold.Turn:
                return Outcome.TurnRunning;

            case Hold.RemodelRun:
                return Outcome.RemodelRunning;

            case Hold.NoAnswer:
                return Outcome.NotAnswered;
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
    /// Stops the watcher and refuses every restart that has not begun. A restart already under
    /// way is not waited for: the backend client's own disposal ends it, and stops what it started.
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
            _deferrals++;
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

    private long Deferrals()
    {
        lock (_state)
        {
            return _deferrals;
        }
    }

    /// <summary>
    /// The watcher: waits a poll, then asks. It ends when nothing waits any more - the restart
    /// was made, by it or by anyone, or failed, or the owner was disposed - and when it stops
    /// looking at a backend that does not answer, the restart still waiting for the next caller.
    /// </summary>
    private void Watch()
    {
        // The unanswered looks in a row since the save the restart now waits for.
        int unanswered = 0;
        long since = 0;
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
                if (Apply(out _) != Outcome.NotAnswered)
                {
                    unanswered = 0;
                    continue;
                }

                long deferrals = Deferrals();
                if (unanswered == 0 || deferrals != since)
                {
                    since = deferrals;
                    unanswered = 0;
                }

                if (++unanswered >= UnansweredLooks && StopWatching(since))
                {
                    return;
                }
            }
            catch (Exception)
            {
                // Apply answers rather than throws, and reports its own failures; this is the
                // last guard on a background thread inside SOLIDWORKS, where an exception would
                // end the process.
            }
        }
    }

    /// <summary>
    /// Stops this watcher looking at a backend that has not answered, and says so - unless the
    /// restart was made meanwhile, or a newer save is the one now waiting, whose looks are counted
    /// afresh. The restart itself still waits. All of it under the restart's own lock: a restart
    /// being made is never reported as one that was not, and a later save's refusal - made under
    /// the same lock - and the promise it posts after it come after this report, never before.
    /// </summary>
    /// <returns>True when this watcher stops.</returns>
    private bool StopWatching(long since)
    {
        lock (_restarting)
        {
            lock (_state)
            {
                if (_disposed || !_pending || _deferrals != since)
                {
                    return false;
                }

                if (_watcher == Thread.CurrentThread)
                {
                    _watcher = null;
                }
            }

            Report(_notAnswered);
            return true;
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
