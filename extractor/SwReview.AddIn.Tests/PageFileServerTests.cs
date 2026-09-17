using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using SwReview.AddIn;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The page file server (`docs/pane-backend-proxy.md` section 4, option B).
///
/// <b>Why this class exists.</b> WebView2 raises no `WebResourceRequested` for a virtual host
/// mapped with `SetVirtualHostNameToFolderMapping`, so a page served that way cannot call its
/// own origin under `/__backend` - which is the whole of the same-origin proxy. Dropping the
/// mapping means the host has to serve the pages itself, through the same handler that serves
/// the backend prefix: `BackendProxyHandler.TryServe` answers `/__backend/*`, and this answers
/// everything else on the origin.
///
/// <b>What it is allowed to do is the point.</b> The mapping was a sandbox - one folder, no
/// traversal out of it - and replacing it with `File.ReadAllBytes` re-opens every question the
/// mapping had already answered. So the rule is stated here rather than inferred: the canonical
/// path must stay under the web folder, the extension must be one the pages actually ship, the
/// query string never picks the file, and there is no directory listing. Anything else is a
/// 404, not an exception and not a guess.
/// </summary>
public sealed class PageFileServerTests : IDisposable
{
    private const string Origin = "https://swreview.invalid";

    private readonly string _root;
    private readonly string _web;

    public PageFileServerTests()
    {
        _root = Path.Combine(
            Path.GetTempPath(), "swreview-file-server-" + Guid.NewGuid().ToString("N"));
        _web = Path.Combine(_root, "web");
        Directory.CreateDirectory(Path.Combine(_web, "Review", "ReviewPage"));

        // The file the pages are meant to be able to reach...
        File.WriteAllText(Path.Combine(_web, "Review", "ReviewPage", "index.html"), "<p>page</p>");
        File.WriteAllText(Path.Combine(_web, "Review", "ReviewPage", "app.js"), "// script");

        // ...and one, one level up, that they are not. It is a real file with a served
        // extension, so a traversal that got out of the folder would succeed rather than 404
        // for the uninteresting reason that there was nothing there.
        File.WriteAllText(Path.Combine(_root, "secret.html"), "<p>outside</p>");
    }

    private PageFileServer Server() => new PageFileServer(_web);

    // ---- what it serves ----------------------------------------------------------------------

    [Fact]
    public void APageFileIsServedWithItsContentTypeAndNoStore()
    {
        ProxiedResponse answer = Server().Serve(Origin + "/Review/ReviewPage/index.html");

        Assert.Equal(200, answer.Status);
        Assert.Equal("OK", answer.Reason);
        Assert.Equal("<p>page</p>", Encoding.UTF8.GetString(answer.Content));
        Assert.Contains("Content-Type: text/html; charset=utf-8", answer.Headers, StringComparison.Ordinal);

        // No-store because the pane reloads a page whenever its tab is rebuilt and an engineer
        // who has just been given a new build must not be shown the previous one's script.
        Assert.Contains("Cache-Control: no-store", answer.Headers, StringComparison.Ordinal);
    }

    /// <summary>
    /// The extensions the four pages actually ship, plus the ones an icon or a font would
    /// arrive as. The list is closed on purpose: an extension that is not here is a 404, so a
    /// file that finds its way into `web/` is not served merely because it is there.
    /// </summary>
    [Theory]
    [InlineData("page.html", "text/html; charset=utf-8")]
    [InlineData("page.js", "text/javascript; charset=utf-8")]
    [InlineData("page.css", "text/css; charset=utf-8")]
    [InlineData("page.json", "application/json; charset=utf-8")]
    [InlineData("page.svg", "image/svg+xml")]
    [InlineData("page.png", "image/png")]
    [InlineData("page.ico", "image/x-icon")]
    [InlineData("page.woff2", "font/woff2")]
    public void EachServedExtensionGetsItsContentType(string name, string expected)
    {
        File.WriteAllText(Path.Combine(_web, name), "x");

        ProxiedResponse answer = Server().Serve(Origin + "/" + name);

        Assert.Equal(200, answer.Status);
        Assert.Contains("Content-Type: " + expected, answer.Headers, StringComparison.Ordinal);
    }

    /// <summary>
    /// The extension is matched without regard to case, because the request carries whatever
    /// the page's `href` spelled and a `.CSS` that 404s would be a mystery on a file system
    /// that found the file perfectly well.
    /// </summary>
    [Fact]
    public void TheExtensionIsMatchedWithoutRegardToCase()
    {
        File.WriteAllText(Path.Combine(_web, "LOUD.CSS"), "body{}");

        ProxiedResponse answer = Server().Serve(Origin + "/LOUD.CSS");

        Assert.Equal(200, answer.Status);
        Assert.Contains("Content-Type: text/css; charset=utf-8", answer.Headers, StringComparison.Ordinal);
    }

    /// <summary>
    /// A served file is returned byte for byte. `vendor/xterm.js` is 300 KB of third-party
    /// script whose bytes are not ours to reinterpret, so nothing here decodes or re-encodes.
    /// </summary>
    [Fact]
    public void TheFileIsServedByteForByte()
    {
        var bytes = new byte[] { 0x00, 0xC3, 0xA9, 0x0D, 0x0A, 0xFF };
        File.WriteAllBytes(Path.Combine(_web, "raw.png"), bytes);

        ProxiedResponse answer = Server().Serve(Origin + "/raw.png");

        Assert.Equal(bytes, answer.Content);
    }

    /// <summary>
    /// The query string never picks the file. A page that cache-busts with `?v=2` must get the
    /// same file, and `?x=../../secret.html` must not get a different one.
    /// </summary>
    [Theory]
    [InlineData("?v=2")]
    [InlineData("?x=../../secret.html")]
    [InlineData("?")]
    public void TheQueryStringDoesNotChooseTheFile(string query)
    {
        ProxiedResponse answer = Server().Serve(Origin + "/Review/ReviewPage/app.js" + query);

        Assert.Equal(200, answer.Status);
        Assert.Equal("// script", Encoding.UTF8.GetString(answer.Content));
    }

    /// <summary>A fragment is the renderer's business and never reaches the file system.</summary>
    [Fact]
    public void AFragmentDoesNotChooseTheFile()
    {
        ProxiedResponse answer = Server().Serve(Origin + "/Review/ReviewPage/app.js#top");

        Assert.Equal(200, answer.Status);
        Assert.Equal("// script", Encoding.UTF8.GetString(answer.Content));
    }

    // ---- what it refuses ---------------------------------------------------------------------

    /// <summary>
    /// Traversal, in the two forms that can reach here. `..` in the raw URL is resolved by the
    /// browser and by <see cref="Uri"/> before this class ever sees it - and clamps at the
    /// root, so it lands on a path that simply is not there - while the percent-encoded form
    /// survives both and arrives intact. Both must end at the same 404, and neither may read
    /// `secret.html`, which really exists one level above the web folder.
    /// </summary>
    [Theory]
    [InlineData("/../secret.html")]
    [InlineData("/Review/../../secret.html")]
    [InlineData("/%2e%2e/secret.html")]
    [InlineData("/Review/%2e%2e/%2e%2e/secret.html")]
    [InlineData("/..%2f..%2fsecret.html")]
    [InlineData("/Review%5C..%5Csecret.html")]
    [InlineData("/%2e%2e%5csecret.html")]
    public void TraversalOutOfTheWebFolderIsRefused(string path)
    {
        ProxiedResponse answer = Server().Serve(Origin + path);

        AssertNotFound(answer);
        Assert.DoesNotContain("outside", Encoding.UTF8.GetString(answer.Content), StringComparison.Ordinal);
    }

    /// <summary>
    /// An absolute path smuggled in as a segment. `Path.Combine` would take a rooted second
    /// argument and discard the first, so a drive letter or a UNC prefix is refused before the
    /// path is built rather than caught after it.
    /// </summary>
    [Theory]
    [InlineData("/C:/Windows/win.ini.html")]
    [InlineData("/C:%5CWindows%5Cwin.ini.html")]
    [InlineData("//evil.invalid/share/x.html")]
    public void AnAbsoluteOrRootedPathIsRefused(string path)
    {
        AssertNotFound(Server().Serve(Origin + path));
    }

    /// <summary>
    /// An extension the pages do not ship is a 404 even when the file is there. `vendor/`
    /// carries a `LICENSES.md` that no page loads, and a folder that happens to hold a
    /// `settings.json` or a `.log` must not become a download.
    /// </summary>
    [Theory]
    [InlineData("notes.md")]
    [InlineData("notes.txt")]
    [InlineData("archive.zip")]
    [InlineData("noextension")]
    [InlineData("page.js.map")]
    public void AnUnknownExtensionIsRefusedEvenWhenTheFileExists(string name)
    {
        File.WriteAllText(Path.Combine(_web, name), "present");

        AssertNotFound(Server().Serve(Origin + "/" + name));
    }

    /// <summary>No directory listing, and no implicit `index.html` - the pane navigates to a
    /// file name every time, so a directory request is a bug rather than a shortcut.</summary>
    [Theory]
    [InlineData("/")]
    [InlineData("/Review/")]
    [InlineData("/Review")]
    [InlineData("/Review/ReviewPage/")]
    public void ADirectoryIsRefused(string path)
    {
        AssertNotFound(Server().Serve(Origin + path));
    }

    [Fact]
    public void AFileThatIsNotThereIsRefused()
    {
        AssertNotFound(Server().Serve(Origin + "/Review/ReviewPage/missing.js"));
    }

    /// <summary>
    /// Only this origin. The filter is `https://swreview.invalid/*`, so nothing else should
    /// arrive - but the page file server is the last thing in the chain, and a rule that is
    /// only enforced by the filter is a rule that a wider filter would silently repeal.
    /// </summary>
    [Theory]
    [InlineData("http://127.0.0.1:51234/Review/ReviewPage/index.html")]
    [InlineData("https://evil.invalid/Review/ReviewPage/index.html")]
    [InlineData("http://swreview.invalid/Review/ReviewPage/index.html")]
    [InlineData("https://swreview.invalid.evil.test/Review/ReviewPage/index.html")]
    [InlineData("file:///C:/web/Review/ReviewPage/index.html")]
    public void AnythingOffThePageOriginIsRefused(string url)
    {
        AssertNotFound(Server().Serve(url));
    }

    [Theory]
    [InlineData("not a url")]
    [InlineData("")]
    [InlineData("/Review/ReviewPage/index.html")]
    public void AMalformedUrlIsRefused(string url)
    {
        AssertNotFound(Server().Serve(url));
    }

    [Fact]
    public void ANullUrlIsRefusedRatherThanThrown()
    {
        AssertNotFound(Server().Serve(null!));
    }

    /// <summary>
    /// A 404 says nothing about what is or is not on the disk: one body, one content type, for
    /// every refusal above. A page that asked for something it should not have asked for learns
    /// only that it did not get it.
    /// </summary>
    [Fact]
    public void EveryRefusalLooksTheSame()
    {
        PageFileServer server = Server();

        ProxiedResponse missing = server.Serve(Origin + "/Review/ReviewPage/missing.js");
        ProxiedResponse traversal = server.Serve(Origin + "/%2e%2e/secret.html");
        ProxiedResponse unknown = server.Serve(Origin + "/Review/ReviewPage/index.html.bak");

        Assert.Equal(missing.Headers, traversal.Headers);
        Assert.Equal(missing.Headers, unknown.Headers);
        Assert.Equal(missing.Content, traversal.Content);
        Assert.Equal(missing.Content, unknown.Content);
    }

    // ---- the folder the add-in actually ships ------------------------------------------------

    /// <summary>
    /// Every reference in the four shipped pages, resolved against the page's own URL and served
    /// the way `TaskPaneControl` serves it. The list is <b>read out of the pages</b> rather than
    /// written down here: a hand-kept list is the thing that drifts the next time a page gains a
    /// file, and it had already drifted - three of the four stylesheets and `addon-fit.js` were
    /// missing from it while this test's own summary claimed to cover every file the pages load.
    /// The folder mapping that used to answer these unconditionally is gone, so a file this
    /// server refuses is a blank tab.
    /// </summary>
    [Fact]
    public void EveryFileTheShippedPagesLoadIsServed()
    {
        var server = new PageFileServer(ReviewPageFiles.WebFolder);

        foreach (string pageUrl in ShippedPageUrls)
        {
            ProxiedResponse page = AssertServed(server, pageUrl);
            Assert.Contains("Content-Type: text/html", page.Headers, StringComparison.Ordinal);

            IReadOnlyList<string> referenced = ReferencedUrls(
                Encoding.UTF8.GetString(page.Content), pageUrl);

            Assert.True(
                referenced.Count > 0,
                pageUrl + " loads no script and no stylesheet, which means the scan below found "
                    + "nothing rather than that the page is empty.");

            foreach (string url in referenced)
            {
                AssertServed(server, url);
            }
        }
    }

    /// <summary>
    /// The `../../shared/dom.js` every page carries has to come back as `/shared/dom.js`. The
    /// scan above would pass just as well if relative resolution were broken and every reference
    /// collapsed to nothing, so the one reference that leaves its page's folder is named here.
    /// </summary>
    [Fact]
    public void ASharedScriptReferencedFromAPageFolderResolvesAboveIt()
    {
        var server = new PageFileServer(ReviewPageFiles.WebFolder);
        string html = Encoding.UTF8.GetString(
            AssertServed(server, TaskPaneControl.ReviewPageUrl).Content);

        Assert.Contains(
            Origin + "/shared/dom.js",
            ReferencedUrls(html, TaskPaneControl.ReviewPageUrl));
    }

    /// <summary>
    /// The closed extension list, against the folder that actually ships rather than a temp
    /// file: every file under `web/` is served except the vendor licence notice, which is the
    /// named reason the list is closed. A new asset the server cannot answer - a `.woff`, a
    /// `.map`, a `settings.json` that is really a `.log` - fails here instead of shipping as a
    /// 404 nobody sees until a tab loads half-built.
    /// </summary>
    [Fact]
    public void TheOnlyShippedFileThatIsNotServedIsTheVendorLicenceNotice()
    {
        var server = new PageFileServer(ReviewPageFiles.WebFolder);
        string root = ReviewPageFiles.WebFolder;
        Assert.True(Directory.Exists(root), "The web folder was not copied to " + root + ".");

        string[] files = Directory.GetFiles(root, "*", SearchOption.AllDirectories);
        Assert.NotEmpty(files);

        var refused = new List<string>();
        foreach (string file in files)
        {
            string url = Origin + "/"
                + file.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar)
                    .Replace(Path.DirectorySeparatorChar, '/');

            if (server.Serve(url).Status != 200)
            {
                refused.Add(url);
            }
        }

        Assert.Equal(new[] { Origin + "/Terminal/TerminalPage/vendor/LICENSES.md" }, refused);
    }

    /// <summary>The four pages the pane navigates to, taken from the constants it navigates by.</summary>
    private static IEnumerable<string> ShippedPageUrls => new[]
    {
        TaskPaneControl.ReviewPageUrl,
        TaskPaneControl.TerminalPageUrl,
        TaskPaneControl.ModelCheckPageUrl,
        TaskPaneControl.RemodelPageUrl,
    };

    /// <summary>
    /// Every `src=`/`href=` in a page, resolved against the page's own URL. A `#fragment` is the
    /// renderer's business and is skipped; anything else has to be on the page origin, because
    /// the CSP refuses an off-origin load anyway and a page that grew one should say so here.
    /// </summary>
    private static IReadOnlyList<string> ReferencedUrls(string html, string pageUrl)
    {
        var pageUri = new Uri(pageUrl, UriKind.Absolute);
        var urls = new List<string>();

        foreach (Match match in Reference.Matches(html))
        {
            string reference = match.Groups[1].Value.Length > 0
                ? match.Groups[1].Value
                : match.Groups[2].Value;

            if (reference.Length == 0 || reference[0] == '#')
            {
                continue;
            }

            string resolved = new Uri(pageUri, reference).GetLeftPart(UriPartial.Path);
            Assert.StartsWith(Origin + "/", resolved, StringComparison.Ordinal);

            if (!urls.Contains(resolved))
            {
                urls.Add(resolved);
            }
        }

        return urls;
    }

    private static readonly Regex Reference = new Regex(
        @"\b(?:src|href)\s*=\s*(?:""([^""]*)""|'([^']*)')",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static ProxiedResponse AssertServed(PageFileServer server, string url)
    {
        ProxiedResponse answer = server.Serve(url);

        Assert.True(
            answer.Status == 200,
            url + " was not served from the shipped web folder ("
                + ReviewPageFiles.WebFolder + "); the pane has no folder mapping any more, so a "
                + "file this server refuses is a blank tab.");
        Assert.Contains("Content-Type: ", answer.Headers, StringComparison.Ordinal);
        Assert.NotEmpty(answer.Content);

        return answer;
    }

    private static void AssertNotFound(ProxiedResponse answer)
    {
        Assert.Equal(404, answer.Status);
        Assert.Equal("Not Found", answer.Reason);
        Assert.Contains("Cache-Control: no-store", answer.Headers, StringComparison.Ordinal);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_root))
            {
                Directory.Delete(_root, recursive: true);
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
