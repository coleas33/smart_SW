using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T041: no page script contains a ranking rule (FR-023, contracts/attention.md section 6).
///
/// <b>What this is guarding.</b> The whole point of the attention policy is that there is one
/// of it: `report/attention.py` ranks a finished session, the record is written beside it, and
/// `report.md`, the Model check tab, the Standards tab and the Review tab all render the rows
/// they are handed, in the order they were handed them. The moment a page decides that a `high`
/// comes before a `medium`, or sorts by check id "so the list looks tidy", there are two
/// policies: the one an engineer can argue with by pointing at a line of Python, and the one in
/// a renderer that nobody reads. The second always wins the argument at the workstation,
/// because it is the one on screen.
///
/// <b>Why a scan and not a behavioural test.</b> A render test proves the order is right for
/// the fixture it was handed - and <see cref="ModelCheckPageTests"/>,
/// <see cref="StandardsPageTests"/> and <see cref="ReviewPageAttentionPanelTests"/> all make
/// that assertion with rows in an order no page could have produced. What they cannot prove is
/// that no page will reorder some other list next year. That is a property of the source, so
/// it is scanned in the source, over every script all four pages run - which is why the Review
/// page's entry brings `shared/dom.js` in with it: a comparator helper added there would reach
/// every page in the pane at once. The Remodel tab joined the sweep with the owner's decision
/// 24A (004 T170), whose plan-lost notice was the first change to that page to be held to it.
///
/// <b>The allowlist is the interesting half.</b> Four ordered lists in these pages are display
/// orders, written down before this feature and unrelated to it, and two comparisons decide
/// which bucket a row is drawn in. Each is named below with the reason it is not a rank. A new
/// one has to be added here deliberately, with a reason, which is the whole mechanism: the
/// scan is never loosened, it is argued with.
/// </summary>
public sealed class PageRuleScanTests
{
    /// <summary>
    /// The words this feature ranks by, and the bucket names the pages already display. Three
    /// or more of them together inside one array literal is an order over finding vocabulary,
    /// which is what a band rule looks like when it is written in JavaScript.
    ///
    /// Severity and status are contracts/attention.md section 1's keys 4 and 5, verbatim. The
    /// bucket names are the two check tabs' and the coverage panel's own vocabulary; they are
    /// in here because a page that ordered those would be ordering findings by another name.
    /// </summary>
    private static readonly HashSet<string> Vocabulary = new HashSet<string>(
        new[]
        {
            // severity, key 5
            "high", "medium", "low", "info",

            // status, key 4
            "demonstrated", "suspected", "unresolved", "checked_within_scope",

            // the buckets the pages draw
            "failed", "warned", "warning", "error", "checked", "skipped", "out_of_scope",
            "waived",
        },
        StringComparer.Ordinal);

    /// <summary>
    /// Fewer than this many vocabulary words in one array literal is not an order: `['failed',
    /// 'warned']` in `check-page.js` is which two chips start pressed, and a pair cannot express
    /// a band rule that a single comparison would not express more plainly.
    /// </summary>
    private const int OrderedListSize = 3;

    /// <summary>
    /// The three ordered lists that were here before this feature, and the Remodel tab's, which
    /// joined the sweep later: each a display order and none of them a rank. Keyed by the script and by the vocabulary words it holds, sorted,
    /// so moving the list within its file is fine and adding a word to it is not.
    /// </summary>
    private static readonly Dictionary<string, string> AllowedOrders =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            {
                // `BUCKETS` in web/shared/check-page.js: the order a check page's header states
                // its counts in and the order the rule list is grouped in - what to act on
                // first. It orders buckets of rules, never findings, and every rule is in the
                // list whatever its bucket.
                "shared/check-page.js|checked,failed,out_of_scope,skipped,unresolved,warned",
                "the bucket display order of the two check tabs"
            },
            {
                // The `COUNTS` rows in Standards/StandardsPage/standards.js: which counts the
                // release headline states and in which order, each with the unit it counts.
                // contracts/standards-check.md D3; a count is not a rank.
                "Standards/StandardsPage/standards.js|checked,error,out_of_scope,skipped,"
                    + "unresolved,waived,warning",
                "the standards headline's count rows"
            },
            {
                // `coverageSummary`'s `order` in Review/ReviewPage/render.js: the order the
                // coverage panel lists its buckets in. Coverage items, not findings.
                "Review/ReviewPage/render.js|checked,failed,out_of_scope,skipped,unresolved",
                "the coverage panel's bucket order"
            },
            {
                // `BUCKETS` in Remodel/RemodelPage/remodel.js: the order the Remodel tab's before
                // and after grades state their counts in, the check tabs' bucket display order
                // over one run's grade. It orders buckets of rules, never findings, and every
                // bucket is drawn whatever its count. Written with the page (004 T133); in the
                // sweep since decision 24A (004 T170).
                "Remodel/RemodelPage/remodel.js|checked,failed,out_of_scope,skipped,unresolved,warned",
                "the Remodel tab's grade bucket order"
            },
        };

    /// <summary>
    /// The comparisons on a `severity` or `status` value that were here before this feature.
    /// Each decides which bucket or which card state a row is drawn in; none of them orders two
    /// rows against each other. Keyed by the script and the comparison as written.
    /// </summary>
    private static readonly Dictionary<string, string> AllowedComparisons =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            {
                // `bucketOfFinding` in web/shared/check-page.js: an accepted rule is drawn in
                // the `checked` chip rather than the `failed` one, because the rule layer
                // already decided that and the page reports it rather than re-deciding it.
                "shared/check-page.js|finding.status === 'checked_within_scope'",
                "which chip an accepted rule is drawn in"
            },
            {
                // The same function's warn-to-warned mapping. The two families spell the
                // advisory severity differently - `warn` in one catalogue, `warning` in the
                // other - and both mean the row is advice rather than a failure. It maps a
                // spelling to a bucket name; it puts nothing before anything.
                "shared/check-page.js|row.severity === 'warn'",
                "the warn-to-warned bucket mapping"
            },
            {
                "shared/check-page.js|row.severity === 'warning'",
                "the warn-to-warned bucket mapping, the other family's spelling"
            },
            {
                // `evidenceCard` in Review/ReviewPage/render.js: an evidence request's own
                // lifecycle - open, then answered - which is not a finding's status at all.
                "Review/ReviewPage/render.js|body.status === 'answered'",
                "whether an evidence request has been answered"
            },
            {
                // `changeRow` in Remodel/RemodelPage/remodel.js: a change record's own lifecycle -
                // written as `attempting` before its call and again with its outcome - which
                // decides whether the row carries the "written before the call" note. Not a
                // finding's status at all, and it puts no row before another.
                "Remodel/RemodelPage/remodel.js|change.status === 'attempting'",
                "whether a change record is the one a run left in flight"
            },
        };

    // ---- the scan is not vacuous ----------------------------------------------------------

    /// <summary>
    /// Every script all four pages run is in the sweep, `shared/dom.js` and
    /// `shared/check-page.js` included, and each file is scanned once however many pages load
    /// it. A sweep that quietly found nothing would make every assertion below pass for free.
    /// </summary>
    [Fact]
    public void EveryScriptOfAllFourPagesIsScannedOnce()
    {
        IReadOnlyList<KeyValuePair<string, string>> scripts = Scripts();

        foreach (string expected in new[]
                 {
                     "shared/dom.js",
                     "shared/check-page.js",
                     "shared/document.js",
                     "shared/attention.js",
                     "Model/ModelCheckPage/check.js",
                     "Standards/StandardsPage/standards.js",
                     "Review/ReviewPage/app.js",
                     "Review/ReviewPage/render.js",
                     "Remodel/RemodelPage/remodel.js",
                 })
        {
            Assert.Single(scripts, script => script.Key == expected);
        }
    }

    // ---- rule 1: nothing sorts --------------------------------------------------------------

    /// <summary>
    /// `.sort(` and `localeCompare` are what reordering looks like. The ranking arrives in the
    /// order it is to be shown in, from the one place that decided it; a page that re-sorted it
    /// would silently overrule the policy, and a page that sorted anything else would be one
    /// refactor away from sorting this.
    /// </summary>
    [Theory]
    [InlineData(".sort(")]
    [InlineData("localeCompare")]
    public void NoPageScriptReordersAnything(string sink)
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> script in Scripts())
        {
            if (Strip(script.Value).IndexOf(sink, StringComparison.Ordinal) >= 0)
            {
                offences.Add(script.Key);
            }
        }

        Assert.True(
            offences.Count == 0,
            $"These page scripts contain `{sink}`: " + string.Join(", ", offences)
                + Environment.NewLine
                + "A page renders the ranking in the order the backend supplied it "
                + "(contracts/attention.md section 6). Ordering belongs in "
                + "reviewer/src/swreview/report/attention.py, where it can be argued with.");
    }

    // ---- rule 2: no ordered list of finding vocabulary --------------------------------------

    /// <summary>
    /// No array literal holds <see cref="OrderedListSize"/> or more of the words the policy
    /// ranks by, unless it is one of the display orders named in <see cref="AllowedOrders"/>.
    ///
    /// An array literal is an order and an object literal is a map, which is why
    /// `BUCKET_LABELS` - `{failed: 'failed', warned: 'warned', ...}` in `check-page.js` - is
    /// not scanned: it says what each bucket is called, in no order at all.
    /// </summary>
    [Fact]
    public void NoPageScriptSpellsOutAnOrderOverFindingVocabulary()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> script in Scripts())
        {
            foreach (string literal in ArrayLiterals(Strip(script.Value)))
            {
                string[] words = Vocabulary
                    .Where(word => QuotedWords(literal).Contains(word))
                    .OrderBy(word => word, StringComparer.Ordinal)
                    .ToArray();

                if (words.Length < OrderedListSize)
                {
                    continue;
                }

                string key = script.Key + "|" + string.Join(",", words);
                if (!AllowedOrders.ContainsKey(key))
                {
                    offences.Add(key);
                }
            }
        }

        Assert.True(
            offences.Count == 0,
            "These page scripts spell out an order over the words the attention policy ranks "
                + "by:" + Environment.NewLine + string.Join(Environment.NewLine, offences.Distinct())
                + Environment.NewLine
                + "If it is a display order rather than a rank, add it to AllowedOrders with "
                + "the reason. Allowed today: "
                + string.Join("; ", AllowedOrders.Select(entry => entry.Value)));
    }

    // ---- rule 3: no comparison on a severity or a status ------------------------------------

    /// <summary>
    /// No page compares a `severity` or a `status` value - not for order and not for equality -
    /// unless it is one of the bucket and card-state decisions named in
    /// <see cref="AllowedComparisons"/>.
    ///
    /// Equality is scanned as well as ordering because that is how a band rule is actually
    /// written by hand: `severity === 'high' ? 0 : severity === 'medium' ? 1 : 2` is a total
    /// order with no `&lt;` anywhere in it.
    /// </summary>
    [Fact]
    public void NoPageScriptComparesASeverityOrAStatus()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> script in Scripts())
        {
            foreach (Match match in ValueComparison.Matches(Strip(script.Value)))
            {
                string key = script.Key + "|" + Collapse(match.Value);
                if (!AllowedComparisons.ContainsKey(key))
                {
                    offences.Add(key);
                }
            }
        }

        Assert.True(
            offences.Count == 0,
            "These page scripts compare a severity or a status:" + Environment.NewLine
                + string.Join(Environment.NewLine, offences.Distinct())
                + Environment.NewLine
                + "Severity is read and never recomputed (contracts/attention.md section 1). "
                + "If the comparison decides which bucket or card state a row is drawn in "
                + "rather than which row comes first, add it to AllowedComparisons with the "
                + "reason. Allowed today: "
                + string.Join("; ", AllowedComparisons.Select(entry => entry.Value)));
    }

    // ---- rule 4: the panel holds what the backend said, and identifies nothing -------------

    /// <summary>
    /// Feature 011 T092 (T082's identity scan, replaced deliberately). The Review page appends
    /// every coverage item it is sent and drops only what a `coverage.withdrawn` event names, so
    /// `withdrawCoverage` reads the two lists the event's body carries - by the names the chat
    /// events schema gives them - and of each held entry only its item's `check` and its `bucket`,
    /// tested for membership in those lists; never a reason, an error, a scope, a status or a
    /// severity, and no key that would identify one item with another.
    /// </summary>
    [Fact]
    public void TheWithdrawalReadsTheTwoListsTheContractNamesAndNothingThatRanks()
    {
        string app = ReviewScript("app.js");
        string withdraw = FunctionBody(app, "withdrawCoverage");

        string[] lists = WithdrawnBodySchema().GetProperty("properties").EnumerateObject()
            .Select(field => field.Name)
            .ToArray();
        Assert.Equal(new[] { "checks", "buckets" }, lists);
        foreach (string field in lists.Concat(new[] { "check", "bucket" }))
        {
            Assert.True(Word(field).IsMatch(withdraw), "withdrawCoverage does not read '" + field + "'.");
        }

        foreach (string field in new[] { "reason", "error", "scope", "status", "severity" })
        {
            Assert.False(Word(field).IsMatch(withdraw), "withdrawCoverage reads '" + field + "', which the backend did not name.");
        }

        Assert.Contains("indexOf(", withdraw, StringComparison.Ordinal);
        Assert.DoesNotContain("coverageKey", app, StringComparison.Ordinal);
    }

    /// <summary>
    /// And no coverage reaches the panel's state, or leaves it, around those two: the one append
    /// is inside `recordCoverage`, which the live event and a restored snapshot both go through
    /// unchanged, and the one filter is inside `withdrawCoverage`.
    /// </summary>
    [Fact]
    public void EveryCoverageItemReachesThePanelThroughOneAppendAndLeavesThroughTheWithdrawal()
    {
        string app = ReviewScript("app.js");
        string record = FunctionBody(app, "recordCoverage");
        string withdraw = FunctionBody(app, "withdrawCoverage");

        Assert.Equal(1, Occurrences(app, "state.coverage.push("));
        Assert.Contains("state.coverage.push(", record, StringComparison.Ordinal);
        Assert.Equal(1, Occurrences(app, "state.coverage.filter("));
        Assert.Contains("state.coverage.filter(", withdraw, StringComparison.Ordinal);
        Assert.DoesNotContain("snapshot.coverage || []).slice()", app, StringComparison.Ordinal);
    }

    // ---- the allowlists are live ------------------------------------------------------------

    /// <summary>
    /// Every allowlist entry still matches something. An entry for a line that has been deleted
    /// or rewritten is an exemption nobody is using, and the next one written beside it gets
    /// waved through on its neighbour's reputation.
    /// </summary>
    [Fact]
    public void EveryAllowlistEntryStillMatchesAScriptThatIsShipped()
    {
        var found = new HashSet<string>(StringComparer.Ordinal);

        foreach (KeyValuePair<string, string> script in Scripts())
        {
            string source = Strip(script.Value);

            foreach (string literal in ArrayLiterals(source))
            {
                string[] words = Vocabulary
                    .Where(word => QuotedWords(literal).Contains(word))
                    .OrderBy(word => word, StringComparer.Ordinal)
                    .ToArray();
                found.Add(script.Key + "|" + string.Join(",", words));
            }

            foreach (Match match in ValueComparison.Matches(source))
            {
                found.Add(script.Key + "|" + Collapse(match.Value));
            }
        }

        string[] stale = AllowedOrders.Keys.Concat(AllowedComparisons.Keys)
            .Where(key => !found.Contains(key))
            .OrderBy(key => key, StringComparer.Ordinal)
            .ToArray();

        Assert.True(
            stale.Length == 0,
            "These allowlist entries match nothing the pages ship any more; delete them:"
                + Environment.NewLine + string.Join(Environment.NewLine, stale));
    }

    // ---- scanning ------------------------------------------------------------------------------

    /// <summary>
    /// Every script the four pages run, each file once. `PageScripts.Collect` answers "what
    /// does this page load" per page - the page's own folder plus the shared files its own
    /// `index.html` names - and the two check tabs both load `shared/check-page.js`, so the
    /// union is taken by path.
    /// </summary>
    private static IReadOnlyList<KeyValuePair<string, string>> Scripts()
    {
        IEnumerable<KeyValuePair<string, string>> all =
            PageScripts.Collect(ModelCheckPageFiles.Folder, ModelCheckPageFiles.IndexHtml())
                .Concat(PageScripts.Collect(
                    StandardsPageFiles.Folder, StandardsPageFiles.IndexHtml()))
                .Concat(PageScripts.Collect(ReviewPageFiles.Folder, ReviewPageFiles.IndexHtml()))
                .Concat(PageScripts.Collect(RemodelPageFiles.Folder, RemodelPageFiles.IndexHtml()));

        List<KeyValuePair<string, string>> scripts = all
            .GroupBy(script => Normalize(script.Key), StringComparer.Ordinal)
            .Select(group => new KeyValuePair<string, string>(group.Key, group.First().Value))
            .OrderBy(script => script.Key, StringComparer.Ordinal)
            .ToList();

        Assert.True(scripts.Count >= 6, "the page sweep found almost nothing; did a folder move?");
        return scripts;
    }

    /// <summary>The Windows path separator the collector reports, as the contracts write it.</summary>
    private static string Normalize(string path) => path.Replace('\\', '/');

    /// <summary>One of the Review page's own scripts, comments out of the way.</summary>
    private static string ReviewScript(string fileName) =>
        Strip(Scripts().Single(script => script.Key == "Review/ReviewPage/" + fileName).Value);

    /// <summary>
    /// The body of <c>function {name}(...)</c>, from its opening brace to the one that closes it,
    /// quoted text skipped so a brace inside a string neither opens nor closes; the test fails
    /// when the page has no such function, so a scan of it is never vacuous.
    /// </summary>
    private static string FunctionBody(string source, string name)
    {
        int at = source.IndexOf("function " + name + "(", StringComparison.Ordinal);
        Assert.True(at >= 0, "the Review page has no function " + name + ".");

        int open = source.IndexOf('{', at);
        int depth = 0;
        for (int index = open; index >= 0 && index < source.Length; index++)
        {
            char character = source[index];
            if (character == '\'' || character == '"' || character == '`')
            {
                index = EndOfString(source, index);
                continue;
            }

            if (character == '{')
            {
                depth++;
            }
            else if (character == '}' && --depth == 0)
            {
                return source.Substring(open, index - open + 1);
            }
        }

        Assert.Fail("function " + name + " never closes.");
        return string.Empty;
    }

    /// <summary>
    /// The `coverage.withdrawn` body as the chat events schema states it, copied next to the test
    /// assembly (the csproj's Content item, which <see cref="ReviewPageContractTests"/> reads too).
    /// </summary>
    private static JsonElement WithdrawnBodySchema()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "chat-events.schema.json");
        Assert.True(
            File.Exists(path),
            "chat-events.schema.json was not copied next to the test assembly; check the Content item in the csproj.");

        using (JsonDocument schema = JsonDocument.Parse(File.ReadAllText(path)))
        {
            foreach (JsonElement rule in schema.RootElement.GetProperty("allOf").EnumerateArray())
            {
                JsonElement type = rule.GetProperty("if").GetProperty("properties").GetProperty("type");
                if (type.TryGetProperty("const", out JsonElement name) && name.GetString() == "coverage.withdrawn")
                {
                    return rule.GetProperty("then").GetProperty("properties").GetProperty("body").Clone();
                }
            }
        }

        Assert.Fail("chat-events.schema.json has no coverage.withdrawn body.");
        return default;
    }

    /// <summary>The name as a whole word: <c>check</c> in <c>item.check</c>, not in <c>checked</c>.</summary>
    private static Regex Word(string name) => new Regex(@"\b" + Regex.Escape(name) + @"\b", RegexOptions.CultureInvariant);

    private static int Occurrences(string text, string value)
    {
        int count = 0;
        for (int at = text.IndexOf(value, StringComparison.Ordinal);
            at >= 0;
            at = text.IndexOf(value, at + value.Length, StringComparison.Ordinal))
        {
            count++;
        }

        return count;
    }

    /// <summary>
    /// Every array literal in the source, as the text between a `[` and the `]` that closes it.
    /// Quoted text is skipped, so a bracket inside a string never opens or closes one.
    /// A nested array yields its own span as well as being part of its parent's, which only
    /// ever means the same words are reported twice.
    /// </summary>
    private static IEnumerable<string> ArrayLiterals(string source)
    {
        var opened = new Stack<int>();

        for (int at = 0; at < source.Length; at++)
        {
            char character = source[at];

            if (character == '\'' || character == '"' || character == '`')
            {
                at = EndOfString(source, at);
                continue;
            }

            if (character == '[')
            {
                opened.Push(at);
            }
            else if (character == ']' && opened.Count > 0)
            {
                int start = opened.Pop();
                yield return source.Substring(start, at - start + 1);
            }
        }
    }

    /// <summary>The index of the closing quote, or of the last character if the string never ends.</summary>
    private static int EndOfString(string source, int start)
    {
        char quote = source[start];
        for (int at = start + 1; at < source.Length; at++)
        {
            if (source[at] == '\\')
            {
                at++;
                continue;
            }

            if (source[at] == quote)
            {
                return at;
            }
        }

        return source.Length - 1;
    }

    /// <summary>The quoted string literals inside one span.</summary>
    private static ISet<string> QuotedWords(string span) =>
        new HashSet<string>(
            StringLiteral.Matches(span).Cast<Match>()
                .Select(match => match.Groups[1].Success ? match.Groups[1].Value : match.Groups[2].Value),
            StringComparer.Ordinal);

    /// <summary>Runs of whitespace to one space, so a comparison wrapped over two lines has one key.</summary>
    private static string Collapse(string text) => Whitespace.Replace(text.Trim(), " ");

    private static readonly Regex Whitespace = new Regex(@"\s+", RegexOptions.Compiled);

    private static readonly Regex StringLiteral = new Regex(
        @"'([^'\\\r\n]*)'|""([^""\\\r\n]*)""", RegexOptions.Compiled);

    /// <summary>
    /// A comparison with a `severity` or a `status` on either side of it, in the shapes these
    /// pages write: a property read (`row.severity`) or a bare name, against a literal or
    /// another name.
    /// </summary>
    private static readonly Regex ValueComparison = new Regex(
        Subject + Operator + Operand + "|" + Operand + Operator + Subject,
        RegexOptions.Compiled);

    private const string Subject = @"(?:[A-Za-z_$][A-Za-z0-9_$]*\s*\.\s*)?\b(?:severity|status)\b";

    private const string Operator = @"\s*(?:===|!==|==|!=|<=|>=|<|>)\s*";

    private const string Operand = @"(?:'[^'\r\n]*'|""[^""\r\n]*""|[A-Za-z0-9_$.]+)";

    private static readonly Regex BlockComment = new Regex(
        @"/\*.*?\*/", RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex WholeLineComment = new Regex(
        @"^[ \t]*//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    /// <summary>
    /// Comments out of the way before scanning, the same way every other page scan in this
    /// assembly does it: block comments and whole-line `//` comments, and a trailing comment
    /// left alone because stripping it would mean deciding whether the `//` is inside a string
    /// without parsing JavaScript. A trailing comment that spelled out a severity order would
    /// be read as code here, which is the safe direction to be wrong in.
    /// </summary>
    private static string Strip(string source) =>
        WholeLineComment.Replace(BlockComment.Replace(source, " "), string.Empty);
}
