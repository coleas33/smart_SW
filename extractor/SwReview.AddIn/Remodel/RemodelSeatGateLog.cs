using System;
using System.Text;
using SwReview.AddIn.ToolService;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// Owner decision 144A (feature 011, research R11): the gate log of one action of the re-modeler's
/// pane seat (<see cref="SwRemodelSeat"/>) - what its gate was asked about, what its guard refused and
/// how the action ended - as lines of the run folder's <c>remodel.log</c>, beside the lines the tool
/// service writes there for the bridge's <c>remodel.*</c> requests (<see cref="RemodelRunLog"/>).
///
/// Two lines per action. <c>seat=&lt;action&gt; begin</c> before its first call, so an action
/// SOLIDWORKS never returns from still leaves a line, as every bridge request's begin line does (U27).
/// Then <c>seat=&lt;action&gt; status=ok outcome=&lt;outcome&gt; gated=&lt;members&gt;</c>, or
/// <c>status=error gated=&lt;members&gt;</c> with <c> error=&lt;exception type&gt;</c> at the end, and
/// <c> refused=&lt;members&gt;</c> before it when the guard refused any. The members are the distinct
/// names the gate was asked about, in the order it first saw them, which is what the tool service's
/// request line holds (<see cref="SwGateRecorder"/>, whose sets this keeps). No path is written: the
/// copy is the run folder's own, and an exception's message, which may quote a path, stays on the pane.
///
/// One per action, never shared: it is the gate's observer for that one call of the seat, on the
/// application thread, and it tells the observer it was built with, if any, everything it is told.
/// </summary>
internal sealed class RemodelSeatGateLog : ISwGateObserver
{
    private readonly SwGateRecorder _recorder = new SwGateRecorder();
    private readonly ISwGateObserver? _also;

    /// <param name="also">Told everything this log is told; null for none.</param>
    public RemodelSeatGateLog(ISwGateObserver? also)
    {
        _also = also;
    }

    /// <summary>The line written before an action's first call.</summary>
    public static string BeginLine(string action) => "seat=" + action + " begin";

    /// <inheritdoc />
    public void Gated(string interopMember)
    {
        _recorder.Gated(interopMember);
        _also?.Gated(interopMember);
    }

    /// <inheritdoc />
    public void Refused(MutatingCallError refusal)
    {
        _recorder.Refused(refusal);
        _also?.Refused(refusal);
    }

    /// <summary>The line for <paramref name="action"/> once it is done, unstamped, and this log emptied.</summary>
    /// <param name="action">The seat's name for what it was asked to do.</param>
    /// <param name="outcome">How the action ended, when it returned; not written when it threw.</param>
    /// <param name="failure">What the action threw, or null when it returned.</param>
    public string Line(string action, string? outcome, Exception? failure)
    {
        SwGateActivity activity = _recorder.Drain();

        var line = new StringBuilder(112);
        line.Append("seat=").Append(action);
        line.Append(" status=").Append(failure == null ? "ok" : "error");
        if (failure == null && !string.IsNullOrEmpty(outcome))
        {
            line.Append(" outcome=").Append(outcome);
        }

        line.Append(" gated=").Append(string.Join(",", activity.GatedMembers));

        if (activity.RefusedMembers.Count > 0)
        {
            line.Append(" refused=").Append(string.Join(",", activity.RefusedMembers));
        }

        if (failure != null)
        {
            line.Append(" error=").Append(failure.GetType().Name);
        }

        return line.ToString();
    }

    /// <summary>
    /// A line written to <paramref name="runDirectory"/>'s <c>remodel.log</c>, stamped as every line of
    /// that file is. <see cref="RemodelRunLog"/> never throws for a folder it cannot write to: a log that
    /// cannot be written must not fail the action it describes.
    /// </summary>
    public static void Write(string runDirectory, string line) =>
        new RemodelRunLog(() => runDirectory).WriteLine(line);
}
