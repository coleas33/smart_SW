using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.ToolService;
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

    /// <summary>The tool-service attachment a world starts with: a pipe name, as the gate mints one.</summary>
    private const string FirstAttachment = "swreview-attachment-1";

    /// <summary>The attachment after a re-attach: another start, so another pipe name.</summary>
    private const string SecondAttachment = "swreview-attachment-2";

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
    /// Owner decision 155A, test first (004 T193; feature 011 research R12.9 item 9): a page that loads
    /// again asks for `init`, and `init.latest_run` carried the plan's state and nothing of whether the run
    /// was in flight, so a page that loaded again during a run offered what the host refuses and could not
    /// stop the run. `init.latest_run.running` says so: true from `remodel.started` while the run is in
    /// flight.
    /// </summary>
    [Fact]
    public void AnInitAnsweredWhileTheRunIsInFlightSaysTheLatestRunIsRunning()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                world.WritePlanState("applying");
                world.Receive("ready", "r2", new { });
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_run");
            Assert.Equal(world.ExpectedRunDirectory, latest.GetProperty("run_dir").GetString());
            Assert.Equal("applying", latest.GetProperty("state").GetString());
            Assert.True(latest.GetProperty("running").GetBoolean());
        }
    }

    /// <summary>
    /// Owner decision 155A (004 T193): and false for a run that is not in flight - a plan waiting for Start,
    /// one Start refused, a run that has ended, and a plan whose copy was discarded.
    /// </summary>
    [Theory]
    [InlineData("planned")]
    [InlineData("refused")]
    [InlineData("ended")]
    [InlineData("discarded")]
    public void AnInitSaysTheLatestRunIsNotRunningWhenNoRunIsInFlight(string when)
    {
        using (var world = new RemodelWorld { StartValidated = when != "refused" })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            if (when == "refused" || when == "ended")
            {
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            }
            else if (when == "discarded")
            {
                world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            }

            world.Receive("ready", "r2", new { });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_run");
            Assert.False(latest.GetProperty("running").GetBoolean());

            // Edited deliberately by owner decision 159A, on the final review (004 T251): nor does it carry a word.
            Assert.Equal(JsonValueKind.Null, latest.GetProperty("status").ValueKind);
        }
    }

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T251; research R19.22; its nit): a page that loads again
    /// while its run runs showed "Running..." where the page that never loaded again shows the run's last word - the
    /// backend not answering above all, which is told once. <c>init.latest_run.status</c> carries that word while the run
    /// is in flight: the host's own first one, then the last the pipeline posted.
    /// </summary>
    [Fact]
    public void AnInitAnsweredWhileTheRunIsInFlightCarriesTheRunsLastWord()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                world.Receive("ready", "r2", new { });
                reporter.Status("applying", BackendRemodelPipeline.BackendNotAnsweringMidRunMessage);
                world.Receive("ready", "r3", new { });
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement first = world.Reply("init", "r2").GetProperty("latest_run").GetProperty("status");
            Assert.Equal("judging", first.GetProperty("stage").GetString());
            Assert.Equal(RemodelHost.RunningThePlanMessage, first.GetProperty("message").GetString());
            JsonElement last = world.Reply("init", "r3").GetProperty("latest_run").GetProperty("status");
            Assert.Equal("applying", last.GetProperty("stage").GetString());
            Assert.Equal(BackendRemodelPipeline.BackendNotAnsweringMidRunMessage, last.GetProperty("message").GetString());
        }
    }

    // ---- 004 T259: the host's stopping words survive a page reload -------------------------

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void AnInitWhileStoppingKeepsTheHostsLatestWord(bool copyGone)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                reporter.Status("verifying", "FICT checking the copy.");
                if (copyGone)
                {
                    File.Delete(world.ExpectedCopyPath);
                    world.Host.DocumentChanged();
                }
                else
                {
                    world.Receive("remodel.stop", "x1", new { });
                }

                Assert.True(reporter.StopRequested);
                world.Receive("ready", "r2", new { });
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_run");
            Assert.True(latest.GetProperty("running").GetBoolean());
            JsonElement status = latest.GetProperty("status");
            Assert.Equal("applying", status.GetProperty("stage").GetString());
            Assert.Equal(copyGone ? RemodelHost.CopyGoneMessage : RemodelHost.StoppingMessage,
                status.GetProperty("message").GetString());
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

    /// <summary>
    /// U13 (docs/history/pane-findings-2026-09-20-review-gui.md section 6): the no-seat refusal is a
    /// build capability said in an engineer's words, not a console command. The Task Pane is
    /// read by someone with a part open in SOLIDWORKS; the probe command is for the testing
    /// handover, and following it with the part still open is the wrong procedure anyway.
    /// </summary>
    [Fact]
    public void TheNoSeatMessageIsPlainWordsAndNamesNoCommand()
    {
        Assert.Equal(
            "Remodel is not in this build yet. This tab will not change the open part.",
            RemodelHost.NoSeatMessage);
        Assert.DoesNotContain("swreview-extract", RemodelHost.NoSeatMessage, StringComparison.Ordinal);
        Assert.DoesNotContain("--", RemodelHost.NoSeatMessage, StringComparison.Ordinal);
    }

    /// <summary>The still-checking message names no command either; it asks for a moment.</summary>
    [Fact]
    public void TheSeatCheckingMessageNamesNoCommand()
    {
        Assert.DoesNotContain("swreview-extract", RemodelHost.SeatCheckingMessage, StringComparison.Ordinal);
        Assert.DoesNotContain("--", RemodelHost.SeatCheckingMessage, StringComparison.Ordinal);
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

    /// <summary>
    /// Owner decision 159A (004 T210; research R18.7 item 2): an unsaved part is refused retryable whoever refuses it -
    /// saving it, or closing it unsaved and opening it again, makes the same press succeed. This host's own reading of the
    /// probe's signals has always said so; the backend's mapping of the bridge's `source_dirty`, on the probe and the open,
    /// did not and does now (<c>test_chat_remodel_routes.py</c>), and the flag of a refusal the backend answered reaches the
    /// page as the backend gave it. A guard of this host's route, and of the flag passed on.
    /// </summary>
    [Theory]
    [InlineData("signal")]
    [InlineData("probe")]
    [InlineData("open")]
    public void AnUnsavedPartIsRefusedRetryableOnEveryRoute(string route)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            const string said = "'C:\\Fictional\\FICT-bracket.SLDPRT' has unsaved changes.";
            if (route == "signal")
            {
                world.Pipeline.Signals.SaveFlagDirty = true;
            }
            else if (route == "probe")
            {
                world.Pipeline.ProbeFailure = TheBackends("DocumentDirty", said, retryable: true);
            }
            else
            {
                world.Pipeline.CopyFailure = TheBackends("DocumentDirty", said, retryable: true);
            }

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("DocumentDirty", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.DocumentDirtyMessage, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
        }
    }

    /// <summary>
    /// U26: the host no longer refuses a read-only source whose save flag the probe believed.
    /// What happens to the source file itself is asserted where the real copy code runs, not over
    /// this fake pipeline, which never touches it: <c>RemodelOpenHandlerTests</c>'
    /// <c>ProbeAndOpen_OnAReadOnlySourceFile_MakeAWritableCopyAndLeaveTheSourceExactlyAsItWas</c>
    /// and <c>RemodelCopyTests.AReadOnlySourceIsCopiedAndTheCopyIsWritable</c>.
    /// </summary>
    [Fact]
    public void ACleanReadOnlySourceIsNotRefusedByTheHost()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Signals.ReadOnly = true;
            world.Pipeline.Signals.SaveFlagDirty = false;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal(1, world.Pipeline.Count("copy"));
            Assert.Equal(1, world.Pipeline.Count("plan"));
        }
    }

    /// <summary>
    /// U26 (default taken 2026-09-28, the owner may revise): a read-only source whose save flag
    /// the probe could not believe - SOLIDWORKS set to discard changes to read-only documents
    /// without asking, so unsaved edits read as clean - is refused before any copy, and the
    /// refusal names the option and the two ways past it.
    /// </summary>
    [Fact]
    public void AReadOnlySourceWhoseUnsavedChangesCannotBeSeenIsRefusedNamingTheOption()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Signals.ReadOnly = true;
            world.Pipeline.Signals.SaveFlagDirty = null;

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("ScopeRefused", error.GetProperty("error_class").GetString());
            string message = error.GetProperty("message").GetString()!;
            Assert.Contains("signal_unresolved: save_flag_dirty", message);
            Assert.Contains("Don't prompt to save read-only referenced documents", message);
            Assert.Contains("turn that option off", message);
            Assert.Contains("check the part out", message);
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void ReadOnlySourceWithUnsavedChangesIsStillRefusedBeforeTheCopy()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Signals.ReadOnly = true;
            world.Pipeline.Signals.SaveFlagDirty = true;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("DocumentDirty", world.ErrorClass("p1"));
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void ReadOnlySourceWithExternalReferencesIsStillRefusedBeforeTheCopy()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.Signals.ReadOnly = true;
            world.Pipeline.Signals.ExternalReferenceCount = 1;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("ExternalReferences", world.ErrorClass("p1"));
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

    // ---- owner decision 155A: the refusals that named a path, in the tab's own words ---------

    /// <summary>
    /// The part the bridge's sentences name, fictional, spelled as <c>RemodelScopeProbe.Probe</c> and
    /// <c>BridgeDispatcher.RecheckSource</c> spell a part's full path.
    /// </summary>
    private const string BridgePart = @"C:\Fictional\FICT-bracket.SLDPRT";

    /// <summary>
    /// The three ways a plan meets <c>DocumentDirty</c> and <c>ExternalReferences</c>: this host's own
    /// reading of the probe's signals, which the bridge as built never reaches; the bridge's probe, which
    /// refuses before it answers a signal; and the bridge's reading of the part again inside
    /// <c>remodel.open</c>, before the copy. The last two carry the bridge's sentence, which names the
    /// part's full path, through the backend unchanged.
    /// </summary>
    public static IEnumerable<object[]> PartRefusalRoutes => new[]
    {
        new object[] { "DocumentDirty", "signal" },
        new object[] { "DocumentDirty", "probe" },
        new object[] { "DocumentDirty", "open" },
        new object[] { "ExternalReferences", "signal" },
        new object[] { "ExternalReferences", "probe" },
        new object[] { "ExternalReferences", "open" },
    };

    /// <summary>
    /// Owner decision 155A, test first (004 T189): an unsaved part and a part that references other files
    /// are refused in the tab's own plain words whoever refused them, and no path reaches the page - not in
    /// the refusal, and not in the run line's `status {stage: "error"}` a failed call posts beside it.
    /// The host's sentences for the two classes are the ones it already had for its own reading of the
    /// probe, which the bridge never reached: its probe refuses `source_dirty` and `external_refs` before
    /// it answers a dirty save flag or a count of references.
    /// </summary>
    [Theory]
    [MemberData(nameof(PartRefusalRoutes))]
    public void APartRefusalReachesThePageInTheTabsOwnWordsWhoeverRefusedItAndNamesNoPath(
        string errorClass, string route)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            bool dirty = errorClass == "DocumentDirty";
            string bridgeSentence = dirty
                ? (route == "probe"
                    ? $"'{BridgePart}' has unsaved changes. The copy would be taken from the file on disk "
                        + "and would not be the part the engineer is looking at."
                    : $"'{BridgePart}' has been edited since the probe and has unsaved changes.")
                : (route == "probe"
                    ? $"'{BridgePart}' has 2 external file reference(s). Reorganizing a part whose "
                        + "geometry is driven from another document is out of scope in v1."
                    : $"'{BridgePart}' has 1 external file reference(s) now.");
            var refusal = new RemodelRefusal(errorClass, bridgeSentence, retryable: false);
            switch (route)
            {
                case "signal":
                    if (dirty)
                    {
                        world.Pipeline.Signals.SaveFlagDirty = true;
                    }
                    else
                    {
                        world.Pipeline.Signals.ExternalReferenceCount = 2;
                    }

                    break;
                case "probe":
                    world.Pipeline.ProbeFailure = refusal;
                    break;
                default:
                    world.Pipeline.CopyFailure = refusal;
                    break;
            }

            world.Receive("remodel.plan", "p1", new { });

            string words = dirty ? RemodelHost.DocumentDirtyMessage : RemodelHost.ExternalReferencesMessage;
            JsonElement error = world.Reply("error", "p1");
            Assert.Equal(errorClass, error.GetProperty("error_class").GetString());
            Assert.Equal(words, error.GetProperty("message").GetString());
            Assert.All(
                world.AllPosted("status").Where(status => status.GetProperty("stage").GetString() == "error"),
                status => Assert.Equal(words, status.GetProperty("message").GetString()));
            AssertNoPathWasPosted(world);
            Assert.Equal(0, world.Pipeline.Count("plan"));
        }
    }

    /// <summary>
    /// Owner decision 155A (004 T189): `RunNotFound` - a run folder the page names that this host has no
    /// record of - is answered in one plain sentence, naming no path, on every row that looks a run up:
    /// the host's own, and the shared rows' lookup (`report.open`, `folder.open`, `entity.show`).
    /// </summary>
    [Theory]
    [InlineData("remodel.start")]
    [InlineData("remodel.result")]
    [InlineData("remodel.open_copy")]
    [InlineData("remodel.discard_copy")]
    [InlineData("remodel.show_change")]
    [InlineData("report.open")]
    [InlineData("folder.open")]
    [InlineData("entity.show")]
    public void ARunThisHostDoesNotHaveIsRefusedInPlainWordsThatNameNoPath(string type)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            int before = world.Posted.Count;
            const string unknown = @"C:\Fictional\runs\20260101-000000-FICT-remodel";

            world.Receive(type, "x1", new { run_dir = unknown, change_seq = 1, persist_ref = "FICT-ref" });

            JsonElement error = world.Reply("error", "x1");
            Assert.Equal("RunNotFound", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.RunNotFoundMessage, error.GetProperty("message").GetString());
            AssertNoPathWasPosted(world, before);
            Assert.Equal(0, world.Pipeline.Count("run"));
            Assert.Equal(0, world.Pipeline.Count("activate"));
            Assert.Empty(world.Opener.Opened);
        }
    }

    /// <summary>
    /// Owner decision 155A (004 T189): the stop when the run's copy goes away mid-run - RK-14, a Start's run
    /// only - is told in plain words that name no path, where it named the copy's full path.
    /// </summary>
    [Fact]
    public void TheStopWhenTheCopyIsGoneIsToldInPlainWordsThatNameNoPath()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            int before = -1;
            world.Pipeline.DuringRun = reporter =>
            {
                before = world.Posted.Count;
                File.Delete(world.ExpectedCopyPath);
                world.Document = null;
                world.Host.DocumentChanged();
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Single(
                world.Posted.Skip(before)
                    .Select(json => JsonDocument.Parse(json).RootElement)
                    .Where(root => root.GetProperty("type").GetString() == "status")
                    .Select(root => root.GetProperty("payload").Clone()),
                status => status.GetProperty("message").GetString() == RemodelHost.CopyGoneMessage);
            AssertNoPathWasPosted(world, before);
        }
    }

    /// <summary>
    /// Owner decision 155A (004 T189): the four sentences, word for word. Each says what was not done and
    /// how to go on, by the button's label where there is one, and names no path, no command and none of
    /// the build's plumbing; the two refusals of a plan and the copy-gone stop vouch for the engineer's
    /// part alone, as the tab's other refusals do.
    /// </summary>
    [Fact]
    public void TheRefusalsThatNamedAPathAreThePlainWordsOfTheTab()
    {
        Assert.Equal(
            "Your part has unsaved changes, and the re-modeler copies the part as it is saved on disk, so "
            + "nothing was copied and no new plan was made. Your part was not changed. Save it, or close it "
            + "without saving and open it again, then press Remodel a copy again.",
            RemodelHost.DocumentDirtyMessage);
        Assert.Equal(
            "This part references other files, which this remodel cannot copy with it, so nothing was "
            + "copied and no new plan was made. Your part was not changed. This version remodels only "
            + "parts that reference no other files.",
            RemodelHost.ExternalReferencesMessage);
        Assert.Equal(
            "This tab no longer has that run, so nothing was done with it. Press Remodel a copy to plan "
            + "again.",
            RemodelHost.RunNotFoundMessage);
        Assert.Equal(
            "The copy is gone, so the run is stopping: the change in flight is finished first, and the "
            + "change log stays in the run folder. Your part was not changed. Once the run has ended, "
            + "press Remodel a copy to plan again.",
            RemodelHost.CopyGoneMessage);

        foreach (string message in new[]
                 {
                     RemodelHost.DocumentDirtyMessage,
                     RemodelHost.ExternalReferencesMessage,
                     RemodelHost.RunNotFoundMessage,
                     RemodelHost.CopyGoneMessage,
                 })
        {
            AssertPlainWords(message);
            Assert.DoesNotContain("/", message, StringComparison.Ordinal);
            Assert.DoesNotContain("run_dir", message, StringComparison.Ordinal);
        }
    }

    /// <summary>A posted message with its JSON escapes undone, so a path reads as it would on the page.</summary>
    private static string Unescaped(string json) => Regex.Unescape(json);

    /// <summary>
    /// Owner decision 155A: no message posted from <paramref name="from"/> on names a path - a drive's
    /// root, a share, the run root, or the fictional folders these cases put in the bridge's sentences and
    /// the page's `run_dir`. `remodel.planned`, `init` and `document.changed` name the run folder or the
    /// active document by design - the page echoes the one back and shows both in its header - and are not
    /// refusals, so they are left out.
    /// </summary>
    private static void AssertNoPathWasPosted(RemodelWorld world, int from = 0)
    {
        foreach (string json in world.Posted.Skip(from))
        {
            JsonElement root = JsonDocument.Parse(json).RootElement;
            string type = root.GetProperty("type").GetString()!;
            if (type == "remodel.planned" || type == "init" || type == "document.changed")
            {
                continue;
            }

            string text = Unescaped(json);
            foreach (string mark in new[] { @":\", @"\\", "Fictional", world.RunRoot })
            {
                Assert.True(
                    text.IndexOf(mark, StringComparison.OrdinalIgnoreCase) < 0,
                    $"a '{type}' message names a path ({mark}): {text}");
            }
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
    /// stopped - and the class the bridge chose is the class the page is told. *Changed
    /// deliberately 2026-10-20 (owner decision 155A, 004 research R18):* the class is
    /// `RunFolderFailed`, a refusal that keeps its own words, where it was `DocumentDirty`, whose
    /// words on this tab are now the host's own whoever refused
    /// (<see cref="APartRefusalReachesThePageInTheTabsOwnWordsWhoeverRefusedItAndNamesNoPath"/>).
    /// </summary>
    [Fact]
    public void ARefusalRaisedWhileCopyingIsAnsweredWithItsOwnClass()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyFailure = new RemodelRefusal(
                "RunFolderFailed",
                "the copy could not be made: the disk is full.",
                retryable: true);

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("RunFolderFailed", error.GetProperty("error_class").GetString());
            Assert.Equal(
                "the copy could not be made: the disk is full.",
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
    /// *Changed deliberately 2026-10-20 (owner decision 155A, 004 research R18):* the page is
    /// told the run is stopping in a status of the stage the engineer's own Stop is told in,
    /// where it was told in `error`, which ends the page's running state while the run still
    /// holds the host
    /// (<see cref="TheStopWhenTheCopyIsGoneLeavesThePageRunningUntilTheRunEnds"/>).
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
                status => status.GetProperty("stage").GetString() == "applying"
                    && status.GetProperty("message").GetString() == RemodelHost.CopyGoneMessage);
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

    // ---- remodel.start after the tool service re-attached (decision 22A, T160) ----------

    /// <summary>
    /// The premise of decision 22A, pinned: a plan waiting for Start holds nothing. The flag the
    /// add-in's busy question reads drops when planning ends, so a document switch between the
    /// plan and Start re-attaches the tool service and throws the plan's bridge session away.
    /// </summary>
    [Fact]
    public void APlannedRunDoesNotHoldTheToolServiceBusy()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("remodel.planned", "p1");
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// The decision: the session does not survive the re-attach, and Start refuses by name
    /// before anything that could change anything. No `remodel.started`, no pipeline call - so
    /// no backend job and no bridge command - and not one byte written or touched in the run
    /// folder or in the engineer's file.
    /// </summary>
    [Fact]
    public void AStartAfterTheToolServiceReattachedIsSessionLostAndNothingIsCalledOrWritten()
    {
        using (var world = new RemodelWorld())
        {
            string source = world.CreateSourceFile();
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");

            string[] callsBefore = world.Pipeline.Calls.ToArray();
            int sourcesSeenBefore = world.Pipeline.SourcePathsSeen.Count;
            int postedBefore = world.Posted.Count;
            string[] runFolderBefore = RemodelWorld.Snapshot(world.ExpectedRunDirectory);
            string[] sourceBefore = RemodelWorld.Snapshot(Path.GetDirectoryName(source)!);

            world.Attachment = SecondAttachment;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("SessionLost", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.SessionLostMessage, error.GetProperty("message").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());

            // The refusal is the only thing the page is told: no `remodel.started`, no `status`.
            Assert.Equal(postedBefore + 1, world.Posted.Count);
            Assert.Empty(world.AllPosted("remodel.started"));

            Assert.Equal(callsBefore, world.Pipeline.Calls.ToArray());
            Assert.Equal(sourcesSeenBefore, world.Pipeline.SourcePathsSeen.Count);
            Assert.Equal(runFolderBefore, RemodelWorld.Snapshot(world.ExpectedRunDirectory));
            Assert.Equal(sourceBefore, RemodelWorld.Snapshot(Path.GetDirectoryName(source)!));
            Assert.Equal(RemodelRunPhase.Planned, world.Host.LatestRun!.Phase);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// U13's rule for every sentence this tab puts in front of the engineer: plain words, no
    /// command, and none of the build's plumbing. It names no path either - the source's in
    /// particular, which nothing after the copy may name - says nothing was changed, and says
    /// what to press next.
    /// </summary>
    [Fact]
    public void TheSessionLostMessageIsPlainWordsAndNamesNoCommandNoPathAndNoPlumbing()
    {
        Assert.Equal(
            "This plan can no longer be started. The add-in reconnected to SOLIDWORKS after the "
            + "plan was made, which happens when the active document changes, and the plan did "
            + "not carry over to the new connection. Your part was not changed. Make your part the "
            + "active document and press Remodel a copy to plan again.",
            RemodelHost.SessionLostMessage);

        AssertPlainWords(RemodelHost.SessionLostMessage);
    }

    /// <summary>
    /// The attachment decides, never the document. Switching away and back re-attaches twice
    /// and ends on the same document, but on a new dispatcher that has no session - so the plan
    /// is refused although every document the host could compare says it is the same part.
    /// </summary>
    [Fact]
    public void AReattachBackToTheSameDocumentIsStillANewAttachmentAndIsRefused()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Document = new PageDocument(@"C:\parts\frame.SLDPRT", "Default");
            world.Host.DocumentChanged();
            world.Attachment = SecondAttachment;
            world.Document = new PageDocument(SourcePath, "Default");
            world.Host.DocumentChanged();
            world.Attachment = "swreview-attachment-3";

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// And the other side of the same rule: while the attachment is the one the plan was made
    /// on, the session is intact, and no document or configuration the host sees is a reason
    /// to refuse. A configuration switch reaches the gate as a follow of the same document, a
    /// different spelling of it is the same document, and a drawing glanced at is not followed
    /// at all - none re-attaches, so none is refused here.
    /// </summary>
    [Theory]
    [InlineData(SourcePath, "Machined")]
    [InlineData(@"c:\PARTS\BRACKET.sldprt", "Default")]
    [InlineData(@"C:\parts\sheet.SLDDRW", null)]
    [InlineData(null, null)]
    public void WithoutAReattachStartGoesAheadWhateverTheDocumentDid(string? path, string? configuration)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Document = path == null ? null : new PageDocument(path, configuration);
            world.Host.DocumentChanged();

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// Start pressed twice after a re-attach: the same answer twice, nothing called either
    /// time, and a refusal that leaves the host exactly as free as it was - the next plan is
    /// accepted, not answered `RunInProgress`.
    /// </summary>
    [Fact]
    public void StartPressedTwiceAfterAReattachIsRefusedTwiceTheSameWay()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("remodel.start", "s2", new { run_dir = world.ExpectedRunDirectory });

            JsonElement first = world.Reply("error", "s1");
            JsonElement second = world.Reply("error", "s2");
            Assert.Equal("SessionLost", first.GetProperty("error_class").GetString());
            Assert.Equal(first.GetRawText(), second.GetRawText());
            Assert.Equal(0, world.Pipeline.Count("run"));
            Assert.False(world.Host.RunInProgress);

            world.Receive("remodel.plan", "p2", new { });
            world.Reply("remodel.planned", "p2");
        }
    }

    /// <summary>
    /// Back to Plan is the way out, and it works: the new plan is made on the attachment
    /// listening now, in a folder of its own, and starts. The old plan stays refused - the
    /// attachment it was made on never comes back, because every start mints a new one.
    /// </summary>
    [Fact]
    public void ANewPlanOnTheNewAttachmentStartsAndTheOldOneStaysRefused()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));

            world.Receive("remodel.plan", "p2", new { });
            string again = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.NotEqual(world.ExpectedRunDirectory, again);

            world.Receive("remodel.start", "s2", new { run_dir = again });
            world.Reply("remodel.started", "s2");
            Assert.Equal(1, world.Pipeline.Count("run"));

            world.Receive("remodel.start", "s3", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s3"));
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// Mid-restart the gate answers no attachment and the seat reads as still being checked.
    /// The session is already gone - whatever attaches next is a new dispatcher - so a Start
    /// that reaches the host then is told so, rather than asked to wait for an attachment that
    /// will refuse the plan on the next press. Such a Start is one the page sent before the
    /// availability refresh reached it: the page itself holds Start while the seat reads as
    /// being checked, so the engineer's usual sequence is the wait and then `SessionLost`
    /// (<c>RemodelPageContractTests</c>, the review of 2026-09-25).
    /// </summary>
    [Fact]
    public void AStartWhileTheToolServiceIsRestartingIsSessionLostRatherThanAWait()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = null;
            world.RemodelCapability = RemodelAvailability.Unknown;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// Unknown is never the same (constitution Principle I). A plan made while no attachment
    /// was known, a Start while none is, and a blank name are each refused - including none
    /// against none, which a plain equality would have let through.
    /// </summary>
    [Theory]
    [InlineData(null, null)]
    [InlineData(null, FirstAttachment)]
    [InlineData("", "")]
    [InlineData("   ", "   ")]
    [InlineData("   ", FirstAttachment)]
    [InlineData(FirstAttachment, null)]
    [InlineData(FirstAttachment, "")]
    public void AnUnknownAttachmentOnEitherSideIsNeverTheSameOne(string? planned, string? now)
    {
        using (var world = new RemodelWorld())
        {
            world.Attachment = planned;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            world.Attachment = now;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    /// <summary>A pipe name is minted, never typed: a name that differs only in case is another one.</summary>
    [Fact]
    public void AnAttachmentIsComparedExactly()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = FirstAttachment.ToUpperInvariant();

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("SessionLost", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// When the plan reads the attachment: once it holds the host busy - from then on the
    /// tool service will not begin a re-attach of its own - and before the probe, so the name
    /// recorded is the one the probe, the copy and the session went to.
    ///
    /// *Amended 2026-09-25 (decision 24A):* the read the run records is still that one, and the
    /// only other is decision 24A's question once the plan has released the host - whether the
    /// plan on screen is already lost - after every pipeline call the plan made.
    /// </summary>
    [Fact]
    public void ThePlanReadsTheAttachmentOnceItIsBusyAndBeforeTheProbe()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("remodel.planned", "p1");
            int planCalls = world.Pipeline.Calls.Count;
            Assert.Equal(new[] { (true, 0), (false, planCalls) }, world.AttachmentReads.ToArray());
            Assert.Equal(FirstAttachment, world.Host.LatestRun!.ToolServiceAttachment);
        }
    }

    /// <summary>
    /// A document change whose busy question was answered just before the plan began can still
    /// re-attach while the plan runs. The run keeps the attachment its plan began on, so Start
    /// refuses it, rather than recording the new one and sending the run to a dispatcher that
    /// never saw its copy.
    /// </summary>
    [Fact]
    public void AReattachThatLandsWhileThePlanRunsIsRefusedAtStart()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.DuringPlan = () => world.Attachment = SecondAttachment;

            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(FirstAttachment, world.Host.LatestRun!.ToolServiceAttachment);
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// A refused plan records no run, even one refused after its folder exists. A Start naming
    /// that folder is `RunNotFound`, as it always was: the host resolves a run from its own
    /// records and never from the disk, and a plan that never existed has no session to lose.
    /// </summary>
    [Fact]
    public void AStartNamingARefusedPlanIsRunNotFoundAndNotSessionLost()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.RebuildErrorCount = 2;
            world.Receive("remodel.plan", "p1", new { });
            Assert.Equal("PreexistingRebuildErrors", world.ErrorClass("p1"));
            Assert.True(Directory.Exists(world.ExpectedRunDirectory));
            world.Attachment = SecondAttachment;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("RunNotFound", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// A plan refused after a good one records nothing, so it cannot re-bind the earlier run to
    /// the attachment it ran on. *Amended 2026-09-27 (004 T173):* it can no longer leave the
    /// earlier plan as it was either, once it has got as far as the bridge - the dirty source is
    /// read by the probe, and the earlier plan's session is closed before the probe, so that plan
    /// is lost whether or not the tool service re-attached in between. A plan refused on the spot,
    /// before any call, still costs it nothing (<see cref="APlanRefusedOnTheSpotCostsTheEarlierPlanNothing"/>).
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ARefusedPlanNeitherRescuesAnEarlierPlanNorLeavesItOnceTheBridgeWasAsked(bool reattachedBetween)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            if (reattachedBetween)
            {
                world.Attachment = SecondAttachment;
            }

            world.Pipeline.Signals.SaveFlagDirty = true;
            world.Receive("remodel.plan", "p2", new { });
            Assert.Equal("DocumentDirty", world.ErrorClass("p2"));
            Assert.Equal(reattachedBetween ? 0 : 1, world.Pipeline.Count("close"));

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("SessionLost", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, error.GetProperty("message").GetString());
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// Where `SessionLost` sits in Start's order (`contracts/pane-remodel-messages.md`): after
    /// the refusals that say the run can never go again whatever is attached, before the seat
    /// check.
    /// </summary>
    [Theory]
    [InlineData("applying")]
    [InlineData("saved")]
    [InlineData("failed")]
    public void AResumeRefusalComesBeforeSessionLost(string state)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WritePlanState(state);
            world.Attachment = SecondAttachment;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("ResumeRefused", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// A second Start while the run is in flight is told the run is in flight, whatever the
    /// attachment reads: the answer that is true of this host comes first.
    /// </summary>
    [Fact]
    public void RunInProgressComesBeforeSessionLost()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                world.Attachment = SecondAttachment;
                world.Receive("remodel.start", "s2", new { run_dir = world.ExpectedRunDirectory });
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            Assert.Equal("RunInProgress", world.ErrorClass("s2"));
        }
    }

    [Fact]
    public void ADiscardedCopyComesBeforeSessionLost()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            world.Attachment = SecondAttachment;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("CopyDiscarded", world.ErrorClass("s1"));
        }
    }

    [Theory]
    [InlineData(RemodelAvailability.Unavailable)]
    [InlineData(RemodelAvailability.Unknown)]
    public void SessionLostComesBeforeTheSeatCheck(RemodelAvailability availability)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;
            world.RemodelCapability = availability;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("SessionLost", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// Refused is not destroyed: the run stays readable from its folder, its copy can still be
    /// brought up in SOLIDWORKS, and `init` still reports it `planned`, because the refusal
    /// wrote nothing to `plan.json`.
    /// </summary>
    [Fact]
    public void ARunRefusedAsSessionLostStaysReadableAndItsCopyCanStillBeOpened()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));

            world.Receive("remodel.result", "r1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("planned", world.Reply("remodel.result", "r1").GetProperty("state").GetString());

            world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "o1");
            Assert.Contains(world.ExpectedCopyPath, world.Pipeline.Opened);

            world.Receive("ready", "r2", new { });
            Assert.Equal(
                "planned",
                world.Reply("init", "r2").GetProperty("latest_run").GetProperty("state").GetString());
        }
    }

    // ---- the page is told when a plan is lost (decision 24A, T170) ----------------------

    /// <summary>
    /// The decision: a re-attach after the plan is told to the page at once, before any Start.
    /// It reaches the host as the gate's withdrawal of the old service - a refresh with nothing
    /// listening - and the host posts `remodel.plan_lost` there, naming the plan's folder, in
    /// its own words, right after the capability refresh that shows the page the wait. The new
    /// service listening is the second refresh of the same re-attach and tells nothing more.
    /// </summary>
    [Fact]
    public void AReattachAfterThePlanIsToldToThePageAtOnceInTheHostsOwnWords()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            int before = world.Posted.Count;

            world.Publish(null);

            Assert.Equal(new[] { "document.changed", "remodel.plan_lost" }, world.TypesPostedSince(before));
            JsonElement notice = world.LastPosted("remodel.plan_lost");
            Assert.Equal(world.ExpectedRunDirectory, notice.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanLostMessage, notice.GetProperty("message").GetString());
            Assert.Equal(2, notice.EnumerateObject().Count());

            int withdrawn = world.Posted.Count;
            world.Publish(SecondAttachment);

            Assert.Equal(new[] { "document.changed" }, world.TypesPostedSince(withdrawn));
            Assert.Single(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// U13's rule, as <see cref="RemodelHost.SessionLostMessage"/> keeps it: plain words, no
    /// command, no path and none of the build's plumbing. It says nothing was changed, in the
    /// one sentence both messages share, and what to press next.
    /// </summary>
    [Fact]
    public void ThePlanLostMessageIsPlainWordsAndNamesNoCommandNoPathAndNoPlumbing()
    {
        Assert.Equal(
            "This plan was made before SOLIDWORKS switched documents, so it can no longer be "
            + "started. Your part was not changed. Make your part the active document and press Plan "
            + "again.",
            RemodelHost.PlanLostMessage);

        const string originalWasNotChanged = "Your part was not changed.";
        Assert.Contains(originalWasNotChanged, RemodelHost.PlanLostMessage, StringComparison.Ordinal);
        Assert.Contains(originalWasNotChanged, RemodelHost.SessionLostMessage, StringComparison.Ordinal);

        AssertPlainWords(RemodelHost.PlanLostMessage);
    }

    /// <summary>
    /// No plan held, nothing told: before any plan; after a plan that was refused, which tracks
    /// no run; after the run has finished, which is not a plan waiting for Start; and after the
    /// engineer discarded the copy, whose Start is `CopyDiscarded` whatever is attached.
    /// </summary>
    [Theory]
    [InlineData("no plan")]
    [InlineData("a refused plan")]
    [InlineData("a finished run")]
    [InlineData("a discarded copy")]
    public void AReattachWithNoPlanHeldTellsNothing(string held)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            switch (held)
            {
                case "a refused plan":
                    world.Pipeline.Signals.SaveFlagDirty = true;
                    world.Receive("remodel.plan", "p1", new { });
                    Assert.Equal("DocumentDirty", world.ErrorClass("p1"));
                    break;
                case "a finished run":
                    world.Receive("remodel.plan", "p1", new { });
                    world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                    Assert.Equal(RemodelRunPhase.Finished, world.Host.LatestRun!.Phase);
                    break;
                case "a discarded copy":
                    world.Receive("remodel.plan", "p1", new { });
                    world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
                    world.Reply("ok", "d1");
                    break;
            }

            world.Reattach(SecondAttachment);
            world.Reattach("swreview-attachment-3");

            Assert.Empty(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// The attachment decides, never the document. Away and back re-attaches twice and ends on
    /// the part the plan was made from, on a dispatcher that never saw its copy: the plan is
    /// lost, the page is told once, at the first withdrawal, and Start still refuses it.
    /// </summary>
    [Fact]
    public void AReattachBackToTheSameDocumentIsStillLostAndIsToldOnce()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Document = new PageDocument(@"C:\parts\frame.SLDPRT", "Default");
            world.Host.DocumentChanged();
            world.Reattach(SecondAttachment);
            world.Document = new PageDocument(SourcePath, "Default");
            world.Host.DocumentChanged();
            world.Reattach("swreview-attachment-3");

            JsonElement notice = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(world.ExpectedRunDirectory, notice.GetProperty("run_dir").GetString());
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// A configuration switch reaches the host as a `document.changed` and the gate as a follow
    /// of the same document, which re-attaches nothing; the same document spelt differently is
    /// the same. And a refresh on which the plan's own attachment is still listening - a
    /// capability answer, not a re-attach - is no loss either. None of them tells anything, and
    /// Start goes ahead.
    /// </summary>
    [Theory]
    [InlineData(SourcePath, "Machined")]
    [InlineData(@"c:\PARTS\BRACKET.sldprt", "Default")]
    public void AConfigurationSwitchOrARefreshOnThePlansOwnAttachmentTellsNothing(
        string path, string configuration)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Document = new PageDocument(path, configuration);
            world.Host.DocumentChanged();
            world.Publish(FirstAttachment);

            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s1");
        }
    }

    /// <summary>
    /// Two re-attaches in a row are four refreshes, every one of which finds the plan's
    /// attachment gone. The page is told once, and the plan stays refused at Start.
    /// </summary>
    [Fact]
    public void TwoReattachesInARowAreToldOnce()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Reattach(SecondAttachment);
            world.Reattach("swreview-attachment-3");

            Assert.Single(world.AllPosted("remodel.plan_lost"));
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            Assert.Single(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// A run in progress holds the tool service - `RunInProgress` is the gate's busy question -
    /// so no re-attach should land under one. Pinned all the same: a refresh during the run,
    /// with the attachment gone, tells nothing, and neither does one after the run has
    /// finished, which is not a plan waiting for Start. The run's own ending is what the page
    /// is told.
    /// </summary>
    [Fact]
    public void ARefreshWhileARunIsInProgressTellsNothingAndNeitherDoesTheFinishedRun()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                Assert.True(world.Host.RunInProgress);
                world.Reattach(SecondAttachment);
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s1");
            world.Reattach("swreview-attachment-3");

            Assert.Equal(1, world.Pipeline.Count("run"));
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// 22A's race: a re-attach that lands while the plan itself runs. Nothing is told while the
    /// plan holds the host - the run it will record does not exist yet - and the moment the plan
    /// releases the host it is asked again: the run it just recorded is lost on arrival, and
    /// the page is told once, after `remodel.planned` has given it the folder the notice names.
    /// </summary>
    [Fact]
    public void AReattachDuringThePlanIsToldWhenThePlanEndsAboutTheRunItRecorded()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int toldDuringThePlan = -1;
            world.Pipeline.DuringPlan = () =>
            {
                world.Reattach(SecondAttachment);
                toldDuringThePlan = world.AllPosted("remodel.plan_lost").Length;
            };

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal(0, toldDuringThePlan);
            JsonElement notice = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(world.ExpectedRunDirectory, notice.GetProperty("run_dir").GetString());
            Assert.True(world.IndexOf("remodel.planned") < world.IndexOf("remodel.plan_lost"));
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// Nothing about a re-attach is told while a plan holds the host: a notice mid-plan would
    /// be about a folder the page is leaving. When the second plan ends the plan on screen is the
    /// one it recorded, lost on arrival, and that is the one the page is told about - once.
    /// *Amended 2026-09-27 (004 T173):* the first plan is still told about exactly once, but as
    /// the plan the second one closed, before its probe and in <see cref="RemodelHost.PlanClosedMessage"/>'s
    /// words - never for the re-attach, which reaches it after it is already lost.
    /// </summary>
    [Fact]
    public void AReattachDuringASecondPlanIsToldAboutTheSecondWhenItEndsAndTheFirstOnlyAsClosed()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            JsonElement[] toldDuringThePlan = new JsonElement[0];
            world.Pipeline.DuringPlan = () =>
            {
                world.Reattach(SecondAttachment);
                toldDuringThePlan = world.AllPosted("remodel.plan_lost");
            };

            world.Receive("remodel.plan", "p2", new { });

            JsonElement closed = Assert.Single(toldDuringThePlan);
            Assert.Equal(world.ExpectedRunDirectory, closed.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, closed.GetProperty("message").GetString());

            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.NotEqual(world.ExpectedRunDirectory, second);
            JsonElement[] notices = world.AllPosted("remodel.plan_lost");
            Assert.Equal(2, notices.Length);
            Assert.Equal(second, notices[1].GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanLostMessage, notices[1].GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// The same race under a plan that fails: it records nothing, so the plan still on screen
    /// is the earlier one - made on the attachment that has just gone - and that is the one the
    /// page is told about. *Amended 2026-09-27 (004 T173):* it is told when the failed plan
    /// closes it, before that plan's probe, in <see cref="RemodelHost.PlanClosedMessage"/>'s words,
    /// and once: the re-attach finds it already told.
    /// </summary>
    [Fact]
    public void AReattachDuringARefusedPlanIsToldAboutThePlanStillOnScreen()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            world.Pipeline.DuringPlan = () =>
            {
                world.Reattach(SecondAttachment);
                throw new InvalidOperationException("the copy's feature tree could not be read");
            };

            world.Receive("remodel.plan", "p2", new { });

            Assert.Equal("HostError", world.ErrorClass("p2"));
            Assert.Equal(world.ExpectedRunDirectory, world.Host.LatestRun!.RunDirectory);
            JsonElement notice = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(world.ExpectedRunDirectory, notice.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, notice.GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// Once per plan, not once per host: Plan again makes a plan on the new attachment, which is
    /// not lost and is not told about; when it, in turn, is lost, the page is told about it,
    /// by its own folder.
    /// </summary>
    [Fact]
    public void APlanMadeOnTheNewAttachmentIsToldAboutWhenItInTurnIsLost()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reattach(SecondAttachment);

            world.Receive("remodel.plan", "p2", new { });
            string again = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.Single(world.AllPosted("remodel.plan_lost"));

            world.Reattach("swreview-attachment-3");

            Assert.Equal(
                new[] { world.ExpectedRunDirectory, again },
                world.AllPosted("remodel.plan_lost").Select(notice => notice.GetProperty("run_dir").GetString()).ToArray());
        }
    }

    /// <summary>
    /// The notice changes nothing but the page. Not one byte written or touched in the run
    /// folder or the engineer's file, no pipeline call, the host not held, the run still
    /// planned and readable - and Start's refusal unchanged: `SessionLost` stays the backstop,
    /// for a Start that reaches the host before the notice reaches the page.
    /// </summary>
    [Fact]
    public void TheNoticeChangesNothingAndStartStillRefusesAsSessionLost()
    {
        using (var world = new RemodelWorld())
        {
            string source = world.CreateSourceFile();
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string[] callsBefore = world.Pipeline.Calls.ToArray();
            string[] runFolderBefore = RemodelWorld.Snapshot(world.ExpectedRunDirectory);
            string[] sourceBefore = RemodelWorld.Snapshot(Path.GetDirectoryName(source)!);

            world.Reattach(SecondAttachment);

            Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(callsBefore, world.Pipeline.Calls.ToArray());
            Assert.Equal(runFolderBefore, RemodelWorld.Snapshot(world.ExpectedRunDirectory));
            Assert.Equal(sourceBefore, RemodelWorld.Snapshot(Path.GetDirectoryName(source)!));
            Assert.Equal(RemodelRunPhase.Planned, world.Host.LatestRun!.Phase);
            Assert.False(world.Host.RunInProgress);

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("SessionLost", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.SessionLostMessage, error.GetProperty("message").GetString());
            Assert.Equal(callsBefore, world.Pipeline.Calls.ToArray());

            world.Receive("remodel.result", "r1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("planned", world.Reply("remodel.result", "r1").GetProperty("state").GetString());
        }
    }

    // ---- ...and to a page that starts again (decision 24A, amended on review) --------------

    /// <summary>
    /// The notice is told once per plan, and a page keeps it only while it lives. A page that
    /// loads again - a reload, or the pane building its view anew - asks `ready` and starts
    /// from `init` alone, so `init.latest_run` says the plan is lost, in the notice's own words.
    /// The notice is not posted again: `init` neither spends nor needs its once-per-plan claim.
    /// </summary>
    [Fact]
    public void AnInitAfterTheNoticeSaysThePlanIsLostInTheHostsOwnWords()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reattach(SecondAttachment);
            Assert.Single(world.AllPosted("remodel.plan_lost"));

            world.Receive("ready", "r2", new { });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_run");
            Assert.Equal(world.ExpectedRunDirectory, latest.GetProperty("run_dir").GetString());
            Assert.Equal("planned", latest.GetProperty("state").GetString());
            Assert.Equal(RemodelHost.PlanLostMessage, latest.GetProperty("plan_lost").GetString());
            Assert.Single(world.AllPosted("remodel.plan_lost"));

            world.Receive("ready", "r3", new { });
            Assert.Equal(
                RemodelHost.PlanLostMessage,
                world.Reply("init", "r3").GetProperty("latest_run").GetProperty("plan_lost").GetString());
            Assert.Single(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// `init` reads the state, not the notice: an attachment that changed with no refresh to
    /// post the notice - so the page was never told - is still a lost plan to `init`, and the
    /// notice's claim is still unspent for the refresh that follows.
    /// </summary>
    [Fact]
    public void AnInitSaysThePlanIsLostWhenTheNoticeWasNeverPosted()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;

            world.Receive("ready", "r2", new { });

            Assert.Equal(
                RemodelHost.PlanLostMessage,
                world.Reply("init", "r2").GetProperty("latest_run").GetProperty("plan_lost").GetString());
            Assert.Empty(world.AllPosted("remodel.plan_lost"));

            world.Host.RefreshAvailability();
            Assert.Single(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// No lost plan, no `plan_lost`: a plan on its own attachment (whatever the document did
    /// that re-attached nothing); a finished run, which is not a plan waiting for Start; and a
    /// discarded copy, whose Start is `CopyDiscarded` whatever is attached - each after a
    /// re-attach, which a plan on screen would have lost.
    /// </summary>
    [Theory]
    [InlineData("a plan on its own attachment")]
    [InlineData("a finished run")]
    [InlineData("a discarded copy")]
    public void AnInitWithNoLostPlanSaysNothingIsLost(string held)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            switch (held)
            {
                case "a plan on its own attachment":
                    world.Document = new PageDocument(SourcePath, "Machined");
                    world.Host.DocumentChanged();
                    world.Publish(FirstAttachment);
                    break;
                case "a finished run":
                    world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                    Assert.Equal(RemodelRunPhase.Finished, world.Host.LatestRun!.Phase);
                    world.Reattach(SecondAttachment);
                    break;
                case "a discarded copy":
                    world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
                    world.Reply("ok", "d1");
                    world.Reattach(SecondAttachment);
                    break;
            }

            world.Receive("ready", "r2", new { });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_run");
            Assert.Equal(world.ExpectedRunDirectory, latest.GetProperty("run_dir").GetString());
            Assert.Equal(JsonValueKind.Null, latest.GetProperty("plan_lost").ValueKind);
        }
    }

    /// <summary>
    /// An `init` changes nothing either: no pipeline call, nothing written to the run folder or
    /// beside the engineer's file, the host not held and the run still planned - and Start
    /// still refuses the lost plan as `SessionLost`.
    /// </summary>
    [Fact]
    public void AnInitAboutALostPlanChangesNothingAndStartStillRefusesAsSessionLost()
    {
        using (var world = new RemodelWorld())
        {
            string source = world.CreateSourceFile();
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reattach(SecondAttachment);
            string[] callsBefore = world.Pipeline.Calls.ToArray();
            string[] runFolderBefore = RemodelWorld.Snapshot(world.ExpectedRunDirectory);
            string[] sourceBefore = RemodelWorld.Snapshot(Path.GetDirectoryName(source)!);

            world.Receive("ready", "r2", new { });
            world.Reply("init", "r2");

            Assert.Equal(callsBefore, world.Pipeline.Calls.ToArray());
            Assert.Equal(runFolderBefore, RemodelWorld.Snapshot(world.ExpectedRunDirectory));
            Assert.Equal(sourceBefore, RemodelWorld.Snapshot(Path.GetDirectoryName(source)!));
            Assert.Equal(RemodelRunPhase.Planned, world.Host.LatestRun!.Phase);
            Assert.False(world.Host.RunInProgress);

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            Assert.Equal(callsBefore, world.Pipeline.Calls.ToArray());
        }
    }

    // ---- ...and through a real gate, wired as the add-in wires it -------------------------

    /// <summary>
    /// The same decision with the refreshes coming from a real <see cref="ToolServiceGate"/>
    /// rather than from the test: a re-attach before any plan tells nothing; one after the plan
    /// tells once, at the withdrawal; away and back again tells nothing more; and the plan made
    /// on the part it started from is refused at Start, because every attachment is new.
    /// </summary>
    [Fact]
    public void ThroughTheGateAReattachIsToldOnceAndBackToTheSameDocumentNothingMore()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            ToolServiceGate gate = world.AttachGate();
            gate.EnsureStarted();
            world.SwitchTo(gate, @"C:\parts\frame.SLDPRT");
            world.SwitchTo(gate, SourcePath);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));

            world.Receive("remodel.plan", "p1", new { });
            Assert.Equal(gate.Attachment, world.Host.LatestRun!.ToolServiceAttachment);
            world.SwitchTo(gate, @"C:\parts\frame.SLDPRT");
            world.SwitchTo(gate, SourcePath);

            Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.NotEqual(gate.Attachment, world.Host.LatestRun!.ToolServiceAttachment);
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// Through the gate, a configuration switch and the same document spelt differently are
    /// follows of the document already attached: nothing re-attaches, nothing is told, and
    /// Start goes ahead on the plan's own attachment.
    /// </summary>
    [Fact]
    public void ThroughTheGateAConfigurationSwitchReattachesNothingAndTellsNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            ToolServiceGate gate = world.AttachGate();
            gate.EnsureStarted();
            world.Receive("remodel.plan", "p1", new { });
            string? planned = gate.Attachment;

            world.SwitchTo(gate, SourcePath, "Machined");
            world.SwitchTo(gate, @"c:\PARTS\BRACKET.sldprt", "Machined");

            Assert.Equal(planned, gate.Attachment);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s1");
        }
    }

    /// <summary>
    /// Through the gate, a run holds the tool service: a document switch while it runs is asked
    /// whether work is holding the bridge, `RunInProgress` says yes, and the gate re-attaches
    /// nothing - so no refresh reaches the host and nothing is told while the run holds it. Once
    /// the run has ended the gate follows the switch it skipped, to the document active then (owner
    /// decision 152A), and the run is finished, so nothing is told then either.
    /// </summary>
    [Fact]
    public void ThroughTheGateARunHoldsTheServiceSoASwitchWhileItRunsTellsNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            ToolServiceGate gate = world.AttachGate();
            gate.EnsureStarted();
            world.Receive("remodel.plan", "p1", new { });
            string? planned = gate.Attachment;
            world.Pipeline.DuringRun = reporter => world.SwitchTo(gate, @"C:\parts\frame.SLDPRT");

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            Assert.Equal(planned, gate.Attachment);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));

            Assert.Equal(1, world.LooksWaiting);
            world.RunLooks();

            Assert.NotEqual(planned, gate.Attachment);
            Assert.Equal(@"C:\parts\frame.SLDPRT", gate.DocumentPath);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(0, world.LooksWaiting);
        }
    }

    /// <summary>
    /// Owner decision 158A: a run is not exempt from the hold's limit, and needs no exemption. Its hold,
    /// held longer than <see cref="ToolServiceGate.HoldLimit"/>, is ignored and said by its kind; but
    /// that ends nothing - the run goes on to its end - and only lets the look ask the busy question,
    /// which reads the run in progress (<see cref="RemodelHost.RunInProgress"/>, as the add-in's reads it
    /// first). So the bridge is not taken down under the run, and the switch is followed once it ends.
    /// </summary>
    [Fact]
    public void ThroughTheGateARunHeldPastTheHoldLimitIsStillNotTakenDownUnder()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            ToolServiceGate gate = world.AttachGate();
            gate.EnsureStarted();
            world.Receive("remodel.plan", "p1", new { });
            string? planned = gate.Attachment;
            var running = (FakeToolService)gate.Service!;
            world.Pipeline.DuringRun = reporter =>
            {
                world.SwitchTo(gate, @"C:\parts\frame.SLDPRT");
                world.GateClock = ToolServiceGate.HoldLimit + TimeSpan.FromSeconds(1);
                world.RunLooks();

                Assert.Equal(planned, gate.Attachment);
                Assert.False(running.Disposed);
                Assert.Single(running.LogLines, line => line.StartsWith("ignoring a hold by a Remodel plan or run: held for 1:00:01, ", StringComparison.Ordinal));
                Assert.Equal(1, world.LooksWaiting);
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            Assert.Equal(1, world.Pipeline.Count("run"));
            Assert.Equal("ready", world.LastPosted("status").GetProperty("stage").GetString());
            Assert.Equal(planned, gate.Attachment);
            Assert.False(world.Host.RunInProgress);

            world.RunLooks();

            Assert.Equal(@"C:\parts\frame.SLDPRT", gate.DocumentPath);
            Assert.True(running.Disposed);
            Assert.Equal(0, world.LooksWaiting);
        }
    }

    /// <summary>
    /// Owner decision 152A keeps the planned copy's attachment exactly as 004 T180 keeps it. The
    /// plan held the bridge while its copy was opened and made active, so that switch was skipped;
    /// once the plan ends the gate looks again, finds the exact held copy active, keeps the plan's
    /// attachment and asks no more - nothing is told, and Start goes ahead on the plan's session.
    /// </summary>
    [Fact]
    public void ThroughTheGateTheLookOnceAPlanEndsKeepsTheAttachmentItsCopyHolds()
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate())
            {
                gate.EnsureStarted();
                IToolService original = gate.Service!;
                world.Pipeline.DuringPlan = () => world.SwitchTo(gate, world.ExpectedCopyPath);

                world.Receive("remodel.plan", "p1", new { });

                Assert.Equal(1, world.LooksWaiting);
                world.RunLooks();

                Assert.Same(original, gate.Service);
                Assert.False(((FakeToolService)original).Disposed);
                Assert.Equal(0, world.LooksWaiting);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                world.Reply("remodel.started", "s1");
                Assert.Equal(1, world.Pipeline.Count("run"));
            }
        }
    }

    /// <summary>
    /// The 152A review's R5, put to the owner as 152A's question 3. With Start switched off - the
    /// shipped build - a plan closes its session before it answers (004 T176), so no held copy keeps
    /// the attachment (T180), and the look once the plan ends follows whatever the plan's close left
    /// active: the original part, normally, which is the document attached to, so nothing changes; or
    /// the copy, when the close left it open and active, which the tool service then follows - a
    /// re-attach. Before 152A that switch was skipped for good. *Changed deliberately 2026-10-21 (owner
    /// decision 159A, 004 research R19):* the follow is kept - the tool service follows the document
    /// SOLIDWORKS has active - and the re-attach no longer tells the plan lost, where it did in words
    /// that said SOLIDWORKS switched documents: a plan the host closed at the plan holds no session a
    /// re-attach could take, and no Start can use it in this build either way. The follow itself is now
    /// pinned too.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ThroughTheGateWithStartSwitchedOffTheLookFollowsWhatThePlansCloseLeftActive(bool copyLeftActive)
    {
        using (var world = new RemodelWorld())
        {
            world.StartValidated = false;
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate())
            {
                gate.EnsureStarted();
                IToolService original = gate.Service!;
                world.Pipeline.DuringPlan = () => world.SwitchTo(gate, world.ExpectedCopyPath);

                world.Receive("remodel.plan", "p1", new { });
                if (!copyLeftActive)
                {
                    world.SwitchTo(gate, SourcePath);
                }

                world.RunLooks();

                Assert.Equal(copyLeftActive, ((FakeToolService)original).Disposed);
                Assert.Equal(copyLeftActive ? world.ExpectedCopyPath : SourcePath, gate.DocumentPath);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
                Assert.Equal(0, world.LooksWaiting);
            }
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T212; 002 research 152A's owner question 3): with Start switched off, the
    /// look once a plan ends follows the copy the plan's close left open and active - the tool service follows the
    /// document SOLIDWORKS has active, as 152A made it - and the plan is not told lost: its session was closed at the
    /// plan (004 T176), so the re-attach took nothing from it, and `init` says nothing is lost either. The run line
    /// keeps the plan; Start answers what it answers every plan in this build, `StartNotValidated`. Once the engineer
    /// closes the copy, as the teardown's words ask, the tool service follows their part again, and nothing is told.
    /// </summary>
    [Fact]
    public void WithStartSwitchedOffAPlanIsNotToldLostWhenTheToolServiceFollowsTheCopyItsCloseLeftActive()
    {
        using (var world = new RemodelWorld())
        {
            world.StartValidated = false;
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate())
            {
                gate.EnsureStarted();
                world.Pipeline.DuringPlan = () => world.SwitchTo(gate, world.ExpectedCopyPath);

                world.Receive("remodel.plan", "p1", new { });
                world.RunLooks();

                Assert.Equal(world.ExpectedCopyPath, gate.DocumentPath);
                Assert.True(world.Host.LatestRun!.SessionClosedAtPlan);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
                world.Receive("ready", "r1", new { });
                Assert.Equal(JsonValueKind.Null, world.Reply("init", "r1").GetProperty("latest_run").GetProperty("plan_lost").ValueKind);
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                Assert.Equal("StartNotValidated", world.ErrorClass("s1"));

                world.SwitchTo(gate, SourcePath);

                Assert.Equal(SourcePath, gate.DocumentPath);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
            }
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T212): the same rule for any re-attach, the engineer's own switch to another
    /// part included - a re-attach loses a plan by taking the session it holds, and a plan the host closed at the plan
    /// holds none, so nothing is told and `init` says nothing is lost.
    /// </summary>
    [Fact]
    public void WithStartSwitchedOffAReattachTellsNothingOfAPlanTheHostClosedAtThePlan()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            ToolServiceGate gate = world.AttachGate();
            gate.EnsureStarted();
            world.Receive("remodel.plan", "p1", new { });
            string? planned = gate.Attachment;

            world.SwitchTo(gate, @"C:\parts\frame.SLDPRT");

            Assert.NotEqual(planned, gate.Attachment);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            world.Receive("ready", "r1", new { });
            Assert.Equal(JsonValueKind.Null, world.Reply("init", "r1").GetProperty("latest_run").GetProperty("plan_lost").ValueKind);
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T212): a guard of what the rule leaves. With Start switched off, a plan whose close the
    /// bridge could not answer keeps its session (004 T176), and a re-attach takes it: that plan is told lost, as before.
    /// So is one planning again set aside (004 T173), whose notice says so in its own words.
    /// </summary>
    [Fact]
    public void WithStartSwitchedOffAPlanStillHoldingItsSessionIsToldLostOnAReattach()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            ToolServiceGate gate = world.AttachGate();
            gate.EnsureStarted();
            world.Pipeline.CloseFailure = new RemodelRefusal(
                "BridgeUnavailable", "FICT the bridge did not answer remodel.close.", retryable: true);
            world.Receive("remodel.plan", "p1", new { });
            Assert.False(world.Host.LatestRun!.SessionClosedAtPlan);
            world.Pipeline.CloseFailure = null;

            world.SwitchTo(gate, @"C:\parts\frame.SLDPRT");

            JsonElement lost = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(RemodelHost.PlanLostMessage, lost.GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T229; the mutation review's RF1 - a guard): a plan closed at the plan, while Start
    /// is switched off, is not lost to a re-attach (T213), but planning again sets it aside whatever its session (T173) - and
    /// `init` says so while it is still the latest run: here the new plan was refused before it was recorded.
    /// </summary>
    [Fact]
    public void WithStartSwitchedOffAPlanPlanningAgainSetAsideIsToldLostByInitWhileItIsTheLatestRun()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            Assert.True(world.Host.LatestRun!.SessionClosedAtPlan);
            world.Pipeline.ProbeFailure = TheBackends("RunFolderFailed", "FICT the backend refused the probe.");

            world.Receive("remodel.plan", "p2", new { });
            world.Reply("error", "p2");
            world.Receive("ready", "r1", new { });

            JsonElement latest = world.Reply("init", "r1").GetProperty("latest_run");
            Assert.Equal(first, latest.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, latest.GetProperty("plan_lost").GetString());
        }
    }

    // ---- a plan or a run holds the tool service through the gate (152A, the Codex review: X2) --

    /// <summary>
    /// The Codex review of 152A, X2, as it found it. A look's busy question asks the run first, then
    /// whether a turn may be running - a round trip per open chat - and a plan can begin while that
    /// round trip is out: it marks the host busy, too late for the question, makes its copy the active
    /// document, and is not yet a plan whose held copy keeps the attachment (004 T180), since it is
    /// tracked only once planned. The look took the bridge down under it. The plan holds the tool
    /// service through the gate before it reads its attachment, and the look takes the bridge down
    /// only if no hold was taken while its question was out: it waits, and once the plan is planned
    /// the next look keeps the plan's attachment for its copy, and Start runs on its session. The plan
    /// runs on a thread of its own, as on the Remodel tab's pump, and is held in its planning while the
    /// look decides.
    /// </summary>
    [Fact]
    public void ThroughTheGateAPlanBegunWhileALooksTurnQuestionIsOutIsNotTornDownUnderIt()
    {
        using (var world = new RemodelWorld())
        using (var planning = new ManualResetEventSlim(false))
        using (var release = new ManualResetEventSlim(false))
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            Thread? plan = null;
            Exception? planFailure = null;
            bool asked = false;
            using (ToolServiceGate gate = world.AttachLifecycleGate(turnQuery: () =>
            {
                if (asked)
                {
                    return false;
                }

                // The run was asked first and was not in progress; the backend's answer is had - no
                // turn - and on its way back the plan begins on the page's thread.
                asked = true;
                plan = new Thread(() =>
                {
                    try
                    {
                        world.Receive("remodel.plan", "p1", new { });
                    }
                    catch (Exception failure)
                    {
                        planFailure = failure;
                    }
                }) { IsBackground = true };
                plan.Start();
                Assert.True(planning.Wait(TimeSpan.FromSeconds(10)), "the plan never reached its planning");
                return false;
            }))
            {
                gate.EnsureStarted();
                IToolService original = gate.Service!;
                world.Pipeline.DuringPlan = () =>
                {
                    world.SwitchTo(gate, world.ExpectedCopyPath);
                    planning.Set();
                    Assert.True(release.Wait(TimeSpan.FromSeconds(10)), "the plan was never let go on");
                };
                try
                {
                    gate.FollowActiveDocument();

                    Assert.Same(original, gate.Service);
                    Assert.False(((FakeToolService)original).Disposed);
                    Assert.Equal(1, world.LooksWaiting);
                }
                finally
                {
                    release.Set();
                    Assert.True(plan == null || plan.Join(TimeSpan.FromSeconds(10)), "the plan never finished");
                }

                Assert.Null(planFailure);
                world.Reply("remodel.planned", "p1");
                world.RunLooks();

                Assert.Same(original, gate.Service);
                Assert.False(((FakeToolService)original).Disposed);
                Assert.Equal(0, world.LooksWaiting);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                world.Reply("remodel.started", "s1");
                Assert.Equal(1, world.Pipeline.Count("run"));
            }
        }
    }

    /// <summary>
    /// ...and the same race with Start: pressed while a look's round trip is out, its run makes the
    /// plan no longer one a held copy keeps the attachment for (004 T180: a planned plan only), and the
    /// look took the bridge down under the run. Start holds the tool service through the gate before
    /// the run is handed on, and holds it until the run's session is closed: the look waits.
    /// </summary>
    [Fact]
    public void ThroughTheGateARunBegunWhileALooksTurnQuestionIsOutIsNotTornDownUnderIt()
    {
        using (var world = new RemodelWorld())
        {
            var runs = new Queue<Action>();
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Scheduler = work => runs.Enqueue(work);
            world.Open();
            bool armed = false;
            using (ToolServiceGate gate = world.AttachLifecycleGate(turnQuery: () =>
            {
                if (!armed)
                {
                    return false;
                }

                // The run was asked first and was not in progress; the backend's answer is had - no
                // turn - and on its way back Start is pressed.
                armed = false;
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                return false;
            }))
            {
                gate.EnsureStarted();
                IToolService original = gate.Service!;
                world.Pipeline.DuringPlan = () => world.SwitchTo(gate, world.ExpectedCopyPath);
                world.Receive("remodel.plan", "p1", new { });
                world.RunLooks();
                Assert.Same(original, gate.Service);
                bool closedHeld = false;
                world.Pipeline.DuringClose = () => closedHeld = gate.Service == original && !((FakeToolService)original).Disposed;
                armed = true;

                gate.FollowActiveDocument();

                world.Reply("remodel.started", "s1");
                Assert.False(((FakeToolService)original).Disposed);
                Assert.Equal(1, world.LooksWaiting);
                world.RunLooks();
                Assert.False(((FakeToolService)original).Disposed);
                Assert.Equal(1, world.LooksWaiting);

                runs.Dequeue()();

                Assert.Equal(1, world.Pipeline.Count("run"));
                Assert.True(closedHeld, "the run's session was not closed on the bridge it ran on");
                Assert.False(world.Host.RunInProgress);
                world.RunLooks();
                Assert.True(((FakeToolService)original).Disposed);
            }
        }
    }

    /// <summary>
    /// A plan holds the tool service from before it reads the attachment its session will live on
    /// until it ends, whatever ends it - planned, refused on its second reading of the document, a
    /// probe or a copy that failed - and a run until its session is closed: the host never leaves a
    /// hold behind, which would keep the tool service off every document for good.
    /// </summary>
    [Theory]
    [InlineData("planned")]
    [InlineData("its document changed")]
    [InlineData("its probe failed")]
    [InlineData("its copy failed")]
    [InlineData("run")]
    public void APlanOrARunHoldsTheToolServiceWhileItRunsAndLetsGoWhenItEnds(string ending)
    {
        using (var world = new RemodelWorld())
        {
            var holds = new CountedHolds();
            int readsAtTheHold = -1;
            var during = new List<(int Taken, int Held)>();
            world.Hold = holds.Take;
            holds.OnTake = () => readsAtTheHold = world.AttachmentReads.Count;
            world.Pipeline.DuringPlan = () => during.Add((holds.Taken, holds.Held));
            world.Pipeline.DuringRun = _ => during.Add((holds.Taken, holds.Held));
            world.Pipeline.DuringClose = () => during.Add((holds.Taken, holds.Held));
            if (ending == "its probe failed") world.Pipeline.ProbeFailure = new InvalidOperationException("FICT probe failed");
            if (ending == "its copy failed") world.Pipeline.CopyFailure = new InvalidOperationException("FICT copy failed");
            world.Open();
            int readsBefore = world.AttachmentReads.Count;
            if (ending == "its document changed")
            {
                world.Options.BeginRun = begin =>
                {
                    world.Document = new PageDocument(@"C:\parts\frame.SLDPRT", "Default");
                    begin();
                    return null;
                };
            }

            world.Receive("remodel.plan", "p1", new { });
            if (ending == "run")
            {
                during.Clear();
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                world.Reply("remodel.started", "s1");
                Assert.Equal(2, holds.Taken);
                Assert.Equal(new[] { (2, 1), (2, 1) }, during.ToArray());
            }
            else
            {
                Assert.Equal(1, holds.Taken);
                Assert.Equal(readsBefore, readsAtTheHold);
                Assert.All(during, seen => Assert.Equal((1, 1), seen));
            }

            Assert.Equal(0, holds.Held);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// With no service listening to hold - none has started, or a follow has begun taking the bridge
    /// down - a plan finds none, and is refused as one is while the tool service attaches, before any
    /// call and with the host free again; and a Start, whose plan's session goes with the attachment
    /// being taken down, is refused as a lost session. Nothing waits: the page's thread is never held
    /// for the attach.
    /// </summary>
    [Theory]
    [InlineData("plan")]
    [InlineData("start")]
    public void AnythingTheGateGivesNoHoldIsRefusedAndTheHostIsFreeAgain(string press)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            if (press == "start")
            {
                world.Receive("remodel.plan", "p1", new { });
            }

            int calls = world.Pipeline.Calls.Count;
            world.Hold = () => null;

            if (press == "plan")
            {
                world.Receive("remodel.plan", "p2", new { });
                JsonElement error = world.Reply("error", "p2");
                Assert.Equal("RemodelUnavailable", error.GetProperty("error_class").GetString());
                Assert.Equal(RemodelHost.SeatCheckingMessage, error.GetProperty("message").GetString());
                Assert.True(error.GetProperty("retryable").GetBoolean());
            }
            else
            {
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                JsonElement error = world.Reply("error", "s1");
                Assert.Equal("SessionLost", error.GetProperty("error_class").GetString());
                Assert.False(error.GetProperty("retryable").GetBoolean());
                Assert.Empty(world.AllPosted("remodel.started"));
            }

            Assert.Equal(calls, world.Pipeline.Calls.Count);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// Through the gate: a plan pressed while a follow takes the bridge down - after the follow has
    /// withdrawn the service and before the next one listens - is refused as above, and holds nothing.
    /// </summary>
    [Fact]
    public void ThroughTheGateAPlanPressedWhileAFollowTakesTheBridgeDownIsRefused()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            bool pressed = false;
            using (ToolServiceGate gate = world.AttachLifecycleGate(cleanup: () =>
            {
                if (!pressed)
                {
                    pressed = true;
                    world.Receive("remodel.plan", "p1", new { });
                }
            }))
            {
                gate.EnsureStarted();

                world.SwitchTo(gate, @"C:\parts\frame.SLDPRT");

                Assert.Equal("RemodelUnavailable", world.ErrorClass("p1"));
                Assert.Empty(world.Pipeline.Calls);
                Assert.False(world.Host.RunInProgress);
                Assert.Equal(@"C:\parts\frame.SLDPRT", gate.DocumentPath);
                world.SwitchTo(gate, @"C:\parts\plate.SLDPRT");
                Assert.Equal(@"C:\parts\plate.SLDPRT", gate.DocumentPath);
            }
        }
    }

    /// <summary>
    /// The review of 152A's Codex fixes, N4: a plan or a run lets go of its hold before it frees the
    /// host. A run ends on a thread of its own, and a plan pressed the moment the host is free takes a
    /// hold of its own; a run that freed the host first and let go after let go of that plan's hold,
    /// leaving the plan unheld. So each lets go while the host is still busy.
    /// </summary>
    [Fact]
    public void APlanOrARunLetsGoOfItsHoldBeforeItFreesTheHost()
    {
        using (var world = new RemodelWorld())
        {
            var holds = new CountedHolds();
            var busyAsLetGo = new List<bool>();
            world.Hold = holds.Take;
            holds.OnRelease = () => busyAsLetGo.Add(world.Host.RunInProgress);
            world.Open();

            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            Assert.Equal(new[] { true, true }, busyAsLetGo.ToArray());
            Assert.False(world.Host.RunInProgress);
            Assert.Equal(0, holds.Held);
        }
    }

    /// <summary>
    /// ...and takes its hold only once the host is busy (owner decision 158A, on its review: S3). So
    /// whenever the Remodel host holds the tool service, <see cref="RemodelHost.RunInProgress"/> is true,
    /// and the gate's busy question, which the add-in reads it first in, keeps the bridge under a plan or
    /// a run whether or not its hold is past the gate's limit: the limit only ever says such a hold, and
    /// a plan or a run that never ended would hold the follow back through the busy question.
    /// </summary>
    [Fact]
    public void APlanOrARunTakesItsHoldOnlyOnceTheHostIsBusy()
    {
        using (var world = new RemodelWorld())
        {
            var holds = new CountedHolds();
            var busyAsTaken = new List<bool>();
            world.Hold = holds.Take;
            holds.OnTake = () => busyAsTaken.Add(world.Host.RunInProgress);
            world.Open();

            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            Assert.Equal(new[] { true, true }, busyAsTaken.ToArray());
        }
    }

    /// <summary>
    /// ...and letting go comes first, so a hold that fails as it is let go must not keep the host
    /// busy - a host left busy holds back every plan, and every settings restart, until SOLIDWORKS
    /// restarts - nor change the press's answer, nor reach a run's own thread, which nothing waits on.
    /// The gate's own holds never fail; a host is handed whatever <c>HoldToolService</c> answers.
    /// </summary>
    [Theory]
    [InlineData("plan")]
    [InlineData("run")]
    public void AHoldThatFailsAsItIsLetGoStillFreesTheHost(string press)
    {
        using (var world = new RemodelWorld())
        {
            var holds = new CountedHolds();
            world.Hold = holds.Take;
            world.Open();
            if (press == "run")
            {
                world.Receive("remodel.plan", "p1", new { });
            }

            holds.OnRelease = () => throw new InvalidOperationException("FICT the hold would not let go");

            if (press == "plan")
            {
                world.Receive("remodel.plan", "x", new { });
                world.Reply("remodel.planned", "x");
            }
            else
            {
                world.Receive("remodel.start", "x", new { run_dir = world.ExpectedRunDirectory });
                world.Reply("remodel.started", "x");
                Assert.Equal(1, world.Pipeline.Count("run"));
            }

            Assert.Empty(world.AllPosted("error"));
            Assert.False(world.Host.RunInProgress);
            Assert.Equal(0, holds.Held);
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

    /// <summary>
    /// Owner decision 148A (feature 011 T188, research R12.4; R11.8 item 9): Open copy pressed while a run
    /// is in progress is refused - <c>RunInProgress</c>, retryable, in plain words naming no path - before
    /// anything is asked of SOLIDWORKS: the copy activated or opened between the run's requests to the
    /// bridge would change the document SOLIDWORKS has active under the run. The page offers it no more
    /// than Discard copy while a run runs; this is the host's backstop.
    /// </summary>
    [Fact]
    public void OpenCopyWhileItsRunIsInProgressIsRefusedInPlainWordsAndNothingIsActivated()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
                world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            JsonElement error = world.Reply("error", "o1");
            Assert.Equal("RunInProgress", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.OpenCopyWhileARunIsInProgressMessage, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(0, world.Pipeline.Count("activate"));
        }
    }

    /// <summary>
    /// Decision 148A: any run in progress, not only the copy's own - the copy of an earlier plan, still in
    /// its folder, is not opened under a run either, since the active document would change under it the
    /// same way.
    /// </summary>
    [Fact]
    public void OpenCopyOfAnEarlierPlanWhileARunIsInProgressIsRefusedToo()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string earlier = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            world.Receive("remodel.plan", "p2", new { });
            string later = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.NotEqual(earlier, later);
            world.Pipeline.DuringRun = reporter => world.Receive("remodel.open_copy", "o1", new { run_dir = earlier });

            world.Receive("remodel.start", "s1", new { run_dir = later });

            world.Reply("remodel.started", "s1");
            Assert.Equal("RunInProgress", world.ErrorClass("o1"));
            Assert.Equal(0, world.Pipeline.Count("activate"));
        }
    }

    /// <summary>
    /// Decision 148A's review (feature 011 T193, research R12.8): a plan in flight holds the host as a run
    /// does - the decision says "a plan or a run" - so Open copy of an earlier plan's copy, sent while a
    /// second plan is being made, is refused <c>RunInProgress</c> and nothing is activated. The page cannot
    /// send it then, since its messages wait on the one thread the plan holds (research R12.4); this pins
    /// the host's own answer, which the three tests above, each pressing it during a run, could not.
    /// </summary>
    [Fact]
    public void OpenCopyOfAnEarlierPlanWhileAPlanIsInFlightIsRefusedToo()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string earlier = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            world.Pipeline.DuringPlan = () => world.Receive("remodel.open_copy", "o1", new { run_dir = earlier });

            world.Receive("remodel.plan", "p2", new { });

            JsonElement error = world.Reply("error", "o1");
            Assert.Equal("RunInProgress", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.OpenCopyWhileARunIsInProgressMessage, error.GetProperty("message").GetString());
            Assert.Equal(0, world.Pipeline.Count("activate"));
            Assert.NotEqual(earlier, world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString());
        }
    }

    /// <summary>Decision 148A: once the run has finished, Open copy is answered again, as before it began.</summary>
    [Fact]
    public void OpenCopyAfterTheRunHasFinishedActivatesTheCopyAgain()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.False(world.Host.RunInProgress);

            world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("ok", "o1");
            Assert.Equal(1, world.Pipeline.Count("activate"));
        }
    }

    /// <summary>
    /// The refusal decision 148A mirrors, pinned beside it: Discard copy pressed while its run is in
    /// progress is refused <c>RunInProgress</c>, and the copy stays.
    /// </summary>
    [Fact]
    public void DiscardCopyWhileItsRunIsInProgressIsRefusedAndTheCopyStays()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
                world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("RunInProgress", world.ErrorClass("d1"));
            Assert.True(File.Exists(world.ExpectedCopyPath));
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

    /// <summary>
    /// T168 (decision 22A): `remodel.close` named no run until owner decision 159A, so a close is sent only through the
    /// attachment the run's plan was made on. After a re-attach the run's session went with
    /// its attachment and there is nothing of it to close; the discard still deletes the copy
    /// and still writes `discarded`, so the run reads as the engineer left it.
    /// </summary>
    [Fact]
    public void ADiscardAfterAReattachSendsNoCloseAndStillDeletesTheCopy()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;

            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("ok", "d1");
            Assert.Equal(0, world.Pipeline.Count("close"));
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));

            world.Receive("remodel.result", "g1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("discarded", world.Reply("remodel.result", "g1").GetProperty("state").GetString());
        }
    }

    /// <summary>
    /// The flow T168 was found on: refused as `SessionLost`, back to plan on the new
    /// attachment, then the old copy cleared away. The close the discard used to send through
    /// the new attachment would have closed the new plan's copy - the bridge closes whatever
    /// session it holds - and the new plan's Start would then have failed on the bridge. It
    /// sends none, and the new plan starts.
    /// </summary>
    [Fact]
    public void DiscardingTheOldRunAfterAReattachLeavesTheNewPlanStartable()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            world.Receive("remodel.plan", "p2", new { });
            string again = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;

            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "d1");
            Assert.Equal(0, world.Pipeline.Count("close"));

            world.Receive("remodel.start", "s2", new { run_dir = again });
            Assert.Equal(new[] { again }, world.Pipeline.Closed);
            world.Reply("remodel.started", "s2");
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// One predicate for Start and for the close: an attachment nobody knew at the plan is not
    /// one a close may be sent through either, since the session it would reach may be another
    /// plan's. On the attachment the plan was made on the discard closes first, as it always has
    /// (<see cref="DiscardDeletesOnlyTheCopyAndKeepsEveryOtherArtifact"/>).
    /// </summary>
    [Theory]
    [InlineData(null, null, false)]
    [InlineData(null, FirstAttachment, false)]
    [InlineData(FirstAttachment, null, false)]
    [InlineData(FirstAttachment, FirstAttachment, true)]
    public void ADiscardClosesOnlyThroughTheAttachmentThePlanWasMadeOn(
        string? planned, string? now, bool closes)
    {
        using (var world = new RemodelWorld())
        {
            world.Attachment = planned;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = now;

            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("ok", "d1");
            Assert.Equal(closes ? 1 : 0, world.Pipeline.Count("close"));
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
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

    /// <summary>
    /// The reviews of decision 154A, finding F6: once a settings save has moved the run root, a remodel run made
    /// under the one before it in this SOLIDWORKS session still opens - its report and its folder - since every
    /// run root in force this session is the pane's.
    /// </summary>
    [Fact]
    public void ARunMadeUnderAnEarlierRunRootStillOpensOnceTheRunRootMoves()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            File.WriteAllText(Path.Combine(world.ExpectedRunDirectory, "report.md"), "# report");
            string moved = Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "moved", "runs");
            world.RunRootSpelling = moved;
            world.Options.RunRootsInForce = () => new[] { world.RunRoot, moved };

            world.Receive("report.open", "r1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("folder.open", "f1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("ok", "r1");
            world.Reply("ok", "f1");
            Assert.Equal(
                new[] { Path.Combine(world.ExpectedRunDirectory, "report.md"), world.ExpectedRunDirectory },
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

    // ---- the refusals the run folder's bind and the copy's activation raise (T158, T159) --

    /// <summary>
    /// T158's host half, as the host passes it on: a run folder that could not be handed to the
    /// tool service is refused `BridgeUnavailable` in the host's own words, verbatim, before
    /// anything was copied. The folder the host made is kept, as every refused plan's is, and no
    /// run is tracked or registered.
    /// </summary>
    [Fact]
    public void APlanWhoseRunFolderCouldNotBeHandedOverIsRefusedInTheHostsWords()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyFailure = new RemodelRefusal(
                "BridgeUnavailable", RemodelHost.RunNotBoundMessage, retryable: true);

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("BridgeUnavailable", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.RunNotBoundMessage, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(RemodelHost.RunNotBoundMessage, world.LastPosted("status").GetProperty("message").GetString());
            Assert.True(Directory.Exists(world.ExpectedRunDirectory));
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
            Assert.Null(world.Host.LatestRun);
            Assert.Empty(world.Registered);
        }
    }

    /// <summary>
    /// T159 before the plan: a copy SOLIDWORKS could not make the active document is refused
    /// `CopyNotActive` in the host's words, verbatim, retryable, with no run tracked; unlike
    /// `PreexistingRebuildErrors` it deletes nothing, so the run folder and the copy stay as the
    /// evidence.
    /// </summary>
    [Fact]
    public void APlanWhoseCopyCouldNotBeMadeTheActiveDocumentIsRefusedInTheHostsWordsAndKeepsTheCopy()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.PlanFailure = new RemodelRefusal(
                "CopyNotActive", RemodelHost.CopyNotActiveBeforePlanMessage, retryable: true);

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("CopyNotActive", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.CopyNotActiveBeforePlanMessage, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.True(File.Exists(world.ExpectedCopyPath), "CopyNotActive deletes nothing");
            Assert.Null(world.Host.LatestRun);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>T159 after the changes: the executor's refusal reaches the page with its class and its words.</summary>
    [Fact]
    public void AnAfterReadingOfACopyThatCouldNotBeMadeTheActiveDocumentEndsTheRunInTheHostsWords()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.RunFailure = new RemodelRefusal(
                "CopyNotActive", RemodelHost.CopyNotActiveAfterChangesMessage, retryable: false);

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = Assert.Single(world.AllPosted("error"));
            Assert.Equal("CopyNotActive", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.CopyNotActiveAfterChangesMessage, error.GetProperty("message").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());
            Assert.Contains(
                world.AllPosted("status"),
                status => status.GetProperty("stage").GetString() == "error"
                    && status.GetProperty("message").GetString() == RemodelHost.CopyNotActiveAfterChangesMessage);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// The words of this landing, pinned whole: each says what happened, that the engineer's part
    /// was not changed, and - where there is one - what to press, by the label the page gives the
    /// button; none names a command, a path or the build's plumbing.
    /// </summary>
    [Fact]
    public void TheBindAndActivationRefusalsArePlainWords()
    {
        Assert.Equal(
            "The add-in could not reach SOLIDWORKS to get the copy ready, so nothing was copied. "
            + "Your part was not changed. Wait a moment and press Remodel a copy again.",
            RemodelHost.RunNotBoundMessage);
        Assert.Equal(
            "SOLIDWORKS could not make the copy the active document - it may have been closed - so "
            + "the copy was not read and there is no plan. Nothing was changed: not your part and "
            + "not the copy. Press Remodel a copy to plan again.",
            RemodelHost.CopyNotActiveBeforePlanMessage);
        Assert.Equal(
            "SOLIDWORKS could not make the copy the active document - it may have been closed - so "
            + "the copy was not read after the changes. The run cannot be checked, and the copy was "
            + "not saved. Your part was not changed.",
            RemodelHost.CopyNotActiveAfterChangesMessage);

        foreach (string message in new[]
                 {
                     RemodelHost.RunNotBoundMessage,
                     RemodelHost.CopyNotActiveBeforePlanMessage,
                     RemodelHost.CopyNotActiveAfterChangesMessage,
                 })
        {
            AssertPlainWords(message);
        }
    }

    // ---- 004 T175: a plan that fails after the open was asked for ends its session -----------

    public static IEnumerable<object[]> PlanStepFailures => new[]
    {
        new object[] { "CopyNotActive" },
        new object[] { "PackageMissing" },
        new object[] { "HostError" },
    };

    private static Exception PlanStepFailure(string kind)
    {
        switch (kind)
        {
            case "CopyNotActive":
                return new RemodelRefusal(
                    "CopyNotActive", RemodelHost.CopyNotActiveBeforePlanMessage, retryable: true);
            case "PackageMissing":
                return new RemodelRefusal(
                    "PackageMissing", "package-before.json is not in the run folder.", retryable: false);
            default:
                // The profile check and the post-check of the dump throw no named refusal.
                return new InvalidOperationException("the dump written for 'package-before.json' names no document.");
        }
    }

    /// <summary>
    /// 004 T175 (default taken 2026-09-27, the owner may revise; research R14.1): the plan step
    /// fails after the copy exists and the bridge holds its session - the activation's
    /// `CopyNotActive`, `POST /remodel/plan`'s refusal, a dump that names no document. The host
    /// closes that session once, after the failure and before it answers, through the pipeline's
    /// close (unsaved: the copy and the folder stay as the evidence); the page gets the plan's own
    /// refusal unchanged; no run is tracked; and the next plan is not refused `RunInProgress` by a
    /// bridge still holding the failed one's session. *Changed deliberately 2026-10-21 (owner decision
    /// 159A, 004 research R19):* a failure that is no named refusal - a dump that names no document - is
    /// answered in the tab's own words, its message, which can name a path, in the host's log; its class
    /// and everything else pinned here are as they were.
    /// </summary>
    [Theory]
    [MemberData(nameof(PlanStepFailures))]
    public void APlanWhoseStepFailsAfterTheCopyExistsClosesItsSessionOnceAndAnswersItsOwnRefusal(string kind)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.HoldsTheBridgeSession = true;
            Exception failure = PlanStepFailure(kind);
            world.Pipeline.PlanFailure = failure;
            int postedAtClose = -1;
            world.Pipeline.DuringClose = () => postedAtClose = world.Posted.Count;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal(new[] { "probe", "copy", "plan", "close" }, world.Pipeline.Calls);
            Assert.Equal(new[] { world.ExpectedRunDirectory }, world.Pipeline.Closed);
            Assert.False(world.Pipeline.SessionOpen);
            Assert.True(postedAtClose >= 0 && postedAtClose <= world.IndexOf("error"), "the page was answered before the session was closed");

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal(kind, error.GetProperty("error_class").GetString());
            Assert.Equal(
                kind == "HostError" ? RemodelHost.UnexpectedFailureMessage : failure.Message,
                error.GetProperty("message").GetString());
            if (kind == "HostError")
            {
                Assert.Contains(world.Logged, line => line.Contains(failure.Message));
            }

            Assert.True(File.Exists(world.ExpectedCopyPath), "a failed plan's close deletes nothing");
            Assert.True(Directory.Exists(world.ExpectedRunDirectory));
            Assert.Null(world.Host.LatestRun);
            Assert.False(world.Host.RunInProgress);

            world.Pipeline.PlanFailure = null;
            world.Receive("remodel.plan", "p2", new { });
            world.Reply("remodel.planned", "p2");
        }
    }

    /// <summary>
    /// 004 T175, widened: the open itself fails after the bridge's open answered - the backend's
    /// own steps after it (the attestation, the geometry baseline) or a reply lost on the way - so
    /// the bridge holds a session the host was never told of. Once the open was asked for, a plan
    /// that records no run closes it, and the next plan goes ahead.
    /// </summary>
    [Fact]
    public void APlanWhoseOpenFailsClosesTheSessionTheOpenMayHaveLeftAndTheNextPlanGoesAhead()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Pipeline.CopyFailureLeavesTheSessionOpen = true;
            world.Pipeline.CopyFailure = new RemodelRefusal(
                "RunFolderFailed",
                "remodel.geometry answered a reading this build cannot read, so the run has no baseline to compare against.",
                retryable: false);

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal(new[] { "probe", "copy", "close" }, world.Pipeline.Calls);
            Assert.False(world.Pipeline.SessionOpen);
            Assert.Equal("RunFolderFailed", world.ErrorClass("p1"));
            Assert.True(Directory.Exists(world.ExpectedRunDirectory), "the run folder is the evidence and is kept");
            Assert.Null(world.Host.LatestRun);

            world.Pipeline.CopyFailure = null;
            world.Receive("remodel.plan", "p2", new { });
            world.Reply("remodel.planned", "p2");
        }
    }

    /// <summary>
    /// And an open the bridge refused, which restored everything itself, is closed too: the host
    /// cannot tell the two apart, the only session the bridge can hold then is this plan's, and a
    /// close with none is answered with no SOLIDWORKS call. It changes nothing the page is told.
    /// </summary>
    [Fact]
    public void AnOpenTheBridgeRefusedIsClosedTooAndThePageGetsTheRefusalAsItWas()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.CopyFailure = new RemodelRefusal(
                "ScopeChanged", "the copy's scope signals differ from the probe's.", retryable: true);

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal(new[] { "probe", "copy", "close" }, world.Pipeline.Calls);
            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("ScopeChanged", error.GetProperty("error_class").GetString());
            Assert.Equal("the copy's scope signals differ from the probe's.", error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
        }
    }

    public static IEnumerable<object[]> CloseFailures => new[]
    {
        new object[] { new RemodelRefusal("BridgeUnavailable", "the SOLIDWORKS bridge did not answer remodel.close.", retryable: true) },
        new object[] { new RemodelRefusal("RunFolderFailed", "the session is over, but its clean-up did not all land.", retryable: false) },
        new object[] { new IOException("the backend did not answer") },
    };

    /// <summary>
    /// A close that fails - not answered, answered with what it left, or failed with no named
    /// refusal - never replaces the plan's own refusal, and the host is free again.
    /// </summary>
    [Theory]
    [MemberData(nameof(CloseFailures))]
    public void ACloseThatFailsNeverReplacesTheFailedPlansOwnRefusal(Exception closeFailure)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.PlanFailure = PlanStepFailure("CopyNotActive");
            world.Pipeline.CloseFailure = closeFailure;

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("CopyNotActive", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.CopyNotActiveBeforePlanMessage, error.GetProperty("message").GetString());
            Assert.Equal(1, world.Pipeline.Count("close"));
            Assert.False(world.Host.RunInProgress);
            Assert.Null(world.Host.LatestRun);
        }
    }

    public static IEnumerable<object[]> RefusalsBeforeTheOpen => new[]
    {
        new object[] { "ScopeRefused" },
        new object[] { "DocumentDirty" },
        new object[] { "ProbeFailed" },
    };

    /// <summary>A plan refused before the open was asked for opened nothing, so it closes nothing.</summary>
    [Theory]
    [MemberData(nameof(RefusalsBeforeTheOpen))]
    public void APlanRefusedBeforeTheOpenSendsNoClose(string refusal)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            switch (refusal)
            {
                case "ScopeRefused":
                    world.Pipeline.Refusals = new[] { "the part is a weldment." };
                    break;
                case "DocumentDirty":
                    world.Pipeline.Signals.SaveFlagDirty = true;
                    break;
                default:
                    world.Pipeline.ProbeFailure = new RemodelRefusal(
                        "BridgeUnavailable", "the SOLIDWORKS bridge did not answer.", retryable: true);
                    break;
            }

            world.Receive("remodel.plan", "p1", new { });

            Assert.NotEmpty(world.AllPosted("error"));
            Assert.Equal(0, world.Pipeline.Count("copy"));
            Assert.Equal(0, world.Pipeline.Count("close"));
        }
    }

    /// <summary>
    /// `PreexistingRebuildErrors` keeps its own close-and-delete, once: it is the one refusal
    /// whose handler deletes a copy, and T175 adds no second close to it.
    /// </summary>
    [Fact]
    public void PreexistingRebuildErrorsStillClosesOnceAndDeletesTheCopy()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.RebuildErrorCount = 2;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("PreexistingRebuildErrors", world.ErrorClass("p1"));
            Assert.Equal(1, world.Pipeline.Count("close"));
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
        }
    }

    /// <summary>
    /// With Start switched on, a plan that succeeds keeps its session for Start: nothing is closed
    /// until Discard, planning again, a re-attach or an unload ends it.
    /// </summary>
    [Fact]
    public void WithStartSwitchedOnAPlanThatSucceedsHoldsItsSessionUntilDiscard()
    {
        using (var world = new RemodelWorld { StartValidated = true })
        {
            world.Open();
            world.Pipeline.HoldsTheBridgeSession = true;

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("remodel.planned", "p1");
            Assert.Equal(0, world.Pipeline.Count("close"));
            Assert.True(world.Pipeline.SessionOpen);
            Assert.False(world.Host.LatestRun!.SessionClosedAtPlan);

            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "d1");
            Assert.Equal(1, world.Pipeline.Count("close"));
            Assert.False(world.Pipeline.SessionOpen);
        }
    }

    // ---- 004 T176: while Start is switched off, a plan holds no session ---------------------

    /// <summary>
    /// 004 T176 (default taken 2026-09-27, the owner may revise; research R14.2): no Start can use
    /// a plan's session while Start is switched off, and holding it keeps the engineer's four
    /// application-wide settings changed for as long as the plan waits. So the host ends it as soon
    /// as the plan is made: once, after the plan step and before the `ready` status and the
    /// `remodel.planned` reply, through the pipeline's close (unsaved: the copy stays in
    /// <c>copy/</c> and <c>plan.json</c> stays <c>planned</c>). The plan is on screen and not lost.
    /// </summary>
    [Fact]
    public void WhileStartIsSwitchedOffAPlanEndsItsSessionBeforeItAnswersPlanned()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Pipeline.HoldsTheBridgeSession = true;
            int postedAtClose = -1;
            world.Pipeline.DuringClose = () => postedAtClose = world.Posted.Count;

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal(new[] { "probe", "copy", "plan", "close" }, world.Pipeline.Calls);
            Assert.Equal(new[] { world.ExpectedRunDirectory }, world.Pipeline.Closed);
            Assert.False(world.Pipeline.SessionOpen);
            int planned = world.IndexOf("remodel.planned");
            int ready = world.Posted.FindIndex(message => message.Contains("\"stage\":\"ready\""));
            Assert.True(postedAtClose >= 0 && postedAtClose <= ready && ready < planned, "the session was closed after the page was told the plan was made");

            Assert.True(File.Exists(world.ExpectedCopyPath), "the close is unsaved and deletes nothing");
            Assert.Contains("\"state\":\"planned\"", File.ReadAllText(Path.Combine(world.ExpectedRunDirectory, "plan.json")), StringComparison.Ordinal);
            RemodelRun run = world.Host.LatestRun!;
            Assert.True(run.SessionClosedAtPlan);
            Assert.Equal(RemodelRunPhase.Planned, run.Phase);

            // Not lost: nothing the plan needs went away, and Start still answers the switch.
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            world.Receive("ready", "r1", new { });
            Assert.Equal(JsonValueKind.Null, world.Reply("init", "r1").GetProperty("latest_run").GetProperty("plan_lost").ValueKind);
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("StartNotValidated", world.ErrorClass("s1"));
        }
    }

    /// <summary>Then Discard deletes <c>copy/</c> and sends no second close for a session that is over.</summary>
    [Fact]
    public void WhileStartIsSwitchedOffDiscardSendsNoSecondCloseAndDeletesTheCopy()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("ok", "d1");
            Assert.Equal(1, world.Pipeline.Count("close"));
            Assert.False(Directory.Exists(Path.Combine(world.ExpectedRunDirectory, "copy")));
        }
    }

    /// <summary>
    /// Then planning again sends no close for the earlier plan, still marks it lost and tells the
    /// page once in <see cref="RemodelHost.PlanClosedMessage"/>'s words (T173), and plans - ending
    /// the new plan's session in its turn.
    /// </summary>
    [Fact]
    public void WhileStartIsSwitchedOffPlanningAgainSendsNoCloseForTheEarlierPlanAndStillMarksItLost()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;

            world.Receive("remodel.plan", "p2", new { });

            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.Equal(new[] { first, second }, world.Pipeline.Closed);
            JsonElement lost = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(first, lost.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, lost.GetProperty("message").GetString());
            Assert.True(world.Host.FindRun(first)!.ClosedByPlanAgain);
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T223; the mutation review's M6): closes that never reached the bridge's
    /// end-of-session routine, or whose answer says nothing of it, as the add-in's pipeline raises them - the client's
    /// <c>BackendUnavailable</c> when the backend does not answer within its 30 seconds, while the backend waits 60 for the
    /// bridge, or when it is not running; its <c>HttpError</c> and <c>BadResponse</c>; the backend's refusals of the request
    /// before the bridge is asked (<c>InvalidRunDir</c>, <c>InvalidRequest</c>); and the pipeline's own refusal when no
    /// backend runs to carry the close. The bridge may still hold the session after each.
    /// </summary>
    public static IEnumerable<object[]> ClosesThatNeverReachedTheBridge => new[]
    {
        new object[] { TheBackends("BackendUnavailable", "the review backend did not answer: The operation has timed out", retryable: true) },
        new object[] { TheBackends("BackendUnavailable", "the review backend is not running.", retryable: true) },
        new object[] { TheBackends("HttpError", "the backend answered 500.", retryable: true) },
        new object[] { TheBackends("BadResponse", "the backend's answer was not JSON.") },
        new object[] { TheBackends("InvalidRunDir", "FICT run_dir is not under the run root.") },
        new object[] { TheBackends("InvalidRequest", "FICT the bridge settings did not read.") },
        new object[] { new RemodelRefusal("BackendUnavailable", "the review backend is not running, so the close was not sent.", retryable: true) },
    };

    /// <summary>
    /// Every close that may have left the session held: the bridge's own <c>BridgeUnavailable</c>, a failure with no named
    /// refusal at all, and those that never reached the bridge (<see cref="ClosesThatNeverReachedTheBridge"/>, owner decision
    /// 159A on review).
    /// </summary>
    public static IEnumerable<object[]> UnansweredCloses => new[]
    {
        new object[] { new RemodelRefusal("BridgeUnavailable", "the SOLIDWORKS bridge did not answer remodel.close.", retryable: true) },
        new object[] { new IOException("the backend did not answer") },
    }.Concat(ClosesThatNeverReachedTheBridge);

    /// <summary>
    /// A close the bridge could not answer may have left the session held, so the plan keeps it:
    /// it is still planned and answered, and a later Discard sends the close again.
    /// </summary>
    [Theory]
    [MemberData(nameof(UnansweredCloses))]
    public void WhileStartIsSwitchedOffACloseTheBridgeCouldNotAnswerLeavesThePlanHoldingItsSession(Exception closeFailure)
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Pipeline.CloseFailure = closeFailure;

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("remodel.planned", "p1");
            Assert.False(world.Host.LatestRun!.SessionClosedAtPlan);
            Assert.False(world.Host.RunInProgress);

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "d1");
            Assert.Equal(2, world.Pipeline.Count("close"));
        }
    }

    /// <summary>
    /// A close the bridge answered with what it left ended the session all the same - the routine
    /// clears it whatever it left, and what it left reaches the page as T167's one status error by
    /// the add-in's wiring - so no close is sent for it again.
    /// </summary>
    [Fact]
    public void WhileStartIsSwitchedOffACloseAnsweredWithWhatItLeftEndsTheSession()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Pipeline.CloseFailure = new RemodelRefusal(
                "RunFolderFailed", "the session is over, but its clean-up did not all land.", retryable: false);

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("remodel.planned", "p1");
            Assert.True(world.Host.LatestRun!.SessionClosedAtPlan);

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "d1");
            Assert.Equal(1, world.Pipeline.Count("close"));
        }
    }

    /// <summary>
    /// Owner decision 159A, on review, test first (004 T223; research R19.9; the mutation review's M6, older than 159A): a
    /// run's close that never reached the bridge is not taken for its answer. Every named refusal but the bridge's own
    /// `BridgeUnavailable` counted as the end-of-session routine's answer with what it left, so a close the add-in's client
    /// gave up on - after its 30 seconds, while the backend waited 60 for the bridge - was recorded as done: the run ended
    /// "The run ended 'saved'. ..." with the copy perhaps still open and the engineer's four settings still changed, and
    /// nothing would close it. The run ends in the words of a close that was not answered, keeps its session for Discard,
    /// planning again, a re-attach or an unload to end, and what the close said is in the host's log.
    /// </summary>
    [Theory]
    [MemberData(nameof(ClosesThatNeverReachedTheBridge))]
    public void ARunsCloseThatNeverReachedTheBridgeIsNotTakenForAnAnswer(Exception closeFailure)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.CloseFailure = closeFailure;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement end = world.LastPosted("status");
            Assert.Equal("error", end.GetProperty("stage").GetString());
            Assert.Equal(RemodelHost.RunCloseNotAnsweredMessage, end.GetProperty("message").GetString());
            Assert.False(world.Host.LatestRun!.SessionEnded);
            Assert.Contains(world.Logged, line => line.Contains(closeFailure.Message));

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "d1");
            Assert.Equal(2, world.Pipeline.Count("close"));
        }
    }

    /// <summary>
    /// Owner decision 159A, on review, test first (004 T223, T225; research R19.9; the mutation review's M3 and M6): an
    /// earlier plan's close that never reached the bridge leaves that plan as it was and refuses the new one, as a close the
    /// bridge did not answer does and in its words, the class the close was refused with kept and what it said in the host's
    /// log. It was taken for an answer: the earlier plan was marked lost and its session believed ended, and the new plan
    /// went on to open its copy beside it.
    /// </summary>
    [Theory]
    [MemberData(nameof(ClosesThatNeverReachedTheBridge))]
    public void AnEarlierPlansCloseThatNeverReachedTheBridgeLeavesItAsItWas(Exception closeFailure)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.CloseFailure = closeFailure;

            world.Receive("remodel.plan", "p2", new { });

            JsonElement refused = world.Reply("error", "p2");
            Assert.Equal(((RemodelRefusal)closeFailure).ErrorClass, refused.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.EarlierPlanNotClosedMessage, refused.GetProperty("message").GetString());
            Assert.True(refused.GetProperty("retryable").GetBoolean());
            Assert.Contains(world.Logged, line => line.Contains(closeFailure.Message));
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(1, world.Pipeline.Count("probe"));

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s1");
        }
    }

    // ---- the Start switch (T172's host refusal) --------------------------------------------

    /// <summary>
    /// While Start is switched off it is refused by name, in the host's words, before anything
    /// that could change anything: no `remodel.started`, no pipeline call - so no backend job and
    /// no bridge command - no status, and not one byte written in the run folder or the
    /// engineer's file. The plan stays planned, on screen and startable later; it is not lost.
    /// </summary>
    [Fact]
    public void WhileStartIsSwitchedOffStartIsRefusedInTheHostsWordsAndNothingIsCalledOrWritten()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            string source = world.CreateSourceFile();
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");

            string[] callsBefore = world.Pipeline.Calls.ToArray();
            int postedBefore = world.Posted.Count;
            string[] runFolderBefore = RemodelWorld.Snapshot(world.ExpectedRunDirectory);
            string[] sourceBefore = RemodelWorld.Snapshot(Path.GetDirectoryName(source)!);

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("StartNotValidated", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.StartNotValidatedMessage, error.GetProperty("message").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());

            Assert.Equal(postedBefore + 1, world.Posted.Count);
            Assert.Empty(world.AllPosted("remodel.started"));
            Assert.Equal(callsBefore, world.Pipeline.Calls.ToArray());
            Assert.Equal(runFolderBefore, RemodelWorld.Snapshot(world.ExpectedRunDirectory));
            Assert.Equal(sourceBefore, RemodelWorld.Snapshot(Path.GetDirectoryName(source)!));
            Assert.Equal(RemodelRunPhase.Planned, world.Host.LatestRun!.Phase);
            Assert.False(world.Host.RunInProgress);

            world.Receive("ready", "r1", new { });
            JsonElement latest = world.Reply("init", "r1").GetProperty("latest_run");
            Assert.Equal("planned", latest.GetProperty("state").GetString());
            Assert.Equal(JsonValueKind.Null, latest.GetProperty("plan_lost").ValueKind);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>Pressed again, it is refused again, the same way, and the host stays free.</summary>
    [Fact]
    public void StartPressedTwiceWhileSwitchedOffIsRefusedTwiceTheSameWay()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("remodel.start", "s2", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(world.Reply("error", "s1").ToString(), world.Reply("error", "s2").ToString());
            Assert.Equal("StartNotValidated", world.ErrorClass("s2"));
            Assert.Equal(0, world.Pipeline.Count("run"));
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// Plan runs as it does while Start is off - on the seat it exercises the adapter and the
    /// teardown - and so do Open copy, the result and Discard.
    /// </summary>
    [Fact]
    public void PlanOpenCopyTheResultAndDiscardWorkWhileStartIsSwitchedOff()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();

            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");

            world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "o1");

            world.Receive("remodel.result", "r1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Equal("planned", world.Reply("remodel.result", "r1").GetProperty("state").GetString());

            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("ok", "d1");
            Assert.False(File.Exists(world.ExpectedCopyPath));
        }
    }

    /// <summary>
    /// Where `StartNotValidated` sits in Start's order: after the refusals that say this run can
    /// never go again whatever the build - a folder this host did not plan, a run in flight, a
    /// discarded copy, a state that is not `planned` - so each keeps its own answer.
    /// </summary>
    [Fact]
    public void RunNotFoundComesBeforeStartNotValidated()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });

            world.Receive("remodel.start", "s1", new { run_dir = Path.Combine(world.RunRoot, "elsewhere") });

            Assert.Equal("RunNotFound", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// The switch is the host's constructor argument, so the only work in flight on a host built
    /// with it off is a plan: a Start naming the earlier plan while the next one is being planned
    /// is `RunInProgress`, not `StartNotValidated`.
    /// </summary>
    [Fact]
    public void RunInProgressComesBeforeStartNotValidated()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string earlier = world.ExpectedRunDirectory;
            world.Pipeline.DuringProbe = () =>
                world.Receive("remodel.start", "s1", new { run_dir = earlier });

            world.Receive("remodel.plan", "p2", new { });

            Assert.Equal("RunInProgress", world.ErrorClass("s1"));
            Assert.Equal(0, world.Pipeline.Count("run"));
        }
    }

    [Fact]
    public void ADiscardedCopyComesBeforeStartNotValidated()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("CopyDiscarded", world.ErrorClass("s1"));
        }
    }

    [Theory]
    [InlineData("applying")]
    [InlineData("saved")]
    [InlineData("failed")]
    public void AResumeRefusalComesBeforeStartNotValidated(string state)
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.WritePlanState(state);

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("ResumeRefused", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// And before everything about the plan's session and the seat (research R13.8, D2): a Start
    /// this build can never honour says so first, so a plan the tool service re-attached under is
    /// not sent back to be planned again only to meet this answer next.
    /// </summary>
    [Fact]
    public void StartNotValidatedComesBeforeSessionLost()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Attachment = SecondAttachment;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("StartNotValidated", world.ErrorClass("s1"));
        }
    }

    [Theory]
    [InlineData(RemodelAvailability.Unavailable)]
    [InlineData(RemodelAvailability.Unknown)]
    public void StartNotValidatedComesBeforeTheSeatCheck(RemodelAvailability availability)
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.RemodelCapability = availability;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("StartNotValidated", world.ErrorClass("s1"));
        }
    }

    [Fact]
    public void StartNotValidatedComesBeforeNotAttached()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Options.Pipeline = null;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("StartNotValidated", world.ErrorClass("s1"));
        }
    }

    /// <summary>
    /// T172's words: Start is not switched on in this build yet, Plan and Discard work - named
    /// by their buttons' labels, which the page tests read off the page - and nothing was
    /// changed. No command, no path, no probe number and none of the build's plumbing.
    /// </summary>
    [Fact]
    public void TheStartNotValidatedMessageIsPlainWordsAndNamesNoProbe()
    {
        Assert.Equal(
            "Start is not switched on in this build yet, so this plan cannot be applied to the copy. "
            + "Remodel a copy and Discard copy still work, and the plan stays in its run folder. "
            + "Nothing was changed: not your part and not the copy.",
            RemodelHost.StartNotValidatedMessage);

        AssertPlainWords(RemodelHost.StartNotValidatedMessage);
        Assert.DoesNotContain("probe", RemodelHost.StartNotValidatedMessage, StringComparison.OrdinalIgnoreCase);
        Assert.False(
            RemodelHost.StartNotValidatedMessage.Any(char.IsDigit),
            "the sentence names no probe number, nor any other number");
    }

    // ---- when a re-attach or an unload ends the session (T167's words) --------------------

    private const string NothingPutBack =
        "Not everything the plan changed in SOLIDWORKS could be put back. Your part was not changed.";

    /// <summary>
    /// Success is quiet: a teardown that put every setting back and closed the copy tells the
    /// page nothing, and neither does one handed no list at all.
    /// </summary>
    [Fact]
    public void ASessionThatEndedWithNothingLeftTellsThePageNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int before = world.Posted.Count;

            world.Host.SessionEnded(new int[0], commandInProgressNotRestored: false, copyClosed: true);
            world.Host.SessionEnded(null, commandInProgressNotRestored: false, copyClosed: true);

            Assert.Equal(before, world.Posted.Count);
            Assert.Null(RemodelHost.SessionEndedMessage(new int[0], false, true));
            Assert.Null(RemodelHost.SessionEndedMessage(null, false, true));
        }
    }

    /// <summary>
    /// A teardown that left something posts exactly one `status {stage: "error"}`, in the host's
    /// words, and nothing else.
    /// </summary>
    [Fact]
    public void ASessionThatLeftSomethingPostsOneErrorStatusInTheHostsWords()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int before = world.Posted.Count;
            int[] left = { RemodelSystemToggles.ShowErrorsEveryRebuild };

            world.Host.SessionEnded(left, commandInProgressNotRestored: true, copyClosed: false);

            Assert.Equal(new[] { "status" }, world.TypesPostedSince(before));
            JsonElement status = world.LastPosted("status");
            Assert.Equal("error", status.GetProperty("stage").GetString());
            Assert.Equal(
                RemodelHost.SessionEndedMessage(left, true, false),
                status.GetProperty("message").GetString());
        }
    }

    [Fact]
    public void OneSettingLeftIsNamedByItsToolsOptionsLabel()
    {
        Assert.Equal(
            NothingPutBack + " The setting \"Show errors every rebuild\" in Tools > Options > System "
            + "Options > General may still be as the plan left it: set it back the way you had it.",
            RemodelHost.SessionEndedMessage(new[] { RemodelSystemToggles.ShowErrorsEveryRebuild }, false, true));
    }

    [Fact]
    public void TwoSettingsLeftAreNamedTogether()
    {
        Assert.Equal(
            NothingPutBack + " These settings in Tools > Options > System Options > General may still "
            + "be as the plan left them: \"Input dimension value\" and \"Warn before saving documents "
            + "with update errors\". Set them back the way you had them.",
            RemodelHost.SessionEndedMessage(
                new[] { RemodelSystemToggles.WarnSaveUpdateErrors, RemodelSystemToggles.InputDimValOnCreate },
                false,
                true));
    }

    /// <summary>
    /// All three, named once each and in the order the run sets them, however they were handed
    /// over - out of order, and one of them twice.
    /// </summary>
    [Fact]
    public void EverySettingLeftIsNamedOnceInTheOrderTheRunSetsThem()
    {
        Assert.Equal(
            NothingPutBack + " These settings in Tools > Options > System Options > General may still "
            + "be as the plan left them: \"Input dimension value\", \"Show errors every rebuild\" and "
            + "\"Warn before saving documents with update errors\". Set them back the way you had them.",
            RemodelHost.SessionEndedMessage(
                new[]
                {
                    RemodelSystemToggles.WarnSaveUpdateErrors,
                    RemodelSystemToggles.ShowErrorsEveryRebuild,
                    RemodelSystemToggles.InputDimValOnCreate,
                    RemodelSystemToggles.ShowErrorsEveryRebuild,
                },
                false,
                true));
    }

    /// <summary>`CommandInProgress` has no Tools > Options label; its words say what it does and how it clears.</summary>
    [Fact]
    public void TheCommandInProgressFlagLeftIsWordedByWhatItDoes()
    {
        Assert.Equal(
            NothingPutBack + " SOLIDWORKS may keep some of its messages hidden until you restart it.",
            RemodelHost.SessionEndedMessage(new int[0], true, true));
    }

    /// <summary>A copy the routine did not close may still be open: named by its suffix, never by its path.</summary>
    [Fact]
    public void ACopyThatWasNotClosedIsNamedBySuffixAndNeverByPath()
    {
        Assert.Equal(
            NothingPutBack + " The copy may still be open in SOLIDWORKS (its name ends in -RMS): close "
            + "it without saving.",
            RemodelHost.SessionEndedMessage(new int[0], false, false));
        Assert.Contains(RemodelCopy.CopySuffix, RemodelHost.SessionEndedMessage(new int[0], false, false));
    }

    /// <summary>
    /// A value that is not one of the three toggles is still something left: it is worded as
    /// another setting rather than dropped, alone or beside the ones that have labels.
    /// </summary>
    [Fact]
    public void ASettingWithNoLabelIsStillSaidRatherThanDropped()
    {
        Assert.Equal(
            NothingPutBack + " A setting the plan changed may not be as you had it.",
            RemodelHost.SessionEndedMessage(new[] { 999 }, false, true));
        Assert.Equal(
            NothingPutBack + " The setting \"Input dimension value\" in Tools > Options > System Options "
            + "> General may still be as the plan left it: set it back the way you had it. Another "
            + "setting the plan changed may also not be as you had it.",
            RemodelHost.SessionEndedMessage(new[] { 999, RemodelSystemToggles.InputDimValOnCreate, -1 }, false, true));
    }

    [Fact]
    public void EverythingLeftAtOnceIsSaidInOneStatusInAFixedOrder()
    {
        Assert.Equal(
            NothingPutBack + " These settings in Tools > Options > System Options > General may still "
            + "be as the plan left them: \"Input dimension value\", \"Show errors every rebuild\" and "
            + "\"Warn before saving documents with update errors\". Set them back the way you had them. "
            + "Another setting the plan changed may also not be as you had it. SOLIDWORKS may keep "
            + "some of its messages hidden until you restart it. The copy may still be open in "
            + "SOLIDWORKS (its name ends in -RMS): close it without saving.",
            RemodelHost.SessionEndedMessage(
                RemodelSystemToggles.SuppressedToggles.Concat(new[] { 42 }), true, false));
    }

    /// <summary>
    /// Every toggle the run changes has a label, so a fourth added to
    /// <see cref="RemodelSystemToggles.SuppressedToggles"/> without one fails here rather than
    /// being worded as "a setting".
    /// </summary>
    [Fact]
    public void EveryToggleTheRunChangesHasALabel()
    {
        foreach (int toggle in RemodelSystemToggles.SuppressedToggles)
        {
            string message = RemodelHost.SessionEndedMessage(new[] { toggle }, false, true)!;
            Assert.StartsWith(NothingPutBack + " The setting \"", message, StringComparison.Ordinal);
            Assert.DoesNotContain("setting the plan changed", message, StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// The labels are the ones the workstation test plan already asks the engineer to read on the
    /// General page, so the two cannot name different settings. Whether 2024 SP5 spells them so is
    /// a seat item (research R13.8, D8).
    /// </summary>
    [Fact]
    public void TheLabelsAreTheOnesTheWorkstationTestPlanReads()
    {
        // Read with every run of white space as one space: a label can wrap across the plan's lines.
        string plan = Regex.Replace(
            File.ReadAllText(Path.Combine(
                ErrorLabelsCoverTheHostTests.RepositoryRoot(), "docs", "test-plan-2026-09-27", "workstation-test-plan.md")),
            @"\s+",
            " ");
        string message = RemodelHost.SessionEndedMessage(RemodelSystemToggles.SuppressedToggles, false, true)!;

        foreach (string label in new[]
                 {
                     "Input dimension value", "Show errors every rebuild", "Warn before saving documents with update errors",
                 })
        {
            Assert.Contains("\"" + label + "\"", message, StringComparison.Ordinal);
            Assert.Contains("**" + label + "**", plan, StringComparison.Ordinal);
        }

        Assert.Contains("Tools > Options > System Options", plan, StringComparison.Ordinal);
    }

    /// <summary>Every combination is plain words: no command, no path and none of the build's plumbing.</summary>
    [Fact]
    public void TheTeardownWordsArePlainWordsInEveryCombination()
    {
        int[][] toggleSets =
        {
            new int[0],
            new[] { RemodelSystemToggles.InputDimValOnCreate },
            RemodelSystemToggles.SuppressedToggles.ToArray(),
            new[] { 7 },
        };

        int said = 0;
        foreach (int[] toggles in toggleSets)
        {
            foreach (bool commandInProgress in new[] { false, true })
            {
                foreach (bool copyClosed in new[] { false, true })
                {
                    string? message = RemodelHost.SessionEndedMessage(toggles, commandInProgress, copyClosed);
                    if (message == null)
                    {
                        Assert.True(toggles.Length == 0 && !commandInProgress && copyClosed);
                        continue;
                    }

                    said++;
                    Assert.StartsWith(NothingPutBack, message, StringComparison.Ordinal);
                    AssertPlainWords(message);
                }
            }
        }

        Assert.Equal(15, said);
    }

    /// <summary>
    /// Called from the tool service's teardown, so it never throws - not even when the page
    /// cannot be told.
    /// </summary>
    [Fact]
    public void SessionEndedNeverThrowsEvenWhenThePageCannotBeTold()
    {
        var host = new RemodelHost(new RemodelHostOptions(new ThrowingChannel(), () => "C:\\runs"));

        host.SessionEnded(RemodelSystemToggles.SuppressedToggles, true, false);
    }

    // ---- the routine's outcome, as the add-in hands it over (lanes D and E integrated) ----------

    /// <summary>
    /// An ending of a session that existed, as lane D's routine reports it: the settings still
    /// holding the run's value by <see cref="RemodelSystemToggles.Outstanding"/>'s names, and
    /// whether the copy was closed. Everything else is what a clean ending has.
    /// </summary>
    private static RemodelSessionEnd Ended(
        IReadOnlyList<string> settingsOutstanding,
        bool copyClosed = true,
        bool verified = true,
        bool tagRemoved = true,
        string reason = RemodelSessionEnd.ReasonToolServiceStopped)
    {
        var failures = new List<string>();
        if (settingsOutstanding.Count > 0)
        {
            failures.Add("the settings were not all put back");
        }

        if (!copyClosed)
        {
            failures.Add("close: the copy was not closed");
        }

        if (!tagRemoved)
        {
            failures.Add("untag: the tag did not come off");
        }

        return new RemodelSessionEnd(
            reason,
            @"C:\runs\20260916-142201-bracket-remodel",
            @"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT",
            verified,
            verified ? (RemodelTargetCheck?)null : RemodelTargetCheck.DocumentPath,
            tagRemoved,
            copyClosed,
            settingsOutstanding,
            failures);
    }

    /// <summary>
    /// The add-in hands <see cref="RemodelHost.SessionEnded(RemodelSessionEnd)"/> the routine's
    /// outcome as it is, and the host reads the three facts its words need off it: each setting
    /// left by the name the routine gives it, <c>CommandInProgress</c> apart, and whether the
    /// copy was closed. What is posted is exactly what the three-fact seam posts for the same
    /// facts, so the words have one source.
    /// </summary>
    [Fact]
    public void AnOutcomeThatLeftSomethingPostsTheWordsForWhatItLeft()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int before = world.Posted.Count;

            world.Host.SessionEnded(Ended(
                new[]
                {
                    RemodelSystemToggles.SettingName(RemodelSystemToggles.ShowErrorsEveryRebuild),
                    RemodelSystemToggles.CommandInProgressSetting,
                },
                copyClosed: false));

            Assert.Equal(new[] { "status" }, world.TypesPostedSince(before));
            JsonElement status = world.LastPosted("status");
            Assert.Equal("error", status.GetProperty("stage").GetString());
            Assert.Equal(
                RemodelHost.SessionEndedMessage(new[] { RemodelSystemToggles.ShowErrorsEveryRebuild }, true, false),
                status.GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// 004 T177: a failed <c>remodel.open</c>'s ending is worded as every other ending is - the
    /// reason decides nothing - so an unwind that could not close the copy or put a setting back
    /// posts the same one status error, and no verification or tag is worded.
    /// </summary>
    [Fact]
    public void AFailedOpensEndingIsWordedAsEveryOtherEnding()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int before = world.Posted.Count;

            world.Host.SessionEnded(Ended(
                new[] { RemodelSystemToggles.CommandInProgressSetting },
                copyClosed: false,
                verified: false,
                tagRemoved: false,
                reason: RemodelSessionEnd.ReasonOpenFailed));

            Assert.Equal(new[] { "status" }, world.TypesPostedSince(before));
            Assert.Equal(
                RemodelHost.SessionEndedMessage(new int[0], true, false),
                world.LastPosted("status").GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// Every one of the three toggles the routine can report is read back to its value, so each
    /// is named by its label; the routine's order does not matter.
    /// </summary>
    [Fact]
    public void EveryToggleTheRoutineNamesIsReadBackToItsLabel()
    {
        Assert.Equal(
            RemodelHost.SessionEndedMessage(RemodelSystemToggles.SuppressedToggles, false, true),
            RemodelHost.SessionEndedMessage(Ended(RemodelSystemToggles.SuppressedToggles
                .Reverse()
                .Select(RemodelSystemToggles.SettingName)
                .ToArray())));
    }

    /// <summary>
    /// A clean ending tells the page nothing, whatever ended it; and neither does an ending of
    /// no session, which the routine reports when a teardown found nothing to end.
    /// </summary>
    [Theory]
    [InlineData(RemodelSessionEnd.ReasonClose)]
    [InlineData(RemodelSessionEnd.ReasonToolServiceStopped)]
    [InlineData(RemodelSessionEnd.ReasonOpenFailed)]
    public void ACleanEndingOrNoSessionTellsThePageNothing(string reason)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int before = world.Posted.Count;

            world.Host.SessionEnded(Ended(new string[0], reason: reason));
            world.Host.SessionEnded(RemodelSessionEnd.NoSession(reason));

            Assert.Equal(before, world.Posted.Count);
            Assert.Null(RemodelHost.SessionEndedMessage(Ended(new string[0], reason: reason)));
            Assert.Null(RemodelHost.SessionEndedMessage(RemodelSessionEnd.NoSession(reason)));
        }
    }

    /// <summary>
    /// A verification that failed closes nothing, so the copy may still be open and the words say
    /// so, by its suffix; the settings the routine put back regardless are not mentioned.
    /// </summary>
    [Fact]
    public void AnEndingWhoseVerificationFailedSaysTheCopyMayStillBeOpen()
    {
        Assert.Equal(
            NothingPutBack + " The copy may still be open in SOLIDWORKS (its name ends in -RMS): close "
            + "it without saving.",
            RemodelHost.SessionEndedMessage(Ended(new string[0], copyClosed: false, verified: false, tagRemoved: false)));
    }

    /// <summary>
    /// 004 T179 (default taken 2026-09-27, the owner may revise; research R15.3): a close SOLIDWORKS
    /// did not carry out, and one nobody could confirm, are both a copy not closed, and the words -
    /// that it may still be open - are true of both; the tag SOLIDWORKS would not remove is still
    /// not worded.
    /// </summary>
    [Theory]
    [InlineData("close: CloseDoc returned, but SOLIDWORKS still has the copy open")]
    [InlineData("close: CloseDoc returned, but whether SOLIDWORKS still has the copy open could not be read, so it is not counted as closed: COMException: the RPC server is unavailable")]
    public void AnEndingWhoseCloseWasNotConfirmedSaysTheCopyMayStillBeOpen(string failure)
    {
        var outcome = new RemodelSessionEnd(
            RemodelSessionEnd.ReasonToolServiceStopped,
            @"C:\runs\20260916-142201-bracket-remodel",
            @"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT",
            verified: true,
            failedCheck: null,
            tagRemoved: false,
            copyClosed: false,
            settingsOutstanding: new string[0],
            failures: new[] { "untag: Delete2 answered swCustomInfoDeleteResult_NotPresent (1)", failure });

        Assert.Equal(
            NothingPutBack + " The copy may still be open in SOLIDWORKS (its name ends in -RMS): close "
            + "it without saving.",
            RemodelHost.SessionEndedMessage(outcome));
    }

    /// <summary>
    /// A setting name the host has no toggle for is still something left, worded as another
    /// setting rather than dropped.
    /// </summary>
    [Fact]
    public void ASettingNameTheHostDoesNotKnowIsStillSaid()
    {
        Assert.Equal(
            NothingPutBack + " A setting the plan changed may not be as you had it.",
            RemodelHost.SessionEndedMessage(Ended(new[] { "swSomeFutureToggle" })));
    }

    /// <summary>
    /// A tag the routine could not take off, with the copy closed and every setting back, leaves
    /// nothing the engineer can act on - the unsaved close took the tag with the document - so it
    /// tells the page nothing; the routine's line in the logs carries it.
    /// </summary>
    [Fact]
    public void ATagLeftOnAClosedCopyTellsThePageNothing()
    {
        Assert.Null(RemodelHost.SessionEndedMessage(Ended(new string[0], tagRemoved: false)));
    }

    /// <summary>Called from the tool service's teardown, so a null outcome is nothing, never a throw.</summary>
    [Fact]
    public void ANullOutcomeIsNothingAndNeverAThrow()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int before = world.Posted.Count;

            world.Host.SessionEnded((RemodelSessionEnd?)null);

            Assert.Equal(before, world.Posted.Count);
            new RemodelHost(new RemodelHostOptions(new ThrowingChannel(), () => "C:\\runs"))
                .SessionEnded(Ended(RemodelSystemToggles.SuppressedToggles.Select(RemodelSystemToggles.SettingName).ToArray(), copyClosed: false));
        }
    }

    // ---- the words rule ----------------------------------------------------------------------

    /// <summary>The build's plumbing, which no sentence this tab shows the engineer may name (U13).</summary>
    private static readonly string[] Plumbing =
    {
        "swreview-extract", "--", "tool service", "bridge", "pipe", "attach", "session",
        "dispatcher", "remodel.", "\\", ".SLDPRT",
    };

    private static void AssertPlainWords(string message)
    {
        foreach (string word in Plumbing)
        {
            Assert.DoesNotContain(word, message, StringComparison.OrdinalIgnoreCase);
        }
    }

    // ---- the world -----------------------------------------------------------------------

    // ---- 004 T172: Start is switched off until the blocking probes pass ---------------------

    /// <summary>
    /// The pin: Start ships switched off, and the host as shipped is built with the one switch,
    /// so the commit that sets it true - citing the capabilities ledger's verdicts for PROBE-1,
    /// 2, 3, 4 and 12 - edits this case and `BridgeDispatcherTests`' in the same commit.
    /// </summary>
    [Fact]
    public void TheShippedHostIsBuiltWithTheShippedSwitch()
    {
        Assert.False(RemodelStart.SeatValidated);

        var channel = new CollectingChannel(new List<string>());
        var shipped = new RemodelHost(new RemodelHostOptions(channel, () => Path.GetTempPath()));
        var off = new RemodelHost(new RemodelHostOptions(channel, () => Path.GetTempPath()), startValidated: false);
        var on = new RemodelHost(new RemodelHostOptions(channel, () => Path.GetTempPath()), startValidated: true);

        Assert.Equal(RemodelStart.SeatValidated, shipped.StartValidated);
        Assert.False(off.StartValidated);
        Assert.True(on.StartValidated);
    }

    /// <summary>
    /// Nothing a plan records depends on the switch: the plan a build with Start switched off
    /// makes is the plan one with it on makes, message for message and file for file, so once
    /// the switch is set the same plan starts. (The switch is the host's constructor argument, so
    /// one host cannot flip it; two hosts over two run roots show the plans are the same.)
    /// *Amended 2026-09-27 (004 T176):* the one difference is the close that ends the plan's
    /// session at the end of a plan made while the switch is off, which changes no message and no
    /// file.
    /// </summary>
    [Fact]
    public void APlanMadeWhileTheSwitchIsOffIsThePlanThatStartsOnceItIsOn()
    {
        using (var off = new RemodelWorld { StartValidated = false })
        using (var on = new RemodelWorld { StartValidated = true })
        {
            off.Open();
            on.Open();
            off.Receive("remodel.plan", "p1", new { });
            on.Receive("remodel.plan", "p1", new { });

            Assert.Equal(StripRunRoot(off, off.Posted), StripRunRoot(on, on.Posted));
            Assert.Equal(on.Pipeline.Calls.Concat(new[] { "close" }), off.Pipeline.Calls);
            Assert.Equal(
                File.ReadAllText(Path.Combine(off.ExpectedRunDirectory, "plan.json")),
                File.ReadAllText(Path.Combine(on.ExpectedRunDirectory, "plan.json")));

            on.Receive("remodel.start", "s1", new { run_dir = on.ExpectedRunDirectory });
            on.Reply("remodel.started", "s1");
            Assert.Equal(1, on.Pipeline.Count("run"));
        }
    }

    private static string[] StripRunRoot(RemodelWorld world, IEnumerable<string> posted) =>
        posted.Select(message => message.Replace(JsonSerializer.Serialize(world.RunRoot).Trim('"'), "<run_root>")).ToArray();

    // ---- 004 T173: planning again while an earlier plan waits for Start ----------------------

    [Fact]
    public void PlanningAgainClosesTheEarlierPlanThenMarksItLostAndTellsThePageThenPlans()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            string firstCopy = world.ExpectedCopyPath;
            int postedAtClose = -1;
            int postedAtProbe = -1;
            world.Pipeline.DuringClose = () => postedAtClose = world.Posted.Count;
            world.Pipeline.DuringProbe = () => postedAtProbe = world.Posted.Count;

            world.Receive("remodel.plan", "p2", new { });

            // The close, then the mark and the notice, then the plan as today.
            Assert.Equal(new[] { first }, world.Pipeline.Closed);
            int notice = world.Posted.FindIndex(message => message.Contains("\"remodel.plan_lost\""));
            Assert.True(postedAtClose >= 0 && notice >= postedAtClose, "the notice came before the close");
            Assert.True(postedAtProbe > notice, "the new plan probed before the earlier plan was told lost");
            JsonElement lost = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(first, lost.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, lost.GetProperty("message").GetString());

            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.NotEqual(first, second);

            // The earlier plan's folder is whole, its copy still in copy/, plan.json still planned.
            Assert.True(File.Exists(firstCopy));
            Assert.Contains("\"state\":\"planned\"", File.ReadAllText(Path.Combine(first, "plan.json")), StringComparison.Ordinal);
        }
    }

    [Fact]
    public void AStartNamingTheEarlierPlanIsSessionLostInThePlanClosedWordsAndCallsNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Receive("remodel.plan", "p2", new { });
            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            int calls = world.Pipeline.Calls.Count;

            world.Receive("remodel.start", "s1", new { run_dir = first });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("SessionLost", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, error.GetProperty("message").GetString());
            Assert.Equal(calls, world.Pipeline.Calls.Count);

            // The new plan is the one on screen, and it starts.
            world.Receive("ready", "r1", new { });
            JsonElement latest = world.Reply("init", "r1").GetProperty("latest_run");
            Assert.Equal(second, latest.GetProperty("run_dir").GetString());
            Assert.Equal(JsonValueKind.Null, latest.GetProperty("plan_lost").ValueKind);
            world.Receive("remodel.start", "s2", new { run_dir = second });
            world.Reply("remodel.started", "s2");
        }
    }

    public static IEnumerable<object[]> OnTheSpotRefusals => new[]
    {
        new object[] { "NoDocument" },
        new object[] { "NotAPart" },
        new object[] { "RemodelUnavailable" },
        new object[] { "SourceIsRemodelCopy" },
    };

    [Theory]
    [MemberData(nameof(OnTheSpotRefusals))]
    public void APlanRefusedOnTheSpotCostsTheEarlierPlanNothing(string refusal)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            PageDocument? source = world.Document;
            int posted = world.Posted.Count;

            switch (refusal)
            {
                case "NoDocument":
                    world.Document = null;
                    break;
                case "NotAPart":
                    world.Document = new PageDocument(@"C:\parts\bracket-assy.SLDASM", "Default");
                    break;
                case "RemodelUnavailable":
                    world.RemodelCapability = RemodelAvailability.Unavailable;
                    break;
                default:
                    // Once the pipeline activates the copy for its dump (T159), the earlier plan's
                    // own copy can be the active document when Plan is pressed again.
                    world.Document = new PageDocument(world.ExpectedCopyPath, "Default");
                    break;
            }

            world.Receive("remodel.plan", "p2", new { });

            Assert.Equal(refusal, world.ErrorClass("p2"));
            Assert.Empty(world.Pipeline.Closed);
            Assert.DoesNotContain("remodel.plan_lost", world.TypesPostedSince(posted));

            world.Document = source;
            world.RemodelCapability = RemodelAvailability.Available;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s1");
        }
    }

    [Fact]
    public void AReattachSinceTheEarlierPlanSendsNoCloseAndStillMarksItLost()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;

            // The attachment changed with no refresh to tell the page: the plan's session went
            // with it, so there is nothing to close through the attachment listening now.
            world.Attachment = SecondAttachment;
            world.Receive("remodel.plan", "p2", new { });

            Assert.Empty(world.Pipeline.Closed);
            JsonElement lost = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(first, lost.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, lost.GetProperty("message").GetString());
            world.Reply("remodel.planned", "p2");

            world.Receive("remodel.start", "s1", new { run_dir = first });
            Assert.Equal(RemodelHost.PlanClosedMessage, world.Reply("error", "s1").GetProperty("message").GetString());
        }
    }

    [Fact]
    public void APlanAlreadyToldLostIsNotToldAgainWhenPlanningAgainClosesIt()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reattach(SecondAttachment);
            Assert.Equal(RemodelHost.PlanLostMessage, Assert.Single(world.AllPosted("remodel.plan_lost")).GetProperty("message").GetString());

            world.Receive("remodel.plan", "p2", new { });

            Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Empty(world.Pipeline.Closed);
            world.Reply("remodel.planned", "p2");
        }
    }

    [Fact]
    public void ANewPlanTheScopeGateRefusesLeavesTheEarlierPlanLostAndItsNoticeStanding()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.Refusals = new[] { "weldment: the part is a weldment" };

            world.Receive("remodel.plan", "p2", new { });

            Assert.Equal("ScopeRefused", world.ErrorClass("p2"));
            Assert.Equal(new[] { first }, world.Pipeline.Closed);
            Assert.Equal(first, Assert.Single(world.AllPosted("remodel.plan_lost")).GetProperty("run_dir").GetString());

            world.Receive("ready", "r1", new { });
            JsonElement latest = world.Reply("init", "r1").GetProperty("latest_run");
            Assert.Equal(first, latest.GetProperty("run_dir").GetString());
            Assert.Equal(RemodelHost.PlanClosedMessage, latest.GetProperty("plan_lost").GetString());

            world.Receive("remodel.start", "s1", new { run_dir = first });
            Assert.Equal("SessionLost", world.ErrorClass("s1"));
        }
    }

    [Fact]
    public void ACloseTheBridgeCouldNotAnswerRefusesTheNewPlanAndLeavesTheEarlierOneAsItWas()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.CloseFailure = new RemodelRefusal(
                "BridgeUnavailable", "the SOLIDWORKS bridge did not answer remodel.close", retryable: true);

            world.Receive("remodel.plan", "p2", new { });

            Assert.Equal("BridgeUnavailable", world.ErrorClass("p2"));
            // The earlier plan's probe only: the new plan went no further than the close.
            Assert.Equal(1, world.Pipeline.Count("probe"));
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            Assert.Single(Directory.GetDirectories(world.RunRoot));

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s1");
        }
    }

    /// <summary>
    /// A close that failed with no named refusal counts as unanswered: the new plan is refused
    /// `BridgeUnavailable` and the earlier plan stays as it was. *Changed deliberately 2026-10-21 (owner
    /// decision 159A, 004 research R19):* the refusal is in the tab's own words, where it ended with the
    /// close's own message, which can name the bridge's pipe and is now in the host's log.
    /// </summary>
    [Fact]
    public void ACloseThatFailedWithoutANamedRefusalCountsAsUnanswered()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.CloseFailure = new InvalidOperationException("the loopback socket closed");

            world.Receive("remodel.plan", "p2", new { });

            JsonElement error = world.Reply("error", "p2");
            Assert.Equal("BridgeUnavailable", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.EarlierPlanNotClosedMessage, error.GetProperty("message").GetString());
            Assert.Contains(world.Logged, line => line.Contains("the loopback socket closed"));
            Assert.Empty(world.AllPosted("remodel.plan_lost"));

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s1");
        }
    }

    /// <summary>
    /// A close the bridge answered with what it left - the routine clears the session whatever it
    /// left - lets the new plan go ahead. What it left reaches the page as T167's one status
    /// error through <c>ToolServiceOptions.RemodelSessionEnded</c>, which is told every ending,
    /// this close's included, so nothing here posts a second one.
    /// </summary>
    [Fact]
    public void ACloseThatAnsweredWithWhatItLeftLetsTheNewPlanGoAhead()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.CloseFailure = new RemodelRefusal(
                "RunFolderFailed", "the session is over, but its clean-up did not all land");
            int posted = world.Posted.Count;

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Equal(first, Assert.Single(world.AllPosted("remodel.plan_lost")).GetProperty("run_dir").GetString());
            Assert.DoesNotContain(
                world.Posted.Skip(posted),
                message => message.Contains("clean-up did not all land"));
        }
    }

    [Fact]
    public void PlanningAfterTheEarlierRunFinishedOrItsCopyWasDiscardedClosesNoOtherSession()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            Assert.Single(world.Pipeline.Closed);

            world.Receive("remodel.plan", "p2", new { });
            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.Single(world.Pipeline.Closed);

            world.Receive("remodel.start", "s1", new { run_dir = second });
            world.Reply("remodel.started", "s1");
            world.Receive("remodel.plan", "p3", new { });
            world.Reply("remodel.planned", "p3");

            Assert.Equal(new[] { world.ExpectedRunDirectory, second }, world.Pipeline.Closed);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// T168's hazard, the other way round: `remodel.close` named no run until owner decision 159A,
    /// and the bridge closed whatever session it held - after planning again, that is the new plan's. A plan planning
    /// again closed has no session left anywhere, so discarding it sends no close, on its own
    /// attachment or any other, and still deletes its copy and writes `discarded`; the new plan
    /// is untouched and starts.
    /// </summary>
    [Fact]
    public void DiscardingAPlanThatPlanningAgainClosedSendsNoCloseAndLeavesTheNewPlanStartable()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Receive("remodel.plan", "p2", new { });
            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.Equal(new[] { first }, world.Pipeline.Closed);

            world.Receive("remodel.discard_copy", "d1", new { run_dir = first });

            world.Reply("ok", "d1");
            Assert.Equal(new[] { first }, world.Pipeline.Closed);
            Assert.False(Directory.Exists(Path.Combine(first, "copy")));
            world.Receive("remodel.result", "g1", new { run_dir = first });
            Assert.Equal("discarded", world.Reply("remodel.result", "g1").GetProperty("state").GetString());

            world.Receive("remodel.start", "s1", new { run_dir = second });
            world.Reply("remodel.started", "s1");
        }
    }

    [Fact]
    public void PlanningAgainAfterAPlanAgainWasRefusedDoesNotCloseTheEarlierPlanTwice()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.Refusals = new[] { "weldment: the part is a weldment" };
            world.Receive("remodel.plan", "p2", new { });
            Assert.Equal("ScopeRefused", world.ErrorClass("p2"));

            world.Pipeline.Refusals = new string[0];
            world.Receive("remodel.plan", "p3", new { });

            world.Reply("remodel.planned", "p3");
            Assert.Equal(new[] { first }, world.Pipeline.Closed);
            Assert.Single(world.AllPosted("remodel.plan_lost"));
        }
    }

    [Fact]
    public void ThePlanClosedSentenceKeepsSessionLostsRulesAndNamesThePlanAgainButton()
    {
        string sentence = RemodelHost.PlanClosedMessage;

        Assert.Contains("Your part was not changed", sentence, StringComparison.Ordinal);
        Assert.Contains("Plan again", sentence, StringComparison.Ordinal);
        Assert.DoesNotContain("remodel.", sentence, StringComparison.Ordinal);
        Assert.DoesNotContain("\\", sentence, StringComparison.Ordinal);
        Assert.NotEqual(RemodelHost.PlanLostMessage, sentence);
    }

    // ---- 004 T173: a copy is never a source -------------------------------------------------

    public static IEnumerable<object[]> CopyPaths => new[]
    {
        new object[] { "the run's copy", false },
        new object[] { "another case", false },
        new object[] { "through ..", false },
        new object[] { "a part outside run_root", true },
        new object[] { "a folder merely named copy elsewhere", true },
        new object[] { "a copy folder two levels down", true },
        new object[] { "a part in a run folder but not in its copy", true },
    };

    [Theory]
    [MemberData(nameof(CopyPaths))]
    public void AnActiveDocumentInARunFoldersCopyIsRefusedBeforeAnyBridgeCall(string where, bool allowed)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            string runRoot = world.RunRoot;
            string run = Path.Combine(runRoot, "20260915-090000-bracket-remodel");
            string path;
            switch (where)
            {
                case "the run's copy":
                    path = Path.Combine(run, "copy", "bracket-RMS.SLDPRT");
                    break;
                case "another case":
                    path = Path.Combine(runRoot.ToUpperInvariant(), "20260915-090000-BRACKET-REMODEL", "COPY", "BRACKET-RMS.SLDPRT");
                    break;
                case "through ..":
                    path = Path.Combine(runRoot, "elsewhere", "..", "20260915-090000-bracket-remodel", "copy", "bracket-RMS.SLDPRT");
                    break;
                case "a part outside run_root":
                    path = SourcePath;
                    break;
                case "a folder merely named copy elsewhere":
                    path = Path.Combine(Path.GetDirectoryName(runRoot)!, "work", "copy", "bracket.SLDPRT");
                    break;
                case "a copy folder two levels down":
                    path = Path.Combine(run, "nested", "copy", "bracket.SLDPRT");
                    break;
                default:
                    path = Path.Combine(run, "bracket.SLDPRT");
                    break;
            }

            world.Document = new PageDocument(path, "Default");

            world.Receive("remodel.plan", "p1", new { });

            if (allowed)
            {
                world.Reply("remodel.planned", "p1");
                return;
            }

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("SourceIsRemodelCopy", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.SourceIsRemodelCopyMessage, error.GetProperty("message").GetString());
            Assert.Empty(world.Pipeline.Calls);
            world.AssertNothingWasCopied();
        }
    }

    [Fact]
    public void TheCopySentenceNamesNoPathAndSendsTheEngineerBackToTheirOwnPart()
    {
        string sentence = RemodelHost.SourceIsRemodelCopyMessage;

        Assert.DoesNotContain("\\", sentence, StringComparison.Ordinal);
        Assert.DoesNotContain(":", sentence, StringComparison.Ordinal);
        Assert.DoesNotContain("remodel.", sentence, StringComparison.Ordinal);
        Assert.Contains("your own part", sentence, StringComparison.Ordinal);
    }

    private static string ChangeLine(int seq, string status) =>
        "{\"seq\":" + seq + ",\"at\":\"2026-09-16T14:22:31.481Z\",\"kind\":\"reorder\","
        + "\"subject\":{\"feature_id\":\"feat:0042\",\"name\":\"Fillet3\","
        + "\"persist_ref\":\"cGVyc2lzdC1yZWY=\"},\"status\":\"" + status + "\"}";


    // ---- T180: held-copy attachment and teardown lifetime --------------------------------

    [Fact]
    public void T180ExactHeldCopyActivationKeepsTheOriginalAttachmentAndStartSession()
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate())
            {
                gate.EnsureStarted();
                world.Receive("remodel.plan", "p1", new { });
                IToolService original = gate.Service!;
                Assert.False(world.Host.RunInProgress);

                world.SwitchTo(gate, world.ExpectedCopyPath.ToUpperInvariant());

                Assert.Same(original, gate.Service);
                Assert.False(((FakeToolService)original).Disposed);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                world.Reply("remodel.started", "s1");
                Assert.Equal(1, world.Pipeline.Count("run"));
            }
        }
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void T180QueuedFollowUsesTheCurrentDocumentForExactCopyPreservation(bool finishesOnOtherDocument)
    {
        using (var world = new RemodelWorld())
        {
            var queued = new Queue<Action>();
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate(scheduler: work => queued.Enqueue(work)))
            {
                gate.EnsureStarted();
                queued.Dequeue()();
                world.Receive("remodel.plan", "p1", new { });
                IToolService original = gate.Service!;
                string other = @"C:\parts\another.SLDPRT";
                world.SwitchTo(gate, finishesOnOtherDocument ? world.ExpectedCopyPath : other);
                world.SwitchTo(gate, finishesOnOtherDocument ? other : world.ExpectedCopyPath);
                Assert.Single(queued);

                queued.Dequeue()();

                Assert.Equal(finishesOnOtherDocument, ((FakeToolService)original).Disposed);
                if (finishesOnOtherDocument)
                {
                    Assert.NotSame(original, gate.Service);
                    Assert.Equal(other, gate.DocumentPath);
                    Assert.Single(world.AllPosted("remodel.plan_lost"));
                }
                else
                {
                    Assert.Same(original, gate.Service);
                    Assert.Empty(world.AllPosted("remodel.plan_lost"));
                }
            }
        }
    }

    [Theory]
    [InlineData("another-copy")]
    [InlineData("another-run")]
    [InlineData("another-attachment")]
    [InlineData("no-attachment")]
    public void T180PreservationRequiresTheExactHeldCopyAndOriginalAttachment(string mismatch)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string copy = world.ExpectedCopyPath;
            string? attachment = world.Attachment;
            Assert.True(world.KeepCopyAttachment(copy, attachment));
            if (mismatch == "another-copy") copy = Path.Combine(Path.GetDirectoryName(copy)!, "other-RMS.SLDPRT");
            if (mismatch == "another-run") copy = Path.Combine(world.RunRoot, "other-remodel", "copy", "bracket-RMS.SLDPRT");
            if (mismatch == "another-attachment") attachment = "swreview-another-attachment";
            if (mismatch == "no-attachment") attachment = null;

            Assert.False(world.KeepCopyAttachment(copy, attachment));
        }
    }

    [Theory]
    [InlineData("unplanned")]
    [InlineData("closed-at-plan")]
    [InlineData("discarded")]
    [InlineData("finished")]
    public void T180APlanWhichNoLongerHoldsASessionCannotPreserveAnAttachment(string state)
    {
        using (var world = new RemodelWorld())
        {
            world.StartValidated = state != "closed-at-plan";
            world.Open();
            if (state != "unplanned") world.Receive("remodel.plan", "p1", new { });
            if (state == "discarded") world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
            if (state == "finished") world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.False(world.KeepCopyAttachment(world.ExpectedCopyPath, world.Attachment));
        }
    }

    [Fact]
    public void T180WithdrawalPrecedesDisposeAndPlanNoticeFollowsTheActualCleanupReport()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate(() =>
            {
                Assert.Null(world.PublishedService);
                Assert.Null(world.AttachmentNow);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
                world.Host.SessionEnded(world.EndOutcome(copyClosed: false));
            }))
            {
                gate.EnsureStarted();
                world.Receive("remodel.plan", "p1", new { });
                world.Lifecycle.Clear();
                world.SwitchTo(gate, @"C:\parts\another.SLDPRT");

                Assert.Equal(new[] { "withdraw", "dispose", "stopped", "publish" }, world.Lifecycle);
                JsonElement notice = Assert.Single(world.AllPosted("remodel.plan_lost"));
                Assert.DoesNotContain("not the copy", notice.GetProperty("message").GetString()!);
                Assert.Contains("Your part was not changed", notice.GetProperty("message").GetString()!);
                int loss = world.IndexOf("remodel.plan_lost");
                Assert.Contains(world.Posted.Take(loss), line => line.Contains("The copy may still be open"));
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                Assert.Equal("SessionLost", world.ErrorClass("s1"));
                Assert.DoesNotContain("not the copy", world.Reply("error", "s1").GetProperty("message").GetString()!);
                Assert.Equal(0, world.Pipeline.Count("run"));
            }
        }
    }

    [Fact]
    public void T180DisposeFailureStillPostsALossWithoutClaimingTheCopyWasUntouched()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate(() => throw new IOException("fictional stop failure")))
            {
                gate.EnsureStarted();
                world.Receive("remodel.plan", "p1", new { });
                world.Lifecycle.Clear();
                world.SwitchTo(gate, @"C:\parts\another.SLDPRT");

                Assert.Equal(new[] { "withdraw", "dispose", "stopped", "publish" }, world.Lifecycle);
                string words = Assert.Single(world.AllPosted("remodel.plan_lost")).GetProperty("message").GetString()!;
                Assert.DoesNotContain("not the copy", words);
                Assert.Contains("Your part was not changed", words);
            }
        }
    }

    [Fact]
    public void T180LateCleanupReportsItsFactsWithoutChangingTheNewestPlanOrRepeatingLoss()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            using (ToolServiceGate gate = world.AttachLifecycleGate())
            {
                gate.EnsureStarted();
                world.Receive("remodel.plan", "p1", new { });
                RemodelRun first = world.Host.LatestRun!;
                world.SwitchTo(gate, @"C:\parts\another.SLDPRT");
                string words = Assert.Single(world.AllPosted("remodel.plan_lost")).GetProperty("message").GetString()!;
                Assert.DoesNotContain("not the copy", words);
                world.Receive("remodel.plan", "p2", new { });
                RemodelRun latest = world.Host.LatestRun!;
                Assert.True(world.KeepCopyAttachment(latest.CopyPath, gate.Attachment));

                world.Host.SessionEnded(world.EndOutcome(copyClosed: false, run: first));

                Assert.Same(latest, world.Host.LatestRun);
                Assert.True(world.KeepCopyAttachment(latest.CopyPath, gate.Attachment));
                Assert.Single(world.AllPosted("remodel.plan_lost"));
                Assert.Contains(world.AllPosted("status"), status => status.GetProperty("message").GetString()!.Contains("The copy may still be open"));
            }
        }
    }

    [Theory]
    [InlineData("saved")]
    [InlineData("truncated")]
    [InlineData("failed")]
    public void T180FinishedRunClosesBeforeReleasingBusyAndKeepsEverySavedArtifact(string state)
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Pipeline.RunState = state;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = _ => world.WriteRunArtifacts();
            string[]? saved = null;
            world.Pipeline.DuringClose = () =>
            {
                Assert.True(world.Host.RunInProgress);
                Assert.Equal(RemodelRunPhase.Running, world.Host.LatestRun!.Phase);
                saved = RemodelWorld.Snapshot(world.ExpectedRunDirectory);
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(1, world.Pipeline.Count("close"));
            Assert.False(world.Pipeline.SessionOpen);
            Assert.False(world.Host.RunInProgress);
            Assert.Equal(saved, RemodelWorld.Snapshot(world.ExpectedRunDirectory));
            world.Pipeline.DuringClose = null;
            world.Receive("remodel.plan", "p2", new { });
            world.Reply("remodel.planned", "p2");
            Assert.Equal(2, world.Pipeline.Count("copy"));
            Assert.Equal(1, world.Pipeline.Count("close"));
        }
    }

    [Theory]
    [InlineData("run")]
    [InlineData("copy")]
    [InlineData("exact")]
    public void T180CleanupOnlyEndsTheKnownRunWhoseCopyItActuallyNames(string match)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            RemodelRun run = world.Host.LatestRun!;
            Assert.True(world.KeepCopyAttachment(run.CopyPath, world.Attachment));
            var outcome = new RemodelSessionEnd(
                RemodelSessionEnd.ReasonToolServiceStopped,
                match == "run" ? Path.Combine(world.RunRoot, "unknown-remodel") : run.RunDirectory,
                match == "copy" ? Path.Combine(run.RunDirectory, "copy", "unknown.SLDPRT") : run.CopyPath,
                verified: true, failedCheck: null, tagRemoved: true, copyClosed: true,
                settingsOutstanding: new string[0], failures: new string[0]);

            world.Host.SessionEnded(outcome);

            Assert.Equal(match != "exact", world.KeepCopyAttachment(run.CopyPath, world.Attachment));
            world.Receive("ready", "r1", new { });
            JsonElement loss = world.Reply("init", "r1").GetProperty("latest_run").GetProperty("plan_lost");
            if (match == "exact")
            {
                Assert.Equal(RemodelHost.PlanLostMessage, loss.GetString());
                Assert.Single(world.AllPosted("remodel.plan_lost"));
                world.Receive("remodel.start", "s1", new { run_dir = run.RunDirectory });
                Assert.Equal("SessionLost", world.ErrorClass("s1"));
                Assert.Equal(0, world.Pipeline.Count("run"));
            }
            else
            {
                Assert.Equal(JsonValueKind.Null, loss.ValueKind);
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
            }
        }
    }

    [Fact]
    public void T180AClosedFinishedRunDoesNotCloseTheNewWaitingPlanWhenDiscarded()
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            RemodelRun first = world.Host.LatestRun!;
            world.Pipeline.DuringRun = _ => world.WriteRunArtifacts();
            world.Receive("remodel.start", "s1", new { run_dir = first.RunDirectory });
            world.Receive("remodel.plan", "p2", new { });
            world.Reply("remodel.planned", "p2");
            RemodelRun next = world.Host.LatestRun!;
            Assert.True(world.Pipeline.SessionOpen);
            int closes = world.Pipeline.Count("close");

            world.Receive("remodel.discard_copy", "d1", new { run_dir = first.RunDirectory });

            world.Reply("ok", "d1");
            Assert.True(world.Pipeline.SessionOpen);
            Assert.Equal(closes, world.Pipeline.Count("close"));
            Assert.True(world.KeepCopyAttachment(next.CopyPath, world.Attachment));
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void T180FinishedCloseFailureIsTruthfulAndOnlyAnAnsweredCloseReleasesSession(bool answered)
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Pipeline.CloseFailure = answered
                ? new RemodelRefusal("CloseIncomplete", "fictional close left settings", true)
                : new RemodelRefusal("BridgeUnavailable", "fictional bridge timeout", true);
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = _ => world.WriteRunArtifacts();

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(1, world.Pipeline.Count("close"));
            Assert.Equal(!answered, world.Pipeline.SessionOpen);
            Assert.False(world.Host.RunInProgress);
            Assert.True(File.Exists(world.ExpectedCopyPath));
            if (!answered)
            {
                // *Changed deliberately 2026-10-21 (owner decision 159A, on review; 004 T223, research R19.9):* the words
                // of a close that was not answered, exactly, where it looked for "did not answer" in them - which they
                // no longer say, since a close that never reached the bridge is not answered either.
                Assert.Contains(
                    world.AllPosted("status"),
                    status => status.GetProperty("message").GetString() == RemodelHost.RunCloseNotAnsweredMessage);
            }
        }
    }

    // ---- owner decision 159A, on the final review: a session a run's unanswered close left on the bridge ------------

    /// <summary>
    /// Owner decision 159A, on the final review, test first (004 T249; research R19.21; its S2): a run whose close was not
    /// answered - its backend gone mid-run, so the close was never sent - leaves its session on the bridge, and since
    /// protocol 1.5 a close names its run, so no other run's close ends it. The next plan's open was refused
    /// <c>run_in_progress</c>, the failed plan's clean-up close named the new run and was refused as another run's, and every
    /// later press did the same, the page saying neither what held the bridge nor the way out. The host closes the session
    /// its finished run may still hold before the next plan copies anything, naming that run.
    /// </summary>
    [Fact]
    public void ARunWhoseCloseWasNotAnsweredIsClosedBeforeTheNextPlanCopiesAnything()
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.DuringRun = _ => world.WriteRunArtifacts();
            world.Pipeline.RunState = "failed";
            world.Pipeline.CloseFailure = new RemodelRefusal(
                "BackendUnavailable", "FICT the review backend is not running, so the close was not sent.", retryable: true);
            world.Receive("remodel.start", "s1", new { run_dir = first });
            Assert.True(world.Pipeline.SessionOpen, "the run's close was not answered, so its session is still on the bridge");
            world.Pipeline.CloseFailure = null;
            int copies = world.Pipeline.Count("copy");

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Equal(new[] { first, first }, world.Pipeline.Closed);
            Assert.Equal(copies + 1, world.Pipeline.Count("copy"));
            Assert.True(world.Pipeline.Calls.LastIndexOf("close") < world.Pipeline.Calls.LastIndexOf("copy"));
            Assert.True(world.Host.LatestRun!.RunDirectory != first);

            // Its session ended, the earlier run sends no close again: discarding its copy deletes the copy alone.
            world.Receive("remodel.discard_copy", "d1", new { run_dir = first });
            world.Reply("ok", "d1");
            Assert.Equal(2, world.Pipeline.Closed.Count(folder => folder == first));
        }
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T249; its S2): a close of that session that is still not answered
    /// refuses the next plan before anything is copied - retryable, in plain words, the close's class kept and its
    /// failure in the log - and pressing again asks the close again, as planning again does for an earlier plan's.
    /// </summary>
    [Fact]
    public void ARunWhoseCloseIsStillNotAnsweredRefusesTheNextPlanRetryableAndCopiesNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.DuringRun = _ => world.WriteRunArtifacts();
            world.Pipeline.RunState = "failed";
            world.Pipeline.CloseFailure = new RemodelRefusal(
                "BackendUnavailable", "FICT the review backend is not running, so the close was not sent.", retryable: true);
            world.Receive("remodel.start", "s1", new { run_dir = first });
            int copies = world.Pipeline.Count("copy");
            int probes = world.Pipeline.Count("probe");

            world.Receive("remodel.plan", "p2", new { });

            JsonElement refused = world.Reply("error", "p2");
            Assert.Equal("BackendUnavailable", refused.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.EarlierRunNotClosedMessage, refused.GetProperty("message").GetString());
            Assert.True(refused.GetProperty("retryable").GetBoolean());
            Assert.Equal(copies, world.Pipeline.Count("copy"));
            Assert.Equal(probes, world.Pipeline.Count("probe"));
            Assert.Equal(new[] { first, first }, world.Pipeline.Closed);
            Assert.True(world.Pipeline.SessionOpen);

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.plan", "p3", new { });

            world.Reply("remodel.planned", "p3");
            Assert.Equal(new[] { first, first, first }, world.Pipeline.Closed);
        }
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T249 - a guard; its S2): a finished run whose close was answered holds
    /// no session, and the next plan sends no close for it.
    /// </summary>
    [Fact]
    public void ARunWhoseCloseWasAnsweredIsNotClosedAgainByTheNextPlan()
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.DuringRun = _ => world.WriteRunArtifacts();
            world.Receive("remodel.start", "s1", new { run_dir = first });

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Equal(new[] { first }, world.Pipeline.Closed);
        }
    }

    // ---- 004 T257: a failed plan's unanswered cleanup keeps its own identity ----------------

    private const string FailedPlanCleanupWords =
        "Closing the copy from the earlier attempt was not confirmed, so no new plan was made. "
        + "Your part was not changed. Wait a moment, then press Remodel a copy again.";

    [Theory]
    [InlineData("before-open")]
    [InlineData("after-open")]
    [InlineData("plan")]
    public void AFailedPlansUnansweredCloseIsRetriedForItsOwnRunBeforeAnotherProbe(string failedAt)
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            if (failedAt == "plan") world.Pipeline.PlanFailure = new IOException("FICT planning failed.");
            else world.Pipeline.CopyFailure = new IOException("FICT opening failed.");
            world.Pipeline.CopyFailureLeavesTheSessionOpen = failedAt == "after-open";
            world.Pipeline.CloseFailure = new IOException("FICT cleanup did not answer.");
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            Assert.Equal("HostError", world.ErrorClass("p1"));
            Assert.Null(world.Host.LatestRun);
            Assert.Empty(world.Host.Runs);
            Assert.Empty(world.Registered);
            Assert.True(Directory.Exists(first));
            world.Pipeline.CopyFailure = null;
            world.Pipeline.PlanFailure = null;
            world.Pipeline.CloseFailure = null;
            int calls = world.Pipeline.Calls.Count;

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Equal(new[] { first, first }, world.Pipeline.Closed);
            Assert.Equal(new[] { "close", "probe", "copy", "plan" }, world.Pipeline.Calls.Skip(calls));
            Assert.NotEqual(first, world.Host.LatestRun!.RunDirectory);
        }
    }

    [Theory]
    [InlineData("BridgeUnavailable")]
    [InlineData("BackendUnavailable")]
    [InlineData("HttpError")]
    [InlineData("BadResponse")]
    [InlineData("InvalidRunDir")]
    [InlineData("InvalidRequest")]
    [InlineData("exception")]
    public void AFailedPlansStillUnansweredCloseRefusesRetryablyAndKeepsItsIdentity(string failureClass)
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Pipeline.PlanFailure = new IOException("FICT planning failed.");
            world.Pipeline.CloseFailure = failureClass == "exception"
                ? new IOException("FICT cleanup could not reach 0FAKEtoken.")
                : new RemodelRefusal(failureClass, "FICT cleanup could not reach 0FAKEtoken.", retryable: false);
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            int calls = world.Pipeline.Calls.Count;
            world.Pipeline.PlanFailure = null;

            world.Receive("remodel.plan", "p2", new { });

            JsonElement error = world.Reply("error", "p2");
            Assert.Equal(failureClass == "exception" ? "BridgeUnavailable" : failureClass,
                error.GetProperty("error_class").GetString());
            Assert.Equal(FailedPlanCleanupWords, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            AssertPlainWords(error.GetProperty("message").GetString()!);
            Assert.Equal(new[] { "close" }, world.Pipeline.Calls.Skip(calls));
            Assert.Equal(new[] { first, first }, world.Pipeline.Closed);
            Assert.True(world.Pipeline.SessionOpen);
            Assert.Single(Directory.GetDirectories(world.RunRoot));
            Assert.Contains(world.Logged, line => line.Contains("FICT cleanup could not reach"));
            Assert.DoesNotContain(world.Logged, line => line.Contains("0FAKEtoken"));

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.plan", "p3", new { });
            world.Reply("remodel.planned", "p3");
            Assert.Equal(new[] { first, first, first }, world.Pipeline.Closed);
        }
    }

    [Theory]
    [InlineData("closed")]
    [InlineData("CloseIncomplete")]
    [InlineData("RunFolderFailed")]
    public void AFailedPlansAnsweredCloseIsNotSentAgain(string answer)
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Pipeline.PlanFailure = new IOException("FICT planning failed.");
            world.Pipeline.CloseFailure = answer == "closed" ? null
                : new RemodelRefusal(answer, "FICT the close answered.", retryable: false);
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.PlanFailure = null;
            world.Pipeline.CloseFailure = null;

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Equal(new[] { first }, world.Pipeline.Closed);
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void AFailedPlansPendingCloseNeverReachesAReplacementAttachment(bool withdrawn)
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Pipeline.PlanFailure = new IOException("FICT planning failed.");
            world.Pipeline.CloseFailure = new IOException("FICT cleanup did not answer.");
            world.Receive("remodel.plan", "p1", new { });
            var replacement = new FakePipeline { HoldsTheBridgeSession = true };
            world.Options.Pipeline = replacement;
            world.Attachment = withdrawn ? null : SecondAttachment;

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Empty(replacement.Closed);
            Assert.Single(world.Pipeline.Closed);
            Assert.True(replacement.SessionOpen);
        }
    }

    [Fact]
    public void AFailedPlansInitialCleanupNeverReachesAReplacementAttachment()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.DuringPlan = () => world.Attachment = SecondAttachment;
            world.Pipeline.PlanFailure = new IOException("FICT planning failed after replacement.");

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("HostError", world.ErrorClass("p1"));
            Assert.Empty(world.Pipeline.Closed);
        }
    }

    [Fact]
    public void AFailedPlansCleanupKeepsTheOldRunWhenTheRunRootMovesAndTheBackendRefusesIt()
    {
        using (var world = new RemodelWorld())
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Open();
            world.Pipeline.PlanFailure = new IOException("FICT planning failed.");
            world.Pipeline.CloseFailure = new RemodelRefusal("BackendUnavailable", "FICT the backend stopped.", true);
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            world.Pipeline.PlanFailure = null;
            world.RunRootSpelling = Path.Combine(world.RunRoot, "later");
            world.Pipeline.CloseFailure = new RemodelRefusal("InvalidRunDir", "FICT the old run is outside the root.", false);

            world.Receive("remodel.plan", "p2", new { });

            JsonElement error = world.Reply("error", "p2");
            Assert.Equal("InvalidRunDir", error.GetProperty("error_class").GetString());
            Assert.Equal(FailedPlanCleanupWords, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(new[] { first, first }, world.Pipeline.Closed);
            Assert.Equal(1, world.Pipeline.Count("probe"));
            Assert.Equal(1, world.Pipeline.Count("copy"));
            world.RunRootSpelling = null;
            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.plan", "p3", new { });
            world.Reply("remodel.planned", "p3");
            Assert.Equal(new[] { first, first, first }, world.Pipeline.Closed);
        }
    }

    /// <summary>
    /// Owner decision 159A, on the final review (004 T249; its S2): the fake bridge keeps protocol 1.5's rule, so the cases
    /// above are the product's: a close names its run, and one naming another run than the session's is refused, the
    /// session left as it was - as the backend answers the bridge's <c>session_mismatch</c>, <c>RunFolderFailed</c>.
    /// </summary>
    [Fact]
    public void TheFakeBridgeRefusesAnotherRunsCloseAndLeavesItsSession()
    {
        var pipeline = new FakePipeline { HoldsTheBridgeSession = true };
        var reporter = new NullReporter();
        pipeline.OpenCopy(new RemodelCopyRequest(Path.Combine(Path.GetTempPath(), "FICT-run-a"), @"C:\FICT\a.SLDPRT", null), reporter);

        RemodelRefusal refused = Assert.Throws<RemodelRefusal>(() => pipeline.CloseCopy(Path.Combine(Path.GetTempPath(), "FICT-run-b")));

        Assert.Equal("RunFolderFailed", refused.ErrorClass);
        Assert.True(pipeline.SessionOpen);
        pipeline.CloseCopy(Path.Combine(Path.GetTempPath(), "FICT-run-a"));
        Assert.False(pipeline.SessionOpen);
    }

    // ---- owner decision 159A (004 T277; research R22): a session left under a run root a restart moves --------------

    /// <summary>
    /// What the Review tab says of a save whose restart waits for a remodel copy's close (004 research R22). *Changed
    /// deliberately 2026-10-27 (owner decision 159A, 004 research R22.11):* it names the earlier folder for runs as the
    /// way out, where saving again only asked the close again.
    /// </summary>
    private const string CleanupPromise =
        "the settings are saved; the backend restarts with them once the copy an earlier remodel left open in SOLIDWORKS "
        + "is closed. That is tried again before the next review, follow-up, remodel run or check; if it cannot be "
        + "closed, save the earlier folder for runs in Settings again.";

    /// <summary>
    /// What a plan or a Start is refused with while that close holds the restart back (004 research R22). *Changed
    /// deliberately 2026-10-27 (owner decision 159A, 004 research R22.10, the review's S2):* it names the ways out.
    /// </summary>
    private const string CleanupHoldsTheRemodelRun =
        "a copy an earlier remodel left open in SOLIDWORKS could not be closed, so the backend has not been restarted "
        + "with the saved settings, and no remodel run starts before then. Make another document active in SOLIDWORKS, "
        + "or save the earlier folder for runs in Settings again, then try again.";

    /// <summary>
    /// Owner decision 159A, test first (004 T277; research R22): the defect R19.29 named, over the review host's real
    /// settings restart. A failed plan's close was not answered, so its session is still on the bridge, under run root A.
    /// Saving run root B restarted the backend under B at once, and B refuses A's folder before the bridge is reached
    /// (`resolve_run_dir`), so every later plan retried a close that could never be sent. Now the close goes first, through
    /// A - the one backend that takes the old run's folder - before A is stopped: while it is not answered B stays saved and
    /// A in force, a plan is refused retryably and copies nothing, and once it is answered the next plan's gate makes the
    /// restart and plans under B - a run of the old run's own name, in the other root, which nothing closes for the old run.
    /// </summary>
    [Fact]
    public void ARunRootChangeWaitsForTheFailedPlansCleanupThroughTheOldBackendThenPlansUnderTheNewRoot()
    {
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            string oldRoot = world.RunRoot;
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Pipeline.PlanFailure = new IOException("FICT planning failed.");
            world.Pipeline.CloseFailure = new RemodelRefusal("BridgeUnavailable", "FICT the bridge did not answer.", retryable: true);
            world.Receive("remodel.plan", "p1", new { });
            string first = world.ExpectedRunDirectory;
            Assert.Equal("HostError", world.ErrorClass("p1"));
            world.Pipeline.PlanFailure = null;

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(CleanupPromise, restart.LastStatus());
            Assert.Equal(restart.NewRoot, restart.Review.Settings.RunRoot);
            Assert.Equal(oldRoot, restart.Review.RunRoot);
            Assert.Empty(restart.Backend.Restarts);
            Assert.True(restart.Review.RestartAhead);
            Assert.Equal(new[] { first, first }, world.Pipeline.Closed);
            Assert.Equal(new[] { oldRoot, oldRoot }, world.Pipeline.RootsClosedUnder);
            Assert.True(world.Pipeline.SessionOpen);

            int probes = world.Pipeline.Count("probe");
            int copies = world.Pipeline.Count("copy");
            world.Receive("remodel.plan", "p2", new { });

            JsonElement refused = world.Reply("error", "p2");
            Assert.Equal("RemodelCleanupPending", refused.GetProperty("error_class").GetString());
            Assert.Equal(CleanupHoldsTheRemodelRun, refused.GetProperty("message").GetString());
            Assert.True(refused.GetProperty("retryable").GetBoolean());
            Assert.Equal(probes, world.Pipeline.Count("probe"));
            Assert.Equal(copies, world.Pipeline.Count("copy"));
            Assert.False(world.Host.RunInProgress);
            Assert.Equal(oldRoot, restart.Review.RunRoot);
            Assert.Empty(restart.Backend.Restarts);
            Assert.Equal(new[] { first, first, first }, world.Pipeline.Closed);
            Assert.True(world.Pipeline.SessionOpen);

            world.Pipeline.CloseFailure = null;
            world.Receive("remodel.plan", "p3", new { });

            world.Reply("remodel.planned", "p3");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Equal(restart.NewRoot, Assert.Single(restart.Backend.Restarts).RunRoot);
            Assert.Equal(new[] { false }, restart.Backend.SessionOpenAtEachRestart);
            Assert.Equal(new[] { first, first, first, first }, world.Pipeline.Closed);
            Assert.Equal(new[] { oldRoot, oldRoot, oldRoot, oldRoot }, world.Pipeline.RootsClosedUnder);
            string second = world.Host.LatestRun!.RunDirectory;
            Assert.Equal(Path.Combine(restart.NewRoot, world.ExpectedRunId), second);
            Assert.True(world.Pipeline.SessionOpen);

            // The run of the same name under B holds the bridge now, and nothing names the old run again: planning
            // again closes the new run's session alone, through B.
            world.Receive("remodel.plan", "p4", new { });

            world.Reply("remodel.planned", "p4");
            Assert.Equal(new[] { first, first, first, first, second }, world.Pipeline.Closed);
            Assert.Equal(restart.NewRoot, world.Pipeline.RootsClosedUnder.Last());
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T277; research R22): each session a run can leave on the bridge - a failed plan's,
    /// a plan waiting for Start (Start on, or Start off with its close at the plan not answered) and a finished run's - is
    /// closed through the backend in force, before a save's restart moves the run root, and the restart is then made at once.
    /// A plan closed so is told lost once, in words of its own; the next plan, under the new run root, closes nothing more.
    /// </summary>
    [Theory]
    [InlineData("failed")]
    [InlineData("waiting")]
    [InlineData("waiting, Start off")]
    [InlineData("finished")]
    public void ALeftoverUnderTheOldRunRootIsClosedThroughTheOldBackendBeforeTheRestartMovesIt(string leftover)
    {
        using (var world = new RemodelWorld { StartValidated = leftover != "waiting, Start off" })
        using (var restart = new RunRootRestart(world))
        {
            string oldRoot = world.RunRoot;
            string first = world.ExpectedRunDirectory;
            LeaveASessionOnTheBridge(world, leftover);
            int closes = world.Pipeline.Closed.Count;

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Equal(restart.NewRoot, Assert.Single(restart.Backend.Restarts).RunRoot);
            Assert.Equal(new[] { false }, restart.Backend.SessionOpenAtEachRestart);
            Assert.Equal(new[] { first }, world.Pipeline.Closed.Skip(closes));
            Assert.Equal(oldRoot, world.Pipeline.RootsClosedUnder.Last());
            Assert.False(world.Pipeline.SessionOpen);
            bool waiting = leftover.StartsWith("waiting", StringComparison.Ordinal);
            if (waiting)
            {
                JsonElement notice = Assert.Single(world.AllPosted("remodel.plan_lost"));
                Assert.Equal(first, notice.GetProperty("run_dir").GetString());
                Assert.Equal(RemodelHost.PlanClosedForRunRootMessage, notice.GetProperty("message").GetString());
                AssertPlainWords(RemodelHost.PlanClosedForRunRootMessage);
            }
            else
            {
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
            }

            if (leftover == "waiting")
            {
                // Start on: a Start naming the plan, and a page that loads again, are told the same words.
                world.Receive("remodel.start", "s2", new { run_dir = first });
                JsonElement lost = world.Reply("error", "s2");
                Assert.Equal("SessionLost", lost.GetProperty("error_class").GetString());
                Assert.Equal(RemodelHost.PlanClosedForRunRootMessage, lost.GetProperty("message").GetString());
                world.Receive("ready", "r2", new { });
                Assert.Equal(
                    RemodelHost.PlanClosedForRunRootMessage,
                    world.Reply("init", "r2").GetProperty("latest_run").GetProperty("plan_lost").GetString());
            }

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Equal(Path.Combine(restart.NewRoot, world.ExpectedRunId), world.Host.LatestRun!.RunDirectory);
            Assert.Equal(new[] { first }, world.Pipeline.Closed.Skip(closes).Where(folder => folder == first));
            Assert.Equal(waiting ? 1 : 0, world.AllPosted("remodel.plan_lost").Length);
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T277; research R22): a close answered with what it left - the routine's own
    /// refusal, or another run's session on the bridge - is an answer, as it is for planning again; the restart is made, and
    /// the next plan, under the new run root, sends no close for the old run.
    /// </summary>
    [Theory]
    [InlineData("CloseIncomplete")]
    [InlineData("RunFolderFailed")]
    public void ARunRootChangesOnceTheOldRunsCloseIsAnsweredWithWhatItLeft(string answer)
    {
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            string first = world.ExpectedRunDirectory;
            LeaveASessionOnTheBridge(world, "failed");
            int closes = world.Pipeline.Closed.Count;
            world.Pipeline.CloseFailure = new RemodelRefusal(answer, "FICT the close answered with what it left.", retryable: false);

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Equal(new[] { first }, world.Pipeline.Closed.Skip(closes));
            world.Pipeline.CloseFailure = null;

            world.Receive("remodel.plan", "p2", new { });

            world.Reply("remodel.planned", "p2");
            Assert.Equal(new[] { first }, world.Pipeline.Closed.Skip(closes));
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T277; research R22): every close that is not an answer - the bridge's silence, a
    /// close that never reached it, and a failure with no class - holds the restart back: the saved run root stays saved,
    /// the one in force stays in force, nothing is stopped or started, the session is left as it was, and the failure is in
    /// the log, masked. *Changed deliberately 2026-10-27 (owner decision 159A, 004 research R22.10, the review's M1):*
    /// the leftover is a parameter, and a waiting plan (Start on and off) and a finished run are rows beside the failed
    /// plan, none of them marked closed or told lost: a run's unanswered close let through survived every case before.
    /// </summary>
    [Theory]
    [InlineData("failed", "BridgeUnavailable")]
    [InlineData("failed", "BackendUnavailable")]
    [InlineData("failed", "HttpError")]
    [InlineData("failed", "BadResponse")]
    [InlineData("failed", "InvalidRunDir")]
    [InlineData("failed", "InvalidRequest")]
    [InlineData("failed", "exception")]
    [InlineData("waiting", "BridgeUnavailable")]
    [InlineData("waiting, Start off", "BridgeUnavailable")]
    [InlineData("finished", "BridgeUnavailable")]
    public void ARunRootChangeWaitsWhileTheOldRunsCloseIsNotAnswered(string leftover, string failureClass)
    {
        using (var world = new RemodelWorld { StartValidated = leftover != "waiting, Start off" })
        using (var restart = new RunRootRestart(world))
        {
            string oldRoot = world.RunRoot;
            LeaveASessionOnTheBridge(world, leftover);
            world.Pipeline.CloseFailure = failureClass == "exception"
                ? new IOException("FICT the close could not reach 0FAKEtoken.")
                : new RemodelRefusal(failureClass, "FICT the close could not reach 0FAKEtoken.", retryable: false);

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(CleanupPromise, restart.LastStatus());
            Assert.Equal(restart.NewRoot, restart.Review.Settings.RunRoot);
            Assert.Equal(oldRoot, restart.Review.RunRoot);
            Assert.Empty(restart.Backend.Restarts);
            Assert.True(world.Pipeline.SessionOpen);
            Assert.Contains(world.Logged, line => line.Contains("FICT the close could not reach"));
            Assert.DoesNotContain(world.Logged, line => line.Contains("0FAKEtoken"));
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            if (leftover != "failed")
            {
                Assert.False(world.Host.LatestRun!.ClosedForRunRoot);
                Assert.False(world.Host.LatestRun!.SessionEnded);
            }
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T277 - a guard and the record of a known defect; research R22): with backend A gone there is
    /// nothing to close the old run through, and the restart is what brings a backend back, so it is not held: B comes into
    /// force. The old run's close is then refused by B before it reaches the bridge, the plan refused retryably and nothing
    /// copied - so no close of the old run can reach the bridge under B, where a run of the same name may later hold it. A
    /// re-attach, whose teardown ends whatever session the old attachment held, is the way on; the next plan, on the new
    /// attachment, sends no close of the old run.
    /// </summary>
    [Fact]
    public void WithTheOldBackendGoneTheRunRootMovesAndTheOldRunsCloseIsRefusedBeforeTheBridge()
    {
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            string first = world.ExpectedRunDirectory;
            LeaveASessionOnTheBridge(world, "failed");
            int closes = world.Pipeline.Closed.Count;
            restart.Backend.Down = true;

            restart.Save("save", restart.NewRoot);

            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Single(restart.Backend.Restarts);
            Assert.Equal(closes, world.Pipeline.Closed.Count);

            world.Receive("remodel.plan", "p2", new { });

            JsonElement refused = world.Reply("error", "p2");
            Assert.Equal("InvalidRunDir", refused.GetProperty("error_class").GetString());
            Assert.Equal(FailedPlanCleanupWords, refused.GetProperty("message").GetString());
            Assert.True(refused.GetProperty("retryable").GetBoolean());
            Assert.Equal(new[] { first }, world.Pipeline.Closed.Skip(closes));
            Assert.DoesNotContain(restart.NewRoot, world.Pipeline.RootsClosedUnder);
            Assert.True(world.Pipeline.SessionOpen);
            Assert.Equal(1, world.Pipeline.Count("copy"));

            var replacement = new FakePipeline
            {
                HoldsTheBridgeSession = true,
                BackendRunRoot = () => restart.Backend.Down ? null : restart.Backend.StartedRoot,
            };
            world.Options.Pipeline = replacement;
            world.Attachment = SecondAttachment;

            world.Receive("remodel.plan", "p3", new { });

            world.Reply("remodel.planned", "p3");
            Assert.Empty(replacement.Closed);
            Assert.Equal(Path.Combine(restart.NewRoot, world.ExpectedRunId), world.Host.LatestRun!.RunDirectory);
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T279 - a guard added with the fix; research R22): a leftover under an earlier run root - left
    /// there when that root's backend had gone, so the change to the run root in force was made without it - is not closed
    /// through the backend in force, which would refuse its folder, and does not hold the next change back for ever: only
    /// what lies under the run root leaving is the restart's to close. It stays T258's, as the known defect says.
    /// </summary>
    [Theory]
    [InlineData("failed")]
    [InlineData("waiting")]
    [InlineData("finished")]
    public void ALeftoverUnderAnEarlierRunRootDoesNotHoldTheNextRunRootChange(string leftover)
    {
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            LeaveASessionOnTheBridge(world, leftover);
            int closes = world.Pipeline.Closed.Count;
            restart.Backend.Down = true;
            restart.Save("first", restart.NewRoot);
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            string third = Path.Combine(world.Root, "third", "runs");

            restart.Save("second", third);

            restart.Reply("settings.saved", "second");
            Assert.Equal(third, restart.Review.RunRoot);
            Assert.Equal(2, restart.Backend.Restarts.Count);
            Assert.Equal(closes, world.Pipeline.Closed.Count);
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T279 - a guard added with the fix; research R22): a run that holds no session - a plan
    /// whose close at the plan was answered, while Start is switched off - is not closed again before the run root moves.
    /// </summary>
    [Fact]
    public void ARunRootChangeSendsNoCloseForAPlanThatHoldsNoSession()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        using (var restart = new RunRootRestart(world))
        {
            world.Pipeline.HoldsTheBridgeSession = true;
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            Assert.True(world.Host.LatestRun!.SessionClosedAtPlan);
            int closes = world.Pipeline.Closed.Count;

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Equal(closes, world.Pipeline.Closed.Count);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T279 - a guard added with the fix; research R22): the closes before the run root moves hold
    /// the tool service, as a plan's do, so no follow of the active document takes the bridge down under them, and let it
    /// go after; with no tool service listening to hold there is no session left to close, and the restart is made.
    /// </summary>
    [Theory]
    [InlineData("held")]
    [InlineData("none listening")]
    public void TheClosesBeforeARunRootChangeHoldTheToolService(string service)
    {
        int holds = 0;
        var heldDuringTheClose = new List<int>();
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            LeaveASessionOnTheBridge(world, "failed");
            int closes = world.Pipeline.Closed.Count;
            world.Hold = () =>
            {
                if (service == "none listening")
                {
                    return null;
                }

                holds++;
                return new Released(() => holds--);
            };
            world.Pipeline.DuringClose = () => heldDuringTheClose.Add(holds);

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Equal(0, holds);
            Assert.Equal(service == "held" ? new[] { 1 } : new int[0], heldDuringTheClose);
            Assert.Equal(service == "held" ? closes + 1 : closes, world.Pipeline.Closed.Count);
        }
    }

    /// <summary>A hold that runs <c>release</c> when it is let go.</summary>
    private sealed class Released : IDisposable
    {
        private readonly Action _release;

        public Released(Action release) => _release = release;

        public void Dispose() => _release();
    }

    /// <summary>
    /// Owner decision 159A (004 T277 - a guard; research R22): a leftover of an attachment that is no longer listening is
    /// not closed through the new one - its session went with the old - and does not hold the restart back. *Changed
    /// deliberately 2026-10-27 (owner decision 159A, 004 research R22.10, the review's S1):* a waiting plan and a finished
    /// run are rows beside the failed plan, so a run read against its own attachment rather than the one listening now
    /// fails here.
    /// </summary>
    [Theory]
    [InlineData("failed")]
    [InlineData("waiting")]
    [InlineData("finished")]
    public void ARunRootChangeSendsNoCloseToAReplacementAttachment(string leftover)
    {
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            LeaveASessionOnTheBridge(world, leftover);
            int closes = world.Pipeline.Closed.Count;
            var replacement = new FakePipeline
            {
                HoldsTheBridgeSession = true,
                BackendRunRoot = () => restart.Backend.Down ? null : restart.Backend.StartedRoot,
            };
            world.Options.Pipeline = replacement;
            world.Attachment = SecondAttachment;

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Empty(replacement.Closed);
            Assert.Equal(closes, world.Pipeline.Closed.Count);
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T281; research R22.10, Codex's review): the real bridge tells the host a
    /// session ended (<c>RemodelHost.SessionEnded</c>, from <c>remodel.close</c>'s end-of-session routine) before the
    /// close's answer comes back. A plan closed before the run root moves was then marked ended and told lost from inside
    /// the close, in the re-attach words - SOLIDWORKS switching documents, which did not happen - and the run-root words
    /// after it could not take the one notice back. Now the plan is told lost once, in the run-root words, whether the
    /// bridge tells the end inside the close ("inside") or after a close whose answer never came, its wait abandoned
    /// ("late", R22.3): a wait given up on still ends the session when the bridge gets to it. A guard added with the fix
    /// (T282): a teardown's end after a close not answered ("teardown") is no close's, and keeps the re-attach words.
    /// </summary>
    [Theory]
    [InlineData("waiting", "inside")]
    [InlineData("waiting, Start off", "inside")]
    [InlineData("waiting", "late")]
    [InlineData("waiting, Start off", "late")]
    [InlineData("waiting", "teardown")]
    public void APlanClosedBeforeTheRunRootMovesIsToldLostOnceInItsOwnWordsWhenTheBridgeTellsTheEnd(
        string leftover, string when)
    {
        using (var world = new RemodelWorld { StartValidated = leftover != "waiting, Start off" })
        using (var restart = new RunRootRestart(world))
        {
            string first = world.ExpectedRunDirectory;
            LeaveASessionOnTheBridge(world, leftover);
            RemodelRun run = world.Host.LatestRun!;
            string words = when == "teardown" ? RemodelHost.PlanLostMessage : RemodelHost.PlanClosedForRunRootMessage;
            var ended = new RemodelSessionEnd(
                when == "teardown" ? RemodelSessionEnd.ReasonToolServiceStopped : RemodelSessionEnd.ReasonClose,
                run.RunDirectory, run.CopyPath,
                verified: true, failedCheck: null, tagRemoved: true, copyClosed: true,
                settingsOutstanding: new string[0], failures: new string[0]);
            if (when == "inside")
            {
                world.Pipeline.DuringClose = () => world.Host.SessionEnded(ended);
            }
            else
            {
                world.Pipeline.CloseFailure = new RemodelRefusal("BridgeUnavailable", "FICT the bridge did not answer.", retryable: true);
            }

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            if (when == "inside")
            {
                Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            }
            else
            {
                Assert.Equal(CleanupPromise, restart.LastStatus());
                Assert.Empty(world.AllPosted("remodel.plan_lost"));
                world.Host.SessionEnded(ended);
            }

            JsonElement notice = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(first, notice.GetProperty("run_dir").GetString());
            Assert.Equal(words, notice.GetProperty("message").GetString());
            world.Receive("ready", "r2", new { });
            Assert.Equal(words, world.Reply("init", "r2").GetProperty("latest_run").GetProperty("plan_lost").GetString());
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T281; research R22.10, the review's S3): Discard deletes the copy folder even
    /// when its close is not answered, and marks the copy discarded, so the run can still hold its session on the bridge.
    /// Skipping a discarded run left that session there for ever once the run root moved; now the restart closes it through
    /// the backend in force first, like any run that holds its session. Nobody is told a plan was lost: a discarded copy is
    /// no plan on screen.
    /// </summary>
    [Theory]
    [InlineData("waiting")]
    [InlineData("finished")]
    public void ARunRootChangeClosesADiscardedRunWhoseDiscardCloseWasNotAnswered(string leftover)
    {
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            string first = world.ExpectedRunDirectory;
            LeaveASessionOnTheBridge(world, leftover);
            world.Pipeline.CloseFailure = new RemodelRefusal("BridgeUnavailable", "FICT the bridge did not answer.", retryable: true);
            world.Receive("remodel.discard_copy", "d1", new { run_dir = first });
            world.Reply("ok", "d1");
            Assert.True(world.Host.LatestRun!.CopyDiscarded);
            Assert.True(world.Pipeline.SessionOpen);
            world.Pipeline.CloseFailure = null;
            int closes = world.Pipeline.Closed.Count;

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Equal(new[] { false }, restart.Backend.SessionOpenAtEachRestart);
            Assert.Equal(new[] { first }, world.Pipeline.Closed.Skip(closes));
            Assert.False(world.Pipeline.SessionOpen);
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T281 - a guard; research R22.10, the review's S3): a discarded run whose close was
    /// answered holds no session. When the bridge told the host so, nothing more is sent; when it did not, the one close
    /// the restart sends finds no session and is answered with no SOLIDWORKS call. Either way the restart is made and
    /// nobody is told a plan was lost.
    /// </summary>
    [Theory]
    [InlineData("told")]
    [InlineData("not told")]
    public void ARunRootChangeIsHarmlessForADiscardedRunWhoseDiscardCloseWasAnswered(string bridge)
    {
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            string first = world.ExpectedRunDirectory;
            LeaveASessionOnTheBridge(world, "waiting");
            RemodelRun run = world.Host.LatestRun!;
            if (bridge == "told")
            {
                world.Pipeline.DuringClose = () => world.Host.SessionEnded(new RemodelSessionEnd(
                    RemodelSessionEnd.ReasonClose, run.RunDirectory, run.CopyPath,
                    verified: true, failedCheck: null, tagRemoved: true, copyClosed: true,
                    settingsOutstanding: new string[0], failures: new string[0]));
            }

            world.Receive("remodel.discard_copy", "d1", new { run_dir = first });
            world.Reply("ok", "d1");
            world.Pipeline.DuringClose = null;
            Assert.False(world.Pipeline.SessionOpen);
            int closes = world.Pipeline.Closed.Count;
            int notices = world.AllPosted("remodel.plan_lost").Length;

            restart.Save("save", restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(restart.NewRoot, restart.Review.RunRoot);
            Assert.Equal(new[] { false }, restart.Backend.SessionOpenAtEachRestart);
            Assert.InRange(world.Pipeline.Closed.Count - closes, 0, bridge == "told" ? 0 : 1);
            Assert.Equal(notices, world.AllPosted("remodel.plan_lost").Length);
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T277 - guards; research R22): what holds a restart back is asked first, and the close only
    /// once nothing does - a turn running, or a remodel run in progress, holds it with no close sent - and a restart that
    /// keeps the run root sends none at all, the session under it left for planning again, as before.
    /// </summary>
    [Theory]
    [InlineData("a turn")]
    [InlineData("a remodel run")]
    [InlineData("the run root kept")]
    public void ARestartClosesNothingWhileSomethingHoldsItOrWhenTheRunRootStays(string what)
    {
        var kept = new List<Action>();
        using (var world = new RemodelWorld())
        using (var restart = new RunRootRestart(world))
        {
            string oldRoot = world.RunRoot;
            if (what == "a remodel run")
            {
                world.Pipeline.HoldsTheBridgeSession = true;
                world.Receive("remodel.plan", "p1", new { });
                world.Options.Schedule = kept.Add;
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                Assert.True(world.Host.RunInProgress);
            }
            else
            {
                LeaveASessionOnTheBridge(world, "failed");
            }

            if (what == "a turn")
            {
                // A turn that starts during the save, after its own check: one running before it refuses the save.
                restart.Review.TrackSession("chat-1", Path.Combine(oldRoot, "20261027-101500-chat-1"));
                restart.Backend.DuringModelList = () => restart.Backend.TurnRunning = true;
            }

            int closes = world.Pipeline.Closed.Count;

            restart.Save("save", what == "the run root kept" ? null : restart.NewRoot);

            restart.Reply("settings.saved", "save");
            Assert.Equal(closes, world.Pipeline.Closed.Count);
            if (what == "the run root kept")
            {
                Assert.Single(restart.Backend.Restarts);
                Assert.Equal(oldRoot, restart.Review.RunRoot);
                Assert.True(world.Pipeline.SessionOpen);
            }
            else
            {
                Assert.Empty(restart.Backend.Restarts);
                Assert.Equal(oldRoot, restart.Review.RunRoot);
                Assert.NotEqual(CleanupPromise, restart.LastStatus());
            }
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T287; research R22.12): the Remodel host's reading of whether it still holds a
    /// session under a run root - what its cleanup would close, read without closing it or asking anything: a failed plan's
    /// whose close was not answered, or a run that holds its session, on the attachment listening now, under that run
    /// root. The close's late end, a re-attach, or another run root is none; and a run root changed only so a review host
    /// can read it, never a close sent.
    /// </summary>
    [Theory]
    [InlineData("a waiting plan", true)]
    [InlineData("a failed plan", true)]
    [InlineData("a finished run", true)]
    [InlineData("ended late", false)]
    [InlineData("re-attached", false)]
    [InlineData("another run root", false)]
    public void TheRemodelHostSaysWhetherASessionIsLeftUnderARunRoot(string state, bool expected)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            LeaveASessionOnTheBridge(world, state == "a failed plan" ? "failed" : state == "a finished run" ? "finished" : "waiting");
            string runRoot = world.RunRoot;
            switch (state)
            {
                case "ended late":
                    RemodelRun run = world.Host.LatestRun!;
                    world.Host.SessionEnded(new RemodelSessionEnd(
                        RemodelSessionEnd.ReasonClose, run.RunDirectory, run.CopyPath,
                        verified: true, failedCheck: null, tagRemoved: true, copyClosed: true,
                        settingsOutstanding: new string[0], failures: new string[0]));
                    break;
                case "re-attached":
                    world.Attachment = SecondAttachment;
                    break;
                case "another run root":
                    runRoot = Path.Combine(world.Root, "another", "runs");
                    break;
            }

            int closes = world.Pipeline.Closed.Count;

            Assert.Equal(expected, world.Host.HoldsASessionLeftUnder(runRoot));
            Assert.Equal(closes, world.Pipeline.Closed.Count);
        }
    }

    /// <summary>
    /// Leaves one session of the world's first run on its fake bridge, under the world's run root, whose close is not
    /// answered, then lets later closes be answered: a failed plan's, a plan waiting for Start (Start on keeps it; Start
    /// off, with its close at the plan not answered), or a finished run's (its close at the run's end not sent).
    /// </summary>
    private static void LeaveASessionOnTheBridge(RemodelWorld world, string leftover)
    {
        world.Pipeline.HoldsTheBridgeSession = true;
        switch (leftover)
        {
            case "failed":
                world.Pipeline.PlanFailure = new IOException("FICT planning failed.");
                world.Pipeline.CloseFailure = new RemodelRefusal("BridgeUnavailable", "FICT the bridge did not answer.", retryable: true);
                world.Receive("remodel.plan", "p1", new { });
                Assert.Equal("HostError", world.ErrorClass("p1"));
                world.Pipeline.PlanFailure = null;
                break;

            case "waiting":
                world.Receive("remodel.plan", "p1", new { });
                world.Reply("remodel.planned", "p1");
                break;

            case "waiting, Start off":
                world.Pipeline.CloseFailure = new RemodelRefusal("BridgeUnavailable", "FICT the bridge did not answer.", retryable: true);
                world.Receive("remodel.plan", "p1", new { });
                world.Reply("remodel.planned", "p1");
                Assert.False(world.Host.LatestRun!.SessionClosedAtPlan);
                break;

            case "finished":
                world.Receive("remodel.plan", "p1", new { });
                world.Pipeline.DuringRun = _ => world.WriteRunArtifacts();
                world.Pipeline.RunState = "failed";
                world.Pipeline.CloseFailure = new RemodelRefusal(
                    "BackendUnavailable", "FICT the review backend is not running, so the close was not sent.", retryable: true);
                world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                Assert.Equal(RemodelRunPhase.Finished, world.Host.LatestRun!.Phase);
                break;

            default:
                throw new ArgumentOutOfRangeException(nameof(leftover), leftover, null);
        }

        Assert.True(world.Pipeline.SessionOpen);
        world.Pipeline.CloseFailure = null;
    }

    // ---- owner decision 155A: a run's ending reaches the page once the host is free ------------

    /// <summary>Whether a message is a `status` that ends the page's running state: `ready` and `error` do (`remodel.js`, `showStatus`).</summary>
    private static bool EndsTheRunOnThePage(JsonElement message)
    {
        if (message.GetProperty("type").GetString() != "status")
        {
            return false;
        }

        string? stage = message.GetProperty("payload").GetProperty("stage").GetString();
        return stage == "ready" || stage == "error";
    }

    /// <summary>
    /// The endings of a run that tell the page something in a stage that ends its running state: a run the
    /// executor refused by name, one that failed with no named refusal, a pipeline that posted its own error
    /// before it answered, a close that left something (T167's words, told through
    /// <c>ToolServiceOptions.RemodelSessionEnded</c> while the close is answered), and a run that saved.
    /// </summary>
    public static IEnumerable<object[]> RunEndings => new[]
    {
        new object[] { "refused" },
        new object[] { "failed" },
        new object[] { "pipeline" },
        new object[] { "left" },
        new object[] { "saved" },
    };

    /// <summary>The words T167 posts for a close that left one setting changed, as <see cref="RunEndings"/>' "left" has it.</summary>
    private static readonly string LeftBehind =
        RemodelHost.SessionEndedMessage(new[] { RemodelSystemToggles.InputDimValOnCreate }, false, copyClosed: true)!;

    /// <summary>
    /// Owner decision 155A, test first (004 T195; feature 011 research R12.9 item 4): the page offers Open copy
    /// and Discard copy again on the run's terminal status, and that status reached it - posted by the
    /// pipeline, by `Execute` as it caught the failure, or as T167's words while the close was answered -
    /// before `Execute` had closed the run's session and freed the host, so a press in that window was refused
    /// `RunInProgress`. Every status that ends the page's running state is now posted once the host is free,
    /// in the order the ending made them, the run's own last word last. *Changed deliberately 2026-10-21 (owner
    /// decision 159A, 004 research R19):* a failure with no named refusal, and the pipeline's own error, are told in
    /// the tab's own words, where each carried its own sentence, which can name a path; the order and the moment
    /// pinned here are as they were.
    /// </summary>
    [Theory]
    [MemberData(nameof(RunEndings))]
    public void EveryStatusThatEndsTheRunOnThePageIsPostedOnceTheHostIsFree(string ending)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            switch (ending)
            {
                case "refused":
                    world.Pipeline.RunFailure = new RemodelRefusal(
                        "RunNotPlanned", "FICT this run was not planned, so nothing was started.", retryable: false);
                    break;
                case "failed":
                    world.Pipeline.RunFailure = new IOException("FICT the backend stopped answering.");
                    break;
                case "pipeline":
                    world.Pipeline.RunState = "failed";
                    world.Pipeline.DuringRun = reporter => reporter.Status("error", "FICT the run failed in the backend.");
                    break;
                case "left":
                    world.Pipeline.DuringClose = () => world.Host.SessionEnded(
                        new[] { RemodelSystemToggles.InputDimValOnCreate }, false, copyClosed: true);
                    break;
            }

            var ended = new List<(string Words, bool Busy)>();
            world.WhenPosted = root =>
            {
                if (EndsTheRunOnThePage(root))
                {
                    ended.Add((root.GetProperty("payload").GetProperty("message").GetString()!, world.Host.RunInProgress));
                }
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Reply("remodel.started", "s1");
            Assert.Equal(1, world.Pipeline.Count("close"));
            string[] expected = ending switch
            {
                "refused" => new[] { "FICT this run was not planned, so nothing was started.", "The run ended without saving the copy. The report says why." },
                "failed" => new[] { RemodelHost.UnexpectedFailureMessage, "The run ended without saving the copy. The report says why." },
                "pipeline" => new[] { RemodelHost.BackendFailedMessage, "The run ended without saving the copy. The report says why." },
                "left" => new[] { LeftBehind, "The run ended 'saved'. Open the report for the change list, the grade and the geometry comparison." },
                _ => new[] { "The run ended 'saved'. Open the report for the change list, the grade and the geometry comparison." },
            };
            Assert.Equal(expected, ended.Select(status => status.Words).ToArray());
            Assert.All(ended, status => Assert.False(status.Busy, "a status that ends the run on the page was posted while the run held the host: " + status.Words));
        }
    }

    /// <summary>
    /// Owner decision 155A (004 T195): a refusal the executor raised still reaches the page with its class, as
    /// an unsolicited `error`, and between the run line's word on it and the run's last word - after the host
    /// is free, as they are.
    /// </summary>
    [Fact]
    public void TheExecutorsRefusalIsToldAfterTheHostIsFreeBetweenItsStatusAndTheRunsLastWord()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.RunFailure = new RemodelRefusal("RunNotPlanned", "FICT this run was not planned.", retryable: false);
            int closedAt = -1;
            world.Pipeline.DuringClose = () => closedAt = world.Posted.Count;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement refusal = Assert.Single(world.AllPosted("error"));
            Assert.Equal("RunNotPlanned", refusal.GetProperty("error_class").GetString());
            Assert.Equal("FICT this run was not planned.", refusal.GetProperty("message").GetString());

            // After the close: the run line's word on the refusal, the refusal, and the run's last word.
            Assert.Equal(world.Posted.Count - 3, closedAt);
            Assert.Equal(new[] { "status", "error", "status" }, world.TypesPostedSince(closedAt));
        }
    }

    /// <summary>
    /// Owner decision 155A, test first (004 T195): the press R12.9 item 4 describes - Open copy or Discard copy
    /// pressed the moment a failed run's terminal status offers it - is answered, not refused
    /// `RunInProgress`, since the status now reaches the page once the host is free.
    /// </summary>
    [Theory]
    [InlineData("remodel.open_copy")]
    [InlineData("remodel.discard_copy")]
    public void ACopyActionPressedAsSoonAsAFailedRunsEndIsOfferedIsAnswered(string press)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.RunFailure = new RemodelRefusal("RunNotPlanned", "FICT this run was not planned.", retryable: false);
            bool pressed = false;
            world.WhenPosted = root =>
            {
                if (!pressed && EndsTheRunOnThePage(root))
                {
                    pressed = true;
                    world.Receive(press, "c1", new { run_dir = world.ExpectedRunDirectory });
                }
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.True(pressed);
            world.Reply("ok", "c1");
        }
    }

    /// <summary>
    /// Owner decision 155A, test first (004 T195): the stop when the copy is gone is told as the engineer's own
    /// Stop is told - in a stage the page shows in its run line while the run goes on (`applying`) - and not in
    /// one that ends the page's running state, which it was: the page then offered Open copy and Discard copy,
    /// and disabled Stop, while the run was still finishing the change in flight and closing. The run's own
    /// last word, once the host is free, is the one status that ends it.
    /// </summary>
    [Fact]
    public void TheStopWhenTheCopyIsGoneLeavesThePageRunningUntilTheRunEnds()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                File.Delete(world.ExpectedCopyPath);
                world.Document = null;
                world.Host.DocumentChanged();
            };
            var ended = new List<bool>();
            world.WhenPosted = root =>
            {
                if (EndsTheRunOnThePage(root))
                {
                    ended.Add(world.Host.RunInProgress);
                }
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement gone = Assert.Single(
                world.AllPosted("status"),
                status => status.GetProperty("message").GetString() == RemodelHost.CopyGoneMessage);
            Assert.Equal("applying", gone.GetProperty("stage").GetString());
            Assert.Equal(new[] { false }, ended);
        }
    }

    /// <summary>
    /// Owner decision 155A (004 T195): `init` and a run's ending are told in one order. An `init` answered
    /// on the page's thread as the run ends on its own reads that the run is in flight and is posted before the
    /// host is freed and the ending told, or reads that it is not: it is never told after the ending that the
    /// run is in flight, which would leave a page loaded again showing a run that has ended, with Stop the
    /// only button on offer. Here the `init` is held inside its post, after it has read the run in flight, until
    /// the run's close has begun, and a moment more.
    /// </summary>
    [Fact]
    public void AnInitAnsweredAsTheRunEndsIsNeverToldAfterTheEndingThatTheRunIsInFlight()
    {
        using (var world = new RemodelWorld())
        using (var entered = new ManualResetEventSlim())
        using (var closing = new ManualResetEventSlim())
        {
            int testThread = Environment.CurrentManagedThreadId;
            world.Channel = new PausingChannel(world.Posted, json =>
            {
                if (Environment.CurrentManagedThreadId != testThread && json.Contains("\"type\":\"init\""))
                {
                    entered.Set();
                    closing.Wait(TimeSpan.FromSeconds(10));
                    Thread.Sleep(200);
                }
            });
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            var init = new Thread(() => world.Receive("ready", "r9", new { })) { IsBackground = true, Name = "fict-page-thread" };
            world.Pipeline.DuringRun = reporter =>
            {
                init.Start();
                Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "the init was never posted");
            };
            world.Pipeline.DuringClose = () => closing.Set();

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.True(init.Join(TimeSpan.FromSeconds(10)), "the init never finished");

            List<JsonElement> posted;
            lock (world.Posted)
            {
                posted = world.Posted.Select(json => JsonDocument.Parse(json).RootElement.Clone()).ToList();
            }

            int initAt = posted.FindIndex(message => message.GetProperty("type").GetString() == "init");
            int startedAt = posted.FindIndex(message => message.GetProperty("type").GetString() == "remodel.started");
            int endedAt = posted.FindIndex(startedAt + 1, EndsTheRunOnThePage);
            Assert.True(initAt >= 0 && startedAt >= 0 && endedAt > startedAt);
            bool running = posted[initAt].GetProperty("payload").GetProperty("latest_run").GetProperty("running").GetBoolean();
            Assert.True(
                !running || initAt < endedAt,
                "the page was told the run is in flight after it was told the run had ended");
        }
    }

    /// <summary>
    /// Owner decision 155A's review (004 T202): `SendInit` reads the active document before it takes the
    /// ending's lock. The add-in reads it on SOLIDWORKS' application thread and waits for the answer
    /// (`SwReviewAddIn.CurrentDocument`), and that thread takes the lock when a session's ending is told
    /// during a run (`PostWhatWasLeft`); read under the lock, a page's `init` would hold the lock and wait on
    /// the thread waiting for it, and SOLIDWORKS would hang. Here SOLIDWORKS' thread, played by a thread of
    /// its own, is told a session ended once the page's `init` has asked it for the active document, and the
    /// `init` must finish within a bound, so a regression fails rather than hangs.
    /// </summary>
    [Fact]
    public void AnInitNeverWaitsOnSolidworksThreadWhileItHoldsTheEndingsLock()
    {
        using (var world = new RemodelWorld())
        using (var app = new FakeAppThread())
        {
            var gate = new ManualResetEventSlim();
            var solidworks = (IAppThreadInvoker)app;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            PageDocument? active = world.Document;

            // As the add-in reads it: on SOLIDWORKS' thread, waited for - here within a bound, so a thread
            // that never answers ends the wait rather than the test run.
            world.Options.CurrentDocument = () =>
            {
                PageDocument? read = null;
                var done = new ManualResetEventSlim();
                solidworks.Post(() =>
                {
                    read = active;
                    done.Set();
                });
                return done.Wait(TimeSpan.FromSeconds(15)) ? read : null;
            };

            bool asked = false;
            bool finished = false;
            world.Pipeline.DuringRun = reporter =>
            {
                // SOLIDWORKS' thread is busy until the gate opens, then a session's ending is told on it, as
                // the tool service tells one during a run.
                solidworks.Post(() =>
                {
                    gate.Wait(TimeSpan.FromSeconds(15));
                    world.Host.SessionEnded(new[] { RemodelSystemToggles.InputDimValOnCreate }, false, copyClosed: true);
                });
                int posted = app.Posted;
                var page = new Thread(() => world.Receive("ready", "r9", new { })) { IsBackground = true, Name = "fict-page-thread" };
                page.Start();

                // The page's init has asked SOLIDWORKS' thread for the active document; then it is let go.
                asked = SpinWait.SpinUntil(() => app.Posted > posted, TimeSpan.FromSeconds(10));
                gate.Set();
                finished = page.Join(TimeSpan.FromSeconds(5));
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.True(asked, "the page's init never asked SOLIDWORKS' thread for the active document");
            Assert.True(finished, "the page's init and SOLIDWORKS' application thread waited on each other");
            Assert.True(world.Reply("init", "r9").GetProperty("latest_run").GetProperty("running").GetBoolean());
            Assert.Single(world.AllPosted("status"), status => status.GetProperty("message").GetString() == LeftBehind);
        }
    }

    /// <summary>
    /// Owner decision 155A's review (004 T202): what a run's ending held is told once - at that run's end -
    /// and never again at a later run's. Two runs in one host, the first refused by its executor: its words
    /// reach the page once, in the run line and in the refusal.
    /// </summary>
    [Fact]
    public void WhatARunsEndingHeldIsToldOnceAndNotAgainAtTheNextRunsEnd()
    {
        using (var world = new RemodelWorld())
        {
            const string refused = "FICT the first run was not planned, so nothing was started.";
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.RunFailure = new RemodelRefusal("RunNotPlanned", refused, retryable: false);
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            world.Pipeline.RunFailure = null;
            world.Receive("remodel.plan", "p2", new { });
            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            Assert.NotEqual(world.ExpectedRunDirectory, second);
            world.Receive("remodel.start", "s2", new { run_dir = second });

            world.Reply("remodel.started", "s2");
            Assert.Single(world.AllPosted("status"), status => status.GetProperty("message").GetString() == refused);
            Assert.Single(world.AllPosted("error"), error => error.GetProperty("message").GetString() == refused);
        }
    }

    /// <summary>
    /// Owner decision 155A's review (004 T202): only the stages that end the page's running state wait for the
    /// run's end. `applying`, `verifying` and `saving` reach the page as the pipeline posts them, while the run
    /// holds the host and before the progress reported after them; held, the run line would stand still for the
    /// whole of a run that can take twenty minutes.
    /// </summary>
    [Fact]
    public void TheRunsOtherStagesReachThePageAsTheyArePostedWhileTheRunHoldsTheHost()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            var stages = new List<(string Stage, bool Busy)>();
            world.WhenPosted = root =>
            {
                if (root.GetProperty("type").GetString() == "status")
                {
                    stages.Add((root.GetProperty("payload").GetProperty("stage").GetString()!, world.Host.RunInProgress));
                }
            };
            world.Pipeline.DuringRun = reporter =>
            {
                reporter.Status("applying", "Applying the plan to the copy...");
                reporter.Status("verifying", "Verifying the copy against the baseline...");
                reporter.Status("saving", "Saving the copy...");
                reporter.Progress(3, 3, 3, "rename", "Fillet3");
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            foreach (string stage in new[] { "applying", "verifying", "saving" })
            {
                Assert.Contains((stage, true), stages);
            }

            int saving = world.Posted.FindIndex(json => json.Contains("\"stage\":\"saving\""));
            Assert.True(saving >= 0 && saving < world.IndexOf("remodel.progress"), "the run's stages were held past its progress");
        }
    }

    // ---- owner decision 159A: a Stop and the run's end, decided under one lock ---------------------

    /// <summary>What the host tells the page as the engineer's Stop reaches a run.</summary>
    private const string StoppingWords = RemodelHost.StoppingMessage;

    /// <summary>
    /// Owner decision 159A, test first (004 T204; research R18.7 item 4): every `remodel.stop` is answered once - at the end
    /// of the run it reached, with that run's count, or at once when no run is in flight. Stop stays pressable until the run
    /// ends, so it can be pressed twice; the second press replaced the first's id, and the first was never answered. Neither
    /// outlives the run: the next run, which no one stops, ends answering no Stop.
    /// </summary>
    [Fact]
    public void EveryStopThatReachesARunIsAnsweredOnceAtItsEndAndNotAtTheNextRunsEnd()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                world.Receive("remodel.stop", "x1", new { });
                world.Receive("remodel.stop", "x2", new { });
                world.Pipeline.ChangesApplied = 2;
                world.Pipeline.RunState = "truncated";
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal(2, world.Reply("remodel.stopped", "x1").GetProperty("changes_applied").GetInt32());
            Assert.Equal(2, world.Reply("remodel.stopped", "x2").GetProperty("changes_applied").GetInt32());
            Assert.Equal(2, world.AllPosted("remodel.stopped").Length);

            world.Pipeline.DuringRun = null;
            world.Pipeline.RunState = "saved";
            world.Receive("remodel.plan", "p2", new { });
            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            int before = world.Posted.Count;
            world.Receive("remodel.start", "s2", new { run_dir = second });

            world.Reply("remodel.started", "s2");
            Assert.DoesNotContain("remodel.stopped", world.TypesPostedSince(before));
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T204; research R18.7 item 4): a Stop and the end of its run are decided under
    /// the one lock that frees the host, so a Stop either reaches the run - its word told before the run's end, its id
    /// answered at that end - or finds no run in flight and is answered at once, storing nothing. Here the Stop's word is
    /// held in its post, on the page's thread, while the run reaches its end on a thread of its own: the run's end waits for
    /// it. Read and stored outside that lock, the Stop's "Stopping" was told after the run's last word, as the line the
    /// page ends on, of a run that had ended; and a Stop that read the run just before the host was freed, and stored its id
    /// just after the end had taken the ids, left its id for the next run's end to answer.
    /// </summary>
    [Fact]
    public void AStopTheRunsEndMeetsIsToldBeforeThatEndAndAnsweredAtIt()
    {
        using (var world = new RemodelWorld())
        {
            (List<JsonElement> posted, bool closed) = AStopsWordHeldAsTheRunEnds(
                world, StoppingWords, () => world.Receive("remodel.stop", "x1", new { }));

            Assert.True(closed, "the run never reached its close while the Stop's word was held");
            int started = posted.FindIndex(message => message.GetProperty("type").GetString() == "remodel.started");
            int stopping = posted.FindIndex(message => message.GetProperty("type").GetString() == "status"
                && message.GetProperty("payload").GetProperty("message").GetString() == StoppingWords);
            int ended = posted.FindIndex(started + 1, EndsTheRunOnThePage);
            int answered = posted.FindIndex(message => message.GetProperty("type").GetString() == "remodel.stopped");
            Assert.True(started >= 0 && stopping > started && ended > stopping, "the Stop's word was told after the run's end");
            Assert.True(answered > ended, "the Stop was answered before the run's last word");
            JsonElement stopped = Assert.Single(posted, message => message.GetProperty("type").GetString() == "remodel.stopped");
            Assert.Equal("x1", stopped.GetProperty("id").GetString());
            Assert.Equal(1, stopped.GetProperty("payload").GetProperty("changes_applied").GetInt32());
        }
    }

    /// <summary>
    /// Owner decision 159A, test first (004 T204): the stop when the copy is gone is decided under the same lock, so its word
    /// is told before the run's end or not at all. Here the copy goes away mid-run and the stop's word is held in its post, on
    /// SOLIDWORKS' thread, while the run reaches its end on a thread of its own: the run's end waits for it. Decided outside
    /// the lock, "the run is stopping" was told after the run's last word.
    /// </summary>
    [Fact]
    public void TheStopWhenTheCopyIsGoneThatTheRunsEndMeetsIsToldBeforeThatEnd()
    {
        using (var world = new RemodelWorld())
        {
            (List<JsonElement> posted, bool closed) = AStopsWordHeldAsTheRunEnds(world, RemodelHost.CopyGoneMessage, () =>
            {
                File.Delete(world.ExpectedCopyPath);
                world.Document = null;
                world.Host.DocumentChanged();
            });

            Assert.True(closed, "the run never reached its close while the stop's word was held");
            int started = posted.FindIndex(message => message.GetProperty("type").GetString() == "remodel.started");
            int gone = posted.FindIndex(message => message.GetProperty("type").GetString() == "status"
                && message.GetProperty("payload").GetProperty("message").GetString() == RemodelHost.CopyGoneMessage);
            int ended = posted.FindIndex(started + 1, EndsTheRunOnThePage);
            Assert.True(started >= 0 && gone > started && ended > gone, "the copy-gone stop was told after the run's end");
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T204): a Stop that arrives once its run has ended - pressed the moment the run's last word
    /// reaches the page - is answered at once, as one with no run in flight is, and stores nothing: the next run, which no one
    /// stops, ends answering no Stop. A guard, true before the decision and after it.
    /// </summary>
    [Fact]
    public void AStopThatArrivesOnceItsRunHasEndedIsAnsweredAtOnceAndStoresNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            bool pressed = false;
            world.WhenPosted = root =>
            {
                if (!pressed && EndsTheRunOnThePage(root))
                {
                    pressed = true;
                    world.Receive("remodel.stop", "x1", new { });
                }
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.True(pressed);
            Assert.Equal("RunNotFound", world.ErrorClass("x1"));
            world.WhenPosted = null;
            world.Receive("remodel.plan", "p2", new { });
            string second = world.Reply("remodel.planned", "p2").GetProperty("run_dir").GetString()!;
            world.Receive("remodel.start", "s2", new { run_dir = second });
            world.Reply("remodel.started", "s2");
            Assert.Empty(world.AllPosted("remodel.stopped"));
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T215; research R19.9; the race review's finding R1, the host's half - a guard).
    /// Every Stop that reached the run is answered at its end, under its own id, to whichever page the pane shows then: a
    /// page that has since loaded again included. The ids here are the ones the page used before T216, numbered from `m1`
    /// at every load: the first load's Stop was its sixth request, and the load after it asks for the result as its sixth
    /// once the run's last word reaches it - so the answer to the earlier Stop and the result's own reply carry one id, and
    /// only the page can tell them apart (<c>RemodelPageContractTests.AnEarlierLoadsAnswerToStopIsNeverTakenForTheResultOfThePageThatLoadedAgain</c>).
    /// </summary>
    [Fact]
    public void EveryStopIsAnsweredUnderItsOwnIdThoughThePageLoadedAgain()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("ready", "m1", new { });
            world.Receive("remodel.plan", "m2", new { });
            string runDir = world.Reply("remodel.planned", "m2").GetProperty("run_dir").GetString()!;
            world.Receive("remodel.result", "m3", new { run_dir = runDir });
            int reloaded = -1;
            world.Pipeline.DuringRun = reporter =>
            {
                world.Receive("remodel.result", "m5", new { run_dir = runDir });
                world.Receive("remodel.stop", "m6", new { });

                // The page loads again mid-run: the load after it, which numbered its requests from m1 again.
                reloaded = world.Posted.Count;
                world.Receive("ready", "m1", new { });
                world.Receive("remodel.result", "m2", new { run_dir = runDir });
                world.Receive("remodel.stop", "m3", new { });
                world.Receive("report.open", "m4", new { run_dir = runDir });
                world.Receive("folder.open", "m5", new { run_dir = runDir });
                world.Pipeline.ChangesApplied = 2;
                world.Pipeline.RunState = "truncated";
            };

            world.Receive("remodel.start", "m4", new { run_dir = runDir });
            world.Receive("remodel.result", "m6", new { run_dir = runDir });

            List<JsonElement> toTheLoadAfter = world.Posted.Skip(reloaded)
                .Select(json => JsonDocument.Parse(json).RootElement.Clone()).ToList();
            Assert.Equal("init", toTheLoadAfter[0].GetProperty("type").GetString());
            Assert.True(toTheLoadAfter[0].GetProperty("payload").GetProperty("latest_run").GetProperty("running").GetBoolean());
            string[] underM6 = toTheLoadAfter
                .Where(message => message.TryGetProperty("id", out JsonElement id)
                    && id.ValueKind == JsonValueKind.String && id.GetString() == "m6")
                .Select(message => message.GetProperty("type").GetString()!)
                .ToArray();
            Assert.Equal(new[] { "remodel.stopped", "remodel.result" }, underM6);
        }
    }

    /// <summary>
    /// Owner decision 159A, on review, test first (004 T219; research R19.9; the race review's finding R3). A Start whose run
    /// cannot be handed to its scheduler posted its `error` - the run's last word on the page - and only then, in its
    /// <c>finally</c>, let go of the run, outside the lock that frees the host. The copy-gone stop, decided under that lock
    /// on SOLIDWORKS' thread, could land between: it found the run in flight, set its stop flag and told the page the run
    /// was stopping, after the run's last word; and the flag stayed on the plan, which stays startable, so the next Start's
    /// run was stopped before it began and answered `remodel.stopped` unasked. Here the copy goes away, and SOLIDWORKS says
    /// so, as that last word is posted - or, earlier, as `remodel.started` is, while the run is in flight: the stop is
    /// told then, before the last word, and taken back with the run, so the plan carries none into its next run.
    /// </summary>
    [Theory]
    [InlineData("error")]
    [InlineData("remodel.started")]
    public void AFailedHandOverLetsGoOfItsRunBeforeItsLastWordAndLeavesNoStopOnThePlan(string goneAs)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            Action<Action> schedule = world.Options.Schedule;
            world.Options.Schedule = work => throw new InvalidOperationException("FICT the run could not be handed on");
            string aside = world.ExpectedCopyPath + ".aside";
            bool gone = false;
            world.WhenPosted = root =>
            {
                bool now = goneAs == "error"
                    ? EndsTheRunOnThePage(root)
                    : root.GetProperty("type").GetString() == goneAs;
                if (!gone && now)
                {
                    gone = true;
                    File.Move(world.ExpectedCopyPath, aside);
                    world.Host.DocumentChanged();
                }
            };

            world.Receive("remodel.start", "s1", new { run_dir = runDir });

            int started = world.IndexOf("remodel.started");
            int ended = world.Posted.FindIndex(started + 1, json => EndsTheRunOnThePage(JsonDocument.Parse(json).RootElement));
            int stopping = world.Posted.FindIndex(json => Unescaped(json).Contains(RemodelHost.CopyGoneMessage));
            string sequence = string.Join(" | ", world.TypesPostedSince(started));
            bool flagLeft = world.Host.LatestRun!.StopRequested;

            world.WhenPosted = null;
            File.Move(aside, world.ExpectedCopyPath);
            world.Options.Schedule = schedule;
            bool stoppedBeforeItBegan = false;
            world.Pipeline.DuringRun = reporter => stoppedBeforeItBegan = reporter.StopRequested;
            int before = world.Posted.Count;
            world.Receive("remodel.start", "s2", new { run_dir = runDir });

            Assert.True(gone, "the failed hand-over posted no last word");
            Assert.True(ended >= 0, "the failed hand-over's last word was not posted after remodel.started");
            bool toldAfter = stopping > ended;
            bool answeredUnasked = world.TypesPostedSince(before).Contains("remodel.stopped");
            Assert.True(
                !toldAfter && !flagLeft && !stoppedBeforeItBegan && !answeredUnasked,
                $"told after the run's last word: {toldAfter} ({sequence}); flag left on the plan: {flagLeft}; "
                + $"next run stopped before it began: {stoppedBeforeItBegan}; answered remodel.stopped unasked: {answeredUnasked}");
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T229; the mutation review's RS8 - a guard): a run stopped only because its copy
    /// went away is answered unasked at its end, `remodel.stopped` with no id and the run's count, after its last word; no
    /// Stop reached it to be answered.
    /// </summary>
    [Fact]
    public void ARunStoppedOnlyBecauseItsCopyWentAwayIsAnsweredUnaskedAtItsEnd()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string aside = world.ExpectedCopyPath + ".aside";
            world.Pipeline.DuringRun = reporter =>
            {
                File.Move(world.ExpectedCopyPath, aside);
                world.Host.DocumentChanged();
                world.Pipeline.ChangesApplied = 3;
                world.Pipeline.RunState = "truncated";
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement stopped = Assert.Single(world.AllPosted("remodel.stopped"));
            int answered = world.IndexOf("remodel.stopped");
            int ended = world.Posted.FindLastIndex(json => EndsTheRunOnThePage(JsonDocument.Parse(json).RootElement));
            Assert.Equal(JsonValueKind.Null, JsonDocument.Parse(world.Posted[answered]).RootElement.GetProperty("id").ValueKind);
            Assert.Equal(3, stopped.GetProperty("changes_applied").GetInt32());
            Assert.True(answered > ended, "the unasked answer came before the run's last word");
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T229; the mutation review's RS10 - a guard): the stop when the copy goes away is
    /// decided once. Every later change of the active document while the run goes on to its end finds the stop already
    /// asked for, and tells the page nothing more.
    /// </summary>
    [Fact]
    public void TheStopWhenTheCopyIsGoneIsToldOnceHoweverOftenTheDocumentChanges()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string aside = world.ExpectedCopyPath + ".aside";
            world.Pipeline.DuringRun = reporter =>
            {
                File.Move(world.ExpectedCopyPath, aside);
                world.Host.DocumentChanged();
                world.Host.DocumentChanged();
                world.Host.DocumentChanged();
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Single(world.Posted, json => Unescaped(json).Contains(RemodelHost.CopyGoneMessage));
        }
    }

    /// <summary>
    /// Owner decision 159A: what the page receives when a stop's word - a post carrying <paramref name="held"/> - is held in
    /// its post, on the thread <paramref name="stop"/> runs on, while the run reaches its end on a thread of its own. The run,
    /// once stopped, finishes and closes its session; the held post is let go once the run's last word has been posted, or
    /// half a second after the close if it has not - when the run's end waits on the stop's word. Every wait is bounded, so a
    /// regression fails rather than hangs. Also answers whether the run reached its close while the word was held.
    /// </summary>
    private static (List<JsonElement> Posted, bool Closed) AStopsWordHeldAsTheRunEnds(RemodelWorld world, string held, Action stop)
    {
        using (var running = new ManualResetEventSlim())
        using (var closing = new ManualResetEventSlim())
        {
            Thread? run = null;
            bool closed = false;
            world.Channel = new PausingChannel(world.Posted, json =>
            {
                // A failed assertion here would be swallowed by the post it is in, so the wait is recorded and asserted after.
                if (Unescaped(json).Contains(held))
                {
                    closed = closing.Wait(TimeSpan.FromSeconds(10));
                    SpinWait.SpinUntil(() => TheRunsLastWordIsPosted(world), TimeSpan.FromMilliseconds(500));
                }
            });
            world.Scheduler = work =>
            {
                run = new Thread(() => work()) { IsBackground = true, Name = "fict-remodel-run" };
                run.Start();
            };
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.DuringRun = reporter =>
            {
                running.Set();
                SpinWait.SpinUntil(() => reporter.StopRequested, TimeSpan.FromSeconds(10));
                world.Pipeline.ChangesApplied = 1;
                world.Pipeline.RunState = "truncated";
            };
            world.Pipeline.DuringClose = () => closing.Set();

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            Assert.True(running.Wait(TimeSpan.FromSeconds(10)), "the run never began");
            stop();
            Assert.True(run != null && run.Join(TimeSpan.FromSeconds(10)), "the run never ended");

            lock (world.Posted)
            {
                return (world.Posted.Select(json => JsonDocument.Parse(json).RootElement.Clone()).ToList(), closed);
            }
        }
    }

    // ---- owner decision 159A: the tab's words for a failure whose own sentence can name a path ----------

    /// <summary>A fictional run folder, as the backend's and the disk's sentences name one.</summary>
    private const string FictionalRun = @"C:\Fictional\runs\20260101-000000-FICT-remodel";

    /// <summary>A fictional pipe, as the reviewer's bridge client names the one it could not reach.</summary>
    private const string FictionalPipe = @"\\.\pipe\FICT-swreview-remodel";

    /// <summary>A fictional backend log, as a failed start or restart ends (decision 150A).</summary>
    private const string FictionalLog = @"C:\Fictional\FICT-logs\backend.log";

    /// <summary>
    /// A refusal the review backend answered, as <c>BackendRemodelPipeline</c> hands it on: the backend's class and
    /// sentence, with its answer as the refusal's cause (<c>BackendRemodelPipelineTests</c> pins that the pipeline
    /// keeps it).
    /// </summary>
    private static RemodelRefusal TheBackends(string errorClass, string sentence, bool retryable = false) =>
        new RemodelRefusal(
            errorClass, sentence, retryable, new BackendRequestException(errorClass, sentence, retryable, null, 400));

    /// <summary>
    /// Owner decision 159A: whether <paramref name="text"/> names a path - a drive letter's root, or the two separators a
    /// share or a device path (a pipe) begins with.
    /// </summary>
    private static bool NamesAPath(string text) =>
        Regex.IsMatch(text, @"[A-Za-z]:[\\/]") || text.Contains(@"\\") || text.Contains("//");

    /// <summary>
    /// Owner decision 159A: every sentence the Remodel page can print out of what the host posted from
    /// <paramref name="from"/> on - an `error`'s message, a `status`'s, Show's `entity.shown`, a lost plan's notice and
    /// `init`'s, and the capability's - with the type it came in. Not the fields the page shows as the run's data: the run
    /// folder and the active document in its header (`init`, `document.changed`, `remodel.planned`), and what
    /// `remodel.result`, `remodel.change` and `remodel.progress` read out of the run folder.
    /// </summary>
    private static List<(string Type, string Sentence)> PrintedSentences(RemodelWorld world, int from = 0)
    {
        var printed = new List<(string Type, string Sentence)>();
        List<string> posted;
        lock (world.Posted)
        {
            posted = world.Posted.Skip(from).ToList();
        }

        foreach (string json in posted)
        {
            JsonElement root = JsonDocument.Parse(json).RootElement;
            string type = root.GetProperty("type").GetString()!;
            JsonElement payload = root.GetProperty("payload");
            void Take(JsonElement element, string name)
            {
                if (element.ValueKind == JsonValueKind.Object
                    && element.TryGetProperty(name, out JsonElement value)
                    && value.ValueKind == JsonValueKind.String)
                {
                    printed.Add((type, value.GetString()!));
                }
            }

            switch (type)
            {
                case "error":
                case "status":
                case "entity.shown":
                case "remodel.plan_lost":
                    Take(payload, "message");
                    break;
                case "init":
                    Take(payload.GetProperty("remodel"), "message");
                    if (payload.GetProperty("latest_run").ValueKind == JsonValueKind.Object)
                    {
                        Take(payload.GetProperty("latest_run"), "plan_lost");
                    }

                    break;
                case "document.changed":
                    if (payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("remodel", out JsonElement remodel))
                    {
                        Take(remodel, "message");
                    }

                    break;
            }
        }

        return printed;
    }

    /// <summary>Owner decision 159A: no sentence the page can print, posted from <paramref name="from"/> on, names a path.</summary>
    private static void AssertNothingPrintedNamesAPath(RemodelWorld world, int from = 0)
    {
        foreach ((string type, string sentence) in PrintedSentences(world, from))
        {
            Assert.False(NamesAPath(sentence), $"a '{type}' the page prints names a path: {sentence}");
        }
    }

    /// <summary>
    /// The routes by which a failure whose own sentence can name a path reached the Remodel page (004 research R18.1's
    /// list, R18.7 item 1): the bridge's `not_a_part` and `source_not_open`, its refusals of the copy, the backend's
    /// `RunFolderFailed` and `PackageMissing`, `POST /remodel/runs`, the run's own failure, `OpenFailed` and `DiscardFailed`,
    /// the restart gate's `BackendUnavailable` and the add-in's word that the backend did not start, Show's
    /// `entity.shown`, and the host's own failures beside them.
    /// </summary>
    public static IEnumerable<object[]> FailuresThatCanNameAPath => new[]
    {
        new object[] { "the probe: the bridge's not_a_part" },
        new object[] { "the probe: the bridge's source_not_open" },
        new object[] { "the probe: SOLIDWORKS not answering" },
        new object[] { "the open: a refusal of the copy" },
        new object[] { "the open: the backend not answering" },
        new object[] { "the plan: the backend's PackageMissing" },
        new object[] { "the plan: a failure of the add-in's own" },
        new object[] { "the plan: the run folder not made" },
        new object[] { "the plan: the earlier plan's close not answered" },
        new object[] { "the plan: the earlier plan's close refused by the backend" },
        new object[] { "Start: POST /remodel/runs refused" },
        new object[] { "the run: the backend's failure in the run line" },
        new object[] { "the run: a failure of the add-in's own" },
        new object[] { "the run: its close not answered" },
        new object[] { "the run: its close not answered by the review backend" },
        new object[] { "Open copy: SOLIDWORKS would not open it" },
        new object[] { "Discard copy: the copy could not be deleted" },
        new object[] { "Discard copy: discarded not written" },
        new object[] { "Show change: SOLIDWORKS could not show it" },
        new object[] { "Open report: Windows could not open it" },
        new object[] { "Open run folder: Windows could not open it" },
        new object[] { "View log: the log folder could not be made" },
        new object[] { "View log: Windows could not open it" },
        new object[] { "the restart gate: the restart failed" },
        new object[] { "the add-in: the backend did not start" },
    };

    /// <summary>
    /// Owner decision 159A, test first (004 T208; research R18.7 item 1): every failure whose own sentence can name a path
    /// reaches the Remodel tab in the tab's own plain words, where the sentence a test of each route carries names a
    /// fictional drive-letter path, run folder, pipe or log; no sentence the page can print names a path; and the failure's
    /// own sentence is in the host's log, for whoever debugs. Before, each reached the page as it was raised. *Changed
    /// deliberately 2026-10-21 (owner decision 159A, on review; 004 T230, research R19.9):* but for the add-in's word that the
    /// backend did not start, whose words send the engineer to the Review tab, which shows the failure whole, and which the
    /// add-in's own report of a first start logs: the host logs nothing more, where it logged it a second time.
    /// </summary>
    [Theory]
    [MemberData(nameof(FailuresThatCanNameAPath))]
    public void AFailureThatCanNameAPathReachesTheTabInItsOwnWordsAndItsSentenceGoesToTheLog(string route)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            string said;
            string words;
            switch (route)
            {
                case "the probe: the bridge's not_a_part":
                    said = $"'{BridgePart}' is not an existing .SLDPRT file. The re-modeler works on parts, and only on parts, in stage 1.";
                    world.Pipeline.ProbeFailure = TheBackends("NotAPart", said);
                    words = RemodelHost.NotAPartOnDiskMessage;
                    APlanIsRefusedInTheTabsWords(world, "NotAPart", words);
                    break;
                case "the probe: the bridge's source_not_open":
                    said = $"SOLIDWORKS does not have '{BridgePart}' open. The probe reads the document the engineer already has open.";
                    world.Pipeline.ProbeFailure = TheBackends("RunFolderFailed", said);
                    words = RemodelHost.BackendFailedMessage;
                    APlanIsRefusedInTheTabsWords(world, "RunFolderFailed", words);
                    break;
                case "the probe: SOLIDWORKS not answering":
                    said = $"the SOLIDWORKS bridge did not answer remodel.probe_scope: the bridge on {FictionalPipe} could not be reached: [WinError 2]";
                    world.Pipeline.ProbeFailure = TheBackends("BridgeUnavailable", said, retryable: true);
                    words = RemodelHost.BridgeNotAnsweringMessage;
                    APlanIsRefusedInTheTabsWords(world, "BridgeUnavailable", words);
                    break;
                case "the open: a refusal of the copy":
                    said = $"the copy target '{FictionalRun}\\copy\\FICT-bracket-RMS.SLDPRT' already exists, and the re-modeler never writes over a file.";
                    world.Pipeline.CopyFailure = TheBackends("RunFolderFailed", said);
                    words = RemodelHost.BackendFailedMessage;
                    APlanIsRefusedInTheTabsWords(world, "RunFolderFailed", words);
                    break;
                case "the open: the backend not answering":
                    said = "the review backend did not answer: Unable to connect to the remote server";
                    world.Pipeline.CopyFailure = TheBackends("BackendUnavailable", said, retryable: true);
                    words = RemodelHost.BackendNotAnsweringMessage;
                    APlanIsRefusedInTheTabsWords(world, "BackendUnavailable", words);
                    break;
                case "the plan: the backend's PackageMissing":
                    said = $"package-before.json is not in {FictionalRun}; the dump has not been written";
                    world.Pipeline.PlanFailure = TheBackends("PackageMissing", said);
                    words = RemodelHost.BackendFailedMessage;
                    APlanIsRefusedInTheTabsWords(world, "PackageMissing", words);
                    break;
                case "the plan: a failure of the add-in's own":
                    said = $"'{FictionalRun}\\package.json' records the 'full' profile, so it cannot be used as 'package-before.json'.";
                    world.Pipeline.PlanFailure = new InvalidOperationException(said);
                    words = RemodelHost.UnexpectedFailureMessage;
                    APlanIsRefusedInTheTabsWords(world, "HostError", words);
                    break;
                case "the plan: the run folder not made":
                    string file = Path.Combine(world.Root, "FICT-not-a-folder");
                    File.WriteAllText(file, "a file where the run root would be");
                    world.RunRootSpelling = Path.Combine(file, "runs");
                    said = file;
                    words = RemodelHost.RunFolderNotMadeMessage;
                    APlanIsRefusedInTheTabsWords(world, "RunFolderFailed", words);
                    break;
                case "the plan: the earlier plan's close not answered":
                    world.Receive("remodel.plan", "p0", new { });
                    said = $"the pipe {FictionalPipe} was closed before the close was answered";
                    world.Pipeline.CloseFailure = new IOException(said);
                    words = RemodelHost.EarlierPlanNotClosedMessage;
                    world.Receive("remodel.plan", "p1", new { });
                    JsonElement refused = world.Reply("error", "p1");
                    Assert.Equal("BridgeUnavailable", refused.GetProperty("error_class").GetString());
                    Assert.Equal(words, refused.GetProperty("message").GetString());
                    break;
                case "the plan: the earlier plan's close refused by the backend":
                    // Owner decision 159A, on review (004 T225; the mutation review's M3): the backend's own
                    // `BridgeUnavailable`, whose sentence names the bridge's pipe (`chat/remodel.py`, `_unavailable`).
                    world.Receive("remodel.plan", "p0", new { });
                    said = $"the SOLIDWORKS bridge did not answer remodel.close: the bridge on {FictionalPipe} could not be reached";
                    world.Pipeline.CloseFailure = TheBackends("BridgeUnavailable", said, retryable: true);
                    words = RemodelHost.EarlierPlanNotClosedMessage;
                    world.Receive("remodel.plan", "p1", new { });
                    AnAnswerIs(world, "p1", "BridgeUnavailable", words);
                    Assert.True(world.Reply("error", "p1").GetProperty("retryable").GetBoolean());
                    Assert.Empty(world.AllPosted("remodel.plan_lost"));
                    break;
                case "Start: POST /remodel/runs refused":
                    world.Receive("remodel.plan", "p1", new { });
                    said = $"{FictionalRun} holds no plan; press Remodel to plan this part before starting a run";
                    world.Pipeline.RunFailure = TheBackends("RunNotPlanned", said);
                    words = RemodelHost.BackendFailedMessage;
                    world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                    JsonElement unasked = Assert.Single(world.AllPosted("error"));
                    Assert.Equal("RunNotPlanned", unasked.GetProperty("error_class").GetString());
                    Assert.Equal(words, unasked.GetProperty("message").GetString());
                    Assert.Contains(world.AllPosted("status"), status => status.GetProperty("message").GetString() == words);
                    break;
                case "the run: the backend's failure in the run line":
                    world.Receive("remodel.plan", "p1", new { });
                    said = $"OSError: [Errno 13] Permission denied: '{FictionalRun}\\plan.json'";
                    world.Pipeline.RunState = "failed";
                    world.Pipeline.DuringRun = reporter => reporter.Status("error", said);
                    words = RemodelHost.BackendFailedMessage;
                    world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                    Assert.Contains(world.AllPosted("status"), status => status.GetProperty("stage").GetString() == "error"
                        && status.GetProperty("message").GetString() == words);
                    break;
                case "the run: a failure of the add-in's own":
                    world.Receive("remodel.plan", "p1", new { });
                    said = $"Access to the path '{FictionalRun}\\package-after.json' is denied.";
                    world.Pipeline.RunFailure = new IOException(said);
                    words = RemodelHost.UnexpectedFailureMessage;
                    world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                    JsonElement failed = Assert.Single(world.AllPosted("error"));
                    Assert.Equal("HostError", failed.GetProperty("error_class").GetString());
                    Assert.Equal(words, failed.GetProperty("message").GetString());
                    Assert.Contains(world.AllPosted("status"), status => status.GetProperty("message").GetString() == words);
                    break;
                case "the run: its close not answered":
                    world.Receive("remodel.plan", "p1", new { });
                    said = $"the pipe {FictionalPipe} was closed before the close was answered";
                    world.Pipeline.CloseFailure = new IOException(said);
                    words = RemodelHost.RunCloseNotAnsweredMessage;
                    world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                    Assert.Equal(words, world.LastPosted("status").GetProperty("message").GetString());
                    break;
                case "the run: its close not answered by the review backend":
                    // Owner decision 159A, on review (004 T223; the mutation review's M6): the add-in's client gives up after
                    // 30 seconds, while the backend waits 60 for the bridge.
                    world.Receive("remodel.plan", "p1", new { });
                    said = $"the review backend did not answer: The operation has timed out (FICT {FictionalRun})";
                    world.Pipeline.CloseFailure = TheBackends("BackendUnavailable", said, retryable: true);
                    words = RemodelHost.RunCloseNotAnsweredMessage;
                    world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
                    Assert.Equal(words, world.LastPosted("status").GetProperty("message").GetString());
                    Assert.False(world.Host.LatestRun!.SessionEnded);
                    break;
                case "Open copy: SOLIDWORKS would not open it":
                    world.Receive("remodel.plan", "p1", new { });
                    said = $"SOLIDWORKS would not open the copy at '{FictionalRun}\\copy\\FICT-bracket-RMS.SLDPRT': file not found.";
                    world.Pipeline.ActivateFailure = new InvalidOperationException(said);
                    words = RemodelHost.OpenCopyFailedMessage;
                    world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });
                    AnAnswerIs(world, "o1", "OpenFailed", words);
                    break;
                case "Discard copy: the copy could not be deleted":
                    world.Receive("remodel.plan", "p1", new { });
                    words = RemodelHost.DiscardCopyFailedMessage;
                    said = Path.GetFileName(world.ExpectedCopyPath);
                    using (new FileStream(world.ExpectedCopyPath, FileMode.Open, FileAccess.Read, FileShare.None))
                    {
                        world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
                    }

                    AnAnswerIs(world, "d1", "DiscardFailed", words);
                    break;
                case "Discard copy: discarded not written":
                    world.Receive("remodel.plan", "p1", new { });
                    string plan = Path.Combine(world.ExpectedRunDirectory, "plan.json");
                    words = RemodelHost.DiscardStateNotWrittenMessage;
                    said = plan;
                    File.SetAttributes(plan, FileAttributes.ReadOnly);
                    try
                    {
                        world.Receive("remodel.discard_copy", "d1", new { run_dir = world.ExpectedRunDirectory });
                    }
                    finally
                    {
                        File.SetAttributes(plan, FileAttributes.Normal);
                    }

                    AnAnswerIs(world, "d1", "DiscardFailed", words);
                    break;
                case "Show change: SOLIDWORKS could not show it":
                    world.Receive("remodel.plan", "p1", new { });
                    world.WriteRunArtifacts();
                    said = "'C:\\Fictional\\FICT-sheet.SLDDRW' is a drawing, which has no configuration to bind a session to.";
                    world.Resolver.Failure = new InvalidOperationException(said);
                    words = RemodelHost.ShowFailedMessage;
                    world.Receive("remodel.show_change", "c1", new { run_dir = world.ExpectedRunDirectory, change_seq = 17 });
                    JsonElement shown = world.Reply("entity.shown", "c1");
                    Assert.False(shown.GetProperty("ok").GetBoolean());
                    Assert.Equal(words, shown.GetProperty("message").GetString());
                    break;
                case "Open report: Windows could not open it":
                case "Open run folder: Windows could not open it":
                    world.Receive("remodel.plan", "p1", new { });
                    world.WriteRunArtifacts();
                    said = $"no application is associated with '{FictionalRun}\\report.md'";
                    world.Opener.Failure = new System.ComponentModel.Win32Exception(said);
                    words = RemodelHost.NotOpenedMessage;
                    world.Receive(route.StartsWith("Open report", StringComparison.Ordinal) ? "report.open" : "folder.open", "r1", new { run_dir = world.ExpectedRunDirectory });
                    AnAnswerIs(world, "r1", "OpenFailed", words);
                    break;
                case "View log: the log folder could not be made":
                    string blocker = Path.Combine(world.Root, "FICT-log-file");
                    File.WriteAllText(blocker, "a file where the log folder would be");
                    world.LogFolder = Path.Combine(blocker, "logs");
                    said = blocker;
                    words = RemodelHost.LogFolderNotOpenedMessage;
                    world.Receive("log.open", "l1", new { });
                    AnAnswerIs(world, "l1", "OpenFailed", words);
                    break;
                case "View log: Windows could not open it":
                    said = $"no application is associated with '{world.LogFolder}'";
                    world.Opener.Failure = new System.ComponentModel.Win32Exception(said);
                    words = RemodelHost.LogFolderNotOpenedMessage;
                    world.Receive("log.open", "l1", new { });
                    AnAnswerIs(world, "l1", "OpenFailed", words);
                    break;
                case "the restart gate: the restart failed":
                    said = $"the backend could not be started: the job refused it (log: {FictionalLog})";
                    world.Options.BeginRun = begin => new BackendRequestException("BackendUnavailable", said, retryable: true);
                    words = RemodelHost.BackendNotRestartedMessage;
                    world.Receive("remodel.plan", "p1", new { });
                    AnAnswerIs(world, "p1", "BackendUnavailable", words);
                    Assert.True(world.Reply("error", "p1").GetProperty("retryable").GetBoolean());
                    break;
                case "the add-in: the backend did not start":
                    said = $"the backend did not answer /health within 30 seconds. See the log at {FictionalLog}.";
                    words = RemodelHost.BackendDidNotStartMessage;
                    world.Host.PostStatus("error", ReviewHost.WithTheWayOn(said, ReviewHost.StartItAgainOnTheReviewTab), lifecycle: true);
                    JsonElement told = world.LastPosted("status");
                    Assert.Equal("error", told.GetProperty("stage").GetString());
                    Assert.Equal(words, told.GetProperty("message").GetString());
                    Assert.True(told.GetProperty("lifecycle").GetBoolean());
                    break;
                default:
                    throw new ArgumentOutOfRangeException(nameof(route), route, "no such route");
            }

            AssertNothingPrintedNamesAPath(world);
            List<string> logged;
            lock (world.Logged)
            {
                logged = world.Logged.ToList();
            }

            if (route == "the add-in: the backend did not start")
            {
                Assert.DoesNotContain(logged, line => line.Contains(said));
            }
            else
            {
                Assert.Contains(logged, line => line.Contains(said));
            }
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T208): the host's log keeps what a failure said masked, as everything this host sends is
    /// (FR-015): a failure's sentence that quotes the backend's token reaches neither the page nor the log unmasked, and the
    /// rest of the sentence is kept.
    /// </summary>
    [Fact]
    public void WhatTheLogKeepsIsMasked()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.ProbeFailure = TheBackends("RunFolderFailed", "FICT the backend refused it, quoting 0FAKEtoken.");

            world.Receive("remodel.plan", "p1", new { });

            List<string> logged;
            lock (world.Logged)
            {
                logged = world.Logged.ToList();
            }

            Assert.Contains(logged, line => line.Contains("FICT the backend refused it, quoting"));
            Assert.All(logged, line => Assert.DoesNotContain("0FAKEtoken", line, StringComparison.Ordinal));
            Assert.All(
                world.Posted.Where(json => !json.Contains("\"type\":\"init\"")),
                json => Assert.DoesNotContain("0FAKEtoken", json, StringComparison.Ordinal));
        }
    }

    /// <summary>
    /// Owner decision 159A, on review, test first (004 T217; research R19.9; the race review's finding R2): the sentence the
    /// tab sends the engineer to View log to read reaches <c>addin.log</c> though another append holds the file as Open copy
    /// fails - its handle open as an append's is, writing and sharing the file for reading only. The add-in appends there
    /// from several threads at once; the sentence was lost. The host logs through the append <c>AddInLog.Write</c> makes,
    /// on a file of this case's own (<see cref="AddInLogTests"/>).
    /// </summary>
    [Fact]
    public void AFailuresSentenceReachesTheAddInsLogThoughAnotherAppendHoldsTheFile()
    {
        using (var world = new RemodelWorld())
        {
            string log = Path.Combine(world.Root, "FICT-addin.log");
            File.WriteAllText(log, string.Empty);
            world.Open();
            world.Options.Log = line => AddInLog.Append(log, line);
            world.Receive("remodel.plan", "p1", new { });
            const string Sentence = "FICT SOLIDWORKS would not open the copy";
            world.Pipeline.ActivateFailure = new InvalidOperationException(Sentence);

            using (new FileStream(log, FileMode.Append, FileAccess.Write, FileShare.Read))
            {
                world.Receive("remodel.open_copy", "o1", new { run_dir = world.ExpectedRunDirectory });
            }

            AnAnswerIs(world, "o1", "OpenFailed", RemodelHost.OpenCopyFailedMessage);
            AddInLog.Append(log, "FICT a later line");
            string written = File.ReadAllText(log);
            Assert.Contains("FICT a later line", written, StringComparison.Ordinal);
            Assert.Contains(Sentence, written, StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T235 - a guard; asked as 158A was merged): a line the add-in's log keeps while
    /// something else holds the file is the line the host masked, so the key a failure quoted reaches neither the kept
    /// line nor the file once it is written. The host masks a line before it hands it on (FR-015;
    /// <see cref="WhatTheLogKeepsIsMasked"/>), and <c>AddInLog</c> keeps only what it is handed.
    /// </summary>
    [Fact]
    public void ALineKeptWhileTheLogIsHeldIsTheMaskedLine()
    {
        using (var world = new RemodelWorld())
        {
            string log = Path.Combine(world.Root, "FICT-addin.log");
            File.WriteAllText(log, string.Empty);
            world.Open();
            world.Options.Log = line => AddInLog.Append(log, line);
            world.Pipeline.ProbeFailure = TheBackends("RunFolderFailed", "FICT the backend refused it, quoting 0FAKEtoken.");

            using (new FileStream(log, FileMode.Append, FileAccess.Write, FileShare.Read))
            {
                world.Receive("remodel.plan", "p1", new { });
            }

            AddInLog.Append(log, "FICT a later line");
            string written = File.ReadAllText(log);
            Assert.Contains("FICT the backend refused it, quoting", written, StringComparison.Ordinal);
            Assert.DoesNotContain("0FAKEtoken", written, StringComparison.Ordinal);
            Assert.Contains("FICT a later line", written, StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T229 - a guard): the line the host's log keeps, in the shape research R19.3 and
    /// `run-artifacts.md` give it - `Remodel tab, &lt;what was asked&gt;: &lt;class&gt;: &lt;sentence&gt;` for a refusal,
    /// and for any other failure the whole of it: its type, its message and where it was thrown.
    /// </summary>
    [Fact]
    public void TheLogKeepsWhatWasAskedAndWhatTheFailureSaid()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Pipeline.ProbeFailure = TheBackends("RunFolderFailed", "FICT the backend refused the probe.");
            world.Receive("remodel.plan", "p1", new { });
            world.Pipeline.ProbeFailure = new InvalidOperationException("FICT the add-in failed the probe.");
            world.Receive("remodel.plan", "p2", new { });

            List<string> logged;
            lock (world.Logged)
            {
                logged = world.Logged.ToList();
            }

            Assert.Equal(2, logged.Count);
            Assert.Equal("Remodel tab, remodel.plan: RunFolderFailed: FICT the backend refused the probe.", logged[0]);
            Assert.StartsWith(
                "Remodel tab, remodel.plan: System.InvalidOperationException: FICT the add-in failed the probe.",
                logged[1],
                StringComparison.Ordinal);
            Assert.Contains(" at ", logged[1], StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T229; the mutation review's RW5 - a guard): a log that throws - its folder gone,
    /// its disk full - costs nothing but its line. The page is answered all the same, and a run whose ending holds a refusal
    /// to tell still tells it, with the run's last word after it: a throw from the log inside a held post would have left
    /// <c>Execute</c> before that last word.
    /// </summary>
    [Fact]
    public void ALogThatThrowsCostsNothingButItsLine()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Options.Log = line => throw new IOException("FICT the log's disk is full");
            world.Pipeline.ProbeFailure = TheBackends("RunFolderFailed", "FICT the backend refused the probe.");
            world.Receive("remodel.plan", "p1", new { });
            AnAnswerIs(world, "p1", "RunFolderFailed", RemodelHost.BackendFailedMessage);

            world.Pipeline.ProbeFailure = null;
            world.Receive("remodel.plan", "p2", new { });
            world.Pipeline.RunFailure = TheBackends("PackageMissing", "FICT package-after.json is not there.");
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Contains(
                world.AllPosted("error"), error => error.GetProperty("error_class").GetString() == "PackageMissing");
            Assert.Equal(
                "The run ended without saving the copy. The report says why.",
                world.LastPosted("status").GetProperty("message").GetString());
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 T229; the mutation review's M2 - a guard): only the add-in's `error` on the
    /// backend is told in this tab's words. Its other words on the backend - `backend_starting` and `ready`, which every
    /// start of the add-in posts (<c>SwReviewAddIn.StartBackend</c>) - reach the page as the add-in gave them, still marked
    /// as its own, and nothing of them is logged.
    /// </summary>
    [Theory]
    [InlineData("backend_starting", "Starting the review backend...")]
    [InlineData("ready", "Backend ready.")]
    public void TheAddInsOtherWordsOnTheBackendReachTheTabAsTheyAre(string stage, string message)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();

            world.Host.PostStatus(stage, message, lifecycle: true);

            JsonElement told = world.LastPosted("status");
            Assert.Equal(stage, told.GetProperty("stage").GetString());
            Assert.Equal(message, told.GetProperty("message").GetString());
            Assert.True(told.GetProperty("lifecycle").GetBoolean());
            Assert.Empty(world.Logged);
        }
    }

    /// <summary>A plan refused with <paramref name="errorClass"/> in <paramref name="words"/>, in the refusal and in the run line's `error` beside it.</summary>
    private static void APlanIsRefusedInTheTabsWords(RemodelWorld world, string errorClass, string words)
    {
        world.Receive("remodel.plan", "p1", new { });
        AnAnswerIs(world, "p1", errorClass, words);
        Assert.All(
            world.AllPosted("status").Where(status => status.GetProperty("stage").GetString() == "error"),
            status => Assert.Equal(words, status.GetProperty("message").GetString()));
    }

    /// <summary>The `error` answering <paramref name="id"/>, of <paramref name="errorClass"/>, in <paramref name="words"/>.</summary>
    private static void AnAnswerIs(RemodelWorld world, string id, string errorClass, string words)
    {
        JsonElement error = world.Reply("error", id);
        Assert.Equal(errorClass, error.GetProperty("error_class").GetString());
        Assert.Equal(words, error.GetProperty("message").GetString());
    }

    /// <summary>
    /// The classes the review backend answers on the remodel routes, as its contract's error table lists them
    /// (<c>backend-remodel.md</c>), with the two it shares with every route (<c>InvalidRunDir</c>, <c>InvalidRequest</c>) and the
    /// three the add-in's client of it raises (<c>BackendUnavailable</c>, <c>HttpError</c>, <c>BadResponse</c>).
    /// </summary>
    public static IEnumerable<object[]> TheBackendsClasses()
    {
        string contract = File.ReadAllText(Path.Combine(
            ErrorLabelsCoverTheHostTests.RepositoryRoot(), "specs", "004-resilient-remodeler", "contracts", "backend-remodel.md"));
        int table = contract.IndexOf("## Error classes", StringComparison.Ordinal);
        int end = contract.IndexOf("\n## ", table + 1, StringComparison.Ordinal);
        var classes = Regex.Matches(contract.Substring(table, end - table), @"^\| `(?<class>[A-Za-z]+)` \|", RegexOptions.Multiline)
            .Cast<Match>()
            .Select(match => match.Groups["class"].Value)
            .Concat(new[] { "InvalidRunDir", "InvalidRequest", "BackendUnavailable", "HttpError", "BadResponse" })
            .Distinct(StringComparer.Ordinal)
            .ToList();
        return classes.Select(errorClass => new object[] { errorClass });
    }

    /// <summary>Owner decision 159A (004 T208): the contract's error table is read whole, so no class it lists goes unworded.</summary>
    [Fact]
    public void TheBackendsErrorTableIsReadWhole()
    {
        string[] classes = TheBackendsClasses().Select(row => (string)row[0]).ToArray();

        foreach (string errorClass in new[]
                 {
                     "NotAPart", "DocumentDirty", "ExternalReferences", "ScopeRefused", "RunFolderFailed", "BridgeUnavailable",
                     "PackageMissing", "NotModelCheck", "RunNotPlanned", "ResumeRefused", "RunInProgress", "UnknownJob",
                     "PackageAfterRefused",
                 })
        {
            Assert.Contains(errorClass, classes);
        }
    }

    /// <summary>
    /// What the review backend's body says for `ScopeRefused`, the one class it words plainly itself (owner decision 149A,
    /// `SCOPE_REFUSAL_WORDS`, pinned word for word in <c>test_chat_remodel_routes.py</c>): the tab prints it as it is.
    /// </summary>
    private const string BackendsScopeWords =
        "The part to be copied is not one this remodel checked, so nothing was copied and no new plan was made. Your part "
        + "was not changed. Make your part the active document and press Remodel a copy again.";

    /// <summary>
    /// Owner decision 159A, test first (004 T208): every class the review backend can answer reaches the tab in words that
    /// name no path - the tab's own for the class, or for every class it has no sentence of its own for - where its sentence
    /// names the part's full path and a run folder, as the backend's do; `ScopeRefused` in the backend's own plain words.
    /// The sentence is in the host's log.
    /// </summary>
    [Theory]
    [MemberData(nameof(TheBackendsClasses))]
    public void EveryClassTheBackendAnswersReachesTheTabInWordsThatNameNoPath(string errorClass)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            string said = errorClass == "ScopeRefused"
                ? BackendsScopeWords
                : $"the backend refused '{BridgePart}' with {errorClass} in {FictionalRun}.";
            world.Pipeline.ProbeFailure = TheBackends(errorClass, said);

            world.Receive("remodel.plan", "p1", new { });

            string expected = errorClass switch
            {
                "DocumentDirty" => RemodelHost.DocumentDirtyMessage,
                "ExternalReferences" => RemodelHost.ExternalReferencesMessage,
                "ScopeRefused" => BackendsScopeWords,
                "NotAPart" => RemodelHost.NotAPartOnDiskMessage,
                "BridgeUnavailable" => RemodelHost.BridgeNotAnsweringMessage,
                "BackendUnavailable" => RemodelHost.BackendNotAnsweringMessage,
                _ => RemodelHost.BackendFailedMessage,
            };
            AnAnswerIs(world, "p1", errorClass, expected);
            AssertNothingPrintedNamesAPath(world);
            if (errorClass != "ScopeRefused")
            {
                Assert.Contains(world.Logged, line => line.Contains(said));
            }
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T208): the sentences of the tab's own for a failure that can name a path, word for word.
    /// Each says what was not done and that the engineer's part was not changed - but the word that the backend did not
    /// start, which reports no press, and the two of Windows not opening a file or a folder - and the way on, by the
    /// button's label where there is one; and each names no path, no command and none of the build's plumbing. *Changed
    /// deliberately 2026-10-21 (owner decision 159A, on review; 004 T223, research R19.9):* the two words of a close that
    /// was not answered no longer say SOLIDWORKS did not answer it - a close the review backend did not carry, or refused
    /// before the bridge was asked, is not answered either (the mutation review's M6) - but what is known: that closing the
    /// copy was not confirmed.
    /// </summary>
    [Fact]
    public void TheTabsWordsForAFailureThatCanNameAPathArePlain()
    {
        var expected = new Dictionary<string, string>
        {
            {
                RemodelHost.UnexpectedFailureMessage,
                "The add-in met a failure it did not expect, so what was asked was not done. Your part was not changed. "
                    + "Press View log to see why."
            },
            {
                RemodelHost.NotAPartOnDiskMessage,
                "The active document is not a part file the re-modeler can find where SOLIDWORKS opened it from - it may have "
                    + "been moved, renamed or deleted since - so nothing was copied and no new plan was made. Your part was not "
                    + "changed. Save it as a part, then press Remodel a copy again."
            },
            {
                RemodelHost.BridgeNotAnsweringMessage,
                "SOLIDWORKS did not answer the re-modeler, so it stopped. Your part was not changed. Wait a moment, then press "
                    + "Remodel a copy again."
            },
            {
                RemodelHost.BackendNotAnsweringMessage,
                "The review backend did not answer, so the re-modeler stopped. Your part was not changed. Wait for the backend "
                    + "to be ready, then press Remodel a copy again."
            },
            {
                RemodelHost.BackendFailedMessage,
                "The review backend could not do a step of this remodel, so it stopped. Your part was not changed. Press View "
                    + "log to see why, then press Remodel a copy to plan again."
            },
            {
                RemodelHost.RunFolderNotMadeMessage,
                "The run folder could not be made under the run root, so nothing was copied and no new plan was made. Your part "
                    + "was not changed. Press View log to see why; if the run root cannot be written to, choose a local folder "
                    + "for runs in Settings on the Review tab, then press Remodel a copy again."
            },
            {
                RemodelHost.EarlierPlanNotClosedMessage,
                "Closing the earlier plan's copy was not confirmed, so that plan is left as it was and no new plan was made. "
                    + "Your part was not changed. Wait a moment, then press Remodel a copy again."
            },
            {
                RemodelHost.RunCloseNotAnsweredMessage,
                "The run ended, but closing its copy was not confirmed, so the copy may still be open in SOLIDWORKS; the "
                    + "report and the saved artifacts are kept. Your part was not changed. Press View log to see why."
            },
            {
                RemodelHost.OpenCopyFailedMessage,
                "SOLIDWORKS did not open the copy, so nothing was opened. Your part was not changed. Press View log to see why, "
                    + "then press Open copy again."
            },
            {
                RemodelHost.DiscardCopyFailedMessage,
                "The copy could not be deleted, so it is still in the run folder; SOLIDWORKS may still have it open. Your part "
                    + "was not changed. Close the copy in SOLIDWORKS without saving, then press Discard copy again. Press View "
                    + "log to see why."
            },
            {
                RemodelHost.DiscardStateNotWrittenMessage,
                "The copy was deleted, but 'discarded' could not be written to plan.json, so this tab would go on reporting the "
                    + "state the run ended in. Your part was not changed. Press View log to see why."
            },
            {
                RemodelHost.BackendNotRestartedMessage,
                "The review backend has not restarted with the saved settings, so nothing was done. Your part was not changed. "
                    + "Save the settings again on the Review tab to restart it, then try again. Press View log to see why."
            },
            {
                RemodelHost.BackendDidNotStartMessage,
                "The review backend did not start, so this tab cannot plan or run. The Review tab says why. Save Settings on the "
                    + "Review tab to start it again."
            },
            {
                RemodelHost.ShowFailedMessage,
                "SOLIDWORKS could not show this, so nothing was selected. Press View log to see why."
            },
            {
                RemodelHost.NotOpenedMessage,
                "Windows could not open it, so nothing was opened. Press View log to see why."
            },
            {
                RemodelHost.LogFolderNotOpenedMessage,
                "Windows could not open the log folder, so nothing was opened."
            },
        };

        foreach (KeyValuePair<string, string> sentence in expected)
        {
            Assert.Equal(sentence.Value, sentence.Key);
            AssertPlainWords(sentence.Key);
            Assert.False(NamesAPath(sentence.Key), sentence.Key);
            Assert.DoesNotContain("/", sentence.Key, StringComparison.Ordinal);
            Assert.DoesNotContain("run_dir", sentence.Key, StringComparison.Ordinal);
        }
    }

    /// <summary>Whether a `status` that ends the run on the page has been posted since `remodel.started`, read under the posts' lock.</summary>
    private static bool TheRunsLastWordIsPosted(RemodelWorld world)
    {
        lock (world.Posted)
        {
            List<JsonElement> posted = world.Posted.Select(json => JsonDocument.Parse(json).RootElement.Clone()).ToList();
            int started = posted.FindIndex(message => message.GetProperty("type").GetString() == "remodel.started");
            return started >= 0 && posted.FindIndex(started + 1, EndsTheRunOnThePage) >= 0;
        }
    }

    // ---- a settings restart and a plan or a run (owner decision 145A) ---------------------------

    /// <summary>
    /// Owner decision 145A: a plan holds the backend for as long as it runs, as a turn does, so it
    /// begins through the review host's restart gate - asked once, after every refusal that needs
    /// no call and before the first pipeline call - and the host is marked busy by the gate's own
    /// step, under the restart's lock, and not before.
    /// </summary>
    [Fact]
    public void APlanBeginsThroughTheRestartGateAfterItsOwnRefusalsAndBeforeAnyCall()
    {
        using (var world = new RemodelWorld())
        {
            var asked = new List<(int Calls, bool BusyBefore, bool BusyAfter)>();
            world.Open();
            world.Options.BeginRun = begin =>
            {
                bool before = world.Host.RunInProgress;
                begin();
                asked.Add((world.Pipeline.Calls.Count, before, world.Host.RunInProgress));
                return null;
            };

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("remodel.planned", "p1");
            (int calls, bool busyBefore, bool busyAfter) = Assert.Single(asked);
            Assert.Equal(0, calls);
            Assert.False(busyBefore);
            Assert.True(busyAfter);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// A plan the gate refuses - a waiting restart that a turn holds back, say - is answered with
    /// the gate's own class, words and flag, and nothing else happens: no call, no run folder, no
    /// run recorded, and the host is left free.
    /// </summary>
    [Fact]
    public void APlanTheRestartGateRefusesIsAnsweredWithItsRefusalAndNothingHappens()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Options.BeginRun = begin =>
                new BackendRequestException("TurnRunning", "FICT the restart waits for a turn.", retryable: true);

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("TurnRunning", error.GetProperty("error_class").GetString());
            Assert.Equal("FICT the restart waits for a turn.", error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Empty(world.Pipeline.Calls);
            Assert.Empty(Directory.GetDirectories(world.RunRoot));
            Assert.Empty(world.Registered);
            Assert.Null(world.Host.LatestRun);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// A plan refused on the spot asks no gate: a press that could never plan makes no restart, and
    /// waits for none.
    /// </summary>
    [Theory]
    [InlineData("no document")]
    [InlineData("not a part")]
    [InlineData("no seat")]
    public void APlanRefusedOnTheSpotAsksNoRestartGate(string refusal)
    {
        using (var world = new RemodelWorld())
        {
            if (refusal == "no document")
            {
                world.Document = null;
            }
            else if (refusal == "not a part")
            {
                world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            }
            else
            {
                world.RemodelCapability = RemodelAvailability.Unavailable;
            }

            int asked = 0;
            world.Open();
            world.Options.BeginRun = begin =>
            {
                asked++;
                begin();
                return null;
            };

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("error", "p1");
            Assert.Equal(0, asked);
        }
    }

    /// <summary>
    /// Start likewise: the gate is asked once, after every refusal that needs no call and before
    /// `remodel.started`, and the run is marked in progress by its step.
    /// </summary>
    [Fact]
    public void AStartBeginsThroughTheRestartGateAfterItsOwnRefusals()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            var asked = new List<(int Started, bool BusyBefore, bool BusyAfter)>();
            world.Options.BeginRun = begin =>
            {
                bool before = world.Host.RunInProgress;
                begin();
                asked.Add((world.AllPosted("remodel.started").Length, before, world.Host.RunInProgress));
                return null;
            };

            world.Receive("remodel.start", "s1", new { run_dir = runDir });

            world.Reply("remodel.started", "s1");
            (int started, bool busyBefore, bool busyAfter) = Assert.Single(asked);
            Assert.Equal(0, started);
            Assert.False(busyBefore);
            Assert.True(busyAfter);
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// A Start the gate refuses is answered with the gate's refusal and the run never starts: no
    /// `remodel.started`, no run call, the plan still planned and startable once nothing holds the
    /// restart back. *Changed deliberately 2026-10-21 (owner decision 159A, 004 research R19):* the gate's
    /// `BackendUnavailable` that can be pressed again is in the tab's own words, where it carried the
    /// gate's own - a restart's failure can end in the backend's log's path - which is now in the host's log.
    /// </summary>
    [Fact]
    public void AStartTheRestartGateRefusesIsAnsweredWithItsRefusalAndTheRunNeverStarts()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
                new BackendRequestException("BackendUnavailable", "FICT the backend does not answer.", retryable: true);

            world.Receive("remodel.start", "s1", new { run_dir = runDir });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.BackendNotRestartedMessage, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Contains(world.Logged, line => line.Contains("FICT the backend does not answer."));
            Assert.Empty(world.AllPosted("remodel.started"));
            Assert.Equal(0, world.Pipeline.Count("run"));
            Assert.Equal(RemodelRunPhase.Planned, world.Host.LatestRun!.Phase);
            Assert.False(world.Host.RunInProgress);

            world.Options.BeginRun = allowed;
            world.Receive("remodel.start", "s2", new { run_dir = runDir });
            world.Reply("remodel.started", "s2");
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// Owner decision 159A (004 T208, a guard): only the gate's `BackendUnavailable` that can be pressed again - the
    /// restart failed, or the backend did not answer whether a turn runs - is told in the tab's own words. The gate's other
    /// refusals keep the words the review host writes for this tab, which name no path, with their class and flag: a remodel
    /// run in flight, and the add-in unloading, whose `BackendUnavailable` cannot be pressed again. A turn's is pinned by
    /// <see cref="APlanTheRestartGateRefusesIsAnsweredWithItsRefusalAndNothingHappens"/>.
    /// </summary>
    [Theory]
    [InlineData("RemodelRunning", true)]
    [InlineData("BackendUnavailable", false)]
    public void AGateRefusalThatIsNotTheRestartsKeepsTheReviewHostsWords(string errorClass, bool retryable)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            string words = $"FICT the review host's words for {errorClass}.";
            world.Options.BeginRun = begin => new BackendRequestException(errorClass, words, retryable);

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal(errorClass, error.GetProperty("error_class").GetString());
            Assert.Equal(words, error.GetProperty("message").GetString());
            Assert.Equal(retryable, error.GetProperty("retryable").GetBoolean());
            Assert.Empty(world.Pipeline.Calls);
        }
    }

    /// <summary>
    /// The gate can wait through a settings restart - seconds in which the host is not busy yet, so
    /// the tool service is free to re-attach, or a teardown to end the plan's session. Start reads
    /// the plan's session again once the host is busy, and refuses `SessionLost` before
    /// `remodel.started` and before any call, as it does when the loss came before the press
    /// (decision 22A): a run never starts on a session that went while the gate waited. Found by
    /// an independent review of 145A.
    /// </summary>
    [Theory]
    [InlineData("re-attach")]
    [InlineData("session ended")]
    public void APlansSessionLostWhileTheGateWaitsIsRefusedBeforeTheRunStarts(string loss)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            world.Options.BeginRun = begin =>
            {
                if (loss == "re-attach")
                {
                    world.Reattach(SecondAttachment);
                }
                else
                {
                    world.Host.SessionEnded(world.EndOutcome(copyClosed: true));
                }

                begin();
                return null;
            };

            world.Receive("remodel.start", "s1", new { run_dir = runDir });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("SessionLost", error.GetProperty("error_class").GetString());
            Assert.Equal(RemodelHost.SessionLostMessage, error.GetProperty("message").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());
            Assert.Empty(world.AllPosted("remodel.started"));
            Assert.Equal(0, world.Pipeline.Count("run"));
            Assert.Equal(RemodelRunPhase.Planned, world.Host.LatestRun!.Phase);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// A plan's session can go after the gate has marked the host busy - the tool service
    /// re-attached, or a teardown ended it - and the notice that the plan is lost waits while the
    /// host is busy (decision 24A). Start refuses the plan `SessionLost` and frees the host, and the
    /// notice is given then, as the end of a plan gives it: Start does not stay on for a plan that
    /// can no longer be started (owner decision 145A, found on review).
    /// </summary>
    [Theory]
    [InlineData("re-attach")]
    [InlineData("session ended")]
    public void APlanLostAfterTheGateMarkedTheHostIsAnnouncedOnceStartFreesIt(string loss)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            world.Options.BeginRun = begin =>
            {
                begin();
                if (loss == "re-attach")
                {
                    world.Reattach(SecondAttachment);
                }
                else
                {
                    world.Host.SessionEnded(world.EndOutcome(copyClosed: true));
                }

                return null;
            };

            world.Receive("remodel.start", "s1", new { run_dir = runDir });

            Assert.Equal("SessionLost", world.ErrorClass("s1"));
            JsonElement lost = Assert.Single(world.AllPosted("remodel.plan_lost"));
            Assert.Equal(runDir, lost.GetProperty("run_dir").GetString());
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// Anything that throws once the gate has marked the host busy, and before the run is handed to
    /// its scheduler, leaves the host free: busy for the rest of the SOLIDWORKS session, it would hold
    /// back every settings restart, and every new review with it (owner decision 145A, found on
    /// review). The plan stays planned and startable, nothing is left in flight for Stop, and a page
    /// already told `remodel.started` is told the run is over, by the status that ends a run.
    /// *Changed deliberately 2026-10-21 (owner decision 159A, 004 research R19):* that status is in the
    /// tab's own words, where it carried the failure's message, which is now in the host's log.
    /// </summary>
    [Theory]
    [InlineData("the attachment read")]
    [InlineData("the scheduler")]
    public void AStartThatFailsAfterTheGateLeavesTheHostFree(string failing)
    {
        const string Failure = "FICT the run could not be handed on";
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            Func<string?> attachment = world.Options.ToolServiceAttachment;
            Action<Action> schedule = world.Options.Schedule;
            if (failing == "the attachment read")
            {
                world.Options.BeginRun = begin =>
                {
                    begin();
                    world.Options.ToolServiceAttachment = () => throw new InvalidOperationException(Failure);
                    return null;
                };
            }
            else
            {
                world.Options.Schedule = work => throw new InvalidOperationException(Failure);
            }

            world.Receive("remodel.start", "s1", new { run_dir = runDir });

            Assert.False(world.Host.RunInProgress);
            Assert.Equal(RemodelRunPhase.Planned, world.Host.LatestRun!.Phase);
            Assert.Equal(0, world.Pipeline.Count("run"));
            if (failing == "the scheduler")
            {
                world.Reply("remodel.started", "s1");
                Assert.Contains(world.AllPosted("status"), status =>
                    status.GetProperty("stage").GetString() == "error"
                    && status.GetProperty("message").GetString() == RemodelHost.UnexpectedFailureMessage);
                Assert.Contains(world.Logged, line => line.Contains(Failure));
            }
            else
            {
                Assert.Empty(world.AllPosted("remodel.started"));
                Assert.Equal("HostError", world.ErrorClass("s1"));
            }

            world.Options.BeginRun = allowed;
            world.Options.ToolServiceAttachment = attachment;
            world.Options.Schedule = schedule;
            world.Receive("remodel.stop", "x1", new { });
            Assert.Equal("RunNotFound", world.ErrorClass("x1"));
            world.Receive("remodel.start", "s2", new { run_dir = runDir });
            world.Reply("remodel.started", "s2");
            Assert.Equal(1, world.Pipeline.Count("run"));
        }
    }

    /// <summary>
    /// A press whose gate will make a waiting settings restart first, or wait for one being made,
    /// says so before the gate: the restart can take seconds, up to the backend's handshake, in
    /// which the page would say only "Reading the part..." or "Running..." (owner decision 145A,
    /// found on review). One `status {stage: "backend_starting"}`, which the page writes into its run
    /// status line - a backend-lifecycle stage, never a run phase - in words for the press.
    /// </summary>
    [Theory]
    [InlineData("plan")]
    [InlineData("start")]
    public void APressThatMakesARestartFirstSaysSoBeforeTheGate(string press)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            string? runDir = null;
            if (press == "start")
            {
                world.Receive("remodel.plan", "p1", new { });
                runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            }

            int before = world.AllPosted("status").Length;
            int atTheGate = -1;
            world.Options.RestartAhead = () => true;
            world.Options.BeginRun = begin =>
            {
                atTheGate = world.AllPosted("status").Length;
                begin();
                return null;
            };

            if (press == "plan")
            {
                world.Receive("remodel.plan", "p2", new { });
            }
            else
            {
                world.Receive("remodel.start", "s1", new { run_dir = runDir });
            }

            JsonElement[] statuses = world.AllPosted("status");
            Assert.Equal(before + 1, atTheGate);
            Assert.Equal("backend_starting", statuses[before].GetProperty("stage").GetString());
            Assert.Equal(
                press == "plan"
                    ? "Waiting for the review backend to restart with the saved settings, then reading the part..."
                    : "Waiting for the review backend to restart with the saved settings, then starting the run...",
                statuses[before].GetProperty("message").GetString());
            Assert.Single(statuses, status => status.GetProperty("stage").GetString() == "backend_starting");
        }
    }

    /// <summary>
    /// A press with no restart before it says nothing of one; nor does one refused on the spot,
    /// which asks no gate; nor one whose reading of a restart ahead throws - the sentence is only
    /// words for the page, and the press goes on through the gate, which decides.
    /// </summary>
    [Theory]
    [InlineData("none ahead")]
    [InlineData("refused on the spot")]
    [InlineData("the reading throws")]
    public void APressSaysNothingOfARestartItWillNotMakeFirst(string why)
    {
        using (var world = new RemodelWorld())
        {
            if (why == "refused on the spot")
            {
                world.Document = null;
            }

            world.Open();
            world.Options.RestartAhead = why == "none ahead"
                ? () => false
                : why == "refused on the spot"
                    ? () => true
                    : () => throw new InvalidOperationException("FICT the review host cannot be asked");

            world.Receive("remodel.plan", "p1", new { });

            Assert.DoesNotContain(
                world.AllPosted("status"), status => status.GetProperty("stage").GetString() == "backend_starting");
            if (why == "refused on the spot")
            {
                Assert.Equal("NoDocument", world.ErrorClass("p1"));
            }
            else
            {
                world.Reply("remodel.planned", "p1");
            }
        }
    }

    /// <summary>
    /// The words a plan whose document changed while its gate waited is refused with: plain, and
    /// naming no path, as this tab's words never do.
    /// </summary>
    private const string DocumentChangedWords =
        "The active document or its configuration changed after Remodel a copy was pressed, so nothing was "
        + "copied and no new plan was made. Your part was not changed. Make your part the active document "
        + "and press Remodel a copy again.";

    /// <summary>
    /// Plan reads the active document before its gate, and the gate can wait through a settings
    /// restart - seconds, up to the backend's handshake - in which the engineer can make another
    /// document active. Plan reads it again once the host is busy, before any call, and refuses one
    /// that changed - another part, another configuration of the same part, or none at all -
    /// `DocumentChanged`, in plain words that name no path: nothing is probed, copied or closed, no
    /// folder is made, and the host is free (owner decision 145A, found on review). Its probe would
    /// read whatever was active by then, and the bridge would refuse the open as `scope_not_probed`,
    /// both paths in its words.
    /// </summary>
    [Theory]
    [InlineData("another part")]
    [InlineData("another configuration")]
    [InlineData("no document")]
    public void APlanWhoseDocumentChangedWhileTheGateWaitedIsRefusedBeforeAnyCall(string change)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Options.BeginRun = begin =>
            {
                world.Document = change == "another part"
                    ? new PageDocument(@"C:\parts\frame.SLDPRT", "Default")
                    : change == "another configuration"
                        ? new PageDocument(SourcePath, "Machined")
                        : null;
                begin();
                return null;
            };

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("DocumentChanged", error.GetProperty("error_class").GetString());
            Assert.Equal(DocumentChangedWords, error.GetProperty("message").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.DoesNotContain(@":\", DocumentChangedWords, StringComparison.Ordinal);
            Assert.Empty(world.Pipeline.Calls);
            Assert.Empty(Directory.GetDirectories(world.RunRoot));
            Assert.Empty(world.Registered);
            Assert.Null(world.Host.LatestRun);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// The refusal comes before the earlier plan waiting for Start is ended (004 T173): that plan
    /// is not closed, not marked lost and not announced lost, and Start still starts it.
    /// </summary>
    [Fact]
    public void APlanRefusedForADocumentChangedLeavesTheEarlierPlanAsItWas()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            int calls = world.Pipeline.Calls.Count;
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
            {
                world.Document = new PageDocument(@"C:\parts\frame.SLDPRT", "Default");
                begin();
                return null;
            };

            world.Receive("remodel.plan", "p2", new { });

            Assert.Equal("DocumentChanged", world.ErrorClass("p2"));
            Assert.Equal(calls, world.Pipeline.Calls.Count);
            Assert.Equal(0, world.Pipeline.Count("close"));
            Assert.Empty(world.AllPosted("remodel.plan_lost"));
            Assert.False(world.Host.LatestRun!.ClosedByPlanAgain);

            world.Options.BeginRun = allowed;
            world.Receive("remodel.start", "s1", new { run_dir = runDir });
            world.Reply("remodel.started", "s1");
        }
    }

    /// <summary>
    /// The document is the same one however its path is spelled: Windows names one file however it
    /// is cased, and the rule is the pane's one rule for "the same document"
    /// (<see cref="PageDocument.IsSameDocument(PageDocument)"/>). Such a plan goes ahead.
    /// </summary>
    [Fact]
    public void APlanWhoseDocumentIsTheSameHoweverItsPathIsSpelledGoesAhead()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Options.BeginRun = begin =>
            {
                world.Document = new PageDocument(SourcePath.ToUpperInvariant(), "Default");
                begin();
                return null;
            };

            world.Receive("remodel.plan", "p1", new { });

            world.Reply("remodel.planned", "p1");
        }
    }

    /// <summary>A Start refused on the spot - Start switched off in this build - asks no gate.</summary>
    [Fact]
    public void AStartRefusedOnTheSpotAsksNoRestartGate()
    {
        using (var world = new RemodelWorld { StartValidated = false })
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            string runDir = world.Reply("remodel.planned", "p1").GetProperty("run_dir").GetString()!;
            int asked = 0;
            world.Options.BeginRun = begin =>
            {
                asked++;
                begin();
                return null;
            };

            world.Receive("remodel.start", "s1", new { run_dir = runDir });

            Assert.Equal("StartNotValidated", world.Reply("error", "s1").GetProperty("error_class").GetString());
            Assert.Equal(0, asked);
        }
    }

    /// <summary>
    /// A gate that throws leaves the host free: the press is answered as a failure is, and a later
    /// plan goes ahead - one failure must not hold every later plan, and the settings restart that
    /// waits on the run, back for good.
    /// </summary>
    [Fact]
    public void ARestartGateThatThrowsLeavesTheHostFree()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
            {
                begin();
                throw new InvalidOperationException("FICT the gate broke");
            };

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("HostError", world.Reply("error", "p1").GetProperty("error_class").GetString());
            Assert.False(world.Host.RunInProgress);
            Assert.Empty(world.Pipeline.Calls);

            world.Options.BeginRun = allowed;
            world.Receive("remodel.plan", "p2", new { });
            world.Reply("remodel.planned", "p2");
        }
    }

    // ---- owner decision 154A: a run root on a share or reached through a link -----------

    /// <summary>
    /// Owner decision 154A (feature 002 T191; feature 011 research R12.9, items 1 and 2): a plan refuses a
    /// run root the run root rule refuses, first - before a run in progress, the document, the seat or a
    /// waiting settings restart is asked about - in the Remodel tab's words, which its page shows whole: what
    /// the root is, that nothing was copied, and the way on, a local folder chosen for runs in Settings on the
    /// Review tab, since this page has none (the reviews' F5), and Remodel a copy pressed again. The gate is
    /// not entered, nothing is asked of the pipeline - no probe of
    /// the part, no copy - no run folder is made, no status is posted, and no path reaches the page; an earlier
    /// plan waiting for Start is left as it is.
    /// </summary>
    [Theory]
    [MemberData(nameof(FakeRunRootProbe.RefusedKinds), MemberType = typeof(FakeRunRootProbe))]
    public void APlanRefusesARunRootTheRuleRefusesFirstAndMakesNothing(string kind)
    {
        using (var world = new RemodelWorld())
        {
            var refusing = FakeRunRootProbe.Refusing(kind, world.RunRoot);
            world.RunRootSpelling = refusing.RunRoot;
            world.Probe = refusing.Probe;
            world.Open();
            int gates = 0;
            world.Options.BeginRun = begin =>
            {
                gates++;
                begin();
                return null;
            };

            world.Receive("remodel.plan", "p1", new { });
            world.Document = null;
            world.Receive("remodel.plan", "p2", new { });

            foreach (string id in new[] { "p1", "p2" })
            {
                JsonElement error = world.Reply("error", id);
                Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
                Assert.False(error.GetProperty("retryable").GetBoolean());
                Assert.Equal(
                    RunRootRule.Refusal(
                        refusing.Verdict, "nothing was copied", RunRootRule.InSettingsOnTheReviewTab, "press Remodel a copy again"),
                    error.GetProperty("message").GetString());
            }

            Assert.Equal(0, gates);
            Assert.Empty(world.Pipeline.Calls);
            world.AssertNothingWasCopied();
            Assert.False(world.Host.RunInProgress);
            Assert.Null(world.Host.LatestRun);
            Assert.Empty(world.Registered);
            Assert.DoesNotContain(world.Posted, message => message.Contains("\"type\":\"status\""));
            Assert.DoesNotContain(world.Posted, message => message.Contains(Path.GetFileName(Path.GetDirectoryName(world.RunRoot)!)));
        }
    }

    /// <summary>
    /// A Start refuses a run root the rule refuses as a plan does, in the Remodel tab's words - the plan was
    /// not applied - before the run it names is looked up, and begins nothing: the gate is not entered, the
    /// run is not handed to the pipeline, the plan stays planned and startable once the root is accepted
    /// again. Here the rule's answer changes after the plan, as a run folder whose root was replaced by a link
    /// would; the faked drive goes from local to a substituted one.
    /// </summary>
    [Fact]
    public void AStartRefusesARunRootTheRuleRefusesAndBeginsNothing()
    {
        using (var world = new RemodelWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            RemodelRun planned = world.Host.LatestRun!;
            List<string> callsBefore = world.Pipeline.Calls.ToList();
            int gates = 0;
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
            {
                gates++;
                return allowed(begin);
            };

            probe.Substitutes[world.RunRoot.Substring(0, 2)] = @"C:\Fictional\work";
            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });
            world.Receive("remodel.start", "s2", new { run_dir = @"C:\Fictional\no-such-run" });

            foreach (string id in new[] { "s1", "s2" })
            {
                JsonElement error = world.Reply("error", id);
                Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
                Assert.False(error.GetProperty("retryable").GetBoolean());
                Assert.Equal(
                    RunRootRule.Refusal(
                        RunRootVerdict.Link, "the plan was not applied", RunRootRule.InSettingsOnTheReviewTab, "press Remodel a copy again"),
                    error.GetProperty("message").GetString());
            }

            Assert.Equal(0, gates);
            Assert.Equal(callsBefore, world.Pipeline.Calls);
            Assert.DoesNotContain(world.Posted, message => message.Contains("\"type\":\"remodel.started\""));
            Assert.Equal(RemodelRunPhase.Planned, planned.Phase);
            Assert.False(world.Host.RunInProgress);

            probe.Substitutes.Clear();
            world.Receive("remodel.start", "s3", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s3");
        }
    }

    // ---- the reviews of decision 154A: a run root moved inside a session (F6, N8) ------------------------

    /// <summary>
    /// The reviews' finding F6: a re-modeler's copy made under a run root a save has since moved is still one
    /// of the re-modeler's own copies - every run root in force this session is read - so 004's T173 guard
    /// holds: a plan of it is refused as a copy, before anything is asked of the pipeline.
    /// </summary>
    [Fact]
    public void ACopyMadeUnderAnEarlierRunRootIsStillRefusedAsASource()
    {
        using (var world = new RemodelWorld())
        {
            string earlier = Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "earlier", "runs");
            world.Open();
            world.Options.RunRootsInForce = () => new[] { earlier, world.RunRoot };
            world.Document = new PageDocument(
                Path.Combine(earlier, "20260915-090000-bracket-remodel", "copy", "bracket-RMS.SLDPRT"), "Default");

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("SourceIsRemodelCopy", error.GetProperty("error_class").GetString());
            Assert.Empty(world.Pipeline.Calls);
            world.AssertNothingWasCopied();
        }
    }

    /// <summary>
    /// The reviews' finding F6: a Start hands the backend the plan's own run folder, and the backend makes runs
    /// only under the run root it was started with - so a plan made under a run root a save has since moved is
    /// refused before the run begins, in plain words with the way on: plan again. Nothing is started, and the
    /// plan stays as it was.
    /// </summary>
    [Fact]
    public void AStartOfAPlanMadeUnderAnEarlierRunRootIsRefusedAndBeginsNothing()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            RemodelRun planned = world.Host.LatestRun!;
            world.RunRootSpelling = Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "moved", "runs");

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("RunRootChanged", error.GetProperty("error_class").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(
                "this plan's run folder is under a run root that is no longer in force, and the backend makes runs "
                + "only under the one in force, so the plan was not applied. Press Remodel a copy again.",
                error.GetProperty("message").GetString());
            Assert.DoesNotContain(world.Posted, message => message.Contains("\"type\":\"remodel.started\""));
            Assert.Equal(RemodelRunPhase.Planned, planned.Phase);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// The reviews' N8: a plan judges the run root in force before it does anything, and the gate then makes a
    /// waiting settings restart, which can bring another into force; the plan judges that one again before it
    /// asks the pipeline anything or makes its run folder there. Here the gate brings in a run root on a
    /// network drive.
    /// </summary>
    [Fact]
    public void APlanJudgesAgainTheRunRootTheGateBringsIn()
    {
        using (var world = new RemodelWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            probe.Drives[@"Y:\"] = RunRootDrive.Network;
            world.Probe = probe;
            world.Open();
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
            {
                world.RunRootSpelling = @"Y:\Fictional\runs";
                return allowed(begin);
            };

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
            Assert.Equal(
                RunRootRule.Refusal(
                    RunRootVerdict.Share, "nothing was copied", RunRootRule.InSettingsOnTheReviewTab, "press Remodel a copy again"),
                error.GetProperty("message").GetString());
            Assert.Empty(world.Pipeline.Calls);
            Assert.False(world.Host.RunInProgress);
            world.AssertNothingWasCopied();
        }
    }

    /// <summary>...and a Start judges again too, before the run begins: the plan stays planned.</summary>
    [Fact]
    public void AStartJudgesAgainTheRunRootTheGateBringsIn()
    {
        using (var world = new RemodelWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            probe.Drives[@"Y:\"] = RunRootDrive.Network;
            world.Probe = probe;
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            RemodelRun planned = world.Host.LatestRun!;
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
            {
                world.RunRootSpelling = @"Y:\Fictional\runs";
                return allowed(begin);
            };

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
            Assert.Equal(
                RunRootRule.Refusal(
                    RunRootVerdict.Share, "the plan was not applied", RunRootRule.InSettingsOnTheReviewTab, "press Remodel a copy again"),
                error.GetProperty("message").GetString());
            Assert.DoesNotContain(world.Posted, message => message.Contains("\"type\":\"remodel.started\""));
            Assert.Equal(RemodelRunPhase.Planned, planned.Phase);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// Owner decision 152A merged with 154A (feature 002 T225): a plan whose gate brings in a run root the rule
    /// refuses is refused `RunRootRefused`, its way on a local folder for runs, before it takes its hold on the
    /// tool service - whether or not one is to be had: 154A judges the run root before anything is asked or made
    /// under it, and the hold asks the tool service (corrected on the final reviews, N1).
    /// </summary>
    [Theory]
    [InlineData("a hold to be had")]
    [InlineData("no hold to be had")]
    public void APlanWhoseGateBringsInARefusedRunRootIsRefusedForThatBeforeItHoldsTheToolService(string hold)
    {
        using (var world = new RemodelWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            probe.Drives[@"Y:\"] = RunRootDrive.Network;
            world.Probe = probe;
            var holds = new CountedHolds();
            world.Hold = hold == "a hold to be had" ? holds.Take : () => null;
            world.Open();
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
            {
                world.RunRootSpelling = @"Y:\Fictional\runs";
                return allowed(begin);
            };

            world.Receive("remodel.plan", "p1", new { });

            Assert.Equal("RunRootRefused", world.Reply("error", "p1").GetProperty("error_class").GetString());
            Assert.Equal(0, holds.Taken);
            Assert.Empty(world.Pipeline.Calls);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// ...and a Start of a plan made under a run root a save has since moved is refused `RunRootChanged`, its way
    /// on a plan again, before it takes its hold - whether or not one is to be had, when it would otherwise be
    /// refused as a session lost. The plan stays planned.
    /// </summary>
    [Theory]
    [InlineData("a hold to be had")]
    [InlineData("no hold to be had")]
    public void AStartOfAPlanMadeUnderAnEarlierRunRootIsRefusedForThatBeforeItHoldsTheToolService(string hold)
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            RemodelRun planned = world.Host.LatestRun!;
            var holds = new CountedHolds();
            world.Hold = hold == "a hold to be had" ? holds.Take : () => null;
            world.RunRootSpelling = Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "moved", "runs");

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            Assert.Equal("RunRootChanged", world.Reply("error", "s1").GetProperty("error_class").GetString());
            Assert.Equal(0, holds.Taken);
            Assert.Empty(world.AllPosted("remodel.started"));
            Assert.Equal(RemodelRunPhase.Planned, planned.Phase);
            Assert.False(world.Host.RunInProgress);
        }
    }

    /// <summary>
    /// Owner decision 154A, with 153A's record of the settings in force (feature 002 T201): a plan's gate holds
    /// back every settings restart, but not the add-in's first start of the backend, which can be under way once the
    /// gate is passed. While one that would bring another run root into force is, the plan is refused before
    /// anything is asked of the pipeline or made, `BackendUnavailable`, retryable, in this tab's words - the plan's
    /// calls would go to a backend started with another run root than the one its folder would be made under - and
    /// the host is left free.
    /// </summary>
    [Fact]
    public void APlanIsRefusedWhileAStartOfTheBackendWouldBringAnotherRunRootIn()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            int gates = 0;
            Func<Action, BackendRequestException?> allowed = world.Options.BeginRun;
            world.Options.BeginRun = begin =>
            {
                gates++;
                return allowed(begin);
            };
            world.Options.RunRootForANewRun = () => null;

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(
                RunRootRule.MovingRefusal("nothing was copied", "press Remodel a copy again"),
                error.GetProperty("message").GetString());
            Assert.Equal(1, gates);
            Assert.Empty(world.Pipeline.Calls);
            Assert.False(world.Host.RunInProgress);
            world.AssertNothingWasCopied();
        }
    }

    /// <summary>
    /// ...and so is a Start, once its gate is passed and before the run begins: the plan stays planned, and can be
    /// started once the start has ended.
    /// </summary>
    [Fact]
    public void AStartIsRefusedWhileAStartOfTheBackendWouldBringAnotherRunRootIn()
    {
        using (var world = new RemodelWorld())
        {
            world.Open();
            world.Receive("remodel.plan", "p1", new { });
            world.Reply("remodel.planned", "p1");
            RemodelRun planned = world.Host.LatestRun!;
            world.Options.RunRootForANewRun = () => null;

            world.Receive("remodel.start", "s1", new { run_dir = world.ExpectedRunDirectory });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(
                RunRootRule.MovingRefusal("the plan was not applied", "press Remodel a copy again"),
                error.GetProperty("message").GetString());
            Assert.DoesNotContain(world.Posted, message => message.Contains("\"type\":\"remodel.started\""));
            Assert.Equal(RemodelRunPhase.Planned, planned.Phase);
            Assert.False(world.Host.RunInProgress);

            world.Options.RunRootForANewRun = () => world.RunRoot;
            world.Receive("remodel.start", "s2", new { run_dir = world.ExpectedRunDirectory });
            world.Reply("remodel.started", "s2");
        }
    }

    /// <summary>
    /// The reviews of 154A's merge, N4 (feature 002 T204): under a run root in force that the rule refuses, with a
    /// folder chosen for runs in the Review tab's Settings that is not in force - its save's restart failed - a plan
    /// is refused `RunRootChosenNotInForce`, not retryable, in this tab's words: the folder chosen is not in force
    /// until the review backend restarts with it, and the way on is to save the settings again to retry the restart -
    /// not to choose a local folder, which the engineer has just done. Nothing is asked of the pipeline or copied,
    /// and no path reaches the page.
    /// </summary>
    [Fact]
    public void UnderARefusedRunRootAFolderChosenNotInForceIsToldWithTheWayOnToRetryTheRestart()
    {
        using (var world = new RemodelWorld())
        {
            var refusing = FakeRunRootProbe.Refusing("on a share", world.RunRoot);
            world.RunRootSpelling = refusing.RunRoot;
            world.Probe = refusing.Probe;
            world.Open();
            world.Options.RunRootSaved = () => Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "FICT-chosen", "runs");

            world.Receive("remodel.plan", "p1", new { });

            JsonElement error = world.Reply("error", "p1");
            Assert.Equal("RunRootChosenNotInForce", error.GetProperty("error_class").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(
                RunRootRule.ChosenNotInForceRefusal(
                    refusing.Verdict, "nothing was copied", RunRootRule.InSettingsOnTheReviewTab, "press Remodel a copy again"),
                error.GetProperty("message").GetString());
            Assert.Empty(world.Pipeline.Calls);
            Assert.False(world.Host.RunInProgress);
            Assert.DoesNotContain(world.Posted, message => message.Contains("FICT-chosen"));
            world.AssertNothingWasCopied();
        }
    }

    private sealed class RemodelWorld : IDisposable
    {
        private readonly string _root;
        private readonly List<Action> _looks = new List<Action>();
        private RemodelHost? _host;
        private RemodelHostOptions? _options;
        private ToolServiceGate? _gate;
        private int _services;

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

        /// <summary>The world's own folder, for a case that needs a file of its own beside the run root.</summary>
        public string Root => _root;

        public string RunRoot { get; }

        /// <summary>The run root as the setting spells it, when not <see cref="RunRoot"/> (owner decision 154A).</summary>
        public string? RunRootSpelling { get; set; }

        /// <summary>
        /// Owner decision 159A (004 research R22): the run root in force as the review host's real settings restart records
        /// it, read per call, when a case wires that restart (<see cref="RunRootRestart"/>); unset, the spelling or
        /// <see cref="RunRoot"/>. Set before <see cref="Open"/>.
        /// </summary>
        public Func<string>? RunRootInForce { get; set; }

        /// <summary>
        /// What the run root rule reads (owner decision 154A); when null, a probe that answers every folder as a
        /// local one reached by its own path - not Windows, so a temp folder below a junction on a developer's
        /// machine fails no test that is not about the rule (the reviews' N11).
        /// </summary>
        public IRunRootProbe? Probe { get; set; }

        /// <summary>What `log.open` opens; settable so a case can name one that cannot be made (owner decision 159A).</summary>
        public string LogFolder { get; set; }

        /// <summary>
        /// Owner decision 159A: every line the host wrote to its log (<see cref="RemodelHostOptions.Log"/>), in order -
        /// what a failure said where the tab told it in its own words.
        /// </summary>
        public List<string> Logged { get; } = new List<string>();

        public PageDocument? Document { get; set; } = new PageDocument(SourcePath, "Default");

        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(51234, "0FAKEtoken");

        public FakePipeline Pipeline { get; } = new FakePipeline();

        public bool UsePipeline { get; set; } = true;

        public RemodelAvailability RemodelCapability { get; set; } = RemodelAvailability.Available;

        /// <summary>
        /// The Start switch the host is built with (004 T172). On here, because most of what
        /// this suite drives is a Start a validated build answers; the switch's own cases build
        /// their host with it off, or with the shipped <see cref="RemodelStart.SeatValidated"/>.
        /// </summary>
        public bool StartValidated { get; set; } = true;

        /// <summary>The options the host was built with, read by the host per message.</summary>
        public RemodelHostOptions Options =>
            _options ?? throw new InvalidOperationException("call Open() first");

        /// <summary>
        /// The tool-service attachment listening now, as `ToolServiceGate.Attachment` answers
        /// it: a pipe name, and null while none is. Changing it is a re-attach (decision 22A).
        /// </summary>
        public string? Attachment { get; set; } = FirstAttachment;

        /// <summary>
        /// Every time the host asked which attachment is listening: whether it was busy then,
        /// and how many pipeline calls had been made, so a test can pin <b>when</b> a plan
        /// reads it.
        /// </summary>
        public List<(bool Busy, int PipelineCalls)> AttachmentReads { get; } =
            new List<(bool Busy, int PipelineCalls)>();

        public FakeResolver Resolver { get; } = new FakeResolver();

        public RecordingOpener Opener { get; } = new RecordingOpener();

        public List<string> Posted { get; } = new List<string>();

        /// <summary>
        /// Owner decision 155A: what the page does the moment a message reaches it, run after the message
        /// is collected - a press made as soon as the page offers it.
        /// </summary>
        public Action<JsonElement>? WhenPosted { get; set; }

        /// <summary>
        /// Owner decision 155A: the channel the host is built with, when a case needs one of its own;
        /// null builds the collecting channel over <see cref="Posted"/>.
        /// </summary>
        public IPageChannel? Channel { get; set; }

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
            _options = new RemodelHostOptions(
                Channel ?? new CollectingChannel(Posted, root => WhenPosted?.Invoke(root)), () => RunRootInForce?.Invoke() ?? RunRootSpelling ?? RunRoot)
            {
                Backend = () => Endpoint,
                CurrentDocument = () => Document,
                RemodelAvailability = () => RemodelCapability,
                ToolServiceAttachment = () =>
                {
                    AttachmentReads.Add((Host.RunInProgress, Pipeline.Calls.Count));
                    return _gate != null ? _gate.Attachment : Attachment;
                },
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
                Schedule = Scheduler ?? (work => work()),

                // Owner decision 152A, on the Codex review (X2): the gate's hold once one is
                // attached, as the add-in wires it, and nothing to hold before.
                HoldToolService = () => Hold != null ? Hold() : _gate != null ? _gate.HoldAttachment(ToolServiceHolder.Remodel) : ToolServiceHold.Nothing,

                // Owner decision 159A: the host's log, collected, where the add-in writes it to its own.
                Log = line =>
                {
                    lock (Logged)
                    {
                        Logged.Add(line);
                    }
                },
            };
            _options.RunRootProbe = Probe ?? FakeRunRootProbe.Local();

            _host = new RemodelHost(_options, StartValidated);
        }

        public void Receive(string type, string id, object payload) =>
            Host.Receive(JsonSerializer.Serialize(new { type, id, payload }));

        /// <summary>
        /// What the add-in's gate callback does each time the gate publishes a service or
        /// withdraws one (`SwReviewAddIn.CreateToolServiceGate`): the attachment listening is
        /// now <paramref name="attachment"/> - null for a withdrawal - and the host is refreshed.
        /// </summary>
        public void Publish(string? attachment)
        {
            Attachment = attachment;
            Host.RefreshAvailability();
        }

        /// <summary>
        /// One re-attach as the gate performs it: the old service withdrawn, then the new one
        /// listening under <paramref name="next"/>. Two refreshes, as `ToolServiceWiringTests`
        /// pins the gate publishing them.
        /// </summary>
        public void Reattach(string next)
        {
            Publish(null);
            Publish(next);
        }

        /// <summary>
        /// A real <see cref="ToolServiceGate"/> over <see cref="FakeToolService"/>s, wired to this
        /// host the way `SwReviewAddIn.CreateToolServiceGate` wires the add-in's: its publish
        /// callback refreshes the host, its busy question is
        /// <see cref="RemodelHost.RunInProgress"/>, and from here on the attachment the host
        /// reads is the gate's. It starts inline, so an assertion can follow the call.
        /// </summary>
        public List<string> Lifecycle { get; } = new List<string>();

        public IToolService? PublishedService { get; private set; }

        public string? AttachmentNow => _gate != null ? _gate.Attachment : Attachment;

        /// <summary>
        /// What the host holds the tool service with, when a case answers it itself (owner decision
        /// 152A, on the Codex review: X2); unset, the attached gate's hold, and nothing with no gate.
        /// </summary>
        public Func<IDisposable?>? Hold { get; set; }

        /// <summary>Where a Start's run executes, when not inline: a case that keeps it to run later.</summary>
        public Action<Action>? Scheduler { get; set; }

        public bool KeepCopyAttachment(string path, string? attachment)
        {
            // Compile against the pre-fix public surface, then exercise the optional seam when present.
            System.Reflection.MethodInfo? keep = typeof(RemodelHost).GetMethod("KeepCopyAttachment");
            return keep != null && (bool)keep.Invoke(Host, new object?[] { path, attachment })!;
        }

        private void RefreshLifecycleAvailability(bool announce)
        {
            System.Reflection.MethodInfo? refresh = typeof(RemodelHost).GetMethod(
                "RefreshAvailability", new[] { typeof(bool) });
            if (refresh == null) Host.RefreshAvailability();
            else refresh.Invoke(Host, new object[] { announce });
        }

        public RemodelSessionEnd EndOutcome(bool copyClosed, RemodelRun? run = null)
        {
            run = run ?? Host.LatestRun!;
            return new RemodelSessionEnd(
                RemodelSessionEnd.ReasonToolServiceStopped, run.RunDirectory, run.CopyPath,
                verified: true, failedCheck: null, tagRemoved: true, copyClosed: copyClosed,
                settingsOutstanding: new string[0],
                failures: copyClosed ? new string[0] : new[] { "fictional copy remains open" });
        }

        /// <summary>
        /// How many looks again the gate has asked for and none has run yet (owner decision 152A):
        /// the add-in's gate runs each a poll later, and this world keeps it until a case runs it.
        /// </summary>
        public int LooksWaiting => _looks.Count;

        /// <summary>Runs every look waiting now, as the polls coming due would; a look asked for meanwhile waits.</summary>
        public void RunLooks()
        {
            Action[] due = _looks.ToArray();
            _looks.Clear();
            foreach (Action look in due)
            {
                look();
            }
        }

        /// <param name="turnQuery">The second half of the add-in's busy question, asked after the run:
        /// whether a turn may be running - a round trip per open chat, which a case can make take as
        /// long as it needs (owner decision 152A, on the Codex review: X2). None by default.</param>
        public ToolServiceGate AttachLifecycleGate(
            Action? cleanup = null, Action<Action>? scheduler = null, Func<bool>? turnQuery = null)
        {
            Func<PageDocument?> document = () => Document;
            Func<IToolService> start = () => new FakeToolService(++_services, Document!.Path, Document!.Configuration)
            {
                DuringDispose = () =>
                {
                    Lifecycle.Add("dispose");
                    cleanup?.Invoke();
                },
            };
            Action<IToolService?> publish = service =>
            {
                PublishedService = service;
                Lifecycle.Add(service == null ? "withdraw" : "publish");
                RefreshLifecycleAvailability(service != null);
            };
            Action<string, Exception?> report = (what, failure) => { };
            Action<Action> schedule = scheduler ?? (work => work());
            Func<bool> busy = () => Host.RunInProgress || (turnQuery != null && turnQuery());
            Func<string, string, bool> preserve = (path, attachment) => KeepCopyAttachment(path, attachment);
            Action<IToolService> stopped = _ =>
            {
                Lifecycle.Add("stopped");
                RefreshLifecycleAvailability(true);
            };
            _gate = new ToolServiceGate(
                document,
                start,
                publish,
                report,
                schedule,
                busy,
                preserveAttachment: preserve,
                afterStopped: stopped,
                later: look => _looks.Add(look));
            return _gate;
        }

        public ToolServiceGate AttachGate()
        {
            _gate = new ToolServiceGate(
                () => Document,
                () => new FakeToolService(++_services, Document!.Path, Document!.Configuration),
                _ => Host.RefreshAvailability(),
                (what, failure) => { },
                schedule: work => work(),
                busy: () => Host.RunInProgress,
                later: look => _looks.Add(look),
                clock: () => GateClock);
            return _gate;
        }

        /// <summary>
        /// The time on the clock <see cref="AttachGate"/>'s gate reads its holds' ages off (owner decision
        /// 158A). It stands still until a case moves it.
        /// </summary>
        public TimeSpan GateClock { get; set; }

        /// <summary>
        /// SOLIDWORKS makes <paramref name="path"/> the active document, or switches it to
        /// <paramref name="configuration"/>, and the add-in fans it out as it does: every tab's
        /// `document.changed` first, then the gate follows the document
        /// (`SwReviewAddIn.TellEveryTabTheDocumentChanged`).
        /// </summary>
        public void SwitchTo(ToolServiceGate gate, string path, string? configuration = "Default")
        {
            Document = new PageDocument(path, configuration);
            Host.DocumentChanged();
            gate.FollowDocument(path);
        }

        /// <summary>The types posted from <paramref name="index"/> on, in the order the page receives them.</summary>
        public string[] TypesPostedSince(int index) => Posted
            .Skip(index)
            .Select(message => JsonDocument.Parse(message).RootElement.GetProperty("type").GetString()!)
            .ToArray();

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

        /// <summary>
        /// Makes the engineer's part a real file, named as <see cref="SourcePath"/> is, and the
        /// active document, so a test can show a message left it byte for byte and time for time
        /// as it was. Returns its path.
        /// </summary>
        public string CreateSourceFile()
        {
            string folder = Path.Combine(_root, "parts");
            Directory.CreateDirectory(folder);
            string source = Path.Combine(folder, Path.GetFileName(SourcePath));
            File.WriteAllText(source, "the engineer's part");
            Document = new PageDocument(source, "Default");
            return source;
        }

        /// <summary>
        /// Every file under <paramref name="directory"/>, with its bytes and its last write, in
        /// one comparable string per file: two snapshots are equal only if nothing under it was
        /// created, deleted, rewritten or touched.
        /// </summary>
        public static string[] Snapshot(string directory) =>
            Directory.GetFiles(directory, "*", SearchOption.AllDirectories)
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                .Select(path => path.Substring(directory.Length)
                    + " " + Convert.ToBase64String(File.ReadAllBytes(path))
                    + " " + File.GetLastWriteTimeUtc(path).Ticks)
                .ToArray();

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

    /// <summary>
    /// Owner decision 155A: a page channel two threads post to - the host's message thread and its run -
    /// which collects every message under a lock and runs <c>beforePosted</c> on the posting thread first,
    /// so a case can hold one post where it is made.
    /// </summary>
    private sealed class PausingChannel : IPageChannel
    {
        private readonly List<string> _posted;
        private readonly Action<string> _beforePosted;

        public PausingChannel(List<string> posted, Action<string> beforePosted)
        {
            _posted = posted;
            _beforePosted = beforePosted;
        }

        public void PostMessage(string json)
        {
            _beforePosted(json);
            lock (_posted)
            {
                _posted.Add(json);
            }
        }
    }

    /// <summary>A page that is gone: every post throws.</summary>
    private sealed class ThrowingChannel : IPageChannel
    {
        public void PostMessage(string json) =>
            throw new InvalidOperationException("the Remodel page is gone");
    }

    private sealed class CollectingChannel : IPageChannel
    {
        private static readonly IReadOnlyCollection<string> Stages =
            RemodelPageFiles.StatusStages();

        private readonly List<string> _posted;

        private readonly Action<JsonElement>? _whenPosted;

        public CollectingChannel(List<string> posted, Action<JsonElement>? whenPosted = null)
        {
            _posted = posted;
            _whenPosted = whenPosted;
        }

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
            _whenPosted?.Invoke(root);
        }
    }

    /// <summary>
    /// Everything the host asks SOLIDWORKS and the executor for, with nothing behind it.
    ///
    /// <see cref="Opened"/> is the load-bearing field: it holds every path this fake was asked
    /// to open <b>as a document</b>, and the source's path must never appear in it.
    /// </summary>
    /// <summary>
    /// Owner decision 159A (004 T277; research R22): the review host's real settings restart, wired to a
    /// <see cref="RemodelWorld"/> as `SwReviewAddIn` wires the two - the Remodel host's run roots, its restart gate and its
    /// busy reading are the review host's, and the review host's cleanup before a restart that moves the run root is the
    /// Remodel host's - over a backend whose run root is the one its last start was made with, which the world's fake
    /// pipeline judges every run folder against, as `resolve_run_dir` does. It opens the world. The watcher's poll is long,
    /// so nothing happens on another thread.
    /// </summary>
    private sealed class RunRootRestart : IDisposable
    {
        private readonly List<string> _posted = new List<string>();

        public RunRootRestart(RemodelWorld world)
        {
            NewRoot = Path.Combine(world.Root, "moved", "runs");
            string settingsPath = Path.Combine(world.Root, "settings.json");
            UserSettings settings = UserSettings.Defaults();
            settings.RunRoot = world.RunRoot;
            settings.Save(settingsPath);
            Backend = new RootBackend(world.RunRoot, () => world.Pipeline.SessionOpen);
            Review = new ReviewHost(new ReviewHostOptions(new ListChannel(_posted), Backend, settingsPath)
            {
                BuildMode = BuildMode.Development,
                LogFolder = Path.Combine(world.Root, "review-logs"),
                RestartPoll = TimeSpan.FromMinutes(10),
                RunRootProbe = FakeRunRootProbe.Local(),
                BackendBusy = () => world.Host.RunInProgress,
                EndRemodelSessionsLeftUnder = runRoot => world.Host.EndTheSessionsLeftUnder(runRoot),
                BackendRestarted = () => world.Host.BackendRestarted(),
            });

            world.RunRootInForce = () => Review.RunRoot;
            world.Open();
            world.Options.RunRootsInForce = () => Review.RunRootsInForce;
            world.Options.RunRootForANewRun = Review.RunRootForANewRun;
            world.Options.RunRootSaved = () => Review.Settings.RunRoot;
            world.Options.BeginRun = Review.BeginRemodelRun;
            world.Options.RestartAhead = () => Review.RestartAhead;
            world.Pipeline.BackendRunRoot = () => Backend.Down ? null : Backend.StartedRoot;
        }

        /// <summary>Run root B, the one a save chooses; nothing is made in it until the backend is started with it.</summary>
        public string NewRoot { get; }

        public RootBackend Backend { get; }

        public ReviewHost Review { get; }

        /// <summary>A settings save on the Review tab, choosing <paramref name="runRoot"/> for runs, or keeping the run root when null.</summary>
        public void Save(string id, string? runRoot)
        {
            var payload = new Dictionary<string, object?>
            {
                { "provider", "openai" },
                { "model", "gpt-5.6" },
                { "effort", "low" },
                { "api_key", null },
                { "base_url", null },
                { "gemini_enterprise", null },
            };
            if (runRoot != null)
            {
                payload["run_root"] = runRoot;
            }

            Review.Receive(JsonSerializer.Serialize(new { type = "settings.save", id, payload }));
        }

        /// <summary>The single reply of <paramref name="type"/> the Review page was sent for <paramref name="id"/>.</summary>
        public JsonElement Reply(string type, string id)
        {
            JsonElement[] matches = Messages()
                .Where(root => root.GetProperty("type").GetString() == type
                    && root.TryGetProperty("id", out JsonElement replyId)
                    && replyId.ValueKind == JsonValueKind.String
                    && replyId.GetString() == id)
                .Select(root => root.GetProperty("payload").Clone())
                .ToArray();
            Assert.True(matches.Length == 1, $"expected one '{type}' reply to '{id}', saw {matches.Length}: " + string.Join(" | ", Snapshot()));
            return matches[0];
        }

        /// <summary>The words of the last `status` the Review page was sent, or null with none.</summary>
        public string? LastStatus() => Messages()
            .Where(root => root.GetProperty("type").GetString() == "status")
            .Select(root => root.GetProperty("payload").GetProperty("message").GetString())
            .LastOrDefault();

        public void Dispose() => Review.Dispose();

        private string[] Snapshot()
        {
            lock (_posted)
            {
                return _posted.ToArray();
            }
        }

        private IEnumerable<JsonElement> Messages() => Snapshot().Select(message => JsonDocument.Parse(message).RootElement);
    }

    /// <summary>A page that keeps what it is sent, from any thread.</summary>
    private sealed class ListChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public ListChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json)
        {
            lock (_posted)
            {
                _posted.Add(json);
            }
        }
    }

    /// <summary>
    /// The review backend as <see cref="RunRootRestart"/> needs it (owner decision 159A, 004 research R22): up from the start
    /// under the run root it was started with, a restart refused while a turn runs, as <c>BackendSupervisor.Restart</c>
    /// refuses it before it stops anything, and otherwise a new backend under the restart's run root.
    /// </summary>
    private sealed class RootBackend : IBackendClient
    {
        private readonly Func<bool> _sessionOpen;
        private int _generation;

        public RootBackend(string runRoot, Func<bool> sessionOpen)
        {
            StartedRoot = runRoot;
            _sessionOpen = sessionOpen;
        }

        /// <summary>The run root the backend that is up was started with.</summary>
        public string StartedRoot { get; private set; }

        /// <summary>No backend process: the old one exited, and nothing answers.</summary>
        public bool Down { get; set; }

        /// <summary>Whether every chat has a turn running.</summary>
        public bool TurnRunning { get; set; }

        /// <summary>Runs inside the model-list round trip a save makes between its own check and its restart.</summary>
        public Action? DuringModelList { get; set; }

        /// <summary>The settings of every restart made, in order.</summary>
        public List<UserSettings> Restarts { get; } = new List<UserSettings>();

        /// <summary>Whether the fake bridge held a session as each restart stopped the old backend.</summary>
        public List<bool> SessionOpenAtEachRestart { get; } = new List<bool>();

        public BackendEndpoint? Endpoint => Down ? null : new BackendEndpoint(53000 + _generation, "FICT-review-token-" + _generation);

        public IReadOnlyList<ModelChoice> ListModels(string provider)
        {
            DuringModelList?.Invoke();
            return new ModelChoice[0];
        }

        public bool IsTurnRunning(string chatId) => TurnRunning;

        public ChatSessionHandle CreateSession(NewSessionRequest request) =>
            throw new BackendRequestException("BackendUnavailable", "FICT no review is made here.", retryable: true);

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
            if (TurnRunning)
            {
                throw new TurnRunningException();
            }

            SessionOpenAtEachRestart.Add(_sessionOpen());
            Restarts.Add(settings);
            StartedRoot = settings.RunRoot;
            _generation++;
            Down = false;
        }
    }

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

        /// <summary>What <see cref="Plan"/> throws after the copy exists - the dump's, or the planner's.</summary>
        public Exception? PlanFailure { get; set; }

        public Exception? RunFailure { get; set; }

        public Exception? ActivateFailure { get; set; }

        public string PlanSummaryJson { get; set; } = "{\"moves\":3}";

        public Action<IRemodelRunReporter>? DuringRun { get; set; }

        /// <summary>Runs inside <see cref="Plan"/>, after the copy exists and before it answers.</summary>
        public Action? DuringPlan { get; set; }

        public string RunState { get; set; } = "saved";

        public int ChangesApplied { get; set; }

        public string? CopyPath { get; private set; }

        public int Count(string call) => Calls.Count(name => name == call);

        public RemodelScopeReading ProbeScope()
        {
            Calls.Add("probe");
            DuringProbe?.Invoke();
            if (ProbeFailure != null)
            {
                throw ProbeFailure;
            }

            return new RemodelScopeReading(Signals, Refusals);
        }

        /// <summary>
        /// 004 T175: when true, this fake keeps the one remodel session a bridge dispatcher holds,
        /// as <c>remodel.open</c> and <c>remodel.close</c> keep it: an open that answered opens it,
        /// a close the bridge answered ends it, and an open while it is open is refused
        /// <c>RunInProgress</c> as the bridge's <c>run_in_progress</c> is. Off by default, because
        /// most cases here re-attach by changing the attachment, which in the product throws the
        /// session away with the old dispatcher and which this fake does not follow.
        /// </summary>
        public bool HoldsTheBridgeSession { get; set; }

        /// <summary>Whether the bridge this fake plays holds a session now (<see cref="HoldsTheBridgeSession"/>).</summary>
        public bool SessionOpen { get; private set; }

        /// <summary>
        /// The run folder whose open opened the session (owner decision 159A, protocol 1.5): a close names its run, and the
        /// bridge refuses one naming another - <c>session_mismatch</c>, which the backend answers as <c>RunFolderFailed</c> -
        /// leaving the session as it was.
        /// </summary>
        public string? SessionRun { get; private set; }

        /// <summary>
        /// 004 T175: whether <see cref="CopyFailure"/> is thrown after the bridge's open answered -
        /// the backend's own steps after it failed, or its reply was lost - so the session is open
        /// although the open failed.
        /// </summary>
        public bool CopyFailureLeavesTheSessionOpen { get; set; }

        public RemodelCopyReading OpenCopy(RemodelCopyRequest request, IRemodelRunReporter reporter)
        {
            Calls.Add("copy");
            SourcePathsSeen.Add(request.SourcePath);
            TheBackendTakes(request.RunDirectory);
            if (HoldsTheBridgeSession && SessionOpen)
            {
                throw new RemodelRefusal(
                    "RunInProgress",
                    "this bridge session already has a remodel run open.",
                    retryable: true);
            }

            if (CopyFailure != null)
            {
                SessionOpen = HoldsTheBridgeSession && CopyFailureLeavesTheSessionOpen;
                SessionRun = SessionOpen ? request.RunDirectory : null;
                throw CopyFailure;
            }

            // The bridge closed the document itself on `preexisting_rebuild_errors`.
            SessionOpen = HoldsTheBridgeSession && CopyPresent;
            SessionRun = SessionOpen ? request.RunDirectory : null;

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

        /// <summary>Every run folder <see cref="CloseCopy"/> was asked to close, in order.</summary>
        public List<string> Closed { get; } = new List<string>();

        /// <summary>What <see cref="CloseCopy"/> throws, if anything: a bridge that did not answer, or one that answered with what it left.</summary>
        public Exception? CloseFailure { get; set; }

        /// <summary>Runs inside <see cref="CloseCopy"/>, before it answers.</summary>
        public Action? DuringClose { get; set; }

        /// <summary>Runs inside <see cref="ProbeScope"/>, before it answers.</summary>
        public Action? DuringProbe { get; set; }

        /// <summary>
        /// Owner decision 159A (004 research R22): the run root the review backend in force was started with, or null while
        /// none is up - read per call, so a restart the review host makes moves it. Set, every call that names a run folder
        /// is first judged as `resolve_run_dir` judges it (chat/server.py): no backend is `BackendUnavailable`, as
        /// <c>BackendRemodelPipeline</c> refuses it, and a folder that is not strictly inside that run root is
        /// `InvalidRunDir`, refused before anything reaches the bridge. Unset, the backend takes every folder, as before.
        /// </summary>
        public Func<string?>? BackendRunRoot { get; set; }

        /// <summary>The run root the backend in force had as each close passed its judging and went on to the bridge, in order.</summary>
        public List<string> RootsClosedUnder { get; } = new List<string>();

        /// <summary>The backend's judging of a run folder (<see cref="BackendRunRoot"/>): the run root it was taken under, or null when unset.</summary>
        private string? TheBackendTakes(string runDirectory)
        {
            if (BackendRunRoot == null)
            {
                return null;
            }

            string? root = BackendRunRoot();
            if (root == null)
            {
                throw new RemodelRefusal(
                    "BackendUnavailable", "FICT the review backend is not running, so the call was not sent.", retryable: true);
            }

            string folder = Path.GetFullPath(runDirectory).TrimEnd(Path.DirectorySeparatorChar);
            string inside = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!folder.StartsWith(inside, StringComparison.OrdinalIgnoreCase))
            {
                throw new RemodelRefusal("InvalidRunDir", "FICT run_dir is not inside the run root.", retryable: false);
            }

            return root;
        }

        public void CloseCopy(string runDirectory)
        {
            Calls.Add("close");
            Closed.Add(runDirectory);
            DuringClose?.Invoke();
            string? judgedUnder = TheBackendTakes(runDirectory);
            if (judgedUnder != null)
            {
                RootsClosedUnder.Add(judgedUnder);
            }

            // A close the bridge answered ends the session whatever it left - `close_incomplete`
            // included - and one it could not answer (`BridgeUnavailable`, or no named refusal)
            // leaves it as it was; so does one the backend could not send (`BackendUnavailable`;
            // owner decision 159A, on the final review). Since protocol 1.5 the bridge compares the
            // run a close names with its session's exactly, and refuses another run's. The run a close
            // names is its folder's own name, `run_id` (BridgeDispatcher.Session), never the whole path:
            // changed deliberately 2026-10-27 (owner decision 159A, 004 research R22), so two runs of one
            // name under two run roots are one run to this fake, as they are to the bridge.
            bool answered = CloseFailure == null
                || (CloseFailure is RemodelRefusal refusal
                    && refusal.ErrorClass != "BridgeUnavailable"
                    && refusal.ErrorClass != "BackendUnavailable"
                    && refusal.ErrorClass != "HttpError"
                    && refusal.ErrorClass != "BadResponse"
                    && refusal.ErrorClass != "InvalidRunDir"
                    && refusal.ErrorClass != "InvalidRequest");
            if (answered
                && SessionOpen
                && !string.Equals(Path.GetFileName(SessionRun), Path.GetFileName(runDirectory), StringComparison.Ordinal))
            {
                throw new RemodelRefusal(
                    "RunFolderFailed",
                    "FICT 'remodel.close' was sent for another run than the one whose copy is open on this bridge.",
                    retryable: false);
            }

            if (answered)
            {
                SessionOpen = false;
                SessionRun = null;
            }

            if (CloseFailure != null)
            {
                throw CloseFailure;
            }
        }

        public string Plan(string runDirectory, IRemodelRunReporter reporter)
        {
            Calls.Add("plan");
            TheBackendTakes(runDirectory);
            DuringPlan?.Invoke();
            if (PlanFailure != null)
            {
                throw PlanFailure;
            }

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

    /// <summary>A reporter that keeps nothing, for a fake asked directly.</summary>
    private sealed class NullReporter : IRemodelRunReporter
    {
        public bool StopRequested => false;

        public void Status(string stage, string message)
        {
        }

        public void Progress(int applied, int total, int seq, string kind, string? subjectName)
        {
        }

        public void Change(string changeRecordJson)
        {
        }
    }

    private sealed class FakeResolver : IEntityResolver
    {
        public List<EntityShowRequest> Requests { get; } = new List<EntityShowRequest>();

        public EntityShowOutcome Outcome { get; set; } = EntityShowOutcome.Shown(null);

        /// <summary>What <see cref="Show"/> throws, if anything: SOLIDWORKS that did not answer, or would not attach (owner decision 159A).</summary>
        public Exception? Failure { get; set; }

        public EntityShowOutcome Show(EntityShowRequest request)
        {
            Requests.Add(request);
            if (Failure != null)
            {
                throw Failure;
            }

            return Outcome;
        }
    }

    private sealed class RecordingOpener : IPathOpener
    {
        public List<string> Opened { get; } = new List<string>();

        /// <summary>What <see cref="Open"/> throws, if anything: Windows that would not open it (owner decision 159A).</summary>
        public Exception? Failure { get; set; }

        public void Open(string path)
        {
            if (Failure != null)
            {
                throw Failure;
            }

            Opened.Add(path);
        }
    }
}
