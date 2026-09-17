using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using SwReview.AddIn.Model;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T027. <see cref="CheckPaneHost"/> is the page-channel plumbing both check tabs hold: the
/// envelope (<c>Receive</c> and its dispatch), <c>ready</c>/<c>SendInit</c>, the check records
/// (<c>TrackCheck</c>, <c>FindCheck</c>), the unsolicited messages (<c>Post</c>,
/// <c>PostStatus</c>, <c>DocumentChanged</c>), the one document payload shape, and
/// <c>Dispose</c>. It takes its one start step from its owner and does nothing else that is
/// specific to a family.
///
/// <b>A collaborator, not a base class</b> (plan.md Structure Decision 3). A shared abstract
/// <c>PaneHost</c> over all four hosts stays rejected for feature 003's reason - it would drag
/// backend chat state into a host that has none, and a seat and a pipeline into two that have
/// neither - but that argument is about the hosts that are not in question. The two check hosts
/// need the same 250 lines, so they hold one copy of them rather than inherit one.
///
/// <b>The regression proof is that nothing downstream moved.</b> The four shared rows are still
/// <see cref="PaneActions"/>'s, which this feature does not edit, and
/// <see cref="ModelCheckHostTests"/> and <see cref="PaneActionsTests"/> pass <b>unedited</b>
/// after <see cref="ModelCheckHost"/> is rebuilt on this collaborator (quickstart gate 7b). The
/// last two tests here assert the machine-checkable half of that: the surface those tests bind
/// to still exists with the same shapes, and it is reached by composition rather than by
/// inheritance.
/// </summary>
public sealed class CheckPaneHostTests
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 16, 10, 15, 32);

    // ---- ready / init -------------------------------------------------------------------

    [Fact]
    public void ReadyAnswersInitWithTheBackendTheTokenTheRunRootAndTheDocument()
    {
        using (var world = new PaneWorld())
        {
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Machined");
            world.Open();

            world.Receive("ready", "r1", new { });

            JsonElement init = world.Reply("init", "r1");
            Assert.Equal(51234, init.GetProperty("backend").GetProperty("port").GetInt32());

            // The page's OWN origin under `/__backend`, never the backend's loopback one: both
            // check pages fetch their own origin and the host serves that prefix from C#.
            Assert.Equal(
                "https://swreview.invalid/__backend",
                init.GetProperty("backend").GetProperty("origin").GetString());
            Assert.Equal("0FAKEtoken", init.GetProperty("token").GetString());
            Assert.Equal(world.RunRoot, init.GetProperty("run_root").GetString());

            JsonElement document = init.GetProperty("document");
            Assert.Equal(@"C:\parts\bracket.SLDPRT", document.GetProperty("path").GetString());
            Assert.Equal("Machined", document.GetProperty("configuration").GetString());
            Assert.Equal("part", document.GetProperty("kind").GetString());

            Assert.Equal(JsonValueKind.Null, init.GetProperty("latest_check").ValueKind);
        }
    }

    [Fact]
    public void InitCarriesNoDocumentAndNoBackendWhenThereIsNeither()
    {
        using (var world = new PaneWorld())
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
    /// The endpoint and the document are read fresh on every `ready`, not cached at
    /// construction: the tab is opened before the backend is listening, the page re-asks when
    /// the host says it is up, and the second answer has to carry what the first could not.
    /// </summary>
    [Fact]
    public void ASecondReadyCarriesTheBackendAndTheDocumentThatArrivedAfterTheFirstOne()
    {
        using (var world = new PaneWorld())
        {
            world.Endpoint = null;
            world.Document = null;
            world.Open();

            world.Receive("ready", "r1", new { });
            Assert.Equal(JsonValueKind.Null, world.Reply("init", "r1").GetProperty("backend").ValueKind);

            world.Endpoint = new BackendEndpoint(51234, "0FAKEtoken");
            world.Document = new PageDocument(@"C:\parts\bracket.SLDPRT", "Default");
            world.Receive("ready", "r2", new { });

            JsonElement second = world.Reply("init", "r2");
            Assert.Equal(51234, second.GetProperty("backend").GetProperty("port").GetInt32());
            Assert.Equal(
                @"C:\parts\bracket.SLDPRT",
                second.GetProperty("document").GetProperty("path").GetString());
        }
    }

    [Fact]
    public void InitCarriesTheLatestCheckOnceOneIsTracked()
    {
        using (var world = new PaneWorld())
        {
            world.Open();
            world.Host.TrackCheck(Path.Combine(world.RunRoot, "20260916-101532-bracket-check"));

            world.Receive("ready", "r1", new { });

            JsonElement latest = world.Reply("init", "r1").GetProperty("latest_check");
            Assert.Equal(
                Path.Combine(world.RunRoot, "20260916-101532-bracket-check"),
                latest.GetProperty("run_dir").GetString());
            Assert.Equal("2026-09-16T10:15:32.0000000", latest.GetProperty("at").GetString());
        }
    }

    // ---- the owner's one start step -------------------------------------------------------

    /// <summary>
    /// The collaborator knows the owner's start type and nothing about what it does: the id is
    /// handed over so the owner's reply and its refusals echo the page's message.
    /// </summary>
    [Fact]
    public void TheOwnersStartTypeIsHandedToTheOwnersStartStepWithTheMessageId()
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            world.Receive("check.start", "c1", new { scope = "part" });

            Assert.Equal(new[] { "c1" }, world.Started.ToArray());
            Assert.Empty(world.AllPosted("error"));
        }
    }

    [Fact]
    public void AStartWithNoIdIsStillHandedOver()
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            world.Host.Receive(JsonSerializer.Serialize(new { type = "check.start" }));

            Assert.Equal(new string?[] { null }, world.Started.ToArray());
        }
    }

    [Fact]
    public void AMessageTypeNeitherTheCollaboratorNorItsOwnerHandlesIsAnsweredWithAnError()
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            world.Receive("check.explode", "x1", new { });

            JsonElement error = world.Reply("error", "x1");
            Assert.Equal("UnknownMessage", error.GetProperty("error_class").GetString());
            Assert.Contains("check.explode", error.GetProperty("message").GetString()!);
            Assert.False(error.GetProperty("retryable").GetBoolean());
            Assert.Empty(world.Started);
        }
    }

    /// <summary>
    /// An exception escaping into the `WebMessageReceived` handler surfaces inside SOLIDWORKS.
    /// Nothing the page can send may do that, including a start step that throws.
    /// </summary>
    [Theory]
    [InlineData("not json at all")]
    [InlineData("[]")]
    [InlineData("7")]
    [InlineData("{\"id\": \"x\"}")]
    [InlineData("{\"type\": 7}")]
    [InlineData("{\"type\": \"\"}")]
    public void AMalformedPageMessageIsAnsweredRatherThanThrown(string json)
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            world.Host.Receive(json);

            Assert.NotEmpty(world.AllPosted("error"));
        }
    }

    [Fact]
    public void AStartStepThatThrowsIsAnsweredRatherThanThrown()
    {
        using (var world = new PaneWorld())
        {
            world.StartFailure = new InvalidOperationException("the feature tree could not be read");
            world.Open();

            world.Receive("check.start", "c1", new { });

            JsonElement error = world.Reply("error", "c1");
            Assert.Equal("HostError", error.GetProperty("error_class").GetString());
            Assert.Contains("the feature tree could not be read", error.GetProperty("message").GetString()!);
        }
    }

    // ---- the four shared rows stay PaneActions' ------------------------------------------

    /// <summary>
    /// The rows are not re-implemented here: the collaborator asks <see cref="PaneActions"/>
    /// first and falls through to `ready` and the owner's start type. `PaneActionsTests` is
    /// parameterized over the hosts and proves the rows themselves; what matters here is that
    /// they are reached at all, and that a check the pane never ran is refused by name.
    /// </summary>
    [Fact]
    public void TheFourSharedRowsAreAnsweredByPaneActions()
    {
        using (var world = new PaneWorld())
        {
            world.Open();
            string runDirectory = Path.Combine(world.RunRoot, "20260916-101532-bracket-check");
            Directory.CreateDirectory(runDirectory);
            world.Host.TrackCheck(runDirectory);

            world.Receive("folder.open", "f1", new { run_id = "20260916-101532-bracket-check" });
            world.Receive("log.open", "l1", new { });
            world.Receive("entity.show", "e1", new { persist_ref = "AAAA" });

            Assert.Equal(new[] { runDirectory, world.LogFolder }, world.Opener.Opened.ToArray());

            // No resolver: the pane is not attached to a session, which is a state it has.
            Assert.Equal("NotAttached", world.Reply("error", "e1").GetProperty("error_class").GetString());
        }
    }

    [Fact]
    public void AFolderOpenForACheckThisPaneNeverRanIsRefusedByName()
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            world.Receive("folder.open", "f1", new { run_id = "20260101-000000-other-check" });

            JsonElement error = world.Reply("error", "f1");
            Assert.Equal("UnknownCheck", error.GetProperty("error_class").GetString());
            Assert.Contains("20260101-000000-other-check", error.GetProperty("message").GetString()!);
            Assert.Empty(world.Opener.Opened);
        }
    }

    // ---- the check records ----------------------------------------------------------------

    [Fact]
    public void TrackCheckNamesTheRecordAfterTheFolderAndRegistersItAsThePanesLatestRun()
    {
        using (var world = new PaneWorld())
        {
            world.Open();
            string runDirectory = Path.Combine(world.RunRoot, "20260916-101532-bracket-check");

            CheckRecord record = world.Host.TrackCheck(runDirectory);

            Assert.Equal("20260916-101532-bracket-check", record.CheckId);
            Assert.Equal(runDirectory, record.RunDirectory);
            Assert.Equal(Stamp, record.At);
            Assert.Same(record, world.Host.LatestCheck);
            Assert.Equal(new[] { runDirectory }, world.Registered.ToArray());
        }
    }

    /// <summary>A trailing separator is not a second check: the id is the folder's own name.</summary>
    [Fact]
    public void ATrailingSeparatorDoesNotChangeTheCheckId()
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            CheckRecord record = world.Host.TrackCheck(
                Path.Combine(world.RunRoot, "20260916-101532-bracket-check")
                + Path.DirectorySeparatorChar);

            Assert.Equal("20260916-101532-bracket-check", record.CheckId);
        }
    }

    [Fact]
    public void TrackingTheSameFolderTwiceKeepsOneRecordAndTheNewerTime()
    {
        using (var world = new PaneWorld())
        {
            world.Open();
            string runDirectory = Path.Combine(world.RunRoot, "20260916-101532-bracket-check");

            world.Host.TrackCheck(runDirectory);
            world.Now = Stamp.AddMinutes(5);
            CheckRecord second = world.Host.TrackCheck(runDirectory);

            Assert.Single(world.Host.Checks);
            Assert.Equal(Stamp.AddMinutes(5), world.Host.Checks[0].At);
            Assert.Same(second, world.Host.Checks[0]);
        }
    }

    [Fact]
    public void ChecksAreKeptOldestFirstAndFindCheckFindsOnlyWhatWasTracked()
    {
        using (var world = new PaneWorld())
        {
            world.Open();
            world.Host.TrackCheck(Path.Combine(world.RunRoot, "first-check"));
            world.Host.TrackCheck(Path.Combine(world.RunRoot, "second-check"));

            Assert.Equal(
                new[] { "first-check", "second-check" },
                world.Host.Checks.Select(check => check.CheckId).ToArray());
            Assert.Equal("second-check", world.Host.LatestCheck!.CheckId);
            Assert.Equal("first-check", world.Host.FindCheck("first-check")!.CheckId);
            Assert.Null(world.Host.FindCheck("third-check"));
        }
    }

    [Fact]
    public void TrackCheckRefusesANullFolder()
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            Assert.Throws<ArgumentNullException>(() => world.Host.TrackCheck(null!));
        }
    }

    // ---- the unsolicited messages ----------------------------------------------------------

    [Fact]
    public void PostSendsAnUnsolicitedMessageWithNoId()
    {
        using (var world = new PaneWorld())
        {
            world.Open();

            world.Host.Post("backend.stopped", new Dictionary<string, object?> { { "exit_code", 3 } });

            JsonElement root = JsonDocument.Parse(world.Posted.Last()).RootElement;
            Assert.Equal("backend.stopped", root.GetProperty("type").GetString());
            Assert.Equal(JsonValueKind.Null, root.GetProperty("id").ValueKind);
            Assert.Equal(3, root.GetProperty("payload").GetProperty("exit_code").GetInt32());
        }
    }

    /// <summary>
    /// Every status goes through <see cref="PaneActions.PostStatus"/>, which is the one place
    /// a configured secret is masked out of anything headed for the page (FR-015).
    /// </summary>
    [Fact]
    public void PostStatusMasksEverySecretOutOfTheMessage()
    {
        using (var world = new PaneWorld())
        {
            world.Secret = "sk-0FAKEsecret";
            world.Open();

            world.Host.PostStatus("error", "the dump failed with key sk-0FAKEsecret in the command");

            string message = world.LastPosted("status").GetProperty("message").GetString()!;
            Assert.DoesNotContain("sk-0FAKEsecret", message);
            Assert.Equal("error", world.LastPosted("status").GetProperty("stage").GetString());
        }
    }

    [Fact]
    public void DocumentChangedPostsThePathTheConfigurationAndTheKindTheHostSees()
    {
        using (var world = new PaneWorld())
        {
            world.Open();
            world.Document = new PageDocument(@"C:\parts\other.SLDASM", "Machined");

            world.Host.DocumentChanged();

            JsonElement changed = world.LastPosted("document.changed");
            Assert.Equal(@"C:\parts\other.SLDASM", changed.GetProperty("path").GetString());
            Assert.Equal("Machined", changed.GetProperty("configuration").GetString());
            Assert.Equal("assembly", changed.GetProperty("kind").GetString());
        }
    }

    [Fact]
    public void ClosingTheLastDocumentPostsANullDocumentChanged()
    {
        using (var world = new PaneWorld())
        {
            world.Document = new PageDocument(@"C:\parts\other.SLDPRT", null);
            world.Open();
            world.Document = null;

            world.Host.DocumentChanged();

            Assert.Equal(JsonValueKind.Null, world.LastPosted("document.changed").ValueKind);
        }
    }

    /// <summary>
    /// One document payload, sent by `init` and by `document.changed` alike, so a page never
    /// has two shapes to read. A kind the extension does not name stays null rather than
    /// becoming "part": unknown stays unknown.
    /// </summary>
    [Theory]
    [InlineData(@"C:\parts\bracket.SLDPRT", "part")]
    [InlineData(@"C:\parts\bracket assy.sldasm", "assembly")]
    [InlineData(@"C:\parts\sheet.SLDDRW", "drawing")]
    [InlineData(@"C:\parts\bracket.step", null)]
    public void DocumentPayloadCarriesThePathTheConfigurationAndTheKindAndNothingElse(
        string path, string? kind)
    {
        Dictionary<string, object?>? payload =
            CheckPaneHost.DocumentPayload(new PageDocument(path, "Default"));

        Assert.NotNull(payload);
        Assert.Equal(
            new[] { "path", "configuration", "kind" },
            payload!.Keys.ToArray());
        Assert.Equal(path, payload["path"]);
        Assert.Equal("Default", payload["configuration"]);
        Assert.Equal(kind, payload["kind"]);
    }

    [Fact]
    public void DocumentPayloadForNoDocumentIsNullRatherThanAnEmptyObject()
    {
        Assert.Null(CheckPaneHost.DocumentPayload(null));
    }

    [Fact]
    public void DisposeForgetsTheChecks()
    {
        using (var world = new PaneWorld())
        {
            world.Open();
            world.Host.TrackCheck(Path.Combine(world.RunRoot, "20260916-101532-bracket-check"));

            world.Host.Dispose();

            Assert.Empty(world.Host.Checks);
            Assert.Null(world.Host.LatestCheck);
        }
    }

    [Fact]
    public void TheOptionsRefuseTheThingsTheHostCannotRunWithout()
    {
        var channel = new CollectingChannel(new List<string>());

        Assert.Throws<ArgumentNullException>(
            () => new CheckPaneHostOptions(null!, () => "runs", "check.start", _ => { }));
        Assert.Throws<ArgumentNullException>(
            () => new CheckPaneHostOptions(channel, null!, "check.start", _ => { }));
        Assert.Throws<ArgumentNullException>(
            () => new CheckPaneHostOptions(channel, () => "runs", null!, _ => { }));
        Assert.Throws<ArgumentNullException>(
            () => new CheckPaneHostOptions(channel, () => "runs", "check.start", null!));
        Assert.Throws<ArgumentNullException>(() => new CheckPaneHost(null!));
    }

    // ---- the regression proof --------------------------------------------------------------

    /// <summary>
    /// Composition, not inheritance: <see cref="ModelCheckHost"/> derives from nothing and
    /// holds a <see cref="CheckPaneHost"/>. Feature 003's rejection of a shared base class over
    /// the pane hosts stands, and each host's own dependencies stay explicit (plan.md Structure
    /// Decision 3).
    /// </summary>
    [Fact]
    public void TheModelCheckHostHoldsTheCollaboratorRatherThanInheritingIt()
    {
        Assert.Equal(typeof(object), typeof(ModelCheckHost).BaseType);
        Assert.Equal(typeof(object), typeof(CheckPaneHost).BaseType);

        Assert.Contains(
            typeof(ModelCheckHost).GetFields(BindingFlags.Instance | BindingFlags.NonPublic),
            field => field.FieldType == typeof(CheckPaneHost));
    }

    /// <summary>
    /// The surface <see cref="ModelCheckHostTests"/> and <see cref="PaneActionsTests"/> bind
    /// to, asserted as a table so the extraction is proved to be an extraction rather than
    /// merely believed to be one. Those two files are not edited by this feature; if a member
    /// below moved or changed shape they would not compile, and this test says which one.
    /// </summary>
    [Theory]
    [InlineData("Receive", typeof(void), typeof(string))]
    [InlineData("Post", typeof(void), typeof(string), typeof(object))]
    [InlineData("PostStatus", typeof(void), typeof(string), typeof(string))]
    [InlineData("DocumentChanged", typeof(void))]
    [InlineData("TrackCheck", typeof(CheckRecord), typeof(string))]
    [InlineData("FindCheck", typeof(CheckRecord), typeof(string))]
    [InlineData("Dispose", typeof(void))]
    public void TheModelCheckHostStillCarriesTheMethodsItsOwnTestsCall(
        string name, Type returns, params Type[] parameters)
    {
        MethodInfo? method = typeof(ModelCheckHost).GetMethod(
            name, BindingFlags.Instance | BindingFlags.Public, null, parameters, null);

        Assert.True(method != null, "ModelCheckHost no longer has a public " + name + ".");
        Assert.Equal(returns, method!.ReturnType);
    }

    [Theory]
    [InlineData("Backend")]
    [InlineData("CurrentDocument")]
    [InlineData("Dump")]
    [InlineData("RegisterLatestRun")]
    [InlineData("EntityResolver")]
    [InlineData("Opener")]
    [InlineData("LogFolder")]
    [InlineData("Now")]
    [InlineData("Secrets")]
    public void TheModelCheckHostOptionsStillCarryTheSettersItsOwnTestsSet(string name)
    {
        PropertyInfo? property = typeof(ModelCheckHostOptions).GetProperty(name);

        Assert.True(property != null, "ModelCheckHostOptions no longer has a " + name + ".");
        Assert.True(property!.CanWrite, name + " is no longer settable.");
    }

    // ---- the world ----------------------------------------------------------------------

    private sealed class PaneWorld : IDisposable
    {
        private readonly string _root;
        private CheckPaneHost? _host;

        public PaneWorld()
        {
            _root = Path.Combine(
                Path.GetTempPath(), "SwReview.CheckPaneHost.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            RunRoot = Path.Combine(_root, "runs");
            Directory.CreateDirectory(RunRoot);
            LogFolder = Path.Combine(_root, "logs");
            Directory.CreateDirectory(LogFolder);
        }

        public string RunRoot { get; }

        public string LogFolder { get; }

        public PageDocument? Document { get; set; }

        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(51234, "0FAKEtoken");

        public DateTime Now { get; set; } = Stamp;

        public string? Secret { get; set; }

        public Exception? StartFailure { get; set; }

        public List<string?> Started { get; } = new List<string?>();

        public List<string> Registered { get; } = new List<string>();

        public List<string> Posted { get; } = new List<string>();

        public FakeOpener Opener { get; } = new FakeOpener();

        public CheckPaneHost Host =>
            _host ?? throw new InvalidOperationException("call Open() first");

        public void Open()
        {
            _host = new CheckPaneHost(new CheckPaneHostOptions(
                new CollectingChannel(Posted), () => RunRoot, "check.start", Start)
            {
                Backend = () => Endpoint,
                CurrentDocument = () => Document,
                RegisterLatestRun = directory => Registered.Add(directory),
                Opener = () => Opener,
                LogFolder = () => LogFolder,
                Now = () => Now,
                Secrets = () => new[] { Secret },
            });
        }

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

        private void Start(string? id)
        {
            Started.Add(id);
            if (StartFailure != null)
            {
                throw StartFailure;
            }
        }
    }

    private sealed class CollectingChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public CollectingChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json) => _posted.Add(json);
    }

    private sealed class FakeOpener : IPathOpener
    {
        public List<string> Opened { get; } = new List<string>();

        public void Open(string path) => Opened.Add(path);
    }
}
