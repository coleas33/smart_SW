using System;
using System.Linq;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T045. The `secret` field and the two scopes it selects
/// (specs/002-task-pane-assistant/contracts/README.md, Serve/PROTOCOL.md).
///
/// The policy is injected rather than baked into the dispatcher because the two hosts
/// differ: the console host (`swreview-extract serve`) has no secret at all - its boundary
/// is the pipe - while the in-process host inside the add-in issues two per-launch secrets
/// and requires one on every line.
///
/// The general-chat scope is the reason this lives in the dispatcher and not in the MCP
/// allowlist: the CLI can read the profile that lists its own tools, so a scope the
/// dispatcher enforces is the only place `interference` is actually withheld from general
/// chat (FR-022).
/// </summary>
public class BridgeSecretPolicyTests : IDisposable
{
    private const string ReviewSecret = "review-secret-abc";
    private const string ChatSecret = "chat-secret-xyz";

    private readonly string _captureDirectory;
    private readonly FakeCaptureView _captureView = new FakeCaptureView();

    public BridgeSecretPolicyTests()
    {
        _captureDirectory = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (System.IO.Directory.Exists(_captureDirectory))
        {
            System.IO.Directory.Delete(_captureDirectory, recursive: true);
        }
    }

    // ---- the console host: no secret ---------------------------------------------

    [Theory]
    [InlineData(BridgeCommands.Ping)]
    [InlineData(BridgeCommands.Capture)]
    [InlineData(BridgeCommands.Measure)]
    [InlineData(BridgeCommands.Interference)]
    public void NoSecretPolicy_AuthorizesEveryCommand_WithOrWithoutASecret(string command)
    {
        Assert.True(NoSecretPolicy.Instance.IsAuthorized(null, command));
        Assert.True(NoSecretPolicy.Instance.IsAuthorized(string.Empty, command));
        Assert.True(NoSecretPolicy.Instance.IsAuthorized("anything at all", command));
    }

    [Fact]
    public void NoSecretPolicy_Host_IgnoresASecretOnTheLine()
    {
        // A client written for the in-process host still works against the console host.
        BridgeResponse response = Dispatch(
            Request("1", BridgeCommands.Ping, secret: ChatSecret), NoSecretPolicy.Instance);

        Assert.Equal(BridgeStatus.Ok, response.Status);
    }

    // ---- the in-process host: two secrets, two scopes -----------------------------

    [Theory]
    [InlineData(BridgeCommands.Ping)]
    [InlineData(BridgeCommands.Capture)]
    [InlineData(BridgeCommands.Measure)]
    [InlineData(BridgeCommands.Interference)]
    [InlineData(BridgeCommands.Tessellate)]
    public void ScopedSecretPolicy_ReviewSecret_AuthorizesTheWholeReviewVocabulary(string command)
    {
        Assert.True(Scoped().IsAuthorized(ReviewSecret, command));
    }

    [Theory]
    [InlineData(BridgeCommands.Ping)]
    [InlineData(BridgeCommands.Capture)]
    [InlineData(BridgeCommands.Measure)]
    public void ScopedSecretPolicy_GeneralChatSecret_AuthorizesTheReadOnlySubset(string command)
    {
        Assert.True(Scoped().IsAuthorized(ChatSecret, command));
    }

    [Fact]
    public void ScopedSecretPolicy_GeneralChatSecret_DoesNotAuthorizeInterference()
    {
        Assert.False(Scoped().IsAuthorized(ChatSecret, BridgeCommands.Interference));
    }

    [Fact]
    public void ScopedSecretPolicy_GeneralChatSecret_DoesNotAuthorizeTessellate()
    {
        // Review scope only (T096): a mesh fetch writes a file and can take seconds, so it
        // does not go to general chat. The refusal is the indistinguishable `unauthorized`
        // every other out-of-scope command gets.
        Assert.False(Scoped().IsAuthorized(ChatSecret, BridgeCommands.Tessellate));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("not-a-secret")]
    [InlineData("REVIEW-SECRET-ABC")]
    [InlineData("review-secret-ab")]
    [InlineData("review-secret-abc ")]
    public void ScopedSecretPolicy_AnythingButTheTwoSecrets_AuthorizesNothing(string? secret)
    {
        ScopedSecretPolicy policy = Scoped();

        foreach (string command in BridgeCommands.All)
        {
            Assert.False(policy.IsAuthorized(secret, command));
        }
    }

    [Theory]
    [InlineData("rebuild")]
    [InlineData("Save3")]
    [InlineData("")]
    public void ScopedSecretPolicy_CommandOutsideTheVocabulary_IsNeverAuthorized(string command)
    {
        ScopedSecretPolicy policy = Scoped();

        Assert.False(policy.IsAuthorized(ReviewSecret, command));
        Assert.False(policy.IsAuthorized(ChatSecret, command));
    }

    [Fact]
    public void ScopedSecretPolicy_ScopesAreExactlyWhatTheContractNames()
    {
        Assert.Equal(
            new[]
            {
                BridgeCommands.Ping,
                BridgeCommands.Capture,
                BridgeCommands.Measure,
                BridgeCommands.Interference,
                BridgeCommands.Tessellate,
            },
            ScopedSecretPolicy.ReviewCommands.ToArray());

        Assert.Equal(
            new[] { BridgeCommands.Ping, BridgeCommands.Capture, BridgeCommands.Measure },
            ScopedSecretPolicy.GeneralChatCommands.ToArray());
    }

    [Theory]
    [InlineData(null, ChatSecret)]
    [InlineData("", ChatSecret)]
    [InlineData("   ", ChatSecret)]
    [InlineData(ReviewSecret, null)]
    [InlineData(ReviewSecret, "")]
    [InlineData(ReviewSecret, "   ")]
    public void ScopedSecretPolicy_EmptySecret_IsRefusedAtConstruction(string? review, string? chat)
    {
        // An empty secret would be matched by a line that simply omits the field.
        Assert.Throws<ArgumentException>(() => new ScopedSecretPolicy(review!, chat!));
    }

    [Fact]
    public void ScopedSecretPolicy_OneSecretForBothScopes_IsRefusedAtConstruction()
    {
        // Reusing one secret would authenticate without bounding what it authorizes, which
        // is the whole point of issuing two.
        Assert.Throws<ArgumentException>(() => new ScopedSecretPolicy(ReviewSecret, ReviewSecret));
    }

    // ---- what the dispatcher answers ----------------------------------------------

    [Fact]
    public void Dispatch_ReviewSecret_RunsTheCommand()
    {
        BridgeResponse response = Dispatch(
            Request("1", BridgeCommands.Ping, secret: ReviewSecret), Scoped());

        Assert.Equal(BridgeStatus.Ok, response.Status);
        Assert.IsType<PingResult>(response.Result);
    }

    [Fact]
    public void Dispatch_GeneralChatSecretAskingForInterference_IsUnauthorized()
    {
        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, secret: ChatSecret), Scoped());

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
        Assert.Null(response.Result);
    }

    [Fact]
    public void Dispatch_WrongSecret_IsUnauthorizedAndIndistinguishableFromAScopeRefusal()
    {
        // The message says nothing about which of the two went wrong, and never echoes the
        // secret that was offered.
        BridgeResponse wrong = Dispatch(
            Request("4", BridgeCommands.Interference, secret: "guessed"), Scoped());
        BridgeResponse scoped = Dispatch(
            Request("4", BridgeCommands.Interference, secret: ChatSecret), Scoped());

        Assert.Equal(scoped.Status, wrong.Status);
        Assert.Equal(scoped.Error, wrong.Error);
        Assert.Equal("unauthorized", wrong.Error);
        Assert.DoesNotContain("guessed", wrong.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Dispatch_MissingSecret_IsUnauthorized()
    {
        BridgeResponse response = Dispatch(Request("1", BridgeCommands.Ping), Scoped());

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
    }

    [Fact]
    public void Dispatch_Unauthorized_NeverTouchesSolidworks()
    {
        // The refusal happens before the handler, so an unauthorized capture leaves no
        // selection change and no PNG behind.
        BridgeResponse response = Dispatch(
            Request(
                "2",
                BridgeCommands.Capture,
                "{\"persist_ref\":\"cmVm\",\"view\":\"iso\"}",
                secret: null),
            Scoped());

        Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
        Assert.Empty(_captureView.Calls);
        Assert.False(System.IO.Directory.Exists(_captureDirectory));
    }

    [Fact]
    public void Dispatch_Unauthorized_StillCarriesTheIdAndTheElapsedTime()
    {
        BridgeResponse response = Dispatch(
            Request("9", BridgeCommands.Interference, secret: ChatSecret), Scoped());

        Assert.Equal("9", response.Id);
        Assert.True(response.ElapsedMs >= 0);
    }

    [Fact]
    public void Dispatch_UnknownCommandWithAValidSecret_IsUnauthorizedNotACommandList()
    {
        // Under a scoped policy the vocabulary itself is part of what the secret authorizes,
        // so a probe learns nothing from the answer.
        BridgeResponse response = Dispatch(
            Request("1", "rebuild", secret: ReviewSecret), Scoped());

        Assert.Equal(SwBridgeDispatcher.UnauthorizedError, response.Error);
    }

    // ---- helpers -----------------------------------------------------------------

    private static ScopedSecretPolicy Scoped() => new ScopedSecretPolicy(ReviewSecret, ChatSecret);

    private static BridgeRequest Request(
        string id, string command, string? paramsJson = null, string? secret = null)
    {
        string line = "{\"id\":\"" + id + "\",\"command\":\"" + command + "\""
            + (paramsJson == null ? string.Empty : ",\"params\":" + paramsJson)
            + (secret == null ? string.Empty : ",\"secret\":\"" + secret + "\"")
            + "}";

        // Through the codec, so these tests exercise the same parse the pipe does.
        return JsonSerializer.Deserialize<BridgeRequest>(line, BridgeCodec.Options)!;
    }

    private BridgeResponse Dispatch(BridgeRequest request, ISecretPolicy secrets)
    {
        var services = new BridgeServices(
            _captureView,
            new FakeMeasureSource("no measure source in this test"),
            new FakeInterferenceSource(new FakeInterferenceDetector()),
            new ComponentIndex(new ComponentTreeResult { ActiveConfiguration = "Default" }),
            _captureDirectory)
        {
            SwVersion = "32.5.0",
            DocumentPath = @"C:\work\bracket-assy.SLDASM",
            Configuration = "Default",
        };

        return new SwBridgeDispatcher(services, secrets).Dispatch(request);
    }
}
