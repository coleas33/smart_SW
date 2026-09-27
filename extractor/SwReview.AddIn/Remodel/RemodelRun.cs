using System;
using System.Threading;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// What the executor is bounded by, as `init.limits` reports them
/// (`contracts/run-artifacts.md`, "Limits").
///
/// They are the <b>executor's</b>, reported to the page and never taken from it. A page that
/// could raise <see cref="MaxChanges"/> would be a page that could ask for five thousand
/// writes into a document, which is exactly the bound these exist to be; and hitting one is a
/// `truncated` run that says so, never a silent partial success.
/// </summary>
public sealed class RemodelLimits
{
    /// <summary>The values stage 1 ships with.</summary>
    public static readonly RemodelLimits Default = new RemodelLimits(250, 20, 120);

    public RemodelLimits(int maxChanges, int maxMinutes, int maxRebuildSeconds)
    {
        MaxChanges = maxChanges;
        MaxMinutes = maxMinutes;
        MaxRebuildSeconds = maxRebuildSeconds;
    }

    public int MaxChanges { get; }

    /// <summary>Wall clock for the whole run.</summary>
    public int MaxMinutes { get; }

    /// <summary>Wall clock for one rebuild.</summary>
    public int MaxRebuildSeconds { get; }
}

/// <summary>Where a run this host started is, as the host itself sees it.</summary>
public enum RemodelRunPhase
{
    /// <summary>Planned and waiting for `remodel.start`.</summary>
    Planned,

    /// <summary>Between `remodel.start` and the executor returning. One at a time.</summary>
    Running,

    /// <summary>The executor returned, whatever it returned.</summary>
    Finished,
}

/// <summary>
/// One re-modeler run this host started: the folder, the copy, and the one flag that can stop
/// it.
///
/// The run's <b>state</b> is deliberately not here. `plan.json` carries it, rewritten at every
/// transition, and `remodel.result` reads it from there, so the pane and the artifacts cannot
/// disagree and a run interrupted by a crash still answers (data-model.md section 11). What
/// this type holds is only what the host needs to answer a message: which folder the page's
/// `run_dir` resolves to, where the copy is, and whether a stop has been asked for.
///
/// <see cref="RunId"/> is the run folder's own name, which is also the chat id
/// `remodel.started` replies with - the same "one id" rule feature 003's `CheckRecord` follows,
/// so a page holding a run's result can address its folder, its events and its report without
/// a second identifier to keep in step.
/// </summary>
public sealed class RemodelRun
{
    private int _stop;
    private int _planLostNotice;
    private bool _closedByPlanAgain;
    private bool _sessionClosedAtPlan;

    internal RemodelRun(
        string runDirectory, string copyPath, DateTime at, string? toolServiceAttachment)
    {
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        CopyPath = copyPath ?? throw new ArgumentNullException(nameof(copyPath));
        At = at;
        ToolServiceAttachment = toolServiceAttachment;
        RunId = System.IO.Path.GetFileName(runDirectory.TrimEnd(
            System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar));
    }

    /// <summary>The run folder's name, `&lt;yyyyMMdd-HHmmss&gt;-&lt;doc&gt;-remodel`.</summary>
    public string RunId { get; }

    public string RunDirectory { get; }

    /// <summary>The copy, which lives only under <see cref="RunDirectory"/>.</summary>
    public string CopyPath { get; }

    /// <summary>When the run was planned, as `init.latest_run.at` carries it.</summary>
    public DateTime At { get; }

    /// <summary>
    /// The tool-service attachment this run's plan was made on, or null when none was
    /// listening (decision 22A). The bridge session that holds the copy lives and dies with
    /// that attachment, so `remodel.start` refuses the run as `SessionLost` unless it is the
    /// attachment listening now. Set once, at the plan, and never moved to a later attachment.
    /// </summary>
    public string? ToolServiceAttachment { get; }

    public RemodelRunPhase Phase { get; internal set; } = RemodelRunPhase.Planned;

    /// <summary>Whether the engineer has discarded this run's copy.</summary>
    public bool CopyDiscarded { get; internal set; }

    /// <summary>
    /// 004 T173: whether this plan was closed because the engineer planned again while it waited
    /// for Start. A plan marked so is lost - its session is over - whatever attachment is
    /// listening, and a Start naming it is `SessionLost` with <c>RemodelHost.PlanClosedMessage</c>.
    /// Set once, by the host that planned again, and never cleared: the session it names is gone.
    /// Volatile because it is read on the tool service's refresh thread as well as the message
    /// thread that sets it.
    /// </summary>
    public bool ClosedByPlanAgain => Volatile.Read(ref _closedByPlanAgain);

    internal void MarkClosedByPlanAgain() => Volatile.Write(ref _closedByPlanAgain, true);

    /// <summary>
    /// 004 T176 (default taken 2026-09-27, the owner may revise; research R14.2): whether the host
    /// ended this plan's bridge session as soon as the plan was made, because Start is switched off
    /// in this build and no Start could use it, and the bridge answered that close. A plan marked
    /// so holds no session: no close is sent for it again - not by Discard, not by planning again -
    /// and it is <b>not</b> lost, since nothing it needs went away. Set once, by the host that
    /// planned it, and never cleared. Volatile for the reason <see cref="ClosedByPlanAgain"/> is.
    /// </summary>
    public bool SessionClosedAtPlan => Volatile.Read(ref _sessionClosedAtPlan);

    internal void MarkSessionClosedAtPlan() => Volatile.Write(ref _sessionClosedAtPlan, true);

    /// <summary>
    /// Whether a stop has been asked for, by `remodel.stop` or by the copy going away
    /// mid-run.
    ///
    /// Read by the executor between changes, which is the whole mechanism: the change in
    /// flight is finished, inverted if it failed, and the artifacts are finalized. Nothing is
    /// killed mid-write, because a write killed halfway through is the one state no undo tier
    /// can describe. Interlocked because the flag is set on the message thread and read on the
    /// worker the run is executing on.
    /// </summary>
    public bool StopRequested => Interlocked.CompareExchange(ref _stop, 0, 0) != 0;

    internal void RequestStop() => Interlocked.Exchange(ref _stop, 1);

    /// <summary>
    /// Claims the one `remodel.plan_lost` this run's plan is told with (decision 24A): true the
    /// first time, false ever after. The attachment a plan was made on never comes back -
    /// every start mints a new one - so a plan lost once is lost for good, and every refresh
    /// after the first finds it lost again. Interlocked because the refreshes arrive on the
    /// tool service's thread and the end of a plan on the message thread.
    /// </summary>
    internal bool ClaimPlanLostNotice() => Interlocked.Exchange(ref _planLostNotice, 1) == 0;
}
