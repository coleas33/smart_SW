using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.AccessControl;
using System.Security.Principal;
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
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 1, 1) : Finished("saved", 1);

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
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 3, 3) : Finished("saved", 3);

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
        // Edited deliberately by owner decision 159A (004 T242): the job never got its after-dump, so it fails once it
        // stops waiting for it; the run waits for that end (T239), and a job that finished had its dump.
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);

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
        // Edited deliberately by owner decision 159A (004 T242): the job never got its after-dump, so it fails once it
        // stops waiting for it; the run waits for that end (T239), and a job that finished had its dump.
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);

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
                return Awaiting("applying", 3, 3);
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
        // this test rather than poll forever. Edited deliberately by owner decision 159A (004 T242):
        // the backend refused the dump, so its job fails once it stops waiting for one; it never finishes.
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);

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
        // Edited deliberately by owner decision 159A (004 T242): the job never got its after-dump, so it fails once it
        // stops waiting for it; the run waits for that end (T239), and a job that finished had its dump.
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);

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
                case 4: return Awaiting("applying", 3, 3);
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

    /// <summary>
    /// A backend that vanishes mid-run ends the run `failed`, after an error status. *Changed deliberately 2026-10-21 (owner
    /// decision 159A, on Codex's review; 004 T238, research R19.14):* vanished means the backend process that ran the job
    /// is gone - none is running, or another runs in its place - and its worker with it; a poll that merely went
    /// unanswered is no longer the run's end (<see cref="ARunWhoseStatusPollIsNotAnsweredWaitsForItsJobToEnd"/>). The poll
    /// answers a finished run if it is asked again, so a build that waited on a gone backend fails this case rather than
    /// hanging.
    /// </summary>
    [Theory]
    [InlineData("none running")]
    [InlineData("another in its place")]
    [InlineData("another port, the same token")]
    [InlineData("the same port, another token")]
    public void ABackendThatVanishesMidRunEndsTheRunFailedAfterAnErrorStatus(string how)
    {
        var world = new World(this);
        world.Backend.StatusAt = poll =>
        {
            if (poll == 0)
            {
                return Running("applying", 4, 2);
            }

            if (poll >= 3)
            {
                return Finished("saved", 4);
            }

            // Owner decision 159A, on the final review (A2, A3): the port and the token each tell another backend.
            world.Endpoint = how == "none running" ? null
                : how == "another port, the same token" ? new BackendEndpoint(8124, "a-token")
                : how == "the same port, another token" ? new BackendEndpoint(8123, "another-token")
                : new BackendEndpoint(8124, "another-token");
            throw new BackendRequestException(
                "BackendUnavailable", "the review backend did not answer.", retryable: true);
        };

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("failed", outcome.State);
        Assert.Equal(2, outcome.ChangesApplied);
        Assert.Equal("error", world.Reporter.Statuses.Last().Key);
    }

    // ---- owner decision 159A, on Codex's review: a run is not over until its job is ------------------

    /// <summary>
    /// Owner decision 159A, on Codex's review of the merge, test first (004 T238; research R19.14; its C1, older than
    /// 159A): a status poll the backend did not answer is not the run's end. The run ended `failed` at the first poll
    /// that failed - a transient one, a backend busy past the client's 30 seconds - while the backend's worker went on
    /// applying changes; the host then closed the run's session and was free, a plan made then opened its copy on the
    /// same bridge, and the earlier run's next rename or equation, whose bridge command names no run, landed on that
    /// copy. The run now waits for its job: the page is told once that the backend is not answering, the poll is asked
    /// again, backing off, the page is told where the run stands once it answers, and the run ends as its job ends.
    /// </summary>
    [Fact]
    public void ARunWhoseStatusPollIsNotAnsweredWaitsForItsJobToEnd()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll =>
        {
            switch (poll)
            {
                case 0:
                    return Running("applying", 4, 1);
                case 1:
                case 2:
                    throw new BackendRequestException(
                        "BackendUnavailable", "the review backend did not answer: The operation has timed out", retryable: true);
                case 3:
                    return Running("applying", 4, 3);
                default:
                    return Finished("saved", 4);
            }
        };

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("saved", outcome.State);
        Assert.Equal(4, outcome.ChangesApplied);
        Assert.Equal(5, world.Backend.Calls.Count(call => call.Route == "status"));
        Assert.DoesNotContain(world.Reporter.Statuses, status => status.Key == "error");
        int waiting = Assert.Single(
            world.Reporter.Statuses.Select((status, index) => (status, index)),
            pair => pair.status.Value == BackendRemodelPipeline.BackendNotAnsweringMidRunMessage).index;
        Assert.Equal("applying", world.Reporter.Statuses[waiting].Key);
        Assert.Contains(world.Reporter.Statuses.Skip(waiting + 1), status => status.Key == "applying");
    }

    /// <summary>
    /// Owner decision 159A, on Codex's review (004 T238; its C1): the wait after a poll the backend did not answer doubles,
    /// from the poll delay, up to eight seconds, so a backend busy for a moment is asked again soon and one that stays
    /// silent is not asked twice a second for as long as it does; a poll delay of none, as these tests run with, stays none.
    /// </summary>
    [Fact]
    public void TheWaitAfterAnUnansweredPollDoublesUpToItsBound()
    {
        Assert.Equal(TimeSpan.FromSeconds(1), BackendRemodelPipeline.Longer(TimeSpan.FromMilliseconds(500)));
        Assert.Equal(TimeSpan.FromSeconds(8), BackendRemodelPipeline.Longer(TimeSpan.FromSeconds(4)));
        Assert.Equal(TimeSpan.FromSeconds(8), BackendRemodelPipeline.Longer(TimeSpan.FromSeconds(8)));
        Assert.Equal(TimeSpan.Zero, BackendRemodelPipeline.Longer(TimeSpan.Zero));
    }

    /// <summary>
    /// Owner decision 159A, on Codex's review (004 T238; its C1): Stop works while the backend does not answer. The stop the
    /// engineer asked for is tried on every poll until it lands - each fails while the backend does not answer - and the run
    /// ends as its job, stopped, ends. Before T239 the first poll that failed ended the run `failed`, with the job never told
    /// to stop.
    /// </summary>
    [Fact]
    public void AStopAskedForWhileTheBackendDoesNotAnswerReachesTheJobOnceItAnswers()
    {
        var world = new World(this);
        world.Reporter.StopRequested = true;
        world.Backend.StopFailures = 2;
        world.Backend.StatusAt = poll =>
        {
            switch (poll)
            {
                case 0:
                case 1:
                    throw new BackendRequestException(
                        "BackendUnavailable", "the review backend did not answer.", retryable: true);
                case 2:
                    return Running("applying", 4, 2);
                default:
                    return Finished("truncated", 2);
            }
        };

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("truncated", outcome.State);
        Assert.Equal(3, world.Backend.Calls.Count(call => call.Route == "stop"));
        Assert.Equal(0, world.Backend.StopFailures);
    }

    /// <summary>
    /// Owner decision 159A, on Codex's review (004 T238 - a guard; its C1): a run the backend no longer knows has no worker
    /// on it - the backend's runs live in its memory - so it is over: `failed`, after an error status. Asked again, the poll
    /// would answer a finished run, so a build that waited on such a run fails this case rather than hanging.
    /// </summary>
    [Fact]
    public void ARunTheBackendNoLongerKnowsEndsFailed()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll =>
        {
            if (poll == 0)
            {
                return Running("applying", 4, 2);
            }

            if (poll >= 3)
            {
                return Finished("saved", 4);
            }

            throw new BackendRequestException("UnknownJob", "no run 'job-42' on this backend", retryable: false);
        };

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("failed", outcome.State);
        Assert.Equal("error", world.Reporter.Statuses.Last().Key);
    }

    /// <summary>
    /// Owner decision 159A, on Codex's review, test first (004 T238; its C1): an after-dump that fails does not end the run
    /// while its job is live. The job waits for its package, then goes on to its end; the run waits for that end, and only
    /// then answers with the failure, as before. It answered at once, freeing the host for a plan while the job could still
    /// act on the copy once its wait ran out. *Edited deliberately by T242:* the page is told, as the dump fails, that the
    /// run ends when the backend has finished with the dump or stopped waiting for it.
    /// </summary>
    [Fact]
    public void AnAfterDumpThatFailsLeavesTheRunToTheEndOfItsJob()
    {
        var world = new World(this);
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "PackageAfterRefused", "the package the add-in named is not this run's package-after.json.", retryable: false);
        world.Backend.StatusAt = poll => poll <= 2 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal("PackageAfterRefused", refusal.ErrorClass);
        Assert.Equal(4, world.Backend.Calls.Count(call => call.Route == "status"));
        Assert.Single(world.Backend.Calls, call => call.Route == "package-after");
        KeyValuePair<string, string> told = Assert.Single(
            world.Reporter.Statuses, status => status.Value == BackendRemodelPipeline.AfterDumpNotConfirmedMessage);
        Assert.Equal("verifying", told.Key);
    }

    // ---- owner decision 159A, on the final review: what the page holds, and Stop, while a job waits for its dump ----

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T247; research R19.20; its S1): while a job waits for its
    /// after-dump, the backend's plan still reads `applying` - it records `verifying` once the dump has arrived - so the
    /// poll after the dump failed mapped the stage back and wrote "Applying the plan to the copy..." over
    /// <see cref="BackendRemodelPipeline.AfterDumpNotConfirmedMessage"/>, for as long as the job waited. The line keeps
    /// what it said of the dump while the job waits for it.
    /// </summary>
    [Fact]
    public void TheAfterDumpsWordsAreWhatTheLineHoldsWhileTheJobWaitsForTheDump()
    {
        var world = new World(this);
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "PackageAfterRefused", "FICT the package is not this run's.", retryable: false);
        world.Backend.StatusAt = poll => poll <= 4 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);

        Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        int told = world.Reporter.Statuses.FindIndex(
            status => status.Value == BackendRemodelPipeline.AfterDumpNotConfirmedMessage);
        Assert.True(told >= 0, "the page was never told the dump was not confirmed handed over");
        Assert.Equal("verifying", world.Reporter.Statuses[told].Key);
        Assert.Empty(world.Reporter.Statuses.Skip(told + 1));
    }

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T247; found while recording its S1): a poll not answered
    /// while the job waits for its after-dump tells the page so; and once the backend answered again the line kept that,
    /// since what the line holds while the job waits is what was said last - so it said the backend was not answering for
    /// as long as the job waited, and never again that Stop ends the wait. Once the backend answers again, the line says
    /// again what it said of the dump.
    /// </summary>
    [Fact]
    public void OnceTheBackendAnswersAgainWhileTheJobWaitsForItsDumpTheLineSaysAgainWhatItSaidOfTheDump()
    {
        var world = new World(this);
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "PackageAfterRefused", "FICT the package is not this run's.", retryable: false);
        world.Backend.StatusAt = poll =>
        {
            switch (poll)
            {
                case 0:
                case 2:
                case 3:
                    return Awaiting("applying", 3, 3);
                case 1:
                    throw new BackendRequestException(
                        "BackendUnavailable", "FICT the review backend did not answer.", retryable: true);
                default:
                    return WithoutItsDump(3);
            }
        };

        Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal(
            new[]
            {
                "verifying: " + BackendRemodelPipeline.AfterDumpNotConfirmedMessage,
                "verifying: " + BackendRemodelPipeline.BackendNotAnsweringMidRunMessage,
                "verifying: " + BackendRemodelPipeline.AfterDumpNotConfirmedMessage,
            },
            world.Reporter.Statuses
                .SkipWhile(status => status.Value != BackendRemodelPipeline.AfterDumpNotConfirmedMessage)
                .Select(status => status.Key + ": " + status.Value)
                .ToArray());
    }

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T247; its S1): a Stop asked for before the after-dump
    /// failed has landed and been honoured by the apply loop, and a Stop ends the job's wait for its dump only when it is
    /// asked for during that wait. So once the dump fails, a Stop the engineer asked for is asked again, and the wait for a
    /// dump that will not come ends on it rather than at its bound.
    /// </summary>
    [Fact]
    public void AStopAskedForBeforeTheAfterDumpFailedIsAskedAgainSoTheJobsWaitEnds()
    {
        var world = new World(this);
        world.Reporter.StopRequested = true;
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "PackageAfterRefused", "FICT the package is not this run's.", retryable: false);
        world.Backend.StatusAt = poll =>
        {
            switch (poll)
            {
                case 0:
                    return Running("applying", 3, 2);
                case 1:
                case 2:
                    return Awaiting("applying", 3, 2);
                default:
                    return new RemodelRunStatus(
                        RemodelRunStatus.FailedState, "failed", 3, 2, null, null,
                        "PackageAfterStopped: package-after.json never arrived: the engineer stopped the run while it waited");
            }
        };

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal("PackageAfterRefused", refusal.ErrorClass);
        Assert.Equal(2, world.Backend.Calls.Count(call => call.Route == "stop"));
    }

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T247; its S4, the review's probe PR2): an after-dump whose
    /// answer was lost may have reached its job, and a job that then failed elsewhere - its copy saved, its report not
    /// written - was answered with the lost answer: "backend not answering", and the host's "ended without saving the
    /// copy", while the job's own error reached neither the page nor the log. The job's own end decides now.
    /// </summary>
    [Fact]
    public void ALostAfterDumpAnswerThenAJobThatFailedElsewhereEndsWithTheJobsOwnWords()
    {
        var world = new World(this);
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "BackendUnavailable", "FICT the review backend did not answer: The operation has timed out", retryable: true);
        world.Backend.StatusAt = poll => poll <= 1
            ? Awaiting("applying", 3, 3)
            : new RemodelRunStatus(
                RemodelRunStatus.FailedState, "saved", 3, 3, null, null, "OSError: FICT the report could not be written");

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("saved", outcome.State);
        Assert.Equal(3, outcome.ChangesApplied);
        Assert.Contains(
            new KeyValuePair<string, string>("error", "OSError: FICT the report could not be written"),
            world.Reporter.Statuses);
    }

    // ---- owner decision 159A, on the final review: a Start whose answer was lost ------------------------------------

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T247; its S3, older than 159A): a Start whose answer did
    /// not come back was read as a refusal, so the host closed the run's session and was free while the job the Start had
    /// made could still run. The pipeline names the job it starts and asks the same Start again - the backend answers it
    /// with the job it made, or makes it now - so the run waits for its job; the page is told once meanwhile.
    /// </summary>
    [Fact]
    public void AStartWhoseAnswerDidNotComeBackIsAskedAgainAndTheRunWaitsForItsJob()
    {
        var world = new World(this);
        world.Backend.StartFailuresFirst.Enqueue(new BackendRequestException(
            "BackendUnavailable", "FICT the review backend did not answer: The operation has timed out", retryable: true));
        world.Backend.StatusAt = poll => Finished("saved", 2);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("saved", outcome.State);
        RemodelRunRequest[] starts = world.Backend.Calls
            .Where(call => call.Route == "runs").Select(call => (RemodelRunRequest)call.Request!).ToArray();
        Assert.Equal(2, starts.Length);
        Assert.Matches("^[0-9a-f]{32}$", starts[0].JobId);
        Assert.Equal(starts[0].JobId, starts[1].JobId);
        KeyValuePair<string, string> told = Assert.Single(
            world.Reporter.Statuses, status => status.Value == BackendRemodelPipeline.BackendNotAnsweringMidRunMessage);
        Assert.Equal("judging", told.Key);
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its S3): a Start whose answer failed as it was read -
    /// the connection reset mid-answer, not the client's refusal - is asked again too.
    /// </summary>
    [Fact]
    public void AStartWhoseAnswerFailedAsItWasReadIsAskedAgain()
    {
        var world = new World(this);
        world.Backend.StartFailuresFirst.Enqueue(new IOException("FICT the connection was reset as the answer was read."));
        world.Backend.StatusAt = poll => Finished("saved", 2);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("saved", outcome.State);
        Assert.Equal(2, world.Backend.Calls.Count(call => call.Route == "runs"));
    }

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T247; found while recording its S3): a Start answered with
    /// a body the client could not read - <c>BadResponse</c>, which only an answer of success is, since the backend answers
    /// a Start it refuses with an error class of its own - was read as a refusal, freeing the host while the job the
    /// backend had made ran. The backend took the Start, and its job is the one the pipeline named: the run waits for it,
    /// and the Start is not asked again.
    /// </summary>
    [Fact]
    public void AStartAnsweredSoTheClientCouldNotReadItRunsTheJobItNamed()
    {
        var world = new World(this);
        world.Backend.StartFailuresFirst.Enqueue(new BackendRequestException(
            "BadResponse", "FICT the backend's answer was not JSON.", retryable: false));
        world.Backend.StatusAt = poll => Finished("saved", 2);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("saved", outcome.State);
        var start = (RemodelRunRequest)Assert.Single(world.Backend.Calls, call => call.Route == "runs").Request!;
        string[] polled = world.Backend.Calls
            .Where(call => call.Route == "status").Select(call => (string)call.Request!).ToArray();
        Assert.NotEmpty(polled);
        Assert.All(polled, job => Assert.Equal(start.JobId, job));
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247; its S3): a Start not answered by a backend that is then gone is
    /// refused - the job, if the Start made one, went with the backend - and asked no further. The fake answers a Start
    /// asked too often with a failure of its own, so a build that kept asking fails rather than hangs.
    /// </summary>
    [Fact]
    public void AStartNotAnsweredByABackendThatIsThenGoneIsRefused()
    {
        var world = new World(this);
        world.Backend.StartFailuresFirst.Enqueue(new BackendRequestException(
            "BackendUnavailable", "FICT the review backend did not answer.", retryable: true));
        world.Backend.DuringStart = () => world.Endpoint = null;

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal("BackendUnavailable", refusal.ErrorClass);
        Assert.Single(world.Backend.Calls, call => call.Route == "runs");
        Assert.DoesNotContain(world.Backend.Calls, call => call.Route == "status");
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247; its S3): a Start whose answer failed as it was read, from a backend
    /// that is then gone, is refused as a backend not answering - the job, if the Start made one, went with the backend.
    /// </summary>
    [Fact]
    public void AStartWhoseAnswerFailedAsItWasReadByABackendThenGoneIsRefused()
    {
        var world = new World(this);
        world.Backend.StartFailuresFirst.Enqueue(new IOException("FICT the connection was reset as the answer was read."));
        world.Backend.DuringStart = () => world.Endpoint = null;

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal("BackendUnavailable", refusal.ErrorClass);
        Assert.IsType<IOException>(refusal.InnerException);
        Assert.Single(world.Backend.Calls, call => call.Route == "runs");
    }

    // ---- owner decision 159A, on the final review: what the review's mutations found unpinned ------------------------

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its A1): a poll that fails other than as the client's
    /// refusal - the connection reset while the answer was read - is a poll not answered, and asked again; the run ends as
    /// its job does.
    /// </summary>
    [Fact]
    public void APollThatFailsOtherThanAsTheClientsRefusalIsAskedAgain()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll =>
        {
            if (poll == 1)
            {
                throw new IOException("FICT the connection was reset as the answer was read.");
            }

            return poll == 0 ? Running("applying", 4, 1) : Finished("saved", 4);
        };

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("saved", outcome.State);
        Assert.Equal(3, world.Backend.Calls.Count(call => call.Route == "status"));
        Assert.Single(world.Reporter.Statuses, status => status.Value == BackendRemodelPipeline.BackendNotAnsweringMidRunMessage);
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its A12): a change log this side may not read ends
    /// nothing: the run is over only when its job is, and the lines are there to read on a later poll.
    /// </summary>
    [Fact]
    public void AChangeLogThisSideMayNotReadDoesNotEndTheRun()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        string log = Path.Combine(runDirectory, "changes.jsonl");
        File.WriteAllText(log, "{\"seq\":1}\n");
        world.Backend.StatusAt = poll => poll == 0 ? Running("applying", 2, 1) : Finished("saved", 2);
        var deny = new FileSystemAccessRule(
            WindowsIdentity.GetCurrent().User!, FileSystemRights.ReadData, AccessControlType.Deny);
        FileSecurity security = File.GetAccessControl(log);
        security.AddAccessRule(deny);
        File.SetAccessControl(log, security);
        try
        {
            RemodelRunOutcome outcome = world.Pipeline.Run(runDirectory, world.Reporter);

            Assert.Equal("saved", outcome.State);
            Assert.Empty(world.Reporter.Changes);
        }
        finally
        {
            security.RemoveAccessRule(deny);
            File.SetAccessControl(log, security);
        }
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its A13): a Stop that fails other than as the client's
    /// refusal is a Stop not yet posted, and posted again at the next poll.
    /// </summary>
    [Fact]
    public void AStopThatFailsOtherThanAsTheClientsRefusalIsAskedAgain()
    {
        var world = new World(this);
        world.Reporter.StopRequested = true;
        world.Backend.StopFailures = 1;
        world.Backend.StopFailure = new IOException("FICT the connection was reset as the stop was sent.");
        world.Backend.StatusAt = poll => poll <= 1 ? Running("applying", 4, poll + 1) : Finished("truncated", 2);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("truncated", outcome.State);
        Assert.Equal(2, world.Backend.Calls.Count(call => call.Route == "stop"));
        Assert.Equal(0, world.Backend.StopFailures);
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its A6): an after-dump that never reached its job, and
    /// then a backend gone - so no job is left to say how the run ended - is answered with the dump's failure, which is why
    /// the run could not be completed, not with the transport's words.
    /// </summary>
    [Fact]
    public void AnAfterDumpFailureIsTheRunsAnswerWhenItsBackendIsThenGone()
    {
        var world = new World(this);
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "PackageAfterRefused", "FICT the package is not this run's.", retryable: false);
        world.Backend.StatusAt = poll =>
        {
            if (poll == 0)
            {
                return Awaiting("applying", 3, 3);
            }

            if (poll >= 3)
            {
                return WithoutItsDump(3);
            }

            world.Endpoint = null;
            throw new BackendRequestException("BackendUnavailable", "the review backend is not running.", retryable: true);
        };

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Equal("PackageAfterRefused", refusal.ErrorClass);
        Assert.Equal(2, world.Backend.Calls.Count(call => call.Route == "status"));
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its A10): the backend not answering is told once for
    /// each time it stops answering, and where the run stands once for each time it answers again.
    /// </summary>
    [Fact]
    public void EachTimeTheBackendStopsAnsweringIsToldOnce()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll =>
        {
            switch (poll)
            {
                case 1:
                case 2:
                case 4:
                    throw new BackendRequestException("BackendUnavailable", "FICT the review backend did not answer.", retryable: true);
                case 0:
                case 3:
                    return Running("applying", 4, poll);
                default:
                    return Finished("saved", 4);
            }
        };

        world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal(
            new[] { "applying", "not answering", "applying", "not answering" },
            world.Reporter.Statuses
                .Where(status => status.Key == "applying")
                .Select(status => status.Value == BackendRemodelPipeline.BackendNotAnsweringMidRunMessage ? "not answering" : "applying")
                .ToArray());
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its A8 and A9): the waits after polls the backend did
    /// not answer double from the poll delay, and come back to it once the backend answers - read through the pipeline's
    /// own waits, which the tests' poll delay of half a second hands to a recorder rather than to the clock.
    /// </summary>
    [Fact]
    public void TheWaitsAfterUnansweredPollsDoubleAndComeBackToThePollDelayOnceAnswered()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll =>
        {
            switch (poll)
            {
                case 0:
                case 1:
                case 2:
                case 4:
                    throw new BackendRequestException("BackendUnavailable", "FICT the review backend did not answer.", retryable: true);
                case 3:
                    return Running("applying", 4, 2);
                default:
                    return Finished("saved", 4);
            }
        };

        world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal(
            new[] { 500, 1000, 2000, 500, 500 },
            world.Pauses.Select(wait => (int)wait.TotalMilliseconds).ToArray());
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T247 - a guard; its A15): a first poll not answered, before the run
    /// has a stage, is told in `judging` - a stage of a running run, where `ready` or `error` would end it on the page.
    /// </summary>
    [Fact]
    public void AFirstPollNotAnsweredIsToldInJudging()
    {
        var world = new World(this);
        world.Backend.StatusAt = poll => poll == 0
            ? throw new BackendRequestException("BackendUnavailable", "FICT the review backend did not answer.", retryable: true)
            : Finished("saved", 1);

        world.Pipeline.Run(world.RunFolder(), world.Reporter);

        KeyValuePair<string, string> told = Assert.Single(
            world.Reporter.Statuses, status => status.Value == BackendRemodelPipeline.BackendNotAnsweringMidRunMessage);
        Assert.Equal("judging", told.Key);
    }

    /// <summary>
    /// Owner decision 159A, on Codex's review, test first (004 T242; its C1): an after-dump whose answer did not come back -
    /// the backend took it, and its answer was lost - is not the run's failure once the job finishes. A job finishes only
    /// once its after-dump has arrived, so the run ends as its job did; T239 answered it with the lost answer, telling a run
    /// that saved its copy as one that failed.
    /// </summary>
    [Fact]
    public void AnAfterDumpWhoseAnswerWasLostEndsAsItsJobDidOnceTheJobFinishes()
    {
        var world = new World(this);
        world.Backend.PackageAfterFailure = new BackendRequestException(
            "BackendUnavailable", "FICT the review backend did not answer: The operation has timed out", retryable: true);
        world.Backend.StatusAt = poll => poll <= 1 ? Awaiting("applying", 3, 3) : Finished("saved", 3);

        RemodelRunOutcome outcome = world.Pipeline.Run(world.RunFolder(), world.Reporter);

        Assert.Equal("saved", outcome.State);
        Assert.Equal(3, outcome.ChangesApplied);
        Assert.Single(world.Backend.Calls, call => call.Route == "package-after");
        Assert.Single(world.Reporter.Statuses, status => status.Value == BackendRemodelPipeline.AfterDumpNotConfirmedMessage);
        Assert.DoesNotContain(world.Reporter.Statuses, status => status.Key == "error");
    }

    /// <summary>
    /// Owner decision 159A, on Codex's review (004 T242 - a guard; its C1): an after-dump this side could not write - the
    /// extractor wrote another profile's package - was never handed over, so the job fails once it stops waiting for it,
    /// and the run is answered with the dump's own failure then: not before, while the job is live, and not lost.
    /// </summary>
    [Fact]
    public void AnAfterDumpThisSideCouldNotWriteIsAnsweredOnceItsJobFails()
    {
        var world = new World(this);
        world.Dump.Profile = "full";
        world.Backend.StatusAt = poll => poll <= 1 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);

        InvalidOperationException failure = Assert.Throws<InvalidOperationException>(
            () => world.Pipeline.Run(world.RunFolder(), world.Reporter));

        Assert.Contains("'full' profile", failure.Message, StringComparison.Ordinal);
        Assert.Equal(3, world.Backend.Calls.Count(call => call.Route == "status"));
        Assert.DoesNotContain(world.Backend.Calls, call => call.Route == "package-after");
        Assert.Single(world.Reporter.Statuses, status => status.Value == BackendRemodelPipeline.AfterDumpNotConfirmedMessage);
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

    /// <summary>
    /// Owner decision 159A (004 T208): a refusal the review backend answered keeps that answer as its cause, its class
    /// and its sentence as the backend wrote them, on every route that turns one into a refusal - the open, a run's start
    /// and its after-dump. The Remodel host reads the cause to know the backend answered, and tells the page the tab's own
    /// words for the class in place of the backend's sentence, which can name the part's or the run folder's full path;
    /// the sentence goes to the add-in's log. A guard: the pipeline has always kept it.
    /// </summary>
    [Theory]
    [InlineData("open")]
    [InlineData("start")]
    [InlineData("package-after")]
    public void ARefusalTheBackendAnsweredKeepsTheAnswerAsItsCause(string route)
    {
        var world = new World(this);
        var answer = new BackendRequestException(
            "RunFolderFailed", "FICT the backend refused in C:\\Fictional\\runs\\FICT-run.", retryable: false);
        RemodelRefusal refusal;
        if (route == "open")
        {
            world.Backend.OpenFailure = answer;
            refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.OpenCopy(
                new RemodelCopyRequest(world.RunFolder(), SourcePath, null), world.Reporter));
        }
        else
        {
            if (route == "start")
            {
                world.Backend.StartFailure = answer;
            }
            else
            {
                // Edited deliberately by owner decision 159A (004 T242): a refused after-dump's job fails once it
                // stops waiting for the dump, as the backend's run does; it never finishes, and a job that
                // finished had its dump and is answered as it ended.
                world.Backend.PackageAfterFailure = answer;
                world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 3, 3) : WithoutItsDump(3);
            }

            refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.Run(world.RunFolder(), world.Reporter));
        }

        Assert.Same(answer, refusal.InnerException);
        Assert.Equal("RunFolderFailed", refusal.ErrorClass);
        Assert.Equal(answer.Message, refusal.Message);
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
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 1, 1) : Finished("saved", 1);

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
    /// With no tool service listening there is no bridge to hold a session - its teardown ended any - so a close is a
    /// quiet no-op. *Changed deliberately 2026-10-21 (owner decision 159A, on review; 004 T223, research R19.9):* this case
    /// pinned a backend that is not running as a quiet no-op too, and the host then took the close for done although the
    /// bridge may still hold the session; that half is <see cref="CloseCopyWithNoBackendRunningIsRefusedAsNotSent"/>. The
    /// host's way to deleting `copy/` goes on either way: it deletes whatever the close answers.
    /// </summary>
    [Fact]
    public void CloseCopyWithNoBridgeIsAQuietNoOp()
    {
        var world = new World(this) { Bridge = null };
        world.Pipeline.CloseCopy(world.RunFolder());

        var neither = new World(this) { Bridge = null, Endpoint = null };
        neither.Pipeline.CloseCopy(neither.RunFolder());

        Assert.Empty(world.Backend.Calls);
        Assert.Empty(neither.Backend.Calls);
    }

    /// <summary>
    /// Owner decision 159A, on review, test first (004 T223; research R19.9; the mutation review's M6): a backend that is
    /// not running cannot carry a close, and the bridge may still hold the session the run or the plan opened - a backend
    /// that stopped after the open leaves it so. The close is refused, `BackendUnavailable` and retryable, sending nothing,
    /// so the host reads it as a close that was not answered, where it was a quiet no-op it took for done.
    /// </summary>
    [Fact]
    public void CloseCopyWithNoBackendRunningIsRefusedAsNotSent()
    {
        var world = new World(this) { Endpoint = null };

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(() => world.Pipeline.CloseCopy(world.RunFolder()));

        Assert.Equal("BackendUnavailable", refusal.ErrorClass);
        Assert.True(refusal.Retryable);
        Assert.Empty(world.Backend.Calls);
    }

    // ---- native open-copy identity and SOLIDWORKS lock files -------------------------------

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void U30PlanIgnoresTheOpenCopysSolidWorksLockFile(bool withOpenRecord)
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        string copy = World.CopyOf(runDirectory);
        File.WriteAllText(Path.Combine(runDirectory, "copy", "~$bracket-RMS.SLDPRT"), "lock");
        if (withOpenRecord)
        {
            WriteOpenRecord(runDirectory, copy);
        }

        world.Pipeline.Plan(runDirectory, world.Reporter);

        Assert.Equal(new[] { copy }, world.Seat.ActivatedOpen);
        Assert.Equal("plan", world.Backend.Calls.Single().Route);
        Assert.True(File.Exists(Path.Combine(runDirectory, "package-before.json")));
    }

    [Fact]
    public void U30AfterDumpIgnoresTheOpenCopysSolidWorksLockFile()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        File.WriteAllText(Path.Combine(runDirectory, "copy", "~$bracket-RMS.SLDPRT"), "lock");
        WriteOpenRecord(runDirectory, World.CopyOf(runDirectory));
        world.Backend.StatusAt = poll => poll == 0 ? Awaiting("applying", 0, 0) : Finished("saved", 0);

        RemodelRunOutcome outcome = world.Pipeline.Run(runDirectory, world.Reporter);

        Assert.Equal("saved", outcome.State);
        Assert.Equal(new[] { World.CopyOf(runDirectory) }, world.Seat.ActivatedOpen);
        Assert.Single(world.Backend.PackageAfterPaths);
        Assert.True(File.Exists(Path.Combine(runDirectory, "package-after.json")));
    }

    [Fact]
    public void U30ActivateCopyIgnoresTheSolidWorksLockFile()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        File.WriteAllText(Path.Combine(runDirectory, "copy", "~$bracket-RMS.sldprt"), "lock");
        WriteOpenRecord(runDirectory, World.CopyOf(runDirectory));

        world.Pipeline.ActivateCopy(runDirectory);

        Assert.Equal(new[] { World.CopyOf(runDirectory) }, world.Seat.Activated);
    }

    [Fact]
    public void U30ALockAloneDoesNotBecomeACopy()
    {
        var world = new World(this);
        string runDirectory = world.RunFolder(withCopy: false);
        Directory.CreateDirectory(Path.Combine(runDirectory, "copy"));
        File.WriteAllText(Path.Combine(runDirectory, "copy", "~$bracket-RMS.SLDPRT"), "lock");

        RemodelRefusal refusal = Assert.Throws<RemodelRefusal>(
            () => world.Pipeline.ActivateCopy(runDirectory));

        Assert.Equal("CopyDiscarded", refusal.ErrorClass);
        Assert.Empty(world.Seat.Activated);
    }

    [Theory]
    [InlineData("plan")]
    [InlineData("activate")]
    public void U30TwoRealPartsAreStillRefusedWithAnExactOpenRecordAndALock(string operation)
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        File.WriteAllText(Path.Combine(runDirectory, "copy", "~$bracket-RMS.SLDPRT"), "lock");
        File.WriteAllText(Path.Combine(runDirectory, "copy", "other-RMS.SLDPRT"), "another real part");
        WriteOpenRecord(runDirectory, World.CopyOf(runDirectory));

        InvalidOperationException failure = Assert.Throws<InvalidOperationException>(() =>
        {
            if (operation == "plan")
            {
                world.Pipeline.Plan(runDirectory, world.Reporter);
            }
            else
            {
                world.Pipeline.ActivateCopy(runDirectory);
            }
        });

        Assert.Contains("holds 2 parts", failure.Message, StringComparison.Ordinal);
        Assert.Empty(world.Seat.ActivatedOpen);
        Assert.Empty(world.Seat.Activated);
        Assert.Empty(world.Dump.Folders);
        Assert.Empty(world.Backend.Calls);
    }

    [Theory]
    [InlineData("different real part")]
    [InlineData("source")]
    [InlineData("lock")]
    [InlineData("relative")]
    [InlineData("no copy path")]
    [InlineData("malformed")]
    public void U30AnOpenRecordThatDoesNotNameTheExactCopyStopsBeforeAnyActivation(string how)
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        string record = Path.Combine(runDirectory, "open.json");
        switch (how)
        {
            case "different real part":
                WriteOpenRecord(runDirectory, Path.Combine(runDirectory, "copy", "other-RMS.SLDPRT"));
                break;
            case "source":
                WriteOpenRecord(runDirectory, SourcePath);
                break;
            case "lock":
                WriteOpenRecord(runDirectory, Path.Combine(runDirectory, "copy", "~$bracket-RMS.SLDPRT"));
                break;
            case "relative":
                WriteOpenRecord(runDirectory, "bracket-RMS.SLDPRT");
                break;
            case "no copy path":
                File.WriteAllText(record, "{}");
                break;
            case "malformed":
                File.WriteAllText(record, "{");
                break;
        }

        Exception failure = Assert.ThrowsAny<Exception>(
            () => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.DoesNotContain(SourcePath, failure.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Empty(world.Seat.ActivatedOpen);
        Assert.Empty(world.Dump.Folders);
        Assert.Empty(world.Backend.Calls);
    }

    [Theory]
    [InlineData("~$bracket-RMS.SLDPRT")]
    [InlineData("other-RMS.SLDPRT")]
    public void U30APlanRefusesADumpNamingAnotherPathInTheCopyFolder(string fileName)
    {
        var world = new World(this);
        string runDirectory = world.RunFolder();
        WriteOpenRecord(runDirectory, World.CopyOf(runDirectory));
        world.Dump.DocumentPath = Path.Combine(runDirectory, "copy", fileName);

        Assert.ThrowsAny<Exception>(() => world.Pipeline.Plan(runDirectory, world.Reporter));

        Assert.Equal(new[] { World.CopyOf(runDirectory) }, world.Seat.ActivatedOpen);
        Assert.False(File.Exists(Path.Combine(runDirectory, "package-before.json")));
        Assert.True(File.Exists(Path.Combine(runDirectory, "package.json")));
        Assert.Empty(world.Backend.Calls);
    }

    private static void WriteOpenRecord(string runDirectory, string copyPath) =>
        File.WriteAllText(Path.Combine(runDirectory, "open.json"),
            JsonSerializer.Serialize(new { copy_path = copyPath }));

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

    /// <summary>
    /// How a job ends that never got its after-dump: it fails once it stops waiting for it, as the backend's run does
    /// (`test_a_dump_that_never_arrives_fails_the_run_with_the_log_intact`). It never finishes.
    /// </summary>
    private static RemodelRunStatus WithoutItsDump(int applied) =>
        new RemodelRunStatus(
            RemodelRunStatus.FailedState, "failed", applied, applied, null, null, "package-after.json never arrived");

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

        /// <summary>
        /// What the first Starts throw, one each, before a Start is answered (owner decision 159A, on the final review:
        /// S3). A Start asked more than ten times answers a failure of its own, so a build that kept asking fails a case
        /// rather than hanging it.
        /// </summary>
        public Queue<Exception> StartFailuresFirst { get; } = new Queue<Exception>();

        /// <summary>Runs inside every Start, before it answers.</summary>
        public Action? DuringStart { get; set; }

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

        /// <summary>What a Stop that fails throws: the client's refusal by default (owner decision 159A, on the final review: A13).</summary>
        public Exception? StopFailure { get; set; }

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
            DuringStart?.Invoke();
            if (StartFailure != null)
            {
                throw StartFailure;
            }

            if (StartFailuresFirst.Count > 0)
            {
                throw StartFailuresFirst.Dequeue();
            }

            if (Calls.Count(call => call.Route == "runs") > 10)
            {
                throw new InvalidOperationException("FICT the Start was asked more than ten times.");
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
                throw StopFailure ?? new BackendRequestException(
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
                TimeSpan.FromMilliseconds(500),
                wait => Pauses.Add(wait));
        }

        /// <summary>
        /// Every wait the pipeline made, in order, and none of them slept (owner decision 159A, on the final review: A8, A9):
        /// the poll delay of half a second is the product's, so the backoff after a poll not answered can be read.
        /// </summary>
        public List<TimeSpan> Pauses { get; } = new List<TimeSpan>();

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
