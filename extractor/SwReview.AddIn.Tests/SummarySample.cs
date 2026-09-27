using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One `ReviewRanking` as `specs/009-engineer-workspace/contracts/review-summary.md` prints it,
/// amended by feature 013 (`specs/013-engineer-first-review/contracts/grouped-list.md` sections 3
/// and 4): <see cref="AttentionSample"/>'s ranking plus the `summary` the backend computes beside it
/// and the grouped findings (`groups`, <see cref="GroupsSample"/>). Hand-built, so the page tests
/// run before the backend that computes them has landed (tasks.md: "its page tasks need only the
/// contract").
///
/// What is deliberate about it:
///
/// <b>Every number is one no page could have computed.</b> The headline, the tally and the
/// not-reached line do not follow from <see cref="AttentionSample"/>'s six rows or from the
/// groups: a page that counted anything prints a different number and fails. The page prints.
///
/// <b>The summary is 013's.</b> The headline counts passes as checked; one tally line replaces the
/// Decide, Fix and Verify lines with their goal counts; one not-reached line names the goals the
/// review did not reach, in goal order; the goal lines themselves live under their groups
/// (<see cref="GroupsSample"/>), and `modelling_practice` and the top-level goal list are gone.
///
/// <b>The three questions are the three shapes</b> contracts/questions.md names: a short form
/// with offered answers and the goal it blocks, a short form answered in free text, and an older
/// request with only its long `what`.
///
/// <b>The drawing line is there</b> (feature 009 T086, the owner's decision 10A, 2026-09-23): a
/// summary from this build carries one line about drawings, and a test of an older backend
/// removes it. It is the one line no page could compose, so it is the backend's own: the
/// `summary_drawings` block of the generated `Fixtures/review-drawing-questions.json`
/// (<see cref="DrawingQuestionsFixture"/>, feature 011 T091), member for member.
/// </summary>
internal static class SummarySample
{
    public const string Headline = "99 findings in 18 issues · 2 checked, no issue";

    /// <summary>The one tally line (grouped-list.md section 4): the kinds of action, independent of the type.</summary>
    public const string TallyText = "Decide 9 · Fix 56 · Verify 34 · Decided 1";

    /// <summary>The goals the review did not reach, in goal order, in the backend's words.</summary>
    public const string NotReachedText = "Not reached: Fasteners, Fits and stacks, Tool access";

    public const string QuestionsText = "3 questions for you";

    public const string NotLoadedText = "3 of 89 parts not loaded";

    /// <summary>
    /// The summary's one line about drawings (feature 009 T086, the owner's decision 10A): the
    /// backend's words, which no page could compose from the ranking beside them - the generated
    /// fixture's (feature 011 T091).
    /// </summary>
    public static string DrawingsText => DrawingsLine.GetProperty("text").GetString()!;

    /// <summary>`{read, candidates, text}` as `report/summary.drawings_of` returned it.</summary>
    private static JsonElement DrawingsLine => DrawingQuestionsFixture.Value.GetProperty("summary_drawings");

    public const string ResumeText =
        "Sending resumes the review once. Its last round sent 405,861 input tokens.";

    /// <summary>
    /// The summary's one line about bought parts (feature 013, contracts/part-roles.md section 7):
    /// the persisted rows' sentence, which names the parts not graded once and counts nothing the
    /// page could count - it is the backend's, and the page prints it as sent.
    /// </summary>
    public const string BoughtPartsText =
        "2 parts not graded for modelling practice or hygiene (bought): FICT-PIN-01.SLDPRT (under the "
        + "bought-parts folder), FICT-VALVE-ASM.SLDASM (a Toolbox part)";

    /// <summary>A recorded sentence that carries markup, on the fits-and-stacks goal (<see cref="GroupsSample"/>).</summary>
    public const string HostileDetail = "<img src=x onerror=alert(1)></details><script>alert(2)</script>";

    /// <summary>The names the Review tab prints instead of ids: every component but one.</summary>
    public static readonly Dictionary<string, string> ComponentNames = new Dictionary<string, string>
    {
        { "cmp:0001", "Base-1" },
        { "cmp:0002", "Pin-A-1" },
        { "cmp:0003", "Plate-1" },
        { "cmp:0004", "Pin-B-1" },
    };

    /// <summary>The three open questions, in the order the summary supplies them.</summary>
    public static readonly string[] QuestionIds = { "ER-002", "ER-004", "ER-007" };

    /// <summary>The part-roles question's short form (feature 013, contracts/part-roles.md section 8).</summary>
    public const string PartRolesQuestionText =
        "Are these bought parts? Until you answer, they are graded for modelling practice and hygiene.";

    /// <summary>Its two offered answers, in the order the question offers them.</summary>
    public static readonly string[] PartRolesOptions = { "All bought", "None bought" };

    /// <summary>
    /// The part-roles question as the summary lists it (`QuestionView`, feature 013 T034): the one
    /// code-written question with two buttons and a text box (`allow_text`), about the documents
    /// no rule tells apart. Hand-built from the contract, fictional names only, a fresh node on
    /// every call so a test can place it in a summary of its own.
    /// </summary>
    public static JsonNode PartRolesQuestion() => JsonNode.Parse(JsonSerializer.Serialize(new
    {
        id = "ER-001",
        question = PartRolesQuestionText,
        options = PartRolesOptions,
        allow_text = true,
        source = "code",
        blocks = (string?)null,
        blocks_title = (string?)null,
        what = "Parts no rule tells apart: FICT-PIN-01.SLDPRT, FICT-SPACER-02.SLDPRT",
        why = "Bought parts are not graded for modelling practice or hygiene. Answer to regrade this review now.",
        about = new object[]
        {
            new { id = "doc:0003", name = "FICT-PIN-01.SLDPRT" },
            new { id = "doc:0004", name = "FICT-SPACER-02.SLDPRT" },
        },
    }))!;

    /// <summary>
    /// Replaces a summary's open questions with <paramref name="items"/>, in that order, counted
    /// the way the backend counts them (the questions line is the words file's).
    /// </summary>
    public static void Ask(JsonObject summary, params JsonNode[] items)
    {
        summary["questions"] = new JsonObject
        {
            ["count"] = items.Length,
            ["text"] = items.Length == 1 ? "1 question for you" : items.Length + " questions for you",
            ["items"] = new JsonArray(items),
        };
    }

    /// <summary>One of <see cref="QuestionIds"/>' questions as this sample lists it, a fresh copy.</summary>
    public static JsonNode Question(int index) => Summary()["questions"]!["items"]![index]!.DeepClone();

    /// <summary>The ranking with its summary and its groups, as a JSON literal a page test can embed.</summary>
    /// <param name="change">Edits the summary object before it is serialized.</param>
    public static string Json(Action<JsonObject>? change = null) => Ranking(change).ToJsonString();

    /// <summary>The ranking with its summary and its groups (<see cref="GroupsSample"/>), as a mutable node.</summary>
    public static JsonObject Ranking(Action<JsonObject>? change = null)
    {
        JsonObject ranking = JsonNode.Parse(AttentionSample.Json())!.AsObject();
        JsonObject summary = Summary();
        change?.Invoke(summary);
        ranking["summary"] = summary;
        ranking["groups"] = GroupsSample.Groups();
        return ranking;
    }

    /// <summary>The summary alone, as a mutable node.</summary>
    public static JsonObject Summary() => JsonNode.Parse(JsonSerializer.Serialize(Build()))!.AsObject();

    /// <summary>
    /// The ranking of a review that recorded nothing: the headline says so in words, the tally is
    /// at zero, the not-reached line names what was not reached, and the groups print their goals'
    /// state with no row (review-summary.md section 6, grouped-list.md section 3).
    /// </summary>
    public static string EmptyJson()
    {
        JsonObject ranking = JsonNode.Parse(AttentionSample.EmptyJson())!.AsObject();
        JsonObject summary = Summary();
        summary["headline"] = EmptyHeadline;
        summary["findings"] = 0;
        summary["issues"] = 0;
        summary["groups"] = JsonNode.Parse(JsonSerializer.Serialize(new object[]
        {
            Group("decide", "Decide", 0, "0 need your decision"),
            Group("fix", "Fix", 0, "0 to fix"),
            Group("verify", "Verify", 0, "0 to verify"),
        }));
        summary["tally"] = new JsonObject { ["text"] = EmptyTallyText };
        summary["not_reached"] = JsonNode.Parse(JsonSerializer.Serialize(new
        {
            titles = new[] { "Interference", "Fasteners" },
            text = EmptyNotReachedText,
        }));
        summary["questions"] = JsonNode.Parse(@"{""count"":0,""text"":null,""items"":[]}");
        summary["not_loaded"] = null;
        summary["drawings"] = null;
        summary["bought_parts"] = null;
        ranking["summary"] = summary;
        ranking["groups"] = GroupsSample.EmptyGroups();
        return ranking.ToJsonString();
    }

    public const string EmptyHeadline = "No findings were recorded";

    public const string EmptyTallyText = "Decide 0 · Fix 0 · Verify 0";

    public const string EmptyNotReachedText = "Not reached: Interference, Fasteners";

    /// <summary>
    /// A size-for-size contact list (feature 010's `ReviewSession.contacts`, as the summary maps
    /// it): two contacts in the session's order, the second with a name that carries markup and
    /// a component with no name.
    /// </summary>
    public static JsonNode Contacts(string hostileName) => JsonNode.Parse(JsonSerializer.Serialize(new
    {
        count = 2,
        text = "2 size-for-size contacts",
        items = new object[]
        {
            new
            {
                id = "C-001",
                component_ids = new[] { "cmp:0002", "cmp:0003" },
                names = new[] { "Pin-A-1", "Plate-1" },
                configuration = "Default",
                kind = "zero_volume",
                kind_label = "touching",
                volume_mm3 = 0.0,
                text = "Pin-A-1 and Plate-1",
            },
            new
            {
                id = "C-002",
                component_ids = new[] { "cmp:0004", "cmp:0009" },
                names = new[] { hostileName, null },
                configuration = "Machined",
                kind = "possible_only",
                kind_label = "possible only",
                volume_mm3 = (double?)null,
                text = hostileName + " and cmp:0009",
            },
        },
    }))!;

    private static object Build() => new Dictionary<string, object?>
    {
        { "version", "review_words_v1" },
        { "headline", Headline },
        { "findings", 99 },
        { "issues", 18 },
        {
            "groups", new object[]
            {
                Group("decide", "Decide", 9, "9 need your decision"),
                Group("fix", "Fix", 56, "56 to fix"),
                Group("verify", "Verify", 34, "34 to verify"),
                Group("decided", "Decided", 1, "1 decided"),
            }
        },
        { "tally", new { text = TallyText } },
        { "not_reached", new { titles = new[] { "Fasteners", "Fits and stacks", "Tool access" }, text = NotReachedText } },
        {
            "questions", new
            {
                count = 3,
                text = QuestionsText,
                items = new object[]
                {
                    new
                    {
                        id = QuestionIds[0],
                        source = "model",
                        question = "Is Pin-A-1 meant to be a press fit in Plate-1?",
                        options = new[] { "Press fit", "Slip fit", "Not sure" },
                        blocks = "interfaces.fit",
                        blocks_title = "Fits and stacks",
                        what = "The pin and the bore overlap by 0.012 mm; the drawing that governs the fit was not supplied.",
                        why = "A press fit is intended interference; a slip fit is a defect.",
                        about = new object[]
                        {
                            new { id = "cmp:0002", name = "Pin-A-1" },
                            new { id = "cmp:0003", name = "Plate-1" },
                        },
                    },
                    new
                    {
                        id = QuestionIds[1],
                        source = "model",
                        question = "Which drawing governs Plate-1?",
                        options = new string[0],
                        blocks = "drawing.manufacturing_inputs",
                        blocks_title = "Drawings",
                        what = "No drawing names Plate-1 in its title block.",
                        why = "The tolerances come from the drawing.",
                        about = new object[] { new { id = "cmp:0003", name = "Plate-1" } },
                    },
                    new
                    {
                        id = QuestionIds[2],
                        source = "model",
                        question = "Please confirm which surface of the base plate is the primary datum for the "
                            + "hole pattern, because the extract carries no datum feature symbols and the alignment "
                            + "check cannot choose one without guessing.",
                        options = new string[0],
                        blocks = (string?)null,
                        blocks_title = (string?)null,
                        what = "Please confirm which surface of the base plate is the primary datum for the "
                            + "hole pattern, because the extract carries no datum feature symbols and the alignment "
                            + "check cannot choose one without guessing.",
                        why = "Hole positions are measured from the datum.",
                        about = new object[] { new { id = "doc:0001", name = "bracket.sldasm" }, new { id = "hole:0012", name = (string?)null } },
                    },
                },
            }
        },
        { "not_loaded", new { count = 3, total = 89, text = NotLoadedText } },

        // The backend's whole block; the page reads `text` alone, as it reads `questions` and
        // `not_loaded` (contracts/review-summary.md sections 4 and 5).
        { "drawings", DrawingsLine },

        // Feature 013: `{count, names, maybe_count, maybe_names, text}`, read from the persisted
        // rows; the page reads `text` alone (contracts/part-roles.md section 7).
        {
            "bought_parts", new
            {
                count = 2,
                names = new[] { "FICT-PIN-01.SLDPRT", "FICT-VALVE-ASM.SLDASM" },
                maybe_count = 0,
                maybe_names = new string[0],
                text = BoughtPartsText,
            }
        },
        { "contacts", null },
        { "component_names", ComponentNames },
        { "resume_input_tokens", 405861 },
        { "resume_text", ResumeText },
    };

    /// <summary>One owner group - `SummaryGroup` without the `by_goal` feature 013 removed; the tally line is its words.</summary>
    private static object Group(string kind, string label, int count, string text) =>
        new { kind, label, count, text };
}
