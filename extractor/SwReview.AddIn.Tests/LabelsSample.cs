using System.Collections.Generic;
using System.Text.Json;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One `GET /labels` body as `specs/009-engineer-workspace/data-model.md` section 7 prints it:
/// the words file's `labels` block - status, severity, bucket, evidence status, contact kind and
/// one next-step sentence per error class. Hand-built, so the page tests of User Story 7 run
/// before the py lane's T060 serves it.
///
/// Two of its words are deliberately not the data model's own. The severity labels differ from
/// the raw tokens ("medium severity" for `medium`), so a page that printed the token where it
/// should print the label fails; and the evidence status `open` carries markup, because a label
/// is backend text like any other and reaches the screen as characters (FR-029).
///
/// Feature 013 adds the `source` group (T103): the words for who wrote a record, which the page prints on a
/// finding's line, a question's pager line, an evidence record's head, a goal's recorded sentence
/// and a coverage row whenever the body states its source (contracts/sources.md section 2).
/// </summary>
internal static class LabelsSample
{
    public const string HostileOpen = "<img src=x onerror=alert(1)>waiting for you";

    /// <summary>`labels.source`'s two words (feature 013, contracts/sources.md section 2).</summary>
    public const string SourceCode = "Checked by code";

    public const string SourceModel = "AI guidance";

    public const string TurnRunning = "A review turn is still running. Wait for it to finish, or press Stop.";

    public const string NoDocument = "Open the part or assembly you want reviewed, then press Review.";

    public const string DrawingActive = "Keep the drawing open in SOLIDWORKS and activate the part or assembly it documents. Press Review with that model active; Review reads open drawings whose views show the model.";

    public const string AlreadyAnswered = "That finding was decided in another window. Reload the review to see it.";

    public const string InvalidSettings = "Check the provider, the model and the effort, then save again.";

    public static string Json() => JsonSerializer.Serialize(Value());

    public static object Value() => new Dictionary<string, object>
    {
        { "version", "review_words_v1" },
        {
            "status", new Dictionary<string, string>
            {
                { "demonstrated", "demonstrated" },
                { "suspected", "suspected" },
                { "unresolved", "unresolved" },
                { "checked_within_scope", "checked within scope" },
            }
        },
        {
            "severity", new Dictionary<string, string>
            {
                { "high", "high severity" },
                { "medium", "medium severity" },
                { "low", "low severity" },
                { "info", "for information" },
            }
        },
        {
            "bucket", new Dictionary<string, string>
            {
                { "checked", "checked" },
                { "skipped", "skipped" },
                { "unresolved", "evidence missing" },
                { "failed", "a check failed" },
                { "out_of_scope", "out of scope" },
            }
        },
        {
            "evidence_status", new Dictionary<string, string>
            {
                { "open", HostileOpen },
                { "answered", "answered" },
            }
        },
        {
            "contact_kind", new Dictionary<string, string>
            {
                { "zero_volume", "touching" },
                { "possible_only", "possible only" },
                { "thread_model", "thread model" },
            }
        },
        {
            // Feature 013 (contracts/sources.md section 2): who wrote a record, in words.
            "source", new Dictionary<string, string>
            {
                { "code", SourceCode },
                { "model", SourceModel },
            }
        },
        {
            "errors", new Dictionary<string, string>
            {
                { "TurnRunning", TurnRunning },
                { "NoDocument", NoDocument },
                { "DrawingActive", DrawingActive },
                { "AlreadyAnswered", AlreadyAnswered },
                { "InvalidSettings", InvalidSettings },
            }
        },
    };
}
