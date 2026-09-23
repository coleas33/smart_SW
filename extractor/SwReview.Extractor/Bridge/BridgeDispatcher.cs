using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Measure;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using IrCapture = SwReview.Extractor.Ir.Capture;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Bridge;

/// <summary>Turns one request into one response. The pipe knows nothing about commands.</summary>
public interface IBridgeDispatcher
{
    BridgeResponse Dispatch(BridgeRequest request);
}

/// <summary>What <c>ping</c> answers: enough to prove the worker is alive and on the right model.</summary>
public sealed class PingResult
{
    [JsonPropertyName("pong")]
    public bool Pong { get; set; } = true;

    /// <summary>The protocol this server speaks; see SwReview.Extractor.Console/Serve/PROTOCOL.md.</summary>
    [JsonPropertyName("protocol")]
    public string Protocol { get; set; } = SwBridgeDispatcher.ProtocolVersion;

    [JsonPropertyName("sw_version")]
    public string? SwVersion { get; set; }

    /// <summary>Full path of the document the worker attached to.</summary>
    [JsonPropertyName("document")]
    public string? Document { get; set; }

    [JsonPropertyName("configuration")]
    public string? Configuration { get; set; }

    /// <summary>
    /// How many components carry an id. Component ids only mean the same thing here as in
    /// package.json while this is the document that was dumped.
    /// </summary>
    [JsonPropertyName("component_count")]
    public int ComponentCount { get; set; }
}

/// <summary>What <c>capture</c> answers.</summary>
public sealed class CaptureCommandResult
{
    /// <summary>The IR row to append to <c>captures</c>, or null when the capture failed.</summary>
    [JsonPropertyName("capture")]
    public IrCapture? Capture { get; set; }

    /// <summary>Absolute path of the PNG, so the client can copy it into its own package.</summary>
    [JsonPropertyName("path")]
    public string? Path { get; set; }

    /// <summary>The gap to record when the capture failed, else null.</summary>
    [JsonPropertyName("gap")]
    public Gap? Gap { get; set; }
}

/// <summary>What <c>measure</c> answers: SOLIDWORKS' numbers, in meters, unrounded.</summary>
public sealed class MeasureCommandResult
{
    [JsonPropertyName("distance")]
    public Quantity? Distance { get; set; }

    [JsonPropertyName("delta_x")]
    public Quantity? DeltaX { get; set; }

    [JsonPropertyName("delta_y")]
    public Quantity? DeltaY { get; set; }

    [JsonPropertyName("delta_z")]
    public Quantity? DeltaZ { get; set; }
}

/// <summary>What <c>tessellate</c> answers: the rows written, and where they landed.</summary>
public sealed class TessellateCommandResult
{
    /// <summary>The IR rows to append to <c>bodies</c>, one per body that was written.</summary>
    [JsonPropertyName("bodies")]
    public List<BodyRef> Bodies { get; set; } = new List<BodyRef>();

    /// <summary>
    /// The absolute path of each row's <c>mesh_file</c>, in the same order, so a client can
    /// see the files are inside the directory the host chose for them.
    /// </summary>
    [JsonPropertyName("paths")]
    public List<string> Paths { get; set; } = new List<string>();

    /// <summary>
    /// Why a body is missing from <see cref="Bodies"/>. A component that produced none comes
    /// back here rather than as an empty answer: an empty answer reads as "this component has
    /// no body", which is a clear the reviewer never established.
    /// </summary>
    [JsonPropertyName("gaps")]
    public List<Gap> Gaps { get; set; } = new List<Gap>();
}

/// <summary>
/// T097, lever 10a. One component's bodies, tessellated into the package directory the host
/// chose, through the same export path the dump uses.
///
/// An interface for the same reason the other three are: the dispatcher is unit tested with
/// fakes and no SOLIDWORKS. The real one is <see cref="Dump.SwTessellateSource"/>.
/// </summary>
public interface ITessellateSource
{
    /// <param name="componentId">The package id of the component to tessellate.</param>
    /// <param name="packageDirectory">
    /// The package directory the host chose. Never a path from the request: that would be a
    /// filesystem write the agent controls (research R4).
    /// </param>
    TessellateCommandResult Tessellate(string componentId, string packageDirectory);
}

/// <summary>
/// What <c>drawing.read</c> answers (protocol 1.3, feature 011, contracts/confirmed-open.md
/// section 2): which document's candidate was read, the drawing's own document id, what the seam
/// did, and how many sheets and gaps it added to the package.
/// </summary>
public sealed class ConfirmedDrawingResult
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("drawing_document_id")]
    public string DrawingDocumentId { get; set; } = string.Empty;

    /// <summary>True when the read opened the drawing; false when it was already open.</summary>
    [JsonPropertyName("opened")]
    public bool Opened { get; set; }

    /// <summary>True when the read closed what it opened.</summary>
    [JsonPropertyName("closed")]
    public bool Closed { get; set; }

    [JsonPropertyName("sheets")]
    public int Sheets { get; set; }

    [JsonPropertyName("gaps")]
    public int Gaps { get; set; }
}

/// <summary>
/// A <c>drawing.read</c> the host refused, with the sentence it answers: nothing was opened, or
/// the seam refused the open.
/// </summary>
public sealed class ConfirmedDrawingRefused : InvalidOperationException
{
    public ConfirmedDrawingRefused(string message)
        : base(message)
    {
    }
}

/// <summary>
/// The host side of <c>drawing.read</c> (feature 011): reads the confirmed candidate of one
/// document into one review's package, resolving everything from the host's own records, and
/// refusing with <see cref="ConfirmedDrawingRefused"/> when any step fails. The real one is
/// <see cref="Dump.ConfirmedDrawingRead"/>, which the add-in builds on its review records.
/// </summary>
public interface IConfirmedDrawingSource
{
    ConfirmedDrawingResult Read(string runId, string documentId);
}

/// <summary>What <c>interference</c> answers.</summary>
public sealed class InterferenceCommandResult
{
    [JsonPropertyName("interferences")]
    public List<IrInterference> Interferences { get; set; } = new List<IrInterference>();

    [JsonPropertyName("gaps")]
    public List<Gap> Gaps { get; set; } = new List<Gap>();
}

/// <summary>
/// Everything the dispatcher needs, as interfaces, so the command handling is unit tested
/// with fakes and no SOLIDWORKS (T072). <see cref="PipeServer"/> builds the real one on the
/// STA worker thread, because the COM pointers inside must not cross threads.
/// </summary>
public sealed class BridgeServices
{
    public BridgeServices(
        ICaptureView capture,
        IMeasureSource measure,
        IInterferenceSource interference,
        ComponentIndex components,
        string captureDirectory)
    {
        CaptureView = capture ?? throw new ArgumentNullException(nameof(capture));
        Measure = measure ?? throw new ArgumentNullException(nameof(measure));
        Interference = interference ?? throw new ArgumentNullException(nameof(interference));
        Components = components ?? throw new ArgumentNullException(nameof(components));
        CaptureDirectory = captureDirectory ?? throw new ArgumentNullException(nameof(captureDirectory));
    }

    public ICaptureView CaptureView { get; }

    public IMeasureSource Measure { get; }

    public IInterferenceSource Interference { get; }

    /// <summary>Package component ids to live components, and back.</summary>
    public ComponentIndex Components { get; }

    /// <summary>
    /// The package directory captures are written under, and the one <c>tessellate</c>
    /// writes its <c>meshes/</c> under. Chosen by the host from <c>--out</c>, never by the
    /// client: a path in a request would be a filesystem write the agent controls
    /// (research R4).
    /// </summary>
    public string CaptureDirectory { get; }

    public string? SwVersion { get; set; }

    public string? DocumentPath { get; set; }

    public string? Configuration { get; set; }

    /// <summary>
    /// Feature 005, lever 10a. The mesh export <c>tessellate</c> calls, or null on a bridge
    /// that answers no mesh fetch. Null is the default, so a host hands the command a source
    /// deliberately, and a host that has not answers with a sentence rather than with an
    /// empty body list that would read as "this component has no body".
    /// </summary>
    public ITessellateSource? TessellateSource { get; set; }

    /// <summary>
    /// Feature 004. The SOLIDWORKS side of the <c>remodel.*</c> family, or null on a bridge
    /// that answers no remodel command - the console host and every review session. Null is
    /// the default, so a host has to hand the re-modeler a seat deliberately.
    /// </summary>
    public IRemodelSeat? RemodelSeat { get; set; }

    /// <summary>
    /// The gate the remodel commands call through: a <see cref="SwGate"/> built with a
    /// <see cref="RemodelGuard"/>, and carrying the host's <c>ISwGateObserver</c> so
    /// `remodel.log` records the gated members and the target path of every mutating call.
    /// Null means the dispatcher builds its own, unobserved.
    /// </summary>
    public SwGate? RemodelGate { get; set; }

    /// <summary>
    /// Feature 004. This run's folder, as <c>RunFolders.CreateForRemodel</c> made it.
    ///
    /// <b>Chosen by the host, never by the client</b>, for the same reason
    /// <see cref="CaptureDirectory"/> is (research R4): a run folder derived from the
    /// request's own <c>copy_path</c> would make <c>AssertSaveTarget</c>'s "inside this run's
    /// folder" and "not another run's copy" self-satisfying, and the client could then have
    /// the re-modeler create and save a copy beside the engineer's file - possibly inside an
    /// EPDM vault - which is what OQ-10 says must be structurally impossible.
    ///
    /// Null on a bridge that answers no remodel command, exactly like
    /// <see cref="RemodelSeat"/>: <c>remodel.open</c> refuses rather than inventing one.
    /// </summary>
    public string? RemodelRunRoot { get; set; }

    /// <summary>
    /// Feature 011, protocol 1.3. The source <c>drawing.read</c> reads a confirmed candidate
    /// through, or null on a bridge that reads none - the console host above all, which keeps no
    /// review records. Null is the default, so a host hands the command a source deliberately.
    /// </summary>
    public IConfirmedDrawingSource? ConfirmedDrawings { get; set; }
}

/// <summary>
/// T072. The bridge's command handling.
///
/// Four things happen to every request, whatever the command:
///   * the <see cref="ISecretPolicy"/> is asked whether the request's <c>secret</c>
///     authorizes its command, before anything else runs (T045). The console host passes
///     <see cref="NoSecretPolicy"/> and this is a no-op; the add-in's in-process host
///     passes a <see cref="ScopedSecretPolicy"/>, which is where <c>interference</c> is
///     actually withheld from general chat.
///   * <see cref="ReadOnlyGuard"/> is asked about the command name, so a request that names
///     a mutating API - <c>Save3</c>, <c>FeatureCut4</c> - is refused before anything runs.
///     Everything the handlers then call goes through <c>SwGate</c>, which asks again.
///   * A <see cref="CircuitOpenError"/> becomes <c>circuit_open</c> rather than an error, so
///     the client can stop asking instead of retrying a dead session.
///   * The response carries the elapsed milliseconds, because a bridge call that took eight
///     seconds is information the reviewer's timing report wants.
/// </summary>
public sealed class SwBridgeDispatcher : IBridgeDispatcher
{
    /// <summary>
    /// Bumped when a request or response shape changes; see
    /// SwReview.Extractor.Console/Serve/PROTOCOL.md.
    ///
    /// 1.1 is additive: the four 1.0 commands and the envelope are untouched, and it adds the
    /// <c>remodel.*</c> family and <c>result.error_code</c> on a failed reply. 1.2 is additive
    /// again: everything 1.1 speaks is unchanged and it adds one command, <c>tessellate</c>. 1.3
    /// (feature 011) adds one more, <c>drawing.read</c>, and changes nothing else.
    /// <c>ping</c> reports this value and a client compares against it
    /// (<c>PROTOCOL_VERSION</c> in <c>reviewer/src/swreview/bridge/client.py</c>), so it is
    /// what the document says it is or the two ends have already come apart.
    /// </summary>
    public const string ProtocolVersion = "1.3";

    /// <summary>
    /// The whole of what a refused request is told (T045). One word, the same for a wrong
    /// secret, a missing one, and a valid one asking for a command outside its scope.
    /// </summary>
    public const string UnauthorizedError = "unauthorized";

    private readonly BridgeServices _services;
    private readonly ISecretPolicy _secrets;
    private readonly CaptureService _captures;

    /// <summary>The gate every <c>remodel.*</c> call goes through (feature 004).</summary>
    private readonly SwGate _remodelGate;

    /// <summary>The probes this bridge session performed, and the reading they were made of.</summary>
    private readonly RemodelScopeProbe _probes;

    /// <summary>
    /// The one remodel run this session may have open. Built by <c>remodel.open</c> and by
    /// nothing else, and it holds the only <c>IModelDoc2</c> any remodel command can reach.
    /// </summary>
    private RemodelSession? _session;

    /// <param name="services">Everything SOLIDWORKS, as interfaces.</param>
    /// <param name="secrets">
    /// How the <c>secret</c> on a request line is judged. Required rather than defaulted,
    /// so neither host can end up permissive by omission: the console host passes
    /// <see cref="NoSecretPolicy.Instance"/> and says so at its call site.
    /// </param>
    /// <param name="captureIds">Test hook: the allocator capture ids come from.</param>
    public SwBridgeDispatcher(
        BridgeServices services, ISecretPolicy secrets, Ids.IdAllocator? captureIds = null)
    {
        _services = services ?? throw new ArgumentNullException(nameof(services));
        _secrets = secrets ?? throw new ArgumentNullException(nameof(secrets));
        _captures = new CaptureService(services.CaptureView, captureIds);
        _remodelGate = services.RemodelGate
            ?? new SwGate(new CircuitBreaker(), new RemodelGuard());
        _probes = new RemodelScopeProbe(_remodelGate);
    }

    /// <summary>
    /// The copy every write of the open remodel run goes to, or null when this session has no
    /// run - which includes the whole of <c>remodel.open</c> up to the moment its scope exists.
    ///
    /// Read by the host's remodel gate observer, per mutating call, so `remodel.log` records
    /// the target of every write from the scope that verified it rather than from intent
    /// (FR-041). Null is reported as unknown there; it is never filled in with a guess.
    /// </summary>
    public string? RemodelTargetPath => _session?.Scope.CopyPath;

    /// <summary>This run's folder, where `remodel.log` is written, or null when no run is open.</summary>
    public string? RemodelRunDirectory => _session?.Scope.RunDirectory;

    public BridgeResponse Dispatch(BridgeRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        var clock = Stopwatch.StartNew();
        BridgeResponse response;

        try
        {
            if (!_secrets.IsAuthorized(request.Secret, request.Command))
            {
                // Authenticate and authorize before the command is even looked up, so a
                // refused caller cannot learn what this bridge answers, and nothing it
                // named ever touches SOLIDWORKS. The secret itself is not echoed.
                response = BridgeResponse.Failed(request.Id, UnauthorizedError);
            }
            else
            {
                // The guard sees the command name itself, so "command": "Save3" cannot reach
                // a handler even if one were ever added for it.
                ReadOnlyGuard.Assert(request.Command);
                response = Run(request);
            }
        }
        catch (CircuitOpenError error)
        {
            response = BridgeResponse.CircuitOpen(request.Id, error.Message);
        }
        catch (RemodelCommandError error)
        {
            // The one addition protocol 1.0 makes for this family: the refusal carries a
            // stable token, so the Python client maps it to a class without reading prose.
            response = BridgeResponse.Failed(request.Id, error.Message, error.ToResult());
        }
        catch (MutatingCallError error)
        {
            response = BridgeResponse.Failed(
                request.Id,
                error.Message,
                RemodelCommands.IsRemodelCommand(request.Command)
                    ? new RemodelErrorResult(RemodelErrorCodes.GuardRefused, "member", error.MemberName)
                    : null);
        }
        catch (Exception error)
        {
            response = BridgeResponse.Failed(
                request.Id, error.GetType().Name + ": " + error.Message);
        }

        clock.Stop();
        response.ElapsedMs = clock.ElapsedMilliseconds;
        return response;
    }

    private BridgeResponse Run(BridgeRequest request)
    {
        switch (request.Command)
        {
            case BridgeCommands.Ping:
                return BridgeResponse.Ok(request.Id, Ping());

            case BridgeCommands.Capture:
                return Capture(request);

            case BridgeCommands.Measure:
                return Measure(request);

            case BridgeCommands.Interference:
                return Interference(request);

            case BridgeCommands.Tessellate:
                return Tessellate(request);

            case BridgeCommands.DrawingRead:
                return DrawingRead(request);

            default:
                if (RemodelCommandTable.Find(request.Command) != null)
                {
                    return Remodel(request);
                }

                return BridgeResponse.Failed(
                    request.Id,
                    $"Unknown command '{request.Command}'. This bridge answers "
                    + string.Join(", ", BridgeCommands.All) + ".");
        }
    }

    private PingResult Ping() => new PingResult
    {
        SwVersion = _services.SwVersion,
        Document = _services.DocumentPath,
        Configuration = _services.Configuration,
        ComponentCount = _services.Components.Count,
    };

    private BridgeResponse Capture(BridgeRequest request)
    {
        string persistRef = RequiredString(request, "persist_ref");
        string view = OptionalString(request, "view") ?? CaptureViews.Fit;
        string? scope = OptionalString(request, "scope_document");
        string note = OptionalString(request, "note") ?? string.Empty;

        if (!CaptureViews.IsKnown(view))
        {
            return BridgeResponse.Failed(
                request.Id,
                $"\"view\" must be one of {string.Join(", ", CaptureViews.All)}; got '{view}'.");
        }

        CaptureResult result = _captures.Capture(
            persistRef, scope, view, _services.CaptureDirectory, note);

        if (!result.Succeeded)
        {
            Gap? gap = result.Gap;
            return BridgeResponse.Failed(
                request.Id,
                gap == null
                    ? "The capture did not happen."
                    : gap.Reason + (gap.Error == null ? string.Empty : " - " + gap.Error),
                new CaptureCommandResult { Capture = null, Path = null, Gap = gap });
        }

        return BridgeResponse.Ok(
            request.Id,
            new CaptureCommandResult
            {
                Capture = result.Capture,
                Path = Path.GetFullPath(
                    Path.Combine(
                        _services.CaptureDirectory,
                        result.Capture!.File.Replace('/', Path.DirectorySeparatorChar))),
                Gap = null,
            });
    }

    private BridgeResponse Measure(BridgeRequest request)
    {
        string a = RequiredString(request, "persist_ref_a");
        string b = RequiredString(request, "persist_ref_b");
        string? scopeA = OptionalString(request, "scope_document_a");
        string? scopeB = OptionalString(request, "scope_document_b");

        try
        {
            MeasureReading reading = _services.Measure.Measure(a, scopeA, b, scopeB);
            return BridgeResponse.Ok(
                request.Id,
                new MeasureCommandResult
                {
                    Distance = reading.Distance,
                    DeltaX = reading.DeltaX,
                    DeltaY = reading.DeltaY,
                    DeltaZ = reading.DeltaZ,
                });
        }
        catch (MeasureNotAvailableError error)
        {
            // An unsupported pairing is an error with a sentence, never a number
            // (constitution Principle I).
            return BridgeResponse.Failed(request.Id, error.Message);
        }
    }

    private BridgeResponse Interference(BridgeRequest request)
    {
        IReadOnlyList<string> componentIds = StringArray(request, "component_ids");
        string configuration = OptionalString(request, "configuration")
            ?? _services.Configuration
            ?? string.Empty;

        InterferenceRunSettings settings;
        try
        {
            settings = ReadSettings(request);
        }
        catch (ArgumentException error)
        {
            return BridgeResponse.Failed(request.Id, error.Message);
        }

        int? truncateAfter = OptionalInt(request, "truncate_after");

        List<InterferencePair> pairs;
        try
        {
            pairs = Pairs(componentIds);
        }
        catch (ArgumentException error)
        {
            return BridgeResponse.Failed(request.Id, error.Message);
        }

        var runner = new InterferenceRunner(_services.Interference);
        InterferenceRunResult result = runner.Run(
            configuration,
            pairs,
            settings,
            handle => _services.Components.IdOf(handle),
            id => _services.Components.PatternOf(id),
            truncateAfter);

        return BridgeResponse.Ok(
            request.Id,
            new InterferenceCommandResult
            {
                Interferences = new List<IrInterference>(result.Interferences),
                Gaps = new List<Gap>(result.Gaps),
            });
    }

    /// <summary>
    /// T097, lever 10a. One component's bodies, written under the package directory the host
    /// was started with - exactly as <c>capture</c> writes its PNG there, and for the same
    /// reason: a filesystem path in a request would be a write the agent controls
    /// (research R4), so nothing in <c>params</c> can move this.
    ///
    /// A component this document does not have is refused by name rather than answered with
    /// no bodies, because "no bodies" is what a component with nothing to sweep looks like.
    /// </summary>
    private BridgeResponse Tessellate(BridgeRequest request)
    {
        string componentId = RequiredString(request, "component_id");

        if (_services.TessellateSource == null)
        {
            return BridgeResponse.Failed(
                request.Id,
                "This bridge cannot tessellate: it was built without a mesh source.");
        }

        if (_services.Components.ById(componentId) == null)
        {
            return BridgeResponse.Failed(
                request.Id,
                $"'{componentId}' is not a component of the document this bridge is attached "
                + $"to ({_services.DocumentPath ?? "unknown"}).");
        }

        return BridgeResponse.Ok(
            request.Id,
            _services.TessellateSource.Tessellate(componentId, _services.CaptureDirectory));
    }

    /// <summary>The whole of what <c>drawing.read</c> is handed: a run id and a document id.</summary>
    private static readonly string[] DrawingReadParameters = { "run_id", "document_id" };

    /// <summary>
    /// Feature 011, protocol 1.3 (contracts/confirmed-open.md section 2). Reads the candidate the
    /// engineer confirmed into the review's package, through the host's
    /// <see cref="BridgeServices.ConfirmedDrawings"/>. Any parameter but the two - a path above
    /// all - is refused before anything runs: the host resolves the run folder, the package and
    /// the file from its own records, so the caller can never name what SOLIDWORKS opens.
    /// </summary>
    private BridgeResponse DrawingRead(BridgeRequest request)
    {
        if (request.Params.ValueKind == JsonValueKind.Object)
        {
            foreach (JsonProperty member in request.Params.EnumerateObject())
            {
                if (Array.IndexOf(DrawingReadParameters, member.Name) < 0)
                {
                    return BridgeResponse.Failed(
                        request.Id,
                        $"'{BridgeCommands.DrawingRead}' takes only \"run_id\" and \"document_id\"; "
                        + $"\"{member.Name}\" was refused, so nothing was opened.");
                }
            }
        }

        string runId = RequiredString(request, "run_id");
        string documentId = RequiredString(request, "document_id");

        if (_services.ConfirmedDrawings == null)
        {
            return BridgeResponse.Failed(
                request.Id,
                "This bridge cannot read a drawing: only the add-in's review host reads a confirmed "
                + "candidate, from its own review records.");
        }

        try
        {
            return BridgeResponse.Ok(request.Id, _services.ConfirmedDrawings.Read(runId, documentId));
        }
        catch (ConfirmedDrawingRefused refusal)
        {
            return BridgeResponse.Failed(request.Id, refusal.Message);
        }
    }

    // =================================================================================
    // The remodel.* family (T062). Every handler below reaches the document through
    // _session, and _session is built by exactly one command, remodel.open. No handler
    // takes a document, and nothing here can name one.
    // =================================================================================

    /// <summary>
    /// <c>OpenDoc7</c>, as the gate is told about it. A read as far as
    /// <see cref="ReadOnlyGuard"/> is concerned, and recorded so the log shows what was opened.
    /// </summary>
    private const string OpenDocMember = "OpenDoc7";

    /// <summary><c>ICustomPropertyManager.Add3</c>: the session tag, written before any scope exists.</summary>
    private const string TagMember = "ICustomPropertyManager.Add3";

    /// <summary>The other half of the session tag: written at open, removed at close.</summary>
    private const string UntagKey = "ICustomPropertyManager.Delete2";

    /// <summary>The feature-tree walk, as the gate is told about it.</summary>
    private const string FeaturesMember = "GetFeatures";

    private const string IsRolledBackMember = "IsRolledBack";
    private const string WhatsWrongCountMember = "GetWhatsWrongCount";
    private const string DescriptionMember = "get_Description";
    private const string PersistReferenceMember = "GetPersistReference3";
    private const string EquationCountMember = "GetCount";
    private const string EquationTextMember = "get_Equation";
    private const string LengthUnitMember = "GetUnits";

    /// <summary><c>IFeatureManager.EditRollback(swMoveRollbackBarToEnd = 1, "")</c> (VERIFIED value).</summary>
    private const string RollbackKey = "IFeatureManager.EditRollback";

    private const string RebuildKey = "IModelDoc2.ForceRebuild3";

    private BridgeResponse Remodel(BridgeRequest request)
    {
        switch (request.Command)
        {
            case RemodelCommands.ProbeScope:
                return BridgeResponse.Ok(request.Id, ProbeScope(request));

            case RemodelCommands.Open:
                return BridgeResponse.Ok(request.Id, Open(request));

            case RemodelCommands.Snapshot:
                return BridgeResponse.Ok(request.Id, Snapshot(Session()));

            case RemodelCommands.Rename:
                return BridgeResponse.Ok(request.Id, Rename(request));

            case RemodelCommands.Reorder:
                return BridgeResponse.Ok(request.Id, Reorder(request));

            case RemodelCommands.Folder:
                return BridgeResponse.Ok(request.Id, Folder(request));

            case RemodelCommands.Describe:
                return BridgeResponse.Ok(request.Id, Describe(request));

            case RemodelCommands.Equation:
                return BridgeResponse.Ok(request.Id, EquationChange(request));

            case RemodelCommands.Rebuild:
                return BridgeResponse.Ok(request.Id, Rebuild(request));

            case RemodelCommands.Geometry:
                return BridgeResponse.Ok(request.Id, Geometry(Session()));

            case RemodelCommands.Save:
                return BridgeResponse.Ok(request.Id, Save(request));

            case RemodelCommands.Close:
                return BridgeResponse.Ok(request.Id, Close(request));

            default:
                // Every command in the table has a handler above. A thirteenth one added to
                // the table and not here answers with this rather than silently doing nothing.
                throw new RemodelCommandError(
                    RemodelErrorCodes.BadRequest,
                    $"'{request.Command}' is in the remodel command table but this build has no "
                    + "handler for it.");
        }
    }

    /// <summary>
    /// <c>remodel.probe_scope</c>. Reads the engineer's already-open source, opens nothing,
    /// returns no <c>IModelDoc2</c>, and mints a <c>probe_id</c> beside the canonicalized path.
    /// </summary>
    private RemodelProbeScopeResult ProbeScope(BridgeRequest request)
    {
        RemodelProbeScopeParams parameters = RemodelProbeScopeParams.Read(request);
        IRemodelSeat seat = Seat();

        ProbeRecord record = _probes.Probe(
            parameters.SourcePath, seat.ProbeSource, seat.GetVault(parameters.SourcePath));

        return new RemodelProbeScopeResult
        {
            ProbeId = record.ProbeId,
            SourcePath = record.SourcePath,
            ScopeSignals = record.Signals,
        };
    }

    /// <summary>
    /// <c>remodel.open</c>, in contracts/bridge-remodel.md's twelve numbered steps. The only
    /// command that creates a document handle, and it does so only after the copy exists on
    /// disk.
    ///
    /// Everything from the copy onwards is wrapped: a failure after the copy exists closes the
    /// document, deletes the copy and restores the system toggles, because the copy is the run
    /// and a run that did not start leaves nothing behind.
    /// </summary>
    private RemodelOpenResult Open(BridgeRequest request)
    {
        RemodelOpenParams parameters = RemodelOpenParams.Read(request);
        IRemodelSeat seat = Seat();

        if (_session != null)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.RunInProgress,
                "this bridge session already has a remodel run open. One run at a time: a "
                + "second would share the toggles, the gate and the circuit breaker with the "
                + "first.");
        }

        // 1. The probe happened, on this exact file, before anything is copied.
        ProbeRecord probe = _probes.Require(parameters.ProbeId, parameters.SourcePath);
        string source = probe.SourcePath;

        // 2 and 3. Re-read on the still-open source: the engineer may have edited it between
        // the probe and the run.
        RecheckSource(seat, source);

        // 4. The save target, before a byte is written. The run folder is the HOST's - see
        // BridgeServices.RemodelRunRoot - and never one derived from the request, or both of
        // this step's clauses would be satisfied by whatever path the client sent.
        string runDirectory = RunRoot();
        string copy = System.IO.Path.GetFullPath(parameters.CopyPath.Trim());
        string declaredRun = RemodelCopy.RunDirectoryOf(copy);

        if (!string.Equals(declaredRun, runDirectory, StringComparison.OrdinalIgnoreCase))
        {
            throw new MutatingCallError(
                "Save3",
                $"'{copy}' sits in the run folder '{declaredRun}', which is not this run's "
                + $"folder '{runDirectory}'. The copy lives in the folder the host made for "
                + "this run, and a copy_path may not choose a different one.");
        }

        RemodelScope.AssertSaveTarget(copy, copy, runDirectory, source);

        // 5. The attestation, recorded before the copy and re-checked at report time.
        VaultReference? vault = seat.GetVault(source);
        SourceAttestation attestation = RemodelCopy.RecordSource(
            source, copy, DateTime.UtcNow, vault?.Path, vault?.Revision);

        // 6. The four settings that would otherwise open a modal on the thread the run holds.
        // They are writes to the engineer's application-wide settings, so they go through the
        // same gate every other write does, under their own two allowlist keys.
        RemodelSystemToggles toggles = RemodelSystemToggles.Apply(seat, _remodelGate);

        bool copyCreated = false;
        IRemodelDocument? document = null;
        try
        {
            // 7. The bytewise copy, refusing to overwrite.
            RemodelCopy.CreateCopy(source, copy);
            copyCreated = true;

            // 8. Silent | LoadModel = 17 exactly, then the two-sided assertion.
            document = _remodelGate.Call(
                OpenDocMember, () => seat.OpenDocument(copy, RemodelCopy.OpenOptions));
            if (document == null)
            {
                throw new RemodelCopyError(
                    RemodelErrorCodes.OpenFailed,
                    $"SOLIDWORKS opened no document at '{copy}'.");
            }

            RemodelCopy.AssertOpenedAtCopy(document, copy, source);

            // 9. The tag, written before a scope can exist, because it is one of
            // VerifyTarget's four checks.
            IRemodelDocument tagged = document;
            _remodelGate.Call(TagMember, () => RemodelCopy.Tag(tagged, parameters.RunId));

            var scope = new RemodelScope(
                document, _remodelGate, parameters.RunId, copy, runDirectory);

            // 10. Roll the bar to the end, then assert nothing is still rolled back.
            scope.Write(RollbackKey, () => tagged.EditRollbackToEnd());

            IReadOnlyList<object> features = _remodelGate.Call(
                FeaturesMember, tagged.GetFeaturesInOrder);
            foreach (object feature in features)
            {
                if (_remodelGate.Call(IsRolledBackMember, () => tagged.IsRolledBack(feature)))
                {
                    throw new RemodelCopyError(
                        RemodelErrorCodes.OpenFailed,
                        "a feature still reports IsRolledBack() after EditRollback to the end, "
                        + "so the tree the run would measure is not the whole tree.");
                }
            }

            // 11. The one refusal that happens after a copy exists.
            scope.Write(RebuildKey, () => tagged.ForceRebuild(false));
            int rebuildErrors = _remodelGate.Call(
                WhatsWrongCountMember, tagged.GetWhatsWrongCount);
            if (rebuildErrors != 0)
            {
                throw new RemodelCommandError(
                    RemodelErrorCodes.PreexistingRebuildErrors,
                    $"the part already had {rebuildErrors} rebuild error(s) at baseline. Nothing "
                    + "after this point could be attributed to the run, so the run stops and the "
                    + "copy is deleted.");
            }

            // 12. The probe's rows, re-read on the copy, compared field for field.
            ScopeSignals signals = RemodelScopeProbe.ReadSignals(_remodelGate, tagged);
            IReadOnlyList<string> differences =
                RemodelScopeProbe.ModelSignalDifferences(probe.Signals, signals);
            if (differences.Count > 0)
            {
                throw new RemodelCommandError(
                    RemodelErrorCodes.ScopeChanged,
                    "the copy's scope signals differ from the probe's in "
                    + string.Join(", ", differences)
                    + ". The document being changed is not the one the verdict was reached on.");
            }

            signals.RebuildErrorCount = rebuildErrors;
            signals.SaveFlagDirty = _remodelGate.Call("GetSaveFlag", tagged.GetSaveFlag);

            var session = new RemodelSession(
                scope, document, _remodelGate, source, attestation, toggles)
            {
                Signals = signals,
                BaselineRebuildErrors = rebuildErrors,
                LengthUnit = _remodelGate.Call(LengthUnitMember, tagged.GetLengthUnit),
                Configurations = signals.ConfigurationNames ?? new string[0],
            };

            _session = session;

            return new RemodelOpenResult
            {
                DocumentPath = copy,
                Tag = parameters.RunId,
                FeatureCount = features.Count,
                ScopeSignals = signals,
                Configurations = session.Configurations,
                DocumentLengthUnit = session.LengthUnit,
                SourceAttestation = attestation,
            };
        }
        catch (Exception)
        {
            // The restore is in a finally, not after the rollback: CloseDocument is a COM call
            // and DeleteCopy a filesystem call, both on a path that is already failing, and a
            // throw from either would otherwise leave the engineer's four settings flipped
            // with nothing reporting it. Restore is idempotent, so the one in Close() stays
            // correct.
            try
            {
                if (document != null)
                {
                    // The same allowlisted write remodel.close makes, gated under the same key:
                    // this path runs after preexisting_rebuild_errors, scope_changed and the
                    // still-rolled-back refusal, which is where the audit record matters most.
                    // Call rather than Write, because the scope may not exist yet.
                    _remodelGate.Call(CloseKey, () => seat.CloseDocument(copy));
                }

                if (copyCreated)
                {
                    DeleteCopy(copy);
                }
            }
            finally
            {
                toggles.Restore();
            }

            throw;
        }
    }

    /// <summary>
    /// <c>remodel.open</c> steps 2 and 3, on the source SOLIDWORKS still has open. The source
    /// is read here and nowhere else in this command, and it is never opened.
    /// </summary>
    private void RecheckSource(IRemodelSeat seat, string source)
    {
        if (!System.IO.File.Exists(source))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.NotAPart, $"'{source}' no longer exists.");
        }

        IRemodelProbeSource reader = seat.ProbeSource;
        if (!_remodelGate.Call("GetOpenDocumentByName", () => reader.IsOpen(source)))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.SourceNotOpen,
                $"SOLIDWORKS no longer has '{source}' open, so its state cannot be re-read "
                + "before the copy is made.");
        }

        if (_remodelGate.Call("GetSaveFlag", reader.GetSaveFlag))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.SourceDirty,
                $"'{source}' has been edited since the probe and has unsaved changes.");
        }

        int externalReferences = _remodelGate.Call(
            "ListExternalFileReferencesCount2", reader.GetExternalReferenceCount);
        if (externalReferences != 0)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.ExternalRefs,
                $"'{source}' has {externalReferences} external file reference(s) now.");
        }
    }

    /// <summary>
    /// <c>remodel.snapshot</c>. Read-only, and the same shape before and after every change,
    /// so the executor diffs without a second vocabulary.
    ///
    /// <c>is_global</c> and <c>value</c> are left null on purpose. Globalness comes off
    /// <c>IEquationMgr.GlobalVariable</c>, which the snapshot does not read - feature 003's
    /// dump is where a package's equations get that flag - and whether <c>get_Value</c> answers
    /// in document units or metres is UNVERIFIED and blocking (PROBE-2). Unknown stays unknown.
    /// </summary>
    private RemodelSnapshotResult Snapshot(RemodelSession session)
    {
        IRemodelDocument document = session.Document;
        SwGate gate = session.Gate;

        IReadOnlyList<KeyValuePair<string, object>> tree = RefsInOrder(session);

        var order = new List<string>(tree.Count);
        var names = new Dictionary<string, string?>(StringComparer.Ordinal);
        var descriptions = new Dictionary<string, string?>(StringComparer.Ordinal);

        foreach (KeyValuePair<string, object> node in tree)
        {
            object feature = node.Value;
            order.Add(node.Key);
            names[node.Key] = gate.Call(
                RemodelSession.NameMember, () => document.GetFeatureName(feature));
            descriptions[node.Key] = gate.Call(
                DescriptionMember, () => document.GetFeatureDescription(feature));
        }

        string documentId = DocumentIds.DesignId(session.Scope.CopyPath);
        IEquationTarget equations = document.Equations;
        int count = gate.Call(EquationCountMember, equations.GetCount);
        var rows = new List<Equation>(Math.Max(count, 0));

        // A row whose text will not read cannot become an IR Equation - Equation.text is a
        // string, and "" would be a default written over engineering data - so its index is
        // named here instead. Dropping it silently would leave a snapshot that is quietly
        // shorter than the manager with nothing recording it, and the snapshot is what the
        // executor diffs before and after every change.
        var unreadable = new List<int>();
        for (int index = 0; index < count; index++)
        {
            int at = index;
            string? text = gate.Call(EquationTextMember, () => equations.GetEquation(at));
            if (text == null)
            {
                unreadable.Add(at);
                continue;
            }

            rows.Add(new Equation
            {
                DocumentId = documentId,
                Index = at,
                Text = text,
                Lhs = Equation.LhsOf(text),
                IsGlobal = null,
                Value = null,
            });
        }

        return new RemodelSnapshotResult
        {
            Order = order,
            Names = names,
            Descriptions = descriptions,
            Equations = rows,
            UnreadableEquationIndexes = unreadable,
            RebuildErrors = gate.Call(WhatsWrongCountMember, document.GetWhatsWrongCount),
            FeatureCount = tree.Count,
        };
    }

    // ---- the five mutating commands (T064) -------------------------------------------
    //
    // Every one of them resolves a persistent reference, reads the feature's name and calls
    // the name-based API in one breath, because the SOLIDWORKS members that do this work are
    // name-based and a name read at any other moment may no longer address the feature.

    /// <summary><c>swMoveLocation_e.Before</c> (VERIFIED value 2).</summary>
    private const int MoveBefore = 2;

    /// <summary><c>swMoveLocation_e.After</c> (VERIFIED value 3).</summary>
    private const int MoveAfter = 3;

    /// <summary><c>swFeatureTreeFolder_e.swFeatureTreeFolder_Containing</c> (VERIFIED value 2).</summary>
    private const int ContainingFolder = 2;

    /// <summary>The type name a feature folder reports on 2024 SP5 (VERIFIED).</summary>
    private const string FolderTypeName = "FtrFolder";

    private const string NameKey = "IFeature.set_Name";
    private const string DescriptionKey = "IFeature.set_Description";
    private const string SelectKey = "IFeature.Select2";
    private const string ClearSelectionKey = "IModelDoc2.ClearSelection2";
    private const string ReorderKey = "IModelDocExtension.ReorderFeature";
    private const string InsertFolderKey = "IFeatureManager.InsertFeatureTreeFolder2";
    private const string DeleteEquationKey = "IEquationMgr.Delete";
    private const string TypeNameMember = "GetTypeName2";
    private const string FolderLocationMember = "FeatureFolderLocation";
    private const string EquationCountRead = "GetCount";
    private const string EquationTextRead = "get_Equation";

    /// <summary>
    /// <c>remodel.rename</c>. Two uses and no others: repairing a duplicate feature name
    /// before any reorder, and naming a folder the run just created. There is no dimension
    /// form (FR-030).
    /// </summary>
    private RemodelRenameResult Rename(BridgeRequest request)
    {
        RemodelRenameParams parameters = RemodelRenameParams.Read(request);
        RemodelSession session = Session();

        ResolvedFeature target = session.Resolve(parameters.PersistRef);
        session.Scope.Write(
            NameKey, () => session.Document.SetFeatureName(target.Feature, parameters.NewName));

        return new RemodelRenameResult
        {
            PreviousName = target.Name,
            NewName = parameters.NewName,
        };
    }

    /// <summary>
    /// <c>remodel.reorder</c>. The only move operation in stage 1.
    ///
    /// A <c>false</c> return is a <b>contract violation</b>, not a retry: legality was decided
    /// from the dependency graph before the call, so <c>false</c> means the model of the tree
    /// is wrong. The run stops and the copy is discarded; it never retries and never searches
    /// for a legal position.
    /// </summary>
    private RemodelReorderResult Reorder(BridgeRequest request)
    {
        RemodelReorderParams parameters = RemodelReorderParams.Read(request);
        RemodelSession session = Session();

        // The tree walk comes first, and the whole of it: it is one GetFeaturesInOrder plus one
        // GetPersistReference3 per feature, and a walk between the name reads and the move is
        // exactly the gap in which a name stops addressing the feature it was read for.
        IReadOnlyList<KeyValuePair<string, object>> before = RefsInOrder(session);
        int previousIndex = IndexOf(before, parameters.FeaturePersistRef);

        // The inverse, read from the tree rather than assumed: the feature goes back after the
        // one it used to follow, or before the one it used to precede when it was first.
        string? previousAnchor = null;
        string? previousLocation = null;
        if (previousIndex > 0)
        {
            previousAnchor = before[previousIndex - 1].Key;
            previousLocation = RemodelReorderLocations.After;
        }
        else if (before.Count > 1)
        {
            previousAnchor = before[1].Key;
            previousLocation = RemodelReorderLocations.Before;
        }

        int location = string.Equals(
            parameters.Location, RemodelReorderLocations.Before, StringComparison.Ordinal)
            ? MoveBefore
            : MoveAfter;

        // Both refs resolved, both names read and the name-based call made in one breath: the
        // only thing between them is VerifyTarget, which reads no name.
        ResolvedFeature feature = session.Resolve(parameters.FeaturePersistRef);
        ResolvedFeature anchor = session.Resolve(parameters.AnchorPersistRef);

        bool moved = session.Scope.Write(
            ReorderKey,
            () => session.Document.ReorderFeature(feature.Name, anchor.Name, location));

        if (!moved)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.ReorderRefused,
                $"ReorderFeature('{feature.Name}', '{anchor.Name}', {location}) answered false. "
                + "Legality was decided from the dependency graph before the call, so this is a "
                + "contract violation: the run stops rather than retrying or searching for a "
                + "position SOLIDWORKS would accept.");
        }

        return new RemodelReorderResult
        {
            PreviousAnchorPersistRef = previousAnchor,
            PreviousLocation = previousLocation,
            PreviousIndex = previousIndex,
            NewIndex = IndexOf(RefsInOrder(session), parameters.FeaturePersistRef),
        };
    }

    /// <summary>
    /// <c>remodel.folder</c>: <c>create</c> and <c>rename</c> in v1, and <c>dissolve</c>
    /// refused with <c>not_in_v1</c>.
    ///
    /// A <c>create</c> wraps a run of features that is already contiguous - the planner proves
    /// it and this handler re-checks it, because a non-contiguous request is a contract
    /// violation rather than something to attempt - and then <b>verifies</b> the membership
    /// with <c>FeatureFolderLocation</c> rather than assuming it from the selection. The
    /// result carries the <b>verified</b> membership, so a caller that asked for four members
    /// and is answered with three has a failed change to record; a folder that did not appear
    /// at all answers with a null <c>folder_persist_ref</c>, which is the same reading. Folder
    /// creation has no in-place inverse in v1 (a dissolve needs <c>IModelDoc2.EditDelete</c>,
    /// which is not allowlisted), so a failed one ends the run.
    /// </summary>
    private RemodelFolderResult Folder(BridgeRequest request)
    {
        RemodelFolderParams parameters = RemodelFolderParams.Read(request);

        if (string.Equals(parameters.Op, RemodelFolderOps.Dissolve, StringComparison.Ordinal))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.NotInV1,
                "remodel.folder op 'dissolve' is reserved for stage 2. IModelDoc2.EditDelete is "
                + "not on the stage-1 allowlist, and a part carrying an RMS-named folder whose "
                + "members differ from the plan is refused by the scope gate before anything is "
                + "copied.");
        }

        RemodelSession session = Session();

        return string.Equals(parameters.Op, RemodelFolderOps.Rename, StringComparison.Ordinal)
            ? RenameFolder(session, parameters)
            : CreateFolder(session, parameters);
    }

    private RemodelFolderResult RenameFolder(RemodelSession session, RemodelFolderParams parameters)
    {
        if (string.IsNullOrWhiteSpace(parameters.FolderPersistRef))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                "remodel.folder op 'rename' needs \"params.folder_persist_ref\".");
        }

        string name = RequiredFolderName(parameters);
        ResolvedFeature folder = session.Resolve(parameters.FolderPersistRef!);

        // The folder is identified by its type name, never by its name: the ___EndTag___
        // marker keeps the folder's default name after a rename (PROBE-10), so a name is not
        // evidence of what a feature is.
        string? typeName = session.Gate.Call(
            TypeNameMember, () => session.Document.GetFeatureTypeName(folder.Feature));
        if (!string.Equals(typeName, FolderTypeName, StringComparison.Ordinal))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                $"'{parameters.FolderPersistRef}' is a '{typeName}' and not a {FolderTypeName}, "
                + "so it is not a folder to rename.");
        }

        session.Scope.Write(
            NameKey, () => session.Document.SetFeatureName(folder.Feature, name));

        return new RemodelFolderResult
        {
            FolderPersistRef = parameters.FolderPersistRef,
            Name = name,

            // A rename does not touch membership, so it reports none: the membership a caller
            // can rely on is the one a create verified.
            MemberPersistRefs = new string[0],
        };
    }

    private RemodelFolderResult CreateFolder(RemodelSession session, RemodelFolderParams parameters)
    {
        string name = RequiredFolderName(parameters);
        IReadOnlyList<string> requested = parameters.MemberPersistRefs;

        if (requested.Count == 0)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.FolderMembersNotContiguous,
                "remodel.folder op 'create' needs at least one member; an empty folder wraps "
                + "nothing and has no place in the plan.");
        }

        IReadOnlyList<KeyValuePair<string, object>> order = RefsInOrder(session);
        var indices = new List<int>(requested.Count);
        foreach (string persistRef in requested)
        {
            int at = IndexOf(order, persistRef);
            if (at < 0)
            {
                throw new RemodelCommandError(
                    RemodelErrorCodes.PersistRefUnresolved,
                    $"'{persistRef}' is not in the copy's feature tree, so it cannot be a member "
                    + "of a folder.");
            }

            indices.Add(at);
        }

        for (int i = 1; i < indices.Count; i++)
        {
            if (indices[i] != indices[i - 1] + 1)
            {
                throw new RemodelCommandError(
                    RemodelErrorCodes.FolderMembersNotContiguous,
                    "the requested members are not a contiguous run in the current tree order "
                    + $"(positions {string.Join(", ", indices)}). The planner proves contiguity "
                    + "before the request is made, so this is a contract violation rather than "
                    + "something to attempt.");
            }
        }

        session.Scope.Write(ClearSelectionKey, session.Document.ClearSelection);

        for (int i = 0; i < indices.Count; i++)
        {
            object member = order[indices[i]].Value;
            bool append = i > 0;
            session.Scope.Write(SelectKey, () => session.Document.SelectFeature(member, append, 0));
        }

        object? folder = session.Scope.Write(
            InsertFolderKey, () => session.Document.InsertFeatureTreeFolder(ContainingFolder));

        if (folder == null)
        {
            // No folder appeared. The reading is reported rather than guessed at: folder
            // creation has no inverse in v1, so the executor ends the run on this answer.
            return new RemodelFolderResult
            {
                FolderPersistRef = null,
                Name = null,
                MemberPersistRefs = new string[0],
            };
        }

        object created = folder;
        session.Scope.Write(NameKey, () => session.Document.SetFeatureName(created, name));

        string? folderRef = session.Gate.Call(
            PersistReferenceMember, () => session.Document.GetPersistReference(created));

        return new RemodelFolderResult
        {
            FolderPersistRef = folderRef,
            Name = name,
            MemberPersistRefs = VerifiedMembers(session, order, indices, folderRef),
        };
    }

    /// <summary>
    /// <c>IFeatureManager.FeatureFolderLocation(Feature)</c> for every member, compared by
    /// persistent reference rather than by object identity, because a COM pointer is not an
    /// identity and a name is not either.
    /// </summary>
    private static IReadOnlyList<string> VerifiedMembers(
        RemodelSession session,
        IReadOnlyList<KeyValuePair<string, object>> order,
        IReadOnlyList<int> indices,
        string? folderRef)
    {
        var verified = new List<string>(indices.Count);
        if (string.IsNullOrEmpty(folderRef))
        {
            return verified;
        }

        foreach (int at in indices)
        {
            object member = order[at].Value;
            object? holder = session.Gate.Call(
                FolderLocationMember, () => session.Document.GetFeatureFolder(member));
            if (holder == null)
            {
                continue;
            }

            string? holderRef = session.Gate.Call(
                PersistReferenceMember, () => session.Document.GetPersistReference(holder));
            if (string.Equals(holderRef, folderRef, StringComparison.Ordinal))
            {
                verified.Add(order[at].Key);
            }
        }

        return verified;
    }

    private static string RequiredFolderName(RemodelFolderParams parameters)
    {
        if (string.IsNullOrWhiteSpace(parameters.Name))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                $"remodel.folder op '{parameters.Op}' needs a non-empty \"params.name\".");
        }

        return parameters.Name!.Trim();
    }

    /// <summary>
    /// <c>remodel.describe</c>. The previous text is <b>read before</b> the write, because it
    /// is the inverse and the command never guesses it.
    ///
    /// A description that reads back as null is unreadable, which is not the same as
    /// <c>""</c> (absent). The change is refused rather than applied: an inverse that writes
    /// <c>""</c> over something unreadable is a silent edit, and the constitution's re-modeler
    /// exception requires an inverse for every applied change. The planner refuses such a
    /// feature up front, so a request for one is a bug in the caller.
    /// </summary>
    private RemodelDescribeResult Describe(BridgeRequest request)
    {
        RemodelDescribeParams parameters = RemodelDescribeParams.Read(request);
        RemodelSession session = Session();

        ResolvedFeature target = session.Resolve(parameters.PersistRef);
        string? previous = session.Gate.Call(
            DescriptionMember, () => session.Document.GetFeatureDescription(target.Feature));

        if (previous == null)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                $"the description of '{parameters.PersistRef}' could not be read, so writing one "
                + "would leave a change with no inverse. The planner refuses a feature whose "
                + "description is unreadable before the run starts.");
        }

        session.Scope.Write(
            DescriptionKey,
            () => session.Document.SetFeatureDescription(target.Feature, parameters.Text));

        return new RemodelDescribeResult { PreviousText = previous };
    }

    /// <summary>
    /// <c>remodel.equation</c>. <c>add</c> and <c>set</c> go through the two verified helpers
    /// and nothing else; <c>delete</c> is only ever the inverse of an add this run made, is
    /// issued in reverse order of addition, and never removes a global the part already had.
    /// </summary>
    private RemodelEquationResult EquationChange(BridgeRequest request)
    {
        RemodelEquationParams parameters = RemodelEquationParams.Read(request);
        RemodelSession session = Session();
        IEquationTarget equations = session.Document.Equations;

        switch (parameters.Op)
        {
            case RemodelEquationOps.Add:
                return RemodelEquations.AddEquationVerified(
                    session.Scope,
                    session.Gate,
                    equations,
                    parameters.Index ?? -1,
                    RequiredEquationText(parameters),
                    parameters.WhichConfigs,
                    null);

            case RemodelEquationOps.Set:
                return RemodelEquations.SetEquationVerified(
                    session.Scope,
                    session.Gate,
                    equations,
                    RequiredEquationIndex(parameters),
                    RequiredEquationText(parameters),
                    parameters.WhichConfigs,
                    null);

            default:
                return DeleteEquation(session, equations, RequiredEquationIndex(parameters));
        }
    }

    /// <summary>
    /// The inverse of an <c>add</c>, with the same kind of evidence the add helper demands:
    /// the row is read before it goes, and the count is read after it, so a delete that
    /// removed nothing - or removed more than one row - is a failed change rather than a
    /// silent one.
    /// </summary>
    private static RemodelEquationResult DeleteEquation(
        RemodelSession session, IEquationTarget equations, int index)
    {
        string? previous = session.Gate.Call(
            EquationTextRead, () => equations.GetEquation(index));
        if (previous == null)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.EquationUnverified,
                $"equation {index} could not be read before the delete, so there is nothing to "
                + "record as having been removed.");
        }

        int before = session.Gate.Call(EquationCountRead, equations.GetCount);
        session.Scope.Write(DeleteEquationKey, () => equations.Delete(index));
        int after = session.Gate.Call(EquationCountRead, equations.GetCount);

        if (after != before - 1)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.EquationUnverified,
                $"deleting equation {index} took the count from {before} to {after}, which is "
                + "not one row removed.");
        }

        return new RemodelEquationResult
        {
            Index = index,
            CountBefore = before,
            CountAfter = after,
            PreviousText = previous,
            RoundTripText = null,
            HelperPath = RemodelEquationHelperPaths.Delete,
        };
    }

    private static string RequiredEquationText(RemodelEquationParams parameters)
    {
        if (string.IsNullOrWhiteSpace(parameters.Text))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                $"remodel.equation op '{parameters.Op}' needs a non-empty \"params.text\".");
        }

        return parameters.Text!;
    }

    private static int RequiredEquationIndex(RemodelEquationParams parameters)
    {
        if (parameters.Index == null)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                $"remodel.equation op '{parameters.Op}' needs \"params.index\".");
        }

        return parameters.Index.Value;
    }

    /// <summary>
    /// The feature tree as (persistent reference, feature) pairs, in tree order. One walk, so
    /// a command that needs positions - a reorder's indices, a folder's contiguity - reads the
    /// tree once rather than once per member.
    ///
    /// A feature with no persistent reference cannot be addressed at all, and a plan made
    /// against a tree that is quietly shorter than it looks would move the wrong features, so
    /// it is named here rather than dropped.
    /// </summary>
    private static IReadOnlyList<KeyValuePair<string, object>> RefsInOrder(RemodelSession session)
    {
        IReadOnlyList<object> features = session.Gate.Call(
            FeaturesMember, session.Document.GetFeaturesInOrder);

        var order = new List<KeyValuePair<string, object>>(features.Count);
        foreach (object feature in features)
        {
            string? persistRef = session.Gate.Call(
                PersistReferenceMember, () => session.Document.GetPersistReference(feature));
            if (string.IsNullOrEmpty(persistRef))
            {
                throw new RemodelCommandError(
                    RemodelErrorCodes.PersistRefUnresolved,
                    "a feature in the copy has no persistent reference, so it cannot be "
                    + "addressed and no plan may be made against this tree.");
            }

            order.Add(new KeyValuePair<string, object>(persistRef!, feature));
        }

        return order;
    }

    private static int IndexOf(
        IReadOnlyList<KeyValuePair<string, object>> order, string persistRef)
    {
        for (int i = 0; i < order.Count; i++)
        {
            if (string.Equals(order[i].Key, persistRef, StringComparison.Ordinal))
            {
                return i;
            }
        }

        return -1;
    }

    // ---- rebuild, save and close (T066) ----------------------------------------------

    private const string SaveKey = "IModelDoc2.Save3";
    private const string CloseKey = "ISldWorks.CloseDoc";
    private const string ErrorCodeMember = "GetErrorCode2";
    private const string WhatsWrongMember = "GetWhatsWrong";
    private const string SaveFlagMember = "GetSaveFlag";

    /// <summary>
    /// <c>remodel.rebuild</c>. <c>IModelDoc2.ForceRebuild3(force)</c> and then the error
    /// reading: one <c>IFeature.GetErrorCode2</c> per feature, which is the <b>primary</b>
    /// reading and the one the verify phase reads, with <c>GetWhatsWrong</c> carried beside it
    /// as corroboration only. Every feature gets a row, including the ones that are fine, so
    /// "every feature reports swFeatureErrorNone" is a statement a reader can check rather than
    /// an absence they have to trust.
    ///
    /// <c>IModelDoc2.EditRebuild3</c> is not allowlisted: one rebuild call, one meaning.
    /// </summary>
    private RemodelRebuildResult Rebuild(BridgeRequest request)
    {
        RemodelRebuildParams parameters = RemodelRebuildParams.Read(request);
        RemodelSession session = Session();
        IRemodelDocument document = session.Document;

        var clock = Stopwatch.StartNew();
        session.Scope.Write(RebuildKey, () => document.ForceRebuild(parameters.Force));
        clock.Stop();

        int rebuildErrors = session.Gate.Call(
            WhatsWrongCountMember, document.GetWhatsWrongCount);
        IReadOnlyList<string> whatsWrong = session.Gate.Call(
            WhatsWrongMember, document.GetWhatsWrong);

        var featureErrors = new List<RemodelFeatureError>();
        foreach (KeyValuePair<string, object> node in RefsInOrder(session))
        {
            object feature = node.Value;
            bool isWarning = false;
            int code = session.Gate.Call(
                ErrorCodeMember, () => document.GetFeatureErrorCode(feature, out isWarning));

            featureErrors.Add(new RemodelFeatureError
            {
                PersistRef = node.Key,
                Name = session.Gate.Call(
                    RemodelSession.NameMember, () => document.GetFeatureName(feature)),
                ErrorCode = code,
                IsWarning = isWarning,
            });
        }

        return new RemodelRebuildResult
        {
            RebuildErrors = rebuildErrors,
            WhatsWrong = whatsWrong,
            ElapsedMs = clock.ElapsedMilliseconds,
            FeatureErrors = featureErrors,
        };
    }

    /// <summary>
    /// <c>remodel.geometry</c> (T095). It takes no parameters because there is nothing to
    /// name: the scope's copy is the only document this run can reach, and the gate compares
    /// that copy against itself.
    ///
    /// The <c>subject</c> is stamped here, from the run's own phase - the first reading of a run
    /// is the baseline, taken after the open rollback and rebuild and before the first change,
    /// and every later one is the after - so the caller cannot ask for a reading of anything
    /// else. The source is never opened for the comparison, in any mode (FR-037); the baseline
    /// stands for it because the copy is a byte-for-byte <c>File.Copy</c> whose SHA-256 was
    /// recorded before any document handle existed, and the reading carries that hash.
    ///
    /// The measurement is <see cref="RemodelGeometry.Read"/>'s and the verdict is Python's.
    /// </summary>
    private GeometryReading Geometry(RemodelSession session)
    {
        string subject = session.BaselineGeometryTaken
            ? RemodelGeometrySubjects.CopyAtEnd
            : RemodelGeometrySubjects.CopyAtOpen;
        session.GeometryReadings++;

        return RemodelGeometry.Read(
            session.Gate,
            session.Document,
            subject,
            session.Attestation.Sha256,
            DateTime.UtcNow);
    }

    /// <summary>
    /// <c>remodel.save</c>. <c>IModelDoc2.Save3(swSaveAsOptions_Silent = 1, out errors, out
    /// warnings)</c>, which takes <b>no filename</b> (VERIFIED) - the structural reason it
    /// cannot reach the source - behind <c>AssertSaveTarget</c>, which is run anyway because
    /// the property is checked rather than merely argued.
    ///
    /// Three ways this fails, and all three are failures of the <b>run</b>:
    /// a non-zero <c>errors</c>; a <c>swFileSaveWarning_RebuildError</c> warning, which leaves
    /// a saved artifact and is reported as exactly that rather than as success; and a
    /// <c>GetSaveFlag()</c> that is still set afterwards, because a document SOLIDWORKS still
    /// considers dirty was not saved whatever <c>Save3</c> answered.
    ///
    /// Before any of that, the gate: <c>gate_not_passed</c> unless the geometry gate has
    /// returned <c>pass</c> for this run. Two things have to be true, and a refusal names both
    /// that failed - the verdict the runner reports is <c>pass</c>, and this host actually took
    /// the two readings a verdict is reached from, so a caller cannot claim a gate that never
    /// ran. The verdict is reported rather than computed because the measurement is the
    /// bridge's and the decision is Python's (contracts/bridge-remodel.md).
    /// </summary>
    private RemodelSaveResult Save(BridgeRequest request)
    {
        RemodelSaveParams parameters = RemodelSaveParams.Read(request);
        RemodelSession session = Session();
        RemodelScope scope = session.Scope;

        if (!string.Equals(parameters.Verdict, RemodelGateVerdicts.Pass, StringComparison.Ordinal)
            || session.GeometryReadings < RemodelGateVerdicts.ReadingsAVerdictNeeds)
        {
            var reasons = new List<string>();
            if (!string.Equals(parameters.Verdict, RemodelGateVerdicts.Pass, StringComparison.Ordinal))
            {
                reasons.Add($"the reported geometry verdict is '{parameters.Verdict}'");
            }

            if (session.GeometryReadings < RemodelGateVerdicts.ReadingsAVerdictNeeds)
            {
                reasons.Add(
                    $"this run took {session.GeometryReadings} geometry reading(s) and a verdict "
                    + $"is reached from {RemodelGateVerdicts.ReadingsAVerdictNeeds}");
            }

            throw new RemodelCommandError(
                RemodelErrorCodes.GateNotPassed,
                "the copy is not saved: " + string.Join(", and ", reasons)
                + ". Save3 runs only after the geometry comparison has passed "
                + "(.specify/memory/constitution.md, the mutation exception).",
                new Dictionary<string, string>(StringComparer.Ordinal)
                {
                    { "verdict", parameters.Verdict },
                    {
                        "geometry_readings",
                        session.GeometryReadings.ToString(CultureInfo.InvariantCulture)
                    },
                });
        }

        RemodelScope.AssertSaveTarget(
            scope.CopyPath, scope.CopyPath, scope.RunDirectory, session.SourcePath);

        IRemodelDocument document = session.Document;
        int errors = 0;
        int warnings = 0;
        scope.Write(SaveKey, () => document.Save(RemodelCopy.SaveOptions, out errors, out warnings));

        bool saveFlag = session.Gate.Call(SaveFlagMember, document.GetSaveFlag);

        if (errors != 0)
        {
            throw Failed(
                scope.CopyPath,
                errors,
                warnings,
                saveFlag,
                $"Save3 answered error {errors} for '{scope.CopyPath}'.",
                saved: false);
        }

        if ((warnings & RemodelCopy.SaveWarningRebuildError) != 0)
        {
            throw Failed(
                scope.CopyPath,
                errors,
                warnings,
                saveFlag,
                $"'{scope.CopyPath}' was saved with a rebuild error warning "
                + $"(swFileSaveWarning_RebuildError, warnings = {warnings}). The artifact is on "
                + "disk and the run failed; this is not a success.",
                saved: true);
        }

        if (saveFlag)
        {
            throw Failed(
                scope.CopyPath,
                errors,
                warnings,
                saveFlag,
                $"'{scope.CopyPath}' still reports GetSaveFlag() after the save, so SOLIDWORKS "
                + "still considers it dirty and the file on disk is not what was measured.",
                saved: false);
        }

        return new RemodelSaveResult
        {
            Path = scope.CopyPath,
            Errors = errors,
            Warnings = warnings,
            SaveFlagAfter = saveFlag,
        };
    }

    private static RemodelCommandError Failed(
        string path, int errors, int warnings, bool saveFlag, string message, bool saved) =>
        new RemodelCommandError(
            RemodelErrorCodes.SaveFailed,
            message,
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                { "path", path },
                { "errors", errors.ToString(CultureInfo.InvariantCulture) },
                { "warnings", warnings.ToString(CultureInfo.InvariantCulture) },
                { "save_flag_after", saveFlag ? "true" : "false" },

                // Whether the engineer has a file to look at. A failed run that left an
                // artifact and one that left nothing are different situations.
                { "saved", saved ? "true" : "false" },
            });

    /// <summary>
    /// <c>remodel.close</c>. Closes the tagged copy - the target is verified first, so the
    /// close cannot land on a document that became something else - and with
    /// <c>discard_copy</c> deletes the copy and <b>nothing else</b>.
    ///
    /// Discard keeps every other artifact. Deleting the run folder would lose the evidence
    /// Principle VI asks for, and "what did it propose?" has to stay answerable after the
    /// engineer says no.
    ///
    /// The system toggles are restored here, and <see cref="RemodelSystemToggles.Restore"/> is
    /// idempotent, so a host that also restores them in its own <c>finally</c> does not write
    /// the engineer's settings twice.
    /// </summary>
    private RemodelCloseResult Close(BridgeRequest request)
    {
        RemodelCloseParams parameters = RemodelCloseParams.Read(request);
        RemodelSession session = Session();
        IRemodelSeat seat = Seat();
        string copy = session.Scope.CopyPath;

        // The close-out pair, behind one verification. The tag is VerifyTarget's own check 2,
        // so the run cannot verify again between removing it and closing: the removal is the
        // last thing the session does to the document and the close is the next. The saved
        // file keeps the tag it was saved with - Save3 runs before this and the run saves once
        // - so this removes the tag from the open document, not from the artifact on disk.
        session.Scope.VerifyTarget();
        session.Gate.Call(UntagKey, () => RemodelCopy.Untag(session.Document));
        session.Gate.Call(CloseKey, () => seat.CloseDocument(copy));

        bool deleted = false;
        if (parameters.DiscardCopy)
        {
            DeleteCopy(copy);
            deleted = !System.IO.File.Exists(copy);
        }

        // A restore that could not put every setting back raises, and the run still ends: the
        // document is already closed, so leaving the session open would let a later command
        // address a document that is gone.
        try
        {
            session.Toggles.Restore();
        }
        finally
        {
            _session = null;
        }

        return new RemodelCloseResult { Closed = true, CopyDeleted = deleted };
    }

    /// <summary>
    /// This run's folder as the host set it, canonicalized, or the refusal a bridge built
    /// without one answers with. It is never taken from a request: see
    /// <see cref="BridgeServices.RemodelRunRoot"/>.
    /// </summary>
    private string RunRoot()
    {
        string? root = _services.RemodelRunRoot;
        if (string.IsNullOrWhiteSpace(root))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.TargetMismatch,
                "this bridge was not built with a remodel run folder, so there is nowhere a "
                + "copy may be created. The run folder is the host's and is never taken from "
                + "the request.");
        }

        return System.IO.Path.GetFullPath(root!.Trim())
            .TrimEnd(System.IO.Path.DirectorySeparatorChar);
    }

    /// <summary>The seat, or the refusal a bridge built without one answers with.</summary>
    private IRemodelSeat Seat() =>
        _services.RemodelSeat ?? throw new RemodelCommandError(
            RemodelErrorCodes.TargetMismatch,
            "this bridge was not built with a remodel seat, so no remodel command can reach "
            + "SOLIDWORKS.");

    /// <summary>
    /// The run, or the refusal every command after <c>remodel.open</c> answers with when there
    /// is no run. It is reported as <c>target_mismatch</c> - the degenerate case of
    /// <c>VerifyTarget</c>, where there is no target at all - because the caller is a client
    /// that skipped <c>remodel.open</c>, and that is a bug in the caller rather than a
    /// condition of the part.
    /// </summary>
    private RemodelSession Session() =>
        _session ?? throw new RemodelCommandError(
            RemodelErrorCodes.TargetMismatch,
            "remodel.open has not returned in this bridge session, so there is no copy for this "
            + "command to act on.");

    /// <summary>
    /// Deletes the copy on a refusal that happens after it exists. A copy that will not delete
    /// is reported through the refusal that is already on its way up, never swallowed and never
    /// turned into a different error: the caller needs the reason the run stopped.
    /// </summary>
    private static void DeleteCopy(string copy)
    {
        try
        {
            if (System.IO.File.Exists(copy))
            {
                System.IO.File.Delete(copy);
            }
        }
        catch (Exception error) when (error is System.IO.IOException
            || error is UnauthorizedAccessException)
        {
            // Left on disk. The refusal that brought us here is the answer the caller gets.
        }
    }

    /// <summary>
    /// <c>component_ids</c> to work units: none is the whole assembly, two is that pair, and
    /// more than two is every unordered pair among them. An id this document does not have
    /// is refused by name rather than quietly dropped - dropping it would report "no
    /// interference" for a component that was never checked.
    /// </summary>
    private List<InterferencePair> Pairs(IReadOnlyList<string> componentIds)
    {
        var pairs = new List<InterferencePair>();
        if (componentIds.Count == 0)
        {
            pairs.Add(InterferencePair.WholeAssembly());
            return pairs;
        }

        if (componentIds.Count == 1)
        {
            throw new ArgumentException(
                "\"component_ids\" needs either none (the whole assembly) or at least two "
                + "components; one component cannot interfere with nothing.");
        }

        var components = new List<InterferenceComponent>(componentIds.Count);
        foreach (string id in componentIds)
        {
            InterferenceComponent? component = _services.Components.ById(id);
            if (component == null)
            {
                throw new ArgumentException(
                    $"'{id}' is not a component of the document this bridge is attached to "
                    + $"({_services.DocumentPath ?? "unknown"}).");
            }

            components.Add(component);
        }

        for (int i = 0; i < components.Count; i++)
        {
            for (int j = i + 1; j < components.Count; j++)
            {
                pairs.Add(InterferencePair.Of(components[i], components[j]));
            }
        }

        return pairs;
    }

    private static InterferenceRunSettings ReadSettings(BridgeRequest request)
    {
        var settings = new InterferenceRunSettings();
        JsonElement element;
        if (!TryGetMember(request, "settings", out element) || element.ValueKind != JsonValueKind.Object)
        {
            return settings;
        }

        settings.TreatCoincidentAsInterference =
            Flag(element, "treat_coincident_as_interference", settings.TreatCoincidentAsInterference);
        settings.TreatSubassembliesAsComponents =
            Flag(element, "treat_subassemblies_as_components", settings.TreatSubassembliesAsComponents);
        settings.IncludeMultibody = Flag(element, "include_multibody", settings.IncludeMultibody);
        settings.IgnoreHidden = Flag(element, "ignore_hidden", settings.IgnoreHidden);

        JsonElement treatment;
        if (element.TryGetProperty("fastener_folder_treatment", out treatment)
            && treatment.ValueKind == JsonValueKind.String)
        {
            settings.Fasteners = InterferenceRunSettings.ParseFastenerTreatment(treatment.GetString());
        }

        return settings;
    }

    private static bool Flag(JsonElement settings, string name, bool fallback)
    {
        JsonElement value;
        if (!settings.TryGetProperty(name, out value))
        {
            return fallback;
        }

        switch (value.ValueKind)
        {
            case JsonValueKind.True:
                return true;
            case JsonValueKind.False:
                return false;
            default:
                throw new ArgumentException($"\"settings.{name}\" must be true or false.");
        }
    }

    private static bool TryGetMember(BridgeRequest request, string name, out JsonElement value)
    {
        value = default(JsonElement);
        if (request.Params.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        return request.Params.TryGetProperty(name, out value);
    }

    private static string RequiredString(BridgeRequest request, string name)
    {
        string? value = OptionalString(request, name);
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new BridgeProtocolError(
                $"'{request.Command}' needs a non-empty \"params.{name}\".");
        }

        return value!;
    }

    private static string? OptionalString(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGetMember(request, name, out value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        return value.GetString();
    }

    private static int? OptionalInt(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGetMember(request, name, out value) || value.ValueKind != JsonValueKind.Number)
        {
            return null;
        }

        int parsed;
        return value.TryGetInt32(out parsed) ? parsed : (int?)null;
    }

    private static IReadOnlyList<string> StringArray(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGetMember(request, name, out value) || value.ValueKind != JsonValueKind.Array)
        {
            return new string[0];
        }

        var items = new List<string>();
        foreach (JsonElement item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String)
            {
                throw new BridgeProtocolError($"\"params.{name}\" must hold strings.");
            }

            string? text = item.GetString();
            if (!string.IsNullOrWhiteSpace(text))
            {
                items.Add(text!);
            }
        }

        return items;
    }
}
