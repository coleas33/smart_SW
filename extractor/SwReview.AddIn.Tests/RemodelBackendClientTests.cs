using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T134d. <see cref="RemodelBackendClient"/> against a real HTTP server: the nine loopback
/// routes of `specs/004-resilient-remodeler/contracts/backend-remodel.md`, one test per route,
/// plus the refusal mapping.
///
/// An in-process <see cref="HttpListener"/> on 127.0.0.1 rather than a seam over the transport,
/// because the transport is what this class is. Everything that could be wrong here is on the
/// wire: the method, the path, whether the bearer token is in the header instead of the URL,
/// whether the bridge secret is in the body instead of the query string, and whether a 4xx
/// arrives as the backend's own `error_class` or as prose. A fake `Call` would assert that this
/// test's idea of an HTTP request matches the client's idea of one, which is no evidence at all.
///
/// The conventions are <see cref="BackendClient"/>'s, deliberately: same bearer header, same
/// <see cref="BackendRequestException"/> carrying `{error_class, message, retryable}`, same
/// `BackendUnavailable` for a backend that is not there. Two loopback clients in one add-in
/// that disagreed about what a failure looks like would be two error vocabularies on one page.
/// </summary>
public sealed class RemodelBackendClientTests
{
    private const string Token = "token-for-the-loopback-backend";

    private const string Pipe = "swreview-8f2c";

    private const string Secret = "remodel-secret-never-in-a-url";

    private const string RunDirectory = @"C:\SwReviewRuns\20260916-142201-bracket-remodel";

    private const string SourcePath = @"C:\work\bracket.SLDPRT";

    // ---- POST /remodel/probe ---------------------------------------------------------------

    [Fact]
    public void ProbePostsTheSourceAndTheBridgeAndReadsTheSignalsBack()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""probe_id"":""probe-7"",
                ""signals"":{""document_type"":1,""solid_body_count"":1,""is_weldment"":false,
                             ""external_reference_count"":0,""save_flag_dirty"":false},
                ""refusals"":[]}");

            RemodelProbeReply reply = backend.Client().Probe(
                new RemodelProbeRequest(SourcePath, "Default", new BridgeConfig(Pipe, Secret)));

            RecordedRequest request = backend.Only();
            Assert.Equal("POST", request.Method);
            Assert.Equal("/remodel/probe", request.Path);
            Assert.Equal("Bearer " + Token, request.Authorization);
            Assert.Equal(SourcePath, request.Text("source_path"));
            Assert.Equal("Default", request.Text("configuration"));
            Assert.Equal(Pipe, request.Text("bridge", "pipe"));
            Assert.Equal(Secret, request.Text("bridge", "secret"));

            Assert.Equal("probe-7", reply.ProbeId);
            Assert.Equal(1, reply.Signals.DocumentType);
            Assert.Equal(1, reply.Signals.SolidBodyCount);
            Assert.False(reply.Signals.IsWeldment);
            Assert.Empty(reply.Refusals);
        }
    }

    [Fact]
    public void ProbeCarriesEveryRefusalSentenceRatherThanTheFirst()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""probe_id"":""probe-8"",""signals"":{},
                ""refusals"":[""the part is a weldment"",""the part has 3 solid bodies""]}");

            RemodelProbeReply reply = backend.Client().Probe(
                new RemodelProbeRequest(SourcePath, null, new BridgeConfig(Pipe, Secret)));

            Assert.Equal(
                new[] { "the part is a weldment", "the part has 3 solid bodies" },
                reply.Refusals);

            // A signals object the backend did not fill is every signal unknown, never a pass:
            // the host refuses a null signal by name (data-model.md 4.1).
            Assert.Null(reply.Signals.DocumentType);
        }
    }

    // ---- POST /remodel/open ----------------------------------------------------------------

    [Fact]
    public void OpenSendsTheRunFolderTheSourceAndTheProbeIdAndReadsTheCopyBack()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(
                200,
                @"{""copy_path"":""C:\\runs\\copy\\bracket-RMS.SLDPRT"",
                   ""rebuild_error_count"":0,""copy_present"":true}");

            RemodelOpenReply reply = backend.Client().Open(new RemodelOpenRequest(
                RunDirectory, SourcePath, "Default", "probe-7", new BridgeConfig(Pipe, Secret)));

            RecordedRequest request = backend.Only();
            Assert.Equal("POST", request.Method);
            Assert.Equal("/remodel/open", request.Path);
            Assert.Equal(RunDirectory, request.Text("run_dir"));
            Assert.Equal(SourcePath, request.Text("source_path"));
            Assert.Equal("Default", request.Text("configuration"));
            Assert.Equal("probe-7", request.Text("probe_id"));
            Assert.Equal(Secret, request.Text("bridge", "secret"));

            Assert.Equal(@"C:\runs\copy\bracket-RMS.SLDPRT", reply.CopyPath);
            Assert.Equal(0, reply.RebuildErrorCount);
            Assert.True(reply.CopyPresent);
        }
    }

    /// <summary>
    /// The one refusal that is a 200: the bridge has already deleted the copy and closed the
    /// document, so the count comes back with `copy_present: false` and the host takes its
    /// existing `PreexistingRebuildErrors` path (wiring brief, `POST /remodel/open`).
    /// </summary>
    [Fact]
    public void OpenReportsPreexistingRebuildErrorsAsACountWithNoCopy()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(
                200,
                @"{""copy_path"":""C:\\runs\\copy\\bracket-RMS.SLDPRT"",
                   ""rebuild_error_count"":4,""copy_present"":false}");

            RemodelOpenReply reply = backend.Client().Open(new RemodelOpenRequest(
                RunDirectory, SourcePath, null, "probe-7", new BridgeConfig(Pipe, Secret)));

            Assert.Equal(4, reply.RebuildErrorCount);
            Assert.False(reply.CopyPresent);
        }
    }

    /// <summary>
    /// A count that is absent is <b>unknown</b>, not zero. Reading "no errors" into an
    /// unanswered call is how a run gets started on a part that is already broken.
    /// </summary>
    [Fact]
    public void OpenReportsARebuildCountItWasNotGivenAsUnknown()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""copy_path"":""C:\\runs\\copy\\bracket-RMS.SLDPRT"",
                                  ""rebuild_error_count"":null,""copy_present"":true}");

            RemodelOpenReply reply = backend.Client().Open(new RemodelOpenRequest(
                RunDirectory, SourcePath, null, "probe-7", new BridgeConfig(Pipe, Secret)));

            Assert.Null(reply.RebuildErrorCount);
        }
    }

    [Fact]
    public void OpenWithoutACopyPathIsABadResponseRatherThanAnEmptyPath()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""rebuild_error_count"":0,""copy_present"":true}");

            BackendRequestException failure = Assert.Throws<BackendRequestException>(
                () => backend.Client().Open(new RemodelOpenRequest(
                    RunDirectory, SourcePath, null, "probe-7", new BridgeConfig(Pipe, Secret))));

            Assert.Equal("BadResponse", failure.ErrorClass);
        }
    }

    // ---- POST /remodel/plan ----------------------------------------------------------------

    [Fact]
    public void PlanPostsTheRunFolderAloneAndReturnsThePlanSummaryUntouched()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""plan_summary"":{""moves"":12,""folders"":6,
                                  ""state"":""planned"",""descriptions"":[]}}");

            string summary = backend.Client().Plan(RunDirectory);

            RecordedRequest request = backend.Only();
            Assert.Equal("POST", request.Method);
            Assert.Equal("/remodel/plan", request.Path);
            Assert.Equal(RunDirectory, request.Text("run_dir"));

            // The bridge is not in this body: planning reads the folder the add-in already
            // dumped into and makes no bridge call, so the secret does not travel with it.
            Assert.False(request.Has("bridge"));

            using (JsonDocument parsed = JsonDocument.Parse(summary))
            {
                Assert.Equal(12, parsed.RootElement.GetProperty("moves").GetInt32());
                Assert.Equal("planned", parsed.RootElement.GetProperty("state").GetString());
            }
        }
    }

    [Fact]
    public void PlanWithoutASummaryIsABadResponse()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, "{}");

            BackendRequestException failure = Assert.Throws<BackendRequestException>(
                () => backend.Client().Plan(RunDirectory));

            Assert.Equal("BadResponse", failure.ErrorClass);
        }
    }

    // ---- POST /remodel/runs ----------------------------------------------------------------

    [Fact]
    public void StartRunPostsTheRunFolderAndTheBridgeAndReturnsTheJobId()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(201, @"{""job_id"":""job-42"",""chat_id"":""job-42""}");

            string jobId = backend.Client().StartRun(
                new RemodelRunRequest(RunDirectory, new BridgeConfig(Pipe, Secret)));

            RecordedRequest request = backend.Only();
            Assert.Equal("POST", request.Method);
            Assert.Equal("/remodel/runs", request.Path);
            Assert.Equal(RunDirectory, request.Text("run_dir"));
            Assert.Equal(Pipe, request.Text("bridge", "pipe"));
            Assert.Equal(Secret, request.Text("bridge", "secret"));
            Assert.Equal("job-42", jobId);
        }
    }

    [Fact]
    public void StartRunWithoutAJobIdIsABadResponse()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(201, @"{""chat_id"":""job-42""}");

            BackendRequestException failure = Assert.Throws<BackendRequestException>(
                () => backend.Client().StartRun(
                    new RemodelRunRequest(RunDirectory, new BridgeConfig(Pipe, Secret))));

            Assert.Equal("BadResponse", failure.ErrorClass);
        }
    }

    // ---- GET /remodel/runs/{job_id} --------------------------------------------------------

    [Fact]
    public void StatusGetsTheJobAndReadsEveryFieldOfIt()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""state"":""running"",""plan_state"":""applying"",
                ""changes_total"":12,""changes_applied"":5,
                ""current"":{""seq"":6,""kind"":""reorder"",""subject_name"":""Fillet3""},
                ""awaiting"":null,""error"":null}");

            RemodelRunStatus status = backend.Client().Status("job 42");

            RecordedRequest request = backend.Only();
            Assert.Equal("GET", request.Method);
            Assert.Equal("/remodel/runs/job%2042", request.Path);
            Assert.Equal("Bearer " + Token, request.Authorization);
            Assert.Equal(string.Empty, request.Body);

            Assert.Equal(RemodelRunStatus.RunningState, status.State);
            Assert.Equal("applying", status.PlanState);
            Assert.Equal(12, status.ChangesTotal);
            Assert.Equal(5, status.ChangesApplied);
            Assert.NotNull(status.Current);
            Assert.Equal(6, status.Current!.Seq);
            Assert.Equal("reorder", status.Current.Kind);
            Assert.Equal("Fillet3", status.Current.SubjectName);
            Assert.Null(status.Awaiting);
            Assert.Null(status.Error);
        }
    }

    [Fact]
    public void StatusReadsTheRendezvousAndTheTerminalError()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""state"":""awaiting_package_after"",""plan_state"":""verifying"",
                ""changes_total"":12,""changes_applied"":12,""current"":null,
                ""awaiting"":""package_after"",""error"":null}");
            Assert.Equal(
                RemodelRunStatus.PackageAfterAwaiting, backend.Client().Status("job-42").Awaiting);

            backend.Reply(200, @"{""state"":""failed"",""plan_state"":""failed"",
                ""changes_total"":12,""changes_applied"":3,""current"":null,
                ""awaiting"":null,""error"":""the geometry gate refused the copy""}");
            RemodelRunStatus failed = backend.Client().Status("job-42");

            Assert.Equal(RemodelRunStatus.FailedState, failed.State);
            Assert.Equal("the geometry gate refused the copy", failed.Error);
            Assert.Null(failed.Current);
        }
    }

    // ---- GET /remodel/runs/{job_id}/events -------------------------------------------------

    [Fact]
    public void EventsGetsTheCursorAndHandsBackTheLinesAndTheNextCursor()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""events"":[{""type"":""started"",""seq"":4},
                                              {""type"":""tool_call"",""seq"":5}],""next"":5}");

            RemodelEventPage page = backend.Client().Events("job-42", after: 3);

            RecordedRequest request = backend.Only();
            Assert.Equal("GET", request.Method);
            Assert.Equal("/remodel/runs/job-42/events", request.Path);
            Assert.Equal("after=3", request.Query);
            Assert.Equal(5, page.Next);
            Assert.Equal(2, page.Events.Count);

            using (JsonDocument first = JsonDocument.Parse(page.Events[0]))
            {
                Assert.Equal("started", first.RootElement.GetProperty("type").GetString());
            }
        }
    }

    // ---- POST /remodel/runs/{job_id}/package-after -----------------------------------------

    [Fact]
    public void PackageAfterPostsTheExactPathAndNothingElse()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""ok"":true}");
            string path = Path.Combine(RunDirectory, "package-after.json");

            backend.Client().PackageAfter("job-42", path);

            RecordedRequest request = backend.Only();
            Assert.Equal("POST", request.Method);
            Assert.Equal("/remodel/runs/job-42/package-after", request.Path);
            Assert.Equal(path, request.Text("path"));
        }
    }

    // ---- POST /remodel/runs/{job_id}/stop --------------------------------------------------

    [Fact]
    public void StopPostsAnEmptyBodyToTheJobsStopRoute()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""stopping"":true}");

            backend.Client().Stop("job-42");

            RecordedRequest request = backend.Only();
            Assert.Equal("POST", request.Method);
            Assert.Equal("/remodel/runs/job-42/stop", request.Path);
            Assert.Equal("{}", request.Body);
        }
    }

    // ---- POST /remodel/close ---------------------------------------------------------------

    [Fact]
    public void CloseSaysWhetherTheCopyIsBeingDiscardedAndCarriesTheBridge()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""closed"":true}");

            backend.Client().Close(
                new RemodelCloseRequest(RunDirectory, new BridgeConfig(Pipe, Secret), false));

            RecordedRequest request = backend.Only();
            Assert.Equal("POST", request.Method);
            Assert.Equal("/remodel/close", request.Path);
            Assert.Equal(RunDirectory, request.Text("run_dir"));
            Assert.Equal(Secret, request.Text("bridge", "secret"));
            Assert.False(request.Flag("discard_copy"));
        }
    }

    // ---- the refusal mapping ---------------------------------------------------------------

    [Theory]
    [InlineData(400, "NotAPart", "the active document is an assembly.")]
    [InlineData(409, "ResumeRefused", "a changes.jsonl already exists in this run folder.")]
    [InlineData(409, "RunInProgress", "a remodel run is already running in that folder.")]
    [InlineData(409, "RunNotPlanned", "this run folder holds no plan.json.")]
    [InlineData(422, "ScopeRefused", "the part is a weldment; the part has 3 solid bodies.")]
    [InlineData(503, "BridgeUnavailable", "the SOLIDWORKS bridge did not answer.")]
    public void ARefusalArrivesAsItsOwnErrorClassAndMessage(
        int status, string errorClass, string message)
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(
                status,
                JsonSerializer.Serialize(new Dictionary<string, object?>
                {
                    { "error_class", errorClass },
                    { "message", message },
                    { "retryable", status >= 500 },
                }));

            BackendRequestException failure = Assert.Throws<BackendRequestException>(
                () => backend.Client().Plan(RunDirectory));

            Assert.Equal(errorClass, failure.ErrorClass);
            Assert.Equal(message, failure.Message);
            Assert.Equal(status >= 500, failure.Retryable);
        }
    }

    [Fact]
    public void AnErrorBodyThatIsNotJsonIsReportedAsAnHttpErrorRatherThanParsedAsProse()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(500, "<html>Internal Server Error</html>");

            BackendRequestException failure = Assert.Throws<BackendRequestException>(
                () => backend.Client().Plan(RunDirectory));

            Assert.Equal("HttpError", failure.ErrorClass);
            Assert.True(failure.Retryable);
        }
    }

    [Fact]
    public void ABackendThatIsNotRunningIsBackendUnavailableAndNeverAnAttemptedCall()
    {
        var client = new RemodelBackendClient(() => null);

        BackendRequestException failure = Assert.Throws<BackendRequestException>(
            () => client.Plan(RunDirectory));

        Assert.Equal("BackendUnavailable", failure.ErrorClass);
        Assert.True(failure.Retryable);
    }

    [Fact]
    public void ABackendThatDiedMidRunIsBackendUnavailableRatherThanAnUnhandledWebException()
    {
        BackendEndpoint endpoint;
        using (var backend = new FakeBackend())
        {
            endpoint = backend.Endpoint;
        }

        var client = new RemodelBackendClient(() => endpoint);

        BackendRequestException failure = Assert.Throws<BackendRequestException>(
            () => client.Status("job-42"));

        Assert.Equal("BackendUnavailable", failure.ErrorClass);
        Assert.True(failure.Retryable);
    }

    /// <summary>
    /// The token is in the header and the bridge secret is in the body. A URL reaches access
    /// logs and crash dumps (chat-api.md), and the remodel secret authorizes every write the
    /// run makes to the copy.
    /// </summary>
    [Fact]
    public void NeitherTheTokenNorTheBridgeSecretEverReachesAUrl()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, @"{""probe_id"":""probe-7"",""signals"":{},""refusals"":[]}");
            backend.Client().Probe(
                new RemodelProbeRequest(SourcePath, "Default", new BridgeConfig(Pipe, Secret)));

            backend.Reply(200, @"{""closed"":true}");
            backend.Client().Close(
                new RemodelCloseRequest(RunDirectory, new BridgeConfig(Pipe, Secret), true));

            foreach (RecordedRequest request in backend.Requests)
            {
                Assert.DoesNotContain(Secret, request.Url, StringComparison.Ordinal);
                Assert.DoesNotContain(Token, request.Url, StringComparison.Ordinal);
                Assert.Equal("Bearer " + Token, request.Authorization);
            }
        }
    }

    // ---- the server ------------------------------------------------------------------------

    /// <summary>One request as it arrived on the wire.</summary>
    private sealed class RecordedRequest
    {
        public RecordedRequest(string method, string url, string? authorization, string body)
        {
            Method = method;
            Url = url;
            Authorization = authorization;
            Body = body;
        }

        public string Method { get; }

        /// <summary>Path and query exactly as the client asked for them.</summary>
        public string Url { get; }

        public string? Authorization { get; }

        public string Body { get; }

        public string Path
        {
            get
            {
                int mark = Url.IndexOf('?');
                return mark < 0 ? Url : Url.Substring(0, mark);
            }
        }

        public string Query
        {
            get
            {
                int mark = Url.IndexOf('?');
                return mark < 0 ? string.Empty : Url.Substring(mark + 1);
            }
        }

        public bool Has(string name) => Member(name).ValueKind != JsonValueKind.Undefined;

        public bool Flag(string name) => Member(name).ValueKind == JsonValueKind.True;

        /// <summary>A string member of the JSON body, or of one of its objects.</summary>
        public string? Text(string name, string? inner = null)
        {
            JsonElement member = Member(name);
            if (inner != null)
            {
                if (member.ValueKind != JsonValueKind.Object
                    || !member.TryGetProperty(inner, out member))
                {
                    return null;
                }
            }

            return member.ValueKind == JsonValueKind.String ? member.GetString() : null;
        }

        private JsonElement Member(string name)
        {
            using (JsonDocument document = JsonDocument.Parse(Body))
            {
                return document.RootElement.ValueKind == JsonValueKind.Object
                    && document.RootElement.TryGetProperty(name, out JsonElement value)
                        ? value.Clone()
                        : default(JsonElement);
            }
        }
    }

    /// <summary>
    /// The loopback backend, in this process: one <see cref="HttpListener"/> on a free port,
    /// answering every request with whatever <see cref="Reply"/> last set and recording what it
    /// was asked.
    /// </summary>
    private sealed class FakeBackend : IDisposable
    {
        private readonly HttpListener _listener = new HttpListener();
        private readonly Thread _thread;
        private readonly List<RecordedRequest> _requests = new List<RecordedRequest>();
        private readonly object _gate = new object();

        private int _status = 200;
        private string _body = "{}";

        public FakeBackend()
        {
            int port = FreePort();
            _listener.Prefixes.Add("http://127.0.0.1:" + port + "/");
            _listener.Start();
            Endpoint = new BackendEndpoint(port, Token);
            _thread = new Thread(Serve) { IsBackground = true, Name = "fake-remodel-backend" };
            _thread.Start();
        }

        public BackendEndpoint Endpoint { get; }

        public IReadOnlyList<RecordedRequest> Requests
        {
            get
            {
                lock (_gate)
                {
                    return new List<RecordedRequest>(_requests);
                }
            }
        }

        public RemodelBackendClient Client() => new RemodelBackendClient(() => Endpoint);

        public void Reply(int status, string body)
        {
            lock (_gate)
            {
                _status = status;
                _body = body;
            }
        }

        /// <summary>The one request this server was asked; fails loudly if there were others.</summary>
        public RecordedRequest Only()
        {
            IReadOnlyList<RecordedRequest> seen = Requests;
            Assert.Single(seen);
            return seen[0];
        }

        public void Dispose()
        {
            try
            {
                _listener.Stop();
                _listener.Close();
            }
            catch (ObjectDisposedException)
            {
                // Already closed; the port is free either way.
            }

            _thread.Join(TimeSpan.FromSeconds(5));
        }

        private void Serve()
        {
            while (true)
            {
                HttpListenerContext context;
                try
                {
                    context = _listener.GetContext();
                }
                catch (Exception)
                {
                    // Stop() and Close() are how this loop ends; both throw here.
                    return;
                }

                string body;
                using (var reader = new StreamReader(
                    context.Request.InputStream, context.Request.ContentEncoding ?? Encoding.UTF8))
                {
                    body = reader.ReadToEnd();
                }

                int status;
                string reply;
                lock (_gate)
                {
                    _requests.Add(new RecordedRequest(
                        context.Request.HttpMethod,
                        context.Request.RawUrl ?? string.Empty,
                        context.Request.Headers["Authorization"],
                        body));
                    status = _status;
                    reply = _body;
                }

                byte[] payload = Encoding.UTF8.GetBytes(reply);
                context.Response.StatusCode = status;
                context.Response.ContentType = "application/json";
                context.Response.ContentLength64 = payload.Length;
                context.Response.OutputStream.Write(payload, 0, payload.Length);
                context.Response.Close();
            }
        }

        /// <summary>A port the operating system has just confirmed is free.</summary>
        private static int FreePort()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0);
            probe.Start();
            try
            {
                return ((IPEndPoint)probe.LocalEndpoint).Port;
            }
            finally
            {
                probe.Stop();
            }
        }
    }
}
