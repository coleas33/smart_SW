using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 011 T092 (rewritten deliberately from T082's keyed replacement, after the review
/// finding of 2026-09-23): the coverage panel holds what the session holds.
///
/// The backend restates coverage by dropping items and appending new ones, and the stream says
/// both: a `coverage` event appends its item, and a `coverage.withdrawn` event - emitted by
/// `ToolContext.withdraw_coverage`, the one place an announced item leaves the session - drops
/// every item of its `checks` from each of its `buckets` (specs/002-task-pane-assistant/contracts/
/// chat-events.schema.json). So the page identifies no item with another: two items the session
/// holds side by side - one check over one scope, skipped and checked, or a tool that failed twice
/// - stay two lines, as they are in `report.md`; a restated check is one line because the backend
/// withdrew the first; and a restored snapshot, being the session after every withdrawal, is
/// printed as it came.
///
/// <b>Membership, not ranking.</b> Nothing is sorted, and the only test on a bucket is whether
/// the backend named it (<see cref="PageRuleScanTests"/> holds the source to it). Driven, because
/// "a withdrawal drops what it names and nothing else" and "a restored review keeps what the
/// session kept" are things only a page that received the events can show.
/// </summary>
public sealed class ReviewPageCoverageTests
{
    private const string PathA = @"C:\parts\bracket.sldasm";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    /// <summary>
    /// `compare_with_profile` writes a drawing's conformance skipped (the profile leaves a setting
    /// empty) and checked (the rest agree): one check, one scope, two items in the session. A tool
    /// that failed twice is two `failed` items of one check over the empty scope. Each is a line.
    /// </summary>
    [Fact]
    public void ItemsTheBackendHoldsSideBySideStaySideBySide()
    {
        JsonElement live = Scripted.Value.SideBySide;

        Assert.Equal(
            new[] { "drawing_profile.conformance - the profile leaves sheet formats empty" },
            ReviewPageDriver.Strings(live, "skipped"));
        Assert.Equal(
            new[] { "drawing_profile.conformance - agrees in projection and unit" },
            ReviewPageDriver.Strings(live, "checked"));
        Assert.Equal(
            new[]
            {
                "tool.query_package - tool query_package failed [first refusal]",
                "tool.query_package - tool query_package failed [second refusal]",
            },
            ReviewPageDriver.Strings(live, "failed"));
        Assert.Equal("1 checked · 1 skipped · 2 failed", live.GetProperty("counts").GetString());
    }

    /// <summary>
    /// The drawing check after a confirmed read, as the backend streams it: the first items, a
    /// withdrawal of its two checks from the buckets that held them, then the restated items. The
    /// panel shows the restatement once, in the backend's order, and keeps every item of another
    /// check - the confirmed open's own, and an item of the withdrawn check in a bucket the
    /// withdrawal did not name.
    /// </summary>
    [Fact]
    public void AWithdrawalDropsWhatItNamesAndTheRestatementFollows()
    {
        JsonElement live = Scripted.Value.Restated;

        Assert.Equal(
            new[]
            {
                "drawing.confirmed_open - opened read-only, read and closed (1 sheet)",
                "drawing.context - read from housing.SLDDRW; 1 view usable",
                "drawing.context - read from bracket-assy.SLDDRW; 2 views usable",
            },
            ReviewPageDriver.Strings(live, "checked"));
        Assert.Empty(ReviewPageDriver.Strings(live, "skipped"));
        Assert.Equal(
            new[] { "drawing.context - a bucket the withdrawal did not name" },
            ReviewPageDriver.Strings(live, "unresolved"));
    }

    /// <summary>
    /// A withdrawal is the backend's two lists, as sent: a check it did not name keeps its item in
    /// a bucket it did name, and a withdrawal naming what the panel does not hold changes nothing.
    /// </summary>
    [Fact]
    public void AWithdrawalTouchesOnlyTheChecksAndBucketsItNames()
    {
        JsonElement live = Scripted.Value.Restated;

        Assert.Equal(
            new[] { "hygiene - a check the withdrawal did not name" },
            ReviewPageDriver.Strings(live, "outOfScope"));
        Assert.Equal("3 checked · 1 unresolved · 1 out of scope", live.GetProperty("counts").GetString());
        Assert.Equal(5, ReviewPageDriver.Strings(live, "all").Length);
        Assert.Equal(0, live.GetProperty("injected").GetInt32());
    }

    /// <summary>
    /// A restored review prints the snapshot's coverage as it came - the session after every
    /// withdrawal, so one check over one scope in two buckets is two lines - and once the reload of
    /// a running chat is live again, a withdrawal and a restatement act on the restored items as on
    /// live ones.
    /// </summary>
    [Fact]
    public void ARestoredReviewPrintsTheSnapshotAsItCameAndALiveWithdrawalActsOnIt()
    {
        JsonElement restored = Scripted.Value.Restored;
        JsonElement afterLive = Scripted.Value.RestoredThenLive;

        Assert.Equal(new[] { "drawing.context - checked in the snapshot" }, ReviewPageDriver.Strings(restored, "checked"));
        Assert.Equal(new[] { "drawing.context - skipped in the snapshot" }, ReviewPageDriver.Strings(restored, "skipped"));
        Assert.Equal(new[] { "drawing.confirmed_open - not yet opened" }, ReviewPageDriver.Strings(restored, "unresolved"));

        Assert.Equal(
            new[] { "drawing.context - the live restatement", "drawing.confirmed_open - read as it stood" },
            ReviewPageDriver.Strings(afterLive, "checked"));
        Assert.Empty(ReviewPageDriver.Strings(afterLive, "skipped"));
        Assert.Equal(new[] { "drawing.confirmed_open - not yet opened" }, ReviewPageDriver.Strings(afterLive, "unresolved"));
    }

    /// <summary>
    /// The Transcript of a restored review replays the stream from its start, and the snapshot
    /// already holds what each coverage event and withdrawal did: a replayed withdrawal drops
    /// nothing and a replayed coverage event adds nothing.
    /// </summary>
    [Fact]
    public void AReplayedWithdrawalOrCoverageEventLeavesTheRestoredPanelAsItWas()
    {
        JsonElement before = Scripted.Value.BeforeReplay;
        JsonElement after = Scripted.Value.AfterReplay;

        Assert.Equal(ReviewPageDriver.Strings(before, "all"), ReviewPageDriver.Strings(after, "all"));
        Assert.Equal(before.GetProperty("counts").GetString(), after.GetProperty("counts").GetString());
        Assert.Equal(3, ReviewPageDriver.Strings(after, "all").Length);
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static Run Drive()
    {
        var run = new Run();
        RunLive(run, SideBySideEvents(), (r, state) => r.SideBySide = state);
        RunLive(run, RestatedEvents(), (r, state) => r.Restated = state);
        RunRestored(run);
        RunReplayed(run);
        return run;
    }

    /// <summary>Two identities the backend holds twice each, in the order it emits them.</summary>
    private static IEnumerable<(string Type, string Body)> SideBySideEvents()
    {
        yield return ("coverage", Coverage("skipped", "drawing_profile.conformance", Documents("doc:0012"), "the profile leaves sheet formats empty"));
        yield return ("coverage", Coverage("checked", "drawing_profile.conformance", Documents("doc:0012"), "agrees in projection and unit"));
        yield return ("coverage", Coverage("failed", "tool.query_package", EmptyScope(), "tool query_package failed", "first refusal"));
        yield return ("coverage", Coverage("failed", "tool.query_package", EmptyScope(), "tool query_package failed", "second refusal"));
    }

    /// <summary>The drawing check restated after a confirmed read, as `check_drawings` streams it.</summary>
    private static IEnumerable<(string Type, string Body)> RestatedEvents()
    {
        yield return ("coverage", Coverage("skipped", "drawing.context", Documents("doc:0004"), "no open drawing shows it; a drawing with its name sits beside it (candidate)"));
        yield return ("coverage", Coverage("checked", "drawing.context", Documents("doc:0002"), "read from bracket-assy.SLDDRW; 2 views usable"));
        yield return ("coverage", Coverage("unresolved", "drawing.context", Documents("doc:0009"), "a bucket the withdrawal did not name"));
        yield return ("coverage", Coverage("out_of_scope", "hygiene", null, "a check the withdrawal did not name"));
        yield return ("coverage", Coverage("checked", "drawing.confirmed_open", Documents("doc:0004"), "opened read-only, read and closed (1 sheet)"));
        yield return ("coverage.withdrawn", Withdrawn(new[] { "drawing.context", "drawing_profile.conformance" }, new[] { "skipped", "checked", "out_of_scope" }));
        yield return ("coverage", Coverage("checked", "drawing.context", Documents("doc:0004"), "read from housing.SLDDRW; 1 view usable"));
        yield return ("coverage", Coverage("checked", "drawing.context", Documents("doc:0002"), "read from bracket-assy.SLDDRW; 2 views usable"));
        yield return ("coverage.withdrawn", Withdrawn(new[] { "rms.part.grouping" }, new[] { "failed" }));
    }

    /// <summary>A live review: the events arrive in the order a restating backend emits them.</summary>
    private static void RunLive(Run run, IEnumerable<(string Type, string Body)> events, Action<Run, JsonElement> keep)
    {
        ReviewPageDriver.Run(
            null,
            async driver =>
            {
                await driver.StartReview();

                int seq = 0;
                foreach ((string type, string body) in events)
                {
                    await driver.Push("chat-1", ++seq, type, body);
                }

                await driver.Settle();
                keep(run, await driver.Read(ReadCoverage));
            });
    }

    /// <summary>
    /// A page reload while the chat runs: the snapshot is restored at init, and the events after its
    /// last seq are live.
    /// </summary>
    private static void RunRestored(Run run)
    {
        Dictionary<string, object?> item = ReviewPageSessionsTests.Item("chat-7", "20260923-091500-bracket-7", PathA, 9, 15);

        ReviewPageDriver.Run(
            driver =>
            {
                driver.Document = new { path = PathA, configuration = "Default" };
                driver.Sessions.Add(item);
                driver.InitialRoutes.Add(("GET", "/sessions/chat-7/snapshot", 200, Snapshot("20260923-091500-bracket-7", "running", 1)));
            },
            async driver =>
            {
                run.Restored = await driver.Read(ReadCoverage);

                await driver.Push("chat-7", 2, "coverage.withdrawn", Withdrawn(new[] { "drawing.context" }, new[] { "checked", "skipped" }));
                await driver.Push("chat-7", 3, "coverage", Coverage("checked", "drawing.context", Documents("doc:0004"), "the live restatement"));
                await driver.Push("chat-7", 4, "coverage", Coverage("checked", "drawing.confirmed_open", Documents("doc:0005"), "read as it stood"));
                await driver.Settle();
                run.RestoredThenLive = await driver.Read(ReadCoverage);
            });
    }

    /// <summary>
    /// An ended review restored at init, then its Transcript: the stream is replayed from its start
    /// up to the snapshot's last seq, a withdrawal and a coverage event among the replayed events.
    /// </summary>
    private static void RunReplayed(Run run)
    {
        Dictionary<string, object?> item = ReviewPageSessionsTests.Item("chat-8", "20260923-093000-bracket-8", PathA, 9, 30);

        ReviewPageDriver.Run(
            driver =>
            {
                driver.Document = new { path = PathA, configuration = "Default" };
                driver.Sessions.Add(item);
                driver.InitialRoutes.Add(("GET", "/sessions/chat-8/snapshot", 200, Snapshot("20260923-093000-bracket-8", "ended", 4)));
            },
            async driver =>
            {
                run.BeforeReplay = await driver.Read(ReadCoverage);

                await driver.Click("view-transcript");
                await driver.Push("chat-8", 1, "coverage", Coverage("skipped", "drawing.context", Documents("doc:0004"), "skipped in the snapshot"));
                await driver.Push("chat-8", 2, "coverage.withdrawn", Withdrawn(new[] { "drawing.context", "drawing.confirmed_open" }, new[] { "checked", "skipped", "unresolved" }));
                await driver.Push("chat-8", 3, "coverage", Coverage("checked", "drawing.context", Documents("doc:0004"), "checked in the snapshot"));
                await driver.Push("chat-8", 4, "session.ended", @"{""ended_at"":""2026-09-23T09:40:00+00:00""}");
                await driver.Settle();
                await driver.Click("view-results");
                run.AfterReplay = await driver.Read(ReadCoverage);
            });
    }

    /// <summary>
    /// A chat's snapshot whose coverage holds one check over one scope in two buckets - the session
    /// after every withdrawal, bucket by bucket.
    /// </summary>
    private static string Snapshot(string runId, string chatState, int lastSeq) => new JsonObject
    {
        ["run_id"] = runId,
        ["read_only"] = false,
        ["read_only_reason"] = null,
        ["chat_state"] = chatState,
        ["last_seq"] = lastSeq,
        ["document"] = new JsonObject { ["path"] = PathA, ["configuration"] = "Default" },
        ["findings"] = new JsonArray(),
        ["evidence_requests"] = new JsonArray(),
        ["coverage"] = new JsonArray(
            JsonNode.Parse(Coverage("checked", "drawing.context", Documents("doc:0004"), "checked in the snapshot")),
            JsonNode.Parse(Coverage("skipped", "drawing.context", Documents("doc:0004"), "skipped in the snapshot")),
            JsonNode.Parse(Coverage("unresolved", "drawing.confirmed_open", Documents("doc:0005"), "not yet opened"))),
        ["ranking"] = null,
        ["not_examined"] = null,
    }.ToJsonString();

    /// <summary>One `coverage` event body; a null scope sends the item with no scope member at all.</summary>
    private static string Coverage(string bucket, string check, JsonObject? scope, string reason, string? error = null)
    {
        var item = new JsonObject { ["check"] = check };
        if (scope != null)
        {
            item["scope"] = scope;
        }

        item["reason"] = reason;
        item["error"] = error;
        return new JsonObject { ["bucket"] = bucket, ["item"] = item }.ToJsonString();
    }

    /// <summary>One `coverage.withdrawn` event body, the two lists as the backend sends them.</summary>
    private static string Withdrawn(string[] checks, string[] buckets) => new JsonObject
    {
        ["checks"] = new JsonArray(Array.ConvertAll(checks, check => (JsonNode?)JsonValue.Create(check))),
        ["buckets"] = new JsonArray(Array.ConvertAll(buckets, bucket => (JsonNode?)JsonValue.Create(bucket))),
    }.ToJsonString();

    /// <summary>A scope as the backend dumps it: every list present, the named documents in one.</summary>
    private static JsonObject Documents(params string[] documentIds)
    {
        JsonObject scope = EmptyScope();
        scope["document_ids"] = new JsonArray(Array.ConvertAll(documentIds, id => (JsonNode?)JsonValue.Create(id)));
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
  failed: h.texts(panel, '.bucket-failed .bucket-item'),
  outOfScope: h.texts(panel, '.bucket-out_of_scope .bucket-item'),
  injected: h.injected(panel)
});";

    private sealed class Run
    {
        public JsonElement SideBySide { get; set; }

        public JsonElement Restated { get; set; }

        public JsonElement Restored { get; set; }

        public JsonElement RestoredThenLive { get; set; }

        public JsonElement BeforeReplay { get; set; }

        public JsonElement AfterReplay { get; set; }
    }
}
