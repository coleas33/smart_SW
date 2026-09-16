using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Where the Model check page's shipped files live, and how a test renders inside one.
///
/// The same convention <see cref="ReviewPageFiles"/> already uses, for the same reason: the
/// files are read from the build output, which is the copy the add-in actually serves, so a
/// page file that never reaches `web/` fails the scan instead of passing it from source. The
/// web folder itself and the contract reader are reused rather than restated - there is one
/// answer to "which folder is the virtual host" in this assembly.
/// </summary>
internal static class ModelCheckPageFiles
{
    /// <summary>The Model check page's folder inside the mapped web folder.</summary>
    public static string Folder =>
        Path.Combine(ReviewPageFiles.WebFolder, "Model", "ModelCheckPage");

    /// <summary>The shared helpers both pages load (T080).</summary>
    public static string SharedFolder => Path.Combine(ReviewPageFiles.WebFolder, "shared");

    /// <summary>The URL the add-in navigates the Model check tab to.</summary>
    public const string PageUrl = "https://swreview.invalid/Model/ModelCheckPage/index.html";

    /// <summary>`index.html` as shipped.</summary>
    public static string IndexHtml() => Read("index.html");

    /// <summary>One page file, by name relative to <see cref="Folder"/>.</summary>
    public static string Read(string name)
    {
        AssertPresent();
        string path = Path.Combine(Folder, name);
        Assert.True(File.Exists(path), $"{name} is missing from {Folder}.");
        return File.ReadAllText(path);
    }

    /// <summary>
    /// Every script the page runs: its own, and the shared helpers it loads from the same
    /// virtual host. `shared/dom.js` is in here because the page's rules are its rules -
    /// it is where this page's text reaches the DOM (T080).
    /// </summary>
    public static IReadOnlyList<KeyValuePair<string, string>> Scripts()
    {
        AssertPresent();

        List<KeyValuePair<string, string>> scripts = new[] { Folder, SharedFolder }
            .Where(Directory.Exists)
            .SelectMany(folder => Directory.GetFiles(folder, "*.js", SearchOption.AllDirectories))
            .Where(path => !path.Split(Path.DirectorySeparatorChar).Contains("vendor"))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => new KeyValuePair<string, string>(
                path.Substring(ReviewPageFiles.WebFolder.Length).TrimStart(Path.DirectorySeparatorChar),
                File.ReadAllText(path)))
            .ToList();

        Assert.True(
            scripts.Count >= 2,
            $"The Model check page ships no script beside {ModelCheckPageFiles.SharedFolder}; "
                + "check the Content items in SwReview.AddIn.csproj.");
        return scripts;
    }

    private static void AssertPresent() =>
        Assert.True(
            Directory.Exists(Folder),
            $"The Model check page was not copied to {Folder}; check the Content items in "
                + "SwReview.AddIn.csproj.");
}

/// <summary>
/// The Model check page, loaded from the add-in's own virtual host in an offscreen WebView2,
/// with a script evaluated inside it.
///
/// The boot is <see cref="OffscreenReviewPage.WithPage(string, Action{Microsoft.Web.WebView2.Core.CoreWebView2}, Func{Microsoft.Web.WebView2.Core.CoreWebView2, System.Threading.Tasks.Task})"/>
/// - the same virtual host mapping, the same real page URL, the same real CSP - because the
/// two pages share an origin and must not be tested under two different approximations of it.
/// Only the prelude differs: this one renders through `window.SwReviewCheck`.
///
/// `window.chrome.webview` exists in this host as it does in the add-in, so the page posts its
/// `ready` normally; nothing answers it, which is exactly the state the page is in before the
/// host replies, and rendering does not depend on it.
/// </summary>
internal static class OffscreenModelCheckPage
{
    /// <summary>
    /// Evaluates a JS function body in the loaded page and parses what it returned. The body
    /// runs with two helpers in scope: `check(result)` hands a `CheckResult` to the page's own
    /// renderer, and `describe(node)` reports what actually landed in the DOM.
    /// </summary>
    public static JsonElement Evaluate(string body)
    {
        string? raw = null;

        OffscreenReviewPage.WithPage(
            ModelCheckPageFiles.PageUrl,
            null,
            async page =>
            {
                // Through the DevTools protocol rather than injected into the document, so the
                // page's own CSP neither blocks it nor is weakened by it.
                raw = await page.ExecuteScriptAsync(Prelude + body + Epilogue);
            });

        Assert.False(
            string.IsNullOrEmpty(raw) || raw == "null",
            "The page script threw before it could report: " + (raw ?? "<nothing>")
                + Environment.NewLine + body);

        string json = JsonDocument.Parse(raw!).RootElement.GetString()
            ?? throw new InvalidOperationException("The page script returned no value: " + raw);
        return JsonDocument.Parse(json).RootElement.Clone();
    }

    private const string Prelude = @"
(function () {
  function check(result) {
    var api = window.SwReviewCheck;
    if (!api || typeof api.renderResult !== 'function') {
      throw new Error('Model/ModelCheckPage/check.js must set window.SwReviewCheck.renderResult ' +
        '(T082): the tests render through the same function the tab renders through.');
    }
    api.renderResult(result);
    return document.body;
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

  function texts(selector) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
    return out;
  }

  function attrs(selector, name) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute(name)); }
    return out;
  }

  try {
";

    private const string Epilogue = @"
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}());
";
}
