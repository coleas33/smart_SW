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
/// of the review's findings or coverage, and no error class name. Every id is still one press
/// away, in a fold, the Transcript and the report.
///
/// The fourth check of section 7 - no `cmp:` id of a part the summary names - waits for T062,
/// which puts part names into finding titles: until it lands, six of the fixture's titles name
/// parts by id, as the recording's titles did.
/// </summary>
public sealed class ReviewPageDefaultViewScanTests
{
    private static readonly Lazy<string> Visible = new Lazy<string>(Drive);

    private static readonly Regex CheckIdShape = new Regex(@"^[a-z]+(\.[a-z0-9_]+)+$", RegexOptions.Compiled);

    [Fact]
    public void TheScanReadsTheWholeDefaultView()
    {
        string text = Visible.Value;

        Assert.Contains("99 findings in 18 issues", text);
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
}
