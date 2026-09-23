using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T056: one review per model, kept (User Story 6, FR-020 to FR-023,
/// contracts/sessions.md sections 5 to 8).
///
/// A normal night is an assembly, then a pin, then a plate. Before this feature the second
/// review threw the first away, or the first stayed painted under the second. Now the host keeps
/// a record of every review for the SOLIDWORKS session (`sessions.list`), the page draws a chip for
/// each, and choosing one restores that review - from the backend's live chat
/// (`GET /sessions/{chat}/snapshot`), or read-only from its run folder when the chat is gone
/// (`GET /reviews/{run_id}`) - with one GET and no tokens (SC-005). Returning to a document shows
/// its newest review; everything that acts on a review names its chat, so Show resolves against
/// the review on screen (FR-023).
///
/// The snapshots are hand-built in the contract's shape (data-model section 8); the backend
/// routes that serve them are the py lane's T051, not landed.
/// </summary>
public sealed class ReviewPageSessionsTests
{
    private const string PathA = @"C:\parts\bracket.sldasm";
    private const string PathB = @"C:\parts\pin.sldprt";
    private const string PathC = @"C:\parts\plate.sldprt";

    private const string ReadOnlyReason =
        "The backend restarted, so this review is shown from its run folder. Follow-ups, decisions and answers are off.";

    private static readonly string[] FindingsA = { "F-007", "F-008", "F-002" };

    private static readonly Lazy<NightRun> Night = new Lazy<NightRun>(DriveNight);

    private static readonly Lazy<ReloadRun> Reload = new Lazy<ReloadRun>(DriveReload);

    // ---- the chips ------------------------------------------------------------------------------

    /// <summary>
    /// The page asks the host for its reviews after `init` and again after every
    /// `review.started`, and draws one chip per review in the host's order - file, configuration,
    /// time - the one on screen marked `aria-current`.
    /// </summary>
    [Fact]
    public void ThePageListsTheReviewsAfterInitAndAfterEachReviewAndDrawsAChipForEach()
    {
        NightRun run = Night.Value;

        Assert.Equal(1, run.ListsAfterInit);
        Assert.True(run.Initial.GetProperty("chipsHidden").GetBoolean(), "chips are drawn with no review.");
        Assert.Equal(2, run.ListsAfterFirstReview);

        Assert.Equal(new[] { "bracket.sldasm [Default] 10:15", "pin.sldprt [Default] 10:40" }, ReviewPageDriver.Strings(run.Chips, "chipTexts"));
        Assert.Equal(new[] { "false", "true" }, ReviewPageDriver.Strings(run.Chips, "chipCurrent"));
    }

    /// <summary>
    /// Choosing a review is one `GET /sessions/{chat}/snapshot`, no `POST` and no `review.start`
    /// (SC-005), and what it renders is the review as it was rendered live: the same cards, the
    /// same Start-here rows, the same summary.
    /// </summary>
    [Fact]
    public void RestoringAReviewIsOneGetAndRendersWhatTheLiveReviewRendered()
    {
        NightRun run = Night.Value;

        JsonElement call = Assert.Single(run.RestoreCalls);
        Assert.Equal("GET", call.GetProperty("method").GetString());
        Assert.Equal("/sessions/chat-1/snapshot", call.GetProperty("path").GetString());
        Assert.Equal(run.StartsBeforeRestore, run.StartsAfterRestore);

        Assert.Equal(FindingsA, ReviewPageDriver.Strings(run.RestoredA, "cards"));
        Assert.Equal(ReviewPageDriver.Strings(run.Live, "cards"), ReviewPageDriver.Strings(run.RestoredA, "cards"));
        Assert.Equal(ReviewPageDriver.Strings(run.Live, "startHere"), ReviewPageDriver.Strings(run.RestoredA, "startHere"));
        Assert.Equal(run.Live.GetProperty("summary").GetString(), run.RestoredA.GetProperty("summary").GetString());
    }

    /// <summary>
    /// Returning to a document shows its newest review with no stale line; a chip of a document
    /// that is not on screen renders behind the stale line; a document with no review leaves the
    /// shown one hidden behind it, as the landed U8 binding always has.
    /// </summary>
    [Fact]
    public void ReturningToADocumentShowsItsReviewAndAChipOfAnotherDocumentIsStale()
    {
        NightRun run = Night.Value;

        Assert.True(run.RestoredA.GetProperty("staleHidden").GetBoolean(), "the review of the document on screen is stale.");
        Assert.Equal(new[] { "true", "false" }, ReviewPageDriver.Strings(run.RestoredA, "chipCurrent"));

        Assert.True(run.RestoredB.GetProperty("staleHidden").GetBoolean(), "returning to B left B's review stale.");
        Assert.Equal(new[] { "F-100" }, ReviewPageDriver.Strings(run.RestoredB, "cards"));

        Assert.False(run.ChipOfAnother.GetProperty("staleHidden").GetBoolean(), "a chip of another document was not stale.");
        Assert.Equal(
            "This review is of bracket.sldasm [Default]. Press Review to review pin.sldprt [Default].",
            run.ChipOfAnother.GetProperty("staleText").GetString());

        Assert.Equal(
            "This review is of bracket.sldasm [Default]. Press Review to review plate.sldprt [Default].",
            run.NoReviewOfC.GetProperty("staleText").GetString());
        Assert.Empty(run.NoReviewOfCCalls);
    }

    /// <summary>What the engineer typed and the follow-ups pinned stay with their review across a switch away and back.</summary>
    [Fact]
    public void DraftsAndPinsSurviveSwitchingAwayAndBack()
    {
        NightRun run = Night.Value;

        Assert.Equal("Why?", run.RestoredB.GetProperty("pinQuestion").GetString());
        Assert.Equal("Because.", run.RestoredB.GetProperty("pinAnswer").GetString());
        Assert.Equal("Drawing 7", run.DraftAfterReturn.GetProperty("boxValue").GetString());
    }

    /// <summary>
    /// A follow-up on a review restored from its live chat picks the stream up after the
    /// snapshot's last seq - never from the start, which would play the finished turns again as if
    /// they were live - and a cleared review leaves no chip marked as shown.
    /// </summary>
    [Fact]
    public void AFollowUpOnARestoredReviewReadsTheStreamFromTheSnapshotsLastSeq()
    {
        NightRun run = Night.Value;

        Assert.Equal("chat-2", run.FollowUpOpen.GetProperty("chat_id").GetString());
        Assert.Equal("4", run.FollowUpOpen.GetProperty("last_event_id").GetString());
    }

    [Fact]
    public void ClearingTheShownReviewLeavesNoChipMarkedAsShown()
    {
        Assert.Equal(new[] { "false", "false" }, ReviewPageDriver.Strings(Night.Value.Cleared, "chipCurrent"));
    }

    /// <summary>Show names the chat on screen, so the host resolves against that review's package (FR-023).</summary>
    [Fact]
    public void EntityShowCarriesTheShownReviewsChatId()
    {
        Assert.Equal("chat-1", Night.Value.Shown.GetProperty("chat_id").GetString());
    }

    /// <summary>
    /// Choosing the Transcript of a review restored from its live chat replays the stream from the
    /// start: a replayed finding adds its marker and never a second card; a `session.ended` below
    /// the snapshot's last seq neither closes the stream nor reads the ranking again; reaching it
    /// closes the stream (contracts/sessions.md section 8).
    /// </summary>
    [Fact]
    public void ChoosingTheTranscriptReplaysTheStreamWithoutTouchingResults()
    {
        NightRun run = Night.Value;

        Assert.Equal("chat-1", run.ReplayOpen.GetProperty("chat_id").GetString());
        Assert.Equal(JsonValueKind.Null, run.ReplayOpen.GetProperty("last_event_id").ValueKind);

        Assert.Equal(1, run.ReplayMid.GetProperty("f007Cards").GetInt32());
        Assert.Contains("F-007 recorded: Finding F-007", ReviewPageDriver.Strings(run.ReplayMid, "markers"));
        Assert.Contains("Replayed prose.", run.ReplayMid.GetProperty("transcript").GetString()!);
        Assert.Equal(run.ClosesBeforeReplay, run.ClosesMidReplay);
        Assert.Equal(0, run.AttentionReadsDuringReplay);

        Assert.Equal(run.ClosesBeforeReplay + 1, run.ClosesAfterReplay);
    }

    // ---- a reload, the read-only restore, a review that is gone --------------------------------

    /// <summary>
    /// After `init` with a document open whose review the host kept, that review is shown - a
    /// page reload does not lose it; a snapshot whose chat is still running sets the turn and
    /// reopens the stream from the snapshot's last seq.
    /// </summary>
    [Fact]
    public void AfterInitTheOpenDocumentsReviewIsShownAndARunningChatReopensTheStream()
    {
        ReloadRun run = Reload.Value;

        Assert.Equal(FindingsA, ReviewPageDriver.Strings(run.Reloaded, "cards"));
        Assert.Equal(@"C:\SwReviewRuns\20260923-091500-bracket-7", run.Reloaded.GetProperty("runDir").GetString());
        Assert.Equal(new[] { "true", "false" }, ReviewPageDriver.Strings(run.Reloaded, "chipCurrent"));
        Assert.False(run.Reloaded.GetProperty("stopDisabled").GetBoolean(), "the running turn's Stop is disabled.");
        Assert.Equal("chat-7", run.ReloadOpen.GetProperty("chat_id").GetString());
        Assert.Equal("9", run.ReloadOpen.GetProperty("last_event_id").GetString());
    }

    /// <summary>
    /// While a turn runs or a start is in flight a chip changes nothing and fetches nothing, and a
    /// document change leaves the running review stale with Stop live (FR-030).
    /// </summary>
    [Fact]
    public void AChipIsRefusedWhileATurnRunsOrAStartIsInFlight()
    {
        ReloadRun run = Reload.Value;

        Assert.Empty(run.CallsWhileRunning);
        Assert.Equal(@"C:\SwReviewRuns\20260923-091500-bracket-7", run.WhileRunning.GetProperty("runDir").GetString());
        Assert.False(run.WhileRunning.GetProperty("staleHidden").GetBoolean(), "the running review was not hidden for B.");
        Assert.False(run.WhileRunning.GetProperty("stopDisabled").GetBoolean(), "Stop was disabled for another document.");

        Assert.Empty(run.CallsWhileStarting);
    }

    /// <summary>
    /// A chat the backend no longer holds falls back to the run folder, read-only: the follow-up,
    /// every disposition control and the questions are off and the reason is shown, while Open
    /// report and Open run folder still work (FR-021).
    /// </summary>
    [Fact]
    public void AReviewWhoseChatIsGoneIsRestoredReadOnlyFromItsRunFolder()
    {
        ReloadRun run = Reload.Value;

        Assert.Equal(
            new[] { "GET /sessions/chat-8/snapshot", "GET /reviews/20260923-093000-pin-8" },
            run.ReadOnlyCalls.Select(call => call.GetProperty("method").GetString() + " " + call.GetProperty("path").GetString()).ToArray());

        JsonElement readOnly = run.ReadOnly;
        Assert.Equal(new[] { "F-100" }, ReviewPageDriver.Strings(readOnly, "cards"));
        Assert.True(readOnly.GetProperty("followupDisabled").GetBoolean(), "the follow-up is live on a read-only review.");
        Assert.True(readOnly.GetProperty("decisionsDisabled").GetBoolean(), "a disposition control is live on a read-only review.");
        Assert.True(readOnly.GetProperty("questionsDisabled").GetBoolean(), "the questions are live on a read-only review.");
        Assert.Equal(ReadOnlyReason, readOnly.GetProperty("readOnly").GetString());
        Assert.False(readOnly.GetProperty("reportDisabled").GetBoolean(), "Open report is off on a read-only review.");
        Assert.False(readOnly.GetProperty("folderDisabled").GetBoolean(), "Open run folder is off on a read-only review.");
    }

    /// <summary>
    /// A review restored from its folder has no stream to replay: its Transcript says where the
    /// transcript is, and offers the folder.
    /// </summary>
    [Fact]
    public void AReviewRestoredFromItsFolderSaysWhereItsTranscriptIs()
    {
        ReloadRun run = Reload.Value;

        Assert.Contains(
            "This review was restored from its run folder; its transcript is in events.jsonl there.",
            run.FolderTranscript.GetProperty("transcript").GetString()!);
        Assert.Equal(run.OpensBeforeFolderTranscript, run.OpensAfterFolderTranscript);
        Assert.Equal("chat-8", run.FolderOpened.GetProperty("chat_id").GetString());
    }

    /// <summary>
    /// A review whose run folder is gone too says so on its chip and offers Remove, which asks
    /// the host to forget it and redraws the chips from the host's answer.
    /// </summary>
    [Fact]
    public void AReviewThatCanNoLongerBeRestoredSaysSoAndRemoveForgetsIt()
    {
        ReloadRun run = Reload.Value;

        Assert.Contains("This review can no longer be restored.", run.Gone.GetProperty("goneChip").GetString()!);
        Assert.True(run.Gone.GetProperty("hasRemove").GetBoolean(), "no Remove on a review that is gone.");
        Assert.Empty(ReviewPageDriver.Strings(run.Gone, "cards"));
        Assert.Equal(string.Empty, run.Gone.GetProperty("runDir").GetString());

        Assert.Equal("chat-7", run.Forgot.GetProperty("chat_id").GetString());
        Assert.Equal(new[] { "pin.sldprt [Default] 09:30" }, ReviewPageDriver.Strings(run.AfterRemove, "chipTexts"));
    }

    // ---- the night: review A, then B, then back ---------------------------------------------

    private static NightRun DriveNight()
    {
        var run = new NightRun();
        Dictionary<string, object?> a1 = Item("chat-1", "20260923-101500-bracket-1", PathA, 10, 15);
        Dictionary<string, object?> b1 = Item("chat-2", "20260923-104000-pin-2", PathB, 10, 40);

        ReviewPageDriver.Run(
            driver =>
            {
                driver.Document = Doc(PathA);
                driver.ReviewStarted = press => press == 1 ? Started(a1) : Started(b1);
            },
            async driver =>
            {
                run.ListsAfterInit = driver.Posted("sessions.list").Length;
                run.Initial = await driver.Read(ReadState);

                // Review A, live.
                driver.Sessions.Add(a1);
                await driver.RouteAttention("chat-1", SummarySample.Json());
                await driver.StartReview();
                int seq = 0;
                foreach (string id in FindingsA)
                {
                    await driver.Push("chat-1", ++seq, "finding", Finding(id));
                }

                await driver.EndSession("chat-1");
                run.Live = await driver.Read(ReadState);
                run.ListsAfterFirstReview = driver.Posted("sessions.list").Length;

                // Open B (no review of it yet), review it, ask a follow-up, draft an answer.
                await driver.DocumentChanged(Doc(PathB));
                driver.Sessions.Add(b1);
                await driver.RouteAttention("chat-2", SummarySample.Json());
                await driver.StartReview();
                await driver.Push("chat-2", 1, "finding", Finding("F-100"));
                await driver.EndSession("chat-2");
                await driver.Route("POST", "/sessions/chat-2/messages", 200, "{}");
                await driver.Read(FollowUp("Why?"));
                await driver.Settle();
                await driver.Push("chat-2", 50, "text.done", @"{""text"":""Because.""}");
                await driver.EndSession("chat-2");
                await driver.Read(Press("question-next") + Type("Drawing 7") + "return JSON.stringify({ok: true});");
                run.Chips = await driver.Read(ReadState);

                // Back to A: its review is shown, restored with one GET.
                await driver.Route("GET", "/sessions/chat-1/snapshot", 200, Snapshot("20260923-101500-bracket-1", PathA, FindingsA, "ended", 4, false));
                await driver.Route("GET", "/sessions/chat-2/snapshot", 200, Snapshot("20260923-104000-pin-2", PathB, new[] { "F-100" }, "ended", 4, false));
                await driver.ClearCalls();
                run.StartsBeforeRestore = driver.Starts;
                await driver.DocumentChanged(Doc(PathA));
                run.RestoredA = await driver.Read(ReadState);
                run.RestoreCalls = await driver.Calls();
                run.StartsAfterRestore = driver.Starts;
                await driver.Read("document.querySelector('.card.finding[data-finding-id=\"F-007\"] [data-action=\"show\"]').click(); return JSON.stringify({ok: true});");
                await driver.Settle();
                run.Shown = driver.Posted("entity.show").Last();

                // Back to B: its review, its pin, its draft.
                await driver.DocumentChanged(Doc(PathB));
                run.RestoredB = await driver.Read(ReadState);
                run.DraftAfterReturn = await driver.Read(Press("question-next") + ReadDraft);

                // A follow-up on the restored B reads the stream from the snapshot's last seq.
                await driver.Read(FollowUp("And now?"));
                await driver.Settle();
                run.FollowUpOpen = driver.Posted("events.open").Last();
                await driver.Push("chat-2", 5, "turn.ended", @"{""reason"":""end""}");
                await driver.Settle();

                // A's chip while B is on screen: behind the stale line.
                await driver.Read(Chip("chat-1"));
                await driver.Settle();
                run.ChipOfAnother = await driver.Read(ReadState);

                // C has no review: the shown one stays hidden, and nothing is fetched.
                await driver.ClearCalls();
                await driver.DocumentChanged(Doc(PathC));
                run.NoReviewOfC = await driver.Read(ReadState);
                run.NoReviewOfCCalls = await driver.Calls();

                // The Transcript of A, replayed from the start.
                await driver.ClearCalls();
                run.ClosesBeforeReplay = driver.Posted("events.close").Length;
                await driver.Click("view-transcript");
                run.ReplayOpen = driver.Posted("events.open").Last();
                await driver.Push("chat-1", 1, "text.delta", @"{""text"":""Replayed prose.""}");
                await driver.Push("chat-1", 2, "finding", Finding("F-007"));
                await driver.Push("chat-1", 3, "session.ended", @"{""ended_at"":""2026-09-23T10:20:00+00:00""}");
                await driver.Settle();
                run.ReplayMid = await driver.Read(ReadReplay);
                run.ClosesMidReplay = driver.Posted("events.close").Length;
                await driver.Push("chat-1", 4, "usage", UsageBody);
                await driver.Settle();
                run.ClosesAfterReplay = driver.Posted("events.close").Length;
                run.AttentionReadsDuringReplay = (await driver.Calls()).Count(c => (c.GetProperty("path").GetString() ?? string.Empty).EndsWith("/attention", StringComparison.Ordinal));
                await driver.Click("view-results");

                // Clear review: no chip is the shown one any more.
                await driver.Click("clear-review");
                run.Cleared = await driver.Read(ReadState);
            });

        return run;
    }

    // ---- a reload mid-turn, then the fallbacks ------------------------------------------------

    private static ReloadRun DriveReload()
    {
        var run = new ReloadRun();
        Dictionary<string, object?> a7 = Item("chat-7", "20260923-091500-bracket-7", PathA, 9, 15);
        Dictionary<string, object?> b8 = Item("chat-8", "20260923-093000-pin-8", PathB, 9, 30);

        ReviewPageDriver.Run(
            driver =>
            {
                driver.Document = Doc(PathA);
                driver.Sessions.Add(a7);
                driver.Sessions.Add(b8);
                driver.ReviewStarted = press => Started(Item("chat-9", "20260923-100000-pin-9", PathB, 10, 0));
                driver.InitialRoutes.Add(("GET", "/sessions/chat-7/snapshot", 200,
                    Snapshot("20260923-091500-bracket-7", PathA, FindingsA, "running", 9, false)));
            },
            async driver =>
            {
                run.Reloaded = await driver.Read(ReadState);
                run.ReloadOpen = driver.Posted("events.open").Last();

                // While the turn runs: a chip does nothing, another document leaves it stale.
                await driver.ClearCalls();
                await driver.Read(Chip("chat-8"));
                await driver.Settle();
                await driver.DocumentChanged(Doc(PathB));
                run.WhileRunning = await driver.Read(ReadState);
                run.CallsWhileRunning = await driver.Calls();

                // The turn ends; B's chat is gone, so its chip falls back to its run folder.
                await driver.RouteAttention("chat-7", SummarySample.Json());
                await driver.EndSession("chat-7");
                await driver.Route("GET", "/sessions/chat-8/snapshot", 404, @"{""error_class"":""UnknownChat"",""message"":""no chat chat-8"",""retryable"":false}");
                await driver.Route("GET", "/reviews/20260923-093000-pin-8", 200, Snapshot("20260923-093000-pin-8", PathB, new[] { "F-100" }, null, null, true));
                await driver.ClearCalls();
                await driver.Read(Chip("chat-8"));
                await driver.Settle();
                run.ReadOnly = await driver.Read(ReadState);
                run.ReadOnlyCalls = await driver.Calls();

                run.OpensBeforeFolderTranscript = driver.Posted("events.open").Length;
                await driver.Click("view-transcript");
                run.FolderTranscript = await driver.Read(ReadReplay);
                run.OpensAfterFolderTranscript = driver.Posted("events.open").Length;
                await driver.Read("document.querySelector('#transcript [data-action=\"open-folder\"]').click(); return JSON.stringify({ok: true});");
                await driver.Settle();
                run.FolderOpened = driver.Posted("folder.open").Last();
                await driver.Click("view-results");

                // A start in flight: a chip does nothing.
                driver.HoldReviewStart = true;
                await driver.StartReview();
                await driver.ClearCalls();
                await driver.Read(Chip("chat-7"));
                await driver.Settle();
                run.CallsWhileStarting = await driver.Calls();
                await driver.ReleaseReviewStart();

                // A's chat and its folder are both gone.
                await driver.Route("GET", "/sessions/chat-7/snapshot", 404, @"{""error_class"":""UnknownChat"",""message"":""no chat chat-7"",""retryable"":false}");
                await driver.Route("GET", "/reviews/20260923-091500-bracket-7", 404, @"{""error_class"":""UnknownReview"",""message"":""no review"",""retryable"":false}");
                await driver.EndSession("chat-9");
                await driver.Read(Chip("chat-7"));
                await driver.Settle();
                run.Gone = await driver.Read(ReadState);
                await driver.Read("document.querySelector('#review-chips [data-action=\"review-forget\"]').click(); return JSON.stringify({ok: true});");
                await driver.Settle();
                run.Forgot = driver.Posted("session.forget").Last();
                run.AfterRemove = await driver.Read(ReadState);
            });

        return run;
    }

    // ---- samples ------------------------------------------------------------------------------

    private static object Doc(string path) => new { path, configuration = "Default" };

    /// <summary>One `sessions` item, as the host lists a review; the time in this machine's own zone.</summary>
    private static Dictionary<string, object?> Item(string chatId, string runId, string path, int hour, int minute)
    {
        var local = new DateTime(2026, 9, 23, hour, minute, 0, DateTimeKind.Unspecified);
        var started = new DateTimeOffset(local, TimeZoneInfo.Local.GetUtcOffset(local));
        return new Dictionary<string, object?>
        {
            { "chat_id", chatId },
            { "run_id", runId },
            { "run_dir", @"C:\SwReviewRuns\" + runId },
            { "path", path },
            { "configuration", "Default" },
            { "started_at", started.ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture) },
        };
    }

    private static Dictionary<string, object?> Started(Dictionary<string, object?> item) => new Dictionary<string, object?>
    {
        { "chat_id", item["chat_id"] },
        { "run_dir", item["run_dir"] },
        { "document", new { path = item["path"], configuration = "Default" } },
    };

    private static string Finding(string id) => JsonSerializer.Serialize(new
    {
        id,
        check = "interference.static",
        title = "Finding " + id,
        status = "demonstrated",
        severity = "medium",
        component_ids = new[] { "cmp:0002", "cmp:0003" },
        drawing_locations = new[] { new { document_id = "doc-1", persist_ref = "AQAAAA==" } },
        observed = "Observed for " + id + ".",
    });

    /// <summary>A snapshot in the shape of data-model section 8, the summary sample's ranking in it.</summary>
    private static string Snapshot(string runId, string path, string[] findingIds, string? chatState, int? lastSeq, bool readOnly)
    {
        var snapshot = new JsonObject
        {
            ["run_id"] = runId,
            ["read_only"] = readOnly,
            ["read_only_reason"] = readOnly ? ReadOnlyReason : null,
            ["chat_state"] = chatState,
            ["last_seq"] = lastSeq,
            ["document"] = JsonNode.Parse(JsonSerializer.Serialize(Doc(path))),
            ["findings"] = new JsonArray(findingIds.Select(id => JsonNode.Parse(Finding(id))).ToArray()),
            ["evidence_requests"] = new JsonArray(),
            ["coverage"] = JsonNode.Parse(@"[{""bucket"":""unresolved"",""item"":{""check"":""interfaces.fit"",""reason"":""no drawing""}}]"),
            ["ranking"] = SummarySample.Ranking(),
            ["not_examined"] = null,
        };
        return snapshot.ToJsonString();
    }

    private const string UsageBody =
        @"{""round_index"":0,""provider"":""openai"",""model"":""gpt-5.6"",""input_tokens"":10,"
        + @"""cached_input_tokens"":5,""cache_write_tokens"":null,""output_tokens"":8,"
        + @"""reasoning_tokens"":4,""tool_result_input_tokens"":null,""total_tokens"":18,"
        + @"""latency_s"":1.5,""cache_diagnostic"":null}";

    private static string Chip(string chatId) =>
        "document.querySelector('#review-chips [data-action=\"review-chip\"][data-chat-id=\"" + chatId + "\"]').click();"
        + "return JSON.stringify({ok: true});";

    private static string Press(string action) =>
        "document.querySelector('#questions [data-action=\"" + action + "\"]').click();";

    private static string Type(string text) =>
        "var box = document.querySelector('#questions .question-answer'); box.value = " + JsonSerializer.Serialize(text)
        + "; box.dispatchEvent(new Event('input', { bubbles: true }));";

    private static string FollowUp(string text) =>
        "var input = document.getElementById('followup-text'); input.value = " + JsonSerializer.Serialize(text) + ";"
        + "document.getElementById('followup').dispatchEvent(new Event('submit', {cancelable: true}));"
        + "return JSON.stringify({ok: true});";

    private const string ReadDraft = @"
var box = document.querySelector('#questions .question-answer');
return JSON.stringify({ ok: true, boxValue: box ? box.value : null });";

    private const string ReadReplay = @"
var transcript = document.getElementById('transcript');
return JSON.stringify({
  ok: true,
  f007Cards: document.querySelectorAll('#findings .card.finding[data-finding-id=""F-007""]').length,
  markers: h.texts(transcript, '.marker'),
  transcript: transcript.textContent
});";

    private const string ReadState = @"
var chips = document.querySelectorAll('#review-chips [data-action=""review-chip""]');
var gone = document.querySelector('#review-chips .review-chip.gone');
var decisions = document.querySelectorAll('#findings [data-action=""accept""], #findings [data-action=""reject""], #findings [data-action=""defer""], #findings input.note');
var decisionsDisabled = decisions.length > 0;
for (var i = 0; i < decisions.length; i++) { if (!decisions[i].disabled) { decisionsDisabled = false; } }
var questionControls = document.querySelectorAll('#questions button, #questions input');
var questionsDisabled = questionControls.length > 0;
for (var j = 0; j < questionControls.length; j++) { if (!questionControls[j].disabled) { questionsDisabled = false; } }
var pins = document.querySelectorAll('#answers .pinned');
var pin = pins.length ? pins[pins.length - 1] : null;
var readOnly = document.getElementById('read-only');
return JSON.stringify({
  ok: true,
  chipsHidden: !!document.getElementById('review-chips').hidden,
  chipTexts: h.texts(document, '#review-chips [data-action=""review-chip""]'),
  chipCurrent: h.attrs(document, '#review-chips [data-action=""review-chip""]', 'aria-current'),
  goneChip: gone ? gone.textContent : '',
  hasRemove: !!document.querySelector('#review-chips [data-action=""review-forget""]'),
  cards: h.attrs(document.getElementById('findings'), '.card.finding', 'data-finding-id'),
  startHere: h.attrs(document.getElementById('attention-panel'), '.attention-row', 'data-finding-id'),
  summary: document.getElementById('summary').textContent,
  staleHidden: !!document.getElementById('stale-review').hidden,
  staleText: document.getElementById('stale-review').textContent,
  runDir: document.getElementById('run-dir').textContent,
  stopDisabled: document.getElementById('stop-turn').disabled,
  followupDisabled: document.getElementById('followup-text').disabled,
  reportDisabled: document.getElementById('open-report').disabled,
  folderDisabled: document.getElementById('open-folder').disabled,
  decisionsDisabled: decisionsDisabled,
  questionsDisabled: questionsDisabled,
  readOnly: readOnly && !readOnly.hidden ? readOnly.textContent : null,
  pinQuestion: pin ? h.text(pin, '.pinned-question') : null,
  pinAnswer: pin ? h.text(pin, '.pinned-answer') : null
});";

    private sealed class NightRun
    {
        public int ListsAfterInit { get; set; }

        public JsonElement Initial { get; set; }

        public JsonElement Live { get; set; }

        public int ListsAfterFirstReview { get; set; }

        public JsonElement Chips { get; set; }

        public int StartsBeforeRestore { get; set; }

        public JsonElement RestoredA { get; set; }

        public JsonElement[] RestoreCalls { get; set; } = new JsonElement[0];

        public int StartsAfterRestore { get; set; }

        public JsonElement Shown { get; set; }

        public JsonElement RestoredB { get; set; }

        public JsonElement DraftAfterReturn { get; set; }

        public JsonElement ChipOfAnother { get; set; }

        public JsonElement NoReviewOfC { get; set; }

        public JsonElement[] NoReviewOfCCalls { get; set; } = new JsonElement[0];

        public int ClosesBeforeReplay { get; set; }

        public JsonElement ReplayOpen { get; set; }

        public JsonElement ReplayMid { get; set; }

        public int ClosesMidReplay { get; set; }

        public int ClosesAfterReplay { get; set; }

        public int AttentionReadsDuringReplay { get; set; }

        public JsonElement FollowUpOpen { get; set; }

        public JsonElement Cleared { get; set; }
    }

    private sealed class ReloadRun
    {
        public JsonElement Reloaded { get; set; }

        public JsonElement ReloadOpen { get; set; }

        public JsonElement WhileRunning { get; set; }

        public JsonElement[] CallsWhileRunning { get; set; } = new JsonElement[0];

        public JsonElement ReadOnly { get; set; }

        public JsonElement[] ReadOnlyCalls { get; set; } = new JsonElement[0];

        public int OpensBeforeFolderTranscript { get; set; }

        public JsonElement FolderTranscript { get; set; }

        public int OpensAfterFolderTranscript { get; set; }

        public JsonElement FolderOpened { get; set; }

        public JsonElement[] CallsWhileStarting { get; set; } = new JsonElement[0];

        public JsonElement Gone { get; set; }

        public JsonElement Forgot { get; set; }

        public JsonElement AfterRemove { get; set; }
    }
}
