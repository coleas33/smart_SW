using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T074: the four rows every pane host shares - `entity.show`, `report.open`, `folder.open`
/// and `log.open` - proven to behave identically in every host that serves them.
///
/// These rows already existed in <see cref="ReviewHost"/>. The Model check tab needs the same
/// four, and a second host that copied them would be the duplication this feature would be
/// judged on, so they are extracted into <see cref="PaneActions"/> and every host delegates.
/// Every test below therefore runs once per host (<see cref="Hosts"/>): the rows are proven
/// identical rather than assumed, which is the whole reason for the extraction
/// (`contracts/model-check.md` section 2, plan.md "Structure decision, extended for User
/// Story 6").
///
/// <b>The regression proof for the extraction is that `ReviewHostTests.cs` needs no edits.</b>
/// That file pins the same four rows against the Review host as they behaved before
/// <see cref="PaneActions"/> existed; it is not touched by the extraction, so a behaviour
/// change in any of them fails there rather than being absorbed into a rewritten expectation.
/// <see cref="TheHostsAnswerTheSharedRowsIdentically"/> closes the other half: it compares the
/// hosts' replies to each other, so a row that drifts in one host alone cannot pass.
///
/// Four rules are what these rows exist to enforce, and each has a test per host:
///
/// 1. <b>The page never supplies a path.</b> It names a run by id; the folder comes from the
///    host's own record. A crafted `path` in the payload is ignored.
/// 2. <b>Every resolved path is canonicalized and contained.</b> `..`, a foreign root, a UNC
///    path and a Win32 device path are refused before anything reaches the shell.
/// 3. <b>Messages are redacted.</b> A resolver failure or an opener failure can carry the
///    configured key; neither reaches the page unmasked (FR-015).
/// 4. <b>`entity.show` always answers `entity.shown`</b> carrying `{ok, state_code, message,
///    full_path}` - a reference that no longer resolves is an answer, not an error.
/// </summary>
public sealed class PaneActionsTests
{
    /// <summary>A stored key, so the redaction tests have something real to mask.</summary>
    private const string Secret = "sk-test-0123456789abcdef";

    /// <summary>Every host that serves the four shared rows.</summary>
    public static IEnumerable<object[]> Hosts =>
        PaneHostWorld.Kinds.Select(kind => new object[] { kind });

    // ---- entity.show --------------------------------------------------------------------

    [Theory]
    [MemberData(nameof(Hosts))]
    public void EntityShowHandsThePagesReferenceToTheResolverAndAnswersShown(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Resolver.Outcome = EntityShowOutcome.Shown("sub-2/bracket-3");
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

            // The page decides which instance to show and sends its component id with the
            // reference; the host accepts it and passes it through untouched (T079).
            Assert.Equal("cmp-4", asked.ComponentId);

            JsonElement shown = world.Reply("entity.shown", "e1");
            Assert.True(shown.GetProperty("ok").GetBoolean());
            Assert.Equal(0, shown.GetProperty("state_code").GetInt32());
            Assert.Equal("sub-2/bracket-3", shown.GetProperty("full_path").GetString());
            Assert.True(shown.TryGetProperty("message", out _));
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void AReferenceThatNoLongerResolvesReportsTheStateCodeAndTheComponentsFullPath(
        string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            // 4 is swPersistReferencedObject_Deleted: the entity is gone after a rebuild, so
            // the only thing left that helps is where the component sits in the tree.
            world.Resolver.Outcome = EntityShowOutcome.NotShown(
                4, "deleted: the entity no longer exists", "sub-2/bracket-3");
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "AQAAAA==" });

            JsonElement shown = world.Reply("entity.shown", "e1");
            Assert.False(shown.GetProperty("ok").GetBoolean());
            Assert.Equal(4, shown.GetProperty("state_code").GetInt32());
            Assert.Equal("sub-2/bracket-3", shown.GetProperty("full_path").GetString());
            Assert.Contains("deleted", shown.GetProperty("message").GetString()!);
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void EntityShowWithoutAReferenceIsRefusedWithoutTouchingSolidworks(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "  ", component_id = "cmp-4" });

            Assert.Equal(
                "InvalidRequest", world.Reply("error", "e1").GetProperty("error_class").GetString());
            Assert.Empty(world.Resolver.Requests);
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void EntityShowIsRefusedWhenTheAddInIsNotAttachedToSolidworks(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.UseResolver = false;
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "AQAAAA==" });

            JsonElement error = world.Reply("error", "e1");
            Assert.Equal("NotAttached", error.GetProperty("error_class").GetString());
            Assert.True(error.GetProperty("retryable").GetBoolean());
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void AResolverThatThrowsIsAnsweredAsANotShownReplyRatherThanAsACrash(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            // A modal dialog on the application thread, a closed document, a circuit-open
            // gate: the card has to be able to say so rather than the pane throwing.
            world.Resolver.Failure = new InvalidOperationException("SOLIDWORKS did not answer");
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "AQAAAA==" });

            JsonElement shown = world.Reply("entity.shown", "e1");
            Assert.False(shown.GetProperty("ok").GetBoolean());

            // -1 is not a swPersistReferencedObjectStates_e value: SOLIDWORKS never answered
            // at all, which is a different thing from a reference that resolved to nothing.
            Assert.Equal(-1, shown.GetProperty("state_code").GetInt32());
            Assert.Contains("SOLIDWORKS did not answer", shown.GetProperty("message").GetString()!);
            Assert.Equal(JsonValueKind.Null, shown.GetProperty("full_path").ValueKind);
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void AResolverMessageCarryingTheConfiguredKeyIsMaskedBeforeThePageSeesIt(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Settings.SetApiKey(Secret);
            world.Resolver.Outcome = EntityShowOutcome.NotShown(
                1, "the gate refused: OPENAI_API_KEY=" + Secret, null);
            world.Open();

            world.Receive("entity.show", "e1", new { persist_ref = "AQAAAA==" });

            string message = world.Reply("entity.shown", "e1").GetProperty("message").GetString()!;
            Assert.DoesNotContain(Secret, message);
            Assert.Contains(Redaction.Mask, message);
            world.AssertNothingPostedContains(Secret);
        }
    }

    // ---- report.open / folder.open ------------------------------------------------------

    [Theory]
    [MemberData(nameof(Hosts))]
    public void ReportOpenResolvesTheFileFromTheHostsOwnRecordAndIgnoresThePagesPath(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();
            string runDirectory = world.CreateRun("bracket");
            File.WriteAllText(Path.Combine(runDirectory, "report.md"), "# report");
            string runId = world.Track(runDirectory);

            world.Receive("report.open", "o1", world.Message(runId, new Dictionary<string, object?>
            {
                // A page that has been taken over would like these to be what opens.
                { "path", @"C:\Windows\System32\cmd.exe" },
                { "run_dir", @"C:\Windows" },
            }));

            world.Reply("ok", "o1");
            Assert.Equal(
                new[] { Path.Combine(runDirectory, "report.md") }, world.Opener.Opened.ToArray());
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void FolderOpenOpensTheRecordedRunFolder(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();
            string runDirectory = world.CreateRun("bracket");
            string runId = world.Track(runDirectory);

            world.Receive("folder.open", "o1", world.Message(runId));

            world.Reply("ok", "o1");
            Assert.Equal(new[] { runDirectory }, world.Opener.Opened.ToArray());
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void ReportOpenIsRefusedBeforeTheReportHasBeenWritten(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();
            string runId = world.Track(world.CreateRun("bracket"));

            world.Receive("report.open", "o1", world.Message(runId));

            JsonElement error = world.Reply("error", "o1");
            Assert.Equal("NotFound", error.GetProperty("error_class").GetString());
            Assert.Contains("report.md", error.GetProperty("message").GetString()!);
            Assert.Empty(world.Opener.Opened);
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void OpenIsRefusedWithoutAnIdAndTheShellIsNeverReached(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();

            world.Receive("folder.open", "o1", new Dictionary<string, object?>());
            world.Receive("report.open", "o2", world.Message("   "));

            Assert.Equal(
                "InvalidRequest", world.Reply("error", "o1").GetProperty("error_class").GetString());
            Assert.Equal(
                "InvalidRequest", world.Reply("error", "o2").GetProperty("error_class").GetString());
            Assert.Empty(world.Opener.Opened);
        }
    }

    [Theory]
    [MemberData(nameof(Hosts))]
    public void OpenIsRefusedForARunTheHostNeverRecorded(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();

            world.Receive("folder.open", "o1", world.Message("not-mine"));

            JsonElement error = world.Reply("error", "o1");
            Assert.Equal(world.UnknownErrorClass, error.GetProperty("error_class").GetString());
            Assert.False(error.GetProperty("retryable").GetBoolean());
            Assert.Empty(world.Opener.Opened);
        }
    }

    /// <summary>
    /// The containment rule, stated as the shapes it exists to refuse. A page that could name
    /// the path to open could open anything on the workstation with one crafted message, and
    /// a record built from a path that walks back out of the run root is the same hole with
    /// one more step in it.
    /// </summary>
    [Theory]
    [MemberData(nameof(ContainmentCases))]
    public void TheOpenerIsNeverReachedWithAPathOutsideTheRunRoot(string kind, string relative)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();
            string runDirectory = relative.StartsWith("|", StringComparison.Ordinal)
                ? relative.Substring(1)
                : Path.Combine(world.RunRoot, relative);
            string runId = world.Track(runDirectory);

            world.Receive("folder.open", "o1", world.Message(runId));
            world.Receive("report.open", "o2", world.Message(runId));

            Assert.Equal(
                "PathRefused", world.Reply("error", "o1").GetProperty("error_class").GetString());
            Assert.Equal(
                "PathRefused", world.Reply("error", "o2").GetProperty("error_class").GetString());
            Assert.Empty(world.Opener.Opened);
        }
    }

    /// <summary>A `|` prefix means the path is absolute and not relative to the run root.</summary>
    public static IEnumerable<object[]> ContainmentCases =>
        from kind in PaneHostWorld.Kinds
        from relative in new[]
        {
            Path.Combine("..", "..", "Windows"),
            Path.Combine("..", "elsewhere"),
            @"|\\server\share\runs",
            @"|\\.\PhysicalDrive0",
            @"|C:\Windows\System32",
        }
        select new object[] { kind, relative };

    // ---- log.open -----------------------------------------------------------------------

    [Theory]
    [MemberData(nameof(Hosts))]
    public void LogOpenOpensTheHostsLogFolderAndCreatesItIfItIsNotThereYet(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Open();

            world.Receive("log.open", "o1", new Dictionary<string, object?>());

            world.Reply("ok", "o1");
            Assert.Equal(new[] { world.LogFolder }, world.Opener.Opened.ToArray());
            Assert.True(Directory.Exists(world.LogFolder));
        }
    }

    // ---- the shell ----------------------------------------------------------------------

    [Theory]
    [MemberData(nameof(Hosts))]
    public void AnOpenerThatFailsIsReportedRedactedRatherThanThrownIntoWebView2(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Settings.SetApiKey(Secret);
            world.Opener.Failure = new System.ComponentModel.Win32Exception(
                "no application is associated with " + Secret);
            world.Open();
            string runId = world.Track(world.CreateRun("bracket"));

            world.Receive("folder.open", "o1", world.Message(runId));

            JsonElement error = world.Reply("error", "o1");
            Assert.Equal("OpenFailed", error.GetProperty("error_class").GetString());

            string message = error.GetProperty("message").GetString()!;
            Assert.Contains("no application is associated", message);
            Assert.DoesNotContain(Secret, message);
            world.AssertNothingPostedContains(Secret);
        }
    }

    // ---- the hosts are the same host on these four rows ---------------------------------

    /// <summary>
    /// The extraction's other half of the proof: every host's answer to the four shared rows
    /// is compared with every other host's, byte for byte apart from the id the page names a
    /// run by. `ReviewHostTests` pins the Review host's behaviour and needs no edits for this
    /// feature; this pins that the second host did not get its own dialect of it.
    /// </summary>
    [Fact]
    public void TheHostsAnswerTheSharedRowsIdentically()
    {
        string[] replies = PaneHostWorld.Kinds.Select(Transcript).ToArray();

        for (int index = 1; index < replies.Length; index++)
        {
            Assert.Equal(replies[0], replies[index]);
        }
    }

    /// <summary>One host's replies to the four shared rows, with the ids normalized away.</summary>
    private static string Transcript(string kind)
    {
        using (PaneHostWorld world = PaneHostWorld.For(kind))
        {
            world.Resolver.Outcome = EntityShowOutcome.NotShown(2, "suppressed", "sub-2/bracket-3");
            world.Open();
            string runId = world.Track(world.CreateRun("bracket"));

            world.Receive("entity.show", "m1", new { persist_ref = "AQAAAA==" });
            world.Receive("entity.show", "m2", new { persist_ref = string.Empty });
            world.Receive("folder.open", "m3", world.Message(runId));
            world.Receive("report.open", "m4", world.Message(runId));
            world.Receive("folder.open", "m5", world.Message("not-mine"));
            world.Receive("log.open", "m6", new Dictionary<string, object?>());

            // The run root, the log folder and the unknown-run sentence are the only things
            // that legitimately differ between two worlds: the first two are per-world
            // temporary folders and the third names the host's own kind of run.
            return string.Join("\n", world.Posted)
                .Replace(world.RunRoot, "<run-root>")
                .Replace(world.LogFolder, "<log-folder>")
                .Replace(world.UnknownErrorClass, "<unknown>")
                .Replace(Escaped(world.UnknownSentence("not-mine")), "<unknown-sentence>")
                .Replace("\"" + world.RunIdField + "\"", "\"<run-id-field>\"");
        }
    }

    /// <summary>A string as it appears inside the posted JSON, escaping and all.</summary>
    private static string Escaped(string text) => JsonSerializer.Serialize(text).Trim('"');

    // ---- the worlds ---------------------------------------------------------------------

    /// <summary>
    /// One pane host with every seam faked, a temporary run root and a temporary log folder.
    ///
    /// The subclasses differ only in which host they build and how a run is named on the
    /// wire; everything the tests assert is above that line, which is the point.
    /// </summary>
    private abstract class PaneHostWorld : IDisposable
    {
        /// <summary>Every host that delegates the four rows to <see cref="PaneActions"/>.</summary>
        public static readonly string[] Kinds = { "review", "model-check" };

        private readonly string _root;

        protected PaneHostWorld()
        {
            _root = Path.Combine(
                Path.GetTempPath(), "SwReview.PaneActions.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            SettingsPath = Path.Combine(_root, "settings.json");
            LogFolder = Path.Combine(_root, "logs");
            Settings = UserSettings.Defaults();
            Settings.RunRoot = Path.Combine(_root, "runs");
            Directory.CreateDirectory(Settings.RunRoot);
        }

        public static PaneHostWorld For(string kind)
        {
            switch (kind)
            {
                case "review":
                    return new ReviewWorld();

                case "model-check":
                    return new ModelCheckWorld();

                default:
                    throw new ArgumentOutOfRangeException(
                        nameof(kind), kind, "no pane host world is registered for that kind");
            }
        }

        public string SettingsPath { get; }

        public string LogFolder { get; }

        public UserSettings Settings { get; }

        public string RunRoot => Settings.RunRoot;

        public FakeResolver Resolver { get; } = new FakeResolver();

        public FakeOpener Opener { get; } = new FakeOpener();

        public List<string> Posted { get; } = new List<string>();

        public bool UseResolver { get; set; } = true;

        /// <summary>The payload field this host's page names a run by.</summary>
        public abstract string RunIdField { get; }

        /// <summary>The error class for an id this host never recorded.</summary>
        public abstract string UnknownErrorClass { get; }

        /// <summary>The sentence that goes with it.</summary>
        public abstract string UnknownSentence(string runId);

        /// <summary>Builds the host. Called after the test has set up the fakes.</summary>
        public abstract void Open();

        /// <summary>Records <paramref name="runDirectory"/> and returns the id to send.</summary>
        public abstract string Track(string runDirectory);

        protected abstract void Deliver(string json);

        /// <summary>A run folder inside the run root, as a real run would have left one.</summary>
        public string CreateRun(string name)
        {
            string directory = Path.Combine(RunRoot, "20260916-101532-" + name);
            Directory.CreateDirectory(directory);
            return directory;
        }

        /// <summary>A `report.open`/`folder.open` payload naming <paramref name="runId"/>.</summary>
        public Dictionary<string, object?> Message(
            string runId, Dictionary<string, object?>? extra = null)
        {
            var payload = new Dictionary<string, object?> { { RunIdField, runId } };
            if (extra != null)
            {
                foreach (KeyValuePair<string, object?> pair in extra)
                {
                    payload[pair.Key] = pair.Value;
                }
            }

            return payload;
        }

        public void Receive(string type, string id, object payload) =>
            Deliver(JsonSerializer.Serialize(new { type, id, payload }));

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
                + string.Join(" | ", Posted));
            return matches[0];
        }

        public void AssertNothingPostedContains(string secret)
        {
            foreach (string message in Posted)
            {
                Assert.DoesNotContain(secret, message);
            }
        }

        protected void SaveSettings()
        {
            if (!File.Exists(SettingsPath))
            {
                Settings.Save(SettingsPath);
            }
        }

        public virtual void Dispose()
        {
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

    private sealed class ReviewWorld : PaneHostWorld
    {
        private ReviewHost? _host;
        private int _chats;

        public override string RunIdField => "chat_id";

        public override string UnknownErrorClass => "UnknownChat";

        public override string UnknownSentence(string runId) =>
            $"this pane did not start a chat called '{runId}', so it does not know which "
            + "folder to open.";

        public override void Open()
        {
            SaveSettings();
            _host = new ReviewHost(new ReviewHostOptions(
                new FakeChannel(Posted), new SilentBackend(), SettingsPath)
            {
                BuildMode = BuildMode.Development,
                LogFolder = LogFolder,
                CurrentDocument = () => null,
                Environment = _ => null,
                EntityResolver = UseResolver ? Resolver : null,
                Opener = Opener,
            });
        }

        public override string Track(string runDirectory)
        {
            string chatId = "chat-" + (++_chats).ToString(System.Globalization.CultureInfo.InvariantCulture);
            Host.TrackSession(chatId, runDirectory);
            return chatId;
        }

        protected override void Deliver(string json) => Host.Receive(json);

        public override void Dispose()
        {
            _host?.Dispose();
            base.Dispose();
        }

        private ReviewHost Host =>
            _host ?? throw new InvalidOperationException("call Open() first");
    }

    private sealed class ModelCheckWorld : PaneHostWorld
    {
        private SwReview.AddIn.Model.ModelCheckHost? _host;

        public override string RunIdField => "run_id";

        public override string UnknownErrorClass => "UnknownCheck";

        public override string UnknownSentence(string runId) =>
            $"this pane did not run a check called '{runId}', so it does not know which "
            + "folder to open.";

        public override void Open()
        {
            SaveSettings();
            _host = new SwReview.AddIn.Model.ModelCheckHost(
                new SwReview.AddIn.Model.ModelCheckHostOptions(
                    new FakeChannel(Posted), () => RunRoot)
                {
                    LogFolder = () => LogFolder,
                    EntityResolver = () => UseResolver ? Resolver : null,
                    Opener = () => Opener,
                    Secrets = () => new[] { Settings.ResolveApiKey(_ => null).Key },
                });
        }

        public override string Track(string runDirectory)
        {
            return Host.TrackCheck(runDirectory).CheckId;
        }

        protected override void Deliver(string json) => Host.Receive(json);

        public override void Dispose()
        {
            _host?.Dispose();
            base.Dispose();
        }

        private SwReview.AddIn.Model.ModelCheckHost Host =>
            _host ?? throw new InvalidOperationException("call Open() first");
    }

    // ---- the fakes ----------------------------------------------------------------------

    private sealed class FakeChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public FakeChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json) => _posted.Add(json);
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
            if (Failure != null)
            {
                throw Failure;
            }

            Opened.Add(path);
        }
    }

    /// <summary>A backend that is never reached: none of the four shared rows touches one.</summary>
    private sealed class SilentBackend : IBackendClient
    {
        public BackendEndpoint? Endpoint => null;

        public IReadOnlyList<ModelChoice> ListModels(string provider) => new ModelChoice[0];

        public bool IsTurnRunning(string chatId) => false;

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
        }

        public ChatSessionHandle CreateSession(NewSessionRequest request) =>
            throw new InvalidOperationException("the shared rows never create a session");
    }
}
