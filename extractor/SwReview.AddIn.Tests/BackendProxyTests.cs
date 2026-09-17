using System;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The map from a same-origin page URL to the loopback backend.
///
/// <b>Why this exists.</b> Endpoint security products (Sophos Web Protection on the pilot
/// workstation) intercept HTTP from <i>browser</i> processes and answer
/// <c>http://127.0.0.1:&lt;port&gt;</c> with a block or warn interstitial. The Task Pane's
/// WebView2 is a browser process, so every page <c>fetch</c> to the backend received that
/// page - a 403 carrying no CORS headers - while the backend itself logged 204. Requests
/// made by the add-in's own C# code are not intercepted, which is why a review ran to
/// completion while the pane showed nothing.
///
/// So the page stops crossing the network boundary: it calls its <b>own origin</b> under
/// <see cref="BackendProxy.PathPrefix"/>, the host intercepts that with
/// <c>WebResourceRequested</c> and forwards it from C#. Same-origin means no CORS, no
/// preflight, and nothing for a web filter to classify.
///
/// The mapping is a pure function so it can be pinned without WebView2, a backend, or a
/// network - and because it is the one place a path could escape to somewhere that is not
/// the backend.
/// </summary>
public sealed class BackendProxyTests
{
    private static readonly BackendEndpoint Endpoint = new BackendEndpoint(51234, "0FAKEtoken");

    [Fact]
    public void APageUrlUnderThePrefixMapsToTheBackend()
    {
        Assert.True(BackendProxy.TryMapToBackend(
            "https://swreview.invalid/__backend/sessions/abc/events", Endpoint, out Uri? target));

        Assert.Equal("http://127.0.0.1:51234/sessions/abc/events", target!.ToString());
    }

    /// <summary>The query string is part of the request: `?after=N` drives the remodel poll.</summary>
    [Fact]
    public void TheQueryStringIsCarriedThrough()
    {
        Assert.True(BackendProxy.TryMapToBackend(
            "https://swreview.invalid/__backend/models?provider=openai", Endpoint, out Uri? target));

        Assert.Equal("http://127.0.0.1:51234/models?provider=openai", target!.ToString());
    }

    /// <summary>The prefix itself is the root of the backend, not a path under it.</summary>
    [Fact]
    public void ThePrefixAloneMapsToTheBackendRoot()
    {
        Assert.True(BackendProxy.TryMapToBackend(
            "https://swreview.invalid/__backend/", Endpoint, out Uri? target));

        Assert.Equal("http://127.0.0.1:51234/", target!.ToString());
    }

    /// <summary>
    /// Anything outside the prefix is not ours. The page's own HTML, CSS and vendored
    /// scripts share this origin - the host serves those too, from the web folder - and
    /// answering them here would send the page's scripts to the backend rather than proxy a
    /// call.
    /// </summary>
    [Theory]
    [InlineData("https://swreview.invalid/Review/ReviewPage/index.html")]
    [InlineData("https://swreview.invalid/")]
    [InlineData("https://swreview.invalid/__backendish/sessions")]
    [InlineData("https://example.invalid/__backend/sessions")]
    [InlineData("http://127.0.0.1:51234/sessions")]
    public void AUrlOutsideThePrefixIsNotProxied(string url)
    {
        Assert.False(BackendProxy.TryMapToBackend(url, Endpoint, out Uri? target));
        Assert.Null(target);
    }

    /// <summary>
    /// A traversal that climbs out of the prefix is simply not ours. `..` segments are
    /// resolved before the prefix is tested - `/__backend/../../etc/passwd` is
    /// `/etc/passwd` by then - so the URL fails the prefix check and WebView2 serves it as
    /// it would any other page URL.
    ///
    /// Stated per row rather than branched on: the previous shape of this test put its
    /// assertions inside `if (TryMapToBackend(...))`, so both rows took the false branch and
    /// it passed having asserted nothing at all.
    /// </summary>
    [Theory]
    [InlineData("https://swreview.invalid/__backend/../../etc/passwd")]
    [InlineData("https://swreview.invalid/__backend/sessions/../../..")]
    [InlineData("https://swreview.invalid/__backend/%2e%2e/etc")]
    public void ATraversalOutOfThePrefixIsNotOurs(string url)
    {
        Assert.False(BackendProxy.TryMapToBackend(url, Endpoint, out Uri? target));
        Assert.Null(target);
    }

    /// <summary>
    /// A traversal that stays under the prefix still lands on the backend and nowhere else.
    ///
    /// This is the half that has to be asserted unconditionally, because it is the half that
    /// could go wrong: the mapped URL is rebuilt from the already-normalized path with an
    /// explicit scheme, host and port, so neither an encoded `..` nor a protocol-relative
    /// `//evil.invalid/x` can move the request off 127.0.0.1. What the backend then does with
    /// a path it does not route is the backend's business.
    /// </summary>
    [Theory]
    [InlineData("https://swreview.invalid/__backend/sessions/../models", "http://127.0.0.1:51234/models")]
    [InlineData("https://swreview.invalid/__backend/a/./b", "http://127.0.0.1:51234/a/b")]
    [InlineData(
        "https://swreview.invalid/__backend/..%2f..%2fetc", "http://127.0.0.1:51234/..%2f..%2fetc")]
    [InlineData(
        "https://swreview.invalid/__backend//evil.invalid/x",
        "http://127.0.0.1:51234//evil.invalid/x")]
    public void ATraversalUnderThePrefixNeverLeavesTheBackend(string url, string expected)
    {
        Assert.True(BackendProxy.TryMapToBackend(url, Endpoint, out Uri? target));

        Assert.Equal(expected, target!.ToString());
        Assert.Equal("127.0.0.1", target.Host);
        Assert.Equal(51234, target.Port);
        Assert.Equal(Uri.UriSchemeHttp, target.Scheme);
    }

    [Fact]
    public void AMalformedUrlIsNotProxied()
    {
        Assert.False(BackendProxy.TryMapToBackend("not a url", Endpoint, out Uri? target));
        Assert.Null(target);
    }

    /// <summary>
    /// What the hosts put in `init.backend.origin`. The page concatenates it with the path
    /// it wants, so it must carry the prefix and no trailing slash.
    /// </summary>
    [Fact]
    public void ThePageOriginIsThePaneOriginPlusThePrefix()
    {
        Assert.Equal("https://swreview.invalid/__backend", BackendProxy.PageOrigin);
        Assert.DoesNotContain("127.0.0.1", BackendProxy.PageOrigin);
        Assert.EndsWith(BackendProxy.PathPrefix, BackendProxy.PageOrigin, StringComparison.Ordinal);
    }

    /// <summary>
    /// The one filter WebView2 is given covers the whole origin, not just the prefix: the host
    /// serves the page files through the same handler now, so a filter narrowed to
    /// `/__backend/*` would leave every page unserved (docs/pane-backend-proxy.md section 4).
    /// </summary>
    [Fact]
    public void TheOneResourceFilterCoversThePrefixAndThePagesThemselves()
    {
        Assert.Equal("https://swreview.invalid/*", TaskPaneControl.PageResourceFilter);
        Assert.StartsWith(
            TaskPaneControl.PageOrigin + "/",
            BackendProxy.PageOrigin + "/",
            StringComparison.Ordinal);
    }
}
