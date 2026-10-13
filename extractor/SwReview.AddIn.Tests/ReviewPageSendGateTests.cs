using System;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

public sealed class ReviewPageSendGateTests
{
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void TheBoxIsInTheSessionAfterItsButtonsAndSavesEachChangeImmediately(bool send)
    {
        ReviewPageDriver.Run(driver => driver.SendWhenChecked = send, async driver =>
        {
            JsonElement initial = await driver.Read(ReadBox);
            Assert.Equal(send, initial.GetProperty("checked").GetBoolean());
            Assert.False(initial.GetProperty("disabled").GetBoolean());
            Assert.True(initial.GetProperty("afterButtons").GetBoolean());
            await driver.ChangeSendWhenChecked(!send);
            Assert.Equal(!send, Assert.Single(driver.Posted("send_when_checked.save")).GetProperty("send_when_checked").GetBoolean());
            Assert.Equal(!send, (await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
        });
    }

    [Fact]
    public void TheSettingsSavedViewAndAReInitRefreshTheBoxFromTheStoredValue()
    {
        ReviewPageDriver.Run(driver => driver.SendWhenChecked = false, async driver =>
        {
            Assert.False((await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
            driver.SendWhenChecked = true;
            await driver.Click("save-settings");
            Assert.True((await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
            driver.SendWhenChecked = false;
            await driver.Reload();
            Assert.False((await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
        });
    }

    [Fact]
    public void RapidChangesRetainTheNewChoiceAndRollbackToTheLatestConfirmedValue()
    {
        ReviewPageDriver.Run(driver => driver.HoldSendWhenCheckedSave = true, async driver =>
        {
            await driver.ChangeSendWhenChecked(false);
            await driver.ChangeSendWhenChecked(true);
            Assert.Equal(2, driver.Posted("send_when_checked.save").Length);
            await driver.ReleaseSendWhenCheckedSave();
            Assert.True((await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
            await driver.ReleaseSendWhenCheckedSave(new { error_class = "SettingNotSaved", message = "FICT-write failed", retryable = false });
            Assert.False((await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
            Assert.False((await driver.Read(ReadBox)).GetProperty("disabled").GetBoolean());
        });
    }

    [Fact]
    public void ARefusedBoxSaveShowsTheLabelAndTheNextChangeClearsIt()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            driver.SendWhenCheckedSaveError = new { error_class = "SettingNotSaved", message = "FICT-write failed", retryable = false };
            await driver.ChangeSendWhenChecked(true);
            JsonElement refused = await driver.Read(ReadBox);
            Assert.False(refused.GetProperty("checked").GetBoolean());
            Assert.Contains(fixture.Root.GetProperty("labels").GetProperty("errors").GetProperty("SettingNotSaved").GetString()!, refused.GetProperty("note").GetString());
            driver.SendWhenCheckedSaveError = null;
            await driver.ChangeSendWhenChecked(true);
            Assert.Equal("", (await driver.Read(ReadBox)).GetProperty("note").GetString());
        });
    }

    [Fact]
    public void TheBoxStaysEnabledDuringAHeldStartAndItsReplyControlsTheReviewState()
    {
        ReviewPageDriver.Run(driver => { driver.SendWhenChecked = false; driver.HoldReviewStart = true; }, async driver =>
        {
            await driver.StartReview();
            await driver.ChangeSendWhenChecked(true);
            JsonElement held = await driver.Read(ReadBox);
            Assert.True(held.GetProperty("checked").GetBoolean());
            Assert.False(held.GetProperty("disabled").GetBoolean());
            string[] types = driver.PostedTypes();
            Assert.True(Array.IndexOf(types, "review.start") < Array.IndexOf(types, "send_when_checked.save"));
            await driver.ReleaseReviewStart();
            Assert.Equal("Checked by code. Not sent to the model.", (await driver.Read(ReadWaiting)).GetProperty("status").GetString());
            Assert.True((await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
        });
    }

    [Fact]
    public void TheBoxStaysEnabledWhileATickedTurnRuns()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.StartReview();
            Assert.False((await driver.Read(ReadBox)).GetProperty("disabled").GetBoolean());
            await driver.ChangeSendWhenChecked(false);
            Assert.False((await driver.Read(ReadBox)).GetProperty("checked").GetBoolean());
            Assert.False((await driver.Read("return JSON.stringify({ok:true, disabled:document.getElementById('stop-turn').disabled});")).GetProperty("disabled").GetBoolean());
        });
    }

    [Fact]
    public void UntickedPreparationUsesNoTokensAndTheBoxIsReadAtReviewAvailableEvidence()
    {
        ReviewPageDriver.Run(driver =>
        {
            driver.SendWhenChecked = false;
            driver.PreparationReply = new
            {
                preparation_id = "FICT-preparation",
                document = driver.Document,
                component_count = 2, unread_count = 1, gap_count = 0,
                instances = new object[0], omitted_instances = 0,
                requires_attention = true, standards_configured = true,
            };
        }, async driver =>
        {
            await driver.StartReview();
            Assert.Empty(driver.Posted("review.start"));
            Assert.Contains("No review tokens have been used.", (await driver.Read("return JSON.stringify({ok:true,text:document.getElementById('preparation-summary').textContent});")).GetProperty("text").GetString());
            await driver.ChangeSendWhenChecked(true);
            await driver.Click("preparation-continue");
            Assert.Single(driver.Posted("review.start"));
            Assert.Equal("The review is running.", (await driver.Read(ReadWaiting)).GetProperty("status").GetString());
        });
    }

    [Fact]
    public void AnUntickedReviewShowsTheBackendSentenceAndNeverRunsATurnOrAllowsAFollowUp()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            JsonElement waiting = await driver.Read(ReadWaiting);
            Assert.Equal("Checked by code. Not sent to the model.", waiting.GetProperty("status").GetString());
            Assert.True(waiting.GetProperty("stopOff").GetBoolean());
            Assert.True(waiting.GetProperty("followupOff").GetBoolean());
            Assert.Equal("Not sent to the model yet: press Send to model first", waiting.GetProperty("placeholder").GetString());
            Assert.True(waiting.GetProperty("sendAfterSummary").GetBoolean());
            Assert.True(waiting.GetProperty("sendBeforeQuestions").GetBoolean());
            Assert.Contains(fixture.Waiting.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("text").GetString()!, waiting.GetProperty("sendText").GetString());
            Assert.Contains("Send to model", waiting.GetProperty("sendText").GetString());
            Assert.Contains("Checked by code only: nothing is sent to the model until Send to model is pressed.", waiting.GetProperty("transcript").GetString());
            Assert.Contains("The checks ended at 2026-10-09T12:00:00+00:00. Nothing was sent to the model.", waiting.GetProperty("transcript").GetString());
            await driver.Click("toggle-settings");
            Assert.Contains("Saving restarts the backend. The waiting review stays, and its Send checks its saved evidence again first.", waiting.GetProperty("settingsNote").GetString());
            Assert.Equal("No key is stored. With the box ticked a review fails until one is entered; with it unticked the code checks run and Send waits for a key.", (await driver.Read("return JSON.stringify({ok:true,text:document.getElementById('key-source').textContent});")).GetProperty("text").GetString());
        });
    }

    [Fact]
    public void ClearSwitchAndReviewAgainKeepTheWaitingChipAndMakeNoModelProxyCall()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            await driver.ClearCalls();
            await driver.Click("clear-review");
            await driver.DocumentChanged(new { path = @"C:\Fictional\FICT-other.SLDPRT", configuration = "Default" });
            await driver.DocumentChanged(fixture.Waiting.GetProperty("document").Clone());
            await driver.Click("start-review");
            await driver.Read("document.querySelector(\"[data-chat-id='chat-1']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            JsonElement waiting = await driver.Read(ReadWaiting);
            Assert.Equal("Checked by code. Not sent to the model.", waiting.GetProperty("status").GetString());
            Assert.True(waiting.GetProperty("stopOff").GetBoolean());
            Assert.Contains(" · not sent", waiting.GetProperty("chips").GetString());
            Assert.True(waiting.GetProperty("sendShown").GetBoolean());
            Assert.DoesNotContain(await driver.Calls(), call => new[] { "/send", "/messages", "/evidence" }.Any(suffix => call.GetProperty("path").GetString()!.EndsWith(suffix, StringComparison.Ordinal)));
        });
    }

    [Fact]
    public void AReloadMarksTheWaitingChipBeforeItIsChosenAndDoesNotMarkATickedChip()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.Sessions.Add(new System.Collections.Generic.Dictionary<string, object?> { { "chat_id", "ticked" }, { "run_id", "FICT-ticked" }, { "path", @"C:\Fictional\FICT-other.SLDPRT" }, { "configuration", "Default" }, { "started_at", "2026-10-09T13:00:00+00:00" } });
        }, async driver =>
        {
            await driver.Reload();
            JsonElement chips = await driver.Read("return JSON.stringify({ok:true,waiting:h.text(document,'[data-chat-id=\"chat-1\"]'),ticked:h.text(document,'[data-chat-id=\"ticked\"]')});");
            Assert.Contains(" · not sent", chips.GetProperty("waiting").GetString());
            Assert.DoesNotContain("not sent", chips.GetProperty("ticked").GetString());
            Assert.Equal("Checked by code. Not sent to the model.", (await driver.Read(ReadWaiting)).GetProperty("status").GetString());
        });
    }

    [Fact]
    public void AnUntickedStartRefusalStillShowsTheErrorCardAndRetryWithoutSend()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(driver => { fixture.Configure(driver); driver.ReviewStartError = new { error_class = "InvalidPackage", message = "FICT-invalid package", retryable = true }; driver.Sessions.Clear(); }, async driver =>
        {
            await driver.StartReview();
            JsonElement error = await driver.Read("return JSON.stringify({ok:true,card:!!document.querySelector('#errors .card.error'),retry:!!document.querySelector('#errors [data-action=retry]'),send:h.rendered(document.getElementById('send'))});");
            Assert.True(error.GetProperty("card").GetBoolean());
            Assert.True(error.GetProperty("retry").GetBoolean());
            Assert.False(error.GetProperty("send").GetBoolean());
        });
    }

    /// <summary>A renderer lifecycle harness, pending the separate real waiting-fixture
    /// acceptance below: a refusal must never leave the prior summary's Send controls active.</summary>
    [Fact]
    public void ARefusedSecondStartClearsTheWaitingPresentationAndKeepsTheChipInThePageHarness()
    {
        ReviewFixture fixture = ReviewFixture.Value;
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.SendWhenChecked = false;
            driver.ReviewStarted = _ => new { chat_id = "chat-1", run_dir = fixture.RunDirectory,
                document = fixture.Document, send_when_checked = false };
            driver.Sessions.Add(new System.Collections.Generic.Dictionary<string, object?>
            {
                { "chat_id", "chat-1" }, { "run_id", fixture.RunId }, { "path", fixture.DocumentPath },
                { "configuration", fixture.DocumentConfiguration }, { "model_status", "not_sent" },
            });
        }, async driver =>
        {
            await fixture.Review(driver, fixture.RankingJson(summary =>
                summary["send"] = System.Text.Json.Nodes.JsonNode.Parse("{\"text\":\"FICT-harness waiting sentence\"}")));
            Assert.True((await driver.Read(ReadWaiting)).GetProperty("sendShown").GetBoolean());
            await AssertSecondStartRefusedWithoutSend(driver);
            // The old chip still performs the normal restore GET; no host removal occurred.
            await driver.Read("document.querySelector(\"[data-chat-id='chat-1']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            Assert.Contains(await driver.Calls(), call => call.GetProperty("path").GetString() == "/sessions/chat-1/snapshot");
            Assert.Empty(driver.Posted("session.forget"));
        });
    }

    [Fact]
    public void ARefusedSecondStartFromTheRealWaitingFixtureClearsSendAndItsChipRestoresTheWaitingReview()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            Assert.True((await driver.Read(ReadWaiting)).GetProperty("sendShown").GetBoolean());
            await AssertSecondStartRefusedWithoutSend(driver);
            await driver.Read("document.querySelector(\"[data-chat-id='chat-1']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            Assert.True((await driver.Read(ReadWaiting)).GetProperty("sendShown").GetBoolean());
            Assert.Equal("Checked by code. Not sent to the model.", (await driver.Read(ReadWaiting)).GetProperty("status").GetString());
        });
    }

    private static async System.Threading.Tasks.Task AssertSecondStartRefusedWithoutSend(ReviewPageDriver driver)
    {
        driver.ReviewStartError = new { error_class = "InvalidPackage", message = "FICT-invalid second package", retryable = true };
        await driver.StartReview();
        JsonElement refused = await driver.Read(@"
return JSON.stringify({ok:true,card:!!document.querySelector('#errors .card.error'),
 retry:!!document.querySelector('#errors [data-action=retry]'),send:h.rendered(document.getElementById('send')),
 summary:h.rendered(document.getElementById('summary')),chips:document.getElementById('review-chips').textContent});");
        Assert.Equal(2, driver.Starts);
        Assert.True(refused.GetProperty("card").GetBoolean());
        Assert.True(refused.GetProperty("retry").GetBoolean());
        Assert.False(refused.GetProperty("send").GetBoolean());
        Assert.False(refused.GetProperty("summary").GetBoolean());
        Assert.Contains(" · not sent", refused.GetProperty("chips").GetString());
    }

    internal const string ReadBox = @"
var box=document.getElementById('send-when-checked');
return JSON.stringify({ok:true,checked:box.checked,disabled:box.disabled,
 afterButtons:box.parentNode.classList.contains('send-when-checked') && box.parentNode.parentNode.id==='session' && box.parentNode.previousElementSibling.classList.contains('row'),
 note:document.getElementById('send-when-checked-note').textContent});";

    internal const string ReadWaiting = @"
var send=document.getElementById('send');
return JSON.stringify({ok:true,status:document.getElementById('results-state').textContent,
 stopOff:document.getElementById('stop-turn').disabled,followupOff:document.getElementById('followup-text').disabled,
 placeholder:document.getElementById('followup-text').placeholder,sendShown:h.rendered(send),
 sendAfterSummary:send.previousElementSibling.id==='summary',sendBeforeQuestions:send.nextElementSibling.id==='questions',
 sendText:send.textContent,transcript:document.getElementById('transcript').textContent,
 chips:document.getElementById('review-chips').textContent,settingsNote:document.getElementById('waiting-settings-note').textContent});";
}
