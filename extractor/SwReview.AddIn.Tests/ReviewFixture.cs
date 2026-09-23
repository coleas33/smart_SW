using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The big-assembly pane fixture (feature 009 T032): `Fixtures/review-big-assembly.json`, which
/// the backend's `tests/fixtures/pane/generate_pane_fixture.py` writes - `review_snapshot` of
/// feature 008's fictional big-assembly replay fixture plus the words file's `labels` - and a
/// Python test keeps equal to a fresh generation (research R2.24).
///
/// <b>Why a generated file and not a sample.</b> The page tests of User Stories 3 to 7 were
/// written against hand-built samples (<see cref="SummarySample"/>, <see cref="LabelsSample"/>),
/// which prove the page prints whatever it is given. This proves the page prints what the
/// backend actually produces, at the size of the review the feature was written for: 99
/// findings, 18 issues, 103 coverage rows, four questions, three parts not loaded.
///
/// <b>What it plays.</b> <see cref="Configure"/> makes the host's document the fixture's and
/// routes `/labels` before `init` (the page asks for it the moment it learns the backend);
/// <see cref="Review"/> presses Review, routes `/attention` and `/snapshot` for the chat, and
/// streams the fixture's findings, evidence requests and coverage, one usage, `turn.ended` and
/// `session.ended`, in the order a live run writes them - so the end of the turn fetches the
/// ranking and its summary exactly as it does on the workstation.
/// </summary>
internal sealed class ReviewFixture
{
    public const string FileName = "review-big-assembly.json";

    /// <summary>The chat the driver's first Review press is given.</summary>
    public const string ChatId = "chat-1";

    /// <summary>A `usage` body in the shape `chat-events.schema.json` pins.</summary>
    public const string UsageBody =
        @"{""round_index"":0,""provider"":""openai"",""model"":""gpt-5.6"",""input_tokens"":405861,"
        + @"""cached_input_tokens"":380000,""cache_write_tokens"":null,""output_tokens"":2048,"
        + @"""reasoning_tokens"":1024,""tool_result_input_tokens"":null,""total_tokens"":407909,"
        + @"""latency_s"":41.5,""cache_diagnostic"":null}";

    private const string SessionEndedBody =
        @"{""ended_at"":""2026-09-22T23:00:00+00:00"",""timing"":{""baseline_minutes"":null,"
        + @"""assisted_supervision_minutes"":0.0,""assisted_verification_minutes"":0.0,"
        + @"""false_alarm_handling_minutes"":0.0,""unattended_runtime_minutes"":12.5,""net_saved_minutes"":null}}";

    private static readonly Lazy<ReviewFixture> Loaded = new Lazy<ReviewFixture>(Read);

    private ReviewFixture(JsonElement root)
    {
        Root = root;
    }

    /// <summary>The fixture, read once per test run.</summary>
    public static ReviewFixture Value => Loaded.Value;

    public JsonElement Root { get; }

    public JsonElement Summary => Root.GetProperty("ranking").GetProperty("summary");

    public string RunId => Root.GetProperty("run_id").GetString()!;

    public string DocumentPath => Root.GetProperty("document").GetProperty("path").GetString()!;

    public string DocumentConfiguration => Root.GetProperty("document").GetProperty("configuration").GetString()!;

    /// <summary>The run folder the host's record names for the fixture's review.</summary>
    public string RunDirectory => @"C:\SwReviewRuns\" + RunId;

    public JsonElement[] Findings => Root.GetProperty("findings").EnumerateArray().ToArray();

    public JsonElement[] EvidenceRequests => Root.GetProperty("evidence_requests").EnumerateArray().ToArray();

    public JsonElement[] Coverage => Root.GetProperty("coverage").EnumerateArray().ToArray();

    public string LabelsJson => Root.GetProperty("labels").GetRawText();

    /// <summary>The document the fixture's review is of, as `init` and `review.started` name it.</summary>
    public object Document => new { path = DocumentPath, configuration = DocumentConfiguration };

    /// <summary>The ranking with its summary, optionally edited, as the attention route answers it.</summary>
    public string RankingJson(Action<JsonObject>? changeSummary = null)
    {
        JsonObject ranking = JsonNode.Parse(Root.GetProperty("ranking").GetRawText())!.AsObject();
        changeSummary?.Invoke(ranking["summary"]!.AsObject());
        return ranking.ToJsonString();
    }

    /// <summary>The snapshot the live route answers: the fixture without its labels.</summary>
    public string SnapshotJson(Action<JsonObject>? change = null)
    {
        JsonObject snapshot = JsonNode.Parse(Root.GetRawText())!.AsObject();
        snapshot.Remove("labels");
        change?.Invoke(snapshot);
        return snapshot.ToJsonString();
    }

    /// <summary>
    /// Makes the host's active document the fixture's, routes `/labels` before `init`, and
    /// makes `review.started` carry the fixture's run folder and not-examined block.
    /// </summary>
    public void Configure(ReviewPageDriver driver)
    {
        driver.Document = Document;
        driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsJson));
        driver.ReviewStarted = press => new Dictionary<string, object?>
        {
            { "chat_id", "chat-" + press },
            { "run_dir", RunDirectory },
            { "document", Document },
            { "not_examined", Root.GetProperty("not_examined") },
        };
    }

    /// <summary>
    /// Presses Review and plays the fixture's review to its end: the findings, the evidence
    /// requests and the coverage as a live run streams them, one usage, then `turn.ended` and
    /// `session.ended`, which fetch the ranking and its summary.
    /// </summary>
    public async Task Review(ReviewPageDriver driver, string? rankingJson = null)
    {
        await driver.RouteAttention(ChatId, rankingJson ?? RankingJson());
        await driver.Route("GET", "/sessions/" + ChatId + "/snapshot", 200, SnapshotJson());
        await driver.StartReview();

        int seq = 0;
        foreach (JsonElement finding in Findings)
        {
            await driver.Push(ChatId, ++seq, "finding", Compact(finding));
        }

        foreach (JsonElement request in EvidenceRequests)
        {
            await driver.Push(ChatId, ++seq, "evidence.requested", Compact(request));
        }

        foreach (JsonElement coverage in Coverage)
        {
            await driver.Push(ChatId, ++seq, "coverage", Compact(coverage));
        }

        await driver.Push(ChatId, ++seq, "usage", UsageBody);
        await driver.Push(ChatId, ++seq, "turn.ended", @"{""reason"":""end""}");
        await driver.Push(ChatId, ++seq, "session.ended", SessionEndedBody);
        await driver.Settle();
    }

    /// <summary>The string values of one array property of the summary, each item's <paramref name="field"/>.</summary>
    public string[] SummaryStrings(string list, string field) =>
        Summary.GetProperty(list).EnumerateArray()
            .Select(item => item.GetProperty(field).ValueKind == JsonValueKind.Null ? string.Empty : item.GetProperty(field).GetString() ?? string.Empty)
            .ToArray();

    /// <summary>
    /// One event body on one line: the fixture file is indented, and an SSE `data` line ends at
    /// the first newline, so a body is re-serialized compact before it is framed.
    /// </summary>
    public static string Compact(JsonElement body) => JsonSerializer.Serialize(body);

    private static ReviewFixture Read()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "Fixtures", FileName);
        Assert.True(
            File.Exists(path),
            FileName + " was not copied next to the test assembly; check the Content item in the csproj, "
            + "and regenerate it with `uv run python tests/fixtures/pane/generate_pane_fixture.py --write` from reviewer/.");
        return new ReviewFixture(JsonDocument.Parse(File.ReadAllText(path)).RootElement.Clone());
    }
}
