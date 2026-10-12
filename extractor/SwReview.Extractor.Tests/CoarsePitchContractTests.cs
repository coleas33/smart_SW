using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using SwReview.Extractor.Fasteners;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 010 amendment 2026-10-08, T114. <see cref="CoarsePitch"/> is the extractor's copy of
/// the <c>metric</c> rows of <c>specs/010-mechanical-checks/contracts/coarse-pitch.json</c>,
/// which the name grammar reads to tell a pitch from a length (contracts/fasteners.md sections
/// 8.3 and 8.8). The Python copy, <c>reviewer/src/swreview/checks/coarse_pitch.yaml</c>, is
/// pinned to the same file by <c>reviewer/tests/unit/test_coarse_pitch.py</c>, so a value
/// changed in one copy and not the other fails that copy's suite (the pattern of the shared
/// name vectors, research R2.11).
/// </summary>
public class CoarsePitchContractTests
{
    private const string FileName = "coarse-pitch.json";

    [Fact]
    public void Metric_EqualsTheContractsMetricRowsInOrder()
    {
        IReadOnlyList<(double SizeMm, double CoarsePitchMm)> contract = ContractMetricRows();

        Assert.Equal(contract.Count, CoarsePitch.Metric.Count);
        for (int index = 0; index < contract.Count; index++)
        {
            Assert.Equal(contract[index].SizeMm, CoarsePitch.Metric[index].SizeMm);
            Assert.Equal(contract[index].CoarsePitchMm, CoarsePitch.Metric[index].CoarsePitchMm);
        }
    }

    [Fact]
    public void CoarsePitchMm_GivesEveryContractRowsPitch()
    {
        foreach ((double sizeMm, double coarsePitchMm) in ContractMetricRows())
        {
            Assert.Equal(coarsePitchMm, CoarsePitch.CoarsePitchMm(sizeMm));
        }
    }

    [Theory]
    [InlineData(25.0)] // a fine-only size: ISO 261 gives it fine pitches only
    [InlineData(2.3)] // a size in no table
    public void CoarsePitchMm_IsNullForASizeWithNoCoarsePitch(double sizeMm)
    {
        Assert.Null(CoarsePitch.CoarsePitchMm(sizeMm));
    }

    /// <summary>The <c>metric</c> rows of the contract file, in file order. Every failure to load is loud.</summary>
    private static IReadOnlyList<(double SizeMm, double CoarsePitchMm)> ContractMetricRows()
    {
        string path = Path.Combine(AppContext.BaseDirectory, FileName);
        Assert.True(
            File.Exists(path),
            $"{FileName} was not copied next to the test assembly; check the Content item in "
                + "SwReview.Extractor.Tests.csproj.");

        using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
        Assert.True(
            document.RootElement.TryGetProperty("metric", out JsonElement metric)
                && metric.ValueKind == JsonValueKind.Array,
            $"{FileName} has no 'metric' array.");

        var rows = new List<(double SizeMm, double CoarsePitchMm)>();
        foreach (JsonElement row in metric.EnumerateArray())
        {
            rows.Add((row.GetProperty("size_mm").GetDouble(), row.GetProperty("coarse_pitch_mm").GetDouble()));
        }

        Assert.True(rows.Count > 0, $"{FileName} holds no metric rows; every assertion over them would be vacuous.");
        return rows;
    }
}
