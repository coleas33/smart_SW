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
    /// The rows in the order the backend supplied them, each naming the finding, the check and
    /// the reason it was placed. <see cref="AttentionSample"/>'s ids run F-007, F-008, F-003,
    /// F-002, F-004 and its checks are not alphabetical, so a page that sorted anything renders
    /// a different list and fails here; the sixth row is beyond `top_n` and must not appear.
    /// </summary>
    [Fact]
    public void TheRankedRowsRenderInTheOrderTheRankingSuppliedThem()
    {
        JsonElement panel = Scripted.Value.FirstEnd;

        Assert.False(panel.GetProperty("hidden").GetBoolean(), "the panel stayed hidden.");
        Assert.Equal(AttentionSample.ShownFindingIds, Strings(panel, "ids"));
        Assert.Equal(AttentionSample.ShownChecks, Strings(panel, "checks"));
        Assert.Equal(AttentionSample.ShownReasons, Strings(panel, "reasons"));
        Assert.Equal(AttentionSample.Heading, panel.GetProperty("heading").GetString());
        Assert.DoesNotContain(AttentionSample.BeyondTopN, panel.GetProperty("text").GetString()!);
    }

    /// <summary>
    /// Pinned above the transcript, which is where it has to be: a panel under a transcript
    /// that has just grown by a whole review is a panel nobody scrolls to (FR-023).
    /// </summary>
    [Fact]
    public void ThePanelIsAboveTheTranscript()
    {
        Assert.True(
            Scripted.Value.FirstEnd.GetProperty("aboveTranscript").GetBoolean(),
            "#attention-panel must come before #transcript in the document.");
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

                // 1. A review that ends normally: the panel appears with the stubbed rows.
                await StartReview(page);
                await EndSession(page, "chat-1");
                run.FirstEnd = await Read(page);

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
            });

        return run;
    }

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

    private static async Task<JsonElement> Read(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync(PanelState);

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
      checks: texts(panel, '.attention-check'),
      reasons: texts(panel, '.attention-reason'),
      lists: panel.querySelectorAll('ol').length,
      injected: panel.querySelectorAll('img,script,iframe,svg,object,embed,link,style').length,
      handlers: handlers,
      aboveTranscript: !!(panel.compareDocumentPosition(transcript)
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

        public JsonElement AfterSecondPress { get; set; }

        public JsonElement AfterStaleAnswer { get; set; }

        public JsonElement EmptyEnd { get; set; }

        public JsonElement HostileEnd { get; set; }

        public JsonElement AfterFailedRead { get; set; }
    }
}
