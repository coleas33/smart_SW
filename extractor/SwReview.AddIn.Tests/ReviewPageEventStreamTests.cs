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
/// <b>One boot, one scripted conversation.</b> Every assertion below reads the same run. A
/// WebView2 with the real page in it costs seconds to start, the conversation is a single
/// ordered script (open, frames, a frame for another chat, two closures, a session end), and
/// splitting it into six boots would be six times the wall clock to observe the same six facts.
/// The script is deterministic and nothing in it depends on wall-clock time, because
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
    /// `events.closed` reopens from the highest `seq` the page actually showed, which is what
    /// stops a reconnect replaying the whole transcript on screen.
    /// </summary>
    [Fact]
    public void AClosedStreamIsReopenedFromTheHighestSeqThePageShowed()
    {
        Conversation run = Scripted.Value;

        JsonElement reopened = run.Payload("events.open", 1);
        Assert.Equal(ChatId, reopened.GetProperty("chat_id").GetString());
        Assert.Equal("12", reopened.GetProperty("last_event_id").GetString());
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

                await Push(page, Frame(7, "text.delta", @"{""text"":""first""}"));
                await Push(page, Frame(12, "text.delta", @"{""text"":""second""}"));
                await OffscreenReviewPage.Settled(page);
                run.TranscriptAfterFrames = await Transcript(page);

                await Push(page, Frame(13, "text.delta", @"{""text"":""ghost""}"), "chat-9");
                await OffscreenReviewPage.Settled(page);
                run.TranscriptAfterGhostFrame = await Transcript(page);

                await Closed(page);
                await OffscreenReviewPage.Settled(page);
                await Closed(page);
                await OffscreenReviewPage.Settled(page);

                await Push(page, Frame(20, "session.ended", @"{""ended_at"":""2026-09-16T10:20:00Z""}"));
                await OffscreenReviewPage.Settled(page);

                run.Delays = await Delays(page);
            });

        return run;
    }

    /// <summary>One `events.frame` from the host, as the pump posts it.</summary>
    private static Task<string> Push(CoreWebView2 page, string frame, string chatId = ChatId) =>
        Post(page, "events.frame", new { chat_id = chatId, frame });

    private static Task<string> Closed(CoreWebView2 page) =>
        Post(page, "events.closed", new { chat_id = ChatId, reason = "the backend closed the event stream." });

    private static Task<string> Post(CoreWebView2 page, string type, object payload)
    {
        page.PostWebMessageAsJson(JsonSerializer.Serialize(
            new { type, id = (string?)null, payload }));
        return page.ExecuteScriptAsync("0");
    }

    /// <summary>One raw SSE frame, the text between blank lines, exactly as the host hands it on.</summary>
    private static string Frame(int seq, string type, string body) =>
        "id: " + seq + "\ndata: {\"seq\":" + seq + ",\"type\":\"" + type + "\",\"body\":" + body + "}";

    private static async Task<string> Transcript(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync(
            "document.getElementById('transcript').textContent");
        return JsonDocument.Parse(raw).RootElement.GetString() ?? string.Empty;
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

        public string TranscriptAfterFrames { get; set; } = string.Empty;

        public string TranscriptAfterGhostFrame { get; set; } = string.Empty;

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
