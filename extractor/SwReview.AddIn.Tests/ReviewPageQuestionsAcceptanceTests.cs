using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T045 - the US4 acceptance, written after the page and the backend and passing
/// with no further production code: the big-assembly review (<see cref="ReviewFixture"/>) with
/// three of its open requests given the short form by the harness, standing in for a backend
/// whose model asked them that way.
///
/// The Independent Test: "Question 1 of 3" above Start here; answering two and skipping one
/// posts one submission carrying two answers (SC-004's page half); the resume sentence - the
/// backend's, with the figure the run measured - was on screen before Send; and the summary the
/// backend answers after the resumed turn still lists the skipped question, because skipping
/// sends nothing.
/// </summary>
public sealed class ReviewPageQuestionsAcceptanceTests
{
    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    [Fact]
    public void TheFirstOfThreeQuestionsIsAskedAboveStartHere()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal("Question 1 of 3", first.GetProperty("position").GetString());
        Assert.Equal("Which vault version of the assembly was reviewed?", first.GetProperty("question").GetString());
        Assert.Equal("Blocks: Hygiene", first.GetProperty("blocks").GetString());
        Assert.True(first.GetProperty("afterSummary").GetBoolean(), "the questions must come after the summary.");
        Assert.True(first.GetProperty("beforeAttention").GetBoolean(), "the questions must come before Start here.");
    }

    /// <summary>The cost of resuming was said before Send was pressed, in the backend's words.</summary>
    [Fact]
    public void TheResumeSentenceIsShownBeforeSend()
    {
        string expected = ReviewFixture.Value.Summary.GetProperty("resume_text").GetString()!;

        Assert.StartsWith("Sending resumes the review once. Its last round sent ", expected);
        Assert.Equal(expected, Scripted.Value.BeforeSend.GetProperty("resume").GetString());
        Assert.False(Scripted.Value.BeforeSend.GetProperty("sendDisabled").GetBoolean(), "Send stayed disabled with two answers.");
    }

    /// <summary>Two answered, one skipped: one POST, two answers, in the summary's order, trimmed.</summary>
    [Fact]
    public void AnsweringTwoAndSkippingOnePostsOneSubmissionWithTwoAnswers()
    {
        JsonElement post = Assert.Single(Scripted.Value.SentCalls, call => call.GetProperty("method").GetString() == "POST");
        Assert.Equal("/sessions/" + ReviewFixture.ChatId + "/evidence", post.GetProperty("path").GetString());

        JsonElement[] answers = JsonDocument.Parse(post.GetProperty("body").GetString()!).RootElement
            .GetProperty("answers").EnumerateArray().ToArray();
        Assert.Equal(new[] { "ER-001", "ER-002" }, answers.Select(answer => answer.GetProperty("request_id").GetString()).ToArray());
        Assert.Equal(new[] { "Latest released", "12 mm" }, answers.Select(answer => answer.GetProperty("answer").GetString()).ToArray());
    }

    /// <summary>The skipped question is still asked once the backend answers again.</summary>
    [Fact]
    public void TheSummaryAnsweredNextStillListsTheSkippedQuestion()
    {
        JsonElement after = Scripted.Value.AfterTurn;

        Assert.Equal("Question 1 of 1", after.GetProperty("position").GetString());
        Assert.Equal("Should the three parts that were not loaded be resolved and reviewed again?", after.GetProperty("question").GetString());
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static Run Drive()
    {
        var run = new Run();
        ReviewFixture fixture = ReviewFixture.Value;

        ReviewPageDriver.Run(
            fixture.Configure,
            async driver =>
            {
                await fixture.Review(driver, fixture.RankingJson(summary => AskInShortForm(summary, 3)));
                run.First = await driver.Read(ReadPanel);

                await driver.Read(Option(0) + Press("question-next") + Type("  12 mm  ") + Press("question-next")
                    + Press("question-skip") + "return JSON.stringify({ok: true});");
                run.BeforeSend = await driver.Read(ReadPanel);

                await driver.Route("POST", "/sessions/" + ReviewFixture.ChatId + "/evidence", 202, "{}");
                await driver.ClearCalls();
                await driver.Read(Press("question-send") + "return JSON.stringify({ok: true});");
                await driver.Settle();
                run.SentCalls = await driver.Calls();

                // The resumed turn ends; the backend recorded the two answers, so it now lists
                // only the skipped request.
                await driver.RouteAttention(ReviewFixture.ChatId, fixture.RankingJson(summary => AskOnlyTheSkipped(summary)));
                await driver.EndSession(ReviewFixture.ChatId);
                run.AfterTurn = await driver.Read(ReadPanel);
            });

        return run;
    }

    /// <summary>The fixture's first <paramref name="count"/> open requests, given the short form.</summary>
    private static void AskInShortForm(JsonObject summary, int count)
    {
        JsonArray items = summary["questions"]!["items"]!.AsArray();
        var asked = new JsonArray();
        for (int index = 0; index < count; index++)
        {
            JsonObject item = JsonNode.Parse(items[index]!.ToJsonString())!.AsObject();
            (string question, string[] options, string blocks, string title) = ShortForms[index];
            item["question"] = question;
            item["options"] = JsonNode.Parse(JsonSerializer.Serialize(options));
            item["blocks"] = blocks;
            item["blocks_title"] = title;
            asked.Add(item);
        }

        summary["questions"] = new JsonObject
        {
            ["count"] = count,
            ["text"] = count + " questions for you",
            ["items"] = asked,
        };
    }

    private static void AskOnlyTheSkipped(JsonObject summary)
    {
        AskInShortForm(summary, 3);
        JsonNode skipped = summary["questions"]!["items"]![2]!;
        summary["questions"] = new JsonObject
        {
            ["count"] = 1,
            ["text"] = "1 question for you",
            ["items"] = new JsonArray(JsonNode.Parse(skipped.ToJsonString())),
        };
    }

    private static readonly (string Question, string[] Options, string Blocks, string Title)[] ShortForms =
    {
        ("Which vault version of the assembly was reviewed?", new[] { "Latest released", "Work in progress" }, "provenance", "Hygiene"),
        ("What is the usable thread depth of the two tapped holes?", new string[0], "fasteners", "Fasteners"),
        ("Should the three parts that were not loaded be resolved and reviewed again?", new[] { "Yes", "No" }, "interference", "Interference"),
    };

    private static string Press(string action) =>
        "document.querySelector('#questions [data-action=\"" + action + "\"]').click();";

    private static string Option(int index) =>
        "document.querySelectorAll('#questions [data-action=\"question-option\"]')[" + index + "].click();";

    private static string Type(string text) =>
        "var box = document.querySelector('#questions .question-answer'); box.value = " + JsonSerializer.Serialize(text)
        + "; box.dispatchEvent(new Event('input', { bubbles: true }));";

    private const string ReadPanel = @"
var section = document.getElementById('questions');
var send = section.querySelector('[data-action=""question-send""]');
return JSON.stringify({
  ok: true,
  afterSummary: h.before(document.getElementById('summary'), section),
  beforeAttention: h.before(section, document.getElementById('attention-panel')),
  position: h.text(section, '.question-position'),
  question: h.text(section, '.question-text'),
  blocks: h.text(section, '.question-blocks'),
  resume: h.text(section, '.question-resume'),
  sendDisabled: send ? send.disabled : null
});";

    private sealed class Run
    {
        public JsonElement First { get; set; }

        public JsonElement BeforeSend { get; set; }

        public JsonElement[] SentCalls { get; set; } = new JsonElement[0];

        public JsonElement AfterTurn { get; set; }
    }
}
