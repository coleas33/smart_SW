using System.Linq;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 143A, the Review page's half, against the real page in an offscreen WebView2.
///
/// When a settings save meets a turn that started during it, the host restarts the backend once
/// no turn runs and tells the page with `backend.restarted {promise}`. Nothing else tells it: the
/// save's own reply came long before, while the old backend still ran. The new backend has a new
/// port and a new token, and the page holds the old ones from its last `init` - every call it made
/// with them would be refused - so on that message it asks `ready` again, as it does after a save
/// that restarted the backend at once, and takes the host's sentence - the `promise` - off the
/// banner, since it is no longer true once the restart is made; anything else there stays.
/// </summary>
public sealed class ReviewPageBackendRestartTests
{
    /// <summary>The host's sentence for a save a turn started during (ReviewHost, `settings.save`).</summary>
    private const string Promise = "the settings are saved; the backend restarts when the running turn ends.";

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

            await driver.Post("backend.restarted", new { promise = Promise });
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
    /// The restart takes back only its own sentence: a banner that has said something else since -
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

            await driver.Post("backend.restarted", new { promise = Promise });
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
            await driver.Post("backend.restarted", new { promise = Promise });
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
            await driver.Post("backend.restarted", new { promise = Promise });
            await driver.Until(() => driver.Posted("ready").Length > readies, "asked for init again");
            await driver.Settle();
            await driver.RunHeldTimers();
            await driver.RunHeldTimers();

            Assert.Single(driver.Posted("events.open"));
        });
    }
}
