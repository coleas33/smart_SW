using System;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>Only backend-made waiting snapshots; no page-side acceptance summary.</summary>
internal sealed class WaitingReviewFixture
{
    private WaitingReviewFixture(JsonElement root) { Root = root; }

    public JsonElement Root { get; }

    public JsonElement Waiting => Root.GetProperty("waiting");

    public static WaitingReviewFixture Read(string fileName = "review-waiting.json")
    {
        string path = Path.Combine(AppContext.BaseDirectory, "Fixtures", fileName);
        Assert.True(File.Exists(path), fileName + " is missing; run generate_waiting_fixtures.py --write.");
        return new WaitingReviewFixture(JsonDocument.Parse(File.ReadAllText(path)).RootElement.Clone());
    }

    public void Configure(ReviewPageDriver driver)
    {
        JsonElement document = Waiting.GetProperty("document");
        driver.Document = document.Clone();
        driver.SendWhenChecked = false;
        driver.KeySource = "none";
        driver.InitialRoutes.Add(("GET", "/labels", 200, Root.GetProperty("labels").GetRawText()));
        driver.ReviewStarted = press => new
        {
            chat_id = "chat-" + press,
            run_dir = @"C:\Fictional\FICT-run-" + press,
            document = document.Clone(),
            send_when_checked = driver.SendWhenChecked,
        };
        driver.Sessions.Add(new System.Collections.Generic.Dictionary<string, object?>
        {
            { "chat_id", "chat-1" }, { "run_id", Waiting.GetProperty("run_id").GetString() },
            { "run_dir", @"C:\Fictional\FICT-run" },
            { "path", document.GetProperty("path").GetString() },
            { "configuration", document.GetProperty("configuration").GetString() },
            { "started_at", "2026-10-09T12:00:00+00:00" }, { "model_status", "not_sent" },
        });
        driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, Waiting.GetRawText()));
    }

    public async Task Start(ReviewPageDriver driver)
    {
        await driver.RouteAttention("chat-1", Waiting.GetProperty("ranking").GetRawText());
        await driver.Route("GET", "/sessions/chat-1/snapshot", 200, Waiting.GetRawText());
        await driver.StartReview();
        await driver.Push("chat-1", 1, "session.started", "{\"send_when_checked\":false}");
        await driver.Push("chat-1", 2, "session.ended", "{\"ended_at\":\"2026-10-09T12:00:00+00:00\"}");
        await driver.Settle();
    }
}
