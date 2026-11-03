using System.Collections.Generic;
using System.Linq;
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
///
/// Owner decision 185A (002 T311) adds the `triage` group: the words of a finding's four triage outcomes,
/// the words file's own. Roadmap hole H-g-012 (002 T321) adds `TriageAlreadyRecorded`'s sentence, the words
/// file's own: a second triage refused, the one recorded standing. Owner decision 187A (002 T333) adds the
/// `pass_triage` group, the words file's own: the word of the one outcome a pass takes, the miss. Roadmap hole
/// H-c-008 (002 T353) adds the `no_triage` group, the words file's own: what a flagged finding's card head says
/// until its triage is recorded, for a finding not yet decided and for each decision recorded without one.
///
/// *Changed 2026-11-02 (002 T356; cycle 9's Tier 2 review):* the `no_triage` words are the words file's shorter ones, and
/// the group gains `read_only`, what such a card says while its review is read-only, whatever its decision. That one word
/// is deliberately not the words file's own, which is `undecided`'s: a page that looked up the decision, or `undecided`, on
/// a read-only review would print the same, so the sample's own words tell them apart.
///
/// *Changed 2026-11-02 (002 T365; owner decision 198A):* `deferred`'s words are the words file's new ones, naming Defer again.
///
/// *Changed 2026-11-02 (002 T368; cycle 11's Tier 2 review):* the `note` group, the words file's own: what a card says when a
/// late triage keeps the note recorded first in place of another one the press sent.
///
/// *Changed 2026-11-02 (002 T374; cycle 13's Tier 2 review):* `errors` gains `HttpError`, the words file's own sentence, so a
/// page fact can check that a failed restore read's card says its next step.
///
/// *Changed 2026-11-03 (002 T377; roadmap hole H-c-010):* `errors` gains `OutcomeNeeded`, the words file's own sentence: the
/// decision recorded without a triage, pressed again with no outcome, is refused with words that name the repair.
///
/// *Changed 2026-11-03 (002 T389; cycle 17, roadmap hole H-a-009):* the `first_shown` group, the words file's own: the line a
/// card says when an earlier review of the same document first showed its finding, `{date}` that review's date.
///
/// *Changed 2026-11-03 (007 T088; cycle 18, minutes typed on the Review page):* the `timing` and `timing_form` groups, the
/// words file's own: the minutes form's word for each human timing input, keyed by `TIMING_INPUTS` in their order, and its
/// heading, its button and the line a save leaves; and `errors` gains `InvalidTiming`, the words file's own sentence for a
/// refused save.
///
/// *Changed 2026-11-03 (007 T091; cycle 18's Tier 2 review):* `InvalidTiming`'s sentence is the words file's new one, which
/// names minutes of 0 or more, so it is true of a negative figure too.
///
/// *Changed 2026-11-03 (007 T097; cycle 20, roadmap hole H-a-015):* `timing_form` gains `all_six`, the words file's own line
/// under the form's heading that says to type all six, zero for none.
///
/// *Changed 2026-11-03 (007 T099; cycle 20's Tier 2 review):* `all_six` is the words file's new line, which says to type
/// them once known, and that each replaces what is recorded.
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

    /// <summary>A save whose restart failed (owner decision 150A): the words file's sentence for it.</summary>
    public const string BackendNotRestarted =
        "The settings are saved, but the review backend did not restart with them. Save Settings again to retry the restart.";

    public const string AddInStopping =
        "The settings are saved. The add-in is stopping; nothing else needs doing.";

    /// <summary>The one outcome a pass takes, `wrong`, worded as the miss it is counted as (owner decision 187A).</summary>
    public const string Miss = "wrong: a miss";

    /// <summary>A flagged finding's card head while it is not yet decided and has no triage (roadmap hole H-c-008).</summary>
    public const string NoTriageUndecided = "No triage recorded yet";

    /// <summary>An Accept recorded without a triage: owner decision 185A's late triage is the same decision again.</summary>
    public const string NoTriageAccepted = "No triage recorded yet: pick one, then press Accept again";

    /// <summary>A Reject recorded without a triage, as <see cref="NoTriageAccepted"/>.</summary>
    public const string NoTriageRejected = "No triage recorded yet: pick one, then press Reject again";

    /// <summary>
    /// A Defer recorded without a triage: owner decision 198A's late triage is Defer again, which records the outcome and keeps
    /// the deferral (it said to press Accept or Reject until 2026-11-02, 002 T365).
    /// </summary>
    public const string NoTriageDeferred = "No triage recorded yet: pick one, then press Defer again";

    /// <summary>
    /// Any flagged card of a read-only review with no triage, whatever its decision: no press, since the review takes none
    /// (cycle 9's Tier 2 review). Not the words file's own, which are <see cref="NoTriageUndecided"/>'s (see the summary).
    /// </summary>
    public const string NoTriageReadOnly = "No triage recorded yet (read-only review)";

    /// <summary>
    /// A decision's reply that keeps the note recorded first in place of another one the press sent: a late triage keeps it
    /// (owner decision 198A; cycle 11's Tier 2 review).
    /// </summary>
    public const string NoteNotKept = "The note recorded first stays.";

    /// <summary>
    /// What a card says of a finding an earlier review of the same document first showed, `{date}` that review's date (roadmap
    /// hole H-a-009; 002 cycle 17), which the page fills in as text.
    /// </summary>
    public const string FirstShown = "First shown in the review of {date}.";

    /// <summary>A second triage refused (roadmap hole H-g-012; owner decision 185A): the words file's sentence for it.</summary>
    public const string TriageAlreadyRecorded =
        "That finding already has a triage, and a triage is recorded only once. The one recorded stands and is shown again.";

    /// <summary>A press repeated without an outcome refused (roadmap hole H-c-010): the words file's sentence for it.</summary>
    public const string OutcomeNeeded = "Pick an outcome first, then press the same button again.";

    /// <summary>
    /// The minutes form's word for each human timing input (feature 007, cycle 18), keyed by `TIMING_INPUTS` in their order:
    /// the words file's own.
    /// </summary>
    public static readonly (string Key, string Word)[] Timing =
    {
        ("baseline", "Baseline: a review of this design by hand, without SwReview"),
        ("supervision", "Supervision: your time on the review while it ran"),
        ("verification", "Verification: checking the findings judged right"),
        ("false_alarms", "False alarms: the findings judged wrong"),
        ("setup", "Setup: preparing and starting this review, any rerun included"),
        ("by_hand", "By hand: checking what the review did not reach"),
    };

    /// <summary>The minutes form's heading (feature 007, cycle 18).</summary>
    public const string TimingHeading = "Minutes for this review";

    /// <summary>The line under the heading that says to type all six (feature 007, cycle 20).</summary>
    public const string TimingAllSix = "Type all six once you know them, zero for none. Each replaces what is recorded.";

    /// <summary>The minutes form's button.</summary>
    public const string TimingSave = "Save minutes";

    /// <summary>The one line a save leaves.</summary>
    public const string TimingSaved = "The minutes are recorded.";

    /// <summary>A refused save of the minutes (feature 007, cycle 18): the words file's sentence for its class.</summary>
    public const string InvalidTiming = "Enter each as a number of minutes, 0 or more, then save again.";

    /// <summary>
    /// A run root the run root rule refuses (owner decision 154A): the words file's sentence for it, true since the
    /// reviews of 154A's merge (F1) of a folder name ending in a space or a period too, and since the review of owner
    /// decision 160A of a name Windows cannot use for a folder.
    /// </summary>
    public const string RunRootRefused =
        "Runs are made only in a local folder reached by its own path - not on a network share, not through a link, and with folder names Windows can use: none longer than 255 characters, none with \\ / : * ? \" < > | or a control character, none ending in a space or a period - and the add-in must be able to check that it is one. Choose a local folder for runs in Settings.";

    /// <summary>
    /// A failed read the page names by its status alone, a 500 with no error body among them (002 cycle 13's Tier 2 review):
    /// the words file's sentence for it.
    /// </summary>
    public const string HttpError = "The review backend answered with an error. Try again; if it keeps happening, open the log.";

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
            // Owner decision 185A (002 FR-031): a finding's four triage outcomes, in words.
            "triage", new Dictionary<string, string>
            {
                { "new_and_real", "new and real" },
                { "already_known", "real but already known" },
                { "wrong", "wrong" },
                { "not_worth_flagging", "true but not worth flagging" },
            }
        },
        {
            // Owner decision 187A (002 FR-031): the one outcome a pass takes, the miss, in words.
            "pass_triage", new Dictionary<string, string>
            {
                { "wrong", Miss },
            }
        },
        {
            // Roadmap hole H-c-008 (002 FR-031): a flagged finding's card head until its triage is recorded, in words.
            "no_triage", new Dictionary<string, string>
            {
                { "undecided", NoTriageUndecided },
                { "accepted", NoTriageAccepted },
                { "rejected", NoTriageRejected },
                { "deferred", NoTriageDeferred },
                { "read_only", NoTriageReadOnly },
            }
        },
        {
            // Cycle 11's Tier 2 review (owner decision 198A): a note a late triage did not keep, in words.
            "note", new Dictionary<string, string>
            {
                { "not_kept", NoteNotKept },
            }
        },
        {
            // Cycle 17 (roadmap hole H-a-009): when an earlier review first showed a finding, in words.
            "first_shown", new Dictionary<string, string>
            {
                { "earlier", FirstShown },
            }
        },
        {
            // Feature 007, cycle 18: the minutes form's word for each timing input, in `TIMING_INPUTS`' order.
            "timing", Timing.ToDictionary(entry => entry.Key, entry => entry.Word)
        },
        {
            // Feature 007, cycle 18: the minutes form's heading, its button and the line a save leaves; cycle 20, the line
            // that says to type all six.
            "timing_form", new Dictionary<string, string>
            {
                { "heading", TimingHeading },
                { "all_six", TimingAllSix },
                { "save", TimingSave },
                { "saved", TimingSaved },
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
                { "BackendNotRestarted", BackendNotRestarted },
                { "AddInStopping", AddInStopping },
                { "RunRootRefused", RunRootRefused },
                { "TriageAlreadyRecorded", TriageAlreadyRecorded },
                { "OutcomeNeeded", OutcomeNeeded },
                { "InvalidTiming", InvalidTiming },
                { "HttpError", HttpError },
            }
        },
    };
}
