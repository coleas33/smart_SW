using System;
using System.IO;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// `Fixtures/review-drawing-questions.json`, read once per test run: what one scripted review of
/// feature 011 gave the page, written by `reviewer/tests/fixtures/pane/generate_drawing_questions.py`
/// and held to a fresh generation by `reviewer/tests/unit/test_pane_drawing_fixture.py` (research
/// R2.24). `ReviewPageDrawingQuestionsTests` plays its questions, answers and coverage, and
/// <see cref="SummarySample"/> takes its drawing line from it (feature 011 T091), so both print
/// the backend's own words.
/// </summary>
internal static class DrawingQuestionsFixture
{
    public const string FileName = "review-drawing-questions.json";

    public const string WriteCommand = "uv run python tests/fixtures/pane/generate_drawing_questions.py --write";

    private static readonly Lazy<JsonElement> Loaded = new Lazy<JsonElement>(Read);

    /// <summary>The fixture's root object.</summary>
    public static JsonElement Value => Loaded.Value;

    private static JsonElement Read()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "Fixtures", FileName);
        Assert.True(
            File.Exists(path),
            FileName + " was not copied next to the test assembly; check the Content item in the csproj, "
            + "and regenerate it with `" + WriteCommand + "` from reviewer/.");
        return JsonDocument.Parse(File.ReadAllText(path)).RootElement.Clone();
    }
}
