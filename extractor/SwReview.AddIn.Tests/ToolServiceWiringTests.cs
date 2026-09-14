using System;
using System.Collections.Generic;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.ToolService;
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
            DocumentPath = @"C:\models\bracket-" + ordinal + ".sldasm";
            Session = new FakeSession();
        }

        public string PipeName { get; }

        public string DocumentPath { get; }

        public BridgeConfig ReviewBridge { get; }

        public BridgeConfig GeneralChatBridge { get; }

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
