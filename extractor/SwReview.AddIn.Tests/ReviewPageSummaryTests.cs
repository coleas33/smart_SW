using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T024: the summary at the top of Results (User Story 3, FR-007 to FR-009,
/// contracts/review-summary.md section 5).
///
/// <b>What is under test is a printer.</b> The backend counts the findings into Decide, Fix and
/// Verify by the policy's own keys, states each check goal and writes every word; the page
/// prints what it was given, in the order it was given, and computes nothing (FR-009). So the
/// sample's numbers are ones no page could have derived from the ranking beside them, and the
/// assertions are the sample's own strings, in its order.
///
/// <b>Driven, not scanned</b>, because the summary arrives the way the ranking does - read from
/// `GET /sessions/{chat_id}/attention` once the session ends - and "a second ranking replaces the
/// block" and "an older backend shows nothing" are both things only a page that fetched twice
/// can show. One boot, one scripted run, read by every test below (<see cref="ReviewPageDriver"/>).
/// </summary>
public sealed class ReviewPageSummaryTests
{
    /// <summary>A drawing line that carries markup: the backend's text travels verbatim, so this is characters.</summary>
    private const string HostileDrawings = "<img src=x onerror=alert(3)><script>alert(4)</script> 2 drawings read";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    [Fact]
    public void TheSummaryIsShownBeforeStartHereOnceTheSessionEnds()
    {
        JsonElement first = Scripted.Value.First;

        Assert.False(first.GetProperty("hidden").GetBoolean(), "#summary stayed hidden.");
        Assert.True(first.GetProperty("rendered").GetBoolean(), "#summary is not on screen.");
        Assert.True(first.GetProperty("beforePanel").GetBoolean(), "#summary must come before #attention-panel.");
        Assert.Equal("function", first.GetProperty("exported").GetString());
    }

    /// <summary>
    /// The block reads in the order of the Independent Test: the headline, the three groups
    /// (and decided, which the backend sent because it is non-zero), the questions, the parts not
    /// loaded, the one line about drawings (T086, edited deliberately: the owner's decision 10A),
    /// then one line per goal.
    /// </summary>
    [Fact]
    public void TheSummaryReadsTheHeadlineTheGroupsTheQuestionsTheMissingPartsAndTheGoalsInOrder()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal(
            new[] { "summary-headline", "summary-groups", "summary-questions", "summary-not-loaded", "summary-drawings", "summary-goals" },
            ReviewPageDriver.Strings(first, "children"));
        Assert.Equal(SummarySample.Headline, first.GetProperty("headline").GetString());
        Assert.Equal(SummarySample.QuestionsText, first.GetProperty("questions").GetString());
        Assert.Equal(SummarySample.NotLoadedText, first.GetProperty("notLoaded").GetString());
    }

    /// <summary>
    /// Feature 009 T086 (the owner's decision 10A): the summary's one line about drawings is the
    /// backend's text, printed as sent - the page counts no drawing and composes no word of it.
    /// </summary>
    [Fact]
    public void TheDrawingLineIsTheBackendsTextPrintedVerbatim()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal(SummarySample.DrawingsText, first.GetProperty("drawings").GetString());
        Assert.Equal(1, first.GetProperty("drawingLines").GetInt32());
    }

    /// <summary>The backend's line is characters, never an element or a handler (FR-029).</summary>
    [Fact]
    public void AHostileDrawingLineRendersAsLiteralTextAndAddsNoElement()
    {
        JsonElement hostile = Scripted.Value.HostileDrawings;

        Assert.Equal(HostileDrawings, hostile.GetProperty("drawings").GetString());
        Assert.Equal(0, hostile.GetProperty("injected").GetInt32());
        Assert.Equal(0, hostile.GetProperty("handlers").GetInt32());
    }

    /// <summary>
    /// No drawing line where the backend sent none: `drawings` null - as the zero-findings summary
    /// sends it - and a summary with no `drawings` member at all, from a backend older than the
    /// line, both leave the block exactly as it was before it.
    /// </summary>
    [Fact]
    public void ANullOrAbsentDrawingLineRendersNothing()
    {
        JsonElement older = Scripted.Value.Older;

        Assert.Equal(0, Scripted.Value.Second.GetProperty("drawingLines").GetInt32());
        Assert.Equal(0, older.GetProperty("drawingLines").GetInt32());
        Assert.Equal(
            new[] { "summary-headline", "summary-groups", "summary-questions", "summary-not-loaded", "summary-goals" },
            ReviewPageDriver.Strings(older, "children"));
        Assert.Equal(SummarySample.Headline, older.GetProperty("headline").GetString());
    }

    [Fact]
    public void EachGroupPrintsItsLabelItsSentenceAndItsGoalsAsTheBackendSentThem()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal(
            SummarySample.Groups.Select(group => "summary-group group-" + group.Kind).ToArray(),
            ReviewPageDriver.Strings(first, "groupClasses"));
        Assert.Equal(SummarySample.Groups.Select(group => group.Label).ToArray(), ReviewPageDriver.Strings(first, "groupLabels"));
        Assert.Equal(SummarySample.Groups.Select(group => group.Text).ToArray(), ReviewPageDriver.Strings(first, "groupTexts"));
        Assert.Equal(
            SummarySample.Groups.Select(group => string.Join("|", group.Goals)).ToArray(),
            ReviewPageDriver.Strings(first, "groupGoals"));
    }

    /// <summary>
    /// One line per goal - its title, its state in words and the few words of its reason - with
    /// the recorded sentence behind a shut fold, and nothing behind a fold where none was sent.
    /// </summary>
    [Fact]
    public void EachGoalLinePrintsItsStateAndReasonWithTheRecordedSentenceInAShutFold()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal(
            SummarySample.Goals.Select(goal => "summary-goal goal-" + goal.State).ToArray(),
            ReviewPageDriver.Strings(first, "goalClasses"));
        Assert.Equal(SummarySample.Goals.Select(goal => goal.Title).ToArray(), ReviewPageDriver.Strings(first, "goalTitles"));
        Assert.Equal(SummarySample.Goals.Select(goal => goal.Label).ToArray(), ReviewPageDriver.Strings(first, "goalStates"));
        Assert.Equal(SummarySample.Goals.Select(goal => goal.Reason ?? string.Empty).ToArray(), ReviewPageDriver.Strings(first, "goalReasons"));
        Assert.Equal(SummarySample.Goals.Select(goal => goal.Detail ?? string.Empty).ToArray(), ReviewPageDriver.Strings(first, "goalDetails"));
        Assert.Equal(
            SummarySample.Goals.Select(goal => goal.Detail == null ? "none" : "shut").ToArray(),
            ReviewPageDriver.Strings(first, "goalFolds"));
    }

    /// <summary>A recorded sentence is written by the model: it is characters, never an element (FR-029).</summary>
    [Fact]
    public void AHostileRecordedSentenceRendersAsLiteralTextAndAddsNoElement()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Contains(SummarySample.HostileDetail, first.GetProperty("text").GetString()!);
        Assert.Equal(0, first.GetProperty("injected").GetInt32());
        Assert.Equal(0, first.GetProperty("handlers").GetInt32());
    }

    /// <summary>
    /// The summary is a result like any other: another document hides it (U8), and the
    /// reviewed document coming back shows it again.
    /// </summary>
    [Fact]
    public void AnotherDocumentHidesTheSummaryAndTheReviewedOneBringsItBack()
    {
        Assert.False(Scripted.Value.Stale.GetProperty("rendered").GetBoolean(), "the summary survived another document.");
        Assert.True(Scripted.Value.Back.GetProperty("rendered").GetBoolean(), "the summary did not come back.");
    }

    /// <summary>
    /// A second ranking for the same chat - the end of a follow-up turn - replaces the block
    /// rather than stacking a second one under it; a review that recorded nothing says so in the
    /// backend's words, with the three groups at zero and every goal line still there.
    /// </summary>
    [Fact]
    public void ASecondRankingReplacesTheBlockAndAnEmptyReviewStillListsEveryGoal()
    {
        JsonElement second = Scripted.Value.Second;

        Assert.Equal(1, second.GetProperty("blocks").GetInt32());
        Assert.Equal("No findings were recorded", second.GetProperty("headline").GetString());
        Assert.Equal(
            new[] { "0 need your decision", "0 to fix", "0 to verify" },
            ReviewPageDriver.Strings(second, "groupTexts"));
        Assert.Equal(SummarySample.Goals.Length, ReviewPageDriver.Strings(second, "goalTitles").Length);
        Assert.Equal(JsonValueKind.Null, second.GetProperty("questions").ValueKind);
        Assert.Equal(JsonValueKind.Null, second.GetProperty("notLoaded").ValueKind);
    }

    /// <summary>
    /// FR-030: a ranking from a backend that sends no summary renders exactly as before this
    /// feature - no block, no empty section taking room, and Start here where it always was.
    /// </summary>
    [Fact]
    public void ARankingWithNoSummaryShowsNoBlockAndLeavesStartHereWhereItWas()
    {
        JsonElement none = Scripted.Value.NoSummary;

        Assert.True(none.GetProperty("hidden").GetBoolean(), "#summary is shown with no summary.");
        Assert.False(none.GetProperty("rendered").GetBoolean(), "#summary takes room with no summary.");
        Assert.Equal(0, none.GetProperty("blocks").GetInt32());
        Assert.True(none.GetProperty("panelShown").GetBoolean(), "Start here was not shown.");
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
                await driver.EndSession("chat-1");
                run.First = await driver.Read(ReadSummary);

                await driver.DocumentChanged(new { path = @"C:\parts\other.SLDPRT", configuration = "Default" });
                run.Stale = await driver.Read(ReadSummary);
                await driver.DocumentChanged(new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" });
                run.Back = await driver.Read(ReadSummary);

                await driver.RouteAttention("chat-1", SummarySample.EmptyJson());
                await driver.EndSession("chat-1");
                run.Second = await driver.Read(ReadSummary);

                // A backend older than the drawing line sends no `drawings` member at all.
                await driver.RouteAttention("chat-1", SummarySample.Json(summary => summary.Remove("drawings")));
                await driver.EndSession("chat-1");
                run.Older = await driver.Read(ReadSummary);

                await driver.RouteAttention(
                    "chat-1", SummarySample.Json(summary => summary["drawings"] = new JsonObject { ["text"] = HostileDrawings }));
                await driver.EndSession("chat-1");
                run.HostileDrawings = await driver.Read(ReadSummary);

                await driver.StartReview();
                await driver.RouteAttention("chat-2", AttentionSample.Json());
                await driver.EndSession("chat-2");
                run.NoSummary = await driver.Read(ReadSummary);
            });

        return run;
    }

    private const string ReadSummary = @"
var section = document.getElementById('summary');
var panel = document.getElementById('attention-panel');
var block = section.querySelector('.summary');
var groups = section.querySelectorAll('.summary-group');
var goals = section.querySelectorAll('.summary-goal');

var groupGoals = [];
for (var i = 0; i < groups.length; i++) { groupGoals.push(h.texts(groups[i], '.group-goal').join('|')); }

var goalReasons = [], goalDetails = [], goalFolds = [];
for (var j = 0; j < goals.length; j++) {
  goalReasons.push(h.text(goals[j], '.goal-reason') || '');
  var fold = goals[j].querySelector('details');
  goalDetails.push(fold ? (h.text(fold, '.goal-detail') || '') : '');
  goalFolds.push(fold ? (fold.open ? 'open' : 'shut') : 'none');
}

var handlers = 0;
var all = section.getElementsByTagName('*');
for (var k = 0; k < all.length; k++) {
  for (var a = 0; a < all[k].attributes.length; a++) { if (/^on/i.test(all[k].attributes[a].name)) { handlers++; } }
}

return JSON.stringify({
  ok: true,
  hidden: !!section.hidden,
  rendered: h.rendered(section),
  beforePanel: h.before(section, panel),
  panelShown: !panel.hidden,
  blocks: section.querySelectorAll('.summary').length,
  children: h.children(block),
  headline: h.text(section, '.summary-headline'),
  groupClasses: Array.prototype.map.call(groups, function (g) { return g.className; }),
  groupLabels: h.texts(section, '.summary-group .group-label'),
  groupTexts: h.texts(section, '.summary-group .group-text'),
  groupGoals: groupGoals,
  questions: h.text(section, '.summary-questions'),
  notLoaded: h.text(section, '.summary-not-loaded'),
  drawings: h.text(section, '.summary-drawings'),
  drawingLines: section.querySelectorAll('.summary-drawings').length,
  goalClasses: Array.prototype.map.call(goals, function (g) { return g.className; }),
  goalTitles: h.texts(section, '.summary-goal .goal-title'),
  goalStates: h.texts(section, '.summary-goal .goal-state'),
  goalReasons: goalReasons,
  goalDetails: goalDetails,
  goalFolds: goalFolds,
  text: section.textContent,
  injected: h.injected(section),
  handlers: handlers,
  exported: typeof (window.SwReviewRender || {}).summaryBlock
});";

    private sealed class Run
    {
        public JsonElement First { get; set; }

        public JsonElement Stale { get; set; }

        public JsonElement Back { get; set; }

        public JsonElement Second { get; set; }

        public JsonElement Older { get; set; }

        public JsonElement HostileDrawings { get; set; }

        public JsonElement NoSummary { get; set; }
    }
}
