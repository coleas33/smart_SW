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
/// <b>The Independent Test</b>: the summary reads, in order, the finding and issue counts, the
/// three groups, the questions, the parts not loaded and one line per goal with its state - every
/// word the backend's, checked against the fixture's own summary and, for the numbers an engineer
/// reads first, against the literals the backend acceptance (T022) derived by hand.
///
/// <b>SC-001</b>: with Results at its top, the headline, the three groups and every goal line
/// whose state is not reached are inside the viewport - the ten-second read needs no scroll.
/// </summary>
public sealed class ReviewPageSummaryAcceptanceTests
{
    private static readonly Lazy<JsonElement> Scripted = new Lazy<JsonElement>(Drive);

    [Fact]
    public void TheSummaryReadsInTheOrderOfTheIndependentTest()
    {
        JsonElement read = Scripted.Value;

        Assert.Equal(
            new[] { "summary-headline", "summary-groups", "summary-questions", "summary-not-loaded", "summary-goals" },
            ReviewPageDriver.Strings(read, "children"));
        // 96 and 15 since the fixture follows the code: three touching groups are contacts (ReviewFixture).
        Assert.Equal("96 findings in 15 issues", read.GetProperty("headline").GetString());
        Assert.Equal("4 questions for you", read.GetProperty("questions").GetString());
        Assert.Equal("3 of 89 parts not loaded", read.GetProperty("notLoaded").GetString());
        Assert.True(read.GetProperty("beforePanel").GetBoolean(), "the summary must come before Start here.");
    }

    [Fact]
    public void TheThreeGroupsAreTheBackendsDecideFixVerifyWithTheirGoals()
    {
        JsonElement read = Scripted.Value;

        Assert.Equal(new[] { "Decide", "Fix", "Verify" }, ReviewPageDriver.Strings(read, "groupLabels"));
        // Interference 3, not 6, since the fixture follows the code: three touching groups are contacts (ReviewFixture).
        Assert.Equal(
            new[] { "6 need your decision", "56 to fix", "34 to verify" },
            ReviewPageDriver.Strings(read, "groupTexts"));
        Assert.Equal(
            new[] { "Interference 3|Hole alignment 3", "Hygiene 5|Modelling practice 51", "Modelling practice 34" },
            ReviewPageDriver.Strings(read, "groupGoals"));
    }

    [Fact]
    public void EveryGoalLinePrintsTheBackendsStateAndReason()
    {
        JsonElement read = Scripted.Value;
        ReviewFixture fixture = ReviewFixture.Value;

        Assert.Equal(fixture.SummaryStrings("goals", "title"), ReviewPageDriver.Strings(read, "goalTitles"));
        Assert.Equal(fixture.SummaryStrings("goals", "state_label"), ReviewPageDriver.Strings(read, "goalStates"));
        Assert.Equal(fixture.SummaryStrings("goals", "reason"), ReviewPageDriver.Strings(read, "goalReasons"));
        Assert.Equal(
            fixture.SummaryStrings("goals", "state").Select(state => "summary-goal goal-" + state).ToArray(),
            ReviewPageDriver.Strings(read, "goalClasses"));
        Assert.Equal(
            new[] { "issues found", "not reached", "issues found", "not reached", "not reached", "not reached", "issues found", "not reached", "issues found" },
            ReviewPageDriver.Strings(read, "goalStates"));
    }

    /// <summary>Every finding the stream delivered has its card in Results, in arrival order.</summary>
    [Fact]
    public void EveryFindingOfTheReviewHasItsCardInResults()
    {
        JsonElement read = Scripted.Value;

        Assert.Equal(
            ReviewFixture.Value.Findings.Select(finding => finding.GetProperty("id").GetString()).ToArray(),
            ReviewPageDriver.Strings(read, "cardIds"));
    }

    /// <summary>SC-001: the ten-second read is on the first screen of a docked pane.</summary>
    [Fact]
    public void TheHeadlineTheThreeGroupsAndEveryNotReachedGoalAreInsideThe300By600Viewport()
    {
        JsonElement read = Scripted.Value;

        Assert.True(read.GetProperty("headlineInView").GetBoolean(), "the headline is below the fold: " + read.GetProperty("geometry"));
        Assert.Equal(new[] { true, true, true }, read.GetProperty("groupsInView").EnumerateArray().Select(value => value.GetBoolean()).ToArray());
        Assert.Equal(5, read.GetProperty("notReachedInView").GetArrayLength());
        Assert.All(
            read.GetProperty("notReachedInView").EnumerateArray(),
            value => Assert.True(value.GetBoolean(), "a not-reached goal line is below the fold: " + read.GetProperty("geometry")));
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
var groups = section.querySelectorAll('.summary-group');
var goals = section.querySelectorAll('.summary-goal');

var groupGoals = [], groupsInView = [];
for (var i = 0; i < groups.length; i++) {
  groupGoals.push(h.texts(groups[i], '.group-goal').join('|'));
  groupsInView.push(h.inView(groups[i]));
}

var goalReasons = [], notReachedInView = [];
for (var j = 0; j < goals.length; j++) {
  goalReasons.push(h.text(goals[j], '.goal-reason') || '');
  if (goals[j].classList.contains('goal-not_reached')) { notReachedInView.push(h.inView(goals[j])); }
}

var last = goals.length ? goals[goals.length - 1].getBoundingClientRect() : null;
return JSON.stringify({
  ok: true,
  children: h.children(block),
  beforePanel: h.before(section, document.getElementById('attention-panel')),
  headline: h.text(section, '.summary-headline'),
  headlineInView: h.inView(section.querySelector('.summary-headline')),
  groupLabels: h.texts(section, '.summary-group .group-label'),
  groupTexts: h.texts(section, '.summary-group .group-text'),
  groupGoals: groupGoals,
  groupsInView: groupsInView,
  questions: h.text(section, '.summary-questions'),
  notLoaded: h.text(section, '.summary-not-loaded'),
  goalClasses: Array.prototype.map.call(goals, function (g) { return g.className; }),
  goalTitles: h.texts(section, '.summary-goal .goal-title'),
  goalStates: h.texts(section, '.summary-goal .goal-state'),
  goalReasons: goalReasons,
  notReachedInView: notReachedInView,
  cardIds: h.attrs(document.getElementById('findings'), '.card.finding', 'data-finding-id'),
  geometry: { innerHeight: window.innerHeight, summaryTop: section.getBoundingClientRect().top, lastGoalBottom: last ? last.bottom : null }
});";
}
