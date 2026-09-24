using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.ToolService;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Measure;
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
        world.Publish = service => options.Bridge = service?.ReviewBridge;
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();

        Assert.NotNull(options.Bridge);
        Assert.Equal(world.Services[0].PipeName, options.Bridge!.Pipe);
        Assert.Equal(world.Services[0].ReviewBridge.Secret, options.Bridge.Secret);
    }

    /// <summary>
    /// And what it passes once that service is gone: nothing. The bridge is published on a
    /// successful start and cleared on every stop, because `POST /sessions` carrying a pipe that
    /// has been closed hands the backend a bridge whose every command fails one at a time -
    /// where a null bridge makes the Python side fall back to its own attach, which works.
    /// </summary>
    [Fact]
    public void AStoppedToolServiceTakesItsBridgeOutOfTheReviewHostsOptions()
    {
        var options = new ReviewHostOptions(
            new SilentChannel(), new UnusedBackend(), UserSettings.DefaultPath);

        var world = new GateWorld();
        world.Publish = service => options.Bridge = service?.ReviewBridge;
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();
        Assert.NotNull(options.Bridge);

        gate.Dispose();

        Assert.Null(options.Bridge);
    }

    /// <summary>
    /// The same rule on the path that makes it matter. A document change takes the running
    /// service down before it attaches the new one, so a restart whose attach fails must leave
    /// no bridge behind either: the next review would otherwise be handed the dead pipe.
    /// </summary>
    [Fact]
    public void ARestartWhoseAttachFailsLeavesNoBridgePublished()
    {
        var options = new ReviewHostOptions(
            new SilentChannel(), new UnusedBackend(), UserSettings.DefaultPath);

        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        world.Publish = service => options.Bridge = service?.ReviewBridge;
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();
        Assert.NotNull(options.Bridge);

        world.Failure = new InvalidOperationException("the component tree could not be walked");
        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.True(world.Services[0].Disposed);
        Assert.Null(options.Bridge);
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

    // ---- following the active document (docs/pane-findings-2026-09-16.md, finding 1) ---------

    /// <summary>
    /// The finding: the service bound to whichever document was open when the add-in started,
    /// the engineer switched to another part, and every bridge command afterwards asked about a
    /// document that no longer exists. <c>EnsureStarted</c> cannot fix it - it is a no-op once a
    /// service exists, and deliberately so - hence a second entry point.
    /// </summary>
    [Fact]
    public void AChangeToAnotherDocumentReattachesTheToolServiceToIt()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        FakeToolService first = world.Services[0];
        Assert.Equal(@"C:\models\deck.SLDASM", gate.DocumentPath);

        // The engineer opens a different part. EnsureStarted alone leaves the bridge attached
        // to the assembly, which is the whole of the finding.
        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.EnsureStarted();
        Assert.Equal(1, world.Starts);

        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.Equal(2, world.Starts);
        Assert.True(first.Disposed);
        Assert.Equal(@"C:\models\bracket.SLDPRT", gate.DocumentPath);

        // Re-pointed by the same callback the first start used: the secret `POST /sessions`
        // carries belongs to the service that is listening now, not to the disposed one.
        Assert.Equal(world.Services[1].ReviewBridge.Secret, world.Published!.Secret);
        Assert.Equal(world.Services[1].RemodelBridge.Secret, gate.RemodelBridge!.Secret);

        // Once followed, it stays followed: the next ActiveDocChangeNotify restarts nothing.
        gate.FollowDocument(@"C:\models\bracket.SLDPRT");
        Assert.Equal(2, world.Starts);
    }

    /// <summary>
    /// SOLIDWORKS is not asked to spell the path the same way twice, and Windows does not care
    /// about case. A restart per document change would be a new pipe, a new scope and a new
    /// pair of secrets for nothing.
    /// </summary>
    [Fact]
    public void TheSameDocumentSpeltDifferentlyDoesNotRestartAnything()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        gate.FollowDocument(@"C:\models\deck.SLDASM");
        gate.FollowDocument(@"c:\MODELS\DECK.sldasm");
        gate.FollowDocument(@"C:\models\sub\..\deck.SLDASM");

        Assert.Equal(1, world.Starts);
        Assert.False(world.Services[0].Disposed);
    }

    /// <summary>
    /// A review turn or a remodel run is holding the bridge. Disposing the service underneath
    /// it would fail the work in flight, so the gate does not - and says so where the engineer
    /// reading the tool-service log will find it, naming both documents.
    /// </summary>
    [Fact]
    public void ABusyBridgeIsNotRestartedAndTheLogSaysWhyNamingBothDocuments()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM", Busy = true };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.Equal(1, world.Starts);
        Assert.False(world.Services[0].Disposed);
        Assert.Equal(@"C:\models\deck.SLDASM", gate.DocumentPath);

        string line = Assert.Single(world.Services[0].LogLines);
        Assert.Contains("not re-attaching", line, StringComparison.Ordinal);
        Assert.Contains(@"C:\models\bracket.SLDPRT", line, StringComparison.Ordinal);
        Assert.Contains(@"C:\models\deck.SLDASM", line, StringComparison.Ordinal);

        // The turn ends. The next ActiveDocChangeNotify - or the next tab switch - follows it.
        world.Busy = false;
        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.Equal(2, world.Starts);
        Assert.Equal(@"C:\models\bracket.SLDPRT", gate.DocumentPath);
    }

    /// <summary>
    /// A busy predicate that throws - <c>AnyTurnRunning</c> asks the backend over HTTP - is
    /// read as busy. Tearing down a service on an unanswered question is the one outcome that
    /// cannot be undone.
    /// </summary>
    [Fact]
    public void ABusyPredicateThatThrowsIsTreatedAsBusyAndReported()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        world.BusyFailure = new InvalidOperationException("the backend did not answer");
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.Equal(1, world.Starts);
        Assert.False(world.Services[0].Disposed);
        Assert.Contains("the backend did not answer", Assert.Single(world.Reports));
    }

    /// <summary>
    /// Closing the last document is not a reason to drop the service: the engineer reopens one,
    /// and a service attached to a document that is gone still answers `document no longer
    /// open` with that document's name, which is the message finding 1 asked for.
    /// </summary>
    [Fact]
    public void NothingOpenLeavesTheAttachedServiceAlone()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        gate.FollowDocument(null);
        gate.FollowDocument(string.Empty);
        gate.FollowDocument("   ");

        Assert.Equal(1, world.Starts);
        Assert.False(world.Services[0].Disposed);
        Assert.NotNull(gate.GeneralChatBridge);
        Assert.Equal(@"C:\models\deck.SLDASM", gate.DocumentPath);
    }

    [Fact]
    public void FollowDocumentStartsNothingBeforeTheFirstService()
    {
        var world = new GateWorld { DocumentOpen = false };
        ToolServiceGate gate = world.Gate();

        // Starting is EnsureStarted's job, and it has its own rule about when it may.
        gate.FollowDocument(@"C:\models\deck.SLDASM");

        Assert.Equal(0, world.Starts);
        Assert.Null(gate.GeneralChatBridge);
    }

    [Fact]
    public void DisposeDuringAPendingRestartStartsNothingAndStopsWhatWasThere()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        Action? pending = null;
        ToolServiceGate gate = world.Gate(schedule: work => pending = work);

        gate.EnsureStarted();
        pending!();
        pending = null;
        FakeToolService first = world.Services[0];

        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        // Nothing has happened on the caller's thread: the busy question, the teardown and the
        // start are all inside the scheduled work, because the caller is the application thread.
        Assert.False(first.Disposed);
        Assert.NotNull(pending);

        gate.Dispose();
        pending!();

        // The add-in unloaded before the re-attach ran, so nothing new is started: a pipe
        // listening into a SOLIDWORKS with no add-in is worse than no tool service at all. The
        // service the engineer had is stopped by Dispose itself.
        Assert.True(first.Disposed);
        Assert.Equal(1, world.Starts);
        Assert.Null(gate.GeneralChatBridge);

        // ...and the bridge it had published goes down with it, rather than outliving the pipe
        // it names.
        Assert.Null(world.Published);
    }

    /// <summary>
    /// Between the teardown and the new service listening the gate answers null, which is what
    /// makes the Remodel tab refuse a run rather than start one against a pipe that is closing.
    /// Captured rather than asserted inside the start delegate: an exception thrown there is a
    /// failed start, which is not what a broken assertion should look like.
    /// </summary>
    [Fact]
    public void MidRestartTheGateAnswersNullRatherThanNamingAClosingPipe()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();
        FakeToolService first = world.Services[0];

        bool stoppedFirst = false;
        BridgeConfig? remodelMidway = null;
        string? documentMidway = null;
        world.OnStart = () =>
        {
            stoppedFirst = first.Disposed;
            remodelMidway = gate.RemodelBridge;
            documentMidway = gate.DocumentPath;
        };

        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.Equal(2, world.Starts);
        Assert.True(stoppedFirst);
        Assert.Null(remodelMidway);
        Assert.Null(documentMidway);
    }

    [Fact]
    public void ARestartWhoseAttachFailsIsReportedAndTheNextDocumentTriesAgain()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        world.Failure = new InvalidOperationException("the component tree could not be walked");
        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.True(world.Services[0].Disposed);
        Assert.Null(gate.GeneralChatBridge);
        Assert.Contains(
            "the component tree could not be walked",
            Assert.Single(world.Reports));

        // A failed attach is not terminal, and EnsureStarted is no longer a no-op: the gate is
        // empty, so the next ActiveDocChangeNotify starts one against the document it names.
        world.Failure = null;
        gate.EnsureStarted();

        Assert.Equal(@"C:\models\bracket.SLDPRT", gate.DocumentPath);
    }

    // ---- drawings ------------------------------------------------------------------------------

    /// <summary>
    /// The repro: SOLIDWORKS was loaded with a drawing active, the gate saw a document and
    /// started an attach, and <c>SwSession.Attach</c> threw - every drawing answers null to
    /// <c>ConfigurationManager.ActiveConfiguration</c>, and a session is bound to one. The
    /// failure went into addin.log as "The SwReview tool service did not start." and the service
    /// stayed null, which turns off the bridge, the terminal's tools and the Remodel tab for the
    /// whole session.
    ///
    /// So a drawing is not a document this may attach to, and the next part is.
    /// </summary>
    [Fact]
    public void ADrawingStartsNothingAndTheFirstModelAfterItStartsExactlyOne()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\sheet.SLDDRW" };
        ToolServiceGate gate = world.Gate();

        gate.EnsureStarted();

        Assert.Equal(0, world.Starts);
        Assert.Empty(world.Services);
        Assert.Null(world.Published);
        Assert.Null(gate.GeneralChatBridge);
        Assert.Null(gate.DocumentPath);

        // The engineer opens the part the drawing documents. Nothing was spent on the drawing,
        // so this is an ordinary first start.
        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.EnsureStarted();

        Assert.Equal(1, world.Starts);
        Assert.Equal(@"C:\models\bracket.SLDPRT", gate.DocumentPath);
        Assert.Same(world.Services[0].ReviewBridge, world.Published);
    }

    [Fact]
    public void ADrawingThatIsSkippedSaysSoWhereTheEngineerWillSeeIt()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\sheet.SLDDRW" };

        world.Gate().EnsureStarted();

        // Through the seam a failed start already uses - the actions panel and addin.log -
        // because a pane whose tools are all off must not be off silently, and the refusal is
        // the one line that says which document caused it and what to open instead.
        string report = Assert.Single(world.Reports);
        Assert.Contains(@"C:\models\sheet.SLDDRW", report, StringComparison.Ordinal);
        Assert.Contains("drawing", report, StringComparison.Ordinal);
        Assert.Contains("part or assembly", report, StringComparison.Ordinal);
    }

    /// <summary>
    /// The worse half of the same bug: <see cref="ToolServiceGate.FollowDocument"/> disposes the
    /// running service <i>before</i> it re-attaches, so opening a drawing to look at it took
    /// down a bridge that was working and the failed re-attach left nothing in its place. A
    /// drawing is the "nothing worth attaching to" case, which the gate already leaves alone.
    /// </summary>
    [Fact]
    public void GlancingAtADrawingLeavesAWorkingBridgeExactlyAsItWas()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();

        gate.FollowDocument(@"C:\models\sheet.SLDDRW");

        Assert.Equal(1, world.Starts);
        Assert.False(world.Services[0].Disposed);
        Assert.Equal(@"C:\models\deck.SLDASM", gate.DocumentPath);
        Assert.Same(world.Services[0].ReviewBridge, world.Published);
        Assert.Contains(
            @"C:\models\sheet.SLDDRW", Assert.Single(world.Reports), StringComparison.Ordinal);
    }

    [Fact]
    public void ADrawingPassedOnTheWayDoesNotStopTheNextModelBeingFollowed()
    {
        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        ToolServiceGate gate = world.Gate();
        gate.EnsureStarted();
        FakeToolService first = world.Services[0];

        // Open the drawing, read it, open the part it documents: three ActiveDocChangeNotify
        // events, and the third is the one that has to re-attach.
        gate.FollowDocument(@"C:\models\sheet.SLDDRW");
        world.DocumentPath = @"C:\models\bracket.SLDPRT";
        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        Assert.Equal(2, world.Starts);
        Assert.True(first.Disposed);
        Assert.Equal(@"C:\models\bracket.SLDPRT", gate.DocumentPath);
        Assert.Equal(world.Services[1].ReviewBridge.Secret, world.Published!.Secret);
    }

    /// <summary>
    /// The predicate both entry points read, over the extensions SOLIDWORKS saves under. It is
    /// <see cref="PageDocument.Kind"/>'s answer narrowed to the two kinds that have a
    /// configuration, rather than a second extension table beside it.
    /// </summary>
    [Theory]
    [InlineData(@"C:\parts\bracket.sldprt", true)]
    [InlineData(@"C:\parts\bracket.SLDPRT", true)]
    [InlineData(@"C:\parts\deck assy.SLDASM", true)]
    [InlineData(@"C:\parts\sheet.slddrw", false)]
    [InlineData(@"C:\parts\sheet.SLDDRW", false)]
    [InlineData(@"C:\parts\bracket.step", false)]
    [InlineData(@"C:\parts\bracket", false)]
    public void OnlyAPartOrAnAssemblyIsSomethingAScopeCanBeAttachedTo(string path, bool attachable)
    {
        Assert.Equal(attachable, new PageDocument(path, null).IsAttachable);
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

    /// <summary>
    /// The same rule, for the other entry point, and for all three of the expensive things it
    /// does. <c>FollowDocument</c> is called from <c>ActiveDocChangeNotify</c> - the SOLIDWORKS
    /// application thread - and the add-in's busy question is a 30-second-timeout HTTP round
    /// trip per open chat while the teardown joins the accept thread, every client thread and
    /// the pump. Blocking the caller on either freezes SOLIDWORKS on an ordinary document
    /// switch, so the only work left on that thread is the decision to schedule.
    /// </summary>
    [Fact]
    public void TheBusyProbeTheTeardownAndTheRestartAllRunOffTheCallingThread()
    {
        var attached = new ManualResetEventSlim();
        var probing = new ManualResetEventSlim();
        var release = new ManualResetEventSlim();
        var restarted = new ManualResetEventSlim();
        int caller = Thread.CurrentThread.ManagedThreadId;
        int prober = caller;
        int starter = caller;

        var world = new GateWorld { DocumentPath = @"C:\models\deck.SLDASM" };
        world.Publish = _ =>
        {
            if (world.Services.Count > 1)
            {
                restarted.Set();
                return;
            }

            attached.Set();
        };

        // Null schedule: the gate's own, which is the one SwReviewAddIn gets.
        ToolServiceGate gate = world.Gate(schedule: null);
        gate.EnsureStarted();
        Assert.True(attached.Wait(TimeSpan.FromSeconds(10)), "the first tool service never started.");

        FakeToolService first = world.Services[0];
        world.OnBusy = () =>
        {
            prober = Thread.CurrentThread.ManagedThreadId;
            probing.Set();
            release.Wait(TimeSpan.FromSeconds(10));
        };
        world.OnStart = () => starter = Thread.CurrentThread.ManagedThreadId;
        world.DocumentPath = @"C:\models\bracket.SLDPRT";

        gate.FollowDocument(@"C:\models\bracket.SLDPRT");

        // Reached while the busy question is still out: before the fix, this line waited for it.
        Assert.True(probing.Wait(TimeSpan.FromSeconds(10)), "the busy question was never asked.");
        Assert.False(first.Disposed);
        release.Set();

        Assert.True(restarted.Wait(TimeSpan.FromSeconds(10)), "the tool service never re-attached.");
        Assert.NotEqual(caller, prober);
        Assert.NotEqual(caller, first.DisposedThreadId);
        Assert.NotEqual(caller, starter);
        Assert.Equal(@"C:\models\bracket.SLDPRT", gate.DocumentPath);
        Assert.Empty(world.Reports);
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

    // ---- drawing.read: the confirmed drawing's source (feature 011 T073) ------------------------
    //
    // specs/011-drawing-context/contracts/confirmed-open.md section 2. The backend names the review
    // a confirmed candidate belongs to by `run_id`, the run folder's own name, and the add-in
    // resolves it through the review host's own session records - never as a path - before
    // anything is opened, on the application thread every other command runs on. What is under
    // test is the request path the host builds (`ToolServiceHost.RequestChain`) around the source
    // it builds (`ToolServiceHost.ConfirmedDrawingSource`), behind a real ReviewHost, the real
    // secret policy and the real in-process server; SOLIDWORKS is faked behind the four seams the
    // confirmed read is given. Every rule of the read itself is the extractor's
    // (`ConfirmedDrawingReadTests`, `DrawingOpenTests`); these pin the wiring.

    /// <summary>
    /// Null review records - <c>ToolServiceOptions.ReviewRunDirectory</c>'s default - build no
    /// source, and the command then answers the dispatcher's sentence rather than reading from
    /// records the host does not keep.
    /// </summary>
    [Fact]
    public void AHostGivenNoReviewRecordsBuildsNoSourceAndDrawingReadSaysSo()
    {
        using (var world = new DrawingReadWorld(seatValidated: true, reviewRecords: false))
        {
            string name = Path.GetFileName(world.ReviewRun("chat-1"));
            world.Seat.AlreadyOpen(world.CandidatePath);

            BridgeResponse response = world.Read(name, world.HousingId, DrawingReadWorld.ReviewSecret);

            Assert.Null(world.Source);
            Assert.Equal(BridgeStatus.Error, response.Status);
            Assert.StartsWith("This bridge cannot read a drawing", response.Error, StringComparison.Ordinal);
            Assert.Empty(world.Seat.Calls);
        }
    }

    /// <summary>
    /// A review this host started, named by its folder's name: the id reaches the review host's
    /// own lookup exactly as sent, the candidate is read into that review's package, and the
    /// lookup and every SOLIDWORKS call run on the application thread. A drawing the engineer has
    /// open is read as it stands - no visibility, open or close call - which is also why this path
    /// works with the seat's switch off.
    /// </summary>
    [Fact]
    public void AReviewsCandidateIsReadThroughTheReviewHostsOwnRecordOnTheApplicationThread()
    {
        using (var world = new DrawingReadWorld(seatValidated: false))
        {
            string run = world.ReviewRun("chat-1");
            string name = Path.GetFileName(run);
            world.Seat.AlreadyOpen(world.CandidatePath);

            BridgeResponse response = world.Read(name, world.HousingId, DrawingReadWorld.ReviewSecret);

            Assert.Equal(BridgeStatus.Ok, response.Status);
            ConfirmedDrawingResult result = Assert.IsType<ConfirmedDrawingResult>(response.Result);
            Assert.Equal(world.HousingId, result.DocumentId);
            Assert.Equal(DocumentIds.For(world.CandidatePath), result.DrawingDocumentId);
            Assert.False(result.Opened);
            Assert.False(result.Closed);

            Assert.Equal(new[] { name }, world.LookupRunIds.ToArray());
            EvidencePackage package = PackageAppender.Load(run);
            Assert.Contains(package.DrawingRecords!, record => record.DocumentId == result.DrawingDocumentId);
            Assert.DoesNotContain(
                package.DrawingCandidates ?? new List<DrawingCandidate>(),
                row => row.DocumentId == world.HousingId);

            Assert.Equal(new[] { world.ApplicationThreadId }, world.LookupThreads.Distinct().ToArray());
            Assert.Equal(new[] { world.ApplicationThreadId }, world.Seat.Threads.Distinct().ToArray());
            Assert.Equal(new[] { "OpenDocument" }, world.Seat.Calls.Distinct().ToArray());
        }
    }

    /// <summary>
    /// Section 2, item 1: an id that names no review of this host - unknown, a Model check's or a
    /// remodel run's record (both tracked through <c>TrackCheck</c>, each folder holding a
    /// package), or the review's own folder spelt as a path - is refused naming it, and nothing
    /// is opened or read, although the seat's switch is on.
    /// </summary>
    [Theory]
    [InlineData("an unknown run")]
    [InlineData("a Model check record")]
    [InlineData("a remodel record")]
    [InlineData("the review's folder spelt as a path")]
    public void ARunIdThatIsNotOneOfThisHostsReviewsIsRefusedNamingItAndOpensNothing(string which)
    {
        using (var world = new DrawingReadWorld(seatValidated: true))
        {
            string review = world.ReviewRun("chat-1");
            string runId =
                which == "an unknown run" ? "20260923-101500-chat-404"
                : which == "a Model check record" ? Path.GetFileName(world.CheckRun("bracket-check"))
                : which == "a remodel record" ? Path.GetFileName(world.CheckRun("bracket-remodel"))
                : review;

            BridgeResponse response = world.Read(runId, world.HousingId, DrawingReadWorld.ReviewSecret);

            Assert.Equal(BridgeStatus.Error, response.Status);
            Assert.Equal(
                "'" + runId + "' is not a review this SOLIDWORKS session started, so no drawing was opened.",
                response.Error);
            Assert.Equal(new[] { runId }, world.LookupRunIds.ToArray());
            Assert.Empty(world.Seat.Calls);
            Assert.Equal(0, world.Seat.Reads);
        }
    }

    /// <summary>
    /// A review this host did start, whose run folder no longer holds a readable package - the
    /// file deleted, or cut short - is answered with an error on the request, never an exception
    /// that would reach the pipe, and nothing is opened or read.
    /// </summary>
    [Theory]
    [InlineData("deleted")]
    [InlineData("cut short")]
    public void AReviewWhosePackageCannotBeReadIsAnsweredWithAnErrorAndOpensNothing(string what)
    {
        using (var world = new DrawingReadWorld(seatValidated: true))
        {
            string run = world.ReviewRun("chat-1");
            string package = PackageAppender.PathIn(run);
            if (what == "deleted")
            {
                File.Delete(package);
            }
            else
            {
                File.WriteAllText(package, "{\"package_id\": ");
            }

            BridgeResponse response = world.Read(Path.GetFileName(run), world.HousingId, DrawingReadWorld.ReviewSecret);

            Assert.Equal(BridgeStatus.Error, response.Status);
            Assert.False(string.IsNullOrWhiteSpace(response.Error));
            if (what == "deleted")
            {
                Assert.Equal(
                    "The review '" + Path.GetFileName(run) + "' has no package in its run folder, so no drawing was opened.",
                    response.Error);
            }

            Assert.Empty(world.Seat.Calls);
            Assert.Equal(0, world.Seat.Reads);
            Assert.Single(world.LogLines);
        }
    }

    /// <summary>
    /// Review scope only (section 2): the general-chat and remodel secrets are answered
    /// `unauthorized` before the review host is asked or SOLIDWORKS touched, and the review
    /// secret reaches the command. No secret reaches the log.
    /// </summary>
    [Fact]
    public void TheReviewSecretReachesDrawingReadAndTheGeneralChatAndRemodelSecretsDoNot()
    {
        using (var world = new DrawingReadWorld(seatValidated: true))
        {
            string name = Path.GetFileName(world.ReviewRun("chat-1"));
            world.Seat.AlreadyOpen(world.CandidatePath);

            foreach (string refused in new[] { DrawingReadWorld.ChatSecret, DrawingReadWorld.RemodelSecret })
            {
                BridgeResponse response = world.Read(name, world.HousingId, refused);
                Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
                Assert.Null(response.Result);
            }

            Assert.Empty(world.LookupRunIds);
            Assert.Empty(world.Seat.Calls);

            BridgeResponse allowed = world.Read(name, world.HousingId, DrawingReadWorld.ReviewSecret);
            Assert.Equal(BridgeStatus.Ok, allowed.Status);
            Assert.Equal(new[] { name }, world.LookupRunIds.ToArray());

            foreach (string secret in new[]
                     {
                         DrawingReadWorld.ReviewSecret, DrawingReadWorld.ChatSecret, DrawingReadWorld.RemodelSecret,
                     })
            {
                Assert.DoesNotContain(secret, world.Log, StringComparison.Ordinal);
            }
        }
    }

    /// <summary>
    /// The SC-004 artifact: a confirmed read's line carries the seam's three qualified keys and
    /// the reads beside them on the request's own <c>gated=</c> field, and no <c>target=</c>.
    /// The drawing gate is observed by the plain recorder, and that matters: <c>CloseDoc</c> is
    /// on the remodel allowlist, so the remodel gate's observer would have recorded the close as a
    /// write to the run's copy.
    /// </summary>
    [Fact]
    public void AConfirmedReadsGatedKeysAreOnItsOwnLogLineAndNoTargetIsRecorded()
    {
        Assert.Contains(DrawingOpenGuard.CloseDocKey, RemodelGuard.AllowedKeys);

        using (var world = new DrawingReadWorld(seatValidated: true))
        {
            string name = Path.GetFileName(world.ReviewRun("chat-1"));

            BridgeResponse response = world.Read(name, world.HousingId, DrawingReadWorld.ReviewSecret);

            Assert.Equal(BridgeStatus.Ok, response.Status);
            ConfirmedDrawingResult result = Assert.IsType<ConfirmedDrawingResult>(response.Result);
            Assert.True(result.Opened);
            Assert.True(result.Closed);

            string line = Assert.Single(world.LogLines);
            Assert.Contains(" command=" + BridgeCommands.DrawingRead + " ", line, StringComparison.Ordinal);
            Assert.Contains(" status=ok ", line, StringComparison.Ordinal);
            Assert.Equal(
                new[]
                {
                    "GetOpenDocumentByName",
                    DrawingOpenGuard.DocumentVisibleKey,
                    DrawingOpenGuard.OpenDocKey,
                    DrawingReadWorld.PhaseRead,
                    DrawingOpenGuard.CloseDocKey,
                },
                GatedOf(line));
            Assert.DoesNotContain(" target=", line, StringComparison.Ordinal);
            Assert.DoesNotContain(" refused=", line, StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// While the seat is unvalidated (T077 has not run), a closed candidate is refused with the
    /// seam's sentence and the only key on its line is the lookup that found it closed: nothing
    /// was hidden, opened or closed.
    /// </summary>
    [Fact]
    public void WhileTheSeatIsUnvalidatedAClosedCandidateIsRefusedAndOnlyTheLookupIsGated()
    {
        using (var world = new DrawingReadWorld(seatValidated: false))
        {
            string name = Path.GetFileName(world.ReviewRun("chat-1"));

            BridgeResponse response = world.Read(name, world.HousingId, DrawingReadWorld.ReviewSecret);

            Assert.Equal(BridgeStatus.Error, response.Status);
            Assert.Equal(DrawingOpenScope.NotValidatedSentence, response.Error);
            Assert.Equal(new[] { "GetOpenDocumentByName" }, GatedOf(Assert.Single(world.LogLines)));
            Assert.Equal(new[] { "OpenDocument" }, world.Seat.Calls.ToArray());
            Assert.Equal(0, world.Seat.Reads);
        }
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

    // ---- drawing.read's world (T073) ------------------------------------------------------------

    /// <summary>
    /// The add-in's side of <c>drawing.read</c>, composed as <see cref="ToolServiceHost"/> composes
    /// it: a real <see cref="ReviewHost"/> whose session records the lookup reads, the source
    /// <see cref="ToolServiceHost.ConfirmedDrawingSource"/> builds on them, the real dispatcher and
    /// secret policy inside <see cref="ToolServiceHost.RequestChain"/>, and the real in-process
    /// server posting every request to a <see cref="FakeAppThread"/>. The review is of a fictional
    /// assembly under a temporary folder, whose housing has a candidate drawing on disk beside it.
    /// </summary>
    private sealed class DrawingReadWorld : IDisposable
    {
        public const string ReviewSecret = "review-secret-0123456789";
        public const string ChatSecret = "general-chat-secret-abcdefghij";
        public const string RemodelSecret = "remodel-secret-klmnopqrstuv";

        /// <summary>The bare-name read the fake drawing phase gates, as the real one gates its reads.</summary>
        public const string PhaseRead = "GetSheetNames";

        private readonly string _root;
        private readonly string _runRoot;
        private readonly FakeAppThread _app = new FakeAppThread();
        private readonly ReviewHost _host;
        private readonly InProcPipeServer _server;
        private readonly StringWriter _log = new StringWriter();
        private readonly object _lookupLock = new object();
        private readonly List<string> _lookupRunIds = new List<string>();
        private readonly List<int> _lookupThreads = new List<int>();

        /// <param name="seatValidated">The switch the source's seam is built with; the add-in
        /// passes <see cref="DrawingOpenScope.SeatValidated"/>.</param>
        /// <param name="reviewRecords">False gives the host no review records, as a
        /// <see cref="ToolServiceOptions"/> left at its default does.</param>
        public DrawingReadWorld(bool seatValidated, bool reviewRecords = true)
        {
            _root = Path.Combine(Path.GetTempPath(), "swreview-drawing-read", Guid.NewGuid().ToString("N"));
            string models = Path.Combine(_root, "models");
            _runRoot = Path.Combine(_root, "runs");
            Directory.CreateDirectory(models);
            Directory.CreateDirectory(_runRoot);

            AssemblyPath = Path.Combine(models, "bracket-assy.SLDASM");
            HousingPath = Path.Combine(models, "housing.SLDPRT");
            CandidatePath = Path.Combine(models, "housing.SLDDRW");
            File.WriteAllBytes(CandidatePath, new byte[0]);

            UserSettings settings = UserSettings.Defaults();
            settings.RunRoot = _runRoot;
            string settingsPath = Path.Combine(_root, "settings.json");
            settings.Save(settingsPath);
            _host = new ReviewHost(new ReviewHostOptions(new SilentChannel(), new UnusedBackend(), settingsPath)
            {
                BuildMode = BuildMode.Development,
                LogFolder = Path.Combine(_root, "logs"),
                Environment = _ => null,
            });

            Recorder = new SwGateRecorder();
            Seat = new FakeDrawingSeat(new SwGate { Observer = Recorder });
            Source = ToolServiceHost.ConfirmedDrawingSource(
                reviewRecords ? Lookup : (Func<string, string?>?)null,
                AssemblyPath,
                Recorder,
                Seat,
                seatValidated,
                Seat,
                Seat,
                Seat);

            var services = new BridgeServices(
                new NoViews(), new NoViews(), new NoViews(), new ComponentIndex(new ComponentTreeResult()), _root)
            {
                DocumentPath = AssemblyPath,
                Configuration = "Default",
                ConfirmedDrawings = Source,
            };

            _server = new InProcPipeServer(new InProcPipeServerOptions(
                PipeNames.NewToolServiceName(),
                ToolServiceHost.RequestChain(
                    new SwBridgeDispatcher(services, new ScopedSecretPolicy(ReviewSecret, ChatSecret, RemodelSecret)),
                    () => true,
                    AssemblyPath,
                    Recorder,
                    _log.Write),
                _app)
            {
                InvokeTimeout = TimeSpan.FromSeconds(30),
            });
        }

        public string AssemblyPath { get; }

        public string HousingPath { get; }

        public string CandidatePath { get; }

        public string HousingId => DocumentIds.For(HousingPath);

        public SwGateRecorder Recorder { get; }

        public FakeDrawingSeat Seat { get; }

        /// <summary>What <see cref="ToolServiceHost.ConfirmedDrawingSource"/> built, or null.</summary>
        public IConfirmedDrawingSource? Source { get; }

        public int ApplicationThreadId => _app.ThreadId;

        /// <summary>The tool-service log as written: one line per request.</summary>
        public string Log => _log.ToString();

        public string[] LogLines =>
            Log.Split(new[] { System.Environment.NewLine }, StringSplitOptions.RemoveEmptyEntries);

        /// <summary>Every run id the review host's lookup was asked about, in order.</summary>
        public IReadOnlyList<string> LookupRunIds
        {
            get
            {
                lock (_lookupLock)
                {
                    return _lookupRunIds.ToArray();
                }
            }
        }

        public IReadOnlyList<int> LookupThreads
        {
            get
            {
                lock (_lookupLock)
                {
                    return _lookupThreads.ToArray();
                }
            }
        }

        /// <summary>A review this host started: its run folder, holding the package, tracked for a chat.</summary>
        public string ReviewRun(string chatId)
        {
            string folder = RunFolder("20260923-101500-" + chatId);
            _host.TrackSession(chatId, folder);
            return folder;
        }

        /// <summary>A Model check's, a Standards run's or a remodel run's folder, tracked as one.</summary>
        public string CheckRun(string name)
        {
            string folder = RunFolder("20260923-101500-" + name);
            _host.TrackCheck(folder);
            return folder;
        }

        /// <summary>One <c>drawing.read</c> line, answered through the whole request path.</summary>
        public BridgeResponse Read(string runId, string documentId, string secret) =>
            _server.Answer(JsonSerializer.Serialize(new Dictionary<string, object>
            {
                { "id", "7" },
                { "command", BridgeCommands.DrawingRead },
                { "secret", secret },
                { "params", new Dictionary<string, string> { { "run_id", runId }, { "document_id", documentId } } },
            }));

        public void Dispose()
        {
            _server.Dispose();
            _app.Dispose();
            _host.Dispose();
            try
            {
                Directory.Delete(_root, recursive: true);
            }
            catch (IOException)
            {
            }
        }

        /// <summary>The add-in's lookup, <see cref="ReviewHost.ReviewRunDirectory"/>, watched.</summary>
        private string? Lookup(string runId)
        {
            lock (_lookupLock)
            {
                _lookupRunIds.Add(runId);
                _lookupThreads.Add(Thread.CurrentThread.ManagedThreadId);
            }

            return _host.ReviewRunDirectory(runId);
        }

        private string RunFolder(string name)
        {
            string folder = Path.Combine(_runRoot, name);
            Directory.CreateDirectory(folder);
            PackageAppender.Save(folder, Package());
            return folder;
        }

        /// <summary>The package `review.start` wrote: the assembly, its housing, and the housing's candidate.</summary>
        private EvidencePackage Package()
        {
            var package = new EvidencePackage
            {
                PackageId = Guid.NewGuid(),
                CreatedAt = DateTimeOffset.Now,
                Design = new Design
                {
                    DesignId = DocumentIds.DesignId(AssemblyPath),
                    Name = "bracket-assy",
                    RootAssemblyDocumentId = DocumentIds.For(AssemblyPath),
                    ActiveConfiguration = "Default",
                },
                DrawingRecords = new List<DrawingRecord>(),
                DrawingCandidates = new List<DrawingCandidate>
                {
                    new DrawingCandidate { DocumentId = HousingId, Path = CandidatePath },
                },
            };

            AddDocument(package, AssemblyPath, DocumentKind.Assembly);
            AddDocument(package, HousingPath, DocumentKind.Part);
            return package;
        }

        private static void AddDocument(EvidencePackage package, string path, DocumentKind kind)
        {
            string id = DocumentIds.For(path);
            package.Documents.Add(new Document
            {
                DocumentId = id,
                Kind = kind,
                FileName = Path.GetFileName(path),
                Path = path,
                ActiveConfiguration = "Default",
            });
            package.Manifest.Entries.Add(new ManifestEntry
            {
                DocumentId = id,
                VaultPath = path,
                Configuration = "Default",
                ExportMethod = ExportMethod.Native,
            });
        }
    }

    /// <summary>
    /// SOLIDWORKS behind the four seams <see cref="ConfirmedDrawingRead"/> is given: which
    /// drawings are open and what an open does (<see cref="IDrawingOpenHost"/>), and the drawing,
    /// document and manifest phases. Records each open-host call by name and the thread it ran on;
    /// the drawing phase gates one bare-name read through the host's recorder, as the real phase
    /// reads through the session's gate.
    /// </summary>
    private sealed class FakeDrawingSeat : IDrawingOpenHost, IDrawingSource, IDocumentSource, IManifestSource
    {
        private readonly Dictionary<string, object> _open = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        private readonly SwGate _readGate;

        public FakeDrawingSeat(SwGate readGate)
        {
            _readGate = readGate;
        }

        /// <summary>The open-host calls, by member name, in order.</summary>
        public List<string> Calls { get; } = new List<string>();

        /// <summary>The thread each open-host call ran on.</summary>
        public List<int> Threads { get; } = new List<int>();

        /// <summary>How many times the drawing phase read a drawing.</summary>
        public int Reads { get; private set; }

        public void AlreadyOpen(string path) => _open[path] = new object();

        public object? OpenDocument(string path)
        {
            Record(nameof(OpenDocument));
            return _open.TryGetValue(path, out object? document) ? document : null;
        }

        public void DocumentVisible(bool visible, int documentType) => Record(nameof(DocumentVisible));

        public object? OpenDoc6(string path, int documentType, int options, string configuration, out int errors, out int warnings)
        {
            Record(nameof(OpenDoc6));
            errors = 0;
            warnings = 0;
            var document = new object();
            _open[path] = document;
            return document;
        }

        public void CloseDoc(string path)
        {
            Record(nameof(CloseDoc));
            _open.Remove(path);
        }

        public IReadOnlyList<DrawingRecord> Dump(DumpScope scope)
        {
            Reads++;
            _readGate.Call(DrawingReadWorld.PhaseRead, () => 0);
            return scope.Drawings.Select(drawing =>
            {
                var record = new DrawingRecord { DocumentId = scope.DocumentId(drawing.DocumentPath), ActiveSheetName = "Sheet1" };
                record.Sheets.Add(new DrawingSheetRecord
                {
                    Id = scope.DrawingIds.Sheets.Next(),
                    Name = "Sheet1",
                    Index = 0,
                    WasActive = true,
                });
                return record;
            }).ToList();
        }

        public IReadOnlyList<Document> Dump(DumpScope scope, IReadOnlyList<string> documentPaths) =>
            documentPaths.Select(path => new Document
            {
                DocumentId = scope.DocumentId(path),
                Kind = DocumentKind.Drawing,
                FileName = Path.GetFileName(path),
                Path = path,
                ActiveConfiguration = string.Empty,
            }).ToList();

        public Manifest Build(DumpScope scope, IReadOnlyList<Document> documents)
        {
            var manifest = new Manifest();
            foreach (Document document in documents)
            {
                manifest.Entries.Add(new ManifestEntry
                {
                    DocumentId = document.DocumentId,
                    VaultPath = document.Path,
                    Configuration = document.ActiveConfiguration,
                    ExportMethod = ExportMethod.Native,
                });
            }

            return manifest;
        }

        private void Record(string member)
        {
            Calls.Add(member);
            Threads.Add(Thread.CurrentThread.ManagedThreadId);
        }
    }

    /// <summary>Capture, measure and interference: <c>drawing.read</c> touches none of them.</summary>
    private sealed class NoViews : ICaptureView, IMeasureSource, IInterferenceSource
    {
        private const string Untouched = "drawing.read touches no capture, measure or interference source.";

        public bool TrySelect(string persistRef, string? scopeDocumentPath, out string reason) =>
            throw new NotSupportedException(Untouched);

        public IReadOnlyList<string> SelectedComponentIds() => throw new NotSupportedException(Untouched);

        public void ZoomToSelection() => throw new NotSupportedException(Untouched);

        public void ShowNamedView(string namedView) => throw new NotSupportedException(Untouched);

        public bool SaveImage(string pngPath) => throw new NotSupportedException(Untouched);

        public MeasureReading Measure(string persistRefA, string? scopeA, string persistRefB, string? scopeB) =>
            throw new NotSupportedException(Untouched);

        public IInterferenceDetector Open() => throw new NotSupportedException(Untouched);
    }

    // ---- fakes ---------------------------------------------------------------------------------

    /// <summary>The three delegates <see cref="SwReviewAddIn"/> supplies, and what they saw.</summary>
    private sealed class GateWorld
    {
        private int _next;

        public bool DocumentOpen { get; set; } = true;

        /// <summary>What the next start attaches to, as SOLIDWORKS' active document would be.</summary>
        public string DocumentPath { get; set; } = @"C:\models\bracket.sldasm";

        /// <summary>
        /// The active document as <c>SwReviewAddIn.CurrentDocument</c> reports it - a saved path
        /// and nothing else - because what the gate decides from is the document, not a bool: a
        /// drawing is open and is still not something a scope can be attached to.
        /// </summary>
        public PageDocument? Active() => DocumentOpen ? new PageDocument(DocumentPath, null) : null;

        /// <summary>A review turn or a remodel run is holding the bridge.</summary>
        public bool Busy { get; set; }

        /// <summary>Set to make the busy question throw, as an unanswering backend would.</summary>
        public Exception? BusyFailure { get; set; }

        /// <summary>Runs inside the busy question, on whichever thread asked it. The add-in's
        /// answer is one HTTP round trip per open chat, so a test may block here.</summary>
        public Action? OnBusy { get; set; }

        /// <summary>Set to make the next start throw, as a failed attach would.</summary>
        public Exception? Failure { get; set; }

        /// <summary>Runs inside the start delegate, on whichever thread it was scheduled onto.</summary>
        public Action? OnStart { get; set; }

        /// <summary>What the add-in does with the service that is running now, or with null when
        /// none is; the default records it.</summary>
        public Action<IToolService?>? Publish { get; set; }

        public List<FakeToolService> Services { get; } = new List<FakeToolService>();

        public List<string> Reports { get; } = new List<string>();

        public BridgeConfig? Published { get; private set; }

        public int Starts => Services.Count;

        /// <summary>A gate that starts inline, so an assertion can follow the call.</summary>
        public ToolServiceGate Gate() => Gate(work => work());

        /// <summary>Null means the gate's own schedule - the one the add-in gets.</summary>
        public ToolServiceGate Gate(Action<Action>? schedule) => new ToolServiceGate(
            Active,
            Start,
            service =>
            {
                if (Publish != null)
                {
                    Publish(service);
                    return;
                }

                Published = service?.ReviewBridge;
            },
            (what, failure) => Reports.Add(failure == null ? what : what + " " + failure.Message),
            schedule,
            Asked);

        private bool Asked()
        {
            OnBusy?.Invoke();

            if (BusyFailure != null)
            {
                throw BusyFailure;
            }

            return Busy;
        }

        private IToolService Start()
        {
            OnStart?.Invoke();

            if (Failure != null)
            {
                throw Failure;
            }

            var service = new FakeToolService(++_next, DocumentPath);
            Services.Add(service);
            return service;
        }
    }

    /// <summary>A tool service with no pipe, no SOLIDWORKS and two distinct secrets.</summary>
    private sealed class FakeToolService : IToolService
    {
        public FakeToolService(int ordinal, string? documentPath = null)
        {
            PipeName = "swreview-fake-" + ordinal;
            ReviewBridge = new BridgeConfig(PipeName, "review-secret-" + ordinal);
            GeneralChatBridge = new BridgeConfig(PipeName, "chat-secret-" + ordinal);
            RemodelBridge = new BridgeConfig(PipeName, "remodel-secret-" + ordinal);
            RemodelSeatAvailable = false;
            DocumentPath = documentPath ?? @"C:\models\bracket-" + ordinal + ".sldasm";
            Session = new FakeSession();
        }

        public string PipeName { get; }

        public string DocumentPath { get; }

        public BridgeConfig ReviewBridge { get; }

        public BridgeConfig GeneralChatBridge { get; }

        public BridgeConfig RemodelBridge { get; }

        public bool RemodelSeatAvailable { get; }

        public ISwSession Session { get; }

        public bool Disposed { get; private set; }

        /// <summary>
        /// The thread the gate stopped it on. Recorded because the real stop joins an accept
        /// thread, every client thread and the pump - so it must not be the SOLIDWORKS
        /// application thread.
        /// </summary>
        public int DisposedThreadId { get; private set; }

        /// <summary>What the gate wrote into this service's own tool-service log.</summary>
        public List<string> LogLines { get; } = new List<string>();

        public void WriteLog(string line) => LogLines.Add(line);

        public void Dispose()
        {
            DisposedThreadId = Thread.CurrentThread.ManagedThreadId;
            Disposed = true;
        }
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
