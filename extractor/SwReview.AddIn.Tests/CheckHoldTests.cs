using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
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
        world.Advance(CheckPaneHostOptions.DefaultHandOverLimit + TimeSpan.FromMinutes(5));
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
    /// back for the hand-over's limit and no longer, measured from the hand-over: a moment short of it the check is in
    /// progress, at it not; and an evaluation that comes after the limit is not held.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AHandOverNotTakenWithinItsLimitHoldsNothingMore(string tab)
    {
        using var world = new HoldWorld(tab);
        world.Open();
        world.Press("c1");
        string runDirectory = world.Extracted("c1");

        world.Advance(CheckPaneHostOptions.DefaultHandOverLimit - TimeSpan.FromTicks(1));
        Assert.True(world.CheckInProgress);
        world.Advance(TimeSpan.FromTicks(1));
        Assert.False(world.CheckInProgress);

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
        Assert.Equal(TimeSpan.FromSeconds(60), CheckPaneHostOptions.DefaultHandOverLimit);
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
        Func<TimeSpan> pane = new CheckPaneHostOptions(channel, runRoot, "check.start", _ => { }).Clock;
        Func<TimeSpan> model = new ModelCheckHostOptions(channel, runRoot).Clock;
        Func<TimeSpan> standards = new StandardsHostOptions(channel, runRoot).Clock;
        TimeSpan[] before = { CheckPaneHostOptions.MonotonicClock(), pane(), model(), standards() };

        System.Threading.Thread.Sleep(50);

        Assert.True(CheckPaneHostOptions.MonotonicClock() > before[0], "the add-in's clock did not move");
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

        public TimeSpan HandOverLimit { get; set; } = CheckPaneHostOptions.DefaultHandOverLimit;

        /// <summary>Whether a settings restart stands before the press, as the review host would answer it.</summary>
        public bool RestartAhead { get; set; }

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

        public IDisposable? HoldEvaluation(string runDirectory) =>
            _modelCheck != null ? _modelCheck.HoldEvaluation(runDirectory) : _standards!.HoldEvaluation(runDirectory);

        public void Advance(TimeSpan by) => _clock += by;

        public void Open()
        {
            Func<string> runRoot = () => RunRootSpelling ?? RunRoot;
            if (Tab == "Model check")
            {
                var options = new ModelCheckHostOptions(new CollectingChannel(_posted), runRoot)
                {
                    CurrentDocument = () => Document,
                    Dump = UseDump ? Dump : null,
                    RegisterLatestRun = _ => Registering?.Invoke(),
                    LogFolder = () => Path.Combine(Root, "logs"),
                    Now = () => Stamp,
                    RunRootProbe = Probe ?? FakeRunRootProbe.Local(),
                    BeginCheck = Gate,
                    RestartAhead = () => RestartAhead,
                    HandOverLimit = HandOverLimit,
                    Clock = () => _clock,
                };
                if (RunRootForANewRun != null)
                {
                    options.RunRootForANewRun = RunRootForANewRun;
                }

                _modelCheck = new ModelCheckHost(options);
            }
            else
            {
                var options = new StandardsHostOptions(new CollectingChannel(_posted), runRoot)
                {
                    CurrentDocument = () => Document,
                    ProfilePath = () => ProfilePath,
                    Dump = UseDump ? Dump : null,
                    RegisterLatestRun = _ => Registering?.Invoke(),
                    LogFolder = () => Path.Combine(Root, "logs"),
                    Now = () => Stamp,
                    RunRootProbe = Probe ?? FakeRunRootProbe.Local(),
                    BeginCheck = Gate,
                    RestartAhead = () => RestartAhead,
                    HandOverLimit = HandOverLimit,
                    Clock = () => _clock,
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

        private BackendRequestException? Gate(Action begin)
        {
            GateAsked++;
            AtTheGate?.Invoke();
            if (GateFailure != null && !GateFailsAfterTheStep)
            {
                throw GateFailure;
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

    private sealed class CollectingChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public CollectingChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json) => _posted.Add(json);
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
