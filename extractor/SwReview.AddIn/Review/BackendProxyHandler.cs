using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;

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
/// Four refusals are answered rather than forwarded, each in the
/// `{error_class, message, retryable}` shape the pages already render:
/// <list type="bullet">
/// <item>no backend yet - the pane opens before the child has handshaken;</item>
/// <item>the event stream - it cannot be served through `WebResourceRequested` at all,
/// because the response must be complete when the deferral ends, so asking for it here is
/// a bug in the page rather than something to half-answer;</item>
/// <item>the call failed - a dead child must read as a backend problem, not a blank page;</item>
/// <item>the call could not be made at all - `ProxyFailed`, which is this side breaking
/// rather than the backend's, and is not retryable.</item>
/// </list>
/// </summary>
public sealed class BackendProxyHandler
{
    /// <summary>The one route that must never come through here; see the class remarks.</summary>
    public const string EventStreamSuffix = "/events";

    private static readonly TimeSpan CallTimeout = TimeSpan.FromSeconds(120);

    private readonly Func<BackendEndpoint?> _endpoint;
    private readonly Func<ProxiedRequest, ProxiedResponse> _send;

    public BackendProxyHandler(Func<BackendEndpoint?> endpoint, Func<ProxiedRequest, ProxiedResponse> send)
    {
        _endpoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
        _send = send ?? throw new ArgumentNullException(nameof(send));
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

        var request = new ProxiedRequest(target, method, Forwardable(headers), Read(content));

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
            return Error(
                500,
                "Internal Server Error",
                "ProxyFailed",
                "the pane could not make this call: " + failure.Message,
                retryable: false);
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
