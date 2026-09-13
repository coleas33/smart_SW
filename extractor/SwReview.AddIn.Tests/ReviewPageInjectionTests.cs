using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T042a: a finding title, a recommended action and a tool result summary that contain markup
/// reach the screen as characters, not as elements (FR-029, contracts/pane-host-messages.md).
///
/// <b>How this is driven, and why.</b> tasks.md asks for the page's pure rendering functions in
/// a separately loadable script file, evaluated with a minimal JS engine on net48, and allows
/// an offscreen `CoreWebView2` with the vendored files as the fallback. This test takes both
/// halves: the page must ship `render.js` exposing pure rendering functions, and those
/// functions are called <i>inside the real page</i>, loaded from the real virtual host in an
/// offscreen WebView2, with the result read back through `ExecuteScriptAsync`.
///
/// The engine route was rejected on the merits rather than for want of one. The .NET Framework
/// does ship a JavaScript engine (`Microsoft.JScript`), and it is unusable here for two
/// independent reasons. It is an ES3 engine: `Object.create`, `Array.prototype.forEach` and
/// `JSON` - which the page already uses - do not exist in it, so the file under test would have
/// to be written down to the engine rather than the engine chosen to fit the file. And it has
/// no DOM, so the test would have to supply a shim, and a shim cannot answer the only question
/// an injection test asks: would a browser's HTML parser turn this string into an element? A
/// shim can only report which property the code assigned, which is what the static scan below
/// already proves, from the source, for free. The real engine answers the real question:
/// `querySelectorAll('img,script,...')` over the rendered subtree, and the escaped `&lt;img` in
/// its serialized markup.
///
/// <b>What T041 must provide.</b> `Review/ReviewPage/render.js`, loaded by `index.html` before
/// `app.js`, setting `window.SwReviewRender` to an object with two pure functions - pure in the
/// sense that they touch no host bridge, no network and no page state, so they can be called
/// from a test with nothing else set up:
///
/// <code>
///   window.SwReviewRender.findingCard(finding) -> Element   // a Finding, review-session.schema.json
///   window.SwReviewRender.toolCard(tool)       -> Element   // a tool.started body merged with
///                                                           // its tool.finished body
/// </code>
///
/// `app.js` renders its transcript through the same two functions; the static scan is what
/// keeps the rest of the page honest.
/// </summary>
public sealed class ReviewPageInjectionTests
{
    // Each of the three carries both shapes tasks.md asks for: an element that fires on a load
    // failure (no network is needed, so the CSP's `img-src` is not what is being relied on), and
    // a closing script tag, which is what escapes a string that was written into markup.

    /// <summary>A finding title, as a model wrote it.</summary>
    private const string HostileTitle = "<img src=x onerror=\"alert(1)\"></script>";

    /// <summary>A recommended action, which is the field an engineer is most likely to read.</summary>
    private const string HostileAction = "</script><script>alert(2)</script><img src=x onerror=alert(2)>";

    /// <summary>A tool's own words, which come back from the model the same way.</summary>
    private const string HostileSummary = "<img src=x onerror=alert(3)></script><svg/onload=alert(4)>";

    // ---- the rendered DOM -------------------------------------------------------------------

    [Fact]
    public void AFindingTitleAndRecommendedActionRenderAsLiteralText()
    {
        string finding = JsonSerializer.Serialize(HostileFinding());

        JsonElement rendered = OffscreenReviewPage.Evaluate(
            "return JSON.stringify(describe(render('findingCard', " + finding + ")));");

        AssertLiteral(rendered, HostileTitle, HostileAction);
    }

    [Fact]
    public void AToolResultSummaryRendersAsLiteralText()
    {
        string tool = JsonSerializer.Serialize(new
        {
            step_index = 3,
            tool = "check_fastener_grip",
            arguments = new { component_id = "c-17" },
            status = "ok",
            result_summary = HostileSummary,
            elapsed_s = 1.25,
            error = (string?)null,
        });

        JsonElement rendered = OffscreenReviewPage.Evaluate(
            "return JSON.stringify(describe(render('toolCard', " + tool + ")));");

        AssertLiteral(rendered, HostileSummary);
    }

    private static void AssertLiteral(JsonElement rendered, params string[] expected)
    {
        Assert.True(
            rendered.GetProperty("ok").GetBoolean(),
            rendered.TryGetProperty("error", out JsonElement error) ? error.GetString() : "the page did not render");

        string text = rendered.GetProperty("text").GetString()!;
        string html = rendered.GetProperty("html").GetString()!;

        foreach (string value in expected)
        {
            Assert.Contains(value, text);
        }

        Assert.Equal(0, rendered.GetProperty("injected").GetInt32());
        Assert.Equal(0, rendered.GetProperty("handlers").GetInt32());

        // The serialized markup proves the other half: the browser escaped what it was given
        // instead of parsing it, which is what `textContent` does and `innerHTML` does not.
        Assert.Contains("&lt;", html);
        Assert.DoesNotContain("<img", html);
        Assert.DoesNotContain("<script", html);
    }

    /// <summary>
    /// A complete `Finding` (review-session.schema.json), because the card renders more than the
    /// two hostile fields and a half-filled body would exercise a different path.
    /// </summary>
    private static object HostileFinding() => new
    {
        id = "F-001",
        check = "fastener_grip",
        title = HostileTitle,
        status = "suspected",
        severity = "high",
        component_ids = new[] { "c-17", "c-18" },
        drawing_locations = new[] { new { document_id = "d-1", sheet = "Sheet1" } },
        provenance = new[]
        {
            new
            {
                document_id = "d-1",
                vault_path = @"\\vault\bracket.sldasm",
                vault_version = 4,
                revision = "B",
                configuration = "Default",
                local_modified = false,
                export_method = "native",
            },
        },
        configuration = "Default",
        observed = "Grip length 12.0 mm against a 10.0 mm stack.",
        requirement = "Grip length must not exceed the fastened stack.",
        inputs = new[] { "grip=12.0 mm" },
        calculation = (object?)null,
        tool_result_ids = new[] { 7 },
        coverage_limits = new[] { "threads not modelled" },
        recommended_action = HostileAction,
        group = (object?)null,
        capture_ids = Array.Empty<string>(),
        disposition = (object?)null,
        exception_id = (string?)null,
    };

    // ---- the static half: the page's own rules --------------------------------------------

    [Fact]
    public void IndexHtmlCarriesTheContractCspMetaTag()
    {
        string expected = ContractCsp();
        string index = ReviewPageFiles.IndexHtml();

        Match meta = Regex.Match(
            index,
            @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""([^""]*)""\s*/?>",
            RegexOptions.IgnoreCase);

        Assert.True(meta.Success, "index.html carries no Content-Security-Policy meta tag.");
        Assert.Equal(Normalize(expected), Normalize(meta.Groups[1].Value));
    }

    [Fact]
    public void NeitherThePageNorItsScriptsAssignMarkup()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> file in PageFiles())
        {
            foreach (Match match in MarkupSink.Matches(file.Value))
            {
                offences.Add($"{file.Key}: {match.Value.Trim()}");
            }
        }

        Assert.True(
            offences.Count == 0,
            "The page must build every node with textContent/createTextNode; these turn a string "
                + "into markup:" + Environment.NewLine + string.Join(Environment.NewLine, offences));
    }

    [Fact]
    public void IndexHtmlNamesNoInlineHandlerAndNoInnerHtml()
    {
        string index = ReviewPageFiles.IndexHtml();

        List<string> handlers = Regex.Matches(index, @"<[^>!][^>]*?\s(on[a-z]+)\s*=", RegexOptions.IgnoreCase)
            .Cast<Match>()
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        Assert.True(
            handlers.Count == 0,
            "index.html carries inline event handlers (" + string.Join(", ", handlers)
                + "); every handler is attached with addEventListener in app.js.");
        Assert.DoesNotContain("innerHTML", index, StringComparison.Ordinal);
    }

    /// <summary>
    /// The sinks that turn a string into markup. `eval` and `new Function` are here because the
    /// page's CSP (`script-src 'self'`, no `unsafe-eval`) already blocks them at runtime, and a
    /// page that needs them is a page whose CSP is about to be loosened.
    /// </summary>
    private static readonly Regex MarkupSink = new Regex(
        @"\.\s*(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\s*\.\s*write|\bnew\s+Function\s*\(|\beval\s*\(",
        RegexOptions.Compiled);

    private static IEnumerable<KeyValuePair<string, string>> PageFiles() =>
        ReviewPageFiles.Scripts()
            .Concat(new[] { new KeyValuePair<string, string>("index.html", ReviewPageFiles.IndexHtml()) });

    /// <summary>The CSP the contract prints in its fenced `html` block, read as data.</summary>
    private static string ContractCsp()
    {
        string contract = ReviewPageFiles.ReadContract("pane-host-messages.md");
        Match meta = Regex.Match(
            contract,
            @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""([^""]*)""\s*>",
            RegexOptions.IgnoreCase);

        Assert.True(meta.Success, "contracts/pane-host-messages.md no longer prints a CSP meta tag.");
        return meta.Groups[1].Value;
    }

    private static string Normalize(string policy) =>
        string.Join(
            "; ",
            policy.Split(';')
                .Select(directive => Regex.Replace(directive.Trim(), @"\s+", " "))
                .Where(directive => directive.Length > 0));
}

/// <summary>
/// The Review page, loaded from the add-in's own virtual host in an offscreen WebView2, with a
/// script evaluated inside it.
///
/// The page is navigated to `https://swreview.invalid/Review/ReviewPage/index.html` over the
/// same `SetVirtualHostNameToFolderMapping` the add-in uses, so the CSP meta tag, the relative
/// `src` of every script and the page's origin are the real ones rather than a `file://`
/// approximation of them. `window.chrome.webview` exists in this host as it does in the add-in,
/// so `app.js` starts normally; nothing answers its `ready`, which is exactly the state the page
/// is in before the host replies, and the rendering functions do not depend on it.
///
/// The environment gets its own throwaway user data folder per call. The add-in's single
/// process-wide environment (T042b) is a different concern and a different folder; two
/// environments over the same folder with different options is the failure
/// contracts/pane-host-messages.md warns about.
/// </summary>
internal static class OffscreenReviewPage
{
    /// <summary>
    /// Evaluates a JS function body in the loaded page and parses what it returned. The body
    /// runs with two helpers in scope: `render(name, value)` calls one `window.SwReviewRender`
    /// function and appends the element it returns to the document, and `describe(node)`
    /// reports what actually landed in the DOM.
    /// </summary>
    public static JsonElement Evaluate(string body)
    {
        string raw = Run(Prelude + body + Epilogue);
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("The page script returned no value: " + raw);
        return JsonDocument.Parse(json).RootElement.Clone();
    }

    private const string Prelude = @"
(function () {
  function render(name, value) {
    var api = window.SwReviewRender;
    if (!api || typeof api[name] !== 'function') {
      throw new Error('Review/ReviewPage/render.js must set window.SwReviewRender.' + name +
        ' (T041): this test renders through the same functions the transcript renders through.');
    }
    var host = document.createElement('div');
    document.body.appendChild(host);
    host.appendChild(api[name](value));
    return host;
  }

  function describe(node) {
    var handlers = 0;
    var all = node.getElementsByTagName('*');
    for (var i = 0; i < all.length; i++) {
      var attributes = all[i].attributes;
      for (var j = 0; j < attributes.length; j++) {
        if (/^on/i.test(attributes[j].name)) { handlers++; }
      }
    }
    return {
      ok: true,
      text: node.textContent,
      html: node.innerHTML,
      injected: node.querySelectorAll('img,script,iframe,svg,object,embed,link,style').length,
      handlers: handlers
    };
  }

  try {
";

    private const string Epilogue = @"
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}());
";

    /// <summary>
    /// Loads the real page in an offscreen WebView2 and hands the live
    /// <see cref="CoreWebView2"/> to <paramref name="body"/>.
    ///
    /// Shared with the tests that <i>drive</i> the page rather than call one of its rendering
    /// functions (T041's turn state). Those need the host end of the bridge - a
    /// `WebMessageReceived` handler answering `ready` and `review.start` the way the add-in does
    /// - and it has to be subscribed before the page loads, because the page posts `ready` from
    /// `DOMContentLoaded`. Everything above it is the same boot: the virtual host mapping, the
    /// real page URL, the real CSP.
    /// </summary>
    /// <param name="beforeNavigate">Runs on the UI thread with the page not yet navigated;
    /// this is where event handlers are attached. May be null.</param>
    /// <param name="body">Runs once the page has loaded.</param>
    public static void WithPage(Action<CoreWebView2>? beforeNavigate, Func<CoreWebView2, Task> body)
    {
        if (body == null)
        {
            throw new ArgumentNullException(nameof(body));
        }

        string userDataFolder = Path.Combine(
            Path.GetTempPath(), "swreview-page-tests-" + Guid.NewGuid().ToString("N"));

        try
        {
            StaHost.Run(async form =>
            {
                using (var view = new WebView2 { Dock = DockStyle.Fill })
                {
                    form.Controls.Add(view);

                    CoreWebView2Environment environment;
                    try
                    {
                        environment = await CoreWebView2Environment.CreateAsync(null, userDataFolder, null);
                    }
                    catch (WebView2RuntimeNotFoundException error)
                    {
                        throw new InvalidOperationException(
                            "The Evergreen WebView2 runtime is not installed on this machine, so the "
                                + "Review page cannot be rendered and this security test cannot run. "
                                + "The add-in cannot run here either; install the runtime.",
                            error);
                    }

                    await view.EnsureCoreWebView2Async(environment);
                    view.CoreWebView2.SetVirtualHostNameToFolderMapping(
                        "swreview.invalid",
                        ReviewPageFiles.WebFolder,
                        CoreWebView2HostResourceAccessKind.Allow);

                    var loaded = new TaskCompletionSource<CoreWebView2NavigationCompletedEventArgs>();
                    view.CoreWebView2.NavigationCompleted += (sender, args) => loaded.TrySetResult(args);

                    beforeNavigate?.Invoke(view.CoreWebView2);

                    view.CoreWebView2.Navigate(ReviewPageFiles.PageUrl);

                    CoreWebView2NavigationCompletedEventArgs navigation = await loaded.Task;
                    if (!navigation.IsSuccess)
                    {
                        throw new InvalidOperationException(
                            $"{ReviewPageFiles.PageUrl} did not load: {navigation.WebErrorStatus}.");
                    }

                    await body(view.CoreWebView2);
                }
            });
        }
        finally
        {
            TryDelete(userDataFolder);
        }
    }

    /// <summary>
    /// Lets the page's promise chain drain.
    ///
    /// `bridge.postMessage` and the host's reply cross a process boundary and everything the
    /// page does with a reply is a microtask behind it, so "the page has finished reacting" is
    /// a few round trips through the renderer rather than a single one. Each `ExecuteScriptAsync`
    /// is ordered behind everything the previous one queued, which is what makes this bounded
    /// rather than a race.
    /// </summary>
    public static async Task Settled(CoreWebView2 page)
    {
        for (int turn = 0; turn < 12; turn++)
        {
            await page.ExecuteScriptAsync("0");
            await Task.Delay(15);
        }
    }

    private static string Run(string script)
    {
        string? result = null;

        WithPage(
            null,
            async page =>
            {
                // Script evaluated through the DevTools protocol rather than injected into
                // the document, so the page's own CSP neither blocks it nor is weakened by it.
                result = await page.ExecuteScriptAsync(script);
            });

        Assert.False(
            string.IsNullOrEmpty(result) || result == "null",
            "The page script threw before it could report: " + (result ?? "<nothing>")
                + Environment.NewLine + script);

        return result!;
    }

    /// <summary>Best effort: the browser process may still be letting go of the folder.</summary>
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
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
