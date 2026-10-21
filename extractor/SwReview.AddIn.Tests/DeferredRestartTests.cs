using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.EngineeringContext;
using SwReview.AddIn.Model;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.Standards;
using SwReview.AddIn.ToolService;
using SwReview.Extractor.Dump;
using Xunit;
using Xunit.Sdk;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 143A: the add-in keeps the promise the Review tab makes when a settings save
/// meets a turn that started during it - "the backend restarts when the running turn ends".
///
/// `settings.save` asks whether a turn is running before it writes anything, and the backend
/// asks again before it stops the old process (<see cref="BackendSupervisor.Restart"/>). A turn
/// the page starts in between - a follow-up, an answer or a Send goes to the backend directly -
/// leaves the settings written and saved in the host, and the restart refused. These tests
/// start that turn where it really lands: inside the model-list round trip the save makes after
/// its check and before its restart.
///
/// What they pin:
/// 1. <b>The save is kept and says so.</b> `settings.saved`, the settings on disk and saved,
///    and the sentence, word for word.
/// 2. <b>The backend restarts once no turn runs</b>, however the turn ended, once, with the
///    settings saved by then - the last of several saves - and never under a running turn.
/// 3. <b>A save when no turn runs is today's restart</b>, made at once, and it replaces a
///    restart still waiting rather than adding a second.
/// 4. <b>A new review never runs on the old backend.</b> It makes the restart first, waits for
///    one in flight, and is refused - before anything is extracted - while a turn still runs or
///    when the restart fails. It is never dropped: every refusal is an answer.
/// 5. <b>A failed restart is reported</b>, as a failed start is, and not retried behind the
///    engineer's back.
/// 6. <b>Disposing the host while a restart waits</b>, or while it is being made, leaves nothing
///    asking, restarts nothing afterwards and does not wait for the restart in flight.
/// 7. <b>The 138A marker follows the new settings</b>: the restarted backend names the new
///    provider's saved key, or none.
///
/// Owner decision 145A adds two more: <b>every other tab is told</b> of each restart the host
/// makes (section 9), and <b>a remodel run is treated as a turn</b> (section 10) - a save made
/// during one waits for it and says so, and one started while a restart waits makes it first,
/// waits for the one being made, or is refused saying what holds it back, so a restart and a run
/// never overlap. Owner decision 150A adds section 11: <b>a save whose restart fails says what is
/// true</b> - the settings are saved, the backend did not restart, why, and that saving again
/// retries it.
///
/// Owner decision 149A adds one more (section 4b): <b>a new review reads its document again</b>
/// once the backend is ready. A restart takes seconds, and the dump attaches to whatever is active
/// after it, so a review whose document changed meanwhile is refused, making nothing.
///
/// Owner decision 153A adds section 13: <b>until a restart succeeds, the settings the backend was
/// started with are in force</b>. A restart that fails before it stops the old backend leaves it up
/// with its environment; every session then takes that backend's provider, model and effort, not
/// the saved ones, and the Review tab is told the saved settings are not in force yet and that
/// saving again retries.
///
/// Owner decision 154A adds section 14: <b>the run root in force is the settings in force's</b> - the
/// one the backend that is up was started with, which moves only with a start that succeeds - so a
/// folder chosen for runs comes into force with the start that brings it in, every tab makes its runs
/// under it from then on, and a run whose folder is under another is refused before it begins.
///
/// Owner decision 152A adds section 15: <b>a session's bridge serves the review's document</b>.
/// Every start that makes a session asks which document the bridge it would hand over serves, and
/// refuses one that is not the review's, making nothing, rather than run its live checks over
/// another document.
///
/// The fakes run with no SOLIDWORKS, no Python and no provider; the one test that reads the
/// backend's real answer to "is a turn running" uses the real <see cref="BackendClient"/>
/// against a loopback listener, as <see cref="BackendClientSessionBodyTests"/> does.
/// </summary>
[Collection(StubChildrenCollection.Name)]
public sealed class DeferredRestartTests
{
    /// <summary>The Review tab's sentence for a save a turn started during, pinned word for word.</summary>
    private const string Promise = "the settings are saved; the backend restarts when the running turn ends.";

    /// <summary>A new review, or a page call that would start a turn, refused while a turn holds the restart back.</summary>
    private const string TurnHoldsIt =
        "the backend restarts with the saved settings when the running turn ends, and nothing new starts "
        + "before then. Wait for the turn to end, or press Stop, then try again.";

    /// <summary>...while a remodel run holds it back.</summary>
    private const string RemodelRunHoldsIt =
        "the backend restarts with the saved settings when the remodel run ends, and nothing new starts "
        + "before then. Wait for the run to end, then try again.";

    /// <summary>...while the backend does not answer whether a turn runs.</summary>
    private const string NoAnswerHoldsIt =
        "the review backend did not answer whether a turn is running, so it has not been restarted with "
        + "the saved settings, and nothing new starts before then. Save the settings again to restart "
        + "it, then try again.";

    /// <summary>
    /// The status the host posts when its watcher stops looking at a backend that does not answer:
    /// the restart still waits, for the next review, follow-up, remodel run or check. Since owner decision
    /// 145A it says "the saved settings", since a save during a remodel run is not one made during
    /// the turn, and names the remodel run among what makes the restart first; since owner decision 157A,
    /// which makes a check make the restart first too, it names the check (changed deliberately).
    /// </summary>
    private const string NotAnsweringYet =
        "the review backend is not answering, so it has not been restarted with the saved settings yet. "
        + "It will be before the next review, follow-up, remodel run or check, once it answers; to restart it "
        + "now, save the settings again.";

    /// <summary>The Review tab's sentence for a save made while a remodel run is in progress (owner decision 145A).</summary>
    private const string RemodelRunPromise =
        "the settings are saved; the backend restarts when the remodel run ends.";

    /// <summary>...and for one a turn also started during.</summary>
    private const string TurnAndRemodelRunPromise =
        "the settings are saved; the backend restarts when the running turn and the remodel run end.";

    /// <summary>
    /// Every sentence the Review tab may have been shown about a restart that waits, as
    /// `backend.restarted` carries them: the promises and the watcher's word that the backend is not
    /// answering. 145A's three promises first, then since owner decision 157A (changed deliberately) the
    /// eight that name a check - one, or one on each check tab - alone or with a turn, a remodel run or both.
    /// </summary>
    private static readonly string[] RestartSentences =
    {
        Promise,
        RemodelRunPromise,
        TurnAndRemodelRunPromise,
        "the settings are saved; the backend restarts when the running check ends.",
        "the settings are saved; the backend restarts when the running turn and the running check end.",
        "the settings are saved; the backend restarts when the remodel run and the running check end.",
        "the settings are saved; the backend restarts when the running turn, the remodel run and the running check end.",
        "the settings are saved; the backend restarts when the running checks end.",
        "the settings are saved; the backend restarts when the running turn and the running checks end.",
        "the settings are saved; the backend restarts when the remodel run and the running checks end.",
        "the settings are saved; the backend restarts when the running turn, the remodel run and the running checks end.",
        NotAnsweringYet,
    };

    /// <summary>
    /// A remodel run - a plan or a Start - refused while a turn holds the restart back (owner
    /// decision 145A). On the Remodel tab, whose own Stop stops the run: the turn's is on the Review tab.
    /// </summary>
    private const string TurnHoldsTheRemodelRun =
        "the backend restarts with the saved settings when the running review turn ends, and no remodel run "
        + "starts before then. Wait for the turn to end, or press Stop on the Review tab, then try again.";

    /// <summary>...while the backend does not answer whether a turn runs.</summary>
    private const string NoAnswerHoldsTheRemodelRun =
        "the review backend did not answer whether a turn is running, so it has not been restarted with the "
        + "saved settings, and no remodel run starts before then. Save the settings again on the Review tab "
        + "to restart it, then try again.";

    /// <summary>
    /// How the answer to a save whose restart failed begins, the reason after it (owner decision
    /// 150A): the settings are saved, the backend did not restart, and saving again retries it.
    /// </summary>
    private const string SavedNotRestarted =
        "the settings are saved, but the review backend did not restart with them. " + RetryTheRestart
        + " The restart failed: ";

    /// <summary>
    /// The way on after a restart for saved settings failed, whether it stopped the old backend or
    /// not: in a save's answer, and after the failure a restart that waited posts (150A review).
    /// </summary>
    private const string RetryTheRestart = "Save the settings again to retry the restart.";

    /// <summary>
    /// What the Review tab is told while the backend that is up was started with settings other than
    /// the saved ones - a restart failed before it stopped the old backend - ending with the way on
    /// (owner decision 153A), pinned word for word.
    /// </summary>
    private const string NotInForce =
        "The saved settings are not in force yet: the review backend did not restart with them, so reviews "
        + "run with the settings it was started with. " + RetryTheRestart;

    /// <summary>
    /// What the Review tab is told instead while the run root saved is not the one in force (owner decision 154A,
    /// with 153A's record): 153A's sentence, and where every tab makes its runs meanwhile - the folder for runs the
    /// backend was started with, not the one the Settings panel's field shows - pinned word for word.
    /// </summary>
    private const string NotInForceWithTheRunRoot =
        "The saved settings are not in force yet: the review backend did not restart with them, so reviews run with "
        + "the settings it was started with, and every tab makes its runs in the folder for runs it was started with, "
        + "not the one saved. " + RetryTheRestart;

    /// <summary>
    /// ...and instead while the run root in force is one the rule refuses (the reviews of 154A's merge, N4): no tab
    /// makes runs there - every start is refused - so the sentence says no run can start until the backend
    /// restarts with the settings saved, pinned word for word.
    /// </summary>
    private const string NotInForceWhileTheRunRootIsRefused =
        "The saved settings are not in force yet: the review backend did not restart with them, and no run can start "
        + "until it does, since the folder for runs it was started with is refused. " + RetryTheRestart;

    /// <summary>A restart's failure before it stops anything: the configured launcher cannot be found.</summary>
    private const string LauncherGone = "FICT the launcher could not be resolved";

    /// <summary>Fictional keys, built from fragments and in no provider's format (AGENTS.md rule 2).</summary>
    private static readonly string OpenAiKey = string.Concat("FICT", "-saved-", "openai-", "143a-0001");

    private static readonly string GeminiKey = string.Concat("FICT", "-saved-", "gemini-", "143a-0002");

    private static readonly DateTime Stamp = new DateTime(2026, 10, 19, 10, 15, 0);

    // ---- 1. the save is kept, and the pane says so --------------------------------------------

    [Fact]
    public void ASaveATurnStartedDuringIsKeptAndSaysTheBackendRestartsWhenTheTurnEnds()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");

        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        // Not refused: the settings were written before the turn could be seen, so they are the
        // saved settings (contracts/pane-host-messages.md, `settings.save`).
        Assert.Equal("low", world.Reply("settings.saved", "save").GetProperty("settings").GetProperty("effort").GetString());
        Assert.Equal("low", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
        Assert.Equal("low", world.Host.Settings.Effort);

        JsonElement status = world.Last("status");
        Assert.Equal("error", status.GetProperty("stage").GetString());
        Assert.Equal(Promise, status.GetProperty("message").GetString());
        Assert.Empty(world.Backend.Restarts);
    }

    // ---- 2. the restart, once no turn runs ----------------------------------------------------

    [Fact]
    public void NothingIsRestartedWhileTheTurnRuns()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        // The host keeps asking whether the turn has ended...
        Polls(world.Backend, 5);

        // ...and restarts nothing under it: the backend's own check is never even reached.
        Assert.Equal(0, world.Backend.Attempts);
        Assert.Empty(world.Backend.Restarts);
        Assert.Empty(world.Posted("backend.restarted"));
    }

    [Fact]
    public void OnceTheTurnEndsTheBackendRestartsOnceWithTheSavedSettingsAndThePageIsTold()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(model: "gpt-5.6-mini", effort: "low"));
        Polls(world.Backend, 2);

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");

        (UserSettings settings, ResolvedApiKey key) = Assert.Single(world.Backend.Restarts);
        Assert.Equal("gpt-5.6-mini", settings.Model);
        Assert.Equal("low", settings.Effort);
        Assert.Equal(OpenAiKey, key.Key);
        Assert.Equal("settings", key.Source);

        // One message after the restart, and nothing else: the promise is the only status, and the
        // message carries the host's sentences about the wait back - the three promises (owner
        // decision 145A) and the one for a backend that does not answer - so the page takes
        // whichever it shows, and nothing else, off its banner.
        Assert.Equal("backend.restarted", world.Types().Last());
        Assert.Equal(
            RestartSentences,
            world.Last("backend.restarted").GetProperty("sentences").EnumerateArray().Select(sentence => sentence.GetString()));
        Assert.Single(world.Posted("status"));
        world.AssertNothingPostedContains(OpenAiKey);

        // The host stops asking once the restart is made: nothing is left polling the backend.
        int asked = world.Backend.Questions;
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(asked, world.Backend.Questions);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// Owner decision 154A, the owner's follow-up (feature 002 T194): a folder chosen for runs in a save whose
    /// restart a turn holds back comes into force with that restart, not before. Until it is made, the run root
    /// in force is the one the running backend was started with, under which it still accepts a run's folder;
    /// the restart is made with the folder chosen, and brings it in.
    /// </summary>
    [Fact]
    public void AFolderChosenForRunsAsATurnStartsComesIntoForceWithTheRestart()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        string inForce = world.Host.RunRoot;
        string chosen = Path.Combine(world.Root, "chosen", "runs");
        Dictionary<string, object?> payload = Save(effort: "low");
        payload["run_root"] = chosen;

        SaveAsATurnStarts(world, "save", payload);

        Assert.Equal(chosen, world.Reply("settings.saved", "save").GetProperty("settings").GetProperty("run_root").GetString());
        Assert.Equal(chosen, world.Host.Settings.RunRoot);
        Assert.Equal(inForce, world.Host.RunRoot);

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");

        (UserSettings settings, _) = Assert.Single(world.Backend.Restarts);
        Assert.Equal(chosen, settings.RunRoot);
        Assert.Equal(chosen, world.Host.RunRoot);
    }

    /// <summary>
    /// The reviews' N8: a start judges the run root in force before it does anything, and the restart it then
    /// makes - one a save during a turn left waiting - can bring another into force; the start judges that one
    /// again before it makes its run folder there. Here the folder chosen was local when it was saved and is on
    /// a network drive by the time the restart brings it in, as a drive mapped in between would leave it.
    /// </summary>
    [Theory]
    [InlineData("review.start")]
    [InlineData("context.prepare")]
    [InlineData("review.recheck")]
    public void AStartJudgesAgainTheRunRootTheRestartItMakesBringsIn(string start)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10), Probe = probe };
        world.Open();
        world.Track("chat-1");
        world.Track("waiting");
        const string chosen = @"Y:\Fictional\runs";
        Dictionary<string, object?> payload = Save(effort: "low");
        payload["run_root"] = chosen;
        SaveAsATurnStarts(world, "save", payload);
        world.Backend.EndTurn("chat-1");
        probe.Drives[@"Y:\"] = RunRootDrive.Network;

        world.Receive(start, "start", new { chat_id = "waiting" });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
        Assert.Equal(
            RunRootRule.Refusal(RunRootVerdict.Share, "nothing was started", RunRootRule.InSettings, "try again"),
            error.GetProperty("message").GetString());
        Assert.Equal(chosen, world.Host.RunRoot);
        Assert.Single(world.Backend.Restarts);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
    }

    /// <summary>
    /// However the turn ends, the chat leaves `running`, and that is all the host reads
    /// (`GET /sessions/{chat_id}`, through the real <see cref="BackendClient"/>): a turn that
    /// ended normally or was stopped (`ended`), one that ended in an error (`failed`), one that
    /// ended asking the engineer (`waiting_engineer`) and a Send that failed back to waiting
    /// (`awaiting_send`) - the states `chat/server.py` settles a turn in (data-model section 3).
    /// The contract names none of them as a reason to keep the old settings.
    /// </summary>
    [Theory]
    [InlineData("ended")]
    [InlineData("failed")]
    [InlineData("waiting_engineer")]
    [InlineData("awaiting_send")]
    public void HoweverTheTurnEndsTheBackendRestarts(string endedAs)
    {
        using (var server = new SessionStateServer("chat-1"))
        using (var real = new RealClient(server.Port))
        {
            BackendClient client = real.Client;
            using (var world = new RestartWorld())
            {
                world.BackendOverride = new TurnsAskedOfTheRealClient(client, world.Backend);
                world.Open();
                world.Track("chat-1");
                world.Backend.DuringModelList = () =>
                {
                    server.State = "running";
                    world.Backend.StartTurn("chat-1");
                };

                world.Receive("settings.save", "save", Save(effort: "low"));
                world.Backend.DuringModelList = null;
                Assert.Equal(Promise, world.Last("status").GetProperty("message").GetString());
                Assert.True(client.IsTurnRunning("chat-1"), "the real client did not read the turn as running");

                server.State = endedAs;
                world.Backend.EndTurn("chat-1");
                Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted after " + endedAs);

                Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
            }
        }
    }

    /// <summary>
    /// The real client keeps the status the backend answered with, so the host can tell the
    /// answers that rule a turn out - `UnknownChat` (404) for a chat it does not hold,
    /// `InvalidRequest` (400) for an id it cannot read - from one that says nothing of it, such as
    /// a 500 whose body is not the backend's, and from no answer at all, which has no status.
    /// </summary>
    [Fact]
    public void TheRealClientKeepsTheStatusTheBackendAnsweredWith()
    {
        using (var server = new SessionStateServer("chat-1") { InvalidChat = "FICT-not-an-id", BrokenChat = "FICT-broken" })
        using (var answering = new RealClient(server.Port))
        {
            BackendRequestException unknown = Assert.Throws<BackendRequestException>(
                () => answering.Client.IsTurnRunning("FICT-other-chat"));
            Assert.Equal("UnknownChat", unknown.ErrorClass);
            Assert.Equal(404, unknown.Status);

            BackendRequestException invalid = Assert.Throws<BackendRequestException>(
                () => answering.Client.IsTurnRunning("FICT-not-an-id"));
            Assert.Equal("InvalidRequest", invalid.ErrorClass);
            Assert.Equal(400, invalid.Status);

            BackendRequestException broken = Assert.Throws<BackendRequestException>(
                () => answering.Client.IsTurnRunning("FICT-broken"));
            Assert.Equal("HttpError", broken.ErrorClass);
            Assert.Equal(500, broken.Status);
        }

        var probe = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        int closed = ((IPEndPoint)probe.LocalEndpoint).Port;
        probe.Stop();
        using (var silent = new RealClient(closed))
        {
            BackendRequestException missing = Assert.Throws<BackendRequestException>(
                () => silent.Client.IsTurnRunning("chat-1"));
            Assert.Equal("BackendUnavailable", missing.ErrorClass);
            Assert.Null(missing.Status);
        }
    }

    [Fact]
    public void SeveralSavesDuringOneTurnRestartTheBackendOnceWithTheLastOfThem()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "first", Save(effort: "low"));

        // A second save during the same turn gets past the save's own check only when that check
        // cannot see the turn - a question the backend does not answer reads as "no turn"
        // (ReviewHost.AnyTurnRunning) - and the backend's own check, made a model-list round
        // trip later, still refuses it. Only the save's own questions go unanswered: the host's
        // look, on its own thread, is answered throughout, as a backend that let one round trip
        // time out answers the next.
        world.Backend.LeavesUnanswered(() =>
            world.Receive("settings.save", "second", Save(model: "gpt-5.6-mini", effort: "medium")));

        Assert.Equal("medium", world.Reply("settings.saved", "second").GetProperty("settings").GetProperty("effort").GetString());
        Assert.Equal(2, world.Posted("status").Count(status => status.GetProperty("message").GetString() == Promise));
        Assert.Empty(world.Backend.Restarts);

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));

        (UserSettings settings, _) = Assert.Single(world.Backend.Restarts);
        Assert.Equal("gpt-5.6-mini", settings.Model);
        Assert.Equal("medium", settings.Effort);
        Assert.Single(world.Posted("backend.restarted"));
    }

    /// <summary>
    /// The host asks every second for as long as the turn runs, so a question the backend does not
    /// answer must not be read as "no turn": the backend's own check asks the same question, and
    /// two such readings in a row would restart the backend under the running turn. Only an
    /// answer releases the restart - here after two looks without one, fewer than the host waits
    /// out (<see cref="DeferredRestart.UnansweredLooks"/>).
    /// </summary>
    [Fact]
    public void AQuestionTheBackendDoesNotAnswerIsNeverReadAsAnEndedTurn()
    {
        using var world = new RestartWorld();
        world.Backend.CheckAsksTheSameQuestion = true;
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.StopsAnswering(questions: DeferredRestart.UnansweredLooks - 1);
        Polls(world.Backend, DeferredRestart.UnansweredLooks + 2);
        Assert.Equal(0, world.Backend.Attempts);
        Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("message").GetString() == NotAnsweringYet);

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted once answered");
        Assert.Equal(1, world.Backend.Attempts);
    }

    /// <summary>
    /// After the watcher has stopped looking, the backend answers again, the turn over: the next
    /// review - or follow-up - restarts it first, and the review runs on the restarted backend,
    /// never on the old one with the new settings. A follow-up is told its chat ended only once a
    /// restart has really been made, and the page is told of it, with every one of the host's
    /// sentences about the wait.
    /// </summary>
    [Theory]
    [InlineData("review")]
    [InlineData("follow-up")]
    public void AfterTheWatcherStopsTheNextReviewOrFollowUpRestartsTheBackendOnceItAnswers(string next)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(model: "gpt-5.6-mini", effort: "low"));
        world.Backend.StopsAnswering();
        Eventually(
            () => world.Posted("status").Any(posted => posted.GetProperty("message").GetString() == NotAnsweringYet),
            "the watcher stopping");

        world.Backend.AnswersAgain();
        world.Backend.EndTurn("chat-1");
        Assert.Empty(world.Backend.Restarts);

        if (next == "review")
        {
            world.Receive("review.start", "start", new { });

            world.Reply("review.started", "start");
            (NewSessionRequest request, int generation) = Assert.Single(world.Backend.Sessions);
            Assert.Equal(1, generation);
            Assert.Equal("gpt-5.6-mini", request.Model);
        }
        else
        {
            BackendRequestException? refusal = world.Host.PageTurnRefusal();

            Assert.NotNull(refusal);
            Assert.Equal("UnknownChat", refusal!.ErrorClass);
            Assert.Equal(ChatEndedWithTheRestart, refusal.Message);
        }

        Assert.Single(world.Backend.Restarts);
        Assert.Equal(
            RestartSentences,
            Assert.Single(world.Posted("backend.restarted")).GetProperty("sentences").EnumerateArray()
                .Select(sentence => sentence.GetString()));
    }

    /// <summary>
    /// A watcher that has stopped looking is gone, so a save refused again later starts a new one:
    /// the backend stops answering until the watcher stops, answers again, and the turn ends; a
    /// second save then meets a turn of its own, and when that turn ends the new watcher restarts
    /// the backend with it - nothing else is asking.
    /// </summary>
    [Fact]
    public void ASaveRefusedAfterTheWatcherStoppedIsWatchedByANewWatcher()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "first", Save(effort: "low"));
        world.Backend.StopsAnswering();
        Eventually(
            () => world.Posted("status").Any(posted => posted.GetProperty("message").GetString() == NotAnsweringYet),
            "the watcher stopping");
        world.Backend.AnswersAgain();
        world.Backend.EndTurn("chat-1");

        SaveAsATurnStarts(world, "second", Save(effort: "medium"));
        Assert.Empty(world.Backend.Restarts);
        world.Backend.EndTurn("chat-1");

        Eventually(() => world.Backend.Restarts.Length == 1, "a new watcher restarting the backend");
        Assert.Equal("medium", world.Backend.Restarts[0].Settings.Effort);
    }

    /// <summary>
    /// A chat the backend does not hold - a review found on disk, or one an earlier backend held -
    /// is answered `UnknownChat`, which is an answer: no turn of it runs here.
    /// </summary>
    [Fact]
    public void AChatTheBackendDoesNotHoldDoesNotHoldTheRestartBack()
    {
        using var world = new RestartWorld();
        world.Backend.Unknown.Add("found-on-disk");
        world.Open();
        world.Track("found-on-disk");
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
    }

    /// <summary>
    /// The refusals that rule a turn out, besides a readable state: 404 `UnknownChat`, a chat the
    /// backend does not hold, and 400 `InvalidRequest`, an id it could not hold. The restart is
    /// not held back by a chat answered so.
    /// </summary>
    [Theory]
    [InlineData("UnknownChat", 404)]
    [InlineData("InvalidRequest", 400)]
    public void ARefusalThatRulesATurnOutDoesNotHoldTheRestartBack(string errorClass, int status)
    {
        using var world = new RestartWorld();
        world.Backend.Refusals["FICT-odd-id"] = new BackendRequestException(
            errorClass, "FICT the backend refused this one", retryable: false, inner: null, status: status);
        world.Open();
        world.Track("FICT-odd-id");
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted past a " + status);
    }

    /// <summary>
    /// Every other answer says nothing of the turn - a 500, the backend's refusal of a chat that
    /// failed, a class answered with a status that is not its own - and holds the restart back as
    /// no answer does: the save's own check, and the backend's, read it as no turn, so the restart
    /// that waits must not. Within the bound: the watcher then stops, and says so.
    /// </summary>
    [Theory]
    [InlineData("HttpError", 500)]
    [InlineData("SessionFailed", 409)]
    [InlineData("InvalidRequest", 500)]
    [InlineData("UnknownChat", 400)]
    public void AnyOtherAnswerLeavesTheTurnUnknownAndHoldsTheRestartBack(string errorClass, int status)
    {
        using var world = new RestartWorld();
        world.Backend.Refusals["FICT-odd-id"] = new BackendRequestException(
            errorClass, "FICT the backend refused this one", retryable: false, inner: null, status: status);
        world.Open();
        world.Track("FICT-odd-id");
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        int asked = world.Backend.RestartsAsked;

        world.Backend.EndTurn("chat-1");
        Eventually(
            () => world.Posted("status").Any(posted => posted.GetProperty("message").GetString() == NotAnsweringYet),
            "the watcher stopping, held back by a " + status);
        Assert.Equal(asked, world.Backend.RestartsAsked);
        Assert.Empty(world.Posted("backend.restarted"));
    }

    /// <summary>
    /// A backend that answers 500 to the turn question while a turn runs is never restarted under
    /// it: the 500 is no answer, so the host never asks the backend to restart - whose own check,
    /// as lenient as the save's, would read the same 500 as no turn and let it through.
    /// </summary>
    [Fact]
    public void ABackendThatAnswers500DuringATurnIsNeverAskedToRestartUnderIt()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        int asked = world.Backend.RestartsAsked;

        world.Backend.Refuses("chat-1", new BackendRequestException(
            "HttpError", "the backend answered 500.", retryable: true, inner: null, status: 500));
        Eventually(
            () => world.Posted("status").Any(posted => posted.GetProperty("message").GetString() == NotAnsweringYet),
            "the watcher stopping");

        // Only the save itself asked, and was refused for the turn it saw.
        Assert.Equal(asked, world.Backend.RestartsAsked);
        Assert.Empty(world.Backend.Restarts);
    }

    /// <summary>
    /// A backend that has stopped answering is watched, but not for ever: after
    /// <see cref="DeferredRestart.UnansweredLooks"/> looks in a row without an answer the watcher
    /// stops, restarts nothing, and tells the engineer so - and how to go on. The restart still
    /// waits: a turn call is refused, saying the backend does not answer, rather than sent to the
    /// old backend. Saving the settings again restarts it, once the save's round trips have timed
    /// out: the save's own check, and the backend's, read a missing answer as no turn.
    /// </summary>
    [Fact]
    public void ABackendThatStopsAnsweringIsWatchedForABoundedTimeThenTheEngineerIsToldHowToGoOn()
    {
        using var world = new RestartWorld();
        world.Backend.CheckAsksTheSameQuestion = true;
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.StopsAnswering();
        Eventually(
            () => world.Posted("status").Any(status => status.GetProperty("message").GetString() == NotAnsweringYet),
            "the status that the host stopped waiting");

        JsonElement status = world.Last("status");
        Assert.Equal("error", status.GetProperty("stage").GetString());
        Assert.Equal(NotAnsweringYet, status.GetProperty("message").GetString());
        Assert.Equal(0, world.Backend.Attempts);
        Assert.Empty(world.Posted("backend.restarted"));

        // The watcher has gone, so nothing asks of its own accord...
        int asked = world.Backend.Questions;
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(asked, world.Backend.Questions);

        // ...but the restart still waits: a turn call looks once, and is refused while the
        // backend still does not answer, rather than sent to the old backend.
        BackendRequestException? refusal = world.Host.PageTurnRefusal();
        Assert.NotNull(refusal);
        Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
        Assert.Equal(NoAnswerHoldsIt, refusal.Message);
        Assert.Equal(asked + 1, world.Backend.Questions);

        world.Receive("settings.save", "again", Save(effort: "medium"));

        Assert.Equal("medium", Assert.Single(world.Backend.Restarts).Settings.Effort);
        world.Reply("settings.saved", "again");
        Assert.Single(world.Posted("status"), posted => posted.GetProperty("message").GetString() == NotAnsweringYet);
    }

    /// <summary>
    /// With no backend process at all nothing can be running on it, and the restart is what brings
    /// one back with the saved settings.
    /// </summary>
    [Fact]
    public void WithNoBackendAtAllTheRestartIsMadeToBringOneBack()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.EndTurn("chat-1");
        world.Backend.Down = true;
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
        Assert.NotNull(world.Backend.Endpoint);
    }

    /// <summary>
    /// A remodel run in progress holds the restart back as a turn does: the backend runs it, and a
    /// restart would end it with the copy half changed. Before 143A only a save the engineer made
    /// could restart the backend; the host's own restart must not end a run the engineer started.
    /// </summary>
    [Fact]
    public void ARemodelRunInProgressHoldsTheRestartBackUntilItEnds()
    {
        bool remodelling = true;
        int asked = 0;
        using var world = new RestartWorld
        {
            BackendBusy = () =>
            {
                Interlocked.Increment(ref asked);
                return Volatile.Read(ref remodelling);
            },
        };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        // A remodel run is known without asking the backend, and is looked at first.
        world.Backend.EndTurn("chat-1");
        int from = Volatile.Read(ref asked);
        Eventually(() => Volatile.Read(ref asked) >= from + 5, "5 more looks at the remodel run");
        Assert.Equal(0, world.Backend.Attempts);

        Volatile.Write(ref remodelling, false);
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted after the run");
    }

    // ---- 3. a save when no turn runs is today's restart ---------------------------------------

    /// <summary>
    /// The path every save took before 143A, unchanged: the restart is made within the save and
    /// before its reply, the reply is what tells the page, and nothing is left asking.
    /// </summary>
    [Fact]
    public void ASaveWhenNoTurnRunsRestartsTheBackendAtOnceAsBefore()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");

        world.Receive("settings.save", "save", Save(effort: "low"));

        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
        Assert.Equal(1, world.Backend.Generation);
        world.Reply("settings.saved", "save");
        Assert.Empty(world.Posted("status"));
        Assert.Empty(world.Posted("backend.restarted"));

        int asked = world.Backend.Questions;
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(asked, world.Backend.Questions);
    }

    /// <summary>
    /// A save made after the turn has ended, before the host has noticed, is a save when no turn
    /// runs: it restarts the backend at once with its own settings, and that is the restart the
    /// earlier save was waiting for - a review started next runs on that backend with no second
    /// restart.
    /// </summary>
    [Fact]
    public void ASaveOnceTheTurnHasEndedReplacesTheRestartThatWaited()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "first", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("settings.save", "second", Save(effort: "medium"));

        Assert.Equal("medium", Assert.Single(world.Backend.Restarts).Settings.Effort);
        world.Reply("settings.saved", "second");

        world.Receive("review.start", "start", new { });
        world.Reply("review.started", "start");
        Assert.Equal(1, Assert.Single(world.Backend.Sessions).Generation);
        Assert.Single(world.Backend.Restarts);
    }

    // ---- 4. a new review never runs on the old backend ----------------------------------------

    [Fact]
    public void ANewReviewTheMomentTheTurnEndsRestartsTheBackendFirstAndRunsOnIt()
    {
        // A poll long enough that the review gets there before the host's own look does.
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(model: "gpt-5.6-mini", effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("review.start", "start", new { });

        world.Reply("review.started", "start");
        (NewSessionRequest request, int generation) = Assert.Single(world.Backend.Sessions);
        Assert.Equal(1, generation);
        Assert.Equal("gpt-5.6-mini", request.Model);
        Assert.Equal("low", request.Effort);
        Assert.Single(world.Backend.Restarts);

        string[] types = world.Types();
        Assert.True(
            Array.IndexOf(types, "backend.restarted") >= 0
                && Array.IndexOf(types, "backend.restarted") < Array.IndexOf(types, "review.started"),
            "the page was not told of the restart before the review it carries: " + string.Join(" | ", types));
    }

    [Fact]
    public void ARecheckTheMomentTheTurnEndsRunsOnTheRestartedBackendToo()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        world.Track("waiting");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("review.recheck", "recheck", new { chat_id = "waiting" });

        world.Reply("review.rechecked", "recheck");
        (NewSessionRequest request, int generation) = Assert.Single(world.Backend.Sessions);
        Assert.Equal(1, generation);
        Assert.Equal(ReviewMode.Recheck, request.Mode);
        Assert.Equal("low", request.Effort);
    }

    [Fact]
    public void ANewReviewWhileTheTurnStillRunsIsRefusedBeforeAnythingIsExtracted()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("TurnRunning", error.GetProperty("error_class").GetString());
        Assert.Equal(TurnHoldsIt, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        Assert.Empty(world.Backend.Restarts);

        // The refusal leaves the restart waiting, and it is made when the turn ends.
        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// A remodel run that holds the restart back holds a new review back too: the review cannot
    /// run on the old backend, and the restart cannot be made under the run. The refusal names
    /// the run, under a class whose next step is true of it - not `TurnRunning`, whose words send
    /// the engineer to a Stop button there is no turn for.
    /// </summary>
    [Fact]
    public void ANewReviewWhileARemodelRunHoldsTheRestartIsRefusedBeforeAnythingIsExtracted()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10), BackendBusy = () => true };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("RemodelRunning", error.GetProperty("error_class").GetString());
        Assert.Equal(RemodelRunHoldsIt, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(0, world.Backend.Attempts);
    }

    /// <summary>
    /// ...and while the backend does not answer whether a turn runs, the refusal says that, under
    /// the class whose next step is the way on: saving the settings again restarts it.
    /// </summary>
    [Fact]
    public void ANewReviewWhileTheBackendDoesNotAnswerIsRefusedSayingSo()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        world.Backend.StopsAnswering(questions: 1);

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
        Assert.Equal(NoAnswerHoldsIt, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(0, world.Backend.Attempts);

        // The refusal left the restart waiting: answered again, the next review makes it first and
        // runs on the restarted backend.
        world.Receive("review.start", "again", new { });
        world.Reply("review.started", "again");
        Assert.Equal(1, Assert.Single(world.Backend.Sessions).Generation);
    }

    /// <summary>
    /// A remodel run is named before a backend that does not answer: the add-in knows of the run
    /// without asking the backend, and the way on from a backend that does not answer - saving
    /// the settings again, which restarts it at once - would end the run. So while the run lasts
    /// the host waits for it, and does not stop waiting for want of an answer.
    /// </summary>
    [Fact]
    public void ARemodelRunIsNamedBeforeABackendThatDoesNotAnswer()
    {
        int looks = 0;
        using var world = new RestartWorld
        {
            BackendBusy = () =>
            {
                Interlocked.Increment(ref looks);
                return true;
            },
        };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        world.Backend.StopsAnswering();

        int from = Volatile.Read(ref looks);
        Eventually(() => Volatile.Read(ref looks) >= from + DeferredRestart.UnansweredLooks * 3, "the host's looks");

        Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("message").GetString() == NotAnsweringYet);
        world.Receive("review.start", "start", new { });
        JsonElement error = world.Reply("error", "start");
        Assert.Equal("RemodelRunning", error.GetProperty("error_class").GetString());
        Assert.Equal(0, world.Dump.Runs);
    }

    /// <summary>
    /// A review with saved engineering context (feature 016) starts through the same session path:
    /// prepared before the save, and reviewed the moment the turn ends, it runs on the restarted
    /// backend.
    /// </summary>
    [Fact]
    public void AContextReviewTheMomentTheTurnEndsRunsOnTheRestartedBackendToo()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        world.Receive("context.prepare", "prepare", new { });
        JsonElement prepared = world.Reply("context.prepared", "prepare");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("context.review", "review", new
        {
            run_id = prepared.GetProperty("run_id").GetString(),
            context_id = Guid.NewGuid().ToString(),
            head_digest = new string('a', 64),
            package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        });

        world.Reply("review.started", "review");
        (NewSessionRequest request, int generation) = Assert.Single(world.Backend.Sessions);
        Assert.Equal(1, generation);
        Assert.NotNull(request.EngineeringContext);
        Assert.Equal("low", request.Effort);
    }

    /// <summary>
    /// An engineering context request checks the backend before it reads anything (feature 016,
    /// `ContextReady`), so it makes the restart first too: preparing context the moment the turn
    /// ends restarts the backend before the dump begins.
    /// </summary>
    [Fact]
    public void AContextPreparationTheMomentTheTurnEndsRestartsTheBackendBeforeItsDump()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        int restartsAtTheDump = -1;
        world.Dump.OnRun = () => restartsAtTheDump = world.Backend.Restarts.Length;
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("context.prepare", "prepare", new { });

        world.Reply("context.prepared", "prepare");
        Assert.Equal(1, restartsAtTheDump);
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
    }

    /// <summary>...and reading the selection against prepared context restarts it before the selection is read.</summary>
    [Fact]
    public void AContextSelectionTheMomentTheTurnEndsRestartsTheBackendBeforeTheSelectionIsRead()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        int restartsAtTheRead = -1;
        world.Selection.OnCapture = () => restartsAtTheRead = world.Backend.Restarts.Length;
        world.Open();
        world.Track("chat-1");
        world.Receive("context.prepare", "prepare", new { });
        JsonElement prepared = world.Reply("context.prepared", "prepare");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("context.selection", "select", new
        {
            run_id = prepared.GetProperty("run_id").GetString(),
            package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        });

        world.Reply("context.selected", "select");
        Assert.Equal(1, restartsAtTheRead);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// While something holds the restart back, an engineering context request is refused before
    /// anything is read - no dump, no selection - and says what holds it: a turn (refused by the
    /// request's own check, as before 143A), a remodel run, or a backend that does not answer.
    /// </summary>
    [Theory]
    [InlineData("context.prepare", "turn")]
    [InlineData("context.prepare", "remodel run")]
    [InlineData("context.prepare", "no answer")]
    [InlineData("context.selection", "turn")]
    [InlineData("context.selection", "remodel run")]
    [InlineData("context.selection", "no answer")]
    public void AContextRequestWhileTheRestartIsHeldBackIsRefusedBeforeAnythingIsRead(string request, string cause)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        object payload = new { };
        if (request == "context.selection")
        {
            world.Receive("context.prepare", "prepare", new { });
            JsonElement prepared = world.Reply("context.prepared", "prepare");
            payload = new
            {
                run_id = prepared.GetProperty("run_id").GetString(),
                package_sha256 = prepared.GetProperty("package_sha256").GetString(),
            };
        }

        int dumps = world.Dump.Runs;
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        string expectedClass;
        string expectedMessage;
        switch (cause)
        {
            case "turn":
                expectedClass = "TurnRunning";
                expectedMessage = "Stop the running review before changing engineering context.";
                break;

            case "remodel run":
                world.Backend.EndTurn("chat-1");
                world.BackendBusy = () => true;
                expectedClass = "RemodelRunning";
                expectedMessage = RemodelRunHoldsIt;
                break;

            default:
                world.Backend.EndTurn("chat-1");
                world.Backend.StopsAnswering();
                expectedClass = "BackendUnavailable";
                expectedMessage = NoAnswerHoldsIt;
                break;
        }

        world.Receive(request, "asked", payload);

        JsonElement error = world.Reply("error", "asked");
        Assert.Equal(expectedClass, error.GetProperty("error_class").GetString());
        Assert.Equal(expectedMessage, error.GetProperty("message").GetString());
        Assert.Equal(dumps, world.Dump.Runs);
        Assert.Equal(0, world.Selection.Captures);
        Assert.Equal(0, world.Backend.Attempts);
    }

    [Fact]
    public void ANewReviewWhileTheRestartIsBeingMadeWaitsForItAndRunsOnTheNewBackend()
    {
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Backend.Hold = hold;
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the host never began the restart");

            var start = new Caller<bool>(() =>
            {
                world.Receive("review.start", "start", new { });
                return true;
            });
            Assert.False(start.Finishes(TimeSpan.FromMilliseconds(300)), "the review did not wait for the restart being made");
            Assert.Empty(world.Backend.Sessions);

            hold.Set();
            Assert.True(start.Finishes(TimeSpan.FromSeconds(10)), "the review never went on after the restart");
            Assert.True(start.Result);
            world.Reply("review.started", "start");
            Assert.Equal(1, Assert.Single(world.Backend.Sessions).Generation);
            Assert.Single(world.Backend.Restarts);
        }
        finally
        {
            hold.Set();
        }
    }

    [Fact]
    public void ANewReviewWhoseRestartFailsIsRefusedWithThatFailure()
    {
        const string Failure = "the backend exited with code 2 before printing its handshake line";
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Backend.RestartFailure = new BackendStartException(Failure);
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
        Assert.Equal(Failure, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        // The status the restart's failure posted carries the way on after it (150A review); the
        // refusal carries the failure alone, its class's sentence naming the way on.
        JsonElement status = world.Last("status");
        Assert.Equal("error", status.GetProperty("stage").GetString());
        Assert.Equal(Failure + ". " + RetryTheRestart, status.GetProperty("message").GetString());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
    }

    // ---- 4b. a new review reads its document again (owner decision 149A) -----------------------

    /// <summary>
    /// What a new review is refused with when the active document changed after the review was
    /// asked for (owner decision 149A), pinned word for word. It names no path.
    /// </summary>
    private const string DocumentChangedWords =
        "the active document or its configuration changed after the review was asked for, so nothing "
        + "was extracted and no run folder was made. Make the part or assembly you want reviewed the "
        + "active document, then press Review again.";

    /// <summary>
    /// A new review reads the active document before the restart it makes first, and the dump
    /// attaches to whatever is active after it: a restart takes seconds, in which the engineer can
    /// make another document active, and the run folder named for one document would hold
    /// another's evidence. So the review reads its document again once the backend is ready, by the
    /// pane's one rule for "the same document", and refuses one that changed - another document,
    /// another configuration of it, none at all, or a drawing - `DocumentChanged`, retryable, in
    /// words that name no path: nothing is extracted, no run folder is made and no session is
    /// created. The restart it made stands, and nothing is left held: pressed again with its
    /// document active, the review runs on the restarted backend, which is not restarted again.
    /// </summary>
    [Theory]
    [InlineData("another document")]
    [InlineData("another configuration")]
    [InlineData("no document")]
    [InlineData("a drawing")]
    public void ANewReviewWhoseDocumentChangedDuringTheRestartItMadeIsRefusedAndMakesNothing(string change)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        PageDocument pressed = world.Document!;
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        string[] folders = FoldersUnderTheRunRoot(world);
        world.Backend.DuringRestart = () => world.Document = Changed(pressed, change);

        world.Receive("review.start", "start", new { });

        AssertRefusedForADocumentThatChanged(world, "start", folders, pressed);
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
        Assert.Single(world.Posted("backend.restarted"));

        world.Backend.DuringRestart = null;
        world.Document = pressed;
        world.Receive("review.start", "again", new { });

        world.Reply("review.started", "again");
        Assert.Equal(1, Assert.Single(world.Backend.Sessions).Generation);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// ...and so is one whose document changed while it waited for the restart another caller was
    /// making - the watcher's here. The restart it waited for is made, and is its answer; the
    /// document is read again after it.
    /// </summary>
    [Fact]
    public void ANewReviewWhoseDocumentChangedWhileItWaitedForTheRestartIsRefusedAndMakesNothing()
    {
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Backend.Hold = hold;
            world.Open();
            world.Track("chat-1");
            PageDocument pressed = world.Document!;
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the host never began the restart");
            string[] folders = FoldersUnderTheRunRoot(world);
            int reads = world.DocumentReads;

            var start = new Caller<bool>(() =>
            {
                world.Receive("review.start", "start", new { });
                return true;
            });
            Eventually(() => world.DocumentReads > reads, "the review's first reading of its document");
            world.Document = Changed(pressed, "another document");
            Assert.False(start.Finishes(TimeSpan.FromMilliseconds(300)), "the review did not wait for the restart being made");

            hold.Set();
            Assert.True(start.Finishes(TimeSpan.FromSeconds(10)), "the review never went on after the restart");
            Assert.True(start.Result);
            AssertRefusedForADocumentThatChanged(world, "start", folders, pressed);
            Assert.Single(world.Backend.Restarts);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// A Retry of a review started without saved context is a new review in a run folder of its own
    /// (`review.start` with `retry_of`), so it extracts afresh and is read again as any new review is.
    /// </summary>
    [Fact]
    public void ARetryWhoseDocumentChangedDuringTheRestartIsRefusedAsANewReviewIs()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        world.Track("failed");
        PageDocument pressed = world.Document!;
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        string[] folders = FoldersUnderTheRunRoot(world);
        world.Backend.DuringRestart = () => world.Document = Changed(pressed, "another document");

        world.Receive("review.start", "retry", new { retry_of = "failed" });

        AssertRefusedForADocumentThatChanged(world, "retry", folders, pressed);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// The document is read again once the backend is ready whether or not a restart waited - one
    /// rule, as Plan's on the Remodel tab is, and true of any change between the two readings. With
    /// nothing waiting nothing is restarted or asked, and a document that changed between them is
    /// refused as above.
    /// </summary>
    [Fact]
    public void ANewReviewReadsItsDocumentAgainOnceTheBackendIsReadyWithNoRestartWaitingToo()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        PageDocument pressed = world.Document!;
        string[] folders = FoldersUnderTheRunRoot(world);
        int before = world.DocumentReads;
        world.DocumentAtRead = read => read == before + 1 ? pressed : Changed(pressed, "another document");

        world.Receive("review.start", "start", new { });

        AssertRefusedForADocumentThatChanged(world, "start", folders, pressed);
        Assert.True(world.DocumentReads >= before + 2, "the document was not read again: " + (world.DocumentReads - before));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.Equal(0, world.Backend.Questions);
        Assert.Empty(world.Posted("backend.restarted"));
    }

    /// <summary>
    /// The same document however its path is spelled is not a change: Windows names one file however
    /// it is cased, and the rule is the pane's one rule for "the same document"
    /// (<see cref="PageDocument.IsSameDocument(PageDocument)"/>). Such a review runs, on the
    /// restarted backend, and is of the document read when it was asked for.
    /// </summary>
    [Fact]
    public void ANewReviewWhoseDocumentIsTheSameHoweverItsPathIsSpelledRunsOnTheRestartedBackend()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        PageDocument pressed = world.Document!;
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        world.Backend.DuringRestart = () => world.Document = Changed(pressed, "spelled otherwise");

        world.Receive("review.start", "start", new { });

        JsonElement started = world.Reply("review.started", "start");
        Assert.Equal(1, Assert.Single(world.Backend.Sessions).Generation);
        Assert.Equal(1, world.Dump.Runs);
        Assert.Equal(pressed.Path, started.GetProperty("document").GetProperty("path").GetString());
    }

    /// <summary>
    /// A new review the add-in starts as it always does, through a preparation (`review.prepare`,
    /// then `review.start` with its `preparation_id`), reads its document again too: the
    /// preparation is checked against the first reading, before the restart, and the second reading
    /// comes after it.
    /// </summary>
    [Fact]
    public void APreparedReviewWhoseDocumentChangedDuringTheRestartIsRefusedAndMakesNothing()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10), Prepares = true };
        world.Open();
        world.Track("chat-1");
        PageDocument pressed = world.Document!;
        world.Receive("review.prepare", "prepare", new { });
        string preparation = world.Reply("review.prepared", "prepare").GetProperty("preparation_id").GetString()!;
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        string[] folders = FoldersUnderTheRunRoot(world);
        world.Backend.DuringRestart = () => world.Document = Changed(pressed, "another document");

        world.Receive("review.start", "start", new { preparation_id = preparation });

        AssertRefusedForADocumentThatChanged(world, "start", folders, pressed);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// A Recheck (feature 015) extracts nothing and asks the seat nothing: it re-runs the checks on
    /// the evidence saved in its own run folder and carries the first run's live detection over
    /// rather than detecting again (015 `contracts/recheck.md` section 3). A document made active
    /// during the restart it makes cannot put another document's evidence in its folder, so it does
    /// not read its document again (owner decision 149A; research). Pinned, so that a change to it -
    /// a dump, a live call, or a reading after the gate - is deliberate.
    /// </summary>
    [Fact]
    public void ARecheckRunsOnItsSavedEvidenceWhateverIsActiveAfterTheRestart()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        world.Track("waiting");
        PageDocument pressed = world.Document!;
        int sessions = world.Backend.Sessions.Length;
        string[] folders = FoldersUnderTheRunRoot(world);
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        world.Backend.DuringRestart = () => world.Document = Changed(pressed, "another document");

        world.Receive("review.recheck", "again", new { chat_id = "waiting" });

        world.Reply("review.rechecked", "again");
        (NewSessionRequest request, int generation) = world.Backend.Sessions.Last();
        Assert.Equal(sessions + 1, world.Backend.Sessions.Length);
        Assert.Equal(1, generation);
        Assert.Equal(ReviewMode.Recheck, request.Mode);
        Assert.Equal(Path.Combine(world.Settings.RunRoot, "20261019-101500-waiting"), request.RunDirectory);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Equal(folders, FoldersUnderTheRunRoot(world));
    }

    /// <summary>
    /// What a context review's Retry is refused with when the review's document is not the active
    /// one (owner decision 108A), pinned word for word.
    /// </summary>
    private const string ContextRetryNotActiveWords =
        "Open or switch to the reviewed document and configuration before retrying its review with saved context.";

    /// <summary>
    /// A context review's Retry (owner decision 108A) extracts nothing, but its session is more than
    /// its saved evidence: every pane review runs its checks first, a Retry carries none of them
    /// over, and the first of them, the live interference check, runs over the bridge the session is
    /// given - the tool service's, which follows the active document - and writes its rows into the
    /// review's package (owner decision 149A, found on review). A document made active during the
    /// restart would have that check run over it, and its rows judged as this review's. So the Retry
    /// reads its document again once the backend is ready, and refuses one that changed as it
    /// refuses one active when Retry is pressed: `ReviewNotActive`, retryable, in the same words,
    /// since the way on is the review's own document and Retry, which keeps the saved context.
    /// Nothing is created; the restart stands; pressed again with its document active, the Retry
    /// runs on the restarted backend, in its own folder, with its saved context.
    /// </summary>
    [Fact]
    public void AContextReviewsRetryWhoseDocumentChangedDuringTheRestartIsRefusedAsWhenPressedOnAnother()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        PageDocument pressed = world.Document!;
        world.Receive("context.prepare", "prepare", new { });
        JsonElement prepared = world.Reply("context.prepared", "prepare");
        world.Receive("context.review", "review", new
        {
            run_id = prepared.GetProperty("run_id").GetString(),
            context_id = Guid.NewGuid().ToString(),
            head_digest = new string('a', 64),
            package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        });
        JsonElement first = world.Reply("review.started", "review");
        string chatId = first.GetProperty("chat_id").GetString()!;
        string runDirectory = first.GetProperty("run_dir").GetString()!;

        world.Document = Changed(pressed, "another document");
        world.Receive("review.start", "pressed on another", new { retry_of = chatId });
        JsonElement whenPressed = world.Reply("error", "pressed on another");
        world.Document = pressed;

        int dumps = world.Dump.Runs;
        int sessions = world.Backend.Sessions.Length;
        string[] folders = FoldersUnderTheRunRoot(world);
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        world.Backend.DuringRestart = () => world.Document = Changed(pressed, "another document");

        world.Receive("review.start", "retry", new { retry_of = chatId });

        JsonElement error = world.Reply("error", "retry");
        Assert.Equal("ReviewNotActive", error.GetProperty("error_class").GetString());
        Assert.Equal(ContextRetryNotActiveWords, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(whenPressed.GetRawText(), error.GetRawText());
        Assert.Equal(sessions, world.Backend.Sessions.Length);
        Assert.Equal(dumps, world.Dump.Runs);
        Assert.Equal(folders, FoldersUnderTheRunRoot(world));
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);

        world.Backend.DuringRestart = null;
        world.Document = pressed;
        world.Receive("review.start", "again", new { retry_of = chatId });

        world.Reply("review.started", "again");
        (NewSessionRequest request, int generation) = world.Backend.Sessions.Last();
        Assert.Equal(sessions + 1, world.Backend.Sessions.Length);
        Assert.Equal(1, generation);
        Assert.Equal(runDirectory, request.RunDirectory);
        Assert.NotNull(request.EngineeringContext);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>The run folders under the run root, in a stable order.</summary>
    private static string[] FoldersUnderTheRunRoot(RestartWorld world) =>
        Directory.GetDirectories(world.Settings.RunRoot).OrderBy(folder => folder, StringComparer.Ordinal).ToArray();

    /// <summary>The active document after <paramref name="change"/>, from the one the review was asked for.</summary>
    private static PageDocument? Changed(PageDocument pressed, string change)
    {
        switch (change)
        {
            case "another document":
                return new PageDocument(@"C:\Fictional\FICT-frame\FICT-frame.SLDASM", pressed.Configuration);

            case "another configuration":
                return new PageDocument(pressed.Path, "FICT-machined");

            case "a drawing":
                return new PageDocument(Path.ChangeExtension(pressed.Path, ".SLDDRW"), null);

            case "spelled otherwise":
                return new PageDocument(pressed.Path.ToUpperInvariant(), pressed.Configuration);

            case "no document":
                return null;

            default:
                throw new ArgumentOutOfRangeException(nameof(change), change, "no such change");
        }
    }

    /// <summary>
    /// The review was refused `DocumentChanged`, retryable, in its words - which name no path - and
    /// left nothing half made: no dump, no run folder, no session, and nothing said of an extraction.
    /// </summary>
    private static void AssertRefusedForADocumentThatChanged(
        RestartWorld world, string id, string[] folders, PageDocument pressed)
    {
        JsonElement error = world.Reply("error", id);
        Assert.Equal("DocumentChanged", error.GetProperty("error_class").GetString());
        string message = error.GetProperty("message").GetString()!;
        Assert.Equal(DocumentChangedWords, message);
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.DoesNotContain(@":\", message, StringComparison.Ordinal);
        Assert.DoesNotContain(Path.GetFileNameWithoutExtension(pressed.Path), message, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(folders, FoldersUnderTheRunRoot(world));
        Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("stage").GetString() == "extracting");
    }

    // ---- 5. a failed restart is reported ------------------------------------------------------

    [Fact]
    public void ARestartThatFailsIsReportedAsAFailedStartIsAndNotTriedAgain()
    {
        using var world = new RestartWorld();
        string failure = "the backend did not answer /health within 30 seconds. See the log at "
            + Path.Combine(world.Root, "logs", "backend-20261019-101500.log") + ".";
        world.Backend.RestartFailure = new BackendStartException(failure);
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("status").Length == 2, "the failure's status");

        // As a failed start is reported, with the way on after it (150A review).
        JsonElement reported = world.Last("status");
        Assert.Equal("error", reported.GetProperty("stage").GetString());
        Assert.Equal(failure + " " + RetryTheRestart, reported.GetProperty("message").GetString());
        Assert.Empty(world.Posted("backend.restarted"));

        // Not retried: the next save is the engineer's retry, as after any failed start.
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(1, world.Backend.Attempts);
    }

    /// <summary>
    /// Anything the restart throws is reported, not only a failed start: the host carries the
    /// restart out on a thread of its own, where an exception would end SOLIDWORKS and a caught
    /// one nobody reported would be the silence 143A removes. The message is masked like every
    /// other (FR-015).
    /// </summary>
    [Fact]
    public void AnyFailureOfTheRestartIsReportedWithTheKeyMasked()
    {
        using var world = new RestartWorld();
        world.Backend.RestartFailure = new InvalidOperationException(
            "the job object refused the child started with " + OpenAiKey);
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("status").Length == 2, "the failure's status");

        string message = world.Last("status").GetProperty("message").GetString()!;
        Assert.StartsWith("the job object refused the child started with ", message, StringComparison.Ordinal);
        Assert.Contains(Redaction.Mask, message, StringComparison.Ordinal);
        world.AssertNothingPostedContains(OpenAiKey);
        Assert.Empty(world.Posted("backend.restarted"));
    }

    // ---- 6. the pane or the add-in going away -------------------------------------------------

    [Fact]
    public void DisposingTheHostWhileARestartWaitsStopsAskingAndRestartsNothing()
    {
        var world = new RestartWorld();
        try
        {
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            Polls(world.Backend, 2);

            var clock = Stopwatch.StartNew();
            world.Host.Dispose();
            // Bounded, not instant: a loaded test run can be slow to schedule the watcher. That it
            // stopped is what the questions below show.
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(5), "disposing the host waited " + clock.Elapsed);

            int asked = world.Backend.Questions;
            world.Backend.EndTurn("chat-1");
            Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
            Assert.Equal(asked, world.Backend.Questions);
            Assert.Equal(0, world.Backend.Attempts);
        }
        finally
        {
            world.Dispose();
        }
    }

    [Fact]
    public void DisposingTheHostWhileTheRestartIsBeingMadeDoesNotWaitForItAndNothingFollows()
    {
        var hold = new ManualResetEventSlim(false);
        var world = new RestartWorld();
        try
        {
            world.Backend.Hold = hold;
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the host never began the restart");

            // Bounded, like the page pumps: the restart is the backend client's to see out on
            // unload (BackendClient.Dispose takes the same gate), not the host's.
            var clock = Stopwatch.StartNew();
            world.Host.Dispose();
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(5), "disposing the host waited " + clock.Elapsed);

            hold.Set();
            Eventually(() => world.Backend.Restarts.Length == 1, "the restart in flight to finish");
            Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
            Assert.Equal(1, world.Backend.Attempts);
        }
        finally
        {
            hold.Set();
            world.Dispose();
        }
    }

    [Fact]
    public void APageThatReloadsWhileARestartWaitsLeavesItWaitingAndIsToldWhenItIsMade()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Receive("ready", "reload", new { });
        world.Reply("init", "reload");

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
        Assert.Single(world.Backend.Restarts);
    }

    // ---- 7. the 138A marker follows the new settings ------------------------------------------

    /// <summary>
    /// The restart is built from the settings saved when it is made - here a switch from
    /// OpenAI to Gemini saved during the turn - with the key resolved from them then, through the
    /// real <see cref="BackendClient.StartOptions"/>. With a Gemini key typed in, the backend is
    /// started with it under Gemini's variables and names Gemini as the saved key's provider, so
    /// a Gemini session records `key_source: settings`; with none, the stored OpenAI key was
    /// retired by the switch and nothing is named (owner decision 138A). The OpenAI key goes
    /// nowhere either way.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void TheRestartedBackendNamesTheNewProvidersSavedKeyOrNone(bool withKey)
    {
        using var world = new RestartWorld();
        world.Backend.Options = (settings, key) => RealStartOptions(world, settings, key);
        world.Open();
        world.Track("chat-1");

        SaveAsATurnStarts(world, "save", Save(
            provider: "gemini", model: "gemini-3.5-flash", apiKey: withKey ? GeminiKey : null));
        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");

        BackendStartOptions started = Assert.Single(world.Backend.Started);
        Assert.False(started.Environment.ContainsKey("OPENAI_API_KEY"));
        Assert.DoesNotContain(OpenAiKey, started.Secrets);
        if (withKey)
        {
            Assert.Equal("gemini", started.SettingsKeyProvider);
            Assert.Equal(GeminiKey, started.Environment["GOOGLE_API_KEY"]);
            Assert.Equal(GeminiKey, started.Environment["GEMINI_API_KEY"]);
        }
        else
        {
            Assert.Null(started.SettingsKeyProvider);
            Assert.False(started.Environment.ContainsKey("GOOGLE_API_KEY"));
            Assert.False(started.Environment.ContainsKey("GEMINI_API_KEY"));
        }
    }

    // ---- 8. a page call that would start a turn (the proxy's question) -------------------------

    /// <summary>What the proxy answers a turn call with once the restart has ended that call's chat.</summary>
    private const string ChatEndedWithTheRestart =
        "the backend restarted with the saved settings, and this review's chat ended with the backend "
        + "it ran on. Press Review to review again with the new settings.";

    /// <summary>With nothing waiting, every turn call goes on as before, and nothing is asked.</summary>
    [Fact]
    public void WithNoRestartWaitingEveryTurnCallGoesOnAndNothingIsAsked()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");

        Assert.Null(world.Host.PageTurnRefusal());
        Assert.Equal(0, world.Backend.Questions);
    }

    /// <summary>
    /// While a turn runs, a turn call is refused as the backend refuses a call while a turn runs -
    /// `TurnRunning`, not retryable (chat/server.py) - and the restart still waits.
    /// </summary>
    [Fact]
    public void WhileTheTurnRunsATurnCallIsRefusedAndTheRestartStillWaits()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        BackendRequestException? refusal = world.Host.PageTurnRefusal();

        Assert.NotNull(refusal);
        Assert.Equal("TurnRunning", refusal!.ErrorClass);
        Assert.Equal(TurnHoldsIt, refusal.Message);
        Assert.False(refusal.Retryable);
        Assert.Empty(world.Backend.Restarts);

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
    }

    /// <summary>
    /// ...and while a remodel run, or a backend that does not answer, holds the restart back, the
    /// refusal says which.
    /// </summary>
    [Theory]
    [InlineData("remodel run", "RemodelRunning", false)]
    [InlineData("no answer", "BackendUnavailable", true)]
    public void WhileSomethingElseHoldsTheRestartATurnCallIsRefusedSayingWhat(
        string cause, string expectedClass, bool expectedRetryable)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        if (cause == "remodel run")
        {
            world.BackendBusy = () => true;
        }
        else
        {
            world.Backend.StopsAnswering(questions: 1);
        }

        BackendRequestException? refusal = world.Host.PageTurnRefusal();

        Assert.NotNull(refusal);
        Assert.Equal(expectedClass, refusal!.ErrorClass);
        Assert.Equal(cause == "remodel run" ? RemodelRunHoldsIt : NoAnswerHoldsIt, refusal.Message);
        Assert.Equal(expectedRetryable, refusal.Retryable);
        Assert.Equal(0, world.Backend.Attempts);
    }

    /// <summary>
    /// A follow-up, an answer or a Send the moment the turn ends is for a chat of the backend about
    /// to be replaced. It never reaches that backend: the restart is made first, and the call is
    /// answered as the restarted backend would answer it, since that backend does not hold the chat.
    /// </summary>
    [Fact]
    public void ATurnCallTheMomentTheTurnEndsMakesTheRestartFirstAndIsToldItsChatEnded()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        BackendRequestException? refusal = world.Host.PageTurnRefusal();

        Assert.NotNull(refusal);
        Assert.Equal("UnknownChat", refusal!.ErrorClass);
        Assert.Equal(ChatEndedWithTheRestart, refusal.Message);
        Assert.False(refusal.Retryable);
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
        Assert.Single(world.Posted("backend.restarted"));
        Assert.Null(world.Host.PageTurnRefusal());
    }

    [Fact]
    public void ATurnCallWhileTheRestartIsBeingMadeWaitsForItAndIsToldItsChatEnded()
    {
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Backend.Hold = hold;
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the host never began the restart");

            var call = new Caller<BackendRequestException?>(() => world.Host.PageTurnRefusal());
            Assert.False(call.Finishes(TimeSpan.FromMilliseconds(300)), "the call did not wait for the restart being made");

            hold.Set();
            Assert.True(call.Finishes(TimeSpan.FromSeconds(10)), "the call never got an answer");
            Assert.Equal("UnknownChat", call.Result!.ErrorClass);
            Assert.Single(world.Backend.Restarts);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// A call that waited for a restart another caller was making, which then failed, is not told
    /// the backend restarted: it is told the failure, as the caller that made the attempt was.
    /// </summary>
    [Fact]
    public void ATurnCallWhoseRestartFailedForAnotherCallerIsToldThatFailure()
    {
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Backend.Hold = hold;
            world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the host never began the restart");

            var call = new Caller<BackendRequestException?>(() => world.Host.PageTurnRefusal());
            Assert.False(call.Finishes(TimeSpan.FromMilliseconds(300)), "the call did not wait for the restart being made");
            hold.Set();
            Assert.True(call.Finishes(TimeSpan.FromSeconds(10)), "the call never got an answer");

            BackendRequestException? refusal = call.Result;
            Assert.NotNull(refusal);
            Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
            Assert.Equal("FICT the backend would not start", refusal.Message);
            Assert.True(refusal.Retryable);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// A restart can fail before it stops anything - the configured launcher has gone, and the
    /// start options cannot be built - leaving the old backend up, still holding its chats. A turn
    /// call, or a new review, that waited for that restart is told the failure, masked, as the
    /// caller that made the attempt was: never that the backend restarted, and never let through
    /// to the old backend with the new settings.
    /// </summary>
    [Theory]
    [InlineData("turn call")]
    [InlineData("review")]
    public void ACallThatWaitedForARestartThatFailedBeforeStoppingAnythingIsToldThatFailure(string caller)
    {
        string failure = "the `python` setting names 'C:\\Fictional\\FICT-gone\\swreview.exe', which does not exist "
            + "(" + OpenAiKey + ")";
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Backend.Hold = hold;
            world.Backend.EarlyRestartFailure = new BackendStartException(failure);
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the host never began the restart");

            var call = new Caller<JsonElement?>(() =>
            {
                if (caller == "turn call")
                {
                    BackendRequestException? refusal = world.Host.PageTurnRefusal();
                    return refusal == null
                        ? (JsonElement?)null
                        : JsonDocument.Parse(JsonSerializer.Serialize(new
                        {
                            error_class = refusal.ErrorClass,
                            message = refusal.Message,
                        })).RootElement;
                }

                world.Receive("review.start", "start", new { });
                return world.Reply("error", "start");
            });
            Assert.False(call.Finishes(TimeSpan.FromMilliseconds(300)), "the call did not wait for the restart being made");
            hold.Set();
            Assert.True(call.Finishes(TimeSpan.FromSeconds(10)), "the call never got an answer");

            // The old backend is still up: the restart failed before it stopped anything.
            Assert.NotNull(world.Backend.Endpoint);
            Assert.Equal(0, world.Backend.Generation);
            string reported = world.Last("status").GetProperty("message").GetString()!;
            Assert.Contains(Redaction.Mask, reported, StringComparison.Ordinal);

            // The same failure, masked: the status with the way on after it (150A review) - since
            // owner decision 153A the sentence that the saved settings are not in force, which ends
            // with it, as the old backend runs on with the settings it was started with - the refusal
            // alone, its class's sentence naming the way on.
            JsonElement? answer = call.Result;
            Assert.NotNull(answer);
            Assert.Equal("BackendUnavailable", answer!.Value.GetProperty("error_class").GetString());
            Assert.Equal(answer.Value.GetProperty("message").GetString() + ". " + NotInForce, reported);
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.Backend.Sessions);
            world.AssertNothingPostedContains(OpenAiKey);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// ...and so is one that waited for a save's own restart, made when no turn ran, that failed
    /// so: the save is told, in its answer (owner decision 150A), and the call that waited is told
    /// the same failure.
    /// </summary>
    [Fact]
    public void ATurnCallThatWaitedForASavesRestartThatFailedIsToldThatFailure()
    {
        string failure = "the `python` setting names 'C:\\Fictional\\FICT-gone\\swreview.exe', which does not exist";
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "first", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            world.Backend.Hold = hold;
            world.Backend.EarlyRestartFailure = new BackendStartException(failure);

            var save = new Caller<bool>(() =>
            {
                world.Receive("settings.save", "second", Save(effort: "medium"));
                return true;
            });
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the save never began its restart");
            var call = new Caller<BackendRequestException?>(() => world.Host.PageTurnRefusal());
            Assert.False(call.Finishes(TimeSpan.FromMilliseconds(300)), "the call did not wait for the save's restart");

            hold.Set();
            Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
            Assert.True(call.Finishes(TimeSpan.FromSeconds(10)), "the call never got an answer");

            Assert.Equal(SavedNotRestarted + failure, world.Reply("error", "second").GetProperty("message").GetString());
            BackendRequestException? refusal = call.Result;
            Assert.NotNull(refusal);
            Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
            Assert.Equal(failure, refusal.Message);
            Assert.NotNull(world.Backend.Endpoint);
            Assert.Empty(world.Backend.Restarts);
        }
        finally
        {
            hold.Set();
        }
    }

    [Fact]
    public void ATurnCallWhoseRestartFailsIsAnsweredWithTheFailureMasked()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Backend.RestartFailure = new InvalidOperationException("the child would not start with " + OpenAiKey);
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        BackendRequestException? refusal = world.Host.PageTurnRefusal();

        Assert.NotNull(refusal);
        Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
        Assert.StartsWith("the child would not start with ", refusal.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(OpenAiKey, refusal.Message, StringComparison.Ordinal);
        Assert.True(refusal.Retryable);
        world.AssertNothingPostedContains(OpenAiKey);
    }

    /// <summary>
    /// The add-in hands the pane's proxy the review host's answer, read through the field per call:
    /// the pane is built before the host, and a host that has gone answers nothing. The add-in
    /// cannot be built without a live SOLIDWORKS, so its source is read, as the wiring tests do.
    /// </summary>
    [Fact]
    public void TheAddInHandsThePanesProxyTheReviewHostsAnswer()
    {
        string addIn = Path.Combine(ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn");
        string source = System.Text.RegularExpressions.Regex.Replace(
            File.ReadAllText(Path.Combine(addIn, "SwReviewAddIn.cs")), @"\s+", " ");

        int start = source.IndexOf("_pane = new TaskPaneControl(new TaskPaneOptions(", StringComparison.Ordinal);
        int end = start < 0 ? -1 : source.IndexOf("});", start, StringComparison.Ordinal);
        Assert.True(end > start, "SwReviewAddIn no longer builds its pane's options where this test reads them.");
        Assert.Contains(
            "PageTurnRefusal = () => _reviewHost?.PageTurnRefusal(),",
            source.Substring(start, end - start),
            StringComparison.Ordinal);
    }

    /// <summary>
    /// The add-in tells the review host whether a remodel run is in progress, read through the
    /// field per call: the Remodel host is built after the review host's options are.
    /// </summary>
    [Fact]
    public void TheAddInTellsTheReviewHostWhetherARemodelRunIsInProgress()
    {
        string addIn = Path.Combine(ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn");
        string source = System.Text.RegularExpressions.Regex.Replace(
            File.ReadAllText(Path.Combine(addIn, "SwReviewAddIn.cs")), @"\s+", " ");

        int start = source.IndexOf("var reviewOptions = new ReviewHostOptions(", StringComparison.Ordinal);
        int end = start < 0 ? -1 : source.IndexOf("_reviewHost = new ReviewHost(reviewOptions);", start, StringComparison.Ordinal);
        Assert.True(end > start, "SwReviewAddIn no longer builds the review host's options where this test reads them.");
        Assert.Contains(
            "BackendBusy = () => _remodelHost?.RunInProgress == true,",
            source.Substring(start, end - start),
            StringComparison.Ordinal);
    }

    /// <summary>
    /// The pane's proxy answers a turn call the host refuses as the backend answers a call it
    /// refuses with the same class: the status and the `retryable` flag chat/server.py gives it,
    /// read from that source - while the turn runs (`TurnRunning`) and once the restart has ended
    /// the call's chat (`UnknownChat`). The words are the host's own, and say why.
    /// </summary>
    [Fact]
    public void TheProxyAnswersARefusedTurnCallWithTheBackendsOwnStatusAndFlag()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        var proxy = new BackendProxyHandler(
            () => world.Backend.Endpoint,
            request => throw new InvalidOperationException("FICT a refused call was sent"),
            world.Host.PageTurnRefusal);

        AssertAnsweredAsTheBackendAnswers(proxy, "TurnRunning");

        world.Backend.EndTurn("chat-1");
        AssertAnsweredAsTheBackendAnswers(proxy, "UnknownChat");
        Assert.Single(world.Backend.Restarts);
    }

    private static void AssertAnsweredAsTheBackendAnswers(BackendProxyHandler proxy, string errorClass)
    {
        ProxiedResponse? response = proxy.TryServe(
            TaskPaneControl.PageOrigin + BackendProxy.PathPrefix + "/sessions/chat-1/messages", "POST", null, null);

        Assert.NotNull(response);
        JsonElement body = JsonDocument.Parse(Encoding.UTF8.GetString(response!.Content)).RootElement;
        (int status, bool retryable) = ChatServerSource.ErrorClass(errorClass);
        Assert.Equal(errorClass, body.GetProperty("error_class").GetString());
        Assert.Equal(status, response.Status);
        Assert.Equal(retryable, body.GetProperty("retryable").GetBoolean());
    }

    // ---- 9. every other tab is told (owner decision 145A) ---------------------------------------

    /// <summary>
    /// A save's restart made at once tells every other tab, once, as soon as it is made. The
    /// Review page is told as before, by the save's reply; the Model check, Standards and Remodel
    /// pages hold the old port and token and nothing else tells them.
    /// </summary>
    [Fact]
    public void ASavesRestartMadeAtOnceTellsTheOtherTabsOnce()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");

        world.Receive("settings.save", "save", Save(effort: "low"));

        Assert.Single(world.Backend.Restarts);
        world.Reply("settings.saved", "save");
        Assert.Equal(1, world.OtherTabsTold);
        Assert.Empty(world.Posted("backend.restarted"));
    }

    /// <summary>A restart that waited tells them once it is made, and not while it waits.</summary>
    [Fact]
    public void ARestartThatWaitedTellsTheOtherTabsOnceItIsMadeAndNotBefore()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        Polls(world.Backend, 2);
        Assert.Equal(0, world.OtherTabsTold);

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.OtherTabsTold == 1, "the other tabs told of the restart");

        Assert.Single(world.Posted("backend.restarted"));
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(1, world.OtherTabsTold);
    }

    /// <summary>...whoever makes it: a new review, or a page call that would start a turn, the moment the turn ends.</summary>
    [Theory]
    [InlineData("review")]
    [InlineData("turn call")]
    public void ARestartANewReviewOrATurnCallMakesTellsTheOtherTabs(string maker)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");

        if (maker == "review")
        {
            world.Receive("review.start", "start", new { });
            world.Reply("review.started", "start");
        }
        else
        {
            Assert.Equal("UnknownChat", world.Host.PageTurnRefusal()!.ErrorClass);
        }

        Assert.Single(world.Backend.Restarts);
        Assert.Equal(1, world.OtherTabsTold);
    }

    /// <summary>
    /// A restart that fails once the old backend has stopped - made at once or after waiting - is
    /// never told to the other tabs as a restart: no backend was started for them to ask about. It is
    /// told to them as a failure, once, with its words, as a failed first start is told to every page
    /// (owner decision 145A, found on review; until then it told them nothing, and they went on
    /// holding the token of a backend that was gone). The Review tab is told it as before - a save's,
    /// since owner decision 150A, in the save's own answer (section 11).
    /// </summary>
    [Theory]
    [InlineData("at once")]
    [InlineData("after waiting")]
    public void ARestartThatFailsOnceTheOldBackendStoppedIsToldToTheOtherTabsAsAFailure(string when)
    {
        using var world = new RestartWorld();
        world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
        world.Open();
        world.Track("chat-1");

        if (when == "at once")
        {
            world.Receive("settings.save", "save", Save(effort: "low"));
            Assert.Equal(
                SavedNotRestarted + "FICT the backend would not start",
                world.Reply("error", "save").GetProperty("message").GetString());
        }
        else
        {
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Eventually(() => world.Posted("status").Length == 2, "the failure's status");
            Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        }

        Assert.Equal(1, world.Backend.Attempts);
        Assert.Equal(0, world.OtherTabsTold);
        Assert.Equal(new[] { "FICT the backend would not start" }, world.FailuresToldToTheOtherTabs);
    }

    /// <summary>
    /// A restart that fails before it stops anything - the launcher has gone, say - leaves the old
    /// backend up, and the token every other tab holds with it: they are told nothing. The Review
    /// tab is told the failure as before - a save's, since owner decision 150A, in the save's own
    /// answer (section 11).
    /// </summary>
    [Theory]
    [InlineData("at once")]
    [InlineData("after waiting")]
    public void ARestartThatFailsBeforeTheOldBackendStoppedTellsTheOtherTabsNothing(string when)
    {
        using var world = new RestartWorld();
        world.Backend.EarlyRestartFailure = new BackendStartException("FICT the launcher has gone");
        world.Open();
        world.Track("chat-1");

        if (when == "at once")
        {
            world.Receive("settings.save", "save", Save(effort: "low"));
            Assert.Equal(
                SavedNotRestarted + "FICT the launcher has gone",
                world.Reply("error", "save").GetProperty("message").GetString());
        }
        else
        {
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
            world.Backend.EndTurn("chat-1");
            Eventually(() => world.Posted("status").Length == 2, "the failure's status");
            Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));

            // Since owner decision 153A the way on is the sentence that the saved settings are not in
            // force, which ends with it: the old backend runs on with the settings it was started with.
            Assert.Equal("FICT the launcher has gone. " + NotInForce, world.Last("status").GetProperty("message").GetString());
        }

        Assert.NotNull(world.Backend.Endpoint);
        Assert.Equal(0, world.OtherTabsTold);
        Assert.Empty(world.FailuresToldToTheOtherTabs);
    }

    /// <summary>
    /// A save's restart can fail with something other than a start failure: the old backend
    /// stopped, and the new one's log could not be opened, outside the wrapper that makes a
    /// <see cref="BackendStartException"/>. No backend is up then, and the other tabs are told, as
    /// for any failure (owner decision 145A, third review: only a <see cref="BackendStartException"/>
    /// told them). One that fails so before it stops anything leaves the old backend up, and tells
    /// them nothing. The save is answered as any save whose restart failed (owner decision 150A,
    /// section 11).
    /// </summary>
    [Theory]
    [InlineData("old backend stopped")]
    [InlineData("old backend still up")]
    public void ASavesRestartThatFailsOtherwiseIsToldToTheOtherTabsOnceNoBackendIsUp(string when)
    {
        using var world = new RestartWorld();
        var failure = new IOException("FICT the backend's log could not be opened with " + OpenAiKey);
        if (when == "old backend stopped")
        {
            world.Backend.RestartFailure = failure;
        }
        else
        {
            world.Backend.EarlyRestartFailure = failure;
        }

        world.Open();

        world.Receive("settings.save", "save", Save(effort: "low"));

        Assert.Equal(0, world.OtherTabsTold);
        if (when == "old backend stopped")
        {
            string told = Assert.Single(world.FailuresToldToTheOtherTabs);
            Assert.StartsWith("FICT the backend's log could not be opened with ", told, StringComparison.Ordinal);
            Assert.DoesNotContain(OpenAiKey, told, StringComparison.Ordinal);
        }
        else
        {
            Assert.Empty(world.FailuresToldToTheOtherTabs);
        }

        // Owner decision 150A: no longer `HostError`, as if nothing had been saved - the settings
        // were written, and the save says so.
        Assert.Equal("BackendNotRestarted", world.Reply("error", "save").GetProperty("error_class").GetString());
    }

    /// <summary>
    /// The failure reaches the other tabs masked: whatever the start said - a key in a child's
    /// error, say - never leaves this host unmasked (FR-015).
    /// </summary>
    [Fact]
    public void AFailedRestartToldToTheOtherTabsIsMasked()
    {
        using var world = new RestartWorld();
        world.Backend.RestartFailure = new BackendStartException("FICT the child would not start with " + OpenAiKey);
        world.Open();

        world.Receive("settings.save", "save", Save(effort: "low"));
        world.Reply("error", "save");

        string told = Assert.Single(world.FailuresToldToTheOtherTabs);
        Assert.StartsWith("FICT the child would not start with ", told, StringComparison.Ordinal);
        Assert.DoesNotContain(OpenAiKey, told, StringComparison.Ordinal);
    }

    /// <summary>
    /// A tab that cannot be told of the failure turns nothing into an error of its own: the save is
    /// still answered with its restart's failure, and nothing else - since owner decision 150A,
    /// `BackendNotRestarted`, never the tab's `HostError`.
    /// </summary>
    [Fact]
    public void ATabThatCannotBeToldOfAFailedRestartTurnsNothingIntoAnError()
    {
        using var world = new RestartWorld();
        world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
        world.TellingTheOtherTabsOfAFailure = () => throw new InvalidOperationException("FICT the pane has closed");
        world.Open();

        world.Receive("settings.save", "save", Save(effort: "low"));

        JsonElement answer = Assert.Single(world.Posted("error"));
        Assert.Equal("BackendNotRestarted", answer.GetProperty("error_class").GetString());
        Assert.Equal(SavedNotRestarted + "FICT the backend would not start", answer.GetProperty("message").GetString());
        Assert.Single(world.FailuresToldToTheOtherTabs);
    }

    /// <summary>
    /// A tab that cannot be told turns no restart into a failure: the save is still answered
    /// `settings.saved` with nothing refused, and a restart that waited is still told to the
    /// Review page.
    /// </summary>
    [Fact]
    public void ATabThatCannotBeToldTurnsNoRestartIntoAFailure()
    {
        using var world = new RestartWorld();
        world.TellingTheOtherTabs = () => throw new InvalidOperationException("FICT the pane has closed");
        world.Open();
        world.Track("chat-1");

        world.Receive("settings.save", "first", Save(effort: "low"));
        world.Reply("settings.saved", "first");
        Assert.Empty(world.Posted("error"));

        SaveAsATurnStarts(world, "second", Save(effort: "medium"));
        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
        Eventually(() => world.OtherTabsTold == 2, "the other tabs asked to be told twice");
        Assert.Equal(2, world.Backend.Restarts.Length);
    }

    // ---- 10. a remodel run is treated as a turn (owner decision 145A) --------------------------

    /// <summary>
    /// A save made while a remodel run is in progress - a plan or a Start's run - is kept: written,
    /// saved in the host and answered `settings.saved`. Its restart waits for the run, as one a
    /// turn started during waits for the turn, and the pane says so: before 145A it restarted the
    /// backend at once and ended the run with its copy half changed. Nothing is asked of the backend
    /// meanwhile - the run is known without it - and once the run ends the backend restarts once,
    /// with the saved settings, and every tab is told.
    /// </summary>
    [Fact]
    public void ASaveDuringARemodelRunIsKeptAndItsRestartWaitsForTheRun()
    {
        int remodelling = 1;
        using var world = new RestartWorld { BackendBusy = () => Volatile.Read(ref remodelling) == 1 };
        world.Open();
        world.Track("chat-1");

        world.Receive("settings.save", "save", Save(model: "gpt-5.6-mini", effort: "low"));

        Assert.Equal("low", world.Reply("settings.saved", "save").GetProperty("settings").GetProperty("effort").GetString());
        Assert.Equal("low", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
        Assert.Equal("low", world.Host.Settings.Effort);
        JsonElement status = world.Last("status");
        Assert.Equal("error", status.GetProperty("stage").GetString());
        Assert.Equal(RemodelRunPromise, status.GetProperty("message").GetString());

        // The run goes on with the backend it began on: no restart is asked for, not even of the
        // backend's own check, while it lasts.
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.Equal(0, world.OtherTabsTold);

        Volatile.Write(ref remodelling, 0);
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted after the run");
        (UserSettings settings, _) = Assert.Single(world.Backend.Restarts);
        Assert.Equal("gpt-5.6-mini", settings.Model);
        Assert.Equal("low", settings.Effort);
        Eventually(() => world.OtherTabsTold == 1, "the other tabs told");
    }

    /// <summary>
    /// A save made during a remodel run that a turn also started during - after the save's own
    /// check, inside its model-list round trip - says the restart waits for both, and it waits for
    /// both: whichever ends first leaves it waiting for the other.
    /// </summary>
    [Theory]
    [InlineData("the turn")]
    [InlineData("the run")]
    public void ASaveDuringARemodelRunThatATurnStartedDuringWaitsForBothAndSaysSo(string first)
    {
        int remodelling = 1;
        using var world = new RestartWorld { BackendBusy = () => Volatile.Read(ref remodelling) == 1 };
        world.Open();
        world.Track("chat-1");

        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        Assert.Equal(TurnAndRemodelRunPromise, world.Last("status").GetProperty("message").GetString());

        if (first == "the turn")
        {
            world.Backend.EndTurn("chat-1");
        }
        else
        {
            Volatile.Write(ref remodelling, 0);
        }

        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.Attempts);
        Assert.Empty(world.Posted("backend.restarted"));

        world.Backend.EndTurn("chat-1");
        Volatile.Write(ref remodelling, 0);
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted after both");
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// `backend.restarted` carries every sentence the Review tab may have shown about a restart
    /// that waits - for a turn, for a remodel run, for both, and the watcher's word that the
    /// backend is not answering - so the page takes whichever is on its banner off it, and nothing
    /// else there.
    /// </summary>
    [Fact]
    public void TheRestartCarriesEverySentenceTheReviewTabMayHaveShown()
    {
        int remodelling = 1;
        using var world = new RestartWorld { BackendBusy = () => Volatile.Read(ref remodelling) == 1 };
        world.Open();
        world.Track("chat-1");
        world.Receive("settings.save", "save", Save(effort: "low"));

        Volatile.Write(ref remodelling, 0);
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");

        Assert.Equal(
            RestartSentences,
            world.Last("backend.restarted").GetProperty("sentences").EnumerateArray().Select(sentence => sentence.GetString()));
    }

    /// <summary>
    /// With no backend process at all the look answers that nothing holds the restart back - the
    /// restart is what brings a backend back - without reading the remodel run. The run is read
    /// again under the restart's own lock, so one still in progress holds the restart back even
    /// then, and the restart is made once the run ends. Found by an independent review of 145A:
    /// this, not a run begun after the look, is what that reading under the lock guards.
    /// </summary>
    [Fact]
    public void WithNoBackendAtAllARemodelRunInProgressStillHoldsTheRestartBack()
    {
        int remodelling = 1;
        using var world = new RestartWorld { BackendBusy = () => Volatile.Read(ref remodelling) == 1 };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        world.Backend.Down = true;

        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.Attempts);
        Assert.Empty(world.Posted("backend.restarted"));

        Volatile.Write(ref remodelling, 0);
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted after the run");
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
        Assert.NotNull(world.Backend.Endpoint);
    }

    /// <summary>
    /// Through the host: when whether a remodel run is in progress cannot be read -
    /// <c>ReviewHostOptions.BackendBusy</c> throws - a save's restart waits as for a run and says
    /// the run's sentence, and nothing is restarted; a remodel run asked to begin meanwhile is
    /// refused `RemodelRunning`, the one way that refusal is ever given, since the Remodel host
    /// refuses a second run itself. Once the run can be read again, and none is in progress, the
    /// restart is made (owner decision 145A; found unpinned on review).
    /// </summary>
    [Fact]
    public void WhenARemodelRunCannotBeReadASaveWaitsForItAndARunIsRefused()
    {
        int readable = 0;
        using var world = new RestartWorld
        {
            BackendBusy = () => Volatile.Read(ref readable) == 1
                ? false
                : throw new InvalidOperationException("FICT the Remodel host cannot be asked"),
        };
        world.Open();

        world.Receive("settings.save", "save", Save(effort: "low"));
        world.Reply("settings.saved", "save");
        Assert.Equal(
            "the settings are saved; the backend restarts when the remodel run ends.",
            world.Last("status").GetProperty("message").GetString());

        int began = 0;
        BackendRequestException? refusal = world.Host.BeginRemodelRun(() => began++);
        Assert.NotNull(refusal);
        Assert.Equal("RemodelRunning", refusal!.ErrorClass);
        Assert.Equal(
            "the backend restarts with the saved settings when the remodel run ends, and nothing new starts "
            + "before then. Wait for the run to end, then try again.",
            refusal.Message);
        Assert.True(refusal.Retryable);
        Assert.Equal(0, began);
        Assert.Equal(0, world.Backend.Attempts);

        Volatile.Write(ref readable, 1);
        Eventually(() => world.Backend.Restarts.Length == 1, "the restart once the run can be read");
        Assert.Equal("low", world.Backend.Restarts[0].Settings.Effort);
    }

    /// <summary>With nothing waiting, a remodel run begins at once: nothing is asked of the backend and nothing restarts.</summary>
    [Fact]
    public void ARemodelRunWithNoRestartWaitingBeginsAtOnceAndNothingIsAsked()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        int begun = 0;

        Assert.Null(world.Host.BeginRemodelRun(() => begun++));

        Assert.Equal(1, begun);
        Assert.Equal(0, world.Backend.Questions);
        Assert.Equal(0, world.Backend.RestartsAsked);
    }

    /// <summary>
    /// A remodel run started the moment the turn ends makes the waiting restart first, as a new
    /// review does, and begins on the restarted backend with the saved settings - never on the old
    /// one, with the provider and key the engineer replaced. Every page is told of the restart
    /// before the run begins.
    /// </summary>
    [Fact]
    public void ARemodelRunTheMomentTheTurnEndsRestartsTheBackendFirstAndBeginsOnIt()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(model: "gpt-5.6-mini", effort: "low"));
        world.Backend.EndTurn("chat-1");
        int restartsAtTheBeginning = -1;
        int toldAtTheBeginning = -1;

        BackendRequestException? refusal = world.Host.BeginRemodelRun(() =>
        {
            restartsAtTheBeginning = world.Backend.Restarts.Length;
            toldAtTheBeginning = world.Posted("backend.restarted").Length + world.OtherTabsTold;
        });

        Assert.Null(refusal);
        Assert.Equal(1, restartsAtTheBeginning);
        Assert.Equal(2, toldAtTheBeginning);
        Assert.Equal("gpt-5.6-mini", Assert.Single(world.Backend.Restarts).Settings.Model);
    }

    /// <summary>
    /// While something holds the restart back the run is refused, saying what, and its step never
    /// runs: a turn (`TurnRunning`), in words for the Remodel tab, whose own Stop stops the run -
    /// the turn's is on the Review tab; or a backend that does not answer (`BackendUnavailable`).
    /// The restart still waits, and the next press makes it once nothing holds it back.
    /// </summary>
    [Theory]
    [InlineData("turn", "TurnRunning")]
    [InlineData("no answer", "BackendUnavailable")]
    public void ARemodelRunWhileSomethingHoldsTheRestartIsRefusedSayingWhat(string cause, string expectedClass)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        if (cause == "no answer")
        {
            world.Backend.EndTurn("chat-1");
            world.Backend.StopsAnswering(questions: 1);
        }

        int begun = 0;
        BackendRequestException? refusal = world.Host.BeginRemodelRun(() => begun++);

        Assert.NotNull(refusal);
        Assert.Equal(expectedClass, refusal!.ErrorClass);
        Assert.Equal(cause == "turn" ? TurnHoldsTheRemodelRun : NoAnswerHoldsTheRemodelRun, refusal.Message);
        Assert.True(refusal.Retryable);
        Assert.Equal(0, begun);
        Assert.Equal(0, world.Backend.Attempts);

        world.Backend.EndTurn("chat-1");
        Assert.Null(world.Host.BeginRemodelRun(() => begun++));
        Assert.Equal(1, begun);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// A remodel run started while a restart is being made waits for it, and begins on the
    /// restarted backend - the watcher's restart, and a save's own, made at once, which no caller
    /// waited for before 145A: a run began at once, on a backend about to go.
    /// </summary>
    [Theory]
    [InlineData("the watcher")]
    [InlineData("a save")]
    public void ARemodelRunWhileARestartIsBeingMadeWaitsForItThenBegins(string maker)
    {
        using var world = new RestartWorld { Poll = maker == "a save" ? TimeSpan.FromMinutes(10) : TimeSpan.FromMilliseconds(10) };
        using var hold = new ManualResetEventSlim(false);
        Caller<bool>? save = null;
        try
        {
            world.Open();
            world.Track("chat-1");
            if (maker == "the watcher")
            {
                SaveAsATurnStarts(world, "save", Save(effort: "low"));
                world.Backend.Hold = hold;
                world.Backend.EndTurn("chat-1");
            }
            else
            {
                world.Backend.Hold = hold;
                save = new Caller<bool>(() =>
                {
                    world.Receive("settings.save", "save", Save(effort: "low"));
                    return true;
                });
            }

            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the restart was never begun");
            int restartsAtTheBeginning = -1;
            var run = new Caller<BackendRequestException?>(() =>
                world.Host.BeginRemodelRun(() => restartsAtTheBeginning = world.Backend.Restarts.Length));
            Assert.False(run.Finishes(TimeSpan.FromMilliseconds(300)), "the run did not wait for the restart being made");

            hold.Set();
            Assert.True(run.Finishes(TimeSpan.FromSeconds(10)), "the run never began");
            Assert.Null(run.Result);
            Assert.Equal(1, restartsAtTheBeginning);
            Assert.True(save == null || save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
            Assert.Single(world.Backend.Restarts);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// A run whose restart fails is refused with that failure, masked, and never begins - its own
    /// restart, or a save's it waited for, which failed before it stopped anything and so left the
    /// old backend up with the old settings: as every waiter is told (143A), the run is never let
    /// through to it.
    /// </summary>
    [Theory]
    [InlineData("its own")]
    [InlineData("a save's")]
    public void ARemodelRunWhoseRestartFailsIsRefusedWithThatFailureAndNeverBegins(string whose)
    {
        string failure = "the child would not start with " + OpenAiKey;
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Open();
            world.Track("chat-1");
            int begun = 0;
            BackendRequestException? refusal;
            if (whose == "its own")
            {
                SaveAsATurnStarts(world, "save", Save(effort: "low"));
                world.Backend.EndTurn("chat-1");
                world.Backend.RestartFailure = new InvalidOperationException(failure);
                refusal = world.Host.BeginRemodelRun(() => begun++);
            }
            else
            {
                world.Backend.Hold = hold;
                world.Backend.EarlyRestartFailure = new BackendStartException(failure);
                var save = new Caller<bool>(() =>
                {
                    world.Receive("settings.save", "save", Save(effort: "low"));
                    return true;
                });
                Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the save never began its restart");
                var run = new Caller<BackendRequestException?>(() => world.Host.BeginRemodelRun(() => begun++));
                Assert.False(run.Finishes(TimeSpan.FromMilliseconds(300)), "the run did not wait for the save's restart");
                hold.Set();
                Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
                Assert.True(run.Finishes(TimeSpan.FromSeconds(10)), "the run never got an answer");
                refusal = run.Result;
                Assert.NotNull(world.Backend.Endpoint);
                Assert.Equal(0, world.Backend.Generation);
            }

            Assert.NotNull(refusal);
            Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
            Assert.StartsWith("the child would not start with ", refusal.Message, StringComparison.Ordinal);
            Assert.DoesNotContain(OpenAiKey, refusal.Message, StringComparison.Ordinal);
            Assert.True(refusal.Retryable);
            Assert.Equal(0, begun);
            world.AssertNothingPostedContains(OpenAiKey);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>A run asked for once the host is disposed - the add-in unloading, its backend with it - never begins.</summary>
    [Fact]
    public void ARemodelRunOnceTheHostIsDisposedIsRefusedAndNeverBegins()
    {
        var world = new RestartWorld();
        try
        {
            world.Open();
            world.Host.Dispose();
            int begun = 0;

            BackendRequestException? refusal = world.Host.BeginRemodelRun(() => begun++);

            Assert.NotNull(refusal);
            Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
            Assert.Equal("the review backend is stopping with the add-in.", refusal.Message);
            Assert.False(refusal.Retryable);
            Assert.Equal(0, begun);
        }
        finally
        {
            world.Dispose();
        }
    }

    /// <summary>
    /// The add-in hands the Remodel host the review host's gate, read through the field per call:
    /// the review host is the one that keeps the restart, on another pump. With no review host
    /// there is no settings restart to wait for, and the run begins.
    /// </summary>
    [Fact]
    public void TheAddInHandsTheRemodelHostTheReviewHostsRestartGate()
    {
        string source = OtherTabsBackendRestartTests.AddInSource();
        string options = OtherTabsBackendRestartTests.Between(
            source, "_remodelHost = new RemodelHost(new RemodelHostOptions(", "StartRemodelPump();");
        Assert.Contains("BeginRun = BeginRemodelRun,", options, StringComparison.Ordinal);

        string gate = OtherTabsBackendRestartTests.Between(
            source, "private BackendRequestException? BeginRemodelRun(Action begin) {", "private ");
        Assert.Contains("ReviewHost? host = _reviewHost;", gate, StringComparison.Ordinal);
        Assert.Contains("return host.BeginRemodelRun(begin);", gate, StringComparison.Ordinal);
        Assert.Contains("begin(); return null;", gate, StringComparison.Ordinal);
    }

    /// <summary>
    /// The add-in hands the Remodel host the review host's word on whether a settings restart
    /// stands before a plan or a run, read through the field per call - and none with no review
    /// host (owner decision 145A, found on review).
    /// </summary>
    [Fact]
    public void TheAddInHandsTheRemodelHostTheReviewHostsWordOnARestartAhead()
    {
        string source = OtherTabsBackendRestartTests.AddInSource();
        string options = OtherTabsBackendRestartTests.Between(
            source, "_remodelHost = new RemodelHost(new RemodelHostOptions(", "StartRemodelPump();");
        Assert.Contains("RestartAhead = () => _reviewHost?.RestartAhead == true,", options, StringComparison.Ordinal);
    }

    // ---- 11. a save whose restart fails says what is true (owner decision 150A) ---------------

    /// <summary>
    /// The settings are written, and saved in the host, before the save restarts the backend,
    /// so a save whose restart fails is a save that was kept and a backend that was not restarted -
    /// whatever the restart threw: a <see cref="BackendStartException"/>, or anything outside that
    /// wrapper, such as the new backend's log not opened, and with the old backend stopped or still
    /// up. It is answered `error {error_class: "BackendNotRestarted", retryable: true}`, whose
    /// message says so, names the way on - saving again retries the restart - and gives the reason,
    /// masked (owner decision 150A). Before it a start failure was answered `settings.saved`, the
    /// reason alone in a `status`, and any other failure `HostError`, not retryable, as if nothing
    /// had been saved (research 145A, Not changed).
    /// </summary>
    [Theory]
    [InlineData("a start failure", "old backend stopped")]
    [InlineData("a start failure", "old backend still up")]
    [InlineData("any other failure", "old backend stopped")]
    [InlineData("any other failure", "old backend still up")]
    public void ASaveWhoseRestartFailsSaysTheSettingsAreSavedAndTheBackendDidNotRestart(string kind, string when)
    {
        string reason = "FICT the backend's log could not be opened with " + OpenAiKey;
        Exception failure = kind == "a start failure" ? new BackendStartException(reason) : new IOException(reason);
        using var world = new RestartWorld();
        if (when == "old backend stopped")
        {
            world.Backend.RestartFailure = failure;
        }
        else
        {
            world.Backend.EarlyRestartFailure = failure;
        }

        world.Open();

        world.Receive("settings.save", "save", Save(model: "gpt-5.6-mini", effort: "low"));

        JsonElement answer = world.Reply("error", "save");
        Assert.Equal("BackendNotRestarted", answer.GetProperty("error_class").GetString());
        Assert.True(answer.GetProperty("retryable").GetBoolean());
        string message = answer.GetProperty("message").GetString()!;
        Assert.StartsWith(SavedNotRestarted + "FICT the backend's log could not be opened with ", message, StringComparison.Ordinal);
        Assert.EndsWith(Redaction.Mask, message, StringComparison.Ordinal);

        // Kept: written, and saved in the host. The answer says it all, so nothing beside it -
        // no `settings.saved`, and no `status` carrying the reason a second time.
        Assert.Equal("low", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
        Assert.Equal("gpt-5.6-mini", world.Host.Settings.Model);
        Assert.Empty(world.Posted("settings.saved"));
        Assert.Empty(world.Posted("status"));
        Assert.Equal(1, world.Backend.Attempts);
        Assert.Equal(when == "old backend stopped" ? 1 : 0, world.FailuresToldToTheOtherTabs.Length);
        world.AssertNothingPostedContains(OpenAiKey);
    }

    /// <summary>
    /// The way on is true: the next save retries the restart - nothing waits from the one that
    /// failed - and, made, is answered `settings.saved` and told to the other tabs as any save's
    /// restart is.
    /// </summary>
    [Fact]
    public void SavingAgainAfterARestartThatFailedRetriesTheRestart()
    {
        using var world = new RestartWorld();
        world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
        world.Open();
        world.Receive("settings.save", "first", Save(effort: "low"));
        world.Reply("error", "first");
        Assert.False(world.Host.RestartAhead);

        world.Backend.RestartFailure = null;
        world.Receive("settings.save", "again", Save(effort: "low"));

        world.Reply("settings.saved", "again");
        Assert.Equal(2, world.Backend.Attempts);
        Assert.Single(world.Backend.Restarts);
        Assert.Equal(1, world.OtherTabsTold);
    }

    // ---- 12. a restart that waited and failed names the way on (150A review) ------------------

    /// <summary>
    /// A restart that waited for a turn and then failed is told to the Review page as before, as a
    /// failed start is - `status {stage: "error"}` with the failure, masked - and now with the way on
    /// after it: saving the settings again retries the restart (150A review, O2; until then the
    /// banner carried the bare failure). Whether the restart stopped the old backend or failed before
    /// it did, the status ends with those words; one that failed before it did left that backend up
    /// with the settings it was started with, which are in force until a restart succeeds, so its way
    /// on is the sentence saying the saved settings are not in force yet, which ends with them (owner
    /// decision 153A). The other tabs are handed the failure alone, and only once no backend is up:
    /// the add-in adds their way on.
    /// </summary>
    [Theory]
    [InlineData(
        "old backend stopped",
        "FICT the backend did not answer /health within 30 seconds.",
        "FICT the backend did not answer /health within 30 seconds. Save the settings again to retry the restart.")]
    [InlineData(
        "old backend still up",
        "FICT the launcher could not be resolved (log: C:\\Fictional\\FICT-logs\\backend.log)",
        "FICT the launcher could not be resolved (log: C:\\Fictional\\FICT-logs\\backend.log). The saved settings "
            + "are not in force yet: the review backend did not restart with them, so reviews run with the "
            + "settings it was started with. Save the settings again to retry the restart.")]
    public void ARestartThatWaitedAndFailedSaysSavingAgainRetriesIt(string when, string failure, string said)
    {
        using var world = new RestartWorld();
        var thrown = new BackendStartException(failure);
        if (when == "old backend stopped")
        {
            world.Backend.RestartFailure = thrown;
        }
        else
        {
            world.Backend.EarlyRestartFailure = thrown;
        }

        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("status").Length == 2, "the failure's status");

        JsonElement status = world.Last("status");
        Assert.Equal("error", status.GetProperty("stage").GetString());
        Assert.Equal(said, status.GetProperty("message").GetString());
        Assert.Equal(when == "old backend stopped" ? new[] { failure } : new string[0], world.FailuresToldToTheOtherTabs);
    }

    // ---- 13. until a restart succeeds, the settings the backend was started with are in force (153A)

    /// <summary>
    /// A restart can fail before it stops the old backend - the configured launcher cannot be
    /// resolved, say - and nothing waits afterwards, so the next review goes to that backend, which
    /// keeps the environment it was started with: the key, `OPENAI_BASE_URL`, Gemini Enterprise.
    /// Until a restart succeeds, every session takes the provider, model and effort that backend
    /// was started with, not the saved ones (owner decision 153A). It took the saved ones, and so
    /// paired one provider's settings with another's environment (research 150A, Not changed) -
    /// here a switch to Gemini, with a Gemini key, on a backend started for OpenAI with an OpenAI
    /// key. Every way a session is made: a review, a recheck, a review with saved engineering
    /// context and that review's Retry; whichever restart failed - a save's made at once, or one
    /// that waited for a turn.
    /// </summary>
    [Theory]
    [InlineData("review", "at once")]
    [InlineData("review", "after waiting")]
    [InlineData("recheck", "at once")]
    [InlineData("recheck", "after waiting")]
    [InlineData("context review", "at once")]
    [InlineData("context review", "after waiting")]
    [InlineData("context retry", "at once")]
    [InlineData("context retry", "after waiting")]
    public void ASessionAfterARestartThatFailedBeforeTheOldBackendStoppedTakesTheSettingsItWasStartedWith(
        string session, string when)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, when, ASwitchToGemini());

        NewSessionRequest request = MakeASession(world, session);

        Assert.Equal("openai", request.Provider);
        Assert.Equal("gpt-5.6", request.Model);
        Assert.Equal("high", request.Effort);
        Assert.Equal(0, world.Backend.Sessions.Last().Generation);

        // Saved all the same: the Settings form shows them, and the next restart is made with them.
        Assert.Equal("gemini", world.Host.Settings.Provider);
        Assert.Equal("gemini-3.5-flash", world.Host.Settings.Model);
        Assert.Equal("low", world.Host.Settings.Effort);
    }

    /// <summary>
    /// While the saved settings are not in force the Review tab is told so, and that saving again
    /// retries, by every `init` - so a page that loads or reloads is told too - in one sentence of
    /// the host's; and the status a restart that waited posts when it failed before it stopped the
    /// old backend ends with that sentence rather than the bare way on, since that backend runs on
    /// with the settings it was started with (owner decision 153A).
    /// </summary>
    [Theory]
    [InlineData("at once")]
    [InlineData("after waiting")]
    public void WhileTheSavedSettingsAreNotInForceInitSaysSoAndThatSavingAgainRetries(string when)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");

        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, when, ASwitchToGemini());

        if (when == "after waiting")
        {
            Assert.Equal(LauncherGone + ". " + NotInForce, world.Last("status").GetProperty("message").GetString());
        }

        Assert.Equal(NotInForce, Init(world, "init").GetProperty("settings_not_in_force").GetString());
        Assert.Equal(NotInForce, Init(world, "reload").GetProperty("settings_not_in_force").GetString());
    }

    /// <summary>
    /// The sentence is said only while it is true: never while the saved settings are the ones in
    /// force - nothing failed, or a save after the failed one restarted the backend with its own,
    /// or the settings saved are the ones in force already, so a failed restart left them in force
    /// (a save of the same settings, or one back to them, its key typed again) - nor with no
    /// backend at all, which is 150A's path: a restart that failed once the old backend had stopped
    /// leaves nothing in force; nor while a restart waits, when 143A's promise is the true sentence
    /// and nothing runs on the old backend before it is made. `init` carries null for each.
    /// </summary>
    [Theory]
    [InlineData("nothing failed")]
    [InlineData("saved again and restarted")]
    [InlineData("the same settings saved again")]
    [InlineData("the settings in force saved again")]
    [InlineData("the old backend stopped")]
    [InlineData("a restart waits")]
    public void InitSaysNothingOfTheSettingsInForceWhileItIsNotTrue(string state)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        switch (state)
        {
            case "saved again and restarted":
                SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", ASwitchToGemini());
                world.Backend.EarlyRestartFailure = null;
                world.Receive("settings.save", "again", ASwitchToGemini());
                world.Reply("settings.saved", "again");
                break;

            case "the same settings saved again":
                SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", Save());
                break;

            case "the settings in force saved again":
                // Back to OpenAI from the switch, whose restart failed: the switch retired the
                // stored key, so the engineer types it again - stored anew, the same key.
                SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", ASwitchToGemini());
                world.Receive("settings.save", "back", Save(apiKey: OpenAiKey));
                Assert.Equal("BackendNotRestarted", world.Reply("error", "back").GetProperty("error_class").GetString());
                break;

            case "the old backend stopped":
                world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
                world.Receive("settings.save", "save", ASwitchToGemini());
                world.Reply("error", "save");
                Assert.Null(world.Backend.Endpoint);
                break;

            case "a restart waits":
                SaveAsATurnStarts(world, "save", ASwitchToGemini());
                world.Reply("settings.saved", "save");
                Assert.True(world.Host.RestartAhead);
                break;
        }

        Assert.Equal(JsonValueKind.Null, Init(world, "init").GetProperty("settings_not_in_force").ValueKind);
    }

    /// <summary>
    /// The saved settings are in force when the backend was started with the same of everything a
    /// session takes - the provider, the model, the effort - and of everything a save writes that
    /// the backend's start reads: the key, by its value and by where it comes from (138A's marker
    /// follows the second), the base URL and Gemini Enterprise's project and location. A save that
    /// changes only one of them, whose restart fails before the old backend stops, is not in force
    /// (owner decision 153A).
    /// </summary>
    [Theory]
    [InlineData("provider")]
    [InlineData("model")]
    [InlineData("effort")]
    [InlineData("key")]
    [InlineData("where the key comes from")]
    [InlineData("base URL")]
    [InlineData("Gemini Enterprise's project")]
    [InlineData("Gemini Enterprise's location")]
    public void ASaveThatChangesOnlyOneSettingTheBackendNeedsIsNotInForceUntilItRestarts(string changed)
    {
        using var world = new RestartWorld();
        Dictionary<string, object?> payload;
        switch (changed)
        {
            case "provider":
                // The same key typed for the other provider, so the provider alone changes.
                payload = Save(provider: "gemini", apiKey: OpenAiKey);
                break;

            case "model":
                payload = Save(model: "gpt-5.6-mini");
                break;

            case "effort":
                payload = Save(effort: "low");
                break;

            case "key":
                payload = Save(apiKey: string.Concat("FICT", "-saved-", "openai-", "153a-0003"));
                break;

            case "where the key comes from":
                // The stored key removed, and the same key found in the workstation's environment:
                // the backend was started naming the pane's key as the saved one (138A), and would
                // not be now.
                world.WorkstationEnvironment = name => name == "OPENAI_API_KEY" ? OpenAiKey : null;
                payload = Save(apiKey: string.Empty);
                break;

            case "base URL":
                payload = Save(baseUrl: "https://fict-gateway.invalid/v1");
                break;

            default:
                world.Settings.Provider = "gemini";
                world.Settings.Model = "gemini-3.5-flash";
                world.Settings.SetApiKey(GeminiKey);
                world.Settings.GeminiEnterprise = new GeminiEnterpriseSettings
                {
                    Project = "fict-project",
                    Location = "fict-location",
                };
                payload = Save(
                    provider: "gemini",
                    model: "gemini-3.5-flash",
                    geminiEnterprise: changed == "Gemini Enterprise's project"
                        ? new { project = "fict-project-2", location = "fict-location" }
                        : new { project = "fict-project", location = "fict-location-2" });
                break;
        }

        world.Open();
        world.Track("chat-1");
        Assert.Equal(JsonValueKind.Null, Init(world, "before").GetProperty("settings_not_in_force").ValueKind);

        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", payload);

        Assert.Equal(NotInForce, Init(world, "after").GetProperty("settings_not_in_force").GetString());
    }

    /// <summary>
    /// Two saves, the first failing before the old backend stopped and the second restarting the
    /// backend - at once, or once the turn it met has ended: the saved settings are in force from
    /// then on. The next review takes them, on the restarted backend, and `init` says nothing more.
    /// </summary>
    [Theory]
    [InlineData("at once")]
    [InlineData("after waiting")]
    public void ASaveThatRestartsTheBackendAfterOneThatFailedPutsTheSavedSettingsInForce(string when)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", Save(model: "gpt-5.6-mini", effort: "low"));
        world.Backend.EarlyRestartFailure = null;

        Dictionary<string, object?> second = ASwitchToGemini();
        if (when == "at once")
        {
            world.Receive("settings.save", "second", second);
        }
        else
        {
            SaveAsATurnStarts(world, "second", second);
            world.Backend.EndTurn("chat-1");
            Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
        }

        world.Reply("settings.saved", "second");
        Assert.Equal(1, world.Backend.Generation);
        Assert.Equal(JsonValueKind.Null, Init(world, "init").GetProperty("settings_not_in_force").ValueKind);

        NewSessionRequest request = MakeASession(world, "review");
        Assert.Equal("gemini", request.Provider);
        Assert.Equal("gemini-3.5-flash", request.Model);
        Assert.Equal("low", request.Effort);
        Assert.Equal(1, world.Backend.Sessions.Last().Generation);
    }

    /// <summary>
    /// The add-in loads with saved settings whose first start fails: no backend, so no settings are
    /// in force, and `init` says nothing of them - the add-in's word that the backend did not start
    /// says how to go on (150A) - and a review is refused, as with no backend. A save then starts the
    /// backend with its settings, which are in force from then on: a review takes them. A save whose
    /// start fails too leaves no backend, and `init` still says nothing of them.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void WhenTheFirstStartFailedNothingIsInForceUntilASaveStartsTheBackend(bool saveStartsIt)
    {
        using var world = new RestartWorld();
        world.Backend.Down = true;
        world.Open();

        Assert.Equal(JsonValueKind.Null, Init(world, "init").GetProperty("settings_not_in_force").ValueKind);
        world.Receive("review.start", "refused", new { });
        Assert.Equal("BackendUnavailable", world.Reply("error", "refused").GetProperty("error_class").GetString());

        if (!saveStartsIt)
        {
            world.Backend.EarlyRestartFailure = new BackendStartException(LauncherGone);
        }

        world.Receive("settings.save", "save", ASwitchToGemini());

        if (!saveStartsIt)
        {
            Assert.Equal("BackendNotRestarted", world.Reply("error", "save").GetProperty("error_class").GetString());
            Assert.Null(world.Backend.Endpoint);
            Assert.Equal(JsonValueKind.Null, Init(world, "after").GetProperty("settings_not_in_force").ValueKind);
            return;
        }

        world.Reply("settings.saved", "save");
        Assert.Equal(JsonValueKind.Null, Init(world, "after").GetProperty("settings_not_in_force").ValueKind);
        NewSessionRequest request = MakeASession(world, "review");
        Assert.Equal("gemini", request.Provider);
        Assert.Equal("gemini-3.5-flash", request.Model);
        Assert.Equal("low", request.Effort);
    }

    /// <summary>
    /// The Review tab's Send box is saved without a restart (feature 015) and is no setting the
    /// backend is started with, so its save leaves the settings in force as they were: `init` goes
    /// on saying the saved settings are not in force while they are not, and says nothing while
    /// they are.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void TheSendBoxsSaveLeavesTheSettingsInForceAsTheyWere(bool afterAFailedRestart)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        if (afterAFailedRestart)
        {
            SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", ASwitchToGemini());
        }

        world.Receive("send_when_checked.save", "box", new { send_when_checked = false });
        world.Reply("send_when_checked.saved", "box");

        JsonElement said = Init(world, "init").GetProperty("settings_not_in_force");
        if (afterAFailedRestart)
        {
            Assert.Equal(NotInForce, said.GetString());
        }
        else
        {
            Assert.Equal(JsonValueKind.Null, said.ValueKind);
        }
    }

    /// <summary>
    /// Found on review (S1, N4): the word that a restart which waited has failed is the one message
    /// after which the settings in force can differ from the saved ones with no `init` to say so -
    /// the page is not asked to read its `init` again - so it carries `settings_not_in_force`, as
    /// `init` does, and the Review page holds it from there. The sentence while the old backend is
    /// still up with other settings than the saved ones; null, and 150A's way on alone, when the
    /// saved settings are the ones in force or when no backend is up.
    /// </summary>
    [Theory]
    [InlineData("other settings, the old backend still up")]
    [InlineData("the same settings, the old backend still up")]
    [InlineData("the old backend stopped")]
    public void TheWordThatARestartWhichWaitedFailedSaysWhetherTheSavedSettingsAreInForce(string state)
    {
        const string Stopped = "FICT the backend did not answer /health within 30 seconds.";
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        string said;
        switch (state)
        {
            case "other settings, the old backend still up":
                SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "after waiting", ASwitchToGemini());
                said = LauncherGone + ". " + NotInForce;
                break;

            case "the same settings, the old backend still up":
                SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "after waiting", Save());
                said = LauncherGone + ". " + RetryTheRestart;
                break;

            default:
                world.Backend.RestartFailure = new BackendStartException(Stopped);
                SaveAsATurnStarts(world, "save", ASwitchToGemini());
                world.Backend.EndTurn("chat-1");
                Eventually(
                    () => world.Posted("status").Any(status =>
                        status.GetProperty("message").GetString()!.StartsWith(Stopped, StringComparison.Ordinal)),
                    "the failure's status");
                said = Stopped + " " + RetryTheRestart;
                break;
        }

        JsonElement failure = world.Last("status");
        Assert.Equal("error", failure.GetProperty("stage").GetString());
        Assert.Equal(said, failure.GetProperty("message").GetString());
        JsonElement inForce = failure.GetProperty("settings_not_in_force");
        if (state == "other settings, the old backend still up")
        {
            Assert.Equal(NotInForce, inForce.GetString());
        }
        else
        {
            Assert.Equal(JsonValueKind.Null, inForce.ValueKind);
        }
    }

    /// <summary>
    /// Found on review (S2): while the saved settings are not in force the backend holds the key it
    /// was started with - here the OpenAI key, after a switch to Gemini whose restart failed before
    /// the old backend stopped - and the host masks it as it masks the saved key: a session's
    /// failure that quotes it reaches the page masked, in the `status` and in the review's refusal.
    /// The backend masks the keys in its own environment as well; this is the add-in's layer, which
    /// masked only the saved key. With no switch the key the backend holds is the saved one, masked
    /// before and after (a guard).
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void TheKeyTheBackendWasStartedWithIsMaskedAsTheSavedKeyIs(bool switched)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        if (switched)
        {
            SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", ASwitchToGemini());
        }

        world.Backend.SessionFailure = new BackendRequestException(
            "ProviderError", "FICT the provider refused the key " + OpenAiKey, retryable: false);

        world.Receive("review.start", "start", new { });

        string refusal = world.Reply("error", "start").GetProperty("message").GetString()!;
        Assert.StartsWith("FICT the provider refused the key ", refusal, StringComparison.Ordinal);
        Assert.EndsWith(Redaction.Mask, refusal, StringComparison.Ordinal);
        Assert.EndsWith(Redaction.Mask, world.Last("status").GetProperty("message").GetString()!, StringComparison.Ordinal);
        world.AssertNothingPostedContains(OpenAiKey);
    }

    /// <summary>
    /// ...and the keys the host masks, which the add-in hands every other tab to mask, are the saved
    /// key and the key the backend that is up was started with: both while they differ, and the
    /// saved one alone, as before, once a restart has put the saved settings in force.
    /// </summary>
    [Fact]
    public void TheKeysToMaskAreTheSavedKeyAndTheKeyTheBackendWasStartedWith()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        Assert.Equal(new string?[] { OpenAiKey }, world.Host.KeysToMask().Distinct());

        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", ASwitchToGemini());
        Assert.Equal(
            new string?[] { GeminiKey, OpenAiKey },
            world.Host.KeysToMask().OrderBy(key => key, StringComparer.Ordinal));

        world.Backend.EarlyRestartFailure = null;
        world.Receive("settings.save", "again", ASwitchToGemini());
        world.Reply("settings.saved", "again");
        Assert.Equal(new string?[] { GeminiKey }, world.Host.KeysToMask().Distinct());
    }

    /// <summary>
    /// ...and the add-in hands every other tab those keys to mask - read through the review host's
    /// field per call, as it read the saved key, and with no review host the default settings' key,
    /// as before - the Remodel tab its bridge's secret besides. The add-in cannot be built without a
    /// live SOLIDWORKS, so its source is read, as the wiring tests do.
    /// </summary>
    [Fact]
    public void TheAddInHandsEveryOtherTabTheKeysTheReviewHostMasks()
    {
        string source = OtherTabsBackendRestartTests.AddInSource();
        Assert.Contains(
            "private IEnumerable<string?> KeysToMask() => _reviewHost?.KeysToMask() "
                + "?? new[] { UserSettings.Defaults().ResolveApiKey().Key };",
            source,
            StringComparison.Ordinal);

        foreach ((string start, string end) in new[]
        {
            ("_modelCheckHost = new ModelCheckHost(new ModelCheckHostOptions(", "StartModelCheckPump();"),
            ("_standardsHost = new StandardsHost(new StandardsHostOptions(", "StartStandardsPump();"),
        })
        {
            string options = OtherTabsBackendRestartTests.Between(source, start, end);
            Assert.Contains("Secrets = KeysToMask,", options, StringComparison.Ordinal);
            Assert.DoesNotContain("ResolveApiKey()", options, StringComparison.Ordinal);
        }

        string remodel = OtherTabsBackendRestartTests.Between(
            source, "_remodelHost = new RemodelHost(new RemodelHostOptions(", "StartRemodelPump();");
        Assert.Contains(
            "Secrets = () => KeysToMask().Concat(new[] { _toolService?.RemodelBridge?.Secret }),",
            remodel,
            StringComparison.Ordinal);
        Assert.DoesNotContain("ResolveApiKey()", remodel, StringComparison.Ordinal);
    }

    /// <summary>
    /// Found on review (N5): a setting the backend's start does not read for the provider is no part
    /// of what is in force. The base URL is read for openai alone - trimmed, and a blank one is none -
    /// and Gemini Enterprise for gemini alone (`BackendClient.StartOptions`), so a settings file
    /// edited by hand to carry one, saved again through the pane with the same settings, whose
    /// restart fails before the old backend stops, leaves the saved settings in force: `init` says
    /// nothing. They were compared for every provider, and said the saved settings were not in force.
    /// </summary>
    [Theory]
    [InlineData("Gemini Enterprise, for openai")]
    [InlineData("a base URL, for gemini")]
    [InlineData("a blank base URL, for openai")]
    [InlineData("a base URL spaced otherwise, for openai")]
    public void ASettingTheBackendDoesNotReadForItsProviderIsNoPartOfWhatIsInForce(string setting)
    {
        using var world = new RestartWorld();
        Dictionary<string, object?> payload;
        switch (setting)
        {
            case "Gemini Enterprise, for openai":
                world.Settings.GeminiEnterprise = new GeminiEnterpriseSettings
                {
                    Project = "fict-project",
                    Location = "fict-location",
                };
                payload = Save();
                break;

            case "a base URL, for gemini":
                world.Settings.Provider = "gemini";
                world.Settings.Model = "gemini-3.5-flash";
                world.Settings.SetApiKey(GeminiKey);
                world.Settings.BaseUrl = "https://fict-gateway.invalid/v1";
                payload = Save(provider: "gemini", model: "gemini-3.5-flash");
                break;

            case "a blank base URL, for openai":
                world.Settings.BaseUrl = "   ";
                payload = Save();
                break;

            default:
                world.Settings.BaseUrl = "https://fict-gateway.invalid/v1 ";
                payload = Save(baseUrl: "https://fict-gateway.invalid/v1");
                break;
        }

        world.Open();
        world.Track("chat-1");

        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", payload);

        Assert.Equal(JsonValueKind.Null, Init(world, "init").GetProperty("settings_not_in_force").ValueKind);
    }

    /// <summary>
    /// Found on review (C1): the add-in makes its first start of the backend through the host
    /// (<see cref="ReviewHost.FirstStart"/>), under the lock every settings restart takes, with the
    /// settings saved when it is made, which it records as in force by the same transition a restart
    /// records them by. With nothing saved since the add-in loaded, the backend starts with the
    /// settings loaded, and the backend, the settings in force, the sessions and the keys masked agree.
    /// </summary>
    [Fact]
    public void TheFirstStartStartsTheBackendWithTheSavedSettingsAndRecordsThemInForce()
    {
        using var world = new RestartWorld();
        world.Backend.Down = true;
        world.Open();

        Assert.True(FirstStart(world));

        (UserSettings started, ResolvedApiKey key) = Assert.Single(world.Backend.Restarts);
        Assert.Equal("openai", started.Provider);
        Assert.Equal(OpenAiKey, key.Key);
        Assert.Equal(1, world.Backend.Generation);
        AssertTheBackendAndTheSettingsInForceAgree(world, "openai", "gpt-5.6", "high", OpenAiKey);
    }

    /// <summary>
    /// The ordering Codex found (C1): the first start's thread-pool item comes late, after a save whose
    /// restart has started the backend with the saved settings and recorded them. The first start
    /// finds that backend up and starts nothing: a second start, with the settings loaded, would have
    /// replaced it, leaving the saved settings recorded in force on a backend started with others; a
    /// second start with the saved ones would end any review already running on it. The backend, the
    /// settings in force, the sessions and the keys masked agree.
    /// </summary>
    [Fact]
    public void AFirstStartThatComesAfterASavesRestartStartedTheBackendStartsNothing()
    {
        using var world = new RestartWorld();
        world.Backend.Down = true;
        world.Open();
        world.Receive("settings.save", "save", ASwitchToGemini());
        world.Reply("settings.saved", "save");
        Assert.Equal(1, world.Backend.Generation);

        Assert.False(FirstStart(world));

        Assert.Equal(1, world.Backend.Generation);
        Assert.Equal(1, world.Backend.RestartsAsked);
        AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
    }

    /// <summary>
    /// The ordering recorded as O2: a save whose restart failed before the first start was made -
    /// before it stopped anything, or with nothing up to stop - leaves no backend, and the first start,
    /// made then, starts the backend with the settings saved by then and records them; it recorded
    /// none, and the settings loaded stayed recorded in force on a backend started with the saved ones.
    /// </summary>
    [Theory]
    [InlineData("before it stopped anything")]
    [InlineData("with nothing up to stop")]
    public void AFirstStartAfterASaveWhoseRestartFailedStartsWithTheSavedSettingsAndRecordsThem(string failed)
    {
        using var world = new RestartWorld();
        world.Backend.Down = true;
        if (failed == "before it stopped anything")
        {
            world.Backend.EarlyRestartFailure = new BackendStartException(LauncherGone);
        }
        else
        {
            world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
        }

        world.Open();
        world.Receive("settings.save", "save", ASwitchToGemini());
        Assert.Equal("BackendNotRestarted", world.Reply("error", "save").GetProperty("error_class").GetString());
        world.Backend.EarlyRestartFailure = null;
        world.Backend.RestartFailure = null;

        Assert.True(FirstStart(world));

        (UserSettings started, ResolvedApiKey key) = Assert.Single(world.Backend.Restarts);
        Assert.Equal("gemini", started.Provider);
        Assert.Equal(GeminiKey, key.Key);
        AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
    }

    /// <summary>
    /// The first start and a save's restart never overlap, whichever begins first: one lock is held
    /// for the whole of either, and the second sees what the first did. A save's restart being made
    /// holds the first start back, and the first start, let go, finds the backend it started and
    /// starts nothing - Codex's ordering, made certain. A first start being made holds a save's restart
    /// back, and the restart, let go, replaces the backend the first start made with one started with
    /// the saved settings, and records them.
    /// </summary>
    [Theory]
    [InlineData("the save's restart")]
    [InlineData("the first start")]
    public void TheFirstStartAndASavesRestartNeverOverlap(string first)
    {
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Backend.Down = true;
            world.Backend.Hold = hold;
            world.Open();

            Caller<bool> earlier = first == "the save's restart"
                ? new Caller<bool>(() =>
                {
                    world.Receive("settings.save", "save", ASwitchToGemini());
                    return true;
                })
                : new Caller<bool>(() => FirstStart(world));
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the earlier start never began");

            Caller<bool> later = first == "the save's restart"
                ? new Caller<bool>(() => FirstStart(world))
                : new Caller<bool>(() =>
                {
                    world.Receive("settings.save", "save", ASwitchToGemini());
                    return true;
                });
            Assert.False(later.Finishes(TimeSpan.FromMilliseconds(300)), "the later start did not wait for the earlier");
            Assert.Equal(1, world.Backend.RestartsAsked);

            hold.Set();
            Assert.True(earlier.Finishes(TimeSpan.FromSeconds(10)), "the earlier start never finished");
            Assert.True(later.Finishes(TimeSpan.FromSeconds(10)), "the later start never finished");
            world.Reply("settings.saved", "save");

            if (first == "the save's restart")
            {
                Assert.False(later.Result);
                Assert.Equal(1, world.Backend.Generation);
            }
            else
            {
                Assert.True(earlier.Result);
                Assert.Equal(new[] { "openai", "gemini" }, world.Backend.Restarts.Select(restart => restart.Settings.Provider));
                Assert.Equal(2, world.Backend.Generation);
            }

            AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// A first start that fails records nothing - no backend is up, so nothing is in force - and its
    /// failure is thrown to the add-in, which tells every page as before, with 150A's way on; a save
    /// then starts the backend with its settings, which are in force from then on.
    /// </summary>
    [Fact]
    public void AFirstStartThatFailsRecordsNothingAndIsThrownToTheAddIn()
    {
        using var world = new RestartWorld();
        world.Backend.Down = true;
        world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
        world.Open();

        BackendStartException thrown = Assert.Throws<BackendStartException>(() => FirstStart(world));
        Assert.Equal("FICT the backend would not start", thrown.Message);
        Assert.Null(world.Backend.Endpoint);
        Assert.Equal(JsonValueKind.Null, Init(world, "init").GetProperty("settings_not_in_force").ValueKind);

        world.Backend.RestartFailure = null;
        world.Receive("settings.save", "save", ASwitchToGemini());
        world.Reply("settings.saved", "save");
        AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
    }

    /// <summary>
    /// Once the host is disposed - the add-in unloading - a first start starts nothing, and is thrown
    /// to the add-in, which logs that the backend did not start, as a start the unloading backend
    /// client refused was.
    /// </summary>
    [Fact]
    public void AFirstStartOnceTheHostIsDisposedStartsNothing()
    {
        using var world = new RestartWorld();
        world.Backend.Down = true;
        world.Open();
        world.Host.Dispose();

        Assert.Throws<ObjectDisposedException>(() => FirstStart(world));
        Assert.Equal(0, world.Backend.RestartsAsked);
    }

    /// <summary>
    /// The add-in makes its first start through the review host, queued with nothing read beforehand:
    /// it tells every page the backend is starting, starts it through <see cref="ReviewHost.FirstStart"/>
    /// with the backend client's own start, and says it is ready - and on a failure, as before, tells
    /// every page the way on (150A). The add-in cannot be built without a live SOLIDWORKS, so its source
    /// is read, as the wiring tests do.
    /// </summary>
    [Fact]
    public void TheAddInMakesItsFirstStartThroughTheReviewHost()
    {
        string source = OtherTabsBackendRestartTests.AddInSource();
        Assert.Contains("ThreadPool.QueueUserWorkItem(_ => StartBackend());", source, StringComparison.Ordinal);
        Assert.DoesNotContain("UserSettings settings = _reviewHost.Settings;", source, StringComparison.Ordinal);

        string start = OtherTabsBackendRestartTests.Between(
            source, "private void StartBackend() {", "Report(\"The SwReview backend did not start.\", failure);");
        Assert.Contains(
            "PostStatusToPages(\"backend_starting\", \"Starting the review backend...\"); "
                + "_reviewHost?.FirstStart((settings, key) => _backend?.Start(settings, key)); "
                + "PostStatusToPages(\"ready\", \"Backend ready.\");",
            start,
            StringComparison.Ordinal);
        Assert.Single(System.Text.RegularExpressions.Regex.Matches(source, @"_backend\?\.Start\(")
            .Cast<System.Text.RegularExpressions.Match>());
    }

    /// <summary>
    /// Found on review (C2): `init` and the word that a restart which waited failed each carry, with
    /// whether the saved settings are in force, the number of that reading - one past the last such
    /// reading's, in the order the host took them (`settings_not_in_force_revision`) - so the page can
    /// tell an `init` read before the failure and delivered after it from one read since. Read while
    /// the restart waited, `init` says nothing, numbered below the failure's word, which says the
    /// sentence; read after it, `init` says the sentence too, numbered above.
    /// </summary>
    [Fact]
    public void EachWordOnTheSettingsInForceIsNumberedInTheOrderItWasRead()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        world.Backend.EarlyRestartFailure = new BackendStartException(LauncherGone);
        SaveAsATurnStarts(world, "save", ASwitchToGemini());
        world.Reply("settings.saved", "save");

        JsonElement whileItWaited = Init(world, "waiting");
        Assert.Equal(JsonValueKind.Null, whileItWaited.GetProperty("settings_not_in_force").ValueKind);
        long readWhileItWaited = whileItWaited.GetProperty("settings_not_in_force_revision").GetInt64();

        // The turn ends, and the next review makes the restart, which fails before the old backend stops.
        world.Backend.EndTurn("chat-1");
        world.Receive("review.start", "start", new { });
        world.Reply("error", "start");
        JsonElement failure = world.Last("status");
        Assert.Equal(NotInForce, failure.GetProperty("settings_not_in_force").GetString());
        long failed = failure.GetProperty("settings_not_in_force_revision").GetInt64();
        Assert.True(failed > readWhileItWaited, $"the failure's word, {failed}, is not numbered above {readWhileItWaited}");

        JsonElement since = Init(world, "since");
        Assert.Equal(NotInForce, since.GetProperty("settings_not_in_force").GetString());
        Assert.True(
            since.GetProperty("settings_not_in_force_revision").GetInt64() > failed,
            "an init read after the failure's word is not numbered above it");
    }

    /// <summary>
    /// ...and a reading and its number are taken together, under one lock, so the numbers follow the
    /// readings when two are taken at once (C2). An `init` held inside its reading - once it has the
    /// settings it compares, before it has compared them - while a save puts the saved settings in
    /// force, is numbered below an `init` read after that save, which waits for it: its reading is
    /// the older, and the page, taking only a higher number, keeps the newer. A reading taken apart
    /// from its number would leave the older reading with the higher number, for the page to keep.
    /// </summary>
    [Fact]
    public void AReadingAndItsNumberAreTakenTogetherSoTheNumbersFollowTheReadings()
    {
        string workstationKey = string.Concat("FICT", "-env-", "openai-", "153a-0004");
        using var looks = new ThreadLocal<int>();
        using var reading = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        using var world = new RestartWorld();
        try
        {
            // The key comes from the workstation's environment, so each reading looks it up: the first
            // `init`'s second look is its reading's, made once it holds the settings it compares.
            world.Settings.ApiKeyProtected = null;
            world.WorkstationEnvironment = name =>
            {
                if (looks.Value > 0 && ++looks.Value == 3)
                {
                    reading.Set();
                    letGo.Wait(TimeSpan.FromSeconds(15));
                }

                return name == "OPENAI_API_KEY" ? workstationKey : null;
            };
            world.Open();
            world.Track("chat-1");
            SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", Save(model: "gpt-5.6-mini"));
            world.Backend.EarlyRestartFailure = null;

            var older = new Caller<bool>(() =>
            {
                looks.Value = 1;
                Init(world, "older");
                return true;
            });
            Assert.True(reading.Wait(TimeSpan.FromSeconds(10)), "the first init never reached its reading");

            world.Receive("settings.save", "in force", Save(model: "gpt-5.6-mini"));
            world.Reply("settings.saved", "in force");
            var newer = new Caller<bool>(() =>
            {
                Init(world, "newer");
                return true;
            });
            newer.Finishes(TimeSpan.FromMilliseconds(300));

            letGo.Set();
            Assert.True(older.Finishes(TimeSpan.FromSeconds(10)), "the older init never finished");
            Assert.True(newer.Finishes(TimeSpan.FromSeconds(10)), "the newer init never finished");
            Assert.True(older.Result);
            Assert.True(newer.Result);
            JsonElement olderInit = world.Reply("init", "older");
            JsonElement newerInit = world.Reply("init", "newer");
            Assert.Equal(NotInForce, olderInit.GetProperty("settings_not_in_force").GetString());
            Assert.Equal(JsonValueKind.Null, newerInit.GetProperty("settings_not_in_force").ValueKind);
            Assert.True(
                olderInit.GetProperty("settings_not_in_force_revision").GetInt64()
                    < newerInit.GetProperty("settings_not_in_force_revision").GetInt64(),
                "the older reading is not numbered below the newer");
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// Codex's re-review (R1): every start publishes the backend's endpoint before it records the settings
    /// it was made with, and an `init` read between the two found the backend up with the settings
    /// recorded before - here the settings loaded, after a save that switched the provider failed with no
    /// backend up, so the first start was made with the saved ones - and said the saved settings were not
    /// in force. The page held that sentence: `ready` asks nothing more of a page that has the backend.
    /// While a start is under way `init` says nothing of the settings in force, as while a restart waits
    /// or is being made; nothing posted carries the sentence; and once the start is over the backend and
    /// the settings in force agree.
    /// </summary>
    [Fact]
    public void AnInitReadWhileTheFirstStartIsUnderWaySaysNothingOfTheSettingsInForce()
    {
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            Caller<bool> first = FirstStartHeldOncePublished(world, published, letGo);

            JsonElement meanwhile = Init(world, "meanwhile");
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);

            Assert.Equal(JsonValueKind.Null, meanwhile.GetProperty("settings_not_in_force").ValueKind);
            AssertNothingPostedCarriesTheSentence(world);
            AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// ...and a session asked for in that window took its provider, model and effort from the settings
    /// recorded before - the settings loaded, OpenAI's - on the backend the start had published, started
    /// with Gemini's environment: the pairing 153A ended (R1, the same window). It is refused as one asked
    /// for before the backend is up - `BackendUnavailable`, retryable - and nothing is created; asked for
    /// again once the start is over, it takes the saved settings. Every way a session is asked for that
    /// can meet that window with no backend up before it: a review, a recheck of a review that waits, and
    /// a review with engineering context prepared in the window.
    /// </summary>
    [Theory]
    [InlineData("review")]
    [InlineData("recheck")]
    [InlineData("context review")]
    public void ASessionAskedForWhileAStartIsUnderWayIsRefusedAsOneBeforeTheBackendIsUp(string session)
    {
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            Caller<bool> first = FirstStartHeldOncePublished(world, published, letGo);

            JsonElement refused = world.Reply("error", AskForASession(world, session));
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);

            Assert.Equal("BackendUnavailable", refused.GetProperty("error_class").GetString());
            Assert.True(refused.GetProperty("retryable").GetBoolean());
            Assert.Empty(world.Backend.Sessions);
            AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// ...and the keys masked (R1, the same window): from the moment a start is made until it has recorded
    /// the settings it was made with, the backend it starts holds their key, which neither the saved
    /// settings nor those recorded in force need name - here a second save, made while the first start is
    /// under way, has replaced the saved ones and waits for that start to end. Every host masks the key of
    /// a start under way as well; once the second save's restart is made, the backend, the settings in
    /// force and the keys masked agree on its key.
    /// </summary>
    [Fact]
    public void TheKeyAStartUnderWayWasMadeWithIsMasked()
    {
        string thirdKey = string.Concat("FICT", "-saved-", "openai-", "153a-0005");
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            Caller<bool> first = FirstStartHeldOncePublished(world, published, letGo);
            var second = new Caller<bool>(() =>
            {
                world.Receive("settings.save", "second", Save(apiKey: thirdKey));
                return true;
            });
            Eventually(() => world.Host.Settings.Provider == "openai", "the second save's settings");

            IReadOnlyList<string?> masked = world.Host.KeysToMask();
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(second.Finishes(TimeSpan.FromSeconds(10)), "the second save never finished");
            Assert.True(first.Result);
            Assert.True(second.Result);
            world.Reply("settings.saved", "second");

            Assert.Contains(GeminiKey, masked);
            Assert.Contains(thirdKey, masked);
            Assert.Contains(OpenAiKey, masked);
            AssertTheBackendAndTheSettingsInForceAgree(world, "openai", "gpt-5.6", "high", thirdKey);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// The same window in a restart, checked on the re-review (R1): a restart, too, publishes the new
    /// backend's endpoint before it records the settings it was made with, and an `init` read between the
    /// two says nothing of the settings in force either. A save's restart made at once is marked as being
    /// made for its whole length, the record included, and one that waited stays waiting until it has
    /// ended; both stand before new work (<see cref="ReviewHost.RestartAhead"/>), which `init` reads.
    /// Guards: they held before the re-review's change. The save's restart is made on a thread of its own
    /// here, which the one page pump never does, so that the reading itself is pinned; one that waited is
    /// made on the watcher's, as it always is.
    /// </summary>
    [Theory]
    [InlineData("a save's, made at once")]
    [InlineData("one that waited")]
    public void AnInitReadWhileARestartIsUnderWaySaysNothingOfTheSettingsInForce(string restart)
    {
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            world.Open();
            HoldTheStartOncePublished(world, published, letGo);
            Caller<bool>? save = null;
            if (restart == "a save's, made at once")
            {
                save = new Caller<bool>(() =>
                {
                    world.Receive("settings.save", "save", ASwitchToGemini());
                    return true;
                });
            }
            else
            {
                world.Track("chat-1");
                SaveAsATurnStarts(world, "save", ASwitchToGemini());
                world.Backend.EndTurn("chat-1");
            }

            Assert.True(published.Wait(TimeSpan.FromSeconds(10)), "the restart never started the backend");
            JsonElement meanwhile = Init(world, "meanwhile");
            letGo.Set();
            if (save != null)
            {
                Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
                Assert.True(save.Result);
            }

            Eventually(() => !world.Host.RestartAhead && world.Backend.Generation == 1, "the restart's end");
            world.Reply("settings.saved", "save");

            Assert.Equal(JsonValueKind.Null, meanwhile.GetProperty("settings_not_in_force").ValueKind);
            AssertNothingPostedCarriesTheSentence(world);
            AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// The fourth 153A review (S1): a start's failure is told once the start is no longer under way - a
    /// restart that waited tells it in its `status` and in its word to every other tab - and a save made
    /// while the start was under way has by then replaced the saved key, while nothing records the key
    /// the start was made with, which its failure can name. Here a restart that waited, made with key A,
    /// fails naming A while a save of key B waits for it; a remodel run, begun meanwhile, keeps that
    /// save's restart waiting, so A's failure is all that is told. Neither the Review page nor any other
    /// tab is told A: every key a start has been made with is masked.
    /// </summary>
    [Fact]
    public void TheFailureOfARestartThatWaitedIsToldWithItsKeyMaskedThoughASaveReplacedTheKey()
    {
        string keyA = string.Concat("FICT", "-saved-", "openai-", "153a-0006");
        string keyB = string.Concat("FICT", "-saved-", "openai-", "153a-0007");
        int remodelRun = 0;
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.BackendBusy = () => Volatile.Read(ref remodelRun) == 1;
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save-a", Save(effort: "low", apiKey: keyA));
            world.Reply("settings.saved", "save-a");
            world.Backend.Hold = hold;
            world.Backend.RestartFailure = new InvalidOperationException(
                "FICT the job object refused the child started with " + keyA);
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the restart that waited never began");

            Volatile.Write(ref remodelRun, 1);
            var saveB = new Caller<bool>(() =>
            {
                world.Receive("settings.save", "save-b", Save(effort: "medium", apiKey: keyB));
                return true;
            });
            Eventually(() => world.Host.Settings.Effort == "medium", "the second save's settings");

            hold.Set();
            Assert.True(saveB.Finishes(TimeSpan.FromSeconds(10)), "the second save never finished");
            Assert.True(saveB.Result);
            Eventually(() => world.FailuresToldToTheOtherTabs.Length > 0, "the failure told to the other tabs");

            Assert.True(
                world.Posted("status").Any(status =>
                    status.GetProperty("message").GetString()!.StartsWith("FICT the job object refused", StringComparison.Ordinal)),
                "the failure was not told to the Review page");
            Assert.False(world.AnythingPostedContains(keyA), "the Review page is told the key the restart was made with");
            Assert.False(
                world.FailuresToldToTheOtherTabs.Any(told => told.Contains(keyA)),
                "the other tabs are told the key the restart was made with");
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// ...and the add-in's first start (S1): made with the saved Gemini key after a save that switched the
    /// provider failed with no backend up, it fails naming that key while a save of another key waits for
    /// it, and that save's restart has begun before the add-in, on the first start's thread, tells the
    /// Review page and writes its log line. A single place for the key of the last start made would hold
    /// the second save's key by then; every key a start has been made with is masked, so neither the page
    /// nor the log line is told the first start's.
    /// </summary>
    [Fact]
    public void TheFailureOfAFirstStartIsToldWithItsKeyMaskedThoughASaveReplacedTheKeyAndRestarted()
    {
        string keyB = string.Concat("FICT", "-saved-", "openai-", "153a-0008");
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        using var entered = new ManualResetEventSlim(false);
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            int attempts = world.Backend.Attempts;
            world.Backend.Hold = hold;
            world.Backend.RestartFailure = new InvalidOperationException(
                "FICT the job object refused the child started with " + GeminiKey);
            world.Backend.DuringRestart = () =>
            {
                // The second save's restart, after the first start's, succeeds.
                if (world.Backend.Attempts == attempts + 2)
                {
                    world.Backend.RestartFailure = null;
                }

                entered.Set();
            };

            string? logged = null;
            var first = new Caller<bool>(() =>
            {
                try
                {
                    return FirstStart(world);
                }
                catch (Exception failure)
                {
                    // As SwReviewAddIn.StartBackend tells it, once the second save's restart has begun: the
                    // Review page, then the log (Report, which masks through the review host).
                    Eventually(() => world.Backend.Attempts == attempts + 2, "the second save's restart");
                    world.Host.PostStatus("error", ReviewHost.WithTheWayOn(failure.Message, ReviewHost.StartItAgain));
                    logged = world.Host.Redact(failure.ToString());
                    return false;
                }
            });
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the first start never began");

            var saveB = new Caller<bool>(() =>
            {
                world.Receive("settings.save", "save-b", Save(effort: "medium", apiKey: keyB));
                return true;
            });
            Eventually(() => world.Host.Settings.Effort == "medium", "the second save's settings");

            hold.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(saveB.Finishes(TimeSpan.FromSeconds(10)), "the second save never finished");
            Assert.False(first.Result);
            Assert.True(saveB.Result);
            world.Reply("settings.saved", "save-b");

            Assert.True(
                world.Posted("status").Any(status =>
                    status.GetProperty("message").GetString()!.StartsWith("FICT the job object refused", StringComparison.Ordinal)),
                "the failure was not told to the Review page");
            Assert.False(world.AnythingPostedContains(GeminiKey), "the Review page is told the key the first start was made with");
            Assert.True(logged!.Contains("FICT the job object refused"), "the log line does not say the failure");
            Assert.False(logged.Contains(GeminiKey), "the log line names the key the first start was made with");
            AssertTheBackendAndTheSettingsInForceAgree(world, "openai", "gpt-5.6", "medium", keyB);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// ...and while the restart that waited is still under way (S2): its key is among the keys masked,
    /// though a save made meanwhile has replaced the saved key and nothing has recorded the restart's. A
    /// guard, which held before the fourth review: it pins that a restart's start puts its key there, as
    /// the first start's does, where nothing else did.
    /// </summary>
    [Fact]
    public void TheKeyOfARestartThatWaitedIsMaskedWhileItIsUnderWayThoughASaveReplacedTheKey()
    {
        string keyA = string.Concat("FICT", "-saved-", "openai-", "153a-0009");
        string keyB = string.Concat("FICT", "-saved-", "openai-", "153a-0010");
        int remodelRun = 0;
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.BackendBusy = () => Volatile.Read(ref remodelRun) == 1;
            world.Open();
            world.Track("chat-1");
            SaveAsATurnStarts(world, "save-a", Save(effort: "low", apiKey: keyA));
            world.Reply("settings.saved", "save-a");
            world.Backend.Hold = hold;
            world.Backend.EndTurn("chat-1");
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the restart that waited never began");

            Volatile.Write(ref remodelRun, 1);
            var saveB = new Caller<bool>(() =>
            {
                world.Receive("settings.save", "save-b", Save(effort: "medium", apiKey: keyB));
                return true;
            });
            Eventually(() => world.Host.Settings.Effort == "medium", "the second save's settings");

            bool masked = world.Host.KeysToMask().Contains(keyA);
            hold.Set();
            Assert.True(saveB.Finishes(TimeSpan.FromSeconds(10)), "the second save never finished");
            Assert.True(saveB.Result);
            Assert.True(masked, "the key of the restart under way is not among the keys masked");
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// The fourth review (N5): a recheck refused while a start is under way was the one refusal posted after
    /// the `checking` status with no `error` status after it, so the page's badge went on saying "Checking
    /// the saved evidence again..." of a recheck that never ran. A start under way is read before that
    /// status, so the refused recheck posts none.
    /// </summary>
    [Fact]
    public void ARecheckRefusedWhileAStartIsUnderWayPostsNoCheckingWord()
    {
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            Caller<bool> first = FirstStartHeldOncePublished(world, published, letGo);

            JsonElement refused = world.Reply("error", AskForASession(world, "recheck"));
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);

            Assert.Equal("BackendUnavailable", refused.GetProperty("error_class").GetString());
            Assert.False(
                world.Posted("status").Any(status => status.GetProperty("stage").GetString() == "checking"),
                "a checking status was posted for the refused recheck");
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// The fourth review (N3, the reading order its MR3 named): whether the saved settings are in force is
    /// read with the backend first and the start under way after it, so a start whose endpoint the reading
    /// found is seen still under way, or has recorded its settings. Here the first start begins, and
    /// publishes the backend's endpoint, while an `init` reads that endpoint for whether the saved settings
    /// are in force - after it read the backend, none, for its `backend` - and the `init` says nothing of
    /// the settings in force. Read the other way round, the reading found no start under way, then the
    /// backend up with the settings loaded still recorded, and said the saved settings were not in force.
    /// </summary>
    [Fact]
    public void WhetherTheSavedSettingsAreInForceIsReadWithTheBackendBeforeTheStartUnderWay()
    {
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            HoldTheStartOncePublished(world, published, letGo);
            int reader = Thread.CurrentThread.ManagedThreadId;
            int reads = 0;
            Caller<bool>? first = null;
            bool publishedInTime = false;
            world.Backend.EndpointRead = () =>
            {
                // `init` reads the backend twice: for its `backend`, then for whether the saved settings
                // are in force. The first start begins, and publishes the endpoint, inside the second.
                if (Thread.CurrentThread.ManagedThreadId == reader && ++reads == 2)
                {
                    first = new Caller<bool>(() => FirstStart(world));
                    publishedInTime = published.Wait(TimeSpan.FromSeconds(10));
                }
            };

            JsonElement init = Init(world, "init");
            world.Backend.EndpointRead = null;
            letGo.Set();
            Assert.True(publishedInTime, "the first start never started the backend inside the init's reading");
            Assert.True(first!.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);

            Assert.Equal(JsonValueKind.Null, init.GetProperty("backend").ValueKind);
            Assert.Equal(JsonValueKind.Null, init.GetProperty("settings_not_in_force").ValueKind);
            AssertTheBackendAndTheSettingsInForceAgree(world, "gemini", "gemini-3.5-flash", "low", GeminiKey);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>The first start the add-in makes, through the host, of the world's backend.</summary>
    private static bool FirstStart(RestartWorld world) =>
        world.Host.FirstStart((settings, key) => world.Backend.Restart(settings, key));

    /// <summary>
    /// The add-in loaded with no backend up, then a save that switched the provider to Gemini whose restart
    /// failed with nothing up to stop: the settings loaded, OpenAI's, stay recorded in force, the saved
    /// ones are Gemini's, and no backend is up (Codex's re-review, R1).
    /// </summary>
    private static void ASaveThatSwitchedTheProviderFailedWithNoBackendUp(RestartWorld world)
    {
        world.Backend.Down = true;
        world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
        world.Open();
        world.Receive("settings.save", "save", ASwitchToGemini());
        Assert.Equal("BackendNotRestarted", world.Reply("error", "save").GetProperty("error_class").GetString());
        world.Backend.RestartFailure = null;
        Assert.Null(world.Backend.Endpoint);
    }

    /// <summary>
    /// Holds each start of the world's backend - the first, or a restart - once it has started the backend,
    /// its endpoint published, and before the host records the settings it was made with: sets
    /// <paramref name="published"/> there, and waits for <paramref name="letGo"/> (R1). A start made once
    /// <paramref name="letGo"/> is set is not held.
    /// </summary>
    private static void HoldTheStartOncePublished(
        RestartWorld world, ManualResetEventSlim published, ManualResetEventSlim letGo)
    {
        world.Backend.Published = () =>
        {
            published.Set();
            letGo.Wait(TimeSpan.FromSeconds(15));
        };
    }

    /// <summary>
    /// The add-in's first start, made on a thread of its own and held once it has published the backend's
    /// endpoint, before the host records the settings it was made with (<see cref="HoldTheStartOncePublished"/>).
    /// </summary>
    private static Caller<bool> FirstStartHeldOncePublished(
        RestartWorld world, ManualResetEventSlim published, ManualResetEventSlim letGo)
    {
        HoldTheStartOncePublished(world, published, letGo);
        var first = new Caller<bool>(() => FirstStart(world));
        Assert.True(published.Wait(TimeSpan.FromSeconds(10)), "the first start never started the backend");
        Assert.NotNull(world.Backend.Endpoint);
        return first;
    }

    /// <summary>No `init` and no `status` posted so far says the saved settings are not in force.</summary>
    private static void AssertNothingPostedCarriesTheSentence(RestartWorld world) =>
        Assert.DoesNotContain(
            world.Posted("init").Concat(world.Posted("status")),
            payload => payload.TryGetProperty("settings_not_in_force", out JsonElement sentence)
                && sentence.ValueKind == JsonValueKind.String);

    /// <summary>
    /// The backend that is up was started with the settings recorded in force, which are the saved
    /// ones: `init` says nothing of the settings in force, a review takes that provider, model and
    /// effort, and the keys masked are that key and every key a start was made with - since the fourth
    /// review (S1), when they were that key alone.
    /// </summary>
    private static void AssertTheBackendAndTheSettingsInForceAgree(
        RestartWorld world, string provider, string model, string effort, string key)
    {
        Assert.NotNull(world.Backend.Endpoint);
        UserSettings started = world.Backend.Restarts.Last().Settings;
        Assert.Equal(provider, started.Provider);
        Assert.Equal(JsonValueKind.Null, Init(world, "agree").GetProperty("settings_not_in_force").ValueKind);
        string?[] expected = new string?[] { key }.Concat(world.Backend.KeysAsked)
            .Distinct().OrderBy(entry => entry, StringComparer.Ordinal).ToArray();
        string?[] masked = world.Host.KeysToMask().Distinct().OrderBy(entry => entry, StringComparer.Ordinal).ToArray();
        Assert.True(
            expected.SequenceEqual(masked),
            $"the keys masked are not the backend's key and every key a start was made with: {masked.Length} masked, "
                + $"{expected.Length} expected (the keys themselves are not printed)");

        NewSessionRequest request = MakeASession(world, "review");
        Assert.Equal(provider, request.Provider);
        Assert.Equal(model, request.Model);
        Assert.Equal(effort, request.Effort);
        Assert.Equal(world.Backend.Generation, world.Backend.Sessions.Last().Generation);
    }

    /// <summary>A switch from the world's OpenAI settings to Gemini, with a Gemini key and another model and effort.</summary>
    private static Dictionary<string, object?> ASwitchToGemini() =>
        Save(provider: "gemini", model: "gemini-3.5-flash", effort: "low", apiKey: GeminiKey);

    /// <summary>
    /// A save of <paramref name="payload"/> whose restart fails before it stops the old backend - the
    /// launcher cannot be resolved - made at once, or after waiting for a turn on chat-1, which the
    /// caller tracks. Either way nothing waits afterwards, and the old backend is still up.
    /// </summary>
    private static void SaveWhoseRestartFailsBeforeTheOldBackendStops(RestartWorld world, string when, object payload)
    {
        world.Backend.EarlyRestartFailure = new BackendStartException(LauncherGone);
        if (when == "at once")
        {
            world.Receive("settings.save", "save", payload);
            Assert.Equal("BackendNotRestarted", world.Reply("error", "save").GetProperty("error_class").GetString());
        }
        else
        {
            SaveAsATurnStarts(world, "save", payload);
            world.Reply("settings.saved", "save");
            world.Backend.EndTurn("chat-1");
            Eventually(
                () => world.Posted("status").Any(status =>
                    status.GetProperty("message").GetString()!.StartsWith(LauncherGone, StringComparison.Ordinal)),
                "the failure's status");
        }

        Assert.False(world.Host.RestartAhead);
        Assert.NotNull(world.Backend.Endpoint);
        Assert.Equal(0, world.Backend.Generation);
    }

    /// <summary>The `init` the host answers a `ready` with.</summary>
    private static JsonElement Init(RestartWorld world, string id)
    {
        world.Receive("ready", id, new { });
        return world.Reply("init", id);
    }

    /// <summary>
    /// Makes the session <paramref name="session"/> names and answers the request the backend was
    /// asked to create it with: a review; a recheck of a review that waits; a review with saved
    /// engineering context (feature 016); or that review's Retry (owner decision 108A).
    /// </summary>
    private static NewSessionRequest MakeASession(RestartWorld world, string session)
    {
        switch (session)
        {
            case "review":
                world.Reply("review.started", AskForASession(world, session));
                break;

            case "recheck":
                world.Reply("review.rechecked", AskForASession(world, session));
                break;

            case "context review":
                ReviewWithContext(world);
                break;

            case "context retry":
                string chatId = ReviewWithContext(world).GetProperty("chat_id").GetString()!;
                world.Receive("review.start", "retry", new { retry_of = chatId });
                world.Reply("review.started", "retry");
                break;

            default:
                throw new ArgumentOutOfRangeException(nameof(session), session, "no such session");
        }

        return world.Backend.Sessions.Last().Request;
    }

    /// <summary>
    /// Asks for the session <paramref name="session"/> names, and answers the id its reply echoes: a
    /// review; a recheck of a review that waits; or a review with saved engineering context, the context
    /// prepared first (feature 016).
    /// </summary>
    private static string AskForASession(RestartWorld world, string session)
    {
        switch (session)
        {
            case "review":
                world.Receive("review.start", "start", new { });
                return "start";

            case "recheck":
                world.Track("waiting");
                world.Receive("review.recheck", "recheck", new { chat_id = "waiting" });
                return "recheck";

            case "context review":
                world.Receive("context.prepare", "prepare", new { });
                JsonElement prepared = world.Reply("context.prepared", "prepare");
                world.Receive("context.review", "context", new
                {
                    run_id = prepared.GetProperty("run_id").GetString(),
                    context_id = Guid.NewGuid().ToString(),
                    head_digest = new string('a', 64),
                    package_sha256 = prepared.GetProperty("package_sha256").GetString(),
                });
                return "context";

            default:
                throw new ArgumentOutOfRangeException(nameof(session), session, "no such session to ask for");
        }
    }

    /// <summary>Prepares engineering context and reviews with it, answering `review.started`.</summary>
    private static JsonElement ReviewWithContext(RestartWorld world) =>
        world.Reply("review.started", AskForASession(world, "context review"));

    // ---- 14. the run root in force is the settings in force's (owner decision 154A, with 153A) --

    /// <summary>
    /// Owner decision 154A, folded into 153A's record of the settings in force (feature 002 T201): the run root in
    /// force is the one the backend that is up was started with, so it moves whenever that record does - at the
    /// add-in's first start too. A folder chosen for runs in a save whose restart failed with no backend up comes
    /// into force with the first start, which starts the backend with the settings saved by then: every tab makes
    /// its runs under it from then on, and it joins the run roots in force. While the run root in force was a
    /// record of its own, which only a restart moved, the backend ran under the folder chosen and every tab made
    /// its runs under the run root loaded, which that backend refuses.
    /// </summary>
    [Theory]
    [InlineData("before it stopped anything")]
    [InlineData("with nothing up to stop")]
    public void AFolderChosenInASaveWhoseRestartFailedComesIntoForceWithTheFirstStart(string failed)
    {
        using var world = new RestartWorld();
        string loaded = world.Settings.RunRoot;
        string chosen = ChosenRoot(world);
        world.Backend.Down = true;
        if (failed == "before it stopped anything")
        {
            world.Backend.EarlyRestartFailure = new BackendStartException(LauncherGone);
        }
        else
        {
            world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
        }

        world.Open();
        world.Receive("settings.save", "save", Choosing(chosen, Save(effort: "low")));
        Assert.Equal("BackendNotRestarted", world.Reply("error", "save").GetProperty("error_class").GetString());
        world.Backend.EarlyRestartFailure = null;
        world.Backend.RestartFailure = null;
        Assert.Equal(loaded, world.Host.RunRoot);

        Assert.True(FirstStart(world));

        Assert.Equal(chosen, Assert.Single(world.Backend.Restarts).Settings.RunRoot);
        AssertTheBackendAndTheRunRootInForceAgree(world, chosen);
        Assert.Equal(new[] { loaded, chosen }, world.Host.RunRootsInForce);
    }

    /// <summary>
    /// Codex's third finding against 154A, closed by 153A's first start (feature 002 T201): the add-in's first
    /// start and a save's restart never overlap, and the first start takes the settings saved when it is made. A
    /// first start delayed behind a save's restart that brought a folder chosen for runs in finds the backend that
    /// restart started and starts nothing, so it cannot put the run root loaded back; one made first is followed
    /// by the save's restart, which brings the folder chosen in. Either way the backend that is up and the run root
    /// in force agree - the folder chosen - and every run root in force is kept. Each start is held, by the fake
    /// backend, while the other is asked for.
    /// </summary>
    [Theory]
    [InlineData("the save's restart")]
    [InlineData("the first start")]
    public void AFirstStartAndASaveThatChoseAFolderForRunsLeaveTheBackendAndTheRunRootInForceAgreeWhicheverComesFirst(
        string first)
    {
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            string loaded = world.Settings.RunRoot;
            string chosen = ChosenRoot(world);
            world.Backend.Down = true;
            world.Backend.Hold = hold;
            world.Open();
            Func<bool> save = () =>
            {
                world.Receive("settings.save", "save", Choosing(chosen, Save(effort: "low")));
                return true;
            };
            Func<bool> firstStart = () => FirstStart(world);

            var earlier = new Caller<bool>(first == "the save's restart" ? save : firstStart);
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the earlier start never began");
            var later = new Caller<bool>(first == "the save's restart" ? firstStart : save);
            Assert.False(later.Finishes(TimeSpan.FromMilliseconds(300)), "the later start did not wait for the earlier");

            hold.Set();
            Assert.True(earlier.Finishes(TimeSpan.FromSeconds(10)), "the earlier start never finished");
            Assert.True(later.Finishes(TimeSpan.FromSeconds(10)), "the later start never finished");
            world.Reply("settings.saved", "save");

            Assert.Equal(
                first == "the save's restart" ? new[] { chosen } : new[] { loaded, chosen },
                world.Backend.Restarts.Select(restart => restart.Settings.RunRoot));
            AssertTheBackendAndTheRunRootInForceAgree(world, chosen);
            Assert.Equal(new[] { loaded, chosen }, world.Host.RunRootsInForce);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// Owner decision 154A, with 153A's record (feature 002 T201): the run root is among the settings a backend
    /// runs with - it makes runs only under the one it was started with - so a save that changes it, whose restart
    /// fails before the old backend stops, is not in force, and the Review tab is told so by every `init` and by
    /// the status of a restart that waited and failed. The sentence is 153A's, with where every tab makes its runs
    /// meanwhile: the folder for runs the backend was started with, not the one saved, which the Settings panel's
    /// field shows - whether the run root alone changed or other settings with it. `init` names the run root in
    /// force, and its settings the one saved. Changed deliberately for the reviews of 154A's merge, N3: the failed
    /// start adds nothing to the run roots in force, which a start appended before it was made would.
    /// </summary>
    [Theory]
    [InlineData("the run root alone", "at once")]
    [InlineData("the run root alone", "after waiting")]
    [InlineData("the run root and the provider", "at once")]
    [InlineData("the run root and the provider", "after waiting")]
    public void ASaveThatChangesTheRunRootIsNotInForceUntilItRestartsAndInitSaysWhereRunsAreMade(string changed, string when)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        string loaded = world.Host.RunRoot;
        string chosen = ChosenRoot(world);
        Dictionary<string, object?> payload = Choosing(chosen, changed == "the run root alone" ? Save() : ASwitchToGemini());

        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, when, payload);

        if (when == "after waiting")
        {
            Assert.Equal(LauncherGone + ". " + NotInForceWithTheRunRoot, world.Last("status").GetProperty("message").GetString());
        }

        JsonElement init = Init(world, "init");
        Assert.Equal(NotInForceWithTheRunRoot, init.GetProperty("settings_not_in_force").GetString());
        Assert.Equal(loaded, init.GetProperty("run_root").GetString());
        Assert.Equal(chosen, init.GetProperty("settings").GetProperty("run_root").GetString());
        Assert.Equal(loaded, world.Host.RunRoot);
        Assert.Equal(new[] { loaded }, world.Host.RunRootsInForce);
    }

    /// <summary>
    /// ...while a run root saved in another letter case names the same folder, which Windows reads either way: it
    /// is the run root in force - `init` says nothing of the settings in force after its restart failed - and once
    /// a restart brings it in it is not a second run root in force (owner decision 154A, one rule for whether two
    /// run roots are the same).
    /// </summary>
    [Theory]
    [InlineData("its restart failed")]
    [InlineData("its restart was made")]
    public void ARunRootSavedInAnotherLetterCaseIsTheRunRootInForce(string restart)
    {
        using var world = new RestartWorld();
        world.Open();
        string loaded = world.Host.RunRoot;
        string otherCase = loaded.ToUpperInvariant();
        Assert.NotEqual(loaded, otherCase);
        Dictionary<string, object?> payload = Choosing(otherCase, Save());

        if (restart == "its restart failed")
        {
            SaveWhoseRestartFailsBeforeTheOldBackendStops(world, "at once", payload);
            Assert.Equal(JsonValueKind.Null, Init(world, "init").GetProperty("settings_not_in_force").ValueKind);
            Assert.Equal(loaded, world.Host.RunRoot);
        }
        else
        {
            world.Receive("settings.save", "save", payload);
            world.Reply("settings.saved", "save");
            Assert.Equal(otherCase, world.Host.RunRoot);
        }

        Assert.Equal(otherCase, world.Host.Settings.RunRoot);
        Assert.Equal(new[] { loaded }, world.Host.RunRootsInForce);
    }

    /// <summary>
    /// Owner decision 154A, with 153A's record (feature 002 T201): a start of the backend publishes its endpoint
    /// before it records the settings it was made with, and can still fail and leave the backend it would replace -
    /// so while one that would bring another run root into force is under way, neither run root is the one to make
    /// a new run under: the run root for a new run is none, and the Model check, Standards and Remodel tabs refuse
    /// a start on it. Once the start ends it is the one the start left in force: the one it brought in, or, when it
    /// failed, the one before. A start under way that keeps the run root moves nothing, and runs go on under it.
    /// Every start: a save's restart, one that waited for a turn, and the add-in's first. Changed deliberately for
    /// the reviews of 154A's merge, N3: a start's run root joins those in force only once the start has succeeded.
    /// </summary>
    [Theory]
    [InlineData("a save's restart that brings another run root in")]
    [InlineData("a save's restart that fails before the old backend stops")]
    [InlineData("a restart that waited for a turn")]
    [InlineData("the first start, after a save whose restart failed")]
    [InlineData("a save's restart that keeps the run root")]
    public void WhileAStartOfTheBackendIsUnderWayANewRunTakesTheRunRootItLeavesInForce(string start)
    {
        using var world = new RestartWorld();
        using var hold = new ManualResetEventSlim(false);
        try
        {
            string loaded = world.Settings.RunRoot;
            string chosen = ChosenRoot(world);
            Dictionary<string, object?> payload = Choosing(chosen, Save(effort: "low"));
            string after = chosen;
            Caller<bool>? caller = null;
            Func<bool> save = () =>
            {
                world.Receive("settings.save", "save", payload);
                return true;
            };

            switch (start)
            {
                case "a save's restart that brings another run root in":
                    world.Open();
                    world.Backend.Hold = hold;
                    caller = new Caller<bool>(save);
                    break;

                case "a save's restart that fails before the old backend stops":
                    world.Open();
                    world.Backend.Hold = hold;
                    world.Backend.EarlyRestartFailure = new BackendStartException(LauncherGone);
                    caller = new Caller<bool>(save);
                    after = loaded;
                    break;

                case "a restart that waited for a turn":
                    world.Open();
                    world.Track("chat-1");
                    SaveAsATurnStarts(world, "save", payload);
                    world.Reply("settings.saved", "save");
                    world.Backend.Hold = hold;
                    world.Backend.EndTurn("chat-1");
                    break;

                case "the first start, after a save whose restart failed":
                    world.Backend.Down = true;
                    world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
                    world.Open();
                    world.Receive("settings.save", "failed", payload);
                    world.Reply("error", "failed");
                    world.Backend.RestartFailure = null;

                    // The failed restart got past the backend's own check, so the first start is waited for afresh.
                    world.Backend.Entered.Reset();
                    world.Backend.Hold = hold;
                    caller = new Caller<bool>(() => FirstStart(world));
                    break;

                default:
                    payload.Remove("run_root");
                    world.Open();
                    world.Backend.Hold = hold;
                    caller = new Caller<bool>(save);
                    after = loaded;
                    break;
            }

            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the start never began");
            Assert.Equal(loaded, world.Host.RunRoot);
            Assert.Equal(start == "a save's restart that keeps the run root" ? loaded : null, world.Host.RunRootForANewRun());

            hold.Set();
            if (caller != null)
            {
                Assert.True(caller.Finishes(TimeSpan.FromSeconds(10)), "the start never finished");
            }
            else
            {
                Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
            }

            Assert.Equal(after, world.Host.RunRoot);
            Assert.Equal(after, world.Host.RunRootForANewRun());
            Assert.Equal(after == loaded ? new[] { loaded } : new[] { loaded, chosen }, world.Host.RunRootsInForce);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// ...and the Review tab needs no refusal of its own (feature 002 T201): it takes the run root for a new
    /// review's folder once the backend is ready, when the only start that can be under way is the add-in's first,
    /// and a review whose folder was made while that start was bringing another run root in is answered before the
    /// backend is asked for a session - refused while the start is still under way (153A), or, once the start has
    /// brought the other run root in, refused `RunRootChanged`, its folder under a run root no longer in force (the
    /// reviews' F6). The backend is never asked for a session in a folder outside the run root it was started
    /// with. While the run root in force was a record of its own, the first start did not move it, and a review
    /// whose evidence was extracted as the start ended went on in a folder that backend refuses.
    /// </summary>
    [Theory]
    [InlineData("still under way when the session is asked for")]
    [InlineData("over while the evidence was extracted")]
    public void AReviewWhoseFolderIsMadeWhileTheFirstStartBringsAnotherRunRootInIsNotStarted(string start)
    {
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            string loaded = world.Settings.RunRoot;
            string chosen = ChosenRoot(world);
            world.Backend.Down = true;
            world.Backend.RestartFailure = new BackendStartException("FICT the backend would not start");
            world.Open();
            world.Receive("settings.save", "save", Choosing(chosen, Save(effort: "low")));
            world.Reply("error", "save");
            world.Backend.RestartFailure = null;
            Caller<bool> first = FirstStartHeldOncePublished(world, published, letGo);
            if (start == "over while the evidence was extracted")
            {
                world.Dump.OnRun = () =>
                {
                    letGo.Set();
                    Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
                };
            }

            world.Receive("review.start", "start", new { });

            JsonElement error = world.Reply("error", "start");
            if (start == "still under way when the session is asked for")
            {
                Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
                Assert.True(error.GetProperty("retryable").GetBoolean());
            }
            else
            {
                Assert.Equal("RunRootChanged", error.GetProperty("error_class").GetString());
                Assert.Equal(
                    "the run root changed while the evidence was extracted, and the backend makes runs only under the "
                    + "one in force, so the review was not started. Press Review again.",
                    error.GetProperty("message").GetString());
            }

            Assert.Equal(1, world.Dump.Runs);
            Assert.Empty(world.Backend.Sessions);
            Assert.Single(Directory.GetDirectories(loaded));
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);
            Assert.Equal(chosen, world.Host.RunRoot);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// The reviews of 154A's merge, N4 (feature 002 T204): the run root the add-in loaded is one the rule refuses -
    /// here its last folder a link - so every start is refused, and the engineer chooses a local folder in Settings,
    /// whose save's restart fails before the old backend stops. The run root in force is still the old one, so every
    /// start is still refused, and both what the Review tab is told and the refusal must be true: `init`, and the
    /// status of a restart that waited, say no run can start until the backend restarts with the settings saved -
    /// not where runs are made, since none is - and a review start is refused `RunRootChosenNotInForce`, whose way
    /// on is to save the settings again to retry the restart, not to choose a local folder, which the engineer has
    /// just done. Nothing is made or asked of the backend.
    /// </summary>
    [Theory]
    [InlineData("at once")]
    [InlineData("after waiting")]
    public void UnderARefusedRunRootAFolderChosenWhoseRestartFailedIsToldTrulyWithTheWayOnToRetryTheRestart(string when)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();
        using var world = new RestartWorld { Probe = probe };
        probe.Links.Add(world.Settings.RunRoot);
        world.Open();
        world.Track("chat-1");
        string chosen = ChosenRoot(world);

        SaveWhoseRestartFailsBeforeTheOldBackendStops(world, when, Choosing(chosen, Save()));

        if (when == "after waiting")
        {
            Assert.Equal(
                LauncherGone + ". " + NotInForceWhileTheRunRootIsRefused,
                world.Last("status").GetProperty("message").GetString());
        }

        Assert.Equal(NotInForceWhileTheRunRootIsRefused, Init(world, "init").GetProperty("settings_not_in_force").GetString());
        int sessions = world.Backend.Sessions.Length;

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("RunRootChosenNotInForce", error.GetProperty("error_class").GetString());
        Assert.False(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(
            RunRootRule.ChosenNotInForceRefusal(RunRootVerdict.Link, "nothing was started", RunRootRule.InSettings, "try again"),
            error.GetProperty("message").GetString());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Equal(sessions, world.Backend.Sessions.Length);
        Assert.False(Directory.Exists(chosen));
    }

    /// <summary>A folder for runs beside the world's own run root, under its temporary folder: one a save chooses.</summary>
    private static string ChosenRoot(RestartWorld world) => Path.Combine(world.Root, "chosen", "runs");

    /// <summary><paramref name="payload"/>, a settings save, choosing <paramref name="runRoot"/> as the folder for runs.</summary>
    private static Dictionary<string, object?> Choosing(string runRoot, Dictionary<string, object?> payload)
    {
        payload["run_root"] = runRoot;
        return payload;
    }

    /// <summary>
    /// The backend that is up was started with the run root in force (owner decision 154A, with 153A's record):
    /// it is the run root for a new run and among the run roots in force, `init` names it and says nothing of the
    /// settings in force, and a review's folder is made under it.
    /// </summary>
    private static void AssertTheBackendAndTheRunRootInForceAgree(RestartWorld world, string runRoot)
    {
        Assert.NotNull(world.Backend.Endpoint);
        Assert.Equal(runRoot, world.Backend.Restarts.Last().Settings.RunRoot);
        Assert.Equal(runRoot, world.Host.RunRoot);
        Assert.Equal(runRoot, world.Host.RunRootForANewRun());
        Assert.Contains(runRoot, world.Host.RunRootsInForce);
        JsonElement init = Init(world, "agree-run-root");
        Assert.Equal(runRoot, init.GetProperty("run_root").GetString());
        Assert.Equal(JsonValueKind.Null, init.GetProperty("settings_not_in_force").ValueKind);
        Assert.Equal(runRoot, Path.GetDirectoryName(MakeASession(world, "review").RunDirectory));
    }

    // ---- 15. a session's bridge serves the review's document (owner decision 152A) ------------

    /// <summary>
    /// What a new review is refused with when the bridge it would be given is not on its document,
    /// read before anything is made (owner decision 152A), pinned word for word.
    /// </summary>
    private const string BridgeElsewhereBeforeExtraction =
        "the SOLIDWORKS bridge this review would be given is not attached to the review's document and "
        + "configuration, so nothing was extracted and no run folder was made. It follows the active "
        + "document once no review turn or remodel holds it: wait a moment, then press Review again.";

    /// <summary>...and what any start is refused with at its session, where whatever it made stays made.</summary>
    private const string BridgeElsewhereAtTheSession =
        "the SOLIDWORKS bridge this review would be given is not attached to the review's document and "
        + "configuration, so no review session was started and no check ran. It follows the active "
        + "document once no review turn or remodel holds it: wait a moment, then try again.";

    /// <summary>The bridge the tool service publishes: the pipe minted for its attach, and the review secret.</summary>
    private static readonly BridgeConfig ReviewBridge = new BridgeConfig("swreview-FICT-152a-1", "FICT-review-secret-152a-1");

    /// <summary>
    /// Owner decision 152A, its second half. A session is given whatever bridge the tool service is
    /// attached to when it is made, and its first check, the live interference check, runs over it
    /// and writes its rows into the review's package - another document's, when the tool service
    /// was left on another one (002 research, 149A's owner question 5). Every start that makes a
    /// session now asks which document the bridge it would hand over serves - the tool service's own
    /// record of its attachment, which its `ping` answers - and refuses one not on the review's, by
    /// the pane's one rule (the path ignoring case, the configuration exactly), or on none:
    /// `BridgeOnAnotherDocument`, retryable, in plain words naming no path; it asks the tool service
    /// to follow the active document, so that pressing again can find the bridge there; and it makes
    /// nothing - no session, no status, and for a new review no extraction and no run folder.
    /// </summary>
    [Theory]
    [InlineData("review", "another document")]
    [InlineData("review", "another configuration")]
    [InlineData("review", "no service")]
    [InlineData("prepared review", "another document")]
    [InlineData("prepared review", "another configuration")]
    [InlineData("retry", "another document")]
    [InlineData("context review", "another document")]
    [InlineData("context review", "another configuration")]
    [InlineData("context review", "no service")]
    [InlineData("context retry", "another document")]
    [InlineData("context retry", "another configuration")]
    [InlineData("recheck", "another document")]
    [InlineData("recheck", "another configuration")]
    [InlineData("recheck", "no service")]
    public void AStartWhoseBridgeIsNotOnItsDocumentIsRefusedAndMakesNothing(string kind, string served)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge, Prepares = kind == "prepared review" };
        PageDocument reviewed = world.Document!;
        PageDocument? servedNow = reviewed;
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? servedNow : null;
        world.Open();
        Directory.CreateDirectory(world.Settings.RunRoot);
        var start = new SessionStart(world, kind);
        start.Ready();
        servedNow = served == "no service" ? null : Changed(reviewed, served);
        int sessions = world.Backend.Sessions.Length;
        int dumps = world.Dump.Runs;
        int statuses = world.Posted("status").Length;
        string[] folders = FoldersUnderTheRunRoot(world);

        start.Press("press");

        JsonElement error = world.Reply("error", "press");
        Assert.Equal("BridgeOnAnotherDocument", error.GetProperty("error_class").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        string message = error.GetProperty("message").GetString()!;
        Assert.Equal(start.Extracts ? BridgeElsewhereBeforeExtraction : BridgeElsewhereAtTheSession, message);
        Assert.DoesNotContain(@":\", message, StringComparison.Ordinal);
        Assert.DoesNotContain("FICT", message, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(sessions, world.Backend.Sessions.Length);
        Assert.Equal(dumps, world.Dump.Runs);
        Assert.Equal(folders, FoldersUnderTheRunRoot(world));
        Assert.DoesNotContain(
            world.Posted("status").Skip(statuses),
            status => status.GetProperty("stage").GetString() is "extracting" or "checking");
        Assert.Equal(1, world.FollowsAsked);
    }

    /// <summary>
    /// A bridge on the review's document is handed over, and it is the one the session is given -
    /// the same document however its path is spelled, since Windows names one file however it is
    /// cased and the rule is the pane's one rule. Nothing is refused and the tool service is asked
    /// nothing.
    /// </summary>
    [Theory]
    [InlineData("review", "the same")]
    [InlineData("review", "spelled otherwise")]
    [InlineData("prepared review", "spelled otherwise")]
    [InlineData("retry", "spelled otherwise")]
    [InlineData("context review", "the same")]
    [InlineData("context review", "spelled otherwise")]
    [InlineData("context retry", "spelled otherwise")]
    [InlineData("recheck", "the same")]
    [InlineData("recheck", "spelled otherwise")]
    public void AStartWhoseBridgeIsOnItsDocumentIsGivenThatBridge(string kind, string served)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge, Prepares = kind == "prepared review" };
        PageDocument reviewed = world.Document!;
        PageDocument? servedNow = reviewed;
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? servedNow : null;
        world.Open();
        var start = new SessionStart(world, kind);
        start.Ready();
        servedNow = served == "the same" ? reviewed : Changed(reviewed, served);
        int sessions = world.Backend.Sessions.Length;

        start.Press("press");

        start.AssertStarted("press");
        Assert.Equal(sessions + 1, world.Backend.Sessions.Length);
        NewSessionRequest request = world.Backend.Sessions.Last().Request;
        Assert.Equal(ReviewBridge.Pipe, request.Bridge!.Pipe);
        Assert.Equal(ReviewBridge.Secret, request.Bridge.Secret);
        Assert.Equal(0, world.FollowsAsked);
    }

    /// <summary>
    /// The refusal is retryable, and truly: once the bridge serves the review's document - the tool
    /// service has followed it - the same press starts the review, with that bridge: a new review
    /// prepared afresh as the page always prepares one, a context review on the context it prepared,
    /// a Retry or a Recheck on the review it names.
    /// </summary>
    [Theory]
    [InlineData("review")]
    [InlineData("prepared review")]
    [InlineData("retry")]
    [InlineData("context review")]
    [InlineData("context retry")]
    [InlineData("recheck")]
    public void PressedAgainOnceTheBridgeIsOnItsDocumentTheStartGoesAhead(string kind)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge, Prepares = kind == "prepared review" };
        PageDocument reviewed = world.Document!;
        PageDocument? servedNow = reviewed;
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? servedNow : null;
        world.Open();
        var start = new SessionStart(world, kind);
        start.Ready();
        servedNow = Changed(reviewed, "another configuration");
        start.Press("refused");
        Assert.Equal("BridgeOnAnotherDocument", world.Reply("error", "refused").GetProperty("error_class").GetString());
        int sessions = world.Backend.Sessions.Length;

        servedNow = reviewed;
        start.Press("again");

        start.AssertStarted("again");
        Assert.Equal(sessions + 1, world.Backend.Sessions.Length);
        Assert.Equal(ReviewBridge.Pipe, world.Backend.Sessions.Last().Request.Bridge!.Pipe);
        Assert.Equal(1, world.FollowsAsked);
    }

    /// <summary>
    /// The bridge is asked again at the session, after the extraction - minutes, in which the tool
    /// service can follow another document - and one it attached to another document meanwhile is
    /// refused there, in words true there: no session was started and no check ran. The run folder
    /// keeps the evidence just extracted, of the review's document, as an extraction that fails keeps
    /// its own; the next press makes a new one.
    /// </summary>
    [Fact]
    public void ABridgeMovedToAnotherDocumentDuringTheExtractionIsRefusedAtTheSession()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        var moved = new BridgeConfig("swreview-FICT-152a-2", "FICT-review-secret-152a-2");
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe
            ? reviewed
            : bridge.Pipe == moved.Pipe ? Changed(reviewed, "another document") : null;
        world.Open();
        Directory.CreateDirectory(world.Settings.RunRoot);
        string[] folders = FoldersUnderTheRunRoot(world);
        world.Dump.OnRun = () => world.Bridge = moved;

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("BridgeOnAnotherDocument", error.GetProperty("error_class").GetString());
        Assert.Equal(BridgeElsewhereAtTheSession, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(1, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        string made = Assert.Single(FoldersUnderTheRunRoot(world).Except(folders));
        Assert.True(File.Exists(Path.Combine(made, "package.json")));
        Assert.Equal(1, world.FollowsAsked);
    }

    /// <summary>
    /// ...and the session is given the bridge read at its creation, never the one read before the
    /// extraction: one the tool service moved to the review's own document meanwhile is handed over.
    /// </summary>
    [Fact]
    public void TheSessionIsGivenTheBridgeReadAtItsCreation()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        var moved = new BridgeConfig("swreview-FICT-152a-2", "FICT-review-secret-152a-2");
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe || bridge.Pipe == moved.Pipe ? reviewed : null;
        world.Open();
        world.Dump.OnRun = () => world.Bridge = moved;

        world.Receive("review.start", "start", new { });

        world.Reply("review.started", "start");
        NewSessionRequest request = Assert.Single(world.Backend.Sessions).Request;
        Assert.Equal(moved.Pipe, request.Bridge!.Pipe);
        Assert.Equal(moved.Secret, request.Bridge.Secret);
        Assert.Equal(0, world.FollowsAsked);
    }

    /// <summary>
    /// The session is given the very bridge that was asked about. One the tool service publishes
    /// between the question and the session - it re-attached, so the bridge asked about is closing -
    /// is not handed over unasked: the session gets the one asked about, whose pipe serves the
    /// review's document or nothing, never another document.
    /// </summary>
    [Fact]
    public void TheSessionIsGivenTheBridgeThatWasAskedAboutAndNoOtherPublishedSince()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        var published = new BridgeConfig("swreview-FICT-152a-3", "FICT-review-secret-152a-3");
        world.BridgeServes = bridge =>
        {
            if (bridge.Pipe == ReviewBridge.Pipe && world.Dump.Runs > 0)
            {
                world.Bridge = published;
            }

            return bridge.Pipe == ReviewBridge.Pipe ? reviewed : Changed(reviewed, "another document");
        };
        world.Open();

        world.Receive("review.start", "start", new { });

        world.Reply("review.started", "start");
        NewSessionRequest request = Assert.Single(world.Backend.Sessions).Request;
        Assert.Equal(ReviewBridge.Pipe, request.Bridge!.Pipe);
        Assert.Equal(ReviewBridge.Secret, request.Bridge.Secret);
    }

    /// <summary>
    /// With no bridge published - no tool service listening yet, or one being replaced - a session is
    /// given none and nothing is asked, as before owner decision 152A: the backend runs no live check
    /// and says so in the review's coverage, and nothing of another document can reach it.
    /// </summary>
    [Fact]
    public void WithNoBridgeASessionIsGivenNoneAndNothingIsAsked()
    {
        using var world = new RestartWorld();
        world.BridgeServes = _ => throw new InvalidOperationException("no bridge, so nothing is asked of one");
        world.Open();

        world.Receive("review.start", "start", new { });

        world.Reply("review.started", "start");
        Assert.Null(Assert.Single(world.Backend.Sessions).Request.Bridge);
        Assert.Equal(0, world.FollowsAsked);
    }

    /// <summary>
    /// A bridge whose document the host cannot be told is handed to no session: an answer of none,
    /// and an answer that throws, are refused as a bridge on another document is. And by default a
    /// host has no answer: a host given a bridge and nothing to ask about it refuses, rather than
    /// hand over a bridge whose document it cannot vouch for.
    /// </summary>
    [Theory]
    [InlineData("no answer")]
    [InlineData("an answer that throws")]
    public void ABridgeWhoseDocumentCannotBeToldIsHandedToNoSession(string answer)
    {
        Assert.Null(new ReviewHostOptions(new FakeChannel(), new FakeBackend(), "FICT-settings.json").BridgeDocument(ReviewBridge));

        using var world = new RestartWorld { Bridge = ReviewBridge };
        world.BridgeServes = answer == "no answer"
            ? (Func<BridgeConfig, PageDocument?>?)null
            : _ => throw new InvalidOperationException("the gate could not be asked");
        world.Open();

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("BridgeOnAnotherDocument", error.GetProperty("error_class").GetString());
        Assert.Equal(BridgeElsewhereBeforeExtraction, error.GetProperty("message").GetString());
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(0, world.Dump.Runs);
    }

    /// <summary>
    /// The 152A review's R1. The tool-service gate asks whether work holds the bridge before every
    /// follow, and since owner decision 152A every second while a follow is owed, for the length of a
    /// turn; a "no" takes the bridge down, which cannot be undone. A chat the backend gives no usable
    /// answer about may have a turn running - not knowing whether a turn runs is not knowing that none
    /// does, as the settings restart reads it (143A) - so the gate's question, `TurnMayBeRunning`,
    /// answers yes to it, where `AnyTurnRunning`, which a save asks, answers no. With no backend
    /// process at all no turn can run, and it answers no, so the tool service still follows the
    /// engineer while the backend is down.
    /// </summary>
    [Theory]
    [InlineData("a turn running", true)]
    [InlineData("no answer", true)]
    [InlineData("no turn", false)]
    [InlineData("no backend", false)]
    public void TheGatesQuestionCountsAChatTheBackendDoesNotAnswerAboutAsATurnThatMayRun(string state, bool mayRun)
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        world.Track("chat-2");
        if (state != "no turn")
        {
            world.Backend.StartTurn("chat-2");
        }

        if (state == "no answer")
        {
            world.Backend.StopsAnswering();
        }
        else if (state == "no backend")
        {
            world.Backend.Down = true;
        }

        Assert.Equal(mayRun, world.Host.TurnMayBeRunning());
        Assert.Equal(state == "a turn running", world.Host.AnyTurnRunning());
    }

    /// <summary>
    /// What a new review is refused with when its document or configuration is not the active one
    /// once its evidence is extracted (owner decision 152A, on the Codex review: X1), pinned word for
    /// word. It names no path.
    /// </summary>
    private const string DocumentChangedAtTheSession =
        "the active document or its configuration changed while the evidence was extracted, so no review "
        + "session was started and no check ran. Make the part or assembly and the configuration you want "
        + "reviewed active again, then press Review again.";

    /// <summary>
    /// What the status line says once a new review is refused after its extraction: the extraction's
    /// statuses are over, and nothing was sent.
    /// </summary>
    private const string ExtractedButNotReviewed =
        "Evidence extracted, but no review was started; no review tokens used.";

    /// <summary>
    /// The Codex review of 152A, X1. A configuration switch re-attaches nothing (004, decision 22A), so
    /// the bridge's pipe is not replaced and its record of its attach still names the configuration the
    /// review was asked for, while the live checks run on the configuration active when they run,
    /// mapped through the attach's component table: Machined's interference rows entered Default's
    /// review. The extraction runs on the SOLIDWORKS application thread in one call, so a switch made
    /// during it lands as it ends. So a new review reads its document again once its evidence is
    /// extracted - the last moment before its session is given the bridge - and refuses one that
    /// changed, another configuration above all, `DocumentChanged`, retryable, in words true there that
    /// name no path: no session is created and no check runs, the tool service is asked nothing, and the
    /// status line says the extraction is over. The run folder keeps what was extracted, of the review's
    /// own document, as one whose extraction fails keeps its own.
    /// </summary>
    [Theory]
    [InlineData("another configuration")]
    [InlineData("another document")]
    [InlineData("no document")]
    [InlineData("a drawing")]
    public void ANewReviewWhoseDocumentChangedDuringItsExtractionIsRefusedAtTheSession(string change)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? reviewed : null;
        world.Open();
        Directory.CreateDirectory(world.Settings.RunRoot);
        string[] folders = FoldersUnderTheRunRoot(world);
        world.Dump.OnRun = () => world.Document = Changed(reviewed, change);

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("DocumentChanged", error.GetProperty("error_class").GetString());
        string message = error.GetProperty("message").GetString()!;
        Assert.Equal(DocumentChangedAtTheSession, message);
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.DoesNotContain(@":\", message, StringComparison.Ordinal);
        Assert.DoesNotContain("FICT", message, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(1, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        string made = Assert.Single(FoldersUnderTheRunRoot(world).Except(folders));
        Assert.True(File.Exists(Path.Combine(made, "package.json")));
        Assert.Equal(0, world.FollowsAsked);
        JsonElement status = world.Last("status");
        Assert.Equal("ready", status.GetProperty("stage").GetString());
        Assert.Equal(ExtractedButNotReviewed, status.GetProperty("message").GetString());
    }

    /// <summary>
    /// ...and truly retryable: with the review's configuration active again, the same press extracts
    /// afresh and starts the review, with the bridge, which never moved.
    /// </summary>
    [Fact]
    public void PressedAgainWithItsConfigurationActiveAgainTheReviewGoesAhead()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? reviewed : null;
        world.Open();
        world.Dump.OnRun = () => world.Document = Changed(reviewed, "another configuration");
        world.Receive("review.start", "refused", new { });
        Assert.Equal("DocumentChanged", world.Reply("error", "refused").GetProperty("error_class").GetString());

        world.Dump.OnRun = null;
        world.Document = reviewed;
        world.Receive("review.start", "again", new { });

        world.Reply("review.started", "again");
        Assert.Equal(2, world.Dump.Runs);
        Assert.Equal(ReviewBridge.Pipe, Assert.Single(world.Backend.Sessions).Request.Bridge!.Pipe);
    }

    /// <summary>
    /// The same document however its path is spelled is not a change, at the session as before the
    /// extraction: the pane's one rule (the path ignoring case, the configuration exactly).
    /// </summary>
    [Fact]
    public void ANewReviewWhoseDocumentIsSpelledOtherwiseAfterItsExtractionStarts()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? reviewed : null;
        world.Open();
        world.Dump.OnRun = () => world.Document = Changed(reviewed, "spelled otherwise");

        world.Receive("review.start", "start", new { });

        world.Reply("review.started", "start");
        Assert.Single(world.Backend.Sessions);
    }

    /// <summary>
    /// Nothing half made: a new review refused after its extraction - its document changed, or its
    /// bridge moved to another document meanwhile (152A) - ends the extraction's statuses with one that
    /// says the extraction is over and nothing was sent, rather than leave the page saying it is
    /// extracting. A refusal before the extraction posts none (above).
    /// </summary>
    [Theory]
    [InlineData("its document changed")]
    [InlineData("its bridge moved")]
    public void ANewReviewRefusedAfterItsExtractionSaysTheExtractionIsOver(string refusal)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        var moved = new BridgeConfig("swreview-FICT-152a-2", "FICT-review-secret-152a-2");
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe
            ? reviewed
            : bridge.Pipe == moved.Pipe ? Changed(reviewed, "another document") : null;
        world.Open();
        world.Dump.OnRun = refusal == "its document changed"
            ? (Action)(() => world.Document = Changed(reviewed, "another configuration"))
            : () => world.Bridge = moved;
        int statuses = world.Posted("status").Length;

        world.Receive("review.start", "start", new { });

        Assert.Equal(
            refusal == "its document changed" ? "DocumentChanged" : "BridgeOnAnotherDocument",
            world.Reply("error", "start").GetProperty("error_class").GetString());
        JsonElement[] posted = world.Posted("status").Skip(statuses).ToArray();
        Assert.Equal(
            new[] { "extracting", "ready" },
            posted.Select(status => status.GetProperty("stage").GetString()).ToArray());
        Assert.Equal(ExtractedButNotReviewed, posted.Last().GetProperty("message").GetString());
        Assert.Empty(world.Backend.Sessions);
    }

    /// <summary>
    /// The review of 152A's Codex fixes, S2. The dump attaches to whatever is active when it begins,
    /// which can be another document than every reading made before it: switched after 149A's second
    /// reading - while the run folder is made and the status posted - and switched back during the
    /// extraction, the dump extracts the other one, and the reading made once it ends sees the
    /// review's own document again. So the session is checked against what the dump says it extracted
    /// too, and such a review is refused as one whose document changed during its extraction, in the
    /// same words, leaving nothing half made: no session, the status line told the extraction is over,
    /// the tool service asked nothing.
    /// </summary>
    [Theory]
    [InlineData("another configuration")]
    [InlineData("another document")]
    public void ANewReviewWhoseDumpAttachedToAnotherDocumentIsRefusedThoughItsOwnIsActiveAgain(string change)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? reviewed : null;
        world.Open();
        int statuses = world.Posted("status").Length;
        world.Dump.BeforeAttach = () => world.Document = Changed(reviewed, change);
        world.Dump.OnRun = () => world.Document = reviewed;

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("DocumentChanged", error.GetProperty("error_class").GetString());
        Assert.Equal(DocumentChangedAtTheSession, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(1, world.Dump.Runs);
        Assert.Same(reviewed, world.Document);
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(0, world.FollowsAsked);
        Assert.Equal(
            new[] { "extracting", "ready" },
            world.Posted("status").Skip(statuses).Select(status => status.GetProperty("stage").GetString()).ToArray());
        Assert.Equal(ExtractedButNotReviewed, world.Last("status").GetProperty("message").GetString());
    }

    /// <summary>
    /// ...and evidence a dump says nothing of is not taken for the review's: the add-in's dump always
    /// says what it attached to, and one that does not is refused as one that attached elsewhere,
    /// rather than vouched for. The same document however its path is spelled is the review's.
    /// </summary>
    [Theory]
    [InlineData("says nothing", false)]
    [InlineData("spelled otherwise", true)]
    public void WhatTheDumpSaysItExtractedDecides(string said, bool started)
    {
        using var world = new RestartWorld();
        PageDocument reviewed = world.Document!;
        world.Open();
        world.Dump.Attaches = said == "says nothing"
            ? (Func<PageDocument?>)(() => null)
            : () => Changed(reviewed, said);

        world.Receive("review.start", "start", new { });

        if (started)
        {
            world.Reply("review.started", "start");
            Assert.Single(world.Backend.Sessions);
        }
        else
        {
            Assert.Equal("DocumentChanged", world.Reply("error", "start").GetProperty("error_class").GetString());
            Assert.Empty(world.Backend.Sessions);
        }
    }

    /// <summary>
    /// The Codex review of 152A, X2, for a review session. A review's checks run over the bridge while
    /// `POST /sessions` is out - its live interference check first - and the session is tracked, so
    /// that the gate's busy question asks after its turn, only once that call has answered. A follow
    /// whose busy question was out as the session was made - its answer had before the session
    /// existed - took the bridge down under it. Every start holds the tool service through the gate
    /// before it reads the bridge it hands over, and the follow takes the bridge down only if no hold
    /// was taken while its question was out: it waits, asks again a poll later, finds the review's turn
    /// running, waits on, and follows once the turn has ended.
    /// </summary>
    [Fact]
    public void AReviewSessionMadeWhileAFollowsTurnQuestionIsOutIsNotTornDownUnderIt()
    {
        using var world = new RestartWorld();
        PageDocument reviewed = world.Document!;
        ToolServiceGate? gate = null;
        var services = new List<FakeToolService>();
        var looks = new List<Action>();
        Action? onTheWayBack = null;
        world.BridgeServes = bridge => gate!.DocumentServedBy(bridge);
        world.Hold = () => gate!.HoldAttachment(ToolServiceHolder.ReviewSession);
        world.Open();
        gate = new ToolServiceGate(
            () => world.Document,
            () =>
            {
                var service = new FakeToolService(services.Count + 1, world.Document!.Path, world.Document.Configuration);
                services.Add(service);
                return service;
            },
            service => world.Bridge = service?.ReviewBridge,
            (what, failure) => { },
            schedule: work => work(),
            busy: () =>
            {
                // The add-in's question: whether a turn may be running on a chat it started - a round
                // trip per chat. Its answer is had; on its way back, the review starts.
                bool answer = world.Host.TurnMayBeRunning();
                Action? back = onTheWayBack;
                onTheWayBack = null;
                back?.Invoke();
                return answer;
            },
            later: look => looks.Add(look));
        using (gate)
        {
            gate.EnsureStarted();
            string? chatId = null;
            onTheWayBack = () =>
            {
                world.Receive("review.start", "start", new { });
                chatId = world.Reply("review.started", "start").GetProperty("chat_id").GetString()!;
                world.Backend.StartTurn(chatId);
                world.Document = Changed(reviewed, "another document");
            };

            gate.FollowActiveDocument();

            Assert.Equal(services[0].PipeName, Assert.Single(world.Backend.Sessions).Request.Bridge!.Pipe);
            Assert.False(services[0].Disposed);
            Assert.Single(services);
            Action look = Assert.Single(looks);
            looks.Clear();

            look();

            Assert.False(services[0].Disposed);
            look = Assert.Single(looks);
            looks.Clear();
            world.Backend.EndTurn(chatId!);

            look();

            Assert.True(services[0].Disposed);
            Assert.Equal(2, services.Count);
            Assert.Equal(Changed(reviewed, "another document")!.Path, gate.DocumentPath);
        }
    }

    /// <summary>
    /// Every start that makes a session holds the tool service from before it reads the bridge it hands
    /// over until its session is tracked - from then the gate's busy question asks after its turn - and
    /// lets go then: a new review, a Retry, a context review and its Retry, and a Recheck alike.
    /// </summary>
    [Theory]
    [InlineData("review")]
    [InlineData("prepared review")]
    [InlineData("retry")]
    [InlineData("context review")]
    [InlineData("context retry")]
    [InlineData("recheck")]
    public void EveryStartHoldsTheToolServiceFromTheBridgeItHandsOverUntilItsSessionIsTracked(string kind)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge, Prepares = kind == "prepared review" };
        PageDocument reviewed = world.Document!;
        var holds = new CountedHolds();
        var atTheBridge = new List<int>();
        var trackedAtTheRelease = new List<int>();
        world.BridgeServes = bridge =>
        {
            atTheBridge.Add(holds.Held);
            return reviewed;
        };
        world.Hold = holds.Take;
        holds.OnRelease = () => trackedAtTheRelease.Add(world.Host.Reviews().Count);
        world.Open();
        var start = new SessionStart(world, kind);
        start.Ready();
        int takenBefore = holds.Taken;
        int reviews = world.Host.Reviews().Count;
        atTheBridge.Clear();
        trackedAtTheRelease.Clear();

        start.Press("press");

        start.AssertStarted("press");
        Assert.Equal(takenBefore + 1, holds.Taken);
        Assert.Equal(0, holds.Held);
        Assert.Equal(1, atTheBridge.Last());
        Assert.Equal(reviews + (kind == "recheck" ? 0 : 1), Assert.Single(trackedAtTheRelease));
    }

    /// <summary>
    /// ...and lets go however the start ends at its session: refused for a bridge that moved to another
    /// document while it extracted - let go before the tool service is asked to follow, which a hold
    /// still held would put off a poll - or failed at the backend. A start refused before its session -
    /// its document changed during its extraction - takes none.
    /// </summary>
    [Theory]
    [InlineData("its bridge moved", 1)]
    [InlineData("the backend failed", 1)]
    [InlineData("its document changed", 0)]
    public void AStartEndedAtItsSessionLetsGoOfItsHold(string ending, int taken)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        var moved = new BridgeConfig("swreview-FICT-152a-2", "FICT-review-secret-152a-2");
        var holds = new CountedHolds();
        var heldAtTheFollow = new List<int>();
        world.BridgeServes = bridge => bridge.Pipe == ReviewBridge.Pipe ? reviewed : Changed(reviewed, "another document");
        world.Hold = holds.Take;
        world.OnFollow = () => heldAtTheFollow.Add(holds.Held);
        world.Open();
        if (ending == "its bridge moved") world.Dump.OnRun = () => world.Bridge = moved;
        if (ending == "the backend failed") world.Backend.CreateFailure = new BackendRequestException("BackendUnavailable", "FICT the backend stopped", retryable: true);
        if (ending == "its document changed") world.Dump.OnRun = () => world.Document = Changed(reviewed, "another configuration");

        world.Receive("review.start", "start", new { });

        world.Reply("error", "start");
        Assert.Equal(taken, holds.Taken);
        Assert.Equal(0, holds.Held);
        Assert.Equal(ending == "its bridge moved" ? new[] { 0 } : new int[0], heldAtTheFollow.ToArray());
    }

    /// <summary>
    /// With no hold to be had - no tool service listening, or one being taken down - a start goes on as
    /// before: the session is given what is published, none, or the bridge is refused for serving no
    /// document, as a bridge no service listening has always was.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void WithNoHoldToBeHadAStartIsGivenWhatIsPublishedAsBefore(bool published)
    {
        using var world = new RestartWorld { Bridge = published ? ReviewBridge : null };
        world.BridgeServes = _ => null;
        world.Hold = () => null;
        world.Open();

        world.Receive("review.start", "start", new { });

        if (published)
        {
            Assert.Equal("BridgeOnAnotherDocument", world.Reply("error", "start").GetProperty("error_class").GetString());
            Assert.Empty(world.Backend.Sessions);
        }
        else
        {
            world.Reply("review.started", "start");
            Assert.Null(Assert.Single(world.Backend.Sessions).Request.Bridge);
        }
    }

    /// <summary>
    /// The final review of 152A (Codex, C1; feature 002 T227). A session's start asked the gate for its hold while
    /// a follow was re-attaching - no service listening, so none - and the follow then published the new service's
    /// bridge before the start read the bridge: the start handed that bridge to `POST /sessions` with nothing
    /// held, and a switch while the call was out let a follow take it down under the review's first checks. In
    /// that order - the hold refused, the new bridge published, the session asked for, a follow while the call
    /// is out - the start asks for the hold again once it finds a bridge published, holds the new service and is
    /// given its bridge; the follow waits until the session is tracked, and is made once nothing holds the bridge.
    /// </summary>
    [Fact]
    public void ASessionAskedForAsAReAttachEndsHoldsTheBridgeItIsGivenSoAFollowWaitsForIt()
    {
        using var world = new RestartWorld();
        using var startingTheSecond = new ManualResetEventSlim(false);
        using var letTheSecondStart = new ManualResetEventSlim(false);
        using var secondPublished = new ManualResetEventSlim(false);
        PageDocument reviewed = world.Document!;
        PageDocument elsewhere = Changed(reviewed, "another document")!;
        ToolServiceGate? gate = null;
        var services = new List<FakeToolService>();
        var looks = new List<Action>();
        bool letGoOnce = false;
        world.BridgeServes = bridge => gate!.DocumentServedBy(bridge);
        world.Hold = () =>
        {
            IDisposable? hold = gate!.HoldAttachment(ToolServiceHolder.ReviewSession);
            if (hold == null && !letGoOnce)
            {
                // The order the review found: the hold refused mid re-attach, then the new bridge published.
                letGoOnce = true;
                letTheSecondStart.Set();
                Assert.True(secondPublished.Wait(TimeSpan.FromSeconds(10)), "the second service was never published");
            }

            return hold;
        };
        world.Open();
        world.Track("waiting");
        world.Document = elsewhere;
        gate = new ToolServiceGate(
            () => world.Document,
            () =>
            {
                var service = new FakeToolService(services.Count + 1, world.Document!.Path, world.Document.Configuration);
                services.Add(service);
                if (services.Count == 2)
                {
                    startingTheSecond.Set();
                    Assert.True(letTheSecondStart.Wait(TimeSpan.FromSeconds(10)), "the second start was never let go");
                }

                return service;
            },
            service =>
            {
                world.Bridge = service?.ReviewBridge;
                if (service != null && services.Count == 2)
                {
                    secondPublished.Set();
                }
            },
            (what, failure) => { },
            schedule: work => work(),
            busy: () => world.Host.TurnMayBeRunning(),
            later: look => looks.Add(look));
        using (gate)
        {
            gate.EnsureStarted();
            Assert.Equal(services[0].ReviewBridge, world.Bridge);

            // The engineer makes the review's document active, and the gate follows it on a thread of its own.
            world.Document = reviewed;
            var follow = new Caller<bool>(() =>
            {
                gate.FollowActiveDocument();
                return true;
            });
            Assert.True(startingTheSecond.Wait(TimeSpan.FromSeconds(10)), "the follow never began the second start");
            bool takenDownDuringTheCall = false;
            world.Backend.DuringCreate = () =>
            {
                Assert.True(follow.Finishes(TimeSpan.FromSeconds(10)), "the follow never finished");
                world.Document = elsewhere;
                gate.FollowActiveDocument();
                takenDownDuringTheCall = services[1].Disposed;
            };

            world.Receive("review.recheck", "recheck", new { chat_id = "waiting" });

            world.Reply("review.rechecked", "recheck");
            Assert.True(follow.Result);
            Assert.Equal(services[1].PipeName, Assert.Single(world.Backend.Sessions).Request.Bridge!.Pipe);
            Assert.False(takenDownDuringTheCall, "a follow took the session's bridge down while POST /sessions was out");
            Assert.False(services[1].Disposed);
            Action look = Assert.Single(looks);
            looks.Clear();

            look();

            Assert.True(services[1].Disposed);
            Assert.Equal(3, services.Count);
            Assert.Equal(elsewhere.Path, gate.DocumentPath);
        }
    }

    /// <summary>
    /// ...and the bridge is read again under the second hold (feature 002 T227): asked for as a re-attach takes the
    /// old service down - nothing to hold, its bridge still published - the start finds that bridge, asks for the
    /// hold again once the new service is listening, and is given the new service's bridge, read under the hold,
    /// not the old one, which no service has any more.
    /// </summary>
    [Fact]
    public void ABridgeReadAsAReAttachTakesItsServiceDownIsReadAgainUnderTheSecondHold()
    {
        using var world = new RestartWorld();
        using var takingTheFirstDown = new ManualResetEventSlim(false);
        using var letTheFirstGo = new ManualResetEventSlim(false);
        using var secondPublished = new ManualResetEventSlim(false);
        PageDocument reviewed = world.Document!;
        PageDocument elsewhere = Changed(reviewed, "another document")!;
        ToolServiceGate? gate = null;
        var services = new List<FakeToolService>();
        int asked = 0;
        world.BridgeServes = bridge => gate!.DocumentServedBy(bridge);
        world.Hold = () =>
        {
            if (++asked == 2)
            {
                // The second asking comes once the re-attach has ended.
                letTheFirstGo.Set();
                Assert.True(secondPublished.Wait(TimeSpan.FromSeconds(10)), "the second service was never published");
            }

            return gate!.HoldAttachment(ToolServiceHolder.ReviewSession);
        };
        world.Open();
        world.Track("waiting");
        world.Document = elsewhere;
        gate = new ToolServiceGate(
            () => world.Document,
            () =>
            {
                var service = new FakeToolService(services.Count + 1, world.Document!.Path, world.Document.Configuration);
                services.Add(service);
                return service;
            },
            service =>
            {
                if (service == null && !letTheFirstGo.IsSet)
                {
                    // Taking the first service down: no service listening, its bridge still published.
                    takingTheFirstDown.Set();
                    Assert.True(letTheFirstGo.Wait(TimeSpan.FromSeconds(10)), "the first service was never let go");
                }

                world.Bridge = service?.ReviewBridge;
                if (service != null && services.Count == 2)
                {
                    secondPublished.Set();
                }
            },
            (what, failure) => { },
            schedule: work => work(),
            busy: () => world.Host.TurnMayBeRunning(),
            later: _ => { });
        using (gate)
        {
            gate.EnsureStarted();
            world.Document = reviewed;
            var follow = new Caller<bool>(() =>
            {
                gate.FollowActiveDocument();
                return true;
            });
            Assert.True(takingTheFirstDown.Wait(TimeSpan.FromSeconds(10)), "the follow never began taking the first down");
            Assert.Equal(services[0].ReviewBridge, world.Bridge);

            world.Receive("review.recheck", "recheck", new { chat_id = "waiting" });

            world.Reply("review.rechecked", "recheck");
            Assert.True(follow.Finishes(TimeSpan.FromSeconds(10)), "the follow never finished");
            Assert.True(follow.Result);
            Assert.Equal(2, asked);
            Assert.Equal(services[1].PipeName, Assert.Single(world.Backend.Sessions).Request.Bridge!.Pipe);
        }
    }

    /// <summary>
    /// ...and a bridge published that no hold can be had on, though asked for again, is not handed over (feature 002
    /// T227): the start is refused as one whose bridge is not on its document - retryable, the tool service asked
    /// to follow the active document, nothing made - whatever the bridge says it serves, rather than given a bridge
    /// nothing holds. Here the hold is never to be had while the bridge says it serves the review's document, as
    /// only a service published and taken down again between the two askings would leave it.
    /// </summary>
    [Fact]
    public void ABridgeNoHoldCanBeHadOnIsNotHandedOverThoughItServesTheReviewsDocument()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        int asked = 0;
        world.BridgeServes = _ => reviewed;
        world.Hold = () =>
        {
            asked++;
            return null;
        };
        world.Open();
        world.Track("waiting");

        world.Receive("review.recheck", "recheck", new { chat_id = "waiting" });

        JsonElement error = world.Reply("error", "recheck");
        Assert.Equal("BridgeOnAnotherDocument", error.GetProperty("error_class").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(BridgeElsewhereAtTheSession, error.GetProperty("message").GetString());
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(2, asked);
        Assert.Equal(1, world.FollowsAsked);
        Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("stage").GetString() == "checking");
    }

    // The merge with 153A and 154A (feature 002 T225): which refusal a start meets first - the order those two
    // leave: 153A reads a start under way before anything of the settings in force, the run root among them,
    // and 154A judges the run root, and the folder under it, before anything is asked or made under it, so the
    // bridge is asked about, and the tool service held and asked to follow, only by a start that would
    // otherwise go ahead (corrected on the final reviews, N1).

    /// <summary>
    /// A start whose run folder is under a run root a save has since moved is refused `RunRootChanged` (154A) -
    /// its way on, a run made again under the run root in force - though the bridge it would be given is on
    /// another document too: no hold is taken, and the tool service is asked to follow nothing. A new review whose
    /// run root moved while its evidence was extracted then ends the extraction's statuses with `ready`, as one
    /// refused at its session for its bridge does.
    /// </summary>
    [Theory]
    [InlineData("review")]
    [InlineData("recheck")]
    [InlineData("context review")]
    [InlineData("context retry")]
    public void AStartWhoseFolderIsUnderARunRootNoLongerInForceIsRefusedForThatBeforeItsBridgeIsAsked(string kind)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        PageDocument? servedNow = reviewed;
        var holds = new CountedHolds();
        world.BridgeServes = _ => servedNow;
        world.Hold = holds.Take;
        world.Open();
        Directory.CreateDirectory(world.Settings.RunRoot);
        var start = new SessionStart(world, kind);
        start.Ready();
        string chosen = ChosenRoot(world);
        if (kind == "review")
        {
            // Both move while the evidence is extracted: asked before it, the bridge was on the review's document.
            world.Dump.OnRun = () =>
            {
                MoveTheRunRootInForce(world, chosen);
                servedNow = Changed(reviewed, "another document");
            };
        }
        else
        {
            MoveTheRunRootInForce(world, chosen);
            servedNow = Changed(reviewed, "another document");
        }

        int sessions = world.Backend.Sessions.Length;
        int taken = holds.Taken;
        int follows = world.FollowsAsked;

        start.Press("press");

        JsonElement error = world.Reply("error", "press");
        Assert.Equal("RunRootChanged", error.GetProperty("error_class").GetString());
        Assert.False(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(chosen, world.Host.RunRoot);
        Assert.Equal(sessions, world.Backend.Sessions.Length);
        Assert.Equal(taken, holds.Taken);
        Assert.Equal(follows, world.FollowsAsked);
        if (kind == "review")
        {
            JsonElement status = world.Last("status");
            Assert.Equal("ready", status.GetProperty("stage").GetString());
            Assert.Equal(ExtractedButNotReviewed, status.GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// ...a start asked for while a start of the backend is under way is refused `BackendUnavailable` (153A),
    /// though its bridge is on another document too: the start under way is read before anything of the
    /// settings in force, and the bridge is asked about only once it is over. Nothing is held, the tool service
    /// is asked to follow nothing, and a Recheck posts no `checking` status.
    /// </summary>
    [Theory]
    [InlineData("recheck")]
    [InlineData("context review")]
    public void AStartAskedForWhileAStartOfTheBackendIsUnderWayIsRefusedForThatBeforeItsBridgeIsAsked(string session)
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        PageDocument reviewed = world.Document!;
        var holds = new CountedHolds();
        world.BridgeServes = _ => Changed(reviewed, "another document");
        world.Hold = holds.Take;
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            Caller<bool> first = FirstStartHeldOncePublished(world, published, letGo);

            JsonElement refused = world.Reply("error", AskForASession(world, session));
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);

            Assert.Equal("BackendUnavailable", refused.GetProperty("error_class").GetString());
            Assert.True(refused.GetProperty("retryable").GetBoolean());
            Assert.Empty(world.Backend.Sessions);
            Assert.Equal(0, holds.Taken);
            Assert.Equal(0, world.FollowsAsked);
            Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("stage").GetString() == "checking");
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// ...a start whose restart - one a save during a turn left waiting, which the start makes - brings in a run
    /// root the rule refuses is refused `RunRootRefused` (154A), its way on a local folder for runs in Settings,
    /// though its bridge is on another document too: a new review before anything is extracted, a Recheck at its
    /// session. Nothing is made or held, and the tool service is asked to follow nothing.
    /// </summary>
    [Theory]
    [InlineData("review.start")]
    [InlineData("review.recheck")]
    public void AStartWhoseRestartBringsInARefusedRunRootIsRefusedForThatBeforeItsBridgeIsAsked(string start)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10), Probe = probe, Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        var holds = new CountedHolds();
        world.BridgeServes = _ => Changed(reviewed, "another document");
        world.Hold = holds.Take;
        world.Open();
        world.Track("chat-1");
        world.Track("waiting");
        const string chosen = @"Y:\Fictional\runs";
        SaveAsATurnStarts(world, "save", Choosing(chosen, Save(effort: "low")));
        world.Backend.EndTurn("chat-1");
        probe.Drives[@"Y:\"] = RunRootDrive.Network;

        world.Receive(start, "start", new { chat_id = "waiting" });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
        Assert.Equal(chosen, world.Host.RunRoot);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(0, holds.Taken);
        Assert.Equal(0, world.FollowsAsked);
    }

    /// <summary>
    /// ...and a new review whose document and run root both changed while its evidence was extracted is refused
    /// `DocumentChanged` (152A, on the Codex review): read again before the session is asked for, so before 153A's
    /// and 154A's refusals there - and its way on, the review's document active again and Review pressed, makes a
    /// new run under the run root in force, which mends both. A guard of the order the merge kept.
    /// </summary>
    [Fact]
    public void ANewReviewWhoseDocumentAndRunRootBothChangedWhileItExtractedIsRefusedForItsDocument()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        PageDocument reviewed = world.Document!;
        var holds = new CountedHolds();
        world.BridgeServes = _ => reviewed;
        world.Hold = holds.Take;
        world.Open();
        string chosen = ChosenRoot(world);
        world.Dump.OnRun = () =>
        {
            MoveTheRunRootInForce(world, chosen);
            world.Document = Changed(reviewed, "another configuration");
        };

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("DocumentChanged", error.GetProperty("error_class").GetString());
        Assert.Equal(chosen, world.Host.RunRoot);
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(0, holds.Taken);
        Assert.Equal(0, world.FollowsAsked);
        Assert.Equal(ExtractedButNotReviewed, world.Last("status").GetProperty("message").GetString());
    }

    /// <summary>
    /// 153A's MR1, pinnable since the merge (feature 002 T227, the final review's N2): the run root, the hold and
    /// the bridge are asked between the reading of a start of the backend under way and the reading of the
    /// settings in force, so a start can end between the two. The start under way is read first: one under way
    /// refuses the session before any of them is asked, so a start that ends while the bridge is asked about
    /// cannot leave the session with the settings recorded before it on the backend it started.
    /// </summary>
    [Fact]
    public void AStartUnderWayIsReadBeforeTheQuestionsAskedBetweenItAndTheSettingsInForce()
    {
        using var world = new RestartWorld { Bridge = ReviewBridge };
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        PageDocument reviewed = world.Document!;
        Caller<bool>? first = null;
        world.BridgeServes = _ =>
        {
            // The start ends while the bridge is asked about.
            letGo.Set();
            Assert.True(first!.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            return reviewed;
        };
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            first = FirstStartHeldOncePublished(world, published, letGo);

            JsonElement refused = world.Reply("error", AskForASession(world, "recheck"));
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);

            Assert.Equal("BackendUnavailable", refused.GetProperty("error_class").GetString());
            Assert.Empty(world.Backend.Sessions);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// ...and before the run root (feature 002 T227, the final review's N3): a Recheck of a review whose run folder
    /// is under a run root not in force, asked for while a start of the backend is under way, is refused as one
    /// asked for before the backend is up - the start under way read first, as 153A reads it before anything of
    /// the settings in force, the run root among them - and not answered for its run root from a record that
    /// start is about to replace.
    /// </summary>
    [Fact]
    public void ARecheckUnderARunRootNotInForceAskedForWhileAStartIsUnderWayIsRefusedForTheStart()
    {
        using var world = new RestartWorld();
        using var published = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        try
        {
            ASaveThatSwitchedTheProviderFailedWithNoBackendUp(world);
            string earlier = Path.Combine(world.Root, "earlier", "runs", "20261019-101500-earlier");
            Directory.CreateDirectory(earlier);
            world.Host.TrackSession("earlier", earlier, world.Document, new DateTimeOffset(Stamp));
            Caller<bool> first = FirstStartHeldOncePublished(world, published, letGo);

            world.Receive("review.recheck", "recheck", new { chat_id = "earlier" });

            JsonElement refused = world.Reply("error", "recheck");
            letGo.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first start never finished");
            Assert.True(first.Result);
            Assert.Equal("BackendUnavailable", refused.GetProperty("error_class").GetString());
            Assert.Empty(world.Backend.Sessions);
        }
        finally
        {
            letGo.Set();
        }
    }

    /// <summary>
    /// A settings save that chooses <paramref name="runRoot"/> for runs and changes nothing else, whose restart is
    /// made at once and succeeds: the run root in force moves to it.
    /// </summary>
    private static void MoveTheRunRootInForce(RestartWorld world, string runRoot)
    {
        world.Receive("settings.save", "move-run-root", Choosing(runRoot, Save()));
        world.Reply("settings.saved", "move-run-root");
        Assert.Equal(runRoot, world.Host.RunRoot);
    }

    /// <summary>
    /// One kind of start that makes a review session (owner decision 152A): made ready with the bridge
    /// on the review's document - whatever has to exist before it can be pressed - then pressed.
    /// </summary>
    private sealed class SessionStart
    {
        private readonly RestartWorld _world;
        private readonly string _kind;
        private string? _chatId;
        private JsonElement _context;

        public SessionStart(RestartWorld world, string kind)
        {
            _world = world;
            _kind = kind;
        }

        /// <summary>Whether the start makes a run folder and extracts into it: a new review, a Retry of one among them.</summary>
        public bool Extracts => _kind == "review" || _kind == "prepared review" || _kind == "retry";

        public void Ready()
        {
            switch (_kind)
            {
                case "review":
                case "prepared review":
                    return;

                case "retry":
                    _world.Track("failed");
                    _chatId = "failed";
                    return;

                case "recheck":
                    _world.Track("waiting");
                    _chatId = "waiting";
                    return;

                case "context review":
                case "context retry":
                    _world.Receive("context.prepare", "context", new { });
                    JsonElement prepared = _world.Reply("context.prepared", "context");
                    _context = JsonSerializer.SerializeToElement(new
                    {
                        run_id = prepared.GetProperty("run_id").GetString(),
                        context_id = Guid.NewGuid().ToString(),
                        head_digest = new string('a', 64),
                        package_sha256 = prepared.GetProperty("package_sha256").GetString(),
                    });
                    if (_kind == "context retry")
                    {
                        _world.Receive("context.review", "first", _context);
                        _chatId = _world.Reply("review.started", "first").GetProperty("chat_id").GetString();
                    }

                    return;

                default:
                    throw new ArgumentOutOfRangeException(nameof(_kind), _kind, "no such start");
            }
        }

        public void Press(string id)
        {
            switch (_kind)
            {
                case "review":
                    _world.Receive("review.start", id, new { });
                    return;

                case "prepared review":
                    // The page prepares every review it starts, and a preparation is used up by the start.
                    _world.Receive("review.prepare", id + "-prepare", new { });
                    string preparation = _world.Reply("review.prepared", id + "-prepare").GetProperty("preparation_id").GetString()!;
                    _world.Receive("review.start", id, new { preparation_id = preparation });
                    return;

                case "retry":
                case "context retry":
                    _world.Receive("review.start", id, new { retry_of = _chatId });
                    return;

                case "context review":
                    _world.Receive("context.review", id, _context);
                    return;

                case "recheck":
                    _world.Receive("review.recheck", id, new { chat_id = _chatId });
                    return;
            }
        }

        public void AssertStarted(string id) =>
            _world.Reply(_kind == "recheck" ? "review.rechecked" : "review.started", id);
    }

    // ---- 16. a check holds the restart back (owner decision 157A) --------------------------------

    /// <summary>The Review tab's sentence for a save made while a check is in progress (owner decision 157A).</summary>
    private const string CheckPromise = "the settings are saved; the backend restarts when the running check ends.";

    /// <summary>
    /// A new review, a turn call or a remodel run refused while a check holds the restart back (owner decision 157A):
    /// 145A's words for a remodel run, naming the check, pinned word for word.
    /// </summary>
    private const string CheckHoldsIt =
        "the backend restarts with the saved settings when the running check ends, and nothing new starts "
        + "before then. Wait for the check to end, then try again.";

    /// <summary>...while a check on each check tab holds it back.</summary>
    private const string ChecksHoldIt =
        "the backend restarts with the saved settings when the running checks end, and nothing new starts "
        + "before then. Wait for the checks to end, then try again.";

    /// <summary>...while a remodel run and a check hold it back together.</summary>
    private const string RemodelRunAndCheckHoldIt =
        "the backend restarts with the saved settings when the remodel run and the running check end, and nothing "
        + "new starts before then. Wait for them to end, then try again.";

    /// <summary>
    /// A check refused while a turn holds the restart back, on a check tab, which has no Stop of the turn's: 145A's
    /// words for a remodel run, naming a check.
    /// </summary>
    private const string TurnHoldsTheCheck =
        "the backend restarts with the saved settings when the running review turn ends, and no check starts "
        + "before then. Wait for the turn to end, or press Stop on the Review tab, then try again.";

    /// <summary>...while the backend does not answer whether a turn runs; the settings are saved on the Review tab.</summary>
    private const string NoAnswerHoldsTheCheck =
        "the review backend did not answer whether a turn is running, so it has not been restarted with the "
        + "saved settings, and no check starts before then. Save the settings again on the Review tab "
        + "to restart it, then try again.";

    /// <summary>
    /// Owner decision 157A: a save made while a check is in progress - on the Model check or the Standards tab, from
    /// its press until the page's evaluation of it has been answered - is kept: written, saved in the host and
    /// answered `settings.saved`. Its restart waits for the check, as one made during a remodel run waits for the
    /// run, and the pane says so; before 157A it restarted the backend at once, under the check. Nothing is asked of
    /// the backend while the check lasts - the check is known without it - and once it ends the backend restarts
    /// once, with the saved settings, and every tab is told.
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ASaveDuringACheckIsKeptAndItsRestartWaitsForTheCheck(string tab)
    {
        int checking = 1;
        using var world = new RestartWorld();
        world.Checking(tab, () => Volatile.Read(ref checking) == 1);
        world.Open();
        world.Track("chat-1");

        world.Receive("settings.save", "save", Save(model: "gpt-5.6-mini", effort: "low"));

        Assert.Equal("low", world.Reply("settings.saved", "save").GetProperty("settings").GetProperty("effort").GetString());
        Assert.Equal("low", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
        JsonElement status = world.Last("status");
        Assert.Equal("error", status.GetProperty("stage").GetString());
        Assert.Equal(CheckPromise, status.GetProperty("message").GetString());

        // The check goes on with the backend it began on: no restart is asked for, and nothing is asked of the
        // backend, while it lasts.
        int asked = world.Backend.Questions;
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.Equal(0, world.OtherTabsTold);
        Assert.Equal(asked, world.Backend.Questions);

        Volatile.Write(ref checking, 0);
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted after the check");
        (UserSettings settings, _) = Assert.Single(world.Backend.Restarts);
        Assert.Equal("gpt-5.6-mini", settings.Model);
        Assert.Equal("low", settings.Effort);
        Eventually(() => world.OtherTabsTold == 1, "the other tabs told");
    }

    /// <summary>
    /// The save's sentence names everything its restart waits for (owner decisions 145A and 157A): a turn that
    /// started during the save, a remodel run, and the checks in progress - one, or one on each check tab - in that
    /// order, with "and" before the last and the verb agreeing. 145A's three sentences are the rows with no check,
    /// word for word.
    /// </summary>
    [Theory]
    [InlineData(false, false, "Model check", "the settings are saved; the backend restarts when the running check ends.")]
    [InlineData(false, false, "Standards", "the settings are saved; the backend restarts when the running check ends.")]
    [InlineData(false, false, "both", "the settings are saved; the backend restarts when the running checks end.")]
    [InlineData(true, false, "Model check", "the settings are saved; the backend restarts when the running turn and the running check end.")]
    [InlineData(true, false, "both", "the settings are saved; the backend restarts when the running turn and the running checks end.")]
    [InlineData(false, true, "Standards", "the settings are saved; the backend restarts when the remodel run and the running check end.")]
    [InlineData(false, true, "both", "the settings are saved; the backend restarts when the remodel run and the running checks end.")]
    [InlineData(true, true, "Model check", "the settings are saved; the backend restarts when the running turn, the remodel run and the running check end.")]
    [InlineData(true, true, "both", "the settings are saved; the backend restarts when the running turn, the remodel run and the running checks end.")]
    [InlineData(false, true, "none", "the settings are saved; the backend restarts when the remodel run ends.")]
    [InlineData(true, true, "none", "the settings are saved; the backend restarts when the running turn and the remodel run end.")]
    [InlineData(true, false, "none", "the settings are saved; the backend restarts when the running turn ends.")]
    public void ASavesSentenceNamesEverythingItsRestartWaitsFor(bool turn, bool remodelRun, string checks, string sentence)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10), BackendBusy = () => remodelRun };
        world.Checking(checks, () => true);
        world.Open();
        world.Track("chat-1");

        if (turn)
        {
            SaveAsATurnStarts(world, "save", Save(effort: "low"));
        }
        else
        {
            world.Receive("settings.save", "save", Save(effort: "low"));
        }

        world.Reply("settings.saved", "save");
        Assert.Equal(sentence, world.Last("status").GetProperty("message").GetString());
        Assert.Equal(0, world.Backend.Attempts);
    }

    /// <summary>
    /// A check that holds the restart back holds a new review and a turn call back too, as a remodel run does (owner
    /// decision 157A): neither may run on the old backend, and the restart cannot be made under the check. The
    /// refusal names the check - one, or one on each check tab - under its own class, `CheckRunning`, whose sentence
    /// is true of it; a new review is refused retryable, as every refusal of a review is, and a turn call with the
    /// flag a turn's refusal carries. Nothing is extracted, created or restarted.
    /// </summary>
    [Theory]
    [InlineData("a new review", "Model check")]
    [InlineData("a new review", "both")]
    [InlineData("a turn call", "Standards")]
    [InlineData("a turn call", "both")]
    public void WhileACheckHoldsTheRestartANewReviewOrATurnCallIsRefusedSayingSo(string caller, string checks)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Checking(checks, () => true);
        world.Open();
        world.Track("chat-1");
        world.Receive("settings.save", "save", Save(effort: "low"));
        world.Reply("settings.saved", "save");

        string? errorClass;
        string? message;
        bool retryable;
        if (caller == "a new review")
        {
            world.Receive("review.start", "start", new { });
            JsonElement error = world.Reply("error", "start");
            errorClass = error.GetProperty("error_class").GetString();
            message = error.GetProperty("message").GetString();
            retryable = error.GetProperty("retryable").GetBoolean();
        }
        else
        {
            BackendRequestException? refusal = world.Host.PageTurnRefusal();
            Assert.NotNull(refusal);
            errorClass = refusal!.ErrorClass;
            message = refusal.Message;
            retryable = refusal.Retryable;
        }

        Assert.Equal("CheckRunning", errorClass);
        Assert.Equal(checks == "both" ? ChecksHoldIt : CheckHoldsIt, message);
        Assert.Equal(caller == "a new review", retryable);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        Assert.Equal(0, world.Backend.Attempts);
    }

    /// <summary>
    /// A check is named before a backend that does not answer, as a remodel run is (owner decision 157A): the add-in
    /// knows of the check without asking the backend, and while it lasts the watcher asks the backend nothing, so it
    /// never stops waiting for want of an answer, nor tells the engineer to save again, which would restart the
    /// backend under the check.
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ACheckIsNamedBeforeABackendThatDoesNotAnswer(string tab)
    {
        int looks = 0;
        using var world = new RestartWorld();
        world.Checking(tab, () =>
        {
            Interlocked.Increment(ref looks);
            return true;
        });
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        world.Backend.StopsAnswering();
        int asked = world.Backend.Questions;

        int from = Volatile.Read(ref looks);
        Eventually(() => Volatile.Read(ref looks) >= from + DeferredRestart.UnansweredLooks * 3, "the host's looks");

        Assert.Equal(asked, world.Backend.Questions);
        Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("message").GetString() == NotAnsweringYet);
        world.Receive("review.start", "start", new { });
        Assert.Equal("CheckRunning", world.Reply("error", "start").GetProperty("error_class").GetString());
        Assert.Equal(0, world.Dump.Runs);
    }

    /// <summary>
    /// With no backend process at all a check holds nothing (owner decision 157A): there is no backend to restart under
    /// it, and the restart is what brings back the backend its evaluation needs - 143A's rule for the look. A remodel run
    /// holds the restart back even then, since every call it makes fails and it cannot last (145A); a check's extraction
    /// asks no backend and lasts minutes, and holding the restart would only waste it. So a save made while a check is in
    /// progress with no backend up restarts the backend at once, with the saved settings, saying nothing of a wait.
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void WithNoBackendAtAllACheckHoldsNothingAndASaveStartsTheBackend(string tab)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Checking(tab, () => true);
        world.Backend.Down = true;
        world.Open();

        world.Receive("settings.save", "save", Save(effort: "low"));

        Assert.Equal("low", world.Reply("settings.saved", "save").GetProperty("settings").GetProperty("effort").GetString());
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
        Assert.NotNull(world.Backend.Endpoint);
        Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("message").GetString() == CheckPromise);
    }

    /// <summary>
    /// ...and a restart that waits for a check made with a backend up is made once that backend has stopped, though the
    /// check is still in progress: no backend is left to restart under it, and its evaluation needs one (owner decision
    /// 157A). The check's page is told the backend restarted, and its evaluation goes to the new backend.
    /// </summary>
    [Fact]
    public void ARestartThatWaitsForACheckIsMadeOnceTheBackendHasStopped()
    {
        using var world = new RestartWorld();
        world.Checking("Model check", () => true);
        world.Open();
        world.Receive("settings.save", "save", Save(effort: "low"));
        Assert.Equal(CheckPromise, world.Last("status").GetProperty("message").GetString());
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);

        world.Backend.Down = true;

        Eventually(() => world.Posted("backend.restarted").Length == 1, "the restart once the backend stopped");
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
        Eventually(() => world.OtherTabsTold == 1, "the other tabs told");
    }

    /// <summary>
    /// The pane's proxy answers a turn call a check holds back with the status a turn's refusal is answered with -
    /// 409, as `TurnRunning` and `RemodelRunning` are - never sending it (owner decision 157A).
    /// </summary>
    [Fact]
    public void TheProxyAnswersATurnCallACheckHoldsBackAsATurnsRefusal()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Checking("Model check", () => true);
        world.Open();
        world.Track("chat-1");
        world.Receive("settings.save", "save", Save(effort: "low"));
        var handler = new BackendProxyHandler(
            () => world.Backend.Endpoint,
            _ => throw new InvalidOperationException("the call must not have been sent"),
            () => world.Host.PageTurnRefusal());

        ProxiedResponse? response = handler.TryServe(BackendProxy.PageOrigin + "/sessions/chat-1/messages", "POST", null, null);

        Assert.Equal(409, response!.Status);
        string body = Encoding.UTF8.GetString(response.Content);
        Assert.Contains("\"error_class\":\"CheckRunning\"", body, StringComparison.Ordinal);
        Assert.Contains("\"retryable\":false", body, StringComparison.Ordinal);
    }

    /// <summary>
    /// A remodel run asked to begin while a check holds the restart back is refused, saying so, and never begins; once
    /// the check is over the next press makes the restart first and begins on the restarted backend (owner decision
    /// 157A).
    /// </summary>
    [Fact]
    public void ARemodelRunWhileACheckHoldsTheRestartIsRefusedSayingSo()
    {
        int checking = 1;
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Checking("Model check", () => Volatile.Read(ref checking) == 1);
        world.Open();
        world.Receive("settings.save", "save", Save(effort: "low"));
        int begun = 0;

        BackendRequestException? refusal = world.Host.BeginRemodelRun(() => begun++);

        Assert.NotNull(refusal);
        Assert.Equal("CheckRunning", refusal!.ErrorClass);
        Assert.Equal(CheckHoldsIt, refusal.Message);
        Assert.True(refusal.Retryable);
        Assert.Equal(0, begun);
        Assert.Equal(0, world.Backend.Attempts);

        Volatile.Write(ref checking, 0);
        Assert.Null(world.Host.BeginRemodelRun(() => begun++));
        Assert.Equal(1, begun);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// Work that holds the restart back together is named together (owner decision 157A): a remodel run and a check
    /// hold a new review back under the remodel run's class - a remodel run is in progress, as its sentence on the
    /// Review tab says - in words that name both, so a refusal never says the restart comes when the run ends while a
    /// check holds it too.
    /// </summary>
    [Fact]
    public void ARemodelRunAndACheckHoldingTheRestartTogetherAreNamedTogether()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10), BackendBusy = () => true };
        world.Checking("Standards", () => true);
        world.Open();
        world.Receive("settings.save", "save", Save(effort: "low"));

        world.Receive("review.start", "start", new { });

        JsonElement error = world.Reply("error", "start");
        Assert.Equal("RemodelRunning", error.GetProperty("error_class").GetString());
        Assert.Equal(RemodelRunAndCheckHoldIt, error.GetProperty("message").GetString());
        Assert.Equal(0, world.Dump.Runs);
    }

    /// <summary>
    /// With nothing waiting, a check begins at once beside any work in progress - a check on the other tab, a remodel
    /// run - and nothing is asked of the backend: a check holds back only a settings restart (owner decision 157A).
    /// </summary>
    [Theory]
    [InlineData("nothing else")]
    [InlineData("a remodel run")]
    [InlineData("a check on the other tab")]
    public void ACheckWithNoRestartWaitingBeginsAtOnceBesideOtherWork(string beside)
    {
        using var world = new RestartWorld { BackendBusy = () => beside == "a remodel run" };
        world.Checking("Standards", () => beside == "a check on the other tab");
        world.Open();
        world.Track("chat-1");
        int begun = 0;

        Assert.Null(world.Host.BeginCheck(() => begun++));

        Assert.Equal(1, begun);
        Assert.Equal(0, world.Backend.Questions);
        Assert.Equal(0, world.Backend.RestartsAsked);
    }

    /// <summary>
    /// A check started the moment the turn ends makes the waiting restart first, as a new review and a remodel run do,
    /// and begins on the restarted backend with the saved settings, every page told of the restart before it begins
    /// (owner decision 157A).
    /// </summary>
    [Fact]
    public void ACheckTheMomentTheTurnEndsRestartsTheBackendFirstAndBeginsOnIt()
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(model: "gpt-5.6-mini", effort: "low"));
        world.Backend.EndTurn("chat-1");
        int restartsAtTheBeginning = -1;
        int toldAtTheBeginning = -1;

        BackendRequestException? refusal = world.Host.BeginCheck(() =>
        {
            restartsAtTheBeginning = world.Backend.Restarts.Length;
            toldAtTheBeginning = world.Posted("backend.restarted").Length + world.OtherTabsTold;
        });

        Assert.Null(refusal);
        Assert.Equal(1, restartsAtTheBeginning);
        Assert.Equal(2, toldAtTheBeginning);
        Assert.Equal("gpt-5.6-mini", Assert.Single(world.Backend.Restarts).Settings.Model);
    }

    /// <summary>
    /// While something holds the restart back a check is refused, saying what, and its step never runs (owner decision
    /// 157A): a turn (`TurnRunning`), in words for a check tab, which has no Stop of the turn's; a backend that does
    /// not answer (`BackendUnavailable`); a remodel run (`RemodelRunning`); or the check on the other tab
    /// (`CheckRunning`). The restart still waits, and the next press makes it once nothing holds it back.
    /// </summary>
    [Theory]
    [InlineData("turn", "TurnRunning")]
    [InlineData("no answer", "BackendUnavailable")]
    [InlineData("remodel run", "RemodelRunning")]
    [InlineData("the other check", "CheckRunning")]
    public void ACheckWhileSomethingHoldsTheRestartIsRefusedSayingWhat(string cause, string expectedClass)
    {
        int remodelling = cause == "remodel run" ? 1 : 0;
        int otherCheck = cause == "the other check" ? 1 : 0;
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10), BackendBusy = () => Volatile.Read(ref remodelling) == 1 };
        world.Checking("Standards", () => Volatile.Read(ref otherCheck) == 1);
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        if (cause != "turn")
        {
            world.Backend.EndTurn("chat-1");
        }

        if (cause == "no answer")
        {
            world.Backend.StopsAnswering(questions: 1);
        }

        int begun = 0;
        BackendRequestException? refusal = world.Host.BeginCheck(() => begun++);

        Assert.NotNull(refusal);
        Assert.Equal(expectedClass, refusal!.ErrorClass);
        Assert.Equal(
            cause == "turn" ? TurnHoldsTheCheck
                : cause == "no answer" ? NoAnswerHoldsTheCheck
                : cause == "remodel run" ? RemodelRunHoldsIt
                : CheckHoldsIt,
            refusal.Message);
        Assert.True(refusal.Retryable);
        Assert.Equal(0, begun);
        Assert.Equal(0, world.Backend.Attempts);

        world.Backend.EndTurn("chat-1");
        Volatile.Write(ref remodelling, 0);
        Volatile.Write(ref otherCheck, 0);
        Assert.Null(world.Host.BeginCheck(() => begun++));
        Assert.Equal(1, begun);
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// A check started while a restart is being made waits for it and begins on the restarted backend - the
    /// watcher's restart, and a save's own, made at once (owner decision 157A).
    /// </summary>
    [Theory]
    [InlineData("the watcher")]
    [InlineData("a save")]
    public void ACheckWhileARestartIsBeingMadeWaitsForItThenBegins(string maker)
    {
        using var world = new RestartWorld { Poll = maker == "a save" ? TimeSpan.FromMinutes(10) : TimeSpan.FromMilliseconds(10) };
        using var hold = new ManualResetEventSlim(false);
        Caller<bool>? save = null;
        try
        {
            world.Open();
            world.Track("chat-1");
            if (maker == "the watcher")
            {
                SaveAsATurnStarts(world, "save", Save(effort: "low"));
                world.Backend.Hold = hold;
                world.Backend.EndTurn("chat-1");
            }
            else
            {
                world.Backend.Hold = hold;
                save = new Caller<bool>(() =>
                {
                    world.Receive("settings.save", "save", Save(effort: "low"));
                    return true;
                });
            }

            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the restart was never begun");
            int restartsAtTheBeginning = -1;
            var check = new Caller<BackendRequestException?>(() =>
                world.Host.BeginCheck(() => restartsAtTheBeginning = world.Backend.Restarts.Length));
            Assert.False(check.Finishes(TimeSpan.FromMilliseconds(300)), "the check did not wait for the restart being made");

            hold.Set();
            Assert.True(check.Finishes(TimeSpan.FromSeconds(10)), "the check never began");
            Assert.Null(check.Result);
            Assert.Equal(1, restartsAtTheBeginning);
            Assert.True(save == null || save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
            Assert.Single(world.Backend.Restarts);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// A check whose restart fails is refused with that failure, masked, and never begins - its own restart, or a
    /// save's it waited for, which failed before it stopped anything and so left the old backend up with the old
    /// settings (owner decision 157A).
    /// </summary>
    [Theory]
    [InlineData("its own")]
    [InlineData("a save's")]
    public void ACheckWhoseRestartFailsIsRefusedWithThatFailureAndNeverBegins(string whose)
    {
        string failure = "the child would not start with " + OpenAiKey;
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Open();
            world.Track("chat-1");
            int begun = 0;
            BackendRequestException? refusal;
            if (whose == "its own")
            {
                SaveAsATurnStarts(world, "save", Save(effort: "low"));
                world.Backend.EndTurn("chat-1");
                world.Backend.RestartFailure = new InvalidOperationException(failure);
                refusal = world.Host.BeginCheck(() => begun++);
            }
            else
            {
                world.Backend.Hold = hold;
                world.Backend.EarlyRestartFailure = new BackendStartException(failure);
                var save = new Caller<bool>(() =>
                {
                    world.Receive("settings.save", "save", Save(effort: "low"));
                    return true;
                });
                Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the save never began its restart");
                var check = new Caller<BackendRequestException?>(() => world.Host.BeginCheck(() => begun++));
                Assert.False(check.Finishes(TimeSpan.FromMilliseconds(300)), "the check did not wait for the save's restart");
                hold.Set();
                Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
                Assert.True(check.Finishes(TimeSpan.FromSeconds(10)), "the check never got an answer");
                refusal = check.Result;
                Assert.NotNull(world.Backend.Endpoint);
                Assert.Equal(0, world.Backend.Generation);
            }

            Assert.NotNull(refusal);
            Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
            Assert.StartsWith("the child would not start with ", refusal.Message, StringComparison.Ordinal);
            Assert.DoesNotContain(OpenAiKey, refusal.Message, StringComparison.Ordinal);
            Assert.True(refusal.Retryable);
            Assert.Equal(0, begun);
            world.AssertNothingPostedContains(OpenAiKey);
        }
        finally
        {
            hold.Set();
        }
    }

    // ---- 16b. end to end, per tab and per ordering (owner decision 157A) ---------------------------

    /// <summary>
    /// Owner decision 157A, end to end on each check tab: a save made while the check reads the model waits for the
    /// check, which runs to its end on the backend it began on - its extraction handed to the page, and the page's
    /// evaluation, made through the pane's proxy, answered by that backend - and only then does the backend restart,
    /// once, with the saved settings. Before 157A the save restarted the backend under the extraction, and the
    /// evaluation met the restarted backend: the extraction was wasted.
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ASaveWhileACheckReadsTheModelWaitsUntilItsEvaluationIsAnswered(string tab)
    {
        using var world = new RestartWorld();
        world.Open();
        using var check = new CheckTab(world, tab);
        int restartsAskedDuringTheExtraction = -1;
        world.Dump.OnRun = () =>
        {
            world.Receive("settings.save", "save", Save(effort: "low"));
            Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
            restartsAskedDuringTheExtraction = world.Backend.RestartsAsked;
        };

        check.Press("c1");
        world.Dump.OnRun = null;

        Assert.Equal(0, restartsAskedDuringTheExtraction);
        world.Reply("settings.saved", "save");
        Assert.Equal(CheckPromise, world.Last("status").GetProperty("message").GetString());
        string runDirectory = check.Extracted("c1");
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.True(check.CheckInProgress);

        check.WhileEvaluating = () => Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        ProxiedResponse answer = check.Evaluate(runDirectory);

        Assert.Equal(201, answer.Status);
        CheckTab.Evaluation evaluation = Assert.Single(check.Evaluations);
        Assert.Equal(runDirectory, evaluation.RunDirectory);
        Assert.Equal(0, evaluation.Generation);
        Assert.Equal(0, evaluation.RestartsAskedWhenAnswered);
        Eventually(() => world.Posted("backend.restarted").Length == 1, "the restart once the evaluation is answered");
        Assert.Equal("low", Assert.Single(world.Backend.Restarts).Settings.Effort);
        Assert.False(check.CheckInProgress);
    }

    /// <summary>
    /// ...and a save made between the extraction and the evaluation - the run handed to the page, its evaluation not
    /// yet answered - waits for the evaluation, which is answered by the backend the check began on, however long it
    /// is out (owner decision 157A).
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ASaveBetweenACheckExtractionAndItsEvaluationWaitsForTheEvaluation(string tab)
    {
        using var world = new RestartWorld();
        world.Open();
        using var check = new CheckTab(world, tab);
        check.Press("c1");
        string runDirectory = check.Extracted("c1");

        world.Receive("settings.save", "save", Save(effort: "low"));

        world.Reply("settings.saved", "save");
        Assert.Equal(CheckPromise, world.Last("status").GetProperty("message").GetString());
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);

        check.WhileEvaluating = () => Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(201, check.Evaluate(runDirectory).Status);

        CheckTab.Evaluation evaluation = Assert.Single(check.Evaluations);
        Assert.Equal(0, evaluation.Generation);
        Assert.Equal(0, evaluation.RestartsAskedWhenAnswered);
        Eventually(() => world.Backend.Restarts.Length == 1, "the restart once the evaluation is answered");
    }

    /// <summary>
    /// A check started while a restart waits makes the restart first, as a remodel run does, and so runs on the
    /// restarted backend with the saved settings: the page is told before the gate, in this tab's words, that the
    /// press waits for the restart; told the backend restarted before its extraction is answered; and its
    /// evaluation is answered by the restarted backend (owner decision 157A).
    /// </summary>
    [Theory]
    [InlineData("Model check", "Waiting for the review backend to restart with the saved settings, then reading the feature tree...")]
    [InlineData("Standards", "Waiting for the review backend to restart with the saved settings, then reading the document...")]
    public void ACheckStartedWhileARestartWaitsMakesItFirstAndIsEvaluatedOnTheRestartedBackend(string tab, string waiting)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        using var check = new CheckTab(world, tab);
        SaveAsATurnStarts(world, "save", Save(model: "gpt-5.6-mini", effort: "low"));
        world.Backend.EndTurn("chat-1");

        check.Press("c1");

        string runDirectory = check.Extracted("c1");
        Assert.Equal("gpt-5.6-mini", Assert.Single(world.Backend.Restarts).Settings.Model);
        JsonElement first = check.Posted("status")[0];
        Assert.Equal("backend_starting", first.GetProperty("stage").GetString());
        Assert.Equal(waiting, first.GetProperty("message").GetString());
        string[] types = check.Types();
        Assert.True(
            Array.IndexOf(types, "backend.restarted") >= 0
                && Array.IndexOf(types, "backend.restarted") < Array.IndexOf(types, check.ExtractedType),
            "the tab was not told the backend restarted before its extraction was answered: " + string.Join(", ", types));
        Assert.Equal(1, world.Dump.Runs);

        Assert.Equal(201, check.Evaluate(runDirectory).Status);
        Assert.Equal(1, Assert.Single(check.Evaluations).Generation);
    }

    /// <summary>
    /// A check whose gate waited for a save's restart made at once is told of that restart before its extraction is
    /// answered, as a check whose gate made the restart is (the case above), so its page evaluates with the token of
    /// the restarted backend (owner decision 157A, the reviews: the race review and Codex). The page's evaluation waits
    /// for an `init` only once it has been told (`check-page.js`, `call`, `initSettled`); told after the reply, it
    /// evaluates with the token of the backend the restart replaced and is refused, the extraction wasted. A save used
    /// to tell the other tabs after its restart had let the restart's lock go, so nothing ordered the telling before a
    /// gate that waited on that lock. The save's thread is held here as it tells them - as a Review pump that was
    /// descheduled would be - until the check has replied, or two seconds at most, so telling them under the lock
    /// passes.
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ACheckThatWaitedForASavesRestartIsToldOfItBeforeItsExtractionIsAnswered(string tab)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        using var hold = new ManualResetEventSlim(false);
        try
        {
            world.Open();
            using var check = new CheckTab(world, tab);
            world.TellingTheOtherTabs = () =>
            {
                SpinWait.SpinUntil(() => check.Posted(check.ExtractedType).Length > 0, TimeSpan.FromSeconds(2));
                check.BackendRestarted();
            };
            world.Backend.Hold = hold;
            var save = new Caller<bool>(() =>
            {
                world.Receive("settings.save", "save", Save(effort: "low"));
                return true;
            });
            Assert.True(world.Backend.Entered.Wait(TimeSpan.FromSeconds(10)), "the save never began its restart");
            var press = new Caller<bool>(() =>
            {
                check.Press("c1");
                return true;
            });
            Assert.False(press.Finishes(TimeSpan.FromMilliseconds(300)), "the check did not wait for the save's restart");

            hold.Set();

            Assert.True(press.Finishes(TimeSpan.FromSeconds(10)), "the check never finished");
            Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
            world.Reply("settings.saved", "save");
            string runDirectory = check.Extracted("c1");
            Assert.Equal(1, world.Backend.Generation);
            string[] types = check.Types();
            Assert.True(
                Array.IndexOf(types, "backend.restarted") >= 0
                    && Array.IndexOf(types, "backend.restarted") < Array.IndexOf(types, check.ExtractedType),
                "the tab was not told the backend restarted before its extraction was answered: " + string.Join(", ", types));

            Assert.Equal(201, check.Evaluate(runDirectory).Status);
            CheckTab.Evaluation evaluation = Assert.Single(check.Evaluations);
            Assert.True(evaluation.Authorized, "the page evaluated with the token of the backend the restart replaced");
            Assert.Equal(1, evaluation.Generation);
        }
        finally
        {
            hold.Set();
        }
    }

    /// <summary>
    /// The reviews of 157A (the race review, Codex and the mutation review): a check's reply, its page's `init` and its
    /// evaluation all wait on SOLIDWORKS' application thread, which another tab's extraction holds for its whole
    /// length. A reply held up there for over a minute - while a save waits for the check - still holds the restart:
    /// the run's minute starts once the reply has reached the page, which then evaluates on the backend the check began
    /// on, and the restart is made once that evaluation is answered. Before, the minute ran from the hand-over, ran out
    /// while the page could not yet read its reply, and the restart was made under it - its evaluation refused, with the
    /// token of the backend the restart replaced.
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ACheckWhoseReplyWaitsOnABusyApplicationThreadHoldsTheRestartUntilItIsEvaluated(string tab)
    {
        using var world = new RestartWorld();
        world.Open();
        using var check = new CheckTab(world, tab);
        world.Pane.Hold();
        check.Press("c1");
        string runDirectory = check.Extracted("c1");
        world.Receive("settings.save", "save", Save(effort: "low"));
        world.Reply("settings.saved", "save");

        check.Advance(TimeSpan.FromMinutes(5));
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.True(check.CheckInProgress);

        world.Pane.Release();
        Assert.Equal(201, check.Evaluate(runDirectory).Status);

        CheckTab.Evaluation evaluation = Assert.Single(check.Evaluations);
        Assert.True(evaluation.Authorized);
        Assert.Equal(0, evaluation.Generation);
        Assert.Equal(0, evaluation.RestartsAskedWhenAnswered);
        Eventually(() => world.Backend.Restarts.Length == 1, "the restart once the evaluation is answered");
    }

    /// <summary>
    /// The reviews of 157A (Codex's regression): two checks pressed back to back, a save made while the second reads its
    /// model, and the first's reply held up behind that extraction on SOLIDWORKS' application thread for over a minute.
    /// Each check's minute starts once its reply has reached its page, so the restart waits for both evaluations, in
    /// whichever order they come, and each is answered by the backend the checks began on. Before, the first check's
    /// minute ran out during the second's extraction, and the restart was made the moment the second's evaluation was
    /// answered, while the first's page had not yet called.
    /// </summary>
    [Fact]
    public void TwoChecksBackToBackWithTheirRepliesHeldUpAreEachEvaluatedBeforeTheRestart()
    {
        using var world = new RestartWorld();
        world.Open();
        using var model = new CheckTab(world, "Model check");
        using var standards = new CheckTab(world, "Standards");
        world.Pane.Hold();
        model.Press("m1");
        string modelRun = model.Extracted("m1");
        world.Dump.OnRun = () =>
        {
            world.Receive("settings.save", "save", Save(effort: "low"));
            model.Advance(CheckHoldOptions.DefaultHandOverLimit + TimeSpan.FromMinutes(1));
            standards.Advance(CheckHoldOptions.DefaultHandOverLimit + TimeSpan.FromMinutes(1));
        };

        standards.Press("s1");
        world.Dump.OnRun = null;
        string standardsRun = standards.Extracted("s1");
        world.Reply("settings.saved", "save");
        world.Pane.Release();

        Assert.Equal(201, standards.Evaluate(standardsRun).Status);
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.True(model.CheckInProgress);
        Assert.Equal(201, model.Evaluate(modelRun).Status);

        foreach (CheckTab.Evaluation evaluation in model.Evaluations.Concat(standards.Evaluations))
        {
            Assert.True(evaluation.Authorized);
            Assert.Equal(0, evaluation.Generation);
            Assert.Equal(0, evaluation.RestartsAskedWhenAnswered);
        }

        Eventually(() => world.Backend.Restarts.Length == 1, "the restart once both evaluations are answered");
    }

    /// <summary>
    /// The reviews of 157A (the race review's second case): two checks pressed back to back, and a save made once both
    /// have passed their gates. The second's extraction holds SOLIDWORKS' application thread, through which the first's
    /// page evaluates, until long after the first's minute - modelled by moving its clock past it during that
    /// extraction. The first's evaluation, held up past its minute, takes its hold back, since no restart has been
    /// made since its gate: the restart waits for it, though the second's evaluation is answered first, and is made
    /// once it is answered.
    /// </summary>
    [Fact]
    public void AnEvaluationHeldUpBehindAnotherChecksExtractionIsStillHeld()
    {
        using var world = new RestartWorld();
        using var standardsAnswered = new ManualResetEventSlim(false);
        using var entered = new ManualResetEventSlim(false);
        world.Open();
        using var model = new CheckTab(world, "Model check");
        using var standards = new CheckTab(world, "Standards");
        model.Press("m1");
        string modelRun = model.Extracted("m1");
        world.Dump.OnRun = () =>
        {
            world.Receive("settings.save", "save", Save(effort: "low"));
            model.Advance(CheckHoldOptions.DefaultHandOverLimit + TimeSpan.FromSeconds(1));
        };

        standards.Press("s1");
        world.Dump.OnRun = null;

        string standardsRun = standards.Extracted("s1");
        world.Reply("settings.saved", "save");
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.False(model.CheckInProgress);
        Assert.True(standards.CheckInProgress);

        model.WhileEvaluating = () =>
        {
            entered.Set();
            Assert.True(standardsAnswered.Wait(TimeSpan.FromSeconds(10)), "the Standards evaluation was never answered");
            Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        };
        var late = new Caller<ProxiedResponse>(() => model.Evaluate(modelRun));
        Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the Model check's evaluation was never sent");
        Assert.Equal(201, standards.Evaluate(standardsRun).Status);
        standardsAnswered.Set();
        Assert.True(late.Finishes(TimeSpan.FromSeconds(20)), "the Model check's evaluation was never answered");

        CheckTab.Evaluation evaluation = Assert.Single(model.Evaluations);
        Assert.True(evaluation.Authorized);
        Assert.Equal(0, evaluation.Generation);
        Assert.True(
            evaluation.RestartsAskedWhenAnswered == 0,
            "the backend restarted while the Model check's evaluation was out: restarts asked when it was answered = "
                + evaluation.RestartsAskedWhenAnswered);
        Eventually(() => world.Backend.Restarts.Length == 1, "the restart once the Model check's evaluation is answered");
    }

    /// <summary>
    /// A check started while a turn holds the restart back is refused, in this tab's words, before anything is read,
    /// made or extracted, and holds nothing; the restart still waits for the turn alone, and once it ends the next
    /// press makes it first (owner decision 157A). A check refused on the spot - no document - makes no restart.
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ACheckStartedWhileATurnHoldsTheRestartIsRefusedAndMakesNothing(string tab)
    {
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        using var check = new CheckTab(world, tab);
        SaveAsATurnStarts(world, "save", Save(effort: "low"));

        check.Press("c1");

        JsonElement error = check.Reply("error", "c1");
        Assert.Equal("TurnRunning", error.GetProperty("error_class").GetString());
        Assert.Equal(TurnHoldsTheCheck, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(check.RunFolders());
        Assert.False(check.CheckInProgress);
        Assert.Equal(0, world.Backend.Attempts);

        world.Backend.EndTurn("chat-1");
        PageDocument? part = world.Document;
        world.Document = null;
        check.Press("c2");
        Assert.Equal("NoDocument", check.Reply("error", "c2").GetProperty("error_class").GetString());
        Assert.Equal(0, world.Backend.Attempts);

        world.Document = part;
        check.Press("c3");
        check.Extracted("c3");
        Assert.Single(world.Backend.Restarts);
    }

    /// <summary>
    /// A check whose gate's restart fails is refused with the failure, masked, before anything is made, and holds
    /// nothing: the next save restarts the backend at once (owner decision 157A). Whether the restart failed before
    /// the old backend stopped or once it had.
    /// </summary>
    [Theory]
    [InlineData("Model check", "before the old backend stopped")]
    [InlineData("Standards", "once the old backend stopped")]
    public void ACheckWhoseRestartFailsIsRefusedWithTheFailureAndHoldsNothing(string tab, string when)
    {
        string failure = "FICT the child would not start with " + OpenAiKey;
        using var world = new RestartWorld { Poll = TimeSpan.FromMinutes(10) };
        world.Open();
        world.Track("chat-1");
        using var check = new CheckTab(world, tab);
        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        world.Backend.EndTurn("chat-1");
        if (when == "before the old backend stopped")
        {
            world.Backend.EarlyRestartFailure = new BackendStartException(failure);
        }
        else
        {
            world.Backend.RestartFailure = new InvalidOperationException(failure);
        }

        check.Press("c1");

        JsonElement error = check.Reply("error", "c1");
        Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
        Assert.StartsWith("FICT the child would not start with ", error.GetProperty("message").GetString(), StringComparison.Ordinal);
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(check.RunFolders());
        Assert.False(check.CheckInProgress);
        check.AssertNothingPostedContains(OpenAiKey);

        world.Backend.EarlyRestartFailure = null;
        world.Backend.RestartFailure = null;
        world.Receive("settings.save", "again", Save(effort: "medium"));
        world.Reply("settings.saved", "again");
        Assert.Equal("medium", world.Backend.Restarts.Last().Settings.Effort);
    }

    /// <summary>
    /// A restart that waited for a check and then failed is told as any restart that waited and failed is, once the
    /// check's evaluation has been answered by the backend it began on; the check's answer stands, and the check holds
    /// nothing any more (owner decision 157A).
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ARestartThatWaitedForACheckAndFailedLeavesTheCheckAnswered(string tab)
    {
        using var world = new RestartWorld();
        world.Open();
        using var check = new CheckTab(world, tab);
        check.Press("c1");
        string runDirectory = check.Extracted("c1");
        world.Backend.RestartFailure = new InvalidOperationException("FICT the new backend would not start");
        world.Receive("settings.save", "save", Save(effort: "low"));
        Assert.Equal(CheckPromise, world.Last("status").GetProperty("message").GetString());

        Assert.Equal(201, check.Evaluate(runDirectory).Status);

        Assert.Equal(0, Assert.Single(check.Evaluations).Generation);
        Eventually(
            () => world.Posted("status").Any(status =>
                (status.GetProperty("message").GetString() ?? string.Empty).StartsWith("FICT the new backend would not start", StringComparison.Ordinal)),
            "the restart's failure told");
        Assert.False(check.CheckInProgress);
        Assert.Empty(world.Backend.Restarts);
    }

    /// <summary>
    /// A page that never evaluates its check - reloaded, or closed, once the run was handed to it - holds the restart
    /// back no longer than the hand-over's limit, a minute, measured from the hand-over by a clock only the test moves:
    /// a moment short of it the restart still waits, and at it the restart is made. An evaluation that comes after
    /// the limit is not held, and goes on as before 157A (owner decision 157A): its page, told of the restart only
    /// after the reply that handed it the run, calls with the token of the backend the restart replaced, which the
    /// restarted one refuses. (Changed deliberately on the reviews of 157A: the page's token is the page's own now, from
    /// its `init`, where it was the backend's of the moment, which hid the refusal.)
    /// </summary>
    [Theory]
    [InlineData("Model check")]
    [InlineData("Standards")]
    public void ACheckWhosePageNeverEvaluatesItHoldsTheRestartNoLongerThanTheLimit(string tab)
    {
        using var world = new RestartWorld();
        world.Open();
        using var check = new CheckTab(world, tab);
        check.Press("c1");
        string runDirectory = check.Extracted("c1");
        world.Receive("settings.save", "save", Save(effort: "low"));
        world.Reply("settings.saved", "save");

        check.Advance(CheckHoldOptions.DefaultHandOverLimit - TimeSpan.FromMilliseconds(1));
        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        Assert.True(check.CheckInProgress);

        check.Advance(TimeSpan.FromMilliseconds(1));
        Eventually(() => world.Backend.Restarts.Length == 1, "the restart once the page has had its minute");
        Assert.False(check.CheckInProgress);

        Assert.Equal(401, check.Evaluate(runDirectory).Status);
        CheckTab.Evaluation late = Assert.Single(check.Evaluations);
        Assert.Equal(1, late.Generation);
        Assert.False(late.Authorized);
        Assert.False(check.CheckInProgress);
    }

    /// <summary>
    /// The reviews of 154A's merge, N6, after owner decision 157A: while a backend is up no settings save's restart can
    /// move the run root under a check, which holds it back; the run root read again once the extraction is over guards
    /// the starts that bring a backend up where there was none, which nothing holds back, since there is no backend to
    /// restart under the check. A save that chose another folder for runs with no backend up starts the backend with it
    /// at once; or the add-in's first start, after a save that chose one and whose restart failed, starts it with the
    /// settings saved. Either way that folder comes into force during the extraction, and the check, made under the run
    /// root loaded, is answered `RunRootChanged` once its model is read, and not handed on.
    /// </summary>
    [Theory]
    [InlineData("Model check", "the feature tree was read", "press Model check again", "a save")]
    [InlineData("Standards", "the document was read", "press Standards check again", "a save")]
    [InlineData("Model check", "the feature tree was read", "press Model check again", "the first start")]
    [InlineData("Standards", "the document was read", "press Standards check again", "the first start")]
    public void AStartThatBringsABackendUpDuringACheckIsStillAnsweredForTheRunRootItBringsIn(
        string tab, string during, string wayOn, string start)
    {
        using var world = new RestartWorld();
        world.Backend.Down = true;
        world.Open();
        using var check = new CheckTab(world, tab);
        string chosen = Path.Combine(world.Root, "FICT-chosen-runs");
        world.Dump.OnRun = () =>
        {
            if (start == "the first start")
            {
                world.Backend.EarlyRestartFailure = new BackendStartException("FICT the launcher has gone");
            }

            Dictionary<string, object?> save = Save(effort: "low");
            save["run_root"] = chosen;
            world.Receive("settings.save", "save", save);
            if (start == "the first start")
            {
                world.Reply("error", "save");
                world.Backend.EarlyRestartFailure = null;
                Assert.True(FirstStart(world));
            }
            else
            {
                world.Reply("settings.saved", "save");
            }
        };

        check.Press("c1");
        world.Dump.OnRun = null;

        Assert.DoesNotContain(world.Posted("status"), status => status.GetProperty("message").GetString() == CheckPromise);
        Assert.Equal(chosen, world.Host.RunRoot);
        JsonElement error = check.Reply("error", "c1");
        Assert.Equal("RunRootChanged", error.GetProperty("error_class").GetString());
        Assert.Equal(RunRootRule.ChangedRefusal(during, "nothing was checked", wayOn), error.GetProperty("message").GetString());
        Assert.Empty(check.Posted(check.ExtractedType));
        Assert.False(check.CheckInProgress);
    }

    /// <summary>A check asked for once the host is disposed - the add-in unloading, its backend with it - never begins (owner decision 157A).</summary>
    /// <summary>
    /// The race review of 157A: as the add-in unloads, the settings restart stops before the hosts whose work holds it
    /// back are disposed, so their holds going with them makes no restart in the moment before the review host goes,
    /// on a backend about to be stopped. Stopped, a restart that waits for a check is not made once the check is over,
    /// and nothing begins through the gate; stopping again, or disposing the host, does nothing more.
    /// </summary>
    [Fact]
    public void ARestartStoppedForTheUnloadIsNotMadeWhenTheWorkThatHeldItEnds()
    {
        int checking = 1;
        using var world = new RestartWorld();
        world.Checking("Model check", () => Volatile.Read(ref checking) == 1);
        world.Open();
        world.Receive("settings.save", "save", Save(effort: "low"));
        world.Reply("settings.saved", "save");

        world.Host.StopRestarting();
        Volatile.Write(ref checking, 0);

        Thread.Sleep(TimeSpan.FromTicks(world.Poll.Ticks * 20));
        Assert.Equal(0, world.Backend.RestartsAsked);
        int begun = 0;
        BackendRequestException? refusal = world.Host.BeginCheck(() => begun++);
        Assert.Equal("the review backend is stopping with the add-in.", refusal?.Message);
        Assert.Equal(0, begun);
        world.Host.StopRestarting();
        world.Host.Dispose();
        Assert.Equal(0, world.Backend.RestartsAsked);
    }

    /// <summary>
    /// ...and the add-in stops it so: in <c>DisconnectFromSW</c>, the review host's restart stops before the Model check,
    /// Remodel and Standards hosts are disposed - each lets the hold of its work go with it - and the review host is
    /// disposed after them, as before.
    /// </summary>
    [Fact]
    public void TheAddInStopsTheRestartBeforeTheHostsThatHoldItBackGo()
    {
        string unload = OtherTabsBackendRestartTests.Between(
            OtherTabsBackendRestartTests.AddInSource(), "public bool DisconnectFromSW() {", "_backend?.Dispose();");
        int stop = unload.IndexOf("_reviewHost?.StopRestarting();", StringComparison.Ordinal);
        Assert.True(stop >= 0, "the add-in does not stop the restart as it unloads");
        foreach (string host in new[] { "_modelCheckHost?.Dispose();", "_remodelHost?.Dispose();", "_standardsHost?.Dispose();" })
        {
            Assert.True(stop < unload.IndexOf(host, StringComparison.Ordinal), host + " is disposed before the restart stops");
        }

        Assert.True(
            unload.IndexOf("_standardsHost?.Dispose();", StringComparison.Ordinal)
                < unload.IndexOf("_reviewHost?.Dispose();", StringComparison.Ordinal),
            "the review host is disposed before the hosts that register their folders on it");
    }

    [Fact]
    public void ACheckOnceTheHostIsDisposedIsRefusedAndNeverBegins()
    {
        var world = new RestartWorld();
        try
        {
            world.Open();
            world.Host.Dispose();
            int begun = 0;

            BackendRequestException? refusal = world.Host.BeginCheck(() => begun++);

            Assert.NotNull(refusal);
            Assert.Equal("BackendUnavailable", refusal!.ErrorClass);
            Assert.Equal("the review backend is stopping with the add-in.", refusal.Message);
            Assert.False(refusal.Retryable);
            Assert.Equal(0, begun);
        }
        finally
        {
            world.Dispose();
        }
    }

    /// <summary>
    /// The add-in tells the review host whether a check is in progress on either check tab, read through each host's
    /// field per call: both are built after the review host's options are, and one that has gone holds nothing (owner
    /// decision 157A).
    /// </summary>
    [Fact]
    public void TheAddInTellsTheReviewHostWhetherACheckIsInProgress()
    {
        string options = OtherTabsBackendRestartTests.Between(
            OtherTabsBackendRestartTests.AddInSource(),
            "var reviewOptions = new ReviewHostOptions(",
            "_reviewHost = new ReviewHost(reviewOptions);");

        Assert.Contains("ModelCheckInProgress = () => _modelCheckHost?.CheckInProgress == true,", options, StringComparison.Ordinal);
        Assert.Contains("StandardsCheckInProgress = () => _standardsHost?.CheckInProgress == true,", options, StringComparison.Ordinal);
    }

    /// <summary>
    /// The add-in hands each check host the review host's gate, and its word on whether a restart stands before a
    /// check, read through the field per call - the review host keeps the restart, on another pump - and with no review
    /// host there is no settings restart to wait for, and the check begins (owner decision 157A).
    /// </summary>
    [Theory]
    [InlineData("_modelCheckHost = new ModelCheckHost(new ModelCheckHostOptions(", "StartModelCheckPump();")]
    [InlineData("_standardsHost = new StandardsHost(new StandardsHostOptions(", "StartStandardsPump();")]
    public void TheAddInHandsEachCheckHostTheReviewHostsGate(string start, string end)
    {
        string source = OtherTabsBackendRestartTests.AddInSource();
        string options = OtherTabsBackendRestartTests.Between(source, start, end);
        Assert.Contains("BeginCheck = BeginCheck,", options, StringComparison.Ordinal);
        Assert.Contains("RestartAhead = () => _reviewHost?.RestartAhead == true,", options, StringComparison.Ordinal);

        string gate = OtherTabsBackendRestartTests.Between(
            source, "private BackendRequestException? BeginCheck(Action begin) {", "private ");
        Assert.Contains("ReviewHost? host = _reviewHost;", gate, StringComparison.Ordinal);
        Assert.Contains("return host.BeginCheck(begin);", gate, StringComparison.Ordinal);
        Assert.Contains("begin(); return null;", gate, StringComparison.Ordinal);
    }

    /// <summary>
    /// The reviews of 157A: the add-in hands each check host the pane's queue behind its posts, so a run's minute starts
    /// once its reply has reached the page, and the review host's step that runs while no restart can begin or be made,
    /// so an evaluation held up past its minute is taken back while the backend its check began on is up. Each is read
    /// through its field per call - the pane is built before the hosts, the review host after - and with none, there is
    /// nothing to wait behind, or no settings restart, and the action or the step runs at once.
    /// </summary>
    [Theory]
    [InlineData("_modelCheckHost = new ModelCheckHost(new ModelCheckHostOptions(", "StartModelCheckPump();")]
    [InlineData("_standardsHost = new StandardsHost(new StandardsHostOptions(", "StartStandardsPump();")]
    public void TheAddInHandsEachCheckHostThePanesDeliveryAndTheRestartsLock(string start, string end)
    {
        string source = OtherTabsBackendRestartTests.AddInSource();
        string options = OtherTabsBackendRestartTests.Between(source, start, end);
        Assert.Contains("AfterPosts = AfterPagePosts,", options, StringComparison.Ordinal);
        Assert.Contains("WhileNoRestartRuns = WhileNoRestartRuns,", options, StringComparison.Ordinal);

        string delivery = OtherTabsBackendRestartTests.Between(source, "private void AfterPagePosts(Action action) {", "private ");
        Assert.Contains("TaskPaneControl? pane = _pane;", delivery, StringComparison.Ordinal);
        Assert.Contains("pane.AfterPosts(action); return;", delivery, StringComparison.Ordinal);
        Assert.Contains("action(); }", delivery, StringComparison.Ordinal);

        string step = OtherTabsBackendRestartTests.Between(source, "private bool WhileNoRestartRuns(Func<bool> step) {", "private ");
        Assert.Contains("ReviewHost? host = _reviewHost;", step, StringComparison.Ordinal);
        Assert.Contains("return host != null ? host.WhileNoRestartRuns(step) : step();", step, StringComparison.Ordinal);
    }

    /// <summary>
    /// The add-in hands the pane's proxy the check hosts' holds of an evaluation, each read through its field per call:
    /// the run folder an evaluation names is one check host's at most, and the other answers none (owner decision
    /// 157A). The pane hands the proxy its option, read per call: the check hosts are built after the pane.
    /// </summary>
    [Fact]
    public void TheAddInHandsThePanesProxyTheCheckHostsHoldsOfAnEvaluation()
    {
        string options = OtherTabsBackendRestartTests.Between(
            OtherTabsBackendRestartTests.AddInSource(), "_pane = new TaskPaneControl(new TaskPaneOptions(", "});");
        Assert.Contains(
            "HoldCheckEvaluation = runDirectory => _modelCheckHost?.HoldEvaluation(runDirectory) ?? _standardsHost?.HoldEvaluation(runDirectory),",
            options,
            StringComparison.Ordinal);

        string pane = System.Text.RegularExpressions.Regex.Replace(
            File.ReadAllText(Path.Combine(
                ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn", "TaskPaneControl.cs")),
            @"\s+",
            " ");
        string proxy = OtherTabsBackendRestartTests.Between(pane, "_proxy = new BackendProxyHandler(", ");");
        Assert.Contains("runDirectory => _options.HoldCheckEvaluation(runDirectory)", proxy, StringComparison.Ordinal);
    }

    // ---- the restart itself, with no host ------------------------------------------------------

    [Fact]
    public void TwoCallersOfOneWaitingRestartRestartTheBackendOnce()
    {
        int restarts = 0;
        using var entered = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        using var restart = NewRestart(
            () => DeferredRestart.Hold.None,
            () =>
            {
                Interlocked.Increment(ref restarts);
                entered.Set();
                release.Wait(TimeSpan.FromSeconds(10));
            });
        try
        {
            Assert.False(restart.Now(() => throw new TurnRunningException()));
            Assert.True(restart.Pending);

            var first = new Caller<DeferredRestart.Outcome>(() => restart.Apply(out _));
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the first caller never began the restart");
            var second = new Caller<DeferredRestart.Outcome>(() => restart.Apply(out _));
            Assert.False(second.Finishes(TimeSpan.FromMilliseconds(300)), "the second caller did not wait for the restart being made");

            release.Set();
            Assert.True(first.Finishes(TimeSpan.FromSeconds(10)), "the first caller never finished");
            Assert.True(second.Finishes(TimeSpan.FromSeconds(10)), "the second caller never finished");
            Assert.Equal(DeferredRestart.Outcome.Restarted, first.Result);
            Assert.Equal(DeferredRestart.Outcome.RestartedMeanwhile, second.Result);
            Assert.Equal(1, restarts);
            Assert.False(restart.Pending);
        }
        finally
        {
            release.Set();
        }
    }

    /// <summary>
    /// A caller that waited for a restart another was making is told what became of it: made -
    /// by another caller's Apply, or by a save - or failed, with that same failure. It never makes
    /// a second attempt of its own, and is never told nothing was waiting.
    /// </summary>
    [Theory]
    [InlineData("apply", false)]
    [InlineData("apply", true)]
    [InlineData("save", false)]
    [InlineData("save", true)]
    public void AWaiterIsToldWhatBecameOfTheRestartItWaitedFor(string maker, bool fails)
    {
        var failure = new BackendStartException("FICT the launcher has gone");
        int attempts = 0;
        using var entered = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        Action attempt = () =>
        {
            Interlocked.Increment(ref attempts);
            entered.Set();
            release.Wait(TimeSpan.FromSeconds(10));
            if (fails)
            {
                throw failure;
            }
        };
        using var restart = NewRestart(() => DeferredRestart.Hold.None, attempt);
        try
        {
            Assert.False(restart.Now(() => throw new TurnRunningException()));

            var making = new Caller<bool>(() =>
            {
                try
                {
                    if (maker == "apply")
                    {
                        restart.Apply(out _);
                    }
                    else
                    {
                        restart.Now(attempt);
                    }
                }
                catch (BackendStartException)
                {
                    // A save's own failure is thrown to the save.
                }

                return true;
            });
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the restart was never begun");
            var waiting = new Caller<(DeferredRestart.Outcome, Exception?)>(() =>
                (restart.Apply(out Exception? theirs), theirs));
            Assert.False(waiting.Finishes(TimeSpan.FromMilliseconds(300)), "the waiter did not wait for the restart being made");

            release.Set();
            Assert.True(making.Finishes(TimeSpan.FromSeconds(10)), "the restart never finished");
            Assert.True(waiting.Finishes(TimeSpan.FromSeconds(10)), "the waiter never got an answer");

            (DeferredRestart.Outcome outcome, Exception? told) = waiting.Result;
            Assert.Equal(fails ? DeferredRestart.Outcome.Failed : DeferredRestart.Outcome.RestartedMeanwhile, outcome);
            Assert.Same(fails ? failure : null, told);
            Assert.Equal(1, attempts);
            Assert.False(restart.Pending);
        }
        finally
        {
            release.Set();
        }
    }

    /// <summary>
    /// While something holds the restart back, Apply answers at once, naming what, and tries
    /// nothing: a turn, a remodel run, or a backend that does not answer.
    /// </summary>
    [Theory]
    [InlineData("Turn", "TurnRunning")]
    [InlineData("Work", "WorkInProgress")]
    [InlineData("NoAnswer", "NotAnswered")]
    public void WhileSomethingHoldsTheRestartApplyAnswersAtOnceSayingWhatAndTriesNothing(string hold, string expected)
    {
        int tried = 0;
        var held = (DeferredRestart.Hold)Enum.Parse(typeof(DeferredRestart.Hold), hold);
        using var restart = NewRestart(() => held, () => tried++);
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        Assert.Equal(
            (DeferredRestart.Outcome)Enum.Parse(typeof(DeferredRestart.Outcome), expected),
            restart.Apply(out Exception? failure));
        Assert.Null(failure);
        Assert.Equal(0, tried);
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// The host's look says no turn runs, and the backend's own check, made just after, finds
    /// one that started in between: nothing was changed, nothing is reported, and the restart
    /// still waits.
    /// </summary>
    [Fact]
    public void ARestartTheBackendRefusesForATurnThatStartedAfterTheLookStillWaits()
    {
        int reported = 0;
        using var restart = NewRestart(
            () => DeferredRestart.Hold.None,
            () => throw new TurnRunningException(),
            restarted: () => reported++,
            failed: _ => reported++);
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        Assert.Equal(DeferredRestart.Outcome.TurnRunning, restart.Apply(out Exception? failure));
        Assert.Null(failure);
        Assert.True(restart.Pending);
        Assert.Equal(0, reported);
    }

    /// <summary>
    /// A look at the turns that cannot be made does not make <see cref="DeferredRestart.Apply"/>
    /// throw - it runs on the watcher's thread and on a proxied request's - and does not decide
    /// anything either: the backend's own check, made before it stops anything, does.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ALookAtTheTurnsThatCannotBeMadeLeavesTheDecisionToTheBackendsOwnCheck(bool backendSeesATurn)
    {
        int restarted = 0;
        using var restart = NewRestart(
            () => throw new InvalidOperationException("FICT the look could not be made"),
            () =>
            {
                if (backendSeesATurn)
                {
                    throw new TurnRunningException();
                }

                restarted++;
            });
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        DeferredRestart.Outcome outcome = restart.Apply(out Exception? failure);

        Assert.Null(failure);
        Assert.Equal(backendSeesATurn ? DeferredRestart.Outcome.TurnRunning : DeferredRestart.Outcome.Restarted, outcome);
        Assert.Equal(backendSeesATurn ? 0 : 1, restarted);
        Assert.Equal(backendSeesATurn, restart.Pending);
    }

    [Fact]
    public void AnImmediateRestartThatFailsIsThrownAsBeforeAndLeavesNothingWaiting()
    {
        using var restart = NewRestart(() => DeferredRestart.Hold.None, () => { });
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        Assert.True(restart.Pending);

        var failure = new BackendStartException("FICT the backend would not start");
        Assert.Same(failure, Assert.Throws<BackendStartException>(() => restart.Now(() => throw failure)));
        Assert.False(restart.Pending);
    }

    /// <summary>
    /// The watcher stops looking after <see cref="DeferredRestart.UnansweredLooks"/> looks in a
    /// row the backend leaves unanswered - not one more, not one fewer - says so once, tries no
    /// restart, and ends. The restart still waits: a caller's look that is still unanswered is
    /// refused, and one the backend answers with nothing holding the restart back makes it.
    /// </summary>
    [Fact]
    public void TheWatcherStopsLookingAfterABoundedRunOfUnansweredLooksAndTheRestartStillWaits()
    {
        int looks = 0;
        int looksWhenTold = -1;
        int told = 0;
        int tried = 0;
        var hold = DeferredRestart.Hold.NoAnswer;
        using var restart = NewRestart(
            () =>
            {
                Interlocked.Increment(ref looks);
                return hold;
            },
            () => tried++,
            notAnswered: () =>
            {
                looksWhenTold = Volatile.Read(ref looks);
                Interlocked.Increment(ref told);
            },
            poll: TimeSpan.FromMilliseconds(5));
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        Eventually(() => Volatile.Read(ref told) == 1, "the watcher saying it stopped looking");
        Thread.Sleep(100);

        Assert.Equal(DeferredRestart.UnansweredLooks, looksWhenTold);
        Assert.Equal(DeferredRestart.UnansweredLooks, Volatile.Read(ref looks));
        Assert.Equal(1, Volatile.Read(ref told));
        Assert.Equal(0, tried);
        Assert.True(restart.Pending);

        Assert.Equal(DeferredRestart.Outcome.NotAnswered, restart.Apply(out _));
        Assert.True(restart.Pending);

        hold = DeferredRestart.Hold.None;
        Assert.Equal(DeferredRestart.Outcome.Restarted, restart.Apply(out _));
        Assert.Equal(1, tried);
        Assert.False(restart.Pending);
        Assert.Equal(1, Volatile.Read(ref told));
    }

    /// <summary>
    /// A save refused again while the watcher is deciding to stop - inside the restart's own lock,
    /// where the decision is made - is a newer save: the watcher does not stop on the strength of
    /// looks made for the older one, and says nothing yet; it counts the newer save's looks
    /// afresh, and stops after the full run of them.
    /// </summary>
    [Fact]
    public void ASaveRefusedAgainWhileTheWatcherDecidesToStopIsWatchedAfresh()
    {
        int looks = 0;
        int looksWhenTold = -1;
        using var saving = new ManualResetEventSlim(false);
        using var lookMade = new ManualResetEventSlim(false);
        using var refuse = new ManualResetEventSlim(false);
        DeferredRestart? restart = null;
        restart = NewRestart(
            () =>
            {
                if (Interlocked.Increment(ref looks) == DeferredRestart.UnansweredLooks)
                {
                    // The last look of the run returns only once the save below holds the
                    // restart's lock, so the watcher's decision to stop has to wait for it.
                    lookMade.Set();
                    saving.Wait(TimeSpan.FromSeconds(10));
                }

                return DeferredRestart.Hold.NoAnswer;
            },
            () => { },
            notAnswered: () => looksWhenTold = Volatile.Read(ref looks),
            poll: TimeSpan.FromMilliseconds(5));
        using (restart)
        {
            Assert.False(restart.Now(() => throw new TurnRunningException()));
            Assert.True(lookMade.Wait(TimeSpan.FromSeconds(10)), "the watcher never made its last look");

            var save = new Caller<bool>(() => restart.Now(() =>
            {
                saving.Set();
                refuse.Wait(TimeSpan.FromSeconds(10));
                throw new TurnRunningException();
            }));
            Assert.True(saving.Wait(TimeSpan.FromSeconds(10)), "the save never took the restart's lock");

            // The watcher now wants the lock the save holds, to decide whether to stop.
            Thread.Sleep(200);
            refuse.Set();
            Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
            Assert.False(save.Result);

            Eventually(() => Volatile.Read(ref looksWhenTold) > 0, "the watcher stopping for the newer save");
            Assert.Equal(DeferredRestart.UnansweredLooks * 2, looksWhenTold);
            Assert.True(restart.Pending);
        }
    }

    /// <summary>
    /// The watcher says it stopped looking while it holds the restart's own lock, so a save made
    /// meanwhile - refused under that lock, its promise posted after - comes after it: the page
    /// never shows "not answering" above a newer save's promise.
    /// </summary>
    [Fact]
    public void TheWatchersReportIsMadeUnderTheRestartsLockSoALaterSaveComesAfterIt()
    {
        var order = new List<string>();
        using var reporting = new ManualResetEventSlim(false);
        using var reported = new ManualResetEventSlim(false);
        using var restart = NewRestart(
            () => DeferredRestart.Hold.NoAnswer,
            () => { },
            notAnswered: () =>
            {
                reporting.Set();
                reported.Wait(TimeSpan.FromSeconds(10));
                lock (order)
                {
                    order.Add("not answering");
                }
            },
            poll: TimeSpan.FromMilliseconds(5));
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        Assert.True(reporting.Wait(TimeSpan.FromSeconds(10)), "the watcher never said it stopped looking");

        var save = new Caller<bool>(() =>
        {
            bool restarted = restart.Now(() => throw new TurnRunningException());
            lock (order)
            {
                order.Add("promise");
            }

            return restarted;
        });
        Assert.False(save.Finishes(TimeSpan.FromMilliseconds(500)), "the save went ahead while the watcher was still saying it stopped");

        reported.Set();
        Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
        Assert.False(save.Result);
        lock (order)
        {
            // The newer save's own watcher may say so too, later; what matters is what came first.
            Assert.Equal(new[] { "not answering", "promise" }, order.Take(2));
        }
    }

    /// <summary>
    /// The run of unanswered looks must be unbroken: one look the backend answers - a turn still
    /// running - starts the count again, so a backend that answers now and then is waited for.
    /// </summary>
    [Fact]
    public void ALookTheBackendAnswersStartsTheCountAgain()
    {
        int looks = 0;
        int told = 0;
        using var restart = NewRestart(
            () =>
            {
                // Two unanswered, one answered, and again: never the bound in a row.
                int look = Interlocked.Increment(ref looks);
                return look % DeferredRestart.UnansweredLooks == 0 ? DeferredRestart.Hold.Turn : DeferredRestart.Hold.NoAnswer;
            },
            () => { },
            notAnswered: () => Interlocked.Increment(ref told),
            poll: TimeSpan.FromMilliseconds(5));
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        Eventually(() => Volatile.Read(ref looks) >= DeferredRestart.UnansweredLooks * 6, "six runs of looks");

        Assert.Equal(0, Volatile.Read(ref told));
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// A save refused again during a run of unanswered looks is a newer save, and its restart is
    /// waited for from then on: the count starts again with it rather than ending that restart
    /// on the strength of looks made before it was asked for.
    /// </summary>
    [Fact]
    public void ARestartRefusedAgainDuringARunOfUnansweredLooksStartsTheCountAgain()
    {
        int looks = 0;
        int looksWhenTold = -1;
        bool? secondSaveRestarted = null;
        DeferredRestart? restart = null;
        restart = NewRestart(
            () =>
            {
                if (Interlocked.Increment(ref looks) == 2)
                {
                    // A second save, refused by the backend's own check while this look is made.
                    secondSaveRestarted = restart!.Now(() => throw new TurnRunningException());
                }

                return DeferredRestart.Hold.NoAnswer;
            },
            () => { },
            notAnswered: () => looksWhenTold = Volatile.Read(ref looks),
            poll: TimeSpan.FromMilliseconds(5));
        using (restart)
        {
            Assert.False(restart.Now(() => throw new TurnRunningException()));

            Eventually(() => Volatile.Read(ref looksWhenTold) > 0, "the watcher saying it stopped waiting");

            // Look 2 belongs to the second save's run: told after it and two more, not after look 3.
            Assert.False(secondSaveRestarted);
            Assert.Equal(DeferredRestart.UnansweredLooks + 1, looksWhenTold);
        }
    }

    /// <summary>
    /// A poll the watcher could not wait out is refused when the host is built, not met later on
    /// the watcher's thread, inside SOLIDWORKS: none, a negative one, one under the millisecond a
    /// wait can count - on which the watcher would spin - and one longer than a wait can take.
    /// </summary>
    [Theory]
    [InlineData(0L)]
    [InlineData(-TimeSpan.TicksPerMillisecond)]
    [InlineData(1L)]
    [InlineData(TimeSpan.TicksPerMillisecond - 1)]
    [InlineData((int.MaxValue + 1L) * TimeSpan.TicksPerMillisecond)]
    public void APollTheWatcherCouldNotWaitOutIsRefusedAtOnce(long ticks)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => NewRestart(
            () => DeferredRestart.Hold.None, () => { }, poll: TimeSpan.FromTicks(ticks)));
    }

    /// <summary>The shortest poll a wait can count, a millisecond, is taken.</summary>
    [Fact]
    public void AMillisecondPollIsTaken()
    {
        using var restart = NewRestart(() => DeferredRestart.Hold.None, () => { }, poll: TimeSpan.FromMilliseconds(1));
        Assert.False(restart.Pending);
    }

    [Fact]
    public void DisposeWakesTheWatcherAtOnceAndNothingRestartsAfterIt()
    {
        int tried = 0;
        var restart = NewRestart(() => DeferredRestart.Hold.None, () => tried++);
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        Assert.True(restart.Pending);

        // The watcher is asleep for a ten-minute poll; disposing wakes it rather than outwaiting it.
        // Left asleep, it would hold the join for its whole two-second bound; woken, it is gone in
        // milliseconds, and the bound below leaves a loaded test run room to schedule it.
        var clock = Stopwatch.StartNew();
        restart.Dispose();
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(1.5), "disposing waited " + clock.Elapsed);

        Assert.Equal(DeferredRestart.Outcome.Stopped, restart.Apply(out _));
        Assert.False(restart.Pending);
        Assert.Equal(0, tried);
        restart.Dispose();
    }

    /// <summary>
    /// Owner decision 145A: a save's restart never ends a remodel run. The run is read under the
    /// restart's own lock before anything is asked; the restart then waits, and says it is the run
    /// that holds it back - a turn the backend's own check finds is said as before.
    /// </summary>
    [Theory]
    [InlineData(true, "Work")]
    [InlineData(false, "Turn")]
    public void ASavesRestartWaitsForARemodelRunOrATurnAndSaysWhich(bool remodelling, string expected)
    {
        int tried = 0;
        using var restart = NewRestart(() => DeferredRestart.Hold.None, () => { }, busy: () => remodelling);

        bool restarted = restart.Now(
            () =>
            {
                tried++;
                throw new TurnRunningException();
            },
            out DeferredRestart.Hold heldBy);

        Assert.False(restarted);
        Assert.Equal((DeferredRestart.Hold)Enum.Parse(typeof(DeferredRestart.Hold), expected), heldBy);
        Assert.Equal(remodelling ? 0 : 1, tried);
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// A look that answers that nothing holds the restart back while a remodel run is in progress -
    /// the review host's answers so, without reading the run, when there is no backend process at
    /// all, and a look that cannot be made counts as such an answer - never leads to a restart that
    /// ends the run: the run is read again under the restart's own lock, and the restart still
    /// waits. (Renamed on review: it was said to guard a run begun after the look, which the gate
    /// rules out, since a run begins only once no restart waits.)
    /// </summary>
    [Fact]
    public void ARestartNeverEndsARemodelRunItsLookDidNotRead()
    {
        int busy = 0;
        int tried = 0;
        using var restart = NewRestart(
            () =>
            {
                // A run is in progress, and this look answers without reading it.
                Volatile.Write(ref busy, 1);
                return DeferredRestart.Hold.None;
            },
            () => tried++,
            busy: () => Volatile.Read(ref busy) == 1);
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, restart.Apply(out Exception? failure));
        Assert.Null(failure);
        Assert.Equal(0, tried);
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// A restart stands before new work while one waits, until it is made, and while a save's is
    /// being made at once - which never waits - and not once it is made, nor once the owner is
    /// disposed (owner decision 145A, found on review): what the Remodel tab reads to say a press
    /// makes the restart first. The gate itself decides; this is only what the page is told.
    /// </summary>
    [Fact]
    public void ARestartIsAheadWhileOneWaitsOrIsBeingMade()
    {
        using var entered = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        Action blocking = () =>
        {
            entered.Set();
            release.Wait(TimeSpan.FromSeconds(10));
        };
        using var restart = NewRestart(() => DeferredRestart.Hold.None, blocking);
        Assert.False(restart.Ahead);

        // A save's restart, being made at once.
        var save = new Caller<bool>(() => restart.Now(blocking));
        Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the save's restart never began");
        Assert.True(restart.Ahead);
        release.Set();
        Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save's restart never ended");
        Assert.True(save.Result);
        Assert.False(restart.Ahead);

        // One that waits, and then is made.
        entered.Reset();
        release.Reset();
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        Assert.True(restart.Ahead);
        var made = new Caller<DeferredRestart.Outcome>(() => restart.Apply(out _));
        Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the waiting restart was never made");
        Assert.True(restart.Ahead);
        release.Set();
        Assert.True(made.Finishes(TimeSpan.FromSeconds(10)), "the waiting restart never ended");
        Assert.Equal(DeferredRestart.Outcome.Restarted, made.Result);
        Assert.False(restart.Ahead);

        // Once the owner is disposed none stands before anything - the gate answers that the add-in
        // is unloading - not even a save's restart still under way.
        entered.Reset();
        release.Reset();
        var underWay = new Caller<bool>(() => restart.Now(blocking));
        Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the last save's restart never began");
        Assert.True(restart.Ahead);
        restart.Dispose();
        Assert.False(restart.Ahead);
        release.Set();
        Assert.True(underWay.Finishes(TimeSpan.FromSeconds(10)), "the last save's restart never ended");
    }

    /// <summary>
    /// Through the host: a settings restart stands before new work while it waits for a turn, and
    /// not once it is made (owner decision 145A, found on review). The add-in hands this to the
    /// Remodel host, which says so before a plan or a Start.
    /// </summary>
    [Fact]
    public void TheReviewHostSaysARestartIsAheadWhileOneWaits()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        Assert.False(world.Host.RestartAhead);

        SaveAsATurnStarts(world, "save", Save(effort: "low"));
        Assert.True(world.Host.RestartAhead);

        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Backend.Restarts.Length == 1, "the restart once the turn ends");
        Eventually(() => !world.Host.RestartAhead, "no restart ahead once it is made");
    }

    /// <summary>
    /// Not knowing whether a remodel run is in progress is not knowing that none is: a reading of
    /// the run that throws is read as one in progress. A save's restart waits for it and says so, a
    /// restart that waits is not made under it, and a run's step does not begin while it waits
    /// (owner decision 145A; the rule was written down, and found unpinned on review).
    /// </summary>
    [Fact]
    public void ARunReadingThatThrowsIsReadAsARunInProgress()
    {
        int restarted = 0;
        using var restart = NewRestart(
            () => DeferredRestart.Hold.None,
            () => restarted++,
            busy: () => throw new InvalidOperationException("FICT the Remodel host cannot be asked"));

        Assert.False(restart.Now(() => restarted++, out DeferredRestart.Hold heldBy));
        Assert.Equal(DeferredRestart.Hold.Work, heldBy);
        Assert.True(restart.Pending);

        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, restart.Apply(out Exception? failure));
        Assert.Null(failure);

        int began = 0;
        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, restart.Begin(() => began++, out failure));
        Assert.Null(failure);
        Assert.Equal(0, began);
        Assert.Equal(0, restarted);
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// Begin runs a run's step under the restart's own lock: a save asking for its restart while the
    /// step runs waits for it, and then finds the run in progress and waits for it in turn - so a
    /// run and a restart never overlap.
    /// </summary>
    [Fact]
    public void BeginRunsItsStepUnderTheRestartsLockSoNoRestartOverlapsTheRun()
    {
        int busy = 0;
        int tried = 0;
        using var entered = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        using var restart = NewRestart(() => DeferredRestart.Hold.None, () => { }, busy: () => Volatile.Read(ref busy) == 1);
        try
        {
            var run = new Caller<DeferredRestart.Outcome>(() => restart.Begin(
                () =>
                {
                    entered.Set();
                    release.Wait(TimeSpan.FromSeconds(10));
                    Volatile.Write(ref busy, 1);
                },
                out _));
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the run's step never ran");

            var save = new Caller<(bool, DeferredRestart.Hold)>(() =>
                (restart.Now(() => Interlocked.Increment(ref tried), out DeferredRestart.Hold heldBy), heldBy));
            Assert.False(save.Finishes(TimeSpan.FromMilliseconds(300)), "the save's restart did not wait for the run's step");

            release.Set();
            Assert.True(run.Finishes(TimeSpan.FromSeconds(10)), "the run never began");
            Assert.Equal(DeferredRestart.Outcome.NotPending, run.Result);
            Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
            Assert.False(save.Result.Item1);
            Assert.Equal(DeferredRestart.Hold.Work, save.Result.Item2);
            Assert.Equal(0, Volatile.Read(ref tried));
        }
        finally
        {
            release.Set();
        }
    }

    /// <summary>
    /// Begin makes a waiting restart first when nothing holds it back, as a new review does, and
    /// runs its step after it; while something holds it back it answers what, runs nothing and
    /// leaves the restart waiting.
    /// </summary>
    [Theory]
    [InlineData("None", "Restarted")]
    [InlineData("Turn", "TurnRunning")]
    [InlineData("Work", "WorkInProgress")]
    [InlineData("NoAnswer", "NotAnswered")]
    public void BeginMakesAWaitingRestartFirstOrAnswersWhatHoldsItBack(string hold, string expected)
    {
        var order = new List<string>();
        var held = (DeferredRestart.Hold)Enum.Parse(typeof(DeferredRestart.Hold), hold);
        using var restart = NewRestart(() => held, () => order.Add("restart"));
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        DeferredRestart.Outcome outcome = restart.Begin(() => order.Add("begin"), out Exception? failure);

        Assert.Equal((DeferredRestart.Outcome)Enum.Parse(typeof(DeferredRestart.Outcome), expected), outcome);
        Assert.Null(failure);
        Assert.Equal(hold == "None" ? new[] { "restart", "begin" } : new string[0], order);
        Assert.Equal(hold != "None", restart.Pending);
    }

    /// <summary>
    /// Begin waits for a restart being made - one that waited, made by another caller's look, and a
    /// save's made at once, which is never waiting and which nothing waited for before 145A - and
    /// is told what became of it: made, and the step runs after it; or failed, and the step never
    /// runs. It makes no attempt of its own.
    /// </summary>
    [Theory]
    [InlineData("apply", false)]
    [InlineData("apply", true)]
    [InlineData("save", false)]
    [InlineData("save", true)]
    public void BeginWaitsForARestartBeingMadeAndIsToldWhatBecameOfIt(string maker, bool fails)
    {
        var failure = new BackendStartException("FICT the launcher has gone");
        int attempts = 0;
        int begun = 0;
        using var entered = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        Action attempt = () =>
        {
            Interlocked.Increment(ref attempts);
            entered.Set();
            release.Wait(TimeSpan.FromSeconds(10));
            if (fails)
            {
                throw failure;
            }
        };
        using var restart = NewRestart(() => DeferredRestart.Hold.None, attempt);
        try
        {
            if (maker == "apply")
            {
                Assert.False(restart.Now(() => throw new TurnRunningException()));
            }

            var making = new Caller<bool>(() =>
            {
                try
                {
                    if (maker == "apply")
                    {
                        restart.Apply(out _);
                    }
                    else
                    {
                        restart.Now(attempt);
                    }
                }
                catch (BackendStartException)
                {
                    // A save's own failure is thrown to the save.
                }

                return true;
            });
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the restart was never begun");
            var run = new Caller<(DeferredRestart.Outcome, Exception?)>(() =>
                (restart.Begin(() => Interlocked.Increment(ref begun), out Exception? theirs), theirs));
            Assert.False(run.Finishes(TimeSpan.FromMilliseconds(300)), "the run did not wait for the restart being made");

            release.Set();
            Assert.True(making.Finishes(TimeSpan.FromSeconds(10)), "the restart never finished");
            Assert.True(run.Finishes(TimeSpan.FromSeconds(10)), "the run never got an answer");

            (DeferredRestart.Outcome outcome, Exception? told) = run.Result;
            Assert.Equal(fails ? DeferredRestart.Outcome.Failed : DeferredRestart.Outcome.RestartedMeanwhile, outcome);
            Assert.Same(fails ? failure : null, told);
            Assert.Equal(fails ? 0 : 1, Volatile.Read(ref begun));
            Assert.Equal(1, Volatile.Read(ref attempts));
        }
        finally
        {
            release.Set();
        }
    }

    /// <summary>
    /// A newer save's restart that starts to wait while Begin waits for the lock - the backend's own
    /// check found a turn - is looked at afresh: the turn holds it back, the run is refused saying
    /// so, and its step never runs.
    /// </summary>
    [Fact]
    public void BeginLooksAgainAtARestartThatStartedToWaitWhileItWaitedForTheLock()
    {
        int hold = (int)DeferredRestart.Hold.None;
        int begun = 0;
        using var entered = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        using var restart = NewRestart(() => (DeferredRestart.Hold)Volatile.Read(ref hold), () => { });
        try
        {
            var save = new Caller<bool>(() => restart.Now(() =>
            {
                entered.Set();
                release.Wait(TimeSpan.FromSeconds(10));
                throw new TurnRunningException();
            }));
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the save never began its restart");
            var run = new Caller<DeferredRestart.Outcome>(() => restart.Begin(() => Interlocked.Increment(ref begun), out _));
            Assert.False(run.Finishes(TimeSpan.FromMilliseconds(300)), "the run did not wait for the save's restart");

            Volatile.Write(ref hold, (int)DeferredRestart.Hold.Turn);
            release.Set();
            Assert.True(save.Finishes(TimeSpan.FromSeconds(10)), "the save never finished");
            Assert.True(run.Finishes(TimeSpan.FromSeconds(10)), "the run never got an answer");

            Assert.False(save.Result);
            Assert.Equal(DeferredRestart.Outcome.TurnRunning, run.Result);
            Assert.Equal(0, Volatile.Read(ref begun));
            Assert.True(restart.Pending);
        }
        finally
        {
            release.Set();
        }
    }

    /// <summary>Once disposed, Begin runs nothing and says so.</summary>
    [Fact]
    public void BeginOnceDisposedRunsNothing()
    {
        int begun = 0;
        var restart = NewRestart(() => DeferredRestart.Hold.None, () => { });
        restart.Dispose();

        Assert.Equal(DeferredRestart.Outcome.Stopped, restart.Begin(() => begun++, out Exception? failure));
        Assert.Null(failure);
        Assert.Equal(0, begun);
    }

    // ---- the work reading says which work holds the restart back (owner decision 157A) ---------

    /// <summary>
    /// The work the restart would end, read as one reading: a remodel run, a Model check, a Standards check,
    /// and any of them together.
    /// </summary>
    public static IEnumerable<object[]> WorkInProgress() => new[]
    {
        new object[] { "RemodelRun" },
        new object[] { "ModelCheck" },
        new object[] { "StandardsCheck" },
        new object[] { "ModelCheck, StandardsCheck" },
        new object[] { "RemodelRun, ModelCheck" },
        new object[] { "RemodelRun, ModelCheck, StandardsCheck" },
    };

    /// <summary>The work named as the theories name it, by its flags' names.</summary>
    private static DeferredRestart.Work WorkNamed(string names) =>
        (DeferredRestart.Work)Enum.Parse(typeof(DeferredRestart.Work), names);

    /// <summary>
    /// Owner decision 157A: a save's restart, deferred for work in progress, says which work it found under the
    /// restart's own lock - the reading it deferred by, whole - so the save names what the restart waits for; and
    /// it tries nothing, asking the backend nothing.
    /// </summary>
    [Theory]
    [MemberData(nameof(WorkInProgress))]
    public void ASavesRestartSaysWhichWorkItWaitsFor(string named)
    {
        DeferredRestart.Work work = WorkNamed(named);
        int tried = 0;
        int looked = 0;
        using var restart = NewRestart(
            () =>
            {
                looked++;
                return DeferredRestart.Hold.None;
            },
            () => tried++,
            work: () => work);

        bool restarted = restart.Now(() => tried++, out DeferredRestart.Hold heldBy, out DeferredRestart.Work busyWith);

        Assert.False(restarted);
        Assert.Equal(DeferredRestart.Hold.Work, heldBy);
        Assert.Equal(work, busyWith);
        Assert.Equal(0, tried);
        Assert.Equal(0, looked);
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// ...and a restart that waits, asked for by a review, a turn call or the watcher (<c>Apply</c>), or by work
    /// that would begin (<c>Begin</c>), says which work holds it back, and does nothing: the step does not run and
    /// the restart still waits.
    /// </summary>
    [Theory]
    [MemberData(nameof(WorkInProgress))]
    public void ARestartThatWaitsSaysWhichWorkHoldsItBack(string named)
    {
        DeferredRestart.Work work = WorkNamed(named);
        DeferredRestart.Work reading = DeferredRestart.Work.None;
        int tried = 0;
        using var restart = NewRestart(() => DeferredRestart.Hold.None, () => tried++, work: () => reading);
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        reading = work;

        DeferredRestart.Outcome applied = restart.Apply(out Exception? failure, out DeferredRestart.Work appliedWith);
        int begun = 0;
        DeferredRestart.Outcome began = restart.Begin(() => begun++, out Exception? beginFailure, out DeferredRestart.Work beganWith);

        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, applied);
        Assert.Equal(work, appliedWith);
        Assert.Null(failure);
        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, began);
        Assert.Equal(work, beganWith);
        Assert.Null(beginFailure);
        Assert.Equal(0, begun);
        Assert.Equal(0, tried);
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// Owner decision 157A: work the restart would end is known without asking the backend, so a restart that
    /// waits reads it before its look - before any round trip to ask about the turns - as 145A's look read a remodel
    /// run before the turns; and while work holds the restart back the look is never asked, so the watcher counts no
    /// backend that does not answer meanwhile.
    /// </summary>
    [Fact]
    public void WorkIsReadBeforeTheLookAndWhileItHoldsTheRestartNoTurnIsAskedAbout()
    {
        DeferredRestart.Work reading = DeferredRestart.Work.None;
        int looked = 0;
        using var restart = NewRestart(
            () =>
            {
                looked++;
                return DeferredRestart.Hold.NoAnswer;
            },
            () => { },
            work: () => reading);
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        reading = DeferredRestart.Work.ModelCheck;

        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, restart.Apply(out _, out _));
        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, restart.Begin(() => { }, out _, out _));

        Assert.Equal(0, looked);
        reading = DeferredRestart.Work.None;
        Assert.Equal(DeferredRestart.Outcome.NotAnswered, restart.Apply(out _, out DeferredRestart.Work busyWith));
        Assert.Equal(1, looked);
        Assert.Equal(DeferredRestart.Work.None, busyWith);
    }

    /// <summary>
    /// Work the reading before the look did not find, and the reading under the restart's own lock did - work that
    /// began while the look was out, which only a look like this case's can make - holds the restart back and is named
    /// by that second reading: which work the restart waits for is always the reading that decided it (owner decision
    /// 157A).
    /// </summary>
    [Fact]
    public void WorkFoundOnlyUnderTheLockIsNamedByThatReading()
    {
        DeferredRestart.Work reading = DeferredRestart.Work.None;
        int tried = 0;
        using var restart = NewRestart(
            () =>
            {
                reading = DeferredRestart.Work.StandardsCheck;
                return DeferredRestart.Hold.None;
            },
            () => tried++,
            work: () => reading);
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, restart.Apply(out _, out DeferredRestart.Work busyWith));

        Assert.Equal(DeferredRestart.Work.StandardsCheck, busyWith);
        Assert.Equal(0, tried);
        Assert.True(restart.Pending);
    }

    /// <summary>
    /// A look that names work the reading did not see, and a reading that throws, are work of a kind not known
    /// (<see cref="DeferredRestart.Work.Unknown"/>): not knowing what work is in progress is not knowing that none
    /// is, as 145A read a reading that throws.
    /// </summary>
    [Theory]
    [InlineData("a look that names work")]
    [InlineData("a reading that throws")]
    public void WorkThatCannotBeReadIsUnknownWorkInProgress(string how)
    {
        bool throws = false;
        using var restart = NewRestart(
            () => how == "a look that names work" ? DeferredRestart.Hold.Work : DeferredRestart.Hold.None,
            () => { },
            work: () => throws ? throw new InvalidOperationException("FICT the hosts cannot be asked") : DeferredRestart.Work.None);
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        throws = how == "a reading that throws";

        Assert.Equal(DeferredRestart.Outcome.WorkInProgress, restart.Apply(out _, out DeferredRestart.Work busyWith));
        Assert.Equal(DeferredRestart.Work.Unknown, busyWith);
        if (throws)
        {
            Assert.False(restart.Now(() => { }, out DeferredRestart.Hold heldBy, out DeferredRestart.Work savedWith));
            Assert.Equal(DeferredRestart.Hold.Work, heldBy);
            Assert.Equal(DeferredRestart.Work.Unknown, savedWith);
        }
    }

    /// <summary>
    /// Owner decision 157A: with no restart waiting, work begins at once whatever else is in progress - two checks,
    /// a check and a remodel run - and nothing is read or asked: work holds back only a restart, never other work.
    /// </summary>
    [Theory]
    [MemberData(nameof(WorkInProgress))]
    public void WithNoRestartWaitingWorkBeginsBesideWorkInProgress(string named)
    {
        DeferredRestart.Work work = WorkNamed(named);
        int read = 0;
        int looked = 0;
        int begun = 0;
        using var restart = NewRestart(
            () =>
            {
                looked++;
                return DeferredRestart.Hold.None;
            },
            () => { },
            work: () =>
            {
                read++;
                return work;
            });

        Assert.Equal(
            DeferredRestart.Outcome.NotPending,
            restart.Begin(() => begun++, out Exception? failure, out DeferredRestart.Work busyWith));

        Assert.Equal(1, begun);
        Assert.Null(failure);
        Assert.Equal(DeferredRestart.Work.None, busyWith);
        Assert.Equal(0, read);
        Assert.Equal(0, looked);
    }

    /// <summary>
    /// A restart with the callbacks a test does not care about doing nothing, no remodel run in
    /// progress unless given a reading of one (owner decision 145A), and a ten-minute poll unless
    /// given one. A reading of a remodel run - true while one is in progress, as 145A's cases read it - is
    /// the work reading's <see cref="DeferredRestart.Work.RemodelRun"/> since owner decision 157A, which made
    /// the reading say which work; <paramref name="work"/> gives that reading whole.
    /// </summary>
    private static DeferredRestart NewRestart(
        Func<DeferredRestart.Hold> heldBack,
        Action restart,
        Action? restarted = null,
        Action<Exception>? failed = null,
        Action? notAnswered = null,
        TimeSpan? poll = null,
        Func<bool>? busy = null,
        Func<DeferredRestart.Work>? work = null) =>
        new DeferredRestart(
            heldBack,
            work ?? (busy == null
                ? () => DeferredRestart.Work.None
                : () => busy() ? DeferredRestart.Work.RemodelRun : DeferredRestart.Work.None),
            restart,
            restarted ?? (() => { }),
            failed ?? (_ => { }),
            notAnswered ?? (() => { }),
            poll ?? TimeSpan.FromMinutes(10));

    // ---- helpers --------------------------------------------------------------------------------

    /// <summary>
    /// A save during which a turn starts on <paramref name="chatId"/>: after the save's own check
    /// and before its restart, inside the model-list round trip between them - where a follow-up
    /// or a Send the page posts to the backend directly lands. The backend's own check then
    /// refuses the restart.
    /// </summary>
    private static void SaveAsATurnStarts(RestartWorld world, string id, object payload, string chatId = "chat-1")
    {
        world.Backend.DuringModelList = () => world.Backend.StartTurn(chatId);
        try
        {
            world.Receive("settings.save", id, payload);
        }
        finally
        {
            world.Backend.DuringModelList = null;
        }
    }

    private static Dictionary<string, object?> Save(
        string provider = "openai",
        string model = "gpt-5.6",
        string effort = "high",
        string? apiKey = null,
        string? baseUrl = null,
        object? geminiEnterprise = null)
    {
        return new Dictionary<string, object?>
        {
            { "provider", provider },
            { "model", model },
            { "effort", effort },
            { "api_key", apiKey },
            { "base_url", baseUrl },
            { "gemini_enterprise", geminiEnterprise },
        };
    }

    /// <summary>What the real client builds for a start with these settings and this key.</summary>
    private static BackendStartOptions RealStartOptions(RestartWorld world, UserSettings settings, ResolvedApiKey key)
    {
        using (var supervisor = new BackendSupervisor(() => false))
        using (var client = new BackendClient(supervisor, Path.Combine(world.Root, "logs"), null))
        {
            return client.StartOptions(settings, key);
        }
    }

    /// <summary>Waits for <paramref name="condition"/>, which another thread makes true; bounded.</summary>
    private static void Eventually(Func<bool> condition, string what)
    {
        var clock = Stopwatch.StartNew();
        while (!condition())
        {
            if (clock.Elapsed > TimeSpan.FromSeconds(15))
            {
                throw new XunitException("timed out waiting for " + what);
            }

            Thread.Sleep(5);
        }
    }

    /// <summary>
    /// Lets the host ask whether a turn runs at least <paramref name="questions"/> more times, so
    /// that "nothing happened" is asserted after the watcher looked rather than before it could.
    /// </summary>
    private static void Polls(FakeBackend backend, int questions)
    {
        int from = backend.Questions;
        Eventually(() => backend.Questions >= from + questions, questions + " more questions about the turn");
    }

    /// <summary>
    /// One call made on a thread of its own, for the tests that time how long a call waits. A
    /// thread-pool item can wait behind a loaded test run before it starts, which these tests
    /// would read as the call waiting - or, for "it did not finish in time", as the call holding
    /// back when it had not begun - so the call starts at once, and is timed only once it has.
    /// </summary>
    /// <summary>
    /// SOLIDWORKS' application thread, as far as a page's deliveries go: what is queued behind the pages' posts runs at
    /// once, or - while a case holds the thread, as another tab's extraction does - once the case lets it go, in order.
    /// </summary>
    private sealed class PaneThread
    {
        private readonly Queue<Action> _queued = new Queue<Action>();
        private bool _held;

        public void Hold()
        {
            lock (_queued)
            {
                _held = true;
            }
        }

        public void Release()
        {
            while (true)
            {
                Action next;
                lock (_queued)
                {
                    if (_queued.Count == 0)
                    {
                        _held = false;
                        return;
                    }

                    next = _queued.Dequeue();
                }

                next();
            }
        }

        public void AfterPosts(Action action)
        {
            lock (_queued)
            {
                if (_held)
                {
                    _queued.Enqueue(action);
                    return;
                }
            }

            action();
        }
    }

    private sealed class Caller<T>
    {
        private readonly ManualResetEventSlim _started = new ManualResetEventSlim(false);
        private readonly ManualResetEventSlim _done = new ManualResetEventSlim(false);
        private T _result = default!;
        private Exception? _error;

        public Caller(Func<T> call)
        {
            var thread = new Thread(() =>
            {
                _started.Set();
                try
                {
                    _result = call();
                }
                catch (Exception failure)
                {
                    _error = failure;
                }
                finally
                {
                    _done.Set();
                }
            })
            {
                IsBackground = true,
                Name = "fict-timed-caller",
            };
            thread.Start();
            Assert.True(_started.Wait(TimeSpan.FromSeconds(10)), "the caller's thread never started");
        }

        /// <summary>Whether the call finishes within <paramref name="bound"/>, counted from now.</summary>
        public bool Finishes(TimeSpan bound) => _done.Wait(bound);

        /// <summary>What the call returned; what it threw fails the test.</summary>
        public T Result
        {
            get
            {
                Assert.True(_done.IsSet, "the call has not finished");
                if (_error != null)
                {
                    throw new XunitException("the call threw: " + _error);
                }

                return _result;
            }
        }
    }

    /// <summary>The settings file, a host over the fakes, and what it posted, torn down together.</summary>
    private sealed class RestartWorld : IDisposable
    {
        private readonly FakeChannel _channel = new FakeChannel();
        private readonly List<string> _failuresTold = new List<string>();
        private ReviewHost? _host;
        private ReviewHostOptions? _options;
        private BridgeConfig? _bridge;
        private int _otherTabsTold;
        private int _documentReads;
        private int _followsAsked;

        public RestartWorld()
        {
            Root = Path.Combine(Path.GetTempPath(), "SwReview.DeferredRestart.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Root);
            SettingsPath = Path.Combine(Root, "settings.json");
            Settings = UserSettings.Defaults();
            Settings.RunRoot = Path.Combine(Root, "runs");

            // A launcher BackendLocator takes, for the test that builds the real start options.
            Settings.Python = Path.Combine(Root, "swreview.exe");
            File.WriteAllText(Settings.Python, string.Empty);
            Settings.SetApiKey(OpenAiKey);

            // The dump attaches to the document active as it begins, as the real one does.
            Dump.Attaches = () => Document;
        }

        public string Root { get; }

        public string SettingsPath { get; }

        public UserSettings Settings { get; }

        public FakeBackend Backend { get; } = new FakeBackend();

        /// <summary>A backend used instead of <see cref="Backend"/>; the one test that asks the real client sets it.</summary>
        public IBackendClient? BackendOverride { get; set; }

        public FakeDump Dump { get; } = new FakeDump();

        /// <summary>SOLIDWORKS' application thread, as far as what is queued behind the pages' posts goes.</summary>
        public PaneThread Pane { get; } = new PaneThread();

        public FakeSelection Selection { get; } = new FakeSelection();

        public PageDocument? Document { get; set; } = new PageDocument(@"C:\Fictional\FICT-bracket\FICT-bracket.SLDASM", "Default");

        /// <summary>How many times the host has asked for the active document.</summary>
        public int DocumentReads => Volatile.Read(ref _documentReads);

        /// <summary>
        /// The active document by the number of the reading, counted as <see cref="DocumentReads"/>
        /// counts them, for a test that changes it between two readings with no restart between
        /// them (owner decision 149A); null answers <see cref="Document"/>.
        /// </summary>
        public Func<int, PageDocument?>? DocumentAtRead { get; set; }

        /// <summary>
        /// Whether the host prepares a review before it starts one, as the add-in's always does:
        /// a preparation of the active document, its tree empty (owner decision 149A, on review).
        /// </summary>
        public bool Prepares { get; set; }

        /// <summary>How often the host asks whether the turn has ended; short, so the tests are.</summary>
        public TimeSpan Poll { get; set; } = TimeSpan.FromMilliseconds(10);

        /// <summary>
        /// What the run root rule reads (owner decision 154A); when null, a probe that answers every folder as a
        /// local one reached by its own path - not Windows, so a temp folder below a junction on a developer's
        /// machine fails no test that is not about the rule (the reviews' N11).
        /// </summary>
        public IRunRootProbe? Probe { get; set; }

        /// <summary>Whether a remodel run is in progress on the backend, as the add-in answers it.</summary>
        public Func<bool> BackendBusy { get; set; } = () => false;

        /// <summary>Whether a Model check is in progress, as the add-in answers it (owner decision 157A).</summary>
        public Func<bool> ModelChecking { get; set; } = () => false;

        /// <summary>Whether a Standards check is in progress, as the add-in answers it (owner decision 157A).</summary>
        public Func<bool> StandardsChecking { get; set; } = () => false;

        /// <summary>
        /// Sets the reading of the check tabs named - "Model check", "Standards", "both" or "none" - to
        /// <paramref name="reading"/>, and the other's to none (owner decision 157A).
        /// </summary>
        public void Checking(string tabs, Func<bool> reading)
        {
            ModelChecking = tabs == "Model check" || tabs == "both" ? reading : () => false;
            StandardsChecking = tabs == "Standards" || tabs == "both" ? reading : () => false;
        }

        /// <summary>The workstation's environment as the host reads it; none of it by default.</summary>
        public Func<string, string?> WorkstationEnvironment { get; set; } = _ => null;

        /// <summary>
        /// How many times the host asked for every other tab to be told the backend restarted
        /// (owner decision 145A), as the add-in tells the Model check, Standards and Remodel tabs.
        /// </summary>
        public int OtherTabsTold => Volatile.Read(ref _otherTabsTold);

        /// <summary>What telling the other tabs does after it is counted; a test makes it throw.</summary>
        public Action? TellingTheOtherTabs { get; set; }

        /// <summary>
        /// Every failed restart the host asked for every other tab to be told of, by its words - one
        /// that failed once the old backend had stopped (owner decision 145A, found on review) - as
        /// the add-in tells the Model check, Standards and Remodel tabs.
        /// </summary>
        public string[] FailuresToldToTheOtherTabs
        {
            get
            {
                lock (_failuresTold)
                {
                    return _failuresTold.ToArray();
                }
            }
        }

        /// <summary>What telling the other tabs of a failure does after it is recorded; a test makes it throw.</summary>
        public Action? TellingTheOtherTabsOfAFailure { get; set; }

        /// <summary>
        /// The tool service's review bridge as the add-in publishes it into the host's options (owner
        /// decision 152A): none by default, as every case before 152A had it. Set while the host is
        /// open, it is the gate publishing another service's bridge, or none.
        /// </summary>
        public BridgeConfig? Bridge
        {
            get => _options != null ? _options.Bridge : _bridge;
            set
            {
                _bridge = value;
                if (_options != null)
                {
                    _options.Bridge = value;
                }
            }
        }

        /// <summary>
        /// The document and configuration the tool service behind a bridge is attached to, as the
        /// add-in's gate answers it (owner decision 152A); null answers none, as for a pipe no
        /// service listening now has.
        /// </summary>
        public Func<BridgeConfig, PageDocument?>? BridgeServes { get; set; }

        /// <summary>How many times the host asked the tool service to follow the active document (owner decision 152A).</summary>
        public int FollowsAsked => Volatile.Read(ref _followsAsked);

        /// <summary>Runs as the host asks the tool service to follow, once counted.</summary>
        public Action? OnFollow { get; set; }

        /// <summary>
        /// What the host holds the tool service with (owner decision 152A, on the Codex review: X2), as
        /// the add-in's gate answers it; unset, nothing, as for a host with no gate.
        /// </summary>
        public Func<IDisposable?>? Hold { get; set; }

        public ReviewHost Host => _host ?? throw new InvalidOperationException("call Open() first");

        public void Open()
        {
            if (!File.Exists(SettingsPath))
            {
                Settings.Save(SettingsPath);
            }

            _options = new ReviewHostOptions(_channel, BackendOverride ?? Backend, SettingsPath)
            {
                BuildMode = BuildMode.Development,
                LogFolder = Path.Combine(Root, "logs"),
                Bridge = _bridge,
                BridgeDocument = bridge => BridgeServes?.Invoke(bridge),
                FollowActiveDocument = () =>
                {
                    Interlocked.Increment(ref _followsAsked);
                    OnFollow?.Invoke();
                },
                HoldToolService = () => Hold != null ? Hold() : ToolServiceHold.Nothing,
                CurrentDocument = () =>
                {
                    int read = Interlocked.Increment(ref _documentReads);
                    return DocumentAtRead != null ? DocumentAtRead(read) : Document;
                },
                Environment = name => WorkstationEnvironment(name),
                Dump = Dump,
                PrepareReview = Prepares
                    ? () => new ReviewPreparation(
                        new ComponentTreeResult
                        {
                            RootDocumentPath = Document!.Path,
                            ActiveConfiguration = Document.Configuration ?? string.Empty,
                        },
                        new GapCollector())
                    : (Func<ReviewPreparation>?)null,
                EngineeringSelection = Selection,
                Engineer = "FICT-engineer",
                Now = () => Stamp,
                RestartPoll = Poll,
                RunRootProbe = Probe ?? FakeRunRootProbe.Local(),
                BackendBusy = () => BackendBusy(),
                ModelCheckInProgress = () => ModelChecking(),
                StandardsCheckInProgress = () => StandardsChecking(),
                BackendRestarted = () =>
                {
                    Interlocked.Increment(ref _otherTabsTold);
                    TellingTheOtherTabs?.Invoke();
                },
                BackendRestartFailed = message =>
                {
                    lock (_failuresTold)
                    {
                        _failuresTold.Add(message);
                    }

                    TellingTheOtherTabsOfAFailure?.Invoke();
                },
            };
            _host = new ReviewHost(_options);
        }

        /// <summary>A review of the open document the host started, in a run folder of its own.</summary>
        public void Track(string chatId)
        {
            string folder = Path.Combine(Settings.RunRoot, "20261019-101500-" + chatId);
            Directory.CreateDirectory(folder);
            Host.TrackSession(chatId, folder, Document, new DateTimeOffset(Stamp));
        }

        public void Receive(string type, string id, object payload) =>
            Host.Receive(JsonSerializer.Serialize(new { type, id, payload }));

        /// <summary>The single reply of <paramref name="type"/> that echoes <paramref name="id"/>.</summary>
        public JsonElement Reply(string type, string id)
        {
            JsonElement[] matches = Messages()
                .Where(root => root.GetProperty("type").GetString() == type
                    && root.TryGetProperty("id", out JsonElement replyId)
                    && replyId.ValueKind == JsonValueKind.String
                    && replyId.GetString() == id)
                .Select(root => root.GetProperty("payload"))
                .ToArray();
            Assert.True(
                matches.Length == 1,
                $"expected exactly one '{type}' reply to '{id}', saw {matches.Length}; posted: "
                    + string.Join(" | ", Types()));
            return matches[0];
        }

        /// <summary>The payload of every message of <paramref name="type"/>, in the order posted.</summary>
        public JsonElement[] Posted(string type) => Messages()
            .Where(root => root.GetProperty("type").GetString() == type)
            .Select(root => root.GetProperty("payload"))
            .ToArray();

        public JsonElement Last(string type)
        {
            JsonElement[] all = Posted(type);
            Assert.True(all.Length > 0, $"no '{type}' message was posted");
            return all[all.Length - 1];
        }

        public string[] Types() => Messages().Select(root => root.GetProperty("type").GetString() ?? "?").ToArray();

        /// <summary>
        /// Whether anything posted to the page names <paramref name="secret"/>: answered, so that a case
        /// asserting it never prints a key, even a fictional one.
        /// </summary>
        public bool AnythingPostedContains(string secret) =>
            _channel.Snapshot().Any(message => message.Contains(secret));

        public void AssertNothingPostedContains(string secret)
        {
            foreach (string message in _channel.Snapshot())
            {
                Assert.DoesNotContain(secret, message, StringComparison.Ordinal);
            }
        }

        public void Dispose()
        {
            _host?.Dispose();
            try
            {
                Directory.Delete(Root, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        private IEnumerable<JsonElement> Messages() =>
            _channel.Snapshot().Select(message => JsonDocument.Parse(message).RootElement);
    }

    /// <summary>The page, as the host sees it; posted to from the host's own threads too.</summary>
    private sealed class FakeChannel : IPageChannel
    {
        private readonly List<string> _posted = new List<string>();

        public void PostMessage(string json)
        {
            lock (_posted)
            {
                _posted.Add(json);
            }
        }

        public string[] Snapshot()
        {
            lock (_posted)
            {
                return _posted.ToArray();
            }
        }
    }

    /// <summary>
    /// The backend as the host reaches it. Its restart refuses while a turn runs, as
    /// <see cref="BackendSupervisor.Restart"/> does, before anything is stopped; each restart it
    /// makes is a new backend - a new port and token, one generation on - and each session
    /// remembers the generation it was created on. Asked from the host's own threads as well as
    /// the test's, so everything it keeps is behind one lock.
    /// </summary>
    private sealed class FakeBackend : IBackendClient
    {
        private readonly object _gate = new object();
        private readonly HashSet<string> _running = new HashSet<string>(StringComparer.Ordinal);
        private readonly List<(UserSettings, ResolvedApiKey)> _restarts = new List<(UserSettings, ResolvedApiKey)>();
        private readonly List<string> _keysAsked = new List<string>();
        private readonly List<(NewSessionRequest, int)> _sessions = new List<(NewSessionRequest, int)>();
        private readonly List<BackendStartOptions> _started = new List<BackendStartOptions>();
        private readonly ThreadLocal<bool> _unansweredHere = new ThreadLocal<bool>();
        private int _generation;
        private int _questions;
        private int _attempts;
        private int _unanswered;
        private int _restartsAsked;
        private bool _down;

        /// <summary>Thrown by each restart the backend's own check lets through, the old backend stopped.</summary>
        public Exception? RestartFailure { get; set; }

        /// <summary>
        /// Thrown by each restart the backend's own check lets through before it stops anything -
        /// the launcher has gone, say - so the old backend is still up.
        /// </summary>
        public Exception? EarlyRestartFailure { get; set; }

        /// <summary>
        /// Whether the backend's own check asks the host's question, as production's does
        /// (BackendSupervisor's delegate is ReviewHost.AnyTurnRunning), and so cannot see a turn
        /// while its question goes unanswered. False models a backend that answers again by the
        /// time it asks.
        /// </summary>
        public bool CheckAsksTheSameQuestion { get; set; }

        /// <summary>Chats this backend does not hold: their question is answered `UnknownChat`.</summary>
        public HashSet<string> Unknown { get; } = new HashSet<string>(StringComparer.Ordinal);

        /// <summary>
        /// Chats whose question is answered with this refusal rather than their state; set before
        /// the host is opened, or through <see cref="Refuses"/> once it may be asking.
        /// </summary>
        public Dictionary<string, BackendRequestException> Refusals { get; } =
            new Dictionary<string, BackendRequestException>(StringComparer.Ordinal);

        /// <summary>From now on, answers <paramref name="chatId"/>'s question with <paramref name="refusal"/>.</summary>
        public void Refuses(string chatId, BackendRequestException refusal)
        {
            lock (_gate)
            {
                Refusals[chatId] = refusal;
            }
        }

        /// <summary>
        /// Gives no answer to the next <paramref name="questions"/> questions about a turn, from
        /// any thread, as a backend that has stopped answering - every one, by default - then
        /// answers again.
        /// </summary>
        public void StopsAnswering(int questions = int.MaxValue)
        {
            lock (_gate)
            {
                _unanswered = questions;
            }
        }

        /// <summary>Answers every question again.</summary>
        public void AnswersAgain() => StopsAnswering(questions: 0);

        /// <summary>
        /// Gives no answer to the questions <paramref name="asking"/> asks on the calling thread -
        /// the test's, where the page's messages are handled - while the host's own look, on its
        /// thread, is answered: one round trip that timed out, not a backend that stopped answering.
        /// </summary>
        public void LeavesUnanswered(Action asking)
        {
            _unansweredHere.Value = true;
            try
            {
                asking();
            }
            finally
            {
                _unansweredHere.Value = false;
            }
        }

        /// <summary>
        /// No backend process: no endpoint, and every question refused as the real client refuses
        /// one with no backend. A failed restart leaves it so - the old process was stopped and the
        /// new one did not start - and a restart that succeeds ends it.
        /// </summary>
        public bool Down
        {
            get { lock (_gate) { return _down; } }
            set { lock (_gate) { _down = value; } }
        }

        /// <summary>Runs inside the model-list round trip a save makes between its check and its restart.</summary>
        public Action? DuringModelList { get; set; }

        /// <summary>When set, a restart past the backend's own check waits on it: a restart being made.</summary>
        public ManualResetEventSlim? Hold { get; set; }

        /// <summary>Set once a restart has got past the backend's own check.</summary>
        public ManualResetEventSlim Entered { get; } = new ManualResetEventSlim(false);

        /// <summary>
        /// Runs while a restart is being made, past the backend's own check, on the thread making
        /// it - where the engineer can make another document active (owner decision 149A).
        /// </summary>
        public Action? DuringRestart { get; set; }

        /// <summary>
        /// Runs once a restart has started its backend - its endpoint published, as
        /// <see cref="BackendSupervisor.Start"/> publishes `Current` - before the restart returns, on the
        /// thread making it: where that thread can be held before the host records the settings the
        /// start was made with (owner decision 153A, Codex's re-review, R1).
        /// </summary>
        public Action? Published { get; set; }

        /// <summary>Builds the start options each restart would be made with; null builds none.</summary>
        public Func<UserSettings, ResolvedApiKey, BackendStartOptions>? Options { get; set; }

        /// <summary>Thrown by each `POST /sessions`, which creates nothing; null creates sessions.</summary>
        public Exception? SessionFailure { get; set; }

        /// <summary>
        /// Runs as the endpoint is read, before it is, on the reading thread: where a case can make a start
        /// begin between two of a reader's readings (owner decision 153A, the fourth review, N3).
        /// </summary>
        public Action? EndpointRead { get; set; }

        public BackendEndpoint? Endpoint
        {
            get
            {
                EndpointRead?.Invoke();
                lock (_gate)
                {
                    return _down ? null : new BackendEndpoint(52000 + _generation, "FICT-token-" + _generation);
                }
            }
        }

        /// <summary>0 for the backend the add-in started; one more for each restart.</summary>
        public int Generation
        {
            get { lock (_gate) { return _generation; } }
        }

        /// <summary>How many times the host has asked whether a turn runs.</summary>
        public int Questions
        {
            get { lock (_gate) { return _questions; } }
        }

        /// <summary>Restarts the backend's own check let through, made or failed.</summary>
        public int Attempts
        {
            get { lock (_gate) { return _attempts; } }
        }

        /// <summary>Every restart the host asked for, the ones the backend's own check refused too.</summary>
        public int RestartsAsked
        {
            get { lock (_gate) { return _restartsAsked; } }
        }

        public (UserSettings Settings, ResolvedApiKey Key)[] Restarts
        {
            get { lock (_gate) { return _restarts.ToArray(); } }
        }

        /// <summary>
        /// The key of every restart the host asked for, in the order asked - the ones the backend's own
        /// check refused and the ones that failed as well - and none for a start with no key.
        /// </summary>
        public string[] KeysAsked
        {
            get { lock (_gate) { return _keysAsked.ToArray(); } }
        }

        public (NewSessionRequest Request, int Generation)[] Sessions
        {
            get { lock (_gate) { return _sessions.ToArray(); } }
        }

        public BackendStartOptions[] Started
        {
            get { lock (_gate) { return _started.ToArray(); } }
        }

        public void StartTurn(string chatId)
        {
            lock (_gate)
            {
                _running.Add(chatId);
            }
        }

        public void EndTurn(string chatId)
        {
            lock (_gate)
            {
                _running.Remove(chatId);
            }
        }

        public IReadOnlyList<ModelChoice> ListModels(string provider)
        {
            DuringModelList?.Invoke();

            // None offered: the save keeps the model unchecked, as for a provider it cannot ask.
            return new ModelChoice[0];
        }

        public bool IsTurnRunning(string chatId)
        {
            lock (_gate)
            {
                _questions++;
                if (_down)
                {
                    throw new BackendRequestException(
                        "BackendUnavailable", "the review backend is not running.", retryable: true);
                }

                if (Unanswered())
                {
                    if (!_unansweredHere.Value && _unanswered != int.MaxValue)
                    {
                        _unanswered--;
                    }

                    throw new BackendRequestException(
                        "BackendUnavailable", "the review backend did not answer: FICT timed out", retryable: true);
                }

                if (Unknown.Contains(chatId))
                {
                    throw new BackendRequestException("UnknownChat", "no chat " + chatId, retryable: false, inner: null, status: 404);
                }

                if (Refusals.TryGetValue(chatId, out BackendRequestException? refusal))
                {
                    throw refusal;
                }

                return _running.Contains(chatId);
            }
        }

        /// <summary>Whether a question asked now goes unanswered; called under the fake's lock.</summary>
        private bool Unanswered() => _unansweredHere.Value || _unanswered > 0;

        /// <summary>Thrown by every session the backend is asked to create, when set: a backend that stopped.</summary>
        public Exception? CreateFailure { get; set; }

        /// <summary>
        /// Run while `POST /sessions` is out, before the session is answered: what a switch and a follow made
        /// while the call is out do (owner decision 152A, the final review's C1).
        /// </summary>
        public Action? DuringCreate { get; set; }

        public ChatSessionHandle CreateSession(NewSessionRequest request)
        {
            if (CreateFailure != null)
            {
                throw CreateFailure;
            }

            DuringCreate?.Invoke();

            lock (_gate)
            {
                if (SessionFailure != null)
                {
                    throw SessionFailure;
                }

                _sessions.Add((request, _generation));
                return new ChatSessionHandle("chat-new-" + _sessions.Count, "review-new-" + _sessions.Count);
            }
        }

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
            lock (_gate)
            {
                _restartsAsked++;
                if (key.Key != null)
                {
                    _keysAsked.Add(key.Key);
                }

                // The backend's own check, made before anything is stopped - blind to the turns
                // while the question goes unanswered, when it asks the same question.
                bool blind = CheckAsksTheSameQuestion && Unanswered();
                if (_running.Count > 0 && !blind)
                {
                    throw new TurnRunningException();
                }

                _attempts++;
            }

            Entered.Set();
            DuringRestart?.Invoke();
            Hold?.Wait(TimeSpan.FromSeconds(15));

            lock (_gate)
            {
                if (EarlyRestartFailure != null)
                {
                    throw EarlyRestartFailure;
                }

                if (RestartFailure != null)
                {
                    _down = true;
                    throw RestartFailure;
                }

                if (Options != null)
                {
                    _started.Add(Options(settings, key));
                }

                _restarts.Add((settings, key));
                _generation++;
                _down = false;
            }

            Published?.Invoke();
        }
    }

    /// <summary>
    /// The fake backend, except that whether a turn runs is asked of the real
    /// <see cref="BackendClient"/>, over HTTP, as the add-in asks it.
    /// </summary>
    private sealed class TurnsAskedOfTheRealClient : IBackendClient
    {
        private readonly BackendClient _client;
        private readonly FakeBackend _fake;

        public TurnsAskedOfTheRealClient(BackendClient client, FakeBackend fake)
        {
            _client = client;
            _fake = fake;
        }

        public BackendEndpoint? Endpoint => _client.Endpoint;

        public IReadOnlyList<ModelChoice> ListModels(string provider) => _fake.ListModels(provider);

        public bool IsTurnRunning(string chatId) => _client.IsTurnRunning(chatId);

        public ChatSessionHandle CreateSession(NewSessionRequest request) => _fake.CreateSession(request);

        public void Restart(UserSettings settings, ResolvedApiKey key) => _fake.Restart(settings, key);
    }

    /// <summary>
    /// The real <see cref="BackendClient"/>, over a stub child whose handshake names
    /// <paramref name="port"/>: whatever listens there - or nothing - is the backend it asks.
    /// </summary>
    private sealed class RealClient : IDisposable
    {
        private readonly StubBackend _stub = new StubBackend();
        private readonly BackendSupervisor _supervisor = new BackendSupervisor(() => false);

        public RealClient(int port)
        {
            _stub.PrintsHandshake(port);
            var options = new BackendStartOptions(_stub.Command, _stub.LogPath)
            {
                RunRoot = _stub.RunRoot,
                AllowOrigin = "https://swreview.invalid",
                HealthProbe = (origin, token) => true,
                StopGrace = TimeSpan.FromMilliseconds(100),
            };
            foreach (KeyValuePair<string, string> knob in _stub.Knobs)
            {
                options.Environment[knob.Key] = knob.Value;
            }

            _supervisor.Start(options);
            Client = new BackendClient(_supervisor, Path.GetDirectoryName(_stub.LogPath)!, null);
        }

        public BackendClient Client { get; }

        public void Dispose()
        {
            Client.Dispose();
            _supervisor.Dispose();
            _stub.Dispose();
        }
    }

    /// <summary>`GET /sessions/{chat_id}` answering `{state}` for one chat, as `chat/server.py` does.</summary>
    private sealed class SessionStateServer : IDisposable
    {
        private readonly HttpListener _listener;
        private readonly Thread _serving;
        private readonly string _chatId;
        private volatile string _state = "ended";

        public SessionStateServer(string chatId)
        {
            _chatId = chatId;
            _listener = LoopbackPort.StartListener(out int port);
            Port = port;
            _serving = new Thread(Serve) { IsBackground = true, Name = "fict-session-state" };
            _serving.Start();
        }

        public int Port { get; }

        public string State
        {
            get => _state;
            set => _state = value;
        }

        /// <summary>A chat id answered `400 InvalidRequest`, as the backend answers one it cannot read.</summary>
        public string? InvalidChat { get; set; }

        /// <summary>A chat id answered 500 with a body that is not the backend's JSON.</summary>
        public string? BrokenChat { get; set; }

        public void Dispose()
        {
            try
            {
                _listener.Stop();
                _listener.Close();
            }
            catch (Exception)
            {
            }

            _serving.Join(TimeSpan.FromSeconds(2));
        }

        private void Serve()
        {
            while (true)
            {
                HttpListenerContext context;
                try
                {
                    context = _listener.GetContext();
                }
                catch (Exception)
                {
                    return;
                }

                try
                {
                    bool known = context.Request.HttpMethod == "GET"
                        && context.Request.Url!.AbsolutePath == "/sessions/" + _chatId;
                    bool invalid = InvalidChat != null
                        && context.Request.Url!.AbsolutePath == "/sessions/" + InvalidChat;
                    bool broken = BrokenChat != null
                        && context.Request.Url!.AbsolutePath == "/sessions/" + BrokenChat;
                    byte[] body = Encoding.UTF8.GetBytes(known
                        ? "{\"chat_id\":\"" + _chatId + "\",\"state\":\"" + _state + "\"}"
                        : invalid
                            ? "{\"error_class\":\"InvalidRequest\",\"message\":\"not a chat id\",\"retryable\":false}"
                            : broken
                                ? "FICT Internal Server Error"
                                : "{\"error_class\":\"UnknownChat\",\"message\":\"no such chat\",\"retryable\":false}");
                    context.Response.StatusCode = known ? 200 : invalid ? 400 : broken ? 500 : 404;
                    context.Response.ContentType = "application/json";
                    context.Response.ContentLength64 = body.Length;
                    context.Response.OutputStream.Write(body, 0, body.Length);
                    context.Response.Close();
                }
                catch (Exception)
                {
                    // The test is over and the listener went with it.
                }
            }
        }
    }

    private sealed class FakeDump : IReviewDump
    {
        private int _runs;

        public int Runs => Volatile.Read(ref _runs);

        /// <summary>Runs as each dump begins, before anything is written.</summary>
        public Action? OnRun { get; set; }

        /// <summary>
        /// Runs as each dump begins, before it attaches: a switch that lands in the moment between the
        /// host's last reading of the document and the dump's attach (owner decision 152A, on review:
        /// S2). <see cref="OnRun"/> runs after the attach, during the extraction.
        /// </summary>
        public Action? BeforeAttach { get; set; }

        /// <summary>
        /// What the dump attaches to as it begins - the active document, as the real dump's attach
        /// finds it - and says it extracted (<see cref="DumpSummary.Extracted"/>); none answers none.
        /// </summary>
        public Func<PageDocument?>? Attaches { get; set; }

        public DumpSummary Run(string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
        {
            BeforeAttach?.Invoke();
            PageDocument? attached = Attaches?.Invoke();
            OnRun?.Invoke();
            Interlocked.Increment(ref _runs);

            // A package to digest: a context review is bound to its package's SHA-256.
            string package = Path.Combine(outputDirectory, "package.json");
            File.WriteAllText(package, "{\"package_id\":\"FICT-package\"}");
            return new DumpSummary(package, components: 12, gaps: 0, extracted: attached);
        }
    }

    /// <summary>
    /// A Model check or a Standards tab bound to a world's review host as the add-in binds them (owner decision 157A):
    /// its host - on the caller's thread, standing in for the tab's own pump - reading the run root, the backend and the
    /// restart's gate through the review host; the review host reading whether the tab holds a check; a restart the
    /// review host makes told to the tab; and the pane's proxy, through which the page evaluates a check, holding that
    /// check while the call is out. Its dump is the world's, its document a fictional part, and the clock its hand-over
    /// is measured by the test's.
    /// </summary>
    private sealed class CheckTab : IDisposable
    {
        private readonly FakeChannel _channel = new FakeChannel();
        private readonly List<Evaluation> _evaluations = new List<Evaluation>();
        private readonly RestartWorld _world;
        private readonly ModelCheckHost? _modelCheck;
        private readonly StandardsHost? _standards;
        private long _clockTicks;
        private int _readies;

        public CheckTab(RestartWorld world, string tab)
        {
            _world = world;
            Tab = tab;
            world.Document = new PageDocument(@"C:\Fictional\FICT-bracket\FICT-bracket.SLDPRT", "Default");
            Func<TimeSpan> clock = () => TimeSpan.FromTicks(Interlocked.Read(ref _clockTicks));
            if (tab == "Model check")
            {
                _modelCheck = new ModelCheckHost(new ModelCheckHostOptions(_channel, () => world.Host.RunRoot)
                {
                    RunRootsInForce = () => world.Host.RunRootsInForce,
                    RunRootForANewRun = () => world.Host.RunRootForANewRun(),
                    RunRootSaved = () => world.Host.Settings.RunRoot,
                    Backend = () => world.Backend.Endpoint,
                    CurrentDocument = () => world.Document,
                    Dump = world.Dump,
                    LogFolder = () => Path.Combine(world.Root, "logs"),
                    Now = () => Stamp,
                    RunRootProbe = FakeRunRootProbe.Local(),
                    Hold =
                    {
                        BeginCheck = begin => world.Host.BeginCheck(begin),
                        RestartAhead = () => world.Host.RestartAhead,
                        Clock = clock,
                        AfterPosts = world.Pane.AfterPosts,
                        WhileNoRestartRuns = step => world.Host.WhileNoRestartRuns(step),
                    },
                });
                world.ModelChecking = () => _modelCheck.CheckInProgress;
            }
            else
            {
                string profile = Path.Combine(world.Root, "FICT-standards.yaml");
                File.WriteAllText(profile, "# FICT standards profile\n");
                _standards = new StandardsHost(new StandardsHostOptions(_channel, () => world.Host.RunRoot)
                {
                    RunRootsInForce = () => world.Host.RunRootsInForce,
                    RunRootForANewRun = () => world.Host.RunRootForANewRun(),
                    RunRootSaved = () => world.Host.Settings.RunRoot,
                    Backend = () => world.Backend.Endpoint,
                    CurrentDocument = () => world.Document,
                    ProfilePath = () => profile,
                    Dump = world.Dump,
                    LogFolder = () => Path.Combine(world.Root, "logs"),
                    Now = () => Stamp,
                    RunRootProbe = FakeRunRootProbe.Local(),
                    Hold =
                    {
                        BeginCheck = begin => world.Host.BeginCheck(begin),
                        RestartAhead = () => world.Host.RestartAhead,
                        Clock = clock,
                        AfterPosts = world.Pane.AfterPosts,
                        WhileNoRestartRuns = step => world.Host.WhileNoRestartRuns(step),
                    },
                });
                world.StandardsChecking = () => _standards.CheckInProgress;
            }

            world.TellingTheOtherTabs = BackendRestarted;
            Proxy = new BackendProxyHandler(
                () => world.Backend.Endpoint,
                Send,
                () => world.Host.PageTurnRefusal(),
                () => ToolServiceHold.Nothing,
                HoldEvaluation);

            // The page loads: `ready`, answered with the `init` whose token it calls the backend with.
            Ready();
        }

        /// <summary>
        /// One evaluation the proxy sent on: its folder, the backend's generation and restarts asked once it was answered,
        /// and whether it carried the token of the backend it reached, which refuses any other.
        /// </summary>
        public sealed class Evaluation
        {
            public Evaluation(string? runDirectory, int generation, int restartsAskedWhenAnswered, bool authorized)
            {
                RunDirectory = runDirectory;
                Generation = generation;
                RestartsAskedWhenAnswered = restartsAskedWhenAnswered;
                Authorized = authorized;
            }

            public string? RunDirectory { get; }

            /// <summary>The backend the evaluation reached: 0 for the one the add-in started, one more for each restart.</summary>
            public int Generation { get; }

            public int RestartsAskedWhenAnswered { get; }

            /// <summary>Whether the evaluation carried the token of the backend it reached; one that did not was refused.</summary>
            public bool Authorized { get; }
        }

        public string Tab { get; }

        public string StartType => Tab == "Model check" ? "check.start" : "standards.start";

        public string ExtractedType => Tab == "Model check" ? "check.extracted" : "standards.extracted";

        /// <summary>The route the page evaluates its check with (contracts/model-check.md, standards-check.md).</summary>
        public string Route => Tab == "Model check" ? "/checks/rms" : "/checks/standards";

        public BackendProxyHandler Proxy { get; }

        /// <summary>Runs while an evaluation is out, before it is answered.</summary>
        public Action? WhileEvaluating { get; set; }

        public Evaluation[] Evaluations
        {
            get
            {
                lock (_evaluations)
                {
                    return _evaluations.ToArray();
                }
            }
        }

        public bool CheckInProgress => _modelCheck?.CheckInProgress ?? _standards!.CheckInProgress;

        public IDisposable? HoldEvaluation(string runDirectory) =>
            _modelCheck != null ? _modelCheck.HoldEvaluation(runDirectory) : _standards!.HoldEvaluation(runDirectory);

        public void BackendRestarted()
        {
            if (_modelCheck != null)
            {
                _modelCheck.BackendRestarted();
            }
            else
            {
                _standards!.BackendRestarted();
            }
        }

        /// <summary>The engineer presses Model check, or Standards check: the start, on this thread.</summary>
        public void Press(string id)
        {
            object payload = Tab == "Model check" ? new { scope = "part" } : (object)new { };
            string json = JsonSerializer.Serialize(new { type = StartType, id, payload });
            if (_modelCheck != null)
            {
                _modelCheck.Receive(json);
            }
            else
            {
                _standards!.Receive(json);
            }
        }

        /// <summary>The run folder the start's extraction handed to the page.</summary>
        public string Extracted(string id) =>
            Reply(ExtractedType, id).GetProperty("run_dir").GetString()
                ?? throw new XunitException("the extraction named no run folder");

        /// <summary>
        /// The page evaluates the check in <paramref name="runDirectory"/> through the pane's proxy, with the token it
        /// holds (<see cref="PageToken"/>), as the page does.
        /// </summary>
        public ProxiedResponse Evaluate(string runDirectory)
        {
            object body = Tab == "Model check"
                ? new { run_dir = runDirectory, scope = "part", document_id = (string?)null }
                : (object)new { run_dir = runDirectory, profile_path = "FICT-standards.yaml" };
            return Proxy.TryServe(
                BackendProxy.PageOrigin + Route,
                "POST",
                new[]
                {
                    new KeyValuePair<string, string>("Content-Type", "application/json"),
                    new KeyValuePair<string, string>("Authorization", "Bearer " + PageToken(runDirectory)),
                },
                new MemoryStream(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(body))))
                ?? throw new XunitException("the proxy did not take the evaluation");
        }

        /// <summary>Moves the clock the hand-over is measured by.</summary>
        public void Advance(TimeSpan by) => Interlocked.Add(ref _clockTicks, by.Ticks);

        /// <summary>This tab's run folders under the run root in force - a check's, not the tracked reviews' beside them.</summary>
        public string[] RunFolders() =>
            Directory.Exists(_world.Host.RunRoot)
                ? Directory.GetDirectories(_world.Host.RunRoot)
                    .Where(folder => folder.EndsWith(
                        Tab == "Model check" ? SwReview.AddIn.Review.RunFolders.CheckSuffix : SwReview.AddIn.Review.RunFolders.StandardsSuffix,
                        StringComparison.OrdinalIgnoreCase))
                    .ToArray()
                : new string[0];

        public JsonElement Reply(string type, string id)
        {
            JsonElement[] matches = Messages()
                .Where(root => root.GetProperty("type").GetString() == type
                    && root.TryGetProperty("id", out JsonElement replyId)
                    && replyId.ValueKind == JsonValueKind.String
                    && replyId.GetString() == id)
                .Select(root => root.GetProperty("payload"))
                .ToArray();
            Assert.True(
                matches.Length == 1,
                $"expected exactly one '{type}' reply to '{id}', saw {matches.Length}; posted: " + string.Join(" | ", Types()));
            return matches[0];
        }

        public JsonElement[] Posted(string type) => Messages()
            .Where(root => root.GetProperty("type").GetString() == type)
            .Select(root => root.GetProperty("payload"))
            .ToArray();

        public string[] Types() => Messages().Select(root => root.GetProperty("type").GetString() ?? "?").ToArray();

        public void AssertNothingPostedContains(string secret)
        {
            foreach (string message in _channel.Snapshot())
            {
                Assert.DoesNotContain(secret, message, StringComparison.Ordinal);
            }
        }

        public void Dispose()
        {
            _modelCheck?.Dispose();
            _standards?.Dispose();
        }

        private ProxiedResponse Send(ProxiedRequest request)
        {
            string? runDirectory = null;
            if (request.Body != null)
            {
                using (JsonDocument body = JsonDocument.Parse(request.Body))
                {
                    runDirectory = body.RootElement.GetProperty("run_dir").GetString();
                }
            }

            int generation = _world.Backend.Generation;
            bool authorized = request.Headers.Any(header =>
                header.Key == "Authorization" && header.Value == "Bearer " + _world.Backend.Endpoint?.Token);
            WhileEvaluating?.Invoke();
            lock (_evaluations)
            {
                _evaluations.Add(new Evaluation(runDirectory, generation, _world.Backend.RestartsAsked, authorized));
            }

            // The backend refuses a token other than its own: the token of a backend a restart replaced.
            return authorized
                ? new ProxiedResponse(
                    201, "Created", "Content-Type: application/json", Encoding.UTF8.GetBytes("{\"check_id\":\"FICT-check\"}"))
                : new ProxiedResponse(
                    401, "Unauthorized", "Content-Type: application/json", Encoding.UTF8.GetBytes("{\"error_class\":\"Unauthorized\"}"));
        }

        /// <summary>
        /// The page asks for its `init` - as it loads, and again once told the backend restarted - and answers the
        /// token it carries.
        /// </summary>
        private string? Ready()
        {
            string id = "ready-" + Interlocked.Increment(ref _readies);
            string json = JsonSerializer.Serialize(new { type = "ready", id, payload = new { } });
            if (_modelCheck != null)
            {
                _modelCheck.Receive(json);
            }
            else
            {
                _standards!.Receive(json);
            }

            JsonElement token = Reply("init", id).GetProperty("token");
            return token.ValueKind == JsonValueKind.String ? token.GetString() : null;
        }

        /// <summary>
        /// The token the page evaluates the run in <paramref name="runDirectory"/> with: the one its last `init` carried
        /// when it read the reply that handed it the run - or, told before that reply that the backend restarted, the one
        /// the `init` it then asked for carries, which its evaluation waits for (`check-page.js`, `call`,
        /// `initSettled`). Told only after the reply, it has already called with the token it had: the backend the
        /// restart replaced.
        /// </summary>
        private string? PageToken(string runDirectory)
        {
            string? token = null;
            bool told = false;
            foreach (JsonElement message in Messages())
            {
                string? type = message.GetProperty("type").GetString();
                JsonElement payload = message.GetProperty("payload");
                if (type == "init")
                {
                    JsonElement carried = payload.GetProperty("token");
                    token = carried.ValueKind == JsonValueKind.String ? carried.GetString() : null;
                    told = false;
                }
                else if (type == "backend.restarted")
                {
                    told = true;
                }
                else if (type == ExtractedType
                    && payload.TryGetProperty("run_dir", out JsonElement handed)
                    && handed.GetString() == runDirectory)
                {
                    break;
                }
            }

            return told ? Ready() : token;
        }

        private IEnumerable<JsonElement> Messages() =>
            _channel.Snapshot().Select(message => JsonDocument.Parse(message).RootElement);
    }

    /// <summary>The current selection, read against prepared context (feature 016).</summary>
    private sealed class FakeSelection : IEngineeringSelectionCapture
    {
        private int _captures;

        public int Captures => Volatile.Read(ref _captures);

        /// <summary>Runs as each read begins.</summary>
        public Action? OnCapture { get; set; }

        public EngineeringSelectionObservation Capture(string runDirectory, string expectedPackageSha256)
        {
            OnCapture?.Invoke();
            Interlocked.Increment(ref _captures);
            return new EngineeringSelectionObservation { PackageSha256 = expectedPackageSha256 };
        }
    }
}
