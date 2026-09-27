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

    // ---- the run folder, bound before the open (T158's host half) ----------------------------

    /// <summary>
    /// T158: the bridge's run root is the folder the host made, handed over for this run and
    /// used up by the open. So the pipeline binds exactly the request's own folder - never one
    /// read from anywhere else - once, and before anything is said about copying or sent to the
    /// backend: a copy that could not happen is not announced.
    /// </summary>
    [Fact]
    public void OpenCopyBindsTheRequestsOwnRunFolderOnceAndBeforeTheOpen()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();

        world.Pipeline.OpenCopy(
            new RemodelCopyRequest(runDirectory, SourcePath, "Default"), world.Reporter);

        Assert.Equal(new[] { runDirectory }, world.Bound);
        Assert.Equal(new[] { "bind", "status:copying", "backend:open" }, world.Log.ToArray());
        Assert.Equal(
            runDirectory,
            Assert.IsType<RemodelOpenRequest>(world.Backend.Calls.Single().Request).RunDirectory);
    }

    /// <summary>The run root is used up at open, so a second open binds again - its own folder.</summary>
    [Fact]
    public void EveryOpenBindsItsOwnRunFolder()
    {
        var world = new World(this);
        string first = world.RunFolder();
        string second = world.RunFolder();

        world.Pipeline.OpenCopy(new RemodelCopyRequest(first, SourcePath, null), world.Reporter);
        world.Pipeline.OpenCopy(new RemodelCopyRequest(second, SourcePath, null), world.Reporter);

        Assert.Equal(new[] { first, second }, world.Bound);
        Assert.Equal(
            new[] { "bind", "status:copying", "backend:open", "bind", "status:copying", "backend:open" },
            world.Log.ToArray());
    }

    /// <summary>
    /// A bind that fails - answered false, or thrown, which is kept as the cause - is
    /// `BridgeUnavailable` in the host's own words, which is the words source the page prints
    /// verbatim: nothing was copied, no open was sent, and pressing the button again can work.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ABindThatFailsIsRefusedAsBridgeUnavailableInTheHostsWordsAndNothingIsOpened(bool throws)
    {
        var world = new World(this);
        var failure = new TimeoutException("the application thread did not answer within 5 s");
        if (throws)
        {
            world.BindFailure = failure;
        }
        else
        {
            world.BindAnswer = false;
        }

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.OpenCopy(
            new RemodelCopyRequest(world.RunFolder(), SourcePath, "Default"), world.Reporter));

        Assert.Equal("BridgeUnavailable", refusal.ErrorClass);
        Assert.Equal(RemodelHost.RunNotBoundMessage, refusal.Message);
        Assert.True(refusal.Retryable);
        Assert.Same(throws ? failure : null, refusal.InnerException);
        Assert.Empty(world.Backend.Calls);
        Assert.Empty(world.Reporter.Statuses);
        Assert.Equal(new[] { "bind" }, world.Log.ToArray());
    }

    /// <summary>
    /// With no backend or no tool service listening there is nothing to bind to and nothing the
    /// bind could be for: those refusals come first, in their own words, and nothing is bound.
    /// </summary>
    [Fact]
    public void NothingIsBoundWithoutABackendOrAToolService()
    {
        var noBackend = new World(this) { Endpoint = null };
        RemodelRefusal backendRefusal = Assert.Throws<RemodelRefusal>(() => noBackend.Pipeline.OpenCopy(
            new RemodelCopyRequest(noBackend.RunFolder(), SourcePath, null), noBackend.Reporter));

        var noBridge = new World(this) { Bridge = null };
        RemodelRefusal bridgeRefusal = Assert.Throws<RemodelRefusal>(() => noBridge.Pipeline.OpenCopy(
            new RemodelCopyRequest(noBridge.RunFolder(), SourcePath, null), noBridge.Reporter));

        Assert.Equal("BackendUnavailable", backendRefusal.ErrorClass);
        Assert.Equal("BridgeUnavailable", bridgeRefusal.ErrorClass);
        Assert.NotEqual(RemodelHost.RunNotBoundMessage, bridgeRefusal.Message);
        Assert.Empty(noBackend.Bound);
        Assert.Empty(noBridge.Bound);
    }

    /// <summary>
    /// Only the open binds. The probe reads the source before any run folder exists, and the
    /// plan, the run, Open copy and the close all address a run whose root the open used up.
    /// </summary>
    [Fact]
    public void OnlyTheOpenBinds()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("verifying", 1, 1) : Finished("saved", 1);

        world.Pipeline.ProbeScope();
        Assert.Empty(world.Bound);

        world.Pipeline.OpenCopy(new RemodelCopyRequest(runDirectory, SourcePath, null), world.Reporter);
        world.Pipeline.Plan(runDirectory, world.Reporter);
        world.Pipeline.Run(runDirectory, world.Reporter);
        world.Pipeline.ActivateCopy(runDirectory);
        world.Pipeline.CloseCopy(runDirectory);

        Assert.Equal(new[] { runDirectory }, world.Bound);
    }

    [Fact]
    public void ThePipelineIsNeverBuiltWithoutABind()
    {
        var world = new World(this);

        Assert.Throws<ArgumentNullException>(() => new BackendRemodelPipeline(
            () => world.Endpoint,
            () => world.Bridge,
            null!,
            () => world.Document,
            world.Dump,
            world.Seat,
            world.Backend));
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
        Assert.Empty(world.Seat.ActivatedOpen);
    }

    // ---- the copy, made the active document before each dump (T159) -------------------------

    /// <summary>
    /// T159: the dump reads whatever document SOLIDWORKS has active, and after the open the
    /// engineer's own part can still be the one in front. So the copy - the one part in the run
    /// folder's `copy/` - is made the active document first, and only activated: a dump that
    /// could open a document would be a second way to open one (research R13.8, D6), so
    /// `ActivateOrOpen`, `remodel.open_copy`'s call, is never made here.
    /// </summary>
    [Fact]
    public void ThePlanMakesTheCopyTheActiveDocumentBeforeItDumpsAndOnlyActivatesIt()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();

        world.Pipeline.Plan(runDirectory, world.Reporter);

        Assert.Equal(new[] { World.CopyOf(runDirectory) }, world.Seat.ActivatedOpen);
        Assert.Empty(world.Seat.Activated);
        Assert.Equal(
            new[] { "activate", "dump", "backend:plan" },
            world.Log.Where(entry => !entry.StartsWith("status:", StringComparison.Ordinal)).ToArray());
        Assert.True(File.Exists(Path.Combine(runDirectory, "package-before.json")));
    }

    /// <summary>
    /// The after-dump comes minutes later, and the engineer has been free to click back to their
    /// own part the whole time: the same activation, in the same place, before that dump too.
    /// </summary>
    [Fact]
    public void TheAfterDumpMakesTheCopyTheActiveDocumentFirstAndOnlyActivatesIt()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("verifying", 3, 3) : Finished("saved", 3);

        world.Pipeline.Run(runDirectory, world.Reporter);

        Assert.Equal(new[] { World.CopyOf(runDirectory) }, world.Seat.ActivatedOpen);
        Assert.Empty(world.Seat.Activated);
        string[] order = world.Log
            .Where(entry => entry == "activate" || entry == "dump" || entry == "backend:package-after")
            .ToArray();
        Assert.Equal(new[] { "activate", "dump", "backend:package-after" }, order);
        Assert.True(File.Exists(Path.Combine(runDirectory, "package-after.json")));
    }

    /// <summary>
    /// Every way the copy fails to become the active document before the plan: SOLIDWORKS does
    /// not have it open (it is not opened here - refused instead), something else is active
    /// afterwards - the engineer's part, another run's copy, or an answer that names no path -
    /// or the seat's call throws, which is kept as the cause. Each is `CopyNotActive` in the
    /// host's words for this moment, retryable because planning again makes a new copy, and
    /// nothing is dumped, renamed or planned.
    /// </summary>
    [Theory]
    [InlineData("not open")]
    [InlineData("the source active")]
    [InlineData("another run's copy active")]
    [InlineData("a name, not a path")]
    [InlineData("throws")]
    public void APlanWhoseCopyCannotBeMadeTheActiveDocumentIsRefusedAndNothingIsDumped(string how)
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        Exception? cause = world.Seat.Fail(how, runDirectory);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.Equal("CopyNotActive", refusal.ErrorClass);
        Assert.Equal(RemodelHost.CopyNotActiveBeforePlanMessage, refusal.Message);
        Assert.True(refusal.Retryable);
        Assert.Same(cause, refusal.InnerException);
        Assert.Empty(world.Seat.Activated);
        Assert.Empty(world.Dump.Folders);
        Assert.False(File.Exists(Path.Combine(runDirectory, "package-before.json")));
        Assert.False(File.Exists(Path.Combine(runDirectory, "package.json")));
        Assert.Empty(world.Backend.Calls);
    }

    /// <summary>
    /// The same failures after the changes: `CopyNotActive` in the host's words for that moment,
    /// not retryable - the run cannot be checked and the copy is not saved - and nothing is
    /// dumped and nothing is handed to the backend as the after reading.
    /// </summary>
    [Theory]
    [InlineData("not open")]
    [InlineData("the source active")]
    [InlineData("another run's copy active")]
    [InlineData("a name, not a path")]
    [InlineData("throws")]
    public void AnAfterDumpWhoseCopyCannotBeMadeTheActiveDocumentIsRefusedAndNothingIsPosted(string how)
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        Exception? cause = world.Seat.Fail(how, runDirectory);
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("verifying", 3, 3) : Finished("saved", 3);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.Run(runDirectory, world.Reporter));

        Assert.Equal("CopyNotActive", refusal.ErrorClass);
        Assert.Equal(RemodelHost.CopyNotActiveAfterChangesMessage, refusal.Message);
        Assert.False(refusal.Retryable);
        Assert.Same(cause, refusal.InnerException);
        Assert.Empty(world.Seat.Activated);
        Assert.Empty(world.Dump.Folders);
        Assert.False(File.Exists(Path.Combine(runDirectory, "package-after.json")));
        Assert.Empty(world.Backend.PackageAfterPaths);
        Assert.DoesNotContain(world.Backend.Calls, call => call.Route == "package-after");
    }

    /// <summary>
    /// The seat's answer is compared as a path, not as text: the copy spelt in another case, or
    /// through a `..`, is the copy, and the dump goes ahead.
    /// </summary>
    [Theory]
    [InlineData("upper case")]
    [InlineData("through a dot-dot")]
    public void TheActiveDocumentIsComparedWithTheCopyAsAPath(string spelling)
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Seat.ActiveAfter = copy => spelling == "upper case"
            ? copy.ToUpperInvariant()
            : Path.Combine(runDirectory, "copy", "..", "copy", Path.GetFileName(copy));

        world.Pipeline.Plan(runDirectory, world.Reporter);

        Assert.Single(world.Dump.Folders);
        Assert.True(File.Exists(Path.Combine(runDirectory, "package-before.json")));
    }

    /// <summary>
    /// A run folder with no copy in it has nothing to activate, and nothing is activated,
    /// opened or dumped: it is `CopyNotActive` in the words for the dump that was stopped, with
    /// the lookup's own refusal kept as the cause, since `remodel.open_copy`'s words for a missing
    /// copy speak of a plan and a report that a plan-time dump does not have yet.
    /// </summary>
    [Fact]
    public void APlanWithNoCopyInTheRunFolderActivatesNothingAndDumpsNothing()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder(withCopy: false);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.Equal("CopyNotActive", refusal.ErrorClass);
        Assert.Equal(RemodelHost.CopyNotActiveBeforePlanMessage, refusal.Message);
        Assert.Equal("CopyDiscarded", Assert.IsType<RemodelRefusal>(refusal.InnerException).ErrorClass);
        Assert.Empty(world.Seat.ActivatedOpen);
        Assert.Empty(world.Seat.Activated);
        Assert.Empty(world.Dump.Folders);
        Assert.Empty(world.Backend.Calls);
    }

    /// <summary>The same at the after-dump: no copy left to activate is `CopyNotActive` in that dump's words.</summary>
    [Fact]
    public void AnAfterDumpWithNoCopyInTheRunFolderActivatesNothingAndPostsNothing()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder(withCopy: false);
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("verifying", 3, 3) : Finished("saved", 3);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.Run(runDirectory, world.Reporter));

        Assert.Equal("CopyNotActive", refusal.ErrorClass);
        Assert.Equal(RemodelHost.CopyNotActiveAfterChangesMessage, refusal.Message);
        Assert.False(refusal.Retryable);
        Assert.Empty(world.Seat.ActivatedOpen);
        Assert.Empty(world.Dump.Folders);
        Assert.DoesNotContain(world.Backend.Calls, call => call.Route == "package-after");
    }

    /// <summary>
    /// The activation does not replace the post-check: a copy that was the active document when
    /// asked, and a dump that then read another document (the engineer clicked away in between),
    /// is still refused by the check of what the written package read.
    /// </summary>
    [Fact]
    public void ThePostCheckStillRefusesADumpThatReadAnotherDocumentAfterASuccessfulActivation()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        world.Dump.DocumentPath = SourcePath;

        Assert.ThrowsAny<Exception>(() => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.Equal(new[] { World.CopyOf(runDirectory) }, world.Seat.ActivatedOpen);
        Assert.False(File.Exists(Path.Combine(runDirectory, "package-before.json")));
        Assert.Empty(world.Backend.Calls);
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

        // Both dumps made the copy the active document, and only ever the copy.
        Assert.Equal(
            new[] { World.CopyOf(runDirectory), World.CopyOf(runDirectory) },
            world.Seat.ActivatedOpen);
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
        string runDirectory = world.RunFolder(withCopy: false);

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
        private readonly List<string> _log;
        private int _polls;

        /// <param name="log">The world's one ordered log, which every fake writes to, so a test
        /// can pin the order of a bind, an activation, a dump and a route across all of them.</param>
        public FakeBackend(List<string> log) => _log = log;

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
            Record(new RecordedCall("probe", request));
            return Probe;
        }

        RemodelOpenReply IRemodelBackend.Open(RemodelOpenRequest request)
        {
            Record(new RecordedCall("open", request));
            if (OpenFailure != null)
            {
                throw OpenFailure;
            }

            return Open;
        }

        string IRemodelBackend.Plan(string runDirectory)
        {
            Record(new RecordedCall("plan", runDirectory));
            return PlanSummary;
        }

        string IRemodelBackend.StartRun(RemodelRunRequest request)
        {
            Record(new RecordedCall("runs", request));
            if (StartFailure != null)
            {
                throw StartFailure;
            }

            return "job-42";
        }

        RemodelRunStatus IRemodelBackend.Status(string jobId)
        {
            Record(new RecordedCall("status", jobId));
            return StatusAt(_polls++);
        }

        RemodelEventPage IRemodelBackend.Events(string jobId, int after)
        {
            Record(new RecordedCall("events", jobId));
            return new RemodelEventPage(new string[0], after);
        }

        void IRemodelBackend.PackageAfter(string jobId, string packagePath)
        {
            Record(new RecordedCall("package-after", packagePath));
            if (PackageAfterFailure != null)
            {
                throw PackageAfterFailure;
            }

            PackageAfterPaths.Add(packagePath);
        }

        void IRemodelBackend.Stop(string jobId)
        {
            Record(new RecordedCall("stop", jobId));
            if (StopFailures > 0)
            {
                StopFailures--;
                throw new BackendRequestException(
                    "BackendUnavailable", "the review backend did not answer.", retryable: true);
            }
        }

        void IRemodelBackend.Close(RemodelCloseRequest request)
        {
            Record(new RecordedCall("close", request));
        }

        private void Record(RecordedCall call)
        {
            Calls.Add(call);
            _log.Add("backend:" + call.Route);
        }
    }

    private sealed class FakeSeat : IRemodelSeat
    {
        private readonly List<string> _log;

        public FakeSeat(List<string> log) => _log = log;

        /// <summary>Every copy `remodel.open_copy` asked to be activated or opened.</summary>
        public List<string> Activated { get; } = new List<string>();

        /// <summary>Every copy a dump asked to be made the active document, activate only (T159).</summary>
        public List<string> ActivatedOpen { get; } = new List<string>();

        /// <summary>
        /// What SOLIDWORKS has active once <see cref="ActivateOpenCopy"/> has run: by default the
        /// copy it was asked about, which is a seat that has the copy open and activates it.
        /// </summary>
        public Func<string, string?> ActiveAfter { get; set; } = copyPath => copyPath;

        /// <summary>What <see cref="ActivateOpenCopy"/> throws, or null.</summary>
        public Exception? ActivateFailure { get; set; }

        public void ActivateOrOpen(string copyPath) => Activated.Add(copyPath);

        public string? ActivateOpenCopy(string copyPath)
        {
            ActivatedOpen.Add(copyPath);
            _log.Add("activate");
            if (ActivateFailure != null)
            {
                throw ActivateFailure;
            }

            return ActiveAfter(copyPath);
        }

        /// <summary>
        /// Makes every activation fail <paramref name="how"/>, and answers what a refusal should
        /// carry as its cause: the exception for a seat that throws, null for every answer.
        /// </summary>
        public Exception? Fail(string how, string runDirectory)
        {
            switch (how)
            {
                case "not open":
                    // SOLIDWORKS does not have the copy open, so nothing was activated or opened.
                    ActiveAfter = _ => null;
                    return null;
                case "the source active":
                    ActiveAfter = _ => SourcePath;
                    return null;
                case "another run's copy active":
                    ActiveAfter = _ => World.CopyOf(
                        Path.Combine(Path.GetDirectoryName(runDirectory)!, "an-earlier-run"));
                    return null;
                case "a name, not a path":
                    ActiveAfter = _ => "bracket-RMS.SLDPRT";
                    return null;
                case "throws":
                    ActivateFailure = new InvalidOperationException(
                        "the SwReview Task Pane is closed, so SOLIDWORKS cannot be called.");
                    return ActivateFailure;
                default:
                    throw new ArgumentOutOfRangeException(nameof(how), how, "no such failure");
            }
        }
    }

    private sealed class RecordingReporter : IRemodelRunReporter
    {
        private readonly List<string> _log;

        public RecordingReporter(List<string> log) => _log = log;

        public bool StopRequested { get; set; }

        public List<KeyValuePair<string, string>> Statuses { get; } =
            new List<KeyValuePair<string, string>>();

        public List<RecordedProgress> Progress { get; } = new List<RecordedProgress>();

        public List<string> Changes { get; } = new List<string>();

        void IRemodelRunReporter.Status(string stage, string message)
        {
            Statuses.Add(new KeyValuePair<string, string>(stage, message));
            _log.Add("status:" + stage);
        }

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
            Backend = new FakeBackend(Log);
            Dump = new FakeRemodelDump(Log);
            Seat = new FakeSeat(Log);
            Reporter = new RecordingReporter(Log);
            Pipeline = new BackendRemodelPipeline(
                () => Endpoint,
                () => Bridge,
                Bind,
                () => Document,
                Dump,
                Seat,
                Backend,
                TimeSpan.Zero);
        }

        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(8123, "a-token");

        public BridgeConfig? Bridge { get; set; } = new BridgeConfig(Pipe, Secret);

        public PageDocument? Document { get; set; } = new PageDocument(SourcePath, "Default");

        /// <summary>
        /// Everything every fake was asked, in the one order it was asked: `bind`, `activate`,
        /// `dump`, `status:&lt;stage&gt;` and `backend:&lt;route&gt;`.
        /// </summary>
        public List<string> Log { get; } = new List<string>();

        /// <summary>Every run folder the pipeline handed to the tool service (T158).</summary>
        public List<string> Bound { get; } = new List<string>();

        /// <summary>What the bind answers: true is a tool service that took the folder.</summary>
        public bool BindAnswer { get; set; } = true;

        /// <summary>What the bind throws, or null.</summary>
        public Exception? BindFailure { get; set; }

        public FakeBackend Backend { get; }

        public FakeRemodelDump Dump { get; }

        public FakeSeat Seat { get; }

        public RecordingReporter Reporter { get; }

        public BackendRemodelPipeline Pipeline { get; }

        /// <summary>Where <see cref="WriteCopy"/> puts the copy of <paramref name="runDirectory"/>.</summary>
        public static string CopyOf(string runDirectory) =>
            Path.Combine(runDirectory, "copy", "bracket-RMS.SLDPRT");

        /// <summary>
        /// A run folder, created the way the host creates it before the copy - and, unless
        /// <paramref name="withCopy"/> is false, holding the copy, as it does once `remodel.open`
        /// has answered: the state every dump, and so every plan and every after-dump, is taken in.
        /// </summary>
        public string RunFolder(bool withCopy = true)
        {
            string folder = Path.Combine(_test._root, "run-" + (++_folders));
            Directory.CreateDirectory(folder);
            if (withCopy)
            {
                WriteCopy(folder);
            }

            return folder;
        }

        /// <summary>The copy, where `remodel.open` would have put it.</summary>
        public string WriteCopy(string runDirectory)
        {
            string copy = CopyOf(runDirectory);
            Directory.CreateDirectory(Path.GetDirectoryName(copy)!);
            File.WriteAllText(copy, "the copy");
            return copy;
        }

        /// <summary>The bind the pipeline is built with: records, logs, then answers or throws.</summary>
        private bool Bind(string runDirectory)
        {
            Bound.Add(runDirectory);
            Log.Add("bind");
            if (BindFailure != null)
            {
                throw BindFailure;
            }

            return BindAnswer;
        }
    }
}
