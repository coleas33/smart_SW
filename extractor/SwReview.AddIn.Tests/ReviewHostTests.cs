using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T039: the review half of the page-to-host contract in
/// `specs/002-task-pane-assistant/contracts/pane-host-messages.md` - `review.start`,
/// `entity.show`, `report.open`, `folder.open`, `log.open`, and the unsolicited
/// `document.changed`.
///
/// Like <see cref="PageMessageTests"/> these run against <see cref="ReviewHost"/> with fakes
/// and no WebView2, no SOLIDWORKS and no Python, because every rule that has to hold here is
/// a decision the host makes between the page and the world:
///
/// 1. <b>A review cannot start without a document.</b> The dump derives every id in the
///    package from the root document's path, so a Review press with nothing open has to be
///    refused at the top rather than surfacing as an exception out of the extractor.
/// 2. <b>The run folder is the host's, and it is created before anything is written into
///    it.</b> `&lt;run_root&gt;/&lt;yyyyMMdd-HHmmss&gt;-&lt;doc&gt;`, through the same helper the
///    terminal-first path uses for `-terminal` (T060), including when two runs land in the
///    same second.
/// 3. <b>A reference that no longer resolves reports the state code and the component's full
///    path</b> rather than a bare failure, because the engineer's next move is to find the
///    component by hand (spec Edge Cases, SC-007).
/// 4. <b>The page never supplies a path to open.</b> `report.open` and `folder.open` resolve
///    the folder from the host's own session record keyed by `chat_id`, and every resolved
///    path is canonicalized and checked to be inside `run_root` (or the log folder) before it
///    reaches the shell. A page that could name the path could open anything on the
///    workstation with one crafted message.
/// </summary>
public sealed class ReviewHostTests
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 13, 14, 25, 30);

    /// <summary>A stored key, so a redaction test has something real to mask.</summary>
    private const string Secret = "sk-test-0123456789abcdef";

    // ---- review.start -------------------------------------------------------------------

    [Fact]
    public void ReviewStartIsRefusedWhenNoDocumentIsOpen()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = null;
            world.Open();

            world.Receive("review.start", "r1", new { });

            JsonElement error = world.Reply("error", "r1");
            Assert.Equal("NoDocument", error.GetProperty("error_class").GetString());
            Assert.Contains("document", error.GetProperty("message").GetString()!, StringComparison.OrdinalIgnoreCase);

            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.Backend.Created);
            Assert.Empty(world.Host.Sessions);
            Assert.Empty(world.RunFolders());
        }
    }

    [Fact]
    public void ReviewStartCreatesTheRunFolderRunsTheDumpPostsTheSessionAndReplies()
    {
        using (var world = new ReviewWorld())
        {
            world.Now = Stamp;
            world.Document = new PageDocument(@"C:\parts\bracket assy.SLDASM", "Default");
            world.Settings.Provider = "openai";
            world.Settings.Model = "gpt-5.1";
            world.Settings.Effort = "high";
            world.Bridge = new BridgeConfig("swreview-abc123", "bridge-secret-value");
            world.Open();

            world.Receive("review.start", "r1", new { });

            string expected = Path.Combine(world.Settings.RunRoot, "20260913-142530-bracket assy");
            Assert.True(Directory.Exists(expected), $"the host did not create {expected}");
            Assert.Equal(expected, world.Dump.LastDirectory);
            Assert.Equal(1, world.Dump.Runs);

            // T064. The review reasons over faces, holes, fasteners and meshes, so it asks
            // for every phase. A review that quietly took the Model check profile would
            // report a design with no holes in it, which reads as a bad design rather than
            // as a partial extract (FR-022, RK-19).
            Assert.Equal(DumpProfile.Full, world.Dump.LastProfile);

            NewSessionRequest posted = Assert.Single(world.Backend.Created);
            Assert.Equal(expected, posted.RunDirectory);
            Assert.Equal("openai", posted.Provider);
            Assert.Equal("gpt-5.1", posted.Model);
            Assert.Equal("high", posted.Effort);
            Assert.Equal(world.Engineer, posted.Engineer);
            Assert.Null(posted.RetryOf);
            Assert.Equal("swreview-abc123", posted.Bridge!.Pipe);
            Assert.Equal("bridge-secret-value", posted.Bridge!.Secret);

            JsonElement started = world.Reply("review.started", "r1");
            Assert.Equal("chat-1", started.GetProperty("chat_id").GetString());
            Assert.Equal(expected, started.GetProperty("run_dir").GetString());

            SessionRecord record = Assert.Single(world.Host.Sessions);
            Assert.Equal("chat-1", record.ChatId);
            Assert.Equal(expected, record.RunDirectory);

            // The bridge secret authorizes the in-process tool service (T047). It travels to
            // the backend and nowhere else; the page must never see it.
            world.AssertNothingPostedContains("bridge-secret-value");
        }
    }

    [Fact]
    public void ReviewStartReportsTheDumpsProgressAsExtractingStatusMessagesAndEndsReady()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Dump.Progress.Add("Walking the component tree...");
            world.Dump.Progress.Add("Exporting 12 meshes...");
            world.Open();

            world.Receive("review.start", "r1", new { });

            string[] stages = world.AllPosted("status")
                .Select(payload => payload.GetProperty("stage").GetString()!).ToArray();
            string[] messages = world.AllPosted("status")
                .Select(payload => payload.GetProperty("message").GetString()!).ToArray();

            Assert.Equal("ready", stages.Last());
            Assert.All(stages.Take(stages.Length - 1), stage => Assert.Equal("extracting", stage));

            // "Extracting bracket..." meant nothing to an engineer who had not been told what
            // the pane extracts. The first line the page shows names the thing being written.
            Assert.StartsWith("Extracting evidence from bracket", messages[0]);
            Assert.Contains("Walking the component tree...", messages);
            Assert.Contains("Exporting 12 meshes...", messages);
            Assert.True(
                Array.IndexOf(messages, "Walking the component tree...")
                    < Array.IndexOf(messages, "Exporting 12 meshes..."),
                "the dump's progress messages reached the page out of order");
        }
    }

    // ---- the ready status names what was never read (feature: resolve-lightweight) --------

    /// <summary>
    /// The ready status names the lightweight and suppressed component instances the dump could
    /// not read, before a review spends a single token on the ones it could
    /// (docs/feature-request-resolve-lightweight.md, docs/task-a-2026-09-19.md issue 3).
    /// </summary>
    [Fact]
    public void TheReadyStatusNamesHowManyComponentsWereNeverRead()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Dump.Unexamined = 2;
            world.Open();

            world.Receive("review.start", "r1", new { });

            string message = world.LastPosted("status").GetProperty("message").GetString()!;
            Assert.Equal(
                "Reviewing 12 components, 2 not read (lightweight or suppressed).", message);
        }
    }

    /// <summary>Zero and null both mean nothing was left unread, so the sentence is unchanged.</summary>
    [Theory]
    [InlineData(null)]
    [InlineData(0)]
    public void AnUnexaminedCountOfZeroOrNullLeavesTheReadyStatusUnchanged(int? unexamined)
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Dump.Unexamined = unexamined;
            world.Open();

            world.Receive("review.start", "r1", new { });

            string message = world.LastPosted("status").GetProperty("message").GetString()!;
            Assert.Equal("Reviewing 12 components.", message);
        }
    }

    /// <summary>
    /// The four combinations of a gap count and an unexamined count, plus the singular "1 not
    /// read": <see cref="ReviewHost.ReadyMessage"/> is the one place this sentence is composed,
    /// and every one of the Review, Model check and Standards hosts' ready statuses reaches for
    /// the same <see cref="DumpSummary.UnexaminedClause"/> it uses.
    /// </summary>
    [Theory]
    [InlineData(0, null, "Reviewing 4 components.")]
    [InlineData(23, null, "Reviewing 4 components (23 gaps).")]
    [InlineData(0, 2, "Reviewing 4 components, 2 not read (lightweight or suppressed).")]
    [InlineData(
        23, 2, "Reviewing 4 components, 2 not read (lightweight or suppressed) (23 gaps).")]
    [InlineData(0, 1, "Reviewing 4 components, 1 not read (lightweight or suppressed).")]
    public void ReadyMessageComposesTheGapsAndUnexaminedClauses(
        int gaps, int? unexamined, string expected)
    {
        Assert.Equal(expected, ReviewHost.ReadyMessage(components: 4, gaps, unexamined));
    }

    [Fact]
    public void ADumpThatFailsIsReportedAndNoSessionIsPosted()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Dump.Failure = new InvalidOperationException("the component tree could not be walked");
            world.Open();

            world.Receive("review.start", "r1", new { });

            JsonElement error = world.Reply("error", "r1");
            Assert.Equal("ExtractionFailed", error.GetProperty("error_class").GetString());
            Assert.Contains("the component tree could not be walked", error.GetProperty("message").GetString()!);

            Assert.Empty(world.Backend.Created);
            Assert.Empty(world.Host.Sessions);
            Assert.Equal("error", world.LastPosted("status").GetProperty("stage").GetString());
        }
    }

    [Fact]
    public void ReviewStartIsRefusedBeforeTheBackendIsRunningAndNothingIsExtracted()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Backend.Endpoint = null;
            world.Open();

            world.Receive("review.start", "r1", new { });

            JsonElement error = world.Reply("error", "r1");
            Assert.Equal("BackendUnavailable", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());

            // Extraction is minutes of SOLIDWORKS time; it is not spent on a review that has
            // nowhere to go.
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    [Fact]
    public void ASessionThatTheBackendRefusesIsReportedAndNotTracked()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Backend.CreateFailure = new BackendRequestException(
                "InvalidRunDir", "run_dir is not inside the run root", retryable: false);
            world.Open();

            world.Receive("review.start", "r1", new { });

            JsonElement error = world.Reply("error", "r1");
            Assert.Equal("InvalidRunDir", error.GetProperty("error_class").GetString());
            Assert.Empty(world.Host.Sessions);
        }
    }

    [Fact]
    public void ARetryCarriesTheChatItIsRetrying()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Open();

            world.Receive("review.start", "r1", new { retry_of = "chat-0" });

            Assert.Equal("chat-0", Assert.Single(world.Backend.Created).RetryOf);
        }
    }

    [Fact]
    public void TwoReviewsInTheSameSecondGetDistinctRunFolders()
    {
        using (var world = new ReviewWorld())
        {
            world.Now = Stamp;
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Open();

            world.Receive("review.start", "r1", new { });
            world.Backend.NextChatId = "chat-2";
            world.Receive("review.start", "r2", new { });

            string first = world.Reply("review.started", "r1").GetProperty("run_dir").GetString()!;
            string second = world.Reply("review.started", "r2").GetProperty("run_dir").GetString()!;

            Assert.NotEqual(first, second);
            Assert.Equal(Path.Combine(world.Settings.RunRoot, "20260913-142530-bracket"), first);
            Assert.Equal(Path.Combine(world.Settings.RunRoot, "20260913-142530-bracket-2"), second);
            Assert.Equal(2, world.RunFolders().Length);
        }
    }

    [Theory]
    [InlineData(@"C:\parts\bracket.sldasm", "20260913-142530-bracket")]
    [InlineData(@"C:\parts\sub/rev 2.SLDPRT", "20260913-142530-rev 2")]
    [InlineData(@"C:\parts\.sldasm", "20260913-142530-document")]
    [InlineData(@"C:\vault\bad|name*.sldasm", "20260913-142530-bad-name")]
    [InlineData("", "20260913-142530-document")]
    public void TheRunFolderIsNamedAfterTheDocumentWithNothingAPathCannotHold(
        string documentPath, string expectedName)
    {
        using (var world = new ReviewWorld())
        {
            string created = RunFolders.CreateForDocument(world.Settings.RunRoot, documentPath, Stamp);

            Assert.Equal(Path.Combine(world.Settings.RunRoot, expectedName), created);
            Assert.True(Directory.Exists(created));
        }
    }

    [Fact]
    public void ALongDocumentNameIsTruncatedSoTheRunFolderStaysInsideMaxPath()
    {
        using (var world = new ReviewWorld())
        {
            // meshes\<body id>.glb goes underneath this folder, so the name cannot spend the
            // whole path budget on the document.
            string created = RunFolders.CreateForDocument(
                world.Settings.RunRoot, @"C:\parts\" + new string('a', 120) + ".sldasm", Stamp);

            Assert.Equal(
                Path.Combine(world.Settings.RunRoot, "20260913-142530-" + new string('a', 48)),
                created);
        }
    }

    [Fact]
    public void TheTerminalRunFolderComesFromTheSameHelper()
    {
        using (var world = new ReviewWorld())
        {
            // T060's terminal-first path: no document, no review, still a run folder.
            string created = RunFolders.CreateForTerminal(world.Settings.RunRoot, Stamp);

            Assert.Equal(Path.Combine(world.Settings.RunRoot, "20260913-142530-terminal"), created);
            Assert.True(Directory.Exists(created));
        }
    }

    // ---- check records (T076) -----------------------------------------------------------

    /// <summary>
    /// A Model check writes a run folder, and that folder has to become the pane's latest run:
    /// `CurrentSessionRunDirectory` and `RunPackageIndex` both read
    /// <see cref="ReviewHost.LatestSession"/>, and `entity.show` resolves `document_id` to a
    /// path through the package in that folder. A check that wrote somewhere else would
    /// silently degrade Show to "no full path" for every finding and open the Ask tab in an
    /// unrelated folder (`contracts/model-check.md` section 4, FR-028).
    /// </summary>
    [Fact]
    public void TrackingACheckMakesItsFolderTheLatestRunAndTheRecordCarriesNoChatId()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();
            string review = world.TrackedRun("chat-1");
            string check = world.TrackedRun("bracket-check");
            world.WritePackage(check, "doc-check", @"C:\parts\bracket.sldprt");
            world.Host.TrackSession("chat-1", review);

            SessionRecord record = world.Host.TrackCheck(check);

            Assert.True(record.IsCheck);
            Assert.Null(record.ChatId);
            Assert.Equal(check, record.RunDirectory);
            Assert.Same(record, world.Host.LatestSession);

            // `TaskPaneOptions.CurrentSessionRunDirectory` and the `RunPackageIndex` the entity
            // resolver looks ids up through are both wired to `LatestSession` in
            // SwReviewAddIn, so both follow the check with no second registration to keep in
            // step. Spelled the way SwReviewAddIn spells it, and read through the index itself:
            // this is what makes Show resolve `document_id` against the check's own package
            // rather than against the last review's.
            var packages = new RunPackageIndex(() => world.Host.LatestSession?.RunDirectory);
            Assert.Equal(check, world.Host.LatestSession!.RunDirectory);
            Assert.Equal(@"C:\parts\bracket.sldprt", packages.DocumentPath("doc-check"));

            // The chat is still tracked: `folder.open` on the review's card must keep working
            // after a check has been pressed.
            Assert.Equal(review, world.Host.FindSession("chat-1")!.RunDirectory);
        }
    }

    /// <summary>
    /// T134g: the same registration, made by the Remodel tab, over the folder a remodel run
    /// leaves behind.
    ///
    /// `SwReviewAddIn` hands `RemodelHostOptions.RegisterLatestRun` straight to
    /// <see cref="ReviewHost.TrackCheck"/>, so a remodel folder becomes the pane's latest run
    /// exactly as a check's does - and that folder holds no `package.json`: the add-in's
    /// before-dump is renamed to `package-before.json` (`contracts/run-artifacts.md`). This is
    /// the test that pressing Remodel does not silently cost the Review and Model check tabs
    /// their Show: the same assertion as
    /// <see cref="TrackingACheckMakesItsFolderTheLatestRunAndTheRecordCarriesNoChatId"/>,
    /// through the same index, over the names a remodel folder really holds.
    /// </summary>
    [Fact]
    public void TrackingARemodelRunResolvesShowThroughItsBeforeDump()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();
            string review = world.TrackedRun("chat-1");
            world.WritePackage(review, "doc-review", @"C:\parts\housing.sldprt");
            world.Host.TrackSession("chat-1", review);

            string remodel = world.TrackedRun("bracket-remodel");
            string copy = Path.Combine(remodel, "copy", "bracket-RMS.SLDPRT");
            world.WritePackage(remodel, "doc-copy", copy, packageName: "package-before.json");

            world.Host.TrackCheck(remodel);

            var packages = new RunPackageIndex(() => world.Host.LatestSession?.RunDirectory);
            Assert.Equal(remodel, world.Host.LatestSession!.RunDirectory);
            Assert.Equal(copy, packages.DocumentPath("doc-copy"));
        }
    }

    /// <summary>
    /// A check has no chat, so the backend must never be asked about one. Today's scan
    /// swallows every exception, which means a fabricated id would appear to work - at the cost
    /// of one HTTP round trip per settings save and a record that lies. The skip is explicit
    /// instead (FR-028).
    /// </summary>
    [Fact]
    public void TheAnyTurnRunningScanSkipsCheckRecordsWithoutAskingTheBackend()
    {
        using (var world = new ReviewWorld())
        {
            world.Backend.TurnRunningFailure = new InvalidOperationException(
                "the backend was asked about a chat that does not exist");
            world.Open();
            world.Host.TrackCheck(world.TrackedRun("bracket-check"));

            Assert.False(world.Host.AnyTurnRunning());
            Assert.Empty(world.Backend.TurnQuestions);
        }
    }

    [Fact]
    public void ACheckRecordDoesNotHideARunningTurnOnAChatTheHostAlsoTracks()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();
            world.Host.TrackSession("chat-1", world.TrackedRun("chat-1"));
            world.Host.TrackCheck(world.TrackedRun("bracket-check"));
            world.Backend.Running.Add("chat-1");

            Assert.True(world.Host.AnyTurnRunning());
            Assert.Equal(new[] { "chat-1" }, world.Backend.TurnQuestions.ToArray());
        }
    }

    /// <summary>
    /// The session list belongs to the page-message pump thread, and the tool-service gate now
    /// asks `AnyTurnRunning` from another one - it is the gate's busy question, and the answer
    /// decides whether the bridge may be re-attached to the document the engineer just opened
    /// (docs/pane-findings-2026-09-16.md, finding 1). A `review.start` or a Model check landing
    /// while the question is out used to throw `Collection was modified` out of the enumerator,
    /// which the gate read as "busy" and skipped the re-attach for: the very failure the
    /// wiring exists to remove, with a race as its trigger.
    ///
    /// Deterministic rather than threaded: the backend round trip is where the pump gets its
    /// turn, so a mutation from inside it is the same interleaving without the flake.
    /// </summary>
    [Fact]
    public void AnyTurnRunningSurvivesASessionArrivingWhileItIsAsking()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();
            world.Host.TrackSession("chat-1", world.TrackedRun("chat-1"));
            world.Host.TrackSession("chat-2", world.TrackedRun("chat-2"));

            string check = world.TrackedRun("bracket-check");
            world.Backend.OnTurnQuestion = chatId =>
            {
                if (chatId == "chat-1")
                {
                    world.Host.TrackCheck(check);
                }
            };

            Assert.False(world.Host.AnyTurnRunning());

            // The scan answers about the chats it started with; the new record is the pump's,
            // and the next question will see it.
            Assert.Equal(new[] { "chat-1", "chat-2" }, world.Backend.TurnQuestions.ToArray());
        }
    }

    /// <summary>
    /// The same invariant under real threads, because the deterministic test above only pins
    /// the one interleaving it stages. Every mutation is on one thread, as the pump's are; only
    /// the question crosses.
    /// </summary>
    [Fact]
    public void TheSessionListSurvivesTheBusyQuestionAndThePumpRunningAtOnce()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();
            string run = world.TrackedRun("chat-x");
            var failures = new List<Exception>();
            var stop = new ManualResetEventSlim();

            var pump = new Thread(() =>
            {
                try
                {
                    for (int i = 0; i < 500 && !stop.IsSet; i++)
                    {
                        world.Host.TrackSession("chat-" + i, run);
                        world.Host.TrackCheck(run);
                        world.Host.FindSession("chat-" + i);
                    }
                }
                catch (Exception failure)
                {
                    lock (failures)
                    {
                        failures.Add(failure);
                    }
                }
                finally
                {
                    stop.Set();
                }
            })
            {
                IsBackground = true,
            };

            pump.Start();
            try
            {
                while (!stop.IsSet)
                {
                    world.Host.AnyTurnRunning();
                }
            }
            catch (Exception failure)
            {
                lock (failures)
                {
                    failures.Add(failure);
                }
            }

            stop.Set();
            Assert.True(pump.Join(TimeSpan.FromSeconds(30)), "the pump thread never finished.");
            Assert.True(failures.Count == 0, failures.Count == 0 ? string.Empty : failures[0].ToString());
        }
    }

    /// <summary>A check folder is never openable as a chat: the page has no id for it.</summary>
    [Fact]
    public void ACheckRecordIsNotReachableThroughAChatIdAndDoesNotAnswerFolderOpen()
    {
        using (var world = new ReviewWorld())
        {
            string check = world.TrackedRun("bracket-check");
            world.Open();
            world.Host.TrackCheck(check);

            world.Receive("folder.open", "o1", new { chat_id = Path.GetFileName(check) });

            Assert.Equal("UnknownChat", world.Reply("error", "o1").GetProperty("error_class").GetString());
            Assert.Empty(world.Opener.Opened);
        }
    }

    // ---- entity.show --------------------------------------------------------------------

    [Fact]
    public void EntityShowHandsThePagesReferenceToTheResolverAndAnswersShown()
    {
        using (var world = new ReviewWorld())
        {
            world.Resolver.Outcome = EntityShowOutcome.Shown("bracket-3");
            world.Open();

            world.Receive("entity.show", "e1", new
            {
                persist_ref = "AQAAAA==",
                persist_ref_scope = "doc-9f2",
                component_id = "cmp-4",
            });

            EntityShowRequest asked = Assert.Single(world.Resolver.Requests);
            Assert.Equal("AQAAAA==", asked.PersistRef);
            Assert.Equal("doc-9f2", asked.PersistRefScope);
            Assert.Equal("cmp-4", asked.ComponentId);

            JsonElement shown = world.Reply("entity.shown", "e1");
            Assert.True(shown.GetProperty("ok").GetBoolean());
            Assert.Equal(0, shown.GetProperty("state_code").GetInt32());
            Assert.Equal("bracket-3", shown.GetProperty("full_path").GetString());
            Assert.True(shown.TryGetProperty("message", out _));
        }
    }

    [Fact]
    public void AReferenceThatNoLongerResolvesReportsTheStateCodeAndTheComponentsFullPath()
    {
        using (var world = new ReviewWorld())
        {
            // 4 is swPersistReferencedObject_Deleted: the entity is gone after a rebuild, so
            // the only thing left that helps is where the component sits in the tree.
            world.Resolver.Outcome = EntityShowOutcome.NotShown(
                4, "deleted: the entity no longer exists", "sub-2/bracket-3");
            world.Open();

            world.Receive("entity.show", "e1", new
            {
                persist_ref = "AQAAAA==",
                persist_ref_scope = "doc-9f2",
                component_id = "cmp-4",
            });

            JsonElement shown = world.Reply("entity.shown", "e1");
            Assert.False(shown.GetProperty("ok").GetBoolean());
            Assert.Equal(4, shown.GetProperty("state_code").GetInt32());
            Assert.Equal("sub-2/bracket-3", shown.GetProperty("full_path").GetString());
            Assert.Contains("deleted", shown.GetProperty("message").GetString()!);
        }
    }

    [Fact]
    public void EntityShowWithoutAReferenceIsRefusedWithoutTouchingSolidworks()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "  ", component_id = "cmp-4" });

            JsonElement error = world.Reply("error", "e1");
            Assert.Equal("InvalidRequest", error.GetProperty("error_class").GetString());
            Assert.Empty(world.Resolver.Requests);
        }
    }

    [Fact]
    public void AResolverThatThrowsIsAnsweredAsANotShownReplyRatherThanAsACrash()
    {
        using (var world = new ReviewWorld())
        {
            // A modal dialog on the application thread, a closed document, a circuit-open
            // gate: the finding card has to be able to say so on the card (spec Scenario 2).
            world.Resolver.Failure = new InvalidOperationException("SOLIDWORKS did not answer");
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "AQAAAA==", component_id = "cmp-4" });

            JsonElement shown = world.Reply("entity.shown", "e1");
            Assert.False(shown.GetProperty("ok").GetBoolean());
            Assert.Contains("SOLIDWORKS did not answer", shown.GetProperty("message").GetString()!);
            Assert.Equal(JsonValueKind.Null, shown.GetProperty("full_path").ValueKind);
        }
    }

    [Fact]
    public void EntityShowIsRefusedWhenTheAddInIsNotAttachedToSolidworks()
    {
        using (var world = new ReviewWorld())
        {
            world.UseResolver = false;
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "AQAAAA==" });

            Assert.Equal("NotAttached", world.Reply("error", "e1").GetProperty("error_class").GetString());
        }
    }

    // ---- report.open / folder.open / log.open -------------------------------------------

    [Fact]
    public void ReportOpenResolvesTheFileFromTheHostsOwnSessionRecordAndIgnoresThePagesPath()
    {
        using (var world = new ReviewWorld())
        {
            string runDirectory = world.TrackedRun("chat-1");
            File.WriteAllText(Path.Combine(runDirectory, "report.md"), "# report");
            world.Open();
            world.Host.TrackSession("chat-1", runDirectory);

            world.Receive("report.open", "o1", new
            {
                chat_id = "chat-1",
                // A page that has been taken over would like this to be the path that opens.
                path = @"C:\Windows\System32\cmd.exe",
                run_dir = @"C:\Windows",
            });

            world.Reply("ok", "o1");
            Assert.Equal(
                new[] { Path.Combine(runDirectory, "report.md") },
                world.Opener.Opened.ToArray());
        }
    }

    [Fact]
    public void FolderOpenOpensThatChatsRunFolder()
    {
        using (var world = new ReviewWorld())
        {
            string runDirectory = world.TrackedRun("chat-1");
            world.Open();
            world.Host.TrackSession("chat-1", runDirectory);

            world.Receive("folder.open", "o1", new { chat_id = "chat-1" });

            world.Reply("ok", "o1");
            Assert.Equal(new[] { runDirectory }, world.Opener.Opened.ToArray());
        }
    }

    [Fact]
    public void LogOpenOpensTheHostsLogFolderAndCreatesItIfItIsNotThereYet()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();

            world.Receive("log.open", "o1", new { });

            world.Reply("ok", "o1");
            Assert.Equal(new[] { world.LogFolder }, world.Opener.Opened.ToArray());
            Assert.True(Directory.Exists(world.LogFolder));
        }
    }

    [Fact]
    public void OpenIsRefusedForAChatTheHostNeverStarted()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();

            world.Receive("folder.open", "o1", new { chat_id = "chat-not-mine" });

            Assert.Equal("UnknownChat", world.Reply("error", "o1").GetProperty("error_class").GetString());
            Assert.Empty(world.Opener.Opened);
        }
    }

    [Fact]
    public void OpenIsRefusedWhenTheSessionRecordPointsOutsideTheRunRoot()
    {
        using (var world = new ReviewWorld())
        {
            // A run_root that changed under a live session, or a record built from a path that
            // walks back out of it: the check is at the shell, not at the record.
            string outside = Path.Combine(world.Settings.RunRoot, "..", "elsewhere");
            Directory.CreateDirectory(Path.GetFullPath(outside));
            world.Open();
            world.Host.TrackSession("chat-1", outside);

            world.Receive("folder.open", "o1", new { chat_id = "chat-1" });
            world.Receive("report.open", "o2", new { chat_id = "chat-1" });

            Assert.Equal("PathRefused", world.Reply("error", "o1").GetProperty("error_class").GetString());
            Assert.Equal("PathRefused", world.Reply("error", "o2").GetProperty("error_class").GetString());
            Assert.Empty(world.Opener.Opened);
        }
    }

    [Fact]
    public void ReportOpenIsRefusedBeforeTheReportHasBeenWritten()
    {
        using (var world = new ReviewWorld())
        {
            string runDirectory = world.TrackedRun("chat-1");
            world.Open();
            world.Host.TrackSession("chat-1", runDirectory);

            world.Receive("report.open", "o1", new { chat_id = "chat-1" });

            JsonElement error = world.Reply("error", "o1");
            Assert.Equal("NotFound", error.GetProperty("error_class").GetString());
            Assert.Contains("report.md", error.GetProperty("message").GetString()!);
            Assert.Empty(world.Opener.Opened);
        }
    }

    [Fact]
    public void AnOpenerThatFailsIsReportedRatherThanThrownIntoWebView2()
    {
        using (var world = new ReviewWorld())
        {
            string runDirectory = world.TrackedRun("chat-1");
            world.Opener.Failure = new System.ComponentModel.Win32Exception("no application is associated");
            world.Open();
            world.Host.TrackSession("chat-1", runDirectory);

            world.Receive("folder.open", "o1", new { chat_id = "chat-1" });

            JsonElement error = world.Reply("error", "o1");
            Assert.Contains("no application is associated", error.GetProperty("message").GetString()!);
        }
    }

    [Fact]
    public void TheOpenerIsNeverCalledWithAPathOutsideTheRunRootOrTheLogFolder()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();
            world.Host.TrackSession("traversal", Path.Combine(world.Settings.RunRoot, "..", "..", "Windows"));
            world.Host.TrackSession("unc", @"\\server\share\runs");
            world.Host.TrackSession("device", @"\\.\PhysicalDrive0");
            world.Host.TrackSession("blank", string.Empty);

            foreach (string chatId in new[] { "traversal", "unc", "device", "blank" })
            {
                world.Receive("folder.open", "open-" + chatId, new { chat_id = chatId });
                world.Receive("report.open", "report-" + chatId, new { chat_id = chatId });
            }

            Assert.Empty(world.Opener.Opened);
        }
    }

    // ---- document.changed ---------------------------------------------------------------

    [Fact]
    public void DocumentChangedPostsThePathAndConfigurationTheHostSees()
    {
        using (var world = new ReviewWorld())
        {
            world.Open();
            world.Document = new PageDocument(@"C:\parts\other.sldprt", "Machined");

            world.Host.DocumentChanged();

            JsonElement changed = world.LastPosted("document.changed");
            Assert.Equal(@"C:\parts\other.sldprt", changed.GetProperty("path").GetString());
            Assert.Equal("Machined", changed.GetProperty("configuration").GetString());
        }
    }

    [Fact]
    public void ClosingTheLastDocumentPostsANullDocumentChanged()
    {
        using (var world = new ReviewWorld())
        {
            world.Document = new PageDocument(@"C:\parts\other.sldprt", "Machined");
            world.Open();
            world.Document = null;

            world.Host.DocumentChanged();

            Assert.Equal(JsonValueKind.Null, world.LastPosted("document.changed").ValueKind);
        }
    }

    // ---- the redaction choke point (FR-015) ---------------------------------------------

    /// <summary>
    /// Everything the add-in shows the engineer about a failure goes through the host, and the
    /// host is the only thing that knows the key. `StartBackend` reports a backend that would
    /// not start by posting a `status` message, and the exception it reports is not always the
    /// one <see cref="BackendProcess"/> already redacted - a job-object failure, a key-resolution
    /// failure, or anything thrown before the redacting wrapper arrives verbatim - so the
    /// redaction has to happen here rather than at each call site (FR-015).
    /// </summary>
    [Fact]
    public void PostStatusRedactsTheConfiguredKeyBeforeThePageSeesIt()
    {
        using (var world = new ReviewWorld())
        {
            world.Settings.SetApiKey(Secret);
            world.Open();

            world.Host.PostStatus("error", "the launcher refused: Authorization: Bearer " + Secret);

            JsonElement status = world.LastPosted("status");
            Assert.Equal("error", status.GetProperty("stage").GetString());

            string message = status.GetProperty("message").GetString()!;
            Assert.DoesNotContain(Secret, message);
            Assert.Contains(Redaction.Mask, message);
            world.AssertNothingPostedContains(Secret);
        }
    }

    /// <summary>
    /// The add-in log is the other place a raw exception lands (`addin.log`), and
    /// `Exception.ToString()` carries every inner exception's message - which is exactly where
    /// the unredacted launcher failure lives, because `BackendProcess` redacts only the outer
    /// message and attaches the raw failure as the inner one. FR-015 forbids a key in a log
    /// file just as firmly as in a message, so the same masking is available to that caller.
    /// </summary>
    [Fact]
    public void RedactMasksTheConfiguredKeyForWhoeverIsAboutToWriteALogLine()
    {
        using (var world = new ReviewWorld())
        {
            world.Settings.SetApiKey(Secret);
            world.Open();

            var failure = new InvalidOperationException(
                "the backend did not start",
                new InvalidOperationException("uv run failed with OPENAI_API_KEY=" + Secret));

            string line = world.Host.Redact(failure.ToString());

            Assert.DoesNotContain(Secret, line);
            Assert.Contains(Redaction.Mask, line);
            Assert.Contains("the backend did not start", line);
        }
    }

    // ---- the world ----------------------------------------------------------------------

    /// <summary>
    /// A <see cref="ReviewHost"/> with every seam faked and a temporary run root.
    ///
    /// Deliberately a second copy of <see cref="PageMessageTests"/>' harness rather than a
    /// shared one: that file is the Settings contract's and this one is the review flow's,
    /// they fake different seams, and a shared harness would make each file's fixture depend
    /// on the other file's needs. The duplication is the `Receive`/`Reply` plumbing only.
    /// </summary>
    private sealed class ReviewWorld : IDisposable
    {
        private readonly string _root;
        private ReviewHost? _host;

        public ReviewWorld()
        {
            _root = Path.Combine(Path.GetTempPath(), "SwReview.ReviewHost.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            SettingsPath = Path.Combine(_root, "settings.json");
            LogFolder = Path.Combine(_root, "logs");
            Settings = UserSettings.Defaults();
            Settings.RunRoot = Path.Combine(_root, "runs");
        }

        public string SettingsPath { get; }

        public string LogFolder { get; }

        public UserSettings Settings { get; }

        public FakeBackend Backend { get; } = new FakeBackend();

        public FakeDump Dump { get; } = new FakeDump();

        public FakeResolver Resolver { get; } = new FakeResolver();

        public FakeOpener Opener { get; } = new FakeOpener();

        public PageDocument? Document { get; set; }

        public DateTime Now { get; set; } = Stamp;

        public BridgeConfig? Bridge { get; set; }

        public string Engineer { get; } = "test-engineer";

        public bool UseResolver { get; set; } = true;

        public List<string> Posted { get; } = new List<string>();

        public ReviewHost Host => _host ?? throw new InvalidOperationException("call Open() first");

        public void Open()
        {
            if (!File.Exists(SettingsPath))
            {
                Settings.Save(SettingsPath);
            }

            var options = new ReviewHostOptions(new FakeChannel(Posted), Backend, SettingsPath)
            {
                BuildMode = BuildMode.Development,
                LogFolder = LogFolder,
                CurrentDocument = () => Document,
                Environment = _ => null,
                Dump = Dump,
                EntityResolver = UseResolver ? Resolver : null,
                Opener = Opener,
                Bridge = Bridge,
                Engineer = Engineer,
                Now = () => Now,
            };
            _host = new ReviewHost(options);
        }

        /// <summary>A run folder inside the run root, as a real review would have left one.</summary>
        public string TrackedRun(string chatId)
        {
            string directory = Path.Combine(Settings.RunRoot, "20260913-142530-" + chatId);
            Directory.CreateDirectory(directory);
            return directory;
        }

        /// <summary>
        /// A one-document package in <paramref name="runDirectory"/> (T076), under the name a
        /// review writes or, for a remodel run folder, the name the before-dump is renamed to.
        /// </summary>
        public void WritePackage(
            string runDirectory,
            string documentId,
            string documentPath,
            string packageName = "package.json")
        {
            var package = new SwReview.Extractor.Ir.EvidencePackage();
            package.Documents.Add(new SwReview.Extractor.Ir.Document
            {
                DocumentId = documentId,
                Kind = SwReview.Extractor.Ir.DocumentKind.Part,
                FileName = Path.GetFileName(documentPath),
                Path = documentPath,
                ActiveConfiguration = "Default",
            });

            File.WriteAllText(
                Path.Combine(runDirectory, packageName),
                SwReview.Extractor.Ir.PackageSerializer.Serialize(package));
        }

        public string[] RunFolders() =>
            Directory.Exists(Settings.RunRoot) ? Directory.GetDirectories(Settings.RunRoot) : new string[0];

        public void Receive(string type, string id, object payload) =>
            Host.Receive(JsonSerializer.Serialize(new { type, id, payload }));

        /// <summary>The single reply of <paramref name="type"/> that echoes <paramref name="id"/>.</summary>
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
                + string.Join(" | ", Posted.Select(TypeOf)));
            return matches[0];
        }

        /// <summary>Every message of <paramref name="type"/>, in the order they were posted.</summary>
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

        public void AssertNothingPostedContains(string secret)
        {
            foreach (string message in Posted)
            {
                Assert.DoesNotContain(secret, message);
            }
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

        private static string TypeOf(string message) =>
            JsonDocument.Parse(message).RootElement.GetProperty("type").GetString() ?? "?";
    }

    private sealed class FakeChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public FakeChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json) => _posted.Add(json);
    }

    private sealed class FakeDump : IReviewDump
    {
        public int Runs { get; private set; }

        public string? LastDirectory { get; private set; }

        public List<string> Progress { get; } = new List<string>();

        public Exception? Failure { get; set; }

        /// <summary>The profile the host asked for; the review path must stay on Full.</summary>
        public DumpProfile? LastProfile { get; private set; }

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
                components: 12,
                gaps: Gaps,
                unexamined: Unexamined);
        }
    }

    private sealed class FakeResolver : IEntityResolver
    {
        public List<EntityShowRequest> Requests { get; } = new List<EntityShowRequest>();

        public EntityShowOutcome Outcome { get; set; } = EntityShowOutcome.Shown(null);

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

    private sealed class FakeOpener : IPathOpener
    {
        public List<string> Opened { get; } = new List<string>();

        public Exception? Failure { get; set; }

        public void Open(string path)
        {
            Opened.Add(path);
            if (Failure != null)
            {
                throw Failure;
            }
        }
    }

    private sealed class FakeBackend : IBackendClient
    {
        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(51234, "0FAKEtoken");

        public List<NewSessionRequest> Created { get; } = new List<NewSessionRequest>();

        public string NextChatId { get; set; } = "chat-1";

        public BackendRequestException? CreateFailure { get; set; }

        /// <summary>Every chat id the host asked about, so a skipped record can be proven skipped.</summary>
        public List<string> TurnQuestions { get; } = new List<string>();

        public HashSet<string> Running { get; } = new HashSet<string>(StringComparer.Ordinal);

        /// <summary>Thrown for a chat this fake was never told about (T076).</summary>
        public Exception? TurnRunningFailure { get; set; }

        /// <summary>
        /// Runs inside the question, before it is answered. The real one is an HTTP round trip,
        /// which is where the page-message pump gets to deliver the next message.
        /// </summary>
        public Action<string>? OnTurnQuestion { get; set; }

        public IReadOnlyList<ModelChoice> ListModels(string provider) => new ModelChoice[0];

        public bool IsTurnRunning(string chatId)
        {
            TurnQuestions.Add(chatId);
            OnTurnQuestion?.Invoke(chatId);
            if (TurnRunningFailure != null)
            {
                throw TurnRunningFailure;
            }

            return Running.Contains(chatId);
        }

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
        }

        public ChatSessionHandle CreateSession(NewSessionRequest request)
        {
            if (CreateFailure != null)
            {
                throw CreateFailure;
            }

            Created.Add(request);
            return new ChatSessionHandle(NextChatId, "review-" + NextChatId);
        }
    }
}
