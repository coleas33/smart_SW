using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Rms;

namespace SwReview.Extractor.Bridge;

/// <summary>
/// The five commands the bridge answers (contracts/cli.md, contracts/agent-tools.md).
/// Anything else is an error response naming these, never a silent no-op.
/// </summary>
public static class BridgeCommands
{
    public const string Ping = "ping";
    public const string Capture = "capture";
    public const string Measure = "measure";
    public const string Interference = "interference";

    /// <summary>
    /// Protocol 1.2 (T096): one component's bodies tessellated into the package's mesh
    /// directory, for a review whose package was extracted without meshes (lever 10a).
    /// Review scope only - a mesh fetch writes a file and can take seconds.
    /// </summary>
    public const string Tessellate = "tessellate";

    /// <summary>For the "unknown command" message and for SwReview.Extractor.Console/Serve/PROTOCOL.md.</summary>
    public static readonly string[] All = { Ping, Capture, Measure, Interference, Tessellate };
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
    /// in-process host requires one on every line. That is why the field's arrival needed no
    /// version bump - a client that omits it still works against the console host, and simply
    /// gets <c>unauthorized</c> from the in-process one.
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

// =====================================================================================
// T060. The remodel.* command family (contracts/bridge-remodel.md), added in protocol 1.1
// additively: the four 1.0 commands and the envelope are untouched.
//
// These are COMMANDS, not tools. The bridge already carries a secret policy, a call guard, a
// circuit breaker and a per-request log of gated members, and the re-modeler needs every one
// of them.
//
// The one property the whole family rests on: NO COMMAND THAT WRITES TAKES A DOCUMENT
// PARAMETER. RemodelScope holds the only IModelDoc2 the run can reach, and every write goes
// to it. Exactly two commands name a path at all - remodel.probe_scope and remodel.open -
// and both run before the scope exists. That is stronger than validating a path a caller
// supplied, and it is what the constitution's re-modeler exception rests on. It is asserted
// as a property over RemodelCommandTable rather than one command at a time, so a thirteenth
// command cannot be added without meeting it.
// =====================================================================================

/// <summary>The twelve <c>remodel.*</c> commands (contracts/bridge-remodel.md).</summary>
public static class RemodelCommands
{
    /// <summary>What makes a command part of the family, for the secret scope and the log.</summary>
    public const string Prefix = "remodel.";

    public const string ProbeScope = "remodel.probe_scope";
    public const string Open = "remodel.open";
    public const string Snapshot = "remodel.snapshot";
    public const string Rename = "remodel.rename";
    public const string Reorder = "remodel.reorder";
    public const string Folder = "remodel.folder";
    public const string Describe = "remodel.describe";
    public const string Equation = "remodel.equation";
    public const string Rebuild = "remodel.rebuild";
    public const string Geometry = "remodel.geometry";
    public const string Save = "remodel.save";
    public const string Close = "remodel.close";

    /// <summary>In the order contracts/bridge-remodel.md tabulates them.</summary>
    public static readonly string[] All =
    {
        ProbeScope, Open, Snapshot, Rename, Reorder, Folder, Describe, Equation, Rebuild,
        Geometry, Save, Close,
    };

    /// <summary>
    /// True for any command in the family, known or not. The secret scope is written against
    /// the prefix rather than the list, so a command added to the list cannot leak out of
    /// <c>RemodelSecret</c>'s scope by being forgotten somewhere else.
    /// </summary>
    public static bool IsRemodelCommand(string? command) =>
        command != null && command.StartsWith(Prefix, StringComparison.Ordinal);
}

/// <summary>When a command runs, relative to the one moment a document handle appears.</summary>
public enum RemodelCommandStage
{
    /// <summary>
    /// Before <c>remodel.open</c> has returned: <c>probe_scope</c>, which reads the engineer's
    /// already-open source and returns no handle, and <c>open</c> itself, which names the
    /// source to copy from and the copy to create. These two, and only these two, name a path.
    /// </summary>
    BeforeScope,

    /// <summary>
    /// On the scope's copy. Takes no path and no document: the target is unreachable, not
    /// validated.
    /// </summary>
    OnScope,
}

/// <summary>One row of the command table: what a command is allowed to be handed.</summary>
public sealed class RemodelCommandShape
{
    public RemodelCommandShape(
        string command,
        RemodelCommandStage stage,
        bool writes,
        bool namesAPath,
        string[] parameterNames,
        string[] addressingParameterNames)
    {
        Command = command;
        Stage = stage;
        Writes = writes;
        NamesAPath = namesAPath;
        ParameterNames = parameterNames;
        AddressingParameterNames = addressingParameterNames;
    }

    public string Command { get; }

    public RemodelCommandStage Stage { get; }

    /// <summary>Whether the command can change a document. For the log and the report.</summary>
    public bool Writes { get; }

    /// <summary>True for <c>probe_scope</c> and <c>open</c>, and for nothing else, ever.</summary>
    public bool NamesAPath { get; }

    /// <summary>
    /// <b>Exactly</b> the parameters the command reads, in the contract's order. A parameter
    /// not named here is not read, which is how "the target is unreachable" stays true of a
    /// request that carries an extra member.
    /// </summary>
    public IReadOnlyList<string> ParameterNames { get; }

    /// <summary>
    /// The subset of <see cref="ParameterNames"/> that addresses something in the tree. Every
    /// one is a persistent reference: names change and indices change on every reorder.
    /// </summary>
    public IReadOnlyList<string> AddressingParameterNames { get; }
}

/// <summary>
/// The whole command family as data, so the family's properties are asserted once over the
/// table instead of once per command.
/// </summary>
public static class RemodelCommandTable
{
    private static readonly string[] None = new string[0];

    private static readonly RemodelCommandShape[] CommandArray =
    {
        // The two that run before a document handle exists, and the only two that name a path.
        Shape(RemodelCommands.ProbeScope, RemodelCommandStage.BeforeScope, false, true,
            new[] { "source_path" }, None),
        Shape(RemodelCommands.Open, RemodelCommandStage.BeforeScope, true, true,
            new[] { "source_path", "copy_path", "run_id", "probe_id" }, None),

        // Everything below is on the scope's copy and names no document.
        Shape(RemodelCommands.Snapshot, RemodelCommandStage.OnScope, false, false, None, None),
        Shape(RemodelCommands.Rename, RemodelCommandStage.OnScope, true, false,
            new[] { "persist_ref", "new_name" }, new[] { "persist_ref" }),
        Shape(RemodelCommands.Reorder, RemodelCommandStage.OnScope, true, false,
            new[] { "feature_persist_ref", "anchor_persist_ref", "location" },
            new[] { "feature_persist_ref", "anchor_persist_ref" }),
        Shape(RemodelCommands.Folder, RemodelCommandStage.OnScope, true, false,
            new[] { "op", "name", "member_persist_refs", "folder_persist_ref" },
            new[] { "member_persist_refs", "folder_persist_ref" }),
        Shape(RemodelCommands.Describe, RemodelCommandStage.OnScope, true, false,
            new[] { "persist_ref", "text" }, new[] { "persist_ref" }),
        Shape(RemodelCommands.Equation, RemodelCommandStage.OnScope, true, false,
            new[] { "op", "index", "text", "which_configs" }, None),
        Shape(RemodelCommands.Rebuild, RemodelCommandStage.OnScope, true, false,
            new[] { "force" }, None),

        // It takes no parameters because there is nothing to name: the only document this run
        // can reach is the scope's copy, and the C# side stamps the subject from the run's
        // own phase.
        Shape(RemodelCommands.Geometry, RemodelCommandStage.OnScope, false, false, None, None),
        // One parameter, and it names no document: the geometry gate's verdict, which the
        // host refuses to save without. The measurement is the bridge's and the verdict is
        // Python's, so the host is told it rather than computing it.
        Shape(RemodelCommands.Save, RemodelCommandStage.OnScope, true, false,
            new[] { "verdict" }, None),
        Shape(RemodelCommands.Close, RemodelCommandStage.OnScope, true, false,
            new[] { "discard_copy" }, None),
    };

    /// <summary>One row per command, in <see cref="RemodelCommands.All"/>'s order.</summary>
    public static readonly IReadOnlyList<RemodelCommandShape> Commands = CommandArray;

    /// <summary>The row for <paramref name="command"/>, or null when it is not in the family.</summary>
    public static RemodelCommandShape? Find(string? command)
    {
        if (command == null)
        {
            return null;
        }

        foreach (RemodelCommandShape shape in CommandArray)
        {
            if (string.Equals(shape.Command, command, StringComparison.Ordinal))
            {
                return shape;
            }
        }

        return null;
    }

    /// <summary>The row for a command that must be in the family.</summary>
    public static RemodelCommandShape For(string command) =>
        Find(command) ?? throw new ArgumentException(
            $"'{command}' is not one of the {CommandArray.Length} remodel commands.", nameof(command));

    private static RemodelCommandShape Shape(
        string command,
        RemodelCommandStage stage,
        bool writes,
        bool namesAPath,
        string[] parameterNames,
        string[] addressingParameterNames) =>
        new RemodelCommandShape(
            command, stage, writes, namesAPath, parameterNames, addressingParameterNames);
}

/// <summary><c>remodel.reorder</c>'s <c>location</c>: a closed set of two.</summary>
public static class RemodelReorderLocations
{
    /// <summary><c>swMoveLocation_e.Before = 2</c> (VERIFIED value).</summary>
    public const string Before = "before";

    /// <summary><c>swMoveLocation_e.After = 3</c> (VERIFIED value).</summary>
    public const string After = "after";

    public static readonly string[] All = { Before, After };

    public static bool IsKnown(string? location) =>
        location != null && Array.IndexOf(All, location) >= 0;
}

/// <summary><c>remodel.folder</c>'s <c>op</c>: a closed set of three, one of them stage 2's.</summary>
public static class RemodelFolderOps
{
    public const string Create = "create";
    public const string Rename = "rename";

    /// <summary>
    /// Refused in v1 with <c>not_in_v1</c>. The value stays in the protocol so stage 2 adds an
    /// allowlist entry and a handler branch rather than a new command, and a part that would
    /// need a dissolve is refused by the scope gate before anything is copied.
    /// </summary>
    public const string Dissolve = "dissolve";

    public static readonly string[] All = { Create, Rename, Dissolve };

    public static bool IsKnown(string? op) => op != null && Array.IndexOf(All, op) >= 0;
}

/// <summary><c>remodel.equation</c>'s <c>op</c>: a closed set of three.</summary>
public static class RemodelEquationOps
{
    public const string Add = "add";

    /// <summary>FR-029's in-place repair. Never a delete plus an add (research R3.5).</summary>
    public const string Set = "set";

    public const string Delete = "delete";

    public static readonly string[] All = { Add, Set, Delete };

    public static bool IsKnown(string? op) => op != null && Array.IndexOf(All, op) >= 0;
}

/// <summary>Which member an equation write was proven to have landed through.</summary>
public static class RemodelEquationHelperPaths
{
    public const string Add3 = "add3";
    public const string Add2 = "add2";
    public const string SetEquation = "set_equation";
    public const string SetEquationAndConfigurationOption = "set_equation_and_configuration_option";
    public const string Delete = "delete";
}

/// <summary>
/// The stable tokens contracts/bridge-remodel.md's "Error codes" table names, all
/// twenty-four of them.
///
/// Every token here maps to one Python class in <c>bridge/remodel_client.py</c>, which
/// subclasses the existing <c>BridgeError</c>, so a caller that catches the base type cannot
/// crash on any of them. <see cref="BadRequest"/> is the "cannot be honoured as sent" token,
/// and it is in the table because the <b>handlers</b> raise it too and not only the parameter
/// readers: a <c>folder</c> <c>rename</c> aimed at something that is not an <c>FtrFolder</c>,
/// a <c>describe</c> whose previous text will not read and so has no inverse. All of them are
/// bugs in the caller rather than conditions of the part, which is why the contract gives it
/// <c>RemodelContractError</c>: a token the host emits on a change path and the table does
/// not list leaves the executor unable to tell "the caller sent junk" from "the change failed,
/// invert it".
/// </summary>
public static class RemodelErrorCodes
{
    public const string NotAPart = "not_a_part";
    public const string SourceNotOpen = "source_not_open";
    public const string ScopeNotProbed = "scope_not_probed";
    public const string ScopeChanged = "scope_changed";
    public const string SourceDirty = "source_dirty";
    public const string ExternalRefs = "external_refs";
    public const string CopyExists = "copy_exists";
    public const string CopyFailed = "copy_failed";
    public const string OpenFailed = "open_failed";
    public const string TagFailed = "tag_failed";
    public const string PreexistingRebuildErrors = "preexisting_rebuild_errors";
    public const string TargetMismatch = "target_mismatch";
    public const string GuardRefused = "guard_refused";
    public const string PersistRefUnresolved = "persist_ref_unresolved";
    public const string ReorderRefused = "reorder_refused";
    public const string FolderMembersNotContiguous = "folder_members_not_contiguous";
    public const string EquationUnverified = "equation_unverified";
    public const string RebuildRegressed = "rebuild_regressed";
    public const string RebuildTimeout = "rebuild_timeout";
    public const string GateNotPassed = "gate_not_passed";
    public const string SaveFailed = "save_failed";
    public const string NotInV1 = "not_in_v1";
    public const string RunInProgress = "run_in_progress";

    /// <summary>A request the parameter readers could not read. See the class remarks.</summary>
    public const string BadRequest = "bad_request";

    public static readonly string[] All =
    {
        NotAPart, SourceNotOpen, ScopeNotProbed, ScopeChanged, SourceDirty, ExternalRefs,
        CopyExists, CopyFailed, OpenFailed, TagFailed, PreexistingRebuildErrors, TargetMismatch,
        GuardRefused, PersistRefUnresolved, ReorderRefused, FolderMembersNotContiguous,
        EquationUnverified, RebuildRegressed, RebuildTimeout, GateNotPassed, SaveFailed,
        NotInV1, RunInProgress, BadRequest,
    };
}

/// <summary>
/// What a <c>remodel.*</c> error puts in <c>result</c>: the stable token and whatever names
/// the condition. The one addition protocol 1.0 makes for this family, under the same "except
/// where noted" allowance 1.0 grants <c>capture</c>.
/// </summary>
public sealed class RemodelErrorResult
{
    public RemodelErrorResult()
    {
    }

    /// <summary>Key and value pairs, in order; an odd count is a programming error.</summary>
    public RemodelErrorResult(string errorCode, params string[] detail)
    {
        ErrorCode = errorCode;
        if (detail == null || detail.Length == 0)
        {
            return;
        }

        if (detail.Length % 2 != 0)
        {
            throw new ArgumentException(
                "detail is key and value pairs; got an odd number of strings.", nameof(detail));
        }

        var pairs = new Dictionary<string, string>(StringComparer.Ordinal);
        for (int i = 0; i < detail.Length; i += 2)
        {
            pairs[detail[i]] = detail[i + 1];
        }

        Detail = pairs;
    }

    /// <summary>One of <see cref="RemodelErrorCodes"/>.</summary>
    [JsonPropertyName("error_code")]
    public string ErrorCode { get; set; } = string.Empty;

    /// <summary>Whatever names the condition; null when the token says the whole of it.</summary>
    [JsonPropertyName("detail")]
    public IReadOnlyDictionary<string, string>? Detail { get; set; }
}

/// <summary>
/// A refusal carrying the stable token contracts/bridge-remodel.md's error table maps to a
/// Python class. The dispatcher turns it into <c>status: "error"</c> with a
/// <see cref="RemodelErrorResult"/>, so no handler formats a response itself and no token
/// reaches the wire without being one of <see cref="RemodelErrorCodes"/>.
/// </summary>
[Serializable]
public class RemodelCommandError : Exception
{
    public RemodelCommandError(string errorCode, string message)
        : this(errorCode, message, null)
    {
    }

    public RemodelCommandError(
        string errorCode, string message, IReadOnlyDictionary<string, string>? detail)
        : base(message)
    {
        ErrorCode = errorCode;
        Detail = detail;
    }

    /// <summary>One of <see cref="RemodelErrorCodes"/>.</summary>
    public string ErrorCode { get; }

    /// <summary>What goes in <c>result.detail</c>, or null.</summary>
    public IReadOnlyDictionary<string, string>? Detail { get; }

    /// <summary>This refusal as the object the response carries.</summary>
    public RemodelErrorResult ToResult() =>
        new RemodelErrorResult { ErrorCode = ErrorCode, Detail = Detail };
}

/// <summary>
/// Reading <c>params</c>. One place, so every command reports a missing or mistyped member
/// the same way and every <c>remodel.*</c> parse failure carries
/// <see cref="RemodelErrorCodes.BadRequest"/> rather than a bare sentence.
/// </summary>
public static class BridgeParams
{
    /// <summary>The raw member, or false when <c>params</c> is not an object or lacks it.</summary>
    public static bool TryGet(BridgeRequest request, string name, out JsonElement value)
    {
        value = default(JsonElement);
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        if (request.Params.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        return request.Params.TryGetProperty(name, out value);
    }

    public static string? OptionalString(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGet(request, name, out value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        return value.GetString();
    }

    public static int? OptionalInt(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGet(request, name, out value) || value.ValueKind != JsonValueKind.Number)
        {
            return null;
        }

        int parsed;
        return value.TryGetInt32(out parsed) ? parsed : (int?)null;
    }

    public static bool? OptionalBool(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGet(request, name, out value))
        {
            return null;
        }

        switch (value.ValueKind)
        {
            case JsonValueKind.True:
                return true;
            case JsonValueKind.False:
                return false;
            default:
                return null;
        }
    }

    /// <summary>A required string member of a <c>remodel.*</c> request.</summary>
    public static string RequiredString(BridgeRequest request, string name)
    {
        string? value = OptionalString(request, name);
        if (string.IsNullOrWhiteSpace(value))
        {
            throw Missing(request, name, "a non-empty string");
        }

        return value!.Trim();
    }

    /// <summary>A required integer member of a <c>remodel.*</c> request.</summary>
    public static int RequiredInt(BridgeRequest request, string name)
    {
        int? value = OptionalInt(request, name);
        if (value == null)
        {
            throw Missing(request, name, "an integer");
        }

        return value.Value;
    }

    /// <summary>
    /// A string array member. Absent is an empty list; a non-string element is a refusal,
    /// never a silently dropped member - a dropped persist ref addresses the wrong feature.
    /// </summary>
    public static IReadOnlyList<string> StringArray(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGet(request, name, out value) || value.ValueKind != JsonValueKind.Array)
        {
            return new string[0];
        }

        var items = new List<string>();
        foreach (JsonElement item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(item.GetString()))
            {
                throw Missing(request, name, "an array of non-empty strings");
            }

            items.Add(item.GetString()!.Trim());
        }

        return items;
    }

    /// <summary>A member whose value must be one of a closed set.</summary>
    public static string RequiredChoice(BridgeRequest request, string name, string[] choices)
    {
        string value = RequiredString(request, name);
        if (Array.IndexOf(choices, value) < 0)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                $"'{request.Command}' needs \"params.{name}\" to be one of "
                + string.Join(", ", choices) + $"; got '{value}'.");
        }

        return value;
    }

    private static RemodelCommandError Missing(BridgeRequest request, string name, string wanted) =>
        new RemodelCommandError(
            RemodelErrorCodes.BadRequest,
            $"'{request.Command}' needs \"params.{name}\" to be {wanted}.");
}

// ---- request shapes -----------------------------------------------------------------
// One reader per command, reading EXACTLY the parameters RemodelCommandTable declares for it.

/// <summary><c>remodel.probe_scope</c>: the one command that touches the source, and it reads.</summary>
public sealed class RemodelProbeScopeParams
{
    private RemodelProbeScopeParams(string sourcePath)
    {
        SourcePath = sourcePath;
    }

    public string SourcePath { get; }

    public static RemodelProbeScopeParams Read(BridgeRequest request) =>
        new RemodelProbeScopeParams(BridgeParams.RequiredString(request, "source_path"));
}

/// <summary><c>remodel.open</c>: the source to copy from and the copy to create.</summary>
public sealed class RemodelOpenParams
{
    private RemodelOpenParams(string sourcePath, string copyPath, string runId, string probeId)
    {
        SourcePath = sourcePath;
        CopyPath = copyPath;
        RunId = runId;
        ProbeId = probeId;
    }

    public string SourcePath { get; }

    public string CopyPath { get; }

    public string RunId { get; }

    /// <summary>A probe this bridge session performed, on this exact canonicalized source.</summary>
    public string ProbeId { get; }

    public static RemodelOpenParams Read(BridgeRequest request) =>
        new RemodelOpenParams(
            BridgeParams.RequiredString(request, "source_path"),
            BridgeParams.RequiredString(request, "copy_path"),
            BridgeParams.RequiredString(request, "run_id"),
            BridgeParams.RequiredString(request, "probe_id"));
}

/// <summary><c>remodel.rename</c>: a feature persist ref and a name. No dimension form (FR-030).</summary>
public sealed class RemodelRenameParams
{
    private RemodelRenameParams(string persistRef, string newName)
    {
        PersistRef = persistRef;
        NewName = newName;
    }

    public string PersistRef { get; }

    public string NewName { get; }

    public static RemodelRenameParams Read(BridgeRequest request) =>
        new RemodelRenameParams(
            BridgeParams.RequiredString(request, "persist_ref"),
            BridgeParams.RequiredString(request, "new_name"));
}

/// <summary><c>remodel.reorder</c>: two persist refs and a closed-set location.</summary>
public sealed class RemodelReorderParams
{
    private RemodelReorderParams(string featurePersistRef, string anchorPersistRef, string location)
    {
        FeaturePersistRef = featurePersistRef;
        AnchorPersistRef = anchorPersistRef;
        Location = location;
    }

    public string FeaturePersistRef { get; }

    public string AnchorPersistRef { get; }

    /// <summary>One of <see cref="RemodelReorderLocations"/>.</summary>
    public string Location { get; }

    public static RemodelReorderParams Read(BridgeRequest request) =>
        new RemodelReorderParams(
            BridgeParams.RequiredString(request, "feature_persist_ref"),
            BridgeParams.RequiredString(request, "anchor_persist_ref"),
            BridgeParams.RequiredChoice(request, "location", RemodelReorderLocations.All));
}

/// <summary><c>remodel.folder</c>: create or rename; dissolve is answered <c>not_in_v1</c>.</summary>
public sealed class RemodelFolderParams
{
    private RemodelFolderParams(
        string op, string? name, IReadOnlyList<string> memberPersistRefs, string? folderPersistRef)
    {
        Op = op;
        Name = name;
        MemberPersistRefs = memberPersistRefs;
        FolderPersistRef = folderPersistRef;
    }

    /// <summary>One of <see cref="RemodelFolderOps"/>.</summary>
    public string Op { get; }

    public string? Name { get; }

    /// <summary>The contiguous run a <c>create</c> wraps; empty for the other operations.</summary>
    public IReadOnlyList<string> MemberPersistRefs { get; }

    public string? FolderPersistRef { get; }

    public static RemodelFolderParams Read(BridgeRequest request) =>
        new RemodelFolderParams(
            BridgeParams.RequiredChoice(request, "op", RemodelFolderOps.All),
            BridgeParams.OptionalString(request, "name"),
            BridgeParams.StringArray(request, "member_persist_refs"),
            BridgeParams.OptionalString(request, "folder_persist_ref"));
}

/// <summary><c>remodel.describe</c>: a feature persist ref and the text to write.</summary>
public sealed class RemodelDescribeParams
{
    private RemodelDescribeParams(string persistRef, string text)
    {
        PersistRef = persistRef;
        Text = text;
    }

    public string PersistRef { get; }

    /// <summary>
    /// May be empty - writing <c>""</c> is how a description is cleared - so it is read as an
    /// optional string and defaulted to <c>""</c> rather than required non-empty.
    /// </summary>
    public string Text { get; }

    public static RemodelDescribeParams Read(BridgeRequest request) =>
        new RemodelDescribeParams(
            BridgeParams.RequiredString(request, "persist_ref"),
            BridgeParams.OptionalString(request, "text") ?? string.Empty);
}

/// <summary><c>remodel.equation</c>: add, set or delete, by index into the equation manager.</summary>
public sealed class RemodelEquationParams
{
    private RemodelEquationParams(string op, int? index, string? text, int? whichConfigs)
    {
        Op = op;
        Index = index;
        Text = text;
        WhichConfigs = whichConfigs;
    }

    /// <summary>One of <see cref="RemodelEquationOps"/>.</summary>
    public string Op { get; }

    /// <summary>
    /// The position in the equation manager. Required for <c>set</c> and <c>delete</c>;
    /// for <c>add</c> it is where the new equation goes, and null means "at the end".
    /// </summary>
    public int? Index { get; }

    public string? Text { get; }

    /// <summary>
    /// <c>swInConfigurationOpts_e</c>. Null is unknown, never a guess: the configuration count
    /// <c>remodel.open</c> recorded is what the caller composes it from.
    /// </summary>
    public int? WhichConfigs { get; }

    public static RemodelEquationParams Read(BridgeRequest request) =>
        new RemodelEquationParams(
            BridgeParams.RequiredChoice(request, "op", RemodelEquationOps.All),
            BridgeParams.OptionalInt(request, "index"),
            BridgeParams.OptionalString(request, "text"),
            BridgeParams.OptionalInt(request, "which_configs"));
}

/// <summary><c>remodel.rebuild</c>: one flag, and no document.</summary>
public sealed class RemodelRebuildParams
{
    private RemodelRebuildParams(bool force)
    {
        Force = force;
    }

    /// <summary><c>ForceRebuild3(force)</c>'s <c>TopOnly</c>. Absent is false.</summary>
    public bool Force { get; }

    public static RemodelRebuildParams Read(BridgeRequest request) =>
        new RemodelRebuildParams(BridgeParams.OptionalBool(request, "force") ?? false);
}

/// <summary>
/// <c>remodel.save</c>: the geometry gate's verdict for this run, and nothing else.
///
/// The bridge measures the geometry and Python decides the verdict
/// (contracts/bridge-remodel.md, <c>remodel.geometry</c>), so the host cannot compute the
/// tri-state it has to gate on - it is told. Telling it is what lets the refusal live where
/// <c>Save3</c> lives: the constitution's mutation exception permits the save "only after the
/// geometry comparison has passed", and a clause enforced in the caller alone is a clause the
/// caller can skip.
/// </summary>
public sealed class RemodelSaveParams
{
    private RemodelSaveParams(string verdict)
    {
        Verdict = verdict;
    }

    /// <summary>
    /// <c>GateResult.verdict</c>: <c>pass</c>, <c>fail</c> or <c>unresolved</c>. Required,
    /// because a missing verdict is not a passing one and a default here would be a default
    /// written for engineering data.
    /// </summary>
    public string Verdict { get; }

    public static RemodelSaveParams Read(BridgeRequest request) =>
        new RemodelSaveParams(BridgeParams.RequiredString(request, "verdict"));
}

/// <summary><c>remodel.close</c>: close the tagged copy, and optionally delete it.</summary>
public sealed class RemodelCloseParams
{
    private RemodelCloseParams(bool discardCopy)
    {
        DiscardCopy = discardCopy;
    }

    /// <summary>
    /// Deletes <c>copy/</c> and nothing else. Discard keeps every other artifact, because
    /// "what did it propose?" must stay answerable after the engineer says no.
    /// </summary>
    public bool DiscardCopy { get; }

    public static RemodelCloseParams Read(BridgeRequest request) =>
        new RemodelCloseParams(BridgeParams.OptionalBool(request, "discard_copy") ?? false);
}

// ---- response shapes ----------------------------------------------------------------

/// <summary>What <c>remodel.probe_scope</c> answers. No document handle, ever.</summary>
public sealed class RemodelProbeScopeResult
{
    /// <summary>Minted against the canonicalized source path; <c>remodel.open</c> checks it.</summary>
    [JsonPropertyName("probe_id")]
    public string ProbeId { get; set; } = string.Empty;

    [JsonPropertyName("source_path")]
    public string SourcePath { get; set; } = string.Empty;

    /// <summary>
    /// The raw measurements. The verdict is <b>not</b> made here: the pure
    /// <c>remodel/scope.py</c> decides it, so the refusal table is table-testable with no seat.
    /// </summary>
    [JsonPropertyName("scope_signals")]
    public ScopeSignals? ScopeSignals { get; set; }
}

/// <summary>What <c>remodel.open</c> answers, once the copy exists and is open at its own path.</summary>
public sealed class RemodelOpenResult
{
    /// <summary>The copy. Asserted equal to <c>copy_path</c> and unequal to the source.</summary>
    [JsonPropertyName("document_path")]
    public string DocumentPath { get; set; } = string.Empty;

    /// <summary>The <c>SwReviewRemodelRun</c> value, read back rather than assumed.</summary>
    [JsonPropertyName("tag")]
    public string Tag { get; set; } = string.Empty;

    [JsonPropertyName("feature_count")]
    public int FeatureCount { get; set; }

    /// <summary>Measured on the <b>copy</b>, at step 12, and compared with the probe's.</summary>
    [JsonPropertyName("scope_signals")]
    public ScopeSignals? ScopeSignals { get; set; }

    [JsonPropertyName("configurations")]
    public IReadOnlyList<string> Configurations { get; set; } = new string[0];

    /// <summary>
    /// The only stated source for FR-027's metres-to-document-unit conversion. Null is
    /// unknown, and a change that needs it refuses rather than assuming metres.
    /// </summary>
    [JsonPropertyName("document_length_unit")]
    public string? DocumentLengthUnit { get; set; }

    [JsonPropertyName("source_attestation")]
    public SourceAttestation? SourceAttestation { get; set; }
}

/// <summary>
/// What <c>remodel.snapshot</c> answers: the same shape before and after every change, so the
/// executor diffs without a second vocabulary.
/// </summary>
public sealed class RemodelSnapshotResult
{
    /// <summary>Tree order, as persist refs.</summary>
    [JsonPropertyName("order")]
    public IReadOnlyList<string> Order { get; set; } = new string[0];

    /// <summary>Keyed by persist ref, not a list: a list would be addressed by index.</summary>
    [JsonPropertyName("names")]
    public IReadOnlyDictionary<string, string?> Names { get; set; } =
        new Dictionary<string, string?>(StringComparer.Ordinal);

    /// <summary>
    /// Keyed by persist ref. <c>null</c> means <b>unreadable</b>, which is not the same as
    /// <c>""</c>, which means absent: an inverse that writes <c>""</c> over something
    /// unreadable is a silent edit, so the planner refuses that feature up front.
    /// </summary>
    [JsonPropertyName("descriptions")]
    public IReadOnlyDictionary<string, string?> Descriptions { get; set; } =
        new Dictionary<string, string?>(StringComparer.Ordinal);

    /// <summary>The IR <c>Equation</c> shape, so a snapshot row and a package row are one type.</summary>
    [JsonPropertyName("equations")]
    public IReadOnlyList<Equation> Equations { get; set; } = new Equation[0];

    /// <summary>
    /// The manager positions whose text read back <c>null</c>, which is <b>unreadable</b>.
    /// They carry no <see cref="Equations"/> row, because <c>Equation.text</c> is a string and
    /// an empty one would be a default written over engineering data - the same reason a
    /// description reads back <c>null</c> rather than <c>""</c>. Named rather than left to a
    /// gap in the surviving rows' indexes, so a snapshot that is shorter than the manager says
    /// on its face which rows are missing and why.
    /// </summary>
    [JsonPropertyName("unreadable_equation_indexes")]
    public IReadOnlyList<int> UnreadableEquationIndexes { get; set; } = new int[0];

    /// <summary><c>GetWhatsWrongCount()</c>.</summary>
    [JsonPropertyName("rebuild_errors")]
    public int RebuildErrors { get; set; }

    [JsonPropertyName("feature_count")]
    public int FeatureCount { get; set; }
}

/// <summary>What <c>remodel.rename</c> answers. <c>previous_name</c> is read, never guessed.</summary>
public sealed class RemodelRenameResult
{
    [JsonPropertyName("previous_name")]
    public string? PreviousName { get; set; }

    [JsonPropertyName("new_name")]
    public string NewName { get; set; } = string.Empty;
}

/// <summary>What <c>remodel.reorder</c> answers: everything <c>derive_undo</c> needs.</summary>
public sealed class RemodelReorderResult
{
    [JsonPropertyName("previous_anchor_persist_ref")]
    public string? PreviousAnchorPersistRef { get; set; }

    /// <summary>One of <see cref="RemodelReorderLocations"/>, or null when there was no anchor.</summary>
    [JsonPropertyName("previous_location")]
    public string? PreviousLocation { get; set; }

    [JsonPropertyName("previous_index")]
    public int PreviousIndex { get; set; }

    [JsonPropertyName("new_index")]
    public int NewIndex { get; set; }
}

/// <summary>What <c>remodel.folder</c> answers, with membership verified rather than assumed.</summary>
public sealed class RemodelFolderResult
{
    [JsonPropertyName("folder_persist_ref")]
    public string? FolderPersistRef { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("member_persist_refs")]
    public IReadOnlyList<string> MemberPersistRefs { get; set; } = new string[0];
}

/// <summary>What <c>remodel.describe</c> answers.</summary>
public sealed class RemodelDescribeResult
{
    /// <summary>Null is unreadable; the planner refuses such a feature before any write.</summary>
    [JsonPropertyName("previous_text")]
    public string? PreviousText { get; set; }
}

/// <summary>What <c>remodel.equation</c> answers, for every one of the three operations.</summary>
public sealed class RemodelEquationResult
{
    [JsonPropertyName("index")]
    public int Index { get; set; }

    [JsonPropertyName("count_before")]
    public int CountBefore { get; set; }

    [JsonPropertyName("count_after")]
    public int CountAfter { get; set; }

    /// <summary>Read before the write, for the inverse. Null on an <c>add</c>.</summary>
    [JsonPropertyName("previous_text")]
    public string? PreviousText { get; set; }

    /// <summary>
    /// <c>get_Equation(i)</c> after the write. This, not the member's return code, is the
    /// evidence the write landed (PROBE-6 saw <c>Add3</c> return -1 and add nothing).
    /// </summary>
    [JsonPropertyName("round_trip_text")]
    public string? RoundTripText { get; set; }

    /// <summary>
    /// Which member succeeded, one of <see cref="RemodelEquationHelperPaths"/>, so the run
    /// report can say what the seat actually did.
    /// </summary>
    [JsonPropertyName("helper_path")]
    public string? HelperPath { get; set; }
}

/// <summary>One feature's error reading. The primary reading a rebuild answers with.</summary>
public sealed class RemodelFeatureError
{
    [JsonPropertyName("persist_ref")]
    public string? PersistRef { get; set; }

    /// <summary>For the report. Never used to address anything.</summary>
    [JsonPropertyName("name")]
    public string? Name { get; set; }

    /// <summary><c>IFeature.GetErrorCode2(out bool)</c>; <c>swFeatureErrorNone = 0</c>.</summary>
    [JsonPropertyName("error_code")]
    public int ErrorCode { get; set; }

    [JsonPropertyName("is_warning")]
    public bool IsWarning { get; set; }
}

/// <summary>What <c>remodel.rebuild</c> answers.</summary>
public sealed class RemodelRebuildResult
{
    /// <summary><c>GetWhatsWrongCount()</c>.</summary>
    [JsonPropertyName("rebuild_errors")]
    public int RebuildErrors { get; set; }

    /// <summary>
    /// Corroborating only: the out-array element type of <c>GetWhatsWrong</c> is UNVERIFIED
    /// (PROBE-9), and re-joining by name is fragile where two features in different folders
    /// share one.
    /// </summary>
    [JsonPropertyName("whats_wrong")]
    public IReadOnlyList<string> WhatsWrong { get; set; } = new string[0];

    [JsonPropertyName("elapsed_ms")]
    public long ElapsedMs { get; set; }

    /// <summary>The <b>primary</b> reading: one <c>GetErrorCode2</c> per feature.</summary>
    [JsonPropertyName("feature_errors")]
    public IReadOnlyList<RemodelFeatureError> FeatureErrors { get; set; } = new RemodelFeatureError[0];
}

/// <summary>
/// <c>GeometryReading.subject</c>: a closed set of two, both of them the run's own copy.
///
/// The C# side stamps it from the run's own phase, so the caller cannot ask for a reading of
/// anything else - which is the whole reason <c>remodel.geometry</c> takes no parameters.
/// </summary>
public static class RemodelGeometrySubjects
{
    /// <summary>
    /// Taken after the baseline rollback and rebuild and before the first change. It stands in
    /// for the source, which is never opened in any mode (FR-037): the copy is a byte-for-byte
    /// <c>File.Copy</c> whose SHA-256 was recorded before any document handle existed, and the
    /// reading carries that hash.
    /// </summary>
    public const string CopyAtOpen = "copy_at_open";

    /// <summary>Taken after the last change.</summary>
    public const string CopyAtEnd = "copy_at_end";

    public static readonly string[] All = { CopyAtOpen, CopyAtEnd };
}

/// <summary>
/// The geometry gate's tri-state, as <c>remodel.save</c> is told it. The same three tokens as
/// <c>remodel/geometry.py</c>'s <c>Verdict</c>; the decision is made there and reported here,
/// because the measurement is the bridge's and the verdict is Python's.
/// </summary>
public static class RemodelGateVerdicts
{
    /// <summary>The only verdict <c>remodel.save</c> proceeds on.</summary>
    public const string Pass = "pass";

    public const string Fail = "fail";

    /// <summary>The gate could not decide. Not a pass, and never treated as one.</summary>
    public const string Unresolved = "unresolved";

    /// <summary>
    /// A verdict is reached from a before and an after (<c>copy_at_open</c> and
    /// <c>copy_at_end</c>), both taken by this host. A run that has produced fewer readings
    /// than this has no gate result to report, whatever it says it has.
    /// </summary>
    public const int ReadingsAVerdictNeeds = 2;

    public static readonly string[] All = { Pass, Fail, Unresolved };
}

/// <summary>
/// What <c>remodel.geometry</c> answers: one reading of the copy's mass properties
/// (data-model.md section 3.1), measured in C# and <b>never interpreted here</b> - the verdict
/// is <c>remodel/geometry.py</c>'s, so that it is table-testable with no seat.
///
/// Every length is metres. A measured field is null when it could not be read, and
/// <see cref="Status"/> says why: unknown stays unknown, because a defaulted zero is a number
/// the gate would compare and pass.
/// </summary>
public sealed class GeometryReading
{
    [JsonPropertyName("at")]
    public DateTime At { get; set; }

    /// <summary>The attested hash of the source the copy was made from; the same on both readings.</summary>
    [JsonPropertyName("source_sha256")]
    public string SourceSha256 { get; set; } = string.Empty;

    /// <summary>One of <see cref="RemodelGeometrySubjects"/>, stamped by the run's phase.</summary>
    [JsonPropertyName("subject")]
    public string Subject { get; set; } = string.Empty;

    /// <summary><c>swMassPropertiesStatus_e</c>; anything but <c>OK(0)</c> makes the gate unresolved.</summary>
    [JsonPropertyName("status")]
    public int Status { get; set; }

    /// <summary><c>swMassPropertyAccuracyLevel_Higher = 2</c> on every reading.</summary>
    [JsonPropertyName("accuracy_level")]
    public int AccuracyLevel { get; set; }

    /// <summary><c>IMassProperty2.Recalculate()</c>'s answer, checked <b>before</b> anything was read.</summary>
    [JsonPropertyName("recalculated")]
    public bool Recalculated { get; set; }

    [JsonPropertyName("volume_m3")]
    public double? VolumeM3 { get; set; }

    [JsonPropertyName("surface_area_m2")]
    public double? SurfaceAreaM2 { get; set; }

    [JsonPropertyName("center_of_mass_m")]
    public IReadOnlyList<double>? CenterOfMassM { get; set; }

    /// <summary>
    /// <b>Sorted ascending</b> by the producer: two bodies differing by a symmetry-degenerate
    /// rotation return the same three numbers permuted.
    /// </summary>
    [JsonPropertyName("principal_moments")]
    public IReadOnlyList<double>? PrincipalMoments { get; set; }

    /// <summary>Compared <b>separately</b> from geometry: mass is volume times density.</summary>
    [JsonPropertyName("mass_kg")]
    public double? MassKg { get; set; }

    /// <inheritdoc cref="MassKg" />
    [JsonPropertyName("density")]
    public double? Density { get; set; }

    /// <summary>
    /// <c>IPartDoc.GetMaterialPropertyName2</c> (VERIFIED). A mass-only delta reports
    /// <c>material_changed</c> and never <c>geometry_changed</c>, which is what this is for.
    /// </summary>
    [JsonPropertyName("material_name")]
    public string? MaterialName { get; set; }

    [JsonPropertyName("solid_body_count")]
    public int SolidBodyCount { get; set; }

    [JsonPropertyName("sheet_body_count")]
    public int SheetBodyCount { get; set; }

    /// <summary>Summed over the solid bodies; null when one of them would not answer.</summary>
    [JsonPropertyName("face_count")]
    public int? FaceCount { get; set; }

    /// <inheritdoc cref="FaceCount" />
    [JsonPropertyName("edge_count")]
    public int? EdgeCount { get; set; }

    /// <summary>
    /// Tier 2's boolean symmetric difference. <b>Always null in v1</b>: stage 1 creates no
    /// geometry, so it cannot mirror anything, and the field exists so that stage 2 adds a tier
    /// rather than changing a type.
    /// </summary>
    [JsonPropertyName("residual")]
    public object? Residual { get; set; }
}

/// <summary>What <c>remodel.save</c> answers. <c>Save3</c> takes no filename (VERIFIED).</summary>
public sealed class RemodelSaveResult
{
    /// <summary>The copy, as <c>AssertSaveTarget</c> confirmed it.</summary>
    [JsonPropertyName("path")]
    public string Path { get; set; } = string.Empty;

    [JsonPropertyName("errors")]
    public int Errors { get; set; }

    /// <summary><c>swFileSaveWarning_RebuildError (1)</c> is a failed run with a saved artifact.</summary>
    [JsonPropertyName("warnings")]
    public int Warnings { get; set; }

    /// <summary><c>GetSaveFlag()</c> after the save; asserted false.</summary>
    [JsonPropertyName("save_flag_after")]
    public bool SaveFlagAfter { get; set; }
}

/// <summary>What <c>remodel.close</c> answers.</summary>
public sealed class RemodelCloseResult
{
    [JsonPropertyName("closed")]
    public bool Closed { get; set; }

    /// <summary>True only when <c>discard_copy</c> was asked for and the copy is gone.</summary>
    [JsonPropertyName("copy_deleted")]
    public bool CopyDeleted { get; set; }
}
