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
/// Feature 009 T048: SC-006 and the performance bound of contracts/views.md section 7.
///
/// <b>SC-006</b>: every finding of a 99-finding review is reachable from the top of Results in
/// at most two clicks - none for a headline card in the list (scrolling is not a click), one for
/// a card inside the modelling-practice group. On 830-02342 94 of 99 findings had no path at all.
/// The review here is generated in the shape research R2.3 gives that run - 99 findings in 18
/// issues, 51 of them modelling practice - with and without the family's group; the same
/// assertion on the committed big-assembly pane fixture joins the acceptance tests once the py
/// lane's T023 has generated it.
///
/// <b>The bound</b>: 1,000 findings and a 1,000-row ranking are rendered into Results within 3 s
/// offscreen, with the first card in view (research R2.25: measured first, paged only if the
/// measurement asks for it). Driven here through the live stream - every finding event and the
/// ranking route, the same renderers a restored snapshot goes through - at the widest docked pane,
/// 420 px, and a docked pane's height.
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
    public void EveryFindingOfTheBigReviewIsReachedFromTheTopOfResultsInAtMostTwoClicksWithTheGroup()
    {
        JsonElement reach = Reach(withFamily: true);

        Assert.Equal(99, reach.GetProperty("cards").GetInt32());
        Assert.Equal(99, reach.GetProperty("reached").GetInt32());
        Assert.Equal(48, reach.GetProperty("noClick").GetInt32());
        Assert.Equal(FamilySize, reach.GetProperty("oneClick").GetInt32());
        Assert.True(reach.GetProperty("most").GetInt32() <= 2, "a finding needs more than two clicks: " + reach);
        Assert.Equal(1, reach.GetProperty("groups").GetInt32());
    }

    [Fact]
    public void EveryFindingOfTheBigReviewIsReachedFromTheTopOfResultsWithoutAClickWhenThereIsNoGroup()
    {
        JsonElement reach = Reach(withFamily: false);

        Assert.Equal(99, reach.GetProperty("cards").GetInt32());
        Assert.Equal(99, reach.GetProperty("noClick").GetInt32());
        Assert.Equal(0, reach.GetProperty("groups").GetInt32());
    }

    [Fact]
    public void AThousandFindingsAndAThousandRowsAreRenderedIntoResultsWithinThreeSeconds()
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
                // No summary: the bound is about the findings and the rows, and the first card
                // must be on screen under Start here without a scroll.
                await driver.RouteAttention("chat-1", Ranking(Ids(count, "F-{0:0000}"), family: null, withSummary: false));
                await driver.StartReview();

                Stopwatch watch = Stopwatch.StartNew();
                int seq = 0;
                foreach (string id in Ids(count, "F-{0:0000}"))
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
                        "document.querySelectorAll('#findings .card.finding').length === " + count
                        + " && document.querySelectorAll('#attention-panel .attention-index .attention-line').length === " + (count - 5));
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
var row = document.querySelector('#attention-panel .attention-row');
var first = document.querySelector('#findings .card.finding');
return JSON.stringify({
  ok: true,
  firstRowId: row ? row.getAttribute('data-finding-id') : null,
  firstRowInView: h.inView(row),
  firstId: first ? first.getAttribute('data-finding-id') : null,
  firstRendered: !!first && first.querySelector('.card-head').checkVisibility(),
  resultsTop: results.scrollTop
});");
            });

        _output.WriteLine("1,000 findings and a 1,000-row ranking rendered in " + elapsed + " ms. " + after);
        Assert.True(elapsed >= 0, "the page never finished rendering 1,000 findings.");
        Assert.True(elapsed < 3000, "rendering 1,000 findings took " + elapsed + " ms, over the 3 s bound.");

        // The first card of Results - Start here's first row - is on screen with Results at its
        // top, and the first finding's card is rendered below it, not paged away (research R2.25).
        Assert.Equal("F-0001", after.GetProperty("firstRowId").GetString());
        Assert.True(after.GetProperty("firstRowInView").GetBoolean(), "the first card of Results is not in view.");
        Assert.Equal("F-0001", after.GetProperty("firstId").GetString());
        Assert.True(after.GetProperty("firstRendered").GetBoolean(), "the first finding's card is not rendered.");
        Assert.Equal(0, after.GetProperty("resultsTop").GetDouble());
    }

    // ---- the generated review -----------------------------------------------------------------

    private static JsonElement Reach(bool withFamily)
    {
        JsonElement result = default;
        string[] ids = Ids(99, "F-{0:000}");
        string[] family = ids.Skip(48).ToArray();

        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.RouteAttention("chat-1", Ranking(ids, withFamily ? family : null));
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
    /// How many clicks each finding's card is from the top of Results: 0 when its head is on the
    /// page (scrolling is not a click), 1 when it is inside a shut group that one press opens.
    /// </summary>
    private const string ReadReach = @"
var cards = document.querySelectorAll('#findings .card.finding');
var noClick = 0, oneClick = 0, reached = 0, most = 0;
for (var i = 0; i < cards.length; i++) {
  var head = cards[i].querySelector('.card-head');
  var clicks = 99;
  if (head.checkVisibility()) {
    clicks = 0;
  } else {
    var group = cards[i].closest('details.finding-group');
    if (group && !group.open) {
      group.querySelector(':scope > summary').click();
      if (head.checkVisibility()) { clicks = 1; }
      group.open = false;
    }
  }
  if (clicks === 0) { noClick++; }
  if (clicks === 1) { oneClick++; }
  if (clicks <= 2) { reached++; }
  if (clicks > most) { most = clicks; }
}
return JSON.stringify({
  ok: true,
  cards: cards.length,
  reached: reached,
  noClick: noClick,
  oneClick: oneClick,
  most: most,
  groups: document.querySelectorAll('.finding-group').length
});";

    private static string[] Ids(int count, string format) =>
        Enumerable.Range(1, count).Select(index => string.Format(format, index)).ToArray();

    /// <summary>
    /// A ranking of the findings, with a summary: one row per finding when there is no family;
    /// with one, the other findings folded three and two to a row and the family's findings one
    /// row at position three - 18 issues for 99 findings, research R2.3's shape.
    /// </summary>
    private static string Ranking(string[] ids, string[]? family, bool withSummary = true)
    {
        var rows = new List<object>();
        if (family == null)
        {
            rows.AddRange(ids.Select(id => Row(id, new[] { id }, "interference.static")));
        }
        else
        {
            string[] rest = ids.Except(family).ToArray();
            int at = 0;
            while (at < rest.Length)
            {
                int size = rows.Count < 14 ? 3 : 2;
                rows.Add(Row(rest[at], rest.Skip(at).Take(size).ToArray(), "interference.static"));
                at += size;
            }

            rows.Insert(2, Row(family[0], family, "rms.sketches.fully_defined"));
        }

        JsonObject ranking = JsonNode.Parse(JsonSerializer.Serialize(new
        {
            policy_version = "attention_policy_v1",
            rows,
            top_n = 5,
            not_amplified = new { total = 0, checked_within_scope = 0, dispositioned = 0, info = 0, beyond_top_n = ids.Length - 5 },
            empty_reason = (string?)null,
        }))!.AsObject();

        if (!withSummary)
        {
            return ranking.ToJsonString();
        }

        JsonObject summary = SummarySample.Summary();
        summary["modelling_practice"] = family == null
            ? null
            : JsonNode.Parse(JsonSerializer.Serialize(new
            {
                title = "Modelling practice: " + family.Length + " findings across 12 rules",
                findings = family.Length,
                rules = 12,
                finding_ids = family,
            }));
        ranking["summary"] = summary;
        return ranking.ToJsonString();
    }

    private static object Row(string id, string[] members, string check) => new
    {
        finding_id = id,
        member_finding_ids = members,
        check,
        title = "Finding " + id,
        status = "demonstrated",
        severity = "low",
        component_ids = new[] { "cmp:0002" },
        consequence_class = "interface",
        key = new Dictionary<string, object> { { "judgement", 1 } },
        reason = "interface, demonstrated",
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
