using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T058 - the US6 acceptance, written after the page and the backend and passing
/// with no further production code: review A is the big-assembly review as the backend produces
/// it (<see cref="ReviewFixture"/>), review B the hand-built <see cref="SummarySample"/> on a pin.
///
/// The Independent Test: the chips name both reviews; choosing A restores A's summary, Start-here
/// rows and finding cards exactly as the live turn rendered them, with one `GET` and no token
/// spent (SC-005); when the backend no longer holds A's chat (a settings save restarted it),
/// choosing A restores it read-only from its run folder with the backend's reason on screen; and
/// a configuration switch to another configuration of A's own document hides A's results.
/// </summary>
public sealed class ReviewPageSessionsAcceptanceTests
{
    private const string PathB = @"C:\parts\pin.sldprt";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    [Fact]
    public void TheChipsNameBothReviews()
    {
        ReviewFixture fixture = ReviewFixture.Value;

        Assert.Equal(
            new[] { Path.GetFileName(fixture.DocumentPath) + " [" + fixture.DocumentConfiguration + "] 21:30", "pin.sldprt [Default] 22:10" },
            ReviewPageDriver.Strings(Scripted.Value.Chips, "chipTexts"));
    }

    /// <summary>Choosing A renders exactly what the live turn rendered, from one GET and nothing else.</summary>
    [Fact]
    public void ChoosingARestoresItsSummaryRowsAndCardsExactly()
    {
        Run run = Scripted.Value;

        JsonElement call = Assert.Single(run.RestoreCalls);
        Assert.Equal("GET /sessions/" + ReviewFixture.ChatId + "/snapshot", call.GetProperty("method").GetString() + " " + call.GetProperty("path").GetString());
        Assert.Equal(run.StartsBeforeRestore, run.StartsAfterRestore);

        Assert.Equal(99, ReviewPageDriver.Strings(run.Live, "cards").Length);
        Assert.Equal(ReviewPageDriver.Strings(run.Live, "cards"), ReviewPageDriver.Strings(run.Restored, "cards"));
        Assert.Equal(ReviewPageDriver.Strings(run.Live, "startHere"), ReviewPageDriver.Strings(run.Restored, "startHere"));
        Assert.Equal(run.Live.GetProperty("summary").GetString(), run.Restored.GetProperty("summary").GetString());
        Assert.StartsWith("99 findings in 18 issues", run.Restored.GetProperty("summary").GetString());
    }

    /// <summary>With A's chat gone, A comes back read-only from its run folder, the reason on screen.</summary>
    [Fact]
    public void WithTheChatGoneARestoresReadOnlyFromItsRunFolder()
    {
        Run run = Scripted.Value;

        Assert.Equal(
            new[] { "GET /sessions/" + ReviewFixture.ChatId + "/snapshot", "GET /reviews/" + ReviewFixture.Value.RunId },
            run.ReadOnlyCalls.Select(call => call.GetProperty("method").GetString() + " " + call.GetProperty("path").GetString()).ToArray());
        Assert.Equal(ReviewPageSessionsTests.ReadOnlyReason, run.ReadOnly.GetProperty("readOnly").GetString());
        Assert.True(run.ReadOnly.GetProperty("followupDisabled").GetBoolean(), "the follow-up is live on a read-only review.");
        Assert.True(run.ReadOnly.GetProperty("decisionsDisabled").GetBoolean(), "a decision is live on a read-only review.");

        // Chosen while B's document is on screen, A is behind the stale line, which disables
        // Open report by the U8 rule; back on A's own document the read-only review keeps it.
        Assert.Equal(ReviewPageSessionsTests.ReadOnlyReason, run.OnA.GetProperty("readOnly").GetString());
        Assert.False(run.OnA.GetProperty("reportDisabled").GetBoolean(), "Open report is off on a read-only review.");
        Assert.True(run.OnA.GetProperty("followupDisabled").GetBoolean(), "the follow-up came back on a read-only review.");
        Assert.Equal(ReviewPageDriver.Strings(run.Live, "cards"), ReviewPageDriver.Strings(run.ReadOnly, "cards"));
        Assert.Equal(run.Live.GetProperty("summary").GetString(), run.ReadOnly.GetProperty("summary").GetString());
    }

    /// <summary>Another configuration of A's own document is another document: A's results hide.</summary>
    [Fact]
    public void AnotherConfigurationOfAsDocumentHidesItsResults()
    {
        Run run = Scripted.Value;

        Assert.True(run.OnA.GetProperty("staleHidden").GetBoolean(), "A was stale on its own document.");
        Assert.True(run.OnA.GetProperty("summaryRendered").GetBoolean(), "A's summary was not on screen on its own document.");
        Assert.False(run.OtherConfiguration.GetProperty("staleHidden").GetBoolean(), "another configuration did not hide A.");
        Assert.False(run.OtherConfiguration.GetProperty("summaryRendered").GetBoolean(), "A's summary stayed on screen.");
        Assert.Contains("[Machined]", run.OtherConfiguration.GetProperty("staleText").GetString());
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static Run Drive()
    {
        var run = new Run();
        ReviewFixture fixture = ReviewFixture.Value;
        Dictionary<string, object?> a = ReviewPageSessionsTests.Item(ReviewFixture.ChatId, fixture.RunId, fixture.DocumentPath, 21, 30);
        a["configuration"] = fixture.DocumentConfiguration;
        a["run_dir"] = fixture.RunDirectory;
        Dictionary<string, object?> b = ReviewPageSessionsTests.Item("chat-2", "20260923-221000-pin-2", PathB, 22, 10);
        object documentB = new { path = PathB, configuration = "Default" };

        ReviewPageDriver.Run(
            driver =>
            {
                fixture.Configure(driver);
                Func<int, object> startedA = driver.ReviewStarted!;
                driver.ReviewStarted = press => press == 1 ? startedA(press) : ReviewPageSessionsTests.Started(b);
            },
            async driver =>
            {
                // Review A, live, to its end.
                driver.Sessions.Add(a);
                await fixture.Review(driver);
                run.Live = await driver.Read(ReadState);

                // Open B and review it.
                await driver.DocumentChanged(documentB);
                driver.Sessions.Add(b);
                await driver.RouteAttention("chat-2", SummarySample.Json());
                await driver.Route("GET", "/sessions/chat-2/snapshot", 200,
                    ReviewPageSessionsTests.Snapshot("20260923-221000-pin-2", PathB, new[] { "F-100" }, "ended", 3, false));
                await driver.StartReview();
                await driver.Push("chat-2", 1, "finding", ReviewPageSessionsTests.Finding("F-100"));
                await driver.EndSession("chat-2");
                run.Chips = await driver.Read(ReadState);

                // Choose A: one GET, no POST, no review.start.
                await driver.ClearCalls();
                run.StartsBeforeRestore = driver.Starts;
                await driver.Read(ReviewPageSessionsTests.Chip(ReviewFixture.ChatId));
                await driver.Settle();
                run.Restored = await driver.Read(ReadState);
                run.RestoreCalls = await driver.Calls();
                run.StartsAfterRestore = driver.Starts;

                // The backend restarted: A's chat is gone, its folder is not.
                await driver.Read(ReviewPageSessionsTests.Chip("chat-2"));
                await driver.Settle();
                await driver.Route("GET", "/sessions/" + ReviewFixture.ChatId + "/snapshot", 404,
                    @"{""error_class"":""UnknownChat"",""message"":""no chat " + ReviewFixture.ChatId + @""",""retryable"":false}");
                await driver.Route("GET", "/reviews/" + fixture.RunId, 200, fixture.SnapshotJson(snapshot =>
                {
                    snapshot["read_only"] = true;
                    snapshot["read_only_reason"] = ReviewPageSessionsTests.ReadOnlyReason;
                    snapshot["chat_state"] = null;
                    snapshot["last_seq"] = null;
                }));
                await driver.ClearCalls();
                await driver.Read(ReviewPageSessionsTests.Chip(ReviewFixture.ChatId));
                await driver.Settle();
                run.ReadOnly = await driver.Read(ReadState);
                run.ReadOnlyCalls = await driver.Calls();

                // A's own document, then another configuration of it.
                await driver.DocumentChanged(fixture.Document);
                run.OnA = await driver.Read(ReadState);
                await driver.DocumentChanged(new { path = fixture.DocumentPath, configuration = "Machined" });
                run.OtherConfiguration = await driver.Read(ReadState);
            });

        return run;
    }

    private const string ReadState = @"
var decisions = document.querySelectorAll('#findings [data-action=""accept""], #findings [data-action=""reject""], #findings [data-action=""defer""], #findings input.note');
var decisionsDisabled = decisions.length > 0;
for (var i = 0; i < decisions.length; i++) { if (!decisions[i].disabled) { decisionsDisabled = false; } }
var readOnly = document.getElementById('read-only');
return JSON.stringify({
  ok: true,
  chipTexts: h.texts(document, '#review-chips [data-action=""review-chip""]'),
  cards: h.attrs(document.getElementById('findings'), '.card.finding', 'data-finding-id'),
  startHere: h.attrs(document.getElementById('attention-panel'), '.attention-row', 'data-finding-id'),
  summary: document.getElementById('summary').textContent,
  summaryRendered: h.rendered(document.getElementById('summary')),
  staleHidden: !!document.getElementById('stale-review').hidden,
  staleText: document.getElementById('stale-review').textContent,
  followupDisabled: document.getElementById('followup-text').disabled,
  reportDisabled: document.getElementById('open-report').disabled,
  decisionsDisabled: decisionsDisabled,
  readOnly: readOnly && !readOnly.hidden ? readOnly.textContent : null
});";

    private sealed class Run
    {
        public JsonElement Live { get; set; }

        public JsonElement Chips { get; set; }

        public int StartsBeforeRestore { get; set; }

        public JsonElement Restored { get; set; }

        public JsonElement[] RestoreCalls { get; set; } = new JsonElement[0];

        public int StartsAfterRestore { get; set; }

        public JsonElement ReadOnly { get; set; }

        public JsonElement[] ReadOnlyCalls { get; set; } = new JsonElement[0];

        public JsonElement OnA { get; set; }

        public JsonElement OtherConfiguration { get; set; }
    }
}
