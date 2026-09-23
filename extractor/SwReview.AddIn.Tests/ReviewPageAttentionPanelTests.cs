using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T039: the pinned panel the Review tab shows when a session ends (FR-023, FR-024).
///
/// <b>Why it is driven rather than scanned.</b> The two check tabs are handed the ranking on
/// the body they already hold, so a render test is enough for them. This tab holds nothing: it
/// has to notice that the session ended, ask `GET /sessions/{chat_id}/attention` with its
/// bearer token, and decide whether the answer still belongs to the chat on screen. None of
/// that is visible to a scan, and the one that matters most - the answer that arrives after a
/// second Review press - is a race a scan cannot even name. So this drives the real page in a
/// real WebView2 with the host end of the bridge played by the test, exactly as
/// <see cref="ReviewPageEventStreamTests"/> plays it, and with `window.fetch` stubbed the way
/// <see cref="ModelCheckPageTests"/>' Accept test stubs it.
///
/// <b>The frames are the backend's.</b> The session end is played from
/// `contracts/event-stream.sample.sse` through <see cref="SseFrames"/>, whose bytes the Python
/// producer test pins, so this cannot pass against a frame shape the backend never writes -
/// the failure that let three reviews end unnoticed on the workstation
/// (docs/pane-findings-2026-09-18.md).
///
/// <b>One boot, one scripted conversation.</b> Five reviews are pressed in one page, each
/// ending its session, and every test below reads that one run: a WebView2 with the real page
/// in it costs seconds to start and the script is deterministic. The stub holds its answer
/// only where a test needs it held.
/// </summary>
public sealed class ReviewPageAttentionPanelTests
{
    /// <summary>The scripted run, driven once and read by every test in this class.</summary>
    private static readonly Lazy<Conversation> Scripted = new Lazy<Conversation>(Drive);

    /// <summary>The token the host sends in `init`, which must travel in the header and nowhere else.</summary>
    private const string Token = "0FAKEtoken-for-the-page-tests";

    private const string Origin = "http://127.0.0.1:51999";

    // ---- the fetch ---------------------------------------------------------------------------

    /// <summary>
    /// One authenticated read of the chat that just ended. The path names the chat, the token
    /// is in the `Authorization` header and nowhere in the URL (chat-api.md), and the method is
    /// a `GET` because the route computes the ranking in memory and writes nothing.
    /// </summary>
    [Fact]
    public void TheEndOfASessionReadsTheRankingForThatChatWithTheBearerHeader()
    {
        JsonElement call = Assert.Single(Scripted.Value.FirstEnd.GetProperty("calls").EnumerateArray());

        Assert.Equal("GET", call.GetProperty("method").GetString());
        Assert.Equal(Origin + "/sessions/chat-1/attention", call.GetProperty("url").GetString());
        Assert.Equal("Bearer " + Token, call.GetProperty("authorization").GetString());
    }

    // ---- what it shows -----------------------------------------------------------------------

    /// <summary>
    /// Every row, in the order the backend supplied it. <see cref="AttentionSample"/>'s ids run
    /// F-007, F-008, F-003, F-002, F-004, F-009 and its checks are not alphabetical, so a page
    /// that sorted anything renders a different list and fails here.
    ///
    /// U12 rewrote the second half of this (docs/pane-findings-2026-09-20-review-gui.md section
    /// 5): the sixth row, beyond `top_n`, used to be asserted absent, and on 830-02342 that hid
    /// 94 of 99 findings with no path to them. The first `top_n` rows are still the only ones
    /// under Start here; the rest follow them behind "Show all", in the supplied order, and are
    /// on screen only once that control is opened (contracts/attention.md section 6).
    /// </summary>
    [Fact]
    public void TheRankedRowsRenderInTheOrderTheRankingSuppliedThem()
    {
        JsonElement panel = Scripted.Value.FirstEnd;
        JsonElement expanded = Scripted.Value.FirstEndExpanded;
        string[] everyRow = AttentionSample.ShownFindingIds.Concat(new[] { AttentionSample.BeyondTopN }).ToArray();

        Assert.False(panel.GetProperty("hidden").GetBoolean(), "the panel stayed hidden.");
        Assert.Equal(AttentionSample.ShownFindingIds, Strings(panel, "ids"));
        Assert.Equal(AttentionSample.ShownChecks, Strings(panel, "checks"));
        Assert.Equal(AttentionSample.ShownReasons, Strings(panel, "reasons"));
        Assert.Equal(AttentionSample.Heading, panel.GetProperty("heading").GetString());

        Assert.Equal(new[] { AttentionSample.BeyondTopN }, Strings(panel, "indexIds"));
        Assert.Equal(everyRow, Strings(panel, "allIds"));
        Assert.False(
            panel.GetProperty("beyondRendered").GetBoolean(),
            "the row beyond top_n was on screen before Show all was opened.");

        Assert.True(
            expanded.GetProperty("beyondRendered").GetBoolean(),
            "the row beyond top_n is not on screen after Show all was opened.");
        Assert.Equal(everyRow, Strings(expanded, "allIds"));
        Assert.Equal(AttentionSample.ShownFindingIds, Strings(expanded, "ids"));
    }

    /// <summary>
    /// One count line, from the backend's own numbers, saying which unit each counts: the rows
    /// are issues (`rows.length`; a row can fold several findings of one check) and
    /// `not_amplified.beyond_top_n` counts findings. The sample's sixth row folds three findings,
    /// so a line that took one number for the other prints 6 or 1 where 3 belongs. The control
    /// names both units too.
    /// </summary>
    [Fact]
    public void TheCountLineSaysHowManyIssuesStartHereShowsAndHowManyFindingsAreNotInIt()
    {
        JsonElement panel = Scripted.Value.FirstEnd;

        Assert.Equal(
            "Start here: 5 of " + AttentionSample.IssueCount + " issues · "
                + AttentionSample.BeyondTopNFindings + " findings not in Start here",
            panel.GetProperty("countLine").GetString());
        Assert.Equal(
            "Show all " + AttentionSample.IssueCount + " issues (" + AttentionSample.FindingCount + " findings)",
            panel.GetProperty("moreLabel").GetString());
    }

    /// <summary>
    /// A row behind Show all is a way into the transcript like a Start-here row: the click
    /// scrolls its card's head into view and lights the card, and opens nothing.
    /// </summary>
    [Fact]
    public void ClickingARowBehindShowAllScrollsToItsFindingCard()
    {
        JsonElement clicked = Scripted.Value.AfterIndexClick;

        Assert.False(clicked.GetProperty("headInViewBefore").GetBoolean(), "the head was already in view.");
        Assert.True(clicked.GetProperty("headInViewAfter").GetBoolean(), "the click did not scroll to the card.");
        Assert.True(clicked.GetProperty("flashed").GetBoolean(), "the finding card was not lit.");
        Assert.True(clicked.GetProperty("afterHidden").GetBoolean(), "the click opened the fold.");
    }

    /// <summary>
    /// In Results, after the summary and the questions and before the findings, which is where
    /// it has to be: a panel under a list that has just grown by a whole review is a panel
    /// nobody scrolls to (FR-023).
    ///
    /// Until feature 009 this pinned the panel above the one container that interleaved the
    /// findings with the transcript (`ThePanelIsAboveTheTranscript`). Results and Transcript are
    /// two views now (User Story 5, contracts/views.md section 2), and Start here belongs to
    /// Results: after the summary and the questions (User Stories 3 and 4), before the findings.
    /// </summary>
    [Fact]
    public void ThePanelIsInResultsAfterTheSummaryAndTheQuestions()
    {
        JsonElement panel = Scripted.Value.FirstEnd;

        Assert.True(panel.GetProperty("inResults").GetBoolean(), "#attention-panel is not in #results.");
        Assert.True(panel.GetProperty("afterSummary").GetBoolean(), "#attention-panel must come after #summary.");
        Assert.True(panel.GetProperty("afterQuestions").GetBoolean(), "#attention-panel must come after #questions.");
        Assert.True(panel.GetProperty("beforeFindings").GetBoolean(), "#attention-panel must come before #findings.");
        Assert.False(panel.GetProperty("inTranscript").GetBoolean(), "#attention-panel is in the Transcript view.");
    }

    /// <summary>
    /// A session that ended before its first finding says so in words. The sentence is the
    /// backend's: the page neither composes it nor decides when it applies (FR-024).
    /// </summary>
    [Fact]
    public void ARankingWithNoRowsShowsItsOwnSentenceAndNoList()
    {
        JsonElement panel = Scripted.Value.EmptyEnd;

        Assert.False(panel.GetProperty("hidden").GetBoolean(), "the panel stayed hidden.");
        Assert.Contains(AttentionSample.EmptyReason, panel.GetProperty("text").GetString()!);
        Assert.Empty(Strings(panel, "ids"));
        Assert.Equal(0, panel.GetProperty("lists").GetInt32());
    }

    // ---- the chat it belongs to -----------------------------------------------------------------

    /// <summary>
    /// A second Review press throws the first chat away - `resetTranscript` clears the
    /// transcript, the findings and the coverage - and the panel goes with it. A panel left
    /// standing would be the previous review's five rows over a review that has just started,
    /// which is the most confident wrong thing this page could show.
    /// </summary>
    [Fact]
    public void ASecondReviewPressClearsAndHidesThePanel()
    {
        JsonElement panel = Scripted.Value.AfterSecondPress;

        Assert.True(panel.GetProperty("hidden").GetBoolean(), "the panel was left showing.");
        Assert.Equal(string.Empty, panel.GetProperty("text").GetString());
        Assert.Equal(0, panel.GetProperty("children").GetInt32());
    }

    /// <summary>
    /// The answer to a request made for a chat the page has moved on from is dropped.
    ///
    /// This is the race the guard exists for, and it is not hypothetical: the request is made
    /// at `session.ended` and a second Review press is one click away, so the reply can land
    /// after `resetTranscript` has already cleared the panel for the new chat. Without the
    /// guard the new review would open showing the old review's rows.
    /// </summary>
    [Fact]
    public void AnAnswerThatArrivesAfterTheChatMovedOnIsDiscarded()
    {
        JsonElement panel = Scripted.Value.AfterStaleAnswer;

        Assert.True(panel.GetProperty("hidden").GetBoolean(), "a stale ranking was shown.");
        Assert.Equal(string.Empty, panel.GetProperty("text").GetString());
    }

    // ---- when the read fails ----------------------------------------------------------------

    /// <summary>
    /// A read that fails shows nothing new and breaks nothing else. The ranking is an
    /// amplification of findings that are already in the transcript and in `report.md`; a
    /// banner about it at the moment the engineer is reading an ended session would be noise
    /// about a panel they have not missed. What must not happen is an unhandled rejection that
    /// takes the rest of `endSession` with it, so the session-ended line is asserted too.
    /// </summary>
    [Fact]
    public void AFailedReadLeavesThePanelHiddenAndTheRestOfTheEndIntact()
    {
        JsonElement panel = Scripted.Value.AfterFailedRead;

        Assert.True(panel.GetProperty("hidden").GetBoolean(), "the panel was shown after a failed read.");
        Assert.Equal(string.Empty, panel.GetProperty("text").GetString());
        Assert.Contains("The session ended", panel.GetProperty("transcript").GetString()!);
        Assert.Equal("The session ended.", panel.GetProperty("streamState").GetString());
    }

    // ---- following a row into the transcript ---------------------------------------------------

    /// <summary>
    /// A ranked row is a way into the transcript, not a sentence about one - and it leads to a
    /// headline, not to a paragraph.
    ///
    /// U10 (docs/pane-findings-2026-09-20-review-gui.md section 3) retires what this test used
    /// to pin: the click opened the card's fold, so every ranked row followed left one more
    /// finding open at full length and the next click opened another. Clicking the row now
    /// scrolls the card's head into view - from the top of a transcript long enough that it
    /// was out of view - and lights the card, and the fold stays shut with its button still
    /// reading "Details". Opening it is the engineer's press.
    /// </summary>
    [Fact]
    public void ClickingARankedRowScrollsToItsFindingCardAndFlashesItWithoutOpeningIt()
    {
        JsonElement clicked = Scripted.Value.AfterRowClick;

        Assert.False(
            clicked.GetProperty("headInViewBefore").GetBoolean(),
            "the finding's head was already in view, so the scroll proves nothing.");
        Assert.True(
            clicked.GetProperty("headInViewAfter").GetBoolean(),
            "clicking the ranked row did not scroll the finding's head into view.");
        Assert.True(
            clicked.GetProperty("afterHidden").GetBoolean(),
            "clicking the ranked row opened the finding's fold.");
        Assert.Equal("Details", clicked.GetProperty("toggleLabel").GetString());
        Assert.True(clicked.GetProperty("flashed").GetBoolean(), "the finding card was not lit.");
    }

    /// <summary>
    /// Collapse all closes every finding's fold at once, and every button says so. Beside the
    /// transcript's own toggle, because the fold of one card is the unit an engineer opens and
    /// "put them all back to headlines" is the one move there was no control for.
    /// </summary>
    [Fact]
    public void CollapseAllShutsEveryFindingsFoldAndResetsItsButton()
    {
        JsonElement collapsed = Scripted.Value.AfterCollapseAll;

        Assert.Equal(2, collapsed.GetProperty("openBefore").GetInt32());
        Assert.Equal(0, collapsed.GetProperty("openAfter").GetInt32());
        Assert.True(collapsed.GetProperty("cards").GetInt32() > 2, "too few cards to prove 'all'.");
        Assert.All(
            collapsed.GetProperty("labels").EnumerateArray().Select(label => label.GetString()),
            label => Assert.Equal("Details", label));
        Assert.Equal("Collapse all", collapsed.GetProperty("buttonText").GetString());

        // Until feature 009 Collapse all sat in the transcript's head beside the fold's toggle.
        // The toggle is gone - Results and Transcript are two views - and Collapse all sits in
        // Results over the findings it shuts (contracts/views.md section 2).
        Assert.True(
            collapsed.GetProperty("overTheFindings").GetBoolean(),
            "Collapse all is not in Results over the findings.");
    }

    /// <summary>
    /// A row whose finding is not in the transcript does nothing rather than scrolling
    /// somewhere arbitrary. A ranking is read once the session has ended and the transcript
    /// holds every finding of that session - but a reconnect that missed a `finding` event is
    /// exactly the case where the page must not pretend it knows where to go.
    /// </summary>
    [Fact]
    public void ARankedRowWithNoCardInTheTranscriptDoesNothing()
    {
        JsonElement clicked = Scripted.Value.AfterRowClick;

        Assert.True(
            clicked.GetProperty("strayRowSurvived").GetBoolean(),
            "clicking a ranked row whose finding is not in the transcript threw.");
        Assert.Equal(1, clicked.GetProperty("flashedCards").GetInt32());
    }

    // ---- the renderer ------------------------------------------------------------------------

    /// <summary>
    /// The panel is built by `render.attentionPanel`, exported like every other renderer on
    /// this page, so the security tests can call it directly and `app.js` holds no second copy
    /// of how a ranked row looks.
    /// </summary>
    [Fact]
    public void ThePanelBuilderIsExportedOnTheRenderApi()
    {
        Assert.Equal("function", Scripted.Value.FirstEnd.GetProperty("exported").GetString());
    }

    /// <summary>
    /// A reason line that carries markup reaches the screen as characters. A reason is
    /// assembled out of a check id and a finding's own fields, and a finding's `title` is
    /// written by a language model reading a reviewed assembly (FR-029).
    /// </summary>
    [Fact]
    public void AHostileReasonRendersAsLiteralText()
    {
        JsonElement panel = Scripted.Value.HostileEnd;

        Assert.Contains(AttentionSample.HostileReason, panel.GetProperty("text").GetString()!);
        Assert.Equal(0, panel.GetProperty("injected").GetInt32());
        Assert.Equal(0, panel.GetProperty("handlers").GetInt32());
        Assert.DoesNotContain("<img", panel.GetProperty("html").GetString()!);
    }

    // ---- driving the real page ------------------------------------------------------------------

    /// <summary>
    /// Loads the page, answers `ready`, `models.list` and `review.start` the way the add-in
    /// does - handing out a fresh chat id on each press - stubs `window.fetch`, and then plays
    /// five reviews at it: one that ends normally, one that is replaced by a second press, one
    /// whose answer is held until the page has moved on, one that produced no findings, and one
    /// whose reason line is hostile. The failed read is the sixth.
    /// </summary>
    private static Conversation Drive()
    {
        var run = new Conversation();
        int chats = 0;

        OffscreenReviewPage.WithPage(
            page =>
            {
                page.WebMessageReceived += (sender, args) =>
                {
                    JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                    string type = message.GetProperty("type").GetString() ?? string.Empty;
                    string id = message.TryGetProperty("id", out JsonElement value)
                        && value.ValueKind == JsonValueKind.String
                            ? value.GetString() ?? string.Empty
                            : string.Empty;

                    switch (type)
                    {
                        case "ready":
                            page.PostWebMessageAsJson(Reply("init", id, Init()));
                            return;
                        case "models.list":
                            page.PostWebMessageAsJson(Reply(
                                "models", id, new { provider = "openai", models = new object[0] }));
                            return;
                        case "review.start":
                            chats++;
                            page.PostWebMessageAsJson(Reply(
                                "review.started",
                                id,
                                new Dictionary<string, object?>
                                {
                                    { "chat_id", "chat-" + chats },
                                    { "run_dir", @"C:\SwReviewRuns\20260916-101500-bracket-" + chats },
                                    { "document", new { path = @"C:\parts\bracket.sldasm", configuration = "Default" } },
                                }));
                            return;
                        default:
                            return;
                    }
                };
            },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);
                await page.ExecuteScriptAsync(FetchStub);
                await Body(page, AttentionSample.Json());

                // 1. A review that ends normally: the panel appears with the stubbed rows, and
                //    then Show all is opened.
                await StartReview(page);
                await EndSession(page, "chat-1");
                run.FirstEnd = await Read(page);
                await page.ExecuteScriptAsync(
                    "document.querySelector('#attention-panel .attention-more > summary').click();0");
                run.FirstEndExpanded = await Read(page);

                // 2. A second press throws that chat away, and the panel with it.
                await StartReview(page);
                run.AfterSecondPress = await Read(page);

                // 3. The answer for chat-2 is held until a third press has moved the page on,
                //    then released: it belongs to a transcript that is gone.
                await Hold(page, true);
                await EndSession(page, "chat-2");
                await StartReview(page);
                await Hold(page, false);
                await page.ExecuteScriptAsync("window.__attention.release();0");
                await OffscreenReviewPage.Settled(page);
                run.AfterStaleAnswer = await Read(page);

                // 4. A run that produced no findings: the sentence, and no list.
                await Body(page, AttentionSample.EmptyJson());
                await EndSession(page, "chat-3");
                run.EmptyEnd = await Read(page);

                // 5. A hostile reason line.
                await Body(page, AttentionSample.Json(AttentionSample.HostileReason));
                await StartReview(page);
                await EndSession(page, "chat-4");
                run.HostileEnd = await Read(page);

                // 6. A read that fails.
                await StartReview(page);
                await page.ExecuteScriptAsync("window.__attention.fail = true;0");
                await EndSession(page, "chat-5");
                run.AfterFailedRead = await Read(page);

                // 7. A review whose first ranked row has a card in the transcript, so the row
                //    can be followed into it - and a second row whose finding never arrived, so
                //    the click that goes nowhere goes nowhere quietly. Thirty unranked findings
                //    come first, so the ranked one is far enough down that scrolling to it is
                //    something the click has to do.
                await page.ExecuteScriptAsync("window.__attention.fail = false;0");
                await Body(page, AttentionSample.Json());
                await StartReview(page);
                for (int filler = 0; filler < Fillers; filler++)
                {
                    await SseFrames.Push(page, "chat-6", SseFrames.Frame(filler + 1, "finding", Filler(filler)));
                }

                await SseFrames.Push(page, "chat-6", SseFrames.Frame(Fillers + 1, "finding", BeyondFinding));
                await SseFrames.Push(page, "chat-6", SseFrames.Frame(Fillers + 2, "finding", RankedFinding));
                await OffscreenReviewPage.Settled(page);
                await EndSession(page, "chat-6");
                run.AfterRowClick = await Evaluate(
                    page,
                    RowClick
                        .Replace("@@FOUND@@", AttentionSample.ShownFindingIds[0])
                        .Replace("@@MISSING@@", AttentionSample.ShownFindingIds[1]));
                run.AfterIndexClick = await Evaluate(page, IndexClick.Replace("@@FOUND@@", AttentionSample.BeyondTopN));

                // 8. Two folds opened by their own buttons, then Collapse all.
                run.AfterCollapseAll = await Evaluate(page, CollapseAll);
            });

        return run;
    }

    /// <summary>
    /// The first ranked row's finding, as the stream carries one. Its id is
    /// <see cref="AttentionSample.ShownFindingIds"/>[0], which is what makes the row above it a
    /// link rather than a label; the second row's finding is deliberately never sent.
    /// </summary>
    private const string RankedFinding =
        @"{""id"":""F-007"",""check"":""interference.static"","
        + @"""title"":""The pin interferes with the bore it is pressed into"","
        + @"""status"":""demonstrated"",""severity"":""medium"","
        + @"""component_ids"":[""cmp:0002"",""cmp:0003""],"
        + @"""observed"":""Largest overlap 0.012 mm in configuration Default.""}";

    /// <summary>The finding the row beyond `top_n` stands for, so that row too has a card.</summary>
    private static readonly string BeyondFinding = JsonSerializer.Serialize(new
    {
        id = AttentionSample.BeyondTopN,
        check = "rms.folders.present",
        title = AttentionSample.BeyondTopNTitle,
        status = "suspected",
        severity = "low",
        component_ids = new[] { "cmp:0002" },
        observed = "The 1-Reference folder is missing.",
    });

    /// <summary>How many unranked findings stand in the transcript before the ranked one.</summary>
    private const int Fillers = 30;

    /// <summary>An unranked finding, so the transcript is long; its id is in no ranked row.</summary>
    private static string Filler(int index) => JsonSerializer.Serialize(new
    {
        id = "F-" + (100 + index),
        check = "rms.sketches.fully_defined",
        title = "A sketch is not fully defined",
        status = "demonstrated",
        severity = "low",
        component_ids = new[] { "cmp:0002" },
        observed = "Sketch" + index + " has 2 under-defined entities.",
    });

    private static async Task StartReview(CoreWebView2 page)
    {
        await page.ExecuteScriptAsync("window.__attention.calls = [];0");
        await page.ExecuteScriptAsync("document.getElementById('start-review').click()");
        await OffscreenReviewPage.Settled(page);
    }

    /// <summary>Plays the contract sample's closing pair at the page, for one chat.</summary>
    private static async Task EndSession(CoreWebView2 page, string chatId)
    {
        foreach (string frame in SseFrames.ContractSampleFrames())
        {
            await SseFrames.Push(page, chatId, frame);
        }

        await OffscreenReviewPage.Settled(page);
    }

    private static Task<string> Body(CoreWebView2 page, string json) =>
        page.ExecuteScriptAsync("window.__attention.body = " + json + ";0");

    private static Task<string> Hold(CoreWebView2 page, bool held) =>
        page.ExecuteScriptAsync("window.__attention.hold = " + (held ? "true" : "false") + ";0");

    private static Task<JsonElement> Read(CoreWebView2 page) => Evaluate(page, PanelState);

    /// <summary>
    /// Runs one reporting script in the page and parses what it said. Every script this class
    /// evaluates answers `{ok: true, ...}` or `{ok: false, error}`, so a page that threw says
    /// so here rather than failing an assertion about a missing property three frames away.
    /// </summary>
    private static async Task<JsonElement> Evaluate(CoreWebView2 page, string script)
    {
        string raw = await page.ExecuteScriptAsync(script);

        Assert.False(
            string.IsNullOrEmpty(raw) || raw == "null",
            "The page script threw before it could report: " + (raw ?? "<nothing>"));

        string json = JsonDocument.Parse(raw!).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing: " + raw);
        JsonElement state = JsonDocument.Parse(json).RootElement.Clone();

        Assert.True(
            state.GetProperty("ok").GetBoolean(),
            state.TryGetProperty("error", out JsonElement error)
                ? error.GetString()
                : "the page did not report");
        return state;
    }

    private static string[] Strings(JsonElement state, string name) =>
        state.GetProperty(name).EnumerateArray().Select(value => value.GetString()!).ToArray();

    /// <summary>
    /// The backend, stubbed. It records every call the page makes - the URL, the method and the
    /// `Authorization` header - and answers with whatever the test last put in `body`. `hold`
    /// makes it keep the promise until `release` is called, which is how the stale answer is
    /// driven without a race; `fail` rejects the way an unreachable backend does.
    /// </summary>
    private const string FetchStub = @"
(function () {
  window.__attention = { calls: [], body: null, hold: false, release: null, fail: false };

  window.fetch = function (url, request) {
    var headers = (request && request.headers) || {};
    window.__attention.calls.push({
      url: String(url),
      method: (request && request.method) || 'GET',
      authorization: headers.Authorization || ''
    });

    if (window.__attention.fail) {
      return Promise.reject(new Error('the review backend is not running.'));
    }

    var body = window.__attention.body;
    var answer = {
      ok: true,
      status: 200,
      text: function () { return Promise.resolve(JSON.stringify(body)); }
    };

    if (window.__attention.hold) {
      return new Promise(function (resolve) {
        window.__attention.release = function () { resolve(answer); };
      });
    }

    return Promise.resolve(answer);
  };
}())
";

    /// <summary>What the panel looks like, and what the page asked for to get there.</summary>
    private const string PanelState = @"
(function () {
  function texts(root, selector) {
    var found = root.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
    return out;
  }

  function attrs(root, selector, name) {
    var found = root.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute(name)); }
    return out;
  }

  try {
    var panel = document.getElementById('attention-panel');
    var transcript = document.getElementById('transcript');
    var heading = panel.querySelector('.attention-heading');
    var count = panel.querySelector('.attention-count');
    var more = panel.querySelector('.attention-more > summary');
    var beyond = panel.querySelector('.attention-index [data-finding-id=""" + AttentionSample.BeyondTopN + @"""]');

    var handlers = 0;
    var all = panel.getElementsByTagName('*');
    for (var i = 0; i < all.length; i++) {
      var attributes = all[i].attributes;
      for (var j = 0; j < attributes.length; j++) {
        if (/^on/i.test(attributes[j].name)) { handlers++; }
      }
    }

    return JSON.stringify({
      ok: true,
      hidden: !!panel.hidden,
      text: panel.textContent,
      html: panel.innerHTML,
      children: panel.childNodes.length,
      heading: heading ? heading.textContent : '',
      ids: attrs(panel, '.attention-row', 'data-finding-id'),
      indexIds: attrs(panel, '.attention-index [data-finding-id]', 'data-finding-id'),
      allIds: attrs(panel, '[data-finding-id]', 'data-finding-id'),
      // `checkVisibility` as well as the boxes: a shut <details> skips its content rather than
      // removing it from layout, so a row inside one still reports client rects.
      beyondRendered: !!beyond && beyond.getClientRects().length > 0 && beyond.checkVisibility(),
      countLine: count ? count.textContent : '',
      moreLabel: more ? more.textContent : '',
      checks: texts(panel, '.attention-check'),
      reasons: texts(panel, '.attention-reason'),
      lists: panel.querySelectorAll('ol').length,
      injected: panel.querySelectorAll('img,script,iframe,svg,object,embed,link,style').length,
      handlers: handlers,
      inResults: document.getElementById('results').contains(panel),
      inTranscript: document.getElementById('transcript-view').contains(panel),
      afterSummary: !!(document.getElementById('summary').compareDocumentPosition(panel)
        & Node.DOCUMENT_POSITION_FOLLOWING),
      afterQuestions: !!(document.getElementById('questions').compareDocumentPosition(panel)
        & Node.DOCUMENT_POSITION_FOLLOWING),
      beforeFindings: !!(panel.compareDocumentPosition(document.getElementById('findings'))
        & Node.DOCUMENT_POSITION_FOLLOWING),
      transcript: transcript.textContent,
      streamState: document.getElementById('stream-state').textContent,
      calls: window.__attention.calls,
      exported: typeof (window.SwReviewRender || {}).attentionPanel
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}())
";

    /// <summary>
    /// Clicks two ranked rows and reports what happened: the one whose finding is in the
    /// transcript, and the one whose finding never arrived.
    ///
    /// The click and the reading are one evaluation on purpose. The flash is a class the page
    /// takes off again after a couple of seconds, and a test that clicked in one round trip and
    /// looked in the next would be asserting against that timer rather than against the page.
    /// </summary>
    private const string RowClick = @"
(function () {
  try {
    var rowOf = function (id) {
      return document.querySelector('#attention-panel .attention-row[data-finding-id=""' + id + '""]');
    };

    var found = rowOf('@@FOUND@@');
    var missing = rowOf('@@MISSING@@');
    if (!found) { return JSON.stringify({ ok: false, error: 'no ranked row for @@FOUND@@' }); }
    if (!missing) { return JSON.stringify({ ok: false, error: 'no ranked row for @@MISSING@@' }); }

    var card = document.querySelector(
      '#findings .card.finding[data-finding-id=""@@FOUND@@""]');
    if (!card) { return JSON.stringify({ ok: false, error: 'no finding card for @@FOUND@@' }); }
    if (document.querySelector('#findings .card.finding[data-finding-id=""@@MISSING@@""]')) {
      return JSON.stringify({ ok: false, error: '@@MISSING@@ was in the findings after all' });
    }

    // Results is the scroller the findings live in since feature 009 (User Story 5).
    var results = document.getElementById('results');
    var headInView = function () {
      var head = card.querySelector('.card-head').getBoundingClientRect();
      var view = results.getBoundingClientRect();
      return head.top >= view.top && head.bottom <= view.bottom;
    };

    results.scrollTop = 0;
    var headInViewBefore = headInView();
    found.click();
    var headInViewAfter = headInView();

    var strayRowSurvived = true;
    try { missing.click(); } catch (error) { strayRowSurvived = false; }

    var toggle = card.querySelector('[data-action=""expand""]');
    return JSON.stringify({
      ok: true,
      headInViewBefore: headInViewBefore,
      headInViewAfter: headInViewAfter,
      afterHidden: card.querySelector('.details').hidden,
      toggleLabel: toggle ? toggle.textContent : '',
      flashed: /(^|\s)flash(\s|$)/.test(card.className),
      flashedCards: document.querySelectorAll('#findings .card.flash').length,
      strayRowSurvived: strayRowSurvived
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}())
";

    /// <summary>
    /// Opens Show all, scrolls the transcript to its top, clicks the line for the row beyond
    /// `top_n`, and reports where its card went - in one evaluation, for the flash's sake.
    /// </summary>
    private const string IndexClick = @"
(function () {
  try {
    var more = document.querySelector('#attention-panel .attention-more');
    if (!more) { return JSON.stringify({ ok: false, error: 'no Show all control' }); }
    more.open = true;

    var line = document.querySelector('#attention-panel .attention-index [data-finding-id=""@@FOUND@@""]');
    if (!line) { return JSON.stringify({ ok: false, error: 'no line for @@FOUND@@' }); }
    var card = document.querySelector('#findings .card.finding[data-finding-id=""@@FOUND@@""]');
    if (!card) { return JSON.stringify({ ok: false, error: 'no finding card for @@FOUND@@' }); }

    var results = document.getElementById('results');
    var headInView = function () {
      var head = card.querySelector('.card-head').getBoundingClientRect();
      var view = results.getBoundingClientRect();
      return head.top >= view.top && head.bottom <= view.bottom;
    };

    results.scrollTop = 0;
    var headInViewBefore = headInView();
    line.click();

    return JSON.stringify({
      ok: true,
      headInViewBefore: headInViewBefore,
      headInViewAfter: headInView(),
      flashed: /(^|\s)flash(\s|$)/.test(card.className),
      afterHidden: card.querySelector('.details').hidden
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}())
";

    /// <summary>
    /// Opens two findings' folds with their own Details buttons, presses Collapse all, and
    /// reports every fold and every button afterwards.
    /// </summary>
    private const string CollapseAll = @"
(function () {
  try {
    var cards = document.querySelectorAll('#findings .card.finding');
    if (cards.length < 3) { return JSON.stringify({ ok: false, error: 'too few finding cards' }); }
    cards[0].querySelector('[data-action=""expand""]').click();
    cards[cards.length - 1].querySelector('[data-action=""expand""]').click();

    var open = function () {
      return document.querySelectorAll('#findings .card.finding .details:not([hidden])').length;
    };
    var openBefore = open();

    var button = document.getElementById('collapse-findings');
    button.click();

    var labels = [];
    var toggles = document.querySelectorAll('#findings .card.finding [data-action=""expand""]');
    for (var i = 0; i < toggles.length; i++) { labels.push(toggles[i].textContent); }

    var findings = document.getElementById('findings');
    return JSON.stringify({
      ok: true,
      openBefore: openBefore,
      openAfter: open(),
      cards: cards.length,
      labels: labels,
      buttonText: button.textContent,
      overTheFindings: document.getElementById('results').contains(button)
        && !!(button.compareDocumentPosition(findings) & Node.DOCUMENT_POSITION_FOLLOWING)
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}())
";

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    /// <summary>
    /// The `init` the host sends once the backend is up. A backend and a token are named
    /// because `call` refuses without them, which is the whole point of the header assertion.
    /// </summary>
    private static object Init() => new
    {
        backend = new { port = 51999, origin = Origin },
        token = Token,
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
        providers = new[] { "openai", "gemini" },
        document = new { path = @"C:\parts\bracket.sldasm", configuration = "Default" },
    };

    /// <summary>What the scripted run saw, one snapshot per phase.</summary>
    private sealed class Conversation
    {
        public JsonElement FirstEnd { get; set; }

        public JsonElement FirstEndExpanded { get; set; }

        public JsonElement AfterSecondPress { get; set; }

        public JsonElement AfterStaleAnswer { get; set; }

        public JsonElement EmptyEnd { get; set; }

        public JsonElement HostileEnd { get; set; }

        public JsonElement AfterFailedRead { get; set; }

        public JsonElement AfterRowClick { get; set; }

        public JsonElement AfterIndexClick { get; set; }

        public JsonElement AfterCollapseAll { get; set; }
    }
}
