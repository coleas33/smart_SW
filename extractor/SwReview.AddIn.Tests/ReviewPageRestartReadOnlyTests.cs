using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 002 T398 (cycle 22, roadmap hole H-c-011; FR-031, 009 FR-021): after a backend restart a finished review is
/// shown read-only at once.
///
/// When `init` names another backend - a Settings save, or a backend started again after it stopped - the new backend holds
/// no chat of the old one. Until this cycle only a review waiting for Send was shown from its run folder then (015
/// FR-042); any other live review on screen lost its stream and the minutes form but kept its decision, triage and note
/// controls, its follow-up box and its answers, and each press was refused `UnknownChat`, whose sentence sends the engineer
/// to a new review. Now the live review on screen - of whichever document, finished or mid-turn - is shown from its folder
/// at once, as a waiting one is: its snapshot gone, `GET /reviews/{run_id}`, read-only with the reason a restore after a
/// restart gives, every control that would post to the old backend off. A turn on screen ran on the backend that went, so
/// it is over: a follow-up still waiting says it had no answer, and a folder that holds no record leaves the chip saying
/// the review can no longer be restored. The reason is the backend's, printed as sent: for a record whose flagged findings
/// do not all record an outcome it ends with the console's sentence, which records the rest (`swreview disposition`). A
/// waiting review is restored as before, with Send offered. Every id and path is fictional.
/// </summary>
public sealed class ReviewPageRestartReadOnlyTests
{
    private const string Chat = "chat-1";

    /// <summary>The run folder of the review started first, as the driver's `review.started` and the host's item name it.</summary>
    private const string Run = "20260923-101500-bracket-1";

    private const string SnapshotPath = "/sessions/" + Chat + "/snapshot";

    private const string FolderPath = "/reviews/" + Run;

    private const string RestartedToken = "FICT-restarted-backend-token";

    /// <summary>
    /// The words file's `read_only_console`, with which the backend ends a finished record's line while a flagged finding
    /// records no outcome (`snapshot.restored_snapshot`; `reviewer/tests/unit/test_review_words.py` pins the words).
    /// </summary>
    internal const string ConsoleLine = "Record the rest of the triage at the console: swreview disposition.";

    /// <summary>The line of a record restored from its folder whose flagged findings do not all record an outcome.</summary>
    private const string MissingReason = ReviewPageSessionsTests.ReadOnlyReason + " " + ConsoleLine;

    private const string UnknownReview = "{\"error_class\":\"UnknownReview\",\"message\":\"no review FICT\",\"retryable\":false}";

    /// <summary>
    /// A finished review on screen when the backend restarts is shown from its folder at once: the page asks the new backend
    /// for its snapshot, which it does not hold, then its folder, and nothing else; the line under the status line says why
    /// it is read-only - and, when a flagged finding records no outcome, that the console records the rest, which a record
    /// whose every flagged finding is judged does not say; every decision, triage and note control, the questions, the
    /// follow-up box and Stop are off, and pressing each posts nothing; the minutes form is gone; and the Transcript is the
    /// restored one.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void AFinishedReviewOnScreenIsShownFromItsFolderAfterARestart(bool outcomesMissing)
    {
        ReviewPageDriver.Run(Kept, async driver =>
        {
            await Finished(driver);
            JsonElement live = await driver.Read(ReadPage);
            Assert.Null(live.GetProperty("readOnly").GetString());
            Assert.False(live.GetProperty("decisionsOff").GetBoolean(), "the live review's decisions are off before the restart.");
            Assert.True(live.GetProperty("timingShown").GetBoolean(), "the live review shows no minutes form before the restart.");

            await driver.Route("GET", SnapshotPath, 404, ReviewPageRecheckTests.UnknownChat);
            await driver.Route("GET", FolderPath, 200, Folder(outcomesMissing));
            await driver.ClearCalls();
            await Restart(driver);

            JsonElement shown = await driver.Read(ReadPage);
            string reason = shown.GetProperty("readOnly").GetString()!;
            Assert.Equal(outcomesMissing ? MissingReason : ReviewPageSessionsTests.ReadOnlyReason, reason);
            if (outcomesMissing)
            {
                Assert.Contains(ConsoleLine, reason);
            }
            else
            {
                Assert.DoesNotContain(ConsoleLine, reason);
            }

            AssertEveryControlOff(shown);
            Assert.False(shown.GetProperty("timingShown").GetBoolean(), "the minutes form stays on a review the backend no longer holds.");
            Assert.Contains("This review was restored from its run folder", shown.GetProperty("transcript").GetString());
            Assert.Equal(new[] { "GET " + SnapshotPath, "GET " + FolderPath }, await RestoreReads(driver));

            await PressEverything(driver);
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("method").GetString() == "POST");
        });
    }

    /// <summary>
    /// A review mid-turn when the backend restarts - here a follow-up's, the page not yet told its turn ended - had its turn
    /// on the backend that went. Until this cycle the page kept it running: Stop on, Review off, the chips and the document
    /// rule refused, until a reload. Now the turn is over - its follow-up says it had no answer - and the review is shown
    /// from its folder as any other: read-only when the folder holds a record; when it holds none, its chip says it can no
    /// longer be restored, the pane shows no review and Review is on.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void AReviewMidTurnAtARestartIsShownFromItsFolderWithItsTurnOver(bool recorded)
    {
        ReviewPageDriver.Run(Kept, async driver =>
        {
            await Finished(driver);
            await driver.Route("POST", "/sessions/" + Chat + "/messages", 202, "{}");
            await driver.Read(
                "var input = document.getElementById('followup-text'); input.value = 'FICT why F-001?';"
                + "document.getElementById('followup').dispatchEvent(new Event('submit', {cancelable: true}));"
                + "return JSON.stringify({ok: true});");
            await driver.Settle();
            JsonElement running = await driver.Read(ReadPage);
            Assert.False(running.GetProperty("stopOff").GetBoolean(), "the follow-up's turn is not running before the restart.");
            Assert.Equal(new[] { "Waiting for the answer." }, ReviewPageDriver.Strings(running, "pins"));

            await driver.Route("GET", SnapshotPath, 404, ReviewPageRecheckTests.UnknownChat);
            await driver.Route("GET", FolderPath, recorded ? 200 : 404, recorded ? Folder(true) : UnknownReview);
            await driver.ClearCalls();
            int readies = driver.Posted("ready").Length;
            driver.BackendToken = RestartedToken;
            await driver.Post("backend.restarted", new { sentences = Array.Empty<string>() });
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init after the restart");
            await driver.Settle();

            JsonElement after = await driver.Read(ReadPage);
            Assert.True(after.GetProperty("stopOff").GetBoolean(), "Stop is on for a turn that ended with its backend.");
            Assert.False(after.GetProperty("reviewOff").GetBoolean(), "Review is off after the turn ended with its backend.");
            Assert.Equal(new[] { "GET " + SnapshotPath, "GET " + FolderPath }, await RestoreReads(driver));
            if (recorded)
            {
                Assert.Equal(MissingReason, after.GetProperty("readOnly").GetString());
                AssertEveryControlOff(after);
                Assert.Equal(new[] { "No answer: the turn ended (restarted)." }, ReviewPageDriver.Strings(after, "pins"));
            }
            else
            {
                Assert.Null(after.GetProperty("readOnly").GetString());
                Assert.Equal(0, after.GetProperty("cards").GetInt32());
                Assert.Contains("This review can no longer be restored.", after.GetProperty("chips").GetString());
            }

            await PressEverything(driver);
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("method").GetString() == "POST");
        });
    }

    /// <summary>
    /// The restart shows the live review on screen whichever document it is of, not only the active one's: a review left
    /// on screen behind the stale line while another document is active is shown from its folder at the restart, so
    /// returning to its document shows it read-only, with nothing more asked, and none of its controls posts.
    /// </summary>
    [Fact]
    public void ALiveReviewOfAnotherDocumentOnScreenIsShownFromItsFolderAfterARestart()
    {
        ReviewPageDriver.Run(Kept, async driver =>
        {
            await Finished(driver);
            await driver.DocumentChanged(new { path = @"C:\parts\pin.sldprt", configuration = "Default" });
            await driver.Route("GET", SnapshotPath, 404, ReviewPageRecheckTests.UnknownChat);
            await driver.Route("GET", FolderPath, 200, Folder(true));
            await driver.ClearCalls();

            await Restart(driver);
            Assert.Equal(new[] { "GET " + SnapshotPath, "GET " + FolderPath }, await RestoreReads(driver));

            await driver.ClearCalls();
            await driver.DocumentChanged(new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" });
            JsonElement back = await driver.Read(ReadPage);
            Assert.Equal(MissingReason, back.GetProperty("readOnly").GetString());
            Assert.Equal(2, back.GetProperty("cards").GetInt32());
            AssertEveryControlOff(back);
            Assert.Empty(await RestoreReads(driver));

            await PressEverything(driver);
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("method").GetString() == "POST");
        });
    }

    /// <summary>
    /// A guard: a live review waiting for Send is restored at a restart as before (015 FR-042) - read-only, its line the
    /// backend's waiting one, which names no console, its decisions, questions and follow-up box off and its Send offered,
    /// the one control a restored waiting review has.
    /// </summary>
    [Fact]
    public void AWaitingReviewOnScreenAtARestartIsRestoredAsBefore()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver => fixture.Configure(driver, refuseSend: true), async driver =>
        {
            await ReviewPageRecheckTests.PressSend(driver);
            Assert.False((await driver.Read(ReviewPageRecheckTests.ReadState)).GetProperty("readOnly").GetBoolean());
            await driver.Route("GET", "/sessions/" + fixture.RecheckedChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat);

            await Restart(driver);

            JsonElement state = await driver.Read(ReviewPageRecheckTests.ReadState);
            Assert.True(state.GetProperty("readOnly").GetBoolean(), state.GetRawText());
            string reason = state.GetProperty("reason").GetString()!;
            Assert.Equal(fixture.Restored.GetProperty("read_only_reason").GetString(), reason);
            Assert.DoesNotContain(ConsoleLine, reason);
            Assert.True(state.GetProperty("sendShown").GetBoolean());
            Assert.False(state.GetProperty("sendOff").GetBoolean(), "Send is the one control a restored waiting review offers.");
            Assert.True(state.GetProperty("decisions").GetInt32() > 0);
            Assert.True(state.GetProperty("decisionsOff").GetBoolean());
            Assert.True(state.GetProperty("questions").GetInt32() > 0);
            Assert.True(state.GetProperty("questionsOff").GetBoolean());
            Assert.True(state.GetProperty("followupOff").GetBoolean());
        });
    }

    /// <summary>
    /// At a docked pane's 300 px the line a restart leaves - the reason and the console's sentence - is whole, inside the
    /// window and every box that clips it, its words wrapping rather than cut off, with no sideways page scroll.
    /// </summary>
    [Fact]
    public void TheReadOnlyLineIsWhollyVisibleAtThreeHundredPixelsAfterARestart()
    {
        ReviewPageDriver.Run(Kept, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await Finished(driver);
            await driver.Route("GET", SnapshotPath, 404, ReviewPageRecheckTests.UnknownChat);
            await driver.Route("GET", FolderPath, 200, Folder(true));
            await Restart(driver);

            JsonElement measured = await driver.Read(ReadLineWhole);
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.Equal(MissingReason, measured.GetProperty("text").GetString());
            Assert.True(measured.GetProperty("whole").GetBoolean(), measured.GetRawText());
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.GetRawText());
        });
    }

    // ---- driving the page ---------------------------------------------------------------------

    /// <summary>The backend's words, and the review the host keeps for the first press of Review, as it keeps every one.</summary>
    private static void Kept(ReviewPageDriver driver)
    {
        driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
        driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, Run, ReviewPageDriver.ReviewedPath, 10, 15));
    }

    /// <summary>
    /// A live review of the active document, finished: two flagged findings, F-001 undecided and F-002 accepted with no
    /// triage, and the summary's three questions, so every kind of control a finished review has is on screen.
    /// </summary>
    private static async Task Finished(ReviewPageDriver driver)
    {
        await driver.RouteAttention(Chat, SummarySample.Json());
        await driver.StartReview();
        await driver.Push(Chat, 1, "finding", Finding("F-001", null));
        await driver.Push(Chat, 2, "finding", Finding("F-002", Accepted(null)));
        await driver.EndSession(Chat);
    }

    /// <summary>A Settings save that restarts the backend: the next `init` names a new token.</summary>
    private static async Task Restart(ReviewPageDriver driver)
    {
        int readies = driver.Posted("ready").Length;
        driver.BackendToken = RestartedToken;
        await driver.Click("save-settings");
        await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init after the save");
        await driver.Settle();
    }

    /// <summary>The reads of the review's chat and run folder since the calls were last cleared, in order.</summary>
    private static async Task<string[]> RestoreReads(ReviewPageDriver driver) =>
        (await driver.Calls())
            .Select(call => call.GetProperty("method").GetString() + " " + call.GetProperty("path").GetString())
            .Where(call => call == "GET " + SnapshotPath || call == "GET " + FolderPath)
            .ToArray();

    /// <summary>
    /// Presses every control a finished review offers, as the engineer would: each card's triage and decision buttons, a
    /// question's option and its send, the follow-up box's submit, Stop and the minutes form's Save.
    /// </summary>
    private static async Task PressEverything(ReviewPageDriver driver)
    {
        await driver.Read(@"
var press = function (selector) {
  var found = document.querySelectorAll(selector);
  for (var i = 0; i < found.length; i++) { found[i].click(); }
};
press('#results .card.finding [data-action=""triage""]');
press('#results .card.finding [data-action=""accept""]');
press('#results .card.finding [data-action=""reject""]');
press('#results .card.finding [data-action=""defer""]');
press('#questions [data-action=""question-option""]');
press('#questions [data-action=""question-send""]');
document.getElementById('followup-text').value = 'FICT a follow-up after the restart';
document.getElementById('followup').dispatchEvent(new Event('submit', { cancelable: true }));
press('#stop-turn');
press('#timing [data-action=""save-timing""]');
return JSON.stringify({ ok: true });");
        await driver.Settle();
    }

    private static void AssertEveryControlOff(JsonElement page)
    {
        Assert.True(page.GetProperty("decisions").GetInt32() > 0, page.GetRawText());
        Assert.True(page.GetProperty("decisionsOff").GetBoolean(), "a decision, triage or note control is on: " + page.GetRawText());
        Assert.True(page.GetProperty("questions").GetInt32() > 0, page.GetRawText());
        Assert.True(page.GetProperty("questionsOff").GetBoolean(), "a question's control is on: " + page.GetRawText());
        Assert.True(page.GetProperty("followupOff").GetBoolean(), "the follow-up box is on: " + page.GetRawText());
        Assert.True(page.GetProperty("stopOff").GetBoolean(), "Stop is on: " + page.GetRawText());
    }

    // ---- samples ------------------------------------------------------------------------------

    private static string Finding(string id, Dictionary<string, object?>? disposition) =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "id", id },
            { "check", "interference.static" },
            { "title", "FICT finding " + id },
            { "status", "demonstrated" },
            { "severity", "medium" },
            { "component_ids", new[] { "cmp:0002" } },
            { "observed", "FICT observed for " + id + "." },
            { "disposition", disposition },
        });

    /// <summary>An Accept, with <paramref name="triage"/> as its outcome; the key left out when none, as the backend leaves it.</summary>
    private static Dictionary<string, object?> Accepted(string? triage)
    {
        var disposition = new Dictionary<string, object?>
        {
            { "decision", "accepted" },
            { "note", "FICT intended" },
            { "by", "FICT-ENG" },
            { "at", "2026-11-03T09:00:00+00:00" },
        };
        if (triage != null)
        {
            disposition["triage"] = triage;
        }

        return disposition;
    }

    /// <summary>
    /// The review's record as `GET /reviews/{run_id}` answers it from its folder: read-only, its two findings - F-001
    /// undecided and F-002 accepted with no triage when <paramref name="outcomesMissing"/>, both judged otherwise - and the
    /// line the backend composes for each, the console's sentence after 009's while a flagged finding records no outcome.
    /// </summary>
    private static string Folder(bool outcomesMissing) => new JsonObject
    {
        ["run_id"] = Run,
        ["read_only"] = true,
        ["read_only_reason"] = outcomesMissing ? MissingReason : ReviewPageSessionsTests.ReadOnlyReason,
        ["chat_state"] = null,
        ["last_seq"] = null,
        ["document"] = JsonNode.Parse(JsonSerializer.Serialize(new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" })),
        ["findings"] = new JsonArray(
            JsonNode.Parse(Finding("F-001", outcomesMissing ? null : Accepted("new_and_real"))),
            JsonNode.Parse(Finding("F-002", Accepted(outcomesMissing ? null : "already_known")))),
        ["evidence_requests"] = new JsonArray(),
        ["coverage"] = new JsonArray(),
        ["ranking"] = SummarySample.Ranking(),
        ["not_examined"] = null,
    }.ToJsonString();

    /// <summary>
    /// The page as a restart leaves it: the read-only line when shown, the cards, every decision, triage and note control and
    /// every question control with whether all are off, the follow-up box, Stop, Review, the status line, whether the minutes
    /// form shows, the chips' text, the pins' answers and the Transcript's text.
    /// </summary>
    private const string ReadPage = @"
var reason = document.getElementById('read-only');
var timing = document.getElementById('timing');
var count = function (selector) { return document.querySelectorAll(selector).length; };
var off = function (selector) {
  var found = document.querySelectorAll(selector);
  for (var i = 0; i < found.length; i++) { if (!found[i].disabled) { return false; } }
  return true;
};
var decisions = '#results .card.finding [data-action=""accept""], #results .card.finding [data-action=""reject""], '
  + '#results .card.finding [data-action=""defer""], #results .card.finding [data-action=""triage""], '
  + '#results .card.finding input.note';
var questions = '#questions button, #questions input, #questions textarea';
return JSON.stringify({
  ok: true,
  readOnly: h.rendered(reason) ? reason.textContent : null,
  cards: count('#results .card.finding'),
  decisions: count(decisions),
  decisionsOff: off(decisions),
  questions: count(questions),
  questionsOff: off(questions),
  followupOff: document.getElementById('followup-text').disabled && document.getElementById('followup-send').disabled,
  stopOff: document.getElementById('stop-turn').disabled,
  reviewOff: document.getElementById('start-review').disabled,
  status: document.getElementById('results-state').textContent,
  timingShown: !!timing && h.rendered(timing),
  chips: document.getElementById('review-chips').textContent,
  pins: h.texts(document.getElementById('answers'), '.pinned-answer'),
  transcript: document.getElementById('transcript').textContent
});";

    /// <summary>The read-only line at the pane's width, measured by <see cref="ReviewPageTriageTests.Whole"/>.</summary>
    private const string ReadLineWhole = @"
var line = document.getElementById('read-only');
" + ReviewPageTriageTests.Whole + @"
return JSON.stringify({
  ok: true,
  width: window.innerWidth,
  text: line.textContent,
  whole: !line.hidden && whole(line),
  noHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth
});";
}
