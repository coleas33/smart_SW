using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One `FindingsByType` as `specs/013-engineer-first-review/contracts/grouped-list.md` section 3
/// prints it: the `groups` member of the Review tab's ranking (`ReviewRanking.groups`). Hand-built
/// from the contract, so the page tests of feature 013's grouped list run before the backend's
/// `report/finding_groups.py` (013 T048) lands; the pane fixture carries the backend's own once
/// 013 T056 regenerates it.
///
/// Its rows are <see cref="AttentionSample"/>'s findings, with the same titles, plus the ones a
/// grouped list shows that a five-row Start here never did. What is deliberate about it:
///
/// <b>No order a page could have produced.</b> The groups come in the words file's fixed order,
/// with no Standards and no Mass and material group (a group with neither a row nor a goal is left
/// out by the backend); within Interference and fit the decided F-007 comes after F-008 (the
/// backend moves decided rows to the end of their group), so a page that sorted by id puts them the
/// other way round. F-009's row lists its members F-009, F-010, F-011, and the stream delivers
/// F-011 before F-010, so a page that kept arrival order inside a row fails.
///
/// <b>Every count, plural and word is the backend's.</b> Each group's `text`, each row's
/// `tail_text`, `reach_text` and `chip`, and `hide_card_title` are fields the page prints or
/// honours. The Hygiene row's words deliberately disagree with its members and components
/// (<see cref="DisagreeingTail"/>, <see cref="DisagreeingReach"/>), so a page that counted prints
/// something else and fails.
///
/// <b>The edges.</b> Fasteners has goals and no row, so it prints its goals' state; Modelling
/// practice arrives collapsed; the checked fold holds two passes, one inside an accepted exception;
/// Other checks is last; one row's title carries markup; and <see cref="UnnamedCard"/> is a finding
/// the stream delivers that no row names, which must stay on the page.
/// </summary>
internal static class GroupsSample
{
    /// <summary>The groups, in the order the backend supplies them.</summary>
    public static readonly string[] GroupIds = { "interference_fit", "fasteners", "drawings", "modelling_practice", "hygiene", "other" };

    public static readonly string[] GroupTitles =
        { "Interference and fit", "Fasteners", "Drawings", "Modelling practice", "Hygiene", "Other checks" };

    /// <summary>Each group's `text`: its findings in words, or - a group with no row - its first goal's state.</summary>
    public static readonly string[] GroupTexts =
        { "2 findings · 1 decided", "not reached · evidence missing", "1 finding", "6 findings", "2 findings", "1 finding" };

    /// <summary>Whether each group arrives open: Modelling practice arrives collapsed (research R2.15).</summary>
    public static readonly bool[] GroupOpen = { true, true, true, false, true, true };

    /// <summary>Each group's rows, by survivor, in the supplied order.</summary>
    public static readonly string[][] GroupRowIds =
    {
        new[] { "F-008", "F-007" },
        new string[0],
        new[] { "F-017" },
        new[] { "F-003", "F-002", "F-004", "F-009" },
        new[] { "F-013" },
        new[] { "F-014" },
    };

    /// <summary>The cards inside each group, row by row, each row's members in its supplied order.</summary>
    public static readonly string[][] GroupCardIds =
    {
        new[] { "F-008", "F-007" },
        new string[0],
        new[] { "F-017" },
        new[] { "F-003", "F-002", "F-004", "F-009", "F-010", "F-011" },
        new[] { "F-013", "F-016" },
        new[] { "F-014" },
    };

    /// <summary>The goal lines under Interference and fit, in goal order: titles, state labels and classes.</summary>
    public static readonly string[] InterferenceGoalTitles = { "Interference", "Hole alignment", "Fits and stacks" };

    public static readonly string[] InterferenceGoalStates = { "issues found", "checked, no issue", "not reached" };

    public static readonly string[] InterferenceGoalClasses =
        { "summary-goal goal-issues", "summary-goal goal-checked", "summary-goal goal-not_reached" };

    /// <summary>The goal lines under Fasteners, a group with no row.</summary>
    public static readonly string[] FastenersGoalTitles = { "Fasteners", "Tool access" };

    /// <summary>Fasteners' first goal's recorded sentence, behind its fold.</summary>
    public const string FastenersDetail = "list_fasteners returned zero instances, so no screw or bolt joint could be checked.";

    /// <summary>The row whose members and words disagree on purpose: two members, one component.</summary>
    public const string DisagreeingRow = "F-013";

    /// <summary>The Hygiene row's `tail_text`: not its two members - the page prints it anyway.</summary>
    public const string DisagreeingTail = "×5";

    /// <summary>The Hygiene row's `reach_text`: not its one component - printed anyway.</summary>
    public const string DisagreeingReach = "reaches 4 components";

    /// <summary>The folded row of Modelling practice, its words, and its members in the supplied order.</summary>
    public const string FoldedRow = "F-009";

    public static readonly string[] FoldedMembers = { "F-009", "F-010", "F-011" };

    public const string FoldedTail = "×3";

    /// <summary>The model-written row (a drawing finding the model recorded) and the chip the backend gave it.</summary>
    public const string ModelRow = "F-017";

    public const string ModelChip = "AI guidance";

    /// <summary>A row title that carries markup; the row is a finding title a model wrote.</summary>
    public const string HostileTitle = "<img src=x onerror=alert(11)></summary><script>alert(12)</script>";

    /// <summary>The row whose title carries markup.</summary>
    public const string HostileRow = "F-014";

    /// <summary>The checked fold: its words and its rows, one inside an accepted exception.</summary>
    public const string CheckedTitle = "Checked, no issue";

    public const string CheckedText = "2 findings";

    public static readonly string[] CheckedRowIds = { "F-012", "F-015" };

    public const string ExceptionTail = "within an accepted exception";

    /// <summary>A finding the stream delivers that no row names: it stays in the holding list.</summary>
    public const string UnnamedCard = "F-099";

    /// <summary>Every finding card the review's stream delivers, in the order it delivers them.</summary>
    public static readonly string[] ArrivalOrder =
    {
        "F-002", "F-003", "F-004", "F-007", "F-008", "F-009", "F-011", "F-010", "F-012", "F-013",
        "F-014", "F-015", "F-016", "F-017", UnnamedCard,
    };

    /// <summary>The survivor of every row, in document order: every group's rows, then the checked fold's.</summary>
    public static string[] EveryRowId() => GroupRowIds.SelectMany(rows => rows).Concat(CheckedRowIds).ToArray();

    /// <summary>The `groups` member of a ranking, as a fresh node.</summary>
    public static JsonNode Groups() => JsonNode.Parse(JsonSerializer.Serialize(Build()))!;

    /// <summary>
    /// The `groups` of a review that recorded nothing: the groups that have goals, each printing
    /// its goals' state, no row anywhere, and no checked fold.
    /// </summary>
    public static JsonNode EmptyGroups() => JsonNode.Parse(JsonSerializer.Serialize(new
    {
        version = 1,
        groups = new object[]
        {
            Group("interference_fit", GroupTitles[0], true, 0, 0, "not reached · evidence missing", new object[0],
                Goal("interference", "Interference", "not_reached", "not reached", "evidence missing", null)),
            Group("fasteners", GroupTitles[1], true, 0, 0, "not reached · evidence missing", new object[0],
                Goal("fasteners", "Fasteners", "not_reached", "not reached", "evidence missing", null)),
        },
        @checked = (object?)null,
    }))!;

    /// <summary>
    /// A finding card's body, as the stream delivers it, for every id this sample names: its check
    /// and display title are the ones its row carries.
    /// </summary>
    public static string Finding(string id) => JsonSerializer.Serialize(new
    {
        id,
        check = Checks[id],
        title = TitleOf(id),
        status = CheckedRowIds.Contains(id) ? "checked_within_scope" : "demonstrated",
        severity = "medium",
        component_ids = new[] { "cmp:0002" },
        observed = "Observed for " + id + ".",
    });

    /// <summary>The display title of every card and row: <see cref="AttentionSample"/>'s where it names one.</summary>
    public static string TitleOf(string id)
    {
        int shown = System.Array.IndexOf(AttentionSample.ShownFindingIds, id);
        if (shown >= 0)
        {
            return AttentionSample.ShownTitles[shown];
        }

        if (id == AttentionSample.BeyondTopN)
        {
            return AttentionSample.BeyondTopNTitle;
        }

        return id == HostileRow ? HostileTitle : "Finding " + id;
    }

    /// <summary>The check of every card this sample delivers, survivors and members alike: one table for rows and cards.</summary>
    private static readonly Dictionary<string, string> Checks = new Dictionary<string, string>
    {
        { "F-002", "rms.sketches.fully_defined" },
        { "F-003", "rms.assembly.mates_to_reference_geometry" },
        { "F-004", "rms.grouping.all_features_in_a_group" },
        { "F-007", "interference.static" },
        { "F-008", "interference.static" },
        { "F-009", "rms.folders.present" },
        { "F-010", "rms.folders.present" },
        { "F-011", "rms.folders.present" },
        { "F-012", "interference.static" },
        { "F-013", "hygiene.revision_present" },
        { "F-014", "vendor.fict_rule" },
        { "F-015", "hole.alignment" },
        { "F-016", "hygiene.revision_present" },
        { "F-017", "drawing.manufacturing_inputs" },
        { UnnamedCard, "interference.static" },
    };

    private static object Build() => new
    {
        version = 1,
        groups = new object[]
        {
            Group("interference_fit", GroupTitles[0], true, 2, 1, GroupTexts[0],
                new object[]
                {
                    Row("F-008", new[] { "F-008" }, new[] { "cmp:0004", "cmp:0005" }, "interface", 0, reach: "reaches 2 components"),
                    Row("F-007", new[] { "F-007" }, new[] { "cmp:0002", "cmp:0003" }, "interface", 0, reach: "reaches 2 components"),
                },
                Goal("interference", "Interference", "issues", "issues found", null, null),
                Goal("hole_alignment", "Hole alignment", "checked", "checked, no issue", null, null),
                Goal("fits_and_stacks", "Fits and stacks", "not_reached", "not reached", "a check failed", SummarySample.HostileDetail)),
            Group("fasteners", GroupTitles[1], true, 0, 0, GroupTexts[1], new object[0],
                Goal("fasteners", "Fasteners", "not_reached", "not reached", "evidence missing", FastenersDetail),
                Goal("tool_access", "Tool access", "not_reached", "not reached", "no check ran", null)),
            Group("drawings", GroupTitles[2], true, 1, 0, GroupTexts[2],
                new object[]
                {
                    Row(ModelRow, new[] { ModelRow }, new string[0], "manufacturing", 1, source: "model", chip: ModelChip),
                },
                Goal("drawings", "Drawings", "issues", "issues found", null, null)),
            Group("modelling_practice", GroupTitles[3], false, 6, 0, GroupTexts[3],
                new object[]
                {
                    Row("F-003", new[] { "F-003" }, new[] { "cmp:0001", "cmp:0002" }, "rebuild_breaker", 1, reach: "reaches 2 components"),
                    Row("F-002", new[] { "F-002" }, new[] { "cmp:0002" }, "rebuild_breaker", 1, reach: "reaches 1 component"),
                    Row("F-004", new[] { "F-004" }, new[] { "cmp:0002" }, "discipline", 1, reach: "reaches 1 component"),
                    Row(FoldedRow, FoldedMembers, new[] { "cmp:0002" }, "hygiene", 1, tail: FoldedTail, reach: "reaches 1 component"),
                },
                Goal("modelling_practice", "Modelling practice", "issues", "issues found", null, null)),
            Group("hygiene", GroupTitles[4], true, 2, 0, GroupTexts[4],
                new object[]
                {
                    Row(DisagreeingRow, new[] { DisagreeingRow, "F-016" }, new[] { "cmp:0003" }, "hygiene", 1,
                        tail: DisagreeingTail, reach: DisagreeingReach),
                },
                Goal("hygiene", "Hygiene", "issues", "issues found", null, null)),
            Group("other", GroupTitles[5], true, 1, 0, GroupTexts[5],
                new object[] { Row(HostileRow, new[] { HostileRow }, new string[0], "unclassified", 1) }),
        },
        @checked = new
        {
            title = CheckedTitle,
            open = false,
            findings = 2,
            text = CheckedText,
            rows = new object[]
            {
                Row("F-012", new[] { "F-012" }, new[] { "cmp:0006" }, "interface", 1,
                    tail: ExceptionTail, reach: "reaches 1 component", status: "checked_within_scope"),
                Row("F-015", new[] { "F-015" }, new[] { "cmp:0007" }, "interface", 1,
                    reach: "reaches 1 component", status: "checked_within_scope"),
            },
        },
    };

    private static object Group(string id, string title, bool open, int findings, int decided, string text, object[] rows, params object[] goals) =>
        new { id, title, open, findings, decided, text, rows, goals };

    /// <summary>
    /// One `GroupRow`: every `AttentionRow` field (feature 007's contract section 4) plus the five
    /// the grouped view adds. `hide_card_title` is the backend's: true exactly on a single-member row.
    /// </summary>
    private static object Row(
        string survivor,
        string[] members,
        string[] components,
        string consequence,
        int judgement,
        string? tail = null,
        string? reach = null,
        string source = "code",
        string? chip = null,
        string status = "demonstrated") => new Dictionary<string, object?>
    {
        { "finding_id", survivor },
        { "member_finding_ids", members },
        { "check", Checks[survivor] },
        { "title", TitleOf(survivor) },
        { "status", status },
        { "severity", "medium" },
        { "component_ids", components },
        { "consequence_class", consequence },
        {
            "key", new Dictionary<string, object>
            {
                { "suppressed", status == "checked_within_scope" ? 1 : 0 },
                { "judgement", judgement },
                { "consequence", 1 },
                { "status", 0 },
                { "severity", 1 },
                { "reach", components.Length > 3 ? 3 : components.Length },
                { "carried", 0 },
                { "check", Checks[survivor] },
                { "finding_id", survivor },
            }
        },
        { "reason", judgement == 0 ? "needs your judgement" : consequence.Replace('_', ' ') + ", " + status },
        { "source", source },
        { "tail_text", tail },
        { "reach_text", reach },
        { "hide_card_title", members.Length == 1 },
        { "chip", chip },
    };

    /// <summary>One `GoalLine` (feature 009's data model section 2), as a group carries it.</summary>
    private static object Goal(string goal, string title, string state, string label, string? reason, string? detail) =>
        new Dictionary<string, object?>
        {
            { "goal", goal },
            { "title", title },
            { "state", state },
            { "state_label", label },
            { "findings", state == "issues" ? 2 : 0 },
            { "reason", reason },
            { "detail", detail },
        };
}
