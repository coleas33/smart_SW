using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Remodel.Seat;
using SwReview.AddIn.Review;
using SwReview.AddIn.ToolService;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Measure;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004's build order, lanes D, E and F integrated: a Remodel <b>Plan</b> driven end to end
/// over the fakes, through every piece the seat adapter added, and a <b>Start</b> refused by the
/// switch. SOLIDWORKS is never started; what a real seat answers is the sitting's.
///
/// Everything on the add-in's side is the product's own code, wired the way <c>SwReviewAddIn</c>
/// wires it: the Remodel host built with its shipped constructor, so with the shipped Start switch
/// (T172); the <see cref="BackendRemodelPipeline"/> with the add-in's own bind
/// (<see cref="SwReviewAddIn.BindRemodelRun(ToolServiceGate, string)"/>, T158) and the pane's
/// <see cref="SwRemodelSeat"/> (T159's activation); a real <see cref="ToolServiceGate"/> over a
/// real <see cref="ToolServiceHost"/> - its dispatcher, secret policy, remodel gate, request chain
/// and pipe - whose bridge is handed the production seat through <c>ToolServiceHost.RemodelSeatFor</c>
/// (T157), so the probe source (T154), the copy adapter (T153) and the extractor-side seat (T155)
/// answer every <c>remodel.*</c> command, over <see cref="StandInSolidworks"/>; and the session
/// endings wired to the host as the add-in wires them (T167).
///
/// Three things are stand-ins: SOLIDWORKS; the extractor's dump (<see cref="FakeRemodelDump"/>);
/// and the Python backend, played by <see cref="BackendRelay"/>, which sends the bridge exactly the
/// commands the backend's routes send (`/remodel/probe`: <c>remodel.probe_scope</c>;
/// `/remodel/open`: <c>remodel.open</c> then <c>remodel.geometry</c>; `/remodel/close`:
/// <c>remodel.close</c>) over the tool service's own pipe with the remodel secret, and files
/// <c>plan.json</c> as `/remodel/plan` does.
/// </summary>
public sealed class RemodelPlanEndToEndTests
{
    /// <summary>
    /// Plan: probe, bind, open, geometry, activation, dump and plan, in that order, each through the
    /// piece built for it; the engineer's part only ever read; the copy opened once at its own path,
    /// tagged and holding the four settings. Start: refused by the switch in the host's words with
    /// nothing called - no backend run - and, as the backstop, a change command sent straight to the
    /// bridge refused before anything is written. Discard: the session ends through the routine
    /// (copy closed unsaved, tag off, settings back), the page is told nothing because nothing was
    /// left, and <c>copy/</c> is deleted.
    /// </summary>
    [Fact]
    public void APlanRunsThroughTheSeatAdapterStartIsRefusedByTheSwitchAndDiscardEndsTheSession()
    {
        using (var world = new PlanWorld())
        {
            byte[] sourceBefore = File.ReadAllBytes(world.SourcePath);

            // T157: the in-process bridge carries the production seat, and the gate reads it.
            Assert.Equal(RemodelAvailability.Available, world.Gate.RemodelCapability);
            Assert.IsType<SwRemodelBridgeSeat>(world.Services!.RemodelSeat);

            world.Receive("remodel.plan", "p1");

            JsonElement planned = world.Reply("remodel.planned", "p1");
            string runDirectory = planned.GetProperty("run_dir").GetString()!;
            string copyPath = Path.GetFullPath(RemodelCopy.CopyPathFor(runDirectory, world.SourcePath));

            // The order a Plan takes, across the backend, the bind, the pane's seat and the dump.
            Assert.Equal(
                new[] { "backend:probe", "bind", "backend:open", "backend:geometry", "seat", "dump", "backend:plan" },
                world.Log);

            // T154: the probe read the engineer's part, and only read it.
            Assert.Equal(sourceBefore, File.ReadAllBytes(world.SourcePath));
            Assert.All(world.Solidworks.Source.AllMembers(), member => Assert.Contains(member, StandInSolidworks.SourceReads));
            Assert.DoesNotContain(
                world.Solidworks.Application.Calls,
                call => call.Member != "GetOpenDocumentByName" && call.Arguments.Contains(world.SourcePath));

            // T161, through the probe: the feature types as read, one per feature.
            Assert.Equal(new[] { "Extrusion", "Extrusion" }, world.Backend.ProbedSignals!.FeatureTypeNames);

            // T158 and T155: the bound folder's copy, opened once at its own path, tagged with the run.
            Assert.Equal(copyPath, world.Solidworks.CopyPath);
            Assert.True(File.Exists(copyPath));
            Assert.Equal(new object?[] { copyPath }, Assert.Single(world.Solidworks.Application.Calls, call => call.Member == "GetOpenDocSpec").Arguments);
            Assert.Single(world.Solidworks.Application.Calls, call => call.Member == "OpenDoc7");
            Assert.Equal(Path.GetFileName(runDirectory), world.Solidworks.Tag);
            Assert.Equal(
                new[] { new object?[] { true } },
                world.Solidworks.Application.Calls.Where(call => call.Member == "set_CommandInProgress").Select(call => call.Arguments));

            // T153: the geometry baseline was read off the copy's own mass property.
            Assert.Contains("get_Volume", world.Solidworks.MassProperty.Members);

            // T159: the copy was made the active document by its title, with no rebuild and no
            // second open, before the dump read it.
            Assert.Equal(
                Path.GetFileName(copyPath),
                Assert.Single(world.Solidworks.Application.Calls, call => call.Member == "ActivateDoc3").Arguments[0]);
            Assert.True(File.Exists(Path.Combine(runDirectory, "package-before.json")));

            // Start: the switch refuses it in the host's words, and nothing reaches the backend.
            world.Receive("remodel.start", "s1", new { run_dir = runDirectory });

            JsonElement refused = world.Reply("error", "s1");
            Assert.Equal("StartNotValidated", refused.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.StartNotValidatedMessage, refused.GetProperty("message").GetString());
            Assert.Equal(0, world.Backend.StartRuns);
            Assert.Empty(world.Posted("remodel.started"));

            // The bridge's backstop, reached the way a backend that skipped the pane would: a change
            // command answers `start_not_validated` before the seat is asked anything.
            PipeReply rename = world.Remodel(
                RemodelCommands.Rename,
                new { persist_ref = PersistRefCodec.Encode(StandInSolidworks.CutRef), new_name = "Cut-Pocket1" });
            Assert.Equal(RemodelErrorCodes.StartNotValidated, rename.ErrorCode);
            Assert.DoesNotContain("set_Name", world.Solidworks.Cut.Members);

            // Discard: remodel.close runs the end-of-session routine, which leaves nothing, so the
            // page hears no error; the copy is closed unsaved and its folder deleted.
            int postedBeforeDiscard = world.PostedCount;
            world.Receive("remodel.discard_copy", "d1", new { run_dir = runDirectory });

            world.Reply("ok", "d1");
            Assert.False(world.Solidworks.CopyOpen);
            Assert.Null(world.Solidworks.Tag);
            Assert.DoesNotContain("Save3", world.Solidworks.Copy.Document.Members);
            Assert.Equal(
                new[] { new object?[] { true }, new object?[] { false } },
                world.Solidworks.Application.Calls.Where(call => call.Member == "set_CommandInProgress").Select(call => call.Arguments));
            Assert.False(Directory.Exists(Path.Combine(runDirectory, "copy")));
            Assert.DoesNotContain(
                world.PostedSince(postedBeforeDiscard),
                message => message.GetProperty("type").GetString() == "status"
                    && message.GetProperty("payload").GetProperty("stage").GetString() == "error");
        }
    }

    /// <summary>
    /// T167 end to end: the tool service stops while a plan waits - a re-attach or an unload - and
    /// the teardown runs the routine on the application thread before the pipe closes. Here the
    /// three toggles cannot be put back, so the page is told the plan is lost (decision 24A) and
    /// then, in one status error, which settings were left, by their Tools &gt; Options labels.
    /// </summary>
    [Fact]
    public void AToolServiceThatStopsWhileAPlanWaitsTellsThePageWhatItsTeardownLeft()
    {
        using (var world = new PlanWorld())
        {
            world.Receive("remodel.plan", "p1");
            world.Reply("remodel.planned", "p1");

            // Putting a toggle back (its original value, true) fails from here on.
            world.Solidworks.Application.Handle("SetUserPreferenceToggle", arguments =>
            {
                if ((bool)arguments[1]!)
                {
                    throw new InvalidOperationException("the setting could not be written");
                }

                return null;
            });
            int before = world.PostedCount;

            world.Gate.Dispose();

            List<JsonElement> told = world.PostedSince(before);
            JsonElement lost = Assert.Single(told, message => message.GetProperty("type").GetString() == "remodel.plan_lost");
            Assert.Equal(RemodelHost.PlanLostMessage, lost.GetProperty("payload").GetProperty("message").GetString());

            JsonElement status = Assert.Single(
                told,
                message => message.GetProperty("type").GetString() == "status"
                    && message.GetProperty("payload").GetProperty("stage").GetString() == "error");
            Assert.Equal(
                RemodelHost.SessionEndedMessage(RemodelSystemToggles.SuppressedToggles, false, true),
                status.GetProperty("payload").GetProperty("message").GetString());
            Assert.True(told.IndexOf(lost) < told.IndexOf(status), "the plan is told lost before what its teardown left");

            // The routine closed the copy unsaved and put CommandInProgress back, last.
            Assert.False(world.Solidworks.CopyOpen);
            Assert.Equal(
                new object?[] { false },
                world.Solidworks.Application.Calls.Last(call => call.Member == "set_CommandInProgress").Arguments);
        }
    }

    // ---- the world -------------------------------------------------------------------------------

    /// <summary>
    /// The add-in's Remodel side, wired as <c>SwReviewAddIn</c> wires it, over a real tool service
    /// on a fake application thread, with SOLIDWORKS, the dump and the Python backend as stand-ins.
    /// </summary>
    private sealed class PlanWorld : IDisposable
    {
        private static readonly DateTime Stamp = new DateTime(2026, 9, 27, 10, 0, 0, DateTimeKind.Local);

        private readonly string _root;
        private readonly List<string> _posted = new List<string>();
        private readonly RemodelHost _host;

        public PlanWorld()
        {
            _root = Path.Combine(Path.GetTempPath(), "swreview-plan-e2e", Guid.NewGuid().ToString("N"));
            RunRoot = Path.Combine(_root, "runs");
            SourcePath = Path.Combine(_root, "work", "bracket.SLDPRT");
            Directory.CreateDirectory(RunRoot);
            Directory.CreateDirectory(Path.GetDirectoryName(SourcePath)!);
            File.WriteAllText(SourcePath, "the engineer's part, as bytes the attestation hashes");

            Solidworks = new StandInSolidworks(SourcePath);
            Backend = new BackendRelay(Log);

            var options = new ToolServiceOptions(Solidworks.Application.Instance, App)
            {
                LogFolder = Path.Combine(_root, "logs"),
                CaptureDirectory = Path.Combine(_root, "captures"),
                InvokeTimeout = TimeSpan.FromSeconds(30),
                TeardownTimeout = TimeSpan.FromSeconds(30),

                // As SwReviewAddIn.CreateToolServiceGate sets it.
                RemodelSessionEnded = outcome => Host?.SessionEnded(outcome),
            };

            Gate = new ToolServiceGate(
                () => new PageDocument(SourcePath, "Default"),
                () => ToolServiceHost.Start(options, Attach),
                service => Host?.RefreshAvailability(),
                (message, failure) => throw new InvalidOperationException(message, failure),
                schedule: work => work());
            Gate.EnsureStarted();

            BridgeConfig? Bridge() => Gate.RemodelBridge;
            var endpoint = new BackendEndpoint(51234, "0FAKEtoken");
            PageDocument Document() => new PageDocument(SourcePath, "Default");

            _host = new RemodelHost(new RemodelHostOptions(new ListChannel(_posted), () => RunRoot)
            {
                Backend = () => endpoint,
                CurrentDocument = Document,
                RemodelAvailability = () => Gate.RemodelCapability,
                ToolServiceAttachment = () => Gate.Attachment,
                Pipeline = new BackendRemodelPipeline(
                    () => endpoint,
                    Bridge,
                    runDirectory =>
                    {
                        Log.Add("bind");
                        return SwReviewAddIn.BindRemodelRun(Gate, runDirectory);
                    },
                    Document,
                    new FakeRemodelDump(Log),
                    new SwRemodelSeat(Solidworks.Application.Instance, new LoggedThread(Log)),
                    Backend),
                LogFolder = () => Path.Combine(_root, "logs"),
                Now = () => Stamp,
                Schedule = work => work(),
            });
            Host = _host;
        }

        public FakeAppThread App { get; } = new FakeAppThread();

        public string RunRoot { get; }

        public string SourcePath { get; }

        public StandInSolidworks Solidworks { get; }

        public BackendRelay Backend { get; }

        public ToolServiceGate Gate { get; }

        public RemodelHost? Host { get; private set; }

        /// <summary>The bridge's services, as the attach built them.</summary>
        public BridgeServices? Services { get; private set; }

        /// <summary>One ordered log every stand-in on the add-in's side writes to.</summary>
        public List<string> Log { get; } = new List<string>();

        public int PostedCount
        {
            get
            {
                lock (_posted)
                {
                    return _posted.Count;
                }
            }
        }

        public void Receive(string type, string id, object? payload = null) =>
            _host.Receive(JsonSerializer.Serialize(new { type, id, payload = payload ?? new { } }));

        /// <summary>The reply of <paramref name="type"/> to <paramref name="id"/>'s message; there must be exactly one.</summary>
        public JsonElement Reply(string type, string id)
        {
            List<JsonElement> replies = PostedSince(0)
                .Where(message => message.GetProperty("type").GetString() == type
                    && message.TryGetProperty("id", out JsonElement replyTo)
                    && replyTo.GetString() == id)
                .ToList();
            Assert.True(replies.Count == 1, $"expected one '{type}' for '{id}', saw: {string.Join(" | ", PostedSince(0).Select(message => message.ToString()))}");
            return replies[0].GetProperty("payload");
        }

        public List<JsonElement> Posted(string type) =>
            PostedSince(0).Where(message => message.GetProperty("type").GetString() == type).ToList();

        public List<JsonElement> PostedSince(int index)
        {
            lock (_posted)
            {
                return _posted.Skip(index).Select(json => JsonDocument.Parse(json).RootElement.Clone()).ToList();
            }
        }

        /// <summary>A <c>remodel.*</c> command straight to the bridge, with the remodel secret.</summary>
        public PipeReply Remodel(string command, object parameters)
        {
            BridgeConfig bridge = Gate.RemodelBridge ?? throw new InvalidOperationException("no tool service is listening");
            return RemodelPipe.Send(bridge.Pipe, bridge.Secret, command, parameters);
        }

        public void Dispose()
        {
            Host = null;
            _host.Dispose();
            Gate.Dispose();
            App.Dispose();
            try
            {
                Directory.Delete(_root, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        /// <summary>
        /// The attach, on the application thread: what <c>ToolServiceHost.Attach</c> hands the bridge,
        /// with the COM walk's views as stand-ins and the seat built by the same line the add-in's
        /// attach calls.
        /// </summary>
        private ToolServiceHost.Attached Attach(
            ToolServiceOptions attachOptions, SwGateRecorder recorder, string captureDirectory, SwGate remodelGate)
        {
            var views = new InteropRecorder<ICaptureView>(typeof(IMeasureSource), typeof(IInterferenceSource));
            Services = new BridgeServices(
                views.Instance,
                views.As<IMeasureSource>(),
                views.As<IInterferenceSource>(),
                new ComponentIndex(new ComponentTreeResult()),
                captureDirectory)
            {
                DocumentPath = SourcePath,
                Configuration = "Default",
                RemodelGate = remodelGate,
                RemodelSeat = ToolServiceHost.RemodelSeatFor(attachOptions.SwApp),
            };

            return new ToolServiceHost.Attached(
                Services, new InteropRecorder<ISwSession>().Instance, SourcePath, "Default", 0, () => true);
        }
    }

    /// <summary>
    /// The Python backend's remodel routes, as far as a Plan and a Discard reach them: the bridge
    /// commands each route sends, over the tool service's pipe with the request's own remodel
    /// bridge, and the files it writes into the run folder. A refusal comes back as the backend's
    /// named refusal would, as a <see cref="BackendRequestException"/>.
    /// </summary>
    private sealed class BackendRelay : IRemodelBackend
    {
        private readonly List<string> _log;

        public BackendRelay(List<string> log) => _log = log;

        /// <summary>The scope signals the probe answered, as the backend read them.</summary>
        public ScopeSignals? ProbedSignals { get; private set; }

        public int StartRuns { get; private set; }

        public RemodelProbeReply Probe(RemodelProbeRequest request)
        {
            _log.Add("backend:probe");
            JsonElement result = Answered(request.Bridge, RemodelCommands.ProbeScope, new { source_path = request.SourcePath });
            ProbedSignals = JsonSerializer.Deserialize<ScopeSignals>(
                result.GetProperty("scope_signals").GetRawText(), BridgeCodec.Options)!;
            return new RemodelProbeReply(result.GetProperty("probe_id").GetString()!, ProbedSignals, new string[0]);
        }

        public RemodelOpenReply Open(RemodelOpenRequest request)
        {
            _log.Add("backend:open");
            string copyPath = RemodelCopy.CopyPathFor(request.RunDirectory, request.SourcePath);
            Answered(
                request.Bridge,
                RemodelCommands.Open,
                new
                {
                    source_path = request.SourcePath,
                    copy_path = copyPath,
                    run_id = Path.GetFileName(request.RunDirectory),
                    probe_id = request.ProbeId,
                });

            _log.Add("backend:geometry");
            Answered(request.Bridge, RemodelCommands.Geometry, new { });
            return new RemodelOpenReply(copyPath, 0, copyPresent: true);
        }

        public string Plan(string runDirectory)
        {
            _log.Add("backend:plan");
            Assert.True(File.Exists(Path.Combine(runDirectory, "package-before.json")), "the plan was asked for before the copy's dump was filed");
            File.WriteAllText(
                Path.Combine(runDirectory, "plan.json"),
                "{\"plan_schema\":\"1.0\",\"plan_revision\":1,\"state\":\"planned\"}");
            return "{\"moves\":0}";
        }

        public string StartRun(RemodelRunRequest request)
        {
            StartRuns++;
            throw new InvalidOperationException("a Start reached the backend while Start is switched off");
        }

        public RemodelRunStatus Status(string jobId) => throw new NotSupportedException();

        public RemodelEventPage Events(string jobId, int after) => throw new NotSupportedException();

        public void PackageAfter(string jobId, string packagePath) => throw new NotSupportedException();

        public void Stop(string jobId) => throw new NotSupportedException();

        public void Close(RemodelCloseRequest request)
        {
            _log.Add("backend:close");
            Answered(request.Bridge, RemodelCommands.Close, new { discard_copy = request.DiscardCopy });
        }

        private static JsonElement Answered(BridgeConfig bridge, string command, object parameters)
        {
            PipeReply reply = RemodelPipe.Send(bridge.Pipe, bridge.Secret, command, parameters);
            if (reply.Status != BridgeStatus.Ok)
            {
                throw new BackendRequestException(
                    "RunFolderFailed", command + " answered " + (reply.ErrorCode ?? "an error") + ": " + reply.Error, retryable: false);
            }

            return reply.Result;
        }
    }

    /// <summary>The pane's application thread, run inline, logging each hand-over.</summary>
    private sealed class LoggedThread : IApplicationThread
    {
        private readonly List<string> _log;

        public LoggedThread(List<string> log) => _log = log;

        public T Invoke<T>(Func<T> work)
        {
            _log.Add("seat");
            return work();
        }
    }

    /// <summary>The Remodel page, as the list of messages posted to it.</summary>
    private sealed class ListChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public ListChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json)
        {
            lock (_posted)
            {
                _posted.Add(json);
            }
        }
    }
}
