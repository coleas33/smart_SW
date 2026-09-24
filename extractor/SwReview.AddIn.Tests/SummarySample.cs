using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One `ReviewRanking` as `specs/009-engineer-workspace/contracts/review-summary.md` prints it:
/// <see cref="AttentionSample"/>'s ranking plus the `summary` the backend computes beside it
/// (data-model section 2). Hand-built, so the page tests of User Stories 3 to 7 run before the
/// backend that computes it has landed (tasks.md: "its page tasks need only the contract").
///
/// What is deliberate about it:
///
/// <b>Every number is one no page could have computed.</b> The groups' counts, the goals'
/// states and the headline do not follow from <see cref="AttentionSample"/>'s six rows: a page
/// that counted anything prints a different number and fails. The page prints and slices.
///
/// <b>Every goal state is here</b>, and the goals come in the words file's order (nine goals,
/// modelling practice the ninth, contracts/review-summary.md section 3), one with a hostile
/// recorded sentence - a close-out row's `reason` is written by the model and travels verbatim.
///
/// <b>The three questions are the three shapes</b> contracts/questions.md names: a short form
/// with offered answers and the goal it blocks, a short form answered in free text, and an older
/// request with only its long `what`.
///
/// <b>The drawing line is there</b> (feature 009 T086, the owner's decision 10A, 2026-09-23): a
/// summary from this build carries one line about drawings, and a test of an older backend
/// removes it.
/// </summary>
internal static class SummarySample
{
    public const string Headline = "99 findings in 18 issues";

    public const string QuestionsText = "3 questions for you";

    public const string NotLoadedText = "3 of 89 parts not loaded";

    /// <summary>
    /// The summary's one line about drawings (feature 009 T086, the owner's decision 10A): the
    /// backend's words, which no page could compose from the ranking beside them.
    /// </summary>
    public const string DrawingsText = "2 drawings read with this review; 1 drawing beside a part was not opened";

    public const string ResumeText =
        "Sending resumes the review once. Its last round sent 405,861 input tokens.";

    /// <summary>A recorded sentence that carries markup, on the fits-and-stacks goal.</summary>
    public const string HostileDetail = "<img src=x onerror=alert(1)></details><script>alert(2)</script>";

    /// <summary>The group lines in the order the backend supplies them: label, text, "title count".</summary>
    public static readonly (string Kind, string Label, string Text, string[] Goals)[] Groups =
    {
        ("decide", "Decide", "9 need your decision", new[] { "Interference 6", "Hole alignment 3" }),
        ("fix", "Fix", "56 to fix", new[] { "Modelling practice 51", "Hygiene 5" }),
        ("verify", "Verify", "34 to verify", new[] { "Drawings 20", "Fasteners 14" }),
        ("decided", "Decided", "1 decided", new[] { "Interference 1" }),
    };

    /// <summary>The goal lines in the words file's order: title, state, state label, reason, detail.</summary>
    public static readonly (string Goal, string Title, string State, string Label, string? Reason, string? Detail)[] Goals =
    {
        ("interference", "Interference", "issues", "issues found", null, null),
        ("fasteners", "Fasteners", "not_reached", "not reached", "evidence missing",
            "list_fasteners returned zero instances, so no screw or bolt joint could be checked."),
        ("hole_alignment", "Hole alignment", "checked", "checked, no issue", null, null),
        ("fits_and_stacks", "Fits and stacks", "not_reached", "not reached", "a check failed", HostileDetail),
        ("tool_access", "Tool access", "not_reached", "not reached", "no check ran", null),
        ("mass_and_material", "Mass and material", "not_applicable", "not applicable", "out of scope", null),
        ("hygiene", "Hygiene", "issues", "issues found", null, null),
        ("drawings", "Drawings", "issues", "issues found", null, null),
        ("modelling_practice", "Modelling practice", "issues", "issues found", null, null),
    };

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

    /// <summary>The ranking with its summary, as a JSON literal a page test can embed.</summary>
    /// <param name="change">Edits the summary object before it is serialized.</param>
    public static string Json(Action<JsonObject>? change = null) => Ranking(change).ToJsonString();

    /// <summary>The ranking with its summary, as a mutable node.</summary>
    public static JsonObject Ranking(Action<JsonObject>? change = null)
    {
        JsonObject ranking = JsonNode.Parse(AttentionSample.Json())!.AsObject();
        JsonObject summary = Summary();
        change?.Invoke(summary);
        ranking["summary"] = summary;
        return ranking;
    }

    /// <summary>The summary alone, as a mutable node.</summary>
    public static JsonObject Summary() => JsonNode.Parse(JsonSerializer.Serialize(Build()))!.AsObject();

    /// <summary>
    /// The summary of a review that recorded nothing: the headline says so in words, the three
    /// owner groups are there at zero, and every goal line is still there (review-summary.md
    /// section 6).
    /// </summary>
    public static string EmptyJson()
    {
        JsonObject ranking = JsonNode.Parse(AttentionSample.EmptyJson())!.AsObject();
        JsonObject summary = Summary();
        summary["headline"] = "No findings were recorded";
        summary["findings"] = 0;
        summary["issues"] = 0;
        summary["groups"] = JsonNode.Parse(JsonSerializer.Serialize(new object[]
        {
            Group("decide", "Decide", 0, "0 need your decision"),
            Group("fix", "Fix", 0, "0 to fix"),
            Group("verify", "Verify", 0, "0 to verify"),
        }));
        summary["questions"] = JsonNode.Parse(@"{""count"":0,""text"":null,""items"":[]}");
        summary["not_loaded"] = null;
        summary["drawings"] = null;
        ranking["summary"] = summary;
        return ranking.ToJsonString();
    }

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
                Group("decide", "Decide", 9, "9 need your decision", ("interference", "Interference", 6), ("hole_alignment", "Hole alignment", 3)),
                Group("fix", "Fix", 56, "56 to fix", ("modelling_practice", "Modelling practice", 51), ("hygiene", "Hygiene", 5)),
                Group("verify", "Verify", 34, "34 to verify", ("drawings", "Drawings", 20), ("fasteners", "Fasteners", 14)),
                Group("decided", "Decided", 1, "1 decided", ("interference", "Interference", 1)),
            }
        },
        { "modelling_practice", null },
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

        // The page reads `text` alone, as it reads `questions` and `not_loaded`: the other members
        // of the line are the backend's (contracts/review-summary.md section 4).
        { "drawings", new { text = DrawingsText } },
        {
            "goals", Array.ConvertAll(Goals, line => (object)new Dictionary<string, object?>
            {
                { "goal", line.Goal },
                { "title", line.Title },
                { "state", line.State },
                { "state_label", line.Label },
                { "findings", line.State == "issues" ? 3 : 0 },
                { "reason", line.Reason },
                { "detail", line.Detail },
            })
        },
        { "contacts", null },
        { "component_names", ComponentNames },
        { "resume_input_tokens", 405861 },
        { "resume_text", ResumeText },
    };

    private static object Group(string kind, string label, int count, string text, params (string Goal, string Title, int Count)[] goals) =>
        new
        {
            kind,
            label,
            count,
            text,
            by_goal = Array.ConvertAll(goals, goal => (object)new { goal = goal.Goal, title = goal.Title, count = goal.Count }),
        };
}
