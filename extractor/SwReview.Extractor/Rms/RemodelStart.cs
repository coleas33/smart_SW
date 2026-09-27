using System;
using System.Collections.Generic;
using SwReview.Extractor.Bridge;

namespace SwReview.Extractor.Rms;

/// <summary>
/// 004 T172 (default taken 2026-09-26, the owner may revise; research R13.3): <b>Start is
/// switched off until the blocking probes pass.</b>
///
/// With the production seat (T157) the add-in can reach Start before the workstation has
/// verdicts on PROBE-1, 2, 3, 4 and 12, and PROBE-1 is exactly whether an illegal reorder's
/// "Cannot reorder" box hangs the application thread; Plan makes no reorder, Start does. So,
/// like <see cref="Sw.DrawingOpenScope.SeatValidated"/>, this build ships the switch off: Plan and
/// Discard run, and a Start is refused in plain words by the pane host
/// (<c>RemodelHost.StartNotValidatedMessage</c>) before any call - and, as the backstop, the
/// bridge answers the six change commands <see cref="RemodelErrorCodes.StartNotValidated"/>
/// before it verifies the target or writes anything (contracts/bridge-remodel.md, "The Start
/// switch"). A clause checked only by the caller is a clause the caller can skip.
///
/// <see cref="SeatValidated"/> is set true in a commit of its own that cites the capabilities
/// ledger's verdict for each of the five probes and edits the pin test beside it. The host and
/// the dispatcher take the switch as a constructor argument, defaulting to this value, so every
/// other test passes the switch it means.
/// </summary>
public static class RemodelStart
{
    /// <summary>
    /// False until the capabilities ledger records a seat's verdict on PROBE-1, 2, 3, 4 and 12
    /// (<c>verified</c>, or the owner's recorded decision for one that is not). A property rather
    /// than a constant, as <see cref="Sw.DrawingOpenScope.SeatValidated"/> is, so no branch on it
    /// is folded away and flagged unreachable while it is false.
    /// </summary>
    public static bool SeatValidated => false;

    /// <summary>
    /// The six commands only a Start sends: every change to the copy, and the one save. The
    /// commands Plan and Discard use - <c>probe_scope</c>, <c>open</c>, <c>snapshot</c>,
    /// <c>rebuild</c>, <c>geometry</c> and <c>close</c> - are not here, so they run whichever way
    /// the switch is set.
    /// </summary>
    public static readonly IReadOnlyList<string> ChangeCommands = new[]
    {
        RemodelCommands.Rename,
        RemodelCommands.Reorder,
        RemodelCommands.Folder,
        RemodelCommands.Describe,
        RemodelCommands.Equation,
        RemodelCommands.Save,
    };

    /// <summary>Whether <paramref name="command"/> is one of <see cref="ChangeCommands"/>, by exact name.</summary>
    public static bool IsChangeCommand(string? command)
    {
        if (command == null)
        {
            return false;
        }

        foreach (string change in ChangeCommands)
        {
            if (string.Equals(change, command, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }
}
