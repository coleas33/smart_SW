using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Text.Json;
using SwReview.AddIn.Review;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// The real <see cref="IRemodelBackend"/>: nine loopback calls against the backend the Review
/// tab already started.
///
/// The conventions are <see cref="BackendClient"/>'s, member for member, and that is the point
/// rather than an accident: <b>the token travels in an `Authorization: Bearer` header</b> and
/// never in a URL, which reaches access logs and crash dumps; <b>the bridge secret travels in
/// the body</b>, for the same reason and because it authorizes every write the run makes to the
/// copy; <b>a failure is an answer</b>, mapped onto <see cref="BackendRequestException"/> with
/// the backend's own `error_class`, so the pane can tell a weldment from a dead backend instead
/// of reading prose; and <b>the proxy is never consulted for 127.0.0.1</b>, which cannot help
/// and costs seconds on a corporate workstation.
///
/// <see cref="HttpWebRequest"/> rather than <see cref="System.Net.Http.HttpClient"/>, again for
/// <see cref="BackendClient"/>'s reasons: it is synchronous, which is what the pipeline wants on
/// its worker thread, and it can be told to ignore the proxy.
///
/// The endpoint is asked for fresh on every call. `settings.save` restarts the child on a new
/// port, and a run that had captured the old one would talk to a backend that is gone.
/// </summary>
public sealed class RemodelBackendClient : IRemodelBackend
{
    /// <summary>
    /// <see cref="BackendClient"/>'s timeout. The routes here are quick by construction - the
    /// run itself is a job the backend owns and this client polls - so a call that takes longer
    /// than this is a backend that has stopped answering, not a long computation.
    /// </summary>
    private static readonly TimeSpan CallTimeout = TimeSpan.FromSeconds(30);

    private readonly Func<BackendEndpoint?> _endpoint;

    public RemodelBackendClient(Func<BackendEndpoint?> endpoint)
    {
        _endpoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
    }

    public RemodelProbeReply Probe(RemodelProbeRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        JsonElement body = Call("POST", "/remodel/probe", JsonSerializer.Serialize(
            new Dictionary<string, object?>
            {
                { "source_path", request.SourcePath },
                { "configuration", request.Configuration },
                { "bridge", Bridge(request.Bridge) },
            }));

        return new RemodelProbeReply(Text(body, "probe_id") ?? string.Empty, Signals(body), Refusals(body));
    }

    public RemodelOpenReply Open(RemodelOpenRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        JsonElement body = Call("POST", "/remodel/open", JsonSerializer.Serialize(
            new Dictionary<string, object?>
            {
                { "run_dir", request.RunDirectory },
                { "source_path", request.SourcePath },
                { "configuration", request.Configuration },
                { "probe_id", request.ProbeId },
                { "bridge", Bridge(request.Bridge) },
            }));

        string? copyPath = Text(body, "copy_path");
        if (string.IsNullOrEmpty(copyPath))
        {
            // Without the path there is nothing to close, nothing to activate and nothing to
            // delete; an empty string here would be a run folder root passed to a delete.
            throw new BackendRequestException(
                "BadResponse", "the backend opened a copy without saying where it is.", retryable: false);
        }

        return new RemodelOpenReply(copyPath!, Count(body, "rebuild_error_count"), Flag(body, "copy_present"));
    }

    public string Plan(string runDirectory)
    {
        JsonElement body = Call("POST", "/remodel/plan", JsonSerializer.Serialize(
            new Dictionary<string, object?> { { "run_dir", runDirectory } }));

        if (body.ValueKind != JsonValueKind.Object
            || !body.TryGetProperty("plan_summary", out JsonElement summary))
        {
            throw new BackendRequestException(
                "BadResponse", "the backend planned the run without returning a plan summary.",
                retryable: false);
        }

        // Raw: the host parses it once to embed it and the page renders it. Nothing in the
        // add-in reads a field of it, so nothing in the add-in can reshape it.
        return summary.GetRawText();
    }

    public string StartRun(RemodelRunRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        JsonElement body = Call("POST", "/remodel/runs", JsonSerializer.Serialize(
            new Dictionary<string, object?>
            {
                { "run_dir", request.RunDirectory },
                { "bridge", Bridge(request.Bridge) },
            }));

        string? jobId = Text(body, "job_id");
        if (string.IsNullOrEmpty(jobId))
        {
            throw new BackendRequestException(
                "BadResponse", "the backend started a remodel run without a job_id.", retryable: false);
        }

        return jobId!;
    }

    public RemodelRunStatus Status(string jobId)
    {
        JsonElement body = Call("GET", "/remodel/runs/" + Escape(jobId), null);

        RemodelRunCurrent? current = null;
        if (body.ValueKind == JsonValueKind.Object
            && body.TryGetProperty("current", out JsonElement change)
            && change.ValueKind == JsonValueKind.Object)
        {
            current = new RemodelRunCurrent(
                Count(change, "seq") ?? 0, Text(change, "kind") ?? string.Empty, Text(change, "subject_name"));
        }

        return new RemodelRunStatus(
            Text(body, "state") ?? string.Empty,
            Text(body, "plan_state"),
            Count(body, "changes_total") ?? 0,
            Count(body, "changes_applied") ?? 0,
            current,
            Text(body, "awaiting"),
            Text(body, "error"));
    }

    public RemodelEventPage Events(string jobId, int after)
    {
        JsonElement body = Call(
            "GET",
            "/remodel/runs/" + Escape(jobId) + "/events?after="
                + after.ToString(CultureInfo.InvariantCulture),
            null);

        var events = new List<string>();
        if (body.ValueKind == JsonValueKind.Object
            && body.TryGetProperty("events", out JsonElement listed)
            && listed.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement recorded in listed.EnumerateArray())
            {
                events.Add(recorded.GetRawText());
            }
        }

        return new RemodelEventPage(events, Count(body, "next") ?? after);
    }

    public void PackageAfter(string jobId, string packagePath)
    {
        Call(
            "POST",
            "/remodel/runs/" + Escape(jobId) + "/package-after",
            JsonSerializer.Serialize(new Dictionary<string, object?> { { "path", packagePath } }));
    }

    public void Stop(string jobId)
    {
        Call("POST", "/remodel/runs/" + Escape(jobId) + "/stop", "{}");
    }

    public void Close(RemodelCloseRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        Call("POST", "/remodel/close", JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "run_dir", request.RunDirectory },
            { "bridge", Bridge(request.Bridge) },
            { "discard_copy", request.DiscardCopy },
        }));
    }

    // ---- the reply ------------------------------------------------------------------------

    /// <summary>
    /// The signals, through the bridge's own serializer options, so the spellings here are the
    /// spellings `remodel.probe_scope` wrote. An absent object is <b>every signal unknown</b>,
    /// which the pure gate refuses; it is never a pass (data-model.md 4.1).
    /// </summary>
    private static ScopeSignals Signals(JsonElement body)
    {
        if (body.ValueKind != JsonValueKind.Object
            || !body.TryGetProperty("signals", out JsonElement signals)
            || signals.ValueKind != JsonValueKind.Object)
        {
            return new ScopeSignals();
        }

        try
        {
            return JsonSerializer.Deserialize<ScopeSignals>(signals.GetRawText(), BridgeCodec.Options)
                ?? new ScopeSignals();
        }
        catch (JsonException failure)
        {
            throw new BackendRequestException(
                "BadResponse",
                "the backend's scope signals did not read as signals: " + failure.Message,
                retryable: false,
                failure);
        }
    }

    private static IReadOnlyList<string> Refusals(JsonElement body)
    {
        var refusals = new List<string>();
        if (body.ValueKind == JsonValueKind.Object
            && body.TryGetProperty("refusals", out JsonElement listed)
            && listed.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement sentence in listed.EnumerateArray())
            {
                if (sentence.ValueKind == JsonValueKind.String)
                {
                    refusals.Add(sentence.GetString()!);
                }
            }
        }

        return refusals;
    }

    private static Dictionary<string, object?> Bridge(BridgeConfig bridge) =>
        new Dictionary<string, object?>
        {
            { "pipe", bridge.Pipe },
            { "secret", bridge.Secret },
        };

    private static string Escape(string? value) => Uri.EscapeDataString(value ?? string.Empty);

    // ---- one HTTP call ----------------------------------------------------------------------

    private JsonElement Call(string method, string path, string? body)
    {
        BackendEndpoint? endpoint = _endpoint();
        if (endpoint == null)
        {
            throw new BackendRequestException(
                "BackendUnavailable", "the review backend is not running.", retryable: true);
        }

        var request = (HttpWebRequest)WebRequest.Create(endpoint.Origin + path);
        request.Method = method;
        request.Timeout = (int)CallTimeout.TotalMilliseconds;
        request.ReadWriteTimeout = (int)CallTimeout.TotalMilliseconds;
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

    /// <summary>A number member, or <b>null</b> for one that is absent or JSON null.</summary>
    private static int? Count(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty(name, out JsonElement value)
            && value.ValueKind == JsonValueKind.Number
            && value.TryGetInt32(out int number)
                ? number
                : (int?)null;

    private static bool Flag(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty(name, out JsonElement value)
            && value.ValueKind == JsonValueKind.True;
}
