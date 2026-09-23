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
/// <b>What the page is given is the backend's.</b> `Fixtures/review-drawing-questions.json` is
/// written by `reviewer/tests/fixtures/pane/generate_drawing_questions.py` from one scripted review
/// played through the real runner, `check_drawings`, session writer and bridge client, and a Python
/// test (`test_pane_drawing_fixture.py`) keeps it equal to a fresh generation (research R2.24):
/// the summary's three drawing questions - the candidate question, a governing question offering
/// the drawings by file name, and one whose stem the backend shortened and which offers nothing -
/// the engineer's batch, every coverage event of the review in the order the backend emitted it,
/// and the questions still open after the resumed turn. (The page lane first wrote these tests on
/// hand-built samples from the contract; at integration the backend's `what`, `about`, "read from"
/// lists and the bridge's wording of a host refusal differed from them, so the samples became the
/// backend's own output.)
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

    public const string FileName = "review-drawing-questions.json";

    private const string WriteCommand = "uv run python tests/fixtures/pane/generate_drawing_questions.py --write";

    private static readonly Lazy<JsonElement> Fixture = new Lazy<JsonElement>(ReadFixture);

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    private static JsonElement[] Asked => Items(Fixture.Value.GetProperty("questions_asked"));

    private static JsonElement[] OpenAfter => Items(Fixture.Value.GetProperty("questions_open_after"));

    private static (string RequestId, string Answer)[] Answers =>
        Fixture.Value.GetProperty("answers").EnumerateArray()
            .Select(pair => (pair[0].GetString()!, pair[1].GetString()!))
            .ToArray();

    /// <summary>Every `coverage` event body of the review, in the order the backend emitted it.</summary>
    private static JsonElement[] Coverage => Fixture.Value.GetProperty("coverage").EnumerateArray().ToArray();

    // ---- the fixture is the one these tests are about -----------------------------------------

    /// <summary>
    /// The backend's candidate question comes first and its first answer is, ordinal-equal, the
    /// word this page test pins; the page's trimming of answers cannot change it.
    /// </summary>
    [Fact]
    public void TheFixturesFirstQuestionIsTheCandidateQuestionAndItsFirstAnswerIsTheConfirmation()
    {
        Assert.Equal(3, Asked.Length);
        string first = Strings(Asked[0], "options")[0];
        Assert.True(string.Equals(CandidateConfirm, first, StringComparison.Ordinal), "the backend offers: " + first);
        Assert.Equal(first.Trim(), first);
        Assert.Equal(Answers[0], (Asked[0].GetProperty("id").GetString()!, CandidateConfirm));
    }

    // ---- the candidate question ---------------------------------------------------------------

    /// <summary>
    /// The candidate question in the backend's words: the three answers as buttons in the order
    /// offered, the goal it blocks, the reviewed files it is about, and the backend's `what` and
    /// `why` behind the fold.
    /// </summary>
    [Fact]
    public void TheCandidateQuestionIsAskedInTheBackendsWordsWithItsThreeAnswersInOrder()
    {
        JsonElement first = Scripted.Value.First;
        JsonElement asked = Asked[0];

        Assert.False(first.GetProperty("hidden").GetBoolean(), "#questions stayed hidden.");
        Assert.Equal("Question 1 of 3", first.GetProperty("position").GetString());
        Assert.Equal(asked.GetProperty("question").GetString(), first.GetProperty("question").GetString());
        Assert.Equal("Blocks: " + asked.GetProperty("blocks_title").GetString(), first.GetProperty("blocks").GetString());
        Assert.Equal(About(asked), first.GetProperty("about").GetString());
        Assert.Equal(Strings(asked, "options"), ReviewPageDriver.Strings(first, "options"));
        Assert.Equal(3, ReviewPageDriver.Strings(first, "options").Length);
        Assert.False(first.GetProperty("hasBox").GetBoolean(), "a question with offered answers has a box.");
        Assert.Contains(asked.GetProperty("why").GetString()!, first.GetProperty("foldText").GetString()!);
        Assert.Contains(asked.GetProperty("what").GetString()!, first.GetProperty("foldText").GetString()!);
        Assert.Equal(0, first.GetProperty("injected").GetInt32());
    }

    // ---- the governing questions --------------------------------------------------------------

    /// <summary>A governing question offers each drawing by its file name, then "They all apply".</summary>
    [Fact]
    public void AGoverningQuestionOffersTheDrawingsByFileNameThenTheyAllApply()
    {
        JsonElement second = Scripted.Value.Second;
        JsonElement asked = Asked[1];

        Assert.Equal("Question 2 of 3", second.GetProperty("position").GetString());
        Assert.Equal(asked.GetProperty("question").GetString(), second.GetProperty("question").GetString());
        Assert.Equal(Strings(asked, "options"), ReviewPageDriver.Strings(second, "options"));
        Assert.Equal("They all apply", ReviewPageDriver.Strings(second, "options").Last());
        Assert.Equal(JsonValueKind.Null, second.GetProperty("blocks").ValueKind);
        Assert.Equal(About(asked), second.GetProperty("about").GetString());
        Assert.Contains(asked.GetProperty("why").GetString()!, second.GetProperty("foldText").GetString()!);
        Assert.Contains(asked.GetProperty("what").GetString()!, second.GetProperty("foldText").GetString()!);
    }

    /// <summary>
    /// With more drawings than buttons, the backend offers no answers: the page gives the one text
    /// box, and prints the question - its stem shortened with an ellipsis - as it was sent.
    /// </summary>
    [Fact]
    public void AGoverningQuestionWithNoOfferedAnswersHasABoxAndItsShortenedQuestionIsPrintedAsSent()
    {
        JsonElement third = Scripted.Value.Third;
        string question = Asked[2].GetProperty("question").GetString()!;

        Assert.Contains("\u2026", question);
        Assert.Equal("Question 3 of 3", third.GetProperty("position").GetString());
        Assert.Equal(question, third.GetProperty("question").GetString());
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
        Assert.Equal(Answers.Select(pair => pair.RequestId).ToArray(), answers.Select(a => a.GetProperty("request_id").GetString()).ToArray());
        for (int index = 0; index < answers.Length; index++)
        {
            string? sent = answers[index].GetProperty("answer").GetString();
            Assert.True(
                string.Equals(Answers[index].Answer, sent, StringComparison.Ordinal),
                "an answer was not sent as the offered words: " + sent);
        }
    }

    /// <summary>
    /// What the review's checks and the confirmed opens found is the backend's coverage, and the
    /// page prints it verbatim, in the order it arrived within each bucket: the drawing context of
    /// each reviewed document, then each confirmed candidate - read and closed, refused while the
    /// seam is off (in the bridge's words), read as it stood. The checked bucket arrives out of
    /// sorted order, so a page that sorted it would fail here.
    /// </summary>
    [Fact]
    public void TheCoverageIsPrintedVerbatimInTheBackendsOrder()
    {
        JsonElement coverage = Scripted.Value.Coverage;

        foreach (string bucket in new[] { "checked", "unresolved", "skipped" })
        {
            string[] expected = Coverage
                .Where(row => row.GetProperty("bucket").GetString() == bucket)
                .Select(row => Line(row.GetProperty("item")))
                .ToArray();
            Assert.NotEmpty(expected);
            Assert.Equal(expected, ReviewPageDriver.Strings(coverage, bucket));
        }

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

        JsonElement open = Assert.Single(OpenAfter);
        Assert.Equal("Question 1 of 1", after.GetProperty("position").GetString());
        Assert.Equal(open.GetProperty("question").GetString(), after.GetProperty("question").GetString());
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
        string confirm = Answers[0].Answer;
        string governing = Answers[1].Answer;

        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.RouteAttention("chat-1", SummarySample.Json(summary => Ask(summary, "questions_asked")));
                await driver.StartReview();
                await driver.EndSession("chat-1");
                run.First = await driver.Read(ReadPanel);
                run.Second = await driver.Read(Press("question-next") + ReadPanel);
                run.Third = await driver.Read(Press("question-next") + ReadPanel);

                // Skip the third, go back, choose the batch's answer on the second and confirm the first.
                await driver.Read(Press("question-skip") + Press("question-previous") + Option(Asked[1], governing)
                    + Press("question-previous") + Option(Asked[0], confirm) + "return JSON.stringify({ok: true});");

                await driver.Route("POST", "/sessions/chat-1/evidence", 202, "{}");
                await driver.ClearCalls();
                await driver.Read(Press("question-send") + "return JSON.stringify({ok: true});");
                await driver.Settle();
                run.SentCalls = await driver.Calls();

                // The review's coverage as the backend emitted it, the confirmed opens last: the
                // backend opened, read and closed before resuming; the answered questions are no
                // longer open.
                int seq = 10;
                foreach (JsonElement row in Coverage)
                {
                    // One line per SSE frame: the fixture is indented, the frame's data is not.
                    await driver.Push("chat-1", seq++, "coverage", JsonSerializer.Serialize(row));
                }

                await driver.RouteAttention("chat-1", SummarySample.Json(summary => Ask(summary, "questions_open_after")));
                await driver.EndSession("chat-1");
                run.Coverage = await driver.Read(ReadCoverage);
                run.AfterTurn = await driver.Read(ReadPanel);
            });

        return run;
    }

    /// <summary>The summary's questions replaced by the fixture's block of that name.</summary>
    private static void Ask(JsonObject summary, string block) =>
        summary["questions"] = JsonNode.Parse(Fixture.Value.GetProperty(block).GetRawText());

    private static JsonElement ReadFixture()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "Fixtures", FileName);
        Assert.True(
            File.Exists(path),
            FileName + " was not copied next to the test assembly; check the Content item in the csproj, "
            + "and regenerate it with `" + WriteCommand + "` from reviewer/.");
        return JsonDocument.Parse(File.ReadAllText(path)).RootElement.Clone();
    }

    private static JsonElement[] Items(JsonElement block) => block.GetProperty("items").EnumerateArray().ToArray();

    private static string[] Strings(JsonElement element, string name) =>
        element.GetProperty(name).EnumerateArray().Select(item => item.GetString()!).ToArray();

    /// <summary>The about line as the panel writes it: "About: " and the names, comma separated.</summary>
    private static string About(JsonElement question) =>
        "About: " + string.Join(", ", question.GetProperty("about").EnumerateArray().Select(item => item.GetProperty("name").GetString()));

    /// <summary>
    /// A coverage line as `render.coverageBucket` writes it: "check - reason", then " [error]" when
    /// the item carries one (the refused read carries the bridge error's class).
    /// </summary>
    private static string Line(JsonElement item)
    {
        string line = item.GetProperty("check").GetString() + " - " + item.GetProperty("reason").GetString();
        JsonElement error = item.GetProperty("error");
        return error.ValueKind == JsonValueKind.Null ? line : line + " [" + error.GetString() + "]";
    }

    /// <summary>The shared scripts the Review page's index.html loads beside its own.</summary>
    private static KeyValuePair<string, string>[] SharedScripts() =>
        Directory.GetFiles(Path.Combine(ReviewPageFiles.WebFolder, "shared"), "*.js")
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => new KeyValuePair<string, string>("shared/" + Path.GetFileName(path), File.ReadAllText(path)))
            .ToArray();

    private static string Press(string action) =>
        "document.querySelector('#questions [data-action=\"" + action + "\"]').click();";

    /// <summary>
    /// Clicks the button of <paramref name="question"/> whose offered words are
    /// <paramref name="answer"/>: the test finds it by the backend's order, the page never does.
    /// </summary>
    private static string Option(JsonElement question, string answer)
    {
        int index = Array.IndexOf(Strings(question, "options"), answer);
        Assert.True(index >= 0, "'" + answer + "' is not one of the question's offered answers.");
        return "document.querySelectorAll('#questions [data-action=\"question-option\"]')[" + index + "].click();";
    }

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
