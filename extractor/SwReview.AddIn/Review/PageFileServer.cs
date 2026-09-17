using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace SwReview.AddIn.Review;

/// <summary>
/// Serves the pane's own page files - `index.html`, the scripts, the stylesheets - out of the
/// add-in's `web` folder, from C#, through the same `WebResourceRequested` handler that serves
/// <see cref="BackendProxy"/>'s `/__backend` prefix.
///
/// <b>Why the host serves its own pages.</b> The pages used to be served by
/// `SetVirtualHostNameToFolderMapping`, and WebView2 raises <b>no</b> `WebResourceRequested`
/// for a host that is mapped to a folder: the mapping resolves the request itself, ahead of the
/// event. That makes the same-origin proxy impossible, because the page's own origin is exactly
/// what cannot be intercepted (`docs/pane-backend-proxy.md` section 4, measured in
/// `BackendProxyPageTests`). Dropping the mapping and serving the files here puts the whole
/// origin behind one filter and one handler: `BackendProxyHandler.TryServe` answers the backend
/// prefix, this answers everything else, and `connect-src 'self'` holds with no CORS anywhere.
///
/// <b>What it costs, and what is paid back here.</b> The mapping was also a sandbox - one
/// folder, and no way out of it. `File.ReadAllBytes` is not, so every rule the mapping used to
/// enforce is stated explicitly below and pinned in `PageFileServerTests`:
/// <list type="bullet">
/// <item>the request must be on <see cref="TaskPaneControl.PageOrigin"/>;</item>
/// <item>the path is taken from <see cref="Uri.AbsolutePath"/>, so a <b>query string or a
/// fragment can never choose the file</b>;</item>
/// <item>every segment is decoded first and then refused if it is empty, `.`, `..`, or carries
/// a separator or any character Windows does not allow in a file name - which is what stops
/// `%2e%2e` and a bare drive letter - and the canonical path is <b>checked again</b> to be
/// under the web folder, because one of those two rules holding is not a reason to trust the
/// other;</item>
/// <item>the extension must be one the pages actually ship; anything else is a 404, so a file
/// that finds its way into `web/` is not served merely for being there;</item>
/// <item>there is no directory listing and no implicit `index.html`: the pane navigates to a
/// file name every time.</item>
/// </list>
///
/// Every refusal is the same 404 - same body, same headers - so a page learns only that it did
/// not get what it asked for, never what is on the disk.
/// </summary>
public sealed class PageFileServer
{
    /// <summary>
    /// The extensions the four pages load, and the ones an icon or a webfont would arrive as.
    /// A closed list rather than a lookup, because "what is this file" is the question a static
    /// file server gets wrong: `vendor/` ships a `LICENSES.md` no page loads, and a run folder
    /// that ever landed under `web/` must not become a download.
    /// </summary>
    private static readonly Dictionary<string, string> ContentTypes =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { ".html", "text/html; charset=utf-8" },
            { ".js", "text/javascript; charset=utf-8" },
            { ".css", "text/css; charset=utf-8" },
            { ".json", "application/json; charset=utf-8" },
            { ".svg", "image/svg+xml" },
            { ".png", "image/png" },
            { ".ico", "image/x-icon" },
            { ".woff2", "font/woff2" },
        };

    /// <summary>
    /// `no-store` on everything. The pane rebuilds a tab whenever it is reopened, and an
    /// engineer who has just been given a new build must not be shown the previous one's
    /// script out of the renderer's cache.
    /// </summary>
    private const string CacheControl = "Cache-Control: no-store";

    private static readonly byte[] NotFoundBody = Encoding.UTF8.GetBytes("Not found.");

    /// <summary>The web folder, canonical and without a trailing separator.</summary>
    private readonly string _root;

    /// <param name="webFolder">The folder the pages are served from - `TaskPaneOptions.WebFolder`.</param>
    public PageFileServer(string webFolder)
    {
        if (string.IsNullOrWhiteSpace(webFolder))
        {
            throw new ArgumentNullException(nameof(webFolder));
        }

        // Canonical once, here, so the containment check below compares two full paths rather
        // than a full path against whatever spelling the options carried.
        _root = Path.GetFullPath(webFolder).TrimEnd(Path.DirectorySeparatorChar);
    }

    /// <summary>
    /// Answers one page request. Always answers: this is the last thing in the chain, so a URL
    /// it will not serve is a 404 rather than a null that would leave the request hanging.
    /// </summary>
    public ProxiedResponse Serve(string requestUri)
    {
        string? path = TryResolve(requestUri, out string? contentType);
        if (path == null)
        {
            return NotFound();
        }

        try
        {
            return new ProxiedResponse(
                200, "OK", "Content-Type: " + contentType + "\r\n" + CacheControl,
                File.ReadAllBytes(path));
        }
        catch (IOException)
        {
            // The file is there but cannot be read right now - a build copying over it is the
            // realistic one. Answered as a 404 rather than thrown: this runs off the UI thread
            // under a deferral, and the page's only sensible reaction either way is that the
            // resource is not available.
            return NotFound();
        }
        catch (UnauthorizedAccessException)
        {
            return NotFound();
        }
    }

    /// <summary>
    /// The path rule, in full. Returns the file to read, or null for every refusal.
    /// </summary>
    private string? TryResolve(string requestUri, out string? contentType)
    {
        contentType = null;

        if (string.IsNullOrWhiteSpace(requestUri)
            || !Uri.TryCreate(requestUri, UriKind.Absolute, out Uri? parsed))
        {
            return null;
        }

        if (!string.Equals(
                parsed!.GetLeftPart(UriPartial.Authority),
                TaskPaneControl.PageOrigin,
                StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        // `AbsolutePath` alone, so neither the query string nor the fragment can reach the file
        // system. It is decoded here rather than trusted as `Uri` left it: `%2e%2e` and `%5c`
        // survive parsing on some runtimes and not on others, and a rule that depends on which
        // is a rule that changes under a servicing update.
        string[] segments = Uri.UnescapeDataString(parsed.AbsolutePath).Split('/');

        // `AbsolutePath` always starts with `/`, so the first segment is empty by construction.
        var parts = new List<string>();
        for (int index = 1; index < segments.Length; index++)
        {
            string segment = segments[index];
            if (segment.Length == 0
                || segment == "."
                || segment == ".."
                || segment.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            {
                // The invalid-file-name set is what refuses `\`, a drive letter's `:` and the
                // wildcard characters, so one check covers separators and smuggled roots alike.
                return null;
            }

            parts.Add(segment);
        }

        if (parts.Count == 0)
        {
            // `/` - a directory, and there is no listing and no implicit index.
            return null;
        }

        if (!ContentTypes.TryGetValue(
                Path.GetExtension(parts[parts.Count - 1]), out string? type))
        {
            return null;
        }

        string candidate;
        try
        {
            candidate = Path.GetFullPath(Path.Combine(_root, Path.Combine(parts.ToArray())));
        }
        catch (Exception failure) when (failure is ArgumentException
            || failure is PathTooLongException
            || failure is NotSupportedException)
        {
            return null;
        }

        // The second half of the traversal rule. The segment check above should already have
        // made this impossible; it is here because "should already" is not a guarantee, and
        // this is the line that decides whether the pane can read the rest of the disk.
        if (!candidate.StartsWith(_root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
            || !File.Exists(candidate))
        {
            return null;
        }

        contentType = type;
        return candidate;
    }

    /// <summary>One 404 for every refusal, so none of them says what is on the disk.</summary>
    private static ProxiedResponse NotFound() => new ProxiedResponse(
        404,
        "Not Found",
        "Content-Type: text/plain; charset=utf-8\r\n" + CacheControl,
        NotFoundBody);
}
