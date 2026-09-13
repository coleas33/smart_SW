using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Json.Schema;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The one loader for contracts/ir.schema.json in the test assembly. JsonSchema.FromFile
/// registers the schema's $id in a process-wide registry and registering the same $id
/// twice throws, so every test that validates a package goes through this cache.
/// </summary>
internal static class IrContract
{
    private const string SchemaFileName = "ir.schema.json";

    private static readonly Lazy<JsonSchema> Schema = new Lazy<JsonSchema>(Read);

    /// <summary>The IR contract schema, loaded once per test run.</summary>
    public static JsonSchema Load() => Schema.Value;

    /// <summary>Validates serialized package JSON and asserts, naming every failure.</summary>
    public static void AssertValid(string json)
    {
        using (var instance = System.Text.Json.JsonDocument.Parse(json))
        {
            EvaluationResults results = Load().Evaluate(
                instance.RootElement, new EvaluationOptions { OutputFormat = OutputFormat.List });

            Assert.True(results.IsValid, DescribeFailures(results, json));
        }
    }

    /// <summary>A readable list of the schema violations, with the package that caused them.</summary>
    public static string DescribeFailures(EvaluationResults results, string json)
    {
        var builder = new StringBuilder();
        builder.AppendLine("The serialized package does not satisfy contracts/ir.schema.json:");
        AppendFailures(results, builder);
        builder.AppendLine("--- package.json ---");
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
