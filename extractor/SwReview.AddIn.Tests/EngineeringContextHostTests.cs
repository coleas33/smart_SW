using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using SwReview.AddIn.Review;
using SwReview.AddIn.EngineeringContext;
using SwReview.AddIn.Settings;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

public sealed class EngineeringContextHostTests
{
    [Fact]
    public void PreparingSavedEvidenceDoesNotStartAProvider()
    {
        using var world = new World();
        world.Host.Receive(Message("context.prepare", new { }));
        Assert.Equal(1, world.Dump.Runs);
        Assert.Empty(world.Backend.Created);
        JsonElement reply = world.Reply("context.prepared");
        Assert.Equal(Path.GetFileName(world.Dump.Directory), reply.GetProperty("run_id").GetString());
        Assert.Equal(64, reply.GetProperty("package_sha256").GetString()!.Length);
        Assert.False(reply.TryGetProperty("run_dir", out _));
    }

    [Fact]
    public void ContextReviewUsesThePreparedPackageWithoutAnotherExtraction()
    {
        using var world = new World();
        world.Host.Receive(Message("context.prepare", new { }));
        JsonElement prepared = world.Reply("context.prepared");
        string contextId = Guid.NewGuid().ToString();
        string head = new string('a', 64);
        world.Host.Receive(Message("context.review", new
        {
            run_id = prepared.GetProperty("run_id").GetString(), context_id = contextId,
            head_digest = head, package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        }));
        Assert.Equal(1, world.Dump.Runs);
        NewSessionRequest request = Assert.Single(world.Backend.Created);
        Assert.Equal(world.Dump.Directory, request.RunDirectory);
        Assert.Equal(contextId, request.EngineeringContext!.ContextId);
        Assert.Equal(head, request.EngineeringContext.HeadDigest);
        Assert.Equal(world.Dump.Directory, world.Reply("review.started").GetProperty("run_dir").GetString());
        world.Host.Receive(Message("context.review", new
        {
            run_id = prepared.GetProperty("run_id").GetString(), context_id = contextId,
            head_digest = head, package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        }));
        Assert.Single(world.Backend.Created);
        Assert.Equal("ContextExpired", world.Reply("error").GetProperty("error_class").GetString());
    }

    /// <summary>
    /// Owner decision 99A (the T116 integration review's first blocker): a context review starts
    /// through the one session path ordinary Review uses, so an unticked box makes it wait with
    /// nothing sent, and its reply and chip say so.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ContextReviewFollowsTheSendWhenCheckedBox(bool sendWhenChecked)
    {
        using var world = new World(sendWhenChecked);
        world.Host.Receive(Message("context.prepare", new { }));
        JsonElement prepared = world.Reply("context.prepared");
        string contextId = Guid.NewGuid().ToString();
        world.Host.Receive(Message("context.review", new
        {
            run_id = prepared.GetProperty("run_id").GetString(), context_id = contextId,
            head_digest = new string('a', 64), package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        }));
        NewSessionRequest request = Assert.Single(world.Backend.Created);
        Assert.Equal(sendWhenChecked ? ReviewMode.Send : ReviewMode.Wait, request.Mode);
        Assert.Null(request.RetryOf);
        Assert.Equal(contextId, request.EngineeringContext!.ContextId);
        JsonElement started = world.Reply("review.started");
        Assert.Equal(sendWhenChecked, started.GetProperty("send_when_checked").GetBoolean());
        Assert.Equal("chat-context", started.GetProperty("chat_id").GetString());
        Assert.Equal(world.Dump.Directory, started.GetProperty("run_dir").GetString());
        string ready = world.Status("ready");
        if (sendWhenChecked) Assert.DoesNotContain("nothing was sent", ready);
        else Assert.Equal("Checked 1 components by code; nothing was sent to the model.", ready);
        Assert.Equal(1, world.Dump.Runs);
    }

    /// <summary>
    /// Owner decision 108A: Retry on a failed context review re-attaches the same saved context
    /// in the same run folder, with no new extraction, through the one gated session path.
    /// </summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void RetryOfAContextReviewReattachesItsSavedContextInItsFolder(bool sendWhenChecked)
    {
        using var world = new World(sendWhenChecked);
        (string contextId, string head, string sha) = world.StartContextReview();

        world.Host.Receive(Message("review.start", new { retry_of = "chat-context" }));

        Assert.Equal(1, world.Dump.Runs);
        Assert.Equal(2, world.Backend.Created.Count);
        NewSessionRequest retry = world.Backend.Created[1];
        Assert.Equal(world.Dump.Directory, retry.RunDirectory);
        Assert.Equal("chat-context", retry.RetryOf);
        Assert.Equal(sendWhenChecked ? ReviewMode.Send : ReviewMode.Wait, retry.Mode);
        Assert.Equal(contextId, retry.EngineeringContext!.ContextId);
        Assert.Equal(head, retry.EngineeringContext.HeadDigest);
        Assert.Equal(sha, retry.EngineeringContext.PackageSha256);
        Assert.Equal(sendWhenChecked, world.Reply("review.started").GetProperty("send_when_checked").GetBoolean());
    }

    /// <summary>
    /// Feature 011, decision 141A (2026-10-19): the Retry is a new review session in the same run
    /// folder, so a <c>drawing.read</c> naming that folder belongs to the Retry's session, which
    /// starts its own count of failed opens; the failed review's count is not carried over.
    /// </summary>
    [Fact]
    public void RetryOfAContextReviewIsANewDrawingReadSessionInTheSameFolder()
    {
        using var world = new World();
        world.StartContextReview();
        string runId = Path.GetFileName(world.Dump.Directory!);
        ConfirmedDrawingSession failed = world.Host.DrawingReadSession(runId)!;

        world.Host.Receive(Message("review.start", new { retry_of = "chat-context" }));

        ConfirmedDrawingSession retried = world.Host.DrawingReadSession(runId)!;
        Assert.NotSame(failed, retried);
        Assert.Equal(world.Dump.Directory, retried.RunFolder);
        Assert.Equal(0, retried.UnrecordedOpens);
    }

    [Fact]
    public void ARetryOfAContextReviewWhoseContextChangedIsRefusedWithTheBackendsConflict()
    {
        using var world = new World(sendWhenChecked: false);
        world.StartContextReview();
        world.Backend.NextError = new BackendRequestException(
            "EngineeringContextConflict", "FICT the saved context changed; use the Engineering context panel.", false);

        world.Host.Receive(Message("review.start", new { retry_of = "chat-context" }));

        Assert.Equal(1, world.Dump.Runs);
        JsonElement error = world.Reply("error");
        Assert.Equal("EngineeringContextConflict", error.GetProperty("error_class").GetString());
        Assert.Contains("Engineering context panel", error.GetProperty("message").GetString());
    }

    [Fact]
    public void ARetryOfAContextReviewOfAnotherDocumentIsRefusedAndNothingStarts()
    {
        using var world = new World();
        world.StartContextReview();
        world.Document = new PageDocument(@"C:\Fictional\other.SLDASM", "Default");

        world.Host.Receive(Message("review.start", new { retry_of = "chat-context" }));

        Assert.Single(world.Backend.Created);
        Assert.Equal(1, world.Dump.Runs);
        Assert.Equal("ReviewNotActive", world.Reply("error").GetProperty("error_class").GetString());
    }

    [Fact]
    public void AnOrdinaryRetryStillExtractsAgainWithNoContext()
    {
        using var world = new World();
        world.Host.Receive(Message("review.start", new { }));
        world.Host.Receive(Message("review.start", new { retry_of = "chat-context" }));

        Assert.Equal(2, world.Dump.Runs);
        Assert.Null(world.Backend.Created[1].EngineeringContext);
        Assert.Equal("chat-context", world.Backend.Created[1].RetryOf);
    }

    [Theory]
    [InlineData("document")]
    [InlineData("configuration")]
    [InlineData("package")]
    [InlineData("new preparation")]
    [InlineData("ordinary review")]
    [InlineData("review preparation")]
    public void PreparedContextExpiresWhenItsScopeChanges(string change)
    {
        using var world = new World();
        world.Host.Receive(Message("context.prepare", new { }));
        JsonElement prepared = world.Reply("context.prepared");
        if (change == "document") { world.Document = new PageDocument(@"C:\Fictional\other.SLDASM", "Default"); world.Host.DocumentChanged(); }
        if (change == "configuration") world.Document = new PageDocument(world.Document!.Path, "Other");
        if (change == "package") File.AppendAllText(Path.Combine(world.Dump.Directory!, "package.json"), " ");
        if (change == "new preparation") world.Host.Receive(Message("context.prepare", new { }));
        if (change == "ordinary review") world.Host.Receive(Message("review.start", new { }));
        if (change == "review preparation") world.Host.Receive(Message("review.prepare", new { }));
        if (change == "ordinary review") Assert.Null(Assert.Single(world.Backend.Created).EngineeringContext);
        int before = world.Backend.Created.Count;
        world.Host.Receive(Message("context.review", new
        {
            run_id = prepared.GetProperty("run_id").GetString(), context_id = Guid.NewGuid().ToString(),
            head_digest = new string('b', 64), package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        }));
        Assert.Equal(before, world.Backend.Created.Count);
        Assert.Equal("ContextExpired", world.Reply("error").GetProperty("error_class").GetString());
    }

    [Theory]
    [InlineData("../private")]
    [InlineData(@"C:\private\run")]
    [InlineData("unknown-run")]
    public void ContextSelectionCannotChooseAPathOrUnknownRun(string runId)
    {
        using var world = new World();
        world.Host.Receive(Message("context.prepare", new { }));
        JsonElement prepared = world.Reply("context.prepared");
        world.Host.Receive(Message("context.selection", new
        {
            run_id = runId, package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        }));
        Assert.Empty(world.Selection.Requests);
        Assert.Equal("ContextExpired", world.Reply("error").GetProperty("error_class").GetString());
    }

    [Fact]
    public void ContextSelectionUsesOnlyTheHostOwnedPackageAndPinnedDigest()
    {
        using var world = new World();
        world.Host.Receive(Message("context.prepare", new { }));
        JsonElement prepared = world.Reply("context.prepared");
        string sha = prepared.GetProperty("package_sha256").GetString()!;
        world.Host.Receive(Message("context.selection", new
        {
            run_id = prepared.GetProperty("run_id").GetString(), package_sha256 = sha,
        }));
        Assert.Equal((world.Dump.Directory, sha), Assert.Single(world.Selection.Requests));
        Assert.Empty(world.Backend.Created);
        JsonElement result = world.Reply("context.selected");
        Assert.Equal("matched_saved_target", result.GetProperty("status").GetString());
        Assert.False(result.GetProperty("native_calibrated").GetBoolean());
    }

    [Fact]
    public void ScopeChangeDuringExtractionDoesNotPublishAPreparedRun()
    {
        using var world = new World();
        world.Dump.OnRun = () => world.Document = new PageDocument(world.Document!.Path, "Other");
        world.Host.Receive(Message("context.prepare", new { }));
        Assert.Empty(world.Backend.Created);
        Assert.Equal("ContextExpired", world.Reply("error").GetProperty("error_class").GetString());
        Assert.DoesNotContain(world.Messages, message => JsonDocument.Parse(message).RootElement.GetProperty("type").GetString() == "context.prepared");
    }

    [Fact]
    public void BusyReviewRefusesContextPreparationBeforeExtraction()
    {
        using var world = new World();
        world.Host.TrackSession("busy-chat", "fictional-run");
        world.Backend.Running = true;
        world.Host.Receive(Message("context.prepare", new { }));
        Assert.Equal(0, world.Dump.Runs);
        Assert.Equal("TurnRunning", world.Reply("error").GetProperty("error_class").GetString());
    }

    [Fact]
    public void DocumentNotificationDuringExtractionExpiresEvenWhenTheSameDocumentReturns()
    {
        using var world = new World();
        world.Dump.OnRun = () => world.Host.DocumentChanged();
        world.Host.Receive(Message("context.prepare", new { }));
        Assert.Empty(world.Backend.Created);
        Assert.Equal("ContextExpired", world.Reply("error").GetProperty("error_class").GetString());
        Assert.DoesNotContain(world.Messages, message => JsonDocument.Parse(message).RootElement.GetProperty("type").GetString() == "context.prepared");
    }

    [Theory]
    [InlineData("context.selection")]
    [InlineData("context.review")]
    public void DocumentNotificationDuringScopeCheckPreventsSelectionAndProviderCalls(string message)
    {
        using var world = new World();
        world.Host.Receive(Message("context.prepare", new { }));
        JsonElement prepared = world.Reply("context.prepared");
        world.ReadDocumentCallback = () => world.Host.DocumentChanged();
        world.Host.Receive(Message(message, new
        {
            run_id = prepared.GetProperty("run_id").GetString(), context_id = Guid.NewGuid().ToString(),
            head_digest = new string('b', 64), package_sha256 = prepared.GetProperty("package_sha256").GetString(),
        }));
        Assert.Empty(world.Selection.Requests);
        Assert.Empty(world.Backend.Created);
        Assert.Equal("ContextExpired", world.Reply("error").GetProperty("error_class").GetString());
    }

    private static string Message(string type, object payload) =>
        JsonSerializer.Serialize(new { type, id = "request", payload });

    private sealed class World : IDisposable
    {
        private readonly string _root = Path.Combine(Path.GetTempPath(), "SwReview.ContextHost", Guid.NewGuid().ToString("N"));
        public readonly List<string> Messages = new List<string>();
        public readonly Backend Backend = new Backend();
        public readonly Dump Dump = new Dump();
        public readonly Selection Selection = new Selection();
        public readonly ReviewHost Host;
        public Action? ReadDocumentCallback;
        public PageDocument? Document = new PageDocument(@"C:\Fictional\bracket.SLDASM", "Default");

        public World(bool sendWhenChecked = true)
        {
            System.IO.Directory.CreateDirectory(_root);
            var settings = UserSettings.Defaults();
            settings.RunRoot = Path.Combine(_root, "runs");
            settings.SendsWhenChecked = sendWhenChecked;
            string settingsPath = Path.Combine(_root, "settings.json");
            settings.Save(settingsPath);
            Host = new ReviewHost(new ReviewHostOptions(new Channel(Messages), Backend, settingsPath)
            {
                CurrentDocument = ReadDocument, Dump = Dump, EngineeringSelection = Selection, Engineer = "fictional-engineer", Environment = _ => null,
            });
        }

        private PageDocument? ReadDocument()
        {
            Action? callback = ReadDocumentCallback;
            ReadDocumentCallback = null;
            callback?.Invoke();
            return Document;
        }

        public JsonElement Reply(string type)
        {
            JsonElement? found = null;
            foreach (string message in Messages)
            {
                JsonElement root = JsonDocument.Parse(message).RootElement;
                if (root.GetProperty("type").GetString() == type) found = root.GetProperty("payload").Clone();
            }
            if (found.HasValue) return found.Value;
            throw new Xunit.Sdk.XunitException("Missing " + type + " reply: " + string.Join(" | ", Messages));
        }

        /// <summary>Prepare saved evidence and start a review with an exact attachment.</summary>
        public (string ContextId, string Head, string Sha) StartContextReview()
        {
            Host.Receive(Message("context.prepare", new { }));
            JsonElement prepared = Reply("context.prepared");
            string contextId = Guid.NewGuid().ToString();
            string head = new string('a', 64);
            string sha = prepared.GetProperty("package_sha256").GetString()!;
            Host.Receive(Message("context.review", new
            {
                run_id = prepared.GetProperty("run_id").GetString(), context_id = contextId,
                head_digest = head, package_sha256 = sha,
            }));
            Assert.Single(Backend.Created);
            return (contextId, head, sha);
        }

        /// <summary>The text of the last `status` message posted with `state`.</summary>
        public string Status(string state)
        {
            string? found = null;
            foreach (string message in Messages)
            {
                JsonElement root = JsonDocument.Parse(message).RootElement;
                if (root.GetProperty("type").GetString() != "status") continue;
                JsonElement payload = root.GetProperty("payload");
                if (payload.GetProperty("stage").GetString() == state) found = payload.GetProperty("message").GetString();
            }
            return found ?? throw new Xunit.Sdk.XunitException("Missing " + state + " status: " + string.Join(" | ", Messages));
        }

        public void Dispose()
        {
            Host.Dispose();
            System.IO.Directory.Delete(_root, true);
        }
    }

    private sealed class Channel : IPageChannel
    {
        private readonly List<string> _messages;
        public Channel(List<string> messages) => _messages = messages;
        public void PostMessage(string json) => _messages.Add(json);
    }

    private sealed class Dump : IReviewDump
    {
        public int Runs;
        public string? Directory;
        public Action? OnRun;
        public DumpSummary Run(string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
        {
            Runs++;
            OnRun?.Invoke();
            Directory = outputDirectory;
            File.WriteAllText(Path.Combine(outputDirectory, "package.json"), "{}");
            return new DumpSummary(Path.Combine(outputDirectory, "package.json"), 1, 0);
        }
    }

    private sealed class Selection : IEngineeringSelectionCapture
    {
        public List<(string Directory, string Sha)> Requests = new List<(string, string)>();
        public EngineeringSelectionObservation Capture(string directory, string expectedPackageSha256)
        {
            Requests.Add((directory, expectedPackageSha256));
            return new EngineeringSelectionObservation { Status = "matched_saved_target", PackageSha256 = expectedPackageSha256,
                Kind = "component", EntityId = "cmp:1", ComponentId = "cmp:1", DisplayName = "Fictional bracket" };
        }
    }

    private sealed class Backend : IBackendClient
    {
        public BackendEndpoint? Endpoint => new BackendEndpoint(51234, "fictional-token");
        public List<NewSessionRequest> Created = new List<NewSessionRequest>();
        public bool Running;
        public IReadOnlyList<ModelChoice> ListModels(string provider) => new ModelChoice[0];
        public bool IsTurnRunning(string chatId) => Running;
        public void Restart(UserSettings settings, ResolvedApiKey key) { }
        public BackendRequestException? NextError;
        public ChatSessionHandle CreateSession(NewSessionRequest request)
        {
            BackendRequestException? error = NextError;
            NextError = null;
            if (error != null) throw error;
            Created.Add(request);
            return new ChatSessionHandle("chat-context", "review-context");
        }
    }
}
