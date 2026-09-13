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
/// T031: the Settings half of the page-to-host contract in
/// `specs/002-task-pane-assistant/contracts/pane-host-messages.md`.
///
/// These run against <see cref="ReviewHost"/> with a fake channel and a fake backend, with no
/// WebView2 and no SOLIDWORKS, because the four things that have to hold are all decisions the
/// host makes and none of them are visible from inside the pane:
///
/// 1. <b>The key never goes back to the page.</b> `init`, `settings` and `settings.saved` carry
///    the settings *without* `api_key_protected` and without the key in any form; the page is
///    told only `key_source`. A page that could read the key back would put it in WebView2's
///    renderer process and in any crash dump of it (FR-015).
/// 2. <b>`settings.save` is refused while a turn is running</b> with
///    `error {error_class: "TurnRunning"}` - and refused *completely*: the settings file is not
///    written and the backend is not restarted, because a half-applied save is worse than a
///    refused one (chat-api.md, "Shutdown and settings changes").
/// 3. <b>A model the provider does not offer cannot be saved silently.</b> The save is refused
///    and the fresh model list is pushed to the page, so the engineer re-picks instead of
///    discovering it as an authentication-looking error on the next review.
/// 4. <b>`fake` is a development-build provider (FR-027).</b> A release build refuses to save it.
/// </summary>
public sealed class PageMessageTests
{
    private const string Key = "sk-proj-EXAMPLE-not-a-real-key-0123456789";

    // ---- ready / init -------------------------------------------------------------------

    [Fact]
    public void ReadyIsAnsweredWithInitCarryingTheBackendOriginAndNoKey()
    {
        using (var world = new HostWorld())
        {
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            world.Backend.Endpoint = new BackendEndpoint(51234, "0FAKEtoken");
            world.Document = new PageDocument(@"C:\parts\bracket.sldasm", "Default");
            world.Open();

            world.Receive("ready", "req-1", new { });

            JsonElement init = world.Reply("init", "req-1");
            Assert.Equal(51234, init.GetProperty("backend").GetProperty("port").GetInt32());
            Assert.Equal("http://127.0.0.1:51234", init.GetProperty("backend").GetProperty("origin").GetString());
            Assert.Equal("0FAKEtoken", init.GetProperty("token").GetString());
            Assert.Equal("settings", init.GetProperty("key_source").GetString());
            Assert.Equal(world.Settings.RunRoot, init.GetProperty("run_root").GetString());
            Assert.Equal(@"C:\parts\bracket.sldasm", init.GetProperty("document").GetProperty("path").GetString());
            Assert.Equal("Default", init.GetProperty("document").GetProperty("configuration").GetString());

            JsonElement settings = init.GetProperty("settings");
            Assert.False(settings.TryGetProperty("api_key_protected", out _));
            world.AssertNothingPostedContains(Key);
            world.AssertNothingPostedContains(world.Settings.ApiKeyProtected!);
        }
    }

    [Fact]
    public void InitCarriesANullDocumentAndNullBackendBeforeEitherExists()
    {
        using (var world = new HostWorld())
        {
            world.Backend.Endpoint = null;
            world.Document = null;
            world.Open();

            world.Receive("ready", "req-1", new { });

            JsonElement init = world.Reply("init", "req-1");
            Assert.Equal(JsonValueKind.Null, init.GetProperty("backend").ValueKind);
            Assert.Equal(JsonValueKind.Null, init.GetProperty("token").ValueKind);
            Assert.Equal(JsonValueKind.Null, init.GetProperty("document").ValueKind);
            Assert.Equal("none", init.GetProperty("key_source").GetString());
        }
    }

    [Fact]
    public void InitOffersTheScriptedProviderOnlyInADevelopmentBuild()
    {
        using (var development = new HostWorld(BuildMode.Development))
        {
            development.Open();
            development.Receive("ready", "d", new { });

            string[] offered = development.Reply("init", "d").GetProperty("providers")
                .EnumerateArray().Select(item => item.GetString()!).ToArray();
            Assert.Equal(new[] { "openai", "gemini", "fake" }, offered);
        }

        using (var release = new HostWorld(BuildMode.Release))
        {
            release.Open();
            release.Receive("ready", "r", new { });

            string[] offered = release.Reply("init", "r").GetProperty("providers")
                .EnumerateArray().Select(item => item.GetString()!).ToArray();
            Assert.Equal(new[] { "openai", "gemini" }, offered);
        }
    }

    [Fact]
    public void AProblemInTheSettingsFileIsReportedAfterInitAsAStatusMessage()
    {
        using (var world = new HostWorld(BuildMode.Release))
        {
            File.WriteAllText(
                world.SettingsPath,
                "{\"version\": 1, \"provider\": \"fake\", \"model\": \"fake-scripted\", \"effort\": \"high\","
                + " \"terminal_cli\": \"codex\", \"run_root\": \"C:\\\\runs\"}");
            world.Open();

            world.Receive("ready", "req-1", new { });

            Assert.Equal("openai", world.Reply("init", "req-1").GetProperty("settings")
                .GetProperty("provider").GetString());
            JsonElement status = world.LastPosted("status");
            Assert.Equal("error", status.GetProperty("stage").GetString());
            Assert.Contains("fake", status.GetProperty("message").GetString()!);
        }
    }

    // ---- settings.get -------------------------------------------------------------------

    [Fact]
    public void SettingsGetRepliesWithTheSettingsAndKeySourceAndNeverTheKey()
    {
        using (var world = new HostWorld())
        {
            world.Settings.Provider = "gemini";
            world.Settings.Model = "gemini-3.5-flash";
            world.Settings.Effort = "medium";
            world.Settings.GeminiEnterprise = new GeminiEnterpriseSettings { Project = "p", Location = "eu" };
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            world.Open();

            world.Receive("settings.get", "req-7", new { });

            JsonElement reply = world.Reply("settings", "req-7");
            JsonElement settings = reply.GetProperty("settings");
            Assert.Equal("gemini", settings.GetProperty("provider").GetString());
            Assert.Equal("gemini-3.5-flash", settings.GetProperty("model").GetString());
            Assert.Equal("medium", settings.GetProperty("effort").GetString());
            Assert.Equal("p", settings.GetProperty("gemini_enterprise").GetProperty("project").GetString());
            Assert.Equal("settings", reply.GetProperty("key_source").GetString());
            Assert.False(settings.TryGetProperty("api_key_protected", out _));
            world.AssertNothingPostedContains(Key);
        }
    }

    [Fact]
    public void SettingsGetReportsAKeyFoundOnlyInTheEnvironment()
    {
        using (var world = new HostWorld())
        {
            world.Environment["OPENAI_API_KEY"] = Key;
            world.Open();

            world.Receive("settings.get", "req-7", new { });

            Assert.Equal("env", world.Reply("settings", "req-7").GetProperty("key_source").GetString());
            world.AssertNothingPostedContains(Key);
        }
    }

    // ---- settings.save ------------------------------------------------------------------

    [Fact]
    public void SettingsSaveWritesTheFileRestartsTheBackendAndEchoesNoKey()
    {
        using (var world = new HostWorld())
        {
            world.Backend.Models["openai"] = new[] { new ModelChoice("gpt-5.6", "GPT-5.6") };
            world.Open();

            world.Receive("settings.save", "req-2", new
            {
                provider = "openai",
                model = "gpt-5.6",
                effort = "xhigh",
                api_key = Key,
                base_url = "https://gateway.example.invalid/v1",
                gemini_enterprise = (object?)null,
            });

            JsonElement saved = world.Reply("settings.saved", "req-2");
            Assert.Equal("settings", saved.GetProperty("key_source").GetString());
            Assert.Equal("xhigh", saved.GetProperty("settings").GetProperty("effort").GetString());
            Assert.False(saved.GetProperty("settings").TryGetProperty("api_key_protected", out _));
            world.AssertNothingPostedContains(Key);

            SettingsLoadResult reloaded = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Equal("xhigh", reloaded.Settings.Effort);
            Assert.Equal("https://gateway.example.invalid/v1", reloaded.Settings.BaseUrl);
            Assert.Equal(Key, reloaded.Settings.ResolveApiKey(name => null).Key);
            Assert.DoesNotContain(Key, File.ReadAllText(world.SettingsPath));

            Assert.Equal(1, world.Backend.Restarts);
            Assert.Equal("xhigh", world.Backend.RestartedWith!.Effort);
            Assert.Equal(Key, world.Backend.RestartedKey!.Key);
        }
    }

    [Fact]
    public void SettingsSavePreservesFieldsThePageDoesNotOwn()
    {
        using (var world = new HostWorld())
        {
            world.Settings.TerminalCli = "gemini";
            world.Settings.Python = @"C:\tools\uv.exe";
            world.Settings.RunRoot = @"C:\runs\here";
            world.Settings.Save(world.SettingsPath);
            world.Open();

            world.Receive("settings.save", "req-2", new
            {
                provider = "openai",
                model = "gpt-5.6",
                effort = "low",
                api_key = (string?)null,
                base_url = (string?)null,
                gemini_enterprise = (object?)null,
            });

            world.Reply("settings.saved", "req-2");
            SettingsLoadResult reloaded = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Equal("gemini", reloaded.Settings.TerminalCli);
            Assert.Equal(@"C:\tools\uv.exe", reloaded.Settings.Python);
            Assert.Equal(@"C:\runs\here", reloaded.Settings.RunRoot);
        }
    }

    [Fact]
    public void ANullApiKeyLeavesTheStoredKeyAloneAndAnEmptyOneClearsIt()
    {
        using (var world = new HostWorld())
        {
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            world.Open();

            // The page's key box is blank whenever a key is stored - it can never show one -
            // so a save that carries no key must not be a save that deletes it.
            world.Receive("settings.save", "keep", Save(apiKey: null));
            Assert.Equal("settings", world.Reply("settings.saved", "keep").GetProperty("key_source").GetString());
            Assert.Equal(Key, UserSettings.Load(world.SettingsPath, BuildMode.Development)
                .Settings.ResolveApiKey(name => null).Key);

            // Clearing is explicit: the page sends an empty string.
            world.Receive("settings.save", "clear", Save(apiKey: string.Empty));
            Assert.Equal("none", world.Reply("settings.saved", "clear").GetProperty("key_source").GetString());
            Assert.Null(UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.ApiKeyProtected);
        }
    }

    [Fact]
    public void ChangingTheProviderWithoutANewKeyClearsTheStoredOne()
    {
        using (var world = new HostWorld())
        {
            // There is one key slot in settings.schema.json and the page's key box is blank
            // whenever a key is stored, so a bare provider switch would otherwise restart the
            // backend with the engineer's OpenAI key in GEMINI_API_KEY - one vendor's
            // credential sent to another vendor's endpoint. The key belongs to the provider it
            // was entered for; changing the provider retires it.
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            string openAiCiphertext = world.Settings.ApiKeyProtected!;
            world.Open();

            world.Receive("settings.save", "switch", Save(
                provider: "gemini", model: "gemini-3.5-flash", apiKey: null));

            JsonElement saved = world.Reply("settings.saved", "switch");
            Assert.Equal("none", saved.GetProperty("key_source").GetString());
            Assert.Equal("gemini", saved.GetProperty("settings").GetProperty("provider").GetString());

            SettingsLoadResult reloaded = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Null(reloaded.Settings.ApiKeyProtected);
            Assert.DoesNotContain(openAiCiphertext, File.ReadAllText(world.SettingsPath));

            Assert.Equal(1, world.Backend.Restarts);
            Assert.Null(world.Backend.RestartedKey!.Key);
            Assert.Equal("none", world.Backend.RestartedKey!.Source);
        }
    }

    [Fact]
    public void ChangingTheProviderAndTheKeyTogetherStoresTheNewKey()
    {
        using (var world = new HostWorld())
        {
            // The switch is not refused - it is the one-step flow the Settings section offers:
            // pick the new provider, type that provider's key, Save.
            const string GeminiKey = "AIza-EXAMPLE-not-a-real-key-0123456789";
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            world.Open();

            world.Receive("settings.save", "switch", Save(
                provider: "gemini", model: "gemini-3.5-flash", apiKey: GeminiKey));

            Assert.Equal(
                "settings", world.Reply("settings.saved", "switch").GetProperty("key_source").GetString());
            Assert.Equal(
                GeminiKey,
                UserSettings.Load(world.SettingsPath, BuildMode.Development)
                    .Settings.ResolveApiKey(name => null).Key);
            Assert.Equal(GeminiKey, world.Backend.RestartedKey!.Key);
            world.AssertNothingPostedContains(GeminiKey);
        }
    }

    [Fact]
    public void SavingTheSameProviderLeavesTheStoredKeyAlone()
    {
        using (var world = new HostWorld())
        {
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            world.Open();

            world.Receive("settings.save", "same", Save(provider: "openai", effort: "low", apiKey: null));

            Assert.Equal(
                "settings", world.Reply("settings.saved", "same").GetProperty("key_source").GetString());
            Assert.Equal(
                Key,
                UserSettings.Load(world.SettingsPath, BuildMode.Development)
                    .Settings.ResolveApiKey(name => null).Key);
        }
    }

    [Fact]
    public void ABaseUrlIsRefusedForAProviderThatHasNoEndpointOverride()
    {
        using (var world = new HostWorld())
        {
            // `OPENAI_BASE_URL` is the only endpoint override the backend reads
            // (agent/settings.py `_env_base_url`, openai only). Accepting one for gemini,
            // echoing it back in `settings.saved` and then reviewing against the public
            // endpoint is the silent discard this refusal exists to prevent.
            world.Open();

            world.Receive("settings.save", "gw", Save(
                provider: "gemini",
                model: "gemini-3.5-flash",
                baseUrl: "https://gateway.example.invalid/v1"));

            JsonElement error = world.Reply("error", "gw");
            Assert.Equal("InvalidSettings", error.GetProperty("error_class").GetString());
            Assert.Contains("base URL", error.GetProperty("message").GetString()!, StringComparison.OrdinalIgnoreCase);
            Assert.Equal(0, world.Backend.Restarts);
            Assert.Equal("openai", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Provider);
        }
    }

    [Fact]
    public void SettingsSaveIsRefusedWhileATurnIsRunningAndChangesNothing()
    {
        using (var world = new HostWorld())
        {
            world.Settings.Effort = "high";
            world.Settings.Save(world.SettingsPath);
            world.Open();
            world.Host.TrackSession("chat-1", Path.Combine(world.Settings.RunRoot, "20260913-101500-bracket"));
            world.Backend.RunningTurns.Add("chat-1");

            world.Receive("settings.save", "req-3", Save(effort: "low", apiKey: Key));

            JsonElement error = world.Reply("error", "req-3");
            Assert.Equal("TurnRunning", error.GetProperty("error_class").GetString());
            Assert.False(string.IsNullOrWhiteSpace(error.GetProperty("message").GetString()));
            Assert.Equal(0, world.Backend.Restarts);
            Assert.Equal("high", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
            Assert.Null(UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.ApiKeyProtected);
            world.AssertNothingPostedContains(Key);
        }
    }

    [Fact]
    public void TheSameSaveSucceedsOnceTheTurnHasEnded()
    {
        using (var world = new HostWorld())
        {
            world.Open();
            world.Host.TrackSession("chat-1", Path.Combine(world.Settings.RunRoot, "20260913-101500-bracket"));
            world.Backend.RunningTurns.Add("chat-1");
            world.Receive("settings.save", "req-3", Save(effort: "low"));
            world.Reply("error", "req-3");

            world.Backend.RunningTurns.Clear();
            world.Receive("settings.save", "req-4", Save(effort: "low"));

            world.Reply("settings.saved", "req-4");
            Assert.Equal(1, world.Backend.Restarts);
        }
    }

    [Fact]
    public void ATurnRunningOnAnotherChatAlsoRefusesTheSave()
    {
        using (var world = new HostWorld())
        {
            world.Open();
            world.Host.TrackSession("chat-1", world.Settings.RunRoot);
            world.Host.TrackSession("chat-2", world.Settings.RunRoot);
            world.Backend.RunningTurns.Add("chat-2");

            world.Receive("settings.save", "req-3", Save(effort: "low"));

            Assert.Equal("TurnRunning", world.Reply("error", "req-3").GetProperty("error_class").GetString());
        }
    }

    [Fact]
    public void AReleaseBuildRefusesToSaveTheScriptedProvider()
    {
        using (var world = new HostWorld(BuildMode.Release))
        {
            world.Open();

            world.Receive("settings.save", "req-5", Save(provider: "fake", model: "fake-scripted"));

            JsonElement error = world.Reply("error", "req-5");
            Assert.Equal("FakeProviderNotAllowed", error.GetProperty("error_class").GetString());
            Assert.Equal(0, world.Backend.Restarts);
            Assert.Equal("openai", UserSettings.Load(world.SettingsPath, BuildMode.Release).Settings.Provider);
        }
    }

    [Fact]
    public void ADevelopmentBuildSavesTheScriptedProvider()
    {
        using (var world = new HostWorld(BuildMode.Development))
        {
            world.Backend.Models["fake"] = new[] { new ModelChoice("fake-scripted", "Scripted (development)") };
            world.Open();

            world.Receive("settings.save", "req-5", Save(provider: "fake", model: "fake-scripted"));

            world.Reply("settings.saved", "req-5");
            Assert.Equal("fake", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Provider);
        }
    }

    [Theory]
    [InlineData("provider", "anthropic")]
    [InlineData("effort", "maximum")]
    [InlineData("model", "")]
    public void SettingsSaveRefusesValuesTheContractDoesNotAllow(string field, string value)
    {
        using (var world = new HostWorld())
        {
            world.Open();

            world.Receive("settings.save", "req-6", new Dictionary<string, object?>
            {
                { "provider", field == "provider" ? value : "openai" },
                { "model", field == "model" ? value : "gpt-5.6" },
                { "effort", field == "effort" ? value : "high" },
                { "api_key", null },
                { "base_url", null },
                { "gemini_enterprise", null },
            });

            JsonElement error = world.Reply("error", "req-6");
            Assert.Equal("InvalidSettings", error.GetProperty("error_class").GetString());
            Assert.Contains(field, error.GetProperty("message").GetString()!);
            Assert.Equal(0, world.Backend.Restarts);
        }
    }

    // ---- models.list --------------------------------------------------------------------

    [Fact]
    public void ModelsListProxiesToTheBackend()
    {
        using (var world = new HostWorld())
        {
            world.Backend.Models["openai"] = new[]
            {
                new ModelChoice("gpt-5.6", "GPT-5.6"),
                new ModelChoice("gpt-5.6-mini", "GPT-5.6 mini"),
            };
            world.Open();

            world.Receive("models.list", "req-8", new { provider = "openai" });

            JsonElement reply = world.Reply("models", "req-8");
            Assert.Equal("openai", reply.GetProperty("provider").GetString());
            Assert.Equal(
                new[] { "gpt-5.6", "gpt-5.6-mini" },
                reply.GetProperty("models").EnumerateArray().Select(m => m.GetProperty("id").GetString()).ToArray());
            Assert.Equal("GPT-5.6", reply.GetProperty("models")[0].GetProperty("label").GetString());
        }
    }

    [Fact]
    public void ModelsListSurfacesTheProviderErrorClassRedacted()
    {
        using (var world = new HostWorld())
        {
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            world.Backend.ModelsFailure = new BackendRequestException(
                "AuthenticationError", "invalid api key " + Key, retryable: false);
            world.Open();

            world.Receive("models.list", "req-8", new { provider = "openai" });

            JsonElement error = world.Reply("error", "req-8");
            Assert.Equal("AuthenticationError", error.GetProperty("error_class").GetString());
            Assert.DoesNotContain(Key, error.GetProperty("message").GetString()!);
            Assert.False(error.GetProperty("retryable").GetBoolean());
        }
    }

    [Fact]
    public void ModelsListWithoutABackendSaysSoRatherThanThrowing()
    {
        using (var world = new HostWorld())
        {
            world.Backend.Endpoint = null;
            world.Open();

            world.Receive("models.list", "req-8", new { provider = "openai" });

            Assert.Equal("BackendUnavailable", world.Reply("error", "req-8").GetProperty("error_class").GetString());
        }
    }

    [Fact]
    public void AModelTheProviderRejectsIsRefusedAndRetriggersTheModelList()
    {
        using (var world = new HostWorld())
        {
            world.Backend.Models["openai"] = new[]
            {
                new ModelChoice("gpt-5.6", "GPT-5.6"),
                new ModelChoice("gpt-5.6-mini", "GPT-5.6 mini"),
            };
            world.Open();

            world.Receive("settings.save", "req-9", Save(model: "gpt-4o-retired"));

            JsonElement error = world.Reply("error", "req-9");
            Assert.Equal("UnknownModel", error.GetProperty("error_class").GetString());
            Assert.Contains("gpt-4o-retired", error.GetProperty("message").GetString()!);

            // The page does not have to ask again: the refreshed list is pushed with it, so the
            // picker re-renders with what the provider actually offers.
            JsonElement models = world.LastPosted("models");
            Assert.Equal("openai", models.GetProperty("provider").GetString());
            Assert.Equal(2, models.GetProperty("models").GetArrayLength());

            Assert.Equal(0, world.Backend.Restarts);
            Assert.Equal("gpt-5.6", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Model);
        }
    }

    [Fact]
    public void AModelIsSavedUncheckedWhenTheProviderCannotBeAsked()
    {
        using (var world = new HostWorld())
        {
            // No key, no network, an enterprise gateway that is down: none of those may stop an
            // engineer configuring the pane. Validation is a courtesy, not a gate.
            world.Backend.ModelsFailure = new BackendRequestException(
                "APIConnectionError", "connection refused", retryable: true);
            world.Open();

            world.Receive("settings.save", "req-9", Save(model: "gpt-5.6-preview"));

            world.Reply("settings.saved", "req-9");
            Assert.Equal(
                "gpt-5.6-preview",
                UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Model);
        }
    }

    // ---- everything else ----------------------------------------------------------------

    [Fact]
    public void AnUnknownMessageTypeIsAnsweredWithAnError()
    {
        using (var world = new HostWorld())
        {
            world.Open();

            world.Receive("settings.reset", "req-10", new { });

            JsonElement error = world.Reply("error", "req-10");
            Assert.Contains("settings.reset", error.GetProperty("message").GetString()!);
        }
    }

    [Fact]
    public void MalformedJsonIsAnsweredWithAnErrorAndNeverThrows()
    {
        using (var world = new HostWorld())
        {
            world.Open();

            world.Host.Receive("{\"type\": \"settings.get\"");
            world.Host.Receive("[]");
            world.Host.Receive(string.Empty);

            Assert.Equal(3, world.Posted.Count(message => TypeOf(message) == "error"));
        }
    }

    [Fact]
    public void AHandlerThatThrowsBecomesAnErrorReplyWithTheKeyRedacted()
    {
        using (var world = new HostWorld())
        {
            world.Settings.SetApiKey(Key);
            world.Settings.Save(world.SettingsPath);
            world.Backend.ModelsThrow = new InvalidOperationException("boom for " + Key);
            world.Open();

            world.Receive("models.list", "req-11", new { provider = "openai" });

            JsonElement error = world.Reply("error", "req-11");
            Assert.DoesNotContain(Key, error.GetProperty("message").GetString()!);
            Assert.Contains(Redaction.Mask, error.GetProperty("message").GetString()!);
        }
    }

    // ---- helpers ------------------------------------------------------------------------

    private static Dictionary<string, object?> Save(
        string provider = "openai",
        string model = "gpt-5.6",
        string effort = "high",
        string? apiKey = null,
        string? baseUrl = null)
    {
        return new Dictionary<string, object?>
        {
            { "provider", provider },
            { "model", model },
            { "effort", effort },
            { "api_key", apiKey },
            { "base_url", baseUrl },
            { "gemini_enterprise", null },
        };
    }

    private static string TypeOf(string message)
    {
        using (JsonDocument document = JsonDocument.Parse(message))
        {
            return document.RootElement.GetProperty("type").GetString()!;
        }
    }

    /// <summary>Channel, backend, settings file and host, torn down together.</summary>
    private sealed class HostWorld : IDisposable
    {
        private readonly string _root;
        private readonly BuildMode _mode;
        private ReviewHost? _host;

        public HostWorld(BuildMode mode = BuildMode.Development)
        {
            _mode = mode;
            _root = Path.Combine(Path.GetTempPath(), "SwReview.PageMessage.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            SettingsPath = Path.Combine(_root, "settings.json");
            Settings = UserSettings.Defaults();
            Settings.RunRoot = Path.Combine(_root, "runs");
        }

        public string SettingsPath { get; }

        public UserSettings Settings { get; }

        public FakeBackend Backend { get; } = new FakeBackend();

        public Dictionary<string, string> Environment { get; } =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public PageDocument? Document { get; set; }

        public List<string> Posted { get; } = new List<string>();

        public ReviewHost Host => _host ?? throw new InvalidOperationException("call Open() first");

        /// <summary>Writes the settings file if the test has not, then builds the host.</summary>
        public void Open()
        {
            if (!File.Exists(SettingsPath))
            {
                Settings.Save(SettingsPath);
            }

            var options = new ReviewHostOptions(new FakeChannel(Posted), Backend, SettingsPath)
            {
                BuildMode = _mode,
                LogFolder = Path.Combine(_root, "logs"),
                CurrentDocument = () => Document,
                Environment = name => Environment.TryGetValue(name, out string? value) ? value : null,
            };
            _host = new ReviewHost(options);
        }

        public void Receive(string type, string id, object payload)
        {
            Host.Receive(JsonSerializer.Serialize(new { type, id, payload }));
        }

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
                $"expected exactly one '{type}' reply to '{id}', saw {matches.Count}; "
                + $"posted: {string.Join(" | ", Posted.Select(TypeOf))}");
            return matches[0];
        }

        /// <summary>The payload of the last unsolicited message of <paramref name="type"/>.</summary>
        public JsonElement LastPosted(string type)
        {
            for (int index = Posted.Count - 1; index >= 0; index--)
            {
                JsonElement root = JsonDocument.Parse(Posted[index]).RootElement;
                if (root.GetProperty("type").GetString() == type)
                {
                    return root.GetProperty("payload");
                }
            }

            throw new Xunit.Sdk.XunitException($"no '{type}' message was posted");
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
        }
    }

    private sealed class FakeChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public FakeChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json) => _posted.Add(json);
    }

    private sealed class FakeBackend : IBackendClient
    {
        public BackendEndpoint? Endpoint { get; set; } = new BackendEndpoint(51234, "0FAKEtoken");

        public Dictionary<string, IReadOnlyList<ModelChoice>> Models { get; } =
            new Dictionary<string, IReadOnlyList<ModelChoice>>(StringComparer.Ordinal);

        public BackendRequestException? ModelsFailure { get; set; }

        public Exception? ModelsThrow { get; set; }

        public HashSet<string> RunningTurns { get; } = new HashSet<string>(StringComparer.Ordinal);

        public int Restarts { get; private set; }

        public UserSettings? RestartedWith { get; private set; }

        public ResolvedApiKey? RestartedKey { get; private set; }

        public IReadOnlyList<ModelChoice> ListModels(string provider)
        {
            if (ModelsThrow != null)
            {
                throw ModelsThrow;
            }

            if (ModelsFailure != null)
            {
                throw ModelsFailure;
            }

            return Models.TryGetValue(provider, out IReadOnlyList<ModelChoice>? models)
                ? models
                : new ModelChoice[0];
        }

        public bool IsTurnRunning(string chatId) => RunningTurns.Contains(chatId);

        /// <summary>Part of the seam, exercised by <see cref="ReviewHostTests"/>; no Settings
        /// message starts a chat, so nothing here calls it.</summary>
        public ChatSessionHandle CreateSession(NewSessionRequest request) =>
            throw new NotSupportedException("the Settings tests never start a review");

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
            Restarts++;
            RestartedWith = settings;
            RestartedKey = key;
        }
    }
}
