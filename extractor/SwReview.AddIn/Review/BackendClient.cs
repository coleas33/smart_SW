using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Text.Json;
using SwReview.AddIn.Native;
using SwReview.AddIn.Settings;

namespace SwReview.AddIn.Review;

/// <summary>
/// The real <see cref="IBackendClient"/>: the child process (through
/// <see cref="BackendSupervisor"/>) and the loopback HTTP calls <see cref="ReviewHost"/> makes
/// against it, behind one seam because they are one thing - `settings.save` writes the file,
/// restarts the child with the new environment, and answers the page.
///
/// Three rules it exists to keep:
///
/// <b>The key travels in the child's environment and nowhere else</b> (FR-015, chat-api.md).
/// It is never an argument, never a file, and it is registered as a secret so the backend log
/// and every start failure are redacted of it.
///
/// <b>The token travels in a header.</b> `Authorization: Bearer ...` on every call, never in a
/// URL: a URL reaches access logs and crash dumps.
///
/// <b>A failure is an answer.</b> Every call maps the backend's `{error_class, message,
/// retryable}` onto <see cref="BackendRequestException"/>, so the page can tell a missing key
/// from a dead backend instead of reading prose.
///
/// `HttpWebRequest` rather than `HttpClient`: it is what <see cref="BackendProcess"/>' health
/// probe already uses, it is synchronous, which is what <see cref="ReviewHost"/> wants on its
/// worker thread, and it can be told not to consult the corporate proxy for 127.0.0.1.
/// </summary>
public sealed class BackendClient : IBackendClient, IDisposable
{
    /// <summary>Long enough for a cold `uv run` model list, short enough to not hang the pane.</summary>
    private static readonly TimeSpan CallTimeout = TimeSpan.FromSeconds(30);

    private readonly BackendSupervisor _supervisor;
    private readonly string _logFolder;
    private readonly JobObject? _job;
    private readonly Func<DateTime> _now;

    /// <summary>
    /// Serializes starting and restarting. The first start runs on a worker thread so the
    /// add-in load is not held up by a cold `uv run`, and `settings.save` can restart from the
    /// page's own thread while that is still in flight; two starts at once would leave two
    /// children, each holding a copy of the key.
    /// </summary>
    private readonly object _gate = new object();

    public BackendClient(BackendSupervisor supervisor, string logFolder, JobObject? job)
        : this(supervisor, logFolder, job, () => DateTime.Now)
    {
    }

    public BackendClient(BackendSupervisor supervisor, string logFolder, JobObject? job, Func<DateTime> now)
    {
        _supervisor = supervisor ?? throw new ArgumentNullException(nameof(supervisor));
        _logFolder = logFolder ?? throw new ArgumentNullException(nameof(logFolder));
        _job = job;
        _now = now ?? throw new ArgumentNullException(nameof(now));
    }

    public BackendEndpoint? Endpoint
    {
        get
        {
            BackendProcess? current = _supervisor.Current;
            return current != null && current.Healthy ? current.Endpoint : null;
        }
    }

    /// <summary>Starts the backend for the first time, after the settings have been loaded.</summary>
    public BackendProcess Start(UserSettings settings, ResolvedApiKey key)
    {
        lock (_gate)
        {
            return _supervisor.Start(StartOptions(settings, key));
        }
    }

    public void Restart(UserSettings settings, ResolvedApiKey key)
    {
        lock (_gate)
        {
            _supervisor.Restart(StartOptions(settings, key));
        }
    }

    public IReadOnlyList<ModelChoice> ListModels(string provider)
    {
        JsonElement body = Call(
            "GET",
            "/models?provider=" + Uri.EscapeDataString(provider ?? string.Empty),
            null);

        var models = new List<ModelChoice>();
        if (body.ValueKind == JsonValueKind.Object
            && body.TryGetProperty("models", out JsonElement listed)
            && listed.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement model in listed.EnumerateArray())
            {
                string? id = Text(model, "id");
                if (!string.IsNullOrEmpty(id))
                {
                    models.Add(new ModelChoice(id!, Text(model, "label") ?? id!));
                }
            }
        }

        return models;
    }

    public bool IsTurnRunning(string chatId)
    {
        JsonElement body = Call("GET", "/sessions/" + Uri.EscapeDataString(chatId ?? string.Empty), null);
        return string.Equals(Text(body, "state"), "running", StringComparison.Ordinal);
    }

    public ChatSessionHandle CreateSession(NewSessionRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        var payload = new Dictionary<string, object?>
        {
            { "run_dir", request.RunDirectory },
            { "provider", request.Provider },
            { "model", request.Model },
            { "effort", request.Effort },
            { "engineer", request.Engineer },
            { "retry_of", request.RetryOf },
            {
                "bridge",
                request.Bridge == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "pipe", request.Bridge.Pipe },
                        { "secret", request.Bridge.Secret },
                    }
            },
        };

        JsonElement body = Call("POST", "/sessions", JsonSerializer.Serialize(payload));
        string? chatId = Text(body, "chat_id");
        if (string.IsNullOrEmpty(chatId))
        {
            throw new BackendRequestException(
                "BadResponse", "the backend created a session without a chat_id.", retryable: false);
        }

        return new ChatSessionHandle(chatId!, Text(body, "review_session_id") ?? string.Empty);
    }

    /// <summary>Stops the child and releases the supervisor. Called on add-in disconnect.</summary>
    public void Dispose()
    {
        lock (_gate)
        {
            _supervisor.Dispose();
        }
    }

    // ---- starting the child -------------------------------------------------------------

    /// <summary>
    /// How the backend is launched for these settings: the resolved launcher, a timestamped
    /// log, the run root it must keep every `run_dir` inside, the page's origin as the only
    /// allowed CORS origin, and the credentials - in the environment, as secrets.
    /// </summary>
    public BackendStartOptions StartOptions(UserSettings settings, ResolvedApiKey key)
    {
        if (settings == null)
        {
            throw new ArgumentNullException(nameof(settings));
        }

        var options = new BackendStartOptions(BackendLocator.Resolve(settings), LogPath())
        {
            RunRoot = settings.RunRoot,
            AllowOrigin = TaskPaneControl.PageOrigin,
            Job = _job,
        };

        if (key != null && !string.IsNullOrEmpty(key.Key))
        {
            foreach (string name in KeyVariablesFor(settings.Provider))
            {
                options.Environment[name] = key.Key!;
            }

            options.Secrets.Add(key.Key!);
        }

        // OPENAI_BASE_URL is the only endpoint override the backend reads, and it reads it for
        // the openai provider only (agent/settings.py `_env_base_url`). Writing it for another
        // provider would be an override the engineer was told was saved and that nothing ever
        // consults; `ReviewHost` refuses such a save, and this is the second half of that rule
        // for a settings file that was edited by hand.
        if (settings.Provider == "openai" && !string.IsNullOrWhiteSpace(settings.BaseUrl))
        {
            options.Environment["OPENAI_BASE_URL"] = settings.BaseUrl!.Trim();
        }

        if (settings.Provider == "gemini")
        {
            WriteGeminiEndpoint(options, settings.GeminiEnterprise);
        }

        return options;
    }

    /// <summary>
    /// Whether this run goes at Vertex, stated either way.
    ///
    /// `GOOGLE_CLOUD_PROJECT` on its own deliberately does not route a review at Vertex:
    /// agent/settings.py `_env_enterprise` ignores it unless the switch is present and on,
    /// because plenty of corporate workstations export a project for unrelated tools. So the
    /// pane has to say `true` when it has been configured for Enterprise - and, just as
    /// importantly, `false` when it has not, because the child inherits SLDWORKS.exe's whole
    /// environment and a switch the workstation exports would otherwise silently outrank the
    /// pane's own answer. The first of `ENTERPRISE_ENV` that is *present* decides on the
    /// Python side, on or off, so writing the new name off is enough to settle it.
    /// </summary>
    private static void WriteGeminiEndpoint(
        BackendStartOptions options, GeminiEnterpriseSettings? enterprise)
    {
        if (enterprise == null)
        {
            options.Environment["GOOGLE_GENAI_USE_ENTERPRISE"] = "false";
            return;
        }

        options.Environment["GOOGLE_GENAI_USE_ENTERPRISE"] = "true";
        options.Environment["GOOGLE_CLOUD_PROJECT"] = enterprise.Project;
        options.Environment["GOOGLE_CLOUD_LOCATION"] = enterprise.Location;
    }

    /// <summary>
    /// The variables the provider reads, *all* of them (chat-api.md). `fake` needs none, which
    /// is why a development run with no key still starts.
    ///
    /// Gemini gets both names, and that is the point rather than belt and braces: the child
    /// inherits the parent's environment, and the backend resolves `GOOGLE_API_KEY` ahead of
    /// `GEMINI_API_KEY` - the precedence google.genai applies itself, mirrored in
    /// <see cref="UserSettings.ResolveApiKey(Func{string, string})"/>. Writing only
    /// `GEMINI_API_KEY` would let a workstation's personal `GOOGLE_API_KEY` win while the pane
    /// reported `key_source` "settings", which is a run that cannot say which credential it
    /// used (FR-015).
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

    private string LogPath() => Path.Combine(
        _logFolder,
        "backend-" + _now().ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".log");

    // ---- one HTTP call --------------------------------------------------------------------

    private JsonElement Call(string method, string path, string? body)
    {
        BackendEndpoint? endpoint = Endpoint;
        if (endpoint == null)
        {
            throw new BackendRequestException(
                "BackendUnavailable", "the review backend is not running.", retryable: true);
        }

        var request = (HttpWebRequest)WebRequest.Create(endpoint.Origin + path);
        request.Method = method;
        request.Timeout = (int)CallTimeout.TotalMilliseconds;
        request.ReadWriteTimeout = (int)CallTimeout.TotalMilliseconds;
        // Never ask a corporate proxy about 127.0.0.1: it cannot help and it costs seconds.
        request.Proxy = null;
        request.Headers["Authorization"] = "Bearer " + endpoint.Token;
        request.Accept = "application/json";

        if (body != null)
        {
            byte[] payload = Encoding.UTF8.GetBytes(body);
            request.ContentType = "application/json";
            request.ContentLength = payload.Length;
            using (Stream stream = request.GetRequestStream())
            {
                stream.Write(payload, 0, payload.Length);
            }
        }

        try
        {
            using (var response = (HttpWebResponse)request.GetResponse())
            {
                return Parse(Read(response));
            }
        }
        catch (WebException failure)
        {
            throw Failed(failure);
        }
    }

    /// <summary>The backend's own error class and message, or the transport's.</summary>
    private static BackendRequestException Failed(WebException failure)
    {
        var response = failure.Response as HttpWebResponse;
        if (response == null)
        {
            return new BackendRequestException(
                "BackendUnavailable",
                "the review backend did not answer: " + failure.Message,
                retryable: true,
                failure);
        }

        using (response)
        {
            string text = Read(response);
            JsonElement body;
            try
            {
                body = Parse(text);
            }
            catch (BackendRequestException)
            {
                return new BackendRequestException(
                    "HttpError",
                    $"the backend answered {(int)response.StatusCode}.",
                    retryable: (int)response.StatusCode >= 500,
                    failure);
            }

            return new BackendRequestException(
                Text(body, "error_class") ?? "HttpError",
                Text(body, "message") ?? $"the backend answered {(int)response.StatusCode}.",
                Flag(body, "retryable"),
                failure);
        }
    }

    private static string Read(HttpWebResponse response)
    {
        using (Stream stream = response.GetResponseStream())
        {
            if (stream == null)
            {
                return string.Empty;
            }

            using (var reader = new StreamReader(stream, Encoding.UTF8))
            {
                return reader.ReadToEnd();
            }
        }
    }

    private static JsonElement Parse(string text)
    {
        try
        {
            using (JsonDocument document = JsonDocument.Parse(string.IsNullOrEmpty(text) ? "{}" : text))
            {
                return document.RootElement.Clone();
            }
        }
        catch (JsonException failure)
        {
            throw new BackendRequestException(
                "BadResponse", "the backend's answer was not JSON.", retryable: false, failure);
        }
    }

    private static string? Text(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty(name, out JsonElement value)
            && value.ValueKind == JsonValueKind.String
                ? value.GetString()
                : null;

    private static bool Flag(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty(name, out JsonElement value)
            && value.ValueKind == JsonValueKind.True;
}
