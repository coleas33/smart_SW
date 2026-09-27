using System;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T032 - the US3 page acceptance, written after the page and the backend and
/// passing with no further production code: the big-assembly review as the backend produces it
/// (<see cref="ReviewFixture"/>), played into the real page in a docked pane's 300 by 600.
///
/// Feature 013 T053 amends it with the summary block (contracts/grouped-list.md section 4): the
/// headline, one tally line, the questions, the parts not loaded and one not-reached line, the goal
/// lines living under their groups. SC-001 is amended with it: with Results at its top, the
/// headline, the tally and the not-reached line are inside the viewport. The committed fixture
/// predates feature 013, so the assertions that read its tally, its not-reached line or its groups
/// wait for 013 T056's regeneration (<see cref="ReviewFixture.WaitsForT056"/>); the rest hold on
/// the fixture as it is and as it will be.
/// </summary>
public sealed class ReviewPageSummaryAcceptanceTests
{
    private static readonly Lazy<JsonElement> Scripted = new Lazy<JsonElement>(Drive);

    /// <summary>The headline, the questions and the parts not loaded are the backend's words, and the summary comes before the groups.</summary>
    [Fact]
    public void TheSummaryPrintsTheBackendsHeadlineQuestionsAndPartsNotLoaded()
    {
        JsonElement read = Scripted.Value;

        Assert.Equal(ReviewFixture.Value.Summary.GetProperty("headline").GetString(), read.GetProperty("headline").GetString());
        Assert.Equal("4 questions for you", read.GetProperty("questions").GetString());
        Assert.Equal("3 of 89 parts not loaded", read.GetProperty("notLoaded").GetString());
        Assert.True(read.GetProperty("beforeGroups").GetBoolean(), "the summary must come before the grouped findings.");
        Assert.Equal(0, read.GetProperty("goalLines").GetInt32());
    }

    /// <summary>The block reads in the order of the Independent Test as feature 013 amends it.</summary>
    [Fact(Skip = ReviewFixture.WaitsForT056)]
    public void TheSummaryReadsInTheOrderOfTheIndependentTest()
    {
        JsonElement read = Scripted.Value;

        Assert.Equal(
            new[] { "summary-headline", "summary-tally", "summary-questions", "summary-not-loaded", "summary-not-reached" },
            ReviewPageDriver.Strings(read, "children"));
        Assert.Equal(ReviewFixture.Value.Summary.GetProperty("tally").GetProperty("text").GetString(), read.GetProperty("tally").GetString());
        Assert.Equal(
            ReviewFixture.Value.Summary.GetProperty("not_reached").GetProperty("text").GetString(),
            read.GetProperty("notReached").GetString());
    }

    /// <summary>
    /// Every goal line of the backend is printed under its group with its state and reason, in the
    /// backend's order - the lines the summary listed until feature 013.
    /// </summary>
    [Fact(Skip = ReviewFixture.WaitsForT056)]
    public void EveryGoalLinePrintsTheBackendsStateAndReasonUnderItsGroup()
    {
        JsonElement read = Scripted.Value;
        JsonElement[] goals = ReviewFixture.Value.GroupsWithRows()
            .Where(group => group.Group.TryGetProperty("goals", out _))
            .SelectMany(group => group.Group.GetProperty("goals").EnumerateArray())
            .ToArray();

        Assert.NotEmpty(goals);
        Assert.Equal(goals.Select(goal => goal.GetProperty("title").GetString()).ToArray(), ReviewPageDriver.Strings(read, "goalTitles"));
        Assert.Equal(goals.Select(goal => goal.GetProperty("state_label").GetString()).ToArray(), ReviewPageDriver.Strings(read, "goalStates"));
        Assert.Equal(
            goals.Select(goal => goal.GetProperty("reason").ValueKind == JsonValueKind.Null ? string.Empty : goal.GetProperty("reason").GetString()).ToArray(),
            ReviewPageDriver.Strings(read, "goalReasons"));
    }

    /// <summary>
    /// Every finding the stream delivered has exactly one card in Results - in its row, or in the
    /// holding list when no row names it - and no card is there twice.
    /// </summary>
    [Fact]
    public void EveryFindingOfTheReviewHasOneCardInResults()
    {
        JsonElement read = Scripted.Value;
        string[] cards = ReviewPageDriver.Strings(read, "cardIds");

        Assert.Equal(
            ReviewFixture.Value.Findings.Select(finding => finding.GetProperty("id").GetString()).OrderBy(id => id, StringComparer.Ordinal).ToArray(),
            cards.OrderBy(id => id, StringComparer.Ordinal).ToArray());
        Assert.Equal(cards.Length, cards.Distinct().Count());
    }

    /// <summary>SC-001: the ten-second read starts on the first screen of a docked pane.</summary>
    [Fact]
    public void TheHeadlineIsInsideThe300By600Viewport()
    {
        JsonElement read = Scripted.Value;

        Assert.True(read.GetProperty("headlineInView").GetBoolean(), "the headline is below the fold: " + read.GetProperty("geometry"));
    }

    /// <summary>SC-001 as feature 013 amends it: the headline, the tally and the not-reached line are on the first screen.</summary>
    [Fact(Skip = ReviewFixture.WaitsForT056)]
    public void TheHeadlineTheTallyAndTheNotReachedLineAreInsideThe300By600Viewport()
    {
        JsonElement read = Scripted.Value;

        Assert.True(read.GetProperty("headlineInView").GetBoolean(), "the headline is below the fold: " + read.GetProperty("geometry"));
        Assert.True(read.GetProperty("tallyInView").GetBoolean(), "the tally is below the fold: " + read.GetProperty("geometry"));
        Assert.True(read.GetProperty("notReachedInView").GetBoolean(), "the not-reached line is below the fold: " + read.GetProperty("geometry"));
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static JsonElement Drive()
    {
        JsonElement read = default;
        ReviewFixture fixture = ReviewFixture.Value;

        ReviewPageDriver.Run(
            fixture.Configure,
            async driver =>
            {
                await NarrowPane(driver);
                await fixture.Review(driver);
                read = await driver.Read(ReadSummary);
            });

        return read;
    }

    /// <summary>The docked pane's size, as the narrow-layout tests set it.</summary>
    internal static async Task NarrowPane(ReviewPageDriver driver)
    {
        await driver.Page.CallDevToolsProtocolMethodAsync(
            "Emulation.setDeviceMetricsOverride",
            JsonSerializer.Serialize(new { width = 300, height = 600, deviceScaleFactor = 1, mobile = false }));
        await driver.Settle();
    }

    private const string ReadSummary = @"
h.resetScroll();
var section = document.getElementById('summary');
var block = section.querySelector('.summary');
var groups = document.getElementById('findings-by-type');
var goals = groups.querySelectorAll('.summary-goal');
var goalReasons = [];
for (var j = 0; j < goals.length; j++) { goalReasons.push(h.text(goals[j], '.goal-reason') || ''); }
var notReached = section.querySelector('.summary-not-reached');
return JSON.stringify({
  ok: true,
  children: h.children(block),
  beforeGroups: h.before(section, groups),
  headline: h.text(section, '.summary-headline'),
  headlineInView: h.inView(section.querySelector('.summary-headline')),
  tally: h.text(section, '.summary-tally'),
  tallyInView: h.inView(section.querySelector('.summary-tally')),
  questions: h.text(section, '.summary-questions'),
  notLoaded: h.text(section, '.summary-not-loaded'),
  notReached: notReached ? notReached.textContent : null,
  notReachedInView: h.inView(notReached),
  goalLines: section.querySelectorAll('.summary-goal').length,
  goalTitles: h.texts(groups, '.summary-goal .goal-title'),
  goalStates: h.texts(groups, '.summary-goal .goal-state'),
  goalReasons: goalReasons,
  cardIds: h.attrs(document.getElementById('results'), '.card.finding', 'data-finding-id'),
  geometry: { innerHeight: window.innerHeight, summaryTop: section.getBoundingClientRect().top }
});";
}
