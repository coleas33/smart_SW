using System;
using System.Collections.Generic;
using System.Globalization;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The four settings <see cref="RemodelSystemToggles"/> reads, sets and restores, and nothing
/// else, so the set-and-restore is testable without a SOLIDWORKS seat.
///
/// Three of them are <c>swUserPreferenceToggle_e</c> values reached through
/// <c>ISldWorks.GetUserPreferenceToggle</c> and <c>ISldWorks.SetUserPreferenceToggle</c> (both
/// VERIFIED). The fourth is <c>ISldWorks.CommandInProgress</c>, a plain property, which is why
/// it has its own pair of members here and its own allowlist key,
/// <c>ISldWorks.set_CommandInProgress</c>, rather than riding on the toggle member
/// (research R5.6, contracts/guard-allowlist.md).
/// </summary>
public interface IRemodelToggleHost
{
    /// <summary><c>ISldWorks.GetUserPreferenceToggle(toggle)</c>.</summary>
    bool GetUserPreferenceToggle(int toggle);

    /// <summary><c>ISldWorks.SetUserPreferenceToggle(toggle, value)</c>.</summary>
    void SetUserPreferenceToggle(int toggle, bool value);

    /// <summary><c>ISldWorks.get_CommandInProgress()</c>.</summary>
    bool GetCommandInProgress();

    /// <summary><c>ISldWorks.set_CommandInProgress(value)</c>.</summary>
    void SetCommandInProgress(bool value);
}

/// <summary>
/// T053. The three system toggles and the one application flag a run sets, and restores in a
/// <c>finally</c> (research R5.6).
///
/// Every one of them is a dialog, and in an add-in a dialog is a <b>hang</b>, not an error: the
/// message box opens on the SOLIDWORKS thread the run is holding and nothing answers it.
///
///   - <c>swInputDimValOnCreate = 10</c>: leaving it on is recorded upstream as "the single most
///     expensive failure in this repo's history" - every dimension call opens a modal and the
///     script appears to hang;
///   - <c>swShowErrorsEveryRebuild = 77</c>: a rebuild with errors raises What's Wrong;
///   - <c>swWarnSaveUpdateErrors = 329</c>: the "save anyway?" dialog;
///   - <c>CommandInProgress = true</c>: PROBE-1's modal suppression for a refused
///     <c>ReorderFeature</c>, which returns a bare <c>false</c> with no code and may raise
///     "Cannot reorder" on the STA thread. <b>UNVERIFIED that it suppresses that box, and that
///     is blocking</b>; if PROBE-1 fails, stage 1 cannot run unattended.
///
/// <b>All four are read before any of them is set.</b> A value that could not be read refuses
/// the start rather than being guessed: a guessed "restore" leaves the engineer's SOLIDWORKS in
/// a state nobody chose, which is the class of silent write this feature exists to make
/// impossible. For the same reason a set that fails halfway puts back the ones that already
/// landed before it raises.
///
/// Recovery of a previous run's leftovers is the same sequence and not a special case: the
/// recovering run reads what is <b>actually</b> there, records that as the original, and
/// restores to it. Nothing in this process knows what the engineer had before the run that died.
/// </summary>
public sealed class RemodelSystemToggles
{
    /// <summary><c>swUserPreferenceToggle_e.swInputDimValOnCreate</c> (VERIFIED value 10).</summary>
    public const int InputDimValOnCreate = (int)swUserPreferenceToggle_e.swInputDimValOnCreate;

    /// <summary><c>swUserPreferenceToggle_e.swShowErrorsEveryRebuild</c> (VERIFIED value 77).</summary>
    public const int ShowErrorsEveryRebuild = (int)swUserPreferenceToggle_e.swShowErrorsEveryRebuild;

    /// <summary><c>swUserPreferenceToggle_e.swWarnSaveUpdateErrors</c> (VERIFIED value 329).</summary>
    public const int WarnSaveUpdateErrors = (int)swUserPreferenceToggle_e.swWarnSaveUpdateErrors;

    /// <summary>
    /// <c>ISldWorks.SetUserPreferenceToggle</c>, as the gate is told about it: the
    /// interface-qualified stage-1 allowlist key of contracts/guard-allowlist.md. The three
    /// toggle writes change the engineer's application-wide settings, so they go through
    /// <see cref="SwGate"/> like every other write the re-modeler makes.
    /// </summary>
    public const string ToggleMember = "ISldWorks.SetUserPreferenceToggle";

    /// <summary>
    /// <c>ISldWorks.set_CommandInProgress</c>, as the gate is told about it. A property and
    /// not a <c>swUserPreferenceToggle_e</c> value, which is why it carries its own key.
    /// </summary>
    public const string CommandInProgressMember = "ISldWorks.set_CommandInProgress";

    /// <summary><c>ISldWorks.GetUserPreferenceToggle</c>: a read, gated by its bare name.</summary>
    public const string ReadToggleMember = "GetUserPreferenceToggle";

    /// <summary><c>ISldWorks.get_CommandInProgress</c>: a read, gated by its bare name.</summary>
    public const string ReadCommandInProgressMember = "get_CommandInProgress";

    /// <summary>
    /// The three toggles, in the order they are read, set and restored. Three, not four:
    /// <c>CommandInProgress</c> is a property and an entry here would be handed to
    /// <c>SetUserPreferenceToggle</c>, where the same integer means something else entirely.
    /// </summary>
    private static readonly int[] ToggleArray =
    {
        InputDimValOnCreate,
        ShowErrorsEveryRebuild,
        WarnSaveUpdateErrors,
    };

    /// <inheritdoc cref="ToggleArray" />
    public static readonly IReadOnlyList<int> SuppressedToggles = ToggleArray;

    private readonly IRemodelToggleHost _host;
    private readonly SwGate _gate;
    private readonly Dictionary<int, bool> _originalToggles;
    private readonly bool _originalCommandInProgress;

    /// <summary>
    /// What is still holding the run's value. A setting leaves this set when its original
    /// value is <b>actually back</b>, never when a restore was merely attempted: a restore
    /// that threw halfway must be finishable by the next one, and "restored" is a fact about
    /// the seat rather than about how many times <see cref="Restore"/> was called.
    /// </summary>
    private readonly HashSet<int> _pendingToggles;
    private bool _pendingCommandInProgress;

    private RemodelSystemToggles(
        IRemodelToggleHost host,
        SwGate gate,
        Dictionary<int, bool> originalToggles,
        bool originalCommandInProgress)
    {
        _host = host;
        _gate = gate;
        _originalToggles = originalToggles;
        _originalCommandInProgress = originalCommandInProgress;
        _pendingToggles = new HashSet<int>();
    }

    /// <summary>The value <paramref name="toggle"/> had before the run set it.</summary>
    public bool OriginalToggle(int toggle) => _originalToggles[toggle];

    /// <summary>The value <c>CommandInProgress</c> had before the run set it.</summary>
    public bool OriginalCommandInProgress => _originalCommandInProgress;

    /// <summary>
    /// Reads all four, then sets all four. Nothing is set unless every original value was read,
    /// and nothing stays set if any set fails.
    /// </summary>
    public static RemodelSystemToggles Apply(IRemodelToggleHost host, SwGate gate)
    {
        if (host == null)
        {
            throw new ArgumentNullException(nameof(host));
        }

        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        var originals = new Dictionary<int, bool>(ToggleArray.Length);
        foreach (int toggle in ToggleArray)
        {
            originals[toggle] = Read(
                () => gate.Call(ReadToggleMember, () => host.GetUserPreferenceToggle(toggle)),
                "swUserPreferenceToggle_e " + toggle.ToString(CultureInfo.InvariantCulture));
        }

        bool commandInProgress = Read(
            () => gate.Call(ReadCommandInProgressMember, host.GetCommandInProgress),
            "ISldWorks.CommandInProgress");

        var applied = new RemodelSystemToggles(host, gate, originals, commandInProgress);
        applied.Suppress();
        return applied;
    }

    /// <summary>
    /// <see cref="Apply"/>, <paramref name="body"/>, and <see cref="Restore"/> in a
    /// <c>finally</c>. The <c>finally</c> is written once, here, so no caller can forget it -
    /// including the caller that is unwinding from a failed run, which is the one that matters.
    /// </summary>
    public static void Within(IRemodelToggleHost host, SwGate gate, Action body)
    {
        if (body == null)
        {
            throw new ArgumentNullException(nameof(body));
        }

        RemodelSystemToggles applied = Apply(host, gate);
        try
        {
            body();
        }
        finally
        {
            applied.Restore();
        }
    }

    /// <summary>
    /// Puts every original value back, and <b>attempts all four whatever any one of them
    /// does</b>: a write that throws must not take the remaining three with it. The one that
    /// matters most is <c>CommandInProgress</c>, written last - left <c>true</c> it suppresses
    /// modals for the rest of the engineer's SOLIDWORKS session.
    ///
    /// Failures are collected and raised together as an <see cref="AggregateException"/>, so
    /// the caller hears about every setting that is still holding the run's value.
    ///
    /// Idempotent, and recoverable by the same mechanism: a setting leaves the pending set
    /// when its original value is actually back, so a second call writes only what is still
    /// outstanding - nothing at all after a restore that finished, and the remainder after
    /// one that did not.
    /// </summary>
    public void Restore()
    {
        if (_pendingToggles.Count == 0 && !_pendingCommandInProgress)
        {
            return;
        }

        List<Exception>? failures = null;

        foreach (int toggle in ToggleArray)
        {
            if (!_pendingToggles.Contains(toggle))
            {
                continue;
            }

            try
            {
                PutBack(
                    ToggleMember,
                    () => _host.SetUserPreferenceToggle(toggle, _originalToggles[toggle]));
                _pendingToggles.Remove(toggle);
            }
            catch (Exception error)
            {
                failures = failures ?? new List<Exception>();
                failures.Add(error);
            }
        }

        if (_pendingCommandInProgress)
        {
            try
            {
                PutBack(
                    CommandInProgressMember,
                    () => _host.SetCommandInProgress(_originalCommandInProgress));
                _pendingCommandInProgress = false;
            }
            catch (Exception error)
            {
                failures = failures ?? new List<Exception>();
                failures.Add(error);
            }
        }

        if (failures != null)
        {
            throw new AggregateException(
                "the engineer's SOLIDWORKS settings were not all put back: "
                + failures.Count.ToString(CultureInfo.InvariantCulture)
                + " of the four writes failed. The ones that landed are back; the rest are "
                + "still holding the run's value, and the next Restore() retries them.",
                failures);
        }
    }

    /// <summary>
    /// Turns the three dialogs off and the command flag on, putting back anything that already
    /// landed if one of them fails.
    /// </summary>
    private void Suppress()
    {
        var landed = new List<int>(ToggleArray.Length);
        try
        {
            foreach (int toggle in ToggleArray)
            {
                _gate.Call(ToggleMember, () => _host.SetUserPreferenceToggle(toggle, false));
                landed.Add(toggle);
                _pendingToggles.Add(toggle);
            }

            _gate.Call(CommandInProgressMember, () => _host.SetCommandInProgress(true));
            _pendingCommandInProgress = true;
        }
        catch (Exception)
        {
            foreach (int toggle in landed)
            {
                PutBack(
                    ToggleMember,
                    () => _host.SetUserPreferenceToggle(toggle, _originalToggles[toggle]));
                _pendingToggles.Remove(toggle);
            }

            throw;
        }
    }

    /// <summary>
    /// One put-back write: the guard and the observer, and <b>not</b> the circuit breaker.
    ///
    /// <see cref="SwGate.Assert"/> rather than <see cref="SwGate.Call{T}"/> because the run
    /// that most needs its settings put back is the run that killed the session, and a call
    /// counted against an open circuit would be refused before it reached the seat - leaving
    /// <c>CommandInProgress</c> set for the rest of the engineer's SOLIDWORKS session. The
    /// guard still judges the key and the observer still records it, so the write is on the
    /// audited <c>gated=</c> set either way.
    /// </summary>
    private void PutBack(string key, Action write)
    {
        _gate.Assert(key);
        write();
    }

    /// <summary>
    /// One original value. A seat that will not answer refuses the start, naming the setting,
    /// rather than handing back a value nobody measured.
    /// </summary>
    private static bool Read(Func<bool> read, string named)
    {
        try
        {
            return read();
        }
        catch (Exception error)
        {
            throw new InvalidOperationException(
                $"the original value of {named} could not be read, so the run refuses to start: "
                + "restoring a value that was never measured is a silent write to the engineer's "
                + $"settings. The seat said: {error.Message}",
                error);
        }
    }
}
