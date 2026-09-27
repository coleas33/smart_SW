using System;
using System.Collections.Generic;
using System.Globalization;

namespace SwReview.Extractor.Rms;

/// <summary>
/// 004 T167 (default taken 2026-09-26, the owner may revise; research R13.1): what the one
/// end-of-session routine, <c>SwBridgeDispatcher.EndRemodelSession</c>, did - whatever ended the
/// session: <c>remodel.close</c>, a tool-service re-attach or an add-in unload
/// (contracts/bridge-remodel.md, "Ending a session"); and, since 004 T177, what a
/// <c>remodel.open</c> that failed after it changed the settings did on its way out, by the same
/// clean-up rules (<see cref="ReasonOpenFailed"/>).
///
/// It is a record of facts about the seat, never a guess: whether the target verified (and which
/// check failed when it did not), whether the tag came off, whether the copy was closed, which of
/// the four settings still hold the run's value, and one sentence per failure. The routine never
/// saves and never deletes, so there is nothing about the file here.
///
/// Three readers: <c>remodel.close</c>'s answer (<see cref="Fields"/> is its <c>detail</c>), the
/// tool service's teardown line (the same fields, and the failures), and the pane, which is told
/// through <c>BridgeServices.RemodelSessionEnded</c> and names what was left in plain words
/// (T167's pane words). <see cref="RunDirectory"/> and <see cref="CopyPath"/> are for the logs
/// only; the pane names no path.
/// </summary>
public sealed class RemodelSessionEnd
{
    /// <summary>The reason <c>remodel.close</c> ends a session with.</summary>
    public const string ReasonClose = "remodel.close";

    /// <summary>
    /// The reason the tool service's own disposal ends one with - a re-attach and an unload
    /// alike (default taken 2026-09-27, the owner may revise): which of the two it was is a fact
    /// about the add-in, not the bridge, and the teardown line records the thread it ran on.
    /// </summary>
    public const string ReasonToolServiceStopped = "tool_service_stopped";

    /// <summary>
    /// 004 T177 (default taken 2026-09-27, the owner may revise; research R14.3): the reason a
    /// <c>remodel.open</c> that failed after it changed the settings ends the session it was making,
    /// by the routine's clean-up rules - no verification (there may be no scope yet), the copy
    /// closed unsaved and deleted, the settings put back. <see cref="Verified"/> and
    /// <see cref="TagRemoved"/> are false for it; <see cref="CopyClosed"/> is true when the copy was
    /// never made, and when no handle came back and SOLIDWORKS then answered that nothing is open at
    /// the copy's path (004 T183).
    /// </summary>
    public const string ReasonOpenFailed = "remodel.open";

    private static readonly string[] Nothing = new string[0];

    public RemodelSessionEnd(
        string reason,
        string runDirectory,
        string copyPath,
        bool verified,
        RemodelTargetCheck? failedCheck,
        bool tagRemoved,
        bool copyClosed,
        IReadOnlyList<string> settingsOutstanding,
        IReadOnlyList<string> failures)
    {
        Reason = RequiredReason(reason);
        HadSession = true;
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        CopyPath = copyPath ?? throw new ArgumentNullException(nameof(copyPath));
        Verified = verified;
        FailedCheck = failedCheck;
        TagRemoved = tagRemoved;
        CopyClosed = copyClosed;
        SettingsOutstanding = settingsOutstanding ?? throw new ArgumentNullException(nameof(settingsOutstanding));
        Failures = failures ?? throw new ArgumentNullException(nameof(failures));
    }

    private RemodelSessionEnd(string reason)
    {
        Reason = RequiredReason(reason);
        HadSession = false;
        SettingsOutstanding = Nothing;
        Failures = Nothing;
    }

    /// <summary>
    /// What ended the session: <see cref="ReasonClose"/>, <see cref="ReasonToolServiceStopped"/> or
    /// <see cref="ReasonOpenFailed"/>.
    /// </summary>
    public string Reason { get; }

    /// <summary>
    /// False when there was no session to end, in which case the routine called nothing - no
    /// SOLIDWORKS member and no gate - and every other fact here is empty.
    /// </summary>
    public bool HadSession { get; }

    /// <summary>The run's folder, for the teardown line in its <c>remodel.log</c>; null with no session.</summary>
    public string? RunDirectory { get; }

    /// <summary>The copy, for the logs only; null with no session.</summary>
    public string? CopyPath { get; }

    /// <summary>Whether <c>VerifyTarget</c> passed. When it did not, nothing was closed.</summary>
    public bool Verified { get; }

    /// <summary>The check that failed, or null when the verification passed or could not say which.</summary>
    public RemodelTargetCheck? FailedCheck { get; }

    /// <summary>
    /// Whether the session tag came off the open document, by SOLIDWORKS's own answer (004 T179):
    /// <c>Delete2</c> answered <c>swCustomInfoDeleteResult_OK</c>. Any other answer is false, and
    /// <see cref="Failures"/> names it.
    /// </summary>
    public bool TagRemoved { get; }

    /// <summary>
    /// Whether the copy is known to be closed (004 T179): <c>CloseDoc</c> returned and SOLIDWORKS
    /// then answered that it has no document open at the copy's path. False means it may still be
    /// open - the close threw, SOLIDWORKS still has it open, or that could not be read - and
    /// <see cref="Failures"/> says which. For a failed open's unwind it is also true when the copy
    /// was never made, so nothing was opened, and when no document handle came back and SOLIDWORKS
    /// then answered that it has no document open at the copy's path (004 T183); a read that could
    /// not answer is false.
    /// </summary>
    public bool CopyClosed { get; }

    /// <summary>
    /// The settings still holding the run's value, by the names
    /// <see cref="RemodelSystemToggles.Outstanding"/> gives them; empty when all four are back.
    /// </summary>
    public IReadOnlyList<string> SettingsOutstanding { get; }

    /// <summary>How many of the four settings are back; zero with no session, which set none.</summary>
    public int SettingsRestored =>
        HadSession ? RemodelSystemToggles.SettingCount - SettingsOutstanding.Count : 0;

    /// <summary>One sentence per thing the routine could not do, in the order it tried them.</summary>
    public IReadOnlyList<string> Failures { get; }

    /// <summary>True when the routine did all of it, or had nothing to do.</summary>
    public bool Succeeded => Failures.Count == 0;

    /// <summary>The outcome of a routine that found no session.</summary>
    public static RemodelSessionEnd NoSession(string reason) => new RemodelSessionEnd(reason);

    /// <summary>
    /// The outcome as ordered key and value pairs, every value a plain token: what
    /// <c>remodel.close</c>'s error carries as <c>detail</c> and what the teardown line writes, so
    /// the two cannot name a fact differently. <c>failed_check</c> is present only when a check
    /// failed; <c>settings_outstanding</c> is comma-separated and empty when all four are back.
    /// </summary>
    public IReadOnlyList<KeyValuePair<string, string>> Fields()
    {
        var fields = new List<KeyValuePair<string, string>>
        {
            Pair("reason", Reason),
            Pair("verified", Flag(Verified)),
        };

        if (FailedCheck.HasValue)
        {
            fields.Add(Pair("failed_check", ((int)FailedCheck.Value).ToString(CultureInfo.InvariantCulture)));
        }

        fields.Add(Pair("tag_removed", Flag(TagRemoved)));
        fields.Add(Pair("copy_closed", Flag(CopyClosed)));
        fields.Add(Pair("settings_restored", SettingsRestored.ToString(CultureInfo.InvariantCulture)));
        fields.Add(Pair("settings_outstanding", string.Join(",", SettingsOutstanding)));
        return fields;
    }

    private static KeyValuePair<string, string> Pair(string key, string value) =>
        new KeyValuePair<string, string>(key, value);

    private static string Flag(bool value) => value ? "true" : "false";

    private static string RequiredReason(string reason)
    {
        if (string.IsNullOrWhiteSpace(reason))
        {
            throw new ArgumentException(
                "A session ends for a reason; name it (remodel.close, tool_service_stopped).",
                nameof(reason));
        }

        return reason.Trim();
    }
}
