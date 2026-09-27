using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 013 T053: the finding cards move into the grouped rows (contracts/grouped-list.md
/// section 5, `applyRanking`'s move). Until feature 013 this class pinned feature 009's one
/// modelling-practice group (T026), which the grouped list generalises and replaces: the group is
/// the fold now, for every type.
///
/// While a turn runs the cards arrive in a holding list, one headline each, in arrival order. When
/// a ranking arrives the page returns every card to the holding list in arrival order, then moves
/// each into its row's body in the row's `member_finding_ids` order. It decides nothing about
/// which card goes where or in what order: <see cref="GroupsSample"/>'s F-009 row lists F-009,
/// F-010, F-011 while the stream delivers F-011 first, and <see cref="GroupsSample.UnnamedCard"/>
/// is a card no row names, which stays in the holding list and is never dropped.
/// </summary>
public sealed class ReviewPageFindingGroupTests
{
    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    /// <summary>Each group holds its rows' cards, each row's members in the row's order - not the order they arrived in.</summary>
    [Fact]
    public void EachRowHoldsItsMembersCardsInTheRowsOrder()
    {
        JsonElement grouped = Scripted.Value.Grouped;

        Assert.Equal(
            GroupsSample.GroupCardIds.Select(cards => string.Join("|", cards)).Concat(new[] { string.Join("|", GroupsSample.CheckedRowIds) }).ToArray(),
            ReviewPageDriver.Strings(grouped, "groupCards"));
        Assert.Equal(GroupsSample.FoldedMembers, ReviewPageDriver.Strings(grouped, "foldedRowCards"));
    }

    /// <summary>A card is moved, never rebuilt: the one the stream delivered is the one in the row.</summary>
    [Fact]
    public void AMovedCardIsTheCardTheStreamDelivered()
    {
        Assert.Equal("kept", Scripted.Value.Grouped.GetProperty("probe").GetString());
    }

    /// <summary>A card no row names stays in the holding list - on the page, never dropped.</summary>
    [Fact]
    public void ACardNoRowNamesStaysInTheHoldingList()
    {
        JsonElement grouped = Scripted.Value.Grouped;

        Assert.Equal(new[] { GroupsSample.UnnamedCard }, ReviewPageDriver.Strings(grouped, "holdingIds"));
        Assert.True(grouped.GetProperty("unnamedRendered").GetBoolean(), "the card no row names is not on screen.");
        Assert.Equal(GroupsSample.ArrivalOrder.Length, grouped.GetProperty("cards").GetInt32());
    }

    /// <summary>
    /// A second ranking - the end of a follow-up turn - regroups: the same cards in the same rows,
    /// and no card twice anywhere on the page.
    /// </summary>
    [Fact]
    public void ASecondRankingRegroupsWithoutDuplicatingACard()
    {
        JsonElement again = Scripted.Value.Regrouped;

        Assert.Equal(ReviewPageDriver.Strings(Scripted.Value.Grouped, "groupCards"), ReviewPageDriver.Strings(again, "groupCards"));
        Assert.Equal(GroupsSample.ArrivalOrder.Length, again.GetProperty("cards").GetInt32());
        Assert.Equal(again.GetProperty("cards").GetInt32(), again.GetProperty("distinct").GetInt32());
        Assert.Equal("kept", again.GetProperty("probe").GetString());
    }

    /// <summary>
    /// A ranking whose rows no longer name some cards returns them to the holding list, in the
    /// order they arrived - here Modelling practice's six, when a ranking carries no such group.
    /// </summary>
    [Fact]
    public void ACardARankingNoLongerNamesReturnsToTheHoldingListInArrivalOrder()
    {
        JsonElement fewer = Scripted.Value.Fewer;
        string[] modelling = GroupsSample.GroupCardIds[Array.IndexOf(GroupsSample.GroupIds, "modelling_practice")];

        Assert.Equal(
            GroupsSample.ArrivalOrder.Where(id => modelling.Contains(id) || id == GroupsSample.UnnamedCard).ToArray(),
            ReviewPageDriver.Strings(fewer, "holdingIds"));
        Assert.Equal(GroupsSample.ArrivalOrder.Length, fewer.GetProperty("distinct").GetInt32());
    }

    /// <summary>
    /// A single-member row hides its card's title, which would repeat the row's own; a row of
    /// several shows each card's; and a card back in the holding list shows its title again.
    /// </summary>
    [Fact]
    public void ARowThatHidesItsCardsTitleHidesItAndOnlyThere()
    {
        JsonElement titles = Scripted.Value.Grouped.GetProperty("titleShown");
        JsonElement back = Scripted.Value.Fewer.GetProperty("titleShown");

        Assert.False(titles.GetProperty("F-008").GetBoolean(), "a single-member row's card repeats the row's title.");
        Assert.True(titles.GetProperty("F-009").GetBoolean(), "a card of a row of several lost its title.");
        Assert.True(titles.GetProperty("F-010").GetBoolean(), "a card of a row of several lost its title.");
        Assert.True(titles.GetProperty(GroupsSample.UnnamedCard).GetBoolean(), "a card in the holding list lost its title.");
        Assert.True(back.GetProperty("F-003").GetBoolean(), "a card back in the holding list still hides its title.");
    }

    /// <summary>
    /// SC-006 (feature 009, amended): a card in an open group is one click from the top of Results
    /// - its row - and a card in a collapsed group two: the group, then the row.
    /// </summary>
    [Fact]
    public void ARowOpensItsCardsOneClickInAnOpenGroupTwoInACollapsedOne()
    {
        JsonElement open = Scripted.Value.OpenGroupRow;
        JsonElement collapsed = Scripted.Value.CollapsedGroupRow;

        Assert.False(open.GetProperty("visibleBefore").GetBoolean(), "a card in a shut row was already on screen.");
        Assert.True(open.GetProperty("visibleAfterOne").GetBoolean(), "one click on its row did not show the card.");

        Assert.False(collapsed.GetProperty("visibleBefore").GetBoolean(), "a card in a collapsed group was already on screen.");
        Assert.False(collapsed.GetProperty("visibleAfterOne").GetBoolean(), "opening the group alone showed a card of a shut row.");
        Assert.True(collapsed.GetProperty("visibleAfterTwo").GetBoolean(), "the group and then the row did not show the card.");
        Assert.Equal(GroupsSample.FoldedMembers, ReviewPageDriver.Strings(collapsed, "visibleCards"));
    }

    /// <summary>Collapse all shuts every open row and every card's fold, and leaves the groups as they were.</summary>
    [Fact]
    public void CollapseAllShutsRowsAndCardFoldsButNotGroups()
    {
        JsonElement collapsed = Scripted.Value.Collapsed;

        Assert.True(collapsed.GetProperty("openRowsBefore").GetInt32() >= 2, "too few rows open to prove 'all'.");
        Assert.Equal(2, collapsed.GetProperty("openFoldsBefore").GetInt32());
        Assert.Equal(0, collapsed.GetProperty("openRowsAfter").GetInt32());
        Assert.Equal(0, collapsed.GetProperty("openFoldsAfter").GetInt32());
        Assert.All(ReviewPageDriver.Strings(collapsed, "labels"), label => Assert.Equal("Details", label));
        Assert.Equal(
            collapsed.GetProperty("groupsBefore").EnumerateArray().Select(value => value.GetBoolean()).ToArray(),
            collapsed.GetProperty("groupsAfter").EnumerateArray().Select(value => value.GetBoolean()).ToArray());
        Assert.True(collapsed.GetProperty("overTheGroups").GetBoolean(), "Collapse all is not in Results over the grouped findings.");
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

                int seq = 0;
                foreach (string id in GroupsSample.ArrivalOrder)
                {
                    await driver.Push("chat-1", ++seq, "finding", GroupsSample.Finding(id));
                }

                await driver.Settle();
                await driver.Read("document.querySelector('.card.finding[data-finding-id=\"F-008\"]').setAttribute('data-probe', 'kept'); return JSON.stringify({ok: true});");

                await driver.EndSession("chat-1");
                run.Grouped = await driver.Read(ReadGroups);
                run.OpenGroupRow = await driver.Read(OpenRow("interference_fit", "F-008"));
                run.CollapsedGroupRow = await driver.Read(OpenRow("modelling_practice", GroupsSample.FoldedRow));
                run.Collapsed = await driver.Read(CollapseAll);

                await driver.EndSession("chat-1");
                run.Regrouped = await driver.Read(ReadGroups);

                await driver.RouteAttention("chat-1", WithoutModellingPractice());
                await driver.EndSession("chat-1");
                run.Fewer = await driver.Read(ReadGroups);
            });

        return run;
    }

    /// <summary>The sample's ranking with its Modelling practice group taken out.</summary>
    private static string WithoutModellingPractice()
    {
        JsonObject ranking = SummarySample.Ranking();
        JsonArray groups = ranking["groups"]!["groups"]!.AsArray();
        groups.RemoveAt(Array.IndexOf(GroupsSample.GroupIds, "modelling_practice"));
        return ranking.ToJsonString();
    }

    /// <summary>Every group's cards, the holding list, and the facts about the cards the tests read.</summary>
    private const string ReadGroups = @"
var section = document.getElementById('findings-by-type');
var groups = section.querySelectorAll('details.type-group');
var groupCards = [];
for (var g = 0; g < groups.length; g++) { groupCards.push(h.attrs(groups[g], '.card.finding', 'data-finding-id').join('|')); }
var cards = h.attrs(document.getElementById('results'), '.card.finding', 'data-finding-id');
var distinct = {};
for (var c = 0; c < cards.length; c++) { distinct[cards[c]] = true; }
var cardOf = function (id) { return document.querySelector('.card.finding[data-finding-id=""' + id + '""]'); };
var titleShown = function (id) {
  var card = cardOf(id);
  return !!card && getComputedStyle(card.querySelector('.card-head .title')).display !== 'none';
};
var folded = section.querySelector('details.type-row[data-finding-id=""F-009""]');
var probe = cardOf('F-008');
var unnamed = cardOf('F-099');
return JSON.stringify({
  ok: true,
  groupCards: groupCards,
  foldedRowCards: h.attrs(folded, '.card.finding', 'data-finding-id'),
  holdingIds: h.attrs(document.getElementById('findings'), ':scope > .card.finding', 'data-finding-id'),
  cards: cards.length,
  distinct: Object.keys(distinct).length,
  probe: probe ? probe.getAttribute('data-probe') : null,
  unnamedRendered: !!unnamed && unnamed.querySelector('.card-head').checkVisibility(),
  titleShown: { 'F-003': titleShown('F-003'), 'F-008': titleShown('F-008'), 'F-009': titleShown('F-009'), 'F-010': titleShown('F-010'), 'F-099': titleShown('F-099') }
});";

    /// <summary>
    /// With Results at its top, clicks the group's summary when the group is shut, then the row's
    /// summary, and reports after each click whether the row's first card is on screen.
    /// </summary>
    private static string OpenRow(string group, string row) => @"
h.resetScroll();
var groupNode = document.querySelector('#findings-by-type details.type-group[data-group=""" + group + @"""]');
var rowNode = groupNode.querySelector('details.type-row[data-finding-id=""" + row + @"""]');
var card = rowNode.querySelector('.card.finding');
var visible = function () { return card.querySelector('.card-head').checkVisibility(); };
var visibleBefore = visible();
if (!groupNode.open) { groupNode.querySelector(':scope > summary').click(); } else { rowNode.querySelector(':scope > summary').click(); }
var visibleAfterOne = visible();
if (!rowNode.open) { rowNode.querySelector(':scope > summary').click(); }
var shown = [];
var inRow = rowNode.querySelectorAll('.card.finding');
for (var i = 0; i < inRow.length; i++) { if (inRow[i].querySelector('.card-head').checkVisibility()) { shown.push(inRow[i].getAttribute('data-finding-id')); } }
return JSON.stringify({ ok: true, visibleBefore: visibleBefore, visibleAfterOne: visibleAfterOne, visibleAfterTwo: visible(), visibleCards: shown });";

    /// <summary>Opens two cards' folds with their own Details buttons, presses Collapse all, and reports rows, folds and groups.</summary>
    private const string CollapseAll = @"
var section = document.getElementById('findings-by-type');
document.querySelector('.card.finding[data-finding-id=""F-008""] [data-action=""expand""]').click();
document.querySelector('.card.finding[data-finding-id=""F-009""] [data-action=""expand""]').click();
var openRows = function () { return section.querySelectorAll('details.type-row[open]').length; };
var openFolds = function () { return document.querySelectorAll('#results .card.finding .details:not([hidden])').length; };
var groupStates = function () {
  var out = [];
  var groups = section.querySelectorAll('details.type-group');
  for (var i = 0; i < groups.length; i++) { out.push(!!groups[i].open); }
  return out;
};
var openRowsBefore = openRows(), openFoldsBefore = openFolds(), groupsBefore = groupStates();
var button = document.getElementById('collapse-findings');
button.click();
return JSON.stringify({
  ok: true,
  openRowsBefore: openRowsBefore,
  openFoldsBefore: openFoldsBefore,
  openRowsAfter: openRows(),
  openFoldsAfter: openFolds(),
  labels: h.texts(document.getElementById('results'), '.card.finding [data-action=""expand""]'),
  groupsBefore: groupsBefore,
  groupsAfter: groupStates(),
  overTheGroups: document.getElementById('results').contains(button) && h.before(button, section)
});";

    private sealed class Run
    {
        public JsonElement Grouped { get; set; }

        public JsonElement OpenGroupRow { get; set; }

        public JsonElement CollapsedGroupRow { get; set; }

        public JsonElement Collapsed { get; set; }

        public JsonElement Regrouped { get; set; }

        public JsonElement Fewer { get; set; }
    }
}
