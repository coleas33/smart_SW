using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SwReview.AddIn.Settings;

/// <summary>Which build the add-in is: the scripted `fake` provider exists only in the first.</summary>
public enum BuildMode
{
    /// <summary>A development build: the scripted `fake` provider is selectable and loadable.</summary>
    Development,

    /// <summary>A shipped build: a settings file naming `fake` is refused (FR-027).</summary>
    Release,
}

/// <summary>
/// The compile-time build mode. <see cref="UserSettings.Load(string, BuildMode)"/> takes the
/// mode as an argument so both paths are testable from one build, and this is the value the
/// add-in passes when it does not care to say: a shipped assembly is compiled without DEBUG
/// and can therefore never load a settings file naming the scripted provider.
/// </summary>
public static class BuildModes
{
#if DEBUG
    public static readonly BuildMode Current = BuildMode.Development;
#else
    public static readonly BuildMode Current = BuildMode.Release;
#endif
}

/// <summary>The Google Cloud project and location a Gemini Enterprise client is bound to.</summary>
public sealed class GeminiEnterpriseSettings
{
    [JsonPropertyName("project")]
    public string Project { get; set; } = string.Empty;

    [JsonPropertyName("location")]
    public string Location { get; set; } = string.Empty;
}

/// <summary>What <see cref="UserSettings.Load(string, BuildMode)"/> produced, and what was wrong.</summary>
public sealed class SettingsLoadResult
{
    internal SettingsLoadResult(UserSettings settings, string? error)
    {
        Settings = settings;
        Error = error;
    }

    /// <summary>Always usable: defaults stand in for anything the file could not supply.</summary>
    public UserSettings Settings { get; }

    /// <summary>Every problem found, joined; null when the file loaded cleanly. Show it.</summary>
    public string? Error { get; }
}

/// <summary>The API key for a run, where it came from, and why it could not be read.</summary>
public sealed class ResolvedApiKey
{
    internal ResolvedApiKey(string? key, string source, string? error)
    {
        Key = key;
        Source = source;
        Error = error;
    }

    /// <summary>The key, or null when there is none. Never log this; see <see cref="Redaction"/>.</summary>
    public string? Key { get; }

    /// <summary>`settings`, `env` or `none` - the `key_source` the session records (FR-015).</summary>
    public string Source { get; }

    /// <summary>Set when a stored key exists but could not be decrypted on this account.</summary>
    public string? Error { get; }
}

/// <summary>
/// %APPDATA%\SwReview\settings.json - the per-Windows-user provider settings, whose shape is
/// specs/002-task-pane-assistant/contracts/settings.schema.json.
///
/// Three rules shape this class:
///
/// <b>The key is never text.</b> It is stored as a DPAPI CurrentUser blob, base64 in the file
/// (research R8), and travels from here into the backend child process's environment block and
/// nowhere else. A blob written by another Windows account, or one that was altered, fails to
/// unprotect; that is reported as an error the engineer can act on rather than thrown at a pane
/// that is mid-render.
///
/// <b>A damaged file degrades, it does not fail.</b> The file is hand-editable and lives in a
/// roaming profile, so Load treats every field as suspect: an unknown provider, effort or
/// terminal CLI falls back to the documented default and every problem is reported together, so
/// one bad character cannot leave the pane with no settings at all.
///
/// <b>The scripted provider is a development-build affordance (FR-027).</b> `fake` fabricates
/// findings. It round-trips in a development build so the pane is demonstrable without keys; a
/// release build refuses it and falls back to the default provider with a visible error.
/// </summary>
public sealed class UserSettings
{
    /// <summary>The only settings version this add-in understands.</summary>
    public const int CurrentVersion = 1;

    private const string DefaultProvider = "openai";
    private const string DefaultEffort = "high";
    private const string DefaultTerminalCli = "codex";

    private static readonly IReadOnlyList<string> Providers = new[] { "openai", "gemini", "fake" };
    private static readonly IReadOnlyList<string> Efforts = new[] { "low", "medium", "high", "xhigh" };
    private static readonly IReadOnlyList<string> TerminalClis = new[] { "codex", "gemini" };

    /// <summary>Application-specific DPAPI entropy: a blob from another application's store,
    /// even under the same Windows account, is not ours to decrypt.</summary>
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("SwReview.Settings.v1");

    private static readonly UTF8Encoding Utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        // The file is hand-editable; a trailing comma or a comment is not a reason to lose
        // someone's settings.
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    [JsonPropertyName("version")]
    public int Version { get; set; } = CurrentVersion;

    [JsonPropertyName("provider")]
    public string Provider { get; set; } = DefaultProvider;

    [JsonPropertyName("model")]
    public string Model { get; set; } = DefaultModelFor(DefaultProvider);

    [JsonPropertyName("effort")]
    public string Effort { get; set; } = DefaultEffort;

    /// <summary>Base64 DPAPI ciphertext; null when no key is stored. Set it with
    /// <see cref="SetApiKey"/>, read it with <see cref="ResolveApiKey()"/>.</summary>
    [JsonPropertyName("api_key_protected")]
    public string? ApiKeyProtected { get; set; }

    [JsonPropertyName("base_url")]
    public string? BaseUrl { get; set; }

    [JsonPropertyName("gemini_enterprise")]
    public GeminiEnterpriseSettings? GeminiEnterprise { get; set; }

    [JsonPropertyName("terminal_cli")]
    public string TerminalCli { get; set; } = DefaultTerminalCli;

    [JsonPropertyName("python")]
    public string? Python { get; set; }

    [JsonPropertyName("run_root")]
    public string RunRoot { get; set; } = DefaultRunRoot();

    /// <summary>
    /// Where the Standards profile is, `%LOCALAPPDATA%\SwReview\standards.yaml` by default
    /// (`contracts/profile.md`). The file itself is never committed and is never read here:
    /// the add-in knows the path and the reasoning side owns the schema, which is what keeps
    /// every company value out of this repository (FR-001, FR-002).
    ///
    /// A blank value is left blank rather than defaulted past, unlike <see cref="RunRoot"/>:
    /// "no profile is configured" is a state the Standards tab refuses by name, and this
    /// feature has no fallback values of any kind.
    /// </summary>
    [JsonPropertyName("standards_profile_path")]
    public string StandardsProfilePath { get; set; } = DefaultStandardsProfilePath();

    /// <summary>%APPDATA%\SwReview\settings.json.</summary>
    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "SwReview", "settings.json");

    /// <summary>A settings object with every documented default and no key.</summary>
    public static UserSettings Defaults() => new UserSettings();

    /// <summary>
    /// The model a provider runs when nobody chose one. These are the values
    /// reviewer/src/swreview/agent/settings.py DEFAULT_MODELS carries; the two lists are
    /// deliberately short and are asserted on both sides, because the pane writes the model id
    /// the backend then runs with.
    /// </summary>
    public static string DefaultModelFor(string provider)
    {
        switch (provider)
        {
            case "openai":
                return "gpt-5.6";
            case "gemini":
                return "gemini-3.5-flash";
            case "fake":
                return "fake-scripted";
            default:
                throw new ArgumentOutOfRangeException(
                    nameof(provider), provider, "provider must be openai, gemini or fake");
        }
    }

    /// <summary>Loads the settings file, using the compile-time build mode.</summary>
    public static SettingsLoadResult Load(string path) => Load(path, BuildModes.Current);

    /// <summary>
    /// Loads the settings file. A missing file is not an error - it is a first run, and the
    /// defaults are the answer. Anything else that is wrong is reported and defaulted past, so
    /// the caller always gets usable settings.
    /// </summary>
    public static SettingsLoadResult Load(string path, BuildMode mode)
    {
        if (path == null)
        {
            throw new ArgumentNullException(nameof(path));
        }

        if (!File.Exists(path))
        {
            return new SettingsLoadResult(Defaults(), null);
        }

        UserSettings? parsed;
        try
        {
            parsed = JsonSerializer.Deserialize<UserSettings>(File.ReadAllText(path, Encoding.UTF8), JsonOptions);
        }
        catch (Exception failure)
            when (failure is IOException || failure is UnauthorizedAccessException || failure is JsonException)
        {
            return new SettingsLoadResult(
                Defaults(),
                $"{path} could not be read ({failure.Message.Trim()}); the default settings are in use.");
        }

        if (parsed == null)
        {
            return new SettingsLoadResult(Defaults(), $"{path} is empty; the default settings are in use.");
        }

        if (parsed.Version != CurrentVersion)
        {
            return new SettingsLoadResult(
                Defaults(),
                $"{path} has version {parsed.Version}; this add-in reads version {CurrentVersion} only, "
                + "so the default settings are in use.");
        }

        var problems = new List<string>();
        parsed.Normalize(mode, problems);
        return new SettingsLoadResult(parsed, problems.Count == 0 ? null : string.Join(" ", problems));
    }

    /// <summary>
    /// Writes the settings to <paramref name="path"/>, creating the folder. The write goes to a
    /// temporary file first: a crash part way through a direct write would leave a truncated
    /// file, and the stored key with it.
    /// </summary>
    public void Save(string path)
    {
        if (path == null)
        {
            throw new ArgumentNullException(nameof(path));
        }

        string? directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory!);
        }

        string temporary = path + ".tmp";
        File.WriteAllText(temporary, ToJson(), Utf8NoBom);
        if (File.Exists(path))
        {
            File.Replace(temporary, path, destinationBackupFileName: null);
        }
        else
        {
            File.Move(temporary, path);
        }
    }

    /// <summary>The settings as the contract's JSON document.</summary>
    public string ToJson() => JsonSerializer.Serialize(this, JsonOptions);

    /// <summary>
    /// Stores <paramref name="key"/> DPAPI-protected for the current Windows user. A null or
    /// blank key clears the stored one - that is how the Settings UI removes a key.
    /// </summary>
    public void SetApiKey(string? key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            ApiKeyProtected = null;
            return;
        }

        byte[] plain = Encoding.UTF8.GetBytes(key!.Trim());
        ApiKeyProtected = Convert.ToBase64String(
            ProtectedData.Protect(plain, Entropy, DataProtectionScope.CurrentUser));
        Array.Clear(plain, 0, plain.Length);
    }

    /// <summary>The key for this run, read from the settings file then the process environment.</summary>
    public ResolvedApiKey ResolveApiKey() => ResolveApiKey(Environment.GetEnvironmentVariable);

    /// <summary>
    /// The key for this run and where it came from.
    ///
    /// Settings beat the environment, and the answer is recorded as `key_source`, for the reason
    /// the Python side states: a workstation that exports a personal key must not quietly
    /// override the key the engineer entered in the pane, and a run that cannot say which
    /// credential it used cannot be reproduced or revoked.
    /// </summary>
    /// <param name="environment">Reads one environment variable; injected so a test never has
    /// to mutate the process environment.</param>
    public ResolvedApiKey ResolveApiKey(Func<string, string?> environment)
    {
        if (environment == null)
        {
            throw new ArgumentNullException(nameof(environment));
        }

        string? error = null;
        if (!string.IsNullOrWhiteSpace(ApiKeyProtected))
        {
            try
            {
                byte[] cipher = Convert.FromBase64String(ApiKeyProtected!);
                byte[] plain = ProtectedData.Unprotect(cipher, Entropy, DataProtectionScope.CurrentUser);
                string key = Encoding.UTF8.GetString(plain);
                Array.Clear(plain, 0, plain.Length);
                return new ResolvedApiKey(key, "settings", null);
            }
            catch (Exception failure) when (failure is FormatException || failure is CryptographicException)
            {
                // A DPAPI CurrentUser blob saved by another Windows account, or one that was
                // altered, fails exactly here. The message names the cause and never the key.
                error = "The stored API key could not be decrypted on this Windows account - it was "
                    + "saved by a different user or the settings file was altered. Enter the key "
                    + $"again in the pane's Settings section ({failure.GetType().Name}).";
            }
        }

        foreach (string name in KeyVariablesFor(Provider))
        {
            string? value = environment(name);
            if (!string.IsNullOrWhiteSpace(value))
            {
                return new ResolvedApiKey(value!.Trim(), "env", error);
            }
        }

        return new ResolvedApiKey(null, "none", error);
    }

    /// <summary>
    /// The key variables for a provider, in precedence order. GOOGLE_API_KEY ahead of
    /// GEMINI_API_KEY is the order google.genai applies itself; `fake` needs no key.
    /// </summary>
    private static IEnumerable<string> KeyVariablesFor(string provider)
    {
        if (provider == "openai")
        {
            yield return "OPENAI_API_KEY";
        }
        else if (provider == "gemini")
        {
            yield return "GOOGLE_API_KEY";
            yield return "GEMINI_API_KEY";
        }
    }

    /// <summary>
    /// %USERPROFILE%\Documents\SwReview\runs. MyDocuments rather than a literal Documents path
    /// so a redirected Documents folder is honoured.
    /// </summary>
    private static string DefaultRunRoot() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "SwReview", "runs");

    /// <summary>
    /// %LOCALAPPDATA%\SwReview\standards.yaml. Local rather than roaming, beside the logs: the
    /// profile describes this workstation's vault paths, and a roaming copy would follow the
    /// engineer to a machine where those paths mean something else.
    /// </summary>
    public static string DefaultStandardsProfilePath() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "SwReview",
        "standards.yaml");

    /// <summary>
    /// Replaces every field the contract cannot accept with its default, collecting one message
    /// per problem so the pane can show all of them at once.
    /// </summary>
    private void Normalize(BuildMode mode, ICollection<string> problems)
    {
        if (!Providers.Contains(Provider))
        {
            problems.Add(
                $"provider '{Provider}' is not one of {string.Join(", ", Providers)}; "
                + $"'{DefaultProvider}' is in use.");
            FallBackToDefaultProvider();
        }
        else if (Provider == "fake" && mode == BuildMode.Release)
        {
            problems.Add(
                "provider 'fake' is the scripted development provider and this is a release "
                + $"build, which cannot produce real findings with it; '{DefaultProvider}' is in use.");
            FallBackToDefaultProvider();
        }

        if (string.IsNullOrWhiteSpace(Model))
        {
            problems.Add($"model was blank; the default model for '{Provider}' is in use.");
            Model = DefaultModelFor(Provider);
        }

        if (!Efforts.Contains(Effort))
        {
            problems.Add(
                $"effort '{Effort}' is not one of {string.Join(", ", Efforts)}; '{DefaultEffort}' is in use.");
            Effort = DefaultEffort;
        }

        if (!TerminalClis.Contains(TerminalCli))
        {
            problems.Add(
                $"terminal_cli '{TerminalCli}' is not one of {string.Join(", ", TerminalClis)}; "
                + $"'{DefaultTerminalCli}' is in use.");
            TerminalCli = DefaultTerminalCli;
        }

        if (string.IsNullOrWhiteSpace(RunRoot))
        {
            problems.Add("run_root was blank; the default run folder is in use.");
            RunRoot = DefaultRunRoot();
        }
    }

    /// <summary>The model chosen for the refused provider means nothing to the default one, so
    /// the fallback takes the whole provider default, not just its name.</summary>
    private void FallBackToDefaultProvider()
    {
        Provider = DefaultProvider;
        Model = DefaultModelFor(DefaultProvider);
    }
}
