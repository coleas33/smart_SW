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

    private static ProxiedResponse MustNotSend(ProxiedRequest request) =>
        throw new InvalidOperationException("the handler must not have sent this request");

    private static ProxiedResponse Json(int status, string reason, string body) =>
        new ProxiedResponse(status, reason, "Content-Type: application/json", Encoding.UTF8.GetBytes(body));
}
