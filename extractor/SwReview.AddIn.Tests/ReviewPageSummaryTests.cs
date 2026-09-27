using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T024: the summary at the top of Results (User Story 3, FR-007 to FR-009,
/// contracts/review-summary.md section 5), as feature 013 T053 amends it (contracts/grouped-list.md
/// section 4): the headline, one tally line, the questions, the parts not loaded, the drawings,
/// the bought parts and one not-reached line. The Decide, Fix and Verify lines with their goal
/// counts and the goal lines left the summary: the tally says the kinds of action in one line, and
/// the goal lines sit under their groups (<see cref="ReviewPageAttentionPanelTests"/>).
///
/// <b>What is under test is a printer.</b> The backend counts the findings, states each check goal
/// and writes every word; the page prints what it was given, in the order it was given, and
/// computes nothing (FR-009). So the sample's numbers are ones no page could have derived from the
/// ranking beside them, and the assertions are the sample's own strings, in its order.
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

    /// <summary>A bought-parts line that carries markup, for the same reason.</summary>
    private const string HostileBoughtParts = "<img src=x onerror=alert(6)></p><script>alert(7)</script> 1 part not graded";

    /// <summary>A tally and a not-reached line that carry markup, for the same reason.</summary>
    private const string HostileTally = "<img src=x onerror=alert(13)>Decide 1";

    private const string HostileNotReached = "<script>alert(14)</script>Not reached: Fasteners";

    /// <summary>The drawings line while the seat opens no closed drawing, for one file (drawing-capability.md section 4).</summary>
    private const string InstructionOne = "Open FICT-0002.SLDDRW in SOLIDWORKS, then press Review again with FICT-0001.SLDASM active";

    /// <summary>The same for several files, named as a sentence names them.</summary>
    private const string InstructionMany =
        "Open FICT-0002.SLDDRW and FICT-0003.SLDDRW in SOLIDWORKS, then press Review again with FICT-0001.SLDASM active";

    /// <summary>An instruction whose drawing's file name carries markup.</summary>
    private const string HostileInstruction =
        "Open <img src=x onerror=alert(15)>.SLDDRW in SOLIDWORKS, then press Review again with FICT-0001.SLDASM active";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    [Fact]
    public void TheSummaryIsShownBeforeTheGroupedFindingsOnceTheSessionEnds()
    {
        JsonElement first = Scripted.Value.First;

        Assert.False(first.GetProperty("hidden").GetBoolean(), "#summary stayed hidden.");
        Assert.True(first.GetProperty("rendered").GetBoolean(), "#summary is not on screen.");
        Assert.True(first.GetProperty("beforeGroups").GetBoolean(), "#summary must come before #findings-by-type.");
        Assert.Equal("function", first.GetProperty("exported").GetString());
    }

    /// <summary>
    /// The block reads in the order of the Independent Test as feature 013 amends it (grouped-list.md
    /// section 4): the headline, the tally, the questions, the parts not loaded, the one line about
    /// drawings, the one line about bought parts, and the goals not reached. No Decide, Fix and
    /// Verify lines and no goal lines: those are the tally's and the groups' now.
    /// </summary>
    [Fact]
    public void TheSummaryReadsTheHeadlineTheTallyTheQuestionsTheMissingPartsAndWhatWasNotReachedInOrder()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal(
            new[]
            {
                "summary-headline", "summary-tally", "summary-questions", "summary-not-loaded", "summary-drawings",
                "summary-bought-parts", "summary-not-reached",
            },
            ReviewPageDriver.Strings(first, "children"));
        Assert.Equal(SummarySample.Headline, first.GetProperty("headline").GetString());
        Assert.Equal(SummarySample.QuestionsText, first.GetProperty("questions").GetString());
        Assert.Equal(SummarySample.NotLoadedText, first.GetProperty("notLoaded").GetString());
        Assert.Equal(0, first.GetProperty("goalLines").GetInt32());
    }

    /// <summary>
    /// The tally and the not-reached line are the backend's words, printed as sent: the page counts
    /// no finding and names no goal (grouped-list.md section 4).
    /// </summary>
    [Fact]
    public void TheTallyAndTheNotReachedLineAreTheBackendsWordsPrintedVerbatim()
    {
        JsonElement first = Scripted.Value.First;

        Assert.Equal(SummarySample.TallyText, first.GetProperty("tally").GetString());
        Assert.Equal(SummarySample.NotReachedText, first.GetProperty("notReached").GetString());
    }

    /// <summary>`not_reached` is null when every goal was reached, and then there is no line.</summary>
    [Fact]
    public void EveryGoalReachedLeavesNoNotReachedLine()
    {
        JsonElement reached = Scripted.Value.EveryGoalReached;

        Assert.Equal(0, reached.GetProperty("notReachedLines").GetInt32());
        Assert.Equal(SummarySample.TallyText, reached.GetProperty("tally").GetString());
    }

    /// <summary>The tally and the not-reached line are backend text, and characters (FR-029).</summary>
    [Fact]
    public void AHostileTallyOrNotReachedLineRendersAsLiteralText()
    {
        JsonElement hostile = Scripted.Value.HostileLines;

        Assert.Equal(HostileTally, hostile.GetProperty("tally").GetString());
        Assert.Equal(HostileNotReached, hostile.GetProperty("notReached").GetString());
        Assert.Equal(0, hostile.GetProperty("injected").GetInt32());
        Assert.Equal(0, hostile.GetProperty("handlers").GetInt32());
    }

    /// <summary>
    /// Feature 011 T090 (2026-09-23): the sample's drawing line is the backend's, not words written
    /// for the page - the summary's `drawings` block of the review
    /// `reviewer/tests/fixtures/pane/generate_drawing_questions.py` plays, as
    /// `report/summary.drawings_of` returned it, member for member.
    /// </summary>
    [Fact]
    public void TheSamplesDrawingLineIsTheBackendsFromTheGeneratedFixture()
    {
        JsonNode? sample = SummarySample.Summary()["drawings"];
        JsonNode? backend = JsonNode.Parse(DrawingQuestionsFixture.Value.GetProperty("summary_drawings").GetRawText());

        Assert.True(
            JsonNode.DeepEquals(backend, sample),
            "SummarySample's drawings member differs from the generated fixture's summary_drawings: "
            + sample?.ToJsonString() + " against " + backend?.ToJsonString());
        Assert.Equal(backend!["text"]!.GetValue<string>(), SummarySample.DrawingsText);
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
            new[] { "summary-headline", "summary-tally", "summary-questions", "summary-not-loaded", "summary-bought-parts", "summary-not-reached" },
            ReviewPageDriver.Strings(older, "children"));
        Assert.Equal(SummarySample.Headline, older.GetProperty("headline").GetString());
    }

    /// <summary>
    /// Feature 013 (contracts/drawing-capability.md section 4): while the seat cannot open a closed
    /// drawing (`drawing_read` `open_only` or `none`), the backend asks no drawing question and its
    /// drawings line is the instruction instead - "Open {drawing} in SOLIDWORKS, then press Review
    /// again with {model} active", one file or several (`open_then_review_one`, `_many`). The page
    /// prints it verbatim as the one drawings line, and composes no word of it.
    /// </summary>
    [Fact]
    public void TheDrawingInstructionLineIsTheBackendsTextPrintedVerbatim()
    {
        JsonElement one = Scripted.Value.InstructionOne;
        JsonElement many = Scripted.Value.InstructionMany;

        Assert.Equal(InstructionOne, one.GetProperty("drawings").GetString());
        Assert.Equal(1, one.GetProperty("drawingLines").GetInt32());
        Assert.True(one.GetProperty("questionsHidden").GetBoolean(), "a questions panel was shown beside the instruction.");
        Assert.Equal(InstructionMany, many.GetProperty("drawings").GetString());
        Assert.Equal(1, many.GetProperty("drawingLines").GetInt32());
    }

    /// <summary>
    /// The instruction names files read from the reviewed folder, so it is backend text like any
    /// other: a file name that carries markup is characters (FR-029). The same words reach the
    /// coverage fold as the candidate row's reason, printed as sent.
    /// </summary>
    [Fact]
    public void AHostileInstructionIsLiteralTextAndTheCoverageReasonIsPrintedAsSent()
    {
        JsonElement hostile = Scripted.Value.InstructionHostile;

        Assert.Equal(HostileInstruction, hostile.GetProperty("drawings").GetString());
        Assert.Equal(0, hostile.GetProperty("injected").GetInt32());
        Assert.Equal(0, hostile.GetProperty("handlers").GetInt32());
        Assert.Contains("drawing.context - " + InstructionOne, ReviewPageDriver.Strings(hostile, "coverageLines"));
    }

    /// <summary>
    /// Feature 013 (contracts/part-roles.md section 7): the bought parts are named once, in the
    /// backend's one line, printed as sent after the drawings line - the page counts no part and
    /// composes no word of it, and the line is characters, never an element or a handler.
    /// </summary>
    [Fact]
    public void TheBoughtPartsLineIsTheBackendsTextPrintedVerbatimOnce()
    {
        JsonElement first = Scripted.Value.First;
        JsonElement hostile = Scripted.Value.HostileBoughtParts;

        Assert.Equal(SummarySample.BoughtPartsText, first.GetProperty("boughtParts").GetString());
        Assert.Equal(1, first.GetProperty("boughtPartsLines").GetInt32());
        Assert.Equal(HostileBoughtParts, hostile.GetProperty("boughtParts").GetString());
        Assert.Equal(0, hostile.GetProperty("injected").GetInt32());
        Assert.Equal(0, hostile.GetProperty("handlers").GetInt32());
    }

    /// <summary>
    /// No bought-parts line where the backend sent none: `bought_parts` null - nothing to say, as
    /// the zero-findings summary sends it - and a summary from a backend older than the line.
    /// </summary>
    [Fact]
    public void ANullOrAbsentBoughtPartsLineRendersNothing()
    {
        Assert.Equal(0, Scripted.Value.Second.GetProperty("boughtPartsLines").GetInt32());
        Assert.Equal(0, Scripted.Value.NoBoughtParts.GetProperty("boughtPartsLines").GetInt32());
        Assert.Equal(SummarySample.Headline, Scripted.Value.NoBoughtParts.GetProperty("headline").GetString());
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
    /// backend's words, with the tally at zero and the goals it did not reach.
    /// </summary>
    [Fact]
    public void ASecondRankingReplacesTheBlockAndAnEmptyReviewSaysSoInTheBackendsWords()
    {
        JsonElement second = Scripted.Value.Second;

        Assert.Equal(1, second.GetProperty("blocks").GetInt32());
        Assert.Equal(SummarySample.EmptyHeadline, second.GetProperty("headline").GetString());
        Assert.Equal(SummarySample.EmptyTallyText, second.GetProperty("tally").GetString());
        Assert.Equal(SummarySample.EmptyNotReachedText, second.GetProperty("notReached").GetString());
        Assert.Equal(JsonValueKind.Null, second.GetProperty("questions").ValueKind);
        Assert.Equal(JsonValueKind.Null, second.GetProperty("notLoaded").ValueKind);
    }

    /// <summary>
    /// FR-030: a ranking from a backend that sends no summary renders no block and no empty
    /// section taking room.
    /// </summary>
    [Fact]
    public void ARankingWithNoSummaryShowsNoBlock()
    {
        JsonElement none = Scripted.Value.NoSummary;

        Assert.True(none.GetProperty("hidden").GetBoolean(), "#summary is shown with no summary.");
        Assert.False(none.GetProperty("rendered").GetBoolean(), "#summary takes room with no summary.");
        Assert.Equal(0, none.GetProperty("blocks").GetInt32());
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

                // Feature 013: a backend older than the bought-parts line, then a hostile one.
                await driver.RouteAttention("chat-1", SummarySample.Json(summary => summary.Remove("bought_parts")));
                await driver.EndSession("chat-1");
                run.NoBoughtParts = await driver.Read(ReadSummary);

                await driver.RouteAttention(
                    "chat-1", SummarySample.Json(summary => summary["bought_parts"] = new JsonObject { ["text"] = HostileBoughtParts }));
                await driver.EndSession("chat-1");
                run.HostileBoughtParts = await driver.Read(ReadSummary);

                // Feature 013: every goal reached, then a hostile tally and not-reached line.
                await driver.RouteAttention("chat-1", SummarySample.Json(summary => summary["not_reached"] = null));
                await driver.EndSession("chat-1");
                run.EveryGoalReached = await driver.Read(ReadSummary);

                await driver.RouteAttention("chat-1", SummarySample.Json(summary =>
                {
                    summary["tally"] = new JsonObject { ["text"] = HostileTally };
                    summary["not_reached"] = new JsonObject { ["titles"] = new JsonArray("Fasteners"), ["text"] = HostileNotReached };
                }));
                await driver.EndSession("chat-1");
                run.HostileLines = await driver.Read(ReadSummary);

                await driver.StartReview();
                await driver.RouteAttention("chat-2", AttentionSample.Json());
                await driver.EndSession("chat-2");
                run.NoSummary = await driver.Read(ReadSummary);

                // Feature 013: the seat opens no closed drawing, so the drawings line is the
                // instruction and no drawing question is asked; its candidate row says the same.
                await driver.StartReview();
                await driver.RouteAttention("chat-3", SummarySample.Json(summary => Instruct(summary, InstructionOne)));
                await driver.Push("chat-3", 1, "coverage", JsonSerializer.Serialize(new
                {
                    bucket = "unresolved",
                    item = new { check = "drawing.context", reason = InstructionOne },
                }));
                await driver.EndSession("chat-3");
                run.InstructionOne = await driver.Read(ReadSummary);

                await driver.RouteAttention("chat-3", SummarySample.Json(summary => Instruct(summary, InstructionMany)));
                await driver.EndSession("chat-3");
                run.InstructionMany = await driver.Read(ReadSummary);

                await driver.RouteAttention("chat-3", SummarySample.Json(summary => Instruct(summary, HostileInstruction)));
                await driver.EndSession("chat-3");
                run.InstructionHostile = await driver.Read(ReadSummary);
            });

        return run;
    }

    /// <summary>
    /// The summary of a review whose seat opens no closed drawing: its drawings line is the
    /// instruction (`{read, candidates, text}` as `drawings_of` returns it) and it asks nothing.
    /// </summary>
    private static void Instruct(JsonObject summary, string instruction)
    {
        summary["drawings"] = JsonNode.Parse(JsonSerializer.Serialize(new
        {
            read = new string[0],
            candidates = new[] { "FICT-0002.SLDDRW" },
            text = instruction,
        }));
        summary["questions"] = JsonNode.Parse(@"{""count"":0,""text"":null,""items"":[]}");
    }

    private const string ReadSummary = @"
var section = document.getElementById('summary');
var block = section.querySelector('.summary');

var handlers = 0;
var all = section.getElementsByTagName('*');
for (var k = 0; k < all.length; k++) {
  for (var a = 0; a < all[k].attributes.length; a++) { if (/^on/i.test(all[k].attributes[a].name)) { handlers++; } }
}

return JSON.stringify({
  ok: true,
  hidden: !!section.hidden,
  rendered: h.rendered(section),
  beforeGroups: h.before(section, document.getElementById('findings-by-type')),
  blocks: section.querySelectorAll('.summary').length,
  children: h.children(block),
  headline: h.text(section, '.summary-headline'),
  tally: h.text(section, '.summary-tally'),
  questions: h.text(section, '.summary-questions'),
  notLoaded: h.text(section, '.summary-not-loaded'),
  drawings: h.text(section, '.summary-drawings'),
  drawingLines: section.querySelectorAll('.summary-drawings').length,
  boughtParts: h.text(section, '.summary-bought-parts'),
  boughtPartsLines: section.querySelectorAll('.summary-bought-parts').length,
  notReached: h.text(section, '.summary-not-reached'),
  notReachedLines: section.querySelectorAll('.summary-not-reached').length,
  goalLines: section.querySelectorAll('.summary-goal').length,
  questionsHidden: !!document.getElementById('questions').hidden,
  coverageLines: h.texts(document.getElementById('coverage-panel'), '.bucket-item'),
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

        public JsonElement NoBoughtParts { get; set; }

        public JsonElement HostileBoughtParts { get; set; }

        public JsonElement EveryGoalReached { get; set; }

        public JsonElement HostileLines { get; set; }

        public JsonElement NoSummary { get; set; }

        public JsonElement InstructionOne { get; set; }

        public JsonElement InstructionMany { get; set; }

        public JsonElement InstructionHostile { get; set; }
    }
}
