using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T043: questions for you (User Story 4, FR-014 to FR-016, contracts/questions.md
/// sections 4, 6 and 7).
///
/// Every evening review asked for drawings and fit intent in long paragraphs nobody answered,
/// and each answer would have cost a whole turn. The review now asks one short question at a
/// time above the grouped findings; the engineer picks an offered answer or types one, skips what they
/// cannot answer yet, and sends what they answered together - one `POST /sessions/{chat_id}
/// /evidence` (feature 008's batch route), one resumed turn - with the cost of resuming said
/// beside Send before they press it.
///
/// <b>The open list is the backend's.</b> The page must not filter evidence requests by status
/// (PageRuleScanTests), so the questions come from `summary.questions`, in its order, and the
/// panel prints them. What the page keeps is only what the engineer typed and skipped, per chat,
/// in page memory.
///
/// <b>One way to answer.</b> The transcript's evidence card is a record now: no answer box, no
/// Send, and no page script posts to the single-answer route.
/// </summary>
public sealed class ReviewPageQuestionsTests
{
    private const string HostileText = "<img src=x onerror=alert(1)></button><script>alert(2)</script>";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    [Fact]
    public void TheFirstQuestionSitsAfterTheSummaryAndBeforeTheGroupedFindingsWithAPager()
    {
        JsonElement first = Scripted.Value.First;

        Assert.False(first.GetProperty("hidden").GetBoolean(), "#questions stayed hidden.");
        Assert.True(first.GetProperty("afterSummary").GetBoolean(), "#questions must come after #summary.");
        Assert.True(first.GetProperty("beforeGroups").GetBoolean(), "#questions must come before #findings-by-type.");
        Assert.Equal("Question 1 of 3", first.GetProperty("position").GetString());
        Assert.True(first.GetProperty("previousDisabled").GetBoolean(), "Previous is offered on the first question.");
        Assert.False(first.GetProperty("nextDisabled").GetBoolean(), "Next is refused on the first question.");
    }

    /// <summary>
    /// The short question in the lead face, the goal it blocks and the parts it is about by name;
    /// the long description, the reason and the ids behind a shut fold.
    /// </summary>
    [Fact]
    public void AQuestionShowsItsShortFormWhatItBlocksAndItsPartsWithTheRestInAShutFold()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal("Is Pin-A-1 meant to be a press fit in Plate-1?", first.GetProperty("question").GetString());
        Assert.Equal("Blocks: Fits and stacks", first.GetProperty("blocks").GetString());
        Assert.Equal("About: Pin-A-1, Plate-1", first.GetProperty("about").GetString());
        Assert.Equal("shut", first.GetProperty("fold").GetString());
        Assert.Contains("the drawing that governs the fit was not supplied", first.GetProperty("foldText").GetString()!);
        Assert.Contains("cmp:0002, cmp:0003", first.GetProperty("foldText").GetString()!);
        Assert.DoesNotContain("cmp:", first.GetProperty("visible").GetString()!);
    }

    /// <summary>
    /// Offered answers are buttons; pressing one selects it and only it. Send stays disabled
    /// until some question has an answer that is not blank, and the cost of resuming is printed
    /// beside it in the backend's words (FR-016).
    /// </summary>
    [Fact]
    public void AnOptionPressSelectsItAloneAndSendWaitsForANonBlankAnswer()
    {
        Run run = Scripted.Value;

        Assert.Equal(new[] { "Press fit", "Slip fit", "Not sure" }, ReviewPageDriver.Strings(run.First, "options"));
        Assert.Equal(new[] { "false", "false", "false" }, ReviewPageDriver.Strings(run.First, "pressed"));
        Assert.True(run.First.GetProperty("sendDisabled").GetBoolean(), "Send is offered with nothing answered.");
        Assert.Equal(SummarySample.ResumeText, run.First.GetProperty("resume").GetString());

        Assert.True(run.BlankTyped.GetProperty("sendDisabled").GetBoolean(), "a blank answer enabled Send.");

        Assert.Equal(new[] { "false", "true", "false" }, ReviewPageDriver.Strings(run.SecondOption, "pressed"));
        Assert.Equal(new[] { "true", "false", "false" }, ReviewPageDriver.Strings(run.FirstOption, "pressed"));
        Assert.False(run.FirstOption.GetProperty("sendDisabled").GetBoolean(), "Send stayed disabled with an answer.");
    }

    /// <summary>
    /// A question with no offered answers gets one text box; a question with only its long
    /// description asks that description; Skip for now moves on and sends nothing.
    /// </summary>
    [Fact]
    public void AFreeTextQuestionHasABoxAndSkipMovesOnSendingNothing()
    {
        Run run = Scripted.Value;

        Assert.Equal("Question 2 of 3", run.Second.GetProperty("position").GetString());
        Assert.True(run.Second.GetProperty("hasBox").GetBoolean(), "a question with no options has no box.");
        Assert.Empty(ReviewPageDriver.Strings(run.Second, "options"));

        Assert.Equal("Question 3 of 3", run.Third.GetProperty("position").GetString());
        Assert.StartsWith("Please confirm which surface of the base plate", run.Third.GetProperty("question").GetString());
        Assert.Equal(JsonValueKind.Null, run.Third.GetProperty("blocks").ValueKind);
        Assert.True(run.Third.GetProperty("nextDisabled").GetBoolean(), "Next is offered on the last question.");

        Assert.Equal("Skipped for now.", run.Skipped.GetProperty("skippedNote").GetString());
        Assert.Equal(0, run.Skipped.GetProperty("calls").GetInt32());
    }

    /// <summary>
    /// What was typed and chosen is kept: going back shows it, and so does a ranking re-rendered
    /// at the end of a turn.
    /// </summary>
    [Fact]
    public void DraftsSurviveGoingBackAndTheRankingBeingRenderedAgain()
    {
        Run run = Scripted.Value;

        Assert.Equal("  Drawing FICT-1001 rev B  ", run.BackToSecond.GetProperty("boxValue").GetString());
        Assert.Equal("  Drawing FICT-1001 rev B  ", run.AfterRerender.GetProperty("boxValue").GetString());
        Assert.Equal(new[] { "true", "false", "false" }, ReviewPageDriver.Strings(run.RerenderFirst, "pressed"));
    }

    /// <summary>
    /// Send posts exactly one submission holding the answered questions in the order the
    /// summary supplied them, trimmed, and nothing for the skipped one; then the turn runs, the
    /// stream reopens, and the panel is disabled while it does.
    /// </summary>
    [Fact]
    public void SendPostsOneSubmissionOfTheAnsweredQuestionsInOrderThenTheTurnRuns()
    {
        Run run = Scripted.Value;
        JsonElement[] posts = run.SentCalls.Where(call => call.GetProperty("method").GetString() == "POST").ToArray();

        JsonElement post = Assert.Single(posts);
        Assert.Equal("/sessions/chat-1/evidence", post.GetProperty("path").GetString());
        Assert.Equal("Bearer " + ReviewPageDriver.Token, post.GetProperty("authorization").GetString());

        JsonElement body = JsonDocument.Parse(post.GetProperty("body").GetString()!).RootElement;
        JsonElement[] answers = body.GetProperty("answers").EnumerateArray().ToArray();
        Assert.Equal(2, answers.Length);
        Assert.Equal("ER-002", answers[0].GetProperty("request_id").GetString());
        Assert.Equal("Press fit", answers[0].GetProperty("answer").GetString());
        Assert.Equal("ER-004", answers[1].GetProperty("request_id").GetString());
        Assert.Equal("Drawing FICT-1001 rev B", answers[1].GetProperty("answer").GetString());

        Assert.True(run.Sent.GetProperty("controlsDisabled").GetBoolean(), "the panel stayed live during the turn.");
        Assert.False(run.Sent.GetProperty("stopDisabled").GetBoolean(), "Stop is disabled while the answers run.");
        Assert.True(run.StreamOpensAfterSend > run.StreamOpensBeforeSend, "the stream was not reopened for the turn.");
    }

    /// <summary>Once sent, the drafts of the sent questions are dropped; the skipped one was never sent.</summary>
    [Fact]
    public void TheDraftsOfTheSentQuestionsAreDropped()
    {
        Run run = Scripted.Value;

        Assert.Equal(new[] { "false", "false", "false" }, ReviewPageDriver.Strings(run.AfterTurn, "pressed"));
        Assert.Equal(string.Empty, run.AfterTurnSecond.GetProperty("boxValue").GetString());
    }

    /// <summary>
    /// A question answered from another window is refused whole (008's batch route records
    /// nothing): the pane names the question by its number and its words, reads the summary
    /// again, and keeps every other draft.
    /// </summary>
    [Fact]
    public void AnAlreadyAnsweredRefusalNamesTheQuestionReloadsTheSummaryAndKeepsTheOtherDrafts()
    {
        Run run = Scripted.Value;

        Assert.Equal(
            "Question 1 (Is Pin-A-1 meant to be a press fit in Plate-1?) was answered elsewhere, so nothing was sent.",
            run.Refused.GetProperty("status").GetString());
        Assert.Equal(run.AttentionReadsBeforeRefusal + 1, run.AttentionReadsAfterRefusal);
        Assert.Equal("Face A", run.RefusedThird.GetProperty("boxValue").GetString());
        Assert.False(run.Refused.GetProperty("controlsDisabled").GetBoolean(), "the panel stayed disabled after a refusal.");
        Assert.True(run.Refused.GetProperty("stopDisabled").GetBoolean(), "a refused submission left a turn running.");
    }

    /// <summary>A refusal because a turn is already running says so, and keeps every draft.</summary>
    [Fact]
    public void ATurnRunningRefusalSaysSoAndKeepsTheDrafts()
    {
        Run run = Scripted.Value;

        Assert.Contains("a turn is already running", run.TurnRefused.GetProperty("status").GetString()!);
        Assert.Equal("Face A", run.TurnRefusedThird.GetProperty("boxValue").GetString());
        Assert.Equal(run.AttentionReadsAfterRefusal, run.AttentionReadsAfterTurnRefusal);
    }

    [Fact]
    public void HostileQuestionOptionAndReasonTextsAreLiteral()
    {
        JsonElement hostile = Scripted.Value.Hostile;

        Assert.Equal(HostileText, hostile.GetProperty("question").GetString());
        Assert.Contains(HostileText, ReviewPageDriver.Strings(hostile, "options"));
        Assert.Contains(HostileText, hostile.GetProperty("foldText").GetString()!);
        Assert.Equal(0, hostile.GetProperty("injected").GetInt32());
    }

    /// <summary>No open question - a count of zero, or a backend that sends no summary - shows no panel.</summary>
    [Fact]
    public void NoQuestionsRendersNoPanel()
    {
        Assert.True(Scripted.Value.NoneCounted.GetProperty("hidden").GetBoolean(), "a count of 0 showed the panel.");
        Assert.True(Scripted.Value.NoSummary.GetProperty("hidden").GetBoolean(), "no summary showed the panel.");
    }

    /// <summary>
    /// The transcript's evidence card is a record: the question, why, and once answered the
    /// answer - no box and no Send, because the one way to answer is the panel.
    /// </summary>
    [Fact]
    public void TheTranscriptsEvidenceRecordHasNoAnswerBoxAndNoSend()
    {
        JsonElement record = Scripted.Value.Record;

        Assert.Equal(1, record.GetProperty("cards").GetInt32());
        Assert.Equal(0, record.GetProperty("boxes").GetInt32());
        Assert.Equal(0, record.GetProperty("sends").GetInt32());
    }

    // ---- buttons and a text box (feature 013 T035, contracts/part-roles.md section 8) -------------

    /// <summary>The run with the backend's labels, whose part-roles question allows text.</summary>
    private static readonly Lazy<TextRun> TextScripted = new Lazy<TextRun>(DriveTextBox);

    /// <summary>
    /// A question with `allow_text` draws its offered answers as buttons and, under them, one text
    /// box whose placeholder is the backend's (`labels.questions.text_placeholder`), set as an
    /// attribute of characters: the sample's placeholder carries markup and injects nothing.
    /// </summary>
    [Fact]
    public void AQuestionThatAllowsTextDrawsItsButtonsAndATextBoxWithTheBackendsPlaceholder()
    {
        JsonElement first = TextScripted.Value.First;

        Assert.Equal(SummarySample.PartRolesQuestionText, first.GetProperty("question").GetString());
        Assert.Equal(SummarySample.PartRolesOptions, ReviewPageDriver.Strings(first, "options"));
        Assert.Equal(new[] { "false", "false" }, ReviewPageDriver.Strings(first, "pressed"));
        Assert.True(first.GetProperty("hasBox").GetBoolean(), "a question that allows text has no box.");
        Assert.True(first.GetProperty("boxAfterOptions").GetBoolean(), "the text box is not under the buttons.");
        Assert.Equal(string.Empty, first.GetProperty("boxValue").GetString());
        Assert.Equal(LabelsSample.HostileTextPlaceholder, first.GetProperty("placeholder").GetString());
        Assert.Equal(0, first.GetProperty("injected").GetInt32());
        Assert.True(first.GetProperty("sendDisabled").GetBoolean(), "Send is offered with nothing answered.");
    }

    /// <summary>Pressing a button answers with its text, verbatim, and only that button is pressed.</summary>
    [Fact]
    public void ChoosingAButtonSendsItsTextVerbatim()
    {
        TextRun run = TextScripted.Value;

        Assert.Equal(new[] { "true", "false" }, ReviewPageDriver.Strings(run.AfterOption, "pressed"));
        Assert.Equal(string.Empty, run.AfterOption.GetProperty("boxValue").GetString());
        Assert.Equal(new[] { ("ER-001", "All bought") }, Answers(run.OptionCalls));
    }

    /// <summary>
    /// Typing answers with the text: every button lets go as the engineer types, the draft
    /// survives going to another question and back, and Send carries the text trimmed.
    /// </summary>
    [Fact]
    public void TypingLetsGoOfTheButtonsAndSendsTheTrimmedText()
    {
        TextRun run = TextScripted.Value;

        Assert.Equal(new[] { "false", "false" }, ReviewPageDriver.Strings(run.AfterTyping, "pressed"));
        Assert.Equal(TypedNames, run.AfterTyping.GetProperty("boxValue").GetString());
        Assert.False(run.AfterTyping.GetProperty("sendDisabled").GetBoolean(), "Send stayed disabled with a typed answer.");
        Assert.Equal(TypedNames, run.TypedBack.GetProperty("boxValue").GetString());
        Assert.Equal(new[] { "false", "false" }, ReviewPageDriver.Strings(run.TypedBack, "pressed"));
        Assert.Equal(new[] { ("ER-001", TypedNames.Trim()) }, Answers(run.TypedCalls));
    }

    /// <summary>A button pressed after typing is the answer: the box empties and that button is pressed.</summary>
    [Fact]
    public void AButtonPressedAfterTypingIsTheAnswerAndEmptiesTheBox()
    {
        JsonElement repressed = TextScripted.Value.Repressed;

        Assert.Equal(new[] { "false", "true" }, ReviewPageDriver.Strings(repressed, "pressed"));
        Assert.Equal(string.Empty, repressed.GetProperty("boxValue").GetString());
    }

    /// <summary>
    /// A question without `allow_text` renders as before: offered answers are buttons and no
    /// box, and a question with none gets one box with the page's own placeholder.
    /// </summary>
    [Fact]
    public void AQuestionWithoutAllowTextRendersAsBefore()
    {
        TextRun run = TextScripted.Value;

        Assert.Equal(new[] { "Press fit", "Slip fit", "Not sure" }, ReviewPageDriver.Strings(run.OptionsOnly, "options"));
        Assert.False(run.OptionsOnly.GetProperty("hasBox").GetBoolean(), "a question without allow_text drew a box beside its buttons.");
        Assert.Empty(ReviewPageDriver.Strings(run.FreeText, "options"));
        Assert.True(run.FreeText.GetProperty("hasBox").GetBoolean(), "a question with no options has no box.");
        Assert.Equal("Your answer", run.FreeText.GetProperty("placeholder").GetString());
    }

    /// <summary>
    /// FR-030: with no labels - an older backend - the box beside the buttons still appears, with
    /// the placeholder the page's own free-text box has always carried.
    /// </summary>
    [Fact]
    public void WithNoLabelsTheBoxBesideTheButtonsCarriesThePagesOwnPlaceholder()
    {
        JsonElement unlabelled = Scripted.Value.TextNoLabels;

        Assert.Equal(SummarySample.PartRolesOptions, ReviewPageDriver.Strings(unlabelled, "options"));
        Assert.True(unlabelled.GetProperty("hasBox").GetBoolean(), "the box beside the buttons is missing with no labels.");
        Assert.Equal("Your answer", unlabelled.GetProperty("placeholder").GetString());
    }

    /// <summary>
    /// Feature 013 T103 (contracts/sources.md section 2): the pager line carries the backend's word
    /// for who asked - the part-roles question is code's, the sample's fit question the model's -
    /// looked up from `labels.source` by the question's `source`, never compared; and with no
    /// labels, none.
    /// </summary>
    [Fact]
    public void ThePagerLineCarriesTheQuestionsSourceWord()
    {
        TextRun run = TextScripted.Value;

        Assert.Equal(LabelsSample.SourceCode, run.First.GetProperty("sourceChip").GetString());
        Assert.Equal(LabelsSample.SourceModel, run.OptionsOnly.GetProperty("sourceChip").GetString());
        Assert.Equal(JsonValueKind.Null, Scripted.Value.First.GetProperty("sourceChip").ValueKind);
    }

    /// <summary>What the engineer types into the part-roles question's box, spaces and all.</summary>
    private const string TypedNames = "  FICT-PIN-01.SLDPRT, FICT-SPACER-02.SLDPRT  ";

    private static TextRun DriveTextBox()
    {
        var run = new TextRun();

        ReviewPageDriver.Run(
            driver => driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json())),
            async driver =>
            {
                await driver.RouteAttention("chat-1", SummarySample.Json(summary => SummarySample.Ask(
                    summary, SummarySample.PartRolesQuestion(), SummarySample.Question(0), SummarySample.Question(1))));
                await driver.Route("POST", "/sessions/chat-1/evidence", 202, "{}");
                await driver.StartReview();
                await driver.EndSession("chat-1");
                run.First = await driver.Read(ReadPanel);

                run.AfterOption = await driver.Read(Option(0) + ReadPanelBody);
                run.OptionCalls = await SendAndEndTheTurn(driver);

                run.AfterTyping = await driver.Read(Option(1) + Type(TypedNames) + ReadPanelBody);
                run.TypedBack = await driver.Read(Press("question-next") + Press("question-previous") + ReadPanelBody);
                run.TypedCalls = await SendAndEndTheTurn(driver);

                run.Repressed = await driver.Read(Type("FICT-PIN-01") + Option(1) + ReadPanelBody);
                run.OptionsOnly = await driver.Read(Press("question-next") + ReadPanelBody);
                run.FreeText = await driver.Read(Press("question-next") + ReadPanelBody);
            });

        return run;
    }

    /// <summary>Presses Send, reads what the page posted, and ends the resumed turn.</summary>
    private static async System.Threading.Tasks.Task<JsonElement[]> SendAndEndTheTurn(ReviewPageDriver driver)
    {
        await driver.ClearCalls();
        await driver.Read(Press("question-send") + "return JSON.stringify({ok: true});");
        await driver.Settle();
        JsonElement[] calls = await driver.Calls();
        await driver.EndSession("chat-1");
        return calls;
    }

    /// <summary>The `(request_id, answer)` pairs of the one evidence submission among <paramref name="calls"/>.</summary>
    private static (string, string)[] Answers(JsonElement[] calls)
    {
        JsonElement post = Assert.Single(calls, call => call.GetProperty("method").GetString() == "POST");
        Assert.Equal("/sessions/chat-1/evidence", post.GetProperty("path").GetString());
        return JsonDocument.Parse(post.GetProperty("body").GetString()!).RootElement
            .GetProperty("answers").EnumerateArray()
            .Select(answer => (answer.GetProperty("request_id").GetString()!, answer.GetProperty("answer").GetString()!))
            .ToArray();
    }

    /// <summary>No page script names the single-answer route any more (contracts/questions.md section 7).</summary>
    [Fact]
    public void NoPageScriptPostsToTheSingleAnswerRoute()
    {
        foreach (var script in ReviewPageFiles.Scripts())
        {
            Assert.False(
                Regex.IsMatch(script.Value, @"/evidence/"),
                script.Key + " still names the single-answer route /evidence/{request_id}.");
        }
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
                await driver.StartReview();
                await driver.Push("chat-1", 1, "evidence.requested",
                    @"{""id"":""ER-002"",""what"":""Which fit?"",""why"":""The limits decide it."",""entity_ids"":[""cmp:0002""],""status"":""open""}");
                await driver.EndSession("chat-1");
                run.Record = await driver.Read(ReadRecord);
                run.First = await driver.Read(ReadPanel);

                run.Second = await driver.Read(Press("question-next") + ReadPanelBody);
                run.BlankTyped = await driver.Read(Type("   ") + ReadPanelBody);
                await driver.Read(Press("question-previous") + "return JSON.stringify({ok: true});");
                run.SecondOption = await driver.Read(Option(1) + ReadPanelBody);
                run.FirstOption = await driver.Read(Option(0) + ReadPanelBody);
                await driver.Read(Press("question-next") + Type("  Drawing FICT-1001 rev B  ") + "return JSON.stringify({ok: true});");
                run.Third = await driver.Read(Press("question-next") + ReadPanelBody);
                await driver.ClearCalls();
                run.Skipped = await driver.Read(Press("question-skip") + ReadPanelBody);
                run.BackToSecond = await driver.Read(Press("question-previous") + ReadPanelBody);

                await driver.EndSession("chat-1");
                run.AfterRerender = await driver.Read(ReadPanel);
                run.RerenderFirst = await driver.Read(Press("question-previous") + ReadPanelBody);

                await driver.Route("POST", "/sessions/chat-1/evidence", 202, "{}");
                await driver.ClearCalls();
                run.StreamOpensBeforeSend = driver.Posted("events.open").Length;
                await driver.Read(Press("question-send") + "return JSON.stringify({ok: true});");
                await driver.Settle();
                run.Sent = await driver.Read(ReadPanel);
                run.SentCalls = await driver.Calls();
                run.StreamOpensAfterSend = driver.Posted("events.open").Length;

                await driver.EndSession("chat-1");
                run.AfterTurn = await driver.Read(ReadPanel);
                run.AfterTurnSecond = await driver.Read(Press("question-next") + ReadPanelBody);

                // Answer the first and the third, then have the backend refuse the first.
                await driver.Read(Press("question-previous") + Option(1) + Press("question-next") + Press("question-next")
                    + Type("Face A") + "return JSON.stringify({ok: true});");
                await driver.Route("POST", "/sessions/chat-1/evidence", 409,
                    @"{""error_class"":""AlreadyAnswered"",""message"":""ER-002 is already answered"",""retryable"":false,""request_id"":""ER-002""}");
                await driver.ClearCalls();
                await driver.Read(Press("question-send") + "return JSON.stringify({ok: true});");
                await driver.Settle();
                run.AttentionReadsBeforeRefusal = 0;
                run.AttentionReadsAfterRefusal = AttentionReads(await driver.Calls());
                run.Refused = await driver.Read(ReadPanel);
                run.RefusedThird = await driver.Read(Press("question-next") + Press("question-next") + ReadPanelBody);

                await driver.Route("POST", "/sessions/chat-1/evidence", 409,
                    @"{""error_class"":""TurnRunning"",""message"":""a turn is already running"",""retryable"":true}");
                await driver.Read(Press("question-send") + "return JSON.stringify({ok: true});");
                await driver.Settle();
                run.AttentionReadsAfterTurnRefusal = AttentionReads(await driver.Calls());
                run.TurnRefused = await driver.Read(ReadPanel);
                run.TurnRefusedThird = await driver.Read(ReadPanel);

                await driver.StartReview();
                await driver.RouteAttention("chat-2", SummarySample.Json(summary =>
                {
                    JsonNode question = summary["questions"]!["items"]![0]!;
                    question["question"] = HostileText;
                    question["options"] = JsonNode.Parse(JsonSerializer.Serialize(new[] { "Press fit", HostileText }));
                    question["why"] = HostileText;
                }));
                await driver.EndSession("chat-2");
                run.Hostile = await driver.Read(ReadPanel);

                await driver.StartReview();
                await driver.RouteAttention("chat-3", SummarySample.EmptyJson());
                await driver.EndSession("chat-3");
                run.NoneCounted = await driver.Read(ReadPanel);

                await driver.StartReview();
                await driver.RouteAttention("chat-4", AttentionSample.Json());
                await driver.EndSession("chat-4");
                run.NoSummary = await driver.Read(ReadPanel);

                // Feature 013 T035: this run has no labels, and its last review asks the part-roles question.
                await driver.StartReview();
                await driver.RouteAttention("chat-5", SummarySample.Json(summary => SummarySample.Ask(summary, SummarySample.PartRolesQuestion())));
                await driver.EndSession("chat-5");
                run.TextNoLabels = await driver.Read(ReadPanel);
            });

        return run;
    }

    private static int AttentionReads(JsonElement[] calls) =>
        calls.Count(call => call.GetProperty("method").GetString() == "GET"
            && (call.GetProperty("path").GetString() ?? string.Empty).EndsWith("/attention", StringComparison.Ordinal));

    private static string Press(string action) =>
        "document.querySelector('#questions [data-action=\"" + action + "\"]').click();";

    private static string Option(int index) =>
        "document.querySelectorAll('#questions [data-action=\"question-option\"]')[" + index + "].click();";

    private static string Type(string text) =>
        "var box = document.querySelector('#questions .question-answer'); box.value = " + JsonSerializer.Serialize(text)
        + "; box.dispatchEvent(new Event('input', { bubbles: true }));";

    private const string ReadRecord = @"
var cards = document.querySelectorAll('.card.evidence');
return JSON.stringify({
  ok: true,
  cards: cards.length,
  boxes: document.querySelectorAll('.card.evidence input').length,
  sends: document.querySelectorAll('.card.evidence button').length
});";

    private const string ReadPanel = ReadPanelBody;

    private const string ReadPanelBody = @"
var section = document.getElementById('questions');
var fold = section.querySelector('.question-fold');
var box = section.querySelector('.question-answer');
var controls = section.querySelectorAll('button, input');
var allDisabled = controls.length > 0;
for (var i = 0; i < controls.length; i++) { if (!controls[i].disabled) { allDisabled = false; } }
var byAction = function (action) {
  var node = section.querySelector('[data-action=""' + action + '""]');
  return node ? node.disabled : null;
};
return JSON.stringify({
  ok: true,
  hidden: !!section.hidden,
  afterSummary: h.before(document.getElementById('summary'), section),
  beforeGroups: h.before(section, document.getElementById('findings-by-type')),
  position: h.text(section, '.question-position'),
  sourceChip: h.text(section, '.question-pager .source-chip'),
  question: h.text(section, '.question-text'),
  blocks: h.text(section, '.question-blocks'),
  about: h.text(section, '.question-about'),
  options: h.texts(section, '[data-action=""question-option""]'),
  pressed: h.attrs(section, '[data-action=""question-option""]', 'aria-pressed'),
  hasBox: !!box,
  boxValue: box ? box.value : null,
  placeholder: box ? box.getAttribute('placeholder') : null,
  boxAfterOptions: h.before(section.querySelector('.question-options'), box),
  previousDisabled: byAction('question-previous'),
  nextDisabled: byAction('question-next'),
  sendDisabled: byAction('question-send'),
  controlsDisabled: allDisabled,
  resume: h.text(section, '.question-resume'),
  status: h.text(section, '.question-status'),
  skippedNote: h.text(section, '.question-skipped'),
  fold: fold ? (fold.open ? 'open' : 'shut') : 'none',
  foldText: fold ? fold.textContent : '',
  visible: h.visibleText(section),
  injected: h.injected(section),
  stopDisabled: document.getElementById('stop-turn').disabled,
  calls: window.__fetch.calls.length
});";

    private sealed class Run
    {
        public JsonElement Record { get; set; }

        public JsonElement First { get; set; }

        public JsonElement Second { get; set; }

        public JsonElement BlankTyped { get; set; }

        public JsonElement SecondOption { get; set; }

        public JsonElement FirstOption { get; set; }

        public JsonElement Third { get; set; }

        public JsonElement Skipped { get; set; }

        public JsonElement BackToSecond { get; set; }

        public JsonElement AfterRerender { get; set; }

        public JsonElement RerenderFirst { get; set; }

        public JsonElement Sent { get; set; }

        public JsonElement[] SentCalls { get; set; } = new JsonElement[0];

        public int StreamOpensBeforeSend { get; set; }

        public int StreamOpensAfterSend { get; set; }

        public JsonElement AfterTurn { get; set; }

        public JsonElement AfterTurnSecond { get; set; }

        public int AttentionReadsBeforeRefusal { get; set; }

        public int AttentionReadsAfterRefusal { get; set; }

        public JsonElement Refused { get; set; }

        public JsonElement RefusedThird { get; set; }

        public int AttentionReadsAfterTurnRefusal { get; set; }

        public JsonElement TurnRefused { get; set; }

        public JsonElement TurnRefusedThird { get; set; }

        public JsonElement Hostile { get; set; }

        public JsonElement NoneCounted { get; set; }

        public JsonElement NoSummary { get; set; }

        public JsonElement TextNoLabels { get; set; }
    }

    private sealed class TextRun
    {
        public JsonElement First { get; set; }

        public JsonElement AfterOption { get; set; }

        public JsonElement[] OptionCalls { get; set; } = new JsonElement[0];

        public JsonElement AfterTyping { get; set; }

        public JsonElement TypedBack { get; set; }

        public JsonElement[] TypedCalls { get; set; } = new JsonElement[0];

        public JsonElement Repressed { get; set; }

        public JsonElement OptionsOnly { get; set; }

        public JsonElement FreeText { get; set; }
    }
}
