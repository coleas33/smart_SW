using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Regression for the docked Task Pane geometry reported on 2026-09-20. This uses the browser's
/// 300 by 600 device metrics, a complete Start-here ranking, a detailed finding, the long run
/// folder line and the real not-examined warning. The assertion measures the clipped viewport,
/// rather than checking the CSS declarations that happen to implement it.
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
/// `#results`, the view that scrolls it, and the card is found in `#findings`. The floor is
/// unchanged.
/// </summary>
public sealed class ReviewPageNarrowLayoutTests
{
    private const string ChatId = "chat-narrow";

    [Fact]
    public void TheFirstFindingDetailsHaveAReadableViewportAtTheNarrowPaneSize()
    {
        JsonElement geometry = Drive();

        Assert.True(
            geometry.GetProperty("hiddenAfterRowClick").GetBoolean(),
            "following the ranked row opened the finding's fold.");
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
            "Start here and its matching finding must show the same persisted explanation.");
        Assert.False(geometry.GetProperty("explanationMarkup").GetBoolean(),
            "The explanation must remain text, including hostile markup.");
    }

    private static JsonElement Drive()
    {
        JsonElement? observed = null;

        OffscreenReviewPage.WithPage(
            page =>
            {
                page.WebMessageReceived += (sender, args) =>
                {
                    JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                    string type = message.GetProperty("type").GetString() ?? string.Empty;
                    string id = message.TryGetProperty("id", out JsonElement messageId)
                        && messageId.ValueKind == JsonValueKind.String
                            ? messageId.GetString() ?? string.Empty
                            : string.Empty;

                    if (type == "ready")
                    {
                        page.PostWebMessageAsJson(Reply("init", id, Init()));
                    }
                    else if (type == "models.list")
                    {
                        page.PostWebMessageAsJson(Reply(
                            "models", id, new { provider = "openai", models = new object[0] }));
                    }
                    else if (type == "review.start")
                    {
                        page.PostWebMessageAsJson(Reply(
                            "review.started",
                            id,
                            new Dictionary<string, object?>
                            {
                                { "chat_id", ChatId },
                                { "document", new { path = @"C:\parts\bracket.sldasm", configuration = "Default" } },
                                {
                                    "run_dir",
                                    @"C:\SwReviewRuns\20260920-184136-810-11249-very-long-run-folder-name"
                                },
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
                            }));
                    }
                };
            },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);
                await page.CallDevToolsProtocolMethodAsync(
                    "Emulation.setDeviceMetricsOverride",
                    JsonSerializer.Serialize(new
                    {
                        width = 300,
                        height = 600,
                        deviceScaleFactor = 1,
                        mobile = false,
                    }));
                await page.ExecuteScriptAsync(
                    "window.__narrow = {body:" + WithExplanation() + "};"
                        + "window.fetch = function () { return Promise.resolve({ok:true,status:200,"
                        + "text:function () { return Promise.resolve(JSON.stringify(window.__narrow.body)); }}); };0");
                await page.ExecuteScriptAsync("document.getElementById('start-review').click()");
                await OffscreenReviewPage.Settled(page);
                await SseFrames.Push(
                    page,
                    ChatId,
                    SseFrames.Frame(1, "finding", DetailedFinding));
                await SseFrames.Push(
                    page,
                    ChatId,
                    SseFrames.Frame(2, "session.ended", @"{""ended_at"":""2026-09-20T22:49:11Z""}"));
                await OffscreenReviewPage.Settled(page);
                observed = await Measure(page);
            });

        return observed ?? throw new InvalidOperationException("the narrow layout was not measured");
    }

    private static async Task<JsonElement> Measure(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync(@"(function () {
  var row = document.querySelector('#attention-panel .attention-row');
  if (!row) { return JSON.stringify({error:'no attention row'}); }
  var card = document.querySelector('#findings .card.finding[data-finding-id=""F-007""]');
  if (!card) { return JSON.stringify({error:'no finding card'}); }
  row.click();
  var details = card.querySelector('.details');
  var hiddenAfterRowClick = details.hidden;
  card.querySelector('[data-action=""expand""]').click();
  var results = document.getElementById('results').getBoundingClientRect();
  var viewportHeight = window.innerHeight;
  var rect = details.getBoundingClientRect();
  var top = Math.max(rect.top, results.top, 0);
  var bottom = Math.min(rect.bottom, results.bottom, viewportHeight);
  var followup = document.getElementById('followup').getBoundingClientRect();
  return JSON.stringify({
    hiddenAfterRowClick: hiddenAfterRowClick,
    explanationFirstInFold: !!details.firstElementChild
      && details.firstElementChild.className === 'finding-explanation',
    detailsVisibleHeight: Math.max(0, bottom - top),
    followupInViewport: followup.top >= 0 && followup.bottom <= viewportHeight,
    warningVisible: !document.getElementById('not-examined').hidden
      && document.getElementById('not-examined').getBoundingClientRect().height > 0,
    warningText: document.getElementById('not-examined').textContent,
    explanationMatches: !!row.querySelector('.finding-explanation')
      && !!card.querySelector('.finding-explanation')
      && row.querySelector('.finding-explanation').textContent === card.querySelector('.finding-explanation').textContent,
    explanationMarkup: !!document.querySelector('.finding-explanation img'),
    viewport: [window.innerWidth, viewportHeight]
  });
}())");
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("the page returned no geometry");
        JsonElement result = JsonDocument.Parse(json).RootElement.Clone();
        Assert.False(result.TryGetProperty("error", out JsonElement error), error.ToString());
        return result;
    }

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    private static string WithExplanation() => new Regex("\"finding_id\"\\s*:\\s*\"F-007\"")
        .Replace(AttentionSample.Json(), "\"finding_id\":\"F-007\",\"explanation\":"
            + JsonSerializer.Serialize("These faces locate the pin; editing them may break the mate. <img src=x onerror=alert(1)>"), 1);

    private static object Init() => new
    {
        backend = new { port = 51999, origin = "http://127.0.0.1:51999" },
        token = "0FAKEtoken-for-the-page-tests",
        settings = new
        {
            version = 1,
            provider = "openai",
            model = "gpt-5.6",
            effort = "high",
            base_url = (string?)null,
            gemini_enterprise = (object?)null,
            terminal_cli = "codex",
            python = "uv",
            run_root = @"C:\SwReviewRuns",
        },
        key_source = "settings",
        run_root = @"C:\SwReviewRuns",
        providers = new[] { "openai", "gemini" },
        document = new { path = @"C:\parts\bracket.sldasm", configuration = "Default" },
    };

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
