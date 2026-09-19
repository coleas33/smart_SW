using System;
using System.IO;
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

    /// <summary>
    /// One line into this service's own tool-service log, beside the <c>attached to ...</c>
    /// line the launch wrote.
    ///
    /// On the service rather than on the gate because the log belongs to the service: the gate
    /// outlives any one of them, and the only thing it has to say - "I am not re-attaching to
    /// the document you just opened, because a turn is running" - is a fact about <i>this</i>
    /// attachment, and belongs in the file the engineer reads to find out what it is attached
    /// to. Must not throw; a log that cannot be written is not a reason to fail anything.
    /// </summary>
    void WriteLog(string line);
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
/// <b>And not to a drawing.</b> "Something to attach to" is a part or an assembly
/// (<see cref="PageDocument.IsAttachable"/>). A drawing has no configuration, and a session is
/// bound to one, so the attach throws - and a throw here is swallowed into addin.log, which is
/// how a SOLIDWORKS loaded with a drawing active used to leave every bridge-backed feature off
/// for the session. Both entry points refuse one, and both say so through
/// <c>report</c>: a refusal nobody can see is the same as the failure it replaced.
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
/// <b>And it follows the active document.</b> "Once" above is about one service at a time, not
/// about one document per SOLIDWORKS session: the scope is bound to the document it attached
/// to, so an engineer who opens another one gets `document no longer open` from every command
/// until the add-in is reloaded (docs/pane-findings-2026-09-16.md, finding 1).
/// <see cref="FollowDocument"/> is the second entry point that fixes that, and it is separate
/// from <see cref="EnsureStarted"/> because the two answer different questions: "is there one?"
/// and "is it the right one?".
///
/// Thread-safe, because it is not called from one thread: the pane's calls come from the
/// application thread and the start itself completes on a worker.
/// </summary>
public sealed class ToolServiceGate : IToolServiceAccess, IDisposable
{
    private readonly Func<PageDocument?> _activeDocument;
    private readonly Func<IToolService> _start;
    private readonly Action<IToolService?> _publish;
    private readonly Action<string, Exception?> _report;
    private readonly Action<Action> _schedule;
    private readonly Func<bool> _busy;
    private readonly object _lock = new object();

    private IToolService? _service;
    private bool _starting;
    private bool _disposed;

    /// <param name="activeDocument">SOLIDWORKS' active document, or null when nothing is open.
    /// The document rather than a yes/no, because a drawing is open and is still not something a
    /// scope can be attached to. Asked on the scheduled thread, so it may marshal onto the
    /// application thread itself.</param>
    /// <param name="start">Starts the host. Blocks; see the class remarks.</param>
    /// <param name="publish">Publishes the review half of whichever service is listening - in
    /// the add-in, into <see cref="ReviewHostOptions.Bridge"/>, which is what
    /// <c>POST /sessions</c> carries - and is called with null when one stops, so that what is
    /// published is never a pipe that has been closed.</param>
    /// <param name="report">A failed start, or a document not attached to, for the pane and the
    /// add-in log. The exception is null when nothing threw: a refusal is not a failure, but it
    /// is just as invisible if it is not said.</param>
    /// <param name="schedule">Where the start runs. Defaults to the thread pool.</param>
    /// <param name="busy">Whether work is holding the bridge - in the add-in, a review turn or
    /// a remodel run. Asked by <see cref="FollowDocument"/> only, on the scheduled thread and
    /// off the lock, because the add-in's answer costs an HTTP round trip per open chat.
    /// Defaults to "never busy", which is right for a gate with no work to hold it.</param>
    public ToolServiceGate(
        Func<PageDocument?> activeDocument,
        Func<IToolService> start,
        Action<IToolService?> publish,
        Action<string, Exception?> report,
        Action<Action>? schedule = null,
        Func<bool>? busy = null)
    {
        _activeDocument = activeDocument ?? throw new ArgumentNullException(nameof(activeDocument));
        _start = start ?? throw new ArgumentNullException(nameof(start));
        _publish = publish ?? throw new ArgumentNullException(nameof(publish));
        _report = report ?? throw new ArgumentNullException(nameof(report));
        _schedule = schedule ?? (work => ThreadPool.QueueUserWorkItem(_ => work()));
        _busy = busy ?? (() => false);
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
            ClearStarting();
            _report("The SwReview tool service could not be scheduled.", failure);
        }
    }

    /// <summary>
    /// Re-attaches the tool service to <paramref name="activePath"/> when it is attached to
    /// something else. Returns immediately: everything but the decision to schedule runs on the
    /// scheduled thread, exactly as the first start did, so the callback that publishes the
    /// review bridge re-points it too. Never throws - the add-in calls this from
    /// <c>ActiveDocChangeNotify</c>.
    ///
    /// <b>Nothing expensive on the caller's thread.</b> The caller is the SOLIDWORKS
    /// application thread (the class remarks above), and the two expensive things here are
    /// paid per document switch: the add-in's busy question is an HTTP round trip per open
    /// chat, each with the backend client's 30-second timeout, and the teardown joins the
    /// pipe's accept thread, every client thread and its pump. Asking either inline would
    /// freeze SOLIDWORKS for the better part of a minute when the backend is wedged - which is
    /// exactly when the engineer is most likely to be switching documents. So the checks below
    /// are the cheap ones (a string compare and a canonicalization), and everything after them
    /// is <see cref="FollowCore"/>, on the scheduled thread.
    ///
    /// Four cases it deliberately does nothing in:
    ///
    /// <b>Nothing open.</b> A null or blank active path means SOLIDWORKS has no document, not
    /// that the attachment is wrong. Dropping the service there would cost a restart for every
    /// close, and a command against the closed document still answers with its name.
    ///
    /// <b>A drawing.</b> The same answer for the same reason, and it matters more here than in
    /// <see cref="EnsureStarted"/>: the re-attach takes the running service down <i>first</i>,
    /// so before this case existed, opening a drawing to look at it disposed a bridge that was
    /// working and the attach that would have replaced it threw.
    ///
    /// <b>The same document.</b> Compared canonically and case-insensitively: SOLIDWORKS is
    /// under no obligation to spell a path the way it spelt it at attach time, and a restart
    /// per document change would be a new pipe, a new scope and a new pair of secrets for
    /// nothing.
    ///
    /// <b>Work is holding the bridge.</b> A review turn or a remodel run is executing commands
    /// against this scope; disposing it underneath them fails work that was going fine. The
    /// engineer is told through the tool-service log rather than by a silent no-op, because
    /// this is the one case where the bridge really does keep answering about the other
    /// document. A busy question that throws counts as busy: a teardown cannot be undone.
    /// </summary>
    public void FollowDocument(string? activePath)
    {
        if (string.IsNullOrWhiteSpace(activePath))
        {
            return;
        }

        IToolService? attached = null;
        bool skipped = false;
        lock (_lock)
        {
            if (_disposed || _starting || _service == null)
            {
                // A start already in flight will attach to whatever is active when it runs, and
                // no service at all is EnsureStarted's business, not this method's.
                return;
            }

            if (SameDocument(_service.DocumentPath, activePath!))
            {
                return;
            }

            if (!Attachable(activePath!))
            {
                // A drawing, so this is the "nothing open" case above rather than a document
                // worth re-attaching to: the running service keeps its scope, its pipe and its
                // secrets, and the engineer who opens a drawing to read it still has a bridge
                // when they come back. Reported below rather than here, because the report
                // reaches the pane and nothing that touches the pane may hold this lock.
                skipped = true;
            }
            else
            {
                attached = _service;

                // Claimed here, on the caller's thread, rather than in FollowCore: it is what
                // keeps an EnsureStarted or a second document change arriving in the gap from
                // scheduling a start of its own. The service stays published until FollowCore
                // takes it down, so the pane keeps answering about the document it is really
                // attached to.
                _starting = true;
            }
        }

        if (skipped)
        {
            _report(SkippedMessage(activePath!), null);
            return;
        }

        try
        {
            _schedule(() => FollowCore(attached!, activePath!));
        }
        catch (Exception failure)
        {
            ClearStarting();
            _report("The SwReview tool service could not be scheduled.", failure);
        }
    }

    /// <summary>
    /// The rest of <see cref="FollowDocument"/>, on the scheduled thread: ask whether work is
    /// holding the bridge, and if not, take the old service down and start one against the
    /// document that is active now.
    /// </summary>
    private void FollowCore(IToolService attached, string activePath)
    {
        bool busy;
        try
        {
            busy = _busy();
        }
        catch (Exception failure)
        {
            ClearStarting();
            _report("The SwReview tool service could not be asked whether it is busy.", failure);
            return;
        }

        if (busy)
        {
            ClearStarting();
            Log(
                attached,
                "not re-attaching to " + activePath
                + ": a turn is running against " + attached.DocumentPath);
            return;
        }

        lock (_lock)
        {
            if (_disposed || !ReferenceEquals(_service, attached))
            {
                // Disposed, or Dispose took the service down, while this was queued or while
                // the busy question was out. Either way there is nothing left to re-attach.
                _starting = false;
                return;
            }

            // The gate answers null from here until the new service is listening, which is what
            // makes the Remodel tab refuse a run rather than start one against a pipe that is
            // closing. `_starting` is already ours.
            _service = null;
        }

        Stop(attached);

        // Inline: this is the scheduled thread, which is the one StartCore is owed.
        StartCore();
    }

    private void ClearStarting()
    {
        lock (_lock)
        {
            _starting = false;
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
            PageDocument? document = _activeDocument();
            if (document == null)
            {
                // Nothing open, which is an ordinary state and not worth a line: the pane asks
                // again on every ActiveDocChangeNotify.
                ClearStarting();
                return;
            }

            if (!document.IsAttachable)
            {
                // A drawing. Attaching to one throws, and this method turns a throw into a log
                // line nobody reads, so it is refused before the attempt and said out loud.
                ClearStarting();
                _report(SkippedMessage(document.Path), null);
                return;
            }

            service = _start();
        }
        catch (Exception failure)
        {
            ClearStarting();
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
            _publish(service);
        }
        catch (Exception failure)
        {
            // The host is listening either way; what failed is the handover to the backend.
            _report("The SwReview tool service could not be given to the review backend.", failure);
        }
    }

    /// <summary>
    /// Whether a path names a document a scope can be attached to: the rule
    /// <see cref="PageDocument.IsAttachable"/> states, asked of a bare path because
    /// <c>ActiveDocChangeNotify</c> is what hands <see cref="FollowDocument"/> one. Built rather
    /// than restated so there is one extension table in the add-in, not two.
    /// </summary>
    private static bool Attachable(string activePath) =>
        new PageDocument(activePath, null).IsAttachable;

    /// <summary>
    /// The one line a document that is not attached to gets: which document, why, and what to
    /// open instead. Shared by both entry points, because the engineer's question is the same
    /// whether the drawing was open at add-in load or opened later - "why are the tools off?".
    /// </summary>
    private static string SkippedMessage(string documentPath) =>
        "The SwReview tool service is not attaching to '" + documentPath
        + "': a drawing has no configuration to attach to. Open the part or assembly it "
        + "documents.";

    /// <summary>
    /// Whether two paths name the same document. Canonical because SOLIDWORKS hands back
    /// whatever it was opened with, case-insensitive because Windows is; an
    /// <see cref="Path.GetFullPath(string)"/> that throws - a path with a character the
    /// filesystem does not allow - leaves the raw strings to be compared rather than deciding
    /// the documents differ, because "differ" is the answer that restarts the service.
    /// </summary>
    private static bool SameDocument(string attached, string active) =>
        string.Equals(Canonical(attached), Canonical(active), StringComparison.OrdinalIgnoreCase);

    private static string Canonical(string path)
    {
        try
        {
            return Path.GetFullPath(path).TrimEnd('\\', '/');
        }
        catch (Exception)
        {
            return path.Trim().TrimEnd('\\', '/');
        }
    }

    private static void Log(IToolService service, string line)
    {
        try
        {
            service.WriteLog(line);
        }
        catch (Exception)
        {
            // A log that cannot be written must not fail a COM callback.
        }
    }

    private void Stop(IToolService? service)
    {
        if (service == null)
        {
            return;
        }

        // Un-published before it is closed, and from here rather than from each of the three
        // callers, so the invariant is one sentence: what is published is what is listening. A
        // `POST /sessions` that goes out carrying a pipe this method has already closed hands
        // the backend a bridge whose every command fails, where a null bridge makes the Python
        // side fall back to its own attach - which works.
        try
        {
            _publish(null);
        }
        catch (Exception failure)
        {
            _report("The SwReview tool service could not be withdrawn from the review backend.", failure);
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
