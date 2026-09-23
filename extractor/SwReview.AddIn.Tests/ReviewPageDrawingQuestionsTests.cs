using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 011 User Story 5 and its part B, the page's half: the drawing questions and the
/// read-only open of a confirmed candidate reach the engineer through feature 009's "Questions
/// for you" panel and feature 008's batch route <b>with no page change</b>
/// (specs/011-drawing-context/contracts/questions.md sections 4 and 6, contracts/confirmed-open.md
/// sections 1 and 5; plan.md: "no pane page changes").
///
/// Hand-built, as feature 009's page lane built <see cref="SummarySample"/>: the backend that
/// raises these questions and performs the open is another lane's (T046, T048, T076), so the
/// summary here is written from the contract, modelled on the fictional `plate-drawing` fixture
/// (reviewer/tests/fixtures/drawings) - the block beside its same-name drawing is the candidate,
/// the plate shown by drawings A and B is the governing question.
///
/// What is pinned, because the backend depends on it and the page could break it:
///
/// <b>The confirmation travels as the offered words, exactly.</b> The backend opens a drawing
/// only when the candidate question's answer <i>equals</i> `CANDIDATE_CONFIRM`
/// (confirmed-open.md section 1); a page that reworded, re-cased or decorated the option would
/// silently turn the engineer's "yes" into "open nothing".
///
/// <b>The page recognises nothing.</b> It prints the backend's question, options, blocks line and
/// coverage sentences verbatim and in the backend's order; no page script names the candidate
/// answer, the bridge command or a drawing check, so there is no second place deciding what an
/// answer means.
/// </summary>
public sealed class ReviewPageDrawingQuestionsTests
{
    /// <summary>`checks/drawing_context.CANDIDATE_CONFIRM` (contracts/questions.md section 4).</summary>
    public const string CandidateConfirm = "Yes, open it read-only and read it";

    public const string CandidateQuestion =
        "A drawing with the same name sits beside 1 reviewed file(s) but is not open. Should the review read it?";

    public const string CandidateWhy =
        "Fits, stacks and callouts stay unresolved without a drawing. The review opens a file only when you "
        + "confirm it, read-only, and closes it again.";

    public const string GoverningQuestion = "2 open drawings show FICT-TULMKALO-3001. Which one governs it?";

    public const string GoverningWhy =
        "Open drawings of one part can disagree; the review uses them all, in a fixed order, until you say "
        + "which governs.";

    /// <summary>A governing question too long for buttons, its stem shortened by the backend.</summary>
    public const string ShortenedQuestion =
        "5 open drawings show FICT-OKTAKALO-5001-LONG-CONFIGURATION-SPECIFIC-NAME-THAT-THE-BACKEND-SHORTENS-"
        + "UNTIL-IT-F\u2026. Which one governs it?";

    private static readonly string[] CandidateOptions = { CandidateConfirm, "Review without it", "It is not the right drawing" };

    private static readonly string[] GoverningOptions =
        { "FICT-TULMKALO-3001.SLDDRW", "FICT-TULMKALO-3001-B.SLDDRW", "They all apply" };

    private static readonly string[] QuestionIds = { "ER-003", "ER-004", "ER-005" };

    /// <summary>
    /// What the resumed turn reports, in the order the backend writes it: bucket, check, reason.
    /// Deliberately not in any sorted order - `drawing.context` before `drawing.confirmed_open`,
    /// which sorts first - so a page that sorted a bucket fails.
    /// </summary>
    private static readonly (string Bucket, string Check, string Reason)[] TurnCoverage =
    {
        ("checked", "drawing.context", "read from FICT-TULMKALO-3001.SLDDRW, FICT-TULMKALO-3001-B.SLDDRW; 2 views usable"),
        ("checked", "drawing.confirmed_open", "opened read-only, read and closed (2 sheets)"),
        ("unresolved", "drawing.confirmed_open",
            "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 probe D14)"),
        ("skipped", "drawing.context", "no open drawing shows it"),
        ("checked", "drawing.confirmed_open", "read as it stood; it was already open, so it was left open"),
    };

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    // ---- the candidate question ---------------------------------------------------------------

    /// <summary>
    /// The candidate question in the backend's words: the three answers as buttons in the order
    /// offered, the goal it blocks, the reviewed file it is about, and the backend's `what` and
    /// `why` behind the fold.
    /// </summary>
    [Fact]
    public void TheCandidateQuestionIsAskedInTheBackendsWordsWithItsThreeAnswersInOrder()
    {
        JsonElement first = Scripted.Value.First;

        Assert.False(first.GetProperty("hidden").GetBoolean(), "#questions stayed hidden.");
        Assert.Equal("Question 1 of 3", first.GetProperty("position").GetString());
        Assert.Equal(CandidateQuestion, first.GetProperty("question").GetString());
        Assert.Equal("Blocks: Drawings", first.GetProperty("blocks").GetString());
        Assert.Equal("About: FICT-TULMSORN-3002.SLDPRT", first.GetProperty("about").GetString());
        Assert.Equal(CandidateOptions, ReviewPageDriver.Strings(first, "options"));
        Assert.False(first.GetProperty("hasBox").GetBoolean(), "a question with offered answers has a box.");
        Assert.Contains(CandidateWhy, first.GetProperty("foldText").GetString()!);
        Assert.Contains("FICT-TULMSORN-3002.SLDDRW", first.GetProperty("foldText").GetString()!);
        Assert.Equal(0, first.GetProperty("injected").GetInt32());
    }

    // ---- the governing questions --------------------------------------------------------------

    /// <summary>A governing question offers each drawing by its file name, then "They all apply".</summary>
    [Fact]
    public void AGoverningQuestionOffersTheDrawingsByFileNameThenTheyAllApply()
    {
        JsonElement second = Scripted.Value.Second;

        Assert.Equal("Question 2 of 3", second.GetProperty("position").GetString());
        Assert.Equal(GoverningQuestion, second.GetProperty("question").GetString());
        Assert.Equal(GoverningOptions, ReviewPageDriver.Strings(second, "options"));
        Assert.Equal(JsonValueKind.Null, second.GetProperty("blocks").ValueKind);
        Assert.Equal(
            "About: FICT-TULMKALO-3001.SLDPRT, FICT-TULMKALO-3001.SLDDRW, FICT-TULMKALO-3001-B.SLDDRW",
            second.GetProperty("about").GetString());
        Assert.Contains(GoverningWhy, second.GetProperty("foldText").GetString()!);
    }

    /// <summary>
    /// With more drawings than buttons, the backend offers no answers: the page gives the one text
    /// box, and prints the question - its stem shortened with an ellipsis - as it was sent.
    /// </summary>
    [Fact]
    public void AGoverningQuestionWithNoOfferedAnswersHasABoxAndItsShortenedQuestionIsPrintedAsSent()
    {
        JsonElement third = Scripted.Value.Third;

        Assert.Equal("Question 3 of 3", third.GetProperty("position").GetString());
        Assert.Equal(ShortenedQuestion, third.GetProperty("question").GetString());
        Assert.True(third.GetProperty("hasBox").GetBoolean(), "a question with no offered answers has no box.");
        Assert.Empty(ReviewPageDriver.Strings(third, "options"));
    }

    // ---- the confirmation (part B) ------------------------------------------------------------

    /// <summary>
    /// Confirming the candidate and choosing "They all apply" posts one submission to 008's batch
    /// route, the two answers in the summary's order and each the offered words exactly - the
    /// backend's trigger is an equality - and nothing for the skipped question.
    /// </summary>
    [Fact]
    public void ConfirmingTheCandidateSendsTheOfferedWordsExactlyInOneSubmission()
    {
        JsonElement[] posts = Scripted.Value.SentCalls
            .Where(call => call.GetProperty("method").GetString() == "POST")
            .ToArray();

        JsonElement post = Assert.Single(posts);
        Assert.Equal("/sessions/chat-1/evidence", post.GetProperty("path").GetString());

        JsonElement[] answers = JsonDocument.Parse(post.GetProperty("body").GetString()!).RootElement
            .GetProperty("answers").EnumerateArray().ToArray();
        Assert.Equal(new[] { QuestionIds[0], QuestionIds[1] }, answers.Select(a => a.GetProperty("request_id").GetString()).ToArray());
        Assert.True(
            string.Equals(CandidateConfirm, answers[0].GetProperty("answer").GetString(), StringComparison.Ordinal),
            "the confirmation was not sent as the offered words: " + answers[0].GetProperty("answer").GetString());
        Assert.True(
            string.Equals("They all apply", answers[1].GetProperty("answer").GetString(), StringComparison.Ordinal),
            "the governing answer was not sent as the offered words.");
    }

    /// <summary>
    /// What the confirmed open did is the backend's coverage, and the page prints it verbatim, in
    /// the order it arrived within each bucket: read and closed, read as it stood, and the
    /// not-validated sentence the switch answers while it is off.
    /// </summary>
    [Fact]
    public void TheConfirmedOpensOutcomesArePrintedVerbatimInTheBackendsOrder()
    {
        JsonElement coverage = Scripted.Value.Coverage;

        Assert.Equal(
            TurnCoverage.Where(row => row.Bucket == "checked").Select(Line).ToArray(),
            ReviewPageDriver.Strings(coverage, "checked"));
        Assert.Equal(
            TurnCoverage.Where(row => row.Bucket == "unresolved").Select(Line).ToArray(),
            ReviewPageDriver.Strings(coverage, "unresolved"));
        Assert.Equal(
            TurnCoverage.Where(row => row.Bucket == "skipped").Select(Line).ToArray(),
            ReviewPageDriver.Strings(coverage, "skipped"));
        Assert.Equal(0, coverage.GetProperty("injected").GetInt32());
    }

    /// <summary>
    /// Once the backend stops listing the answered questions, the panel asks only what is still
    /// open - the skipped governing question - because which requests are open is the backend's
    /// to say.
    /// </summary>
    [Fact]
    public void AfterTheTurnThePanelAsksOnlyWhatTheBackendStillLists()
    {
        JsonElement after = Scripted.Value.AfterTurn;

        Assert.Equal("Question 1 of 1", after.GetProperty("position").GetString());
        Assert.Equal(ShortenedQuestion, after.GetProperty("question").GetString());
    }

    /// <summary>
    /// No script the Review page loads names the candidate answer, the `drawing.read` command, a
    /// drawing check or a drawing tool: what an answer means is decided once, in the backend.
    /// </summary>
    [Theory]
    [InlineData("open it read-only")]
    [InlineData("They all apply")]
    [InlineData("drawing.read")]
    [InlineData("drawing.context")]
    [InlineData("drawing.confirmed_open")]
    [InlineData("check_drawings")]
    [InlineData("get_drawing_brief")]
    public void NoScriptTheReviewPageLoadsRecognisesADrawingAnswerOrCommand(string word)
    {
        foreach (var script in ReviewPageFiles.Scripts().Concat(SharedScripts()))
        {
            Assert.True(
                script.Value.IndexOf(word, StringComparison.OrdinalIgnoreCase) < 0,
                script.Key + " names '" + word + "'; the page prints the backend's words and recognises none.");
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
                await driver.RouteAttention("chat-1", SummarySample.Json(summary => Ask(summary, 0, 1, 2)));
                await driver.StartReview();
                await driver.EndSession("chat-1");
                run.First = await driver.Read(ReadPanel);
                run.Second = await driver.Read(Press("question-next") + ReadPanel);
                run.Third = await driver.Read(Press("question-next") + ReadPanel);

                // Skip the third, go back, choose "They all apply" on the second and confirm the first.
                await driver.Read(Press("question-skip") + Press("question-previous") + Option(2)
                    + Press("question-previous") + Option(0) + "return JSON.stringify({ok: true});");

                await driver.Route("POST", "/sessions/chat-1/evidence", 202, "{}");
                await driver.ClearCalls();
                await driver.Read(Press("question-send") + "return JSON.stringify({ok: true});");
                await driver.Settle();
                run.SentCalls = await driver.Calls();

                // The resumed turn: the backend opened, read and closed before resuming, and says
                // so in coverage; the answered questions are no longer open.
                int seq = 10;
                foreach ((string bucket, string check, string reason) in TurnCoverage)
                {
                    await driver.Push("chat-1", seq++, "coverage", JsonSerializer.Serialize(new
                    {
                        bucket,
                        item = new { check, status = bucket, reason },
                    }));
                }

                await driver.RouteAttention("chat-1", SummarySample.Json(summary => Ask(summary, 2)));
                await driver.EndSession("chat-1");
                run.Coverage = await driver.Read(ReadCoverage);
                run.AfterTurn = await driver.Read(ReadPanel);
            });

        return run;
    }

    /// <summary>The summary's questions replaced by the drawing questions at these indexes.</summary>
    private static void Ask(JsonObject summary, params int[] indexes)
    {
        var items = new JsonArray();
        foreach (int index in indexes)
        {
            items.Add(JsonNode.Parse(JsonSerializer.Serialize(Questions()[index])));
        }

        summary["questions"] = new JsonObject
        {
            ["count"] = indexes.Length,
            ["text"] = indexes.Length == 1 ? "1 question for you" : indexes.Length + " questions for you",
            ["items"] = items,
        };
    }

    /// <summary>The three drawing questions as `summary.questions.items` carries them (009 contracts/questions.md).</summary>
    private static object[] Questions() => new object[]
    {
        new
        {
            id = QuestionIds[0],
            question = CandidateQuestion,
            options = CandidateOptions,
            blocks = "drawing.manufacturing_inputs",
            blocks_title = "Drawings",
            what = "Same-name drawings beside reviewed files: FICT-TULMSORN-3002.SLDDRW",
            why = CandidateWhy,
            about = new object[] { new { id = "doc:0003", name = "FICT-TULMSORN-3002.SLDPRT" } },
        },
        new
        {
            id = QuestionIds[1],
            question = GoverningQuestion,
            options = GoverningOptions,
            blocks = (string?)null,
            blocks_title = (string?)null,
            what = "doc:0006 FICT-TULMKALO-3001.SLDDRW, doc:0007 FICT-TULMKALO-3001-B.SLDDRW",
            why = GoverningWhy,
            about = new object[]
            {
                new { id = "doc:0002", name = "FICT-TULMKALO-3001.SLDPRT" },
                new { id = "doc:0006", name = "FICT-TULMKALO-3001.SLDDRW" },
                new { id = "doc:0007", name = "FICT-TULMKALO-3001-B.SLDDRW" },
            },
        },
        new
        {
            id = QuestionIds[2],
            question = ShortenedQuestion,
            options = new string[0],
            blocks = (string?)null,
            blocks_title = (string?)null,
            what = "doc:0011 to doc:0015, five drawings of FICT-OKTAKALO-5001",
            why = GoverningWhy,
            about = new object[] { new { id = "doc:0010", name = "FICT-OKTAKALO-5001.SLDPRT" } },
        },
    };

    /// <summary>A coverage line as `render.coverageBucket` writes it: "check - reason".</summary>
    private static string Line((string Bucket, string Check, string Reason) row) => row.Check + " - " + row.Reason;

    /// <summary>The shared scripts the Review page's index.html loads beside its own.</summary>
    private static KeyValuePair<string, string>[] SharedScripts() =>
        Directory.GetFiles(Path.Combine(ReviewPageFiles.WebFolder, "shared"), "*.js")
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => new KeyValuePair<string, string>("shared/" + Path.GetFileName(path), File.ReadAllText(path)))
            .ToArray();

    private static string Press(string action) =>
        "document.querySelector('#questions [data-action=\"" + action + "\"]').click();";

    private static string Option(int index) =>
        "document.querySelectorAll('#questions [data-action=\"question-option\"]')[" + index + "].click();";

    private const string ReadPanel = @"
var section = document.getElementById('questions');
var fold = section.querySelector('.question-fold');
return JSON.stringify({
  ok: true,
  hidden: !!section.hidden,
  position: h.text(section, '.question-position'),
  question: h.text(section, '.question-text'),
  blocks: h.text(section, '.question-blocks'),
  about: h.text(section, '.question-about'),
  options: h.texts(section, '[data-action=""question-option""]'),
  hasBox: !!section.querySelector('.question-answer'),
  foldText: fold ? fold.textContent : '',
  injected: h.injected(section)
});";

    private const string ReadCoverage = @"
var panel = document.getElementById('coverage-panel');
return JSON.stringify({
  ok: true,
  checked: h.texts(panel, '.bucket-checked .bucket-item'),
  unresolved: h.texts(panel, '.bucket-unresolved .bucket-item'),
  skipped: h.texts(panel, '.bucket-skipped .bucket-item'),
  injected: h.injected(panel)
});";

    private sealed class Run
    {
        public JsonElement First { get; set; }

        public JsonElement Second { get; set; }

        public JsonElement Third { get; set; }

        public JsonElement[] SentCalls { get; set; } = new JsonElement[0];

        public JsonElement Coverage { get; set; }

        public JsonElement AfterTurn { get; set; }
    }
}
