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
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.ToolService;

/// <summary>What one request asked of SOLIDWORKS, as the gate saw it.</summary>
public sealed class SwGateActivity
{
    public SwGateActivity(
        IReadOnlyList<string> gatedMembers,
        IReadOnlyList<string> refusedMembers,
        IReadOnlyList<string> targetPaths)
    {
        GatedMembers = gatedMembers ?? throw new ArgumentNullException(nameof(gatedMembers));
        RefusedMembers = refusedMembers ?? throw new ArgumentNullException(nameof(refusedMembers));
        TargetPaths = targetPaths ?? throw new ArgumentNullException(nameof(targetPaths));
    }

    /// <summary>Distinct interop member names, in the order they were first seen.</summary>
    public IReadOnlyList<string> GatedMembers { get; }

    /// <summary>Distinct members <see cref="ReadOnlyGuard"/> refused. Normally empty; SC-004 fails if it is not.</summary>
    public IReadOnlyList<string> RefusedMembers { get; }

    /// <summary>
    /// Feature 004: the distinct documents this request's mutating calls wrote to, in
    /// first-seen order, empty for a request that wrote nothing. The run report states from
    /// here, rather than from intent, that every write of the run went to the copy (FR-041).
    /// </summary>
    public IReadOnlyList<string> TargetPaths { get; }
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
    private readonly HashSet<string> _targetSeen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _targets = new List<string>();

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

    /// <summary>
    /// The document a mutating call wrote to, told by <see cref="RemodelGateRecorder"/> - the
    /// one observer that can tell a write from a read, because it is the one that knows the
    /// allowlist. Distinct, in first-seen order, for the same reason the members are.
    /// </summary>
    public void Wrote(string targetPath)
    {
        if (string.IsNullOrWhiteSpace(targetPath))
        {
            return;
        }

        if (_targetSeen.Add(targetPath))
        {
            _targets.Add(targetPath);
        }
    }

    /// <summary>Takes what has been collected and starts the next request empty.</summary>
    public SwGateActivity Drain()
    {
        if (_gated.Count == 0 && _refused.Count == 0)
        {
            return new SwGateActivity(Nothing, Nothing, Nothing);
        }

        var activity = new SwGateActivity(_gated.ToArray(), _refused.ToArray(), _targets.ToArray());
        _seen.Clear();
        _gated.Clear();
        _refusedSeen.Clear();
        _refused.Clear();
        _targetSeen.Clear();
        _targets.Clear();
        return activity;
    }
}

/// <summary>
/// T058. The remodel gate's observer: everything <see cref="SwGateRecorder"/> records, plus the
/// <b>target path of every mutating call</b> (contracts/guard-allowlist.md, FR-041).
///
/// It wraps the tool service's one recorder rather than replacing it, so a launch that runs a
/// remodel keeps one log line per request covering both gates and one drain point.
///
/// Telling a write from a read is the whole of what it adds, and only the stage-1 allowlist can
/// do that: <c>SwGate</c> hands an observer a string with no classification in it, and the
/// remodel family deliberately spells writes as interface-qualified keys and reads as bare
/// names. So a gated key on <see cref="RemodelGuard.IsAllowlisted"/> is a write, and its target
/// is whatever document the run is open on at that instant.
///
/// <b>Unknown stays unknown.</b> A write made before <c>remodel.open</c> has built the scope -
/// the three user-preference toggles and the modal-suppression flag, which name no document -
/// records <see cref="NoTarget"/> rather than the copy path that does not exist yet.
/// </summary>
public sealed class RemodelGateRecorder : ISwGateObserver
{
    /// <summary>What a mutating call with no document behind it records. Never a path.</summary>
    public const string NoTarget = "(none)";

    private readonly SwGateRecorder _recorder;
    private readonly Func<string?> _targetPath;

    /// <param name="recorder">The tool service's recorder, which keeps the one drained set.</param>
    /// <param name="targetPath">
    /// The copy the open remodel run writes to, or null when no run has a scope yet. Asked per
    /// mutating call rather than captured once: a run opens and closes inside one launch.
    /// </param>
    public RemodelGateRecorder(SwGateRecorder recorder, Func<string?> targetPath)
    {
        _recorder = recorder ?? throw new ArgumentNullException(nameof(recorder));
        _targetPath = targetPath ?? throw new ArgumentNullException(nameof(targetPath));
    }

    public void Gated(string interopMember)
    {
        _recorder.Gated(interopMember);

        if (!RemodelGuard.IsAllowlisted(interopMember))
        {
            return;
        }

        string? target = _targetPath();
        _recorder.Wrote(string.IsNullOrWhiteSpace(target) ? NoTarget : target!);
    }

    public void Refused(MutatingCallError refusal) => _recorder.Refused(refusal);
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
    private readonly Action<string>? _writeRemodel;
    private readonly Func<DateTimeOffset> _now;

    /// <param name="remodelLog">
    /// T070. Where a <c>remodel.*</c> request's line goes <b>as well</b>: `remodel.log` in the
    /// run folder (contracts/run-artifacts.md), so the run report has the record beside the
    /// artifacts it describes rather than in a launch-wide log the run folder does not carry.
    /// The same line, built once, so the two files cannot disagree - and redacted by the same
    /// construction, since <see cref="BridgeResponse"/> has no secret field at all. Null on a
    /// host that answers no remodel command.
    /// </param>
    public ToolServiceRequestLogger(
        IBridgeDispatcher inner,
        SwGateRecorder recorder,
        Action<string> write,
        Func<DateTimeOffset>? now = null,
        Action<string>? remodelLog = null)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _recorder = recorder ?? throw new ArgumentNullException(nameof(recorder));
        _write = write ?? throw new ArgumentNullException(nameof(write));
        _writeRemodel = remodelLog;
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

        if (activity.TargetPaths.Count > 0)
        {
            // Absent, rather than empty, for a request that wrote nothing: an empty field
            // would read like a write whose target could not be recorded.
            line.Append(" target=").Append(string.Join(",", activity.TargetPaths));
        }

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
        string line;
        try
        {
            line = Format(_now(), request, response, activity) + System.Environment.NewLine;
            _write(line);
        }
        catch (Exception)
        {
            // A log that cannot be written must not fail the review it is describing.
            return;
        }

        if (_writeRemodel == null || !RemodelCommands.IsRemodelCommand(request.Command))
        {
            return;
        }

        try
        {
            _writeRemodel(line);
        }
        catch (Exception)
        {
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
    /// <summary>
    /// The documented answer's opening, and the substring the Python client matches on. The
    /// message repeats it - see <see cref="DocumentClosedError"/> - because this half is the
    /// wire marker and the rest of the sentence is for the engineer.
    /// </summary>
    public const string DocumentClosedPrefix = "document no longer open";

    private readonly IBridgeDispatcher _inner;
    private readonly Func<bool> _documentIsOpen;
    private readonly string _attachedDocumentPath;

    /// <param name="inner">The dispatcher whose failures are re-read.</param>
    /// <param name="documentIsOpen">Asked on the application thread, after a failed command.</param>
    /// <param name="attachedDocumentPath">The document the scope is bound to. Named in the
    /// message, because the engineer reads that message against the document they are looking
    /// at (docs/pane-findings-2026-09-16.md, finding 1).</param>
    public DocumentPresenceDispatcher(
        IBridgeDispatcher inner,
        Func<bool> documentIsOpen,
        string attachedDocumentPath)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _documentIsOpen = documentIsOpen ?? throw new ArgumentNullException(nameof(documentIsOpen));
        _attachedDocumentPath = attachedDocumentPath
            ?? throw new ArgumentNullException(nameof(attachedDocumentPath));
    }

    /// <summary>
    /// The answer for a document that has gone, naming the one the scope is bound to. The old
    /// wording - "the model the tool service attached to was closed" - was accurate and still
    /// misled: the pane header shows an open document, and the engineer read the sentence
    /// against that one. The tool service now follows the active document
    /// (<see cref="ToolServiceGate.FollowDocument"/>), so what is left for this message is the
    /// window between the switch and the re-attach, and the attachment a running turn held.
    /// </summary>
    public static string DocumentClosedError(string attachedDocumentPath) =>
        DocumentClosedPrefix + ": the tool service is attached to " + attachedDocumentPath
        + ", which is no longer open in SOLIDWORKS";

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
            Error = DocumentClosedError(_attachedDocumentPath),
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

/// <summary>
/// T070. `remodel.log`, the run folder's own record of what the bridge was asked to do
/// (contracts/run-artifacts.md): one line per <c>remodel.*</c> request, with the command, the
/// elapsed time, the gated members and the target path of every mutating call.
///
/// The run folder is not known when the host starts - it is the folder the run's copy lives
/// under, and there is no copy until <c>remodel.open</c> has returned - so the path is asked
/// for per write rather than fixed at construction. Before that, and on a launch that runs no
/// remodel, there is nothing to write to and nothing is written; those requests are still in
/// the tool-service log, which is the SC-004 artifact.
/// </summary>
public sealed class RemodelRunLog
{
    /// <summary>The file's name inside the run folder. One spelling, here.</summary>
    public const string FileName = "remodel.log";

    private readonly Func<string?> _runDirectory;
    private ToolServiceLog? _log;

    public RemodelRunLog(Func<string?> runDirectory)
    {
        _runDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
    }

    /// <summary>Appends text exactly as given; the caller supplies its own line ending.</summary>
    public void Write(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        string? directory = _runDirectory();
        if (string.IsNullOrWhiteSpace(directory))
        {
            return;
        }

        string path = System.IO.Path.Combine(directory!, FileName);
        try
        {
            if (_log == null || !string.Equals(_log.Path, path, StringComparison.OrdinalIgnoreCase))
            {
                // One run, one file: re-made only when a later run opens a different folder.
                _log = new ToolServiceLog(path);
            }
        }
        catch (Exception)
        {
            // A run folder that cannot be written to must not fail the run it describes.
            _log = null;
            return;
        }

        _log.Write(text);
    }
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

    /// <summary>
    /// Feature 011 T074. The run folder of a review this add-in started, looked up by the
    /// folder's own name (<see cref="ReviewHost.ReviewRunDirectory"/>), or null for a run it did
    /// not start. The one lookup <c>drawing.read</c> resolves its <c>run_id</c> through
    /// (specs/011-drawing-context/contracts/confirmed-open.md section 2, item 1); asked on the
    /// application thread, per request. Null - the default - is a host that keeps no review
    /// records, and then the command has no source and answers that this bridge cannot read a
    /// drawing.
    /// </summary>
    public Func<string, string?>? ReviewRunDirectory { get; set; }

    /// <summary>How long <see cref="ToolServiceHost.Start"/> waits for the attach to run.</summary>
    public TimeSpan AttachTimeout { get; set; } = TimeSpan.FromSeconds(60);

    public Func<DateTime> Now { get; set; } = () => DateTime.Now;
}

/// <summary>
/// T047, T058, T070. The in-process tool service: the SOLIDWORKS half wired up, the scoped
/// secrets minted, the pipe listening, and the log open.
///
/// The composition is the whole job, and four parts of it are decisions rather than plumbing:
///
///   * <b><see cref="SwScope.Open"/> runs on the application thread.</b> It walks the
///     component tree, which is hundreds of COM calls, and every pointer it keeps is bound to
///     the thread that made it. Attaching anywhere else would produce a scope that fails on
///     its first use.
///   * <b>Three secrets, not one.</b> The review session gets one that authorizes
///     <c>ping | capture | measure | interference</c>; the CLI's generated profile gets one
///     that authorizes <c>ping | capture | measure</c>; the remodel backend session gets one
///     that authorizes <c>ping</c> and <c>remodel.*</c> and nothing else. A single shared
///     secret would authenticate without bounding what it authorizes, and the CLI can read its
///     own profile, so the MCP allowlist withholds nothing on its own (contracts/README.md).
///   * <b>The remodel gate is its own gate.</b> It is built with <see cref="RemodelGuard"/>
///     rather than the read-only guard, and its observer is the one that can tell a write from
///     a read, so `remodel.log` records the target path of every mutating call (FR-041). It
///     shares the one recorder, so a launch still writes one log line per request.
///   * <b>One host, one pipe name.</b> <c>swreview-&lt;guid&gt;</c>, because two Task Panes in
///     one SOLIDWORKS are two hosts in one process (see <see cref="PipeNames"/>).
///   * <b>The confirmed drawing's gate is observed by the plain recorder</b> (feature 011,
///     <see cref="ConfirmedDrawingSource"/>): its three keys join the request's own
///     <c>gated=</c> line, and no <c>target=</c> is written for a read that writes nothing.
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
        string remodelSecret,
        bool remodelSeatAvailable,
        ISwSession session,
        string documentPath,
        string captureDirectory)
    {
        _server = server;
        _log = log;
        ReviewSecret = reviewSecret;
        GeneralChatSecret = generalChatSecret;
        RemodelSecret = remodelSecret;
        RemodelSeatAvailable = remodelSeatAvailable;
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
    /// T070. Authorizes <c>ping</c> and <c>remodel.*</c>, and nothing else. Goes to the remodel
    /// backend session and to nothing else - never to the review session, never to the CLI
    /// profile, and never to the tool layer, which has no remodel command to call
    /// (contracts/tools.md).
    /// </summary>
    public string RemodelSecret { get; }

    /// <summary>Whether the attached bridge was given a remodel seat.</summary>
    public bool RemodelSeatAvailable { get; }

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

    /// <summary>
    /// One timestamped line into this launch's log, for the gate: the only thing it has to say
    /// is why it is leaving this service attached to a document the engineer has switched away
    /// from, which belongs beside the <c>attached to ...</c> line rather than in the add-in log.
    /// </summary>
    public void WriteLog(string line) => _log.WriteLine(line);

    /// <summary>What <c>POST /sessions</c> is given as <c>bridge</c>.</summary>
    public BridgeConfig ReviewBridge => new BridgeConfig(PipeName, ReviewSecret);

    /// <summary>What the CLI profile writer is given.</summary>
    public BridgeConfig GeneralChatBridge => new BridgeConfig(PipeName, GeneralChatSecret);

    /// <summary>What the remodel backend session is given, and no one else (T070).</summary>
    public BridgeConfig RemodelBridge => new BridgeConfig(PipeName, RemodelSecret);

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
        string remodelSecret = NewSecret();

        var recorder = new SwGateRecorder();

        // The re-modeler's own gate: RemodelGuard rather than the read-only guard, which is
        // the only reason a write can pass at all. Its observer is attached below, once there
        // is a dispatcher to ask which document the open run is writing to.
        var remodelGate = new SwGate(new CircuitBreaker(), new RemodelGuard());

        // On the application thread, because every pointer this produces belongs to it.
        Attached attached = OnApplicationThread(
            options.Invoker,
            () => Attach(options, recorder, captureDirectory, remodelGate),
            options.AttachTimeout);

        var dispatcher = new SwBridgeDispatcher(
            attached.Services,
            new ScopedSecretPolicy(reviewSecret, generalChatSecret, remodelSecret));

        remodelGate.Observer = new RemodelGateRecorder(recorder, () => dispatcher.RemodelTargetPath);

        IBridgeDispatcher chain = RequestChain(
            dispatcher, attached.DocumentIsOpen, attached.DocumentPath, recorder, log.Write);

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
            remodelSecret,
            attached.Services.RemodelSeat != null,
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
    /// The request path around <paramref name="dispatcher"/>, outermost first: the log describes
    /// the answer that actually goes out, including one rewritten because the document went away.
    /// A remodel request's line is written to the run folder's `remodel.log` as well, where the
    /// run report reads it. Internal so the wiring tests drive the chain this host builds rather
    /// than a copy of it.
    /// </summary>
    internal static IBridgeDispatcher RequestChain(
        SwBridgeDispatcher dispatcher,
        Func<bool> documentIsOpen,
        string documentPath,
        SwGateRecorder recorder,
        Action<string> write) =>
        new ToolServiceRequestLogger(
            new DocumentPresenceDispatcher(dispatcher, documentIsOpen, documentPath),
            recorder,
            write,
            remodelLog: new RemodelRunLog(() => dispatcher.RemodelRunDirectory).Write);

    /// <summary>
    /// Feature 011 T074: the source <c>drawing.read</c> reads a confirmed candidate through
    /// (specs/011-drawing-context/contracts/confirmed-open.md sections 2 to 4), or null when the
    /// host was given no review records to resolve a <c>run_id</c> through - the dispatcher then
    /// answers that this bridge cannot read a drawing.
    ///
    /// <b>The run comes from the review host's records, never from the request.</b>
    /// <paramref name="reviewRunDirectory"/> is <see cref="ReviewHost.ReviewRunDirectory"/>: the
    /// id is compared with a review record's folder name and nothing else, so a Model check's,
    /// Standards run's or remodel run's record, an unknown id and a path spelling all answer null,
    /// which the confirmed read refuses naming the id before anything is opened.
    ///
    /// <b>On the application thread.</b> Built by <see cref="Attach"/>, which runs there, over
    /// seams bound to the attached session; <see cref="InProcPipeServer"/> posts every request to
    /// the same thread through the host's invoker, so the lookup, the open and the read run where
    /// every other command runs.
    ///
    /// <b>The plain recorder, not the remodel gate's.</b> The seam's own gate
    /// (<see cref="DrawingOpenGuard"/>) reports to <paramref name="recorder"/>, so its three keys
    /// join the request's <c>gated=</c> line. <see cref="RemodelGateRecorder"/> would record a
    /// target for every key on the remodel allowlist - <c>ISldWorks.CloseDoc</c> is one - and a
    /// read that writes nothing must never appear as a write to a copy.
    ///
    /// <b>The switch is the caller's to pass.</b> The add-in passes
    /// <see cref="DrawingOpenScope.SeatValidated"/>, false until probe D14 passes at a seat
    /// (T077): a closed candidate is then refused with the seam's sentence and an open one is
    /// still read, since reading it opens nothing.
    /// </summary>
    internal static IConfirmedDrawingSource? ConfirmedDrawingSource(
        Func<string, string?>? reviewRunDirectory,
        string attachedDocumentPath,
        SwGateRecorder recorder,
        IDrawingOpenHost host,
        bool seatValidated,
        IDrawingSource drawings,
        IDocumentSource documents,
        IManifestSource manifest)
    {
        if (reviewRunDirectory == null)
        {
            return null;
        }

        return new ConfirmedDrawingRead(
            reviewRunDirectory,
            attachedDocumentPath,
            File.Exists,
            new DrawingOpenScope(host, recorder, seatValidated),
            drawings,
            documents,
            manifest);
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
        ToolServiceOptions options,
        SwGateRecorder recorder,
        string captureDirectory,
        SwGate remodelGate)
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

            // Lever 10a. Review scope only, which the ScopedSecretPolicy enforces: a mesh
            // fetch writes a file and can take seconds, so it is not general chat's to call.
            TessellateSource = scope.TessellateSource(),

            // The gate the remodel.* commands call through. The seat itself is not wired here:
            // this host attaches to the document the engineer has open, and the re-modeler
            // reaches SOLIDWORKS through its own seat, so until one is handed over every
            // remodel command answers "this bridge was not built with a remodel seat".
            RemodelGate = remodelGate,

            // Feature 011 T074, review scope only (ScopedSecretPolicy): a confirmed candidate,
            // read into the review's package through the review host's own records, over the
            // drawing phase, the document phase and the manifest of this session's gate.
            ConfirmedDrawings = ConfirmedDrawingSource(
                options.ReviewRunDirectory,
                documentPath,
                recorder,
                new SwDrawingOpenHost(options.SwApp),
                DrawingOpenScope.SeatValidated,
                new DrawingDumper(session.Gate, new SwDrawingReader(session, new PersistRefService(session.Gate))),
                new PropertyDumper(session, options.SwApp),
                new ManifestBuilder(session.Gate)),
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
