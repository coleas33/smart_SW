using System;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// Converts PascalCase enum member names to the exact lowercase strings in
/// contracts/ir.schema.json: an underscore before every uppercase letter except the first,
/// then lowercase. Digits are left attached, so <c>Mm3</c> becomes <c>mm3</c> and
/// <c>AntiAligned</c> becomes <c>anti_aligned</c>.
/// </summary>
public sealed class SnakeCaseLowerNamingPolicy : JsonNamingPolicy
{
    public static readonly SnakeCaseLowerNamingPolicy Instance = new SnakeCaseLowerNamingPolicy();

    public override string ConvertName(string name)
    {
        if (string.IsNullOrEmpty(name))
        {
            return name;
        }

        var builder = new StringBuilder(name.Length + 4);
        for (int i = 0; i < name.Length; i++)
        {
            char c = name[i];
            if (char.IsUpper(c))
            {
                if (i > 0)
                {
                    builder.Append('_');
                }

                builder.Append(char.ToLowerInvariant(c));
            }
            else
            {
                builder.Append(c);
            }
        }

        return builder.ToString();
    }
}

/// <summary>
/// The only way an <see cref="EvidencePackage"/> becomes JSON and back. The options are
/// fixed so the C# extractor and the Python reviewer agree byte for byte on the contract:
/// explicit snake_case property names (no naming policy, every name carries
/// JsonPropertyName), nulls written rather than skipped, and enums as schema strings.
/// </summary>
public static class PackageSerializer
{
    public static readonly JsonSerializerOptions Options = CreateOptions();

    /// <summary>Serializes a package as indented JSON with every null field present.</summary>
    public static string Serialize(EvidencePackage package)
    {
        if (package == null)
        {
            throw new ArgumentNullException(nameof(package));
        }

        return JsonSerializer.Serialize(package, Options);
    }

    /// <summary>Parses a package. Unknown properties and unknown enum values are errors.</summary>
    public static EvidencePackage Deserialize(string json)
    {
        if (json == null)
        {
            throw new ArgumentNullException(nameof(json));
        }

        EvidencePackage? package = JsonSerializer.Deserialize<EvidencePackage>(json, Options);
        if (package == null)
        {
            throw new JsonException("The IR package JSON deserialized to null.");
        }

        return package;
    }

    /// <summary>The schema string for an enum value, e.g. LengthUnit.Mm -> "mm".</summary>
    public static string EnumToJsonName<TEnum>(TEnum value)
        where TEnum : struct, Enum
    {
        return SnakeCaseLowerNamingPolicy.Instance.ConvertName(value.ToString());
    }

    private static JsonSerializerOptions CreateOptions()
    {
        var options = new JsonSerializerOptions
        {
            WriteIndented = true,

            // Nulls are evidence: "unknown" must survive the round trip (Principle I).
            DefaultIgnoreCondition = JsonIgnoreCondition.Never,

            // Property names come from [JsonPropertyName] only.
            PropertyNamingPolicy = null,
            PropertyNameCaseInsensitive = false,

            // additionalProperties is false throughout the schema and the pydantic models
            // use extra="forbid" (research R5); extractor drift must fail loudly here too.
            UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,

            // Discrepancy.expected/actual are string | integer | null in the schema.
            UnknownTypeHandling = JsonUnknownTypeHandling.JsonElement,

            // Base64 persist refs stay readable instead of becoming + escapes.
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        };

        options.Converters.Add(
            new JsonStringEnumConverter(SnakeCaseLowerNamingPolicy.Instance, allowIntegerValues: false));

        return options;
    }
}
