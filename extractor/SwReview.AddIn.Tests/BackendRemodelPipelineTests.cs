using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T134d. <see cref="BackendRemodelPipeline"/>: the one implementation of
/// <see cref="IRemodelPipeline"/> the product uses, over a fake backend, a fake dump and a fake
/// seat, with no SOLIDWORKS and no Python.
///
/// What is worth testing here is the wiring, because the wiring is where this feature's rules
/// are either kept or quietly dropped:
///
/// <b>The source is named once.</b> `OpenCopy` is the last member that knows the source path;
/// every later call addresses the run folder. That is the property the constitution's re-modeler
/// exception rests on, and it is asserted over every recorded call rather than assumed from the
/// shape of the code.
///
/// <b>Every `status` stage is on the contract's closed list.</b> The list is read out of
/// `contracts/pane-remodel-messages.md` rather than restated here, so a stage this class invents
/// fails the test instead of reaching a page that has no rendering for it.
///
/// <b>Each change line reaches the page once and unchanged.</b> `changes.jsonl` is the change
/// list; a line relayed twice is a duplicate row, a line reshaped is a record the page cannot
/// read, and a half-written last line relayed early is a parse failure on the page.
///
/// <b>The two dumps happen exactly once each, at the two moments the run defines.</b> A second
/// `package-after.json` dump would measure a tree the gate never compared.
/// </summary>
public sealed class BackendRemodelPipelineTests : IDisposable
{
    private const string SourcePath = @"C:\work\bracket.SLDPRT";

    private const string Pipe = "swreview-8f2c";

    private const string Secret = "remodel-secret";

    private readonly string _root = Path.Combine(
        Path.GetTempPath(), "swreview-pipeline-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_root))
            {
                Directory.Delete(_root, recursive: true);
            }
        }
        catch (IOException)
        {
            // A temp folder that will not delete is not a test failure.
        }
    }

    // ---- probe -----------------------------------------------------------------------------

    [Fact]
    public void ProbeAsksTheBackendAboutTheActiveDocumentAndCarriesTheVerdictWhole()
    {
        var world = new World(this);
        world.Backend.Probe = new RemodelProbeReply(
            "probe-7",
            new SwReview.Extractor.Rms.ScopeSignals { DocumentType = 1, SolidBodyCount = 1 },
            new[] { "the part is a weldment", "the part has 3 solid bodies" });

        RemodelScopeReading reading = world.Pipeline.ProbeScope();

        RemodelProbeRequest sent = Assert.IsType<RemodelProbeRequest>(world.Backend.Calls[0].Request);
        Assert.Equal("probe", world.Backend.Calls[0].Route);
        Assert.Equal(SourcePath, sent.SourcePath);
        Assert.Equal("Default", sent.Configuration);
        Assert.Equal(Pipe, sent.Bridge.Pipe);
        Assert.Equal(Secret, sent.Bridge.Secret);

        Assert.Equal(1, reading.Signals.DocumentType);
        Assert.Equal(
            new[] { "the part is a weldment", "the part has 3 solid bodies" }, reading.Refusals);
    }

    [Fact]
    public void ProbeWithNoDocumentRefusesByNameRatherThanCallingTheBackend()
    {
        var world = new World(this) { Document = null };

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.ProbeScope());

        Assert.Equal("NoDocument", refusal.ErrorClass);
        Assert.Empty(world.Backend.Calls);
    }

    [Fact]
    public void AToolServiceThatIsNotListeningYetRefusesBeforeAnythingIsCopied()
    {
        var world = new World(this) { Bridge = null };

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.ProbeScope());

        Assert.Equal("BridgeUnavailable", refusal.ErrorClass);
        Assert.Empty(world.Backend.Calls);
    }

    // ---- open ------------------------------------------------------------------------------

    [Fact]
    public void OpenCopySendsTheProbeIdTheProbeMintedAndReportsTheCopying()
    {
        var world = new World(this);
        world.Backend.Probe = new RemodelProbeReply(
            "probe-7", new SwReview.Extractor.Rms.ScopeSignals(), new string[0]);
        world.Pipeline.ProbeScope();

        string runDirectory = world.RunFolder();
        RemodelCopyReading reading = world.Pipeline.OpenCopy(
            new RemodelCopyRequest(runDirectory, SourcePath, "Default"), world.Reporter);

        RemodelOpenRequest sent = Assert.IsType<RemodelOpenRequest>(world.Backend.Calls[1].Request);
        Assert.Equal("open", world.Backend.Calls[1].Route);
        Assert.Equal(runDirectory, sent.RunDirectory);
        Assert.Equal(SourcePath, sent.SourcePath);
        Assert.Equal("probe-7", sent.ProbeId);
        Assert.Equal(Secret, sent.Bridge.Secret);

        Assert.Equal(world.Backend.Open.CopyPath, reading.CopyPath);
        Assert.Equal(0, reading.RebuildErrorCount);
        Assert.Equal("copying", world.Reporter.Statuses[0].Key);
    }

    [Fact]
    public void ARefusalFromOpenBecomesARemodelRefusalCarryingTheBackendsClassAndSentence()
    {
        var world = new World(this);
        world.Backend.OpenFailure = new BackendRequestException(
            "ExternalReferences",
            "the part has 2 external references.",
            retryable: false);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.OpenCopy(
            new RemodelCopyRequest(world.RunFolder(), SourcePath, null), world.Reporter));

        Assert.Equal("ExternalReferences", refusal.ErrorClass);
        Assert.Equal("the part has 2 external references.", refusal.Message);
    }

    /// <summary>
    /// A count that could not be read stays unknown all the way to the host, which refuses the
    /// run on it. Null is not zero anywhere on this path.
    /// </summary>
    [Fact]
    public void AnUnknownRebuildCountArrivesAtTheHostAsUnknown()
    {
        var world = new World(this);
        world.Backend.Open = new RemodelOpenReply(@"C:\runs\copy\bracket-RMS.SLDPRT", null, true);

        RemodelCopyReading reading = world.Pipeline.OpenCopy(
            new RemodelCopyRequest(world.RunFolder(), SourcePath, null), world.Reporter);

        Assert.Null(reading.RebuildErrorCount);
    }

    /// <summary>
    /// `copy_present` is a safety signal, not a decoration: it is the bridge saying it has
    /// already deleted the copy and closed the document (`preexisting_rebuild_errors`). Dropped
    /// here, the host would have only the count to go on, and a count of 0 arriving with a copy
    /// that is gone reads as a clean part - after which the next thing the run does is dump
    /// "the copy", which is whatever document SOLIDWORKS still has active.
    /// </summary>
    [Fact]
    public void OpenCopyCarriesWhetherTheBridgeStillHasACopyOnDisk()
    {
        var world = new World(this);
        world.Backend.Open = new RemodelOpenReply(@"C:\runs\copy\bracket-RMS.SLDPRT", 0, false);

        RemodelCopyReading gone = world.Pipeline.OpenCopy(
            new RemodelCopyRequest(world.RunFolder(), SourcePath, null), world.Reporter);

        Assert.False(gone.CopyPresent);

        world.Backend.Open = new RemodelOpenReply(@"C:\runs\copy\bracket-RMS.SLDPRT", 0, true);

        RemodelCopyReading present = world.Pipeline.OpenCopy(
            new RemodelCopyRequest(world.RunFolder(), SourcePath, null), world.Reporter);

        Assert.True(present.CopyPresent);
    }

    // ---- plan ------------------------------------------------------------------------------

    [Fact]
    public void PlanDumpsTheCopyAsAModelCheckAndRenamesThePackageToPackageBefore()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Backend.PlanSummary = @"{""moves"":12,""folders"":6,""state"":""planned""}";

        string summary = world.Pipeline.Plan(runDirectory, world.Reporter);

        Assert.Equal(DumpProfile.ModelCheck, world.Dump.Profiles.Single());
        Assert.Equal(runDirectory, world.Dump.Folders.Single());
        Assert.True(File.Exists(Path.Combine(runDirectory, "package-before.json")));
        Assert.False(File.Exists(Path.Combine(runDirectory, "package.json")));

        // Untouched: the host parses it and forwards it to the page as `plan_summary`.
        Assert.Equal(world.Backend.PlanSummary, summary);
        Assert.Equal(runDirectory, Assert.IsType<string>(world.Backend.Calls.Single().Request));
        Assert.Equal("plan", world.Backend.Calls.Single().Route);

        Assert.Equal(
            new[] { "dumping", "planning" },
            world.Reporter.Statuses.Select(status => status.Key).Distinct().ToArray());
    }

    /// <summary>
    /// The profile is asserted in the file that was written, not in the argument that was
    /// passed: a full dump renamed to `package-before.json` would be a package with holes,
    /// fasteners and meshes in it, and the plan the RMS rules produce from it is a plan for a
    /// different reading of the part.
    /// </summary>
    [Fact]
    public void PlanRefusesAPackageThatWasNotWrittenByAModelCheckDump()
    {
        var world = new World(this);
        world.Dump.Profile = "full";
        string runDirectory = world.RunFolder();

        Exception failure = Assert.ThrowsAny<Exception>(
            () => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.Contains("model_check", failure.Message, StringComparison.Ordinal);
        Assert.False(File.Exists(Path.Combine(runDirectory, "package-before.json")));
        Assert.Empty(world.Backend.Calls);
    }

    /// <summary>
    /// The dump attaches to whatever document SOLIDWORKS has active, and the engineer's own
    /// source is still open in another tab. Which document was read is knowable only from the
    /// file that was written, so it is read out of it: a `package-before.json` that is a
    /// reading of the source would be planned against, graded against and compared against, and
    /// the report would state a verified run for a document the run never touched.
    ///
    /// The path that was read is <b>not</b> in the message: it may be the source, and nothing
    /// after the copy may name the source. The written `package.json` stays in the run folder as
    /// the evidence.
    /// </summary>
    [Fact]
    public void PlanRefusesAPackageThatNamesADocumentOutsideTheRunFoldersCopy()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Dump.DocumentPath = SourcePath;

        Exception failure = Assert.ThrowsAny<Exception>(
            () => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.Contains(runDirectory, failure.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(SourcePath, failure.Message, StringComparison.OrdinalIgnoreCase);
        Assert.False(File.Exists(Path.Combine(runDirectory, "package-before.json")));
        Assert.Empty(world.Backend.Calls);
    }

    /// <summary>A package that names no document at all says nothing about what it read, and
    /// unknown is not "the copy" (constitution Principle I).</summary>
    [Fact]
    public void PlanRefusesAPackageThatNamesNoDocumentAtAll()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Dump.WritesADocument = false;

        Assert.ThrowsAny<Exception>(() => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.False(File.Exists(Path.Combine(runDirectory, "package-before.json")));
        Assert.Empty(world.Backend.Calls);
    }

    /// <summary>
    /// A dump costs the engineer minutes on the application thread. A backend that is not
    /// listening is knowable before it is spent.
    /// </summary>
    [Fact]
    public void PlanRefusesBeforeItDumpsWhenTheBackendIsNotRunning()
    {
        var world = new World(this) { Endpoint = null };

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.Plan(world.RunFolder(), world.Reporter));

        Assert.Equal("BackendUnavailable", refusal.ErrorClass);
        Assert.Empty(world.Dump.Folders);
    }

    // ---- run -------------------------------------------------------------------------------

    [Fact]
    public void TheRunRelaysEveryChangeLineOnceAndExactlyAsItWasWritten()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        string[] lines =
        {
            @"{""seq"":1,""kind"":""rename"",""status"":""attempting"",""subject"":{""name"":""A""}}",
            @"{""seq"":1,""kind"":""rename"",""status"":""applied"",""subject"":{""name"":""A""}}",
            @"{""seq"":2,""kind"":""reorder"",""status"":""applied"",""subject"":{""name"":""B""}}",
        };

        world.Backend.StatusAt = poll =>
        {
            if (poll == 0)
            {
                Append(runDirectory, lines[0]);
                return Running("applying", 2, 0);
            }

            if (poll == 1)
            {
                Append(runDirectory, lines[1], lines[2]);
                return Running("applying", 2, 2);
            }

            return Finished("saved", 2);
        };

        RemodelRunOutcome outcome = world.Pipeline.Run(runDirectory, world.Reporter);

        Assert.Equal(lines, world.Reporter.Changes);
        Assert.Equal("saved", outcome.State);
        Assert.Equal(2, outcome.ChangesApplied);
    }

    /// <summary>
    /// The writer appends a line in two steps - the record, then the newline - and the reader
    /// polls in between. A record relayed while it is half written is a page that throws on the
    /// line it was given.
    /// </summary>
    [Fact]
    public void AHalfWrittenLastLineIsNotRelayedUntilItIsComplete()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        string line = @"{""seq"":1,""kind"":""rename"",""status"":""applied""}";

        world.Backend.StatusAt = poll =>
        {
            if (poll == 0)
            {
                File.AppendAllText(Path.Combine(runDirectory, "changes.jsonl"), line);
                return Running("applying", 1, 0);
            }

            if (poll == 1)
            {
                Assert.Empty(world.Reporter.Changes);
                File.AppendAllText(Path.Combine(runDirectory, "changes.jsonl"), "\n");
                return Running("applying", 1, 1);
            }

            return Finished("saved", 1);
        };

        world.Pipeline.Run(runDirectory, world.Reporter);

        Assert.Equal(new[] { line }, world.Reporter.Changes);
    }

    [Fact]
    public void TheRunReportsTheCountsAndTheChangeInFlight()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll => poll == 0
            ? Running("applying", 12, 5, new RemodelRunCurrent(6, "reorder", "Fillet3"))
            : Finished("saved", 12);

        world.Pipeline.Run(world.RunFolder(), world.Reporter);

        RecordedProgress progress = Assert.Single(world.Reporter.Progress);
        Assert.Equal(5, progress.Applied);
        Assert.Equal(12, progress.Total);
        Assert.Equal(6, progress.Seq);
        Assert.Equal("reorder", progress.Kind);
        Assert.Equal("Fillet3", progress.SubjectName);
    }

    [Fact]
    public void ExactlyOneStopIsPostedHoweverManyPollsSeeTheFlag()
    {
        var world = new World(this);
        world.Reporter.StopRequested = true;
        world.Backend.StatusAt = poll => poll < 3 ? Running("applying", 4, 1) : Finished("truncated", 1);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal(1, world.Backend.Calls.Count(call => call.Route == "stop"));
        Assert.Equal("truncated", outcome.State);
    }

    /// <summary>
    /// A stop that could not be posted has not happened, and the run it belongs to is still
    /// healthy: the executor is applying changes to the copy either way. So the failure is not
    /// allowed out of the poll loop - that would end the run as `failed` with zero changes while
    /// the backend is still applying them, and leave the folder blocked by `RunInProgress` -
    /// and the stop is simply posted again on the next poll, which the route's idempotence
    /// makes free.
    /// </summary>
    [Fact]
    public void AStopThatCouldNotBePostedIsPostedAgainOnTheNextPollRatherThanEndingTheRun()
    {
        var world = new World(this);
        world.Reporter.StopRequested = true;
        world.Backend.StopFailures = 1;
        world.Backend.StatusAt = poll => poll < 3 ? Running("applying", 4, 1) : Finished("truncated", 1);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal(2, world.Backend.Calls.Count(call => call.Route == "stop"));
        Assert.Equal("truncated", outcome.State);
        Assert.Equal(1, outcome.ChangesApplied);
    }

    [Fact]
    public void NoStopIsPostedWhenNobodyAskedForOne()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll => poll == 0 ? Running("applying", 1, 0) : Finished("saved", 1);

        world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.DoesNotContain(world.Backend.Calls, call => call.Route == "stop");
    }

    [Fact]
    public void ThePackageAfterRendezvousDumpsOnceAndPostsThatExactPath()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Backend.StatusAt = poll =>
        {
            if (poll <= 1)
            {
                return Awaiting("verifying", 3, 3);
            }

            return Finished("saved", 3);
        };

        world.Pipeline.Run(runDirectory, world.Reporter);

        string expected = Path.Combine(runDirectory, "package-after.json");
        Assert.True(File.Exists(expected));
        Assert.False(File.Exists(Path.Combine(runDirectory, "package.json")));
        Assert.Equal(new[] { expected }, world.Backend.PackageAfterPaths);
        Assert.Equal(new[] { DumpProfile.ModelCheck }, world.Dump.Profiles.ToArray());
        Assert.Contains(world.Reporter.Statuses, status => status.Key == "verifying");
    }

    /// <summary>
    /// `PackageAfterRefused` is one of the backend's named classes. Unwrapped it would leave
    /// the poll loop as a raw <see cref="BackendRequestException"/>, reach the host's generic
    /// catch and be shown as `HostError` with the same prose every other failure gets - which
    /// is the exact thing <see cref="RemodelRefusal"/> exists to prevent.
    /// </summary>
    [Fact]
    public void ARefusedPackageAfterKeepsItsClassRatherThanEscapingAsAHostError()
    {
        var world = new World(this);
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "PackageAfterRefused",
            "the package the add-in named is not this run's package-after.json.",
            retryable: false);

        // Terminal after the rendezvous, so a build that let the refusal through would fail
        // this test rather than poll forever.
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("verifying", 3, 3) : Finished("saved", 3);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal("PackageAfterRefused", refusal.ErrorClass);
    }

    /// <summary>
    /// The same reading at the other end of the run, and it matters more here: the after-dump
    /// happens minutes after the copy was opened, and the engineer has been free to click back
    /// to their own tab the whole time. A `package-after.json` that read the source would grade
    /// the source, compare the source against the copy's baseline and pass.
    /// </summary>
    [Fact]
    public void TheAfterDumpIsRefusedWhenItDidNotReadTheCopyAndNothingIsPosted()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Dump.DocumentPath = SourcePath;
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("verifying", 3, 3) : Finished("saved", 3);

        Exception failure = Assert.ThrowsAny<Exception>(
            () => world.Pipeline.Run(runDirectory, world.Reporter));

        Assert.DoesNotContain(SourcePath, failure.Message, StringComparison.OrdinalIgnoreCase);
        Assert.False(File.Exists(Path.Combine(runDirectory, "package-after.json")));
        Assert.Empty(world.Backend.PackageAfterPaths);
        Assert.DoesNotContain(world.Backend.Calls, call => call.Route == "package-after");
    }

    [Fact]
    public void EveryStageTheRunPostsIsOnTheContractsClosedList()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Backend.StatusAt = poll =>
        {
            switch (poll)
            {
                case 0: return Running("planned", 3, 0);
                case 1: return Running("judging", 3, 0);
                case 2: return Running("applying", 3, 1);
                case 3: return Running("verifying", 3, 3);
                case 4: return Awaiting("verifying", 3, 3);
                case 5: return Running("saved", 3, 3);
                default: return Finished("saved", 3);
            }
        };

        world.Pipeline.Plan(runDirectory, world.Reporter);
        world.Pipeline.OpenCopy(
            new RemodelCopyRequest(runDirectory, SourcePath, null), world.Reporter);
        world.Pipeline.Run(runDirectory, world.Reporter);

        IReadOnlyCollection<string> allowed = RemodelPageFiles.StatusStages();
        foreach (KeyValuePair<string, string> status in world.Reporter.Statuses)
        {
            Assert.Contains(status.Key, allowed);
            Assert.False(
                string.IsNullOrWhiteSpace(status.Value),
                "every status carries a sentence for the engineer: " + status.Key);
        }

        // And the run really did walk the phases, so the assertion above is not vacuous.
        Assert.Equal(
            new[] { "judging", "applying", "verifying", "saving" },
            world.Reporter.Statuses
                .Select(status => status.Key)
                .Where(stage => stage != "dumping" && stage != "planning" && stage != "copying")
                .Distinct()
                .ToArray());
    }

    [Fact]
    public void TheRunEndsWithThePlanStateAndTheAppliedCountTheBackendReports()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll => Finished("truncated", 7);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("truncated", outcome.State);
        Assert.Equal(7, outcome.ChangesApplied);
    }

    [Fact]
    public void AFailedRunSaysWhyBeforeItHandsTheOutcomeBack()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll => new RemodelRunStatus(
            RemodelRunStatus.FailedState,
            "failed",
            12,
            3,
            null,
            null,
            "the geometry gate refused the copy");

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("failed", outcome.State);
        Assert.Equal(3, outcome.ChangesApplied);
        Assert.Contains(
            world.Reporter.Statuses,
            status => status.Key == "error" && status.Value == "the geometry gate refused the copy");
    }

    /// <summary>
    /// A run that finished without recording what state it finished in is not a run that saved.
    /// Unknown is reported, never inferred favourably (constitution Principle I).
    /// </summary>
    [Fact]
    public void ATerminalJobWithNoPlanStateIsReportedFailedRatherThanSaved()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll => new RemodelRunStatus(
            RemodelRunStatus.FinishedState, null, 3, 3, null, null, null);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("failed", outcome.State);
        Assert.Contains(world.Reporter.Statuses, status => status.Key == "error");
    }

    [Fact]
    public void ABackendThatVanishesMidRunEndsTheRunFailedAfterAnErrorStatus()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll =>
        {
            if (poll == 0)
            {
                return Running("applying", 4, 2);
            }

            throw new BackendRequestException(
                "BackendUnavailable", "the review backend did not answer.", retryable: true);
        };

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("failed", outcome.State);
        Assert.Equal(2, outcome.ChangesApplied);
        Assert.Equal("error", world.Reporter.Statuses.Last().Key);
    }

    [Fact]
    public void ARefusedStartIsARemodelRefusalRatherThanAFailedRun()
    {
        var world = new World(this);
        world.Backend.StartFailure = new BackendRequestException(
            "ResumeRefused", "a changes.jsonl already exists in this run folder.", retryable: false);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal("ResumeRefused", refusal.ErrorClass);
    }

    // ---- the source, after the copy ---------------------------------------------------------

    /// <summary>
    /// `OpenCopy` is the last member that names the source. This is the constitution's
    /// re-modeler exception stated as a test: after the copy exists there is no call left that
    /// could reach the engineer's file, so there is no call to get wrong.
    /// </summary>
    [Fact]
    public void TheSourceIsNamedInNoCallTheRunMakesAfterOpenCopy()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("verifying", 1, 1) : Finished("saved", 1);

        world.Pipeline.ProbeScope();
        world.Pipeline.OpenCopy(
            new RemodelCopyRequest(runDirectory, SourcePath, "Default"), world.Reporter);
        world.WriteCopy(runDirectory);
        world.Pipeline.Plan(runDirectory, world.Reporter);
        world.Pipeline.Run(runDirectory, world.Reporter);
        world.Pipeline.ActivateCopy(runDirectory);
        world.Pipeline.CloseCopy(runDirectory);

        int open = world.Backend.Calls.FindIndex(call => call.Route == "open");
        Assert.True(open >= 0, "the run never opened a copy.");

        for (int index = open + 1; index < world.Backend.Calls.Count; index++)
        {
            Assert.DoesNotContain(
                SourcePath, world.Backend.Calls[index].Json, StringComparison.OrdinalIgnoreCase);
        }

        Assert.DoesNotContain(SourcePath, world.Seat.Activated.Single(), StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void TheCallsGoInTheOrderTheContractStatesThem()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Backend.StatusAt = poll => Finished("saved", 0);

        world.Pipeline.ProbeScope();
        world.Pipeline.OpenCopy(
            new RemodelCopyRequest(runDirectory, SourcePath, null), world.Reporter);
        world.Pipeline.Plan(runDirectory, world.Reporter);
        world.Pipeline.Run(runDirectory, world.Reporter);
        world.Pipeline.CloseCopy(runDirectory);

        Assert.Equal(
            new[] { "probe", "open", "plan", "runs", "status", "close" },
            world.Backend.Calls.Select(call => call.Route).Distinct().ToArray());
    }

    // ---- the copy, afterwards ---------------------------------------------------------------

    [Fact]
    public void ActivateCopyHandsTheSeatTheOneCopyInTheRunFolder()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        string copy = world.WriteCopy(runDirectory);

        world.Pipeline.ActivateCopy(runDirectory);

        Assert.Equal(new[] { copy }, world.Seat.Activated);
    }

    [Fact]
    public void ActivateCopyOnADiscardedCopyRefusesByNameRatherThanOpeningSomethingElse()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.ActivateCopy(runDirectory));

        Assert.Equal("CopyDiscarded", refusal.ErrorClass);
        Assert.Empty(world.Seat.Activated);
    }

    [Fact]
    public void CloseCopyAsksTheBackendToCloseTheDocumentAndToDiscardNothing()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();

        world.Pipeline.CloseCopy(runDirectory);

        RemodelCloseRequest sent =
            Assert.IsType<RemodelCloseRequest>(world.Backend.Calls.Single().Request);
        Assert.Equal("close", world.Backend.Calls.Single().Route);
        Assert.Equal(runDirectory, sent.RunDirectory);
        Assert.False(sent.DiscardCopy);
        Assert.Equal(Secret, sent.Bridge.Secret);
    }

    /// <summary>
    /// The host calls this on its way to deleting `copy/`, including on paths where the backend
    /// never started. The folder is what the engineer asked to be rid of; a close that cannot be
    /// made must not stop it.
    /// </summary>
    [Fact]
    public void CloseCopyWithNoBackendOrNoBridgeIsAQuietNoOp()
    {
        var world = new World(this) { Endpoint = null };
        world.Pipeline.CloseCopy(world.RunFolder());

        var second = new World(this) { Bridge = null };
        second.Pipeline.CloseCopy(second.RunFolder());

        Assert.Empty(world.Backend.Calls);
        Assert.Empty(second.Backend.Calls);
    }

    // ---- helpers ----------------------------------------------------------------------------

    private static RemodelRunStatus Running(
        string planState, int total, int applied, RemodelRunCurrent? current = null) =>
        new RemodelRunStatus(
            RemodelRunStatus.RunningState, planState, total, applied, current, null, null);

    private static RemodelRunStatus Awaiting(string planState, int total, int applied) =>
        new RemodelRunStatus(
            RemodelRunStatus.AwaitingState,
            planState,
            total,
            applied,
            null,
            RemodelRunStatus.PackageAfterAwaiting,
            null);

    private static RemodelRunStatus Finished(string planState, int applied) =>
        new RemodelRunStatus(
            RemodelRunStatus.FinishedState, planState, applied, applied, null, null, null);

    private static void Append(string runDirectory, params string[] lines)
    {
        File.AppendAllText(
            Path.Combine(runDirectory, "changes.jsonl"),
            string.Concat(lines.Select(line => line + "\n")),
            new UTF8Encoding(false));
    }

    // ---- the fakes ---------------------------------------------------------------------------

    /// <summary>One call the pipeline made, as the backend saw it.</summary>
    private sealed class RecordedCall
    {
        public RecordedCall(string route, object? request)
        {
            Route = route;
            Request = request;
            Json = request == null
                ? "{}"
                : JsonSerializer.Serialize(request, request.GetType());
        }

        public string Route { get; }

        public object? Request { get; }

        /// <summary>Everything the call carried, for the "no source after the copy" scan.</summary>
        public string Json { get; }
    }

    private sealed class RecordedProgress
    {
        public RecordedProgress(int applied, int total, int seq, string kind, string? subjectName)
        {
            Applied = applied;
            Total = total;
            Seq = seq;
            Kind = kind;
            SubjectName = subjectName;
        }

        public int Applied { get; }

        public int Total { get; }

        public int Seq { get; }

        public string Kind { get; }

        public string? SubjectName { get; }
    }

    private sealed class FakeBackend : IRemodelBackend
    {
        private int _polls;

        public List<RecordedCall> Calls { get; } = new List<RecordedCall>();

        public RemodelProbeReply Probe { get; set; } = new RemodelProbeReply(
            "probe-1", new SwReview.Extractor.Rms.ScopeSignals(), new string[0]);

        public RemodelOpenReply Open { get; set; } =
            new RemodelOpenReply(@"C:\runs\copy\bracket-RMS.SLDPRT", 0, true);

        public BackendRequestException? OpenFailure { get; set; }

        public BackendRequestException? StartFailure { get; set; }

        public string PlanSummary { get; set; } = @"{""moves"":0}";

        public Func<int, RemodelRunStatus> StatusAt { get; set; } =
            poll => new RemodelRunStatus(
                RemodelRunStatus.FinishedState, "saved", 0, 0, null, null, null);

        public List<string> PackageAfterPaths { get; } = new List<string>();

        /// <summary>What `POST /remodel/runs/{job}/package-after` refuses with, or null.</summary>
        public BackendRequestException? PackageAfterFailure { get; set; }

        /// <summary>
        /// How many of the first `POST .../stop` calls fail before one lands. The route is
        /// idempotent, so a stop that could not be posted is a stop that has not happened yet.
        /// </summary>
        public int StopFailures { get; set; }

        RemodelProbeReply IRemodelBackend.Probe(RemodelProbeRequest request)
        {
            Calls.Add(new RecordedCall("probe", request));
            return Probe;
        }

        RemodelOpenReply IRemodelBackend.Open(RemodelOpenRequest request)
        {
            Calls.Add(new RecordedCall("open", request));
            if (OpenFailure != null)
            {
                throw OpenFailure;
            }

            return Open;
        }

        string IRemodelBackend.Plan(string runDirectory)
        {
            Calls.Add(new RecordedCall("plan", runDirectory));
            return PlanSummary;
        }

        string IRemodelBackend.StartRun(RemodelRunRequest request)
        {
            Calls.Add(new RecordedCall("runs", request));
            if (StartFailure != null)
            {
                throw StartFailure;
            }

            return "job-42";
        }

        RemodelRunStatus IRemodelBackend.Status(string jobId)
        {
            Calls.Add(new RecordedCall("status", jobId));
            return StatusAt(_polls++);
        }

        RemodelEventPage IRemodelBackend.Events(string jobId, int after)
        {
            Calls.Add(new RecordedCall("events", jobId));
            return new RemodelEventPage(new string[0], after);
        }

        void IRemodelBackend.PackageAfter(string jobId, string packagePath)
        {
            Calls.Add(new RecordedCall("package-after", packagePath));
            if (PackageAfterFailure != null)
            {
                throw PackageAfterFailure;
            }

            PackageAfterPaths.Add(packagePath);
        }

        void IRemodelBackend.Stop(string jobId)
        {
            Calls.Add(new RecordedCall("stop", jobId));
            if (StopFailures > 0)
            {
                StopFailures--;
                throw new BackendRequestException(
                    "BackendUnavailable", "the review backend did not answer.", retryable: true);
            }
        }

        void IRemodelBackend.Close(RemodelCloseRequest request)
        {
            Calls.Add(new RecordedCall("close", request));
        }
    }

    /// <summary>
    /// The extractor, as far as this pipeline is concerned: it writes a `package.json` whose
    /// head says which profile wrote it, which is the thing the pipeline checks before it
    /// renames the file.
    /// </summary>
    private sealed class FakeDump : IReviewDump
    {
        public List<string> Folders { get; } = new List<string>();

        public List<DumpProfile> Profiles { get; } = new List<DumpProfile>();

        /// <summary>What the written package says about itself; `full` is the wrong one.</summary>
        public string Profile { get; set; } = "model_check";

        /// <summary>
        /// Which document the written package says it read. Null is the ordinary case - the one
        /// copy in the run folder - and any other value is a dump of a document this run did not
        /// make, the source included: the extractor attaches to whatever SOLIDWORKS has active,
        /// and what it had active is only knowable from the file it wrote.
        /// </summary>
        public string? DocumentPath { get; set; }

        /// <summary>Whether the written package names a document at all.</summary>
        public bool WritesADocument { get; set; } = true;

        public DumpSummary Run(
            string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
        {
            Folders.Add(outputDirectory);
            Profiles.Add(profile);
            progress("Extracting bracket.SLDPRT [Default]...");

            Directory.CreateDirectory(outputDirectory);
            string path = Path.Combine(outputDirectory, "package.json");
            string read = DocumentPath
                ?? Path.Combine(outputDirectory, "copy", "bracket-RMS.SLDPRT");
            string documents = WritesADocument
                ? @"[{""document_id"":""doc-1"",""kind"":""part"",""path"":"
                    + JsonSerializer.Serialize(read) + "}]"
                : "[]";

            File.WriteAllText(
                path,
                @"{""schema_version"":""1.3.0"",""extractor"":{""name"":""SwReview"","
                + @"""version"":""0.1.0"",""profile"":""" + Profile + @"""},""documents"":"
                + documents + "}");

            return new DumpSummary(path, components: 1, gaps: 0, documents: 1, features: 40);
        }
    }

    private sealed class FakeSeat : IRemodelSeat
    {
        public List<string> Activated { get; } = new List<string>();

        public void ActivateOrOpen(string copyPath) => Activated.Add(copyPath);
    }

    private sealed class RecordingReporter : IRemodelRunReporter
    {
        public bool StopRequested { get; set; }

        public List<KeyValuePair<string, string>> Statuses { get; } =
            new List<KeyValuePair<string, string>>();

        public List<RecordedProgress> Progress { get; } = new List<RecordedProgress>();

        public List<string> Changes { get; } = new List<string>();

        void IRemodelRunReporter.Status(string stage, string message) =>
            Statuses.Add(new KeyValuePair<string, string>(stage, message));

        void IRemodelRunReporter.Progress(
            int applied, int total, int seq, string kind, string? subjectName) =>
            Progress.Add(new RecordedProgress(applied, total, seq, kind, subjectName));

        void IRemodelRunReporter.Change(string changeRecordJson) => Changes.Add(changeRecordJson);
    }

    /// <summary>The pipeline and everything it was built over, in one place per test.</summary>
    private sealed class World
    {
        private readonly BackendRemodelPipelineTests _test;
        private int _folders;

        public World(BackendRemodelPipelineTests test)
        {
            _test = test;
            Pipeline = new BackendRemodelPipeline(
                () => Endpoint,
                () => Bridge,
                () => Document,
                Dump,
                Seat,
                Backend,
                TimeSpan.Zero);
        }

        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(8123, "a-token");

        public BridgeConfig? Bridge { get; set; } = new BridgeConfig(Pipe, Secret);

        public PageDocument? Document { get; set; } = new PageDocument(SourcePath, "Default");

        public FakeBackend Backend { get; } = new FakeBackend();

        public FakeDump Dump { get; } = new FakeDump();

        public FakeSeat Seat { get; } = new FakeSeat();

        public RecordingReporter Reporter { get; } = new RecordingReporter();

        public BackendRemodelPipeline Pipeline { get; }

        /// <summary>A run folder, created the way the host creates it before the copy.</summary>
        public string RunFolder()
        {
            string folder = Path.Combine(_test._root, "run-" + (++_folders));
            Directory.CreateDirectory(folder);
            return folder;
        }

        /// <summary>The copy, where `remodel.open` would have put it.</summary>
        public string WriteCopy(string runDirectory)
        {
            string folder = Path.Combine(runDirectory, "copy");
            Directory.CreateDirectory(folder);
            string copy = Path.Combine(folder, "bracket-RMS.SLDPRT");
            File.WriteAllText(copy, "the copy");
            return copy;
        }
    }
}
