using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Review;
using SwReview.AddIn.Standards;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T075: the Standards tab's half of `contracts/standards-check.md` sections 2 and 3 - `ready`,
/// `standards.start`, and the unsolicited messages. The four shared rows are
/// <see cref="PaneActions"/>'s and are proved identical across three hosts in
/// <see cref="PaneActionsTests"/> rather than re-asserted here.
///
/// The host does very little on purpose, and what it does not do is the design:
///
/// <b>It evaluates nothing and it never reads the profile.</b> It checks that a profile path is
/// configured and that the file can be opened, and stops: the schema is expressed in exactly
/// one place, `checks/standards/profile.py`, and a host that parsed the file would be a second
/// one to keep in step (FR-002). The page calls `POST /checks/standards` itself with the token,
/// the origin and the `profile_path` it received in `init`.
///
/// <b>A refusal writes no run folder.</b> The profile check happens before anything is created
/// or dumped, so pressing the button with no profile configured leaves the run root exactly as
/// it was. The one case where a folder does exist without a result is a `ProfileInvalid`
/// refusal from the backend, which happens after the dump - and that is the page's to render as
/// an empty run (`contracts/profile.md`).
///
/// <b>It grades all three document kinds.</b> Unlike the Model check tab, which is part-only,
/// a part, an assembly and a drawing are all startable; anything else is `UnsupportedKind`, and
/// a document that has never been saved is `NeverSaved`, because a document with no path has
/// nothing to match against the profile's library prefixes or its part-number pattern.
/// </summary>
public sealed class StandardsHostTests
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 16, 10, 15, 32);

    // ---- ready / init -------------------------------------------------------------------

    [Fact]
    public void ReadyAnswersInitWithTheBackendTheTokenTheRunRootTheProfileAndTheDocument()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "AsBuilt");
            world.WriteProfile();
            world.Open();

            world.Receive("ready", "r1", new { });

            JsonElement init = world.Reply("init", "r1");
            Assert.Equal(51234, init.GetProperty("backend").GetProperty("port").GetInt32());

            // The page's OWN origin under `/__backend`, never the backend's loopback one: the
            // page calls the check route through the host's same-origin proxy.
            Assert.Equal(
                "https://swreview.invalid/__backend",
                init.GetProperty("backend").GetProperty("origin").GetString());
            Assert.DoesNotContain(
                "127.0.0.1",
                init.GetProperty("backend").GetProperty("origin").GetString()!,
                StringComparison.Ordinal);
            Assert.Equal("0FAKEtoken", init.GetProperty("token").GetString());
            Assert.Equal(world.RunRoot, init.GetProperty("run_root").GetString());

            // The path only. The page relays it on `POST /checks/standards`; no profile VALUE
            // ever travels on any message or any request (FR-001, FR-034).
            Assert.Equal(world.ProfilePath, init.GetProperty("profile_path").GetString());

            JsonElement document = init.GetProperty("document");
            Assert.Equal(@"C:\parts\bracket.SLDASM", document.GetProperty("path").GetString());
            Assert.Equal("AsBuilt", document.GetProperty("configuration").GetString());
            Assert.Equal("assembly", document.GetProperty("kind").GetString());

            Assert.Equal(JsonValueKind.Null, init.GetProperty("latest_check").ValueKind);
        }
    }

    [Fact]
    public void InitCarriesANullProfilePathWhenNoProfileIsConfigured()
    {
        using (var world = new StandardsWorld())
        {
            world.ProfilePath = null;
            world.Open();

            world.Receive("ready", "r1", new { });

            Assert.Equal(
                JsonValueKind.Null, world.Reply("init", "r1").GetProperty("profile_path").ValueKind);
        }
    }

    [Fact]
    public void InitCarriesNoDocumentAndNoBackendWhenThereIsNeither()
    {
        using (var world = new StandardsWorld())
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

    /// <summary>
    /// All three kinds are reported, because all three are gradable and the page uses the kind
    /// to say <i>what</i> will be graded rather than whether anything can be.
    /// </summary>
    [Theory]
    [InlineData(@"C:\parts\bracket.SLDPRT", "part")]
    [InlineData(@"C:\parts\bracket assy.SLDASM", "assembly")]
    [InlineData(@"C:\parts\sheet.slddrw", "drawing")]
    public void TheDocumentKindIsReportedSoThePageNeverGuessesFromThePath(string path, string kind)
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(path, "Default");
            world.Open();

            world.Receive("ready", "r1", new { });

            Assert.Equal(
                kind,
                world.Reply("init", "r1").GetProperty("document").GetProperty("kind").GetString());
        }
    }

    [Fact]
    public void ASecondReadyCarriesTheBackendThatStartedAfterTheFirstOne()
    {
        using (var world = new StandardsWorld())
        {
            world.Endpoint = null;
            world.Open();

            world.Receive("ready", "r1", new { });
            Assert.Equal(JsonValueKind.Null, world.Reply("init", "r1").GetProperty("backend").ValueKind);

            world.Endpoint = new BackendEndpoint(51234, "0FAKEtoken");
            world.Receive("ready", "r2", new { });

            JsonElement second = world.Reply("init", "r2");
            Assert.Equal(51234, second.GetProperty("backend").GetProperty("port").GetInt32());
            Assert.Equal("0FAKEtoken", second.GetProperty("token").GetString());
        }
    }

    [Fact]
    public void InitCarriesTheLatestStandardsRunOnceOneHasRun()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile();
            world.Open();
            world.Receive("standards.start", "s1", new { });

            world.Receive("ready", "r2", new { });

            JsonElement latest = world.Reply("init", "r2").GetProperty("latest_check");
            Assert.Equal(
                Path.Combine(world.RunRoot, "20260916-101532-bracket-standards"),
                latest.GetProperty("run_dir").GetString());
            Assert.False(string.IsNullOrWhiteSpace(latest.GetProperty("at").GetString()));
        }
    }

    /// <summary>
    /// SC-009: the tab is opened after a restart and the newest standards run is read back from
    /// the run root, which is in-process state nothing enumerated before this feature.
    /// </summary>
    [Fact]
    public void InitFindsTheNewestStandardsRunOnDiskWhenThisSessionHasRunNone()
    {
        using (var world = new StandardsWorld())
        {
            world.Open();
            string folder = world.MakeRunFolder("20260915-081500-bracket-standards");

            world.Receive("ready", "r1", new { });

            JsonElement latest = world.Reply("init", "r1").GetProperty("latest_check");
            Assert.Equal(folder, latest.GetProperty("run_dir").GetString());
        }
    }

    /// <summary>
    /// Neither tab's latest check is ever the other tab's: the scan answers from the folder
    /// names alone, and a `-check` folder is a Model check's (`contracts/standards-check.md`
    /// section 4, difference D10).
    /// </summary>
    [Fact]
    public void InitNeverNamesAModelCheckFolderAsTheLatestStandardsRun()
    {
        using (var world = new StandardsWorld())
        {
            world.Open();
            world.MakeRunFolder("20260916-101532-bracket-check");
            world.MakeRunFolder("20260916-101532-bracket");

            world.Receive("ready", "r1", new { });

            Assert.Equal(
                JsonValueKind.Null, world.Reply("init", "r1").GetProperty("latest_check").ValueKind);
        }
    }

    /// <summary>
    /// The run `init` named from disk is one the host can also OPEN. The scan records the
    /// folder as well as reporting it, so `folder.open` and `report.open` - which take an id
    /// and never a path - resolve it through the host's own records. Without the record the
    /// page would render a check read back after a restart with two buttons that always refuse
    /// (`contracts/standards-check.md` section 4; pane-host-messages.md).
    /// </summary>
    [Fact]
    public void ARunFoundOnDiskCanBeOpenedByTheIdInitNamedItBy()
    {
        using (var world = new StandardsWorld())
        {
            world.Open();
            string folder = world.MakeRunFolder("20260915-081500-bracket-standards");
            File.WriteAllText(Path.Combine(folder, "report.md"), "# report");

            world.Receive("ready", "r1", new { });
            world.Receive(
                "folder.open",
                "o1",
                new Dictionary<string, object?> { { "run_id", "20260915-081500-bracket-standards" } });
            world.Receive(
                "report.open",
                "o2",
                new Dictionary<string, object?> { { "run_id", "20260915-081500-bracket-standards" } });

            world.Reply("ok", "o1");
            world.Reply("ok", "o2");
            Assert.Equal(
                new[] { folder, Path.Combine(folder, "report.md") },
                world.Opener.Opened.ToArray());
            Assert.Empty(world.AllPosted("error"));
        }
    }

    /// <summary>
    /// The run found on disk is reported and recorded, but it never becomes the PANE's latest
    /// run: this session did not make it, and re-pointing the pane at an old folder would move
    /// `entity.show` and the Ask tab off whatever the engineer is working in. The first run
    /// this session makes is still registered, so the scan has taken nothing away.
    /// </summary>
    [Fact]
    public void ARunFoundOnDiskIsNeverRegisteredAsThePanesLatestRun()
    {
        using (var world = new StandardsWorld())
        {
            world.Open();
            world.MakeRunFolder("20260915-081500-bracket-standards");

            world.Receive("ready", "r1", new { });

            Assert.Empty(world.Registered);

            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile();

            world.Receive("standards.start", "s1", new { });

            Assert.Equal(
                new[] { Path.Combine(world.RunRoot, "20260916-101532-bracket-standards") },
                world.Registered.ToArray());
        }
    }

    // ---- standards.start: the refusals --------------------------------------------------

    [Fact]
    public void StandardsStartIsRefusedWithNoDocumentOpen()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = null;
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("NoDocument", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    [Fact]
    public void StandardsStartIsRefusedWhenTheAddInIsNotAttachedToSolidworks()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile();
            world.UseDump = false;
            world.Open();

            world.Receive("standards.start", "s1", new { });

            Assert.Equal(
                "NotAttached", world.Reply("error", "s1").GetProperty("error_class").GetString());
            Assert.Empty(world.RunFolders());
        }
    }

    /// <summary>
    /// A document that has never been saved has no path to match against the profile's library
    /// prefixes or its part-number pattern, so the run is refused naming the reason. The macro
    /// is silent in exactly this case, because it decides the document kind from the last three
    /// characters of a path that is empty (difference k).
    /// </summary>
    [Fact]
    public void StandardsStartIsRefusedForADocumentThatHasNeverBeenSaved()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(string.Empty, "Default");
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("NeverSaved", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    [Theory]
    [InlineData(@"C:\parts\bracket.step")]
    [InlineData(@"C:\parts\bracket.sldlfp")]
    public void StandardsStartIsRefusedForADocumentKindTheChecksAreNotWrittenFor(string path)
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(path, "Default");
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("UnsupportedKind", error.GetProperty("error_class").GetString());
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    /// <summary>
    /// The profile check comes before the run folder and before the dump: there is no profile,
    /// so there is nothing to grade against, and a folder left behind would render as an empty
    /// run the engineer has to work out the meaning of (FR-002).
    /// </summary>
    [Fact]
    public void StandardsStartIsRefusedWithNoProfileConfiguredAndNothingIsCreatedOrDumped()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.ProfilePath = null;
            world.Open();

            world.Receive("standards.start", "s1", new { });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("NoProfile", error.GetProperty("error_class").GetString());

            // The message names the setting, because that is what the engineer has to change.
            Assert.Contains("StandardsProfilePath", error.GetProperty("message").GetString()!);
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
            Assert.Empty(world.Registered);
        }
    }

    [Fact]
    public void StandardsStartIsRefusedWhenTheProfileFileIsNotThereAndNothingIsCreated()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.Open();

            world.Receive("standards.start", "s1", new { });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("NoProfile", error.GetProperty("error_class").GetString());
            Assert.Contains(world.ProfilePath!, error.GetProperty("message").GetString()!);
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    [Fact]
    public void StandardsStartIsRefusedWhenTheProfileFileCannotBeOpened()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");

            // A directory where the file should be: the path is configured and the thing at it
            // cannot be opened for reading, which is the same refusal as an ACL or a lock.
            Directory.CreateDirectory(world.ProfilePath!);
            world.Open();

            world.Receive("standards.start", "s1", new { });

            Assert.Equal(
                "NoProfile", world.Reply("error", "s1").GetProperty("error_class").GetString());
            Assert.Equal(0, world.Dump.Runs);
            Assert.Empty(world.RunFolders());
        }
    }

    /// <summary>
    /// The schema is expressed in exactly one place and it is not here. A profile that parses
    /// as nothing at all still starts the run: the backend refuses it with `ProfileInvalid`
    /// naming the field, and the page renders the folder as an empty run (FR-002).
    /// </summary>
    [Fact]
    public void AProfileThatIsReadableButNotValidStillStartsTheRunBecauseTheHostNeverReadsIt()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile("this: is: not: a: profile: [");
            world.Open();

            world.Receive("standards.start", "s1", new { });

            world.Reply("standards.extracted", "s1");
            Assert.Equal(1, world.Dump.Runs);
        }
    }

    // ---- standards.start: the happy path ------------------------------------------------

    [Theory]
    [InlineData(@"C:\parts\bracket.SLDPRT")]
    [InlineData(@"C:\parts\bracket.SLDASM")]
    [InlineData(@"C:\parts\bracket.SLDDRW")]
    public void StandardsStartCreatesTheFolderRunsTheStandardsDumpRegistersItAndReplies(string path)
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(path, "AsBuilt");
            world.Dump.Documents = 3;
            world.Dump.Features = 27;
            world.Dump.CutListItems = 4;
            world.Dump.DrawingSheets = 2;
            world.Dump.Gaps = 5;
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            string expected = Path.Combine(world.RunRoot, "20260916-101532-bracket-standards");
            Assert.True(Directory.Exists(expected), $"the host did not create {expected}");
            Assert.Equal(expected, world.Dump.LastDirectory);
            Assert.Equal(1, world.Dump.Runs);

            // The whole point of the profile: the two new phases run and the four expensive
            // ones do not, and the package records which profile wrote it (FR-027).
            Assert.Equal(DumpProfile.Standards, world.Dump.LastProfile);

            // Registered before the page hears about it, so a `POST /checks/standards` sent the
            // instant `standards.extracted` arrives resolves ids through this folder's package.
            Assert.Equal(new[] { expected }, world.Registered.ToArray());

            JsonElement extracted = world.Reply("standards.extracted", "s1");
            Assert.Equal(expected, extracted.GetProperty("run_dir").GetString());
            Assert.Equal(path, extracted.GetProperty("document").GetString());
            Assert.Equal("AsBuilt", extracted.GetProperty("configuration").GetString());
            Assert.Equal(5, extracted.GetProperty("gaps").GetInt32());

            JsonElement counts = extracted.GetProperty("counts");
            Assert.Equal(3, counts.GetProperty("documents").GetInt32());
            Assert.Equal(27, counts.GetProperty("features").GetInt32());
            Assert.Equal(4, counts.GetProperty("cut_list_items").GetInt32());
            Assert.Equal(2, counts.GetProperty("drawing_sheets").GetInt32());
        }
    }

    /// <summary>
    /// The host stops at `standards.extracted`: the page calls `POST /checks/standards` itself
    /// with the token and the origin it received in `init`. There is one no-language-model
    /// evaluation entry point and it is in Python (FR-024).
    /// </summary>
    [Fact]
    public void TheHostStopsAtTheExtractionAndNeverProducesAResult()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            string[] types = world.PostedTypes();
            Assert.Contains("standards.extracted", types);
            Assert.DoesNotContain("standards.result", types);
            Assert.DoesNotContain("standards.checked", types);
        }
    }

    /// <summary>
    /// A count the dump did not report is reported as absent. A zero would read as "this
    /// assembly has no cut-list items", which is a statement about the design rather than about
    /// the extract (constitution: never write a default for engineering data).
    /// </summary>
    [Fact]
    public void ACountTheDumpDidNotReportIsNullRatherThanZero()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.Dump.Documents = 3;
            world.Dump.Features = 27;
            world.Dump.CutListItems = null;
            world.Dump.DrawingSheets = null;
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            JsonElement counts = world.Reply("standards.extracted", "s1").GetProperty("counts");
            Assert.Equal(JsonValueKind.Null, counts.GetProperty("cut_list_items").ValueKind);
            Assert.Equal(JsonValueKind.Null, counts.GetProperty("drawing_sheets").ValueKind);
        }
    }

    [Fact]
    public void StandardsStartReportsProgressAsExtractingStatusMessagesAndEndsReady()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.Dump.Progress.Add("Reading the component tree...");
            world.Dump.Progress.Add("Reading cut lists...");
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            string[] stages = world.AllPosted("status")
                .Select(payload => payload.GetProperty("stage").GetString()!).ToArray();
            string[] messages = world.AllPosted("status")
                .Select(payload => payload.GetProperty("message").GetString()!).ToArray();

            Assert.Equal("ready", stages.Last());
            Assert.All(stages.Take(stages.Length - 1), stage => Assert.Equal("extracting", stage));
            Assert.Contains("bracket", messages[0]);
            Assert.Contains("Reading the component tree...", messages);
            Assert.Contains("Reading cut lists...", messages);
            Assert.True(
                Array.IndexOf(messages, "Reading the component tree...")
                    < Array.IndexOf(messages, "Reading cut lists..."),
                "the dump's progress messages reached the page out of order");
        }
    }

    [Fact]
    public void TwoRunsInTheSameSecondGetDistinctFoldersAndTheSecondBecomesTheLatest()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });
            world.Receive("standards.start", "s2", new { });

            string first = world.Reply("standards.extracted", "s1").GetProperty("run_dir").GetString()!;
            string second = world.Reply("standards.extracted", "s2").GetProperty("run_dir").GetString()!;

            Assert.Equal(Path.Combine(world.RunRoot, "20260916-101532-bracket-standards"), first);
            Assert.Equal(Path.Combine(world.RunRoot, "20260916-101532-bracket-standards-2"), second);
            Assert.Equal(new[] { first, second }, world.Registered.ToArray());
        }
    }

    // ---- standards.start: the failures --------------------------------------------------

    /// <summary>
    /// The folder is left behind on purpose: whatever the dump did write is the evidence for
    /// why it stopped (constitution Principle I). It is not registered, because a half-written
    /// package must not become the folder `entity.show` and the Ask tab read from.
    /// </summary>
    [Fact]
    public void ADumpThatFailsIsReportedAndTheFolderIsNeitherRegisteredNorDeleted()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.Dump.Failure = new InvalidOperationException("the component tree could not be read");
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { });

            JsonElement error = world.Reply("error", "s1");
            Assert.Equal("ExtractionFailed", error.GetProperty("error_class").GetString());
            Assert.Contains(
                "the component tree could not be read", error.GetProperty("message").GetString()!);
            Assert.Equal("error", world.LastPosted("status").GetProperty("stage").GetString());

            Assert.Empty(world.Registered);
            Assert.Single(world.RunFolders());
        }
    }

    [Fact]
    public void ARunRootThatCannotBeWrittenIsReportedRatherThanThrown()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile();
            world.BlankRunRoot = true;
            world.Open();

            world.Receive("standards.start", "s1", new { });

            Assert.Equal(
                "RunFolderFailed", world.Reply("error", "s1").GetProperty("error_class").GetString());
            Assert.Equal(0, world.Dump.Runs);
        }
    }

    // ---- the envelope -------------------------------------------------------------------

    /// <summary>
    /// `standards.start` takes no payload: there is no scope, because all sixteen checks run on
    /// every run and the document kinds decide which apply (difference D1). A page that sends
    /// one anyway is answered exactly as one that sends none.
    /// </summary>
    [Fact]
    public void StandardsStartTakesNoPayloadAndOneSentAnywayChangesNothing()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDASM", "Default");
            world.WriteProfile();
            world.Open();

            world.Receive("standards.start", "s1", new { scope = "drawing", checks = new[] { "one" } });

            JsonElement extracted = world.Reply("standards.extracted", "s1");
            Assert.Equal(
                Path.Combine(world.RunRoot, "20260916-101532-bracket-standards"),
                extracted.GetProperty("run_dir").GetString());
            Assert.Equal(DumpProfile.Standards, world.Dump.LastProfile);
        }
    }

    [Fact]
    public void AMessageTypeTheHostDoesNotHandleIsAnsweredWithAnError()
    {
        using (var world = new StandardsWorld())
        {
            world.Open();

            world.Receive("check.start", "x1", new { scope = "part" });

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
        using (var world = new StandardsWorld())
        {
            world.Open();

            world.Host.Receive(json);

            Assert.NotEmpty(world.AllPosted("error"));
        }
    }

    // ---- the unsolicited set --------------------------------------------------------------

    [Fact]
    public void DocumentChangedPostsThePathTheConfigurationAndTheKindTheHostSees()
    {
        using (var world = new StandardsWorld())
        {
            world.Open();
            world.Document = new PageDocument(@"C:\parts\sheet.SLDDRW", "Default");

            world.Host.DocumentChanged();

            JsonElement changed = world.LastPosted("document.changed");
            Assert.Equal(@"C:\parts\sheet.SLDDRW", changed.GetProperty("path").GetString());
            Assert.Equal("Default", changed.GetProperty("configuration").GetString());

            // The page decides from the kind WHAT will be graded - a drawing fans out to the
            // models its views reference - so it is sent rather than inferred from the path.
            Assert.Equal("drawing", changed.GetProperty("kind").GetString());
        }
    }

    [Fact]
    public void ClosingTheLastDocumentPostsANullDocumentChanged()
    {
        using (var world = new StandardsWorld())
        {
            world.Document = new PageDocument(@"C:\parts\sheet.SLDDRW", "Default");
            world.Open();
            world.Document = null;

            world.Host.DocumentChanged();

            Assert.Equal(JsonValueKind.Null, world.LastPosted("document.changed").ValueKind);
        }
    }

    [Fact]
    public void TheHostPostsTheBackendStagesAndTheBackendStoppedEnvelopeUnchanged()
    {
        using (var world = new StandardsWorld())
        {
            world.Open();

            world.Host.PostStatus("backend_starting", "Starting the backend...");
            world.Host.Post("backend.stopped", new Dictionary<string, object?>
            {
                { "exit_code", 3 },
                { "log_path", @"C:\logs\backend.log" },
            });

            Assert.Equal(
                "backend_starting", world.LastPosted("status").GetProperty("stage").GetString());
            JsonElement stopped = world.LastPosted("backend.stopped");
            Assert.Equal(3, stopped.GetProperty("exit_code").GetInt32());
            Assert.Equal(@"C:\logs\backend.log", stopped.GetProperty("log_path").GetString());
        }
    }

    // ---- the world ----------------------------------------------------------------------

    private sealed class StandardsWorld : IDisposable
    {
        private readonly string _root;
        private StandardsHost? _host;

        public StandardsWorld()
        {
            _root = Path.Combine(
                Path.GetTempPath(), "SwReview.StandardsHost.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            RunRoot = Path.Combine(_root, "runs");
            Directory.CreateDirectory(RunRoot);
            LogFolder = Path.Combine(_root, "logs");
            ProfilePath = Path.Combine(_root, "standards.yaml");
        }

        public string RunRoot { get; }

        public string LogFolder { get; }

        /// <summary>The configured path; the file behind it is written by <see cref="WriteProfile"/>.</summary>
        public string? ProfilePath { get; set; }

        public bool BlankRunRoot { get; set; }

        public PageDocument? Document { get; set; }

        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(51234, "0FAKEtoken");

        public FakeStandardsDump Dump { get; } = new FakeStandardsDump();

        public bool UseDump { get; set; } = true;

        public List<string> Registered { get; } = new List<string>();

        public FakeOpener Opener { get; } = new FakeOpener();

        public List<string> Posted { get; } = new List<string>();

        public StandardsHost Host =>
            _host ?? throw new InvalidOperationException("call Open() first");

        /// <summary>
        /// Writes the file the configured path points at. Its CONTENT is never read by the
        /// host, which is why the default is a comment: if a test passes only because the host
        /// parsed something, this is where it would show.
        /// </summary>
        public void WriteProfile(string content = "# a profile the host never reads\n") =>
            File.WriteAllText(ProfilePath!, content);

        public string MakeRunFolder(string name)
        {
            string directory = Path.Combine(RunRoot, name);
            Directory.CreateDirectory(directory);
            return directory;
        }

        public void Open()
        {
            _host = new StandardsHost(new StandardsHostOptions(
                new CollectingChannel(Posted), () => BlankRunRoot ? "   " : RunRoot)
            {
                Backend = () => Endpoint,
                CurrentDocument = () => Document,
                ProfilePath = () => ProfilePath,
                Dump = UseDump ? Dump : null,
                RegisterLatestRun = directory => Registered.Add(directory),
                Opener = () => Opener,
                LogFolder = () => LogFolder,
                Now = () => Stamp,
            });
        }

        public string[] RunFolders() =>
            Directory.Exists(RunRoot) ? Directory.GetDirectories(RunRoot) : new string[0];

        public void Receive(string type, string id, object payload) =>
            Host.Receive(JsonSerializer.Serialize(new { type, id, payload }));

        public string[] PostedTypes() => Posted
            .Select(message => JsonDocument.Parse(message).RootElement.GetProperty("type").GetString()!)
            .ToArray();

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

    /// <summary>Records what was opened instead of shelling out to Windows.</summary>
    private sealed class FakeOpener : IPathOpener
    {
        public List<string> Opened { get; } = new List<string>();

        public void Open(string path) => Opened.Add(path);
    }

    private sealed class FakeStandardsDump : IReviewDump
    {
        public int Runs { get; private set; }

        public string? LastDirectory { get; private set; }

        public DumpProfile? LastProfile { get; private set; }

        public List<string> Progress { get; } = new List<string>();

        public Exception? Failure { get; set; }

        public int? Documents { get; set; }

        public int? Features { get; set; }

        public int? CutListItems { get; set; }

        public int? DrawingSheets { get; set; }

        public int Gaps { get; set; }

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
                documents: Documents,
                features: Features,
                cutListItems: CutListItems,
                drawingSheets: DrawingSheets);
        }
    }
}
