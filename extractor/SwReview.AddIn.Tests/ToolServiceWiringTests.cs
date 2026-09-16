using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.ToolService;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T048: the add-in's side of the tool service - when it starts, what each of its two secrets
/// is handed to, and what happens to it on disconnect.
///
/// None of this can be tested through <c>SwReviewAddIn</c> itself: every path in that class
/// needs a live <c>ISldWorks</c>. So the decisions live in <see cref="ToolServiceGate"/>, which
/// takes the three things the add-in actually supplies - "is a document open", "start one", and
/// "here is the one that started" - as delegates, and the add-in is left with the lines that
/// name them. What is pinned here is what an engineer would notice if it were wrong:
///
/// - <b>Nothing starts before the first document.</b> The Task Pane exists from add-in load and
///   SOLIDWORKS usually loads with no document open; <c>SwScope.Open</c> walks a component tree
///   and has nothing to walk. So the pane asks again on every `ActiveDocChangeNotify`, and the
///   answer has to stay "not yet" until there is something to attach to.
/// - <b>One service, not one per document change.</b> `ToolService 1 per add-in instance`
///   (data-model.md). A second host would be a second pipe, a second scope and a second pair of
///   secrets, and the review that is running would keep talking to the first.
/// - <b>The two secrets go to different places and are not the same string.</b> The review
///   secret reaches `POST /sessions`; the general-chat secret reaches the CLI profile the
///   terminal writes. They are what bounds the general-chat command scope
///   (contracts/README.md), so one secret used for both would authenticate without bounding.
/// - <b>The start runs off the application thread.</b> <c>ToolServiceHost.Start</c> marshals the
///   attach onto the application thread and waits for it; calling it *from* that thread - which
///   is where `ConnectToSW` and the document-changed event both run - would deadlock SOLIDWORKS
///   until the attach timeout expired.
/// - <b>Disconnect stops it</b>, and a host that finishes starting after the add-in has already
///   unloaded is disposed rather than published, because the alternative is a pipe listening
///   into a SOLIDWORKS that no longer has an add-in.
/// </summary>
public sealed class ToolServiceWiringTests
{
    // ---- when it starts --------------------------------------------------------------------

    [Fact]
    public void NoToolServiceIsStartedUntilADocumentIsOpen()
    {
        var world = new GateWorld { DocumentOpen = false };
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();

        Assert.Equal(0, world.Starts);
        Assert.Null(gate.GeneralChatBridge);
        Assert.Null(gate.DocumentPath);
        Assert.Null(gate.Session);
        Assert.Null(world.Published);
    }

    [Fact]
    public void TheFirstDocumentStartsExactlyOneToolService()
    {
        var world = new GateWorld { DocumentOpen = false };
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();
        Assert.Equal(0, world.Starts);

        // The engineer opens an assembly: ActiveDocChangeNotify asks again.
        world.DocumentOpen = true;
        gate.EnsureStarted();
        Assert.Equal(1, world.Starts);

        // And keeps switching documents. One add-in instance, one tool service.
        gate.EnsureStarted();
        gate.EnsureStarted();
        Assert.Equal(1, world.Starts);

        // And the backend was handed that one host's bridge, once.
        Assert.Same(world.Services[0].ReviewBridge, world.Published);
    }

    // ---- where each secret goes ------------------------------------------------------------

    [Fact]
    public void TheReviewSecretGoesToTheBackendAndTheGeneralChatSecretToTheTerminal()
    {
        var world = new GateWorld();
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();

        FakeToolService service = world.Services[0];

        // What POST /sessions is given as `bridge`.
        Assert.NotNull(world.Published);
        Assert.Equal(service.PipeName, world.Published!.Pipe);
        Assert.Equal(service.ReviewBridge.Secret, world.Published.Secret);

        // What the CLI profile writer is given, through the accessor the terminal branch calls.
        IToolServiceAccess access = gate;
        Assert.NotNull(access.GeneralChatBridge);
        Assert.Equal(service.PipeName, access.GeneralChatBridge!.Pipe);
        Assert.Equal(service.GeneralChatBridge.Secret, access.GeneralChatBridge.Secret);
        Assert.Equal(service.DocumentPath, access.DocumentPath);

        // One pipe, two scopes. A single secret would authenticate without bounding what it
        // authorizes, and the CLI can read its own generated profile.
        Assert.NotEqual(world.Published.Secret, access.GeneralChatBridge.Secret);
    }

    /// <summary>
    /// T134e. The Remodel tab's pipeline is handed a third half, and it is a third secret:
    /// `remodel.*` authorizes every write the run makes to the copy, so it is neither the review
    /// secret nor the one the CLI profile carries. Null before the service is listening, which
    /// is what makes the pane refuse a run rather than start one it cannot execute.
    /// </summary>
    [Fact]
    public void TheRemodelBridgeIsAThirdSecretAndIsNullBeforeTheServiceIsListening()
    {
        var world = new GateWorld();
        ToolServiceGate gate = world.Gate();
        Assert.Null(gate.RemodelBridge);

        gate.EnsureStarted();

        FakeToolService service = world.Services[0];
        Assert.NotNull(gate.RemodelBridge);
        Assert.Equal(service.PipeName, gate.RemodelBridge!.Pipe);
        Assert.Equal(service.RemodelBridge.Secret, gate.RemodelBridge.Secret);
        Assert.NotEqual(service.ReviewBridge.Secret, gate.RemodelBridge.Secret);
        Assert.NotEqual(service.GeneralChatBridge.Secret, gate.RemodelBridge.Secret);
    }

    [Fact]
    public void TheReviewBridgeIsWhatTheReviewHostPassesToPostSessions()
    {
        var options = new ReviewHostOptions(
            new SilentChannel(), new UnusedBackend(), UserSettings.DefaultPath);
        Assert.Null(options.Bridge);

        var world = new GateWorld();
        world.Publish = service => options.Bridge = service.ReviewBridge;
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();

        Assert.NotNull(options.Bridge);
        Assert.Equal(world.Services[0].PipeName, options.Bridge!.Pipe);
        Assert.Equal(world.Services[0].ReviewBridge.Secret, options.Bridge.Secret);
    }

    // ---- entity.show ------------------------------------------------------------------------

    [Fact]
    public void EntityShowSeesTheToolServiceScopeOnceItIsListening()
    {
        var world = new GateWorld { DocumentOpen = false };
        ToolServiceGate gate = world.Gate();

        // Before the tool service exists the resolver has to fall back to its own attach; the
        // gate says so by answering null rather than by throwing.
        gate.EnsureStarted();
        Assert.Null(gate.Session);

        world.DocumentOpen = true;
        gate.EnsureStarted();

        // The same scope the bridge's capture, measure and interference commands run against,
        // rather than a second SwSession.Attach per Show.
        Assert.Same(world.Services[0].Session, gate.Session);
    }

    // ---- failure ----------------------------------------------------------------------------

    [Fact]
    public void AStartThatFailsIsReportedAndTriedAgainOnTheNextDocument()
    {
        var world = new GateWorld();
        world.Failure = new InvalidOperationException("the component tree could not be walked");
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();

        Assert.Null(gate.GeneralChatBridge);
        Assert.Null(world.Published);
        string report = Assert.Single(world.Reports);
        Assert.Contains("tool service", report, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("the component tree could not be walked", report);

        // A failed attach is not terminal: the engineer opens a document that can be walked.
        world.Failure = null;
        gate.EnsureStarted();

        Assert.NotNull(gate.GeneralChatBridge);
        Assert.Single(world.Reports);
    }

    // ---- disconnect -------------------------------------------------------------------------

    [Fact]
    public void DisconnectStopsTheToolServiceAndTheAccessorGoesQuiet()
    {
        var world = new GateWorld();
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        FakeToolService service = world.Services[0];
        Assert.False(service.Disposed);

        gate.Dispose();

        Assert.True(service.Disposed);
        Assert.Null(gate.GeneralChatBridge);
        Assert.Null(gate.Session);
        Assert.Null(gate.DocumentPath);

        // DisconnectFromSW runs inside a SOLIDWORKS callback: a second stop, or a document
        // change that arrives during unload, must not throw out of it.
        gate.Dispose();
        gate.EnsureStarted();
        Assert.Equal(1, world.Starts);
    }

    [Fact]
    public void AToolServiceThatArrivesAfterDisposeIsDisposedRatherThanPublished()
    {
        var world = new GateWorld();

        // The add-in unloads while the attach is still on the application thread.
        Action? pending = null;
        var gate = world.Gate(schedule: work => pending = work);

        gate.EnsureStarted();
        gate.Dispose();
        pending!();

        FakeToolService service = world.Services[0];
        Assert.True(service.Disposed);
        Assert.Null(world.Published);
        Assert.Null(gate.GeneralChatBridge);
    }

    // ---- the thread it starts on -------------------------------------------------------------

    [Fact]
    public void TheStartRunsOffTheCallingThread()
    {
        var done = new ManualResetEventSlim();
        int caller = Thread.CurrentThread.ManagedThreadId;
        int starter = caller;

        var world = new GateWorld();
        world.OnStart = () =>
        {
            starter = Thread.CurrentThread.ManagedThreadId;
            done.Set();
        };

        // Null schedule: the gate's own, which is the one SwReviewAddIn gets. The add-in calls
        // EnsureStarted from the application thread, and ToolServiceHost.Start marshals its
        // attach onto that same thread and waits for it, so starting inline would deadlock
        // SOLIDWORKS until the attach timeout expired.
        ToolServiceGate gate = world.Gate(schedule: null);
        gate.EnsureStarted();

        Assert.True(done.Wait(TimeSpan.FromSeconds(10)), "the tool service start never ran.");
        Assert.NotEqual(caller, starter);
        gate.Dispose();
    }

    // ---- the remodel gate observer (T057) -----------------------------------------------------

    /// <summary>This run's copy, as <c>RemodelScope.CopyPath</c> canonicalizes it.</summary>
    private const string CopyPath =
        @"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT";

    /// <summary>The per-launch secret a remodel request carries, and that no line may repeat.</summary>
    private const string RemodelRequestSecret = "remodel-secret-0123456789";

    /// <summary>The reads a mutating remodel request makes before it writes anything.</summary>
    private static readonly string[] RemodelReads =
    {
        "GetObjectByPersistReference3",
        "get_Name",
        "GetWhatsWrongCount",
    };

    /// <summary>
    /// The writes, as interface-qualified keys. Five of the six needed the stage-1 allowlist to
    /// pass: <c>InsertFeatureTreeFolder2</c> through <see cref="ReadOnlyGuard"/>'s
    /// <c>InsertFeature</c> prefix, and <c>EditRollback</c>, <c>ForceRebuild3</c>,
    /// <c>Delete2</c> and <c>Save3</c> by name.
    /// </summary>
    private static readonly string[] RemodelWrites =
    {
        "IFeature.set_Name",
        "IFeatureManager.InsertFeatureTreeFolder2",
        "IFeatureManager.EditRollback",
        "IModelDoc2.ForceRebuild3",
        "ICustomPropertyManager.Delete2",
        "IModelDoc2.Save3",
    };

    /// <summary>
    /// The SC-004 audit, extended to the re-modeler (contracts/guard-allowlist.md).
    ///
    /// The assertion is <b>not</b> "every gated key is allowlisted". <c>SwGate.Guard</c> calls
    /// <c>observer.Gated</c> for every member <i>before</i> the guard judges it, so a mutating
    /// remodel request gates its reads too and the log records strings with no read/write
    /// classification in them. What is checkable, and what this asserts, is the intersection:
    /// every gated key that <see cref="ReadOnlyGuard"/> would have denied - every key that
    /// needed the allowlist to pass - is on the stage-1 allowlist.
    /// </summary>
    [Fact]
    public void EveryGatedKeyThatNeededTheAllowlistToPassIsOnTheStageOneAllowlist()
    {
        string line = RemodelLine(RemodelReads, RemodelWrites);
        string[] needed = GatedOf(line).Where(NeededTheAllowlist).ToArray();

        Assert.Equal(
            new[]
            {
                "IFeatureManager.InsertFeatureTreeFolder2",
                "IFeatureManager.EditRollback",
                "IModelDoc2.ForceRebuild3",
                "ICustomPropertyManager.Delete2",
                "IModelDoc2.Save3",
            },
            needed);

        foreach (string key in needed)
        {
            Assert.Contains(key, RemodelGuard.AllowedKeys);
        }

        // Nothing was refused: a refusal here is the re-modeler reaching for a member stage 1
        // does not have.
        Assert.DoesNotContain("refused=", line, StringComparison.Ordinal);
    }

    /// <summary>
    /// The weaker property, pinned deliberately so a later change cannot tighten the assertion
    /// above into one the log cannot support: the gated set holds reads that are on no
    /// allowlist, because the gate records what was asked about rather than what was allowed.
    /// </summary>
    [Fact]
    public void TheGatedSetHoldsReadsThatAreOnNoAllowlist()
    {
        string[] gated = GatedOf(RemodelLine(RemodelReads, RemodelWrites));

        foreach (string read in RemodelReads)
        {
            Assert.Contains(read, gated);
            Assert.DoesNotContain(read, RemodelGuard.AllowedKeys);
            Assert.False(NeededTheAllowlist(read));
        }
    }

    /// <summary>
    /// FR-041: the run report states from the log, rather than from intent, that every write
    /// went to the copy. So the target is recorded per mutating call, and a request whose
    /// writes all went to one document records exactly that one path.
    /// </summary>
    [Fact]
    public void EveryMutatingCallRecordsTheTargetPathItWroteTo()
    {
        string line = RemodelLine(RemodelReads, RemodelWrites);

        Assert.Contains(" target=" + CopyPath, line, StringComparison.Ordinal);
        Assert.Equal(1, Occurrences(line, CopyPath));
        Assert.DoesNotContain(RemodelGateRecorder.NoTarget, line, StringComparison.Ordinal);
    }

    [Fact]
    public void AReadOnlyRemodelRequestRecordsNoTargetPathAtAll()
    {
        // remodel.probe_scope reads the engineer's open source and writes nothing, so there is
        // no target to record - and an empty target field would read like one.
        string line = RemodelLine(RemodelReads, new string[0]);

        Assert.DoesNotContain(" target=", line, StringComparison.Ordinal);
    }

    [Fact]
    public void AWriteMadeBeforeTheRunHasAScopeRecordsNoTargetRatherThanAGuessedOne()
    {
        // The three user-preference toggles and the modal-suppression flag are set by
        // remodel.open before any scope exists, and they name no document. Unknown stays
        // unknown: the line says so rather than naming a copy that does not exist yet.
        string line = RemodelLine(
            new string[0], new[] { "ISldWorks.SetUserPreferenceToggle" }, target: null);

        Assert.Contains(" target=" + RemodelGateRecorder.NoTarget, line, StringComparison.Ordinal);
    }

    [Fact]
    public void AKeyOffTheStageOneAllowlistIsRefusedAndRecordedWithNoTarget()
    {
        // IModelDoc2.EditDelete is the owner's decision made visible in the audit artifact: v1
        // refuses a mis-membered RMS-named folder rather than dissolving it, so the one call
        // that deletes real features on a mis-selection is not on the list.
        string line = RemodelLine(new string[0], new[] { "IModelDoc2.EditDelete" });

        Assert.Contains("refused=IModelDoc2.EditDelete", line, StringComparison.Ordinal);
        Assert.Contains("gated=IModelDoc2.EditDelete", line, StringComparison.Ordinal);
        Assert.DoesNotContain(" target=", line, StringComparison.Ordinal);
    }

    [Fact]
    public void TheSecretNeverReachesTheLine()
    {
        Assert.DoesNotContain(
            RemodelRequestSecret, RemodelLine(RemodelReads, RemodelWrites), StringComparison.Ordinal);
    }

    // ---- remodel.log (T070) ---------------------------------------------------------------------

    [Fact]
    public void EveryRemodelRequestGetsOneRedactedLineInTheRunFoldersRemodelLog()
    {
        using (var run = new TempRunFolder())
        {
            var service = new LoggedService(run.Path);

            service.Dispatch(RemodelCommands.Rename, RemodelReads, RemodelWrites);

            string written = File.ReadAllText(run.RemodelLogPath);
            Assert.Equal(1, Occurrences(written, "\n"));
            Assert.Contains("command=" + RemodelCommands.Rename, written, StringComparison.Ordinal);
            Assert.Contains("elapsed_ms=", written, StringComparison.Ordinal);
            Assert.Contains("gated=", written, StringComparison.Ordinal);
            Assert.Contains(" target=" + CopyPath, written, StringComparison.Ordinal);
            Assert.DoesNotContain(RemodelRequestSecret, written, StringComparison.Ordinal);

            // The tool-service log is the SC-004 artifact and keeps its own copy of the line.
            Assert.Contains(
                "command=" + RemodelCommands.Rename, service.ToolServiceLog, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void ARequestThatIsNotARemodelCommandNeverReachesTheRemodelLog()
    {
        using (var run = new TempRunFolder())
        {
            var service = new LoggedService(run.Path);

            service.Dispatch(BridgeCommands.Capture, new[] { "ShowNamedView2" }, new string[0]);

            Assert.False(File.Exists(run.RemodelLogPath));
            Assert.Contains("command=capture", service.ToolServiceLog, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void ARemodelRequestMadeBeforeARunFolderExistsWritesNoFileAndStillLogs()
    {
        // remodel.probe_scope runs before remodel.open has built a scope, so there is no run
        // folder to write into yet. The tool-service log still records the request.
        var service = new LoggedService(runDirectory: null);

        service.Dispatch(RemodelCommands.ProbeScope, RemodelReads, new string[0]);

        Assert.Contains(
            "command=" + RemodelCommands.ProbeScope, service.ToolServiceLog, StringComparison.Ordinal);
    }

    // ---- the remodel observer's helpers ---------------------------------------------------------

    /// <summary>
    /// One formatted log line for a remodel request that gated <paramref name="reads"/> as bare
    /// names and <paramref name="writes"/> as interface-qualified keys, through a real
    /// <see cref="SwGate"/> built with the real <see cref="RemodelGuard"/>.
    /// </summary>
    private static string RemodelLine(string[] reads, string[] writes, string? target = CopyPath)
    {
        var recorder = new SwGateRecorder();
        var gate = new SwGate(new CircuitBreaker(), new RemodelGuard())
        {
            Observer = new RemodelGateRecorder(recorder, () => target),
        };

        Gate(gate, reads, writes);

        BridgeRequest request = BridgeCodec.ReadRequest(
            "{\"id\":\"11\",\"command\":\"" + RemodelCommands.Rename
            + "\",\"secret\":\"" + RemodelRequestSecret + "\"}");

        return ToolServiceRequestLogger.Format(
            DateTimeOffset.Parse("2026-09-16T14:22:01+00:00", CultureInfo.InvariantCulture),
            request,
            BridgeResponse.Ok(request.Id, null),
            recorder.Drain());
    }

    /// <summary>The calls one request makes, a refusal left in the record rather than thrown on.</summary>
    private static void Gate(SwGate gate, string[] reads, string[] writes)
    {
        foreach (string member in reads)
        {
            gate.Call(member, () => 0);
        }

        foreach (string key in writes)
        {
            try
            {
                gate.Call(key, () => 0);
            }
            catch (MutatingCallError)
            {
                // The refusal is the answer the caller gets; the audit wants it in the line.
            }
        }
    }

    /// <summary>The <c>gated=</c> field of a line, split back into keys.</summary>
    private static string[] GatedOf(string line)
    {
        string field = line.Split(' ').Single(
            part => part.StartsWith("gated=", StringComparison.Ordinal));
        string value = field.Substring("gated=".Length);
        return value.Length == 0 ? new string[0] : value.Split(',');
    }

    /// <summary>
    /// True when <see cref="ReadOnlyGuard"/> would have refused this key's bare member name, so
    /// only the stage-1 allowlist can have let it through.
    /// </summary>
    private static bool NeededTheAllowlist(string gatedKey)
    {
        string member = CallKey.BareName(gatedKey);
        return ReadOnlyGuard.DeniedMembers.Contains(member, StringComparer.OrdinalIgnoreCase)
            || ReadOnlyGuard.DeniedPrefixes.Any(
                prefix => member.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
    }

    private static int Occurrences(string text, string value)
    {
        int count = 0;
        for (int at = text.IndexOf(value, StringComparison.Ordinal);
            at >= 0;
            at = text.IndexOf(value, at + value.Length, StringComparison.Ordinal))
        {
            count++;
        }

        return count;
    }

    /// <summary>A run folder on disk, the way the host has one once `remodel.open` has returned.</summary>
    private sealed class TempRunFolder : IDisposable
    {
        public TempRunFolder()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(), "swreview-remodel-log", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public string RemodelLogPath => System.IO.Path.Combine(Path, RemodelRunLog.FileName);

        public void Dispose()
        {
            if (Directory.Exists(Path))
            {
                Directory.Delete(Path, recursive: true);
            }
        }
    }

    /// <summary>
    /// The logging chain as <see cref="ToolServiceHost"/> composes it: one recorder, the remodel
    /// gate's observer on top of it, the tool-service log, and `remodel.log` in the open run's
    /// folder.
    /// </summary>
    private sealed class LoggedService
    {
        private readonly StringWriter _log = new StringWriter();
        private readonly SwGateRecorder _recorder = new SwGateRecorder();
        private readonly AnsweringDispatcher _dispatcher = new AnsweringDispatcher();
        private readonly SwGate _gate;
        private readonly ToolServiceRequestLogger _logger;

        public LoggedService(string? runDirectory)
        {
            _gate = new SwGate(new CircuitBreaker(), new RemodelGuard())
            {
                Observer = new RemodelGateRecorder(_recorder, () => CopyPath),
            };

            _logger = new ToolServiceRequestLogger(
                _dispatcher,
                _recorder,
                _log.Write,
                remodelLog: new RemodelRunLog(() => runDirectory).Write);
        }

        public string ToolServiceLog => _log.ToString();

        public void Dispatch(string command, string[] reads, string[] writes)
        {
            // Inside the dispatch, where a handler's calls happen: the logger drains first, so
            // anything the gate saw between requests belongs to no request.
            _dispatcher.Work = () => Gate(_gate, reads, writes);

            _logger.Dispatch(BridgeCodec.ReadRequest(
                "{\"id\":\"11\",\"command\":\"" + command
                + "\",\"secret\":\"" + RemodelRequestSecret + "\"}"));
        }
    }

    /// <summary>Answers every request `ok`; what it did to SOLIDWORKS is the gate's story.</summary>
    private sealed class AnsweringDispatcher : IBridgeDispatcher
    {
        /// <summary>The interop calls this request makes, run on the way through.</summary>
        public Action? Work { get; set; }

        public BridgeResponse Dispatch(BridgeRequest request)
        {
            Work?.Invoke();
            return BridgeResponse.Ok(request.Id, null);
        }
    }

    // ---- fakes ---------------------------------------------------------------------------------

    /// <summary>The three delegates <see cref="SwReviewAddIn"/> supplies, and what they saw.</summary>
    private sealed class GateWorld
    {
        private int _next;

        public bool DocumentOpen { get; set; } = true;

        /// <summary>Set to make the next start throw, as a failed attach would.</summary>
        public Exception? Failure { get; set; }

        /// <summary>Runs inside the start delegate, on whichever thread it was scheduled onto.</summary>
        public Action? OnStart { get; set; }

        /// <summary>What the add-in does with a started service; the default records it.</summary>
        public Action<IToolService>? Publish { get; set; }

        public List<FakeToolService> Services { get; } = new List<FakeToolService>();

        public List<string> Reports { get; } = new List<string>();

        public BridgeConfig? Published { get; private set; }

        public int Starts => Services.Count;

        /// <summary>A gate that starts inline, so an assertion can follow the call.</summary>
        public ToolServiceGate Gate() => Gate(work => work());

        /// <summary>Null means the gate's own schedule - the one the add-in gets.</summary>
        public ToolServiceGate Gate(Action<Action>? schedule) => new ToolServiceGate(
            () => DocumentOpen,
            Start,
            service =>
            {
                if (Publish != null)
                {
                    Publish(service);
                    return;
                }

                Published = service.ReviewBridge;
            },
            (what, failure) => Reports.Add(what + " " + failure.Message),
            schedule);

        private IToolService Start()
        {
            OnStart?.Invoke();

            if (Failure != null)
            {
                throw Failure;
            }

            var service = new FakeToolService(++_next);
            Services.Add(service);
            return service;
        }
    }

    /// <summary>A tool service with no pipe, no SOLIDWORKS and two distinct secrets.</summary>
    private sealed class FakeToolService : IToolService
    {
        public FakeToolService(int ordinal)
        {
            PipeName = "swreview-fake-" + ordinal;
            ReviewBridge = new BridgeConfig(PipeName, "review-secret-" + ordinal);
            GeneralChatBridge = new BridgeConfig(PipeName, "chat-secret-" + ordinal);
            RemodelBridge = new BridgeConfig(PipeName, "remodel-secret-" + ordinal);
            DocumentPath = @"C:\models\bracket-" + ordinal + ".sldasm";
            Session = new FakeSession();
        }

        public string PipeName { get; }

        public string DocumentPath { get; }

        public BridgeConfig ReviewBridge { get; }

        public BridgeConfig GeneralChatBridge { get; }

        public BridgeConfig RemodelBridge { get; }

        public ISwSession Session { get; }

        public bool Disposed { get; private set; }

        public void Dispose() => Disposed = true;
    }

    /// <summary>Identity only: the tests assert which scope `entity.show` was handed, never
    /// what it did with it. Touching a member would need SOLIDWORKS.</summary>
    private sealed class FakeSession : ISwSession
    {
        public IModelDoc2 Document => throw new NotSupportedException("no SOLIDWORKS in a test.");

        public IConfiguration Configuration =>
            throw new NotSupportedException("no SOLIDWORKS in a test.");

        public string? SwVersion => null;

        public SwGate Gate { get; } = new SwGate();
    }

    /// <summary>The page is not part of this wiring; the options object is.</summary>
    private sealed class SilentChannel : IPageChannel
    {
        public void PostMessage(string json)
        {
        }
    }

    /// <summary>Never called: the test asserts what the host would *carry* to the backend.</summary>
    private sealed class UnusedBackend : IBackendClient
    {
        public BackendEndpoint? Endpoint => null;

        public IReadOnlyList<ModelChoice> ListModels(string provider) => throw new NotSupportedException();

        public bool IsTurnRunning(string chatId) => throw new NotSupportedException();

        public ChatSessionHandle CreateSession(NewSessionRequest request) => throw new NotSupportedException();

        public void Restart(UserSettings settings, ResolvedApiKey key) => throw new NotSupportedException();
    }
}
