using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Regression for the docked Task Pane geometry reported on 2026-09-20. This uses the browser's
/// 300 by 600 device metrics, a complete ranking, a detailed finding, the long run folder line and
/// the real not-examined warning. The assertion measures the clipped viewport, rather than
/// checking the CSS declarations that happen to implement it.
///
/// U10 changed the premise and not the floor. A Start-here click used to open the finding's
/// fold, and this test measured the fold that click opened. The click now only scrolls the
/// card's head into view (docs/pane-findings-2026-09-20-review-gui.md section 3), so the test
/// follows the row, proves the fold stayed shut, presses the card's own Details - the press an
/// engineer makes - and measures that: the same 80 px floor, the same follow-up box, the same
/// explanation, now inside the fold.
///
/// Feature 009 User Story 5 moved the findings out of the one container they shared with the
/// transcript and into Results (contracts/views.md section 2), so the fold is measured against
/// `#results`, the view that scrolls it. Feature 013 T053 replaced Start here with the grouped
/// findings: the test opens the finding's grouped row - the press that shows its card - proves the
/// card's own fold stayed shut, then presses Details and measures that. The floor is unchanged.
/// Feature 013 T114 labels the explanation: the first line inside the fold is the source word
/// ("AI guidance", `labels.source`), then the backend's text - so this run reads the labels, on the
/// shared <see cref="ReviewPageDriver"/>, which routes them before `init`.
/// </summary>
public sealed class ReviewPageNarrowLayoutTests
{
    private const string ChatId = "chat-narrow";

    private static readonly Lazy<JsonElement> Measured = new Lazy<JsonElement>(Drive);

    [Fact]
    public void TheFirstFindingDetailsHaveAReadableViewportAtTheNarrowPaneSize()
    {
        JsonElement geometry = Measured.Value;

        Assert.True(
            geometry.GetProperty("hiddenAfterRowClick").GetBoolean(),
            "opening the grouped row opened the finding's own fold.");
        Assert.True(
            geometry.GetProperty("detailsVisibleHeight").GetDouble() >= 80,
            "the opened finding details are clipped below a usable height: " + geometry);
        Assert.True(
            geometry.GetProperty("explanationFirstInFold").GetBoolean(),
            "the explanation is not the first line inside the finding's fold.");
        Assert.True(
            geometry.GetProperty("followupInViewport").GetBoolean(),
            "the follow-up control fell outside the 300x600 viewport: " + geometry);
        Assert.True(
            geometry.GetProperty("warningVisible").GetBoolean(),
            "the full not-examined warning is not visible at the narrow pane size.");
        Assert.Contains("cmp:0004 (lightweight)", geometry.GetProperty("warningText").GetString());
        Assert.True(geometry.GetProperty("explanationMatches").GetBoolean(),
            "the finding must show the persisted explanation its grouped row carries, verbatim.");
        Assert.False(geometry.GetProperty("explanationMarkup").GetBoolean(),
            "The explanation must remain text, including hostile markup.");
    }

    /// <summary>
    /// Feature 013 T114 (contracts/sources.md section 4): the explanation is the model's, and says
    /// so - its first part is `labels.source`'s word for the model, then the persisted text; and
    /// the legacy "No model explanation" line is rendered nowhere.
    /// </summary>
    [Fact]
    public void TheExplanationIsLabelledAsTheModelsGuidance()
    {
        JsonElement geometry = Measured.Value;

        Assert.Equal(new[] { "chip source-chip source-model", "explanation-text" }, ReviewPageDriver.Strings(geometry, "explanationParts"));
        Assert.Equal(LabelsSample.SourceModel, geometry.GetProperty("explanationLabel").GetString());
        Assert.DoesNotContain("No model explanation", geometry.GetProperty("resultsText").GetString());
    }

    private static JsonElement Drive()
    {
        JsonElement observed = default;

        ReviewPageDriver.Run(
            driver =>
            {
                driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
                driver.ReviewStarted = press => new Dictionary<string, object?>
                {
                    { "chat_id", ChatId },
                    { "document", new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" } },
                    { "run_dir", @"C:\SwReviewRuns\20260920-184136-small-assembly-very-long-run-folder-name" },
                    {
                        "not_examined", new
                        {
                            sentence = "Not examined: 2 of 4 component instances were not read: "
                                + "DOWEL PIN cmp:0002 (lightweight), DOWEL PIN cmp:0004 "
                                + "(lightweight). Interference, fit and the feature-tree "
                                + "rules cannot see them.",
                            instances = new[]
                            {
                                new { id = "cmp:0002", state = "lightweight" },
                                new { id = "cmp:0004", state = "lightweight" },
                            },
                        }
                    },
                };
            },
            async driver =>
            {
                await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
                await driver.RouteAttention(ChatId, WithExplanation());
                await driver.StartReview();
                await driver.Push(ChatId, 1, "finding", DetailedFinding);
                await driver.Push(ChatId, 2, "session.ended", @"{""ended_at"":""2026-09-20T22:49:11Z""}");
                await driver.Settle();
                observed = await driver.Read(Measure);
            });

        return observed;
    }

    private static readonly string Measure = @"
var row = document.querySelector('#findings-by-type details.type-row[data-finding-id=""F-007""]');
if (!row) { return JSON.stringify({ ok: false, error: 'no grouped row' }); }
var card = row.querySelector('.card.finding[data-finding-id=""F-007""]');
if (!card) { return JSON.stringify({ ok: false, error: 'no finding card in its row' }); }
row.querySelector(':scope > summary').click();
var details = card.querySelector('.details');
var hiddenAfterRowClick = details.hidden;
card.querySelector('[data-action=""expand""]').click();
var results = document.getElementById('results').getBoundingClientRect();
var viewportHeight = window.innerHeight;
var rect = details.getBoundingClientRect();
var top = Math.max(rect.top, results.top, 0);
var bottom = Math.min(rect.bottom, results.bottom, viewportHeight);
var followup = document.getElementById('followup').getBoundingClientRect();
var explanation = card.querySelector('.finding-explanation');
return JSON.stringify({
  ok: true,
  hiddenAfterRowClick: hiddenAfterRowClick,
  explanationFirstInFold: !!details.firstElementChild
    && details.firstElementChild.className === 'finding-explanation',
  detailsVisibleHeight: Math.max(0, bottom - top),
  followupInViewport: followup.top >= 0 && followup.bottom <= viewportHeight,
  warningVisible: !document.getElementById('not-examined').hidden
    && document.getElementById('not-examined').getBoundingClientRect().height > 0,
  warningText: document.getElementById('not-examined').textContent,
  explanationMatches: !!explanation && h.text(explanation, '.explanation-text') === " + JsonSerializer.Serialize(Explanation) + @",
  explanationMarkup: !!document.querySelector('.finding-explanation img'),
  explanationParts: h.children(explanation),
  explanationLabel: h.text(explanation, '.source-chip'),
  resultsText: document.getElementById('results').textContent,
  viewport: [window.innerWidth, viewportHeight]
});";

    /// <summary>The persisted explanation, with markup in it: model text, which stays characters.</summary>
    private const string Explanation = "These faces locate the pin; editing them may break the mate. <img src=x onerror=alert(1)>";

    /// <summary>The sample's ranking with the explanation on F-007's grouped row, where the page reads it.</summary>
    private static string WithExplanation()
    {
        JsonObject ranking = SummarySample.Ranking();
        ranking["groups"]!["groups"]![0]!["rows"]![1]!["explanation"] = Explanation;
        return ranking.ToJsonString();
    }

    private static readonly string DetailedFinding = JsonSerializer.Serialize(new
    {
        id = "F-007",
        check = "interference.static",
        title = "The pin interferes with the bore it is pressed into",
        status = "demonstrated",
        severity = "medium",
        component_ids = new[] { "cmp:0002", "cmp:0003" },
        observed = "A detailed overlap observation that wraps across the narrow pane.",
        requirement = "The dowel must be clear of the bore through the full assembled depth.",
        recommended_action = "Resolve both lightweight pins and rerun interference before accepting this finding.",
        inputs = new[] { "pin face", "bore face", "configuration Default" },
        coverage_limits = new[] { "lightweight components were not read" },
        drawing_locations = new object[0],
        tool_result_ids = new object[0],
        capture_ids = new object[0],
    });
}
