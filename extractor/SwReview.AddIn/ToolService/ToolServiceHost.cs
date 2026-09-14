using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.ExceptionServices;
using System.Security.Cryptography;
using System.Text;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Review;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.ToolService;

/// <summary>What one request asked of SOLIDWORKS, as the gate saw it.</summary>
public sealed class SwGateActivity
{
    public SwGateActivity(IReadOnlyList<string> gatedMembers, IReadOnlyList<string> refusedMembers)
    {
        GatedMembers = gatedMembers ?? throw new ArgumentNullException(nameof(gatedMembers));
        RefusedMembers = refusedMembers ?? throw new ArgumentNullException(nameof(refusedMembers));
    }

    /// <summary>Distinct interop member names, in the order they were first seen.</summary>
    public IReadOnlyList<string> GatedMembers { get; }

    /// <summary>Distinct members <see cref="ReadOnlyGuard"/> refused. Normally empty; SC-004 fails if it is not.</summary>
    public IReadOnlyList<string> RefusedMembers { get; }
}

/// <summary>
/// Collects, per request, the distinct set of interop member names <see cref="SwGate"/> was
/// asked about and the ones it refused (data-model.md, <c>ToolService</c>).
///
/// A set rather than a line per call, and the reason is the SOLIDWORKS thread: a full dump
/// makes tens of thousands of gated calls, and writing each one would put tens of thousands
/// of file writes on the thread the engineer is trying to use. The distinct set is what the
/// SC-004 audit actually asks for - "was every member this request touched a reader?" - and
/// it costs one hash lookup per call.
///
/// Not thread-safe, deliberately and for the same reason <see cref="SwGate"/> is not: one
/// gate, one recorder, one application thread.
/// </summary>
public sealed class SwGateRecorder : ISwGateObserver
{
    private static readonly string[] Nothing = new string[0];

    private readonly HashSet<string> _seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _gated = new List<string>();
    private readonly HashSet<string> _refusedSeen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _refused = new List<string>();

    public void Gated(string interopMember)
    {
        if (string.IsNullOrWhiteSpace(interopMember))
        {
            return;
        }

        if (_seen.Add(interopMember))
        {
            _gated.Add(interopMember);
        }
    }

    public void Refused(MutatingCallError refusal)
    {
        if (refusal == null || string.IsNullOrWhiteSpace(refusal.MemberName))
        {
            return;
        }

        if (_refusedSeen.Add(refusal.MemberName))
        {
            _refused.Add(refusal.MemberName);
        }
    }

    /// <summary>Takes what has been collected and starts the next request empty.</summary>
    public SwGateActivity Drain()
    {
        if (_gated.Count == 0 && _refused.Count == 0)
        {
            return new SwGateActivity(Nothing, Nothing);
        }

        var activity = new SwGateActivity(_gated.ToArray(), _refused.ToArray());
        _seen.Clear();
        _gated.Clear();
        _refusedSeen.Clear();
        _refused.Clear();
        return activity;
    }
}

/// <summary>
/// T047. One log line per request: the command, how long it took, the distinct interop
/// members the gate saw, and any refusal.
///
/// This is the artifact SC-004 is audited against (spec.md), so two properties matter more
/// than the format:
///
///   * <b>The secret is never written.</b> The line is built from the request's id and
///     command and the response's status, error and elapsed time - <see cref="BridgeResponse"/>
///     has no secret field at all - so there is no path by which one reaches the file, not
///     even for a request that was refused for having the wrong one (contracts/README.md).
///   * <b>Every request produces a line</b>, including refusals and errors, because an audit
///     of what did *not* happen is only as good as its record of what was attempted.
///
/// Wraps the dispatcher rather than living inside it, so it runs on the application thread,
/// immediately around the calls it is describing.
/// </summary>
public sealed class ToolServiceRequestLogger : IBridgeDispatcher
{
    private readonly IBridgeDispatcher _inner;
    private readonly SwGateRecorder _recorder;
    private readonly Action<string> _write;
    private readonly Func<DateTimeOffset> _now;

    public ToolServiceRequestLogger(
        IBridgeDispatcher inner,
        SwGateRecorder recorder,
        Action<string> write,
        Func<DateTimeOffset>? now = null)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _recorder = recorder ?? throw new ArgumentNullException(nameof(recorder));
        _write = write ?? throw new ArgumentNullException(nameof(write));
        _now = now ?? (() => DateTimeOffset.Now);
    }

    public BridgeResponse Dispatch(BridgeRequest request)
    {
        // Anything the gate saw before this line belongs to no request: T048 gives
        // `entity.show` the tool service's own scope, so Show in SOLIDWORKS runs through the
        // same gate, on the same application thread, between requests. The log is the artifact
        // SC-004 is audited from, and a `capture` line claiming it touched SelectByID2 would be
        // a false record of what that request did.
        _recorder.Drain();

        BridgeResponse response;
        try
        {
            response = _inner.Dispatch(request);
        }
        catch (Exception error)
        {
            // The dispatcher is supposed to turn everything into a response; if it did not,
            // the attempt is still recorded before the exception continues on its way.
            Write(request, BridgeResponse.Failed(request.Id, error.GetType().Name + ": " + error.Message));
            throw;
        }

        Write(request, response);
        return response;
    }

    /// <summary>The line, without its trailing newline. Public so the format has one owner.</summary>
    public static string Format(
        DateTimeOffset at, BridgeRequest request, BridgeResponse response, SwGateActivity activity)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        if (response == null)
        {
            throw new ArgumentNullException(nameof(response));
        }

        if (activity == null)
        {
            throw new ArgumentNullException(nameof(activity));
        }

        var line = new StringBuilder(160);
        line.Append('[').Append(at.ToString("O", CultureInfo.InvariantCulture)).Append("] ");
        line.Append("id=").Append(Field(request.Id));
        line.Append(" command=").Append(Field(request.Command));
        line.Append(" status=").Append(Field(response.Status));
        line.Append(" elapsed_ms=").Append(response.ElapsedMs.ToString(CultureInfo.InvariantCulture));
        line.Append(" gated=").Append(string.Join(",", activity.GatedMembers));

        if (activity.RefusedMembers.Count > 0)
        {
            line.Append(" refused=").Append(string.Join(",", activity.RefusedMembers));
        }

        if (!string.IsNullOrEmpty(response.Error))
        {
            line.Append(" error=\"").Append(Field(response.Error!)).Append('"');
        }

        return line.ToString();
    }

    private void Write(BridgeRequest request, BridgeResponse response)
    {
        SwGateActivity activity = _recorder.Drain();
        try
        {
            _write(Format(_now(), request, response, activity) + System.Environment.NewLine);
        }
        catch (Exception)
        {
            // A log that cannot be written must not fail the review it is describing.
        }
    }

    /// <summary>
    /// Keeps one record on one line and the quoting honest. A request id and a command name
    /// are client-supplied strings, and a newline inside one would forge a log record.
    /// </summary>
    private static string Field(string value) =>
        value.Replace("\r", " ").Replace("\n", " ").Replace("\"", "'");
}

/// <summary>
/// Turns "SOLIDWORKS said no" into "the document is gone" when that is what actually
/// happened (spec.md, edge cases; FR-022's failed-coverage path).
///
/// The engineer closes the assembly mid-review and every later interop call fails with a
/// COM error that means nothing to anyone. The Python client recognises one sentence -
/// <c>no longer open</c>, matched case-insensitively
/// (reviewer/src/swreview/bridge/client.py, <c>DOCUMENT_CLOSED_MARKER</c>) - and turns it
/// into failed coverage rather than a crashed review.
///
/// The check runs <b>after</b> the command, not before, for two reasons: a healthy request
/// never pays for it, and - more importantly - a request refused for its secret must not
/// cause any SOLIDWORKS call at all (contracts/README.md), which a pre-check would.
/// <c>circuit_open</c> is left alone too: the client already distinguishes it, and a dead
/// session is not the same fact as a closed document.
/// </summary>
public sealed class DocumentPresenceDispatcher : IBridgeDispatcher
{
    /// <summary>The documented answer, and the substring the Python client matches on.</summary>
    public const string DocumentClosedError =
        "document no longer open: the model the tool service attached to was closed in SOLIDWORKS";

    private readonly IBridgeDispatcher _inner;
    private readonly Func<bool> _documentIsOpen;

    public DocumentPresenceDispatcher(IBridgeDispatcher inner, Func<bool> documentIsOpen)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _documentIsOpen = documentIsOpen ?? throw new ArgumentNullException(nameof(documentIsOpen));
    }

    public BridgeResponse Dispatch(BridgeRequest request)
    {
        BridgeResponse response = _inner.Dispatch(request);

        if (response.Status != BridgeStatus.Error
            || string.Equals(response.Error, SwBridgeDispatcher.UnauthorizedError, StringComparison.Ordinal))
        {
            return response;
        }

        bool open;
        try
        {
            open = _documentIsOpen();
        }
        catch (Exception)
        {
            // If SOLIDWORKS cannot even answer that, the original error is the better one.
            return response;
        }

        if (open)
        {
            return response;
        }

        return new BridgeResponse
        {
            Id = response.Id,
            Status = BridgeStatus.Error,
            Result = null,
            Error = DocumentClosedError,
            ElapsedMs = response.ElapsedMs,
        };
    }
}

/// <summary>
/// The tool service's log file under <c>%LOCALAPPDATA%\SwReview\logs</c>.
///
/// Appended a line at a time rather than held open with a buffered writer: SOLIDWORKS can be
/// killed, and a log that loses its last minutes is no use for an audit of what the add-in
/// did just before it died.
/// </summary>
public sealed class ToolServiceLog
{
    private readonly object _gate = new object();

    public ToolServiceLog(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("A log path is required.", nameof(path));
        }

        Path = path;
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
    }

    public string Path { get; }

    /// <summary>The name one launch's log gets: <c>tool-service-20260913-101112.log</c>.</summary>
    public static string PathFor(string folder, DateTime at) => System.IO.Path.Combine(
        folder,
        "tool-service-" + at.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".log");

    /// <summary>Appends text exactly as given; the callers supply their own line endings.</summary>
    public void Write(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        lock (_gate)
        {
            try
            {
                File.AppendAllText(Path, text, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            }
            catch (IOException)
            {
                // There is nowhere left to report to.
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }

    /// <summary>A line, for the server's own lifecycle and failure messages.</summary>
    public void WriteLine(string message) => Write(
        "[" + DateTimeOffset.Now.ToString("O", CultureInfo.InvariantCulture) + "] "
        + message + System.Environment.NewLine);
}

/// <summary>Everything <see cref="ToolServiceHost"/> is given.</summary>
public sealed class ToolServiceOptions
{
    public ToolServiceOptions(ISldWorks swApp, IAppThreadInvoker invoker)
    {
        SwApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        Invoker = invoker ?? throw new ArgumentNullException(nameof(invoker));
    }

    /// <summary>The running SOLIDWORKS. Only ever touched on the application thread.</summary>
    public ISldWorks SwApp { get; }

    /// <summary>The Task Pane control, as the thing that owns the application thread.</summary>
    public IAppThreadInvoker Invoker { get; }

    /// <summary>The document to attach to; null means whatever is active.</summary>
    public string? DocumentPath { get; set; }

    /// <summary>Refused unless it is the active one: activating a configuration rebuilds the model.</summary>
    public string? Configuration { get; set; }

    /// <summary>%LOCALAPPDATA%\SwReview\logs.</summary>
    public string LogFolder { get; set; } = ReviewHostOptions.DefaultLogFolder();

    /// <summary>
    /// Where capture PNGs land. Chosen by the host and never by the client, because a path in
    /// a request would be a filesystem write the agent controls (research R4). The Python side
    /// copies what it wants into its own package, so temp is the right home.
    /// </summary>
    public string? CaptureDirectory { get; set; }

    public TimeSpan InvokeTimeout { get; set; } = InProcPipeServer.DefaultInvokeTimeout;

    /// <summary>How long <see cref="ToolServiceHost.Start"/> waits for the attach to run.</summary>
    public TimeSpan AttachTimeout { get; set; } = TimeSpan.FromSeconds(60);

    public Func<DateTime> Now { get; set; } = () => DateTime.Now;
}

/// <summary>
/// T047. The in-process tool service: the SOLIDWORKS half wired up, the two scoped secrets
/// minted, the pipe listening, and the log open.
///
/// The composition is the whole job, and three parts of it are decisions rather than plumbing:
///
///   * <b><see cref="SwScope.Open"/> runs on the application thread.</b> It walks the
///     component tree, which is hundreds of COM calls, and every pointer it keeps is bound to
///     the thread that made it. Attaching anywhere else would produce a scope that fails on
///     its first use.
///   * <b>Two secrets, not one.</b> The review session gets one that authorizes
///     <c>ping | capture | measure | interference</c>; the CLI's generated profile gets one
///     that authorizes <c>ping | capture | measure</c>. A single shared secret would
///     authenticate without bounding what it authorizes, and the CLI can read its own profile,
///     so the MCP allowlist withholds nothing on its own (contracts/README.md).
///   * <b>One host, one pipe name.</b> <c>swreview-&lt;guid&gt;</c>, because two Task Panes in
///     one SOLIDWORKS are two hosts in one process (see <see cref="PipeNames"/>).
/// </summary>
public sealed class ToolServiceHost : IToolService
{
    /// <summary>Bytes of entropy per secret. 256 bits, base64url, no padding.</summary>
    private const int SecretBytes = 32;

    private readonly InProcPipeServer _server;
    private readonly ToolServiceLog _log;
    private bool _disposed;

    private ToolServiceHost(
        InProcPipeServer server,
        ToolServiceLog log,
        string reviewSecret,
        string generalChatSecret,
        ISwSession session,
        string documentPath,
        string captureDirectory)
    {
        _server = server;
        _log = log;
        ReviewSecret = reviewSecret;
        GeneralChatSecret = generalChatSecret;
        Session = session;
        DocumentPath = documentPath;
        CaptureDirectory = captureDirectory;
    }

    /// <summary>The <c>swreview-&lt;guid&gt;</c> name both clients connect to.</summary>
    public string PipeName => _server.PipeName;

    /// <summary>Authorizes the whole vocabulary. Goes to the backend's <c>bridge</c> field (T048).</summary>
    public string ReviewSecret { get; }

    /// <summary>Authorizes <c>ping | capture | measure</c>. Goes to the CLI profile (T048).</summary>
    public string GeneralChatSecret { get; }

    /// <summary>
    /// The attached scope, on the application thread.
    ///
    /// Handed out so `entity.show` resolves a finding's persistent reference against the same
    /// session the bridge's capture, measure and interference commands run against (T048),
    /// rather than opening a second one per Show. Every pointer it holds belongs to the
    /// application thread, so a caller marshals onto that thread before touching it - which is
    /// what <c>SwEntityResolver</c> already does.
    /// </summary>
    public ISwSession Session { get; }

    /// <summary>The document the scope is bound to; component ids only mean anything for it.</summary>
    public string DocumentPath { get; }

    public string CaptureDirectory { get; }

    /// <summary>The SC-004 artifact.</summary>
    public string LogPath => _log.Path;

    /// <summary>What <c>POST /sessions</c> is given as <c>bridge</c>.</summary>
    public BridgeConfig ReviewBridge => new BridgeConfig(PipeName, ReviewSecret);

    /// <summary>What the CLI profile writer is given.</summary>
    public BridgeConfig GeneralChatBridge => new BridgeConfig(PipeName, GeneralChatSecret);

    /// <summary>
    /// Attaches to SOLIDWORKS on the application thread, then starts listening. Throws if the
    /// attach fails or the application thread does not answer, so the add-in can report it.
    /// </summary>
    public static ToolServiceHost Start(ToolServiceOptions options)
    {
        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        string pipeName = PipeNames.NewToolServiceName();
        string captureDirectory = options.CaptureDirectory
            ?? System.IO.Path.Combine(System.IO.Path.GetTempPath(), "swreview-bridge", pipeName);

        var log = new ToolServiceLog(ToolServiceLog.PathFor(options.LogFolder, options.Now()));
        string reviewSecret = NewSecret();
        string generalChatSecret = NewSecret();

        var recorder = new SwGateRecorder();

        // On the application thread, because every pointer this produces belongs to it.
        Attached attached = OnApplicationThread(
            options.Invoker,
            () => Attach(options, recorder, captureDirectory),
            options.AttachTimeout);

        var dispatcher = new SwBridgeDispatcher(
            attached.Services, new ScopedSecretPolicy(reviewSecret, generalChatSecret));

        // Outermost first: the log describes the answer that actually goes out, including one
        // rewritten because the document went away.
        var chain = new ToolServiceRequestLogger(
            new DocumentPresenceDispatcher(dispatcher, attached.DocumentIsOpen),
            recorder,
            log.Write);

        var server = new InProcPipeServer(
            new InProcPipeServerOptions(pipeName, chain, options.Invoker)
            {
                InvokeTimeout = options.InvokeTimeout,
                Log = log.WriteLine,
            });

        try
        {
            server.Start();
        }
        catch (Exception)
        {
            server.Dispose();
            throw;
        }

        log.WriteLine(
            $"attached to {attached.DocumentPath} [{attached.Configuration}], "
            + $"{attached.ComponentCount} components; captures go to {captureDirectory}");

        return new ToolServiceHost(
            server,
            log,
            reviewSecret,
            generalChatSecret,
            attached.Session,
            attached.DocumentPath,
            captureDirectory);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _server.Dispose();
    }

    /// <summary>
    /// A per-launch secret: 256 bits from the OS CSPRNG, base64url so it survives a JSON body,
    /// a command line's quoting rules and an environment block untouched.
    /// </summary>
    internal static string NewSecret()
    {
        var bytes = new byte[SecretBytes];
        using (RandomNumberGenerator random = RandomNumberGenerator.Create())
        {
            random.GetBytes(bytes);
        }

        return Convert.ToBase64String(bytes)
            .Replace('+', '-')
            .Replace('/', '_')
            .TrimEnd('=');
    }

    /// <summary>Runs ON the application thread. Every COM pointer below is created there.</summary>
    private static Attached Attach(
        ToolServiceOptions options, SwGateRecorder recorder, string captureDirectory)
    {
        var gate = new SwGate { Observer = recorder };
        SwSession session = SwSession.Attach(
            options.SwApp, options.DocumentPath, options.Configuration, gate);
        SwScope scope = SwScope.Open(options.SwApp, session);

        string documentPath = session.DocumentPath;
        var services = new BridgeServices(
            scope.CaptureView(),
            scope.MeasureSource(),
            scope.InterferenceSource(),
            scope.Components,
            captureDirectory)
        {
            SwVersion = session.SwVersion,
            DocumentPath = documentPath,
            Configuration = session.Configuration.Name,
        };

        // The attach itself is not part of any request; the first request starts clean.
        recorder.Drain();

        return new Attached(
            services,
            session,
            documentPath,
            session.Configuration.Name,
            scope.Components.Count,
            () => scope.OpenDocument(documentPath) != null);
    }

    /// <summary>
    /// Runs <paramref name="work"/> on the application thread and waits for it, rethrowing
    /// whatever it threw. Shares <see cref="AppThreadCall{T}"/> with the request path, so the
    /// one-off attach gets the same bounded wait and the same "a late delegate publishes
    /// nothing" guarantee.
    /// </summary>
    private static T OnApplicationThread<T>(IAppThreadInvoker invoker, Func<T> work, TimeSpan timeout)
    {
        if (!invoker.CanInvoke)
        {
            throw new InvalidOperationException(InProcPipeServer.UnavailableError + ".");
        }

        AppThreadCall<T> call = AppThreadCall<T>.Post(invoker, work);
        if (!call.Wait(timeout))
        {
            call.Abandon();
            throw new TimeoutException(InProcPipeServer.TimedOutError(timeout) + ".");
        }

        if (call.Failure != null)
        {
            ExceptionDispatchInfo.Capture(call.Failure).Throw();
        }

        return call.Result!;
    }

    /// <summary>What the attach produced, all of it bound to the application thread.</summary>
    private sealed class Attached
    {
        public Attached(
            BridgeServices services,
            ISwSession session,
            string documentPath,
            string configuration,
            int componentCount,
            Func<bool> documentIsOpen)
        {
            Services = services;
            Session = session;
            DocumentPath = documentPath;
            Configuration = configuration;
            ComponentCount = componentCount;
            DocumentIsOpen = documentIsOpen;
        }

        public BridgeServices Services { get; }

        /// <summary>The scope itself, for `entity.show` (T048).</summary>
        public ISwSession Session { get; }

        public string DocumentPath { get; }

        public string Configuration { get; }

        public int ComponentCount { get; }

        /// <summary>Asked on the application thread, after a failed command, and only then.</summary>
        public Func<bool> DocumentIsOpen { get; }
    }
}
