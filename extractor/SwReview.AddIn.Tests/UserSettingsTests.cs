using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T026: the per-user settings store at %APPDATA%\SwReview\settings.json.
///
/// Four things have to hold and none of them can be checked by reading the file inside
/// SOLIDWORKS: the written document satisfies contracts/settings.schema.json, the API key is
/// DPAPI-protected (CurrentUser) rather than stored as text, a missing or damaged file
/// degrades to documented defaults with a visible error instead of throwing into the pane,
/// and the scripted `fake` provider is loadable only in a development build (FR-027).
/// </summary>
public sealed class UserSettingsTests
{
    private const string OpenAiKey = "sk-proj-EXAMPLE/abc+def=0123456789";

    // ---- defaults ---------------------------------------------------------------------

    [Fact]
    public void MissingFileYieldsTheDocumentedDefaults()
    {
        using (var temp = new TempDirectory())
        {
            SettingsLoadResult result = UserSettings.Load(temp.File("settings.json"), BuildMode.Release);

            Assert.Null(result.Error);
            Assert.Equal(1, result.Settings.Version);
            Assert.Equal("openai", result.Settings.Provider);
            Assert.Equal("gpt-5.6", result.Settings.Model);
            Assert.Equal("high", result.Settings.Effort);
            Assert.Equal("codex", result.Settings.TerminalCli);
            Assert.Equal(
                Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                    "SwReview",
                    "runs"),
                result.Settings.RunRoot);
            Assert.Null(result.Settings.ApiKeyProtected);
            Assert.Null(result.Settings.BaseUrl);
            Assert.Null(result.Settings.GeminiEnterprise);
            Assert.Null(result.Settings.Python);
        }
    }

    [Fact]
    public void DefaultsSatisfyTheContract()
    {
        SettingsContract.AssertValid(UserSettings.Defaults().ToJson());
    }

    [Theory]
    [InlineData("openai", "gpt-5.6")]
    [InlineData("gemini", "gemini-3.5-flash")]
    [InlineData("fake", "fake-scripted")]
    public void DefaultModelIsPerProvider(string provider, string model)
    {
        Assert.Equal(model, UserSettings.DefaultModelFor(provider));
    }

    [Fact]
    public void DefaultPathIsUnderApplicationData()
    {
        string expected = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "SwReview",
            "settings.json");

        Assert.Equal(expected, UserSettings.DefaultPath);
    }

    /// <summary>
    /// T076: where the Standards profile is looked for when nobody said. Local rather than
    /// roaming, because the profile describes this workstation's vault paths
    /// (`contracts/profile.md`). The add-in knows this PATH and never the file's schema, which
    /// is what keeps every company value out of this repository (FR-001, FR-002).
    /// </summary>
    [Fact]
    public void TheStandardsProfilePathDefaultsToLocalAppDataAndRoundTripsThroughTheFile()
    {
        using (var temp = new TempDirectory())
        {
            string expected = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "SwReview",
                "standards.yaml");
            Assert.Equal(expected, UserSettings.Defaults().StandardsProfilePath);
            Assert.Equal(expected, UserSettings.DefaultStandardsProfilePath());

            string path = temp.File("settings.json");
            UserSettings saved = UserSettings.Defaults();
            saved.StandardsProfilePath = temp.File("standards.yaml");
            saved.Save(path);

            SettingsContract.AssertValid(File.ReadAllText(path, Encoding.UTF8));
            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.Null(result.Error);
            Assert.Equal(saved.StandardsProfilePath, result.Settings.StandardsProfilePath);
        }
    }

    /// <summary>
    /// A blank path stays blank, unlike `run_root`, which is defaulted past: "no profile is
    /// configured" is a state the Standards tab refuses by name, and this feature has no
    /// fallback values of any kind (`contracts/profile.md`).
    /// </summary>
    [Fact]
    public void ABlankStandardsProfilePathIsLeftBlankRatherThanDefaultedPast()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            UserSettings saved = UserSettings.Defaults();
            saved.StandardsProfilePath = string.Empty;
            saved.Save(path);

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.Null(result.Error);
            Assert.Equal(string.Empty, result.Settings.StandardsProfilePath);
        }
    }

    // ---- round trip -------------------------------------------------------------------

    [Fact]
    public void RoundTripsEveryFieldThroughATempFileAndSatisfiesTheContract()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            UserSettings saved = UserSettings.Defaults();
            saved.Provider = "gemini";
            saved.Model = "gemini-3.5-flash";
            saved.Effort = "xhigh";
            saved.BaseUrl = "https://gateway.example.invalid/v1";
            saved.GeminiEnterprise = new GeminiEnterpriseSettings
            {
                Project = "sw-review-pilot",
                Location = "us-central1",
            };
            saved.TerminalCli = "gemini";
            saved.Python = @"C:\Users\pilot\.local\bin\uv.exe";
            saved.RunRoot = temp.File("runs");
            saved.SetApiKey(OpenAiKey);
            saved.Save(path);

            SettingsContract.AssertValid(File.ReadAllText(path, Encoding.UTF8));

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.Null(result.Error);
            UserSettings loaded = result.Settings;
            Assert.Equal(1, loaded.Version);
            Assert.Equal("gemini", loaded.Provider);
            Assert.Equal("gemini-3.5-flash", loaded.Model);
            Assert.Equal("xhigh", loaded.Effort);
            Assert.Equal("https://gateway.example.invalid/v1", loaded.BaseUrl);
            Assert.NotNull(loaded.GeminiEnterprise);
            Assert.Equal("sw-review-pilot", loaded.GeminiEnterprise!.Project);
            Assert.Equal("us-central1", loaded.GeminiEnterprise.Location);
            Assert.Equal("gemini", loaded.TerminalCli);
            Assert.Equal(@"C:\Users\pilot\.local\bin\uv.exe", loaded.Python);
            Assert.Equal(saved.RunRoot, loaded.RunRoot);
            Assert.Equal(saved.ApiKeyProtected, loaded.ApiKeyProtected);
        }
    }

    [Fact]
    public void SaveCreatesTheDirectoryAndOverwritesAnExistingFile()
    {
        using (var temp = new TempDirectory())
        {
            string path = Path.Combine(temp.Path, "nested", "SwReview", "settings.json");
            UserSettings first = UserSettings.Defaults();
            first.Effort = "low";
            first.Save(path);

            UserSettings second = UserSettings.Defaults();
            second.Effort = "medium";
            second.Save(path);

            Assert.Equal("medium", UserSettings.Load(path, BuildMode.Release).Settings.Effort);
        }
    }

    // ---- the key ----------------------------------------------------------------------

    [Fact]
    public void ApiKeyRoundTripsThroughDpapiAndReportsTheSettingsSource()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.SetApiKey(OpenAiKey);

        ResolvedApiKey resolved = settings.ResolveApiKey(Env());

        Assert.Equal(OpenAiKey, resolved.Key);
        Assert.Equal("settings", resolved.Source);
        Assert.Null(resolved.Error);
    }

    [Fact]
    public void SavedFileNeverContainsTheKeyInTheClear()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            UserSettings settings = UserSettings.Defaults();
            settings.SetApiKey(OpenAiKey);
            settings.Save(path);

            string text = File.ReadAllText(path, Encoding.UTF8);
            Assert.DoesNotContain(OpenAiKey, text, StringComparison.Ordinal);

            // Not merely absent as a literal: the stored blob must not be a reversible
            // encoding of the key either.
            byte[] cipher = Convert.FromBase64String(settings.ApiKeyProtected!);
            Assert.DoesNotContain(
                OpenAiKey,
                Encoding.UTF8.GetString(cipher),
                StringComparison.Ordinal);
        }
    }

    [Fact]
    public void BlankKeyClearsTheStoredCiphertext()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.SetApiKey(OpenAiKey);
        settings.SetApiKey("   ");

        Assert.Null(settings.ApiKeyProtected);
        Assert.Equal("none", settings.ResolveApiKey(Env()).Source);
    }

    [Fact]
    public void TamperedCiphertextIsReportedAndNeverReturnsAKey()
    {
        // Standing in for "the ciphertext was copied out of another Windows user's profile":
        // DPAPI CurrentUser blobs are integrity-protected, so a foreign or an altered blob
        // fails to unprotect the same way, and that path must not throw into the pane.
        UserSettings settings = UserSettings.Defaults();
        settings.SetApiKey(OpenAiKey);
        byte[] cipher = Convert.FromBase64String(settings.ApiKeyProtected!);
        cipher[cipher.Length / 2] ^= 0xFF;
        settings.ApiKeyProtected = Convert.ToBase64String(cipher);

        ResolvedApiKey resolved = settings.ResolveApiKey(Env());

        Assert.Null(resolved.Key);
        Assert.Equal("none", resolved.Source);
        Assert.NotNull(resolved.Error);
        Assert.Contains("key", resolved.Error!, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(OpenAiKey, resolved.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void CiphertextThatIsNotBase64IsReportedRatherThanThrown()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.ApiKeyProtected = "this is not base64 !!!";

        ResolvedApiKey resolved = settings.ResolveApiKey(Env());

        Assert.Null(resolved.Key);
        Assert.Equal("none", resolved.Source);
        Assert.NotNull(resolved.Error);
    }

    [Fact]
    public void AnUnreadableStoredKeyStillFallsBackToTheEnvironment()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.ApiKeyProtected = "this is not base64 !!!";

        ResolvedApiKey resolved = settings.ResolveApiKey(Env("OPENAI_API_KEY", "sk-from-env"));

        Assert.Equal("sk-from-env", resolved.Key);
        Assert.Equal("env", resolved.Source);
        Assert.NotNull(resolved.Error);
    }

    [Fact]
    public void StoredKeyWinsOverTheEnvironment()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.SetApiKey(OpenAiKey);

        ResolvedApiKey resolved = settings.ResolveApiKey(Env("OPENAI_API_KEY", "sk-from-env"));

        Assert.Equal(OpenAiKey, resolved.Key);
        Assert.Equal("settings", resolved.Source);
    }

    [Fact]
    public void EnvironmentKeyIsUsedWhenNoKeyIsStored()
    {
        UserSettings settings = UserSettings.Defaults();

        ResolvedApiKey resolved = settings.ResolveApiKey(Env("OPENAI_API_KEY", "sk-from-env"));

        Assert.Equal("sk-from-env", resolved.Key);
        Assert.Equal("env", resolved.Source);
        Assert.Null(resolved.Error);
    }

    [Fact]
    public void AnEnvironmentVariableThatIsSetButBlankIsNotAKey()
    {
        UserSettings settings = UserSettings.Defaults();

        ResolvedApiKey resolved = settings.ResolveApiKey(Env("OPENAI_API_KEY", "   "));

        Assert.Null(resolved.Key);
        Assert.Equal("none", resolved.Source);
    }

    [Fact]
    public void GeminiPrefersGoogleApiKeyOverGeminiApiKey()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.Provider = "gemini";
        settings.Model = "gemini-3.5-flash";

        var env = new Dictionary<string, string>
        {
            { "GOOGLE_API_KEY", "google-key" },
            { "GEMINI_API_KEY", "gemini-key" },
            { "OPENAI_API_KEY", "sk-wrong-provider" },
        };

        ResolvedApiKey resolved = settings.ResolveApiKey(Env(env));

        Assert.Equal("google-key", resolved.Key);
        Assert.Equal("env", resolved.Source);
    }

    [Fact]
    public void GeminiFallsBackToGeminiApiKey()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.Provider = "gemini";
        settings.Model = "gemini-3.5-flash";

        ResolvedApiKey resolved = settings.ResolveApiKey(Env("GEMINI_API_KEY", "gemini-key"));

        Assert.Equal("gemini-key", resolved.Key);
        Assert.Equal("env", resolved.Source);
    }

    [Fact]
    public void FakeProviderNeedsNoKeySoNoEnvironmentKeyIsAdopted()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.Provider = "fake";
        settings.Model = "fake-scripted";

        ResolvedApiKey resolved = settings.ResolveApiKey(Env("OPENAI_API_KEY", "sk-from-env"));

        Assert.Null(resolved.Key);
        Assert.Equal("none", resolved.Source);
    }

    // ---- the fake provider, FR-027 ----------------------------------------------------

    [Fact]
    public void FakeProviderRoundTripsAndValidatesInADevelopmentBuild()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            UserSettings saved = UserSettings.Defaults();
            saved.Provider = "fake";
            saved.Model = "fake-scripted";
            saved.Save(path);

            SettingsContract.AssertValid(File.ReadAllText(path, Encoding.UTF8));

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Development);

            Assert.Null(result.Error);
            Assert.Equal("fake", result.Settings.Provider);
            Assert.Equal("fake-scripted", result.Settings.Model);
        }
    }

    [Fact]
    public void ReleaseBuildRefusesTheFakeProviderAndFallsBackWithAVisibleError()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            UserSettings saved = UserSettings.Defaults();
            saved.Provider = "fake";
            saved.Model = "fake-scripted";
            saved.Save(path);

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.NotNull(result.Error);
            Assert.Contains("fake", result.Error!, StringComparison.OrdinalIgnoreCase);
            Assert.Contains("openai", result.Error!, StringComparison.OrdinalIgnoreCase);
            Assert.Equal("openai", result.Settings.Provider);
            // The model chosen for the scripted provider is meaningless to OpenAI, so the
            // fallback takes the whole provider default, not just the provider name.
            Assert.Equal("gpt-5.6", result.Settings.Model);
            SettingsContract.AssertValid(result.Settings.ToJson());
        }
    }

    [Fact]
    public void CompileTimeBuildModeMatchesTheBuildConfiguration()
    {
        // The injectable BuildMode above is what the tests drive; this is the proof that the
        // default the shipped add-in uses is decided at compile time (T026).
#if DEBUG
        Assert.Equal(BuildMode.Development, BuildModes.Current);
#else
        Assert.Equal(BuildMode.Release, BuildModes.Current);
#endif
    }

    // ---- damaged files ----------------------------------------------------------------

    [Fact]
    public void MalformedJsonYieldsDefaultsAndAVisibleError()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            File.WriteAllText(path, "{ not json", Encoding.UTF8);

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.NotNull(result.Error);
            Assert.Equal("openai", result.Settings.Provider);
            Assert.Equal("gpt-5.6", result.Settings.Model);
        }
    }

    [Fact]
    public void AnUnsupportedVersionIsRefusedWithAVisibleError()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            string json = UserSettings.Defaults().ToJson().Replace("\"version\": 1", "\"version\": 2");
            SettingsContract.AssertInvalid(json);
            File.WriteAllText(path, json, Encoding.UTF8);

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.NotNull(result.Error);
            Assert.Contains("version", result.Error!, StringComparison.OrdinalIgnoreCase);
            Assert.Equal("openai", result.Settings.Provider);
        }
    }

    [Theory]
    [InlineData("\"provider\": \"openai\"", "\"provider\": \"ollama\"", "provider")]
    [InlineData("\"effort\": \"high\"", "\"effort\": \"maximum\"", "effort")]
    [InlineData("\"terminal_cli\": \"codex\"", "\"terminal_cli\": \"bash\"", "terminal_cli")]
    public void AnUnknownEnumeratedValueFallsBackToTheDefaultWithAVisibleError(
        string original, string replacement, string field)
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            string json = UserSettings.Defaults().ToJson().Replace(original, replacement);
            SettingsContract.AssertInvalid(json);
            File.WriteAllText(path, json, Encoding.UTF8);

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.NotNull(result.Error);
            Assert.Contains(field, result.Error!, StringComparison.OrdinalIgnoreCase);
            SettingsContract.AssertValid(result.Settings.ToJson());
            Assert.Equal("openai", result.Settings.Provider);
            Assert.Equal("high", result.Settings.Effort);
            Assert.Equal("codex", result.Settings.TerminalCli);
        }
    }

    [Fact]
    public void ABlankModelFallsBackToTheProviderDefaultWithAVisibleError()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            UserSettings saved = UserSettings.Defaults();
            saved.Provider = "gemini";
            string json = saved.ToJson().Replace("\"model\": \"gpt-5.6\"", "\"model\": \"\"");
            SettingsContract.AssertInvalid(json);
            File.WriteAllText(path, json, Encoding.UTF8);

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.NotNull(result.Error);
            Assert.Contains("model", result.Error!, StringComparison.OrdinalIgnoreCase);
            Assert.Equal("gemini", result.Settings.Provider);
            Assert.Equal("gemini-3.5-flash", result.Settings.Model);
        }
    }

    [Fact]
    public void EveryProblemInOneFileIsReportedTogether()
    {
        using (var temp = new TempDirectory())
        {
            string path = temp.File("settings.json");
            string json = UserSettings.Defaults().ToJson()
                .Replace("\"effort\": \"high\"", "\"effort\": \"maximum\"")
                .Replace("\"terminal_cli\": \"codex\"", "\"terminal_cli\": \"bash\"");
            File.WriteAllText(path, json, Encoding.UTF8);

            SettingsLoadResult result = UserSettings.Load(path, BuildMode.Release);

            Assert.Contains("effort", result.Error!, StringComparison.OrdinalIgnoreCase);
            Assert.Contains("terminal_cli", result.Error!, StringComparison.OrdinalIgnoreCase);
        }
    }

    // ---- helpers ----------------------------------------------------------------------

    private static Func<string, string?> Env() => _ => null;

    private static Func<string, string?> Env(string name, string value) =>
        Env(new Dictionary<string, string> { { name, value } });

    private static Func<string, string?> Env(IDictionary<string, string> values) =>
        name => values.TryGetValue(name, out string? value) ? value : null;

    private sealed class TempDirectory : IDisposable
    {
        public TempDirectory()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(), "SwReview.Settings.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public string File(string name) => System.IO.Path.Combine(Path, name);

        public void Dispose()
        {
            try
            {
                Directory.Delete(Path, recursive: true);
            }
            catch (IOException)
            {
                // A test that leaves a handle open must not fail the run on cleanup.
            }
        }
    }
}
