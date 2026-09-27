using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One <c>remodel.*</c> line written to a tool service's own pipe and answered on it, exactly as
/// the backend's bridge client sends it: the secret in the line, one request per connection.
/// Shared by the tool service's wiring tests (<see cref="ToolServiceWiringTests"/>) and the Plan
/// driven end to end over the fakes (<see cref="RemodelPlanEndToEndTests"/>), so the two speak to
/// the pipe the same way.
/// </summary>
internal static class RemodelPipe
{
    public static PipeReply Send(string pipeName, string secret, string command, object parameters)
    {
        string line = JsonSerializer.Serialize(new Dictionary<string, object>
        {
            { "id", "1" },
            { "command", command },
            { "secret", secret },
            { "params", parameters },
        });

        using (var client = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut))
        {
            client.Connect(10000);
            var writer = new StreamWriter(client, new UTF8Encoding(false)) { AutoFlush = true };
            var reader = new StreamReader(client, new UTF8Encoding(false));
            writer.WriteLine(line);
            return new PipeReply(reader.ReadLine()!);
        }
    }
}

/// <summary>One response line as it came off the pipe.</summary>
internal sealed class PipeReply
{
    public PipeReply(string line)
    {
        JsonElement root = JsonDocument.Parse(line).RootElement.Clone();
        Status = root.GetProperty("status").GetString()!;
        Error = root.TryGetProperty("error", out JsonElement error) && error.ValueKind == JsonValueKind.String
            ? error.GetString()
            : null;
        Result = root.TryGetProperty("result", out JsonElement result) ? result : default;
        ErrorCode = Result.ValueKind == JsonValueKind.Object
            && Result.TryGetProperty("error_code", out JsonElement code)
            && code.ValueKind == JsonValueKind.String
                ? code.GetString()
                : null;
    }

    public string Status { get; }

    public string? Error { get; }

    public string? ErrorCode { get; }

    public JsonElement Result { get; }
}
