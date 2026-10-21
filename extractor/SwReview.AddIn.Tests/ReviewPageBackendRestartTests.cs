using System;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 143A, the Review page's half, against the real page in an offscreen WebView2.
///
/// When a settings save meets a turn that started during it, the host restarts the backend once
/// nothing holds it back and tells the page with `backend.restarted {sentences}`. Nothing else
/// tells it: the save's own reply came long before, while the old backend still ran. The new
/// backend has a new port and a new token, and the page holds the old ones from its last `init` -
/// every call it made with them would be refused - so on that message it asks `ready` again, as it
/// does after a save that restarted the backend at once, and takes whichever of the host's
/// sentences about the wait is on the banner off it, since neither is true once the restart is
/// made; anything else there stays.
///
/// Owner decision 150A adds what a failed or stopped backend leaves on this page: a save whose
/// restart failed says the settings are saved and the backend did not restart, asks for its
/// `init` again and says the backend is not running while none is named; and `backend.stopped`
/// names saving the settings as the way to start it again.
///
/// Owner decision 153A adds what a restart that failed before it stopped the old backend leaves:
/// that backend runs on with the settings it was started with, and while `init` says the saved
/// settings are not in force the banner says so whenever it says nothing else.
/// </summary>
public sealed class ReviewPageBackendRestartTests
{
    /// <summary>The host's sentence for a save a turn started during (ReviewHost, `settings.save`).</summary>
    private const string Promise = "the settings are saved; the backend restarts when the running turn ends.";

    /// <summary>The host's sentence when its watcher stops looking at a backend that does not answer.</summary>
    private const string NotAnswering =
        "the review backend is not answering, so it has not been restarted with the saved settings yet. "
        + "It will be before the next review, follow-up or remodel run, once it answers; to restart it "
        + "now, save the settings again.";

    /// <summary>The host's sentence for a save made while a remodel run is in progress (owner decision 145A).</summary>
    private const string RemodelRunPromise =
        "the settings are saved; the backend restarts when the remodel run ends.";

    /// <summary>...and for one a turn also started during.</summary>
    private const string TurnAndRemodelRunPromise =
        "the settings are saved; the backend restarts when the running turn and the remodel run end.";

    /// <summary>`backend.restarted` as the host posts it: every one of its sentences about the wait.</summary>
    private static readonly object Restarted = new
    {
        sentences = new[] { Promise, RemodelRunPromise, TurnAndRemodelRunPromise, NotAnswering },
    };

    private const string RestartedToken = "FICT-restarted-backend-token";

    private const string Banner =
        "var banner = document.getElementById('banner');"
        + "return JSON.stringify({ text: banner.textContent, hidden: !!banner.hidden });";

    [Fact]
    public void ABackendRestartedIsAskedForAgainClearsTheSentenceAndIsCalledWithItsOwnToken()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.Post("status", new { stage = "error", message = Promise });
            Assert.Equal(Promise, (await driver.Read(Banner)).GetProperty("text").GetString());

            int readies = driver.Posted("ready").Length;
            await driver.ClearCalls();
            driver.BackendToken = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init again");
            await driver.Settle();

            JsonElement banner = await driver.Read(Banner);
            Assert.True(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(string.Empty, banner.GetProperty("text").GetString());

            // `init` names a backend, so the page reads its labels from it - with the new token,
            // and nothing is sent with the old one.
            JsonElement[] calls = await driver.Calls();
            Assert.Contains(calls, call => call.GetProperty("path").GetString() == "/labels"
                && call.GetProperty("authorization").GetString() == "Bearer " + RestartedToken);
            Assert.DoesNotContain(calls, call =>
                call.GetProperty("authorization").GetString() == "Bearer " + ReviewPageDriver.Token);
        });
    }

    /// <summary>
    /// The host's other sentence about the wait - its watcher stopped looking at a backend that
    /// did not answer - is done with too once the restart is made, and comes off the banner.
    /// </summary>
    [Fact]
    public void ABackendRestartedTakesTheNotAnsweringSentenceOffTheBanner()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.Post("status", new { stage = "error", message = NotAnswering });
            Assert.Equal(NotAnswering, (await driver.Read(Banner)).GetProperty("text").GetString());
            int readies = driver.Posted("ready").Length;
            driver.BackendToken = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init again");
            await driver.Settle();

            JsonElement banner = await driver.Read(Banner);
            Assert.True(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
        });
    }

    /// <summary>
    /// Owner decision 145A: the host's sentences for a save whose restart waits for a remodel run,
    /// or for a turn and a remodel run, are done with too once the restart is made, and come off
    /// the banner as the turn's does.
    /// </summary>
    [Theory]
    [InlineData(RemodelRunPromise)]
    [InlineData(TurnAndRemodelRunPromise)]
    public void ABackendRestartedTakesTheRemodelRunSentencesOffTheBanner(string sentence)
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.Post("status", new { stage = "error", message = sentence });
            Assert.Equal(sentence, (await driver.Read(Banner)).GetProperty("text").GetString());
            int readies = driver.Posted("ready").Length;
            driver.BackendToken = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init again");
            await driver.Settle();

            JsonElement banner = await driver.Read(Banner);
            Assert.True(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
        });
    }

    /// <summary>
    /// The restart takes back only its own sentences: a banner that has said something else since -
    /// a later failure the engineer has not read yet - stays.
    /// </summary>
    [Fact]
    public void ABackendRestartedTakesOnlyItsOwnSentenceOffTheBanner()
    {
        const string Later = "FICT the dump stopped: the model did not rebuild.";
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.Post("status", new { stage = "error", message = Promise });
            await driver.Post("status", new { stage = "error", message = Later });
            int readies = driver.Posted("ready").Length;
            driver.BackendToken = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init again");
            await driver.Settle();

            JsonElement banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(Later, banner.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// An `init` already on its way when `backend.restarted` arrives may have been read before the
    /// new backend was up - the host reads the endpoint when it answers, and during the restart
    /// there is none - so the page asks once more after it, rather than taking that answer as
    /// the last word or sending a second `ready` beside it.
    /// </summary>
    [Fact]
    public void ARestartAnnouncedWhileAnInitIsOnItsWayIsFollowedByOneMoreAsk()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            int readies = driver.Posted("ready").Length;
            driver.HoldReady = true;

            await driver.Post("backend.restarted", new { });
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init");
            await driver.Post("backend.restarted", new { });
            await driver.Settle();
            Assert.Equal(readies + 1, driver.Posted("ready").Length);
            Assert.Equal(1, driver.HeldReady);

            driver.BackendToken = RestartedToken;
            await driver.ReleaseReady();
            await driver.Until(() => driver.Posted("ready").Length == readies + 2, "asked once more");
            await driver.Settle();
            Assert.Equal(readies + 2, driver.Posted("ready").Length);
        });
    }

    /// <summary>
    /// The `init` on its way may have been read while there was no backend at all - between the
    /// old child stopping and the new one answering - and so carries no token. The restart is
    /// still believed when the next one does: a live waiting review on screen, whose chat the
    /// new backend does not hold, is restored from its folder at once (feature 015 FR-042), as it
    /// is when the token simply changes.
    /// </summary>
    [Fact]
    public void ARestartIsBelievedEvenWhenTheInitBeforeItWasReadWithNoBackend()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver => fixture.Configure(driver, refuseSend: true), async driver =>
        {
            await ReviewPageRecheckTests.PressSend(driver);
            Assert.False((await driver.Read(ReviewPageRecheckTests.ReadState)).GetProperty("readOnly").GetBoolean());
            await driver.Route("GET", "/sessions/" + fixture.RecheckedChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat);
            int reviews = (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath);
            int readies = driver.Posted("ready").Length;

            // A save's reply makes the page ask for its `init`; the restart is announced while that
            // one is on its way, and the host read it while the restart was being made.
            driver.HoldReady = true;
            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init after the save");
            await driver.Post("backend.restarted", new { });
            driver.BackendToken = RestartedToken;
            await driver.ReleaseReady(backendUp: false);
            await driver.Until(() => driver.Posted("ready").Length == readies + 2, "asked once more");
            await driver.Settle();

            JsonElement state = await driver.Read(ReviewPageRecheckTests.ReadState);
            Assert.True(state.GetProperty("readOnly").GetBoolean(), state.GetRawText());
            Assert.Equal(
                reviews + 1,
                (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath));
        });
    }

    /// <summary>
    /// The `init` on its way may also have been read before the restart began, and so name the old
    /// backend - the token the page already held when `backend.restarted` arrived. That one is not
    /// the new backend: nothing is restored with it, and the restart is still believed when the
    /// next `init` names the new one, which is the one the live waiting review is restored with.
    /// </summary>
    [Fact]
    public void AnInitReadBeforeTheRestartIsNotTakenForTheNewBackend()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver => fixture.Configure(driver, refuseSend: true), async driver =>
        {
            await ReviewPageRecheckTests.PressSend(driver);
            Assert.False((await driver.Read(ReviewPageRecheckTests.ReadState)).GetProperty("readOnly").GetBoolean());
            await driver.Route("GET", "/sessions/" + fixture.RecheckedChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat);
            int readies = driver.Posted("ready").Length;

            // An `init` on its way, which the host read while the old backend still ran...
            driver.HoldReady = true;
            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init after the save");
            await driver.ClearCalls();

            // ...the restart, announced while it is on its way...
            await driver.Post("backend.restarted", Restarted);
            driver.BackendToken = RestartedToken;

            // ...and then it arrives, naming the old backend.
            await driver.ReleaseReady(token: ReviewPageDriver.Token);
            await driver.Until(() => driver.Posted("ready").Length == readies + 2, "asked once more");
            await driver.Settle();

            JsonElement[] restores = (await driver.Calls())
                .Where(call => call.GetProperty("path").GetString() == fixture.ReviewPath)
                .ToArray();
            JsonElement restore = Assert.Single(restores);
            Assert.Equal("Bearer " + RestartedToken, restore.GetProperty("authorization").GetString());
            Assert.True((await driver.Read(ReviewPageRecheckTests.ReadState)).GetProperty("readOnly").GetBoolean());
        });
    }

    /// <summary>
    /// A `ready` makes the host close the event reader it holds for this page - that is how a page
    /// that reloads drops a stream it no longer shows - but a page that only asks for its `init`
    /// again has not reloaded. Reading a stream, it asks for it again from the last event it
    /// showed, on the same backend: a save that a turn started during re-inits the page while
    /// that turn runs, and without this the page never saw the turn end and stayed "running".
    /// </summary>
    [Fact]
    public void AReInitWhileATurnRunsAsksForItsStreamAgainFromTheLastEventShown()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.StartReview();
            JsonElement opened = Assert.Single(driver.Posted("events.open"));
            string chatId = opened.GetProperty("chat_id").GetString()!;
            await driver.Push(chatId, 7, "text.delta", "{\"text\":\"FICT\"}");
            await driver.Settle();

            int readies = driver.Posted("ready").Length;
            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init after the save");
            await driver.Settle();

            JsonElement[] opens = driver.Posted("events.open");
            Assert.Equal(2, opens.Length);
            Assert.Equal(chatId, opens[1].GetProperty("chat_id").GetString());
            Assert.Equal("7", opens[1].GetProperty("last_event_id").GetString());
        });
    }

    /// <summary>
    /// ...and a page told the backend was replaced asks nothing of the old chat's stream: not when
    /// it re-inits, and not by a reconnect the old stream's close left waiting - the new backend
    /// does not hold the chat, and each 404 would only schedule another.
    /// </summary>
    [Fact]
    public void AReInitOnARestartedBackendAsksNothingOfTheOldChatsStream()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.HoldTimers();
            await driver.StartReview();
            string chatId = Assert.Single(driver.Posted("events.open")).GetProperty("chat_id").GetString()!;
            await driver.Push(chatId, 7, "text.delta", "{\"text\":\"FICT\"}");
            await driver.Settle();

            // The old backend stops: its stream closes, and the page means to reconnect to it.
            await driver.Post("events.closed", new { chat_id = chatId, reason = "FICT the stream closed." });
            await driver.Settle();

            int readies = driver.Posted("ready").Length;
            driver.BackendToken = RestartedToken;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init again");
            await driver.Settle();
            await driver.RunHeldTimers();
            await driver.RunHeldTimers();

            Assert.Single(driver.Posted("events.open"));
        });
    }

    // ---- owner decision 150A: a save whose restart failed, and a backend that stopped -------------

    /// <summary>The host's answer to a save whose restart failed (ReviewHost, `settings.save`).</summary>
    private const string NotRestartedMessage =
        "the settings are saved, but the review backend did not restart with them. Save the settings again "
        + "to retry the restart. The restart failed: FICT the backend did not answer /health within 30 seconds.";

    private static readonly object NotRestarted = new
    {
        error_class = "BackendNotRestarted",
        message = NotRestartedMessage,
        retryable = true,
    };

    private const string SaveLine = @"
var node = document.getElementById('save-state');
var fold = node.querySelector('details');
return JSON.stringify({
  visible: h.visibleText(node),
  fold: fold ? fold.textContent : '',
  text: node.textContent,
  key: document.getElementById('api-key').value
});";

    private const string Strip =
        "var strip = document.getElementById('backend-state');"
        + "return JSON.stringify({ text: strip.textContent, className: strip.className });";

    /// <summary>
    /// Owner decision 160A: the add-in's word that the first start failed - an `error` status while the page holds
    /// no backend - leaves the strip saying the backend is not running, as the other tabs' strips say it (150A),
    /// where it said "Error", until an `init` names a backend; one that names none leaves it so.
    /// </summary>
    [Fact]
    public void AFailedFirstStartLeavesTheStripNotRunningUntilAnInitNamesABackend()
    {
        ReviewPageDriver.Run(driver => driver.NoBackend = true, async driver =>
        {
            const string Failure = "FICT the backend did not start. Save Settings to start it again.";
            await driver.Post("status", new { stage = "error", message = Failure });
            Assert.Equal("Backend not running", (await driver.Read(Strip)).GetProperty("text").GetString());

            int readies = driver.Posted("ready").Length;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init again");
            await driver.Settle();
            Assert.Equal("Backend not running", (await driver.Read(Strip)).GetProperty("text").GetString());

            driver.NoBackend = false;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length == readies + 2, "asked for the running backend");
            await driver.Settle();
            Assert.Equal("Backend ready", (await driver.Read(Strip)).GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// ...and a `status` that is not an error - "Backend ready." from a start made since - does not overwrite it: the
    /// strip says the backend is not running until the `init` that status asks for names a backend.
    /// </summary>
    [Fact]
    public void AReadyStatusAfterAFailedFirstStartKeepsTheStripNotRunningUntilItsInitNamesABackend()
    {
        ReviewPageDriver.Run(driver => driver.NoBackend = true, async driver =>
        {
            await driver.Post("status", new { stage = "error", message = "FICT the backend did not start." });
            driver.HoldReady = true;
            int readies = driver.Posted("ready").Length;

            await driver.Post("status", new { stage = "ready", message = "Backend ready." });
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for the backend named by ready");
            Assert.Equal("Backend not running", (await driver.Read(Strip)).GetProperty("text").GetString());

            await driver.ReleaseReady(backendUp: false);
            Assert.Equal("Backend not running", (await driver.Read(Strip)).GetProperty("text").GetString());

            driver.NoBackend = false;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length == readies + 2, "asked for the running backend");
            await driver.Settle();
            Assert.Equal("Backend ready", (await driver.Read(Strip)).GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// Owner decision 160A: a page that loads, or loads again, after a failed start or restart - whose `status` it
    /// never saw - is told so by `init` (`backend_start_failed`), and says the backend is not running and the way
    /// on, "Save Settings to start it again", where it said "Backend starting"; an `init` that names a backend takes
    /// both down.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void APageLoadedAfterAFailedStartSaysTheBackendIsNotRunningAndHowToStartIt(bool reload)
    {
        ReviewPageDriver.Run(driver =>
        {
            driver.NoBackend = true;
            driver.BackendStartFailed = true;
        }, async driver =>
        {
            if (reload)
            {
                await driver.Reload();
            }

            Assert.Equal("Backend not running", (await driver.Read(Strip)).GetProperty("text").GetString());
            JsonElement banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean());
            Assert.Equal("The backend is not running. Save Settings to start it again.", banner.GetProperty("text").GetString());

            driver.NoBackend = false;
            driver.BackendStartFailed = false;
            int readies = driver.Posted("ready").Length;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for the running backend");
            await driver.Settle();
            Assert.Equal("Backend ready", (await driver.Read(Strip)).GetProperty("text").GetString());
            Assert.True((await driver.Read(Banner)).GetProperty("hidden").GetBoolean());
        });
    }

    /// <summary>...while one that loads before the first start has finished, which has not failed, still says it is starting.</summary>
    [Fact]
    public void APageLoadedBeforeTheFirstStartFinishesStillSaysBackendStarting()
    {
        ReviewPageDriver.Run(driver => driver.NoBackend = true, async driver =>
        {
            Assert.Equal("Backend starting", (await driver.Read(Strip)).GetProperty("text").GetString());
            Assert.True((await driver.Read(Banner)).GetProperty("hidden").GetBoolean());
        });
    }

    /// <summary>
    /// ...and an `init` that takes down 153A's sentence - no backend up, nothing in force - leaves the banner to the way
    /// on: the page weighs the sentence before the failed start's word, which takes the banner only when it says
    /// nothing else.
    /// </summary>
    [Fact]
    public void AFailedStartInitReplacesTheOldSettingsNotInForceSentenceWithTheWayOn()
    {
        ReviewPageDriver.Run(driver =>
        {
            driver.SettingsNotInForce = NotInForce;
            driver.SettingsNotInForceRevision = 1;
        }, async driver =>
        {
            Assert.Equal(NotInForce, (await driver.Read(Banner)).GetProperty("text").GetString());
            driver.NoBackend = true;
            driver.BackendStartFailed = true;
            driver.SettingsNotInForce = null;
            driver.SettingsNotInForceRevision = 2;
            int readies = driver.Posted("ready").Length;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for the failed backend");
            await driver.Settle();

            JsonElement banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean());
            Assert.Equal("The backend is not running. Save Settings to start it again.", banner.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// A save whose restart failed is a save that was kept (owner decision 150A): the save's line
    /// says so in the class's sentence - the settings are saved, the backend did not restart, save
    /// again to retry - with the class and the reason in the fold; and, as after a save that
    /// restarted the backend, the page asks for its `init` again, so it shows the settings saved -
    /// the key typed is in the store and leaves the box - and holds the backend there is now.
    /// </summary>
    [Fact]
    public void ASaveWhoseRestartFailedSaysTheSettingsAreSavedAndAsksForItsInitAgain()
    {
        ReviewPageDriver.Run(
            driver => driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json())),
            async driver =>
            {
                await driver.Read("document.getElementById('api-key').value = 'FICT-typed-key'; return JSON.stringify({ok: true});");
                int readies = driver.Posted("ready").Length;
                driver.SettingsSaveError = NotRestarted;

                await driver.Click("save-settings");
                await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init after the save");
                await driver.Settle();

                JsonElement line = await driver.Read(SaveLine);
                string visible = line.GetProperty("visible").GetString()!.Trim();
                Assert.StartsWith(LabelsSample.BackendNotRestarted, visible, StringComparison.Ordinal);
                Assert.DoesNotContain("BackendNotRestarted", visible, StringComparison.Ordinal);
                Assert.Contains("BackendNotRestarted", line.GetProperty("fold").GetString()!, StringComparison.Ordinal);
                Assert.Contains(NotRestartedMessage, line.GetProperty("fold").GetString()!, StringComparison.Ordinal);
                Assert.Equal(string.Empty, line.GetProperty("key").GetString());
            });
    }

    /// <summary>
    /// With no labels - a backend that never answered this page, say - the save's line prints the
    /// host's message as it is, which says all of it, rather than "class: message".
    /// </summary>
    [Fact]
    public void ASaveWhoseRestartFailedPrintsItsMessageWhenThereAreNoLabels()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            driver.SettingsSaveError = NotRestarted;

            await driver.Click("save-settings");
            await driver.Settle();

            Assert.Equal(NotRestartedMessage, (await driver.Read(SaveLine)).GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// Owner decision 160A: a save answered `AddInStopping` - written while the add-in unloads - shows the class's
    /// sentence on its line, with the class in the fold, or with no labels the message whole, never "class:
    /// message"; and the page asks for no `init`, since nothing more will answer it.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ASaveDuringUnloadSaysTheSettingsAreSavedAndTheAddInIsStopping(bool withLabels)
    {
        ReviewPageDriver.Run(driver =>
        {
            if (withLabels)
            {
                driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
            }
            driver.SettingsSaveError = new
            {
                error_class = "AddInStopping",
                message = LabelsSample.AddInStopping,
                retryable = false,
            };
        }, async driver =>
        {
            int readies = driver.Posted("ready").Length;
            await driver.Click("save-settings");
            await driver.Settle();

            JsonElement line = await driver.Read(SaveLine);
            string visible = line.GetProperty("visible").GetString()!.Trim();
            Assert.StartsWith(LabelsSample.AddInStopping, visible, StringComparison.Ordinal);
            Assert.DoesNotContain("AddInStopping", visible, StringComparison.Ordinal);
            Assert.Equal(readies, driver.Posted("ready").Length);
            if (withLabels)
            {
                Assert.Contains("AddInStopping", line.GetProperty("fold").GetString()!, StringComparison.Ordinal);
            }
            else
            {
                Assert.Equal(LabelsSample.AddInStopping, line.GetProperty("text").GetString());
            }
        });
    }

    /// <summary>
    /// After a save whose restart failed, the strip says the backend is not running while an
    /// `init` names none - the old backend stopped, and nothing is starting - rather than "Backend
    /// starting"; it says "Backend ready" once one names a backend, and an `init` that names none
    /// after that is back to "Backend starting", as it says while a restart is being made.
    /// </summary>
    [Fact]
    public void AfterASaveWhoseRestartFailedTheStripSaysTheBackendIsNotRunningUntilAnInitNamesOne()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            int readies = driver.Posted("ready").Length;
            driver.SettingsSaveError = NotRestarted;
            driver.HoldReady = true;

            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init after the save");
            await driver.ReleaseReady(backendUp: false);
            JsonElement strip = await driver.Read(Strip);
            Assert.Equal("Backend not running", strip.GetProperty("text").GetString());
            Assert.Contains("bad", strip.GetProperty("className").GetString()!, StringComparison.Ordinal);

            driver.BackendToken = RestartedToken;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length == readies + 2, "asked for init again");
            await driver.Settle();
            Assert.Equal("Backend ready", (await driver.Read(Strip)).GetProperty("text").GetString());

            driver.HoldReady = true;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Posted("ready").Length == readies + 3, "asked for init once more");
            await driver.ReleaseReady(backendUp: false);
            Assert.Equal("Backend starting", (await driver.Read(Strip)).GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// A save whose restart failed once the old backend had stopped, then a save that restarted it.
    /// The `init` between the two named no backend, so the next one has no token to compare its own
    /// with; the page still knows the backend was replaced, and asks the new one nothing of the old
    /// chat's stream - which it does not hold - as after any restart (143A). Until the 150A review
    /// it asked, and a 404 and a reconnect after it began (S1).
    /// </summary>
    [Fact]
    public void AfterASaveWhoseRestartFailedTheNextRestartAsksNothingOfTheOldChatsStream()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.HoldTimers();
            await driver.StartReview();
            string chatId = Assert.Single(driver.Posted("events.open")).GetProperty("chat_id").GetString()!;
            await driver.Push(chatId, 7, "text.delta", "{\"text\":\"FICT\"}");
            await driver.Settle();

            await SaveWhoseRestartFailsOnceTheOldBackendStopped(driver);
            int opens = driver.Posted("events.open").Length;

            await SaveThatRestartsTheBackend(driver);
            await driver.RunHeldTimers();
            await driver.RunHeldTimers();

            Assert.Equal(opens, driver.Posted("events.open").Length);
        });
    }

    /// <summary>
    /// ...and a live waiting review on screen is restored from its folder, read-only with Send
    /// offered, by the restart that worked (feature 015 FR-042), as by any other: until the 150A
    /// review it stayed live, and its Send went to a backend that did not hold its chat (S1).
    /// </summary>
    [Fact]
    public void AfterASaveWhoseRestartFailedTheNextRestartRestoresALiveWaitingReview()
    {
        RestoredReviewFixture fixture = RestoredReviewFixture.Read();
        ReviewPageDriver.Run(driver => fixture.Configure(driver, refuseSend: true), async driver =>
        {
            await ReviewPageRecheckTests.PressSend(driver);
            Assert.False((await driver.Read(ReviewPageRecheckTests.ReadState)).GetProperty("readOnly").GetBoolean());
            await driver.Route("GET", "/sessions/" + fixture.RecheckedChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat);
            int reviews = (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath);

            await SaveWhoseRestartFailsOnceTheOldBackendStopped(driver);
            await SaveThatRestartsTheBackend(driver);

            JsonElement state = await driver.Read(ReviewPageRecheckTests.ReadState);
            Assert.True(state.GetProperty("readOnly").GetBoolean(), state.GetRawText());
            Assert.Equal(
                reviews + 1,
                (await driver.Calls()).Count(call => call.GetProperty("path").GetString() == fixture.ReviewPath));
        });
    }

    /// <summary>A save answered `BackendNotRestarted`, and the `init` after it naming no backend: the old one stopped.</summary>
    private static async System.Threading.Tasks.Task SaveWhoseRestartFailsOnceTheOldBackendStopped(ReviewPageDriver driver)
    {
        int readies = driver.Posted("ready").Length;
        driver.SettingsSaveError = NotRestarted;
        driver.HoldReady = true;
        await driver.Click("save-settings");
        await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init after the failed save");
        await driver.ReleaseReady(backendUp: false);
    }

    /// <summary>A save answered `settings.saved`: its restart made, a new backend with a new token.</summary>
    private static async System.Threading.Tasks.Task SaveThatRestartsTheBackend(ReviewPageDriver driver)
    {
        int readies = driver.Posted("ready").Length;
        driver.SettingsSaveError = null;
        driver.BackendToken = RestartedToken;
        await driver.Click("save-settings");
        await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init after the save");
        await driver.Settle();
    }

    /// <summary>
    /// `backend.stopped` names the way that starts the backend again: the add-in starts it when it
    /// loads, and a settings save restarts it, so on this tab, where the settings are saved, the
    /// sentence sends the engineer to Save Settings - not to reopen the pane, which starts nothing.
    /// </summary>
    [Fact]
    public void ABackendStoppedNamesSavingTheSettingsAsTheWayToStartItAgain()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.Post("backend.stopped", new { exit_code = 1, log_path = @"C:\Fictional\FICT-logs\backend.log" });

            JsonElement strip = await driver.Read(Strip);
            Assert.Equal("The backend stopped. Save Settings to start it again.", strip.GetProperty("text").GetString());
            Assert.Contains("bad", strip.GetProperty("className").GetString()!, StringComparison.Ordinal);
        });
    }

    // ---- owner decision 153A: the saved settings are not in force yet ------------------------------

    /// <summary>The host's sentence while the saved settings are not in force (ReviewHost, `init`).</summary>
    private const string NotInForce =
        "The saved settings are not in force yet: the review backend did not restart with them, so reviews "
        + "run with the settings it was started with. Save the settings again to retry the restart.";

    /// <summary>Another word for the banner: a failure the engineer has not read yet.</summary>
    private const string Failure = "FICT the dump stopped: the model did not rebuild.";

    /// <summary>
    /// A page that loads, or loads again, while the backend that is up runs with settings other than
    /// the saved ones - a restart failed before it stopped the old backend - is told so by its `init`,
    /// and says it on its banner: the saved settings are not in force yet, and saving again retries.
    /// </summary>
    [Fact]
    public void APageThatLoadsWhileTheSavedSettingsAreNotInForceSaysSoOnItsBanner()
    {
        ReviewPageDriver.Run(driver => driver.SettingsNotInForce = NotInForce, async driver =>
        {
            JsonElement banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(NotInForce, banner.GetProperty("text").GetString());

            await driver.Reload();

            banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(NotInForce, banner.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// The sentence is said for as long as it is true: it is what the banner says whenever it says
    /// nothing else. A status that clears the banner - a review's, which runs with the settings in
    /// force - leaves the sentence on it; another word takes the banner, and once that is cleared the
    /// sentence is back.
    /// </summary>
    [Fact]
    public void WhileTheSavedSettingsAreNotInForceTheBannerSaysSoWheneverItSaysNothingElse()
    {
        ReviewPageDriver.Run(driver => driver.SettingsNotInForce = NotInForce, async driver =>
        {
            await driver.Post("status", new { stage = "ready", message = "Reviewing 12 components." });
            Assert.Equal(NotInForce, (await driver.Read(Banner)).GetProperty("text").GetString());

            await driver.Post("status", new { stage = "error", message = Failure });
            Assert.Equal(Failure, (await driver.Read(Banner)).GetProperty("text").GetString());

            await driver.Post("status", new { stage = "ready", message = "Reviewing 12 components." });
            JsonElement banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(NotInForce, banner.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// A save whose restart failed before the old backend stopped: its line says the settings are
    /// saved and the backend did not restart (150A), and the `init` the page asks for after it names
    /// the old backend - the strip says it is ready - and says the saved settings are not in force
    /// yet, which the banner says.
    /// </summary>
    [Fact]
    public void ASaveWhoseRestartFailedBeforeTheOldBackendStoppedSaysTheSavedSettingsAreNotInForce()
    {
        ReviewPageDriver.Run(
            driver => driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json())),
            async driver =>
            {
                int readies = driver.Posted("ready").Length;
                driver.SettingsSaveError = NotRestarted;
                driver.SettingsNotInForce = NotInForce;

                await driver.Click("save-settings");
                await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init after the save");
                await driver.Settle();

                string line = (await driver.Read(SaveLine)).GetProperty("visible").GetString()!.Trim();
                Assert.StartsWith(LabelsSample.BackendNotRestarted, line, StringComparison.Ordinal);
                JsonElement banner = await driver.Read(Banner);
                Assert.False(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
                Assert.Equal(NotInForce, banner.GetProperty("text").GetString());
                Assert.Equal("Backend ready", (await driver.Read(Strip)).GetProperty("text").GetString());
            });
    }

    /// <summary>
    /// Once an `init` no longer says so - a save restarted the backend with the saved settings - the
    /// sentence comes off the banner and is not said again; a word the banner took meanwhile, which
    /// the engineer has not read yet, stays.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void AnInitThatNoLongerSaysSoTakesTheSentenceOffAndNothingElse(bool anotherWordMeanwhile)
    {
        ReviewPageDriver.Run(driver => driver.SettingsNotInForce = NotInForce, async driver =>
        {
            Assert.Equal(NotInForce, (await driver.Read(Banner)).GetProperty("text").GetString());
            int readies = driver.Posted("ready").Length;
            driver.SettingsNotInForce = null;
            driver.BackendToken = RestartedToken;
            driver.HoldReady = true;

            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init after the save");
            if (anotherWordMeanwhile)
            {
                await driver.Post("status", new { stage = "error", message = Failure });
            }

            await driver.ReleaseReady();

            JsonElement banner = await driver.Read(Banner);
            if (anotherWordMeanwhile)
            {
                Assert.Equal(Failure, banner.GetProperty("text").GetString());
                await driver.Post("status", new { stage = "ready", message = "Reviewing 12 components." });
                banner = await driver.Read(Banner);
            }

            Assert.True(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(string.Empty, banner.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// Found on review (S1): a restart that waited and failed before it stopped the old backend is
    /// told to the page by its `status` alone - no `init` follows it - so that `status` carries
    /// whether the saved settings are in force, and the page holds the sentence from it as from
    /// `init`. Once the failure goes from the banner - cleared by the next review's statuses - the
    /// sentence is there; it was gone, while the review ran with the settings in force (the review's
    /// probe D: the failure, then two ready statuses).
    /// </summary>
    [Fact]
    public void ARestartsFailureSayingTheSavedSettingsAreNotInForceIsHeldAsInitsWordIs()
    {
        const string Failed = "FICT the launcher could not be resolved. " + NotInForce;
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.Post("status", new { stage = "error", message = Failed, settings_not_in_force = NotInForce });
            Assert.Equal(Failed, (await driver.Read(Banner)).GetProperty("text").GetString());

            await driver.Post("status", new { stage = "ready", message = "Component availability checked; no review tokens used." });
            Assert.Equal(NotInForce, (await driver.Read(Banner)).GetProperty("text").GetString());

            await driver.Post("status", new { stage = "ready", message = "Reviewing 12 components." });
            JsonElement banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(NotInForce, banner.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// ...and one carrying null - the saved settings are the ones in force, or no backend is up -
    /// takes a sentence the page held off: once the failure goes from the banner, nothing is there.
    /// </summary>
    [Fact]
    public void ARestartsFailureSayingNothingOfTheSettingsTakesTheSentenceOff()
    {
        const string Failed = "FICT the launcher could not be resolved. Save the settings again to retry the restart.";
        ReviewPageDriver.Run(driver => driver.SettingsNotInForce = NotInForce, async driver =>
        {
            Assert.Equal(NotInForce, (await driver.Read(Banner)).GetProperty("text").GetString());

            await driver.Post("status", new { stage = "error", message = Failed, settings_not_in_force = (string?)null });
            Assert.Equal(Failed, (await driver.Read(Banner)).GetProperty("text").GetString());

            await driver.Post("status", new { stage = "ready", message = "Reviewing 12 components." });
            JsonElement banner = await driver.Read(Banner);
            Assert.True(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(string.Empty, banner.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// Found on review (C2), Codex's ordering: a save is kept and its restart waits; the `init` the page
    /// asks for after the save's reply is read while the restart waits, and says nothing; the restart
    /// then fails before it stops the old backend, and its word, saying the sentence, reaches the page
    /// before that `init`. The `init` must not take the sentence off: each carries the number of its
    /// reading, and the page takes a word only when its number is above the last it took - so the next
    /// review's ready status leaves the sentence on the banner. An `init` read since, numbered above,
    /// still takes it off.
    /// </summary>
    [Fact]
    public void AnInitReadBeforeARestartFailedCannotTakeTheFailuresSentenceOff()
    {
        const string Failed = "FICT the launcher could not be resolved. " + NotInForce;
        ReviewPageDriver.Run(driver => driver.SettingsNotInForceRevision = 1, async driver =>
        {
            int readies = driver.Posted("ready").Length;
            driver.HoldReady = true;
            driver.SettingsNotInForceRevision = 2;
            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length == readies + 1, "asked for init after the save");

            await driver.Post("status", new
            {
                stage = "error",
                message = Failed,
                settings_not_in_force = NotInForce,
                settings_not_in_force_revision = 3,
            });
            await driver.ReleaseReady();
            await driver.Post("status", new { stage = "ready", message = "Reviewing 12 components." });

            JsonElement banner = await driver.Read(Banner);
            Assert.False(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(NotInForce, banner.GetProperty("text").GetString());

            driver.SettingsNotInForceRevision = 4;
            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length == readies + 2, "asked for init after the next save");
            await driver.Settle();
            banner = await driver.Read(Banner);
            Assert.True(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
        });
    }

    /// <summary>
    /// A backend that stopped holds no settings: `backend.stopped` takes the sentence off the banner
    /// with the backend.
    /// </summary>
    [Fact]
    public void ABackendStoppedTakesTheSentenceOffTheBanner()
    {
        ReviewPageDriver.Run(driver => driver.SettingsNotInForce = NotInForce, async driver =>
        {
            Assert.Equal(NotInForce, (await driver.Read(Banner)).GetProperty("text").GetString());

            await driver.Post("backend.stopped", new { exit_code = 1, log_path = @"C:\Fictional\FICT-logs\backend.log" });

            JsonElement banner = await driver.Read(Banner);
            Assert.True(banner.GetProperty("hidden").GetBoolean(), banner.GetRawText());
            Assert.Equal(string.Empty, banner.GetProperty("text").GetString());
        });
    }
}
