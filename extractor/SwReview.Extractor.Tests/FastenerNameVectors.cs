using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.Extractor.Fasteners;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 010 T050. <c>specs/010-mechanical-checks/contracts/fastener-name-vectors.json</c>,
/// read. The same rows are asserted against the Python parser
/// (<c>reviewer/tests/unit/test_fastener_names.py</c>), so a name one parser reads and the
/// other does not fails a suite instead of drifting (contracts/fasteners.md section 2).
///
/// Every row is one text from one source. A row whose <c>csharp</c> is <c>false</c> is a
/// form this parser never receives and is skipped here; every other row is this parser's to
/// answer. Every failure to load is loud: a loader that quietly returned no rows would make
/// every theory over the table vacuous.
/// </summary>
internal static class FastenerNameVectors
{
    /// <summary>What a row expects, in the Python parser's vocabulary.</summary>
    public sealed class Expected
    {
        public Expected(string? kind, string? headType, string thread, double? lengthMm)
        {
            Kind = kind;
            HeadType = headType;
            Thread = thread;
            LengthMm = lengthMm;
        }

        /// <summary>"screw", "bolt", ...; null when the text names no kind.</summary>
        public string? Kind { get; }

        public string? HeadType { get; }

        /// <summary>The designation upper-cased with no whitespace, e.g. "M4X0.7".</summary>
        public string Thread { get; }

        /// <summary>Millimetres, converted from inches for a unified thread; null when absent.</summary>
        public double? LengthMm { get; }
    }

    /// <summary>One row of the table.</summary>
    public sealed class Row
    {
        public Row(int index, string source, string text, Expected? expected, bool csharp)
        {
            Index = index;
            Source = source;
            Text = text;
            Expected = expected;
            CSharp = csharp;
        }

        public int Index { get; }

        /// <summary>"file_name", "description" or "configuration".</summary>
        public string Source { get; }

        public string Text { get; }

        /// <summary>Null means "this text names no size": the parser reads no designation.</summary>
        public Expected? Expected { get; }

        /// <summary>False for a form this parser never receives.</summary>
        public bool CSharp { get; }
    }

    private const string FileName = "fastener-name-vectors.json";

    private static readonly Lazy<IReadOnlyList<Row>> Table = new Lazy<IReadOnlyList<Row>>(Read);

    /// <summary>Every row, in file order.</summary>
    public static IReadOnlyList<Row> Rows => Table.Value;

    /// <summary>The rows this parser answers, as theory data: the row's index into <see cref="Rows"/>.</summary>
    public static IEnumerable<object[]> CSharpRows() =>
        Rows.Where(row => row.CSharp).Select(row => new object[] { row.Index, row.Source, row.Text });

    /// <summary>
    /// The parser's answer for one row: the text is handed to the argument its source names,
    /// and nothing else is given.
    /// </summary>
    public static FastenerIdentity Parse(Row row) => row.Source switch
    {
        "file_name" => FastenerNameParser.Parse(null, null, row.Text),
        "description" => FastenerNameParser.Parse(null, row.Text),
        "configuration" => FastenerNameParser.Parse(row.Text),
        _ => throw new InvalidOperationException(
            $"{FileName} row {row.Index} names the source '{row.Source}', which no parser reads."),
    };

    /// <summary>
    /// <see cref="FastenerNameParser.IsCandidate"/> for one row, with the text in the argument
    /// its source names.
    /// </summary>
    public static bool IsCandidate(Row row) => row.Source switch
    {
        "file_name" => FastenerNameParser.IsCandidate(row.Text, null, null),
        "description" => FastenerNameParser.IsCandidate(null, row.Text, null),
        "configuration" => FastenerNameParser.IsCandidate(null, null, row.Text),
        _ => throw new InvalidOperationException(
            $"{FileName} row {row.Index} names the source '{row.Source}', which no parser reads."),
    };

    /// <summary>The designation as the table spells it: upper case, no whitespace.</summary>
    public static string? NormalizedThread(FastenerIdentity identity) =>
        identity.ThreadDesignation == null
            ? null
            : new string(identity.ThreadDesignation.Where(c => !char.IsWhiteSpace(c)).ToArray())
                .ToUpperInvariant();

    /// <summary>The kind in the table's vocabulary; <see cref="FastenerKind.Other"/> is null.</summary>
    public static string? KindName(FastenerIdentity identity) =>
        identity.Kind == FastenerKind.Other ? null : PackageSerializer.EnumToJsonName(identity.Kind);

    /// <summary>The length in millimetres, whatever unit the parser recorded it in.</summary>
    public static double? LengthMm(FastenerIdentity identity)
    {
        if (identity.Length == null)
        {
            return null;
        }

        return identity.Length.Unit switch
        {
            LengthUnit.Mm => identity.Length.Value,
            LengthUnit.In => identity.Length.Value * 25.4,
            LengthUnit.M => identity.Length.Value * 1000.0,
            _ => throw new InvalidOperationException($"Unknown length unit {identity.Length.Unit}."),
        };
    }

    private static IReadOnlyList<Row> Read()
    {
        string path = Path.Combine(AppContext.BaseDirectory, FileName);
        Assert.True(
            File.Exists(path),
            $"{FileName} was not copied next to the test assembly; check the Content item in "
                + "SwReview.Extractor.Tests.csproj.");

        using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
        Assert.True(
            document.RootElement.ValueKind == JsonValueKind.Array,
            $"{FileName} must be a JSON array of rows.");

        var rows = new List<Row>();
        int index = 0;
        foreach (JsonElement element in document.RootElement.EnumerateArray())
        {
            rows.Add(ReadRow(index, element));
            index++;
        }

        Assert.True(rows.Count > 0, $"{FileName} holds no rows; every theory over it would be vacuous.");
        return rows;
    }

    private static Row ReadRow(int index, JsonElement element)
    {
        string source = RequiredString(index, element, "source");
        string text = RequiredString(index, element, "text");
        bool csharp = !element.TryGetProperty("csharp", out JsonElement flag) || flag.GetBoolean();

        Assert.True(
            element.TryGetProperty("expected", out JsonElement expected),
            $"{FileName} row {index} has no 'expected' member.");

        if (expected.ValueKind == JsonValueKind.Null)
        {
            return new Row(index, source, text, null, csharp);
        }

        return new Row(
            index,
            source,
            text,
            new Expected(
                OptionalString(expected, "kind"),
                OptionalString(expected, "head_type"),
                RequiredString(index, expected, "thread"),
                expected.TryGetProperty("length_mm", out JsonElement length)
                    && length.ValueKind != JsonValueKind.Null
                    ? length.GetDouble()
                    : (double?)null),
            csharp);
    }

    private static string RequiredString(int index, JsonElement element, string name)
    {
        Assert.True(
            element.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String,
            $"{FileName} row {index} has no string '{name}' member.");
        return value.GetString()!;
    }

    private static string? OptionalString(JsonElement element, string name) =>
        element.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
}
