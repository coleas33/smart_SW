using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Text.Json;

namespace SwReview.AddIn.Review;

/// <summary>One call on its way to the backend, as the host will make it.</summary>
public sealed class ProxiedRequest
{
    public ProxiedRequest(Uri url, string method, IList<KeyValuePair<string, string>> headers, byte[]? body)
    {
        Url = url ?? throw new ArgumentNullException(nameof(url));
        Method = method ?? throw new ArgumentNullException(nameof(method));
        Headers = headers ?? new List<KeyValuePair<string, string>>();
        Body = body;
    }

    public Uri Url { get; }

    public string Method { get; }

    /// <summary>Only the headers the backend should see; see `BackendProxyHandler`.</summary>
    public IList<KeyValuePair<string, string>> Headers { get; }

    public byte[]? Body { get; }
}

/// <summary>What the host hands back to WebView2 for one proxied call.</summary>
public sealed class ProxiedResponse
{
    public ProxiedResponse(int status, string reason, string headers, byte[] content)
    {
        Status = status;
        Reason = reason ?? string.Empty;
        Headers = headers ?? string.Empty;
        Content = content ?? new byte[0];
    }

    public int Status { get; }

    public string Reason { get; }

    /// <summary>`Name: value` pairs joined by CRLF, which is the shape WebView2 takes.</summary>
    public string Headers { get; }

    public byte[] Content { get; }
}

/// <summary>
/// Serves the pane's proxied backend calls (<see cref="BackendProxy"/>) from C#.
///
/// The transport is injected, so every rule below is pinned without WebView2, a backend or
/// a socket. <see cref="Send"/> is the real one: `HttpWebRequest` with `Proxy = null`,
/// matching <see cref="BackendClient"/> - which is not incidental here, because a proxy
/// consulted for 127.0.0.1 is the failure this whole class exists to route around.
///
/// Five refusals are answered rather than forwarded, each in the
/// `{error_class, message, retryable}` shape the pages already render:
/// <list type="bullet">
/// <item>no backend yet - the pane opens before the child has handshaken;</item>
/// <item>the event stream - it cannot be served through `WebResourceRequested` at all,
/// because the response must be complete when the deferral ends, so asking for it here is
/// a bug in the page rather than something to half-answer;</item>
/// <item>the call failed - a dead child must read as a backend problem, not a blank page;</item>
/// <item>the call could not be made at all - `ProxyFailed`, which is this side breaking
/// rather than the backend's, and is not retryable;</item>
/// <item>a call that would start a turn while the backend waits to be restarted with
/// settings saved during a turn - the host's answer, since the call is for a chat of the
/// backend being replaced and must not start a turn there (owner decision 143A).</item>
/// </list>
///
/// And a call that would start a turn holds the tool service's attachment while it is out (owner
/// decision 152A, on the Codex review: X2), so no follow of the active document takes the bridge
/// down under the turn it starts.
///
/// And a check page's evaluation of a check - `POST /checks/rms` or `/checks/standards` - holds that
/// check's hold on a settings restart while it is out, asked of the host by the run folder its body
/// names (owner decision 157A): a check holds the restart back from its gate until the page's
/// evaluation of it has been answered, so the evaluation never meets a backend that restarted under it.
/// </summary>
public sealed class BackendProxyHandler
{
    /// <summary>The one route that must never come through here; see the class remarks.</summary>
    public const string EventStreamSuffix = "/events";

    private static readonly TimeSpan CallTimeout = TimeSpan.FromSeconds(120);

    private readonly Func<BackendEndpoint?> _endpoint;
    private readonly Func<ProxiedRequest, ProxiedResponse> _send;
    private readonly Func<BackendRequestException?> _turnRefusal;
    private readonly Func<IDisposable?> _holdTheBridge;
    private readonly Func<string, string?, IDisposable?> _holdTheCheck;

    public BackendProxyHandler(Func<BackendEndpoint?> endpoint, Func<ProxiedRequest, ProxiedResponse> send)
        : this(endpoint, send, () => null)
    {
    }

    /// <param name="endpoint">Where the backend is, asked per call.</param>
    /// <param name="send">The transport.</param>
    /// <param name="turnRefusal">Asked, per call, before a call that would start a turn is sent:
    /// null sends it on as always, and a refusal is answered instead (owner decision 143A).</param>
    public BackendProxyHandler(
        Func<BackendEndpoint?> endpoint,
        Func<ProxiedRequest, ProxiedResponse> send,
        Func<BackendRequestException?> turnRefusal)
        : this(endpoint, send, turnRefusal, () => ToolServiceHold.Nothing)
    {
    }

    /// <param name="endpoint">Where the backend is, asked per call.</param>
    /// <param name="send">The transport.</param>
    /// <param name="turnRefusal">As above.</param>
    /// <param name="holdTheBridge">Owner decision 152A, on the Codex review (X2): asked, per call that
    /// would start a turn and is not refused, for a hold on the tool service's attachment, which is
    /// let go once the call is answered: the backend marks the turn running before it answers, so a
    /// follow of the active document whose busy question was had before the turn began does not take
    /// the bridge down under it. Null - none listening to hold - sends the call on as before.</param>
    public BackendProxyHandler(
        Func<BackendEndpoint?> endpoint,
        Func<ProxiedRequest, ProxiedResponse> send,
        Func<BackendRequestException?> turnRefusal,
        Func<IDisposable?> holdTheBridge)
        : this(endpoint, send, turnRefusal, holdTheBridge, (_, __) => null)
    {
    }

    /// <param name="endpoint">Where the backend is, asked per call.</param>
    /// <param name="send">The transport.</param>
    /// <param name="turnRefusal">As above.</param>
    /// <param name="holdTheBridge">As above.</param>
    /// <param name="holdTheCheck">Owner decision 157A: asked, per evaluation of a check - `POST /checks/rms` or
    /// `/checks/standards` - with the run folder its body names and the bearer token it carries (the final reviews of
    /// 157A: the backend that will answer it is the one whose token it is), for the hold that check keeps on a
    /// settings restart, which is let go once the evaluation is answered, however it is. Null - no check waits for
    /// that evaluation - sends it on unheld, as before; and so does a host that throws, since an evaluation refused
    /// would waste the very extraction the hold exists to keep.</param>
    public BackendProxyHandler(
        Func<BackendEndpoint?> endpoint,
        Func<ProxiedRequest, ProxiedResponse> send,
        Func<BackendRequestException?> turnRefusal,
        Func<IDisposable?> holdTheBridge,
        Func<string, string?, IDisposable?> holdTheCheck)
    {
        _endpoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
        _send = send ?? throw new ArgumentNullException(nameof(send));
        _turnRefusal = turnRefusal ?? throw new ArgumentNullException(nameof(turnRefusal));
        _holdTheBridge = holdTheBridge ?? throw new ArgumentNullException(nameof(holdTheBridge));
        _holdTheCheck = holdTheCheck ?? throw new ArgumentNullException(nameof(holdTheCheck));
    }

    /// <summary>
    /// Answers one page request, or returns null when the URL is not ours - in which case
    /// WebView2 serves it normally, which is how the page's own HTML and scripts still load.
    /// </summary>
    public ProxiedResponse? TryServe(
        string requestUri,
        string method,
        IEnumerable<KeyValuePair<string, string>>? headers,
        Stream? content)
    {
        // Read once: every call forwards it, and a check's evaluation is held by the folder it names.
        byte[]? body = Read(content);

        if (EvaluatesACheck(requestUri, method))
        {
            return ForwardHoldingTheCheck(requestUri, method, headers, body);
        }

        if (!StartsATurn(requestUri, method))
        {
            return Forward(requestUri, method, headers, body);
        }

        // Before the backend is looked for: while the backend is being restarted there is
        // none, and a call that would start a turn is held to the host's answer rather than
        // told the backend is not running.
        ProxiedResponse? refused = RefuseTurn();
        if (refused != null)
        {
            return refused;
        }

        // Owner decision 152A, on the Codex review (X2): the call is held to the tool service's
        // attachment while it is out, and let go once it is answered. A hold that cannot be asked for
        // is answered as a host that throws instead of answering is, and the call is not sent; none
        // to be had sends it on as before - its chat's bridge, given when the chat was made, serves
        // the attachment going away or none, and waiting would change nothing it reaches.
        IDisposable? hold;
        try
        {
            hold = _holdTheBridge();
        }
        catch (Exception failure)
        {
            return ProxyFailed(failure);
        }

        try
        {
            return Forward(requestUri, method, headers, body);
        }
        finally
        {
            hold?.Dispose();
        }
    }

    /// <summary>
    /// Owner decision 157A: sends a check page's evaluation of a check on holding that check's hold on a settings
    /// restart for as long as it is out - asked of the host by the run folder the body names - and lets it go once
    /// the evaluation is answered, however it is: answered, refused by the backend, unreachable, refused by this side,
    /// or with no backend. With no hold to be had the evaluation goes on unheld, as before.
    /// </summary>
    private ProxiedResponse? ForwardHoldingTheCheck(
        string requestUri,
        string method,
        IEnumerable<KeyValuePair<string, string>>? headers,
        byte[]? body)
    {
        IDisposable? hold = HoldTheCheck(RunDirectoryOf(body), BearerTokenOf(headers));
        try
        {
            return Forward(requestUri, method, headers, body);
        }
        finally
        {
            hold?.Dispose();
        }
    }

    /// <summary>
    /// The host's hold of the check whose run is in <paramref name="runDirectory"/>, asked with the bearer
    /// <paramref name="token"/> the evaluation carries, or null: no folder named, no check waiting for its evaluation,
    /// or a host that throws - which leaves the evaluation as it was before 157A, since an evaluation refused would
    /// waste the very extraction the hold exists to keep.
    /// </summary>
    private IDisposable? HoldTheCheck(string? runDirectory, string? token)
    {
        if (runDirectory == null)
        {
            return null;
        }

        try
        {
            return _holdTheCheck(runDirectory, token);
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>
    /// The final reviews of 157A: the bearer token a page's call carries in its `Authorization` header - the token of
    /// the backend that gave the page its `init`, which only that backend takes - or null when it carries none.
    /// </summary>
    private static string? BearerTokenOf(IEnumerable<KeyValuePair<string, string>>? headers)
    {
        const string Scheme = "Bearer ";
        if (headers == null)
        {
            return null;
        }

        foreach (KeyValuePair<string, string> header in headers)
        {
            if (string.Equals(header.Key, "Authorization", StringComparison.OrdinalIgnoreCase)
                && header.Value != null
                && header.Value.StartsWith(Scheme, StringComparison.OrdinalIgnoreCase))
            {
                string token = header.Value.Substring(Scheme.Length).Trim();
                return token.Length == 0 ? null : token;
            }
        }

        return null;
    }

    /// <summary>
    /// The run folder an evaluation's body names - its `run_dir`, as the page relays it from the host's own reply - or
    /// null when the body is not a JSON object naming one as text.
    /// </summary>
    private static string? RunDirectoryOf(byte[]? body)
    {
        if (body == null)
        {
            return null;
        }

        try
        {
            using (JsonDocument document = JsonDocument.Parse(body))
            {
                return document.RootElement.ValueKind == JsonValueKind.Object
                    && document.RootElement.TryGetProperty("run_dir", out JsonElement runDirectory)
                    && runDirectory.ValueKind == JsonValueKind.String
                    ? runDirectory.GetString()
                    : null;
            }
        }
        catch (JsonException)
        {
            return null;
        }
    }

    /// <summary>
    /// Whether a page call evaluates a check (owner decision 157A): a `POST` to `/checks/rms` or `/checks/standards`,
    /// the backend's two routes that grade a run (chat-api.md). Read from the path the backend would route, as
    /// <see cref="StartsATurn"/> reads it.
    /// </summary>
    private static bool EvaluatesACheck(string requestUri, string method)
    {
        string[]? segments = PostedSegments(requestUri, method);
        return segments != null
            && segments.Length == 2
            && segments[0] == "checks"
            && (segments[1] == "rms" || segments[1] == "standards");
    }

    /// <summary>
    /// The path a `POST` under the backend prefix would be routed by, unescaped, segment by segment - so a trailing
    /// slash or an escaped letter is the same call - or null for any other call.
    /// </summary>
    private static string[]? PostedSegments(string requestUri, string method)
    {
        // Port 0 only answers "is this the prefix", as for a call with no backend yet.
        if (!string.Equals(method, "POST", StringComparison.OrdinalIgnoreCase)
            || !BackendProxy.TryMapToBackend(requestUri, new BackendEndpoint(0, "none"), out Uri? target))
        {
            return null;
        }

        string[] segments = target!.AbsolutePath.Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries);
        for (int index = 0; index < segments.Length; index++)
        {
            segments[index] = Uri.UnescapeDataString(segments[index]);
        }

        return segments;
    }

    /// <summary>
    /// Sends one call on to the backend and answers what it answered, or the proxy's own refusal: no
    /// backend yet, the event stream, a backend that did not answer, a call this side could not make.
    /// </summary>
    private ProxiedResponse? Forward(
        string requestUri,
        string method,
        IEnumerable<KeyValuePair<string, string>>? headers,
        byte[]? body)
    {
        BackendEndpoint? endpoint = _endpoint();
        if (endpoint == null)
        {
            // Still not ours unless the URL is under the prefix: a missing backend must not
            // swallow the page's own resources. Port 0 only answers "is this the prefix".
            return BackendProxy.TryMapToBackend(requestUri, new BackendEndpoint(0, "none"), out _)
                ? Error(503, "Backend Unavailable", "BackendUnavailable",
                    "the review backend is not running yet.", retryable: true)
                : null;
        }

        if (!BackendProxy.TryMapToBackend(requestUri, endpoint, out Uri? target))
        {
            return null;
        }

        if (target!.AbsolutePath.EndsWith(EventStreamSuffix, StringComparison.Ordinal))
        {
            return Error(
                501,
                "Not Implemented",
                "StreamNotProxyable",
                "the event stream is delivered over the page message channel, not over HTTP; "
                    + "this page asked for it the old way.",
                retryable: false);
        }

        var request = new ProxiedRequest(target, method, Forwardable(headers), body);

        try
        {
            return _send(request);
        }
        catch (Exception failure) when (failure is WebException || failure is IOException)
        {
            return Error(
                502,
                "Bad Gateway",
                "BackendUnavailable",
                "the review backend did not answer: " + failure.Message,
                retryable: true);
        }
        catch (Exception failure)
        {
            // Anything else is the proxy refusing to make the call rather than the backend
            // failing to answer it - `HttpWebRequest.Headers` throwing `ArgumentException`
            // for a restricted header is the one that has actually happened. It is not a
            // `WebException`, so without this the request would be left with no response at
            // all, which the page cannot tell apart from the web filter it is routing
            // around. Answered, not retryable, and named differently from the backend's own
            // failures so a log says which side broke.
            return ProxyFailed(failure);
        }
    }

    /// <summary>
    /// This side's own failure to make a call, answered: `ProxyFailed`, not retryable, carrying what
    /// failed - never a request left with no answer.
    /// </summary>
    private static ProxiedResponse ProxyFailed(Exception failure) =>
        Error(
            500,
            "Internal Server Error",
            "ProxyFailed",
            "the pane could not make this call: " + failure.Message,
            retryable: false);

    /// <summary>
    /// Whether a page call would start a turn, or resume one: a `POST` to
    /// `/sessions/{chat_id}/messages`, `/send`, `/evidence` or `/evidence/{request_id}`
    /// (chat-api.md). Read from the path the backend would route, so a trailing slash or an
    /// escaped letter is the same call. `POST /sessions` starts a turn too, but only the host
    /// makes it, and the host waits for a restart there itself; Stop, a disposition and the
    /// timing start none.
    /// </summary>
    private static bool StartsATurn(string requestUri, string method)
    {
        string[]? segments = PostedSegments(requestUri, method);
        if (segments == null || segments.Length < 3 || segments[0] != "sessions")
        {
            return false;
        }

        switch (segments[2])
        {
            case "messages":
            case "send":
                return segments.Length == 3;

            case "evidence":
                return segments.Length == 3 || segments.Length == 4;

            default:
                return false;
        }
    }

    /// <summary>
    /// The host's answer to a call that would start a turn, as a response, or null to send the
    /// call on. Each refusal goes out with the status the backend gives its class - `TurnRunning`
    /// 409 and `UnknownChat` 404, as chat/server.py answers them, a remodel run's
    /// `RemodelRunning` 409 and a check's `CheckRunning` 409 (owner decision 157A) as a turn's, and
    /// `BackendUnavailable` 503 as this proxy answers a
    /// backend that is not there - and the host's `retryable` flag, which is the backend's for
    /// the backend's classes. The words are the host's own, and say why. A host that throws is
    /// answered as any call this side could not make is: never with no answer.
    /// </summary>
    private ProxiedResponse? RefuseTurn()
    {
        BackendRequestException? refusal;
        try
        {
            refusal = _turnRefusal();
        }
        catch (Exception failure)
        {
            return ProxyFailed(failure);
        }

        if (refusal == null)
        {
            return null;
        }

        switch (refusal.ErrorClass)
        {
            case "TurnRunning":
            case "RemodelRunning":
            case "CheckRunning":
                return Error(409, "Conflict", refusal.ErrorClass, refusal.Message, refusal.Retryable);

            case "UnknownChat":
                return Error(404, "Not Found", refusal.ErrorClass, refusal.Message, refusal.Retryable);

            default:
                return Error(503, "Service Unavailable", refusal.ErrorClass, refusal.Message, refusal.Retryable);
        }
    }

    /// <summary>
    /// The headers the backend should see.
    ///
    /// `Authorization` is the point of the exercise - the backend refuses without it.
    /// `Origin` is dropped deliberately: the page's origin is the virtual host, and sending
    /// it on would make the backend's own origin guard refuse the very call this proxy
    /// exists to deliver. `Host`, `Content-Length` and the `Sec-` set describe a request
    /// that is not the one being made - and so, for the same reason, do `User-Agent` and
    /// `Referer`: this request is not being made by a browser and did not come from a page
    /// the backend has ever heard of. Dropping those two is also what keeps
    /// <see cref="Send"/> off the restricted headers `HttpWebRequest` refuses to set, and
    /// they are two of the nine a real WebView2 `fetch` carries.
    ///
    /// `Accept-Encoding` goes too. <see cref="Send"/> sets no `AutomaticDecompression`, so a
    /// backend that took the offer would hand back a compressed body with a
    /// `Content-Encoding` header that <see cref="FormatResponseHeaders"/> copies through -
    /// a coupling between two methods that is much easier to sever here than to get right.
    /// </summary>
    private static IList<KeyValuePair<string, string>> Forwardable(
        IEnumerable<KeyValuePair<string, string>>? headers)
    {
        var kept = new List<KeyValuePair<string, string>>();
        if (headers == null)
        {
            return kept;
        }

        foreach (KeyValuePair<string, string> header in headers)
        {
            if (string.IsNullOrEmpty(header.Key)
                || header.Key.Equals("Host", StringComparison.OrdinalIgnoreCase)
                || header.Key.Equals("Origin", StringComparison.OrdinalIgnoreCase)
                || header.Key.Equals("Content-Length", StringComparison.OrdinalIgnoreCase)
                || header.Key.Equals("Connection", StringComparison.OrdinalIgnoreCase)
                || header.Key.Equals("User-Agent", StringComparison.OrdinalIgnoreCase)
                || header.Key.Equals("Referer", StringComparison.OrdinalIgnoreCase)
                || header.Key.Equals("Accept-Encoding", StringComparison.OrdinalIgnoreCase)
                || header.Key.StartsWith("Sec-", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            kept.Add(header);
        }

        return kept;
    }

    private static byte[]? Read(Stream? content)
    {
        if (content == null)
        {
            return null;
        }

        using (var buffer = new MemoryStream())
        {
            content.CopyTo(buffer);
            byte[] bytes = buffer.ToArray();
            return bytes.Length == 0 ? null : bytes;
        }
    }

    /// <summary>
    /// The real transport: `HttpWebRequest` straight at loopback with no proxy.
    ///
    /// Synchronous on purpose, like <see cref="BackendClient"/>; the WebView2 handler takes
    /// a deferral and runs this off the UI thread.
    /// </summary>
    public static ProxiedResponse Send(ProxiedRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        var web = (HttpWebRequest)WebRequest.Create(request.Url);
        web.Method = request.Method;
        web.Timeout = (int)CallTimeout.TotalMilliseconds;
        web.ReadWriteTimeout = (int)CallTimeout.TotalMilliseconds;

        // The corporate proxy must not be consulted for 127.0.0.1; on this workstation it is
        // the interception that made the page's own fetches fail in the first place.
        web.Proxy = null;

        foreach (KeyValuePair<string, string> header in request.Headers)
        {
            if (header.Key.Equals("Content-Type", StringComparison.OrdinalIgnoreCase))
            {
                web.ContentType = header.Value;
            }
            else if (header.Key.Equals("Accept", StringComparison.OrdinalIgnoreCase))
            {
                web.Accept = header.Value;
            }
            else
            {
                web.Headers[header.Key] = header.Value;
            }
        }

        if (request.Body != null)
        {
            web.ContentLength = request.Body.Length;
            using (Stream body = web.GetRequestStream())
            {
                body.Write(request.Body, 0, request.Body.Length);
            }
        }

        try
        {
            using (var response = (HttpWebResponse)web.GetResponse())
            {
                return Capture(response);
            }
        }
        catch (WebException failure) when (failure.Response is HttpWebResponse refused)
        {
            // The backend's own 4xx and 5xx are answers, not transport failures: the pages
            // read `{error_class, message}` out of them.
            using (refused)
            {
                return Capture(refused);
            }
        }
    }

    private static ProxiedResponse Capture(HttpWebResponse response)
    {
        byte[] content;
        using (Stream? stream = response.GetResponseStream())
        {
            if (stream == null)
            {
                content = new byte[0];
            }
            else
            {
                using (var buffer = new MemoryStream())
                {
                    stream.CopyTo(buffer);
                    content = buffer.ToArray();
                }
            }
        }

        return new ProxiedResponse(
            (int)response.StatusCode,
            response.StatusDescription ?? string.Empty,
            FormatResponseHeaders(response.Headers),
            content);
    }

    /// <summary>
    /// The response headers as WebView2 wants them, minus the ones that would describe a
    /// transfer that is no longer happening.
    ///
    /// No CORS header is copied: the page and this response now share an origin, so there
    /// is nothing to allow, and a stray `Access-Control-Allow-Origin` would only re-open
    /// the question this proxy exists to close.
    /// </summary>
    private static string FormatResponseHeaders(WebHeaderCollection headers)
    {
        var lines = new List<string>();
        foreach (string? name in headers.AllKeys)
        {
            if (name == null
                || name.StartsWith("Access-Control-", StringComparison.OrdinalIgnoreCase)
                || name.Equals("Transfer-Encoding", StringComparison.OrdinalIgnoreCase)
                || name.Equals("Content-Length", StringComparison.OrdinalIgnoreCase)
                || name.Equals("Connection", StringComparison.OrdinalIgnoreCase))
            {
                // WebView2 frames the response itself; a stale length or a chunked marker
                // describes a transfer that already finished.
                continue;
            }

            lines.Add(name + ": " + headers[name]);
        }

        return string.Join("\r\n", lines.ToArray());
    }

    /// <summary>An error in the shape the pages already render, so no page needs a new branch.</summary>
    private static ProxiedResponse Error(
        int status, string reason, string errorClass, string message, bool retryable)
    {
        string body = string.Format(
            CultureInfo.InvariantCulture,
            "{{\"error_class\":{0},\"message\":{1},\"retryable\":{2}}}",
            Quote(errorClass),
            Quote(message),
            retryable ? "true" : "false");

        return new ProxiedResponse(
            status, reason, "Content-Type: application/json", Encoding.UTF8.GetBytes(body));
    }

    private static string Quote(string value)
    {
        var text = new StringBuilder("\"");
        foreach (char character in value)
        {
            switch (character)
            {
                case '"': text.Append("\\\""); break;
                case '\\': text.Append("\\\\"); break;
                case '\n': text.Append("\\n"); break;
                case '\r': text.Append("\\r"); break;
                case '\t': text.Append("\\t"); break;
                default: text.Append(character); break;
            }
        }

        return text.Append('"').ToString();
    }
}
