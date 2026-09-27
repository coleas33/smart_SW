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
///
/// Feature 013 T053 moved the findings into groups (contracts/grouped-list.md section 5): the scan
/// no longer looks for Start here, a card's title is checked wherever the card stands, and the
/// group headings and the rows' titles are checked against the fixture's own groups, which 013 T056
/// regenerated it with.
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

        Assert.Contains(ReviewFixture.Value.Summary.GetProperty("headline").GetString()!, text);
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
    /// The page prints the backend's title and builds none: every finding card, wherever it stands
    /// - in its row or in the holding list - holds the fixture's `title` for that finding, character
    /// for character, whole where the recorded title was cut at 80; and every card is there once.
    /// </summary>
    [Fact]
    public void EveryCardTitleIsTheBackendsStringVerbatim()
    {
        JsonElement read = Titles.Value;
        ReviewFixture fixture = ReviewFixture.Value;
        Dictionary<string, string> findingTitles = fixture.Findings
            .ToDictionary(finding => finding.GetProperty("id").GetString()!, finding => finding.GetProperty("title").GetString()!);
        string[] cardIds = ReviewPageDriver.Strings(read, "cardIds");

        Assert.Equal(findingTitles.Count, cardIds.Length);
        Assert.Equal(cardIds.Select(id => findingTitles[id]).ToArray(), ReviewPageDriver.Strings(read, "cardTitles"));
        Assert.Contains(findingTitles.Values, title => title.Length > RecordedTitleLength);
        Assert.DoesNotContain(findingTitles.Values, title => title.Contains(Ellipsis));
    }

    /// <summary>
    /// Every grouped row holds the fixture's row title verbatim, in the fixture's order, and every
    /// group heading is the fixture's title and words (contracts/grouped-list.md section 3).
    /// </summary>
    [Fact]
    public void EveryRowTitleAndGroupHeadingIsTheBackendsStringVerbatim()
    {
        JsonElement read = Titles.Value;
        (JsonElement Group, JsonElement[] Rows)[] groups = ReviewFixture.Value.GroupsWithRows();

        Assert.Equal(
            groups.SelectMany(group => group.Rows).Select(row => row.GetProperty("finding_id").GetString()!).ToArray(),
            ReviewPageDriver.Strings(read, "rowIds"));
        Assert.Equal(
            groups.SelectMany(group => group.Rows).Select(row => row.GetProperty("title").GetString()!).ToArray(),
            ReviewPageDriver.Strings(read, "rowTitles"));
        Assert.Equal(
            groups.Select(group => group.Group.GetProperty("title").GetString() + "|" + group.Group.GetProperty("text").GetString()).ToArray(),
            ReviewPageDriver.Strings(read, "groupHeads"));
    }

    /// <summary>
    /// The default view shows the group headings and the one-line rows of every open group -
    /// words, with no check id and no raw token among them (the scans above read the same text).
    /// </summary>
    [Fact]
    public void TheDefaultViewShowsTheGroupHeadingsAndTheRowsOfEveryOpenGroup()
    {
        string text = Visible.Value;
        (JsonElement Group, JsonElement[] Rows)[] groups = ReviewFixture.Value.GroupsWithRows();

        foreach ((JsonElement group, JsonElement[] rows) in groups)
        {
            Assert.Contains(group.GetProperty("title").GetString()!, text);
            if (group.GetProperty("open").GetBoolean())
            {
                Assert.All(rows, row => Assert.Contains(row.GetProperty("title").GetString()!, text));
            }
        }
    }

    /// <summary>
    /// Feature 013 T103 (contracts/sources.md section 2): no chip prints the raw source tokens -
    /// a finding's, a question's or a grouped row's source is the backend's word ("Checked by code",
    /// "AI guidance") or nothing. Read off the chips rather than the whole text, because "model" is
    /// an ordinary word in the fixture's own questions.
    /// </summary>
    [Fact]
    public void NoChipPrintsARawSourceToken()
    {
        string[] chips = ReviewPageDriver.Strings(Titles.Value, "chips");

        Assert.NotEmpty(chips);
        Assert.DoesNotContain("code", chips);
        Assert.DoesNotContain("model", chips);
    }

    /// <summary>
    /// Feature 013 T114 (contracts/sources.md section 4): nothing stands in for a missing
    /// explanation - the legacy "No model explanation was generated" line is rendered nowhere in
    /// Results, not even inside a shut fold, though the committed fixture's rows still carry it
    /// as evidence of the legacy line (`rank()` skips it from 013 T112).
    /// </summary>
    [Fact]
    public void TheLegacyExplanationFallbackIsRenderedNowhere()
    {
        Assert.DoesNotContain("No model explanation", Titles.Value.GetProperty("resultsText").GetString());
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
var results = document.getElementById('results');
var groups = document.getElementById('findings-by-type');
var heads = [];
var groupNodes = groups.querySelectorAll('details.type-group');
for (var g = 0; g < groupNodes.length; g++) {
  heads.push(h.text(groupNodes[g], ':scope > summary .type-group-title') + '|' + h.text(groupNodes[g], ':scope > summary .type-group-text'));
}
return JSON.stringify({
  ok: true,
  cardIds: h.attrs(results, '.card.finding', 'data-finding-id'),
  cardTitles: h.texts(results, '.card.finding h3.title'),
  rowIds: h.attrs(groups, 'details.type-row', 'data-finding-id'),
  rowTitles: h.texts(groups, 'details.type-row > summary .type-row-title'),
  chips: h.texts(results, '.chip'),
  resultsText: results.textContent,
  groupHeads: heads
});";
}
