using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using SwReview.AddIn.ToolService;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Measure;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T046: the in-process tool service - the half of the bridge that lives inside SOLIDWORKS.
///
/// The console host (feature 001) could own its own STA thread and be done. This one cannot:
/// the `ISldWorks` pointer belongs to the thread SOLIDWORKS itself runs on, which is also the
/// thread that runs modal dialogs and rebuilds. Every clause below is one way that difference
/// can hurt an engineer, so each is pinned here rather than discovered in a review:
///
/// - a request arrives on a pipe reader thread and must be *executed* on the application
///   thread, or the first COM call fails with "interface marshalled for a different thread";
/// - two clients exist by design - the review backend holds the review secret and the CLI's
///   MCP server holds the general-chat one - so concurrent requests must serialize, in
///   arrival order, or a capture changes the selection underneath a measure;
/// - the secret is what bounds the general-chat scope (contracts/README.md), and it must
///   never reach the log, because the log is the artifact SC-004 is audited from;
/// - the application thread can simply stop answering (a modal dialog), so the wait is
///   bounded and the delegate that wakes up twenty minutes later must not be able to write a
///   stale response onto a pipe that has moved on;
/// - `Control.BeginInvoke` throws when the handle is not created or was destroyed during
///   unload, and that throw must not land on the reader thread and kill the listener;
/// - the engineer can close the document mid-review, and the answer has to be the sentence
///   the Python client recognises (`no longer open`) so the check becomes failed coverage
///   rather than a crash (reviewer/src/swreview/bridge/client.py, DOCUMENT_CLOSED_MARKER);
/// - a named pipe created with the default security descriptor is readable by any local
///   process, so the DACL is asserted here, not assumed.
/// </summary>
public sealed class InProcPipeServerTests
{
    private const string ReviewSecret = "review-secret-0123456789";
    private const string ChatSecret = "general-chat-secret-abcdefghij";

    /// <summary>Feature 004's third scope: <c>ping</c> and <c>remodel.*</c>, and nothing else.</summary>
    private const string RemodelSecret = "remodel-secret-klmnopqrstuv";

    // ---- the thread the work runs on ------------------------------------------------------

    [Fact]
    public void ARequestReadOnAPipeThreadIsExecutedOnTheApplicationThread()
    {
        using (var app = new FakeAppThread())
        {
            var dispatcher = new RecordingDispatcher();
            using (InProcPipeServer server = Server(dispatcher, app))
            {
                server.Start();

                using (PipeClient client = Connect(server.PipeName))
                {
                    client.Send(Line("1", "ping", ReviewSecret));
                    Assert.Equal("ok", client.Receive().Status);
                }
            }

            // The command ran on the application thread and nowhere else.
            Assert.Equal(new[] { app.ThreadId }, dispatcher.DispatchThreads.Distinct().ToArray());

            // And it was handed there from a thread that is neither the application thread
            // nor this test's: the reader/pump side really is separate.
            int posted = Assert.Single(app.PostThreads.Distinct());
            Assert.NotEqual(app.ThreadId, posted);
            Assert.NotEqual(Thread.CurrentThread.ManagedThreadId, posted);
        }
    }

    [Fact]
    public void APingRoundTripsOverTheRealPipeAsOneJsonLine()
    {
        using (var app = new FakeAppThread())
        using (InProcPipeServer server = Server(new RecordingDispatcher(), app))
        {
            server.Start();
            using (PipeClient client = Connect(server.PipeName))
            {
                client.Send(Line("abc", "ping", ReviewSecret));
                BridgeAnswer answer = client.Receive();

                Assert.Equal("abc", answer.Id);
                Assert.Equal("ok", answer.Status);
                Assert.Null(answer.Error);
            }
        }
    }

    // ---- one at a time, in arrival order --------------------------------------------------

    [Fact]
    public void ConcurrentRequestsSerializeInArrivalOrder()
    {
        // The application thread runs nothing until the test releases it, one call at a time,
        // so "second" and "third" are facts here rather than a race the test usually wins.
        using (var app = new FakeAppThread(manual: true))
        {
            var dispatcher = new RecordingDispatcher();
            using (InProcPipeServer server = Server(dispatcher, app))
            {
                var answers = new ConcurrentDictionary<string, BridgeResponse>();
                var callers = new List<Thread>();

                Thread first = Ask(server, answers, "1");
                Until(() => app.Posted == 1, "the first request reached the application thread");
                callers.Add(first);

                // Queued behind it, in the order they were asked.
                callers.Add(Ask(server, answers, "2"));
                Until(() => server.QueuedRequests == 1, "the second request was queued");
                callers.Add(Ask(server, answers, "3"));
                Until(() => server.QueuedRequests == 2, "the third request was queued");

                // Nothing overtook: exactly one call has been handed to the application
                // thread, even though three are outstanding.
                Assert.Equal(1, app.Posted);

                app.ReleaseOne();
                Until(() => app.Posted == 2, "the second request reached the application thread");
                app.ReleaseOne();
                Until(() => app.Posted == 3, "the third request reached the application thread");
                app.ReleaseOne();

                foreach (Thread caller in callers)
                {
                    Assert.True(caller.Join(TimeSpan.FromSeconds(10)), "a caller never got its answer");
                }

                Assert.Equal(new[] { "1", "2", "3" }, dispatcher.DispatchedIds.ToArray());
                Assert.Equal(3, answers.Count);
                Assert.All(answers.Values, response => Assert.Equal("ok", response.Status));
                Assert.Equal(1, dispatcher.MaxConcurrent);
            }
        }
    }

    // ---- the secret ------------------------------------------------------------------------

    [Fact]
    public void AWrongSecretIsUnauthorizedAndNeverReachesTheLog()
    {
        var log = new StringWriter();
        using (var world = new ScopedWorld(log))
        {
            BridgeResponse response = world.Server.Answer(Line("1", "ping", "not-the-secret-9999"));

            Assert.Equal("error", response.Status);
            Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
            Assert.Null(response.Result);

            string written = log.ToString();
            Assert.Contains("unauthorized", written);
            Assert.DoesNotContain("not-the-secret-9999", written);
            Assert.DoesNotContain(ReviewSecret, written);
            Assert.DoesNotContain(ChatSecret, written);
        }
    }

    [Fact]
    public void AMissingSecretIsUnauthorized()
    {
        var log = new StringWriter();
        using (var world = new ScopedWorld(log))
        {
            // A client written for the console host omits the field entirely (T045).
            BridgeResponse response = world.Server.Answer("{\"id\":\"1\",\"command\":\"ping\"}");

            Assert.Equal("error", response.Status);
            Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
            Assert.DoesNotContain(ReviewSecret, log.ToString());
        }
    }

    [Fact]
    public void TheGeneralChatSecretIsRefusedOnInterference()
    {
        var log = new StringWriter();
        using (var world = new ScopedWorld(log))
        {
            BridgeResponse response = world.Server.Answer(Line("1", "interference", ChatSecret));

            Assert.Equal("error", response.Status);
            Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);

            // Refused before anything ran: the interference source was never opened.
            Assert.Equal(0, world.Interference.Opened);
            Assert.DoesNotContain(ChatSecret, log.ToString());
        }
    }

    [Fact]
    public void TheGeneralChatSecretIsAcceptedOnCapture()
    {
        var log = new StringWriter();
        using (var world = new ScopedWorld(log))
        {
            BridgeResponse response = world.Server.Answer(
                Line("1", "capture", ChatSecret, "{\"persist_ref\":\"cGVyc2lzdA==\"}"));

            Assert.Equal("ok", response.Status);
            Assert.Equal(1, world.CaptureView.Saved);
        }
    }

    [Fact]
    public void TheReviewSecretIsAcceptedOnInterference()
    {
        var log = new StringWriter();
        using (var world = new ScopedWorld(log))
        {
            BridgeResponse response = world.Server.Answer(Line("1", "interference", ReviewSecret));

            // Whatever the fake source then does, the secret let the command through.
            Assert.NotEqual(SwBridgeDispatcher.UnauthorizedError, response.Error);
            Assert.Equal(1, world.Interference.Opened);
        }
    }

    // ---- the third scope: the remodel secret (T069) -----------------------------------------
    //
    // contracts/bridge-remodel.md, "Authorization": RemodelSecret may call `ping` and
    // `remodel.*` and nothing else; neither of the other two secrets may call any `remodel.*`.
    // One row per command in both directions, because a scope asserted only on the command
    // somebody thought of is a scope nobody checked.

    public static IEnumerable<object[]> RemodelCommandRows =>
        RemodelCommands.All.Select(command => new object[] { command });

    public static IEnumerable<object[]> NonRemodelCommandRows =>
        new[]
            {
                BridgeCommands.Capture,
                BridgeCommands.Measure,
                BridgeCommands.Interference,
                BridgeCommands.Tessellate,
            }
            .Select(command => new object[] { command });

    [Theory]
    [MemberData(nameof(RemodelCommandRows))]
    public void TheRemodelSecretAuthorizesEveryRemodelCommand(string command)
    {
        Assert.True(Scoped().IsAuthorized(RemodelSecret, command));
    }

    [Theory]
    [MemberData(nameof(RemodelCommandRows))]
    public void TheGeneralChatSecretIsRefusedForEveryRemodelCommand(string command)
    {
        Assert.False(Scoped().IsAuthorized(ChatSecret, command));
    }

    [Theory]
    [MemberData(nameof(RemodelCommandRows))]
    public void TheReviewSecretIsRefusedForEveryRemodelCommand(string command)
    {
        // The review session's secret is the whole review vocabulary and none of this one: a
        // review that could call remodel.open would be a review that writes.
        Assert.False(Scoped().IsAuthorized(ReviewSecret, command));
    }

    [Theory]
    [MemberData(nameof(NonRemodelCommandRows))]
    public void TheRemodelSecretIsRefusedForEveryCommandOutsideItsFamily(string command)
    {
        Assert.False(Scoped().IsAuthorized(RemodelSecret, command));
    }

    [Fact]
    public void TheRemodelSecretAuthorizesPingAndNothingElseOutsideTheFamily()
    {
        ScopedSecretPolicy policy = Scoped();

        Assert.True(policy.IsAuthorized(RemodelSecret, BridgeCommands.Ping));
        Assert.False(policy.IsAuthorized(RemodelSecret, BridgeCommands.Interference));

        // Named as its own row because contracts/bridge-remodel.md names it as its own row.
        Assert.Equal(
            new[] { BridgeCommands.Ping }.Concat(RemodelCommands.All).ToArray(),
            ScopedSecretPolicy.RemodelScopeCommands.ToArray());
    }

    [Theory]
    [InlineData("remodel.")]
    [InlineData("remodel.dissolve")]
    [InlineData("remodel.open2")]
    public void ANameThatMerelyStartsWithRemodelIsAuthorizedByNoSecret(string command)
    {
        // The scope is the twelve commands listed, not a prefix: a thirteenth command has to be
        // added to the table before any secret can reach it.
        ScopedSecretPolicy policy = Scoped();

        Assert.False(policy.IsAuthorized(RemodelSecret, command));
        Assert.False(policy.IsAuthorized(ReviewSecret, command));
        Assert.False(policy.IsAuthorized(ChatSecret, command));
    }

    [Fact]
    public void TheThreeSecretsMustDifferFromEachOther()
    {
        // One secret for two scopes would authenticate without bounding what it authorizes.
        Assert.Throws<ArgumentException>(
            () => new ScopedSecretPolicy(ReviewSecret, ChatSecret, ReviewSecret));
        Assert.Throws<ArgumentException>(
            () => new ScopedSecretPolicy(ReviewSecret, ChatSecret, ChatSecret));
    }

    [Fact]
    public void TheRemodelSecretReachesTheDispatcherAndTheOtherTwoDoNot()
    {
        var log = new StringWriter();
        using (var world = new ScopedWorld(log))
        {
            // This bridge has no remodel seat, so the command is refused - but by the handler,
            // naming the seat, rather than by the secret policy.
            BridgeResponse allowed = world.Server.Answer(
                Line("1", RemodelCommands.Snapshot, RemodelSecret));
            Assert.NotEqual(SwBridgeDispatcher.UnauthorizedError, allowed.Error);

            foreach (string refused in new[] { ChatSecret, ReviewSecret })
            {
                BridgeResponse response = world.Server.Answer(
                    Line("2", RemodelCommands.Snapshot, refused));
                Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
                Assert.Null(response.Result);
            }

            Assert.DoesNotContain(RemodelSecret, log.ToString());
        }
    }

    private static ScopedSecretPolicy Scoped() =>
        new ScopedSecretPolicy(ReviewSecret, ChatSecret, RemodelSecret);

    // ---- the application thread stops answering --------------------------------------------

    [Fact]
    public void AnInvokeThatNeverCompletesTimesOutWithTheDocumentedError()
    {
        using (var app = new FakeAppThread(manual: true))
        using (InProcPipeServer server = Server(new RecordingDispatcher(), app, timeout: TimeSpan.FromMilliseconds(250)))
        {
            var clock = Stopwatch.StartNew();
            BridgeResponse response = server.Answer(Line("1", "ping", ReviewSecret));
            clock.Stop();

            Assert.Equal("error", response.Status);
            Assert.Equal(
                "the SOLIDWORKS thread did not answer within 0.3s - a dialog may be open",
                response.Error);
            Assert.True(
                clock.Elapsed < TimeSpan.FromSeconds(5),
                "the bounded wait did not bound anything: " + clock.Elapsed);
        }
    }

    [Fact]
    public void TheLateDelegateCannotWriteAStaleResponse()
    {
        using (var app = new FakeAppThread(manual: true))
        {
            var dispatcher = new RecordingDispatcher();
            using (InProcPipeServer server = Server(dispatcher, app, timeout: TimeSpan.FromMilliseconds(250)))
            {
                server.Start();
                using (PipeClient client = Connect(server.PipeName))
                {
                    client.Send(Line("stale", "ping", ReviewSecret));
                    Assert.Equal(
                        "the SOLIDWORKS thread did not answer within 0.3s - a dialog may be open",
                        client.Receive().Error);

                    // The dialog closes and the queued delegate finally runs.
                    app.ReleaseOne();
                    Until(() => dispatcher.DispatchedIds.Count == 1, "the late delegate ran");

                    // The next request gets its own answer, not the abandoned one.
                    client.Send(Line("fresh", "ping", ReviewSecret));
                    app.ReleaseOne();
                    BridgeAnswer answer = client.Receive();

                    Assert.Equal("fresh", answer.Id);
                    Assert.Equal("ok", answer.Status);
                }
            }
        }
    }

    [Fact]
    public void AnAbandonedCallNeverPublishesItsResult()
    {
        using (var app = new FakeAppThread(manual: true))
        {
            AppThreadCall<int> call = AppThreadCall<int>.Post(app, () => 42);

            Assert.False(call.Wait(TimeSpan.FromMilliseconds(100)));
            call.Abandon();

            app.ReleaseOne();
            Until(() => app.Ran == 1, "the abandoned delegate ran late");

            Assert.False(call.Completed);
            Assert.True(call.Abandoned);
        }
    }

    // ---- the control the work is marshalled onto --------------------------------------------

    [Fact]
    public void AControlWithNoHandleAnswersACleanError()
    {
        var invoker = new FakeAppThread { CanInvokeValue = false };
        using (invoker)
        using (InProcPipeServer server = Server(new RecordingDispatcher(), invoker))
        {
            BridgeResponse response = server.Answer(Line("1", "ping", ReviewSecret));

            Assert.Equal("error", response.Status);
            Assert.Equal(InProcPipeServer.UnavailableError, response.Error);
            Assert.Equal(0, invoker.Posted);
        }
    }

    [Fact]
    public void ABeginInvokeThatThrowsAnswersACleanErrorInsteadOfKillingTheReader()
    {
        // The handle is destroyed between the check and the call - the unload race the
        // `IsHandleCreated` test alone cannot close (research R6).
        var invoker = new FakeAppThread
        {
            PostFailure = new InvalidOperationException(
                "Invoke or BeginInvoke cannot be called on a control until the window handle has been created."),
        };

        using (invoker)
        using (InProcPipeServer server = Server(new RecordingDispatcher(), invoker))
        {
            server.Start();
            using (PipeClient client = Connect(server.PipeName))
            {
                client.Send(Line("1", "ping", ReviewSecret));
                BridgeAnswer answer = client.Receive();

                Assert.Equal("error", answer.Status);
                Assert.StartsWith(InProcPipeServer.UnavailableError, answer.Error);

                // The listener is still alive: the throw did not land on the reader thread.
                client.Send(Line("2", "ping", ReviewSecret));
                Assert.Equal("2", client.Receive().Id);
            }
        }
    }

    [Fact]
    public void TheControlInvokerReportsAnUncreatedAndADisposedControlAsUnavailable()
    {
        var control = new Control();
        var invoker = new ControlAppThreadInvoker(control);

        // Constructed, never shown: WinForms creates the handle lazily.
        Assert.False(control.IsHandleCreated);
        Assert.False(invoker.CanInvoke);

        control.Dispose();
        Assert.False(invoker.CanInvoke);
    }

    // ---- the document goes away --------------------------------------------------------------

    [Fact]
    public void ARequestWhoseDocumentIsGoneAnswersTheDocumentClosedError()
    {
        bool open = true;
        var inner = new RecordingDispatcher { Failure = "COMException: the RPC server is unavailable" };
        var presence = new DocumentPresenceDispatcher(inner, () => open);

        using (var app = new FakeAppThread())
        using (InProcPipeServer server = Server(presence, app))
        {
            open = false;
            BridgeResponse response = server.Answer(Line("1", "measure", ReviewSecret));

            Assert.Equal("error", response.Status);

            // The exact substring reviewer/src/swreview/bridge/client.py matches on
            // (DOCUMENT_CLOSED_MARKER); the Python half of this - the failed-coverage record -
            // is asserted in reviewer/tests/unit/test_bridge_client.py and test_tools_bridge.py.
            Assert.Contains("no longer open", response.Error!, StringComparison.OrdinalIgnoreCase);
            Assert.StartsWith("document no longer open", response.Error!, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void AnUnauthorizedRequestNeverAsksSolidworksAboutTheDocument()
    {
        int asked = 0;
        var inner = new RecordingDispatcher
        {
            Status = BridgeStatus.Error,
            Failure = SwBridgeDispatcher.UnauthorizedError,
        };
        var presence = new DocumentPresenceDispatcher(inner, () => { asked++; return true; });

        BridgeResponse response = presence.Dispatch(
            BridgeCodec.ReadRequest(Line("1", "ping", "wrong")));

        Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
        Assert.Equal(0, asked);
    }

    [Fact]
    public void AnOpenDocumentLeavesTheOriginalErrorAlone()
    {
        var inner = new RecordingDispatcher { Failure = "\"view\" must be one of fit, iso; got 'sideways'." };
        var presence = new DocumentPresenceDispatcher(inner, () => true);

        BridgeResponse response = presence.Dispatch(
            BridgeCodec.ReadRequest(Line("1", "capture", ReviewSecret)));

        Assert.Equal("\"view\" must be one of fit, iso; got 'sideways'.", response.Error);
    }

    // ---- the circuit ---------------------------------------------------------------------------

    [Fact]
    public void CircuitOpenPropagatesToTheClient()
    {
        var log = new StringWriter();
        using (var world = new ScopedWorld(log))
        {
            world.CaptureView.SelectFailure = new CircuitOpenError(
                "SOLIDWORKS failed 3 times in a row; the circuit is open.");

            BridgeResponse response = world.Server.Answer(
                Line("1", "capture", ReviewSecret, "{\"persist_ref\":\"cGVyc2lzdA==\"}"));

            Assert.Equal(BridgeStatus.CircuitOpen, response.Status);
            Assert.Contains("circuit is open", response.Error!);
            Assert.Contains("circuit_open", log.ToString());
        }
    }

    // ---- the pipe's own access control -----------------------------------------------------------

    [Fact]
    public void ThePipeDaclGrantsTheCurrentUserAndNobodyElse()
    {
        using (var app = new FakeAppThread())
        using (InProcPipeServer server = Server(new RecordingDispatcher(), app))
        {
            server.Start();

            PipeSecurity security = server.ReadPipeSecurity();
            AuthorizationRuleCollection rules = security.GetAccessRules(
                includeExplicit: true, includeInherited: true, targetType: typeof(SecurityIdentifier));

            SecurityIdentifier me;
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
            {
                me = identity.User!;
            }

            PipeAccessRule rule = Assert.IsType<PipeAccessRule>(Assert.Single(rules.Cast<AuthorizationRule>()));
            Assert.Equal(AccessControlType.Allow, rule.AccessControlType);
            Assert.Equal(me, (SecurityIdentifier)rule.IdentityReference);
            Assert.Equal(
                PipeAccessRights.ReadWrite,
                rule.PipeAccessRights & PipeAccessRights.ReadWrite);

            // The GUID in the name is not an access control (contracts/README.md): no rule
            // for Everyone, Authenticated Users, or anyone else at all.
            Assert.DoesNotContain(
                rules.Cast<AuthorizationRule>(),
                other => !me.Equals(other.IdentityReference));
        }
    }

    [Fact]
    public void ThePipeNameCarriesTheDocumentedShape()
    {
        using (var app = new FakeAppThread())
        {
            string name = PipeNames.NewToolServiceName();
            using (InProcPipeServer server = Server(new RecordingDispatcher(), app, pipeName: name))
            {
                Assert.StartsWith("swreview-", server.PipeName);
                Assert.DoesNotContain(" ", server.PipeName);
            }
        }
    }

    // ---- shutdown -------------------------------------------------------------------------------

    [Fact]
    public void DisposeStopsTheListener()
    {
        using (var app = new FakeAppThread())
        {
            InProcPipeServer server = Server(new RecordingDispatcher(), app);
            server.Start();

            using (PipeClient client = Connect(server.PipeName))
            {
                client.Send(Line("1", "ping", ReviewSecret));
                Assert.Equal("ok", client.Receive().Status);
            }

            server.Dispose();

            using (var late = new NamedPipeClientStream(".", server.PipeName, PipeDirection.InOut))
            {
                Assert.Throws<TimeoutException>(() => late.Connect(500));
            }
        }
    }

    [Fact]
    public void DisposeAnswersTheRequestInFlightAndEveryRequestQueuedBehindIt()
    {
        using (var app = new FakeAppThread(manual: true))
        {
            InProcPipeServer server = Server(new RecordingDispatcher(), app);
            var answers = new ConcurrentDictionary<string, BridgeResponse>();

            Thread first = Ask(server, answers, "1");
            Until(() => app.Posted == 1, "the first request reached the application thread");
            Thread second = Ask(server, answers, "2");
            Until(() => server.QueuedRequests == 1, "the second request was queued");

            // SOLIDWORKS is unloading the add-in and the application thread never answers.
            server.Dispose();

            Assert.True(first.Join(TimeSpan.FromSeconds(10)), "the in-flight request never returned");
            Assert.True(second.Join(TimeSpan.FromSeconds(10)), "the queued request never returned");

            Assert.Equal(2, answers.Count);
            Assert.All(answers.Values, response => Assert.Equal("error", response.Status));
            Assert.All(answers.Values, response => Assert.Equal(InProcPipeServer.ShuttingDownError, response.Error));
        }
    }

    [Fact]
    public void ARequestPostedAsDisposeCancelsIsAbandonedRatherThanLeftOnTheInvokeTimeout()
    {
        // The window Dispose cannot see: Execute has already passed its shutdown check and is
        // inside Post, so the call it is about to wait on does not exist yet when Dispose
        // abandons whatever is in flight. Without the re-check after Post, this request waits
        // the whole invoke timeout on an application thread that is being torn down, and the
        // thread blocked in Answer waits with it.
        using (var app = new GatedInvoker())
        {
            InProcPipeServer server = Server(new RecordingDispatcher(), app, TimeSpan.FromSeconds(3));
            server.Start();

            var answers = new ConcurrentDictionary<string, BridgeResponse>();
            Thread asking = Ask(server, answers, "1");
            Assert.True(
                app.Entered.Wait(TimeSpan.FromSeconds(10)),
                "the request never reached the application thread");

            var disposing = new Thread(server.Dispose) { IsBackground = true, Name = "disposing" };
            disposing.Start();

            // A refused connection proves Dispose has cancelled and has already abandoned what
            // was in flight - both happen before the listener is closed - so the call below is
            // posted into a server that is already stopping.
            Until(() => !CanConnect(server.PipeName), "dispose closed the listener");

            app.Release();

            Assert.True(
                asking.Join(TimeSpan.FromSeconds(1.5)),
                "the request posted as dispose cancelled waited for the invoke timeout");
            Assert.Equal("error", answers["1"].Status);
            Assert.Equal(InProcPipeServer.ShuttingDownError, answers["1"].Error);

            // The delegate the application thread eventually runs, long after the answer: it
            // must publish nothing and throw nothing.
            app.RunPending();
            Assert.True(disposing.Join(TimeSpan.FromSeconds(10)), "dispose never returned");
        }
    }

    [Fact]
    public void ARequestAfterDisposeIsAnsweredRatherThanThrown()
    {
        using (var app = new FakeAppThread())
        {
            InProcPipeServer server = Server(new RecordingDispatcher(), app);
            server.Dispose();

            BridgeResponse response = server.Answer(Line("1", "ping", ReviewSecret));

            Assert.Equal("error", response.Status);
            Assert.Equal(InProcPipeServer.ShuttingDownError, response.Error);
        }
    }

    [Fact]
    public void DisposeIsIdempotent()
    {
        using (var app = new FakeAppThread())
        {
            InProcPipeServer server = Server(new RecordingDispatcher(), app);
            server.Start();
            server.Dispose();
            server.Dispose();
        }
    }

    // ---- a line that is not a request -------------------------------------------------------------

    [Fact]
    public void AMalformedLineIsAnsweredWithAnEmptyIdAndTheListenerSurvives()
    {
        using (var app = new FakeAppThread())
        using (InProcPipeServer server = Server(new RecordingDispatcher(), app))
        {
            server.Start();
            using (PipeClient client = Connect(server.PipeName))
            {
                client.Send("{not json");
                BridgeAnswer answer = client.Receive();
                Assert.Equal(string.Empty, answer.Id);
                Assert.Equal("error", answer.Status);

                client.Send(Line("2", "ping", ReviewSecret));
                Assert.Equal("2", client.Receive().Id);
            }
        }
    }

    // ---- the per-request log ------------------------------------------------------------------------

    [Fact]
    public void TheLogRecordsTheCommandTheElapsedTimeAndTheMembersTheGateSaw()
    {
        var log = new StringWriter();
        var recorder = new SwGateRecorder();
        var gate = new SwGate { Observer = recorder };
        var inner = new RecordingDispatcher
        {
            Before = () =>
            {
                gate.Call("GetOpenDocumentByName", () => 0);
                gate.Call("ShowNamedView2", () => 0);
                gate.Call("GetOpenDocumentByName", () => 0);
            },
        };

        var logger = new ToolServiceRequestLogger(inner, recorder, log.Write);
        BridgeResponse response = logger.Dispatch(BridgeCodec.ReadRequest(Line("7", "capture", ReviewSecret)));

        Assert.Equal("ok", response.Status);

        string written = log.ToString();
        Assert.Contains("id=7", written);
        Assert.Contains("command=capture", written);
        Assert.Contains("status=ok", written);
        Assert.Contains("elapsed_ms=", written);

        // Distinct, in first-seen order: a per-call line would be tens of thousands of writes
        // on the SOLIDWORKS thread (data-model.md, ToolService).
        Assert.Contains("gated=GetOpenDocumentByName,ShowNamedView2", written);
        Assert.DoesNotContain("refused=", written);
        Assert.DoesNotContain(ReviewSecret, written);
        Assert.Equal(1, written.Count(c => c == '\n'));
    }

    [Fact]
    public void TheLogRecordsAMutatingCallRefusal()
    {
        var log = new StringWriter();
        var recorder = new SwGateRecorder();
        var gate = new SwGate { Observer = recorder };
        var inner = new RecordingDispatcher
        {
            Before = () =>
            {
                try
                {
                    gate.Call("Save3", () => 0);
                }
                catch (MutatingCallError)
                {
                    // The dispatcher turns it into an error response; the log is what SC-004
                    // is audited from, so the refusal has to be visible there.
                }
            },
            Status = BridgeStatus.Error,
            Failure = "Save3 modifies the model.",
        };

        var logger = new ToolServiceRequestLogger(inner, recorder, log.Write);
        logger.Dispatch(BridgeCodec.ReadRequest(Line("8", "capture", ReviewSecret)));

        string written = log.ToString();
        Assert.Contains("refused=Save3", written);
        Assert.Contains("gated=Save3", written);
        Assert.Contains("status=error", written);
    }

    [Fact]
    public void MembersGatedOutsideARequestAreNotAttributedToTheNextOne()
    {
        var log = new StringWriter();
        var recorder = new SwGateRecorder();
        var gate = new SwGate { Observer = recorder };

        // T048 gives `entity.show` the tool service's own scope, so Show in SOLIDWORKS now runs
        // through this gate too - on the same application thread, between requests. Those calls
        // belong to no request, and the log is the artifact SC-004 is audited from: a `capture`
        // line that claims it touched SelectByID2 is a false record of what that request did.
        gate.Call("ClearSelection2", () => 0);
        gate.Call("SelectByID2", () => 0);

        var inner = new RecordingDispatcher { Before = () => gate.Call("ShowNamedView2", () => 0) };
        var logger = new ToolServiceRequestLogger(inner, recorder, log.Write);
        logger.Dispatch(BridgeCodec.ReadRequest(Line("9", "capture", ReviewSecret)));

        string written = log.ToString();
        Assert.Contains("gated=ShowNamedView2", written);
        Assert.DoesNotContain("SelectByID2", written);
        Assert.DoesNotContain("ClearSelection2", written);
    }

    [Fact]
    public void TheGateRecorderStartsEachRequestEmpty()
    {
        var recorder = new SwGateRecorder();
        var gate = new SwGate { Observer = recorder };

        gate.Call("ActiveDoc", () => 0);
        SwGateActivity first = recorder.Drain();
        SwGateActivity second = recorder.Drain();

        Assert.Equal(new[] { "ActiveDoc" }, first.GatedMembers.ToArray());
        Assert.Empty(second.GatedMembers);
        Assert.Empty(second.RefusedMembers);
    }

    [Fact]
    public void AGateWithNoObserverStillWorks()
    {
        var gate = new SwGate();
        Assert.Equal(7, gate.Call("GetType", () => 7));
        Assert.Throws<MutatingCallError>(() => { gate.Call("Save3", () => 7); });
    }

    // ---- helpers ---------------------------------------------------------------------------------------

    private static InProcPipeServer Server(
        IBridgeDispatcher dispatcher,
        IAppThreadInvoker invoker,
        TimeSpan? timeout = null,
        Action<string>? log = null,
        string? pipeName = null)
    {
        return new InProcPipeServer(
            new InProcPipeServerOptions(pipeName ?? PipeNames.NewToolServiceName(), dispatcher, invoker)
            {
                InvokeTimeout = timeout ?? TimeSpan.FromSeconds(30),
                Log = log,
            });
    }

    private static string Line(string id, string command, string? secret, string? paramsJson = null)
    {
        var text = new StringBuilder("{\"id\":\"").Append(id).Append("\",\"command\":\"").Append(command).Append('"');
        if (secret != null)
        {
            text.Append(",\"secret\":\"").Append(secret).Append('"');
        }

        if (paramsJson != null)
        {
            text.Append(",\"params\":").Append(paramsJson);
        }

        return text.Append('}').ToString();
    }

    /// <summary>Calls <see cref="InProcPipeServer.Answer"/> on its own thread and records the answer.</summary>
    private static Thread Ask(
        InProcPipeServer server, ConcurrentDictionary<string, BridgeResponse> answers, string id)
    {
        var thread = new Thread(() =>
        {
            BridgeResponse response = server.Answer(Line(id, "ping", ReviewSecret));
            answers[id] = response;
        })
        {
            IsBackground = true,
            Name = "ask-" + id,
        };

        thread.Start();
        return thread;
    }

    private static void Until(Func<bool> condition, string what, int timeoutMs = 10000)
    {
        var clock = Stopwatch.StartNew();
        while (clock.ElapsedMilliseconds < timeoutMs)
        {
            if (condition())
            {
                return;
            }

            Thread.Sleep(5);
        }

        throw new TimeoutException("Timed out waiting until " + what + ".");
    }

    private static PipeClient Connect(string pipeName) => new PipeClient(pipeName);

    /// <summary>Whether the pipe is still listening; false once Dispose closed the instance.</summary>
    private static bool CanConnect(string pipeName)
    {
        using (var client = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut))
        {
            try
            {
                client.Connect(100);
                return true;
            }
            catch (TimeoutException)
            {
                return false;
            }
            catch (IOException)
            {
                return false;
            }
        }
    }

    /// <summary>One response line, read back.</summary>
    private sealed class BridgeAnswer
    {
        public BridgeAnswer(string id, string status, string? error)
        {
            Id = id;
            Status = status;
            Error = error;
        }

        public string Id { get; }

        public string Status { get; }

        public string? Error { get; }
    }

    private sealed class PipeClient : IDisposable
    {
        private readonly NamedPipeClientStream _pipe;
        private readonly StreamWriter _writer;
        private readonly StreamReader _reader;

        public PipeClient(string pipeName)
        {
            var encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
            _pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut);
            _pipe.Connect(10000);
            _writer = new StreamWriter(_pipe, encoding) { AutoFlush = true, NewLine = "\n" };
            _reader = new StreamReader(_pipe, encoding, detectEncodingFromByteOrderMarks: false);
        }

        public void Send(string line) => _writer.WriteLine(line);

        public BridgeAnswer Receive()
        {
            string? line = _reader.ReadLine();
            Assert.NotNull(line);

            using (System.Text.Json.JsonDocument document = System.Text.Json.JsonDocument.Parse(line!))
            {
                System.Text.Json.JsonElement root = document.RootElement;
                System.Text.Json.JsonElement error;
                return new BridgeAnswer(
                    root.GetProperty("id").GetString()!,
                    root.GetProperty("status").GetString()!,
                    root.TryGetProperty("error", out error)
                        && error.ValueKind == System.Text.Json.JsonValueKind.String
                            ? error.GetString()
                            : null);
            }
        }

        public void Dispose()
        {
            _pipe.Dispose();
        }
    }

    /// <summary>
    /// Stands in for the thread SOLIDWORKS runs on: one thread, a queue, and - in manual mode -
    /// a permit per call, so a test can hold the application thread the way a modal dialog does.
    /// </summary>
    /// <summary>
    /// An application thread whose <c>Post</c> can be held open, so a request can be parked
    /// exactly between the server's shutdown check and the call it posts. Nothing runs until
    /// <see cref="RunPending"/> is called, which is what a modal dialog looks like from here.
    /// </summary>
    private sealed class GatedInvoker : IAppThreadInvoker, IDisposable
    {
        private readonly ManualResetEventSlim _entered = new ManualResetEventSlim(false);
        private readonly ManualResetEventSlim _release = new ManualResetEventSlim(false);
        private readonly List<Action> _pending = new List<Action>();

        public bool CanInvoke => true;

        /// <summary>Set once a call has reached <see cref="Post"/>.</summary>
        public ManualResetEventSlim Entered => _entered;

        public void Post(Action work)
        {
            lock (_pending)
            {
                _pending.Add(work);
            }

            _entered.Set();
            _release.Wait(TimeSpan.FromSeconds(20));
        }

        /// <summary>Lets the posting thread out of <see cref="Post"/>.</summary>
        public void Release() => _release.Set();

        /// <summary>Runs what was posted, the way the application thread eventually would.</summary>
        public void RunPending()
        {
            Action[] pending;
            lock (_pending)
            {
                pending = _pending.ToArray();
                _pending.Clear();
            }

            foreach (Action work in pending)
            {
                work();
            }
        }

        public void Dispose()
        {
            _release.Set();
            _entered.Dispose();
            _release.Dispose();
        }
    }

    private sealed class FakeAppThread : IAppThreadInvoker, IDisposable
    {
        private readonly BlockingCollection<Action> _queue = new BlockingCollection<Action>();
        private readonly SemaphoreSlim? _permits;
        private readonly ManualResetEventSlim _started = new ManualResetEventSlim(false);
        private readonly Thread _thread;
        private readonly List<int> _postThreads = new List<int>();
        private int _posted;
        private int _ran;

        public FakeAppThread(bool manual = false)
        {
            _permits = manual ? new SemaphoreSlim(0) : null;
            _thread = new Thread(Loop) { IsBackground = true, Name = "fake-solidworks-app-thread" };
            _thread.Start();
            _started.Wait(TimeSpan.FromSeconds(10));
        }

        /// <summary>Whether the pane control would accept an invoke.</summary>
        public bool CanInvokeValue { get; set; } = true;

        /// <summary>What <c>BeginInvoke</c> throws, if anything.</summary>
        public Exception? PostFailure { get; set; }

        public int ThreadId { get; private set; }

        /// <summary>How many calls have been handed to the application thread.</summary>
        public int Posted => Volatile.Read(ref _posted);

        /// <summary>How many have actually run there.</summary>
        public int Ran => Volatile.Read(ref _ran);

        public IReadOnlyList<int> PostThreads
        {
            get
            {
                lock (_postThreads)
                {
                    return _postThreads.ToArray();
                }
            }
        }

        bool IAppThreadInvoker.CanInvoke => CanInvokeValue;

        void IAppThreadInvoker.Post(Action work)
        {
            lock (_postThreads)
            {
                _postThreads.Add(Thread.CurrentThread.ManagedThreadId);
            }

            if (PostFailure != null)
            {
                throw PostFailure;
            }

            Interlocked.Increment(ref _posted);
            _queue.Add(work);
        }

        /// <summary>Lets one held call run (manual mode only).</summary>
        public void ReleaseOne() => _permits!.Release();

        public void Dispose()
        {
            _queue.CompleteAdding();
            _permits?.Release(1000);
            _thread.Join(TimeSpan.FromSeconds(5));
            _started.Dispose();
            _permits?.Dispose();
            _queue.Dispose();
        }

        private void Loop()
        {
            ThreadId = Thread.CurrentThread.ManagedThreadId;
            _started.Set();

            foreach (Action work in _queue.GetConsumingEnumerable())
            {
                _permits?.Wait();
                try
                {
                    work();
                }
                finally
                {
                    Interlocked.Increment(ref _ran);
                }
            }
        }
    }

    /// <summary>A dispatcher that records where and in what order it ran.</summary>
    private sealed class RecordingDispatcher : IBridgeDispatcher
    {
        private readonly List<string> _ids = new List<string>();
        private readonly List<int> _threads = new List<int>();
        private int _concurrent;
        private int _maxConcurrent;

        /// <summary>Runs on the application thread before the answer is built.</summary>
        public Action? Before { get; set; }

        public string Status { get; set; } = BridgeStatus.Ok;

        /// <summary>When set, the response is an error carrying this text.</summary>
        public string? Failure { get; set; }

        public IReadOnlyList<string> DispatchedIds
        {
            get
            {
                lock (_ids)
                {
                    return _ids.ToArray();
                }
            }
        }

        public IReadOnlyList<int> DispatchThreads
        {
            get
            {
                lock (_ids)
                {
                    return _threads.ToArray();
                }
            }
        }

        public int MaxConcurrent => Volatile.Read(ref _maxConcurrent);

        public BridgeResponse Dispatch(BridgeRequest request)
        {
            int now = Interlocked.Increment(ref _concurrent);
            int seen = Volatile.Read(ref _maxConcurrent);
            while (now > seen && Interlocked.CompareExchange(ref _maxConcurrent, now, seen) != seen)
            {
                seen = Volatile.Read(ref _maxConcurrent);
            }

            try
            {
                lock (_ids)
                {
                    _ids.Add(request.Id);
                    _threads.Add(Thread.CurrentThread.ManagedThreadId);
                }

                Before?.Invoke();

                if (Failure != null)
                {
                    return Status == BridgeStatus.CircuitOpen
                        ? BridgeResponse.CircuitOpen(request.Id, Failure)
                        : BridgeResponse.Failed(request.Id, Failure);
                }

                return BridgeResponse.Ok(request.Id, new { pong = true });
            }
            finally
            {
                Interlocked.Decrement(ref _concurrent);
            }
        }
    }

    /// <summary>
    /// The real <see cref="SwBridgeDispatcher"/> behind the real <see cref="ScopedSecretPolicy"/>,
    /// with SOLIDWORKS faked out: the secret scoping is only worth asserting against the
    /// dispatcher that actually enforces it.
    /// </summary>
    private sealed class ScopedWorld : IDisposable
    {
        private readonly FakeAppThread _app;
        private readonly string _captureDirectory;

        public ScopedWorld(TextWriter log)
        {
            _captureDirectory = Path.Combine(
                Path.GetTempPath(), "swreview-toolservice-tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_captureDirectory);

            CaptureView = new FakeCaptureView();
            Interference = new FakeInterferenceSource();

            var services = new BridgeServices(
                CaptureView,
                new FakeMeasureSource(),
                Interference,
                Index(),
                _captureDirectory)
            {
                SwVersion = "32.5.0",
                DocumentPath = @"C:\work\bracket-assy.SLDASM",
                Configuration = "Default",
            };

            Recorder = new SwGateRecorder();
            var dispatcher = new SwBridgeDispatcher(
                services, new ScopedSecretPolicy(ReviewSecret, ChatSecret, RemodelSecret));
            var logger = new ToolServiceRequestLogger(dispatcher, Recorder, log.Write);

            _app = new FakeAppThread();
            Server = new InProcPipeServer(
                new InProcPipeServerOptions(PipeNames.NewToolServiceName(), logger, _app)
                {
                    InvokeTimeout = TimeSpan.FromSeconds(30),
                    Log = text => log.Write(text + System.Environment.NewLine),
                });
        }

        public InProcPipeServer Server { get; }

        public FakeCaptureView CaptureView { get; }

        public FakeInterferenceSource Interference { get; }

        public SwGateRecorder Recorder { get; }

        public void Dispose()
        {
            Server.Dispose();
            _app.Dispose();

            try
            {
                Directory.Delete(_captureDirectory, recursive: true);
            }
            catch (IOException)
            {
            }
        }

        private static ComponentIndex Index()
        {
            var tree = new ComponentTreeResult { ActiveConfiguration = "Default" };
            tree.Nodes.Add(new ComponentNode
            {
                Key = "bracket-assy-1",
                DocumentPath = @"C:\work\bracket-assy.SLDASM",
            });

            return new ComponentIndex(tree);
        }
    }

    private sealed class FakeCaptureView : ICaptureView
    {
        public int Saved { get; private set; }

        public Exception? SelectFailure { get; set; }

        public bool TrySelect(string persistRef, string? scopeDocumentPath, out string reason)
        {
            if (SelectFailure != null)
            {
                throw SelectFailure;
            }

            reason = string.Empty;
            return true;
        }

        public IReadOnlyList<string> SelectedComponentIds() => new[] { "cmp:0001" };

        public void ZoomToSelection()
        {
        }

        public void ShowNamedView(string namedView)
        {
        }

        public bool SaveImage(string pngPath)
        {
            Saved++;
            File.WriteAllBytes(pngPath, new byte[] { 0x89, 0x50, 0x4E, 0x47 });
            return true;
        }
    }

    private sealed class FakeMeasureSource : IMeasureSource
    {
        public MeasureReading Measure(string persistRefA, string? scopeA, string persistRefB, string? scopeB) =>
            throw new NotSupportedException("no measure source in this test");
    }

    private sealed class FakeInterferenceSource : IInterferenceSource
    {
        public int Opened { get; private set; }

        public IInterferenceDetector Open()
        {
            Opened++;
            throw new NotSupportedException("no interference detector in this test");
        }
    }
}
