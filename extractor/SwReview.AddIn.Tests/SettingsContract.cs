using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Json.Schema;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The one loader for contracts/settings.schema.json in this test assembly, mirroring
/// SwReview.Extractor.Tests.IrContract: JsonSchema.FromFile registers the schema's $id in a
/// process-wide registry and registering the same $id twice throws, so every test that
/// validates a settings file goes through this cache.
/// </summary>
internal static class SettingsContract
{
    private const string SchemaFileName = "settings.schema.json";

    private static readonly Lazy<JsonSchema> Schema = new Lazy<JsonSchema>(Read);

    /// <summary>The settings contract schema, loaded once per test run.</summary>
    public static JsonSchema Load() => Schema.Value;

    /// <summary>Validates settings JSON and asserts, naming every failure.</summary>
    public static void AssertValid(string json)
    {
        using (var instance = System.Text.Json.JsonDocument.Parse(json))
        {
            EvaluationResults results = Load().Evaluate(
                instance.RootElement, new EvaluationOptions { OutputFormat = OutputFormat.List });

            Assert.True(results.IsValid, DescribeFailures(results, json));
        }
    }

    /// <summary>Asserts the JSON is refused by the contract, so a negative test cannot pass vacuously.</summary>
    public static void AssertInvalid(string json)
    {
        using (var instance = System.Text.Json.JsonDocument.Parse(json))
        {
            EvaluationResults results = Load().Evaluate(
                instance.RootElement, new EvaluationOptions { OutputFormat = OutputFormat.List });

            Assert.False(
                results.IsValid,
                "Expected contracts/settings.schema.json to refuse this document:" + Environment.NewLine + json);
        }
    }

    private static string DescribeFailures(EvaluationResults results, string json)
    {
        var builder = new StringBuilder();
        builder.AppendLine("The settings JSON does not satisfy contracts/settings.schema.json:");
        AppendFailures(results, builder);
        builder.AppendLine("--- settings.json ---");
        builder.AppendLine(json);
        return builder.ToString();
    }

    private static void AppendFailures(EvaluationResults results, StringBuilder builder)
    {
        if (results.IsValid)
        {
            return;
        }

        if (results.Errors != null)
        {
            foreach (KeyValuePair<string, string> error in results.Errors)
            {
                builder.AppendLine($"  {results.InstanceLocation} [{error.Key}] {error.Value}");
            }
        }

        if (results.Details != null)
        {
            foreach (EvaluationResults detail in results.Details)
            {
                AppendFailures(detail, builder);
            }
        }
    }

    private static JsonSchema Read()
    {
        string path = Path.Combine(AppContext.BaseDirectory, SchemaFileName);
        Assert.True(
            File.Exists(path),
            $"{SchemaFileName} was not copied next to the test assembly; check the Content item in the csproj.");
        return JsonSchema.FromFile(path);
    }
}
