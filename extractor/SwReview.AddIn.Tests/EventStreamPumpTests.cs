using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The review event stream, read by the host and pushed to the page over the message channel
/// (`docs/pane-backend-proxy.md` section 2, `contracts/chat-api.md`).
///
/// <b>Why the host reads it at all.</b> This is the one backend route that cannot be served
/// through `WebResourceRequested`: a response there must be complete when the deferral ends,
/// and WebView2 reads every response stream on one background thread, so a blocking read would
/// stall every other request in the control. So the host reads `GET /sessions/{id}/events`
/// itself with `HttpWebRequest` - a request made by the add-in's own C# code, which is not what
/// an endpoint web filter intercepts - and posts each raw frame as `events.frame`. The page's
/// existing SSE parser is what reads it, unchanged: one parser, in the page.
///
/// <b>An in-process `HttpListener`, not a seam over the transport</b>, for the same reason
/// <see cref="RemodelBackendClientTests"/> uses one: everything that can be wrong here is on the
/// wire. Whether the reader streams or buffers, whether a frame is split at a chunk boundary,
/// whether `Last-Event-ID` is a header, and whether a server that hangs up is an error or an
/// ending are all questions a fake transport would answer by agreeing with the test.
/// </summary>
public sealed class EventStreamPumpTests
{
    private const string Token = "0FAKEtoken-never-in-a-posted-message";

    private const string ChatId = "chat-7";

    /// <summary>How long a test waits for the reader thread to deliver; it is a real socket.</summary>
    private static readonly TimeSpan Patience = TimeSpan.FromSeconds(10);

    // ---- the reader ---------------------------------------------------------------------------

    [Fact]
    public void FramesArriveInOrderAndVerbatim()
    {
        using (var backend = new SseBackend())
        using (var pump = backend.Pump(out Recorder recorded))
        {
            pump.Open(ChatId, null);
            SseConnection stream = backend.FirstConnection();

            stream.Send("id: 1\nevent: session.started\ndata: {\"provider\":\"fake\"}");
            stream.Send("id: 2\nevent: text.delta\ndata: {\"text\":\"one\"}");
            stream.Send(": keep-alive comment");

            recorded.WaitForFrames(3);

            Assert.Equal(
                new[]
                {
                    "id: 1\nevent: session.started\ndata: {\"provider\":\"fake\"}",
                    "id: 2\nevent: text.delta\ndata: {\"text\":\"one\"}",
                    ": keep-alive comment",
                },
                recorded.Frames);
            Assert.All(recorded.FrameChats, chat => Assert.Equal(ChatId, chat));
        }
    }

    /// <summary>
    /// A `data:` value spanning several lines is one frame. The page joins those lines with a
    /// newline before parsing the JSON, so a frame split here would reach it as two unparseable
    /// halves - and the deltas that carry a model's own multi-line text are exactly where this
    /// happens.
    /// </summary>
    [Fact]
    public void AMultiLineDataFrameIsNotSplit()
    {
        using (var backend = new SseBackend())
        using (var pump = backend.Pump(out Recorder recorded))
        {
            pump.Open(ChatId, null);
            backend.FirstConnection().Send("id: 9\nevent: text.delta\ndata: {\"text\":\n data: \"two\\nlines\"}");

            recorded.WaitForFrames(1);

            Assert.Equal(
                "id: 9\nevent: text.delta\ndata: {\"text\":\n data: \"two\\nlines\"}", recorded.Frames.Single());
        }
    }

    /// <summary>
    /// The reconnect rule: the page's highest seen `seq` travels as `Last-Event-ID`, so the
    /// backend replays from `events.jsonl` what was missed and nothing that was not. It is a
    /// header rather than a query parameter for the same reason the token is (chat-api.md).
    /// </summary>
    [Fact]
    public void TheRequestCarriesTheRouteTheTokenAndLastEventId()
    {
        using (var backend = new SseBackend())
        using (var pump = backend.Pump(out Recorder recorded))
        {
            pump.Open(ChatId, "41");
            SseConnection stream = backend.FirstConnection();
            stream.Send("id: 42\ndata: {}");
            recorded.WaitForFrames(1);

            Assert.Equal("GET", stream.Method);
            Assert.Equal("/sessions/chat-7/events", stream.Path);
            Assert.Equal(string.Empty, stream.Query);
            Assert.Equal("Bearer " + Token, stream.Header("Authorization"));
            Assert.Equal("41", stream.Header("Last-Event-ID"));
            Assert.Equal("text/event-stream", stream.Header("Accept"));
        }
    }

    [Fact]
    public void NoLastEventIdIsSentOnAFirstConnection()
    {
        using (var backend = new SseBackend())
        using (var pump = backend.Pump(out Recorder recorded))
        {
            pump.Open(ChatId, null);
            SseConnection stream = backend.FirstConnection();
            stream.Send("id: 1\ndata: {}");
            recorded.WaitForFrames(1);

            Assert.Null(stream.Header("Last-Event-ID"));
        }
    }

    /// <summary>
    /// A server that hangs up is an ending, not an error: nothing is lost, because every event
    /// is in `events.jsonl` and the page reopens from the last `seq` it showed. The page decides
    /// whether to reopen, so the host says only that the stream closed and why.
    /// </summary>
    [Fact]
    public void AServerThatClosesTheStreamYieldsEventsClosed()
    {
        using (var backend = new SseBackend())
        using (var pump = backend.Pump(out Recorder recorded))
        {
            pump.Open(ChatId, null);
            SseConnection stream = backend.FirstConnection();
            stream.Send("id: 1\ndata: {}");
            recorded.WaitForFrames(1);

            stream.Close();

            recorded.WaitForClosed(1);
            Assert.Equal(ChatId, recorded.Closed.Single().Key);
            Assert.NotEqual(string.Empty, recorded.Closed.Single().Value);
        }
    }

    /// <summary>
    /// A reader that outlived its `events.open` must not write into the page that replaced it.
    /// The second open is a second review or a reconnect: the first connection may still be
    /// draining, and a frame from it would land in a transcript it does not belong to.
    /// </summary>
    [Fact]
    public void ASecondOpenReplacesTheFirstAndDropsItsLateFrames()
    {
        using (var backend = new SseBackend())
        using (var pump = backend.Pump(out Recorder recorded))
        {
            pump.Open(ChatId, null);
            SseConnection first = backend.FirstConnection();
            first.Send("id: 1\ndata: {\"from\":\"first\"}");
            recorded.WaitForFrames(1);

            pump.Open("chat-8", null);
            SseConnection second = backend.Connection(1);

            // Whatever the first connection still had to say arrives after it was replaced.
            first.Send("id: 2\ndata: {\"from\":\"first\"}");
            second.Send("id: 1\ndata: {\"from\":\"second\"}");
            recorded.WaitForFrames(2);

            // Long enough for a third frame to arrive if the replaced reader were still feeding
            // this recorder; the two above took milliseconds.
            Thread.Sleep(250);

            Assert.Equal(2, recorded.Frames.Count);
            Assert.Contains("second", recorded.Frames[1]);
            Assert.Equal(new[] { ChatId, "chat-8" }, recorded.FrameChats);

            // And the replaced stream is not reported as a close against the new chat either.
            Assert.DoesNotContain("chat-8", recorded.Closed.Select(closed => closed.Key));
        }
    }

    [Fact]
    public void CloseStopsTheReaderAndSaysNothingFurther()
    {
        using (var backend = new SseBackend())
        using (var pump = backend.Pump(out Recorder recorded))
        {
            pump.Open(ChatId, null);
            SseConnection stream = backend.FirstConnection();
            stream.Send("id: 1\ndata: {}");
            recorded.WaitForFrames(1);

            pump.Close();

            stream.Send("id: 2\ndata: {}");
            Thread.Sleep(250);

            Assert.Single(recorded.Frames);
            Assert.Empty(recorded.Closed);
        }
    }

    [Fact]
    public void OpenOnAHostWithNoBackendClosesRatherThanHanging()
    {
        var recorded = new Recorder();
        using (var pump = new EventStreamPump(() => null, recorded.Frame, recorded.Close))
        {
            pump.Open(ChatId, null);

            recorded.WaitForClosed(1);
            Assert.Contains("backend", recorded.Closed.Single().Value, StringComparison.OrdinalIgnoreCase);
            Assert.Empty(recorded.Frames);
        }
    }

    // ---- the host's half ----------------------------------------------------------------------

    /// <summary>
    /// `events.open` from the page, an `events.frame` per frame back, and the token nowhere in
    /// either. The frames go out through the host's own redacting choke point, which is what
    /// keeps a key that reached a provider error message out of the renderer process (FR-015).
    /// </summary>
    [Fact]
    public void EventsOpenStreamsFramesToThePageAndNeverPostsTheToken()
    {
        using (var backend = new SseBackend())
        using (var world = new PumpWorld(backend.Endpoint))
        {
            world.Receive("events.open", new { chat_id = ChatId, last_event_id = (string?)null });
            backend.FirstConnection().Send("id: 1\nevent: text.delta\ndata: {\"text\":\"one\"}");

            JsonElement frame = world.WaitFor("events.frame");
            Assert.Equal(ChatId, frame.GetProperty("chat_id").GetString());
            Assert.Equal("id: 1\nevent: text.delta\ndata: {\"text\":\"one\"}", frame.GetProperty("frame").GetString());

            world.AssertNothingPostedContains(Token);
        }
    }

    [Fact]
    public void EventsClosedReachesThePageWhenTheBackendHangsUp()
    {
        using (var backend = new SseBackend())
        using (var world = new PumpWorld(backend.Endpoint))
        {
            world.Receive("events.open", new { chat_id = ChatId, last_event_id = (string?)null });
            SseConnection stream = backend.FirstConnection();
            stream.Send("id: 1\ndata: {}");
            world.WaitFor("events.frame");

            stream.Close();

            JsonElement closed = world.WaitFor("events.closed");
            Assert.Equal(ChatId, closed.GetProperty("chat_id").GetString());
            Assert.False(string.IsNullOrEmpty(closed.GetProperty("reason").GetString()));
        }
    }

    /// <summary>
    /// The `last_event_id` the page sent reaches the backend as `Last-Event-ID`, through the
    /// host rather than through <see cref="EventStreamPump.Open"/> called directly.
    ///
    /// <b>Why this is a host test and not another pump test.</b> The pump's own tests hand
    /// `Open` a string, so they prove the header is sent and nothing at all about the row that
    /// produces it. `ReviewHost.LastEventId` could return null for every payload and every one
    /// of them would still pass - and the failure that hides is silent and expensive: every
    /// reconnect would replay `events.jsonl` from seq 0 and duplicate the whole transcript on
    /// screen, which is the one thing `Last-Event-ID` exists to prevent.
    ///
    /// The rows are the ones that method actually branches on. A number as well as a string,
    /// because the page's `seq` is a number; zero and below are "from the beginning", which is
    /// the <i>absence</i> of the header and not an id of `0`, because an id of `0` asks the
    /// backend for everything after event zero and so loses event zero.
    /// </summary>
    [Fact]
    public void TheLastEventIdThePageSentReachesTheBackendAsAHeader()
    {
        var probes = new List<KeyValuePair<object, string?>>
        {
            new KeyValuePair<object, string?>(
                new { chat_id = ChatId, last_event_id = "41" }, "41"),
            new KeyValuePair<object, string?>(
                new { chat_id = ChatId, last_event_id = 41 }, "41"),
            new KeyValuePair<object, string?>(
                new { chat_id = ChatId, last_event_id = 0 }, null),
            new KeyValuePair<object, string?>(
                new { chat_id = ChatId, last_event_id = -5 }, null),
            new KeyValuePair<object, string?>(
                new { chat_id = ChatId, last_event_id = "" }, null),
            new KeyValuePair<object, string?>(
                new { chat_id = ChatId, last_event_id = (string?)null }, null),
            new KeyValuePair<object, string?>(new { chat_id = ChatId }, null),
        };

        foreach (KeyValuePair<object, string?> probe in probes)
        {
            using (var backend = new SseBackend())
            using (var world = new PumpWorld(backend.Endpoint))
            {
                world.Receive("events.open", probe.Key);

                string? sent = backend.FirstConnection().Header("Last-Event-ID");
                Assert.True(
                    probe.Value == sent,
                    $"events.open {JsonSerializer.Serialize(probe.Key)} should reach the backend "
                        + $"with Last-Event-ID {Describe(probe.Value)}, not {Describe(sent)}.");
            }
        }
    }

    private static string Describe(string? header) =>
        header == null ? "<no header>" : "'" + header + "'";

    /// <summary>
    /// A page that reloaded has no transcript and no stream; the reader the old page asked for
    /// would be writing into a page that is gone. `ready` is the moment the host learns of the
    /// reload, so it is where the pump stops.
    /// </summary>
    [Fact]
    public void AReadyFromAReloadedPageAndAnEventsCloseBothStopThePump()
    {
        foreach (string stopper in new[] { "events.close", "ready" })
        {
            using (var backend = new SseBackend())
            using (var world = new PumpWorld(backend.Endpoint))
            {
                world.Receive("events.open", new { chat_id = ChatId, last_event_id = (string?)null });
                SseConnection stream = backend.FirstConnection();
                stream.Send("id: 1\ndata: {}");
                world.WaitFor("events.frame");

                world.Receive(stopper, new { });

                stream.Send("id: 2\ndata: {}");
                Thread.Sleep(250);

                Assert.Equal(1, world.Count("events.frame"));
                Assert.Equal(0, world.Count("events.closed"));
            }
        }
    }

    [Fact]
    public void AnEventsOpenWithNoChatIdIsAnsweredRatherThanStartingAReader()
    {
        using (var backend = new SseBackend())
        using (var world = new PumpWorld(backend.Endpoint))
        {
            world.Receive("events.open", new { });

            JsonElement error = world.WaitFor("error");
            Assert.Equal("InvalidRequest", error.GetProperty("error_class").GetString());
            Assert.Empty(backend.Connections);
        }
    }

    // ---- the host, with nothing else in it -----------------------------------------------------

    /// <summary>
    /// A <see cref="ReviewHost"/> over a temporary settings file, a recording channel and a
    /// backend that is nothing but an endpoint. Smaller than the worlds in
    /// <see cref="PageMessageTests"/> and <see cref="ReviewHostTests"/> on purpose: the rows
    /// under test here touch neither settings nor a review.
    /// </summary>
    private sealed class PumpWorld : IDisposable
    {
        private readonly string _root;
        private readonly List<string> _posted = new List<string>();
        private readonly ReviewHost _host;

        public PumpWorld(BackendEndpoint endpoint)
        {
            _root = Path.Combine(
                Path.GetTempPath(), "SwReview.EventStream.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);

            string settingsPath = Path.Combine(_root, "settings.json");
            UserSettings settings = UserSettings.Defaults();
            settings.RunRoot = Path.Combine(_root, "runs");
            settings.Save(settingsPath);

            _host = new ReviewHost(
                new ReviewHostOptions(new RecordingChannel(_posted), new EndpointOnly(endpoint), settingsPath)
                {
                    LogFolder = Path.Combine(_root, "logs"),
                });
        }

        public void Receive(string type, object payload) =>
            _host.Receive(JsonSerializer.Serialize(new { type, id = (string?)null, payload }));

        /// <summary>The payload of the first message of this type, waited for.</summary>
        public JsonElement WaitFor(string type)
        {
            DateTime deadline = DateTime.UtcNow + Patience;
            while (DateTime.UtcNow < deadline)
            {
                foreach (string message in Snapshot())
                {
                    JsonElement root = JsonDocument.Parse(message).RootElement;
                    if (root.GetProperty("type").GetString() == type)
                    {
                        return root.GetProperty("payload").Clone();
                    }
                }

                Thread.Sleep(20);
            }

            throw new Xunit.Sdk.XunitException(
                $"no '{type}' was posted within {Patience.TotalSeconds:0}s; posted: "
                    + string.Join(", ", Snapshot().Select(TypeOf)));
        }

        public int Count(string type) => Snapshot().Count(message => TypeOf(message) == type);

        public void AssertNothingPostedContains(string secret)
        {
            foreach (string message in Snapshot())
            {
                Assert.DoesNotContain(secret, message);
            }
        }

        public void Dispose()
        {
            _host.Dispose();
            try
            {
                Directory.Delete(_root, recursive: true);
            }
            catch (IOException)
            {
            }
        }

        private List<string> Snapshot()
        {
            lock (_posted)
            {
                return new List<string>(_posted);
            }
        }

        private static string TypeOf(string message) =>
            JsonDocument.Parse(message).RootElement.GetProperty("type").GetString()!;
    }

    /// <summary>The page end of the channel: the reader thread posts through it, so it locks.</summary>
    private sealed class RecordingChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public RecordingChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json)
        {
            lock (_posted)
            {
                _posted.Add(json);
            }
        }
    }

    /// <summary>A backend client that is an endpoint and nothing else.</summary>
    private sealed class EndpointOnly : IBackendClient
    {
        public EndpointOnly(BackendEndpoint? endpoint) => Endpoint = endpoint;

        public BackendEndpoint? Endpoint { get; }

        public IReadOnlyList<ModelChoice> ListModels(string provider) =>
            throw new NotSupportedException("the event stream tests list no models");

        public bool IsTurnRunning(string chatId) => false;

        public ChatSessionHandle CreateSession(NewSessionRequest request) =>
            throw new NotSupportedException("the event stream tests start no review");

        public void Restart(UserSettings settings, ResolvedApiKey key) =>
            throw new NotSupportedException("the event stream tests save no settings");
    }

    // ---- what the pump reads --------------------------------------------------------------------

    /// <summary>What the pump handed out, from the reader thread.</summary>
    private sealed class Recorder
    {
        private readonly object _gate = new object();
        private readonly List<string> _frames = new List<string>();
        private readonly List<string> _frameChats = new List<string>();
        private readonly List<KeyValuePair<string, string>> _closed =
            new List<KeyValuePair<string, string>>();

        public IReadOnlyList<string> Frames
        {
            get
            {
                lock (_gate)
                {
                    return new List<string>(_frames);
                }
            }
        }

        public IReadOnlyList<string> FrameChats
        {
            get
            {
                lock (_gate)
                {
                    return new List<string>(_frameChats);
                }
            }
        }

        public IReadOnlyList<KeyValuePair<string, string>> Closed
        {
            get
            {
                lock (_gate)
                {
                    return new List<KeyValuePair<string, string>>(_closed);
                }
            }
        }

        public void Frame(string chatId, string frame)
        {
            lock (_gate)
            {
                _frameChats.Add(chatId);
                _frames.Add(frame);
            }
        }

        public void Close(string chatId, string reason)
        {
            lock (_gate)
            {
                _closed.Add(new KeyValuePair<string, string>(chatId, reason));
            }
        }

        public void WaitForFrames(int count) => WaitFor(() => Frames.Count >= count, count + " frames");

        public void WaitForClosed(int count) => WaitFor(() => Closed.Count >= count, count + " closures");

        private void WaitFor(Func<bool> done, string what)
        {
            DateTime deadline = DateTime.UtcNow + Patience;
            while (DateTime.UtcNow < deadline)
            {
                if (done())
                {
                    return;
                }

                Thread.Sleep(20);
            }

            throw new Xunit.Sdk.XunitException(
                $"the pump did not deliver {what} within {Patience.TotalSeconds:0}s; it delivered "
                    + $"{Frames.Count} frames and {Closed.Count} closures.");
        }
    }

    /// <summary>
    /// The backend's event route, in this process: an <see cref="HttpListener"/> that answers
    /// `text/event-stream` and holds the connection open until the test sends frames through it.
    /// One <see cref="SseConnection"/> per accepted request, so a reconnect is observable as a
    /// second connection rather than as more traffic on the first.
    /// </summary>
    private sealed class SseBackend : IDisposable
    {
        private readonly HttpListener _listener = new HttpListener();
        private readonly Thread _thread;
        private readonly List<SseConnection> _connections = new List<SseConnection>();
        private readonly object _gate = new object();

        public SseBackend()
        {
            int port = FreePort();
            _listener.Prefixes.Add("http://127.0.0.1:" + port + "/");
            _listener.Start();
            Endpoint = new BackendEndpoint(port, Token);
            _thread = new Thread(Serve) { IsBackground = true, Name = "fake-event-stream" };
            _thread.Start();
        }

        public BackendEndpoint Endpoint { get; }

        public IReadOnlyList<SseConnection> Connections
        {
            get
            {
                lock (_gate)
                {
                    return new List<SseConnection>(_connections);
                }
            }
        }

        /// <summary>A pump pointed at this server, with its callbacks recorded.</summary>
        public EventStreamPump Pump(out Recorder recorded)
        {
            var recorder = new Recorder();
            recorded = recorder;
            return new EventStreamPump(() => Endpoint, recorder.Frame, recorder.Close);
        }

        public SseConnection FirstConnection() => Connection(0);

        /// <summary>The nth connection, waited for: the reader is on its own thread.</summary>
        public SseConnection Connection(int index)
        {
            DateTime deadline = DateTime.UtcNow + Patience;
            while (DateTime.UtcNow < deadline)
            {
                IReadOnlyList<SseConnection> seen = Connections;
                if (seen.Count > index)
                {
                    return seen[index];
                }

                Thread.Sleep(20);
            }

            throw new Xunit.Sdk.XunitException(
                $"the pump never opened connection {index + 1}; it opened {Connections.Count}.");
        }

        public void Dispose()
        {
            foreach (SseConnection connection in Connections)
            {
                connection.Close();
            }

            try
            {
                _listener.Stop();
                _listener.Close();
            }
            catch (ObjectDisposedException)
            {
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

                var connection = new SseConnection(context);
                lock (_gate)
                {
                    _connections.Add(connection);
                }

                var writer = new Thread(connection.Pump)
                {
                    IsBackground = true,
                    Name = "fake-event-stream-writer",
                };
                writer.Start();
            }
        }

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

    /// <summary>One accepted `/events` request, with the frames the test feeds through it.</summary>
    private sealed class SseConnection
    {
        private readonly HttpListenerContext _context;
        private readonly BlockingCollection<string> _outbox = new BlockingCollection<string>();

        public SseConnection(HttpListenerContext context)
        {
            _context = context;
            Method = context.Request.HttpMethod;
            Url = context.Request.RawUrl ?? string.Empty;
            Headers = context.Request.Headers;
        }

        public string Method { get; }

        public string Url { get; }

        public NameValueCollection Headers { get; }

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

        public string? Header(string name) => Headers[name];

        /// <summary>Writes one frame, terminated by the blank line that ends an SSE frame.</summary>
        public void Send(string frame) => _outbox.Add(frame);

        /// <summary>Ends the response, which is what a backend hanging up looks like.</summary>
        public void Close()
        {
            if (!_outbox.IsAddingCompleted)
            {
                _outbox.CompleteAdding();
            }
        }

        public void Pump()
        {
            _context.Response.StatusCode = 200;
            _context.Response.ContentType = "text/event-stream";
            _context.Response.SendChunked = true;

            try
            {
                foreach (string frame in _outbox.GetConsumingEnumerable())
                {
                    byte[] payload = Encoding.UTF8.GetBytes(frame + "\n\n");
                    _context.Response.OutputStream.Write(payload, 0, payload.Length);
                    _context.Response.OutputStream.Flush();
                }
            }
            catch (Exception)
            {
                // The reader aborted the request; there is nobody left to write to.
            }

            try
            {
                _context.Response.Close();
            }
            catch (Exception)
            {
            }
        }
    }
}
