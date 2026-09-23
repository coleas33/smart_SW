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
/// </summary>
internal static class LabelsSample
{
    public const string HostileOpen = "<img src=x onerror=alert(1)>waiting for you";

    public const string TurnRunning = "A review turn is still running. Wait for it to finish, or press Stop.";

    public const string NoDocument = "Open the part or assembly you want reviewed, then press Review.";

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
            "errors", new Dictionary<string, string>
            {
                { "TurnRunning", TurnRunning },
                { "NoDocument", NoDocument },
                { "AlreadyAnswered", AlreadyAnswered },
                { "InvalidSettings", InvalidSettings },
            }
        },
    };
}
