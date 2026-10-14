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

    [Fact]
    public void AWaitingReviewOffersApplyAnswersWithTheBackendsResumeSentence()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            JsonElement questions = await driver.Read(ReadApplyQuestions);
            Assert.Equal("Apply answers", questions.GetProperty("label").GetString());
            Assert.Equal(fixture.Waiting.GetProperty("ranking").GetProperty("summary").GetProperty("resume_text").GetString(), questions.GetProperty("resume").GetString());
            Assert.False(questions.GetProperty("locked").GetBoolean());
        });
    }

    [Fact]
    public void ApplyingAnswersKeepsWaitingStopOffAndSendLockedThroughItsStreamSettle()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyResponses();
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await ChooseAllBought(driver);
            await driver.HoldRoute("POST", "/sessions/chat-1/evidence", 202, replies.GetProperty("accepted").GetRawText());
            await driver.RouteAttention("chat-1", replies.GetProperty("attention_applied").GetRawText());
            await PressApply(driver);
            JsonElement posted = Assert.Single(await driver.Calls(), IsEvidencePost);
            Assert.Equal("Bearer " + ReviewPageDriver.Token, posted.GetProperty("authorization").GetString());
            JsonElement answer = Assert.Single(JsonDocument.Parse(posted.GetProperty("body").GetString()!).RootElement.GetProperty("answers").EnumerateArray());
            Assert.Equal(replies.GetProperty("waiting").GetProperty("ranking").GetProperty("summary").GetProperty("questions").GetProperty("items")[0].GetProperty("id").GetString(), answer.GetProperty("request_id").GetString());
            Assert.Equal("All bought", answer.GetProperty("answer").GetString());
            await AssertWaitingApplyLocked(driver);
            await PressApply(driver);
            await PressSend(driver);
            Assert.Single(await driver.Calls(), IsEvidencePost);
            Assert.DoesNotContain(await driver.Calls(), IsSend);
            await driver.ReleaseRoute("POST", "/sessions/chat-1/evidence");
            await AssertWaitingApplyLocked(driver);
            Assert.Equal(replies.GetProperty("waiting").GetProperty("last_seq").GetInt32().ToString(System.Globalization.CultureInfo.InvariantCulture), driver.Posted("events.open").Last().GetProperty("last_event_id").GetString());
            await PushFixtureEvent(driver, replies.GetProperty("session_ended"));
            await driver.Settle();
            await AssertWaitingApplySettled(driver, replies);
            JsonElement choice = await driver.Read("var option=document.querySelectorAll('#questions [data-action=question-option]')[1];option.click();return JSON.stringify({ok:true,text:option.textContent,pressed:document.querySelectorAll('#questions [data-action=question-option]')[1].getAttribute('aria-pressed'),applyOff:document.querySelector('#questions [data-action=question-send]').disabled});");
            Assert.Equal(replies.GetProperty("applied").GetProperty("ranking").GetProperty("summary").GetProperty("questions").GetProperty("items")[0].GetProperty("options")[1].GetString(), choice.GetProperty("text").GetString());
            Assert.Equal("true", choice.GetProperty("pressed").GetString());
            Assert.False(choice.GetProperty("applyOff").GetBoolean());
        });
    }

    [Fact]
    public void ReloadingDuringAnApplyRestoresTheGenuineWaitingStateWithItsControlsLocked()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyResponses();
        JsonElement applying = replies.GetProperty("applying");
        Assert.Equal("running", applying.GetProperty("chat_state").GetString());
        Assert.False(applying.TryGetProperty("send_in_flight", out _));
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await BeginWaitingApply(driver, replies);
            driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
            driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, applying.GetRawText()));
            await driver.Reload();
            await AssertWaitingApplyLocked(driver);
            Assert.Equal("Apply answers", (await driver.Read(ReadApplyQuestions)).GetProperty("label").GetString());
            Assert.Equal(applying.GetProperty("last_seq").GetInt32().ToString(System.Globalization.CultureInfo.InvariantCulture), driver.Posted("events.open").Last().GetProperty("last_event_id").GetString());
            await driver.RouteAttention("chat-1", replies.GetProperty("attention_applied").GetRawText());
            await PushFixtureEvent(driver, replies.GetProperty("session_ended"));
            await driver.Settle();
            await AssertWaitingApplySettled(driver, replies);
        });
    }

    [Fact]
    public void SendStaysLockedUntilTheFinalApplyAttentionHasArrived()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyResponses();
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await BeginWaitingApply(driver, replies);
            int withdrawal = FirstApplyWithdrawal(replies);
            await driver.RouteAttention("chat-1", replies.GetProperty("attention_applying").GetRawText());
            await PlayApplyEvents(driver, replies, 0, withdrawal);
            await driver.HoldRoute("GET", "/sessions/chat-1/attention", 200, replies.GetProperty("attention_applied").GetRawText());
            await PlayApplyEvents(driver, replies, withdrawal, int.MaxValue);
            JsonElement settling = await driver.Read(ReadSendState);
            Assert.True(settling.GetProperty("sendOff").GetBoolean(), settling.GetRawText());
            Assert.True((await driver.Read(ReadApplyQuestions)).GetProperty("locked").GetBoolean());
            await PressSend(driver);
            Assert.DoesNotContain(await driver.Calls(), IsSend);
            await driver.ReleaseRoute("GET", "/sessions/chat-1/attention", newest: true);
            await AssertWaitingApplySettled(driver, replies);
        });
    }

    [Fact]
    public void AnOlderApplyAttentionCannotRestoreThePreSettleSizeAfterTheFinalSummary()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyResponses();
        JsonElement before = replies.GetProperty("attention_applying").GetProperty("summary");
        JsonElement after = replies.GetProperty("attention_applied").GetProperty("summary");
        Assert.NotEqual(before.GetProperty("send").GetProperty("input_tokens").GetInt32(), after.GetProperty("send").GetProperty("input_tokens").GetInt32());
        Assert.NotEqual(before.GetProperty("bought_parts").GetProperty("text").GetString(), after.GetProperty("bought_parts").GetProperty("text").GetString());
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await BeginWaitingApply(driver, replies);
            int withdrawal = FirstApplyWithdrawal(replies);
            await driver.HoldRoute("GET", "/sessions/chat-1/attention", 200, replies.GetProperty("attention_applying").GetRawText());
            await PlayApplyEvents(driver, replies, 0, withdrawal);
            Assert.Equal(1, (await driver.Read("return JSON.stringify({ok:true,held:window.__fetch.held.length});")).GetProperty("held").GetInt32());
            // That first GET read the actual first-withdrawal boundary. The backend then
            // completes while the remaining real stream frames are still being delivered.
            await driver.HoldRoute("GET", "/sessions/chat-1/attention", 200, replies.GetProperty("attention_applied").GetRawText());
            await PlayApplyEvents(driver, replies, withdrawal, int.MaxValue);
            await driver.ReleaseRoute("GET", "/sessions/chat-1/attention", newest: true);
            await AssertWaitingApplySettled(driver, replies);
            await driver.ReleaseRoute("GET", "/sessions/chat-1/attention");
            await AssertWaitingApplySettled(driver, replies);
            string summary = (await driver.Read("return JSON.stringify({ok:true,text:document.getElementById('summary').textContent});")).GetProperty("text").GetString()!;
            Assert.Contains(after.GetProperty("bought_parts").GetProperty("text").GetString()!, summary);
            Assert.DoesNotContain(before.GetProperty("bought_parts").GetProperty("text").GetString()!, summary);
        });
    }

    [Theory]
    [InlineData("before_save", false)]
    [InlineData("after_save", false)]
    [InlineData("before_save", true)]
    [InlineData("after_save", true)]
    public void AFailedWaitingApplyRestoresItsActualDiskRecordWithoutAnErrorCard(string failurePoint, bool reload)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyFailures().GetProperty(failurePoint);
        Assert.Equal("restored", replies.GetProperty("restored").GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("state").GetString());
        Assert.Equal(JsonValueKind.Null, replies.GetProperty("restored").GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("input_tokens").ValueKind);
        Assert.DoesNotContain(replies.GetProperty("apply_events").EnumerateArray(), item => item.GetProperty("type").GetString() == "turn.ended" || item.GetProperty("type").GetString() == "session.ended");
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await BeginWaitingApply(driver, replies);
            int from = replies.GetProperty("waiting").GetProperty("last_seq").GetInt32();
            if (reload)
            {
                JsonElement applying = replies.GetProperty("applying");
                driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
                driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, applying.GetRawText()));
                await driver.Reload();
                await AssertWaitingApplyLocked(driver);
                from = applying.GetProperty("last_seq").GetInt32();
            }
            string reviewPath = "/reviews/" + replies.GetProperty("waiting").GetProperty("run_id").GetString();
            await driver.Route("GET", reviewPath, 200, replies.GetProperty("restored").GetRawText());
            await driver.RouteAttention("chat-1", replies.GetProperty("attention_failed").GetRawText());
            int opens = driver.Posted("events.open").Length;
            int closes = driver.Posted("events.close").Length;
            await PlayApplyEvents(driver, replies, from, int.MaxValue);
            await AssertFailedApplyRestored(driver, fixture, replies);
            Assert.Single(await driver.Calls(), call => call.GetProperty("method").GetString() == "GET" && call.GetProperty("path").GetString() == reviewPath);
            Assert.Equal(opens, driver.Posted("events.open").Length);
            Assert.Equal(closes + 1, driver.Posted("events.close").Length);
            int calls = (await driver.Calls()).Length;
            await PressApply(driver);
            await PressSend(driver);
            Assert.Equal(calls, (await driver.Calls()).Length);
        });
    }

    [Fact]
    public void AnOlderApplyAttentionCannotReplaceTheRecordRestoredAfterItsFailure()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyFailures().GetProperty("before_save");
        int withdrawal = FirstApplyWithdrawal(replies);
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await BeginWaitingApply(driver, replies);
            await driver.HoldRoute("GET", "/sessions/chat-1/attention", 200, replies.GetProperty("attention_at_withdrawal").GetRawText());
            await PlayApplyEvents(driver, replies, 0, withdrawal);
            Assert.Equal(1, (await driver.Read("return JSON.stringify({ok:true,held:window.__fetch.held.length});")).GetProperty("held").GetInt32());
            await driver.RouteAttention("chat-1", replies.GetProperty("attention_failed").GetRawText());
            await driver.Route("GET", "/reviews/" + replies.GetProperty("waiting").GetProperty("run_id").GetString(), 200, replies.GetProperty("restored").GetRawText());
            await PlayApplyEvents(driver, replies, withdrawal, int.MaxValue);
            await AssertFailedApplyRestored(driver, fixture, replies);
            await driver.ReleaseRoute("GET", "/sessions/chat-1/attention");
            await AssertFailedApplyRestored(driver, fixture, replies);
        });
    }

    [Fact]
    public void ReopeningAFailedApplyUsesTheDiskRecordAndKeepsItsLocalFailure()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyFailures().GetProperty("before_save");
        ReviewPageDriver.Run(driver =>
        {
            ConfigureWaitingApply(driver, fixture, replies);
            var second = new System.Collections.Generic.Dictionary<string, object?>(driver.Sessions[0]);
            second["chat_id"] = "chat-2";
            driver.Sessions.Insert(0, second); // The failed review stays the newest matching chip.
            driver.InitialRoutes.Add(("GET", "/sessions/chat-2/snapshot", 200, fixture.Waiting.GetRawText()));
        }, async driver =>
        {
            await BeginWaitingApply(driver, replies);
            string reviewPath = "/reviews/" + replies.GetProperty("waiting").GetProperty("run_id").GetString();
            await driver.Route("GET", reviewPath, 200, replies.GetProperty("restored").GetRawText());
            await driver.RouteAttention("chat-1", replies.GetProperty("attention_failed").GetRawText());
            await PlayApplyEvents(driver, replies, replies.GetProperty("waiting").GetProperty("last_seq").GetInt32(), int.MaxValue);
            await AssertFailedApplyRestored(driver, fixture, replies);
            await driver.Read(ReviewPageSessionsTests.Chip("chat-2"));
            await driver.Settle();
            await driver.Route("GET", "/sessions/chat-1/snapshot", 200, replies.GetProperty("failed").GetRawText());
            int snapshots = (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == "/sessions/chat-1/snapshot");
            await driver.Read(ReviewPageSessionsTests.Chip("chat-1"));
            await driver.Settle();
            await AssertFailedApplyRestored(driver, fixture, replies);
            Assert.Equal(snapshots, (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == "/sessions/chat-1/snapshot"));
            Assert.Equal(2, (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == reviewPath));
        });
    }

    [Fact]
    public void ReloadingAnAlreadyFailedApplyReadsTheActualDiskRecord()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyFailures().GetProperty("before_save");
        JsonElement failed = replies.GetProperty("failed");
        Assert.Equal("failed", failed.GetProperty("chat_state").GetString());
        Assert.Equal(replies.GetProperty("error").GetProperty("seq").GetInt32(), failed.GetProperty("last_seq").GetInt32());
        Assert.False(failed.TryGetProperty("send_in_flight", out _));
        string reviewPath = "/reviews/" + replies.GetProperty("waiting").GetProperty("run_id").GetString();
        ReviewPageDriver.Run(driver =>
        {
            ConfigureWaitingApply(driver, fixture, replies);
            driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
            driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, failed.GetRawText()));
            driver.InitialRoutes.Add(("GET", reviewPath, 200, replies.GetProperty("restored").GetRawText()));
        }, async driver =>
        {
            // There was no error event on this page. Its fresh snapshot is the only
            // proof that this live cache failed, so no local error is manufactured.
            await driver.Reload();
            await AssertFailedApplyRestored(driver, fixture, replies, showFailure: false);
            Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == "/sessions/chat-1/snapshot");
            Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == reviewPath);
            Assert.Empty(driver.Posted("events.open"));
        });
    }

    [Fact]
    public void AnUnavailableFinalApplyAttentionKeepsSendLockedUntilAFreshSnapshot()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyResponses();
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await BeginWaitingApply(driver, replies);
            await driver.Route("GET", "/sessions/chat-1/attention", 503,
                "{\"error_class\":\"BackendUnavailable\",\"message\":\"FICT-attention temporarily unavailable\",\"retryable\":true}");
            await PushFixtureEvent(driver, replies.GetProperty("session_ended"));
            await driver.Settle();
            await AssertWaitingApplyLocked(driver);
            await PressSend(driver);
            Assert.DoesNotContain(await driver.Calls(), IsSend);
            Assert.False((await driver.Read(ReadSendState)).GetProperty("card").GetBoolean());
            driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
            driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, replies.GetProperty("applied").GetRawText()));
            await driver.Reload();
            await AssertWaitingApplySettled(driver, replies);
        });
    }

    [Fact]
    public void FollowUpStaysOffWhileAFailedApplyDiskRestoreIsPending()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyFailures().GetProperty("before_save");
        ReviewPageDriver.Run(driver => ConfigureWaitingApply(driver, fixture, replies), async driver =>
        {
            await BeginWaitingApply(driver, replies);
            string reviewPath = "/reviews/" + replies.GetProperty("waiting").GetProperty("run_id").GetString();
            await driver.HoldRoute("GET", reviewPath, 200, replies.GetProperty("restored").GetRawText());
            await driver.RouteAttention("chat-1", replies.GetProperty("attention_failed").GetRawText());
            await PlayApplyEvents(driver, replies, replies.GetProperty("waiting").GetProperty("last_seq").GetInt32(), int.MaxValue);
            Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == reviewPath);
            await AssertFailedRestorePending(driver);
            await driver.ReleaseRoute("GET", reviewPath);
            await AssertFailedApplyRestored(driver, fixture, replies);
        });
    }

    [Fact]
    public void FollowUpStaysOffWhileAFreshFailedSnapshotRestoresFromDisk()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read();
        JsonElement replies = ReadWaitingApplyFailures().GetProperty("before_save");
        ReviewPageDriver.Run(driver =>
        {
            ConfigureWaitingApply(driver, fixture, replies);
            var second = new System.Collections.Generic.Dictionary<string, object?>(driver.Sessions[0]);
            second["chat_id"] = "chat-2";
            second["run_id"] = fixture.Waiting.GetProperty("run_id").GetString();
            driver.Sessions.Insert(0, second);
            driver.InitialRoutes.Add(("GET", "/sessions/chat-2/snapshot", 200, fixture.Waiting.GetRawText()));
        }, async driver =>
        {
            // Only the failed snapshot reveals this apply's outcome on this page.
            await driver.Read(ReviewPageSessionsTests.Chip("chat-2"));
            await driver.Settle();
            string reviewPath = "/reviews/" + replies.GetProperty("waiting").GetProperty("run_id").GetString();
            await driver.HoldRoute("GET", "/sessions/chat-1/snapshot", 200, replies.GetProperty("failed").GetRawText());
            await driver.HoldRoute("GET", reviewPath, 200, replies.GetProperty("restored").GetRawText());
            await driver.Read(ReviewPageSessionsTests.Chip("chat-1"));
            await driver.Settle();
            await driver.ReleaseRoute("GET", "/sessions/chat-1/snapshot");
            Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == reviewPath);
            await AssertFailedRestorePending(driver);
            await driver.ReleaseRoute("GET", reviewPath);
            await AssertFailedApplyRestored(driver, fixture, replies, showFailure: false);
        });
    }

    private static async System.Threading.Tasks.Task AssertFailedRestorePending(ReviewPageDriver driver)
    {
        JsonElement waiting = await driver.Read(ReadSendState);
        Assert.True(waiting.GetProperty("followupOff").GetBoolean(), waiting.GetRawText());
        Assert.Equal("Not sent to the model yet: press Send to model first", waiting.GetProperty("placeholder").GetString());
        Assert.Equal("Checked by code. Not sent to the model.", waiting.GetProperty("status").GetString());
        Assert.True(waiting.GetProperty("stopOff").GetBoolean());
        Assert.False(waiting.GetProperty("card").GetBoolean());
        await driver.Read("var box=document.getElementById('followup-text');box.value='FICT-follow-up during restore';document.getElementById('followup').dispatchEvent(new Event('submit',{cancelable:true}));return JSON.stringify({ok:true});");
        await driver.Settle();
        Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString()!.EndsWith("/messages", StringComparison.Ordinal));
        Assert.False((await driver.Read(ReadSendState)).GetProperty("card").GetBoolean());
    }

    private static JsonElement ReadWaitingApplyFailures() => JsonDocument.Parse(System.IO.File.ReadAllText(
        System.IO.Path.Combine(AppContext.BaseDirectory, "Fixtures", "review-waiting-apply-failure.json"))).RootElement.Clone();

    private static async System.Threading.Tasks.Task AssertFailedApplyRestored(ReviewPageDriver driver, WaitingReviewFixture fixture, JsonElement replies, bool showFailure = true)
    {
        JsonElement disk = replies.GetProperty("restored");
        JsonElement error = replies.GetProperty("error").GetProperty("body");
        JsonElement state = await driver.Read(ReadSendState);
        Assert.False(state.GetProperty("card").GetBoolean(), state.GetRawText());
        Assert.False(state.GetProperty("retry").GetBoolean());
        Assert.True(state.GetProperty("stopOff").GetBoolean());
        Assert.True(state.GetProperty("followupOff").GetBoolean());
        Assert.True(state.GetProperty("sendShown").GetBoolean());
        Assert.True(state.GetProperty("sendOff").GetBoolean()); // US4 owns the read-only recheck action.
        Assert.Equal("Checked by code. Not sent to the model.", state.GetProperty("status").GetString());
        Assert.Contains(disk.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("text").GetString()!, state.GetProperty("sendText").GetString());
        if (showFailure)
        {
            Assert.Contains(error.GetProperty("error_class").GetString()!, state.GetProperty("sendText").GetString());
            Assert.Contains(error.GetProperty("message").GetString()!, state.GetProperty("sendText").GetString());
            JsonElement labels = fixture.Root.GetProperty("labels").GetProperty("errors");
            string errorClass = error.GetProperty("error_class").GetString()!;
            string label = labels.TryGetProperty(errorClass, out JsonElement words) ? words.GetString()! : error.GetProperty("message").GetString()!;
            Assert.Equal(label, state.GetProperty("refusal").GetString());
        }
        JsonElement record = await driver.Read(ReadRecoveredApply);
        Assert.True(record.GetProperty("readOnly").GetBoolean());
        Assert.Equal(disk.GetProperty("read_only_reason").GetString(), record.GetProperty("reason").GetString());
        Assert.True(record.GetProperty("decisionsLocked").GetBoolean());
        Assert.True((await driver.Read(ReadApplyQuestions)).GetProperty("locked").GetBoolean());
        Assert.Contains(disk.GetProperty("ranking").GetProperty("summary").GetProperty("questions").GetProperty("text").GetString()!, record.GetProperty("summary").GetString());
        Assert.Contains(disk.GetProperty("ranking").GetProperty("summary").GetProperty("bought_parts").GetProperty("text").GetString()!, record.GetProperty("summary").GetString());
        Assert.Equal(disk.GetProperty("findings").EnumerateArray().Select(item => item.GetProperty("id").GetString()).OrderBy(id => id),
            record.GetProperty("findings").EnumerateArray().Select(item => item.GetString()).OrderBy(id => id));
        Assert.Equal(0, record.GetProperty("selectedDrafts").GetInt32());
        if (showFailure) Assert.False(record.GetProperty("foldOpen").GetBoolean());
        else Assert.Equal(JsonValueKind.Null, record.GetProperty("foldOpen").ValueKind);
        Assert.False((await driver.Read(ReadBox)).GetProperty("disabled").GetBoolean());
    }

    private const string ReadRecoveredApply = @"
var reason=document.getElementById('read-only');var decisions=document.querySelectorAll('#results .card.finding [data-action=accept],#results .card.finding [data-action=reject],#results .card.finding [data-action=defer],#results .card.finding input.note');
var fold=document.querySelector('#send .error-fold');
return JSON.stringify({ok:true,readOnly:h.rendered(reason),reason:reason.textContent,summary:document.getElementById('summary').textContent,
 decisionsLocked:Array.from(decisions).every(function(control){return control.disabled;}),
 findings:h.attrs(document.getElementById('results'),'.card.finding','data-finding-id'),
 selectedDrafts:document.querySelectorAll('#questions [aria-pressed=true]').length,foldOpen:fold?fold.open:null});";

    private static JsonElement ReadWaitingApplyResponses() => JsonDocument.Parse(System.IO.File.ReadAllText(
        System.IO.Path.Combine(AppContext.BaseDirectory, "Fixtures", "review-waiting-apply.json"))).RootElement.Clone();

    private static void ConfigureWaitingApply(ReviewPageDriver driver, WaitingReviewFixture fixture, JsonElement replies)
    {
        fixture.Configure(driver);
        JsonElement waiting = replies.GetProperty("waiting");
        driver.Sessions[0]["run_id"] = waiting.GetProperty("run_id").GetString();
        driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
        driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, waiting.GetRawText()));
    }

    private static async System.Threading.Tasks.Task ChooseAllBought(ReviewPageDriver driver)
    {
        JsonElement chosen = await driver.Read("var option=document.querySelector('#questions [data-action=question-option]');option.click();return JSON.stringify({ok:true,text:option.textContent});");
        Assert.Equal("All bought", chosen.GetProperty("text").GetString());
        await driver.Settle();
    }

    private static async System.Threading.Tasks.Task BeginWaitingApply(ReviewPageDriver driver, JsonElement replies)
    {
        await ChooseAllBought(driver);
        await driver.Route("POST", "/sessions/chat-1/evidence", 202, replies.GetProperty("accepted").GetRawText());
        await PressApply(driver);
        Assert.Single(await driver.Calls(), IsEvidencePost);
    }

    private static async System.Threading.Tasks.Task PressApply(ReviewPageDriver driver)
    {
        await driver.Read("document.querySelector('#questions [data-action=question-send]').click();return JSON.stringify({ok:true});");
        await driver.Settle();
    }

    private static bool IsEvidencePost(JsonElement call) => call.GetProperty("method").GetString() == "POST"
        && call.GetProperty("path").GetString() == "/sessions/chat-1/evidence";

    private static int FirstApplyWithdrawal(JsonElement replies)
    {
        int seq = replies.GetProperty("apply_events").EnumerateArray().First(item => item.GetProperty("type").GetString() == "finding.withdrawn").GetProperty("seq").GetInt32();
        Assert.Equal(seq, replies.GetProperty("snapshot_at_withdrawal").GetProperty("last_seq").GetInt32());
        return seq;
    }

    private static async System.Threading.Tasks.Task PlayApplyEvents(ReviewPageDriver driver, JsonElement replies, int after, int through)
    {
        foreach (JsonElement item in replies.GetProperty("apply_events").EnumerateArray())
        {
            int seq = item.GetProperty("seq").GetInt32();
            if (seq > after && seq <= through) await PushFixtureEvent(driver, item);
        }
        await driver.Settle();
    }

    private static async System.Threading.Tasks.Task AssertWaitingApplyLocked(ReviewPageDriver driver)
    {
        JsonElement state = await driver.Read(ReadSendState);
        Assert.Equal("Checked by code. Not sent to the model.", state.GetProperty("status").GetString());
        Assert.True(state.GetProperty("stopOff").GetBoolean());
        Assert.True(state.GetProperty("followupOff").GetBoolean());
        Assert.True(state.GetProperty("sendShown").GetBoolean());
        Assert.True(state.GetProperty("sendOff").GetBoolean());
        JsonElement panel = await driver.Read(ReadApplyQuestions);
        Assert.True(panel.GetProperty("controls").GetInt32() > 0);
        Assert.True(panel.GetProperty("locked").GetBoolean());
        Assert.False((await driver.Read(ReadBox)).GetProperty("disabled").GetBoolean());
    }

    private static async System.Threading.Tasks.Task AssertWaitingApplySettled(ReviewPageDriver driver, JsonElement replies)
    {
        JsonElement state = await driver.Read(ReadSendState);
        Assert.Equal("Checked by code. Not sent to the model.", state.GetProperty("status").GetString());
        Assert.True(state.GetProperty("stopOff").GetBoolean());
        Assert.True(state.GetProperty("followupOff").GetBoolean());
        Assert.False(state.GetProperty("sendOff").GetBoolean());
        Assert.Contains(replies.GetProperty("attention_applied").GetProperty("summary").GetProperty("send").GetProperty("text").GetString()!, state.GetProperty("sendText").GetString());
        Assert.False((await driver.Read(ReadApplyQuestions)).GetProperty("locked").GetBoolean());
    }

    private const string ReadApplyQuestions = @"
var panel=document.getElementById('questions');var controls=panel.querySelectorAll('button,input');
return JSON.stringify({ok:true,label:h.text(panel,'[data-action=question-send]'),resume:h.text(panel,'.question-resume'),
 controls:controls.length,locked:Array.from(controls).every(function(control){return control.disabled;})});";

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
