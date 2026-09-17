using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// <see cref="BackendProxyHandler.Send"/> - the production default of
/// <see cref="TaskPaneOptions.ProxySend"/> - against a real in-process
/// <see cref="HttpListener"/>, the way <see cref="RemodelBackendClientTests"/> exercises the
/// other loopback client.
///
/// <b>Why a socket and not the injected seam.</b> Every case in
/// <see cref="BackendProxyHandlerTests"/> supplies a fake transport, so the rules about headers
/// and failure shapes are pinned without a network - and `Send` itself was never executed by
/// anything. It is the half where the interesting failures live, because
/// `HttpWebRequest.Headers` on .NET Framework <i>throws</i> `ArgumentException` for the
/// restricted set (`User-Agent`, `Referer`, `Range`, `Date`, `Expect`, `If-Modified-Since`,
/// `Transfer-Encoding`) rather than sending them, and `User-Agent` and `Referer` are two of the
/// nine headers a real WebView2 page `fetch` produces. A fake transport cannot see that; a
/// socket can.
///
/// The header set in <see cref="AWebView2Fetch"/> is not invented. It was captured from a real
/// offscreen WebView2 fetch through `WebResourceRequested` (see `docs/pane-backend-proxy.md`
/// section 4), so this file fails the day the pane would fail.
/// </summary>
public sealed class BackendProxySendTests
{
    private const string Prefix = "https://swreview.invalid/__backend";

    /// <summary>
    /// The exact headers a WebView2 page's `fetch(url, {method: 'POST', headers: {...}})`
    /// carries, captured from the runtime rather than guessed. `Origin` and the `sec-ch-ua`
    /// set are added by the browser; `User-Agent` and `Referer` are the two the transport
    /// refuses.
    /// </summary>
    private static IEnumerable<KeyValuePair<string, string>> AWebView2Fetch() => new[]
    {
        new KeyValuePair<string, string>("Accept", "application/json"),
        new KeyValuePair<string, string>("Authorization", "Bearer 0FAKEtoken"),
        new KeyValuePair<string, string>("Content-Type", "application/json"),
        new KeyValuePair<string, string>("Origin", "https://swreview.invalid"),
        new KeyValuePair<string, string>("Referer", "https://swreview.invalid/Review/ReviewPage/index.html"),
        new KeyValuePair<string, string>(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                + "Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0"),
        new KeyValuePair<string, string>(
            "sec-ch-ua",
            "\"Microsoft Edge WebView2\";v=\"153\", \"Not_A Brand\";v=\"8\""),
        new KeyValuePair<string, string>("sec-ch-ua-mobile", "?0"),
        new KeyValuePair<string, string>("sec-ch-ua-platform", "\"Windows\""),
    };

    /// <summary>
    /// The call the pane actually makes, end to end over a socket: what the backend receives,
    /// and what it must never receive.
    /// </summary>
    [Fact]
    public void AWebView2FetchReachesTheBackendWithoutTheHeadersThatDescribeThePage()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(200, "{\"ok\":true}");

            ProxiedResponse? response = backend.Handler().TryServe(
                Prefix + "/messages",
                "POST",
                AWebView2Fetch(),
                new MemoryStream(Encoding.UTF8.GetBytes("{\"text\":\"hello\"}")));

            Assert.Equal(200, response!.Status);
            Assert.Equal("{\"ok\":true}", Encoding.UTF8.GetString(response.Content));
            Assert.Contains("Content-Type: application/json", response.Headers, StringComparison.Ordinal);

            RecordedCall call = backend.Only();
            Assert.Equal("POST", call.Method);
            Assert.Equal("/messages", call.Path);
            Assert.Equal("{\"text\":\"hello\"}", call.Body);
            Assert.Equal("Bearer 0FAKEtoken", call.Header("Authorization"));
            Assert.Equal("application/json", call.Header("Accept"));
            Assert.Equal("application/json", call.Header("Content-Type"));

            // The page's own request is not the request being made.
            Assert.Null(call.Header("Origin"));
            Assert.Null(call.Header("User-Agent"));
            Assert.Null(call.Header("Referer"));
            Assert.Null(call.Header("sec-ch-ua"));
            Assert.Null(call.Header("sec-ch-ua-platform"));
        }
    }

    /// <summary>
    /// The transport refuses some headers outright, and the page must still get an answer.
    ///
    /// `Range` is one of the restricted set `HttpWebRequest.Headers` throws `ArgumentException`
    /// for - which is neither `WebException` nor `IOException`, so before this was handled it
    /// escaped `TryServe`, was swallowed by the pane's blanket catch, and the request was left
    /// with no response at all.
    /// </summary>
    [Fact]
    public void AHeaderTheTransportRefusesStillAnswersInThePagesErrorShape()
    {
        using (var backend = new FakeBackend())
        {
            ProxiedResponse? response = backend.Handler().TryServe(
                Prefix + "/health",
                "GET",
                new[] { new KeyValuePair<string, string>("Range", "bytes=0-10") },
                null);

            Assert.NotNull(response);
            string body = Encoding.UTF8.GetString(response!.Content);
            Assert.Contains("\"error_class\":\"ProxyFailed\"", body, StringComparison.Ordinal);
            Assert.Contains("\"retryable\":false", body, StringComparison.Ordinal);
            Assert.Empty(backend.Requests);
        }
    }

    /// <summary>
    /// The backend's own refusal is an answer, not a transport failure: `HttpWebRequest` raises
    /// `WebException` for a 4xx, and the page reads `{error_class, message}` out of the body.
    /// </summary>
    [Fact]
    public void TheBackendsOwnRefusalComesBackVerbatimThroughTheRealTransport()
    {
        using (var backend = new FakeBackend())
        {
            backend.Reply(409, "{\"error_class\":\"TurnRunning\",\"retryable\":false}");

            ProxiedResponse? response = backend.Handler().TryServe(
                Prefix + "/messages",
                "POST",
                new[] { new KeyValuePair<string, string>("Content-Type", "application/json") },
                new MemoryStream(Encoding.UTF8.GetBytes("{}")));

            Assert.Equal(409, response!.Status);
            Assert.Equal(
                "{\"error_class\":\"TurnRunning\",\"retryable\":false}",
                Encoding.UTF8.GetString(response.Content));
        }
    }

    /// <summary>A backend that is not listening reads as a retryable backend problem.</summary>
    [Fact]
    public void ABackendThatIsNotListeningAnswersAsBackendUnavailable()
    {
        var handler = new BackendProxyHandler(
            () => new BackendEndpoint(FreePort(), "0FAKEtoken"),
            BackendProxyHandler.Send);

        ProxiedResponse? response = handler.TryServe(Prefix + "/health", "GET", null, null);

        Assert.Equal(502, response!.Status);
        string body = Encoding.UTF8.GetString(response.Content);
        Assert.Contains("\"error_class\":\"BackendUnavailable\"", body, StringComparison.Ordinal);
        Assert.Contains("\"retryable\":true", body, StringComparison.Ordinal);
    }

    /// <summary>A port the operating system has just confirmed is free, so nothing answers on it.</summary>
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

    /// <summary>One request as the backend saw it on the wire.</summary>
    private sealed class RecordedCall
    {
        public RecordedCall(string method, string path, NameValueCollection headers, string body)
        {
            Method = method;
            Path = path;
            Headers = headers;
            Body = body;
        }

        public string Method { get; }

        public string Path { get; }

        public NameValueCollection Headers { get; }

        public string Body { get; }

        public string? Header(string name) => Headers[name];
    }

    /// <summary>
    /// The loopback backend, in this process: one <see cref="HttpListener"/> on a free port,
    /// answering with whatever <see cref="Reply"/> last set and recording what it was asked.
    /// </summary>
    private sealed class FakeBackend : IDisposable
    {
        private readonly HttpListener _listener = new HttpListener();
        private readonly Thread _thread;
        private readonly List<RecordedCall> _requests = new List<RecordedCall>();
        private readonly object _gate = new object();

        private int _status = 200;
        private string _body = "{}";

        public FakeBackend()
        {
            int port = FreePort();
            _listener.Prefixes.Add("http://127.0.0.1:" + port + "/");
            _listener.Start();
            Endpoint = new BackendEndpoint(port, "0FAKEtoken");
            _thread = new Thread(Serve) { IsBackground = true, Name = "fake-proxy-backend" };
            _thread.Start();
        }

        public BackendEndpoint Endpoint { get; }

        public IReadOnlyList<RecordedCall> Requests
        {
            get
            {
                lock (_gate)
                {
                    return new List<RecordedCall>(_requests);
                }
            }
        }

        /// <summary>The handler the pane builds, with the real transport rather than a fake.</summary>
        public BackendProxyHandler Handler() =>
            new BackendProxyHandler(() => Endpoint, BackendProxyHandler.Send);

        public void Reply(int status, string body)
        {
            lock (_gate)
            {
                _status = status;
                _body = body;
            }
        }

        public RecordedCall Only()
        {
            IReadOnlyList<RecordedCall> seen = Requests;
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
                    _requests.Add(new RecordedCall(
                        context.Request.HttpMethod,
                        context.Request.Url?.AbsolutePath ?? string.Empty,
                        context.Request.Headers,
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
    }
}
