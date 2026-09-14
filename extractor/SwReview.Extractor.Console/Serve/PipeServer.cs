using System;
using System.Collections.Concurrent;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using SwReview.Extractor.Bridge;

namespace SwReview.Extractor.Console.Serve;

/// <summary>
/// T072. The live bridge (research R3): one JSON request per line over a named pipe, and a
/// single dedicated STA thread that owns the <c>SldWorks</c> pointer.
///
/// The thread split is not a performance choice, it is a correctness one. COM interface
/// pointers are bound to the thread that created them, and a call from another thread fails
/// with "interface that was marshalled for a different thread". So:
///
///   * the pipe thread reads a line, parses it, and puts the request on a queue;
///   * the STA worker - created once, before any SOLIDWORKS call - drains the queue, builds
///     its dispatcher on its own thread, and completes each request's
///     <see cref="TaskCompletionSource{TResult}"/>;
///   * the pipe thread writes the response line.
///
/// Requests are answered in arrival order, one at a time. That is deliberate: SOLIDWORKS is
/// single threaded anyway, and serialising here means a capture cannot change the selection
/// underneath a measure.
///
/// The dispatcher is built by a factory rather than handed in, because it must be
/// constructed ON the worker thread. The tests pass a factory that returns a fake, which is
/// how the pipe loop itself is exercised without SOLIDWORKS.
/// </summary>
public sealed class PipeServer : IDisposable
{
    /// <summary>
    /// Only this many clients at a time. The reviewer opens one connection per run and the
    /// worker is single threaded, so a second client would only queue behind the first.
    /// </summary>
    public const int MaxConnections = 1;

    private readonly string _pipeName;
    private readonly Func<IBridgeDispatcher> _dispatcherFactory;
    private readonly TextWriter? _log;
    private readonly BlockingCollection<WorkItem> _queue = new BlockingCollection<WorkItem>();

    private Thread? _worker;
    private Exception? _workerStartupError;
    private readonly ManualResetEventSlim _workerReady = new ManualResetEventSlim(false);

    public PipeServer(string pipeName, Func<IBridgeDispatcher> dispatcherFactory, TextWriter? log = null)
    {
        if (string.IsNullOrWhiteSpace(pipeName))
        {
            throw new ArgumentException("A pipe name is required, e.g. --pipe swreview.", nameof(pipeName));
        }

        _pipeName = pipeName;
        _dispatcherFactory = dispatcherFactory ?? throw new ArgumentNullException(nameof(dispatcherFactory));
        _log = log;
    }

    /// <summary>The pipe clients connect to, e.g. <c>\\.\pipe\swreview</c>.</summary>
    public string PipeName => _pipeName;

    /// <summary>
    /// Starts the STA worker and waits until it has attached to SOLIDWORKS (or failed to).
    /// Called by <see cref="Run"/>; separate so a caller can report the attach failure
    /// before a client ever connects.
    /// </summary>
    public void Start()
    {
        if (_worker != null)
        {
            return;
        }

        _worker = new Thread(WorkerLoop)
        {
            Name = "swreview-bridge-sta",
            IsBackground = true,
        };

        // The whole point of this class. Everything SOLIDWORKS touches happens on this one
        // thread (constitution, Technical Constraints).
        _worker.SetApartmentState(ApartmentState.STA);
        _worker.Start();

        _workerReady.Wait();
        if (_workerStartupError != null)
        {
            throw new InvalidOperationException(
                "The bridge worker could not attach to SOLIDWORKS: " + _workerStartupError.Message,
                _workerStartupError);
        }
    }

    /// <summary>
    /// Serves clients until <paramref name="cancellation"/> is signalled. One client at a
    /// time; when a client disconnects the server waits for the next one, so the reviewer
    /// can be restarted without restarting SOLIDWORKS.
    /// </summary>
    public void Run(CancellationToken cancellation)
    {
        Start();

        while (!cancellation.IsCancellationRequested)
        {
            using (var pipe = new NamedPipeServerStream(
                _pipeName,
                PipeDirection.InOut,
                MaxConnections,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous))
            {
                try
                {
                    WaitForConnection(pipe, cancellation);
                }
                catch (OperationCanceledException)
                {
                    return;
                }

                if (cancellation.IsCancellationRequested)
                {
                    return;
                }

                Log("client connected");
                ServeClient(pipe, cancellation);
                Log("client disconnected");
            }
        }
    }

    /// <summary>
    /// Reads request lines from <paramref name="stream"/> and writes response lines back.
    /// Public so the tests can drive the loop over an in-memory stream pair, with no pipe.
    /// </summary>
    public void Serve(Stream reader, Stream writer, CancellationToken cancellation)
    {
        Start();
        ServeStreams(reader, writer, cancellation);
    }

    public void Dispose()
    {
        _queue.CompleteAdding();

        Thread? worker = _worker;
        if (worker != null && worker.IsAlive)
        {
            // The worker drains what is queued and exits; it is a background thread, so a
            // hung SOLIDWORKS call cannot keep the process alive.
            worker.Join(TimeSpan.FromSeconds(5));
        }

        _worker = null;
        _workerReady.Dispose();
        _queue.Dispose();
    }

    private void ServeClient(NamedPipeServerStream pipe, CancellationToken cancellation)
    {
        ServeStreams(pipe, pipe, cancellation);
    }

    private void ServeStreams(Stream reader, Stream writer, CancellationToken cancellation)
    {
        // No BOM, and the writer is flushed per line: a client blocking on a response must
        // not wait for a buffer to fill.
        var encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        var input = new StreamReader(reader, encoding, detectEncodingFromByteOrderMarks: false, bufferSize: 4096);
        var output = new StreamWriter(writer, encoding) { AutoFlush = true, NewLine = "\n" };

        while (!cancellation.IsCancellationRequested)
        {
            string? line;
            try
            {
                line = input.ReadLine();
            }
            catch (IOException)
            {
                // The client went away mid-line. Not an error worth a response.
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
            catch (IOException)
            {
                return;
            }
        }
    }

    /// <summary>Parses one line, has the worker run it, and returns the response to write.</summary>
    private BridgeResponse Answer(string line)
    {
        BridgeRequest request;
        try
        {
            request = BridgeCodec.ReadRequest(line);
        }
        catch (BridgeProtocolError error)
        {
            // The id is unknown, so the response carries an empty one; the client matches on
            // the error rather than on the id.
            return BridgeResponse.Failed(string.Empty, error.Message);
        }

        var work = new WorkItem(request);
        try
        {
            _queue.Add(work);
        }
        catch (InvalidOperationException)
        {
            return BridgeResponse.Failed(request.Id, "The bridge is shutting down.");
        }

        return work.Completion.Task.GetAwaiter().GetResult();
    }

    private void WorkerLoop()
    {
        IBridgeDispatcher? dispatcher = null;
        try
        {
            dispatcher = _dispatcherFactory();
        }
        catch (Exception error)
        {
            _workerStartupError = error;
        }
        finally
        {
            _workerReady.Set();
        }

        if (dispatcher == null)
        {
            // Nothing can be answered. Drain so no caller blocks forever.
            foreach (WorkItem pending in _queue.GetConsumingEnumerable())
            {
                pending.Completion.TrySetResult(BridgeResponse.Failed(
                    pending.Request.Id,
                    "The bridge worker never attached to SOLIDWORKS: "
                    + (_workerStartupError?.Message ?? "unknown reason")));
            }

            return;
        }

        foreach (WorkItem item in _queue.GetConsumingEnumerable())
        {
            BridgeResponse response;
            try
            {
                response = dispatcher.Dispatch(item.Request);
            }
            catch (Exception error)
            {
                // Dispatch is supposed to turn everything into a response; if it did not,
                // the worker still answers rather than dying and hanging every later call.
                response = BridgeResponse.Failed(
                    item.Request.Id, error.GetType().Name + ": " + error.Message);
            }

            item.Completion.TrySetResult(response);
        }
    }

    private static void WaitForConnection(NamedPipeServerStream pipe, CancellationToken cancellation)
    {
        IAsyncResult pending = pipe.BeginWaitForConnection(null, null);
        int signalled = WaitHandle.WaitAny(
            new[] { pending.AsyncWaitHandle, cancellation.WaitHandle });

        if (signalled == 1)
        {
            throw new OperationCanceledException(cancellation);
        }

        pipe.EndWaitForConnection(pending);
    }

    private void Log(string message)
    {
        if (_log != null)
        {
            _log.WriteLine(message);
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
