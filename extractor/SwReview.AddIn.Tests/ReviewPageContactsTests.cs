using System;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T028: size-for-size contacts are one folded list apart from the findings
/// (FR-011, the owner's decision of 2026-09-23, contracts/review-summary.md section 5).
///
/// A pin sitting size-for-size in its bore is not a defect, and on the evening's reviews those
/// contacts were findings - interference at zero volume, one headline each. Feature 010 records
/// them as contacts instead (`ReviewSession.contacts`) and the summary maps each to the names of
/// its two parts, its kind in words and its configuration. The page prints that list in one shut
/// fold after the findings, and nowhere else: not in a finding card, not in Start here, not in
/// the modelling-practice group. Until feature 010 lands the summary's `contacts` is null, so
/// the list is proven here on the sample's hand-added contacts (research R5).
/// </summary>
public sealed class ReviewPageContactsTests
{
    private const string HostileName = "<img src=x onerror=alert(1)>Pin-B-1";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    [Fact]
    public void TheContactsAreOneShutFoldAfterTheFindingCardsHeadedByTheBackendsLine()
    {
        JsonElement listed = Scripted.Value.Listed;

        Assert.Equal(1, listed.GetProperty("folds").GetInt32());
        Assert.False(listed.GetProperty("open").GetBoolean(), "the contacts arrived open.");
        Assert.Equal("2 size-for-size contacts", listed.GetProperty("head").GetString());
        Assert.True(listed.GetProperty("afterEveryCard").GetBoolean(), "the contacts are not after the finding cards.");
    }

    /// <summary>
    /// One line per contact: the two parts by name, the kind in words, the configuration - and
    /// the component ids and the volume in that line's own shut fold.
    /// </summary>
    [Fact]
    public void EachLineNamesTheTwoPartsItsKindAndConfigurationWithTheIdsAndVolumeInItsOwnFold()
    {
        JsonElement listed = Scripted.Value.Listed;

        Assert.Equal(new[] { "Pin-A-1 and Plate-1", HostileName + " and cmp:0009" }, ReviewPageDriver.Strings(listed, "texts"));
        Assert.Equal(new[] { "touching", "possible only" }, ReviewPageDriver.Strings(listed, "kinds"));
        Assert.Equal(new[] { "Default", "Machined" }, ReviewPageDriver.Strings(listed, "configurations"));
        Assert.Equal(new[] { "cmp:0002, cmp:0003 · 0 mm³", "cmp:0004, cmp:0009" }, ReviewPageDriver.Strings(listed, "ids"));
        Assert.Equal(new[] { "shut", "shut" }, ReviewPageDriver.Strings(listed, "lineFolds"));
    }

    [Fact]
    public void NoContactIsInAFindingCardInStartHereOrInTheModellingPracticeGroup()
    {
        JsonElement listed = Scripted.Value.Listed;

        Assert.Equal(0, listed.GetProperty("inCards").GetInt32());
        Assert.Equal(0, listed.GetProperty("inStartHere").GetInt32());
        Assert.Equal(0, listed.GetProperty("inGroup").GetInt32());
        Assert.Equal(1, listed.GetProperty("groups").GetInt32());
    }

    [Fact]
    public void AHostileNameIsLiteralText()
    {
        JsonElement listed = Scripted.Value.Listed;

        Assert.Contains(HostileName, listed.GetProperty("text").GetString()!);
        Assert.Equal(0, listed.GetProperty("injected").GetInt32());
    }

    /// <summary>A summary with no contacts - every review before feature 010 - renders no list at all.</summary>
    [Fact]
    public void NoContactsRendersNothing()
    {
        JsonElement none = Scripted.Value.None;

        Assert.Equal(0, none.GetProperty("folds").GetInt32());
        Assert.False(none.GetProperty("rendered").GetBoolean(), "an empty contacts section takes room.");
    }

    private static Run Drive()
    {
        var run = new Run();

        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.RouteAttention("chat-1", SummarySample.Json(summary =>
                {
                    summary["contacts"] = SummarySample.Contacts(HostileName);
                    summary["modelling_practice"] = JsonNode.Parse(
                        @"{""title"":""Modelling practice: 1 finding across 1 rule"",""findings"":1,""rules"":1,""finding_ids"":[""F-002""]}");
                }));
                await driver.StartReview();
                await driver.Push("chat-1", 1, "finding", Finding("F-007"));
                await driver.Push("chat-1", 2, "finding", Finding("F-002"));
                await driver.Push("chat-1", 3, "finding", Finding("F-008"));
                await driver.EndSession("chat-1");
                run.Listed = await driver.Read(ReadContacts);

                await driver.StartReview();
                await driver.RouteAttention("chat-2", SummarySample.Json());
                await driver.Push("chat-2", 1, "finding", Finding("F-007"));
                await driver.EndSession("chat-2");
                run.None = await driver.Read(ReadContacts);
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
        component_ids = new[] { "cmp:0002", "cmp:0003" },
        observed = "Observed for " + id + ".",
    });

    private const string ReadContacts = @"
var folds = document.querySelectorAll('details.contacts');
var fold = folds[0] || null;
var cards = document.querySelectorAll('.card.finding');
var afterEveryCard = !!fold;
for (var i = 0; i < cards.length; i++) { if (!h.before(cards[i], fold)) { afterEveryCard = false; } }
var lines = fold ? fold.querySelectorAll('.contact') : [];
var ids = [], lineFolds = [];
for (var j = 0; j < lines.length; j++) {
  var own = lines[j].querySelector('details');
  ids.push(own ? (h.text(own, '.contact-ids') || '') : '');
  lineFolds.push(own ? (own.open ? 'open' : 'shut') : 'none');
}
var section = document.getElementById('contacts');
return JSON.stringify({
  ok: true,
  folds: folds.length,
  open: fold ? fold.open : null,
  head: fold ? h.text(fold, ':scope > summary') : null,
  afterEveryCard: afterEveryCard,
  texts: h.texts(fold, '.contact .contact-text'),
  kinds: h.texts(fold, '.contact .contact-kind'),
  configurations: h.texts(fold, '.contact .contact-configuration'),
  ids: ids,
  lineFolds: lineFolds,
  inCards: document.querySelectorAll('.card.finding .contact').length,
  inStartHere: document.querySelectorAll('#attention-panel .contact').length,
  inGroup: document.querySelectorAll('.finding-group .contact').length,
  groups: document.querySelectorAll('.finding-group').length,
  text: fold ? fold.textContent : '',
  injected: h.injected(fold),
  rendered: h.rendered(section)
});";

    private sealed class Run
    {
        public JsonElement Listed { get; set; }

        public JsonElement None { get; set; }
    }
}
