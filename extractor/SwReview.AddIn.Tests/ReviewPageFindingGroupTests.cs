using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T026: the modelling-practice findings are one collapsed group (FR-010, the
/// owner's decision of 2026-09-22, contracts/review-summary.md section 5).
///
/// On 830-02342, 51 of the 56 findings "to fix" were modelling practice - sketches not fully
/// defined, features in no folder - and they stood one headline each between the engineer and
/// the six interferences. The backend names the family's findings (`summary.modelling_practice
/// .finding_ids`, from feature 008's family row); once the ranking arrives the page moves those
/// cards, in the order they arrived, into one shut fold placed where the first of them was. It
/// decides nothing about which cards those are: the list is the backend's, and the order is the
/// order the cards are already in.
///
/// The sample's `finding_ids` are deliberately not in arrival order, so a page that followed the
/// list's order rather than the cards' fails; the members arrive after thirty other findings, so
/// following a Start-here row to one is a scroll the click has to make.
/// </summary>
public sealed class ReviewPageFindingGroupTests
{
    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    private const string Title = "Modelling practice: 3 findings across 3 rules";

    /// <summary>The family's findings as the backend lists them - not the order they arrived in.</summary>
    private static readonly string[] Members = { "F-009", "F-002", "F-004" };

    /// <summary>The same three in the order their cards arrived.</summary>
    private static readonly string[] MembersInArrivalOrder = { "F-002", "F-004", "F-009" };

    private const int Fillers = 30;

    [Fact]
    public void TheFamilysCardsSitInArrivalOrderInsideOneShutGroupNamedByTheBackend()
    {
        JsonElement grouped = Scripted.Value.Grouped;

        Assert.Equal(1, grouped.GetProperty("groups").GetInt32());
        Assert.Equal("DETAILS", grouped.GetProperty("tag").GetString());
        Assert.False(grouped.GetProperty("open").GetBoolean(), "the group arrived open.");
        Assert.Equal(Title, grouped.GetProperty("title").GetString());
        Assert.Equal(MembersInArrivalOrder, ReviewPageDriver.Strings(grouped, "inside"));
    }

    /// <summary>
    /// The group stands where its first member stood, and every other card keeps its place and
    /// is the same card it was - not rebuilt, not reordered.
    /// </summary>
    [Fact]
    public void TheGroupIsPlacedWhereTheFirstMemberWasAndEveryOtherCardIsUntouched()
    {
        JsonElement grouped = Scripted.Value.Grouped;

        var expected = new List<string> { "F-007" };
        expected.AddRange(Enumerable.Range(0, Fillers).Select(index => "F-" + (100 + index)));
        expected.AddRange(new[] { "GROUP", "F-008", "F-003" });

        Assert.Equal(expected.ToArray(), ReviewPageDriver.Strings(grouped, "order"));
        Assert.Equal("kept", grouped.GetProperty("probe").GetString());
    }

    /// <summary>
    /// A Start-here row naming a member opens the group, scrolls the card's head into view and
    /// lights the card - the card's own fold stays shut, as for any other row (U10).
    /// </summary>
    [Fact]
    public void AStartHereRowNamingAMemberOpensTheGroupScrollsToTheCardAndFlashesIt()
    {
        JsonElement clicked = Scripted.Value.RowClick;

        Assert.False(clicked.GetProperty("openBefore").GetBoolean(), "the group was already open.");
        Assert.False(clicked.GetProperty("inViewBefore").GetBoolean(), "the card was already in view.");
        Assert.True(clicked.GetProperty("openAfter").GetBoolean(), "the row did not open the group.");
        Assert.True(clicked.GetProperty("inViewAfter").GetBoolean(), "the row did not scroll to the card.");
        Assert.True(clicked.GetProperty("flashed").GetBoolean(), "the card was not lit.");
        Assert.True(clicked.GetProperty("foldShut").GetBoolean(), "the row opened the card's own fold.");
    }

    [Fact]
    public void AShowAllLineNamingAMemberOpensTheGroupScrollsToTheCardAndFlashesIt()
    {
        JsonElement clicked = Scripted.Value.LineClick;

        Assert.False(clicked.GetProperty("openBefore").GetBoolean(), "the group was already open.");
        Assert.True(clicked.GetProperty("openAfter").GetBoolean(), "the line did not open the group.");
        Assert.True(clicked.GetProperty("inViewAfter").GetBoolean(), "the line did not scroll to the card.");
        Assert.True(clicked.GetProperty("flashed").GetBoolean(), "the card was not lit.");
    }

    [Fact]
    public void CollapseAllShutsTheCardsInsideTheGroup()
    {
        JsonElement collapsed = Scripted.Value.Collapsed;

        Assert.Equal(2, collapsed.GetProperty("openBefore").GetInt32());
        Assert.Equal(0, collapsed.GetProperty("openAfter").GetInt32());
        Assert.All(ReviewPageDriver.Strings(collapsed, "labels"), label => Assert.Equal("Details", label));
    }

    /// <summary>
    /// A second ranking - the end of a follow-up turn - regroups: still one group, still the
    /// three members in arrival order, and no card twice anywhere on the page.
    /// </summary>
    [Fact]
    public void ASecondRankingRegroupsWithoutDuplicatingACard()
    {
        JsonElement again = Scripted.Value.Regrouped;

        Assert.Equal(1, again.GetProperty("groups").GetInt32());
        Assert.Equal(MembersInArrivalOrder, ReviewPageDriver.Strings(again, "inside"));
        Assert.Equal(Fillers + 6, again.GetProperty("cards").GetInt32());
        Assert.Equal(again.GetProperty("cards").GetInt32(), again.GetProperty("distinct").GetInt32());
    }

    /// <summary>A summary with no family moves nothing: the cards stay in the order they arrived.</summary>
    [Fact]
    public void ARankingWithNoModellingPracticeMovesNothing()
    {
        JsonElement none = Scripted.Value.NoFamily;

        Assert.Equal(0, none.GetProperty("groups").GetInt32());
        Assert.Equal(new[] { "F-002", "F-004", "F-009", "F-007" }, ReviewPageDriver.Strings(none, "order"));
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static Run Drive()
    {
        var run = new Run();

        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.RouteAttention("chat-1", WithFamily());
                await driver.StartReview();

                int seq = 0;
                await driver.Push("chat-1", ++seq, "finding", Finding("F-007", "interference.static"));
                for (int filler = 0; filler < Fillers; filler++)
                {
                    await driver.Push("chat-1", ++seq, "finding", Finding("F-" + (100 + filler), "interference.static"));
                }

                await driver.Push("chat-1", ++seq, "finding", Finding("F-002", "rms.sketches.fully_defined"));
                await driver.Push("chat-1", ++seq, "finding", Finding("F-008", "interference.static"));
                await driver.Push("chat-1", ++seq, "finding", Finding("F-004", "rms.grouping.all_features_in_a_group"));
                await driver.Push("chat-1", ++seq, "finding", Finding("F-003", "rms.assembly.mates_to_reference_geometry"));
                await driver.Push("chat-1", ++seq, "finding", Finding("F-009", "rms.folders.present"));
                await driver.Settle();
                await driver.Read("document.querySelector('.card.finding[data-finding-id=\"F-008\"]').setAttribute('data-probe', 'kept'); return JSON.stringify({ok: true});");

                await driver.EndSession("chat-1");
                run.Grouped = await driver.Read(ReadGroups);
                run.RowClick = await driver.Read(Follow("#attention-panel .attention-row[data-finding-id=\"F-002\"]", "F-002"));
                await driver.Read("document.querySelector('.finding-group').open = false; return JSON.stringify({ok: true});");
                run.LineClick = await driver.Read(
                    "document.querySelector('#attention-panel .attention-more').open = true;"
                    + Follow("#attention-panel .attention-index [data-finding-id=\"F-009\"]", "F-009"));
                run.Collapsed = await driver.Read(CollapseAll);

                await driver.EndSession("chat-1");
                run.Regrouped = await driver.Read(ReadGroups);

                await driver.StartReview();
                await driver.RouteAttention("chat-2", SummarySample.Json());
                await driver.Push("chat-2", 1, "finding", Finding("F-002", "rms.sketches.fully_defined"));
                await driver.Push("chat-2", 2, "finding", Finding("F-004", "rms.grouping.all_features_in_a_group"));
                await driver.Push("chat-2", 3, "finding", Finding("F-009", "rms.folders.present"));
                await driver.Push("chat-2", 4, "finding", Finding("F-007", "interference.static"));
                await driver.EndSession("chat-2");
                run.NoFamily = await driver.Read(ReadGroups);
            });

        return run;
    }

    /// <summary>The summary with the modelling-practice line feature 008's family row gives it.</summary>
    private static string WithFamily() => SummarySample.Json(summary =>
        summary["modelling_practice"] = JsonNode.Parse(JsonSerializer.Serialize(new
        {
            title = Title,
            findings = 3,
            rules = 3,
            finding_ids = Members,
        })));

    private static string Finding(string id, string check) => JsonSerializer.Serialize(new
    {
        id,
        check,
        title = "Finding " + id,
        status = "demonstrated",
        severity = "low",
        component_ids = new[] { "cmp:0002" },
        observed = "Observed for " + id + ".",
    });

    /// <summary>
    /// Every finding card and group in the findings list, in document order: the list is
    /// `#findings` once Results and Transcript are two views, `#transcript` before that.
    /// </summary>
    private const string ReadGroups = @"
var list = document.getElementById('findings') || document.getElementById('transcript');
var order = [];
for (var i = 0; i < list.children.length; i++) {
  var node = list.children[i];
  if (node.classList.contains('finding-group')) { order.push('GROUP'); }
  else if (node.classList.contains('finding')) { order.push(node.getAttribute('data-finding-id')); }
}
var groups = document.querySelectorAll('.finding-group');
var group = groups[0] || null;
var cards = h.attrs(document, '.card.finding', 'data-finding-id');
var distinct = {};
for (var c = 0; c < cards.length; c++) { distinct[cards[c]] = true; }
var probe = document.querySelector('.card.finding[data-finding-id=""F-008""]');
return JSON.stringify({
  ok: true,
  groups: groups.length,
  tag: group ? group.tagName : null,
  open: group ? group.open : null,
  title: group ? h.text(group, ':scope > summary') : null,
  inside: group ? h.attrs(group, '.card.finding', 'data-finding-id') : [],
  order: order,
  probe: probe ? probe.getAttribute('data-probe') : null,
  cards: cards.length,
  distinct: Object.keys(distinct).length
});";

    /// <summary>
    /// Scrolls everything to the top, clicks <paramref name="selector"/> and reports where the
    /// card went - in one evaluation, because the flash is a class the page takes off again.
    /// </summary>
    private static string Follow(string selector, string findingId) => @"
var target = document.querySelector('" + selector.Replace("'", "\\'") + @"');
if (!target) { return JSON.stringify({ ok: false, error: 'nothing to click for " + findingId + @"' }); }
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
var group = card.closest('.finding-group');
h.resetScroll();
var openBefore = !!(group && group.open);
var inViewBefore = h.inView(card.querySelector('.card-head'));
target.click();
return JSON.stringify({
  ok: true,
  openBefore: openBefore,
  inViewBefore: inViewBefore,
  openAfter: !!(group && group.open),
  inViewAfter: h.inView(card.querySelector('.card-head')),
  flashed: /(^|\s)flash(\s|$)/.test(card.className),
  foldShut: card.querySelector('.details').hidden
});";

    private const string CollapseAll = @"
var inside = document.querySelectorAll('.finding-group .card.finding');
inside[0].querySelector('[data-action=""expand""]').click();
inside[1].querySelector('[data-action=""expand""]').click();
var open = function () { return document.querySelectorAll('.finding-group .card.finding .details:not([hidden])').length; };
var openBefore = open();
document.getElementById('collapse-findings').click();
return JSON.stringify({
  ok: true,
  openBefore: openBefore,
  openAfter: open(),
  labels: h.texts(document, '.finding-group .card.finding [data-action=""expand""]')
});";

    private sealed class Run
    {
        public JsonElement Grouped { get; set; }

        public JsonElement RowClick { get; set; }

        public JsonElement LineClick { get; set; }

        public JsonElement Collapsed { get; set; }

        public JsonElement Regrouped { get; set; }

        public JsonElement NoFamily { get; set; }
    }
}
