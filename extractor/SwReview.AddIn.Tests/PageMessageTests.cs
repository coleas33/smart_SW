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
            // The page's own origin under `/__backend`, not the backend's loopback one: the
            // page never crosses the network boundary and the host serves that prefix from C#
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
            Assert.Equal("settings", init.GetProperty("key_source").GetString());
            Assert.Equal(world.Settings.RunRoot, init.GetProperty("run_root").GetString());
            Assert.Equal(@"C:\parts\bracket.sldasm", init.GetProperty("document").GetProperty("path").GetString());
            Assert.Equal("Default", init.GetProperty("document").GetProperty("configuration").GetString());

            JsonElement settings = init.GetProperty("settings");
            Assert.True(settings.GetProperty("send_when_checked").GetBoolean());
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

    [Fact]
    public void ABoxSavePersistsWithoutRestartEvenDuringATurnAndPreservesEveryOtherField()
    {
        using (var world = new HostWorld())
        {
            world.Settings.SetApiKey(Key);
            world.Settings.TerminalCli = "gemini";
            world.Settings.Save(world.SettingsPath);
            world.Open();
            world.Host.TrackSession("chat-1", world.Settings.RunRoot);
            world.Backend.RunningTurns.Add("chat-1");
            world.Receive("send_when_checked.save", "box", new { send_when_checked = false });
            Assert.False(world.Reply("send_when_checked.saved", "box").GetProperty("send_when_checked").GetBoolean());
            Assert.Equal(0, world.Backend.Restarts);
            UserSettings stored = UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings;
            Assert.False(stored.SendsWhenChecked);
            stored.SendWhenCheckedValue = null;
            Assert.Equal(world.Settings.ToJson(), stored.ToJson());
            world.Receive("settings.get", "get", new { });
            Assert.False(world.Reply("settings", "get").GetProperty("settings").GetProperty("send_when_checked").GetBoolean());
            world.AssertNothingPostedContains(Key);
        }
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("{\"send_when_checked\":null}")]
    [InlineData("{\"send_when_checked\":\"false\"}")]
    [InlineData("{\"send_when_checked\":0}")]
    public void ABoxSaveRequiresAJsonBoolean(string payload)
    {
        using (var world = new HostWorld())
        {
            world.Open();
            byte[] before = File.ReadAllBytes(world.SettingsPath);
            world.Receive("send_when_checked.save", "bad", JsonDocument.Parse(payload).RootElement);
            Assert.Equal("InvalidRequest", world.Reply("error", "bad").GetProperty("error_class").GetString());
            Assert.Equal(before, File.ReadAllBytes(world.SettingsPath));
            Assert.Equal(0, world.Backend.Restarts);
        }
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void EitherSettingsWriterReportsAFailedWriteAndKeepsTheStoredSettings(bool box)
    {
        using (var world = new HostWorld())
        {
            world.Open();
            File.Delete(world.SettingsPath);
            Directory.CreateDirectory(world.SettingsPath);
            world.Receive(box ? "send_when_checked.save" : "settings.save", "fail", box ? (object)new { send_when_checked = false } : Save(effort: "low"));
            Assert.Equal("SettingNotSaved", world.Reply("error", "fail").GetProperty("error_class").GetString());
            Assert.Equal(0, world.Backend.Restarts);
            world.Receive("settings.get", "get", new { });
            JsonElement settings = world.Reply("settings", "get").GetProperty("settings");
            Assert.True(settings.GetProperty("send_when_checked").GetBoolean());
            Assert.Equal("high", settings.GetProperty("effort").GetString());
        }
    }

    [Fact]
    public void ABoxSaveClearsTheLoadProblemAsASettingsSaveDoes()
    {
        using (var world = new HostWorld())
        {
            File.WriteAllText(world.SettingsPath, world.Settings.ToJson().Replace("\"effort\": \"high\"", "\"effort\": \"invalid\""));
            world.Open();
            world.Receive("ready", "ready", new { });
            Assert.Equal("error", world.LastPosted("status").GetProperty("stage").GetString());
            world.Receive("send_when_checked.save", "box", new { send_when_checked = false });
            world.Reply("send_when_checked.saved", "box");
            Assert.Null(UserSettings.Load(world.SettingsPath, BuildMode.Development).Error);
            world.Posted.Clear();
            world.Receive("settings.get", "get", new { });
            world.Reply("settings", "get");
            Assert.DoesNotContain(world.Posted, message => JsonDocument.Parse(message).RootElement.GetProperty("type").GetString() == "status");
        }
    }

    [Fact]
    public void SettingsSaveKeepsTheHeldFalseTokenAndAcceptsAWaitingReview()
    {
        using (var world = new HostWorld())
        {
            world.Settings.SendsWhenChecked = false;
            world.Open();
            world.Host.TrackSession("waiting", world.Settings.RunRoot);
            world.Receive("settings.save", "save", Save(effort: "low"));
            Assert.False(world.Reply("settings.saved", "save").GetProperty("settings").GetProperty("send_when_checked").GetBoolean());
            Assert.False(UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.SendsWhenChecked);
            Assert.Equal(1, world.Backend.Restarts);
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

    /// <summary>
    /// Owner decision 143A, the words: the refusal says what happened and what to do, and
    /// promises nothing. It used to say "settings are saved once it finishes", and nothing saves
    /// them then: nothing was written, and the engineer presses Save again.
    /// </summary>
    [Fact]
    public void TheRefusalSaysNothingWasSavedAndPromisesNothing()
    {
        using (var world = new HostWorld())
        {
            world.Open();
            world.Host.TrackSession("chat-1", Path.Combine(world.Settings.RunRoot, "20261019-101500-bracket"));
            world.Backend.RunningTurns.Add("chat-1");

            world.Receive("settings.save", "req-3", Save(effort: "low"));

            Assert.Equal(
                "a review turn is running, so the settings were not saved. Stop the turn, or wait "
                    + "for it to end, and press Save again.",
                world.Reply("error", "req-3").GetProperty("message").GetString());
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

    // ---- owner decision 154A and its follow-up: the run root in Settings -------------------

    /// <summary>
    /// The owner's follow-up to decision 154A (feature 002 T194, "A Field + don't block"): a save never
    /// refuses other settings because of the run root. With a refused run root in force and none chosen - the
    /// page sent no folder, or the one in force - the save goes through as any save does: every setting is
    /// written, the backend is restarted, the run root in force stays, and the answer also says the run root
    /// is refused, in the rule's words for the root left in force, with the way on and no path. The send box
    /// saves as it always did. Changed deliberately from decision 154A's first answer (T191), which refused
    /// the whole save and the box, so that no key or model could be saved until the file was edited by hand.
    /// </summary>
    [Theory]
    [MemberData(nameof(FakeRunRootProbe.RefusedKinds), MemberType = typeof(FakeRunRootProbe))]
    public void ASaveUnderARefusedRunRootSavesEverySettingAndSaysTheRunRootIsRefused(string kind)
    {
        using (var world = new HostWorld())
        {
            string local = world.Settings.RunRoot;
            var refusing = FakeRunRootProbe.Refusing(kind, local);
            world.Settings.RunRoot = refusing.RunRoot;
            world.Probe = refusing.Probe;
            world.Open();

            world.Receive("settings.save", "save", Save(effort: "low", apiKey: Key));
            Dictionary<string, object?> same = Save(effort: "medium");
            same["run_root"] = refusing.RunRoot;
            world.Receive("settings.save", "same", same);
            world.Receive("send_when_checked.save", "box", new { send_when_checked = false });

            foreach (string id in new[] { "save", "same" })
            {
                JsonElement refusal = world.Reply("settings.saved", id).GetProperty("run_root_refusal");
                Assert.Equal("RunRootRefused", refusal.GetProperty("error_class").GetString());
                Assert.False(refusal.GetProperty("retryable").GetBoolean());
                Assert.Equal(RunRootRule.KeptRefusal(refusing.Verdict), refusal.GetProperty("message").GetString());
                Assert.DoesNotContain(
                    Path.GetFileName(Path.GetDirectoryName(local)!), refusal.GetProperty("message").GetString()!);
            }

            world.Reply("send_when_checked.saved", "box");
            SettingsLoadResult saved = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Equal("medium", saved.Settings.Effort);
            Assert.False(saved.Settings.SendsWhenChecked);
            Assert.Equal(Key, saved.Settings.ResolveApiKey(name => null).Key);
            Assert.Equal(refusing.RunRoot, saved.Settings.RunRoot);
            Assert.Equal(refusing.RunRoot, world.Host.RunRoot);
            Assert.Equal(2, world.Backend.Restarts);
            Assert.Empty(Posted(world, "error"));
            world.AssertNothingPostedContains(Key);
        }
    }

    /// <summary>
    /// A settings file that names no run root holds the default, Documents\SwReview\runs: under a Documents
    /// on a mapped drive it is refused, and a save goes through all the same - the default written into the
    /// file, as every save writes the run root in force - and its answer says the run root is refused.
    /// Changed deliberately from decision 154A's first answer (T191), which refused the save and wrote nothing.
    /// </summary>
    [Fact]
    public void ASaveUnderARefusedDefaultRunRootGoesThroughAndSaysSo()
    {
        using (var world = new HostWorld())
        {
            File.WriteAllText(
                world.SettingsPath,
                "{\"version\": 1, \"provider\": \"openai\", \"model\": \"gpt-5.6\", \"effort\": \"high\", \"terminal_cli\": \"codex\"}");
            world.Probe = FakeRunRootProbe.OnANetworkDrive();
            world.Open();

            world.Receive("settings.save", "save", Save(effort: "low"));

            JsonElement saved = world.Reply("settings.saved", "save");
            Assert.Equal(
                RunRootRule.KeptRefusal(RunRootVerdict.Share),
                saved.GetProperty("run_root_refusal").GetProperty("message").GetString());
            SettingsLoadResult file = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Equal("low", file.Settings.Effort);
            Assert.Equal(UserSettings.DefaultRunRoot(), file.Settings.RunRoot);
            Assert.Equal(1, world.Backend.Restarts);
        }
    }

    /// <summary>
    /// A folder chosen for runs that the rule accepts is saved - trimmed, as every text field is - and the
    /// backend is restarted with it: the backend refuses a run folder outside the run root it was started
    /// with, so the run root comes into force with that restart. The answer says nothing of the run root.
    /// </summary>
    [Fact]
    public void AFolderChosenForRunsThatTheRuleAcceptsIsSavedAndTheBackendRestartsWithIt()
    {
        using (var world = new HostWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.Open();
            string chosen = Path.Combine(Path.GetDirectoryName(world.Settings.RunRoot)!, "chosen", "runs");
            Dictionary<string, object?> payload = Save(effort: "low");
            payload["run_root"] = "  " + chosen + "  ";

            world.Receive("settings.save", "save", payload);

            JsonElement saved = world.Reply("settings.saved", "save");
            Assert.False(saved.TryGetProperty("run_root_refusal", out _));
            Assert.Equal(chosen, saved.GetProperty("settings").GetProperty("run_root").GetString());
            Assert.Equal(chosen, UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.RunRoot);
            Assert.Equal(chosen, world.Host.Settings.RunRoot);
            Assert.Equal(chosen, world.Host.RunRoot);
            Assert.Equal(1, world.Backend.Restarts);
            Assert.Equal(chosen, world.Backend.RestartedWith!.RunRoot);
            Assert.Contains("FinalPathOf " + chosen, probe.Asked);
        }
    }

    /// <summary>
    /// A folder chosen for runs that the rule refuses is the one field not saved: every other setting in the
    /// save is written and the backend restarted with them, the run root in force stays, and the answer says,
    /// of the folder chosen, that the run root was not changed and the other settings were saved, with the way
    /// on and no path.
    /// </summary>
    [Theory]
    [MemberData(nameof(FakeRunRootProbe.RefusedKinds), MemberType = typeof(FakeRunRootProbe))]
    public void AFolderChosenForRunsThatTheRuleRefusesIsNotSavedButEveryOtherSettingIs(string kind)
    {
        using (var world = new HostWorld())
        {
            string inForce = world.Settings.RunRoot;
            var refusing = FakeRunRootProbe.Refusing(kind, @"C:\Fictional\elsewhere\runs");
            world.Probe = refusing.Probe;
            world.Open();
            Dictionary<string, object?> payload = Save(effort: "low", apiKey: Key);
            payload["run_root"] = refusing.RunRoot;

            world.Receive("settings.save", "save", payload);

            JsonElement saved = world.Reply("settings.saved", "save");
            JsonElement refusal = saved.GetProperty("run_root_refusal");
            Assert.Equal("RunRootRefused", refusal.GetProperty("error_class").GetString());
            Assert.False(refusal.GetProperty("retryable").GetBoolean());
            Assert.Equal(RunRootRule.ChosenRefusal(refusing.Verdict), refusal.GetProperty("message").GetString());
            Assert.DoesNotContain("elsewhere", refusal.GetProperty("message").GetString()!);
            Assert.Equal(inForce, saved.GetProperty("settings").GetProperty("run_root").GetString());
            SettingsLoadResult file = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Equal("low", file.Settings.Effort);
            Assert.Equal(Key, file.Settings.ResolveApiKey(name => null).Key);
            Assert.Equal(inForce, file.Settings.RunRoot);
            Assert.Equal(inForce, world.Host.RunRoot);
            Assert.Equal(1, world.Backend.Restarts);
            Assert.Equal(inForce, world.Backend.RestartedWith!.RunRoot);
            Assert.Empty(Posted(world, "error"));
        }
    }

    /// <summary>An empty field chooses the default run root, Documents\SwReview\runs, judged as any folder is.</summary>
    [Fact]
    public void AnEmptyFolderForRunsChoosesTheDefault()
    {
        using (var world = new HostWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.Open();
            Dictionary<string, object?> payload = Save();
            payload["run_root"] = "   ";

            world.Receive("settings.save", "save", payload);

            Assert.Equal(
                UserSettings.DefaultRunRoot(),
                world.Reply("settings.saved", "save").GetProperty("settings").GetProperty("run_root").GetString());
            Assert.Equal(UserSettings.DefaultRunRoot(), world.Host.RunRoot);
            Assert.Contains("FinalPathOf " + UserSettings.DefaultRunRoot(), probe.Asked);
        }
    }

    /// <summary>
    /// The run root in force is the one the backend was last started with. A folder chosen for runs is saved
    /// at once, and comes into force only with a restart that succeeds: a save whose restart fails leaves the
    /// run root in force as it was - no backend was started with the folder chosen - and says nothing of the
    /// run root, which the rule accepted; the next save that restarts the backend brings the chosen folder in.
    /// </summary>
    [Fact]
    public void AFolderChosenForRunsComesIntoForceOnlyWithARestartThatSucceeds()
    {
        using (var world = new HostWorld())
        {
            world.Probe = FakeRunRootProbe.Local();
            world.Open();
            string inForce = world.Settings.RunRoot;
            string chosen = Path.Combine(Path.GetDirectoryName(inForce)!, "chosen", "runs");
            Dictionary<string, object?> payload = Save();
            payload["run_root"] = chosen;
            world.Backend.RestartFailure = new InvalidOperationException("FICT the backend did not start");

            world.Receive("settings.save", "fails", payload);

            JsonElement failed = world.Reply("error", "fails");
            Assert.Equal("BackendNotRestarted", failed.GetProperty("error_class").GetString());
            Assert.False(failed.TryGetProperty("run_root_refusal", out _));
            Assert.Equal(chosen, world.Host.Settings.RunRoot);
            Assert.Equal(inForce, world.Host.RunRoot);

            world.Backend.RestartFailure = null;
            world.Receive("settings.save", "restarts", payload);

            world.Reply("settings.saved", "restarts");
            Assert.Equal(chosen, world.Host.RunRoot);
        }
    }

    /// <summary>A run root the rule accepts is saved as before: the rule refuses only what it names.</summary>
    [Fact]
    public void ASaveOfSettingsWhoseRunRootTheRuleAcceptsIsSavedAsBefore()
    {
        using (var world = new HostWorld())
        {
            world.Probe = FakeRunRootProbe.Local();
            world.Open();

            world.Receive("settings.save", "save", Save(effort: "low"));

            Assert.False(world.Reply("settings.saved", "save").TryGetProperty("run_root_refusal", out _));
            Assert.Equal("low", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
            Assert.Equal(1, world.Backend.Restarts);
        }
    }

    /// <summary>
    /// A save whose restart fails is still a save (owner decision 150A), answered `BackendNotRestarted`: with
    /// the run root refused - the folder chosen, or the run root left in force - that answer carries the same
    /// `run_root_refusal` a save's `settings.saved` does, so what the save says of the run root is not lost
    /// with the restart.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ASaveWhoseRestartFailsStillSaysTheRunRootIsRefused(bool chosen)
    {
        using (var world = new HostWorld())
        {
            var refusing = FakeRunRootProbe.Refusing("on a share", @"C:\Fictional\elsewhere\runs");
            world.Probe = refusing.Probe;
            if (!chosen)
            {
                world.Settings.RunRoot = refusing.RunRoot;
            }

            world.Open();
            world.Backend.RestartFailure = new InvalidOperationException("FICT the backend did not start");
            Dictionary<string, object?> payload = Save(effort: "low");
            if (chosen)
            {
                payload["run_root"] = refusing.RunRoot;
            }

            world.Receive("settings.save", "save", payload);

            JsonElement failed = world.Reply("error", "save");
            Assert.Equal("BackendNotRestarted", failed.GetProperty("error_class").GetString());
            Assert.True(failed.GetProperty("retryable").GetBoolean());
            JsonElement refusal = failed.GetProperty("run_root_refusal");
            Assert.Equal("RunRootRefused", refusal.GetProperty("error_class").GetString());
            Assert.False(refusal.GetProperty("retryable").GetBoolean());
            Assert.Equal(
                chosen ? RunRootRule.ChosenRefusal(refusing.Verdict) : RunRootRule.KeptRefusal(refusing.Verdict),
                refusal.GetProperty("message").GetString());
            Assert.Equal("low", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
        }
    }

    /// <summary>
    /// The reviews' finding F7: a folder chosen for runs that is not written as a full path is the one field not
    /// saved - resolved against the current folder, the add-in and the backend can each read it as another
    /// folder, and SOLIDWORKS can move its own - and the answer says so, with the way on and no path. The rule
    /// is not asked about it; every other setting is saved and the run root stands.
    /// </summary>
    [Theory]
    [InlineData("FICT-runs")]
    [InlineData(@"..\FICT-runs")]
    [InlineData(@"\FICT-runs")]
    [InlineData("C:FICT-runs")]
    public void AFolderChosenForRunsThatIsNotAFullPathIsNotSaved(string chosen)
    {
        using (var world = new HostWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.Open();
            string inForce = world.Settings.RunRoot;
            Dictionary<string, object?> payload = Save(effort: "low");
            payload["run_root"] = chosen;

            world.Receive("settings.save", "save", payload);

            JsonElement saved = world.Reply("settings.saved", "save");
            JsonElement refusal = saved.GetProperty("run_root_refusal");
            Assert.Equal("RunRootNotFullPath", refusal.GetProperty("error_class").GetString());
            Assert.False(refusal.GetProperty("retryable").GetBoolean());
            Assert.Equal(RunRootRule.NotFullPathRefusal, refusal.GetProperty("message").GetString());
            Assert.DoesNotContain("FICT-runs", refusal.GetProperty("message").GetString()!);
            Assert.Empty(probe.Normalized);
            Assert.Empty(probe.Asked);
            Assert.Equal(inForce, saved.GetProperty("settings").GetProperty("run_root").GetString());
            SettingsLoadResult file = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Equal("low", file.Settings.Effort);
            Assert.Equal(inForce, file.Settings.RunRoot);
            Assert.Equal(inForce, world.Host.RunRoot);
        }
    }

    /// <summary>
    /// The reviews of 154A's merge, finding F1 (feature 002 T204): a folder chosen for runs with a folder name that
    /// ends in a space or a period - <c>C:\Work \runs</c>, <c>C:\Work..\runs</c> - is read two ways by Windows, and
    /// under SOLIDWORKS' path handling every run would be made under another folder than the backend's run root.
    /// It is the one field not saved: every other setting is written and the backend restarted with them, the run
    /// root in force stays, and the answer says why, with the way on and no path.
    /// </summary>
    [Theory]
    [InlineData("Work ")]
    [InlineData("Work..")]
    [InlineData("runs.")]
    public void AFolderChosenForRunsWithANameEndingInASpaceOrAPeriodIsNotSaved(string name)
    {
        using (var world = new HostWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.Open();
            string inForce = world.Settings.RunRoot;
            string chosen = name == "runs."
                ? Path.Combine(Path.GetDirectoryName(inForce)!, "FICT-chosen", name)
                : Path.Combine(Path.GetDirectoryName(inForce)!, "FICT-chosen", name, "runs");
            Dictionary<string, object?> payload = Save(effort: "low");
            payload["run_root"] = chosen;

            world.Receive("settings.save", "save", payload);

            JsonElement saved = world.Reply("settings.saved", "save");
            JsonElement refusal = saved.GetProperty("run_root_refusal");
            Assert.Equal("RunRootRefused", refusal.GetProperty("error_class").GetString());
            Assert.False(refusal.GetProperty("retryable").GetBoolean());
            Assert.Equal(
                RunRootRule.ChosenRefusal(RunRootVerdict.NameEndsInSpaceOrPeriod),
                refusal.GetProperty("message").GetString());
            Assert.DoesNotContain("FICT-chosen", refusal.GetProperty("message").GetString()!);
            Assert.Empty(probe.Asked);
            SettingsLoadResult file = UserSettings.Load(world.SettingsPath, BuildMode.Development);
            Assert.Equal("low", file.Settings.Effort);
            Assert.Equal(inForce, file.Settings.RunRoot);
            Assert.Equal(inForce, world.Host.RunRoot);
            Assert.Equal(1, world.Backend.Restarts);
            Assert.Equal(inForce, world.Backend.RestartedWith!.RunRoot);
        }
    }

    /// <summary>
    /// The reviews of 154A's merge, finding F2 (feature 002 T204): Windows 11's "Copy as path" (Ctrl+Shift+C) puts
    /// the path in double quotes, and a folder pasted so was called not a full path. One pair around the folder
    /// chosen - after the field is trimmed, and with what they hold trimmed again - is taken off, and the folder is
    /// judged and saved as any other; a pair around nothing chooses the default run root, as an empty field does.
    /// </summary>
    [Theory]
    [InlineData("\"{0}\"")]
    [InlineData("  \"{0}\"  ")]
    [InlineData("\" {0} \"")]
    [InlineData("\"\"")]
    public void AFolderCopiedWithItsQuotesIsSavedWithoutThem(string typed)
    {
        using (var world = new HostWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.Open();
            string chosen = Path.Combine(Path.GetDirectoryName(world.Settings.RunRoot)!, "chosen", "runs");
            string expected = typed == "\"\"" ? UserSettings.DefaultRunRoot() : chosen;
            Dictionary<string, object?> payload = Save(effort: "low");
            payload["run_root"] = string.Format(System.Globalization.CultureInfo.InvariantCulture, typed, chosen);

            world.Receive("settings.save", "save", payload);

            JsonElement saved = world.Reply("settings.saved", "save");
            Assert.False(saved.TryGetProperty("run_root_refusal", out _));
            Assert.Equal(expected, saved.GetProperty("settings").GetProperty("run_root").GetString());
            Assert.Equal(expected, UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.RunRoot);
            Assert.Equal(expected, world.Host.RunRoot);
            Assert.Equal(expected, world.Backend.RestartedWith!.RunRoot);
        }
    }

    /// <summary>
    /// ...but only a pair: a quote before the folder alone is the folder's text, which is not written as a full
    /// path, and is answered so, nothing taken off and the rule not asked.
    /// </summary>
    [Fact]
    public void AFolderWithAQuoteBeforeItAloneIsNotAFullPath()
    {
        using (var world = new HostWorld())
        {
            FakeRunRootProbe probe = FakeRunRootProbe.Local();
            world.Probe = probe;
            world.Open();
            string inForce = world.Settings.RunRoot;
            Dictionary<string, object?> payload = Save(effort: "low");
            payload["run_root"] = "\"" + Path.Combine(Path.GetDirectoryName(inForce)!, "chosen", "runs");

            world.Receive("settings.save", "save", payload);

            JsonElement refusal = world.Reply("settings.saved", "save").GetProperty("run_root_refusal");
            Assert.Equal("RunRootNotFullPath", refusal.GetProperty("error_class").GetString());
            Assert.Empty(probe.Asked);
            Assert.Equal(inForce, world.Host.Settings.RunRoot);
        }
    }

    /// <summary>
    /// ...while a relative run root the settings file already names keeps working as before: a save that sends
    /// it back unchanged writes it again and says nothing of it.
    /// </summary>
    [Fact]
    public void ARelativeRunRootTheSettingsFileNamesKeepsWorking()
    {
        using (var world = new HostWorld())
        {
            world.Settings.RunRoot = "FICT-runs";
            world.Probe = FakeRunRootProbe.Local();
            world.Open();
            Dictionary<string, object?> payload = Save(effort: "low");
            payload["run_root"] = "FICT-runs";

            world.Receive("settings.save", "save", payload);

            Assert.False(world.Reply("settings.saved", "save").TryGetProperty("run_root_refusal", out _));
            Assert.Equal("FICT-runs", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.RunRoot);
            Assert.Equal("low", UserSettings.Load(world.SettingsPath, BuildMode.Development).Settings.Effort);
        }
    }

    private static JsonElement[] Posted(HostWorld world, string type) => world.Posted
        .Select(message => JsonDocument.Parse(message).RootElement)
        .Where(root => root.GetProperty("type").GetString() == type)
        .Select(root => root.GetProperty("payload").Clone())
        .ToArray();

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

        /// <summary>
        /// What the run root rule reads (owner decision 154A); when null, a probe that answers every folder as a
        /// local one reached by its own path - not Windows, so a temp folder below a junction on a developer's
        /// machine fails no test that is not about the rule (the reviews' N11).
        /// </summary>
        public IRunRootProbe? Probe { get; set; }

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
            options.RunRootProbe = Probe ?? FakeRunRootProbe.Local();

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

        /// <summary>What a restart throws, when set: a backend that did not start (owner decision 154A, follow-up).</summary>
        public Exception? RestartFailure { get; set; }

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
            if (RestartFailure != null)
            {
                throw RestartFailure;
            }

            Restarts++;
            RestartedWith = settings;
            RestartedKey = key;
        }
    }
}
