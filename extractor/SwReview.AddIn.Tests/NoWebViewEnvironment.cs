using System;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;

namespace SwReview.AddIn.Tests;

/// <summary>
/// A WebView2 environment factory for a pane whose test never shows a page: the pane is built, and its own thread used,
/// but no WebView2 runtime is ever asked for.
/// </summary>
internal sealed class NoWebViewEnvironment : IWebViewEnvironmentFactory
{
    public Task<CoreWebView2Environment> CreateAsync() =>
        throw new InvalidOperationException("This test never initializes WebView2.");
}
