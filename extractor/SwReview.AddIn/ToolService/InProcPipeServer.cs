using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using SwReview.Extractor.Bridge;

namespace SwReview.AddIn.ToolService;

/// <summary>
/// How the tool service reaches the thread SOLIDWORKS runs on.
///
/// An interface, and not because a second implementation is planned: the real one is
/// <see cref="Control.BeginInvoke(Delegate)"/> on the Task Pane control, which needs a
/// created window handle and a pumping message loop, and the three failure modes that matter
/// here - the handle is gone, the thread never answers, the delegate answers far too late -
/// are then testable without SOLIDWORKS and without a message loop.
/// </summary>
public interface IAppThreadInvoker
{
    /// <summary>
    /// False when a call would throw: the control has no handle yet, or it was destroyed
    /// while the add-in unloaded. Checked before every marshalled call, and still raced -
    /// see <see cref="Post"/>.
    /// </summary>
    bool CanInvoke { get; }

    /// <summary>
    /// Queues <paramref name="work"/> onto the application thread and returns immediately.
    /// Throws if the handle went away between the <see cref="CanInvoke"/> check and here;
    /// the caller turns that into a response rather than letting it reach a reader thread.
    /// </summary>
    void Post(Action work);
}

/// <summary>
/// The real invoker: <c>BeginInvoke</c> on the Task Pane control, whose thread is the thread
/// that owns the <c>ISldWorks</c> pointer (research R6).
/// </summary>
public sealed class ControlAppThreadInvoker : IAppThreadInvoker
{
    private readonly Control _control;

    public ControlAppThreadInvoker(Control control)
    {
        _control = control ?? throw new ArgumentNullException(nameof(control));
    }

    public bool CanInvoke
    {
        get
        {
            try
            {
                // Both, and in this order: a disposed control answers IsHandleCreated false
                // anyway, but reading IsDisposed first says what is actually true when the
                // add-in is unloading.
                return !_control.IsDisposed && _control.IsHandleCreated;
            }
            catch (ObjectDisposedException)
            {
                return false;
            }
        }
    }

    /// <summary>
    /// No second check here. The handle can be destroyed between <see cref="CanInvoke"/> and
    /// this line whatever we do, so the throw is the contract and
    /// <see cref="InProcPipeServer"/> answers it.
    /// </summary>
    public void Post(Action work)
    {
        if (work == null)
        {
            throw new ArgumentNullException(nameof(work));
        }

        _control.BeginInvoke(work);
    }
}

/// <summary>
/// One call marshalled to the application thread: a bounded wait, and a delegate that cannot
/// publish anything once the wait has given up.
///
/// The second half is the point. <c>BeginInvoke</c> has no cancellation: when a modal dialog
/// holds the application thread for twenty minutes, the queued delegate still runs when the
/// dialog closes, and by then the request it belonged to has been answered and the pipe has
/// moved on. <see cref="Abandon"/> makes that late delegate harmless instead of racing a
/// later request's response onto the wire.
///
/// Deliberately built on <see cref="Monitor"/> rather than an event handle: nothing here is
/// disposable, so a late delegate cannot meet a disposed wait handle.
/// </summary>
public sealed class AppThreadCall<T>
{
    private readonly object _gate = new object();
    private bool _completed;
    private bool _abandoned;
    private T? _result;
    private Exception? _failure;

    private AppThreadCall()
    {
    }

    /// <summary>True once the delegate published a result the waiter may read.</summary>
    public bool Completed
    {
        get
        {
            lock (_gate)
            {
                return _completed;
            }
        }
    }

    /// <summary>True once the waiter gave up; a later publish is discarded.</summary>
    public bool Abandoned
    {
        get
        {
            lock (_gate)
            {
                return _abandoned;
            }
        }
    }

    /// <summary>What the work returned. Only meaningful once <see cref="Wait"/> returned true.</summary>
    public T? Result
    {
        get
        {
            lock (_gate)
            {
                return _result;
            }
        }
    }

    /// <summary>What the work threw, if anything.</summary>
    public Exception? Failure
    {
        get
        {
            lock (_gate)
            {
                return _failure;
            }
        }
    }

    /// <summary>
    /// Queues <paramref name="work"/> onto the application thread. Whatever
    /// <see cref="IAppThreadInvoker.Post"/> throws is thrown here, before a call exists.
    /// </summary>
    public static AppThreadCall<T> Post(IAppThreadInvoker invoker, Func<T> work)
    {
        if (invoker == null)
        {
            throw new ArgumentNullException(nameof(invoker));
        }

        if (work == null)
        {
            throw new ArgumentNullException(nameof(work));
        }

        var call = new AppThreadCall<T>();
        invoker.Post(() => call.Publish(work));
        return call;
    }

    /// <summary>
    /// Waits up to <paramref name="timeout"/>. False means the call has not answered - it
    /// timed out, or it was abandoned by <see cref="Abandon"/>.
    /// </summary>
    public bool Wait(TimeSpan timeout)
    {
        var clock = Stopwatch.StartNew();
        lock (_gate)
        {
            while (!_completed && !_abandoned)
            {
                TimeSpan remaining = timeout - clock.Elapsed;
                if (remaining <= TimeSpan.Zero)
                {
                    return false;
                }

                Monitor.Wait(_gate, remaining);
            }

            return _completed;
        }
    }

    /// <summary>
    /// Gives up on the call: a waiter is released now, and the delegate - whenever it runs -
    /// publishes nothing.
    /// </summary>
    public void Abandon()
    {
        lock (_gate)
        {
            _abandoned = true;
            Monitor.PulseAll(_gate);
        }
    }

    private void Publish(Func<T> work)
    {
        T? value = default;
        Exception? failure = null;
        try
        {
            value = work();
        }
        catch (Exception error)
        {
            failure = error;
        }

        lock (_gate)
        {
            if (_abandoned)
            {
                // Too late. Nobody is listening and nobody may be told.
                return;
            }

            _result = value;
            _failure = failure;
            _completed = true;
            Monitor.PulseAll(_gate);
        }
    }
}

/// <summary>Everything <see cref="InProcPipeServer"/> is given.</summary>
public sealed class InProcPipeServerOptions
{
    public InProcPipeServerOptions(string pipeName, IBridgeDispatcher dispatcher, IAppThreadInvoker invoker)
    {
        if (string.IsNullOrWhiteSpace(pipeName))
        {
            throw new ArgumentException(
                "A pipe name is required; see PipeNames.NewToolServiceName().", nameof(pipeName));
        }

        PipeName = pipeName;
        Dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
        Invoker = invoker ?? throw new ArgumentNullException(nameof(invoker));
    }

    /// <summary>The <c>swreview-&lt;guid&gt;</c> name clients connect to.</summary>
    public string PipeName { get; }

    /// <summary>Runs on the application thread; everything SOLIDWORKS is behind it.</summary>
    public IBridgeDispatcher Dispatcher { get; }

    public IAppThreadInvoker Invoker { get; }

    /// <summary>
    /// How long one marshalled call may take before the request is answered without it.
    /// The default is deliberately longer than the Python client's own 60s
    /// (reviewer/src/swreview/bridge/client.py, DEFAULT_TIMEOUT_S), so the two sides cannot
    /// disagree about whether a call is still running, and long enough that a real
    /// interference run is never cut off (research R6).
    /// </summary>
    public TimeSpan InvokeTimeout { get; set; } = InProcPipeServer.DefaultInvokeTimeout;

    /// <summary>
    /// Where the server's own lines go. Never given a secret: the lines below carry a request
    /// id and a command name and nothing else off the wire.
    /// </summary>
    public Action<string>? Log { get; set; }
}

/// <summary>
/// T047. The bridge, hosted inside SOLIDWORKS.
///
/// Feature 001's <c>PipeServer</c> owns an STA worker thread it created itself. This one
/// cannot: the <c>ISldWorks</c> pointer belongs to the thread SOLIDWORKS is already running
/// on, and a second apartment would fail on the first COM call. So the shape is inverted -
/// the pipe threads are ours and the execution thread is SOLIDWORKS' - and every consequence
/// of that inversion is handled here rather than by the callers:
///
///   * <b>Access control.</b> The pipe is created with an explicit <see cref="PipeSecurity"/>
///     granting the current user's SID and nobody else. .NET Framework 4.8 has no
///     <c>PipeOptions.CurrentUserOnly</c>, and a named pipe with the default security
///     descriptor is readable by any local process, so the GUID in the name is not an access
///     control (contracts/README.md).
///   * <b>One at a time, in arrival order.</b> Two clients exist by design - the review
///     backend and the CLI's MCP server, holding two different secrets - and SOLIDWORKS is
///     single threaded regardless. Every request goes through one queue and one pump thread,
///     so a capture cannot change the selection underneath a measure.
///   * <b>A bounded wait.</b> The application thread also runs modal dialogs. A request that
///     is not answered within <see cref="InProcPipeServerOptions.InvokeTimeout"/> is answered
///     without it, and the delegate that eventually wakes up is abandoned rather than allowed
///     to write a stale response (see <see cref="AppThreadCall{T}"/>).
///   * <b>A reader thread that survives.</b> <c>BeginInvoke</c> throws when the handle is not
///     created or was destroyed during unload; that becomes a response, not an exception on
///     the thread that owns a client connection.
///
/// What is NOT here: commands, secrets, and SOLIDWORKS itself. Those are the dispatcher's,
/// which is why this class is testable with a fake application thread and no SOLIDWORKS.
/// </summary>
public sealed class InProcPipeServer : IDisposable
{
    /// <summary>
    /// Concurrent connections. Two are used today (the review backend and the MCP server);
    /// the headroom costs nothing and a refused connection is an opaque failure at the client.
    /// </summary>
    public const int MaxServerInstances = 4;

    /// <summary>See <see cref="InProcPipeServerOptions.InvokeTimeout"/>.</summary>
    public static readonly TimeSpan DefaultInvokeTimeout = TimeSpan.FromSeconds(120);

    /// <summary>
    /// The Task Pane cannot be reached at all: no window handle yet, or it was destroyed
    /// while the add-in unloaded. A sentence rather than a stack trace, because the engineer
    /// sees it in the reviewer's coverage report.
    /// </summary>
    public const string UnavailableError =
        "the SOLIDWORKS task pane is not available, so the tool service cannot reach the "
        + "application thread";

    /// <summary>Dispose is in progress; the request was never run.</summary>
    public const string ShuttingDownError = "the tool service is shutting down";

    /// <summary>How often a caller in <see cref="Answer"/> re-checks that the pump is alive.</summary>
    private static readonly TimeSpan PumpWatchdogInterval = TimeSpan.FromMilliseconds(250);

    private readonly string _pipeName;
    private readonly IBridgeDispatcher _dispatcher;
    private readonly IAppThreadInvoker _invoker;
    private readonly TimeSpan _timeout;
    private readonly Action<string>? _log;

    private readonly BlockingCollection<WorkItem> _queue = new BlockingCollection<WorkItem>();
    private readonly CancellationTokenSource _stopping = new CancellationTokenSource();
    private readonly object _gate = new object();
    private readonly List<NamedPipeServerStream> _connections = new List<NamedPipeServerStream>();
    private readonly List<Thread> _clients = new List<Thread>();
    private readonly Thread _pump;

    private NamedPipeServerStream? _listening;
    private Thread? _accept;
    private AppThreadCall<BridgeResponse>? _inFlight;
    private bool _disposed;

    public InProcPipeServer(InProcPipeServerOptions options)
    {
        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        _pipeName = options.PipeName;
        _dispatcher = options.Dispatcher;
        _invoker = options.Invoker;
        _timeout = options.InvokeTimeout;
        _log = options.Log;

        if (_timeout <= TimeSpan.Zero)
        {
            throw new ArgumentException(
                "The invoke timeout must be positive.", nameof(options));
        }

        // Started here rather than in Start(): the queue is what makes requests serial, and
        // Answer() is usable - by the tests, and by any in-process caller - with no pipe.
        _pump = new Thread(Pump)
        {
            IsBackground = true,
            Name = "swreview-toolservice-pump",
        };
        _pump.Start();
    }

    /// <summary>The name clients connect to, e.g. <c>\\.\pipe\swreview-1f2e...</c>.</summary>
    public string PipeName => _pipeName;

    /// <summary>
    /// Requests waiting for the application thread, not counting the one already handed to
    /// it. Diagnostic: it is what proves "one at a time, in arrival order" is a fact.
    /// </summary>
    public int QueuedRequests
    {
        get
        {
            try
            {
                return _queue.IsAddingCompleted ? 0 : _queue.Count;
            }
            catch (ObjectDisposedException)
            {
                return 0;
            }
        }
    }

    /// <summary>
    /// A <see cref="PipeSecurity"/> allowing the current user and no one else.
    ///
    /// <see cref="PipeAccessRights.CreateNewInstance"/> is in the grant as well as
    /// <see cref="PipeAccessRights.ReadWrite"/>, and it has to be: every instance after the
    /// first is created against the existing pipe's DACL, so a grant of ReadWrite alone
    /// would let exactly one client ever connect and then fail with access denied.
    /// </summary>
    public static PipeSecurity CurrentUserOnly()
    {
        SecurityIdentifier user;
        using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
        {
            user = identity.User
                ?? throw new InvalidOperationException(
                    "The current Windows identity has no user SID, so the tool service pipe "
                    + "cannot be restricted to this user.");
        }

        // A fresh PipeSecurity has an empty DACL: whatever is not granted below is denied,
        // including Everyone and Authenticated Users.
        var security = new PipeSecurity();
        security.AddAccessRule(new PipeAccessRule(
            user,
            PipeAccessRights.ReadWrite | PipeAccessRights.CreateNewInstance,
            AccessControlType.Allow));

        return security;
    }

    /// <summary>The documented answer when the application thread never came back.</summary>
    public static string TimedOutError(TimeSpan timeout) =>
        $"the SOLIDWORKS thread did not answer within {timeout.TotalSeconds:0.#}s "
        + "- a dialog may be open";

    /// <summary>
    /// Creates the pipe and starts accepting. Separate from the constructor so a name that is
    /// already taken fails at the add-in's call site, where it can be reported, rather than
    /// silently on a background thread.
    /// </summary>
    public void Start()
    {
        Thread accept;
        lock (_gate)
        {
            ThrowIfDisposed();
            if (_accept != null)
            {
                return;
            }

            // Created here, synchronously: the name is proved free, and the DACL exists to be
            // read before any client has connected.
            _listening = CreateInstance();

            accept = new Thread(AcceptLoop)
            {
                IsBackground = true,
                Name = "swreview-toolservice-accept",
            };
            _accept = accept;
        }

        accept.Start();
        Log($@"listening on \\.\pipe\{_pipeName}");
    }

    /// <summary>
    /// The DACL of the instance currently waiting for a client. Read back off the live pipe
    /// rather than returned from <see cref="CurrentUserOnly"/>, so what is asserted is what
    /// Windows actually applied.
    /// </summary>
    public PipeSecurity ReadPipeSecurity()
    {
        lock (_gate)
        {
            if (_listening == null)
            {
                throw new InvalidOperationException(
                    "There is no listening pipe instance; call Start() first.");
            }

            return _listening.GetAccessControl();
        }
    }

    /// <summary>
    /// Parses one request line, runs it on the application thread, and returns the response
    /// to write back. Public because it is the whole request path: the pipe below only moves
    /// bytes, and everything worth asserting is assertable without one.
    /// </summary>
    public BridgeResponse Answer(string line)
    {
        BridgeRequest request;
        try
        {
            request = BridgeCodec.ReadRequest(line);
        }
        catch (BridgeProtocolError error)
        {
            // No id was parsed, so the response carries an empty one and the client matches
            // on the error (feature 001 PROTOCOL.md).
            return BridgeResponse.Failed(string.Empty, error.Message);
        }

        var work = new WorkItem(request);
        try
        {
            _queue.Add(work);
        }
        catch (InvalidOperationException)
        {
            // CompleteAdding (shutting down), or the collection is already disposed -
            // ObjectDisposedException derives from InvalidOperationException.
            return BridgeResponse.Failed(request.Id, ShuttingDownError);
        }

        // Never an unbounded wait on another thread. A fixed ceiling would be wrong - requests
        // are served one at a time, so a queued one legitimately waits for every request ahead
        // of it - so what is watched is the pump itself: if it has stopped, this caller is
        // answered rather than parked forever.
        while (!work.Completion.Task.Wait(PumpWatchdogInterval))
        {
            if (!_pump.IsAlive)
            {
                work.Completion.TrySetResult(
                    BridgeResponse.Failed(request.Id, ShuttingDownError));
                break;
            }
        }

        return work.Completion.Task.GetAwaiter().GetResult();
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
        }

        _stopping.Cancel();

        Thread? accept;
        Thread[] clients;
        lock (_gate)
        {
            // Releases the pump immediately instead of leaving it on a two-minute wait for a
            // thread that is being torn down.
            _inFlight?.Abandon();

            _listening?.Dispose();
            _listening = null;

            foreach (NamedPipeServerStream connection in _connections)
            {
                // Unblocks a reader thread parked in ReadLine.
                try
                {
                    connection.Dispose();
                }
                catch (Exception)
                {
                }
            }

            _connections.Clear();
            accept = _accept;
            clients = _clients.ToArray();
            _clients.Clear();
        }

        // Whatever is already queued is answered rather than dropped: a caller blocked on a
        // response must never wait for a server that has stopped.
        _queue.CompleteAdding();

        accept?.Join(TimeSpan.FromSeconds(2));
        foreach (Thread client in clients)
        {
            client.Join(TimeSpan.FromSeconds(2));
        }

        _pump.Join(TimeSpan.FromSeconds(5));

        // The queue is deliberately NOT disposed. The join above is bounded, so the pump can
        // still be inside a request; a disposed BlockingCollection would then throw
        // ObjectDisposedException out of GetConsumingEnumerable on a background thread and
        // take SOLIDWORKS down with it. CompleteAdding is what stops it, and it has run.
        _stopping.Dispose();
        Log("stopped");
    }

    // ---- the accept loop -----------------------------------------------------------------

    private void AcceptLoop()
    {
        while (!_stopping.IsCancellationRequested)
        {
            NamedPipeServerStream pipe;
            lock (_gate)
            {
                if (_stopping.IsCancellationRequested)
                {
                    return;
                }

                try
                {
                    pipe = _listening ?? CreateInstance();
                }
                catch (Exception error)
                {
                    Log("could not create a pipe instance: " + error.Message);
                    return;
                }

                _listening = pipe;
            }

            try
            {
                WaitForConnection(pipe, _stopping.Token);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (ObjectDisposedException)
            {
                // Dispose closed the instance we were waiting on.
                return;
            }
            catch (IOException error)
            {
                Log("a pipe instance broke before a client connected: " + error.Message);
                lock (_gate)
                {
                    if (ReferenceEquals(_listening, pipe))
                    {
                        _listening = null;
                    }
                }

                pipe.Dispose();
                continue;
            }

            Thread client;
            lock (_gate)
            {
                _listening = null;
                if (_stopping.IsCancellationRequested)
                {
                    pipe.Dispose();
                    return;
                }

                _connections.Add(pipe);
                client = new Thread(() => ServeClient(pipe))
                {
                    IsBackground = true,
                    Name = "swreview-toolservice-client",
                };
                _clients.Add(client);
            }

            client.Start();
        }
    }

    private NamedPipeServerStream CreateInstance() => new NamedPipeServerStream(
        _pipeName,
        PipeDirection.InOut,
        MaxServerInstances,
        PipeTransmissionMode.Byte,
        PipeOptions.Asynchronous,
        inBufferSize: 4096,
        outBufferSize: 4096,
        pipeSecurity: CurrentUserOnly());

    private static void WaitForConnection(NamedPipeServerStream pipe, CancellationToken cancellation)
    {
        IAsyncResult pending = pipe.BeginWaitForConnection(null, null);
        int signalled = WaitHandle.WaitAny(new[] { pending.AsyncWaitHandle, cancellation.WaitHandle });
        if (signalled == 1)
        {
            throw new OperationCanceledException(cancellation);
        }

        pipe.EndWaitForConnection(pending);
    }

    /// <summary>
    /// One connection: request lines in, response lines out, on this connection's own thread.
    /// One reader and one writer per connection means no lock is needed on the wire; the
    /// ordering that does matter is enforced by the single queue behind <see cref="Answer"/>.
    /// </summary>
    private void ServeClient(NamedPipeServerStream pipe)
    {
        // No BOM, and flushed per line: a client blocked on a response must not wait for a
        // buffer to fill.
        var encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        var input = new StreamReader(pipe, encoding, detectEncodingFromByteOrderMarks: false, bufferSize: 4096);
        var output = new StreamWriter(pipe, encoding) { AutoFlush = true, NewLine = "\n" };

        try
        {
            while (!_stopping.IsCancellationRequested)
            {
                string? line;
                try
                {
                    line = input.ReadLine();
                }
                catch (Exception)
                {
                    // The client went away mid-line, or Dispose closed the pipe under us.
                    return;
                }

                if (line == null)
                {
                    return;
                }

                if (line.Trim().Length == 0)
                {
                    continue;
                }

                BridgeResponse response = Answer(line);

                try
                {
                    output.WriteLine(BridgeCodec.WriteResponse(response));
                }
                catch (Exception)
                {
                    return;
                }
            }
        }
        finally
        {
            lock (_gate)
            {
                _connections.Remove(pipe);
            }

            try
            {
                pipe.Dispose();
            }
            catch (Exception)
            {
            }
        }
    }

    // ---- the one thing at a time --------------------------------------------------------

    private void Pump()
    {
        try
        {
            foreach (WorkItem item in _queue.GetConsumingEnumerable())
            {
                item.Completion.TrySetResult(Execute(item.Request));
            }
        }
        catch (Exception error)
        {
            // Nothing here may reach the thread's top: an unhandled exception on a background
            // thread ends the process, and the process is SOLIDWORKS. Whatever is left in the
            // queue is answered, so no caller is parked on a pump that has stopped.
            Log("the tool service pump stopped: " + error.Message);
            Drain();
        }
    }

    /// <summary>Answers whatever is still queued, so no caller waits on a stopped pump.</summary>
    private void Drain()
    {
        try
        {
            while (_queue.TryTake(out WorkItem item))
            {
                item.Completion.TrySetResult(
                    BridgeResponse.Failed(item.Request.Id, ShuttingDownError));
            }
        }
        catch (Exception)
        {
            // The queue itself is gone; the watchdog in Answer releases the rest.
        }
    }

    private BridgeResponse Execute(BridgeRequest request)
    {
        if (_stopping.IsCancellationRequested)
        {
            return BridgeResponse.Failed(request.Id, ShuttingDownError);
        }

        if (!_invoker.CanInvoke)
        {
            Log($"request {request.Id} ({request.Command}): {UnavailableError}");
            return BridgeResponse.Failed(request.Id, UnavailableError);
        }

        AppThreadCall<BridgeResponse> call;
        try
        {
            call = AppThreadCall<BridgeResponse>.Post(_invoker, () => Dispatch(request));
        }
        catch (Exception error)
        {
            // The handle went away between the check above and the call. A response, not an
            // exception climbing back onto a connection's reader thread.
            Log($"request {request.Id} ({request.Command}): {UnavailableError} "
                + $"({error.GetType().Name})");
            return BridgeResponse.Failed(
                request.Id, UnavailableError + " (" + error.GetType().Name + ")");
        }

        bool stopping;
        lock (_gate)
        {
            _inFlight = call;

            // Under the same lock Dispose abandons the in-flight call from, and after the
            // assignment: the call did not exist when Dispose looked, so either it sees this
            // one, or this line sees the cancellation Dispose raised before it looked. A
            // request that slipped through the check at the top must not hold a caller for
            // the whole invoke timeout on an application thread that is being torn down.
            stopping = _stopping.IsCancellationRequested;
        }

        if (stopping)
        {
            call.Abandon();
        }

        try
        {
            if (call.Wait(_timeout))
            {
                return call.Result!;
            }

            // Nothing this call does later may reach a client.
            call.Abandon();

            if (_stopping.IsCancellationRequested)
            {
                Log($"request {request.Id} ({request.Command}): {ShuttingDownError}");
                return BridgeResponse.Failed(request.Id, ShuttingDownError);
            }

            string timedOut = TimedOutError(_timeout);
            Log($"request {request.Id} ({request.Command}): {timedOut}");
            return BridgeResponse.Failed(request.Id, timedOut);
        }
        finally
        {
            lock (_gate)
            {
                if (ReferenceEquals(_inFlight, call))
                {
                    _inFlight = null;
                }
            }
        }
    }

    /// <summary>
    /// Runs ON the application thread. The dispatcher is supposed to turn everything into a
    /// response; if it ever does not, the caller still gets one instead of a request that
    /// never completes.
    /// </summary>
    private BridgeResponse Dispatch(BridgeRequest request)
    {
        try
        {
            return _dispatcher.Dispatch(request)
                ?? BridgeResponse.Failed(request.Id, "the tool service produced no response");
        }
        catch (Exception error)
        {
            return BridgeResponse.Failed(request.Id, error.GetType().Name + ": " + error.Message);
        }
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(InProcPipeServer));
        }
    }

    private void Log(string message)
    {
        Action<string>? log = _log;
        if (log == null)
        {
            return;
        }

        try
        {
            log(message);
        }
        catch (Exception)
        {
            // A log that throws must not take a review with it.
        }
    }

    private sealed class WorkItem
    {
        public WorkItem(BridgeRequest request)
        {
            Request = request;
        }

        public BridgeRequest Request { get; }

        public TaskCompletionSource<BridgeResponse> Completion { get; } =
            new TaskCompletionSource<BridgeResponse>();
    }
}
