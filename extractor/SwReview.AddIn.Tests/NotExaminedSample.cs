using System.Text.Json;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One `not_examined` value: the value of the key both check bodies carry (the JSON
/// `POST /checks/rms` and `POST /checks/standards` answer, and `GET /checks/{id}`) - `null`
/// when every component instance was read, or an object naming the ones that were not
/// (docs/feature-request-resolve-lightweight.md, docs/task-a-2026-09-19.md issue 3).
///
/// One fixture for both check pages, for the reason <see cref="AttentionSample"/> gives: it is
/// one shape on both surfaces, and a second copy in one page's tests would be the copy that
/// stops matching the other's the first time either is fixed.
/// </summary>
internal static class NotExaminedSample
{
    /// <summary>The sentence both pages render into `#not-examined`.</summary>
    public const string Sentence =
        "2 of 4 component instances were not read: DOWEL PIN cmp:0002 (lightweight), DOWEL PIN "
            + "cmp:0004 (lightweight). Interference, fit and the feature-tree rules cannot see "
            + "them.";

    /// <summary>The `not_examined` value, as a JSON literal a page test can embed.</summary>
    /// <param name="sentence">Replaces the sentence, for the injection test.</param>
    public static string Json(string? sentence = null) => JsonSerializer.Serialize(Value(sentence));

    /// <summary>The same value as an object, for a check sample's `not_examined` key.</summary>
    public static object Value(string? sentence = null) => new
    {
        sentence = sentence ?? Sentence,
        instances = new object[]
        {
            new { id = "cmp:0002", name = "DOWEL PIN", state = "lightweight" },
            new { id = "cmp:0004", name = "DOWEL PIN", state = "lightweight" },
        },
    };
}
