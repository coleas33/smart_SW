using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T107: a waiting review restored after a restart (feature 015 User Story 4), on the backend's
/// own `review-waiting-restored.json`: read-only with its dated line and Send offered; its Send
/// re-runs the checks (`review.recheck`) and then sends the re-run's chat, re-keying nothing
/// (owner decisions 68A and 73A; contracts/pane.md sections 4, 5 and 7 to 9; contracts/recheck.md
/// sections 7 and 10).
/// </summary>
public sealed class ReviewPageRecheckTests
{
    private const string Waiting = "Checked by code. Not sent to the model.";
    private const string WaitingNote = "Saving restarts the backend. The waiting review stays, and its Send checks its saved evidence again first.";
    private const string Rechecking = "Checking the saved evidence again.";
    private const string RecheckingNote = "Checking the saved evidence again; save when it is done.";

    [Fact]
    public void ARestoredReviewIsReadOnlyWithItsDatedLineAndSendAloneEnabled()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            JsonElement state = await driver.Read(ReadState);

            Assert.True(state.GetProperty("readOnly").GetBoolean(), state.GetRawText());
            string reason = state.GetProperty("reason").GetString()!;
            Assert.Equal(fixture.Restored.GetProperty("read_only_reason").GetString(), reason);
            Assert.StartsWith("The backend restarted, so this review is shown from its run folder. Its checks ran 2026-10-09 12:00;", reason);
            Assert.DoesNotContain("Follow-ups, decisions and answers are off.", reason);
            string sentence = fixture.Restored.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("text").GetString()!;
            Assert.DoesNotMatch("[0-9]", sentence);
            Assert.Contains(sentence, state.GetProperty("sendText").GetString());
            Assert.True(state.GetProperty("sendShown").GetBoolean());
            Assert.False(state.GetProperty("sendOff").GetBoolean(), "Send is the one control a restored waiting review offers.");
            Assert.True(state.GetProperty("decisions").GetInt32() > 0);
            Assert.True(state.GetProperty("decisionsOff").GetBoolean());
            Assert.True(state.GetProperty("questions").GetInt32() > 0);
            Assert.True(state.GetProperty("questionsOff").GetBoolean());
            Assert.True(state.GetProperty("followupOff").GetBoolean());
            Assert.Equal(Waiting, state.GetProperty("status").GetString());
            Assert.Equal(WaitingNote, state.GetProperty("settingsNote").GetString());
            Assert.Contains(" · not sent", state.GetProperty("chips").GetString());
            Assert.False(state.GetProperty("card").GetBoolean());
            Assert.Empty(driver.Posted("review.recheck"));
        });
    }

    [Fact]
    public void ItsSendRechecksFirstThenSendsTheRecheckedChatAndReKeysNothing()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await driver.ClearCalls();
            await PressSend(driver);

            Assert.Equal(RestoredReviewFixture.EarlierChat,
                Assert.Single(driver.Posted("review.recheck")).GetProperty("chat_id").GetString());
            string[] paths = (await driver.Calls()).Select(call => call.GetProperty("method").GetString() + " " + call.GetProperty("path").GetString()).ToArray();
            int snapshot = Array.IndexOf(paths, "GET /sessions/" + fixture.RecheckedChat + "/snapshot");
            int sent = Array.IndexOf(paths, "POST /sessions/" + fixture.RecheckedChat + "/send");
            Assert.True(snapshot >= 0 && sent > snapshot, string.Join(", ", paths));
            Assert.DoesNotContain(paths, path => path.Contains(RestoredReviewFixture.EarlierChat));
            Assert.DoesNotContain(paths, path => path.EndsWith("/evidence", StringComparison.Ordinal) || path.Contains("/findings/"));
            Assert.False((await driver.Read(ReadState)).GetProperty("readOnly").GetBoolean());
        });
    }

    [Fact]
    public void ASendRefusedAfterTheReRunLeavesTheLiveWaitingReviewUsable()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver => fixture.Configure(driver, refuseSend: true), async driver =>
        {
            await PressSend(driver);

            JsonElement state = await driver.Read(ReadState);
            Assert.False(state.GetProperty("readOnly").GetBoolean(), state.GetRawText());
            Assert.Equal(Waiting, state.GetProperty("status").GetString());
            Assert.False(state.GetProperty("questionsOff").GetBoolean());
            Assert.False(state.GetProperty("decisionsOff").GetBoolean());
            Assert.False(state.GetProperty("sendOff").GetBoolean());
            JsonElement send = fixture.Rechecked.GetProperty("ranking").GetProperty("summary").GetProperty("send");
            Assert.True(send.GetProperty("input_tokens").GetInt32() > 0);
            Assert.Contains(send.GetProperty("text").GetString()!, state.GetProperty("sendText").GetString());
            Assert.Contains(fixture.Label("NoCredential"), state.GetProperty("sendText").GetString());
            Assert.False(state.GetProperty("card").GetBoolean());
        });
    }

    [Fact]
    public void AReviewFoundAfterSolidWorksReopensIsAskedForFollowedAndRechecked()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        const string found = "00000000-0000-4000-8000-000000000002";
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.Document = null;
            driver.Sessions.Clear();
        }, async driver =>
        {
            Assert.Single(driver.Posted("sessions.list"));
            Assert.False((await driver.Read(ReadState)).GetProperty("statusShown").GetBoolean());
            driver.Sessions.Add(fixture.Item(found, "2020-01-02T03:04:00+09:30"));
            await driver.Route("GET", "/sessions/" + found + "/snapshot", 404, UnknownChat);

            await driver.DocumentChanged(fixture.ActiveDocument);
            await driver.Settle();

            Assert.Equal(2, driver.Posted("sessions.list").Length);
            JsonElement state = await driver.Read(ReadState);
            Assert.Contains(" 2020-01-02 03:04 · not sent", state.GetProperty("chips").GetString());
            Assert.True(state.GetProperty("readOnly").GetBoolean(), state.GetRawText());
            Assert.Equal(fixture.Restored.GetProperty("read_only_reason").GetString(), state.GetProperty("reason").GetString());
            Assert.False(state.GetProperty("sendOff").GetBoolean());

            // Asked again with the review on screen: the list is read, the review stays.
            await driver.DocumentChanged(fixture.ActiveDocument);
            await driver.Settle();
            Assert.Equal(3, driver.Posted("sessions.list").Length);
            Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == fixture.ReviewPath);
            Assert.True((await driver.Read(ReadState)).GetProperty("readOnly").GetBoolean());

            await PressSend(driver);
            Assert.Equal(found, Assert.Single(driver.Posted("review.recheck")).GetProperty("chat_id").GetString());
            Assert.Contains(await driver.Calls(), call => call.GetProperty("method").GetString() == "POST"
                && call.GetProperty("path").GetString() == "/sessions/" + fixture.RecheckedChat + "/send");
        });
    }

    [Fact]
    public void WhileAReRunIsHeldTheReviewIsBeingCheckedAndEveryOtherActionIsRefused()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver, refuseSend: true);
            driver.HoldReviewRecheck = true;
        }, async driver =>
        {
            await PressSend(driver);

            JsonElement held = await driver.Read(ReadState);
            Assert.Equal(Rechecking, held.GetProperty("status").GetString());
            Assert.Equal(RecheckingNote, held.GetProperty("settingsNote").GetString());
            Assert.True(held.GetProperty("saveOff").GetBoolean());
            Assert.True(held.GetProperty("reviewOff").GetBoolean());
            Assert.True(held.GetProperty("chipsOff").GetBoolean());
            Assert.True(held.GetProperty("sendOff").GetBoolean());
            Assert.True(held.GetProperty("stopOff").GetBoolean());
            await PressSend(driver);
            Assert.Single(driver.Posted("review.recheck"));

            await driver.ReleaseReviewRecheck();

            JsonElement released = await driver.Read(ReadState);
            Assert.False(released.GetProperty("readOnly").GetBoolean(), released.GetRawText());
            Assert.Equal(Waiting, released.GetProperty("status").GetString());
            Assert.Equal(WaitingNote, released.GetProperty("settingsNote").GetString());
            Assert.False(released.GetProperty("saveOff").GetBoolean());
            Assert.False(released.GetProperty("chipsOff").GetBoolean());
        });
    }

    [Fact]
    public void AFailedReRunPrintsItsLineKeepsTheReviewReadOnlyAndOffersSendNotRetry()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.RecheckError = new { error_class = "InvalidPackage", message = "FICT the saved package cannot be read", retryable = false };
        }, async driver =>
        {
            await PressSend(driver);

            JsonElement state = await driver.Read(ReadState);
            Assert.Equal(fixture.Restored.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("rerun_failed_text").GetString(),
                state.GetProperty("failure").GetString());
            Assert.Equal("InvalidPackage", state.GetProperty("foldClass").GetString());
            Assert.Contains("FICT the saved package cannot be read", state.GetProperty("sendText").GetString());
            Assert.True(state.GetProperty("readOnly").GetBoolean());
            Assert.False(state.GetProperty("sendOff").GetBoolean());
            Assert.False(state.GetProperty("card").GetBoolean());
            Assert.False(state.GetProperty("retry").GetBoolean());
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString()!.Contains(fixture.RecheckedChat));
        });
    }

    [Fact]
    public void AReRunOfAFolderThatIsGoneSaysItCanNoLongerBeRestored()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.RecheckError = new { error_class = "UnknownReview", message = "no review FICT", retryable = false };
        }, async driver =>
        {
            await PressSend(driver);

            JsonElement state = await driver.Read(ReadState);
            Assert.Contains("This review can no longer be restored.", state.GetProperty("chips").GetString());
            Assert.False(state.GetProperty("readOnly").GetBoolean());
            Assert.False(state.GetProperty("sendShown").GetBoolean());
            Assert.False(state.GetProperty("statusShown").GetBoolean());
        });
    }

    [Fact]
    public void ABackendRestartWithALiveWaitingReviewOnScreenRestoresItAtOnce()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver => fixture.Configure(driver, refuseSend: true), async driver =>
        {
            await PressSend(driver);
            Assert.False((await driver.Read(ReadState)).GetProperty("readOnly").GetBoolean());
            await driver.Route("GET", "/sessions/" + fixture.RecheckedChat + "/snapshot", 404, UnknownChat);
            int reviews = (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath);

            driver.BackendToken = "FICT-restarted-backend-token";
            await driver.Click("save-settings");
            await driver.Settle();

            JsonElement state = await driver.Read(ReadState);
            Assert.True(state.GetProperty("readOnly").GetBoolean(), state.GetRawText());
            Assert.Equal(fixture.Restored.GetProperty("read_only_reason").GetString(), state.GetProperty("reason").GetString());
            Assert.False(state.GetProperty("sendOff").GetBoolean());
            Assert.Equal(reviews + 1, (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath));
        });
    }

    [Fact]
    public void AReloadWhileAReRunIsHeldShowsNothingUntilTheReleaseThenTheLiveWaitingReview()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.HoldReviewRecheck = true;
        }, async driver =>
        {
            await PressSend(driver);
            await driver.ReloadWhileRecheckHeld();

            JsonElement reloaded = await driver.Read(ReadState);
            Assert.False(reloaded.GetProperty("statusShown").GetBoolean(), reloaded.GetRawText());
            Assert.False(reloaded.GetProperty("readOnly").GetBoolean());
            Assert.Equal(0, reloaded.GetProperty("chipCount").GetInt32());

            await driver.ReleaseReviewRecheck();
            await driver.Settle();

            JsonElement shown = await driver.Read(ReadState);
            Assert.Equal(Waiting, shown.GetProperty("status").GetString());
            Assert.False(shown.GetProperty("readOnly").GetBoolean(), shown.GetRawText());
            Assert.True(shown.GetProperty("stopOff").GetBoolean());
            Assert.Single(driver.Posted("review.recheck"));
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString()!.EndsWith("/send", StringComparison.Ordinal));
        });
    }

    [Fact]
    public void AnApplyThatFailsAfterTheReRunRestoresTheReviewFromItsFolderWithSend()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver => fixture.Configure(driver, refuseSend: true), async driver =>
        {
            await PressSend(driver);
            int reviews = (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath);
            await driver.Route("POST", "/sessions/" + fixture.RecheckedChat + "/evidence", 202, "{}");

            await driver.Read("document.querySelector('#questions [data-action=question-option]').click();return JSON.stringify({ok:true});");
            await driver.Read("document.querySelector('#questions [data-action=question-send]').click();return JSON.stringify({ok:true});");
            await driver.Settle();
            Assert.Contains(await driver.Calls(), call => call.GetProperty("path").GetString() == "/sessions/" + fixture.RecheckedChat + "/evidence");

            int seq = fixture.Rechecked.GetProperty("last_seq").GetInt32() + 1;
            await driver.Push(fixture.RecheckedChat, seq, "error",
                "{\"error_class\":\"FICTApplyFailed\",\"message\":\"FICT the apply could not be written\",\"retryable\":true}");
            await driver.Settle();

            JsonElement state = await driver.Read(ReadState);
            Assert.False(state.GetProperty("card").GetBoolean(), state.GetRawText());
            Assert.True(state.GetProperty("readOnly").GetBoolean());
            Assert.Equal(fixture.Restored.GetProperty("read_only_reason").GetString(), state.GetProperty("reason").GetString());
            Assert.False(state.GetProperty("sendOff").GetBoolean());
            Assert.Equal("FICTApplyFailed", state.GetProperty("foldClass").GetString());
            Assert.Equal(reviews + 1, (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath));
        });
    }

    // ---- plumbing -------------------------------------------------------------------------

    internal const string UnknownChat = "{\"error_class\":\"UnknownChat\",\"message\":\"no chat FICT\",\"retryable\":false}";

    internal static async Task PressSend(ReviewPageDriver driver)
    {
        await driver.Read("var b=document.querySelector('#send [data-action=send]');if(b)b.click();return JSON.stringify({ok:true});");
        await driver.Settle();
    }

    internal const string ReadState = @"
var send=document.querySelector('#send [data-action=send]');
var reason=document.getElementById('read-only');
var decisions=document.querySelectorAll('#results .card.finding [data-action=accept],#results .card.finding [data-action=reject],#results .card.finding [data-action=defer]');
var questions=document.querySelectorAll('#questions button,#questions input');
var chips=document.querySelectorAll('#review-chips [data-action=review-chip]');
var failure=document.querySelector('#send .plain-error-text,#send .note.bad');
var fold=document.querySelector('#send .error-fold .error-class');
var status=document.getElementById('results-state');
var all=function(list){for(var i=0;i<list.length;i++){if(!list[i].disabled)return false;}return true;};
return JSON.stringify({ok:true,
 readOnly:h.rendered(reason),reason:reason.textContent,
 sendShown:h.rendered(send),sendOff:send?send.disabled:null,sendText:document.getElementById('send').textContent,
 failure:failure?failure.textContent:null,foldClass:fold?fold.textContent:null,
 decisions:decisions.length,decisionsOff:all(decisions),questions:questions.length,questionsOff:all(questions),
 followupOff:document.getElementById('followup-text').disabled,
 status:status.textContent,statusShown:!status.hidden,
 settingsNote:document.getElementById('waiting-settings-note').textContent,
 saveOff:document.getElementById('save-settings').disabled,reviewOff:document.getElementById('start-review').disabled,
 stopOff:document.getElementById('stop-turn').disabled,chipsOff:all(chips),chipCount:chips.length,
 chips:document.getElementById('review-chips').textContent,
 card:!!document.querySelector('#errors .card.error'),retry:!!document.querySelector('[data-action=retry]')});";
}

/// <summary>
/// The backend's `review-waiting-restored.json` (T101-T102) played by the driver: one kept review
/// whose chat the restarted backend no longer holds, its run folder's read-only snapshot, and the
/// re-run's `POST /sessions` answer and live snapshot.
/// </summary>
internal sealed class RestoredReviewFixture
{
    public const string EarlierChat = "FICT-earlier-chat";

    private RestoredReviewFixture(JsonElement root, string fileName)
    {
        Root = root;
        FileName = fileName;
    }

    public JsonElement Root { get; }

    public string FileName { get; }

    public JsonElement Restored => Root.GetProperty("restored");

    public JsonElement Rechecked => Root.GetProperty("rechecked").GetProperty("snapshot");

    public JsonElement Answer => Root.GetProperty("rechecked").GetProperty("answer");

    public string RecheckedChat => Answer.GetProperty("chat_id").GetString()!;

    public string ReviewPath => "/reviews/" + Restored.GetProperty("run_id").GetString();

    public object ActiveDocument => new
    {
        path = Restored.GetProperty("document").GetProperty("path").GetString(),
        configuration = Restored.GetProperty("document").GetProperty("configuration").GetString(),
        kind = "assembly",
    };

    public static RestoredReviewFixture Read(string fileName = "review-waiting-restored.json")
    {
        WaitingReviewFixture read = WaitingReviewFixture.Read(fileName);
        return new RestoredReviewFixture(read.Root, fileName);
    }

    public string Label(string errorClass) =>
        Root.GetProperty("labels").GetProperty("errors").GetProperty(errorClass).GetString()!;

    public Dictionary<string, object?> Item(string chatId, string startedAt) => new Dictionary<string, object?>
    {
        { "chat_id", chatId },
        { "run_id", Restored.GetProperty("run_id").GetString() },
        { "run_dir", @"C:\Fictional\FICT-runs\" + Restored.GetProperty("run_id").GetString() },
        { "path", Restored.GetProperty("document").GetProperty("path").GetString() },
        { "configuration", Restored.GetProperty("document").GetProperty("configuration").GetString() },
        { "started_at", startedAt },
        { "model_status", "not_sent" },
    };

    /// <summary>
    /// A page opened on the reviewed document after a restart: the host keeps the review's record,
    /// the backend no longer holds its chat, and its folder answers the restored snapshot.
    /// </summary>
    public void Configure(ReviewPageDriver driver) => Configure(driver, refuseSend: false);

    public void Configure(ReviewPageDriver driver, bool refuseSend)
    {
        driver.Document = ActiveDocument;
        driver.SendWhenChecked = false;
        driver.KeySource = "none";
        driver.Sessions.Add(Item(EarlierChat, "2026-10-09T12:00:00+00:00"));
        driver.InitialRoutes.Add(("GET", "/labels", 200, Root.GetProperty("labels").GetRawText()));
        driver.InitialRoutes.Add(("GET", "/sessions/" + EarlierChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat));
        driver.InitialRoutes.Add(("GET", ReviewPath, 200, Restored.GetRawText()));
        if (Root.TryGetProperty("rechecked", out JsonElement rechecked))
        {
            driver.InitialRoutes.Add(("GET", "/sessions/" + RecheckedChat + "/snapshot", 200, rechecked.GetProperty("snapshot").GetRawText()));
            driver.InitialRoutes.Add(("GET", "/sessions/" + RecheckedChat + "/attention", 200, rechecked.GetProperty("snapshot").GetProperty("ranking").GetRawText()));
            driver.InitialRoutes.Add(refuseSend
                ? ("POST", "/sessions/" + RecheckedChat + "/send", 409, "{\"error_class\":\"NoCredential\",\"message\":\"FICT no key is set\",\"retryable\":false}")
                : ("POST", "/sessions/" + RecheckedChat + "/send", 202, "{}"));
            driver.RecheckReply = previous => new Dictionary<string, object?>
            {
                { "chat_id", RecheckedChat },
                { "previous_chat_id", previous },
                { "run_dir", @"C:\Fictional\FICT-runs\" + Restored.GetProperty("run_id").GetString() },
                { "not_examined", JsonDocument.Parse(Answer.GetProperty("not_examined").GetRawText()).RootElement.Clone() },
                { "document", JsonDocument.Parse(Restored.GetProperty("document").GetRawText()).RootElement.Clone() },
            };
        }
    }
}
