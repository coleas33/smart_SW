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
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
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
/// leaves the settings written and in force in the host, and the restart refused. These tests
/// start that turn where it really lands: inside the model-list round trip the save makes after
/// its check and before its restart.
///
/// What they pin:
/// 1. <b>The save is kept and says so.</b> `settings.saved`, the settings on disk and in force,
///    and the sentence, word for word.
/// 2. <b>The backend restarts once no turn runs</b>, however the turn ended, once, with the
///    settings in force then - the last of several saves - and never under a running turn.
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
/// Owner decision 152A adds section 13: <b>a session's bridge serves the review's document</b>.
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
    /// the restart still waits, for the next review, follow-up or remodel run. Since owner decision
    /// 145A it says "the saved settings", since a save during a remodel run is not one made during
    /// the turn, and names the remodel run among what makes the restart first.
    /// </summary>
    private const string NotAnsweringYet =
        "the review backend is not answering, so it has not been restarted with the saved settings yet. "
        + "It will be before the next review, follow-up or remodel run, once it answers; to restart it "
        + "now, save the settings again.";

    /// <summary>The Review tab's sentence for a save made while a remodel run is in progress (owner decision 145A).</summary>
    private const string RemodelRunPromise =
        "the settings are saved; the backend restarts when the remodel run ends.";

    /// <summary>...and for one a turn also started during.</summary>
    private const string TurnAndRemodelRunPromise =
        "the settings are saved; the backend restarts when the running turn and the remodel run end.";

    /// <summary>
    /// Every sentence the Review tab may have been shown about a restart that waits, as
    /// `backend.restarted` carries them: the three promises and the watcher's word that the
    /// backend is not answering.
    /// </summary>
    private static readonly string[] RestartSentences =
        { Promise, RemodelRunPromise, TurnAndRemodelRunPromise, NotAnsweringYet };

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
        // settings in force (contracts/pane-host-messages.md, `settings.save`).
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
    /// The restart is built from the settings in force when it is made - here a switch from
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

            // The same failure, masked: the status with the way on after it (150A review), the
            // refusal alone, its class's sentence naming the way on.
            JsonElement? answer = call.Result;
            Assert.NotNull(answer);
            Assert.Equal("BackendUnavailable", answer!.Value.GetProperty("error_class").GetString());
            Assert.Equal(answer.Value.GetProperty("message").GetString() + ". " + RetryTheRestart, reported);
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
            Assert.Equal("FICT the launcher has gone. " + RetryTheRestart, world.Last("status").GetProperty("message").GetString());
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
    /// in force in the host and answered `settings.saved`. Its restart waits for the run, as one a
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
    /// The settings are written, and in force in the host, before the save restarts the backend,
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

        // Kept: written, and in force in the host. The answer says it all, so nothing beside it -
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
    /// after it, which is the same whether the restart stopped the old backend or failed before it
    /// did: saving the settings again retries the restart (150A review, O2; until then the banner
    /// carried the bare failure). The other tabs are handed the failure alone, and only once no
    /// backend is up: the add-in adds their way on.
    /// </summary>
    [Theory]
    [InlineData(
        "old backend stopped",
        "FICT the backend did not answer /health within 30 seconds.",
        "FICT the backend did not answer /health within 30 seconds. Save the settings again to retry the restart.")]
    [InlineData(
        "old backend still up",
        "FICT the launcher could not be resolved (log: C:\\Fictional\\FICT-logs\\backend.log)",
        "FICT the launcher could not be resolved (log: C:\\Fictional\\FICT-logs\\backend.log). Save the settings again to retry the restart.")]
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

    // ---- 13. a session's bridge serves the review's document (owner decision 152A) ------------

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
    [InlineData("RemodelRun", "RemodelRunning")]
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
    [InlineData(true, "RemodelRun")]
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

        Assert.Equal(DeferredRestart.Outcome.RemodelRunning, restart.Apply(out Exception? failure));
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
        Assert.Equal(DeferredRestart.Hold.RemodelRun, heldBy);
        Assert.True(restart.Pending);

        Assert.Equal(DeferredRestart.Outcome.RemodelRunning, restart.Apply(out Exception? failure));
        Assert.Null(failure);

        int began = 0;
        Assert.Equal(DeferredRestart.Outcome.RemodelRunning, restart.Begin(() => began++, out failure));
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
            Assert.Equal(DeferredRestart.Hold.RemodelRun, save.Result.Item2);
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
    [InlineData("RemodelRun", "RemodelRunning")]
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

    /// <summary>
    /// A restart with the callbacks a test does not care about doing nothing, no remodel run in
    /// progress unless given a reading of one (owner decision 145A), and a ten-minute poll unless
    /// given one.
    /// </summary>
    private static DeferredRestart NewRestart(
        Func<DeferredRestart.Hold> heldBack,
        Action restart,
        Action? restarted = null,
        Action<Exception>? failed = null,
        Action? notAnswered = null,
        TimeSpan? poll = null,
        Func<bool>? busy = null) =>
        new DeferredRestart(
            heldBack,
            busy ?? (() => false),
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
        string provider = "openai", string model = "gpt-5.6", string effort = "high", string? apiKey = null)
    {
        return new Dictionary<string, object?>
        {
            { "provider", provider },
            { "model", model },
            { "effort", effort },
            { "api_key", apiKey },
            { "base_url", null },
            { "gemini_enterprise", null },
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
        }

        public string Root { get; }

        public string SettingsPath { get; }

        public UserSettings Settings { get; }

        public FakeBackend Backend { get; } = new FakeBackend();

        /// <summary>A backend used instead of <see cref="Backend"/>; the one test that asks the real client sets it.</summary>
        public IBackendClient? BackendOverride { get; set; }

        public FakeDump Dump { get; } = new FakeDump();

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

        /// <summary>Whether a remodel run is in progress on the backend, as the add-in answers it.</summary>
        public Func<bool> BackendBusy { get; set; } = () => false;

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
                FollowActiveDocument = () => Interlocked.Increment(ref _followsAsked),
                CurrentDocument = () =>
                {
                    int read = Interlocked.Increment(ref _documentReads);
                    return DocumentAtRead != null ? DocumentAtRead(read) : Document;
                },
                Environment = _ => null,
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
                BackendBusy = () => BackendBusy(),
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

        /// <summary>Builds the start options each restart would be made with; null builds none.</summary>
        public Func<UserSettings, ResolvedApiKey, BackendStartOptions>? Options { get; set; }

        public BackendEndpoint? Endpoint
        {
            get
            {
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

        public ChatSessionHandle CreateSession(NewSessionRequest request)
        {
            lock (_gate)
            {
                _sessions.Add((request, _generation));
                return new ChatSessionHandle("chat-new-" + _sessions.Count, "review-new-" + _sessions.Count);
            }
        }

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
            lock (_gate)
            {
                _restartsAsked++;

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

        public DumpSummary Run(string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
        {
            OnRun?.Invoke();
            Interlocked.Increment(ref _runs);

            // A package to digest: a context review is bound to its package's SHA-256.
            string package = Path.Combine(outputDirectory, "package.json");
            File.WriteAllText(package, "{\"package_id\":\"FICT-package\"}");
            return new DumpSummary(package, components: 12, gaps: 0);
        }
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
