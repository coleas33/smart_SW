using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 143A, the Review page's half, against the real page in an offscreen WebView2.
///
/// When a settings save meets a turn that started during it, the host restarts the backend once
/// no turn runs and tells the page with `backend.restarted {}`. Nothing else tells it: the save's
/// own reply came long before, while the old backend still ran. The new backend has a new port
/// and a new token, and the page holds the old ones from its last `init` - every call it made with
/// them would be refused - so on that message it asks `ready` again, as it does after a save that
/// restarted the backend at once, and clears the banner that carried the host's sentence, which
/// is no longer true once the restart is made.
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

            await driver.Post("backend.restarted", new { });
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
}
