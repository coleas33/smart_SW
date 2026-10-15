using System;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

public sealed class EngineeringContextPaneTests
{
    [Fact]
    public void ExistingReviewPageOffersSavedEvidenceContextWithoutStartingReview()
    {
        int contextPreparations = 0;
        int reviewStarts = 0;
        OffscreenReviewPage.WithPage(page =>
        {
            page.WebMessageReceived += (_, args) =>
            {
                JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                string? type = message.GetProperty("type").GetString();
                string? id = message.GetProperty("id").GetString();
                if (type == "ready")
                    page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type = "init", id, payload = new
                    {
                        providers = new[] { "openai" }, backend = (object?)null, token = (string?)null,
                        document = new { path = @"C:\Fictional\bracket.SLDASM", configuration = "Default" },
                        engineering_context = true, key_source = "none",
                        settings = new { provider = "openai", model = "test", effort = "high" },
                    } }));
                if (type == "context.prepare") contextPreparations++;
                if (type == "review.start" || type == "context.review") reviewStarts++;
            };
        }, async page =>
        {
            await OffscreenReviewPage.Settled(page);
            bool present = JsonDocument.Parse(await page.ExecuteScriptAsync(
                "!!document.getElementById('engineering-context')")).RootElement.GetBoolean();
            Assert.True(present);
            await page.ExecuteScriptAsync("document.getElementById('context-prepare').click()");
            await OffscreenReviewPage.Settled(page);
            Assert.Equal(0, reviewStarts);
        });
        // A backend is needed before preparing; ordinary Review is never invoked by opening the panel.
        Assert.Equal(0, contextPreparations);
    }

    private const string RunId = "saved-context-run";
    private const string ContextId = "00000000-0000-0000-0000-000000000016";
    private static readonly string PackageSha = new string('a', 64);
    private static readonly string Head = new string('b', 64);
    private static readonly string RecordDigest = new string('c', 64);
    private static readonly string DependencyDigest = new string('d', 64);
    private static string Endpoint => "/engineering-context/" + RunId;
    private const string Hostile = "<img src=x onerror=alert(1)>Fictional bracket";

    [Theory]
    [InlineData("", true)]
    [InlineData("0", false)]
    public void SavingAForceKeepsUnknownSeparateFromZero(string magnitude, bool unknown)
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot()), async driver =>
        {
            await Prepare(driver);
            await driver.Page.ExecuteScriptAsync(
                "document.getElementById('context-kind').value='applied_force';"
                + "document.getElementById('context-kind').dispatchEvent(new Event('change'));"
                + "document.getElementById('context-target').value='1';"
                + "document.getElementById('context-id').value='force:1';"
                + "document.getElementById('context-magnitude').value=" + JsonSerializer.Serialize(magnitude) + ";"
                + "document.getElementById('context-unknown').value='Operating load not yet known';"
                + "document.getElementById('context-dx').value='1';"
                + "document.getElementById('context-dy').value='0';"
                + "document.getElementById('context-dz').value='0';"
                + "document.getElementById('context-save').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            JsonElement request = Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/force");
            JsonElement body = RequestBody(request);
            Assert.Equal(Head, body.GetProperty("expected_head").GetString());
            Assert.Equal("cmp:0001", body.GetProperty("entity_id").GetString());
            if (unknown)
            {
                Assert.Equal(JsonValueKind.Null, body.GetProperty("magnitude").ValueKind);
                Assert.Equal("Operating load not yet known", body.GetProperty("unknown_reason").GetString());
            }
            else Assert.Equal(0, body.GetProperty("magnitude").GetDouble());
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/confirm");
            Assert.Empty(driver.Posted("context.review"));
            Assert.Empty(driver.Posted("review.start"));
        });
    }

    [Fact]
    public void RequirementPreviewIsLiteralAndConfirmationPinsTheDisplayedRevision()
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot(Requirement())), async driver =>
        {
            await Prepare(driver);
            Assert.True(await Bool(driver.Page, "document.getElementById('context-records').textContent.indexOf('<img src=x')>=0"));
            Assert.False(await Bool(driver.Page, "!!document.querySelector('#engineering-context img, #engineering-context script')"));
            await driver.Page.ExecuteScriptAsync("document.querySelector('[data-action=context-confirm]').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/confirm");
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-actor').value='fictional-engineer';document.querySelector('[data-action=context-confirm]').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            JsonElement confirm = RequestBody(Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/confirm"));
            Assert.Equal(Head, confirm.GetProperty("expected_head").GetString());
            Assert.Equal(RecordDigest, confirm.GetProperty("expected_record_digest").GetString());
            Assert.Equal(DependencyDigest, confirm.GetProperty("expected_dependency_digest").GetString());
            Assert.Empty(driver.Posted("context.review"));
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-review').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            JsonElement attachment = Assert.Single(driver.Posted("context.review"));
            Assert.Equal(ContextId, attachment.GetProperty("context_id").GetString());
            Assert.Equal(Head, attachment.GetProperty("head_digest").GetString());
            Assert.Equal(PackageSha, attachment.GetProperty("package_sha256").GetString());
            Assert.Single(driver.Posted("context.prepare"));
            Assert.Empty(driver.Posted("review.start"));
        });
    }

    [Fact]
    public void RequirementEntryUsesTheSamePreparedSavedEvidence()
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot()), async driver =>
        {
            await Prepare(driver);
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-target').value='1';"
                + "document.getElementById('context-text').value=" + JsonSerializer.Serialize(Hostile) + ";"
                + "document.getElementById('context-provenance').value='ai_proposal';"
                + "document.getElementById('context-save').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            JsonElement body = RequestBody(Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/requirement"));
            Assert.Equal(Hostile, body.GetProperty("text").GetString());
            Assert.Equal("ai_proposal", body.GetProperty("provenance_kind").GetString());
            Assert.Equal(Head, body.GetProperty("expected_head").GetString());
            Assert.Single(driver.Posted("context.prepare"));
            Assert.Empty(driver.Posted("context.review"));
        });
    }

    [Fact]
    public void ForcePreviewShowsValuesSavedFrameAndTransformedApplicationPoint()
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot(Force())), async driver =>
        {
            await Prepare(driver);
            string text = JsonDocument.Parse(await driver.Page.ExecuteScriptAsync("document.getElementById('context-records').textContent")).RootElement.GetString()!;
            Assert.Contains("25 kN", text);
            Assert.Contains("Frame X in root", text);
            Assert.Contains("Frame origin in root (m)", text);
            Assert.Contains("1, 2, 3", text);
            Assert.Contains("Root application point (m)", text);
            Assert.Contains("4, 5, 6", text);
            Assert.Contains("Unspecified", text);
            Assert.Contains("AI proposal", text);
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/confirm");
        });
    }

    [Fact]
    public void NativeSelectionPrefillsTheExactOccurrenceAndDoesNotConfirm()
    {
        ReviewPageDriver.Run(driver =>
        {
            Configure(driver, Snapshot());
            var route = driver.InitialRoutes[0];
            driver.InitialRoutes[0] = (route.Method, route.Path, route.Status,
                route.Body.Replace("\"targets_omitted\":0", "\"targets_omitted\":501"));
            driver.ContextSelected = new { status = "matched_saved_target", package_sha256 = PackageSha,
                kind = "component", entity_id = "cmp:0002", component_id = "cmp:0002", document_id = "doc:2",
                configuration = "Other", display_name = Hostile, native_calibrated = false,
                native_model_state = "selection_observation_only", freshness = "cannot_establish" };
        }, async driver =>
        {
            await Prepare(driver);
            Assert.True(await Bool(driver.Page, "document.getElementById('context-state').textContent.indexOf('501 saved targets omitted')>=0"));
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-selection').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.True(await Bool(driver.Page, "document.getElementById('context-target').value==='2'"));
            Assert.True(await Bool(driver.Page, "document.getElementById('context-state').textContent.indexOf('not been verified')>=0"));
            Assert.Single(driver.Posted("context.selection"));
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/confirm");
        });
    }

    [Fact]
    public void ChangedDocumentOrPackageClearsThePreparedContext()
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot(Requirement())), async driver =>
        {
            await Prepare(driver);
            await driver.Route("GET", Endpoint, 200, JsonSerializer.Serialize(new
            {
                initialized = true, package_sha256 = new string('f', 64), records = new object[0],
            }));
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-refresh').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.True(await Bool(driver.Page, "document.getElementById('context-entry').hidden"));
            Assert.True(await Bool(driver.Page, "document.getElementById('context-review').disabled"));
            Assert.Empty(driver.Posted("context.review"));
            await driver.DocumentChanged(new { path = @"C:\Fictional\other.SLDASM", configuration = "Other" });
            Assert.True(await Bool(driver.Page, "document.getElementById('context-entry').hidden"));
        });
    }

    [Fact]
    public void StaleConfirmationIsRefusedAndNeverAutomaticallyRetried()
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot(Requirement())), async driver =>
        {
            await Prepare(driver);
            await driver.Route("POST", Endpoint + "/confirm", 409, JsonSerializer.Serialize(new
            {
                error_class = "EngineeringContextConflict", message = "Inspect the changed saved inputs before confirming.", retryable = false,
            }));
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-actor').value='fictional-engineer';document.querySelector('[data-action=context-confirm]').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/confirm");
            Assert.True(await Bool(driver.Page, "document.getElementById('context-state').textContent.indexOf('changed saved inputs')>=0"));
            Assert.Empty(driver.Posted("context.review"));
            Assert.True(await Bool(driver.Page, "document.getElementById('context-review').disabled && document.getElementById('context-entry').hidden"));
        });
    }

    [Fact]
    public void AnExistingInputNeedsExplicitEditBeforeItCanBeReplaced()
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot(Requirement())), async driver =>
        {
            await Prepare(driver);
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-target').value='1';"
                + "document.getElementById('context-text').value='A different intended requirement';"
                + "document.getElementById('context-save').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/requirement");
            Assert.True(await Bool(driver.Page, "document.getElementById('context-state').textContent.indexOf('Choose Edit')>=0"));
            await driver.Page.ExecuteScriptAsync("document.querySelector('[data-action=context-edit]').click();document.getElementById('context-text').value='Explicitly revised';document.getElementById('context-save').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            JsonElement body = RequestBody(Assert.Single(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/requirement"));
            Assert.Equal("Explicitly revised", body.GetProperty("text").GetString());
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-new').click();0");
            Assert.True(await Bool(driver.Page, "document.getElementById('context-id').value==='requirement:2' && document.getElementById('context-text').value===''"));
        });
    }

    [Fact]
    public void PartialForceVectorsAreRefusedBeforeSaving()
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot()), async driver =>
        {
            await Prepare(driver);
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-target').value='1';document.getElementById('context-kind').value='applied_force';document.getElementById('context-kind').dispatchEvent(new Event('change'));document.getElementById('context-magnitude').value='10';document.getElementById('context-dx').value='1';document.getElementById('context-save').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString() == Endpoint + "/force");
            Assert.True(await Bool(driver.Page, "document.getElementById('context-state').textContent.indexOf('all three')>=0"));
        });
    }

    [Theory]
    [InlineData("refresh")]
    [InlineData("confirm")]
    public void AStandardReviewExpiresPendingContextRoutesAndBlocksContextControls(string operation)
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot(Requirement())), async driver =>
        {
            await Prepare(driver);
            driver.HoldReviewStart = true;
            string route = Endpoint + (operation == "confirm" ? "/confirm" : "");
            await driver.Page.ExecuteScriptAsync("(function(){var original=window.fetch;window.__contextRelease=null;window.fetch=function(url,request){if(String(url).slice(-"
                + route.Length + ") === " + JsonSerializer.Serialize(route)
                + "){return new Promise(function(resolve,reject){window.__contextRelease=function(){original(url,request).then(resolve,reject);};});}return original(url,request);};}());0");
            if (operation == "confirm")
                await driver.Page.ExecuteScriptAsync("document.getElementById('context-actor').value='fictional-engineer';document.querySelector('[data-action=context-confirm]').click();0");
            else await driver.Page.ExecuteScriptAsync("document.getElementById('context-refresh').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.True(await Bool(driver.Page, "typeof window.__contextRelease==='function'"));
            await driver.Page.ExecuteScriptAsync("document.getElementById('start-review').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.Single(driver.Posted("review.start"));
            Assert.True(await Bool(driver.Page, "document.getElementById('context-entry').hidden && document.getElementById('context-prepare').disabled && document.getElementById('context-selection').disabled && document.getElementById('context-review').disabled"));
            await driver.Page.ExecuteScriptAsync("window.__contextRelease();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.True(await Bool(driver.Page, "document.getElementById('context-entry').hidden"));
            Assert.Empty(driver.Posted("context.selection"));
            Assert.Empty(driver.Posted("context.review"));
            await driver.ReleaseReviewStart();
            Assert.True(await Bool(driver.Page, "document.getElementById('context-prepare').disabled && document.getElementById('context-review').disabled"));
        });
    }

    /// <summary>
    /// Owner decision 99A (the T116 integration review's first and fourth findings): saved context
    /// cannot be edited or reviewed while a review waits for Send, while its Send is being
    /// accepted, or while a restored review is checked again; and the context start is refused
    /// by the same guard ordinary Review has.
    /// </summary>
    [Fact]
    public void ContextControlsAreRefusedWhileAReviewWaitsOrItsSendIsPending()
    {
        WaitingReviewFixture waiting = WaitingReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            waiting.Configure(driver);
            Configure(driver, Snapshot(Requirement()));
        }, async driver =>
        {
            await driver.Settle();
            Assert.True(await Bool(driver.Page, ContextOff), "a waiting review on screen holds the context panel");
            await driver.Click("clear-review");
            await Prepare(driver);
            Assert.False(await Bool(driver.Page, "document.getElementById('context-review').disabled"));
            await driver.Read("document.querySelector(\"[data-chat-id='chat-1']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            Assert.True(await Bool(driver.Page, ContextOff), "the waiting review is shown again");
            await driver.HoldRoute("POST", "/sessions/chat-1/send", 202, "{}");
            await ReviewPageRecheckTests.PressSend(driver);
            Assert.True(await Bool(driver.Page, ContextOff), "a Send whose acceptance is held");
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-review').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.Empty(driver.Posted("context.review"));
            Assert.Empty(driver.Posted("review.start"));
        });
    }

    [Fact]
    public void ContextControlsAreRefusedWhileARestoredReviewIsCheckedAgain()
    {
        RestoredReviewFixture restored = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver =>
        {
            restored.Configure(driver);
            Configure(driver, Snapshot(Requirement()));
            driver.HoldReviewRecheck = true;
        }, async driver =>
        {
            await driver.Settle();
            Assert.True(await Bool(driver.Page, ContextOff), "a restored waiting review holds the context panel");
            await driver.Click("clear-review");
            await Prepare(driver);
            await driver.Read("document.querySelector(\"[data-chat-id='" + RestoredReviewFixture.EarlierChat + "']\").click();return JSON.stringify({ok:true});");
            await driver.Settle();
            await ReviewPageRecheckTests.PressSend(driver);
            Assert.Single(driver.Posted("review.recheck"));
            Assert.True(await Bool(driver.Page, ContextOff), "a re-run in flight");
            await driver.Page.ExecuteScriptAsync("document.getElementById('context-review').click();0");
            await OffscreenReviewPage.Settled(driver.Page);
            Assert.Empty(driver.Posted("context.review"));
            await driver.ReleaseReviewRecheck();
            Assert.True(await Bool(driver.Page, ContextOff), "the re-run's chat waits for Send");
        });
    }

    /// <summary>
    /// Owner decision 108A: Retry on a failed context review asks the host to retry that chat,
    /// which re-attaches its saved context (the host's part); the box at Retry decides Send or
    /// Wait. The page sends no second context.review and no new preparation.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void RetryOnAFailedContextReviewRetriesThatChat(bool sendWhenChecked)
    {
        ReviewPageDriver.Run(driver => Configure(driver, Snapshot(Requirement())), async driver =>
        {
            await FailedContextReview(driver);
            driver.SendWhenChecked = sendWhenChecked;

            await driver.Read("document.querySelector('#errors [data-action=retry]').click();return JSON.stringify({ok:true});");
            await driver.Settle();

            JsonElement retry = Assert.Single(driver.Posted("review.start"));
            Assert.Equal("chat-1", retry.GetProperty("retry_of").GetString());
            Assert.Single(driver.Posted("context.review"));
            Assert.Single(driver.Posted("context.prepare"));
            string status = (await driver.Read("return JSON.stringify({ok:true,text:document.getElementById('results-state').textContent});")).GetProperty("text").GetString()!;
            Assert.Equal(!sendWhenChecked, status == "Checked by code. Not sent to the model.");
        });
    }

    [Fact]
    public void ARefusedContextRetryPointsToTheContextPanel()
    {
        WaitingReviewFixture words = WaitingReviewFixture.Read();
        string label = words.Root.GetProperty("labels").GetProperty("errors").GetProperty("EngineeringContextConflict").GetString()!;
        ReviewPageDriver.Run(driver =>
        {
            Configure(driver, Snapshot(Requirement()));
            driver.InitialRoutes.Add(("GET", "/labels", 200, words.Root.GetProperty("labels").GetRawText()));
        }, async driver =>
        {
            await FailedContextReview(driver);
            driver.ReviewStartError = new
            {
                error_class = "EngineeringContextConflict", retryable = false,
                message = "The saved engineering context changed after this review started.",
            };

            await driver.Read("document.querySelector('#errors [data-action=retry]').click();return JSON.stringify({ok:true});");
            await driver.Settle();

            string errors = (await driver.Read("return JSON.stringify({ok:true,text:document.getElementById('errors').textContent});")).GetProperty("text").GetString()!;
            Assert.Contains("Engineering context panel", label);
            Assert.Contains(label, errors);
        });
    }

    /// <summary>A review started from the context panel whose first request failed.</summary>
    private static async Task FailedContextReview(ReviewPageDriver driver)
    {
        await Prepare(driver);
        await driver.Page.ExecuteScriptAsync("document.getElementById('context-review').click();0");
        await OffscreenReviewPage.Settled(driver.Page);
        Assert.Single(driver.Posted("context.review"));
        await driver.Push("chat-1", 1, "error", "{\"error_class\":\"FICTTickedError\",\"message\":\"FICT-first request failed\",\"retryable\":true}");
        await driver.Push("chat-1", 2, "turn.ended", "{\"reason\":\"error\"}");
        await driver.Push("chat-1", 3, "session.ended", "{\"ended_at\":\"2026-10-15T12:00:00+00:00\"}");
        await driver.Settle();
        Assert.True(JsonDocument.Parse(await driver.Page.ExecuteScriptAsync("!!document.querySelector('#errors [data-action=retry]')")).RootElement.GetBoolean());
    }

    /// <summary>Every context control that edits, prepares or reviews is off.</summary>
    private const string ContextOff = "['context-prepare','context-selection','context-save','context-new','context-review']"
        + ".every(function(id){return document.getElementById(id).disabled;})";

    [Fact]
    public void LegacyPrivateLabelsCannotBeEditedOrConfirmedFromThePublicPane()
    {
        ReviewPageDriver.Run(driver =>
        {
            Configure(driver, Snapshot(Requirement()));
            var route = driver.InitialRoutes[0];
            driver.InitialRoutes[0] = (route.Method, route.Path, route.Status,
                route.Body.Replace("\"record_id\":\"requirement:1\"", "\"record_id\":null"));
        }, async driver =>
        {
            await Prepare(driver);
            Assert.True(await Bool(driver.Page, "document.querySelector('[data-action=context-edit]').disabled && document.querySelector('[data-action=context-confirm]').disabled"));
        });
    }

    private static JsonElement RequestBody(JsonElement call) =>
        JsonDocument.Parse(call.GetProperty("body").GetString()!).RootElement.Clone();

    private static void Configure(ReviewPageDriver driver, object snapshot)
    {
        driver.ContextPrepared = new { run_id = RunId, package_sha256 = PackageSha, document = driver.Document };
        driver.InitialRoutes.Add(("GET", Endpoint, 200, JsonSerializer.Serialize(snapshot)));
        foreach (string operation in new[] { "init", "requirement", "force", "confirm" })
            driver.InitialRoutes.Add(("POST", Endpoint + "/" + operation, 200, JsonSerializer.Serialize(new
            { run_id = RunId, context_id = ContextId, revision = 1, head_digest = Head, package_sha256 = PackageSha })));
    }

    private static async Task Prepare(ReviewPageDriver driver)
    {
        await driver.Page.ExecuteScriptAsync("document.getElementById('engineering-context').open=true;document.getElementById('context-prepare').click();0");
        await OffscreenReviewPage.Settled(driver.Page);
        Assert.Single(driver.Posted("context.prepare"));
        Assert.True(await Bool(driver.Page, "!document.getElementById('context-entry').hidden"));
        Assert.Empty(driver.Posted("review.start"));
    }

    private static Task<bool> Bool(CoreWebView2 page, string expression) => ReadBool(page, expression);
    private static async Task<bool> ReadBool(CoreWebView2 page, string expression) =>
        JsonDocument.Parse(await page.ExecuteScriptAsync(expression)).RootElement.GetBoolean();

    private static object Snapshot(params object[] records) => new
    {
        initialized = true, run_id = RunId, package_sha256 = PackageSha,
        context_id = ContextId, revision = 1, head_digest = Head, scope = "saved_snapshot", native_model_state = "not_observed",
        records, targets_omitted = 0,
        targets = new object[]
        {
            new { kind = "document", entity_id = "doc:1", document_id = "doc:1", configuration = "Default", component_id = (string?)null, label = "Root model" },
            new { kind = "component", entity_id = "cmp:0001", document_id = "doc:2", configuration = "Default", component_id = "cmp:0001", label = Hostile },
            new { kind = "component", entity_id = "cmp:0002", document_id = "doc:2", configuration = "Other", component_id = "cmp:0002", label = "Second bracket occurrence" },
        },
    };

    private static object Requirement() => new
    {
        record = new { kind = "requirement", record_id = "requirement:1", revision = 1,
            anchor = new { kind = "component", entity_id = "cmp:0001", document_id = "doc:2", configuration = "Default", component_id = "cmp:0001", label = Hostile },
            provenance = new { kind = "engineer" }, assumptions = new[] { "Fictional operating conditions" }, text = Hostile },
        record_digest = RecordDigest, dependency_digest = DependencyDigest, decision = "draft",
        binding = new { status = "matched_snapshot", needs_review = false, reasons = new string[0] }, freshness = "current_snapshot",
    };

    private static object Force() => new
    {
        record = new { kind = "applied_force", record_id = "force:1", revision = 1,
            anchor = new { kind = "component", entity_id = "cmp:0001", document_id = "doc:2", configuration = "Default", component_id = "cmp:0001", label = Hostile },
            provenance = new { kind = "ai_proposal" }, assumptions = new[] { "Fictional force" },
            magnitude = new { state = "known", value = 25.0, unit = "kN", reason = (string?)null },
            direction = new[] { 0.0, 1.0, 0.0 }, application = "component_total", point_m = new[] { 3.0, 3.0, 3.0 },
            frame = new { frame_id = "frame:input", document_id = "doc:1", component_id = (string?)null, label = "Root saved frame",
                transform = new[] { new[] { 1.0, 0.0, 0.0, 1.0 }, new[] { 0.0, 1.0, 0.0, 2.0 }, new[] { 0.0, 0.0, 1.0, 3.0 }, new[] { 0.0, 0.0, 0.0, 1.0 } } } },
        record_digest = RecordDigest, dependency_digest = DependencyDigest, decision = "draft",
        binding = new { status = "matched_snapshot", needs_review = false, reasons = new string[0] }, freshness = "current_snapshot",
        resolved_force = new { magnitude_n = 25000.0, direction = new[] { 0.0, 1.0, 0.0 }, vector_n = new[] { 0.0, 25000.0, 0.0 }, point_m = new[] { 4.0, 5.0, 6.0 } },
    };

}
