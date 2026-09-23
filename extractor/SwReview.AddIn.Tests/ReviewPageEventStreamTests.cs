using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The page half of the event stream over the message channel, driven through the real page.
///
/// <b>Why this exists beside the contract scan.</b>
/// <see cref="ReviewPageContractTests.TheEventStreamRowsAreOnTheTablesAndThePageNoLongerReadsTheStreamItself"/>
/// proves the four type names appear in the page source and that the `fetch` reader is gone. It
/// cannot prove that any of it works, and the gap is not theoretical: the round that moved the
/// stream onto this channel also moved the backoff reset into `openStream`, where the reconnect
/// timer undid it on every retry, and that shipped green past every scan the page had. What a
/// scan cannot see is behaviour, so this drives it - the real page, in a real WebView2, with the
/// host end of the bridge played by the test exactly as <see cref="ReviewPageTurnStateTests"/>
/// plays it.
///
/// <b>The frames are the backend's, not the test's.</b> Every frame pushed here has the wire
/// shape `_sse` in chat/server.py writes - `id`, `event`, `data` with the body alone - through
/// <see cref="SseFrames"/>, and the closing pair is read from the contract sample the Python
/// producer test pins byte for byte. This class once fabricated its own frames with a whole
/// envelope inside `data`, and the page's parser, which expected exactly that, stayed green
/// here while three reviews on the workstation ended without the page ever noticing
/// (docs/pane-findings-2026-09-18.md).
///
/// <b>One boot, one scripted conversation.</b> Every assertion below reads the same run. A
/// WebView2 with the real page in it costs seconds to start, the conversation is a single
/// ordered script (open, a keep-alive, frames, a frame for another chat, an unknown type, a
/// usage round, two closures, the contract sample's session end), and splitting it into as
/// many boots would be that many times the wall clock to observe the same facts. The script
/// is deterministic and nothing in it depends on wall-clock time, because
/// <see cref="TimerPatch"/> records the delay the page asked for and fires at once.
/// </summary>
public sealed class ReviewPageEventStreamTests
{
    private const string ChatId = "chat-1";

    /// <summary>The scripted run, driven once and read by every test in this class.</summary>
    private static readonly Lazy<Conversation> Scripted = new Lazy<Conversation>(Drive);

    [Fact]
    public void AStartedReviewOpensTheStreamOverTheChannelRatherThanFetchingIt()
    {
        Conversation run = Scripted.Value;

        JsonElement open = run.Payload("events.open", 0);
        Assert.Equal(ChatId, open.GetProperty("chat_id").GetString());
        Assert.Equal(
            JsonValueKind.Null,
            open.GetProperty("last_event_id").ValueKind);
    }

    /// <summary>
    /// "Streaming." means an event was read, not that bytes arrived. A keep-alive comment is
    /// proof of the socket and nothing else, and a page that said "Streaming." on any frame
    /// looked healthy for three whole reviews in which it understood nothing.
    /// </summary>
    [Fact]
    public void AKeepAliveProvesTheSocketButIsNotStreaming()
    {
        Conversation run = Scripted.Value;

        Assert.NotEqual("Streaming.", run.StreamStateAfterKeepAlive);
        Assert.Equal("Streaming.", run.StreamStateAfterFrames);
    }

    [Fact]
    public void FramesTheHostPushesAreParsedHereAndRenderedInOrder()
    {
        Conversation run = Scripted.Value;

        Assert.Contains("firstsecond", run.TranscriptAfterFrames);
    }

    /// <summary>
    /// A frame for a chat this page is no longer showing belongs to a transcript that is gone.
    /// The host drops frames from a reader it has replaced; this is the other half of the same
    /// rule, for a frame that was already in flight when the page moved on.
    /// </summary>
    [Fact]
    public void AFrameForAnotherChatIsDropped()
    {
        Conversation run = Scripted.Value;

        Assert.DoesNotContain("ghost", run.TranscriptAfterGhostFrame);
        Assert.Equal(run.TranscriptAfterFrames, run.TranscriptAfterGhostFrame);
    }

    /// <summary>
    /// An event type this page has no case for is said once, on screen, and then counted
    /// silently. The envelope mismatch this class was rewritten for made <i>every</i> event an
    /// unknown one, and the page said nothing about any of them.
    /// </summary>
    [Fact]
    public void AnEventOfAnUnknownTypeIsReportedOnceRatherThanDroppedSilently()
    {
        Conversation run = Scripted.Value;

        Assert.Equal(1, Occurrences(run.TranscriptAfterUnknownType, "not.a.type"));
    }

    /// <summary>
    /// The body of a `usage` frame reaches the usage line through the parser, not only through
    /// `render.usageLine` in isolation, which <see cref="ReviewPageUsageLineTests"/> covers.
    /// </summary>
    [Fact]
    public void AUsageFrameReachesTheUsageLine()
    {
        Conversation run = Scripted.Value;

        Assert.Contains("1 round trip", run.UsageLineAfterUsageFrame);
        Assert.DoesNotContain("No model round trips", run.UsageLineAfterUsageFrame);
    }

    /// <summary>
    /// The review opens on Results, and the switch shows the Transcript instead (feature 009
    /// User Story 5, contracts/views.md section 1).
    ///
    /// Until feature 009 this test pinned a transcript that arrived folded and a header that
    /// unfolded it (`TheTranscriptArrivesFoldedAndItsHeaderUnfoldsIt`): one container that
    /// interleaved findings with tool cards and hid the prose with a class. Results and
    /// Transcript are two views now, and each owns the pane in turn: the chosen one is a class on
    /// `body`, the switch says which with `aria-pressed`, and the other view is not displayed.
    /// </summary>
    [Fact]
    public void TheReviewOpensOnResultsAndTheSwitchShowsTheTranscript()
    {
        Conversation run = Scripted.Value;

        Assert.Contains("view-results", run.BodyClassOnResults.Split(' '));
        Assert.DoesNotContain("view-transcript", run.BodyClassOnResults.Split(' '));

        JsonElement switched = run.SwitchedToTranscript;
        Assert.Contains("view-transcript", switched.GetProperty("bodyClass").GetString()!.Split(' '));
        Assert.DoesNotContain("view-results", switched.GetProperty("bodyClass").GetString()!.Split(' '));
        Assert.Equal("true", switched.GetProperty("transcriptPressed").GetString());
        Assert.Equal("false", switched.GetProperty("resultsPressed").GetString());
        Assert.Equal("none", switched.GetProperty("resultsDisplay").GetString());
        Assert.NotEqual("none", switched.GetProperty("transcriptDisplay").GetString());
    }

    /// <summary>
    /// The Transcript's own head counts the calls and the rounds, and says what is running while
    /// it runs - and none of it is in Results, which shows no tool call and no token count
    /// (FR-018).
    ///
    /// The count is what makes a hung review tell itself from a finished one ("I cannot tell a
    /// finished review from a hung one" is the complaint this page already has on record,
    /// docs/pane-findings-2026-09-18.md). The two numbers come from two different events - a
    /// round trip from `usage`, a call from `tool.finished` - so both are watched moving. Until
    /// feature 009 they were the transcript fold's button label; they are the Transcript view's
    /// head now.
    /// </summary>
    [Fact]
    public void TheTranscriptHeaderCountsTheRoundsTheCallsAndWhatIsRunning()
    {
        Conversation run = Scripted.Value;

        Assert.Contains("Transcript", run.TranscriptHeadAfterUsage);
        Assert.Contains("0 tool calls", run.TranscriptHeadAfterUsage);
        Assert.Contains("1 round", run.TranscriptHeadAfterUsage);

        // While the call is in flight the head is where it is visible.
        Assert.Contains("check_rms_part", run.TranscriptHeadWhileToolRuns);
        Assert.Contains("0 tool calls", run.TranscriptHeadWhileToolRuns);

        Assert.Contains("1 tool call", run.TranscriptHeadAfterTool);
        Assert.DoesNotContain("1 tool calls", run.TranscriptHeadAfterTool);
        Assert.DoesNotContain("check_rms_part", run.TranscriptHeadAfterTool);

        // ...and not in Results, in either state.
        foreach (string results in new[] { run.ResultsWhileToolRuns, run.ResultsAfterTool })
        {
            Assert.DoesNotContain("check_rms_part", results);
            Assert.DoesNotContain("tool call", results);
            Assert.DoesNotContain("1 round", results);
            Assert.DoesNotContain("round trip", results);
        }
    }

    /// <summary>
    /// `events.closed` reopens from the highest `seq` the page actually read, which is what
    /// stops a reconnect replaying the whole transcript on screen. The unknown-type frames
    /// count - they were read - and the frame for another chat does not.
    /// </summary>
    [Fact]
    public void AClosedStreamIsReopenedFromTheHighestSeqThePageRead()
    {
        Conversation run = Scripted.Value;

        JsonElement reopened = run.Payload("events.open", 1);
        Assert.Equal(ChatId, reopened.GetProperty("chat_id").GetString());
        Assert.Equal("16", reopened.GetProperty("last_event_id").GetString());
    }

    /// <summary>
    /// The regression this class was written for. Two closures with no frame in between are two
    /// attempts that never connected, so the second waits longer than the first. A reset in
    /// `openStream` - which is precisely what the reconnect timer calls - pins the delay at
    /// `RECONNECT_MIN` forever, and a backend that is down is then reopened once a second for
    /// the life of the pane: one `events.open`, one `HttpWebRequest` and one thread per second.
    /// </summary>
    [Fact]
    public void TheReconnectBackoffGrowsWhileNothingConnects()
    {
        Conversation run = Scripted.Value;

        Assert.Equal(new[] { 1000, 2000 }, run.Delays);
    }

    /// <summary>
    /// The bug of 2026-09-18, against the backend's own bytes: the closing `turn.ended` /
    /// `session.ended` pair from the contract sample ends the session on screen and hands the
    /// controls back - Review enabled, Stop disabled, the follow-up box open. Before the fix
    /// the pane showed "Streaming." and "No model round trips yet" after every finished review,
    /// Review stayed disabled, and the only way to start another was to restart SOLIDWORKS.
    /// </summary>
    [Fact]
    public void TheContractSampleEndsTheSessionAndReleasesTheControls()
    {
        Conversation run = Scripted.Value;

        Assert.Contains("The session ended at 2026-09-16T10:20:00", run.TranscriptAfterSessionEnded);
        Assert.Equal("The session ended.", run.StreamStateAfterSessionEnded);

        JsonElement controls = run.ControlsAfterSessionEnded;
        Assert.False(controls.GetProperty("startDisabled").GetBoolean(), "Review stayed disabled after the session ended.");
        Assert.True(controls.GetProperty("stopDisabled").GetBoolean(), "Stop stayed enabled after the session ended.");
        Assert.False(controls.GetProperty("followUpDisabled").GetBoolean(), "The follow-up box stayed disabled after the session ended.");
    }

    /// <summary>
    /// The session ended: nothing further will be streamed, so the page gives the reader up
    /// rather than leaving a socket and a thread open in the host for a transcript that is done.
    /// </summary>
    [Fact]
    public void TheSessionEndingGivesTheReaderUpOverTheChannel()
    {
        Conversation run = Scripted.Value;

        Assert.Equal(1, run.Count("events.close"));
    }

    /// <summary>
    /// A follow-up's answer is pinned in Results under the question that produced it, and the
    /// view does not change (FR-019, the owner's decision of 2026-09-23, contracts/views.md
    /// section 4).
    ///
    /// Until feature 009 this test pinned the opposite move
    /// (`AFollowUpUnfoldsTheTranscriptSoItsAssistantAnswerIsVisible`): the follow-up unfolded the
    /// whole transcript so the answer would not be hidden behind tool chrome. The answer is
    /// pinned in Results now - the engineer never has to switch to read it - and the same text
    /// is also a prose block in the Transcript, where the chronology keeps it.
    /// </summary>
    [Fact]
    public void AFollowUpAnswerIsPinnedInResultsWithoutSwitching()
    {
        Conversation run = Scripted.Value;
        JsonElement pinned = run.PinnedAfterFollowup;

        Assert.Contains("view-results", pinned.GetProperty("bodyClass").GetString()!.Split(' '));
        Assert.Equal("What does this mean?", pinned.GetProperty("question").GetString());
        Assert.Equal("The answer is visible.", pinned.GetProperty("answer").GetString());
        Assert.True(pinned.GetProperty("rendered").GetBoolean(), "the pinned answer is not on screen in Results.");
        Assert.True(pinned.GetProperty("inTranscript").GetBoolean(), "the answer is not a prose block in the Transcript.");
    }

    /// <summary>
    /// Loads the page, answers `ready`, `models.list` and `review.start` the way the add-in
    /// does, presses Review, and then plays the host's side of the stream at the page.
    /// </summary>
    private static Conversation Drive()
    {
        var posted = new List<Posted>();
        var run = new Conversation(posted);

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

                    lock (posted)
                    {
                        posted.Add(new Posted(type, message.GetProperty("payload").Clone()));
                    }

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
                            page.PostWebMessageAsJson(Reply(
                                "review.started",
                                id,
                                new Dictionary<string, object?>
                                {
                                    { "chat_id", ChatId },
                                    { "run_dir", @"C:\SwReviewRuns\20260916-101500-bracket-1" },
                                    { "document", new { path = @"C:\parts\bracket.sldasm", configuration = "Default" } },
                                }));
                            return;
                        default:
                            // `events.open` and `events.close` are answered with nothing, which
                            // is what the host does: the page is waiting for frames, not for an
                            // acknowledgement (contracts/pane-host-messages.md).
                            return;
                    }
                };
            },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);
                await page.ExecuteScriptAsync(TimerPatch);

                await page.ExecuteScriptAsync("document.getElementById('start-review').click()");
                await OffscreenReviewPage.Settled(page);

                await Push(page, SseFrames.KeepAlive);
                await OffscreenReviewPage.Settled(page);
                run.StreamStateAfterKeepAlive = await TextOf(page, "stream-state");

                await Push(page, SseFrames.Frame(7, "text.delta", @"{""text"":""first""}"));
                await Push(page, SseFrames.Frame(12, "text.delta", @"{""text"":""second""}"));
                await OffscreenReviewPage.Settled(page);
                run.TranscriptAfterFrames = await TextOf(page, "transcript");
                run.StreamStateAfterFrames = await TextOf(page, "stream-state");

                await Push(page, SseFrames.Frame(99, "text.delta", @"{""text"":""ghost""}"), "chat-9");
                await OffscreenReviewPage.Settled(page);
                run.TranscriptAfterGhostFrame = await TextOf(page, "transcript");

                await Push(page, SseFrames.Frame(14, "not.a.type", @"{""text"":""unknown""}"));
                await Push(page, SseFrames.Frame(15, "not.a.type", @"{""text"":""unknown again""}"));
                await OffscreenReviewPage.Settled(page);
                run.TranscriptAfterUnknownType = await TextOf(page, "transcript");

                await Push(page, SseFrames.Frame(16, "usage", UsageBody));
                await OffscreenReviewPage.Settled(page);
                run.UsageLineAfterUsageFrame = await TextOf(page, "usage-line");
                run.TranscriptHeadAfterUsage = await TextOf(page, "transcript-head");

                // One tool call, started and finished, so the Transcript's head can be watched
                // moving. Their `seq` is below the highest already read, so the reconnect
                // assertion above still sees 16 as the high-water mark: the page appends in
                // arrival order and only ever raises `lastSeq`.
                await Push(page, SseFrames.Frame(8, "tool.started", ToolStarted));
                await OffscreenReviewPage.Settled(page);
                run.TranscriptHeadWhileToolRuns = await TextOf(page, "transcript-head");
                run.ResultsWhileToolRuns = await TextOf(page, "results");

                await Push(page, SseFrames.Frame(9, "tool.finished", ToolFinished));
                await OffscreenReviewPage.Settled(page);
                run.TranscriptHeadAfterTool = await TextOf(page, "transcript-head");
                run.ResultsAfterTool = await TextOf(page, "results");
                run.BodyClassOnResults = await BodyClass(page);

                await page.ExecuteScriptAsync("document.getElementById('view-transcript').click()");
                await OffscreenReviewPage.Settled(page);
                run.SwitchedToTranscript = await ViewState(page);

                await Closed(page);
                await OffscreenReviewPage.Settled(page);
                await Closed(page);
                await OffscreenReviewPage.Settled(page);

                foreach (string frame in SseFrames.ContractSampleFrames())
                {
                    await Push(page, frame);
                }

                await OffscreenReviewPage.Settled(page);
                run.TranscriptAfterSessionEnded = await TextOf(page, "transcript");
                run.StreamStateAfterSessionEnded = await TextOf(page, "stream-state");
                run.ControlsAfterSessionEnded = await Controls(page);

                // Back to Results, then ask a follow-up. Its answer must be pinned there, with
                // the view left alone.
                await page.ExecuteScriptAsync(FollowupFetchStub);
                await page.ExecuteScriptAsync(
                    "document.getElementById('view-results').click();"
                        + "var input = document.getElementById('followup-text');"
                        + "input.value = 'What does this mean?';"
                        + "document.getElementById('followup').dispatchEvent(new Event('submit', {cancelable:true}));0");
                await OffscreenReviewPage.Settled(page);
                await Push(page, SseFrames.Frame(200, "text.done", @"{""text"":""The answer is visible.""}"));
                await OffscreenReviewPage.Settled(page);
                run.PinnedAfterFollowup = await Pinned(page);

                run.Delays = await Delays(page);
            });

        return run;
    }

    /// <summary>
    /// One model round trip, every field the `usage` event carries
    /// (specs/005-llm-efficiency/contracts/usage.md section 5).
    /// </summary>
    private const string UsageBody =
        @"{""round_index"":0,""provider"":""openai"",""model"":""gpt-5.6"",""input_tokens"":10,"
        + @"""cached_input_tokens"":5,""cache_write_tokens"":null,""output_tokens"":8,"
        + @"""reasoning_tokens"":4,""tool_result_input_tokens"":null,""total_tokens"":18,"
        + @"""latency_s"":1.5,""cache_diagnostic"":null}";

    /// <summary>One tool call, as `tool.started` and then `tool.finished` carry it.</summary>
    private const string ToolStarted =
        @"{""step_index"":1,""tool"":""check_rms_part"",""arguments"":{""component_id"":""cmp:0003""}}";

    private const string ToolFinished =
        @"{""step_index"":1,""status"":""ok"",""result_summary"":""3 findings, 11 skipped"","
        + @"""elapsed_s"":0.14}";

    private static Task<string> Push(CoreWebView2 page, string frame, string chatId = ChatId) =>
        SseFrames.Push(page, chatId, frame);

    private static Task<string> Closed(CoreWebView2 page)
    {
        page.PostWebMessageAsJson(JsonSerializer.Serialize(new
        {
            type = "events.closed",
            id = (string?)null,
            payload = new { chat_id = ChatId, reason = "the backend closed the event stream." },
        }));
        return page.ExecuteScriptAsync("0");
    }

    /// <summary>The last pinned answer in Results, the view, and whether the answer is also in the Transcript.</summary>
    private static Task<JsonElement> Pinned(CoreWebView2 page) => Json(page, @"(function () {
  var pins = document.querySelectorAll('#answers .pinned');
  var pin = pins.length ? pins[pins.length - 1] : null;
  var blocks = document.querySelectorAll('#transcript .block.assistant');
  var inTranscript = false;
  for (var i = 0; i < blocks.length; i++) {
    if (blocks[i].textContent.indexOf('The answer is visible.') >= 0) { inTranscript = true; }
  }
  return JSON.stringify({
    bodyClass: document.body.className,
    question: pin ? pin.querySelector('.pinned-question').textContent : null,
    answer: pin ? pin.querySelector('.pinned-answer').textContent : null,
    rendered: !!pin && pin.getClientRects().length > 0 && pin.checkVisibility(),
    inTranscript: inTranscript
  });
}())");

    /// <summary>What the switch and the two views say after the Transcript button is pressed.</summary>
    private static Task<JsonElement> ViewState(CoreWebView2 page) => Json(page, @"JSON.stringify({
  bodyClass: document.body.className,
  transcriptPressed: document.getElementById('view-transcript').getAttribute('aria-pressed'),
  resultsPressed: document.getElementById('view-results').getAttribute('aria-pressed'),
  resultsDisplay: getComputedStyle(document.getElementById('results')).display,
  transcriptDisplay: getComputedStyle(document.getElementById('transcript-view')).display
})");

    private static async Task<JsonElement> Json(CoreWebView2 page, string script)
    {
        string raw = await page.ExecuteScriptAsync(script);
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing: " + raw);
        return JsonDocument.Parse(json).RootElement.Clone();
    }

    private static async Task<string> TextOf(CoreWebView2 page, string elementId)
    {
        string raw = await page.ExecuteScriptAsync(
            "document.getElementById('" + elementId + "').textContent");
        return JsonDocument.Parse(raw).RootElement.GetString() ?? string.Empty;
    }

    private static async Task<string> BodyClass(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync("document.body.className");
        return JsonDocument.Parse(raw).RootElement.GetString() ?? string.Empty;
    }

    /// <summary>The three controls the turn owns, read from the DOM the way the engineer reads them.</summary>
    private static async Task<JsonElement> Controls(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync(@"JSON.stringify({
  startDisabled: document.getElementById('start-review').disabled,
  stopDisabled: document.getElementById('stop-turn').disabled,
  followUpDisabled: document.getElementById('followup-text').disabled
})");
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing about its controls");
        return JsonDocument.Parse(json).RootElement.Clone();
    }

    private static async Task<IReadOnlyList<int>> Delays(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync("JSON.stringify(window.__swreviewDelays)");
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("the timer patch recorded nothing");
        return JsonDocument.Parse(json).RootElement.EnumerateArray()
            .Select(value => value.GetInt32())
            .ToList();
    }

    private static int Occurrences(string text, string needle)
    {
        int count = 0;
        for (int at = text.IndexOf(needle, StringComparison.Ordinal);
             at >= 0;
             at = text.IndexOf(needle, at + needle.Length, StringComparison.Ordinal))
        {
            count++;
        }

        return count;
    }

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    /// <summary>
    /// Records the delay the page asks for and fires the callback at once.
    ///
    /// The assertion is the number, not the wait: letting the real backoff elapse would put
    /// three seconds of wall clock into the test to observe two integers, and would make it a
    /// timing test rather than a behaviour one. `app.js` looks `window.setTimeout` up when it
    /// schedules, so patching it after the page has loaded is enough - and the page's only
    /// `setTimeout` is the reconnect timer, so nothing else lands in the list.
    /// </summary>
    private const string TimerPatch = @"
(function () {
  window.__swreviewDelays = [];
  var real = window.setTimeout;
  window.setTimeout = function (fn, delay) {
    window.__swreviewDelays.push(delay);
    return real.call(window, fn, 0);
  };
}())";

    private const string FollowupFetchStub = @"
(function () {
  window.fetch = function () {
    return Promise.resolve({
      ok: true,
      status: 200,
      text: function () { return Promise.resolve('{}'); }
    });
  };
}())";

    /// <summary>
    /// The `init` the host sends once the backend is up: a document, a backend and a token
    /// (contracts/pane-host-messages.md). A backend is named because `scheduleReconnect` will
    /// not reopen a stream for a page that has none - which is the state
    /// <see cref="ReviewPageTurnStateTests"/> drives, and the reason that test sees no stream at
    /// all. No call is made to it: everything this page does with the backend goes through
    /// `models.list` on this channel or through the stream.
    /// </summary>
    private static object Init() => new
    {
        backend = new { port = 51999, origin = "http://127.0.0.1:51999" },
        token = "0FAKEtoken-for-the-page-tests",
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

    /// <summary>One message the page posted to the host.</summary>
    private sealed class Posted
    {
        public Posted(string type, JsonElement payload)
        {
            Type = type;
            Payload = payload;
        }

        public string Type { get; }

        public JsonElement Payload { get; }
    }

    /// <summary>What the scripted run saw.</summary>
    private sealed class Conversation
    {
        private readonly List<Posted> _posted;

        public Conversation(List<Posted> posted) => _posted = posted;

        public string StreamStateAfterKeepAlive { get; set; } = string.Empty;

        public string TranscriptAfterFrames { get; set; } = string.Empty;

        public string StreamStateAfterFrames { get; set; } = string.Empty;

        public string TranscriptAfterGhostFrame { get; set; } = string.Empty;

        public string TranscriptAfterUnknownType { get; set; } = string.Empty;

        public string UsageLineAfterUsageFrame { get; set; } = string.Empty;

        public string TranscriptHeadAfterUsage { get; set; } = string.Empty;

        public string TranscriptHeadWhileToolRuns { get; set; } = string.Empty;

        public string TranscriptHeadAfterTool { get; set; } = string.Empty;

        public string ResultsWhileToolRuns { get; set; } = string.Empty;

        public string ResultsAfterTool { get; set; } = string.Empty;

        public string BodyClassOnResults { get; set; } = string.Empty;

        public JsonElement SwitchedToTranscript { get; set; }

        public string TranscriptAfterSessionEnded { get; set; } = string.Empty;

        public string StreamStateAfterSessionEnded { get; set; } = string.Empty;

        public JsonElement ControlsAfterSessionEnded { get; set; }

        public JsonElement PinnedAfterFollowup { get; set; }

        public IReadOnlyList<int> Delays { get; set; } = new int[0];

        public int Count(string type) => Snapshot().Count(message => message.Type == type);

        /// <summary>The payload of the nth message of this type, in the order the page sent them.</summary>
        public JsonElement Payload(string type, int index)
        {
            List<Posted> matching = Snapshot().Where(message => message.Type == type).ToList();
            Assert.True(
                matching.Count > index,
                $"the page posted {matching.Count} '{type}' messages, not {index + 1}; it posted: "
                    + string.Join(", ", Snapshot().Select(message => message.Type)));
            return matching[index].Payload;
        }

        private List<Posted> Snapshot()
        {
            lock (_posted)
            {
                return new List<Posted>(_posted);
            }
        }
    }
}
