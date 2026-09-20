using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T122, T124, T126, T128 and T130: the Remodel tab's half of
/// `specs/004-resilient-remodeler/contracts/pane-remodel-messages.md` - `ready` and every
/// `remodel.*` row, over fakes, on a machine with no SOLIDWORKS.
///
/// It mirrors <see cref="ModelCheckHostTests"/> deliberately, because the two hosts are the
/// same shape: a small message table of their own, and the four shared rows delegated to
/// feature 003's <see cref="PaneActions"/>. What differs is what this host refuses and what it
/// owns:
///
/// <b>Every refusal is named.</b> The refusal table's `error_class` values are the whole of
/// what a run can be turned away for, and each one is asserted here with its own case. A
/// refusal costs nothing; a half-rebuilt sheet-metal part costs the engineer their afternoon.
///
/// <b>The source is never opened.</b> The only path handed to SOLIDWORKS is the copy's. The
/// source's path reaches the pipeline exactly once, as the source of a filesystem copy, and
/// never as a document to open - which is the property the constitution's re-modeler exception
/// rests on (plan.md key point 2).
///
/// <b>The state comes off the disk.</b> `remodel.result` reads the run folder rather than the
/// host's memory, so the tab answers after a restart, and `remodel.start` reads `plan.json`'s
/// `state` so a run interrupted mid-apply is refused rather than resumed.
///
/// <b>One run per host.</b> A second `remodel.plan` or `remodel.start` while a run is in flight
/// is `RunInProgress`, the same shape `settings.save` already uses for `TurnRunning` (RK-10).
/// </summary>
public sealed class RemodelHostTests
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 16, 14, 22, 1);

    private const string SourcePath = @"C:\parts\bracket.SLDPRT";

    // ---- ready / init -------------------------------------------------------------------

    [Fact]
    public void ReadyAnswersInitWithTheBackendTheTokenTheRunRootTheDocumentAndTheLimits()
    {
        using (var world = new RemodelWorld())
        {
            world.Document = new PageDocument(SourcePath, "Machined");
            world.Open();

            world.Receive("ready", "r1", new { });

            JsonElement init = world.Reply("init", "r1");
            // The page's OWN origin under `/__backend`, as `ReviewHost` and `ModelCheckHost`
            // send: one field, one meaning in all three contracts. This page does not fetch
            // today, so the value is a guard rather than a dependency - the first fetch anyone
            // adds here must be same-origin, because the page's CSP is `connect-src 'self'`
            // (docs/pane-backend-proxy.md). The port is still sent for the pane and for
            // diagnostics; no page builds a URL out of it.
            Assert.Equal(51234, init.GetProperty("backend").GetProperty("port").GetInt32());
            Assert.Equal(
                "https://swreview.invalid/__backend",
                init.GetProperty("backend").GetProperty("origin").GetString());
            Assert.DoesNotContain(
                "127.0.0.1",
                init.GetProperty("backend").GetProperty("origin").GetString()!,
                StringComparison.Ordinal);
            Assert.Equal("0FAKEtoken", init.GetProperty("token").GetString());
            Assert.Equal(world.RunRoot, init.GetProperty("run_root").GetString());

            JsonElement document = init.GetProperty("document");
            Assert.Equal(SourcePath, document.GetProperty("path").GetString());
            Assert.Equal("Machined", document.GetProperty("configuration").GetString());
            Assert.Equal("part", document.GetProperty("kind").GetString());

            JsonElement limits = init.GetProperty("limits");
            Assert.Equal(250, limits.GetProperty("max_changes").GetInt32());
            Assert.Equal(20, limits.GetProperty("max_minutes").GetInt32());
            Assert.Equal(120, limits.GetProperty("max_rebuild_seconds").GetInt32());

            Assert.True(init.GetProperty("remodel").GetProperty("available").GetBoolean());
            Assert.Equal(JsonValueKind.Null, init.GetProperty("remodel").GetProperty("message").ValueKind);

            Assert.Equal(JsonValueKind.Null, init.GetProperty("latest_run").ValueKind);
        }
    }

    /// <summary>
    /// The limits are the executor's. A page that could raise `max_changes` would be a page
    /// that could ask for five thousand writes into a document, which is exactly the bound the
    /// limits exist to be.
    /// </summary>
    [Fact]
    public void TheLimitsAreReportedAndNeverTakenFromThePage()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("ready", "r1", new
            {
                limits = new { max_changes = 99999, max_minutes = 600, max_rebuild_seconds = 9000 },
            });

            JsonElement limits = world.Reply("init", "r1").GetProperty("limits");
            Assert.Equal(250, limits.GetProperty("max_changes").GetInt32());
            Assert.Equal(20, limits.GetProperty("max_minutes").GetInt32());
            Assert.Equal(120, limits.GetProperty("max_rebuild_seconds").GetInt32());
        }
    }

    [Fact]
    public void InitCarriesNoDocumentAndNoBackendWhenThereIsNeither()
    {
        using (var world = new RemodelWorld())
        {
            world.Document = null;
            world.Endpoint = null;
            world.Open();

            world.Receive("ready", "r1", new { });

            JsonElement init = world.Reply("init", "r1");
            Assert.Equal(JsonValueKind.Null, init.GetProperty("backend").ValueKind);
            Assert.Equal(JsonValueKind.Null, init.GetProperty("token").ValueKind);
            Assert.Equal(JsonValueKind.Null, init.GetProperty("document").ValueKind);
        }
    }

    [Fact]
    public void InitCarriesTheLatestRunOnceOneHasBeenPlanned()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Receive("ready", "r2", new { });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_run");
            Assert.Equal(world.ExpectedRunDirectory, latest.GetProperty("run_dir").GetString());
            Assert.False(string.IsNullOrWhiteSpace(latest.GetProperty("at").GetString()));
            Assert.Equal("planned", latest.GetProperty("state").GetString());
        }
    }

    /// <summary>
    /// The token is a bearer credential. It belongs in exactly one message - the `init` the
    /// page needs it in - and in nothing the host ever says about a failure (FR-015).
    /// </summary>
    [Fact]
    public void TheTokenNeverReachesThePageInAStatusOrAnError()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyFailure = new IOException(
                "the copy failed while authenticating with 0FAKEtoken");

            world.Receive("remodel.plan", "p1", new { });

            string said = string.Join(
                " ", world.Posted.Where(message => !message.Contains("\"init\"")));
            Assert.DoesNotContain("0FAKEtoken", said);
            Assert.NotEmpty(world.AllPosted("error"));
        }
    }

    // ---- remodel.plan: the refusals, one per reason --------------------------------------

    [Fact]
    public void PlanIsRefusedWithNoDocumentOpen()
    {
        using (var world = new RemodelWorld())
        {
            world.Document = null;
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("NoDocument", world.ErrorClass("p1"));
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void PlanIsRefusedWhenTheAddInIsNotAttachedToSolidworks()
    {
        using (var world = new RemodelWorld())
        {
            world.UsePipeline = false;
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("NotAttached", world.ErrorClass("p1"));
        }
    }

    [Fact]
    public void InitExplainsWhenTheAttachedBridgeHasNoRemodelSeat()
    {
        using (var world = new RemodelWorld())
        {
            world.RemodelCapability = RemodelAvailability.Unavailable;
            world.Open();
            world.Receive("ready", "r1", new { });

            JsonElement remodel = world.Reply("init", "r1").GetProperty("remodel");
            Assert.False(remodel.GetProperty("available").GetBoolean());
            Assert.Equal(RemodelHost.NoSeatMessage, remodel.GetProperty("message").GetString());
        }
    }

    [Fact]
    public void AvailabilityRefreshMovesFromUnknownToUnavailableWithoutAProbe()
    {
        using (var world = new RemodelWorld())
        {
            world.RemodelCapability = RemodelAvailability.Unknown;
            world.Open();
            world.Receive("ready", "r1", new { });

            JsonElement initial = world.Reply("init", "r1").GetProperty("remodel");
            Assert.Equal(JsonValueKind.Null, initial.GetProperty("available").ValueKind);
            Assert.Equal(RemodelHost.SeatCheckingMessage, initial.GetProperty("message").GetString());

            world.RemodelCapability = RemodelAvailability.Unavailable;
            world.Host.RefreshAvailability();

            JsonElement changed = world.LastPosted("document.changed");
            Assert.False(changed.GetProperty("remodel").GetProperty("available").GetBoolean());
            Assert.Equal(
                RemodelHost.NoSeatMessage,
                changed.GetProperty("remodel").GetProperty("message").GetString());
        }
    }

    [Fact]
    public void PlanIsRefusedBeforeTheBridgeWhenTheAttachedBuildHasNoRemodelSeat()
    {
        using (var world = new RemodelWorld())
        {
            world.RemodelCapability = RemodelAvailability.Unavailable;
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("RemodelUnavailable", world.ErrorClass("p1"));
            Assert.Equal(RemodelHost.NoSeatMessage, world.Reply("error", "p1")
                .GetProperty("message").GetString());
            Assert.Empty(world.Pipeline.Calls);
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void UnknownAvailabilityIsRefusedBeforeThePipelineCanProbe()
    {
        using (var world = new RemodelWorld())
        {
            world.RemodelCapability = RemodelAvailability.Unknown;
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("RemodelUnavailable", world.ErrorClass("p1"));
            Assert.Equal(
                RemodelHost.SeatCheckingMessage,
                world.Reply("error", "p1").GetProperty("message").GetString());
            Assert.Empty(world.Pipeline.Calls);
        }
    }

    [Fact]
    public void StartIsRefusedBeforeTheBridgeIfTheSeatDisappearsAfterPlanning()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.RemodelCapability = RemodelAvailability.Unavailable;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("RemodelUnavailable", world.ErrorClass("s1"));
            Assert.DoesNotContain("run", world.Pipeline.Calls);
        }
    }

    [Theory]
    [InlineData(@"C:\parts\frame.SLDASM")]
    [InlineData(@"C:\parts\sheet.slddrw")]
    [InlineData(@"C:\parts\bracket.step")]
    public void PlanIsRefusedForAnythingThatIsNotAPart(string path)
    {
        using (var world = new RemodelWorld())
        {
            world.Document = new PageDocument(path, "Default");
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("NotAPart", world.ErrorClass("p1"));
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void PlanIsRefusedWhenTheSourceHasUnsavedChanges()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Signals.SaveFlagDirty = true;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("DocumentDirty", world.ErrorClass("p1"));
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void PlanIsRefusedWhenTheSourceIsOpenReadOnly()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Signals.ReadOnly = true;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("DocumentReadOnly", world.ErrorClass("p1"));
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void PlanIsRefusedWhenTheSourceHasExternalReferences()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Signals.ExternalReferenceCount = 2;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("ExternalReferences", world.ErrorClass("p1"));
            world.AssertNothingWasCopied();
        }
    }

    /// <summary>
    /// "`message` names <b>every</b> failing signal, not the first one": a refusal that named
    /// one of two reasons would send the engineer back to fix one thing and press Remodel
    /// again, to be told the other.
    /// </summary>
    [Fact]
    public void AScopeRefusalNamesEveryFailingSignalAndNotTheFirst()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Refusals = new[]
            {
                "weldment: the part is a weldment",
                "sheet_metal: the part carries a sheet-metal folder",
            };

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("ScopeRefused", error.GetProperty("error_class").GetString());
            string message = error.GetProperty("message").GetString()!;
            Assert.Contains("weldment", message);
            Assert.Contains("sheet_metal", message);
            world.AssertNothingWasCopied();
        }
    }

    /// <summary>
    /// A signal that could not be read is not a pass. `null` is unknown, and a run may not
    /// proceed on an unknown (data-model.md section 4.1).
    /// </summary>
    [Theory]
    [InlineData("save_flag_dirty")]
    [InlineData("read_only")]
    [InlineData("external_reference_count")]
    public void AnUnreadableSignalIsRefusedRatherThanTreatedAsAPass(string signal)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            switch (signal)
            {
                case "save_flag_dirty":
                    world.Pipeline.Signals.SaveFlagDirty = null;
                    break;
                case "read_only":
                    world.Pipeline.Signals.ReadOnly = null;
                    break;
                default:
                    world.Pipeline.Signals.ExternalReferenceCount = null;
                    break;
            }

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("ScopeRefused", error.GetProperty("error_class").GetString());
            string message = error.GetProperty("message").GetString()!;
            Assert.Contains("signal_unresolved", message);
            Assert.Contains(signal, message);
            world.AssertNothingWasCopied();
        }
    }

    /// <summary>
    /// The one refusal that happens after a copy exists, because reading the count needs a
    /// rollback and a rebuild and neither may touch the source. The copy is deleted; the run
    /// folder is left behind, because what it holds is the evidence for why the run stopped.
    /// </summary>
    [Fact]
    public void PreexistingRebuildErrorsRefuseAfterTheCopyAndDeleteTheCopy()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.RebuildErrorCount = 3;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("PreexistingRebuildErrors", world.ErrorClass("p1"));
            Assert.True(Directory.Exists(world.ExpectedRunDirectory), "the run folder was deleted");
            Assert.False(
                Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")),
                "the copy survived a PreexistingRebuildErrors refusal");
            Assert.Contains("close", world.Pipeline.Calls);
        }
    }

    /// <summary>
    /// Unknown is not zero (constitution Principle I), and the refusal is reported under the
    /// one class the contract places <b>after</b> the copy:
    /// `contracts/pane-remodel-messages.md` defines `PreexistingRebuildErrors` as "the only
    /// refusal raised after the copy exists, and the only one whose handler deletes a copy",
    /// and `ScopeRefused` as a pre-copy verdict on the source. A count that could not be read
    /// is the same baseline failure as a count that came back non-zero, so it is the same
    /// class - with a message that says the count could not be read rather than claiming
    /// errors exist, because those are different facts about the part.
    /// </summary>
    [Fact]
    public void ARebuildErrorCountThatCouldNotBeReadIsRefusedRatherThanReadAsZero()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.RebuildErrorCount = null;

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("PreexistingRebuildErrors", error.GetProperty("error_class").GetString());
            string message = error.GetProperty("message").GetString()!;
            Assert.Contains("rebuild-error count could not be read", message);
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
        }
    }

    /// <summary>
    /// The bridge's own `preexisting_rebuild_errors` handler deletes the copy and closes the
    /// document before it refuses (`contracts/bridge-remodel.md`), which reaches the pipeline
    /// as `copy_present: false`. The host then asks for a copy that is not there any more, and
    /// that is the ordinary case rather than a failure: the refusal still arrives by name, the
    /// close is still attempted - the host does not know which half the bridge managed - and
    /// the run folder is still kept, because what it holds is the evidence for why the run
    /// stopped.
    /// </summary>
    [Fact]
    public void ACopyTheBridgeHasAlreadyDeletedIsStillRefusedByNameAndThrowsNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyPresent = false;
            world.Pipeline.RebuildErrorCount = 3;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("PreexistingRebuildErrors", world.ErrorClass("p1"));
            Assert.True(Directory.Exists(world.ExpectedRunDirectory), "the run folder was deleted");
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
            Assert.Contains("close", world.Pipeline.Calls);
            Assert.DoesNotContain(
                world.AllPosted("error"),
                error => error.GetProperty("error_class").GetString() == "HostError");
        }
    }

    /// <summary>
    /// A copy that is gone is refused whatever the count says, and a count of 0 is exactly the
    /// case where the count alone would not refuse. The contract only guarantees the count comes
    /// from the bridge refusal's detail - a refusal that carries no number, or carries 0, is not
    /// excluded - so `copy_present` is the signal that decides, not the number beside it.
    ///
    /// What the run would otherwise do next is the reason this matters: with the copy deleted,
    /// `plan` dumps "the copy" in process against whatever document SOLIDWORKS still has active,
    /// which is the engineer's source. So the assertion is not only the refusal class: nothing
    /// is planned and nothing is dumped.
    /// </summary>
    [Fact]
    public void ACopyTheBridgeDeletedIsRefusedEvenWhenTheCountItReportedIsZero()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyPresent = false;
            world.Pipeline.RebuildErrorCount = 0;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("PreexistingRebuildErrors", world.ErrorClass("p1"));
            Assert.Equal(0, world.Pipeline.Count("plan"));
            Assert.True(Directory.Exists(world.ExpectedRunDirectory), "the run folder was deleted");
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
        }
    }

    [Fact]
    public void ASecondPlanWhileARunIsInFlightIsRefusedAsRunInProgress()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            // The executor is still inside `Run` when the page sends the second message, which
            // is the only moment "in flight" can be observed from a test.
            world.Pipeline.DuringRun = reporter => world.Receive("remodel.plan", "p2", new { });
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("RunInProgress", world.ErrorClass("p2"));
            Assert.Equal(1, world.Pipeline.Count("copy"));
        }
    }

    // ---- refusals the pipeline names -----------------------------------------------------

    /// <summary>
    /// T134g. The pipeline's members return readings, not error objects, so a refusal the
    /// backend or the bridge raised travels back as <see cref="RemodelRefusal"/> with its class
    /// attached. The host has to answer it as `error {error_class, message}` with that class:
    /// a host that caught only <see cref="Exception"/> would answer every one of them
    /// `HostError`, and the page would show the same sentence for a weldment, a dirty source
    /// and a dead bridge.
    /// </summary>
    [Fact]
    public void ARefusalRaisedWhileProbingIsAnsweredWithItsOwnClass()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.ProbeFailure = new RemodelRefusal(
                "BridgeUnavailable",
                "the tool service is not listening, so the part cannot be probed.",
                retryable: true);

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("BridgeUnavailable", error.GetProperty("error_class").GetString());
            Assert.Equal(
                "the tool service is not listening, so the part cannot be probed.",
                error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            world.AssertNothingWasCopied();
        }
    }

    /// <summary>
    /// The refusal the wiring brief names explicitly: a `POST /remodel/open` that came back
    /// `{error_class, message}`. The run folder is kept - it is the evidence for why the run
    /// stopped - and the class the bridge chose is the class the page is told.
    /// </summary>
    [Fact]
    public void ARefusalRaisedWhileCopyingIsAnsweredWithItsOwnClass()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyFailure = new RemodelRefusal(
                "DocumentDirty",
                "the part has unsaved changes. This feature never saves your file.",
                retryable: true);

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("DocumentDirty", error.GetProperty("error_class").GetString());
            Assert.Equal(
                "the part has unsaved changes. This feature never saves your file.",
                error.GetProperty("message").GetString());
            Assert.True(
                Directory.Exists(world.ExpectedRunDirectory),
                "the run folder is the evidence for why the run stopped and is kept");
        }
    }

    /// <summary>
    /// Anything that is <b>not</b> a named refusal stays `HostError`. Pinned beside the cases
    /// above because the two are one decision: the order of the catch clauses.
    /// </summary>
    [Fact]
    public void AFailureThatNamesNoRefusalIsStillAnsweredAsAHostError()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyFailure = new IOException("the disk is full");

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("HostError", world.ErrorClass("p1"));
        }
    }

    /// <summary>
    /// The executor's half. A refusal raised by phases B to D arrives unsolicited - the run is
    /// off the message thread and `remodel.started` was answered long ago - and the host is
    /// left with no run in flight, so the tab is usable again.
    /// </summary>
    [Fact]
    public void ARefusalRaisedByTheExecutorIsAnsweredWithItsOwnClassAndEndsTheRun()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.RunFailure = new RemodelRefusal(
                "CopyDiscarded",
                "the copy is no longer there, so there is nothing left to reorganize.",
                retryable: false);

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = Assert.Single(world.AllPosted("error"));
            Assert.Equal("CopyDiscarded", error.GetProperty("error_class").GetString());
            Assert.Equal(
                "the copy is no longer there, so there is nothing left to reorganize.",
                error.GetProperty("message").GetString());
            Assert.Equal("error", world.LastPosted("status").GetProperty("stage").GetString());

            // No run is in flight any more: the executor's `finally` ran.
            world.Receive("remodel.stop", "x1", new { });
            Assert.Equal("RunNotFound", world.ErrorClass("x1"));
        }
    }

    /// <summary>
    /// `remodel.open_copy` too: a seat that refuses by name says so, rather than being flattened
    /// into the generic `OpenFailed` the tab shows for a SOLIDWORKS that would not open the file.
    /// </summary>
    [Fact]
    public void ARefusalRaisedWhileOpeningTheCopyIsAnsweredWithItsOwnClass()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.ActivateFailure = new RemodelRefusal(
                "CopyDiscarded", "the copy is no longer on disk.", retryable: false);

            world.Receive(
                "remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("CopyDiscarded", world.ErrorClass("o1"));
        }
    }

    [Fact]
    public void AnOpenCopyFailureThatNamesNoRefusalIsStillOpenFailed()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.ActivateFailure = new IOException("SOLIDWORKS would not answer");

            world.Receive(
                "remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("OpenFailed", world.ErrorClass("o1"));
        }
    }

    // ---- remodel.plan: the happy path ----------------------------------------------------

    [Fact]
    public void PlanCreatesTheRunFolderCopiesOpensDumpsAndPlansThenRepliesPlanned()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.PlanSummaryJson = "{\"moves\":12,\"rebuild\":3,\"folders\":6}";

            world.Receive("remodel.plan", "p1", new { });

            JsonElement planned = world.Reply("remodel.planned", "p1");
            Assert.Equal(world.ExpectedRunDirectory, planned.GetProperty("run_dir").GetString());
            JsonElement summary = planned.GetProperty("plan_summary");
            Assert.Equal(12, summary.GetProperty("moves").GetInt32());
            Assert.Equal(6, summary.GetProperty("folders").GetInt32());

            // The order is not negotiable: the scope is read off the source before anything is
            // copied, and the copy exists before the dump that reads it.
            Assert.Equal(new[] { "probe", "copy", "plan" }, world.Pipeline.Calls.ToArray());
            Assert.True(File.Exists(world.ExpectedCopyPath), "no copy was made");
        }
    }

    /// <summary>
    /// T134f/T134g. The run folder becomes "the folder the pane is looking at", the same way a
    /// Model check's does (`ModelCheckHostOptions.RegisterLatestRun`): there is one answer to
    /// that question and it is not this host's to keep. Without it the Ask tab opens somewhere
    /// else and Show resolves ids through an unrelated run's package.
    ///
    /// Once, and at the moment the run is recorded - not at every message about it - because a
    /// hook fired twice would re-register a folder the engineer may since have moved past.
    /// </summary>
    [Fact]
    public void APlannedRunIsRegisteredAsThePanesLatestRunExactlyOnce()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("remodel.result", "g1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(new[] { world.ExpectedRunDirectory }, world.Registered.ToArray());
        }
    }

    /// <summary>
    /// A refused plan registers nothing, including the refusal that happens after the run
    /// folder exists. The pane is still looking at whatever it was looking at before; a folder
    /// with no package in it would degrade Show to "no full path" for every finding on the tab
    /// the engineer was actually using.
    /// </summary>
    [Fact]
    public void ARefusedPlanRegistersNoLatestRun()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.RebuildErrorCount = 3;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("PreexistingRebuildErrors", world.ErrorClass("p1"));
            Assert.Empty(world.Registered);
        }
    }

    [Fact]
    public void PlanPostsTheStagesThePageShows()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            string[] stages = world.AllPosted("status")
                .Select(status => status.GetProperty("stage").GetString()!)
                .ToArray();
            Assert.Contains("copying", stages);
            Assert.Contains("planning", stages);
            Assert.Contains("ready", stages);
        }
    }

    /// <summary>
    /// No document handle to the source is ever taken. The source's path reaches the pipeline
    /// once, as the source of a filesystem copy; the only document the run opens is the copy.
    /// </summary>
    [Fact]
    public void NoDocumentHandleToTheSourceIsEverTaken()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });

            Assert.DoesNotContain(SourcePath, world.Pipeline.Opened);
            Assert.All(world.Pipeline.Opened, path => Assert.Equal(world.ExpectedCopyPath, path));
            Assert.Equal(new[] { SourcePath }, world.Pipeline.SourcePathsSeen.ToArray());
        }
    }

    // ---- remodel.start / remodel.stop ----------------------------------------------------

    [Fact]
    public void StartRunsToCompletionAndRepliesStartedBeforeAnyProgress()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                reporter.Status("applying", "Applying change 1 of 2...");
                reporter.Progress(1, 2, 7, "reorder", "Fillet3");
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement started = world.Reply("remodel.started", "s1");
            Assert.Equal(world.ExpectedRunId, started.GetProperty("chat_id").GetString());
            Assert.True(
                world.IndexOf("remodel.started") < world.IndexOf("remodel.progress"),
                "the page saw progress before it was told the run had started");
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    [Fact]
    public void ProgressCarriesTheAppliedCountTheTotalAndTheChangeInFlight()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter => reporter.Progress(4, 11, 4, "rename", "Fillet3");

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement progress = world.LastPosted("remodel.progress");
            Assert.Equal(4, progress.GetProperty("applied").GetInt32());
            Assert.Equal(11, progress.GetProperty("total").GetInt32());
            JsonElement current = progress.GetProperty("current");
            Assert.Equal(4, current.GetProperty("seq").GetInt32());
            Assert.Equal("rename", current.GetProperty("kind").GetString());
            Assert.Equal("Fillet3", current.GetProperty("subject_name").GetString());
        }
    }

    /// <summary>
    /// Each change is pushed as it is written, so the list on the page grows during the run
    /// rather than appearing all at once at the end. The record is passed through exactly as
    /// `changes.jsonl` holds it; the host neither reshapes it nor summarizes it.
    /// </summary>
    [Fact]
    public void EachChangeRecordReachesThePageAsItIsWritten()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                reporter.Change(ChangeLine(17, "attempting"));
                reporter.Change(ChangeLine(17, "applied"));
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement[] changes = world.AllPosted("remodel.change");
            Assert.Equal(2, changes.Length);
            Assert.Equal(17, changes[0].GetProperty("seq").GetInt32());
            Assert.Equal("attempting", changes[0].GetProperty("status").GetString());
            Assert.Equal("applied", changes[1].GetProperty("status").GetString());
            Assert.Equal(
                "Fillet3", changes[1].GetProperty("subject").GetProperty("name").GetString());
        }
    }

    [Fact]
    public void StopSetsTheFlagAndTheReplyCarriesWhatWasApplied()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            // Recorded rather than asserted inside the callback: the callback runs inside the
            // host's own `try`, which turns anything thrown into an `error` message, so an
            // assertion that failed in there would be swallowed and the test would pass.
            bool? beforeStop = null;
            bool? afterStop = null;
            world.Pipeline.DuringRun = reporter =>
            {
                beforeStop = reporter.StopRequested;
                world.Receive("remodel.stop", "x1", new { });

                // The executor sees the flag, finishes the change in flight and finalizes; it
                // is never killed mid-write.
                afterStop = reporter.StopRequested;
                world.Pipeline.ChangesApplied = 6;
                world.Pipeline.RunState = "truncated";
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(false, beforeStop);
            Assert.Equal(true, afterStop);

            JsonElement stopped = world.Reply("remodel.stopped", "x1");
            Assert.Equal(6, stopped.GetProperty("changes_applied").GetInt32());
            Assert.True(
                world.IndexOf("remodel.stopped") > world.IndexOf("remodel.started"),
                "the run was reported stopped before it was reported started");
        }
    }

    [Fact]
    public void StopWithNoRunInFlightIsAnsweredRatherThanThrown()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.stop", "x1", new { });

            Assert.Equal("RunNotFound", world.ErrorClass("x1"));
        }
    }

    [Fact]
    public void StartOnARunThisHostDidNotCreateIsRunNotFound()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.start", "s1", new { run_dir = @"C:\Windows\System32" });

            Assert.Equal("RunNotFound", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// A run interrupted mid-apply leaves `applying` in `plan.json`. It is never resumed: the
    /// tree it left behind was not re-verified, and replaying changes onto it is exactly the
    /// wrong risk (data-model.md section 11).
    /// </summary>
    [Theory]
    [InlineData("applying")]
    [InlineData("verifying")]
    [InlineData("saved")]
    [InlineData("failed")]
    public void AStartOverAStateThatIsNotPlannedIsRefusedAsResumeRefused(string state)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WritePlanState(state);

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("ResumeRefused", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    [Fact]
    public void AStartOverARunWhoseCopyWasDiscardedIsRefusedAsCopyDiscarded()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("CopyDiscarded", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    [Fact]
    public void ASecondStartWhileTheRunIsInFlightIsRefusedAsRunInProgress()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
                world.Receive("remodel.start", "s2", new { run_dir = world.ExpectedRunDirectory });

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("RunInProgress", world.ErrorClass("s2"));
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// RK-14: the engineer closes or deletes the copy mid-run. The run aborts from the pane
    /// side with the change log intact, rather than writing into whatever is there now.
    /// </summary>
    [Fact]
    public void ADocumentChangedWhoseCopyWentAwayAbortsTheRun()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            bool? beforeAbort = null;
            bool? afterAbort = null;
            world.Pipeline.DuringRun = reporter =>
            {
                beforeAbort = reporter.StopRequested;
                File.Delete(world.ExpectedCopyPath);
                world.Document = null;
                world.Host.DocumentChanged();

                afterAbort = reporter.StopRequested;
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(false, beforeAbort);
            Assert.Equal(true, afterAbort);
            Assert.Contains(
                world.AllPosted("status"),
                status => status.GetProperty("stage").GetString() == "error");
        }
    }

    [Fact]
    public void ADocumentChangedNamingTheCopyItselfDoesNotAbortTheRun()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            bool? stopped = null;
            world.Pipeline.DuringRun = reporter =>
            {
                world.Document = new PageDocument(world.ExpectedCopyPath, "Default");
                world.Host.DocumentChanged();

                stopped = reporter.StopRequested;
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(false, stopped);
            Assert.DoesNotContain(
                world.AllPosted("status"),
                status => status.GetProperty("stage").GetString() == "error");
            Assert.Empty(world.AllPosted("error"));
        }
    }

    // ---- remodel.result ------------------------------------------------------------------

    /// <summary>
    /// Read from the run folder, not from memory, so the tab answers after a restart - and so
    /// the numbers on screen are the numbers in the artifacts the engineer can open.
    /// </summary>
    [Fact]
    public void ResultIsReadFromTheRunFolderRatherThanFromMemory()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WriteRunArtifacts();

            world.Receive("remodel.result", "g1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement result = world.Reply("remodel.result", "g1");
            Assert.Equal("saved", result.GetProperty("state").GetString());

            JsonElement[] changes = result.GetProperty("changes").EnumerateArray().ToArray();
            Assert.Equal(2, changes.Length);
            Assert.Equal("applied", changes[1].GetProperty("status").GetString());

            Assert.Equal(7, result.GetProperty("grade_before").GetProperty("failed").GetInt32());
            Assert.Equal(1, result.GetProperty("grade_after").GetProperty("failed").GetInt32());
            Assert.Equal("pass", result.GetProperty("geometry").GetProperty("verdict").GetString());

            JsonElement[] rebuild = result.GetProperty("rebuild_list").EnumerateArray().ToArray();
            Assert.Single(rebuild);
            Assert.Equal("backward_reference", rebuild[0].GetProperty("reason").GetString());

            Assert.Equal(
                @"C:\parts\bracket.SLDPRT",
                result.GetProperty("attestation").GetProperty("path").GetString());
        }
    }

    /// <summary>
    /// An artifact that has not been written yet is absent, never zero. A `grade_after` of zero
    /// failures would read as a perfect part.
    /// </summary>
    [Fact]
    public void AnArtifactThatIsNotThereYetIsReportedAsUnknownAndNeverAsZero()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Receive("remodel.result", "g1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement result = world.Reply("remodel.result", "g1");
            Assert.Equal(JsonValueKind.Null, result.GetProperty("grade_before").ValueKind);
            Assert.Equal(JsonValueKind.Null, result.GetProperty("grade_after").ValueKind);
            Assert.Equal(JsonValueKind.Null, result.GetProperty("geometry").ValueKind);
            Assert.Empty(result.GetProperty("changes").EnumerateArray());
            Assert.Equal("planned", result.GetProperty("state").GetString());
        }
    }

    [Fact]
    public void ResultForARunThisHostDidNotCreateIsRunNotFound()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive(
                "remodel.result", "g1", new { run_dir = Path.Combine(world.RunRoot, "made-up") });

            Assert.Equal("RunNotFound", world.ErrorClass("g1"));
        }
    }

    // ---- remodel.open_copy / remodel.discard_copy ----------------------------------------

    [Fact]
    public void OpenCopyActivatesTheCopyAndNothingElse()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("ok", "o1");
            Assert.Equal(1, world.Pipeline.Count("activate"));
            Assert.Contains(world.ExpectedCopyPath, world.Pipeline.Opened);
        }
    }

    [Fact]
    public void OpenCopyAfterADiscardIsRefusedAsCopyDiscarded()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("CopyDiscarded", world.ErrorClass("o1"));
            Assert.Equal(0, world.Pipeline.Count("activate"));
        }
    }

    /// <summary>
    /// Discard deletes the `.SLDPRT` and keeps everything else, so "what did it propose?" stays
    /// answerable after the engineer says no.
    /// </summary>
    [Fact]
    public void DiscardDeletesOnlyTheCopyAndKeepsEveryOtherArtifact()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WriteRunArtifacts();

            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement ok = world.Reply("ok", "d1");
            string[] kept = ok.GetProperty("kept")
                .EnumerateArray()
                .Select(name => name.GetString()!)
                .ToArray();

            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
            foreach (string artifact in new[]
                     {
                         "plan.json", "changes.jsonl", "report.md", "grades.json",
                         "geometry.json", "source-attestation.json", "remodel.log",
                     })
            {
                Assert.True(
                    File.Exists(Path.Combine(world.ExpectedRunDirectory, artifact)),
                    artifact + " was deleted with the copy");
                Assert.Contains(artifact, kept);
            }

            Assert.DoesNotContain("copy", kept);

            // Closed without saving, before the folder was deleted.
            Assert.Contains("close", world.Pipeline.Calls);

            // `discarded` is written to `plan.json`, which is where `remodel.result` and
            // `init.latest_run` both read `state` from (data-model.md section 11: the state is
            // "rewritten to plan.json at every transition"). Discard is the one transition no
            // other component can make - the executor has finished by then - so a host that
            // only set a field in memory would keep reporting `saved` for a run whose copy it
            // had just deleted.
            world.Receive("remodel.result", "g1", new { run_dir = world.ExpectedRunDirectory });
            JsonElement result = world.Reply("remodel.result", "g1");
            Assert.Equal("discarded", result.GetProperty("state").GetString());

            // Only `state` moved: the rest of `plan.json` is the plan, and the plan is what
            // "what did it propose?" is answered out of.
            JsonElement rebuild = result.GetProperty("rebuild_list");
            Assert.Equal(1, rebuild.GetArrayLength());
            Assert.Equal("Fillet7", rebuild[0].GetProperty("name").GetString());
            Assert.Equal(
                "parent feat:0061 is in 6-Quarantine", rebuild[0].GetProperty("detail").GetString());
        }
    }

    [Fact]
    public void ResultStillAnswersAfterTheCopyIsDiscarded()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WriteRunArtifacts();
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Receive("remodel.result", "g1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement result = world.Reply("remodel.result", "g1");
            Assert.Equal(2, result.GetProperty("changes").EnumerateArray().Count());
        }
    }

    // ---- the four shared rows ------------------------------------------------------------

    /// <summary>
    /// `report.open`, `folder.open` and `log.open` are feature 003's <see cref="PaneActions"/>,
    /// not a third copy of them. The path is resolved from the host's own run record, and a
    /// path the page supplies is not consulted at all.
    /// </summary>
    [Fact]
    public void ReportOpenAndFolderOpenGoThroughPaneActionsFromTheHostsOwnRecord()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            File.WriteAllText(Path.Combine(world.ExpectedRunDirectory, "report.md"), "# report");

            world.Receive("report.open", "r1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("folder.open", "f1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("log.open", "l1", new { });

            world.Reply("ok", "r1");
            world.Reply("ok", "f1");
            world.Reply("ok", "l1");
            Assert.Equal(
                new[]
                {
                    Path.Combine(world.ExpectedRunDirectory, "report.md"),
                    world.ExpectedRunDirectory,
                    world.LogFolder,
                },
                world.Opener.Opened.ToArray());
        }
    }

    [Fact]
    public void AFolderOpenForAPathThisHostNeverRanIsRefusedAndNothingIsOpened()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("folder.open", "f1", new { run_dir = @"C:\Windows\System32" });

            Assert.Equal("RunNotFound", world.ErrorClass("f1"));
            Assert.Empty(world.Opener.Opened);
        }
    }

    // ---- remodel.show_change -------------------------------------------------------------

    /// <summary>
    /// One resolver serves three tabs: the reply is the identical `entity.shown` payload
    /// `entity.show` already returns, and the ref comes out of `changes.jsonl` rather than off
    /// the page.
    /// </summary>
    [Fact]
    public void ShowChangeResolvesTheChangesPersistRefAndRepliesTheEntityShownPayload()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WriteRunArtifacts();

            world.Receive(
                "remodel.show_change",
                "c1",
                new { run_dir = world.ExpectedRunDirectory, change_seq = 17 });

            JsonElement shown = world.Reply("entity.shown", "c1");
            Assert.True(shown.GetProperty("ok").GetBoolean());
            Assert.Equal(0, shown.GetProperty("state_code").GetInt32());
            Assert.Equal("ok", shown.GetProperty("message").GetString());
            Assert.Equal(JsonValueKind.Null, shown.GetProperty("full_path").ValueKind);

            EntityShowRequest request = Assert.Single(world.Resolver.Requests);
            Assert.Equal("cGVyc2lzdC1yZWY=", request.PersistRef);

            // The copy is a part opened alone, so there is no scope document and no component
            // instance to reach through; the host invents neither.
            Assert.Null(request.PersistRefScope);
            Assert.Null(request.ComponentId);
        }
    }

    [Fact]
    public void ShowChangeForASeqThatIsNotInTheChangeListSaysSoAndSelectsNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WriteRunArtifacts();

            world.Receive(
                "remodel.show_change",
                "c1",
                new { run_dir = world.ExpectedRunDirectory, change_seq = 99 });

            JsonElement shown = world.Reply("entity.shown", "c1");
            Assert.False(shown.GetProperty("ok").GetBoolean());
            Assert.Contains("99", shown.GetProperty("message").GetString());
            Assert.Empty(world.Resolver.Requests);
        }
    }

    [Fact]
    public void ShowChangeForARefThatNoLongerResolvesRepliesOkFalseWithTheReason()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WriteRunArtifacts();
            world.Resolver.Outcome = EntityShowOutcome.NotShown(
                4, "the feature was deleted after change 17.", null);

            world.Receive(
                "remodel.show_change",
                "c1",
                new { run_dir = world.ExpectedRunDirectory, change_seq = 17 });

            JsonElement shown = world.Reply("entity.shown", "c1");
            Assert.False(shown.GetProperty("ok").GetBoolean());
            Assert.Equal(4, shown.GetProperty("state_code").GetInt32());
            Assert.Contains("deleted", shown.GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// A change whose subject carries no persistent reference is answered, not thrown: the
    /// change list still shows the row, and the Show button says why it cannot take the
    /// engineer there.
    /// </summary>
    [Fact]
    public void AChangeWithNoPersistRefIsAnsweredOkFalseRatherThanSelectingNothingSilently()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            File.WriteAllText(
                Path.Combine(world.ExpectedRunDirectory, "changes.jsonl"),
                "{\"seq\":3,\"kind\":\"folder.create\",\"subject\":{\"name\":\"3-Core\"},"
                + "\"status\":\"applied\"}" + Environment.NewLine);

            world.Receive(
                "remodel.show_change",
                "c1",
                new { run_dir = world.ExpectedRunDirectory, change_seq = 3 });

            JsonElement shown = world.Reply("entity.shown", "c1");
            Assert.False(shown.GetProperty("ok").GetBoolean());
            Assert.Contains("persistent reference", shown.GetProperty("message").GetString());
            Assert.Empty(world.Resolver.Requests);
        }
    }

    /// <summary>
    /// The folder half of T130, asserted where the decision is actually made: feature 003's
    /// pure <see cref="FeatureSelection"/>. A folder has no geometry, so it is selected in the
    /// tree and never zoomed to - and this host reuses that strategy rather than restating it.
    /// </summary>
    [Fact]
    public void AFolderSubjectIsSelectedWithoutAZoom()
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: @"C:\runs\copy\bracket-RMS.SLDPRT",
            scopeDocumentPath: null,
            componentSelectByIdString: null,
            featureSelectName: "3-Core",
            featureSelectType: "FTRFOLDER",
            featureName: "3-Core",
            isFolder: true));

        Assert.Equal(FeatureSelectionKind.Feature, plan.Kind);
        Assert.False(plan.Zoom);
        Assert.True(plan.Ok);
    }

    // ---- the envelope --------------------------------------------------------------------

    [Fact]
    public void AMessageTypeTheHostDoesNotHandleIsAnsweredWithAnError()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.explode", "x1", new { });

            JsonElement error = world.Reply("error", "x1");
            Assert.Equal("UnknownMessage", error.GetProperty("error_class").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());
        }
    }

    [Theory]
    [InlineData("not json at all")]
    [InlineData("[]")]
    [InlineData("{\"id\": \"x\"}")]
    [InlineData("{\"type\": 7}")]
    public void AMalformedPageMessageIsAnsweredRatherThanThrown(string json)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Host.Receive(json);

            Assert.NotEmpty(world.AllPosted("error"));
        }
    }

    [Fact]
    public void DocumentChangedPostsThePathTheConfigurationAndTheKindTheHostSees()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Document = new PageDocument(@"C:\parts\other.SLDPRT", "Machined");

            world.Host.DocumentChanged();

            JsonElement changed = world.LastPosted("document.changed");
            Assert.Equal(@"C:\parts\other.SLDPRT", changed.GetProperty("path").GetString());
            Assert.Equal("Machined", changed.GetProperty("configuration").GetString());
            Assert.Equal("part", changed.GetProperty("kind").GetString());
        }
    }

    // ---- the closed list of `status` stages -----------------------------------------------

    /// <summary>
    /// T134f: there is one closed list of `status` stages, and it is the contract's.
    ///
    /// `SwReviewAddIn.PostStatusToPages` fans one backend-lifecycle `status` out to all three
    /// pages, and all three contracts (feature 002 `pane-host-messages.md`, feature 003
    /// `model-check.md`, `contracts/pane-remodel-messages.md`) list `backend_starting`, `ready`
    /// and `error` for it: the page writes the message into its run status line and treats
    /// none of them as a run phase. The add-in still filters that fan-out through
    /// <see cref="RemodelHost.StatusStages"/>, so a stage another page grows later never
    /// reaches this one unannounced - and this asserts the list against the contract file
    /// rather than against a restated copy, so a stage added to one side and not the other
    /// fails here instead of drifting.
    ///
    /// Everything the host itself posts is checked the other way round, on every case in this
    /// class, by the channel the world collects through.
    /// </summary>
    [Fact]
    public void TheClosedListOfStagesIsTheOneTheContractDefines()
    {
        Assert.Equal(
            RemodelPageFiles.StatusStages().OrderBy(stage => stage, StringComparer.Ordinal),
            RemodelHost.StatusStages.OrderBy(stage => stage, StringComparer.Ordinal));

        // The three backend-lifecycle stages every page shares, and one that belongs to the
        // Model check page alone and never reaches this one.
        Assert.True(RemodelHost.IsStatusStage("backend_starting"));
        Assert.True(RemodelHost.IsStatusStage("ready"));
        Assert.True(RemodelHost.IsStatusStage("error"));
        Assert.False(RemodelHost.IsStatusStage("extracting"));
    }

    // ---- the world -----------------------------------------------------------------------

    private static string ChangeLine(int seq, string status) =>
        "{\"seq\":" + seq + ",\"at\":\"2026-09-16T14:22:31.481Z\",\"kind\":\"reorder\","
        + "\"subject\":{\"feature_id\":\"feat:0042\",\"name\":\"Fillet3\","
        + "\"persist_ref\":\"cGVyc2lzdC1yZWY=\"},\"status\":\"" + status + "\"}";

    private sealed class RemodelWorld : IDisposable
    {
        private readonly string _root;
        private RemodelHost? _host;

        public RemodelWorld()
        {
            _root = Path.Combine(
                Path.GetTempPath(), "SwReview.RemodelHost.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            RunRoot = Path.Combine(_root, "runs");
            Directory.CreateDirectory(RunRoot);
            LogFolder = Path.Combine(_root, "logs");
            Directory.CreateDirectory(LogFolder);
        }

        public string RunRoot { get; }

        public string LogFolder { get; }

        public PageDocument? Document { get; set; } = new PageDocument(SourcePath, "Default");

        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(51234, "0FAKEtoken");

        public FakePipeline Pipeline { get; } = new FakePipeline();

        public bool UsePipeline { get; set; } = true;

        public RemodelAvailability RemodelCapability { get; set; } = RemodelAvailability.Available;

        public FakeResolver Resolver { get; } = new FakeResolver();

        public RecordingOpener Opener { get; } = new RecordingOpener();

        public List<string> Posted { get; } = new List<string>();

        /// <summary>Every run folder the host handed to `RegisterLatestRun`, in order.</summary>
        public List<string> Registered { get; } = new List<string>();

        public RemodelHost Host =>
            _host ?? throw new InvalidOperationException("call Open() first");

        /// <summary>The folder `RunFolders.CreateForRemodel` names for this world's stamp.</summary>
        public string ExpectedRunDirectory => Path.Combine(RunRoot, ExpectedRunId);

        public string ExpectedRunId => "20260916-142201-bracket-remodel";

        public string ExpectedCopyPath =>
            Path.Combine(ExpectedRunDirectory, "copy", "bracket-RMS.SLDPRT");

        public void Open()
        {
            _host = new RemodelHost(new RemodelHostOptions(
                new CollectingChannel(Posted), () => RunRoot)
            {
                Backend = () => Endpoint,
                CurrentDocument = () => Document,
                RemodelAvailability = () => RemodelCapability,
                Pipeline = UsePipeline ? Pipeline : null,
                EntityResolver = () => Resolver,
                Opener = () => Opener,
                RegisterLatestRun = directory => Registered.Add(directory),
                LogFolder = () => LogFolder,
                Now = () => Stamp,
                Secrets = () => new[] { Endpoint?.Token },

                // Inline, so the message order a test reads is the order the page would see and
                // nothing has to be waited for. The add-in's own scheduler runs the same body on
                // a worker, which is what lets `remodel.stop` be delivered at all.
                Schedule = work => work(),
            });
        }

        public void Receive(string type, string id, object payload) =>
            Host.Receive(JsonSerializer.Serialize(new { type, id, payload }));

        public string? ErrorClass(string id) =>
            Reply("error", id).GetProperty("error_class").GetString();

        public JsonElement Reply(string type, string id)
        {
            var matches = new List<JsonElement>();
            foreach (string message in Posted)
            {
                JsonElement root = JsonDocument.Parse(message).RootElement;
                if (root.GetProperty("type").GetString() == type
                    && root.TryGetProperty("id", out JsonElement replyId)
                    && replyId.ValueKind == JsonValueKind.String
                    && replyId.GetString() == id)
                {
                    matches.Add(root.GetProperty("payload").Clone());
                }
            }

            Assert.True(
                matches.Count == 1,
                $"expected exactly one '{type}' reply to '{id}', saw {matches.Count}; posted: "
                + string.Join(" | ", Posted));
            return matches[0];
        }

        public JsonElement[] AllPosted(string type) => Posted
            .Select(message => JsonDocument.Parse(message).RootElement)
            .Where(root => root.GetProperty("type").GetString() == type)
            .Select(root => root.GetProperty("payload").Clone())
            .ToArray();

        public JsonElement LastPosted(string type)
        {
            JsonElement[] all = AllPosted(type);
            Assert.True(all.Length > 0, $"no '{type}' message was posted");
            return all[all.Length - 1];
        }

        /// <summary>Where a message type first appears in the stream the page would receive.</summary>
        public int IndexOf(string type)
        {
            for (int index = 0; index < Posted.Count; index++)
            {
                if (JsonDocument.Parse(Posted[index]).RootElement.GetProperty("type").GetString()
                    == type)
                {
                    return index;
                }
            }

            throw new InvalidOperationException(
                $"no '{type}' message was posted; posted: " + string.Join(" | ", Posted));
        }

        public void AssertNothingWasCopied()
        {
            Assert.Equal(0, Pipeline.Count("copy"));
            Assert.Empty(
                Directory.Exists(RunRoot) ? Directory.GetDirectories(RunRoot) : new string[0]);
        }

        /// <summary>Rewrites `plan.json`'s `state`, as a crash mid-run leaves it.</summary>
        public void WritePlanState(string state) =>
            File.WriteAllText(
                Path.Combine(ExpectedRunDirectory, "plan.json"),
                "{\"plan_schema\":\"1.0\",\"plan_revision\":2,\"state\":\"" + state
                + "\",\"rebuild\":[]}");

        /// <summary>The artifacts a finished run leaves behind, as the report reads them.</summary>
        public void WriteRunArtifacts()
        {
            string run = ExpectedRunDirectory;
            File.WriteAllText(
                Path.Combine(run, "plan.json"),
                "{\"plan_schema\":\"1.0\",\"plan_revision\":2,\"state\":\"saved\",\"rebuild\":["
                + "{\"feature_id\":\"feat:0044\",\"name\":\"Fillet7\","
                + "\"reason\":\"backward_reference\","
                + "\"detail\":\"parent feat:0061 is in 6-Quarantine\"}]}");
            File.WriteAllText(
                Path.Combine(run, "changes.jsonl"),
                ChangeLine(17, "attempting") + Environment.NewLine
                + ChangeLine(17, "applied") + Environment.NewLine);
            File.WriteAllText(
                Path.Combine(run, "grades.json"),
                "{\"before\":{\"checked\":24,\"failed\":7,"
                + "\"unresolved_rule_ids\":[\"rms.params.units\"]},"
                + "\"after\":{\"checked\":30,\"failed\":1,"
                + "\"unresolved_rule_ids\":[\"rms.params.units\"]},\"per_rule\":[]}");
            File.WriteAllText(
                Path.Combine(run, "geometry.json"),
                "{\"verdict\":\"pass\",\"profile\":\"IDENTITY\",\"before\":{},\"after\":{}}");
            File.WriteAllText(
                Path.Combine(run, "source-attestation.json"),
                "{\"path\":\"C:\\\\parts\\\\bracket.SLDPRT\",\"length_bytes\":12,\"sha256\":\"abc\"}");
            File.WriteAllText(Path.Combine(run, "report.md"), "# Remodel");
            File.WriteAllText(Path.Combine(run, "remodel.log"), "ping 1ms");
        }

        public void Dispose()
        {
            _host?.Dispose();
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
    }

    private sealed class CollectingChannel : IPageChannel
    {
        private static readonly IReadOnlyCollection<string> Stages =
            RemodelPageFiles.StatusStages();

        private readonly List<string> _posted;

        public CollectingChannel(List<string> posted) => _posted = posted;

        /// <summary>
        /// Collects what the page would receive - and checks every `status` on the way past.
        ///
        /// The check lives here rather than in one case of its own so that every case in this
        /// class carries it: the stages are what the page switches on
        /// (`contracts/pane-remodel-messages.md`), and the host posts them from a dozen places.
        /// </summary>
        public void PostMessage(string json)
        {
            JsonElement root = JsonDocument.Parse(json).RootElement;
            if (root.GetProperty("type").GetString() == "status")
            {
                string? stage = root.GetProperty("payload").GetProperty("stage").GetString();
                Assert.True(
                    stage != null && Stages.Contains(stage),
                    $"the host posted `status {{stage: \"{stage}\"}}`, which is not on the "
                        + "closed list contracts/pane-remodel-messages.md defines: "
                        + string.Join(", ", Stages));
            }

            _posted.Add(json);
        }
    }

    /// <summary>
    /// Everything the host asks SOLIDWORKS and the executor for, with nothing behind it.
    ///
    /// <see cref="Opened"/> is the load-bearing field: it holds every path this fake was asked
    /// to open <b>as a document</b>, and the source's path must never appear in it.
    /// </summary>
    private sealed class FakePipeline : IRemodelPipeline
    {
        public List<string> Calls { get; } = new List<string>();

        public List<string> Opened { get; } = new List<string>();

        public List<string> SourcePathsSeen { get; } = new List<string>();

        public ScopeSignals Signals { get; } = new ScopeSignals
        {
            DocumentType = 1,
            SaveFlagDirty = false,
            ReadOnly = false,
            ExternalReferenceCount = 0,
        };

        public IReadOnlyList<string> Refusals { get; set; } = new string[0];

        public int? RebuildErrorCount { get; set; } = 0;

        /// <summary>
        /// Whether the copy is on disk when <see cref="OpenCopy"/> answers. False is the
        /// bridge's `preexisting_rebuild_errors`, which deletes the copy and closes the
        /// document before it refuses (`contracts/bridge-remodel.md`).
        /// </summary>
        public bool CopyPresent { get; set; } = true;

        public Exception? ProbeFailure { get; set; }

        public Exception? CopyFailure { get; set; }

        public Exception? RunFailure { get; set; }

        public Exception? ActivateFailure { get; set; }

        public string PlanSummaryJson { get; set; } = "{\"moves\":3}";

        public Action<IRemodelRunReporter>? DuringRun { get; set; }

        public string RunState { get; set; } = "saved";

        public int ChangesApplied { get; set; }

        public string? CopyPath { get; private set; }

        public int Count(string call) => Calls.Count(name => name == call);

        public RemodelScopeReading ProbeScope()
        {
            Calls.Add("probe");
            if (ProbeFailure != null)
            {
                throw ProbeFailure;
            }

            return new RemodelScopeReading(Signals, Refusals);
        }

        public RemodelCopyReading OpenCopy(RemodelCopyRequest request, IRemodelRunReporter reporter)
        {
            Calls.Add("copy");
            SourcePathsSeen.Add(request.SourcePath);
            if (CopyFailure != null)
            {
                throw CopyFailure;
            }

            string folder = Path.Combine(request.RunDirectory, "copy");
            CopyPath = Path.Combine(
                folder,
                Path.GetFileNameWithoutExtension(request.SourcePath) + "-RMS.SLDPRT");

            // `copy_present: false` is the bridge's `preexisting_rebuild_errors`: it deleted the
            // copy and closed the document before it answered, so there is nothing on disk for
            // the host to find. The count it read comes back with it either way.
            if (CopyPresent)
            {
                Directory.CreateDirectory(folder);
                File.WriteAllText(CopyPath, "the copy");
                Opened.Add(CopyPath);
            }

            reporter.Status("copying", "Copied.");
            return new RemodelCopyReading(CopyPath, RebuildErrorCount, CopyPresent);
        }

        public void CloseCopy(string runDirectory) => Calls.Add("close");

        public string Plan(string runDirectory, IRemodelRunReporter reporter)
        {
            Calls.Add("plan");
            reporter.Status("dumping", "Reading the copy's feature tree...");
            File.WriteAllText(
                Path.Combine(runDirectory, "plan.json"),
                "{\"plan_schema\":\"1.0\",\"plan_revision\":1,\"state\":\"planned\","
                + "\"rebuild\":[]}");
            return PlanSummaryJson;
        }

        public RemodelRunOutcome Run(string runDirectory, IRemodelRunReporter reporter)
        {
            Calls.Add("run");
            DuringRun?.Invoke(reporter);
            if (RunFailure != null)
            {
                throw RunFailure;
            }

            return new RemodelRunOutcome(RunState, ChangesApplied);
        }

        public void ActivateCopy(string runDirectory)
        {
            Calls.Add("activate");
            if (ActivateFailure != null)
            {
                throw ActivateFailure;
            }

            if (CopyPath != null)
            {
                Opened.Add(CopyPath);
            }
        }
    }

    private sealed class FakeResolver : IEntityResolver
    {
        public List<EntityShowRequest> Requests { get; } = new List<EntityShowRequest>();

        public EntityShowOutcome Outcome { get; set; } = EntityShowOutcome.Shown(null);

        public EntityShowOutcome Show(EntityShowRequest request)
        {
            Requests.Add(request);
            return Outcome;
        }
    }

    private sealed class RecordingOpener : IPathOpener
    {
        public List<string> Opened { get; } = new List<string>();

        public void Open(string path) => Opened.Add(path);
    }
}
