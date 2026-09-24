using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 011 T082 (docs/review-backlog.md, "Feature 011: open follow-ups", the item on
/// `app.js`'s coverage events): the coverage panel holds one item per identity.
///
/// A coverage event's identity is its item's `check` and `scope` - the two fields of
/// `CoverageItem` (specs/001-agentic-design-review/contracts/review-session.schema.json) that say
/// what was covered; its bucket, reason and error say what became of it. A later event with the
/// same identity replaces the earlier item wherever it sat, and takes its place at the end of the
/// arrival order, which is where the backend's own restatement puts it in the session: a check the
/// backend restates (`check_drawings` after a confirmed read) or a summary row that moved bucket is
/// one line on the page, as it is one in the session and in `report.md`, instead of its first and
/// restated items side by side until the page reloads the session.
///
/// <b>Keyed replacement, not ranking.</b> Nothing is sorted, no bucket, status or severity is
/// compared, and a scope's lists are compared in the order the backend sent them
/// (<see cref="PageRuleScanTests"/> holds the source to it). Driven, because "a later event
/// replaces an earlier one" and "a restored review keeps the rule" are things only a page that
/// received the events can show.
/// </summary>
public sealed class ReviewPageCoverageTests
{
    private const string PathA = @"C:\parts\bracket.sldasm";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    /// <summary>
    /// The candidate's drawing context, skipped, is restated checked once the drawing is read: one
    /// item, in the checked bucket, after the confirmed read's own item - and a restatement that
    /// says the same thing again moves that item to the end rather than printing it twice.
    /// </summary>
    [Fact]
    public void ALaterEventForTheSameCheckAndScopeReplacesTheEarlierItemEvenInAnotherBucket()
    {
        JsonElement live = Scripted.Value.Live;

        Assert.Equal(
            new[]
            {
                "drawing.confirmed_open - opened read-only, read and closed (1 sheet)",
                "drawing.context - read from housing.SLDDRW; 1 view usable",
                "drawing.context - read from bracket-assy.SLDDRW; 2 views usable",
            },
            ReviewPageDriver.Strings(live, "checked"));
        Assert.DoesNotContain(
            "drawing.context - no open drawing shows it; a drawing with its name sits beside it (candidate)",
            ReviewPageDriver.Strings(live, "all"));
    }

    /// <summary>
    /// Another scope is another item: the same check over another configuration, and over the
    /// same pair spelt in the other order - the page compares the backend's lists as sent and
    /// sorts nothing - each stands beside the first.
    /// </summary>
    [Fact]
    public void TheSameCheckOverAnotherScopeIsAnotherItem()
    {
        JsonElement live = Scripted.Value.Live;

        Assert.Equal(
            new[]
            {
                "interfaces.fit - no limits on the drawing",
                "interfaces.fit - no limits in the machined configuration",
                "interfaces.fit - no limits, the pair spelt the other way",
            },
            ReviewPageDriver.Strings(live, "unresolved"));
    }

    /// <summary>
    /// An item sent with no scope, one with an empty scope object and one with every scope list
    /// empty and no configuration name the same coverage - the contract's empty scope - so each
    /// replaces the one before, whatever its bucket.
    /// </summary>
    [Fact]
    public void AnAbsentScopeAnEmptyScopeAndAScopeOfEmptyListsAreOneIdentity()
    {
        JsonElement live = Scripted.Value.Live;

        Assert.Equal(new[] { "hygiene - the third statement of the family" }, ReviewPageDriver.Strings(live, "skipped"));
        Assert.Empty(ReviewPageDriver.Strings(live, "outOfScope"));
    }

    /// <summary>The fold's count line counts the items the panel lists, not the events that arrived.</summary>
    [Fact]
    public void TheCountLineCountsItemsNotEvents()
    {
        JsonElement live = Scripted.Value.Live;

        Assert.Equal("3 checked · 1 skipped · 3 unresolved", live.GetProperty("counts").GetString());
        Assert.Equal(7, ReviewPageDriver.Strings(live, "all").Length);
        Assert.Equal(0, live.GetProperty("injected").GetInt32());
    }

    /// <summary>
    /// A restored review goes through the same rule: a snapshot that listed one identity twice
    /// shows it once, the later one; and once the replay of a running chat has caught up, a live
    /// event replaces a restored item rather than standing beside it.
    /// </summary>
    [Fact]
    public void ARestoredReviewKeepsOneItemPerIdentityAndALiveEventReplacesARestoredOne()
    {
        JsonElement restored = Scripted.Value.Restored;
        JsonElement afterLive = Scripted.Value.RestoredThenLive;

        Assert.Equal(new[] { "drawing.context - the later restatement" }, ReviewPageDriver.Strings(restored, "checked"));
        Assert.Empty(ReviewPageDriver.Strings(restored, "skipped"));
        Assert.Equal(new[] { "drawing.confirmed_open - not yet opened" }, ReviewPageDriver.Strings(restored, "unresolved"));

        Assert.Equal(
            new[] { "drawing.context - the later restatement", "drawing.confirmed_open - read as it stood" },
            ReviewPageDriver.Strings(afterLive, "checked"));
        Assert.Empty(ReviewPageDriver.Strings(afterLive, "unresolved"));
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static Run Drive()
    {
        var run = new Run();
        RunLive(run);
        RunRestored(run);
        return run;
    }

    /// <summary>A live review: the events arrive in the order a restating backend emits them.</summary>
    private static void RunLive(Run run)
    {
        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.StartReview();

                int seq = 0;
                foreach (string body in new[]
                {
                    Coverage("skipped", "drawing.context", Documents("doc:0004"), "no open drawing shows it; a drawing with its name sits beside it (candidate)"),
                    Coverage("checked", "drawing.context", Documents("doc:0002"), "read from bracket-assy.SLDDRW; 2 views usable"),
                    Coverage("unresolved", "interfaces.fit", Pair("cmp:0001", "cmp:0002", "Default"), "no limits on the drawing"),
                    Coverage("checked", "drawing.confirmed_open", Documents("doc:0004"), "opened read-only, read and closed (1 sheet)"),
                    Coverage("checked", "drawing.context", Documents("doc:0004"), "read from housing.SLDDRW; 1 view usable"),
                    Coverage("checked", "drawing.context", Documents("doc:0002"), "read from bracket-assy.SLDDRW; 2 views usable"),
                    Coverage("unresolved", "interfaces.fit", Pair("cmp:0001", "cmp:0002", "Machined"), "no limits in the machined configuration"),
                    Coverage("unresolved", "interfaces.fit", Pair("cmp:0002", "cmp:0001", "Default"), "no limits, the pair spelt the other way"),
                    Coverage("out_of_scope", "hygiene", null, "the first statement of the family"),
                    Coverage("skipped", "hygiene", new JsonObject(), "the second statement of the family"),
                    Coverage("skipped", "hygiene", EmptyScope(), "the third statement of the family"),
                })
                {
                    await driver.Push("chat-1", ++seq, "coverage", body);
                }

                await driver.Settle();
                run.Live = await driver.Read(ReadCoverage);
            });
    }

    /// <summary>
    /// A page reload while the chat runs: the snapshot is restored at init, the stream replays up
    /// to its last seq, and the event after that is live.
    /// </summary>
    private static void RunRestored(Run run)
    {
        Dictionary<string, object?> item = ReviewPageSessionsTests.Item("chat-7", "20260923-091500-bracket-7", PathA, 9, 15);

        ReviewPageDriver.Run(
            driver =>
            {
                driver.Document = new { path = PathA, configuration = "Default" };
                driver.Sessions.Add(item);
                driver.InitialRoutes.Add(("GET", "/sessions/chat-7/snapshot", 200, RunningSnapshot()));
            },
            async driver =>
            {
                run.Restored = await driver.Read(ReadCoverage);

                // The replay reaches the snapshot's last seq; the next event is live.
                await driver.Push("chat-7", 1, "coverage", Coverage("checked", "drawing.context", Documents("doc:0004"), "the later restatement"));
                await driver.Push("chat-7", 2, "coverage", Coverage("checked", "drawing.confirmed_open", Documents("doc:0005"), "read as it stood"));
                await driver.Settle();
                run.RestoredThenLive = await driver.Read(ReadCoverage);
            });
    }

    /// <summary>A running chat's snapshot whose coverage lists one identity twice, the later restated.</summary>
    private static string RunningSnapshot() => new JsonObject
    {
        ["run_id"] = "20260923-091500-bracket-7",
        ["read_only"] = false,
        ["read_only_reason"] = null,
        ["chat_state"] = "running",
        ["last_seq"] = 1,
        ["document"] = new JsonObject { ["path"] = PathA, ["configuration"] = "Default" },
        ["findings"] = new JsonArray(),
        ["evidence_requests"] = new JsonArray(),
        ["coverage"] = new JsonArray(
            JsonNode.Parse(Coverage("skipped", "drawing.context", Documents("doc:0004"), "the first statement")),
            JsonNode.Parse(Coverage("unresolved", "drawing.confirmed_open", Documents("doc:0005"), "not yet opened")),
            JsonNode.Parse(Coverage("checked", "drawing.context", Documents("doc:0004"), "the later restatement"))),
        ["ranking"] = null,
        ["not_examined"] = null,
    }.ToJsonString();

    /// <summary>One `coverage` event body; a null scope sends the item with no scope member at all.</summary>
    private static string Coverage(string bucket, string check, JsonObject? scope, string reason)
    {
        var item = new JsonObject { ["check"] = check };
        if (scope != null)
        {
            item["scope"] = scope;
        }

        item["reason"] = reason;
        item["error"] = null;
        return new JsonObject { ["bucket"] = bucket, ["item"] = item }.ToJsonString();
    }

    /// <summary>A scope as the backend dumps it: every list present, the named documents in one.</summary>
    private static JsonObject Documents(params string[] documentIds)
    {
        JsonObject scope = EmptyScope();
        scope["document_ids"] = new JsonArray(Array.ConvertAll(documentIds, id => (JsonNode?)JsonValue.Create(id)));
        return scope;
    }

    private static JsonObject Pair(string first, string second, string configuration)
    {
        JsonObject scope = EmptyScope();
        scope["component_ids"] = new JsonArray(JsonValue.Create(first), JsonValue.Create(second));
        scope["pairs"] = new JsonArray(new JsonArray(JsonValue.Create(first), JsonValue.Create(second)));
        scope["configuration"] = configuration;
        return scope;
    }

    /// <summary>`CoverageScope()` as the backend dumps it: every list empty, no configuration.</summary>
    private static JsonObject EmptyScope() => new JsonObject
    {
        ["component_ids"] = new JsonArray(),
        ["pairs"] = new JsonArray(),
        ["configuration"] = null,
        ["positions"] = new JsonArray(),
        ["document_ids"] = new JsonArray(),
    };

    private const string ReadCoverage = @"
var panel = document.getElementById('coverage-panel');
return JSON.stringify({
  ok: true,
  counts: h.text(panel, 'summary .fold-count'),
  all: h.texts(panel, '.bucket-item'),
  checked: h.texts(panel, '.bucket-checked .bucket-item'),
  skipped: h.texts(panel, '.bucket-skipped .bucket-item'),
  unresolved: h.texts(panel, '.bucket-unresolved .bucket-item'),
  outOfScope: h.texts(panel, '.bucket-out_of_scope .bucket-item'),
  injected: h.injected(panel)
});";

    private sealed class Run
    {
        public JsonElement Live { get; set; }

        public JsonElement Restored { get; set; }

        public JsonElement RestoredThenLive { get; set; }
    }
}
