using System;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T046: Results or Transcript, not both (User Story 5, FR-017 to FR-019,
/// contracts/views.md).
///
/// Results answers "what is wrong": the summary, the questions, Start here, the findings, what
/// was not reached, the error cards and the pinned follow-up answers - no tool call, no argument,
/// no token count. Transcript answers "how the reviewer got there": every prose block and tool
/// call in the order it happened, a one-line marker where each finding was recorded, the
/// evidence records, the counts. Stacked in one 300 px strip each made the other worse; now each
/// owns the pane in turn, and only the Transcript scrolls itself as it grows.
/// </summary>
public sealed class ReviewPageViewsTests
{
    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    private const string ToolName = "check_rms_part";

    private const int Fillers = 40;

    /// <summary>Results holds no tool card, no tool argument, no usage line and no count of calls or rounds (FR-018).</summary>
    [Fact]
    public void ResultsHoldsNoToolCallNoArgumentAndNoTokenCount()
    {
        JsonElement running = Scripted.Value.Running;

        Assert.Equal(0, running.GetProperty("resultsToolCards").GetInt32());
        Assert.False(running.GetProperty("resultsHasUsageLine").GetBoolean(), "the usage line is in Results.");
        string text = running.GetProperty("resultsText").GetString()!;
        Assert.DoesNotContain(ToolName, text);
        Assert.DoesNotContain("component_id", text);
        Assert.DoesNotContain("tool call", text);
        Assert.DoesNotContain("round trip", text);
    }

    /// <summary>
    /// The Transcript holds the prose, the tool call, the evidence record and one marker per
    /// finding, in the order the events arrived; the finding cards are in Results' list and not
    /// in the Transcript.
    /// </summary>
    [Fact]
    public void TranscriptHoldsTheProseTheCallsTheRecordsAndAMarkerPerFindingInEventOrder()
    {
        JsonElement running = Scripted.Value.Running;

        Assert.Equal(
            new[] { "assistant", "tool", "marker", "evidence", "marker" },
            ReviewPageDriver.Strings(running, "transcriptKinds"));
        Assert.Equal(
            new[] { "F-007 recorded: The pin interferes with the bore", "F-008 recorded: The second pin interferes with its bore" },
            ReviewPageDriver.Strings(running, "markers"));
        Assert.Equal(new[] { "F-007", "F-008" }, ReviewPageDriver.Strings(running, "findingCards"));
        Assert.Equal(0, running.GetProperty("cardsInTranscript").GetInt32());
    }

    /// <summary>
    /// An `error` event is a card in Results, in the plain words it arrived with, and a line in
    /// the Transcript naming its class - the class is transcript vocabulary.
    /// </summary>
    [Fact]
    public void AnErrorEventIsACardInResultsAndALineNamingItsClassInTheTranscript()
    {
        JsonElement errored = Scripted.Value.Errored;

        Assert.Equal(1, errored.GetProperty("resultsErrorCards").GetInt32());
        Assert.Contains("the provider refused the request", errored.GetProperty("resultsErrorText").GetString()!);
        Assert.Equal(0, errored.GetProperty("transcriptErrorCards").GetInt32());
        Assert.Contains("ProviderError", errored.GetProperty("transcriptErrorLine").GetString()!);
        Assert.Contains("the provider refused the request", errored.GetProperty("transcriptErrorLine").GetString()!);
    }

    /// <summary>New content scrolls the Transcript to its end, and never moves Results under the reader.</summary>
    [Fact]
    public void NewContentScrollsTheTranscriptToItsEndAndNeverMovesResults()
    {
        Run run = Scripted.Value;

        Assert.True(run.ResultsScroll.GetProperty("before").GetDouble() > 0, "Results was not scrolled, so the test proves nothing.");
        Assert.Equal(run.ResultsScroll.GetProperty("before").GetDouble(), run.ResultsScroll.GetProperty("after").GetDouble());

        Assert.True(run.TranscriptScroll.GetProperty("scrolled").GetBoolean(), "the Transcript did not scroll.");
        Assert.True(run.TranscriptScroll.GetProperty("atEnd").GetBoolean(), "the Transcript is not at its end.");
    }

    /// <summary>The status line reads each of the page's four sentences in its state, and nothing without a chat.</summary>
    [Fact]
    public void TheStatusLineReadsEachOfItsFourSentencesInItsState()
    {
        Run run = Scripted.Value;

        Assert.True(run.NoChat.GetProperty("stateHidden").GetBoolean(), "the status line is shown with no chat.");
        Assert.Equal("The review is running.", run.Running.GetProperty("state").GetString());
        Assert.Equal("Reconnecting to the review.", run.Reconnecting.GetProperty("state").GetString());
        Assert.Equal("Waiting for your answers.", run.Waiting.GetProperty("state").GetString());
        Assert.Equal("The review has finished.", run.Finished.GetProperty("state").GetString());
    }

    [Fact]
    public void TheFollowUpFormIsVisibleInBothViews()
    {
        Assert.True(Scripted.Value.TranscriptScroll.GetProperty("followupRendered").GetBoolean(), "no follow-up form in the Transcript view.");
        Assert.True(Scripted.Value.Running.GetProperty("followupRendered").GetBoolean(), "no follow-up form in Results.");
    }

    /// <summary>
    /// A follow-up is pinned in Results the moment it is sent, waiting; its answer fills the pin
    /// and is brought into view, and the view stays Results. The same exchange is prose in the
    /// Transcript.
    /// </summary>
    [Fact]
    public void AFollowUpIsPinnedInResultsAndItsAnswerFillsThePinWithoutSwitching()
    {
        Run run = Scripted.Value;

        Assert.Equal("Why F-007?", run.PinWaiting.GetProperty("question").GetString());
        Assert.Equal("Waiting for the answer.", run.PinWaiting.GetProperty("answer").GetString());

        Assert.Equal("Because the pin overlaps the bore.", run.PinAnswered.GetProperty("answer").GetString());
        Assert.True(run.PinAnswered.GetProperty("inView").GetBoolean(), "the answered pin was not brought into view.");
        Assert.Contains("view-results", run.PinAnswered.GetProperty("bodyClass").GetString()!.Split(' '));
        Assert.True(run.PinAnswered.GetProperty("questionInTranscript").GetBoolean(), "the follow-up is not prose in the Transcript.");
        Assert.True(run.PinAnswered.GetProperty("answerInTranscript").GetBoolean(), "the answer is not prose in the Transcript.");
    }

    [Fact]
    public void AFollowUpTurnThatEndsWithoutAnAnswerSaysSoInItsPin()
    {
        JsonElement stopped = Scripted.Value.PinStopped;

        Assert.Equal("And F-008?", stopped.GetProperty("question").GetString());
        Assert.Equal("No answer: the turn ended (stopped).", stopped.GetProperty("answer").GetString());
        Assert.Equal(2, stopped.GetProperty("pins").GetInt32());
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static Run Drive()
    {
        var run = new Run();

        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.RouteAttention("chat-1", SummarySample.Json());
                run.NoChat = await driver.Read(ReadState);

                await driver.StartReview();
                int seq = 0;
                await driver.Push("chat-1", ++seq, "text.delta", @"{""text"":""Looking at the pins.""}");
                await driver.Push("chat-1", ++seq, "tool.started",
                    @"{""step_index"":1,""tool"":""" + ToolName + @""",""arguments"":{""component_id"":""cmp:0003""}}");
                await driver.Push("chat-1", ++seq, "tool.finished",
                    @"{""step_index"":1,""status"":""ok"",""result_summary"":""3 findings"",""elapsed_s"":0.14}");
                await driver.Push("chat-1", ++seq, "finding", Finding("F-007", "The pin interferes with the bore"));
                await driver.Push("chat-1", ++seq, "usage", UsageBody);
                await driver.Push("chat-1", ++seq, "evidence.requested",
                    @"{""id"":""ER-002"",""what"":""Which fit?"",""why"":""The limits decide it."",""entity_ids"":[""cmp:0002""]}");
                await driver.Push("chat-1", ++seq, "finding", Finding("F-008", "The second pin interferes with its bore"));
                await driver.Settle();
                run.Running = await driver.Read(ReadState);

                for (int filler = 0; filler < Fillers; filler++)
                {
                    await driver.Push("chat-1", ++seq, "finding", Finding("F-" + (100 + filler), "Filler " + filler));
                }

                await driver.Settle();
                await driver.Read("var r = document.getElementById('results'); r.scrollTop = 150; window.__before = r.scrollTop; return JSON.stringify({ok: true});");
                await driver.Push("chat-1", ++seq, "finding", Finding("F-200", "One more"));
                await driver.Push("chat-1", ++seq, "tool.started", @"{""step_index"":2,""tool"":""list_holes"",""arguments"":{}}");
                await driver.Settle();
                run.ResultsScroll = await driver.Read("return JSON.stringify({ok: true, before: window.__before, after: document.getElementById('results').scrollTop});");

                await driver.Click("view-transcript");
                await driver.Read("document.getElementById('transcript').scrollTop = 0; return JSON.stringify({ok: true});");
                await driver.Push("chat-1", ++seq, "tool.finished", @"{""step_index"":2,""status"":""ok"",""result_summary"":""12 holes"",""elapsed_s"":0.2}");
                await driver.Push("chat-1", ++seq, "tool.started", @"{""step_index"":3,""tool"":""list_mates"",""arguments"":{}}");
                await driver.Settle();
                run.TranscriptScroll = await driver.Read(@"
var t = document.getElementById('transcript');
return JSON.stringify({
  ok: true,
  scrolled: t.scrollTop > 0,
  atEnd: t.scrollTop + t.clientHeight >= t.scrollHeight - 2,
  followupRendered: h.rendered(document.getElementById('followup'))
});");
                await driver.Click("view-results");

                await driver.Push("chat-1", ++seq, "error", @"{""error_class"":""ProviderError"",""message"":""the provider refused the request"",""retryable"":false}");
                await driver.Settle();
                run.Errored = await driver.Read(ReadErrors);

                await driver.EndSession("chat-1");
                run.Waiting = await driver.Read(ReadState);

                await driver.RouteAttention("chat-1", SummarySample.EmptyJson());
                await driver.EndSession("chat-1");
                run.Finished = await driver.Read(ReadState);

                await driver.Route("POST", "/sessions/chat-1/messages", 200, "{}");
                await driver.Read(FollowUp("Why F-007?"));
                await driver.Settle();
                run.PinWaiting = await driver.Read(ReadPins);

                await driver.Post("events.closed", new { chat_id = "chat-1", reason = "the backend closed the event stream." });
                run.Reconnecting = await driver.Read(ReadState);
                await Task.Delay(1300);
                await driver.Settle();

                await driver.Push("chat-1", 300, "text.done", @"{""text"":""Because the pin overlaps the bore.""}");
                await driver.Settle();
                run.PinAnswered = await driver.Read(ReadPins);

                await driver.EndSession("chat-1");
                await driver.Read(FollowUp("And F-008?"));
                await driver.Settle();
                await driver.Push("chat-1", 400, "turn.ended", @"{""reason"":""stopped""}");
                await driver.Settle();
                run.PinStopped = await driver.Read(ReadPins);
            });

        return run;
    }

    private static string Finding(string id, string title) => JsonSerializer.Serialize(new
    {
        id,
        check = "interference.static",
        title,
        status = "demonstrated",
        severity = "medium",
        component_ids = new[] { "cmp:0002", "cmp:0003" },
        observed = title + ".",
    });

    private static string FollowUp(string text) =>
        "var input = document.getElementById('followup-text'); input.value = " + JsonSerializer.Serialize(text) + ";"
        + "document.getElementById('followup').dispatchEvent(new Event('submit', {cancelable: true}));"
        + "return JSON.stringify({ok: true});";

    private const string UsageBody =
        @"{""round_index"":0,""provider"":""openai"",""model"":""gpt-5.6"",""input_tokens"":10,"
        + @"""cached_input_tokens"":5,""cache_write_tokens"":null,""output_tokens"":8,"
        + @"""reasoning_tokens"":4,""tool_result_input_tokens"":null,""total_tokens"":18,"
        + @"""latency_s"":1.5,""cache_diagnostic"":null}";

    private const string ReadState = @"
var results = document.getElementById('results');
var transcript = document.getElementById('transcript');
var kinds = [];
for (var i = 0; i < transcript.children.length; i++) {
  var c = transcript.children[i].classList;
  kinds.push(c.contains('marker') ? 'marker'
    : c.contains('tool') ? 'tool'
    : c.contains('evidence') ? 'evidence'
    : c.contains('assistant') ? 'assistant'
    : c.contains('engineer') ? 'engineer'
    : c.contains('error') ? 'error'
    : c.contains('system') ? 'system' : transcript.children[i].className);
}
var state = document.getElementById('results-state');
return JSON.stringify({
  ok: true,
  state: state.textContent,
  stateHidden: !!state.hidden,
  resultsToolCards: results.querySelectorAll('.card.tool').length,
  resultsHasUsageLine: !!results.querySelector('#usage-line'),
  resultsText: results.textContent,
  transcriptKinds: kinds,
  markers: h.texts(transcript, '.marker'),
  findingCards: h.attrs(document.getElementById('findings'), '.card.finding', 'data-finding-id'),
  cardsInTranscript: transcript.querySelectorAll('.card.finding').length,
  followupRendered: h.rendered(document.getElementById('followup'))
});";

    private const string ReadErrors = @"
var results = document.getElementById('results');
var transcript = document.getElementById('transcript');
var lines = transcript.querySelectorAll('.block.error');
return JSON.stringify({
  ok: true,
  resultsErrorCards: results.querySelectorAll('.card.error').length,
  resultsErrorText: h.text(results, '.card.error'),
  transcriptErrorCards: transcript.querySelectorAll('.card.error').length,
  transcriptErrorLine: lines.length ? lines[lines.length - 1].textContent : ''
});";

    private const string ReadPins = @"
var pins = document.querySelectorAll('#answers .pinned');
var pin = pins.length ? pins[pins.length - 1] : null;
var prose = h.texts(document.getElementById('transcript'), '.block .text');
return JSON.stringify({
  ok: true,
  pins: pins.length,
  question: pin ? h.text(pin, '.pinned-question') : null,
  answer: pin ? h.text(pin, '.pinned-answer') : null,
  inView: h.inView(pin),
  bodyClass: document.body.className,
  questionInTranscript: prose.indexOf('Why F-007?') >= 0,
  answerInTranscript: prose.indexOf('Because the pin overlaps the bore.') >= 0
});";

    private sealed class Run
    {
        public JsonElement NoChat { get; set; }

        public JsonElement Running { get; set; }

        public JsonElement ResultsScroll { get; set; }

        public JsonElement TranscriptScroll { get; set; }

        public JsonElement Errored { get; set; }

        public JsonElement Waiting { get; set; }

        public JsonElement Finished { get; set; }

        public JsonElement PinWaiting { get; set; }

        public JsonElement Reconnecting { get; set; }

        public JsonElement PinAnswered { get; set; }

        public JsonElement PinStopped { get; set; }
    }
}
