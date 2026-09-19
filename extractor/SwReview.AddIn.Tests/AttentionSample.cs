using System.Collections.Generic;
using System.Text.Json;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One ranking as `specs/007-attention-policy-gate/contracts/attention.md` section 4 prints it,
/// minus `session_id` - the value of the `attention` key on both check bodies and the whole
/// body of `GET /sessions/{chat_id}/attention` (section 5).
///
/// One fixture for all three pages, because it is one shape on all three: a second copy of it
/// in the Review tests would be the copy that stops matching the check tabs' the first time
/// either is fixed, and the whole point of the section is that the same five rows appear in
/// `report.md`, on both keyless tabs and on the Review tab.
///
/// Two things about the rows are deliberate and load-bearing.
///
/// <b>They are not in any order a page could have produced.</b> The finding ids run
/// F-007, F-008, F-003, F-002, F-004 and the checks are not alphabetical, so a page that
/// sorted - by id, by check or by anything else - renders a different order and the order
/// assertions fail. The ranking is the backend's and the page is a renderer (FR-023).
///
/// <b>There is one row beyond `top_n`.</b> Six rows and `top_n` of five: a page that rendered
/// `rows` whole rather than the first `top_n` shows <see cref="BeyondTopN"/> and fails.
///
/// Every field of the contract is here even though the pages read three of them. A page that
/// started reading `key` or `consequence_class` would then be tested against the real shape
/// rather than against a fixture shaped like the last thing someone needed.
/// </summary>
internal static class AttentionSample
{
    /// <summary>The heading all three surfaces print, the report's own section name.</summary>
    public const string Heading = "Start here";

    /// <summary>
    /// A reason line that carries markup. A reason is assembled by the policy out of a check
    /// id and a finding's own fields, and a finding's fields are written by a language model
    /// reading a reviewed assembly - so the reason line is untrusted text like any other.
    /// </summary>
    public const string HostileReason = "<img src=x onerror=alert(1)>";

    /// <summary>What a run that produced no findings says instead of rows (FR-024).</summary>
    public const string EmptyReason = "Nothing to start with: no findings were recorded.";

    /// <summary>The five rows a page shows, in the order the ranking supplied them.</summary>
    public static readonly string[] ShownFindingIds = { "F-007", "F-008", "F-003", "F-002", "F-004" };

    /// <summary>
    /// Their titles, in the same order. The check tabs render these; the row already carried
    /// them and the pages used to drop them, which is why they are named here rather than
    /// written out again inside <see cref="Build"/>.
    /// </summary>
    public static readonly string[] ShownTitles =
    {
        "The pin interferes with the bore it is pressed into",
        "The second pin interferes with its bore",
        "Two components mate to reference geometry",
        "A sketch is not fully defined",
        "A content feature is in no group",
    };

    /// <summary>Their checks, in the same order.</summary>
    public static readonly string[] ShownChecks =
    {
        "interference.static",
        "interference.static",
        "rms.assembly.mates_to_reference_geometry",
        "rms.sketches.fully_defined",
        "rms.grouping.all_features_in_a_group",
    };

    /// <summary>Their reasons, in the same order.</summary>
    public static readonly string[] ShownReasons =
    {
        "needs your judgement",
        "needs your judgement",
        "rebuild breaker, demonstrated, 2 components",
        "rebuild breaker, demonstrated",
        "discipline, demonstrated",
    };

    /// <summary>The sixth row, which is beyond `top_n` and must not be rendered.</summary>
    public const string BeyondTopN = "F-009";

    /// <summary>The ranking with rows, as a JSON literal a page test can embed.</summary>
    /// <param name="firstReason">
    /// Replaces the first row's reason, for the injection tests.
    /// </param>
    public static string Json(string? firstReason = null) =>
        JsonSerializer.Serialize(Ranking(firstReason));

    /// <summary>
    /// The same ranking as an object, for the two check samples, which carry it as their
    /// `attention` key rather than as a body of their own (contract section 5).
    /// </summary>
    public static object Ranking(string? firstReason = null) =>
        Build(firstReason ?? ShownReasons[0]);

    /// <summary>
    /// The ranking a run that produced no findings answers with: no rows, and the sentence
    /// that says why (contract section 3, "The empty case is words").
    /// </summary>
    public static string EmptyJson(string emptyReason = EmptyReason) =>
        JsonSerializer.Serialize(EmptyRanking(emptyReason));

    /// <summary>The empty ranking as an object.</summary>
    public static object EmptyRanking(string emptyReason = EmptyReason) => new
    {
        policy_version = "attention_policy_v1",
        rows = new object[0],
        top_n = 5,
        not_amplified = NotAmplified(0),
        coverage = Coverage(),
        empty_reason = emptyReason,
    };

    private static object Build(string firstReason) => new
    {
        policy_version = "attention_policy_v1",
        rows = new object[]
        {
            Row(
                "F-007",
                "interference.static",
                ShownTitles[0],
                "demonstrated",
                "medium",
                new[] { "cmp:0002", "cmp:0003" },
                "interface",
                judgement: 0,
                reason: firstReason),
            Row(
                "F-008",
                "interference.static",
                ShownTitles[1],
                "demonstrated",
                "medium",
                new[] { "cmp:0004", "cmp:0005" },
                "interface",
                judgement: 0,
                reason: ShownReasons[1]),
            Row(
                "F-003",
                "rms.assembly.mates_to_reference_geometry",
                ShownTitles[2],
                "demonstrated",
                "medium",
                new[] { "cmp:0001", "cmp:0002" },
                "rebuild_breaker",
                judgement: 1,
                reason: ShownReasons[2]),
            Row(
                "F-002",
                "rms.sketches.fully_defined",
                ShownTitles[3],
                "demonstrated",
                "medium",
                new[] { "cmp:0002" },
                "rebuild_breaker",
                judgement: 1,
                reason: ShownReasons[3]),
            Row(
                "F-004",
                "rms.grouping.all_features_in_a_group",
                ShownTitles[4],
                "demonstrated",
                "medium",
                new[] { "cmp:0002" },
                "discipline",
                judgement: 1,
                reason: ShownReasons[4]),
            Row(
                BeyondTopN,
                "rms.folders.present",
                "A method group folder is missing",
                "suspected",
                "low",
                new[] { "cmp:0002" },
                "hygiene",
                judgement: 1,
                reason: "hygiene, suspected"),
        },
        top_n = 5,
        not_amplified = NotAmplified(1),
        coverage = Coverage(),
        empty_reason = (string?)null,
    };

    private static object Row(
        string findingId,
        string check,
        string title,
        string status,
        string severity,
        string[] componentIds,
        string consequenceClass,
        int judgement,
        string reason) => new
    {
        finding_id = findingId,
        member_finding_ids = new[] { findingId },
        check,
        title,
        status,
        severity,
        component_ids = componentIds,
        consequence_class = consequenceClass,

        // The nine key values the row was placed by, so the rank is arguable by pointing at a
        // line (contract section 1). A dictionary rather than an anonymous object because two
        // of the names - `check` and `status` - are already parameters here.
        key = new Dictionary<string, object>
        {
            { "suppressed", 0 },
            { "judgement", judgement },
            { "consequence", 1 },
            { "status", 0 },
            { "severity", 1 },
            { "reach", componentIds.Length > 3 ? 3 : componentIds.Length },
            { "carried", 0 },
            { "check", check },
            { "finding_id", findingId },
        },
        reason,
    };

    private static object NotAmplified(int beyondTopN) => new
    {
        total = beyondTopN,
        checked_within_scope = 0,
        dispositioned = 0,
        info = 0,
        beyond_top_n = beyondTopN,
    };

    private static object Coverage() => new
    {
        // `checked` is a C# keyword and the contract's field name; the escape is the
        // identifier and the serialized property is still `checked`.
        @checked = 5,
        skipped = 11,
        unresolved = 39,
        failed = 0,
        out_of_scope = 7,
        not_closed = new object[]
        {
            new
            {
                item = "fasteners",
                reason = "list_fasteners returned zero instances, so no screw or bolt joint "
                    + "could be checked.",
            },
        },
        open_evidence_requests = 3,
        rules = new { unresolved = 23, skipped = 11 },
    };
}
