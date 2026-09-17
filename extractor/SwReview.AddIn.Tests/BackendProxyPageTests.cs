using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The same-origin backend proxy (`docs/pane-backend-proxy.md`), against a real offscreen
/// WebView2: the platform limitation that stopped the first design, and the shipped
/// configuration that routes around it.
///
/// <b>What this file found.</b> The design is: the pages call their own origin under
/// `/__backend`, and `WebResourceRequested` lets the host answer. That cannot work while the
/// pages are served by a folder mapping. <b>WebView2 raises no `WebResourceRequested` at all
/// for a virtual host mapped with `SetVirtualHostNameToFolderMapping`</b>: the mapping resolves
/// the request itself, ahead of the event, so `fetch('/__backend/health')` is answered "no such
/// file" - `Failed to fetch` in the page - and the handler never sees it.
///
/// <b>What shipped.</b> The mapping is gone. Every resource on `https://swreview.invalid` is
/// served by the host through one filter and one handler:
/// <see cref="BackendProxyHandler.TryServe"/> answers `/__backend/*` and
/// <see cref="PageFileServer"/> answers the page's own files. Same origin holds, so the CSP is
/// `connect-src 'self'` and there is no CORS anywhere -
/// <see cref="TheShippedPaneServesItsOwnPagesAndItsBackendCallsThroughOneHandler"/> is that
/// configuration, end to end, in the real <see cref="TaskPaneControl"/>.
///
/// <b>Why the limitation proof stays.</b> Three tests, because a negative result on its own is
/// not evidence. The first two are the limitation, split so neither can be explained by the
/// other: a folder-mapped page's own files raise nothing, and a `fetch` raises nothing <i>with
/// a CSP that permits the call</i>. That second half matters - a page whose CSP forbids the
/// call is refused inside the renderer before any request exists, which produces the same
/// `TypeError: Failed to fetch` and the same zero events whatever the mapping does, so it would
/// prove the policy rather than the platform. The third is the positive control: identical
/// wiring against a host that is <i>not</i> folder-mapped is raised and served from C#, so what
/// fails above is the mapping and not this harness. Together they are why
/// `SetVirtualHostNameToFolderMapping` must not come back, and they fail the day a WebView2
/// update starts raising the event - at which point the mapping becomes a choice again rather
/// than a trap.
/// </summary>
public sealed class BackendProxyPageTests
{
    private static readonly BackendEndpoint Endpoint = new BackendEndpoint(51234, "0FAKEtoken");

    /// <summary>A host name that is deliberately never given a folder mapping.</summary>
    private const string UnmappedHost = "https://backend.swreview.invalid";

    // ---- the limitation, in two halves that cannot explain each other ------------------------

    /// <summary>
    /// Half one, and the half no CSP can account for: a page that really did load its
    /// `index.html`, `app.js`, `render.js` and a stylesheet from the folder-mapped host raises
    /// <b>zero</b> `WebResourceRequested`, with a `*` filter, every resource context and every
    /// request source kind, registered before the mapping and before the navigation.
    ///
    /// Those four files were fetched - the page runs - so this says the event is not raised,
    /// rather than that nothing was requested.
    /// </summary>
    [Fact]
    public void TheFolderMappedVirtualHostRaisesNoWebResourceRequestedForThePagesOwnFiles()
    {
        var seen = new List<string>();
        bool scriptsRan = false;

        WithRawWebView(seen, async (core, environment) =>
        {
            MapTheVirtualHost(core, ReviewPageFiles.WebFolder);
            await Navigate(core, ReviewPageFiles.PageUrl);

            string raw = await core.ExecuteScriptAsync(
                "typeof window.SwReviewRender === 'object' "
                    + "&& document.getElementById('start-review') !== null");
            scriptsRan = JsonDocument.Parse(raw).RootElement.GetBoolean();
        });

        Assert.True(scriptsRan, "the Review page did not actually load, so zero events proves nothing.");
        AssertNoEventsWereRaised(seen);
    }

    /// <summary>
    /// Half two, with the confound removed: the page is served from the folder-mapped host as
    /// before, but its CSP is the one brief Part A item 3 would ship - `connect-src 'self'` -
    /// so a same-origin `fetch` under `/__backend` is permitted by the renderer and really is
    /// issued.
    ///
    /// It still raises nothing, and still reaches the page as `Failed to fetch`. That is the
    /// result that makes "the mapping resolves the request ahead of the event" the explanation
    /// rather than the page's own policy, and it is why items 2 and 3 of the brief cannot be
    /// landed on top of this wiring.
    /// </summary>
    [Fact]
    public void TheFolderMappedVirtualHostRaisesNoWebResourceRequestedForAFetchTheCspAllows()
    {
        var seen = new List<string>();
        string answer = string.Empty;
        string folder = WriteScratchPage("connect-src 'self'");

        try
        {
            WithRawWebView(seen, async (core, environment) =>
            {
                ServeTheBackendPrefixFromCSharp(core, environment);
                MapTheVirtualHost(core, folder);
                await Navigate(core, TaskPaneControl.PageOrigin + "/index.html");

                answer = (await Fetch(core, BackendProxy.PathPrefix + "/health")).ToString();
            });
        }
        finally
        {
            TryDelete(folder);
        }

        Assert.Contains("Failed to fetch", answer, StringComparison.Ordinal);
        AssertNoEventsWereRaised(seen);
    }

    // ---- the positive controls: the same wiring, off the mapping -----------------------------

    /// <summary>
    /// The control the limitation needs, and the one `docs/pane-backend-proxy.md` asserted
    /// without a test: identical filter, identical handler, identical harness - only the host is
    /// not folder-mapped - and the request <b>is</b> raised and <b>is</b> served from C#. So
    /// `seen.Count == 0` above says the mapping swallows the event, not that the wiring in this
    /// harness never fires.
    ///
    /// It also prices the first way out. A second virtual host is cross-origin, so the browser
    /// sends a CORS preflight first: this test has to answer `OPTIONS` with
    /// `Access-Control-Allow-*` before the `GET` happens at all, which is new code in a class
    /// that today strips every `Access-Control-` header on purpose.
    /// </summary>
    [Fact]
    public void TheSameWiringIsRaisedForAHostThatIsNotFolderMapped()
    {
        var seen = new List<string>();
        string answer = string.Empty;
        string folder = WriteScratchPage("connect-src 'self' " + UnmappedHost);

        try
        {
            WithRawWebView(seen, async (core, environment) =>
            {
                core.WebResourceRequested += (sender, args) =>
                {
                    if (args.Request.Method == "OPTIONS")
                    {
                        args.Response = environment.CreateWebResourceResponse(
                            new MemoryStream(new byte[0]),
                            204,
                            "No Content",
                            "Access-Control-Allow-Origin: " + TaskPaneControl.PageOrigin + "\r\n"
                                + "Access-Control-Allow-Headers: authorization,accept\r\n"
                                + "Access-Control-Allow-Methods: GET,POST,OPTIONS");
                    }
                    else if (args.Request.Uri.StartsWith(UnmappedHost, StringComparison.Ordinal))
                    {
                        args.Response = ServedFromCSharp(
                            environment,
                            "Content-Type: application/json\r\nAccess-Control-Allow-Origin: "
                                + TaskPaneControl.PageOrigin);
                    }
                };

                MapTheVirtualHost(core, folder);
                await Navigate(core, TaskPaneControl.PageOrigin + "/index.html");

                answer = (await Fetch(core, UnmappedHost + "/health")).ToString();
            });
        }
        finally
        {
            TryDelete(folder);
        }

        Assert.Contains("served-from-csharp", answer, StringComparison.Ordinal);
        Assert.Contains(seen, entry => entry == "OPTIONS " + UnmappedHost + "/health");
        Assert.Contains(seen, entry => entry == "GET " + UnmappedHost + "/health");
    }

    // ---- the shipped configuration -----------------------------------------------------------

    /// <summary>
    /// The whole of option B, in the real <see cref="TaskPaneControl"/>, on a real WebView2.
    ///
    /// One filter over `https://swreview.invalid/*` and one `WebResourceRequested` handler
    /// serve both halves of the origin, and this asserts both halves really are served that way:
    /// <list type="number">
    /// <item><b>The page and everything it loads.</b> `render.js` and `app.js` ran and
    /// `app.css` applied, with no folder mapping anywhere - so `index.html`, both scripts and
    /// the stylesheet were each answered by <see cref="PageFileServer"/>. A page that came back
    /// styled but scriptless, or scripted but unstyled, would pass a weaker assertion.</item>
    /// <item><b>Nothing of the page's own reached the backend.</b> The transport has recorded
    /// nothing at the point the page has finished loading, which is what `TryServe` returning
    /// null outside the prefix buys and what would catch a proxy that swallowed `app.js`.</item>
    /// <item><b>A same-origin `fetch` under `/__backend` reaches the host's transport</b>,
    /// carrying `Authorization` - the header the backend refuses without, and the entire point
    /// of proxying rather than redirecting.</item>
    /// <item><b>`Origin` does not reach the backend.</b> The second call is a `POST`, because a
    /// same-origin `GET` carries no `Origin` at all and asserting its absence would be vacuous:
    /// WebView2 really does send `Origin: https://swreview.invalid` on the `POST`, and the
    /// backend's own origin guard would refuse a call bearing it, so the strip is load-bearing
    /// rather than tidy.</item>
    /// </list>
    /// </summary>
    [Fact]
    public void TheShippedPaneServesItsOwnPagesAndItsBackendCallsThroughOneHandler()
    {
        var fake = new FakeTransport(200, "OK", "{\"served\":\"served-from-csharp\"}");
        bool pageIsWhole = false;
        int requestsBeforeTheFetch = -1;
        string health = string.Empty;
        string posted = string.Empty;

        WithPane(fake, async page =>
        {
            string raw = await page.ExecuteScriptAsync(
                "typeof window.SwReviewRender === 'object' "
                    + "&& typeof window.SwReviewRender.toolCard === 'function' "
                    + "&& document.getElementById('start-review') !== null "
                    + "&& getComputedStyle(document.body).fontSize === '13px'");
            pageIsWhole = JsonDocument.Parse(raw).RootElement.GetBoolean();
            requestsBeforeTheFetch = fake.Requests.Count;

            health = (await Fetch(page, BackendProxy.PathPrefix + "/health")).ToString();
            posted = (await Fetch(
                page, BackendProxy.PathPrefix + "/sessions", "POST", "{\"run_dir\":\"x\"}"))
                .ToString();
        });

        Assert.True(
            pageIsWhole,
            "The Review page did not load whole from the page file server: its scripts, its "
                + "stylesheet, or index.html itself was not served. There is no folder mapping "
                + "any more, so every one of those files comes through the handler.");
        Assert.Equal(0, requestsBeforeTheFetch);

        Assert.Contains("served-from-csharp", health, StringComparison.Ordinal);
        Assert.Contains("served-from-csharp", posted, StringComparison.Ordinal);

        Assert.Equal(2, fake.Requests.Count);
        ProxiedRequest asked = fake.Requests[0];
        Assert.Equal("GET", asked.Method);
        Assert.Equal("/health", asked.Url.AbsolutePath);
        Assert.Equal("127.0.0.1", asked.Url.Host);
        Assert.Equal(Endpoint.Port, asked.Url.Port);
        Assert.Contains(
            asked.Headers,
            header => header.Key.Equals("Authorization", StringComparison.OrdinalIgnoreCase)
                && header.Value == "Bearer 0FAKEtoken");

        ProxiedRequest sent = fake.Requests[1];
        Assert.Equal("POST", sent.Method);
        Assert.Equal("/sessions", sent.Url.AbsolutePath);
        Assert.Equal("{\"run_dir\":\"x\"}", Encoding.UTF8.GetString(sent.Body!));
        Assert.DoesNotContain(
            sent.Headers,
            header => header.Key.Equals("Origin", StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>
    /// The other half of the same-origin decision: with `connect-src 'self'`, the loopback the
    /// pages used to call is now <b>refused by the renderer</b>, before a socket is opened and
    /// so before any web filter can answer it with an interstitial.
    ///
    /// Asserted on the `securitypolicyviolation` event rather than on the `fetch` rejection,
    /// because a call to a port nothing listens on fails either way and only the violation
    /// event says which of the two happened. `127.0.0.1:1` is the address: nothing can be
    /// listening there, so a test that somehow got past the CSP would still fail rather than
    /// hang.
    /// </summary>
    [Fact]
    public void ThePagesCspRefusesLoopbackBeforeAnyNetworkCallIsMade()
    {
        var fake = new FakeTransport(200, "OK", "{}");
        string violation = string.Empty;
        string answer = string.Empty;

        WithPane(fake, async page =>
        {
            await page.ExecuteScriptAsync(@"
(function () {
  window.__violation = null;
  document.addEventListener('securitypolicyviolation', function (event) {
    window.__violation = JSON.stringify({
      blocked: event.blockedURI,
      directive: event.violatedDirective
    });
  });
}());
");

            answer = (await Fetch(page, "http://127.0.0.1:1/health")).ToString();
            violation = JsonDocument
                .Parse(await page.ExecuteScriptAsync("window.__violation")).RootElement
                .ToString();
        });

        Assert.Contains("Failed to fetch", answer, StringComparison.Ordinal);
        Assert.Contains("connect-src", violation, StringComparison.Ordinal);
        Assert.Contains("127.0.0.1", violation, StringComparison.Ordinal);
        Assert.Empty(fake.Requests);
    }

    // ---- the harness the four raw-WebView2 tests share ---------------------------------------

    /// <summary>
    /// A real offscreen WebView2 with the widest filter the API can express and a recorder on
    /// `WebResourceRequested`, both registered before anything else the body does - so neither
    /// registration order nor a narrow filter can be the explanation for what is or is not seen.
    ///
    /// The body gets the `CoreWebView2` and its environment and decides the rest: whether to map
    /// a folder, and what (if anything) to serve.
    /// </summary>
    private static void WithRawWebView(
        List<string> seen, Func<CoreWebView2, CoreWebView2Environment, Task> body)
    {
        string userDataFolder = NewUserDataFolder();

        try
        {
            StaHost.Run(async form =>
            {
                using (var view = new WebView2 { Dock = DockStyle.Fill })
                {
                    form.Controls.Add(view);
                    CoreWebView2Environment environment =
                        await CoreWebView2Environment.CreateAsync(null, userDataFolder, null);
                    await view.EnsureCoreWebView2Async(environment);
                    CoreWebView2 core = view.CoreWebView2;

                    core.AddWebResourceRequestedFilter(
                        "*",
                        CoreWebView2WebResourceContext.All,
                        CoreWebView2WebResourceRequestSourceKinds.All);
                    core.WebResourceRequested += (sender, args) =>
                    {
                        lock (seen)
                        {
                            seen.Add(args.Request.Method + " " + args.Request.Uri);
                        }
                    };

                    await body(core, environment);
                }
            });
        }
        finally
        {
            TryDelete(userDataFolder);
        }
    }

    /// <summary>The mapping the pane uses, and the thing under suspicion.</summary>
    private static void MapTheVirtualHost(CoreWebView2 core, string folder) =>
        core.SetVirtualHostNameToFolderMapping(
            TaskPaneControl.VirtualHostName, folder, CoreWebView2HostResourceAccessKind.Allow);

    /// <summary>
    /// A handler that would answer the backend prefix, so that "nothing was served" cannot be
    /// confused with "nothing was asked".
    /// </summary>
    private static void ServeTheBackendPrefixFromCSharp(
        CoreWebView2 core, CoreWebView2Environment environment)
    {
        core.WebResourceRequested += (sender, args) =>
        {
            if (args.Request.Uri.StartsWith(BackendProxy.PageOrigin + "/", StringComparison.Ordinal))
            {
                args.Response = ServedFromCSharp(environment, "Content-Type: application/json");
            }
        };
    }

    private static CoreWebView2WebResourceResponse ServedFromCSharp(
        CoreWebView2Environment environment, string headers) =>
        environment.CreateWebResourceResponse(
            new MemoryStream(Encoding.UTF8.GetBytes("{\"served\":\"served-from-csharp\"}")),
            200,
            "OK",
            headers);

    private static void AssertNoEventsWereRaised(List<string> seen) =>
        Assert.True(
            seen.Count == 0,
            "WebView2 now raises WebResourceRequested for the folder-mapped virtual host: "
                + string.Join(", ", seen.ToArray())
                + ". That limitation is what stopped docs/pane-backend-proxy.md's `/__backend` "
                + "prefix from being served on the page's own origin; with it gone, finish the "
                + "proxy as that document's section 2 describes and delete these two tests.");

    /// <summary>
    /// A one-file page whose only interesting property is its CSP, so that a test can put the
    /// policy it wants in front of the runtime instead of inheriting a shipped page's.
    /// </summary>
    private static string ScratchPageHtml(string connectSrc) =>
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        + "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        + "script-src 'self'; style-src 'self'; " + connectSrc + "; "
        + "base-uri 'none'; form-action 'none'\">\n<title>proxy probe</title>\n"
        + "</head>\n<body>proxy probe</body>\n</html>\n";

    private static string WriteScratchPage(string connectSrc)
    {
        string folder = Path.Combine(
            Path.GetTempPath(), "swreview-proxy-page-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        File.WriteAllText(Path.Combine(folder, "index.html"), ScratchPageHtml(connectSrc));
        return folder;
    }

    private static async Task<bool> Navigate(CoreWebView2 core, string url, bool mustSucceed = true)
    {
        var loaded = new TaskCompletionSource<bool>();
        core.NavigationCompleted += (sender, args) => loaded.TrySetResult(args.IsSuccess);
        core.Navigate(url);
        bool ok = await loaded.Task;

        if (mustSucceed)
        {
            Assert.True(ok, "the page did not load: " + url);
        }

        return ok;
    }

    // ---- driving the page ----------------------------------------------------------------------

    /// <summary>
    /// One `fetch` from inside the page, with the reply read back.
    ///
    /// Two turns rather than one because `ExecuteScriptAsync` does not await a promise: the
    /// script starts the call and parks the answer on `window`, and the poll reads it once it
    /// lands. `{status, body}` on success, `{error}` on a refusal.
    ///
    /// The method and body are parameters because a same-origin `GET` carries no `Origin`
    /// header at all: the test that the proxy strips `Origin` needs a request that really has
    /// one, and `POST` is what the pages send.
    /// </summary>
    private static async Task<JsonElement> Fetch(
        CoreWebView2 page, string url, string method = "GET", string? body = null)
    {
        await page.ExecuteScriptAsync(@"
(function () {
  window.__proxyAnswer = null;
  fetch(" + JsonSerializer.Serialize(url) + @", {
    method: " + JsonSerializer.Serialize(method) + @",
    body: " + (body == null ? "null" : JsonSerializer.Serialize(body)) + @",
    headers: " + (body == null
        ? "{ Authorization: 'Bearer 0FAKEtoken', Accept: 'application/json' }"
        : "{ Authorization: 'Bearer 0FAKEtoken', Accept: 'application/json', "
            + "'Content-Type': 'application/json' }") + @",
    cache: 'no-store'
  }).then(function (response) {
    return response.text().then(function (text) {
      window.__proxyAnswer = JSON.stringify({ status: response.status, body: text });
    });
  }).catch(function (error) {
    window.__proxyAnswer = JSON.stringify({ error: '' + error });
  });
}());
");

        for (int turn = 0; turn < 200; turn++)
        {
            JsonElement parked = JsonDocument
                .Parse(await page.ExecuteScriptAsync("window.__proxyAnswer")).RootElement;
            if (parked.ValueKind == JsonValueKind.String)
            {
                return JsonDocument.Parse(parked.GetString()!).RootElement.Clone();
            }

            await Task.Delay(25);
        }

        throw new InvalidOperationException("the page's fetch never settled: " + url);
    }

    /// <summary>
    /// The real pane, on the kind of thread SOLIDWORKS gives it, with the Review page loaded and
    /// the proxy wired the way the add-in wires it.
    ///
    /// A throwaway user data folder rather than the add-in's own: the pane's rule is one
    /// environment per process, and a test that opened the add-in's folder would be a second
    /// instance over a folder a running SOLIDWORKS may hold.
    /// </summary>
    private static void WithPane(FakeTransport transport, Func<CoreWebView2, Task> body)
    {
        string userDataFolder = NewUserDataFolder();

        try
        {
            StaHost.Run(async form =>
            {
                var options = new TaskPaneOptions(
                    new TempFolderEnvironmentFactory(userDataFolder),
                    Path.Combine(userDataFolder, "runs"))
                {
                    WebFolder = ReviewPageFiles.WebFolder,
                    Backend = () => Endpoint,
                    ProxySend = transport.Send,
                };

                using (var control = new TaskPaneControl(options) { Dock = DockStyle.Fill })
                {
                    form.Controls.Add(control);
                    await control.InitializeAsync();

                    Assert.True(
                        control.ReviewPageReady,
                        "The Review page did not load in the pane; the WebView2 runtime has to be "
                            + "installed for this test, as it does for the add-in itself.");

                    CoreWebView2 page = control.ReviewPage!;
                    await Loaded(page);
                    await body(page);
                }
            });
        }
        finally
        {
            TryDelete(userDataFolder);
        }
    }

    /// <summary>
    /// `InitializeAsync` navigates and returns; the page is loaded a few message-loop turns
    /// later. Polled rather than raced on `NavigationCompleted`, because the pane owns that
    /// handler and this test is a bystander to it.
    /// </summary>
    private static async Task Loaded(CoreWebView2 page)
    {
        for (int turn = 0; turn < 400; turn++)
        {
            string raw = await page.ExecuteScriptAsync("document.readyState");
            if (JsonDocument.Parse(raw).RootElement.GetString() == "complete")
            {
                return;
            }

            await Task.Delay(25);
        }

        throw new InvalidOperationException("the Review page never finished loading in the pane.");
    }

    private static string NewUserDataFolder() => Path.Combine(
        Path.GetTempPath(), "swreview-proxy-tests-" + Guid.NewGuid().ToString("N"));

    private static void TryDelete(string folder)
    {
        try
        {
            if (Directory.Exists(folder))
            {
                Directory.Delete(folder, recursive: true);
            }
        }
        catch (IOException)
        {
            // The browser process may still be letting go of it; it is under TEMP either way.
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    /// <summary>A real WebView2 environment over a folder this test owns and deletes.</summary>
    private sealed class TempFolderEnvironmentFactory : IWebViewEnvironmentFactory
    {
        private readonly string _folder;

        public TempFolderEnvironmentFactory(string folder) => _folder = folder;

        public Task<CoreWebView2Environment> CreateAsync()
        {
            Directory.CreateDirectory(_folder);
            return CoreWebView2Environment.CreateAsync(null, _folder, null);
        }
    }

    /// <summary>
    /// The host's transport, faked: it records the call the host would have made to loopback and
    /// answers with a fixed reply. Called off the UI thread by the proxy handler, so the list is
    /// guarded.
    /// </summary>
    private sealed class FakeTransport
    {
        private readonly object _gate = new object();
        private readonly List<ProxiedRequest> _requests = new List<ProxiedRequest>();
        private readonly int _status;
        private readonly string _reason;
        private readonly string _body;

        public FakeTransport(int status, string reason, string body)
        {
            _status = status;
            _reason = reason;
            _body = body;
        }

        public IReadOnlyList<ProxiedRequest> Requests
        {
            get
            {
                lock (_gate)
                {
                    return new List<ProxiedRequest>(_requests);
                }
            }
        }

        public ProxiedResponse Send(ProxiedRequest request)
        {
            lock (_gate)
            {
                _requests.Add(request);
            }

            return new ProxiedResponse(
                _status, _reason, "Content-Type: application/json", Encoding.UTF8.GetBytes(_body));
        }
    }
}
