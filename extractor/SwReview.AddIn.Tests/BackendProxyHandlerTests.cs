using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The host half of the page's backend calls: what it forwards, what it refuses, and what
/// it never copies.
///
/// The transport is injected, so these run with no WebView2, no backend and no socket -
/// which is the point, because what matters is a set of rules about headers and failure
/// shapes rather than anything a live round trip would demonstrate.
/// </summary>
public sealed class BackendProxyHandlerTests
{
    private static readonly BackendEndpoint Endpoint = new BackendEndpoint(51234, "0FAKEtoken");

    private const string Prefix = "https://swreview.invalid/__backend";

    /// <summary>A URL the page owns is not ours; WebView2 must serve it normally.</summary>
    [Fact]
    public void ARequestOutsideThePrefixIsLeftToWebView2()
    {
        var handler = new BackendProxyHandler(() => Endpoint, MustNotSend);

        Assert.Null(handler.TryServe(
            "https://swreview.invalid/Review/ReviewPage/app.js", "GET", null, null));
    }

    [Fact]
    public void AProxiedCallReachesTheBackendWithItsMethodPathAndToken()
    {
        ProxiedRequest? seen = null;
        var handler = new BackendProxyHandler(() => Endpoint, request =>
        {
            seen = request;
            return Json(201, "Created", "{\"ok\":true}");
        });

        ProxiedResponse? response = handler.TryServe(
            Prefix + "/sessions",
            "POST",
            new[] { new KeyValuePair<string, string>("Authorization", "Bearer 0FAKEtoken") },
            new MemoryStream(Encoding.UTF8.GetBytes("{\"run_dir\":\"x\"}")));

        Assert.NotNull(seen);
        Assert.Equal("POST", seen!.Method);
        Assert.Equal("http://127.0.0.1:51234/sessions", seen.Url.ToString());
        Assert.Contains(
            seen.Headers,
            header => header.Key == "Authorization" && header.Value == "Bearer 0FAKEtoken");
        Assert.Equal("{\"run_dir\":\"x\"}", Encoding.UTF8.GetString(seen.Body!));

        Assert.Equal(201, response!.Status);
        Assert.Equal("{\"ok\":true}", Encoding.UTF8.GetString(response.Content));
    }

    /// <summary>
    /// `Origin` is not forwarded. The page's origin is the virtual host, and sending it on
    /// would make the backend's own origin guard refuse the very call this proxy exists to
    /// deliver.
    ///
    /// `User-Agent` and `Referer` go for the same reason - this request is not being made by
    /// a browser - and `Accept-Encoding` because the transport does not decompress. The
    /// header names here are the ones a real WebView2 `fetch` produces, captured in
    /// <see cref="BackendProxySendTests"/>, which is where the same rule is pinned over a
    /// socket.
    /// </summary>
    [Fact]
    public void ThePagesOriginAndHopHeadersAreNotForwarded()
    {
        ProxiedRequest? seen = null;
        var handler = new BackendProxyHandler(() => Endpoint, request =>
        {
            seen = request;
            return Json(200, "OK", "{}");
        });

        handler.TryServe(
            Prefix + "/models?provider=openai",
            "GET",
            new[]
            {
                new KeyValuePair<string, string>("Origin", "https://swreview.invalid"),
                new KeyValuePair<string, string>("Host", "swreview.invalid"),
                new KeyValuePair<string, string>("Sec-Fetch-Mode", "cors"),
                new KeyValuePair<string, string>("sec-ch-ua-platform", "\"Windows\""),
                new KeyValuePair<string, string>("User-Agent", "Mozilla/5.0 Edg/153.0.0.0"),
                new KeyValuePair<string, string>(
                    "Referer", "https://swreview.invalid/Review/ReviewPage/index.html"),
                new KeyValuePair<string, string>("Accept-Encoding", "gzip, deflate, br"),
                new KeyValuePair<string, string>("Authorization", "Bearer 0FAKEtoken"),
                new KeyValuePair<string, string>("Accept", "application/json"),
            },
            null);

        string[] names = seen!.Headers.Select(header => header.Key).ToArray();
        Assert.DoesNotContain("Origin", names);
        Assert.DoesNotContain("Host", names);
        Assert.DoesNotContain("Sec-Fetch-Mode", names);
        Assert.DoesNotContain("sec-ch-ua-platform", names);
        Assert.DoesNotContain("User-Agent", names);
        Assert.DoesNotContain("Referer", names);
        Assert.DoesNotContain("Accept-Encoding", names);
        Assert.Contains("Authorization", names);
        Assert.Contains("Accept", names);
        Assert.Equal("127.0.0.1", seen.Url.Host);
        Assert.Equal("provider=openai", seen.Url.Query.TrimStart('?'));
    }

    /// <summary>
    /// The event stream cannot be served this way at all: WebView2 requires the whole body
    /// before the deferral ends. Refusing loudly beats returning a stream that never ends.
    /// </summary>
    [Fact]
    public void TheEventStreamIsRefusedRatherThanBuffered()
    {
        var handler = new BackendProxyHandler(() => Endpoint, MustNotSend);

        ProxiedResponse? response = handler.TryServe(Prefix + "/sessions/abc/events", "GET", null, null);

        Assert.Equal(501, response!.Status);
        Assert.Contains("StreamNotProxyable", Encoding.UTF8.GetString(response.Content), StringComparison.Ordinal);
    }

    /// <summary>Before the child has handshaken, the page is told so in its own error shape.</summary>
    [Fact]
    public void WithNoBackendYetTheCallIsRefusedAsRetryable()
    {
        var handler = new BackendProxyHandler(() => null, MustNotSend);

        ProxiedResponse? response = handler.TryServe(Prefix + "/health", "GET", null, null);

        Assert.Equal(503, response!.Status);
        string body = Encoding.UTF8.GetString(response.Content);
        Assert.Contains("BackendUnavailable", body, StringComparison.Ordinal);
        Assert.Contains("\"retryable\":true", body, StringComparison.Ordinal);
    }

    /// <summary>...but a page resource is still not ours, even with no backend.</summary>
    [Fact]
    public void WithNoBackendAPageResourceIsStillLeftAlone()
    {
        var handler = new BackendProxyHandler(() => null, MustNotSend);

        Assert.Null(handler.TryServe(
            "https://swreview.invalid/Review/ReviewPage/index.html", "GET", null, null));
    }

    /// <summary>A dead child reads as a backend failure, not as a blank page.</summary>
    [Fact]
    public void ATransportFailureBecomesAReadableGatewayError()
    {
        var handler = new BackendProxyHandler(
            () => Endpoint,
            _ => throw new WebException("connection refused"));

        ProxiedResponse? response = handler.TryServe(Prefix + "/health", "GET", null, null);

        Assert.Equal(502, response!.Status);
        string body = Encoding.UTF8.GetString(response.Content);
        Assert.Contains("BackendUnavailable", body, StringComparison.Ordinal);
        Assert.Contains("connection refused", body, StringComparison.Ordinal);
    }

    /// <summary>The backend's own error status and body reach the page unchanged.</summary>
    [Fact]
    public void TheBackendsOwnErrorIsPassedThroughVerbatim()
    {
        var handler = new BackendProxyHandler(
            () => Endpoint,
            _ => Json(409, "Conflict", "{\"error_class\":\"TurnRunning\"}"));

        ProxiedResponse? response = handler.TryServe(Prefix + "/messages", "POST", null, null);

        Assert.Equal(409, response!.Status);
        Assert.Equal("{\"error_class\":\"TurnRunning\"}", Encoding.UTF8.GetString(response.Content));
    }

    /// <summary>A GET with no body must not invent one.</summary>
    [Fact]
    public void AGetCarriesNoBody()
    {
        ProxiedRequest? seen = null;
        var handler = new BackendProxyHandler(() => Endpoint, request =>
        {
            seen = request;
            return Json(200, "OK", "{}");
        });

        handler.TryServe(Prefix + "/health", "GET", null, new MemoryStream(new byte[0]));

        Assert.Null(seen!.Body);
    }

    // ---- a call that would start a turn, while a restart waits (owner decision 143A) ----------

    /// <summary>
    /// The page's calls that start a turn, or resume one (chat-api.md): a follow-up, Send, the
    /// answers, and the single answer the backend still serves. A trailing slash and an escaped
    /// letter name the same route to the backend, so they are the same call here.
    /// </summary>
    public static TheoryData<string> CallsThatStartATurn => new TheoryData<string>
    {
        "/sessions/chat-1/messages",
        "/sessions/chat-1/send",
        "/sessions/chat-1/evidence",
        "/sessions/chat-1/evidence/request-1",
        "/sessions/chat-1/messages/",
        "/sessions/chat-1/%6Dessages",
    };

    /// <summary>
    /// While the backend waits to be restarted with settings saved during a turn, such a call is
    /// for a chat of the backend being replaced: the host is asked first, and what it answers is
    /// what the page gets - the call is never sent.
    /// </summary>
    [Theory]
    [MemberData(nameof(CallsThatStartATurn))]
    public void ACallThatWouldStartATurnIsAnsweredWithTheHostsRefusalAndNeverSent(string path)
    {
        int asked = 0;
        var handler = new BackendProxyHandler(() => Endpoint, MustNotSend, () =>
        {
            asked++;
            return new BackendRequestException("TurnRunning", "FICT a turn still runs", retryable: true);
        });

        ProxiedResponse? response = handler.TryServe(Prefix + path, "POST", null, null);

        Assert.Equal(1, asked);
        Assert.Equal(409, response!.Status);
        Assert.Equal(
            "{\"error_class\":\"TurnRunning\",\"message\":\"FICT a turn still runs\",\"retryable\":true}",
            Encoding.UTF8.GetString(response.Content));
    }

    /// <summary>
    /// Each refusal goes out with the status its class is answered with - the backend's own for
    /// its classes, a remodel run's as a turn's, and this proxy's own for a backend that is not
    /// there; the page reads only `ok` and the body. That the status and the flag are the
    /// backend's own is pinned against chat/server.py itself, through the host
    /// (DeferredRestartTests.TheProxyAnswersARefusedTurnCallWithTheBackendsOwnStatusAndFlag).
    /// </summary>
    [Theory]
    [InlineData("TurnRunning", 409)]
    [InlineData("RemodelRunning", 409)]
    [InlineData("UnknownChat", 404)]
    [InlineData("BackendUnavailable", 503)]
    public void ARefusalIsAnsweredWithTheStatusTheBackendGivesIt(string errorClass, int status)
    {
        var handler = new BackendProxyHandler(
            () => Endpoint,
            MustNotSend,
            () => new BackendRequestException(errorClass, "FICT refused", retryable: false));

        ProxiedResponse? response = handler.TryServe(Prefix + "/sessions/chat-1/messages", "POST", null, null);

        Assert.Equal(status, response!.Status);
        Assert.Contains("\"error_class\":\"" + errorClass + "\"", Encoding.UTF8.GetString(response.Content), StringComparison.Ordinal);
    }

    /// <summary>When nothing waits the host answers null, and the call goes on exactly as before.</summary>
    [Fact]
    public void ACallTheHostLetsThroughIsSentOnUnchanged()
    {
        int asked = 0;
        ProxiedRequest? seen = null;
        var handler = new BackendProxyHandler(
            () => Endpoint,
            request =>
            {
                seen = request;
                return Json(202, "Accepted", "{\"state\":\"running\"}");
            },
            () =>
            {
                asked++;
                return null;
            });

        ProxiedResponse? response = handler.TryServe(
            Prefix + "/sessions/chat-1/messages",
            "POST",
            new[] { new KeyValuePair<string, string>("Authorization", "Bearer 0FAKEtoken") },
            new MemoryStream(Encoding.UTF8.GetBytes("{\"text\":\"why?\"}")));

        Assert.Equal(1, asked);
        Assert.Equal(202, response!.Status);
        Assert.Equal("http://127.0.0.1:51234/sessions/chat-1/messages", seen!.Url.ToString());
        Assert.Equal("{\"text\":\"why?\"}", Encoding.UTF8.GetString(seen.Body!));
    }

    /// <summary>
    /// Nothing else is asked about. Stop must reach the backend while a turn holds a restart back
    /// - the restart waits for that turn - and a disposition or the timing is the engineer's
    /// write to the review the turn produced: sent now, before the restart, it is recorded, and
    /// held until after it, it would only be refused. `POST /sessions` starts a turn too, but
    /// the host is its only caller and makes it wait itself.
    /// </summary>
    [Theory]
    [InlineData("GET", "/sessions/chat-1/snapshot")]
    [InlineData("GET", "/sessions/chat-1/evidence")]
    [InlineData("POST", "/sessions/chat-1/stop")]
    [InlineData("POST", "/sessions/chat-1/findings/finding-1/disposition")]
    [InlineData("POST", "/sessions/chat-1/timing")]
    [InlineData("POST", "/sessions")]
    [InlineData("POST", "/sessions/chat-1/messages/extra")]
    [InlineData("POST", "/checks/rms")]
    [InlineData("POST", "/engineering-context/run-1/init")]
    [InlineData("POST", "/remodel/plan")]
    public void NoOtherCallIsAskedAbout(string method, string path)
    {
        int asked = 0;
        var handler = new BackendProxyHandler(
            () => Endpoint,
            _ => Json(200, "OK", "{}"),
            () =>
            {
                asked++;
                return new BackendRequestException("TurnRunning", "FICT must not be asked", retryable: true);
            });

        ProxiedResponse? response = handler.TryServe(Prefix + path, method, null, null);

        Assert.Equal(0, asked);
        Assert.Equal(200, response!.Status);
        Assert.Null(handler.TryServe("https://swreview.invalid/Review/ReviewPage/app.js", "POST", null, null));
        Assert.Equal(0, asked);
    }

    /// <summary>
    /// The host is asked before the backend is looked for: during the restart there is no
    /// backend, and a call that would start a turn is held to the host's answer rather than
    /// told the backend is not running.
    /// </summary>
    [Fact]
    public void ACallThatWouldStartATurnIsAskedAboutEvenWhileThereIsNoBackend()
    {
        var refusing = new BackendProxyHandler(
            () => null,
            MustNotSend,
            () => new BackendRequestException("UnknownChat", "FICT the chat ended with the restart", retryable: false));
        Assert.Equal(404, refusing.TryServe(Prefix + "/sessions/chat-1/send", "POST", null, null)!.Status);

        var letting = new BackendProxyHandler(() => null, MustNotSend, () => null);
        ProxiedResponse? response = letting.TryServe(Prefix + "/sessions/chat-1/send", "POST", null, null);
        Assert.Equal(503, response!.Status);
        Assert.Contains("BackendUnavailable", Encoding.UTF8.GetString(response.Content), StringComparison.Ordinal);
    }

    /// <summary>
    /// A host that throws instead of answering still leaves the page with an answer - the
    /// proxy's own `ProxyFailed` - and the call unsent: an unanswered request is the one outcome
    /// the page cannot tell from the web filter this proxy routes around.
    /// </summary>
    [Fact]
    public void AHostThatThrowsLeavesTheCallAnsweredAndUnsent()
    {
        var handler = new BackendProxyHandler(
            () => Endpoint,
            MustNotSend,
            () => throw new InvalidOperationException("FICT the host broke"));

        ProxiedResponse? response = handler.TryServe(Prefix + "/sessions/chat-1/messages", "POST", null, null);

        Assert.Equal(500, response!.Status);
        string body = Encoding.UTF8.GetString(response.Content);
        Assert.Contains("ProxyFailed", body, StringComparison.Ordinal);
        Assert.Contains("FICT the host broke", body, StringComparison.Ordinal);
        Assert.Contains("\"retryable\":false", body, StringComparison.Ordinal);
    }

    /// <summary>
    /// The calls the host is asked about are exactly the backend's routes that start a turn, or
    /// resume one - every route chat/server.py serves whose handler moves a chat to `RUNNING`,
    /// read from that source - save `POST /sessions`, which only the host makes and which waits
    /// for the restart itself. A turn route the backend gains is asked about, or this fails.
    /// </summary>
    [Fact]
    public void TheCallsAskedAboutAreTheBackendsOwnTurnRoutes()
    {
        IReadOnlyList<(string Method, string Path, bool StartsATurn)> routes = ChatServerSource.Routes();
        Assert.Contains(routes, route => route.StartsATurn && route.Path == "/sessions/{chat_id}/messages");

        var wrong = new List<string>();
        foreach ((string method, string path, bool startsATurn) in routes)
        {
            int asked = 0;
            var handler = new BackendProxyHandler(
                () => Endpoint,
                _ => Json(200, "OK", "{}"),
                () =>
                {
                    asked++;
                    return null;
                });
            string concrete = System.Text.RegularExpressions.Regex.Replace(path, @"\{(\w+)\}", "FICT-$1");

            handler.TryServe(Prefix + concrete, method, null, null);

            bool expected = startsATurn && path != "/sessions";
            if ((asked == 1) != expected)
            {
                wrong.Add($"{method} {path}: asked {asked}, starts a turn {startsATurn}");
            }
        }

        Assert.True(wrong.Count == 0, "The proxy's question does not match the backend's turn routes: " + string.Join("; ", wrong));
    }

    // ---- a turn call holds the bridge while it is out (owner decision 152A, the Codex review: X2) --

    /// <summary>
    /// A call that would start a turn holds the tool service's attachment for as long as it is out,
    /// so a follow of the active document that asked whether a turn runs before this one began does
    /// not take the bridge down under it; the backend marks the turn running before it answers, so
    /// from then on the follow's own question sees it, and the hold is let go.
    /// </summary>
    [Theory]
    [MemberData(nameof(CallsThatStartATurn))]
    public void ACallThatWouldStartATurnHoldsTheBridgeWhileItIsOut(string path)
    {
        var holds = new CountedHolds();
        int heldWhileOut = -1;
        var handler = new BackendProxyHandler(
            () => Endpoint,
            _ =>
            {
                heldWhileOut = holds.Held;
                return Json(202, "Accepted", "{\"state\":\"running\"}");
            },
            () => null,
            holds.Take);

        ProxiedResponse? response = handler.TryServe(Prefix + path, "POST", null, null);

        Assert.Equal(202, response!.Status);
        Assert.Equal(1, heldWhileOut);
        Assert.Equal(1, holds.Taken);
        Assert.Equal(0, holds.Held);
    }

    /// <summary>Every other call starts no turn, and holds nothing.</summary>
    [Theory]
    [InlineData("GET", "/sessions/chat-1/snapshot")]
    [InlineData("POST", "/sessions/chat-1/stop")]
    [InlineData("POST", "/sessions/chat-1/findings/finding-1/disposition")]
    [InlineData("POST", "/sessions")]
    [InlineData("POST", "/remodel/plan")]
    public void NoOtherCallHoldsTheBridge(string method, string path)
    {
        var holds = new CountedHolds();
        var handler = new BackendProxyHandler(() => Endpoint, _ => Json(200, "OK", "{}"), () => null, holds.Take);

        Assert.Equal(200, handler.TryServe(Prefix + path, method, null, null)!.Status);
        Assert.Null(handler.TryServe("https://swreview.invalid/Review/ReviewPage/app.js", "POST", null, null));
        Assert.Equal(0, holds.Taken);
    }

    /// <summary>A turn call the host refuses is never sent, and holds nothing.</summary>
    [Fact]
    public void ATurnCallTheHostRefusesHoldsNothing()
    {
        var holds = new CountedHolds();
        var handler = new BackendProxyHandler(
            () => Endpoint,
            MustNotSend,
            () => new BackendRequestException("TurnRunning", "FICT a turn still runs", retryable: true),
            holds.Take);

        Assert.Equal(409, handler.TryServe(Prefix + "/sessions/chat-1/messages", "POST", null, null)!.Status);
        Assert.Equal(0, holds.Taken);
    }

    /// <summary>The hold is let go however the call ends: answered, unreachable, refused by this side, or with no backend.</summary>
    [Theory]
    [InlineData("answered", 202)]
    [InlineData("unreachable", 502)]
    [InlineData("proxy failed", 500)]
    [InlineData("no backend", 503)]
    public void TheHoldIsLetGoHoweverTheCallEnds(string ending, int status)
    {
        var holds = new CountedHolds();
        var handler = new BackendProxyHandler(
            () => ending == "no backend" ? null : Endpoint,
            _ =>
            {
                if (ending == "unreachable")
                {
                    throw new WebException("FICT connection refused");
                }

                if (ending == "proxy failed")
                {
                    throw new ArgumentException("FICT restricted header");
                }

                return Json(202, "Accepted", "{}");
            },
            () => null,
            holds.Take);

        ProxiedResponse? response = handler.TryServe(Prefix + "/sessions/chat-1/send", "POST", null, null);

        Assert.Equal(status, response!.Status);
        Assert.Equal(1, holds.Taken);
        Assert.Equal(0, holds.Held);
    }

    /// <summary>
    /// With no hold to be had - no tool service listening, or one being taken down - the call goes on as
    /// before: its chat's bridge was given when the chat was made, and serves the attachment going away
    /// or none, so waiting would change nothing it reaches.
    /// </summary>
    [Fact]
    public void WithNoHoldToBeHadATurnCallGoesOn()
    {
        int sent = 0;
        var handler = new BackendProxyHandler(
            () => Endpoint,
            _ =>
            {
                sent++;
                return Json(202, "Accepted", "{}");
            },
            () => null,
            () => null);

        Assert.Equal(202, handler.TryServe(Prefix + "/sessions/chat-1/messages", "POST", null, null)!.Status);
        Assert.Equal(1, sent);
    }

    /// <summary>
    /// A hold the host cannot give - its gate throws - leaves the call answered `ProxyFailed` and
    /// unsent, as a host that throws instead of answering its refusal does: a turn is never started
    /// with nothing holding its bridge, and the page is never left without an answer.
    /// </summary>
    [Fact]
    public void AHoldThatThrowsLeavesTheCallAnsweredAndUnsent()
    {
        var handler = new BackendProxyHandler(
            () => Endpoint,
            MustNotSend,
            () => null,
            () => throw new InvalidOperationException("FICT the gate broke"));

        ProxiedResponse? response = handler.TryServe(Prefix + "/sessions/chat-1/messages", "POST", null, null);

        Assert.Equal(500, response!.Status);
        string body = Encoding.UTF8.GetString(response.Content);
        Assert.Contains("ProxyFailed", body, StringComparison.Ordinal);
        Assert.Contains("FICT the gate broke", body, StringComparison.Ordinal);
        Assert.Contains("\"retryable\":false", body, StringComparison.Ordinal);
    }

    private static ProxiedResponse MustNotSend(ProxiedRequest request) =>
        throw new InvalidOperationException("the handler must not have sent this request");

    private static ProxiedResponse Json(int status, string reason, string body) =>
        new ProxiedResponse(status, reason, "Content-Type: application/json", Encoding.UTF8.GetBytes(body));
}
