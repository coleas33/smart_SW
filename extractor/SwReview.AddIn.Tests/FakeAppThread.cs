using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using SwReview.AddIn.ToolService;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The SOLIDWORKS application thread, played by a thread of its own: <c>Post</c> queues the work
/// and the thread runs it in order, so a test can assert which thread a request was executed on
/// (<see cref="ThreadId"/>) and from which it was handed there (<see cref="PostThreads"/>). In
/// manual mode nothing runs until <see cref="ReleaseOne"/>, which is what a modal dialog looks
/// like from the pipe. Shared by the in-process server's tests and the tool service's wiring
/// tests, which drive the same request path.
/// </summary>
internal sealed class FakeAppThread : IAppThreadInvoker, IDisposable
{
    private readonly BlockingCollection<Action> _queue = new BlockingCollection<Action>();
    private readonly SemaphoreSlim? _permits;
    private readonly ManualResetEventSlim _started = new ManualResetEventSlim(false);
    private readonly Thread _thread;
    private readonly List<int> _postThreads = new List<int>();
    private int _posted;
    private int _ran;

    public FakeAppThread(bool manual = false)
    {
        _permits = manual ? new SemaphoreSlim(0) : null;
        _thread = new Thread(Loop) { IsBackground = true, Name = "fake-solidworks-app-thread" };
        _thread.Start();
        _started.Wait(TimeSpan.FromSeconds(10));
    }

    /// <summary>Whether the pane control would accept an invoke.</summary>
    public bool CanInvokeValue { get; set; } = true;

    /// <summary>What <c>BeginInvoke</c> throws, if anything.</summary>
    public Exception? PostFailure { get; set; }

    public int ThreadId { get; private set; }

    /// <summary>How many calls have been handed to the application thread.</summary>
    public int Posted => Volatile.Read(ref _posted);

    /// <summary>How many have actually run there.</summary>
    public int Ran => Volatile.Read(ref _ran);

    public IReadOnlyList<int> PostThreads
    {
        get
        {
            lock (_postThreads)
            {
                return _postThreads.ToArray();
            }
        }
    }

    bool IAppThreadInvoker.CanInvoke => CanInvokeValue;

    void IAppThreadInvoker.Post(Action work)
    {
        lock (_postThreads)
        {
            _postThreads.Add(Thread.CurrentThread.ManagedThreadId);
        }

        if (PostFailure != null)
        {
            throw PostFailure;
        }

        Interlocked.Increment(ref _posted);
        _queue.Add(work);
    }

    /// <summary>Lets one held call run (manual mode only).</summary>
    public void ReleaseOne() => _permits!.Release();

    public void Dispose()
    {
        _queue.CompleteAdding();
        _permits?.Release(1000);
        _thread.Join(TimeSpan.FromSeconds(5));
        _started.Dispose();
        _permits?.Dispose();
        _queue.Dispose();
    }

    private void Loop()
    {
        ThreadId = Thread.CurrentThread.ManagedThreadId;
        _started.Set();

        foreach (Action work in _queue.GetConsumingEnumerable())
        {
            _permits?.Wait();
            try
            {
                work();
            }
            finally
            {
                Interlocked.Increment(ref _ran);
            }
        }
    }
}
