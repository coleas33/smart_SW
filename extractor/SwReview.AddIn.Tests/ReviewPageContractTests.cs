using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T042: the Review page's half of `specs/002-task-pane-assistant/contracts/pane-host-messages.md`.
///
/// This is a scan of the shipped page scripts, not a behavioural test - there is no JS
/// toolchain in this repository and no headless runner - so it is worth being precise about
/// what it can and cannot prove. It proves that the page and the host are talking about the
/// same message vocabulary, in both directions:
///
/// 1. <b>Nothing is invented.</b> Every type the page posts to the host is a row of the
///    "Review page to host" table. A type the host has never heard of is answered
///    `{type: "error"}` at runtime and the feature behind it silently does nothing.
/// 2. <b>Nothing is orphaned.</b> Every row of that table is exercised by the page. The page
///    is the only sender these host handlers have, so a row nothing sends is either dead host
///    code or a feature that was specified and never built - which is exactly what T041 adds
///    (`review.start`, `entity.show`, `report.open`, `folder.open`, `log.open`), and exactly
///    why this test is red before it.
/// 3. <b>Every type the page names is documented somewhere.</b> The page handles two distinct
///    vocabularies - host messages from `window.chrome.webview` and chat events from the
///    backend's SSE stream - so a dotted type literal in the page must appear either in
///    pane-host-messages.md or in the `type` enum of chat-events.schema.json. A typo
///    (`tool.finish`, `document.change`) is otherwise invisible: it compiles, it runs, and the
///    card it should have drawn simply never appears.
/// 4. <b>The key never comes back.</b> The page may *send* a key in a `settings.save` payload
///    and may never read one: no `api_key_protected` anywhere, and no read of an `api_key`
///    field off anything the host replied with (FR-015).
///
/// What it cannot prove is that the page *behaves*: that reconnect sends the highest seen
/// `seq`, that event 501 evicts event 1, that the follow-up box is disabled between
/// `tool.started` and `turn.ended`. Those are the open question in tasks.md ("Behavioural
/// tests for the two pages") and are covered by the host-side tests plus quickstart Scenario 1.
/// Injection is not in scope here either; that is T042a.
/// </summary>
public sealed class ReviewPageContractTests
{
    /// <summary>
    /// The one documented exception to rule 2. `init` already carries the settings and
    /// `settings.saved` carries them again after every save, so the page has no reason to ask
    /// for them; the row exists for a host that wants to answer a page that reloads itself.
    /// </summary>
    private static readonly string[] RowsThePageNeedNotSend = { "settings.get" };

    private static readonly PaneContract Contract = PaneContract.Load();

    // ---- rule 1: nothing is invented ------------------------------------------------------

    [Fact]
    public void EveryTypeThePageSendsIsARowOfTheContract()
    {
        var undocumented = new List<string>();

        foreach (KeyValuePair<string, string> script in ReviewPageFiles.Scripts())
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
            "The page posts message types the host contract does not define:"
                + Environment.NewLine + string.Join(Environment.NewLine, undocumented)
                + Environment.NewLine + "Documented: " + Join(Contract.PageToHost));
    }

    // ---- rule 2: nothing is orphaned ------------------------------------------------------

    [Fact]
    public void EveryPageToHostRowIsExercisedByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            ReviewPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> missing = Contract.PageToHost
            .Where(type => !RowsThePageNeedNotSend.Contains(type))
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            missing.Count == 0,
            "The contract defines host handlers the page never asks for: " + Join(missing)
                + Environment.NewLine
                + "Either the page is missing a feature (T041) or the row belongs in "
                + "contracts/pane-host-messages.md's history rather than its tables.");
    }

    // ---- rule 3: every type the page names is documented -----------------------------------

    [Fact]
    public void EveryMessageTypeThePageNamesIsDocumented()
    {
        var unknown = new List<string>();

        foreach (KeyValuePair<string, string> script in ReviewPageFiles.Scripts())
        {
            foreach (string literal in DottedLiterals(Strip(script.Value)))
            {
                if (!Contract.PageToHost.Contains(literal)
                    && !Contract.HostToPage.Contains(literal)
                    && !Contract.ChatEvents.Contains(literal))
                {
                    unknown.Add($"{script.Key}: '{literal}'");
                }
            }
        }

        Assert.True(
            unknown.Count == 0,
            "The page names types that are in neither contract (a typo in one of these is "
                + "invisible at runtime):" + Environment.NewLine
                + string.Join(Environment.NewLine, unknown)
                + Environment.NewLine + "pane-host-messages.md: "
                + Join(Contract.PageToHost.Concat(Contract.HostToPage))
                + Environment.NewLine + "chat-events.schema.json: " + Join(Contract.ChatEvents));
    }

    // ---- the event stream travels over this channel -----------------------------------------

    /// <summary>
    /// The four rows the event stream now travels on, and the reader that had to go with them.
    ///
    /// Rules 1 to 3 above already hold the page and the contract to the same vocabulary, so this
    /// test exists for what they cannot see: that these four rows in particular are on the
    /// tables, and that the page no longer reads `GET /sessions/{id}/events` itself. The second
    /// half is the point of the round. A page that kept its `fetch` reader <i>and</i> handled
    /// `events.frame` would pass every scan above while still making the one call a web filter
    /// intercepts, and the pane would go on showing nothing on the workstation this was built
    /// for (`docs/pane-backend-proxy.md`).
    /// </summary>
    [Fact]
    public void TheEventStreamRowsAreOnTheTablesAndThePageNoLongerReadsTheStreamItself()
    {
        Assert.Contains("events.open", Contract.PageToHost);
        Assert.Contains("events.close", Contract.PageToHost);
        Assert.Contains("events.frame", Contract.HostToPage);
        Assert.Contains("events.closed", Contract.HostToPage);

        string all = string.Join(
            Environment.NewLine,
            ReviewPageFiles.Scripts().Select(script => Strip(script.Value)));

        foreach (string type in new[] { "events.open", "events.close", "events.frame", "events.closed" })
        {
            Assert.True(Mentions(all, type), $"the page never names '{type}'.");
        }

        foreach (string gone in new[] { "text/event-stream", "getReader", "ReadableStream" })
        {
            Assert.False(
                all.Contains(gone),
                $"the page still reads the event stream itself ({gone}); the host reads that "
                    + "route and pushes frames as `events.frame` (contracts/chat-api.md).");
        }
    }

    // ---- the reply names the document it reviewed -------------------------------------------

    /// <summary>
    /// U8: `review.started` names the document the review is of, and the contract row says so,
    /// because the page binds the results on screen to it (docs/pane-findings-2026-09-20-review-gui.md
    /// section 1). A reply shape the contract does not print is a field the next host can drop.
    /// </summary>
    [Fact]
    public void TheReviewStartRowsReplyNamesTheDocumentItReviewed()
    {
        string row = ReviewPageFiles.ReadContract("pane-host-messages.md")
            .Split('\n')
            .Single(line => line.StartsWith("| `review.start` |", StringComparison.Ordinal));

        Assert.Contains("review.started {chat_id, run_dir, not_examined, document}", row, StringComparison.Ordinal);
        Assert.Contains("`document` is `{path, configuration}`", row, StringComparison.Ordinal);
    }

    // ---- rule 4: the key never comes back --------------------------------------------------

    [Fact]
    public void ThePageNeverReadsAKeyFieldBack()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> script in ReviewPageFiles.Scripts())
        {
            string source = Strip(script.Value);

            if (source.Contains("api_key_protected"))
            {
                offences.Add($"{script.Key} names api_key_protected; the host never sends it (FR-015).");
            }

            foreach (Match match in KeyFieldRead.Matches(source))
            {
                offences.Add($"{script.Key} reads a key field: {match.Value.Trim()}");
            }
        }

        Assert.True(
            offences.Count == 0,
            "The page must never read a key back from the host - a key the renderer process "
                + "holds is a key in every crash dump of it:" + Environment.NewLine
                + string.Join(Environment.NewLine, offences));
    }

    // ---- scanning --------------------------------------------------------------------------

    private static readonly Regex SendCall = new Regex(
        @"\bsend\s*\(\s*['""]([a-z][a-z0-9_.]*)['""]", RegexOptions.Compiled);

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

    /// <summary>
    /// `.api_key` and `['api_key']` are reads; `api_key:` is the write in the `settings.save`
    /// payload, which is the one place a key is allowed to appear (pane-host-messages.md).
    /// </summary>
    private static readonly Regex KeyFieldRead = new Regex(
        @"(\.\s*api_key\b)|(\[\s*['""]api_key['""]\s*\])", RegexOptions.Compiled);

    /// <summary>
    /// Extensions a dotted literal is allowed to end in. `'app.js'`, `'report.md'` and
    /// `'events.jsonl'` are file names, not message types, and the scan would otherwise have to
    /// guess which is which.
    /// </summary>
    private static readonly string[] FileExtensions =
        { "js", "css", "html", "htm", "md", "json", "jsonl", "txt", "svg", "png", "map" };

    /// <summary>
    /// Comments out of the way before scanning. Block comments and whole-line `//` comments
    /// only: a trailing comment is left alone, because stripping it would mean deciding whether
    /// the `//` is inside a string ('https://127.0.0.1') without parsing JavaScript.
    /// </summary>
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

    // ---- the contract itself ----------------------------------------------------------------

    /// <summary>
    /// `pane-host-messages.md` and `chat-events.schema.json`, read as data so a contract change
    /// lands here rather than in a hand-kept list that drifts.
    /// </summary>
    private sealed class PaneContract
    {
        private PaneContract(ISet<string> pageToHost, ISet<string> hostToPage, ISet<string> chatEvents)
        {
            PageToHost = pageToHost;
            HostToPage = hostToPage;
            ChatEvents = chatEvents;
        }

        /// <summary>The `type` column of the "Review page to host" table.</summary>
        public ISet<string> PageToHost { get; }

        /// <summary>
        /// The unsolicited table, plus every type named as a reply in the host-action column
        /// (`init`, `review.started`, `settings.saved`, `settings`, `models`, `entity.shown`,
        /// `ok`, `error`). Replies are matched by `id` rather than by type, so they are not a
        /// table of their own; they are read out of the prose that defines them.
        /// </summary>
        public ISet<string> HostToPage { get; }

        /// <summary>The `type` enum of chat-events.schema.json: what the SSE stream carries.</summary>
        public ISet<string> ChatEvents { get; }

        public static PaneContract Load()
        {
            var pageToHost = new HashSet<string>(StringComparer.Ordinal);
            var hostToPage = new HashSet<string>(StringComparer.Ordinal);

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
                if (section.StartsWith("Review page", StringComparison.Ordinal))
                {
                    pageToHost.Add(type);
                    foreach (string reply in BacktickedTypes(row.Groups[2].Value))
                    {
                        hostToPage.Add(reply);
                    }
                }
                else if (section.StartsWith("Host", StringComparison.Ordinal)
                    && section.IndexOf("review page", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    hostToPage.Add(type);
                }
            }

            // A parser that quietly matched nothing would make every test above vacuous.
            Assert.True(
                pageToHost.Count >= 9 && hostToPage.Count >= 8,
                $"contracts/pane-host-messages.md did not parse: {pageToHost.Count} page-to-host rows, "
                    + $"{hostToPage.Count} host-to-page types. Did the table or heading shape change?");

            var chatEvents = new HashSet<string>(StringComparer.Ordinal);
            using (JsonDocument schema = JsonDocument.Parse(ReviewPageFiles.ReadContract("chat-events.schema.json")))
            {
                foreach (JsonElement value in schema.RootElement
                    .GetProperty("properties").GetProperty("type").GetProperty("enum").EnumerateArray())
                {
                    chatEvents.Add(value.GetString()!);
                }
            }

            Assert.True(chatEvents.Count >= 13, "chat-events.schema.json did not parse its type enum.");

            return new PaneContract(pageToHost, hostToPage, chatEvents);
        }

        private static readonly Regex TableRow = new Regex(
            @"^\|\s*`([a-z][a-z0-9_.]*)`\s*\|(.*)$", RegexOptions.Compiled);

        private static readonly Regex Backticked = new Regex(@"`([^`]+)`", RegexOptions.Compiled);

        private static readonly Regex TypeToken = new Regex(
            @"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$", RegexOptions.Compiled);

        /// <summary>
        /// The first token of every backticked span in a host-action cell, when it looks like a
        /// message type: `review.started {chat_id, run_dir}` yields `review.started`, and
        /// `POST /sessions` yields nothing.
        /// </summary>
        private static IEnumerable<string> BacktickedTypes(string cell) =>
            Backticked.Matches(cell).Cast<Match>()
                .Select(match => match.Groups[1].Value
                    .Split(new[] { ' ', '{', '}', ',' }, StringSplitOptions.RemoveEmptyEntries)
                    .FirstOrDefault() ?? string.Empty)
                .Where(token => TypeToken.IsMatch(token));
    }
}
