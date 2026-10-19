using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
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
/// The fakes run with no SOLIDWORKS, no Python and no provider; the one test that reads the
/// backend's real answer to "is a turn running" uses the real <see cref="BackendClient"/>
/// against a loopback listener, as <see cref="BackendClientSessionBodyTests"/> does.
/// </summary>
public sealed class DeferredRestartTests
{
    /// <summary>The Review tab's sentence for a save a turn started during, pinned word for word.</summary>
    private const string Promise = "the settings are saved; the backend restarts when the running turn ends.";

    /// <summary>A new review refused while a turn still runs and a restart waits for it.</summary>
    private const string TurnStillRunning =
        "the backend restarts with the saved settings when the running turn ends, and nothing new "
        + "starts before then. Wait for the turn to end, or stop it, then try again.";

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

        // One message after the restart, and nothing else: the promise is the only status.
        Assert.Equal("backend.restarted", world.Types().Last());
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
        using (var stub = new StubBackend())
        using (var supervisor = new BackendSupervisor(() => false))
        {
            stub.PrintsHandshake(server.Port);
            var options = new BackendStartOptions(stub.Command, stub.LogPath)
            {
                RunRoot = stub.RunRoot,
                AllowOrigin = "https://swreview.invalid",
                HealthProbe = (origin, token) => true,
                StopGrace = TimeSpan.FromMilliseconds(100),
            };
            foreach (KeyValuePair<string, string> knob in stub.Knobs)
            {
                options.Environment[knob.Key] = knob.Value;
            }

            supervisor.Start(options);
            using (var client = new BackendClient(supervisor, Path.GetDirectoryName(stub.LogPath)!, null))
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

    [Fact]
    public void SeveralSavesDuringOneTurnRestartTheBackendOnceWithTheLastOfThem()
    {
        using var world = new RestartWorld();
        world.Open();
        world.Track("chat-1");
        SaveAsATurnStarts(world, "first", Save(effort: "low"));

        // A second save during the same turn gets past the save's own check only when that check
        // cannot see the turn - a question the backend does not answer reads as "no turn"
        // (ReviewHost.AnyTurnRunning) - and the backend's own check still refuses it.
        world.Backend.QuestionFailure = new BackendRequestException(
            "BackendUnavailable", "the review backend did not answer", retryable: true);
        world.Receive("settings.save", "second", Save(model: "gpt-5.6-mini", effort: "medium"));
        world.Backend.QuestionFailure = null;

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
        Assert.Equal(TurnStillRunning, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
        Assert.Empty(world.Backend.Restarts);

        // The refusal leaves the restart waiting, and it is made when the turn ends.
        world.Backend.EndTurn("chat-1");
        Eventually(() => world.Posted("backend.restarted").Length == 1, "backend.restarted");
        Assert.Single(world.Backend.Restarts);
    }

    [Fact]
    public async Task ANewReviewWhileTheRestartIsBeingMadeWaitsForItAndRunsOnTheNewBackend()
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

            Task start = Task.Run(() => world.Receive("review.start", "start", new { }));
            Assert.False(await Finishes(start, TimeSpan.FromMilliseconds(300)), "the review did not wait for the restart being made");
            Assert.Empty(world.Backend.Sessions);

            hold.Set();
            Assert.True(await Finishes(start, TimeSpan.FromSeconds(10)), "the review never went on after the restart");
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
        JsonElement status = world.Last("status");
        Assert.Equal("error", status.GetProperty("stage").GetString());
        Assert.Equal(Failure, status.GetProperty("message").GetString());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.Backend.Sessions);
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

        JsonElement reported = world.Last("status");
        Assert.Equal("error", reported.GetProperty("stage").GetString());
        Assert.Equal(failure, reported.GetProperty("message").GetString());
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
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(2), "disposing the host waited " + clock.Elapsed);

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

    // ---- the restart itself, with no host ------------------------------------------------------

    [Fact]
    public async Task TwoCallersOfOneWaitingRestartRestartTheBackendOnce()
    {
        int restarts = 0;
        using var entered = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        using var restart = new DeferredRestart(
            () => false,
            () =>
            {
                Interlocked.Increment(ref restarts);
                entered.Set();
                release.Wait(TimeSpan.FromSeconds(10));
            },
            () => { },
            _ => { },
            TimeSpan.FromMinutes(10));
        try
        {
            Assert.False(restart.Now(() => throw new TurnRunningException()));
            Assert.True(restart.Pending);

            Task<DeferredRestart.Outcome> first = Task.Run(() => restart.Apply(out _));
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the first caller never began the restart");
            Task<DeferredRestart.Outcome> second = Task.Run(() => restart.Apply(out _));
            Assert.False(await Finishes(second, TimeSpan.FromMilliseconds(300)), "the second caller did not wait for the restart being made");

            release.Set();
            Assert.True(await Finishes(first, TimeSpan.FromSeconds(10)) && await Finishes(second, TimeSpan.FromSeconds(10)));
            Assert.Equal(DeferredRestart.Outcome.Restarted, await first);
            Assert.Equal(DeferredRestart.Outcome.NotPending, await second);
            Assert.Equal(1, restarts);
            Assert.False(restart.Pending);
        }
        finally
        {
            release.Set();
        }
    }

    [Fact]
    public void WhileATurnRunsApplyAnswersAtOnceAndTriesNothing()
    {
        int tried = 0;
        using var restart = new DeferredRestart(
            () => true, () => tried++, () => { }, _ => { }, TimeSpan.FromMinutes(10));
        Assert.False(restart.Now(() => throw new TurnRunningException()));

        Assert.Equal(DeferredRestart.Outcome.TurnRunning, restart.Apply(out Exception? failure));
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
        using var restart = new DeferredRestart(
            () => false,
            () => throw new TurnRunningException(),
            () => reported++,
            _ => reported++,
            TimeSpan.FromMinutes(10));
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
        using var restart = new DeferredRestart(
            () => throw new InvalidOperationException("FICT the backend did not answer"),
            () =>
            {
                if (backendSeesATurn)
                {
                    throw new TurnRunningException();
                }

                restarted++;
            },
            () => { },
            _ => { },
            TimeSpan.FromMinutes(10));
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
        using var restart = new DeferredRestart(
            () => false, () => { }, () => { }, _ => { }, TimeSpan.FromMinutes(10));
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        Assert.True(restart.Pending);

        var failure = new BackendStartException("FICT the backend would not start");
        Assert.Same(failure, Assert.Throws<BackendStartException>(() => restart.Now(() => throw failure)));
        Assert.False(restart.Pending);
    }

    [Fact]
    public void DisposeWakesTheWatcherAtOnceAndNothingRestartsAfterIt()
    {
        int tried = 0;
        var restart = new DeferredRestart(
            () => false, () => tried++, () => { }, _ => { }, TimeSpan.FromMinutes(10));
        Assert.False(restart.Now(() => throw new TurnRunningException()));
        Assert.True(restart.Pending);

        // The watcher is asleep for a ten-minute poll; disposing wakes it rather than outwaiting it.
        var clock = Stopwatch.StartNew();
        restart.Dispose();
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(1), "disposing waited " + clock.Elapsed);

        Assert.Equal(DeferredRestart.Outcome.Stopped, restart.Apply(out _));
        Assert.False(restart.Pending);
        Assert.Equal(0, tried);
        restart.Dispose();
    }

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

    /// <summary>Whether <paramref name="task"/> finishes within <paramref name="bound"/>.</summary>
    private static async Task<bool> Finishes(Task task, TimeSpan bound) =>
        await Task.WhenAny(task, Task.Delay(bound)) == task;

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

    /// <summary>The settings file, a host over the fakes, and what it posted, torn down together.</summary>
    private sealed class RestartWorld : IDisposable
    {
        private readonly FakeChannel _channel = new FakeChannel();
        private ReviewHost? _host;

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

        public PageDocument? Document { get; set; } = new PageDocument(@"C:\Fictional\FICT-bracket\FICT-bracket.SLDASM", "Default");

        /// <summary>How often the host asks whether the turn has ended; short, so the tests are.</summary>
        public TimeSpan Poll { get; set; } = TimeSpan.FromMilliseconds(10);

        public ReviewHost Host => _host ?? throw new InvalidOperationException("call Open() first");

        public void Open()
        {
            if (!File.Exists(SettingsPath))
            {
                Settings.Save(SettingsPath);
            }

            _host = new ReviewHost(new ReviewHostOptions(_channel, BackendOverride ?? Backend, SettingsPath)
            {
                BuildMode = BuildMode.Development,
                LogFolder = Path.Combine(Root, "logs"),
                CurrentDocument = () => Document,
                Environment = _ => null,
                Dump = Dump,
                Engineer = "FICT-engineer",
                Now = () => Stamp,
                RestartPoll = Poll,
            });
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
        private int _generation;
        private int _questions;
        private int _attempts;

        /// <summary>Thrown by each restart the backend's own check lets through.</summary>
        public Exception? RestartFailure { get; set; }

        /// <summary>Thrown by the turn question, as a backend that does not answer makes it throw.</summary>
        public Exception? QuestionFailure { get; set; }

        /// <summary>Runs inside the model-list round trip a save makes between its check and its restart.</summary>
        public Action? DuringModelList { get; set; }

        /// <summary>When set, a restart past the backend's own check waits on it: a restart being made.</summary>
        public ManualResetEventSlim? Hold { get; set; }

        /// <summary>Set once a restart has got past the backend's own check.</summary>
        public ManualResetEventSlim Entered { get; } = new ManualResetEventSlim(false);

        /// <summary>Builds the start options each restart would be made with; null builds none.</summary>
        public Func<UserSettings, ResolvedApiKey, BackendStartOptions>? Options { get; set; }

        public BackendEndpoint? Endpoint
        {
            get
            {
                lock (_gate)
                {
                    return new BackendEndpoint(52000 + _generation, "FICT-token-" + _generation);
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
                if (QuestionFailure == null)
                {
                    return _running.Contains(chatId);
                }
            }

            throw QuestionFailure;
        }

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
                // The backend's own check, made before anything is stopped.
                if (_running.Count > 0)
                {
                    throw new TurnRunningException();
                }

                _attempts++;
            }

            Entered.Set();
            Hold?.Wait(TimeSpan.FromSeconds(15));

            lock (_gate)
            {
                if (RestartFailure != null)
                {
                    throw RestartFailure;
                }

                if (Options != null)
                {
                    _started.Add(Options(settings, key));
                }

                _restarts.Add((settings, key));
                _generation++;
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
                    byte[] body = Encoding.UTF8.GetBytes(known
                        ? "{\"chat_id\":\"" + _chatId + "\",\"state\":\"" + _state + "\"}"
                        : "{\"error_class\":\"UnknownChat\",\"message\":\"no such chat\",\"retryable\":false}");
                    context.Response.StatusCode = known ? 200 : 404;
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

        public DumpSummary Run(string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
        {
            Interlocked.Increment(ref _runs);
            return new DumpSummary(Path.Combine(outputDirectory, "package.json"), components: 12, gaps: 0);
        }
    }
}
