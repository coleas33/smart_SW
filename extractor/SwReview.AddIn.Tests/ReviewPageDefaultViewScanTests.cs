using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T065 - SC-003's page half (contracts/plain-words.md section 7): the big-assembly
/// review with its labels (<see cref="ReviewFixture"/>), finished, and the visible text of the
/// default Results view read the way an engineer sees it - the contents of shut folds and of
/// hidden elements skipped. The default view is words: no raw status or bucket token, no check id
/// of the review's findings or coverage, no error class name, and no `cmp:` id of a part the
/// summary names. Every id is still one press away, in a fold, the Transcript and the report.
///
/// The fourth check reads the titles a person reads (the owner's decision 2A of 2026-09-23,
/// research R2.28): the backend sends each finding's display title - whole, the parts named -
/// while the recorded title the model read named parts by id in six of the fixture's titles
/// (eight parts). The page builds no title: every title it prints is the fixture's string,
/// verbatim.
/// </summary>
public sealed class ReviewPageDefaultViewScanTests
{
    private static readonly Lazy<string> Visible = new Lazy<string>(Drive);

    private static readonly Lazy<JsonElement> Titles = new Lazy<JsonElement>(DriveTitles);

    private static readonly Regex CheckIdShape = new Regex(@"^[a-z]+(\.[a-z0-9_]+)+$", RegexOptions.Compiled);

    private static readonly Regex PartId = new Regex(@"cmp:[0-9]{4,}", RegexOptions.Compiled);

    /// <summary>The recorded title's cut, never in a title a person reads (FR-027).</summary>
    private const string Ellipsis = "…";

    /// <summary>The recorded title's length limit, which the display title does not have.</summary>
    private const int RecordedTitleLength = 80;

    [Fact]
    public void TheScanReadsTheWholeDefaultView()
    {
        string text = Visible.Value;

        // 96 and 15 since the fixture follows the code: three touching groups are contacts (ReviewFixture).
        Assert.Contains("96 findings in 15 issues", text);
        Assert.Contains("Start here", text);
        Assert.True(text.Length > 2000, "the default view read nearly nothing: " + text.Length + " characters.");
    }

    [Fact]
    public void NoRawStatusOrBucketTokenIsVisible()
    {
        string text = Visible.Value;
        string[] tokens =
        {
            "checked_within_scope", "out_of_scope", "not_reached", "not_applicable", "within_scope", "waiting_engineer",
        };

        AssertNoneVisible(tokens, text);
    }

    [Fact]
    public void NoCheckIdOfTheReviewIsVisible()
    {
        string text = Visible.Value;
        ReviewFixture fixture = ReviewFixture.Value;
        IEnumerable<string> checks = fixture.Findings.Select(finding => finding.GetProperty("check").GetString()!)
            .Concat(fixture.Coverage.Select(row => row.GetProperty("item").GetProperty("check").GetString()!))
            .Where(check => CheckIdShape.IsMatch(check))
            .Distinct();

        AssertNoneVisible(checks, text);
    }

    [Fact]
    public void NoPartIdOfANamedPartIsVisible()
    {
        string text = Visible.Value;
        ReviewFixture fixture = ReviewFixture.Value;
        HashSet<string> named = new HashSet<string>(
            fixture.Summary.GetProperty("component_names").EnumerateObject().Select(entry => entry.Name));
        string[] namedInObserved = fixture.Findings
            .SelectMany(finding => PartId.Matches(finding.GetProperty("observed").GetString()!).Cast<Match>())
            .Select(match => match.Value)
            .Where(named.Contains)
            .Distinct()
            .ToArray();

        Assert.True(
            namedInObserved.Length > 0,
            "no finding of the fixture names a named part by id in its observed text: the scan would prove nothing.");
        AssertNoneVisible(named, text);
    }

    /// <summary>
    /// The page prints the backend's title and builds none: every finding card, every Start-here
    /// row and every line behind "Show all" holds the fixture's `title` for that finding, character
    /// for character - whole, where the recorded title was cut at 80.
    /// </summary>
    [Fact]
    public void EveryTitleIsTheBackendsStringVerbatim()
    {
        JsonElement read = Titles.Value;
        ReviewFixture fixture = ReviewFixture.Value;
        string[] findingTitles = fixture.Findings.Select(finding => finding.GetProperty("title").GetString()!).ToArray();
        Dictionary<string, string> rowTitles = fixture.Root.GetProperty("ranking").GetProperty("rows").EnumerateArray()
            .ToDictionary(row => row.GetProperty("finding_id").GetString()!, row => row.GetProperty("title").GetString()!);
        string[] startIds = ReviewPageDriver.Strings(read, "startIds");
        string[] lineIds = ReviewPageDriver.Strings(read, "lineIds");

        Assert.Equal(findingTitles, ReviewPageDriver.Strings(read, "cardTitles"));
        Assert.Equal(5, startIds.Length);
        Assert.Equal(startIds.Select(id => rowTitles[id]).ToArray(), ReviewPageDriver.Strings(read, "startTitles"));
        Assert.Equal(rowTitles.Count - startIds.Length, lineIds.Length);
        Assert.Equal(lineIds.Select(id => rowTitles[id]).ToArray(), ReviewPageDriver.Strings(read, "lineTitles"));
        Assert.Contains(findingTitles, title => title.Length > RecordedTitleLength);
        Assert.DoesNotContain(findingTitles, title => title.Contains(Ellipsis));
    }

    [Fact]
    public void NoErrorClassNameIsVisible()
    {
        string text = Visible.Value;
        IEnumerable<string> classes = ReviewFixture.Value.Root.GetProperty("labels").GetProperty("errors")
            .EnumerateObject().Select(entry => entry.Name);

        AssertNoneVisible(classes, text);
    }

    private static void AssertNoneVisible(IEnumerable<string> tokens, string text)
    {
        string[] found = tokens.Where(token => WholeWord(token).IsMatch(text)).ToArray();
        Assert.True(found.Length == 0, "visible in the default view: " + string.Join(", ", found));
    }

    private static Regex WholeWord(string token) =>
        new Regex(@"(?<![A-Za-z0-9_.])" + Regex.Escape(token) + @"(?![A-Za-z0-9_])");

    // ---- driving the page ---------------------------------------------------------------------

    private static string Drive()
    {
        string text = string.Empty;
        ReviewFixture fixture = ReviewFixture.Value;

        ReviewPageDriver.Run(
            fixture.Configure,
            async driver =>
            {
                await fixture.Review(driver);
                JsonElement read = await driver.Read(
                    "return JSON.stringify({ok: true, text: h.visibleText(document.getElementById('results'))});");
                text = read.GetProperty("text").GetString() ?? string.Empty;
            });

        return text;
    }

    private static JsonElement DriveTitles()
    {
        JsonElement read = default;
        ReviewFixture fixture = ReviewFixture.Value;

        ReviewPageDriver.Run(
            fixture.Configure,
            async driver =>
            {
                await fixture.Review(driver);
                read = await driver.Read(ReadTitles);
            });

        return read;
    }

    private const string ReadTitles = @"
var findings = document.getElementById('findings');
var panel = document.getElementById('attention-panel');
return JSON.stringify({
  ok: true,
  cardTitles: h.texts(findings, '.card.finding h3.title'),
  startIds: h.attrs(panel, '.attention-row', 'data-finding-id'),
  startTitles: h.texts(panel, '.attention-row .attention-title'),
  lineIds: h.attrs(panel, '.attention-line', 'data-finding-id'),
  lineTitles: h.texts(panel, '.attention-line .line-title')
});";
}
