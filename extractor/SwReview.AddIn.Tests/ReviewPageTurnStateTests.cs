using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T041: the Review page's controls follow the turn, driven through the real page.
///
/// <b>Why this is driven rather than scanned.</b> `ReviewPageContractTests` proves the page
/// speaks the contract's vocabulary and `ReviewPageInjectionTests` proves it renders text as
/// text; neither can say what the page <i>does</i> when the host answers. The rule under test
/// here is one of those: one review at a time. A second `review.start` while the first turn is
/// running throws the first chat away - `resetTranscript` wipes its transcript and findings,
/// `chat_id` and `run_dir` are overwritten, its event stream is closed and its Stop button now
/// points at the new chat - while the first turn keeps running in the backend, unstoppable and
/// unreadable, and a second SOLIDWORKS extraction starts on the application thread on top of
/// the first. Nothing about that is reported to the engineer, so nothing but the button being
/// disabled prevents it. FR-030 gives the engineer Stop for exactly this: end the turn, then
/// start another review.
///
/// The host end is played by the test: `ready` is answered with an `init` that names a
/// document and <b>no backend</b>, which is the state the pane is really in while the backend
/// is starting, and which keeps this test off the network - `openStream` returns at once
/// without a backend or a token, so there is no fetch, no reconnect timer and nothing to flake.
/// `review.start` is answered the way <see cref="Review.ReviewHost"/> answers it, with
/// `review.started {chat_id, run_dir}`.
/// </summary>
public sealed class ReviewPageTurnStateTests
{
    [Fact]
    public void ReviewIsEnabledOnceTheHostNamesADocument()
    {
        PageState state = Drive(startReviews: 0);

        Assert.Equal(0, state.StartsRequested);
        Assert.False(state.StartReviewDisabled, "Review is disabled although a document is open.");
        Assert.True(state.StopDisabled, "Stop is enabled although no turn is running.");
    }

    [Fact]
    public void ReviewStaysDisabledWhileTheTurnItStartedIsStillRunning()
    {
        PageState state = Drive(startReviews: 1);

        Assert.Equal(1, state.StartsRequested);
        Assert.EndsWith("bracket-1", state.RunDir);

        Assert.True(
            state.StartReviewDisabled,
            "The Review button was re-enabled while the turn it started was still running: a "
                + "second press abandons the first chat and starts a second extraction.");

        // The state the button is keyed off, so a failure above says which half is wrong.
        Assert.True(state.TurnRunning, "The page does not believe a turn is running.");
        Assert.False(state.StopDisabled, "Stop is disabled during a running turn (FR-030).");
        Assert.True(state.FollowUpDisabled, "The follow-up box is enabled during a running turn.");
    }

    /// <summary>
    /// A second press must not even be possible; this asserts the consequence rather than the
    /// button property, because a page that disabled the button but left the click handler
    /// reachable another way would still throw the first chat away.
    /// </summary>
    [Fact]
    public void ASecondPressDuringARunningTurnStartsNoSecondReview()
    {
        PageState state = Drive(startReviews: 2);

        Assert.Equal(1, state.StartsRequested);
        Assert.EndsWith("bracket-1", state.RunDir);
    }

    [Fact]
    public void ReviewStartedCarriesTheFullNotExaminedWarningToItsWrappingBlock()
    {
        PageState state = Drive(startReviews: 1);

        Assert.Equal(
            "2 of 4 component instances were not read: DOWEL PIN cmp:0002 (lightweight).",
            state.NotExamined);
        Assert.True(state.WarningBeforeAttention, "the warning must be above Start here.");
        Assert.Equal("anywhere", state.WarningWrap);
    }

    /// <summary>
    /// Loads the page, answers `ready` and `review.start` as the host does, presses Review
    /// <paramref name="startReviews"/> times, and reports what the page looks like afterwards.
    /// </summary>
    private static PageState Drive(int startReviews)
    {
        var starts = 0;
        PageState? observed = null;

        OffscreenReviewPage.WithPage(
            page =>
            {
                page.WebMessageReceived += (sender, args) =>
                {
                    JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                    string type = message.GetProperty("type").GetString() ?? string.Empty;
                    string id = message.GetProperty("id").GetString() ?? string.Empty;

                    if (type == "ready")
                    {
                        page.PostWebMessageAsJson(Reply("init", id, Init()));
                        return;
                    }

                    if (type == "review.start")
                    {
                        starts++;
                        page.PostWebMessageAsJson(Reply(
                            "review.started",
                            id,
                            new Dictionary<string, object?>
                                {
                                    { "chat_id", "chat-" + starts },
                                    { "run_dir", @"C:\SwReviewRuns\20260913-142530-bracket-" + starts },
                                    { "document", new { path = @"C:\parts\bracket.sldasm", configuration = "Default" } },
                                    {
                                        "not_examined", new
                                        {
                                            sentence = "2 of 4 component instances were not read: "
                                                + "DOWEL PIN cmp:0002 (lightweight).",
                                            instances = new[] { new { id = "cmp:0002" } },
                                        }
                                    },
                                }));
                    }
                };
            },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);

                for (int press = 0; press < startReviews; press++)
                {
                    // `click()` rather than a synthesized mouse event: a disabled button ignores
                    // it exactly as it ignores a real press, which is the behaviour under test.
                    await page.ExecuteScriptAsync("document.getElementById('start-review').click()");
                    await OffscreenReviewPage.Settled(page);
                }

                observed = await ReadState(page);
            });

        PageState state = observed ?? throw new InvalidOperationException("the page was never read");
        state.StartsRequested = starts;
        return state;
    }

    private static async Task<PageState> ReadState(CoreWebView2 page)
    {
        // ExecuteScriptAsync hands back the value as JSON, so a script that returns a string
        // arrives as a JSON string holding the JSON the page built.
        string raw = await page.ExecuteScriptAsync(ReadStateScript);
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing about its controls");

        JsonElement fields = JsonDocument.Parse(json).RootElement;
        return new PageState
        {
            StartReviewDisabled = fields.GetProperty("startDisabled").GetBoolean(),
            StopDisabled = fields.GetProperty("stopDisabled").GetBoolean(),
            FollowUpDisabled = fields.GetProperty("followUpDisabled").GetBoolean(),
            RunDir = fields.GetProperty("runDir").GetString(),
            TurnRunning = fields.GetProperty("turnRunning").GetBoolean(),
            NotExamined = fields.GetProperty("notExamined").GetString(),
            WarningBeforeAttention = fields.GetProperty("warningBeforeAttention").GetBoolean(),
            WarningWrap = fields.GetProperty("warningWrap").GetString(),
        };
    }

    /// <summary>
    /// What the page shows, read from the DOM only.
    ///
    /// `app.js` is an IIFE and its `state` object is deliberately not reachable from outside, so
    /// "a turn is running" is read the way the engineer reads it - Stop is enabled and the
    /// follow-up box is not - and the run folder line stands in for the chat, because the page
    /// writes the `run_dir` of whichever session it last started there.
    /// </summary>
    private const string ReadStateScript = @"JSON.stringify({
  startDisabled: document.getElementById('start-review').disabled,
  stopDisabled: document.getElementById('stop-turn').disabled,
  followUpDisabled: document.getElementById('followup-text').disabled,
  runDir: document.getElementById('run-dir').textContent,
  turnRunning: !document.getElementById('stop-turn').disabled,
  notExamined: document.getElementById('not-examined').textContent,
  warningBeforeAttention: !!(document.getElementById('not-examined').compareDocumentPosition(
    document.getElementById('attention-panel')) & Node.DOCUMENT_POSITION_FOLLOWING),
  warningWrap: getComputedStyle(document.getElementById('not-examined')).overflowWrap
})";

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    /// <summary>
    /// The `init` the host sends while the backend is still starting: a document, no backend,
    /// no token (contracts/pane-host-messages.md).
    /// </summary>
    private static object Init() => new
    {
        backend = (object?)null,
        token = (string?)null,
        settings = new
        {
            version = 1,
            provider = "openai",
            model = "gpt-5.1",
            effort = "high",
            base_url = (string?)null,
            gemini_enterprise = (object?)null,
            terminal_cli = "codex",
            python = "uv",
            run_root = @"C:\SwReviewRuns",
        },
        key_source = "settings",
        run_root = @"C:\SwReviewRuns",
        providers = new[] { "openai", "gemini", "fake" },
        document = new { path = @"C:\parts\bracket.sldasm", configuration = "Default" },
    };

    private sealed class PageState
    {
        public bool StartReviewDisabled { get; set; }

        public bool StopDisabled { get; set; }

        public bool FollowUpDisabled { get; set; }

        public string? RunDir { get; set; }

        /// <summary>How many `review.start` messages the host was actually asked for.</summary>
        public int StartsRequested { get; set; }

        public bool TurnRunning { get; set; }

        public string? NotExamined { get; set; }

        public bool WarningBeforeAttention { get; set; }

        public string? WarningWrap { get; set; }

    }
}
