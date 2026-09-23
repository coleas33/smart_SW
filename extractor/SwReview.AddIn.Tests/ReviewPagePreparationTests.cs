using System;
using System.Text.Json;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

public sealed class ReviewPagePreparationTests
{
    [Theory]
    [InlineData("continue", 1)]
    [InlineData("cancel", 0)]
    [InlineData("document-change", 0)]
    [InlineData("check-again", 1)]
    public void UnreadComponentsAreShownBeforeAnyPaidReview(string action, int expectedStarts)
    {
        int preparations = 0;
        int starts = 0;
        string? startedToken = null;
        bool sawWarning = false;
        bool sawMarkup = false;
        const string hostileName = "<img src=x onerror=alert(1)>pin";

        OffscreenReviewPage.WithPage(page =>
        {
            page.WebMessageReceived += (_, args) =>
            {
                JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                string type = message.GetProperty("type").GetString() ?? "";
                string id = message.TryGetProperty("id", out var value) ? value.GetString() ?? "" : "";
                if (type == "ready")
                {
                    page.PostWebMessageAsJson(Reply("init", id, new
                    {
                        providers = new[] { "openai" }, backend = (object?)null, token = (string?)null,
                        document = new { path = @"C:\parts\bracket.sldasm", configuration = "Default" },
                        review_preparation = true, key_source = "none",
                        settings = new { provider = "openai", model = "test", effort = "high" },
                    }));
                }
                else if (type == "review.prepare")
                {
                    preparations++;
                    page.PostWebMessageAsJson(Reply("review.prepared", id, new
                    {
                        preparation_id = "scope-" + preparations,
                        requires_attention = preparations == 1,
                        unread_count = preparations == 1 ? 2 : 0, component_count = 4, gap_count = 0,
                        instances = new[] { new { instance = hostileName, state = "lightweight" } },
                        omitted_instances = 1,
                    }));
                }
                else if (type == "review.start")
                {
                    starts++;
                    startedToken = message.GetProperty("payload").GetProperty("preparation_id").GetString();
                    page.PostWebMessageAsJson(Reply("review.started", id,
                        new
                        {
                            chat_id = "chat-prepared", run_dir = @"C:\runs\prepared",
                            document = new { path = @"C:\parts\bracket.sldasm", configuration = "Default" },
                        }));
                }
            };
        }, async page =>
        {
            await OffscreenReviewPage.Settled(page);
            await page.ExecuteScriptAsync("document.getElementById('start-review').click()");
            await OffscreenReviewPage.Settled(page);
            Assert.Equal(0, starts);
            sawWarning = await Boolean(page, "!document.getElementById('review-preparation').hidden"
                + " && document.getElementById('preparation-summary').textContent.indexOf('2 of 4') >= 0"
                + " && document.getElementById('preparation-instances').textContent.indexOf('1 additional') >= 0");
            sawMarkup = await Boolean(page, "!!document.querySelector('#review-preparation img')");
            if (action == "document-change")
            {
                page.PostWebMessageAsJson(Reply("document.changed", "", new
                {
                    path = @"C:\parts\other.sldasm", configuration = "Default",
                }));
                await OffscreenReviewPage.Settled(page);
                Assert.True(await Boolean(page, "document.getElementById('review-preparation').hidden"));
                await page.ExecuteScriptAsync("document.getElementById('preparation-continue').click()");
            }
            else
            {
                string button = action == "check-again" ? "check" : action;
                await page.ExecuteScriptAsync("document.getElementById('preparation-" + button + "').click()");
            }
            await OffscreenReviewPage.Settled(page);
        });

        Assert.True(sawWarning);
        Assert.False(sawMarkup, "Component text was interpreted as markup.");
        Assert.Equal(expectedStarts, starts);
        if (expectedStarts > 0) Assert.Equal(action == "check-again" ? "scope-2" : "scope-1", startedToken);
        Assert.Equal(action == "check-again" ? 2 : 1, preparations);
    }

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    private static async Task<bool> Boolean(Microsoft.Web.WebView2.Core.CoreWebView2 page, string expression) =>
        JsonDocument.Parse(await page.ExecuteScriptAsync(expression)).RootElement.GetBoolean();
}
