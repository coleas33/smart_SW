using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T061: the Terminal page's half of
/// `specs/002-task-pane-assistant/contracts/pane-host-messages.md`, plus the two things about
/// the Terminal tab that the contract states and only the host can honour - the page URL and
/// the terminal run folder.
///
/// Like <see cref="ReviewPageContractTests"/> this is a scan of the shipped page rather than a
/// behavioural test - there is no JS toolchain in this repository - so it is worth saying what
/// it proves and what it does not.
///
/// It proves the page and the host share one vocabulary in both directions: nothing the page
/// posts is invented, no row of the table is left with no sender, and every dotted type
/// literal in the page is a documented one. A typo such as `terminal.resized` is otherwise
/// invisible - it compiles, it runs, and the resize simply never reaches the pseudo-console.
///
/// It also holds the page to the two rules the contract puts on *both* pages, because the
/// Terminal page carries bytes a model wrote straight to the screen: the identical strict CSP
/// meta tag, and markup that is never assigned (`textContent` only, no inline handler). The
/// terminal's own bytes go through xterm.js, which is a VT parser and not an HTML parser; the
/// rule here is about everything around it - the CLI list, the install steps, the error banner.
///
/// What it cannot prove is that the page behaves: that a resize really reaches the host, that
/// output is decoded before it is written, that Start is disabled while a session runs. Those
/// are the open question tasks.md records under "Behavioural tests for the two pages" and are
/// covered by quickstart Scenario 3.
/// </summary>
public sealed class TerminalPageContractTests
{
    private static readonly TerminalContract Contract = TerminalContract.Load();

    // ---- rule 1: nothing is invented ---------------------------------------------------------

    [Fact]
    public void EveryTypeThePageSendsIsARowOfTheContract()
    {
        var undocumented = new List<string>();

        foreach (KeyValuePair<string, string> script in TerminalPageFiles.Scripts())
        {
            foreach (string type in SentTypes(Strip(script.Value)))
            {
                if (!Contract.PageToHost.Contains(type))
                {
                    undocumented.Add($"{script.Key} posts `{type}`");
                }
            }
        }

        Assert.True(
            undocumented.Count == 0,
            "The Terminal page posts message types the host contract does not define:"
                + Environment.NewLine + string.Join(Environment.NewLine, undocumented)
                + Environment.NewLine + "Documented: " + Join(Contract.PageToHost));
    }

    // ---- rule 2: nothing is orphaned ---------------------------------------------------------

    [Fact]
    public void EveryTerminalPageToHostRowIsExercisedByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            TerminalPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> missing = Contract.PageToHost
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            missing.Count == 0,
            "The contract defines terminal host handlers the page never asks for: " + Join(missing)
                + Environment.NewLine
                + "The page is the only sender these handlers have, so a row nothing sends is "
                + "either dead host code or a feature that was specified and never built.");
    }

    // ---- rule 3: every type the page names is documented --------------------------------------

    [Fact]
    public void EveryMessageTypeThePageNamesIsDocumented()
    {
        var unknown = new List<string>();

        foreach (KeyValuePair<string, string> script in TerminalPageFiles.Scripts())
        {
            foreach (string literal in DottedLiterals(Strip(script.Value)))
            {
                if (!Contract.PageToHost.Contains(literal) && !Contract.HostToPage.Contains(literal))
                {
                    unknown.Add($"{script.Key}: '{literal}'");
                }
            }
        }

        Assert.True(
            unknown.Count == 0,
            "The Terminal page names types the terminal tables do not define (a typo in one of "
                + "these is invisible at runtime):" + Environment.NewLine
                + string.Join(Environment.NewLine, unknown)
                + Environment.NewLine + "Terminal page to host: " + Join(Contract.PageToHost)
                + Environment.NewLine + "Host to terminal page: " + Join(Contract.HostToPage));
    }

    /// <summary>
    /// The other direction of rule 3, which the review page's test cannot do and this one can:
    /// the host-to-page table is short and every row of it is a message the page has to do
    /// something with. A `chatlog.count` nobody reads is a counter that never moves, and a
    /// `terminal.exited` nobody reads is a Stop button that stays enabled for ever.
    /// </summary>
    [Fact]
    public void EveryUnsolicitedHostMessageIsHandledByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            TerminalPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> ignored = Contract.Unsolicited
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            ignored.Count == 0,
            "The host sends the Terminal page messages it never reads: " + Join(ignored));
    }

    // ---- the rules both pages share -----------------------------------------------------------

    /// <summary>
    /// Byte-for-byte the Review page's tag, which is byte-for-byte the contract's. Not "a CSP":
    /// the two pages share one browser process and one virtual host, and a terminal page that
    /// relaxed `script-src` would relax it for a page origin the Review page also lives on.
    /// </summary>
    [Fact]
    public void ThePageShipsTheSameStrictCspMetaTagAsTheReviewPage()
    {
        string expected = CspTag(ReviewPageFiles.IndexHtml(), "the Review page");
        string actual = CspTag(TerminalPageFiles.IndexHtml(), "the Terminal page");

        Assert.Equal(expected, actual);
        Assert.Contains("default-src 'none'", actual);
        Assert.Contains("script-src 'self'", actual);
    }

    [Fact]
    public void ThePageNeverAssignsMarkupAndHasNoInlineHandler()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> script in TerminalPageFiles.Scripts())
        {
            string source = Strip(script.Value);
            foreach (Match match in MarkupAssignment.Matches(source))
            {
                offences.Add($"{script.Key} uses {match.Value.Trim()}");
            }
        }

        string html = TerminalPageFiles.IndexHtml();
        foreach (Match match in InlineHandlerAttribute.Matches(html))
        {
            offences.Add($"index.html has an inline handler: {match.Value.Trim()}");
        }

        foreach (Match match in InlineScriptOrStyle.Matches(html))
        {
            offences.Add($"index.html has an inline {match.Groups[1].Value} block");
        }

        Assert.True(
            offences.Count == 0,
            "The Terminal page must build every node with textContent and attach every handler "
                + "with addEventListener - a CLI's output and an install message are text, not "
                + "markup (FR-029, contracts/pane-host-messages.md):" + Environment.NewLine
                + string.Join(Environment.NewLine, offences));
    }

    /// <summary>
    /// FR-015: secrets travel in an environment block and nowhere else. The Terminal page has no
    /// business with one - it never talks to the backend and never sees the tool-service secret -
    /// so the strongest thing this test can say is that the words do not appear at all.
    /// </summary>
    [Fact]
    public void ThePageNamesNoSecret()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> script in TerminalPageFiles.Scripts())
        {
            foreach (string word in new[] { "api_key", "secret", "token" })
            {
                if (Strip(script.Value).IndexOf(word, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    offences.Add($"{script.Key} names '{word}'");
                }
            }
        }

        Assert.True(
            offences.Count == 0,
            "The Terminal page holds no secret of any kind; a secret in a renderer process is a "
                + "secret in every crash dump of it:" + Environment.NewLine
                + string.Join(Environment.NewLine, offences));
    }

    // ---- what the page is made of --------------------------------------------------------------

    [Fact]
    public void ThePageShipsItsThreeFilesAndTheVendoredTerminal()
    {
        foreach (string name in new[]
        {
            "index.html",
            "term.js",
            "term.css",
            @"vendor\xterm.js",
            @"vendor\xterm.css",
            @"vendor\addon-fit.js",
        })
        {
            Assert.True(
                TerminalPageFiles.Exists(name),
                $"{name} is missing from {TerminalPageFiles.Folder}; check the Content items in "
                    + "SwReview.AddIn.csproj.");
        }
    }

    /// <summary>
    /// Everything the page loads is local. plan.md pins the vendored xterm.js and fit addon with
    /// "no CDN", and the CSP would block a remote origin anyway - silently, which is the problem:
    /// the pane would open on an empty black rectangle with the explanation in a DevTools console
    /// nobody inside SOLIDWORKS can see.
    /// </summary>
    [Fact]
    public void ThePageLoadsNothingFromARemoteOrigin()
    {
        string html = TerminalPageFiles.IndexHtml();
        string withoutCsp = CspMeta.Replace(html, string.Empty);

        List<string> remote = RemoteReference.Matches(withoutCsp).Cast<Match>()
            .Select(match => match.Value.Trim())
            .ToList();

        Assert.True(
            remote.Count == 0,
            "index.html references a remote origin: " + string.Join(", ", remote));
    }

    /// <summary>
    /// The three things about the terminal's own plumbing that the contract names and that a
    /// page which quietly skipped them would still start: output is base64 and has to be decoded
    /// before it is written, the size is negotiated in `cols`/`rows`, and Gemini appears in the
    /// dropdown as deferred rather than as a choice that fails on Start (decision 2026-09-13).
    /// </summary>
    [Fact]
    public void ThePageDecodesOutputNegotiatesSizeAndShowsGeminiAsDeferred()
    {
        string script = Strip(TerminalPageFiles.Read("term.js"));

        Assert.Contains("data_base64", script);
        Assert.Contains("atob", script);
        Assert.Contains("cols", script);
        Assert.Contains("rows", script);
        Assert.Contains("install_steps", script);
        Assert.True(
            script.IndexOf("deferred", StringComparison.OrdinalIgnoreCase) >= 0,
            "The dropdown never says a CLI is deferred, so choosing Gemini looks like a choice "
                + "that will work (decision 2026-09-13: the Gemini terminal is not in v1).");
    }

    // ---- the Terminal tab ----------------------------------------------------------------------

    [Fact]
    public void TheTabNavigatesToThePageOnTheVirtualHost()
    {
        Assert.Equal(
            "https://swreview.invalid/Terminal/TerminalPage/index.html",
            TaskPaneControl.TerminalPageUrl);

        Assert.True(
            File.Exists(Path.Combine(TerminalPageFiles.Folder, "index.html")),
            $"{TaskPaneControl.TerminalPageUrl} maps to {TerminalPageFiles.Folder}, which has no "
                + "index.html.");
    }

    /// <summary>
    /// The contract's terminal run folder rule, the "otherwise" half: the Terminal tab is
    /// reachable with no review and no document open, so a folder is created rather than assumed,
    /// and it is created through the same helper `ReviewHost` uses (T040) so both are named the
    /// one way an engineer sorts by in Explorer.
    /// </summary>
    [Fact]
    public void TheTerminalRunFolderIsCreatedUnderTheRunRootWhenNoSessionExists()
    {
        string root = NewRunRoot();
        try
        {
            var options = new TaskPaneOptions(new UnusedEnvironmentFactory(), root)
            {
                Now = () => new DateTime(2026, 9, 13, 14, 5, 6),
            };

            string folder = WithPane(options, pane => pane.TerminalRunFolder());

            Assert.Equal(Path.Combine(root, "20260913-140506-terminal"), folder);
            Assert.True(Directory.Exists(folder), $"{folder} was named but never created.");
        }
        finally
        {
            Delete(root);
        }
    }

    /// <summary>
    /// The other half: a terminal started after a review runs in that review's folder, so the
    /// CLI's generated profile, its working directory and the review's evidence are one place.
    /// </summary>
    [Fact]
    public void TheTerminalRunsInTheCurrentSessionsFolderWhenThereIsOne()
    {
        string root = NewRunRoot();
        try
        {
            string session = Path.Combine(root, "20260913-120000-bracket");
            Directory.CreateDirectory(session);

            var options = new TaskPaneOptions(new UnusedEnvironmentFactory(), root)
            {
                Now = () => new DateTime(2026, 9, 13, 14, 5, 6),
                CurrentSessionRunDirectory = () => session,
            };

            string folder = WithPane(options, pane => pane.TerminalRunFolder());

            Assert.Equal(session, folder);
            Assert.False(
                Directory.Exists(Path.Combine(root, "20260913-140506-terminal")),
                "A terminal folder was created even though the review's folder was available.");
        }
        finally
        {
            Delete(root);
        }
    }

    /// <summary>
    /// A session folder that has been deleted underneath the pane - the engineer tidied up, or a
    /// network share went away - must not take the Terminal tab down with it. The fallback is the
    /// same folder the no-session case creates.
    /// </summary>
    [Fact]
    public void AVanishedSessionFolderFallsBackToAFreshTerminalFolder()
    {
        string root = NewRunRoot();
        try
        {
            var options = new TaskPaneOptions(new UnusedEnvironmentFactory(), root)
            {
                Now = () => new DateTime(2026, 9, 13, 14, 5, 6),
                CurrentSessionRunDirectory = () => Path.Combine(root, "20260913-120000-gone"),
            };

            string folder = WithPane(options, pane => pane.TerminalRunFolder());

            Assert.Equal(Path.Combine(root, "20260913-140506-terminal"), folder);
            Assert.True(Directory.Exists(folder));
        }
        finally
        {
            Delete(root);
        }
    }

    /// <summary>
    /// `PostWebMessageAsJson` has UI-thread affinity and the terminal's read loop is a background
    /// thread, so the tab hands `TerminalSessionOptions.Channel` a channel that marshals. On a
    /// pane with no page - here, a missing WebView2 runtime - posting has to be a no-op: the read
    /// loop is still draining a pseudo-console and a throw on it would take the process with it.
    /// </summary>
    [Fact]
    public void TheTerminalChannelSwallowsAPostWhenThereIsNoPage()
    {
        var options = new TaskPaneOptions(new UnusedEnvironmentFactory(), @"C:\SwReviewRuns");

        WithPane(options, pane =>
        {
            Assert.NotNull(pane.TerminalChannel);

            Exception? escaped = Record.Exception(
                () => pane.TerminalChannel.PostMessage("{\"type\":\"terminal.output\"}"));

            Assert.True(escaped == null, "Posting to a page that is not there threw: " + escaped);
            return 0;
        });
    }

    // ---- scanning ---------------------------------------------------------------------------------

    /// <summary>
    /// `send` posts and forgets, `request` waits for the reply that echoes its `id`. Both are
    /// matched, because which one a type goes through is the page's business and the contract's
    /// vocabulary is the same either way.
    /// </summary>
    private static readonly Regex SendCall = new Regex(
        @"\b(?:send|request)\s*\(\s*['""]([a-z][a-z0-9_.]*)['""]", RegexOptions.Compiled);

    private static readonly Regex TypeProperty = new Regex(
        @"\btype\s*:\s*['""]([a-z][a-z0-9_.]*)['""]", RegexOptions.Compiled);

    private static readonly Regex StringLiteral = new Regex(
        @"'([^'\\\r\n]*)'|""([^""\\\r\n]*)""", RegexOptions.Compiled);

    private static readonly Regex DottedType = new Regex(
        @"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", RegexOptions.Compiled);

    private static readonly Regex BlockComment = new Regex(
        @"/\*.*?\*/", RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex WholeLineComment = new Regex(
        @"^[ \t]*//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    private static readonly Regex MarkupAssignment = new Regex(
        @"\b(innerHTML|outerHTML|insertAdjacentHTML|document\s*\.\s*write)\b",
        RegexOptions.Compiled);

    /// <summary>`onclick=`, `onload=` and the rest, as attributes rather than as words.</summary>
    private static readonly Regex InlineHandlerAttribute = new Regex(
        @"<[^>]*\son[a-z]+\s*=", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex InlineScriptOrStyle = new Regex(
        @"<(script|style)(?![^>]*\ssrc\s*=)[^>]*>(?!\s*</\1>)",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex CspMeta = new Regex(
        @"<meta\s+http-equiv=""Content-Security-Policy""[^>]*>",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex CspContent = new Regex(
        @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""(?<policy>[^""]*)""",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex RemoteReference = new Regex(
        @"(src|href)\s*=\s*""(https?:)?//[^""]*""", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    /// <summary>
    /// File names that happen to look like dotted types. Same list and same reason as
    /// <see cref="ReviewPageContractTests"/>: `'term.js'` is a script, not a message.
    /// </summary>
    private static readonly string[] FileExtensions =
        { "js", "css", "html", "htm", "md", "json", "jsonl", "txt", "svg", "png", "map" };

    private static string Strip(string source) =>
        WholeLineComment.Replace(BlockComment.Replace(source, " "), string.Empty);

    private static IEnumerable<string> SentTypes(string source) =>
        SendCall.Matches(source).Cast<Match>()
            .Concat(TypeProperty.Matches(source).Cast<Match>())
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.Ordinal);

    private static IEnumerable<string> DottedLiterals(string source) =>
        StringLiteral.Matches(source).Cast<Match>()
            .Select(match => match.Groups[1].Success ? match.Groups[1].Value : match.Groups[2].Value)
            .Where(value => DottedType.IsMatch(value))
            .Where(value => !FileExtensions.Contains(value.Substring(value.LastIndexOf('.') + 1)))
            .Distinct(StringComparer.Ordinal);

    private static bool Mentions(string source, string type) =>
        source.Contains("'" + type + "'") || source.Contains("\"" + type + "\"");

    private static string Join(IEnumerable<string> values) =>
        string.Join(", ", values.OrderBy(value => value, StringComparer.Ordinal));

    private static string CspTag(string html, string which)
    {
        Match match = CspContent.Match(html);
        Assert.True(match.Success, $"{which} ships no Content-Security-Policy meta tag.");
        return match.Groups["policy"].Value;
    }

    // ---- the pane, on a thread of the kind SOLIDWORKS gives it -------------------------------------

    private static T WithPane<T>(TaskPaneOptions options, Func<TaskPaneControl, T> body)
    {
        T result = default!;

        StaHost.Run(form =>
        {
            using (var control = new TaskPaneControl(options))
            {
                control.Dock = DockStyle.Fill;
                form.Controls.Add(control);
                result = body(control);
            }

            return Task.CompletedTask;
        });

        return result;
    }

    private static string NewRunRoot()
    {
        string root = Path.Combine(
            Path.GetTempPath(), "swreview-terminal-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }

    private static void Delete(string folder)
    {
        try
        {
            Directory.Delete(folder, true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    /// <summary>
    /// A factory the tests here never expect to be called: none of them loads a page. It fails
    /// rather than returning null so that a pane which started asking for an environment shows up
    /// as a failure here instead of as a null reference somewhere else.
    /// </summary>
    private sealed class UnusedEnvironmentFactory : IWebViewEnvironmentFactory
    {
        public Task<CoreWebView2Environment> CreateAsync() =>
            throw new WebView2RuntimeNotFoundException(
                "TerminalPageContractTests does not load a page (simulated missing runtime).");
    }

    // ---- the contract itself -------------------------------------------------------------------------

    /// <summary>
    /// The two terminal tables of `pane-host-messages.md`, read as data so a contract change
    /// lands here rather than in a hand-kept list that drifts.
    ///
    /// Only the terminal sections: a Terminal page that posted `review.start` would be a bug, and
    /// a parser that loaded both pages' tables could not see it.
    /// </summary>
    private sealed class TerminalContract
    {
        private TerminalContract(
            ISet<string> pageToHost, ISet<string> hostToPage, ISet<string> unsolicited)
        {
            PageToHost = pageToHost;
            HostToPage = hostToPage;
            Unsolicited = unsolicited;
        }

        /// <summary>The `type` column of "Terminal page to host".</summary>
        public ISet<string> PageToHost { get; }

        /// <summary>The unsolicited table, plus every reply named in a host-action cell
        /// (`init`, `terminal.started`, `terminal.stopped`, `error`).</summary>
        public ISet<string> HostToPage { get; }

        /// <summary>The unsolicited table on its own: what arrives with no request behind it.</summary>
        public ISet<string> Unsolicited { get; }

        public static TerminalContract Load()
        {
            var pageToHost = new HashSet<string>(StringComparer.Ordinal);
            var hostToPage = new HashSet<string>(StringComparer.Ordinal);
            var unsolicited = new HashSet<string>(StringComparer.Ordinal);

            string? section = null;
            foreach (string raw in ReviewPageFiles.ReadContract("pane-host-messages.md").Split('\n'))
            {
                string line = raw.TrimEnd('\r');
                if (line.StartsWith("## ", StringComparison.Ordinal))
                {
                    section = line.Substring(3).Trim();
                    continue;
                }

                Match row = TableRow.Match(line);
                if (!row.Success || section == null)
                {
                    continue;
                }

                string type = row.Groups[1].Value;
                if (section.StartsWith("Terminal page", StringComparison.Ordinal))
                {
                    pageToHost.Add(type);
                    foreach (string reply in RepliesIn(row.Groups[2].Value))
                    {
                        hostToPage.Add(reply);
                    }
                }
                else if (section.StartsWith("Host", StringComparison.Ordinal)
                    && section.IndexOf("terminal page", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    hostToPage.Add(type);
                    unsolicited.Add(type);
                }
            }

            // A parser that quietly matched nothing would make every test above vacuous.
            Assert.True(
                pageToHost.Count == 5 && unsolicited.Count == 3 && hostToPage.Count >= 6,
                $"contracts/pane-host-messages.md did not parse: {pageToHost.Count} terminal "
                    + $"page-to-host rows, {unsolicited.Count} unsolicited, {hostToPage.Count} "
                    + "host-to-page types. Did the tables or the headings change shape?");

            return new TerminalContract(pageToHost, hostToPage, unsolicited);
        }

        private static readonly Regex TableRow = new Regex(
            @"^\|\s*`([a-z][a-z0-9_.]*)`\s*\|(.*)$", RegexOptions.Compiled);

        private static readonly Regex Backticked = new Regex(@"`([^`]+)`", RegexOptions.Compiled);

        private static readonly Regex TypeToken = new Regex(
            @"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$", RegexOptions.Compiled);

        /// <summary>
        /// The first token of every backticked span in the row's <b>last</b> cell - the host
        /// action - when it looks like a message type: `terminal.started {pid, cwd}` yields
        /// `terminal.started`, and `ResizePseudoConsole` yields nothing. The last cell rather
        /// than the whole row, because the payload cell is backticked too and
        /// `` `{cols, rows}` `` would otherwise enter the vocabulary as a type called `cols`.
        /// </summary>
        private static IEnumerable<string> RepliesIn(string rest)
        {
            string action = rest
                .Split('|')
                .Select(cell => cell.Trim())
                .LastOrDefault(cell => cell.Length > 0) ?? string.Empty;

            return Backticked.Matches(action).Cast<Match>()
                .Select(match => match.Groups[1].Value
                    .Split(new[] { ' ', '{', '}', ',' }, StringSplitOptions.RemoveEmptyEntries)
                    .FirstOrDefault() ?? string.Empty)
                .Where(token => TypeToken.IsMatch(token));
        }
    }

    // ---- the shipped page ---------------------------------------------------------------------------

    /// <summary>
    /// Where the Terminal page's files are read from: the build output, which is the copy the
    /// add-in actually maps as `https://swreview.invalid`, for the same reason
    /// <see cref="ReviewPageFiles"/> reads the Review page's from there - a page file that never
    /// reaches `web/` must fail the scan rather than pass it from source.
    /// </summary>
    private static class TerminalPageFiles
    {
        public static string Folder =>
            Path.Combine(AppContext.BaseDirectory, "web", "Terminal", "TerminalPage");

        public static string IndexHtml() => Read("index.html");

        /// <summary>Every script the page ships, by name. `vendor/` is excluded: xterm.js and the
        /// fit addon are vendored byte-for-byte and are not ours to hold to the page's rules.</summary>
        public static IReadOnlyList<KeyValuePair<string, string>> Scripts()
        {
            AssertPresent();

            List<KeyValuePair<string, string>> scripts = Directory
                .GetFiles(Folder, "*.js", SearchOption.AllDirectories)
                .Where(path => !path.Split(Path.DirectorySeparatorChar).Contains("vendor"))
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                .Select(path => new KeyValuePair<string, string>(
                    path.Substring(Folder.Length).TrimStart(Path.DirectorySeparatorChar),
                    File.ReadAllText(path)))
                .ToList();

            Assert.True(
                scripts.Count > 0,
                $"No Terminal page scripts were found under {Folder}; check the Content items in "
                    + "SwReview.AddIn.csproj.");
            return scripts;
        }

        public static string Read(string name)
        {
            AssertPresent();
            string path = Path.Combine(Folder, name);
            Assert.True(File.Exists(path), $"{name} is missing from {Folder}.");
            return File.ReadAllText(path);
        }

        public static bool Exists(string name) => File.Exists(Path.Combine(Folder, name));

        private static void AssertPresent() =>
            Assert.True(
                Directory.Exists(Folder),
                $"The Terminal page was not copied to {Folder}; check the Content items in "
                    + "SwReview.AddIn.csproj.");
    }
}
