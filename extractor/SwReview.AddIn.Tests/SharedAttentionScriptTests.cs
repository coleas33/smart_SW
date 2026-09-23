using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The Start-here renderer is one script, `web/shared/attention.js`, loaded by the Review page
/// and both check pages (feature 009 increment 3, the analyst's fact 22).
///
/// <b>Why it moved.</b> The stripe map, `amplified`, the ranked row, its meta line, the stripe
/// lookup, the separator and the heading were written twice - once in the Review page's
/// `render.js` and once in `web/shared/check-page.js` - and the two copies had already drifted:
/// one guarded the stripe map against a class that names something on `Object.prototype` and
/// the other did not, and one put the components inside the meta line while the other gave them
/// a span of their own. U10 and U12 both change the rows, so every change would have been made
/// twice. Now each is defined once and both surfaces render the same row.
///
/// <b>What stays where.</b> Each page keeps its own panel - the Review page wraps the rows in a
/// section of its own and adds the count line and "Show all"; a check page appends to the
/// section its `index.html` already has - because those differ. `renderAttention` stays in
/// `check-page.js`, so <see cref="SharedCheckPageTests.SharedFunctions"/> is unchanged: none of
/// the functions it pins moved.
/// </summary>
public sealed class SharedAttentionScriptTests
{
    /// <summary>The Start-here renderer's functions, each defined in `web/shared/attention.js`.</summary>
    public static readonly string[] SharedFunctions =
    {
        "amplified", "rowList", "attentionRow", "attentionMeta", "stripeOf",
    };

    public static IEnumerable<object[]> EverySharedFunction() =>
        SharedFunctions.Select(name => new object[] { name });

    /// <summary>Every page script that shows Start here, or used to hold a copy of it.</summary>
    private static IEnumerable<KeyValuePair<string, string>> PageScripts() => new[]
    {
        new KeyValuePair<string, string>("Review/ReviewPage/render.js", ReviewPageFiles.Read("render.js")),
        new KeyValuePair<string, string>("Review/ReviewPage/app.js", ReviewPageFiles.Read("app.js")),
        new KeyValuePair<string, string>("shared/check-page.js", ReadShared("check-page.js")),
        new KeyValuePair<string, string>("Model/ModelCheckPage/check.js", ModelCheckPageFiles.Read("check.js")),
        new KeyValuePair<string, string>("Standards/StandardsPage/standards.js", StandardsPageFiles.Read("standards.js")),
    };

    [Theory]
    [MemberData(nameof(EverySharedFunction))]
    public void EveryStartHereFunctionIsDefinedInTheSharedScript(string name)
    {
        Assert.True(Defines(SharedScript(), name), $"web/shared/attention.js does not define `{name}`.");
    }

    /// <summary>A move, not a copy: no page script keeps its own version of any of them.</summary>
    [Theory]
    [MemberData(nameof(EverySharedFunction))]
    public void NoPageScriptStillDefinesAStartHereFunction(string name)
    {
        foreach (KeyValuePair<string, string> script in PageScripts())
        {
            Assert.False(
                Defines(script.Value, name),
                $"{script.Key} still defines `{name}`; it lives in web/shared/attention.js now.");
        }
    }

    /// <summary>
    /// The heading, the stripe map and the separator are written once, in the shared script:
    /// not as a second `'Start here'`, a second `'stripe-critical'` or a second middle dot in
    /// the two scripts that used to carry them.
    /// </summary>
    [Theory]
    [InlineData("'Start here'")]
    [InlineData("'stripe-critical'")]
    [InlineData("'stripe-judge'")]
    [InlineData("·")]
    public void TheHeadingTheStripeMapAndTheSeparatorAreWrittenOnlyInTheSharedScript(string literal)
    {
        Assert.Contains(
            literal == "·" ? "\\u00b7" : literal,
            Strip(SharedScript()),
            StringComparison.Ordinal);

        foreach (string name in new[] { "Review/ReviewPage/render.js", "shared/check-page.js" })
        {
            string source = Strip(PageScripts().Single(script => script.Key == name).Value);
            Assert.DoesNotContain(literal, source, StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// Every page that shows Start here loads the shared script after `dom.js`, which it builds
    /// through, and before the script that renders with it.
    /// </summary>
    [Fact]
    public void EveryPageThatShowsStartHereLoadsTheSharedScriptBetweenDomJsAndItsRenderer()
    {
        foreach (KeyValuePair<string, string> page in new[]
                 {
                     new KeyValuePair<string, string>("src=\"render.js\"", ReviewPageFiles.IndexHtml()),
                     new KeyValuePair<string, string>("src=\"../../shared/check-page.js\"", ModelCheckPageFiles.IndexHtml()),
                     new KeyValuePair<string, string>("src=\"../../shared/check-page.js\"", StandardsPageFiles.IndexHtml()),
                 })
        {
            int dom = page.Value.IndexOf("src=\"../../shared/dom.js\"", StringComparison.Ordinal);
            int shared = page.Value.IndexOf("src=\"../../shared/attention.js\"", StringComparison.Ordinal);
            int renderer = page.Value.IndexOf(page.Key, StringComparison.Ordinal);

            Assert.True(shared >= 0, "a page that shows Start here does not load shared/attention.js.");
            Assert.True(dom < shared, "shared/attention.js must load after shared/dom.js.");
            Assert.True(shared < renderer, "shared/attention.js must load before " + page.Key + ".");
        }
    }

    /// <summary>
    /// `dom.js` stays the one place a string becomes a text node: the shared renderer builds
    /// every node through it and reaches no DOM constructor of its own.
    /// </summary>
    [Theory]
    [InlineData("createTextNode")]
    [InlineData("createElement")]
    [InlineData("innerHTML")]
    [InlineData("outerHTML")]
    [InlineData("insertAdjacentHTML")]
    [InlineData(".style.")]
    public void TheSharedScriptReachesNoDomConstructorOfItsOwn(string sink)
    {
        Assert.DoesNotContain(sink, Strip(SharedScript()), StringComparison.Ordinal);
    }

    [Fact]
    public void TheSharedScriptBuildsItsNodesThroughDomJs()
    {
        string shared = Strip(SharedScript());

        Assert.Contains("window.SwReviewDom", shared, StringComparison.Ordinal);
        Assert.Contains("dom.el(", shared, StringComparison.Ordinal);
    }

    /// <summary>
    /// The point of the move, asserted on the rendered pages: the Review tab's Start-here rows
    /// and the Model check tab's are the same markup, built by the same function from the same
    /// ranking - not two renderers someone matched by eye.
    /// </summary>
    [Fact]
    public void TheReviewTabAndTheCheckTabsRenderTheSameStartHereRows()
    {
        JsonElement review = OffscreenReviewPage.Evaluate(
            "var panel = render('attentionPanel', " + AttentionSample.Json() + ");"
            + "var rows = panel.querySelectorAll('.attention-rows .attention-row');"
            + "var out = [];"
            + "for (var i = 0; i < rows.length; i++) { out.push(rows[i].outerHTML); }"
            + "return JSON.stringify({ok: true, rows: out});");

        JsonElement check = OffscreenModelCheckPage.Evaluate(
            "check(" + CheckResultSample.Json() + ");"
            + "var rows = document.querySelectorAll('#attention .attention-rows .attention-row');"
            + "var out = [];"
            + "for (var i = 0; i < rows.length; i++) { out.push(rows[i].outerHTML); }"
            + "return JSON.stringify({ok: true, rows: out});");

        Assert.True(review.GetProperty("ok").GetBoolean(), review.ToString());
        Assert.True(check.GetProperty("ok").GetBoolean(), check.ToString());

        string[] reviewRows = Rows(review);
        Assert.Equal(AttentionSample.ShownFindingIds.Length, reviewRows.Length);
        Assert.Equal(reviewRows, Rows(check));
    }

    // ---- reading the files -----------------------------------------------------------------------

    private static string[] Rows(JsonElement rendered) =>
        rendered.GetProperty("rows").EnumerateArray().Select(value => value.GetString()!).ToArray();

    private static string SharedScript() => ReadShared("attention.js");

    private static string ReadShared(string name)
    {
        string path = Path.Combine(ModelCheckPageFiles.SharedFolder, name);
        Assert.True(File.Exists(path), $"{name} is missing from {ModelCheckPageFiles.SharedFolder}.");
        return File.ReadAllText(path);
    }

    private static bool Defines(string source, string name) =>
        Regex.IsMatch(Strip(source), @"\bfunction\s+" + Regex.Escape(name) + @"\s*\(");

    private static readonly Regex BlockComment = new Regex(
        @"/\*.*?\*/", RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex WholeLineComment = new Regex(
        @"^[ \t]*//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    private static string Strip(string source) =>
        WholeLineComment.Replace(BlockComment.Replace(source, " "), string.Empty);
}
