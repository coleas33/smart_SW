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

    [Fact]
    public void SendPostsForTheShownChatReopensTheStreamAndClearsTheWaitingGuardAtFirstUsage()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            await AcceptSend(driver, "chat-1");
            await driver.ClearCalls();
            int opened = driver.Posted("events.open").Length;
            await driver.Read("var send=document.querySelector('#send [data-action=send]');send.click();send.click();return JSON.stringify({ok:true});");
            await driver.Settle();
            JsonElement sent = Assert.Single(await driver.Calls(), IsSend);
            Assert.Equal("POST", sent.GetProperty("method").GetString());
            Assert.Equal("/sessions/chat-1/send", sent.GetProperty("path").GetString());
            Assert.Equal("Bearer " + ReviewPageDriver.Token, sent.GetProperty("authorization").GetString());
            JsonElement running = await driver.Read(ReadSendState);
            Assert.False(running.GetProperty("sendShown").GetBoolean());
            Assert.Equal("The review is running.", running.GetProperty("status").GetString());
            Assert.False(running.GetProperty("stopOff").GetBoolean());
            Assert.True(running.GetProperty("followupOff").GetBoolean());
            Assert.Equal("Not sent to the model yet: press Send to model first", running.GetProperty("placeholder").GetString());
            Assert.Equal(opened + 1, driver.Posted("events.open").Length);
            Assert.Equal("2", driver.Posted("events.open").Last().GetProperty("last_event_id").GetString());
            await driver.Route("POST", "/sessions/chat-1/stop", 202, "{}");
            await driver.Click("stop-turn");
            Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == "/sessions/chat-1/stop");
            await driver.Push("chat-1", 3, "session.sent", SentEvent);
            await driver.Push("chat-1", 4, "usage", UsageEvent);
            await driver.Settle();
            JsonElement used = await driver.Read(ReadSendState);
            Assert.DoesNotContain("not sent", used.GetProperty("chips").GetString());
            Assert.Equal("Ask a follow-up about any finding", used.GetProperty("placeholder").GetString());
            Assert.True(used.GetProperty("followupOff").GetBoolean()); // Today's running-turn gate still holds.
            Assert.False(used.GetProperty("sendShown").GetBoolean());
            Assert.Contains("Sending to openai FICT-model (high -> reasoning_effort=high) - first request 12,905 input tokens", used.GetProperty("transcript").GetString());
            await driver.Push("chat-1", 5, "turn.ended", "{\"reason\":\"end\"}");
            await driver.Settle();
            JsonElement ended = await driver.Read(ReadSendState);
            Assert.False(ended.GetProperty("followupOff").GetBoolean());
            Assert.False(ended.GetProperty("sendShown").GetBoolean());
            driver.Sessions[0].Remove("model_status");
            await RefreshSessions(driver);
            Assert.DoesNotContain("not sent", (await driver.Read(ReadSendState)).GetProperty("chips").GetString());
        });
    }

    [Fact]
    public void ADelayedSessionsAnswerCannotRestoreTheMarkAfterThisPageHasSeenUsage()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            driver.HoldSessions = true;
            await fixture.Start(driver);
            await AcceptSend(driver, "chat-1");
            await PressSend(driver);
            await driver.Push("chat-1", 3, "usage", UsageEvent);
            await driver.Settle();
            await driver.ReleaseSessions();
            Assert.DoesNotContain("not sent", (await driver.Read(ReadSendState)).GetProperty("chips").GetString());
            await driver.Push("chat-1", 4, "turn.ended", "{\"reason\":\"end\"}");
            await driver.Settle();
            driver.Sessions[0].Remove("model_status");
            await RefreshSessions(driver);
            Assert.DoesNotContain("not sent", (await driver.Read(ReadSendState)).GetProperty("chips").GetString());
        });
    }

    [Fact]
    public void APreUsageAttentionResponseCannotBringSendBackAfterTheFirstModelRound()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            // The real waiting snapshot restored at boot supplies the finding and summary.
            await AcceptSend(driver, "chat-1");
            await PressSend(driver);
            await driver.HoldRoute("GET", "/sessions/chat-1/attention", 200, fixture.Waiting.GetProperty("ranking").GetRawText());
            int seq = fixture.Waiting.GetProperty("last_seq").GetInt32();
            string findingId = fixture.Waiting.GetProperty("findings")[0].GetProperty("id").GetString()!;
            await driver.Push("chat-1", ++seq, "finding.withdrawn", JsonSerializer.Serialize(new { finding_id = findingId }));
            await driver.Settle();
            Assert.Equal(1, (await driver.Read("return JSON.stringify({ok:true,held:window.__fetch.held.length});")).GetProperty("held").GetInt32());
            await driver.Push("chat-1", ++seq, "usage", UsageEvent);
            await driver.Settle();
            await driver.ReleaseRoute("GET", "/sessions/chat-1/attention");
            JsonElement used = await driver.Read(ReadSendState);
            Assert.False(used.GetProperty("sendShown").GetBoolean());
            Assert.Equal("Ask a follow-up about any finding", used.GetProperty("placeholder").GetString());
            await driver.Push("chat-1", ++seq, "turn.ended", "{\"reason\":\"end\"}");
            await driver.Settle();
            JsonElement ended = await driver.Read(ReadSendState);
            Assert.False(ended.GetProperty("sendShown").GetBoolean());
            Assert.False(ended.GetProperty("followupOff").GetBoolean());
        });
    }

    [Theory]
    [InlineData("NoCredential")]
    [InlineData("TurnRunning")]
    public void ARefusedSendKeepsTheBlockPrintsItsLabelAndCanBePressedAgain(string errorClass)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            await driver.Route("POST", "/sessions/chat-1/send", 409, JsonSerializer.Serialize(new
            {
                error_class = errorClass, message = "FICT-refusal <img src=x>", retryable = false,
            }));
            int opened = driver.Posted("events.open").Length;
            await PressSend(driver);
            JsonElement refused = await driver.Read(ReadSendState);
            Assert.Single(await driver.Calls(), IsSend);
            Assert.True(refused.GetProperty("sendShown").GetBoolean());
            Assert.False(refused.GetProperty("sendOff").GetBoolean());
            Assert.True(refused.GetProperty("stopOff").GetBoolean());
            Assert.Equal(opened, driver.Posted("events.open").Length);
            Assert.False(refused.GetProperty("card").GetBoolean());
            Assert.False(refused.GetProperty("retry").GetBoolean());
            Assert.Equal(fixture.Root.GetProperty("labels").GetProperty("errors").GetProperty(errorClass).GetString(), refused.GetProperty("refusal").GetString());
            Assert.Contains(errorClass, refused.GetProperty("sendText").GetString());
            Assert.Contains("FICT-refusal <img src=x>", refused.GetProperty("sendText").GetString());
            Assert.Equal(0, refused.GetProperty("injected").GetInt32());
            await AcceptSend(driver, "chat-1");
            await PressSend(driver);
            Assert.Equal(2, (await driver.Calls()).Count(IsSend));
            Assert.False((await driver.Read(ReadSendState)).GetProperty("sendShown").GetBoolean());
        });
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(true, false)]
    [InlineData(false, true)]
    [InlineData(true, true)]
    public void AFailedSendReturnsToWaitingWithoutAnErrorCardAndPreservesItsStreamedText(bool reload, bool onlyError)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement sending = fixture.Root.GetProperty("sending");
        JsonElement failed = fixture.Root.GetProperty("failed_send");
        Assert.True(sending.GetProperty("send_in_flight").GetBoolean());
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            int seq;
            if (reload)
            {
                driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
                driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, sending.GetRawText()));
                await driver.Reload();
                seq = sending.GetProperty("last_seq").GetInt32();
                JsonElement restored = await driver.Read(ReadSendState);
                Assert.Equal("The review is running.", restored.GetProperty("status").GetString());
                Assert.False(restored.GetProperty("sendShown").GetBoolean());
                Assert.False(restored.GetProperty("stopOff").GetBoolean());
                Assert.True(restored.GetProperty("followupOff").GetBoolean());
            }
            else
            {
                await fixture.Start(driver);
                await AcceptSend(driver, "chat-1");
                await PressSend(driver);
                seq = 2;
            }
            await driver.RouteAttention("chat-1", failed.GetProperty("ranking").GetRawText());
            await driver.ClearCalls();
            if (!onlyError)
                await driver.Push("chat-1", ++seq, "text.delta", "{\"text\":\"FICT-text before failed round\"}");
            await driver.Push("chat-1", ++seq, "error", "{\"error_class\":\"FICTSendError\",\"message\":\"FICT-first request failed\",\"retryable\":true}");
            await driver.Settle();
            AssertWaitingFailure(await driver.Read(ReadSendState), failed, !onlyError);
            Assert.Contains(await driver.Calls(), call => call.GetProperty("path").GetString() == "/sessions/chat-1/attention");
            if (!onlyError)
            {
                await driver.Push("chat-1", ++seq, "turn.ended", "{\"reason\":\"error\"}");
                await driver.Push("chat-1", ++seq, "session.ended", "{\"ended_at\":\"2026-10-12T12:00:00+00:00\"}");
                await driver.Settle();
                JsonElement settled = await driver.Read(ReadSendState);
                AssertWaitingFailure(settled, failed, true);
                Assert.Contains("The turn ended: error.", settled.GetProperty("transcript").GetString());
            }
            await AcceptSend(driver, "chat-1");
            await PressSend(driver);
            Assert.Single(await driver.Calls(), IsSend);
            Assert.False((await driver.Read(ReadSendState)).GetProperty("sendShown").GetBoolean());
        });
    }

    [Fact]
    public void ASendWhichHasReceivedUsageKeepsTodaysErrorCardForALaterFailure()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            await AcceptSend(driver, "chat-1");
            await PressSend(driver);
            await driver.Push("chat-1", 3, "usage", UsageEvent);
            await driver.Push("chat-1", 4, "error", "{\"error_class\":\"FICTLaterError\",\"message\":\"FICT-after a round\",\"retryable\":true}");
            await driver.Settle();
            JsonElement failed = await driver.Read(ReadSendState);
            Assert.True(failed.GetProperty("card").GetBoolean());
            Assert.True(failed.GetProperty("retry").GetBoolean());
            Assert.False(failed.GetProperty("sendShown").GetBoolean());
        });
    }

    [Fact]
    public void ATickedFirstRequestFailureKeepsTodaysErrorCardAndRetryAndNeverOffersSend()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.StartReview();
            await driver.Push("chat-1", 1, "error", "{\"error_class\":\"FICTTickedError\",\"message\":\"FICT-first request failed\",\"retryable\":true}");
            await driver.Push("chat-1", 2, "turn.ended", "{\"reason\":\"error\"}");
            await driver.Push("chat-1", 3, "session.ended", "{\"ended_at\":\"2026-10-12T12:00:00+00:00\"}");
            await driver.Settle();
            JsonElement failed = await driver.Read(ReadSendState);
            Assert.True(failed.GetProperty("card").GetBoolean());
            Assert.True(failed.GetProperty("retry").GetBoolean());
            Assert.False(failed.GetProperty("sendShown").GetBoolean());
        });
    }

    [Fact]
    public void SendIsBoundToTheActiveDocumentAndComesBackWhenThatDocumentReturns()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            await AcceptSend(driver, "chat-1");
            foreach (object document in new object[]
            {
                new { path = @"C:\Fictional\FICT-other.SLDPRT", configuration = "Default" },
                new { path = @"C:\Fictional\FICT-drawing.SLDDRW", configuration = "Default" },
            })
            {
                await driver.DocumentChanged(document);
                Assert.True((await driver.Read(ReadSendState)).GetProperty("sendOff").GetBoolean());
                await PressSend(driver);
                Assert.DoesNotContain(await driver.Calls(), IsSend);
                await driver.DocumentChanged(fixture.Waiting.GetProperty("document").Clone());
                Assert.False((await driver.Read(ReadSendState)).GetProperty("sendOff").GetBoolean());
            }
            await PressSend(driver);
            Assert.Single(await driver.Calls(), IsSend);
        });
    }

    [Fact]
    public void WithTwoWaitingReviewsOnlyTheChosenChatIsSentAndItsUsageDropsOnlyItsMark()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            var second = new System.Collections.Generic.Dictionary<string, object?>(driver.Sessions[0]);
            second["chat_id"] = "chat-2";
            driver.Sessions.Add(second);
            driver.InitialRoutes.Add(("GET", "/sessions/chat-2/snapshot", 200, fixture.Waiting.GetRawText()));
        }, async driver =>
        {
            await fixture.Start(driver);
            await driver.Read("document.querySelector(\"[data-chat-id='chat-2']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            await AcceptSend(driver, "chat-2");
            await PressSend(driver);
            JsonElement posted = Assert.Single(await driver.Calls(), IsSend);
            Assert.Equal("/sessions/chat-2/send", posted.GetProperty("path").GetString());
            int seq = fixture.Waiting.GetProperty("last_seq").GetInt32();
            await driver.Push("chat-2", seq + 1, "usage", UsageEvent);
            await driver.Settle();
            JsonElement chips = await driver.Read("return JSON.stringify({ok:true,first:h.text(document,'[data-chat-id=\"chat-1\"]'),second:h.text(document,'[data-chat-id=\"chat-2\"]')});");
            Assert.Contains(" · not sent", chips.GetProperty("first").GetString());
            Assert.DoesNotContain("not sent", chips.GetProperty("second").GetString());
            await driver.Push("chat-2", seq + 2, "turn.ended", "{\"reason\":\"end\"}");
            await driver.Settle();
            driver.Sessions[1].Remove("model_status");
            await RefreshSessions(driver);
            JsonElement confirmed = await driver.Read("return JSON.stringify({ok:true,first:h.text(document,'[data-chat-id=\"chat-1\"]'),second:h.text(document,'[data-chat-id=\"chat-2\"]')});");
            Assert.Contains(" · not sent", confirmed.GetProperty("first").GetString());
            Assert.DoesNotContain("not sent", confirmed.GetProperty("second").GetString());
        });
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void SessionSentPrintsItsSharedEffortPartAndOptionalCountInATranscriptReplay(bool counted)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement failed = fixture.Root.GetProperty("failed_send");
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
            driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, failed.GetRawText()));
        }, async driver =>
        {
            await driver.Click("view-transcript");
            string body = counted ? SentEvent : "{\"provider\":\"openai\",\"model\":\"FICT-model\",\"effort_mapping\":{\"requested\":\"high\",\"provider_param\":\"reasoning_effort\",\"provider_value\":\"high\"},\"estimate\":{\"input_tokens\":null,\"encoding\":\"o200k_base\",\"approximate\":false}}";
            await driver.Push("chat-1", 1, "session.sent", body);
            await driver.Settle();
            string transcript = (await driver.Read(ReadSendState)).GetProperty("transcript").GetString()!;
            Assert.Contains("Sending to openai FICT-model (high -> reasoning_effort=high)", transcript);
            Assert.Equal(counted, transcript.Contains(" - first request 12,905 input tokens"));
            Assert.DoesNotContain("Unreadable", transcript);
        });
    }

    [Fact]
    public void ASecondChipCannotAbandonTheChatWhileItsSendAcceptanceIsHeld()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            var second = new System.Collections.Generic.Dictionary<string, object?>(driver.Sessions[0]);
            second["chat_id"] = "chat-2";
            driver.Sessions.Add(second);
            driver.InitialRoutes.Add(("GET", "/sessions/chat-2/snapshot", 200, fixture.Waiting.GetRawText()));
        }, async driver =>
        {
            // Boot follows the newest chip; choose the chat whose acceptance is held first.
            await driver.Read("document.querySelector(\"[data-chat-id='chat-1']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            await driver.ClearCalls();
            await driver.HoldRoute("POST", "/sessions/chat-1/send", 202, "{}");
            await PressSend(driver);
            Assert.Equal("/sessions/chat-1/send", Assert.Single(await driver.Calls(), IsSend).GetProperty("path").GetString());
            Assert.Equal(1, (await driver.Read("return JSON.stringify({ok:true,held:window.__fetch.held.length});")).GetProperty("held").GetInt32());
            await driver.Read("document.querySelector(\"[data-chat-id='chat-2']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString() == "/sessions/chat-2/snapshot");
            await driver.ReleaseRoute("POST", "/sessions/chat-1/send");
            JsonElement accepted = await driver.Read(ReadSendState);
            Assert.Equal("The review is running.", accepted.GetProperty("status").GetString());
            Assert.False(accepted.GetProperty("stopOff").GetBoolean());
            Assert.False(accepted.GetProperty("sendShown").GetBoolean());
            Assert.Equal("chat-1", driver.Posted("events.open").Last().GetProperty("chat_id").GetString());
        });
    }

    [Fact]
    public void APreselectedAnswerCannotBeAppliedWhileSendAcceptanceIsHeld()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await driver.Read("document.querySelector('#questions [data-action=question-option]').click();return JSON.stringify({ok:true});");
            await driver.Settle();
            Assert.False((await driver.Read("return JSON.stringify({ok:true,off:document.querySelector('#questions [data-action=question-send]').disabled});")).GetProperty("off").GetBoolean());
            await driver.HoldRoute("POST", "/sessions/chat-1/send", 202, "{}");
            await PressSend(driver);
            JsonElement held = await driver.Read(@"
var controls=document.querySelectorAll('#questions button,#questions input');
return JSON.stringify({ok:true,count:controls.length,locked:Array.from(controls).every(function(control){return control.disabled;})});");
            Assert.True(held.GetProperty("count").GetInt32() > 0);
            Assert.True(held.GetProperty("locked").GetBoolean());
            await driver.Read("document.querySelector('#questions [data-action=question-send]').click();return JSON.stringify({ok:true});");
            await driver.Settle();
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString()!.EndsWith("/evidence", StringComparison.Ordinal));
            await driver.ReleaseRoute("POST", "/sessions/chat-1/send");
            Assert.False((await driver.Read(ReadSendState)).GetProperty("stopOff").GetBoolean());
        });
    }

    [Theory]
    [InlineData("NoCredential")]
    [InlineData("TurnRunning")]
    public void ARefusedRetryShowsTheCurrentRefusalInsteadOfThePreviousSendFailure(string errorClass)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement failed = fixture.Root.GetProperty("failed_send");
        string previous = failed.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("failure").GetString()!;
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
            driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, failed.GetRawText()));
        }, async driver =>
        {
            Assert.Contains(previous, (await driver.Read(ReadSendState)).GetProperty("sendText").GetString());
            await driver.Route("POST", "/sessions/chat-1/send", 409, JsonSerializer.Serialize(new
            {
                error_class = errorClass, message = "FICT-current retry refusal", retryable = false,
            }));
            await PressSend(driver);
            JsonElement refused = await driver.Read(ReadSendState);
            Assert.Equal(fixture.Root.GetProperty("labels").GetProperty("errors").GetProperty(errorClass).GetString(), refused.GetProperty("refusal").GetString());
            Assert.Contains("FICT-current retry refusal", refused.GetProperty("sendText").GetString());
            Assert.DoesNotContain(previous, refused.GetProperty("sendText").GetString());
            Assert.True(refused.GetProperty("sendShown").GetBoolean());
            Assert.False(refused.GetProperty("sendOff").GetBoolean());
            Assert.False(refused.GetProperty("card").GetBoolean());
            await driver.HoldRoute("POST", "/sessions/chat-1/send", 202, "{}");
            await PressSend(driver);
            JsonElement next = await driver.Read(ReadSendState);
            Assert.Null(next.GetProperty("refusal").GetString());
            Assert.Contains(previous, next.GetProperty("sendText").GetString());
            await driver.ReleaseRoute("POST", "/sessions/chat-1/send");
        });
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void AGuardFailureRetryReplaysEarlyEventsOnlyAfterItsHeldAcceptance(bool receivesUsage)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement failed = fixture.Root.GetProperty("failed_send");
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await ReachOneErrorGuardFailure(driver, fixture, failed);
            await driver.HoldTimers();
            if (!receivesUsage)
                await driver.Post("events.closed", new { chat_id = "chat-1", reason = "FICT-old stream closed" });
            int opened = driver.Posted("events.open").Length;
            await driver.HoldRoute("POST", "/sessions/chat-1/send", 202, "{}");
            await PressSend(driver);
            Assert.Equal(1, (await driver.Read("return JSON.stringify({ok:true,held:window.__fetch.held.length});")).GetProperty("held").GetInt32());
            await driver.Push("chat-1", 4, "session.sent", SentEvent);
            string firstReply = receivesUsage ? UsageEvent : "{\"error_class\":\"FICTSendError\",\"message\":\"FICT-first request failed\",\"retryable\":true}";
            await driver.Push("chat-1", 5, receivesUsage ? "usage" : "error", firstReply);
            await driver.Post("events.closed", new { chat_id = "chat-1", reason = "FICT-queued close during acceptance" });
            Assert.Equal(0, await driver.RunHeldTimers());
            Assert.Equal(opened, driver.Posted("events.open").Length);
            JsonElement held = await driver.Read(ReadSendState);
            Assert.DoesNotContain("Sending to openai", held.GetProperty("transcript").GetString());
            Assert.False(held.GetProperty("card").GetBoolean());
            await driver.ReleaseRoute("POST", "/sessions/chat-1/send");
            Assert.Equal(opened + 1, driver.Posted("events.open").Length);
            Assert.Equal("3", driver.Posted("events.open").Last().GetProperty("last_event_id").GetString());
            // The host reopens the real event log at the unchanged cursor; deliver that replay.
            await driver.Push("chat-1", 4, "session.sent", SentEvent);
            await driver.Push("chat-1", 5, receivesUsage ? "usage" : "error", firstReply);
            await driver.Settle();
            JsonElement replayed = await driver.Read(ReadSendState);
            Assert.Equal(1, replayed.GetProperty("transcript").GetString()!.Split(new[] { "Sending to openai" }, StringSplitOptions.None).Length - 1);
            if (receivesUsage)
            {
                Assert.False(replayed.GetProperty("sendShown").GetBoolean());
                Assert.DoesNotContain("not sent", replayed.GetProperty("chips").GetString());
                Assert.Equal("Ask a follow-up about any finding", replayed.GetProperty("placeholder").GetString());
                Assert.False(replayed.GetProperty("stopOff").GetBoolean());
                Assert.True(replayed.GetProperty("followupOff").GetBoolean());
                await driver.Push("chat-1", 6, "turn.ended", "{\"reason\":\"end\"}");
                await driver.Settle();
                Assert.False((await driver.Read(ReadSendState)).GetProperty("followupOff").GetBoolean());
            }
            else
            {
                AssertWaitingFailure(replayed, failed, false);
            }
        });
    }

    [Fact]
    public void ARefusedFirstRequestFailureRetryResumesThePriorFinalizationAtItsRetainedCursor()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement failed = fixture.Root.GetProperty("failed_send");
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            JsonElement events = await ReachFirstRequestFailure(driver, fixture, failed);
            int opened = driver.Posted("events.open").Length;
            await driver.HoldRoute("POST", "/sessions/chat-1/send", 409, JsonSerializer.Serialize(new
            {
                error_class = "TurnRunning", message = "FICT-old turn is finalizing", retryable = false,
            }));
            await PressSend(driver);
            await PushFixtureEvent(driver, events[2]);
            await PushFixtureEvent(driver, events[3]);
            await driver.Settle();
            await driver.ReleaseRoute("POST", "/sessions/chat-1/send");
            Assert.Equal(opened + 1, driver.Posted("events.open").Length);
            Assert.Equal(events[1].GetProperty("seq").GetInt32().ToString(System.Globalization.CultureInfo.InvariantCulture), driver.Posted("events.open").Last().GetProperty("last_event_id").GetString());
            await PushFixtureEvent(driver, events[2]);
            await PushFixtureEvent(driver, events[3]);
            await driver.Settle();
            JsonElement ended = await driver.Read(ReadSendState);
            Assert.Contains("The turn ended: error.", ended.GetProperty("transcript").GetString());
            Assert.Equal(1, ended.GetProperty("transcript").GetString()!.Split(new[] { "The turn ended: error." }, StringSplitOptions.None).Length - 1);
            Assert.True(ended.GetProperty("sendShown").GetBoolean());
            Assert.False(ended.GetProperty("sendOff").GetBoolean());
            Assert.True(ended.GetProperty("stopOff").GetBoolean());
            Assert.True(ended.GetProperty("followupOff").GetBoolean());
            Assert.False(ended.GetProperty("card").GetBoolean());
            Assert.Equal(fixture.Root.GetProperty("labels").GetProperty("errors").GetProperty("TurnRunning").GetString(), ended.GetProperty("refusal").GetString());
        });
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void AnAcceptedFirstRequestFailureRetryKeepsItsTurnWhileReplayingThePreviousAttemptEnd(bool receivesUsage)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement failed = fixture.Root.GetProperty("failed_send");
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            JsonElement events = await ReachFirstRequestFailure(driver, fixture, failed);
            await driver.HoldRoute("POST", "/sessions/chat-1/send", 202, "{}");
            await PressSend(driver);
            await PushFixtureEvent(driver, events[2]);
            await PushFixtureEvent(driver, events[3]);
            await driver.Settle();
            await driver.ReleaseRoute("POST", "/sessions/chat-1/send");
            Assert.Equal(events[1].GetProperty("seq").GetInt32().ToString(System.Globalization.CultureInfo.InvariantCulture), driver.Posted("events.open").Last().GetProperty("last_event_id").GetString());
            int closed = driver.Posted("events.close").Length;
            await PushFixtureEvent(driver, events[2]);
            await PushFixtureEvent(driver, events[3]);
            await driver.Settle();
            JsonElement priorEnd = await driver.Read(ReadSendState);
            Assert.Contains("The turn ended: error.", priorEnd.GetProperty("transcript").GetString());
            Assert.Contains("The checks ended at " + events[3].GetProperty("body").GetProperty("ended_at").GetString() + ". Nothing was sent to the model.", priorEnd.GetProperty("transcript").GetString());
            Assert.Equal("The review is running.", priorEnd.GetProperty("status").GetString());
            Assert.False(priorEnd.GetProperty("stopOff").GetBoolean());
            Assert.False(priorEnd.GetProperty("sendShown").GetBoolean());
            Assert.Equal(closed, driver.Posted("events.close").Length);
            int seq = events[3].GetProperty("seq").GetInt32();
            await driver.Push("chat-1", ++seq, "session.sent", JsonSerializer.Serialize(events[0].GetProperty("body")));
            await driver.Push("chat-1", ++seq, receivesUsage ? "usage" : "error", receivesUsage ? UsageEvent : JsonSerializer.Serialize(events[1].GetProperty("body")));
            await driver.Settle();
            JsonElement current = await driver.Read(ReadSendState);
            if (receivesUsage)
            {
                Assert.False(current.GetProperty("sendShown").GetBoolean());
                Assert.DoesNotContain("not sent", current.GetProperty("chips").GetString());
                Assert.False(current.GetProperty("stopOff").GetBoolean());
                Assert.Equal("Ask a follow-up about any finding", current.GetProperty("placeholder").GetString());
            }
            else
            {
                AssertFirstRequestFailure(current, failed, events[1]);
            }
            await driver.Push("chat-1", ++seq, "turn.ended", JsonSerializer.Serialize(events[2].GetProperty("body")));
            await driver.Push("chat-1", ++seq, "session.ended", JsonSerializer.Serialize(events[3].GetProperty("body")));
            await driver.Settle();
            Assert.True((await driver.Read(ReadSendState)).GetProperty("stopOff").GetBoolean());
            Assert.Equal(closed + 1, driver.Posted("events.close").Length);
        });
    }

    /// <summary>The genuine C35 generator event suffix, hash-linked to its unchanged snapshot.
    /// Consume only session.sent and error; its actual terminal pair stays unread for the retry.</summary>
    private static async System.Threading.Tasks.Task<JsonElement> ReachFirstRequestFailure(ReviewPageDriver driver, WaitingReviewFixture fixture, JsonElement failed)
    {
        string folder = System.IO.Path.Combine(AppContext.BaseDirectory, "Fixtures");
        JsonElement source = JsonDocument.Parse(System.IO.File.ReadAllText(System.IO.Path.Combine(folder, "review-send-failure-events.json"))).RootElement.Clone();
        using (var hash = System.Security.Cryptography.SHA256.Create())
        {
            string sha = BitConverter.ToString(hash.ComputeHash(System.IO.File.ReadAllBytes(System.IO.Path.Combine(folder, "review-waiting.json")))).Replace("-", "").ToLowerInvariant();
            Assert.Equal(sha, source.GetProperty("source_fixture_sha256").GetString());
        }
        JsonElement events = source.GetProperty("events");
        Assert.Equal(new[] { "session.sent", "error", "turn.ended", "session.ended" }, events.EnumerateArray().Select(item => item.GetProperty("type").GetString()));
        Assert.Equal(fixture.Waiting.GetProperty("last_seq").GetInt32() + 1, events[0].GetProperty("seq").GetInt32());
        Assert.Equal(failed.GetProperty("last_seq").GetInt32(), events[3].GetProperty("seq").GetInt32());
        await AcceptSend(driver, "chat-1");
        await PressSend(driver);
        await driver.RouteAttention("chat-1", failed.GetProperty("ranking").GetRawText());
        await PushFixtureEvent(driver, events[0]);
        await PushFixtureEvent(driver, events[1]);
        await driver.Settle();
        AssertFirstRequestFailure(await driver.Read(ReadSendState), failed, events[1]);
        return events;
    }

    private static System.Threading.Tasks.Task PushFixtureEvent(ReviewPageDriver driver, JsonElement item) =>
        driver.Push("chat-1", item.GetProperty("seq").GetInt32(), item.GetProperty("type").GetString()!, JsonSerializer.Serialize(item.GetProperty("body")));

    private static void AssertFirstRequestFailure(JsonElement state, JsonElement failed, JsonElement error)
    {
        Assert.True(state.GetProperty("sendShown").GetBoolean(), state.GetRawText());
        Assert.False(state.GetProperty("sendOff").GetBoolean());
        Assert.True(state.GetProperty("stopOff").GetBoolean());
        Assert.True(state.GetProperty("followupOff").GetBoolean());
        Assert.False(state.GetProperty("card").GetBoolean());
        Assert.False(state.GetProperty("retry").GetBoolean());
        Assert.Contains(failed.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("failure").GetString()!, state.GetProperty("sendText").GetString());
        JsonElement body = error.GetProperty("body");
        Assert.Contains(body.GetProperty("error_class").GetString() + ": " + body.GetProperty("message").GetString(), state.GetProperty("transcript").GetString());
    }

    private static async System.Threading.Tasks.Task ReachOneErrorGuardFailure(ReviewPageDriver driver, WaitingReviewFixture fixture, JsonElement failed)
    {
        await fixture.Start(driver);
        await AcceptSend(driver, "chat-1");
        await PressSend(driver);
        await driver.RouteAttention("chat-1", failed.GetProperty("ranking").GetRawText());
        await driver.Push("chat-1", 3, "error", "{\"error_class\":\"FICTSendError\",\"message\":\"FICT-first request failed\",\"retryable\":true}");
        await driver.Settle();
        AssertWaitingFailure(await driver.Read(ReadSendState), failed, false);
    }

    private static async System.Threading.Tasks.Task RefreshSessions(ReviewPageDriver driver)
    {
        int requests = driver.Posted("sessions.list").Length;
        await driver.Click("save-settings"); // settings.saved asks for init, then the actual host list.
        await driver.Until(() => driver.Posted("sessions.list").Length > requests, "asked for sessions again");
        await driver.Settle();
    }

    private static async System.Threading.Tasks.Task PressSend(ReviewPageDriver driver)
    {
        await driver.Read("var send=document.querySelector('#send [data-action=send]');if(send)send.click();return JSON.stringify({ok:true});");
        await driver.Settle();
    }

    private static System.Threading.Tasks.Task AcceptSend(ReviewPageDriver driver, string chatId) =>
        driver.Route("POST", "/sessions/" + chatId + "/send", 202, "{}");

    private static bool IsSend(JsonElement call) => call.GetProperty("path").GetString()!.EndsWith("/send", StringComparison.Ordinal);

    private static void AssertWaitingFailure(JsonElement state, JsonElement failedSnapshot, bool streamedText)
    {
        Assert.False(state.GetProperty("card").GetBoolean());
        Assert.False(state.GetProperty("retry").GetBoolean());
        Assert.True(state.GetProperty("sendShown").GetBoolean());
        Assert.False(state.GetProperty("sendOff").GetBoolean());
        Assert.True(state.GetProperty("stopOff").GetBoolean());
        Assert.True(state.GetProperty("followupOff").GetBoolean());
        Assert.Equal("Checked by code. Not sent to the model.", state.GetProperty("status").GetString());
        Assert.Contains(failedSnapshot.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("failure").GetString()!, state.GetProperty("sendText").GetString());
        if (streamedText) Assert.Contains("FICT-text before failed round", state.GetProperty("transcript").GetString());
        else Assert.DoesNotContain("FICT-text before failed round", state.GetProperty("transcript").GetString());
        Assert.Contains("FICTSendError: FICT-first request failed", state.GetProperty("transcript").GetString());
    }

    private const string SentEvent = "{\"provider\":\"openai\",\"model\":\"FICT-model\",\"effort_mapping\":{\"requested\":\"high\",\"provider_param\":\"reasoning_effort\",\"provider_value\":\"high\"},\"estimate\":{\"input_tokens\":12905,\"encoding\":\"o200k_base\",\"approximate\":false}}";
    private const string UsageEvent = "{\"input_tokens\":12905,\"output_tokens\":3,\"cached_input_tokens\":0,\"elapsed_s\":1}";

    private const string ReadSendState = @"
var send=document.getElementById('send');var button=send.querySelector('[data-action=send]');
return JSON.stringify({ok:true,status:document.getElementById('results-state').textContent,
 stopOff:document.getElementById('stop-turn').disabled,followupOff:document.getElementById('followup-text').disabled,
 placeholder:document.getElementById('followup-text').placeholder,sendShown:h.rendered(send),sendOff:!button||button.disabled,
 sendText:send.textContent,refusal:h.text(send,'.plain-error-text'),injected:h.injected(send),
 transcript:document.getElementById('transcript').textContent,chips:document.getElementById('review-chips').textContent,
 card:!!document.querySelector('#errors .card.error'),retry:!!document.querySelector('#errors [data-action=retry]')});";

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
