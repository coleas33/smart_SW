using System;
using System.Globalization;

namespace SwReview.AddIn.Review;

/// <summary>
/// Lets the pane's pages reach the backend without any browser process making an HTTP
/// request to it.
///
/// <b>Why.</b> Endpoint security products intercept HTTP from browser processes. On the
/// pilot workstation Sophos Web Protection answers <c>http://127.0.0.1:&lt;port&gt;</c>
/// with a "Warning: Uncategorized" interstitial, so every page <c>fetch</c> received a 403
/// carrying no CORS headers while the backend itself logged 204. A <c>fetch</c> cannot
/// click through an interstitial, so the pane was blind even though the review ran to
/// completion. Requests made by the add-in's own C# code are not intercepted.
///
/// <b>How.</b> The pages are told their backend lives at <see cref="PageOrigin"/> - their
/// <i>own</i> origin, under <see cref="PathPrefix"/>. Nothing leaves the page - not the
/// backend calls and not the page's own files: WebView2 raises <c>WebResourceRequested</c>
/// for <see cref="TaskPaneControl.PageResourceFilter"/>, the whole page origin, and one
/// handler answers all of it - <c>BackendProxyHandler.TryServe</c> serves
/// <see cref="PathPrefix"/> by calling the loopback backend from C#, and
/// <c>PageFileServer</c> serves everything else out of the web folder. Same-origin also
/// means no CORS and no preflight, so the whole class of origin, private-network and
/// web-filter failures stops applying to the pane.
///
/// The event stream is deliberately <b>not</b> proxied here. A
/// <c>WebResourceRequested</c> response must have all of its content available when the
/// deferral completes (WebView2 documents this, and WebView2 reads every response stream
/// on one background thread, so a blocking read stalls every other request), which makes
/// server-sent events impossible to serve this way. The host reads that one route itself
/// and pushes each frame to the page over the message channel instead.
/// </summary>
public static class BackendProxy
{
    /// <summary>The path every proxied call sits under, chosen not to collide with the page.</summary>
    public const string PathPrefix = "/__backend";

    /// <summary>
    /// What the hosts put in `init.backend.origin`. The pages concatenate it with the path
    /// they want, so it carries the prefix and no trailing slash.
    /// </summary>
    public static string PageOrigin => TaskPaneControl.PageOrigin + PathPrefix;

    /// <summary>
    /// Maps a page URL to the backend URL it stands for.
    /// </summary>
    /// <param name="requestUri">The URL WebView2 was asked for.</param>
    /// <param name="endpoint">Where the backend is listening.</param>
    /// <param name="target">The loopback URL to call, or null when this is not ours.</param>
    /// <returns>True when the URL is under the prefix and was mapped.</returns>
    public static bool TryMapToBackend(string requestUri, BackendEndpoint endpoint, out Uri? target)
    {
        target = null;
        if (string.IsNullOrWhiteSpace(requestUri) || endpoint == null)
        {
            return false;
        }

        if (!Uri.TryCreate(requestUri, UriKind.Absolute, out Uri? parsed))
        {
            return false;
        }

        // Compare against the parsed URL rather than the original text: `Uri` has already
        // resolved `..` segments and normalized the case, so a traversal cannot smuggle a
        // path past the prefix check and then reappear on the way out.
        string origin = parsed.GetLeftPart(UriPartial.Authority);
        if (!string.Equals(origin, TaskPaneControl.PageOrigin, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        string path = parsed.AbsolutePath;
        if (!path.StartsWith(PathPrefix + "/", StringComparison.Ordinal))
        {
            // `/__backendish/...` must not match, so the separator is required rather than
            // treating the prefix as a bare string prefix.
            return false;
        }

        string remainder = path.Substring(PathPrefix.Length);
        target = new Uri(
            string.Format(
                CultureInfo.InvariantCulture,
                "http://127.0.0.1:{0}{1}{2}",
                endpoint.Port,
                remainder,
                parsed.Query),
            UriKind.Absolute);
        return true;
    }
}
