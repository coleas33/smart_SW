using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Rms;

/// <summary>Raised when the plan file is missing a field the command must not invent.</summary>
[Serializable]
public class SuppressPlanError : Exception
{
    public SuppressPlanError(string message)
        : base(message)
    {
    }

    public SuppressPlanError(string message, Exception inner)
        : base(message, inner)
    {
    }
}

/// <summary>
/// One feature the plan asks the command to test (data-model.md section 2,
/// <c>SuppressPlan</c>).
/// </summary>
public sealed class SuppressPlanFeature
{
    [JsonPropertyName("feature_id")]
    public string FeatureId { get; set; } = string.Empty;

    /// <summary>Base64 of GetPersistReference3 bytes, as the package records it.</summary>
    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    /// <summary>The document whose extension produced <see cref="PersistRef"/>.</summary>
    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("type_name")]
    public string TypeName { get; set; } = string.Empty;
}

/// <summary>
/// The plan <c>swreview rms suppress-plan</c> writes and <c>suppress-test</c> consumes
/// (contracts/cli.md, research R6).
///
/// The extractor holds no RMS constant (research R7): which features are Detail content, and
/// which group they belong to, is decided in Python against <c>rms_types.yaml</c> and arrives
/// here as data. This class therefore reads and validates; it decides nothing.
///
/// Every field is required and nothing is defaulted. An empty configuration would mean
/// suppressing features in whatever the document happens to be showing, and an empty
/// persistent reference would mean testing a feature nobody identified - both are silent
/// wrong answers of exactly the kind Principle I forbids.
///
/// Unknown properties are ignored rather than refused (unlike <c>package.json</c>): the
/// reviewer may add descriptive fields to the plan, and every field this command acts on is
/// checked below by name.
/// </summary>
public sealed class SuppressPlan
{
    private static readonly JsonSerializerOptions Options = new JsonSerializerOptions
    {
        PropertyNamingPolicy = null,
        PropertyNameCaseInsensitive = false,
    };

    /// <summary>The part document the plan is for, as the package ids it.</summary>
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    /// <summary>The review configuration; the command refuses to run in another one.</summary>
    [JsonPropertyName("configuration")]
    public string Configuration { get; set; } = string.Empty;

    /// <summary>The Detail group name, recorded into the run for the reviewer.</summary>
    [JsonPropertyName("group")]
    public string Group { get; set; } = string.Empty;

    /// <summary>The Detail content features, in tree order.</summary>
    [JsonPropertyName("features")]
    public List<SuppressPlanFeature> Features { get; set; } = new List<SuppressPlanFeature>();

    /// <summary>
    /// Reads and validates the plan at <paramref name="path"/>. Throws
    /// <see cref="FileNotFoundException"/> naming the command that writes one, and
    /// <see cref="SuppressPlanError"/> for a plan that is missing anything.
    /// </summary>
    public static SuppressPlan Load(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("A plan file path is required.", nameof(path));
        }

        if (!File.Exists(path))
        {
            throw new FileNotFoundException(
                $"No suppress-test plan at '{path}'. Write one with "
                + "'swreview rms suppress-plan --package <dir> --document <id> --out <file>'.",
                path);
        }

        return Parse(File.ReadAllText(path), path);
    }

    /// <summary>Parses and validates plan JSON. <paramref name="source"/> names the file in errors.</summary>
    public static SuppressPlan Parse(string json, string source)
    {
        if (json == null)
        {
            throw new ArgumentNullException(nameof(json));
        }

        SuppressPlan? plan;
        try
        {
            plan = JsonSerializer.Deserialize<SuppressPlan>(json, Options);
        }
        catch (JsonException error)
        {
            throw new SuppressPlanError($"'{source}' is not a readable plan: {error.Message}", error);
        }

        if (plan == null)
        {
            throw new SuppressPlanError($"'{source}' deserialized to nothing; it is not a plan.");
        }

        Require(plan.DocumentId, "document_id", source);
        Require(plan.Configuration, "configuration", source);
        Require(plan.Group, "group", source);

        if (plan.Features.Count == 0)
        {
            throw new SuppressPlanError(
                $"'{source}' lists no features. A plan with no features would produce a run "
                + "with no rows, which the reviewer would read as a tested part.");
        }

        for (int i = 0; i < plan.Features.Count; i++)
        {
            SuppressPlanFeature feature = plan.Features[i];
            string where = $"features[{i}]";
            Require(feature.FeatureId, $"{where}.feature_id", source);
            Require(feature.PersistRef, $"{where}.persist_ref", source);
            Require(feature.PersistRefScope, $"{where}.persist_ref_scope", source);
            Require(feature.Name, $"{where}.name", source);
            Require(feature.TypeName, $"{where}.type_name", source);
        }

        return plan;
    }

    private static void Require(string value, string field, string source)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new SuppressPlanError(
                $"'{source}' has no {field}. The plan is the only place this command learns "
                + "what to test, and nothing in it is defaulted.");
        }
    }
}
