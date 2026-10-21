using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Model;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T078: the Model check tab's half of `contracts/model-check.md` sections 2 and 3 - `ready`,
/// `check.start`, and the four rows it delegates to <see cref="PaneActions"/>.
///
/// The host does very little on purpose, and what it does not do is the design:
///
/// <b>It does not evaluate anything.</b> It extracts, and the page calls `POST /checks/rms`
/// itself with the token and origin it received in `init`, the same way the Review page already
/// calls the message, evidence and disposition routes. There is one evaluation entry point and
/// it is in Python (FR-024); a host that called it would be a second one.
///
/// <b>It registers no tool and writes to no document</b> (FR-031). `ToolListingCheckTests` and
/// `CliProfileWriterTests` pass unedited because nothing here touches either list.
///
/// <b>It owns the run folder.</b> `RunFolders.CreateForCheck` names and creates it, and the
/// folder becomes the pane's latest run before the page is told about it, so `entity.show` can
/// resolve `document_id` through the package that was just written and the Ask tab opens in the
/// same place (FR-028).
///
/// The refusals come before the extraction because a dump is SOLIDWORKS time, and the one that
/// is specific to this tab is `NotAPart`: the tab ships part-only, and an assembly answered
/// with 34 unresolved rules would read as a bad design rather than as a scope this increment
/// does not cover.
/// </summary>
public sealed class ModelCheckHostTests
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 16, 10, 15, 32);

    // ---- ready / init -------------------------------------------------------------------

    [Fact]
    public void ReadyAnswersInitWithTheBackendTheTokenTheRunRootAndTheDocument()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Machined");
            world.Open();

            world.Receive("ready", "r1", new { });

            JsonElement init = world.Reply("init", "r1");
            // The page's OWN origin under `/__backend`, not the backend's loopback one: the
            // page fetches its own origin and the host serves that prefix from C#
            // (docs/pane-backend-proxy.md). The port is still sent - the pane shows it, and a
            // diagnostic still needs to know which child is listening - but no page builds a
            // URL from it.
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
            Assert.Equal(@"C:\parts\bracket.SLDPRT", document.GetProperty("path").GetString());
            Assert.Equal("Machined", document.GetProperty("configuration").GetString());
            Assert.Equal("part", document.GetProperty("kind").GetString());

            Assert.Equal(JsonValueKind.Null, init.GetProperty("latest_check").ValueKind);
        }
    }

    /// <summary>
    /// Feature 013 T149 (FR-008, US1 scenario 6): the path of the standards profile the Review
    /// tab uses, so the page can relay it on `POST /checks/rms` and the body can say the open
    /// part looks bought and why it is graded anyway. The path only - no profile value travels
    /// on any message - and read fresh, because a settings save moves it.
    /// </summary>
    [Fact]
    public void InitCarriesTheConfiguredStandardsProfilePathReadFresh()
    {
        using (var world = new CheckWorld())
        {
            world.ProfilePath = @"C:\profiles\standards.yaml";
            world.Open();

            world.Receive("ready", "r1", new { });
            world.ProfilePath = @"C:\profiles\other.yaml";
            world.Receive("ready", "r2", new { });

            Assert.Equal(
                @"C:\profiles\standards.yaml",
                world.Reply("init", "r1").GetProperty("standards_profile").GetString());
            Assert.Equal(
                @"C:\profiles\other.yaml",
                world.Reply("init", "r2").GetProperty("standards_profile").GetString());
        }
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void InitCarriesANullStandardsProfileWhenNoneIsConfigured(string? configured)
    {
        using (var world = new CheckWorld())
        {
            world.ProfilePath = configured;
            world.Open();

            world.Receive("ready", "r1", new { });

            Assert.Equal(
                JsonValueKind.Null,
                world.Reply("init", "r1").GetProperty("standards_profile").ValueKind);
        }
    }

    [Fact]
    public void InitCarriesNoDocumentAndNoBackendWhenThereIsNeither()
    {
        using (var world = new CheckWorld())
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

    [Theory]
    [InlineData(@"C:\parts\bracket.SLDPRT", "part")]
    [InlineData(@"C:\parts\bracket.sldprt", "part")]
    [InlineData(@"C:\parts\bracket assy.SLDASM", "assembly")]
    [InlineData(@"C:\parts\sheet.slddrw", "drawing")]
    public void TheDocumentKindIsReportedSoThePageNeverGuessesFromThePath(
        string path, string kind)
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(path, "Default");
            world.Open();

            world.Receive("ready", "r1", new { });

            Assert.Equal(
                kind,
                world.Reply("init", "r1").GetProperty("document").GetProperty("kind").GetString());
        }
    }

    /// <summary>
    /// A document whose extension names no kind is reported as no kind, not as a part. A wrong
    /// "part" here is a Model check run against something the rules were never written for.
    /// </summary>
    [Fact]
    public void ADocumentWhoseKindCannotBeReadIsReportedAsUnknownRatherThanGuessed()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.step", "Default");
            world.Open();

            world.Receive("ready", "r1", new { });

            Assert.Equal(
                JsonValueKind.Null,
                world.Reply("init", "r1").GetProperty("document").GetProperty("kind").ValueKind);
        }
    }

    /// <summary>
    /// The tab can be opened before the backend is listening, and the endpoint is read fresh on
    /// every `ready` for exactly that reason: the page re-asks when the host says the backend
    /// is up, and the second answer has to carry what the first one could not. An `init` that
    /// was answered once from a cached endpoint would leave the tab unable to call any check
    /// route for the life of the page.
    /// </summary>
    [Fact]
    public void ASecondReadyCarriesTheBackendThatStartedAfterTheFirstOne()
    {
        using (var world = new CheckWorld())
        {
            world.Endpoint = null;
            world.Open();

            world.Receive("ready", "r1", new { });
            JsonElement first = world.Reply("init", "r1");
            Assert.Equal(JsonValueKind.Null, first.GetProperty("backend").ValueKind);
            Assert.Equal(JsonValueKind.Null, first.GetProperty("token").ValueKind);

            world.Endpoint = new BackendEndpoint(51234, "0FAKEtoken");
            world.Receive("ready", "r2", new { });

            JsonElement second = world.Reply("init", "r2");
            Assert.Equal(51234, second.GetProperty("backend").GetProperty("port").GetInt32());
            Assert.Equal("0FAKEtoken", second.GetProperty("token").GetString());
        }
    }

    [Fact]
    public void InitCarriesTheLatestCheckOnceOneHasRun()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Open();
            world.Receive("check.start", "c1", new { scope = "part" });

            world.Receive("ready", "r2", new { });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_check");
            Assert.Equal(
                Path.Combine(world.RunRoot, "20260916-101532-bracket-check"),
                latest.GetProperty("run_dir").GetString());
            Assert.False(string.IsNullOrWhiteSpace(latest.GetProperty("at").GetString()));
        }
    }

    // ---- check.start: the refusals ------------------------------------------------------

    [Fact]
    public void CheckStartIsRefusedWithNoDocumentOpen()
    {
        using (var world = new CheckWorld())
        {
            world.Document = null;
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            JsonElement error = world.Reply("error", "c1");
            Assert.Equal("NoDocument", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    [Fact]
    public void CheckStartIsRefusedWhenTheAddInIsNotAttachedToSolidworks()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.UseDump = false;
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            Assert.Equal("NotAttached", world.Reply("error", "c1").GetProperty("error_class").GetString());
            Assert.Empty(world.RunFolders());
        }
    }

    /// <summary>
    /// The tab ships part-only. An assembly is refused with the reason rather than checked and
    /// reported as 34 unresolved rules (tasks.md Phase 9, `contracts/model-check.md` section 1).
    /// </summary>
    [Theory]
    [InlineData(@"C:\parts\bracket assy.SLDASM")]
    [InlineData(@"C:\parts\sheet.slddrw")]
    [InlineData(@"C:\parts\bracket.step")]
    public void CheckStartIsRefusedForAnythingThatIsNotAPartAndNothingIsExtracted(string path)
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(path, "Default");
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            JsonElement error = world.Reply("error", "c1");
            Assert.Equal("NotAPart", error.GetProperty("error_class").GetString());
            Assert.Contains("part", error.GetProperty("message").GetString()!, StringComparison.OrdinalIgnoreCase);
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    // ---- check.start: the happy path ----------------------------------------------------

    [Fact]
    public void CheckStartCreatesTheCheckFolderRunsTheModelCheckDumpRegistersItAndReplies()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Machined");
            world.Dump.Documents = 1;
            world.Dump.Features = 27;
            world.Dump.Equations = 4;
            world.Dump.Gaps = 2;
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            string expected = Path.Combine(world.RunRoot, "20260916-101532-bracket-check");
            Assert.True(Directory.Exists(expected), $"the host did not create {expected}");
            Assert.Equal(expected, world.Dump.LastDirectory);
            Assert.Equal(1, world.Dump.Runs);

            // The whole point of the profile: the hole, fastener, face and mesh phases are what
            // a dump spends its time on, and no RMS rule reads any of them (FR-022).
            Assert.Equal(DumpProfile.ModelCheck, world.Dump.LastProfile);

            // Registered before the page hears about it, so a `POST /checks/rms` sent the
            // instant `check.extracted` arrives resolves ids through this folder's package.
            Assert.Equal(new[] { expected }, world.Registered.ToArray());

            JsonElement extracted = world.Reply("check.extracted", "c1");
            Assert.Equal(expected, extracted.GetProperty("run_dir").GetString());
            Assert.Equal(@"C:\parts\bracket.SLDPRT", extracted.GetProperty("document").GetString());
            Assert.Equal("Machined", extracted.GetProperty("configuration").GetString());
            Assert.Equal(2, extracted.GetProperty("gaps").GetInt32());

            JsonElement counts = extracted.GetProperty("counts");
            Assert.Equal(1, counts.GetProperty("documents").GetInt32());
            Assert.Equal(27, counts.GetProperty("features").GetInt32());
            Assert.Equal(4, counts.GetProperty("equations").GetInt32());
        }
    }

    /// <summary>
    /// A dump that did not report a count reports no count. A zero would read as "this part has
    /// no equations", which is a statement about the design rather than about the extract
    /// (constitution: never write a default for engineering data).
    /// </summary>
    [Fact]
    public void ACountTheDumpDidNotReportIsNullRatherThanZero()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Dump.Documents = 1;
            world.Dump.Features = 27;
            world.Dump.Equations = null;
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            JsonElement counts = world.Reply("check.extracted", "c1").GetProperty("counts");
            Assert.Equal(JsonValueKind.Null, counts.GetProperty("equations").ValueKind);
        }
    }

    [Fact]
    public void CheckStartReportsProgressAsExtractingStatusMessagesAndEndsReady()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Dump.Progress.Add("Reading the feature tree...");
            world.Dump.Progress.Add("Reading equations...");
            world.Dump.Features = 27;
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            string[] stages = world.AllPosted("status")
                .Select(payload => payload.GetProperty("stage").GetString()!).ToArray();
            string[] messages = world.AllPosted("status")
                .Select(payload => payload.GetProperty("message").GetString()!).ToArray();

            Assert.Equal("ready", stages.Last());
            Assert.All(stages.Take(stages.Length - 1), stage => Assert.Equal("extracting", stage));
            Assert.Contains("bracket", messages[0]);
            Assert.Contains("Reading the feature tree...", messages);
            Assert.Contains("Reading equations...", messages);
            Assert.True(
                Array.IndexOf(messages, "Reading the feature tree...")
                    < Array.IndexOf(messages, "Reading equations..."),
                "the dump's progress messages reached the page out of order");
        }
    }

    /// <summary>
    /// The extracted status names components the dump could not read, the same clause the
    /// Review and Standards hosts' ready statuses use
    /// (docs/feature-request-resolve-lightweight.md).
    /// </summary>
    [Fact]
    public void TheExtractedStatusNamesHowManyComponentsWereNeverRead()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Dump.Unexamined = 2;
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            string message = world.LastPosted("status").GetProperty("message").GetString()!;
            Assert.Contains("2 not read (lightweight or suppressed)", message);
        }
    }

    [Fact]
    public void TwoChecksInTheSameSecondGetDistinctFoldersAndTheSecondBecomesTheLatest()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });
            world.Receive("check.start", "c2", new { scope = "part" });

            string first = world.Reply("check.extracted", "c1").GetProperty("run_dir").GetString()!;
            string second = world.Reply("check.extracted", "c2").GetProperty("run_dir").GetString()!;

            Assert.Equal(Path.Combine(world.RunRoot, "20260916-101532-bracket-check"), first);
            Assert.Equal(Path.Combine(world.RunRoot, "20260916-101532-bracket-check-2"), second);
            Assert.Equal(new[] { first, second }, world.Registered.ToArray());
        }
    }

    // ---- check.start: the failures ------------------------------------------------------

    /// <summary>
    /// The folder is left behind on purpose: whatever the dump did write is the evidence for
    /// why it stopped (constitution Principle I). It is not registered, because a half-written
    /// package must not become the folder `entity.show` and the Ask tab read from.
    /// </summary>
    [Fact]
    public void ADumpThatFailsIsReportedAndTheFolderIsNeitherRegisteredNorDeleted()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Dump.Failure = new InvalidOperationException("the feature tree could not be read");
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            JsonElement error = world.Reply("error", "c1");
            Assert.Equal("ExtractionFailed", error.GetProperty("error_class").GetString());
            Assert.Contains("the feature tree could not be read", error.GetProperty("message").GetString()!);
            Assert.Equal("error", world.LastPosted("status").GetProperty("stage").GetString());

            Assert.Empty(world.Registered);
            Assert.Single(world.RunFolders());
        }
    }

    [Fact]
    public void ARunRootThatCannotBeWrittenIsReportedRatherThanThrown()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.BlankRunRoot = true;
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            Assert.Equal(
                "RunFolderFailed", world.Reply("error", "c1").GetProperty("error_class").GetString());
            Assert.Equal(0, world.Dump.Runs);
        }
    }

    // ---- the envelope -------------------------------------------------------------------

    [Fact]
    public void AMessageTypeTheHostDoesNotHandleIsAnsweredWithAnError()
    {
        using (var world = new CheckWorld())
        {
            world.Open();

            world.Receive("check.explode", "x1", new { });

            JsonElement error = world.Reply("error", "x1");
            Assert.Equal("UnknownMessage", error.GetProperty("error_class").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());
        }
    }

    /// <summary>
    /// An exception escaping into the `WebMessageReceived` handler surfaces inside SOLIDWORKS.
    /// Nothing the page can send may do that.
    /// </summary>
    [Theory]
    [InlineData("not json at all")]
    [InlineData("[]")]
    [InlineData("{\"id\": \"x\"}")]
    [InlineData("{\"type\": 7}")]
    public void AMalformedPageMessageIsAnsweredRatherThanThrown(string json)
    {
        using (var world = new CheckWorld())
        {
            world.Open();

            world.Host.Receive(json);

            Assert.NotEmpty(world.AllPosted("error"));
        }
    }

    [Fact]
    public void DocumentChangedPostsThePathTheConfigurationAndTheKindTheHostSees()
    {
        using (var world = new CheckWorld())
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

    [Fact]
    public void ClosingTheLastDocumentPostsANullDocumentChanged()
    {
        using (var world = new CheckWorld())
        {
            world.Document = new PageDocument(@"C:\parts\other.SLDPRT", "Machined");
            world.Open();
            world.Document = null;

            world.Host.DocumentChanged();

            Assert.Equal(JsonValueKind.Null, world.LastPosted("document.changed").ValueKind);
        }
    }

    // ---- owner decision 154A: a run root on a share or reached through a link -----------

    /// <summary>
    /// Owner decision 154A (feature 002 T191): `check.start` refuses a run root the run root rule refuses,
    /// first - before the document is asked about - in the Model check tab's words, which its page shows
    /// whole: what the root is, that nothing was checked, and the way on, a local folder chosen for runs in
    /// Settings on the Review tab, since this page has none (the reviews' F5), and Model check pressed again.
    /// No check folder is made, nothing is extracted or registered, no status is posted and no path reaches
    /// the page.
    /// </summary>
    [Theory]
    [MemberData(nameof(FakeRunRootProbe.RefusedKinds), MemberType = typeof(FakeRunRootProbe))]
    public void CheckStartRefusesARunRootTheRuleRefusesFirstAndMakesNothing(string kind)
    {
        using (var world = new CheckWorld())
        {
            var refusing = FakeRunRootProbe.Refusing(kind, world.RunRoot);
            world.RunRootSpelling = refusing.RunRoot;
            world.Probe = refusing.Probe;
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });
            world.Document = null;
            world.Receive("check.start", "c2", new { scope = "part" });

            foreach (string id in new[] { "c1", "c2" })
            {
                JsonElement error = world.Reply("error", id);
                Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
                Assert.False(error.GetProperty("retryable").GetBoolean());
                Assert.Equal(
                    RunRootRule.Refusal(
                        refusing.Verdict, "nothing was checked", RunRootRule.InSettingsOnTheReviewTab, "press Model check again"),
                    error.GetProperty("message").GetString());
            }

            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
            Assert.Empty(world.Registered);
            Assert.Empty(world.AllPosted("status"));
            Assert.Empty(world.AllPosted("check.extracted"));
            Assert.DoesNotContain(world.Posted, message => message.Contains(Path.GetFileName(Path.GetDirectoryName(world.RunRoot)!)));
        }
    }

    /// <summary>
    /// Owner decision 154A, with 153A's record of the settings in force (feature 002 T201): while a start of the
    /// backend under way would bring another run root into force - a settings save's restart, made on the Review
    /// tab's thread, or the add-in's first start - `check.start` is refused first, before the run root is judged
    /// or the document asked about, `BackendUnavailable`, retryable, in this tab's words: the backend is being
    /// started with another folder for runs, nothing was checked, and Model check pressed again in a moment. A
    /// check made then would be made under the run root in force, which the backend coming up refuses. No folder is
    /// made, nothing is extracted, registered or posted, and the rule reads nothing.
    /// </summary>
    [Fact]
    public void CheckStartIsRefusedWhileAStartOfTheBackendWouldBringAnotherRunRootIn()
    {
        using (var world = new CheckWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.RunRootForANewRun = () => null;
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            JsonElement error = world.Reply("error", "c1");
            Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(
                RunRootRule.MovingRefusal("nothing was checked", "press Model check again"),
                error.GetProperty("message").GetString());
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
            Assert.Empty(world.Registered);
            Assert.Empty(world.AllPosted("status"));
            Assert.Empty(probe.Asked);
        }
    }

    /// <summary>
    /// ...and a check reads the run root once to judge it and make its folder (feature 002 T201): the one it judges
    /// is the one its folder is made under, even when the run root in force moves between - a restart on another
    /// tab's thread that ends meanwhile. It read the run root to judge it and again to make the folder, and so
    /// could make a check's folder under a run root it never judged. Changed deliberately for the reviews of 154A's
    /// merge, N6: the run root is read a second time once the extraction is over, so the move is now answered
    /// there, `RunRootChanged`, where the check was handed on. Changed deliberately for owner decision 157A: the
    /// run root is read once more, once the check's gate is passed - a restart the gate makes can move it, and a moved
    /// one is judged again (`CheckHoldTests`) - so the move this case makes between the folder and the end of the
    /// extraction comes at the third reading.
    /// </summary>
    [Fact]
    public void ACheckJudgesAndMakesItsFolderUnderOneReadingOfTheRunRoot()
    {
        using (var world = new CheckWorld())
        {
            string moved = Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "moved", "runs");
            int readings = 0;
            world.RunRootSource = () => ++readings <= 2 ? world.RunRoot : moved;
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            Assert.Equal("RunRootChanged", world.Reply("error", "c1").GetProperty("error_class").GetString());
            Assert.Equal(world.RunRoot, Path.GetDirectoryName(Assert.Single(world.RunFolders())));
            Assert.False(Directory.Exists(moved), "the check's folder was made under a run root it did not judge");
            Assert.Equal(3, readings);
        }
    }

    /// <summary>
    /// The reviews of 154A's merge, N4 (feature 002 T204): under a run root in force that the rule refuses, with a
    /// folder chosen for runs in the Review tab's Settings that is not in force - its save's restart failed - the
    /// Model check start is refused `RunRootChosenNotInForce`, not retryable, in words that say the folder chosen is not in
    /// force until the review backend restarts with it and to save the settings again to retry the restart -
    /// not to choose a local folder, which the engineer has just done. The folder saved in another letter case is
    /// the run root in force, and the start is refused as before.
    /// </summary>
    [Theory]
    [InlineData("another folder")]
    [InlineData("the run root in force in another letter case")]
    public void UnderARefusedRunRootAFolderChosenNotInForceIsToldWithTheWayOnToRetryTheRestart(string saved)
    {
        using (var world = new CheckWorld())
        {
            var refusing = FakeRunRootProbe.Refusing("on a share", world.RunRoot);
            world.RunRootSpelling = refusing.RunRoot;
            world.Probe = refusing.Probe;
            world.RunRootSaved = () => saved == "another folder"
                ? Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "FICT-chosen", "runs")
                : refusing.RunRoot.ToUpperInvariant();
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Open();

            world.Receive("check.start", "s1", new { scope = "part" });

            JsonElement error = world.Reply("error", "s1");
            Assert.False(error.GetProperty("retryable").GetBoolean());
            if (saved == "another folder")
            {
                Assert.Equal("RunRootChosenNotInForce", error.GetProperty("error_class").GetString());
                Assert.Equal(
                    RunRootRule.ChosenNotInForceRefusal(
                        refusing.Verdict, "nothing was checked", RunRootRule.InSettingsOnTheReviewTab, "press Model check again"),
                    error.GetProperty("message").GetString());
            }
            else
            {
                Assert.Equal("RunRootRefused", error.GetProperty("error_class").GetString());
                Assert.Equal(
                    RunRootRule.Refusal(
                        refusing.Verdict, "nothing was checked", RunRootRule.InSettingsOnTheReviewTab, "press Model check again"),
                    error.GetProperty("message").GetString());
            }

            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
            Assert.DoesNotContain(world.Posted, message => message.Contains("FICT-chosen"));
        }
    }

    /// <summary>
    /// The reviews of 154A's merge, N6 (feature 002 T204): an extraction takes minutes, and a settings save's restart
    /// on the Review tab, which no check holds back, can bring another run root into force meanwhile - the backend
    /// would then refuse the run's folder at the page's first call. The run root is read again once the extraction
    /// is over: a run whose folder is no longer under the run root in force is answered `RunRootChanged`, not
    /// retryable, in words the page prints whole, and while a start that would bring another in is still under way
    /// it is answered as a start is then (`BackendUnavailable`); either way the folder is left as the evidence, and
    /// it is neither registered nor handed to the page. Changed deliberately for owner decision 157A: the run root is
    /// read once more, once the check's gate is passed, so the move made while the model is read comes at the third
    /// reading; and since a check holds every settings restart back while a backend is up, only a start that brings a
    /// backend up where there was none can make it.
    /// </summary>
    [Theory]
    [InlineData("another run root in force")]
    [InlineData("a start under way that brings another in")]
    public void ARunWhoseRunRootMovesWhileTheModelIsReadIsAnsweredAndNotHandedOn(string after)
    {
        using (var world = new CheckWorld())
        {
            string moved = Path.Combine(Path.GetDirectoryName(world.RunRoot)!, "moved", "runs");
            int readings = 0;
            world.RunRootForANewRun = () => ++readings <= 2
                ? world.RunRoot
                : after == "another run root in force" ? moved : null;
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Open();

            world.Receive("check.start", "s1", new { scope = "part" });

            JsonElement error = world.Reply("error", "s1");
            if (after == "another run root in force")
            {
                Assert.Equal("RunRootChanged", error.GetProperty("error_class").GetString());
                Assert.False(error.GetProperty("retryable").GetBoolean());
                Assert.Equal(
                    RunRootRule.ChangedRefusal("the feature tree was read", "nothing was checked", "press Model check again"),
                    error.GetProperty("message").GetString());
            }
            else
            {
                Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
                Assert.True(error.GetProperty("retryable").GetBoolean());
                Assert.Equal(
                    RunRootRule.MovingRefusal("nothing was checked", "press Model check again"),
                    error.GetProperty("message").GetString());
            }

            Assert.Equal(3, readings);
            Assert.Equal(1, world.Dump.Runs);
            Assert.Single(world.RunFolders());
            Assert.Empty(world.Registered);
            Assert.Empty(world.AllPosted("check.extracted"));
            Assert.False(Directory.Exists(moved));
        }
    }

    // ---- the world ----------------------------------------------------------------------

    private sealed class CheckWorld : IDisposable
    {
        private readonly string _root;
        private ModelCheckHost? _host;

        public CheckWorld()
        {
            _root = Path.Combine(
                Path.GetTempPath(), "SwReview.ModelCheckHost.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            RunRoot = Path.Combine(_root, "runs");
            Directory.CreateDirectory(RunRoot);
            LogFolder = Path.Combine(_root, "logs");
        }

        public string RunRoot { get; }

        public string LogFolder { get; }

        public bool BlankRunRoot { get; set; }

        /// <summary>The run root as the setting spells it, when not <see cref="RunRoot"/> (owner decision 154A).</summary>
        public string? RunRootSpelling { get; set; }

        /// <summary>
        /// What each reading of the run root in force answers, when a test makes it move between readings (owner
        /// decision 154A, with 153A's record); null reads <see cref="RunRootSpelling"/> or <see cref="RunRoot"/>.
        /// </summary>
        public Func<string>? RunRootSource { get; set; }

        /// <summary>The run root for a new run, when a test sets it (owner decision 154A, with 153A's record); null keeps the host's default.</summary>
        public Func<string?>? RunRootForANewRun { get; set; }

        /// <summary>The run root saved in the Review tab's Settings, when a test sets it (the reviews of 154A's merge, N4).</summary>
        public Func<string?>? RunRootSaved { get; set; }

        /// <summary>
        /// What the run root rule reads (owner decision 154A); when null, a probe that answers every folder as a
        /// local one reached by its own path - not Windows, so a temp folder below a junction on a developer's
        /// machine fails no test that is not about the rule (the reviews' N11).
        /// </summary>
        public IRunRootProbe? Probe { get; set; }

        public PageDocument? Document { get; set; }

        public string? ProfilePath { get; set; }

        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(51234, "0FAKEtoken");

        public FakeCheckDump Dump { get; } = new FakeCheckDump();

        public bool UseDump { get; set; } = true;

        public List<string> Registered { get; } = new List<string>();

        public List<string> Posted { get; } = new List<string>();

        public ModelCheckHost Host =>
            _host ?? throw new InvalidOperationException("call Open() first");

        public void Open()
        {
            var options = new ModelCheckHostOptions(
                new CollectingChannel(Posted),
                () => RunRootSource != null ? RunRootSource() : BlankRunRoot ? "   " : RunRootSpelling ?? RunRoot)
            {
                Backend = () => Endpoint,
                CurrentDocument = () => Document,
                ProfilePath = () => ProfilePath,
                Dump = UseDump ? Dump : null,
                RegisterLatestRun = directory => Registered.Add(directory),
                LogFolder = () => LogFolder,
                Now = () => Stamp,
            };
            options.RunRootProbe = Probe ?? FakeRunRootProbe.Local();
            if (RunRootForANewRun != null)
            {
                options.RunRootForANewRun = RunRootForANewRun;
            }

            if (RunRootSaved != null)
            {
                options.RunRootSaved = RunRootSaved;
            }

            _host = new ModelCheckHost(options);
        }

        public string[] RunFolders() =>
            Directory.Exists(RunRoot) ? Directory.GetDirectories(RunRoot) : new string[0];

        public void Receive(string type, string id, object payload) =>
            Host.Receive(JsonSerializer.Serialize(new { type, id, payload }));

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
                    matches.Add(root.GetProperty("payload"));
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
            .Select(root => root.GetProperty("payload"))
            .ToArray();

        public JsonElement LastPosted(string type)
        {
            JsonElement[] all = AllPosted(type);
            Assert.True(all.Length > 0, $"no '{type}' message was posted");
            return all[all.Length - 1];
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
        private readonly List<string> _posted;

        public CollectingChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json) => _posted.Add(json);
    }

    private sealed class FakeCheckDump : IReviewDump
    {
        public int Runs { get; private set; }

        public string? LastDirectory { get; private set; }

        public DumpProfile? LastProfile { get; private set; }

        public List<string> Progress { get; } = new List<string>();

        public Exception? Failure { get; set; }

        public int? Documents { get; set; }

        public int? Features { get; set; }

        public int? Equations { get; set; }

        public int Gaps { get; set; }

        public int? Unexamined { get; set; }

        public DumpSummary Run(
            string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
        {
            Runs++;
            LastDirectory = outputDirectory;
            LastProfile = profile;
            foreach (string message in Progress)
            {
                progress(message);
            }

            if (Failure != null)
            {
                throw Failure;
            }

            return new DumpSummary(
                Path.Combine(outputDirectory, "package.json"),
                components: 1,
                gaps: Gaps,
                unexamined: Unexamined,
                documents: Documents,
                features: Features,
                equations: Equations);
        }
    }
}
