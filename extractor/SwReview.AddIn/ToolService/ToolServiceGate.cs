using System;
using System.Threading;
using SwReview.AddIn.Review;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.ToolService;

/// <summary>
/// One running tool service, behind a seam.
///
/// <see cref="ToolServiceHost"/> is the only implementation; the interface exists because
/// starting it needs a live <c>ISldWorks</c> and an attach on the SOLIDWORKS application
/// thread, and the decisions about *when* it starts and *who gets which secret* (T048) have to
/// be testable without either.
/// </summary>
public interface IToolService : IDisposable
{
    /// <summary>The <c>swreview-&lt;guid&gt;</c> name both clients connect to.</summary>
    string PipeName { get; }

    /// <summary>The document the scope is attached to.</summary>
    string DocumentPath { get; }

    /// <summary>Pipe plus the review secret; goes to the backend's <c>POST /sessions</c>.</summary>
    BridgeConfig ReviewBridge { get; }

    /// <summary>Pipe plus the general-chat secret; goes to the generated CLI profile.</summary>
    BridgeConfig GeneralChatBridge { get; }

    /// <summary>
    /// Pipe plus the remodel secret; goes to the backend's remodel routes (T070, T134e) and to
    /// nothing else. It authorizes <c>remodel.*</c>, which is every write the run makes to the
    /// copy, so it is deliberately absent from <see cref="IToolServiceAccess"/>: the terminal
    /// can read its own generated profile.
    /// </summary>
    BridgeConfig RemodelBridge { get; }

    /// <summary>The attached scope, so <c>entity.show</c> resolves against the same one.</summary>
    ISwSession Session { get; }
}

/// <summary>
/// What the Terminal tab needs from the tool service, and nothing else.
///
/// The terminal's profile writer (T057) has to put <c>{pipe, secret}</c> into the generated
/// CLI profile's MCP <c>env</c> block, and the run folder's persona text names the document.
/// It gets those two facts through this interface rather than a reference to the gate, so the
/// terminal can never reach the <b>review</b> secret: that one authorizes <c>interference</c>
/// as well, and the CLI can read its own generated profile (contracts/README.md).
///
/// Both members answer null until the tool service is listening, which is a state the pane
/// really has - the Task Pane exists before the first document is open.
/// </summary>
public interface IToolServiceAccess
{
    /// <summary>Where to connect and the general-chat secret, or null before the start.</summary>
    BridgeConfig? GeneralChatBridge { get; }

    /// <summary>The document the scope is attached to, or null before the start.</summary>
    string? DocumentPath { get; }
}

/// <summary>
/// T048. Owns the tool service's lifetime inside the add-in: start it once a document is open,
/// hand the review half to the backend and keep the general-chat half for the terminal, stop it
/// on disconnect.
///
/// Three things it exists to get right, none of which belong in a COM event handler:
///
/// <b>Not before the first document.</b> SOLIDWORKS normally loads with nothing open, and the
/// Task Pane is created either way. <see cref="ToolServiceHost.Start"/> walks the component
/// tree; with no document there is nothing to walk. So the pane asks on connect and again on
/// every <c>ActiveDocChangeNotify</c>, and this answers "not yet" until there is something to
/// attach to.
///
/// <b>Off the application thread.</b> <see cref="ToolServiceHost.Start"/> marshals its attach
/// onto the application thread and waits for it. Both callers - <c>ConnectToSW</c> and the
/// document-changed event - <i>are</i> that thread, so starting inline would deadlock
/// SOLIDWORKS until the attach timeout expired. The start is therefore scheduled; the delegate
/// is injectable so the tests are deterministic.
///
/// <b>Once.</b> `ToolService 1 per add-in instance` (data-model.md): a second host would be a
/// second pipe, a second scope and a second pair of secrets, and a review already running would
/// still be talking to the first. A start that *failed* is not a start, so the next document
/// tries again - an attach can fail on the document that happened to be open and succeed on the
/// next one, and the alternative is a pane whose tools are dead until SOLIDWORKS restarts.
///
/// Thread-safe, because it is not called from one thread: the pane's calls come from the
/// application thread and the start itself completes on a worker.
/// </summary>
public sealed class ToolServiceGate : IToolServiceAccess, IDisposable
{
    private readonly Func<bool> _documentAvailable;
    private readonly Func<IToolService> _start;
    private readonly Action<IToolService> _started;
    private readonly Action<string, Exception> _report;
    private readonly Action<Action> _schedule;
    private readonly object _lock = new object();

    private IToolService? _service;
    private bool _starting;
    private bool _disposed;

    /// <param name="documentAvailable">Whether SOLIDWORKS has a document worth attaching to.
    /// Asked on the scheduled thread, so it may marshal onto the application thread itself.</param>
    /// <param name="start">Starts the host. Blocks; see the class remarks.</param>
    /// <param name="started">Publishes the review half - in the add-in, into
    /// <see cref="ReviewHostOptions.Bridge"/>, which is what <c>POST /sessions</c> carries.</param>
    /// <param name="report">A failed start, for the pane and the add-in log.</param>
    /// <param name="schedule">Where the start runs. Defaults to the thread pool.</param>
    public ToolServiceGate(
        Func<bool> documentAvailable,
        Func<IToolService> start,
        Action<IToolService> started,
        Action<string, Exception> report,
        Action<Action>? schedule = null)
    {
        _documentAvailable = documentAvailable ?? throw new ArgumentNullException(nameof(documentAvailable));
        _start = start ?? throw new ArgumentNullException(nameof(start));
        _started = started ?? throw new ArgumentNullException(nameof(started));
        _report = report ?? throw new ArgumentNullException(nameof(report));
        _schedule = schedule ?? (work => ThreadPool.QueueUserWorkItem(_ => work()));
    }

    /// <summary>The running service, or null. Null is an ordinary state, not a failure.</summary>
    public IToolService? Service
    {
        get
        {
            lock (_lock)
            {
                return _service;
            }
        }
    }

    public BridgeConfig? GeneralChatBridge => Service?.GeneralChatBridge;

    /// <summary>
    /// The remodel half, for the Remodel tab's pipeline (T134e). Read fresh per call like the
    /// others - the tool service restarts with the document - and null before it is listening,
    /// which is what makes the pane refuse a run rather than start one it cannot execute.
    ///
    /// On the gate and on <see cref="IToolService"/>, never on <see cref="IToolServiceAccess"/>:
    /// that interface is the terminal's view, and this secret authorizes every write the
    /// re-modeler makes to the copy.
    /// </summary>
    public BridgeConfig? RemodelBridge => Service?.RemodelBridge;

    public string? DocumentPath => Service?.DocumentPath;

    /// <summary>
    /// The attached scope, for <c>entity.show</c>. Null before the tool service is listening,
    /// where the resolver falls back to its own attach.
    /// </summary>
    public ISwSession? Session => Service?.Session;

    /// <summary>
    /// Starts the tool service if a document is open and one is not running already. Returns
    /// immediately: the work is scheduled. Never throws - the add-in calls this from a
    /// SOLIDWORKS callback, where an exception is the session's problem rather than ours.
    /// </summary>
    public void EnsureStarted()
    {
        lock (_lock)
        {
            if (_disposed || _service != null || _starting)
            {
                return;
            }

            _starting = true;
        }

        try
        {
            _schedule(StartCore);
        }
        catch (Exception failure)
        {
            lock (_lock)
            {
                _starting = false;
            }

            _report("The SwReview tool service could not be scheduled.", failure);
        }
    }

    /// <summary>Stops the tool service. Safe to call twice, and from any thread.</summary>
    public void Dispose()
    {
        IToolService? service;
        lock (_lock)
        {
            _disposed = true;
            service = _service;
            _service = null;
        }

        Stop(service);
    }

    private void StartCore()
    {
        IToolService service;
        try
        {
            if (!_documentAvailable())
            {
                lock (_lock)
                {
                    _starting = false;
                }

                return;
            }

            service = _start();
        }
        catch (Exception failure)
        {
            lock (_lock)
            {
                _starting = false;
            }

            _report("The SwReview tool service did not start.", failure);
            return;
        }

        bool abandoned;
        lock (_lock)
        {
            _starting = false;
            abandoned = _disposed;
            if (!abandoned)
            {
                _service = service;
            }
        }

        if (abandoned)
        {
            // The add-in unloaded while the attach was still on the application thread. A pipe
            // listening into a SOLIDWORKS with no add-in is worse than no tool service at all.
            Stop(service);
            return;
        }

        try
        {
            _started(service);
        }
        catch (Exception failure)
        {
            // The host is listening either way; what failed is the handover to the backend.
            _report("The SwReview tool service could not be given to the review backend.", failure);
        }
    }

    private void Stop(IToolService? service)
    {
        if (service == null)
        {
            return;
        }

        try
        {
            service.Dispose();
        }
        catch (Exception failure)
        {
            _report("The SwReview tool service did not stop cleanly.", failure);
        }
    }
}
