using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using SwReview.AddIn.Model;
using SwReview.AddIn.Review;
using SwReview.AddIn.Standards;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 157A, the check tabs' half: a Model check or a Standards check holds a settings restart back, as a
/// remodel run does since 145A, from its press until the page's evaluation of it has been answered.
///
/// Every case runs on both tabs, against the hosts with a fake gate in place of the review host's - which
/// <see cref="DeferredRestartTests"/> pins, with both tabs bound to the real one - and a clock only the test moves.
/// What they pin:
/// 1. <b>The gate comes after every refusal that needs no call</b> - the run root, the document, the dump, the kind,
///    the profile - so a press refused on the spot makes no restart; and before anything is made, so a press the gate
///    refuses makes nothing. The page is told first when a settings restart stands before the press.
/// 2. <b>The gate can wait through a restart</b>, which can move the run root and in which the engineer can make
///    another document active: both are read again once it is passed, and a press whose run root moved is judged
///    again, one whose document changed refused.
/// 3. <b>The hold</b>: from the gate's step through the extraction and the hand-over of the run to the page, until the
///    page's evaluation, held by the pane's proxy while it is out, has been answered - or, for a page that never
///    evaluates, until the hand-over's limit; every other way out of a start lets it go, and a hold let go late never
///    ends another check's.
/// </summary>
public sealed class CheckHoldTests
{
    private static readonly DateTime Stamp = new DateTime(2026, 10, 21, 9, 30, 0);

    public static IEnumerable<object[]> Tabs() => new[]
    {
        new object[] { "Model check" },
        new object[] { "Standards" },
    };

    // ---- 1. the gate comes after every refusal that needs no call ------------------------------

    /// <summary>
    /// A press that passes every refusal that needs no call begins through the gate once, and before anything is
    /// made: no folder, no extraction and no status of one when the gate is asked. Its step marks the check in
    /// progress, under the gate.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void APressBeginsThroughTheGateOnceBeforeAnythingIsMade(string tab)
    {
        using var world = new HoldWorld(tab);
        world.AtTheGate = () =>
        {
            Assert.Empty(world.RunFolders());
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.AllPosted("status"));
            Assert.False(world.CheckInProgress);
        };
        world.Open();

        world.Press("c1");

        Assert.Equal(1, world.GateAsked);
        Assert.True(world.InProgressAfterTheStep);
        world.Extracted("c1");
    }

    /// <summary>
    /// A press refused on the spot - for its run root, its document, a dump not attached, the kind of its document, or
    /// on the Standards tab its profile - asks no gate, so it makes no settings restart, and holds nothing.
    /// </summary>
    [Theory]
    [InlineData("Model check", "a run root the rule refuses")]
    [InlineData("Standards", "a run root the rule refuses")]
    [InlineData("Model check", "a run root moving with a start under way")]
    [InlineData("Standards", "a run root moving with a start under way")]
    [InlineData("Model check", "no document")]
    [InlineData("Standards", "no document")]
    [InlineData("Model check", "not attached")]
    [InlineData("Standards", "not attached")]
    [InlineData("Model check", "an assembly")]
    [InlineData("Standards", "a document never saved")]
    [InlineData("Standards", "no profile")]
    public void APressRefusedOnTheSpotAsksNoGate(string tab, string refused)
    {
        using var world = new HoldWorld(tab);
        switch (refused)
        {
            case "a run root the rule refuses":
                var refusing = FakeRunRootProbe.Refusing("on a share", world.RunRoot);
                world.RunRootSpelling = refusing.RunRoot;
                world.Probe = refusing.Probe;
                break;
            case "a run root moving with a start under way":
                world.RunRootForANewRun = () => null;
                break;
            case "no document":
                world.Document = null;
                break;
            case "not attached":
                world.UseDump = false;
                break;
            case "an assembly":
                world.Document = new PageDocument(@"C:\Fictional\FICT-frame\FICT-frame.SLDASM", "Default");
                break;
            case "a document never saved":
                world.Document = new PageDocument(string.Empty, "Default");
                break;
            case "no profile":
                world.ProfilePath = null;
                break;
        }

        world.Open();

        world.Press("c1");

        world.Reply("error", "c1");
        Assert.Equal(0, world.GateAsked);
        Assert.False(world.CheckInProgress);
        Assert.Equal(0, world.Dump.Runs);
    }

    /// <summary>
    /// A press the gate refuses - what holds the restart back, or the restart's failure - is answered with the gate's
    /// class, words and flag, and nothing else happens: no folder, no extraction, no status, nothing held.
    /// </summary>
    [Theory]
    [InlineData("Model check", "TurnRunning", true)]
    [InlineData("Standards", "CheckRunning", true)]
    [InlineData("Model check", "BackendUnavailable", false)]
    public void APressTheGateRefusesIsAnsweredWithTheRefusalAndMakesNothing(string tab, string errorClass, bool retryable)
    {
        using var world = new HoldWorld(tab);
        world.GateRefusal = new BackendRequestException(errorClass, "FICT what holds the restart back", retryable);
        world.Open();

        world.Press("c1");

        JsonElement error = world.Reply("error", "c1");
        Assert.Equal(errorClass, error.GetProperty("error_class").GetString());
        Assert.Equal("FICT what holds the restart back", error.GetProperty("message").GetString());
        Assert.Equal(retryable, error.GetProperty("retryable").GetBoolean());
        Assert.Equal(1, world.GateAsked);
        Assert.False(world.InProgressAfterTheStep);
        Assert.False(world.CheckInProgress);
        Assert.Empty(world.RunFolders());
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.AllPosted("status"));
        Assert.Empty(world.AllPosted(world.ExtractedType));
    }

    /// <summary>
    /// A gate that refuses the press after running its step - which the review host's never does, since a refusal
    /// there runs no step - still leaves nothing held: the press is refused, and nothing holds the restart back.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AGateThatRefusesAfterItsStepLeavesNothingHeld(string tab)
    {
        using var world = new HoldWorld(tab);
        world.GateRefusal = new BackendRequestException("TurnRunning", "FICT a turn holds the restart back", retryable: true);
        world.GateRefusesAfterTheStep = true;
        world.Open();

        world.Press("c1");

        Assert.Equal("TurnRunning", world.Reply("error", "c1").GetProperty("error_class").GetString());
        Assert.True(world.InProgressAfterTheStep);
        Assert.False(world.CheckInProgress);
        Assert.Equal(0, world.Dump.Runs);
    }

    /// <summary>
    /// A gate that throws - whether or not it ran the step - leaves the tab holding nothing, so one failure cannot
    /// hold every later restart back for good; the throw is the press's answer, as any failure of a start is.
    /// </summary>
    [Theory]
    [InlineData("Model check", true)]
    [InlineData("Standards", false)]
    public void AGateThatThrowsLeavesNothingHeld(string tab, bool afterTheStep)
    {
        using var world = new HoldWorld(tab);
        world.GateFailure = new InvalidOperationException("FICT the gate broke");
        world.GateFailsAfterTheStep = afterTheStep;
        world.Open();

        world.Press("c1");

        JsonElement error = world.Reply("error", "c1");
        Assert.Equal("HostError", error.GetProperty("error_class").GetString());
        Assert.False(world.CheckInProgress);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.RunFolders());
    }

    /// <summary>
    /// A press with a settings restart ahead - one waits, or one is being made - tells the page so before the gate, in
    /// this tab's words, as `status {stage: "backend_starting"}`: the gate can wait through the restart for seconds,
    /// in which the page would otherwise say only what the press set. Nothing is said with none ahead, nor for a press
    /// refused on the spot.
    /// </summary>
    [Theory]
    [InlineData("Model check", "Waiting for the review backend to restart with the saved settings, then reading the feature tree...")]
    [InlineData("Standards", "Waiting for the review backend to restart with the saved settings, then reading the document...")]
    public void WithARestartAheadThePageIsToldBeforeTheGate(string tab, string waiting)
    {
        using var world = new HoldWorld(tab);
        world.RestartAhead = true;
        JsonElement[] toldAtTheGate = new JsonElement[0];
        world.AtTheGate = () => toldAtTheGate = world.AllPosted("status");
        world.Open();

        world.Press("c1");

        JsonElement told = Assert.Single(toldAtTheGate);
        Assert.Equal("backend_starting", told.GetProperty("stage").GetString());
        Assert.Equal(waiting, told.GetProperty("message").GetString());

        world.RestartAhead = false;
        world.Press("c2");
        Assert.Single(world.AllPosted("status"), status => status.GetProperty("stage").GetString() == "backend_starting");

        world.RestartAhead = true;
        world.Document = null;
        world.Press("c3");
        world.Reply("error", "c3");
        Assert.Single(world.AllPosted("status"), status => status.GetProperty("stage").GetString() == "backend_starting");
    }

    // ---- 2. what the gate's wait can move is read again once it is passed ------------------------

    /// <summary>
    /// The gate can make a waiting settings restart, which can bring another run root into force: the run root is read
    /// again once the gate is passed, and one that moved is judged again before anything is made under it - refused,
    /// the press is answered and holds nothing; accepted, the run's folder is made under it - and while a start of the
    /// backend under way would bring another in, the press is answered as a press then is.
    /// </summary>
    [Theory]
    [InlineData("Model check", "moved to a folder the rule refuses")]
    [InlineData("Standards", "moved to a folder the rule refuses")]
    [InlineData("Model check", "moved to a folder the rule accepts")]
    [InlineData("Standards", "moved to a folder the rule accepts")]
    [InlineData("Model check", "moving with a start under way")]
    [InlineData("Standards", "moving with a start under way")]
    public void TheRunRootIsReadAgainOnceTheGateIsPassedAndAMoveIsJudgedAgain(string tab, string after)
    {
        using var world = new HoldWorld(tab);
        string moved = Path.Combine(world.Root, "moved", "runs");
        var refusing = FakeRunRootProbe.Refusing("a name ending in a period", moved);
        if (after == "moved to a folder the rule refuses")
        {
            moved = refusing.RunRoot;
            world.Probe = refusing.Probe;
        }

        bool gatePassed = false;
        world.AtTheGate = () => gatePassed = true;
        world.RunRootForANewRun = () => !gatePassed ? world.RunRoot : after == "moving with a start under way" ? null : moved;
        world.Open();

        world.Press("c1");

        if (after == "moved to a folder the rule accepts")
        {
            string runDirectory = world.Extracted("c1");
            Assert.Equal(moved, Path.GetDirectoryName(runDirectory));
            Assert.True(world.CheckInProgress);
            return;
        }

        JsonElement error = world.Reply("error", "c1");
        if (after == "moving with a start under way")
        {
            Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
            Assert.Equal(RunRootRule.MovingRefusal("nothing was checked", world.PressAgain), error.GetProperty("message").GetString());
        }
        else
        {
            Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
            Assert.Equal(
                RunRootRule.Refusal(refusing.Verdict, "nothing was checked", RunRootRule.InSettingsOnTheReviewTab, world.PressAgain),
                error.GetProperty("message").GetString());
        }

        Assert.False(world.CheckInProgress);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.RunFolders());
        Assert.False(Directory.Exists(moved));
    }

    /// <summary>
    /// The engineer can make another document active while the gate waits through a restart: the document is read
    /// again once the gate is passed, and a press whose document - another, another configuration of it, or none -
    /// changed is refused `DocumentChanged`, retryable, in this tab's words, with no path, before anything is made,
    /// and holds nothing. The same document spelled otherwise is the same, and is checked.
    /// </summary>
    [Theory]
    [InlineData("Model check", "another part", false)]
    [InlineData("Standards", "another document", false)]
    [InlineData("Model check", "another configuration", false)]
    [InlineData("Standards", "none", false)]
    [InlineData("Model check", "the same part spelled otherwise", true)]
    [InlineData("Standards", "the same document spelled otherwise", true)]
    public void ADocumentChangedWhileTheGateWaitedIsRefusedAndMakesNothing(string tab, string change, bool checks)
    {
        using var world = new HoldWorld(tab);
        PageDocument pressed = world.Document!;
        world.AtTheGate = () =>
        {
            switch (change)
            {
                case "another part":
                case "another document":
                    world.Document = new PageDocument(@"C:\Fictional\FICT-hinge\FICT-hinge.SLDPRT", "Default");
                    break;
                case "another configuration":
                    world.Document = new PageDocument(pressed.Path, "FICT-machined");
                    break;
                case "none":
                    world.Document = null;
                    break;
                default:
                    world.Document = new PageDocument(pressed.Path.ToUpperInvariant(), pressed.Configuration);
                    break;
            }
        };
        world.Open();

        world.Press("c1");

        if (checks)
        {
            world.Extracted("c1");
            return;
        }

        JsonElement error = world.Reply("error", "c1");
        Assert.Equal("DocumentChanged", error.GetProperty("error_class").GetString());
        Assert.Equal(world.DocumentChangedWords, error.GetProperty("message").GetString());
        Assert.True(error.GetProperty("retryable").GetBoolean());
        Assert.DoesNotContain("FICT-", error.GetProperty("message").GetString(), StringComparison.Ordinal);
        Assert.False(world.CheckInProgress);
        Assert.Equal(0, world.Dump.Runs);
        Assert.Empty(world.RunFolders());
    }

    // ---- 3. the hold -----------------------------------------------------------------------------

    /// <summary>
    /// The check holds the restart back from the gate's step until the page's evaluation of it has been answered: while
    /// its model is read, once its run is handed to the page, while the evaluation the proxy holds for its folder is
    /// out; and not once that is let go.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ACheckHoldsTheRestartFromItsGateUntilItsEvaluationIsAnswered(string tab)
    {
        using var world = new HoldWorld(tab);
        bool duringTheExtraction = false;
        world.Dump.OnRun = () => duringTheExtraction = world.CheckInProgress;
        world.Open();
        Assert.False(world.CheckInProgress);

        world.Press("c1");

        Assert.True(duringTheExtraction);
        string runDirectory = world.Extracted("c1");
        Assert.True(world.CheckInProgress);
        IDisposable? evaluation = world.HoldEvaluation(runDirectory);
        Assert.NotNull(evaluation);
        Assert.True(world.CheckInProgress);
        world.Advance(CheckHoldOptions.DefaultHandOverLimit + TimeSpan.FromMinutes(5));
        Assert.True(world.CheckInProgress);

        evaluation!.Dispose();

        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// Every way out of a start once the gate is passed, but the hand-over of its run to the page, lets the hold go:
    /// the run folder not made, the extraction failed, the run root moved while the model was read or a start of the
    /// backend under way then, and a failure after the extraction - the press is answered, and nothing holds the
    /// restart back.
    /// </summary>
    [Theory]
    [InlineData("Model check", "the run folder not made")]
    [InlineData("Standards", "the run folder not made")]
    [InlineData("Model check", "the extraction failed")]
    [InlineData("Standards", "the extraction failed")]
    [InlineData("Model check", "the run root moved while the model was read")]
    [InlineData("Standards", "a start under way once the model was read")]
    [InlineData("Model check", "a failure once the model was read")]
    [InlineData("Standards", "a failure once the model was read")]
    public void EveryWayOutOfAStartButTheHandOverLetsTheHoldGo(string tab, string way)
    {
        using var world = new HoldWorld(tab);
        int readings = 0;
        switch (way)
        {
            case "the run folder not made":
                File.WriteAllText(Path.Combine(world.Root, "FICT-a-file"), "not a folder");
                world.RunRootSpelling = Path.Combine(world.Root, "FICT-a-file", "runs");
                break;
            case "the extraction failed":
                world.Dump.Failure = new InvalidOperationException("FICT the dump stopped");
                break;
            case "the run root moved while the model was read":
                world.RunRootForANewRun = () => ++readings <= 2 ? world.RunRoot : Path.Combine(world.Root, "moved", "runs");
                break;
            case "a start under way once the model was read":
                world.RunRootForANewRun = () => ++readings <= 2 ? world.RunRoot : null;
                break;
            case "a failure once the model was read":
                world.Registering = () => throw new InvalidOperationException("FICT the pane could not take the run");
                break;
        }

        world.Open();

        world.Press("c1");

        world.Reply("error", "c1");
        Assert.True(world.InProgressAfterTheStep);
        Assert.False(world.CheckInProgress);
        Assert.Empty(world.AllPosted(world.ExtractedType));
    }

    /// <summary>
    /// Only the evaluation of the run handed to the page is held: one of another folder, one asked for while the model
    /// is still read, and one with no check handed over hold nothing; and one is held once - a second evaluation of the
    /// same run, while the first is out, holds nothing more.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void OnlyTheEvaluationOfTheRunHandedToThePageIsHeldAndOnce(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        Assert.Null(world.HoldEvaluation(Path.Combine(world.RunRoot, "FICT-no-check")));
        string? duringTheExtraction = null;
        IDisposable? heldDuringTheExtraction = null;
        world.Dump.OnRun = () =>
        {
            duringTheExtraction = world.Dump.LastDirectory;
            heldDuringTheExtraction = world.HoldEvaluation(duringTheExtraction!);
        };

        world.Press("c1");

        Assert.Null(heldDuringTheExtraction);
        string runDirectory = world.Extracted("c1");
        Assert.Equal(runDirectory, duringTheExtraction);
        Assert.Null(world.HoldEvaluation(Path.Combine(world.RunRoot, "FICT-another-check")));
        IDisposable? first = world.HoldEvaluation(runDirectory.ToUpperInvariant());
        Assert.NotNull(first);
        Assert.Null(world.HoldEvaluation(runDirectory));
        first!.Dispose();
        first.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// The evaluation of the run handed to the page is held however its folder is spelled as Windows names a folder -
    /// in other letter case, or with a trailing separator of either kind - since it is the same folder.
    /// </summary>
    [Theory]
    [InlineData("Model check", "upper case")]
    [InlineData("Standards", "a trailing backslash")]
    [InlineData("Model check", "a trailing slash")]
    public void AnEvaluationOfTheRunHandedOverIsHeldHoweverItsFolderIsSpelled(string tab, string spelling)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        string spelled = spelling == "upper case" ? runDirectory.ToUpperInvariant()
            : spelling == "a trailing backslash" ? runDirectory + "\\"
            : runDirectory + "/";

        IDisposable? evaluation = world.HoldEvaluation(spelled);

        Assert.NotNull(evaluation);
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A page that never evaluates its check - reloaded, or closed, once its run was handed to it - holds the restart
    /// back for the hand-over's limit and no longer, measured from the hand-over, its reply reaching the page at once
    /// here: a moment short of it the check is in progress, at it not; and an evaluation that comes after the limit,
    /// once a restart has been made, is not held. (Changed deliberately on the reviews of 157A: an evaluation after the
    /// limit is held again while it carries the token of the backend up now, so the restart here is made.)
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AHandOverNotTakenWithinItsLimitHoldsNothingMore(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");

        world.Advance(CheckHoldOptions.DefaultHandOverLimit - TimeSpan.FromTicks(1));
        Assert.True(world.CheckInProgress);
        world.Advance(TimeSpan.FromTicks(1));
        Assert.False(world.CheckInProgress);

        world.Backend = new BackendEndpoint(52001, "FICT-token-1");
        Assert.Null(world.HoldEvaluation(runDirectory));
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// The limit is the tab's own option: shorter or longer, the hand-over waits that long, measured from the hand-over
    /// whenever it is made, and the add-in runs with a minute. Pressed three hours in, as the add-in's clock is long
    /// after its first minute, the check holds the restart while its model is read too: a start's hold has no limit
    /// (owner decision 157A, the reviews: the clock the add-in runs with is a stopwatch started with it, never at zero
    /// when a check is pressed).
    /// </summary>
    [Theory]
    [InlineData("Model check", 5)]
    [InlineData("Standards", 300)]
    public void TheHandOverWaitsAsLongAsItsLimit(string tab, int seconds)
    {
        using var world = new HoldWorld(tab) { HandOverLimit = TimeSpan.FromSeconds(seconds) };
        world.Open();
        world.Advance(TimeSpan.FromHours(3));
        bool whileTheModelIsRead = false;
        world.Dump.OnRun = () => whileTheModelIsRead = world.CheckInProgress;
        world.Press("c1");
        world.Extracted("c1");
        Assert.True(whileTheModelIsRead, "the check held nothing while its model was read, three hours in");

        world.Advance(TimeSpan.FromSeconds(seconds) - TimeSpan.FromTicks(1));
        Assert.True(world.CheckInProgress);
        world.Advance(TimeSpan.FromTicks(1));
        Assert.False(world.CheckInProgress);
        Assert.Equal(TimeSpan.FromSeconds(60), CheckHoldOptions.DefaultHandOverLimit);
    }

    /// <summary>
    /// The clock the add-in runs with - it passes none, so each check host's default is the one in use - goes forward:
    /// a clock that stood still would never let a hand-over's limit pass, and a page that never evaluates would hold
    /// every settings restart back until SOLIDWORKS closed (owner decision 157A, the reviews).
    /// </summary>
    [Fact]
    public void TheClockTheAddInRunsWithMovesAndIsEachCheckHostsDefault()
    {
        var channel = new CollectingChannel(new List<string>());
        Func<string> runRoot = () => @"C:\Fictional\FICT-runs";
        Func<TimeSpan> pane = new CheckPaneHostOptions(channel, runRoot, "check.start", _ => { }).Hold.Clock;
        Func<TimeSpan> model = new ModelCheckHostOptions(channel, runRoot).Hold.Clock;
        Func<TimeSpan> standards = new StandardsHostOptions(channel, runRoot).Hold.Clock;
        TimeSpan[] before = { CheckHoldOptions.MonotonicClock(), pane(), model(), standards() };

        System.Threading.Thread.Sleep(50);

        Assert.True(CheckHoldOptions.MonotonicClock() > before[0], "the add-in's clock did not move");
        Assert.True(pane() > before[1], "the check pane's default clock did not move");
        Assert.True(model() > before[2], "the Model check host's default clock did not move");
        Assert.True(standards() > before[3], "the Standards host's default clock did not move");
    }

    /// <summary>
    /// A page loaded again can press again while the evaluation of the check its predecessor pressed is still out:
    /// both hold the restart back, each let go on its own, and an older one let go late never ends a newer one's hold.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void TwoChecksOfOneTabHoldTheRestartEachUntilItsOwnEnds(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string first = world.Extracted("c1");
        IDisposable? firstEvaluation = world.HoldEvaluation(first);
        Assert.NotNull(firstEvaluation);
        bool afterTheOlderLetGo = false;
        world.Dump.OnRun = () =>
        {
            firstEvaluation!.Dispose();
            afterTheOlderLetGo = world.CheckInProgress;
        };

        world.Press("c2");

        Assert.True(afterTheOlderLetGo);
        string second = world.Extracted("c2");
        Assert.NotEqual(first, second);
        Assert.True(world.CheckInProgress);
        world.HoldEvaluation(second)!.Dispose();
        Assert.False(world.CheckInProgress);

        world.Dump.OnRun = null;
        world.Press("c3");
        IDisposable? third = world.HoldEvaluation(world.Extracted("c3"));
        world.Dump.Failure = new InvalidOperationException("FICT the dump stopped");
        world.Press("c4");
        world.Reply("error", "c4");
        Assert.True(world.CheckInProgress);
        third!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>Disposing the host - the add-in unloading - lets every hold go.</summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void DisposingTheHostLetsEveryHoldGo(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        IDisposable? evaluation = world.HoldEvaluation(world.Extracted("c1"));
        world.Press("c2");
        world.Extracted("c2");
        Assert.True(world.CheckInProgress);

        world.DisposeHost();

        Assert.False(world.CheckInProgress);
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    // ---- 4. the hand-over's minute, and an evaluation held up past it (the reviews of 157A) -----------

    /// <summary>
    /// A run's minute starts once its reply has reached the page: in the add-in the reply waits on SOLIDWORKS'
    /// application thread, which another tab's extraction holds for its whole length, and until it is delivered the
    /// page cannot read it, let alone evaluate. The check holds the restart however long that takes, up to the delivery
    /// limit, and its page has its whole minute once it has the reply (the reviews of 157A: the race review, Codex and
    /// the mutation review). (Changed deliberately on the final reviews of 157A: the reply waits fifty-nine minutes
    /// here, where it waited an hour, since an undelivered hand-over now holds an hour at most.)
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AHandOversMinuteStartsOnceItsReplyHasReachedThePage(string tab)
    {
        using var world = new HoldWorld(tab) { HoldDelivery = true };
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");

        world.Advance(TimeSpan.FromMinutes(59));
        Assert.True(world.CheckInProgress, "a reply not yet delivered let the restart go");

        world.Deliver();
        world.Advance(CheckHoldOptions.DefaultHandOverLimit - TimeSpan.FromTicks(1));
        Assert.True(world.CheckInProgress);
        IDisposable? evaluation = world.HoldEvaluation(runDirectory);
        Assert.NotNull(evaluation);
        Assert.Equal(0, world.WhileNoRestartRunsAsked);
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// The minute runs out once the reply has been delivered and no evaluation came: a page that has gone frees the
    /// restart a minute after its reply reached it. A delivery that cannot be awaited - the pane cannot queue behind its
    /// posts - starts the minute at the hand-over, so nothing waits for good on a mark that never comes.
    /// </summary>
    [Theory]
    [InlineData("Model check", false)]
    [InlineData("Standards", false)]
    [InlineData("Model check", true)]
    [InlineData("Standards", true)]
    public void AHandOverNotTakenWithinItsMinuteOfDeliveryHoldsNothingMore(string tab, bool deliveryFails)
    {
        using var world = new HoldWorld(tab) { HoldDelivery = !deliveryFails, AfterPostsFails = deliveryFails };
        world.Open();
        world.Press("c1");
        world.Extracted("c1");
        world.Advance(TimeSpan.FromMinutes(10));
        world.Deliver();

        world.Advance(deliveryFails ? TimeSpan.Zero : CheckHoldOptions.DefaultHandOverLimit);

        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// An evaluation that reaches the proxy after its run's minute - its page held up once it had the reply, behind
    /// SOLIDWORKS' application thread - takes its check's hold back while the token it carries is the token of the
    /// backend up now, the backend that will answer it: it is held as it would have been in its minute, so a restart
    /// waiting meanwhile waits for it. Decided while no restart can begin or be made, once. (Renamed deliberately on
    /// the final reviews of 157A, from `AnEvaluationHeldUpPastItsMinuteIsHeldWhileTheBackendItBeganOnIsUp`: the rule
    /// reads the evaluation's own token now, not the backend at the check's gate.)
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AnEvaluationHeldUpPastItsMinuteIsHeldWhileItCarriesTheTokenOfTheBackendUpNow(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        Assert.False(world.CheckInProgress);

        IDisposable? evaluation = world.HoldEvaluation(runDirectory);

        Assert.NotNull(evaluation);
        Assert.Equal(1, world.WhileNoRestartRunsAsked);
        Assert.True(world.CheckInProgress);
        Assert.Null(world.HoldEvaluation(runDirectory));
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
        evaluation.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// ...but not unless it carries the token of the backend up now: once a restart has been made, on another port or
    /// the same, or the backend has stopped, the evaluation carries the token of a backend that has gone and is refused
    /// as any call to a backend that stopped is, so holding it would only hold the next restart back; nor an evaluation
    /// that carries the token in other letters, which the backend, comparing it exactly, refuses too; nor one that
    /// carries no token, which waits for no restart in flight to be told so; nor once the restart can no longer be
    /// asked, stopping with the add-in, nor when asking it throws. The evaluation goes on unheld, as before 157A.
    /// (Renamed deliberately on the final reviews of 157A, from
    /// `AnEvaluationPastItsMinuteIsNotHeldOnceTheBackendItBeganOnHasGone`, with three rows more.)
    /// </summary>
    [Theory]
    [InlineData("Model check", "a restart was made")]
    [InlineData("Standards", "a restart was made")]
    [InlineData("Standards", "a restart was made on the same port")]
    [InlineData("Model check", "the backend stopped")]
    [InlineData("Standards", "the evaluation carries the token in other letters")]
    [InlineData("Model check", "the evaluation carries no token")]
    [InlineData("Standards", "stopping with the add-in")]
    [InlineData("Model check", "the restart cannot be asked")]
    public void AnEvaluationPastItsMinuteIsNotHeldUnlessItCarriesTheTokenOfTheBackendUpNow(string tab, string why)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        if (why == "a restart was made")
        {
            world.Backend = new BackendEndpoint(52001, "FICT-token-1");
        }
        else if (why == "a restart was made on the same port")
        {
            world.Backend = new BackendEndpoint(52000, "FICT-token-1");
        }
        else if (why == "the backend stopped")
        {
            world.Backend = null;
        }
        else if (why == "the evaluation carries the token in other letters")
        {
            world.PageToken = "fict-TOKEN-0";
        }
        else if (why == "the evaluation carries no token")
        {
            world.PageToken = null;
        }

        world.Stopping = why == "stopping with the add-in";
        world.WhileNoRestartRunsFails = why == "the restart cannot be asked";

        Assert.Null(world.HoldEvaluation(runDirectory));
        Assert.False(world.CheckInProgress);
        if (why == "the evaluation carries no token")
        {
            Assert.Equal(0, world.WhileNoRestartRunsAsked);
        }
    }

    /// <summary>
    /// A hold whose minute has passed stays to be taken back until the delivery limit after its hand-over: the tab's
    /// next press - a page that was not gone after all, pressing again - neither drops it nor is held up by it, and the
    /// evaluation it was handed over for is still held when it comes. (Renamed deliberately on the final reviews of
    /// 157A, from `AHoldPastItsMinuteOutlivesTheTabsNextPressWhileItsBackendIsUp`: what keeps it is now its age.)
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AHoldPastItsMinuteOutlivesTheTabsNextPress(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string first = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);

        world.Press("c2");
        string second = world.Extracted("c2");

        IDisposable? late = world.HoldEvaluation(first);
        Assert.NotNull(late);
        IDisposable? inTime = world.HoldEvaluation(second);
        Assert.NotNull(inTime);
        late!.Dispose();
        Assert.True(world.CheckInProgress);
        inTime!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A page loaded again presses again while the run its predecessor was handed waits for its evaluation: the tab's
    /// next press lets go of nothing but its own hold - refused by the gate, or failing once past it - and the hand-over
    /// before it still holds the restart and is held when its evaluation comes (the reviews of 157A: the mutation
    /// review's P3).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AHandOverWaitingForItsPageOutlivesTheTabsNextPress(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string first = world.Extracted("c1");

        world.GateRefusal = new BackendRequestException("CheckRunning", "FICT a check holds the restart back", retryable: true);
        world.Press("c2");
        world.Reply("error", "c2");
        Assert.True(world.CheckInProgress, "a press the gate refused let go of the hand-over before it");

        world.GateRefusal = null;
        world.Dump.Failure = new InvalidOperationException("FICT the dump stopped");
        world.Press("c3");
        world.Reply("error", "c3");
        Assert.True(world.CheckInProgress, "a press that failed past its gate let go of the hand-over before it");

        IDisposable? evaluation = world.HoldEvaluation(first);
        Assert.NotNull(evaluation);
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// The run is handed over before the page is told: an evaluation the page sends the instant it reads the reply finds
    /// its hold (the reviews of 157A: the mutation review's P4).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AnEvaluationSentTheInstantThePageIsToldFindsItsHold(string tab)
    {
        using var world = new HoldWorld(tab);
        IDisposable? held = null;
        world.OnPosted = json =>
        {
            JsonElement root = JsonDocument.Parse(json).RootElement;
            if (root.GetProperty("type").GetString() == world.ExtractedType)
            {
                held = world.HoldEvaluation(root.GetProperty("payload").GetProperty("run_dir").GetString()!);
            }
        };
        world.Open();

        world.Press("c1");

        Assert.NotNull(held);
        Assert.True(world.CheckInProgress);
        held!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A reading of whether a restart stands before the press that throws is read as none: only the page's words hang on
    /// it, and the gate, which decides, is asked as ever (the reviews of 157A: the mutation review's RV6).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ARestartAheadThatCannotBeReadTellsThePageNothing(string tab)
    {
        using var world = new HoldWorld(tab) { RestartAheadFails = true };
        world.Open();

        world.Press("c1");

        world.Extracted("c1");
        Assert.Equal(1, world.GateAsked);
        Assert.DoesNotContain(world.AllPosted("status"), status => status.GetProperty("stage").GetString() == "backend_starting");
    }

    // ---- 5. the final reviews of 157A ------------------------------------------------------------------

    /// <summary>
    /// A check pressed with no backend up holds nothing then, but its page, told the backend came up during the
    /// extraction, evaluates with that backend's token: held up past its minute, the evaluation takes its hold back,
    /// since that backend will answer it (the final reviews of 157A: the race review's rule, the evaluation's own
    /// token).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ALateEvaluationOfACheckBegunWithNoBackendIsHeldOnTheBackendThatCameUp(string tab)
    {
        using var world = new HoldWorld(tab) { Backend = null };
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        world.Backend = new BackendEndpoint(52003, "FICT-token-3");
        world.PageToken = "FICT-token-3";

        IDisposable? evaluation = world.HoldEvaluation(runDirectory);

        Assert.NotNull(evaluation);
        Assert.True(world.CheckInProgress);
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A check pressed with no backend up, past its minute once a backend has come up, breaks nothing: the tab's next
    /// press is answered as ever (the final reviews of 157A, the mutation review's Z3, which made it throw).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ACheckBegunWithNoBackendDoesNotBreakTheTabsNextPress(string tab)
    {
        using var world = new HoldWorld(tab) { Backend = null };
        world.Open();
        world.Press("c1");
        world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        world.Backend = new BackendEndpoint(52000, "FICT-token-0");

        world.Press("c2");

        world.Extracted("c2");
        Assert.Empty(world.AllPosted("error"));
    }

    /// <summary>
    /// A hold in its minute is not forgotten by the tab's next press, whatever backend is up by then: its evaluation is
    /// still held (the final reviews of 157A, the mutation review's Z13).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AHoldInItsMinuteIsNotForgottenByTheTabsNextPress(string tab)
    {
        using var world = new HoldWorld(tab) { Backend = null };
        world.Open();
        world.Press("c1");
        string first = world.Extracted("c1");
        world.Backend = new BackendEndpoint(52000, "FICT-token-0");

        world.Press("c2");

        IDisposable? evaluation = world.HoldEvaluation(first);
        Assert.NotNull(evaluation);
        evaluation!.Dispose();
    }

    /// <summary>
    /// An evaluation held up past its minute that arrives while a restart is being made reads the backend that restart
    /// leaves, since it reads it while no restart runs: it carries the old backend's token, and is not held (the final
    /// reviews of 157A, the mutation review's Z7, by a handshake: read before the restart's lock, the backend is read
    /// at once, while the restart is still in flight).
    /// </summary>
    [Fact]
    public void ALateEvaluationReadsTheBackendOnlyWhileNoRestartRuns()
    {
        using var world = new HoldWorld("Model check") { RestartLock = new object() };
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        using var inFlight = new ManualResetEventSlim(false);
        using var letGo = new ManualResetEventSlim(false);
        using var readByTheEvaluation = new ManualResetEventSlim(false);
        int evaluationThread = -1;
        world.BackendRead = () =>
        {
            if (Thread.CurrentThread.ManagedThreadId == Volatile.Read(ref evaluationThread))
            {
                readByTheEvaluation.Set();
            }
        };
        var restart = new Thread(() =>
        {
            lock (world.RestartLock)
            {
                inFlight.Set();
                letGo.Wait(TimeSpan.FromSeconds(10));
                world.Backend = new BackendEndpoint(52001, "FICT-token-1");
            }
        });
        restart.Start();
        Assert.True(inFlight.Wait(TimeSpan.FromSeconds(10)), "the restart never began");
        IDisposable? held = null;
        var evaluation = new Thread(() =>
        {
            Volatile.Write(ref evaluationThread, Thread.CurrentThread.ManagedThreadId);
            held = world.HoldEvaluation(runDirectory);
        });
        evaluation.Start();

        bool readDuringTheRestart = readByTheEvaluation.Wait(TimeSpan.FromSeconds(2));
        letGo.Set();
        Assert.True(restart.Join(TimeSpan.FromSeconds(10)), "the restart never ended");
        Assert.True(evaluation.Join(TimeSpan.FromSeconds(10)), "the evaluation never ended");

        Assert.False(readDuringTheRestart, "the evaluation read the backend while a restart was being made");
        Assert.Null(held);
    }

    /// <summary>
    /// Two evaluations of one run, both past its minute and racing, are held once: the second, taken back while the
    /// first waited for no restart to run, leaves the first nothing, read again under the restart's lock (the final
    /// reviews of 157A, the mutation review's Z4).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void TwoLateEvaluationsOfOneRunAreHeldOnce(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        IDisposable? second = null;
        world.BeforeTheStep = () =>
        {
            world.BeforeTheStep = null;
            second = world.HoldEvaluation(runDirectory);
        };

        IDisposable? first = world.HoldEvaluation(runDirectory);

        Assert.Null(first);
        Assert.NotNull(second);
        Assert.True(world.CheckInProgress);
        second!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// An evaluation past its minute whose hold went while it waited for no restart to run - the host disposed with
    /// the add-in - is not held: its hold is read again under the restart's lock (the final reviews of 157A, Z5).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ALateEvaluationWhoseHoldWentMeanwhileIsNotHeld(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        world.BeforeTheStep = world.DisposeHost;

        Assert.Null(world.HoldEvaluation(runDirectory));
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A mark of delivery that comes twice - queued, and run at once too because the queuing then threw - starts the
    /// minute once: the second does not start it again (the final reviews of 157A, the mutation review's Z17).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ASecondMarkOfDeliveryDoesNotStartTheMinuteAgain(string tab)
    {
        using var world = new HoldWorld(tab) { AfterPostsQueuesAndFails = true };
        world.Open();
        world.Press("c1");
        world.Extracted("c1");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);
        Assert.False(world.CheckInProgress);

        world.Deliver();

        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A gate that lets a press through without running its step - the review host's never does - leaves the check
    /// holding nothing, and breaks nothing: the run is handed to the page as ever (the final reviews of 157A, Z63).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AGateThatLetsAPressThroughWithoutItsStepHoldsNothing(string tab)
    {
        using var world = new HoldWorld(tab) { GateSkipsTheStep = true };
        world.Open();

        world.Press("c1");

        world.Extracted("c1");
        Assert.Empty(world.AllPosted("error"));
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// The hold's defaults, for a tab the add-in has not given its own: what is queued behind the posts runs at once,
    /// and a step run while no restart runs runs at once, its answer the step's (the final reviews of 157A, Z34, Z35).
    /// </summary>
    [Fact]
    public void TheHoldsDefaultsDeliverAndRunTheStepAtOnce()
    {
        var hold = new CheckHoldOptions();
        int delivered = 0;

        hold.AfterPosts(() => delivered++);

        Assert.Equal(1, delivered);
        Assert.True(hold.WhileNoRestartRuns(() => true));
        Assert.False(hold.WhileNoRestartRuns(() => false));
    }

    /// <summary>
    /// A run root the gate's restart moved is judged again by the tab's own probe of Windows - here one that answers
    /// the folder is reached through a link, which Windows itself, asked of that real local folder, would not (the
    /// final reviews of 157A, the mutation review's Z22).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AMovedRunRootIsJudgedByTheTabsOwnProbe(string tab)
    {
        using var world = new HoldWorld(tab);
        string moved = Path.Combine(world.Root, "moved-runs");
        Directory.CreateDirectory(moved);
        var probe = FakeRunRootProbe.Local();
        probe.Links.Add(moved);
        world.Probe = probe;
        bool gatePassed = false;
        world.RunRootForANewRun = () => gatePassed ? moved : world.RunRoot;
        world.AtTheGate = () => gatePassed = true;
        world.Open();

        world.Press("c1");

        Assert.Equal("RunRootRefused", world.Reply("error", "c1").GetProperty("error_class").GetString());
        Assert.Empty(Directory.GetDirectories(moved));
        Assert.Equal(0, world.Dump.Runs);
    }

    /// <summary>
    /// A run handed over whose reply never reaches the page - its mark of delivery lost with the pane's window, or
    /// never queued - holds the restart back for the delivery limit after the hand-over and no longer, and an
    /// evaluation that comes after that is not taken back: the bound an undelivered hand-over lacked (the final reviews
    /// of 157A). The limit is an hour, far past any delivery SOLIDWORKS' application thread holds up, counted from the
    /// hand-over - here three hours after the add-in loaded, as the clock the add-in runs with reads then.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AHandOverWhoseReplyNeverReachesThePageHoldsNoLongerThanTheDeliveryLimit(string tab)
    {
        using var world = new HoldWorld(tab) { HoldDelivery = true };
        world.Open();
        world.Advance(TimeSpan.FromHours(3));
        world.Press("c1");
        string runDirectory = world.Extracted("c1");

        world.Advance(CheckHoldOptions.DeliveryLimit - TimeSpan.FromTicks(1));
        Assert.True(world.CheckInProgress);
        world.Advance(TimeSpan.FromTicks(1));
        Assert.False(world.CheckInProgress);

        Assert.Null(world.HoldEvaluation(runDirectory));
        Assert.Equal(TimeSpan.FromHours(1), CheckHoldOptions.DeliveryLimit);
    }

    /// <summary>
    /// ...as on a real pane: the mark queued behind the reply on a pane whose window goes before it runs is lost with
    /// it, as WinForms drops what is queued on a window that goes, and the hold lets the restart go at the delivery
    /// limit (the final reviews of 157A: the mutation review's demonstration).
    /// </summary>
    [Fact]
    public void AMarkLostWithThePanesWindowHoldsNoLongerThanTheDeliveryLimit()
    {
        int marks = -1;
        bool heldJustBefore = false;
        bool heldAfter = true;
        StaHost.Run(async form =>
        {
            var pane = new TaskPaneControl(new TaskPaneOptions(new NoWebViewEnvironment(), @"C:\Fictional\FICT-review-runs"));
            form.Controls.Add(pane);
            Assert.NotEqual(IntPtr.Zero, pane.Handle);
            int ran = 0;
            using var world = new HoldWorld("Model check")
            {
                AfterPostsVia = action => pane.AfterPosts(() =>
                {
                    ran++;
                    action();
                }),
            };
            world.Open();

            // Pressed on the pane's own thread, as the reviewer's demonstration did: the mark is queued behind the
            // reply and the window goes before the thread is free to run it.
            world.Press("c1");
            pane.Dispose();
            await Task.Delay(300);

            world.Advance(CheckHoldOptions.DeliveryLimit - TimeSpan.FromTicks(1));
            heldJustBefore = world.CheckInProgress;
            world.Advance(TimeSpan.FromTicks(1));
            heldAfter = world.CheckInProgress;
            marks = ran;
        });

        Assert.Equal(0, marks);
        Assert.True(heldJustBefore);
        Assert.False(heldAfter);
    }

    /// <summary>
    /// An evaluation the proxy holds holds the restart back for as long as it is out, however far past the delivery
    /// limit: the tab's next press forgets only holds that hold nothing (the final reviews of 157A).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AnEvaluationOutPastTheDeliveryLimitHoldsUntilItIsAnswered(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        IDisposable? evaluation = world.HoldEvaluation(world.Extracted("c1"));
        Assert.NotNull(evaluation);
        world.Advance(CheckHoldOptions.DeliveryLimit + TimeSpan.FromMinutes(1));

        world.Press("c2");
        world.Extracted("c2");
        world.Advance(CheckHoldOptions.DefaultHandOverLimit);

        Assert.True(world.CheckInProgress, "the tab's next press forgot an evaluation still out");
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A reply that reaches the page just before the delivery limit still gives it its whole minute: the limit bounds
    /// the wait for the delivery, not the minute after it, and an evaluation in that minute is held as in any other
    /// (the final reviews of 157A).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AReplyDeliveredJustBeforeTheDeliveryLimitHasItsWholeMinute(string tab)
    {
        using var world = new HoldWorld(tab) { HoldDelivery = true };
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");
        world.Advance(CheckHoldOptions.DeliveryLimit - TimeSpan.FromSeconds(1));
        world.Deliver();

        world.Advance(CheckHoldOptions.DefaultHandOverLimit - TimeSpan.FromSeconds(1));

        Assert.True(world.CheckInProgress);
        IDisposable? evaluation = world.HoldEvaluation(runDirectory);
        Assert.NotNull(evaluation);
        Assert.Equal(0, world.WhileNoRestartRunsAsked);
        evaluation!.Dispose();
        Assert.False(world.CheckInProgress);
    }

    /// <summary>
    /// A start whose reply cannot be made - here its counts cannot be read - lets its hold go, since the reply is made
    /// before the run is handed over: no hold is left handed over to a page that was never told (the final reviews of
    /// 157A: the race probe and the mutation review's demonstration, a hold that held every restart back for good).
    /// </summary>
    [Fact]
    public void AStartWhoseReplyCannotBeMadeLetsItsHoldGo()
    {
        using var world = new PaneWorld { CountsFail = true };

        Assert.Throws<InvalidOperationException>(() => world.Start("c1"));

        Assert.False(world.Pane.CheckInProgress);
        Assert.DoesNotContain(world.Events, posted => posted == "post:check.extracted");
        world.Clock += TimeSpan.FromDays(1);
        Assert.False(world.Pane.CheckInProgress);
    }

    /// <summary>
    /// The mark that starts the page's minute is queued after the reply that hands the run over (the final reviews of
    /// 157A, the mutation review's Z20).
    /// </summary>
    [Fact]
    public void TheMarkOfDeliveryIsQueuedAfterTheReply()
    {
        using var world = new PaneWorld();
        world.Options.Hold.AfterPosts = action =>
        {
            world.Events.Add("mark");
            action();
        };

        world.Start("c1");

        int reply = world.Events.IndexOf("post:check.extracted");
        int mark = world.Events.IndexOf("mark");
        Assert.True(reply >= 0 && mark > reply, string.Join(", ", world.Events));
    }

    // ---- the world -------------------------------------------------------------------------------

    /// <summary>
    /// One check tab's host - the Model check's or the Standards' - over fakes: a gate in place of the review host's
    /// that counts its asks and runs its step, or refuses or throws as a case says; a clock only the case moves; a dump
    /// with a hook while it reads the model; and a run root, a document and a profile that pass every refusal unless a
    /// case says otherwise.
    /// </summary>
    private sealed class HoldWorld : IDisposable
    {
        private readonly List<string> _posted = new List<string>();
        private ModelCheckHost? _modelCheck;
        private StandardsHost? _standards;
        private readonly Queue<Action> _undelivered = new Queue<Action>();
        private TimeSpan _clock;

        public HoldWorld(string tab)
        {
            Tab = tab;
            Root = Path.Combine(Path.GetTempPath(), "SwReview.CheckHold.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Root);
            RunRoot = Path.Combine(Root, "runs");
            Directory.CreateDirectory(RunRoot);
            ProfilePath = Path.Combine(Root, "FICT-standards.yaml");
            File.WriteAllText(ProfilePath, "# a profile the host never reads\n");
            Document = new PageDocument(@"C:\Fictional\FICT-bracket\FICT-bracket.SLDPRT", "Default");
        }

        public string Tab { get; }

        public string Root { get; }

        public string RunRoot { get; }

        /// <summary>The run root as the setting spells it, when not <see cref="RunRoot"/>.</summary>
        public string? RunRootSpelling { get; set; }

        /// <summary>The run root for a new run, read per reading; null keeps the host's default, the run root in force.</summary>
        public Func<string?>? RunRootForANewRun { get; set; }

        public IRunRootProbe? Probe { get; set; }

        public PageDocument? Document { get; set; }

        public string? ProfilePath { get; set; }

        public bool UseDump { get; set; } = true;

        public HoldDump Dump { get; } = new HoldDump();

        /// <summary>Runs as the run is registered as the pane's latest; a case makes it throw.</summary>
        public Action? Registering { get; set; }

        public TimeSpan HandOverLimit { get; set; } = CheckHoldOptions.DefaultHandOverLimit;

        /// <summary>Whether a settings restart stands before the press, as the review host would answer it.</summary>
        public bool RestartAhead { get; set; }

        /// <summary>Whether reading if a settings restart stands before the press throws.</summary>
        public bool RestartAheadFails { get; set; }

        /// <summary>Runs as each message is posted to the page, after it is posted: what the page does the instant it reads it.</summary>
        public Action<string>? OnPosted { get; set; }

        /// <summary>How many times the gate was asked.</summary>
        public int GateAsked { get; private set; }

        /// <summary>Runs as the gate is asked, before its step: what the gate's wait can change.</summary>
        public Action? AtTheGate { get; set; }

        /// <summary>The gate's refusal; null lets the press through, its step run.</summary>
        public BackendRequestException? GateRefusal { get; set; }

        /// <summary>Whether the gate runs its step before it refuses, which the review host's never does.</summary>
        public bool GateRefusesAfterTheStep { get; set; }

        /// <summary>Thrown by the gate - before its step, or after it when <see cref="GateFailsAfterTheStep"/>.</summary>
        public Exception? GateFailure { get; set; }

        public bool GateFailsAfterTheStep { get; set; }

        /// <summary>Whether the check was in progress just after the gate's last step ran.</summary>
        public bool InProgressAfterTheStep { get; private set; }

        /// <summary>The backend up, as the host reads it; a case changes it as a restart or a stop would.</summary>
        public BackendEndpoint? Backend { get; set; } = new BackendEndpoint(52000, "FICT-token-0");

        /// <summary>Runs as the host reads the backend up, before it is answered.</summary>
        public Action? BackendRead { get; set; }

        /// <summary>The token the page evaluates with, from the last `init` it had; none when null.</summary>
        public string? PageToken { get; set; } = "FICT-token-0";

        /// <summary>The restart's own lock, as the review host's step takes it, when a case stands one in; none by default.</summary>
        public object? RestartLock { get; set; }

        /// <summary>Runs inside a step asked to run while no restart runs, before the step: what can happen meanwhile.</summary>
        public Action? BeforeTheStep { get; set; }

        /// <summary>Whether the gate lets a press through without running its step, which the review host's never does.</summary>
        public bool GateSkipsTheStep { get; set; }

        /// <summary>Whether what is queued behind the page's posts is queued and then throws, so it is run at once too.</summary>
        public bool AfterPostsQueuesAndFails { get; set; }

        /// <summary>Where what is queued behind the page's posts goes instead of this world's own queue: a real pane's.</summary>
        public Action<Action>? AfterPostsVia { get; set; }

        /// <summary>Whether what is queued behind the page's posts waits for <see cref="Deliver"/>, as behind a busy application thread.</summary>
        public bool HoldDelivery { get; set; }

        /// <summary>Whether queuing behind the page's posts throws, as a pane that cannot queue would.</summary>
        public bool AfterPostsFails { get; set; }

        /// <summary>Whether the restart can no longer be asked, stopping with the add-in: its step is not run.</summary>
        public bool Stopping { get; set; }

        /// <summary>Whether asking for a step while no restart runs throws.</summary>
        public bool WhileNoRestartRunsFails { get; set; }

        /// <summary>How many times a step was asked to run while no restart runs.</summary>
        public int WhileNoRestartRunsAsked { get; private set; }

        public string StartType => Tab == "Model check" ? "check.start" : "standards.start";

        public string ExtractedType => Tab == "Model check" ? "check.extracted" : "standards.extracted";

        public string PressAgain => Tab == "Model check" ? "press Model check again" : "press Standards check again";

        /// <summary>The tab's words for a press whose document changed while its gate waited, pinned word for word.</summary>
        public string DocumentChangedWords => Tab == "Model check"
            ? "The active document or its configuration changed after Model check was pressed, so nothing was checked. "
                + "Make the part you want checked the active document and press Model check again."
            : "The active document or its configuration changed after Standards check was pressed, so nothing was checked. "
                + "Make the document you want graded the active document and press Standards check again.";

        public bool CheckInProgress => _modelCheck?.CheckInProgress ?? _standards!.CheckInProgress;

        /// <summary>The page evaluates the run in <paramref name="runDirectory"/> with the token it holds (<see cref="PageToken"/>).</summary>
        public IDisposable? HoldEvaluation(string runDirectory) => HoldEvaluation(runDirectory, PageToken);

        public IDisposable? HoldEvaluation(string runDirectory, string? token) =>
            _modelCheck != null ? _modelCheck.HoldEvaluation(runDirectory, token) : _standards!.HoldEvaluation(runDirectory, token);

        public void Advance(TimeSpan by) => _clock += by;

        /// <summary>The application thread frees: what waited behind the page's posts runs, in order.</summary>
        public void Deliver()
        {
            while (_undelivered.Count > 0)
            {
                _undelivered.Dequeue()();
            }
        }

        public void Open()
        {
            Func<string> runRoot = () => RunRootSpelling ?? RunRoot;
            if (Tab == "Model check")
            {
                var options = new ModelCheckHostOptions(new CollectingChannel(_posted, json => OnPosted?.Invoke(json)), runRoot)
                {
                    CurrentDocument = () => Document,
                    Dump = UseDump ? Dump : null,
                    RegisterLatestRun = _ => Registering?.Invoke(),
                    LogFolder = () => Path.Combine(Root, "logs"),
                    Now = () => Stamp,
                    RunRootProbe = Probe ?? FakeRunRootProbe.Local(),
                    Backend = ReadBackend,
                    Hold =
                    {
                        BeginCheck = Gate,
                        RestartAhead = ReadRestartAhead,
                        HandOverLimit = HandOverLimit,
                        Clock = () => _clock,
                        AfterPosts = AfterPosts,
                        WhileNoRestartRuns = WhileNoRestartRuns,
                    },
                };
                if (RunRootForANewRun != null)
                {
                    options.RunRootForANewRun = RunRootForANewRun;
                }

                _modelCheck = new ModelCheckHost(options);
            }
            else
            {
                var options = new StandardsHostOptions(new CollectingChannel(_posted, json => OnPosted?.Invoke(json)), runRoot)
                {
                    CurrentDocument = () => Document,
                    ProfilePath = () => ProfilePath,
                    Dump = UseDump ? Dump : null,
                    RegisterLatestRun = _ => Registering?.Invoke(),
                    LogFolder = () => Path.Combine(Root, "logs"),
                    Now = () => Stamp,
                    RunRootProbe = Probe ?? FakeRunRootProbe.Local(),
                    Backend = ReadBackend,
                    Hold =
                    {
                        BeginCheck = Gate,
                        RestartAhead = ReadRestartAhead,
                        HandOverLimit = HandOverLimit,
                        Clock = () => _clock,
                        AfterPosts = AfterPosts,
                        WhileNoRestartRuns = WhileNoRestartRuns,
                    },
                };
                if (RunRootForANewRun != null)
                {
                    options.RunRootForANewRun = RunRootForANewRun;
                }

                _standards = new StandardsHost(options);
            }
        }

        /// <summary>The engineer presses the tab's check, on this thread.</summary>
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

        /// <summary>The run folder the start handed to the page.</summary>
        public string Extracted(string id) => Reply(ExtractedType, id).GetProperty("run_dir").GetString()!;

        public string[] RunFolders()
        {
            string root = RunRootSpelling ?? RunRoot;
            return Directory.Exists(root) ? Directory.GetDirectories(root) : new string[0];
        }

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
                $"expected exactly one '{type}' reply to '{id}', saw {matches.Length}; posted: " + string.Join(" | ", _posted));
            return matches[0];
        }

        public JsonElement[] AllPosted(string type) => Messages()
            .Where(root => root.GetProperty("type").GetString() == type)
            .Select(root => root.GetProperty("payload"))
            .ToArray();

        public void DisposeHost()
        {
            _modelCheck?.Dispose();
            _standards?.Dispose();
        }

        public void Dispose()
        {
            DisposeHost();
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

        private bool ReadRestartAhead() =>
            RestartAheadFails ? throw new InvalidOperationException("FICT the review host cannot be read") : RestartAhead;

        private BackendEndpoint? ReadBackend()
        {
            BackendRead?.Invoke();
            return Backend;
        }

        private void AfterPosts(Action delivered)
        {
            if (AfterPostsVia != null)
            {
                AfterPostsVia(delivered);
                return;
            }

            if (AfterPostsFails)
            {
                throw new InvalidOperationException("FICT the pane cannot queue");
            }

            if (AfterPostsQueuesAndFails)
            {
                _undelivered.Enqueue(delivered);
                throw new InvalidOperationException("FICT the pane queued it, then failed");
            }

            if (HoldDelivery)
            {
                _undelivered.Enqueue(delivered);
                return;
            }

            delivered();
        }

        private bool WhileNoRestartRuns(Func<bool> step)
        {
            WhileNoRestartRunsAsked++;
            if (WhileNoRestartRunsFails)
            {
                throw new InvalidOperationException("FICT the review host cannot be asked");
            }

            BeforeTheStep?.Invoke();
            if (RestartLock == null)
            {
                return !Stopping && step();
            }

            lock (RestartLock)
            {
                return !Stopping && step();
            }
        }

        private BackendRequestException? Gate(Action begin)
        {
            GateAsked++;
            AtTheGate?.Invoke();
            if (GateFailure != null && !GateFailsAfterTheStep)
            {
                throw GateFailure;
            }

            if (GateSkipsTheStep)
            {
                return null;
            }

            if (GateRefusal != null)
            {
                if (GateRefusesAfterTheStep)
                {
                    begin();
                }

                InProgressAfterTheStep = CheckInProgress;
                return GateRefusal;
            }

            begin();
            InProgressAfterTheStep = CheckInProgress;
            if (GateFailure != null)
            {
                throw GateFailure;
            }

            return null;
        }

        private IEnumerable<JsonElement> Messages() =>
            _posted.Select(message => JsonDocument.Parse(message).RootElement);
    }

    /// <summary>
    /// A check pane on its own, its start given by the case as a tab gives its own (<see cref="CheckStart"/>), for what
    /// only a tab's start can make fail - its reply's counts - and for the order of what it posts and queues.
    /// </summary>
    private sealed class PaneWorld : IDisposable
    {
        private readonly string _root;
        private readonly string _runRoot;
        private int _stamp;

        public PaneWorld()
        {
            _root = Path.Combine(Path.GetTempPath(), "SwReview.CheckHold.Tests", Guid.NewGuid().ToString("N"));
            _runRoot = Path.Combine(_root, "runs");
            Directory.CreateDirectory(_runRoot);
            var document = new PageDocument(@"C:\Fictional\FICT-bracket\FICT-bracket.SLDPRT", "Default");
            Options = new CheckPaneHostOptions(new CollectingChannel(Posted, Record), () => _runRoot, "check.start", _ => { })
            {
                Backend = () => new BackendEndpoint(52000, "FICT-token-0"),
                CurrentDocument = () => document,
                Now = () => Stamp.AddSeconds(_stamp++),
            };
            Options.Hold.Clock = () => Clock;
            Pane = new CheckPaneHost(Options);
        }

        public CheckPaneHostOptions Options { get; }

        public CheckPaneHost Pane { get; }

        public TimeSpan Clock { get; set; }

        public bool CountsFail { get; set; }

        public List<string> Posted { get; } = new List<string>();

        public List<string> Events { get; } = new List<string>();

        public void Start(string id) => Pane.StartCheck(id, new CheckStart(
            noDocument: "FICT no document",
            refuses: (_, __) => false,
            dump: () => new HoldDump(),
            restartFirst: "FICT restart first",
            documentChanged: "FICT changed",
            nothingChecked: "nothing was checked",
            pressAgain: "press Model check again",
            runRootForANewRun: () => _runRoot,
            probe: () => FakeRunRootProbe.Local(),
            createFolder: RunFolders.CreateForCheck,
            folder: "the check folder",
            reading: document => "Reading " + document,
            profile: DumpProfile.ModelCheck,
            during: "the feature tree was read",
            next: ". Checking the model...",
            extractedType: "check.extracted",
            counts: summary => CountsFail
                ? throw new InvalidOperationException("FICT a count that cannot be read")
                : new Dictionary<string, object?> { { "documents", summary.Documents } }));

        public void Dispose()
        {
            Pane.Dispose();
            try
            {
                Directory.Delete(_root, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        private void Record(string json) =>
            Events.Add("post:" + JsonDocument.Parse(json).RootElement.GetProperty("type").GetString());
    }

    private sealed class CollectingChannel : IPageChannel
    {
        private readonly List<string> _posted;
        private readonly Action<string>? _posting;

        public CollectingChannel(List<string> posted, Action<string>? posting = null)
        {
            _posted = posted;
            _posting = posting;
        }

        public void PostMessage(string json)
        {
            _posted.Add(json);
            _posting?.Invoke(json);
        }
    }

    /// <summary>A dump that writes nothing but its package, with a hook while it reads the model and a failure a case can set.</summary>
    private sealed class HoldDump : IReviewDump
    {
        public int Runs { get; private set; }

        public string? LastDirectory { get; private set; }

        public Action? OnRun { get; set; }

        public Exception? Failure { get; set; }

        public DumpSummary Run(string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
        {
            Runs++;
            LastDirectory = outputDirectory;
            OnRun?.Invoke();
            if (Failure != null)
            {
                throw Failure;
            }

            return new DumpSummary(Path.Combine(outputDirectory, "package.json"), components: 1, gaps: 0);
        }
    }
}
