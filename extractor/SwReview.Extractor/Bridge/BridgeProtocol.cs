using System;
using System.Text.Json;
using System.Text.Json.Serialization;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Bridge;

/// <summary>
/// The four commands the bridge answers (contracts/cli.md, contracts/agent-tools.md).
/// Anything else is an error response naming these, never a silent no-op.
/// </summary>
public static class BridgeCommands
{
    public const string Ping = "ping";
    public const string Capture = "capture";
    public const string Measure = "measure";
    public const string Interference = "interference";

    /// <summary>For the "unknown command" message and for SwReview.Extractor.Console/Serve/PROTOCOL.md.</summary>
    public static readonly string[] All = { Ping, Capture, Measure, Interference };
}

/// <summary>The <c>status</c> of a response.</summary>
public static class BridgeStatus
{
    /// <summary>The command ran and <c>result</c> holds its answer.</summary>
    public const string Ok = "ok";

    /// <summary>The command did not run, or ran and failed; <c>error</c> says why.</summary>
    public const string Error = "error";

    /// <summary>
    /// SOLIDWORKS has failed three times in a row and the circuit breaker is open
    /// (research R4). The reviewer turns this into failed coverage, never a pass.
    /// </summary>
    public const string CircuitOpen = "circuit_open";
}

/// <summary>One request line: <c>{"id", "command", "params"}</c>.</summary>
public sealed class BridgeRequest
{
    /// <summary>Echoed back on the response so a client can match them up.</summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>One of <see cref="BridgeCommands"/>.</summary>
    [JsonPropertyName("command")]
    public string Command { get; set; } = string.Empty;

    /// <summary>
    /// Command arguments, read per command. Left as a <see cref="JsonElement"/> rather than
    /// a typed union so one bad argument fails that command with a message instead of
    /// failing to parse the line at all.
    /// </summary>
    [JsonPropertyName("params")]
    public JsonElement Params { get; set; }

    /// <summary>
    /// T045. The per-launch secret, and which scope of commands it authorizes.
    ///
    /// Optional on the wire, because the two hosts differ: the console host issues no
    /// secret and its <see cref="ISecretPolicy"/> ignores this field, while the add-in's
    /// in-process host requires one on every line. That is why the protocol version stays
    /// 1.0 - a client that omits the field still works against the console host, and
    /// simply gets <c>unauthorized</c> from the in-process one.
    ///
    /// Never written back on a response and never logged: see
    /// <see cref="BridgeResponse"/>, which has no such field.
    /// </summary>
    [JsonPropertyName("secret")]
    public string? Secret { get; set; }
}

/// <summary>One response line: <c>{"id", "status", "result", "error", "elapsed_ms"}</c>.</summary>
public sealed class BridgeResponse
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>One of <see cref="BridgeStatus"/>.</summary>
    [JsonPropertyName("status")]
    public string Status { get; set; } = BridgeStatus.Ok;

    /// <summary>The command's answer, or null on any non-ok status.</summary>
    [JsonPropertyName("result")]
    public object? Result { get; set; }

    /// <summary>A sentence an engineer can read, or null when the status is ok.</summary>
    [JsonPropertyName("error")]
    public string? Error { get; set; }

    /// <summary>Wall-clock milliseconds the worker thread spent on the command.</summary>
    [JsonPropertyName("elapsed_ms")]
    public long ElapsedMs { get; set; }

    public static BridgeResponse Ok(string id, object? result) =>
        new BridgeResponse { Id = id, Status = BridgeStatus.Ok, Result = result, Error = null };

    public static BridgeResponse Failed(string id, string error, object? result = null) =>
        new BridgeResponse { Id = id, Status = BridgeStatus.Error, Result = result, Error = error };

    public static BridgeResponse CircuitOpen(string id, string error) =>
        new BridgeResponse { Id = id, Status = BridgeStatus.CircuitOpen, Result = null, Error = error };
}

/// <summary>Raised when a request line is not a request. The server answers, then continues.</summary>
[Serializable]
public class BridgeProtocolError : Exception
{
    public BridgeProtocolError(string message)
        : base(message)
    {
    }

    public BridgeProtocolError(string message, Exception inner)
        : base(message, inner)
    {
    }
}

/// <summary>
/// One JSON object per line, UTF-8 (research R3). The codec is separate from the pipe and
/// from the dispatcher so the framing is unit tested on its own.
///
/// The serializer options are the IR's, with indentation off: an indented response would
/// span several lines and break the framing outright. Enum values therefore come out as the
/// same schema strings <c>package.json</c> uses, so an <c>Interference</c> that travels
/// over the bridge is byte-identical to one that was dumped to a file.
/// </summary>
public static class BridgeCodec
{
    public static readonly JsonSerializerOptions Options = CreateOptions();

    /// <summary>Parses one line. Throws <see cref="BridgeProtocolError"/> for anything else.</summary>
    public static BridgeRequest ReadRequest(string line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            throw new BridgeProtocolError("Empty request line.");
        }

        BridgeRequest? request;
        try
        {
            request = JsonSerializer.Deserialize<BridgeRequest>(line, Options);
        }
        catch (JsonException error)
        {
            throw new BridgeProtocolError(
                "The request line is not a JSON object of {\"id\", \"command\", \"params\"}: "
                + error.Message,
                error);
        }

        if (request == null)
        {
            throw new BridgeProtocolError("The request line deserialized to null.");
        }

        if (string.IsNullOrWhiteSpace(request.Id))
        {
            throw new BridgeProtocolError("Every request needs a non-empty \"id\".");
        }

        if (string.IsNullOrWhiteSpace(request.Command))
        {
            throw new BridgeProtocolError(
                "Every request needs a \"command\": " + string.Join(", ", BridgeCommands.All) + ".");
        }

        return request;
    }

    /// <summary>One response as a single line, with no trailing newline.</summary>
    public static string WriteResponse(BridgeResponse response)
    {
        if (response == null)
        {
            throw new ArgumentNullException(nameof(response));
        }

        return JsonSerializer.Serialize(response, Options);
    }

    private static JsonSerializerOptions CreateOptions()
    {
        // The IR options, so enum spellings and property names match package.json exactly.
        var options = new JsonSerializerOptions(PackageSerializer.Options)
        {
            // One line per message is the whole framing contract.
            WriteIndented = false,
        };

        return options;
    }
}
