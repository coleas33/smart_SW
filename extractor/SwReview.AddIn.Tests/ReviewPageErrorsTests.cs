using System;
using System.Collections.Generic;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T070: errors say what to do next (FR-026, contracts/plain-words.md section 5).
///
/// The Review tab printed "TurnRunning: a turn is already running for chat-1" - an error class
/// is a name in the code, and the message after it was written for whoever reads a log. With the
/// backend's labels the page prints one sentence per class that says what the engineer can do
/// (`labels.errors`), with the class and the message behind a fold where they are still one press
/// away. A class the labels do not name prints its message; with no labels at all - an older
/// backend - every surface reads exactly as it did before this feature (FR-030).
/// </summary>
public sealed class ReviewPageErrorsTests
{
    private const string TurnRunningMessage = "a turn is already running for chat-1";

    private const string NoDocumentMessage = "open the assembly or part you want reviewed in SOLIDWORKS first.";

    private const string SaveMessage = "model must not be blank";

    private static readonly Lazy<Run> Labelled = new Lazy<Run>(() => Drive(withLabels: true));

    private static readonly Lazy<Run> Unlabelled = new Lazy<Run>(() => Drive(withLabels: false));

    [Fact]
    public void AnErrorEventShowsItsLabelWithTheClassAndMessageOnlyInsideTheCardsFold()
    {
        JsonElement card = Labelled.Value.TurnRunningCard;

        Assert.Contains(LabelsSample.TurnRunning, card.GetProperty("visible").GetString()!);
        Assert.DoesNotContain("TurnRunning", card.GetProperty("visible").GetString()!);
        Assert.DoesNotContain(TurnRunningMessage, card.GetProperty("visible").GetString()!);
        Assert.Contains("TurnRunning", card.GetProperty("fold").GetString()!);
        Assert.Contains(TurnRunningMessage, card.GetProperty("fold").GetString()!);
        Assert.Equal("shut", card.GetProperty("foldState").GetString());
    }

    /// <summary>A refused start, a refused decision, a refused answer and a refused settings save each print their label, and no "Class: message".</summary>
    [Fact]
    public void EveryRefusalTheEngineerSeesPrintsItsLabelAndNoClassColonMessage()
    {
        Run run = Labelled.Value;

        Assert.Contains(LabelsSample.NoDocument, run.StartRefused.GetProperty("visible").GetString()!);
        Assert.DoesNotContain("NoDocument", run.StartRefused.GetProperty("visible").GetString()!);

        AssertPlain(run.DecisionRefused, LabelsSample.TurnRunning, "TurnRunning", TurnRunningMessage);
        AssertPlain(run.AnswerRefused, LabelsSample.AlreadyAnswered, "AlreadyAnswered", "the answer was refused");
        AssertPlain(run.SaveRefused, LabelsSample.InvalidSettings, "InvalidSettings", SaveMessage);
    }

    /// <summary>The sentence leads the visible text; the class and the message are in the fold and not beside it.</summary>
    private static void AssertPlain(JsonElement status, string label, string errorClass, string message)
    {
        string visible = status.GetProperty("visible").GetString()!.Trim();
        Assert.StartsWith(label, visible, StringComparison.Ordinal);
        Assert.DoesNotContain(errorClass, visible);
        Assert.DoesNotContain(message, visible);
        Assert.Contains(errorClass, status.GetProperty("fold").GetString()!);
        Assert.Contains(message, status.GetProperty("fold").GetString()!);
    }

    [Fact]
    public void AClassTheLabelsDoNotNamePrintsItsMessage()
    {
        JsonElement card = Labelled.Value.UnlabelledCard;

        Assert.Contains("the provider refused the request", card.GetProperty("visible").GetString()!);
        Assert.DoesNotContain("ProviderError", card.GetProperty("visible").GetString()!);
        Assert.Contains("ProviderError", card.GetProperty("fold").GetString()!);
    }

    /// <summary>FR-030: with no labels every surface prints what it printed before this feature.</summary>
    [Fact]
    public void WithNoLabelsEverySurfaceReadsAsBefore()
    {
        Run run = Unlabelled.Value;

        Assert.Equal("TurnRunning", run.TurnRunningCard.GetProperty("chip").GetString());
        Assert.Equal(TurnRunningMessage, run.TurnRunningCard.GetProperty("message").GetString());
        Assert.Equal("NoDocument", run.StartRefused.GetProperty("chip").GetString());
        Assert.Equal("TurnRunning: " + TurnRunningMessage, run.DecisionRefused.GetProperty("text").GetString());
        Assert.Equal("the answer was refused", run.AnswerRefused.GetProperty("text").GetString());
        Assert.Equal("InvalidSettings: " + SaveMessage, run.SaveRefused.GetProperty("text").GetString());
    }

    private static Run Drive(bool withLabels)
    {
        var run = new Run();

        ReviewPageDriver.Run(
            driver =>
            {
                if (withLabels)
                {
                    driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
                }
            },
            async driver =>
            {
                await driver.RouteAttention("chat-1", SummarySample.Json());
                await driver.StartReview();
                await driver.Push("chat-1", 1, "finding", Finding("F-001"));
                await driver.Push("chat-1", 2, "error",
                    JsonSerializer.Serialize(new { error_class = "TurnRunning", message = TurnRunningMessage, retryable = true }));
                await driver.Settle();
                run.TurnRunningCard = await driver.Read(LastErrorCard);

                await driver.Push("chat-1", 3, "error",
                    @"{""error_class"":""ProviderError"",""message"":""the provider refused the request"",""retryable"":false}");
                await driver.Settle();
                run.UnlabelledCard = await driver.Read(LastErrorCard);

                // A decision the backend refuses.
                await driver.EndSession("chat-1");
                await driver.Route("POST", "/sessions/chat-1/findings/F-001/disposition", 409,
                    JsonSerializer.Serialize(new { error_class = "TurnRunning", message = TurnRunningMessage, retryable = true }));
                await driver.Read("document.querySelector('.card.finding[data-finding-id=\"F-001\"] [data-action=\"accept\"]').click(); return JSON.stringify({ok: true});");
                await driver.Settle();
                run.DecisionRefused = await driver.Read(Status("document.querySelector('.card.finding[data-finding-id=\"F-001\"] .card-status')"));

                // Answers the backend refuses, naming no request.
                await driver.Route("POST", "/sessions/chat-1/evidence", 409,
                    @"{""error_class"":""AlreadyAnswered"",""message"":""the answer was refused"",""retryable"":false}");
                await driver.Read(
                    "document.querySelectorAll('#questions [data-action=\"question-option\"]')[0].click();"
                    + "document.querySelector('#questions [data-action=\"question-send\"]').click(); return JSON.stringify({ok: true});");
                await driver.Settle();
                run.AnswerRefused = await driver.Read(Status("document.querySelector('#questions .question-status')"));

                // A settings save the host refuses.
                driver.SettingsSaveError = new { error_class = "InvalidSettings", message = SaveMessage, retryable = false };
                await driver.Click("save-settings");
                run.SaveRefused = await driver.Read(Status("document.getElementById('save-state')"));

                // A start the host refuses.
                driver.ReviewStartError = new { error_class = "NoDocument", message = NoDocumentMessage, retryable = true };
                await driver.StartReview();
                run.StartRefused = await driver.Read(LastErrorCard);
            });

        return run;
    }

    private static string Finding(string id) => JsonSerializer.Serialize(new
    {
        id,
        check = "interference.static",
        title = "Finding " + id,
        status = "demonstrated",
        severity = "medium",
        component_ids = new[] { "cmp:0002" },
        observed = "Observed for " + id + ".",
    });

    private const string LastErrorCard = @"
var cards = document.querySelectorAll('#errors .card.error');
var card = cards[cards.length - 1];
var fold = card.querySelector('details');
return JSON.stringify({
  ok: true,
  visible: h.visibleText(card),
  fold: fold ? fold.textContent : '',
  foldState: fold ? (fold.open ? 'open' : 'shut') : 'none',
  chip: h.text(card, '.error-class'),
  message: h.text(card, '.message')
});";

    private static string Status(string locate) => @"
var node = " + locate + @";
var fold = node.querySelector('details');
return JSON.stringify({
  ok: true,
  visible: h.visibleText(node),
  fold: fold ? fold.textContent : '',
  text: node.textContent
});";

    private sealed class Run
    {
        public JsonElement TurnRunningCard { get; set; }

        public JsonElement UnlabelledCard { get; set; }

        public JsonElement DecisionRefused { get; set; }

        public JsonElement AnswerRefused { get; set; }

        public JsonElement SaveRefused { get; set; }

        public JsonElement StartRefused { get; set; }
    }
}
