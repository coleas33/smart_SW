using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;
using Xunit.Abstractions;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T048: SC-006 and the performance bound of contracts/views.md section 7, as feature
/// 013 T053 amends them (contracts/grouped-list.md section 5).
///
/// <b>SC-006</b>: every finding of a 99-finding review is reachable from the top of Results in at
/// most two clicks - one for a card in an open group (its row), two for a card in a collapsed one
/// (the group, then the row). On the big assembly 94 of 99 findings had no path at all before
/// feature 009. The review here is generated in the shape research R2.3 gives that run - 99
/// findings, 51 of them modelling practice, whose group arrives collapsed - with and without the
/// collapse; the same assertion on the committed big-assembly pane fixture joins the acceptance
/// tests once 013 T056 has regenerated it with its groups.
///
/// <b>The bound</b>: 1,000 findings and a 1,000-row grouped ranking are rendered into Results
/// within 3 s offscreen, every card moved into its row and the first row in view (research R2.25:
/// measured first, paged only if the measurement asks for it). Driven here through the live
/// stream - every finding event and the ranking route, the same renderers a restored snapshot goes
/// through - at the widest docked pane, 420 px, and a docked pane's height.
/// </summary>
public sealed class ReviewPageScaleTests
{
    private const int FamilySize = 51;

    private readonly ITestOutputHelper _output;

    public ReviewPageScaleTests(ITestOutputHelper output)
    {
        _output = output;
    }

    [Fact]
    public void EveryFindingOfTheBigReviewIsReachedFromTheTopOfResultsInAtMostTwoClicksWithTheCollapsedGroup()
    {
        JsonElement reach = Reach(collapseModellingPractice: true);

        Assert.Equal(99, reach.GetProperty("cards").GetInt32());
        Assert.Equal(99, reach.GetProperty("reached").GetInt32());
        Assert.Equal(99 - FamilySize, reach.GetProperty("oneClick").GetInt32());
        Assert.Equal(FamilySize, reach.GetProperty("twoClicks").GetInt32());
        Assert.True(reach.GetProperty("most").GetInt32() <= 2, "a finding needs more than two clicks: " + reach);
        Assert.Equal(2, reach.GetProperty("groups").GetInt32());
    }

    [Fact]
    public void EveryFindingOfTheBigReviewIsReachedInOneClickWhenEveryGroupIsOpen()
    {
        JsonElement reach = Reach(collapseModellingPractice: false);

        Assert.Equal(99, reach.GetProperty("cards").GetInt32());
        Assert.Equal(99, reach.GetProperty("oneClick").GetInt32());
        Assert.Equal(1, reach.GetProperty("most").GetInt32());
    }

    [Fact]
    public void AThousandFindingsAndAThousandGroupedRowsAreRenderedIntoResultsWithinThreeSeconds()
    {
        const int count = 1000;
        long elapsed = -1;
        JsonElement after = default;

        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.Page.CallDevToolsProtocolMethodAsync(
                    "Emulation.setDeviceMetricsOverride",
                    JsonSerializer.Serialize(new { width = 420, height = 800, deviceScaleFactor = 1, mobile = false }));
                // No summary: the bound is about the findings and the rows, and the first row must
                // be on screen at the top of Results without a scroll.
                string[] ids = Ids(count, "F-{0:0000}");
                await driver.RouteAttention("chat-1", Ranking(ids, family: null, collapse: false, withSummary: false));
                await driver.StartReview();

                Stopwatch watch = Stopwatch.StartNew();
                int seq = 0;
                foreach (string id in ids)
                {
                    Frame(driver, "chat-1", SseFrames.Frame(++seq, "finding", Finding(id, "interference.static")));
                }

                foreach (string frame in SseFrames.ContractSampleFrames())
                {
                    Frame(driver, "chat-1", frame);
                }

                bool done = false;
                while (!done && watch.ElapsedMilliseconds < 15000)
                {
                    string raw = await driver.Page.ExecuteScriptAsync(
                        "document.querySelectorAll('#findings-by-type details.type-row .card.finding').length === " + count);
                    done = raw == "true";
                    if (!done)
                    {
                        await Task.Delay(10);
                    }
                }

                watch.Stop();
                elapsed = done ? watch.ElapsedMilliseconds : -1;
                after = await driver.Read(@"
var results = document.getElementById('results');
var row = document.querySelector('#findings-by-type details.type-row');
var first = row ? row.querySelector('.card.finding') : null;
return JSON.stringify({
  ok: true,
  firstRowId: row ? row.getAttribute('data-finding-id') : null,
  firstRowInView: h.inView(row),
  firstId: first ? first.getAttribute('data-finding-id') : null,
  resultsTop: results.scrollTop
});");
            });

        _output.WriteLine("1,000 findings and a 1,000-row grouped ranking rendered in " + elapsed + " ms. " + after);
        Assert.True(elapsed >= 0, "the page never finished grouping 1,000 findings.");
        Assert.True(elapsed < 3000, "rendering 1,000 findings grouped took " + elapsed + " ms, over the 3 s bound.");

        // The first row of Results is on screen with Results at its top, and the first finding's
        // card is in it, not paged away (research R2.25).
        Assert.Equal("F-0001", after.GetProperty("firstRowId").GetString());
        Assert.True(after.GetProperty("firstRowInView").GetBoolean(), "the first row of Results is not in view.");
        Assert.Equal("F-0001", after.GetProperty("firstId").GetString());
        Assert.Equal(0, after.GetProperty("resultsTop").GetDouble());
    }

    // ---- the generated review -----------------------------------------------------------------

    private static JsonElement Reach(bool collapseModellingPractice)
    {
        JsonElement result = default;
        string[] ids = Ids(99, "F-{0:000}");
        string[] family = ids.Skip(99 - FamilySize).ToArray();

        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.RouteAttention("chat-1", Ranking(ids, family, collapseModellingPractice));
                await driver.StartReview();
                int seq = 0;
                foreach (string id in ids)
                {
                    await driver.Push("chat-1", ++seq, "finding",
                        Finding(id, family.Contains(id) ? "rms.sketches.fully_defined" : "interference.static"));
                }

                await driver.EndSession("chat-1");
                result = await driver.Read(ReadReach);
            });

        return result;
    }

    /// <summary>
    /// How many clicks each finding's card is from the top of Results: 1 when its group is open
    /// and one press on its row shows it, 2 when its group is collapsed and the group and then the
    /// row must be pressed. Every fold is put back as it was after each card is measured.
    /// </summary>
    private const string ReadReach = @"
var cards = document.querySelectorAll('#results .card.finding');
var oneClick = 0, twoClicks = 0, reached = 0, most = 0;
var visible = function (card) { return card.querySelector('.card-head').checkVisibility(); };
for (var i = 0; i < cards.length; i++) {
  var clicks = 0;
  var row = cards[i].closest('details.type-row');
  var group = cards[i].closest('details.type-group');
  var groupWasOpen = !!(group && group.open);
  if (!visible(cards[i]) && group && !group.open) { group.querySelector(':scope > summary').click(); clicks++; }
  if (!visible(cards[i]) && row && !row.open) { row.querySelector(':scope > summary').click(); clicks++; }
  if (!visible(cards[i])) { clicks = 99; }
  if (row) { row.open = false; }
  if (group) { group.open = groupWasOpen; }
  if (clicks === 1) { oneClick++; }
  if (clicks === 2) { twoClicks++; }
  if (clicks <= 2) { reached++; }
  if (clicks > most) { most = clicks; }
}
return JSON.stringify({
  ok: true,
  cards: cards.length,
  reached: reached,
  oneClick: oneClick,
  twoClicks: twoClicks,
  most: most,
  groups: document.querySelectorAll('#findings-by-type details.type-group').length
});";

    private static string[] Ids(int count, string format) =>
        Enumerable.Range(1, count).Select(index => string.Format(format, index)).ToArray();

    /// <summary>
    /// A ranking of the findings with its groups, and a summary: with no family, one open group of
    /// one row per finding; with one, the other findings folded three and two to a row in an open
    /// Interference and fit group, and the family's findings in a Modelling practice group, folded
    /// by rule into twelve rows - research R2.3's shape.
    /// </summary>
    private static string Ranking(string[] ids, string[]? family, bool collapse, bool withSummary = true)
    {
        var interference = new List<object>();
        var modelling = new List<object>();
        if (family == null)
        {
            interference.AddRange(ids.Select(id => Row(id, new[] { id }, "interference.static")));
        }
        else
        {
            string[] rest = ids.Except(family).ToArray();
            for (int at = 0; at < rest.Length;)
            {
                int size = interference.Count < 14 ? 3 : 2;
                interference.Add(Row(rest[at], rest.Skip(at).Take(size).ToArray(), "interference.static"));
                at += size;
            }

            for (int rule = 0, at = 0; rule < 12; rule++)
            {
                int size = rule < 11 ? 4 : family.Length - at;
                modelling.Add(Row(family[at], family.Skip(at).Take(size).ToArray(), "rms.sketches.fully_defined"));
                at += size;
            }
        }

        var groups = new List<object> { Group("interference_fit", "Interference and fit", true, interference) };
        if (modelling.Count > 0)
        {
            groups.Add(Group("modelling_practice", "Modelling practice", !collapse, modelling));
        }

        JsonObject ranking = JsonNode.Parse(JsonSerializer.Serialize(new
        {
            policy_version = "attention_policy_v1",
            rows = interference.Concat(modelling).ToArray(),
            top_n = 5,
            not_amplified = new { total = 0, checked_within_scope = 0, dispositioned = 0, info = 0, beyond_top_n = ids.Length - 5 },
            empty_reason = (string?)null,
            groups = new { version = 1, groups, @checked = (object?)null },
        }))!.AsObject();

        if (withSummary)
        {
            ranking["summary"] = SummarySample.Summary();
        }

        return ranking.ToJsonString();
    }

    private static object Group(string id, string title, bool open, List<object> rows) => new
    {
        id,
        title,
        open,
        findings = rows.Count,
        decided = 0,
        text = rows.Count + " rows",
        rows,
        goals = new object[0],
    };

    private static object Row(string id, string[] members, string check) => new Dictionary<string, object?>
    {
        { "finding_id", id },
        { "member_finding_ids", members },
        { "check", check },
        { "title", "Finding " + id },
        { "status", "demonstrated" },
        { "severity", "low" },
        { "component_ids", new[] { "cmp:0002" } },
        { "consequence_class", "interface" },
        { "key", new Dictionary<string, object> { { "judgement", 1 } } },
        { "reason", "interface, demonstrated" },
        { "source", "code" },
        { "tail_text", members.Length > 1 ? "×" + members.Length : null },
        { "reach_text", "reaches 1 component" },
        { "hide_card_title", members.Length == 1 },
        { "chip", null },
    };

    private static string Finding(string id, string check) => JsonSerializer.Serialize(new
    {
        id,
        check,
        title = "Finding " + id,
        status = "demonstrated",
        severity = "low",
        component_ids = new[] { "cmp:0002" },
        observed = "Observed for " + id + ".",
        requirement = "The requirement the check holds it to.",
        recommended_action = "What to do about it.",
    });

    /// <summary>One `events.frame`, posted without waiting, so a thousand of them are one burst.</summary>
    private static void Frame(ReviewPageDriver driver, string chatId, string frame) =>
        driver.Page.PostWebMessageAsJson(JsonSerializer.Serialize(
            new { type = "events.frame", id = (string?)null, payload = new { chat_id = chatId, frame } }));
}
