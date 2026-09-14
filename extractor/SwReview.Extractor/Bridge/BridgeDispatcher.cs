using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Measure;
using IrCapture = SwReview.Extractor.Ir.Capture;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Bridge;

/// <summary>Turns one request into one response. The pipe knows nothing about commands.</summary>
public interface IBridgeDispatcher
{
    BridgeResponse Dispatch(BridgeRequest request);
}

/// <summary>What <c>ping</c> answers: enough to prove the worker is alive and on the right model.</summary>
public sealed class PingResult
{
    [JsonPropertyName("pong")]
    public bool Pong { get; set; } = true;

    /// <summary>The protocol this server speaks; see SwReview.Extractor.Console/Serve/PROTOCOL.md.</summary>
    [JsonPropertyName("protocol")]
    public string Protocol { get; set; } = SwBridgeDispatcher.ProtocolVersion;

    [JsonPropertyName("sw_version")]
    public string? SwVersion { get; set; }

    /// <summary>Full path of the document the worker attached to.</summary>
    [JsonPropertyName("document")]
    public string? Document { get; set; }

    [JsonPropertyName("configuration")]
    public string? Configuration { get; set; }

    /// <summary>
    /// How many components carry an id. Component ids only mean the same thing here as in
    /// package.json while this is the document that was dumped.
    /// </summary>
    [JsonPropertyName("component_count")]
    public int ComponentCount { get; set; }
}

/// <summary>What <c>capture</c> answers.</summary>
public sealed class CaptureCommandResult
{
    /// <summary>The IR row to append to <c>captures</c>, or null when the capture failed.</summary>
    [JsonPropertyName("capture")]
    public IrCapture? Capture { get; set; }

    /// <summary>Absolute path of the PNG, so the client can copy it into its own package.</summary>
    [JsonPropertyName("path")]
    public string? Path { get; set; }

    /// <summary>The gap to record when the capture failed, else null.</summary>
    [JsonPropertyName("gap")]
    public Gap? Gap { get; set; }
}

/// <summary>What <c>measure</c> answers: SOLIDWORKS' numbers, in meters, unrounded.</summary>
public sealed class MeasureCommandResult
{
    [JsonPropertyName("distance")]
    public Quantity? Distance { get; set; }

    [JsonPropertyName("delta_x")]
    public Quantity? DeltaX { get; set; }

    [JsonPropertyName("delta_y")]
    public Quantity? DeltaY { get; set; }

    [JsonPropertyName("delta_z")]
    public Quantity? DeltaZ { get; set; }
}

/// <summary>What <c>interference</c> answers.</summary>
public sealed class InterferenceCommandResult
{
    [JsonPropertyName("interferences")]
    public List<IrInterference> Interferences { get; set; } = new List<IrInterference>();

    [JsonPropertyName("gaps")]
    public List<Gap> Gaps { get; set; } = new List<Gap>();
}

/// <summary>
/// Everything the dispatcher needs, as interfaces, so the command handling is unit tested
/// with fakes and no SOLIDWORKS (T072). <see cref="PipeServer"/> builds the real one on the
/// STA worker thread, because the COM pointers inside must not cross threads.
/// </summary>
public sealed class BridgeServices
{
    public BridgeServices(
        ICaptureView capture,
        IMeasureSource measure,
        IInterferenceSource interference,
        ComponentIndex components,
        string captureDirectory)
    {
        CaptureView = capture ?? throw new ArgumentNullException(nameof(capture));
        Measure = measure ?? throw new ArgumentNullException(nameof(measure));
        Interference = interference ?? throw new ArgumentNullException(nameof(interference));
        Components = components ?? throw new ArgumentNullException(nameof(components));
        CaptureDirectory = captureDirectory ?? throw new ArgumentNullException(nameof(captureDirectory));
    }

    public ICaptureView CaptureView { get; }

    public IMeasureSource Measure { get; }

    public IInterferenceSource Interference { get; }

    /// <summary>Package component ids to live components, and back.</summary>
    public ComponentIndex Components { get; }

    /// <summary>
    /// The package directory captures are written under. Chosen by the host from
    /// <c>--out</c>, never by the client: a path in a request would be a filesystem write
    /// the agent controls (research R4).
    /// </summary>
    public string CaptureDirectory { get; }

    public string? SwVersion { get; set; }

    public string? DocumentPath { get; set; }

    public string? Configuration { get; set; }
}

/// <summary>
/// T072. The bridge's command handling.
///
/// Four things happen to every request, whatever the command:
///   * the <see cref="ISecretPolicy"/> is asked whether the request's <c>secret</c>
///     authorizes its command, before anything else runs (T045). The console host passes
///     <see cref="NoSecretPolicy"/> and this is a no-op; the add-in's in-process host
///     passes a <see cref="ScopedSecretPolicy"/>, which is where <c>interference</c> is
///     actually withheld from general chat.
///   * <see cref="ReadOnlyGuard"/> is asked about the command name, so a request that names
///     a mutating API - <c>Save3</c>, <c>FeatureCut4</c> - is refused before anything runs.
///     Everything the handlers then call goes through <c>SwGate</c>, which asks again.
///   * A <see cref="CircuitOpenError"/> becomes <c>circuit_open</c> rather than an error, so
///     the client can stop asking instead of retrying a dead session.
///   * The response carries the elapsed milliseconds, because a bridge call that took eight
///     seconds is information the reviewer's timing report wants.
/// </summary>
public sealed class SwBridgeDispatcher : IBridgeDispatcher
{
    /// <summary>Bumped when a request or response shape changes; see SwReview.Extractor.Console/Serve/PROTOCOL.md.</summary>
    public const string ProtocolVersion = "1.0";

    /// <summary>
    /// The whole of what a refused request is told (T045). One word, the same for a wrong
    /// secret, a missing one, and a valid one asking for a command outside its scope.
    /// </summary>
    public const string UnauthorizedError = "unauthorized";

    private readonly BridgeServices _services;
    private readonly ISecretPolicy _secrets;
    private readonly CaptureService _captures;

    /// <param name="services">Everything SOLIDWORKS, as interfaces.</param>
    /// <param name="secrets">
    /// How the <c>secret</c> on a request line is judged. Required rather than defaulted,
    /// so neither host can end up permissive by omission: the console host passes
    /// <see cref="NoSecretPolicy.Instance"/> and says so at its call site.
    /// </param>
    /// <param name="captureIds">Test hook: the allocator capture ids come from.</param>
    public SwBridgeDispatcher(
        BridgeServices services, ISecretPolicy secrets, Ids.IdAllocator? captureIds = null)
    {
        _services = services ?? throw new ArgumentNullException(nameof(services));
        _secrets = secrets ?? throw new ArgumentNullException(nameof(secrets));
        _captures = new CaptureService(services.CaptureView, captureIds);
    }

    public BridgeResponse Dispatch(BridgeRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        var clock = Stopwatch.StartNew();
        BridgeResponse response;

        try
        {
            if (!_secrets.IsAuthorized(request.Secret, request.Command))
            {
                // Authenticate and authorize before the command is even looked up, so a
                // refused caller cannot learn what this bridge answers, and nothing it
                // named ever touches SOLIDWORKS. The secret itself is not echoed.
                response = BridgeResponse.Failed(request.Id, UnauthorizedError);
            }
            else
            {
                // The guard sees the command name itself, so "command": "Save3" cannot reach
                // a handler even if one were ever added for it.
                ReadOnlyGuard.Assert(request.Command);
                response = Run(request);
            }
        }
        catch (CircuitOpenError error)
        {
            response = BridgeResponse.CircuitOpen(request.Id, error.Message);
        }
        catch (MutatingCallError error)
        {
            response = BridgeResponse.Failed(request.Id, error.Message);
        }
        catch (Exception error)
        {
            response = BridgeResponse.Failed(
                request.Id, error.GetType().Name + ": " + error.Message);
        }

        clock.Stop();
        response.ElapsedMs = clock.ElapsedMilliseconds;
        return response;
    }

    private BridgeResponse Run(BridgeRequest request)
    {
        switch (request.Command)
        {
            case BridgeCommands.Ping:
                return BridgeResponse.Ok(request.Id, Ping());

            case BridgeCommands.Capture:
                return Capture(request);

            case BridgeCommands.Measure:
                return Measure(request);

            case BridgeCommands.Interference:
                return Interference(request);

            default:
                return BridgeResponse.Failed(
                    request.Id,
                    $"Unknown command '{request.Command}'. This bridge answers "
                    + string.Join(", ", BridgeCommands.All) + ".");
        }
    }

    private PingResult Ping() => new PingResult
    {
        SwVersion = _services.SwVersion,
        Document = _services.DocumentPath,
        Configuration = _services.Configuration,
        ComponentCount = _services.Components.Count,
    };

    private BridgeResponse Capture(BridgeRequest request)
    {
        string persistRef = RequiredString(request, "persist_ref");
        string view = OptionalString(request, "view") ?? CaptureViews.Fit;
        string? scope = OptionalString(request, "scope_document");
        string note = OptionalString(request, "note") ?? string.Empty;

        if (!CaptureViews.IsKnown(view))
        {
            return BridgeResponse.Failed(
                request.Id,
                $"\"view\" must be one of {string.Join(", ", CaptureViews.All)}; got '{view}'.");
        }

        CaptureResult result = _captures.Capture(
            persistRef, scope, view, _services.CaptureDirectory, note);

        if (!result.Succeeded)
        {
            Gap? gap = result.Gap;
            return BridgeResponse.Failed(
                request.Id,
                gap == null
                    ? "The capture did not happen."
                    : gap.Reason + (gap.Error == null ? string.Empty : " - " + gap.Error),
                new CaptureCommandResult { Capture = null, Path = null, Gap = gap });
        }

        return BridgeResponse.Ok(
            request.Id,
            new CaptureCommandResult
            {
                Capture = result.Capture,
                Path = Path.GetFullPath(
                    Path.Combine(
                        _services.CaptureDirectory,
                        result.Capture!.File.Replace('/', Path.DirectorySeparatorChar))),
                Gap = null,
            });
    }

    private BridgeResponse Measure(BridgeRequest request)
    {
        string a = RequiredString(request, "persist_ref_a");
        string b = RequiredString(request, "persist_ref_b");
        string? scopeA = OptionalString(request, "scope_document_a");
        string? scopeB = OptionalString(request, "scope_document_b");

        try
        {
            MeasureReading reading = _services.Measure.Measure(a, scopeA, b, scopeB);
            return BridgeResponse.Ok(
                request.Id,
                new MeasureCommandResult
                {
                    Distance = reading.Distance,
                    DeltaX = reading.DeltaX,
                    DeltaY = reading.DeltaY,
                    DeltaZ = reading.DeltaZ,
                });
        }
        catch (MeasureNotAvailableError error)
        {
            // An unsupported pairing is an error with a sentence, never a number
            // (constitution Principle I).
            return BridgeResponse.Failed(request.Id, error.Message);
        }
    }

    private BridgeResponse Interference(BridgeRequest request)
    {
        IReadOnlyList<string> componentIds = StringArray(request, "component_ids");
        string configuration = OptionalString(request, "configuration")
            ?? _services.Configuration
            ?? string.Empty;

        InterferenceRunSettings settings;
        try
        {
            settings = ReadSettings(request);
        }
        catch (ArgumentException error)
        {
            return BridgeResponse.Failed(request.Id, error.Message);
        }

        int? truncateAfter = OptionalInt(request, "truncate_after");

        List<InterferencePair> pairs;
        try
        {
            pairs = Pairs(componentIds);
        }
        catch (ArgumentException error)
        {
            return BridgeResponse.Failed(request.Id, error.Message);
        }

        var runner = new InterferenceRunner(_services.Interference);
        InterferenceRunResult result = runner.Run(
            configuration,
            pairs,
            settings,
            handle => _services.Components.IdOf(handle),
            id => _services.Components.PatternOf(id),
            truncateAfter);

        return BridgeResponse.Ok(
            request.Id,
            new InterferenceCommandResult
            {
                Interferences = new List<IrInterference>(result.Interferences),
                Gaps = new List<Gap>(result.Gaps),
            });
    }

    /// <summary>
    /// <c>component_ids</c> to work units: none is the whole assembly, two is that pair, and
    /// more than two is every unordered pair among them. An id this document does not have
    /// is refused by name rather than quietly dropped - dropping it would report "no
    /// interference" for a component that was never checked.
    /// </summary>
    private List<InterferencePair> Pairs(IReadOnlyList<string> componentIds)
    {
        var pairs = new List<InterferencePair>();
        if (componentIds.Count == 0)
        {
            pairs.Add(InterferencePair.WholeAssembly());
            return pairs;
        }

        if (componentIds.Count == 1)
        {
            throw new ArgumentException(
                "\"component_ids\" needs either none (the whole assembly) or at least two "
                + "components; one component cannot interfere with nothing.");
        }

        var components = new List<InterferenceComponent>(componentIds.Count);
        foreach (string id in componentIds)
        {
            InterferenceComponent? component = _services.Components.ById(id);
            if (component == null)
            {
                throw new ArgumentException(
                    $"'{id}' is not a component of the document this bridge is attached to "
                    + $"({_services.DocumentPath ?? "unknown"}).");
            }

            components.Add(component);
        }

        for (int i = 0; i < components.Count; i++)
        {
            for (int j = i + 1; j < components.Count; j++)
            {
                pairs.Add(InterferencePair.Of(components[i], components[j]));
            }
        }

        return pairs;
    }

    private static InterferenceRunSettings ReadSettings(BridgeRequest request)
    {
        var settings = new InterferenceRunSettings();
        JsonElement element;
        if (!TryGetMember(request, "settings", out element) || element.ValueKind != JsonValueKind.Object)
        {
            return settings;
        }

        settings.TreatCoincidentAsInterference =
            Flag(element, "treat_coincident_as_interference", settings.TreatCoincidentAsInterference);
        settings.TreatSubassembliesAsComponents =
            Flag(element, "treat_subassemblies_as_components", settings.TreatSubassembliesAsComponents);
        settings.IncludeMultibody = Flag(element, "include_multibody", settings.IncludeMultibody);
        settings.IgnoreHidden = Flag(element, "ignore_hidden", settings.IgnoreHidden);

        JsonElement treatment;
        if (element.TryGetProperty("fastener_folder_treatment", out treatment)
            && treatment.ValueKind == JsonValueKind.String)
        {
            settings.Fasteners = InterferenceRunSettings.ParseFastenerTreatment(treatment.GetString());
        }

        return settings;
    }

    private static bool Flag(JsonElement settings, string name, bool fallback)
    {
        JsonElement value;
        if (!settings.TryGetProperty(name, out value))
        {
            return fallback;
        }

        switch (value.ValueKind)
        {
            case JsonValueKind.True:
                return true;
            case JsonValueKind.False:
                return false;
            default:
                throw new ArgumentException($"\"settings.{name}\" must be true or false.");
        }
    }

    private static bool TryGetMember(BridgeRequest request, string name, out JsonElement value)
    {
        value = default(JsonElement);
        if (request.Params.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        return request.Params.TryGetProperty(name, out value);
    }

    private static string RequiredString(BridgeRequest request, string name)
    {
        string? value = OptionalString(request, name);
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new BridgeProtocolError(
                $"'{request.Command}' needs a non-empty \"params.{name}\".");
        }

        return value!;
    }

    private static string? OptionalString(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGetMember(request, name, out value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        return value.GetString();
    }

    private static int? OptionalInt(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGetMember(request, name, out value) || value.ValueKind != JsonValueKind.Number)
        {
            return null;
        }

        int parsed;
        return value.TryGetInt32(out parsed) ? parsed : (int?)null;
    }

    private static IReadOnlyList<string> StringArray(BridgeRequest request, string name)
    {
        JsonElement value;
        if (!TryGetMember(request, name, out value) || value.ValueKind != JsonValueKind.Array)
        {
            return new string[0];
        }

        var items = new List<string>();
        foreach (JsonElement item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String)
            {
                throw new BridgeProtocolError($"\"params.{name}\" must hold strings.");
            }

            string? text = item.GetString();
            if (!string.IsNullOrWhiteSpace(text))
            {
                items.Add(text!);
            }
        }

        return items;
    }
}
